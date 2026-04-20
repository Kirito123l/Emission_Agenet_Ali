"""Shared chat/session execution service for API, web, and CLI entrypoints."""
from __future__ import annotations

import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.artifact_summary import ArtifactSummary, summarize_frontend_artifacts
from services.response_utils import attach_download_to_table_data, clean_reply_text, normalize_download_file


TEMP_DIR = Path(tempfile.gettempdir()) / "emission_agent"
TEMP_DIR.mkdir(exist_ok=True)

ROUTER_MODES = {"full", "naive", "governed_v2"}


class UnsupportedRouterMode(ValueError):
    """Raised when a caller asks for an unknown router mode."""


@dataclass
class UploadedFileInput:
    """Upload input accepted by the shared runner.

    API callers pass ``content`` from ``UploadFile``. CLI callers usually pass
    ``source_path`` and let the service stage the file in the same temp area
    used by the web workflow.
    """

    filename: Optional[str] = None
    content: Optional[bytes] = None
    source_path: Optional[str | Path] = None

    @classmethod
    def from_path(cls, path: str | Path) -> "UploadedFileInput":
        resolved = Path(path).expanduser()
        return cls(filename=resolved.name, source_path=resolved)

    def read_bytes(self) -> bytes:
        if self.content is not None:
            return self.content
        if self.source_path is None:
            raise ValueError("UploadedFileInput requires either content or source_path")
        return Path(self.source_path).expanduser().read_bytes()

    def resolved_filename(self) -> Optional[str]:
        if self.filename:
            return self.filename
        if self.source_path is not None:
            return Path(self.source_path).name
        return None


@dataclass
class StoredUpload:
    """Upload staged for router execution."""

    file_name: str
    file_path: str
    file_size: int
    source_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "file_name": self.file_name,
            "file_path": self.file_path,
            "file_size": self.file_size,
        }
        if self.source_path:
            payload["source_path"] = self.source_path
        return payload


@dataclass
class ChatTurnResult:
    """Transport-neutral result for one chat turn."""

    session_id: str
    message_id: str
    reply: str
    raw_reply: str
    success: bool = True
    data_type: Optional[str] = None
    chart_data: Optional[Dict[str, Any]] = None
    table_data: Optional[Dict[str, Any]] = None
    map_data: Optional[Dict[str, Any]] = None
    file_id: Optional[str] = None
    download_file: Optional[Dict[str, Any]] = None
    trace: Optional[Dict[str, Any]] = None
    trace_friendly: Optional[List[Dict[str, Any]]] = None
    uploaded_file: Optional[StoredUpload] = None
    router_mode: str = "full"
    turn_index: int = 0
    debug: Dict[str, Any] = field(default_factory=dict)
    artifact_summaries: List[ArtifactSummary] = field(default_factory=list)

    def to_api_response(self) -> Dict[str, Any]:
        return {
            "reply": self.reply,
            "session_id": self.session_id,
            "success": self.success,
            "data_type": self.data_type,
            "chart_data": self.chart_data,
            "table_data": self.table_data,
            "map_data": self.map_data,
            "file_id": self.file_id,
            "download_file": self.download_file,
            "message_id": self.message_id,
            "trace": self.trace,
            "trace_friendly": self.trace_friendly,
        }

    def to_log_record(self, *, user_input: Optional[str] = None) -> Dict[str, Any]:
        payload = {
            "turn_index": self.turn_index,
            "session_id": self.session_id,
            "message_id": self.message_id,
            "router_mode": self.router_mode,
            "success": self.success,
            "final_text": self.reply,
            "uploaded_file": self.uploaded_file.to_dict() if self.uploaded_file else None,
            "data_type": self.data_type,
            "artifact_summaries": [item.to_dict() for item in self.artifact_summaries],
            "frontend_payloads": {
                "chart_data": self.chart_data,
                "table_data": self.table_data,
                "map_data": self.map_data,
                "download_file": self.download_file,
            },
            "debug": self.debug,
        }
        if user_input is not None:
            payload["user_input"] = user_input
        return payload


