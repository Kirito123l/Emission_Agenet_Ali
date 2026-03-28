from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.supplemental_merge import (
    SupplementalMergeContext,
    apply_supplemental_merge_analysis_refresh,
    build_supplemental_merge_plan,
    execute_supplemental_merge,
)


def _primary_analysis(file_path: str) -> dict:
    return {
        "file_path": file_path,
        "filename": Path(file_path).name,
        "task_type": "macro_emission",
        "columns": ["segment_id", "length_km", "avg_speed"],
        "macro_mapping": {
            "segment_id": "link_id",
            "length_km": "link_length_km",
            "avg_speed": "avg_speed_kph",
        },
        "column_mapping": {
            "segment_id": "link_id",
            "length_km": "link_length_km",
            "avg_speed": "avg_speed_kph",
        },
        "missing_field_diagnostics": {
            "task_type": "macro_emission",
            "status": "partial",
            "required_fields": ["link_id", "traffic_flow_vph", "avg_speed_kph"],
            "required_field_statuses": [
                {"field": "link_id", "status": "present", "mapped_from": "segment_id"},
                {"field": "traffic_flow_vph", "status": "missing", "mapped_from": None},
                {"field": "avg_speed_kph", "status": "present", "mapped_from": "avg_speed"},
            ],
            "missing_fields": [{"field": "traffic_flow_vph", "status": "missing"}],
            "derivable_opportunities": [],
        },
    }


def _supplemental_analysis(
    file_path: str,
    *,
    key_column: str = "segment_id",
    value_column: str = "traffic_flow_vph",
    include_key_mapping: bool = True,
    include_value_mapping: bool = True,
) -> dict:
    macro_mapping = {}
    if include_key_mapping:
        macro_mapping[key_column] = "link_id"
    if include_value_mapping:
        macro_mapping[value_column] = "traffic_flow_vph"
    return {
        "file_path": file_path,
        "filename": Path(file_path).name,
        "task_type": "macro_emission",
        "columns": [key_column, value_column],
        "macro_mapping": macro_mapping,
        "column_mapping": macro_mapping,
        "missing_field_diagnostics": {
            "task_type": "macro_emission",
            "status": "partial",
            "required_fields": ["link_id", "traffic_flow_vph", "avg_speed_kph"],
            "required_field_statuses": [],
            "missing_fields": [],
            "derivable_opportunities": [],
        },
    }


def _build_context(primary_path: str, supplemental_path: str, supplemental_analysis: dict) -> SupplementalMergeContext:
    return SupplementalMergeContext(
        primary_file_summary={"file_path": primary_path, "file_name": Path(primary_path).name},
        supplemental_file_summary={"file_path": supplemental_path, "file_name": Path(supplemental_path).name},
        primary_file_analysis=_primary_analysis(primary_path),
        supplemental_file_analysis=supplemental_analysis,
        current_task_type="macro_emission",
        target_missing_canonical_fields=["traffic_flow_vph"],
        current_residual_workflow_summary="Goal: run_macro_emission",
        relationship_decision_summary={"relationship_type": "merge_supplemental_columns"},
    )


def test_build_plan_selects_segment_id_and_missing_flow_column(tmp_path):
    primary_path = tmp_path / "roads.csv"
    supplemental_path = tmp_path / "flow.csv"
    context = _build_context(
        str(primary_path),
        str(supplemental_path),
        _supplemental_analysis(str(supplemental_path)),
    )

    plan = build_supplemental_merge_plan(context, allow_alias_keys=True)

    assert plan.plan_status == "ready"
    assert plan.merge_keys[0].primary_column == "segment_id"
    assert plan.merge_keys[0].supplemental_column == "segment_id"
    assert plan.canonical_targets["traffic_flow_vph"] == "traffic_flow_vph"
    assert plan.candidate_columns_to_import == ["traffic_flow_vph"]


def test_build_plan_supports_seg_id_alias_key(tmp_path):
    primary_path = tmp_path / "roads.csv"
    supplemental_path = tmp_path / "flow_alias.csv"
    context = _build_context(
        str(primary_path),
        str(supplemental_path),
        _supplemental_analysis(
            str(supplemental_path),
            key_column="seg_id",
            value_column="flow",
            include_key_mapping=False,
            include_value_mapping=True,
        ),
    )

    plan = build_supplemental_merge_plan(context, allow_alias_keys=True)

    assert plan.plan_status == "ready"
    assert plan.merge_keys[0].primary_column == "segment_id"
    assert plan.merge_keys[0].supplemental_column == "seg_id"
    assert plan.attachments[0].supplemental_column == "flow"


def test_build_plan_fails_without_reliable_key(tmp_path):
    primary_path = tmp_path / "roads.csv"
    supplemental_path = tmp_path / "flow_no_key.csv"
    context = _build_context(
        str(primary_path),
        str(supplemental_path),
        {
            "file_path": str(supplemental_path),
            "filename": supplemental_path.name,
            "task_type": "macro_emission",
            "columns": ["district", "traffic_flow_vph"],
            "macro_mapping": {"traffic_flow_vph": "traffic_flow_vph"},
            "column_mapping": {"traffic_flow_vph": "traffic_flow_vph"},
        },
    )

    plan = build_supplemental_merge_plan(context, allow_alias_keys=True)

    assert plan.plan_status != "ready"
    assert "reliable key" in (plan.failure_reason or "")


