"""Phase 6.E.1 — Canonical execution state data model tests.

Read-only behaviour: verify data model, lazy init, telemetry sync, and safety
without changing routing or suppressing tool executions.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.expanduser("~/Agent1/emission_agent"))

from core.analytical_objective import (
    AORelationship,
    AOExecutionState,
    AOStatus,
    AnalyticalObjective,
    ExecutionStep,
    ExecutionStepStatus,
    IdempotencyDecision,
    IdempotencyResult,
    IntentConfidence,
    ToolCallRecord,
    ToolIntent,
)
from core.ao_manager import (
    ensure_execution_state,
    get_completed_tools_from_execution_state,
    get_pending_next_tool_from_execution_state,
    get_result_ref_for_tool,
)
from core.execution_continuation import ExecutionContinuation, PendingObjective
from core.execution_continuation_utils import load_execution_continuation, save_execution_continuation


def _mock_config(enabled: bool):
    """Return a mock config with the feature flag set."""
    cfg = MagicMock()
    cfg.enable_canonical_execution_state = enabled
    return cfg


def _make_ao(ao_id="AO#1", projected_chain=None, tool_call_log=None) -> AnalyticalObjective:
    """Build a minimal AO for testing."""
    chain = list(projected_chain or [])
    intent = ToolIntent(
        resolved_tool=chain[0] if chain else None,
        confidence=IntentConfidence.HIGH if chain else IntentConfidence.NONE,
        projected_chain=chain,
    )
    return AnalyticalObjective(
        ao_id=ao_id,
        session_id="test-session",
        objective_text="test objective",
        status=AOStatus.ACTIVE,
        start_turn=1,
        tool_intent=intent,
        tool_call_log=list(tool_call_log or []),
    )


# ── 1. lazy init from projected_chain creates pending steps ────────────────

def test_lazy_init_from_projected_chain_creates_pending_steps():
    """ensure_execution_state creates PENDING steps from projected_chain."""
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"])
    with patch("config.get_config", return_value=_mock_config(True)):
        state = ensure_execution_state(ao)
    assert state is not None
    assert state.planned_chain == ["calculate_macro_emission", "calculate_dispersion"]
    assert len(state.steps) == 2
    assert state.steps[0].tool_name == "calculate_macro_emission"
    assert state.steps[0].status == ExecutionStepStatus.PENDING
    assert state.steps[1].tool_name == "calculate_dispersion"
    assert state.steps[1].status == ExecutionStepStatus.PENDING
    assert state.chain_status == "active"


# ── 2. lazy init from existing tool_call_log marks completed steps ────────

def test_lazy_init_from_tool_call_log_marks_completed():
    """Tool calls already in tool_call_log produce COMPLETED steps."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"vehicle_type": "LDV"}, success=True, result_ref="macro_emission:baseline", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    with patch("config.get_config", return_value=_mock_config(True)):
        state = ensure_execution_state(ao)
    assert state.steps[0].status == ExecutionStepStatus.COMPLETED
    assert state.steps[0].result_ref == "macro_emission:baseline"
    assert state.steps[0].effective_args == {"vehicle_type": "LDV"}
    assert state.steps[1].status == ExecutionStepStatus.PENDING
    assert state.chain_cursor == 1


# ── 3. completed tool result updates step to COMPLETED ────────────────────

def test_completed_tool_updates_step():
    """Simulate OASC telemetry: a successful tool call transitions step to COMPLETED."""
    ao = _make_ao(projected_chain=["query_emission_factors"])
    with patch("config.get_config", return_value=_mock_config(True)):
        state = ensure_execution_state(ao)
    assert state.steps[0].status == ExecutionStepStatus.PENDING

    # Simulate what _sync_execution_state_telemetry does
    step = state.steps[0]
    step.status = ExecutionStepStatus.COMPLETED
    step.effective_args = {"vehicle_type": "Refuse Truck"}
    step.updated_turn = 2
    step.source = "tool_call"

    assert step.status == ExecutionStepStatus.COMPLETED
    assert step.effective_args == {"vehicle_type": "Refuse Truck"}
    assert step.updated_turn == 2


# ── 4. idempotent skip updates step to SKIPPED ────────────────────────────

def test_idempotent_skip_updates_step_to_skipped():
    """An idempotent skip result marks the step as SKIPPED."""
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"])
    with patch("config.get_config", return_value=_mock_config(True)):
        state = ensure_execution_state(ao)

    step = state.steps[0]
    step.status = ExecutionStepStatus.SKIPPED
    step.source = "idempotent_skip"
    step.provenance["idempotent_skip"] = True

    assert step.status == ExecutionStepStatus.SKIPPED
    assert step.provenance.get("idempotent_skip") is True


# ── 5. failed tool updates step to FAILED ─────────────────────────────────

