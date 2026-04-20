from __future__ import annotations

from pathlib import Path

import pytest
from services.chat_session_service import ChatSessionService, UploadedFileInput, build_router_user_message


class FakeSession:
    def __init__(self, session_id: str = "svc-test"):
        self.session_id = session_id
        self.message_count = 0
        self.updated_at = None
        self.last_result_file = None
        self.chat_calls = []
        self.saved_turns = []

    async def chat(self, message, file_path=None, mode="full"):
        self.chat_calls.append({"message": message, "file_path": file_path, "mode": mode})
        return {
            "text": "done",
            "chart_data": None,
            "table_data": {
                "type": "result_table",
                "columns": ["name", "value"],
                "preview_rows": [{"name": "NOx", "value": 1.2}],
                "total_rows": 1,
            },
            "map_data": None,
            "download_file": {"path": "/tmp/result.xlsx", "filename": "result.xlsx"},
            "executed_tool_calls": [
                {
                    "name": "calculate_macro_emission",
                    "arguments": {"pollutant": "NOx"},
                    "result": {"success": True, "summary": "ok"},
                }
            ],
            "trace": {
                "final_stage": "done",
                "step_count": 1,
                "steps": [
                    {
                        "step_type": "tool_execution",
                        "stage_before": "executing",
                        "action": "calculate_macro_emission",
                        "output_summary": {"success": True},
                    }
                ],
            },
            "trace_friendly": [{"title": "Tool", "description": "ran", "status": "success"}],
        }

    def save_turn(self, **kwargs):
        self.saved_turns.append(kwargs)
        self.message_count += 1
        return kwargs.get("message_id")


class FakeManager:
    def __init__(self):
        self.session = FakeSession()
        self.title_updates = []
        self.saved = False

    def get_or_create_session(self, session_id=None):
        if session_id:
            self.session.session_id = session_id
        return self.session

    def update_session_title(self, session_id, first_message):
        self.title_updates.append((session_id, first_message))

    def save_session(self):
        self.saved = True


@pytest.mark.anyio
async def test_shared_runner_processes_turn_without_web_frontend():
    manager = FakeManager()
    service = ChatSessionService(manager, user_id="svc-user")

    turn = await service.process_turn(message="calculate", session_id="svc-test", mode="full")

    assert turn.reply == "done"
    assert turn.session_id == "svc-test"
    assert turn.data_type == "table"
    assert turn.download_file["url"] == "/api/file/download/message/svc-test/" + turn.message_id + "?user_id=svc-user"
    assert turn.table_data["download"]["filename"] == "result.xlsx"
    assert turn.artifact_summaries[0].kind == "table"
    assert turn.debug["selected_tools"] == ["calculate_macro_emission"]
    assert manager.session.chat_calls == [{"message": "calculate", "file_path": None, "mode": "full"}]
    assert manager.session.saved_turns[0]["assistant_response"] == "done"
    assert manager.saved is True


@pytest.mark.anyio
async def test_shared_runner_stages_cli_upload_like_api_upload(tmp_path):
    upload_path = tmp_path / "roads.csv"
    upload_path.write_text("link_id,length\nA,1\n", encoding="utf-8")
    manager = FakeManager()
    service = ChatSessionService(manager, user_id="svc-user")

    turn = await service.process_turn(
        message="analyze this",
        upload=UploadedFileInput.from_path(upload_path),
        mode="full",
    )

    call = manager.session.chat_calls[0]
    staged_path = Path(call["file_path"])
    assert staged_path.exists()
    assert staged_path.read_text(encoding="utf-8") == "link_id,length\nA,1\n"
    assert "文件已上传，路径:" in call["message"]
    assert "请使用 input_file 参数处理此文件。" in call["message"]
    assert turn.uploaded_file.file_name == "roads.csv"
    assert turn.uploaded_file.source_path == str(upload_path)
    assert manager.session.saved_turns[0]["file_path"] == str(staged_path)


def test_router_user_message_keeps_naive_mode_lightweight():
    message = build_router_user_message("请计算", Path("/tmp/example.csv"), "naive")

    assert message == "请计算\n\n文件已上传，路径: /tmp/example.csv"
