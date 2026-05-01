"""Phase 6.E.4B — Revision invalidation engine tests.

Unit-tests the AOManager.apply_revision_invalidation() method.
Mutates AOExecutionState in controlled unit-test contexts only.
Does NOT connect to live routing / execution path.
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
    RevisionDeltaDecisionPreview,
    RevisionDeltaTelemetry,
    RevisionInvalidationDecision,
    RevisionInvalidationResult,
    ToolCallRecord,
    ToolIntent,
)
from core.ao_manager import AOManager, ensure_execution_state
from core.execution_continuation import ExecutionContinuation


def _mock_config(canonical=True, revision=True):
    cfg = MagicMock()
    cfg.enable_canonical_execution_state = canonical
    cfg.enable_revision_invalidation = revision
    return cfg


def _make_ao(ao_id="AO#1", projected_chain=None, tool_call_log=None,
             relationship=None) -> AnalyticalObjective:
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
        relationship=relationship or AORelationship.INDEPENDENT,
    )


def _make_manager(ao_list=None):
    memory = MagicMock()
    memory.ao_history = list(ao_list or [])
    memory.current_ao_id = ao_list[0].ao_id if ao_list else None
    memory.last_turn_index = 1
    return AOManager(memory)


def _setup_state(ao, steps_completed=True):
    """Ensure AOExecutionState is initialized with completed steps.

    Caller MUST be inside a ``with patch("config.get_config", ...)`` block.
    """
    state = ensure_execution_state(ao)
    if state is None:
        raise RuntimeError(
            "ensure_execution_state returned None — canonical state flag may be disabled"
        )
    if steps_completed:
        for s in state.steps:
            if s.status == ExecutionStepStatus.PENDING:
                s.status = ExecutionStepStatus.COMPLETED
        # Recompute cursor
        state.chain_cursor = 0
        for i, s in enumerate(state.steps):
            if s.status in (ExecutionStepStatus.COMPLETED, ExecutionStepStatus.SKIPPED):
                state.chain_cursor = i + 1
            else:
                break
        if all(s.status in (ExecutionStepStatus.COMPLETED, ExecutionStepStatus.SKIPPED)
               for s in state.steps):
            state.chain_status = "complete"
        else:
            state.chain_status = "active"
    ao.metadata["execution_state"] = state.to_dict()
    return state


# ═══════════════════════════════════════════════════════════════════════════════
# 1. flags disabled => no mutation
# ═══════════════════════════════════════════════════════════════════════════════

def test_flags_disabled_no_mutation():
    log = [ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok")]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    # Set up state with both flags on first
    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_state(ao)

    # Now apply with revision disabled
    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=False)):
        tele = RevisionDeltaTelemetry(
            detected=True,
            decision_preview=RevisionDeltaDecisionPreview.PARAM_DELTA_DOWNSTREAM,
            would_invalidate_tools=["calculate_macro_emission", "calculate_dispersion"],
            changed_keys=["pollutant"],
            reason="test",
        )
        result = mgr.apply_revision_invalidation(ao, tele)

    assert result.decision == RevisionInvalidationDecision.NOOP.value
    assert "flag disabled" in result.reason

    # Verify no state mutation (read with flags on)
    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        state = ensure_execution_state(ao)
        for s in state.steps:
            assert s.status != ExecutionStepStatus.INVALIDATED


# ═══════════════════════════════════════════════════════════════════════════════
# 2. NO_DELTA telemetry => no mutation
# ═══════════════════════════════════════════════════════════════════════════════

def test_no_delta_telemetry_no_mutation():
    log = [ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok")]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_state(ao)

        tele = RevisionDeltaTelemetry(
            detected=False,
            decision_preview=RevisionDeltaDecisionPreview.NO_DELTA,
            changed_keys=[],
            reason="no delta",
        )
        result = mgr.apply_revision_invalidation(ao, tele)

    assert result.decision == RevisionInvalidationDecision.NOOP.value
    assert result.invalidated_step_indices == []
    # State unchanged
    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        state_after = ensure_execution_state(ao)
        for s in state_after.steps:
            assert s.status == ExecutionStepStatus.COMPLETED


# ═══════════════════════════════════════════════════════════════════════════════
# 3. RERUN_SAME_PARAMS => no invalidation, returns rerun_without_invalidation
# ═══════════════════════════════════════════════════════════════════════════════

def test_rerun_same_params_no_invalidation():
    log = [ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok")]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_state(ao)

        tele = RevisionDeltaTelemetry(
            detected=True,
            decision_preview=RevisionDeltaDecisionPreview.RERUN_SAME_PARAMS,
            rerun_signal_present=True,
            changed_keys=[],
            reason="same params rerun",
        )
        result = mgr.apply_revision_invalidation(ao, tele)

        assert result.decision == RevisionInvalidationDecision.RERUN_WITHOUT_INVALIDATION.value
        assert result.invalidated_step_indices == []
        # No steps invalidated
        state_after = ensure_execution_state(ao)
        for s in state_after.steps:
            assert s.status == ExecutionStepStatus.COMPLETED


# ═══════════════════════════════════════════════════════════════════════════════
# 4. INSUFFICIENT_EVIDENCE => no mutation
# ═══════════════════════════════════════════════════════════════════════════════

def test_insufficient_evidence_no_mutation():
    log = [ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok")]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_state(ao)

        tele = RevisionDeltaTelemetry(
            detected=False,
            decision_preview=RevisionDeltaDecisionPreview.INSUFFICIENT_EVIDENCE,
            reason="no effective args",
        )
        result = mgr.apply_revision_invalidation(ao, tele)

        assert result.decision == RevisionInvalidationDecision.INSUFFICIENT_EVIDENCE.value
        assert result.invalidated_step_indices == []
        state_after = ensure_execution_state(ao)
        for s in state_after.steps:
            assert s.status == ExecutionStepStatus.COMPLETED


# ═══════════════════════════════════════════════════════════════════════════════
# 5. macro pollutant NOx -> CO2 telemetry invalidates macro + dispersion
# ═══════════════════════════════════════════════════════════════════════════════

def test_macro_pollutant_change_invalidates_macro_and_dispersion():
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok"),
        ToolCallRecord(turn=2, tool="calculate_dispersion", args_compact={"meteorology": "windy_neutral", "pollutant": "NOx"}, success=True, result_ref="d:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_state(ao)

        tele = RevisionDeltaTelemetry(
            detected=True,
            decision_preview=RevisionDeltaDecisionPreview.PARAM_DELTA_DOWNSTREAM,
            changed_keys=["pollutant"],
            would_invalidate_tools=["calculate_macro_emission", "calculate_dispersion"],
            would_invalidate_steps=True,
            proposed_tool="calculate_macro_emission",
            reason="pollutant changed",
        )
        result = mgr.apply_revision_invalidation(ao, tele)

        assert result.decision == RevisionInvalidationDecision.INVALIDATED.value
        assert "calculate_macro_emission" in result.invalidated_tools
        assert "calculate_dispersion" in result.invalidated_tools

        # Both steps should be INVALIDATED
        state_after = ensure_execution_state(ao)
        for s in state_after.steps:
            assert s.status == ExecutionStepStatus.INVALIDATED, f"{s.tool_name} should be INVALIDATED"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. macro invalidation clears macro and dispersion result_ref, stores stale_result_ref
# ═══════════════════════════════════════════════════════════════════════════════

def test_macro_invalidation_clears_result_refs_and_stores_stale():
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="macro_emission:e1", summary="ok"),
        ToolCallRecord(turn=2, tool="calculate_dispersion", args_compact={"meteorology": "windy_neutral", "pollutant": "NOx"}, success=True, result_ref="dispersion:d1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_state(ao)

        tele = RevisionDeltaTelemetry(
            detected=True,
            decision_preview=RevisionDeltaDecisionPreview.PARAM_DELTA_DOWNSTREAM,
            changed_keys=["pollutant"],
            would_invalidate_tools=["calculate_macro_emission", "calculate_dispersion"],
            would_invalidate_steps=True,
            proposed_tool="calculate_macro_emission",
        )
        result = mgr.apply_revision_invalidation(ao, tele)

        assert "macro_emission:e1" in result.cleared_result_refs
        assert "dispersion:d1" in result.cleared_result_refs

        state_after = ensure_execution_state(ao)
        for s in state_after.steps:
            assert s.result_ref is None, f"{s.tool_name} result_ref should be cleared"
            assert s.provenance.get("stale_result_ref") is not None, f"{s.tool_name} should have stale_result_ref"
            assert s.provenance.get("invalidated_reason") == RevisionDeltaDecisionPreview.PARAM_DELTA_DOWNSTREAM
            assert s.provenance.get("changed_keys") == ["pollutant"]
            assert s.provenance.get("previous_status") == "completed"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. macro invalidation moves chain_cursor to macro index
# ═══════════════════════════════════════════════════════════════════════════════

def test_macro_invalidation_moves_cursor_to_macro():
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok"),
        ToolCallRecord(turn=2, tool="calculate_dispersion", args_compact={"meteorology": "windy_neutral", "pollutant": "NOx"}, success=True, result_ref="d:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_state(ao)

        state_before = ensure_execution_state(ao)
        assert state_before.chain_cursor == 2  # both steps done

        tele = RevisionDeltaTelemetry(
            detected=True,
            decision_preview=RevisionDeltaDecisionPreview.PARAM_DELTA_DOWNSTREAM,
            changed_keys=["pollutant"],
            would_invalidate_tools=["calculate_macro_emission", "calculate_dispersion"],
            would_invalidate_steps=True,
            proposed_tool="calculate_macro_emission",
        )
        result = mgr.apply_revision_invalidation(ao, tele)

        assert result.previous_chain_cursor == 2
        assert result.new_chain_cursor == 0  # cursor moves to macro (index 0)
        state_after = ensure_execution_state(ao)
        assert state_after.chain_cursor == 0
        assert state_after.chain_status == "active"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. dispersion meteorology-only telemetry invalidates dispersion only
# ═══════════════════════════════════════════════════════════════════════════════

def test_dispersion_meteorology_only_invalidates_dispersion():
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok"),
        ToolCallRecord(turn=2, tool="calculate_dispersion", args_compact={"meteorology": "windy_neutral", "pollutant": "NOx"}, success=True, result_ref="d:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_state(ao)

        tele = RevisionDeltaTelemetry(
            detected=True,
            decision_preview=RevisionDeltaDecisionPreview.PARAM_DELTA_SELF,
            changed_keys=["meteorology"],
            would_invalidate_tools=["calculate_dispersion"],
            would_invalidate_steps=True,
            proposed_tool="calculate_dispersion",
            reason="meteorology changed",
        )
        result = mgr.apply_revision_invalidation(ao, tele)

        assert result.decision == RevisionInvalidationDecision.INVALIDATED.value
        assert "calculate_dispersion" in result.invalidated_tools
        assert "calculate_macro_emission" not in result.invalidated_tools


# ═══════════════════════════════════════════════════════════════════════════════
# 9. dispersion-only invalidation preserves macro COMPLETED and macro result_ref
# ═══════════════════════════════════════════════════════════════════════════════

def test_dispersion_only_invalidation_preserves_macro():
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="macro_emission:e1", summary="ok"),
        ToolCallRecord(turn=2, tool="calculate_dispersion", args_compact={"meteorology": "windy_neutral", "pollutant": "NOx"}, success=True, result_ref="dispersion:d1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_state(ao)

        tele = RevisionDeltaTelemetry(
            detected=True,
            decision_preview=RevisionDeltaDecisionPreview.PARAM_DELTA_SELF,
            changed_keys=["meteorology"],
            would_invalidate_tools=["calculate_dispersion"],
            would_invalidate_steps=True,
            proposed_tool="calculate_dispersion",
        )
        result = mgr.apply_revision_invalidation(ao, tele)

        assert "calculate_macro_emission" in result.preserved_tools
        assert "macro_emission:e1" in result.preserved_result_refs

        state_after = ensure_execution_state(ao)
        macro_step = state_after.steps[0]
        assert macro_step.tool_name == "calculate_macro_emission"
        assert macro_step.status == ExecutionStepStatus.COMPLETED
        assert macro_step.result_ref == "macro_emission:e1"

        dispersion_step = state_after.steps[1]
        assert dispersion_step.tool_name == "calculate_dispersion"
        assert dispersion_step.status == ExecutionStepStatus.INVALIDATED
        assert dispersion_step.result_ref is None
        assert dispersion_step.provenance.get("stale_result_ref") == "dispersion:d1"


# ═══════════════════════════════════════════════════════════════════════════════
# 10. query model_year change invalidates query step only
# ═══════════════════════════════════════════════════════════════════════════════

def test_query_model_year_change_invalidates_query_only():
    log = [ToolCallRecord(turn=1, tool="query_emission_factors", args_compact={"model_year": 2020, "vehicle_type": "LDV"}, success=True, result_ref="q:1", summary="ok")]
    ao = _make_ao(projected_chain=["query_emission_factors"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_state(ao)

        tele = RevisionDeltaTelemetry(
            detected=True,
            decision_preview=RevisionDeltaDecisionPreview.PARAM_DELTA_SELF,
            changed_keys=["model_year"],
            would_invalidate_tools=["query_emission_factors"],
            would_invalidate_steps=True,
            proposed_tool="query_emission_factors",
        )
        result = mgr.apply_revision_invalidation(ao, tele)

        assert result.decision == RevisionInvalidationDecision.INVALIDATED.value
        assert result.invalidated_tools == ["query_emission_factors"]
        state_after = ensure_execution_state(ao)
        step = state_after.steps[0]
        assert step.status == ExecutionStepStatus.INVALIDATED
        assert step.result_ref is None
        assert step.provenance.get("stale_result_ref") == "q:1"


# ═══════════════════════════════════════════════════════════════════════════════
# 11. data source delta invalidates all listed tools
# ═══════════════════════════════════════════════════════════════════════════════

def test_data_source_delta_invalidates_all_listed():
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"file_path": "/tmp/a.csv", "pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok"),
        ToolCallRecord(turn=2, tool="calculate_dispersion", args_compact={"meteorology": "windy_neutral", "pollutant": "NOx"}, success=True, result_ref="d:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_state(ao)

        tele = RevisionDeltaTelemetry(
            detected=True,
            decision_preview=RevisionDeltaDecisionPreview.DATA_SOURCE_DELTA_ALL,
            changed_keys=["file_path"],
            would_invalidate_tools=["calculate_macro_emission", "calculate_dispersion"],
            would_invalidate_steps=True,
            proposed_tool="calculate_macro_emission",
        )
        result = mgr.apply_revision_invalidation(ao, tele)

        assert result.decision == RevisionInvalidationDecision.INVALIDATED.value
        assert "calculate_macro_emission" in result.invalidated_tools
        assert "calculate_dispersion" in result.invalidated_tools
        state_after = ensure_execution_state(ao)
        for s in state_after.steps:
            assert s.status == ExecutionStepStatus.INVALIDATED


# ═══════════════════════════════════════════════════════════════════════════════
# 12. multi-pollutant expansion returns insufficient/noop and does not mutate
# ═══════════════════════════════════════════════════════════════════════════════

def test_multi_pollutant_expansion_returns_insufficient_no_mutation():
    log = [ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": ("NOx",)}, success=True, result_ref="e:1", summary="ok")]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_state(ao)

        tele = RevisionDeltaTelemetry(
            detected=True,
            decision_preview=RevisionDeltaDecisionPreview.PARAM_DELTA_DOWNSTREAM,
            changed_keys=["pollutant"],
            would_invalidate_tools=["calculate_macro_emission", "calculate_dispersion"],
            would_invalidate_steps=True,
            scope_expansion_detected=True,
            proposed_tool="calculate_macro_emission",
            reason="multi-pollutant expansion",
        )
        result = mgr.apply_revision_invalidation(ao, tele)

        assert result.decision == RevisionInvalidationDecision.INSUFFICIENT_EVIDENCE.value
        assert "scope_expansion_deferred" in result.reason

        # No state mutation — steps that had result_refs keep them
        state_after = ensure_execution_state(ao)
        for s in state_after.steps:
            assert s.status == ExecutionStepStatus.COMPLETED, f"{s.tool_name} should not be mutated"
        # Macro step specifically should still have its result_ref
        macro_step = state_after.steps[0]
        assert macro_step.result_ref == "e:1"


# ═══════════════════════════════════════════════════════════════════════════════
# 13. revision_epoch increments exactly once per invalidation application
# ═══════════════════════════════════════════════════════════════════════════════

def test_revision_epoch_increments_exactly_once():
    log = [ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok")]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_state(ao)

        state_before = ensure_execution_state(ao)
        assert state_before.revision_epoch == 0

        tele = RevisionDeltaTelemetry(
            detected=True,
            decision_preview=RevisionDeltaDecisionPreview.PARAM_DELTA_DOWNSTREAM,
            changed_keys=["pollutant"],
            would_invalidate_tools=["calculate_macro_emission", "calculate_dispersion"],
            would_invalidate_steps=True,
            proposed_tool="calculate_macro_emission",
        )
        result = mgr.apply_revision_invalidation(ao, tele)

        assert result.revision_epoch == 1
        state_after = ensure_execution_state(ao)
        assert state_after.revision_epoch == 1
        for s in state_after.steps:
            if s.status == ExecutionStepStatus.INVALIDATED:
                assert s.revision_epoch == 1, f"step {s.tool_name} revision_epoch should be 1"


# ═══════════════════════════════════════════════════════════════════════════════
# 14. applying same invalidation twice is idempotent (returns NOOP)
# ═══════════════════════════════════════════════════════════════════════════════

def test_same_invalidation_twice_is_idempotent():
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok"),
        ToolCallRecord(turn=2, tool="calculate_dispersion", args_compact={"meteorology": "windy_neutral", "pollutant": "NOx"}, success=True, result_ref="d:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    tele = RevisionDeltaTelemetry(
        detected=True,
        decision_preview=RevisionDeltaDecisionPreview.PARAM_DELTA_DOWNSTREAM,
        changed_keys=["pollutant"],
        would_invalidate_tools=["calculate_macro_emission", "calculate_dispersion"],
        would_invalidate_steps=True,
        proposed_tool="calculate_macro_emission",
    )

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_state(ao)

        r1 = mgr.apply_revision_invalidation(ao, tele)
        assert r1.decision == RevisionInvalidationDecision.INVALIDATED.value
        assert r1.revision_epoch == 1

        # Second application with same telemetry
        r2 = mgr.apply_revision_invalidation(ao, tele)
        assert r2.decision == RevisionInvalidationDecision.NOOP.value
        assert "already INVALIDATED" in r2.reason
        assert r2.revision_epoch == 1  # epoch unchanged

        # State unchanged by second application
        state_after = ensure_execution_state(ao)
        assert state_after.revision_epoch == 1
        for s in state_after.steps:
            assert s.status == ExecutionStepStatus.INVALIDATED


# ═══════════════════════════════════════════════════════════════════════════════
# 15. tool_call_log is not appended or modified
# ═══════════════════════════════════════════════════════════════════════════════

def test_tool_call_log_not_modified():
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_state(ao)

        log_before = list(ao.tool_call_log)

        tele = RevisionDeltaTelemetry(
            detected=True,
            decision_preview=RevisionDeltaDecisionPreview.PARAM_DELTA_DOWNSTREAM,
            changed_keys=["pollutant"],
            would_invalidate_tools=["calculate_macro_emission", "calculate_dispersion"],
            would_invalidate_steps=True,
            proposed_tool="calculate_macro_emission",
        )
        mgr.apply_revision_invalidation(ao, tele)

        log_after = list(ao.tool_call_log)
        assert len(log_after) == len(log_before)
        for i in range(len(log_before)):
            assert log_after[i].tool == log_before[i].tool
            assert log_after[i].args_compact == log_before[i].args_compact
            assert log_after[i].result_ref == log_before[i].result_ref


# ═══════════════════════════════════════════════════════════════════════════════
# 16. ExecutionContinuation is not modified
# ═══════════════════════════════════════════════════════════════════════════════

def test_execution_continuation_not_modified():
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)

    # Set up an ExecutionContinuation on the AO
    cont = ExecutionContinuation(
        pending_next_tool="calculate_dispersion",
    )
    ao.execution_continuation = cont

    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_state(ao)

        tele = RevisionDeltaTelemetry(
            detected=True,
            decision_preview=RevisionDeltaDecisionPreview.PARAM_DELTA_DOWNSTREAM,
            changed_keys=["pollutant"],
            would_invalidate_tools=["calculate_macro_emission", "calculate_dispersion"],
            would_invalidate_steps=True,
            proposed_tool="calculate_macro_emission",
        )
        mgr.apply_revision_invalidation(ao, tele)

        # ExecutionContinuation unchanged
        assert ao.execution_continuation.pending_next_tool == "calculate_dispersion"


# ═══════════════════════════════════════════════════════════════════════════════
# 17. pending_next_tool after macro invalidation derives macro
# ═══════════════════════════════════════════════════════════════════════════════

def test_pending_next_tool_after_macro_invalidation_derives_macro():
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok"),
        ToolCallRecord(turn=2, tool="calculate_dispersion", args_compact={"meteorology": "windy_neutral", "pollutant": "NOx"}, success=True, result_ref="d:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_state(ao)

        tele = RevisionDeltaTelemetry(
            detected=True,
            decision_preview=RevisionDeltaDecisionPreview.PARAM_DELTA_DOWNSTREAM,
            changed_keys=["pollutant"],
            would_invalidate_tools=["calculate_macro_emission", "calculate_dispersion"],
            would_invalidate_steps=True,
            proposed_tool="calculate_macro_emission",
        )
        mgr.apply_revision_invalidation(ao, tele)

        state = ensure_execution_state(ao)
        # Cursor at 0 points to macro (the earliest invalidated step)
        assert state.chain_cursor == 0
        assert state.steps[0].tool_name == "calculate_macro_emission"
        assert state.steps[0].status == ExecutionStepStatus.INVALIDATED


# ═══════════════════════════════════════════════════════════════════════════════
# 18. pending_next_tool after dispersion-only invalidation derives dispersion
# ═══════════════════════════════════════════════════════════════════════════════

def test_pending_next_tool_after_dispersion_only_invalidation_derives_dispersion():
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok"),
        ToolCallRecord(turn=2, tool="calculate_dispersion", args_compact={"meteorology": "windy_neutral", "pollutant": "NOx"}, success=True, result_ref="d:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        _setup_state(ao)

        tele = RevisionDeltaTelemetry(
            detected=True,
            decision_preview=RevisionDeltaDecisionPreview.PARAM_DELTA_SELF,
            changed_keys=["meteorology"],
            would_invalidate_tools=["calculate_dispersion"],
            would_invalidate_steps=True,
            proposed_tool="calculate_dispersion",
        )
        mgr.apply_revision_invalidation(ao, tele)

        state = ensure_execution_state(ao)
        assert state.chain_cursor == 1  # macro at 0 stays COMPLETED, cursor at dispersion
        assert state.steps[0].tool_name == "calculate_macro_emission"
        assert state.steps[0].status == ExecutionStepStatus.COMPLETED
        assert state.steps[1].tool_name == "calculate_dispersion"
        assert state.steps[1].status == ExecutionStepStatus.INVALIDATED
