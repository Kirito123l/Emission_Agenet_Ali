"""Run rule-only, fuzzy, and full-model standardization benchmark ablations."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_BASE = PROJECT_ROOT / "evaluation" / "results" / "standardization_ablation"
EVAL_SCRIPT = PROJECT_ROOT / "evaluation" / "eval_standardization_benchmark.py"
MODES = ("rule_only", "rule_fuzzy", "full")


def run_mode(mode: str) -> Path:
    output_dir = OUTPUT_BASE / mode
    output_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    if mode == "rule_only":
        env["STANDARDIZATION_FUZZY_ENABLED"] = "false"
        env["ENABLE_LLM_STANDARDIZATION"] = "false"
    elif mode == "rule_fuzzy":
        env["STANDARDIZATION_FUZZY_ENABLED"] = "true"
        env["ENABLE_LLM_STANDARDIZATION"] = "false"
    elif mode == "full":
        env["STANDARDIZATION_FUZZY_ENABLED"] = "true"
        env["ENABLE_LLM_STANDARDIZATION"] = "true"

    result = subprocess.run(
        [sys.executable, str(EVAL_SCRIPT), "--output-dir", str(output_dir), "--mode", mode],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    print(f"=== Mode: {mode} ===")
    print(result.stdout)
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr)
        raise RuntimeError(f"Benchmark ablation mode failed: {mode}")

    return output_dir / "standardization_eval_metrics.json"


def compare_results() -> Dict[str, Any]:
    comparison: Dict[str, Any] = {}
    for mode in MODES:
        metrics_path = OUTPUT_BASE / mode / "standardization_eval_metrics.json"
        if not metrics_path.exists():
            continue
        with metrics_path.open("r", encoding="utf-8") as fh:
            comparison[mode] = json.load(fh)

    summary_path = OUTPUT_BASE / "comparison.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8") as fh:
        json.dump(comparison, fh, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("标准化策略对比")
    print("=" * 60)
    print(f"{'Mode':<15} {'Accuracy':<12} {'Coverage':<12} {'Avg Conf':<12}")
    print("-" * 60)
    for mode in MODES:
        overall = comparison.get(mode, {}).get("overall", {})
        print(
            f"{mode:<15} "
            f"{overall.get('accuracy', 0.0):<12.4f} "
            f"{overall.get('coverage', 0.0):<12.4f} "
            f"{overall.get('avg_confidence', 0.0):<12.4f}"
        )
    return comparison


def main() -> None:
    for mode in MODES:
        run_mode(mode)
    compare_results()


if __name__ == "__main__":
    main()
