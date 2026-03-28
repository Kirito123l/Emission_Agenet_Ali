"""Tests for scenario comparison calculations."""

from __future__ import annotations

from calculators.scenario_comparator import ScenarioComparator
from tests.test_context_store import make_dispersion_result, make_emission_result, make_hotspot_result


def make_emission_variant(label: str, co2: float, nox: float, l1_co2: float, l2_co2: float) -> dict:
    result = make_emission_result(label)
    result["data"]["summary"]["total_emissions_kg_per_hr"] = {"CO2": co2, "NOx": nox}
    result["data"]["results"][0]["total_emissions_kg_per_hr"]["CO2"] = l1_co2
    result["data"]["results"][1]["total_emissions_kg_per_hr"]["CO2"] = l2_co2
    return result


class TestEmissionComparison:
    def test_aggregate_deltas(self):
        comparator = ScenarioComparator()
        baseline = make_emission_variant("baseline", 100.0, 10.0, 70.0, 30.0)
        scenario = make_emission_variant("speed_30", 80.0, 8.0, 50.0, 30.0)

        result = comparator.compare("emission", baseline, scenario)
        assert result["aggregate"]["CO2"]["delta"] == -20.0
        assert result["aggregate"]["CO2"]["delta_pct"] == -20.0

    def test_per_link_changes(self):
        comparator = ScenarioComparator()
        baseline = make_emission_variant("baseline", 100.0, 10.0, 70.0, 30.0)
        scenario = make_emission_variant("speed_30", 80.0, 8.0, 35.0, 30.0)

        result = comparator.compare("emission", baseline, scenario)
        assert result["top_link_changes"][0]["link_id"] == "L1"

    def test_percentage_calculation(self):
        comparator = ScenarioComparator()
        baseline = make_emission_variant("baseline", 120.0, 10.0, 80.0, 40.0)
        scenario = make_emission_variant("speed_30", 90.0, 10.0, 60.0, 30.0)

        result = comparator.compare("emission", baseline, scenario)
        assert result["aggregate"]["CO2"]["delta_pct"] == -25.0

    def test_zero_baseline_handling(self):
        comparator = ScenarioComparator()
        baseline = make_emission_variant("baseline", 0.0, 0.0, 0.0, 0.0)
        scenario = make_emission_variant("speed_30", 10.0, 1.0, 5.0, 5.0)

        result = comparator.compare("emission", baseline, scenario)
        assert result["aggregate"]["CO2"]["delta_pct"] == 0.0


class TestDispersionComparison:
    def test_concentration_deltas(self):
        comparator = ScenarioComparator()
        baseline = make_dispersion_result("baseline")
        scenario = make_dispersion_result("windy")
        baseline["data"]["summary"]["mean_concentration"] = 1.0
        scenario["data"]["summary"]["mean_concentration"] = 0.7

        result = comparator.compare("dispersion", baseline, scenario)
        assert result["metrics"]["mean_concentration"]["delta"] == -0.3
        assert result["metrics"]["mean_concentration"]["delta_pct"] == -30.0

    def test_meteorology_changes_detected(self):
        comparator = ScenarioComparator()
        baseline = make_dispersion_result("baseline")
        scenario = make_dispersion_result("north_wind")
        baseline["data"]["meteorology_used"] = {"wind_direction": 225.0, "wind_speed": 2.5}
        scenario["data"]["meteorology_used"] = {"wind_direction": 315.0, "wind_speed": 2.5}

        result = comparator.compare("dispersion", baseline, scenario)
        assert result["meteorology_changes"]["wind_direction"]["scenario"] == 315.0


class TestMultiScenarioComparison:
    def test_two_scenarios_vs_baseline(self):
        comparator = ScenarioComparator()
        results = {
            "baseline": make_emission_variant("baseline", 100.0, 10.0, 70.0, 30.0),
            "speed_30": make_emission_variant("speed_30", 80.0, 8.0, 50.0, 30.0),
            "speed_45": make_emission_variant("speed_45", 90.0, 9.0, 60.0, 30.0),
        }

        result = comparator.multi_compare("emission", results)
        assert result["multi_comparison"] is True
        assert set(result["comparisons"].keys()) == {"speed_30", "speed_45"}

    def test_missing_scenario_handled(self):
        comparator = ScenarioComparator()
        result = comparator.multi_compare("hotspot", {"speed_30": make_hotspot_result("speed_30")})
        assert "error" in result

