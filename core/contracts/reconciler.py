"""B validator + A reconciler for Phase 5.3 contract governance.

B validator (Round 3.1): contract-grounding filter for LLM-hallucinated slots.
A reconciler (Round 3.2): multi-source arbitration across P1 (Stage 2 LLM),
  P2 (YAML stage 3), and P3 (readiness gate).

B validator is deterministic governance:
  - Input: slot list + tool_name
  - Output: ContractGroundingResult (grounded/dropped partition + evidence)
  - B does NOT output proceed/clarify/deliberate.
  - B does NOT call PCM/readiness/decision components.

A reconciler is arbitration, not "P2 always wins":
  - Consumes P1 (stage2_raw), P2 (stage3_yaml), P3 (readiness_gate), optional B result.
  - F1 validation must pass before P1 is considered.
  - B is advisory input only; it does not decide.
  - Rules A1-A4 with explicit source_trace and trust labels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from tools.contract_loader import get_tool_contract_registry


@dataclass
class ContractGroundingResult:
    """B validator output: grounded vs dropped slot partition for a single filter call."""

    tool_name: str
    source: str  # "stage2_missing_required" or "clarify_candidates"
    original_slots: List[str] = field(default_factory=list)
    allowed_slots: List[str] = field(default_factory=list)
    grounded_slots: List[str] = field(default_factory=list)
    dropped_slots: List[str] = field(default_factory=list)
    dropped_reasons: List[str] = field(default_factory=list)
    contract_source: str = ""
    is_contract_found: bool = False
    trace_payload: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def empty(
        cls,
        tool_name: str = "",
        source: str = "",
        reason: str = "unknown_tool_contract",
    ) -> ContractGroundingResult:
        return cls(
            tool_name=tool_name,
            source=source,
            is_contract_found=False,
            dropped_reasons=[reason],
            trace_payload={"tool_name": tool_name, "source": source, "error": reason},
        )


def _load_tool_contract(tool_name: str) -> Optional[Dict[str, Any]]:
    """Load a single tool's contract spec from the YAML registry.

    Returns None if the tool is not found in the registry.
    """
    if not tool_name or not tool_name.strip():
        return None
    try:
        registry = get_tool_contract_registry()
    except Exception:
        return None

    required = list(registry.get_required_slots(tool_name) or [])
    optional = list(registry.get_optional_slots(tool_name) or [])
    followup = list(registry.get_clarification_followup_slots(tool_name) or [])
    confirm = list(registry.get_confirm_first_slots(tool_name) or [])
    defaults = dict(registry.get_defaults(tool_name) or {})

    tool_found = False
    for definition in registry.get_tool_definitions():
        func = definition.get("function") if isinstance(definition, dict) else None
        name = str((func or {}).get("name") or "").strip()
        if name == tool_name:
            tool_found = True
            break

    if not tool_found:
        return None

    return {
        "required_slots": required,
        "optional_slots": optional,
        "clarification_followup_slots": followup,
        "confirm_first_slots": confirm,
        "defaults": defaults,
    }


def _compute_allowed_slots(tool_contract: Dict[str, Any]) -> List[str]:
    """Compute allowed_slots = required_slots ∪ clarification_followup_slots."""
    required = list(tool_contract.get("required_slots") or [])
    followup = list(tool_contract.get("clarification_followup_slots") or [])
    allowed: List[str] = []
    seen: set = set()
    for slot in required + followup:
        s = str(slot).strip()
        if s and s not in seen:
            allowed.append(s)
            seen.add(s)
    return allowed


def _normalize_candidates(candidates: List[Any]) -> List[str]:
    """Normalize and deduplicate candidates, dropping empty/malformed values."""
    result: List[str] = []
    seen: set = set()
    for item in candidates or []:
        s = str(item).strip() if item is not None else ""
        if not s:
            continue
        if s in seen:
            continue
        result.append(s)
        seen.add(s)
    return result


def filter_stage2_missing_required(
    tool_name: str,
    missing_required: List[str],
) -> ContractGroundingResult:
    """Filter stage2_raw.missing_required against the tool's YAML contract.

    Only slots in allowed_slots (required ∪ clarification_followup) pass through.
    Hallucinated or unrelated slots are dropped with evidence.
    """
    original = _normalize_candidates(missing_required)
    contract = _load_tool_contract(tool_name)
    if contract is None:
        result = ContractGroundingResult.empty(tool_name, "stage2_missing_required")
        result.original_slots = original
        return result

    allowed = _compute_allowed_slots(contract)
    allowed_set = set(allowed)

    grounded: List[str] = []
    dropped: List[str] = []
    dropped_reasons: List[str] = []

    for slot in original:
        if slot in allowed_set:
            grounded.append(slot)
        else:
            dropped.append(slot)
            dropped_reasons.append(f"{slot} not in required_slots U clarification_followup_slots")

    return ContractGroundingResult(
        tool_name=tool_name,
        source="stage2_missing_required",
        original_slots=original,
        allowed_slots=allowed,
        grounded_slots=grounded,
        dropped_slots=dropped,
        dropped_reasons=dropped_reasons,
        contract_source="config/tool_contracts.yaml",
        is_contract_found=True,
        trace_payload={
            "tool_name": tool_name,
            "source": "stage2_missing_required",
            "original": original,
            "allowed": allowed,
            "grounded": grounded,
            "dropped": dropped,
            "dropped_reasons": dropped_reasons,
        },
    )


def filter_clarify_candidates(
    tool_name: str,
    candidates: List[str],
) -> ContractGroundingResult:
    """Filter readiness_gate clarify_candidates against the tool's YAML contract.

    Same contract-grounding logic as filter_stage2_missing_required but
    sourced from clarify_candidates (P3 readiness output).
    """
    original = _normalize_candidates(candidates)
    contract = _load_tool_contract(tool_name)
    if contract is None:
        result = ContractGroundingResult.empty(tool_name, "clarify_candidates")
        result.original_slots = original
        return result

    allowed = _compute_allowed_slots(contract)
    allowed_set = set(allowed)

    grounded: List[str] = []
    dropped: List[str] = []
    dropped_reasons: List[str] = []

    for slot in original:
        if slot in allowed_set:
            grounded.append(slot)
        else:
            dropped.append(slot)
            dropped_reasons.append(f"{slot} not in required_slots U clarification_followup_slots")

    return ContractGroundingResult(
        tool_name=tool_name,
        source="clarify_candidates",
        original_slots=original,
        allowed_slots=allowed,
        grounded_slots=grounded,
        dropped_slots=dropped,
        dropped_reasons=dropped_reasons,
        contract_source="config/tool_contracts.yaml",
        is_contract_found=True,
        trace_payload={
            "tool_name": tool_name,
            "source": "clarify_candidates",
            "original": original,
            "allowed": allowed,
            "grounded": grounded,
            "dropped": dropped,
            "dropped_reasons": dropped_reasons,
        },
    )


# ══════════════════════════════════════════════════════════════════════════
# A Reconciler (Phase 5.3 Round 3.2 — Task 110)
# ══════════════════════════════════════════════════════════════════════════


@dataclass
class Stage2RawSource:
    """P1: Stage 2 LLM raw decision extracted from stage2_payload.

    Mirrors the LLM's decision field plus F1 validation status.
    """

    decision_value: str = ""  # "proceed" | "clarify" | "deliberate"
    decision_confidence: float = 0.0
    decision_reasoning: str = ""
    clarification_question: str = ""
    missing_required: List[str] = field(default_factory=list)
    needs_clarification: bool = False
    resolved_tool: str = ""
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    # F1 validation result (set by caller via validate_decision)
    f1_valid: bool = False
    f1_fallback_reason: str = ""


@dataclass
class ReadinessGateState:
    """P3: Readiness gate disposition from ERC.

    Captures the ERC's determination even when Q3 gate defers the hard-block.
    """

    disposition: str = ""  # "proceed" | "q3_defer" | "hard_block"
    clarify_candidates: List[str] = field(default_factory=list)
    clarify_required_candidates: List[str] = field(default_factory=list)
    clarify_optional_candidates: List[str] = field(default_factory=list)
    hardcoded_recommendation: str = ""
    has_direct_execution: bool = False
    force_proceed_reason: str = ""


@dataclass
class ReconciledDecision:
    """A reconciler output: 7 core fields — no execution_chain / f1_valid / f1_fallback_reason."""

    decision_value: str = ""  # "proceed" | "clarify" | "deliberate"
    reconciled_missing_required: List[str] = field(default_factory=list)
    clarification_question: str = ""
    deliberative_reasoning: str = ""
    reasoning: str = ""
    source_trace: Dict[str, Any] = field(default_factory=dict)
    applied_rule_id: str = ""


# ── P1 / P2 / P3 builders ──────────────────────────────────────────────


def build_p1_from_stage2_payload(
    stage2_payload: Optional[Dict[str, Any]],
    is_valid: bool = False,
    fallback_reason: str = "",
) -> Stage2RawSource:
    """Extract P1 (Stage2RawSource) from a stage2_payload dict."""
    if not isinstance(stage2_payload, dict):
        return Stage2RawSource(f1_valid=is_valid, f1_fallback_reason=fallback_reason)

    decision = stage2_payload.get("decision") if isinstance(stage2_payload.get("decision"), dict) else {}
    return Stage2RawSource(
        decision_value=str(decision.get("value") or "").strip().lower(),
        decision_confidence=float(decision.get("confidence", 0)),
        decision_reasoning=str(decision.get("reasoning") or "").strip(),
        clarification_question=str(decision.get("clarification_question") or "").strip(),
        missing_required=[str(s) for s in (stage2_payload.get("missing_required") or []) if str(s).strip()],
        needs_clarification=bool(stage2_payload.get("needs_clarification")),
        resolved_tool=str((stage2_payload.get("intent") or {}).get("tool") or "").strip(),
        raw_payload=dict(stage2_payload),
        f1_valid=is_valid,
        f1_fallback_reason=fallback_reason,
    )


def build_p2_from_stage3_yaml(
    stage3_yaml: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Normalize P2 (stage3_yaml) from ERC metadata."""
    if not isinstance(stage3_yaml, dict):
        return {
            "missing_required": [],
            "rejected_slots": [],
            "active_required_slots": [],
            "optional_classification": {},
        }
    return {
        "missing_required": [
            str(s) for s in (stage3_yaml.get("missing_required") or []) if str(s).strip()
        ],
        "rejected_slots": [
            str(s) for s in (stage3_yaml.get("rejected_slots") or []) if str(s).strip()
        ],
        "active_required_slots": [
            str(s) for s in (stage3_yaml.get("active_required_slots") or []) if str(s).strip()
        ],
        "optional_classification": dict(stage3_yaml.get("optional_classification") or {}),
    }


