"""Run end-to-end ablations over the structured benchmark task set."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

END2END_SCRIPT = PROJECT_ROOT / "evaluation" / "eval_end2end.py"
DEFAULT_SAMPLES = PROJECT_ROOT / "evaluation" / "benchmarks" / "end2end_tasks.jsonl"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "evaluation" / "results" / "ablation"

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


def run_ablation(
    output_dir: Path,
    *,
    samples_path: Path = DEFAULT_SAMPLES,
    mode: str = "router",
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary: Dict[str, Any] = {"task": "end2end_ablation", "mode": mode, "runs": {}}

    for name, overrides in ABLATION_CONFIGS.items():
        run_dir = output_dir / name
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
                f"Ablation run '{name}' failed with exit code {result.returncode}: {result.stderr}"
            )

        metrics_path = run_dir / "end2end_metrics.json"
        with metrics_path.open("r", encoding="utf-8") as fh:
            metrics = json.load(fh)

        summary["runs"][name] = {
            "env_overrides": overrides,
            "metrics": metrics,
        }

    comparison_path = output_dir / "ablation_summary.json"
    with comparison_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run end-to-end ablations.")
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--mode", choices=["router", "tool"], default="router")
    args = parser.parse_args()

    summary = run_ablation(args.output_dir, samples_path=args.samples, mode=args.mode)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
