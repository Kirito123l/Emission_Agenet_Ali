from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Any, Dict, Optional

from config import get_config
from core.analytical_objective import ConversationalStance, StanceConfidence
from core.ao_manager import AOManager
from core.constraint_violation_writer import (
    ConstraintViolationWriter,
    normalize_cross_constraint_violation,
)
from core.context_store import SessionContextStore
from core.contracts import (
    ClarificationContract,
    ContractContext,
    DependencyContract,
    ExecutionReadinessContract,
    IntentResolutionContract,
    OASCContract,
    StanceResolutionContract,
)
from core.reply import LLMReplyError, LLMReplyParser, LLMReplyTimeout, ReplyContextBuilder
from core.router import RouterResponse, UnifiedRouter
from core.stance_resolver import StanceResolution, StanceResolver
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
        self.constraint_violation_writer = self._build_constraint_violation_writer()
        self.reply_context_builder = ReplyContextBuilder()
        self._reply_parser = LLMReplyParser(timeout_seconds=20.0)
        self.stance_resolver = StanceResolver(runtime_config=self.runtime_config)
        self.oasc_contract = OASCContract(
            inner_router=self.inner_router,
            ao_manager=self.ao_manager,
            runtime_config=self.runtime_config,
        )
        self.dependency_contract = DependencyContract()
        self._build_contracts()

    def _build_contracts(self) -> None:
        self.contract_split_enabled = bool(getattr(self.runtime_config, "enable_contract_split", False))
        self.clarification_contract = None
        self.intent_resolution_contract = None
        self.stance_resolution_contract = None
        self.execution_readiness_contract = None
        self.contracts = [self.oasc_contract]
        if self.contract_split_enabled:
            if bool(getattr(self.runtime_config, "enable_split_intent_contract", True)):
                self.intent_resolution_contract = IntentResolutionContract(
                    inner_router=self.inner_router,
                    ao_manager=self.ao_manager,
                    runtime_config=self.runtime_config,
                )
                self.contracts.append(self.intent_resolution_contract)
            if bool(getattr(self.runtime_config, "enable_split_stance_contract", True)):
                self.stance_resolution_contract = StanceResolutionContract(
                    inner_router=self.inner_router,
                    ao_manager=self.ao_manager,
                    runtime_config=self.runtime_config,
                )
                self.contracts.append(self.stance_resolution_contract)
            if bool(getattr(self.runtime_config, "enable_split_readiness_contract", True)):
                self.execution_readiness_contract = ExecutionReadinessContract(
                    inner_router=self.inner_router,
                    ao_manager=self.ao_manager,
                    runtime_config=self.runtime_config,
                )
                self.contracts.append(self.execution_readiness_contract)
        else:
            self.clarification_contract = ClarificationContract(
                inner_router=self.inner_router,
                ao_manager=self.ao_manager,
                runtime_config=self.runtime_config,
            )
            self.contracts.append(self.clarification_contract)
        self.contracts.append(self.dependency_contract)

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
            if (
                getattr(contract, "name", None) == "oasc"
                and self.contract_split_enabled
                and not bool(getattr(self.runtime_config, "enable_split_stance_contract", True))
            ):
                stance_metadata = self._apply_stance_resolution(context)
                if stance_metadata:
                    context.metadata["stance"] = stance_metadata
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

        self._record_constraint_violations_from_trace(
            result,
            trace,
            source_turn=self._current_turn_index() or self._current_turn_index(pre_call=True),
        )

        for contract in self.contracts:
            await contract.after_turn(context, result)

        if bool(getattr(self.runtime_config, "enable_reply_pipeline", True)):
            reply_context_builder = self.__dict__.get("reply_context_builder") or ReplyContextBuilder()
            reply_context = reply_context_builder.build(
                user_message=context.effective_user_message,
                router_text=result.text,
                trace_steps=self._trace_steps(result, trace),
                ao_manager=self.__dict__.get("ao_manager"),
                violation_writer=self.__dict__.get("constraint_violation_writer"),
                context_store=self._context_store_for_writer(),
                governance_metadata=context.metadata,
            )
            original_text = result.text
            result.text, reply_metadata = await self._generate_final_reply(reply_context)
            self._record_reply_generation_trace(
                result,
                trace,
                metadata=reply_metadata,
                router_text=original_text,
                final_text=result.text,
            )

        return result

    async def _generate_final_reply(self, ctx: Any) -> tuple[str, Dict[str, Any]]:
        runtime_config = self.__dict__.get("runtime_config") or get_config()
        if not bool(getattr(runtime_config, "enable_llm_reply_parser", True)):
            return ctx.router_text, {"mode": "legacy_render"}
        parser = self.__dict__.get("_reply_parser")
        if parser is None:
            return ctx.router_text, {
                "mode": "legacy_render",
                "reason": "reply_parser_uninitialized",
            }
        try:
            return await parser.parse(ctx)
        except (LLMReplyTimeout, LLMReplyError) as exc:
            logger.warning(
                "LLM reply parser failed (%s: %s), keeping router_text",
                type(exc).__name__,
                exc,
            )
            return ctx.router_text, {
                "mode": "fallback",
                "fallback": True,
                "reason": f"{type(exc).__name__}: {exc}",
            }

    @staticmethod
    def _record_reply_generation_trace(
        result: RouterResponse,
        trace: Optional[Dict[str, Any]],
        *,
        metadata: Dict[str, Any],
        router_text: str,
        final_text: str,
    ) -> None:
        trace_target = result.trace if isinstance(result.trace, dict) else trace
        if not isinstance(trace_target, dict):
            return
        trace_target.setdefault("steps", []).append(
            {
                "step_type": "reply_generation",
                "action": "llm_reply_parser",
                "input_summary": {
                    "router_text_chars": len(router_text or ""),
                },
                "output_summary": {
                    **dict(metadata or {}),
                    "reply_chars": len(final_text or ""),
                },
                "reasoning": "LLM reply parser generated final reply"
                if (metadata or {}).get("mode") == "llm"
                else "Router-rendered reply kept as legacy/fallback output",
            }
        )
        if result.trace is None:
            result.trace = trace_target
        if isinstance(result.trace_friendly, list):
            result.trace_friendly.append(
                {
                    "title": "回复生成 / Reply Generation",
                    "description": (
                        "LLM reply parser generated final reply"
                        if (metadata or {}).get("mode") == "llm"
                        else "Router-rendered reply kept as legacy/fallback output"
                    ),
                    "status": "warning" if (metadata or {}).get("fallback") else "success",
                    "step_type": "reply_generation",
                }
            )

    def _build_constraint_violation_writer(self) -> ConstraintViolationWriter:
        return ConstraintViolationWriter(
            self.ao_manager,
            self._context_store_for_writer(),
        )

    def _context_store_for_writer(self) -> SessionContextStore:
        if hasattr(self.inner_router, "_ensure_context_store"):
            return self.inner_router._ensure_context_store()
        context_store = getattr(self.inner_router, "context_store", None)
        if context_store is None:
            context_store = SessionContextStore()
            setattr(self.inner_router, "context_store", context_store)
        return context_store

    def _record_constraint_violations_from_trace(
        self,
        result: RouterResponse,
        trace: Optional[Dict[str, Any]],
        *,
        source_turn: int,
    ) -> None:
        steps = self._trace_steps(result, trace)
        if not steps:
            return

        seen = set()
        for severity, payload, timestamp in self._iter_constraint_violation_events(steps):
            try:
                record = normalize_cross_constraint_violation(
                    payload,
                    severity=severity,
                    source_turn=source_turn,
                    timestamp=timestamp,
                )
            except (TypeError, ValueError):
                logger.debug("Skipped malformed constraint violation payload: %s", payload)
                continue

            signature = (
                record.violation_type,
                record.severity,
                tuple(sorted((key, repr(value)) for key, value in record.involved_params.items())),
                record.source_turn,
            )
            if signature in seen:
                continue
            seen.add(signature)
            self.constraint_violation_writer.record(record)

    @staticmethod
    def _trace_steps(
        result: RouterResponse,
        trace: Optional[Dict[str, Any]],
    ) -> list[Dict[str, Any]]:
        result_trace = getattr(result, "trace", None)
        if isinstance(result_trace, dict) and isinstance(result_trace.get("steps"), list):
            return [item for item in result_trace.get("steps", []) if isinstance(item, dict)]
        if isinstance(trace, dict) and isinstance(trace.get("steps"), list):
            return [item for item in trace.get("steps", []) if isinstance(item, dict)]
        return []

    def _iter_constraint_violation_events(
        self,
        steps: list[Dict[str, Any]],
    ) -> list[tuple[str, Dict[str, Any], Optional[str]]]:
        events: list[tuple[str, Dict[str, Any], Optional[str]]] = []
        for step in steps:
            step_type = str(step.get("step_type") or "")
            timestamp = str(step.get("timestamp")) if step.get("timestamp") is not None else None
            if step_type == "cross_constraint_violation":
                for payload in self._extract_step_constraint_payloads(step):
                    events.append(("reject", payload, timestamp))
                continue
            if step_type == "cross_constraint_warning":
                for payload in self._extract_step_constraint_payloads(step):
                    events.append(("warn", payload, timestamp))
                continue

            for record in list(step.get("standardization_records") or []):
                if not isinstance(record, dict):
                    continue
                record_type = str(record.get("record_type") or record.get("strategy") or "")
                if record_type == "cross_constraint_violation":
                    events.append(("negotiate", record, timestamp))
                elif record_type == "cross_constraint_warning":
                    events.append(("warn", record, timestamp))
        return events

    @staticmethod
    def _extract_step_constraint_payloads(step: Dict[str, Any]) -> list[Dict[str, Any]]:
        payloads: list[Dict[str, Any]] = []
        for container_name in ("input_summary", "output_summary"):
            container = step.get(container_name)
            if not isinstance(container, dict):
                continue
            for key in ("cross_constraint_violations", "violations", "warnings"):
                values = container.get(key)
                if isinstance(values, list):
                    payloads.extend(item for item in values if isinstance(item, dict))

        for record in list(step.get("standardization_records") or []):
            if not isinstance(record, dict):
                continue
            nested = record.get("constraint_violation")
            payloads.append(nested if isinstance(nested, dict) else record)
        return payloads

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
        runtime_defaults_allowed = [
            str(item)
            for item in list(direct_execution.get("runtime_defaults_allowed") or [])
            if str(item).strip()
        ]
        if "model_year" in runtime_defaults_allowed and tool_name == "query_emission_factors":
            allow_factor_year_default = True
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
        if bool(getattr(self.runtime_config, "enable_contract_split", False)):
            return
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

    def _apply_stance_resolution(self, context: ContractContext) -> Dict[str, Any]:
        if not getattr(self.runtime_config, "enable_conversational_stance", True):
            return {}
        oasc_state = context.metadata.get("oasc") if isinstance(context.metadata.get("oasc"), dict) else {}
        classification = oasc_state.get("classification")
        if classification is None:
            return {}
        current_ao = self.ao_manager.get_current_ao()
        if current_ao is None:
            return {}
        if self.contract_split_enabled and not bool(
            getattr(self.runtime_config, "enable_split_stance_contract", True)
        ):
            turn = self._current_turn_index(pre_call=True)
            resolution = StanceResolution(
                stance=ConversationalStance.DIRECTIVE,
                confidence=StanceConfidence.LOW,
                evidence=["minimal_prior_directive"],
                resolved_by="minimal_prior_directive",
            )
            self._write_stance(current_ao, resolution, turn)
            return {
                "reversal_detected": False,
                "stance": resolution.stance.value,
                "resolved_by": resolution.resolved_by,
                "evidence": list(resolution.evidence),
            }
        classification_value = str(getattr(getattr(classification, "classification", None), "value", "") or "")
        turn = self._current_turn_index(pre_call=True)
        if classification_value in {"new_ao", "revision"}:
            fast = self.stance_resolver.resolve_fast(context.effective_user_message, current_ao)
            resolution = self.stance_resolver.resolve_with_llm_hint(fast, None)
            self._write_stance(current_ao, resolution, turn)
            return {
                "reversal_detected": False,
                "stance": resolution.stance.value,
                "resolved_by": resolution.resolved_by,
                "evidence": list(resolution.evidence),
            }
        if classification_value == "continuation":
            reversal = self.stance_resolver.detect_reversal(
                context.effective_user_message,
                current_ao.stance,
            )
            if reversal is None:
                return {"reversal_detected": False}
            evidence = self.stance_resolver.reversal_evidence(context.effective_user_message)
            resolution = StanceResolution(
                stance=reversal,
                confidence=current_ao.stance_confidence,
                evidence=[evidence or "user_reversal"],
                resolved_by="user_reversal",
            )
            self._write_stance(current_ao, resolution, turn)
            return {
                "reversal_detected": True,
                "stance": resolution.stance.value,
                "resolved_by": resolution.resolved_by,
                "evidence": list(resolution.evidence),
            }
        return {}

    @staticmethod
    def _write_stance(ao: Any, resolution: StanceResolution, turn: int) -> None:
        ao.stance = resolution.stance
        ao.stance_confidence = resolution.confidence
        ao.stance_resolved_by = resolution.resolved_by
        if not ao.stance_history or ao.stance_history[-1][1] != resolution.stance:
            ao.stance_history.append((turn, resolution.stance))

    def _current_turn_index(self, *, pre_call: bool = False) -> int:
        turn_counter = int(getattr(self.inner_router.memory, "turn_counter", 0) or 0)
        return turn_counter + 1 if pre_call else turn_counter

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
        self.constraint_violation_writer = self._build_constraint_violation_writer()
        self.stance_resolver = StanceResolver(runtime_config=self.runtime_config)
        self.oasc_contract = OASCContract(
            inner_router=self.inner_router,
            ao_manager=self.ao_manager,
            runtime_config=self.runtime_config,
        )
        self._build_contracts()


def build_router(
    session_id: str,
    *,
    memory_storage_dir: Optional[str | Path] = None,
    router_mode: str = "router",
) -> Any:
    normalized_mode = str(router_mode or "router").strip().lower()
    if normalized_mode in {"full", "governed_v2", "router"}:
        return GovernedRouter(session_id=session_id, memory_storage_dir=memory_storage_dir)
    if normalized_mode == "naive":
        raise ValueError("router_mode='naive' must construct NaiveRouter directly")
    raise ValueError(f"Unsupported router_mode: {router_mode}")
