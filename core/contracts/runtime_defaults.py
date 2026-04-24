from __future__ import annotations

from typing import Any, Dict

from tools.contract_loader import get_tool_contract_registry

_RUNTIME_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "query_emission_factors": {
        "model_year": 2020,
    },
}


def has_runtime_default(tool_name: str, slot_name: str) -> bool:
    return str(slot_name or "") in get_runtime_defaults(tool_name)


def get_runtime_default(tool_name: str, slot_name: str) -> Any:
    return get_runtime_defaults(tool_name).get(str(slot_name or ""))


def get_runtime_defaults(tool_name: str) -> Dict[str, Any]:
    tool = str(tool_name or "").strip()
    if not tool:
        return {}
    defaults = dict(get_tool_contract_registry().get_defaults(tool))

    # When a slot has both YAML default and runtime-only default,
    # runtime-only wins. Rationale: runtime defaults reflect actual router
    # execution behavior; YAML defaults are declarative-level hints that
    # may lag behind operational reality.
    defaults.update(dict(_RUNTIME_DEFAULTS.get(tool) or {}))
    return defaults
