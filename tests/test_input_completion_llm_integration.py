"""Integration tests for LLMReplyParser wiring in input_completion (A.3)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.input_completion import (
    InputCompletionDecisionType,
    InputCompletionOption,
    InputCompletionOptionType,
    InputCompletionParseResult,
    InputCompletionReasonCode,
    InputCompletionRequest,
    parse_input_completion_reply,
)
from core.reply_parser_llm import ParsedReply, ReplyDecision


def _make_request(**kwargs):
    return InputCompletionRequest(
        request_id=kwargs.get("request_id", "ic-test"),
        action_id=kwargs.get("action_id", "run_macro_emission"),
        reason_code=kwargs.get("reason_code", InputCompletionReasonCode.MISSING_REQUIRED_FIELD),
        reason_summary=kwargs.get("reason_summary", "need traffic_flow_vph"),
        missing_requirements=kwargs.get("missing_requirements", ["traffic_flow_vph"]),
        target_field=kwargs.get("target_field", "traffic_flow_vph"),
        options=kwargs.get("options", [
            InputCompletionOption(
                option_id="flow_uniform",
                option_type=InputCompletionOptionType.PROVIDE_UNIFORM_VALUE,
                label="统一流量值",
                description="为所有路段设置统一流量值",
            ),
            InputCompletionOption(
                option_id="flow_pause",
                option_type=InputCompletionOptionType.PAUSE,
                label="暂停",
                description="先不补",
            ),
        ]),
    )


def _base_llm_context(**overrides):
    ctx = {
        "tool_name": "run_macro_emission",
        "slot_name": "traffic_flow_vph",
        "candidate_values": ["统一流量值", "暂停"],  # option labels (calibration 2)
        "confirmed_params": {"pollutant": "CO2"},
        "agent_question": "请选择补救方式: 1. 统一流量值 2. 暂停",
        "constraint_violations": [],
    }
    ctx.update(overrides)
    return ctx


# ── flag off: behaviour identical to legacy regex ──────────────────────


@pytest.mark.asyncio
async def test_flag_off_uses_legacy_regex(monkeypatch):
    monkeypatch.setenv("ENABLE_LLM_USER_REPLY_PARSER", "false")
    from config import reset_config
    reset_config()

    request = _make_request()
    result = await parse_input_completion_reply(request, "全部设为1500")
    assert result.is_resolved is True
    assert result.decision.structured_payload.get("value") == 1500.0

    result2 = await parse_input_completion_reply(
        request, "暂停", llm_context=_base_llm_context(),
    )
    assert result2.is_resolved is True
    assert result2.decision.decision_type == InputCompletionDecisionType.PAUSE


# ── flag on with mock LLM ──────────────────────────────────────────────


def _mock_parser_returning(decision=ReplyDecision.CONFIRMED, slot_values=None, confidence=0.9):
    async def _parse(user_reply, context):
        return ParsedReply(
            decision=decision,
            slot_values=dict(slot_values or {}),
            confidence=confidence,
        )
    return _parse


@pytest.mark.asyncio
async def test_flag_on_llm_extracts_numeric_value(monkeypatch):
    """LLM parses '全部设成2000' → slot_values['traffic_flow_vph']='2000' → CONFIRMED."""
    monkeypatch.setenv("ENABLE_LLM_USER_REPLY_PARSER", "true")
    from config import reset_config
    reset_config()

    request = _make_request()
    context = _base_llm_context()

    with patch("core.reply_parser_llm.LLMReplyParser") as MockParser:
        instance = MockParser.return_value
        instance.parse = _mock_parser_returning(
            slot_values={"traffic_flow_vph": "2000"},
        )
        result = await parse_input_completion_reply(
            request, "全部设成2000", llm_context=context,
        )

    assert result.is_resolved is True
    assert result.decision.decision_type == InputCompletionDecisionType.SELECTED_OPTION
    assert result.decision.structured_payload.get("value") == 2000.0
    assert result.decision.structured_payload.get("mode") == "uniform_scalar"


@pytest.mark.asyncio
async def test_flag_on_llm_no_value_for_target_field_returns_ambiguous(monkeypatch):
    """LLM returns ParsedReply but no value for target_field → AMBIGUOUS (calibration 3)."""
    monkeypatch.setenv("ENABLE_LLM_USER_REPLY_PARSER", "true")
    from config import reset_config
    reset_config()

    request = _make_request()
    context = _base_llm_context()

    with patch("core.reply_parser_llm.LLMReplyParser") as MockParser:
        instance = MockParser.return_value
        instance.parse = _mock_parser_returning(
            decision=ReplyDecision.CONFIRMED,
            slot_values={},  # empty, no value for target_field
        )
        result = await parse_input_completion_reply(
            request, "好", llm_context=context,
        )

    assert result.is_resolved is False
    assert result.needs_retry is True
    # Must NOT be CONFIRMED regardless of LLM self-reported decision
    assert "LLM did not resolve" in (result.error_message or "")


@pytest.mark.asyncio
async def test_flag_on_llm_non_numeric_value_for_target_returns_ambiguous(monkeypatch):
    """LLM returns a value for target_field but it can't be numeric → AMBIGUOUS."""
    monkeypatch.setenv("ENABLE_LLM_USER_REPLY_PARSER", "true")
    from config import reset_config
    reset_config()

    request = _make_request()
    context = _base_llm_context()

    with patch("core.reply_parser_llm.LLMReplyParser") as MockParser:
        instance = MockParser.return_value
        instance.parse = _mock_parser_returning(
            slot_values={"traffic_flow_vph": "很多很多"},
        )
        result = await parse_input_completion_reply(
            request, "很多很多车", llm_context=context,
        )

    assert result.is_resolved is False
    assert result.needs_retry is True
    assert "could not be used as a uniform scalar" in (result.error_message or "")


