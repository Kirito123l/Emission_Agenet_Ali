"""Extract prompt-generation context from repository configuration files."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
BENCHMARK_DIR = PROJECT_ROOT / "evaluation" / "benchmarks"

STANDARDIZATION_DIMENSIONS = (
    "vehicle_type",
    "pollutant",
    "season",
    "road_type",
    "meteorology",
    "stability_class",
)


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    seen = set()
    deduped: List[str] = []
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def load_unified_mappings() -> Dict[str, Any]:
    return _load_yaml(CONFIG_DIR / "unified_mappings.yaml")


@lru_cache(maxsize=1)
def load_tool_contracts() -> Dict[str, Any]:
    return _load_yaml(CONFIG_DIR / "tool_contracts.yaml")


def extract_standardization_context(dimension: str) -> Dict[str, Any]:
    """Extract standard values and known aliases for one standardization dimension."""
    mappings = load_unified_mappings()
    context: Dict[str, Any] = {
        "dimension": dimension,
        "standard_names": [],
        "aliases_by_standard": {},
    }

    if dimension == "vehicle_type":
        for item in mappings.get("vehicle_types", []):
            if not isinstance(item, dict) or "standard_name" not in item:
                continue
            standard_name = str(item["standard_name"])
            aliases = [item.get("display_name_zh", "")]
            aliases.extend(item.get("aliases", []) or [])
            context["standard_names"].append(standard_name)
            context["aliases_by_standard"][standard_name] = _dedupe_preserve_order([str(alias) for alias in aliases])
        return context

    if dimension == "pollutant":
        for item in mappings.get("pollutants", []):
            if not isinstance(item, dict) or "standard_name" not in item:
                continue
            standard_name = str(item["standard_name"])
            aliases = [item.get("display_name_zh", "")]
            aliases.extend(item.get("aliases", []) or [])
            context["standard_names"].append(standard_name)
            context["aliases_by_standard"][standard_name] = _dedupe_preserve_order([str(alias) for alias in aliases])
        return context

    if dimension == "season":
        seasons = mappings.get("seasons", [])
        if isinstance(seasons, list):
            for item in seasons:
                if not isinstance(item, dict) or "standard_name" not in item:
                    continue
                standard_name = str(item["standard_name"])
                aliases = [standard_name]
                aliases.extend(item.get("aliases", []) or [])
                context["standard_names"].append(standard_name)
                context["aliases_by_standard"][standard_name] = _dedupe_preserve_order([str(alias) for alias in aliases])
        elif isinstance(seasons, dict):
            for standard_name, aliases in seasons.items():
                std_name = str(standard_name)
                alias_values = [std_name]
                if isinstance(aliases, list):
                    alias_values.extend(str(alias) for alias in aliases)
                context["standard_names"].append(std_name)
                context["aliases_by_standard"][std_name] = _dedupe_preserve_order(alias_values)
        return context

    if dimension == "road_type":
        for standard_name, info in (mappings.get("road_types", {}) or {}).items():
            aliases = [str(standard_name)]
            if isinstance(info, dict):
                aliases.extend(str(alias) for alias in info.get("aliases", []) or [])
            elif isinstance(info, list):
                aliases.extend(str(alias) for alias in info)
            std_name = str(standard_name)
            context["standard_names"].append(std_name)
            context["aliases_by_standard"][std_name] = _dedupe_preserve_order(aliases)
        return context

    if dimension == "meteorology":
        presets = ((mappings.get("meteorology", {}) or {}).get("presets", {}) or {})
        for standard_name, info in presets.items():
            aliases = [str(standard_name)]
            if isinstance(info, dict):
                aliases.extend(str(alias) for alias in info.get("aliases", []) or [])
            std_name = str(standard_name)
            context["standard_names"].append(std_name)
            context["aliases_by_standard"][std_name] = _dedupe_preserve_order(aliases)
        return context

    if dimension == "stability_class":
        for standard_name, info in (mappings.get("stability_classes", {}) or {}).items():
            aliases = [str(standard_name)]
            if isinstance(info, dict):
                aliases.extend(str(alias) for alias in info.get("aliases", []) or [])
            std_name = str(standard_name)
            context["standard_names"].append(std_name)
            context["aliases_by_standard"][std_name] = _dedupe_preserve_order(aliases)
        return context

    raise ValueError(f"Unsupported standardization dimension: {dimension}")


def extract_all_standardization_contexts() -> Dict[str, Dict[str, Any]]:
    return {dimension: extract_standardization_context(dimension) for dimension in STANDARDIZATION_DIMENSIONS}


def extract_tool_contracts() -> Dict[str, Any]:
    return dict((load_tool_contracts().get("tools", {}) or {}))


def extract_system_capabilities() -> str:
    """Build a compact natural-language system-capability description."""
    tools = extract_tool_contracts()
    contexts = extract_all_standardization_contexts()
    lines: List[str] = ["可用工具:"]

    for tool_name, contract in tools.items():
        if not isinstance(contract, dict):
            continue
        description = str(contract.get("description", "")).strip()
        lines.append(f"- {tool_name}: {description}")
        params = contract.get("parameters", {}) or {}
        for param_name, param_info in params.items():
            if not isinstance(param_info, dict):
                continue
            required = "必填" if param_info.get("required") else "可选"
            std_dimension = param_info.get("standardization") or "无"
            lines.append(f"  参数 {param_name}: {required}, 标准化={std_dimension}")

        dependencies = contract.get("dependencies", {}) or {}
        requires = dependencies.get("requires", []) or []
        provides = dependencies.get("provides", []) or []
        if requires:
            lines.append(f"  依赖产物: {', '.join(str(item) for item in requires)}")
        if provides:
            lines.append(f"  输出产物: {', '.join(str(item) for item in provides)}")

    lines.append("")
    lines.append("标准化维度与标准值:")
    for dimension, context in contexts.items():
        values = context["standard_names"]
        preview = ", ".join(values[:10])
        if len(values) > 10:
            preview += f" ... 共{len(values)}个"
        lines.append(f"- {dimension}: {preview}")

    return "\n".join(lines)


def load_jsonl_records(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if not path.exists():
        return records

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def load_existing_cases(
    benchmark_path: Optional[Path] = None,
    dimension: Optional[str] = None,
) -> List[Dict[str, Any]]:
    path = benchmark_path or (BENCHMARK_DIR / "standardization_benchmark.jsonl")
    records = load_jsonl_records(path)
    if dimension is None:
        return records
    return [record for record in records if record.get("dimension") == dimension]


def load_existing_raw_inputs(
    benchmark_path: Optional[Path] = None,
    dimension: Optional[str] = None,
) -> List[str]:
    return [
        str(record.get("raw_input", "")).strip()
        for record in load_existing_cases(benchmark_path=benchmark_path, dimension=dimension)
        if str(record.get("raw_input", "")).strip()
    ]


def load_existing_end2end_tasks(benchmark_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    path = benchmark_path or (BENCHMARK_DIR / "end2end_tasks.jsonl")
    return load_jsonl_records(path)


def load_existing_user_messages(benchmark_path: Optional[Path] = None, category: Optional[str] = None) -> List[str]:
    records = load_existing_end2end_tasks(benchmark_path=benchmark_path)
    messages: List[str] = []
    for record in records:
        if category is not None and record.get("category") != category:
            continue
        message = str(record.get("user_message", "")).strip()
        if message:
            messages.append(message)
    return messages
