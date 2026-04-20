"""Terminal-first debugging runner for EmissionAgent.

This entrypoint intentionally calls the same shared chat/session service used
by the API routes. It is a debugging harness, not a separate agent path.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from api.session import SessionRegistry
from services.artifact_summary import format_artifact_summaries
from services.chat_session_service import ChatSessionService, ChatTurnResult, UploadedFileInput


HELP_TEXT = """Commands:
  /help                 Show this help
  /upload <path>        Attach a local file to the next message
  /files                Show files registered in this terminal session
  /debug on|off         Toggle developer debug output
  /show last            Show the last turn as structured JSON
  /save-log <path>      Save accumulated JSON transcript
  /reset                Start a new chat session
  /exit                 Quit

Replay YAML format:
  steps:
    - upload: test_data/example.csv
    - user: "帮我分析这个文件"
      expect:
        contains: ["完成"]
        artifact_kinds: ["table"]
        payload_types: ["table"]
"""


@dataclass
class TerminalState:
    session_id: Optional[str] = None
    pending_upload: Optional[UploadedFileInput] = None
    pending_upload_display: Optional[str] = None
    uploaded_files: List[Dict[str, Any]] = field(default_factory=list)
    turns: List[Dict[str, Any]] = field(default_factory=list)
    last_turn: Optional[ChatTurnResult] = None
    debug: bool = False


class TerminalChatRunner:
    """Interactive and replay harness backed by ChatSessionService."""

    def __init__(
        self,
        *,
        service: Optional[ChatSessionService] = None,
        user_id: str = "cli",
        mode: str = "full",
        debug: bool = False,
        quiet: bool = False,
        json_log: Optional[str | Path] = None,
    ):
        self.user_id = user_id
        self.mode = mode
        self.quiet = quiet
        self.json_log = Path(json_log).expanduser() if json_log else None
        self.state = TerminalState(debug=debug)
        self.service = service or ChatSessionService(SessionRegistry.get(user_id), user_id=user_id)

    async def repl(self) -> None:
        self._print("EmissionAgent terminal runner. Type /help for commands.")
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                self._print("")
                break
            if not line:
                continue
            should_continue = await self.handle_line(line)
            if not should_continue:
                break

    async def run_script(self, script_path: str | Path) -> None:
        steps = load_script_steps(script_path)
        for index, step in enumerate(steps, start=1):
            if isinstance(step, str):
                line = step
                self._print(f"[Script {index}] {line}")
                should_continue = await self.handle_line(line)
                if not should_continue:
                    break
                continue

            if not isinstance(step, dict):
                raise ValueError(f"Unsupported script step at index {index}: {step!r}")

            if "debug" in step:
                self.state.debug = _as_bool(step["debug"])
                self._print(f"[Script {index}] debug={'on' if self.state.debug else 'off'}")
                continue

            if "upload" in step and not any(key in step for key in ("user", "message", "input")):
                self.register_upload(step["upload"])
                self._print(f"[Script {index}] upload {step['upload']}")
                continue

            message = step.get("user", step.get("message", step.get("input")))
            if message is None:
                raise ValueError(f"Script step {index} needs one of: upload, user, message, input, debug")

            upload = None
            if step.get("upload"):
                upload = self._resolve_upload(step["upload"])
            turn = await self.send_message(str(message), upload=upload)
            check_expectations(turn, step.get("expect") or {})

    async def handle_line(self, line: str) -> bool:
        if not line.startswith("/"):
            await self.send_message(line)
            return True

        command, *args = shlex.split(line)
        command = command.lower()

        if command == "/help":
            self._print(HELP_TEXT)
        elif command == "/upload":
            if not args:
                self._print("Usage: /upload <path>")
            else:
                self.register_upload(args[0])
        elif command == "/files":
            self.show_files()
        elif command == "/debug":
            if not args or args[0].lower() not in {"on", "off"}:
                self._print(f"debug is {'on' if self.state.debug else 'off'}")
            else:
                self.state.debug = args[0].lower() == "on"
                self._print(f"debug {'on' if self.state.debug else 'off'}")
        elif command == "/show":
            if args and args[0].lower() == "last":
                self.show_last()
            else:
                self._print("Usage: /show last")
        elif command == "/save-log":
            if not args:
                self._print("Usage: /save-log <path>")
            else:
                self.save_log(args[0])
        elif command == "/reset":
            self.reset()
        elif command in {"/exit", "/quit"}:
            return False
        else:
            self._print(f"Unknown command: {command}. Type /help.")
        return True

    async def send_message(
        self,
        message: str,
        *,
        upload: Optional[UploadedFileInput] = None,
    ) -> ChatTurnResult:
        upload_to_send = upload or self.state.pending_upload
        upload_display = None
        if upload_to_send is self.state.pending_upload:
            upload_display = self.state.pending_upload_display
            self.state.pending_upload = None
            self.state.pending_upload_display = None
        elif upload_to_send is not None:
            upload_display = upload_to_send.resolved_filename()

        if not self.quiet:
            self._print(f"\n[User] {message}")
            if upload_display:
                self._print(f"[Upload] {upload_display}")

        turn = await self.service.process_turn(
            message=message,
            session_id=self.state.session_id,
            upload=upload_to_send,
            mode=self.mode,
        )
        self.state.session_id = turn.session_id
        self.state.last_turn = turn

        if turn.uploaded_file:
            self.state.uploaded_files.append(turn.uploaded_file.to_dict())

        record = turn.to_log_record(user_input=message)
        self.state.turns.append(record)
        self._append_json_log(record)

        self.render_turn(turn)
        return turn

    def register_upload(self, path: str | Path) -> None:
        upload = self._resolve_upload(path)
        self.state.pending_upload = upload
        self.state.pending_upload_display = str(Path(path).expanduser())
        self._print(f"Attached to next turn: {self.state.pending_upload_display}")

    def show_files(self) -> None:
        lines = ["[Files]"]
        if self.state.pending_upload_display:
            lines.append(f"pending: {self.state.pending_upload_display}")
        if not self.state.uploaded_files:
            lines.append("uploaded: none")
        else:
            for index, item in enumerate(self.state.uploaded_files, start=1):
                source = item.get("source_path") or item.get("file_path")
                lines.append(f"{index}) {item.get('file_name')} -> {source}")
        self._print("\n".join(lines))

    def show_last(self) -> None:
        if not self.state.last_turn:
            self._print("No turns yet.")
            return
        self._print(json.dumps(self.state.last_turn.to_log_record(), ensure_ascii=False, indent=2, default=str))

    def save_log(self, path: str | Path) -> None:
        output_path = Path(path).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(self.state.turns, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        self._print(f"Saved log: {output_path}")

    def reset(self) -> None:
        manager = getattr(self.service, "session_manager", None)
        if manager is not None and hasattr(manager, "create_session"):
            self.state.session_id = manager.create_session()
        else:
            self.state.session_id = None
        self.state.pending_upload = None
        self.state.pending_upload_display = None
        self.state.last_turn = None
        self._print(f"Started new session: {self.state.session_id or '(created on first message)'}")

    def render_turn(self, turn: ChatTurnResult) -> None:
        if self.quiet:
            if turn.reply:
                self._print(turn.reply)
            return

        self._print("\n[Assistant]")
        self._print(turn.reply or "(empty reply)")

        artifact_block = format_artifact_summaries(turn.artifact_summaries)
        if artifact_block:
            self._print("")
            self._print(artifact_block)

        if self.state.debug:
            self._print("")
            self._print(format_debug_block(turn.debug))

    def _resolve_upload(self, path: str | Path) -> UploadedFileInput:
        resolved = Path(path).expanduser()
        if not resolved.exists():
            raise FileNotFoundError(f"Upload path does not exist: {resolved}")
        if not resolved.is_file():
            raise ValueError(f"Upload path is not a file: {resolved}")
        return UploadedFileInput.from_path(resolved)

    def _append_json_log(self, record: Dict[str, Any]) -> None:
        if not self.json_log:
            return
        self.json_log.parent.mkdir(parents=True, exist_ok=True)
        with self.json_log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def _print(self, text: str) -> None:
        print(text)


def load_script_steps(script_path: str | Path) -> List[Any]:
    path = Path(script_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Script not found: {path}")

    if path.suffix.lower() in {".yaml", ".yml"}:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            raise ValueError("YAML replay script must be a mapping or a list")
        steps = payload.get("steps")
        if not isinstance(steps, list):
            raise ValueError("YAML replay script must contain a list under 'steps'")
        return steps

    lines = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def check_expectations(turn: ChatTurnResult, expect: Dict[str, Any]) -> None:
    if not expect:
        return

    if "success" in expect and bool(expect["success"]) != turn.success:
        raise AssertionError(f"Expected success={expect['success']}, got {turn.success}")

    for needle in _as_list(expect.get("contains")):
        if str(needle) not in turn.reply:
            raise AssertionError(f"Expected reply to contain {needle!r}")

    for needle in _as_list(expect.get("not_contains")):
        if str(needle) in turn.reply:
            raise AssertionError(f"Expected reply not to contain {needle!r}")

    artifact_kinds = {item.kind for item in turn.artifact_summaries}
    for kind in _as_list(expect.get("artifact_kinds")):
        if str(kind) not in artifact_kinds:
            raise AssertionError(f"Expected artifact kind {kind!r}, got {sorted(artifact_kinds)}")

    artifact_types = {item.artifact_type for item in turn.artifact_summaries}
    for artifact_type in _as_list(expect.get("artifact_types")):
        if str(artifact_type) not in artifact_types:
            raise AssertionError(f"Expected artifact type {artifact_type!r}, got {sorted(artifact_types)}")

    payload_types = set(turn.debug.get("payload_types") or [])
    for payload_type in _as_list(expect.get("payload_types")):
        if str(payload_type) not in payload_types:
            raise AssertionError(f"Expected payload type {payload_type!r}, got {sorted(payload_types)}")


def format_debug_block(debug: Dict[str, Any]) -> str:
    lines = ["[Debug]"]
    lines.append(f"mode: {debug.get('router_mode')}")
    if debug.get("trace_final_stage") or debug.get("trace_step_count"):
        lines.append(
            f"trace: final_stage={debug.get('trace_final_stage')}, "
            f"steps={debug.get('trace_step_count')}, duration_ms={debug.get('trace_duration_ms')}"
        )
    if debug.get("payload_types"):
        lines.append(f"payload_types: {', '.join(debug['payload_types'])}")
    if debug.get("selected_tools"):
        lines.append(f"selected_tools: {', '.join(debug['selected_tools'])}")
    if debug.get("readiness"):
        lines.append("readiness:")
        lines.extend(_format_compact_items(debug["readiness"]))
    if debug.get("tool_calls"):
        lines.append("tool_calls:")
        lines.extend(_format_compact_items(debug["tool_calls"]))
    if debug.get("context_injections"):
        lines.append("context:")
        lines.extend(_format_compact_items(debug["context_injections"]))
    if debug.get("frontend_artifacts"):
        lines.append(f"frontend_artifacts: {len(debug['frontend_artifacts'])}")
    if debug.get("final_text"):
        lines.append(f"final_text: {debug['final_text']}")
    return "\n".join(lines)


def _format_compact_items(items: Iterable[Dict[str, Any]]) -> List[str]:
    lines = []
    for item in list(items)[:8]:
        label = item.get("name") or item.get("action") or item.get("step_type") or "item"
        details = []
        if item.get("success") is not None:
            details.append(f"success={item.get('success')}")
        if item.get("reasoning"):
            details.append(f"reason={item.get('reasoning')}")
        if item.get("error"):
            details.append(f"error={item.get('error')}")
        suffix = f" ({'; '.join(details)})" if details else ""
        lines.append(f"- {label}{suffix}")
    return lines


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run EmissionAgent chat in the terminal.")
    parser.add_argument("--script", help="Replay a YAML/YML or TXT conversation script")
    parser.add_argument("--session-id", help="Reuse an existing session id")
    parser.add_argument("--user-id", default="cli", help="Session namespace user id")
    parser.add_argument("--mode", default="full", choices=["full", "naive"], help="Router mode")
    parser.add_argument("--debug", action="store_true", help="Show developer debug blocks")
    parser.add_argument("--quiet", action="store_true", help="Print only assistant text")
    parser.add_argument("--json-log", help="Append structured turn records to JSONL")
    return parser.parse_args(argv)


async def async_main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    runner = TerminalChatRunner(
        user_id=args.user_id,
        mode=args.mode,
        debug=args.debug,
        quiet=args.quiet,
        json_log=args.json_log,
    )
    runner.state.session_id = args.session_id

    try:
        if args.script:
            await runner.run_script(args.script)
        else:
            await runner.repl()
    except Exception as exc:
        print(f"run_code.py failed: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())