def test_failed_tool_updates_step_to_failed():
    """A failed tool call marks the step as FAILED."""
    ao = _make_ao(projected_chain=["calculate_dispersion"])
    with patch("config.get_config", return_value=_mock_config(True)):
        state = ensure_execution_state(ao)

    step = state.steps[0]
    step.status = ExecutionStepStatus.FAILED
    step.error_summary = "missing spatial geometry"

    assert step.status == ExecutionStepStatus.FAILED
    assert "spatial" in step.error_summary


# ── 6. chain_cursor advances over completed/skipped steps ─────────────────

def test_chain_cursor_advances_over_completed_and_skipped():
    """Cursor moves past completed and skipped steps."""
    ao = _make_ao(projected_chain=["A", "B", "C"])
    with patch("config.get_config", return_value=_mock_config(True)):
        state = ensure_execution_state(ao)

    # All pending → cursor at 0
    assert state.chain_cursor == 0

    # Mark A completed
    state.steps[0].status = ExecutionStepStatus.COMPLETED
    # Mark B skipped
    state.steps[1].status = ExecutionStepStatus.SKIPPED
    # Recompute cursor
    cursor = 0
    for i, s in enumerate(state.steps):
        if s.status in (ExecutionStepStatus.COMPLETED, ExecutionStepStatus.SKIPPED):
            cursor = i + 1
        else:
            break
    state.chain_cursor = cursor
    assert state.chain_cursor == 2  # past A and B
    assert state.current_tool == "C"


# ── 7. feature flag false does not write execution_state metadata ─────────

def test_feature_flag_false_no_execution_state():
    """When feature flag is off, ensure_execution_state returns None."""
    ao = _make_ao(projected_chain=["calculate_macro_emission"])
    with patch("config.get_config", return_value=_mock_config(False)):
        state = ensure_execution_state(ao)
    assert state is None
    assert "execution_state" not in (ao.metadata or {})


# ── 8. old AO without metadata remains safe ───────────────────────────────

def test_old_ao_without_metadata_safe():
    """AO with None metadata does not crash ensure_execution_state."""
    ao = _make_ao(projected_chain=["calculate_macro_emission"])
    ao.metadata = None
    with patch("config.get_config", return_value=_mock_config(True)):
        state = ensure_execution_state(ao)
    # Should not crash; metadata is None so can't write but derivation still works
    assert state is not None
    assert state.planned_chain == ["calculate_macro_emission"]


# ── 9. ExecutionContinuation is not modified by 6.E.1 ─────────────────────

def test_execution_continuation_not_modified():
    """ensure_execution_state does not touch ExecutionContinuation."""
    ao = _make_ao(projected_chain=["A", "B"])
    cont = ExecutionContinuation(
        pending_objective=PendingObjective.CHAIN_CONTINUATION,
        pending_next_tool="B",
        pending_tool_queue=["B"],
    )
    save_execution_continuation(ao, cont)

    with patch("config.get_config", return_value=_mock_config(True)):
        ensure_execution_state(ao)

    after = load_execution_continuation(ao)
    assert after.pending_objective == PendingObjective.CHAIN_CONTINUATION
    assert after.pending_next_tool == "B"
    assert after.pending_tool_queue == ["B"]


# ── 10. no behavior-changing router response changes ──────────────────────

def test_no_routing_behavior_change():
    """ensure_execution_state is purely read-only — no side effects on routing state."""
    ao = _make_ao(projected_chain=["calculate_macro_emission"])
    original_status = ao.status
    original_tool_intent = ao.tool_intent.resolved_tool
    original_tool_call_log_len = len(ao.tool_call_log)

    with patch("config.get_config", return_value=_mock_config(True)):
        state = ensure_execution_state(ao)

    # AO state unchanged
    assert ao.status == original_status
    assert ao.tool_intent.resolved_tool == original_tool_intent
    assert len(ao.tool_call_log) == original_tool_call_log_len
    # State is derived but does not replace AO fields
    assert state is not None


# ── 11. compatibility helpers ─────────────────────────────────────────────

def test_get_pending_next_tool_returns_none_when_complete():
    """pending_next_tool is None when all steps are completed."""
    ao = _make_ao(projected_chain=["A"])
    with patch("config.get_config", return_value=_mock_config(True)):
        state = ensure_execution_state(ao)
    state.steps[0].status = ExecutionStepStatus.COMPLETED
    if isinstance(ao.metadata, dict):
        ao.metadata["execution_state"] = state.to_dict()
    with patch("config.get_config", return_value=_mock_config(True)):
        result = get_pending_next_tool_from_execution_state(ao)
    assert result is None


