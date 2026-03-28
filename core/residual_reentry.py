from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from core.geometry_recovery import GeometryRecoveryContext
from core.plan import ExecutionPlan, PlanStep
from core.readiness import get_action_catalog, map_tool_call_to_action_id


class ReentryStatus(str, Enum):
    TARGET_SET = "target_set"
    BIAS_APPLIED = "bias_applied"
    SKIPPED = "skipped"
    STALE = "stale"


@dataclass
class ResidualReentryTarget:
    target_action_id: Optional[str]
    target_tool_name: Optional[str]
    target_step_id: Optional[str]
    source: str
    reason: Optional[str]
    priority: int
    target_tool_arguments: Dict[str, Any] = field(default_factory=dict)
    display_name: Optional[str] = None
    residual_plan_relationship: Optional[str] = None
    matches_next_pending_step: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_action_id": self.target_action_id,
            "target_tool_name": self.target_tool_name,
            "target_step_id": self.target_step_id,
            "source": self.source,
            "reason": self.reason,
            "priority": self.priority,
            "target_tool_arguments": dict(self.target_tool_arguments),
            "display_name": self.display_name,
            "residual_plan_relationship": self.residual_plan_relationship,
            "matches_next_pending_step": self.matches_next_pending_step,
        }

    def to_summary(self) -> Dict[str, Any]:
        return {
            "target_action_id": self.target_action_id,
            "target_tool_name": self.target_tool_name,
            "target_step_id": self.target_step_id,
            "source": self.source,
            "priority": self.priority,
            "display_name": self.display_name,
            "residual_plan_relationship": self.residual_plan_relationship,
            "matches_next_pending_step": self.matches_next_pending_step,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["ResidualReentryTarget"]:
        if not isinstance(data, dict):
            return None
        priority = data.get("priority", 100)
        try:
            normalized_priority = int(priority)
        except (TypeError, ValueError):
            normalized_priority = 100
        return cls(
            target_action_id=(
                str(data.get("target_action_id")).strip()
                if data.get("target_action_id") is not None
                else None
            ),
            target_tool_name=(
                str(data.get("target_tool_name")).strip()
                if data.get("target_tool_name") is not None
                else None
            ),
            target_step_id=(
                str(data.get("target_step_id")).strip()
                if data.get("target_step_id") is not None
                else None
            ),
            source=str(data.get("source") or "").strip() or "geometry_recovery",
            reason=str(data.get("reason")).strip() if data.get("reason") is not None else None,
            priority=normalized_priority,
            target_tool_arguments=dict(data.get("target_tool_arguments") or {}),
            display_name=(
                str(data.get("display_name")).strip()
                if data.get("display_name") is not None
                else None
            ),
            residual_plan_relationship=(
                str(data.get("residual_plan_relationship")).strip()
                if data.get("residual_plan_relationship") is not None
                else None
            ),
            matches_next_pending_step=bool(data.get("matches_next_pending_step", False)),
        )


@dataclass
class ReentryDecision:
    should_apply: bool = False
    decision_status: str = "skipped"
    reason: Optional[str] = None
    target: Optional[ResidualReentryTarget] = None
    source: Optional[str] = None
    guidance_summary: Optional[str] = None
    target_ready: Optional[bool] = None
    readiness_status: Optional[str] = None
    continuation_signal: Optional[str] = None
    new_task_override: bool = False
    residual_plan_exists: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "should_apply": self.should_apply,
            "decision_status": self.decision_status,
            "reason": self.reason,
            "target": self.target.to_dict() if self.target is not None else None,
            "source": self.source,
            "guidance_summary": self.guidance_summary,
            "target_ready": self.target_ready,
            "readiness_status": self.readiness_status,
            "continuation_signal": self.continuation_signal,
            "new_task_override": self.new_task_override,
            "residual_plan_exists": self.residual_plan_exists,
        }


