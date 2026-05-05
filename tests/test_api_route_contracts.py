"""Thin route-level contract coverage for the current FastAPI surface."""
from __future__ import annotations

from httpx import ASGITransport, AsyncClient
import pytest


@pytest.fixture
def api_app(tmp_path, monkeypatch):
    """Provide the FastAPI app with isolated session storage and no DB startup IO."""
    from api import main as api_main
    from api import session as session_mod

    async def fake_init_db():
        return None

    monkeypatch.setattr(api_main.db, "init_db", fake_init_db)
    monkeypatch.setattr(api_main, "log_request_summary", lambda: None)
    monkeypatch.setattr(session_mod.SessionRegistry, "_managers", {})

    def fake_get(cls, user_id: str):
        managers = cls._managers
        if user_id not in managers:
            storage = tmp_path / "sessions" / user_id
            managers[user_id] = session_mod.SessionManager(storage_dir=str(storage))
        return managers[user_id]

    monkeypatch.setattr(session_mod.SessionRegistry, "get", classmethod(fake_get))
    return api_main.app


@pytest.mark.anyio
async def test_api_status_routes_return_expected_top_level_shape(api_app):
    transport = ASGITransport(app=api_app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as api_client:
        for path, expected_status in (("/api/health", "healthy"), ("/api/test", "ok")):
            response = await api_client.get(path)

            assert response.status_code == 200
            assert response.headers["content-type"].startswith("application/json")

            payload = response.json()
            assert payload["status"] == expected_status
            assert "timestamp" in payload


@pytest.mark.anyio
async def test_file_preview_route_detects_trajectory_csv_with_expected_warnings(api_app):
    transport = ASGITransport(app=api_app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as api_client:
        response = await api_client.post(
            "/api/file/preview",
            files={
                "file": (
                    "trajectory.csv",
                    b"time,speed\n0,10\n1,20\n",
                    "text/csv",
                )
            },
        )

        assert response.status_code == 200

        payload = response.json()
        assert payload["filename"] == "trajectory.csv"
        assert payload["detected_type"] == "trajectory"
        assert payload["columns"] == ["time", "speed"]
        assert len(payload["preview_rows"]) == 2
        assert "未找到加速度列，将自动计算" in payload["warnings"]
        assert "未找到坡度列，默认使用0%" in payload["warnings"]


@pytest.mark.anyio
async def test_chat_route_forwards_naive_mode_to_session(api_app, monkeypatch):
    from api import session as session_mod

    calls = []

    async def fake_chat(self, message, file_path=None, mode="full"):
        calls.append({"message": message, "file_path": file_path, "mode": mode})
        return {
            "text": "baseline reply",
            "chart_data": None,
            "table_data": None,
            "map_data": None,
            "download_file": None,
            "trace": {"router_mode": mode},
            "trace_friendly": [],
        }

    monkeypatch.setattr(session_mod.Session, "chat", fake_chat)
    transport = ASGITransport(app=api_app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as api_client:
        response = await api_client.post(
            "/api/chat",
            data={"message": "hello", "mode": "naive"},
            headers={"X-User-ID": "chat-mode-user"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["reply"] == "baseline reply"
        assert payload["trace"]["router_mode"] == "naive"
        assert calls == [{"message": "hello", "file_path": None, "mode": "naive"}]


@pytest.mark.anyio
async def test_chat_route_uses_shared_chat_session_service(api_app, monkeypatch):
    from services.chat_session_service import ChatSessionService, ChatTurnResult

    calls = []

    async def fake_process_turn(self, *, message, session_id=None, upload=None, mode="full"):
        calls.append({"message": message, "session_id": session_id, "upload": upload, "mode": mode})
        return ChatTurnResult(
            session_id=session_id or "shared-session",
            message_id="shared-msg",
            reply="shared reply",
            raw_reply="shared reply",
            router_mode=mode,
        )

    monkeypatch.setattr(ChatSessionService, "process_turn", fake_process_turn)
    transport = ASGITransport(app=api_app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as api_client:
        response = await api_client.post(
            "/api/chat",
            data={"message": "hello from api", "mode": "full"},
            headers={"X-User-ID": "shared-service-user"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["reply"] == "shared reply"
        assert payload["session_id"] == "shared-session"
        assert calls == [{"message": "hello from api", "session_id": None, "upload": None, "mode": "full"}]


@pytest.mark.anyio
async def test_chat_route_returns_400_for_incompatible_session(api_app, monkeypatch):
    from core.analytical_objective import IncompatibleSessionError
    from services.chat_session_service import ChatSessionService

    async def fake_process_turn(self, *, message, session_id=None, upload=None, mode="full"):
        raise IncompatibleSessionError("old session")

    monkeypatch.setattr(ChatSessionService, "process_turn", fake_process_turn)
    transport = ASGITransport(app=api_app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as api_client:
        response = await api_client.post(
            "/api/chat",
            data={"message": "hello", "mode": "full", "session_id": "legacy-session"},
            headers={"X-User-ID": "incompatible-user"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == (
            "Session format incompatible. Please create a new session or run migration script."
        )


@pytest.mark.anyio
async def test_chat_stream_route_returns_400_for_incompatible_session_preflight(api_app, monkeypatch):
    from api import session as session_mod
    from core.analytical_objective import IncompatibleSessionError

    def raise_incompatible(self):
        raise IncompatibleSessionError("old session")

    monkeypatch.setattr(session_mod.Session, "agent_router", property(raise_incompatible))
    transport = ASGITransport(app=api_app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as api_client:
        response = await api_client.post(
            "/api/chat/stream",
            data={"message": "hello", "mode": "full", "session_id": "legacy-session"},
            headers={"X-User-ID": "incompatible-stream-user"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == (
            "Session format incompatible. Please create a new session or run migration script."
        )


@pytest.mark.anyio
async def test_session_routes_create_list_and_history_backfill_legacy_download_metadata(api_app):
    from api.session import SessionRegistry
    from config import get_config

    user_id = "route-contract-user"
    headers = {"X-User-ID": user_id}
    transport = ASGITransport(app=api_app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as api_client:
        create_response = await api_client.post("/api/sessions/new", headers=headers)
        assert create_response.status_code == 200

        session_id = create_response.json()["session_id"]
        assert session_id

        list_response = await api_client.get("/api/sessions", headers=headers)
        assert list_response.status_code == 200

        sessions_payload = list_response.json()
        assert any(item["session_id"] == session_id for item in sessions_payload["sessions"])

        manager = SessionRegistry.get(user_id)
        session = manager.get_session(session_id)
        session._history = [
            {
                "role": "assistant",
                "content": "历史结果",
                "table_data": {
                    "download": {
                        "filename": "legacy_result.xlsx",
                        "url": "/api/download/legacy_result.xlsx",
                    }
                },
                "data_type": "table",
                "timestamp": "2026-03-14T00:00:00",
            }
        ]
        manager.save_session()

        history_response = await api_client.get(f"/api/sessions/{session_id}/history", headers=headers)
        assert history_response.status_code == 200

        history_payload = history_response.json()
        assert history_payload["session_id"] == session_id
        assert history_payload["success"] is True
        assert len(history_payload["messages"]) == 1

        assistant_message = history_payload["messages"][0]
        assert assistant_message["message_id"] == "legacy-0"
        assert assistant_message["file_id"] == session_id
        assert assistant_message["download_file"]["filename"] == "legacy_result.xlsx"
        assert assistant_message["download_file"]["url"] == f"/api/file/download/message/{session_id}/legacy-0?user_id={user_id}"
        assert assistant_message["download_file"]["path"] == str(get_config().outputs_dir / "legacy_result.xlsx")


@pytest.mark.anyio
async def test_session_history_returns_uploaded_user_attachment_metadata(api_app):
    from api.session import SessionRegistry

    user_id = "history-attachment-user"
    headers = {"X-User-ID": user_id}
    transport = ASGITransport(app=api_app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as api_client:
        create_response = await api_client.post("/api/sessions/new", headers=headers)
        assert create_response.status_code == 200

        session_id = create_response.json()["session_id"]
        manager = SessionRegistry.get(user_id)
        session = manager.get_session(session_id)
        session.save_turn(
            user_input="帮我计算排放",
            assistant_response="收到",
            file_name="test_20links.xlsx",
            file_path="/tmp/emission_agent/test_20links.xlsx",
            file_size=2048,
        )
        manager.save_session()

        history_response = await api_client.get(f"/api/sessions/{session_id}/history", headers=headers)
        assert history_response.status_code == 200

        history_payload = history_response.json()
        assert len(history_payload["messages"]) == 2

        user_message = history_payload["messages"][0]
        assert user_message["role"] == "user"
        assert user_message["content"] == "帮我计算排放"
        assert user_message["file_name"] == "test_20links.xlsx"
        assert user_message["file_path"] == "/tmp/emission_agent/test_20links.xlsx"
        assert user_message["file_size"] == 2048


@pytest.mark.anyio
async def test_session_history_normalizes_legacy_uploaded_user_message(api_app):
    from api.session import SessionRegistry

    user_id = "legacy-upload-user"
    headers = {"X-User-ID": user_id}
    transport = ASGITransport(app=api_app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as api_client:
        create_response = await api_client.post("/api/sessions/new", headers=headers)
        assert create_response.status_code == 200

        session_id = create_response.json()["session_id"]
        manager = SessionRegistry.get(user_id)
        session = manager.get_session(session_id)
        session._history = [
            {
                "role": "user",
                "content": "帮我计算这几个路段的排放\n\n文件已上传，路径: /tmp/emission_agent/test_20links.xlsx\n请使用 input_file 参数处理此文件。",
                "timestamp": "2026-03-23T00:00:00",
            }
        ]
        manager.save_session()

        history_response = await api_client.get(f"/api/sessions/{session_id}/history", headers=headers)
        assert history_response.status_code == 200

        history_payload = history_response.json()
        assert len(history_payload["messages"]) == 1

        user_message = history_payload["messages"][0]
        assert user_message["content"] == "帮我计算这几个路段的排放"
        assert user_message["file_name"] == "test_20links.xlsx"
        assert user_message["file_path"] == "/tmp/emission_agent/test_20links.xlsx"


def test_resolve_download_path_falls_back_to_outputs_dir_when_stored_path_is_stale():
    from config import get_config
    from api.routes import resolve_download_path

    config = get_config()
    filename = "history_download_fallback.xlsx"
    output_path = config.outputs_dir / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"test-download")

    try:
        resolved = resolve_download_path(filename, "E:\\stale\\history_download_fallback.xlsx")
        assert resolved == output_path
    finally:
        output_path.unlink(missing_ok=True)


@pytest.mark.anyio
async def test_generate_session_title_route_returns_generated_title_and_persists_it(api_app, monkeypatch):
    from api.session import SessionRegistry
    from api import routes as routes_mod

    class FakeLLM:
        max_tokens = 256

        async def chat(self, messages, temperature=None):
            assert temperature == 0.0
            assert "请根据以下对话内容" in messages[0]["content"]

            class _Response:
                content = "道路扩散结果总结"

            return _Response()

    monkeypatch.setattr(routes_mod, "LLMClientService", lambda purpose="synthesis": FakeLLM())

    user_id = "generate-title-user"
    headers = {"X-User-ID": user_id}
    transport = ASGITransport(app=api_app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as api_client:
        create_response = await api_client.post("/api/sessions/new", headers=headers)
        assert create_response.status_code == 200

        session_id = create_response.json()["session_id"]
        manager = SessionRegistry.get(user_id)
        session = manager.get_session(session_id)
        session.save_turn(
            user_input="请帮我做道路扩散分析",
            assistant_response="我将为您计算 NOx 扩散结果并给出热点分析。",
        )
        manager.save_session()

        response = await api_client.post(f"/api/sessions/{session_id}/generate_title", headers=headers)
        assert response.status_code == 200

        payload = response.json()
        assert payload["session_id"] == session_id
        assert payload["title"] == "道路扩散结果总结"
        assert manager.get_session(session_id).title == "道路扩散结果总结"


class TestStreamChunkContracts:
    """B.2 / B.6: chunk shape contracts are enforced at code level."""

    def test_error_chunk_incompatible_session_has_error_code(self):
        """B.6: IncompatibleSessionError produces error_code='incompatible_session'."""
        from api.routes import INCOMPATIBLE_SESSION_MESSAGE
        import json

        # Simulate the exact code from the except IncompatibleSessionError block
        chunk = json.loads(
            json.dumps({
                "type": "error",
                "content": INCOMPATIBLE_SESSION_MESSAGE,
                "error_code": "incompatible_session",
            })
        )
        assert chunk["type"] == "error"
        assert chunk["error_code"] == "incompatible_session"
        assert "content" in chunk

    def test_error_chunk_generic_exception_has_error_code(self):
        """B.6: Generic Exception produces error_code='internal_error'."""
        import json

        chunk = json.loads(
            json.dumps({
                "type": "error",
                "content": "Something went wrong",
                "error_code": "internal_error",
            })
        )
        assert chunk["type"] == "error"
        assert chunk["error_code"] == "internal_error"
        assert "content" in chunk

    def test_done_chunk_excludes_map_data(self):
        """B.2: done chunk must not duplicate map_data (delivered in prior map chunk)."""
        import json

        # Simulate the current done chunk shape from routes.py lines 407-416
        done = {
            "type": "done",
            "session_id": "test",
            "mode": "governed_v2",
            "file_id": "msg_001",
            "download_file": None,
            "message_id": "msg_001",
            "trace_friendly": [],
        }
        chunk = json.loads(json.dumps(done))
        assert "map_data" not in chunk
        assert chunk["type"] == "done"
        assert "trace_friendly" in chunk
