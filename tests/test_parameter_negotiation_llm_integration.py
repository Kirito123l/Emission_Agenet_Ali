"""Integration tests for LLMReplyParser wiring in parameter_negotiation (A.2)."""

from __future__ import annotations

import asyncio
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from core.parameter_negotiation import (
    NegotiationCandidate,
    NegotiationDecisionType,
    ParameterNegotiationParseResult,
    ParameterNegotiationRequest,
    parse_parameter_negotiation_reply,
)
from core.reply_parser_llm import ParsedReply, ReplyDecision


def _make_request(**kwargs):
    return ParameterNegotiationRequest(
        request_id=kwargs.get("request_id", "neg-test"),
        parameter_name=kwargs.get("parameter_name", "vehicle_type"),
        raw_value=kwargs.get("raw_value", "飞机"),
        confidence=kwargs.get("confidence", 0.62),
        trigger_reason=kwargs.get("trigger_reason", "low_confidence_llm_match"),
        tool_name=kwargs.get("tool_name", "query_emission_factors"),
        candidates=kwargs.get("candidates", [
            NegotiationCandidate(
                index=1,
                normalized_value="Passenger Car",
                display_label="乘用车 (Passenger Car)",
                aliases=["乘用车", "小汽车"],
            ),
            NegotiationCandidate(
                index=2,
                normalized_value="Transit Bus",
                display_label="公交车 (Transit Bus)",
                aliases=["公交车", "巴士"],
            ),
        ]),
    )


def _base_llm_context(**overrides):
    ctx = {
        "tool_name": "query_emission_factors",
        "slot_name": "vehicle_type",
        "candidate_values": ["Passenger Car", "Transit Bus"],
        "confirmed_params": {"pollutant": "CO2"},
        "agent_question": "请确认车辆类型: 1. 乘用车 2. 公交车",
        "constraint_violations": [],
    }
    ctx.update(overrides)
    return ctx


# ── flag off: behaviour identical to legacy regex (no context passed) ──


@pytest.mark.asyncio
async def test_flag_off_uses_legacy_regex(monkeypatch):
    monkeypatch.setenv("ENABLE_LLM_USER_REPLY_PARSER", "false")
    from config import reset_config
    reset_config()

    request = _make_request()
    result = await parse_parameter_negotiation_reply(request, "1")
    assert result.is_resolved is True
    assert result.decision.decision_type == NegotiationDecisionType.CONFIRMED
    assert result.decision.selected_value == "Passenger Car"
    assert result.decision.source == "legacy_regex"
    # No LLM context passed — even if we passed one, flag off ignores it
    result2 = await parse_parameter_negotiation_reply(
        request, "都不对", llm_context=_base_llm_context(),
    )
    assert result2.is_resolved is True
    assert result2.decision.decision_type == NegotiationDecisionType.NONE_OF_ABOVE
    assert result2.decision.source == "legacy_regex"


# ── flag on with mock LLM: each ReplyDecision ────────────────────────────


def _mock_parser_returning(decision: ReplyDecision, slot_values=None, confidence=0.9, evidence=""):
    async def _parse(user_reply, context):
        return ParsedReply(
            decision=decision,
            slot_values=dict(slot_values or {}),
            confidence=confidence,
            evidence=evidence or f"mock {decision.value}",
        )
    return _parse


@pytest.mark.asyncio
async def test_flag_on_llm_confirmed_matches_candidate(monkeypatch):
    monkeypatch.setenv("ENABLE_LLM_USER_REPLY_PARSER", "true")
    from config import reset_config
    reset_config()

    request = _make_request()
    context = _base_llm_context()

    with patch("core.reply_parser_llm.LLMReplyParser") as MockParser:
        instance = MockParser.return_value
        instance.parse = _mock_parser_returning(
            ReplyDecision.CONFIRMED,
            slot_values={"vehicle_type": "小汽车"},
            confidence=0.92,
        )

        result = await parse_parameter_negotiation_reply(
            request, "小汽车", llm_context=context,
        )

    assert result is not None
    assert result.is_resolved is True
    assert result.decision.decision_type == NegotiationDecisionType.CONFIRMED
    assert result.decision.selected_value == "Passenger Car"  # matched via alias
    assert result.decision.selected_index == 1
    assert result.decision.source == "llm_parsed"


@pytest.mark.asyncio
async def test_flag_on_llm_none_of_above(monkeypatch):
    monkeypatch.setenv("ENABLE_LLM_USER_REPLY_PARSER", "true")
    from config import reset_config
    reset_config()

    request = _make_request()
    context = _base_llm_context()

    with patch("core.reply_parser_llm.LLMReplyParser") as MockParser:
        instance = MockParser.return_value
        instance.parse = _mock_parser_returning(
            ReplyDecision.NONE_OF_ABOVE,
            slot_values={},
        )

        result = await parse_parameter_negotiation_reply(
            request, "都不对，三蹦子", llm_context=context,
        )

    assert result.is_resolved is True
    assert result.decision.decision_type == NegotiationDecisionType.NONE_OF_ABOVE
    assert result.decision.source == "llm_parsed"


