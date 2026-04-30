"""Unit tests for Phase 5.3 Round 3.4 — Stage 1 slot protection in Stage2 merge.

Verifies that _merge_stage2_snapshot preserves deterministic Stage 1 fills
when Stage 2 LLM output would downgrade them to missing/empty.
"""

from __future__ import annotations

import pytest

from core.contracts.clarification_contract import ClarificationContract


def _make_contract():
    """Build a minimal ClarificationContract with just the merge method callable."""
    contract = ClarificationContract.__new__(ClarificationContract)
    contract.ao_manager = None
    contract.inner_router = None
    contract.runtime_config = None
    contract.llm_client = None
    return contract


# ── Stage 1 protection tests ──────────────────────────────────────────


def test_stage1_pollutants_preserved_when_stage2_downgrades_to_missing():
    """Stage 1 fills pollutants=["PM10"], Stage 2 says missing → merged keeps PM10."""
    contract = _make_contract()
    base = {
        "vehicle_type": {"value": "Refuse Truck", "source": "user", "confidence": 1.0, "raw_text": "垃圾车"},
        "pollutants": {"value": ["PM10"], "source": "user", "confidence": 1.0, "raw_text": ["PM10"]},
        "model_year": {"value": None, "source": "missing", "confidence": None, "raw_text": None},
    }
    llm = {
        "vehicle_type": {"value": "Refuse Truck", "source": "user", "confidence": 0.9, "raw_text": "垃圾车"},
        "pollutants": {"value": None, "source": "missing", "confidence": 0.0, "raw_text": None},
        "model_year": {"value": None, "source": "missing", "confidence": 0.0, "raw_text": None},
    }
    merged = contract._merge_stage2_snapshot(base, llm)
    assert merged["pollutants"]["value"] == ["PM10"]
    assert merged["pollutants"]["source"] == "user"
    assert merged["vehicle_type"]["value"] == "Refuse Truck"


def test_stage1_vehicle_type_preserved_when_stage2_downgrades():
    """Stage 1 vehicle_type filled, Stage 2 says missing → keeps vehicle_type."""
    contract = _make_contract()
    base = {
        "vehicle_type": {"value": "公交车", "source": "user", "confidence": 1.0, "raw_text": "公交车"},
        "pollutants": {"value": None, "source": "missing", "confidence": None, "raw_text": None},
    }
    llm = {
        "vehicle_type": {"value": None, "source": "missing", "confidence": 0.0, "raw_text": None},
        "pollutants": {"value": None, "source": "missing", "confidence": 0.0, "raw_text": None},
    }
    merged = contract._merge_stage2_snapshot(base, llm)
    assert merged["vehicle_type"]["value"] == "公交车"
    assert merged["vehicle_type"]["source"] == "user"


def test_stage1_empty_slot_accepts_stage2_fill():
    """Empty base slot + Stage 2 non-empty fill → accepts Stage 2 value."""
    contract = _make_contract()
    base = {
        "vehicle_type": {"value": None, "source": "missing", "confidence": None, "raw_text": None},
        "pollutants": {"value": None, "source": "missing", "confidence": None, "raw_text": None},
    }
    llm = {
        "vehicle_type": {"value": "小汽车", "source": "llm", "confidence": 0.8, "raw_text": "小汽车"},
        "pollutants": {"value": ["CO2"], "source": "llm", "confidence": 0.9, "raw_text": ["CO2"]},
    }
    merged = contract._merge_stage2_snapshot(base, llm)
    assert merged["vehicle_type"]["value"] == "小汽车"
    assert merged["vehicle_type"]["source"] == "llm"
    assert merged["pollutants"]["value"] == ["CO2"]


def test_stage2_non_missing_overwrites_stage1_value():
    """Stage 2 provides a different non-empty value → accepted (not a downgrade)."""
    contract = _make_contract()
    base = {
        "vehicle_type": {"value": "小汽车", "source": "user", "confidence": 1.0, "raw_text": "小汽车"},
    }
    llm = {
        "vehicle_type": {"value": "轻型货车", "source": "llm", "confidence": 0.9, "raw_text": "小汽车"},
    }
    merged = contract._merge_stage2_snapshot(base, llm)
    # Stage 2 non-empty update is accepted (refinement, not downgrade)
    assert merged["vehicle_type"]["value"] == "轻型货车"


