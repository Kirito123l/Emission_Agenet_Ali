from __future__ import annotations

from types import SimpleNamespace

import pytest

import api.session as session_module
import core.governed_router as governed_router_module


def _router_response(text: str = "ok") -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        chart_data=None,
        table_data=None,
        map_data=None,
        download_file=None,
        executed_tool_calls=[],
        trace=None,
        trace_friendly=[],
    )


class _ContextStore:
    def to_persisted_dict(self) -> dict:
        return {}


class GovernedRouter:
    def __init__(self, session_id: str, memory_storage_dir=None):
        self.session_id = session_id
        self.memory_storage_dir = memory_storage_dir
        self.context_store = _ContextStore()
        self.chat_calls = []

    async def chat(self, user_message: str, file_path=None, trace=None):
        self.chat_calls.append(
            {"user_message": user_message, "file_path": file_path, "trace": trace}
        )
        return _router_response("governed")

    def to_persisted_state(self) -> dict:
        return {"context_store": {}}


class NaiveRouter:
    def __init__(self, session_id: str, tool_call_log_path=None):
        self.session_id = session_id
        self.tool_call_log_path = tool_call_log_path
        self.chat_calls = []

    async def chat(self, user_message: str, file_path=None, trace=None):
        self.chat_calls.append(
            {"user_message": user_message, "file_path": file_path, "trace": trace}
        )
        return _router_response("naive")

    def to_persisted_state(self) -> dict:
        return {"history": []}


@pytest.fixture
def patched_session_routers(monkeypatch):
    build_calls = []

    def fake_build_router(*, session_id: str, memory_storage_dir=None, router_mode: str = "router"):
        build_calls.append(
            {
                "session_id": session_id,
                "memory_storage_dir": memory_storage_dir,
                "router_mode": router_mode,
            }
        )
        return GovernedRouter(session_id=session_id, memory_storage_dir=memory_storage_dir)

    monkeypatch.setattr(session_module, "build_router", fake_build_router)
    monkeypatch.setattr(session_module, "NaiveRouter", NaiveRouter)
    return build_calls


@pytest.mark.anyio
async def test_full_mode_uses_governed_agent_router(tmp_path, patched_session_routers):
    session = session_module.Session("full-session", storage_dir=tmp_path)

    result = await session.chat("hello", mode="full")

    assert result["text"] == "governed"
    assert session.agent_router.__class__.__name__ == "GovernedRouter"
    assert patched_session_routers[0]["router_mode"] == "full"
    assert session.agent_router.chat_calls[0]["user_message"] == "hello"


@pytest.mark.anyio
async def test_governed_v2_mode_is_alias_for_governed_agent_router(tmp_path, patched_session_routers):
    session = session_module.Session("governed-session", storage_dir=tmp_path)

    result = await session.chat("hello", mode="governed_v2")

    assert result["text"] == "governed"
    assert session.agent_router.__class__.__name__ == "GovernedRouter"
    assert patched_session_routers[0]["router_mode"] == "full"


@pytest.mark.anyio
async def test_naive_mode_uses_naive_router(tmp_path, patched_session_routers):
    session = session_module.Session("naive-session", storage_dir=tmp_path)

    result = await session.chat("hello", mode="naive")

    assert result["text"] == "naive"
    assert session._agent_router is None
    assert session.naive_router.__class__.__name__ == "NaiveRouter"
    assert patched_session_routers == []


def test_router_alias_returns_agent_router(tmp_path, patched_session_routers):
    session = session_module.Session("router-alias-session", storage_dir=tmp_path)

    assert session.router is session.agent_router


def test_governed_router_alias_returns_agent_router(tmp_path, patched_session_routers):
    session = session_module.Session("governed-alias-session", storage_dir=tmp_path)

    assert session.governed_router is session.agent_router


def test_map_export_router_alias_still_exposes_agent_context_store(tmp_path, patched_session_routers):
    session = session_module.Session("map-export-session", storage_dir=tmp_path)

    context_store = getattr(session.router, "context_store", None)

    assert context_store is session.agent_router.context_store


def test_build_router_routes_production_modes_to_governed_router(monkeypatch, tmp_path):
    monkeypatch.setattr(governed_router_module, "GovernedRouter", GovernedRouter)

    for mode in ("full", "governed_v2", "router"):
        router = governed_router_module.build_router(
            session_id=f"{mode}-session",
            memory_storage_dir=tmp_path,
            router_mode=mode,
        )
        assert router.__class__.__name__ == "GovernedRouter"

    with pytest.raises(ValueError, match="NaiveRouter directly"):
        governed_router_module.build_router(
            session_id="naive-session",
            memory_storage_dir=tmp_path,
            router_mode="naive",
        )
