from __future__ import annotations

from core.workflow_templates import (
    recommend_workflow_templates,
    select_primary_template,
)


def make_file_analysis(
    *,
    task_type: str = "macro_emission",
    confidence: float = 0.86,
    readiness_status: str = "complete",
    spatial_ready: bool = False,
):
    analysis = {
        "task_type": task_type,
        "confidence": confidence,
        "selected_primary_table": "roads.csv",
        "dataset_roles": [
            {
                "dataset_name": "roads.csv",
                "role": "primary_analysis",
                "format": "csv",
                "selected": True,
            }
        ],
        "dataset_role_summary": {
            "strategy": "rule",
            "ambiguous": False,
            "selected_primary_table": "roads.csv",
        },
        "missing_field_diagnostics": {
            "task_type": task_type,
            "status": readiness_status,
            "required_fields": ["link_length_km", "traffic_flow_vph", "avg_speed_kph"]
            if task_type == "macro_emission"
            else ["vehicle_type", "speed_kph", "timestamp"],
            "missing_fields": [],
            "derivable_opportunities": [],
        },
        "macro_has_required": readiness_status == "complete" if task_type == "macro_emission" else False,
        "micro_has_required": readiness_status == "complete" if task_type == "micro_emission" else False,
        "spatial_metadata": {},
    }
    if spatial_ready:
        analysis["spatial_metadata"] = {
            "geometry_types": ["LineString"],
            "crs": "EPSG:4326",
            "feature_count": 24,
            "bounds": {"min_x": 0.0, "min_y": 0.0, "max_x": 1.0, "max_y": 1.0},
        }
    return analysis


def test_macro_emission_basic_template_recommended_and_selected():
    analysis = make_file_analysis(task_type="macro_emission", readiness_status="complete")

    recommendations = recommend_workflow_templates(
        analysis,
        user_message="分析这个路网文件",
        max_recommendations=3,
        min_confidence=0.45,
    )
    selection = select_primary_template(recommendations, min_confidence=0.55)

    assert recommendations
    assert recommendations[0].template_id == "macro_emission_baseline"
    assert recommendations[0].is_applicable is True
    assert selection.recommended_template_id == "macro_emission_baseline"
    assert selection.template_prior_used is True
    assert selection.selected_template is not None


def test_micro_emission_template_is_preferred_for_micro_task():
    analysis = make_file_analysis(task_type="micro_emission", readiness_status="complete")

    recommendations = recommend_workflow_templates(
        analysis,
        user_message="做微观排放分析",
        max_recommendations=3,
        min_confidence=0.45,
    )
    selection = select_primary_template(recommendations, min_confidence=0.55)

    assert recommendations
    assert recommendations[0].template_id == "micro_emission_baseline"
    assert all(item.template_id != "macro_spatial_chain" for item in recommendations)
    assert selection.recommended_template_id == "micro_emission_baseline"


def test_spatial_chain_template_can_be_selected_for_spatial_macro_case():
    analysis = make_file_analysis(
        task_type="macro_emission",
        readiness_status="complete",
        spatial_ready=True,
    )

    recommendations = recommend_workflow_templates(
        analysis,
        user_message="先做扩散热点，再渲染地图",
        max_recommendations=4,
        min_confidence=0.45,
    )
    selection = select_primary_template(recommendations, min_confidence=0.55)

    assert recommendations
    assert recommendations[0].template_id == "macro_spatial_chain"
    assert "spatial_ready" in recommendations[0].matched_signals
    assert selection.recommended_template_id == "macro_spatial_chain"


def test_insufficient_readiness_prevents_confident_template_prior_use():
    analysis = make_file_analysis(
        task_type="macro_emission",
        readiness_status="insufficient",
        confidence=0.82,
    )

    recommendations = recommend_workflow_templates(
        analysis,
        user_message="分析这个文件",
        max_recommendations=3,
        min_confidence=0.45,
    )
    selection = select_primary_template(recommendations, min_confidence=0.55)

    assert recommendations
    assert recommendations[0].template_id == "macro_emission_baseline"
    assert recommendations[0].is_applicable is False
    assert "file_readiness_insufficient" in recommendations[0].unmet_requirements
    assert selection.template_prior_used is False
    assert selection.recommended_template_id is None


def test_unknown_task_type_skips_template_recommendation():
    analysis = make_file_analysis(task_type="unknown", confidence=0.28, readiness_status="unknown_task")

    recommendations = recommend_workflow_templates(
        analysis,
        user_message="分析这个文件",
        max_recommendations=3,
        min_confidence=0.45,
    )

    assert recommendations == []
