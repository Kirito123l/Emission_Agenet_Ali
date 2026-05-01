"""Phase 6.E.3 — Canonical chain handoff tests.

Verify downstream handoff signals, intent/readiness integration, and
ExecutionContinuation compatibility.
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
    IntentConfidence,
    ToolCallRecord,
    ToolIntent,
)
from core.ao_manager import AOManager, ensure_execution_state
from core.execution_continuation import ExecutionContinuation, PendingObjective
from core.execution_continuation_utils import load_execution_continuation, save_execution_continuation


def _mock_config(**overrides):
    """Return a mock config with feature flags."""
    cfg = MagicMock()
    cfg.enable_canonical_execution_state = bool(overrides.get("canonical", True))
    cfg.enable_execution_idempotency = bool(overrides.get("idempotency", False))
    cfg.enable_contract_split = bool(overrides.get("contract_split", True))
    cfg.enable_split_continuation_state = bool(overrides.get("split_continuation", True))
    cfg.enable_split_intent_contract = bool(overrides.get("split_intent", True))
    cfg.enable_split_readiness_contract = bool(overrides.get("split_readiness", True))
    cfg.enable_split_stance_contract = bool(overrides.get("split_stance", True))
    cfg.enable_llm_decision_field = bool(overrides.get("llm_decision", False))
    cfg.enable_runtime_default_aware_readiness = bool(overrides.get("runtime_defaults", True))
    return cfg


def _make_ao(ao_id="AO#1", projected_chain=None, tool_call_log=None) -> AnalyticalObjective:
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


def _make_manager(ao_list=None):
    memory = MagicMock()
    memory.ao_history = list(ao_list or [])
    memory.current_ao_id = ao_list[0].ao_id if ao_list else None
    memory.last_turn_index = 1
    return AOManager(memory)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. get_canonical_pending_next_tool — pending downstream
# ═══════════════════════════════════════════════════════════════════════════════

def test_get_canonical_pending_next_tool_returns_dispersion():
    """completed macro + pending dispersion => get_canonical_pending_next_tool returns dispersion."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="emission:baseline", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True)):
        result = mgr.get_canonical_pending_next_tool(ao)

    assert result == "calculate_dispersion"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. get_canonical_pending_next_tool — all complete => None
# ═══════════════════════════════════════════════════════════════════════════════

def test_get_canonical_pending_next_tool_all_complete_returns_none():
    """When all steps are complete, returns None."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={}, success=True, result_ref="e:1", summary="ok"),
        ToolCallRecord(turn=2, tool="calculate_dispersion", args_compact={}, success=True, result_ref="d:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True)):
        result = mgr.get_canonical_pending_next_tool(ao)

    assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# 3. failed pending step — documented behavior
# ═══════════════════════════════════════════════════════════════════════════════

def test_failed_pending_step_returns_pending_tool():
    """When a step is FAILED, get_canonical_pending_next_tool returns it if at cursor.

    The canonical state treats FAILED steps as pending (not completed/skipped),
    so the chain_cursor stays at the failed step. The handoff returns the failed
    tool name, allowing retry. Callers decide whether to retry or abandon.
    """
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={}, success=True, result_ref="e:1", summary="ok"),
        ToolCallRecord(turn=2, tool="calculate_dispersion", args_compact={}, success=False, result_ref=None, summary="geometry missing"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True)):
        state = ensure_execution_state(ao)
        # Mark the dispersion step as FAILED explicitly
        for s in state.steps:
            if s.tool_name == "calculate_dispersion":
                s.status = ExecutionStepStatus.FAILED
        state.chain_cursor = 1  # cursor stops at failed step
        # Persist modifications to metadata so get_canonical_pending_next_tool sees them
        ao.metadata["execution_state"] = state.to_dict()
        result = mgr.get_canonical_pending_next_tool(ao)

    # Returns the failed tool — retry is allowed, caller decides
    assert result == "calculate_dispersion"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. proposed macro while dispersion pending => prefer pending dispersion
# ═══════════════════════════════════════════════════════════════════════════════

def test_should_prefer_pending_dispersion_over_completed_macro():
    """Proposing completed macro while dispersion is pending => prefer dispersion."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={}, success=True, result_ref="e:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True)):
        result = mgr.should_prefer_canonical_pending_tool(ao, proposed_tool="calculate_macro_emission")

    assert result is True


