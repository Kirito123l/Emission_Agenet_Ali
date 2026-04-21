from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class PendingObjective(Enum):
    NONE = "none"
    PARAMETER_COLLECTION = "parameter_collection"
    CHAIN_CONTINUATION = "chain_continuation"


@dataclass
class ExecutionContinuation:
    pending_objective: PendingObjective = PendingObjective.NONE
    pending_slot: Optional[str] = None
    pending_next_tool: Optional[str] = None
    pending_tool_queue: List[str] = field(default_factory=list)
    probe_count: int = 0
    probe_limit: int = 2
    abandoned: bool = False
    updated_turn: Optional[int] = None

    def is_active(self) -> bool:
        if self.pending_objective == PendingObjective.NONE:
            return False
        if self.pending_objective == PendingObjective.PARAMETER_COLLECTION:
            return bool(self.pending_slot) and not self.abandoned
        if self.pending_objective == PendingObjective.CHAIN_CONTINUATION:
            return bool(self.pending_next_tool or self.pending_tool_queue)
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pending_objective": self.pending_objective.value,
            "pending_slot": self.pending_slot,
            "pending_next_tool": self.pending_next_tool,
            "pending_tool_queue": [
                str(item) for item in self.pending_tool_queue if str(item).strip()
            ],
            "probe_count": int(self.probe_count or 0),
            "probe_limit": int(self.probe_limit or 0),
            "abandoned": bool(self.abandoned),
            "updated_turn": int(self.updated_turn) if self.updated_turn is not None else None,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ExecutionContinuation":
        payload = data if isinstance(data, dict) else {}
        pending_objective_raw = str(
            payload.get("pending_objective") or PendingObjective.NONE.value
        ).strip()
        try:
            pending_objective = PendingObjective(pending_objective_raw)
        except ValueError:
            pending_objective = PendingObjective.NONE
        return cls(
            pending_objective=pending_objective,
            pending_slot=(
                str(payload.get("pending_slot")).strip()
                if payload.get("pending_slot") is not None
                else None
            ),
            pending_next_tool=(
                str(payload.get("pending_next_tool")).strip()
                if payload.get("pending_next_tool") is not None
                else None
            ),
            pending_tool_queue=[
                str(item)
                for item in list(payload.get("pending_tool_queue") or [])
                if str(item).strip()
            ],
            probe_count=int(payload.get("probe_count") or 0),
            probe_limit=max(1, int(payload.get("probe_limit") or 2)),
            abandoned=bool(payload.get("abandoned", False)),
            updated_turn=(
                int(payload["updated_turn"])
                if payload.get("updated_turn") is not None
                else None
            ),
        )

    @classmethod
    def empty(cls) -> "ExecutionContinuation":
        return cls()

