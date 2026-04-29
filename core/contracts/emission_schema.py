"""Emission Domain Schema reader.

Single source of truth for domain-level data values. Agent code reads
through this module, never hardcodes domain values (model_year range,
season default, road_type default, etc.).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "config" / "emission_domain_schema.yaml"
_CACHE: Optional[Dict[str, Any]] = None


def _load_schema() -> Dict[str, Any]:
    global _CACHE
    if _CACHE is None:
        try:
            with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
                _CACHE = yaml.safe_load(f) or {}
        except Exception as exc:
            raise RuntimeError(
                f"emission_domain_schema.yaml not loadable: {exc}"
            ) from exc
        if not isinstance(_CACHE, dict) or "dimensions" not in _CACHE:
            raise RuntimeError(
                "emission_domain_schema.yaml missing required 'dimensions' key"
            )
    return _CACHE


def get_dimension(name: str) -> Dict[str, Any]:
    return dict(_load_schema().get("dimensions", {}).get(name, {}))


def get_default(dimension: str) -> Any:
    dim = get_dimension(dimension)
    if dim.get("default_policy") == "default":
        return dim.get("default")
    return None


def get_range(dimension: str) -> Optional[Dict[str, Any]]:
    dim = get_dimension(dimension)
    if dim.get("field_type") == "integer_range":
        r = dim.get("range")
        if isinstance(r, dict):
            return dict(r)
    return None


def get_standard_names(dimension: str) -> List[str]:
    return list(get_dimension(dimension).get("standard_names", []))


def get_display_name_zh(dimension: str) -> str:
    return get_dimension(dimension).get("display_name_zh", dimension)
