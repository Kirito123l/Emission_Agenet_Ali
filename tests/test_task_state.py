"""Tests for the state orchestration data structures."""

from __future__ import annotations

import json

import pytest

from core.artifact_memory import ArtifactMemoryState, ArtifactType, build_artifact_record
from core.geometry_recovery import (
    GeometryRecoveryContext,
    SupportingSpatialInput,
)
from core.file_relationship_resolution import (
    FileRelationshipDecision,
    FileRelationshipFileSummary,
    FileRelationshipTransitionPlan,
    FileRelationshipType,
)
from core.input_completion import (
    InputCompletionDecision,
    InputCompletionDecisionType,
    InputCompletionOption,
    InputCompletionOptionType,
    InputCompletionReasonCode,
    InputCompletionRequest,
)
from core.intent_resolution import (
    DeliverableIntentType,
    IntentResolutionApplicationPlan,
    IntentResolutionDecision,
    ProgressIntentType,
)
from core.parameter_negotiation import (
    NegotiationCandidate,
    NegotiationDecisionType,
    ParameterNegotiationDecision,
    ParameterNegotiationRequest,
)
from core.plan import ExecutionPlan, PlanStep, PlanStepStatus
from core.plan_repair import PlanRepairDecision, PlanRepairPatch, RepairActionType, RepairTriggerType
from core.residual_reentry import RecoveredWorkflowReentryContext, ResidualReentryTarget
from core.supplemental_merge import SupplementalMergePlan, SupplementalMergeResult
from core.summary_delivery import (
    SummaryDeliveryDecision,
    SummaryDeliveryPlan,
    SummaryDeliveryRequest,
    SummaryDeliveryResult,
    SummaryDeliveryType,
)
from core.task_state import ContinuationDecision, FileContext, ParamStatus, TaskStage, TaskState
from core.workflow_templates import TemplateRecommendation, TemplateSelectionResult, WorkflowTemplate, WorkflowTemplateStep


def test_initialize_without_file():
    state = TaskState.initialize(
        user_message="hello",
        file_path=None,
        memory_dict={},
        session_id="session-1",
    )

    assert state.stage == TaskStage.INPUT_RECEIVED
    assert state.file_context.has_file is False
    assert state.file_context.file_path is None


def test_initialize_with_file(tmp_path):
    file_path = tmp_path / "input.csv"
    state = TaskState.initialize(
        user_message="analyze this file",
        file_path=str(file_path),
        memory_dict={},
        session_id="session-1",
    )

    assert state.stage == TaskStage.INPUT_RECEIVED
    assert state.file_context.has_file is True
    assert state.file_context.file_path == str(file_path)


def test_initialize_with_memory(tmp_path):
    active_file = tmp_path / "cached.csv"
    memory_dict = {
        "recent_vehicle": "Passenger Car",
        "recent_pollutants": ["CO2", "NOx"],
        "recent_year": 2022,
        "active_file": str(active_file),
        "file_analysis": {
            "file_path": str(active_file),
            "task_type": "micro_emission",
            "confidence": 0.92,
            "columns": ["time", "speed"],
            "row_count": 12,
            "sample_rows": [{"time": 0, "speed": 10}],
            "micro_mapping": {"speed": "speed_kph"},
            "macro_mapping": {},
            "micro_has_required": True,
            "macro_has_required": False,
        },
    }

    state = TaskState.initialize(
        user_message="continue",
        file_path=None,
        memory_dict=memory_dict,
        session_id="session-1",
    )

    assert state.parameters["vehicle_type"].status == ParamStatus.OK
    assert state.parameters["vehicle_type"].normalized == "Passenger Car"
    assert state.parameters["pollutants"].normalized == "CO2, NOx"
    assert state.parameters["model_year"].normalized == "2022"
    assert state.file_context.has_file is True
    assert state.file_context.file_path == str(active_file)
    assert state.file_context.grounded is True
    assert state.file_context.task_type == "micro_emission"


