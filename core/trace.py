"""
EmissionAgent - Auditable Decision Trace

Records structured decision steps across the agent workflow.
Each state transition in the Router's state loop generates a TraceStep,
creating a complete auditable record of how the system processed a request.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class TraceStepType(str, Enum):
    """Types of trace steps."""

    FILE_GROUNDING = "file_grounding"
    FILE_ANALYSIS_MULTI_TABLE_ROLES = "file_analysis_multi_table_roles"
    FILE_ANALYSIS_MISSING_FIELDS = "file_analysis_missing_fields"
    FILE_ANALYSIS_SPATIAL_METADATA = "file_analysis_spatial_metadata"
    FILE_ANALYSIS_FALLBACK_TRIGGERED = "file_analysis_fallback_triggered"
    FILE_ANALYSIS_FALLBACK_APPLIED = "file_analysis_fallback_applied"
    FILE_ANALYSIS_FALLBACK_SKIPPED = "file_analysis_fallback_skipped"
    FILE_ANALYSIS_FALLBACK_FAILED = "file_analysis_fallback_failed"
    FILE_RELATIONSHIP_RESOLUTION_TRIGGERED = "file_relationship_resolution_triggered"
    FILE_RELATIONSHIP_RESOLUTION_DECIDED = "file_relationship_resolution_decided"
    FILE_RELATIONSHIP_TRANSITION_APPLIED = "file_relationship_transition_applied"
    FILE_RELATIONSHIP_RESOLUTION_SKIPPED = "file_relationship_resolution_skipped"
    FILE_RELATIONSHIP_RESOLUTION_FAILED = "file_relationship_resolution_failed"
    SUPPLEMENTAL_MERGE_TRIGGERED = "supplemental_merge_triggered"
    SUPPLEMENTAL_MERGE_PLANNED = "supplemental_merge_planned"
    SUPPLEMENTAL_MERGE_APPLIED = "supplemental_merge_applied"
    SUPPLEMENTAL_MERGE_FAILED = "supplemental_merge_failed"
    SUPPLEMENTAL_MERGE_READINESS_REFRESHED = "supplemental_merge_readiness_refreshed"
    SUPPLEMENTAL_MERGE_RESUMED = "supplemental_merge_resumed"
    INTENT_RESOLUTION_TRIGGERED = "intent_resolution_triggered"
    INTENT_RESOLUTION_DECIDED = "intent_resolution_decided"
    INTENT_RESOLUTION_APPLIED = "intent_resolution_applied"
    INTENT_RESOLUTION_SKIPPED = "intent_resolution_skipped"
    INTENT_RESOLUTION_FAILED = "intent_resolution_failed"
    ARTIFACT_RECORDED = "artifact_recorded"
    ARTIFACT_MEMORY_UPDATED = "artifact_memory_updated"
    ARTIFACT_ALREADY_PROVIDED_DETECTED = "artifact_already_provided_detected"
    ARTIFACT_SUGGESTION_BIAS_APPLIED = "artifact_suggestion_bias_applied"
    ARTIFACT_MEMORY_SKIPPED = "artifact_memory_skipped"
    SUMMARY_DELIVERY_TRIGGERED = "summary_delivery_triggered"
    SUMMARY_DELIVERY_DECIDED = "summary_delivery_decided"
    SUMMARY_DELIVERY_APPLIED = "summary_delivery_applied"
    SUMMARY_DELIVERY_RECORDED = "summary_delivery_recorded"
    SUMMARY_DELIVERY_SKIPPED = "summary_delivery_skipped"
    SUMMARY_DELIVERY_FAILED = "summary_delivery_failed"
    READINESS_ASSESSMENT_BUILT = "readiness_assessment_built"
    ACTION_READINESS_READY = "action_readiness_ready"
    ACTION_READINESS_BLOCKED = "action_readiness_blocked"
    ACTION_READINESS_REPAIRABLE = "action_readiness_repairable"
    ACTION_READINESS_ALREADY_PROVIDED = "action_readiness_already_provided"
    WORKFLOW_TEMPLATE_RECOMMENDED = "workflow_template_recommended"
    WORKFLOW_TEMPLATE_SELECTED = "workflow_template_selected"
    WORKFLOW_TEMPLATE_INJECTED = "workflow_template_injected"
    WORKFLOW_TEMPLATE_SKIPPED = "workflow_template_skipped"
    PLAN_CREATED = "plan_created"
    PLAN_VALIDATED = "plan_validated"
    PLAN_DEVIATION = "plan_deviation"
    PLAN_STEP_MATCHED = "plan_step_matched"
    PLAN_STEP_COMPLETED = "plan_step_completed"
    DEPENDENCY_VALIDATED = "dependency_validated"
    DEPENDENCY_BLOCKED = "dependency_blocked"
    PLAN_REPAIR_TRIGGERED = "plan_repair_triggered"
    PLAN_REPAIR_PROPOSED = "plan_repair_proposed"
    PLAN_REPAIR_APPLIED = "plan_repair_applied"
    PLAN_REPAIR_FAILED = "plan_repair_failed"
    PLAN_REPAIR_SKIPPED = "plan_repair_skipped"
    PLAN_CONTINUATION_DECIDED = "plan_continuation_decided"
    PLAN_CONTINUATION_SKIPPED = "plan_continuation_skipped"
    PLAN_CONTINUATION_INJECTED = "plan_continuation_injected"
    PARAMETER_NEGOTIATION_REQUIRED = "parameter_negotiation_required"
    PARAMETER_NEGOTIATION_CONFIRMED = "parameter_negotiation_confirmed"
    PARAMETER_NEGOTIATION_REJECTED = "parameter_negotiation_rejected"
    PARAMETER_NEGOTIATION_FAILED = "parameter_negotiation_failed"
    INPUT_COMPLETION_REQUIRED = "input_completion_required"
    INPUT_COMPLETION_CONFIRMED = "input_completion_confirmed"
    INPUT_COMPLETION_REJECTED = "input_completion_rejected"
    INPUT_COMPLETION_FAILED = "input_completion_failed"
    INPUT_COMPLETION_APPLIED = "input_completion_applied"
    INPUT_COMPLETION_PAUSED = "input_completion_paused"
    GEOMETRY_COMPLETION_ATTACHED = "geometry_completion_attached"
    GEOMETRY_RE_GROUNDING_TRIGGERED = "geometry_re_grounding_triggered"
    GEOMETRY_RE_GROUNDING_APPLIED = "geometry_re_grounding_applied"
    GEOMETRY_RE_GROUNDING_FAILED = "geometry_re_grounding_failed"
    GEOMETRY_READINESS_REFRESHED = "geometry_readiness_refreshed"
    GEOMETRY_RECOVERY_RESUMED = "geometry_recovery_resumed"
    RESIDUAL_REENTRY_TARGET_SET = "residual_reentry_target_set"
    RESIDUAL_REENTRY_DECIDED = "residual_reentry_decided"
    RESIDUAL_REENTRY_INJECTED = "residual_reentry_injected"
    RESIDUAL_REENTRY_SKIPPED = "residual_reentry_skipped"
    REMEDIATION_POLICY_OPTION_OFFERED = "remediation_policy_option_offered"
    REMEDIATION_POLICY_CONFIRMED = "remediation_policy_confirmed"
    REMEDIATION_POLICY_APPLIED = "remediation_policy_applied"
    REMEDIATION_POLICY_FAILED = "remediation_policy_failed"
    PARAMETER_STANDARDIZATION = "parameter_standardization"
    CROSS_CONSTRAINT_VALIDATED = "cross_constraint_validated"
    CROSS_CONSTRAINT_VIOLATION = "cross_constraint_violation"
    CROSS_CONSTRAINT_WARNING = "cross_constraint_warning"
    TOOL_SELECTION = "tool_selection"
    TOOL_EXECUTION = "tool_execution"
    STATE_TRANSITION = "state_transition"
    CLARIFICATION = "clarification"
    SYNTHESIS = "synthesis"
    REPLY_GENERATION = "reply_generation"
    ERROR = "error"
    IDEMPOTENT_SKIP = "idempotent_skip"


@dataclass
class TraceStep:
    """A single decision step in the agent workflow."""

    step_index: int
    step_type: TraceStepType
    timestamp: str  # ISO format
    stage_before: str  # TaskStage value at start of this step
    stage_after: Optional[str] = None  # TaskStage value after this step
    action: Optional[str] = None  # what was done (e.g. "analyze_file", "calculate_macro_emission")
    input_summary: Optional[Dict[str, Any]] = None  # key inputs (NOT full data, keep it compact)
    output_summary: Optional[Dict[str, Any]] = None  # key outputs (compact)
    confidence: Optional[float] = None
    reasoning: Optional[str] = None  # why this decision was made
    duration_ms: Optional[float] = None  # step duration in milliseconds
    standardization_records: Optional[List[Dict[str, Any]]] = None  # param standardization details
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict, excluding None fields for cleaner output."""
        result = {}
        for key in ["step_index", "step_type", "timestamp", "stage_before"]:
            val = getattr(self, key)
            result[key] = val.value if isinstance(val, Enum) else val
        for key in [
            "stage_after",
            "action",
            "input_summary",
            "output_summary",
            "confidence",
            "reasoning",
            "duration_ms",
            "standardization_records",
            "error",
        ]:
            val = getattr(self, key)
            if val is not None:
                result[key] = val
        return result