@dataclass
class RecoveredWorkflowReentryContext:
    reentry_target: ResidualReentryTarget
    residual_plan_summary: Optional[str]
    geometry_recovery_context: GeometryRecoveryContext
    readiness_refresh_result: Optional[Dict[str, Any]]
    reentry_status: str = ReentryStatus.TARGET_SET.value
    reentry_guidance_summary: Optional[str] = None
    last_decision_reason: Optional[str] = None
    bias_applied_on_turn: bool = False
    target_ready: Optional[bool] = None
    last_target_readiness_status: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reentry_target": self.reentry_target.to_dict(),
            "residual_plan_summary": self.residual_plan_summary,
            "geometry_recovery_context": self.geometry_recovery_context.to_dict(),
            "readiness_refresh_result": dict(self.readiness_refresh_result or {}),
            "reentry_status": self.reentry_status,
            "reentry_guidance_summary": self.reentry_guidance_summary,
            "last_decision_reason": self.last_decision_reason,
            "bias_applied_on_turn": self.bias_applied_on_turn,
            "target_ready": self.target_ready,
            "last_target_readiness_status": self.last_target_readiness_status,
        }

    def to_summary(self) -> Dict[str, Any]:
        return {
            "reentry_target": self.reentry_target.to_summary(),
            "reentry_status": self.reentry_status,
            "reentry_guidance_summary": self.reentry_guidance_summary,
            "last_decision_reason": self.last_decision_reason,
            "bias_applied_on_turn": self.bias_applied_on_turn,
            "target_ready": self.target_ready,
            "last_target_readiness_status": self.last_target_readiness_status,
        }

    def apply_decision(self, decision: ReentryDecision) -> None:
        self.last_decision_reason = decision.reason
        self.bias_applied_on_turn = bool(decision.should_apply)
        self.target_ready = decision.target_ready
        self.last_target_readiness_status = decision.readiness_status
        if decision.guidance_summary:
            self.reentry_guidance_summary = decision.guidance_summary
        if decision.should_apply:
            self.reentry_status = ReentryStatus.BIAS_APPLIED.value
        elif decision.target_ready is False:
            self.reentry_status = ReentryStatus.STALE.value
        else:
            self.reentry_status = ReentryStatus.SKIPPED.value

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["RecoveredWorkflowReentryContext"]:
        if not isinstance(data, dict):
            return None
        reentry_target = ResidualReentryTarget.from_dict(data.get("reentry_target"))
        geometry_context = GeometryRecoveryContext.from_dict(data.get("geometry_recovery_context"))
        if reentry_target is None or geometry_context is None:
            return None
        return cls(
            reentry_target=reentry_target,
            residual_plan_summary=(
                str(data.get("residual_plan_summary")).strip()
                if data.get("residual_plan_summary") is not None
                else None
            ),
            geometry_recovery_context=geometry_context,
            readiness_refresh_result=dict(data.get("readiness_refresh_result") or {}) or None,
            reentry_status=str(data.get("reentry_status") or ReentryStatus.TARGET_SET.value).strip(),
            reentry_guidance_summary=(
                str(data.get("reentry_guidance_summary")).strip()
                if data.get("reentry_guidance_summary") is not None
                else None
            ),
            last_decision_reason=(
                str(data.get("last_decision_reason")).strip()
                if data.get("last_decision_reason") is not None
                else None
            ),
            bias_applied_on_turn=bool(data.get("bias_applied_on_turn", False)),
            target_ready=data.get("target_ready"),
            last_target_readiness_status=(
                str(data.get("last_target_readiness_status")).strip()
                if data.get("last_target_readiness_status") is not None
                else None
            ),
        )


def _catalog_entry_by_action_id(action_id: Optional[str]) -> Optional[Any]:
    if not action_id:
        return None
    for entry in get_action_catalog():
        if entry.action_id == action_id:
            return entry
    return None


def _find_matching_pending_step(
    plan: Optional[ExecutionPlan],
    *,
    target_action_id: Optional[str],
    target_tool_name: Optional[str],
) -> Optional[PlanStep]:
    if plan is None:
        return None
    for step in plan.get_pending_steps():
        step_action_id = map_tool_call_to_action_id(step.tool_name, step.argument_hints)
        if target_action_id and step_action_id == target_action_id:
            return step
        if target_tool_name and step.tool_name == target_tool_name:
            return step
    return None


