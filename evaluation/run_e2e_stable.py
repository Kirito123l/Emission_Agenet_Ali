"""Run end-to-end evaluation multiple times to get stable metrics."""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


EVAL_SCRIPT = Path(__file__).parent / "eval_end2end.py"
OUTPUT_BASE = Path(__file__).parent / "results" / "end2end_stable"
DEFAULT_SAMPLES = Path(__file__).parent / "benchmarks" / "end2end_tasks.jsonl"
KEY_METRICS = (
    "completion_rate",
    "tool_accuracy",
    "parameter_legal_rate",
    "result_data_rate",
)


def run_single(run_id: int, output_dir: Path, samples_path: Path) -> Dict[str, Any]:
    """Run a single end-to-end evaluation round."""
    run_dir = output_dir / f"run_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            sys.executable,
            str(EVAL_SCRIPT),
            "--samples",
            str(samples_path),
            "--output-dir",
            str(run_dir),
            "--mode",
            "router",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        error = (result.stderr or result.stdout or "unknown error")[:500]
        print(f"Run {run_id} failed: {error}")
        return {"run_id": run_id, "error": error}

    metrics_path = run_dir / "end2end_metrics.json"
    if not metrics_path.exists():
        return {"run_id": run_id, "error": "metrics file not found"}

    with metrics_path.open("r", encoding="utf-8") as fh:
        metrics = json.load(fh)

    print(
        "Run "
        f"{run_id}: completion={metrics.get('completion_rate')}, "
        f"tool_acc={metrics.get('tool_accuracy')}, "
        f"param_legal={metrics.get('parameter_legal_rate')}"
    )

    return {"run_id": run_id, "metrics": metrics}


def _aggregate_series(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {
            "values": [],
            "mean": 0,
            "median": 0,
            "stdev": 0,
            "min": 0,
            "max": 0,
        }

    return {
        "values": values,
        "mean": round(statistics.mean(values), 4),
        "median": round(statistics.median(values), 4),
        "stdev": round(statistics.stdev(values), 4) if len(values) > 1 else 0,
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def aggregate_runs(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute mean, median, and standard deviation across runs."""
    valid_runs = [item for item in runs if "metrics" in item]
    if not valid_runs:
        return {"error": "no valid runs"}

    summary: Dict[str, Any] = {
        "total_runs": len(runs),
        "valid_runs": len(valid_runs),
        "failed_runs": len(runs) - len(valid_runs),
    }

    for metric_name in KEY_METRICS:
        values = [float(run["metrics"].get(metric_name, 0) or 0) for run in valid_runs]
        summary[metric_name] = _aggregate_series(values)

    categories = sorted(
        {
            category
            for run in valid_runs
            for category in (run["metrics"].get("by_category") or {}).keys()
        }
    )
    by_category: Dict[str, Any] = {}
    for category in categories:
        success_values = []
        tool_values = []
        for run in valid_runs:
            category_metrics = (run["metrics"].get("by_category") or {}).get(category, {})
            success_values.append(float(category_metrics.get("success_rate", 0) or 0))
            tool_values.append(float(category_metrics.get("tool_accuracy", 0) or 0))

        by_category[category] = {
            "success_rate": _aggregate_series(success_values),
            "tool_accuracy": _aggregate_series(tool_values),
        }

    summary["by_category"] = by_category
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run e2e evaluation multiple times for stable metrics."
    )
    parser.add_argument("--runs", type=int, default=3, help="Number of evaluation runs")
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = args.output_dir or OUTPUT_BASE / f"stable_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Running {args.runs} evaluation rounds...")
    print(f"Samples: {args.samples}")
    print(f"Output: {output_dir}")
    print("=" * 60)

    runs: List[Dict[str, Any]] = []
    for run_id in range(1, args.runs + 1):
        print(f"\n--- Run {run_id}/{args.runs} ---")
        runs.append(run_single(run_id, output_dir, args.samples))

    print("\n" + "=" * 60)
    print("Aggregating results...")

    summary = aggregate_runs(runs)
    summary["timestamp"] = timestamp
    summary["samples_path"] = str(args.samples)
    summary["individual_runs"] = runs

    summary_path = output_dir / "stable_summary.json"
    with summary_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("STABLE EVALUATION SUMMARY")
    print("=" * 60)
    for metric_name in (
        "completion_rate",
        "tool_accuracy",
        "parameter_legal_rate",
    ):
        data = summary.get(metric_name, {})
        print(
            f"{metric_name:>25s}: mean={data.get('mean', 0):.4f}  "
            f"median={data.get('median', 0):.4f}  "
            f"std={data.get('stdev', 0):.4f}  "
            f"range=[{data.get('min', 0):.4f}, {data.get('max', 0):.4f}]"
        )

    print("\nPer-category success_rate (median):")
    for category, category_metrics in sorted(summary.get("by_category", {}).items()):
        series = category_metrics.get("success_rate", {})
        print(f"  {category:>25s}: {series.get('median', 0):.4f} (std={series.get('stdev', 0):.4f})")

    print(f"\nFull summary saved to: {summary_path}")


if __name__ == "__main__":
    main()
