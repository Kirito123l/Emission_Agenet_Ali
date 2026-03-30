from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional

from core.plan import ExecutionPlan, PlanStatus, PlanStep, PlanStepStatus
from core.tool_dependencies import (
    TOOL_GRAPH,
    get_required_result_tokens,
    get_tool_provides,
    normalize_tokens,
    validate_plan_steps,
)


class RepairTriggerType(str, Enum):
    PLAN_DEVIATION = "plan_deviation"
    DEPENDENCY_BLOCKED = "dependency_blocked"


class RepairActionType(str, Enum):
    KEEP_REMAINING = "KEEP_REMAINING"
    DROP_BLOCKED_STEP = "DROP_BLOCKED_STEP"
    REORDER_REMAINING_STEPS = "REORDER_REMAINING_STEPS"
    REPLACE_STEP = "REPLACE_STEP"
    TRUNCATE_AFTER_CURRENT = "TRUNCATE_AFTER_CURRENT"
    APPEND_RECOVERY_STEP = "APPEND_RECOVERY_STEP"
    NO_REPAIR = "NO_REPAIR"


def _coerce_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_string_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    result: List[str] = []
    for item in values:
        text = _coerce_string(item)
        if text:
            result.append(text)
    return result


def _coerce_enum(value: Any, enum_cls: type[Enum], default: Enum) -> Enum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except Exception:
        return default


def _clone_step(step: PlanStep) -> PlanStep:
    return PlanStep.from_dict(step.to_dict())


def clone_plan(plan: ExecutionPlan) -> ExecutionPlan:
    return ExecutionPlan.from_dict(plan.to_dict())


def _allowed_result_tokens() -> List[str]:
    tokens: List[str] = ["emission", "dispersion", "hotspot"]
    for spec in TOOL_GRAPH.values():
        tokens.extend(spec.get("requires", []))
        tokens.extend(spec.get("provides", []))
    return normalize_tokens(tokens)


def _allocate_repair_step_id(plan: ExecutionPlan, preferred: Optional[str] = None) -> str:
    existing = {step.step_id for step in plan.steps}
    candidate = _coerce_string(preferred)
    if candidate and candidate not in existing:
        return candidate

    index = 1
    while True:
        candidate = f"repair_s{index}"
        if candidate not in existing:
            return candidate
        index += 1


def _is_mutable_step(step: PlanStep) -> bool:
    return step.status not in {
        PlanStepStatus.COMPLETED,
        PlanStepStatus.SKIPPED,
        PlanStepStatus.FAILED,
    }


def _active_residual_step(step: PlanStep) -> bool:
    return step.status not in {
        PlanStepStatus.COMPLETED,
        PlanStepStatus.SKIPPED,
        PlanStepStatus.FAILED,
    }


def _append_unique(target: List[str], note: Optional[str]) -> None:
    text = _coerce_string(note)
    if text and text not in target:
        target.append(text)


@dataclass
class RepairTriggerContext:
    trigger_type: RepairTriggerType
    trigger_reason: str
    target_step_id: Optional[str] = None
    affected_step_ids: List[str] = field(default_factory=list)
    actual_tool_name: Optional[str] = None
    deviation_type: Optional[str] = None
    available_tokens: List[str] = field(default_factory=list)
    missing_tokens: List[str] = field(default_factory=list)
    stale_tokens: List[str] = field(default_factory=list)
    next_pending_step_id: Optional[str] = None
    next_pending_tool_name: Optional[str] = None
    matched_step_id: Optional[str] = None
    blocked_tool_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger_type": self.trigger_type.value,
            "trigger_reason": self.trigger_reason,
            "target_step_id": self.target_step_id,
            "affected_step_ids": list(self.affected_step_ids),
            "actual_tool_name": self.actual_tool_name,
            "deviation_type": self.deviation_type,
            "available_tokens": list(self.available_tokens),
            "missing_tokens": list(self.missing_tokens),
            "stale_tokens": list(self.stale_tokens),
            "next_pending_step_id": self.next_pending_step_id,
            "next_pending_tool_name": self.next_pending_tool_name,
            "matched_step_id": self.matched_step_id,
            "blocked_tool_name": self.blocked_tool_name,
        }


