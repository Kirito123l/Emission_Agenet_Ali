from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import get_config
from core.analytical_objective import AORelationship, ToolCallRecord
from core.ao_classifier import AOClassification, OAScopeClassifier
from core.ao_manager import AOManager, TurnOutcome
from core.contracts.base import BaseContract, ContractContext, ContractInterception
from core.execution_continuation import ExecutionContinuation, PendingObjective
from core.execution_continuation_utils import (
    advance_tool_queue,
    build_chain_continuation,
    continuation_snapshot,
    load_execution_continuation,
    save_execution_continuation,
)
from core.router import RouterResponse
from core.task_state import ContinuationDecision, TaskState
from services.llm_client import get_llm_client


class OASCContract(BaseContract):
    name = "oasc"

    def __init__(self, inner_router: Any, ao_manager: AOManager, runtime_config: Optional[Any] = None):
        self.inner_router = inner_router
        self.ao_manager = ao_manager
        self.runtime_config = runtime_config or get_config()
        classifier_llm = None
        if getattr(self.runtime_config, "enable_ao_classifier_llm_layer", True):
            classifier_llm = get_llm_client(
                "agent",
                model=getattr(self.runtime_config, "ao_classifier_model", None),
            )
        self.classifier = OAScopeClassifier(
            self.ao_manager,
            classifier_llm,
            self.runtime_config,
        )

    async def before_turn(self, context: ContractContext) -> ContractInterception:
        classifier_telemetry_start = self.classifier.telemetry_size()
        ao_telemetry_start = self.ao_manager.telemetry_size()
        classification = None
        classifier_ms = 0.0

        if getattr(self.runtime_config, "enable_ao_aware_memory", True):
            self._pre_register_file_reference(context.file_path)
            classifier_start = time.perf_counter()
            state_snapshot = self._build_state_snapshot(context.effective_user_message, context.file_path)
            classification = await self.classifier.classify(
                user_message=context.effective_user_message,
                recent_conversation=self._get_recent_turns(),
                task_state=state_snapshot,
            )
            classifier_ms = round((time.perf_counter() - classifier_start) * 1000, 2)
            self._apply_classification(classification, context.effective_user_message)
            context.state_snapshot = state_snapshot

        return ContractInterception(
            metadata={
                "oasc": {
                    "classification": classification,
                    "classifier_ms": classifier_ms,
                    "classifier_telemetry_start": classifier_telemetry_start,
                    "ao_telemetry_start": ao_telemetry_start,
                }
            }
        )

    async def after_turn(
        self,
        context: ContractContext,
        result: RouterResponse,
    ) -> None:
        oasc_state = dict(context.metadata.get("oasc") or {})
        classification = oasc_state.get("classification")
        classifier_ms = float(oasc_state.get("classifier_ms") or 0.0)
        classifier_telemetry_start = int(oasc_state.get("classifier_telemetry_start") or 0)
        ao_telemetry_start = int(oasc_state.get("ao_telemetry_start") or 0)

        if result.executed_tool_calls is None:
            result.executed_tool_calls = self._backfill_executed_tool_calls_from_memory()

        if context.router_executed and getattr(self.runtime_config, "enable_ao_aware_memory", True):
            self._sync_ao_from_turn_result(result)
            current_ao = self.ao_manager.get_current_ao()
            if current_ao is not None:
                self._refresh_split_execution_continuation(context, result, current_ao)
                turn_outcome = self._build_turn_outcome(result)
                self.ao_manager.complete_ao(
                    current_ao.ao_id,
                    end_turn=self._current_turn_index(),
                    turn_outcome=turn_outcome,
                )

        self._attach_oasc_trace(
            result,
            classification,
            classifier_ms,
            classifier_telemetry=self.classifier.telemetry_slice(classifier_telemetry_start),
            ao_lifecycle_events=self.ao_manager.telemetry_slice(ao_telemetry_start),
        )

    def _refresh_split_execution_continuation(
        self,
        context: ContractContext,
        result: RouterResponse,
        current_ao: Any,
    ) -> None:
        if not bool(getattr(self.runtime_config, "enable_contract_split", False)):
            return
        if not bool(getattr(self.runtime_config, "enable_split_continuation_state", True)):
            return

        transition_meta = dict(context.metadata.get("execution_continuation_transition") or {})
        continuation_before = load_execution_continuation(current_ao)
        executed_tools = [
            str(item.get("name") or "").strip()
            for item in list(result.executed_tool_calls or [])
            if isinstance(item, dict)
            and str(item.get("name") or "").strip()
            and bool((item.get("result") or {}).get("success"))
        ]
        continuation_after = continuation_before
        transition_reason = str(transition_meta.get("transition_reason") or "no_change")

        if executed_tools:
            projected_chain = [
                str(item)
                for item in list(getattr(getattr(current_ao, "tool_intent", None), "projected_chain", []) or [])
                if str(item).strip()
            ]
            desired_after = transition_meta.get("continuation_after")
            desired_after_state = (
                ExecutionContinuation.from_dict(desired_after)
                if isinstance(desired_after, dict)
                else ExecutionContinuation.empty()
            )
            if continuation_before.pending_objective == PendingObjective.CHAIN_CONTINUATION:
                remaining = advance_tool_queue(
                    list(continuation_before.pending_tool_queue or []),
                    executed_tools,
                )
                continuation_after = ExecutionContinuation(
                    pending_objective=(
                        PendingObjective.CHAIN_CONTINUATION if remaining else PendingObjective.NONE
                    ),
                    pending_next_tool=remaining[0] if remaining else None,
                    pending_tool_queue=remaining,
                    probe_count=continuation_before.probe_count,
                    probe_limit=continuation_before.probe_limit,
                    abandoned=False,
                    updated_turn=self._current_turn_index(),
                )
                transition_reason = "advance_queue" if remaining else "clear_queue_empty"
            elif projected_chain and len(projected_chain) > 1:
                continuation_after = build_chain_continuation(
                    projected_chain,
                    current_tool=executed_tools[0],
                    updated_turn=self._current_turn_index(),
                )
                transition_reason = (
                    "initial_write" if continuation_after.is_active() else "clear_queue_empty"
                )
            elif continuation_before.pending_objective == PendingObjective.PARAMETER_COLLECTION:
                if desired_after_state.pending_objective == PendingObjective.PARAMETER_COLLECTION:
                    continuation_after = ExecutionContinuation(
                        pending_objective=PendingObjective.PARAMETER_COLLECTION,
                        pending_slot=desired_after_state.pending_slot,
                        probe_count=desired_after_state.probe_count,
                        probe_limit=max(1, int(desired_after_state.probe_limit or continuation_before.probe_limit or 2)),
                        abandoned=bool(desired_after_state.abandoned),
                        updated_turn=self._current_turn_index(),
                    )
                    transition_reason = str(
                        transition_meta.get("transition_reason") or "advance"
                    )
                else:
                    continuation_after = ExecutionContinuation(
                        pending_objective=PendingObjective.NONE,
                        updated_turn=self._current_turn_index(),
                    )
                    transition_reason = "clear_queue_empty"

            save_execution_continuation(current_ao, continuation_after)

        context.metadata["execution_continuation_transition"] = {
            **transition_meta,
            "continuation_before": continuation_snapshot(continuation_before),
            "continuation_after": continuation_snapshot(continuation_after),
            "transition_reason": transition_reason,
        }

    def _get_recent_turns(self) -> List[Dict[str, str]]:
        turns = []
        for turn in self.inner_router.memory.get_working_memory()[-4:]:
            user_text = str(turn.get("user") or "").strip()
            assistant_text = str(turn.get("assistant") or "").strip()
            if user_text:
                turns.append({"role": "user", "content": user_text})
            if assistant_text:
                turns.append({"role": "assistant", "content": assistant_text})
        return turns

    def _build_state_snapshot(
        self,
        user_message: str,
        file_path: Optional[str],
    ) -> TaskState:
        state = TaskState.initialize(
            user_message=user_message,
            file_path=file_path,
            memory_dict=self.inner_router.memory.get_fact_memory(),
            session_id=self.inner_router.session_id,
        )
        active_input = self.inner_router._load_active_input_completion_request()
        if active_input is not None:
            state.set_active_input_completion(active_input)
        active_negotiation = self.inner_router._load_active_parameter_negotiation_request()
        if active_negotiation is not None:
            state.set_active_parameter_negotiation(active_negotiation)
        continuation_bundle = self.inner_router._ensure_live_continuation_bundle()
        residual_plan_summary = str(continuation_bundle.get("residual_plan_summary") or "").strip()
        latest_repair_summary = str(continuation_bundle.get("latest_repair_summary") or "").strip()
        plan_payload = continuation_bundle.get("plan")
        if residual_plan_summary or latest_repair_summary or isinstance(plan_payload, dict):
            state.set_continuation_decision(
                ContinuationDecision(
                    residual_plan_exists=bool(residual_plan_summary or plan_payload),
                    continuation_ready=bool(residual_plan_summary or plan_payload),
                    should_continue=bool(residual_plan_summary or plan_payload),
                    signal="governed_wrapper_snapshot",
                    reason="Continuation cues recovered from live router bundle.",
                    residual_plan_summary=residual_plan_summary or None,
                    latest_repair_summary=latest_repair_summary or None,
                )
            )
        return state

    def _apply_classification(self, cls: AOClassification, user_message: str) -> None:
        current_turn = self._current_turn_index(pre_call=True)
        current = self.ao_manager.get_current_ao()
        if cls.classification.value == "continuation":
            if current is None:
                self.ao_manager.create_ao(
                    objective_text=(user_message or "")[:200],
                    relationship=AORelationship.INDEPENDENT,
                    current_turn=current_turn,
                )
            return
        if cls.classification.value == "revision" and cls.target_ao_id:
            self.ao_manager.revise_ao(
                parent_ao_id=cls.target_ao_id,
                revised_objective_text=cls.new_objective_text or (user_message or "")[:200],
                current_turn=current_turn,
            )
            return
        self.ao_manager.create_ao(
            objective_text=cls.new_objective_text or (user_message or "")[:200],
            relationship=(
                AORelationship.REFERENCE
                if cls.reference_ao_id
                else AORelationship.INDEPENDENT
            ),
            parent_ao_id=cls.reference_ao_id,
            current_turn=current_turn,
        )

    def _sync_ao_from_turn_result(self, result: RouterResponse) -> None:
        current = self.ao_manager.get_current_ao()
        if current is None:
            latest_user = (
                self.inner_router.memory.working_memory[-1].user
                if self.inner_router.memory.working_memory
                else ""
            )
            current = self.ao_manager.create_ao(
                objective_text=(latest_user or "")[:200],
                relationship=AORelationship.INDEPENDENT,
                current_turn=self._current_turn_index(),
            )

        tool_calls = list(result.executed_tool_calls or [])
        for item in tool_calls:
            if not isinstance(item, dict):
                continue
            tool_name = str(item.get("name") or "unknown")
            arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
            tool_result = item.get("result") if isinstance(item.get("result"), dict) else {}
            summary = str(tool_result.get("summary") or tool_result.get("message") or "")
            record = ToolCallRecord(
                turn=self._current_turn_index(),
                tool=tool_name,
                args_compact=self.inner_router.memory.fact_memory._compact_payload(arguments),
                success=bool(tool_result.get("success")),
                result_ref=(
                    self.inner_router.memory.fact_memory._infer_result_ref(tool_name, tool_result)
                    if tool_result.get("success")
                    else None
                ),
                summary=summary[:200],
            )
            self.ao_manager.append_tool_call(current.ao_id, record)
            self._merge_ao_parameters(current, arguments)
            if record.result_ref:
                artifact_type, _, label = record.result_ref.partition(":")
                self.ao_manager.register_artifact(current.ao_id, artifact_type, label or artifact_type)

        self._sync_persistent_session_facts(current)

    def _merge_ao_parameters(self, ao: Any, arguments: Dict[str, Any]) -> None:
        interesting = {
            "vehicle_type",
            "season",
            "road_type",
            "meteorology",
            "stability_class",
            "model_year",
            "pollutant",
            "pollutants",
        }
        for key, value in arguments.items():
            if key not in interesting or value in (None, ""):
                continue
            ao.parameters_used[key] = value

    def _sync_persistent_session_facts(self, current_ao: Any) -> None:
        fact_memory = self.inner_router.memory.fact_memory
        if fact_memory.active_file:
            task_type = None
            if isinstance(fact_memory.file_analysis, dict):
                task_type = fact_memory.file_analysis.get("task_type") or fact_memory.file_analysis.get("detected_type")
            fact_memory.register_file_reference(
                path=str(fact_memory.active_file),
                task_type=str(task_type) if task_type is not None else None,
                uploaded_turn=self._current_turn_index(),
            )

        confirmed: Dict[str, Any] = {}
        for key in ("vehicle_type", "season", "road_type", "meteorology", "stability_class", "model_year"):
            if key in current_ao.parameters_used:
                confirmed[key] = current_ao.parameters_used[key]
        if fact_memory.recent_vehicle and "vehicle_type" not in confirmed:
            confirmed["vehicle_type"] = fact_memory.recent_vehicle
        if fact_memory.recent_year is not None and "model_year" not in confirmed:
            confirmed["model_year"] = fact_memory.recent_year
        fact_memory.update_session_confirmed_parameters(confirmed)

        seen = {
            (
                item.get("turn"),
                item.get("constraint"),
                tuple(sorted((item.get("values") or {}).items())),
            )
            for item in current_ao.constraint_violations
            if isinstance(item, dict)
        }
        for item in fact_memory.constraint_violations_seen:
            if not isinstance(item, dict):
                continue
            signature = (
                item.get("turn"),
                item.get("constraint"),
                tuple(sorted((item.get("values") or {}).items())),
            )
            if signature in seen:
                continue
            current_ao.constraint_violations.append(dict(item))
            fact_memory.append_cumulative_constraint_violation(
                int(item.get("turn") or self._current_turn_index()),
                str(item.get("constraint") or "unknown"),
                dict(item.get("values") or {}),
                bool(item.get("blocked")),
                ao_id=current_ao.ao_id,
            )

    def _build_turn_outcome(self, result: RouterResponse) -> TurnOutcome:
        tool_calls = list(result.executed_tool_calls or [])
        tool_chain_succeeded = bool(tool_calls) and all(
            bool((item.get("result") or {}).get("success"))
            for item in tool_calls
            if isinstance(item, dict)
        )
        text = str(result.text or "").strip()
        active_input = self.inner_router._load_active_input_completion_request() is not None
        active_negotiation = self.inner_router._load_active_parameter_negotiation_request() is not None
        continuation_bundle = self.inner_router._ensure_live_continuation_bundle()
        partial_delivery = bool(
            continuation_bundle.get("plan")
            or continuation_bundle.get("residual_plan_summary")
        )
        return TurnOutcome(
            tool_chain_succeeded=tool_chain_succeeded,
            final_response_delivered=bool(text),
            is_clarification=active_input or ("?" in text and not tool_calls),
            is_parameter_negotiation=active_negotiation,
            is_partial_delivery=partial_delivery,
        )

    def _current_turn_index(self, *, pre_call: bool = False) -> int:
        turn_counter = int(getattr(self.inner_router.memory, "turn_counter", 0) or 0)
        return turn_counter + 1 if pre_call else turn_counter

    def _pre_register_file_reference(self, file_path: Optional[str]) -> None:
        if not file_path:
            return
        self.inner_router.memory.fact_memory.register_file_reference(
            path=str(file_path),
            task_type=None,
            uploaded_turn=self._current_turn_index(pre_call=True),
        )

    def _backfill_executed_tool_calls_from_memory(self) -> Optional[List[Dict[str, Any]]]:
        working_memory = getattr(self.inner_router.memory, "working_memory", None) or []
        if not working_memory:
            return None
        last_turn = working_memory[-1]
        tool_calls = getattr(last_turn, "tool_calls", None)
        if not tool_calls:
            return None
        return [dict(item) for item in tool_calls if isinstance(item, dict)] or None

    def _attach_oasc_trace(
        self,
        result: RouterResponse,
        classification: Optional[AOClassification],
        classifier_ms: float,
        *,
        classifier_telemetry: List[Dict[str, Any]],
        ao_lifecycle_events: List[Dict[str, Any]],
    ) -> None:
        trace_obj = result.trace if isinstance(result.trace, dict) else None
        if trace_obj is None:
            trace_obj = {}
            result.trace = trace_obj
        block_telemetry = getattr(self.inner_router.assembler, "last_telemetry", {}) or {}
        block_entry = block_telemetry.get("session_state_block", {}).get("block_telemetry")
        trace_obj["oasc"] = {
            "router_mode": "governed_v2",
            "classifier": (
                {
                    "classification": classification.classification.value,
                    "target_ao_id": classification.target_ao_id,
                    "reference_ao_id": classification.reference_ao_id,
                    "confidence": classification.confidence,
                    "layer": classification.layer,
                    "reasoning": classification.reasoning,
                    "latency_ms": classifier_ms,
                }
                if classification is not None
                else None
            ),
            "current_ao_id": self.ao_manager.get_current_ao().ao_id if self.ao_manager.get_current_ao() else None,
            "ao_block": block_telemetry.get("session_state_block"),
        }
        trace_obj["classifier_telemetry"] = list(classifier_telemetry or [])
        trace_obj["ao_lifecycle_events"] = list(ao_lifecycle_events or [])
        trace_obj["block_telemetry"] = [dict(block_entry)] if isinstance(block_entry, dict) else []
