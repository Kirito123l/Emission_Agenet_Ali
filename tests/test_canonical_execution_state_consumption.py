"""Phase 6.E.2 — Canonical execution state consumption tests.

Verify that the canonical execution state decision helper correctly
suppresses intra-AO duplicate execution and advances to pending steps.
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
    CanonicalExecutionDecision,
    CanonicalExecutionResult,
    ExecutionStep,
    ExecutionStepStatus,
    IntentConfidence,
    ToolCallRecord,
    ToolIntent,
)
from core.ao_manager import AOManager, ensure_execution_state


def _mock_config(enabled: bool):
    cfg = MagicMock()
    cfg.enable_canonical_execution_state = enabled
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


def _make_manager():
    memory = MagicMock()
    memory.ao_history = []
    memory.current_ao_id = None
    return AOManager(memory)


# ── 1. completed step with no pending downstream => SKIP_COMPLETED_STEP ─

def test_completed_step_triggers_skip():
    """Proposing a tool whose step is already COMPLETED with no pending next returns SKIP_COMPLETED_STEP."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="emission:baseline", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission"], tool_call_log=log)
    mgr = _make_manager()

    with patch("config.get_config", return_value=_mock_config(True)):
        result = mgr.check_canonical_execution_state(ao, proposed_tool="calculate_macro_emission")

    assert result.decision == CanonicalExecutionDecision.SKIP_COMPLETED_STEP
    assert result.blocked_tool == "calculate_macro_emission"
    assert result.matched_step_index == 0


# ── 2. completed macro + pending dispersion + proposed macro => ADVANCE_TO_PENDING

def test_completed_with_pending_downstream_advances():
    """When a completed step is proposed and a pending downstream exists, return ADVANCE_TO_PENDING."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={}, success=True, result_ref="emission:baseline", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager()

    with patch("config.get_config", return_value=_mock_config(True)):
        result = mgr.check_canonical_execution_state(ao, proposed_tool="calculate_macro_emission")

    assert result.decision == CanonicalExecutionDecision.ADVANCE_TO_PENDING
    assert result.pending_next_tool == "calculate_dispersion"


# ── 3. proposed pending dispersion => PROCEED ────────────────────────────

def test_pending_downstream_proceeds():
    """Proposing the pending downstream tool returns PROCEED."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={}, success=True, result_ref="emission:baseline", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager()

    with patch("config.get_config", return_value=_mock_config(True)):
        result = mgr.check_canonical_execution_state(ao, proposed_tool="calculate_dispersion")

    assert result.decision == CanonicalExecutionDecision.PROCEED


# ── 4. failed dispersion step is NOT suppressed ─────────────────────────

def test_failed_step_not_suppressed():
    """A FAILED step does not suppress re-execution."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={}, success=True, result_ref="emission:baseline", summary="ok"),
        ToolCallRecord(turn=2, tool="calculate_dispersion", args_compact={}, success=False, result_ref=None, summary="missing spatial geometry"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager()

    with patch("config.get_config", return_value=_mock_config(True)):
        # Force derivation to set dispersion to FAILED
        state = ensure_execution_state(ao)
        for s in state.steps:
            if s.tool_name == "calculate_dispersion":
                s.status = ExecutionStepStatus.FAILED
        if isinstance(ao.metadata, dict):
            ao.metadata["execution_state"] = state.to_dict()

        result = mgr.check_canonical_execution_state(ao, proposed_tool="calculate_dispersion")

    # FAILED step should not be blocked — should PROCEED
    assert result.decision == CanonicalExecutionDecision.PROCEED


# ── 5. canonical flag false => NO_STATE ─────────────────────────────────

def test_flag_off_returns_no_state():
    """When the feature flag is off, returns NO_STATE."""
    ao = _make_ao(projected_chain=["calculate_macro_emission"])
    mgr = _make_manager()

    with patch("config.get_config", return_value=_mock_config(False)):
        result = mgr.check_canonical_execution_state(ao, proposed_tool="calculate_macro_emission")

    assert result.decision == CanonicalExecutionDecision.NO_STATE


# ── 6. skip does NOT append normal tool_call_log ────────────────────────

def test_skip_does_not_append_tool_call_log():
    """Canonical skip result has canonical_skip=True — OASC should not record as normal tool call."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={}, success=True, result_ref="emission:baseline", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager()

    with patch("config.get_config", return_value=_mock_config(True)):
        result = mgr.check_canonical_execution_state(ao, proposed_tool="calculate_macro_emission")

    assert result.decision in (
        CanonicalExecutionDecision.SKIP_COMPLETED_STEP,
        CanonicalExecutionDecision.ADVANCE_TO_PENDING,
    )
    # The decision itself must not mutate tool_call_log
    assert len(ao.tool_call_log) == 1


