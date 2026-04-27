"""Strict schema for LLM reply generation context."""

from __future__ import annotations

from dataclasses import MISSING, dataclass, field, fields
from typing import Any, Dict, List, Optional, Type, TypeVar

from core.constraint_violation_writer import ViolationRecord


T = TypeVar("T")


@dataclass
class ToolExecutionSummary:
    tool_name: str
    arguments: Dict[str, Any]
    success: bool
    summary: str
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "arguments": dict(self.arguments),
            "success": bool(self.success),
            "summary": self.summary,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolExecutionSummary":
        payload = _strict_payload(cls, data)
        return cls(
            tool_name=str(payload["tool_name"]),
            arguments=dict(payload["arguments"] or {}),
            success=bool(payload["success"]),
            summary=str(payload["summary"] or ""),
            error=(str(payload["error"]) if payload.get("error") is not None else None),
        )


@dataclass
class ClarificationRequest:
    target_field: str
    reason: str
    options: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_field": self.target_field,
            "reason": self.reason,
            "options": list(self.options),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClarificationRequest":
        payload = _strict_payload(cls, data)
        return cls(
            target_field=str(payload["target_field"]),
            reason=str(payload["reason"] or ""),
            options=[str(item) for item in list(payload.get("options") or [])],
        )


@dataclass
class AOStatusSummary:
    state: str
    objective: str
    completed_steps: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "objective": self.objective,
            "completed_steps": list(self.completed_steps),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AOStatusSummary":
        payload = _strict_payload(cls, data)
        return cls(
            state=str(payload["state"]),
            objective=str(payload["objective"] or ""),
            completed_steps=[str(item) for item in list(payload.get("completed_steps") or [])],
        )


@dataclass
class ReplyContext:
    user_message: str
    router_text: str
    tool_executions: List[ToolExecutionSummary] = field(default_factory=list)
    violations: List[ViolationRecord] = field(default_factory=list)
    pending_clarifications: List[ClarificationRequest] = field(default_factory=list)
    ao_status: Optional[AOStatusSummary] = None
    trace_highlights: List[Dict[str, Any]] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_message": self.user_message,
            "router_text": self.router_text,
            "tool_executions": [item.to_dict() for item in self.tool_executions],
            "violations": [item.to_dict() for item in self.violations],
            "pending_clarifications": [
                item.to_dict() for item in self.pending_clarifications
            ],
            "ao_status": self.ao_status.to_dict() if self.ao_status else None,
            "trace_highlights": [dict(item) for item in self.trace_highlights],
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReplyContext":
        payload = _strict_payload(cls, data)
        return cls(
            user_message=str(payload["user_message"]),
            router_text=str(payload["router_text"] or ""),
            tool_executions=[
                ToolExecutionSummary.from_dict(item)
                for item in list(payload.get("tool_executions") or [])
            ],
            violations=[
                ViolationRecord.from_dict(item)
                for item in list(payload.get("violations") or [])
                if isinstance(item, dict)
            ],
            pending_clarifications=[
                ClarificationRequest.from_dict(item)
                for item in list(payload.get("pending_clarifications") or [])
            ],
            ao_status=(
                AOStatusSummary.from_dict(payload["ao_status"])
                if isinstance(payload.get("ao_status"), dict)
                else None
            ),
            trace_highlights=[
                dict(item)
                for item in list(payload.get("trace_highlights") or [])
                if isinstance(item, dict)
            ],
            extra=dict(payload.get("extra") or {}),
        )


def _strict_payload(cls: Type[T], data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError(f"{cls.__name__}.from_dict expected dict, got {type(data).__name__}")

    dataclass_fields = fields(cls)
    known = {item.name for item in dataclass_fields}
    unknown = set(data.keys()) - known
    if unknown:
        raise ValueError(
            f"{cls.__name__}.from_dict received unknown fields: {sorted(unknown)}. "
            "For schema evolution use the 'extra' dict; "
            "for core changes update the dataclass."
        )

    payload = dict(data)
    missing = [
        item.name
        for item in dataclass_fields
        if item.name not in payload
        and item.default is MISSING
        and item.default_factory is MISSING
    ]
    if missing:
        raise ValueError(f"{cls.__name__}.from_dict missing required fields: {sorted(missing)}")
    return payload
