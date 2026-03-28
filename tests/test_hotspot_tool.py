"""Tests for HotspotTool."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from config import get_config
from core.memory import FactMemory
from core.router import UnifiedRouter
from services.llm_client import LLMResponse, ToolCall
from tools.hotspot import HotspotTool
from tools.registry import get_registry, init_tools


MOCK_DISPERSION_DATA = {
    "raster_grid": {
        "matrix_mean": [[0.1, 0.2, 5.0], [0.1, 0.3, 6.0], [0.0, 0.1, 0.1]],
        "matrix_max": [[0.2, 0.3, 7.0], [0.2, 0.4, 8.0], [0.0, 0.2, 0.2]],
        "resolution_m": 50,
        "rows": 3,
        "cols": 3,
        "bbox_wgs84": [121.4, 31.2, 121.41, 31.21],
        "cell_receptor_map": {
            "0_2": [0, 1],
            "1_2": [2, 3],
        },
        "cell_centers_wgs84": [
            {"row": 0, "col": 0, "lon": 121.401, "lat": 31.201, "mean_conc": 0.1, "max_conc": 0.2},
            {"row": 0, "col": 1, "lon": 121.403, "lat": 31.201, "mean_conc": 0.2, "max_conc": 0.3},
            {"row": 0, "col": 2, "lon": 121.405, "lat": 31.201, "mean_conc": 5.0, "max_conc": 7.0},
            {"row": 1, "col": 0, "lon": 121.401, "lat": 31.203, "mean_conc": 0.1, "max_conc": 0.2},
            {"row": 1, "col": 1, "lon": 121.403, "lat": 31.203, "mean_conc": 0.3, "max_conc": 0.4},
            {"row": 1, "col": 2, "lon": 121.405, "lat": 31.203, "mean_conc": 6.0, "max_conc": 8.0},
            {"row": 2, "col": 1, "lon": 121.403, "lat": 31.205, "mean_conc": 0.1, "max_conc": 0.2},
            {"row": 2, "col": 2, "lon": 121.405, "lat": 31.205, "mean_conc": 0.1, "max_conc": 0.2},
        ],
        "stats": {"total_cells": 9, "nonzero_cells": 7, "coverage_pct": 77.8},
        "nodata": 0.0,
        "bbox_local": [0, 0, 150, 150],
    },
    "road_contributions": {
        "receptor_top_roads": {
            "0": [(0, 3.5), (1, 1.5)],
            "1": [(0, 2.0), (1, 3.0)],
            "2": [(1, 4.0), (0, 2.0)],
            "3": [(0, 1.0), (1, 5.0)],
        },
        "road_id_map": ["road_A", "road_B"],
        "tracking_mode": "dense_exact",
    },
    "coverage_assessment": {
        "level": "complete_regional",
        "road_density_km_per_km2": 10.5,
        "warnings": [],
    },
    "summary": {"receptor_count": 4, "mean_concentration": 1.5, "max_concentration": 6.0, "unit": "μg/m³"},
}


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


def make_router(*, llm_response: LLMResponse, executor_result=None, fact_memory=None, llm_tool_responses=None) -> UnifiedRouter:
    router = object.__new__(UnifiedRouter)
    router.session_id = "test-session"
    router.runtime_config = get_config()
    router.memory = FakeMemory(fact_memory=fact_memory)
    router.assembler = SimpleNamespace(
        assemble=Mock(
            return_value=SimpleNamespace(
                system_prompt="system prompt",
                tools=[{"type": "function", "function": {"name": "analyze_hotspots"}}],
                messages=[{"role": "user", "content": "test user message"}],
                estimated_tokens=12,
            )
        )
    )
    router.executor = SimpleNamespace(execute=AsyncMock(return_value=executor_result or {}))
    router.llm = SimpleNamespace(
        chat_with_tools=AsyncMock(side_effect=llm_tool_responses or [llm_response]),
        chat=AsyncMock(return_value=LLMResponse(content="unused synthesis")),
    )
    return router


@pytest.fixture
def tool():
    return HotspotTool()


@pytest.fixture
def registry():
    reg = get_registry()
    reg.clear()
    yield reg
    reg.clear()


class TestHotspotToolInit:
    def test_tool_name(self):
        tool = HotspotTool()
        assert tool.name == "analyze_hotspots"

    def test_tool_init(self):
        tool = HotspotTool()
        assert tool._analyzer is not None


class TestHotspotToolExecute:
    @pytest.mark.anyio
    async def test_execute_percentile(self, tool):
        result = await tool.execute(
            _last_result={"success": True, "data": deepcopy(MOCK_DISPERSION_DATA)},
            method="percentile",
            percentile=10.0,
        )

        assert result.success is True
        assert result.data["hotspot_count"] >= 1
        assert result.data["hotspots"]

    @pytest.mark.anyio
    async def test_execute_threshold(self, tool):
        result = await tool.execute(
            _last_result={"success": True, "data": deepcopy(MOCK_DISPERSION_DATA)},
            method="threshold",
            threshold_value=5.0,
        )

        assert result.success is True
        assert result.data["method"] == "threshold"
        assert result.data["hotspot_count"] == 1

    @pytest.mark.anyio
    async def test_execute_no_dispersion_data(self, tool):
        result = await tool.execute()

        assert result.success is False
        assert "Please run calculate_dispersion first" in result.error

    @pytest.mark.anyio
    async def test_execute_no_raster_grid(self, tool):
        result = await tool.execute(
            _last_result={
                "success": True,
                "data": {
                    "summary": {},
                    "concentration_grid": {"receptors": []},
                },
            }
        )

        assert result.success is False
        assert "does not contain raster grid data" in result.error

    @pytest.mark.anyio
    async def test_execute_source_attribution(self, tool):
        result = await tool.execute(
            _last_result={"success": True, "data": deepcopy(MOCK_DISPERSION_DATA)},
            method="threshold",
            threshold_value=5.0,
            source_attribution=True,
        )

        roads = result.data["hotspots"][0]["contributing_roads"]
        assert roads
        assert {road["link_id"] for road in roads} == {"road_A", "road_B"}

    @pytest.mark.anyio
    async def test_map_data_contains_hotspots(self, tool):
        result = await tool.execute(
            _last_result={"success": True, "data": deepcopy(MOCK_DISPERSION_DATA)},
            method="threshold",
            threshold_value=5.0,
        )

        assert result.success is True
        assert result.map_data["type"] == "hotspot"
        assert result.map_data["hotspots"]
        assert "raster_grid" in result.map_data

    @pytest.mark.anyio
    async def test_summary_contains_hotspot_descriptions(self, tool):
        result = await tool.execute(
            _last_result={"success": True, "data": deepcopy(MOCK_DISPERSION_DATA)},
            method="threshold",
            threshold_value=5.0,
        )

        assert result.success is True
        assert "热点 #1" in result.summary
        assert "最高浓度" in result.summary


class TestHotspotToolRegistration:
    def test_registered(self, registry):
        init_tools()

        assert registry.get("analyze_hotspots") is not None

    def test_total_tool_count(self, registry):
        init_tools()

        assert len(registry.list_tools()) == 9


class TestToolDependencies:
    def test_hotspot_requires_dispersion(self):
        from core.tool_dependencies import TOOL_GRAPH

        assert "dispersion" in TOOL_GRAPH["analyze_hotspots"]["requires"]

    def test_hotspot_provides_analysis(self):
        from core.tool_dependencies import TOOL_GRAPH

        assert "hotspot" in TOOL_GRAPH["analyze_hotspots"]["provides"]


class TestHotspotRouterIntegration:
    @pytest.mark.anyio
    async def test_analyze_hotspots_injects_last_result_from_memory(self, caplog):
        config = get_config()
        config.enable_state_orchestration = True
        config.enable_trace = True

        tool_call = ToolCall(
            id="call-hotspot",
            name="analyze_hotspots",
            arguments={"method": "threshold", "threshold_value": 5.0},
        )
        llm_response = LLMResponse(content="calling hotspot tool", tool_calls=[tool_call])
        executor_result = {
            "success": True,
            "summary": "热点分析完成",
            "data": {"hotspot_count": 1, "hotspots": [], "raster_grid": deepcopy(MOCK_DISPERSION_DATA["raster_grid"])},
        }
        router = make_router(
            llm_response=llm_response,
            executor_result=executor_result,
            fact_memory={"last_spatial_data": deepcopy(MOCK_DISPERSION_DATA)},
            llm_tool_responses=[llm_response, LLMResponse(content="热点分析完成。")],
        )

        with caplog.at_level("INFO"):
            await router.chat("分析热点", trace={})

        execute_kwargs = router.executor.execute.await_args.kwargs
        assert execute_kwargs["arguments"]["_last_result"] == {
            "success": True,
            "data": deepcopy(MOCK_DISPERSION_DATA),
        }
        assert "analyze_hotspots: injected raster result from memory spatial_data" in caplog.text

    @pytest.mark.anyio
    async def test_hotspot_result_saved_to_last_spatial_data(self, caplog):
        config = get_config()
        config.enable_state_orchestration = True
        config.enable_trace = True

        tool_call = ToolCall(
            id="call-hotspot",
            name="analyze_hotspots",
            arguments={"method": "threshold", "threshold_value": 5.0},
        )
        llm_response = LLMResponse(content="calling hotspot tool", tool_calls=[tool_call])
        hotspot_data = {
            "hotspot_count": 1,
            "hotspots": [{"rank": 1, "max_conc": 6.0}],
            "raster_grid": deepcopy(MOCK_DISPERSION_DATA["raster_grid"]),
        }
        executor_result = {
            "success": True,
            "summary": "热点分析完成",
            "data": hotspot_data,
        }
        router = make_router(llm_response=llm_response, executor_result=executor_result)
        router.llm.chat_with_tools = AsyncMock(
            side_effect=[llm_response, LLMResponse(content="热点分析完成。")]
        )

        with caplog.at_level("INFO"):
            await router.chat("分析热点", trace={})

        assert router.memory.fact_memory.last_spatial_data == hotspot_data
        assert "Saved last_spatial_data: hotspot analysis with 1 hotspots" in caplog.text