@dataclass
class PlanRepairPatch:
    target_step_id: Optional[str] = None
    affected_step_ids: List[str] = field(default_factory=list)
    skip_step_ids: List[str] = field(default_factory=list)
    reordered_step_ids: List[str] = field(default_factory=list)
    replacement_step: Optional[PlanStep] = None
    append_steps: List[PlanStep] = field(default_factory=list)
    truncate_after_step_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_step_id": self.target_step_id,
            "affected_step_ids": list(self.affected_step_ids),
            "skip_step_ids": list(self.skip_step_ids),
            "reordered_step_ids": list(self.reordered_step_ids),
            "replacement_step": self.replacement_step.to_dict() if self.replacement_step else None,
            "append_steps": [step.to_dict() for step in self.append_steps],
            "truncate_after_step_id": self.truncate_after_step_id,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "PlanRepairPatch":
        payload = data if isinstance(data, dict) else {}
        replacement_payload = payload.get("replacement_step")
        append_payloads = payload.get("append_steps") or []
        return cls(
            target_step_id=_coerce_string(payload.get("target_step_id")),
            affected_step_ids=_coerce_string_list(payload.get("affected_step_ids")),
            skip_step_ids=_coerce_string_list(payload.get("skip_step_ids")),
            reordered_step_ids=_coerce_string_list(payload.get("reordered_step_ids")),
            replacement_step=(
                PlanStep.from_dict(replacement_payload)
                if isinstance(replacement_payload, dict)
                else None
            ),
            append_steps=[
                PlanStep.from_dict(item)
                for item in append_payloads
                if isinstance(item, dict)
            ],
            truncate_after_step_id=_coerce_string(payload.get("truncate_after_step_id")),
        )


@dataclass
class PlanRepairDecision:
    trigger_type: RepairTriggerType
    trigger_reason: str
    action_type: RepairActionType
    target_step_id: Optional[str] = None
    affected_step_ids: List[str] = field(default_factory=list)
    planner_notes: Optional[str] = None
    is_applicable: bool = False
    validation_notes: List[str] = field(default_factory=list)
    patch: PlanRepairPatch = field(default_factory=PlanRepairPatch)
    repaired_plan_snapshot: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger_type": self.trigger_type.value,
            "trigger_reason": self.trigger_reason,
            "action_type": self.action_type.value,
            "target_step_id": self.target_step_id,
            "affected_step_ids": list(self.affected_step_ids),
            "planner_notes": self.planner_notes,
            "is_applicable": self.is_applicable,
            "validation_notes": list(self.validation_notes),
            "patch": self.patch.to_dict(),
            "repaired_plan_snapshot": self.repaired_plan_snapshot,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "PlanRepairDecision":
        payload = data if isinstance(data, dict) else {}
        patch = PlanRepairPatch.from_dict(payload.get("patch"))
        target_step_id = _coerce_string(payload.get("target_step_id")) or patch.target_step_id
        affected_step_ids = _coerce_string_list(payload.get("affected_step_ids")) or patch.affected_step_ids
        return cls(
            trigger_type=_coerce_enum(
                payload.get("trigger_type"),
                RepairTriggerType,
                RepairTriggerType.PLAN_DEVIATION,
            ),
            trigger_reason=_coerce_string(payload.get("trigger_reason")) or "",
            action_type=_coerce_enum(
                payload.get("action_type"),
                RepairActionType,
                RepairActionType.NO_REPAIR,
            ),
            target_step_id=target_step_id,
            affected_step_ids=affected_step_ids,
            planner_notes=_coerce_string(payload.get("planner_notes")),
            is_applicable=bool(payload.get("is_applicable", False)),
            validation_notes=_coerce_string_list(payload.get("validation_notes")),
            patch=patch,
            repaired_plan_snapshot=(
                payload.get("repaired_plan_snapshot")
                if isinstance(payload.get("repaired_plan_snapshot"), dict)
                else None
            ),
        )


@dataclass
class RepairValidationIssue:
    issue_type: str
    message: str
    step_id: Optional[str] = None
    tool_name: Optional[str] = None
    token: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_type": self.issue_type,
            "message": self.message,
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "token": self.token,
        }


@dataclass
class RepairValidationResult:
    action_type: RepairActionType
    is_valid: bool
    validation_notes: List[str] = field(default_factory=list)
    issues: List[RepairValidationIssue] = field(default_factory=list)
    repaired_plan: Optional[ExecutionPlan] = None
    resulting_next_pending_step: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type.value,
            "is_valid": self.is_valid,
            "validation_notes": list(self.validation_notes),
            "issues": [issue.to_dict() for issue in self.issues],
            "repaired_plan": self.repaired_plan.to_dict() if self.repaired_plan else None,
            "resulting_next_pending_step": self.resulting_next_pending_step,
        }


