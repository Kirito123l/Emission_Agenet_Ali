"""Apply deterministic curation fixes to the existing end-to-end benchmark."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.pipeline_v2.common import DEFAULT_BENCHMARK_PATH, load_jsonl_records, save_jsonl


MACRO_DEFAULT_SIMPLE_IDS = {"e2e_incomplete_009", "e2e_incomplete_016"}
PARAMETER_AMBIGUOUS_IDS = {"e2e_incomplete_008", "e2e_incomplete_015", "e2e_constraint_013"}
MOTORCYCLE_HIGHWAY_REPRESENTATIVE_IDS = {"e2e_constraint_001", "e2e_constraint_003", "e2e_constraint_012"}
MOTORCYCLE_HIGHWAY_IDS = {
    "e2e_constraint_001",
    "e2e_constraint_002",
    "e2e_constraint_003",
    "e2e_constraint_004",
    "e2e_constraint_006",
    "e2e_constraint_009",
    "e2e_constraint_010",
    "e2e_constraint_012",
}


def _metadata(task: Dict[str, Any]) -> Dict[str, Any]:
    meta = task.get("benchmark_metadata")
    return dict(meta) if isinstance(meta, dict) else {}


def _merge_metadata(task: Dict[str, Any], updates: Dict[str, Any]) -> None:
    meta = _metadata(task)
    meta.update(updates)
    task["benchmark_metadata"] = meta


def _curate_macro_default(task: Dict[str, Any]) -> None:
    task["category"] = "simple"
    task["description"] = "File-backed macro emission can execute using default model_year, season, and fleet_mix"
    task["expected_tool"] = "calculate_macro_emission"
    task["expected_tool_chain"] = ["calculate_macro_emission"]
    task["expected_params"] = {"pollutants": ["CO2"]}
    task["success_criteria"] = {"tool_executed": True, "params_legal": True, "result_has_data": True}
    _merge_metadata(
        task,
        {
            "curation": "reclassified_from_incomplete",
            "curation_reason": "Direct MacroEmissionTool execution with macro_direct.csv and CO2 succeeds using defaults.",
            "defaults_verified": ["model_year=2020", "season=夏季", "fleet_mix=system_default"],
        },
    )


def _curate_parameter_ambiguous(task: Dict[str, Any]) -> None:
    original_id = task["id"]
    task["category"] = "parameter_ambiguous"
    if original_id == "e2e_constraint_013":
        task["description"] = "高架 is standardized as 快速路, so this is road-type ambiguity plus missing model_year, not a motorcycle-highway constraint"
        task["expected_params"] = {
            "vehicle_type": "Motorcycle",
            "road_type": "快速路",
            "pollutants": ["CO"],
        }
        _merge_metadata(
            task,
            {
                "curation": "reclassified_from_constraint_violation",
                "curation_reason": "高架 maps to 快速路 in current standardizer; it does not trigger vehicle_road_compatibility.",
                "missing_required_params": ["model_year"],
            },
        )
    else:
        task["description"] = "Unsupported colloquial vehicle wording should trigger parameter negotiation instead of being treated as a fully missing request"
        params = dict(task.get("expected_params") or {})
        params.pop("vehicle_type", None)
        params.setdefault("pollutants", ["NOx"])
        task["expected_params"] = params
        _merge_metadata(
            task,
            {
                "curation": "reclassified_from_incomplete",
                "curation_reason": "家用车 is not a supported alias; the benchmark should expect negotiation, not a standardized vehicle value.",
                "ambiguous_raw_params": {"vehicle_type": "家用车"},
                "missing_required_params": ["vehicle_type", "model_year"],
            },
        )
    task["expected_tool_chain"] = []
    task.pop("expected_tool", None)
    task["success_criteria"] = {"tool_executed": False, "requires_user_response": True, "result_has_data": False}


def _curate_constraint(task: Dict[str, Any]) -> None:
    task_id = task["id"]
    params = dict(task.get("expected_params") or {})
    meta = {
        "curation": "constraint_metadata_normalized",
        "expected_constraint_action": "reject",
        "violated_constraints": ["vehicle_road_compatibility"],
    }
    if task_id in MOTORCYCLE_HIGHWAY_IDS:
        params["vehicle_type"] = "Motorcycle"
        params["road_type"] = "高速公路"
        if "CO2" in task.get("user_message", ""):
            params.setdefault("pollutants", ["CO2"])
        elif "NOx" in task.get("user_message", ""):
            params.setdefault("pollutants", ["NOx"])
        elif "PM2.5" in task.get("user_message", ""):
            params.setdefault("pollutants", ["PM2.5"])
        if "2020" in task.get("user_message", ""):
            params["model_year"] = "2020"
        elif "2022" in task.get("user_message", ""):
            params["model_year"] = "2022"
        elif "2023" in task.get("user_message", ""):
            params["model_year"] = "2023"
        if task_id == "e2e_constraint_009":
            task["description"] = "Motorcycle trajectory explicitly says 高速, so the benchmark expects a hard vehicle-road constraint block"
            task["success_criteria"] = {"tool_executed": False, "constraint_blocked": True, "result_has_data": False}
        if task_id == "e2e_constraint_010":
            meta["violated_constraints"] = ["vehicle_road_compatibility", "vehicle_pollutant_relevance"]
            meta["secondary_coverage"] = ["vehicle_pollutant_relevance:Motorcycle:PM2.5"]
        if task_id not in MOTORCYCLE_HIGHWAY_REPRESENTATIVE_IDS:
            meta["redundant_pattern"] = "motorcycle_highway"
        else:
            meta["representative_pattern"] = "motorcycle_highway"

    if task_id in {"e2e_constraint_005", "e2e_constraint_007", "e2e_constraint_008", "e2e_constraint_011", "e2e_constraint_014"}:
        meta["expected_constraint_action"] = "warn"
        meta["violated_constraints"] = ["season_meteorology_consistency"]
        if "urban_summer_day" in task.get("user_message", ""):
            params["meteorology"] = "urban_summer_day"
        elif "urban_summer_night" in task.get("user_message", ""):
            params["meteorology"] = "urban_summer_night"
        elif "urban_winter_day" in task.get("user_message", ""):
            params["meteorology"] = "urban_winter_day"
        elif "urban_winter_night" in task.get("user_message", ""):
            params["meteorology"] = "urban_winter_night"

    if "CO2" in (params.get("pollutants") or []) and "calculate_dispersion" in (task.get("expected_tool_chain") or []):
        violations = list(meta.get("violated_constraints") or [])
        if "pollutant_task_applicability" not in violations:
            violations.append("pollutant_task_applicability")
        meta["violated_constraints"] = violations
        secondary = list(meta.get("secondary_coverage") or [])
        if "pollutant_task_applicability:CO2:calculate_dispersion" not in secondary:
            secondary.append("pollutant_task_applicability:CO2:calculate_dispersion")
        meta["secondary_coverage"] = secondary

    task["expected_params"] = params
    _merge_metadata(task, meta)


def curate(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    updated: List[Dict[str, Any]] = []
    for task in records:
        task = dict(task)
        task_id = str(task.get("id") or "")
        if task_id in MACRO_DEFAULT_SIMPLE_IDS:
            _curate_macro_default(task)
        elif task_id in PARAMETER_AMBIGUOUS_IDS:
            _curate_parameter_ambiguous(task)
        elif task.get("category") == "constraint_violation":
            _curate_constraint(task)
        updated.append(task)
    return updated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply deterministic benchmark curation fixes.")
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_BENCHMARK_PATH)
    parser.add_argument("--write", action="store_true", help="Write output. Without this, only prints a summary.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = load_jsonl_records(args.benchmark)
    curated = curate(records)
    changed_ids = [
        before.get("id")
        for before, after in zip(records, curated)
        if json.dumps(before, ensure_ascii=False, sort_keys=True) != json.dumps(after, ensure_ascii=False, sort_keys=True)
    ]
    summary = {"changed": len(changed_ids), "changed_ids": changed_ids, "output": str(args.output)}
    if args.write:
        save_jsonl(args.output, curated)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
