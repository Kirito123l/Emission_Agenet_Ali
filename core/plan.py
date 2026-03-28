from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class PlanStatus(str, Enum):
    DRAFT = "draft"
    VALID = "valid"
    PARTIAL = "partial"
    INVALID = "invalid"


class PlanStepStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


def _coerce_string_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    result: List[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            result.append(text)
    return result


def _coerce_status(value: Any, enum_cls: type[Enum], default: Enum) -> Enum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except Exception:
        return default


@dataclass
class PlanStep:
    step_id: str
    tool_name: str
    purpose: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    produces: List[str] = field(default_factory=list)
    argument_hints: Dict[str, Any] = field(default_factory=dict)
    status: PlanStepStatus = PlanStepStatus.PENDING
    validation_notes: List[str] = field(default_factory=list)
    reconciliation_notes: List[str] = field(default_factory=list)
    blocked_reason: Optional[str] = None
    repair_action: Optional[str] = None
    repair_source_step_id: Optional[str] = None
    repair_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "purpose": self.purpose,
            "depends_on": list(self.depends_on),
            "produces": list(self.produces),
            "argument_hints": dict(self.argument_hints),
            "status": self.status.value,
            "validation_notes": list(self.validation_notes),
            "reconciliation_notes": list(self.reconciliation_notes),
            "blocked_reason": self.blocked_reason,
            "repair_action": self.repair_action,
            "repair_source_step_id": self.repair_source_step_id,
            "repair_notes": list(self.repair_notes),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "PlanStep":
        payload = data if isinstance(data, dict) else {}
        return cls(
            step_id=str(payload.get("step_id") or "").strip() or "step",
            tool_name=str(payload.get("tool_name") or "").strip(),
            purpose=str(payload.get("purpose")).strip() if payload.get("purpose") is not None else None,
            depends_on=_coerce_string_list(payload.get("depends_on")),
            produces=_coerce_string_list(payload.get("produces")),
            argument_hints=dict(payload.get("argument_hints") or {}),
            status=_coerce_status(payload.get("status"), PlanStepStatus, PlanStepStatus.PENDING),
            validation_notes=_coerce_string_list(payload.get("validation_notes")),
            reconciliation_notes=_coerce_string_list(payload.get("reconciliation_notes")),
            blocked_reason=str(payload.get("blocked_reason")).strip() if payload.get("blocked_reason") is not None else None,
            repair_action=str(payload.get("repair_action")).strip() if payload.get("repair_action") is not None else None,
            repair_source_step_id=str(payload.get("repair_source_step_id")).strip()
            if payload.get("repair_source_step_id") is not None
            else None,
            repair_notes=_coerce_string_list(payload.get("repair_notes")),
        )


@dataclass
class ExecutionPlan:
    goal: str
    steps: List[PlanStep] = field(default_factory=list)
    mode: str = "tool_workflow"
    planner_notes: Optional[str] = None
    status: PlanStatus = PlanStatus.DRAFT
    validation_notes: List[str] = field(default_factory=list)
    reconciliation_notes: List[str] = field(default_factory=list)
    repair_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        next_step = self.get_next_pending_step()
        return {
            "goal": self.goal,
            "mode": self.mode,
            "planner_notes": self.planner_notes,
            "status": self.status.value,
            "validation_notes": list(self.validation_notes),
            "reconciliation_notes": list(self.reconciliation_notes),
            "repair_notes": list(self.repair_notes),
            "next_pending_step": next_step.to_dict() if next_step else None,
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ExecutionPlan":
        payload = data if isinstance(data, dict) else {}
        steps = [
            PlanStep.from_dict(item)
            for item in payload.get("steps", [])
            if isinstance(item, dict)
        ]
        return cls(
            goal=str(payload.get("goal") or "").strip(),
            steps=steps,
            mode=str(payload.get("mode") or "tool_workflow").strip() or "tool_workflow",
            planner_notes=str(payload.get("planner_notes")).strip() if payload.get("planner_notes") is not None else None,
            status=_coerce_status(payload.get("status"), PlanStatus, PlanStatus.DRAFT),
            validation_notes=_coerce_string_list(payload.get("validation_notes")),
            reconciliation_notes=_coerce_string_list(payload.get("reconciliation_notes")),
            repair_notes=_coerce_string_list(payload.get("repair_notes")),
        )

    def get_next_pending_step(self) -> Optional[PlanStep]:
        for step in self.steps:
            if step.status not in {
                PlanStepStatus.COMPLETED,
                PlanStepStatus.FAILED,
                PlanStepStatus.SKIPPED,
            }:
                return step
        return None

    def get_pending_steps(self) -> List[PlanStep]:
        return [
            step
            for step in self.steps
            if step.status not in {
                PlanStepStatus.COMPLETED,
                PlanStepStatus.FAILED,
                PlanStepStatus.SKIPPED,
            }
        ]

    def has_pending_steps(self) -> bool:
        return self.get_next_pending_step() is not None

    def get_next_step(self) -> Optional[PlanStep]:
        return self.get_next_pending_step()

    def get_step(
        self,
        *,
        step_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        allowed_statuses: Optional[set[PlanStepStatus]] = None,
    ) -> Optional[PlanStep]:
        for step in self.steps:
            if step_id and step.step_id != step_id:
                continue
            if tool_name and step.tool_name != tool_name:
                continue
            if allowed_statuses is not None and step.status not in allowed_statuses:
                continue
            if not step_id and not tool_name:
                continue
            return step
        return None

    def mark_step_status(
        self,
        *,
        step_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        status: PlanStepStatus,
        note: Optional[str] = None,
        reconciliation_note: Optional[str] = None,
        blocked_reason: Optional[str] = None,
    ) -> Optional[PlanStep]:
        step = self.get_step(step_id=step_id, tool_name=tool_name)
        if step is None:
            return None
        step.status = status
        if note and note not in step.validation_notes:
            step.validation_notes.append(note)
        if reconciliation_note and reconciliation_note not in step.reconciliation_notes:
            step.reconciliation_notes.append(reconciliation_note)
        if blocked_reason is not None:
            text = str(blocked_reason).strip()
            step.blocked_reason = text or None
        return step

    def append_validation_note(self, note: Optional[str]) -> None:
        if note:
            text = str(note).strip()
            if text and text not in self.validation_notes:
                self.validation_notes.append(text)

    def append_reconciliation_note(self, note: Optional[str]) -> None:
        if note:
            text = str(note).strip()
            if text and text not in self.reconciliation_notes:
                self.reconciliation_notes.append(text)

    def append_repair_note(self, note: Optional[str]) -> None:
        if note:
            text = str(note).strip()
            if text and text not in self.repair_notes:
                self.repair_notes.append(text)
