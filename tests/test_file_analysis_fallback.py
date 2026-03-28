from core.file_analysis_fallback import (
    FallbackReason,
    merge_rule_and_fallback_analysis,
    parse_llm_file_analysis_result,
    should_use_llm_fallback,
)


def make_rule_analysis(**overrides):
    base = {
        "filename": "roads.csv",
        "format": "tabular",
        "task_type": "macro_emission",
        "confidence": 0.92,
        "columns": ["link_id", "flow", "speed", "length"],
        "row_count": 12,
        "sample_rows": [{"link_id": "L1", "flow": 1200, "speed": 45, "length": 1.2}],
        "micro_mapping": {},
        "macro_mapping": {
            "link_id": "link_id",
            "flow": "traffic_flow_vph",
            "speed": "avg_speed_kph",
            "length": "link_length_km",
        },
        "column_mapping": {
            "link_id": "link_id",
            "flow": "traffic_flow_vph",
            "speed": "avg_speed_kph",
            "length": "link_length_km",
        },
        "micro_has_required": False,
        "macro_has_required": True,
        "evidence": ["rule matched standard macro columns"],
        "candidate_tables": [],
        "zip_contents": [],
        "dataset_roles": [
            {
                "dataset_name": "roads.csv",
                "role": "primary_analysis",
                "format": "tabular",
                "task_type": "macro_emission",
                "confidence": 0.92,
                "selection_score": 0.92,
                "reason": "Single dataset.",
                "selected": True,
            }
        ],
        "dataset_role_summary": {
            "strategy": "rule",
            "ambiguous": False,
            "selected_primary_table": "roads.csv",
            "selection_score_gap": None,
            "role_fallback_eligible": False,
        },
    }
    base.update(overrides)
    return base


def test_standard_high_confidence_case_does_not_trigger_fallback():
    decision = should_use_llm_fallback(make_rule_analysis(), confidence_threshold=0.72)

    assert decision.should_use_fallback is False
    assert decision.reasons == []


def test_low_confidence_nonstandard_columns_trigger_fallback():
    rule_analysis = make_rule_analysis(
        filename="custom_links.csv",
        task_type="unknown",
        confidence=0.28,
        columns=["lkid", "vol", "spd", "len_km"],
        micro_mapping={},
        macro_mapping={},
        column_mapping={},
        macro_has_required=False,
        evidence=["No clear task type indicators found"],
    )

    decision = should_use_llm_fallback(rule_analysis, confidence_threshold=0.72)

    assert decision.should_use_fallback is True
    assert FallbackReason.TASK_TYPE_UNKNOWN in decision.reasons
    assert FallbackReason.INSUFFICIENT_COLUMN_MAPPING in decision.reasons
    assert FallbackReason.NONSTANDARD_COLUMN_NAMES in decision.reasons

    llm_payload = {
        "task_type": "macro_emission",
        "confidence": 0.81,
        "column_mapping": {
            "link_id": "lkid",
            "traffic_flow_vph": "vol",
            "avg_speed_kph": "spd",
            "link_length_km": "len_km",
        },
        "reasoning_summary": "vol, spd, and len_km look like traffic flow, speed, and link length abbreviations.",
        "evidence": ["vol", "spd", "len_km"],
    }
    parsed = parse_llm_file_analysis_result(llm_payload, rule_analysis)
    merged = merge_rule_and_fallback_analysis(rule_analysis, parsed)

    assert merged.used_fallback is True
    assert merged.analysis["task_type"] == "macro_emission"
    assert merged.analysis["column_mapping"]["vol"] == "traffic_flow_vph"
    assert merged.analysis["column_mapping"]["spd"] == "avg_speed_kph"


def test_fallback_merge_preserves_reliable_rule_mappings():
    rule_analysis = make_rule_analysis(
        confidence=0.56,
        columns=["id", "vol", "spd", "len_km"],
        macro_mapping={"spd": "avg_speed_kph"},
        column_mapping={"spd": "avg_speed_kph"},
        macro_has_required=False,
        evidence=["Only speed was mapped reliably by rules"],
    )
    llm_payload = {
        "task_type": "macro_emission",
        "confidence": 0.77,
        "column_mapping": {
            "link_id": "id",
            "traffic_flow_vph": "vol",
            "avg_speed_kph": "spd",
            "link_length_km": "len_km",
        },
        "reasoning_summary": "The abbreviations id, vol, spd, len_km match standard road-link fields.",
    }

    parsed = parse_llm_file_analysis_result(llm_payload, rule_analysis)
    merged = merge_rule_and_fallback_analysis(rule_analysis, parsed)

    assert merged.used_fallback is True
    assert merged.merge_strategy == "fallback_merge"
    assert merged.analysis["column_mapping"]["spd"] == "avg_speed_kph"
    assert merged.analysis["column_mapping"]["id"] == "link_id"
    assert merged.analysis["column_mapping"]["len_km"] == "link_length_km"