def test_valid_transitions():
    state = TaskState()

    state.transition(TaskStage.GROUNDED)
    assert state.stage == TaskStage.GROUNDED

    state.transition(TaskStage.EXECUTING)
    assert state.stage == TaskStage.EXECUTING

    state.transition(TaskStage.DONE)
    assert state.stage == TaskStage.DONE


def test_invalid_transition_raises():
    state = TaskState()

    with pytest.raises(ValueError, match="Invalid transition"):
        state.transition(TaskStage.EXECUTING)


@pytest.mark.parametrize(
    "terminal_stage",
    [
        TaskStage.DONE,
        TaskStage.NEEDS_CLARIFICATION,
        TaskStage.NEEDS_PARAMETER_CONFIRMATION,
        TaskStage.NEEDS_INPUT_COMPLETION,
    ],
)
def test_should_stop_at_terminal(terminal_stage):
    state = TaskState(stage=terminal_stage)

    assert state.is_terminal() is True
    assert state.should_stop() is True


def test_should_stop_at_max_steps():
    state = TaskState()
    state.control.max_steps = 2
    state.control.steps_taken = 2

    assert state.should_stop() is True


def test_to_dict_serializable():
    state = TaskState(
        file_context=FileContext(has_file=True, file_path="/tmp/input.csv"),
    )
    state.parameters["vehicle_type"] = state.parameters.get(
        "vehicle_type",
        None,
    ) or TaskState.initialize(
        user_message="hello",
        file_path=None,
        memory_dict={"recent_vehicle": "Passenger Car"},
        session_id="session-1",
    ).parameters["vehicle_type"]

    payload = state.to_dict()

    json.dumps(payload)
    assert payload["stage"] == "INPUT_RECEIVED"
    assert payload["file_context"]["file_path"] == "/tmp/input.csv"


def test_parameter_lock_observability_serializes():
    state = TaskState.initialize(
        user_message="继续",
        file_path=None,
        memory_dict={},
        session_id="session-1",
    )
    state.apply_parameter_lock(
        parameter_name="vehicle_type",
        normalized_value="Passenger Car",
        raw_value="飞机",
        request_id="neg-1",
    )
    state.set_latest_parameter_negotiation_decision(
        ParameterNegotiationDecision(
            parameter_name="vehicle_type",
            decision_type=NegotiationDecisionType.CONFIRMED,
            user_reply="1",
            selected_index=1,
            selected_value="Passenger Car",
            request_id="neg-1",
            selected_display_label="乘用车 (Passenger Car)",
        )
    )

    payload = state.to_dict()

    assert payload["parameter_locks"]["vehicle_type"]["locked"] is True
    assert payload["parameter_locks"]["vehicle_type"]["normalized"] == "Passenger Car"
    assert payload["latest_confirmed_parameter"]["selected_value"] == "Passenger Car"


def test_intent_resolution_observability_serializes():
    state = TaskState.initialize(
        user_message="帮我可视化一下",
        file_path=None,
        memory_dict={},
        session_id="session-1",
    )
    state.set_latest_intent_resolution_decision(
        IntentResolutionDecision(
            deliverable_intent=DeliverableIntentType.CHART_OR_RANKED_SUMMARY,
            progress_intent=ProgressIntentType.SHIFT_OUTPUT_MODE,
            confidence=0.88,
            reason="Visualization was requested without safe geometry support.",
            current_task_relevance=0.91,
            should_bias_existing_action=True,
            should_preserve_residual_workflow=True,
            should_trigger_clarification=False,
            user_utterance_summary="帮我可视化一下",
        )
    )
    state.set_latest_intent_resolution_plan(
        IntentResolutionApplicationPlan(
            deliverable_intent=DeliverableIntentType.CHART_OR_RANKED_SUMMARY,
            progress_intent=ProgressIntentType.SHIFT_OUTPUT_MODE,
            bias_existing_action=True,
            bias_followup_suggestions=True,
            preferred_artifact_kinds=["chart", "summary"],
            deprioritized_action_ids=["render_emission_map"],
            user_visible_summary="当前更适合用排序图和摘要表展示结果。",
        )
    )
    state.set_artifact_memory_state(
        ArtifactMemoryState().append(
            [
                build_artifact_record(
                    artifact_type=ArtifactType.DETAILED_CSV,
                    delivery_turn_index=2,
                    source_tool_name="calculate_macro_emission",
                    summary="已提供可下载的详细结果文件。",
                    related_task_type="macro_emission",
                )
            ]
        )
    )

    payload = state.to_dict()

    assert payload["latest_intent_resolution_decision"]["deliverable_intent"] == "chart_or_ranked_summary"
    assert payload["latest_intent_resolution_plan"]["progress_intent"] == "shift_output_mode"
    assert payload["artifact_memory_summary"]["artifact_count"] == 1
    assert payload["latest_artifact_by_type"]["detailed_csv"]["artifact_type"] == "detailed_csv"