def _note_step_repair(
    step: PlanStep,
    *,
    action_type: RepairActionType,
    note: str,
    source_step_id: Optional[str] = None,
) -> None:
    step.repair_action = action_type.value
    if source_step_id:
        step.repair_source_step_id = source_step_id
    _append_unique(step.repair_notes, note)
    _append_unique(step.reconciliation_notes, note)


def _reject(
    *,
    action_type: RepairActionType,
    issues: List[RepairValidationIssue],
    notes: List[str],
) -> RepairValidationResult:
    return RepairValidationResult(
        action_type=action_type,
        is_valid=False,
        validation_notes=notes,
        issues=issues,
        repaired_plan=None,
        resulting_next_pending_step=None,
    )


def _validate_step_semantics(plan: ExecutionPlan) -> List[RepairValidationIssue]:
    issues: List[RepairValidationIssue] = []
    allowed_tokens = set(_allowed_result_tokens())

    for step in plan.steps:
        if step.tool_name not in TOOL_GRAPH:
            issues.append(
                RepairValidationIssue(
                    issue_type="unknown_tool",
                    message=f"Unknown tool '{step.tool_name}' in repaired plan.",
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                )
            )
            continue

        declared_depends = normalize_tokens(step.depends_on)
        declared_produces = normalize_tokens(step.produces)
        for token in declared_depends:
            if token not in allowed_tokens:
                issues.append(
                    RepairValidationIssue(
                        issue_type="unknown_token",
                        message=f"Unknown depends_on token '{token}' in repaired plan.",
                        step_id=step.step_id,
                        tool_name=step.tool_name,
                        token=token,
                    )
                )
        for token in declared_produces:
            if token not in allowed_tokens:
                issues.append(
                    RepairValidationIssue(
                        issue_type="unknown_token",
                        message=f"Unknown produces token '{token}' in repaired plan.",
                        step_id=step.step_id,
                        tool_name=step.tool_name,
                        token=token,
                    )
                )

        inferred_requires = get_required_result_tokens(step.tool_name, step.argument_hints)
        canonical_provides = get_tool_provides(step.tool_name)
        if declared_depends and inferred_requires and declared_depends != inferred_requires:
            issues.append(
                RepairValidationIssue(
                    issue_type="depends_mismatch",
                    message=(
                        f"Step {step.step_id} declares depends_on {declared_depends}, "
                        f"but tool semantics require {inferred_requires}."
                    ),
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                )
            )
        if declared_produces and canonical_provides and declared_produces != canonical_provides:
            issues.append(
                RepairValidationIssue(
                    issue_type="produces_mismatch",
                    message=(
                        f"Step {step.step_id} declares produces {declared_produces}, "
                        f"but tool semantics provide {canonical_provides}."
                    ),
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                )
            )

    return issues


def _apply_no_repair(plan: ExecutionPlan, decision: PlanRepairDecision) -> ExecutionPlan:
    repaired_plan = clone_plan(plan)
    _append_unique(
        repaired_plan.repair_notes,
        decision.planner_notes or f"Repair decision kept the residual plan unchanged ({decision.action_type.value}).",
    )
    return repaired_plan


def _apply_drop_blocked_step(plan: ExecutionPlan, decision: PlanRepairDecision) -> ExecutionPlan:
    repaired_plan = clone_plan(plan)
    target_ids = (
        decision.patch.skip_step_ids
        or decision.affected_step_ids
        or decision.patch.affected_step_ids
        or ([decision.target_step_id] if decision.target_step_id else [])
    )
    for step_id in target_ids:
        step = repaired_plan.get_step(step_id=step_id)
        if step is None:
            continue
        step.status = PlanStepStatus.SKIPPED
        _note_step_repair(
            step,
            action_type=decision.action_type,
            note=decision.planner_notes or f"Skipped by bounded repair after {decision.trigger_type.value}.",
        )
    _append_unique(
        repaired_plan.repair_notes,
        decision.planner_notes or f"Dropped blocked residual step(s): {', '.join(target_ids)}.",
    )
    return repaired_plan


