from __future__ import annotations

from core.geometry_recovery import (
    SupportingSpatialInput,
    build_geometry_recovery_context,
    re_ground_with_supporting_spatial_input,
)
from core.plan import ExecutionPlan, PlanStep
from core.residual_reentry import build_recovered_workflow_reentry_context
from core.task_state import ContinuationDecision, TaskState
from tests.test_context_store import make_emission_result
from tests.test_geometry_recovery import _supporting_geojson_analysis
from tests.test_router_state_loop import _macro_file_analysis, make_router
from services.llm_client import LLMResponse
from config import get_config


def _build_recovered_state(*, with_geometry_support: bool) -> tuple[object, TaskState]:
    router = make_router(llm_response=LLMResponse(content="unused"))
    supporting = SupportingSpatialInput.from_analysis(
        file_ref="/tmp/roads.geojson",
        source="input_completion_upload",
        analysis_dict=_supporting_geojson_analysis(),
    )
    geometry_context = build_geometry_recovery_context(
        primary_file_ref="/tmp/roads.csv",
        supporting_spatial_input=supporting,
        target_action_id="render_emission_map",
        target_task_type="macro_emission",
        residual_plan_summary="Goal: Render map | Next: s2 -> render_spatial_map [pending]",
        readiness_before={"status": "repairable", "reason_code": "missing_geometry"},
    )
    geometry_context.recovery_status = "resumable"
    geometry_context.resume_hint = "Resume render_emission_map on the next turn."
    geometry_context.readiness_after = {
        "action_id": "render_emission_map",
        "before_status": "repairable",
        "after_status": "ready",
        "status_delta": "repairable->ready",
    }

    plan = ExecutionPlan(
        goal="Render the emission map",
        steps=[
            PlanStep(
                step_id="s2",
                tool_name="render_spatial_map",
                argument_hints={"layer_type": "emission"},
            )
        ],
    )
    reentry_context = build_recovered_workflow_reentry_context(
        geometry_recovery_context=geometry_context,
        readiness_refresh_result=geometry_context.readiness_after,
        residual_plan=plan,
        residual_plan_summary=geometry_context.residual_plan_summary,
        prioritize_recovery_target=True,
    )

    state = TaskState.initialize(
        user_message="继续",
        file_path=None,
        memory_dict={},
        session_id="test-session",
    )
    state.set_plan(plan)
    state.set_geometry_recovery_context(geometry_context)
    state.set_geometry_readiness_refresh_result(dict(geometry_context.readiness_after or {}))
    state.set_residual_reentry_context(reentry_context)

    if with_geometry_support:
        re_grounding = re_ground_with_supporting_spatial_input(
            primary_file_context=_macro_file_analysis(has_geometry=False),
            supporting_spatial_input=supporting,
            target_action_id="render_emission_map",
            target_task_type="macro_emission",
            residual_plan_summary=geometry_context.residual_plan_summary,
        )
        state.update_file_context(re_grounding.updated_file_context)
    else:
        state.update_file_context(_macro_file_analysis(has_geometry=False))

    emission_result = make_emission_result()
    for row in emission_result["data"]["results"]:
        row["geometry"] = None
    router._ensure_context_store().store_result("calculate_macro_emission", emission_result)
    return router, state


