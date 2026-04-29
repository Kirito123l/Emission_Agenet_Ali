"""Unit tests for core.snapshot_coercion (Phase 5.2 Round 3).

Covers all 5 coercion functions + generic loop in governed_router +
2 special post-processing hooks.
"""

from __future__ import annotations

import pytest

from core.governed_router import GovernedRouter
from core.snapshot_coercion import (
    apply_coercion,
    as_list,
    as_string,
    preserve,
    safe_float,
    safe_int,
)


# ---------------------------------------------------------------------------
# Individual coercion function tests
# ---------------------------------------------------------------------------

def test_preserve_returns_value_unchanged():
    assert preserve("hello") == "hello"
    assert preserve(42) == 42
    assert preserve([1, 2, 3]) == [1, 2, 3]
    assert preserve(None) is None


def test_as_list_wraps_scalar():
    assert as_list("NOx") == ["NOx"]
    assert as_list(42) == [42]


def test_as_list_preserves_existing_list():
    original = ["CO2", "NOx"]
    result = as_list(original)
    assert result == ["CO2", "NOx"]
    assert result is not original  # defensive copy


def test_as_list_returns_none_for_none():
    assert as_list(None) is None


def test_safe_int_converts_valid_string():
    assert safe_int("2022", "model_year") == 2022
    assert safe_int(2020, "model_year") == 2020


def test_safe_int_returns_none_on_invalid_value():
    assert safe_int("not_a_number", "slot") is None
    assert safe_int(None, "slot") is None


def test_safe_float_converts_valid_values():
    assert safe_float("3.14", "param") == 3.14
    assert safe_float(2.5, "param") == 2.5
    assert safe_float("5", "param") == 5.0


def test_safe_float_returns_none_on_invalid_value():
    assert safe_float("abc", "slot") is None
    assert safe_float(None, "slot") is None


def test_as_string_converts():
    assert as_string(42) == "42"
    assert as_string("hello") == "hello"
    assert as_string(None) is None


def test_apply_coercion_dispatches_to_correct_function():
    assert apply_coercion("preserve", [1, 2]) == [1, 2]
    assert apply_coercion("as_list", "CO2") == ["CO2"]
    assert apply_coercion("safe_int", "2020") == 2020
    assert apply_coercion("safe_float", "3.14") == 3.14
    assert apply_coercion("as_string", 42) == "42"


def test_apply_coercion_unknown_type_defaults_to_preserve():
    assert apply_coercion("nonexistent_type", "value") == "value"


def test_apply_coercion_none_value_returns_none():
    assert apply_coercion("safe_int", None) is None
    assert apply_coercion("as_list", None) is None


# ---------------------------------------------------------------------------
# Generic _snapshot_to_tool_args loop regression tests
# ---------------------------------------------------------------------------

def test_generic_loop_maps_factor_snapshot():
    """Existing test_snapshot_to_tool_args_maps_factor_snapshot behaviour preserved."""
    snapshot = {
        "vehicle_type": {"value": "Passenger Car", "source": "user"},
        "pollutants": {"value": ["NOx"], "source": "user"},
        "model_year": {"value": "2022", "source": "user"},
        "season": {"value": "冬季", "source": "user"},
        "road_type": {"value": "主干道", "source": "user"},
    }
    args = GovernedRouter._snapshot_to_tool_args("query_emission_factors", snapshot)
    assert args == {
        "vehicle_type": "Passenger Car",
        "pollutants": ["NOx"],
        "model_year": 2022,
        "season": "冬季",
        "road_type": "主干道",
    }


def test_generic_loop_applies_as_list_via_yaml():
    """pollutants scalar → list via YAML type_coercion."""
    snapshot = {
        "pollutants": {"value": "CO2", "source": "user"},
        "vehicle_type": {"value": "Transit Bus", "source": "user"},
    }
    args = GovernedRouter._snapshot_to_tool_args("calculate_macro_emission", snapshot)
    assert args["pollutants"] == ["CO2"]


def test_generic_loop_applies_safe_int_via_yaml():
    """model_year string → int via YAML type_coercion."""
    snapshot = {
        "vehicle_type": {"value": "Motorcycle", "source": "user"},
        "pollutants": {"value": ["CO"], "source": "user"},
        "model_year": {"value": "2021", "source": "user"},
    }
    args = GovernedRouter._snapshot_to_tool_args("calculate_micro_emission", snapshot)
    assert args["model_year"] == 2021


def test_generic_loop_skips_params_not_in_tool_schema():
    """Extra snapshot key not in tool's param list → skipped with warning log."""
    snapshot = {
        "vehicle_type": {"value": "Passenger Car", "source": "user"},
        "pollutants": {"value": ["NOx"], "source": "user"},
        "extra_unknown_param": {"value": "should_be_ignored", "source": "user"},
    }
    args = GovernedRouter._snapshot_to_tool_args("query_emission_factors", snapshot)
    assert "extra_unknown_param" not in args
    assert "vehicle_type" in args
    assert "pollutants" in args


# ---------------------------------------------------------------------------
# Special hook regression tests
# ---------------------------------------------------------------------------

def test_allow_factor_year_default_hook_injects_model_year():
    """When flag is set and model_year is missing, inject from config."""
    snapshot = {
        "vehicle_type": {"value": "Motorcycle", "source": "inferred"},
        "pollutants": {"value": ["CO"], "source": "user"},
    }
    args = GovernedRouter._snapshot_to_tool_args(
        "query_emission_factors",
        snapshot,
        allow_factor_year_default=True,
    )
    assert args["vehicle_type"] == "Motorcycle"
    assert args["pollutants"] == ["CO"]
    assert args["model_year"] == 2020


def test_pollutant_fallback_from_pollutants_dispersion():
    """Dispersion: pollutant missing → falls back to pollutants[0]."""
    snapshot = {
        "pollutants": {"value": ["NOx", "CO2"], "source": "user"},
        "scenario_label": {"value": "baseline", "source": "user"},
    }
    args = GovernedRouter._snapshot_to_tool_args("calculate_dispersion", snapshot)
    assert args["pollutant"] == "NOx"


def test_pollutant_fallback_from_pollutants_render_map():
    """Render spatial map: pollutant missing → falls back to pollutants[0]."""
    snapshot = {
        "pollutants": {"value": ["CO2"], "source": "user"},
    }
    args = GovernedRouter._snapshot_to_tool_args("render_spatial_map", snapshot)
    assert args["pollutant"] == "CO2"


def test_pollutant_fallback_not_applied_for_other_tools():
    """Other tools do NOT get pollutant fallback from pollutants[0]."""
    snapshot = {
        "pollutants": {"value": ["NOx"], "source": "user"},
        "vehicle_type": {"value": "Passenger Car", "source": "user"},
    }
    args = GovernedRouter._snapshot_to_tool_args("query_emission_factors", snapshot)
    assert "pollutant" not in args
    assert args["pollutants"] == ["NOx"]
