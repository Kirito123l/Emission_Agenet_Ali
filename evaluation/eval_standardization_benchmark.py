"""Evaluate parameter standardization on the generated benchmark."""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_config, reset_config
from evaluation.utils import write_json, write_jsonl
from services.standardization_engine import StandardizationEngine
from services.standardizer import StandardizationResult, reset_standardizer


BENCHMARK_PATH = PROJECT_ROOT / "evaluation" / "benchmarks" / "standardization_benchmark.jsonl"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "evaluation" / "results" / "standardization"


DIMENSION_TO_PARAM_TYPE = {
    "vehicle_type": "vehicle_type",
    "pollutant": "pollutant",
    "season": "season",
    "road_type": "road_type",
    "meteorology": "meteorology",
    "stability_class": "stability_class",
}


@dataclass
class EvalRecord:
    case_id: str
    dimension: str
    difficulty: str
    raw_input: str
    expected: Optional[str]
    actual: Optional[str]
    strategy: str
    confidence: float
    correct: bool
    abstained: bool


def _bool_from_env(name: str, default: bool) -> bool:
    return os.getenv(name, "true" if default else "false").strip().lower() == "true"


def detect_mode() -> str:
    fuzzy_enabled = _bool_from_env("STANDARDIZATION_FUZZY_ENABLED", True)
    model_enabled = _bool_from_env("ENABLE_LLM_STANDARDIZATION", True)
    if not fuzzy_enabled and not model_enabled:
        return "rule_only"
    if fuzzy_enabled and not model_enabled:
        return "rule_fuzzy"
    if fuzzy_enabled and model_enabled:
        return "full"
    return "custom"


def apply_mode_overrides(mode: str) -> None:
    if mode == "auto":
        return
    overrides = {
        "rule_only": {
            "STANDARDIZATION_FUZZY_ENABLED": "false",
            "ENABLE_LLM_STANDARDIZATION": "false",
        },
        "rule_fuzzy": {
            "STANDARDIZATION_FUZZY_ENABLED": "true",
            "ENABLE_LLM_STANDARDIZATION": "false",
        },
        "full": {
            "STANDARDIZATION_FUZZY_ENABLED": "true",
            "ENABLE_LLM_STANDARDIZATION": "true",
        },
    }
    for key, value in overrides.get(mode, {}).items():
        os.environ[key] = value


def load_benchmark(path: Path) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def build_engine() -> StandardizationEngine:
    reset_config()
    reset_standardizer()
    runtime_config = get_config()
    return StandardizationEngine(dict(runtime_config.standardization_config))


def evaluate_single(engine: StandardizationEngine, case: Dict[str, Any]) -> EvalRecord:
    dimension = str(case["dimension"])
    param_type = DIMENSION_TO_PARAM_TYPE.get(dimension)
    if param_type is None:
        return EvalRecord(
            case_id=str(case["id"]),
            dimension=dimension,
            difficulty=str(case.get("difficulty", "unknown")),
            raw_input=str(case.get("raw_input", "")),
            expected=case.get("expected_output"),
            actual=None,
            strategy="unsupported",
            confidence=0.0,
            correct=False,
            abstained=True,
        )

    result: StandardizationResult = engine.standardize(param_type, case.get("raw_input"))
    actual = result.normalized
    strategy = result.strategy
    confidence = float(result.confidence or 0.0)
    abstained = (not result.success) or strategy in {"abstain", "none"}
    expected = case.get("expected_output")

    if expected is None:
        correct = abstained or actual is None
    else:
        correct = actual == expected

    return EvalRecord(
        case_id=str(case["id"]),
        dimension=dimension,
        difficulty=str(case.get("difficulty", "unknown")),
        raw_input=str(case.get("raw_input", "")),
        expected=expected,
        actual=actual,
        strategy=strategy,
        confidence=confidence,
        correct=correct,
        abstained=abstained,
    )


def compute_metrics(records: List[EvalRecord], mode: str) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {
        "mode": mode,
        "overall": {},
        "by_dimension": {},
        "by_difficulty": {},
        "by_dimension_difficulty": {},
        "strategy_distribution": {},
    }

    total = len(records)
    correct = sum(1 for record in records if record.correct)
    covered = sum(1 for record in records if not record.abstained)
    avg_confidence = sum(record.confidence for record in records) / total if total else 0.0
    metrics["overall"] = {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "coverage": round(covered / total, 4) if total else 0.0,
        "avg_confidence": round(avg_confidence, 4),
    }

    by_dimension: Dict[str, List[EvalRecord]] = defaultdict(list)
    by_difficulty: Dict[str, List[EvalRecord]] = defaultdict(list)
    by_dimension_difficulty: Dict[str, List[EvalRecord]] = defaultdict(list)
    for record in records:
        by_dimension[record.dimension].append(record)
        by_difficulty[record.difficulty].append(record)
        by_dimension_difficulty[f"{record.dimension}:{record.difficulty}"].append(record)

    def _bucket_metrics(bucket: List[EvalRecord]) -> Dict[str, Any]:
        size = len(bucket)
        bucket_correct = sum(1 for record in bucket if record.correct)
        bucket_covered = sum(1 for record in bucket if not record.abstained)
        bucket_confidence = sum(record.confidence for record in bucket) / size if size else 0.0
        return {
            "total": size,
            "correct": bucket_correct,
            "accuracy": round(bucket_correct / size, 4) if size else 0.0,
            "coverage": round(bucket_covered / size, 4) if size else 0.0,
            "avg_confidence": round(bucket_confidence, 4),
        }

    for name, bucket in sorted(by_dimension.items()):
        metrics["by_dimension"][name] = _bucket_metrics(bucket)
    for name, bucket in sorted(by_difficulty.items()):
        metrics["by_difficulty"][name] = _bucket_metrics(bucket)
    for name, bucket in sorted(by_dimension_difficulty.items()):
        metrics["by_dimension_difficulty"][name] = _bucket_metrics(bucket)

    metrics["strategy_distribution"] = dict(sorted(Counter(record.strategy for record in records).items()))
    return metrics


def run_evaluation(benchmark_path: Path, output_dir: Path, mode: str = "auto") -> Dict[str, Any]:
    apply_mode_overrides(mode)
    resolved_mode = detect_mode() if mode == "auto" else mode
    engine = build_engine()
    records = [evaluate_single(engine, case) for case in load_benchmark(benchmark_path)]
    metrics = compute_metrics(records, resolved_mode)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_dir / "standardization_eval_logs.jsonl", [asdict(record) for record in records])
    write_json(output_dir / "standardization_eval_metrics.json", metrics)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate parameter standardization on the benchmark.")
    parser.add_argument("--benchmark", type=Path, default=BENCHMARK_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--mode", choices=["auto", "rule_only", "rule_fuzzy", "full"], default="auto")
    args = parser.parse_args()

    metrics = run_evaluation(args.benchmark, args.output_dir, mode=args.mode)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
