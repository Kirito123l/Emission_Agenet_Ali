"""Integration tests for router + SessionContextStore."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from config import get_config
from core.plan import ExecutionPlan, PlanStatus, PlanStep, PlanStepStatus
from core.context_store import SessionContextStore
from core.memory import FactMemory
from core.router import UnifiedRouter
from core.tool_dependencies import validate_tool_prerequisites
from services.llm_client import LLMResponse, ToolCall

from tests.test_context_store import (
    make_dispersion_result,
    make_emission_result,
    make_hotspot_result,
)


def make_emission_result_with_pollutants(pollutants: list[str]) -> dict:
    result = make_emission_result()
    result["data"]["query_info"]["pollutants"] = list(pollutants)
    result["data"]["summary"]["total_emissions_kg_per_hr"] = {
        pollutant: float(index + 1)
        for index, pollutant in enumerate(pollutants)
    }
    for row_index, row in enumerate(result["data"]["results"], start=1):
        row["total_emissions_kg_per_hr"] = {
            pollutant: float((index + 1) * row_index)
            for index, pollutant in enumerate(pollutants)
        }
    return result


def make_dispersion_result_with_scenario(
    pollutant: str,
    *,
    meteorology: str = "urban_winter_night",
) -> dict:
    result = make_dispersion_result(pollutant=pollutant)
    result["data"]["query_info"].update(
        {
            "pollutant": pollutant,
            "roughness_height": 1.0,
            "display_grid_resolution_m": 100.0,
            "contour_interp_resolution_m": 25.0,
        }
    )
    result["data"]["meteorology_used"] = {
        "_source_mode": "preset_override",
        "_preset_name": meteorology,
        "_overrides": {
            "wind_speed": {"from": 1.5, "to": 4.2},
            "wind_direction": {"from": 45.0, "to": 315.0},
            "stability_class": {"from": "S", "to": "N1"},
            "mixing_height": {"from": 500.0, "to": 900.0},
        },
        "wind_speed": 4.2,
        "wind_direction": 315.0,
        "stability_class": "N1",
        "mixing_height": 900.0,
    }
    return result


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


def make_router(*, llm_responses=None, executor_results=None) -> UnifiedRouter:
    router = object.__new__(UnifiedRouter)
    router.session_id = "ctx-store-test"
    router.runtime_config = get_config()
    router.memory = FakeMemory()
    router.context_store = SessionContextStore()
    router.assembler = SimpleNamespace(
        assemble=Mock(
            return_value=SimpleNamespace(
                system_prompt="system prompt",
                tools=[
                    {"type": "function", "function": {"name": "calculate_macro_emission"}},
                    {"type": "function", "function": {"name": "calculate_dispersion"}},
                    {"type": "function", "function": {"name": "analyze_hotspots"}},
                    {"type": "function", "function": {"name": "render_spatial_map"}},
                ],
                messages=[{"role": "user", "content": "test user message"}],
                estimated_tokens=12,
            )
        )
    )
    router.executor = SimpleNamespace(execute=AsyncMock(side_effect=executor_results or []))
    router.llm = SimpleNamespace(
        chat_with_tools=AsyncMock(side_effect=llm_responses or [LLMResponse(content="done")]),
        chat=AsyncMock(return_value=LLMResponse(content="unused synthesis")),
        chat_json=AsyncMock(return_value={}),
    )
    return router


class TestRouterContextStoreIntegration:
    def test_scenario_label_routes_to_matching_upstream_result(self):
        router = make_router()
        baseline = make_emission_result("baseline")
        scenario = make_emission_result("speed_30")
        router._save_result_to_session_context("calculate_macro_emission", baseline)
        router._save_result_to_session_context("calculate_macro_emission", scenario)

        args = router._prepare_tool_arguments("calculate_dispersion", {"scenario_label": "speed_30"})

        assert args["_last_result"] == scenario

    def test_compare_tool_receives_context_store(self):
        router = make_router()
        args = router._prepare_tool_arguments("compare_scenarios", {"result_types": ["emission"]})
        assert args["_context_store"] is router.context_store

    def test_emission_then_dispersion_then_render_emission(self):
        router = make_router()
        emission = make_emission_result()
        dispersion = make_dispersion_result()

        router._save_result_to_session_context("calculate_macro_emission", emission)
        router._save_result_to_session_context("calculate_dispersion", dispersion)

        args = router._prepare_tool_arguments("render_spatial_map", {"layer_type": "emission"})

        assert args["_last_result"] == emission

    def test_emission_then_dispersion_then_hotspot_then_render_emission(self):
        router = make_router()
        emission = make_emission_result()
        dispersion = make_dispersion_result()
        hotspot = make_hotspot_result()

        router._save_result_to_session_context("calculate_macro_emission", emission)
        router._save_result_to_session_context("calculate_dispersion", dispersion)
        router._save_result_to_session_context("analyze_hotspots", hotspot)

        args = router._prepare_tool_arguments("render_spatial_map", {"layer_type": "emission"})

        assert args["_last_result"] == emission

    def test_render_dispersion_injects_latest_pollutant_result(self):
        router = make_router()
        nox = make_dispersion_result(pollutant="NOx", mean_concentration=1.0)
        co2 = make_dispersion_result(pollutant="CO2", mean_concentration=10.0)

        router._save_result_to_session_context("calculate_dispersion", nox)
        router._save_result_to_session_context("calculate_dispersion", co2)

        args = router._prepare_tool_arguments("render_spatial_map", {"layer_type": "dispersion"})

        assert args["_last_result"] == co2

    def test_render_dispersion_uses_explicit_pollutant_key(self):
        router = make_router()
        nox = make_dispersion_result(pollutant="NOx", mean_concentration=1.0)
        co2 = make_dispersion_result(pollutant="CO2", mean_concentration=10.0)

        router._save_result_to_session_context("calculate_dispersion", nox)
        router._save_result_to_session_context("calculate_dispersion", co2)

        args = router._prepare_tool_arguments(
            "render_spatial_map",
            {"layer_type": "dispersion", "pollutant": "NOx"},
        )

        assert args["_last_result"] == nox

    def test_hotspot_injects_latest_dispersion_pollutant_result(self):
        router = make_router()
        nox = make_dispersion_result(pollutant="NOx", mean_concentration=1.0)
        co2 = make_dispersion_result(pollutant="CO2", mean_concentration=10.0)

        router._save_result_to_session_context("calculate_dispersion", nox)
        router._save_result_to_session_context("calculate_dispersion", co2)

        args = router._prepare_tool_arguments("analyze_hotspots", {})

        assert args["_last_result"] == co2

    def test_dispersion_preflight_asks_when_multiple_pollutants_without_selection(self):
        from core.task_state import TaskState, TaskStage

        router = make_router()
        router._save_result_to_session_context("calculate_macro_emission", make_emission_result())
        state = TaskState.initialize(
            user_message="继续做扩散分析",
            file_path=None,
            memory_dict={},
            session_id="ctx-store-test",
        )
        args = router._prepare_tool_arguments("calculate_dispersion", {}, state=state)

        blocked = router._evaluate_missing_parameter_preflight(
            state,
            "calculate_dispersion",
            effective_arguments=args,
        )

        assert blocked is True
        assert state.stage == TaskStage.NEEDS_CLARIFICATION
        assert "CO2" in state.control.clarification_question
        assert "NOx" in state.control.clarification_question

    def test_default_nox_tool_arg_is_not_treated_as_user_pollutant_choice(self):
        from core.task_state import TaskState, TaskStage

        router = make_router()
        router._save_result_to_session_context("calculate_macro_emission", make_emission_result())
        state = TaskState.initialize(
            user_message="请帮我进行大气扩散分析吧",
            file_path=None,
            memory_dict={},
            session_id="ctx-store-test",
        )
        args = router._prepare_tool_arguments(
            "calculate_dispersion",
            {"pollutant": "NOx"},
            state=state,
        )

        blocked = router._evaluate_missing_parameter_preflight(
            state,
            "calculate_dispersion",
            effective_arguments=args,
        )

        assert blocked is True
        assert state.stage == TaskStage.NEEDS_CLARIFICATION
        assert "CO2" in state.control.clarification_question
        assert "NOx" in state.control.clarification_question

    def test_supported_subset_prompt_mentions_skipped_pollutants(self):
        from core.task_state import TaskState, TaskStage

        router = make_router()
        router._save_result_to_session_context(
            "calculate_macro_emission",
            make_emission_result_with_pollutants(["CO2", "PM2.5", "unsupported_X"]),
        )
        state = TaskState.initialize(
            user_message="继续做扩散分析",
            file_path=None,
            memory_dict={},
            session_id="ctx-store-test",
        )
        args = router._prepare_tool_arguments("calculate_dispersion", {}, state=state)

        blocked = router._evaluate_missing_parameter_preflight(
            state,
            "calculate_dispersion",
            effective_arguments=args,
        )

        assert blocked is True
        assert state.stage == TaskStage.NEEDS_CLARIFICATION
        assert "CO2" in state.control.clarification_question
        assert "PM2.5" in state.control.clarification_question
        assert "unsupported_X" in state.control.clarification_question

    def test_no_eligible_dispersion_pollutants_does_not_call_tool(self):
        from core.task_state import TaskState, TaskStage

        router = make_router()
        router._save_result_to_session_context(
            "calculate_macro_emission",
            make_emission_result_with_pollutants(["unsupported_X"]),
        )
        state = TaskState.initialize(
            user_message="继续做扩散分析",
            file_path=None,
            memory_dict={},
            session_id="ctx-store-test",
        )
        args = router._prepare_tool_arguments("calculate_dispersion", {}, state=state)

        blocked = router._evaluate_missing_parameter_preflight(
            state,
            "calculate_dispersion",
            effective_arguments=args,
        )

        assert blocked is True
        assert state.stage == TaskStage.DONE
        assert "unsupported_X" in getattr(state, "_final_response_text")
        assert "不会调用扩散计算" in getattr(state, "_final_response_text")

    def test_all_pollutants_request_expands_dispersion_calls(self):
        from core.task_state import TaskState

        router = make_router()
        router._save_result_to_session_context("calculate_macro_emission", make_emission_result())
        state = TaskState.initialize(
            user_message="对所有污染物逐个扩散",
            file_path=None,
            memory_dict={},
            session_id="ctx-store-test",
        )
        call = ToolCall(id="dispersion", name="calculate_dispersion", arguments={})

        expanded = router._expand_multi_pollutant_dispersion_calls(state, [call])

        assert [item.arguments["pollutant"] for item in expanded] == ["CO2", "NOx"]
        assert all(item.arguments["_batch_pollutant_dispatch"] is True for item in expanded)

    def test_all_pollutants_request_ignores_default_nox_and_skips_unsupported(self):
        from core.task_state import TaskState

        router = make_router()
        router._save_result_to_session_context(
            "calculate_macro_emission",
            make_emission_result_with_pollutants(["CO2", "NOx", "unsupported_X"]),
        )
        state = TaskState.initialize(
            user_message="所有污染物都看一下",
            file_path=None,
            memory_dict={},
            session_id="ctx-store-test",
        )
        call = ToolCall(id="dispersion", name="calculate_dispersion", arguments={"pollutant": "NOx"})

        expanded = router._expand_multi_pollutant_dispersion_calls(state, [call])

        assert [item.arguments["pollutant"] for item in expanded] == ["CO2", "NOx"]
        assert all(item.arguments["_pollutant_source"] == "batch" for item in expanded)
        assert "unsupported_X" in getattr(state, "_dispersion_pollutant_notice")

    def test_followup_pollutant_switch_inherits_previous_dispersion_scenario(self):
        from core.task_state import TaskState

        router = make_router()
        router._save_result_to_session_context("calculate_macro_emission", make_emission_result())
        router._save_result_to_session_context(
            "calculate_dispersion",
            make_dispersion_result_with_scenario("NOx"),
        )
        state = TaskState.initialize(
            user_message="CO2的呢？",
            file_path=None,
            memory_dict={},
            session_id="ctx-store-test",
        )

        args = router._prepare_tool_arguments("calculate_dispersion", {}, state=state)

        assert args["pollutant"] == "CO2"
        assert args["_pollutant_source"] == "user"
        assert args["meteorology"] == "urban_winter_night"
        assert args["wind_speed"] == 4.2
        assert args["wind_direction"] == 315.0
        assert args["stability_class"] == "N1"
        assert args["mixing_height"] == 900.0
        assert args["roughness_height"] == 1.0
        assert args["grid_resolution"] == 100.0
        assert args["contour_resolution"] == 25.0
        assert args["_last_result"]["data"]["query_info"]["pollutants"] == ["CO2", "NOx"]

    def test_batch_expansion_preserves_inherited_scenario_for_each_pollutant(self):
        from core.task_state import TaskState

        router = make_router()
        router._save_result_to_session_context("calculate_macro_emission", make_emission_result())
        router._save_result_to_session_context(
            "calculate_dispersion",
            make_dispersion_result_with_scenario("NOx"),
        )
        state = TaskState.initialize(
            user_message="所有污染物都看一下",
            file_path=None,
            memory_dict={},
            session_id="ctx-store-test",
        )
        expanded = router._expand_multi_pollutant_dispersion_calls(
            state,
            [ToolCall(id="dispersion", name="calculate_dispersion", arguments={})],
        )

        prepared = [
            router._prepare_tool_arguments("calculate_dispersion", call.arguments, state=state)
            for call in expanded
        ]

        assert [args["pollutant"] for args in prepared] == ["CO2", "NOx"]
        assert {args["meteorology"] for args in prepared} == {"urban_winter_night"}
        assert {args["wind_speed"] for args in prepared} == {4.2}
        assert {args["roughness_height"] for args in prepared} == {1.0}

    def test_batch_pollutant_argument_is_not_overwritten_by_first_user_pollutant(self):
        from core.task_state import TaskState

        router = make_router()
        router._save_result_to_session_context(
            "calculate_macro_emission",
            make_emission_result_with_pollutants(["CO2", "NOx", "SO2"]),
        )
        state = TaskState.initialize(
            user_message="对所有已计算污染物逐个扩散，包括 CO2、NOx、SO2。",
            file_path=None,
            memory_dict={},
            session_id="ctx-store-test",
        )

        args = router._prepare_tool_arguments(
            "calculate_dispersion",
            {"pollutant": "NOx", "_pollutant_source": "batch"},
            state=state,
        )

        assert args["pollutant"] == "NOx"
        assert args["_pollutant_source"] == "batch"

    def test_hotspot_followup_uses_user_pollutant_dispersion_context(self):
        from core.task_state import TaskState

        router = make_router()
        nox = make_dispersion_result(pollutant="NOx", mean_concentration=1.0)
        co2 = make_dispersion_result(pollutant="CO2", mean_concentration=10.0)
        router._save_result_to_session_context("calculate_dispersion", nox)
        router._save_result_to_session_context("calculate_dispersion", co2)
        state = TaskState.initialize(
            user_message="CO2的热点呢？",
            file_path=None,
            memory_dict={},
            session_id="ctx-store-test",
        )

        args = router._prepare_tool_arguments("analyze_hotspots", {}, state=state)

        assert args["pollutant"] == "CO2"
        assert args["_last_result"] == co2

    def test_plan_validation_uses_context_store_results(self):
        router = make_router()
        router._save_result_to_session_context("calculate_macro_emission", make_emission_result())

        from core.task_state import TaskState

        task_state = TaskState.initialize(
            user_message="继续做扩散分析",
            file_path=None,
            memory_dict={},
            session_id="ctx-store-test",
        )
        task_state.set_plan(
            ExecutionPlan(
                goal="Run dispersion after emission",
                steps=[PlanStep(step_id="s1", tool_name="calculate_dispersion")],
            )
        )

        validation = router._validate_execution_plan(task_state)

        assert validation is not None
        assert task_state.plan is not None
        assert task_state.plan.status == PlanStatus.VALID
        assert task_state.plan.steps[0].status == PlanStepStatus.READY

    def test_current_result_passes_dependency_validation(self):
        router = make_router()
        router._save_result_to_session_context("calculate_macro_emission", make_emission_result())

        validation = validate_tool_prerequisites(
            "calculate_dispersion",
            available_tokens=set(),
            context_store=router.context_store,
            include_stale=False,
        )

        assert validation.is_valid is True
        assert validation.missing_tokens == []
        assert validation.stale_tokens == []

    def test_stale_result_fails_dependency_validation_by_default(self):
        router = make_router()
        router._save_result_to_session_context("calculate_dispersion", make_dispersion_result("baseline"))
        router._save_result_to_session_context("calculate_macro_emission", make_emission_result("baseline"))

        validation = validate_tool_prerequisites(
            "analyze_hotspots",
            available_tokens=set(),
            context_store=router.context_store,
            include_stale=False,
        )

        assert validation.is_valid is False
        assert validation.missing_tokens == []
        assert validation.stale_tokens == ["dispersion"]

    def test_canonical_token_path_ignores_legacy_alias_noise(self):
        router = make_router()
        router._save_result_to_session_context("calculate_macro_emission", make_emission_result())

        availability = router.context_store.get_result_availability("emission_result")
        validation = validate_tool_prerequisites(
            "calculate_dispersion",
            available_tokens={"emission_result"},
            context_store=router.context_store,
            include_stale=False,
        )

        assert availability["token"] == "emission"
        assert validation.is_valid is True

    def test_tool_result_message_under_limit(self):
        router = make_router()
        huge_result = {
            "success": True,
            "summary": "A" * 4000,
            "data": {
                "summary": {
                    "total_links": 20,
                    "total_emissions_kg_per_hr": {"CO2": 123.45, "NOx": 0.67},
                }
            },
        }

        payload = router._build_tool_result_message("calculate_macro_emission", huge_result, "call-1")

        assert payload["role"] == "tool"
        assert len(payload["content"]) <= 1000
        assert "CO2: 123.45 kg/h" in payload["content"]

    @pytest.mark.anyio
    async def test_all_output_paths_sanitized(self):
        config = get_config()
        config.enable_state_orchestration = True
        config.enable_trace = False

        direct_router = make_router(llm_responses=[LLMResponse(content="hello\nLINESTRING(0 0, 1 1)")])
        direct = await direct_router.chat("say hi")
        assert "LINESTRING" not in direct.text or "已省略" in direct.text

        tool_call = ToolCall(id="call-1", name="query_emission_factors", arguments={})
        fallback_router = make_router(
            llm_responses=[
                LLMResponse(content="call tool", tool_calls=[tool_call]),
                LLMResponse(content="bad payload LINESTRING(0 0, 1 1)"),
            ],
            executor_results=[
                {
                    "success": False,
                    "error": True,
                    "message": "bad payload LINESTRING(0 0, 1 1)",
                }
            ],
        )
        fallback = await fallback_router.chat("run failing tool")
        assert "LINESTRING" not in fallback.text

        clarify_router = make_router()
        # Reuse the explicit clarification branch through a minimal TaskState-like object.
        from core.task_state import TaskState, TaskStage

        task_state = TaskState.initialize(
            user_message="need help",
            file_path=None,
            memory_dict={},
            session_id="ctx-store-test",
        )
        task_state.stage = TaskStage.NEEDS_CLARIFICATION
        task_state.control.clarification_question = "Please confirm\nLINESTRING(0 0, 1 1)"
        clarified = await clarify_router._state_build_response(task_state, "need help", trace_obj=None)
        assert "LINESTRING" not in clarified.text or "已省略" in clarified.text

    @pytest.mark.anyio
    async def test_render_hotspot_blocks_without_hotspot_result(self):
        config = get_config()
        config.enable_state_orchestration = True
        config.enable_trace = True

        tool_call = ToolCall(
            id="call-render-hotspot",
            name="render_spatial_map",
            arguments={"layer_type": "hotspot"},
        )
        router = make_router(
            llm_responses=[LLMResponse(content="render hotspot", tool_calls=[tool_call])],
            executor_results=[],
        )

        result = await router.chat("render hotspot map", trace={})

        assert "Cannot execute render_spatial_map" in result.text
        assert "hotspot" in result.text
        assert any(step["step_type"] == "dependency_blocked" for step in result.trace["steps"])
        router.executor.execute.assert_not_awaited()
