from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Any, Dict, Optional

from config import get_config
from core.ao_manager import AOManager
from core.contracts import (
    ClarificationContract,
    ContractContext,
    DependencyContract,
    OASCContract,
)
from core.router import RouterResponse, UnifiedRouter
from core.task_state import TaskStage, TaskState
from core.tool_dependencies import get_tool_provides
from services.config_loader import ConfigLoader

logger = logging.getLogger(__name__)


class GovernedRouter:
    """Thin contract orchestrator over UnifiedRouter."""

    def __init__(self, session_id: str, memory_storage_dir: Optional[str | Path] = None):
        self.session_id = session_id
        self.runtime_config = get_config()
        self.inner_router = UnifiedRouter(
            session_id=session_id,
            memory_storage_dir=memory_storage_dir,
        )
        self.ao_manager = AOManager(self.inner_router.memory.fact_memory)
        self.oasc_contract = OASCContract(
            inner_router=self.inner_router,
            ao_manager=self.ao_manager,
            runtime_config=self.runtime_config,
        )
        self.clarification_contract = ClarificationContract(
            inner_router=self.inner_router,
            ao_manager=self.ao_manager,
            runtime_config=self.runtime_config,
        )
        self.dependency_contract = DependencyContract()
        self.contracts = [
            self.oasc_contract,
            self.clarification_contract,
            self.dependency_contract,
        ]

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner_router, name)

    async def chat(
        self,
        user_message: str,
        file_path: Optional[str] = None,
        trace: Optional[Dict[str, Any]] = None,
    ) -> RouterResponse:
        context = ContractContext(
            user_message=user_message,
            file_path=str(file_path) if file_path else None,
            trace=trace,
        )

        result: Optional[RouterResponse] = None
        for contract in self.contracts:
            interception = await contract.before_turn(context)
            if interception.user_message_override is not None:
                context.user_message_override = interception.user_message_override
            if interception.metadata:
                context.metadata.update(interception.metadata)
            if not interception.proceed:
                result = interception.response or RouterResponse(text="")
                break

        if result is None:
            result = await self._maybe_execute_from_snapshot(context)
            if result is None:
                clarification_state = dict(context.metadata.get("clarification") or {})
                telemetry = clarification_state.get("telemetry")
                if isinstance(telemetry, dict) and telemetry.get("final_decision") == "proceed":
                    telemetry["proceed_mode"] = "fallback"
                    clarification_state["telemetry"] = telemetry
                    context.metadata["clarification"] = clarification_state
                result = await self.inner_router.chat(
                    user_message=context.effective_user_message,
                    file_path=file_path,
                    trace=trace,
                )
                context.router_executed = True
            else:
                context.router_executed = True

        for contract in self.contracts:
            await contract.after_turn(context, result)

        return result

    async def _maybe_execute_from_snapshot(self, context: ContractContext) -> Optional[RouterResponse]:
        clarification_state = dict(context.metadata.get("clarification") or {})
        direct_execution = clarification_state.get("direct_execution")
        telemetry = clarification_state.get("telemetry")
        if not isinstance(direct_execution, dict):
            return None

        tool_name = str(direct_execution.get("tool_name") or "").strip()
        snapshot = direct_execution.get("parameter_snapshot")
        allow_factor_year_default = bool(
            tool_name == "query_emission_factors"
            and str(direct_execution.get("trigger_mode") or "") == "fresh"
            and not bool(direct_execution.get("confirm_first_detected"))
        )
        if not tool_name or not isinstance(snapshot, dict):
            return None

        response = await self._execute_from_snapshot(
            tool_name=tool_name,
            snapshot=snapshot,
            allow_factor_year_default=allow_factor_year_default,
            user_message=context.user_message,
            file_path=context.file_path,
            state_snapshot=context.state_snapshot,
            trace=context.trace,
        )
        if response is None:
            if isinstance(telemetry, dict):
                telemetry["proceed_mode"] = "fallback"
                clarification_state["telemetry"] = telemetry
                context.metadata["clarification"] = clarification_state
            return None

        self._retain_pending_followups_after_direct_execution(
            snapshot=snapshot,
            used_runtime_defaults=(
                ["model_year"]
                if allow_factor_year_default and self._snapshot_missing_value(snapshot, "model_year")
                else []
            ),
        )
        self._mark_parameter_collection_complete()
        if isinstance(telemetry, dict):
            telemetry["proceed_mode"] = "snapshot_direct"
            clarification_state["telemetry"] = telemetry
            context.metadata["clarification"] = clarification_state
        return response

    async def _execute_from_snapshot(
        self,
        *,
        tool_name: str,
        snapshot: Dict[str, Any],
        allow_factor_year_default: bool,
        user_message: str,
        file_path: Optional[str],
        state_snapshot: Optional[Any],
        trace: Optional[Dict[str, Any]],
    ) -> Optional[RouterResponse]:
        arguments = self._snapshot_to_tool_args(
            tool_name,
            snapshot,
            allow_factor_year_default=allow_factor_year_default,
        )
        if not isinstance(arguments, dict):
            return None

        self.inner_router._ensure_context_store().clear_current_turn()
        result = await self.inner_router.executor.execute(
            tool_name=tool_name,
            arguments=arguments,
            file_path=file_path,
        )
        if not bool(result.get("success")):
            return None

        self.inner_router._save_result_to_session_context(tool_name, result)

        tool_result = {
            "tool_call_id": f"clarification_contract_{tool_name}_{time.time_ns()}",
            "name": tool_name,
            "arguments": dict(arguments),
            "result": result,
        }

        state = state_snapshot or TaskState.initialize(
            user_message=user_message,
            file_path=file_path,
            memory_dict=self.inner_router.memory.get_fact_memory(),
            session_id=self.session_id,
        )
        state.stage = TaskStage.DONE
        state.user_message = user_message
        state.execution.selected_tool = tool_name
        state.execution.tool_results = [tool_result]
        state.execution.completed_tools = [tool_name]
        state.execution.available_results.update(get_tool_provides(tool_name))
        state.execution.last_error = None
        state._llm_response = None
        state._assembled_context = type("StateContext", (), {"messages": [{"content": user_message}]})()
        setattr(state, "_final_response_text", None)

        response = await self.inner_router._state_build_response(
            state,
            user_message,
            trace_obj=None,
        )
        if not result.get("success"):
            return None

        self.inner_router.memory.update(
            user_message=user_message,
            assistant_response=response.text,
            tool_calls=response.executed_tool_calls,
            file_path=file_path,
            file_analysis=(
                self.inner_router.memory.fact_memory.file_analysis
                if isinstance(self.inner_router.memory.fact_memory.file_analysis, dict)
                else None
            ),
        )

        if trace is not None:
            trace.setdefault("steps", []).append(
                {
                    "step_type": "tool_execution",
                    "action": "clarification_contract_snapshot_direct",
                    "output_summary": {
                        "tool_name": tool_name,
                        "arguments": dict(arguments),
                        "success": True,
                    },
                }
            )
            if response.trace is None:
                response.trace = trace
            elif isinstance(response.trace, dict):
                response.trace.setdefault("steps", []).extend(trace.get("steps") or [])
        return response

    def _retain_pending_followups_after_direct_execution(
        self,
        *,
        snapshot: Dict[str, Any],
        used_runtime_defaults: list[str],
    ) -> None:
        if not used_runtime_defaults:
            return
        current_ao = self.ao_manager.get_current_ao()
        if current_ao is None or not isinstance(current_ao.metadata, dict):
            return
        clarification_state = current_ao.metadata.get("clarification_contract")
        if not isinstance(clarification_state, dict):
            return
        followup_slots = [
            str(item)
            for item in list(clarification_state.get("followup_slots") or [])
            if str(item).strip()
        ]
        pending_slots = [
            slot_name
            for slot_name in followup_slots
            if slot_name in used_runtime_defaults and self._snapshot_missing_value(snapshot, slot_name)
        ]
        if not pending_slots:
            return
        clarification_state["pending"] = True
        clarification_state["missing_slots"] = pending_slots
        current_ao.metadata["clarification_contract"] = clarification_state

    def _mark_parameter_collection_complete(self) -> None:
        if not getattr(self.runtime_config, "enable_ao_first_class_state", True):
            return
        current_ao = self.ao_manager.get_current_ao()
        if current_ao is None:
            return
        parameter_state = getattr(current_ao, "parameter_state", None)
        if parameter_state is None:
            return
        parameter_state.collection_mode = False
        parameter_state.awaiting_slot = None
        parameter_state.probe_turn_count = 0
        parameter_state.probe_abandoned = False

    @staticmethod
    def _snapshot_missing_value(snapshot: Dict[str, Any], slot_name: str) -> bool:
        payload = snapshot.get(slot_name)
        if not isinstance(payload, dict):
            return True
        if payload.get("source") == "rejected":
            return True
        return payload.get("value") in (None, "", [])

    @staticmethod
    def _snapshot_to_tool_args(
        tool_name: str,
        snapshot: Dict[str, Any],
        *,
        allow_factor_year_default: bool = False,
    ) -> Dict[str, Any]:
        def as_list(value: Any) -> Optional[list[Any]]:
            if value is None:
                return None
            if isinstance(value, list):
                return list(value)
            return [value]

        def read(slot_name: str):
            payload = snapshot.get(slot_name)
            if not isinstance(payload, dict):
                return None
            source = str(payload.get("source") or "").strip().lower()
            value = payload.get("value")
            if source in {"missing", "rejected"}:
                return None
            if isinstance(value, str) and value.strip().lower() in {"missing", "unknown", "none", "n/a", "null", ""}:
                return None
            return value

        def safe_int(value: Any, slot_name: str) -> Optional[int]:
            if value is None:
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                logger.warning("Snapshot type coercion failed for %s=%r", slot_name, value)
                return None

        args: Dict[str, Any] = {}
        if tool_name == "query_emission_factors":
            if read("vehicle_type") is not None:
                args["vehicle_type"] = read("vehicle_type")
            pollutants = as_list(read("pollutants"))
            if pollutants is not None:
                args["pollutants"] = pollutants
            model_year = safe_int(read("model_year"), "model_year")
            if model_year is not None:
                args["model_year"] = model_year
            elif allow_factor_year_default:
                defaults = dict((ConfigLoader.load_mappings() or {}).get("defaults") or {})
                default_model_year = safe_int(defaults.get("model_year"), "model_year")
                if default_model_year is not None:
                    args["model_year"] = default_model_year
            if read("season") is not None:
                args["season"] = read("season")
            if read("road_type") is not None:
                args["road_type"] = read("road_type")
            return args
        if tool_name == "calculate_micro_emission":
            if read("vehicle_type") is not None:
                args["vehicle_type"] = read("vehicle_type")
            pollutants = as_list(read("pollutants"))
            if pollutants is not None:
                args["pollutants"] = pollutants
            model_year = safe_int(read("model_year"), "model_year")
            if model_year is not None:
                args["model_year"] = model_year
            if read("season") is not None:
                args["season"] = read("season")
            return args
        if tool_name == "calculate_macro_emission":
            pollutants = as_list(read("pollutants"))
            if pollutants is not None:
                args["pollutants"] = pollutants
            if read("season") is not None:
                args["season"] = read("season")
            if read("scenario_label") is not None:
                args["scenario_label"] = read("scenario_label")
            return args
        if tool_name == "calculate_dispersion":
            if read("meteorology") is not None:
                args["meteorology"] = read("meteorology")
            if read("pollutant") is not None:
                args["pollutant"] = read("pollutant")
            else:
                pollutants = as_list(read("pollutants"))
                if pollutants:
                    args["pollutant"] = pollutants[0]
            if read("scenario_label") is not None:
                args["scenario_label"] = read("scenario_label")
            return args
        if tool_name == "analyze_hotspots":
            if read("method") is not None:
                args["method"] = read("method")
            if read("percentile") is not None:
                args["percentile"] = read("percentile")
            if read("scenario_label") is not None:
                args["scenario_label"] = read("scenario_label")
            return args
        if tool_name == "render_spatial_map":
            if read("pollutant") is not None:
                args["pollutant"] = read("pollutant")
            else:
                pollutants = as_list(read("pollutants"))
                if pollutants:
                    args["pollutant"] = pollutants[0]
            if read("scenario_label") is not None:
                args["scenario_label"] = read("scenario_label")
            return args
        return {}

    def to_persisted_state(self) -> Dict[str, Any]:
        return self.inner_router.to_persisted_state()

    def restore_persisted_state(self, payload: Dict[str, Any]) -> None:
        self.inner_router.restore_persisted_state(payload)
        self.ao_manager = AOManager(self.inner_router.memory.fact_memory)
        self.oasc_contract = OASCContract(
            inner_router=self.inner_router,
            ao_manager=self.ao_manager,
            runtime_config=self.runtime_config,
        )
        self.clarification_contract = ClarificationContract(
            inner_router=self.inner_router,
            ao_manager=self.ao_manager,
            runtime_config=self.runtime_config,
        )
        self.contracts = [
            self.oasc_contract,
            self.clarification_contract,
            self.dependency_contract,
        ]


def build_router(
    session_id: str,
    *,
    memory_storage_dir: Optional[str | Path] = None,
    router_mode: str = "router",
) -> Any:
    config = get_config()
    if router_mode == "governed_v2" or (
        router_mode == "router" and getattr(config, "enable_governed_router", False)
    ):
        return GovernedRouter(session_id=session_id, memory_storage_dir=memory_storage_dir)
    return UnifiedRouter(session_id=session_id, memory_storage_dir=memory_storage_dir)
