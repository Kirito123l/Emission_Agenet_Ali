from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

UNIFIED_MAPPINGS_PATH = Path(__file__).resolve().parents[2] / "config" / "unified_mappings.yaml"

_RUNTIME_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "query_emission_factors": {
        "model_year": 2020,
    },
}

_CACHE: Dict[str, Any] | None = None


def has_runtime_default(tool_name: str, slot_name: str) -> bool:
    return str(slot_name or "") in get_runtime_defaults(tool_name)


def get_runtime_default(tool_name: str, slot_name: str) -> Any:
    return get_runtime_defaults(tool_name).get(str(slot_name or ""))


def get_runtime_defaults(tool_name: str) -> Dict[str, Any]:
    tool = str(tool_name or "").strip()
    if not tool:
        return {}
    payload = _load_config()
    tools = payload.get("tools") if isinstance(payload.get("tools"), dict) else {}
    tool_spec = tools.get(tool) if isinstance(tools, dict) else {}
    defaults: Dict[str, Any] = {}
    if isinstance(tool_spec, dict) and isinstance(tool_spec.get("defaults"), dict):
        defaults.update(dict(tool_spec.get("defaults") or {}))
    global_defaults = payload.get("defaults") if isinstance(payload.get("defaults"), dict) else {}
    if tool == "query_emission_factors" and isinstance(global_defaults, dict) and "model_year" in global_defaults:
        defaults.setdefault("model_year", global_defaults.get("model_year"))

    # When a slot has both YAML default and runtime-only default,
    # runtime-only wins. Rationale: runtime defaults reflect actual router
    # execution behavior; YAML defaults are declarative-level hints that
    # may lag behind operational reality.
    defaults.update(dict(_RUNTIME_DEFAULTS.get(tool) or {}))
    return defaults


def _load_config() -> Dict[str, Any]:
    global _CACHE
    if _CACHE is None:
        with UNIFIED_MAPPINGS_PATH.open("r", encoding="utf-8") as handle:
            _CACHE = dict(yaml.safe_load(handle) or {})
    return _CACHE