def test_summary_delivery_observability_serializes():
    state = TaskState.initialize(
        user_message="给我前5高排放路段摘要表",
        file_path=None,
        memory_dict={},
        session_id="session-1",
    )
    state.set_latest_summary_delivery_plan(
        SummaryDeliveryPlan(
            request=SummaryDeliveryRequest(
                delivery_type=SummaryDeliveryType.TOPK_SUMMARY_TABLE,
                source_result_type="emission",
                ranking_metric="CO2_kg_h",
                topk=5,
                artifact_family="ranked_summary",
                related_task_type="macro_emission",
                delivery_reason="The user explicitly requested a Top-K summary table.",
            ),
            decision=SummaryDeliveryDecision(
                selected_delivery_type=SummaryDeliveryType.TOPK_SUMMARY_TABLE,
                confidence=0.92,
                reason="A bounded Top-K table delivery is the best fit for the current request.",
                ranking_metric="CO2_kg_h",
                topk=5,
                should_generate_downloadable_table=True,
                should_generate_chart=False,
                should_generate_text_summary=True,
            ),
            source_result_type="emission",
            source_tool_name="calculate_macro_emission",
            source_label="baseline",
            artifact_family="ranked_summary",
            preconditions=["emission_result"],
            plan_status="planned",
            user_visible_summary="已将当前请求承接为 Top-K 摘要表交付。",
        )
    )
    state.set_latest_summary_delivery_result(
        SummaryDeliveryResult(
            success=True,
            artifact_records=[
                build_artifact_record(
                    artifact_type=ArtifactType.TOPK_SUMMARY_TABLE,
                    delivery_turn_index=3,
                    source_tool_name="summary_delivery_surface",
                    source_action_id="download_topk_summary",
                    summary="已提供前 5 高排放路段摘要表。",
                    related_task_type="macro_emission",
                )
            ],
            table_preview={
                "type": "topk_summary_table",
                "summary": {"ranking_metric": "CO2_kg_h", "topk": 5},
            },
            summary_text="已按 CO2 生成前 5 路段摘要表。",
            delivery_summary="已交付 Top-K 摘要表。",
            download_file={"path": "/tmp/top5_co2_summary.csv", "filename": "top5_co2_summary.csv"},
        )
    )

    payload = state.to_dict()

    assert payload["latest_summary_delivery_plan"]["decision"]["selected_delivery_type"] == "topk_summary_table"
    assert payload["latest_summary_delivery_result"]["success"] is True
    assert payload["latest_summary_delivery_result"]["artifact_records"][0]["artifact_type"] == "topk_summary_table"


def test_negotiation_request_observability_serializes():
    state = TaskState.initialize(
        user_message="继续",
        file_path=None,
        memory_dict={},
        session_id="session-1",
    )
    state.set_active_parameter_negotiation(
        ParameterNegotiationRequest.create(
            parameter_name="vehicle_type",
            raw_value="飞机",
            trigger_reason="low_confidence_llm_match(confidence=0.62)",
            tool_name="query_emission_factors",
            confidence=0.62,
            strategy="llm",
            candidates=[
                NegotiationCandidate(
                    index=1,
                    normalized_value="Passenger Car",
                    display_label="乘用车 (Passenger Car)",
                    confidence=0.62,
                    strategy="llm",
                ),
            ],
        )
    )

    payload = state.to_dict()

    assert payload["has_active_parameter_negotiation"] is True
    assert payload["active_parameter_negotiation"]["parameter_name"] == "vehicle_type"
    assert payload["active_parameter_negotiation"]["candidates"][0]["normalized_value"] == "Passenger Car"


