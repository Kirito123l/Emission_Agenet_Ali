"""Pure response-shaping helpers shared by API and CLI paths."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote


def friendly_error_message(error: Exception) -> str:
    """Convert low-level exceptions to user-friendly actionable messages."""
    text = str(error)
    lower = text.lower()

    connection_signals = [
        "connection error",
        "connecterror",
        "unexpected eof",
        "ssl",
        "tls",
        "timed out",
        "api_connection_error",
    ]
    if any(sig in lower for sig in connection_signals):
        return (
            "上游大模型连接失败（网络/代理异常）。请稍后重试。\n"
            "若问题持续：请检查 HTTP(S)_PROXY 配置、代理服务连通性，"
            "或暂时关闭代理后重试。"
        )

    return f"处理出错: {text}"


def clean_reply_text(reply: str) -> str:
    """Remove technical JSON/code fragments from assistant replies."""
    reply = re.sub(r"```json[\s\S]*?```", "", reply)
    reply = re.sub(r"```[\s\S]*?```", "", reply)
    reply = re.sub(r'\{[^{}]*"curve"[^{}]*\}', "", reply)
    reply = re.sub(r'\{[^{}]*"pollutants"[^{}]*\}', "", reply)
    reply = re.sub(r"\n\s*\n\s*\n", "\n\n", reply)
    return reply.strip()


def normalize_download_file(
    download_file: Optional[Any],
    session_id: str,
    message_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Normalize download metadata to a stable frontend-friendly shape."""
    if not download_file:
        return None

    path: Optional[str] = None
    filename: Optional[str] = None

    if isinstance(download_file, dict):
        path = download_file.get("path")
        filename = download_file.get("filename")
    elif isinstance(download_file, str):
        path = download_file
        filename = Path(download_file).name if download_file else None

    if not filename and path:
        filename = Path(path).name
    if not path and not filename:
        return None

    normalized: Dict[str, Any] = {
        "path": str(path) if path else None,
        "filename": filename,
        "file_id": session_id,
    }
    uid_qs = f"?user_id={quote(user_id)}" if user_id else ""
    if message_id:
        normalized["message_id"] = message_id
        normalized["url"] = f"/api/file/download/message/{session_id}/{message_id}{uid_qs}"
    elif filename:
        normalized["url"] = f"/api/download/{quote(filename)}{uid_qs}"
    return normalized


def attach_download_to_table_data(
    table_data: Optional[Dict[str, Any]],
    download_file: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Attach download metadata so table/history views can render downloads."""
    if not table_data or not isinstance(table_data, dict):
        return table_data
    if not download_file:
        return table_data

    enriched = dict(table_data)

    if not enriched.get("download"):
        url = download_file.get("url")
        filename = download_file.get("filename")
        if url and filename:
            enriched["download"] = {"url": url, "filename": filename}

    if not enriched.get("file_id") and download_file.get("file_id"):
        enriched["file_id"] = download_file["file_id"]

    return enriched


__all__ = [
    "attach_download_to_table_data",
    "clean_reply_text",
    "friendly_error_message",
    "normalize_download_file",
]

