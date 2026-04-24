"""Governance-layer persistence for cross-constraint violations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.ao_manager import AOManager
from core.context_store import SessionContextStore
from services.cross_constraints import CrossConstraintViolation


VALID_SEVERITIES = {"reject", "negotiate", "warn"}


@dataclass
class ViolationRecord:
    """Persistent schema for one user-facing constraint violation event."""

    violation_type: str
    severity: str
    involved_params: Dict[str, Any]
    suggested_resolution: str
    timestamp: str
    source_turn: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "violation_type": self.violation_type,
            "severity": self.severity,
            "involved_params": dict(self.involved_params),
            "suggested_resolution": self.suggested_resolution,
            "timestamp": self.timestamp,
            "source_turn": int(self.source_turn or 0),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ViolationRecord":
        payload = data if isinstance(data, dict) else {}
        return cls(
            violation_type=str(payload.get("violation_type") or "unknown_constraint"),
            severity=_normalize_severity(str(payload.get("severity") or "warn")),
            involved_params=dict(payload.get("involved_params") or {}),
            suggested_resolution=str(payload.get("suggested_resolution") or ""),
            timestamp=str(payload.get("timestamp") or datetime.now().isoformat()),
            source_turn=int(payload.get("source_turn") or 0),
        )


def normalize_cross_constraint_violation(
    violation: CrossConstraintViolation,
    *,
    severity: str,
    source_turn: int,
    timestamp: Optional[str] = None,
) -> ViolationRecord:
    """Convert a cross-constraint event into the persistent B-schema record."""

    payload = _violation_payload(violation)
    suggestions = payload.get("suggestions")
    if isinstance(suggestions, list):
        suggested_resolution = "; ".join(str(item) for item in suggestions if str(item).strip())
    else:
        suggested_resolution = ""
    if not suggested_resolution:
        suggested_resolution = str(payload.get("reason") or "")

    return ViolationRecord(
        violation_type=str(
            payload.get("constraint_name")
            or payload.get("violation_type")
            or "unknown_constraint"
        ),
        severity=_normalize_severity(severity),
        involved_params=_extract_involved_params(payload),
        suggested_resolution=suggested_resolution,
        timestamp=str(timestamp or datetime.now().isoformat()),
        source_turn=int(source_turn or 0),
    )


class ConstraintViolationWriter:
    """Single governance-layer writer for persisted constraint violations."""

    def __init__(self, ao_manager: AOManager, context_store: SessionContextStore):
        self.ao_manager = ao_manager
        self.context_store = context_store

    def record(self, violation: ViolationRecord) -> None:
        """Append to current AO and replace the context-store latest list."""

        record = violation.to_dict()
        current_ao = self.ao_manager.get_current_ao() if self.ao_manager is not None else None
        if current_ao is not None:
            current_violations = getattr(current_ao, "constraint_violations", None)
            if not isinstance(current_violations, list):
                current_violations = []
                current_ao.constraint_violations = current_violations
            current_violations.append(record)
            latest = [dict(item) for item in current_violations if isinstance(item, dict)]
        else:
            latest = [record]

        self.context_store.set_latest_constraint_violations(latest)

    def get_latest(self) -> List[ViolationRecord]:
        """Return persisted violations for the current AO only."""

        current_ao = self.ao_manager.get_current_ao() if self.ao_manager is not None else None
        if current_ao is None:
            return []
        return [
            ViolationRecord.from_dict(item)
            for item in list(getattr(current_ao, "constraint_violations", []) or [])
            if isinstance(item, dict)
        ]


def _normalize_severity(severity: str) -> str:
    value = str(severity or "").strip().lower()
    if value not in VALID_SEVERITIES:
        raise ValueError(f"Unsupported constraint violation severity: {severity}")
    return value


def _violation_payload(violation: Any) -> Dict[str, Any]:
    if isinstance(violation, dict):
        nested = violation.get("constraint_violation")
        if isinstance(nested, dict):
            merged = dict(nested)
            for key, value in violation.items():
                merged.setdefault(key, value)
            return merged
        return dict(violation)
    if hasattr(violation, "to_dict"):
        payload = violation.to_dict()
        if isinstance(payload, dict):
            return payload
    return {
        "constraint_name": getattr(violation, "constraint_name", None),
        "param_a_name": getattr(violation, "param_a_name", None),
        "param_a_value": getattr(violation, "param_a_value", None),
        "param_b_name": getattr(violation, "param_b_name", None),
        "param_b_value": getattr(violation, "param_b_value", None),
        "violation_type": getattr(violation, "violation_type", None),
        "reason": getattr(violation, "reason", None),
        "suggestions": list(getattr(violation, "suggestions", []) or []),
    }


def _extract_involved_params(payload: Dict[str, Any]) -> Dict[str, Any]:
    param_a_name = payload.get("param_a_name")
    param_b_name = payload.get("param_b_name")
    involved: Dict[str, Any] = {}
    if param_a_name:
        involved[str(param_a_name)] = payload.get("param_a_value")
    if param_b_name:
        involved[str(param_b_name)] = payload.get("param_b_value")
    if involved:
        return involved

    parsed_a = _parse_param_pair(payload.get("param_a"))
    parsed_b = _parse_param_pair(payload.get("param_b"))
    involved.update(parsed_a)
    involved.update(parsed_b)
    if involved:
        return involved

    param_names = str(payload.get("param") or "").split("+")
    values = str(payload.get("original") or "").split("|")
    for index, name in enumerate(param_names):
        key = name.strip()
        if not key:
            continue
        value = values[index].strip() if index < len(values) else ""
        involved[key] = value
    return involved


def _parse_param_pair(value: Any) -> Dict[str, Any]:
    text = str(value or "").strip()
    if not text or "=" not in text:
        return {}
    name, raw_value = text.split("=", 1)
    key = name.strip()
    if not key:
        return {}
    return {key: raw_value.strip()}
