"""Consistency checks for declarative tool contracts."""

from core.readiness import get_action_catalog
from core.router import CONTINUATION_TOOL_KEYWORDS
from core.tool_dependencies import TOOL_GRAPH
from tools.contract_loader import get_tool_contract_registry
from tools.definitions import TOOL_DEFINITIONS


class TestToolContractConsistency:
    def test_tool_definitions_match_current_runtime(self) -> None:
        registry = get_tool_contract_registry()
        assert registry.get_tool_definitions() == TOOL_DEFINITIONS

    def test_tool_graph_matches_current_runtime(self) -> None:
        registry = get_tool_contract_registry()
        assert registry.get_tool_graph() == TOOL_GRAPH

    def test_action_catalog_matches_current_runtime(self) -> None:
        registry = get_tool_contract_registry()
        generated = registry.get_action_catalog_entries()
        current = [entry.to_dict() for entry in get_action_catalog()]
        assert generated == current

    def test_continuation_keywords_match_current_runtime(self) -> None:
        registry = get_tool_contract_registry()
        assert registry.get_continuation_keywords() == CONTINUATION_TOOL_KEYWORDS

    def test_param_standardization_map(self) -> None:
        registry = get_tool_contract_registry()
        assert registry.get_param_standardization_map() == {
            "query_emission_factors": {
                "vehicle_type": "vehicle_type",
                "pollutants": "pollutant_list",
                "season": "season",
                "road_type": "road_type",
            },
            "calculate_micro_emission": {
                "vehicle_type": "vehicle_type",
                "pollutants": "pollutant_list",
                "season": "season",
            },
            "calculate_macro_emission": {
                "pollutants": "pollutant_list",
                "season": "season",
            },
            "calculate_dispersion": {
                "meteorology": "meteorology",
                "stability_class": "stability_class",
                "pollutant": "pollutant",
            },
            "render_spatial_map": {
                "pollutant": "pollutant",
            },
        }
