"""Unit tests for B validator (contract-grounding filter).

Phase 5.3 Round 3.1 — B validator only (Task 105).
"""

import pytest
from core.contracts.reconciler import (
    ContractGroundingResult,
    _compute_allowed_slots,
    _load_tool_contract,
    _normalize_candidates,
    filter_clarify_candidates,
    filter_stage2_missing_required,
)


# ── _normalize_candidates ──────────────────────────────────────────────

def test_normalize_candidates_preserves_order():
    result = _normalize_candidates(["b", "a", "c"])
    assert result == ["b", "a", "c"]


def test_normalize_candidates_removes_duplicates():
    result = _normalize_candidates(["a", "b", "a", "c", "b"])
    assert result == ["a", "b", "c"]


def test_normalize_candidates_drops_empty_and_malformed():
    result = _normalize_candidates(["a", "", "  ", None, "b"])
    assert result == ["a", "b"]


def test_normalize_candidates_empty_input():
    assert _normalize_candidates([]) == []
    assert _normalize_candidates(None) == []


# ── _load_tool_contract ────────────────────────────────────────────────

def test_load_tool_contract_calculate_macro_emission():
    contract = _load_tool_contract("calculate_macro_emission")
    assert contract is not None
    assert "pollutants" in contract["required_slots"]
    assert "season" in contract["optional_slots"]


def test_load_tool_contract_unknown_tool():
    contract = _load_tool_contract("nonexistent_tool_xyz")
    assert contract is None


def test_load_tool_contract_empty_name():
    assert _load_tool_contract("") is None
    assert _load_tool_contract("   ") is None


# ── _compute_allowed_slots ─────────────────────────────────────────────

def test_compute_allowed_slots_union_required_and_followup():
    contract = {
        "required_slots": ["pollutants"],
        "clarification_followup_slots": ["model_year"],
    }
    allowed = _compute_allowed_slots(contract)
    assert set(allowed) == {"pollutants", "model_year"}


def test_compute_allowed_slots_empty_followup():
    contract = {
        "required_slots": ["pollutants"],
        "clarification_followup_slots": [],
    }
    allowed = _compute_allowed_slots(contract)
    assert allowed == ["pollutants"]


def test_compute_allowed_slots_optional_not_included():
    contract = {
        "required_slots": ["pollutants"],
        "clarification_followup_slots": [],
        "optional_slots": ["season", "scenario_label"],
    }
    allowed = _compute_allowed_slots(contract)
    assert "season" not in allowed
    assert "scenario_label" not in allowed


# ── filter_stage2_missing_required ─────────────────────────────────────

def test_filter_stage2_drops_vehicle_type_and_road_type_for_macro():
    """Task 105 scenario: hallucinated slots for calculate_macro_emission."""
    result = filter_stage2_missing_required(
        "calculate_macro_emission",
        ["vehicle_type", "road_type"],
    )
    assert result.is_contract_found is True
    assert result.original_slots == ["vehicle_type", "road_type"]
    assert result.grounded_slots == []
    assert set(result.dropped_slots) == {"vehicle_type", "road_type"}
    assert len(result.dropped_reasons) == 2


def test_filter_stage2_preserves_pollutants_for_macro():
    """Genuine required slot must survive filtering."""
    result = filter_stage2_missing_required(
        "calculate_macro_emission",
        ["pollutants"],
    )
    assert result.grounded_slots == ["pollutants"]
    assert result.dropped_slots == []


def test_filter_stage2_mixed_preserves_only_contract_slots():
    result = filter_stage2_missing_required(
        "calculate_macro_emission",
        ["pollutants", "vehicle_type", "road_type", "scenario_label"],
    )
    assert result.grounded_slots == ["pollutants"]
    assert set(result.dropped_slots) == {"vehicle_type", "road_type", "scenario_label"}


def test_filter_stage2_empty_input():
    result = filter_stage2_missing_required("calculate_macro_emission", [])
    assert result.is_contract_found is True
    assert result.original_slots == []
    assert result.grounded_slots == []
    assert result.dropped_slots == []