def test_fallback_invalid_result_does_not_override_rule_result():
    rule_analysis = make_rule_analysis(
        task_type="unknown",
        confidence=0.31,
        columns=["lkid", "vol", "spd"],
        macro_mapping={},
        column_mapping={},
        macro_has_required=False,
    )
    invalid_payload = {
        "task_type": "macro_emission",
        "confidence": 0.82,
        "column_mapping": {
            "imaginary_field": "vol",
        },
    }

    try:
        parse_llm_file_analysis_result(invalid_payload, rule_analysis)
    except ValueError as exc:
        assert "Unsupported canonical field" in str(exc)
    else:
        raise AssertionError("Invalid fallback payload should be rejected.")


def test_zip_gis_candidate_table_selection_is_supported():
    rule_analysis = make_rule_analysis(
        filename="network_bundle.zip",
        format="zip_tabular",
        task_type="unknown",
        confidence=0.35,
        columns=["link", "vol", "spd"],
        macro_mapping={},
        column_mapping={},
        macro_has_required=False,
        zip_contents=["roads.csv", "trajectories.csv", "notes.txt"],
        candidate_tables=["roads.csv", "trajectories.csv"],
        selected_primary_table="roads.csv",
        dataset_roles=[
            {
                "dataset_name": "roads.csv",
                "role": "primary_analysis",
                "format": "csv",
                "task_type": "macro_emission",
                "confidence": 0.55,
                "selection_score": 0.71,
                "reason": "Close call with trajectories.csv.",
                "selected": True,
            },
            {
                "dataset_name": "trajectories.csv",
                "role": "trajectory_candidate",
                "format": "csv",
                "task_type": "micro_emission",
                "confidence": 0.54,
                "selection_score": 0.66,
                "reason": "Close call with roads.csv.",
                "selected": False,
            },
        ],
        dataset_role_summary={
            "strategy": "rule",
            "ambiguous": True,
            "selected_primary_table": "roads.csv",
            "selection_score_gap": 0.05,
            "role_fallback_eligible": True,
        },
    )

    decision = should_use_llm_fallback(rule_analysis, confidence_threshold=0.72)
    assert decision.should_use_fallback is True
    assert FallbackReason.ZIP_GIS_STRUCTURE_COMPLEX in decision.reasons

    llm_payload = {
        "task_type": "macro_emission",
        "confidence": 0.74,
        "column_mapping": {
            "link_id": "link",
            "traffic_flow_vph": "vol",
            "avg_speed_kph": "spd",
        },
        "selected_primary_table": "trajectories.csv",
        "reasoning_summary": "The ZIP likely contains multiple candidate tables; trajectories.csv is the better primary table.",
    }

    parsed = parse_llm_file_analysis_result(llm_payload, rule_analysis)
    merged = merge_rule_and_fallback_analysis(rule_analysis, parsed)

    assert merged.used_fallback is True
    assert merged.analysis["selected_primary_table"] == "trajectories.csv"


def test_multi_dataset_rule_assignment_skips_role_fallback_when_not_ambiguous():
    rule_analysis = make_rule_analysis(
        filename="network_bundle.zip",
        format="zip_multi_dataset",
        task_type="macro_emission",
        confidence=0.79,
        columns=["link_id", "flow", "speed", "length"],
        candidate_tables=["roads.csv", "trajectories.csv"],
        zip_contents=["roads.csv", "trajectories.csv", "README.txt"],
        dataset_roles=[
            {
                "dataset_name": "roads.csv",
                "role": "primary_analysis",
                "format": "csv",
                "task_type": "macro_emission",
                "confidence": 0.79,
                "selection_score": 1.12,
                "reason": "Required fields were complete.",
                "selected": True,
            },
            {
                "dataset_name": "trajectories.csv",
                "role": "trajectory_candidate",
                "format": "csv",
                "task_type": "micro_emission",
                "confidence": 0.61,
                "selection_score": 0.74,
                "reason": "Trajectory-like support table.",
                "selected": False,
            },
        ],
        dataset_role_summary={
            "strategy": "rule",
            "ambiguous": False,
            "selected_primary_table": "roads.csv",
            "selection_score_gap": 0.38,
            "role_fallback_eligible": False,
        },
    )

    decision = should_use_llm_fallback(rule_analysis, confidence_threshold=0.72)

    assert FallbackReason.ZIP_GIS_STRUCTURE_COMPLEX not in decision.reasons