def test_input_completion_observability_serializes():
    state = TaskState.initialize(
        user_message="继续",
        file_path=None,
        memory_dict={},
        session_id="session-1",
    )
    state.set_active_input_completion(
        InputCompletionRequest.create(
            action_id="run_macro_emission",
            reason_code=InputCompletionReasonCode.MISSING_REQUIRED_FIELD,
            reason_summary="缺少 traffic_flow_vph。",
            missing_requirements=["traffic_flow_vph"],
            target_field="traffic_flow_vph",
            options=[
                InputCompletionOption(
                    option_id="traffic_flow_vph_uniform_value",
                    option_type=InputCompletionOptionType.PROVIDE_UNIFORM_VALUE,
                    label="统一流量值",
                    description="为所有记录设置统一流量值。",
                )
            ],
        )
    )
    state.apply_input_completion_override(
        key="traffic_flow_vph",
        override={
            "mode": "uniform_scalar",
            "value": 1500,
            "source": "input_completion",
        },
    )
    state.set_latest_input_completion_decision(
        InputCompletionDecision(
            request_id="completion-1",
            decision_type=InputCompletionDecisionType.SELECTED_OPTION,
            user_reply="1500",
            selected_option_id="traffic_flow_vph_uniform_value",
            structured_payload={"mode": "uniform_scalar", "value": 1500},
            source="numeric_reply",
        )
    )

    payload = state.to_dict()

    assert payload["has_active_input_completion"] is True
    assert payload["active_input_completion"]["action_id"] == "run_macro_emission"
    assert payload["input_completion_overrides"]["traffic_flow_vph"]["value"] == 1500
    assert payload["latest_input_completion_decision"]["structured_payload"]["value"] == 1500


def test_file_relationship_observability_serializes():
    state = TaskState.initialize(
        user_message="用这个新的算",
        file_path="/tmp/roads_new.csv",
        memory_dict={},
        session_id="session-1",
    )
    state.set_latest_file_relationship_decision(
        FileRelationshipDecision(
            relationship_type=FileRelationshipType.REPLACE_PRIMARY_FILE,
            confidence=0.93,
            reason="The new upload replaced the old primary file.",
            primary_file_candidate="/tmp/roads_new.csv",
            affected_contexts=["primary_file", "pending_completion"],
            should_supersede_pending_completion=True,
            should_reset_recovery_context=True,
            user_utterance_summary="用这个新的算",
        )
    )
    state.set_latest_file_relationship_transition(
        FileRelationshipTransitionPlan(
            relationship_type=FileRelationshipType.REPLACE_PRIMARY_FILE,
            replace_primary_file=True,
            supersede_pending_completion=True,
            clear_input_completion_overrides=True,
            reset_geometry_recovery_context=True,
            new_primary_file_candidate="/tmp/roads_new.csv",
            user_visible_summary="已将新上传文件视为当前任务的主输入，并替换先前文件。",
        )
    )
    state.set_pending_file_relationship_upload(
        FileRelationshipFileSummary.from_path("/tmp/roads_new.csv", role_candidate="new_upload")
    )
    state.set_attached_supporting_file(
        FileRelationshipFileSummary.from_path("/tmp/roads.geojson", role_candidate="supporting_file")
    )
    state.set_awaiting_file_relationship_clarification(True)

    payload = state.to_dict()

    assert payload["incoming_file_path"] == "/tmp/roads_new.csv"
    assert payload["latest_file_relationship_decision"]["relationship_type"] == "replace_primary_file"
    assert payload["latest_file_relationship_transition"]["replace_primary_file"] is True
    assert payload["pending_file_relationship_upload"]["file_path"] == "/tmp/roads_new.csv"
    assert payload["attached_supporting_file"]["file_path"] == "/tmp/roads.geojson"
    assert payload["awaiting_file_relationship_clarification"] is True


