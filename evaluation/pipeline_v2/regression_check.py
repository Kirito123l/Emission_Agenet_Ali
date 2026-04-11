"""Run full-system regression over newly approved benchmark candidates."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.eval_end2end import run_end2end_evaluation
from evaluation.pipeline_v2.common import canonicalize_benchmark_task, load_jsonl_records, save_json, save_jsonl
from evaluation.pipeline_v2.merge_to_benchmark import _approved_candidates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run regression checks against approved candidates.")
    parser.add_argument("--input", type=Path, required=True, help="reviewed_candidates.jsonl or other candidate JSONL")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "evaluation" / "pipeline_v2" / "regression_results")
    parser.add_argument("--mode", choices=["router", "tool"], default="router")
    parser.add_argument("--macro-modes", default="direct,ai,fuzzy")
    return parser.parse_args()


def _analyze_logs(logs_path: Path) -> Dict[str, Any]:
    logs = load_jsonl_records(logs_path)
    abnormal: List[Dict[str, Any]] = []
    judgement_disputes: List[Dict[str, Any]] = []
    for log in logs:
        expected = log.get("expected", {})
        actual = log.get("actual", {})
        criteria = actual.get("criteria", {})
        success_criteria = expected.get("success_criteria", {})
        if not log.get("success"):
            abnormal.append({"task_id": log.get("task_id"), "failure_type": log.get("failure_type"), "error": log.get("error")})
        if (
            success_criteria.get("requires_user_response") is True
            and (criteria.get("tool_executed") or criteria.get("result_has_data"))
        ):
            judgement_disputes.append(
                {
                    "task_id": log.get("task_id"),
                    "reason": "Task expected clarification, but system executed or returned data.",
                    "criteria": criteria,
                }
            )
    return {
        "logs": len(logs),
        "abnormal_tasks": abnormal,
        "judgement_disputes": judgement_disputes,
    }


def main() -> None:
    args = parse_args()
    records = load_jsonl_records(args.input)
    approved = _approved_candidates(records, include_auto_valid=True)
    canonical = [canonicalize_benchmark_task(record) for record in approved]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    samples_path = args.output_dir / "regression_input.jsonl"
    save_jsonl(samples_path, canonical)

    if not canonical:
        report = {"tasks": 0, "status": "no_approved_candidates"}
        save_json(args.output_dir / "regression_report.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    metrics = run_end2end_evaluation(
        samples_path=samples_path,
        output_dir=args.output_dir,
        mode=args.mode,
        macro_column_mapping_modes=tuple(mode.strip() for mode in args.macro_modes.split(",") if mode.strip()),
    )
    analysis = _analyze_logs(Path(metrics["logs_path"]))
    report = {"metrics": metrics, "analysis": analysis}
    save_json(args.output_dir / "regression_report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
