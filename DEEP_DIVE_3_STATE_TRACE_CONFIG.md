# DEEP_DIVE_3_STATE_TRACE_CONFIG

本文件仅描述当前代码现状，不包含建议。所有代码片段均为完整片段，未使用省略号。

## 1. TaskState 完整定义

对象定位：
- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py#L47) `TaskStage`，行 47-54
- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py#L57) `ParamStatus`，行 57-61
- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py#L82) `ParamEntry`，行 82-137
- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py#L141) `FileContext`，行 141-183
- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py#L187) `ExecutionContext`，行 187-203
- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py#L207) `ControlState`，行 207-225
- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py#L263) `TaskState`，行 263-971；其中 `transition()` 行 400-407，`_valid_transitions()` 行 409-434，`is_terminal()` 行 436-442，`apply_parameter_lock()` 行 869-888，`update_file_context()` 行 926-971。
- `TaskState` 其他 public 方法：`initialize()` 304-398、`should_stop()` 444-445、`to_dict()` 447-584、`set_plan()` 586-587、`get_next_planned_step()` 589-592、`update_plan_step_status()` 594-613、`append_plan_note()` 615-640、`record_plan_repair()` 642-643、`set_continuation_decision()` 645-646、`set_workflow_template_selection()` 648-661、`set_active_parameter_negotiation()` 663-667、`set_latest_parameter_negotiation_decision()` 669-673、`set_active_input_completion()` 675-679、`set_latest_input_completion_decision()` 681-685、`apply_input_completion_override()` 687-695、`get_input_completion_overrides_summary()` 697-702、`set_supporting_spatial_input()` 704-708、`set_geometry_recovery_context()` 710-714、`set_geometry_readiness_refresh_result()` 716-724、`set_residual_reentry_context()` 726-730、`set_reentry_bias_applied()` 732-733、`set_latest_file_relationship_decision()` 735-739、`set_latest_file_relationship_transition()` 741-745、`set_pending_file_relationship_upload()` 747-751、`set_attached_supporting_file()` 753-757、`set_awaiting_file_relationship_clarification()` 759-763、`set_latest_supplemental_merge_plan()` 765-769、`set_latest_supplemental_merge_result()` 771-775、`set_latest_intent_resolution_decision()` 777-781、`set_latest_intent_resolution_plan()` 783-787、`set_artifact_memory_state()` 789-793、`set_latest_summary_delivery_plan()` 795-799、`set_latest_summary_delivery_result()` 801-805、`get_artifact_memory_summary()` 807-808、`get_latest_artifact_by_family()` 810-814、`get_latest_artifact_by_type()` 816-820、`get_recent_delivery_summary()` 822-823、`get_supporting_spatial_input_summary()` 825-828、`get_geometry_recovery_context_summary()` 830-833、`get_geometry_recovery_status()` 835-838、`get_residual_reentry_context_summary()` 840-843、`get_reentry_target_summary()` 845-848、`get_reentry_status()` 850-853、`get_reentry_source()` 855-858、`get_reentry_guidance_summary()` 860-867、`get_parameter_locks_summary()` 890-895、`get_latest_repair_summary()` 897-908、`get_residual_plan_summary()` 910-924

完整文件：

```python
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
```
## 2. Trace 完整结构

