"""Unit tests for core.reply_parser_llm (A.1 - Task Pack A Layer 2 parser).

Tests cover:
- 5 ReplyDecision outcomes via mock LLM
- Timeout -> None
- Bad JSON / missing fields -> None
- Prompt rendering: placeholder substitution, F2/F3 wording
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from core.reply_parser_llm import (
    LLMReplyParser,
    ParsedReply,
    ReplyDecision,
)


def _mock_llm_client(response_payload: Dict[str, Any]):
    """Return an async mock that returns *response_payload* from chat_json()."""
    mock = MagicMock()

    async def _chat_json(**kwargs) -> Dict[str, Any]:
        return dict(response_payload)

    mock.chat_json = _chat_json
    return mock


def _mock_llm_client_raising(exc: Exception):
    """Return an async mock whose chat_json() raises *exc*."""
    mock = MagicMock()

    async def _chat_json(**kwargs) -> Dict[str, Any]:
        raise exc

    mock.chat_json = _chat_json
    return mock


@pytest.fixture
def base_context() -> Dict[str, Any]:
    return {
        "tool_name": "calculate_macro_emission",
        "slot_name": "vehicle_type",
        "candidate_values": ["小汽车", "公交车", "货车", "摩托车", "SUV"],
        "confirmed_params": {"pollutant": "CO2", "road_type": "主干路"},
        "agent_question": "请问这是什么类型的车辆？常见的有：小汽车、公交车、货车、摩托车、SUV。",
        "constraint_violations": [
            {
                "violation_type": "cross_constraint_violation",
                "severity": "warn",
                "involved_params": {"vehicle_type": "重型货车", "road_type": "居民区道路"},
                "suggested_resolution": "重型货车通常不在居民区道路上行驶，请确认路段类型或调整车型。",
                "timestamp": "2026-04-28T10:00:00",
                "source_turn": 1,
            }
        ],
    }


# -- 5 decision-type tests --------------------------------------------------


@pytest.mark.asyncio
async def test_parse_confirmed(base_context):
    parser = LLMReplyParser(
        llm_client=_mock_llm_client({
            "decision": "confirmed",
            "slot_values": {"vehicle_type": "小汽车"},
            "confidence": 0.95,
            "evidence": "用户明确选择了候选值'小汽车'",
        }),
        timeout=5.0,
    )
    result = await parser.parse("小汽车", base_context)
    assert result is not None
    assert result.decision == ReplyDecision.CONFIRMED
    assert result.slot_values == {"vehicle_type": "小汽车"}
    assert result.confidence == 0.95
    assert "小汽车" in result.evidence


@pytest.mark.asyncio
async def test_parse_none_of_above(base_context):
    parser = LLMReplyParser(
        llm_client=_mock_llm_client({
            "decision": "none_of_above",
            "slot_values": {},
            "confidence": 0.90,
            "evidence": "用户明确表示'都不对'，拒绝全部候选",
        }),
        timeout=5.0,
    )
    result = await parser.parse("都不对，我要查的是三轮车", base_context)
    assert result is not None
    assert result.decision == ReplyDecision.NONE_OF_ABOVE
    assert result.slot_values == {}


@pytest.mark.asyncio
async def test_parse_partial_reply(base_context):
    parser = LLMReplyParser(
        llm_client=_mock_llm_client({
            "decision": "partial_reply",
            "slot_values": {"vehicle_type": "公交车"},
            "confidence": 0.65,
            "evidence": "用户选择了车型但未提供其他所需参数",
        }),
        timeout=5.0,
    )
    result = await parser.parse("公交车，其他的随便", base_context)
    assert result is not None
    assert result.decision == ReplyDecision.PARTIAL_REPLY
    assert result.slot_values == {"vehicle_type": "公交车"}


@pytest.mark.asyncio
async def test_parse_ambiguous_reply(base_context):
    parser = LLMReplyParser(
        llm_client=_mock_llm_client({
            "decision": "ambiguous_reply",
            "slot_values": {},
            "confidence": 0.30,
            "evidence": "用户仅回复'嗯好'，缺乏明确指代对象",
        }),
        timeout=5.0,
    )
    result = await parser.parse("嗯好", base_context)
    assert result is not None
    assert result.decision == ReplyDecision.AMBIGUOUS_REPLY
    assert result.slot_values == {}
    assert result.confidence <= 0.5


@pytest.mark.asyncio
async def test_parse_pause(base_context):
    parser = LLMReplyParser(
        llm_client=_mock_llm_client({
            "decision": "pause",
            "slot_values": {},
            "confidence": 0.92,
            "evidence": "用户表示'稍等，让我确认一下'，希望暂停",
        }),
        timeout=5.0,
    )
    result = await parser.parse("稍等，让我确认一下参数设置", base_context)
    assert result is not None
    assert result.decision == ReplyDecision.PAUSE


# -- failure-mode tests ------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_returns_none(base_context):
    parser = LLMReplyParser(
        llm_client=_mock_llm_client_raising(asyncio.TimeoutError()),
        timeout=0.1,
    )
    result = await parser.parse("小汽车", base_context)
    assert result is None


@pytest.mark.asyncio
async def test_bad_json_returns_none(base_context):
    mock = MagicMock()

    async def _chat_json(**kwargs) -> Dict[str, Any]:
        import json as _json
        raise _json.JSONDecodeError("bad", "{bad", 0)

    mock.chat_json = _chat_json
    parser = LLMReplyParser(llm_client=mock, timeout=5.0)
    result = await parser.parse("小汽车", base_context)
    assert result is None


@pytest.mark.asyncio
async def test_missing_decision_field_returns_none(base_context):
    parser = LLMReplyParser(
        llm_client=_mock_llm_client({
            "slot_values": {"vehicle_type": "小汽车"},
            "confidence": 0.9,
        }),
        timeout=5.0,
    )
    result = await parser.parse("小汽车", base_context)
    assert result is None


@pytest.mark.asyncio
async def test_invalid_decision_value_returns_none(base_context):
    parser = LLMReplyParser(
        llm_client=_mock_llm_client({
            "decision": "maybe_later",
            "slot_values": {},
            "confidence": 0.5,
            "evidence": "...",
        }),
        timeout=5.0,
    )
    result = await parser.parse("maybe", base_context)
    assert result is None


@pytest.mark.asyncio
async def test_non_dict_slot_values_normalizes_to_empty(base_context):
    parser = LLMReplyParser(
        llm_client=_mock_llm_client({
            "decision": "confirmed",
            "slot_values": ["小汽车"],
            "confidence": 0.8,
            "evidence": "user chose",
        }),
        timeout=5.0,
    )
    result = await parser.parse("小汽车", base_context)
    assert result is not None
    assert result.decision == ReplyDecision.CONFIRMED
    assert result.slot_values == {}


@pytest.mark.asyncio
async def test_confidence_clamped(base_context):
    parser = LLMReplyParser(
        llm_client=_mock_llm_client({
            "decision": "confirmed",
            "slot_values": {"x": "y"},
            "confidence": 2.5,
            "evidence": "x",
        }),
        timeout=5.0,
    )
    result = await parser.parse("x", base_context)
    assert result is not None
    assert result.confidence == 1.0

    parser2 = LLMReplyParser(
        llm_client=_mock_llm_client({
            "decision": "confirmed",
            "slot_values": {"x": "y"},
            "confidence": -0.3,
            "evidence": "x",
        }),
        timeout=5.0,
    )
    result2 = await parser2.parse("x", base_context)
    assert result2 is not None
    assert result2.confidence == 0.0


@pytest.mark.asyncio
async def test_cancelled_error_propagates(base_context):
    """asyncio.CancelledError must propagate, not be swallowed (F6)."""
    parser = LLMReplyParser(
        llm_client=_mock_llm_client_raising(asyncio.CancelledError()),
        timeout=5.0,
    )
    with pytest.raises(asyncio.CancelledError):
        await parser.parse("小汽车", base_context)


@pytest.mark.asyncio
async def test_needs_confirmation_not_auto_set(base_context):
    """F1: needs_confirmation defaults to False regardless of confidence."""
    parser = LLMReplyParser(
        llm_client=_mock_llm_client({
            "decision": "confirmed",
            "slot_values": {"vehicle_type": "小汽车"},
            "confidence": 0.45,
            "evidence": "用户回复模糊但勉强判为 confirmed",
        }),
        timeout=5.0,
    )
    result = await parser.parse("好像是小汽车吧", base_context)
    assert result is not None
    assert result.needs_confirmation is False
    assert result.confidence == 0.45


# -- prompt rendering tests --------------------------------------------------


class TestPromptRendering:
    @staticmethod
    def _parser():
        return LLMReplyParser(
            llm_client=_mock_llm_client({
                "decision": "confirmed",
                "slot_values": {},
                "confidence": 1.0,
                "evidence": "",
            }),
        )

    def test_placeholder_substitution(self, base_context):
        rendered = self._parser()._render_prompt("小汽车", base_context)
        assert "小汽车" in rendered
        assert "calculate_macro_emission" in rendered
        assert "vehicle_type" in rendered
        assert "主干路" in rendered
        assert '"小汽车"' in rendered

    def test_f3_candidate_values_label_present(self, base_context):
        rendered = self._parser()._render_prompt("小汽车", base_context)
        assert "唯一可选" in rendered or "候选合法值" in rendered

    def test_f2_constraint_violations_label_present(self, base_context):
        rendered = self._parser()._render_prompt("小汽车", base_context)
        assert "仅供参考" in rendered or "非规则" in rendered

    def test_empty_confirmed_params_renders_empty_json(self):
        ctx: Dict[str, Any] = {
            "tool_name": "t", "slot_name": "s",
            "candidate_values": [], "confirmed_params": {},
            "agent_question": "q?", "constraint_violations": [],
        }
        rendered = self._parser()._render_prompt("x", ctx)
        assert "{}" in rendered

    def test_empty_violations_renders_empty_json(self):
        ctx: Dict[str, Any] = {
            "tool_name": "t", "slot_name": "s",
            "candidate_values": [], "confirmed_params": {},
            "agent_question": "q?", "constraint_violations": [],
        }
        rendered = self._parser()._render_prompt("x", ctx)
        assert "[]" in rendered


# -- smoke: enum / dataclass / construction defaults ------------------------


def test_reply_decision_enum_values():
    assert ReplyDecision.CONFIRMED.value == "confirmed"
    assert ReplyDecision.NONE_OF_ABOVE.value == "none_of_above"
    assert ReplyDecision.PARTIAL_REPLY.value == "partial_reply"
    assert ReplyDecision.AMBIGUOUS_REPLY.value == "ambiguous_reply"
    assert ReplyDecision.PAUSE.value == "pause"
    assert len(ReplyDecision) == 5


def test_parsed_reply_defaults():
    pr = ParsedReply(decision=ReplyDecision.CONFIRMED)
    assert pr.slot_values == {}
    assert pr.confidence == 0.0
    assert pr.evidence == ""
    assert pr.needs_confirmation is False


def test_default_timeout():
    parser = LLMReplyParser()
    assert parser.timeout == 5.0


def test_custom_timeout():
    parser = LLMReplyParser(timeout=3.0)
    assert parser.timeout == 3.0
