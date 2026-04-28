"""Unit tests for Layer 1 fast path in parameter_negotiation (A.2)."""

from __future__ import annotations

import pytest

from core.parameter_negotiation import (
    NegotiationCandidate,
    NegotiationDecisionType,
    ParameterNegotiationParseResult,
    ParameterNegotiationRequest,
    _try_fast_path,
)


def _make_request(candidates=None):
    if candidates is None:
        candidates = [
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
            NegotiationCandidate(
                index=3,
                normalized_value="Motorcycle",
                display_label="摩托车 (Motorcycle)",
                aliases=["摩托车", "摩托"],
            ),
        ]
    return ParameterNegotiationRequest(
        request_id="neg-fastpath-01",
        parameter_name="vehicle_type",
        raw_value="飞机",
        confidence=0.62,
        trigger_reason="low_confidence_llm_match",
        tool_name="query_emission_factors",
        candidates=candidates,
    )


def test_fast_path_numeric_index_selects_candidate():
    r = _make_request()
    result = _try_fast_path("1", r)
    assert result is not None
    assert result.is_resolved is True
    assert result.decision.decision_type == NegotiationDecisionType.CONFIRMED
    assert result.decision.selected_value == "Passenger Car"
    assert result.decision.source == "fast_path_index"


def test_fast_path_chinese_ordinal_skipped():
    """Chinese ordinals (第一个) are >3 chars or not in fast-path categories.
    They are handled by Layer 4 legacy regex instead."""
    r = _make_request()
    result = _try_fast_path("第一个", r)
    assert result is None  # fast path delegates, regex handles it


def test_fast_path_confirm_word_with_single_candidate():
    r = _make_request(candidates=[
        NegotiationCandidate(
            index=1,
            normalized_value="Passenger Car",
            display_label="乘用车",
            aliases=["小汽车"],
        ),
    ])
    result = _try_fast_path("好", r)
    assert result is not None
    assert result.is_resolved is True
    assert result.decision.selected_value == "Passenger Car"
    assert result.decision.source == "fast_path_confirm"


def test_fast_path_confirm_word_with_multiple_candidates_returns_none():
    """When there are multiple candidates, '好' alone is ambiguous."""
    r = _make_request()
    result = _try_fast_path("好", r)
    assert result is None


def test_fast_path_decline_word():
    r = _make_request()
    result = _try_fast_path("都不是", r)
    assert result is not None
    assert result.is_resolved is True
    assert result.decision.decision_type == NegotiationDecisionType.NONE_OF_ABOVE
    assert result.decision.source == "fast_path_decline"


def test_fast_path_long_reply_skips():
    """Replies longer than 3 chars should skip fast path."""
    r = _make_request()
    result = _try_fast_path("我选第一个", r)
    assert result is None


def test_fast_path_empty_reply():
    r = _make_request()
    result = _try_fast_path("", r)
    assert result is None


def test_numeric_out_of_range():
    r = _make_request()
    result = _try_fast_path("99", r)
    assert result is not None
    assert result.is_resolved is False
    assert result.needs_retry is True
