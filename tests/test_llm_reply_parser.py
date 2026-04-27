from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from core.constraint_violation_writer import ViolationRecord
from core.reply import LLMReplyError, LLMReplyParser, LLMReplyTimeout, ReplyContext, ToolExecutionSummary


class _FakeLLMClient:
    model = "fake-synthesis"

    def __init__(self, *, response=None, delay: float = 0.0, error: Exception | None = None):
        self.response = response or SimpleNamespace(content="LLM 生成回复")
        self.delay = delay
        self.error = error
        self.calls = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.response


@pytest.mark.anyio
async def test_llm_reply_parser_returns_reply_and_metadata() -> None:
    client = _FakeLLMClient(response=SimpleNamespace(content="自然语言回复"))
    parser = LLMReplyParser(timeout_seconds=1.0, llm_client=client)

    reply, metadata = await parser.parse(ReplyContext(user_message="u", router_text="draft"))

    assert reply == "自然语言回复"
    assert metadata["mode"] == "llm"
    assert metadata["fallback"] is False
    assert metadata["model"] == "fake-synthesis"
    assert client.calls[0]["temperature"] == 0.0


@pytest.mark.anyio
async def test_llm_reply_parser_timeout_raises_explicit_error() -> None:
    parser = LLMReplyParser(timeout_seconds=0.01, llm_client=_FakeLLMClient(delay=0.05))

    with pytest.raises(LLMReplyTimeout):
        await parser.parse(ReplyContext(user_message="u", router_text="draft"))


@pytest.mark.anyio
async def test_llm_reply_parser_api_error_raises_explicit_error() -> None:
    parser = LLMReplyParser(
        timeout_seconds=1.0,
        llm_client=_FakeLLMClient(error=RuntimeError("provider down")),
    )

    with pytest.raises(LLMReplyError) as exc_info:
        await parser.parse(ReplyContext(user_message="u", router_text="draft"))

    assert "provider down" in str(exc_info.value)


def test_llm_reply_prompt_contains_all_core_context_fields() -> None:
    context = ReplyContext(
        user_message="用户消息",
        router_text="router draft",
        tool_executions=[
            ToolExecutionSummary(
                tool_name="calculate_macro_emission",
                arguments={"pollutants": ["CO2"]},
                success=True,
                summary="macro done",
            )
        ],
        violations=[
            ViolationRecord(
                violation_type="vehicle_road_compatibility",
                severity="reject",
                involved_params={"vehicle_type": "Motorcycle"},
                suggested_resolution="改用城市道路",
                timestamp="2026-04-25T10:00:00",
                source_turn=1,
            )
        ],
        extra={"data_quality_report": {"row_count": 2}},
    )

    prompt = LLMReplyParser._render_prompt(context)

    assert "用户消息" in prompt
    assert "router draft" in prompt
    assert "calculate_macro_emission" in prompt
    assert "vehicle_road_compatibility" in prompt
    assert "data_quality_report" in prompt
