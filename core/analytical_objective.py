from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class AOStatus(Enum):
    CREATED = "created"
    ACTIVE = "active"
    REVISING = "revising"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"


class AORelationship(Enum):
    INDEPENDENT = "independent"
    REVISION = "revision"
    REFERENCE = "reference"


class IntentConfidence(Enum):
    HIGH = "high"
    LOW = "low"
    NONE = "none"


@dataclass
class ToolIntent:
    resolved_tool: Optional[str] = None
    confidence: IntentConfidence = IntentConfidence.NONE
    evidence: List[str] = field(default_factory=list)
    resolved_at_turn: Optional[int] = None
    resolved_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resolved_tool": self.resolved_tool,
            "confidence": self.confidence.value,
            "evidence": list(self.evidence),
            "resolved_at_turn": self.resolved_at_turn,
            "resolved_by": self.resolved_by,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ToolIntent":
        payload = data if isinstance(data, dict) else {}
        confidence_raw = str(payload.get("confidence") or IntentConfidence.NONE.value)
        try:
            confidence = IntentConfidence(confidence_raw)
        except ValueError:
            confidence = IntentConfidence.NONE
        return cls(
            resolved_tool=(
                str(payload.get("resolved_tool")).strip()
                if payload.get("resolved_tool") is not None
                else None
            ),
            confidence=confidence,
            evidence=[str(item) for item in list(payload.get("evidence") or []) if str(item).strip()],
            resolved_at_turn=(
                int(payload["resolved_at_turn"])
                if payload.get("resolved_at_turn") is not None
                else None
            ),
            resolved_by=(
                str(payload.get("resolved_by")).strip()
                if payload.get("resolved_by") is not None
                else None
            ),
        )


@dataclass
class ParameterState:
    required_filled: Set[str] = field(default_factory=set)
    optional_filled: Set[str] = field(default_factory=set)
    awaiting_slot: Optional[str] = None
    collection_mode: bool = False
    collection_mode_reason: Optional[str] = None
    probe_turn_count: int = 0
    probe_abandoned: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "required_filled": sorted(str(item) for item in self.required_filled),
            "optional_filled": sorted(str(item) for item in self.optional_filled),
            "awaiting_slot": self.awaiting_slot,
            "collection_mode": self.collection_mode,
            "collection_mode_reason": self.collection_mode_reason,
            "probe_turn_count": int(self.probe_turn_count or 0),
            "probe_abandoned": bool(self.probe_abandoned),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ParameterState":
        payload = data if isinstance(data, dict) else {}
        return cls(
            required_filled={
                str(item)
                for item in list(payload.get("required_filled") or [])
                if str(item).strip()
            },
            optional_filled={
                str(item)
                for item in list(payload.get("optional_filled") or [])
                if str(item).strip()
            },
            awaiting_slot=(
                str(payload.get("awaiting_slot")).strip()
                if payload.get("awaiting_slot") is not None
                else None
            ),
            collection_mode=bool(payload.get("collection_mode", False)),
            collection_mode_reason=(
                str(payload.get("collection_mode_reason")).strip()
                if payload.get("collection_mode_reason") is not None
                else None
            ),
            probe_turn_count=int(payload.get("probe_turn_count") or 0),
            probe_abandoned=bool(payload.get("probe_abandoned", False)),
        )


@dataclass
class ToolCallRecord:
    """Compact tool-call record scoped to one analytical objective."""

    turn: int
    tool: str
    args_compact: Dict[str, Any]
    success: bool
    result_ref: Optional[str]
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn": self.turn,
            "tool": self.tool,
            "args_compact": dict(self.args_compact),
            "success": self.success,
            "result_ref": self.result_ref,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ToolCallRecord":
        payload = data if isinstance(data, dict) else {}
        return cls(
            turn=int(payload.get("turn") or 0),
            tool=str(payload.get("tool") or "unknown"),
            args_compact=dict(payload.get("args_compact") or {}),
            success=bool(payload.get("success", False)),
            result_ref=(
                str(payload.get("result_ref")).strip()
                if payload.get("result_ref") is not None
                else None
            ),
            summary=str(payload.get("summary") or ""),
        )


