"""Unit tests for Phase 8.2.2 ablation flags and telemetry TraceStepType values."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from config import get_config, reset_config
from core.analytical_objective import AORelationship, AOStatus
from core.ao_classifier import AOClassification, AOClassType, OAScopeClassifier
from core.ao_manager import AOManager
from core.memory import FactMemory
from core.task_state import TaskState
from core.trace import TraceStepType


# ── Helpers ──────────────────────────────────────────────────────────────────

class AsyncMockLLM:
    def __init__(self, payload=None, error=None):
        self.payload = payload or {}
        self.error = error
        self.calls = []

    async def chat_json(self, *, messages, system=None, temperature=None):
        self.calls.append({"messages": messages, "system": system, "temperature": temperature})
        if self.error is not None:
            raise self.error
        return self.payload


def _make_classifier(llm_payload=None, llm_error=None):
    reset_config()
    config = get_config()
    memory = FactMemory(session_id="abl-session")
    manager = AOManager(memory)
    llm = AsyncMockLLM(payload=llm_payload, error=llm_error)
    classifier = OAScopeClassifier(manager, llm, config)
    return classifier, manager, memory, llm


# ── TraceStepType enum tests ─────────────────────────────────────────────────

def test_new_trace_step_types_exist():
    """Verify the 4 new ablation telemetry TraceStepType values are defined."""
    assert hasattr(TraceStepType, "AO_CLASSIFIER_FORCED_NEW_AO")
    assert hasattr(TraceStepType, "READINESS_GATING_SKIPPED")
    assert hasattr(TraceStepType, "CROSS_CONSTRAINT_CHECK_SKIPPED")
    assert hasattr(TraceStepType, "FAST_PATH_SKIPPED")

    assert TraceStepType.AO_CLASSIFIER_FORCED_NEW_AO.value == "ao_classifier_forced_new_ao"
    assert TraceStepType.READINESS_GATING_SKIPPED.value == "readiness_gating_skipped"
    assert TraceStepType.CROSS_CONSTRAINT_CHECK_SKIPPED.value == "cross_constraint_check_skipped"
    assert TraceStepType.FAST_PATH_SKIPPED.value == "fast_path_skipped"


def test_new_trace_steps_are_serializable():
    """All trace step type values must be plain strings (JSON-serializable)."""
    for st in (
        TraceStepType.AO_CLASSIFIER_FORCED_NEW_AO,
        TraceStepType.READINESS_GATING_SKIPPED,
        TraceStepType.CROSS_CONSTRAINT_CHECK_SKIPPED,
        TraceStepType.FAST_PATH_SKIPPED,
    ):
        assert isinstance(st.value, str)
        assert st.value  # non-empty


def test_existing_trace_steps_not_broken():
    """Verify existing trace step types still resolve correctly after additions."""
    assert TraceStepType.RECONCILER_INVOKED.value == "reconciler_invoked"
    assert TraceStepType.RECONCILER_PROCEED.value == "reconciler_proceed"
    assert TraceStepType.B_VALIDATOR_FILTER.value == "b_validator_filter"
    assert TraceStepType.PCM_ADVISORY_INJECTED.value == "pcm_advisory_injected"
    assert TraceStepType.PROJECTED_CHAIN_GENERATED.value == "projected_chain_generated"
    assert TraceStepType.CROSS_CONSTRAINT_VALIDATED.value == "cross_constraint_validated"
    assert TraceStepType.CROSS_CONSTRAINT_VIOLATION.value == "cross_constraint_violation"
    assert TraceStepType.CROSS_CONSTRAINT_WARNING.value == "cross_constraint_warning"


# ── ENABLE_AO_CLASSIFIER flag tests ──────────────────────────────────────────

@pytest.mark.anyio
async def test_ao_classifier_flag_true_uses_normal_pipeline(monkeypatch):
    """Default flag=true: classifier proceeds to rule layer (normal behavior)."""
    monkeypatch.setenv("ENABLE_AO_CLASSIFIER", "true")
    classifier, manager, _memory, _llm = _make_classifier()
    manager.create_ao("算排放", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState()
    state.active_input_completion = SimpleNamespace(request_id="r1")

    result = await classifier.classify("冬天", [], state)

    # Should hit the rule layer, NOT the disabled early-return
    assert result.classification == AOClassType.CONTINUATION
    assert result.layer == "rule"
    assert result.confidence != 1.0  # rule layer confidence, not forced 1.0


@pytest.mark.anyio
async def test_ao_classifier_flag_false_forces_new_ao(monkeypatch):
    """flag=false: classifier returns NEW_AO unconditionally with layer='disabled'."""
    monkeypatch.setenv("ENABLE_AO_CLASSIFIER", "false")
    classifier, manager, _memory, _llm = _make_classifier()
    manager.create_ao("算排放", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState()

    result = await classifier.classify("继续分析", [], state)

    assert result.classification == AOClassType.NEW_AO
    assert result.layer == "disabled"
    assert result.confidence == 1.0
    assert "ENABLE_AO_CLASSIFIER=false" in result.reasoning


@pytest.mark.anyio
async def test_ao_classifier_flag_false_does_not_call_llm(monkeypatch):
    """flag=false: the LLM layer2 is never invoked, saving inference cost."""
    monkeypatch.setenv("ENABLE_AO_CLASSIFIER", "false")
    llm_error = RuntimeError("LLM should not be called")
    classifier, manager, _memory, llm = _make_classifier(llm_error=llm_error)
    state = TaskState()

    # Should succeed without calling the LLM (early-return before layer2)
    result = await classifier.classify("继续分析", [], state)

    assert result.classification == AOClassType.NEW_AO
    assert result.layer == "disabled"
    assert len(llm.calls) == 0


@pytest.mark.anyio
async def test_ao_classifier_flag_false_ignores_rule_layer(monkeypatch):
    """flag=false: even if rule_layer1 would match, the master flag takes priority."""
    monkeypatch.setenv("ENABLE_AO_CLASSIFIER", "false")
    classifier, manager, _memory, _llm = _make_classifier()
    manager.create_ao("算排放", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState()
    state.active_input_completion = SimpleNamespace(request_id="r1")

    # Even with active_input_completion (which rule_layer1 would catch as CONTINUATION),
    # the master flag forces NEW_AO
    result = await classifier.classify("冬天", [], state)

    assert result.classification == AOClassType.NEW_AO
    assert result.layer == "disabled"


# ── ENABLE_CONVERSATION_FAST_PATH flag tests ─────────────────────────────────

def test_fast_path_config_flag_exists():
    """ENABLE_CONVERSATION_FAST_PATH flag is wired in config.py."""
    reset_config()
    config = get_config()
    assert hasattr(config, "enable_conversation_fast_path")
    # Default should be True for production
    assert config.enable_conversation_fast_path is True


def test_fast_path_config_flag_respects_env(monkeypatch):
    """ENABLE_CONVERSATION_FAST_PATH env var toggle works."""
    monkeypatch.setenv("ENABLE_CONVERSATION_FAST_PATH", "false")
    reset_config()
    config = get_config()
    assert config.enable_conversation_fast_path is False


# ── Config flag registration tests ──────────────────────────────────────────

def test_enable_ao_classifier_flag_exists():
    """ENABLE_AO_CLASSIFIER master flag is wired in config.py."""
    reset_config()
    config = get_config()
    assert hasattr(config, "enable_ao_classifier")
    assert config.enable_ao_classifier is True  # default


def test_enable_ao_classifier_flag_respects_env(monkeypatch):
    """ENABLE_AO_CLASSIFIER env var toggle works and defaults to true."""
    monkeypatch.setenv("ENABLE_AO_CLASSIFIER", "false")
    reset_config()
    config = get_config()
    assert config.enable_ao_classifier is False


def test_existing_flags_not_broken_by_additions():
    """Verify existing ablation-related flags still resolve after additions."""
    reset_config()
    config = get_config()
    assert hasattr(config, "enable_cross_constraint_validation")
    assert hasattr(config, "enable_readiness_gating")
    assert hasattr(config, "enable_conversation_fast_path")
    assert hasattr(config, "enable_ao_classifier_rule_layer")
    assert hasattr(config, "enable_ao_classifier_llm_layer")


def test_flag_default_values_preserve_production_behavior():
    """All new flags default to true — no production breakage on deploy."""
    reset_config()
    config = get_config()
    assert config.enable_ao_classifier is True
    assert config.enable_conversation_fast_path is True
    assert config.enable_readiness_gating is True
    assert config.enable_cross_constraint_validation is True


# ── Phase 8.2.2.C-1.2: CONTINUATION→NEW_AO override tests ─────────────────


def _make_contract(enable_override=True):
    """Create a minimal OASCContract for testing _apply_classification."""
    from types import SimpleNamespace
    from core.contracts.oasc_contract import OASCContract

    inner = SimpleNamespace()
    inner.memory = SimpleNamespace(turn_counter=0)

    memory = FactMemory(session_id="ct-override-test")
    manager = AOManager(memory)

    runtime = SimpleNamespace(
        enable_ao_classifier_llm_layer=False,
        enable_continuation_override=enable_override,
        enable_ao_aware_memory=True,
        enable_contract_split=False,
        enable_split_continuation_state=False,
    )

    contract = OASCContract.__new__(OASCContract)
    contract.inner_router = inner
    contract.ao_manager = manager
    contract.runtime_config = runtime
    return contract, manager


def _make_cls(class_type=AOClassType.CONTINUATION):
    """Create a minimal AOClassification."""
    return AOClassification(
        classification=class_type,
        target_ao_id=None,
        reference_ao_id=None,
        new_objective_text="test objective",
        confidence=0.85,
        reasoning="LLM classified as continuation",
        layer="llm",
    )


def test_continuation_override_flag_true_no_prior_ao_overrides_to_new_ao():
    """flag=true + CONTINUATION + current=None → classification overridden to NEW_AO."""
    contract, manager = _make_contract(enable_override=True)
    cls = _make_cls(AOClassType.CONTINUATION)
    assert manager.get_current_ao() is None

    contract._apply_classification(cls, "帮我计算排放")

    assert cls.classification == AOClassType.NEW_AO
    assert cls.layer == "continuation_overridden"
    assert "CONTINUATION→NEW_AO" in cls.reasoning
    assert cls.new_objective_text is not None
    # AO should NOT be created yet (happens in fall-through create_ao)
    current = manager.get_current_ao()
    assert current is not None
    assert current.objective_text == "test objective"


def test_continuation_override_flag_true_with_prior_ao_preserves_continuation():
    """flag=true + CONTINUATION + current!=None → keeps CONTINUATION (multi-turn)."""
    contract, manager = _make_contract(enable_override=True)
    manager.create_ao("算排放", AORelationship.INDEPENDENT, current_turn=1)
    assert manager.get_current_ao() is not None

    cls = _make_cls(AOClassType.CONTINUATION)
    contract._apply_classification(cls, "继续分析")

    assert cls.classification == AOClassType.CONTINUATION
    assert cls.layer == "llm"
    assert "CONTINUATION→NEW_AO" not in cls.reasoning


def test_continuation_override_flag_false_no_prior_ao_preserves_v1_behavior():
    """flag=false + CONTINUATION + current=None → keeps CONTINUATION (v1 silent AO)."""
    contract, manager = _make_contract(enable_override=False)
    assert manager.get_current_ao() is None

    cls = _make_cls(AOClassType.CONTINUATION)
    contract._apply_classification(cls, "帮我计算排放")

    assert cls.classification == AOClassType.CONTINUATION
    assert cls.layer == "llm"
    # v1: silent AO created inside the CONTINUATION branch
    current = manager.get_current_ao()
    assert current is not None


def test_continuation_override_not_triggered_for_new_ao_or_revision():
    """flag=true + NEW_AO/REVISION → override NOT triggered (only targets CONTINUATION)."""
    contract, manager = _make_contract(enable_override=True)
    assert manager.get_current_ao() is None

    cls_new = _make_cls(AOClassType.NEW_AO)
    cls_new.layer = "rule"
    contract._apply_classification(cls_new, "帮我计算排放")
    assert cls_new.classification == AOClassType.NEW_AO
    assert cls_new.layer == "rule"
    assert "CONTINUATION→NEW_AO" not in cls_new.reasoning

    cls_rev = _make_cls(AOClassType.REVISION)
    # REVISION requires a real target AO — create one first
    existing = manager.create_ao("原始分析任务", AORelationship.INDEPENDENT, current_turn=1)
    cls_rev.target_ao_id = existing.ao_id
    cls_rev.layer = "llm"
    contract._apply_classification(cls_rev, "修正一下")
    assert cls_rev.classification == AOClassType.REVISION
    assert cls_rev.layer == "llm"