对象定位：
- [core/trace.py](/home/kirito/Agent1/emission_agent/core/trace.py#L16) `TraceStepType`，行 16-108。
- [core/trace.py](/home/kirito/Agent1/emission_agent/core/trace.py#L112) `TraceStep`，行 112-149。
- [core/trace.py](/home/kirito/Agent1/emission_agent/core/trace.py#L153) `Trace`，行 153-1031；包含 `start()` 164-169、`record()` 171-202、`finish()` 204-214、`to_dict()` 216-226、`to_user_friendly()` 228-239、`_format_step_friendly()` 241-1031。

完整文件：

```python
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
    TOOL_SELECTION = "tool_selection"
    TOOL_EXECUTION = "tool_execution"
    STATE_TRANSITION = "state_transition"
    CLARIFICATION = "clarification"
    SYNTHESIS = "synthesis"
    ERROR = "error"


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
```
### 2.1 `router.py` 中 5 个代表性 `trace_obj.record()` 调用

#### 文件分析/grounding

位置：[core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L8384)，上下文行 8384-8402。

```python
            state.update_file_context(analysis_dict)
            setattr(state, "_file_analysis_cache", analysis_dict)
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.FILE_GROUNDING,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="analyze_file",
                    output_summary={
                        "task_type": state.file_context.task_type,
                        "confidence": state.file_context.confidence,
                        "columns": state.file_context.columns[:10],
                        "row_count": state.file_context.row_count,
                    },
                    confidence=state.file_context.confidence,
                    reasoning="; ".join(state.file_context.evidence) if state.file_context.evidence else "File structure analyzed",
                )
                self._record_file_analysis_enhancement_traces(analysis_dict, trace_obj)

        should_resolve_intent, intent_resolution_reason = self._should_resolve_intent(state)
```
#### 参数标准化

位置：[core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L9096)，上下文行 9096-9108。

```python
                            )

                    if std_summary_parts:
                        trace_obj.record(
                            step_type=TraceStepType.PARAMETER_STANDARDIZATION,
                            stage_before=TaskStage.EXECUTING.value,
                            action="standardize_parameters",
                            reasoning="; ".join(std_summary_parts),
                            standardization_records=std_records,
                        )

                if result.get("error") and result.get("error_type") == "standardization":
                    error_msg = result.get("message", "Parameter standardization failed")
```
#### 状态转移

位置：[core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L1085)，上下文行 1085-1096。

```python
        stage_before = state.stage.value
        state.transition(new_stage, reason=reason)
        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.STATE_TRANSITION,
                stage_before=stage_before,
                stage_after=state.stage.value,
                reasoning=reason,
            )

    def _identify_critical_missing(self, state: TaskState) -> Optional[str]:
        """Identify the single most critical missing piece of information.
```
#### 工具执行

位置：[core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L9157)，上下文行 9157-9179。

```python
                    else:
                        output_info["error"] = str(result.get("message", ""))[:200]

                    trace_obj.record(
                        step_type=TraceStepType.TOOL_EXECUTION,
                        stage_before=TaskStage.EXECUTING.value,
                        action=tool_call.name,
                        input_summary={
                            "arguments": {
                                key: str(value)[:80]
                                for key, value in (tool_call.arguments or {}).items()
                            }
                        },
                        output_summary=output_info,
                        confidence=None,
                        reasoning=result.get("summary", ""),
                        duration_ms=elapsed_ms,
                        standardization_records=std_records or None,
                        error=result.get("message") if result.get("error") else None,
                    )

            if dependency_blocked or repair_halted:
                break
```
#### 协商/补全

位置：[core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L6597)，上下文行 6597-6619。

```python
            trace_obj=trace_obj,
        )
        if trace_obj and record_required:
            trace_obj.record(
                step_type=TraceStepType.PARAMETER_NEGOTIATION_REQUIRED,
                stage_before=TaskStage.EXECUTING.value,
                stage_after=TaskStage.NEEDS_PARAMETER_CONFIRMATION.value,
                action=request.tool_name,
                input_summary={
                    "parameter_name": request.parameter_name,
                    "raw_value": request.raw_value,
                    "strategy": request.strategy,
                    "confidence": request.confidence,
                },
                output_summary={
                    "request_id": request.request_id,
                    "candidates": [candidate.to_dict() for candidate in request.candidates],
                },
                reasoning=request.trigger_reason,
            )

    def _should_handle_parameter_confirmation(self, state: TaskState) -> bool:
        request = state.active_parameter_negotiation or self._load_active_parameter_negotiation_request()
```
## 3. 记忆与上下文管理

- [core/memory.py](/home/kirito/Agent1/emission_agent/core/memory.py#L51) `MemoryManager`，行 51-336。
```python
class MemoryManager:
    """
    Memory manager with three-layer structure:
    1. Working memory - Recent complete conversations
    2. Fact memory - Structured facts (vehicle, pollutants, etc.)
    3. Compressed memory - Summary of old conversations
    """

    MAX_WORKING_MEMORY_TURNS = 5  # Keep last 5 turns

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.working_memory: List[Turn] = []
        self.fact_memory = FactMemory()
        self.compressed_memory: str = ""

        # Load persisted memory if exists
        self._load()

    def get_working_memory(self) -> List[Dict]:
        """
        Get working memory (recent conversations)

        Returns:
            List of conversation turns
        """
        return [
            {"user": turn.user, "assistant": turn.assistant}
            for turn in self.working_memory[-self.MAX_WORKING_MEMORY_TURNS:]
        ]

    def get_fact_memory(self) -> Dict:
        """
        Get fact memory

        Returns:
            Dictionary of structured facts
        """
        return {
            "recent_vehicle": self.fact_memory.recent_vehicle,
            "recent_pollutants": self.fact_memory.recent_pollutants,
            "recent_year": self.fact_memory.recent_year,
            "active_file": self.fact_memory.active_file,
            "file_analysis": self.fact_memory.file_analysis,
            "last_tool_name": self.fact_memory.last_tool_name,
            "last_tool_summary": self.fact_memory.last_tool_summary,
            "last_tool_snapshot": self.fact_memory.last_tool_snapshot,
            "last_spatial_data": self.fact_memory.last_spatial_data,
        }

    def update(
        self,
        user_message: str,
        assistant_response: str,
        tool_calls: Optional[List[Dict]] = None,
        file_path: Optional[str] = None,
        file_analysis: Optional[Dict] = None
    ):
        """
        Update memory after a conversation turn

        Args:
            user_message: User's message
            assistant_response: Assistant's response
            tool_calls: Optional tool calls made
            file_path: Optional file path if file was uploaded
            file_analysis: Optional cached file analysis result
        """
        # 1. Add to working memory
        turn = Turn(
            user=user_message,
            assistant=assistant_response,
            tool_calls=tool_calls
        )
        self.working_memory.append(turn)

        # 2. Update fact memory from successful tool calls
        if tool_calls:
            self._extract_facts_from_tool_calls(tool_calls)

        # 3. Update active file and cache analysis
        if file_path:
            self.fact_memory.active_file = str(file_path)
            if file_analysis:
                # Convert any Path objects to strings before storing
                self.fact_memory.file_analysis = _convert_paths_to_strings(file_analysis)

        # 4. Detect user corrections
        self._detect_correction(user_message)

        # 5. Compress old memory if needed
        if len(self.working_memory) > self.MAX_WORKING_MEMORY_TURNS * 2:
            self._compress_old_memory()

        # 6. Persist
        self._save()

    def _extract_facts_from_tool_calls(self, tool_calls: List[Dict]):
        """Extract facts from successful tool calls"""
        for call in tool_calls:
            args = call.get("arguments", {})
            result = call.get("result", {})

            # Only update from successful calls
            if not result.get("success"):
                continue

            tool_name = call.get("name")
            if tool_name:
                self.fact_memory.last_tool_name = tool_name
            if result.get("summary"):
                self.fact_memory.last_tool_summary = str(result["summary"])

            data = result.get("data", {})
            if isinstance(data, dict):
                # Keep a compact snapshot for follow-up grounding.
                snapshot: Dict[str, Any] = {}
                for k in ("query_info", "summary", "fleet_mix_fill", "download_file", "row_count", "columns", "task_type", "detected_type"):
                    if k in data:
                        snapshot[k] = data[k]
                if snapshot:
                    self.fact_memory.last_tool_snapshot = snapshot

            # Full spatial results are captured in core.router before tool data compaction.
            # This method only sees compacted tool calls, so geometry-bearing results are unavailable here.

            # Extract vehicle type
            if "vehicle_type" in args:
                self.fact_memory.recent_vehicle = args["vehicle_type"]
            elif isinstance(data, dict):
                q = data.get("query_info", {})
                if isinstance(q, dict) and q.get("vehicle_type"):
                    self.fact_memory.recent_vehicle = q["vehicle_type"]
                elif data.get("vehicle_type"):
                    self.fact_memory.recent_vehicle = data["vehicle_type"]

            # Extract pollutant(s)
            if "pollutant" in args:
                pol = args["pollutant"]
                self._merge_recent_pollutants([pol])

            if "pollutants" in args:
                if isinstance(args["pollutants"], list):
                    self._merge_recent_pollutants(args["pollutants"])
            elif isinstance(data, dict):
                q = data.get("query_info", {})
                if isinstance(q, dict) and isinstance(q.get("pollutants"), list):
                    self._merge_recent_pollutants(q["pollutants"])
                elif isinstance(data.get("pollutants"), list):
                    self._merge_recent_pollutants(data["pollutants"])

            # Extract model year
            if "model_year" in args:
                self.fact_memory.recent_year = args["model_year"]
            elif isinstance(data, dict):
                q = data.get("query_info", {})
                if isinstance(q, dict) and q.get("model_year"):
                    self.fact_memory.recent_year = q["model_year"]
                elif data.get("model_year"):
                    self.fact_memory.recent_year = data["model_year"]

    def _merge_recent_pollutants(self, pollutants: List[Any]):
        """Merge pollutant list while keeping recent distinct entries."""
        for pol in pollutants:
            if not pol:
                continue
            pol_str = str(pol)
            if pol_str not in self.fact_memory.recent_pollutants:
                self.fact_memory.recent_pollutants.insert(0, pol_str)
        self.fact_memory.recent_pollutants = self.fact_memory.recent_pollutants[:5]

    def _detect_correction(self, user_message: str):
        """Detect user corrections and update fact memory"""
        correction_patterns = ["不对", "不是", "应该是", "我说的是", "换成", "改成"]

        if not any(p in user_message for p in correction_patterns):
            return

        # Simple correction detection
        # In production, could use LLM to understand corrections better
        vehicle_keywords = ["小汽车", "公交车", "货车", "轿车", "客车"]
        for kw in vehicle_keywords:
            if kw in user_message:
                self.fact_memory.recent_vehicle = kw
                logger.info(f"Detected correction: vehicle -> {kw}")
                break

    def _compress_old_memory(self):
        """Compress old memory to save space"""
        # Keep recent turns, compress older ones
        old_turns = self.working_memory[:-self.MAX_WORKING_MEMORY_TURNS]

        # Simple compression: extract tool call info
        summaries = []
        for turn in old_turns:
            if turn.tool_calls:
                for call in turn.tool_calls:
                    summaries.append(f"- Called {call.get('name')} with {call.get('arguments')}")

        self.compressed_memory = "\n".join(summaries)
        self.working_memory = self.working_memory[-self.MAX_WORKING_MEMORY_TURNS:]
        logger.info(f"Compressed memory, kept {len(self.working_memory)} recent turns")

    def clear_topic_memory(self):
        """Clear topic-related memory (when topic changes)"""
        self.fact_memory.active_file = None
        self.fact_memory.file_analysis = None
        self.fact_memory.last_tool_name = None
        self.fact_memory.last_tool_summary = None
        self.fact_memory.last_tool_snapshot = None
        self.fact_memory.last_spatial_data = None
        logger.info("Cleared topic memory")

    def _save(self):
        """Persist memory to disk"""
        data = {
            "session_id": self.session_id,
            "fact_memory": {
                "recent_vehicle": self.fact_memory.recent_vehicle,
                "recent_pollutants": self.fact_memory.recent_pollutants,
                "recent_year": self.fact_memory.recent_year,
                "active_file": self.fact_memory.active_file,
                "file_analysis": _convert_paths_to_strings(self.fact_memory.file_analysis),
                "last_tool_name": self.fact_memory.last_tool_name,
                "last_tool_summary": self.fact_memory.last_tool_summary,
                "last_tool_snapshot": _convert_paths_to_strings(self.fact_memory.last_tool_snapshot),
                "last_spatial_data": _convert_paths_to_strings(self.fact_memory.last_spatial_data),
            },
            "compressed_memory": self.compressed_memory,
            "working_memory": [
                {
                    "user": t.user,
                    "assistant": t.assistant,
                    "timestamp": t.timestamp.isoformat()
                }
                for t in self.working_memory[-10:]  # Save max 10 turns
            ]
        }

        path = Path(f"data/sessions/history/{self.session_id}.json")
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save memory: {e}")

    def _load(self):
        """Load persisted memory from disk"""
        path = Path(f"data/sessions/history/{self.session_id}.json")
        if not path.exists():
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Load fact memory
            if "fact_memory" in data:
                fm = data["fact_memory"]
                self.fact_memory.recent_vehicle = fm.get("recent_vehicle")
                self.fact_memory.recent_pollutants = fm.get("recent_pollutants", [])
                self.fact_memory.recent_year = fm.get("recent_year")
                self.fact_memory.active_file = fm.get("active_file")
                self.fact_memory.file_analysis = fm.get("file_analysis")
                self.fact_memory.last_tool_name = fm.get("last_tool_name")
                self.fact_memory.last_tool_summary = fm.get("last_tool_summary")
                self.fact_memory.last_tool_snapshot = fm.get("last_tool_snapshot")
                self.fact_memory.last_spatial_data = fm.get("last_spatial_data")

            # Load compressed memory
            self.compressed_memory = data.get("compressed_memory", "")

            # Load working memory
            if "working_memory" in data:
                for item in data["working_memory"]:
                    self.working_memory.append(Turn(
                        user=item["user"],
                        assistant=item["assistant"]
                    ))

            logger.info(f"Loaded memory for session {self.session_id}")

        except Exception as e:
            logger.warning(f"Failed to load memory: {e}")
```
- [core/context_store.py](/home/kirito/Agent1/emission_agent/core/context_store.py#L19) `StoredResult`，行 19-38；[core/context_store.py](/home/kirito/Agent1/emission_agent/core/context_store.py#L41) `SessionContextStore`，行 41-562。`store_result()` 行 82-115，`get_result_for_tool()` 行 117-177，`clear_current_turn()` 行 398-399。
```python
class StoredResult:
    """One successful tool result stored with semantic type and scenario label."""

    result_type: str
    tool_name: str
    label: str
    timestamp: str
    summary: str
    data: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def compact(self) -> Dict[str, Any]:
        """Return an LLM-safe compact representation without raw payloads."""
        return {
            "type": self.result_type,
            "tool": self.tool_name,
            "label": self.label,
            "summary": self.summary,
            "metadata": self.metadata,
        }


class SessionContextStore:
    """
    Keep semantic tool results for the active router/session instance.

    Results are keyed by semantic type + scenario label so downstream tools can
    resolve the correct upstream data without depending on "the last result".
    """

    BASELINE_LABEL = "baseline"
    MAX_SCENARIOS = 5

    TOOL_TO_RESULT_TYPE = {
        "calculate_macro_emission": "emission",
        "calculate_micro_emission": "emission",
        "calculate_dispersion": "dispersion",
        "analyze_hotspots": "hotspot",
        "render_spatial_map": "visualization",
        "compare_scenarios": "scenario_comparison",
        "analyze_file": "file_analysis",
        "query_emission_factors": "emission_factors",
        "query_knowledge": "knowledge",
    }

    TOOL_DEPENDENCIES: Dict[str, Any] = {
        "calculate_dispersion": ["emission"],
        "analyze_hotspots": ["dispersion"],
        "render_spatial_map": {
            "emission": ["emission"],
            "dispersion": ["dispersion"],
            "raster": ["dispersion"],
            "concentration": ["dispersion"],
            "hotspot": ["hotspot"],
            "_default": ["hotspot", "dispersion", "emission"],
        },
    }

    def __init__(self) -> None:
        self._store: Dict[str, StoredResult] = {}
        self._history: List[StoredResult] = []
        self._current_turn_results: List[Dict[str, Any]] = []

    def store_result(self, tool_name: str, result: Dict[str, Any]) -> Optional[StoredResult]:
        """Store one successful tool result under semantic type + scenario label."""
        if not isinstance(result, dict) or not result.get("success"):
            return None

        result_type = self.TOOL_TO_RESULT_TYPE.get(tool_name, "unknown")
        label = self._extract_label(result)
        stored = StoredResult(
            result_type=result_type,
            tool_name=tool_name,
            label=label,
            timestamp=datetime.now().isoformat(),
            summary=self._build_summary(tool_name, result),
            data=result,
            metadata=self._build_metadata(tool_name, result, label),
        )

        key = self._make_key(result_type, label)
        self._store[key] = stored
        self._history.append(stored)
        self._enforce_scenario_limit(result_type)

        if result_type == "emission":
            self._invalidate_dependents(label, ["dispersion", "hotspot"])
        elif result_type == "dispersion":
            self._invalidate_dependents(label, ["hotspot"])

        logger.info(
            "Context store: saved %s from %s with metadata=%s",
            key,
            tool_name,
            stored.metadata,
        )
        return stored

    def get_result_for_tool(
        self,
        requesting_tool: str,
        *,
        label: Optional[str] = None,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        """Return the best full tool result payload for a downstream tool."""
        deps = self.TOOL_DEPENDENCIES.get(requesting_tool)
        if deps is None:
            return None

        if isinstance(deps, dict):
            layer_type = normalize_result_token(kwargs.get("layer_type")) or str(
                kwargs.get("layer_type") or ""
            ).strip().lower()
            needed_types = deps.get(layer_type, deps.get("_default", []))
        else:
            needed_types = deps

        requested_label = str(label).strip() if label else None
        for result_type in needed_types:
            current_turn = self._find_current_turn_result(result_type, label=requested_label)
            if current_turn is not None:
                logger.info(
                    "Context store: providing current-turn %s%s data to %s",
                    result_type,
                    f":{requested_label}" if requested_label else "",
                    requesting_tool,
                )
                return current_turn

            stored = self.get_by_type(result_type, label=requested_label)
            if stored is not None and stored.data:
                logger.info(
                    "Context store: providing stored %s:%s data to %s",
                    result_type,
                    stored.label,
                    requesting_tool,
                )
                return stored.data

            if requested_label and requested_label != self.BASELINE_LABEL:
                baseline = self.get_by_type(result_type, label=self.BASELINE_LABEL)
                if baseline is not None and baseline.data:
                    logger.info(
                        "Context store: falling back to %s:%s for %s",
                        result_type,
                        self.BASELINE_LABEL,
                        requesting_tool,
                    )
                    return baseline.data

        logger.warning(
            "Context store: no data found for %s (needed=%s, label=%s, available=%s)",
            requesting_tool,
            needed_types,
            requested_label or self.BASELINE_LABEL,
            sorted(self._store.keys()),
        )
        return None

    def get_latest(self) -> Optional[StoredResult]:
        return self._history[-1] if self._history else None

    def get_by_type(self, result_type: str, label: Optional[str] = None) -> Optional[StoredResult]:
        """Return one stored result, defaulting to baseline when available."""
        result_type = normalize_result_token(result_type) or result_type
        requested_label = str(label).strip() if label else None
        if requested_label:
            return self._store.get(self._make_key(result_type, requested_label))

        baseline = self._store.get(self._make_key(result_type, self.BASELINE_LABEL))
        if baseline is not None:
            return baseline

        candidates = [item for item in self._store.values() if item.result_type == result_type]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.timestamp)

    def has_result(self, result_type: str, label: Optional[str] = None) -> bool:
        return self.get_by_type(result_type, label=label) is not None

    def get_scenario_pair(
        self,
        result_type: str,
        baseline: str,
        scenario: str,
    ) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        result_type = normalize_result_token(result_type) or result_type
        baseline_stored = self.get_by_type(result_type, label=baseline)
        scenario_stored = self.get_by_type(result_type, label=scenario)
        return (
            baseline_stored.data if baseline_stored is not None else None,
            scenario_stored.data if scenario_stored is not None else None,
        )

    def list_scenarios(self, result_type: Optional[str] = None) -> Dict[str, List[str]]:
        grouped: Dict[str, List[str]] = {}
        for stored in self._store.values():
            if result_type and stored.result_type != result_type:
                continue
            grouped.setdefault(stored.result_type, [])
            if stored.label not in grouped[stored.result_type]:
                grouped[stored.result_type].append(stored.label)

        for labels in grouped.values():
            labels.sort(key=lambda item: (item != self.BASELINE_LABEL, item))
        return grouped

    def get_context_summary(self) -> str:
        """Build a compact session summary safe for LLM context."""
        if not self._store:
            return ""

        lines = ["[Available session analysis results]"]
        grouped: Dict[str, List[StoredResult]] = {}
        for stored in self._store.values():
            grouped.setdefault(stored.result_type, []).append(stored)

        for result_type in sorted(grouped.keys()):
            stored_items = sorted(
                grouped[result_type],
                key=lambda item: (item.label != self.BASELINE_LABEL, item.label),
            )
            if len(stored_items) == 1:
                item = stored_items[0]
                stale = " [stale]" if item.metadata.get("stale") else ""
                lines.append(f"- {result_type}[{item.label}]{stale}: {item.summary}")
                continue

            labels_desc = []
            for item in stored_items:
                label_text = item.label + ("*" if item.metadata.get("stale") else "")
                labels_desc.append(f"{label_text}={item.summary}")
            lines.append(f"- {result_type}: " + " | ".join(labels_desc))

        summary = "\n".join(lines)
        if len(summary) <= MAX_CONTEXT_SUMMARY_CHARS:
            return summary
        return summary[: MAX_CONTEXT_SUMMARY_CHARS - 3].rstrip() + "..."

    def get_available_types(self, include_stale: bool = False) -> set[str]:
        available = set()
        for item in self._current_turn_results:
            result_type = normalize_result_token(item.get("result_type")) or item.get("result_type")
            if not result_type:
                continue
            label = str(item.get("label") or self.BASELINE_LABEL)
            stored = self._store.get(self._make_key(result_type, label))
            if stored is not None and stored.metadata.get("stale") and not include_stale:
                continue
            available.add(result_type)
        for stored in self._store.values():
            if stored.metadata.get("stale") and not include_stale:
                continue
            available.add(stored.result_type)
        return available

    def get_result_availability(
        self,
        result_type: str,
        *,
        label: Optional[str] = None,
        include_stale: bool = False,
    ) -> Dict[str, Any]:
        """Describe whether one semantic result token is currently usable."""
        result_type = normalize_result_token(result_type) or result_type
        requested_label = str(label).strip() if label else None

        def _availability_payload(
            *,
            available: bool,
            stale: bool,
            source: str,
            resolved_label: Optional[str],
        ) -> Dict[str, Any]:
            return {
                "token": result_type,
                "available": available,
                "stale": stale,
                "source": source,
                "label": resolved_label,
            }

        if requested_label:
            current_turn_entry = self._find_current_turn_entry(result_type, label=requested_label)
            if current_turn_entry is not None:
                entry_label = str(current_turn_entry.get("label") or requested_label or self.BASELINE_LABEL)
                stored_current = self._store.get(self._make_key(result_type, entry_label))
                is_stale = bool(stored_current.metadata.get("stale")) if stored_current is not None else False
                return _availability_payload(
                    available=include_stale or not is_stale,
                    stale=is_stale,
                    source="current_turn",
                    resolved_label=entry_label,
                )

            stored_exact = self._store.get(self._make_key(result_type, requested_label))
            if stored_exact is not None:
                is_stale = bool(stored_exact.metadata.get("stale"))
                return _availability_payload(
                    available=include_stale or not is_stale,
                    stale=is_stale,
                    source="stored_exact",
                    resolved_label=stored_exact.label,
                )

            if requested_label != self.BASELINE_LABEL:
                current_turn_entry = self._find_current_turn_entry(result_type, label=self.BASELINE_LABEL)
                if current_turn_entry is not None:
                    stored_current = self._store.get(self._make_key(result_type, self.BASELINE_LABEL))
                    is_stale = bool(stored_current.metadata.get("stale")) if stored_current is not None else False
                    return _availability_payload(
                        available=include_stale or not is_stale,
                        stale=is_stale,
                        source="current_turn_baseline_fallback",
                        resolved_label=self.BASELINE_LABEL,
                    )

                stored_baseline = self._store.get(self._make_key(result_type, self.BASELINE_LABEL))
                if stored_baseline is not None:
                    is_stale = bool(stored_baseline.metadata.get("stale"))
                    return _availability_payload(
                        available=include_stale or not is_stale,
                        stale=is_stale,
                        source="stored_baseline_fallback",
                        resolved_label=stored_baseline.label,
                    )

            return _availability_payload(
                available=False,
                stale=False,
                source="unavailable",
                resolved_label=requested_label,
            )

        current_turn_entry = self._find_current_turn_entry(result_type)
        if current_turn_entry is not None:
            entry_label = str(current_turn_entry.get("label") or self.BASELINE_LABEL)
            stored_current = self._store.get(self._make_key(result_type, entry_label))
            is_stale = bool(stored_current.metadata.get("stale")) if stored_current is not None else False
            return _availability_payload(
                available=include_stale or not is_stale,
                stale=is_stale,
                source="current_turn",
                resolved_label=entry_label,
            )

        stored_default = self.get_by_type(result_type)
        if stored_default is None:
            return _availability_payload(
                available=False,
                stale=False,
                source="unavailable",
                resolved_label=None,
            )

        is_stale = bool(stored_default.metadata.get("stale"))
        return _availability_payload(
            available=include_stale or not is_stale,
            stale=is_stale,
            source="stored",
            resolved_label=stored_default.label,
        )

    def add_current_turn_result(self, tool_name: str, result: Dict[str, Any]) -> None:
        entry = {
            "name": tool_name,
            "result": result,
            "result_type": self.TOOL_TO_RESULT_TYPE.get(tool_name, "unknown"),
            "label": self._extract_label(result),
        }
        self._current_turn_results.append(entry)
        if isinstance(result, dict) and result.get("success"):
            self.store_result(tool_name, result)

    def get_current_turn_results(self) -> List[Dict[str, Any]]:
        return list(self._current_turn_results)

    def clear_current_turn(self) -> None:
        self._current_turn_results = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "results": {key: value.compact() for key, value in self._store.items()},
            "history_count": len(self._history),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionContextStore":
        """Restore compact metadata only; full payloads are kept in memory only."""
        store = cls()
        results = data.get("results", {})
        if not isinstance(results, dict):
            return store

        for key, compact in results.items():
            if not isinstance(compact, dict):
                continue
            label = str(compact.get("label") or cls.BASELINE_LABEL)
            result_type = str(compact.get("type") or key.split(":", 1)[0])
            store._store[key] = StoredResult(
                result_type=result_type,
                tool_name=str(compact.get("tool") or "unknown"),
                label=label,
                timestamp=datetime.now().isoformat(),
                summary=str(compact.get("summary") or ""),
                data={},
                metadata=compact.get("metadata", {}) if isinstance(compact.get("metadata"), dict) else {},
            )
        return store

    def _extract_label(self, result: Dict[str, Any]) -> str:
        data = result.get("data", {})
        if isinstance(data, dict):
            label = data.get("scenario_label")
            if isinstance(label, str) and label.strip():
                return label.strip()
        return self.BASELINE_LABEL

    def _make_key(self, result_type: str, label: str) -> str:
        return f"{result_type}:{label}"

    def _find_current_turn_result(
        self,
        result_type: str,
        *,
        label: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        entry = self._find_current_turn_entry(result_type, label=label)
        if entry is None:
            return None
        result = entry.get("result")
        if isinstance(result, dict) and result.get("success"):
            return result
        return None

    def _find_current_turn_entry(
        self,
        result_type: str,
        *,
        label: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        for item in reversed(self._current_turn_results):
            if item.get("result_type") != result_type:
                continue
            if label and item.get("label") != label:
                continue
            result = item.get("result")
            if isinstance(result, dict) and result.get("success"):
                return item
        return None

    def _invalidate_dependents(self, label: str, dependent_types: List[str]) -> None:
        for dependent_type in dependent_types:
            key = self._make_key(dependent_type, label)
            stored = self._store.get(key)
            if stored is None:
                continue
            stored.metadata["stale"] = True
            logger.info("Context store: marked %s as stale", key)

    def _enforce_scenario_limit(self, result_type: str) -> None:
        candidates = [
            item
            for key, item in self._store.items()
            if item.result_type == result_type and item.label != self.BASELINE_LABEL
        ]
        if len(candidates) <= self.MAX_SCENARIOS:
            return

        removable = sorted(candidates, key=lambda item: item.timestamp)[: len(candidates) - self.MAX_SCENARIOS]
        for item in removable:
            key = self._make_key(item.result_type, item.label)
            self._store.pop(key, None)
            logger.info("Context store: removed %s due to scenario limit", key)

    def _build_summary(self, tool_name: str, result: Dict[str, Any]) -> str:
        summary = str(result.get("summary") or "").strip()
        if summary:
            compact = " ".join(summary.split())
            return compact[:MAX_SUMMARY_CHARS]

        data = result.get("data", {})
        if isinstance(data, dict):
            summary_block = data.get("summary", {})
            if isinstance(summary_block, dict):
                if "total_links" in summary_block:
                    return f"Emission calculation for {summary_block['total_links']} links"
                if "receptor_count" in summary_block:
                    return f"Dispersion analysis for {summary_block['receptor_count']} receptors"
                if "hotspot_count" in summary_block:
                    return f"Hotspot analysis with {summary_block['hotspot_count']} hotspots"
        return f"{tool_name} completed"

    def _build_metadata(
        self,
        tool_name: str,
        result: Dict[str, Any],
        label: str,
    ) -> Dict[str, Any]:
        data = result.get("data", {})
        metadata: Dict[str, Any] = {
            "tool_name": tool_name,
            "scenario_label": label,
        }
        if not isinstance(data, dict):
            return metadata

        results_list = data.get("results")
        if isinstance(results_list, list):
            metadata["count"] = len(results_list)
            if results_list and isinstance(results_list[0], dict):
                metadata["has_geometry"] = any(
                    isinstance(item, dict) and bool(item.get("geometry"))
                    for item in results_list[:5]
                )

        query_info = data.get("query_info", {})
        if isinstance(query_info, dict):
            if query_info.get("pollutants"):
                metadata["pollutants"] = query_info.get("pollutants")
            if query_info.get("pollutant"):
                metadata["pollutant"] = query_info.get("pollutant")
            if query_info.get("model_year") is not None:
                metadata["model_year"] = query_info.get("model_year")

        summary = data.get("summary", {})
        if isinstance(summary, dict):
            for key in (
                "total_links",
                "receptor_count",
                "hotspot_count",
                "mean_concentration",
                "max_concentration",
            ):
                if key in summary:
                    metadata[key] = summary[key]

        overrides = data.get("overrides_applied")
        if isinstance(overrides, list) and overrides:
            metadata["override_count"] = len(overrides)

        return metadata
```
- [core/artifact_memory.py](/home/kirito/Agent1/emission_agent/core/artifact_memory.py#L1) `core/artifact_memory.py` 完整文件，行 1-859；包含所有 public 类与方法。
```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence

from core.intent_resolution import IntentResolutionApplicationPlan


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _clean_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    cleaned: List[str] = []
    for item in values:
        text = _clean_text(item)
        if text:
            cleaned.append(text)
    return cleaned


class ArtifactType(str, Enum):
    DETAILED_CSV = "detailed_csv"
    TOPK_SUMMARY_TABLE = "topk_summary_table"
    RANKED_CHART = "ranked_chart"
    SPATIAL_MAP = "spatial_map"
    DISPERSION_MAP = "dispersion_map"
    HOTSPOT_MAP = "hotspot_map"
    QUICK_SUMMARY_TEXT = "quick_summary_text"
    COMPARISON_RESULT = "comparison_result"
    UNKNOWN = "unknown"


class ArtifactFamily(str, Enum):
    DOWNLOADABLE_TABLE = "downloadable_table"
    RANKED_SUMMARY = "ranked_summary"
    SPATIAL_VISUALIZATION = "spatial_visualization"
    TEXTUAL_SUMMARY = "textual_summary"
    COMPARISON_OUTPUT = "comparison_output"


class ArtifactDeliveryStatus(str, Enum):
    FULL = "full"
    PARTIAL = "partial"


_ARTIFACT_FAMILY_BY_TYPE: Dict[ArtifactType, ArtifactFamily] = {
    ArtifactType.DETAILED_CSV: ArtifactFamily.DOWNLOADABLE_TABLE,
    ArtifactType.TOPK_SUMMARY_TABLE: ArtifactFamily.RANKED_SUMMARY,
    ArtifactType.RANKED_CHART: ArtifactFamily.RANKED_SUMMARY,
    ArtifactType.SPATIAL_MAP: ArtifactFamily.SPATIAL_VISUALIZATION,
    ArtifactType.DISPERSION_MAP: ArtifactFamily.SPATIAL_VISUALIZATION,
    ArtifactType.HOTSPOT_MAP: ArtifactFamily.SPATIAL_VISUALIZATION,
    ArtifactType.QUICK_SUMMARY_TEXT: ArtifactFamily.TEXTUAL_SUMMARY,
    ArtifactType.COMPARISON_RESULT: ArtifactFamily.COMPARISON_OUTPUT,
    ArtifactType.UNKNOWN: ArtifactFamily.TEXTUAL_SUMMARY,
}


_ACTION_ARTIFACT_TYPE_MAP: Dict[str, ArtifactType] = {
    "download_detailed_csv": ArtifactType.DETAILED_CSV,
    "download_topk_summary": ArtifactType.TOPK_SUMMARY_TABLE,
    "render_rank_chart": ArtifactType.RANKED_CHART,
    "deliver_quick_structured_summary": ArtifactType.QUICK_SUMMARY_TEXT,
    "render_emission_map": ArtifactType.SPATIAL_MAP,
    "render_dispersion_map": ArtifactType.DISPERSION_MAP,
    "render_hotspot_map": ArtifactType.HOTSPOT_MAP,
    "compare_scenario": ArtifactType.COMPARISON_RESULT,
}


_DEFAULT_ACTION_BY_TYPE: Dict[ArtifactType, str] = {
    ArtifactType.DETAILED_CSV: "download_detailed_csv",
    ArtifactType.TOPK_SUMMARY_TABLE: "download_topk_summary",
    ArtifactType.RANKED_CHART: "render_rank_chart",
    ArtifactType.QUICK_SUMMARY_TEXT: "deliver_quick_structured_summary",
    ArtifactType.SPATIAL_MAP: "render_emission_map",
    ArtifactType.DISPERSION_MAP: "render_dispersion_map",
    ArtifactType.HOTSPOT_MAP: "render_hotspot_map",
    ArtifactType.COMPARISON_RESULT: "compare_scenario",
}


_ARTIFACT_KIND_BY_TYPE: Dict[ArtifactType, str] = {
    ArtifactType.DETAILED_CSV: "download",
    ArtifactType.TOPK_SUMMARY_TABLE: "table",
    ArtifactType.RANKED_CHART: "chart",
    ArtifactType.SPATIAL_MAP: "map",
    ArtifactType.DISPERSION_MAP: "map",
    ArtifactType.HOTSPOT_MAP: "map",
    ArtifactType.QUICK_SUMMARY_TEXT: "summary",
    ArtifactType.COMPARISON_RESULT: "comparison",
}


def artifact_family_for_type(artifact_type: ArtifactType) -> ArtifactFamily:
    return _ARTIFACT_FAMILY_BY_TYPE.get(artifact_type, ArtifactFamily.TEXTUAL_SUMMARY)


def artifact_type_for_action_id(action_id: Optional[str]) -> Optional[ArtifactType]:
    action_text = _clean_text(action_id)
    if not action_text:
        return None
    return _ACTION_ARTIFACT_TYPE_MAP.get(action_text)


@dataclass
class ArtifactRecord:
    artifact_id: str
    artifact_type: ArtifactType
    artifact_family: ArtifactFamily
    source_action_id: Optional[str] = None
    source_tool_name: Optional[str] = None
    delivery_turn_index: int = 0
    delivery_status: ArtifactDeliveryStatus = ArtifactDeliveryStatus.FULL
    file_ref: Optional[str] = None
    download_ref: Optional[Dict[str, Any]] = None
    summary: Optional[str] = None
    related_task_type: Optional[str] = None
    related_pollutant: Optional[str] = None
    related_scope: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "ArtifactRecord":
        data = payload if isinstance(payload, dict) else {}
        artifact_type_value = data.get("artifact_type") or ArtifactType.UNKNOWN.value
        artifact_family_value = data.get("artifact_family") or ArtifactFamily.TEXTUAL_SUMMARY.value
        delivery_status_value = data.get("delivery_status") or ArtifactDeliveryStatus.FULL.value
        try:
            artifact_type = ArtifactType(str(artifact_type_value).strip())
        except ValueError:
            artifact_type = ArtifactType.UNKNOWN
        try:
            artifact_family = ArtifactFamily(str(artifact_family_value).strip())
        except ValueError:
            artifact_family = artifact_family_for_type(artifact_type)
        try:
            delivery_status = ArtifactDeliveryStatus(str(delivery_status_value).strip())
        except ValueError:
            delivery_status = ArtifactDeliveryStatus.FULL
        return cls(
            artifact_id=_clean_text(data.get("artifact_id")) or "artifact",
            artifact_type=artifact_type,
            artifact_family=artifact_family,
            source_action_id=_clean_text(data.get("source_action_id")),
            source_tool_name=_clean_text(data.get("source_tool_name")),
            delivery_turn_index=int(data.get("delivery_turn_index") or 0),
            delivery_status=delivery_status,
            file_ref=_clean_text(data.get("file_ref")),
            download_ref=_clean_dict(data.get("download_ref")) or None,
            summary=_clean_text(data.get("summary")),
            related_task_type=_clean_text(data.get("related_task_type")),
            related_pollutant=_clean_text(data.get("related_pollutant")),
            related_scope=_clean_text(data.get("related_scope")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type.value,
            "artifact_family": self.artifact_family.value,
            "source_action_id": self.source_action_id,
            "source_tool_name": self.source_tool_name,
            "delivery_turn_index": self.delivery_turn_index,
            "delivery_status": self.delivery_status.value,
            "file_ref": self.file_ref,
            "download_ref": dict(self.download_ref or {}),
            "summary": self.summary,
            "related_task_type": self.related_task_type,
            "related_pollutant": self.related_pollutant,
            "related_scope": self.related_scope,
        }

    def to_summary(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type.value,
            "artifact_family": self.artifact_family.value,
            "delivery_status": self.delivery_status.value,
            "source_action_id": self.source_action_id,
            "source_tool_name": self.source_tool_name,
            "summary": self.summary,
            "related_scope": self.related_scope,
            "related_task_type": self.related_task_type,
        }


@dataclass
class ArtifactMemoryState:
    artifacts: List[ArtifactRecord] = field(default_factory=list)
    latest_by_family: Dict[str, ArtifactRecord] = field(default_factory=dict)
    latest_by_type: Dict[str, ArtifactRecord] = field(default_factory=dict)
    recent_artifact_summary: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "ArtifactMemoryState":
        data = payload if isinstance(payload, dict) else {}
        state = cls(
            artifacts=[
                ArtifactRecord.from_dict(item)
                for item in (data.get("artifacts") or [])
                if isinstance(item, dict)
            ]
        )
        state.refresh_indexes()
        if isinstance(data.get("recent_artifact_summary"), list):
            state.recent_artifact_summary = [
                dict(item)
                for item in data.get("recent_artifact_summary")
                if isinstance(item, dict)
            ]
        return state

    def refresh_indexes(self) -> "ArtifactMemoryState":
        latest_by_family: Dict[str, ArtifactRecord] = {}
        latest_by_type: Dict[str, ArtifactRecord] = {}
        ordered = sorted(
            self.artifacts,
            key=lambda item: (item.delivery_turn_index, item.artifact_id),
        )
        for record in ordered:
            latest_by_family[record.artifact_family.value] = record
            latest_by_type[record.artifact_type.value] = record
        self.latest_by_family = latest_by_family
        self.latest_by_type = latest_by_type
        summary_records = sorted(
            self.artifacts,
            key=lambda item: (item.delivery_turn_index, item.artifact_id),
            reverse=True,
        )
        self.recent_artifact_summary = [item.to_summary() for item in summary_records[:8]]
        return self

    def append(self, records: Sequence[ArtifactRecord]) -> "ArtifactMemoryState":
        if not records:
            return self
        self.artifacts.extend(records)
        self.refresh_indexes()
        return self

    def clone(self) -> "ArtifactMemoryState":
        return ArtifactMemoryState.from_dict(self.to_dict())

    def find_latest_type(
        self,
        artifact_type: ArtifactType,
        *,
        status: Optional[ArtifactDeliveryStatus] = None,
    ) -> Optional[ArtifactRecord]:
        candidates = [
            item
            for item in self.artifacts
            if item.artifact_type == artifact_type
            and (status is None or item.delivery_status == status)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item.delivery_turn_index, item.artifact_id))

    def find_latest_family(
        self,
        artifact_family: ArtifactFamily,
        *,
        status: Optional[ArtifactDeliveryStatus] = None,
    ) -> Optional[ArtifactRecord]:
        candidates = [
            item
            for item in self.artifacts
            if item.artifact_family == artifact_family
            and (status is None or item.delivery_status == status)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item.delivery_turn_index, item.artifact_id))

    def to_summary(self) -> Dict[str, Any]:
        return {
            "artifact_count": len(self.artifacts),
            "latest_by_family": {
                key: value.to_summary()
                for key, value in self.latest_by_family.items()
            },
            "latest_by_type": {
                key: value.to_summary()
                for key, value in self.latest_by_type.items()
            },
            "recent_artifact_summary": [dict(item) for item in self.recent_artifact_summary],
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifacts": [item.to_dict() for item in self.artifacts],
            "latest_by_family": {
                key: value.to_dict()
                for key, value in self.latest_by_family.items()
            },
            "latest_by_type": {
                key: value.to_dict()
                for key, value in self.latest_by_type.items()
            },
            "recent_artifact_summary": [dict(item) for item in self.recent_artifact_summary],
        }


@dataclass
class ArtifactAvailabilityDecision:
    requested_type: Optional[ArtifactType] = None
    requested_family: Optional[ArtifactFamily] = None
    same_type_full_provided: bool = False
    same_family_full_provided: bool = False
    matching_record: Optional[ArtifactRecord] = None
    family_record: Optional[ArtifactRecord] = None
    should_suppress_repeat: bool = False
    should_promote_new_family: bool = False
    explanation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requested_type": self.requested_type.value if self.requested_type is not None else None,
            "requested_family": self.requested_family.value if self.requested_family is not None else None,
            "same_type_full_provided": self.same_type_full_provided,
            "same_family_full_provided": self.same_family_full_provided,
            "matching_record": self.matching_record.to_dict() if self.matching_record is not None else None,
            "family_record": self.family_record.to_dict() if self.family_record is not None else None,
            "should_suppress_repeat": self.should_suppress_repeat,
            "should_promote_new_family": self.should_promote_new_family,
            "explanation": self.explanation,
        }


@dataclass
class ArtifactSuggestionPlan:
    suppressed_action_ids: List[str] = field(default_factory=list)
    promoted_action_ids: List[str] = field(default_factory=list)
    promoted_families: List[str] = field(default_factory=list)
    repeated_artifact_types: List[str] = field(default_factory=list)
    repeated_artifact_families: List[str] = field(default_factory=list)
    user_visible_summary: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    availability_decision: Optional[ArtifactAvailabilityDecision] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "suppressed_action_ids": list(self.suppressed_action_ids),
            "promoted_action_ids": list(self.promoted_action_ids),
            "promoted_families": list(self.promoted_families),
            "repeated_artifact_types": list(self.repeated_artifact_types),
            "repeated_artifact_families": list(self.repeated_artifact_families),
            "user_visible_summary": self.user_visible_summary,
            "notes": list(self.notes),
            "availability_decision": (
                self.availability_decision.to_dict()
                if self.availability_decision is not None
                else None
            ),
        }


def coerce_artifact_memory_state(payload: Any) -> ArtifactMemoryState:
    if isinstance(payload, ArtifactMemoryState):
        return payload.clone()
    if isinstance(payload, dict):
        return ArtifactMemoryState.from_dict(payload)
    return ArtifactMemoryState()


def build_artifact_record(
    *,
    artifact_type: ArtifactType,
    delivery_turn_index: int,
    source_tool_name: Optional[str] = None,
    source_action_id: Optional[str] = None,
    delivery_status: ArtifactDeliveryStatus = ArtifactDeliveryStatus.FULL,
    file_ref: Optional[str] = None,
    download_ref: Optional[Dict[str, Any]] = None,
    summary: Optional[str] = None,
    related_task_type: Optional[str] = None,
    related_pollutant: Optional[str] = None,
    related_scope: Optional[str] = None,
) -> ArtifactRecord:
    normalized_source_action = source_action_id or _DEFAULT_ACTION_BY_TYPE.get(artifact_type)
    family = artifact_family_for_type(artifact_type)
    artifact_id = f"{artifact_type.value}:{delivery_turn_index}:{normalized_source_action or source_tool_name or 'artifact'}"
    return ArtifactRecord(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        artifact_family=family,
        source_action_id=normalized_source_action,
        source_tool_name=source_tool_name,
        delivery_turn_index=delivery_turn_index,
        delivery_status=delivery_status,
        file_ref=file_ref,
        download_ref=dict(download_ref or {}) or None,
        summary=summary,
        related_task_type=related_task_type,
        related_pollutant=related_pollutant,
        related_scope=related_scope,
    )


def _extract_first_pollutant(tool_results: Sequence[Dict[str, Any]]) -> Optional[str]:
    for item in tool_results:
        if not isinstance(item, dict):
            continue
        arguments = item.get("arguments") or {}
        if isinstance(arguments, dict):
            pollutant = _clean_text(arguments.get("pollutant"))
            if pollutant:
                return pollutant
            pollutants = arguments.get("pollutants")
            if isinstance(pollutants, list) and pollutants:
                pollutant = _clean_text(pollutants[0])
                if pollutant:
                    return pollutant
        result = item.get("result") or {}
        data = result.get("data") if isinstance(result, dict) else {}
        query_info = data.get("query_info") if isinstance(data, dict) else {}
        if isinstance(query_info, dict):
            pollutant = _clean_text(query_info.get("pollutant"))
            if pollutant:
                return pollutant
            pollutants = query_info.get("pollutants")
            if isinstance(pollutants, list) and pollutants:
                pollutant = _clean_text(pollutants[0])
                if pollutant:
                    return pollutant
    return None


def _classify_download_artifact(download_payload: Any) -> tuple[ArtifactType, Optional[str], Optional[str], Optional[str]]:
    payload = _clean_dict(download_payload)
    filename = _clean_text(payload.get("filename") or payload.get("path"))
    filename_lower = str(filename or "").lower()
    if "top" in filename_lower or "summary" in filename_lower or "rank" in filename_lower:
        return ArtifactType.TOPK_SUMMARY_TABLE, filename, "topk", "已提供可下载的摘要/Top-K 结果文件。"
    return ArtifactType.DETAILED_CSV, filename, "full_table", "已提供可下载的详细结果文件。"


def _classify_table_artifact(
    table_payload: Any,
    *,
    source_tool_name: Optional[str],
) -> tuple[ArtifactType, Optional[str], Optional[str]]:
    payload = _clean_dict(table_payload)
    payload_type = str(payload.get("type") or "").strip().lower()
    if any(token in payload_type for token in ("top", "rank", "summary", "hotspot")):
        return ArtifactType.TOPK_SUMMARY_TABLE, "topk", "已提供摘要表或 Top-K 结果表。"
    if source_tool_name in {"analyze_hotspots", "compare_scenarios"}:
        return ArtifactType.TOPK_SUMMARY_TABLE, "topk", "已提供摘要表或 Top-K 结果表。"
    return ArtifactType.UNKNOWN, None, None


def _iter_map_payloads(map_payload: Any) -> Iterable[Dict[str, Any]]:
    if not isinstance(map_payload, dict) or not map_payload:
        return []
    if map_payload.get("type") == "map_collection" and isinstance(map_payload.get("items"), list):
        return [dict(item) for item in map_payload.get("items") if isinstance(item, dict)]
    return [dict(map_payload)]


def _classify_map_artifact(map_payload: Dict[str, Any]) -> tuple[ArtifactType, Optional[str]]:
    map_type = str(map_payload.get("type") or "").strip().lower()
    if map_type in {"macro_emission_map", "emission"}:
        return ArtifactType.SPATIAL_MAP, "已提供排放空间地图。"
    if map_type in {"raster", "concentration", "points", "dispersion"}:
        return ArtifactType.DISPERSION_MAP, "已提供扩散浓度空间地图。"
    if map_type == "hotspot":
        return ArtifactType.HOTSPOT_MAP, "已提供热点空间地图。"
    return ArtifactType.UNKNOWN, None


def _dedupe_records(records: Sequence[ArtifactRecord]) -> List[ArtifactRecord]:
    deduped: Dict[tuple[str, str, str, str], ArtifactRecord] = {}
    for record in records:
        key = (
            record.artifact_type.value,
            record.artifact_family.value,
            record.source_tool_name or "",
            record.related_scope or "",
        )
        deduped[key] = record
    return list(deduped.values())


def classify_artifacts_from_delivery(
    *,
    tool_results: Sequence[Dict[str, Any]],
    frontend_payloads: Optional[Dict[str, Any]],
    response_text: Optional[str],
    delivery_turn_index: int,
    related_task_type: Optional[str],
    track_textual_summary: bool = True,
) -> List[ArtifactRecord]:
    payloads = dict(frontend_payloads or {})
    related_pollutant = _extract_first_pollutant(tool_results)
    records: List[ArtifactRecord] = []
    source_tool_name = _clean_text(tool_results[-1].get("name")) if tool_results else None

    download_payload = payloads.get("download_file")
    if download_payload:
        artifact_type, file_ref, scope, summary = _classify_download_artifact(download_payload)
        records.append(
            build_artifact_record(
                artifact_type=artifact_type,
                delivery_turn_index=delivery_turn_index,
                source_tool_name=source_tool_name,
                delivery_status=ArtifactDeliveryStatus.FULL,
                file_ref=file_ref,
                download_ref=_clean_dict(download_payload) or None,
                summary=summary,
                related_task_type=related_task_type,
                related_pollutant=related_pollutant,
                related_scope=scope,
            )
        )

    table_payload = payloads.get("table_data")
    if table_payload:
        table_type, scope, summary = _classify_table_artifact(
            table_payload,
            source_tool_name=source_tool_name,
        )
        if table_type != ArtifactType.UNKNOWN:
            records.append(
                build_artifact_record(
                    artifact_type=table_type,
                    delivery_turn_index=delivery_turn_index,
                    source_tool_name=source_tool_name,
                    delivery_status=ArtifactDeliveryStatus.PARTIAL,
                    summary=summary,
                    related_task_type=related_task_type,
                    related_pollutant=related_pollutant,
                    related_scope=scope,
                )
            )

    chart_payload = payloads.get("chart_data")
    if isinstance(chart_payload, dict) and chart_payload:
        records.append(
            build_artifact_record(
                artifact_type=ArtifactType.RANKED_CHART,
                delivery_turn_index=delivery_turn_index,
                source_tool_name=source_tool_name,
                delivery_status=ArtifactDeliveryStatus.FULL,
                summary="已提供结果图表。",
                related_task_type=related_task_type,
                related_pollutant=related_pollutant,
            )
        )

    for map_item in _iter_map_payloads(payloads.get("map_data")):
        artifact_type, summary = _classify_map_artifact(map_item)
        if artifact_type == ArtifactType.UNKNOWN:
            continue
        records.append(
            build_artifact_record(
                artifact_type=artifact_type,
                delivery_turn_index=delivery_turn_index,
                source_tool_name="render_spatial_map",
                delivery_status=ArtifactDeliveryStatus.FULL,
                summary=summary,
                related_task_type=related_task_type,
                related_pollutant=related_pollutant,
            )
        )

    for item in tool_results:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").strip() != "compare_scenarios":
            continue
        result = item.get("result") or {}
        if isinstance(result, dict) and result.get("success"):
            records.append(
                build_artifact_record(
                    artifact_type=ArtifactType.COMPARISON_RESULT,
                    delivery_turn_index=delivery_turn_index,
                    source_tool_name="compare_scenarios",
                    delivery_status=ArtifactDeliveryStatus.FULL,
                    summary="已提供情景对比结果。",
                    related_task_type=related_task_type,
                    related_pollutant=related_pollutant,
                )
            )

    if track_textual_summary:
        text = _clean_text(response_text)
        if text:
            status = (
                ArtifactDeliveryStatus.PARTIAL
                if records
                else ArtifactDeliveryStatus.FULL
            )
            records.append(
                build_artifact_record(
                    artifact_type=ArtifactType.QUICK_SUMMARY_TEXT,
                    delivery_turn_index=delivery_turn_index,
                    source_tool_name=source_tool_name,
                    delivery_status=status,
                    summary=text[:160],
                    related_task_type=related_task_type,
                    related_pollutant=related_pollutant,
                )
            )

    return _dedupe_records(records)


def update_artifact_memory(
    current_state: Optional[ArtifactMemoryState],
    records: Sequence[ArtifactRecord],
) -> ArtifactMemoryState:
    state = coerce_artifact_memory_state(current_state)
    state.append(records)
    return state


def _requested_artifact_from_intent(
    intent_plan: Optional[IntentResolutionApplicationPlan],
) -> tuple[Optional[ArtifactType], Optional[ArtifactFamily]]:
    if intent_plan is None:
        return None, None

    for action_id in intent_plan.preferred_action_ids:
        artifact_type = artifact_type_for_action_id(action_id)
        if artifact_type is not None:
            return artifact_type, artifact_family_for_type(artifact_type)

    deliverable = intent_plan.deliverable_intent.value
    if deliverable == "downloadable_table":
        return ArtifactType.DETAILED_CSV, ArtifactFamily.DOWNLOADABLE_TABLE
    if deliverable == "chart_or_ranked_summary":
        return ArtifactType.RANKED_CHART, ArtifactFamily.RANKED_SUMMARY
    if deliverable == "spatial_map":
        return None, ArtifactFamily.SPATIAL_VISUALIZATION
    if deliverable in {"quick_summary", "rough_estimate"}:
        return ArtifactType.QUICK_SUMMARY_TEXT, ArtifactFamily.TEXTUAL_SUMMARY
    if deliverable == "scenario_comparison":
        return ArtifactType.COMPARISON_RESULT, ArtifactFamily.COMPARISON_OUTPUT
    return None, None


def build_artifact_availability_decision(
    memory_state: Optional[ArtifactMemoryState],
    *,
    requested_type: Optional[ArtifactType] = None,
    requested_family: Optional[ArtifactFamily] = None,
) -> ArtifactAvailabilityDecision:
    state = coerce_artifact_memory_state(memory_state)
    matching_record = (
        state.find_latest_type(requested_type, status=ArtifactDeliveryStatus.FULL)
        if requested_type is not None
        else None
    )
    family_record = (
        state.find_latest_family(requested_family, status=ArtifactDeliveryStatus.FULL)
        if requested_family is not None
        else None
    )
    same_type = matching_record is not None
    same_family = family_record is not None
    explanation = None
    if same_type and requested_type is not None:
        explanation = f"{requested_type.value} was already fully delivered."
    elif same_family and requested_family is not None:
        explanation = f"{requested_family.value} already has a delivered artifact in memory."
    return ArtifactAvailabilityDecision(
        requested_type=requested_type,
        requested_family=requested_family,
        same_type_full_provided=same_type,
        same_family_full_provided=same_family,
        matching_record=matching_record,
        family_record=family_record,
        should_suppress_repeat=same_type,
        should_promote_new_family=(same_family and not same_type),
        explanation=explanation,
    )


def _scan_repeated_available_actions(
    memory_state: ArtifactMemoryState,
    capability_summary: Optional[Dict[str, Any]],
) -> tuple[List[str], List[str], List[str]]:
    if not isinstance(capability_summary, dict):
        return [], [], []
    suppressed: List[str] = []
    repeated_types: List[str] = []
    repeated_families: List[str] = []
    for item in capability_summary.get("available_next_actions") or []:
        if not isinstance(item, dict):
            continue
        action_id = _clean_text(item.get("action_id"))
        artifact_type = artifact_type_for_action_id(action_id)
        if artifact_type is None:
            continue
        matching_record = memory_state.find_latest_type(
            artifact_type,
            status=ArtifactDeliveryStatus.FULL,
        )
        if matching_record is None:
            continue
        if action_id and action_id not in suppressed:
            suppressed.append(action_id)
        if artifact_type.value not in repeated_types:
            repeated_types.append(artifact_type.value)
        family_value = artifact_family_for_type(artifact_type).value
        if family_value not in repeated_families:
            repeated_families.append(family_value)
    return suppressed, repeated_types, repeated_families


def _promote_requested_family_if_partial_summary_exists(
    memory_state: ArtifactMemoryState,
    requested_family: Optional[ArtifactFamily],
) -> bool:
    if requested_family is None or requested_family == ArtifactFamily.TEXTUAL_SUMMARY:
        return False
    text_record = memory_state.find_latest_type(ArtifactType.QUICK_SUMMARY_TEXT)
    if text_record is None:
        return False
    return text_record.delivery_status == ArtifactDeliveryStatus.PARTIAL


def build_artifact_suggestion_plan(
    memory_state: Optional[ArtifactMemoryState],
    capability_summary: Optional[Dict[str, Any]],
    intent_plan: Optional[IntentResolutionApplicationPlan],
    *,
    dedup_by_family: bool = True,
) -> ArtifactSuggestionPlan:
    state = coerce_artifact_memory_state(memory_state)
    requested_type, requested_family = _requested_artifact_from_intent(intent_plan)
    availability = build_artifact_availability_decision(
        state,
        requested_type=requested_type,
        requested_family=requested_family,
    )
    suppressed_action_ids, repeated_types, repeated_families = _scan_repeated_available_actions(
        state,
        capability_summary,
    )
    promoted_families: List[str] = []
    notes: List[str] = []
    user_visible_summary: Optional[str] = None

    if availability.should_suppress_repeat and availability.matching_record is not None:
        repeated_type = availability.matching_record.artifact_type.value
        if repeated_type not in repeated_types:
            repeated_types.append(repeated_type)
        family_value = availability.matching_record.artifact_family.value
        if family_value not in repeated_families:
            repeated_families.append(family_value)
        action_id = availability.matching_record.source_action_id or _DEFAULT_ACTION_BY_TYPE.get(
            availability.matching_record.artifact_type
        )
        if action_id and action_id not in suppressed_action_ids:
            suppressed_action_ids.append(action_id)
        summary = _clean_text(availability.matching_record.summary)
        user_visible_summary = summary or "当前请求的交付物已经完整提供过，下一步更适合切换为另一种输出形式。"
        notes.append("exact_artifact_repeat_detected")

    elif (
        dedup_by_family
        and
        availability.should_promote_new_family
        and requested_family is not None
        and requested_family.value not in promoted_families
    ):
        promoted_families.append(requested_family.value)
        notes.append("same_family_different_type")
        family_record = availability.family_record
        family_label = family_record.artifact_type.value if family_record is not None else requested_family.value
        if requested_type is not None:
            user_visible_summary = (
                f"当前已提供同一交付族的 {family_label}，如需换一种形式展示，可继续切到 {requested_type.value}。"
            )

    if _promote_requested_family_if_partial_summary_exists(state, requested_family):
        if requested_family is not None and requested_family.value not in promoted_families:
            promoted_families.append(requested_family.value)
        notes.append("partial_summary_can_expand")
        if user_visible_summary is None and requested_family is not None:
            user_visible_summary = (
                f"当前已有文本摘要，可继续补成 {requested_family.value} 这类更完整的交付。"
            )

    if suppressed_action_ids and user_visible_summary is None:
        user_visible_summary = "部分同类交付物已经完整提供，后续建议将优先切换为新的输出形式。"
        notes.append("repeated_available_action_suppressed")

    return ArtifactSuggestionPlan(
        suppressed_action_ids=list(dict.fromkeys(suppressed_action_ids)),
        promoted_action_ids=[],
        promoted_families=list(dict.fromkeys(promoted_families)),
        repeated_artifact_types=list(dict.fromkeys(repeated_types)),
        repeated_artifact_families=list(dict.fromkeys(repeated_families)),
        user_visible_summary=user_visible_summary,
        notes=list(dict.fromkeys(notes)),
        availability_decision=availability,
    )


def apply_artifact_memory_to_capability_summary(
    summary: Optional[Dict[str, Any]],
    memory_state: Optional[ArtifactMemoryState],
    intent_plan: Optional[IntentResolutionApplicationPlan],
    *,
    dedup_by_family: bool = True,
) -> Optional[Dict[str, Any]]:
    if not isinstance(summary, dict):
        return summary
    state = coerce_artifact_memory_state(memory_state)
    if not state.artifacts:
        biased = dict(summary)
        biased["artifact_memory"] = state.to_summary()
        return biased

    suggestion_plan = build_artifact_suggestion_plan(
        state,
        capability_summary=summary,
        intent_plan=intent_plan,
        dedup_by_family=dedup_by_family,
    )
    suppressed = set(suggestion_plan.suppressed_action_ids)

    def _filter_items(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        filtered: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            action_id = _clean_text(item.get("action_id"))
            if action_id and action_id in suppressed:
                continue
            filtered.append(dict(item))
        return filtered

    biased = dict(summary)
    biased["available_next_actions"] = _filter_items(summary.get("available_next_actions") or [])
    hints = [
        str(item).strip()
        for item in (summary.get("guidance_hints") or [])
        if str(item).strip()
    ]
    if suggestion_plan.user_visible_summary and suggestion_plan.user_visible_summary not in hints:
        hints.insert(0, suggestion_plan.user_visible_summary)
    biased["guidance_hints"] = hints
    biased["artifact_memory"] = state.to_summary()
    biased["artifact_bias"] = suggestion_plan.to_dict()
    return biased
```
## 4. 全局配置

### 4.1 `AppConfig` / `Config`

无法确认 `AppConfig`：[config.py](/home/kirito/Agent1/emission_agent/config.py#L17) 当前定义的是 `Config`，行 17-264；同文件还定义了 `LLMAssignment`，行 10-14。

```python
import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()
PROJECT_ROOT = Path(__file__).parent

@dataclass
class LLMAssignment:
    provider: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 8000  # Increased to 8000 for complex multi-tool synthesis responses

@dataclass
class Config:
    def __post_init__(self):
        self.providers = {
            "qwen": {"api_key": os.getenv("QWEN_API_KEY"), "base_url": os.getenv("QWEN_BASE_URL")},
            "deepseek": {"api_key": os.getenv("DEEPSEEK_API_KEY"), "base_url": os.getenv("DEEPSEEK_BASE_URL")},
            "local": {"api_key": os.getenv("LOCAL_LLM_API_KEY"), "base_url": os.getenv("LOCAL_LLM_BASE_URL")},
        }

        self.agent_llm = LLMAssignment(
            provider=os.getenv("AGENT_LLM_PROVIDER", "qwen"),
            model=os.getenv("AGENT_LLM_MODEL", "qwen-plus"),
            temperature=0.0  # v2.0+: 降低temperature提高确定性
        )
        self.standardizer_llm = LLMAssignment(
            provider=os.getenv("STANDARDIZER_LLM_PROVIDER", "qwen"),
            model=os.getenv("STANDARDIZER_LLM_MODEL", "qwen-turbo-latest"),
            temperature=0.1, max_tokens=200
        )
        self.synthesis_llm = LLMAssignment(
            provider=os.getenv("SYNTHESIS_LLM_PROVIDER", "qwen"),
            model=os.getenv("SYNTHESIS_LLM_MODEL", "qwen-plus")
        )
        self.rag_refiner_llm = LLMAssignment(
            provider=os.getenv("RAG_REFINER_LLM_PROVIDER", "qwen"),
            model=os.getenv("RAG_REFINER_LLM_MODEL", "qwen-plus")
        )

        self.enable_llm_standardization = os.getenv("ENABLE_LLM_STANDARDIZATION", "true").lower() == "true"
        self.enable_standardization_cache = os.getenv("ENABLE_STANDARDIZATION_CACHE", "true").lower() == "true"
        self.enable_data_collection = os.getenv("ENABLE_DATA_COLLECTION", "true").lower() == "true"
        self.enable_file_analyzer = os.getenv("ENABLE_FILE_ANALYZER", "true").lower() == "true"
        self.enable_file_context_injection = os.getenv("ENABLE_FILE_CONTEXT_INJECTION", "true").lower() == "true"
        self.enable_executor_standardization = os.getenv("ENABLE_EXECUTOR_STANDARDIZATION", "true").lower() == "true"
        self.enable_state_orchestration = os.getenv("ENABLE_STATE_ORCHESTRATION", "true").lower() == "true"
        self.enable_trace = os.getenv("ENABLE_TRACE", "true").lower() == "true"
        self.enable_lightweight_planning = os.getenv("ENABLE_LIGHTWEIGHT_PLANNING", "false").lower() == "true"
        self.enable_bounded_plan_repair = os.getenv("ENABLE_BOUNDED_PLAN_REPAIR", "false").lower() == "true"
        self.enable_repair_aware_continuation = os.getenv("ENABLE_REPAIR_AWARE_CONTINUATION", "false").lower() == "true"
        self.enable_parameter_negotiation = os.getenv("ENABLE_PARAMETER_NEGOTIATION", "false").lower() == "true"
        self.enable_file_analysis_llm_fallback = os.getenv("ENABLE_FILE_ANALYSIS_LLM_FALLBACK", "false").lower() == "true"
        self.enable_workflow_templates = os.getenv("ENABLE_WORKFLOW_TEMPLATES", "false").lower() == "true"
        self.enable_capability_aware_synthesis = (
            os.getenv("ENABLE_CAPABILITY_AWARE_SYNTHESIS", "true").lower() == "true"
        )
        self.enable_readiness_gating = os.getenv("ENABLE_READINESS_GATING", "true").lower() == "true"
        self.readiness_repairable_enabled = (
            os.getenv("READINESS_REPAIRABLE_ENABLED", "true").lower() == "true"
        )
        self.readiness_already_provided_dedup_enabled = (
            os.getenv("READINESS_ALREADY_PROVIDED_DEDUP_ENABLED", "true").lower() == "true"
        )
        self.enable_input_completion_flow = (
            os.getenv("ENABLE_INPUT_COMPLETION_FLOW", "true").lower() == "true"
        )
        self.input_completion_max_options = int(
            os.getenv("INPUT_COMPLETION_MAX_OPTIONS", "4")
        )
        self.input_completion_allow_uniform_scalar = (
            os.getenv("INPUT_COMPLETION_ALLOW_UNIFORM_SCALAR", "true").lower() == "true"
        )
        self.input_completion_allow_upload_support_file = (
            os.getenv("INPUT_COMPLETION_ALLOW_UPLOAD_SUPPORT_FILE", "true").lower() == "true"
        )
        self.enable_geometry_recovery_path = (
            os.getenv("ENABLE_GEOMETRY_RECOVERY_PATH", "true").lower() == "true"
        )
        self.enable_file_relationship_resolution = (
            os.getenv("ENABLE_FILE_RELATIONSHIP_RESOLUTION", "true").lower() == "true"
        )
        self.file_relationship_resolution_require_new_upload = (
            os.getenv("FILE_RELATIONSHIP_RESOLUTION_REQUIRE_NEW_UPLOAD", "true").lower() == "true"
        )
        self.file_relationship_resolution_allow_llm_fallback = (
            os.getenv("FILE_RELATIONSHIP_RESOLUTION_ALLOW_LLM_FALLBACK", "true").lower() == "true"
        )
        self.enable_supplemental_column_merge = (
            os.getenv("ENABLE_SUPPLEMENTAL_COLUMN_MERGE", "true").lower() == "true"
        )
        self.supplemental_merge_allow_alias_keys = (
            os.getenv("SUPPLEMENTAL_MERGE_ALLOW_ALIAS_KEYS", "true").lower() == "true"
        )
        self.supplemental_merge_require_readiness_refresh = (
            os.getenv("SUPPLEMENTAL_MERGE_REQUIRE_READINESS_REFRESH", "true").lower() == "true"
        )
        self.enable_intent_resolution = (
            os.getenv("ENABLE_INTENT_RESOLUTION", "true").lower() == "true"
        )
        self.intent_resolution_allow_llm_fallback = (
            os.getenv("INTENT_RESOLUTION_ALLOW_LLM_FALLBACK", "true").lower() == "true"
        )
        self.intent_resolution_bias_followup_suggestions = (
            os.getenv("INTENT_RESOLUTION_BIAS_FOLLOWUP_SUGGESTIONS", "true").lower() == "true"
        )
        self.intent_resolution_bias_continuation = (
            os.getenv("INTENT_RESOLUTION_BIAS_CONTINUATION", "true").lower() == "true"
        )
        self.enable_artifact_memory = (
            os.getenv("ENABLE_ARTIFACT_MEMORY", "true").lower() == "true"
        )
        self.artifact_memory_track_textual_summary = (
            os.getenv("ARTIFACT_MEMORY_TRACK_TEXTUAL_SUMMARY", "true").lower() == "true"
        )
        self.artifact_memory_dedup_by_family = (
            os.getenv("ARTIFACT_MEMORY_DEDUP_BY_FAMILY", "true").lower() == "true"
        )
        self.artifact_memory_bias_followup = (
            os.getenv("ARTIFACT_MEMORY_BIAS_FOLLOWUP", "true").lower() == "true"
        )
        self.enable_summary_delivery_surface = (
            os.getenv("ENABLE_SUMMARY_DELIVERY_SURFACE", "true").lower() == "true"
        )
        self.summary_delivery_enable_bar_chart = (
            os.getenv("SUMMARY_DELIVERY_ENABLE_BAR_CHART", "true").lower() == "true"
        )
        self.summary_delivery_default_topk = int(
            os.getenv("SUMMARY_DELIVERY_DEFAULT_TOPK", "5")
        )
        self.summary_delivery_allow_text_fallback = (
            os.getenv("SUMMARY_DELIVERY_ALLOW_TEXT_FALLBACK", "true").lower() == "true"
        )
        self.geometry_recovery_supported_file_types = tuple(
            item.strip().lower()
            for item in os.getenv(
                "GEOMETRY_RECOVERY_SUPPORTED_FILE_TYPES",
                "geojson,json,shp,zip,csv,xlsx,xls",
            ).split(",")
            if item.strip()
        )
        self.geometry_recovery_require_readiness_refresh = (
            os.getenv("GEOMETRY_RECOVERY_REQUIRE_READINESS_REFRESH", "true").lower() == "true"
        )
        self.enable_residual_reentry_controller = (
            os.getenv("ENABLE_RESIDUAL_REENTRY_CONTROLLER", "true").lower() == "true"
        )
        self.residual_reentry_require_ready_target = (
            os.getenv("RESIDUAL_REENTRY_REQUIRE_READY_TARGET", "true").lower() == "true"
        )
        self.residual_reentry_prioritize_recovery_target = (
            os.getenv("RESIDUAL_REENTRY_PRIORITIZE_RECOVERY_TARGET", "true").lower() == "true"
        )
        self.enable_policy_based_remediation = (
            os.getenv("ENABLE_POLICY_BASED_REMEDIATION", "true").lower() == "true"
        )
        self.enable_default_typical_profile_policy = (
            os.getenv("ENABLE_DEFAULT_TYPICAL_PROFILE_POLICY", "true").lower() == "true"
        )
        self.default_typical_profile_allowed_task_types = tuple(
            item.strip().lower()
            for item in os.getenv(
                "DEFAULT_TYPICAL_PROFILE_ALLOWED_TASK_TYPES",
                "macro_emission",
            ).split(",")
            if item.strip()
        )
        self.workflow_template_max_recommendations = int(
            os.getenv("WORKFLOW_TEMPLATE_MAX_RECOMMENDATIONS", "3")
        )
        self.workflow_template_min_confidence = float(
            os.getenv("WORKFLOW_TEMPLATE_MIN_CONFIDENCE", "0.55")
        )
        self.file_analysis_fallback_confidence_threshold = float(
            os.getenv("FILE_ANALYSIS_FALLBACK_CONFIDENCE_THRESHOLD", "0.72")
        )
        self.file_analysis_fallback_max_sample_rows = int(
            os.getenv("FILE_ANALYSIS_FALLBACK_MAX_SAMPLE_ROWS", "3")
        )
        self.file_analysis_fallback_max_columns = int(
            os.getenv("FILE_ANALYSIS_FALLBACK_MAX_COLUMNS", "25")
        )
        self.file_analysis_fallback_allow_zip_table_selection = (
            os.getenv("FILE_ANALYSIS_FALLBACK_ALLOW_ZIP_TABLE_SELECTION", "true").lower() == "true"
        )
        self.parameter_negotiation_confidence_threshold = float(
            os.getenv("PARAMETER_NEGOTIATION_CONFIDENCE_THRESHOLD", "0.85")
        )
        self.parameter_negotiation_max_candidates = int(
            os.getenv("PARAMETER_NEGOTIATION_MAX_CANDIDATES", "5")
        )
        self.continuation_prompt_variant = (
            os.getenv("CONTINUATION_PROMPT_VARIANT", "balanced_repair_aware").strip().lower()
            or "balanced_repair_aware"
        )
        self.enable_builtin_map_data = os.getenv("ENABLE_BUILTIN_MAP_DATA", "false").lower() == "true"
        self.enable_skill_injection = os.getenv("ENABLE_SKILL_INJECTION", "true").lower() == "true"
        self.max_orchestration_steps = int(os.getenv("MAX_ORCHESTRATION_STEPS", "4"))
        self.macro_column_mapping_modes = tuple(
            mode.strip().lower()
            for mode in os.getenv("MACRO_COLUMN_MAPPING_MODES", "direct,ai,fuzzy").split(",")
            if mode.strip()
        )
        self.standardization_config = {
            "llm_enabled": os.getenv(
                "STANDARDIZATION_LLM_ENABLED",
                "true" if self.enable_llm_standardization else "false",
            ).lower() == "true",
            "llm_backend": os.getenv("STANDARDIZATION_LLM_BACKEND", "api").lower(),
            "llm_model": os.getenv("STANDARDIZATION_LLM_MODEL") or None,
            "llm_timeout": float(os.getenv("STANDARDIZATION_LLM_TIMEOUT", "5.0")),
            "llm_max_retries": int(os.getenv("STANDARDIZATION_LLM_MAX_RETRIES", "1")),
            "fuzzy_threshold": float(os.getenv("STANDARDIZATION_FUZZY_THRESHOLD", "0.7")),
            "parameter_negotiation_enabled": self.enable_parameter_negotiation,
            "parameter_negotiation_confidence_threshold": self.parameter_negotiation_confidence_threshold,
            "parameter_negotiation_max_candidates": self.parameter_negotiation_max_candidates,
            "local_model_path": os.getenv("STANDARDIZATION_LOCAL_MODEL_PATH") or None,
        }

        self.data_collection_dir = PROJECT_ROOT / os.getenv("DATA_COLLECTION_DIR", "data/collection")
        self.log_dir = PROJECT_ROOT / os.getenv("LOG_DIR", "data/logs")
        self.outputs_dir = PROJECT_ROOT / os.getenv("OUTPUTS_DIR", "outputs")

        self.data_collection_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)

        # 代理设置
        self.http_proxy = os.getenv("HTTP_PROXY", "")
        self.https_proxy = os.getenv("HTTPS_PROXY", "")

        # ============ 本地标准化模型配置 ============
        self.use_local_standardizer = os.getenv("USE_LOCAL_STANDARDIZER", "false").lower() == "true"

        self.local_standardizer_config = {
            "enabled": self.use_local_standardizer,
            "mode": os.getenv("LOCAL_STANDARDIZER_MODE", "direct"),  # "direct" or "vllm"
            "base_model": os.getenv("LOCAL_STANDARDIZER_BASE_MODEL", "Qwen/Qwen2.5-3B-Instruct"),
            "unified_lora": os.getenv("LOCAL_STANDARDIZER_UNIFIED_LORA", "./LOCAL_STANDARDIZER_MODEL/models/unified_lora/final"),
            "column_lora": os.getenv("LOCAL_STANDARDIZER_COLUMN_LORA", "./LOCAL_STANDARDIZER_MODEL/models/column_lora/checkpoint-200"),
            "device": os.getenv("LOCAL_STANDARDIZER_DEVICE", "cuda"),  # "cuda" or "cpu"
            "max_length": int(os.getenv("LOCAL_STANDARDIZER_MAX_LENGTH", "256")),
            "vllm_url": os.getenv("LOCAL_STANDARDIZER_VLLM_URL", "http://localhost:8001"),
        }

        # ============ RAG配置 ============
        # Embedding模式: "api" 或 "local"
        self.embedding_mode = os.getenv("EMBEDDING_MODE", "api").lower()

        # Rerank模式: "api", "local" 或 "none"
        self.rerank_mode = os.getenv("RERANK_MODE", "api").lower()

        # API模式下的模型配置
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
        self.embedding_dimension = int(os.getenv("EMBEDDING_DIMENSION", "1024"))
        self.rerank_model = os.getenv("RERANK_MODEL", "gte-rerank")
        self.rerank_top_n = int(os.getenv("RERANK_TOP_N", "5"))

    def is_macro_mapping_mode_enabled(self, mode: str) -> bool:
        """Return whether a macro column-mapping stage is enabled."""
        return mode.strip().lower() in self.macro_column_mapping_modes

_config = None
def get_config():
    global _config
    if _config is None:
        _config = Config()
    return _config


def reset_config():
    """Reset cached config so new env/runtime overrides can take effect."""
    global _config
    _config = None
```
### 4.2 `.env.example` 完整内容

文件：[.env.example](/home/kirito/Agent1/emission_agent/.env.example#L1)，行 1-64。

```dotenv
# Minimal setup notes:
# 1. Copy this file to `.env`.
# 2. `python main.py health` and most local tests can run without real provider keys.
# 3. For normal chat usage in `python run_api.py` or other live-LLM paths, set at least one real provider key.
# 4. Some evaluation paths may also need real provider access depending on the runner and flags you choose.
# 5. Unused providers can remain as placeholders.
#
# ============ LLM Provider 配置 ============
# 支持的Provider: qwen, deepseek, local (自定义兼容OpenAI API的服务)

# ===== Qwen (通义千问) =====
# 获取地址: https://dashscope.console.aliyun.com/
QWEN_API_KEY=sk-xxx
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
# 可用模型: qwen-max, qwen-plus, qwen-turbo, qwen-turbo-latest, qwen-long
QWEN_MODELS={"max": "qwen-max", "plus": "qwen-plus", "turbo": "qwen-turbo-latest"}

# ===== DeepSeek =====
# 获取地址: https://platform.deepseek.com/
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
# 可用模型: deepseek-chat, deepseek-coder
DEEPSEEK_MODELS={"chat": "deepseek-chat", "coder": "deepseek-coder"}

# ===== 本地/自定义 LLM (兼容OpenAI API) =====
LOCAL_LLM_API_KEY=not-needed
LOCAL_LLM_BASE_URL=http://localhost:8000/v1
LOCAL_LLM_MODEL=local-model

# ============ 模型分配 (按用途配置) ============
# Agent Planning层 (需要推理能力，推荐qwen-plus或deepseek-chat)
AGENT_LLM_PROVIDER=qwen
AGENT_LLM_MODEL=qwen-plus

# 标准化层 (简单分类，追求速度，推荐qwen-turbo)
STANDARDIZER_LLM_PROVIDER=qwen
STANDARDIZER_LLM_MODEL=qwen-turbo-latest

# 综合层 (生成回复，推荐qwen-plus)
SYNTHESIS_LLM_PROVIDER=qwen
SYNTHESIS_LLM_MODEL=qwen-plus

# RAG精炼层 (知识总结，推荐qwen-max以获得最佳质量)
RAG_REFINER_LLM_PROVIDER=qwen
RAG_REFINER_LLM_MODEL=qwen-max

# ============ 功能开关 ============
ENABLE_LLM_STANDARDIZATION=true
ENABLE_STANDARDIZATION_CACHE=true
ENABLE_DATA_COLLECTION=true
ENABLE_FILE_ANALYZER=true
ENABLE_FILE_CONTEXT_INJECTION=true
ENABLE_EXECUTOR_STANDARDIZATION=true

# ============ 安全配置 ============
# IMPORTANT: Set a strong random secret for production deployments.
# Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"
JWT_SECRET_KEY=change-me-to-a-strong-random-secret

# ============ 其他 ============
PORT=8000
DATA_COLLECTION_DIR=data/collection
LOG_DIR=data/logs
LOG_LEVEL=INFO
```
### 4.3 通过 `config` 控制的功能开关

说明：以下条目基于 `config.py` 中 `Config.__post_init__()` 的布尔/布尔语义字段抽取；“检查语句”优先列出非测试 Python 文件中的 `if` 条件头，若静态扫描未发现 `if` 条件，则列出运行时代码中的命中行。

#### `enable_llm_standardization`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L44) `Config.__post_init__()` 行 44。
- 默认值表达式：`os.getenv("ENABLE_LLM_STANDARDIZATION", "true").lower() == "true"`
- 控制行为：当前仅能从字段名和使用位置确认其控制相关分支；更细粒度意图无法确认。
- 运行时代码命中（静态扫描未抽出 `if` 条件头）：
  - [shared/standardizer/vehicle.py](/home/kirito/Agent1/emission_agent/shared/standardizer/vehicle.py#L49) 行 49：`cls._instance._llm = get_llm("standardizer") if config.enable_llm_standardization else None`
  - [shared/standardizer/vehicle.py](/home/kirito/Agent1/emission_agent/shared/standardizer/vehicle.py#L55) 行 55：`cls._instance._enable_llm = config.enable_llm_standardization or config.use_local_standardizer`
  - [shared/standardizer/pollutant.py](/home/kirito/Agent1/emission_agent/shared/standardizer/pollutant.py#L49) 行 49：`cls._instance._llm = get_llm("standardizer") if config.enable_llm_standardization else None`
  - [shared/standardizer/pollutant.py](/home/kirito/Agent1/emission_agent/shared/standardizer/pollutant.py#L55) 行 55：`cls._instance._enable_llm = config.enable_llm_standardization or config.use_local_standardizer`

#### `enable_standardization_cache`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L45) `Config.__post_init__()` 行 45。
- 默认值表达式：`os.getenv("ENABLE_STANDARDIZATION_CACHE", "true").lower() == "true"`
- 控制行为：当前仅能从字段名和使用位置确认其控制相关分支；更细粒度意图无法确认。
- 检查语句：本次静态扫描未在非测试 Python 文件中发现直接检查语句。

#### `enable_data_collection`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L46) `Config.__post_init__()` 行 46。
- 默认值表达式：`os.getenv("ENABLE_DATA_COLLECTION", "true").lower() == "true"`
- 控制行为：当前仅能从字段名和使用位置确认其控制相关分支；更细粒度意图无法确认。
- 运行时代码命中（静态扫描未抽出 `if` 条件头）：
  - [llm/data_collector.py](/home/kirito/Agent1/emission_agent/llm/data_collector.py#L14) 行 14：`cls._instance.enabled = config.enable_data_collection`

#### `enable_file_analyzer`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L47) `Config.__post_init__()` 行 47。
- 默认值表达式：`os.getenv("ENABLE_FILE_ANALYZER", "true").lower() == "true"`
- 控制行为：控制 router/evaluation 是否执行文件分析。
- 检查语句：
  - [evaluation/eval_end2end.py](/home/kirito/Agent1/emission_agent/evaluation/eval_end2end.py#L86) 行 86
```python
                if file_path and enable_file_analyzer:
```
  - [evaluation/eval_file_grounding.py](/home/kirito/Agent1/emission_agent/evaluation/eval_file_grounding.py#L100) 行 100
```python
                if enable_file_analyzer:
```
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L1637) 行 1637
```python
        if getattr(self.runtime_config, "enable_file_analyzer", True):
```
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L767) 行 767
```python
            if self.runtime_config.enable_file_analyzer and cache_valid:
```
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L8347) 行 8347
```python
            if (
                self.runtime_config.enable_file_analyzer
                and isinstance(pending_relationship_analysis, dict)
                and str(pending_relationship_analysis.get("file_path") or "").strip() == file_path_str
            ):
```
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L770) 行 770
```python
            elif self.runtime_config.enable_file_analyzer:
```
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L8359) 行 8359
```python
            elif self.runtime_config.enable_file_analyzer and cache_valid:
```
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L8366) 行 8366
```python
            elif self.runtime_config.enable_file_analyzer:
```

#### `enable_file_context_injection`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L48) `Config.__post_init__()` 行 48。
- 默认值表达式：`os.getenv("ENABLE_FILE_CONTEXT_INJECTION", "true").lower() == "true"`
- 控制行为：控制 assembler 是否把 file context 注入 prompt。
- 检查语句：
  - [core/assembler.py](/home/kirito/Agent1/emission_agent/core/assembler.py#L236) 行 236
```python
        if file_context and self.runtime_config.enable_file_context_injection:
```

#### `enable_executor_standardization`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L49) `Config.__post_init__()` 行 49。
- 默认值表达式：`os.getenv("ENABLE_EXECUTOR_STANDARDIZATION", "true").lower() == "true"`
- 控制行为：控制 ToolExecutor 是否执行参数标准化。
- 检查语句：
  - [core/executor.py](/home/kirito/Agent1/emission_agent/core/executor.py#L335) 行 335
```python
        if not self.runtime_config.enable_executor_standardization:
```

#### `enable_state_orchestration`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L50) `Config.__post_init__()` 行 50。
- 默认值表达式：`os.getenv("ENABLE_STATE_ORCHESTRATION", "true").lower() == "true"`
- 控制行为：控制 `UnifiedRouter.chat()` 选择 `_run_state_loop()` 还是 `_run_legacy_loop()`。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L708) 行 708
```python
        if config.enable_state_orchestration:
```

#### `enable_trace`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L51) `Config.__post_init__()` 行 51。
- 默认值表达式：`os.getenv("ENABLE_TRACE", "true").lower() == "true"`
- 控制行为：控制是否创建/附带 `Trace` 结果，以及 API session 是否初始化 trace 容器。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L867) 行 867
```python
        if get_config().enable_trace and trace is not None:
```

#### `enable_lightweight_planning`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L52) `Config.__post_init__()` 行 52。
- 默认值表达式：`os.getenv("ENABLE_LIGHTWEIGHT_PLANNING", "false").lower() == "true"`
- 控制行为：控制状态编排路径是否在首次执行前生成轻量执行计划。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L3854) 行 3854
```python
        if not getattr(self.runtime_config, "enable_lightweight_planning", False):
```

#### `enable_bounded_plan_repair`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L53) `Config.__post_init__()` 行 53。
- 默认值表达式：`os.getenv("ENABLE_BOUNDED_PLAN_REPAIR", "false").lower() == "true"`
- 控制行为：控制执行阶段检测到计划偏离或依赖阻塞时是否尝试 plan repair。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L7140) 行 7140
```python
        if not getattr(self.runtime_config, "enable_bounded_plan_repair", False):
```

#### `enable_repair_aware_continuation`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L54) `Config.__post_init__()` 行 54。
- 默认值表达式：`os.getenv("ENABLE_REPAIR_AWARE_CONTINUATION", "false").lower() == "true"`
- 控制行为：控制 continuation 判定是否考虑 repair/residual plan 相关上下文。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L6329) 行 6329
```python
        if not getattr(self.runtime_config, "enable_repair_aware_continuation", False):
```

#### `enable_parameter_negotiation`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L55) `Config.__post_init__()` 行 55。
- 默认值表达式：`os.getenv("ENABLE_PARAMETER_NEGOTIATION", "false").lower() == "true"`
- 控制行为：控制标准化低置信度时是否进入参数协商。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L4147) 行 4147
```python
        if not getattr(self.runtime_config, "enable_parameter_negotiation", False):
```
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L6620) 行 6620
```python
        if request is None or not getattr(self.runtime_config, "enable_parameter_negotiation", False):
```

#### `enable_file_analysis_llm_fallback`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L56) `Config.__post_init__()` 行 56。
- 默认值表达式：`os.getenv("ENABLE_FILE_ANALYSIS_LLM_FALLBACK", "false").lower() == "true"`
- 控制行为：控制文件分析置信度不足时是否启用 LLM fallback。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L3518) 行 3518
```python
        if not getattr(self.runtime_config, "enable_file_analysis_llm_fallback", False):
```

#### `enable_workflow_templates`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L57) `Config.__post_init__()` 行 57。
- 默认值表达式：`os.getenv("ENABLE_WORKFLOW_TEMPLATES", "false").lower() == "true"`
- 控制行为：控制 router 是否推荐并注入 workflow template。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L8579) 行 8579
```python
        if getattr(self.runtime_config, "enable_workflow_templates", False) and (
            continuation_decision.should_continue or state.file_context.grounded
        ):
```

#### `enable_capability_aware_synthesis`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L58) `Config.__post_init__()` 行 58。
- 默认值表达式：`os.getenv("ENABLE_CAPABILITY_AWARE_SYNTHESIS", "true").lower() == "true"`
- 控制行为：控制 synthesis prompt 是否注入 capability summary 约束。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L7872) 行 7872
```python
        if purpose not in {"pre_execution", "input_completion_recheck", "intent_resolution"} and not getattr(
            self.runtime_config,
            "enable_capability_aware_synthesis",
            True,
        ):
```
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L8070) 行 8070
```python
        if not getattr(self.runtime_config, "enable_capability_aware_synthesis", True):
```

