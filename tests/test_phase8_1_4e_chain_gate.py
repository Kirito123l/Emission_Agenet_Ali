"""Phase 8.1.4e — Chain-aware completion gating unit tests.

Covers 4 core scenarios:
  1. Full chain completion (macro → dispersion → hotspot over 3 turns)
  2. User revision mid-chain (revision overrides chain continuation)
  3. Single-step chain (AO completes normally after single tool)
  4. Max-turn stall limit (force-complete after MAX_CHAIN_STALL_TURNS)
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, "/home/kirito/Agent1/emission_agent")

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
from core.execution_continuation_utils import (
    load_execution_continuation,
    save_execution_continuation,
    build_chain_continuation,
)


def _mock_config(**overrides):
    cfg = MagicMock()
    cfg.enable_canonical_execution_state = bool(overrides.get("canonical", True))
    cfg.enable_execution_idempotency = bool(overrides.get("idempotency", False))
    cfg.enable_contract_split = bool(overrides.get("contract_split", False))
    cfg.enable_split_continuation_state = bool(overrides.get("split_continuation", True))
    cfg.enable_lifecycle_contract_alignment = bool(overrides.get("lifecycle_alignment", True))
    return cfg


def _make_ao(ao_id="AO#1", projected_chain=None, tool_call_log=None,
             status=AOStatus.ACTIVE, start_turn=1, relationship=AORelationship.INDEPENDENT):
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
        status=status,
        start_turn=start_turn,
        relationship=relationship,
        tool_intent=intent,
        tool_call_log=list(tool_call_log or []),
    )


def _make_manager(ao_list=None, current_idx=0):
    memory = MagicMock()
    memory.ao_history = list(ao_list or [])
    if ao_list and current_idx < len(ao_list):
        memory.current_ao_id = ao_list[current_idx].ao_id
    else:
        memory.current_ao_id = None
    memory.last_turn_index = 1
    memory._ao_counter = len(ao_list or [])
    memory.files_in_session = []
    memory.session_confirmed_parameters = {}
    return AOManager(memory)


def _add_tool_call(ao, tool_name, turn, success=True):
    ao.tool_call_log.append(ToolCallRecord(
        turn=turn,
        tool=tool_name,
        args_compact={"test": True},
        success=success,
        result_ref=f"{tool_name}:result",
        summary="ok",
    ))


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1: Full chain completion over multiple turns
# ═══════════════════════════════════════════════════════════════════════════════

@patch("config.get_config")
def test_full_chain_completion_over_turns(mock_get_config):
    """chain=[macro, dispersion, hotspot] — completes only after all 3 steps."""
    mock_get_config.return_value = _mock_config()

    ao = _make_ao("AO#1", projected_chain=[
        "calculate_macro_emission", "calculate_dispersion", "analyze_hotspots"
    ])
    mgr = _make_manager([ao])

    # Derive execution state
    state = ensure_execution_state(ao)
    assert state is not None
    assert len(state.steps) == 3
    assert state.pending_next_tool == "calculate_macro_emission"

    # Turn 1: macro executes
    _add_tool_call(ao, "calculate_macro_emission", turn=1)
    ao.metadata.pop("execution_state", None)  # clear cache for re-derive
    state = ensure_execution_state(ao)
    assert state.pending_next_tool == "calculate_dispersion"
    assert mgr.has_pending_chain_steps(ao) is True

    # Turn 2: dispersion executes
    _add_tool_call(ao, "calculate_dispersion", turn=2)
    ao.metadata.pop("execution_state", None)
    state = ensure_execution_state(ao)
    assert state.pending_next_tool == "analyze_hotspots"
    assert mgr.has_pending_chain_steps(ao) is True

    # Turn 3: hotspot executes — chain complete
    _add_tool_call(ao, "analyze_hotspots", turn=3)
    ao.metadata.pop("execution_state", None)
    state = ensure_execution_state(ao)
    assert state.pending_next_tool is None
    assert state.is_chain_complete is True
    assert mgr.has_pending_chain_steps(ao) is False


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2: User revision mid-chain
# ═══════════════════════════════════════════════════════════════════════════════

@patch("config.get_config")
def test_revision_mid_chain_yields_to_new_ao(mock_get_config):
    """When create_ao is called with an ACTIVE AO that has pending chain steps,
    the old AO should be completed (not blocked by chain continuation)."""
    mock_get_config.return_value = _mock_config(contract_split=True)

    ao = _make_ao("AO#1", projected_chain=[
        "calculate_macro_emission", "calculate_dispersion"
    ])
    mgr = _make_manager([ao])

    # Write chain continuation (as _refresh_split_execution_continuation would)
    cont = build_chain_continuation(
        ["calculate_macro_emission", "calculate_dispersion"],
        current_tool="calculate_macro_emission",
        updated_turn=1,
    )
    save_execution_continuation(ao, cont)
    assert load_execution_continuation(ao).is_active() is True
    assert load_execution_continuation(ao).pending_objective == PendingObjective.CHAIN_CONTINUATION

    # Now simulate revision: create_ao creates a new REVISION AO
    new_ao = mgr.create_ao(
        objective_text="revised: change season to winter",
        relationship=AORelationship.REVISION,
        parent_ao_id=ao.ao_id,
        current_turn=2,
    )

    # Old AO should be COMPLETED (chain continuation yielded to revision)
    assert ao.status == AOStatus.COMPLETED
    assert ao.end_turn is not None

    # New REVISION AO should be ACTIVE
    assert new_ao.status == AOStatus.ACTIVE
    assert new_ao.relationship == AORelationship.REVISION
    assert new_ao.parent_ao_id == ao.ao_id

    # New AO has fresh execution state (not inherited from old AO)
    new_state = ensure_execution_state(new_ao)
    assert new_state is not None
    assert new_state.planned_chain == []  # fresh AO, no chain yet


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3: Single-step chain completes normally
# ═══════════════════════════════════════════════════════════════════════════════

@patch("config.get_config")
def test_single_step_chain_completes_normally(mock_get_config):
    """chain=[factor_query] — after execution, has_pending_chain_steps=False."""
    mock_get_config.return_value = _mock_config()

    ao = _make_ao("AO#1", projected_chain=["query_emission_factors"])
    mgr = _make_manager([ao])

    state = ensure_execution_state(ao)
    assert state.pending_next_tool == "query_emission_factors"
    assert mgr.has_pending_chain_steps(ao) is True  # pending BEFORE execution

    # Execute the single tool
    _add_tool_call(ao, "query_emission_factors", turn=1)

    # Re-derive: chain complete, no pending steps
    ao.metadata.pop("execution_state", None)  # clear cache
    state = ensure_execution_state(ao)
    assert state.pending_next_tool is None
    assert state.is_chain_complete is True
    assert mgr.has_pending_chain_steps(ao) is False


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4: Max-turn stall limit triggers force-complete
# ═══════════════════════════════════════════════════════════════════════════════

@patch("config.get_config")
def test_max_stall_turns_force_complete(mock_get_config):
    """After MAX_CHAIN_STALL_TURNS=5 with no progress, active_turns_without_progress
    returns >= 5 and the gate should force-complete."""
    mock_get_config.return_value = _mock_config()

    ao = _make_ao("AO#1", projected_chain=[
        "calculate_macro_emission", "calculate_dispersion"
    ], start_turn=1)
    mgr = _make_manager([ao])

    # Turn 1: macro executes, chain has pending dispersion
    _add_tool_call(ao, "calculate_macro_emission", turn=1)
    state = ensure_execution_state(ao)
    assert state.pending_next_tool == "calculate_dispersion"
    assert mgr.has_pending_chain_steps(ao) is True

    # At turn 2 (1 turn after last progress): stalls < 5
    stalls = mgr.active_turns_without_progress(ao, current_turn=2)
    assert stalls == 1  # 2 - 1 = 1
    assert stalls < 5

    # At turn 5 (4 turns after last progress): stalls < 5
    stalls = mgr.active_turns_without_progress(ao, current_turn=5)
    assert stalls == 4  # 5 - 1 = 4
    assert stalls < 5

    # At turn 6 (5 turns after last progress): stalls >= 5
    stalls = mgr.active_turns_without_progress(ao, current_turn=6)
    assert stalls == 5  # 6 - 1 = 5
    assert stalls >= 5  # should trigger force-complete

    # At turn 10 (9 turns after last progress): well past limit
    stalls = mgr.active_turns_without_progress(ao, current_turn=10)
    assert stalls == 9
    assert stalls >= 5


# ═══════════════════════════════════════════════════════════════════════════════
# Edge case: has_pending_chain_steps when canonical state is disabled
# ═══════════════════════════════════════════════════════════════════════════════

@patch("config.get_config")
def test_has_pending_chain_steps_disabled(mock_get_config):
    """Returns False when canonical execution state feature flag is off."""
    mock_get_config.return_value = _mock_config(canonical=False)

    ao = _make_ao("AO#1", projected_chain=[
        "calculate_macro_emission", "calculate_dispersion"
    ])
    mgr = _make_manager([ao])

    assert mgr.has_pending_chain_steps(ao) is False


@patch("config.get_config")
def test_has_pending_chain_steps_no_state(mock_get_config):
    """Returns False when AO has no execution state (empty tool_intent)."""
    mock_get_config.return_value = _mock_config()

    ao = _make_ao("AO#1", projected_chain=[])  # no chain
    mgr = _make_manager([ao])

    assert mgr.has_pending_chain_steps(ao) is False


@patch("config.get_config")
def test_active_turns_without_progress_no_state(mock_get_config):
    """Returns 0 when canonical state is disabled."""
    mock_get_config.return_value = _mock_config(canonical=False)

    ao = _make_ao("AO#1", start_turn=1)
    mgr = _make_manager([ao])

    assert mgr.active_turns_without_progress(ao, current_turn=10) == 0
