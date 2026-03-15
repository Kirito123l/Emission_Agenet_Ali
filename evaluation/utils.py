"""Common utilities for local benchmark execution."""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def resolve_project_path(relative_or_abs: Optional[str]) -> Optional[Path]:
    if not relative_or_abs:
        return None
    path = Path(relative_or_abs)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


@contextmanager
def runtime_overrides(**overrides: Any) -> Iterator[Any]:
    """Temporarily override runtime config fields."""
    from config import get_config

    config = get_config()
    previous = {key: getattr(config, key) for key in overrides}
    try:
        for key, value in overrides.items():
            setattr(config, key, value)
        yield config
    finally:
        for key, value in previous.items():
            setattr(config, key, value)


def rebuild_tool_registry() -> None:
    """Reinitialize tool instances so new runtime flags take effect."""
    from tools.registry import get_registry, init_tools

    registry = get_registry()
    registry.clear()
    init_tools()


def now_ts() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def subset_dict(data: Dict[str, Any], keys: Iterable[str]) -> Dict[str, Any]:
    return {key: data.get(key) for key in keys if key in data}


def compare_expected_subset(actual: Dict[str, Any], expected: Dict[str, Any]) -> Dict[str, Any]:
    matched = True
    details: Dict[str, Any] = {}
    for key, exp_value in expected.items():
        act_value = actual.get(key)
        if isinstance(exp_value, list) and isinstance(act_value, list):
            equal = act_value == exp_value
        elif isinstance(exp_value, dict) and isinstance(act_value, dict):
            nested = compare_expected_subset(act_value, exp_value)
            equal = nested["matched"]
            details[key] = nested
        else:
            equal = act_value == exp_value
        if key not in details:
            details[key] = {
                "expected": exp_value,
                "actual": act_value,
                "matched": equal,
            }
        matched = matched and equal
    return {"matched": matched, "details": details}


def classify_failure(record: Dict[str, Any]) -> str:
    if record.get("success"):
        return "success"
    error_type = (record.get("error_type") or "").lower()
    message = str(record.get("message") or record.get("error") or "").lower()
    if "standard" in error_type or "cannot recognize" in message:
        return "参数错误"
    if "route" in error_type or "tool" in message and "unknown" in message:
        return "错误路由"
    if "mapping" in message or "列" in message:
        return "列映射失败"
    if "missing required" in message or "缺少" in message:
        return "缺失必要字段"
    if "execution" in error_type or "failed" in message:
        return "工具执行异常"
    return "输出不完整"


def classify_recoverability(failure_type: str) -> str:
    if failure_type in {"参数错误", "错误路由", "列映射失败", "缺失必要字段", "输出不完整"}:
        return "可恢复失败"
    if failure_type == "success":
        return "success"
    return "不可恢复失败"


def safe_div(numerator: float, denominator: float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator
