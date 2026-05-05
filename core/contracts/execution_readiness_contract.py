from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from core.analytical_objective import (
    ConversationalStance,
    ExecutionStepStatus,
    RevisionDeltaDecisionPreview,
    RevisionDeltaTelemetry,
)
from core.ao_manager import ensure_execution_state
from core.continuation_signals import has_probe_abandon_marker, has_reversal_marker
from core.contracts.base import ContractContext, ContractInterception
from core.contracts.runtime_defaults import _RUNTIME_DEFAULTS as RUNTIME_DEFAULTS, has_runtime_default
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
from core.trace import TraceStepType, make_friendly_entry


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
        classification_value = str(getattr(getattr(classification, "classification", None), "value", "") or "")
        if (
            classification_value in {"new_ao", "revision"}
            and continuation_before.pending_objective == PendingObjective.PARAMETER_COLLECTION
            and continuation_before.probe_count
        ):
            continuation_before = ExecutionContinuation(
                pending_objective=continuation_before.pending_objective,
                pending_slot=continuation_before.pending_slot,
                pending_next_tool=continuation_before.pending_next_tool,
                pending_tool_queue=list(continuation_before.pending_tool_queue or []),
                probe_count=0,
                probe_limit=max(1, int(continuation_before.probe_limit or 2)),
                abandoned=bool(continuation_before.abandoned),
                updated_turn=self._current_turn_index(),
            )
            save_execution_continuation(current_ao, continuation_before)
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

        # ── Phase 6.E.3: canonical execution state chain handoff guard ──────
        # Belt-and-suspenders: if canonical state has a pending downstream tool
        # and the intent-resolved tool is an already-completed upstream step,
        # override to the downstream tool.  Does NOT override revisions or
        # independent tasks (only overrides completed upstream drift).
        canonical_handoff_applied = False
        if (
            self.ao_manager is not None
            and bool(getattr(self.runtime_config, "enable_canonical_execution_state", False))
        ):
            canonical_pending = self.ao_manager.get_canonical_pending_next_tool(current_ao)
            if (
                canonical_pending
                and canonical_pending != tool_name
                and self.ao_manager.should_prefer_canonical_pending_tool(
                    current_ao, proposed_tool=tool_name,
                )
            ):
                state_obj = ensure_execution_state(current_ao)
                remaining_chain = [canonical_pending]
                if state_obj is not None and 0 <= state_obj.chain_cursor < len(state_obj.steps):
                    remaining_chain = [
                        s.tool_name for s in state_obj.steps[state_obj.chain_cursor:]
                        if s.status != ExecutionStepStatus.SKIPPED
                    ]
                tool_name = canonical_pending
                context.metadata["canonical_chain_handoff"] = {
                    "triggered": True,
                    "source": "execution_readiness_guard",
                    "pending_next_tool": canonical_pending,
                    "remaining_chain": list(remaining_chain),
                }
                canonical_handoff_applied = True

        tool_spec = self._get_tool_spec(tool_name)
        if not tool_spec:
            return ContractInterception()
        projected_chain = normalize_tool_queue(
            list(getattr(tool_intent, "projected_chain", []) or [tool_name])
        )
        if not projected_chain or canonical_handoff_applied:
            projected_chain = [tool_name]
        if not projected_chain:
            projected_chain = [tool_name]

        pending_state = self._get_split_pending_state(current_ao)
        snapshot = self._initial_snapshot(
            tool_name=tool_name,
            current_ao=current_ao,
            pending_state=pending_state,
            classification=classification,
        )
        stage1_filled = self._run_stage1(state, snapshot)
        active_required_slots = list(dict.fromkeys(tool_spec.get("required_slots") or []))
        missing_required_stage1 = self._missing_slots(snapshot, active_required_slots)

        # Phase 4: pre-compute PCM advisory for flag=true injection into Stage 2 payload
        flag_on = bool(getattr(self.runtime_config, "enable_llm_decision_field", False))
        pcm_advisory = None
        if flag_on:
            prelim_optional_class = self._classify_missing_optionals(tool_name, snapshot, tool_spec)
            prelim_no_default = list(prelim_optional_class["no_default"])
            prelim_resolved = list(prelim_optional_class["resolved_by_default"])
            prelim_confirm_first = bool(
                pending_state.get("confirm_first_detected") or self._detect_confirm_first(context.effective_user_message)
            )
            if prelim_no_default or prelim_resolved or prelim_confirm_first or continuation_before.pending_objective == PendingObjective.PARAMETER_COLLECTION:
                runtime_defaults_available: Dict[str, Any] = {}
                for slot_name in prelim_no_default:
                    if has_runtime_default(tool_name, slot_name):
                        rt = dict(RUNTIME_DEFAULTS.get(tool_name or "", {}))
                        if slot_name in rt:
                            runtime_defaults_available[slot_name] = rt[slot_name]
                pcm_advisory = {
                    "unfilled_optionals_without_default": prelim_no_default,
                    "runtime_defaults_available": runtime_defaults_available,
                    "resolved_by_default": prelim_resolved,
                    "confirm_first_detected": prelim_confirm_first,
                    "suggested_probe_slot": prelim_no_default[0] if prelim_no_default else None,
                    "collection_mode_active": True,
                }

        stage2_meta = dict(context.metadata.get("stage2_telemetry") or {})
        llm_payload = context.metadata.get("stage2_payload") if isinstance(context.metadata.get("stage2_payload"), dict) else None
        if (
            llm_payload is None
            and self._stage2_available()
            and (
                missing_required_stage1
                or continuation_before.pending_objective == PendingObjective.PARAMETER_COLLECTION
                or bool(pending_state.get("followup_slots"))
                or bool(pending_state.get("confirm_first_slots"))
                or (flag_on and pcm_advisory is not None)
            )
        ):
            llm_payload, stage2_meta = await self._run_stage2_llm_with_telemetry(
                user_message=context.effective_user_message,
                state=state,
                current_ao=current_ao,
                tool_name=tool_name,
                snapshot=snapshot,
                tool_spec=tool_spec,
                classification=classification,
                pcm_advisory=pcm_advisory,
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
        self._sync_revision_invalidation_runtime(
            context=context,
            current_ao=current_ao,
            tool_name=tool_name,
            snapshot=snapshot,
            missing_required=missing_required,
            rejected_slots=rejected_slots,
        )
        # Phase 5.3 Round 3.2: write stage3_yaml for A reconciler P2 source
        context.metadata["stage3_yaml"] = {
            "missing_required": list(missing_required),
            "rejected_slots": list(rejected_slots),
            "active_required_slots": list(active_required_slots),
            "optional_classification": dict(optional_classification),
        }
        stage2_needs_clarification = bool((llm_payload or {}).get("needs_clarification"))
        followup_slots = self._slot_names(
            pending_state.get("followup_slots") if pending_state.get("followup_slots") else tool_spec.get("clarification_followup_slots")
        )
        confirm_first_slots = self._slot_names(
            pending_state.get("confirm_first_slots") if pending_state.get("confirm_first_slots") else tool_spec.get("confirm_first_slots")
        )
        confirm_first_detected = bool(
            pending_state.get("confirm_first_detected") or self._detect_confirm_first(context.effective_user_message)
        )
        confirm_first_active = bool(confirm_first_detected and len(projected_chain) <= 1)
        missing_followup = self._missing_named_slots(snapshot, followup_slots)
        missing_confirm_first = self._missing_confirm_first_slots(snapshot, confirm_first_slots)
        executed_tool_count = len(list(getattr(current_ao, "tool_call_log", []) or []))
        if bool(getattr(self.runtime_config, "enable_split_stance_contract", True)):
            stance_value = getattr(getattr(current_ao, "stance", None), "value", None) or "directive"
        else:
            stance_value = ConversationalStance.DIRECTIVE.value
        branch = stance_value if stance_value in {"directive", "deliberative", "exploratory"} else "directive"
        transition_reason = "no_change"
        continuation_after = continuation_before
        probe_limit = max(1, int(continuation_before.probe_limit or 2))
        probe_count_value = int(continuation_before.probe_count or 0)
        force_proceed_reason: Optional[str] = None

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
            # Phase 6.E.3: if canonical state has a newer pending tool, let it win
            applied_source = "continuation"
            pending_next = continuation_before.pending_next_tool
            if bool(getattr(self.runtime_config, "enable_canonical_execution_state", False)):
                canonical_pending = (
                    self.ao_manager.get_canonical_pending_next_tool(current_ao)
                    if self.ao_manager is not None else None
                )
                if canonical_pending and canonical_pending != pending_next:
                    if canonical_pending in projected_chain:
                        pending_next = canonical_pending
                        applied_source = "canonical_execution_state"
                        context.metadata.setdefault("canonical_chain_handoff", {})
                        context.metadata["canonical_chain_handoff"].setdefault("conflict", {})
                        context.metadata["canonical_chain_handoff"]["conflict"] = {
                            "canonical_pending_next_tool": canonical_pending,
                            "continuation_pending_next_tool": continuation_before.pending_next_tool,
                            "applied_source": applied_source,
                        }
            if pending_next in projected_chain:
                idx = projected_chain.index(pending_next)
                continuation_after = ExecutionContinuation(
                    pending_objective=PendingObjective.CHAIN_CONTINUATION,
                    pending_next_tool=pending_next,
                    pending_tool_queue=list(projected_chain[idx:]),
                    updated_turn=self._current_turn_index(),
                )
                save_execution_continuation(current_ao, continuation_after)
                transition_reason = "replace_queue_override"
            # else: pending_next_tool not in projected_chain — preserve existing, no-op

        clarify_candidates = list(missing_required) + list(rejected_slots)
        clarify_required_candidates = list(missing_required)
        clarify_optional_candidates = [
            slot_name
            for slot_name in rejected_slots
            if slot_name not in active_required_slots
        ]
        if continuation_before.pending_objective == PendingObjective.PARAMETER_COLLECTION:
            carried_missing = self._missing_named_slots(snapshot, pending_state.get("missing_slots") or [])
            clarify_candidates.extend(carried_missing)
            clarify_required_candidates.extend(
                [slot_name for slot_name in carried_missing if slot_name in active_required_slots]
            )
            clarify_optional_candidates.extend(
                [slot_name for slot_name in carried_missing if slot_name not in active_required_slots]
            )
            clarify_candidates.extend(missing_confirm_first)
            clarify_candidates.extend(missing_followup)
            clarify_optional_candidates.extend(missing_confirm_first)
            clarify_optional_candidates.extend(missing_followup)
        if confirm_first_active:
            clarify_candidates.extend(missing_confirm_first)
            clarify_optional_candidates.extend(missing_confirm_first)
        if stage2_needs_clarification and executed_tool_count == 0:
            stage2_required_candidates = self._missing_named_slots(snapshot, stage2_meta.get("stage2_missing_required") or [])
            clarify_candidates.extend(stage2_required_candidates)
            clarify_required_candidates.extend(stage2_required_candidates)
            clarify_candidates.extend(missing_confirm_first)
            clarify_candidates.extend(missing_followup)
            clarify_optional_candidates.extend(missing_confirm_first)
            clarify_optional_candidates.extend(missing_followup)

        clarify_candidates = list(dict.fromkeys(str(item) for item in clarify_candidates if str(item).strip()))
        clarify_required_candidates = list(
            dict.fromkeys(str(item) for item in clarify_required_candidates if str(item).strip())
        )
        clarify_optional_candidates = list(
            dict.fromkeys(str(item) for item in clarify_optional_candidates if str(item).strip())
        )

        if stage2_needs_clarification and executed_tool_count == 0 and not clarify_candidates:
            clarify_candidates = self._missing_named_slots(snapshot, active_required_slots)
            clarify_required_candidates = list(clarify_candidates)
            if not clarify_candidates:
                clarify_candidates = list(dict.fromkeys([*missing_confirm_first, *missing_followup]))
                clarify_optional_candidates = list(clarify_candidates)
            if not clarify_candidates and active_required_slots:
                clarify_candidates = [active_required_slots[0]]
                clarify_required_candidates = list(clarify_candidates)

        if clarify_candidates:
            optional_only_probe = bool(clarify_optional_candidates) and not bool(clarify_required_candidates)
            if optional_only_probe and probe_count_value >= probe_limit:
                force_proceed_reason = "probe_limit_reached"
                continuation_after = ExecutionContinuation(
                    pending_objective=PendingObjective.NONE,
                    probe_count=probe_count_value,
                    probe_limit=probe_limit,
                    updated_turn=self._current_turn_index(),
                )
                save_execution_continuation(current_ao, continuation_after)
                if transition_reason == "no_change":
                    transition_reason = "advance"
            elif flag_on and optional_only_probe:
                # Phase 4 advisory mode: compute advisory, don't hard-block
                no_default_optionals = list(optional_classification["no_default"])
                pcm_advisory = {
                    "unfilled_optionals_without_default": no_default_optionals,
                    "runtime_defaults_available": {
                        slot_name: dict(RUNTIME_DEFAULTS.get(tool_name or "", {})).get(slot_name)
                        for slot_name in no_default_optionals
                        if slot_name in dict(RUNTIME_DEFAULTS.get(tool_name or "", {}))
                    },
                    "resolved_by_default": list(optional_classification["resolved_by_default"]),
                    "confirm_first_detected": confirm_first_active,
                    "suggested_probe_slot": clarify_candidates[0] if clarify_candidates else None,
                    "collection_mode_active": True,
                }
                context.metadata["pcm_advisory"] = pcm_advisory
                force_proceed_reason = "advisory_mode"
                continuation_after = ExecutionContinuation(
                    pending_objective=PendingObjective.NONE,
                    probe_count=probe_count_value,
                    probe_limit=probe_limit,
                    updated_turn=self._current_turn_index(),
                )
                save_execution_continuation(current_ao, continuation_after)
                if transition_reason == "no_change":
                    transition_reason = "advance"
            else:
                if optional_only_probe:
                    probe_count_value = probe_count_value + 1
                else:
                    probe_count_value = 0
                probe_limit = max(1, int(continuation_before.probe_limit or 2))
                pending_slot = clarify_candidates[0]
                question = self._build_question(
                    tool_name=tool_name,
                    snapshot=snapshot,
                    missing_slots=clarify_candidates,
                    rejected_slots=rejected_slots,
                    llm_question=stage2_meta.get("stage2_clarification_question"),
                )
                self._persist_split_pending(
                    current_ao,
                    tool_name,
                    pending_slot,
                    snapshot,
                    missing_slots=clarify_candidates,
                    followup_slots=followup_slots,
                    confirm_first_slots=confirm_first_slots,
                    confirm_first_detected=confirm_first_active,
                    needs_clarification=stage2_needs_clarification,
                )
                continuation_after = ExecutionContinuation(
                    pending_objective=PendingObjective.PARAMETER_COLLECTION,
                    pending_slot=pending_slot,
                    probe_count=probe_count_value,
                    probe_limit=probe_limit,
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
                    probe_count=probe_count_value,
                    probe_limit=probe_limit,
                    force_proceed_reason=None,
                )
                context.metadata["execution_continuation_transition"] = {
                    "continuation_before": continuation_snapshot(continuation_before),
                    "continuation_after": continuation_snapshot(continuation_after),
                    "transition_reason": transition_reason,
                    "short_circuit_intent": short_circuit_intent,
                }
                # Q3 gate: defer to decision field when active
                if self._split_decision_field_active(context):
                    return ContractInterception(
                        metadata={
                            "clarification": {"telemetry": telemetry},
                            "hardcoded_recommendation": "clarify",
                            "hardcoded_reason": question,
                            "readiness_gate": {
                                "disposition": "q3_defer",
                                "clarify_candidates": list(clarify_candidates),
                                "clarify_required_candidates": list(clarify_required_candidates),
                                "clarify_optional_candidates": list(clarify_optional_candidates),
                                "hardcoded_recommendation": "clarify",
                                "has_direct_execution": False,
                                "force_proceed_reason": "",
                            },
                        }
                    )
                return ContractInterception(
                    proceed=False,
                    response=RouterResponse(
                        text=question,
                        trace_friendly=[
                            make_friendly_entry(
                                step_type=TraceStepType.CLARIFICATION.value,
                                description=question,
                                status="warning",
                                title="需要确认 / Clarification Needed",
                                latency_ms=int(telemetry["stage2_latency_ms"]) if telemetry.get("stage2_latency_ms") is not None else None,
                            )
                        ],
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
                probe_count=probe_count_value,
                probe_limit=probe_limit,
                force_proceed_reason=force_proceed_reason,
            )
            context.metadata["execution_continuation_transition"] = {
                "continuation_before": continuation_snapshot(continuation_before),
                "continuation_after": continuation_snapshot(continuation_after),
                "transition_reason": transition_reason,
                "short_circuit_intent": short_circuit_intent,
            }
            # Q3 gate: defer to decision field when active
            if self._split_decision_field_active(context):
                return ContractInterception(
                    metadata={
                        "clarification": {"telemetry": telemetry},
                        "stance": "exploratory",
                        "available_capabilities": [
                            "排放因子查询", "微观排放计算", "宏观排放计算", "扩散影响分析",
                        ],
                        "hardcoded_recommendation": "deliberate",
                        "hardcoded_reason": "exploratory stance detected",
                        "readiness_gate": {
                            "disposition": "q3_defer",
                            "clarify_candidates": [],
                            "clarify_required_candidates": [],
                            "clarify_optional_candidates": [],
                            "hardcoded_recommendation": "deliberate",
                            "has_direct_execution": False,
                            "force_proceed_reason": "",
                        },
                    }
                )
            return ContractInterception(
                proceed=False,
                response=RouterResponse(
                    text="",
                    trace_friendly=[
                            make_friendly_entry(
                                step_type=TraceStepType.CLARIFICATION.value,
                                description="scope framing",
                                status="warning",
                                title="需要确认 / Clarification Needed",
                                latency_ms=int(telemetry["stage2_latency_ms"]) if telemetry.get("stage2_latency_ms") is not None else None,
                            )
                        ],
                ),
                metadata={
                    "clarification": {"telemetry": telemetry},
                    "stance": "exploratory",
                    "available_capabilities": [
                        "排放因子查询",
                        "微观排放计算",
                        "宏观排放计算",
                        "扩散影响分析",
                    ],
                },
            )

        if branch == ConversationalStance.DELIBERATIVE.value and no_default_optionals:
            if flag_on:
                # Phase 4 advisory mode: compute advisory, don't hard-block
                pcm_advisory = {
                    "unfilled_optionals_without_default": no_default_optionals,
                    "runtime_defaults_available": {
                        slot_name: dict(RUNTIME_DEFAULTS.get(tool_name or "", {})).get(slot_name)
                        for slot_name in no_default_optionals
                        if slot_name in dict(RUNTIME_DEFAULTS.get(tool_name or "", {}))
                    },
                    "resolved_by_default": runtime_defaults,
                    "confirm_first_detected": confirm_first_active,
                    "suggested_probe_slot": no_default_optionals[0],
                    "collection_mode_active": True,
                    "stance": "deliberative",
                }
                context.metadata["pcm_advisory"] = pcm_advisory
                force_proceed_reason = "advisory_mode"
                continuation_after = ExecutionContinuation(
                    pending_objective=PendingObjective.NONE,
                    updated_turn=self._current_turn_index(),
                )
                save_execution_continuation(current_ao, continuation_after)
                if transition_reason == "no_change":
                    transition_reason = "advance"
            else:
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
                    self._persist_split_pending(
                        current_ao,
                        tool_name,
                        pending_slot,
                        snapshot,
                        missing_slots=[pending_slot],
                        followup_slots=followup_slots,
                        confirm_first_slots=confirm_first_slots,
                        confirm_first_detected=confirm_first_active,
                        needs_clarification=stage2_needs_clarification,
                    )
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
                        probe_count=probe_count_value,
                        probe_limit=probe_limit,
                        force_proceed_reason=None,
                    )
                    context.metadata["execution_continuation_transition"] = {
                        "continuation_before": continuation_snapshot(continuation_before),
                        "continuation_after": continuation_snapshot(continuation_after),
                        "transition_reason": transition_reason,
                        "short_circuit_intent": short_circuit_intent,
                    }
                    # Q3 gate: defer to decision field when active
                    if self._split_decision_field_active(context):
                        return ContractInterception(
                            metadata={
                                "clarification": {"telemetry": telemetry},
                                "hardcoded_recommendation": "clarify",
                                "hardcoded_reason": question,
                                "readiness_gate": {
                                    "disposition": "q3_defer",
                                    "clarify_candidates": [pending_slot],
                                    "clarify_required_candidates": [pending_slot],
                                    "clarify_optional_candidates": [],
                                    "hardcoded_recommendation": "clarify",
                                    "has_direct_execution": False,
                                    "force_proceed_reason": "",
                                },
                            }
                        )
                    return ContractInterception(
                        proceed=False,
                        response=RouterResponse(
                            text=question,
                            trace_friendly=[
                                make_friendly_entry(
                                    step_type=TraceStepType.CLARIFICATION.value,
                                    description=question,
                                    status="warning",
                                    title="需要确认 / Clarification Needed",
                                    latency_ms=int(telemetry["stage2_latency_ms"]) if telemetry.get("stage2_latency_ms") is not None else None,
                                )
                            ],
                        ),
                        metadata={"clarification": {"telemetry": telemetry}},
                    )

        preserve_followup_slot = next(
            (
                slot_name
                for slot_name in followup_slots
                if slot_name in runtime_defaults and self._snapshot_missing_value(snapshot, slot_name)
            ),
            None,
        )
        if force_proceed_reason:
            preserve_followup_slot = None
        self._persist_split_pending(
            current_ao,
            tool_name,
            preserve_followup_slot,
            snapshot,
            missing_slots=[preserve_followup_slot] if preserve_followup_slot else [],
            followup_slots=followup_slots,
            confirm_first_slots=confirm_first_slots,
            confirm_first_detected=confirm_first_active,
            needs_clarification=stage2_needs_clarification,
        )
        if preserve_followup_slot:
            continuation_after = ExecutionContinuation(
                pending_objective=PendingObjective.PARAMETER_COLLECTION,
                pending_slot=preserve_followup_slot,
                probe_count=0,
                probe_limit=max(1, int(continuation_before.probe_limit or 2)),
                abandoned=False,
                updated_turn=self._current_turn_index(),
            )
            save_execution_continuation(current_ao, continuation_after)
            if transition_reason == "no_change":
                transition_reason = "initial_write"
        elif continuation_before.pending_objective == PendingObjective.PARAMETER_COLLECTION:
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
            probe_count=probe_count_value,
            probe_limit=probe_limit,
            force_proceed_reason=force_proceed_reason,
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
                "confirm_first_detected": confirm_first_active,
                "trigger_mode": "fresh",
                "runtime_defaults_allowed": runtime_defaults,
                "projected_chain": list(projected_chain),
            }
        context.metadata["execution_continuation_plan"] = {
            "projected_chain": list(projected_chain),
            "tool_name": tool_name,
        }
        # Phase 5.3 Round 3.2: attach readiness_gate for A reconciler P3 source
        clarification_metadata["readiness_gate"] = {
            "disposition": "proceed",
            "clarify_candidates": [],
            "clarify_required_candidates": [],
            "clarify_optional_candidates": [],
            "hardcoded_recommendation": "",
            "has_direct_execution": bool(
                clarification_metadata.get("direct_execution") is not None
            ),
            "force_proceed_reason": str(force_proceed_reason or ""),
        }
        return ContractInterception(
            metadata={
                "clarification": clarification_metadata,
                "readiness_gate": clarification_metadata["readiness_gate"],
            }
        )

    # ── Phase 6.E.4C: revision invalidation runtime integration ─────────────

    def _sync_revision_invalidation_runtime(
        self,
        *,
        context: ContractContext,
        current_ao: Any,
        tool_name: str,
        snapshot: Dict[str, Dict[str, Any]],
        missing_required: List[str],
        rejected_slots: List[str],
    ) -> None:
        """Detect and apply revision invalidation from final readiness args.

        This runs after Stage 3 normalization, before router-level duplicate
        suppression. It only mutates AOExecutionState through AOManager's
        Phase 6.E.4B engine and does not dispatch or suppress tools itself.
        """
        if self.ao_manager is None or current_ao is None:
            return
        if not (
            bool(getattr(self.runtime_config, "enable_canonical_execution_state", False))
            and bool(getattr(self.runtime_config, "enable_revision_invalidation", False))
        ):
            return

        state = ensure_execution_state(current_ao)
        if state is None:
            telemetry = RevisionDeltaTelemetry(
                proposed_tool=str(tool_name or ""),
                decision_preview=RevisionDeltaDecisionPreview.INSUFFICIENT_EVIDENCE,
                reason="no canonical execution state available",
            )
            self._store_revision_runtime_telemetry(context, current_ao, telemetry)
            return

        proposed_args = self._snapshot_to_effective_args(tool_name, snapshot)
        if context.file_path and "file_path" not in proposed_args:
            proposed_args["file_path"] = str(context.file_path)

        if missing_required or rejected_slots:
            fingerprint = self.ao_manager._build_semantic_fingerprint(tool_name, proposed_args)
            telemetry = RevisionDeltaTelemetry(
                proposed_tool=str(tool_name or ""),
                proposed_args_fingerprint=fingerprint,
                missing_keys=list(dict.fromkeys([*missing_required, *rejected_slots])),
                decision_preview=RevisionDeltaDecisionPreview.INSUFFICIENT_EVIDENCE,
                reason="final effective args unavailable: missing or rejected slots",
            )
            self._store_revision_runtime_telemetry(context, current_ao, telemetry)
            return

        fingerprint = self.ao_manager._build_semantic_fingerprint(tool_name, proposed_args)
        if not self.ao_manager._fingerprint_sufficient(fingerprint, tool_name):
            telemetry = RevisionDeltaTelemetry(
                proposed_tool=str(tool_name or ""),
                proposed_args_fingerprint=fingerprint,
                decision_preview=RevisionDeltaDecisionPreview.INSUFFICIENT_EVIDENCE,
                reason="final effective args unavailable: insufficient semantic fingerprint",
            )
            self._store_revision_runtime_telemetry(context, current_ao, telemetry)
            return

        telemetry = self.ao_manager.detect_revision_delta_telemetry(
            current_ao,
            proposed_tool=tool_name,
            proposed_args=proposed_args,
            user_message=context.effective_user_message,
        )
        self._store_revision_runtime_telemetry(context, current_ao, telemetry)

        if telemetry.scope_expansion_detected:
            return
        if telemetry.decision_preview not in (
            RevisionDeltaDecisionPreview.PARAM_DELTA_SELF,
            RevisionDeltaDecisionPreview.PARAM_DELTA_DOWNSTREAM,
            RevisionDeltaDecisionPreview.DATA_SOURCE_DELTA_ALL,
        ):
            return
        if not telemetry.would_invalidate_tools:
            return

        result = self.ao_manager.apply_revision_invalidation(current_ao, telemetry)
        payload = {
            **result.to_dict(),
            "runtime_integration_point": "execution_readiness_stage3",
        }
        context.metadata["revision_invalidation_result"] = payload
        if isinstance(getattr(current_ao, "metadata", None), dict):
            current_ao.metadata["last_revision_invalidation"] = dict(payload)

    def _store_revision_runtime_telemetry(
        self,
        context: ContractContext,
        current_ao: Any,
        telemetry: RevisionDeltaTelemetry,
    ) -> None:
        payload = {
            **telemetry.to_dict(),
            "runtime_integration_point": "execution_readiness_stage3",
        }
        context.metadata["revision_delta_telemetry"] = payload
        if isinstance(getattr(current_ao, "metadata", None), dict):
            current_ao.metadata["last_revision_delta_telemetry"] = dict(payload)

    @staticmethod
    def _snapshot_to_effective_args(
        tool_name: str,
        snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Convert final Stage 3 readiness snapshot to effective tool args."""
        from core.snapshot_coercion import apply_coercion
        from tools.contract_loader import get_tool_contract_registry

        def read(slot_name: str):
            payload = snapshot.get(slot_name)
            if not isinstance(payload, dict):
                return None
            source = str(payload.get("source") or "").strip().lower()
            value = payload.get("value")
            if source in {"missing", "rejected"}:
                return None
            if isinstance(value, str) and value.strip().lower() in {
                "missing", "unknown", "none", "n/a", "null", "",
            }:
                return None
            return value

        if tool_name in ("calculate_dispersion", "render_spatial_map"):
            if read("pollutant") is None and read("pollutants") is not None:
                pollutants_raw = read("pollutants")
                if isinstance(pollutants_raw, list) and pollutants_raw:
                    snapshot = dict(snapshot)
                    snapshot["pollutant"] = {
                        "value": pollutants_raw[0],
                        "source": "inferred",
                    }

        registry = get_tool_contract_registry()
        param_coercions = registry.get_type_coercion(tool_name)
        args: Dict[str, Any] = {}
        for slot_name in sorted(snapshot):
            raw = read(slot_name)
            if raw is None:
                continue
            coercion = param_coercions.get(slot_name)
            if coercion is None:
                continue
            coerced = apply_coercion(coercion, raw, slot_name)
            if coerced is not None:
                args[slot_name] = coerced
        return args

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
            continuation_after = dict(transition_meta.get("continuation_after") or {})
            pending["pending"] = bool(continuation_after.get("pending_objective") == "parameter_collection")
            if pending["pending"]:
                pending["pending_slot"] = continuation_after.get("pending_slot")
                pending["missing_slots"] = [continuation_after.get("pending_slot")] if continuation_after.get("pending_slot") else []
            else:
                pending["pending_slot"] = None
                pending["missing_slots"] = []
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
        probe_count: int,
        probe_limit: int,
        force_proceed_reason: Optional[str],
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
                "probe_count": int(probe_count or 0),
                "probe_limit": max(1, int(probe_limit or 2)),
                "force_proceed_reason": force_proceed_reason,
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
    def _persist_split_pending(
        ao: Any,
        tool_name: str,
        pending_slot: Optional[str],
        snapshot: Dict[str, Any],
        *,
        missing_slots: Optional[List[str]] = None,
        followup_slots: Optional[List[str]] = None,
        confirm_first_slots: Optional[List[str]] = None,
        confirm_first_detected: bool = False,
        needs_clarification: bool = False,
    ) -> None:
        if ao is None or not isinstance(getattr(ao, "metadata", None), dict):
            return
        normalized_missing = [
            str(item) for item in list(missing_slots if missing_slots is not None else ([pending_slot] if pending_slot else [])) if str(item).strip()
        ]
        ao.metadata["execution_readiness"] = {
            "pending": bool(pending_slot),
            "tool_name": tool_name,
            "pending_slot": pending_slot,
            "missing_slots": normalized_missing,
            "parameter_snapshot": copy.deepcopy(snapshot),
            "followup_slots": [str(item) for item in list(followup_slots or []) if str(item).strip()],
            "confirm_first_slots": [str(item) for item in list(confirm_first_slots or []) if str(item).strip()],
            "confirm_first_detected": bool(confirm_first_detected),
            "needs_clarification": bool(needs_clarification),
        }
        # Phase 5.3 Round 3.3: mirror to top-level AO-local fields
        # (legacy ClarificationContract writes these; split ERC must do the same
        #  so _initial_snapshot fallback can find the snapshot.)
        ao.metadata["parameter_snapshot"] = copy.deepcopy(snapshot)
        for slot_name, slot_payload in snapshot.items():
            if not isinstance(slot_payload, dict):
                continue
            if slot_payload.get("source") in {"missing", "rejected"}:
                continue
            value = slot_payload.get("value")
            if value in (None, "", []):
                continue
            ao.parameters_used[slot_name] = value

    @staticmethod
    def _slot_names(values: Any) -> List[str]:
        return [str(item) for item in list(values or []) if str(item).strip()]

    def _missing_named_slots(self, snapshot: Dict[str, Dict[str, Any]], slot_names: Any) -> List[str]:
        return [
            slot_name
            for slot_name in self._slot_names(slot_names)
            if self._snapshot_missing_value(snapshot, slot_name)
        ]

    def _missing_confirm_first_slots(
        self,
        snapshot: Dict[str, Dict[str, Any]],
        slot_names: Any,
    ) -> List[str]:
        missing: List[str] = []
        for slot_name in self._slot_names(slot_names):
            slot_payload = snapshot.get(slot_name)
            if not isinstance(slot_payload, dict):
                missing.append(slot_name)
                continue
            if self._snapshot_missing_value(snapshot, slot_name):
                missing.append(slot_name)
                continue
            if str(slot_payload.get("source") or "missing") == "default":
                missing.append(slot_name)
        return missing
