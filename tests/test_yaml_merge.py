"""Regression coverage for E-8.1 tool-level YAML merge."""

from core.contracts.clarification_contract import ClarificationContract
from core.contracts.runtime_defaults import get_runtime_defaults
from core.contracts.stance_resolution_contract import StanceResolutionContract
from tools.contract_loader import get_tool_contract_registry


MIGRATED_TOOLS = (
    "query_emission_factors",
    "calculate_micro_emission",
    "calculate_macro_emission",
    "calculate_dispersion",
    "analyze_hotspots",
    "render_spatial_map",
    "query_knowledge",
)

EMPTY_SLOT_METADATA_TOOLS = ("analyze_file", "compare_scenarios", "clean_dataframe")


def test_registry_loads_yaml_merge_fields_for_all_contract_tools() -> None:
    registry = get_tool_contract_registry()
    tool_names = [
        definition["function"]["name"]
        for definition in registry.get_tool_definitions()
    ]

    assert set(MIGRATED_TOOLS).issubset(tool_names)
    assert set(EMPTY_SLOT_METADATA_TOOLS).issubset(tool_names)

    for tool_name in tool_names:
        assert registry.get_required_slots(tool_name) is not None
        assert registry.get_optional_slots(tool_name) is not None
        assert registry.get_defaults(tool_name) is not None
        assert registry.get_clarification_followup_slots(tool_name) is not None
        assert registry.get_confirm_first_slots(tool_name) is not None


def test_query_emission_factor_slot_contract_matches_legacy_mapping() -> None:
    registry = get_tool_contract_registry()

    assert registry.get_required_slots("query_emission_factors") == [
        "vehicle_type",
        "pollutants",
    ]
    assert registry.get_optional_slots("query_emission_factors") == [
        "model_year",
        "season",
        "road_type",
    ]
    assert registry.get_defaults("query_emission_factors") == {
        "season": "夏季",
        "road_type": "快速路",
    }
    assert registry.get_clarification_followup_slots("query_emission_factors") == [
        "model_year"
    ]
    assert registry.get_confirm_first_slots("query_emission_factors") == ["road_type"]


def test_tools_without_legacy_slot_metadata_return_empty_values() -> None:
    registry = get_tool_contract_registry()

    for tool_name in EMPTY_SLOT_METADATA_TOOLS:
        assert registry.get_required_slots(tool_name) == []
        assert registry.get_optional_slots(tool_name) == []
        assert registry.get_defaults(tool_name) == {}
        assert registry.get_clarification_followup_slots(tool_name) == []
        assert registry.get_confirm_first_slots(tool_name) == []


def test_stance_resolution_required_slots_match_migrated_contract() -> None:
    assert StanceResolutionContract._required_slots_for_tool("query_emission_factors") == [
        "vehicle_type",
        "pollutants",
    ]
    assert StanceResolutionContract._check_required_filled_presence(
        "query_emission_factors",
        {
            "vehicle_type": {"value": "Passenger Car"},
            "pollutants": {"value": ["CO2"]},
        },
    )
    assert not StanceResolutionContract._check_required_filled_presence(
        "query_emission_factors",
        {"vehicle_type": {"value": "Passenger Car"}},
    )


def test_clarification_contract_tool_spec_comes_from_contract_registry() -> None:
    ClarificationContract._tools_cache = None
    contract = object.__new__(ClarificationContract)

    assert contract._get_tool_spec("calculate_micro_emission") == {
        "required_slots": ["vehicle_type", "pollutants"],
        "optional_slots": ["season", "model_year"],
        "defaults": {"season": "夏季"},
        "clarification_followup_slots": [],
        "confirm_first_slots": ["season"],
    }
    assert contract._get_tool_spec("compare_scenarios") == {
        "required_slots": [],
        "optional_slots": [],
        "defaults": {},
        "clarification_followup_slots": [],
        "confirm_first_slots": [],
    }


def test_runtime_defaults_use_contract_defaults_with_runtime_override() -> None:
    assert get_runtime_defaults("query_emission_factors") == {
        "season": "夏季",
        "road_type": "快速路",
        "model_year": 2020,
    }
    assert get_runtime_defaults("calculate_macro_emission") == {"season": "夏季"}
