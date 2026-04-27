"""F1 safety net: validate LLM decision field before consumption."""

from __future__ import annotations

from typing import Optional, Tuple

VALID_DECISION_VALUES = {"proceed", "clarify", "deliberate"}


def validate_decision(stage2_output: dict) -> Tuple[bool, Optional[str]]:
    """Validate Stage 2 LLM decision field against F1 safety rules.

    Returns (is_valid, fallback_reason).  If is_valid is False, the caller
    MUST fall back to the existing hard-rule governance path.
    """
    if not isinstance(stage2_output, dict):
        return False, "stage2_output is not a dict"

    decision = stage2_output.get("decision")
    if not isinstance(decision, dict):
        return False, "decision field missing or not a dict"

    # (a) value present + in valid set
    value = str(decision.get("value") or "").strip().lower()
    if value not in VALID_DECISION_VALUES:
        return False, f"decision.value={value!r} not in {VALID_DECISION_VALUES}"

    # (b) confidence >= 0.5
    try:
        confidence = float(decision.get("confidence", 0))
    except (TypeError, ValueError):
        return False, f"decision.confidence={decision.get('confidence')!r} not numeric"
    if confidence < 0.5:
        return False, f"decision.confidence={confidence} below 0.5 threshold"

    # (c) value=proceed → missing_required must be []
    if value == "proceed":
        missing_required = stage2_output.get("missing_required")
        if isinstance(missing_required, list) and len(missing_required) > 0:
            return False, "decision=proceed but missing_required is non-empty"

    # (d) value=clarify → clarification_question non-empty
    if value == "clarify":
        question = str(decision.get("clarification_question") or "").strip()
        if not question:
            return False, "decision=clarify but clarification_question is empty"

    # (e) value=deliberate → reasoning non-empty
    if value == "deliberate":
        reasoning = str(decision.get("reasoning") or "").strip()
        if not reasoning:
            return False, "decision=deliberate but reasoning is empty"

    return True, None
