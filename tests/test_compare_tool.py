"""Tests for the compare_scenarios tool."""

from __future__ import annotations

import pytest

from core.context_store import SessionContextStore
from tools.scenario_compare import ScenarioCompareTool
from tests.test_context_store import make_dispersion_result, make_emission_result


def make_store() -> SessionContextStore:
    store = SessionContextStore()
    baseline_emission = make_emission_result("baseline")
    baseline_emission["data"]["summary"]["total_emissions_kg_per_hr"]["CO2"] = 100.0
    scenario_emission = make_emission_result("speed_30")
    scenario_emission["data"]["summary"]["total_emissions_kg_per_hr"]["CO2"] = 80.0

    baseline_dispersion = make_dispersion_result("baseline")
    baseline_dispersion["data"]["summary"]["mean_concentration"] = 1.0
    scenario_dispersion = make_dispersion_result("speed_30")
    scenario_dispersion["data"]["summary"]["mean_concentration"] = 0.8

    store.store_result("calculate_macro_emission", baseline_emission)
    store.store_result("calculate_macro_emission", scenario_emission)
    store.store_result("calculate_dispersion", baseline_dispersion)
    store.store_result("calculate_dispersion", scenario_dispersion)
    return store


class TestCompareScenariosTool:
    @pytest.mark.anyio
    async def test_single_emission_comparison(self):
        tool = ScenarioCompareTool()
        result = await tool.execute(
            result_types=["emission"],
            scenario="speed_30",
            _context_store=make_store(),
        )
        assert result.success is True
        assert result.data["emission"]["comparison_type"] == "emission"

    @pytest.mark.anyio
    async def test_multi_result_type_comparison(self):
        tool = ScenarioCompareTool()
        result = await tool.execute(
            result_types=["emission", "dispersion"],
            scenario="speed_30",
            _context_store=make_store(),
        )
        assert "emission" in result.data
        assert "dispersion" in result.data

    @pytest.mark.anyio
    async def test_multi_scenario_comparison(self):
        tool = ScenarioCompareTool()
        store = make_store()
        extra = make_emission_result("speed_45")
        extra["data"]["summary"]["total_emissions_kg_per_hr"]["CO2"] = 90.0
        store.store_result("calculate_macro_emission", extra)

        result = await tool.execute(
            result_types=["emission"],
            scenarios=["speed_30", "speed_45"],
            _context_store=store,
        )
        assert result.success is True
        assert result.data["emission"]["multi_comparison"] is True

    @pytest.mark.anyio
    async def test_no_context_store_error(self):
        tool = ScenarioCompareTool()
        result = await tool.execute(result_types=["emission"], scenario="speed_30")
        assert result.success is False
        assert "No context store available" in result.error

    @pytest.mark.anyio
    async def test_missing_baseline_error(self):
        tool = ScenarioCompareTool()
        store = SessionContextStore()
        store.store_result("calculate_macro_emission", make_emission_result("speed_30"))
        result = await tool.execute(
            result_types=["dispersion"],
            scenario="speed_30",
            _context_store=store,
        )
        assert "error" in result.data["dispersion"]

    @pytest.mark.anyio
    async def test_missing_scenario_error(self):
        tool = ScenarioCompareTool()
        result = await tool.execute(
            result_types=["emission"],
            scenario="missing_case",
            _context_store=make_store(),
        )
        assert "missing_case" in result.data["emission"]["error"]

    @pytest.mark.anyio
    async def test_chart_data_produced(self):
        tool = ScenarioCompareTool()
        result = await tool.execute(
            result_types=["emission"],
            scenario="speed_30",
            _context_store=make_store(),
        )
        assert result.chart_data is not None
        assert result.chart_data["type"] == "scenario_comparison"

    @pytest.mark.anyio
    async def test_summary_readable(self):
        tool = ScenarioCompareTool()
        result = await tool.execute(
            result_types=["emission", "dispersion"],
            scenario="speed_30",
            _context_store=make_store(),
        )
        assert result.summary.startswith("Scenario comparison:")
        assert len(result.summary) < 500

