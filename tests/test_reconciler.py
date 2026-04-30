"""Unit tests for Phase 5.3 Round 3.2 — A reconciler.

Tests rules A1-A4, source transport, and ReconciledDecision contract.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from core.contracts.reconciler import (
    ContractGroundingResult,
    ReadinessGateState,
    ReconciledDecision,
    Stage2RawSource,
    build_p1_from_stage2_payload,
    build_p2_from_stage3_yaml,
    build_p3_from_readiness_gate,
    filter_stage2_missing_required,
    reconcile,
)


# ── Builder helpers ────────────────────────────────────────────────────


def _p1_proceed(**overrides):
    kwargs = {
        "decision_value": "proceed",
        "decision_confidence": 0.9,
        "f1_valid": True,
    }
    kwargs.update(overrides)
    return Stage2RawSource(**kwargs)


def _p1_clarify(missing_required=None, **overrides):
    kwargs = {
        "decision_value": "clarify",
        "decision_confidence": 0.85,
        "f1_valid": True,
        "missing_required": missing_required or ["vehicle_type", "pollutants"],
        "clarification_question": "请问什么车型?",
    }
    kwargs.update(overrides)
    return Stage2RawSource(**kwargs)


def _p2_complete():
    return {"missing_required": [], "rejected_slots": [], "active_required_slots": ["vehicle_type", "pollutants"]}


def _p2_missing_vehicle_type():
    return {"missing_required": ["vehicle_type"], "rejected_slots": [], "active_required_slots": ["vehicle_type", "pollutants"]}


def _p3_proceed():
    return ReadinessGateState(
        disposition="proceed",
        has_direct_execution=True,
    )


def _p3_q3_defer_clarify():
    return ReadinessGateState(
        disposition="q3_defer",
        clarify_required_candidates=["vehicle_type"],
        hardcoded_recommendation="clarify",
    )


def _p3_hard_block():
    return ReadinessGateState(
        disposition="q3_defer",
        clarify_required_candidates=["vehicle_type", "pollutants"],
        hardcoded_recommendation="clarify",
    )


# ── Rule A1: proceed supported ─────────────────────────────────────────


def test_a1_proceed_supported():
    """P1 proceed + P2 complete + P3 no hard-block => proceed, rule A1."""
    result = reconcile(
        _p1_proceed(),
        _p2_complete(),
        _p3_proceed(),
    )
    assert result.decision_value == "proceed"
    assert result.applied_rule_id == "R_A_STAGE2_PROCEED_SUPPORTED_BY_YAML_AND_READINESS"
    assert result.reconciled_missing_required == []


def test_a1_f1_invalid_p1_falls_through():
    """P1 with F1 invalid must not trigger A1."""
    result = reconcile(
        _p1_proceed(f1_valid=False, f1_fallback_reason="confidence below 0.5"),
        _p2_complete(),
        _p3_proceed(),
    )
    # Falls to A4 degrade path
    assert result.decision_value != "proceed" or result.applied_rule_id != "R_A_STAGE2_PROCEED_SUPPORTED_BY_YAML_AND_READINESS"


# ── Rule A2: true YAML missing required ────────────────────────────────


def test_a2_yaml_missing_required_wins():
    """P1 proceed + P2 has missing required => clarify, rule A2."""
    result = reconcile(
        _p1_proceed(),
        _p2_missing_vehicle_type(),
        _p3_proceed(),
    )
    assert result.decision_value == "clarify"
    assert result.applied_rule_id == "R_A_YAML_REQUIRED_MISSING"
    assert "vehicle_type" in result.reconciled_missing_required


# ── Rule A3: B-filtered hallucinated slots ─────────────────────────────


def test_a3_b_filtered_empty_with_p2p3_support():
    """P1 clarify + B filters missing to empty + P2/P3 clear => proceed, rule A3."""
    # "speed_limit" is not in any query_emission_factors slot list
    p1 = _p1_clarify(missing_required=["speed_limit"])
    p2 = _p2_complete()
    p3 = _p3_proceed()

    b_result = filter_stage2_missing_required("query_emission_factors", p1.missing_required)
    assert b_result.grounded_slots == []
    assert "speed_limit" in b_result.dropped_slots

    result = reconcile(p1, p2, p3, b_result=b_result)
    assert result.decision_value == "proceed"
    assert result.applied_rule_id == "R_A_B_FILTERED_EMPTY_WITH_P2P3_SUPPORT"


def test_a3_b_filtered_requires_p2p3_clear():
    """A3 must not fire when P2 has missing required."""
    p1 = _p1_clarify(missing_required=["model_year"])
    p2 = _p2_missing_vehicle_type()  # P2 has real missing
    p3 = _p3_proceed()

    b_result = filter_stage2_missing_required("query_emission_factors", p1.missing_required)
    result = reconcile(p1, p2, p3, b_result=b_result)
    # A2 fires first (P2 has missing) → clarify, not A3
    assert result.applied_rule_id == "R_A_YAML_REQUIRED_MISSING"


# ── Rule A4: defer to readiness ────────────────────────────────────────


def test_a4_p3_hard_block_not_bypassed():
    """P3 true hard-block (required candidates + hardcoded_recommendation=clarify) must not be bypassed."""
    result = reconcile(
        _p1_proceed(),
        _p2_complete(),  # P2 says complete
        _p3_hard_block(),  # P3 says clarify with required candidates
    )
    # A1 blocked because p3_is_hard_block is True
    # A2 doesn't fire (P2 missing empty)
    # A3 doesn't fire (no B result, or P1 is proceed not clarify)
    # A4 defers to P3 → clarify
    assert result.decision_value == "clarify"
    assert result.applied_rule_id == "R_A_DEFER_TO_READINESS"


def test_a4_no_p2_always_wins():
    """P3 true hard-block beats P2 complete — A is not P2-always-wins."""
    result = reconcile(
        _p1_proceed(),
        _p2_complete(),  # P2 complete
        _p3_hard_block(),  # P3 has hardcoded_recommendation=clarify
    )
    # P2 is complete but P3 has hard-block → A1 blocked, A4 defers
    assert result.decision_value == "clarify"
    assert result.applied_rule_id == "R_A_DEFER_TO_READINESS"


# ── Source trace ───────────────────────────────────────────────────────


def test_source_trace_contains_all_sources_and_trust_labels():
    """source_trace must include P1/P2/P3 with trust labels."""
    b_result = filter_stage2_missing_required("query_emission_factors", ["vehicle_type"])
    result = reconcile(
        _p1_proceed(),
        _p2_complete(),
        _p3_proceed(),
        b_result=b_result,
    )
    trace = result.source_trace
    assert isinstance(trace, dict)
    assert trace["p1"]["trust"] == "llm_semantic"
    assert trace["p2"]["trust"] == "yaml_deterministic"
    assert trace["p3"]["trust"] == "readiness_heuristic"
    assert "b" in trace
    assert trace["b"]["trust"] == "contract_deterministic"


# ── Unknown tool contract diagnostic ───────────────────────────────────


def test_b_result_unknown_tool_does_not_force_proceed():
    """When B returns empty (unknown tool), A3 must not fire and must not force proceed."""
    p1 = _p1_clarify(missing_required=["some_slot"])
    p2 = _p2_complete()
    p3 = _p3_proceed()

    b_result = filter_stage2_missing_required("nonexistent_tool_xyz", p1.missing_required)
    assert b_result.is_contract_found is False

    result = reconcile(p1, p2, p3, b_result=b_result)
    # A3 requires is_contract_found=True → doesn't fire
    # Falls to A4 → degrade: P1 clarify with valid F1 but no clear path
    assert result.applied_rule_id != "R_A_B_FILTERED_EMPTY_WITH_P2P3_SUPPORT"


# ── ReconciledDecision contract ────────────────────────────────────────


def test_reconciled_decision_has_exactly_7_core_fields():
    """ReconciledDecision must have exactly 7 core fields and no forbidden ones."""
    field_names = {f.name for f in fields(ReconciledDecision)}
    expected = {
        "decision_value",
        "reconciled_missing_required",
        "clarification_question",
        "deliberative_reasoning",
        "reasoning",
        "source_trace",
        "applied_rule_id",
    }
    assert field_names == expected

    forbidden = {"execution_chain", "f1_valid", "f1_fallback_reason"}
    assert field_names.isdisjoint(forbidden)


# ── Builder tests ──────────────────────────────────────────────────────


def test_build_p1_from_stage2_payload_proceed():
    payload = {
        "decision": {"value": "proceed", "confidence": 0.9, "reasoning": "all clear"},
        "missing_required": [],
        "needs_clarification": False,
        "intent": {"tool": "query_emission_factors"},
    }
    p1 = build_p1_from_stage2_payload(payload, is_valid=True)
    assert p1.decision_value == "proceed"
    assert p1.decision_confidence == 0.9
    assert p1.f1_valid is True
    assert p1.resolved_tool == "query_emission_factors"


def test_build_p1_from_stage2_payload_none():
    p1 = build_p1_from_stage2_payload(None)
    assert p1.decision_value == ""
    assert p1.f1_valid is False


def test_build_p2_from_stage3_yaml():
    stage3 = {
        "missing_required": ["vehicle_type"],
        "rejected_slots": ["foo_slot"],
        "active_required_slots": ["vehicle_type", "pollutants"],
        "optional_classification": {"no_default": ["season"]},
    }
    p2 = build_p2_from_stage3_yaml(stage3)
    assert p2["missing_required"] == ["vehicle_type"]
    assert p2["rejected_slots"] == ["foo_slot"]
    assert p2["active_required_slots"] == ["vehicle_type", "pollutants"]


def test_build_p2_from_none():
    p2 = build_p2_from_stage3_yaml(None)
    assert p2["missing_required"] == []
    assert p2["active_required_slots"] == []


def test_build_p3_from_readiness_gate():
    gate = {
        "disposition": "q3_defer",
        "clarify_candidates": ["vehicle_type"],
        "clarify_required_candidates": ["vehicle_type"],
        "hardcoded_recommendation": "clarify",
        "has_direct_execution": False,
    }
    p3 = build_p3_from_readiness_gate(gate)
    assert p3.disposition == "q3_defer"
    assert p3.hardcoded_recommendation == "clarify"
    assert p3.has_direct_execution is False


def test_build_p3_from_none():
    p3 = build_p3_from_readiness_gate(None)
    assert p3.disposition == ""
    assert p3.hardcoded_recommendation == ""


# ── P3 force_proceed overrides hardcoded_recommendation ───────────────


def test_p3_force_proceed_reason_disarms_hard_block():
    """P3 with force_proceed_reason is not treated as hard-block."""
    p3 = ReadinessGateState(
        disposition="proceed",
        hardcoded_recommendation="clarify",  # would be hard-block but...
        clarify_required_candidates=["season"],
        force_proceed_reason="probe_limit_reached",  # overrides
        has_direct_execution=True,
    )
    result = reconcile(_p1_proceed(), _p2_complete(), p3)
    # p3_is_hard_block is False because force_proceed_reason is set
    # A1 fires: P1 proceed + P2 complete + P3 not hard-block
    assert result.decision_value == "proceed"
    assert result.applied_rule_id == "R_A_STAGE2_PROCEED_SUPPORTED_BY_YAML_AND_READINESS"


# ── Degrade paths ──────────────────────────────────────────────────────


def test_degrade_safe_when_sources_missing():
    """When P2/P3 are empty defaults, valid P1 proceed degrades to proceed."""
    result = reconcile(
        _p1_proceed(),
        build_p2_from_stage3_yaml(None),
        build_p3_from_readiness_gate(None),
    )
    # A1 fires: P1 valid + P2 empty + P3 not hard-block
    assert result.decision_value == "proceed"
    assert result.applied_rule_id == "R_A_STAGE2_PROCEED_SUPPORTED_BY_YAML_AND_READINESS"


def test_degrade_clarify_when_no_clear_path():
    """When P1 invalid, P2 empty, P3 empty — no source supports proceed, degrade to clarify."""
    result = reconcile(
        Stage2RawSource(),  # empty P1, f1_valid=False
        _p2_complete(),
        ReadinessGateState(),  # empty P3, no has_direct_execution
    )
    # No source supports proceed → degrade to clarify
    assert result.decision_value == "clarify"
    assert result.applied_rule_id == "R_A_DEFER_TO_READINESS"
