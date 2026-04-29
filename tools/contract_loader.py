"""Load declarative tool contracts and generate runtime tool metadata."""

from __future__ import annotations

import logging
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

CONTRACTS_FILE = Path(__file__).resolve().parent.parent / "config" / "tool_contracts.yaml"


class ToolContractRegistry:
    """Registry that loads declarative tool contracts from YAML."""

    def __init__(self, contracts_path: Optional[Path] = None):
        self._path = contracts_path or CONTRACTS_FILE
        self._data = self._load()
        self._contracts: Dict[str, Dict[str, Any]] = dict(self._data.get("tools", {}))
        self._tool_definition_order: List[str] = list(
            self._data.get("tool_definition_order") or self._contracts.keys()
        )
        self._readiness_action_order: List[str] = list(
            self._data.get("readiness_action_order") or []
        )
        self._artifact_actions: List[Dict[str, Any]] = list(
            self._data.get("artifact_actions") or []
        )
        self._validate()

    def _load(self) -> Dict[str, Any]:
        with self._path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Invalid tool contract file: {self._path}")
        return data

    def _validate(self) -> None:
        missing_tools = [
            tool_name for tool_name in self._tool_definition_order if tool_name not in self._contracts
        ]
        if missing_tools:
            raise ValueError(
                f"tool_definition_order references undefined tools: {missing_tools}"
            )

        variant_ids = set()
        for tool_name, contract in self._contracts.items():
            if not isinstance(contract.get("parameters", {}), dict):
                raise ValueError(f"Tool {tool_name} parameters must be a mapping")
            for variant in contract.get("action_variants", []) or []:
                action_id = str(variant.get("action_id") or "").strip()
                if not action_id:
                    raise ValueError(f"Tool {tool_name} has action variant without action_id")
                variant_ids.add(action_id)

        artifact_ids = {
            str(action.get("action_id") or "").strip()
            for action in self._artifact_actions
            if str(action.get("action_id") or "").strip()
        }
        known_action_ids = variant_ids | artifact_ids

        missing_actions = [
            action_id for action_id in self._readiness_action_order if action_id not in known_action_ids
        ]
        if missing_actions:
            raise ValueError(
                f"readiness_action_order references undefined actions: {missing_actions}"
            )

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Generate OpenAI function-calling tool definitions."""
        definitions: List[Dict[str, Any]] = []
        for tool_name in self._tool_definition_order:
            contract = self._contracts[tool_name]
            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": contract.get("description", ""),
                        "parameters": self._build_json_schema(contract.get("parameters", {})),
                    },
                }
            )
        return definitions

    def get_tool_graph(self) -> Dict[str, Dict[str, List[str]]]:
        """Generate the canonical tool dependency graph."""
        graph: Dict[str, Dict[str, List[str]]] = {}
        for tool_name in self._tool_definition_order:
            dependencies = dict(self._contracts[tool_name].get("dependencies") or {})
            graph[tool_name] = {
                "requires": list(dependencies.get("requires") or []),
                "provides": list(dependencies.get("provides") or []),
            }
        return graph

    def get_action_catalog_entries(self) -> List[Dict[str, Any]]:
        """Generate readiness action catalog entries in stable order."""
        entries_by_id: Dict[str, Dict[str, Any]] = {}

        for tool_name, contract in self._contracts.items():
            defaults = self._build_action_defaults(tool_name, contract)
            for variant in contract.get("action_variants", []) or []:
                payload = deepcopy(defaults)
                payload.update(deepcopy(variant))
                payload["tool_name"] = payload.get("tool_name") or tool_name
                action_id = str(payload.get("action_id") or "").strip()
                if action_id:
                    entries_by_id[action_id] = payload

        for action in self._artifact_actions:
            payload = self._normalize_action_entry(action)
            action_id = str(payload.get("action_id") or "").strip()
            if action_id:
                entries_by_id[action_id] = payload

        if not self._readiness_action_order:
            return list(entries_by_id.values())
        return [
            deepcopy(entries_by_id[action_id])
            for action_id in self._readiness_action_order
            if action_id in entries_by_id
        ]

    def get_tool_names(self) -> List[str]:
        """Return all registered tool names in definition order."""
        return list(self._tool_definition_order)

    def get_type_coercion(self, tool_name: str) -> Dict[str, str]:
        """Return param→coercion_type mapping for a tool's parameters."""
        contract = self._contracts.get(str(tool_name or "").strip())
        if not isinstance(contract, dict):
            return {}
        params = contract.get("parameters") or {}
        if not isinstance(params, dict):
            return {}
        return {
            name: str(info.get("type_coercion") or "preserve")
            for name, info in params.items()
            if isinstance(info, dict)
        }

    def get_completion_keywords(self, tool_name: str) -> Dict[str, List[str]]:
        """Return 3-tier completion keywords (primary/secondary/requires) for a tool."""
        contract = self._contracts.get(str(tool_name or "").strip())
        if not isinstance(contract, dict):
            return {"primary": [], "secondary": [], "requires": []}
        ck = contract.get("completion_keywords")
        if not isinstance(ck, dict):
            return {"primary": [], "secondary": [], "requires": []}
        return {
            "primary": [str(k).lower() for k in (ck.get("primary") or [])],
            "secondary": [str(k).lower() for k in (ck.get("secondary") or [])],
            "requires": [str(k).lower() for k in (ck.get("requires") or [])],
        }

    def get_naive_available_tools(self) -> List[str]:
        """Return tool names where available_in_naive is not explicitly false."""
        result: List[str] = []
        for tool_name in self._tool_definition_order:
            contract = self._contracts.get(tool_name)
            if not isinstance(contract, dict):
                continue
            if contract.get("available_in_naive") is False:
                continue
            result.append(tool_name)
        return result

    def get_continuation_keywords(self) -> Dict[str, List[str]]:
        """Generate router continuation keywords."""
        keywords: Dict[str, List[str]] = {}
        for tool_name in self._tool_definition_order:
            terms = list(self._contracts[tool_name].get("continuation_keywords") or [])
            if terms:
                keywords[tool_name] = terms
        return keywords

    def get_param_standardization_map(self) -> Dict[str, Dict[str, str]]:
        """Generate tool-specific parameter standardization declarations."""
        result: Dict[str, Dict[str, str]] = {}
        for tool_name in self._tool_definition_order:
            params = self._contracts[tool_name].get("parameters") or {}
            param_map: Dict[str, str] = {}
            for param_name, param_info in params.items():
                standardization = param_info.get("standardization")
                if standardization:
                    param_map[param_name] = str(standardization)
            if param_map:
                result[tool_name] = param_map
        return result

    def get_required_slots(self, tool_name: str) -> List[str]:
        """Return conversation-layer required slots for a tool."""
        return self._get_string_list(tool_name, "required_slots")

    def get_optional_slots(self, tool_name: str) -> List[str]:
        """Return conversation-layer optional slots for a tool."""
        return self._get_string_list(tool_name, "optional_slots")

    def get_defaults(self, tool_name: str) -> Dict[str, Any]:
        """Return declarative defaults for a tool."""
        value = self._get_contract_value(tool_name, "defaults")
        return deepcopy(value) if isinstance(value, dict) else {}

    def get_clarification_followup_slots(self, tool_name: str) -> List[str]:
        """Return slots to ask again for clarification resumes."""
        return self._get_string_list(tool_name, "clarification_followup_slots")

    def get_confirm_first_slots(self, tool_name: str) -> List[str]:
        """Return slots that should trigger confirm-first behavior."""
        return self._get_string_list(tool_name, "confirm_first_slots")

    def _get_contract_value(self, tool_name: str, field_name: str) -> Any:
        tool = str(tool_name or "").strip()
        if not tool:
            return None
        contract = self._contracts.get(tool)
        if not isinstance(contract, dict):
            return None
        return contract.get(field_name)

    def _get_string_list(self, tool_name: str, field_name: str) -> List[str]:
        value = self._get_contract_value(tool_name, field_name)
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]

    def _build_json_schema(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        properties: Dict[str, Any] = {}
        required: List[str] = []
        for param_name, param_info in parameters.items():
            properties[param_name] = deepcopy(param_info.get("schema") or {})
            if bool(param_info.get("required")):
                required.append(param_name)
        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    def _build_action_defaults(
        self,
        tool_name: str,
        contract: Dict[str, Any],
    ) -> Dict[str, Any]:
        readiness = dict(contract.get("readiness") or {})
        return {
            "tool_name": tool_name,
            "arguments": {},
            "guidance_utterance": None,
            "required_task_types": list(readiness.get("required_task_types") or []),
            "required_result_tokens": list(readiness.get("required_result_tokens") or []),
            "requires_geometry_support": bool(
                readiness.get("requires_geometry_support", False)
            ),
            "requires_spatial_result_token": None,
            "provided_conflicts": [],
            "artifact_key": None,
            "alternative_action_ids": [],
            "guidance_enabled": True,
            "pre_execution_enabled": True,
            "category": "analysis",
        }

    def _normalize_action_entry(self, action: Dict[str, Any]) -> Dict[str, Any]:
        payload = deepcopy(action)
        payload.setdefault("tool_name", None)
        payload.setdefault("arguments", {})
        payload.setdefault("guidance_utterance", None)
        payload.setdefault("required_task_types", [])
        payload.setdefault("required_result_tokens", [])
        payload.setdefault("requires_geometry_support", False)
        payload.setdefault("requires_spatial_result_token", None)
        payload.setdefault("provided_conflicts", [])
        payload.setdefault("artifact_key", None)
        payload.setdefault("alternative_action_ids", [])
        payload.setdefault("guidance_enabled", True)
        payload.setdefault("pre_execution_enabled", True)
        payload.setdefault("category", "analysis")
        return payload


_registry: Optional[ToolContractRegistry] = None


def get_tool_contract_registry() -> ToolContractRegistry:
    """Return the process-global tool contract registry."""
    global _registry
    if _registry is None:
        _registry = ToolContractRegistry()
    return _registry