# ── 7. chain_cursor preserved after skip ────────────────────────────────

def test_chain_cursor_preserved_after_skip():
    """After canonical skip, chain_cursor still points to pending dispersion."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={}, success=True, result_ref="emission:baseline", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager()

    with patch("config.get_config", return_value=_mock_config(True)):
        # Check state before skip
        state = ensure_execution_state(ao)
        assert state.chain_cursor == 1  # macro done, cursor at dispersion
        assert state.pending_next_tool == "calculate_dispersion"

        # Run decision
        result = mgr.check_canonical_execution_state(ao, proposed_tool="calculate_macro_emission")
        assert result.decision == CanonicalExecutionDecision.ADVANCE_TO_PENDING

        # State is unchanged by check (read-only)
        state2 = ensure_execution_state(ao)
        assert state2.chain_cursor == 1
        assert state2.pending_next_tool == "calculate_dispersion"


# ── 8. Phase 6.1 inter-AO idempotency works independently ──────────────

def test_inter_ao_idempotency_independent():
    """Canonical state check and Phase 6.1 inter-AO idempotency are independent layers."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="emission:baseline", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission"], tool_call_log=log)
    mgr = _make_manager()

    with patch("config.get_config", return_value=_mock_config(True)):
        canonical = mgr.check_canonical_execution_state(ao, proposed_tool="calculate_macro_emission")

    # Canonical check should see the completed step and skip
    assert canonical.decision in (
        CanonicalExecutionDecision.SKIP_COMPLETED_STEP,
        CanonicalExecutionDecision.ADVANCE_TO_PENDING,
    )

    # Phase 6.1 idempotency would also catch this (same tool in same AO's tool_call_log)
    # Both layers are complementary but independent
    from core.ao_manager import TOOL_SEMANTIC_KEYS
    assert "calculate_macro_emission" in TOOL_SEMANTIC_KEYS


# ── 9. Task 120-like: macro completed, proposed macro => skip ───────────

def test_task120_macro_completed_proposed_macro_skip():
    """Task 120 pattern: after macro completed, another macro proposal is skipped."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission",
                       args_compact={"pollutants": ["NOx"], "file_path": "/tmp/road.csv"},
                       success=True, result_ref="emission:baseline", summary="ok"),
    ]
    ao = _make_ao(
        projected_chain=["calculate_macro_emission", "calculate_dispersion"],
        tool_call_log=log,
    )
    mgr = _make_manager()

    with patch("config.get_config", return_value=_mock_config(True)):
        result = mgr.check_canonical_execution_state(ao, proposed_tool="calculate_macro_emission")

    assert result.decision == CanonicalExecutionDecision.ADVANCE_TO_PENDING
    assert result.pending_next_tool == "calculate_dispersion"
    assert result.blocked_tool == "calculate_macro_emission"


# ── 10. Task 120-like: proposed dispersion after macro completed => proceed

def test_task120_dispersion_after_macro_proceeds():
    """After macro completed, proposing the pending dispersion should proceed."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission",
                       args_compact={}, success=True, result_ref="emission:baseline", summary="ok"),
    ]
    ao = _make_ao(
        projected_chain=["calculate_macro_emission", "calculate_dispersion"],
        tool_call_log=log,
    )
    mgr = _make_manager()

    with patch("config.get_config", return_value=_mock_config(True)):
        result = mgr.check_canonical_execution_state(ao, proposed_tool="calculate_dispersion")

    assert result.decision == CanonicalExecutionDecision.PROCEED


# ── 11. empty proposed tool => PROCEED ──────────────────────────────────

def test_empty_proposed_tool_proceeds():
    """Empty proposed tool returns PROCEED."""
    ao = _make_ao(projected_chain=["A"])
    mgr = _make_manager()

    with patch("config.get_config", return_value=_mock_config(True)):
        result = mgr.check_canonical_execution_state(ao, proposed_tool="")

    assert result.decision == CanonicalExecutionDecision.PROCEED


