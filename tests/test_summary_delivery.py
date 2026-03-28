from __future__ import annotations

from core.artifact_memory import ArtifactMemoryState, ArtifactType, build_artifact_record, update_artifact_memory
from core.intent_resolution import DeliverableIntentType, ProgressIntentType
from core.summary_delivery import (
    SummaryDeliveryContext,
    SummaryDeliveryType,
    build_summary_delivery_plan,
    execute_summary_delivery_plan,
)
from tests.test_context_store import make_emission_result


def _make_context(
    *,
    user_message: str,
    result_payload: dict | None = None,
    has_geometry_support: bool = False,
) -> SummaryDeliveryContext:
    payload = result_payload or make_emission_result()
    return SummaryDeliveryContext(
        user_message=user_message,
        current_task_type="macro_emission",
        deliverable_intent=DeliverableIntentType.CHART_OR_RANKED_SUMMARY,
        progress_intent=ProgressIntentType.SHIFT_OUTPUT_MODE,
        has_geometry_support=has_geometry_support,
        source_result_type="emission",
        source_tool_name="calculate_macro_emission",
        source_label="baseline",
        source_result_summary={"tool": "calculate_macro_emission", "label": "baseline"},
        available_metrics=["CO2_kg_h", "NOx_kg_h"],
        artifact_memory_summary={},
        raw_source_result=payload,
    )


def test_summary_delivery_visualize_without_geometry_prefers_ranked_chart(tmp_path):
    context = _make_context(user_message="帮我可视化一下", has_geometry_support=False)

    plan = build_summary_delivery_plan(
        context,
        ArtifactMemoryState(),
        default_topk=5,
        enable_bar_chart=True,
        allow_text_fallback=True,
    )
    result = execute_summary_delivery_plan(
        plan,
        context,
        outputs_dir=tmp_path,
        delivery_turn_index=3,
        source_tool_name="summary_delivery_surface",
    )

    assert plan.plan_status == "planned"
    assert plan.decision.selected_delivery_type == SummaryDeliveryType.RANKED_BAR_CHART
    assert plan.decision.ranking_metric == "CO2_kg_h"
    assert result.success is True
    assert result.chart_ref["type"] == "ranked_bar_chart"
    assert result.table_preview["type"] == "topk_summary_table"
    assert "当前缺少空间几何" in (result.summary_text or "")
    artifact_types = {item.artifact_type.value for item in result.artifact_records}
    assert artifact_types == {"ranked_chart", "topk_summary_table"}


def test_summary_delivery_switches_to_chart_when_topk_table_was_already_delivered():
    memory = update_artifact_memory(
        ArtifactMemoryState(),
        [
            build_artifact_record(
                artifact_type=ArtifactType.TOPK_SUMMARY_TABLE,
                delivery_turn_index=1,
                source_tool_name="summary_delivery_surface",
                source_action_id="download_topk_summary",
                summary="已提供 Top-K 摘要表。",
                related_task_type="macro_emission",
            )
        ],
    )
    context = _make_context(user_message="给我前5高排放路段摘要表")

    plan = build_summary_delivery_plan(
        context,
        memory,
        default_topk=5,
        enable_bar_chart=True,
        allow_text_fallback=True,
    )

    assert plan.plan_status == "planned"
    assert plan.artifact_repeat_detected is True
    assert plan.decision.selected_delivery_type == SummaryDeliveryType.RANKED_BAR_CHART
    assert plan.decision.switched_from_delivery_type == "topk_summary_table"


def test_summary_delivery_falls_back_to_quick_summary_when_metric_missing():
    bad_result = {
        "success": True,
        "summary": "Emission calculation finished",
        "data": {
            "summary": {"total_links": 2},
            "results": [{"link_id": "L1"}, {"link_id": "L2"}],
        },
    }
    context = SummaryDeliveryContext(
        user_message="帮我可视化一下",
        current_task_type="macro_emission",
        deliverable_intent=DeliverableIntentType.CHART_OR_RANKED_SUMMARY,
        progress_intent=ProgressIntentType.SHIFT_OUTPUT_MODE,
        has_geometry_support=False,
        source_result_type="emission",
        source_tool_name="calculate_macro_emission",
        source_label="baseline",
        source_result_summary={"tool": "calculate_macro_emission"},
        available_metrics=[],
        artifact_memory_summary={},
        raw_source_result=bad_result,
    )

    plan = build_summary_delivery_plan(
        context,
        ArtifactMemoryState(),
        default_topk=5,
        enable_bar_chart=True,
        allow_text_fallback=True,
    )

    assert plan.plan_status == "planned"
    assert plan.decision.selected_delivery_type == SummaryDeliveryType.QUICK_STRUCTURED_SUMMARY
    assert "结构化摘要" in (plan.user_visible_summary or "")


def test_summary_delivery_topk_table_materializes_download_file(tmp_path):
    context = _make_context(user_message="给我前1高排放路段摘要表")

    plan = build_summary_delivery_plan(
        context,
        ArtifactMemoryState(),
        default_topk=5,
        enable_bar_chart=True,
        allow_text_fallback=True,
    )
    result = execute_summary_delivery_plan(
        plan,
        context,
        outputs_dir=tmp_path,
        delivery_turn_index=4,
        source_tool_name="summary_delivery_surface",
    )

    assert plan.decision.selected_delivery_type == SummaryDeliveryType.TOPK_SUMMARY_TABLE
    assert plan.decision.topk == 1
    assert result.success is True
    assert result.download_file is not None
    assert tmp_path.joinpath(result.download_file["filename"]).exists()
    assert result.table_preview["preview_rows"][0]["rank"] == 1
    assert result.artifact_records[0].artifact_type.value == "topk_summary_table"
