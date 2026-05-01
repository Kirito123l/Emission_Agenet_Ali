from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from core.execution_continuation import ExecutionContinuation


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


class ConversationalStance(Enum):
    DIRECTIVE = "directive"
    DELIBERATIVE = "deliberative"
    EXPLORATORY = "exploratory"
    UNKNOWN = "unknown"


class StanceConfidence(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IncompatibleSessionError(ValueError):
    """Raised when persisted AO state predates the Phase 2R stance schema."""


class IdempotencyDecision(Enum):
    NO_DUPLICATE = "no_duplicate"
    EXACT_DUPLICATE = "exact_duplicate"
    REVISION_DETECTED = "revision_detected"
    EXPLICIT_RERUN = "explicit_rerun"


@dataclass
class IdempotencyResult:
    decision: IdempotencyDecision
    matched_ao_id: Optional[str] = None
    matched_tool: Optional[str] = None
    matched_turn: Optional[int] = None
    matched_result_ref: Optional[str] = None
    proposed_fingerprint: Optional[Dict[str, Any]] = None
    previous_fingerprint: Optional[Dict[str, Any]] = None
    decision_reason: str = ""
    explicit_rerun_absent: bool = True


# ── Phase 6.E: canonical multi-turn execution state ─────────────────────


class ExecutionStepStatus(Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    INVALIDATED = "invalidated"


@dataclass
class ExecutionStep:
    """One step in the canonical execution chain."""
    tool_name: str
    status: ExecutionStepStatus = ExecutionStepStatus.PENDING
    effective_args: Dict[str, Any] = field(default_factory=dict)
    result_ref: Optional[str] = None
    error_summary: Optional[str] = None
    source: str = ""                       # "projected_chain" | "tool_call" | "idempotent_skip" | "manual"
    created_turn: Optional[int] = None
    updated_turn: Optional[int] = None
    revision_epoch: int = 0
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "status": self.status.value,
            "effective_args": dict(self.effective_args),
            "result_ref": self.result_ref,
            "error_summary": self.error_summary,
            "source": self.source,
            "created_turn": self.created_turn,
            "updated_turn": self.updated_turn,
            "revision_epoch": self.revision_epoch,
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ExecutionStep":
        payload = data if isinstance(data, dict) else {}
        status_raw = str(payload.get("status") or ExecutionStepStatus.PENDING.value)
        try:
            status = ExecutionStepStatus(status_raw)
        except ValueError:
            status = ExecutionStepStatus.PENDING
        return cls(
            tool_name=str(payload.get("tool_name") or ""),
            status=status,
            effective_args=dict(payload.get("effective_args") or {}),
            result_ref=(
                str(payload.get("result_ref")).strip()
                if payload.get("result_ref") is not None else None
            ),
            error_summary=(
                str(payload.get("error_summary")).strip()
                if payload.get("error_summary") is not None else None
            ),
            source=str(payload.get("source") or ""),
            created_turn=(
                int(payload["created_turn"]) if payload.get("created_turn") is not None else None
            ),
            updated_turn=(
                int(payload["updated_turn"]) if payload.get("updated_turn") is not None else None
            ),
            revision_epoch=int(payload.get("revision_epoch") or 0),
            provenance=dict(payload.get("provenance") or {}),
        )


@dataclass
class AOExecutionState:
    """Canonical multi-turn execution state for one AnalyticalObjective."""
    objective_id: str = ""
    planned_chain: List[str] = field(default_factory=list)
    chain_cursor: int = 0
    steps: List[ExecutionStep] = field(default_factory=list)
    revision_epoch: int = 0
    chain_status: str = ""                 # "active" | "complete" | "failed" | "abandoned"
    last_updated_turn: Optional[int] = None
    provenance: Dict[str, Any] = field(default_factory=dict)

    @property
    def pending_steps(self) -> List[ExecutionStep]:
        return [s for s in self.steps if s.status == ExecutionStepStatus.PENDING]

    @property
    def completed_steps(self) -> List[ExecutionStep]:
        return [s for s in self.steps if s.status == ExecutionStepStatus.COMPLETED]

    @property
    def skipped_steps(self) -> List[ExecutionStep]:
        return [s for s in self.steps if s.status == ExecutionStepStatus.SKIPPED]

    @property
    def failed_steps(self) -> List[ExecutionStep]:
        return [s for s in self.steps if s.status == ExecutionStepStatus.FAILED]

    @property
    def pending_next_tool(self) -> Optional[str]:
        pending = self.pending_steps
        return pending[0].tool_name if pending else None

    @property
    def current_tool(self) -> Optional[str]:
        if 0 <= self.chain_cursor < len(self.planned_chain):
            return self.planned_chain[self.chain_cursor]
        return None

    @property
    def is_chain_complete(self) -> bool:
        if not self.steps:
            return False
        return all(s.status in (ExecutionStepStatus.COMPLETED, ExecutionStepStatus.SKIPPED)
                   for s in self.steps)

    def active_tool_matches(self, tool_name: str) -> bool:
        return self.current_tool == tool_name

    def to_dict(self) -> Dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "planned_chain": [str(item) for item in self.planned_chain if str(item).strip()],
            "chain_cursor": self.chain_cursor,
            "steps": [step.to_dict() for step in self.steps],
            "revision_epoch": self.revision_epoch,
            "chain_status": self.chain_status,
            "last_updated_turn": self.last_updated_turn,
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "AOExecutionState":
        payload = data if isinstance(data, dict) else {}
        return cls(
            objective_id=str(payload.get("objective_id") or ""),
            planned_chain=[
                str(item) for item in list(payload.get("planned_chain") or [])
                if str(item).strip()
            ],
            chain_cursor=int(payload.get("chain_cursor") or 0),
            steps=[
                ExecutionStep.from_dict(item)
                for item in list(payload.get("steps") or [])
                if isinstance(item, dict)
            ],
            revision_epoch=int(payload.get("revision_epoch") or 0),
            chain_status=str(payload.get("chain_status") or ""),
            last_updated_turn=(
                int(payload["last_updated_turn"])
                if payload.get("last_updated_turn") is not None else None
            ),
            provenance=dict(payload.get("provenance") or {}),
        )


@dataclass
class ToolIntent:
    resolved_tool: Optional[str] = None
    confidence: IntentConfidence = IntentConfidence.NONE
    evidence: List[str] = field(default_factory=list)
    resolved_at_turn: Optional[int] = None
    resolved_by: Optional[str] = None
    projected_chain: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resolved_tool": self.resolved_tool,
            "confidence": self.confidence.value,
            "evidence": list(self.evidence),
            "resolved_at_turn": self.resolved_at_turn,
            "resolved_by": self.resolved_by,
            "projected_chain": [
                str(item) for item in self.projected_chain if str(item).strip()
            ],
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
            projected_chain=[
                str(item)
                for item in list(payload.get("projected_chain") or [])
                if str(item).strip()
            ],
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
        payload = {
            "required_filled": sorted(str(item) for item in self.required_filled),
            "optional_filled": sorted(str(item) for item in self.optional_filled),
        }
        if not _contract_split_enabled():
            payload.update(
                {
                    "awaiting_slot": self.awaiting_slot,
                    "collection_mode": self.collection_mode,
                    "collection_mode_reason": self.collection_mode_reason,
                    "probe_turn_count": int(self.probe_turn_count or 0),
                    "probe_abandoned": bool(self.probe_abandoned),
                }
            )
        return payload

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
    stance: ConversationalStance = ConversationalStance.UNKNOWN
    stance_confidence: StanceConfidence = StanceConfidence.LOW
    stance_resolved_by: Optional[str] = None
    stance_history: List[Tuple[int, ConversationalStance]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def has_produced_expected_artifacts(self) -> bool:
        return any(record.success for record in self.tool_call_log)

    def to_dict(self) -> Dict[str, Any]:
        metadata = dict(self.metadata)
        if _contract_split_enabled():
            metadata.pop("collection_mode", None)
            metadata.pop("pcm_trigger_reason", None)
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
            "stance": self.stance.value,
            "stance_confidence": self.stance_confidence.value,
            "stance_resolved_by": self.stance_resolved_by,
            "stance_history": [
                {"turn": int(turn or 0), "stance": stance.value}
                for turn, stance in self.stance_history
            ],
            "metadata": metadata,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "AnalyticalObjective":
        payload = data if isinstance(data, dict) else {}
        if "stance" not in payload:
            ao_id = str(payload.get("ao_id") or "unknown")
            raise IncompatibleSessionError(
                "AnalyticalObjective payload is missing Phase 2R stance fields "
                f"for {ao_id}. Run scripts/migrate_phase_2_4_to_2r.py on the "
                "session file before loading it with Phase 2R."
            )
        status_raw = str(payload.get("status") or AOStatus.CREATED.value)
        relationship_raw = str(payload.get("relationship") or AORelationship.INDEPENDENT.value)
        stance_raw = str(payload.get("stance") or ConversationalStance.UNKNOWN.value)
        stance_confidence_raw = str(payload.get("stance_confidence") or StanceConfidence.LOW.value)
        try:
            status = AOStatus(status_raw)
        except ValueError:
            status = AOStatus.CREATED
        try:
            relationship = AORelationship(relationship_raw)
        except ValueError:
            relationship = AORelationship.INDEPENDENT
        try:
            stance = ConversationalStance(stance_raw)
        except ValueError:
            stance = ConversationalStance.UNKNOWN
        try:
            stance_confidence = StanceConfidence(stance_confidence_raw)
        except ValueError:
            stance_confidence = StanceConfidence.LOW
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
            stance=stance,
            stance_confidence=stance_confidence,
            stance_resolved_by=(
                str(payload.get("stance_resolved_by")).strip()
                if payload.get("stance_resolved_by") is not None
                else None
            ),
            stance_history=cls._parse_stance_history(payload.get("stance_history")),
            metadata=metadata,
        )

    @staticmethod
    def _parse_stance_history(value: Any) -> List[Tuple[int, ConversationalStance]]:
        history: List[Tuple[int, ConversationalStance]] = []
        for item in list(value or []):
            if isinstance(item, dict):
                turn_raw = item.get("turn")
                stance_raw = item.get("stance")
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                turn_raw, stance_raw = item[0], item[1]
            else:
                continue
            try:
                stance = ConversationalStance(str(stance_raw))
            except ValueError:
                stance = ConversationalStance.UNKNOWN
            try:
                turn = int(turn_raw or 0)
            except (TypeError, ValueError):
                turn = 0
            history.append((turn, stance))
        return history

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
            if not tool_intent.projected_chain:
                tool_intent.projected_chain = [pending_tool]

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

        continuation_state = metadata.get("execution_continuation")
        if isinstance(continuation_state, dict):
            metadata["execution_continuation"] = ExecutionContinuation.from_dict(
                continuation_state
            ).to_dict()


def _contract_split_enabled() -> bool:
    try:
        from config import get_config

        return bool(getattr(get_config(), "enable_contract_split", False))
    except Exception:
        return False