def test_supplemental_merge_observability_serializes():
    state = TaskState.initialize(
        user_message="把这一列加上",
        file_path="/tmp/flow.csv",
        memory_dict={},
        session_id="session-1",
    )
    state.set_latest_supplemental_merge_plan(
        SupplementalMergePlan.from_dict(
            {
                "primary_file_ref": "/tmp/roads.csv",
                "supplemental_file_ref": "/tmp/flow.csv",
                "merge_keys": [
                    {
                        "primary_column": "segment_id",
                        "supplemental_column": "segment_id",
                        "confidence": 0.95,
                        "reason": "Same identifier column name.",
                    }
                ],
                "candidate_columns_to_import": ["traffic_flow_vph"],
                "canonical_targets": {"traffic_flow_vph": "traffic_flow_vph"},
                "plan_status": "ready",
            }
        )
    )
    state.set_latest_supplemental_merge_result(
        SupplementalMergeResult.from_dict(
            {
                "success": True,
                "merged_columns": ["traffic_flow_vph"],
                "materialized_primary_file_ref": "/tmp/roads__merged.csv",
                "updated_readiness_summary": {
                    "action_id": "run_macro_emission",
                    "after_status": "ready",
                },
            }
        )
    )

    payload = state.to_dict()

    assert payload["latest_supplemental_merge_plan"]["plan_status"] == "ready"
    assert payload["latest_supplemental_merge_plan"]["merge_keys"][0]["primary_column"] == "segment_id"
    assert payload["latest_supplemental_merge_result"]["success"] is True
    assert payload["latest_supplemental_merge_result"]["merged_columns"] == ["traffic_flow_vph"]


def test_update_file_context():
    state = TaskState()
    analysis_dict = {
        "file_path": "/tmp/sample.csv",
        "task_type": "micro_emission",
        "confidence": 0.95,
        "columns": ["time", "speed", "acceleration"],
        "row_count": 24,
        "sample_rows": [{"time": 0, "speed": 12.3}],
        "micro_mapping": {"speed": "speed_kph", "time": "time"},
        "macro_mapping": {"flow": "traffic_flow_vph"},
        "micro_has_required": True,
        "macro_has_required": False,
        "evidence": ["speed column matched", "time column matched"],
    }

    state.update_file_context(analysis_dict)

    assert state.file_context.has_file is True
    assert state.file_context.file_path == "/tmp/sample.csv"
    assert state.file_context.grounded is True
    assert state.file_context.task_type == "micro_emission"
    assert state.file_context.confidence == 0.95
    assert state.file_context.columns == ["time", "speed", "acceleration"]
    assert state.file_context.row_count == 24
    assert state.file_context.sample_rows == [{"time": 0, "speed": 12.3}]
    assert state.file_context.micro_mapping == {"speed": "speed_kph", "time": "time"}
    assert state.file_context.macro_mapping == {"flow": "traffic_flow_vph"}
    assert state.file_context.micro_has_required is True
    assert state.file_context.macro_has_required is False
    assert state.file_context.column_mapping == {"speed": "speed_kph", "time": "time"}
    assert state.file_context.evidence == ["speed column matched", "time column matched"]