def test_filter_stage2_unknown_tool_returns_diagnostic():
    result = filter_stage2_missing_required("unknown_tool_abc", ["slot1", "slot2"])
    assert result.is_contract_found is False
    assert result.original_slots == ["slot1", "slot2"]
    assert "unknown_tool_contract" in result.dropped_reasons[0]


def test_filter_stage2_query_emission_factors_with_followup():
    """query_emission_factors has required=[vehicle_type,pollutants] + followup=[model_year]."""
    result = filter_stage2_missing_required(
        "query_emission_factors",
        ["pollutants", "model_year", "season"],
    )
    assert result.is_contract_found is True
    # pollutants is required; model_year is followup => both allowed
    # season is optional, NOT in allowed => dropped
    assert set(result.grounded_slots) == {"pollutants", "model_year"}
    assert "season" in result.dropped_slots


# ── filter_clarify_candidates ──────────────────────────────────────────

def test_filter_clarify_candidates_drops_non_contract_slots():
    """Clarify candidates must be filtered like missing_required."""
    result = filter_clarify_candidates(
        "calculate_macro_emission",
        ["vehicle_type", "road_type", "season"],
    )
    assert result.source == "clarify_candidates"
    assert result.grounded_slots == []
    assert set(result.dropped_slots) == {"vehicle_type", "road_type", "season"}


def test_filter_clarify_candidates_preserves_contract_slots():
    result = filter_clarify_candidates(
        "calculate_macro_emission",
        ["pollutants"],
    )
    assert result.grounded_slots == ["pollutants"]


def test_filter_clarify_candidates_empty_input():
    result = filter_clarify_candidates("calculate_macro_emission", [])
    assert result.grounded_slots == []


def test_filter_clarify_candidates_unknown_tool_returns_diagnostic():
    result = filter_clarify_candidates("unknown_tool_xyz", ["slot1"])
    assert result.is_contract_found is False


# ── ContractGroundingResult ────────────────────────────────────────────

def test_contract_grounding_result_trace_payload():
    result = filter_stage2_missing_required(
        "calculate_macro_emission",
        ["vehicle_type", "road_type"],
    )
    payload = result.trace_payload
    assert payload["tool_name"] == "calculate_macro_emission"
    assert payload["source"] == "stage2_missing_required"
    assert "original" in payload
    assert "allowed" in payload
    assert "grounded" in payload
    assert "dropped" in payload
    assert "dropped_reasons" in payload


def test_contract_grounding_result_fields():
    result = filter_stage2_missing_required(
        "calculate_macro_emission",
        ["vehicle_type"],
    )
    assert result.tool_name == "calculate_macro_emission"
    assert result.source == "stage2_missing_required"
    assert result.contract_source == "config/tool_contracts.yaml"
    assert isinstance(result.original_slots, list)
    assert isinstance(result.allowed_slots, list)
    assert isinstance(result.grounded_slots, list)
    assert isinstance(result.dropped_slots, list)
    assert isinstance(result.dropped_reasons, list)
    assert isinstance(result.trace_payload, dict)


def test_empty_factory():
    result = ContractGroundingResult.empty("my_tool", "my_source")
    assert result.tool_name == "my_tool"
    assert result.source == "my_source"
    assert result.is_contract_found is False
    assert result.grounded_slots == []
    assert "my_source" in str(result.trace_payload)


# ── B has no decision field ────────────────────────────────────────────

def test_b_output_has_no_decision_field():
    """B must not output proceed/clarify/deliberate decisions."""
    result = filter_stage2_missing_required(
        "calculate_macro_emission",
        ["vehicle_type", "pollutants"],
    )
    for forbidden in ("decision", "decision_value", "proceed", "clarify", "deliberate"):
        assert not hasattr(result, forbidden), f"B must not have {forbidden}"


# ── ContractGroundingResult constructability ───────────────────────────

def test_can_construct_directly():
    result = ContractGroundingResult(
        tool_name="test_tool",
        source="test_source",
        original_slots=["a", "b"],
        allowed_slots=["a"],
        grounded_slots=["a"],
        dropped_slots=["b"],
        dropped_reasons=["b not in allowed"],
        contract_source="test.yaml",
        is_contract_found=True,
        trace_payload={"key": "value"},
    )
    assert result.is_contract_found is True
    assert result.grounded_slots == ["a"]
