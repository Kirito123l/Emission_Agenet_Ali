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
    _macro_file_analysis,
    _supporting_spatial_geojson_analysis,
    make_router,
)


@pytest.mark.anyio
async def test_transcript_recovered_continuation_prefers_map_render_reentry_target():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_readiness_gating = True
    config.enable_input_completion_flow = True
    config.enable_geometry_recovery_path = True
    config.enable_residual_reentry_controller = True
    config.enable_workflow_templates = True

    router = make_router(
        llm_response=LLMResponse(
            content="call dispersion",
            tool_calls=[ToolCall(id="c1", name="calculate_dispersion", arguments={"pollutant": "NOx"})],
        )
    )
    router._analyze_file = AsyncMock(return_value=_supporting_spatial_geojson_analysis())
    router.llm.chat_with_tools = AsyncMock(
        side_effect=[
            LLMResponse(
                content="call render",
                tool_calls=[ToolCall(id="c1", name="render_spatial_map", arguments={"layer_type": "emission"})],
            ),
            LLMResponse(
                content="resume render",
                tool_calls=[ToolCall(id="c2", name="render_spatial_map", arguments={"layer_type": "emission"})],
            ),
        ]
    )

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

    third_state = TaskState.initialize(
        user_message="继续",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    third_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(third_state, trace_obj=third_trace)
    await router._state_handle_grounded(third_state, trace_obj=third_trace)

    injected_messages = router.llm.chat_with_tools.await_args_list[-1].kwargs["messages"]

    assert third_state.continuation is not None
    assert third_state.continuation.should_continue is True
    assert third_state.residual_reentry_context is not None
    assert third_state.reentry_bias_applied is True
    assert third_state.execution.selected_tool == "render_spatial_map"
    assert any(step.step_type.value == "residual_reentry_decided" for step in third_trace.steps)
    assert any(step.step_type.value == "residual_reentry_injected" for step in third_trace.steps)
    assert any(step.step_type.value == "workflow_template_skipped" for step in third_trace.steps)
    assert any(
        msg.get("role") == "system"
        and "Recovered workflow re-entry target" in msg.get("content", "")
        and "render_emission_map" in msg.get("content", "")
        for msg in injected_messages
    )


@pytest.mark.anyio
async def test_transcript_explicit_new_task_skips_recovered_reentry_target():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_readiness_gating = True
    config.enable_input_completion_flow = True
    config.enable_geometry_recovery_path = True
    config.enable_residual_reentry_controller = True

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
        user_message="帮我做扩散分析",
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
    assert second_state.residual_reentry_context is not None

    router.llm.chat_with_tools = AsyncMock(return_value=LLMResponse(content="new task answer"))
    third_state = TaskState.initialize(
        user_message="现在改做另一个任务，不要管前面的",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    third_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(third_state, trace_obj=third_trace)

    assert third_state.stage == TaskStage.DONE
    assert third_state.residual_reentry_context is None
    assert third_state.reentry_bias_applied is False
    assert any(step.step_type.value == "residual_reentry_skipped" for step in third_trace.steps)
