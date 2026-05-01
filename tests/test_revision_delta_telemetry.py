"""Phase 6.E.4A — Revision delta telemetry tests.

Read-only: no AOExecutionState mutation, no result_ref clearing, no chain_cursor
movement, no execution behavior change.
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
    ToolCallRecord,
    ToolIntent,
)
from core.ao_manager import AOManager, ensure_execution_state


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


# ═══════════════════════════════════════════════════════════════════════════════
# 1. flag false => no telemetry
# ═══════════════════════════════════════════════════════════════════════════════

def test_flag_false_no_telemetry():
    log = [ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok")]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=False)):
        result = mgr.detect_revision_delta_telemetry(
            ao, proposed_tool="calculate_macro_emission",
            proposed_args={"pollutant": "CO2"},
        )
    assert result.detected is False
    assert "flag disabled" in result.reason


# ═══════════════════════════════════════════════════════════════════════════════
# 2. canonical state disabled => no telemetry
# ═══════════════════════════════════════════════════════════════════════════════

def test_canonical_disabled_no_telemetry():
    log = [ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok")]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=False, revision=True)):
        result = mgr.detect_revision_delta_telemetry(
            ao, proposed_tool="calculate_macro_emission",
            proposed_args={"pollutant": "CO2"},
        )
    assert result.detected is False
    assert "flag disabled" in result.reason


# ═══════════════════════════════════════════════════════════════════════════════
# 3. same params + no rerun => NO_DELTA
# ═══════════════════════════════════════════════════════════════════════════════

def test_same_params_no_rerun_no_delta():
    log = [ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok")]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        result = mgr.detect_revision_delta_telemetry(
            ao, proposed_tool="calculate_macro_emission",
            proposed_args={"pollutant": "NOx"},
        )
    assert result.decision_preview == RevisionDeltaDecisionPreview.NO_DELTA
    assert result.changed_keys == []
    assert result.would_invalidate_steps is False


# ═══════════════════════════════════════════════════════════════════════════════
# 4. same params + rerun cue => RERUN_SAME_PARAMS
# ═══════════════════════════════════════════════════════════════════════════════

def test_same_params_rerun_cue_rerun_same_params():
    log = [ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok")]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        result = mgr.detect_revision_delta_telemetry(
            ao, proposed_tool="calculate_macro_emission",
            proposed_args={"pollutant": "NOx"},
            user_message="重新算一遍",
        )
    assert result.decision_preview == RevisionDeltaDecisionPreview.RERUN_SAME_PARAMS
    assert result.rerun_signal_present is True
    assert result.changed_keys == []
    assert result.would_invalidate_steps is False


# ═══════════════════════════════════════════════════════════════════════════════
# 5. macro pollutant NOx -> CO2 => would invalidate macro + dispersion
# ═══════════════════════════════════════════════════════════════════════════════

def test_pollutant_change_invalidates_macro_and_dispersion():
    log = [ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok")]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        result = mgr.detect_revision_delta_telemetry(
            ao, proposed_tool="calculate_macro_emission",
            proposed_args={"pollutant": "CO2"},
        )
    assert "pollutant" in result.changed_keys
    assert result.decision_preview == RevisionDeltaDecisionPreview.PARAM_DELTA_DOWNSTREAM
    assert "calculate_macro_emission" in result.would_invalidate_tools
    assert "calculate_dispersion" in result.would_invalidate_tools
    assert result.would_invalidate_steps is True


# ═══════════════════════════════════════════════════════════════════════════════
# 6. dispersion meteorology change => would invalidate dispersion only
# ═══════════════════════════════════════════════════════════════════════════════

def test_meteorology_change_invalidates_dispersion_only():
    """Dispersion meteorology change: previous dispersion already has same pollutant as proposed."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok"),
        ToolCallRecord(turn=2, tool="calculate_dispersion", args_compact={"meteorology": "windy_neutral", "pollutant": "NOx"}, success=True, result_ref="d:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        result = mgr.detect_revision_delta_telemetry(
            ao, proposed_tool="calculate_dispersion",
            proposed_args={"meteorology": "urban_summer_day", "pollutant": "NOx"},
        )
    assert "meteorology" in result.changed_keys
    assert "pollutant" not in result.changed_keys  # pollutant unchanged between prev and proposed
    assert result.decision_preview == RevisionDeltaDecisionPreview.PARAM_DELTA_SELF
    assert "calculate_dispersion" in result.would_invalidate_tools
    assert "calculate_macro_emission" not in result.would_invalidate_tools


# ═══════════════════════════════════════════════════════════════════════════════
# 7. query_emission_factors model_year 2020 -> 2021 => would invalidate query
# ═══════════════════════════════════════════════════════════════════════════════

