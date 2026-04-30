"""Unit tests for Phase 5.3 Round 3.6 Fix 1 — projected_chain persistence guard.

Verifies _persist_tool_intent preserves existing multi-step projected_chain
against empty or single-step degradation.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.contracts.clarification_contract import ClarificationContract


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_contract():
    contract = ClarificationContract.__new__(ClarificationContract)
    contract.ao_manager = None
    contract.inner_router = None
    contract.runtime_config = SimpleNamespace(
        enable_contract_split=True,
        enable_first_class_state=True,
    )
    contract._first_class_state_enabled = lambda: True
    return contract


def _ao_with_chain(chain=None):
    """Create an AO-like object with tool_intent having projected_chain."""
    tool_intent = SimpleNamespace()
    tool_intent.resolved_tool = "calculate_macro_emission"
    tool_intent.confidence = None
    tool_intent.evidence = []
    tool_intent.resolved_at_turn = None
    tool_intent.resolved_by = None
    tool_intent.projected_chain = list(chain) if chain else []
    ao = SimpleNamespace()
    ao.tool_intent = tool_intent
    return ao


def _tool_intent_with_chain(chain=None, resolved_tool="calculate_macro_emission"):
    """Create a tool_intent-like object."""
    ti = SimpleNamespace()
    ti.resolved_tool = resolved_tool
    ti.confidence = SimpleNamespace()
    ti.confidence.value = "high"
    ti.evidence = ["test"]
    ti.resolved_at_turn = 1
    ti.resolved_by = "test"
    ti.projected_chain = list(chain) if chain else []
    return ti


# ── Tests ────────────────────────────────────────────────────────────────


class TestProjectedChainPersistence:
    """Fix 1: _persist_tool_intent preserves multi-step chains against degradation."""

    def test_empty_new_does_not_erase_existing_multi_step(self):
        """existing ["A","B"] + new [] => keeps ["A","B"]."""
        contract = _make_contract()
        ao = _ao_with_chain(["calculate_macro_emission", "calculate_dispersion"])
        new_ti = _tool_intent_with_chain([])
        contract._persist_tool_intent(ao, new_ti)
        assert ao.tool_intent.projected_chain == ["calculate_macro_emission", "calculate_dispersion"]

    def test_single_step_new_does_not_degrade_multi_step_existing(self):
        """existing ["A","B"] + new ["A"] => keeps ["A","B"]."""
        contract = _make_contract()
        ao = _ao_with_chain(["calculate_macro_emission", "calculate_dispersion"])
        new_ti = _tool_intent_with_chain(["calculate_macro_emission"])
        contract._persist_tool_intent(ao, new_ti)
        assert ao.tool_intent.projected_chain == ["calculate_macro_emission", "calculate_dispersion"]

    def test_valid_downstream_advancement_accepted(self):
        """existing ["A","B"] + new ["B"] => allows ["B"] (downstream advancement)."""
        contract = _make_contract()
        ao = _ao_with_chain(["calculate_macro_emission", "calculate_dispersion"])
        new_ti = _tool_intent_with_chain(["calculate_dispersion"], resolved_tool="calculate_dispersion")
        contract._persist_tool_intent(ao, new_ti)
        assert ao.tool_intent.projected_chain == ["calculate_dispersion"]

    def test_unrelated_single_tool_does_not_overwrite_multi_step(self):
        """existing ["A","B"] + new ["X"] => keeps ["A","B"]."""
        contract = _make_contract()
        ao = _ao_with_chain(["calculate_macro_emission", "calculate_dispersion"])
        new_ti = _tool_intent_with_chain(["query_emission_factors"])
        contract._persist_tool_intent(ao, new_ti)
        assert ao.tool_intent.projected_chain == ["calculate_macro_emission", "calculate_dispersion"]

    def test_empty_existing_accepts_new_chain(self):
        """existing [] + new ["A","B"] => accepts ["A","B"]."""
        contract = _make_contract()
        ao = _ao_with_chain([])
        new_ti = _tool_intent_with_chain(["calculate_macro_emission", "calculate_dispersion"])
        contract._persist_tool_intent(ao, new_ti)
        assert ao.tool_intent.projected_chain == ["calculate_macro_emission", "calculate_dispersion"]

    def test_more_informative_new_chain_accepted(self):
        """existing ["A","B"] + new ["A","B","C"] => accepts ["A","B","C"]."""
        contract = _make_contract()
        ao = _ao_with_chain(["calculate_macro_emission", "calculate_dispersion"])
        new_ti = _tool_intent_with_chain(
            ["calculate_macro_emission", "calculate_dispersion", "analyze_hotspots"]
        )
        contract._persist_tool_intent(ao, new_ti)
        assert ao.tool_intent.projected_chain == [
            "calculate_macro_emission", "calculate_dispersion", "analyze_hotspots"
        ]

    def test_identical_chain_accepted(self):
        """existing ["A","B"] + new ["A","B"] => accepts (identical)."""
        contract = _make_contract()
        ao = _ao_with_chain(["calculate_macro_emission", "calculate_dispersion"])
        new_ti = _tool_intent_with_chain(["calculate_macro_emission", "calculate_dispersion"])
        contract._persist_tool_intent(ao, new_ti)
        assert ao.tool_intent.projected_chain == ["calculate_macro_emission", "calculate_dispersion"]

    def test_none_ao_safe(self):
        """None AO does not crash."""
        contract = _make_contract()
        new_ti = _tool_intent_with_chain(["A", "B"])
        contract._persist_tool_intent(None, new_ti)  # should not raise

    def test_ao_without_tool_intent_safe(self):
        """AO without tool_intent does not crash."""
        contract = _make_contract()
        ao = SimpleNamespace()
        new_ti = _tool_intent_with_chain(["A", "B"])
        contract._persist_tool_intent(ao, new_ti)  # should not raise

    def test_single_step_existing_accepts_empty_new(self):
        """existing ["A"] + new [] => accepts [] (single-step not protected)."""
        contract = _make_contract()
        ao = _ao_with_chain(["calculate_macro_emission"])
        new_ti = _tool_intent_with_chain([])
        contract._persist_tool_intent(ao, new_ti)
        # Single-step existing is not protected — only multi-step (>1)
        assert ao.tool_intent.projected_chain == ["calculate_macro_emission"]