class ChatSessionService:
    """Shared per-turn chat orchestration used by API routes and CLI tools."""

    def __init__(self, session_manager: Any, *, user_id: str = "cli"):
        self.session_manager = session_manager
        self.user_id = user_id

    async def process_turn(
        self,
        *,
        message: str,
        session_id: Optional[str] = None,
        upload: Optional[UploadedFileInput] = None,
        mode: str = "full",
    ) -> ChatTurnResult:
        router_mode = normalize_router_mode(mode)
        original_message = message
        session = self.session_manager.get_or_create_session(session_id)

        stored_upload = self._stage_upload(session.session_id, upload) if upload else None
        input_file_path = Path(stored_upload.file_path) if stored_upload else None
        message_with_file = build_router_user_message(original_message, input_file_path, router_mode)

        result = await session.chat(message_with_file, input_file_path, mode=router_mode)

        # Preserve the existing API/web history semantics. The first increment
        # keeps title generation behavior aligned with the current route; the
        # save_turn call below performs the existing persisted-history update.
        session.message_count += 1
        session.updated_at = datetime.now().isoformat()
        self.session_manager.update_session_title(
            session.session_id,
            build_session_title_source(
                original_message,
                stored_upload.file_name if stored_upload else None,
            ),
        )

        raw_reply = result.get("text", "") or ""
        chart_data = result.get("chart_data")
        table_data = result.get("table_data")
        map_data = result.get("map_data")
        trace = result.get("trace")
        trace_friendly = result.get("trace_friendly")
        assistant_message_id = uuid.uuid4().hex[:12]
        download_file = normalize_download_file(
            result.get("download_file"),
            session.session_id,
            assistant_message_id,
            self.user_id,
        )
        data_type = infer_data_type(chart_data=chart_data, table_data=table_data, map_data=map_data)
        table_data = attach_download_to_table_data(table_data, download_file)

        if download_file:
            session.last_result_file = download_file

        session.save_turn(
            user_input=original_message,
            assistant_response=raw_reply,
            file_name=stored_upload.file_name if stored_upload else None,
            file_path=stored_upload.file_path if stored_upload else None,
            file_size=stored_upload.file_size if stored_upload else None,
            chart_data=chart_data,
            table_data=table_data,
            map_data=map_data,
            data_type=data_type,
            file_id=session.session_id if download_file else None,
            download_file=download_file,
            message_id=assistant_message_id,
            trace_friendly=trace_friendly,
        )
        self.session_manager.save_session()

        artifact_summaries = summarize_frontend_artifacts(
            chart_data=chart_data,
            table_data=table_data,
            map_data=map_data,
            download_file=download_file,
        )
        debug = build_debug_summary(
            raw_result=result,
            mode=router_mode,
            message_with_file=message_with_file,
            uploaded_file=stored_upload,
            artifact_summaries=artifact_summaries,
        )

        return ChatTurnResult(
            session_id=session.session_id,
            message_id=assistant_message_id,
            reply=clean_reply_text(raw_reply),
            raw_reply=raw_reply,
            success=True,
            data_type=data_type,
            chart_data=chart_data,
            table_data=table_data,
            map_data=map_data,
            file_id=session.session_id if download_file else None,
            download_file=download_file,
            trace=trace,
            trace_friendly=trace_friendly,
            uploaded_file=stored_upload,
            router_mode=router_mode,
            turn_index=session.message_count,
            debug=debug,
            artifact_summaries=artifact_summaries,
        )

    def _stage_upload(self, session_id: str, upload: UploadedFileInput) -> StoredUpload:
        raw_filename = upload.resolved_filename()
        safe_name = sanitize_uploaded_filename(raw_filename) or "upload"
        suffix = Path(safe_name).suffix
        input_file_path = TEMP_DIR / f"{session_id}_input{suffix}"

        content = upload.read_bytes()
        with input_file_path.open("wb") as fh:
            fh.write(content)

        source_path = str(Path(upload.source_path).expanduser()) if upload.source_path is not None else None
        return StoredUpload(
            file_name=safe_name,
            file_path=str(input_file_path),
            file_size=len(content),
            source_path=source_path,
        )


def normalize_router_mode(mode: Optional[str]) -> str:
    normalized = str(mode or "full").strip().lower()
    if not normalized:
        return "full"
    if normalized not in ROUTER_MODES:
        raise UnsupportedRouterMode(f"Unsupported router mode: {mode}")
    return normalized


def build_router_user_message(original_message: str, input_file_path: Optional[Path], mode: str) -> str:
    if not input_file_path:
        return original_message
    if mode == "naive":
        return f"{original_message}\n\n文件已上传，路径: {str(input_file_path)}"
    return f"{original_message}\n\n文件已上传，路径: {str(input_file_path)}\n请使用 input_file 参数处理此文件。"