def test_geometry_recovery_observability_serializes():
    state = TaskState.initialize(
        user_message="继续",
        file_path=None,
        memory_dict={},
        session_id="session-1",
    )
    supporting = SupportingSpatialInput(
        file_ref="/tmp/roads.geojson",
        file_name="roads.geojson",
        file_type="geojson",
        source="input_completion_upload",
        geometry_capability_summary={
            "has_geometry_support": True,
            "support_modes": ["spatial_metadata"],
            "geometry_types": ["LineString"],
        },
        dataset_roles=[{"dataset_name": "roads.geojson", "role": "supporting_spatial_dataset"}],
        spatial_metadata={"geometry_types": ["LineString"]},
    )
    state.set_supporting_spatial_input(supporting)
    state.set_geometry_recovery_context(
        GeometryRecoveryContext(
            primary_file_ref="/tmp/roads.csv",
            supporting_spatial_input=supporting,
            target_action_id="render_emission_map",
            target_task_type="macro_emission",
            residual_plan_summary="Next: s2 -> render_spatial_map",
            recovery_status="resumable",
            resume_hint="Resume render_emission_map on the next turn.",
            upstream_recompute_recommendation="Continue map rendering on the next turn.",
        )
    )
    state.set_geometry_readiness_refresh_result(
        {
            "action_id": "render_emission_map",
            "before_status": "repairable",
            "after_status": "ready",
            "status_delta": "repairable->ready",
        }
    )
    state.set_residual_reentry_context(
        RecoveredWorkflowReentryContext(
            reentry_target=ResidualReentryTarget(
                target_action_id="render_emission_map",
                target_tool_name="render_spatial_map",
                target_step_id="s2",
                source="geometry_recovery",
                reason="Recovered geometry action became the primary re-entry target.",
                priority=100,
                display_name="可视化排放空间分布",
                residual_plan_relationship="aligned_with_next_pending_step",
                matches_next_pending_step=True,
            ),
            residual_plan_summary="Next: s2 -> render_spatial_map",
            geometry_recovery_context=state.geometry_recovery_context,
            readiness_refresh_result=state.geometry_readiness_refresh_result,
            reentry_status="target_set",
            reentry_guidance_summary="Primary re-entry target: render_emission_map -> render_spatial_map",
        )
    )
    state.set_reentry_bias_applied(True)

    payload = state.to_dict()

    assert payload["supporting_spatial_input_summary"]["file_name"] == "roads.geojson"
    assert payload["supporting_spatial_input_summary"]["has_geometry_support"] is True
    assert payload["geometry_recovery_context_summary"]["target_action_id"] == "render_emission_map"
    assert payload["geometry_recovery_status"] == "resumable"
    assert payload["geometry_readiness_refresh_result"]["after_status"] == "ready"
    assert payload["reentry_target_summary"]["target_action_id"] == "render_emission_map"
    assert payload["reentry_status"] == "target_set"
    assert payload["reentry_source"] == "geometry_recovery"
    assert payload["reentry_bias_applied"] is True


def test_plan_serialization_roundtrip():
    state = TaskState.initialize(
        user_message="继续",
        file_path=None,
        memory_dict={},
        session_id="session-1",
    )
    state.set_plan(
        ExecutionPlan(
            goal="Run emission then map rendering",
            steps=[
                PlanStep(step_id="s1", tool_name="calculate_macro_emission"),
                PlanStep(step_id="s2", tool_name="render_spatial_map", depends_on=["emission"]),
            ],
        )
    )

    payload = state.to_dict()

    json.dumps(payload)
    assert payload["plan"]["goal"] == "Run emission then map rendering"
    assert payload["plan"]["steps"][1]["depends_on"] == ["emission"]
    assert payload["next_planned_step"]["step_id"] == "s1"


def test_plan_step_execution_observability_serializes():
    state = TaskState.initialize(
        user_message="继续",
        file_path=None,
        memory_dict={},
        session_id="session-1",
    )
    state.set_plan(
        ExecutionPlan(
            goal="Run emission then dispersion",
            steps=[PlanStep(step_id="s1", tool_name="calculate_macro_emission")],
        )
    )
    state.update_plan_step_status(
        step_id="s1",
        status=PlanStepStatus.BLOCKED,
        note="Missing prerequisite results: ['emission'].",
        reconciliation_note="Execution blocked before calculate_macro_emission.",
        blocked_reason="deterministic gate blocked execution",
    )

    payload = state.to_dict()

    assert payload["plan"]["steps"][0]["status"] == "blocked"
    assert payload["plan"]["steps"][0]["blocked_reason"] == "deterministic gate blocked execution"
    assert payload["plan"]["steps"][0]["reconciliation_notes"] == [
        "Execution blocked before calculate_macro_emission."
    ]