@dataclass
class Trace:
    """Complete auditable decision trace for one agent turn."""

    session_id: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    total_duration_ms: Optional[float] = None
    steps: List[TraceStep] = field(default_factory=list)
    final_stage: Optional[str] = None  # the TaskStage the system ended in

    @classmethod
    def start(cls, session_id: Optional[str] = None) -> "Trace":
        """Initialize a new trace at the beginning of a turn."""
        return cls(
            session_id=session_id,
            start_time=datetime.now().isoformat(),
        )

    def record(
        self,
        step_type: TraceStepType,
        stage_before: str,
        stage_after: Optional[str] = None,
        action: Optional[str] = None,
        input_summary: Optional[Dict] = None,
        output_summary: Optional[Dict] = None,
        confidence: Optional[float] = None,
        reasoning: str = "",
        duration_ms: Optional[float] = None,
        standardization_records: Optional[List[Dict]] = None,
        error: Optional[str] = None,
    ) -> TraceStep:
        """Record a single trace step. Returns the created step."""
        step = TraceStep(
            step_index=len(self.steps),
            step_type=step_type,
            timestamp=datetime.now().isoformat(),
            stage_before=stage_before,
            stage_after=stage_after,
            action=action,
            input_summary=input_summary,
            output_summary=output_summary,
            confidence=confidence,
            reasoning=reasoning,
            duration_ms=duration_ms,
            standardization_records=standardization_records,
            error=error,
        )
        self.steps.append(step)
        return step

    def finish(self, final_stage: str) -> None:
        """Mark the trace as complete."""
        self.end_time = datetime.now().isoformat()
        self.final_stage = final_stage
        if self.start_time:
            try:
                start = datetime.fromisoformat(self.start_time)
                end = datetime.fromisoformat(self.end_time)
                self.total_duration_ms = round((end - start).total_seconds() * 1000, 1)
            except (ValueError, TypeError):
                pass

    def to_dict(self) -> Dict[str, Any]:
        """Full serialization for API response and logging."""
        return {
            "session_id": self.session_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_duration_ms": self.total_duration_ms,
            "final_stage": self.final_stage,
            "step_count": len(self.steps),
            "steps": [s.to_dict() for s in self.steps],
        }

    def persist(
        self,
        output_dir: Optional[str | Path] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """Persist the trace as a JSON audit artifact on disk."""
        import json

        if output_dir is None:
            resolved_output_dir = Path(__file__).parent.parent / "data" / "traces"
        else:
            resolved_output_dir = Path(output_dir)

        resolved_output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        resolved_session_id = session_id or self.session_id
        session_part = f"_{resolved_session_id}" if resolved_session_id else ""
        filename = f"trace{session_part}_{timestamp}.json"
        filepath = resolved_output_dir / filename

        with filepath.open("w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2, default=str)

        return str(filepath)

    def to_user_friendly(self) -> List[Dict[str, str]]:
        """Convert to user-friendly display format for frontend trace panel.

        Returns a list of {title, description, status, step_type} dicts.
        Title and description are bilingual (Chinese / English).
        """
        friendly = []
        for step in self.steps:
            entry = self._format_step_friendly(step)
            if entry:
                friendly.append(entry)
        return friendly

    def _format_step_friendly(self, step: TraceStep) -> Optional[Dict[str, str]]:
        """Format a single step for user display."""
        if step.step_type == TraceStepType.FILE_GROUNDING:
            task_type = step.output_summary.get("task_type", "unknown") if step.output_summary else "unknown"
            conf = step.confidence
            if conf is None and step.output_summary:
                conf = step.output_summary.get("confidence")
            if conf is not None:
                try:
                    conf = float(conf)
                except (TypeError, ValueError):
                    conf = None
            conf_str = f"{conf:.0%}" if conf is not None else "N/A"
            row_count = step.output_summary.get("row_count", "?") if step.output_summary else "?"
            columns = step.output_summary.get("columns", []) if step.output_summary else []
            col_preview = ", ".join(columns[:5])
            if len(columns) > 5:
                col_preview += f" ... (+{len(columns) - 5})"

            evidence_lines = ""
            if step.reasoning:
                evidence_items = [e.strip() for e in step.reasoning.split(";") if e.strip()]
                if evidence_items:
                    evidence_lines = "\n" + "\n".join(f"  · {e}" for e in evidence_items[:4])

            desc = f"Task: {task_type} (confidence {conf_str}), {row_count} rows"
            if col_preview:
                desc += f"\nColumns: {col_preview}"
            desc += evidence_lines

            return {
                "title": "文件识别 / File Analysis",
                "description": desc,
                "status": "success" if conf and conf > 0.6 else "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.FILE_ANALYSIS_MULTI_TABLE_ROLES:
            return {
                "title": "多表角色 / Multi-Table Roles",
                "description": step.reasoning or "Detected bounded dataset roles for a multi-dataset file package.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.FILE_ANALYSIS_MISSING_FIELDS:
            return {
                "title": "缺失字段诊断 / Missing-Field Diagnostics",
                "description": step.reasoning or "Structured required-field diagnostics were generated for file grounding.",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.FILE_ANALYSIS_SPATIAL_METADATA:
            return {
                "title": "空间元数据 / Spatial Metadata",
                "description": step.reasoning or "Extracted bounded spatial metadata from the grounded geospatial file.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.FILE_ANALYSIS_FALLBACK_TRIGGERED:
            return {
                "title": "文件兜底触发 / File Fallback Triggered",
                "description": step.reasoning or "Low-confidence file grounding triggered bounded LLM fallback",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.FILE_ANALYSIS_FALLBACK_APPLIED:
            return {
                "title": "文件兜底应用 / File Fallback Applied",
                "description": step.reasoning or "LLM fallback was merged into the canonical file analysis result",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.FILE_ANALYSIS_FALLBACK_SKIPPED:
            return {
                "title": "文件兜底跳过 / File Fallback Skipped",
                "description": step.reasoning or "Rule-based file analysis was strong enough; no fallback used",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.FILE_ANALYSIS_FALLBACK_FAILED:
            return {
                "title": "文件兜底失败 / File Fallback Failed",
                "description": step.reasoning or step.error or "LLM fallback failed and the system kept the rule-based result",
                "status": "error",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.FILE_RELATIONSHIP_RESOLUTION_TRIGGERED:
            return {
                "title": "文件关系触发 / File Relationship Triggered",
                "description": step.reasoning or "A bounded file-relationship resolution pass was triggered before state migration.",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.FILE_RELATIONSHIP_RESOLUTION_DECIDED:
            relationship_type = (
                step.output_summary.get("relationship_type", "unknown")
                if step.output_summary
                else "unknown"
            )
            desc = f"Resolved as {relationship_type}"
            if step.reasoning:
                desc += f"\n{step.reasoning}"
            return {
                "title": "文件关系判定 / File Relationship Decided",
                "description": desc,
                "status": "success" if relationship_type != "ask_clarify" else "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.FILE_RELATIONSHIP_TRANSITION_APPLIED:
            return {
                "title": "文件迁移应用 / Relationship Transition Applied",
                "description": step.reasoning or "Applied a bounded backend transition from the file-relationship decision.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.FILE_RELATIONSHIP_RESOLUTION_SKIPPED:
            return None

        elif step.step_type == TraceStepType.FILE_RELATIONSHIP_RESOLUTION_FAILED:
            return {
                "title": "文件关系失败 / File Relationship Failed",
                "description": step.reasoning or step.error or "The bounded file-relationship resolution failed.",
                "status": "error",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.SUPPLEMENTAL_MERGE_TRIGGERED:
            return {
                "title": "补充表合并触发 / Supplemental Merge Triggered",
                "description": step.reasoning or "A bounded supplemental-column merge path was triggered.",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.SUPPLEMENTAL_MERGE_PLANNED:
            return {
                "title": "补充表合并规划 / Supplemental Merge Planned",
                "description": step.reasoning or "A bounded key-based supplemental merge plan was built.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.SUPPLEMENTAL_MERGE_APPLIED:
            return {
                "title": "补充表合并应用 / Supplemental Merge Applied",
                "description": step.reasoning or "The supplemental columns were materialized into a merged primary dataset.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.SUPPLEMENTAL_MERGE_FAILED:
            return {
                "title": "补充表合并失败 / Supplemental Merge Failed",
                "description": step.reasoning or step.error or "The bounded supplemental merge path could not be applied safely.",
                "status": "error",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.SUPPLEMENTAL_MERGE_READINESS_REFRESHED:
            return {
                "title": "补充表就绪刷新 / Supplemental Merge Readiness Refreshed",
                "description": step.reasoning or "Readiness was refreshed after the bounded supplemental merge.",
                "status": "success" if (step.output_summary or {}).get("after_status") == "ready" else "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.SUPPLEMENTAL_MERGE_RESUMED:
            return {
                "title": "补充表恢复可续 / Supplemental Merge Resumable",
                "description": step.reasoning or "The merged workflow became resumable without auto-replay.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.INTENT_RESOLUTION_TRIGGERED:
            return {
                "title": "意图解析触发 / Intent Resolution Triggered",
                "description": step.reasoning or "A bounded deliverable/progress intent pass was triggered.",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.INTENT_RESOLUTION_DECIDED:
            deliverable = (
                step.output_summary.get("deliverable_intent", "unknown")
                if step.output_summary
                else "unknown"
            )
            progress = (
                step.output_summary.get("progress_intent", "ask_clarify")
                if step.output_summary
                else "ask_clarify"
            )
            desc = f"Resolved as {deliverable} + {progress}"
            if step.reasoning:
                desc += f"\n{step.reasoning}"
            return {
                "title": "意图判定 / Intent Resolution Decided",
                "description": desc,
                "status": "success" if progress != "ask_clarify" else "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.INTENT_RESOLUTION_APPLIED:
            return {
                "title": "意图偏置应用 / Intent Resolution Applied",
                "description": step.reasoning or "Applied bounded deliverable/progress bias to the current workflow context.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.INTENT_RESOLUTION_SKIPPED:
            return None

        elif step.step_type == TraceStepType.INTENT_RESOLUTION_FAILED:
            return {
                "title": "意图解析失败 / Intent Resolution Failed",
                "description": step.reasoning or step.error or "The bounded deliverable/progress intent resolution failed.",
                "status": "error",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.ARTIFACT_RECORDED:
            return {
                "title": "交付物记录 / Artifact Recorded",
                "description": step.reasoning or "A delivered artifact was recorded into bounded artifact memory.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.ARTIFACT_MEMORY_UPDATED:
            return {
                "title": "交付物记忆更新 / Artifact Memory Updated",
                "description": step.reasoning or "Artifact memory state was updated after delivery.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.ARTIFACT_ALREADY_PROVIDED_DETECTED:
            return {
                "title": "重复交付识别 / Artifact Already Provided Detected",
                "description": step.reasoning or "A repeated artifact request or suggestion was detected from artifact memory.",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.ARTIFACT_SUGGESTION_BIAS_APPLIED:
            return {
                "title": "交付物偏置应用 / Artifact Suggestion Bias Applied",
                "description": step.reasoning or "Artifact memory biased follow-up suggestions toward new output forms.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.ARTIFACT_MEMORY_SKIPPED:
            return None

        elif step.step_type == TraceStepType.SUMMARY_DELIVERY_TRIGGERED:
            return {
                "title": "摘要交付触发 / Summary Delivery Triggered",
                "description": step.reasoning or "A bounded chart/summary delivery surface was triggered.",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.SUMMARY_DELIVERY_DECIDED:
            return {
                "title": "摘要交付判定 / Summary Delivery Decided",
                "description": step.reasoning or "A bounded summary-delivery plan was selected.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.SUMMARY_DELIVERY_APPLIED:
            return {
                "title": "摘要交付应用 / Summary Delivery Applied",
                "description": step.reasoning or "The bounded chart/summary delivery payloads were materialized.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.SUMMARY_DELIVERY_RECORDED:
            return {
                "title": "摘要交付记录 / Summary Delivery Recorded",
                "description": step.reasoning or "The delivery artifacts were recorded for the bounded chart/summary surface.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.SUMMARY_DELIVERY_SKIPPED:
            return None

        elif step.step_type == TraceStepType.SUMMARY_DELIVERY_FAILED:
            return {
                "title": "摘要交付失败 / Summary Delivery Failed",
                "description": step.reasoning or step.error or "The bounded summary-delivery surface could not produce a safe output.",
                "status": "error",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.READINESS_ASSESSMENT_BUILT:
            return {
                "title": "就绪性评估 / Readiness Assessment",
                "description": step.reasoning or "Built a bounded readiness assessment for current action affordances.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.ACTION_READINESS_READY:
            return {
                "title": "动作可执行 / Action Ready",
                "description": step.reasoning or "The selected action is currently executable.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.ACTION_READINESS_BLOCKED:
            return {
                "title": "动作阻断 / Action Blocked",
                "description": step.reasoning or "The selected action was blocked before execution.",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.ACTION_READINESS_REPAIRABLE:
            return {
                "title": "动作可修复 / Action Repairable",
                "description": step.reasoning or "The selected action was recognized as repairable and stopped before execution.",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.ACTION_READINESS_ALREADY_PROVIDED:
            return {
                "title": "交付已提供 / Already Provided",
                "description": step.reasoning or "The selected artifact-equivalent action was already delivered in this turn.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.WORKFLOW_TEMPLATE_RECOMMENDED:
            return {
                "title": "模板推荐 / Template Recommended",
                "description": step.reasoning or "Rule-based workflow templates were recommended from file grounding.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.WORKFLOW_TEMPLATE_SELECTED:
            return {
                "title": "模板选定 / Template Selected",
                "description": step.reasoning or "A primary workflow template prior was selected for planning.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.WORKFLOW_TEMPLATE_INJECTED:
            return {
                "title": "模板注入 / Template Injected",
                "description": step.reasoning or "Workflow template prior was injected into the planning context.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.WORKFLOW_TEMPLATE_SKIPPED:
            return {
                "title": "模板跳过 / Template Skipped",
                "description": step.reasoning or "Workflow template recommendation was skipped for this turn.",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.TOOL_SELECTION:
            tool = step.action or "unknown"
            return {
                "title": "工具选择 / Tool Selection",
                "description": f"Selected {tool}",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.PLAN_CREATED:
            goal = step.output_summary.get("goal", "unknown goal") if step.output_summary else "unknown goal"
            step_count = step.output_summary.get("step_count", 0) if step.output_summary else 0
            desc = f"{step_count} planned step(s)\nGoal: {goal}"
            if step.reasoning:
                desc += f"\n{step.reasoning}"
            return {
                "title": "计划生成 / Plan Created",
                "description": desc,
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.PLAN_VALIDATED:
            plan_status = step.output_summary.get("plan_status", "unknown") if step.output_summary else "unknown"
            desc = f"Validation status: {plan_status}"
            if step.reasoning:
                desc += f"\n{step.reasoning}"
            return {
                "title": "计划校验 / Plan Validated",
                "description": desc,
                "status": "success" if plan_status == "valid" else "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.PLAN_DEVIATION:
            return {
                "title": "计划偏离 / Plan Deviation",
                "description": step.reasoning or "Execution deviated from the current plan",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.PLAN_STEP_MATCHED:
            return {
                "title": "计划对齐 / Plan Step Matched",
                "description": step.reasoning or "Actual tool matched the next planned step",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.PLAN_STEP_COMPLETED:
            return {
                "title": "计划完成 / Plan Step Completed",
                "description": step.reasoning or "Planned step completed",
                "status": "success" if step.error is None else "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.DEPENDENCY_VALIDATED:
            return {
                "title": "依赖校验 / Dependency Validated",
                "description": step.reasoning or "Dependency validation passed",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.DEPENDENCY_BLOCKED:
            return {
                "title": "依赖阻断 / Dependency Blocked",
                "description": step.reasoning or "Execution blocked by missing prerequisites",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.PLAN_REPAIR_TRIGGERED:
            return {
                "title": "修复触发 / Plan Repair Triggered",
                "description": step.reasoning or "Bounded plan repair was triggered",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.PLAN_REPAIR_PROPOSED:
            return {
                "title": "修复提议 / Plan Repair Proposed",
                "description": step.reasoning or "A bounded repair proposal was generated",
                "status": "success" if (step.output_summary or {}).get("validation_passed") else "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.PLAN_REPAIR_APPLIED:
            return {
                "title": "修复应用 / Plan Repair Applied",
                "description": step.reasoning or "Residual plan was updated by bounded repair",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.PLAN_REPAIR_FAILED:
            return {
                "title": "修复失败 / Plan Repair Failed",
                "description": step.reasoning or step.error or "Repair generation or validation failed",
                "status": "error",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.PLAN_REPAIR_SKIPPED:
            return {
                "title": "修复跳过 / Plan Repair Skipped",
                "description": step.reasoning or "Repair trigger was evaluated but skipped",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.PLAN_CONTINUATION_DECIDED:
            return {
                "title": "延续判定 / Continuation Decided",
                "description": step.reasoning or "The next turn was treated as a residual-plan continuation",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.PLAN_CONTINUATION_SKIPPED:
            return {
                "title": "延续跳过 / Continuation Skipped",
                "description": step.reasoning or "Residual-plan continuation was evaluated but skipped",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.PLAN_CONTINUATION_INJECTED:
            return {
                "title": "延续注入 / Continuation Injected",
                "description": step.reasoning or "Residual-plan continuation guidance was injected into tool selection",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.PARAMETER_NEGOTIATION_REQUIRED:
            return {
                "title": "参数协商触发 / Parameter Negotiation Required",
                "description": step.reasoning or "Execution stopped for bounded parameter confirmation",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.PARAMETER_NEGOTIATION_CONFIRMED:
            return {
                "title": "参数确认 / Parameter Negotiation Confirmed",
                "description": step.reasoning or "A candidate value was confirmed and locked",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.PARAMETER_NEGOTIATION_REJECTED:
            return {
                "title": "参数拒绝 / Parameter Negotiation Rejected",
                "description": step.reasoning or "The candidate set was rejected or superseded",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.PARAMETER_NEGOTIATION_FAILED:
            return {
                "title": "参数协商失败 / Parameter Negotiation Failed",
                "description": step.reasoning or "The confirmation reply could not be resolved",
                "status": "error",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.INPUT_COMPLETION_REQUIRED:
            return {
                "title": "输入补全触发 / Input Completion Required",
                "description": step.reasoning or "A repairable action entered bounded input completion.",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.INPUT_COMPLETION_CONFIRMED:
            return {
                "title": "输入补全确认 / Input Completion Confirmed",
                "description": step.reasoning or "A bounded completion decision was parsed successfully.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.INPUT_COMPLETION_REJECTED:
            return {
                "title": "输入补全拒绝 / Input Completion Rejected",
                "description": step.reasoning or "The active completion flow was rejected or superseded.",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.INPUT_COMPLETION_FAILED:
            return {
                "title": "输入补全失败 / Input Completion Failed",
                "description": step.reasoning or "The completion reply could not be resolved into a valid bounded decision.",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.INPUT_COMPLETION_APPLIED:
            return {
                "title": "输入补全应用 / Input Completion Applied",
                "description": step.reasoning or "The completion override was written into execution state.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.INPUT_COMPLETION_PAUSED:
            return {
                "title": "输入补全暂停 / Input Completion Paused",
                "description": step.reasoning or "The active completion flow was paused explicitly.",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.GEOMETRY_COMPLETION_ATTACHED:
            return {
                "title": "空间补救附加 / Geometry Support Attached",
                "description": step.reasoning or "A supporting spatial file was attached through bounded input completion.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.GEOMETRY_RE_GROUNDING_TRIGGERED:
            return {
                "title": "空间重锚触发 / Geometry Re-Grounding Triggered",
                "description": step.reasoning or "Bounded re-grounding started with the primary file plus a supporting spatial file.",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.GEOMETRY_RE_GROUNDING_APPLIED:
            return {
                "title": "空间重锚应用 / Geometry Re-Grounding Applied",
                "description": step.reasoning or "Supporting spatial facts were merged into the current task context.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.GEOMETRY_RE_GROUNDING_FAILED:
            return {
                "title": "空间重锚失败 / Geometry Re-Grounding Failed",
                "description": step.reasoning or step.error or "The supporting file did not enable bounded geometry recovery.",
                "status": "error",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.GEOMETRY_READINESS_REFRESHED:
            return {
                "title": "空间就绪刷新 / Geometry Readiness Refreshed",
                "description": step.reasoning or "Readiness was refreshed after bounded geometry remediation.",
                "status": "success" if (step.output_summary or {}).get("after_status") == "ready" else "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.GEOMETRY_RECOVERY_RESUMED:
            return {
                "title": "空间恢复可续 / Geometry Recovery Resumable",
                "description": step.reasoning or "The repaired workflow became resumable without auto-executing downstream tools.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.RESIDUAL_REENTRY_TARGET_SET:
            return {
                "title": "恢复回入口设定 / Re-entry Target Set",
                "description": step.reasoning or "A formal recovered-workflow re-entry target was set after remediation.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.RESIDUAL_REENTRY_DECIDED:
            return {
                "title": "恢复回入口决策 / Re-entry Decision",
                "description": step.reasoning or "The controller decided whether to bias this turn toward the recovered target.",
                "status": "success" if (step.output_summary or {}).get("should_apply") else "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.RESIDUAL_REENTRY_INJECTED:
            return {
                "title": "恢复回入口注入 / Re-entry Guidance Injected",
                "description": step.reasoning or "Recovered-workflow re-entry guidance was injected into the next-turn tool selection context.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.RESIDUAL_REENTRY_SKIPPED:
            return {
                "title": "恢复回入口跳过 / Re-entry Skipped",
                "description": step.reasoning or "Recovered-workflow re-entry bias was evaluated but skipped for this turn.",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.REMEDIATION_POLICY_OPTION_OFFERED:
            return {
                "title": "策略补救选项 / Remediation Policy Offered",
                "description": step.reasoning or "A bounded remediation policy option was offered in the completion flow.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.REMEDIATION_POLICY_CONFIRMED:
            return {
                "title": "策略补救确认 / Remediation Policy Confirmed",
                "description": step.reasoning or "The user confirmed a remediation policy for missing-field recovery.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.REMEDIATION_POLICY_APPLIED:
            return {
                "title": "策略补救应用 / Remediation Policy Applied",
                "description": step.reasoning or "Remediation policy was applied and field-level overrides were written.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.REMEDIATION_POLICY_FAILED:
            return {
                "title": "策略补救失败 / Remediation Policy Failed",
                "description": step.reasoning or step.error or "Remediation policy application failed.",
                "status": "error",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.PARAMETER_STANDARDIZATION:
            desc = step.reasoning or "Parameters checked"
            if step.standardization_records:
                lines = []
                for rec in step.standardization_records:
                    record_type = rec.get("record_type")
                    if record_type == "cross_constraint_violation":
                        lines.append(
                            f"{rec.get('param', '?')}: incompatible ({rec.get('reason', 'cross constraint violation')})"
                        )
                        continue
                    if record_type == "cross_constraint_warning":
                        lines.append(
                            f"{rec.get('param', '?')}: warning ({rec.get('reason', 'cross constraint warning')})"
                        )
                        continue

                    param = rec.get("param", "?")
                    original = rec.get("original", "?")
                    normalized = rec.get("normalized", original)
                    strategy = rec.get("strategy", "?")
                    conf = rec.get("confidence", 0)
                    if original != normalized:
                        lines.append(f"{param}: {original} → {normalized}  ({strategy} · {conf:.2f})")
                    else:
                        lines.append(f"{param}: {original} ✓  ({strategy} · {conf:.2f})")
                desc = "\n".join(lines)

            return {
                "title": "参数标准化 / Parameter Standardization",
                "description": desc,
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.CROSS_CONSTRAINT_VALIDATED:
            return {
                "title": "交叉约束校验 / Cross-Constraint Validation",
                "description": step.reasoning or "Cross-parameter constraints were evaluated.",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.CROSS_CONSTRAINT_VIOLATION:
            return {
                "title": "交叉约束冲突 / Cross-Constraint Violation",
                "description": step.reasoning or step.error or "A cross-parameter constraint was violated.",
                "status": "error",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.CROSS_CONSTRAINT_WARNING:
            return {
                "title": "交叉约束警告 / Cross-Constraint Warning",
                "description": step.reasoning or "A cross-parameter compatibility warning was recorded.",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.TOOL_EXECUTION:
            tool = step.action or "unknown"
            success = step.error is None
            duration = f"{step.duration_ms:.0f}ms" if step.duration_ms else ""

            if success:
                parts = [f"{tool} completed"]
                if duration:
                    parts[0] += f" ({duration})"
                if step.output_summary:
                    if step.output_summary.get("total_links"):
                        parts.append(f"{step.output_summary['total_links']} links processed")
                    if step.output_summary.get("pollutants"):
                        parts.append(f"pollutants: {', '.join(step.output_summary['pollutants'])}")
                    if step.output_summary.get("data_points"):
                        parts.append(f"{step.output_summary['data_points']} data points")
                desc = " · ".join(parts)
                return {
                    "title": f"计算执行 / {tool}",
                    "description": desc,
                    "status": "success",
                    "step_type": step.step_type.value,
                }
            else:
                return {
                    "title": f"执行失败 / {tool} Failed",
                    "description": step.error or "Execution error",
                    "status": "error",
                    "step_type": step.step_type.value,
                }

        elif step.step_type == TraceStepType.SYNTHESIS:
            return {
                "title": "结果合成 / Result Synthesis",
                "description": step.reasoning or "Analysis report generated",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.REPLY_GENERATION:
            return {
                "title": "回复生成 / Reply Generation",
                "description": step.reasoning or "Final reply generated",
                "status": "warning" if step.output_summary and step.output_summary.get("fallback") else "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.CLARIFICATION:
            return {
                "title": "需要确认 / Clarification Needed",
                "description": step.reasoning or "More information needed",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.ERROR:
            return {
                "title": "错误 / Error",
                "description": step.error or "An error occurred",
                "status": "error",
                "step_type": step.step_type.value,
            }

        return None