def sanitize_uploaded_filename(filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    return Path(str(filename).strip()).name or None


def build_session_title_source(message: str, uploaded_file_name: Optional[str]) -> str:
    clean_message = (message or "").strip()
    if clean_message:
        return clean_message
    if uploaded_file_name:
        return f"上传文件：{uploaded_file_name}"
    return "新对话"


def infer_data_type(
    *,
    chart_data: Optional[Dict[str, Any]],
    table_data: Optional[Dict[str, Any]],
    map_data: Optional[Dict[str, Any]],
) -> Optional[str]:
    if chart_data:
        return "chart"
    if table_data and map_data:
        return "table_and_map"
    if table_data:
        return "table"
    if map_data:
        return "map"
    return None


def build_debug_summary(
    *,
    raw_result: Dict[str, Any],
    mode: str,
    message_with_file: str,
    uploaded_file: Optional[StoredUpload],
    artifact_summaries: List[ArtifactSummary],
) -> Dict[str, Any]:
    trace = raw_result.get("trace") if isinstance(raw_result.get("trace"), dict) else {}
    steps = trace.get("steps") if isinstance(trace.get("steps"), list) else []
    executed_tool_calls = raw_result.get("executed_tool_calls") or []

    selected_tools: List[str] = []
    tool_calls: List[Dict[str, Any]] = []
    readiness: List[Dict[str, Any]] = []
    context_injections: List[Dict[str, Any]] = []
    detected_intents: List[Dict[str, Any]] = []

    for step in steps:
        if not isinstance(step, dict):
            continue
        step_type = str(step.get("step_type") or "")
        action = step.get("action")
        compact_step = _compact_trace_step(step)

        if step_type in {"tool_selection", "tool_execution"} and action:
            if action not in selected_tools:
                selected_tools.append(str(action))
        if step_type == "tool_execution":
            tool_calls.append(compact_step)
        if "readiness" in step_type or "blocked" in step_type or "repair" in step_type:
            readiness.append(compact_step)
        if (
            "file_" in step_type
            or "injected" in step_type
            or "artifact_memory" in step_type
            or step_type in {"summary_delivery_applied", "artifact_recorded"}
        ):
            context_injections.append(compact_step)
        if "intent" in step_type:
            detected_intents.append(compact_step)

    for call in executed_tool_calls:
        compact_call = _compact_tool_call(call)
        name = compact_call.get("name")
        if name and name not in selected_tools:
            selected_tools.append(str(name))
        if compact_call not in tool_calls:
            tool_calls.append(compact_call)

    payload_types = []
    if raw_result.get("chart_data"):
        payload_types.append("chart")
    if raw_result.get("table_data"):
        payload_types.append("table")
    map_data = raw_result.get("map_data")
    if map_data:
        if isinstance(map_data, dict) and map_data.get("type") == "map_collection":
            map_types = [
                str(item.get("type") or "map")
                for item in map_data.get("items", [])
                if isinstance(item, dict)
            ]
            payload_types.extend([f"map:{item}" for item in map_types] or ["map"])
        elif isinstance(map_data, dict):
            payload_types.append(f"map:{map_data.get('type') or 'map'}")
        else:
            payload_types.append("map")
    if raw_result.get("download_file"):
        payload_types.append("download")

    return {
        "router_mode": mode,
        "message_with_file": _truncate_text(message_with_file, 400),
        "uploaded_file": uploaded_file.to_dict() if uploaded_file else None,
        "detected_intents": detected_intents,
        "selected_tools": selected_tools,
        "tool_calls": tool_calls,
        "readiness": readiness,
        "context_injections": context_injections,
        "payload_types": payload_types,
        "frontend_artifacts": [item.to_dict() for item in artifact_summaries],
        "trace_final_stage": trace.get("final_stage"),
        "trace_step_count": trace.get("step_count") or len(steps),
        "trace_duration_ms": trace.get("total_duration_ms"),
        "final_text": _truncate_text(raw_result.get("text") or "", 800),
    }


def _compact_trace_step(step: Dict[str, Any]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {
        "step_type": step.get("step_type"),
    }
    for key in ("stage_before", "stage_after", "action", "reasoning", "error"):
        value = step.get(key)
        if value not in (None, ""):
            compact[key] = _truncate_value(value)
    for key in ("input_summary", "output_summary"):
        value = step.get(key)
        if isinstance(value, dict) and value:
            compact[key] = _truncate_value(value)
    return compact


def _compact_tool_call(call: Any) -> Dict[str, Any]:
    if not isinstance(call, dict):
        return {"raw": _truncate_value(call)}
    result = call.get("result") if isinstance(call.get("result"), dict) else {}
    compact: Dict[str, Any] = {
        "name": call.get("name") or call.get("tool_name"),
    }
    arguments = call.get("arguments")
    if isinstance(arguments, dict):
        compact["arguments"] = _truncate_value(arguments)
    if result:
        compact["success"] = result.get("success")
        if result.get("message"):
            compact["message"] = _truncate_text(str(result.get("message")), 240)
        if result.get("summary"):
            compact["summary"] = _truncate_text(str(result.get("summary")), 240)
        if result.get("error"):
            compact["error"] = _truncate_text(str(result.get("error")), 240)
    return compact


def _truncate_value(value: Any, *, text_limit: int = 160) -> Any:
    if isinstance(value, str):
        return _truncate_text(value, text_limit)
    if isinstance(value, dict):
        return {str(key): _truncate_value(item, text_limit=text_limit) for key, item in list(value.items())[:12]}
    if isinstance(value, list):
        return [_truncate_value(item, text_limit=text_limit) for item in value[:8]]
    return value


def _truncate_text(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."