def _apply_reorder_remaining_steps(plan: ExecutionPlan, decision: PlanRepairDecision) -> ExecutionPlan:
    repaired_plan = clone_plan(plan)
    reordered_ids = decision.patch.reordered_step_ids
    mutable_steps = [step for step in repaired_plan.steps if _active_residual_step(step)]
    id_to_step = {step.step_id: step for step in mutable_steps}
    reordered_steps = [id_to_step[step_id] for step_id in reordered_ids]

    cursor = 0
    new_steps: List[PlanStep] = []
    for step in repaired_plan.steps:
        if _active_residual_step(step):
            candidate = reordered_steps[cursor]
            _note_step_repair(
                candidate,
                action_type=decision.action_type,
                note=decision.planner_notes or "Residual step order updated by bounded repair.",
            )
            new_steps.append(candidate)
            cursor += 1
        else:
            new_steps.append(step)
    repaired_plan.steps = new_steps
    _append_unique(
        repaired_plan.repair_notes,
        decision.planner_notes or "Reordered residual plan steps.",
    )
    return repaired_plan


def _apply_replace_step(plan: ExecutionPlan, decision: PlanRepairDecision) -> ExecutionPlan:
    repaired_plan = clone_plan(plan)
    target_id = decision.target_step_id or decision.patch.target_step_id
    target_step = repaired_plan.get_step(step_id=target_id)
    if target_step is None:
        return repaired_plan

    replacement = _clone_step(decision.patch.replacement_step) if decision.patch.replacement_step else None
    if replacement is None:
        return repaired_plan
    replacement.step_id = _allocate_repair_step_id(repaired_plan, replacement.step_id)
    replacement.depends_on = normalize_tokens(replacement.depends_on)
    replacement.produces = normalize_tokens(replacement.produces or get_tool_provides(replacement.tool_name))
    replacement.status = PlanStepStatus.PENDING
    _note_step_repair(
        replacement,
        action_type=decision.action_type,
        note=decision.planner_notes or f"Replacement for step {target_step.step_id}.",
        source_step_id=target_step.step_id,
    )

    target_step.status = PlanStepStatus.SKIPPED
    _note_step_repair(
        target_step,
        action_type=decision.action_type,
        note=decision.planner_notes or f"Replaced by {replacement.step_id}.",
        source_step_id=replacement.step_id,
    )

    index = repaired_plan.steps.index(target_step)
    repaired_plan.steps.insert(index + 1, replacement)
    _append_unique(
        repaired_plan.repair_notes,
        decision.planner_notes or f"Replaced residual step {target_step.step_id} with {replacement.step_id}.",
    )
    return repaired_plan


def _apply_truncate_after_current(plan: ExecutionPlan, decision: PlanRepairDecision) -> ExecutionPlan:
    repaired_plan = clone_plan(plan)
    anchor_id = decision.patch.truncate_after_step_id or decision.target_step_id
    if not anchor_id:
        return repaired_plan

    anchor = repaired_plan.get_step(step_id=anchor_id)
    if anchor is None:
        return repaired_plan

    start = repaired_plan.steps.index(anchor)
    affected: List[str] = []
    for step in repaired_plan.steps[start:]:
        if step.status == PlanStepStatus.COMPLETED:
            continue
        if step.status in {PlanStepStatus.SKIPPED, PlanStepStatus.FAILED}:
            continue
        step.status = PlanStepStatus.SKIPPED
        _note_step_repair(
            step,
            action_type=decision.action_type,
            note=decision.planner_notes or f"Truncated from step {anchor_id}.",
            source_step_id=anchor_id,
        )
        affected.append(step.step_id)

    _append_unique(
        repaired_plan.repair_notes,
        decision.planner_notes or f"Truncated residual workflow from {anchor_id}: {', '.join(affected)}.",
    )
    return repaired_plan


def _apply_append_recovery_step(plan: ExecutionPlan, decision: PlanRepairDecision) -> ExecutionPlan:
    repaired_plan = clone_plan(plan)
    appended_ids: List[str] = []
    for raw_step in decision.patch.append_steps:
        step = _clone_step(raw_step)
        step.step_id = _allocate_repair_step_id(repaired_plan, step.step_id)
        step.depends_on = normalize_tokens(step.depends_on)
        step.produces = normalize_tokens(step.produces or get_tool_provides(step.tool_name))
        step.status = PlanStepStatus.PENDING
        _note_step_repair(
            step,
            action_type=decision.action_type,
            note=decision.planner_notes or "Appended as a bounded recovery step.",
            source_step_id=decision.target_step_id,
        )
        repaired_plan.steps.append(step)
        appended_ids.append(step.step_id)

    _append_unique(
        repaired_plan.repair_notes,
        decision.planner_notes or f"Appended recovery step(s): {', '.join(appended_ids)}.",
    )
    return repaired_plan


