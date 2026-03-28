from __future__ import annotations

from core.capability_summary import get_capability_aware_follow_up
from core.intent_resolution import (
    DeliverableIntentType,
    IntentResolutionApplicationPlan,
    IntentResolutionContext,
    ProgressIntentType,
    apply_intent_bias_to_capability_summary,
    build_intent_resolution_application_plan,
    infer_intent_resolution_fallback,
    parse_intent_resolution_result,
)


def test_parse_intent_resolution_result_normalizes_chart_shift_decision():
    context = IntentResolutionContext(
        user_message="帮我可视化一下",
        current_task_type="macro_emission",
        recent_result_types=["emission"],
        has_geometry_support=False,
    )

    result = parse_intent_resolution_result(
        {
            "deliverable_intent": "chart_or_ranked_summary",
            "progress_intent": "shift_output_mode",
            "confidence": 0.88,
            "reason": "The user wants visualization but the current context is not spatially ready.",
            "current_task_relevance": 0.91,
            "should_bias_existing_action": True,
            "should_preserve_residual_workflow": True,
            "should_trigger_clarification": False,
        },
        context,
    )

    assert result.is_resolved is True
    assert result.decision is not None
    assert result.decision.deliverable_intent == DeliverableIntentType.CHART_OR_RANKED_SUMMARY
    assert result.decision.progress_intent == ProgressIntentType.SHIFT_OUTPUT_MODE
    assert result.decision.user_utterance_summary == "帮我可视化一下"


def test_fallback_visualize_without_geometry_prefers_chart_shift():
    context = IntentResolutionContext(
        user_message="帮我可视化一下",
        current_task_type="macro_emission",
        recent_result_types=["emission"],
        has_geometry_support=False,
        has_residual_workflow=True,
    )

    decision = infer_intent_resolution_fallback(context)
    plan = build_intent_resolution_application_plan(decision, context)

    assert decision.deliverable_intent == DeliverableIntentType.CHART_OR_RANKED_SUMMARY
    assert decision.progress_intent == ProgressIntentType.SHIFT_OUTPUT_MODE
    assert "render_emission_map" in plan.deprioritized_action_ids
    assert "chart" in plan.preferred_artifact_kinds


def test_fallback_continue_with_recovered_target_prefers_resume():
    context = IntentResolutionContext(
        user_message="继续",
        current_task_type="macro_emission",
        residual_workflow_summary="Goal: render the recovered map",
        recovered_target_summary={
            "target_action_id": "render_emission_map",
            "target_tool_name": "render_spatial_map",
        },
        recent_result_types=["emission"],
        has_geometry_support=True,
        has_residual_workflow=True,
        has_recovered_target=True,
    )

    decision = infer_intent_resolution_fallback(context)
    plan = build_intent_resolution_application_plan(decision, context)

    assert decision.progress_intent == ProgressIntentType.RESUME_RECOVERED_TARGET
    assert "render_emission_map" in plan.preferred_action_ids
    assert plan.bias_continuation is True


def test_capability_summary_bias_suppresses_default_map_follow_up_for_chart_shift():
    summary = {
        "available_next_actions": [
            {
                "action_id": "render_emission_map",
                "label": "可视化排放空间分布",
                "description": "地图",
                "utterance": "帮我可视化排放分布",
            },
            {
                "action_id": "compare_scenario",
                "label": "对比情景结果",
                "description": "情景对比",
                "utterance": "把速度降到 30 再比较一下",
            },
        ],
        "repairable_actions": [],
        "unavailable_actions_with_reasons": [],
        "already_provided": [],
        "guidance_hints": [],
    }
    plan = IntentResolutionApplicationPlan(
        deliverable_intent=DeliverableIntentType.CHART_OR_RANKED_SUMMARY,
        progress_intent=ProgressIntentType.SHIFT_OUTPUT_MODE,
        bias_existing_action=True,
        bias_followup_suggestions=True,
        preferred_action_ids=[],
        deprioritized_action_ids=["render_emission_map"],
        preferred_artifact_kinds=["chart", "summary"],
        user_visible_summary="当前更适合用排序图和摘要表展示结果。",
    )

    biased = apply_intent_bias_to_capability_summary(summary, plan)
    follow_up = get_capability_aware_follow_up("calculate_macro_emission", biased)

    assert follow_up["suggestions"] == []
    assert follow_up["hints"][0] == "当前更适合用排序图和摘要表展示结果。"