#### `enable_readiness_gating`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L61) `Config.__post_init__()` 行 61。
- 默认值表达式：`os.getenv("ENABLE_READINESS_GATING", "true").lower() == "true"`
- 控制行为：控制执行前 readiness assessment / gating。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L7860) 行 7860
```python
        if purpose in {"pre_execution", "input_completion_recheck"} and not getattr(
            self.runtime_config,
            "enable_readiness_gating",
            True,
        ):
```

#### `readiness_repairable_enabled`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L62) `Config.__post_init__()` 行 62。
- 默认值表达式：`os.getenv("READINESS_REPAIRABLE_ENABLED", "true").lower() == "true"`
- 控制行为：控制 readiness 结果是否允许返回 repairable affordance。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L8018) 行 8018
```python
        if not getattr(self.runtime_config, "readiness_repairable_enabled", True):
```

#### `readiness_already_provided_dedup_enabled`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L65) `Config.__post_init__()` 行 65。
- 默认值表达式：`os.getenv("READINESS_ALREADY_PROVIDED_DEDUP_ENABLED", "true").lower() == "true"`
- 控制行为：控制 readiness/capability summary 是否去重已交付 artifact。
- 运行时代码命中（静态扫描未抽出 `if` 条件头）：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L7895) 行 7895：`"readiness_already_provided_dedup_enabled",`

