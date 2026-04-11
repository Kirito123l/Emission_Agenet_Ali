"""Common utilities for local benchmark execution."""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from functools import lru_cache
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


@lru_cache(maxsize=1)
def _get_evaluation_standardizer() -> Any:
    from services.standardizer import get_standardizer

    return get_standardizer()


_PARAM_NAME_ALIASES = {
    "vehicle": "vehicle_type",
    "vehicletype": "vehicle_type",
    "pollutant": "pollutants",
    "pollutants": "pollutants",
    "road": "road_type",
}


def _coerce_numeric(value: Any) -> Optional[float]:
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str) and value.strip():
            return float(value.strip())
    except (TypeError, ValueError):
        return None
    return None


def _normalize_param_name(key: Any) -> str:
    normalized = str(key or "").strip()
    return _PARAM_NAME_ALIASES.get(normalized, normalized)


def _canonicalize_alias(key: Optional[str], value: str) -> set[str]:
    method_names = {
        "vehicle_type": ("standardize_vehicle",),
        "pollutant": ("standardize_pollutant",),
        "pollutants": ("standardize_pollutant",),
        "season": ("standardize_season",),
        "road_type": ("standardize_road_type",),
        "meteorology": ("standardize_meteorology",),
        "stability_class": ("standardize_stability_class",),
    }.get(_normalize_param_name(str(key or "").strip().lower()), ())
    if not method_names:
        return set()

    try:
        standardizer = _get_evaluation_standardizer()
    except Exception:
        return set()

    canonical: set[str] = set()
    for method_name in method_names:
        method = getattr(standardizer, method_name, None)
        if not callable(method):
            continue
        try:
            result = method(value)
        except Exception:
            continue
        normalized = getattr(result, "normalized", None) if hasattr(result, "normalized") else result
        success = getattr(result, "success", normalized is not None)
        if success and normalized:
            canonical.add(str(normalized).strip().lower())
    return canonical


def _alias_match(key: Optional[str], actual: str, expected: str) -> bool:
    actual_canonical = _canonicalize_alias(key, actual)
    expected_canonical = _canonicalize_alias(key, expected)
    return bool(actual_canonical and expected_canonical and actual_canonical & expected_canonical)


def _list_subset_match(actual: List[Any], expected: List[Any], *, key: Optional[str] = None) -> bool:
    remaining = list(actual)
    for expected_item in expected:
        match_index = next(
            (
                index
                for index, actual_item in enumerate(remaining)
                if _flexible_match(actual_item, expected_item, key=key)
            ),
            None,
        )
        if match_index is None:
            return False
        remaining.pop(match_index)
    return True


def _flexible_match(actual: Any, expected: Any, *, key: Optional[str] = None) -> bool:
    if actual == expected:
        return True
    if expected is None:
        return actual is None
    if actual is None:
        return False

    actual_number = _coerce_numeric(actual)
    expected_number = _coerce_numeric(expected)
    if actual_number is not None and expected_number is not None:
        return actual_number == expected_number

    if isinstance(actual, dict) and isinstance(expected, dict):
        return compare_expected_subset(actual, expected)["matched"]

    if isinstance(actual, list) and not isinstance(expected, list):
        return any(_flexible_match(item, expected, key=key) for item in actual)

    if not isinstance(actual, list) and isinstance(expected, list):
        return len(expected) == 1 and _flexible_match(actual, expected[0], key=key)

    if isinstance(actual, list) and isinstance(expected, list):
        return _list_subset_match(actual, expected, key=key)

    if isinstance(actual, str) and isinstance(expected, str):
        actual_normalized = actual.strip().lower()
        expected_normalized = expected.strip().lower()
        if actual_normalized == expected_normalized:
            return True
        return _alias_match(key, actual, expected)

    return False


def compare_expected_subset(actual: Dict[str, Any], expected: Dict[str, Any]) -> Dict[str, Any]:
    if not expected:
        return {"matched": True, "details": {}}

    normalized_actual: Dict[str, Any] = {}
    for key, value in actual.items():
        normalized_key = _normalize_param_name(key)
        if normalized_key not in normalized_actual:
            normalized_actual[normalized_key] = value
            continue
        existing = normalized_actual[normalized_key]
        if existing == value:
            continue
        existing_list = existing if isinstance(existing, list) else [existing]
        incoming_list = value if isinstance(value, list) else [value]
        normalized_actual[normalized_key] = existing_list + incoming_list

    matched = True
    details: Dict[str, Any] = {}
    for original_key, exp_value in expected.items():
        key = _normalize_param_name(original_key)
        act_value = normalized_actual.get(key)
        if act_value is None:
            equal = False
            details[original_key] = {
                "expected": exp_value,
                "actual": None,
                "matched": False,
                "reason": "missing",
                "normalized_key": key,
            }
            matched = False
            continue

        if isinstance(exp_value, dict) and isinstance(act_value, dict):
            nested = compare_expected_subset(act_value, exp_value)
            equal = nested["matched"]
            details[original_key] = nested
        else:
            equal = _flexible_match(act_value, exp_value, key=key)
        if original_key not in details:
            details[original_key] = {
                "expected": exp_value,
                "actual": act_value,
                "matched": equal,
                "normalized_key": key,
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
