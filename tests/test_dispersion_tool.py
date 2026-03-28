"""Tests for the Sprint 9 dispersion tool integration."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from config import get_config
from core.memory import FactMemory
from core.router import UnifiedRouter
from services.llm_client import LLMResponse, ToolCall
from tools.dispersion import DispersionTool
from tools.registry import get_registry, init_tools


MOCK_MACRO_RESULT = {
    "success": True,
    "data": {
        "results": [
            {
                "link_id": "road_001",
                "link_length_km": 0.5,
                "total_emissions_kg_per_hr": {"NOx": 0.1, "CO2": 5.0},
                "geometry": "LINESTRING(121.4 31.2, 121.405 31.2)",
            },
            {
                "link_id": "road_002",
                "link_length_km": 0.3,
                "total_emissions_kg_per_hr": {"NOx": 0.08, "CO2": 4.0},
                "geometry": "LINESTRING(121.405 31.2, 121.41 31.205)",
            },
        ],
        "summary": {
            "total_links": 2,
            "total_emissions_kg_per_hr": {"NOx": 0.18, "CO2": 9.0},
        },
    },
}

MOCK_DISPERSION_RESULT = {
    "status": "success",
    "data": {
        "query_info": {
            "pollutant": "NOx",
            "n_roads": 2,
            "n_receptors": 10,
            "n_time_steps": 1,
            "roughness_height": 0.5,
            "met_source": "preset:urban_summer_day",
        },
        "results": [
            {
                "receptor_id": i,
                "lon": 121.4 + i * 0.001,
                "lat": 31.2 + i * 0.001,
                "local_x": float(i * 10),
                "local_y": float(i * 10),
                "concentrations": {"2024070112": 0.5},
                "mean_conc": 0.5,
                "max_conc": 0.5,
            }
            for i in range(10)
        ],
        "summary": {
            "receptor_count": 10,
            "time_steps": 1,
            "mean_concentration": 0.5,
            "max_concentration": 0.8,
            "unit": "μg/m³",
            "coordinate_system": "WGS-84",
        },
        "concentration_grid": {
            "receptors": [
                {
                    "lon": 121.4 + i * 0.001,
                    "lat": 31.2 + i * 0.001,
                    "mean_conc": 0.5,
                    "max_conc": 0.8,
                }
                for i in range(10)
            ],
            "bounds": {
                "min_lon": 121.4,
                "max_lon": 121.41,
                "min_lat": 31.2,
                "max_lat": 31.21,
            },
        },
    },
}


class StubCalculator:
    """Simple stub calculator for execute-path tests."""

    def __init__(self, result):
        self.result = result

    def calculate(self, **kwargs):
        return deepcopy(self.result)


class FakeMemory:
    def __init__(self, fact_memory=None, working_memory=None):
        self.fact_memory = FactMemory()
        for key, value in (fact_memory or {}).items():
            if hasattr(self.fact_memory, key):
                setattr(self.fact_memory, key, value)
        self._working_memory = working_memory or []
        self.update_calls = []

    def get_fact_memory(self):
        return {
            "recent_vehicle": self.fact_memory.recent_vehicle,
            "recent_pollutants": self.fact_memory.recent_pollutants,
            "recent_year": self.fact_memory.recent_year,
            "active_file": self.fact_memory.active_file,
            "file_analysis": self.fact_memory.file_analysis,
            "last_tool_name": self.fact_memory.last_tool_name,
            "last_tool_summary": self.fact_memory.last_tool_summary,
            "last_tool_snapshot": self.fact_memory.last_tool_snapshot,
            "last_spatial_data": self.fact_memory.last_spatial_data,
        }

    def get_working_memory(self):
        return list(self._working_memory)

    def update(self, user_message, assistant_response, tool_calls=None, file_path=None, file_analysis=None):
        self.update_calls.append(
            {
                "user_message": user_message,
                "assistant_response": assistant_response,
                "tool_calls": tool_calls,
                "file_path": file_path,
                "file_analysis": file_analysis,
            }
        )


def make_router(*, llm_response: LLMResponse, executor_result=None, fact_memory=None) -> UnifiedRouter:
    router = object.__new__(UnifiedRouter)
    router.session_id = "test-session"
    router.runtime_config = get_config()
    router.memory = FakeMemory(fact_memory=fact_memory)
    router.assembler = SimpleNamespace(
        assemble=Mock(
            return_value=SimpleNamespace(
                system_prompt="system prompt",
                tools=[{"type": "function", "function": {"name": "calculate_dispersion"}}],
                messages=[{"role": "user", "content": "test user message"}],
                estimated_tokens=12,
            )
        )
    )
    router.executor = SimpleNamespace(execute=AsyncMock(return_value=executor_result or {}))
    router.llm = SimpleNamespace(
        chat_with_tools=AsyncMock(
            side_effect=[llm_response, LLMResponse(content="扩散分析完成。")]
        ),
        chat=AsyncMock(return_value=LLMResponse(content="unused synthesis")),
    )
    return router


@pytest.fixture
def tool():
    return DispersionTool()


@pytest.fixture
def registry():
    reg = get_registry()
    reg.clear()
    yield reg
    reg.clear()


class TestDispersionToolInit:
    def test_tool_name(self, tool):
        assert tool.name == "calculate_dispersion"

    def test_tool_init_imports(self):
        tool = DispersionTool()
        assert tool._calculator_class.__name__ == "DispersionCalculator"
        assert tool._config_class.__name__ == "DispersionConfig"


class TestResolveEmissionSource:
    def test_last_result_success(self, tool):
        result = tool._resolve_emission_source("last_result", {"_last_result": deepcopy(MOCK_MACRO_RESULT)})

        assert result == {"status": "success", "data": deepcopy(MOCK_MACRO_RESULT["data"])}

    def test_last_result_missing(self, tool):
        assert tool._resolve_emission_source("last_result", {}) is None

    def test_last_result_failed(self, tool):
        result = tool._resolve_emission_source(
            "last_result",
            {"_last_result": {"success": False, "error": "failed"}},
        )

        assert result is None

    def test_file_path_returns_none(self, tool, caplog):
        with caplog.at_level("WARNING"):
            result = tool._resolve_emission_source("/tmp/emission.xlsx", {})

        assert result is None
        assert "file-based emission_source is not supported yet" in caplog.text


class TestBuildMetInput:
    def test_preset_name(self, tool):
        assert tool._build_met_input("urban_summer_day", {}) == "urban_summer_day"

    def test_custom_dict(self, tool):
        met = tool._build_met_input(
            "custom",
            {
                "wind_speed": 3.0,
                "wind_direction": 270.0,
                "stability_class": "U",
                "mixing_height": 900.0,
            },
        )

        assert met["wind_speed"] == 3.0
        assert met["wind_direction"] == 270.0
        assert met["stability_class"] == "U"
        assert met["mixing_height"] == 900.0
        assert met["monin_obukhov_length"] == -500.0

    def test_sfc_file_path(self, tool):
        assert tool._build_met_input("demo.sfc", {}) == "demo.sfc"

    def test_default_fallback(self, tool, caplog):
        with caplog.at_level("WARNING"):
            met = tool._build_met_input("not_a_real_preset", {})

        assert met == "urban_summer_day"
        assert "falling back to urban_summer_day" in caplog.text


class TestGetCalculator:
    def test_cache_reuse(self, tool):
        calc1 = tool._get_calculator(0.5)
        calc2 = tool._get_calculator(0.5)

        assert calc1 is calc2

    def test_different_roughness(self, tool):
        calc1 = tool._get_calculator(0.05)
        calc2 = tool._get_calculator(0.5)

        assert calc1 is not calc2


class TestExecuteIntegration:
    @pytest.mark.anyio
    async def test_execute_with_mock_last_result(self, tool, monkeypatch):
        monkeypatch.setattr(tool, "_get_calculator", lambda roughness: StubCalculator(MOCK_DISPERSION_RESULT))

        result = await tool.execute(
            _last_result=deepcopy(MOCK_MACRO_RESULT),
            meteorology="urban_summer_day",
            pollutant="NOx",
        )

        assert result.success is True
        assert result.data["summary"]["receptor_count"] == 10
        assert "concentration_grid" in result.map_data

    @pytest.mark.anyio
    async def test_execute_no_emission_data(self, tool):
        result = await tool.execute(meteorology="urban_summer_day")

        assert result.success is False
        assert "Please run calculate_macro_emission first" in result.error

    @pytest.mark.anyio
    async def test_execute_no_geometry(self, tool, monkeypatch):
        no_geometry = deepcopy(MOCK_MACRO_RESULT)
        for item in no_geometry["data"]["results"]:
            item.pop("geometry", None)
        monkeypatch.setattr(tool, "_get_calculator", lambda roughness: StubCalculator(MOCK_DISPERSION_RESULT))

        result = await tool.execute(
            _last_result=no_geometry,
            meteorology="urban_summer_day",
        )

        assert result.success is False
        assert "No road geometry found in emission results" in result.error

    @pytest.mark.anyio
    async def test_execute_calculator_error(self, tool, monkeypatch):
        monkeypatch.setattr(
            tool,
            "_get_calculator",
            lambda roughness: StubCalculator(
                {"status": "error", "message": "Dispersion calculation failed in stub"}
            ),
        )

        result = await tool.execute(
            _last_result=deepcopy(MOCK_MACRO_RESULT),
            meteorology="urban_summer_day",
        )

        assert result.success is False
        assert result.error == "Dispersion calculation failed in stub"


class TestToolRegistration:
    def test_init_tools_registers_dispersion(self, registry):
        init_tools()

        assert registry.get("calculate_dispersion") is not None

    def test_total_tool_count(self, registry):
        init_tools()

        assert len(registry.list_tools()) == 9


class TestRouterSpatialDataSave:
    @pytest.mark.anyio
    async def test_calculate_dispersion_injects_last_result_from_memory(self, caplog):
        config = get_config()
        config.enable_state_orchestration = True
        config.enable_trace = True

        tool_call = ToolCall(
            id="call-dispersion",
            name="calculate_dispersion",
            arguments={"meteorology": "urban_summer_day"},
        )
        llm_response = LLMResponse(content="calling dispersion tool", tool_calls=[tool_call])
        executor_result = {
            "success": True,
            "summary": "扩散计算完成",
            "data": deepcopy(MOCK_DISPERSION_RESULT["data"]),
        }
        router = make_router(
            llm_response=llm_response,
            executor_result=executor_result,
            fact_memory={"last_spatial_data": deepcopy(MOCK_MACRO_RESULT["data"])},
        )

        with caplog.at_level("INFO"):
            await router.chat("用 urban_summer_day 计算扩散", trace={})

        execute_kwargs = router.executor.execute.await_args.kwargs
        assert execute_kwargs["arguments"]["_last_result"] == {
            "success": True,
            "data": deepcopy(MOCK_MACRO_RESULT["data"]),
        }
        assert "calculate_dispersion: injected macro emission result from memory spatial_data, 2 links" in caplog.text

    @pytest.mark.anyio
    async def test_dispersion_result_saved_to_last_spatial_data(self, caplog):
        config = get_config()
        config.enable_state_orchestration = True
        config.enable_trace = True

        tool_call = ToolCall(
            id="call-dispersion",
            name="calculate_dispersion",
            arguments={"meteorology": "urban_summer_day"},
        )
        llm_response = LLMResponse(content="calling dispersion tool", tool_calls=[tool_call])
        concentration_data = deepcopy(MOCK_DISPERSION_RESULT["data"])
        executor_result = {
            "success": True,
            "summary": "扩散计算完成",
            "data": concentration_data,
        }
        router = make_router(llm_response=llm_response, executor_result=executor_result)

        with caplog.at_level("INFO"):
            await router.chat("用 urban_summer_day 计算扩散", trace={})

        assert router.memory.fact_memory.last_spatial_data == concentration_data
        assert "Saved last_spatial_data: concentration_grid with 10 receptors" in caplog.text
