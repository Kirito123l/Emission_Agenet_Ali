from __future__ import annotations

from types import SimpleNamespace

import pytest

import core.governed_router as governed_router_module
from config import reset_config
from core.analytical_objective import AORelationship
from core.context_store import SessionContextStore
from core.memory import FactMemory
from core.naive_router import NaiveRouter
from core.reply import LLMReplyTimeout
from core.router import RouterResponse
from services.llm_client import LLMResponse


class _FakeInnerRouter:
    def __init__(self, session_id: str, memory_storage_dir=None):
        self.session_id = session_id
        self.memory = SimpleNamespace(
            fact_memory=FactMemory(session_id=session_id),
            turn_counter=0,
        )
        self.context_store = SessionContextStore()
        self.response = RouterResponse(
            text="router text",
            trace={
                "steps": [
                    {
                        "step_type": "tool_execution",
                        "action": "query_knowledge",
                        "input_summary": {"arguments": {"query": "x"}},
                        "output_summary": {"success": True, "message": "ok"},
                    }
                ]
            },
        )

    def _ensure_context_store(self):
        return self.context_store

    async def chat(self, user_message: str, file_path=None, trace=None):
        self.memory.turn_counter = 1
        if isinstance(trace, dict) and isinstance(self.response.trace, dict):
            trace.update(self.response.trace)
        return self.response

    def to_persisted_state(self):
        return {"version": 2, "live_state": {}}

    def restore_persisted_state(self, payload):
        self.memory = SimpleNamespace(
            fact_memory=FactMemory(session_id=self.session_id),
            turn_counter=0,
        )
        self.context_store = SessionContextStore()


class _NoopContract:
    name = "noop"

    def __init__(self, *args, **kwargs):
        pass

    async def before_turn(self, context):
        return SimpleNamespace(
            proceed=True,
            response=None,
            user_message_override=None,
            metadata={},
        )

    async def after_turn(self, context, result):
        return None


class _FakeParser:
    def __init__(self, *, reply: str | None = None, error: Exception | None = None):
        self.reply = reply or "LLM reply"
        self.error = error
        self.contexts = []

    async def parse(self, context):
        self.contexts.append(context)
        if self.error is not None:
            raise self.error
        return self.reply, {
            "mode": "llm",
            "fallback": False,
            "latency_ms": 1,
            "model": "fake-synthesis",
        }


@pytest.fixture
def patched_governed_router(monkeypatch):
    monkeypatch.setenv("ENABLE_CONTRACT_SPLIT", "false")
    reset_config()
    monkeypatch.setattr(governed_router_module, "UnifiedRouter", _FakeInnerRouter)
    monkeypatch.setattr(governed_router_module, "OASCContract", _NoopContract)
    monkeypatch.setattr(governed_router_module, "ClarificationContract", _NoopContract)
    monkeypatch.setattr(governed_router_module, "DependencyContract", _NoopContract)
    yield governed_router_module
    reset_config()


@pytest.mark.anyio
async def test_governed_router_uses_llm_reply_when_enabled_and_successful(
    patched_governed_router,
    monkeypatch,
):
    monkeypatch.setenv("ENABLE_REPLY_PIPELINE", "true")
    monkeypatch.setenv("ENABLE_LLM_REPLY_PARSER", "true")
    reset_config()
    parser = _FakeParser(reply="LLM polished reply")
    monkeypatch.setattr(
        patched_governed_router,
        "LLMReplyParser",
        lambda timeout_seconds=20.0: parser,
    )
    router = patched_governed_router.GovernedRouter("reply-success")
    router.ao_manager.create_ao("reply objective", AORelationship.INDEPENDENT, current_turn=1)

    result = await router.chat("用户消息", trace={})

    assert result.text == "LLM polished reply"
    assert parser.contexts[0].router_text == "router text"
    reply_step = result.trace["steps"][-1]
    assert reply_step["step_type"] == "reply_generation"
    assert reply_step["output_summary"]["mode"] == "llm"
    assert reply_step["output_summary"]["fallback"] is False


@pytest.mark.anyio
async def test_governed_router_falls_back_to_router_text_on_llm_timeout(
    patched_governed_router,
    monkeypatch,
):
    monkeypatch.setenv("ENABLE_REPLY_PIPELINE", "true")
    monkeypatch.setenv("ENABLE_LLM_REPLY_PARSER", "true")
    reset_config()
    parser = _FakeParser(error=LLMReplyTimeout("timeout after 20.0s"))
    monkeypatch.setattr(
        patched_governed_router,
        "LLMReplyParser",
        lambda timeout_seconds=20.0: parser,
    )
    router = patched_governed_router.GovernedRouter("reply-timeout")
    router.ao_manager.create_ao("reply objective", AORelationship.INDEPENDENT, current_turn=1)

    result = await router.chat("用户消息", trace={})

    assert result.text == "router text"
    reply_step = result.trace["steps"][-1]
    assert reply_step["output_summary"]["fallback"] is True
    assert "LLMReplyTimeout" in reply_step["output_summary"]["reason"]


@pytest.mark.anyio
async def test_governed_router_keeps_router_text_when_flag_disabled(
    patched_governed_router,
    monkeypatch,
):
    monkeypatch.setenv("ENABLE_REPLY_PIPELINE", "true")
    monkeypatch.setenv("ENABLE_LLM_REPLY_PARSER", "false")
    reset_config()
    parser = _FakeParser(error=AssertionError("parser should not be called"))
    monkeypatch.setattr(
        patched_governed_router,
        "LLMReplyParser",
        lambda timeout_seconds=20.0: parser,
    )
    router = patched_governed_router.GovernedRouter("reply-disabled")
    router.ao_manager.create_ao("reply objective", AORelationship.INDEPENDENT, current_turn=1)

    result = await router.chat("用户消息", trace={})

    assert result.text == "router text"
    assert parser.contexts == []
    assert result.trace["steps"][-1]["output_summary"]["mode"] == "legacy_render"


@pytest.mark.anyio
async def test_naive_router_does_not_construct_llm_reply_parser(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "core.reply.llm_parser.get_llm_client",
        lambda purpose: (_ for _ in ()).throw(AssertionError("reply parser client should not load")),
    )

    class _FakeNaiveLLM:
        async def chat_with_tools(self, **kwargs):
            return LLMResponse(content="naive reply")

    router = NaiveRouter(
        session_id="naive-reply",
        llm=_FakeNaiveLLM(),
        registry=SimpleNamespace(list_tools=lambda: [], get=lambda name: None),
        tool_call_log_path=tmp_path / "naive.jsonl",
    )

    result = await router.chat("普通问题")

    assert result.text == "naive reply"
