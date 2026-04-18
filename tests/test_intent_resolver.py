from types import SimpleNamespace

from config import get_config, reset_config
from core.analytical_objective import (
    AORelationship,
    AOStatus,
    AnalyticalObjective,
    IntentConfidence,
    ToolCallRecord,
)
from core.intent_resolver import IntentResolver


class FakeRouter:
    def __init__(self, hints):
        self._hints = hints
        self.memory = SimpleNamespace(fact_memory=SimpleNamespace(ao_history=[]))

    def _extract_message_execution_hints(self, _state):
        return dict(self._hints)


def test_fast_path_resolves_strict_factor_intent():
    reset_config()
    resolver = IntentResolver(FakeRouter({"wants_factor": True}), None)
    ao = AnalyticalObjective(
        ao_id="AO#1",
        session_id="s",
        objective_text="帮我查询公交车排放因子",
        status=AOStatus.ACTIVE,
        start_turn=1,
    )

    intent = resolver.resolve_fast(SimpleNamespace(turn_index=1), ao)

    assert intent.resolved_tool == "query_emission_factors"
    assert intent.confidence == IntentConfidence.HIGH
    assert intent.resolved_by == "rule:wants_factor_strict"


def test_llm_hint_resolves_factor_phrase_when_fast_misses():
    reset_config()
    resolver = IntentResolver(FakeRouter({"wants_factor": False, "desired_tool_chain": []}), None)
    ao = AnalyticalObjective(
        ao_id="AO#1",
        session_id="s",
        objective_text="我需要公交车CO2那类因子，先帮我确认参数",
        status=AOStatus.ACTIVE,
        start_turn=1,
    )

    intent = resolver.resolve_with_llm_hint(
        SimpleNamespace(turn_index=1),
        ao,
        {
            "resolved_tool": "query_emission_factors",
            "intent_confidence": "high",
            "reasoning": "因子查询意图明确",
        },
    )

    assert intent.resolved_tool == "query_emission_factors"
    assert intent.confidence == IntentConfidence.HIGH
    assert intent.resolved_by == "llm_slot_filler"


def test_no_signal_returns_none():
    reset_config()
    resolver = IntentResolver(FakeRouter({"wants_factor": False, "desired_tool_chain": []}), None)
    ao = AnalyticalObjective(
        ao_id="AO#1",
        session_id="s",
        objective_text="今天天气真好",
        status=AOStatus.ACTIVE,
        start_turn=1,
    )

    intent = resolver.resolve_with_llm_hint(SimpleNamespace(turn_index=1), ao, None)

    assert intent.resolved_tool is None
    assert intent.confidence == IntentConfidence.NONE


def test_llm_intent_resolution_flag_can_disable_fallback():
    reset_config()
    config = get_config()
    config.enable_llm_intent_resolution = False
    resolver = IntentResolver(FakeRouter({"wants_factor": False, "desired_tool_chain": []}), None)
    ao = AnalyticalObjective(
        ao_id="AO#1",
        session_id="s",
        objective_text="我需要公交车CO2那类因子，先帮我确认参数",
        status=AOStatus.ACTIVE,
        start_turn=1,
    )

    intent = resolver.resolve_with_llm_hint(
        SimpleNamespace(turn_index=1),
        ao,
        {"resolved_tool": "query_emission_factors", "intent_confidence": "high"},
    )

    assert intent.resolved_tool is None
    assert intent.confidence == IntentConfidence.NONE


def test_revision_parent_fast_path_uses_parent_success_tool():
    reset_config()
    parent = AnalyticalObjective(
        ao_id="AO#1",
        session_id="s",
        objective_text="查因子",
        status=AOStatus.COMPLETED,
        start_turn=1,
    )
    parent.tool_call_log.append(
        ToolCallRecord(
            turn=1,
            tool="query_emission_factors",
            args_compact={},
            success=True,
            result_ref="emission_factors:baseline",
            summary="ok",
        )
    )
    child = AnalyticalObjective(
        ao_id="AO#2",
        session_id="s",
        objective_text="改成冬季",
        status=AOStatus.REVISING,
        start_turn=2,
        relationship=AORelationship.REVISION,
        parent_ao_id=parent.ao_id,
    )
    router = FakeRouter({"wants_factor": False, "desired_tool_chain": []})
    router.memory.fact_memory.ao_history = [parent, child]
    resolver = IntentResolver(router, None)

    intent = resolver.resolve_fast(SimpleNamespace(turn_index=2), child)

    assert intent.resolved_tool == "query_emission_factors"
    assert intent.confidence == IntentConfidence.HIGH
    assert intent.resolved_by == "rule:revision_parent"
