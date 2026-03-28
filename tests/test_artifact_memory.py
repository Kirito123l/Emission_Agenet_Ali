from __future__ import annotations

from core.artifact_memory import (
    ArtifactDeliveryStatus,
    ArtifactFamily,
    ArtifactMemoryState,
    ArtifactType,
    apply_artifact_memory_to_capability_summary,
    build_artifact_record,
    build_artifact_suggestion_plan,
    classify_artifacts_from_delivery,
    update_artifact_memory,
)
from core.intent_resolution import (
    DeliverableIntentType,
    IntentResolutionApplicationPlan,
    ProgressIntentType,
)


def test_classify_artifacts_from_delivery_records_download_and_partial_summary():
    tool_results = [
        {
            "name": "calculate_macro_emission",
            "arguments": {"pollutants": ["CO2"]},
            "result": {
                "success": True,
                "data": {
                    "download_file": {
                        "path": "/tmp/emission.xlsx",
                        "filename": "emission.xlsx",
                    },
                    "query_info": {"pollutants": ["CO2"]},
                },
            },
        }
    ]

    records = classify_artifacts_from_delivery(
        tool_results=tool_results,
        frontend_payloads={"download_file": {"path": "/tmp/emission.xlsx", "filename": "emission.xlsx"}},
        response_text="已生成详细结果文件，并给出简要说明。",
        delivery_turn_index=3,
        related_task_type="macro_emission",
        track_textual_summary=True,
    )

    by_type = {record.artifact_type: record for record in records}
    assert ArtifactType.DETAILED_CSV in by_type
    assert ArtifactType.QUICK_SUMMARY_TEXT in by_type
    assert by_type[ArtifactType.DETAILED_CSV].delivery_status == ArtifactDeliveryStatus.FULL
    assert by_type[ArtifactType.QUICK_SUMMARY_TEXT].delivery_status == ArtifactDeliveryStatus.PARTIAL


def test_build_artifact_suggestion_plan_detects_repeat_downloadable_table():
    state = update_artifact_memory(
        ArtifactMemoryState(),
        [
            build_artifact_record(
                artifact_type=ArtifactType.DETAILED_CSV,
                delivery_turn_index=1,
                source_tool_name="calculate_macro_emission",
                summary="已提供可下载的详细结果文件。",
                related_task_type="macro_emission",
            )
        ],
    )
    intent_plan = IntentResolutionApplicationPlan(
        deliverable_intent=DeliverableIntentType.DOWNLOADABLE_TABLE,
        progress_intent=ProgressIntentType.SHIFT_OUTPUT_MODE,
    )

    suggestion_plan = build_artifact_suggestion_plan(
        state,
        capability_summary={"available_next_actions": []},
        intent_plan=intent_plan,
    )

    assert "download_detailed_csv" in suggestion_plan.suppressed_action_ids
    assert "detailed_csv" in suggestion_plan.repeated_artifact_types
    assert suggestion_plan.availability_decision is not None
    assert suggestion_plan.availability_decision.same_type_full_provided is True


def test_same_family_different_type_is_not_treated_as_repeat():
    state = update_artifact_memory(
        ArtifactMemoryState(),
        [
            build_artifact_record(
                artifact_type=ArtifactType.TOPK_SUMMARY_TABLE,
                delivery_turn_index=1,
                source_tool_name="analyze_hotspots",
                summary="已提供摘要表或 Top-K 结果表。",
                related_task_type="macro_emission",
            )
        ],
    )
    intent_plan = IntentResolutionApplicationPlan(
        deliverable_intent=DeliverableIntentType.CHART_OR_RANKED_SUMMARY,
        progress_intent=ProgressIntentType.SHIFT_OUTPUT_MODE,
    )

    suggestion_plan = build_artifact_suggestion_plan(
        state,
        capability_summary={"available_next_actions": []},
        intent_plan=intent_plan,
    )

    assert suggestion_plan.availability_decision is not None
    assert suggestion_plan.availability_decision.same_family_full_provided is True
    assert suggestion_plan.availability_decision.same_type_full_provided is False
    assert "same_family_different_type" in suggestion_plan.notes
    assert "ranked_chart" in (suggestion_plan.user_visible_summary or "")


def test_apply_artifact_memory_to_capability_summary_suppresses_repeated_map_follow_up():
    state = update_artifact_memory(
        ArtifactMemoryState(),
        [
            build_artifact_record(
                artifact_type=ArtifactType.SPATIAL_MAP,
                delivery_turn_index=2,
                source_tool_name="render_spatial_map",
                summary="已提供排放空间地图。",
                related_task_type="macro_emission",
            )
        ],
    )
    summary = {
        "available_next_actions": [
            {"action_id": "render_emission_map", "label": "可视化排放空间分布", "utterance": "帮我可视化排放分布"},
            {"action_id": "run_dispersion", "label": "模拟污染物扩散浓度", "utterance": "帮我做扩散分析"},
        ],
        "repairable_actions": [],
        "unavailable_actions_with_reasons": [],
        "already_provided": [],
        "guidance_hints": [],
    }

    biased = apply_artifact_memory_to_capability_summary(summary, state, intent_plan=None)

    available_ids = {item["action_id"] for item in biased["available_next_actions"]}
    assert "render_emission_map" not in available_ids
    assert "run_dispersion" in available_ids
    assert "spatial_map" in biased["artifact_bias"]["repeated_artifact_types"]


def test_partial_text_summary_can_promote_new_output_family():
    state = update_artifact_memory(
        ArtifactMemoryState(),
        [
            build_artifact_record(
                artifact_type=ArtifactType.QUICK_SUMMARY_TEXT,
                delivery_turn_index=1,
                source_tool_name="calculate_macro_emission",
                delivery_status=ArtifactDeliveryStatus.PARTIAL,
                summary="已给出简短文字摘要。",
                related_task_type="macro_emission",
            )
        ],
    )
    intent_plan = IntentResolutionApplicationPlan(
        deliverable_intent=DeliverableIntentType.CHART_OR_RANKED_SUMMARY,
        progress_intent=ProgressIntentType.SHIFT_OUTPUT_MODE,
    )

    suggestion_plan = build_artifact_suggestion_plan(
        state,
        capability_summary={"available_next_actions": []},
        intent_plan=intent_plan,
    )

    assert ArtifactFamily.RANKED_SUMMARY.value in suggestion_plan.promoted_families
    assert "partial_summary_can_expand" in suggestion_plan.notes
    assert "更完整的交付" in (suggestion_plan.user_visible_summary or "")