def build_residual_reentry_target(
    *,
    geometry_recovery_context: GeometryRecoveryContext,
    residual_plan: Optional[ExecutionPlan] = None,
    prioritize_recovery_target: bool = True,
) -> ResidualReentryTarget:
    action_id = geometry_recovery_context.target_action_id
    catalog_entry = _catalog_entry_by_action_id(action_id)
    target_tool_name = catalog_entry.tool_name if catalog_entry is not None else None
    target_tool_arguments = dict(getattr(catalog_entry, "arguments", {}) or {})
    display_name = getattr(catalog_entry, "display_name", None) if catalog_entry is not None else None
    source = "geometry_recovery"
    priority = 100 if prioritize_recovery_target else 80

    next_step = residual_plan.get_next_pending_step() if residual_plan is not None else None
    matched_step = _find_matching_pending_step(
        residual_plan,
        target_action_id=action_id,
        target_tool_name=target_tool_name,
    )

    target_step_id = None
    residual_plan_relationship = "no_residual_plan"
    matches_next_pending_step = False

    if next_step is not None and matched_step is not None and matched_step.step_id == next_step.step_id:
        target_step_id = next_step.step_id
        target_tool_name = next_step.tool_name
        target_tool_arguments = dict(next_step.argument_hints or {}) or target_tool_arguments
        residual_plan_relationship = "aligned_with_next_pending_step"
        matches_next_pending_step = True
    elif matched_step is not None:
        target_step_id = matched_step.step_id
        target_tool_name = matched_step.tool_name
        target_tool_arguments = dict(matched_step.argument_hints or {}) or target_tool_arguments
        residual_plan_relationship = "recovered_target_within_residual_plan"
    elif next_step is not None:
        residual_plan_relationship = "recovery_target_prioritized_over_next_pending_step"
        if not prioritize_recovery_target:
            target_step_id = next_step.step_id
            target_tool_name = next_step.tool_name
            target_tool_arguments = dict(next_step.argument_hints or {})
            action_id = map_tool_call_to_action_id(next_step.tool_name, next_step.argument_hints) or action_id
            fallback_entry = _catalog_entry_by_action_id(action_id)
            if fallback_entry is not None:
                display_name = fallback_entry.display_name
            source = "continuation"
            priority = 80
            residual_plan_relationship = "fallback_next_pending_step"

    if residual_plan_relationship == "aligned_with_next_pending_step":
        reason = "The repaired geometry target matched the next pending residual step, so it was bound as the primary re-entry target."
    elif residual_plan_relationship == "recovered_target_within_residual_plan":
        reason = "The repaired geometry target remained within the residual workflow and was promoted as the primary re-entry target."
    elif residual_plan_relationship == "recovery_target_prioritized_over_next_pending_step":
        reason = "The repaired geometry target remained the preferred re-entry target even though the residual next pending step summary was retained."
    elif residual_plan_relationship == "fallback_next_pending_step":
        reason = "The re-entry controller fell back to the next pending residual step because recovery-target prioritization was disabled."
    else:
        reason = "The repaired action became the sole bounded re-entry target because no residual plan was available."

    return ResidualReentryTarget(
        target_action_id=action_id,
        target_tool_name=target_tool_name,
        target_step_id=target_step_id,
        source=source,
        reason=reason,
        priority=priority,
        target_tool_arguments=target_tool_arguments,
        display_name=display_name,
        residual_plan_relationship=residual_plan_relationship,
        matches_next_pending_step=matches_next_pending_step,
    )


def build_reentry_guidance_summary(
    *,
    reentry_target: ResidualReentryTarget,
    residual_plan_summary: Optional[str],
    geometry_recovery_context: GeometryRecoveryContext,
) -> str:
    target_name = reentry_target.display_name or reentry_target.target_action_id or "recovered_action"
    lines = ["[Recovered workflow re-entry target]"]
    lines.append(
        "This workflow was previously repaired through bounded geometry recovery. Treat the recovered target below as the highest-priority continuation hint for this turn."
    )
    lines.append(
        f"Primary re-entry target: {target_name} -> {reentry_target.target_tool_name or 'unknown_tool'}"
    )
    if reentry_target.target_step_id:
        lines.append(f"Recovered target step: {reentry_target.target_step_id}")
    lines.append(f"Target source: {reentry_target.source}")
    if reentry_target.residual_plan_relationship:
        lines.append(
            f"Residual-plan relationship: {reentry_target.residual_plan_relationship}"
        )
    if residual_plan_summary:
        lines.append(f"Residual workflow summary: {residual_plan_summary}")
    if geometry_recovery_context.resume_hint:
        lines.append(f"Recovery resume hint: {geometry_recovery_context.resume_hint}")
    lines.append(
        "Tool-selection rule: prefer this recovered target before other residual steps when the user is continuing the same workflow. Do not auto-execute and do not replay the whole workflow."
    )
    return "\n".join(lines)


def build_recovered_workflow_reentry_context(
    *,
    geometry_recovery_context: GeometryRecoveryContext,
    readiness_refresh_result: Optional[Dict[str, Any]],
    residual_plan: Optional[ExecutionPlan] = None,
    residual_plan_summary: Optional[str] = None,
    prioritize_recovery_target: bool = True,
) -> RecoveredWorkflowReentryContext:
    target = build_residual_reentry_target(
        geometry_recovery_context=geometry_recovery_context,
        residual_plan=residual_plan,
        prioritize_recovery_target=prioritize_recovery_target,
    )
    summary = residual_plan_summary or geometry_recovery_context.residual_plan_summary
    return RecoveredWorkflowReentryContext(
        reentry_target=target,
        residual_plan_summary=summary,
        geometry_recovery_context=geometry_recovery_context,
        readiness_refresh_result=dict(readiness_refresh_result or {}) or None,
        reentry_status=ReentryStatus.TARGET_SET.value,
        reentry_guidance_summary=build_reentry_guidance_summary(
            reentry_target=target,
            residual_plan_summary=summary,
            geometry_recovery_context=geometry_recovery_context,
        ),
        last_decision_reason=target.reason,
    )
