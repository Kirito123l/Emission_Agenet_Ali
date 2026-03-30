"""Run the lowest-friction local evaluation smoke suite.

This is the canonical minimal reproducibility path for the current evaluation
framework. It reuses the existing benchmark runners with conservative defaults:

- normalization evaluation
- file-grounding evaluation
- end-to-end evaluation in `tool` mode

The default macro mapping modes are `direct,fuzzy` to avoid depending on the
AI-only mapping step for the smallest local validation run.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.eval_end2end import run_end2end_evaluation
from evaluation.eval_file_grounding import run_file_grounding_evaluation
from evaluation.eval_normalization import run_normalization_evaluation
from evaluation.utils import now_ts, write_json

DEFAULT_MACRO_MODES: Tuple[str, ...] = ("direct", "fuzzy")


def run_smoke_suite(
    output_dir: Path,
    enable_file_analyzer: bool = True,
    enable_file_context_injection: bool = True,
    enable_executor_standardization: bool = True,
    macro_column_mapping_modes: Tuple[str, ...] = DEFAULT_MACRO_MODES,
) -> Dict[str, Any]:
    """Run the recommended smoke-level evaluation set and persist a summary."""
    output_dir.mkdir(parents=True, exist_ok=True)

    normalization_metrics = run_normalization_evaluation(
        samples_path=PROJECT_ROOT / "evaluation/normalization/samples.jsonl",
        output_dir=output_dir / "normalization",
        enable_executor_standardization=enable_executor_standardization,
    )
    file_grounding_metrics = run_file_grounding_evaluation(
        samples_path=PROJECT_ROOT / "evaluation/file_tasks/samples.jsonl",
        output_dir=output_dir / "file_grounding",
        enable_file_analyzer=enable_file_analyzer,
        enable_file_context_injection=enable_file_context_injection,
        macro_column_mapping_modes=macro_column_mapping_modes,
    )
    end2end_metrics = run_end2end_evaluation(
        samples_path=PROJECT_ROOT / "evaluation/end2end/samples.jsonl",
        output_dir=output_dir / "end2end",
        mode="tool",
        enable_file_analyzer=enable_file_analyzer,
        enable_file_context_injection=enable_file_context_injection,
        enable_executor_standardization=enable_executor_standardization,
        macro_column_mapping_modes=macro_column_mapping_modes,
        only_task=None,
    )

    summary = {
        "suite": "smoke",
        "recommended_defaults": {
            "mode": "tool",
            "enable_file_analyzer": enable_file_analyzer,
            "enable_file_context_injection": enable_file_context_injection,
            "enable_executor_standardization": enable_executor_standardization,
            "macro_column_mapping_modes": list(macro_column_mapping_modes),
        },
        "metrics": {
            "normalization": normalization_metrics,
            "file_grounding": file_grounding_metrics,
            "end2end": end2end_metrics,
        },
    }
    write_json(output_dir / "smoke_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the minimal local evaluation smoke suite.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / f"evaluation/results/smoke/smoke_{now_ts()}",
    )
    parser.add_argument("--disable-file-analyzer", action="store_true")
    parser.add_argument("--disable-file-context-injection", action="store_true")
    parser.add_argument("--disable-executor-standardization", action="store_true")
    parser.add_argument(
        "--macro-modes",
        default="direct,fuzzy",
        help="Comma-separated macro column mapping modes for the smoke run.",
    )
    args = parser.parse_args()

    summary = run_smoke_suite(
        output_dir=args.output_dir,
        enable_file_analyzer=not args.disable_file_analyzer,
        enable_file_context_injection=not args.disable_file_context_injection,
        enable_executor_standardization=not args.disable_executor_standardization,
        macro_column_mapping_modes=tuple(mode.strip() for mode in args.macro_modes.split(",") if mode.strip()),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
