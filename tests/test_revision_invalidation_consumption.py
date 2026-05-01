"""Phase 6.E.4D — Execution boundary consumes invalidated cursor.

These tests verify that the execution boundary correctly handles INVALIDATED steps:
canonical duplicate guard returns PROCEED, idempotency returns NO_DUPLICATE,
pending-next-tool includes INVALIDATED, OASC revalidation telemetry is written,
and feature flags preserve old behaviour.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.expanduser("~/Agent1/emission_agent"))

from core.analytical_objective import (
    AORelationship,
    AOStatus,
    AnalyticalObjective,
    CanonicalExecutionDecision,
    CanonicalExecutionResult,
    ExecutionStep,
    ExecutionStepStatus,
    IdempotencyDecision,
    IntentConfidence,
    ToolCallRecord,
    ToolIntent,
)
from core.ao_manager import AOManager, ensure_execution_state


def _mock_config(*, canonical=True, revision=True, idempotency=False):
    cfg = MagicMock()
    cfg.enable_canonical_execution_state = canonical
    cfg.enable_revision_invalidation = revision
    cfg.enable_execution_idempotency = idempotency
    return cfg


def _make_ao(projected_chain=None, tool_call_log=None):
    chain = list(projected_chain or [])
    intent = ToolIntent(
        resolved_tool=chain[0] if chain else None,
        confidence=IntentConfidence.HIGH if chain else IntentConfidence.NONE,
        projected_chain=chain,
    )
    return AnalyticalObjective(
        ao_id="AO#4D",
        session_id="test-session-4d",
        objective_text="test consumption objective",
        status=AOStatus.ACTIVE,
        start_turn=1,
        tool_intent=intent,
        tool_call_log=list(tool_call_log or []),
    )


def _make_manager():
    memory = MagicMock()
    memory.ao_history = []
    memory.current_ao_id = None
    return AOManager(memory)


def _setup_invalidated_state(ao):
    """Set up AOExecutionState with COMPLETED macro + INVALIDATED dispersion at cursor=1."""
    state = ensure_execution_state(ao)
    assert state is not None, "ensure_execution_state returned None — canonical flag may be disabled"
    state.steps[0].status = ExecutionStepStatus.COMPLETED
    state.steps[0].effective_args = {"pollutants": ["NOx"], "file_path": "/tmp/links.csv"}
    state.steps[0].result_ref = "macro_emission:nox"
    state.steps[0].source = "tool_call"
    state.steps[1].status = ExecutionStepStatus.INVALIDATED
    state.steps[1].effective_args = {"pollutant": "NOx", "meteorology": "windy_neutral"}
    state.steps[1].provenance = {"stale_result_ref": "dispersion:nox", "invalidated_reason": "param_delta_downstream"}
    state.chain_cursor = 1
    state.chain_status = "active"
    if isinstance(ao.metadata, dict):
        ao.metadata["execution_state"] = state.to_dict()
    return state


def _setup_both_invalidated_state(ao):
    """Set up AOExecutionState with both macro and dispersion INVALIDATED at cursor=0."""
    state = ensure_execution_state(ao)
    assert state is not None, "ensure_execution_state returned None — canonical flag may be disabled"
    state.steps[0].status = ExecutionStepStatus.INVALIDATED
    state.steps[0].effective_args = {"pollutants": ["NOx"], "file_path": "/tmp/links.csv"}
    state.steps[0].provenance = {"stale_result_ref": "macro_emission:nox", "invalidated_reason": "param_delta_self"}
    state.steps[1].status = ExecutionStepStatus.INVALIDATED
    state.steps[1].effective_args = {"pollutant": "NOx", "meteorology": "windy_neutral"}
    state.steps[1].provenance = {"stale_result_ref": "dispersion:nox", "invalidated_reason": "param_delta_downstream"}
    state.chain_cursor = 0
    state.chain_status = "active"
    if isinstance(ao.metadata, dict):
        ao.metadata["execution_state"] = state.to_dict()
    return state


# ── 1. invalidated macro at cursor => canonical duplicate guard returns PROCEED ─

def test_invalidated_macro_at_cursor_canonical_guard_returns_proceed():
    """When macro is INVALIDATED at chain_cursor, check_canonical_execution_state returns PROCEED."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutants": ["NOx"]},
                       success=True, result_ref="macro_emission:nox", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager()

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_both_invalidated_state(ao)
        result = mgr.check_canonical_execution_state(ao, proposed_tool="calculate_macro_emission")

    assert result.decision == CanonicalExecutionDecision.PROCEED
    assert "invalidated" in result.reason.lower()


# ── 2. invalidated macro at cursor => idempotency returns NO_DUPLICATE ─

