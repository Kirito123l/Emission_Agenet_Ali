from __future__ import annotations

from click.testing import CliRunner


def test_chat_command_constructs_governed_router(monkeypatch):
    import main

    calls = []

    class GovernedRouter:
        def clear_history(self):
            return None

    def fake_build_router(*, session_id: str, router_mode: str = "router"):
        calls.append({"session_id": session_id, "router_mode": router_mode})
        return GovernedRouter()

    monkeypatch.setattr(main, "build_router", fake_build_router)
    monkeypatch.setattr(main.console, "input", lambda *args, **kwargs: "quit")

    result = CliRunner().invoke(main.cli, ["chat"])

    assert result.exit_code == 0
    assert calls == [{"session_id": "cli_session", "router_mode": "full"}]
