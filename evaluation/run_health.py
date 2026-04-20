from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.eval_end2end import run_end2end_evaluation
from evaluation.utils import load_jsonl, write_jsonl


def _select_preflight_tasks(samples_path: Path, count: int) -> List[Dict[str, Any]]:
    tasks = load_jsonl(samples_path)
    simple = [task for task in tasks if str(task.get("category") or "") == "simple"]
    return simple[:count]


def run_preflight(
    *,
    samples_path: Path,
    output_dir: Path,
    count: int = 5,
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    selected = _select_preflight_tasks(samples_path, count)
    selected_path = output_dir / "preflight_tasks.jsonl"
    write_jsonl(selected_path, selected)
    metrics = run_end2end_evaluation(
        samples_path=selected_path,
        output_dir=output_dir,
        mode="router",
    )
    logs_path = output_dir / "end2end_logs.jsonl"
    logs = load_jsonl(logs_path)
    all_ok = all(str(log.get("infrastructure_status") or "ok") == "ok" for log in logs)
    summary = {
        "task_count": len(logs),
        "all_infrastructure_ok": all_ok,
        "run_status": metrics.get("run_status"),
        "data_integrity": metrics.get("data_integrity"),
        "infrastructure_health": metrics.get("infrastructure_health", {}),
        "provider_balance_check": "unsupported",
        "selected_task_ids": [str(task.get("id") or "") for task in selected],
        "metrics_path": str(output_dir / "end2end_metrics.json"),
        "logs_path": str(logs_path),
    }
    with (output_dir / "preflight_summary.json").open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run benchmark preflight health check.")
    parser.add_argument("--samples", type=Path, default=PROJECT_ROOT / "evaluation" / "benchmarks" / "end2end_tasks.jsonl")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--count", type=int, default=5)
    args = parser.parse_args()

    summary = run_preflight(
        samples_path=args.samples,
        output_dir=args.output_dir,
        count=args.count,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