@dataclass
class AnalyticalObjective:
    """One user analytical intent tracked as a cognitive unit within a session."""

    ao_id: str
    session_id: str
    objective_text: str
    status: AOStatus
    start_turn: int
    end_turn: Optional[int] = None
    relationship: AORelationship = AORelationship.INDEPENDENT
    parent_ao_id: Optional[str] = None
    tool_call_log: List[ToolCallRecord] = field(default_factory=list)
    artifacts_produced: Dict[str, str] = field(default_factory=dict)
    parameters_used: Dict[str, Any] = field(default_factory=dict)
    failure_reason: Optional[str] = None
    constraint_violations: List[Dict[str, Any]] = field(default_factory=list)
    tool_intent: ToolIntent = field(default_factory=ToolIntent)
    parameter_state: ParameterState = field(default_factory=ParameterState)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def has_produced_expected_artifacts(self) -> bool:
        return any(record.success for record in self.tool_call_log)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ao_id": self.ao_id,
            "session_id": self.session_id,
            "objective_text": self.objective_text,
            "status": self.status.value,
            "start_turn": self.start_turn,
            "end_turn": self.end_turn,
            "relationship": self.relationship.value,
            "parent_ao_id": self.parent_ao_id,
            "tool_call_log": [record.to_dict() for record in self.tool_call_log],
            "artifacts_produced": dict(self.artifacts_produced),
            "parameters_used": dict(self.parameters_used),
            "failure_reason": self.failure_reason,
            "constraint_violations": [dict(item) for item in self.constraint_violations],
            "tool_intent": self.tool_intent.to_dict(),
            "parameter_state": self.parameter_state.to_dict(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "AnalyticalObjective":
        payload = data if isinstance(data, dict) else {}
        status_raw = str(payload.get("status") or AOStatus.CREATED.value)
        relationship_raw = str(payload.get("relationship") or AORelationship.INDEPENDENT.value)
        try:
            status = AOStatus(status_raw)
        except ValueError:
            status = AOStatus.CREATED
        try:
            relationship = AORelationship(relationship_raw)
        except ValueError:
            relationship = AORelationship.INDEPENDENT
        metadata = dict(payload.get("metadata") or {})
        tool_intent = ToolIntent.from_dict(payload.get("tool_intent"))
        parameter_state = ParameterState.from_dict(payload.get("parameter_state"))
        cls._migrate_deprecated_metadata(metadata, tool_intent, parameter_state)
        return cls(
            ao_id=str(payload.get("ao_id") or "AO#legacy"),
            session_id=str(payload.get("session_id") or ""),
            objective_text=str(payload.get("objective_text") or ""),
            status=status,
            start_turn=int(payload.get("start_turn") or 0),
            end_turn=int(payload["end_turn"]) if payload.get("end_turn") is not None else None,
            relationship=relationship,
            parent_ao_id=(
                str(payload.get("parent_ao_id")).strip()
                if payload.get("parent_ao_id") is not None
                else None
            ),
            tool_call_log=[
                ToolCallRecord.from_dict(item)
                for item in payload.get("tool_call_log") or []
                if isinstance(item, dict)
            ],
            artifacts_produced=dict(payload.get("artifacts_produced") or {}),
            parameters_used=dict(payload.get("parameters_used") or {}),
            failure_reason=(
                str(payload.get("failure_reason")).strip()
                if payload.get("failure_reason") is not None
                else None
            ),
            constraint_violations=[
                dict(item)
                for item in payload.get("constraint_violations") or []
                if isinstance(item, dict)
            ],
            tool_intent=tool_intent,
            parameter_state=parameter_state,
            metadata=metadata,
        )

    @staticmethod
    def _migrate_deprecated_metadata(
        metadata: Dict[str, Any],
        tool_intent: ToolIntent,
        parameter_state: ParameterState,
    ) -> None:
        contract_state = metadata.get("clarification_contract")
        if not isinstance(contract_state, dict):
            contract_state = {}
        pending_tool = str(contract_state.get("tool_name") or "").strip()
        if pending_tool and not tool_intent.resolved_tool:
            tool_intent.resolved_tool = pending_tool
            tool_intent.confidence = IntentConfidence.HIGH
            tool_intent.resolved_by = "migration:metadata"
            tool_intent.evidence.append("metadata.clarification_contract.tool_name")

        if not parameter_state.collection_mode:
            parameter_state.collection_mode = bool(metadata.get("collection_mode", False))
        if parameter_state.collection_mode and parameter_state.collection_mode_reason is None:
            reason = str(
                metadata.get("pcm_trigger_reason")
                or contract_state.get("pcm_trigger_reason")
                or ""
            ).strip()
            parameter_state.collection_mode_reason = reason or None

        if parameter_state.awaiting_slot is None:
            awaiting_slot = str(contract_state.get("probe_optional_slot") or "").strip()
            if not awaiting_slot:
                missing_slots = list(contract_state.get("missing_slots") or [])
                awaiting_slot = str(missing_slots[0]).strip() if missing_slots else ""
            parameter_state.awaiting_slot = awaiting_slot or None

        if not parameter_state.probe_turn_count:
            parameter_state.probe_turn_count = int(contract_state.get("probe_turn_count") or 0)
        if not parameter_state.probe_abandoned:
            parameter_state.probe_abandoned = bool(contract_state.get("probe_abandoned", False))