#### `enable_input_completion_flow`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L68) `Config.__post_init__()` 行 68。
- 默认值表达式：`os.getenv("ENABLE_INPUT_COMPLETION_FLOW", "true").lower() == "true"`
- 控制行为：控制缺失关键输入时是否进入 input completion 流程。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L4381) 行 4381
```python
        if not getattr(self.runtime_config, "enable_input_completion_flow", False):
```
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L4697) 行 4697
```python
        if request is None or not getattr(self.runtime_config, "enable_input_completion_flow", False):
```

#### `input_completion_allow_uniform_scalar`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L74) `Config.__post_init__()` 行 74。
- 默认值表达式：`os.getenv("INPUT_COMPLETION_ALLOW_UNIFORM_SCALAR", "true").lower() == "true"`
- 控制行为：控制 input completion 是否允许统一标量补全选项。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L4464) 行 4464
```python
                if getattr(self.runtime_config, "input_completion_allow_uniform_scalar", True):
```

#### `input_completion_allow_upload_support_file`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L77) `Config.__post_init__()` 行 77。
- 默认值表达式：`os.getenv("INPUT_COMPLETION_ALLOW_UPLOAD_SUPPORT_FILE", "true").lower() == "true"`
- 控制行为：控制 input completion 是否允许上传 supporting file 选项。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L4598) 行 4598
```python
            if getattr(self.runtime_config, "input_completion_allow_upload_support_file", True):
```
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L4499) 行 4499
```python
                if getattr(self.runtime_config, "input_completion_allow_upload_support_file", True):
```
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L4553) 行 4553
```python
                    if getattr(self.runtime_config, "input_completion_allow_upload_support_file", True):
```