def build_p3_from_readiness_gate(
    readiness_gate: Optional[Dict[str, Any]],
) -> ReadinessGateState:
    """Extract P3 (ReadinessGateState) from ERC readiness_gate metadata."""
    if not isinstance(readiness_gate, dict):
        return ReadinessGateState()

    return ReadinessGateState(
        disposition=str(readiness_gate.get("disposition") or "").strip(),
        clarify_candidates=[
            str(s) for s in (readiness_gate.get("clarify_candidates") or []) if str(s).strip()
        ],
        clarify_required_candidates=[
            str(s) for s in (readiness_gate.get("clarify_required_candidates") or []) if str(s).strip()
        ],
        clarify_optional_candidates=[
            str(s) for s in (readiness_gate.get("clarify_optional_candidates") or []) if str(s).strip()
        ],
        hardcoded_recommendation=str(readiness_gate.get("hardcoded_recommendation") or "").strip(),
        has_direct_execution=bool(readiness_gate.get("has_direct_execution")),
        force_proceed_reason=str(readiness_gate.get("force_proceed_reason") or "").strip(),
    )


# ── F1 guard ────────────────────────────────────────────────────────────


def _f1_validate_p1(p1: Stage2RawSource) -> bool:
    """Check whether P1 has a valid F1-passed proceed/clarify/deliberate decision.

    Returns True if P1 can be used for reconciliation.
    """
    return (
        p1.f1_valid
        and p1.decision_value in {"proceed", "clarify", "deliberate"}
    )