def test_repaired_plan_serialization_exposes_repair_history_and_step_annotations():
    state = TaskState.initialize(
        user_message="继续",
        file_path=None,
        memory_dict={},
        session_id="session-1",
    )
    state.set_plan(
        ExecutionPlan(
            goal="Repair residual plan",
            steps=[
                PlanStep(
                    step_id="s1",
                    tool_name="render_spatial_map",
                    status=PlanStepStatus.SKIPPED,
                    repair_action="DROP_BLOCKED_STEP",
                    repair_notes=["Skipped by bounded repair."],
                ),
                PlanStep(
                    step_id="repair_s1",
                    tool_name="calculate_dispersion",
                    status=PlanStepStatus.READY,
                    repair_action="APPEND_RECOVERY_STEP",
                    repair_source_step_id="s1",
                    repair_notes=["Appended recovery step."],
                ),
            ],
            repair_notes=["Applied bounded residual repair."],
        )
    )
    state.record_plan_repair(
        PlanRepairDecision(
            trigger_type=RepairTriggerType.DEPENDENCY_BLOCKED,
            trigger_reason="Missing hotspot result.",
            action_type=RepairActionType.APPEND_RECOVERY_STEP,
            target_step_id="s1",
            affected_step_ids=["s1", "repair_s1"],
            planner_notes="Append dispersion recovery step.",
            is_applicable=True,
            patch=PlanRepairPatch(
                append_steps=[PlanStep(step_id="repair_s1", tool_name="calculate_dispersion")]
            ),
            repaired_plan_snapshot=state.plan.to_dict() if state.plan else None,
        )
    )

    payload = state.to_dict()

    assert payload["plan"]["repair_notes"] == ["Applied bounded residual repair."]
    assert payload["plan"]["steps"][0]["repair_action"] == "DROP_BLOCKED_STEP"
    assert payload["plan"]["steps"][1]["repair_source_step_id"] == "s1"
    assert payload["next_planned_step"]["step_id"] == "repair_s1"
    assert payload["repair_history"][0]["action_type"] == "APPEND_RECOVERY_STEP"


def test_residual_plan_observability_after_repair_marks_next_pending_step():
    state = TaskState.initialize(
        user_message="继续",
        file_path=None,
        memory_dict={},
        session_id="session-1",
    )
    state.set_plan(
        ExecutionPlan(
            goal="Residual workflow",
            steps=[
                PlanStep(step_id="s1", tool_name="calculate_macro_emission", status=PlanStepStatus.COMPLETED),
                PlanStep(step_id="s2", tool_name="analyze_hotspots", status=PlanStepStatus.SKIPPED),
                PlanStep(step_id="repair_s1", tool_name="calculate_dispersion", status=PlanStepStatus.READY),
            ],
            repair_notes=["Blocked hotspot step was replaced."],
        )
    )

    payload = state.to_dict()

    assert payload["next_planned_step"]["tool_name"] == "calculate_dispersion"
    assert payload["plan"]["steps"][1]["status"] == "skipped"
    assert payload["plan"]["repair_notes"] == ["Blocked hotspot step was replaced."]


