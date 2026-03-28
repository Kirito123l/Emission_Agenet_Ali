"""Tests for preserving frontend payloads across multi-tool execution."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from config import get_config
from core.memory import FactMemory
from core.router import UnifiedRouter
from services.llm_client import LLMResponse, ToolCall


class FakeMemory:
    def __init__(self, *, fact_memory=None, working_memory=None):
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


def make_router(*, llm_tool_responses, executor_results) -> UnifiedRouter:
    router = object.__new__(UnifiedRouter)
    router.session_id = "test-session"
    router.runtime_config = get_config()
    router.memory = FakeMemory()
    router.assembler = SimpleNamespace(
        assemble=Mock(
            return_value=SimpleNamespace(
                system_prompt="system prompt",
                tools=[
                    {"type": "function", "function": {"name": "render_spatial_map"}},
                    {"type": "function", "function": {"name": "calculate_dispersion"}},
                ],
                messages=[{"role": "user", "content": "test user message"}],
                estimated_tokens=24,
            )
        )
    )
    router.executor = SimpleNamespace(execute=AsyncMock(side_effect=executor_results))
    router.llm = SimpleNamespace(
        chat_with_tools=AsyncMock(side_effect=llm_tool_responses),
        chat=AsyncMock(return_value=LLMResponse(content="unused synthesis")),
    )
    return router


def make_emission_map():
    return {
        "type": "emission",
        "title": "排放地图",
        "links": [
            {
                "link_id": "L1",
                "geometry": [[121.4, 31.2], [121.41, 31.21]],
                "emissions": {"CO2": 12.3},
            }
        ],
        "pollutant": "CO2",
    }


def make_raster_map():
    return {
        "type": "raster",
        "title": "浓度栅格",
        "layers": [
            {
                "id": "grid",
                "type": "polygon",
                "data": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"value": 1.2},
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [[[121.4, 31.2], [121.41, 31.2], [121.41, 31.21], [121.4, 31.21], [121.4, 31.2]]],
                            },
                        }
                    ],
                },
            }
        ],
        "raster_grid": {"rows": 1, "cols": 1, "resolution_m": 50},
    }


class TestMultiToolMapData:
    def test_single_tool_map_data_preserved(self):
        router = make_router(llm_tool_responses=[LLMResponse(content="unused")], executor_results=[])

        payload = router._extract_map_data(
            [{"name": "render_spatial_map", "result": {"map_data": make_emission_map()}}]
        )

        assert payload == make_emission_map()

    def test_multi_tool_all_map_data_collected(self):
        router = make_router(llm_tool_responses=[LLMResponse(content="unused")], executor_results=[])

        payload = router._extract_map_data(
            [
                {"name": "render_spatial_map", "result": {"map_data": make_emission_map()}},
                {"name": "calculate_dispersion", "result": {"map_data": make_raster_map()}},
            ]
        )

        assert payload["type"] == "map_collection"
        assert [item["type"] for item in payload["items"]] == ["emission", "raster"]
        assert payload["summary"]["map_count"] == 2

    def test_multi_tool_download_file_preserved(self):
        router = make_router(llm_tool_responses=[LLMResponse(content="unused")], executor_results=[])

        payloads = router._extract_frontend_payloads(
            [
                {
                    "name": "render_spatial_map",
                    "result": {
                        "map_data": make_emission_map(),
                        "download_file": {"path": "/tmp/result.xlsx", "filename": "result.xlsx"},
                    },
                },
                {"name": "calculate_dispersion", "result": {"map_data": make_raster_map()}},
            ]
        )

        assert payloads["download_file"] == {"path": "/tmp/result.xlsx", "filename": "result.xlsx"}
        assert payloads["map_data"]["type"] == "map_collection"

    @pytest.mark.anyio
    async def test_llm_text_response_with_map_data(self):
        config = get_config()
        config.enable_state_orchestration = True
        config.enable_trace = True

        initial_response = LLMResponse(
            content="先渲染地图并做扩散",
            tool_calls=[
                ToolCall(id="map-1", name="render_spatial_map", arguments={"pollutant": "CO2"}),
                ToolCall(id="disp-1", name="calculate_dispersion", arguments={"pollutant": "NOx"}),
            ],
        )
        final_response = LLMResponse(content="已完成地图渲染和扩散分析。")
        router = make_router(
            llm_tool_responses=[initial_response, final_response],
            executor_results=[
                {"success": True, "summary": "地图渲染完成", "map_data": make_emission_map()},
                {"success": True, "summary": "扩散完成", "map_data": make_raster_map()},
            ],
        )

        result = await router.chat("先画排放，再做扩散", trace={})

        assert result.text == "已完成地图渲染和扩散分析。"
        assert result.map_data["type"] == "map_collection"
        assert [item["type"] for item in result.map_data["items"]] == ["emission", "raster"]
        assert [call["name"] for call in result.executed_tool_calls] == [
            "render_spatial_map",
            "calculate_dispersion",
        ]

    def test_map_data_collection_preserves_table_and_order(self):
        router = make_router(llm_tool_responses=[LLMResponse(content="unused")], executor_results=[])

        payloads = router._extract_frontend_payloads(
            [
                {
                    "name": "render_spatial_map",
                    "result": {
                        "map_data": make_emission_map(),
                        "table_data": {"type": "render_spatial_map", "columns": ["A"], "preview_rows": [{"A": 1}]},
                    },
                },
                {"name": "calculate_dispersion", "result": {"map_data": make_raster_map()}},
            ]
        )

        assert payloads["table_data"]["type"] == "render_spatial_map"
        assert [item["type"] for item in payloads["map_data"]["items"]] == ["emission", "raster"]