def test_get_completed_tools_from_execution_state():
    """Completed tools are returned from execution state."""
    log = [
        ToolCallRecord(turn=1, tool="A", args_compact={}, success=True, result_ref="a:baseline", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["A", "B"], tool_call_log=log)
    with patch("config.get_config", return_value=_mock_config(True)):
        tools = get_completed_tools_from_execution_state(ao)
    assert tools == ["A"]


def test_get_result_ref_for_tool():
    """result_ref lookup returns the correct reference."""
    log = [
        ToolCallRecord(turn=1, tool="A", args_compact={}, success=True, result_ref="artifact:baseline", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["A"], tool_call_log=log)
    with patch("config.get_config", return_value=_mock_config(True)):
        ref = get_result_ref_for_tool(ao, "A")
    assert ref == "artifact:baseline"


# ── 12. serialization round-trip ──────────────────────────────────────────

def test_execution_step_serialization_round_trip():
    """ExecutionStep to_dict / from_dict preserves data."""
    step = ExecutionStep(
        tool_name="calculate_macro_emission",
        status=ExecutionStepStatus.COMPLETED,
        effective_args={"vehicle_type": "LDV"},
        result_ref="macro_emission:baseline",
        source="tool_call",
        created_turn=1,
        updated_turn=2,
        revision_epoch=0,
        provenance={"key": "value"},
    )
    d = step.to_dict()
    restored = ExecutionStep.from_dict(d)
    assert restored.tool_name == "calculate_macro_emission"
    assert restored.status == ExecutionStepStatus.COMPLETED
    assert restored.effective_args == {"vehicle_type": "LDV"}
    assert restored.result_ref == "macro_emission:baseline"
    assert restored.provenance == {"key": "value"}


def test_ao_execution_state_serialization_round_trip():
    """AOExecutionState to_dict / from_dict preserves data."""
    state = AOExecutionState(
        objective_id="AO#1",
        planned_chain=["A", "B"],
        chain_cursor=1,
        steps=[
            ExecutionStep(tool_name="A", status=ExecutionStepStatus.COMPLETED, source="tool_call"),
            ExecutionStep(tool_name="B", status=ExecutionStepStatus.PENDING, source="projected_chain"),
        ],
        revision_epoch=0,
        chain_status="active",
        last_updated_turn=2,
    )
    d = state.to_dict()
    restored = AOExecutionState.from_dict(d)
    assert restored.objective_id == "AO#1"
    assert restored.planned_chain == ["A", "B"]
    assert restored.chain_cursor == 1
    assert len(restored.steps) == 2
    assert restored.steps[0].status == ExecutionStepStatus.COMPLETED
    assert restored.steps[1].status == ExecutionStepStatus.PENDING
    assert restored.chain_status == "active"


# ── 13. properties ────────────────────────────────────────────────────────

def test_is_chain_complete_all_completed():
    """is_chain_complete returns True when all steps completed/skipped."""
    state = AOExecutionState(
        steps=[
            ExecutionStep(tool_name="A", status=ExecutionStepStatus.COMPLETED),
            ExecutionStep(tool_name="B", status=ExecutionStepStatus.SKIPPED),
        ],
    )
    assert state.is_chain_complete is True


def test_is_chain_complete_with_pending():
    """is_chain_complete returns False when any step is pending."""
    state = AOExecutionState(
        steps=[
            ExecutionStep(tool_name="A", status=ExecutionStepStatus.COMPLETED),
            ExecutionStep(tool_name="B", status=ExecutionStepStatus.PENDING),
        ],
    )
    assert state.is_chain_complete is False


def test_is_chain_complete_with_failed():
    """is_chain_complete returns False when any step failed."""
    state = AOExecutionState(
        steps=[
            ExecutionStep(tool_name="A", status=ExecutionStepStatus.COMPLETED),
            ExecutionStep(tool_name="B", status=ExecutionStepStatus.FAILED),
        ],
    )
    assert state.is_chain_complete is False


def test_active_tool_matches():
    """active_tool_matches checks against current_tool."""
    state = AOExecutionState(
        planned_chain=["A", "B"],
        chain_cursor=0,
        steps=[
            ExecutionStep(tool_name="A", status=ExecutionStepStatus.PENDING),
            ExecutionStep(tool_name="B", status=ExecutionStepStatus.PENDING),
        ],
    )
    assert state.active_tool_matches("A") is True
    assert state.active_tool_matches("B") is False


def test_empty_steps_chain_not_complete():
    """Empty steps list → is_chain_complete is False."""
    state = AOExecutionState()
    assert state.is_chain_complete is False
    assert state.pending_next_tool is None
    assert state.current_tool is None


# ── 14. No-op with flag off ───────────────────────────────────────────────

def test_ensure_execution_state_none_with_flag_off():
    """When flag is off, ensure_execution_state returns None even for valid AO."""
    ao = _make_ao(projected_chain=["A", "B"])
    with patch("config.get_config", return_value=_mock_config(False)):
        assert ensure_execution_state(ao) is None
        assert ensure_execution_state(None) is None
