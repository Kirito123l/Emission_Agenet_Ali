from __future__ import annotations

from pathlib import Path

import pytest

from run_code import TerminalChatRunner
from services.artifact_summary import ArtifactSummary
from services.chat_session_service import ChatTurnResult, StoredUpload


class FakeCliService:
    def __init__(self):
        self.calls = []

    async def process_turn(self, *, message, session_id=None, upload=None, mode="full"):
        self.calls.append({"message": message, "session_id": session_id, "upload": upload, "mode": mode})
        uploaded_file = None
        if upload is not None:
            uploaded_file = StoredUpload(
                file_name=upload.resolved_filename() or "upload",
                file_path=str(upload.source_path),
                file_size=len(upload.read_bytes()),
                source_path=str(upload.source_path),
            )
        return ChatTurnResult(
            session_id=session_id or "cli-session",
            message_id="msg-1",
            reply="done with table",
            raw_reply="done with table",
            data_type="table",
            table_data={"type": "table", "columns": ["A"], "preview_rows": [{"A": 1}], "total_rows": 1},
            router_mode=mode,
            uploaded_file=uploaded_file,
            debug={"payload_types": ["table"], "router_mode": mode, "selected_tools": ["fake_tool"]},
            artifact_summaries=[
                ArtifactSummary(
                    kind="table",
                    artifact_type="table",
                    title="Table",
                    frontend="table",
                    key_stats={"rows": 1, "columns": 1},
                    preview=[{"A": 1}],
                )
            ],
        )


@pytest.mark.anyio
async def test_cli_upload_command_registers_file_for_next_turn(tmp_path):
    upload_path = tmp_path / "input.csv"
    upload_path.write_text("A\n1\n", encoding="utf-8")
    service = FakeCliService()
    runner = TerminalChatRunner(service=service, quiet=True)

    runner.register_upload(str(upload_path))
    assert runner.state.pending_upload is not None

    await runner.send_message("process it")

    assert runner.state.pending_upload is None
    assert service.calls[0]["message"] == "process it"
    assert Path(service.calls[0]["upload"].source_path) == upload_path
    assert runner.state.uploaded_files[0]["file_name"] == "input.csv"


@pytest.mark.anyio
async def test_replay_mode_executes_simple_yaml_script(tmp_path):
    upload_path = tmp_path / "input.csv"
    upload_path.write_text("A\n1\n", encoding="utf-8")
    script_path = tmp_path / "flow.yaml"
    script_path.write_text(
        "\n".join(
            [
                "steps:",
                f"  - upload: {upload_path}",
                "  - user: process it",
                "    expect:",
                "      contains: done",
                "      artifact_kinds: [table]",
                "      payload_types: [table]",
            ]
        ),
        encoding="utf-8",
    )
    service = FakeCliService()
    runner = TerminalChatRunner(service=service, quiet=True)

    await runner.run_script(script_path)

    assert len(service.calls) == 1
    assert service.calls[0]["message"] == "process it"
    assert Path(service.calls[0]["upload"].source_path) == upload_path
    assert runner.state.turns[0]["artifact_summaries"][0]["kind"] == "table"

