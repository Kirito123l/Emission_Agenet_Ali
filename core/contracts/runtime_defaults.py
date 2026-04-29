from __future__ import annotations

import logging
from typing import Any, Dict

from core.contracts.emission_schema import get_default as _schema_get_default
from tools.contract_loader import get_tool_contract_registry

logger = logging.getLogger(__name__)

_RUNTIME_DEFAULTS: Dict[str, Dict[str, Any]] = {}
_loaded: bool = False


def _ensure_defaults_loaded() -> None:
    global _RUNTIME_DEFAULTS, _loaded
    if _loaded:
        return
    model_year = _schema_get_default("model_year")
    _RUNTIME_DEFAULTS.clear()
    if model_year is not None:
        _RUNTIME_DEFAULTS["query_emission_factors"] = {"model_year": model_year}
    else:
        logger.warning("emission_domain_schema: model_year default not found, "
                       "_RUNTIME_DEFAULTS will be empty")
    _loaded = True


def has_runtime_default(tool_name: str, slot_name: str) -> bool:
    _ensure_defaults_loaded()
    return str(slot_name or "") in get_runtime_defaults(tool_name)


def get_runtime_default(tool_name: str, slot_name: str) -> Any:
    _ensure_defaults_loaded()
    return get_runtime_defaults(tool_name).get(str(slot_name or ""))


def get_runtime_defaults(tool_name: str) -> Dict[str, Any]:
    _ensure_defaults_loaded()
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