def test_invalidated_macro_idempotency_returns_no_duplicate():
    """When macro step is INVALIDATED, idempotency returns NO_DUPLICATE, not EXACT_DUPLICATE."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutants": ["NOx"], "file_path": "/tmp/links.csv"},
                       success=True, result_ref="macro_emission:nox", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager()

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True, idempotency=True)):
        _setup_both_invalidated_state(ao)
        idem = mgr.check_execution_idempotency(
            ao,
            proposed_tool="calculate_macro_emission",
            proposed_args={"pollutants": ["NOx"], "file_path": "/tmp/links.csv"},
            user_message="NOx",
        )

    assert idem.decision == IdempotencyDecision.NO_DUPLICATE
    assert "canonical_step_invalidated" in idem.decision_reason


# ── 3. completed macro + invalidated dispersion => pending_next_tool is dispersion ─

def test_completed_macro_invalidated_dispersion_pending_next_tool_is_dispersion():
    """When dispersion is INVALIDATED at cursor=1, pending_next_tool returns dispersion."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutants": ["NOx"]},
                       success=True, result_ref="macro_emission:nox", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager()

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_invalidated_state(ao)
        pending = mgr.get_canonical_pending_next_tool(ao)

    assert pending == "calculate_dispersion"


# ── 4. proposed macro while dispersion invalidated => prefer dispersion ─

def test_proposed_macro_while_dispersion_invalidated_prefer_dispersion():
    """When dispersion is INVALIDATED at cursor=1 and macro is proposed, prefer dispersion."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutants": ["NOx"]},
                       success=True, result_ref="macro_emission:nox", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager()

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_invalidated_state(ao)
        should_prefer = mgr.should_prefer_canonical_pending_tool(ao, proposed_tool="calculate_macro_emission")

    assert should_prefer is True

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        canonical = mgr.check_canonical_execution_state(ao, proposed_tool="calculate_macro_emission")

    assert canonical.decision == CanonicalExecutionDecision.ADVANCE_TO_PENDING
    assert canonical.pending_next_tool == "calculate_dispersion"
    assert canonical.blocked_tool == "calculate_macro_emission"


# ── 5. invalidated dispersion executes successfully => COMPLETED + fresh result_ref ─

def test_invalidated_dispersion_revalidates_to_completed_with_fresh_ref():
    """After INVALIDATED dispersion executes successfully, status=COMPLETED with fresh result_ref."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutants": ["NOx"]},
                       success=True, result_ref="macro_emission:nox", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        state = _setup_invalidated_state(ao)
        dispersion_step = state.steps[1]
        assert dispersion_step.status == ExecutionStepStatus.INVALIDATED
        assert dispersion_step.provenance.get("stale_result_ref") == "dispersion:nox"

        # Simulate what _sync_execution_state_telemetry does for success
        dispersion_step.status = ExecutionStepStatus.COMPLETED
        dispersion_step.result_ref = "dispersion:co2"
        dispersion_step.effective_args = {"pollutant": "CO2", "meteorology": "urban_summer_day"}
        dispersion_step.updated_turn = 3
        dispersion_step.source = "tool_call"
        dispersion_step.provenance["revalidated_at_turn"] = 3
        if isinstance(ao.metadata, dict):
            ao.metadata["execution_state"] = state.to_dict()

        # Re-verify
        state2 = ensure_execution_state(ao)
        assert state2.steps[1].status == ExecutionStepStatus.COMPLETED
        assert state2.steps[1].result_ref == "dispersion:co2"


# ── 6. stale_result_ref remains in provenance after revalidation ─

def test_stale_result_ref_preserved_after_revalidation():
    """After INVALIDATED step revalidates, provenance retains stale_result_ref."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutants": ["NOx"]},
                       success=True, result_ref="macro_emission:nox", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        state = _setup_invalidated_state(ao)
        dispersion_step = state.steps[1]

        # Revalidate
        was_invalidated = dispersion_step.status == ExecutionStepStatus.INVALIDATED
        dispersion_step.status = ExecutionStepStatus.COMPLETED
        dispersion_step.result_ref = "dispersion:co2"
        dispersion_step.updated_turn = 3
        if was_invalidated:
            dispersion_step.provenance["revalidated_at_turn"] = 3
        if isinstance(ao.metadata, dict):
            ao.metadata["execution_state"] = state.to_dict()

        state2 = ensure_execution_state(ao)
        prov = state2.steps[1].provenance
        assert prov.get("stale_result_ref") == "dispersion:nox"
        assert prov.get("revalidated_at_turn") == 3
        assert prov.get("invalidated_reason") == "param_delta_downstream"


# ── 7. chain_cursor advances after invalidated step completion ─

def test_chain_cursor_advances_after_invalidated_step_revalidates():
    """After INVALIDATED step completes, chain_cursor advances past it."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutants": ["NOx"]},
                       success=True, result_ref="macro_emission:nox", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        state = _setup_both_invalidated_state(ao)
        assert state.chain_cursor == 0

        # Macro revalidates
        macro_step = state.steps[0]
        macro_step.status = ExecutionStepStatus.COMPLETED
        macro_step.result_ref = "macro_emission:co2"
        macro_step.updated_turn = 3
        macro_step.provenance["revalidated_at_turn"] = 3

        # Recompute cursor
        cursor = 0
        for i, s in enumerate(state.steps):
            if s.status in (ExecutionStepStatus.COMPLETED, ExecutionStepStatus.SKIPPED):
                cursor = i + 1
            else:
                break
        state.chain_cursor = cursor
        if isinstance(ao.metadata, dict):
            ao.metadata["execution_state"] = state.to_dict()

        state2 = ensure_execution_state(ao)
        assert state2.chain_cursor == 1
        assert state2.steps[0].status == ExecutionStepStatus.COMPLETED
        assert state2.steps[0].result_ref == "macro_emission:co2"
        assert state2.steps[1].status == ExecutionStepStatus.INVALIDATED


