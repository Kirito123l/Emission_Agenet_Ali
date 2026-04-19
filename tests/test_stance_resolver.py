from types import SimpleNamespace

from config import reset_config
from core.analytical_objective import (
    AOStatus,
    AnalyticalObjective,
    ConversationalStance,
    StanceConfidence,
)
from core.stance_resolver import StanceResolver


def _resolver(**flags):
    runtime = SimpleNamespace(
        enable_conversational_stance=flags.get("enable_conversational_stance", True),
        enable_stance_llm_resolution=flags.get("enable_stance_llm_resolution", True),
        enable_stance_reversal_detection=flags.get("enable_stance_reversal_detection", True),
        stance_signals_path="",
    )
    return StanceResolver(signal_config={}, runtime_config=runtime)


def test_fast_path_resolves_directive_signal():
    reset_config()
    result = _resolver().resolve_fast("帮我查公交车CO2排放因子", None)

    assert result is not None
    assert result.stance == ConversationalStance.DIRECTIVE
    assert result.confidence == StanceConfidence.MEDIUM
    assert result.resolved_by == "rule:directive_signal"


def test_fast_path_resolves_deliberative_signal():
    result = _resolver().resolve_fast("我需要公交车CO2那类因子，先帮我确认参数", None)

    assert result is not None
    assert result.stance == ConversationalStance.DELIBERATIVE
    assert result.confidence == StanceConfidence.HIGH
    assert result.resolved_by == "rule:deliberative_signal"


def test_fast_path_resolves_exploratory_signal():
    result = _resolver().resolve_fast("看看这个数据能分析什么", None)

    assert result is not None
    assert result.stance == ConversationalStance.EXPLORATORY
    assert result.confidence == StanceConfidence.HIGH
    assert result.resolved_by == "rule:exploratory_signal"


def test_llm_hint_used_when_fast_path_misses():
    resolver = _resolver()
    fast = resolver.resolve_fast("随便看看", None)

    result = resolver.resolve_with_llm_hint(
        fast,
        {"value": "directive", "confidence": "high", "reasoning": "意图明确"},
    )

    assert fast is None
    assert result.stance == ConversationalStance.DIRECTIVE
    assert result.confidence == StanceConfidence.HIGH
    assert result.resolved_by == "llm_slot_filler"


def test_default_directive_when_no_fast_or_llm_signal():
    result = _resolver().resolve_with_llm_hint(
        _resolver().resolve_fast("没有任何信号", None),
        None,
    )

    assert result.stance == ConversationalStance.DIRECTIVE
    assert result.confidence == StanceConfidence.LOW
    assert result.resolved_by == "default_directive"


def test_reversal_detection_returns_deliberative_for_change_signal():
    result = _resolver().detect_reversal("等等，换成SUV", ConversationalStance.DIRECTIVE)

    assert result == ConversationalStance.DELIBERATIVE


def test_reversal_detection_ignores_plain_short_reply():
    result = _resolver().detect_reversal("2021", ConversationalStance.DIRECTIVE)

    assert result is None


def test_feature_flag_disabled_keeps_ao_stance_unknown():
    resolver = _resolver(enable_conversational_stance=False)
    ao = AnalyticalObjective(
        ao_id="AO#1",
        session_id="s",
        objective_text="查因子",
        status=AOStatus.ACTIVE,
        start_turn=1,
    )

    fast = resolver.resolve_fast("帮我查公交车CO2排放因子", ao)
    result = resolver.resolve_with_llm_hint(fast, {"value": "directive", "confidence": "high"})

    assert fast is None
    assert result.stance == ConversationalStance.UNKNOWN
    assert ao.stance == ConversationalStance.UNKNOWN


def test_llm_resolution_flag_disabled_ignores_llm_hint():
    resolver = _resolver(enable_stance_llm_resolution=False)

    result = resolver.resolve_with_llm_hint(
        resolver.resolve_fast("随便看看", None),
        {"value": "directive", "confidence": "high"},
    )

    assert result.stance == ConversationalStance.DIRECTIVE
    assert result.confidence == StanceConfidence.LOW
    assert result.resolved_by == "default_directive"


def test_reversal_detection_flag_disabled_returns_none():
    result = _resolver(enable_stance_reversal_detection=False).detect_reversal(
        "等等，换成SUV",
        ConversationalStance.DIRECTIVE,
    )

    assert result is None
