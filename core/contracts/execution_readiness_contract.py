from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from core.analytical_objective import ConversationalStance
from core.continuation_signals import has_probe_abandon_marker, has_reversal_marker
from core.contracts.base import ContractContext, ContractInterception
from core.contracts.runtime_defaults import has_runtime_default
from core.contracts.split_contract_utils import SplitContractSupport
from core.execution_continuation import ExecutionContinuation, PendingObjective
from core.execution_continuation_utils import (
    clear_execution_continuation,
    continuation_snapshot,
    load_execution_continuation,
    normalize_tool_queue,
    save_execution_continuation,
)
from core.intent_resolver import IntentResolver
from core.router import RouterResponse


class ExecutionReadinessContract(SplitContractSupport):
    """Wave 2 split contract for stance-dependent execution readiness."""

    name = "execution_readiness"

    def __init__(self, inner_router: Any = None, ao_manager: Any = None, runtime_config: Any = None):
        super().__init__(inner_router=inner_router, ao_manager=ao_manager, runtime_config=runtime_config)
        self.intent_resolver = IntentResolver(inner_router, ao_manager)

    async def before_turn(self, context: ContractContext) -> ContractInterception:
        if not getattr(self.runtime_config, "enable_contract_split", False):
            return ContractInterception()
        if not getattr(self.runtime_config, "enable_split_readiness_contract", True):
            return ContractInterception()
        state = context.state_snapshot
        oasc_state = dict(context.metadata.get("oasc") or {})
        classification = oasc_state.get("classification")
        current_ao = self.ao_manager.get_current_ao() if self.ao_manager is not None else None
        if state is None or classification is None or current_ao is None:
            return ContractInterception()
        continuation_before = load_execution_continuation(current_ao)
        short_circuit_intent = bool(
            (context.metadata.get("intent_resolution") or {}).get("short_circuit_intent")
        )
        tool_intent = context.metadata.get("tool_intent") or getattr(current_ao, "tool_intent", None)
        if (
            (tool_intent is None or not str(getattr(tool_intent, "resolved_tool", "") or "").strip())
            and not bool(getattr(self.runtime_config, "enable_split_intent_contract", True))
        ):
            tool_intent = self.intent_resolver.resolve_fast(state, current_ao)
            context.metadata["tool_intent"] = tool_intent
            self._persist_tool_intent(current_ao, tool_intent)
        tool_name = str(getattr(tool_intent, "resolved_tool", "") or "").strip()
        if not tool_name:
            return ContractInterception()
        tool_spec = self._get_tool_spec(tool_name)
        if not tool_spec:
            return ContractInterception()
        projected_chain = normalize_tool_queue(
            list(getattr(tool_intent, "projected_chain", []) or [tool_name])
        )
        if not projected_chain:
            projected_chain = [tool_name]

        snapshot = self._initial_snapshot(
            tool_name=tool_name,
            current_ao=current_ao,
            pending_state=self._get_split_pending_state(current_ao),
            classification=classification,
        )
        stage1_filled = self._run_stage1(state, snapshot)
        active_required_slots = list(dict.fromkeys(tool_spec.get("required_slots") or []))
        missing_required_stage1 = self._missing_slots(snapshot, active_required_slots)
        stage2_meta = dict(context.metadata.get("stage2_telemetry") or {})
        llm_payload = context.metadata.get("stage2_payload") if isinstance(context.metadata.get("stage2_payload"), dict) else None
        if llm_payload is None and missing_required_stage1 and self._stage2_available():
            llm_payload, stage2_meta = await self._run_stage2_llm_with_telemetry(
                user_message=context.effective_user_message,
                state=state,
                current_ao=current_ao,
                tool_name=tool_name,
                snapshot=snapshot,
                tool_spec=tool_spec,
                classification=classification,
            )
            context.metadata["stage2_payload"] = llm_payload
            context.metadata["stage2_telemetry"] = stage2_meta
        if llm_payload is not None:
            snapshot = self._merge_stage2_snapshot(snapshot, self._stage2_snapshot_payload(llm_payload))

        snapshot, normalizations, rejected_slots = self._run_stage3(
            tool_name=tool_name,
            snapshot=snapshot,
            tool_spec=tool_spec,
            suppress_defaults_for=[],
        )
        missing_required = self._missing_slots(snapshot, active_required_slots)
        optional_classification = self._classify_missing_optionals(tool_name, snapshot, tool_spec)
        if bool(getattr(self.runtime_config, "enable_split_stance_contract", True)):
            stance_value = getattr(getattr(current_ao, "stance", None), "value", None) or "directive"
        else:
            stance_value = ConversationalStance.DIRECTIVE.value
        branch = stance_value if stance_value in {"directive", "deliberative", "exploratory"} else "directive"
        transition_reason = "no_change"
        continuation_after = continuation_before

        reversal_detected = bool((context.metadata.get("stance") or {}).get("reversal_detected"))
        if (
            continuation_before.is_active()
            and (reversal_detected or has_reversal_marker(context.effective_user_message))
        ):
            clear_execution_continuation(current_ao, updated_turn=self._current_turn_index())
            continuation_after = load_execution_continuation(current_ao)
            continuation_before = continuation_before
            transition_reason = "reset_reversal"
        elif (
            continuation_before.pending_objective == PendingObjective.CHAIN_CONTINUATION
            and continuation_before.pending_next_tool
            and projected_chain
            and projected_chain[0] != continuation_before.pending_next_tool
        ):
            continuation_after = ExecutionContinuation(
                pending_objective=PendingObjective.CHAIN_CONTINUATION,
                pending_next_tool=projected_chain[0],
                pending_tool_queue=list(projected_chain),
                updated_turn=self._current_turn_index(),
            )
            save_execution_continuation(current_ao, continuation_after)
            transition_reason = "replace_queue_override"

        if missing_required or rejected_slots:
            pending_slot = (missing_required or rejected_slots or [None])[0]
            question = self._build_question(
                tool_name=tool_name,
                snapshot=snapshot,
                missing_slots=missing_required,
                rejected_slots=rejected_slots,
                llm_question=stage2_meta.get("stage2_clarification_question"),
            )
            self._persist_split_pending(current_ao, tool_name, pending_slot, snapshot)
            continuation_after = ExecutionContinuation(
                pending_objective=PendingObjective.PARAMETER_COLLECTION,
                pending_slot=pending_slot,
                probe_count=int(
                    continuation_before.probe_count
                    if continuation_before.pending_slot == pending_slot
                    else 0
                ),
                probe_limit=max(1, int(continuation_before.probe_limit or 2)),
                abandoned=False,
                updated_turn=self._current_turn_index(),
            )
            save_execution_continuation(current_ao, continuation_after)
            if transition_reason == "no_change":
                transition_reason = "initial_write"
            telemetry = self._telemetry(
                tool_name=tool_name,
                decision="clarify",
                branch=branch,
                pending_slot=pending_slot,
                stage1_filled=stage1_filled,
                stage2_meta=stage2_meta,
                normalizations=normalizations,
                rejected_slots=rejected_slots,
                runtime_defaults=[],
                no_default_optionals_probed=[],
                continuation_before=continuation_before,
                continuation_after=continuation_after,
                transition_reason=transition_reason,
                short_circuit_intent=short_circuit_intent,
            )
            context.metadata["execution_continuation_transition"] = {
                "continuation_before": continuation_snapshot(continuation_before),
                "continuation_after": continuation_snapshot(continuation_after),
                "transition_reason": transition_reason,
                "short_circuit_intent": short_circuit_intent,
            }
            return ContractInterception(
                proceed=False,
                response=RouterResponse(
                    text=question,
                    trace_friendly=[{"step_type": "clarification", "summary": question}],
                ),
                metadata={"clarification": {"telemetry": telemetry}},
            )

        no_default_optionals = list(optional_classification["no_default"])
        runtime_defaults = list(optional_classification["resolved_by_default"])

        if branch == ConversationalStance.EXPLORATORY.value:
            telemetry = self._telemetry(
                tool_name=tool_name,
                decision="clarify",
                branch=branch,
                pending_slot="scope",
                stage1_filled=stage1_filled,
                stage2_meta=stage2_meta,
                normalizations=normalizations,
                rejected_slots=rejected_slots,
                runtime_defaults=[],
                no_default_optionals_probed=[],
                continuation_before=continuation_before,
                continuation_after=continuation_after,
                transition_reason=transition_reason,
                short_circuit_intent=short_circuit_intent,
            )
            context.metadata["execution_continuation_transition"] = {
                "continuation_before": continuation_snapshot(continuation_before),
                "continuation_after": continuation_snapshot(continuation_after),
                "transition_reason": transition_reason,
                "short_circuit_intent": short_circuit_intent,
            }
            return ContractInterception(
                proceed=False,
                response=RouterResponse(
                    text="您想先比较哪类交通排放分析目标？可以指定排放因子、微观排放、宏观排放或扩散影响。",
                    trace_friendly=[{"step_type": "clarification", "summary": "scope framing"}],
                ),
                metadata={"clarification": {"telemetry": telemetry}},
            )

        if branch == ConversationalStance.DELIBERATIVE.value and no_default_optionals:
            pending_slot = no_default_optionals[0]
            probe_count = (
                continuation_before.probe_count + 1
                if continuation_before.pending_objective == PendingObjective.PARAMETER_COLLECTION
                and continuation_before.pending_slot == pending_slot
                else 1
            )
            probe_limit = max(1, int(continuation_before.probe_limit or 2))
            if has_probe_abandon_marker(context.effective_user_message) or probe_count >= probe_limit:
                continuation_after = ExecutionContinuation(
                    pending_objective=PendingObjective.PARAMETER_COLLECTION,
                    pending_slot=pending_slot,
                    probe_count=probe_count,
                    probe_limit=probe_limit,
                    abandoned=True,
                    updated_turn=self._current_turn_index(),
                )
                save_execution_continuation(current_ao, continuation_after)
                transition_reason = "abandon_probe_limit"
            else:
                self._persist_split_pending(current_ao, tool_name, pending_slot, snapshot)
                continuation_after = ExecutionContinuation(
                    pending_objective=PendingObjective.PARAMETER_COLLECTION,
                    pending_slot=pending_slot,
                    probe_count=probe_count,
                    probe_limit=probe_limit,
                    abandoned=False,
                    updated_turn=self._current_turn_index(),
                )
                save_execution_continuation(current_ao, continuation_after)
                if transition_reason == "no_change":
                    transition_reason = "initial_write"
                question = await self._build_probe_question(
                    tool_name=tool_name,
                    snapshot=snapshot,
                    slot_name=pending_slot,
                    current_ao=current_ao,
                )
                telemetry = self._telemetry(
                    tool_name=tool_name,
                    decision="clarify",
                    branch=branch,
                    pending_slot=pending_slot,
                    stage1_filled=stage1_filled,
                    stage2_meta=stage2_meta,
                    normalizations=normalizations,
                    rejected_slots=rejected_slots,
                    runtime_defaults=runtime_defaults,
                    no_default_optionals_probed=no_default_optionals,
                    continuation_before=continuation_before,
                    continuation_after=continuation_after,
                    transition_reason=transition_reason,
                    short_circuit_intent=short_circuit_intent,
                )
                context.metadata["execution_continuation_transition"] = {
                    "continuation_before": continuation_snapshot(continuation_before),
                    "continuation_after": continuation_snapshot(continuation_after),
                    "transition_reason": transition_reason,
                    "short_circuit_intent": short_circuit_intent,
                }
                return ContractInterception(
                    proceed=False,
                    response=RouterResponse(
                        text=question,
                        trace_friendly=[{"step_type": "clarification", "summary": question}],
                    ),
                    metadata={"clarification": {"telemetry": telemetry}},
                )

        self._persist_split_pending(current_ao, tool_name, None, snapshot)
        if continuation_before.pending_objective == PendingObjective.PARAMETER_COLLECTION:
            continuation_after = ExecutionContinuation(
                pending_objective=PendingObjective.NONE,
                updated_turn=self._current_turn_index(),
            )
            save_execution_continuation(current_ao, continuation_after)
            if transition_reason == "no_change":
                transition_reason = "advance"

        telemetry = self._telemetry(
            tool_name=tool_name,
            decision="proceed",
            branch=branch,
            pending_slot=None,
            stage1_filled=stage1_filled,
            stage2_meta=stage2_meta,
            normalizations=normalizations,
            rejected_slots=rejected_slots,
            runtime_defaults=runtime_defaults,
            no_default_optionals_probed=[],
            continuation_before=continuation_before,
            continuation_after=continuation_after,
            transition_reason=transition_reason,
            short_circuit_intent=short_circuit_intent,
        )
        context.metadata["execution_continuation_transition"] = {
            "continuation_before": continuation_snapshot(continuation_before),
            "continuation_after": continuation_snapshot(continuation_after),
            "transition_reason": transition_reason,
            "short_circuit_intent": short_circuit_intent,
        }
        clarification_metadata: Dict[str, Any] = {"telemetry": telemetry}
        if len(projected_chain) <= 1:
            clarification_metadata["direct_execution"] = {
                "tool_name": tool_name,
                "parameter_snapshot": copy.deepcopy(snapshot),
                "confirm_first_detected": False,
                "trigger_mode": "fresh",
                "runtime_defaults_allowed": runtime_defaults,
                "projected_chain": list(projected_chain),
            }
        context.metadata["execution_continuation_plan"] = {
            "projected_chain": list(projected_chain),
            "tool_name": tool_name,
        }
        return ContractInterception(metadata={"clarification": clarification_metadata})

    async def after_turn(self, context: ContractContext, result: RouterResponse) -> None:
        clarification_state = dict(context.metadata.get("clarification") or {})
        telemetry = clarification_state.get("telemetry")
        if telemetry is None:
            return
        transition_meta = dict(context.metadata.get("execution_continuation_transition") or {})
        telemetry["execution_continuation"] = {
            "continuation_before": dict(
                transition_meta.get("continuation_before")
                or continuation_snapshot(load_execution_continuation(self.ao_manager.get_current_ao() if self.ao_manager else None))
            ),
            "continuation_after": dict(
                transition_meta.get("continuation_after")
                or continuation_snapshot(load_execution_continuation(self.ao_manager.get_current_ao() if self.ao_manager else None))
            ),
            "transition_reason": transition_meta.get("transition_reason") or "no_change",
            "short_circuit_intent": bool(transition_meta.get("short_circuit_intent")),
        }
        trace_obj = result.trace if isinstance(result.trace, dict) else None
        if trace_obj is None:
            trace_obj = {}
            result.trace = trace_obj
        existing = trace_obj.setdefault("clarification_telemetry", [])
        if not any(
            isinstance(item, dict)
            and item.get("turn") == telemetry.get("turn")
            and item.get("tool_name") == telemetry.get("tool_name")
            and item.get("final_decision") == telemetry.get("final_decision")
            for item in existing
        ):
            existing.append(dict(telemetry))
        trace_obj["clarification_contract"] = {
            "enabled": True,
            "split": True,
            "final_decision": telemetry.get("final_decision"),
            "tool_name": telemetry.get("tool_name"),
        }
        current_ao = self.ao_manager.get_current_ao() if self.ao_manager is not None else None
        if current_ao is not None and telemetry.get("final_decision") == "proceed":
            pending = dict(getattr(current_ao, "metadata", {}).get("execution_readiness") or {})
            pending["pending"] = False
            current_ao.metadata["execution_readiness"] = pending

    def _telemetry(
        self,
        *,
        tool_name: str,
        decision: str,
        branch: str,
        pending_slot: Optional[str],
        stage1_filled: List[str],
        stage2_meta: Dict[str, Any],
        normalizations: List[Dict[str, Any]],
        rejected_slots: List[str],
        runtime_defaults: List[str],
        no_default_optionals_probed: List[str],
        continuation_before: ExecutionContinuation,
        continuation_after: ExecutionContinuation,
        transition_reason: str,
        short_circuit_intent: bool,
    ) -> Dict[str, Any]:
        return {
            "turn": self._current_turn_index(),
            "triggered": True,
            "trigger_mode": "split",
            "classification_at_trigger": None,
            "stage1_filled_slots": list(stage1_filled),
            "stage2_called": bool(stage2_meta.get("stage2_called")),
            "stage2_latency_ms": stage2_meta.get("stage2_latency_ms"),
            "stage2_missing_required": list(stage2_meta.get("stage2_missing_required") or []),
            "stage2_clarification_question": stage2_meta.get("stage2_clarification_question"),
            "stage2_response_chars": stage2_meta.get("stage2_response_chars"),
            "stage2_intent_chars": stage2_meta.get("stage2_intent_chars"),
            "stage2_stance_chars": stage2_meta.get("stage2_stance_chars"),
            "stage2_prompt_tokens": stage2_meta.get("stage2_prompt_tokens"),
            "stage2_completion_tokens": stage2_meta.get("stage2_completion_tokens"),
            "stage2_raw_response_truncated": stage2_meta.get("stage2_raw_response_truncated"),
            "stage3_rejected_slots": list(rejected_slots),
            "stage3_normalizations": [dict(item) for item in normalizations],
            "final_decision": decision,
            "proceed_mode": None,
            "ao_id": getattr(self.ao_manager.get_current_ao(), "ao_id", None) if self.ao_manager else None,
            "tool_name": tool_name,
            "execution_readiness": {
                "readiness_branch": branch,
                "readiness_decision": decision,
                "pending_slot": pending_slot,
                "runtime_defaults_applied": list(runtime_defaults),
                "runtime_defaults_resolved": list(runtime_defaults),
                "no_default_optionals_probed": list(no_default_optionals_probed),
            },
            "execution_continuation": {
                "continuation_before": continuation_snapshot(continuation_before),
                "continuation_after": continuation_snapshot(continuation_after),
                "transition_reason": transition_reason,
                "short_circuit_intent": bool(short_circuit_intent),
            },
        }

    def _classify_missing_optionals(
        self,
        tool_name: str,
        snapshot: Dict[str, Dict[str, Any]],
        tool_spec: Dict[str, Any],
    ) -> Dict[str, List[str]]:
        resolved_by_default: List[str] = []
        no_default: List[str] = []
        optional_slots = [
            str(item)
            for item in list(tool_spec.get("optional_slots") or [])
            if str(item).strip()
        ]
        for slot_name in optional_slots:
            if not self._snapshot_missing_value(snapshot, slot_name):
                continue
            if (
                getattr(self.runtime_config, "enable_runtime_default_aware_readiness", True)
                and has_runtime_default(tool_name, slot_name)
            ):
                resolved_by_default.append(slot_name)
            else:
                no_default.append(slot_name)
        return {
            "resolved_by_default": list(dict.fromkeys(resolved_by_default)),
            "no_default": list(dict.fromkeys(no_default)),
        }

    @staticmethod
    def _snapshot_missing_value(snapshot: Dict[str, Any], slot_name: str) -> bool:
        payload = snapshot.get(slot_name)
        if not isinstance(payload, dict):
            return True
        if payload.get("source") == "rejected":
            return True
        return payload.get("value") in (None, "", [])

    @staticmethod
    def _get_split_pending_state(ao: Any) -> Dict[str, Any]:
        if ao is None or not isinstance(getattr(ao, "metadata", None), dict):
            return {}
        payload = ao.metadata.get("execution_readiness")
        return dict(payload) if isinstance(payload, dict) else {}

    @staticmethod
    def _persist_split_pending(ao: Any, tool_name: str, pending_slot: Optional[str], snapshot: Dict[str, Any]) -> None:
        if ao is None or not isinstance(getattr(ao, "metadata", None), dict):
            return
        ao.metadata["execution_readiness"] = {
            "pending": bool(pending_slot),
            "tool_name": tool_name,
            "pending_slot": pending_slot,
            "missing_slots": [pending_slot] if pending_slot else [],
            "parameter_snapshot": copy.deepcopy(snapshot),
        }