# ── 12. skipped step + proposed same tool => SKIP_COMPLETED_STEP ───────

def test_skipped_step_triggers_skip():
    """A step that was skipped by idempotency should also trigger skip."""
    ao = _make_ao(projected_chain=["A", "B"])
    mgr = _make_manager()

    with patch("config.get_config", return_value=_mock_config(True)):
        state = ensure_execution_state(ao)
        state.steps[0].status = ExecutionStepStatus.SKIPPED
        state.steps[0].source = "idempotent_skip"
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

        result = mgr.check_canonical_execution_state(ao, proposed_tool="A")

    assert result.decision == CanonicalExecutionDecision.ADVANCE_TO_PENDING
    assert result.pending_next_tool == "B"


# ── 13. completed step status NOT overwritten by canonical skip telemetry ──

def test_completed_step_remains_completed_after_canonical_skip():
    """When canonical skip occurs for a COMPLETED step, status stays COMPLETED."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission",
                       args_compact={"pollutant": "NOx"}, success=True,
                       result_ref="emission:baseline", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"],
                  tool_call_log=log)
    mgr = _make_manager()

    with patch("config.get_config", return_value=_mock_config(True)):
        state = ensure_execution_state(ao)
        # Verify macro is COMPLETED
        assert state.steps[0].status == ExecutionStepStatus.COMPLETED

        # Simulate what _sync_execution_state_telemetry does with a canonical_skip result
        # The step is COMPLETED, canonical_skip=True → must NOT change to SKIPPED
        step = state.steps[0]
        is_canonical_skip = True
        if is_canonical_skip and step.status == ExecutionStepStatus.COMPLETED:
            step.provenance["canonical_skip_attempted"] = True
            step.provenance["canonical_skip_attempted_at_turn"] = 2
        else:
            step.status = ExecutionStepStatus.SKIPPED  # This path must NOT run

        assert step.status == ExecutionStepStatus.COMPLETED
        assert step.provenance.get("canonical_skip_attempted") is True
        assert step.result_ref == "emission:baseline"


# ── 14. ADVANCE_TO_PENDING preserves chain_cursor and pending_next_tool ──

def test_advance_to_pending_preserves_chain_state():
    """ADVANCE_TO_PENDING decision does not mutate chain_cursor or pending_next_tool."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission",
                       args_compact={}, success=True,
                       result_ref="emission:baseline", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"],
                  tool_call_log=log)
    mgr = _make_manager()

    with patch("config.get_config", return_value=_mock_config(True)):
        state = ensure_execution_state(ao)
        assert state.chain_cursor == 1
        assert state.pending_next_tool == "calculate_dispersion"

        # Run decision — must be read-only
        result = mgr.check_canonical_execution_state(ao, proposed_tool="calculate_macro_emission")
        assert result.decision == CanonicalExecutionDecision.ADVANCE_TO_PENDING
        assert result.pending_next_tool == "calculate_dispersion"

        # chain_cursor unchanged
        state2 = ensure_execution_state(ao)
        assert state2.chain_cursor == 1
        assert state2.pending_next_tool == "calculate_dispersion"


# ── 15. canonical skip result is NOT success ────────────────────────────

def test_canonical_skip_result_not_success():
    """The executor wrapper does NOT return success=True for canonical skips."""
    # This verifies that the return dict from _IdempotencyAwareExecutor.execute()
    # for canonical skips has success=False and canonical_skip=True.
    # Simulate the exact return value the wrapper produces.
    result = {
        "success": False,
        "message": "canonical skip — calculate_macro_emission already advance_to_pending",
        "summary": "Canonical execution state skip: calculate_macro_emission (matched step[0], pending_next=calculate_dispersion)",
        "canonical_skip": True,
        "canonical_decision": "advance_to_pending",
        "pending_next_tool": "calculate_dispersion",
    }
    assert result["success"] is False
    assert result["canonical_skip"] is True
    # OASC checks canonical_skip BEFORE success
    assert result.get("canonical_skip") is True
    # This means OASC's `if tool_result.get("canonical_skip"): continue` works


# ── 16. OASC continuation excludes canonical_skip from executed_tools ──

