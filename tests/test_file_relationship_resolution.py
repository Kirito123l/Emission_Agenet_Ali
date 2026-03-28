from __future__ import annotations

from core.file_relationship_resolution import (
    FileRelationshipDecision,
    FileRelationshipFileSummary,
    FileRelationshipResolutionContext,
    FileRelationshipTransitionPlan,
    FileRelationshipType,
    build_file_relationship_transition_plan,
    infer_file_relationship_fallback,
    parse_file_relationship_result,
)


def test_parse_file_relationship_result_normalizes_replace_decision():
    context = FileRelationshipResolutionContext(
        current_primary_file=FileRelationshipFileSummary.from_path(
            "/tmp/roads_old.csv",
            role_candidate="current_primary",
        ),
        latest_uploaded_file=FileRelationshipFileSummary.from_path(
            "/tmp/roads_new.csv",
            role_candidate="new_upload",
        ),
        current_task_type="macro_emission",
        has_pending_completion=True,
        has_completion_overrides=True,
        user_message="刚刚发错了，用这个新的算",
    )

    result = parse_file_relationship_result(
        {
            "relationship_type": "replace_primary_file",
            "confidence": 0.92,
            "reason": "The user explicitly replaced the previous file.",
            "should_supersede_pending_completion": True,
            "should_reset_recovery_context": True,
            "affected_contexts": ["primary_file", "pending_completion", "completion_overrides"],
        },
        context,
    )

    assert result.is_resolved is True
    assert result.decision is not None
    assert result.decision.relationship_type == FileRelationshipType.REPLACE_PRIMARY_FILE
    assert result.decision.primary_file_candidate == "/tmp/roads_new.csv"
    assert result.decision.should_supersede_pending_completion is True
    assert result.decision.user_utterance_summary == "刚刚发错了，用这个新的算"


def test_replace_transition_plan_precisely_resets_primary_bound_state():
    context = FileRelationshipResolutionContext(
        current_primary_file=FileRelationshipFileSummary.from_path("/tmp/roads_old.csv"),
        latest_uploaded_file=FileRelationshipFileSummary.from_path("/tmp/roads_new.csv"),
        current_task_type="macro_emission",
        has_pending_completion=True,
        has_geometry_recovery=True,
        has_residual_reentry=True,
        has_residual_workflow=True,
        has_completion_overrides=True,
        user_message="我重新上传一个路网文件，用这个新的计算",
    )
    decision = FileRelationshipDecision(
        relationship_type=FileRelationshipType.REPLACE_PRIMARY_FILE,
        confidence=0.9,
        reason="The new upload supersedes the earlier primary file.",
        primary_file_candidate="/tmp/roads_new.csv",
        affected_contexts=[
            "primary_file",
            "pending_completion",
            "completion_overrides",
            "geometry_recovery",
            "residual_workflow",
        ],
        should_supersede_pending_completion=True,
        should_reset_recovery_context=True,
        should_preserve_residual_workflow=False,
        user_utterance_summary="我重新上传一个路网文件，用这个新的计算",
    )

    plan = build_file_relationship_transition_plan(decision, context)

    assert plan.relationship_type == FileRelationshipType.REPLACE_PRIMARY_FILE
    assert plan.replace_primary_file is True
    assert plan.supersede_pending_completion is True
    assert plan.clear_input_completion_overrides is True
    assert plan.reset_geometry_recovery_context is True
    assert plan.clear_residual_reentry_context is True
    assert plan.preserve_residual_workflow is False
    assert plan.new_primary_file_candidate == "/tmp/roads_new.csv"
    assert "locked_parameters" in plan.state_preserved


def test_fallback_prefers_supporting_file_in_geometry_recovery_context():
    context = FileRelationshipResolutionContext(
        current_primary_file=FileRelationshipFileSummary.from_path("/tmp/roads.csv"),
        latest_uploaded_file=FileRelationshipFileSummary(
            file_path="/tmp/roads.geojson",
            file_name="roads.geojson",
            file_type="geojson",
            spatial_metadata={"geometry_types": ["LineString"]},
            role_candidate="new_upload",
        ),
        current_task_type="macro_emission",
        has_pending_completion=True,
        pending_completion_reason_code="missing_geometry",
        has_geometry_recovery=True,
        has_residual_workflow=True,
        user_message="这是配套的 GIS 文件",
    )

    decision = infer_file_relationship_fallback(context)

    assert decision.relationship_type == FileRelationshipType.ATTACH_SUPPORTING_FILE
    assert decision.supporting_file_candidate == "/tmp/roads.geojson"
    assert decision.should_preserve_residual_workflow is True
    assert decision.should_reset_recovery_context is False


def test_fallback_asks_clarify_for_ambiguous_use_this_message():
    context = FileRelationshipResolutionContext(
        current_primary_file=FileRelationshipFileSummary.from_path("/tmp/roads.csv"),
        latest_uploaded_file=FileRelationshipFileSummary.from_path("/tmp/new_file.csv"),
        current_task_type="macro_emission",
        has_residual_workflow=True,
        user_message="用这个吧",
    )

    decision = infer_file_relationship_fallback(context)
    plan = build_file_relationship_transition_plan(decision, context)

    assert decision.relationship_type == FileRelationshipType.ASK_CLARIFY
    assert plan.require_clarification is True
    assert plan.should_halt_after_transition is True
    assert "替换主文件" in (plan.clarification_question or "")


def test_transition_plan_roundtrip_serializes_cleanly():
    plan = FileRelationshipTransitionPlan(
        relationship_type=FileRelationshipType.MERGE_SUPPLEMENTAL_COLUMNS,
        preserve_primary_file=True,
        pending_merge_semantics=True,
        should_halt_after_transition=True,
        supporting_file_candidate="/tmp/supplement.csv",
        user_visible_summary="Recognized merge semantics.",
        affected_contexts=["primary_file", "supplemental_merge"],
        state_preserved=["primary_file", "session_trace"],
    )

    payload = plan.to_dict()
    restored = FileRelationshipTransitionPlan.from_dict(payload)

    assert restored.relationship_type == FileRelationshipType.MERGE_SUPPLEMENTAL_COLUMNS
    assert restored.pending_merge_semantics is True
    assert restored.supporting_file_candidate == "/tmp/supplement.csv"