def test_continuation_observability_serializes_latest_repair_and_residual_summary():
    state = TaskState.initialize(
        user_message="继续",
        file_path=None,
        memory_dict={},
        session_id="session-1",
    )
    state.set_plan(
        ExecutionPlan(
            goal="Residual workflow",
            steps=[
                PlanStep(step_id="s1", tool_name="calculate_macro_emission", status=PlanStepStatus.COMPLETED),
                PlanStep(step_id="repair_s1", tool_name="calculate_dispersion", status=PlanStepStatus.READY),
            ],
            repair_notes=["Replaced blocked hotspot render with dispersion."],
        )
    )
    state.record_plan_repair(
        PlanRepairDecision(
            trigger_type=RepairTriggerType.DEPENDENCY_BLOCKED,
            trigger_reason="Missing hotspot result.",
            action_type=RepairActionType.REPLACE_STEP,
            target_step_id="s2",
            affected_step_ids=["s2", "repair_s1"],
            planner_notes="Replace blocked hotspot render with dispersion.",
            is_applicable=True,
            patch=PlanRepairPatch(
                replacement_step=PlanStep(step_id="repair_s1", tool_name="calculate_dispersion")
            ),
        )
    )
    state.set_continuation_decision(
        ContinuationDecision(
            residual_plan_exists=True,
            continuation_ready=True,
            should_continue=True,
            prompt_variant="balanced_repair_aware",
            signal="explicit_continuation",
            reason="explicit continuation cue '继续' matched the residual workflow",
            next_step_id="repair_s1",
            next_tool_name="calculate_dispersion",
            latest_repair_summary="REPLACE_STEP: Replace blocked hotspot render with dispersion.",
            residual_plan_summary="Goal: Residual workflow | Next: repair_s1 -> calculate_dispersion [ready]",
        )
    )

    payload = state.to_dict()

    assert payload["continuation_ready"] is True
    assert payload["continuation_reason"] == "explicit continuation cue '继续' matched the residual workflow"
    assert payload["latest_repair_summary"] == "REPLACE_STEP: Replace blocked hotspot render with dispersion."
    assert payload["residual_plan_summary"].startswith("Goal: Residual workflow")
    assert payload["continuation"]["next_tool_name"] == "calculate_dispersion"
    assert payload["continuation"]["prompt_variant"] == "balanced_repair_aware"


def test_live_residual_plan_summary_falls_back_to_plan_when_no_continuation_decision():
    state = TaskState.initialize(
        user_message="继续",
        file_path=None,
        memory_dict={},
        session_id="session-1",
    )
    state.set_plan(
        ExecutionPlan(
            goal="Continue dispersion workflow",
            steps=[
                PlanStep(step_id="s1", tool_name="calculate_macro_emission", status=PlanStepStatus.COMPLETED),
                PlanStep(step_id="s2", tool_name="calculate_dispersion", status=PlanStepStatus.READY),
            ],
        )
    )

    payload = state.to_dict()

    assert payload["continuation_ready"] is False
    assert payload["latest_repair_summary"] is None
    assert "Goal: Continue dispersion workflow" in payload["residual_plan_summary"]
    assert payload["next_planned_step"]["step_id"] == "s2"


def test_workflow_template_observability_serializes_selection_and_recommendations():
    state = TaskState.initialize(
        user_message="分析这个文件",
        file_path=None,
        memory_dict={},
        session_id="session-1",
    )
    selection = TemplateSelectionResult(
        recommended_template_id="macro_spatial_chain",
        recommendations=[
            TemplateRecommendation(
                template_id="macro_spatial_chain",
                confidence=0.84,
                reason="task_type=macro_emission; readiness=complete; spatial context available",
                matched_signals=["macro_task", "file_readiness_complete", "spatial_ready"],
                unmet_requirements=[],
                is_applicable=True,
                priority_rank=1,
            )
        ],
        selection_reason="Selected macro_spatial_chain as the highest-ranked applicable template prior.",
        template_prior_used=True,
        selected_template=WorkflowTemplate(
            template_id="macro_spatial_chain",
            name="Macro Spatial Chain",
            description="Macro emission followed by dispersion, hotspot analysis, and rendering.",
            supported_task_types=["macro_emission"],
            required_file_signals=["macro_task", "spatial_ready"],
            step_skeleton=[
                WorkflowTemplateStep(step_id="t1", tool_name="calculate_macro_emission", produces=["emission"]),
                WorkflowTemplateStep(step_id="t2", tool_name="calculate_dispersion", depends_on=["emission"], produces=["dispersion"]),
            ],
        ),
    )
    state.set_workflow_template_selection(selection)

    payload = state.to_dict()

    assert payload["template_prior_used"] is True
    assert payload["template_selection_reason"].startswith("Selected macro_spatial_chain")
    assert payload["recommended_workflow_templates"][0]["template_id"] == "macro_spatial_chain"
    assert payload["selected_workflow_template"]["template_id"] == "macro_spatial_chain"
