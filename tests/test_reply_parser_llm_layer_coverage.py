"""LLM Layer coverage unit tests for edge-case inputs (Phase 5.1 Stage 2.6).

5 tests validating LLMReplyParser behaviour on inputs where Layer 1 (fast path)
would not fire and standardizer may not help — colloquial phrasing, multi-slot,
ambiguous referent-less replies, and F2/F3 prompt wording verification.

All tests mock the LLM client; no real API calls.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from core.reply_parser_llm import LLMReplyParser, ParsedReply, ReplyDecision


# ── mock helpers (extended from tests/test_reply_parser_llm.py) ──────────

def _mock_llm_client(response_payload: Dict[str, Any]):
    """Return an async mock whose chat_json() returns *response_payload*."""
    mock = MagicMock()

    async def _chat_json(**kwargs) -> Dict[str, Any]:
        return dict(response_payload)

    mock.chat_json = _chat_json
    return mock


def _mock_llm_client_capture(response_payload: Dict[str, Any], capture: Dict[str, Any]):
    """Return an async mock whose chat_json() returns *response_payload* and
    captures the ``messages`` and ``system`` kwargs into *capture*."""
    mock = MagicMock()

    async def _chat_json(**kwargs) -> Dict[str, Any]:
        capture["messages"] = kwargs.get("messages", [])
        capture["system"] = kwargs.get("system", "")
        return dict(response_payload)

    mock.chat_json = _chat_json
    return mock


# ── Test 1: 高度模糊 colloquial 输入 ─────────────────────────────────────

@pytest.mark.asyncio
async def test_edge_case_colloquial_input():
    """'那个三轮的吧' with English candidates → CONFIRMED, F1 confidence preserved."""
    context: Dict[str, Any] = {
        "tool_name": "calculate_macro_emission",
        "slot_name": "vehicle_type",
        "candidate_values": ["Light Commercial Truck", "Passenger Car", "Bus"],
        "confirmed_params": {},
        "agent_question": "请选择车型：Light Commercial Truck, Passenger Car, Bus",
        "constraint_violations": [],
    }
    parser = LLMReplyParser(
        llm_client=_mock_llm_client({
            "decision": "confirmed",
            "slot_values": {"vehicle_type": "Light Commercial Truck"},
            "confidence": 0.78,
            "evidence": "三轮 maps to small commercial vehicle category",
        }),
    )
    result = await parser.parse("那个三轮的吧", context)
    assert result is not None
    assert result.decision == ReplyDecision.CONFIRMED
    assert result.slot_values == {"vehicle_type": "Light Commercial Truck"}
    assert result.confidence == 0.78
    # F1: needs_confirmation defaults to False; caller sets it per own policy
    assert result.needs_confirmation is False


# ── Test 2: 用户回复同时含多 slot, LLM 返回 PARTIAL_REPLY ─────────────────

@pytest.mark.asyncio
async def test_edge_case_multi_slot_partial_reply():
    """Multi-slot reply '高峰时候的小汽车 NOx' → PARTIAL_REPLY, all slots preserved."""
    context: Dict[str, Any] = {
        "tool_name": "calculate_macro_emission",
        "slot_name": "vehicle_type",
        "candidate_values": ["Passenger Car", "Bus", "Truck"],
        "confirmed_params": {},
        "agent_question": "请选择车型",
        "constraint_violations": [],
    }
    parser = LLMReplyParser(
        llm_client=_mock_llm_client({
            "decision": "partial_reply",
            "slot_values": {
                "vehicle_type": "Passenger Car",
                "time_period": "peak",
                "pollutant": "NOx",
            },
            "confidence": 0.85,
            "evidence": "user provided 3 slots in one reply",
        }),
    )
    result = await parser.parse("高峰时候的小汽车 NOx", context)
    assert result is not None
    assert result.decision == ReplyDecision.PARTIAL_REPLY
    # LLMReplyParser does not discard extra slots — caller decides
    assert result.slot_values == {
        "vehicle_type": "Passenger Car",
        "time_period": "peak",
        "pollutant": "NOx",
    }
    assert result.confidence == 0.85
    assert result.needs_confirmation is False


# ── Test 3: 用户回复歧义无指代 ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_edge_case_ambiguous_reply_no_reference():
    """'嗯就那个吧' with no referent → AMBIGUOUS_REPLY, F1 no auto-gating."""
    context: Dict[str, Any] = {
        "tool_name": "calculate_macro_emission",
        "slot_name": "vehicle_type",
        "candidate_values": ["A", "B", "C"],
        "confirmed_params": {},
        "agent_question": "请选择 A, B, 或 C",
        "constraint_violations": [],
    }
    parser = LLMReplyParser(
        llm_client=_mock_llm_client({
            "decision": "ambiguous_reply",
            "slot_values": {},
            "confidence": 0.45,
            "evidence": "user reply lacks discriminating information",
        }),
    )
    result = await parser.parse("嗯就那个吧", context)
    assert result is not None
    assert result.decision == ReplyDecision.AMBIGUOUS_REPLY
    assert result.slot_values == {}
    assert result.confidence == 0.45
    # F1: needs_confirmation remains False even at low confidence;
    # the LLM self-reports the decision but does not gate.
    assert result.needs_confirmation is False


# ── Test 4: F2 — constraint_violations 标记为历史事实 ──────────────────────

@pytest.mark.asyncio
async def test_f2_constraint_violations_as_historical_facts():
    """F2: constraint_violations rendered with '仅供参考,非规则' label, no prescriptive tone."""
    capture: Dict[str, Any] = {}
    context: Dict[str, Any] = {
        "tool_name": "calculate_macro_emission",
        "slot_name": "vehicle_type",
        "candidate_values": ["Passenger Car", "Bus", "Truck"],
        "confirmed_params": {"road_type": "Expressway"},
        "agent_question": "请选择车型",
        "constraint_violations": [
            {
                "violation_type": "cross_constraint_violation",
                "involved_params": {"vehicle_type": "Motorcycle", "road_type": "Expressway"},
                "suggested_resolution": "Motorcycle not allowed on Expressway",
                "timestamp": "2026-04-28T10:00:00",
                "source_turn": 2,
            }
        ],
    }
    parser = LLMReplyParser(
        llm_client=_mock_llm_client_capture({
            "decision": "confirmed",
            "slot_values": {"vehicle_type": "Passenger Car"},
            "confidence": 0.82,
            "evidence": "user switched to Passenger Car, resolving previous Expressway conflict",
        }, capture),
    )
    result = await parser.parse("换个别的车型", context)
    assert result is not None
    assert result.decision == ReplyDecision.CONFIRMED
    assert result.slot_values == {"vehicle_type": "Passenger Car"}

    user_msg = capture["messages"][0]["content"]

    # F2: user_template line 56 renders "历史违规记录 (仅供参考,非规则):"
    assert "仅供参考" in user_msg
    assert "非规则" in user_msg
    assert "cross_constraint_violation" in user_msg
    assert "Motorcycle" in user_msg

    # F2: no prescriptive directive language about violations in user_template
    assert "必须遵守" not in user_msg

    # system_prompt F2 says "不是必须遵守的规则" (negation, not prescription)
    assert "不是必须遵守的规则" in capture["system"]


# ── Test 5: F3 — candidate_values 是 LLM 的唯一合法集 ─────────────────────

@pytest.mark.asyncio
async def test_f3_candidate_values_exclusive_set():
    """F3: prompt labels candidates as exclusive; parser returns out-of-set value as-is
    (caller-layer standardize_batch is responsible for rejection)."""
    capture: Dict[str, Any] = {}
    context: Dict[str, Any] = {
        "tool_name": "calculate_macro_emission",
        "slot_name": "vehicle_type",
        "candidate_values": ["Passenger Car", "Bus", "Truck"],
        "confirmed_params": {},
        "agent_question": "请选择车型：Passenger Car, Bus, Truck",
        "constraint_violations": [],
    }
    parser = LLMReplyParser(
        llm_client=_mock_llm_client_capture({
            "decision": "confirmed",
            "slot_values": {"vehicle_type": "Motorcycle"},
            "confidence": 0.92,
            "evidence": "user said motorcycle",
        }, capture),
    )
    result = await parser.parse("摩托车", context)
    assert result is not None
    assert result.decision == ReplyDecision.CONFIRMED

    # F3: user_template line 52 renders "候选合法值 (唯一可选,不可补全):"
    user_msg = capture["messages"][0]["content"]
    assert "唯一可选" in user_msg
    assert "不可补全" in user_msg

    # LLMReplyParser does NOT validate against candidate_values;
    # it returns the LLM output as-is.  Caller-layer standardize_batch
    # is responsible for rejecting out-of-set values.
    assert result.slot_values == {"vehicle_type": "Motorcycle"}
    assert result.confidence == 0.92
