from __future__ import annotations

from services.llm_client import LLMResponse, ToolCall
from core.task_state import TaskStage, TaskState
from core.trace import Trace
from config import get_config
from tests.test_context_store import make_emission_result
from tests.test_router_state_loop import FakeMemory, _macro_file_analysis, make_router

import pytest


@pytest.mark.anyio
async def test_transcript_missing_flow_enters_structured_completion():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_readiness_gating = True
    config.enable_input_completion_flow = True

    router = make_router(
        llm_response=LLMResponse(
            content="call macro",
            tool_calls=[ToolCall(id="c1", name="calculate_macro_emission", arguments={"pollutants": ["CO2"]})],
        )
    )
    router.memory = FakeMemory(
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=False, missing_flow=True),
        }
    )

    state = TaskState.initialize(
        user_message="默认就好，先算排放",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    trace_obj = Trace.start(session_id="test-session")

    await router._state_handle_input(state, trace_obj=trace_obj)
    await router._state_handle_grounded(state, trace_obj=trace_obj)
    await router._state_handle_executing(state, trace_obj=trace_obj)

    assert state.stage == TaskStage.NEEDS_INPUT_COMPLETION
    assert state.active_input_completion is not None
    assert state.active_input_completion.reason_code.value == "missing_required_field"
    assert "1500" in (state.control.input_completion_prompt or "")
    router.executor.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_transcript_missing_geometry_enters_structured_completion():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_readiness_gating = True
    config.enable_input_completion_flow = True

    router = make_router(
        llm_response=LLMResponse(
            content="call render",
            tool_calls=[ToolCall(id="c1", name="render_spatial_map", arguments={"layer_type": "emission"})],
        )
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

    state = TaskState.initialize(
        user_message="帮我画地图",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    trace_obj = Trace.start(session_id="test-session")

    await router._state_handle_input(state, trace_obj=trace_obj)
    await router._state_handle_grounded(state, trace_obj=trace_obj)
    await router._state_handle_executing(state, trace_obj=trace_obj)

    assert state.stage == TaskStage.NEEDS_INPUT_COMPLETION
    assert state.active_input_completion is not None
    assert state.active_input_completion.reason_code.value == "missing_geometry"
    assert "上传" in (state.control.input_completion_prompt or "")
    router.executor.execute.assert_not_awaited()
