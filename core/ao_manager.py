from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from core.analytical_objective import (
    AORelationship,
    AOStatus,
    AnalyticalObjective,
    IdempotencyDecision,
    IdempotencyResult,
    IntentConfidence,
    ToolCallRecord,
)
from core.ao_manager_keywords import MULTI_STEP_SIGNAL_PATTERNS as _MULTI_STEP_SIGNAL_PATTERNS
from core.execution_continuation_utils import load_execution_continuation

logger = logging.getLogger(__name__)

# ── Phase 6.1: tool-specific semantic keys for effective-args fingerprint ──
# Keys that, if changed, would change the tool output. Runtime noise (output_path,
# timestamp, run_id, trace_id, tool_call_id, result_ref) is always excluded.
TOOL_SEMANTIC_KEYS: Dict[str, frozenset] = {
    "calculate_macro_emission": frozenset({
        "vehicle_type", "pollutant", "pollutants", "season", "road_type",
        "model_year", "meteorology", "stability_class", "file_path",
    }),
    "calculate_micro_emission": frozenset({
        "vehicle_type", "pollutant", "pollutants", "trajectory_file", "file_path",
    }),
    "calculate_dispersion": frozenset({
        "source_tool", "pollutant", "meteorology", "stability_class",
        "spatial_geometry", "file_path",
    }),
    "query_emission_factors": frozenset({
        "vehicle_type", "pollutant", "pollutants", "model_year", "season",
        "road_type",
    }),
    "analyze_hotspots": frozenset({
        "source_tool", "method", "threshold",
    }),
    "render_spatial_map": frozenset({
        "source_tool", "layer", "basemap",
    }),
    "analyze_file": frozenset({
        "file_path",
    }),
    "query_knowledge": frozenset({
        "query_text",
    }),
    "compare_scenarios": frozenset({
        "scenario_a_tool", "scenario_b_tool",
    }),
}

_RERUN_SIGNALS = ("重新算", "再算一遍", "重跑", "rerun", "recalculate")

RUNTIME_NOISE_KEYS = frozenset({
    "output_path", "timestamp", "run_id", "trace_id", "tool_call_id",
    "result_ref", "summary", "message",
})


@dataclass
class TurnOutcome:
    """One-turn execution summary used by strict AO completion checks."""

    tool_chain_succeeded: bool
    final_response_delivered: bool
    is_clarification: bool
    is_parameter_negotiation: bool
    is_partial_delivery: bool


@dataclass
class AOLifecycleEvent:
    turn: int
    event_type: str
    ao_id: str
    relationship: str
    parent_ao_id: Optional[str]
    complete_check_results: Optional[Dict[str, Any]] = None
    tool_intent_confidence: Optional[str] = None
    tool_intent_resolved_by: Optional[str] = None
    parameter_state_collection_mode: Optional[bool] = None
    parameter_state_awaiting_slot: Optional[str] = None
    completion_path: Optional[str] = None
    block_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn": self.turn,
            "event_type": self.event_type,
            "ao_id": self.ao_id,
            "relationship": self.relationship,
            "parent_ao_id": self.parent_ao_id,
            "complete_check_results": (
                dict(self.complete_check_results)
                if isinstance(self.complete_check_results, dict)
                else None
            ),
            "tool_intent_confidence": self.tool_intent_confidence,
            "tool_intent_resolved_by": self.tool_intent_resolved_by,
            "parameter_state_collection_mode": self.parameter_state_collection_mode,
            "parameter_state_awaiting_slot": self.parameter_state_awaiting_slot,
            "completion_path": self.completion_path,
            "block_reason": self.block_reason,
        }


