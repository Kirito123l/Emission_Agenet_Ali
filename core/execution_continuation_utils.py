from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.execution_continuation import ExecutionContinuation, PendingObjective


def load_execution_continuation(ao: Any) -> ExecutionContinuation:
    if ao is None or not isinstance(getattr(ao, "metadata", None), dict):
        return ExecutionContinuation.empty()
    payload = ao.metadata.get("execution_continuation")
    return ExecutionContinuation.from_dict(payload)


def save_execution_continuation(ao: Any, continuation: ExecutionContinuation) -> None:
    if ao is None:
        return
    if not isinstance(getattr(ao, "metadata", None), dict):
        ao.metadata = {}
    ao.metadata["execution_continuation"] = continuation.to_dict()


def clear_execution_continuation(ao: Any, *, updated_turn: Optional[int] = None) -> None:
    continuation = ExecutionContinuation.empty()
    continuation.updated_turn = updated_turn
    save_execution_continuation(ao, continuation)


def normalize_tool_queue(
    projected_chain: List[str],
    *,
    current_tool: Optional[str] = None,
) -> List[str]:
    queue = [str(item) for item in list(projected_chain or []) if str(item).strip()]
    if current_tool:
        current_tool = str(current_tool).strip()
        if queue and queue[0] == current_tool:
            queue = queue[1:]
    return queue


def build_chain_continuation(
    projected_chain: List[str],
    *,
    current_tool: str,
    updated_turn: Optional[int] = None,
) -> ExecutionContinuation:
    queue = normalize_tool_queue(projected_chain, current_tool=current_tool)
    continuation = ExecutionContinuation(
        pending_objective=PendingObjective.CHAIN_CONTINUATION if queue else PendingObjective.NONE,
        pending_next_tool=queue[0] if queue else None,
        pending_tool_queue=queue,
        updated_turn=updated_turn,
    )
    return continuation


def continuation_snapshot(continuation: ExecutionContinuation | Dict[str, Any] | None) -> Dict[str, Any]:
    if isinstance(continuation, ExecutionContinuation):
        return continuation.to_dict()
    if isinstance(continuation, dict):
        return ExecutionContinuation.from_dict(continuation).to_dict()
    return ExecutionContinuation.empty().to_dict()


def advance_tool_queue(queue: List[str], executed_tools: List[str]) -> List[str]:
    remaining = [str(item) for item in list(queue or []) if str(item).strip()]
    for tool_name in [str(item) for item in list(executed_tools or []) if str(item).strip()]:
        if remaining and remaining[0] == tool_name:
            remaining = remaining[1:]
            continue
        if tool_name in remaining:
            remaining = remaining[remaining.index(tool_name) + 1 :]
    return remaining
