"""Merge reviewed generated end-to-end tasks into the formal benchmark."""
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

from evaluation.generate_e2e_tasks import CATEGORY_DESCRIPTIONS, CATEGORY_ID_PREFIX
from evaluation.utils import load_jsonl, write_jsonl


BENCHMARK_PATH = PROJECT_ROOT / "evaluation" / "benchmarks" / "end2end_tasks.jsonl"
GENERATED_DIR = PROJECT_ROOT / "evaluation" / "generated"

MERGEABLE_STATUS = "valid"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge reviewed generated e2e tasks into the benchmark.")
    parser.add_argument("--confirm", action="store_true", help="Actually write merged results back to the benchmark file.")
    return parser.parse_args()


def _parse_numeric_suffix(raw_id: str) -> int:
    tail = str(raw_id).rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _normalize_message(value: Any) -> str:
    return str(value).strip()


def _load_generated_records() -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for category in CATEGORY_DESCRIPTIONS:
        path = GENERATED_DIR / f"e2e_tasks_{category}.jsonl"
        if path.exists():
            records.extend(load_jsonl(path))
    return records


def _next_id_map(existing_records: List[Dict[str, Any]]) -> Dict[str, int]:
    next_ids: Dict[str, int] = {}
    for category, prefix in CATEGORY_ID_PREFIX.items():
        max_suffix = max(
            (
                _parse_numeric_suffix(record.get("id", ""))
                for record in existing_records
                if str(record.get("id", "")).startswith(f"e2e_{prefix}_")
            ),
            default=0,
        )
        next_ids[category] = max_suffix + 1
    return next_ids


def _count_by_category(records: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for record in records:
        category = str(record.get("category", "unknown"))
        counts[category] = counts.get(category, 0) + 1
    return counts


def _benchmark_record(record: Dict[str, Any], new_id: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "id": new_id,
        "category": record["category"],
        "description": record.get("description", ""),
        "user_message": record.get("user_message", ""),
        "has_file": bool(record.get("has_file")),
        "test_file": record.get("test_file"),
        "expected_tool_chain": list(record.get("expected_tool_chain", []) or []),
        "expected_params": dict(record.get("expected_params", {}) or {}),
        "success_criteria": dict(record.get("success_criteria", {}) or {}),
    }
    expected_tool = record.get("expected_tool")
    if expected_tool and len(payload["expected_tool_chain"]) == 1:
        payload["expected_tool"] = expected_tool
    return payload


def main() -> None:
    args = parse_args()

    benchmark_records = load_jsonl(BENCHMARK_PATH)
    generated_records = _load_generated_records()
    existing_messages = {_normalize_message(record.get("user_message", "")) for record in benchmark_records}
    next_ids = _next_id_map(benchmark_records)

    merged_records: List[Dict[str, Any]] = []
    skipped = Counter()

    for record in generated_records:
        category = str(record.get("category", ""))
        status = str((record.get("validation") or {}).get("status", "needs_review"))
        user_message = _normalize_message(record.get("user_message", ""))

        if status != MERGEABLE_STATUS:
            skipped[f"status:{status}"] += 1
            continue
        if category not in CATEGORY_ID_PREFIX:
            skipped["unknown_category"] += 1
            continue
        if not user_message:
            skipped["empty_user_message"] += 1
            continue
        if user_message in existing_messages:
            skipped["duplicate_user_message"] += 1
            continue

        new_id = f"e2e_{CATEGORY_ID_PREFIX[category]}_{next_ids[category]:03d}"
        next_ids[category] += 1
        merged_records.append(_benchmark_record(record, new_id))
        existing_messages.add(user_message)

    final_records = benchmark_records + merged_records
    report = {
        "confirm": bool(args.confirm),
        "benchmark_path": str(BENCHMARK_PATH),
        "existing_records": len(benchmark_records),
        "merge_candidates": len(generated_records),
        "merged_records": len(merged_records),
        "skipped": dict(sorted(skipped.items())),
        "counts_before": _count_by_category(benchmark_records),
        "counts_after": _count_by_category(final_records),
    }

    if args.confirm and merged_records:
        write_jsonl(BENCHMARK_PATH, final_records)

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