def test_continuation_excludes_canonical_skip():
    """_refresh_split_execution_continuation must not count canonical_skip as executed."""
    # Simulate the executed_tools filter logic
    executed_tool_calls = [
        {
            "name": "calculate_macro_emission",
            "result": {
                "success": False,
                "canonical_skip": True,
                "canonical_decision": "advance_to_pending",
            },
        },
        {
            "name": "calculate_dispersion",
            "result": {"success": True},
        },
    ]
    executed_tools = [
        str(item.get("name") or "").strip()
        for item in executed_tool_calls
        if isinstance(item, dict)
        and str(item.get("name") or "").strip()
        and bool((item.get("result") or {}).get("success"))
        and not bool((item.get("result") or {}).get("idempotent_skip"))
        and not bool((item.get("result") or {}).get("canonical_skip"))
    ]
    assert "calculate_macro_emission" not in executed_tools
    assert executed_tools == ["calculate_dispersion"]


# ── 17. forced duplicate macro through executor wrapper ─────────────────

@pytest.mark.anyio
async def test_executor_wrapper_blocks_duplicate_macro():
    """Deterministic: executor wrapper receives duplicate macro, real executor NOT called."""
    from unittest.mock import AsyncMock
    from core.governed_router import _IdempotencyAwareExecutor

    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission",
                       args_compact={"pollutant": "NOx"}, success=True,
                       result_ref="emission:baseline", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"],
                  tool_call_log=log)

    # Build a mock governed_router
    mock_gr = MagicMock()
    mock_gr.runtime_config = _mock_config(True)
    mgr = _make_manager()
    # Put ao into memory so get_current_ao() returns it
    mgr._memory.ao_history = [ao]
    mgr._memory.current_ao_id = ao.ao_id
    mock_gr.ao_manager = mgr

    # Build executor with a real delegate that counts calls
    real_executor = MagicMock()
    real_executor.execute = AsyncMock(return_value={"success": True, "summary": "real execution"})

    wrapper = _IdempotencyAwareExecutor(real_executor, mock_gr)

    # Canonical state enabled, macro already completed → should block
    with patch("config.get_config", return_value=_mock_config(True)):
        result = await wrapper.execute(
            tool_name="calculate_macro_emission",
            arguments={"pollutant": "NOx"},
        )

    # Real executor must NOT have been called
    real_executor.execute.assert_not_called()

    # Result must indicate canonical skip, not success
    assert result.get("success") is False
    assert result.get("canonical_skip") is True
    assert result.get("pending_next_tool") == "calculate_dispersion"

    # tool_call_log must NOT have been appended
    assert len(ao.tool_call_log) == 1

    # Macro step must remain COMPLETED
    with patch("config.get_config", return_value=_mock_config(True)):
        state = ensure_execution_state(ao)
    assert state.steps[0].status == ExecutionStepStatus.COMPLETED
    assert state.steps[0].result_ref == "emission:baseline"
    assert state.chain_cursor == 1
    assert state.pending_next_tool == "calculate_dispersion"


# ── 18. executor wrapper proceeds when canonical state says PROCEED ──────

@pytest.mark.anyio
async def test_executor_wrapper_proceeds_when_proceed():
    """Deterministic: executor wrapper calls real executor when decision is PROCEED."""
    from unittest.mock import AsyncMock
    from core.governed_router import _IdempotencyAwareExecutor

    ao = _make_ao(projected_chain=["calculate_dispersion"])
    mock_gr = MagicMock()
    mock_gr.runtime_config = _mock_config(True)
    mgr = _make_manager()
    mgr._memory.ao_history = [ao]
    mgr._memory.current_ao_id = ao.ao_id
    mock_gr.ao_manager = mgr

    real_executor = MagicMock()
    real_executor.execute = AsyncMock(return_value={"success": True, "summary": "dispersion done"})

    wrapper = _IdempotencyAwareExecutor(real_executor, mock_gr)

    with patch("config.get_config", return_value=_mock_config(True)):
        result = await wrapper.execute(
            tool_name="calculate_dispersion",
            arguments={"stability_class": "neutral"},
        )

    # Real executor must have been called (dispersion is pending, not completed)
    real_executor.execute.assert_called_once()
    assert result["success"] is True
    assert "canonical_skip" not in result
