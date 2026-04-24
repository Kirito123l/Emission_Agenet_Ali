"""Structured data-quality report schema for CSV inspection tools."""

from __future__ import annotations

import math
from dataclasses import MISSING, dataclass, field, fields
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Type, TypeVar


T = TypeVar("T")


@dataclass
class ColumnInfo:
    """Column-level data-quality facts for a CSV file."""

    name: str
    dtype: str
    non_null_count: int
    unique_count: int
    sample_values: List[Any]
    mean: Optional[float] = None
    std: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "dtype": self.dtype,
            "non_null_count": int(self.non_null_count),
            "unique_count": int(self.unique_count),
            "sample_values": [_json_safe_value(value) for value in self.sample_values],
            "mean": _json_safe_float(self.mean),
            "std": _json_safe_float(self.std),
            "min": _json_safe_float(self.min),
            "max": _json_safe_float(self.max),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ColumnInfo":
        payload = _strict_payload(cls, data)
        return cls(
            name=str(payload["name"]),
            dtype=str(payload["dtype"]),
            non_null_count=int(payload["non_null_count"]),
            unique_count=int(payload["unique_count"]),
            sample_values=list(payload["sample_values"] or []),
            mean=_optional_float(payload.get("mean")),
            std=_optional_float(payload.get("std")),
            min=_optional_float(payload.get("min")),
            max=_optional_float(payload.get("max")),
        )


@dataclass
class CleanDataFrameReport:
    """Stable report schema produced by the clean_dataframe tool."""

    file_path: str
    row_count: int
    column_count: int
    columns: List[ColumnInfo]
    missing_summary: Dict[str, int]
    encoding_detected: str
    generated_at: str
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "row_count": int(self.row_count),
            "column_count": int(self.column_count),
            "columns": [column.to_dict() for column in self.columns],
            "missing_summary": {
                str(key): int(value)
                for key, value in self.missing_summary.items()
            },
            "encoding_detected": self.encoding_detected,
            "generated_at": self.generated_at,
            "extra": _json_safe_mapping(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CleanDataFrameReport":
        payload = _strict_payload(cls, data)
        return cls(
            file_path=str(payload["file_path"]),
            row_count=int(payload["row_count"]),
            column_count=int(payload["column_count"]),
            columns=[
                ColumnInfo.from_dict(item)
                for item in list(payload["columns"] or [])
            ],
            missing_summary={
                str(key): int(value)
                for key, value in dict(payload["missing_summary"]).items()
            },
            encoding_detected=str(payload["encoding_detected"]),
            generated_at=str(payload["generated_at"]),
            extra=dict(payload.get("extra") or {}),
        )


def _strict_payload(cls: Type[T], data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError(f"{cls.__name__}.from_dict expected dict, got {type(data).__name__}")

    dataclass_fields = fields(cls)
    known_fields = {item.name for item in dataclass_fields}
    unknown = set(data.keys()) - known_fields
    if unknown:
        raise ValueError(
            f"{cls.__name__}.from_dict received unknown fields: {sorted(unknown)}. "
            f"This indicates schema drift or a developer typo. "
            f"If you need to add a core field, update the dataclass definition and "
            f"all to_dict/from_dict producers/consumers. "
            f"If you need to store arbitrary extension data, use the 'extra' dict."
        )

    payload = dict(data)
    missing = [
        item.name
        for item in dataclass_fields
        if item.name not in payload
        and item.default is MISSING
        and item.default_factory is MISSING
    ]
    if missing:
        raise ValueError(
            f"{cls.__name__}.from_dict missing required fields: {sorted(missing)}"
        )
    return payload


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _json_safe_float(value: Any) -> Optional[float]:
    return _optional_float(value)


def _json_safe_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return _json_safe_mapping(value)
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    return value


def _json_safe_mapping(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        str(key): _json_safe_value(value)
        for key, value in dict(payload or {}).items()
    }
