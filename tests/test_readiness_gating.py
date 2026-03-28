from __future__ import annotations

from core.readiness import ReadinessStatus, build_readiness_assessment
from core.context_store import SessionContextStore
from tests.test_context_store import make_emission_result


def _macro_file_context(*, status: str = "complete", has_geometry: bool = False) -> dict:
    diagnostics = {
        "task_type": "macro_emission",
        "status": status,
        "required_fields": ["link_id", "traffic_flow_vph", "avg_speed_kph"],
        "required_field_statuses": [
            {
                "field": "link_id",
                "status": "present",
                "mapped_from": "segment_id",
                "candidate_columns": [],
                "reason": "present",
            },
            {
                "field": "traffic_flow_vph",
                "status": "present" if status == "complete" else "missing",
                "mapped_from": "daily_traffic" if status == "complete" else None,
                "candidate_columns": [],
                "reason": "present" if status == "complete" else "missing",
            },
            {
                "field": "avg_speed_kph",
                "status": "present",
                "mapped_from": "avg_speed",
                "candidate_columns": [],
                "reason": "present",
            },
        ],
        "missing_fields": [] if status == "complete" else [{"field": "traffic_flow_vph", "status": "missing"}],
        "derivable_opportunities": [],
    }
    payload = {
        "task_type": "macro_emission",
        "confidence": 0.92,
        "columns": ["segment_id", "daily_traffic", "avg_speed"],
        "column_mapping": {
            "segment_id": "link_id",
            "daily_traffic": "traffic_flow_vph" if status == "complete" else "daily_traffic",
            "avg_speed": "avg_speed_kph",
        },
        "missing_field_diagnostics": diagnostics,
    }
    if has_geometry:
        payload["spatial_metadata"] = {
            "crs": "EPSG:4326",
            "bounds": {"min_x": 121.4, "min_y": 31.2, "max_x": 121.6, "max_y": 31.4},
        }
    return payload


def _emission_result(*, with_geometry: bool) -> dict:
    result = make_emission_result()
    if not with_geometry:
        for row in result["data"]["results"]:
            row["geometry"] = None
    return result


def test_geometry_missing_marks_spatial_actions_not_ready():
    store = SessionContextStore()
    result = _emission_result(with_geometry=False)
    store.store_result("calculate_macro_emission", result)

    assessment = build_readiness_assessment(
        _macro_file_context(status="complete", has_geometry=False),
        store,
        [{"name": "calculate_macro_emission", "result": result}],
    )

    render_affordance = assessment.get_action("render_emission_map")
    dispersion_affordance = assessment.get_action("run_dispersion")

    assert render_affordance is not None
    assert render_affordance.status == ReadinessStatus.REPAIRABLE
    assert render_affordance.reason is not None
    assert render_affordance.reason.reason_code == "missing_geometry"

    assert dispersion_affordance is not None
    assert dispersion_affordance.status == ReadinessStatus.REPAIRABLE
    assert dispersion_affordance.reason is not None
    assert dispersion_affordance.reason.reason_code == "missing_geometry"


def test_missing_traffic_flow_marks_macro_action_repairable():
    assessment = build_readiness_assessment(
        _macro_file_context(status="partial", has_geometry=False),
        None,
        [],
    )

    affordance = assessment.get_action("run_macro_emission")

    assert affordance is not None
    assert affordance.status == ReadinessStatus.REPAIRABLE
    assert affordance.reason is not None
    assert affordance.reason.reason_code == "missing_required_fields"
    assert any("交通流量" in item for item in affordance.reason.missing_requirements)


def test_download_artifact_already_provided_is_deduplicated():
    result = _emission_result(with_geometry=True)
    result["data"]["download_file"] = {
        "path": "/tmp/emission.xlsx",
        "filename": "emission.xlsx",
    }

    assessment = build_readiness_assessment(
        _macro_file_context(status="complete", has_geometry=True),
        None,
        [{"name": "calculate_macro_emission", "result": result}],
        current_response_payloads={"download_file": result["data"]["download_file"]},
    )

    affordance = assessment.get_action("download_detailed_csv")
    assert affordance is not None
    assert affordance.status == ReadinessStatus.ALREADY_PROVIDED
    assert affordance.provided_artifact is not None
    assert affordance.provided_artifact.artifact_id == "download_detailed_csv"


def test_standard_macro_input_is_ready():
    assessment = build_readiness_assessment(
        _macro_file_context(status="complete", has_geometry=False),
        None,
        [],
    )

    affordance = assessment.get_action("run_macro_emission")
    assert affordance is not None
    assert affordance.status == ReadinessStatus.READY