def test_model_year_change_invalidates_query():
    log = [ToolCallRecord(turn=1, tool="query_emission_factors", args_compact={"model_year": 2020, "vehicle_type": "LDV"}, success=True, result_ref="q:1", summary="ok")]
    ao = _make_ao(projected_chain=["query_emission_factors"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        result = mgr.detect_revision_delta_telemetry(
            ao, proposed_tool="query_emission_factors",
            proposed_args={"model_year": 2021, "vehicle_type": "LDV"},
        )
    assert "model_year" in result.changed_keys
    assert result.decision_preview == RevisionDeltaDecisionPreview.PARAM_DELTA_SELF
    assert "query_emission_factors" in result.would_invalidate_tools
    assert result.would_invalidate_steps is True


# ═══════════════════════════════════════════════════════════════════════════════
# 8. file_path/data source change => would invalidate all relevant steps
# ═══════════════════════════════════════════════════════════════════════════════

def test_file_path_change_invalidates_all():
    log = [ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"file_path": "/tmp/a.csv", "pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok")]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        result = mgr.detect_revision_delta_telemetry(
            ao, proposed_tool="calculate_macro_emission",
            proposed_args={"file_path": "/tmp/b.csv", "pollutant": "NOx"},
        )
    assert "file_path" in result.changed_keys
    assert result.decision_preview == RevisionDeltaDecisionPreview.DATA_SOURCE_DELTA_ALL
    assert result.would_invalidate_steps is True


# ═══════════════════════════════════════════════════════════════════════════════
# 9. multi-pollutant expansion NOx -> NOx+CO2 => scope_expansion detected
# ═══════════════════════════════════════════════════════════════════════════════

def test_multi_pollutant_expansion_scope_expansion():
    log = [ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": ("NOx",)}, success=True, result_ref="e:1", summary="ok")]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        result = mgr.detect_revision_delta_telemetry(
            ao, proposed_tool="calculate_macro_emission",
            proposed_args={"pollutant": ["NOx", "CO2"]},  # list form as executor would pass
        )
    assert "pollutant" in result.changed_keys
    assert result.scope_expansion_detected is True
    assert result.decision_preview == RevisionDeltaDecisionPreview.PARAM_DELTA_DOWNSTREAM
    # Observed but no behavior change — read-only telemetry


# ═══════════════════════════════════════════════════════════════════════════════
# 10. missing effective args => INSUFFICIENT_EVIDENCE
# ═══════════════════════════════════════════════════════════════════════════════

def test_missing_effective_args_insufficient_evidence():
    # AO with no prior tool calls and no effective_args in steps
    ao = _make_ao(projected_chain=["calculate_macro_emission"])
    mgr = _make_manager([ao])
    # Manually set empty effective_args on the step to simulate no evidence
    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        state = ensure_execution_state(ao)
        state.steps[0].effective_args = {}
        ao.metadata["execution_state"] = state.to_dict()
        result = mgr.detect_revision_delta_telemetry(
            ao, proposed_tool="calculate_macro_emission",
            proposed_args={},
        )
    # Both proposed and previous have no effective args — insufficient evidence
    assert result.decision_preview == RevisionDeltaDecisionPreview.INSUFFICIENT_EVIDENCE


# ═══════════════════════════════════════════════════════════════════════════════
# 11. transitive dependents use tool graph when available
# ═══════════════════════════════════════════════════════════════════════════════

def test_transitive_dependents_from_tool_graph():
    """Verify _preview_transitive_dependents uses tool_contracts when available."""
    from core.ao_manager import _preview_transitive_dependents
    # The real tool graph has calculate_dispersion requiring emission
    # which calculate_macro_emission provides
    result = _preview_transitive_dependents(
        ["calculate_macro_emission", "calculate_dispersion", "analyze_hotspots", "render_spatial_map"],
        "calculate_macro_emission",
    )
    # At minimum, calculate_dispersion should be a dependent
    assert "calculate_dispersion" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 12. fallback linear-chain dependency preview when graph unavailable
# ═══════════════════════════════════════════════════════════════════════════════

def test_fallback_linear_chain_when_graph_unavailable():
    """When tool_graph is unavailable, fall back to linear chain order."""
    from core.ao_manager import _preview_transitive_dependents
    with patch("tools.contract_loader.get_tool_contract_registry", side_effect=ImportError):
        result = _preview_transitive_dependents(
            ["calculate_macro_emission", "calculate_dispersion", "analyze_hotspots"],
            "calculate_macro_emission",
        )
    assert "calculate_dispersion" in result
    assert "analyze_hotspots" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 13. no AOExecutionState mutation
# ═══════════════════════════════════════════════════════════════════════════════

def test_no_execution_state_mutation():
    """detect_revision_delta_telemetry must NOT mutate AOExecutionState."""
    log = [ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok")]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        # Snapshot state before
        state_before = ensure_execution_state(ao)
        assert state_before is not None
        steps_before = [(s.tool_name, s.status) for s in state_before.steps]
        cursor_before = state_before.chain_cursor

        result = mgr.detect_revision_delta_telemetry(
            ao, proposed_tool="calculate_macro_emission",
            proposed_args={"pollutant": "CO2"},
        )

        # State after should be identical
        state_after = ensure_execution_state(ao)
        steps_after = [(s.tool_name, s.status) for s in state_after.steps]
        cursor_after = state_after.chain_cursor

    assert result.detected is True  # delta IS detected
    assert steps_before == steps_after
    assert cursor_before == cursor_after
    for s in state_after.steps:
        if s.status == ExecutionStepStatus.COMPLETED:
            assert s.result_ref is not None  # result_ref NOT cleared


# ═══════════════════════════════════════════════════════════════════════════════
# 14. chain_cursor unchanged
# ═══════════════════════════════════════════════════════════════════════════════

def test_chain_cursor_unchanged():
    log = [ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok")]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        state = ensure_execution_state(ao)
        assert state.chain_cursor == 1  # macro completed, cursor at dispersion
        cursor_before = state.chain_cursor

        mgr.detect_revision_delta_telemetry(
            ao, proposed_tool="calculate_macro_emission",
            proposed_args={"pollutant": "CO2"},
        )

        state_after = ensure_execution_state(ao)
        assert state_after.chain_cursor == cursor_before  # unchanged


# ═══════════════════════════════════════════════════════════════════════════════
# 15. result_ref unchanged
# ═══════════════════════════════════════════════════════════════════════════════

def test_result_ref_unchanged():
    log = [ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="macro_emission:baseline", summary="ok")]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        state = ensure_execution_state(ao)
        ref_before = state.steps[0].result_ref
        assert ref_before == "macro_emission:baseline"

        mgr.detect_revision_delta_telemetry(
            ao, proposed_tool="calculate_macro_emission",
            proposed_args={"pollutant": "CO2"},
        )

        state_after = ensure_execution_state(ao)
        assert state_after.steps[0].result_ref == ref_before  # unchanged


# ═══════════════════════════════════════════════════════════════════════════════
# 16. dispersion meteorology-only change => invalidate dispersion only
# ═══════════════════════════════════════════════════════════════════════════════

def test_dispersion_meteorology_only_delta():
    """When only meteorology changes in dispersion and pollutant matches, only
    dispersion should be in the would_invalidate set."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok"),
        ToolCallRecord(turn=2, tool="calculate_dispersion", args_compact={"meteorology": "windy_neutral", "pollutant": "NOx"}, success=True, result_ref="d:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        result = mgr.detect_revision_delta_telemetry(
            ao, proposed_tool="calculate_dispersion",
            proposed_args={"meteorology": "N2", "pollutant": "NOx"},
        )
    assert result.changed_keys == ["meteorology"]  # only meteorology changed
    assert "pollutant" not in result.changed_keys
    assert "calculate_dispersion" in result.would_invalidate_tools
    assert "calculate_macro_emission" not in result.would_invalidate_tools
    assert result.decision_preview == RevisionDeltaDecisionPreview.PARAM_DELTA_SELF


# ═══════════════════════════════════════════════════════════════════════════════
# 17. dispersion pollutant change (NOx → CO2) with macro coupled upstream
# ═══════════════════════════════════════════════════════════════════════════════

def test_dispersion_pollutant_change_upstream_coupling():
    """When dispersion's pollutant changes from NOx to CO2, and macro was
    computed with NOx, telemetry detects the delta.  The would_invalidate set
    includes dispersion.  Whether macro should also be invalidated depends on
    upstream coupling — for now, telemetry records the delta on dispersion
    and marks PARAM_DELTA_SELF (dispersion-only).  Upstream coupling is a
    Phase 6.E.4B decision."""
    log = [
        ToolCallRecord(turn=1, tool="calculate_macro_emission", args_compact={"pollutant": "NOx"}, success=True, result_ref="e:1", summary="ok"),
        ToolCallRecord(turn=2, tool="calculate_dispersion", args_compact={"meteorology": "windy_neutral", "pollutant": "NOx"}, success=True, result_ref="d:1", summary="ok"),
    ]
    ao = _make_ao(projected_chain=["calculate_macro_emission", "calculate_dispersion"], tool_call_log=log)
    mgr = _make_manager([ao])

    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        result = mgr.detect_revision_delta_telemetry(
            ao, proposed_tool="calculate_dispersion",
            proposed_args={"meteorology": "windy_neutral", "pollutant": "CO2"},
        )
    assert "pollutant" in result.changed_keys
    assert result.detected is True
    # Telemetry records the delta.  In 6.E.4A this is read-only.
    # Whether macro must also be invalidated (because macro output is NOx
    # but dispersion now wants CO2) is deferred to 6.E.4B invalidation engine.
    assert result.would_invalidate_steps is True
