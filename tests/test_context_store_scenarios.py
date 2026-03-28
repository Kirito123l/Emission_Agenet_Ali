"""Tests for scenario-versioned SessionContextStore behavior."""

from __future__ import annotations

from core.context_store import SessionContextStore
from tests.test_context_store import make_dispersion_result, make_emission_result, make_hotspot_result


class TestMultiVersionStorage:
    def test_baseline_stored_by_default(self):
        store = SessionContextStore()
        store.store_result("calculate_macro_emission", make_emission_result())
        stored = store.get_by_type("emission")
        assert stored is not None
        assert stored.label == "baseline"

    def test_scenario_stored_with_label(self):
        store = SessionContextStore()
        store.store_result("calculate_macro_emission", make_emission_result("speed_30"))
        stored = store.get_by_type("emission", label="speed_30")
        assert stored is not None
        assert stored.label == "speed_30"

    def test_baseline_and_scenario_coexist(self):
        store = SessionContextStore()
        baseline = make_emission_result("baseline")
        scenario = make_emission_result("speed_30")
        store.store_result("calculate_macro_emission", baseline)
        store.store_result("calculate_macro_emission", scenario)
        assert store.get_by_type("emission", label="baseline").data == baseline
        assert store.get_by_type("emission", label="speed_30").data == scenario

    def test_get_scenario_pair(self):
        store = SessionContextStore()
        baseline = make_emission_result("baseline")
        scenario = make_emission_result("speed_30")
        store.store_result("calculate_macro_emission", baseline)
        store.store_result("calculate_macro_emission", scenario)
        stored_baseline, stored_scenario = store.get_scenario_pair("emission", "baseline", "speed_30")
        assert stored_baseline == baseline
        assert stored_scenario == scenario

    def test_list_scenarios(self):
        store = SessionContextStore()
        store.store_result("calculate_macro_emission", make_emission_result("baseline"))
        store.store_result("calculate_macro_emission", make_emission_result("speed_30"))
        store.store_result("calculate_dispersion", make_dispersion_result("speed_30"))
        listed = store.list_scenarios()
        assert listed["emission"] == ["baseline", "speed_30"]
        assert listed["dispersion"] == ["speed_30"]

    def test_scenario_limit_enforced(self):
        store = SessionContextStore()
        store.store_result("calculate_macro_emission", make_emission_result("baseline"))
        for index in range(7):
            store.store_result("calculate_macro_emission", make_emission_result(f"speed_{index}"))
        listed = store.list_scenarios("emission")["emission"]
        assert "baseline" in listed
        assert len([item for item in listed if item != "baseline"]) == store.MAX_SCENARIOS
        assert "speed_0" not in listed
        assert "speed_1" not in listed

    def test_dependency_invalidation(self):
        store = SessionContextStore()
        store.store_result("calculate_dispersion", make_dispersion_result("baseline"))
        store.store_result("analyze_hotspots", make_hotspot_result("baseline"))
        store.store_result("calculate_macro_emission", make_emission_result("baseline"))
        assert store.get_by_type("dispersion", label="baseline").metadata["stale"] is True
        assert store.get_by_type("hotspot", label="baseline").metadata["stale"] is True

    def test_fallback_to_baseline(self):
        store = SessionContextStore()
        baseline = make_dispersion_result("baseline")
        store.store_result("calculate_dispersion", baseline)
        resolved = store.get_result_for_tool("analyze_hotspots", label="speed_30")
        assert resolved == baseline


class TestContextSummaryWithScenarios:
    def test_summary_shows_versions(self):
        store = SessionContextStore()
        store.store_result("calculate_macro_emission", make_emission_result("baseline"))
        store.store_result("calculate_macro_emission", make_emission_result("speed_30"))
        summary = store.get_context_summary()
        assert "emission:" in summary
        assert "baseline=" in summary
        assert "speed_30=" in summary