# ── LLM failure → legacy fallback ──────────────────────────────────────


@pytest.mark.asyncio
async def test_flag_on_llm_returns_none_falls_back_to_legacy_regex(monkeypatch):
    """LLM fails (timeout/error) → Layer 4 legacy regex handles the reply."""
    monkeypatch.setenv("ENABLE_LLM_USER_REPLY_PARSER", "true")
    from config import reset_config
    reset_config()

    request = _make_request()
    context = _base_llm_context()

    with patch("core.reply_parser_llm.LLMReplyParser") as MockParser:
        instance = MockParser.return_value
        async def _fail(*args, **kwargs):
            return None
        instance.parse = _fail

        result = await parse_input_completion_reply(
            request, "全部设为1500", llm_context=context,
        )

    # Legacy regex should catch "1500" as numeric → uniform scalar
    assert result.is_resolved is True
    assert result.decision.structured_payload.get("value") == 1500.0


# ── LLM returns ParsedReply but slot_values is not a dict ──────────────


@pytest.mark.asyncio
async def test_flag_on_llm_non_dict_slot_values_returns_ambiguous(monkeypatch):
    monkeypatch.setenv("ENABLE_LLM_USER_REPLY_PARSER", "true")
    from config import reset_config
    reset_config()

    request = _make_request()
    context = _base_llm_context()

    # Manually construct a ParsedReply with non-dict slot_values
    bad = ParsedReply(
        decision=ReplyDecision.CONFIRMED,
        slot_values=None,  # not a dict
        confidence=0.8,
    )

    with patch("core.reply_parser_llm.LLMReplyParser") as MockParser:
        instance = MockParser.return_value
        async def _bad_slots(*args, **kwargs):
            return bad
        instance.parse = _bad_slots

        result = await parse_input_completion_reply(
            request, "1500", llm_context=context,
        )

    assert result.is_resolved is False
    assert result.needs_retry is True