#### `enable_geometry_recovery_path`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L80) `Config.__post_init__()` 行 80。
- 默认值表达式：`os.getenv("ENABLE_GEOMETRY_RECOVERY_PATH", "true").lower() == "true"`
- 控制行为：控制缺少 geometry 时是否开启 geometry recovery。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L5114) 行 5114
```python
        if not getattr(self.runtime_config, "enable_geometry_recovery_path", True):
```
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L6410) 行 6410
```python
        if not getattr(self.runtime_config, "enable_geometry_recovery_path", True):
```

#### `enable_file_relationship_resolution`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L83) `Config.__post_init__()` 行 83。
- 默认值表达式：`os.getenv("ENABLE_FILE_RELATIONSHIP_RESOLUTION", "true").lower() == "true"`
- 控制行为：控制补充上传文件时是否触发 file relationship resolution。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L1752) 行 1752
```python
        if not getattr(self.runtime_config, "enable_file_relationship_resolution", True):
```

#### `file_relationship_resolution_require_new_upload`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L86) `Config.__post_init__()` 行 86。
- 默认值表达式：`os.getenv("FILE_RELATIONSHIP_RESOLUTION_REQUIRE_NEW_UPLOAD", "true").lower() == "true"`
- 控制行为：控制文件关系判定是否要求本轮存在新上传。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L1795) 行 1795
```python
        if not getattr(self.runtime_config, "file_relationship_resolution_require_new_upload", True) and has_relation_cue:
```

#### `file_relationship_resolution_allow_llm_fallback`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L89) `Config.__post_init__()` 行 89。
- 默认值表达式：`os.getenv("FILE_RELATIONSHIP_RESOLUTION_ALLOW_LLM_FALLBACK", "true").lower() == "true"`
- 控制行为：控制文件关系判定是否允许 LLM fallback。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L1830) 行 1830
```python
            if getattr(self.runtime_config, "file_relationship_resolution_allow_llm_fallback", True):
```

#### `enable_supplemental_column_merge`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L92) `Config.__post_init__()` 行 92。
- 默认值表达式：`os.getenv("ENABLE_SUPPLEMENTAL_COLUMN_MERGE", "true").lower() == "true"`
- 控制行为：控制 supplemental merge 路径是否可用。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L8268) 行 8268
```python
            if (
                transition_plan.pending_merge_semantics
                and getattr(self.runtime_config, "enable_supplemental_column_merge", True)
                and state.stage == TaskStage.INPUT_RECEIVED
            ):
```
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L1991) 行 1991
```python
            if getattr(self.runtime_config, "enable_supplemental_column_merge", True):
```

#### `supplemental_merge_allow_alias_keys`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L95) `Config.__post_init__()` 行 95。
- 默认值表达式：`os.getenv("SUPPLEMENTAL_MERGE_ALLOW_ALIAS_KEYS", "true").lower() == "true"`
- 控制行为：控制 supplemental merge 是否接受 alias key 对齐。
- 运行时代码命中（静态扫描未抽出 `if` 条件头）：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L2162) 行 2162：`allow_alias_keys=getattr(self.runtime_config, "supplemental_merge_allow_alias_keys", True),`

#### `supplemental_merge_require_readiness_refresh`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L98) `Config.__post_init__()` 行 98。
- 默认值表达式：`os.getenv("SUPPLEMENTAL_MERGE_REQUIRE_READINESS_REFRESH", "true").lower() == "true"`
- 控制行为：控制 supplemental merge 后是否必须刷新 readiness。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L2319) 行 2319
```python
        if getattr(self.runtime_config, "supplemental_merge_require_readiness_refresh", True):
```

#### `enable_intent_resolution`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L101) `Config.__post_init__()` 行 101。
- 默认值表达式：`os.getenv("ENABLE_INTENT_RESOLUTION", "true").lower() == "true"`
- 控制行为：控制 follow-up 场景是否先做 intent resolution。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L3154) 行 3154
```python
        if not getattr(self.runtime_config, "enable_intent_resolution", True):
```
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L7866) 行 7866
```python
        if purpose == "intent_resolution" and not getattr(
            self.runtime_config,
            "enable_intent_resolution",
            True,
        ):
```

#### `intent_resolution_allow_llm_fallback`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L104) `Config.__post_init__()` 行 104。
- 默认值表达式：`os.getenv("INTENT_RESOLUTION_ALLOW_LLM_FALLBACK", "true").lower() == "true"`
- 控制行为：控制 intent resolution 是否允许 LLM fallback。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L3239) 行 3239
```python
            if getattr(self.runtime_config, "intent_resolution_allow_llm_fallback", True):
```

#### `intent_resolution_bias_followup_suggestions`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L107) `Config.__post_init__()` 行 107。
- 默认值表达式：`os.getenv("INTENT_RESOLUTION_BIAS_FOLLOWUP_SUGGESTIONS", "true").lower() == "true"`
- 控制行为：控制 intent resolution 是否调整 follow-up suggestion 排序。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L8085) 行 8085
```python
        if (
            state is not None
            and state.latest_intent_resolution_plan is not None
            and getattr(self.runtime_config, "intent_resolution_bias_followup_suggestions", True)
        ):
```

#### `intent_resolution_bias_continuation`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L110) `Config.__post_init__()` 行 110。
- 默认值表达式：`os.getenv("INTENT_RESOLUTION_BIAS_CONTINUATION", "true").lower() == "true"`
- 控制行为：控制 intent resolution 是否偏置 residual continuation。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L3379) 行 3379
```python
        if (
            plan is None
            or not getattr(self.runtime_config, "intent_resolution_bias_continuation", True)
        ):
```

#### `enable_artifact_memory`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L113) `Config.__post_init__()` 行 113。
- 默认值表达式：`os.getenv("ENABLE_ARTIFACT_MEMORY", "true").lower() == "true"`
- 控制行为：控制 artifact memory 的记录与跨轮持久化。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L1004) 行 1004
```python
        if not getattr(self.runtime_config, "enable_artifact_memory", True):
```
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L3102) 行 3102
```python
        if (
            getattr(self.runtime_config, "enable_artifact_memory", True)
            and state.artifact_memory_state.recent_artifact_summary
        ):
```
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L8094) 行 8094
```python
        if (
            state is not None
            and getattr(self.runtime_config, "enable_artifact_memory", True)
        ):
```

#### `artifact_memory_track_textual_summary`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L116) `Config.__post_init__()` 行 116。
- 默认值表达式：`os.getenv("ARTIFACT_MEMORY_TRACK_TEXTUAL_SUMMARY", "true").lower() == "true"`
- 控制行为：控制 artifact memory 是否跟踪 textual summary。
- 运行时代码命中（静态扫描未抽出 `if` 条件头）：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L1031) 行 1031：`"artifact_memory_track_textual_summary",`

#### `artifact_memory_dedup_by_family`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L119) `Config.__post_init__()` 行 119。
- 默认值表达式：`os.getenv("ARTIFACT_MEMORY_DEDUP_BY_FAMILY", "true").lower() == "true"`
- 控制行为：控制 artifact memory 是否按 family 去重。
- 运行时代码命中（静态扫描未抽出 `if` 条件头）：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L8104) 行 8104：`"artifact_memory_dedup_by_family",`
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L8133) 行 8133：`"artifact_memory_dedup_by_family",`

#### `artifact_memory_bias_followup`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L122) `Config.__post_init__()` 行 122。
- 默认值表达式：`os.getenv("ARTIFACT_MEMORY_BIAS_FOLLOWUP", "true").lower() == "true"`
- 控制行为：控制 artifact memory 是否参与 capability/follow-up bias。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L8126) 行 8126
```python
            if getattr(self.runtime_config, "artifact_memory_bias_followup", True):
```

#### `enable_summary_delivery_surface`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L125) `Config.__post_init__()` 行 125。
- 默认值表达式：`os.getenv("ENABLE_SUMMARY_DELIVERY_SURFACE", "true").lower() == "true"`
- 控制行为：控制 summary delivery surface 是否启用。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L2564) 行 2564
```python
        if not getattr(self.runtime_config, "enable_summary_delivery_surface", True):
```

#### `summary_delivery_enable_bar_chart`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L128) `Config.__post_init__()` 行 128。
- 默认值表达式：`os.getenv("SUMMARY_DELIVERY_ENABLE_BAR_CHART", "true").lower() == "true"`
- 控制行为：控制 summary delivery 是否提供 bar chart 输出类型。
- 运行时代码命中（静态扫描未抽出 `if` 条件头）：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L2813) 行 2813：`enable_bar_chart=getattr(self.runtime_config, "summary_delivery_enable_bar_chart", True),`

#### `summary_delivery_allow_text_fallback`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L134) `Config.__post_init__()` 行 134。
- 默认值表达式：`os.getenv("SUMMARY_DELIVERY_ALLOW_TEXT_FALLBACK", "true").lower() == "true"`
- 控制行为：控制 summary delivery 是否允许文本 fallback。
- 运行时代码命中（静态扫描未抽出 `if` 条件头）：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L2814) 行 2814：`allow_text_fallback=getattr(self.runtime_config, "summary_delivery_allow_text_fallback", True),`

#### `geometry_recovery_require_readiness_refresh`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L145) `Config.__post_init__()` 行 145。
- 默认值表达式：`os.getenv("GEOMETRY_RECOVERY_REQUIRE_READINESS_REFRESH", "true").lower() == "true"`
- 控制行为：控制 geometry recovery 后是否要求 readiness refresh。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L5354) 行 5354
```python
        if getattr(self.runtime_config, "geometry_recovery_require_readiness_refresh", True):
```

#### `enable_residual_reentry_controller`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L148) `Config.__post_init__()` 行 148。
- 默认值表达式：`os.getenv("ENABLE_RESIDUAL_REENTRY_CONTROLLER", "true").lower() == "true"`
- 控制行为：控制 geometry recovery/supplemental merge 后的 residual reentry 控制器。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L4946) 行 4946
```python
        if not getattr(self.runtime_config, "enable_residual_reentry_controller", True):
```
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L5382) 行 5382
```python
            if getattr(self.runtime_config, "enable_residual_reentry_controller", True):
```

#### `residual_reentry_require_ready_target`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L151) `Config.__post_init__()` 行 151。
- 默认值表达式：`os.getenv("RESIDUAL_REENTRY_REQUIRE_READY_TARGET", "true").lower() == "true"`
- 控制行为：控制 residual reentry 是否要求目标 action ready。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L4999) 行 4999
```python
        if (
            getattr(self.runtime_config, "residual_reentry_require_ready_target", True)
            and target.target_action_id
        ):
```

#### `residual_reentry_prioritize_recovery_target`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L154) `Config.__post_init__()` 行 154。
- 默认值表达式：`os.getenv("RESIDUAL_REENTRY_PRIORITIZE_RECOVERY_TARGET", "true").lower() == "true"`
- 控制行为：控制 residual reentry 是否优先恢复目标动作。
- 运行时代码命中（静态扫描未抽出 `if` 条件头）：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L5391) 行 5391：`"residual_reentry_prioritize_recovery_target",`

#### `enable_policy_based_remediation`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L157) `Config.__post_init__()` 行 157。
- 默认值表达式：`os.getenv("ENABLE_POLICY_BASED_REMEDIATION", "true").lower() == "true"`
- 控制行为：控制 input completion 构建阶段是否附加 remediation policy 选项。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L4409) 行 4409
```python
            if (
                getattr(self.runtime_config, "enable_policy_based_remediation", False)
                and getattr(self.runtime_config, "enable_default_typical_profile_policy", False)
            ):
```

#### `enable_default_typical_profile_policy`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L160) `Config.__post_init__()` 行 160。
- 默认值表达式：`os.getenv("ENABLE_DEFAULT_TYPICAL_PROFILE_POLICY", "true").lower() == "true"`
- 控制行为：控制 remediation policy 中 default typical profile 选项是否可用。
- 检查语句：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L4409) 行 4409
```python
            if (
                getattr(self.runtime_config, "enable_policy_based_remediation", False)
                and getattr(self.runtime_config, "enable_default_typical_profile_policy", False)
            ):
```

