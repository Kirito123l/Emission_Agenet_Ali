"""Unit tests for Phase 5.3 Round 3.5 — PARAMETER_COLLECTION stance guard in SRC.

Verifies that active PARAMETER_COLLECTION causes the StanceResolutionContract
to resolve short parameter-value messages as DIRECTIVE instead of preserving
a stale EXPLORATORY stance.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.analytical_objective import ConversationalStance, StanceConfidence
from core.contracts.base import ContractContext
from core.contracts.stance_resolution_contract import StanceResolutionContract
from core.execution_continuation import ExecutionContinuation, PendingObjective


# ── Helpers ──────────────────────────────────────────────────────────────


def _ao_with_stance(stance=ConversationalStance.EXPLORATORY, confidence=StanceConfidence.LOW):
    """Create a minimal AO-like object with stance fields."""
    ao = SimpleNamespace()
    ao.stance = stance
    ao.stance_confidence = confidence
    ao.stance_resolved_by = "default"
    ao.stance_history = []
    ao.metadata = {}
    ao.tool_intent = None
    return ao


def _fake_classification(value="continuation"):
    """Create a minimal classification object."""
    inner = SimpleNamespace()
    inner.value = value
    outer = SimpleNamespace()
    outer.classification = inner
    return outer


def _make_src():
    """Create a minimal SRC with runtime_config enabled and ao_manager set up."""
    src = StanceResolutionContract()
    src.inner_router = None
    src.runtime_config = SimpleNamespace(
        enable_contract_split=True,
        enable_split_stance_contract=True,
    )
    src.ao_manager = SimpleNamespace()
    return src


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.anyio
class TestSRCParameterCollectionGuard:
    """SRC continuation branch upgrades to DIRECTIVE when PARAMETER_COLLECTION is active."""

    async def test_active_parameter_collection_pm10_gets_directive(self):
        """Active PARAMETER_COLLECTION + 'PM10' -> DIRECTIVE."""
        src = _make_src()
        ao = _ao_with_stance(ConversationalStance.EXPLORATORY, StanceConfidence.LOW)
        continuation = ExecutionContinuation(
            pending_objective=PendingObjective.PARAMETER_COLLECTION,
            pending_slot="pollutants",
        )
        ao.metadata["execution_continuation"] = continuation.to_dict()
        src.ao_manager.get_current_ao = lambda: ao

        ctx = ContractContext(
            user_message="PM10", file_path=None, trace=None,
            metadata={"oasc": {"classification": _fake_classification("continuation")}},
        )

        with patch.object(src.stance_resolver, 'detect_reversal', return_value=None):
            await src.before_turn(ctx)

        assert ctx.metadata["stance"]["stance"] == "directive"
        assert ctx.metadata["stance"]["resolved_by"] == "continuation_state:parameter_collection"
        assert not ctx.metadata["stance"]["reversal_detected"]

    async def test_active_parameter_collection_2020_gets_directive(self):
        """Active PARAMETER_COLLECTION + '2020年' -> DIRECTIVE."""
        src = _make_src()
        ao = _ao_with_stance(ConversationalStance.EXPLORATORY, StanceConfidence.LOW)
        continuation = ExecutionContinuation(
            pending_objective=PendingObjective.PARAMETER_COLLECTION,
            pending_slot="model_year",
        )
        ao.metadata["execution_continuation"] = continuation.to_dict()
        src.ao_manager.get_current_ao = lambda: ao

        ctx = ContractContext(
            user_message="2020年", file_path=None, trace=None,
            metadata={"oasc": {"classification": _fake_classification("continuation")}},
        )

        with patch.object(src.stance_resolver, 'detect_reversal', return_value=None):
            await src.before_turn(ctx)

        assert ctx.metadata["stance"]["stance"] == "directive"
        assert ctx.metadata["stance"]["resolved_by"] == "continuation_state:parameter_collection"

    async def test_no_parameter_collection_exploratory_preserved(self):
        """No active PARAMETER_COLLECTION + exploratory -> stance preserved (no change)."""
        src = _make_src()
        ao = _ao_with_stance(ConversationalStance.EXPLORATORY, StanceConfidence.LOW)
        ao.metadata["execution_continuation"] = ExecutionContinuation(
            pending_objective=PendingObjective.NONE,
        ).to_dict()
        src.ao_manager.get_current_ao = lambda: ao

        ctx = ContractContext(
            user_message="有哪些排放因子？", file_path=None, trace=None,
            metadata={"oasc": {"classification": _fake_classification("continuation")}},
        )

        with patch.object(src.stance_resolver, 'detect_reversal', return_value=None):
            await src.before_turn(ctx)

        # Without PARAMETER_COLLECTION, preserves EXPLORATORY
        assert ctx.metadata["stance"]["stance"] == "exploratory"

    async def test_chain_continuation_unaffected(self):
        """CHAIN_CONTINUATION does NOT trigger the PARAMETER_COLLECTION guard."""
        src = _make_src()
        ao = _ao_with_stance(ConversationalStance.DELIBERATIVE, StanceConfidence.MEDIUM)
        continuation = ExecutionContinuation(
            pending_objective=PendingObjective.CHAIN_CONTINUATION,
            pending_next_tool="calculate_micro_emission",
        )
        ao.metadata["execution_continuation"] = continuation.to_dict()
        src.ao_manager.get_current_ao = lambda: ao

        ctx = ContractContext(
            user_message="继续计算微观排放", file_path=None, trace=None,
            metadata={"oasc": {"classification": _fake_classification("continuation")}},
        )

        with patch.object(src.stance_resolver, 'detect_reversal', return_value=None):
            await src.before_turn(ctx)

        # CHAIN_CONTINUATION: not affected, preserves DELIBERATIVE
        assert ctx.metadata["stance"]["stance"] == "deliberative"

    async def test_reversal_overrides_parameter_collection(self):
        """User reversal detected during PARAMETER_COLLECTION -> reversal wins."""
        src = _make_src()
        ao = _ao_with_stance(ConversationalStance.DIRECTIVE, StanceConfidence.HIGH)
        continuation = ExecutionContinuation(
            pending_objective=PendingObjective.PARAMETER_COLLECTION,
            pending_slot="pollutants",
        )
        ao.metadata["execution_continuation"] = continuation.to_dict()
        src.ao_manager.get_current_ao = lambda: ao

        ctx = ContractContext(
            user_message="不，我要查的是微观排放", file_path=None, trace=None,
            metadata={"oasc": {"classification": _fake_classification("continuation")}},
        )

        # Reversal detected before PARAMETER_COLLECTION check
        with patch.object(src.stance_resolver, 'detect_reversal', return_value=ConversationalStance.EXPLORATORY):
            with patch.object(src.stance_resolver, 'reversal_evidence', return_value="user_reversal"):
                await src.before_turn(ctx)

        assert ctx.metadata["stance"]["reversal_detected"]
        assert ctx.metadata["stance"]["stance"] == "exploratory"

    async def test_inactive_parameter_collection_preserves_previous_stance(self):
        """PARAMETER_COLLECTION pending_objective but NOT active (no pending_slot) -> no guard."""
        src = _make_src()
        ao = _ao_with_stance(ConversationalStance.EXPLORATORY, StanceConfidence.LOW)
        # PARAMETER_COLLECTION without pending_slot -> is_active() returns False
        continuation = ExecutionContinuation(
            pending_objective=PendingObjective.PARAMETER_COLLECTION,
            pending_slot=None,
        )
        ao.metadata["execution_continuation"] = continuation.to_dict()
        src.ao_manager.get_current_ao = lambda: ao

        ctx = ContractContext(
            user_message="PM10", file_path=None, trace=None,
            metadata={"oasc": {"classification": _fake_classification("continuation")}},
        )

        with patch.object(src.stance_resolver, 'detect_reversal', return_value=None):
            await src.before_turn(ctx)

        # Inactive -> guard doesn't fire -> preserves EXPLORATORY
        assert ctx.metadata["stance"]["stance"] == "exploratory"

    async def test_abandoned_parameter_collection_no_guard(self):
        """Abandoned PARAMETER_COLLECTION -> is_active() False -> no guard."""
        src = _make_src()
        ao = _ao_with_stance(ConversationalStance.EXPLORATORY, StanceConfidence.LOW)
        continuation = ExecutionContinuation(
            pending_objective=PendingObjective.PARAMETER_COLLECTION,
            pending_slot="pollutants",
            abandoned=True,
        )
        ao.metadata["execution_continuation"] = continuation.to_dict()
        src.ao_manager.get_current_ao = lambda: ao

        ctx = ContractContext(
            user_message="PM10", file_path=None, trace=None,
            metadata={"oasc": {"classification": _fake_classification("continuation")}},
        )

        with patch.object(src.stance_resolver, 'detect_reversal', return_value=None):
            await src.before_turn(ctx)

        # Abandoned -> is_active() False -> preserves EXPLORATORY
        assert ctx.metadata["stance"]["stance"] == "exploratory"
