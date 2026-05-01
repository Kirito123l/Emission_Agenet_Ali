from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from core.geometry_recovery import (
    GeometryRecoveryContext,
    SupportingSpatialInput,
)
from core.file_relationship_resolution import (
    FileRelationshipDecision,
    FileRelationshipFileSummary,
    FileRelationshipTransitionPlan,
)
from core.artifact_memory import ArtifactMemoryState
from core.input_completion import (
    InputCompletionDecision,
    InputCompletionRequest,
)
from core.intent_resolution import (
    IntentResolutionApplicationPlan,
    IntentResolutionDecision,
)
from core.parameter_negotiation import (
    ParameterNegotiationDecision,
    ParameterNegotiationRequest,
)
from core.plan import ExecutionPlan, PlanStep, PlanStepStatus
from core.plan_repair import PlanRepairDecision
from core.residual_reentry import RecoveredWorkflowReentryContext
from core.supplemental_merge import (
    SupplementalMergePlan,
    SupplementalMergeResult,
)
from core.summary_delivery import (
    SummaryDeliveryPlan,
    SummaryDeliveryResult,
)
from core.workflow_templates import (
    TemplateRecommendation,
    TemplateSelectionResult,
    WorkflowTemplate,
)


class TaskStage(str, Enum):
    INPUT_RECEIVED = "INPUT_RECEIVED"
    GROUNDED = "GROUNDED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    NEEDS_PARAMETER_CONFIRMATION = "NEEDS_PARAMETER_CONFIRMATION"
    NEEDS_INPUT_COMPLETION = "NEEDS_INPUT_COMPLETION"
    EXECUTING = "EXECUTING"
    DONE = "DONE"


