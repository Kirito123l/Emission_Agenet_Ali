from __future__ import annotations

from typing import Any, Dict

from core.analytical_objective import ExecutionStepStatus, IntentConfidence
from config import get_config
from core.ao_manager import ensure_execution_state
from core.contracts.base import ContractContext, ContractInterception
from core.contracts.split_contract_utils import SplitContractSupport
from core.continuation_signals import has_reversal_marker
from core.execution_continuation import PendingObjective
from core.execution_continuation_utils import load_execution_continuation
from core.intent_resolver import IntentResolver
from core.router import RouterResponse


class IntentResolutionContract(SplitContractSupport):
    """Wave 2 split contract for tool-intent resolution."""

    name = "intent_resolution"

    def __init__(self, inner_router: Any = None, ao_manager: Any = None, runtime_config: Any = None):
        super().__init__(inner_router=inner_router, ao_manager=ao_manager, runtime_config=runtime_config)
        self.intent_resolver = IntentResolver(inner_router, ao_manager)

    async def before_turn(self, context: ContractContext) -> ContractInterception:
        if not getattr(self.runtime_config, "enable_contract_split", False):
            return ContractInterception()
        if not getattr(self.runtime_config, "enable_split_intent_contract", True):
            return ContractInterception()
        state = context.state_snapshot
        oasc_state = dict(context.metadata.get("oasc") or {})
        classification = oasc_state.get("classification")
        current_ao = self.ao_manager.get_current_ao() if self.ao_manager is not None else None
        if state is None or classification is None or current_ao is None:
            return ContractInterception()

        if context.file_path:
            await self._ensure_file_context(state, context.file_path)

        short_circuit_intent = False
        continuation = load_execution_continuation(current_ao)
        tool_intent = None
        bound_tool = ""
        if (
            getattr(self.runtime_config, "enable_split_continuation_state", True)
            and getattr(classification, "classification", None) is not None
            and str(getattr(classification.classification, "value", "") or "") == "continuation"
            and not has_reversal_marker(context.effective_user_message)
        ):
            fast = self.intent_resolver.resolve_fast(state, current_ao)

            # ── Phase 6.E.3: canonical execution state chain handoff ──────────
            # When canonical state has a pending downstream tool and the fast-resolved
            # tool is an already-completed upstream step, prefer the downstream tool.
            canonical_enabled = bool(getattr(
                self.runtime_config, "enable_canonical_execution_state", False,
            ))
            canonical_pending = None
            canonical_prefer = False
            canonical_conflict = None
            if canonical_enabled and self.ao_manager is not None:
                canonical_pending = self.ao_manager.get_canonical_pending_next_tool(current_ao)
                if canonical_pending:
                    fast_tool = str(getattr(fast, "resolved_tool", "") or "").strip()
                    canonical_prefer = self.ao_manager.should_prefer_canonical_pending_tool(
                        current_ao, proposed_tool=fast_tool or canonical_pending,
                    )
                    # Compatibility: detect conflict with ExecutionContinuation
                    if (
                        continuation.pending_objective == PendingObjective.CHAIN_CONTINUATION
                        and continuation.pending_next_tool
                        and continuation.pending_next_tool != canonical_pending
                    ):
                        canonical_conflict = {
                            "canonical_pending_next_tool": canonical_pending,
                            "continuation_pending_next_tool": continuation.pending_next_tool,
                            "applied_source": "canonical_execution_state",
                        }
            if canonical_prefer and canonical_pending:
                state_obj = ensure_execution_state(current_ao)
                remaining_chain = []
                if state_obj is not None:
                    remaining_chain = [
                        s.tool_name for s in state_obj.steps[state_obj.chain_cursor:]
                        if s.status != ExecutionStepStatus.SKIPPED
                    ] if 0 <= state_obj.chain_cursor < len(state_obj.steps) else []
                if not remaining_chain:
                    remaining_chain = [canonical_pending]
                tool_intent = self.intent_resolver._intent(
                    canonical_pending,
                    IntentConfidence.HIGH,
                    resolved_by="canonical_execution_state:pending_next_tool",
                    evidence=["canonical_execution_state:pending_next_tool"],
                    state=state,
                    projected_chain=remaining_chain,
                )
                short_circuit_intent = True
                context.metadata["canonical_chain_handoff"] = {
                    "triggered": True,
                    "pending_next_tool": canonical_pending,
                    "remaining_chain": list(remaining_chain),
                    "conflict": canonical_conflict,
                }

            if tool_intent is None and (
                continuation.pending_objective == PendingObjective.CHAIN_CONTINUATION
                and continuation.pending_next_tool
                and (not fast.projected_chain or fast.projected_chain[0] == continuation.pending_next_tool)
            ):
                tool_intent = self.intent_resolver._intent(
                    continuation.pending_next_tool,
                    IntentConfidence.HIGH,
                    resolved_by="continuation_state",
                    evidence=["continuation_state"],
                    state=state,
                    projected_chain=list(continuation.pending_tool_queue or []),
                )
                short_circuit_intent = True
            elif continuation.pending_objective == PendingObjective.PARAMETER_COLLECTION:
                bound_tool = str(getattr(getattr(current_ao, "tool_intent", None), "resolved_tool", "") or "").strip()
                if not bound_tool:
                    readiness_state = (
                        current_ao.metadata.get("execution_readiness")
                        if isinstance(getattr(current_ao, "metadata", None), dict)
                        else None
                    )
                    if isinstance(readiness_state, dict):
                        bound_tool = str(readiness_state.get("tool_name") or "").strip()
                if bound_tool and (not fast.projected_chain or fast.projected_chain[0] == bound_tool):
                    projected_chain = list(
                        getattr(getattr(current_ao, "tool_intent", None), "projected_chain", []) or [bound_tool]
                    )
                    tool_intent = self.intent_resolver._intent(
                        bound_tool,
                        IntentConfidence.HIGH,
                        resolved_by="parameter_collection_state",
                        evidence=["parameter_collection_state"],
                        state=state,
                        projected_chain=projected_chain,
                    )
                    short_circuit_intent = True
            elif not continuation.is_active():
                task_type = str(
                    getattr(getattr(state, "file_context", None), "task_type", "") or ""
                ).strip()
                if task_type in ("macro_emission", "micro_emission"):
                    tool_map = {
                        "macro_emission": "calculate_macro_emission",
                        "micro_emission": "calculate_micro_emission",
                    }
                    resolved = tool_map[task_type]
                    tool_intent = self.intent_resolver._intent(
                        resolved,
                        IntentConfidence.HIGH,
                        resolved_by="continuation_state:file_task_type",
                        evidence=[f"file_task_type:{task_type}"],
                        state=state,
                        projected_chain=[resolved],
                    )
                    short_circuit_intent = True

        if tool_intent is None:
            tool_intent = self.intent_resolver.resolve_fast(state, current_ao)
        if (
            tool_intent.confidence == IntentConfidence.NONE
            and self._stage2_available()
            and not short_circuit_intent
        ):
            payload, stage2_meta = await self._run_stage2_llm_with_telemetry(
                user_message=context.effective_user_message,
                state=state,
                current_ao=current_ao,
                tool_name=None,
                snapshot={},
                tool_spec=self._generic_tool_spec(),
                classification=classification,
            )
            llm_hint, llm_raw, parse_success = self._extract_llm_intent_hint(payload)
            tool_intent = self.intent_resolver.resolve_with_llm_hint(state, current_ao, llm_hint)
            context.metadata["stage2_payload"] = payload
            context.metadata["stage2_telemetry"] = stage2_meta
            context.metadata["intent_resolution"] = {
                "llm_intent_raw": llm_raw,
                "llm_intent_parse_success": parse_success,
                "short_circuit_intent": short_circuit_intent,
            }
        else:
            context.metadata["intent_resolution"] = {
                **dict(context.metadata.get("intent_resolution") or {}),
                "short_circuit_intent": short_circuit_intent,
            }
        if short_circuit_intent and continuation is not None:
            cs_meta: Dict[str, Any] = {
                "objective": str(getattr(current_ao, "objective_text", "") or ""),
                "pending_slots": [str(continuation.pending_slot)] if continuation.pending_slot else [],
                "prior_tool": str(continuation.pending_next_tool or bound_tool or ""),
                "pending_objective": str(continuation.pending_objective.value if hasattr(continuation.pending_objective, "value") else continuation.pending_objective),
            }
            if canonical_conflict:
                cs_meta["canonical_conflict"] = canonical_conflict
            context.metadata["continuation_state"] = cs_meta
        self._persist_tool_intent(current_ao, tool_intent)
        context.metadata["tool_intent"] = tool_intent
        if tool_intent.confidence == IntentConfidence.NONE:
            telemetry = self._telemetry(
                tool_name=None,
                decision="clarify",
                branch="intent",
                pending_slot="tool_intent",
                stage2_meta=dict(context.metadata.get("stage2_telemetry") or {}),
            )
            # Q3 gate: defer to decision field when active
            if self._split_decision_field_active(context):
                return ContractInterception(
                    metadata={
                        "clarification": {"telemetry": telemetry},
                        "intent_unresolved": True,
                        "available_tools": [
                            "query_emission_factors", "calculate_micro_emission",
                            "calculate_macro_emission", "query_knowledge",
                        ],
                        "hardcoded_recommendation": "clarify",
                        "hardcoded_reason": "intent unresolved",
                    }
                )
            return ContractInterception(
                proceed=False,
                response=RouterResponse(
                    text="",
                    trace_friendly=[{"step_type": "clarification", "summary": "clarify tool intent"}],
                ),
                metadata={
                    "clarification": {"telemetry": telemetry},
                    "intent_unresolved": True,
                    "available_tools": [
                        "query_emission_factors",
                        "calculate_micro_emission",
                        "calculate_macro_emission",
                        "query_knowledge",
                    ],
                },
            )
        return ContractInterception()

    def _telemetry(
        self,
        *,
        tool_name: str | None,
        decision: str,
        branch: str,
        pending_slot: str | None,
        stage2_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "turn": self._current_turn_index(),
            "triggered": True,
            "trigger_mode": "split",
            "classification_at_trigger": None,
            "stage1_filled_slots": [],
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
            "stage3_rejected_slots": [],
            "stage3_normalizations": [],
            "final_decision": decision,
            "proceed_mode": None,
            "ao_id": getattr(self.ao_manager.get_current_ao(), "ao_id", None) if self.ao_manager else None,
            "tool_name": tool_name,
            "execution_readiness": {
                "readiness_branch": branch,
                "readiness_decision": decision,
                "pending_slot": pending_slot,
                "runtime_defaults_applied": [],
            },
        }