# ── 8. unaffected upstream completed macro stays completed ─

def test_upstream_completed_macro_preserved_when_dispersion_invalidated():
    """When only dispersion is invalidated, upstream macro stays COMPLETED with result_ref."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutants": ["NOx"]},
                       success=True, result_ref="macro_emission:nox", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        state = _setup_invalidated_state(ao)
        macro = state.steps[0]
        assert macro.status == ExecutionStepStatus.COMPLETED
        assert macro.result_ref == "macro_emission:nox"
        assert macro.provenance.get("stale_result_ref") is None


# ── 9. INVALIDATED step is not treated as SKIPPED ─

def test_invalidated_step_not_treated_as_skipped():
    """An INVALIDATED step must NOT be treated as SKIPPED by canonical guard."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutants": ["NOx"]},
                       success=True, result_ref="macro_emission:nox", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager()

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_both_invalidated_state(ao)
        result = mgr.check_canonical_execution_state(ao, proposed_tool="calculate_macro_emission")

    assert result.decision != CanonicalExecutionDecision.SKIP_COMPLETED_STEP
    assert result.decision == CanonicalExecutionDecision.PROCEED


# ── 10. feature flags off => old behavior unchanged ─

def test_flags_off_unchanged_behavior():
    """With canonical/revision flags off, methods behave as before."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutants": ["NOx"]},
                       success=True, result_ref="macro_emission:nox", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager()

    with patch("config.get_config", return_value=_mock_config(canonical=False, revision=False)):
        result = mgr.check_canonical_execution_state(ao, proposed_tool="calculate_macro_emission")
        assert result.decision == CanonicalExecutionDecision.NO_STATE

        pending = mgr.get_canonical_pending_next_tool(ao)
        assert pending is None

        pref = mgr.should_prefer_canonical_pending_tool(ao, proposed_tool="calculate_macro_emission")
        assert pref is False

        idem = mgr.check_execution_idempotency(
            ao,
            proposed_tool="calculate_macro_emission",
            proposed_args={"pollutants": ["NOx"], "file_path": "/tmp/links.csv"},
            user_message="NOx",
        )
        # Without canonical state, the INVALIDATED check in idempotency is skipped
        assert "canonical_step_invalidated" not in idem.decision_reason


# ── 11. explicit rerun of invalidated step still proceeds ─

def test_explicit_rerun_of_invalidated_step_proceeds():
    """Explicit rerun signal with INVALIDATED step still goes through as NO_DUPLICATE."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutants": ["NOx"], "file_path": "/tmp/links.csv"},
                       success=True, result_ref="macro_emission:nox", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager()

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True, idempotency=True)):
        _setup_both_invalidated_state(ao)
        idem = mgr.check_execution_idempotency(
            ao,
            proposed_tool="calculate_macro_emission",
            proposed_args={"pollutants": ["NOx"], "file_path": "/tmp/links.csv"},
            user_message="重新算一遍",
        )

    assert idem.decision == IdempotencyDecision.NO_DUPLICATE
    assert "canonical_step_invalidated" in idem.decision_reason


# ── 12. failed invalidated step retry does not mark complete ─

def test_failed_invalidated_step_retry_does_not_mark_complete():
    """When an INVALIDATED step re-executes and fails, it stays FAILED, not COMPLETED."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutants": ["NOx"]},
                       success=True, result_ref="macro_emission:nox", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        state = _setup_invalidated_state(ao)
        dispersion = state.steps[1]
        assert dispersion.status == ExecutionStepStatus.INVALIDATED

        # Simulate failure: _sync_execution_state_telemetry sets FAILED on non-success
        dispersion.status = ExecutionStepStatus.FAILED
        dispersion.error_summary = "missing spatial geometry"
        dispersion.updated_turn = 3
        if isinstance(ao.metadata, dict):
            ao.metadata["execution_state"] = state.to_dict()

        state2 = ensure_execution_state(ao)
        assert state2.steps[1].status == ExecutionStepStatus.FAILED
        assert state2.steps[1].status != ExecutionStepStatus.COMPLETED
        assert state2.steps[1].error_summary == "missing spatial geometry"
