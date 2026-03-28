"""
Parameter override engine for scenario simulation.

Supports three override modes:
1. Global set/scale/add
2. Conditional overrides with where clauses
3. Fleet composition overrides with automatic normalization
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


class OverrideValidationError(Exception):
    """Raised when an override specification is invalid for the input data."""


OVERRIDABLE_COLUMNS: Dict[str, Dict[str, Any]] = {
    "avg_speed_kph": {
        "min": 1.0,
        "max": 200.0,
        "type": "numeric",
        "description": "Average speed (km/h)",
    },
    "traffic_flow_vph": {
        "min": 0.0,
        "max": 50000.0,
        "type": "numeric",
        "description": "Traffic flow (vehicles/hour)",
    },
    "link_length_km": {
        "min": 0.01,
        "max": 100.0,
        "type": "numeric",
        "description": "Link length (km)",
    },
    "fleet_mix": {
        "type": "fleet_mix",
        "description": "Vehicle fleet composition",
    },
}

ALLOWED_TRANSFORMS: Dict[str, Dict[str, Any]] = {
    "set": {"requires": ["value"]},
    "multiply": {"requires": ["factor"]},
    "add": {"requires": ["offset"]},
}

ALLOWED_OPERATORS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "in": lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
}

KNOWN_FLEET_CATEGORIES = {
    "Passenger Car",
    "Passenger Truck",
    "Light Commercial Truck",
    "Transit Bus",
    "Combination Long-haul Truck",
}


def validate_overrides(overrides: List[Dict[str, Any]]) -> List[str]:
    """Validate override specifications and return a flat error list."""
    errors: List[str] = []
    if not isinstance(overrides, list):
        return ["overrides must be a list"]

    for index, override in enumerate(overrides):
        prefix = f"override[{index}]"
        if not isinstance(override, dict):
            errors.append(f"{prefix}: must be an object")
            continue

        column = override.get("column")
        if column not in OVERRIDABLE_COLUMNS:
            errors.append(
                f"{prefix}: column '{column}' is not overridable; "
                f"allowed={list(OVERRIDABLE_COLUMNS.keys())}"
            )
            continue

        column_spec = OVERRIDABLE_COLUMNS[column]
        where = override.get("where")
        if where is not None:
            if not isinstance(where, dict):
                errors.append(f"{prefix}: where must be an object")
            else:
                if not where.get("column"):
                    errors.append(f"{prefix}: where.column is required")
                op = where.get("op")
                if op not in ALLOWED_OPERATORS:
                    errors.append(
                        f"{prefix}: where.op '{op}' not in {list(ALLOWED_OPERATORS.keys())}"
                    )
                if "value" not in where:
                    errors.append(f"{prefix}: where.value is required")

        if column_spec["type"] == "fleet_mix":
            value = override.get("value")
            if not isinstance(value, dict):
                errors.append(f"{prefix}: fleet_mix value must be an object")
                continue

            unknown = sorted(set(value.keys()) - KNOWN_FLEET_CATEGORIES)
            if unknown:
                errors.append(f"{prefix}: unknown fleet categories: {unknown}")

            total = 0.0
            for category, pct in value.items():
                if not isinstance(pct, (int, float)) or pct < 0:
                    errors.append(
                        f"{prefix}: fleet_mix['{category}'] must be a non-negative number"
                    )
                    continue
                total += float(pct)
            if total < 90 or total > 110:
                errors.append(
                    f"{prefix}: fleet_mix percentages sum to {total:.1f}%, expected about 100%"
                )
            continue

        transform = override.get("transform", "set")
        if transform not in ALLOWED_TRANSFORMS:
            errors.append(
                f"{prefix}: unknown transform '{transform}'; allowed={list(ALLOWED_TRANSFORMS.keys())}"
            )
            continue

        if transform == "set":
            value = override.get("value")
            if not isinstance(value, (int, float)):
                errors.append(f"{prefix}: value must be numeric")
            else:
                numeric = float(value)
                if numeric < column_spec["min"] or numeric > column_spec["max"]:
                    errors.append(
                        f"{prefix}: value {numeric} out of range "
                        f"[{column_spec['min']}, {column_spec['max']}]"
                    )
        elif transform == "multiply":
            factor = override.get("factor")
            if factor is None:
                errors.append(f"{prefix}: multiply requires factor")
            elif not isinstance(factor, (int, float)):
                errors.append(f"{prefix}: factor must be numeric")
            elif float(factor) <= 0:
                errors.append(f"{prefix}: factor must be positive")
        elif transform == "add":
            offset = override.get("offset")
            if offset is None:
                errors.append(f"{prefix}: add requires offset")
            elif not isinstance(offset, (int, float)):
                errors.append(f"{prefix}: offset must be numeric")

    return errors


def apply_overrides(
    links_data: List[Dict[str, Any]],
    overrides: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Apply validated overrides to links_data and return a copied result plus summaries."""
    modified = copy.deepcopy(links_data)
    if not modified or not overrides:
        return modified, []

    df = pd.DataFrame(modified)
    summaries: List[str] = []

    for index, override in enumerate(overrides):
        column = override["column"]
        if column not in OVERRIDABLE_COLUMNS:
            raise OverrideValidationError(f"override[{index}]: unsupported column {column}")

        where = override.get("where")
        mask = _build_mask(df, where, index)
        affected_count = int(mask.sum())

        if OVERRIDABLE_COLUMNS[column]["type"] == "fleet_mix":
            fleet_mix = _normalize_fleet_mix(override["value"])
            target_indices = list(df.index[mask])
            for row_index in target_indices:
                modified[row_index]["fleet_mix"] = dict(fleet_mix)
            desc = f"车队组成: {fleet_mix}（{affected_count}/{len(modified)} 行）"
            summaries.append(desc)
            continue

        if column not in df.columns:
            raise OverrideValidationError(
                f"override[{index}]: target column '{column}' not found in links_data"
            )

        transform = override.get("transform", "set")
        if transform == "set":
            value = float(override["value"])
            df.loc[mask, column] = value
            summaries.append(f"{column}: 设为 {value:g}（{affected_count}/{len(df)} 行）")
        elif transform == "multiply":
            factor = float(override["factor"])
            df.loc[mask, column] = pd.to_numeric(df.loc[mask, column], errors="coerce") * factor
            summaries.append(f"{column}: × {factor:g}（{affected_count}/{len(df)} 行）")
        elif transform == "add":
            offset = float(override["offset"])
            df.loc[mask, column] = pd.to_numeric(df.loc[mask, column], errors="coerce") + offset
            summaries.append(f"{column}: + {offset:g}（{affected_count}/{len(df)} 行）")
        else:
            raise OverrideValidationError(f"override[{index}]: unsupported transform '{transform}'")

        spec = OVERRIDABLE_COLUMNS[column]
        numeric_series = pd.to_numeric(df[column], errors="coerce")
        clamped = numeric_series.clip(lower=spec["min"], upper=spec["max"])
        clamped_count = int((clamped != numeric_series).fillna(False).sum())
        df[column] = clamped
        if clamped_count:
            summaries.append(
                f"  ⚠️ {clamped_count} 行被裁剪到 [{spec['min']}, {spec['max']}] 范围内"
            )

    result = df.to_dict(orient="records")
    for index, row in enumerate(modified):
        if "fleet_mix" in row:
            result[index]["fleet_mix"] = row["fleet_mix"]
    return result, summaries


