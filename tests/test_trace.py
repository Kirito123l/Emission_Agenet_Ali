"""Tests for core.trace module."""

import json
from pathlib import Path

import pytest

from core.trace import Trace, TraceStep, TraceStepType


class TestTraceStep:
    def test_to_dict_excludes_none(self):
        step = TraceStep(
            step_index=0,
            step_type=TraceStepType.FILE_GROUNDING,
            timestamp="2025-01-01T00:00:00",
            stage_before="INPUT_RECEIVED",
        )
        d = step.to_dict()
        assert "stage_after" not in d
        assert "error" not in d
        assert d["step_type"] == "file_grounding"

    def test_to_dict_includes_set_fields(self):
        step = TraceStep(
            step_index=1,
            step_type=TraceStepType.TOOL_EXECUTION,
            timestamp="2025-01-01T00:00:00",
            stage_before="EXECUTING",
            stage_after="DONE",
            action="calculate_macro_emission",
            duration_ms=150.5,
            error=None,
        )
        d = step.to_dict()
        assert d["action"] == "calculate_macro_emission"
        assert d["duration_ms"] == 150.5
        assert "error" not in d


class TestTrace:
    def test_start_creates_with_timestamp(self):
        t = Trace.start(session_id="test-123")
        assert t.session_id == "test-123"
        assert t.start_time is not None
        assert t.steps == []

    def test_record_appends_step(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.FILE_GROUNDING,
            stage_before="INPUT_RECEIVED",
            action="analyze_file",
            confidence=0.88,
        )
        assert len(t.steps) == 1
        assert t.steps[0].step_index == 0
        assert t.steps[0].step_type == TraceStepType.FILE_GROUNDING
        assert t.steps[0].confidence == 0.88

    def test_record_auto_increments_index(self):
        t = Trace.start()
        t.record(step_type=TraceStepType.FILE_GROUNDING, stage_before="INPUT_RECEIVED")
        t.record(step_type=TraceStepType.TOOL_SELECTION, stage_before="GROUNDED")
        t.record(step_type=TraceStepType.TOOL_EXECUTION, stage_before="EXECUTING")
        assert [s.step_index for s in t.steps] == [0, 1, 2]

    def test_finish_sets_end_time_and_duration(self):
        t = Trace.start()
        t.record(step_type=TraceStepType.FILE_GROUNDING, stage_before="INPUT_RECEIVED")
        t.finish(final_stage="DONE")
        assert t.end_time is not None
        assert t.final_stage == "DONE"
        assert t.total_duration_ms is not None
        assert t.total_duration_ms >= 0

    def test_to_dict_serializable(self):
        t = Trace.start(session_id="s1")
        t.record(
            step_type=TraceStepType.TOOL_EXECUTION,
            stage_before="EXECUTING",
            action="calculate_macro_emission",
            output_summary={"success": True},
            duration_ms=200.0,
        )
        t.finish("DONE")
        d = t.to_dict()
        json_str = json.dumps(d)
        assert isinstance(json_str, str)
        assert d["step_count"] == 1
        assert d["final_stage"] == "DONE"

    def test_persist_writes_json_file(self, tmp_path):
        t = Trace.start(session_id="persist-session")
        t.record(
            step_type=TraceStepType.TOOL_EXECUTION,
            stage_before="EXECUTING",
            action="calculate_macro_emission",
            output_summary={"success": True},
        )
        t.finish("DONE")

        persisted_path = Path(t.persist(output_dir=tmp_path))

        assert persisted_path.exists()
        assert persisted_path.name.startswith("trace_persist-session_")

        payload = json.loads(persisted_path.read_text(encoding="utf-8"))
        assert payload["session_id"] == "persist-session"
        assert payload["final_stage"] == "DONE"
        assert payload["step_count"] == 1

    def test_to_user_friendly_file_grounding(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.FILE_GROUNDING,
            stage_before="INPUT_RECEIVED",
            output_summary={"task_type": "macro_emission", "confidence": 0.88},
            confidence=0.88,
        )
        friendly = t.to_user_friendly()
        assert len(friendly) == 1
        assert "macro_emission" in friendly[0]["description"]
        assert friendly[0]["status"] == "success"

    def test_to_user_friendly_tool_execution_success(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.TOOL_EXECUTION,
            stage_before="EXECUTING",
            action="calculate_macro_emission",
            duration_ms=350.0,
        )
        friendly = t.to_user_friendly()
        assert len(friendly) == 1
        assert "350ms" in friendly[0]["description"]
        assert friendly[0]["status"] == "success"

    def test_to_user_friendly_tool_execution_error(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.TOOL_EXECUTION,
            stage_before="EXECUTING",
            action="calculate_micro_emission",
            error="Missing required parameter: vehicle_type",
        )
        friendly = t.to_user_friendly()
        assert len(friendly) == 1
        assert friendly[0]["status"] == "error"

    def test_to_user_friendly_skips_state_transition(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.STATE_TRANSITION,
            stage_before="INPUT_RECEIVED",
            stage_after="GROUNDED",
        )
        friendly = t.to_user_friendly()
        assert len(friendly) == 0

    def test_to_user_friendly_clarification(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.CLARIFICATION,
            stage_before="NEEDS_CLARIFICATION",
            reasoning="Missing pollutant specification",
        )
        friendly = t.to_user_friendly()
        assert len(friendly) == 1
        assert friendly[0]["status"] == "warning"

    def test_to_user_friendly_plan_steps(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.PLAN_CREATED,
            stage_before="INPUT_RECEIVED",
            output_summary={"goal": "Compute emissions", "step_count": 2},
        )
        t.record(
            step_type=TraceStepType.PLAN_VALIDATED,
            stage_before="INPUT_RECEIVED",
            output_summary={"plan_status": "partial"},
            reasoning="Plan is only partially executable.",
        )
        t.record(
            step_type=TraceStepType.PLAN_DEVIATION,
            stage_before="GROUNDED",
            reasoning="Expected calculate_macro_emission but selected render_spatial_map.",
        )
        friendly = t.to_user_friendly()
        assert [item["step_type"] for item in friendly] == [
            "plan_created",
            "plan_validated",
            "plan_deviation",
        ]
        assert friendly[1]["status"] == "warning"

    def test_to_user_friendly_workflow_template_steps(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.WORKFLOW_TEMPLATE_RECOMMENDED,
            stage_before="INPUT_RECEIVED",
            reasoning="Rule-based workflow template recommendations were derived from the grounded file signals.",
        )
        t.record(
            step_type=TraceStepType.WORKFLOW_TEMPLATE_SELECTED,
            stage_before="INPUT_RECEIVED",
            reasoning="Selected macro_spatial_chain as the highest-ranked applicable template prior.",
        )
        t.record(
            step_type=TraceStepType.WORKFLOW_TEMPLATE_INJECTED,
            stage_before="INPUT_RECEIVED",
            reasoning="Prepared workflow template prior macro_spatial_chain for the lightweight planning payload.",
        )
        t.record(
            step_type=TraceStepType.WORKFLOW_TEMPLATE_SKIPPED,
            stage_before="INPUT_RECEIVED",
            reasoning="Residual continuation remained authoritative, so fresh template recommendation was skipped.",
        )

        friendly = t.to_user_friendly()

        assert [item["step_type"] for item in friendly] == [
            "workflow_template_recommended",
            "workflow_template_selected",
            "workflow_template_injected",
            "workflow_template_skipped",
        ]
        assert friendly[0]["status"] == "success"
        assert friendly[-1]["status"] == "warning"

    def test_to_user_friendly_file_relationship_steps(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.FILE_RELATIONSHIP_RESOLUTION_TRIGGERED,
            stage_before="INPUT_RECEIVED",
            reasoning="A new uploaded file entered an active file-bound workflow.",
        )
        t.record(
            step_type=TraceStepType.FILE_RELATIONSHIP_RESOLUTION_DECIDED,
            stage_before="INPUT_RECEIVED",
            output_summary={"relationship_type": "replace_primary_file"},
            reasoning="The user explicitly replaced the previous primary file.",
        )
        t.record(
            step_type=TraceStepType.FILE_RELATIONSHIP_TRANSITION_APPLIED,
            stage_before="INPUT_RECEIVED",
            reasoning="Applied a bounded replacement transition.",
        )

        friendly = t.to_user_friendly()

        assert [item["step_type"] for item in friendly] == [
            "file_relationship_resolution_triggered",
            "file_relationship_resolution_decided",
            "file_relationship_transition_applied",
        ]
        assert friendly[1]["status"] == "success"

    def test_to_user_friendly_supplemental_merge_steps(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.SUPPLEMENTAL_MERGE_TRIGGERED,
            stage_before="INPUT_RECEIVED",
            reasoning="A bounded supplemental merge path was triggered.",
        )
        t.record(
            step_type=TraceStepType.SUPPLEMENTAL_MERGE_PLANNED,
            stage_before="INPUT_RECEIVED",
            reasoning="Planned a bounded key-based merge using segment_id->segment_id.",
        )
        t.record(
            step_type=TraceStepType.SUPPLEMENTAL_MERGE_APPLIED,
            stage_before="INPUT_RECEIVED",
            reasoning="Materialized a merged primary dataset with traffic_flow_vph.",
        )
        t.record(
            step_type=TraceStepType.SUPPLEMENTAL_MERGE_READINESS_REFRESHED,
            stage_before="INPUT_RECEIVED",
            output_summary={"after_status": "ready"},
            reasoning="Readiness refreshed after supplemental merge: repairable->ready.",
        )
        t.record(
            step_type=TraceStepType.SUPPLEMENTAL_MERGE_RESUMED,
            stage_before="INPUT_RECEIVED",
            reasoning="The merged workflow became resumable without auto replay.",
        )

        friendly = t.to_user_friendly()

        assert [item["step_type"] for item in friendly] == [
            "supplemental_merge_triggered",
            "supplemental_merge_planned",
            "supplemental_merge_applied",
            "supplemental_merge_readiness_refreshed",
            "supplemental_merge_resumed",
        ]
        assert friendly[0]["status"] == "warning"
        assert friendly[-1]["status"] == "success"

    def test_to_user_friendly_intent_resolution_steps(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.INTENT_RESOLUTION_TRIGGERED,
            stage_before="INPUT_RECEIVED",
            reasoning="The user requested a new deliverable form while current results were available.",
        )
        t.record(
            step_type=TraceStepType.INTENT_RESOLUTION_DECIDED,
            stage_before="INPUT_RECEIVED",
            output_summary={
                "deliverable_intent": "chart_or_ranked_summary",
                "progress_intent": "shift_output_mode",
            },
            reasoning="Visualization was requested without safe geometry support, so ranked summary delivery was preferred.",
        )
        t.record(
            step_type=TraceStepType.INTENT_RESOLUTION_APPLIED,
            stage_before="INPUT_RECEIVED",
            reasoning="Applied bounded follow-up bias toward summary delivery and away from spatial map actions.",
        )

        friendly = t.to_user_friendly()

        assert [item["step_type"] for item in friendly] == [
            "intent_resolution_triggered",
            "intent_resolution_decided",
            "intent_resolution_applied",
        ]
        assert friendly[1]["status"] == "success"

    def test_to_user_friendly_summary_delivery_steps(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.SUMMARY_DELIVERY_TRIGGERED,
            stage_before="INPUT_RECEIVED",
            reasoning="A bounded ranked chart/table delivery was triggered for the current emission result.",
        )
        t.record(
            step_type=TraceStepType.SUMMARY_DELIVERY_DECIDED,
            stage_before="INPUT_RECEIVED",
            output_summary={"selected_delivery_type": "ranked_bar_chart", "ranking_metric": "CO2_kg_h", "topk": 5},
            reasoning="Selected a ranked bar chart because the user explicitly requested visualization without geometry.",
        )
        t.record(
            step_type=TraceStepType.SUMMARY_DELIVERY_APPLIED,
            stage_before="INPUT_RECEIVED",
            reasoning="Materialized the ranked chart payload and the paired Top-K preview table.",
        )
        t.record(
            step_type=TraceStepType.SUMMARY_DELIVERY_RECORDED,
            stage_before="INPUT_RECEIVED",
            reasoning="Recorded ranked_chart and topk_summary_table artifacts into bounded artifact memory.",
        )

        friendly = t.to_user_friendly()

        assert [item["step_type"] for item in friendly] == [
            "summary_delivery_triggered",
            "summary_delivery_decided",
            "summary_delivery_applied",
            "summary_delivery_recorded",
        ]
        assert friendly[0]["status"] == "warning"
        assert friendly[-1]["status"] == "success"

    def test_to_user_friendly_execution_reconciliation_and_dependency_steps(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.PLAN_STEP_MATCHED,
            stage_before="EXECUTING",
            reasoning="Actual tool matched next planned step s1.",
        )
        t.record(
            step_type=TraceStepType.DEPENDENCY_VALIDATED,
            stage_before="EXECUTING",
            reasoning="All prerequisite result tokens available for calculate_dispersion: ['emission'].",
        )
        t.record(
            step_type=TraceStepType.PLAN_STEP_COMPLETED,
            stage_before="EXECUTING",
            reasoning="Completed planned step s1 via calculate_macro_emission.",
        )
        t.record(
            step_type=TraceStepType.DEPENDENCY_BLOCKED,
            stage_before="EXECUTING",
            reasoning="Cannot execute analyze_hotspots; prerequisite validation failed (missing=['dispersion']).",
        )

        friendly = t.to_user_friendly()

        assert [item["step_type"] for item in friendly] == [
            "plan_step_matched",
            "dependency_validated",
            "plan_step_completed",
            "dependency_blocked",
        ]
        assert friendly[0]["status"] == "success"
        assert friendly[-1]["status"] == "warning"

    def test_to_user_friendly_plan_repair_steps(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.PLAN_REPAIR_TRIGGERED,
            stage_before="EXECUTING",
            reasoning="Dependency gate triggered bounded repair after missing hotspot result.",
        )
        t.record(
            step_type=TraceStepType.PLAN_REPAIR_PROPOSED,
            stage_before="EXECUTING",
            output_summary={"validation_passed": True},
            reasoning="Proposed DROP_BLOCKED_STEP on s3.",
        )
        t.record(
            step_type=TraceStepType.PLAN_REPAIR_APPLIED,
            stage_before="EXECUTING",
            reasoning="Applied bounded repair DROP_BLOCKED_STEP on s3.",
        )
        t.record(
            step_type=TraceStepType.PLAN_REPAIR_FAILED,
            stage_before="EXECUTING",
            reasoning="Repair validation failed because the residual workflow stayed illegal.",
        )
        t.record(
            step_type=TraceStepType.PLAN_REPAIR_SKIPPED,
            stage_before="EXECUTING",
            reasoning="Ahead-of-plan deviation kept the residual workflow legal, so repair was skipped.",
        )

        friendly = t.to_user_friendly()

        assert [item["step_type"] for item in friendly] == [
            "plan_repair_triggered",
            "plan_repair_proposed",
            "plan_repair_applied",
            "plan_repair_failed",
            "plan_repair_skipped",
        ]
        assert friendly[1]["status"] == "success"
        assert friendly[3]["status"] == "error"

    def test_to_user_friendly_plan_continuation_steps(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.PLAN_CONTINUATION_DECIDED,
            stage_before="INPUT_RECEIVED",
            reasoning="Residual plan continuation was selected because the user said '继续'.",
        )
        t.record(
            step_type=TraceStepType.PLAN_CONTINUATION_SKIPPED,
            stage_before="INPUT_RECEIVED",
            reasoning="Residual plan existed, but the user explicitly started a new task.",
        )
        t.record(
            step_type=TraceStepType.PLAN_CONTINUATION_INJECTED,
            stage_before="INPUT_RECEIVED",
            reasoning="Injected next-step guidance for repair_s1 -> calculate_dispersion.",
        )

        friendly = t.to_user_friendly()

        assert [item["step_type"] for item in friendly] == [
            "plan_continuation_decided",
            "plan_continuation_skipped",
            "plan_continuation_injected",
        ]
        assert friendly[0]["status"] == "success"
        assert friendly[1]["status"] == "warning"
        assert friendly[2]["status"] == "success"

    def test_to_user_friendly_parameter_negotiation_steps(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.PARAMETER_NEGOTIATION_REQUIRED,
            stage_before="EXECUTING",
            stage_after="NEEDS_PARAMETER_CONFIRMATION",
            reasoning="vehicle_type='飞机' requires bounded confirmation because the candidate set stayed ambiguous.",
        )
        t.record(
            step_type=TraceStepType.PARAMETER_NEGOTIATION_CONFIRMED,
            stage_before="INPUT_RECEIVED",
            reasoning="Confirmed vehicle_type=Passenger Car from reply '1', and the lock was applied.",
        )
        t.record(
            step_type=TraceStepType.PARAMETER_NEGOTIATION_REJECTED,
            stage_before="INPUT_RECEIVED",
            reasoning="The user rejected all candidates and the flow moved to clarification.",
        )
        t.record(
            step_type=TraceStepType.PARAMETER_NEGOTIATION_FAILED,
            stage_before="INPUT_RECEIVED",
            stage_after="NEEDS_PARAMETER_CONFIRMATION",
            reasoning="The reply mentioned multiple candidates and could not be resolved uniquely.",
        )

        friendly = t.to_user_friendly()

        assert [item["step_type"] for item in friendly] == [
            "parameter_negotiation_required",
            "parameter_negotiation_confirmed",
            "parameter_negotiation_rejected",
            "parameter_negotiation_failed",
        ]
        assert friendly[0]["status"] == "warning"
        assert friendly[1]["status"] == "success"
        assert friendly[2]["status"] == "warning"
        assert friendly[3]["status"] == "error"

    def test_to_user_friendly_file_analysis_fallback_steps(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.FILE_ANALYSIS_FALLBACK_TRIGGERED,
            stage_before="INPUT_RECEIVED",
            reasoning="Rule confidence stayed low and several columns remained unresolved, so bounded fallback was triggered.",
        )
        t.record(
            step_type=TraceStepType.FILE_ANALYSIS_FALLBACK_APPLIED,
            stage_before="INPUT_RECEIVED",
            reasoning="Merged fallback semantics for vol/spd/len_km into the canonical macro file analysis result.",
        )
        t.record(
            step_type=TraceStepType.FILE_ANALYSIS_FALLBACK_SKIPPED,
            stage_before="INPUT_RECEIVED",
            reasoning="Rule-based file grounding already had high-confidence required-field coverage.",
        )
        t.record(
            step_type=TraceStepType.FILE_ANALYSIS_FALLBACK_FAILED,
            stage_before="INPUT_RECEIVED",
            reasoning="Fallback JSON validation failed, so the router kept the rule-based result.",
        )

        friendly = t.to_user_friendly()

        assert [item["step_type"] for item in friendly] == [
            "file_analysis_fallback_triggered",
            "file_analysis_fallback_applied",
            "file_analysis_fallback_skipped",
            "file_analysis_fallback_failed",
        ]
        assert friendly[0]["status"] == "warning"
        assert friendly[1]["status"] == "success"
        assert friendly[2]["status"] == "success"
        assert friendly[3]["status"] == "error"

    def test_to_user_friendly_file_analysis_enhancement_steps(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.FILE_ANALYSIS_MULTI_TABLE_ROLES,
            stage_before="INPUT_RECEIVED",
            reasoning="Detected 4 dataset role entries and selected roads.csv as the primary analysis table.",
        )
        t.record(
            step_type=TraceStepType.FILE_ANALYSIS_MISSING_FIELDS,
            stage_before="INPUT_RECEIVED",
            reasoning="Required-field diagnostics status=partial for task_type=micro_emission.",
        )
        t.record(
            step_type=TraceStepType.FILE_ANALYSIS_SPATIAL_METADATA,
            stage_before="INPUT_RECEIVED",
            reasoning="Extracted spatial metadata for 12 features with geometry_types=['LineString'].",
        )

        friendly = t.to_user_friendly()

        assert [item["step_type"] for item in friendly] == [
            "file_analysis_multi_table_roles",
            "file_analysis_missing_fields",
            "file_analysis_spatial_metadata",
        ]
        assert friendly[0]["status"] == "success"
        assert friendly[1]["status"] == "warning"
        assert friendly[2]["status"] == "success"

    def test_to_user_friendly_readiness_steps(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.READINESS_ASSESSMENT_BUILT,
            stage_before="EXECUTING",
            reasoning="Built readiness assessment for pre_execution: ready=2, repairable=1, blocked=1, already_provided=1.",
        )
        t.record(
            step_type=TraceStepType.ACTION_READINESS_READY,
            stage_before="EXECUTING",
            reasoning="The selected action render_emission_map has all prerequisites satisfied.",
        )
        t.record(
            step_type=TraceStepType.ACTION_READINESS_BLOCKED,
            stage_before="EXECUTING",
            reasoning="The selected action run_macro_emission was blocked because task_type=micro_emission is incompatible.",
        )
        t.record(
            step_type=TraceStepType.ACTION_READINESS_REPAIRABLE,
            stage_before="EXECUTING",
            reasoning="The selected action run_dispersion is repairable once geometry support is provided.",
        )
        t.record(
            step_type=TraceStepType.ACTION_READINESS_ALREADY_PROVIDED,
            stage_before="EXECUTING",
            reasoning="The download_detailed_csv artifact was already delivered in this turn.",
        )

        friendly = t.to_user_friendly()

        assert [item["step_type"] for item in friendly] == [
            "readiness_assessment_built",
            "action_readiness_ready",
            "action_readiness_blocked",
            "action_readiness_repairable",
            "action_readiness_already_provided",
        ]
        assert friendly[0]["status"] == "success"
        assert friendly[1]["status"] == "success"
        assert friendly[2]["status"] == "warning"
        assert friendly[3]["status"] == "warning"
        assert friendly[4]["status"] == "success"

    def test_to_user_friendly_input_completion_steps(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.INPUT_COMPLETION_REQUIRED,
            stage_before="EXECUTING",
            reasoning="The selected action run_macro_emission entered bounded input completion for traffic_flow_vph.",
        )
        t.record(
            step_type=TraceStepType.INPUT_COMPLETION_CONFIRMED,
            stage_before="INPUT_RECEIVED",
            reasoning="Parsed bounded completion reply '1500' into a uniform scalar override.",
        )
        t.record(
            step_type=TraceStepType.INPUT_COMPLETION_APPLIED,
            stage_before="INPUT_RECEIVED",
            reasoning="Applied the traffic_flow_vph uniform override and resumed the current task context.",
        )
        t.record(
            step_type=TraceStepType.INPUT_COMPLETION_FAILED,
            stage_before="INPUT_RECEIVED",
            reasoning="The completion reply did not include a numeric value.",
        )
        t.record(
            step_type=TraceStepType.INPUT_COMPLETION_PAUSED,
            stage_before="INPUT_RECEIVED",
            reasoning="The active completion flow was paused explicitly.",
        )
        t.record(
            step_type=TraceStepType.INPUT_COMPLETION_REJECTED,
            stage_before="INPUT_RECEIVED",
            reasoning="The active completion flow was superseded by an explicit new task.",
        )

        friendly = t.to_user_friendly()

        assert [item["step_type"] for item in friendly] == [
            "input_completion_required",
            "input_completion_confirmed",
            "input_completion_applied",
            "input_completion_failed",
            "input_completion_paused",
            "input_completion_rejected",
        ]
        assert friendly[0]["status"] == "warning"
        assert friendly[1]["status"] == "success"
        assert friendly[2]["status"] == "success"
        assert friendly[3]["status"] == "warning"
        assert friendly[4]["status"] == "warning"
        assert friendly[5]["status"] == "warning"

    def test_to_user_friendly_geometry_recovery_steps(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.GEOMETRY_COMPLETION_ATTACHED,
            stage_before="INPUT_RECEIVED",
            reasoning="Attached supporting spatial file roads.geojson for bounded geometry recovery.",
        )
        t.record(
            step_type=TraceStepType.GEOMETRY_RE_GROUNDING_TRIGGERED,
            stage_before="INPUT_RECEIVED",
            reasoning="Triggered bounded geometry re-grounding with the current primary file plus one supporting spatial file.",
        )
        t.record(
            step_type=TraceStepType.GEOMETRY_RE_GROUNDING_APPLIED,
            stage_before="INPUT_RECEIVED",
            reasoning="Applied bounded file-aware re-grounding and refreshed geometry-support facts in the current task context.",
        )
        t.record(
            step_type=TraceStepType.GEOMETRY_RE_GROUNDING_FAILED,
            stage_before="INPUT_RECEIVED",
            reasoning="Supporting file did not expose usable geometry support signals.",
        )
        t.record(
            step_type=TraceStepType.GEOMETRY_READINESS_REFRESHED,
            stage_before="INPUT_RECEIVED",
            output_summary={"after_status": "ready"},
            reasoning="Readiness refreshed after geometry remediation: repairable->ready.",
        )
        t.record(
            step_type=TraceStepType.GEOMETRY_RECOVERY_RESUMED,
            stage_before="INPUT_RECEIVED",
            reasoning="Restored the current task context after bounded geometry remediation without auto-executing downstream tools.",
        )

        friendly = t.to_user_friendly()

        assert [item["step_type"] for item in friendly] == [
            "geometry_completion_attached",
            "geometry_re_grounding_triggered",
            "geometry_re_grounding_applied",
            "geometry_re_grounding_failed",
            "geometry_readiness_refreshed",
            "geometry_recovery_resumed",
        ]
        assert friendly[0]["status"] == "success"
        assert friendly[1]["status"] == "warning"
        assert friendly[2]["status"] == "success"
        assert friendly[3]["status"] == "error"
        assert friendly[4]["status"] == "success"
        assert friendly[5]["status"] == "success"

    def test_to_user_friendly_residual_reentry_steps(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.RESIDUAL_REENTRY_TARGET_SET,
            stage_before="INPUT_RECEIVED",
            reasoning="Geometry recovery succeeded, so a formal recovered-workflow re-entry target was set for the next turn.",
        )
        t.record(
            step_type=TraceStepType.RESIDUAL_REENTRY_DECIDED,
            stage_before="INPUT_RECEIVED",
            output_summary={"should_apply": True},
            reasoning="Recovered workflow continuation stayed on-task, so the next turn was deterministically biased toward the repaired target action.",
        )
        t.record(
            step_type=TraceStepType.RESIDUAL_REENTRY_INJECTED,
            stage_before="INPUT_RECEIVED",
            reasoning="Injected bounded recovered-workflow re-entry guidance without introducing auto-replay or scheduler semantics.",
        )
        t.record(
            step_type=TraceStepType.RESIDUAL_REENTRY_SKIPPED,
            stage_before="INPUT_RECEIVED",
            reasoning="The user explicitly started a new task, so recovered-workflow re-entry bias was skipped.",
        )

        friendly = t.to_user_friendly()

        assert [item["step_type"] for item in friendly] == [
            "residual_reentry_target_set",
            "residual_reentry_decided",
            "residual_reentry_injected",
            "residual_reentry_skipped",
        ]
        assert friendly[0]["status"] == "success"
        assert friendly[1]["status"] == "success"
        assert friendly[2]["status"] == "success"
        assert friendly[3]["status"] == "warning"

    def test_to_user_friendly_artifact_memory_steps(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.ARTIFACT_RECORDED,
            stage_before="DONE",
            reasoning="Recorded a detailed_csv artifact after delivering the download link.",
        )
        t.record(
            step_type=TraceStepType.ARTIFACT_MEMORY_UPDATED,
            stage_before="DONE",
            reasoning="Artifact memory now tracks downloadable_table and textual_summary outputs.",
        )
        t.record(
            step_type=TraceStepType.ARTIFACT_ALREADY_PROVIDED_DETECTED,
            stage_before="GROUNDED",
            reasoning="The requested CSV export was already delivered in a previous turn.",
        )
        t.record(
            step_type=TraceStepType.ARTIFACT_SUGGESTION_BIAS_APPLIED,
            stage_before="DONE",
            reasoning="Suppressed duplicate map guidance and promoted a new-family ranked summary suggestion.",
        )
        t.record(
            step_type=TraceStepType.ARTIFACT_MEMORY_SKIPPED,
            stage_before="DONE",
            reasoning="No structured artifact was delivered in this turn.",
        )

        friendly = t.to_user_friendly()

        assert [item["step_type"] for item in friendly] == [
            "artifact_recorded",
            "artifact_memory_updated",
            "artifact_already_provided_detected",
            "artifact_suggestion_bias_applied",
        ]
        assert friendly[0]["status"] == "success"
        assert friendly[1]["status"] == "success"
        assert friendly[2]["status"] == "warning"
        assert friendly[3]["status"] == "success"

    def test_full_workflow_trace(self):
        """Simulate a complete file→tool→synthesis trace."""
        t = Trace.start(session_id="full-test")
        t.record(
            step_type=TraceStepType.FILE_GROUNDING,
            stage_before="INPUT_RECEIVED",
            action="analyze_file",
            output_summary={"task_type": "macro_emission"},
            confidence=0.9,
            reasoning="Column 'speed' + 'flow' + 'length' detected",
        )
        t.record(
            step_type=TraceStepType.TOOL_SELECTION,
            stage_before="INPUT_RECEIVED",
            stage_after="GROUNDED",
            action="calculate_macro_emission",
        )
        t.record(
            step_type=TraceStepType.TOOL_EXECUTION,
            stage_before="EXECUTING",
            action="calculate_macro_emission",
            output_summary={"success": True},
            duration_ms=500.0,
        )
        t.record(
            step_type=TraceStepType.SYNTHESIS,
            stage_before="DONE",
            reasoning="Results synthesized",
        )
        t.finish("DONE")

        d = t.to_dict()
        assert d["step_count"] == 4
        assert json.dumps(d)

        friendly = t.to_user_friendly()
        assert len(friendly) == 4
        assert friendly[0]["step_type"] == "file_grounding"
        assert friendly[1]["step_type"] == "tool_selection"
        assert friendly[2]["step_type"] == "tool_execution"
        assert friendly[3]["step_type"] == "synthesis"


