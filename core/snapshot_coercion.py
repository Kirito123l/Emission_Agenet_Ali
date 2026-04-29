"""Type coercion functions for snapshot-to-tool-args conversion.

Each function transforms a raw snapshot value into the typed value expected
by tool implementations.  These are referenced by name from
config/tool_contracts.yaml (type_coercion field).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def preserve(value: Any, _slot_name: str = "") -> Any:
    """Return the value unchanged (default coercion)."""
    return value


def as_list(value: Any, _slot_name: str = "") -> Optional[list[Any]]:
    """Wrap a non-list value into a single-element list."""
    if value is None:
        return None
    if isinstance(value, list):
        return list(value)
    return [value]


def safe_int(value: Any, slot_name: str = "") -> Optional[int]:
    """Convert to int, logging a warning on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning("Snapshot type coercion failed for %s=%r", slot_name, value)
        return None


def safe_float(value: Any, slot_name: str = "") -> Optional[float]:
    """Convert to float, logging a warning on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.warning("Snapshot type coercion failed for %s=%r", slot_name, value)
        return None


def as_string(value: Any, _slot_name: str = "") -> Optional[str]:
    """Convert to string."""
    if value is None:
        return None
    return str(value)


COERCION_MAP = {
    "preserve": preserve,
    "as_list": as_list,
    "safe_int": safe_int,
    "safe_float": safe_float,
    "as_string": as_string,
}


def apply_coercion(
    coercion_type: str, value: Any, slot_name: str = ""
) -> Any:
    """Apply a named coercion function to a raw snapshot value."""
    if value is None:
        return None
    fn = COERCION_MAP.get(coercion_type, preserve)
    return fn(value, slot_name)
