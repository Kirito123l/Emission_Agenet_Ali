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
        assert assistant_message["download_file"]["url"] == f"/api/file/download/message/{session_id}/legacy-0"
        assert assistant_message["download_file"]["path"] == str(get_config().outputs_dir / "legacy_result.xlsx")