def test_recovery_success_sets_formal_reentry_target():
    supporting = SupportingSpatialInput.from_analysis(
        file_ref="/tmp/roads.geojson",
        source="input_completion_upload",
        analysis_dict=_supporting_geojson_analysis(),
    )
    geometry_context = build_geometry_recovery_context(
        primary_file_ref="/tmp/roads.csv",
        supporting_spatial_input=supporting,
        target_action_id="render_emission_map",
        target_task_type="macro_emission",
        residual_plan_summary="Goal: Render map | Next: s2 -> render_spatial_map [pending]",
    )
    plan = ExecutionPlan(
        goal="Render the emission map",
        steps=[
            PlanStep(
                step_id="s2",
                tool_name="render_spatial_map",
                argument_hints={"layer_type": "emission"},
            )
        ],
    )

    reentry_context = build_recovered_workflow_reentry_context(
        geometry_recovery_context=geometry_context,
        readiness_refresh_result={"after_status": "ready"},
        residual_plan=plan,
        residual_plan_summary="Goal: Render map | Next: s2 -> render_spatial_map [pending]",
    )

    assert reentry_context.reentry_target.target_action_id == "render_emission_map"
    assert reentry_context.reentry_target.target_tool_name == "render_spatial_map"
    assert reentry_context.reentry_target.target_step_id == "s2"
    assert reentry_context.reentry_target.source == "geometry_recovery"
    assert "highest-priority continuation hint" in (reentry_context.reentry_guidance_summary or "")


def test_next_turn_continuation_applies_reentry_bias():
    config = get_config()
    previous_flag = config.enable_residual_reentry_controller
    previous_ready_requirement = config.residual_reentry_require_ready_target
    config.enable_residual_reentry_controller = True
    config.residual_reentry_require_ready_target = True

    try:
        router, state = _build_recovered_state(with_geometry_support=True)
        continuation = ContinuationDecision(
            residual_plan_exists=True,
            continuation_ready=True,
            should_continue=True,
            signal="geometry_recovery_resume",
            reason="continue recovered workflow",
            next_step_id="s2",
            next_tool_name="render_spatial_map",
            residual_plan_summary="Goal: Render map | Next: s2 -> render_spatial_map [pending]",
        )

        decision = router._build_residual_reentry_decision(state, continuation)
    finally:
        config.enable_residual_reentry_controller = previous_flag
        config.residual_reentry_require_ready_target = previous_ready_requirement

    assert decision is not None
    assert decision.should_apply is True
    assert decision.decision_status == "applied"
    assert decision.target is not None
    assert decision.target.target_action_id == "render_emission_map"
    assert "Primary re-entry target" in (decision.guidance_summary or "")


def test_explicit_new_task_skips_reentry_bias():
    config = get_config()
    previous_flag = config.enable_residual_reentry_controller
    config.enable_residual_reentry_controller = True

    try:
        router, state = _build_recovered_state(with_geometry_support=True)
        continuation = ContinuationDecision(
            residual_plan_exists=True,
            continuation_ready=True,
            should_continue=False,
            signal="explicit_new_task",
            reason="User explicitly started a new task",
            new_task_override=True,
        )

        decision = router._build_residual_reentry_decision(state, continuation)
    finally:
        config.enable_residual_reentry_controller = previous_flag

    assert decision is not None
    assert decision.should_apply is False
    assert decision.new_task_override is True
    assert "explicitly started a new task" in (decision.reason or "")


def test_target_no_longer_ready_skips_reentry_bias():
    config = get_config()
    previous_flag = config.enable_residual_reentry_controller
    previous_ready_requirement = config.residual_reentry_require_ready_target
    config.enable_residual_reentry_controller = True
    config.residual_reentry_require_ready_target = True

    try:
        router, state = _build_recovered_state(with_geometry_support=False)
        continuation = ContinuationDecision(
            residual_plan_exists=True,
            continuation_ready=True,
            should_continue=True,
            signal="geometry_recovery_resume",
            reason="continue recovered workflow",
            next_step_id="s2",
            next_tool_name="render_spatial_map",
            residual_plan_summary="Goal: Render map | Next: s2 -> render_spatial_map [pending]",
        )

        decision = router._build_residual_reentry_decision(state, continuation)
    finally:
        config.enable_residual_reentry_controller = previous_flag
        config.residual_reentry_require_ready_target = previous_ready_requirement

    assert decision is not None
    assert decision.should_apply is False
    assert decision.decision_status == "stale"
    assert decision.target_ready is False
    assert "not re-validated as ready" in (decision.reason or "")
