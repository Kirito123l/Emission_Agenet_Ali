"""Merge reviewed generated hard cases into the formal standardization benchmark."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.context_extractor import STANDARDIZATION_DIMENSIONS, load_jsonl_records
from evaluation.utils import write_jsonl


BENCHMARK_PATH = PROJECT_ROOT / "evaluation" / "benchmarks" / "standardization_benchmark.jsonl"
GENERATED_DIR = PROJECT_ROOT / "evaluation" / "generated"

MERGEABLE_STATUSES = {"confirmed_correct", "confirmed_abstain"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge reviewed generated hard cases into the benchmark.")
    parser.add_argument("--confirm", action="store_true", help="Actually write merged results back to the benchmark file.")
    return parser.parse_args()


def _parse_numeric_suffix(raw_id: str) -> int:
    tail = str(raw_id).rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _normalize_raw_input(value: Any) -> str:
    return str(value).strip()


def _load_generated_records() -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for dimension in STANDARDIZATION_DIMENSIONS:
        path = GENERATED_DIR / f"hard_cases_{dimension}.jsonl"
        if path.exists():
            records.extend(load_jsonl_records(path))
    return records


def _benchmark_record(record: Dict[str, Any], new_id: str) -> Dict[str, Any]:
    return {
        "dimension": record["dimension"],
        "difficulty": record.get("difficulty", "hard"),
        "raw_input": record["raw_input"],
        "expected_output": record.get("expected_output"),
        "language": record.get("language", "mixed"),
        "notes": record.get("notes", ""),
        "id": new_id,
    }


def _count_by_dimension_and_difficulty(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    counts: Dict[str, Dict[str, int]] = {}
    for record in records:
        dimension = str(record.get("dimension", "unknown"))
        difficulty = str(record.get("difficulty", "unknown"))
        counts.setdefault(dimension, {})
        counts[dimension][difficulty] = counts[dimension].get(difficulty, 0) + 1
    return counts


def main() -> None:
    args = parse_args()

    benchmark_records = load_jsonl_records(BENCHMARK_PATH)
    generated_records = _load_generated_records()
    existing_inputs = {_normalize_raw_input(record.get("raw_input", "")) for record in benchmark_records}

    next_id = max((_parse_numeric_suffix(record.get("id", "")) for record in benchmark_records), default=0) + 1
    merged_records: List[Dict[str, Any]] = []
    skipped = Counter()

    for record in generated_records:
        status = str((record.get("validation") or {}).get("status", "needs_review"))
        raw_input = _normalize_raw_input(record.get("raw_input", ""))
        if status not in MERGEABLE_STATUSES:
            skipped[f"status:{status}"] += 1
            continue
        if not raw_input:
            skipped["empty_raw_input"] += 1
            continue
        if raw_input in existing_inputs:
            skipped["duplicate_raw_input"] += 1
            continue

        new_id = f"{record['dimension']}_{record.get('difficulty', 'hard')}_{next_id:04d}"
        merged_records.append(_benchmark_record(record, new_id))
        existing_inputs.add(raw_input)
        next_id += 1

    final_records = benchmark_records + merged_records
    report = {
        "confirm": bool(args.confirm),
        "benchmark_path": str(BENCHMARK_PATH),
        "existing_records": len(benchmark_records),
        "merge_candidates": len(generated_records),
        "merged_records": len(merged_records),
        "skipped": dict(sorted(skipped.items())),
        "counts_before": _count_by_dimension_and_difficulty(benchmark_records),
        "counts_after": _count_by_dimension_and_difficulty(final_records),
    }

    if args.confirm and merged_records:
        write_jsonl(BENCHMARK_PATH, final_records)

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