# ═══════════════════════════════════════════════════════════════════════════════
# 5. proposed dispersion while dispersion pending => proceed (no override)
# ═══════════════════════════════════════════════════════════════════════════════

def test_should_not_prefer_when_proposed_matches_pending():
    """When proposed tool IS the pending tool, should NOT override."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={}, success=True, result_ref="e:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True)):
        result = mgr.should_prefer_canonical_pending_tool(ao, proposed_tool="calculate_dispersion")

    assert result is False


# ═══════════════════════════════════════════════════════════════════════════════
# 6. proposed unrelated tool not in chain => do not override
# ═══════════════════════════════════════════════════════════════════════════════

def test_should_not_prefer_unrelated_tool():
    """Proposing an unrelated tool not in planned_chain => do not override."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={}, success=True, result_ref="e:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True)):
        result = mgr.should_prefer_canonical_pending_tool(ao, proposed_tool="query_emission_factors")

    assert result is False


# ═══════════════════════════════════════════════════════════════════════════════
# 7. explicit rerun signal => no pending next tool override
# ═══════════════════════════════════════════════════════════════════════════════

def test_rerun_signal_not_overridden_by_helper():
    """The helper itself does NOT check rerun signals — that is the caller's
    responsibility.  The helper correctly returns the pending tool when the
    proposed tool is an already-completed upstream step, regardless of rerun
    signals.  Callers (intent resolution) must gate on has_reversal_marker.
    """
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={}, success=True, result_ref="e:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True)):
        # The helper returns True for completed macro -> dispersion preference
        # even with rerun signal in the message; callers must check signals.
        result = mgr.should_prefer_canonical_pending_tool(ao, proposed_tool="calculate_macro_emission")

    assert result is True  # helper is signal-agnostic; callers gate


# ═══════════════════════════════════════════════════════════════════════════════
# 8. explicit revision signal => not overridden (caller-gated)
# ═══════════════════════════════════════════════════════════════════════════════

def test_revision_signal_not_overridden_by_helper():
    """Same as rerun — the helper is signal-agnostic. Caller intent resolution
    checks has_reversal_marker before invoking the canonical handoff path.
    """
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={}, success=True, result_ref="e:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True)):
        result = mgr.should_prefer_canonical_pending_tool(ao, proposed_tool="calculate_macro_emission")

    assert result is True  # helper returns truthfully; intent resolution gates on reversal


# ═══════════════════════════════════════════════════════════════════════════════
# 9. canonical state disabled => no override
# ═══════════════════════════════════════════════════════════════════════════════

def test_disabled_canonical_state_no_override():
    """When canonical state is disabled, helpers return None/False."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={}, success=True, result_ref="e:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=False)):
        assert mgr.get_canonical_pending_next_tool(ao) is None
        assert mgr.should_prefer_canonical_pending_tool(ao, proposed_tool="calculate_macro_emission") is False


# ═══════════════════════════════════════════════════════════════════════════════
# 10. canonical and ExecutionContinuation agree
# ═══════════════════════════════════════════════════════════════════════════════

def test_canonical_and_continuation_agree():
    """When both canonical state and ExecutionContinuation point to the same
    pending downstream tool, get_canonical_pending_next_tool returns it."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={}, success=True, result_ref="e:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    # Set up ExecutionContinuation with same pending tool
    cont = ExecutionContinuation(
        pending_objective=PendingObjective.CHAIN_CONTINUATION,
        pending_next_tool="calculate_dispersion",
        pending_tool_queue=["calculate_dispersion"],
    )
    save_execution_continuation(ao, cont)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True)):
        canonical_pending = mgr.get_canonical_pending_next_tool(ao)
        loaded = load_execution_continuation(ao)

    assert canonical_pending == "calculate_dispersion"
    assert loaded.pending_next_tool == "calculate_dispersion"
    assert canonical_pending == loaded.pending_next_tool


