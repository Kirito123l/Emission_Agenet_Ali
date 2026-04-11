"""Coverage audit for benchmark pipeline v2."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.pipeline_v2.common import (
    KEY_TOOL_CHAIN_COMBOS,
    build_mappings_catalog,
    detect_language_bucket,
    file_has_geometry,
    flatten_constraint_rules,
    flatten_expected_params,
    get_tool_chain,
    load_jsonl_records,
    load_yaml,
    match_constraint_rules,
    normalized_edit_distance,
    save_json,
    task_signature,
    tool_chain_label,
)

DEFAULT_BENCHMARK_PATH = PROJECT_ROOT / "evaluation" / "benchmarks" / "end2end_tasks.jsonl"
DEFAULT_MAPPINGS_PATH = PROJECT_ROOT / "config" / "unified_mappings.yaml"
DEFAULT_CONSTRAINTS_PATH = PROJECT_ROOT / "config" / "cross_constraints.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit current benchmark coverage and emit gap report JSON.")
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK_PATH)
    parser.add_argument("--mappings", type=Path, default=DEFAULT_MAPPINGS_PATH)
    parser.add_argument("--constraints", type=Path, default=DEFAULT_CONSTRAINTS_PATH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--print-summary", action="store_true")
    return parser.parse_args()


def _coverage_report(supported: Sequence[str], covered_counter: Counter) -> Dict[str, Any]:
    supported_list = [str(item) for item in supported]
    covered = sorted(item for item in supported_list if covered_counter.get(item, 0) > 0)
    missing = [item for item in supported_list if item not in covered]
    coverage_rate = round((len(covered) / len(supported_list)), 4) if supported_list else 1.0
    return {
        "total": len(supported_list),
        "covered": covered,
        "missing": missing,
        "coverage_rate": coverage_rate,
        "counts": {item: int(covered_counter[item]) for item in covered},
    }


def _compute_dimension_counters(tasks: Sequence[Dict[str, Any]]) -> Dict[str, Counter]:
    counters = {
        "vehicle_type": Counter(),
        "pollutant": Counter(),
        "season": Counter(),
        "road_type": Counter(),
        "meteorology": Counter(),
        "stability_class": Counter(),
    }
    for task in tasks:
        params = flatten_expected_params(task)
        if params.get("vehicle_type"):
            counters["vehicle_type"][str(params["vehicle_type"])] += 1
        for pollutant in params.get("pollutants", []) or []:
            counters["pollutant"][str(pollutant)] += 1
        if params.get("pollutant"):
            counters["pollutant"][str(params["pollutant"])] += 1
        for name in ("season", "road_type", "meteorology", "stability_class"):
            if params.get(name):
                counters[name][str(params[name])] += 1
    return counters


def _tool_chain_report(tasks: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    covered_counter = Counter()
    for task in tasks:
        covered_counter[tool_chain_label(get_tool_chain(task))] += 1

    covered = sorted(covered_counter.keys())
    missing = [
        tool_chain_label(chain)
        for chain in KEY_TOOL_CHAIN_COMBOS
        if tool_chain_label(chain) not in covered_counter
    ]
    return {
        "covered": covered,
        "missing": missing,
        "counts": {label: int(covered_counter[label]) for label in covered},
    }


def _language_report(tasks: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    counts = Counter(detect_language_bucket(str(task.get("user_message") or "")) for task in tasks)
    return {
        "chinese": int(counts["chinese"]),
        "english": int(counts["english"]),
        "mixed": int(counts["mixed"]),
        "english_target": 5,
    }


def _test_file_report(tasks: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    file_counter = Counter()
    geometry_files: List[str] = []
    for task in tasks:
        test_file = task.get("test_file")
        if not test_file:
            continue
        file_counter[str(test_file)] += 1
        if file_has_geometry(str(test_file)):
            geometry_files.append(str(test_file))
    return {
        "files": {path: int(count) for path, count in sorted(file_counter.items())},
        "geometry_files": sorted(set(geometry_files)),
        "has_geometry_file": bool(geometry_files),
    }


def _duplicate_report(tasks: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    message_counter = Counter(str(task.get("user_message") or "").strip() for task in tasks if str(task.get("user_message") or "").strip())
    signature_counter = Counter(task_signature(task) for task in tasks)

    near_duplicates: List[Dict[str, Any]] = []
    for index, left in enumerate(tasks):
        left_message = str(left.get("user_message") or "").strip()
        if not left_message:
            continue
        for right in tasks[index + 1 :]:
            right_message = str(right.get("user_message") or "").strip()
            if not right_message:
                continue
            distance = normalized_edit_distance(left_message, right_message)
            if distance < 0.25:
                near_duplicates.append(
                    {
                        "left_id": left.get("id"),
                        "right_id": right.get("id"),
                        "distance": round(distance, 4),
                    }
                )
    near_duplicates.sort(key=lambda item: item["distance"])

    return {
        "duplicate_messages": [
            {"message": message, "count": count}
            for message, count in sorted(message_counter.items(), key=lambda item: (-item[1], item[0]))
            if count > 1
        ],
        "duplicate_signatures": [
            {"signature": signature, "count": count}
            for signature, count in signature_counter.most_common()
            if count > 1
        ],
        "near_duplicate_pairs": near_duplicates[:20],
    }


def _cross_constraint_report(
    tasks: Sequence[Dict[str, Any]],
    constraints_payload: Dict[str, Any],
    catalog: Dict[str, Any],
) -> Dict[str, Any]:
    flattened_rules = flatten_constraint_rules(constraints_payload)
    covered_counter = Counter()
    rule_to_tasks: Dict[str, List[str]] = {}
    for task in tasks:
        if task.get("category") != "constraint_violation":
            continue
        matched = match_constraint_rules(task, flattened_rules, catalog)
        for rule_id in matched:
            covered_counter[rule_id] += 1
            rule_to_tasks.setdefault(rule_id, []).append(str(task.get("id") or ""))

    testable_rules = [rule["rule_id"] for rule in flattened_rules]
    covered_rules = [rule_id for rule_id in testable_rules if covered_counter.get(rule_id, 0) > 0]
    missing_rules = [rule_id for rule_id in testable_rules if rule_id not in covered_rules]
    return {
        "testable_rules": testable_rules,
        "covered_rules": covered_rules,
        "missing_rules": missing_rules,
        "rule_task_counts": {rule_id: int(covered_counter[rule_id]) for rule_id in covered_rules},
        "rule_task_examples": {rule_id: rule_to_tasks[rule_id][:5] for rule_id in covered_rules},
    }


def _invalid_expected_values(tasks: Sequence[Dict[str, Any]], catalog: Dict[str, Any]) -> Dict[str, List[str]]:
    invalid = {
        "vehicle_type": sorted(
            {
                str(flatten_expected_params(task).get("vehicle_type"))
                for task in tasks
                if flatten_expected_params(task).get("vehicle_type")
                and str(flatten_expected_params(task).get("vehicle_type")) not in set(catalog["vehicle_types"])
            }
        ),
        "pollutant": sorted(
            {
                str(pollutant)
                for task in tasks
                for pollutant in (flatten_expected_params(task).get("pollutants") or [])
                if str(pollutant) not in set(catalog["pollutants"])
            }
        ),
    }
    return invalid


def _preferred_alias(catalog: Dict[str, Any], alias_bucket: str, standard_value: str) -> str:
    aliases = (catalog.get(alias_bucket, {}) or {}).get(standard_value, [])
    for alias in aliases:
        if any("\u4e00" <= ch <= "\u9fff" for ch in str(alias)):
            return str(alias)
    return standard_value


def _generation_targets(
    coverage: Dict[str, Any],
    cross_constraints: Dict[str, Any],
    language: Dict[str, Any],
    invalid_values: Dict[str, List[str]],
    catalog: Dict[str, Any],
) -> List[Dict[str, Any]]:
    targets: List[Dict[str, Any]] = []
    for vehicle in coverage["vehicle_type"]["missing"]:
        vehicle_alias = _preferred_alias(catalog, "vehicle_aliases", vehicle)
        targets.append(
            {
                "priority": "P0",
                "dimension": "vehicle_type",
                "gap": vehicle,
                "suggested_category": "simple",
                "suggested_message_template": f"查询2020年{vehicle_alias}在快速路上的NOx排放因子",
            }
        )
    for pollutant in coverage["pollutant"]["missing"]:
        pollutant_alias = _preferred_alias(catalog, "pollutant_aliases", pollutant)
        targets.append(
            {
                "priority": "P0",
                "dimension": "pollutant",
                "gap": pollutant,
                "suggested_category": "simple",
                "suggested_message_template": f"查询2020年乘用车的{pollutant_alias}排放因子",
            }
        )
    for rule_id in cross_constraints["missing_rules"]:
        targets.append(
            {
                "priority": "P0",
                "dimension": "cross_constraints",
                "gap": rule_id,
                "suggested_category": "constraint_violation",
                "suggested_message_template": f"补一条触发 {rule_id} 的约束测试任务",
            }
        )
    for value in invalid_values.get("vehicle_type", []):
        targets.append(
            {
                "priority": "P0",
                "dimension": "benchmark_quality",
                "gap": f"unsupported_vehicle_alias:{value}",
                "suggested_category": "parameter_ambiguous",
                "suggested_message_template": f"用系统明确支持的别名替换不受支持说法“{value}”",
            }
        )
    for meteorology in coverage["meteorology"]["missing"]:
        targets.append(
            {
                "priority": "P1",
                "dimension": "meteorology",
                "gap": meteorology,
                "suggested_category": "multi_step",
                "suggested_message_template": f"先算路网NOx排放，再用 {meteorology} 做扩散分析",
            }
        )
    for combo in coverage["tool_chain_combos"]["missing"]:
        targets.append(
            {
                "priority": "P1",
                "dimension": "tool_chain_combo",
                "gap": combo,
                "suggested_category": "multi_step",
                "suggested_message_template": f"补一条覆盖工具链 {combo} 的任务",
            }
        )
    if language["english"] < language["english_target"]:
        targets.append(
            {
                "priority": "P1",
                "dimension": "language",
                "gap": f"pure_english<{language['english_target']}",
                "suggested_category": "simple",
                "suggested_message_template": "Query the 2020 passenger-car CO2 emission factor on urban expressways.",
            }
        )
    for season in coverage["season"]["covered"]:
        count = coverage["season"]["counts"].get(season, 0)
        if count <= 1:
            targets.append(
                {
                    "priority": "P2",
                    "dimension": "season_balance",
                    "gap": season,
                    "suggested_category": "simple",
                    "suggested_message_template": f"补一条 {season} 场景下的排放因子查询",
                }
            )
    for road_type in coverage["road_type"]["covered"]:
        count = coverage["road_type"]["counts"].get(road_type, 0)
        if count <= 1:
            targets.append(
                {
                    "priority": "P2",
                    "dimension": "road_type_balance",
                    "gap": road_type,
                    "suggested_category": "simple",
                    "suggested_message_template": f"补一条 {road_type} 场景下的排放任务",
                }
            )
    return targets


def build_gap_report(
    tasks: Sequence[Dict[str, Any]],
    mappings_payload: Dict[str, Any],
    constraints_payload: Dict[str, Any],
) -> Dict[str, Any]:
    catalog = build_mappings_catalog(mappings_payload)
    counters = _compute_dimension_counters(tasks)
    coverage = {
        "vehicle_type": _coverage_report(catalog["vehicle_types"], counters["vehicle_type"]),
        "pollutant": _coverage_report(catalog["pollutants"], counters["pollutant"]),
        "season": _coverage_report(catalog["seasons"], counters["season"]),
        "road_type": _coverage_report(catalog["road_types"], counters["road_type"]),
        "meteorology": _coverage_report(catalog["meteorology_presets"], counters["meteorology"]),
        "stability_class": _coverage_report(catalog["stability_classes"], counters["stability_class"]),
    }
    coverage["tool_chain_combos"] = _tool_chain_report(tasks)
    cross_constraints = _cross_constraint_report(tasks, constraints_payload, catalog)
    language = _language_report(tasks)
    invalid_values = _invalid_expected_values(tasks, catalog)

    report = {
        "benchmark_path": str(DEFAULT_BENCHMARK_PATH),
        "task_count": len(tasks),
        "vehicle_type": coverage["vehicle_type"],
        "pollutant": coverage["pollutant"],
        "season": coverage["season"],
        "road_type": coverage["road_type"],
        "meteorology": coverage["meteorology"],
        "stability_class": coverage["stability_class"],
        "tool_chain_combos": coverage["tool_chain_combos"],
        "cross_constraints": cross_constraints,
        "language": language,
        "test_files": _test_file_report(tasks),
        "duplicates": _duplicate_report(tasks),
        "invalid_expected_values": invalid_values,
    }
    report["generation_targets"] = _generation_targets(coverage, cross_constraints, language, invalid_values, catalog)
    return report


def _print_summary(report: Dict[str, Any]) -> None:
    summary = {
        "tasks": report["task_count"],
        "vehicle_type_coverage": f"{len(report['vehicle_type']['covered'])}/{report['vehicle_type']['total']}",
        "pollutant_coverage": f"{len(report['pollutant']['covered'])}/{report['pollutant']['total']}",
        "meteorology_coverage": f"{len(report['meteorology']['covered'])}/{report['meteorology']['total']}",
        "english_tasks": report["language"]["english"],
        "geometry_files": report["test_files"]["geometry_files"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    args = parse_args()
    benchmark_tasks = load_jsonl_records(args.benchmark)
    mappings_payload = load_yaml(args.mappings)
    constraints_payload = load_yaml(args.constraints)
    report = build_gap_report(benchmark_tasks, mappings_payload, constraints_payload)
    report["benchmark_path"] = str(args.benchmark)
    report["mappings_path"] = str(args.mappings)
    report["constraints_path"] = str(args.constraints)
    save_json(args.output, report)
    if args.print_summary:
        _print_summary(report)


if __name__ == "__main__":
    main()
