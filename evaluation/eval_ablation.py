"""Run baseline and ablation matrix for paper experiments."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.eval_end2end import run_end2end_evaluation
from evaluation.eval_file_grounding import run_file_grounding_evaluation
from evaluation.eval_normalization import run_normalization_evaluation
from evaluation.utils import now_ts, write_json


BASELINES: Dict[str, Dict[str, Any]] = {
    "full_system": {
        "enable_file_analyzer": True,
        "enable_file_context_injection": True,
        "enable_executor_standardization": True,
        "macro_column_mapping_modes": ("direct", "ai", "fuzzy"),
        "mode": "tool",
        "only_task": None,
    },
    "no_file_awareness": {
        "enable_file_analyzer": False,
        "enable_file_context_injection": False,
        "enable_executor_standardization": True,
        "macro_column_mapping_modes": ("direct", "ai", "fuzzy"),
        "mode": "tool",
        "only_task": None,
    },
    "no_executor_standardization": {
        "enable_file_analyzer": True,
        "enable_file_context_injection": True,
        "enable_executor_standardization": False,
        "macro_column_mapping_modes": ("direct", "ai", "fuzzy"),
        "mode": "tool",
        "only_task": None,
    },
    "macro_rule_only": {
        "enable_file_analyzer": False,
        "enable_file_context_injection": False,
        "enable_executor_standardization": False,
        "macro_column_mapping_modes": ("direct", "fuzzy"),
        "mode": "tool",
        "only_task": "calculate_macro_emission",
    },
}


def run_ablation(output_dir: Path) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary: Dict[str, Any] = {"baselines": {}}

    for name, config in BASELINES.items():
        baseline_dir = output_dir / name
        normalization_metrics = run_normalization_evaluation(
            samples_path=PROJECT_ROOT / "evaluation/normalization/samples.jsonl",
            output_dir=baseline_dir / "normalization",
            enable_executor_standardization=config["enable_executor_standardization"],
        )
        file_metrics = run_file_grounding_evaluation(
            samples_path=PROJECT_ROOT / "evaluation/file_tasks/samples.jsonl",
            output_dir=baseline_dir / "file_grounding",
            enable_file_analyzer=config["enable_file_analyzer"],
            enable_file_context_injection=config["enable_file_context_injection"],
            macro_column_mapping_modes=config["macro_column_mapping_modes"],
        )
        end2end_metrics = run_end2end_evaluation(
            samples_path=PROJECT_ROOT / "evaluation/end2end/samples.jsonl",
            output_dir=baseline_dir / "end2end",
            mode=config["mode"],
            enable_file_analyzer=config["enable_file_analyzer"],
            enable_file_context_injection=config["enable_file_context_injection"],
            enable_executor_standardization=config["enable_executor_standardization"],
            macro_column_mapping_modes=config["macro_column_mapping_modes"],
            only_task=config["only_task"],
        )
        summary["baselines"][name] = {
            "config": {
                "enable_file_analyzer": config["enable_file_analyzer"],
                "enable_file_context_injection": config["enable_file_context_injection"],
                "enable_executor_standardization": config["enable_executor_standardization"],
                "macro_column_mapping_modes": list(config["macro_column_mapping_modes"]),
                "mode": config["mode"],
                "only_task": config["only_task"],
            },
            "metrics": {
                "normalization": normalization_metrics,
                "file_grounding": file_metrics,
                "end2end": end2end_metrics,
            },
        }

    write_json(output_dir / "ablation_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run benchmark baselines and ablations.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / f"evaluation/logs/ablation_{now_ts()}",
    )
    args = parser.parse_args()
    summary = run_ablation(args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
