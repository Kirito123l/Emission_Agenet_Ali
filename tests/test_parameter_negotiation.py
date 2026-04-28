from __future__ import annotations

import pytest

from core.parameter_negotiation import (
    NegotiationDecisionType,
    ParameterNegotiationRequest,
    parse_parameter_negotiation_reply,
    reply_looks_like_confirmation_attempt,
)
from services.standardization_engine import BatchStandardizationError, StandardizationEngine


def _build_request() -> ParameterNegotiationRequest:
    return ParameterNegotiationRequest.from_dict(
        {
            "request_id": "neg-vehicle",
            "parameter_name": "vehicle_type",
            "raw_value": "飞机",
            "confidence": 0.62,
            "trigger_reason": "low_confidence_llm_match(confidence=0.62)",
            "tool_name": "query_emission_factors",
            "arg_name": "vehicle_type",
            "strategy": "llm",
            "candidates": [
                {
                    "index": 1,
                    "normalized_value": "Passenger Car",
                    "display_label": "乘用车 (Passenger Car)",
                    "confidence": 0.62,
                    "strategy": "llm",
                    "aliases": ["乘用车", "Passenger Car"],
                },
                {
                    "index": 2,
                    "normalized_value": "Transit Bus",
                    "display_label": "公交车 (Transit Bus)",
                    "confidence": 0.62,
                    "strategy": "llm",
                    "aliases": ["公交车", "Transit Bus"],
                },
            ],
        }
    )


@pytest.mark.asyncio
async def test_parse_parameter_negotiation_reply_supports_index_and_label_and_none():
    request = _build_request()

    first = await parse_parameter_negotiation_reply(request, "1")
    assert first.is_resolved is True
    assert first.decision.decision_type == NegotiationDecisionType.CONFIRMED
    assert first.decision.selected_value == "Passenger Car"

    second = await parse_parameter_negotiation_reply(request, "选第2个")
    assert second.is_resolved is True
    assert second.decision.selected_index == 2
    assert second.decision.selected_value == "Transit Bus"

    by_label = await parse_parameter_negotiation_reply(request, "乘用车")
    assert by_label.is_resolved is True
    assert by_label.decision.selected_value == "Passenger Car"

    none = await parse_parameter_negotiation_reply(request, "都不对")
    assert none.is_resolved is True
    assert none.decision.decision_type == NegotiationDecisionType.NONE_OF_ABOVE


def test_reply_looks_like_confirmation_attempt_is_bounded():
    request = _build_request()

    assert reply_looks_like_confirmation_attempt(request, "第一个") is True
    assert reply_looks_like_confirmation_attempt(request, "Passenger Car") is True
    assert reply_looks_like_confirmation_attempt(request, "都不对") is True
    assert reply_looks_like_confirmation_attempt(request, "顺便解释一下 PM2.5 是什么") is False


def test_low_confidence_llm_match_raises_negotiation_eligible_batch_error(monkeypatch):
    engine = StandardizationEngine(
        {
            "llm_enabled": True,
            "parameter_negotiation_enabled": True,
            "parameter_negotiation_confidence_threshold": 0.9,
            "parameter_negotiation_max_candidates": 4,
        }
    )
    monkeypatch.setattr(
        engine._llm_backend,
        "_call_llm",
        lambda *args, **kwargs: {"value": "Passenger Car", "confidence": 0.62},
    )

    with pytest.raises(BatchStandardizationError) as exc_info:
        engine.standardize_batch(
            {"vehicle_type": "Tesla Model 3", "model_year": 2020},
            tool_name="query_emission_factors",
        )

    assert exc_info.value.negotiation_eligible is True
    assert exc_info.value.param_name == "vehicle_type"
    assert "Passenger Car" in exc_info.value.suggestions


def test_high_confidence_alias_auto_accepts_without_negotiation():
    engine = StandardizationEngine(
        {
            "llm_enabled": False,
            "parameter_negotiation_enabled": True,
            "parameter_negotiation_confidence_threshold": 0.9,
        }
    )

    standardized, records = engine.standardize_batch(
        {"vehicle_type": "小汽车", "model_year": 2020},
        tool_name="query_emission_factors",
    )

    assert standardized["vehicle_type"] == "Passenger Car"
    assert records[0]["strategy"] in {"alias", "exact", "fuzzy"}


def test_resolve_candidate_value_handles_display_label_and_alias():
    engine = StandardizationEngine({"llm_enabled": False})

    assert engine.resolve_candidate_value("vehicle_type", "乘用车 (Passenger Car)") == "Passenger Car"
    assert engine.resolve_candidate_value("vehicle_type", "乘用车") == "Passenger Car"
    assert engine.resolve_candidate_value("pollutant", "NOx") == "NOx"