class ParamStatus(str, Enum):
    OK = "OK"
    PENDING = "PENDING"
    MISSING = "MISSING"
    AMBIGUOUS = "AMBIGUOUS"


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        if hasattr(value, "to_dict"):
            return value.to_dict()
        return {
            item.name: _serialize_value(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, dict):
        return {key: _serialize_value(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    return value


@dataclass
class ParamEntry:
    raw: Optional[str] = None
    normalized: Optional[str] = None
    status: ParamStatus = ParamStatus.MISSING
    confidence: Optional[float] = None
    strategy: Optional[str] = None  # exact / alias / fuzzy / abstain
    locked: bool = False
    lock_source: Optional[str] = None
    confirmation_request_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw": self.raw,
            "normalized": self.normalized,
            "status": self.status.value,
            "confidence": self.confidence,
            "strategy": self.strategy,
            "locked": self.locked,
            "lock_source": self.lock_source,
            "confirmation_request_id": self.confirmation_request_id,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ParamEntry":
        payload = data if isinstance(data, dict) else {}
        status_value = payload.get("status", ParamStatus.MISSING.value)
        try:
            status = ParamStatus(status_value)
        except Exception:
            status = ParamStatus.MISSING
        return cls(
            raw=str(payload.get("raw")).strip() if payload.get("raw") is not None else None,
            normalized=(
                str(payload.get("normalized")).strip()
                if payload.get("normalized") is not None
                else None
            ),
            status=status,
            confidence=(
                float(payload["confidence"])
                if payload.get("confidence") is not None
                else None
            ),
            strategy=str(payload.get("strategy")).strip() if payload.get("strategy") is not None else None,
            locked=bool(payload.get("locked", False)),
            lock_source=(
                str(payload.get("lock_source")).strip()
                if payload.get("lock_source") is not None
                else None
            ),
            confirmation_request_id=(
                str(payload.get("confirmation_request_id")).strip()
                if payload.get("confirmation_request_id") is not None
                else None
            ),
        )


@dataclass
class GeometryMetadata:
    """Deterministic geometry-capability metadata extracted from file analysis.

    Captures what spatial information is available in an uploaded file without
    executing any tool or synthesizing geometry.  Every field is backed by
    column-name or sample-value evidence.
    """

    geometry_available: bool = False
    road_geometry_available: bool = False
    point_geometry_available: bool = False
    line_geometry_constructible: bool = False
    geometry_type: str = "none"
    geometry_columns: List[str] = field(default_factory=list)
    coordinate_columns: Dict[str, Optional[str]] = field(default_factory=dict)
    join_key_columns: Dict[str, Optional[str]] = field(default_factory=dict)
    confidence: float = 0.0
    evidence: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "geometry_available": self.geometry_available,
            "road_geometry_available": self.road_geometry_available,
            "point_geometry_available": self.point_geometry_available,
            "line_geometry_constructible": self.line_geometry_constructible,
            "geometry_type": self.geometry_type,
            "geometry_columns": list(self.geometry_columns),
            "coordinate_columns": dict(self.coordinate_columns),
            "join_key_columns": dict(self.join_key_columns),
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "GeometryMetadata":
        if not isinstance(data, dict):
            return cls()
        return cls(
            geometry_available=bool(data.get("geometry_available", False)),
            road_geometry_available=bool(data.get("road_geometry_available", False)),
            point_geometry_available=bool(data.get("point_geometry_available", False)),
            line_geometry_constructible=bool(data.get("line_geometry_constructible", False)),
            geometry_type=str(data.get("geometry_type", "none")),
            geometry_columns=[str(item) for item in (data.get("geometry_columns") or [])],
            coordinate_columns={
                str(k): (str(v) if v is not None else None)
                for k, v in (data.get("coordinate_columns") or {}).items()
            },
            join_key_columns={
                str(k): (str(v) if v is not None else None)
                for k, v in (data.get("join_key_columns") or {}).items()
            },
            confidence=float(data.get("confidence", 0.0)),
            evidence=[str(item) for item in (data.get("evidence") or [])],
            limitations=[str(item) for item in (data.get("limitations") or [])],
        )


@dataclass
class FileContext:
    has_file: bool = False
    file_path: Optional[str] = None
    grounded: bool = False
    task_type: Optional[str] = None
    confidence: Optional[float] = None
    column_mapping: Dict[str, Any] = field(default_factory=dict)
    evidence: List[str] = field(default_factory=list)
    row_count: Optional[int] = None
    columns: List[str] = field(default_factory=list)
    sample_rows: Optional[List[Dict]] = None
    micro_mapping: Optional[Dict] = None
    macro_mapping: Optional[Dict] = None
    micro_has_required: Optional[bool] = None
    macro_has_required: Optional[bool] = None
    selected_primary_table: Optional[str] = None
    dataset_roles: List[Dict[str, Any]] = field(default_factory=list)
    spatial_metadata: Dict[str, Any] = field(default_factory=dict)
    missing_field_diagnostics: Dict[str, Any] = field(default_factory=dict)
    spatial_context: Dict[str, Any] = field(default_factory=dict)
    geometry_metadata: GeometryMetadata = field(default_factory=GeometryMetadata)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_file": self.has_file,
            "file_path": self.file_path,
            "grounded": self.grounded,
            "task_type": self.task_type,
            "confidence": self.confidence,
            "column_mapping": _serialize_value(self.column_mapping),
            "evidence": list(self.evidence),
            "row_count": self.row_count,
            "columns": list(self.columns),
            "sample_rows": _serialize_value(self.sample_rows),
            "micro_mapping": _serialize_value(self.micro_mapping),
            "macro_mapping": _serialize_value(self.macro_mapping),
            "micro_has_required": self.micro_has_required,
            "macro_has_required": self.macro_has_required,
            "selected_primary_table": self.selected_primary_table,
            "dataset_roles": _serialize_value(self.dataset_roles),
            "spatial_metadata": _serialize_value(self.spatial_metadata),
            "missing_field_diagnostics": _serialize_value(self.missing_field_diagnostics),
            "spatial_context": _serialize_value(self.spatial_context),
            "geometry_metadata": self.geometry_metadata.to_dict(),
        }


@dataclass
class ExecutionContext:
    selected_tool: Optional[str] = None
    completed_tools: List[str] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    last_error: Optional[str] = None
    available_results: Set[str] = field(default_factory=set)
    blocked_info: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_tool": self.selected_tool,
            "completed_tools": list(self.completed_tools),
            "tool_results": _serialize_value(self.tool_results),
            "last_error": self.last_error,
            "available_results": sorted(self.available_results),
            "blocked_info": _serialize_value(self.blocked_info),
        }


@dataclass
class ControlState:
    steps_taken: int = 0
    max_steps: int = 4
    needs_user_input: bool = False
    clarification_question: Optional[str] = None
    parameter_confirmation_prompt: Optional[str] = None
    input_completion_prompt: Optional[str] = None
    stop_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "steps_taken": self.steps_taken,
            "max_steps": self.max_steps,
            "needs_user_input": self.needs_user_input,
            "clarification_question": self.clarification_question,
            "parameter_confirmation_prompt": self.parameter_confirmation_prompt,
            "input_completion_prompt": self.input_completion_prompt,
            "stop_reason": self.stop_reason,
        }