class AOManager:
    """Manage analytical-objective lifecycle inside one session."""

    MAX_TOOL_CALLS_PER_AO = 20
    MAX_CONSTRAINT_VIOLATIONS_PER_AO = 10
    MAX_COMPLETED_AOS_IN_SUMMARY = 5
    MULTI_STEP_SIGNAL_PATTERNS = _MULTI_STEP_SIGNAL_PATTERNS

    def __init__(self, fact_memory: Any):
        self._memory = fact_memory
        self._telemetry_log: List[AOLifecycleEvent] = []

    def get_current_ao(self) -> Optional[AnalyticalObjective]:
        current_id = getattr(self._memory, "current_ao_id", None)
        if not current_id:
            return None
        return self.get_ao_by_id(current_id)

    def get_ao_by_id(self, ao_id: Optional[str]) -> Optional[AnalyticalObjective]:
        if not ao_id:
            return None
        for ao in getattr(self._memory, "ao_history", []):
            if ao.ao_id == ao_id:
                return ao
        return None

    def get_completed_aos(self) -> List[AnalyticalObjective]:
        return [
            ao
            for ao in getattr(self._memory, "ao_history", [])
            if ao.status == AOStatus.COMPLETED
        ]

    def create_ao(
        self,
        objective_text: str,
        relationship: AORelationship,
        parent_ao_id: Optional[str] = None,
        current_turn: int = 0,
    ) -> AnalyticalObjective:
        active = self.get_current_ao()
        if active is not None and active.status in {AOStatus.ACTIVE, AOStatus.REVISING}:
            if self._lifecycle_alignment_enabled():
                can_complete, block_reason, check_results = self._can_complete_ao(
                    active,
                    turn_outcome=None,
                    completion_path="create_ao_implicit",
                )
            else:
                can_complete = self._ao_objective_satisfied(active)
                block_reason = None if can_complete else "objective_not_satisfied"
                check_results = {
                    "implicit_on_create": True,
                    "has_produced_expected_artifacts": bool(active.has_produced_expected_artifacts()),
                    "objective_satisfied": bool(self._ao_objective_satisfied(active)),
                }

            if can_complete:
                active.status = AOStatus.COMPLETED
                active.end_turn = max(active.start_turn, int(current_turn or 0) - 1)
                self._record_event(
                    turn=max(active.end_turn, active.start_turn),
                    event_type="complete",
                    ao=active,
                    complete_check_results=check_results,
                    completion_path="create_ao_implicit",
                )
            elif block_reason in {
                "collection_mode_active",
                "intent_not_resolved",
                "metadata_clarification_pending",
                "execution_continuation_active",
            }:
                self._record_event(
                    turn=max(active.start_turn, int(current_turn or 0) - 1),
                    event_type="complete_blocked",
                    ao=active,
                    complete_check_results=check_results,
                    completion_path="create_ao_implicit",
                    block_reason=block_reason,
                )
            else:
                active.status = AOStatus.ABANDONED
                active.end_turn = max(active.start_turn, int(current_turn or 0) - 1)
                self._record_event(
                    turn=max(active.end_turn, active.start_turn),
                    event_type="abandon",
                    ao=active,
                    completion_path="create_ao_implicit",
                    block_reason=block_reason,
                )

        counter = int(getattr(self._memory, "_ao_counter", 0)) + 1
        self._memory._ao_counter = counter
        ao = AnalyticalObjective(
            ao_id=f"AO#{counter}",
            session_id=str(getattr(self._memory, "session_id", "") or ""),
            objective_text=str(objective_text or "").strip(),
            status=AOStatus.CREATED,
            start_turn=int(current_turn or 0),
            relationship=relationship,
            parent_ao_id=parent_ao_id,
        )
        self._memory.ao_history.append(ao)
        self._memory.current_ao_id = ao.ao_id
        self._record_event(
            turn=int(current_turn or 0),
            event_type="create",
            ao=ao,
        )
        return self.activate_ao(ao.ao_id)

    def activate_ao(self, ao_id: str) -> AnalyticalObjective:
        ao = self.get_ao_by_id(ao_id)
        if ao is None:
            raise ValueError(f"Unknown AO id: {ao_id}")
        if ao.status == AOStatus.CREATED:
            ao.status = AOStatus.ACTIVE
        elif ao.status == AOStatus.COMPLETED:
            ao.status = AOStatus.REVISING
        self._memory.current_ao_id = ao.ao_id
        self._record_event(
            turn=int(getattr(self._memory, "last_turn_index", 0) or ao.start_turn or 0),
            event_type="activate",
            ao=ao,
        )
        return ao

    def append_tool_call(self, ao_id: str, tool_call: ToolCallRecord) -> None:
        ao = self.get_ao_by_id(ao_id)
        if ao is None:
            raise ValueError(f"Unknown AO id: {ao_id}")
        ao.tool_call_log.append(tool_call)
        ao.tool_call_log = ao.tool_call_log[-self.MAX_TOOL_CALLS_PER_AO :]
        self._sync_tool_intent_from_tool_call(ao, tool_call)
        self._record_event(
            turn=int(getattr(tool_call, "turn", 0) or getattr(self._memory, "last_turn_index", 0) or ao.start_turn),
            event_type="append_tool_call",
            ao=ao,
        )

    def register_artifact(self, ao_id: str, artifact_type: str, label: str) -> None:
        ao = self.get_ao_by_id(ao_id)
        if ao is None:
            raise ValueError(f"Unknown AO id: {ao_id}")
        artifact_key = str(artifact_type or "").strip() or "unknown"
        artifact_label = str(label or "").strip() or "baseline"
        ao.artifacts_produced[artifact_key] = (
            artifact_label
            if ":" in artifact_label
            else f"{artifact_key}:{artifact_label}"
        )

    def complete_ao(
        self,
        ao_id: str,
        end_turn: int,
        turn_outcome: TurnOutcome,
    ) -> bool:
        ao = self.get_ao_by_id(ao_id)
        if ao is None:
            return False
        should_complete, block_reason, check_results = self._can_complete_ao(
            ao,
            turn_outcome=turn_outcome,
            completion_path="should_complete_explicit",
        )
        if not should_complete:
            if ao.status == AOStatus.CREATED:
                ao.status = AOStatus.ACTIVE
            self._record_event(
                turn=int(end_turn or ao.start_turn),
                event_type="complete_blocked",
                ao=ao,
                complete_check_results=check_results,
                completion_path="should_complete_explicit",
                block_reason=block_reason,
            )
            return False
        ao.status = AOStatus.COMPLETED
        ao.end_turn = int(end_turn or ao.end_turn or ao.start_turn)
        self._record_event(
            turn=int(end_turn or ao.start_turn),
            event_type="complete",
            ao=ao,
            complete_check_results=check_results,
            completion_path="should_complete_explicit",
        )
        return True

    def revise_ao(
        self,
        parent_ao_id: str,
        revised_objective_text: str,
        current_turn: int,
    ) -> AnalyticalObjective:
        parent = self.get_ao_by_id(parent_ao_id)
        if parent is None:
            raise ValueError(f"Unknown AO id: {parent_ao_id}")
        ao = self.create_ao(
            objective_text=revised_objective_text,
            relationship=AORelationship.REVISION,
            parent_ao_id=parent.ao_id,
            current_turn=current_turn,
        )
        ao.status = AOStatus.REVISING
        self._record_event(
            turn=int(current_turn or 0),
            event_type="revise",
            ao=ao,
        )
        return ao

    def fail_ao(self, ao_id: str, reason: str) -> None:
        ao = self.get_ao_by_id(ao_id)
        if ao is None:
            return
        ao.status = AOStatus.FAILED
        ao.failure_reason = str(reason or "").strip() or None
        self._record_event(
            turn=int(getattr(self._memory, "last_turn_index", 0) or ao.start_turn),
            event_type="fail",
            ao=ao,
        )

    def abandon_ao(self, ao_id: str) -> None:
        ao = self.get_ao_by_id(ao_id)
        if ao is None:
            return
        ao.status = AOStatus.ABANDONED
        self._record_event(
            turn=int(getattr(self._memory, "last_turn_index", 0) or ao.start_turn),
            event_type="abandon",
            ao=ao,
        )

    def get_summary_for_classifier(self) -> Dict[str, Any]:
        current = self.get_current_ao()
        completed = self.get_completed_aos()[-self.MAX_COMPLETED_AOS_IN_SUMMARY :]
        return {
            "current_ao": current.to_dict() if current else None,
            "completed_aos": [ao.to_dict() for ao in completed],
            "files_in_session": [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in getattr(self._memory, "files_in_session", [])
            ],
            "session_confirmed_parameters": dict(
                getattr(self._memory, "session_confirmed_parameters", {}) or {}
            ),
            "current_turn": getattr(self._memory, "last_turn_index", 0),
        }

    def get_summary_for_block(self) -> Dict[str, Any]:
        current = self.get_current_ao()
        completed = self.get_completed_aos()[-self.MAX_COMPLETED_AOS_IN_SUMMARY :]
        return {
            "persistent_facts": {
                "files_in_session": [
                    item.to_dict() if hasattr(item, "to_dict") else dict(item)
                    for item in getattr(self._memory, "files_in_session", [])
                ],
                "session_confirmed_parameters": dict(
                    getattr(self._memory, "session_confirmed_parameters", {}) or {}
                ),
                "cumulative_constraint_violations": [
                    dict(item)
                    for item in getattr(
                        self._memory,
                        "cumulative_constraint_violations",
                        [],
                    )
                    if isinstance(item, dict)
                ],
            },
            "completed_aos": [ao.to_dict() for ao in completed],
            "current_ao": current.to_dict() if current else None,
        }

    def should_complete_ao(
        self,
        ao: AnalyticalObjective,
        turn_outcome: TurnOutcome,
    ) -> bool:
        return self._can_complete_ao(
            ao,
            turn_outcome=turn_outcome,
            completion_path="should_complete_explicit",
        )[0]

    def _can_complete_ao(
        self,
        ao: AnalyticalObjective,
        turn_outcome: Optional[TurnOutcome],
        completion_path: str,
    ) -> tuple[bool, Optional[str], Dict[str, Any]]:
        check_results = self._build_complete_check_results(ao, turn_outcome)
        check_results["completion_path"] = completion_path

        clarification_state = ao.metadata.get("clarification_contract") if isinstance(ao.metadata, dict) else None
        continuation_state = load_execution_continuation(ao)
        if self._lifecycle_alignment_enabled():
            if not self._contract_split_enabled():
                parameter_state = getattr(ao, "parameter_state", None)
                if bool(getattr(parameter_state, "collection_mode", False)):
                    return False, "collection_mode_active", check_results
            elif continuation_state.is_active():
                return False, "execution_continuation_active", check_results
            tool_intent = getattr(ao, "tool_intent", None)
            if getattr(tool_intent, "confidence", IntentConfidence.NONE) == IntentConfidence.NONE:
                return False, "intent_not_resolved", check_results
        if isinstance(clarification_state, dict) and clarification_state.get("pending"):
            return False, "metadata_clarification_pending", check_results

        if turn_outcome is not None:
            basic_checks = all(
                [
                    bool(turn_outcome.tool_chain_succeeded),
                    bool(turn_outcome.final_response_delivered),
                    not bool(turn_outcome.is_clarification),
                    not bool(turn_outcome.is_parameter_negotiation),
                    not bool(turn_outcome.is_partial_delivery),
                    ao.has_produced_expected_artifacts(),
                ]
            )
            if not basic_checks:
                return False, "basic_checks_failed", check_results

        if not self._ao_objective_satisfied(ao):
            return False, "objective_not_satisfied", check_results
        return True, None, check_results

    def _build_complete_check_results(
        self,
        ao: AnalyticalObjective,
        turn_outcome: Optional[TurnOutcome],
    ) -> Dict[str, Any]:
        check_results: Dict[str, Any] = {
            "has_produced_expected_artifacts": bool(ao.has_produced_expected_artifacts()),
            "objective_satisfied": bool(self._ao_objective_satisfied(ao)),
            "collection_mode_active": (
                False
                if self._contract_split_enabled()
                else bool(getattr(getattr(ao, "parameter_state", None), "collection_mode", False))
            ),
            "intent_resolved": (
                getattr(getattr(ao, "tool_intent", None), "confidence", IntentConfidence.NONE)
                != IntentConfidence.NONE
            ),
            "execution_continuation_active": bool(load_execution_continuation(ao).is_active()),
            "execution_continuation": load_execution_continuation(ao).to_dict(),
        }
        if turn_outcome is not None:
            check_results.update(
                {
                    "tool_chain_succeeded": bool(turn_outcome.tool_chain_succeeded),
                    "final_response_delivered": bool(turn_outcome.final_response_delivered),
                    "is_clarification": bool(turn_outcome.is_clarification),
                    "is_parameter_negotiation": bool(turn_outcome.is_parameter_negotiation),
                    "is_partial_delivery": bool(turn_outcome.is_partial_delivery),
                }
            )
        else:
            check_results["implicit_on_create"] = True
        return check_results

    @staticmethod
    def _sync_tool_intent_from_tool_call(ao: AnalyticalObjective, tool_call: ToolCallRecord) -> None:
        tool_intent = getattr(ao, "tool_intent", None)
        if tool_intent is None:
            return
        if getattr(tool_intent, "confidence", IntentConfidence.NONE) != IntentConfidence.NONE:
            return
        tool_name = str(getattr(tool_call, "tool", "") or "").strip()
        if not tool_name or tool_name == "unknown":
            return
        tool_intent.resolved_tool = tool_name
        tool_intent.confidence = IntentConfidence.HIGH
        tool_intent.resolved_by = "tool_call"
        tool_intent.resolved_at_turn = int(getattr(tool_call, "turn", 0) or 0) or None
        evidence = list(getattr(tool_intent, "evidence", []) or [])
        evidence.append(f"executed_tool:{tool_name}")
        tool_intent.evidence = evidence[-5:]

    @staticmethod
    def _lifecycle_alignment_enabled() -> bool:
        try:
            from config import get_config

            return bool(getattr(get_config(), "enable_lifecycle_contract_alignment", True))
        except Exception:
            return True

    @staticmethod
    def _contract_split_enabled() -> bool:
        try:
            from config import get_config

            return bool(getattr(get_config(), "enable_contract_split", False))
        except Exception:
            return False

    @staticmethod
    def _tool_intent_confidence(ao: AnalyticalObjective) -> Optional[str]:
        confidence = getattr(getattr(ao, "tool_intent", None), "confidence", None)
        if isinstance(confidence, IntentConfidence):
            return confidence.value
        return str(confidence) if confidence is not None else None

    @staticmethod
    def _parameter_state_collection_mode(ao: AnalyticalObjective) -> Optional[bool]:
        if AOManager._contract_split_enabled():
            return None
        parameter_state = getattr(ao, "parameter_state", None)
        if parameter_state is None:
            return None
        return bool(getattr(parameter_state, "collection_mode", False))

    @staticmethod
    def _parameter_state_awaiting_slot(ao: AnalyticalObjective) -> Optional[str]:
        if AOManager._contract_split_enabled():
            return None
        parameter_state = getattr(ao, "parameter_state", None)
        if parameter_state is None:
            return None
        awaiting_slot = str(getattr(parameter_state, "awaiting_slot", "") or "").strip()
        return awaiting_slot or None

    def telemetry_size(self) -> int:
        return len(self._telemetry_log)

    def telemetry_slice(self, start_index: int = 0) -> List[Dict[str, Any]]:
        if start_index < 0:
            start_index = 0
        return [item.to_dict() for item in self._telemetry_log[start_index:]]

    def _record_event(
        self,
        *,
        turn: int,
        event_type: str,
        ao: AnalyticalObjective,
        complete_check_results: Optional[Dict[str, Any]] = None,
        completion_path: Optional[str] = None,
        block_reason: Optional[str] = None,
    ) -> None:
        try:
            self._telemetry_log.append(
                AOLifecycleEvent(
                    turn=int(turn or 0),
                    event_type=str(event_type or "unknown"),
                    ao_id=ao.ao_id,
                    relationship=ao.relationship.value,
                    parent_ao_id=ao.parent_ao_id,
                    complete_check_results=complete_check_results,
                    tool_intent_confidence=self._tool_intent_confidence(ao),
                    tool_intent_resolved_by=getattr(getattr(ao, "tool_intent", None), "resolved_by", None),
                    parameter_state_collection_mode=self._parameter_state_collection_mode(ao),
                    parameter_state_awaiting_slot=self._parameter_state_awaiting_slot(ao),
                    completion_path=completion_path,
                    block_reason=block_reason,
                )
            )
            self._telemetry_log = self._telemetry_log[-400:]
        except Exception as exc:
            logger.warning("Failed to record AO lifecycle telemetry: %s", exc)

    def _ao_objective_satisfied(self, ao: AnalyticalObjective) -> bool:
        if not ao.has_produced_expected_artifacts():
            return False
        if not self._objective_has_multi_step_intent(ao.objective_text):
            return True
        implied_tool_groups = self._extract_implied_tools(ao.objective_text)
        if not implied_tool_groups:
            return True
        executed_tools = {record.tool for record in ao.tool_call_log if record.success}
        return all(bool(executed_tools.intersection(group)) for group in implied_tool_groups)

    def _objective_has_multi_step_intent(self, text: str) -> bool:
        objective = str(text or "").strip().lower()
        if not objective:
            return False
        if any(re.search(pattern, objective, re.IGNORECASE) for pattern in self.MULTI_STEP_SIGNAL_PATTERNS):
            return True
        return len(self._extract_implied_tools(objective)) > 1

    def _extract_implied_tools(self, text: str) -> List[Set[str]]:
        objective = str(text or "").strip().lower()
        if not objective:
            return []
        from tools.contract_loader import get_tool_contract_registry

        registry = get_tool_contract_registry()

        # Phase 1: primary keywords (exclusive — first match wins, no other tool groups)
        primary_matches: Set[str] = set()
        for tool_name in registry.get_tool_names():
            ck = registry.get_completion_keywords(tool_name)
            primary = ck.get("primary") or []
            if primary and any(kw in objective for kw in primary):
                primary_matches.add(tool_name)
        if primary_matches:
            return [primary_matches]

        # Phase 2: secondary +/- requires keywords, grouped by keyword pattern
        groups_by_pattern: Dict[tuple, Set[str]] = {}
        for tool_name in registry.get_tool_names():
            ck = registry.get_completion_keywords(tool_name)
            secondary = ck.get("secondary") or []
            requires = ck.get("requires") or []

            if not secondary:
                continue
            if not any(kw in objective for kw in secondary):
                continue
            if requires and not any(kw in objective for kw in requires):
                continue

            pattern_key = (frozenset(secondary), frozenset(requires))
            if pattern_key not in groups_by_pattern:
                groups_by_pattern[pattern_key] = set()
            groups_by_pattern[pattern_key].add(tool_name)

        return list(groups_by_pattern.values())

    # ── Phase 6.1: execution idempotency ──────────────────────────────────

    def check_execution_idempotency(
        self,
        ao: AnalyticalObjective,
        proposed_tool: str,
        proposed_args: Dict[str, Any],
        user_message: str,
    ) -> IdempotencyResult:
        if not isinstance(proposed_args, dict) or not proposed_tool:
            return IdempotencyResult(
                decision=IdempotencyDecision.NO_DUPLICATE,
                decision_reason="empty proposed tool or args",
            )

        proposed_fp = self._build_semantic_fingerprint(proposed_tool, proposed_args)
        fp_insufficient = not proposed_fp or not self._fingerprint_sufficient(proposed_fp, proposed_tool)

        # Phase 6.1R: scope-3 fallback for insufficient proposed args.
        # When the proposed fingerprint is empty (e.g., args={} from inner_router fallback)
        # but the context strongly suggests a no-op follow-up (short param message,
        # same tool as recently completed AO), infer effective args from the completed AO.
        inferred_from_completed: Optional[Dict[str, Any]] = None
        if fp_insufficient and ao is not None:
            if self._is_short_parameter_like(user_message):
                completed = self.get_completed_aos()
                if completed:
                    most_recent = completed[-1]
                    prior_tools = {r.tool for r in getattr(most_recent, "tool_call_log", []) or [] if r.success}
                    if proposed_tool in prior_tools:
                        for r in reversed(list(getattr(most_recent, "tool_call_log", []) or [])):
                            if r.tool == proposed_tool and r.success:
                                inferred_from_completed = dict(r.args_compact or {})
                                # Also enrich from AO parameters_used
                                for k, v in getattr(most_recent, "parameters_used", {}).items():
                                    if k not in inferred_from_completed:
                                        inferred_from_completed[k] = v
                                break
                        if inferred_from_completed:
                            proposed_fp = self._build_semantic_fingerprint(proposed_tool, inferred_from_completed)
                            fp_insufficient = not proposed_fp or not self._fingerprint_sufficient(proposed_fp, proposed_tool)

        if fp_insufficient:
            return IdempotencyResult(
                decision=IdempotencyDecision.NO_DUPLICATE,
                decision_reason="proposed fingerprint empty or insufficient for tool",
                proposed_fingerprint=proposed_fp,
            )

        # Rule 1: explicit rerun signal
        rerun_signal = self._contains_rerun_signal(user_message)
        if rerun_signal:
            scope = self._search_idempotency_scope(ao, proposed_tool, proposed_args, user_message)
            for record in scope:
                if record.tool == proposed_tool and record.success:
                    return IdempotencyResult(
                        decision=IdempotencyDecision.EXPLICIT_RERUN,
                        matched_ao_id=self._record_ao_id(record, ao),
                        matched_tool=record.tool,
                        matched_turn=record.turn,
                        proposed_fingerprint=proposed_fp,
                        previous_fingerprint=self._build_semantic_fingerprint(record.tool, record.args_compact),
                        decision_reason=f"explicit rerun signal: {rerun_signal}",
                        explicit_rerun_absent=False,
                    )
            return IdempotencyResult(
                decision=IdempotencyDecision.NO_DUPLICATE,
                decision_reason=f"explicit rerun signal ({rerun_signal}) but no matching prior success",
                proposed_fingerprint=proposed_fp,
                explicit_rerun_absent=False,
            )

        # Rule 2: active CHAIN_CONTINUATION with pending_next_tool matching
        continuation = load_execution_continuation(ao) if ao is not None else None
        if continuation is not None and continuation.is_active():
            if (continuation.pending_objective is not None
                and hasattr(continuation.pending_objective, 'value')
                and continuation.pending_objective.value == "chain_continuation"
                and continuation.pending_next_tool == proposed_tool):
                return IdempotencyResult(
                    decision=IdempotencyDecision.NO_DUPLICATE,
                    decision_reason="active chain continuation pending_next_tool",
                    proposed_fingerprint=proposed_fp,
                )

        # Rule 3/4: search for prior matching executions
        scope = self._search_idempotency_scope(ao, proposed_tool, proposed_args, user_message)
        best_mismatch: Optional[IdempotencyResult] = None
        for record in scope:
            if record.tool != proposed_tool or not record.success:
                continue
            prev_fp = self._build_semantic_fingerprint(record.tool, record.args_compact)
            if not prev_fp or not self._fingerprint_sufficient(prev_fp, record.tool):
                continue
            if self._fingerprints_equivalent(proposed_fp, prev_fp):
                return IdempotencyResult(
                    decision=IdempotencyDecision.EXACT_DUPLICATE,
                    matched_ao_id=self._record_ao_id(record, ao),
                    matched_tool=record.tool,
                    matched_turn=record.turn,
                    matched_result_ref=record.result_ref,
                    proposed_fingerprint=proposed_fp,
                    previous_fingerprint=prev_fp,
                    decision_reason="equivalent effective args fingerprint",
                    explicit_rerun_absent=True,
                )
            # same tool, different fingerprint — save for later, keep searching
            if best_mismatch is None:
                best_mismatch = IdempotencyResult(
                    decision=IdempotencyDecision.REVISION_DETECTED,
                    matched_ao_id=self._record_ao_id(record, ao),
                    matched_tool=record.tool,
                    matched_turn=record.turn,
                    proposed_fingerprint=proposed_fp,
                    previous_fingerprint=prev_fp,
                    decision_reason="same tool but different effective args",
                    explicit_rerun_absent=True,
                )
        if best_mismatch is not None:
            return best_mismatch

        return IdempotencyResult(
            decision=IdempotencyDecision.NO_DUPLICATE,
            decision_reason="no matching prior execution in scope",
            proposed_fingerprint=proposed_fp,
        )

    def _build_semantic_fingerprint(
        self,
        tool_name: str,
        args: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not isinstance(args, dict):
            return {}
        semantic_keys = TOOL_SEMANTIC_KEYS.get(tool_name)
        if semantic_keys is None:
            return {}
        fp: Dict[str, Any] = {}
        for key in sorted(semantic_keys):
            value = args.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            if key in RUNTIME_NOISE_KEYS:
                continue
            fp[key] = self._canonicalize_value(key, value)
        return fp

    @staticmethod
    def _canonicalize_value(key: str, value: Any) -> Any:
        if isinstance(value, str):
            v = value.strip()
            # year normalization: "2020年" → 2020
            if key in ("model_year",) and v:
                m = re.match(r'^(\d{4})年?$', v)
                if m:
                    return int(m.group(1))
            # season aliases
            if key == "season" and v:
                try:
                    from services.standardizer import get_standardizer
                    std = get_standardizer()
                    canonical = std.season_lookup.get(v.lower())
                    if canonical:
                        return canonical
                except Exception:
                    pass
            # vehicle type aliases
            if key == "vehicle_type" and v:
                try:
                    from services.standardizer import get_standardizer
                    std = get_standardizer()
                    canonical = std.vehicle_lookup.get(v.lower())
                    if canonical:
                        return canonical
                except Exception:
                    pass
            # file_path normalization
            if key == "file_path" and v:
                from pathlib import Path
                try:
                    return str(Path(v).resolve())
                except Exception:
                    return v
            return v
        if isinstance(value, list):
            return tuple(sorted(
                str(item) for item in value if item is not None and str(item).strip()
            ))
        if isinstance(value, (int, float, bool)):
            return value
        return str(value)

    @staticmethod
    def _fingerprints_equivalent(
        proposed: Dict[str, Any],
        previous: Dict[str, Any],
    ) -> bool:
        """Strict comparison: all proposed keys must be present and match in previous."""
        if not proposed:
            return False
        comparable = 0
        for key in proposed:
            p_val = proposed.get(key)
            p_empty = p_val is None or (isinstance(p_val, str) and not p_val.strip()) or (isinstance(p_val, (list, tuple)) and len(p_val) == 0)
            if p_empty:
                continue
            comparable += 1
            prev_val = previous.get(key)
            prev_empty = prev_val is None or (isinstance(prev_val, str) and not prev_val.strip()) or (isinstance(prev_val, (list, tuple)) and len(prev_val) == 0)
            if prev_empty:
                return False  # key in proposed but missing/empty in previous
            if p_val != prev_val:
                return False
        return comparable > 0  # at least one comparable key must match

    @staticmethod
    def _fingerprint_sufficient(fp: Dict[str, Any], tool_name: str) -> bool:
        """A fingerprint must have at least one semantic key with a non-empty value."""
        if not fp or tool_name not in TOOL_SEMANTIC_KEYS:
            return False
        for key in TOOL_SEMANTIC_KEYS[tool_name]:
            v = fp.get(key)
            if v is not None and not (isinstance(v, str) and not v.strip()) and not (isinstance(v, (list, tuple)) and len(v) == 0):
                return True
        return False

    @staticmethod
    def _contains_rerun_signal(user_message: str) -> Optional[str]:
        msg = str(user_message or "").strip().lower()
        if not msg:
            return None
        for signal in _RERUN_SIGNALS:
            if signal in msg:
                return signal
        return None

    def _search_idempotency_scope(
        self,
        ao: AnalyticalObjective,
        proposed_tool: str,
        proposed_args: Dict[str, Any],
        user_message: str,
    ) -> List[ToolCallRecord]:
        records: List[ToolCallRecord] = []

        # Scope 1: current AO
        if ao is not None:
            for r in reversed(list(getattr(ao, "tool_call_log", []) or [])):
                records.append(r)

        # Scope 2: direct parent AO if revision child
        if ao is not None and getattr(ao, "relationship", None) is not None:
            try:
                rel = ao.relationship
                if hasattr(rel, 'value'):
                    rel = rel.value
                if rel == "revision":
                    parent_id = getattr(ao, "parent_ao_id", None)
                    if parent_id:
                        parent = self.get_ao_by_id(parent_id)
                        if parent is not None:
                            for r in reversed(list(getattr(parent, "tool_call_log", []) or [])):
                                if r not in records:
                                    records.append(r)
            except Exception:
                pass

        # Scope 3: most-recent completed AO (short-param followup scenario)
        if (ao is None or not list(getattr(ao, "tool_call_log", []) or [])):
            if self._is_short_parameter_like(user_message):
                completed = self.get_completed_aos()
                if completed:
                    most_recent = completed[-1]
                    if most_recent.ao_id != getattr(ao, "ao_id", None):
                        if self._anchor_matches(most_recent, proposed_tool, proposed_args):
                            for r in reversed(list(getattr(most_recent, "tool_call_log", []) or [])):
                                if r not in records:
                                    records.append(r)

        return records

    def _is_short_parameter_like(self, user_message: str) -> bool:
        stripped = str(user_message or "").strip()
        if not stripped or len(stripped) > 20:
            return False
        # single numeric year
        if re.match(r'^\d{4}年?$', stripped):
            return True
        # known alias
        try:
            from services.standardizer import get_standardizer
            std = get_standardizer()
            lowered = stripped.lower()
            for lookup in (std.season_lookup, std.vehicle_lookup,
                           std.road_type_lookup, std.meteorology_lookup,
                           std.stability_lookup):
                if lowered in lookup:
                    return True
        except Exception:
            pass
        # single short word, no spaces
        # Guard: Chinese parameter values are ≤6 chars; longer = sentence
        if len(stripped.split()) == 1 and len(stripped) <= 6:
            return True
        return False

    @staticmethod
    def _anchor_matches(
        completed_ao: AnalyticalObjective,
        proposed_tool: str,
        proposed_args: Dict[str, Any],
    ) -> bool:
        # tool match
        prior_tools = {r.tool for r in getattr(completed_ao, "tool_call_log", []) or [] if r.success}
        if proposed_tool in prior_tools:
            return True
        # file_path match
        proposed_file = str(proposed_args.get("file_path") or "").strip()
        if proposed_file:
            for r in getattr(completed_ao, "tool_call_log", []) or []:
                if not r.success:
                    continue
                prev_file = str(r.args_compact.get("file_path") or "").strip()
                if prev_file and proposed_file == prev_file:
                    return True
        return False

    @staticmethod
    def _record_ao_id(record: ToolCallRecord, current_ao: Any) -> Optional[str]:
        return getattr(current_ao, "ao_id", None)
