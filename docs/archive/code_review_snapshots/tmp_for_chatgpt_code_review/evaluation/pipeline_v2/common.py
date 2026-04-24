"""Shared helpers for benchmark pipeline v2."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
import yaml

from evaluation.utils import write_json, write_jsonl


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BENCHMARK_PATH = PROJECT_ROOT / "evaluation" / "benchmarks" / "end2end_tasks.jsonl"
DEFAULT_MAPPINGS_PATH = PROJECT_ROOT / "config" / "unified_mappings.yaml"
DEFAULT_CONSTRAINTS_PATH = PROJECT_ROOT / "config" / "cross_constraints.yaml"

VALID_CATEGORIES = (
    "simple",
    "parameter_ambiguous",
    "multi_step",
    "incomplete",
    "constraint_violation",
    "multi_turn_clarification",
    "user_revision",
    "ambiguous_colloquial",
    "code_switch_typo",
)
CATEGORY_ID_PREFIX = {
    "simple": "simple",
    "parameter_ambiguous": "ambiguous",
    "multi_step": "multistep",
    "incomplete": "incomplete",
    "constraint_violation": "constraint",
    "multi_turn_clarification": "clarification",
    "user_revision": "revision",
    "ambiguous_colloquial": "colloquial",
    "code_switch_typo": "codeswitch",
}

KEY_TOOL_CHAIN_COMBOS: Tuple[Tuple[str, ...], ...] = (
    ("query_emission_factors",),
    ("query_knowledge",),
    ("calculate_micro_emission",),
    ("calculate_macro_emission",),
    ("calculate_macro_emission", "calculate_dispersion"),
    ("calculate_macro_emission", "calculate_dispersion", "analyze_hotspots"),
    ("calculate_macro_emission", "render_spatial_map"),
    ("calculate_macro_emission", "calculate_dispersion", "render_spatial_map"),
    ("calculate_macro_emission", "calculate_dispersion", "analyze_hotspots", "render_spatial_map"),
    ("calculate_micro_emission", "calculate_dispersion"),
    ("calculate_micro_emission", "calculate_dispersion", "analyze_hotspots"),
    ("calculate_micro_emission", "render_spatial_map"),
    ("calculate_micro_emission", "calculate_dispersion", "render_spatial_map"),
)
GEOMETRY_REQUIRED_TOOLS = {"calculate_dispersion", "analyze_hotspots", "render_spatial_map"}
GEOMETRY_HEADER_TOKENS = ("geometry", "geom", "wkt", "geojson", "lon", "lat", "x_coord", "y_coord")

DEFAULT_TEST_FILE_BY_TOOL = {
    "query_emission_factors": None,
    "query_knowledge": None,
    "calculate_micro_emission": "evaluation/file_tasks/data/micro_time_speed.csv",
    "calculate_macro_emission": "evaluation/file_tasks/data/macro_direct.csv",
    "calculate_dispersion": "test_data/test_6links.xlsx",
    "analyze_hotspots": "test_data/test_6links.xlsx",
    "render_spatial_map": "test_data/test_6links.xlsx",
}


def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return payload if isinstance(payload, dict) else {}


def load_jsonl_records(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _dedupe(values: Iterable[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def build_mappings_catalog(mappings: Dict[str, Any]) -> Dict[str, Any]:
    vehicle_types: List[str] = []
    vehicle_aliases: Dict[str, List[str]] = {}
    for item in mappings.get("vehicle_types", []) or []:
        if not isinstance(item, dict):
            continue
        standard_name = str(item.get("standard_name") or "").strip()
        if not standard_name:
            continue
        vehicle_types.append(standard_name)
        aliases = [str(item.get("display_name_zh") or "").strip()]
        aliases.extend(str(alias).strip() for alias in item.get("aliases", []) or [])
        vehicle_aliases[standard_name] = _dedupe([standard_name, *aliases])

    pollutants: List[str] = []
    pollutant_aliases: Dict[str, List[str]] = {}
    for item in mappings.get("pollutants", []) or []:
        if not isinstance(item, dict):
            continue
        standard_name = str(item.get("standard_name") or "").strip()
        if not standard_name:
            continue
        pollutants.append(standard_name)
        aliases = [str(item.get("display_name_zh") or "").strip()]
        aliases.extend(str(alias).strip() for alias in item.get("aliases", []) or [])
        pollutant_aliases[standard_name] = _dedupe([standard_name, *aliases])

    seasons: List[str] = []
    season_aliases: Dict[str, List[str]] = {}
    seasons_payload = mappings.get("seasons", {}) or {}
    if isinstance(seasons_payload, list):
        for item in seasons_payload:
            if not isinstance(item, dict):
                continue
            standard_name = str(item.get("standard_name") or "").strip()
            if not standard_name:
                continue
            seasons.append(standard_name)
            season_aliases[standard_name] = _dedupe([standard_name, *(str(alias).strip() for alias in item.get("aliases", []) or [])])
    elif isinstance(seasons_payload, dict):
        for standard_name, aliases in seasons_payload.items():
            cleaned = str(standard_name).strip()
            if not cleaned:
                continue
            seasons.append(cleaned)
            season_aliases[cleaned] = _dedupe([cleaned, *(str(alias).strip() for alias in aliases if alias)])

    road_types = [str(name).strip() for name in (mappings.get("road_types", {}) or {}).keys() if str(name).strip()]
    road_aliases: Dict[str, List[str]] = {}
    for standard_name, info in (mappings.get("road_types", {}) or {}).items():
        cleaned = str(standard_name).strip()
        aliases: List[str] = [cleaned]
        if isinstance(info, dict):
            aliases.extend(str(alias).strip() for alias in info.get("aliases", []) or [])
        elif isinstance(info, list):
            aliases.extend(str(alias).strip() for alias in info)
        road_aliases[cleaned] = _dedupe(aliases)

    meteorology_presets = [
        str(name).strip()
        for name in (((mappings.get("meteorology", {}) or {}).get("presets", {}) or {}).keys())
        if str(name).strip()
    ]
    meteorology_aliases: Dict[str, List[str]] = {}
    for standard_name, info in (((mappings.get("meteorology", {}) or {}).get("presets", {}) or {}).items()):
        cleaned = str(standard_name).strip()
        aliases = [cleaned]
        if isinstance(info, dict):
            aliases.extend(str(alias).strip() for alias in info.get("aliases", []) or [])
        meteorology_aliases[cleaned] = _dedupe(aliases)

    stability_classes = [str(name).strip() for name in (mappings.get("stability_classes", {}) or {}).keys() if str(name).strip()]
    stability_aliases: Dict[str, List[str]] = {}
    for standard_name, info in (mappings.get("stability_classes", {}) or {}).items():
        cleaned = str(standard_name).strip()
        aliases = [cleaned]
        if isinstance(info, dict):
            aliases.extend(str(alias).strip() for alias in info.get("aliases", []) or [])
        stability_aliases[cleaned] = _dedupe(aliases)

    return {
        "vehicle_types": vehicle_types,
        "vehicle_aliases": vehicle_aliases,
        "pollutants": pollutants,
        "pollutant_aliases": pollutant_aliases,
        "seasons": seasons,
        "season_aliases": season_aliases,
        "road_types": road_types,
        "road_aliases": road_aliases,
        "meteorology_presets": meteorology_presets,
        "meteorology_aliases": meteorology_aliases,
        "stability_classes": stability_classes,
        "stability_aliases": stability_aliases,
        "defaults": dict(mappings.get("defaults", {}) or {}),
    }


def flatten_expected_params(task: Dict[str, Any]) -> Dict[str, Any]:
    params = dict(task.get("expected_params", {}) or {})
    known_params = params.get("known_params", {})
    flattened: Dict[str, Any] = {}
    if isinstance(known_params, dict):
        flattened.update(known_params)
    for key, value in params.items():
        if key == "known_params":
            continue
        flattened[key] = value
    return flattened


def extract_param_values(task: Dict[str, Any], name: str) -> List[Any]:
    params = flatten_expected_params(task)
    if name == "pollutant":
        values: List[Any] = []
        if params.get("pollutant") is not None:
            values.append(params.get("pollutant"))
        if isinstance(params.get("pollutants"), list):
            values.extend(params.get("pollutants") or [])
        return [value for value in values if value is not None]
    value = params.get(name)
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if item is not None]
    return [value]


def get_tool_chain(task: Dict[str, Any]) -> List[str]:
    raw_chain = task.get("expected_tool_chain", []) or []
    if not isinstance(raw_chain, list):
        raw_chain = [raw_chain]
    return [str(item).strip() for item in raw_chain if str(item).strip()]


def tool_chain_label(chain: Sequence[str]) -> str:
    return " -> ".join(chain) if chain else "(empty)"


def detect_language_bucket(message: str) -> str:
    has_cn = bool(re.search(r"[\u4e00-\u9fff]", message))
    has_en = bool(re.search(r"[a-zA-Z]{3,}", message))
    if has_cn and has_en:
        return "mixed"
    if has_cn:
        return "chinese"
    return "english"


def message_contains_alias(message: str, aliases: Sequence[str]) -> bool:
    lowered = str(message or "").strip().lower()
    return any(str(alias).strip().lower() in lowered for alias in aliases if str(alias).strip())


def _header_has_geometry_tokens(columns: Sequence[Any]) -> bool:
    lowered = {str(column).strip().lower() for column in columns}
    return any(token in lowered for token in GEOMETRY_HEADER_TOKENS)


def file_has_geometry(path_str: Optional[str]) -> bool:
    if not path_str:
        return False
    path = Path(path_str)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        return False
    suffix = path.suffix.lower()
    if suffix in {".shp", ".geojson"}:
        return True
    if suffix == ".zip":
        return True
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig") as handle:
            header = handle.readline().strip().split(",")
        return _header_has_geometry_tokens(header)
    if suffix in {".xlsx", ".xls"}:
        try:
            columns = list(pd.read_excel(path, nrows=0).columns)
        except Exception:
            return False
        return _header_has_geometry_tokens(columns)
    return False


def build_success_criteria(task: Dict[str, Any]) -> Dict[str, Any]:
    explicit = task.get("success_criteria")
    if isinstance(explicit, dict) and explicit:
        return explicit

    category = str(task.get("category") or "").strip()
    chain = get_tool_chain(task)
    has_file = bool(task.get("has_file"))
    if category == "incomplete":
        return {"tool_executed": False, "requires_user_response": True, "result_has_data": False}
    if category == "constraint_violation":
        if chain:
            criteria = {
                "tool_executed": True,
                "params_legal": True,
                "constraint_warning": True,
                "result_has_data": True,
            }
            if has_file and any(tool in GEOMETRY_REQUIRED_TOOLS for tool in chain):
                criteria["geometry_gated_halt_acceptable"] = True
            return criteria
        return {"tool_executed": False, "constraint_blocked": True, "result_has_data": False}

    criteria = {"tool_executed": True, "params_legal": True, "result_has_data": True}
    if category == "multi_step" and has_file and any(tool in GEOMETRY_REQUIRED_TOOLS for tool in chain):
        criteria["geometry_gated_halt_acceptable"] = True
    return criteria


def canonicalize_benchmark_task(task: Dict[str, Any]) -> Dict[str, Any]:
    normalized = {
        "id": str(task.get("id") or "").strip(),
        "category": str(task.get("category") or "").strip(),
        "description": str(task.get("description") or "").strip(),
        "user_message": str(task.get("user_message") or "").strip(),
        "has_file": bool(task.get("has_file")),
        "test_file": task.get("test_file"),
        "expected_tool_chain": get_tool_chain(task),
        "expected_params": dict(task.get("expected_params", {}) or {}),
        "success_criteria": build_success_criteria(task),
    }
    expected_tool = task.get("expected_tool")
    if expected_tool is not None:
        normalized["expected_tool"] = str(expected_tool).strip()
    follow_up_messages = task.get("follow_up_messages")
    if isinstance(follow_up_messages, list):
        normalized["follow_up_messages"] = [
            str(message).strip()
            for message in follow_up_messages
            if str(message or "").strip()
        ]
    for extra_key in ("notes", "benchmark_metadata", "provenance"):
        if extra_key in task:
            normalized[extra_key] = task.get(extra_key)
    return normalized


def compute_next_task_id(existing_records: Sequence[Dict[str, Any]], category: str) -> str:
    suffix = 0
    for record in existing_records:
        raw_id = str(record.get("id") or "")
        tail = raw_id.rsplit("_", 1)[-1]
        if tail.isdigit():
            suffix = max(suffix, int(tail))
    prefix = CATEGORY_ID_PREFIX[category]
    return f"e2e_{prefix}_{suffix + 1:03d}"


def task_signature(task: Dict[str, Any]) -> str:
    params = flatten_expected_params(task)
    signature = {
        "category": str(task.get("category") or ""),
        "chain": get_tool_chain(task),
        "params": params,
        "test_file": task.get("test_file"),
    }
    return json.dumps(signature, ensure_ascii=False, sort_keys=True)


def normalized_edit_distance(left: str, right: str) -> float:
    left = str(left or "").strip()
    right = str(right or "").strip()
    if left == right:
        return 0.0
    if not left or not right:
        return 1.0

    prev = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = prev[j] + 1
            replace_cost = prev[j - 1] + (0 if left_char == right_char else 1)
            current.append(min(insert_cost, delete_cost, replace_cost))
        prev = current
    return prev[-1] / max(len(left), len(right))


def flatten_constraint_rules(constraints_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    flattened: List[Dict[str, Any]] = []
    for constraint in constraints_payload.get("constraints", []) or []:
        if not isinstance(constraint, dict):
            continue
        constraint_name = str(constraint.get("name") or "").strip()
        param_a = str(constraint.get("param_a") or "").strip()
        param_b = str(constraint.get("param_b") or "").strip()
        constraint_type = str(constraint.get("type") or "").strip()
        if not (constraint_name and param_a and param_b and constraint_type):
            continue
        field_name = {
            "blocked_combinations": "blocked",
            "consistency_warning": "inconsistent",
            "conditional_warning": "warned",
        }.get(constraint_type)
        if field_name is None:
            continue
        for value_a, rule in (constraint.get("rules", {}) or {}).items():
            if not isinstance(rule, dict):
                continue
            for value_b in rule.get(field_name, []) or []:
                flattened.append(
                    {
                        "rule_id": f"{constraint_name}:{value_a}:{value_b}",
                        "constraint_name": constraint_name,
                        "constraint_type": constraint_type,
                        "param_a": param_a,
                        "param_b": param_b,
                        "value_a": str(value_a),
                        "value_b": str(value_b),
                        "reason": str(rule.get("reason") or constraint.get("description") or ""),
                    }
                )
    return flattened


def match_constraint_rules(
    task: Dict[str, Any],
    flattened_rules: Sequence[Dict[str, Any]],
    catalog: Dict[str, Any],
) -> List[str]:
    params = flatten_expected_params(task)
    message = str(task.get("user_message") or "")

    alias_lookup = {
        "vehicle_type": catalog.get("vehicle_aliases", {}),
        "pollutants": catalog.get("pollutant_aliases", {}),
        "pollutant": catalog.get("pollutant_aliases", {}),
        "season": catalog.get("season_aliases", {}),
        "road_type": catalog.get("road_aliases", {}),
        "meteorology": catalog.get("meteorology_aliases", {}),
    }

    matched: List[str] = []
    for rule in flattened_rules:
        param_a = rule["param_a"]
        param_b = rule["param_b"]
        value_a = rule["value_a"]
        value_b = rule["value_b"]

        chain_values = set(get_tool_chain(task))
        expected_tool = task.get("expected_tool")
        if expected_tool:
            chain_values.add(str(expected_tool))

        raw_a = list(chain_values) if param_a == "tool_name" else params.get(param_a)
        raw_b = list(chain_values) if param_b == "tool_name" else params.get(param_b)
        if param_b == "pollutants" and raw_b is None:
            raw_b = params.get("pollutant")

        param_a_match = False
        if raw_a is not None:
            if isinstance(raw_a, list):
                param_a_match = value_a in {str(item) for item in raw_a}
            else:
                param_a_match = str(raw_a) == value_a
        if not param_a_match:
            param_a_match = message_contains_alias(message, alias_lookup.get(param_a, {}).get(value_a, [value_a]))

        param_b_match = False
        if raw_b is not None:
            if isinstance(raw_b, list):
                param_b_match = value_b in {str(item) for item in raw_b}
            else:
                param_b_match = str(raw_b) == value_b
        if not param_b_match:
            param_b_match = message_contains_alias(message, alias_lookup.get(param_b, {}).get(value_b, [value_b]))

        if param_a_match and param_b_match:
            matched.append(rule["rule_id"])
    return matched


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    write_json(path, payload)


def save_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    write_jsonl(path, rows)