def test_stage1_slot_not_in_llm_output_is_preserved():
    """Slot in base but not in LLM output → preserved unchanged."""
    contract = _make_contract()
    base = {
        "vehicle_type": {"value": "Refuse Truck", "source": "user", "confidence": 1.0, "raw_text": "垃圾车"},
        "pollutants": {"value": ["PM10"], "source": "user", "confidence": 1.0, "raw_text": ["PM10"]},
    }
    llm = {
        "model_year": {"value": "2020", "source": "llm", "confidence": 0.9, "raw_text": "2020"},
    }
    merged = contract._merge_stage2_snapshot(base, llm)
    assert merged["vehicle_type"]["value"] == "Refuse Truck"
    assert merged["pollutants"]["value"] == ["PM10"]
    assert merged["model_year"]["value"] == "2020"


def test_empty_list_value_is_treated_as_empty():
    """Stage 1 empty list [] is treated as empty — Stage 2 fill accepted."""
    contract = _make_contract()
    base = {
        "pollutants": {"value": [], "source": "user", "confidence": 1.0, "raw_text": None},
    }
    llm = {
        "pollutants": {"value": ["NOx"], "source": "llm", "confidence": 0.9, "raw_text": ["NOx"]},
    }
    merged = contract._merge_stage2_snapshot(base, llm)
    # [] is considered empty, so Stage 2 fill is accepted
    assert merged["pollutants"]["value"] == ["NOx"]


def test_empty_string_value_is_treated_as_empty():
    """Stage 1 empty string is treated as empty — Stage 2 fill accepted."""
    contract = _make_contract()
    base = {
        "season": {"value": "", "source": "user", "confidence": 1.0, "raw_text": None},
    }
    llm = {
        "season": {"value": "夏季", "source": "llm", "confidence": 0.8, "raw_text": "夏季"},
    }
    merged = contract._merge_stage2_snapshot(base, llm)
    assert merged["season"]["value"] == "夏季"


def test_stage2_valid_update_accepted():
    """Stage 2 non-empty, non-missing update with different value → accepted."""
    contract = _make_contract()
    base = {
        "season": {"value": "春季", "source": "default", "confidence": 0.5, "raw_text": None},
    }
    llm = {
        "season": {"value": "夏季", "source": "llm", "confidence": 0.9, "raw_text": "夏天"},
    }
    merged = contract._merge_stage2_snapshot(base, llm)
    assert merged["season"]["value"] == "夏季"
    assert merged["season"]["source"] == "llm"


def test_task110_style_stage1_pm10_stage2_all_missing():
    """Task 110 Turn 3 scenario: Stage 1 fills vehicle_type + pollutants,
    Stage 2 outputs all as missing → vehicle_type and pollutants preserved."""
    contract = _make_contract()
    base = {
        "vehicle_type": {"value": "Refuse Truck", "source": "user", "confidence": 1.0, "raw_text": "垃圾车"},
        "pollutants": {"value": ["PM10"], "source": "user", "confidence": 1.0, "raw_text": ["PM10"]},
        "model_year": {"value": None, "source": "missing", "confidence": None, "raw_text": None},
        "season": {"value": None, "source": "missing", "confidence": None, "raw_text": None},
        "road_type": {"value": None, "source": "missing", "confidence": None, "raw_text": None},
    }
    llm = {
        "vehicle_type": {"value": None, "source": "missing", "confidence": 0.0, "raw_text": None},
        "pollutants": {"value": None, "source": "missing", "confidence": 0.0, "raw_text": None},
        "model_year": {"value": None, "source": "missing", "confidence": 0.0, "raw_text": None},
        "season": {"value": None, "source": "missing", "confidence": 0.0, "raw_text": None},
        "road_type": {"value": None, "source": "missing", "confidence": 0.0, "raw_text": None},
    }
    merged = contract._merge_stage2_snapshot(base, llm)
    assert merged["vehicle_type"]["value"] == "Refuse Truck"
    assert merged["pollutants"]["value"] == ["PM10"]
    # model_year was already missing → stays missing
    assert merged["model_year"]["value"] is None


def test_normalize_sentinel_values_still_work_on_empty_base():
    """When base has no slot, sentinel values (Missing, UNKNOWN, n/a) are normalized."""
    contract = _make_contract()
    base = {}
    llm = {
        "model_year": {"value": "Missing", "source": "missing", "confidence": 0.0, "raw_text": None},
        "season": {"value": "UNKNOWN", "source": "inferred", "confidence": 0.4, "raw_text": None},
    }
    merged = contract._merge_stage2_snapshot(base, llm)
    # Base was empty, so LLM output is used; sentinel values normalized to None
    assert merged["model_year"]["value"] is None
    assert merged["model_year"]["source"] == "missing"
    assert merged["season"]["value"] is None
    assert merged["season"]["source"] == "missing"