class TestTraceFriendlyFieldNaming:
    """Phase 8.2.5 G6: trace_friendly items must have 'type' and 'latency_ms' fields."""

    def test_friendly_items_have_type_field(self):
        """Every trace_friendly item carries 'type' for frontend consumption."""
        t = Trace()
        t.record(
            step_type=TraceStepType.FILE_GROUNDING,
            stage_before="INPUT_RECEIVED",
            output_summary={"task_type": "csv", "row_count": 10},
            confidence=0.95,
        )
        t.record(
            step_type=TraceStepType.TOOL_EXECUTION,
            stage_before="EXECUTING",
            stage_after="DONE",
            duration_ms=1234.5,
        )
        friendly = t.to_user_friendly()
        assert len(friendly) == 2
        for item in friendly:
            assert "type" in item, f"missing 'type' field in {item}"
            assert item["type"] == item.get("step_type", ""), (
                f"'type' ({item['type']}) != 'step_type' ({item.get('step_type')})"
            )

    def test_friendly_items_have_latency_ms_when_duration_present(self):
        """trace_friendly carries latency_ms (integer ms) when duration_ms is set."""
        t = Trace()
        t.record(
            step_type=TraceStepType.TOOL_EXECUTION,
            stage_before="EXECUTING",
            stage_after="DONE",
            duration_ms=987.6,
        )
        t.record(
            step_type=TraceStepType.SYNTHESIS,
            stage_before="EXECUTING",
            stage_after="DONE",
            # duration_ms not set
        )
        friendly = t.to_user_friendly()
        assert len(friendly) == 2
        # Item with duration_ms
        assert "latency_ms" in friendly[0], "missing latency_ms when duration_ms is set"
        assert friendly[0]["latency_ms"] == 987
        assert isinstance(friendly[0]["latency_ms"], int)
        # Item without duration_ms
        assert "latency_ms" not in friendly[1], (
            "latency_ms should be absent when duration_ms is None"
        )
