"""Regression coverage for LLM-native chaining, dispersion guidance, and map rendering."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from config import get_config
from core.memory import FactMemory
from core.router import UnifiedRouter
from core.router_render_utils import render_single_tool_success
from core.router_synthesis_utils import TOOLS_NEEDING_RENDERING, maybe_short_circuit_synthesis
from core.skill_injector import SkillInjector
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


def make_router(
    *,
    llm_tool_responses,
    executor_results=None,
    working_memory=None,
    fact_memory=None,
) -> UnifiedRouter:
    router = object.__new__(UnifiedRouter)
    router.session_id = "test-session"
    router.runtime_config = get_config()
    router.memory = FakeMemory(fact_memory=fact_memory, working_memory=working_memory)
    router.assembler = SimpleNamespace(
        assemble=Mock(
            return_value=SimpleNamespace(
                system_prompt="system prompt",
                tools=[
                    {"type": "function", "function": {"name": "calculate_dispersion"}},
                    {"type": "function", "function": {"name": "analyze_hotspots"}},
                    {"type": "function", "function": {"name": "render_spatial_map"}},
                ],
                messages=[{"role": "user", "content": "test user message"}],
                estimated_tokens=42,
            )
        ),
        all_tool_definitions=[
            {"type": "function", "function": {"name": "calculate_dispersion"}},
            {"type": "function", "function": {"name": "analyze_hotspots"}},
            {"type": "function", "function": {"name": "render_spatial_map"}},
        ],
    )
    router.executor = SimpleNamespace(execute=AsyncMock(side_effect=executor_results or []))
    router.llm = SimpleNamespace(
        chat_with_tools=AsyncMock(side_effect=llm_tool_responses),
        chat=AsyncMock(return_value=LLMResponse(content="综合结果")),
    )
    return router


def make_dispersion_success_result():
    return {
        "success": True,
        "summary": "扩散计算完成",
        "data": {
            "query_info": {"pollutant": "NOx", "n_receptors": 12, "n_time_steps": 1, "roughness_height": 0.5},
            "summary": {
                "receptor_count": 12,
                "time_steps": 1,
                "mean_concentration": 1.1,
                "max_concentration": 2.4,
                "unit": "μg/m³",
            },
            "raster_grid": {"rows": 6, "cols": 6, "resolution_m": 50},
            "meteorology_used": {
                "_source_mode": "preset",
                "_preset_name": "urban_summer_day",
                "_overrides": {},
                "wind_speed": 2.5,
                "wind_direction": 225.0,
                "stability_class": "VU",
                "mixing_height": 1500.0,
            },
        },
    }


def make_hotspot_success_result():
    return {
        "success": True,
        "summary": "热点分析完成",
        "data": {
            "interpretation": "局部热点贡献识别",
            "hotspot_count": 1,
            "summary": {"max_concentration": 2.4, "total_hotspot_area_m2": 2500.0},
            "hotspots": [
                {
                    "rank": 1,
                    "max_conc": 2.4,
                    "area_m2": 2500.0,
                    "contributing_roads": [{"link_id": "R1", "contribution_pct": 62.0}],
                }
            ],
        },
    }


def make_macro_spatial_data():
    return {
        "query_info": {"pollutants": ["NOx"]},
        "summary": {"total_links": 2},
        "results": [
            {
                "link_id": "L1",
                "geometry": "LINESTRING (0 0, 1 1)",
                "total_emissions_kg_per_hr": {"NOx": 0.1},
            },
            {
                "link_id": "L2",
                "geometry": "LINESTRING (1 1, 2 2)",
                "total_emissions_kg_per_hr": {"NOx": 0.2},
            },
        ],
    }


def make_render_result(map_data):
    return {
        "success": True,
        "summary": "Map rendered: 20 features",
        "data": {"map_config": map_data},
        "map_data": map_data,
    }


class TestLLMNativeToolLoop:
    @pytest.mark.anyio
    async def test_tool_results_are_fed_back_and_next_tool_selected(self):
        config = get_config()
        config.enable_state_orchestration = True
        config.enable_trace = True

        llm_tool_responses = [
            LLMResponse(
                content="先做扩散",
                tool_calls=[
                    ToolCall(
                        id="disp-1",
                        name="calculate_dispersion",
                        arguments={"meteorology": "urban_summer_day"},
                    )
                ],
            ),
            LLMResponse(
                content="继续做热点",
                tool_calls=[
                    ToolCall(
                        id="hot-1",
                        name="analyze_hotspots",
                        arguments={"method": "percentile", "percentile": 5.0},
                    )
                ],
            ),
            LLMResponse(content="已完成扩散和热点分析。"),
        ]
        executor_results = [make_dispersion_success_result(), make_hotspot_success_result()]
        router = make_router(
            llm_tool_responses=llm_tool_responses,
            executor_results=executor_results,
            fact_memory={"last_spatial_data": make_macro_spatial_data()},
        )

        result = await router.chat("请做扩散分析，并继续识别热点区域", trace={})

        assert result.text == "已完成扩散和热点分析。"
        assert [call["name"] for call in result.executed_tool_calls] == [
            "calculate_dispersion",
            "analyze_hotspots",
        ]
        assert router.executor.execute.await_count == 2
        assert router.llm.chat_with_tools.await_count == 3

        first_call_args = router.executor.execute.await_args_list[0].kwargs["arguments"]
        second_call_args = router.executor.execute.await_args_list[1].kwargs["arguments"]
        assert first_call_args["_last_result"] == {"success": True, "data": make_macro_spatial_data()}
        assert second_call_args["_last_result"]["data"]["raster_grid"]["resolution_m"] == 50

    @pytest.mark.anyio
    async def test_confirmation_turn_executes_dispersion_without_router_intercept(self):
        config = get_config()
        config.enable_state_orchestration = True
        config.enable_trace = True

        llm_tool_responses = [
            LLMResponse(
                content="开始扩散计算",
                tool_calls=[
                    ToolCall(
                        id="disp-1",
                        name="calculate_dispersion",
                        arguments={"meteorology": "urban_summer_day"},
                    )
                ],
            ),
            LLMResponse(content="已按确认的气象条件完成扩散分析。"),
        ]
        working_memory = [
            {
                "user": "请帮我做扩散分析",
                "assistant": (
                    "我将为您做扩散分析。当前使用城市夏季白天预设（西南风 2.5 m/s，强不稳定条件）。"
                    "您可以直接说‘开始’使用默认设置，或告诉我想调整的参数。"
                ),
            }
        ]
        router = make_router(
            llm_tool_responses=llm_tool_responses,
            executor_results=[make_dispersion_success_result()],
            working_memory=working_memory,
            fact_memory={"last_spatial_data": make_macro_spatial_data()},
        )

        result = await router.chat("OK", trace={})

        assert result.text == "已按确认的气象条件完成扩散分析。"
        assert [call["name"] for call in result.executed_tool_calls] == ["calculate_dispersion"]
        assert result.trace["final_stage"] == "DONE"
        assert router.executor.execute.await_count == 1
        assert router.llm.chat_with_tools.await_count == 2

    @pytest.mark.anyio
    async def test_max_steps_limit_forces_finalize_with_current_results(self):
        config = get_config()
        config.enable_state_orchestration = True
        config.enable_trace = True
        config.max_orchestration_steps = 2

        llm_tool_responses = [
            LLMResponse(
                content="先扩散",
                tool_calls=[ToolCall(id="disp-1", name="calculate_dispersion", arguments={"meteorology": "urban_summer_day"})],
            ),
            LLMResponse(
                content="继续热点",
                tool_calls=[ToolCall(id="hot-1", name="analyze_hotspots", arguments={"method": "percentile", "percentile": 5.0})],
            ),
        ]
        router = make_router(
            llm_tool_responses=llm_tool_responses,
            executor_results=[make_dispersion_success_result(), make_hotspot_success_result()],
            fact_memory={"last_spatial_data": make_macro_spatial_data()},
        )

        result = await router.chat("做扩散然后继续做热点", trace={})

        assert [call["name"] for call in result.executed_tool_calls] == [
            "calculate_dispersion",
            "analyze_hotspots",
        ]
        assert router.llm.chat_with_tools.await_count == 2
        assert router.executor.execute.await_count == 2
        assert result.text == "综合结果"

    def test_dispersion_skill_requires_confirmation_before_tool_call(self):
        injector = SkillInjector()

        prompt = injector.get_situational_prompt({"dispersion"}, last_tool_name=None)

        assert "等用户确认后再调用工具" in prompt
        assert "OK" in prompt
        assert "可以" in prompt


class TestRenderSpatialMapFriendly:
    def test_in_tools_needing_rendering(self):
        assert "render_spatial_map" in TOOLS_NEEDING_RENDERING

    def test_emission_map_render(self):
        rendered = render_single_tool_success(
            "render_spatial_map",
            make_render_result(
                {
                    "type": "macro_emission_map",
                    "title": "路段排放地图",
                    "unit": "kg/(h·km)",
                    "color_scale": {"min": 0.12, "max": 4.6},
                    "links": [{"link_id": "L1"}, {"link_id": "L2"}],
                    "summary": {"total_links": 2},
                }
            ),
        )

        assert rendered.startswith("## 空间渲染结果")
        assert "已渲染 2 条路段的排放分布" in rendered
        assert "排放强度范围: 0.12 - 4.6 kg/(h·km)" in rendered

    def test_raster_map_render(self):
        rendered = render_single_tool_success(
            "render_spatial_map",
            make_render_result(
                {
                    "type": "raster",
                    "title": "NOx 浓度场地图",
                    "summary": {
                        "nonzero_cells": 24,
                        "resolution_m": 50,
                        "max_concentration": 3.45,
                        "unit": "μg/m³",
                    },
                }
            ),
        )

        assert "已渲染 24 个浓度栅格单元" in rendered
        assert "分辨率 50 m" in rendered
        assert "最大浓度 3.45 μg/m³" in rendered

    def test_hotspot_map_render(self):
        rendered = render_single_tool_success(
            "render_spatial_map",
            make_render_result(
                {
                    "type": "hotspot",
                    "title": "热点分析地图",
                    "interpretation": "局部热点贡献识别",
                    "hotspots_detail": [
                        {
                            "rank": 1,
                            "max_conc": 6.0,
                            "area_m2": 5000.0,
                            "contributing_roads": [{"link_id": "road_A", "contribution_pct": 60.0}],
                        }
                    ],
                }
            ),
        )

        assert "热点分析地图" in rendered
        assert "局部热点贡献识别" in rendered
        assert "展示 1 个热点区域" in rendered
        assert "主要贡献路段 road_A（60.0%）" in rendered

    def test_short_circuit_uses_structured_render(self):
        text = maybe_short_circuit_synthesis(
            [
                {
                    "name": "render_spatial_map",
                    "result": make_render_result(
                        {
                            "type": "macro_emission_map",
                            "title": "路段排放地图",
                            "summary": {"total_links": 20},
                            "links": [{"link_id": f"L{i}"} for i in range(20)],
                        }
                    ),
                }
            ]
        )

        assert text.startswith("## 空间渲染结果")
        assert "Map rendered: 20 features" not in text
