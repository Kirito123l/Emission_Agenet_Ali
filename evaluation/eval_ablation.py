"""Run end-to-end ablations over the structured benchmark task set."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.utils import now_ts

END2END_SCRIPT = PROJECT_ROOT / "evaluation" / "eval_end2end.py"
DEFAULT_SAMPLES = PROJECT_ROOT / "evaluation" / "benchmarks" / "end2end_tasks.jsonl"
DEFAULT_OUTPUT_BASE = PROJECT_ROOT / "evaluation" / "results" / "end2end_ablation"
ABLATION_RUNS = 3

ABLATION_CONFIGS: Dict[str, Dict[str, str]] = {
    "baseline": {},
    "no_standardization": {
        "ENABLE_EXECUTOR_STANDARDIZATION": "false",
    },
    "no_cross_constraint": {
        "ENABLE_CROSS_CONSTRAINT_VALIDATION": "false",
    },
    "no_negotiation": {
        "ENABLE_PARAMETER_NEGOTIATION": "false",
    },
    "no_readiness": {
        "ENABLE_READINESS_GATING": "false",
    },
}


def _metric_summary(values: List[float]) -> Dict[str, Any]:
    rounded = [round(float(value), 4) for value in values]
    return {
        "values": rounded,
        "mean": round(statistics.mean(rounded), 4) if rounded else 0.0,
        "median": round(statistics.median(rounded), 4) if rounded else 0.0,
        "stdev": round(statistics.stdev(rounded), 4) if len(rounded) > 1 else 0.0,
        "min": round(min(rounded), 4) if rounded else 0.0,
        "max": round(max(rounded), 4) if rounded else 0.0,
    }


def _aggregate_ablation_runs(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not runs:
        return {}
    if len(runs) == 1:
        return runs[0]

    aggregated: Dict[str, Any] = {
        "task": runs[0].get("task", "end2end"),
        "mode": runs[0].get("mode", "router"),
        "tasks": runs[0].get("tasks", 0),
        "skipped_tasks": runs[0].get("skipped_tasks", 0),
    }

    for metric in ("completion_rate", "tool_accuracy", "parameter_legal_rate", "result_data_rate"):
        aggregated[metric] = _metric_summary([float(run.get(metric, 0.0) or 0.0) for run in runs])

    categories = sorted(
        {
            str(category)
            for run in runs
            for category in (run.get("by_category") or {}).keys()
        }
    )
    by_category: Dict[str, Any] = {}
    for category in categories:
        success_rates = [
            float((run.get("by_category") or {}).get(category, {}).get("success_rate", 0.0) or 0.0)
            for run in runs
        ]
        tool_accuracies = [
            float((run.get("by_category") or {}).get(category, {}).get("tool_accuracy", 0.0) or 0.0)
            for run in runs
        ]
        by_category[category] = {
            "tasks": (runs[0].get("by_category") or {}).get(category, {}).get("tasks", 0),
            "success_rate": _metric_summary(success_rates),
            "tool_accuracy": _metric_summary(tool_accuracies),
        }
    aggregated["by_category"] = by_category
    aggregated["logs_paths"] = [run.get("logs_path") for run in runs if run.get("logs_path")]
    return aggregated


def run_ablation(
    output_dir: Path,
    *,
    samples_path: Path = DEFAULT_SAMPLES,
    mode: str = "router",
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary: Dict[str, Any] = {
        "task": "end2end_ablation",
        "mode": mode,
        "ablation_runs": ABLATION_RUNS,
        "runs": {},
    }

    for name, overrides in ABLATION_CONFIGS.items():
        run_metrics_list: List[Dict[str, Any]] = []
        for run_idx in range(1, ABLATION_RUNS + 1):
            run_dir = output_dir / name / f"run_{run_idx}"
            run_dir.mkdir(parents=True, exist_ok=True)

            env = os.environ.copy()
            env.update(overrides)

            result = subprocess.run(
                [
                    sys.executable,
                    str(END2END_SCRIPT),
                    "--samples",
                    str(samples_path),
                    "--output-dir",
                    str(run_dir),
                    "--mode",
                    mode,
                ],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"Ablation run '{name}' round {run_idx} failed with exit code "
                    f"{result.returncode}: {result.stderr}"
                )

            metrics_path = run_dir / "end2end_metrics.json"
            with metrics_path.open("r", encoding="utf-8") as fh:
                run_metrics_list.append(json.load(fh))

        summary["runs"][name] = {
            "env_overrides": overrides,
            "num_runs": len(run_metrics_list),
            "metrics": _aggregate_ablation_runs(run_metrics_list),
            "individual_runs": run_metrics_list,
        }

    comparison_path = output_dir / "ablation_summary.json"
    with comparison_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run end-to-end ablations.")
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--mode", choices=["router", "tool"], default="router")
    args = parser.parse_args()

    output_dir = args.output_dir or (DEFAULT_OUTPUT_BASE / f"ablation_{now_ts()}")
    summary = run_ablation(output_dir, samples_path=args.samples, mode=args.mode)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