# ── A reconcile ─────────────────────────────────────────────────────────


def reconcile(
    p1: Stage2RawSource,
    p2: Dict[str, Any],
    p3: ReadinessGateState,
    b_result: Optional[ContractGroundingResult] = None,
    tool_name: str = "",
) -> ReconciledDecision:
    """Arbitrate across P1 (Stage 2 LLM), P2 (YAML stage 3), P3 (readiness gate).

    B result is advisory only — it does not decide.
    Rules are evaluated in priority order A1 → A2 → A3 → A4.
    """
    source_trace: Dict[str, Any] = {
        "p1": {
            "decision_value": p1.decision_value,
            "f1_valid": p1.f1_valid,
            "confidence": p1.decision_confidence,
            "missing_required": list(p1.missing_required),
            "trust": "llm_semantic",
        },
        "p2": {
            "missing_required": list(p2.get("missing_required") or []),
            "rejected_slots": list(p2.get("rejected_slots") or []),
            "active_required_slots": list(p2.get("active_required_slots") or []),
            "trust": "yaml_deterministic",
        },
        "p3": {
            "disposition": p3.disposition,
            "hardcoded_recommendation": p3.hardcoded_recommendation,
            "has_direct_execution": p3.has_direct_execution,
            "force_proceed_reason": p3.force_proceed_reason,
            "clarify_required_candidates": list(p3.clarify_required_candidates),
            "trust": "readiness_heuristic",
        },
    }

    if b_result is not None:
        source_trace["b"] = {
            "grounded": list(b_result.grounded_slots),
            "dropped": list(b_result.dropped_slots),
            "is_contract_found": b_result.is_contract_found,
            "trust": "contract_deterministic",
        }

    p2_missing: List[str] = list(p2.get("missing_required") or [])
    p2_rejected: List[str] = list(p2.get("rejected_slots") or [])
    p3_is_hard_block: bool = (
        p3.hardcoded_recommendation == "clarify"
        and bool(p3.clarify_required_candidates)
        and not bool(p3.force_proceed_reason)
    )

    # ── Rule A1 — proceed supported ──────────────────────────────────
    if (
        p1.decision_value == "proceed"
        and _f1_validate_p1(p1)
        and not p2_missing
        and not p2_rejected
        and not p3_is_hard_block
    ):
        return ReconciledDecision(
            decision_value="proceed",
            reasoning="Stage 2 proceed, F1 valid, YAML complete, readiness clear",
            source_trace=source_trace,
            applied_rule_id="R_A_STAGE2_PROCEED_SUPPORTED_BY_YAML_AND_READINESS",
        )

    # ── Rule A2 — true YAML missing required ─────────────────────────
    if p2_missing:
        return ReconciledDecision(
            decision_value="clarify",
            reconciled_missing_required=list(p2_missing),
            reasoning=f"YAML contract requires: {', '.join(p2_missing)}",
            source_trace=source_trace,
            applied_rule_id="R_A_YAML_REQUIRED_MISSING",
        )

    # ── Rule A3 — B-filtered hallucinated slots ──────────────────────
    if (
        p1.decision_value in ("clarify", "proceed")
        and _f1_validate_p1(p1)
        and p1.missing_required
        and b_result is not None
        and b_result.is_contract_found
        and not b_result.grounded_slots
        and not p2_missing
        and not p2_rejected
        and not p3_is_hard_block
    ):
        return ReconciledDecision(
            decision_value="proceed",
            reasoning=(
                f"Stage 2 missing slots {p1.missing_required} dropped by B validation; "
                "YAML and readiness clear"
            ),
            source_trace=source_trace,
            applied_rule_id="R_A_B_FILTERED_EMPTY_WITH_P2P3_SUPPORT",
        )

    # ── Rule A4 — defer to readiness ─────────────────────────────────
    if p3_is_hard_block:
        return ReconciledDecision(
            decision_value="clarify",
            reconciled_missing_required=list(p3.clarify_required_candidates),
            reasoning=f"Defer to readiness: required candidates {p3.clarify_required_candidates}",
            source_trace=source_trace,
            applied_rule_id="R_A_DEFER_TO_READINESS",
        )

    # P3 says proceed (has direct_execution or force_proceed_reason)
    if p3.has_direct_execution or p3.force_proceed_reason:
        return ReconciledDecision(
            decision_value="proceed",
            reasoning=(
                f"Readiness gate proceed"
                + (f" ({p3.force_proceed_reason})" if p3.force_proceed_reason else "")
            ),
            source_trace=source_trace,
            applied_rule_id="R_A_DEFER_TO_READINESS",
        )

    # Degrade safely: keep P1 if valid, else clarify
    if _f1_validate_p1(p1) and p1.decision_value == "proceed":
        return ReconciledDecision(
            decision_value="proceed",
            reasoning="Degrade: P1 proceed with no P2/P3 contradiction",
            source_trace=source_trace,
            applied_rule_id="R_A_DEFER_TO_READINESS",
        )

    return ReconciledDecision(
        decision_value="clarify",
        reasoning="Degrade: no clear proceed path — default clarify",
        source_trace=source_trace,
        applied_rule_id="R_A_DEFER_TO_READINESS",
    )