#### `file_analysis_fallback_allow_zip_table_selection`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L186) `Config.__post_init__()` 行 186。
- 默认值表达式：`os.getenv("FILE_ANALYSIS_FALLBACK_ALLOW_ZIP_TABLE_SELECTION", "true").lower() == "true"`
- 控制行为：当前仅能从字段名和使用位置确认其控制相关分支；更细粒度意图无法确认。
- 运行时代码命中（静态扫描未抽出 `if` 条件头）：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L3527) 行 3527：`allow_zip_table_selection=self.runtime_config.file_analysis_fallback_allow_zip_table_selection,`

#### `enable_builtin_map_data`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L199) `Config.__post_init__()` 行 199。
- 默认值表达式：`os.getenv("ENABLE_BUILTIN_MAP_DATA", "false").lower() == "true"`
- 控制行为：控制宏观排放工具是否输出内置 map_data 负载。
- 检查语句：
  - [tools/macro_emission.py](/home/kirito/Agent1/emission_agent/tools/macro_emission.py#L926) 行 926
```python
            if config.enable_builtin_map_data:
```

#### `enable_skill_injection`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L200) `Config.__post_init__()` 行 200。
- 默认值表达式：`os.getenv("ENABLE_SKILL_INJECTION", "true").lower() == "true"`
- 控制行为：控制 assembler 使用 core_v3 + SkillInjector 还是 legacy tool definition 注入。
- 检查语句：
  - [core/assembler.py](/home/kirito/Agent1/emission_agent/core/assembler.py#L48) 行 48
```python
        if self.runtime_config.enable_skill_injection:
```
  - [core/assembler.py](/home/kirito/Agent1/emission_agent/core/assembler.py#L88) 行 88
```python
        if self.runtime_config.enable_skill_injection and self.skill_injector:
```

#### `standardization_config`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L207) `Config.__post_init__()` 行 207。
- 默认值表达式：`{             "llm_enabled": os.getenv(                 "STANDARDIZATION_LLM_ENABLED",                 "true" if self.enable_llm_standardization else "false",             ).lower() == "true",             "llm_backend": os.getenv("STANDARDIZATION_LLM_BACKEND", "api").lower(),             "llm_model": os.getenv("STANDARDIZATION_LLM_MODEL") or None,             "llm_timeout": float(os.getenv("STANDARDIZATION_LLM_TIMEOUT", "5.0")),             "llm_max_retries": int(os.getenv("STANDARDIZATION_LLM_MAX_RETRIES", "1")),             "fuzzy_threshold": float(os.getenv("STANDARDIZATION_FUZZY_THRESHOLD", "0.7")),             "parameter_negotiation_enabled": self.enable_parameter_negotiation,             "parameter_negotiation_confidence_threshold": self.parameter_negotiation_confidence_threshold,             "parameter_negotiation_max_candidates": self.parameter_negotiation_max_candidates,             "local_model_path": os.getenv("STANDARDIZATION_LOCAL_MODEL_PATH") or None,         }`
- 控制行为：这是 `Config` 中的二级配置字典，不是单独的布尔开关；当前仅能从字段名和使用位置确认它被透传给标准化引擎。
- 运行时代码命中（静态扫描未抽出 `if` 条件头）：
  - [services/standardization_engine.py](/home/kirito/Agent1/emission_agent/services/standardization_engine.py#L510) 行 510：`base_config = getattr(runtime_config, "standardization_config", {})`
  - [core/executor.py](/home/kirito/Agent1/emission_agent/core/executor.py#L166) 行 166：`self._std_engine = StandardizationEngine(self.runtime_config.standardization_config)`

#### `use_local_standardizer`

- 定义：[config.py](/home/kirito/Agent1/emission_agent/config.py#L236) `Config.__post_init__()` 行 236。
- 默认值表达式：`os.getenv("USE_LOCAL_STANDARDIZER", "false").lower() == "true"`
- 控制行为：控制 UnifiedStandardizer/shared standardizer 是否启用本地标准化模型。
- 检查语句：
  - [services/standardizer.py](/home/kirito/Agent1/emission_agent/services/standardizer.py#L737) 行 737
```python
                if config.use_local_standardizer:
```
  - [shared/standardizer/vehicle.py](/home/kirito/Agent1/emission_agent/shared/standardizer/vehicle.py#L42) 行 42
```python
            if config.use_local_standardizer:
```
  - [shared/standardizer/pollutant.py](/home/kirito/Agent1/emission_agent/shared/standardizer/pollutant.py#L42) 行 42
```python
            if config.use_local_standardizer:
```

## 5. 测试与评估基础设施

### 5.1 `evaluation/` 目录完整代码

#### `evaluation/eval_end2end.py`

文件：[evaluation/eval_end2end.py](/home/kirito/Agent1/emission_agent/evaluation/eval_end2end.py#L1)，行 1-242。

```python
"""Evaluate end-to-end grounded execution for benchmark tasks."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.executor import ToolExecutor
from core.router import UnifiedRouter
from evaluation.utils import (
    classify_failure,
    classify_recoverability,
    load_jsonl,
    now_ts,
    rebuild_tool_registry,
    resolve_project_path,
    runtime_overrides,
    safe_div,
    write_json,
    write_jsonl,
)
from tools.file_analyzer import FileAnalyzerTool


def _check_outputs(result_like: Dict[str, Any], expected_outputs: Dict[str, bool]) -> Dict[str, Any]:
    data = result_like.get("data") or {}
    actual_outputs = {
        "has_chart_data": bool(result_like.get("chart_data")),
        "has_table_data": bool(result_like.get("table_data")),
        "has_map_data": bool(result_like.get("map_data")),
        "has_download_file": bool(result_like.get("download_file") or data.get("download_file")),
    }
    matched = True
    details = {}
    for key, expected in expected_outputs.items():
        actual = actual_outputs.get(key)
        details[key] = {"expected": expected, "actual": actual, "matched": actual == expected}
        matched = matched and actual == expected
    return {"matched": matched, "details": details, "actual_outputs": actual_outputs}


def run_end2end_evaluation(
    samples_path: Path,
    output_dir: Path,
    mode: str = "tool",
    enable_file_analyzer: bool = True,
    enable_file_context_injection: bool = True,
    enable_executor_standardization: bool = True,
    macro_column_mapping_modes: tuple[str, ...] = ("direct", "ai", "fuzzy"),
    only_task: Optional[str] = None,
) -> Dict[str, Any]:
    samples = load_jsonl(samples_path)
    if only_task:
        samples = [sample for sample in samples if sample["expected_tool_name"] == only_task]
    output_dir.mkdir(parents=True, exist_ok=True)
    logs: List[Dict[str, Any]] = []

    async def _run_async() -> Dict[str, Any]:
        tool_successes = 0
        completion_successes = 0
        route_successes = 0
        total_turns = 0
        skipped = 0

        with runtime_overrides(
            enable_file_analyzer=enable_file_analyzer,
            enable_file_context_injection=enable_file_context_injection,
            enable_executor_standardization=enable_executor_standardization,
            macro_column_mapping_modes=macro_column_mapping_modes,
        ):
            rebuild_tool_registry()
            executor = ToolExecutor()
            analyzer = FileAnalyzerTool()

            for sample in samples:
                file_path = resolve_project_path(sample.get("file_path"))
                file_analysis = None
                if file_path and enable_file_analyzer:
                    analysis_result = await analyzer.execute(file_path=str(file_path))
                    file_analysis = analysis_result.data if analysis_result.success else None

                start = time.perf_counter()
                route_result: Dict[str, Any] = {}
                raw_result: Dict[str, Any]
                error_message = None
                success = False
                interaction_turns = 1
                standardization_trace = None
                tool_logs = None

                try:
                    if mode == "router":
                        router = UnifiedRouter(session_id=f"eval_{sample['sample_id']}")
                        trace: Dict[str, Any] = {}
                        router_result = await router.chat(
                            user_message=sample["user_query"],
                            file_path=str(file_path) if file_path else None,
                            trace=trace,
                        )
                        raw_result = {
                            "text": router_result.text,
                            "chart_data": router_result.chart_data,
                            "table_data": router_result.table_data,
                            "map_data": router_result.map_data,
                            "download_file": router_result.download_file,
                        }
                        routed_tools = trace.get("routing", {}).get("tool_calls", [])
                        route_result = {
                            "expected_tool_name": sample["expected_tool_name"],
                            "actual_tool_name": routed_tools[0]["name"] if routed_tools else None,
                            "tool_calls": routed_tools,
                        }
                        interaction_turns = max(1, len(trace.get("tool_execution", [])))
                        tool_logs = trace.get("tool_execution", [])
                        if tool_logs:
                            first_batch = tool_logs[0].get("tool_results", [])
                            if first_batch:
                                standardization_trace = first_batch[0].get("trace")
                        success = bool(router_result.text)
                    else:
                        raw_result = await executor.execute(
                            tool_name=sample["expected_tool_name"],
                            arguments=sample["tool_arguments"],
                            file_path=str(file_path) if file_path else None,
                        )
                        route_result = {
                            "expected_tool_name": sample["expected_tool_name"],
                            "actual_tool_name": sample["expected_tool_name"],
                            "tool_calls": [{"name": sample["expected_tool_name"], "arguments": sample["tool_arguments"]}],
                        }
                        standardization_trace = raw_result.get("_trace")
                        tool_logs = [raw_result.get("_trace")]
                        success = bool(raw_result.get("success"))
                except Exception as exc:
                    if mode == "router":
                        skipped += 1
                    raw_result = {}
                    error_message = str(exc)

                duration_ms = round((time.perf_counter() - start) * 1000, 2)
                output_check = _check_outputs(raw_result, sample.get("expected_outputs", {}))
                route_match = route_result.get("actual_tool_name") == sample["expected_tool_name"]
                completion = (success == sample.get("expected_success", True)) and output_check["matched"]
                tool_successes += int(success)
                route_successes += int(route_match)
                completion_successes += int(completion)
                total_turns += interaction_turns

                record = {
                    "sample_id": sample["sample_id"],
                    "mode": mode,
                    "input": {
                        "user_query": sample["user_query"],
                        "file_path": str(file_path) if file_path else None,
                        "tool_arguments": sample["tool_arguments"],
                    },
                    "file_analysis": file_analysis,
                    "routing_result": route_result,
                    "standardization_result": standardization_trace,
                    "tool_call_logs": tool_logs,
                    "final_status": {
                        "success": success,
                        "completion": completion,
                        "output_check": output_check,
                        "message": raw_result.get("message") or raw_result.get("text") or error_message,
                    },
                    "timing_ms": duration_ms,
                    "success": completion,
                    "error": error_message or raw_result.get("message"),
                    "error_type": None if completion else ("router" if mode == "router" and not route_match else "execution"),
                }
                failure_type = classify_failure(record)
                record["failure_type"] = failure_type
                record["recoverability"] = classify_recoverability(failure_type)
                logs.append(record)

        metrics = {
            "task": "end2end",
            "mode": mode,
            "samples": len(samples),
            "tool_call_success_rate": round(safe_div(tool_successes, len(samples)), 4),
            "route_accuracy": round(safe_div(route_successes, len(samples)), 4),
            "end2end_completion_rate": round(safe_div(completion_successes, len(samples)), 4),
            "average_interaction_turns": round(safe_div(total_turns, len(samples)), 4),
            "skipped_samples": skipped,
            "enable_file_analyzer": enable_file_analyzer,
            "enable_file_context_injection": enable_file_context_injection,
            "enable_executor_standardization": enable_executor_standardization,
            "macro_column_mapping_modes": list(macro_column_mapping_modes),
            "logs_path": str(output_dir / "end2end_logs.jsonl"),
        }
        return metrics

    metrics = asyncio.run(_run_async())
    write_jsonl(output_dir / "end2end_logs.jsonl", logs)
    write_json(output_dir / "end2end_metrics.json", metrics)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate end-to-end tasks.")
    parser.add_argument(
        "--samples",
        type=Path,
        default=PROJECT_ROOT / "evaluation/end2end/samples.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / f"evaluation/logs/end2end_{now_ts()}",
    )
    parser.add_argument("--mode", choices=["tool", "router"], default="tool")
    parser.add_argument("--disable-file-analyzer", action="store_true")
    parser.add_argument("--disable-file-context-injection", action="store_true")
    parser.add_argument("--disable-executor-standardization", action="store_true")
    parser.add_argument("--macro-modes", default="direct,ai,fuzzy")
    parser.add_argument("--only-task", choices=["query_emission_factors", "calculate_micro_emission", "calculate_macro_emission"])
    args = parser.parse_args()

    metrics = run_end2end_evaluation(
        samples_path=args.samples,
        output_dir=args.output_dir,
        mode=args.mode,
        enable_file_analyzer=not args.disable_file_analyzer,
        enable_file_context_injection=not args.disable_file_context_injection,
        enable_executor_standardization=not args.disable_executor_standardization,
        macro_column_mapping_modes=tuple(mode.strip() for mode in args.macro_modes.split(",") if mode.strip()),
        only_task=args.only_task,
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```
#### `evaluation/eval_file_grounding.py`

文件：[evaluation/eval_file_grounding.py](/home/kirito/Agent1/emission_agent/evaluation/eval_file_grounding.py#L1)，行 1-213。

```python
"""Evaluate file-aware task recognition and column grounding."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.assembler import ContextAssembler
from evaluation.utils import (
    classify_failure,
    classify_recoverability,
    compare_expected_subset,
    load_jsonl,
    now_ts,
    resolve_project_path,
    runtime_overrides,
    safe_div,
    write_json,
    write_jsonl,
)
from skills.macro_emission.excel_handler import ExcelHandler as MacroExcelHandler
from skills.micro_emission.excel_handler import ExcelHandler as MicroExcelHandler
from tools.file_analyzer import FileAnalyzerTool


def _load_dataframe(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    return pd.read_excel(path)


def _extract_micro_mapping(path: Path) -> Dict[str, str]:
    handler = MicroExcelHandler(llm_client=None)
    df = _load_dataframe(path)
    df.columns = df.columns.str.strip()
    mapping = {}
    speed_col = handler._find_column(df, handler.SPEED_COLUMNS)
    time_col = handler._find_column(df, handler.TIME_COLUMNS)
    acc_col = handler._find_column(df, handler.ACCELERATION_COLUMNS)
    grade_col = handler._find_column(df, handler.GRADE_COLUMNS)
    if speed_col:
        mapping["speed"] = speed_col
    if time_col:
        mapping["time"] = time_col
    if acc_col:
        mapping["acceleration"] = acc_col
    if grade_col:
        mapping["grade"] = grade_col
    return mapping


def _extract_macro_mapping(path: Path) -> Dict[str, str]:
    handler = MacroExcelHandler(llm_client=None)
    df = _load_dataframe(path)
    df.columns = [str(col).strip() for col in df.columns]
    result = handler._resolve_column_mapping(df)
    return result.get("field_to_column", {})


def run_file_grounding_evaluation(
    samples_path: Path,
    output_dir: Path,
    enable_file_analyzer: bool = True,
    enable_file_context_injection: bool = True,
    macro_column_mapping_modes: tuple[str, ...] = ("direct", "ai", "fuzzy"),
) -> Dict[str, Any]:
    samples = load_jsonl(samples_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    logs: List[Dict[str, Any]] = []
    task_hits = 0
    mapping_hits = 0
    mapping_total = 0
    required_hits = 0
    context_hits = 0

    # Re-run with explicit async handling outside of override body to keep logic clearer.
    import asyncio

    async def _evaluate_async() -> None:
        nonlocal task_hits, mapping_hits, mapping_total, required_hits, context_hits, logs
        logs = []
        with runtime_overrides(
            enable_file_analyzer=enable_file_analyzer,
            enable_file_context_injection=enable_file_context_injection,
            macro_column_mapping_modes=macro_column_mapping_modes,
        ):
            analyzer = FileAnalyzerTool()
            assembler = ContextAssembler()
            for sample in samples:
                file_path = resolve_project_path(sample["file_path"])
                analysis = None
                if enable_file_analyzer:
                    analysis_result = await analyzer.execute(file_path=str(file_path))
                    analysis = analysis_result.data if analysis_result.success else None

                if sample["expected_task_type"] == "macro_emission":
                    actual_mapping = _extract_macro_mapping(file_path)
                else:
                    actual_mapping = _extract_micro_mapping(file_path)

                required_present = False
                if analysis:
                    required_present = bool(
                        analysis.get("macro_has_required")
                        if sample["expected_task_type"] == "macro_emission"
                        else analysis.get("micro_has_required")
                    )

                assembled = assembler.assemble(
                    user_message=sample["user_query"],
                    working_memory=[],
                    fact_memory={},
                    file_context=analysis,
                )
                last_message = assembled.messages[-1]["content"] if assembled.messages else ""
                context_injected = "Filename:" in last_message and "task_type:" in last_message

                task_match = bool(analysis and analysis.get("task_type") == sample["expected_task_type"])
                mapping_cmp = compare_expected_subset(actual_mapping, sample["expected_mapping"])
                task_hits += int(task_match)
                required_hits += int(required_present == sample["expected_required_present"])
                expected_context = enable_file_context_injection and bool(analysis)
                context_hits += int(context_injected == expected_context)
                mapping_total += len(sample["expected_mapping"])
                for detail in mapping_cmp["details"].values():
                    if detail.get("matched"):
                        mapping_hits += 1

                record = {
                    "sample_id": sample["sample_id"],
                    "input": {
                        "user_query": sample["user_query"],
                        "file_path": str(file_path),
                    },
                    "file_analysis": analysis,
                    "routing_result": {
                        "expected_task_type": sample["expected_task_type"],
                        "actual_task_type": analysis.get("task_type") if analysis else None,
                    },
                    "mapping_result": {
                        "expected_mapping": sample["expected_mapping"],
                        "actual_mapping": actual_mapping,
                        "comparison": mapping_cmp,
                    },
                    "context_injected": context_injected,
                    "required_present": required_present,
                    "success": task_match and mapping_cmp["matched"] and (required_present == sample["expected_required_present"]),
                }
                failure_type = classify_failure(record)
                record["failure_type"] = failure_type
                record["recoverability"] = classify_recoverability(failure_type)
                logs.append(record)

    asyncio.run(_evaluate_async())

    metrics = {
        "task": "file_grounding",
        "samples": len(samples),
        "routing_accuracy": round(safe_div(task_hits, len(samples)), 4),
        "column_mapping_accuracy": round(safe_div(mapping_hits, mapping_total), 4),
        "required_field_accuracy": round(safe_div(required_hits, len(samples)), 4),
        "file_context_injection_consistency": round(safe_div(context_hits, len(samples)), 4),
        "enable_file_analyzer": enable_file_analyzer,
        "enable_file_context_injection": enable_file_context_injection,
        "macro_column_mapping_modes": list(macro_column_mapping_modes),
        "logs_path": str(output_dir / "file_grounding_logs.jsonl"),
    }
    write_jsonl(output_dir / "file_grounding_logs.jsonl", logs)
    write_json(output_dir / "file_grounding_metrics.json", metrics)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate file task grounding.")
    parser.add_argument(
        "--samples",
        type=Path,
        default=PROJECT_ROOT / "evaluation/file_tasks/samples.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / f"evaluation/logs/file_grounding_{now_ts()}",
    )
    parser.add_argument("--disable-file-analyzer", action="store_true")
    parser.add_argument("--disable-file-context-injection", action="store_true")
    parser.add_argument(
        "--macro-modes",
        default="direct,ai,fuzzy",
        help="Comma-separated macro column mapping modes.",
    )
    args = parser.parse_args()

    metrics = run_file_grounding_evaluation(
        samples_path=args.samples,
        output_dir=args.output_dir,
        enable_file_analyzer=not args.disable_file_analyzer,
        enable_file_context_injection=not args.disable_file_context_injection,
        macro_column_mapping_modes=tuple(mode.strip() for mode in args.macro_modes.split(",") if mode.strip()),
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```
#### `evaluation/eval_normalization.py`

文件：[evaluation/eval_normalization.py](/home/kirito/Agent1/emission_agent/evaluation/eval_normalization.py#L1)，行 1-160。

```python
"""Evaluate executor-layer parameter normalization."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.executor import StandardizationError, ToolExecutor
from evaluation.utils import (
    compare_expected_subset,
    classify_failure,
    classify_recoverability,
    load_jsonl,
    now_ts,
    runtime_overrides,
    safe_div,
    write_json,
    write_jsonl,
)
from services.standardizer import get_standardizer

SEASON_ALLOWED = {"春季", "夏季", "秋季", "冬季"}
ROAD_TYPE_ALLOWED = {"快速路", "地面道路"}


def _check_param_legality(arguments: Dict[str, Any]) -> Dict[str, bool]:
    standardizer = get_standardizer()
    legal = {}

    vehicle = arguments.get("vehicle_type")
    legal["vehicle_type"] = vehicle is None or standardizer.standardize_vehicle(str(vehicle)) is not None

    pollutants = arguments.get("pollutants", [])
    if isinstance(pollutants, list):
        legal["pollutants"] = all(standardizer.standardize_pollutant(str(item)) is not None for item in pollutants)
    else:
        legal["pollutants"] = False

    if "season" in arguments:
        legal["season"] = arguments.get("season") in SEASON_ALLOWED
    if "road_type" in arguments:
        legal["road_type"] = arguments.get("road_type") in ROAD_TYPE_ALLOWED
    if "model_year" in arguments:
        year = arguments.get("model_year")
        legal["model_year"] = isinstance(year, int) and 1995 <= year <= 2025

    return legal


def run_normalization_evaluation(
    samples_path: Path,
    output_dir: Path,
    enable_executor_standardization: bool = True,
) -> Dict[str, Any]:
    samples = load_jsonl(samples_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    logs: List[Dict[str, Any]] = []
    field_total = 0
    field_matched = 0
    sample_success = 0
    legal_success = 0

    with runtime_overrides(enable_executor_standardization=enable_executor_standardization):
        executor = ToolExecutor()

        for sample in samples:
            raw_args = dict(sample["raw_arguments"])
            expected = sample["expected_standardized"]
            expected_success = bool(sample.get("expected_success", True))
            error_message = None
            actual_args = None
            actual_success = True
            try:
                actual_args = executor._standardize_arguments(sample["tool_name"], raw_args)
            except StandardizationError as exc:
                actual_success = False
                error_message = str(exc)
                actual_args = {}

            comparison = compare_expected_subset(actual_args, expected)
            legality = _check_param_legality(actual_args)
            field_total += len(sample.get("focus_params", []))
            for param in sample.get("focus_params", []):
                detail = comparison["details"].get(param)
                if detail and detail.get("matched"):
                    field_matched += 1

            sample_matched = (actual_success == expected_success) and comparison["matched"]
            sample_success += int(sample_matched)
            legal_success += int(all(legality.values()) if legality else False)

            record = {
                "sample_id": sample["sample_id"],
                "tool_name": sample["tool_name"],
                "input": raw_args,
                "expected_success": expected_success,
                "actual_success": actual_success,
                "expected_standardized": expected,
                "actual_standardized": actual_args,
                "comparison": comparison,
                "legality": legality,
                "success": sample_matched,
                "error": error_message,
                "error_type": None if sample_matched else "standardization",
            }
            failure_type = classify_failure(record)
            record["failure_type"] = failure_type
            record["recoverability"] = classify_recoverability(failure_type)
            logs.append(record)

    metrics = {
        "task": "normalization",
        "samples": len(samples),
        "sample_accuracy": round(safe_div(sample_success, len(samples)), 4),
        "field_accuracy": round(safe_div(field_matched, field_total), 4),
        "parameter_legal_rate": round(safe_div(legal_success, len(samples)), 4),
        "executor_standardization_enabled": enable_executor_standardization,
        "logs_path": str(output_dir / "normalization_logs.jsonl"),
    }

    write_jsonl(output_dir / "normalization_logs.jsonl", logs)
    write_json(output_dir / "normalization_metrics.json", metrics)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate executor-layer normalization.")
    parser.add_argument(
        "--samples",
        type=Path,
        default=PROJECT_ROOT / "evaluation/normalization/samples.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / f"evaluation/logs/normalization_{now_ts()}",
    )
    parser.add_argument(
        "--disable-executor-standardization",
        action="store_true",
        help="Bypass executor-layer parameter normalization.",
    )
    args = parser.parse_args()

    metrics = run_normalization_evaluation(
        samples_path=args.samples,
        output_dir=args.output_dir,
        enable_executor_standardization=not args.disable_executor_standardization,
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```
#### `evaluation/run_smoke_suite.py`

文件：[evaluation/run_smoke_suite.py](/home/kirito/Agent1/emission_agent/evaluation/run_smoke_suite.py#L1)，行 1-113。

```python
"""Run the lowest-friction local evaluation smoke suite.

This is the canonical minimal reproducibility path for the current evaluation
framework. It reuses the existing benchmark runners with conservative defaults:

- normalization evaluation
- file-grounding evaluation
- end-to-end evaluation in `tool` mode

The default macro mapping modes are `direct,fuzzy` to avoid depending on the
AI-only mapping step for the smallest local validation run.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.eval_end2end import run_end2end_evaluation
from evaluation.eval_file_grounding import run_file_grounding_evaluation
from evaluation.eval_normalization import run_normalization_evaluation
from evaluation.utils import now_ts, write_json

DEFAULT_MACRO_MODES: Tuple[str, ...] = ("direct", "fuzzy")


def run_smoke_suite(
    output_dir: Path,
    enable_file_analyzer: bool = True,
    enable_file_context_injection: bool = True,
    enable_executor_standardization: bool = True,
    macro_column_mapping_modes: Tuple[str, ...] = DEFAULT_MACRO_MODES,
) -> Dict[str, Any]:
    """Run the recommended smoke-level evaluation set and persist a summary."""
    output_dir.mkdir(parents=True, exist_ok=True)

    normalization_metrics = run_normalization_evaluation(
        samples_path=PROJECT_ROOT / "evaluation/normalization/samples.jsonl",
        output_dir=output_dir / "normalization",
        enable_executor_standardization=enable_executor_standardization,
    )
    file_grounding_metrics = run_file_grounding_evaluation(
        samples_path=PROJECT_ROOT / "evaluation/file_tasks/samples.jsonl",
        output_dir=output_dir / "file_grounding",
        enable_file_analyzer=enable_file_analyzer,
        enable_file_context_injection=enable_file_context_injection,
        macro_column_mapping_modes=macro_column_mapping_modes,
    )
    end2end_metrics = run_end2end_evaluation(
        samples_path=PROJECT_ROOT / "evaluation/end2end/samples.jsonl",
        output_dir=output_dir / "end2end",
        mode="tool",
        enable_file_analyzer=enable_file_analyzer,
        enable_file_context_injection=enable_file_context_injection,
        enable_executor_standardization=enable_executor_standardization,
        macro_column_mapping_modes=macro_column_mapping_modes,
        only_task=None,
    )

    summary = {
        "suite": "smoke",
        "recommended_defaults": {
            "mode": "tool",
            "enable_file_analyzer": enable_file_analyzer,
            "enable_file_context_injection": enable_file_context_injection,
            "enable_executor_standardization": enable_executor_standardization,
            "macro_column_mapping_modes": list(macro_column_mapping_modes),
        },
        "metrics": {
            "normalization": normalization_metrics,
            "file_grounding": file_grounding_metrics,
            "end2end": end2end_metrics,
        },
    }
    write_json(output_dir / "smoke_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the minimal local evaluation smoke suite.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / f"evaluation/logs/smoke_{now_ts()}",
    )
    parser.add_argument("--disable-file-analyzer", action="store_true")
    parser.add_argument("--disable-file-context-injection", action="store_true")
    parser.add_argument("--disable-executor-standardization", action="store_true")
    parser.add_argument(
        "--macro-modes",
        default="direct,fuzzy",
        help="Comma-separated macro column mapping modes for the smoke run.",
    )
    args = parser.parse_args()

    summary = run_smoke_suite(
        output_dir=args.output_dir,
        enable_file_analyzer=not args.disable_file_analyzer,
        enable_file_context_injection=not args.disable_file_context_injection,
        enable_executor_standardization=not args.disable_executor_standardization,
        macro_column_mapping_modes=tuple(mode.strip() for mode in args.macro_modes.split(",") if mode.strip()),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```
### 5.2 关键测试文件中的测试函数

#### `tests/test_router_state_loop.py`

- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L327) `test_legacy_loop_unchanged`，行 327-342：测试 legacy loop 路径在开启兼容分支时保持原有行为。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L346) `test_state_loop_no_tool_call`，行 346-364：测试状态循环在没有工具调用时的返回路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L368) `test_state_loop_with_tool_call`，行 368-426：测试状态循环在存在工具调用时的执行路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L430) `test_state_loop_produces_trace`，行 430-443：测试状态循环会生成 trace 输出。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L447) `test_clarification_on_unknown_file_type`，行 447-483：测试 `test_clarification_on_unknown_file_type` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L487) `test_file_grounding_fallback_integrates_into_state_loop`，行 487-537：测试 `test_file_grounding_fallback_integrates_into_state_loop` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L541) `test_file_grounding_fallback_failure_remains_safe`，行 541-581：测试 `test_file_grounding_fallback_failure_remains_safe` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L585) `test_file_grounding_enhancement_trace_emission`，行 585-676：测试 `test_file_grounding_enhancement_trace_emission` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L680) `test_template_prior_injection_happens_before_planning`，行 680-771：测试 `test_template_prior_injection_happens_before_planning` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L775) `test_continuation_path_skips_fresh_workflow_template_recommendation`，行 775-825：测试 `test_continuation_path_skips_fresh_workflow_template_recommendation` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L829) `test_clarification_on_standardization_error`，行 829-856：测试 `test_clarification_on_standardization_error` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L860) `test_low_confidence_standardization_enters_parameter_negotiation`，行 860-886：测试参数协商流程的触发、确认、拒绝或继续行为。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L890) `test_next_turn_confirmation_by_index_applies_parameter_lock_and_continues`，行 890-954：测试 `test_next_turn_confirmation_by_index_applies_parameter_lock_and_continues` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L958) `test_parameter_negotiation_none_of_above_moves_to_clarification`，行 958-984：测试参数协商流程的触发、确认、拒绝或继续行为。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L988) `test_parameter_negotiation_ambiguous_reply_retries_without_locking`，行 988-1014：测试参数协商流程的触发、确认、拒绝或继续行为。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L1018) `test_parameter_negotiation_confirmation_preserves_residual_continuation`，行 1018-1103：测试参数协商流程的触发、确认、拒绝或继续行为。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L1107) `test_state_loop_saves_full_spatial_data_before_memory_compaction`，行 1107-1141：测试 `test_state_loop_saves_full_spatial_data_before_memory_compaction` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L1145) `test_render_spatial_map_injects_last_spatial_data_from_memory`，行 1145-1187：测试 `test_render_spatial_map_injects_last_spatial_data_from_memory` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L1191) `test_lightweight_planning_runs_before_first_tool_call_after_grounding`，行 1191-1261：测试 `test_lightweight_planning_runs_before_first_tool_call_after_grounding` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L1265) `test_plan_deviation_is_traced_without_blocking_execution`，行 1265-1325：测试 `test_plan_deviation_is_traced_without_blocking_execution` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L1329) `test_planning_failure_falls_back_to_original_tool_calling`，行 1329-1370：测试 `test_planning_failure_falls_back_to_original_tool_calling` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L1374) `test_execution_stage_plan_reconciliation_tracks_multi_step_matches`，行 1374-1443：测试 `test_execution_stage_plan_reconciliation_tracks_multi_step_matches` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L1447) `test_execution_stage_deviation_marks_out_of_order_step_without_blocking`，行 1447-1521：测试 `test_execution_stage_deviation_marks_out_of_order_step_without_blocking` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L1525) `test_dependency_blocked_before_execution_marks_plan_and_builds_response`，行 1525-1571：测试 `test_dependency_blocked_before_execution_marks_plan_and_builds_response` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L1575) `test_readiness_repairable_pre_execution_stops_render_without_geometry`，行 1575-1621：测试 readiness gating 的判定结果。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L1625) `test_readiness_blocked_pre_execution_stops_incompatible_macro_tool`，行 1625-1663：测试 readiness gating 的判定结果。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L1667) `test_readiness_repairable_pre_execution_stops_macro_when_required_field_missing`，行 1667-1708：测试 readiness gating 的判定结果。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L1712) `test_input_completion_uniform_scalar_success_restores_current_task_context`，行 1712-1785：测试输入补全流程的触发、确认或恢复行为。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L1789) `test_explicit_new_task_overrides_pending_input_completion`，行 1789-1837：测试输入补全流程的触发、确认或恢复行为。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L1841) `test_file_relationship_replace_primary_file_supersedes_pending_completion`，行 1841-1919：测试 `test_file_relationship_replace_primary_file_supersedes_pending_completion` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L1923) `test_file_relationship_attach_supporting_file_preserves_primary_context`，行 1923-1997：测试 `test_file_relationship_attach_supporting_file_preserves_primary_context` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L2001) `test_file_relationship_resolution_skips_plain_continuation_without_upload`，行 2001-2026：测试 `test_file_relationship_resolution_skips_plain_continuation_without_upload` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L2030) `test_file_relationship_resolution_asks_clarify_for_ambiguous_upload`，行 2030-2069：测试 `test_file_relationship_resolution_asks_clarify_for_ambiguous_upload` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L2073) `test_run_state_loop_preserves_primary_memory_when_supporting_file_attaches`，行 2073-2129：测试 `test_run_state_loop_preserves_primary_memory_when_supporting_file_attaches` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L2133) `test_supplemental_merge_executes_and_restores_resumable_workflow`，行 2133-2256：测试 `test_supplemental_merge_executes_and_restores_resumable_workflow` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L2260) `test_supplemental_merge_needs_clarification_when_key_alignment_is_not_safe`，行 2260-2376：测试 `test_supplemental_merge_needs_clarification_when_key_alignment_is_not_safe` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L2380) `test_run_state_loop_updates_memory_to_merged_primary_file`，行 2380-2484：测试 `test_run_state_loop_updates_memory_to_merged_primary_file` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L2488) `test_missing_geometry_completion_enables_geometry_recovery_path`，行 2488-2550：测试几何恢复路径的触发、恢复或继续行为。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L2554) `test_geometry_recovery_preserves_residual_workflow_until_next_turn`，行 2554-2656：测试几何恢复路径的触发、恢复或继续行为。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L2660) `test_explicit_new_task_overrides_active_geometry_recovery_context`，行 2660-2726：测试几何恢复路径的触发、恢复或继续行为。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L2730) `test_geometry_reentry_skips_when_recovered_target_is_no_longer_ready`，行 2730-2794：测试 `test_geometry_reentry_skips_when_recovered_target_is_no_longer_ready` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L2798) `test_synthesis_no_longer_suggests_unsupported_spatial_actions_or_duplicate_download`，行 2798-2838：测试 `test_synthesis_no_longer_suggests_unsupported_spatial_actions_or_duplicate_download` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L2842) `test_artifact_memory_is_recorded_and_persisted_after_download_delivery`，行 2842-2883：测试 artifact memory 的记录、持久化或跟随影响。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L2886) `test_artifact_memory_makes_download_action_already_provided_across_turns`，行 2886-2927：测试 artifact memory 的记录、持久化或跟随影响。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L2931) `test_dependency_blocked_triggers_bounded_repair_without_auto_execution`，行 2931-2999：测试 `test_dependency_blocked_triggers_bounded_repair_without_auto_execution` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L3003) `test_plan_exhausted_deviation_triggers_repair_and_stops_before_unplanned_execution`，行 3003-3089：测试 `test_plan_exhausted_deviation_triggers_repair_and_stops_before_unplanned_execution` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L3093) `test_invalid_repair_falls_back_without_mutating_original_plan`，行 3093-3156：测试 `test_invalid_repair_falls_back_without_mutating_original_plan` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L3160) `test_repair_applied_next_turn_continues_on_residual_plan_without_replan`，行 3160-3256：测试 `test_repair_applied_next_turn_continues_on_residual_plan_without_replan` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L3260) `test_dependency_blocked_residual_state_informs_next_turn_continuation`，行 3260-3328：测试 `test_dependency_blocked_residual_state_informs_next_turn_continuation` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L3332) `test_new_task_override_skips_residual_plan_continuation`，行 3332-3415：测试 `test_new_task_override_skips_residual_plan_continuation` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L3419) `test_ambiguous_input_without_residual_alignment_skips_continuation`，行 3419-3501：测试 `test_ambiguous_input_without_residual_alignment_skips_continuation` 所表示的行为路径。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L3505) `test_intent_resolution_visualize_without_geometry_biases_away_from_map`，行 3505-3557：测试 intent resolution 的判定与偏置行为。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L3561) `test_summary_delivery_surface_visualize_without_geometry_returns_ranked_chart`，行 3561-3602：测试 summary delivery surface 的触发与返回行为。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L3606) `test_summary_delivery_surface_switches_from_repeated_topk_table_to_chart`，行 3606-3661：测试 summary delivery surface 的触发与返回行为。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L3665) `test_summary_delivery_surface_quick_summary_returns_structured_text_and_records_artifacts`，行 3665-3711：测试 summary delivery surface 的触发与返回行为。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L3715) `test_intent_resolution_visualize_with_geometry_can_bias_toward_spatial_map`，行 3715-3762：测试 intent resolution 的判定与偏置行为。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L3766) `test_intent_resolution_continue_prefers_recovered_target_resume`，行 3766-3853：测试 intent resolution 的判定与偏置行为。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py#L3857) `test_intent_resolution_shift_output_mode_suppresses_default_residual_continuation`，行 3857-3917：测试 intent resolution 的判定与偏置行为。