@pytest.mark.asyncio
async def test_flag_on_llm_ambiguous_reply(monkeypatch):
    monkeypatch.setenv("ENABLE_LLM_USER_REPLY_PARSER", "true")
    from config import reset_config
    reset_config()

    request = _make_request()
    context = _base_llm_context()

    with patch("core.reply_parser_llm.LLMReplyParser") as MockParser:
        instance = MockParser.return_value
        instance.parse = _mock_parser_returning(
            ReplyDecision.AMBIGUOUS_REPLY,
            slot_values={},
            confidence=0.3,
        )

        result = await parse_parameter_negotiation_reply(
            request, "嗯", llm_context=context,
        )

    assert result.is_resolved is False
    assert result.needs_retry is True


@pytest.mark.asyncio
async def test_flag_on_llm_partial_reply_with_target_param(monkeypatch):
    """PARTIAL_REPLY with the target parameter resolved → CONFIRMED."""
    monkeypatch.setenv("ENABLE_LLM_USER_REPLY_PARSER", "true")
    from config import reset_config
    reset_config()

    request = _make_request()
    context = _base_llm_context()

    with patch("core.reply_parser_llm.LLMReplyParser") as MockParser:
        instance = MockParser.return_value
        instance.parse = _mock_parser_returning(
            ReplyDecision.PARTIAL_REPLY,
            slot_values={"vehicle_type": "公交车", "other_param": "some_value"},
        )

        result = await parse_parameter_negotiation_reply(
            request, "公交车，其他随便", llm_context=context,
        )

    assert result.is_resolved is True
    assert result.decision.decision_type == NegotiationDecisionType.CONFIRMED
    assert result.decision.selected_value == "Transit Bus"
    assert result.decision.source == "llm_parsed"


@pytest.mark.asyncio
async def test_flag_on_llm_partial_reply_without_target_param(monkeypatch):
    """PARTIAL_REPLY without the target param → AMBIGUOUS_REPLY (calibration 2)."""
    monkeypatch.setenv("ENABLE_LLM_USER_REPLY_PARSER", "true")
    from config import reset_config
    reset_config()

    request = _make_request()
    context = _base_llm_context()

    with patch("core.reply_parser_llm.LLMReplyParser") as MockParser:
        instance = MockParser.return_value
        instance.parse = _mock_parser_returning(
            ReplyDecision.PARTIAL_REPLY,
            slot_values={"some_other_param": "value"},
        )

        result = await parse_parameter_negotiation_reply(
            request, "好的", llm_context=context,
        )

    assert result.is_resolved is False
    assert result.needs_retry is True


@pytest.mark.asyncio
async def test_flag_on_llm_pause(monkeypatch):
    """PAUSE → AMBIGUOUS_REPLY with needs_retry=False (calibration 3)."""
    monkeypatch.setenv("ENABLE_LLM_USER_REPLY_PARSER", "true")
    from config import reset_config
    reset_config()

    request = _make_request()
    context = _base_llm_context()

    with patch("core.reply_parser_llm.LLMReplyParser") as MockParser:
        instance = MockParser.return_value
        instance.parse = _mock_parser_returning(
            ReplyDecision.PAUSE,
            slot_values={},
        )

        result = await parse_parameter_negotiation_reply(
            request, "稍等", llm_context=context,
        )

    assert result.is_resolved is False
    assert result.needs_retry is False
    assert "暂停" in (result.error_message or "")


# ── LLM failure → legacy fallback ────────────────────────────────────────


@pytest.mark.asyncio
async def test_flag_on_llm_returns_none_falls_back_to_regex(monkeypatch):
    """LLM timeout/error → Layer 4 legacy regex."""
    monkeypatch.setenv("ENABLE_LLM_USER_REPLY_PARSER", "true")
    from config import reset_config
    reset_config()

    request = _make_request()
    context = _base_llm_context()

    with patch("core.reply_parser_llm.LLMReplyParser") as MockParser:
        instance = MockParser.return_value
        # LLM fails
        async def _fail(*args, **kwargs):
            return None
        instance.parse = _fail

        # "乘用车" is 3 chars (not >3), but not a digit or confirm/decline word,
        # so fast path returns None. LLM then fails, falling back to legacy regex
        # which matches "乘用车" as a label match.
        result = await parse_parameter_negotiation_reply(
            request, "乘用车", llm_context=context,
        )

    assert result is not None
    assert result.is_resolved is True
    assert result.decision.decision_type == NegotiationDecisionType.CONFIRMED
    assert result.decision.selected_value == "Passenger Car"
    assert result.decision.source == "legacy_regex"


# ── Calibration 4: LLM returns value that doesn't match any candidate ───


@pytest.mark.asyncio
async def test_flag_on_llm_value_no_candidate_match_returns_ambiguous(monkeypatch):
    """LLM parsed value that doesn't match candidates → AMBIGUOUS_REPLY.
    Must NOT fall through to legacy regex (calibration 4)."""
    monkeypatch.setenv("ENABLE_LLM_USER_REPLY_PARSER", "true")
    from config import reset_config
    reset_config()

    request = _make_request()
    context = _base_llm_context()

    with patch("core.reply_parser_llm.LLMReplyParser") as MockParser:
        instance = MockParser.return_value
        instance.parse = _mock_parser_returning(
            ReplyDecision.CONFIRMED,
            slot_values={"vehicle_type": "三轮车"},  # not in candidates
        )

        result = await parse_parameter_negotiation_reply(
            request, "三轮车", llm_context=context,
        )

    assert result.is_resolved is False
    assert result.needs_retry is True
    assert "did not match any candidate" in (result.error_message or "")