def test_build_plan_fails_when_supplemental_lacks_target_missing_field(tmp_path):
    primary_path = tmp_path / "roads.csv"
    supplemental_path = tmp_path / "length_only.csv"
    context = _build_context(
        str(primary_path),
        str(supplemental_path),
        {
            "file_path": str(supplemental_path),
            "filename": supplemental_path.name,
            "task_type": "macro_emission",
            "columns": ["segment_id", "length_km"],
            "macro_mapping": {
                "segment_id": "link_id",
                "length_km": "link_length_km",
            },
            "column_mapping": {
                "segment_id": "link_id",
                "length_km": "link_length_km",
            },
        },
    )

    plan = build_supplemental_merge_plan(context, allow_alias_keys=True)

    assert plan.plan_status != "ready"
    assert "missing canonical fields" in (plan.failure_reason or "")


def test_execute_merge_materializes_csv_and_tracks_coverage(tmp_path):
    primary_path = tmp_path / "roads.csv"
    supplemental_path = tmp_path / "flow.csv"
    pd.DataFrame(
        {
            "segment_id": ["S1", "S2", "S3"],
            "length_km": [1.1, 2.2, 3.3],
            "avg_speed": [40, 45, 50],
        }
    ).to_csv(primary_path, index=False)
    pd.DataFrame(
        {
            "segment_id": ["S1", "S2", "S3"],
            "traffic_flow_vph": [1000, 1200, 1300],
        }
    ).to_csv(supplemental_path, index=False)

    context = _build_context(
        str(primary_path),
        str(supplemental_path),
        _supplemental_analysis(str(supplemental_path)),
    )
    plan = build_supplemental_merge_plan(context, allow_alias_keys=True)

    result = execute_supplemental_merge(
        plan,
        outputs_dir=tmp_path,
        session_id="merge-test",
    )

    assert result.success is True
    assert result.materialized_primary_file_ref is not None
    materialized = Path(result.materialized_primary_file_ref)
    assert materialized.exists()
    merged_df = pd.read_csv(materialized)
    assert "traffic_flow_vph" in merged_df.columns
    assert merged_df["traffic_flow_vph"].tolist() == [1000, 1200, 1300]
    assert result.attachments[0].coverage_ratio == 1.0


def test_apply_merge_refresh_keeps_partial_coverage_unresolved(tmp_path):
    primary_path = tmp_path / "roads.csv"
    supplemental_path = tmp_path / "flow_partial.csv"
    pd.DataFrame(
        {
            "segment_id": ["S1", "S2", "S3"],
            "length_km": [1.1, 2.2, 3.3],
            "avg_speed": [40, 45, 50],
        }
    ).to_csv(primary_path, index=False)
    pd.DataFrame(
        {
            "segment_id": ["S1", "S2"],
            "traffic_flow_vph": [1000, 1200],
        }
    ).to_csv(supplemental_path, index=False)

    context = _build_context(
        str(primary_path),
        str(supplemental_path),
        _supplemental_analysis(str(supplemental_path)),
    )
    plan = build_supplemental_merge_plan(context, allow_alias_keys=True)
    result = execute_supplemental_merge(
        plan,
        outputs_dir=tmp_path,
        session_id="merge-test",
    )

    merged_analysis = {
        "file_path": result.materialized_primary_file_ref,
        "task_type": "macro_emission",
        "columns": ["segment_id", "length_km", "avg_speed", "traffic_flow_vph"],
        "column_mapping": {
            "segment_id": "link_id",
            "length_km": "link_length_km",
            "avg_speed": "avg_speed_kph",
            "traffic_flow_vph": "traffic_flow_vph",
        },
        "macro_mapping": {
            "segment_id": "link_id",
            "length_km": "link_length_km",
            "avg_speed": "avg_speed_kph",
            "traffic_flow_vph": "traffic_flow_vph",
        },
        "missing_field_diagnostics": {
            "task_type": "macro_emission",
            "status": "complete",
            "required_fields": ["link_id", "traffic_flow_vph", "avg_speed_kph"],
            "required_field_statuses": [
                {"field": "link_id", "status": "present", "mapped_from": "segment_id"},
                {"field": "traffic_flow_vph", "status": "present", "mapped_from": "traffic_flow_vph"},
                {"field": "avg_speed_kph", "status": "present", "mapped_from": "avg_speed"},
            ],
            "missing_fields": [],
            "derivable_opportunities": [],
        },
    }

    refreshed = apply_supplemental_merge_analysis_refresh(
        merged_analysis,
        plan=plan,
        result=result,
    )

    diagnostics = refreshed["missing_field_diagnostics"]
    flow_status = next(
        item for item in diagnostics["required_field_statuses"] if item["field"] == "traffic_flow_vph"
    )
    assert result.success is True
    assert result.attachments[0].coverage_ratio < 1.0
    assert flow_status["status"] == "partial_merge"
    assert diagnostics["status"] == "partial"