@dataclass
class ContinuationDecision:
    residual_plan_exists: bool = False
    continuation_ready: bool = False
    should_continue: bool = False
    should_replan: bool = False
    prompt_variant: Optional[str] = None
    signal: Optional[str] = None
    reason: Optional[str] = None
    new_task_override: bool = False
    next_step_id: Optional[str] = None
    next_tool_name: Optional[str] = None
    latest_repair_summary: Optional[str] = None
    residual_plan_summary: Optional[str] = None
    latest_blocked_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "residual_plan_exists": self.residual_plan_exists,
            "continuation_ready": self.continuation_ready,
            "should_continue": self.should_continue,
            "should_replan": self.should_replan,
            "prompt_variant": self.prompt_variant,
            "signal": self.signal,
            "reason": self.reason,
            "new_task_override": self.new_task_override,
            "next_step_id": self.next_step_id,
            "next_tool_name": self.next_tool_name,
            "latest_repair_summary": self.latest_repair_summary,
            "residual_plan_summary": self.residual_plan_summary,
            "latest_blocked_reason": self.latest_blocked_reason,
        }


@dataclass
class TaskState:
    stage: TaskStage = TaskStage.INPUT_RECEIVED
    file_context: FileContext = field(default_factory=FileContext)
    parameters: Dict[str, ParamEntry] = field(default_factory=dict)
    execution: ExecutionContext = field(default_factory=ExecutionContext)
    control: ControlState = field(default_factory=ControlState)
    plan: Optional[ExecutionPlan] = None
    repair_history: List[PlanRepairDecision] = field(default_factory=list)
    continuation: Optional[ContinuationDecision] = None
    recommended_workflow_templates: List[TemplateRecommendation] = field(default_factory=list)
    selected_workflow_template: Optional[WorkflowTemplate] = None
    template_prior_used: bool = False
    template_selection_reason: Optional[str] = None
    active_parameter_negotiation: Optional[ParameterNegotiationRequest] = None
    latest_parameter_negotiation_decision: Optional[ParameterNegotiationDecision] = None
    active_input_completion: Optional[InputCompletionRequest] = None
    latest_input_completion_decision: Optional[InputCompletionDecision] = None
    input_completion_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    supporting_spatial_input: Optional[SupportingSpatialInput] = None
    geometry_recovery_context: Optional[GeometryRecoveryContext] = None
    geometry_readiness_refresh_result: Optional[Dict[str, Any]] = None
    residual_reentry_context: Optional[RecoveredWorkflowReentryContext] = None
    reentry_bias_applied: bool = False
    incoming_file_path: Optional[str] = None
    latest_file_relationship_decision: Optional[FileRelationshipDecision] = None
    latest_file_relationship_transition: Optional[FileRelationshipTransitionPlan] = None
    pending_file_relationship_upload: Optional[FileRelationshipFileSummary] = None
    attached_supporting_file: Optional[FileRelationshipFileSummary] = None
    awaiting_file_relationship_clarification: bool = False
    latest_supplemental_merge_plan: Optional[SupplementalMergePlan] = None
    latest_supplemental_merge_result: Optional[SupplementalMergeResult] = None
    latest_intent_resolution_decision: Optional[IntentResolutionDecision] = None
    latest_intent_resolution_plan: Optional[IntentResolutionApplicationPlan] = None
    latest_summary_delivery_plan: Optional[SummaryDeliveryPlan] = None
    latest_summary_delivery_result: Optional[SummaryDeliveryResult] = None
    artifact_memory_state: ArtifactMemoryState = field(default_factory=ArtifactMemoryState)
    session_id: Optional[str] = None
    user_message: Optional[str] = None
    _llm_response: Optional[Any] = field(default=None, repr=False)

    @classmethod
    def initialize(
        cls,
        user_message: Optional[str],
        file_path: Optional[str],
        memory_dict: Optional[Dict[str, Any]],
        session_id: Optional[str],
    ) -> TaskState:
        state = cls(
            session_id=session_id,
            user_message=user_message,
            incoming_file_path=str(file_path) if file_path else None,
        )

        if file_path:
            state.file_context.has_file = True
            state.file_context.file_path = str(file_path)

        memory_dict = memory_dict or {}

        recent_vehicle = memory_dict.get("recent_vehicle")
        if recent_vehicle:
            vehicle_value = str(recent_vehicle)
            state.parameters["vehicle_type"] = ParamEntry(
                raw=vehicle_value,
                normalized=vehicle_value,
                status=ParamStatus.OK,
                confidence=1.0,
                strategy="exact",
            )

        recent_pollutants = memory_dict.get("recent_pollutants") or []
        if recent_pollutants:
            pollutant_value = ", ".join(str(item) for item in recent_pollutants)
            state.parameters["pollutants"] = ParamEntry(
                raw=pollutant_value,
                normalized=pollutant_value,
                status=ParamStatus.OK,
                confidence=1.0,
                strategy="exact",
            )

        recent_year = memory_dict.get("recent_year")
        if recent_year is not None:
            year_value = str(recent_year)
            state.parameters["model_year"] = ParamEntry(
                raw=year_value,
                normalized=year_value,
                status=ParamStatus.OK,
                confidence=1.0,
                strategy="exact",
            )

        if not file_path:
            active_file = memory_dict.get("active_file")
            file_analysis = memory_dict.get("file_analysis")
            if active_file:
                state.file_context.has_file = True
                state.file_context.file_path = str(active_file)
                if isinstance(file_analysis, dict):
                    state.update_file_context(file_analysis)
                    setattr(state, "_file_analysis_cache", dict(file_analysis))
                    if isinstance(file_analysis.get("supplemental_merge_plan"), dict):
                        state.set_latest_supplemental_merge_plan(
                            SupplementalMergePlan.from_dict(file_analysis.get("supplemental_merge_plan"))
                        )
                    if isinstance(file_analysis.get("supplemental_merge_result"), dict):
                        state.set_latest_supplemental_merge_result(
                            SupplementalMergeResult.from_dict(file_analysis.get("supplemental_merge_result"))
                        )
                    if isinstance(file_analysis.get("latest_intent_resolution_decision"), dict):
                        state.set_latest_intent_resolution_decision(
                            IntentResolutionDecision.from_dict(
                                file_analysis.get("latest_intent_resolution_decision")
                            )
                        )
                    if isinstance(file_analysis.get("latest_intent_resolution_plan"), dict):
                        state.set_latest_intent_resolution_plan(
                            IntentResolutionApplicationPlan.from_dict(
                                file_analysis.get("latest_intent_resolution_plan")
                            )
                        )
                    if isinstance(file_analysis.get("artifact_memory"), dict):
                        state.set_artifact_memory_state(
                            ArtifactMemoryState.from_dict(file_analysis.get("artifact_memory"))
                        )
                    if isinstance(file_analysis.get("latest_summary_delivery_plan"), dict):
                        state.set_latest_summary_delivery_plan(
                            SummaryDeliveryPlan.from_dict(file_analysis.get("latest_summary_delivery_plan"))
                        )
                    if isinstance(file_analysis.get("latest_summary_delivery_result"), dict):
                        state.set_latest_summary_delivery_result(
                            SummaryDeliveryResult.from_dict(file_analysis.get("latest_summary_delivery_result"))
                        )

        return state

    def transition(self, new_stage: TaskStage, reason: str = "") -> None:
        valid_targets = self._valid_transitions()
        if new_stage not in valid_targets:
            raise ValueError(f"Invalid transition: {self.stage.value} -> {new_stage.value}")
        self.stage = new_stage
        self.control.steps_taken += 1
        if reason:
            self.control.stop_reason = reason

    def _valid_transitions(self) -> List[TaskStage]:
        transition_map = {
            TaskStage.INPUT_RECEIVED: [
                TaskStage.GROUNDED,
                TaskStage.NEEDS_CLARIFICATION,
                TaskStage.NEEDS_PARAMETER_CONFIRMATION,
                TaskStage.NEEDS_INPUT_COMPLETION,
                TaskStage.DONE,
            ],
            TaskStage.GROUNDED: [
                TaskStage.EXECUTING,
                TaskStage.NEEDS_CLARIFICATION,
                TaskStage.DONE,
            ],
            TaskStage.NEEDS_CLARIFICATION: [],
            TaskStage.NEEDS_PARAMETER_CONFIRMATION: [],
            TaskStage.NEEDS_INPUT_COMPLETION: [],
            TaskStage.EXECUTING: [
                TaskStage.DONE,
                TaskStage.NEEDS_CLARIFICATION,
                TaskStage.NEEDS_PARAMETER_CONFIRMATION,
                TaskStage.NEEDS_INPUT_COMPLETION,
            ],
            TaskStage.DONE: [],
        }
        return transition_map[self.stage]

    def is_terminal(self) -> bool:
        return self.stage in {
            TaskStage.DONE,
            TaskStage.NEEDS_CLARIFICATION,
            TaskStage.NEEDS_PARAMETER_CONFIRMATION,
            TaskStage.NEEDS_INPUT_COMPLETION,
        }

    def should_stop(self) -> bool:
        return self.is_terminal() or self.control.steps_taken >= self.control.max_steps

    def to_dict(self) -> Dict[str, Any]:
        next_planned_step = self.get_next_planned_step()
        latest_repair_summary = self.get_latest_repair_summary()
        residual_plan_summary = self.get_residual_plan_summary()
        return {
            "stage": self.stage.value,
            "file_context": self.file_context.to_dict(),
            "parameters": {
                key: value.to_dict()
                for key, value in self.parameters.items()
            },
            "execution": self.execution.to_dict(),
            "control": self.control.to_dict(),
            "plan": self.plan.to_dict() if self.plan else None,
            "next_planned_step": next_planned_step.to_dict() if next_planned_step else None,
            "repair_history": [decision.to_dict() for decision in self.repair_history],
            "continuation": self.continuation.to_dict() if self.continuation else None,
            "recommended_workflow_templates": [
                recommendation.to_dict()
                for recommendation in self.recommended_workflow_templates
            ],
            "selected_workflow_template": (
                self.selected_workflow_template.to_dict()
                if self.selected_workflow_template
                else None
            ),
            "template_prior_used": self.template_prior_used,
            "template_selection_reason": self.template_selection_reason,
            "active_parameter_negotiation": (
                self.active_parameter_negotiation.to_dict()
                if self.active_parameter_negotiation
                else None
            ),
            "has_active_parameter_negotiation": self.active_parameter_negotiation is not None,
            "active_input_completion": (
                self.active_input_completion.to_dict()
                if self.active_input_completion
                else None
            ),
            "has_active_input_completion": self.active_input_completion is not None,
            "parameter_locks": self.get_parameter_locks_summary(),
            "latest_confirmed_parameter": (
                self.latest_parameter_negotiation_decision.to_dict()
                if self.latest_parameter_negotiation_decision
                else None
            ),
            "input_completion_overrides": self.get_input_completion_overrides_summary(),
            "latest_input_completion_decision": (
                self.latest_input_completion_decision.to_dict()
                if self.latest_input_completion_decision
                else None
            ),
            "supporting_spatial_input_summary": self.get_supporting_spatial_input_summary(),
            "geometry_recovery_context_summary": self.get_geometry_recovery_context_summary(),
            "geometry_recovery_status": self.get_geometry_recovery_status(),
            "geometry_readiness_refresh_result": (
                dict(self.geometry_readiness_refresh_result)
                if isinstance(self.geometry_readiness_refresh_result, dict)
                else None
            ),
            "reentry_target_summary": self.get_reentry_target_summary(),
            "reentry_status": self.get_reentry_status(),
            "reentry_source": self.get_reentry_source(),
            "reentry_guidance_summary": self.get_reentry_guidance_summary(),
            "reentry_bias_applied": self.reentry_bias_applied,
            "residual_reentry_context_summary": self.get_residual_reentry_context_summary(),
            "incoming_file_path": self.incoming_file_path,
            "latest_file_relationship_decision": (
                self.latest_file_relationship_decision.to_dict()
                if self.latest_file_relationship_decision is not None
                else None
            ),
            "latest_file_relationship_transition": (
                self.latest_file_relationship_transition.to_dict()
                if self.latest_file_relationship_transition is not None
                else None
            ),
            "pending_file_relationship_upload": (
                self.pending_file_relationship_upload.to_dict()
                if self.pending_file_relationship_upload is not None
                else None
            ),
            "attached_supporting_file": (
                self.attached_supporting_file.to_dict()
                if self.attached_supporting_file is not None
                else None
            ),
            "awaiting_file_relationship_clarification": self.awaiting_file_relationship_clarification,
            "latest_supplemental_merge_plan": (
                self.latest_supplemental_merge_plan.to_dict()
                if self.latest_supplemental_merge_plan is not None
                else None
            ),
            "latest_supplemental_merge_result": (
                self.latest_supplemental_merge_result.to_dict()
                if self.latest_supplemental_merge_result is not None
                else None
            ),
            "latest_intent_resolution_decision": (
                self.latest_intent_resolution_decision.to_dict()
                if self.latest_intent_resolution_decision is not None
                else None
            ),
            "latest_intent_resolution_plan": (
                self.latest_intent_resolution_plan.to_dict()
                if self.latest_intent_resolution_plan is not None
                else None
            ),
            "latest_summary_delivery_plan": (
                self.latest_summary_delivery_plan.to_dict()
                if self.latest_summary_delivery_plan is not None
                else None
            ),
            "latest_summary_delivery_result": (
                self.latest_summary_delivery_result.to_dict()
                if self.latest_summary_delivery_result is not None
                else None
            ),
            "artifact_memory": self.artifact_memory_state.to_dict(),
            "artifact_memory_summary": self.get_artifact_memory_summary(),
            "latest_artifact_by_family": self.get_latest_artifact_by_family(),
            "latest_artifact_by_type": self.get_latest_artifact_by_type(),
            "recent_delivery_summary": self.get_recent_delivery_summary(),
            "continuation_ready": self.continuation.continuation_ready if self.continuation else False,
            "continuation_reason": self.continuation.reason if self.continuation else None,
            "latest_repair_summary": (
                self.continuation.latest_repair_summary
                if self.continuation and self.continuation.latest_repair_summary
                else latest_repair_summary
            ),
            "residual_plan_summary": (
                self.continuation.residual_plan_summary
                if self.continuation and self.continuation.residual_plan_summary
                else residual_plan_summary
            ),
            "session_id": self.session_id,
            "user_message": self.user_message,
        }

    def set_plan(self, plan: Optional[ExecutionPlan]) -> None:
        self.plan = plan

    def get_next_planned_step(self) -> Optional[PlanStep]:
        if self.plan is None:
            return None
        return self.plan.get_next_pending_step()

    def update_plan_step_status(
        self,
        *,
        step_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        status: PlanStepStatus,
        note: Optional[str] = None,
        reconciliation_note: Optional[str] = None,
        blocked_reason: Optional[str] = None,
    ) -> Optional[PlanStep]:
        if self.plan is None:
            return None
        return self.plan.mark_step_status(
            step_id=step_id,
            tool_name=tool_name,
            status=status,
            note=note,
            reconciliation_note=reconciliation_note,
            blocked_reason=blocked_reason,
        )

    def append_plan_note(
        self,
        note: Optional[str],
        *,
        step_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        reconciliation: bool = False,
    ) -> Optional[PlanStep]:
        if self.plan is None:
            return None
        text = str(note).strip() if note is not None else ""
        if not text:
            return None
        if step_id or tool_name:
            step = self.plan.get_step(step_id=step_id, tool_name=tool_name)
            if step is None:
                return None
            target = step.reconciliation_notes if reconciliation else step.validation_notes
            if text not in target:
                target.append(text)
            return step
        if reconciliation:
            self.plan.append_reconciliation_note(text)
        else:
            self.plan.append_validation_note(text)
        return None

    def record_plan_repair(self, decision: PlanRepairDecision) -> None:
        self.repair_history.append(decision)

    def set_continuation_decision(self, decision: Optional[ContinuationDecision]) -> None:
        self.continuation = decision

    def set_workflow_template_selection(
        self,
        selection: Optional[TemplateSelectionResult],
    ) -> None:
        if selection is None:
            self.recommended_workflow_templates = []
            self.selected_workflow_template = None
            self.template_prior_used = False
            self.template_selection_reason = None
            return
        self.recommended_workflow_templates = list(selection.recommendations)
        self.selected_workflow_template = selection.selected_template
        self.template_prior_used = selection.template_prior_used
        self.template_selection_reason = selection.selection_reason

    def set_active_parameter_negotiation(
        self,
        request: Optional[ParameterNegotiationRequest],
    ) -> None:
        self.active_parameter_negotiation = request

    def set_latest_parameter_negotiation_decision(
        self,
        decision: Optional[ParameterNegotiationDecision],
    ) -> None:
        self.latest_parameter_negotiation_decision = decision

    def set_active_input_completion(
        self,
        request: Optional[InputCompletionRequest],
    ) -> None:
        self.active_input_completion = request

    def set_latest_input_completion_decision(
        self,
        decision: Optional[InputCompletionDecision],
    ) -> None:
        self.latest_input_completion_decision = decision

    def apply_input_completion_override(
        self,
        *,
        key: str,
        override: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized = dict(override or {})
        self.input_completion_overrides[key] = normalized
        return normalized

    def get_input_completion_overrides_summary(self) -> Dict[str, Dict[str, Any]]:
        return {
            key: dict(value)
            for key, value in self.input_completion_overrides.items()
            if isinstance(value, dict)
        }

    def set_supporting_spatial_input(
        self,
        supporting_spatial_input: Optional[SupportingSpatialInput],
    ) -> None:
        self.supporting_spatial_input = supporting_spatial_input

    def set_geometry_recovery_context(
        self,
        geometry_recovery_context: Optional[GeometryRecoveryContext],
    ) -> None:
        self.geometry_recovery_context = geometry_recovery_context

    def set_geometry_readiness_refresh_result(
        self,
        readiness_refresh_result: Optional[Dict[str, Any]],
    ) -> None:
        self.geometry_readiness_refresh_result = (
            dict(readiness_refresh_result)
            if isinstance(readiness_refresh_result, dict)
            else None
        )

    def set_residual_reentry_context(
        self,
        residual_reentry_context: Optional[RecoveredWorkflowReentryContext],
    ) -> None:
        self.residual_reentry_context = residual_reentry_context

    def set_reentry_bias_applied(self, applied: bool) -> None:
        self.reentry_bias_applied = bool(applied)

    def set_latest_file_relationship_decision(
        self,
        decision: Optional[FileRelationshipDecision],
    ) -> None:
        self.latest_file_relationship_decision = decision

    def set_latest_file_relationship_transition(
        self,
        transition: Optional[FileRelationshipTransitionPlan],
    ) -> None:
        self.latest_file_relationship_transition = transition

    def set_pending_file_relationship_upload(
        self,
        summary: Optional[FileRelationshipFileSummary],
    ) -> None:
        self.pending_file_relationship_upload = summary

    def set_attached_supporting_file(
        self,
        summary: Optional[FileRelationshipFileSummary],
    ) -> None:
        self.attached_supporting_file = summary

    def set_awaiting_file_relationship_clarification(
        self,
        awaiting: bool,
    ) -> None:
        self.awaiting_file_relationship_clarification = bool(awaiting)

    def set_latest_supplemental_merge_plan(
        self,
        plan: Optional[SupplementalMergePlan],
    ) -> None:
        self.latest_supplemental_merge_plan = plan

    def set_latest_supplemental_merge_result(
        self,
        result: Optional[SupplementalMergeResult],
    ) -> None:
        self.latest_supplemental_merge_result = result

    def set_latest_intent_resolution_decision(
        self,
        decision: Optional[IntentResolutionDecision],
    ) -> None:
        self.latest_intent_resolution_decision = decision

    def set_latest_intent_resolution_plan(
        self,
        plan: Optional[IntentResolutionApplicationPlan],
    ) -> None:
        self.latest_intent_resolution_plan = plan

    def set_artifact_memory_state(
        self,
        artifact_memory_state: Optional[ArtifactMemoryState],
    ) -> None:
        self.artifact_memory_state = artifact_memory_state or ArtifactMemoryState()

    def set_latest_summary_delivery_plan(
        self,
        plan: Optional[SummaryDeliveryPlan],
    ) -> None:
        self.latest_summary_delivery_plan = plan

    def set_latest_summary_delivery_result(
        self,
        result: Optional[SummaryDeliveryResult],
    ) -> None:
        self.latest_summary_delivery_result = result

    def get_artifact_memory_summary(self) -> Dict[str, Any]:
        return self.artifact_memory_state.to_summary()

    def get_latest_artifact_by_family(self) -> Dict[str, Dict[str, Any]]:
        return {
            key: value.to_summary()
            for key, value in self.artifact_memory_state.latest_by_family.items()
        }

    def get_latest_artifact_by_type(self) -> Dict[str, Dict[str, Any]]:
        return {
            key: value.to_summary()
            for key, value in self.artifact_memory_state.latest_by_type.items()
        }

    def get_recent_delivery_summary(self) -> List[Dict[str, Any]]:
        return [dict(item) for item in self.artifact_memory_state.recent_artifact_summary]

    def get_supporting_spatial_input_summary(self) -> Optional[Dict[str, Any]]:
        if self.supporting_spatial_input is None:
            return None
        return self.supporting_spatial_input.to_summary()

    def get_geometry_recovery_context_summary(self) -> Optional[Dict[str, Any]]:
        if self.geometry_recovery_context is None:
            return None
        return self.geometry_recovery_context.to_summary()

    def get_geometry_recovery_status(self) -> Optional[str]:
        if self.geometry_recovery_context is None:
            return None
        return str(self.geometry_recovery_context.recovery_status or "").strip() or None

    def get_residual_reentry_context_summary(self) -> Optional[Dict[str, Any]]:
        if self.residual_reentry_context is None:
            return None
        return self.residual_reentry_context.to_summary()

    def get_reentry_target_summary(self) -> Optional[Dict[str, Any]]:
        if self.residual_reentry_context is None:
            return None
        return self.residual_reentry_context.reentry_target.to_summary()

    def get_reentry_status(self) -> Optional[str]:
        if self.residual_reentry_context is None:
            return None
        return str(self.residual_reentry_context.reentry_status or "").strip() or None

    def get_reentry_source(self) -> Optional[str]:
        if self.residual_reentry_context is None:
            return None
        return str(self.residual_reentry_context.reentry_target.source or "").strip() or None

    def get_reentry_guidance_summary(self) -> Optional[str]:
        if self.residual_reentry_context is None:
            return None
        return (
            str(self.residual_reentry_context.reentry_guidance_summary).strip()
            if self.residual_reentry_context.reentry_guidance_summary is not None
            else None
        )

    def apply_parameter_lock(
        self,
        *,
        parameter_name: str,
        normalized_value: str,
        raw_value: Optional[str] = None,
        request_id: Optional[str] = None,
        lock_source: str = "user_confirmation",
    ) -> ParamEntry:
        entry = self.parameters.get(parameter_name, ParamEntry())
        entry.raw = raw_value if raw_value is not None else (entry.raw or normalized_value)
        entry.normalized = normalized_value
        entry.status = ParamStatus.OK
        entry.confidence = 1.0
        entry.strategy = "user_confirmed"
        entry.locked = True
        entry.lock_source = lock_source
        entry.confirmation_request_id = request_id
        self.parameters[parameter_name] = entry
        return entry

    def get_parameter_locks_summary(self) -> Dict[str, Dict[str, Any]]:
        return {
            name: entry.to_dict()
            for name, entry in self.parameters.items()
            if entry.locked
        }

    def get_latest_repair_summary(self) -> Optional[str]:
        if self.repair_history:
            latest = self.repair_history[-1]
            note = str(latest.planner_notes or "").strip()
            if note:
                return f"{latest.action_type.value}: {note}"
            return latest.action_type.value
        if self.plan and self.plan.repair_notes:
            note = str(self.plan.repair_notes[-1]).strip()
            if note:
                return note
        return None

    def get_residual_plan_summary(self) -> Optional[str]:
        if self.continuation and self.continuation.residual_plan_summary:
            return self.continuation.residual_plan_summary
        if self.plan is None:
            return None
        pending_steps = self.plan.get_pending_steps()
        if not pending_steps:
            return None

        fragments: List[str] = [f"Goal: {self.plan.goal}"]
        next_step = pending_steps[0]
        fragments.append(f"Next: {next_step.step_id} -> {next_step.tool_name} [{next_step.status.value}]")
        for step in pending_steps[:3]:
            fragments.append(f"{step.step_id}:{step.tool_name}[{step.status.value}]")
        return " | ".join(fragments)

    def update_file_context(self, analysis_dict: Dict[str, Any]) -> None:
        if not isinstance(analysis_dict, dict):
            return

        if analysis_dict.get("file_path"):
            self.file_context.file_path = str(analysis_dict["file_path"])
        self.file_context.has_file = bool(self.file_context.file_path)
        self.file_context.task_type = analysis_dict.get("task_type")
        self.file_context.confidence = analysis_dict.get("confidence")
        self.file_context.columns = list(analysis_dict.get("columns") or [])
        self.file_context.row_count = analysis_dict.get("row_count")
        self.file_context.sample_rows = analysis_dict.get("sample_rows")
        self.file_context.micro_mapping = analysis_dict.get("micro_mapping")
        self.file_context.macro_mapping = analysis_dict.get("macro_mapping")
        self.file_context.micro_has_required = analysis_dict.get("micro_has_required")
        self.file_context.macro_has_required = analysis_dict.get("macro_has_required")
        self.file_context.selected_primary_table = (
            str(analysis_dict.get("selected_primary_table")).strip()
            if analysis_dict.get("selected_primary_table") is not None
            else None
        )
        self.file_context.dataset_roles = [
            dict(item)
            for item in (analysis_dict.get("dataset_roles") or [])
            if isinstance(item, dict)
        ]
        self.file_context.spatial_metadata = dict(analysis_dict.get("spatial_metadata") or {})
        self.file_context.missing_field_diagnostics = dict(analysis_dict.get("missing_field_diagnostics") or {})
        self.file_context.spatial_context = dict(analysis_dict.get("spatial_context") or {})
        self.file_context.geometry_metadata = GeometryMetadata.from_dict(
            analysis_dict.get("geometry_metadata")
        )
        self.file_context.column_mapping = {}
        if self.file_context.task_type == "micro_emission" and self.file_context.micro_mapping:
            self.file_context.column_mapping = dict(self.file_context.micro_mapping)
        elif self.file_context.task_type == "macro_emission" and self.file_context.macro_mapping:
            self.file_context.column_mapping = dict(self.file_context.macro_mapping)

        evidence = analysis_dict.get("evidence")
        if isinstance(evidence, list):
            self.file_context.evidence = [str(item) for item in evidence]
        else:
            derived_evidence: List[str] = []
            if self.file_context.task_type:
                derived_evidence.append(f"task_type={self.file_context.task_type}")
            if self.file_context.confidence is not None:
                derived_evidence.append(f"confidence={self.file_context.confidence}")
            self.file_context.evidence = derived_evidence
        self.file_context.grounded = True
