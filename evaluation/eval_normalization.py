"""Evaluate executor-layer parameter normalization."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.executor import StandardizationError, ToolExecutor
from evaluation.utils import (
    compare_expected_subset,
    classify_failure,
    classify_recoverability,
    load_jsonl,
    now_ts,
    runtime_overrides,
    safe_div,
    write_json,
    write_jsonl,
)
from services.standardizer import get_standardizer

SEASON_ALLOWED = {"春季", "夏季", "秋季", "冬季"}
ROAD_TYPE_ALLOWED = {"快速路", "地面道路"}


def _check_param_legality(arguments: Dict[str, Any]) -> Dict[str, bool]:
    standardizer = get_standardizer()
    legal = {}

    vehicle = arguments.get("vehicle_type")
    legal["vehicle_type"] = vehicle is None or standardizer.standardize_vehicle(str(vehicle)) is not None

    pollutants = arguments.get("pollutants", [])
    if isinstance(pollutants, list):
        legal["pollutants"] = all(standardizer.standardize_pollutant(str(item)) is not None for item in pollutants)
    else:
        legal["pollutants"] = False

    if "season" in arguments:
        legal["season"] = arguments.get("season") in SEASON_ALLOWED
    if "road_type" in arguments:
        legal["road_type"] = arguments.get("road_type") in ROAD_TYPE_ALLOWED
    if "model_year" in arguments:
        year = arguments.get("model_year")
        legal["model_year"] = isinstance(year, int) and 1995 <= year <= 2025

    return legal


def run_normalization_evaluation(
    samples_path: Path,
    output_dir: Path,
    enable_executor_standardization: bool = True,
) -> Dict[str, Any]:
    samples = load_jsonl(samples_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    logs: List[Dict[str, Any]] = []
    field_total = 0
    field_matched = 0
    sample_success = 0
    legal_success = 0

    with runtime_overrides(enable_executor_standardization=enable_executor_standardization):
        executor = ToolExecutor()

        for sample in samples:
            raw_args = dict(sample["raw_arguments"])
            expected = sample["expected_standardized"]
            expected_success = bool(sample.get("expected_success", True))
            error_message = None
            actual_args = None
            actual_success = True
            try:
                actual_args = executor._standardize_arguments(sample["tool_name"], raw_args)
            except StandardizationError as exc:
                actual_success = False
                error_message = str(exc)
                actual_args = {}

            comparison = compare_expected_subset(actual_args, expected)
            legality = _check_param_legality(actual_args)
            field_total += len(sample.get("focus_params", []))
            for param in sample.get("focus_params", []):
                detail = comparison["details"].get(param)
                if detail and detail.get("matched"):
                    field_matched += 1

            sample_matched = (actual_success == expected_success) and comparison["matched"]
            sample_success += int(sample_matched)
            legal_success += int(all(legality.values()) if legality else False)

            record = {
                "sample_id": sample["sample_id"],
                "tool_name": sample["tool_name"],
                "input": raw_args,
                "expected_success": expected_success,
                "actual_success": actual_success,
                "expected_standardized": expected,
                "actual_standardized": actual_args,
                "comparison": comparison,
                "legality": legality,
                "success": sample_matched,
                "error": error_message,
                "error_type": None if sample_matched else "standardization",
            }
            failure_type = classify_failure(record)
            record["failure_type"] = failure_type
            record["recoverability"] = classify_recoverability(failure_type)
            logs.append(record)

    metrics = {
        "task": "normalization",
        "samples": len(samples),
        "sample_accuracy": round(safe_div(sample_success, len(samples)), 4),
        "field_accuracy": round(safe_div(field_matched, field_total), 4),
        "parameter_legal_rate": round(safe_div(legal_success, len(samples)), 4),
        "executor_standardization_enabled": enable_executor_standardization,
        "logs_path": str(output_dir / "normalization_logs.jsonl"),
    }

    write_jsonl(output_dir / "normalization_logs.jsonl", logs)
    write_json(output_dir / "normalization_metrics.json", metrics)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate executor-layer normalization.")
    parser.add_argument(
        "--samples",
        type=Path,
        default=PROJECT_ROOT / "evaluation/normalization/samples.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / f"evaluation/logs/normalization_{now_ts()}",
    )
    parser.add_argument(
        "--disable-executor-standardization",
        action="store_true",
        help="Bypass executor-layer parameter normalization.",
    )
    args = parser.parse_args()

    metrics = run_normalization_evaluation(
        samples_path=args.samples,
        output_dir=args.output_dir,
        enable_executor_standardization=not args.disable_executor_standardization,
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
