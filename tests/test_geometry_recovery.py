from __future__ import annotations

from core.context_store import SessionContextStore
from core.geometry_recovery import (
    SupportingSpatialInput,
    build_geometry_recovery_context,
    re_ground_with_supporting_spatial_input,
)
from core.readiness import ReadinessStatus, build_readiness_assessment
from tests.test_context_store import make_emission_result
from tests.test_router_state_loop import _macro_file_analysis


def _supporting_geojson_analysis() -> dict:
    return {
        "filename": "roads.geojson",
        "file_path": "/tmp/roads.geojson",
        "format": "geojson",
        "task_type": "macro_emission",
        "confidence": 0.84,
        "columns": ["segment_id", "name"],
        "dataset_roles": [
            {
                "dataset_name": "roads.geojson",
                "role": "primary_analysis",
                "format": "geojson",
                "selected": True,
            }
        ],
        "spatial_metadata": {
            "geometry_types": ["LineString"],
            "bounds": {"min_x": 121.4, "min_y": 31.2, "max_x": 121.6, "max_y": 31.4},
        },
    }


def _unsupported_tabular_analysis() -> dict:
    return {
        "filename": "notes.csv",
        "file_path": "/tmp/notes.csv",
        "format": "csv",
        "task_type": "unknown",
        "confidence": 0.18,
        "columns": ["note", "description"],
        "dataset_roles": [
            {
                "dataset_name": "notes.csv",
                "role": "primary_analysis",
                "format": "tabular",
                "selected": True,
            }
        ],
        "spatial_metadata": {},
    }


def test_supporting_spatial_file_attach_builds_formal_object():
    supporting = SupportingSpatialInput.from_analysis(
        file_ref="/tmp/roads.geojson",
        source="input_completion_upload",
        analysis_dict=_supporting_geojson_analysis(),
    )

    assert isinstance(supporting, SupportingSpatialInput)
    assert supporting.file_ref == "/tmp/roads.geojson"
    assert supporting.file_name == "roads.geojson"
    assert supporting.file_type == "geojson"
    assert supporting.geometry_capability_summary["has_geometry_support"] is True
    assert supporting.dataset_roles[0]["dataset_name"] == "roads.geojson"


def test_re_grounding_success_refreshes_geometry_support_for_target_action():
    primary_file_context = _macro_file_analysis(has_geometry=False)
    supporting = SupportingSpatialInput.from_analysis(
        file_ref="/tmp/roads.geojson",
        source="input_completion_upload",
        analysis_dict=_supporting_geojson_analysis(),
    )
    recovery_context = build_geometry_recovery_context(
        primary_file_ref="/tmp/roads.csv",
        supporting_spatial_input=supporting,
        target_action_id="render_emission_map",
        target_task_type="macro_emission",
        residual_plan_summary="Next: s2 -> render_spatial_map",
    )

    result = re_ground_with_supporting_spatial_input(
        primary_file_context=primary_file_context,
        supporting_spatial_input=supporting,
        target_action_id=recovery_context.target_action_id,
        target_task_type=recovery_context.target_task_type,
        residual_plan_summary=recovery_context.residual_plan_summary,
    )

    context_store = SessionContextStore()
    emission_result = make_emission_result()
    for row in emission_result["data"]["results"]:
        row["geometry"] = None
    context_store.store_result("calculate_macro_emission", emission_result)
    assessment = build_readiness_assessment(
        result.updated_file_context,
        context_store,
        current_tool_results=[],
    )
    affordance = assessment.get_action("render_emission_map")

    assert result.success is True
    assert result.geometry_support_established is True
    assert result.updated_file_context["spatial_context"]["mode"] == "supporting_spatial_input"
    assert affordance is not None
    assert affordance.status == ReadinessStatus.READY


def test_re_grounding_failure_does_not_fake_geometry_recovery():
    primary_file_context = _macro_file_analysis(has_geometry=False)
    supporting = SupportingSpatialInput.from_analysis(
        file_ref="/tmp/notes.csv",
        source="input_completion_upload",
        analysis_dict=_unsupported_tabular_analysis(),
    )

    result = re_ground_with_supporting_spatial_input(
        primary_file_context=primary_file_context,
        supporting_spatial_input=supporting,
        target_action_id="render_emission_map",
        target_task_type="macro_emission",
        residual_plan_summary="Next: s2 -> render_spatial_map",
    )

    assessment = build_readiness_assessment(
        primary_file_context,
        SessionContextStore(),
        current_tool_results=[],
    )
    affordance = assessment.get_action("render_emission_map")

    assert result.success is False
    assert result.failure_reason is not None
    assert "geometry support" in result.failure_reason.lower()
    assert affordance is not None
    assert affordance.status == ReadinessStatus.REPAIRABLE


def test_re_grounding_returns_bounded_recompute_recommendation_without_execution_state():
    supporting = SupportingSpatialInput.from_analysis(
        file_ref="/tmp/roads.geojson",
        source="input_completion_upload",
        analysis_dict=_supporting_geojson_analysis(),
    )

    result = re_ground_with_supporting_spatial_input(
        primary_file_context=_macro_file_analysis(has_geometry=False),
        supporting_spatial_input=supporting,
        target_action_id="run_dispersion",
        target_task_type="macro_emission",
        residual_plan_summary="Next: s3 -> calculate_dispersion",
    )

    assert result.success is True
    assert result.upstream_recompute_recommendation is not None
    assert "下一轮" in result.upstream_recompute_recommendation
    assert "tool_results" not in result.updated_file_context
    assert "executor" not in result.updated_file_context