def describe_overrides(overrides: List[Dict[str, Any]]) -> str:
    """Return a short human-readable description of overrides."""
    if not overrides:
        return "无参数覆盖"

    parts: List[str] = []
    for override in overrides:
        if not isinstance(override, dict):
            continue

        column = str(override.get("column", "unknown"))
        if OVERRIDABLE_COLUMNS.get(column, {}).get("type") == "fleet_mix":
            parts.append(f"车队组成: {override.get('value', {})}")
            continue

        transform = override.get("transform", "set")
        if transform == "set":
            desc = f"{column}: 设为 {override.get('value')}"
        elif transform == "multiply":
            desc = f"{column}: × {override.get('factor')}"
        else:
            desc = f"{column}: + {override.get('offset')}"

        where = override.get("where")
        if isinstance(where, dict):
            desc += (
                f"（仅 {where.get('column')} {where.get('op')} {where.get('value')} 的行）"
            )
        parts.append(desc)

    return "；".join(parts) if parts else "无参数覆盖"


def _build_mask(df: pd.DataFrame, where: Optional[Dict[str, Any]], index: int) -> pd.Series:
    if where is None:
        return pd.Series([True] * len(df), index=df.index)

    if not isinstance(where, dict):
        raise OverrideValidationError(f"override[{index}]: where must be an object")

    column = where.get("column")
    if column not in df.columns:
        raise OverrideValidationError(
            f"override[{index}]: where column '{column}' not found in links_data"
        )

    operator = where.get("op")
    if operator not in ALLOWED_OPERATORS:
        raise OverrideValidationError(f"override[{index}]: unknown where.op '{operator}'")

    value = where.get("value")
    comparator = ALLOWED_OPERATORS[operator]
    series = df[column]

    def matches(item: Any) -> bool:
        try:
            return bool(comparator(item, value))
        except Exception:
            return False

    return series.apply(matches)


def _normalize_fleet_mix(fleet_mix: Dict[str, Any]) -> Dict[str, float]:
    total = float(sum(float(value) for value in fleet_mix.values()))
    if total <= 0:
        raise OverrideValidationError("fleet_mix total must be positive")

    normalized = {
        str(category): round(float(value) * 100.0 / total, 4)
        for category, value in fleet_mix.items()
    }
    diff = round(100.0 - sum(normalized.values()), 4)
    if normalized and diff:
        first_key = next(iter(normalized))
        normalized[first_key] = round(normalized[first_key] + diff, 4)
    return normalized
