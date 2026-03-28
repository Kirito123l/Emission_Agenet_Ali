from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from config import get_config
from core.task_state import TaskStage, TaskState
from core.trace import Trace
from services.llm_client import LLMResponse, ToolCall
from tests.test_context_store import make_emission_result
from tests.test_router_state_loop import (
    FakeMemory,
    _irrelevant_supporting_analysis,
    _macro_file_analysis,
    _supporting_spatial_geojson_analysis,
    make_router,
)


@pytest.mark.anyio
async def test_transcript_geometry_recovery_upload_restores_actionability_without_auto_execution():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_readiness_gating = True
    config.enable_input_completion_flow = True
    config.enable_geometry_recovery_path = True

    router = make_router(
        llm_response=LLMResponse(
            content="call render",
            tool_calls=[ToolCall(id="c1", name="render_spatial_map", arguments={"layer_type": "emission"})],
        )
    )
    router._analyze_file = AsyncMock(return_value=_supporting_spatial_geojson_analysis())

    emission_result = make_emission_result()
    for row in emission_result["data"]["results"]:
        row["geometry"] = None
    router._ensure_context_store().store_result("calculate_macro_emission", emission_result)
    router.memory = FakeMemory(
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=False),
        }
    )

    first_state = TaskState.initialize(
        user_message="帮我画排放地图",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    first_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(first_state, trace_obj=first_trace)
    await router._state_handle_grounded(first_state, trace_obj=first_trace)
    await router._state_handle_executing(first_state, trace_obj=first_trace)

    second_state = TaskState.initialize(
        user_message="上传文件",
        file_path="/tmp/roads.geojson",
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    second_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(second_state, trace_obj=second_trace)
    response = await router._state_build_response(second_state, "上传文件", trace_obj=second_trace)

    assert second_state.stage == TaskStage.DONE
    assert second_state.geometry_recovery_context is not None
    assert second_state.geometry_recovery_context.recovery_status == "resumable"
    assert second_state.residual_reentry_context is not None
    assert second_state.residual_reentry_context.reentry_target.target_action_id == "render_emission_map"
    assert second_state.geometry_readiness_refresh_result["after_status"] == "ready"
    assert "不会自动执行后续工具" in response.text
    assert "优先回到" in response.text
    router.executor.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_transcript_irrelevant_supporting_file_does_not_fake_geometry_recovery():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_readiness_gating = True
    config.enable_input_completion_flow = True
    config.enable_geometry_recovery_path = True

    router = make_router(
        llm_response=LLMResponse(
            content="call render",
            tool_calls=[ToolCall(id="c1", name="render_spatial_map", arguments={"layer_type": "emission"})],
        )
    )
    router._analyze_file = AsyncMock(return_value=_irrelevant_supporting_analysis())

    emission_result = make_emission_result()
    for row in emission_result["data"]["results"]:
        row["geometry"] = None
    router._ensure_context_store().store_result("calculate_macro_emission", emission_result)
    router.memory = FakeMemory(
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=False),
        }
    )

    first_state = TaskState.initialize(
        user_message="帮我画排放地图",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    first_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(first_state, trace_obj=first_trace)
    await router._state_handle_grounded(first_state, trace_obj=first_trace)
    await router._state_handle_executing(first_state, trace_obj=first_trace)

    second_state = TaskState.initialize(
        user_message="上传文件",
        file_path="/tmp/notes.csv",
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    second_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(second_state, trace_obj=second_trace)
    response = await router._state_build_response(second_state, "上传文件", trace_obj=second_trace)

    assert second_state.stage == TaskStage.NEEDS_INPUT_COMPLETION
    assert second_state.geometry_recovery_context is not None
    assert second_state.geometry_recovery_context.recovery_status == "failed"
    assert "usable geometry support" in (second_state.geometry_recovery_context.failure_reason or "")
    assert "usable geometry support" in response.text
    assert any(step.step_type.value == "geometry_re_grounding_failed" for step in second_trace.steps)
    router.executor.execute.assert_not_awaited()
