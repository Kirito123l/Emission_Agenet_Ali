"""Helper functions extracted from ``core.router`` for memory compaction."""

from typing import Any, Dict, List, Optional


def compact_tool_data(data: Any) -> Optional[Dict[str, Any]]:
    """Compact tool data to avoid storing large arrays in memory context."""
    if not isinstance(data, dict):
        return None

    compact: Dict[str, Any] = {}
    for key, value in data.items():
        if key in {"results", "speed_curve", "pollutants"}:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            compact[key] = value
            continue
        if key in {"query_info", "summary", "fleet_mix_fill", "download_file"} and isinstance(value, dict):
            compact[key] = value
            continue
        if key == "columns" and isinstance(value, list):
            compact[key] = value[:20]

    return compact


def build_memory_tool_calls(tool_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build compact tool-call records for memory extraction.

    Keep tool success and a compact data snapshot so follow-up turns stay grounded.
    """
    records: List[Dict[str, Any]] = []
    for item in tool_results:
        result = item.get("result", {})
        records.append(
            {
                "name": item.get("name"),
                "arguments": item.get("arguments", {}),
                "result": {
                    "success": bool(result.get("success")),
                    "summary": result.get("summary"),
                    "data": compact_tool_data(result.get("data")),
                },
            }
        )
    return records