def validate_plan_repair(
    current_plan: ExecutionPlan,
    repair_decision: PlanRepairDecision,
    *,
    available_tokens: Optional[Iterable[str]] = None,
    context_store: Optional["SessionContextStore"] = None,
) -> RepairValidationResult:
    action_type = repair_decision.action_type
    issues: List[RepairValidationIssue] = []
    validation_notes: List[str] = []

    if action_type not in set(RepairActionType):
        issues.append(
            RepairValidationIssue(
                issue_type="unknown_action",
                message=f"Unknown repair action '{action_type}'.",
            )
        )
        return _reject(action_type=RepairActionType.NO_REPAIR, issues=issues, notes=validation_notes)

    completed_ids = {
        step.step_id
        for step in current_plan.steps
        if step.status == PlanStepStatus.COMPLETED
    }

    touched_ids: set[str] = set()
    if action_type == RepairActionType.DROP_BLOCKED_STEP:
        touched_ids.update(repair_decision.patch.skip_step_ids)
        touched_ids.update(repair_decision.affected_step_ids)
        touched_ids.update(repair_decision.patch.affected_step_ids)
        for candidate_id in [repair_decision.target_step_id, repair_decision.patch.target_step_id]:
            if candidate_id:
                touched_ids.add(candidate_id)
    elif action_type == RepairActionType.REORDER_REMAINING_STEPS:
        touched_ids.update(repair_decision.patch.reordered_step_ids)
    elif action_type == RepairActionType.REPLACE_STEP:
        for candidate_id in [repair_decision.target_step_id, repair_decision.patch.target_step_id]:
            if candidate_id:
                touched_ids.add(candidate_id)
    elif action_type == RepairActionType.TRUNCATE_AFTER_CURRENT:
        touched_ids.update(repair_decision.affected_step_ids)
        touched_ids.update(repair_decision.patch.affected_step_ids)

    immutable_touches = sorted(touched_ids & completed_ids)
    if immutable_touches:
        for step_id in immutable_touches:
            issues.append(
                RepairValidationIssue(
                    issue_type="completed_step_mutation",
                    message=f"Repair cannot mutate completed step '{step_id}'.",
                    step_id=step_id,
                )
            )
        return _reject(action_type=action_type, issues=issues, notes=validation_notes)

    if repair_decision.action_type == RepairActionType.NO_REPAIR:
        repaired_plan = _apply_no_repair(current_plan, repair_decision)
    elif repair_decision.action_type == RepairActionType.KEEP_REMAINING:
        repaired_plan = _apply_no_repair(current_plan, repair_decision)
    elif repair_decision.action_type == RepairActionType.DROP_BLOCKED_STEP:
        step_ids = (
            repair_decision.patch.skip_step_ids
            or repair_decision.affected_step_ids
            or repair_decision.patch.affected_step_ids
            or ([repair_decision.target_step_id] if repair_decision.target_step_id else [])
        )
        if not step_ids:
            issues.append(
                RepairValidationIssue(
                    issue_type="missing_patch_data",
                    message="DROP_BLOCKED_STEP requires at least one target step id.",
                )
            )
            return _reject(action_type=action_type, issues=issues, notes=validation_notes)
        repaired_plan = _apply_drop_blocked_step(current_plan, repair_decision)
    elif repair_decision.action_type == RepairActionType.REORDER_REMAINING_STEPS:
        mutable_steps = [step for step in current_plan.steps if _active_residual_step(step)]
        mutable_ids = [step.step_id for step in mutable_steps]
        if sorted(repair_decision.patch.reordered_step_ids) != sorted(mutable_ids):
            issues.append(
                RepairValidationIssue(
                    issue_type="illegal_reorder",
                    message=(
                        "REORDER_REMAINING_STEPS must provide an exact permutation of the "
                        f"residual step ids: {mutable_ids}."
                    ),
                )
            )
            return _reject(action_type=action_type, issues=issues, notes=validation_notes)
        repaired_plan = _apply_reorder_remaining_steps(current_plan, repair_decision)
    elif repair_decision.action_type == RepairActionType.REPLACE_STEP:
        if repair_decision.patch.replacement_step is None:
            issues.append(
                RepairValidationIssue(
                    issue_type="missing_patch_data",
                    message="REPLACE_STEP requires patch.replacement_step.",
                )
            )
            return _reject(action_type=action_type, issues=issues, notes=validation_notes)
        repaired_plan = _apply_replace_step(current_plan, repair_decision)
    elif repair_decision.action_type == RepairActionType.TRUNCATE_AFTER_CURRENT:
        if not (repair_decision.patch.truncate_after_step_id or repair_decision.target_step_id):
            issues.append(
                RepairValidationIssue(
                    issue_type="missing_patch_data",
                    message="TRUNCATE_AFTER_CURRENT requires truncate_after_step_id or target_step_id.",
                )
            )
            return _reject(action_type=action_type, issues=issues, notes=validation_notes)
        repaired_plan = _apply_truncate_after_current(current_plan, repair_decision)
    elif repair_decision.action_type == RepairActionType.APPEND_RECOVERY_STEP:
        if not repair_decision.patch.append_steps:
            issues.append(
                RepairValidationIssue(
                    issue_type="missing_patch_data",
                    message="APPEND_RECOVERY_STEP requires patch.append_steps.",
                )
            )
            return _reject(action_type=action_type, issues=issues, notes=validation_notes)
        repaired_plan = _apply_append_recovery_step(current_plan, repair_decision)
    else:
        issues.append(
            RepairValidationIssue(
                issue_type="unknown_action",
                message=f"Unsupported repair action '{repair_decision.action_type.value}'.",
            )
        )
        return _reject(action_type=action_type, issues=issues, notes=validation_notes)

    issues.extend(_validate_step_semantics(repaired_plan))
    if issues:
        return _reject(action_type=action_type, issues=issues, notes=validation_notes)

    available = set(normalize_tokens(available_tokens))
    for step in repaired_plan.steps:
        if step.status == PlanStepStatus.COMPLETED:
            available.update(step.produces or get_tool_provides(step.tool_name))

    residual_steps: List[PlanStep] = []
    for step in repaired_plan.steps:
        if not _active_residual_step(step):
            continue
        clone = _clone_step(step)
        clone.status = PlanStepStatus.PENDING
        residual_steps.append(clone)

    if not residual_steps:
        repaired_plan.status = PlanStatus.VALID
        repaired_plan.validation_notes = ["Residual plan has no executable steps after repair."]
        next_step = repaired_plan.get_next_pending_step()
        return RepairValidationResult(
            action_type=repair_decision.action_type,
            is_valid=True,
            validation_notes=list(repaired_plan.validation_notes),
            issues=[],
            repaired_plan=repaired_plan,
            resulting_next_pending_step=next_step.to_dict() if next_step else None,
        )

    residual_validation = validate_plan_steps(residual_steps, available_tokens=available)
    if residual_validation["status"] != PlanStatus.VALID:
        validation_notes.extend(residual_validation["validation_notes"])
        for result in residual_validation["step_results"]:
            issues.append(
                RepairValidationIssue(
                    issue_type="illegal_residual_plan",
                    message="; ".join(result["validation_notes"]) or "Residual step is not executable.",
                    step_id=result.get("step_id"),
                    tool_name=result.get("tool_name"),
                )
            )
        return _reject(action_type=action_type, issues=issues, notes=validation_notes)

    residual_by_id = {item["step_id"]: item for item in residual_validation["step_results"]}
    for step in repaired_plan.steps:
        if step.step_id not in residual_by_id:
            continue
        result = residual_by_id[step.step_id]
        step.depends_on = list(result["required_tokens"])
        step.produces = list(result["produced_tokens"])
        step.status = result["status"]
        for note in result["validation_notes"]:
            _append_unique(step.validation_notes, note)
        step.blocked_reason = None

    repaired_plan.status = PlanStatus.VALID
    repaired_plan.validation_notes = list(residual_validation["validation_notes"])
    _append_unique(
        repaired_plan.repair_notes,
        repair_decision.planner_notes or f"Repair action {repair_decision.action_type.value} validated.",
    )
    next_step = repaired_plan.get_next_pending_step()

    return RepairValidationResult(
        action_type=repair_decision.action_type,
        is_valid=True,
        validation_notes=list(residual_validation["validation_notes"]),
        issues=[],
        repaired_plan=repaired_plan,
        resulting_next_pending_step=next_step.to_dict() if next_step else None,
    )


def summarize_repair_action(decision: PlanRepairDecision) -> str:
    summary = decision.action_type.value
    if decision.target_step_id:
        summary += f" on {decision.target_step_id}"
    if decision.affected_step_ids:
        summary += f" affecting {', '.join(decision.affected_step_ids)}"
    return summary