#### `tests/test_router_contracts.py`

- [tests/test_router_contracts.py](/home/kirito/Agent1/emission_agent/tests/test_router_contracts.py#L36) `test_build_memory_tool_calls_compacts_large_payloads_for_follow_up_turns`，行 36-91：测试 `test_build_memory_tool_calls_compacts_large_payloads_for_follow_up_turns` 所表示的行为路径。
- [tests/test_router_contracts.py](/home/kirito/Agent1/emission_agent/tests/test_router_contracts.py#L94) `test_router_memory_utils_match_core_router_compatibility_wrappers`，行 94-115：测试 router 相关契约或辅助逻辑。
- [tests/test_router_contracts.py](/home/kirito/Agent1/emission_agent/tests/test_router_contracts.py#L118) `test_router_payload_utils_match_core_router_compatibility_wrappers`，行 118-165：测试 router 相关契约或辅助逻辑。
- [tests/test_router_contracts.py](/home/kirito/Agent1/emission_agent/tests/test_router_contracts.py#L168) `test_router_render_utils_match_core_router_compatibility_wrappers`，行 168-207：测试 router 相关契约或辅助逻辑。
- [tests/test_router_contracts.py](/home/kirito/Agent1/emission_agent/tests/test_router_contracts.py#L210) `test_router_synthesis_utils_match_core_router_compatibility_wrappers`，行 210-231：测试 router 相关契约或辅助逻辑。
- [tests/test_router_contracts.py](/home/kirito/Agent1/emission_agent/tests/test_router_contracts.py#L234) `test_maybe_short_circuit_synthesis_covers_knowledge_failure_and_single_tool_paths`，行 234-266：测试 `test_maybe_short_circuit_synthesis_covers_knowledge_failure_and_single_tool_paths` 所表示的行为路径。
- [tests/test_router_contracts.py](/home/kirito/Agent1/emission_agent/tests/test_router_contracts.py#L269) `test_build_synthesis_request_and_keyword_detection_preserve_llm_input_contract`，行 269-319：测试 `test_build_synthesis_request_and_keyword_detection_preserve_llm_input_contract` 所表示的行为路径。
- [tests/test_router_contracts.py](/home/kirito/Agent1/emission_agent/tests/test_router_contracts.py#L322) `test_render_single_tool_success_formats_micro_results_with_key_sections`，行 322-353：测试 `test_render_single_tool_success_formats_micro_results_with_key_sections` 所表示的行为路径。
- [tests/test_router_contracts.py](/home/kirito/Agent1/emission_agent/tests/test_router_contracts.py#L356) `test_filter_results_and_error_formatting_keep_retry_and_synthesis_signal`，行 356-416：测试 `test_filter_results_and_error_formatting_keep_retry_and_synthesis_signal` 所表示的行为路径。
- [tests/test_router_contracts.py](/home/kirito/Agent1/emission_agent/tests/test_router_contracts.py#L419) `test_extract_chart_data_prefers_explicit_chart_payload`，行 419-436：测试 `test_extract_chart_data_prefers_explicit_chart_payload` 所表示的行为路径。
- [tests/test_router_contracts.py](/home/kirito/Agent1/emission_agent/tests/test_router_contracts.py#L439) `test_extract_chart_data_formats_emission_factor_curves_for_frontend`，行 439-490：测试 `test_extract_chart_data_formats_emission_factor_curves_for_frontend` 所表示的行为路径。
- [tests/test_router_contracts.py](/home/kirito/Agent1/emission_agent/tests/test_router_contracts.py#L493) `test_extract_table_data_formats_macro_results_preview_for_frontend`，行 493-540：测试 `test_extract_table_data_formats_macro_results_preview_for_frontend` 所表示的行为路径。
- [tests/test_router_contracts.py](/home/kirito/Agent1/emission_agent/tests/test_router_contracts.py#L543) `test_extract_table_data_formats_emission_factor_preview_for_frontend`，行 543-594：测试 `test_extract_table_data_formats_emission_factor_preview_for_frontend` 所表示的行为路径。
- [tests/test_router_contracts.py](/home/kirito/Agent1/emission_agent/tests/test_router_contracts.py#L597) `test_extract_table_data_formats_micro_results_preview_for_frontend`，行 597-652：测试 `test_extract_table_data_formats_micro_results_preview_for_frontend` 所表示的行为路径。
- [tests/test_router_contracts.py](/home/kirito/Agent1/emission_agent/tests/test_router_contracts.py#L655) `test_extract_download_and_map_payloads_support_current_and_legacy_locations`，行 655-688：测试 `test_extract_download_and_map_payloads_support_current_and_legacy_locations` 所表示的行为路径。
- [tests/test_router_contracts.py](/home/kirito/Agent1/emission_agent/tests/test_router_contracts.py#L691) `test_format_results_as_fallback_preserves_success_and_error_sections`，行 691-724：测试 `test_format_results_as_fallback_preserves_success_and_error_sections` 所表示的行为路径。
- [tests/test_router_contracts.py](/home/kirito/Agent1/emission_agent/tests/test_router_contracts.py#L728) `test_synthesize_results_calls_llm_with_built_request_and_returns_content`，行 728-777：测试结果综合阶段的调用与输出。
- [tests/test_router_contracts.py](/home/kirito/Agent1/emission_agent/tests/test_router_contracts.py#L781) `test_synthesize_results_short_circuits_failures_without_calling_llm`，行 781-800：测试结果综合阶段的调用与输出。

#### `tests/test_multi_step_execution.py`

- [tests/test_multi_step_execution.py](/home/kirito/Agent1/emission_agent/tests/test_multi_step_execution.py#L171) `TestLLMNativeToolLoop.test_tool_results_are_fed_back_and_next_tool_selected`，行 171-219：测试 `test_tool_results_are_fed_back_and_next_tool_selected` 所表示的行为路径。
- [tests/test_multi_step_execution.py](/home/kirito/Agent1/emission_agent/tests/test_multi_step_execution.py#L222) `TestLLMNativeToolLoop.test_confirmation_turn_executes_dispersion_without_router_intercept`，行 222-262：测试 router 相关契约或辅助逻辑。
- [tests/test_multi_step_execution.py](/home/kirito/Agent1/emission_agent/tests/test_multi_step_execution.py#L265) `TestLLMNativeToolLoop.test_max_steps_limit_forces_finalize_with_current_results`，行 265-295：测试 `test_max_steps_limit_forces_finalize_with_current_results` 所表示的行为路径。
- [tests/test_multi_step_execution.py](/home/kirito/Agent1/emission_agent/tests/test_multi_step_execution.py#L297) `TestLLMNativeToolLoop.test_dispersion_skill_requires_confirmation_before_tool_call`，行 297-304：测试 `test_dispersion_skill_requires_confirmation_before_tool_call` 所表示的行为路径。
- [tests/test_multi_step_execution.py](/home/kirito/Agent1/emission_agent/tests/test_multi_step_execution.py#L308) `TestRenderSpatialMapFriendly.test_in_tools_needing_rendering`，行 308-309：测试 `test_in_tools_needing_rendering` 所表示的行为路径。
- [tests/test_multi_step_execution.py](/home/kirito/Agent1/emission_agent/tests/test_multi_step_execution.py#L311) `TestRenderSpatialMapFriendly.test_emission_map_render`，行 311-328：测试 `test_emission_map_render` 所表示的行为路径。
- [tests/test_multi_step_execution.py](/home/kirito/Agent1/emission_agent/tests/test_multi_step_execution.py#L330) `TestRenderSpatialMapFriendly.test_raster_map_render`，行 330-349：测试 `test_raster_map_render` 所表示的行为路径。
- [tests/test_multi_step_execution.py](/home/kirito/Agent1/emission_agent/tests/test_multi_step_execution.py#L351) `TestRenderSpatialMapFriendly.test_hotspot_map_render`，行 351-374：测试 `test_hotspot_map_render` 所表示的行为路径。
- [tests/test_multi_step_execution.py](/home/kirito/Agent1/emission_agent/tests/test_multi_step_execution.py#L376) `TestRenderSpatialMapFriendly.test_short_circuit_uses_structured_render`，行 376-394：测试 `test_short_circuit_uses_structured_render` 所表示的行为路径。

#### `tests/test_real_model_integration.py`

- [tests/test_real_model_integration.py](/home/kirito/Agent1/emission_agent/tests/test_real_model_integration.py#L170) `test_load_all_real_models`，行 170-188：测试 `test_load_all_real_models` 所表示的行为路径。
- [tests/test_real_model_integration.py](/home/kirito/Agent1/emission_agent/tests/test_real_model_integration.py#L193) `test_model_feature_dimensions`，行 193-209：测试真实模型特征维度与加载结果。
- [tests/test_real_model_integration.py](/home/kirito/Agent1/emission_agent/tests/test_real_model_integration.py#L215) `test_real_macro_to_dispersion_20links`，行 215-263：测试 `test_real_macro_to_dispersion_20links` 所表示的行为路径。
- [tests/test_real_model_integration.py](/home/kirito/Agent1/emission_agent/tests/test_real_model_integration.py#L280) `test_real_dispersion_all_presets`，行 280-293：测试真实扩散模型路径的结果或性能。
- [tests/test_real_model_integration.py](/home/kirito/Agent1/emission_agent/tests/test_real_model_integration.py#L300) `test_real_dispersion_all_roughness`，行 300-317：测试真实扩散模型路径的结果或性能。
- [tests/test_real_model_integration.py](/home/kirito/Agent1/emission_agent/tests/test_real_model_integration.py#L323) `test_real_dispersion_result_to_spatial_renderer`，行 323-340：测试真实扩散模型路径的结果或性能。
- [tests/test_real_model_integration.py](/home/kirito/Agent1/emission_agent/tests/test_real_model_integration.py#L346) `test_real_dispersion_performance_baseline`，行 346-374：测试真实扩散模型路径的结果或性能。

#### `tests/test_smoke_suite.py`

- [tests/test_smoke_suite.py](/home/kirito/Agent1/emission_agent/tests/test_smoke_suite.py#L7) `test_run_smoke_suite_writes_summary_with_expected_defaults`，行 7-70：测试 smoke suite 的汇总输出。

#### `tests/test_readiness_gating.py`

- [tests/test_readiness_gating.py](/home/kirito/Agent1/emission_agent/tests/test_readiness_gating.py#L66) `test_geometry_missing_marks_spatial_actions_not_ready`，行 66-88：测试 `test_geometry_missing_marks_spatial_actions_not_ready` 所表示的行为路径。
- [tests/test_readiness_gating.py](/home/kirito/Agent1/emission_agent/tests/test_readiness_gating.py#L91) `test_missing_traffic_flow_marks_macro_action_repairable`，行 91-104：测试 `test_missing_traffic_flow_marks_macro_action_repairable` 所表示的行为路径。
- [tests/test_readiness_gating.py](/home/kirito/Agent1/emission_agent/tests/test_readiness_gating.py#L107) `test_download_artifact_already_provided_is_deduplicated`，行 107-125：测试 `test_download_artifact_already_provided_is_deduplicated` 所表示的行为路径。
- [tests/test_readiness_gating.py](/home/kirito/Agent1/emission_agent/tests/test_readiness_gating.py#L128) `test_standard_macro_input_is_ready`，行 128-137：测试 `test_standard_macro_input_is_ready` 所表示的行为路径。

#### `tests/test_capability_aware_synthesis.py`

- [tests/test_capability_aware_synthesis.py](/home/kirito/Agent1/emission_agent/tests/test_capability_aware_synthesis.py#L88) `test_build_capability_summary_blocks_spatial_actions_without_geometry`，行 88-111：测试 capability summary 的构建结果。
- [tests/test_capability_aware_synthesis.py](/home/kirito/Agent1/emission_agent/tests/test_capability_aware_synthesis.py#L114) `test_capability_summary_exposes_chart_and_summary_follow_up_surface_without_geometry`，行 114-134：测试 `test_capability_summary_exposes_chart_and_summary_follow_up_surface_without_geometry` 所表示的行为路径。
- [tests/test_capability_aware_synthesis.py](/home/kirito/Agent1/emission_agent/tests/test_capability_aware_synthesis.py#L137) `test_standard_csv_without_geometry_keeps_spatial_suggestions_out`，行 137-171：测试 `test_standard_csv_without_geometry_keeps_spatial_suggestions_out` 所表示的行为路径。
- [tests/test_capability_aware_synthesis.py](/home/kirito/Agent1/emission_agent/tests/test_capability_aware_synthesis.py#L174) `test_build_capability_summary_enables_spatial_actions_with_geometry`，行 174-188：测试 capability summary 的构建结果。
- [tests/test_capability_aware_synthesis.py](/home/kirito/Agent1/emission_agent/tests/test_capability_aware_synthesis.py#L191) `test_build_capability_summary_suppresses_redundant_map_action_when_map_already_provided`，行 191-206：测试 capability summary 的构建结果。
- [tests/test_capability_aware_synthesis.py](/home/kirito/Agent1/emission_agent/tests/test_capability_aware_synthesis.py#L209) `test_build_capability_summary_after_dispersion_supports_hotspots_but_blocks_render_without_spatial`，行 209-231：测试 capability summary 的构建结果。
- [tests/test_capability_aware_synthesis.py](/home/kirito/Agent1/emission_agent/tests/test_capability_aware_synthesis.py#L234) `test_render_single_tool_success_filters_follow_up_with_capability_summary`，行 234-251：测试 `test_render_single_tool_success_filters_follow_up_with_capability_summary` 所表示的行为路径。
- [tests/test_capability_aware_synthesis.py](/home/kirito/Agent1/emission_agent/tests/test_capability_aware_synthesis.py#L254) `test_router_build_capability_summary_logs_summary_payload`，行 254-270：测试 capability summary 的构建结果。
- [tests/test_capability_aware_synthesis.py](/home/kirito/Agent1/emission_agent/tests/test_capability_aware_synthesis.py#L274) `test_synthesize_results_injects_capability_constraints_into_prompt`，行 274-321：测试结果综合阶段的调用与输出。

### 5.3 当前测试运行方式、pytest 配置与 CI/CD

- pytest 配置存在于 [pyproject.toml](/home/kirito/Agent1/emission_agent/pyproject.toml#L1) `[tool.pytest.ini_options]`，行 8-13。
- 当前仓库中的测试入口包括 `pytest`（由 `pyproject.toml` 定义 `tests/` 路径）以及 `scripts/utils/test_*.py` / `evaluation/*.py` 形式的脚本式检查。
- CI/CD 方面，本次静态扫描命中 [.github/workflows/deploy.yml](/home/kirito/Agent1/emission_agent/.github/workflows/deploy.yml#L1) 一个 GitHub Actions workflow，行 1-71；其名称为 `Deploy to Alibaba Cloud`，触发条件为 `push` 到 `main` 与 `workflow_dispatch`。
- 本次静态扫描未在 `.github/workflows/` 下发现单独的测试 workflow。

pyproject.toml 中 pytest 相关配置：

```toml
[project]
name = "emission-agent"
version = "2.2.0"
description = "LLM-powered vehicle emission calculation assistant using EPA MOVES methodology"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.10"

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]
addopts = "-v --tb=short"
```
## 6. 模块间依赖关系图

### `core/router.py`

- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L12) 第 12 行：`from config import get_config` -> `config`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L13) 第 13 行：`from core.assembler import ContextAssembler` -> `core.assembler`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L14) 第 14 行：`from core.context_store import SessionContextStore` -> `core.context_store`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L15) 第 15 行：`from core.executor import ToolExecutor` -> `core.executor`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L16) 第 16 行：`from core.artifact_memory import (` -> `core.artifact_memory`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L23) 第 23 行：`from core.file_relationship_resolution import (` -> `core.file_relationship_resolution`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L34) 第 34 行：`from core.file_analysis_fallback import (` -> `core.file_analysis_fallback`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L41) 第 41 行：`from core.geometry_recovery import (` -> `core.geometry_recovery`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L48) 第 48 行：`from core.input_completion import (` -> `core.input_completion`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L60) 第 60 行：`from core.intent_resolution import (` -> `core.intent_resolution`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L73) 第 73 行：`from core.memory import MemoryManager` -> `core.memory`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L74) 第 74 行：`from core.output_safety import sanitize_response` -> `core.output_safety`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L75) 第 75 行：`from core.remediation_policy import (` -> `core.remediation_policy`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L83) 第 83 行：`from core.parameter_negotiation import (` -> `core.parameter_negotiation`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L94) 第 94 行：`from core.plan import ExecutionPlan, PlanStatus, PlanStep, PlanStepStatus` -> `core.plan`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L95) 第 95 行：`from core.plan_repair import (` -> `core.plan_repair`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L104) 第 104 行：`from core.readiness import (` -> `core.readiness`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L114) 第 114 行：`from core.residual_reentry import (` -> `core.residual_reentry`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L121) 第 121 行：`from core.supplemental_merge import (` -> `core.supplemental_merge`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L130) 第 130 行：`from core.summary_delivery import (` -> `core.summary_delivery`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L138) 第 138 行：`from core.task_state import (` -> `core.task_state`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L145) 第 145 行：`from core.tool_dependencies import (` -> `core.tool_dependencies`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L154) 第 154 行：`from core.trace import Trace, TraceStepType` -> `core.trace`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L155) 第 155 行：`from core.workflow_templates import (` -> `core.workflow_templates`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L163) 第 163 行：`from core.router_memory_utils import (` -> `core.router_memory_utils`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L167) 第 167 行：`from core.router_payload_utils import (` -> `core.router_payload_utils`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L174) 第 174 行：`from core.router_render_utils import (` -> `core.router_render_utils`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L181) 第 181 行：`from core.router_synthesis_utils import (` -> `core.router_synthesis_utils`
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L186) 第 186 行：`from services.llm_client import get_llm_client` -> `services.llm_client`

### `core/executor.py`

- [core/executor.py](/home/kirito/Agent1/emission_agent/core/executor.py#L7) 第 7 行：`from config import get_config` -> `config`
- [core/executor.py](/home/kirito/Agent1/emission_agent/core/executor.py#L8) 第 8 行：`from tools.registry import get_registry` -> `tools.registry`
- [core/executor.py](/home/kirito/Agent1/emission_agent/core/executor.py#L9) 第 9 行：`from services.standardization_engine import BatchStandardizationError, StandardizationEngine` -> `services.standardization_engine`

### `core/task_state.py`

- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py#L7) 第 7 行：`from core.geometry_recovery import (` -> `core.geometry_recovery`
- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py#L11) 第 11 行：`from core.file_relationship_resolution import (` -> `core.file_relationship_resolution`
- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py#L16) 第 16 行：`from core.artifact_memory import ArtifactMemoryState` -> `core.artifact_memory`
- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py#L17) 第 17 行：`from core.input_completion import (` -> `core.input_completion`
- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py#L21) 第 21 行：`from core.intent_resolution import (` -> `core.intent_resolution`
- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py#L25) 第 25 行：`from core.parameter_negotiation import (` -> `core.parameter_negotiation`
- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py#L29) 第 29 行：`from core.plan import ExecutionPlan, PlanStep, PlanStepStatus` -> `core.plan`
- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py#L30) 第 30 行：`from core.plan_repair import PlanRepairDecision` -> `core.plan_repair`
- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py#L31) 第 31 行：`from core.residual_reentry import RecoveredWorkflowReentryContext` -> `core.residual_reentry`
- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py#L32) 第 32 行：`from core.supplemental_merge import (` -> `core.supplemental_merge`
- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py#L36) 第 36 行：`from core.summary_delivery import (` -> `core.summary_delivery`
- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py#L40) 第 40 行：`from core.workflow_templates import (` -> `core.workflow_templates`

### `core/readiness.py`

- [core/readiness.py](/home/kirito/Agent1/emission_agent/core/readiness.py#L9) 第 9 行：`from core.artifact_memory import (` -> `core.artifact_memory`
- [core/readiness.py](/home/kirito/Agent1/emission_agent/core/readiness.py#L15) 第 15 行：`from core.tool_dependencies import (` -> `core.tool_dependencies`

### `core/trace.py`

未发现 emission_agent 内部 import。

### `core/plan.py`

未发现 emission_agent 内部 import。

### `core/plan_repair.py`

- [core/plan_repair.py](/home/kirito/Agent1/emission_agent/core/plan_repair.py#L7) 第 7 行：`from core.plan import ExecutionPlan, PlanStatus, PlanStep, PlanStepStatus` -> `core.plan`
- [core/plan_repair.py](/home/kirito/Agent1/emission_agent/core/plan_repair.py#L8) 第 8 行：`from core.tool_dependencies import (` -> `core.tool_dependencies`

### `core/parameter_negotiation.py`

未发现 emission_agent 内部 import。

### `core/input_completion.py`

未发现 emission_agent 内部 import。

### `core/capability_summary.py`

- [core/capability_summary.py](/home/kirito/Agent1/emission_agent/core/capability_summary.py#L7) 第 7 行：`from core.artifact_memory import (` -> `core.artifact_memory`
- [core/capability_summary.py](/home/kirito/Agent1/emission_agent/core/capability_summary.py#L11) 第 11 行：`from core.intent_resolution import IntentResolutionApplicationPlan` -> `core.intent_resolution`
- [core/capability_summary.py](/home/kirito/Agent1/emission_agent/core/capability_summary.py#L12) 第 12 行：`from core.readiness import build_readiness_assessment` -> `core.readiness`

### `core/context_store.py`

- [core/context_store.py](/home/kirito/Agent1/emission_agent/core/context_store.py#L10) 第 10 行：`from core.tool_dependencies import normalize_result_token` -> `core.tool_dependencies`

### `core/memory.py`

未发现 emission_agent 内部 import。

### `services/standardizer.py`

- [services/standardizer.py](/home/kirito/Agent1/emission_agent/services/standardizer.py#L11) 第 11 行：`from services.config_loader import ConfigLoader` -> `services.config_loader`

### `services/standardization_engine.py`

- [services/standardization_engine.py](/home/kirito/Agent1/emission_agent/services/standardization_engine.py#L28) 第 28 行：`from config import get_config` -> `config`
- [services/standardization_engine.py](/home/kirito/Agent1/emission_agent/services/standardization_engine.py#L29) 第 29 行：`from services.config_loader import ConfigLoader` -> `services.config_loader`
- [services/standardization_engine.py](/home/kirito/Agent1/emission_agent/services/standardization_engine.py#L30) 第 30 行：`from services.standardizer import StandardizationResult, UnifiedStandardizer, get_standardizer` -> `services.standardizer`

### `services/config_loader.py`

未发现 emission_agent 内部 import。

### `tools/base.py`

未发现 emission_agent 内部 import。

### `tools/registry.py`

- [tools/registry.py](/home/kirito/Agent1/emission_agent/tools/registry.py#L7) 第 7 行：`from tools.base import BaseTool` -> `tools.base`

### `tools/definitions.py`

未发现 emission_agent 内部 import。

### `tools/file_analyzer.py`

- [tools/file_analyzer.py](/home/kirito/Agent1/emission_agent/tools/file_analyzer.py#L14) 第 14 行：`from tools.base import BaseTool, ToolResult` -> `tools.base`
- [tools/file_analyzer.py](/home/kirito/Agent1/emission_agent/tools/file_analyzer.py#L15) 第 15 行：`from services.standardizer import get_standardizer` -> `services.standardizer`

### 6.1 结论

- 基于全仓库顶层内部 import 的静态图分析，未发现循环依赖。
- `core/router.py` 顶层直接 import 了 29 个内部模块：见 [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L12) 到 [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L186)。
- 静态 AST 名称使用分析命中的“被 import 但未实际使用”的内部导入：
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L75) 第 75 行：`core.remediation_policy.RemediationPolicyApplicationResult`（绑定名 `RemediationPolicyApplicationResult`）
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L75) 第 75 行：`core.remediation_policy.RemediationPolicyDecision`（绑定名 `RemediationPolicyDecision`）
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L114) 第 114 行：`core.residual_reentry.ReentryStatus`（绑定名 `ReentryStatus`）
  - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L130) 第 130 行：`core.summary_delivery.SummaryDeliveryType`（绑定名 `SummaryDeliveryType`）
  - [core/plan_repair.py](/home/kirito/Agent1/emission_agent/core/plan_repair.py#L8) 第 8 行：`core.tool_dependencies.normalize_result_token`（绑定名 `normalize_result_token`）

## 7. 遗留问题清单

以下 10 项为本次审查过程中记录到的异常或遗留现状，按文件位置引用。

1. 命名与结构不一致：`config.py` 未定义 `AppConfig`，当前定义的是 `Config`。位置：`config.py:17-264`，对象：`Config`。说明：本次要求中的 `AppConfig` 在代码中无法确认；当前实际类名为 `Config`。
2. `Config` 使用 `@dataclass`，但属性在 `__post_init__()` 中动态创建。位置：`config.py:16-264`，对象：`Config`。说明：类体没有显式字段注解，配置项在 `__post_init__()` 中按环境变量逐项赋值。
3. `.env.example` 与 `config.py` 不同步。 位置：`.env.example:1-64；config.py:17-260`。说明：静态比对显示 `config.py` 读取 99 个环境变量，`.env.example` 仅声明 28 个，其中缺少 77 个，另有 6 个示例项未被 `config.py` 读取。
4. `core/router.py` 规模和耦合度集中。位置：`core/router.py:327-9999`，对象：`UnifiedRouter`；另见 `core/router.py:12-186` 顶层 imports。说明：`UnifiedRouter` 单文件 9999 行，顶层直接 import 29 个内部模块。
5. `core/router.py` 存在未使用的内部 import：`RemediationPolicyApplicationResult`。 位置：`core/router.py:75`。说明：静态 AST 名称使用分析未发现该导入名被引用。
6. `core/router.py` 存在未使用的内部 import：`RemediationPolicyDecision` / `ReentryStatus` / `SummaryDeliveryType`。 位置：`core/router.py:75；core/router.py:114；core/router.py:130`。说明：静态 AST 名称使用分析未发现这些导入名被引用。
7. `core/plan_repair.py` 导入了未使用的 `normalize_result_token`。 位置：`core/plan_repair.py:8`。说明：静态 AST 名称使用分析未发现 `normalize_result_token` 被引用。
8. 生产代码中存在显式 debug 日志。 位置：`core/router.py:9745-9754；core/router_payload_utils.py:105-323；web/app.js:418-1281`。说明：静态搜索命中多个 `[DEBUG]` / `[DEBUG EXTRACT]` / `[DEBUG TABLE]` 输出。
9. LLM 客户端 failover 逻辑存在跨模块重复迹象。 位置：`services/llm_client.py:17；llm/client.py:17`。说明：两个模块都保留了 TODO，互相指向对方并说明未来需要合并共享 failover 逻辑。
10. `ControlState.max_steps` 与全局配置 `max_orchestration_steps` 出现双重默认来源。位置：`core/task_state.py:209`，对象：`ControlState.max_steps`；`config.py:201`，对象：`max_orchestration_steps`；`core/router.py:887`，对象：运行时覆盖语句。说明：`ControlState` 数据类自带默认值 4，同时 router 在运行时又把 `state.control.max_steps` 覆盖为 `config.max_orchestration_steps`。

## 自检

- [x] TaskState 及所有子数据类的完整定义已贴出
- [x] TraceStepType 完整枚举已贴出
- [x] Trace 类完整代码已贴出
- [x] 5个代表性 trace.record() 调用已贴出
- [x] MemoryManager 完整代码已贴出
- [x] SessionContextStore 完整代码已贴出
- [x] AppConfig 对应现状已说明，并贴出 `config.py` 当前完整代码
- [x] 功能开关已按 `Config.__post_init__()` 提取并列出检查位置
- [x] evaluation/ 目录代码已完整贴出
- [x] 关键测试文件的函数列表已提供
- [x] 模块间依赖关系已列出
- [x] 循环依赖已检查
- [x] 遗留问题已记录（10项）