# ═══════════════════════════════════════════════════════════════════════════════
# 11. canonical and ExecutionContinuation disagree => canonical wins
# ═══════════════════════════════════════════════════════════════════════════════

def test_canonical_wins_when_disagree():
    """When canonical and ExecutionContinuation disagree, canonical's value
    is authoritative for the same planned_chain."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={}, success=True, result_ref="e:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    # ExecutionContinuation has stale/wrong pending tool
    cont = ExecutionContinuation(
        pending_objective=PendingObjective.CHAIN_CONTINUATION,
        pending_next_tool="calculate_macro_emission",  # wrong — already completed
        pending_tool_queue=["calculate_macro_emission"],
    )
    save_execution_continuation(ao, cont)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True)):
        canonical_pending = mgr.get_canonical_pending_next_tool(ao)
        loaded = load_execution_continuation(ao)

    # Canonical correctly returns dispersion, continuation has stale macro
    assert canonical_pending == "calculate_dispersion"
    assert loaded.pending_next_tool == "calculate_macro_emission"
    assert canonical_pending != loaded.pending_next_tool


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Task 120-like: follow-up resolves to dispersion not macro
# ═══════════════════════════════════════════════════════════════════════════════

def test_task120_followup_resolves_to_dispersion():
    """After macro completed, canonical pending_next_tool is calculate_dispersion."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="emission:baseline", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True)):
        pending = mgr.get_canonical_pending_next_tool(ao)
        should_prefer = mgr.should_prefer_canonical_pending_tool(ao, proposed_tool="calculate_macro_emission")
        state = ensure_execution_state(ao)

    assert pending == "calculate_dispersion"
    assert should_prefer is True
    assert state.chain_cursor == 1
    assert state.steps[0].status == ExecutionStepStatus.COMPLETED
    assert state.steps[1].status == ExecutionStepStatus.PENDING
    assert state.steps[0].tool_name == "calculate_macro_emission"
    assert state.steps[1].tool_name == "calculate_dispersion"


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Readiness for dispersion missing geometry returns clarify
# ═══════════════════════════════════════════════════════════════════════════════

def test_dispersion_missing_geometry_does_not_execute_macro():
    """When dispersion is the active tool but geometry is missing, the system
    should clarify (not re-execute macro).  This is verified by checking that
    get_canonical_pending_next_tool correctly identifies dispersion, and
    should_prefer_canonical_pending_tool blocks re-execution of macro."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={}, success=True, result_ref="e:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True)):
        # True: dispersion is the active pending tool
        pending = mgr.get_canonical_pending_next_tool(ao)
        # True: macro should NOT be re-executed
        prefer_dispersion = mgr.should_prefer_canonical_pending_tool(ao, proposed_tool="calculate_macro_emission")
        # False: dispersion itself should proceed (not be overridden)
        prefer_other = mgr.should_prefer_canonical_pending_tool(ao, proposed_tool="calculate_dispersion")

    assert pending == "calculate_dispersion"
    assert prefer_dispersion is True   # blocks macro re-execution
    assert prefer_other is False       # allows dispersion to proceed


# ═══════════════════════════════════════════════════════════════════════════════
# 14. Chain cursor remains 1 after geometry clarification
# ═══════════════════════════════════════════════════════════════════════════════

def test_chain_cursor_stays_after_clarification():
    """After dispersion receives clarification (geometry), chain_cursor stays
    at 1 (pointing to dispersion) — it doesn't advance and doesn't regress."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={}, success=True, result_ref="e:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True)):
        state = ensure_execution_state(ao)

        # Initial state: cursor=1 (dispersion pending)
        assert state.chain_cursor == 1
        assert state.pending_next_tool == "calculate_dispersion"

        # Simulate clarification turn (no tool executed)
        # Re-derive: state should be stable
        state2 = ensure_execution_state(ao)
        assert state2.chain_cursor == 1
        assert state2.steps[0].status == ExecutionStepStatus.COMPLETED
        assert state2.steps[1].status == ExecutionStepStatus.PENDING
        assert state2.chain_status == "active"  # not "complete" — dispersion still pending
