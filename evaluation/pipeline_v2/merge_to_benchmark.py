"""Merge reviewed benchmark candidates into the canonical benchmark JSONL."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.pipeline_v2.common import (
    DEFAULT_BENCHMARK_PATH,
    VALID_CATEGORIES,
    canonicalize_benchmark_task,
    compute_next_task_id,
    load_jsonl_records,
    save_jsonl,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge approved or auto-valid candidates into benchmark JSONL.")
    parser.add_argument("--reviewed", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_BENCHMARK_PATH)
    parser.add_argument("--exclude-auto-valid", action="store_true", help="Require explicit review approval even for validation=valid tasks.")
    return parser.parse_args()


def _approved_candidates(records: Sequence[Dict[str, Any]], include_auto_valid: bool) -> List[Dict[str, Any]]:
    approved: List[Dict[str, Any]] = []
    for record in records:
        decision = str(record.get("review_decision") or "").strip().lower()
        status = str((record.get("validation") or {}).get("status") or "").strip().lower()
        if decision in {"rejected", "reject", "skipped", "skip"}:
            continue
        if decision in {"approved", "approve", "edited"}:
            approved.append(record)
            continue
        if include_auto_valid and status == "valid":
            approved.append(record)
    return approved


def merge_candidates(
    *,
    reviewed_path: Path,
    benchmark_path: Path,
    output_path: Path,
    include_auto_valid: bool = True,
) -> Dict[str, Any]:
    existing_records = load_jsonl_records(benchmark_path)
    reviewed_records = load_jsonl_records(reviewed_path)
    approved = _approved_candidates(reviewed_records, include_auto_valid)

    existing_messages = {str(record.get("user_message") or "").strip() for record in existing_records}
    merged = list(existing_records)
    added: List[str] = []
    skipped_duplicates: List[str] = []

    for candidate in approved:
        category = str(candidate.get("category") or "").strip()
        if category not in VALID_CATEGORIES:
            continue
        message = str(candidate.get("user_message") or "").strip()
        if not message or message in existing_messages:
            skipped_duplicates.append(str(candidate.get("id") or message))
            continue
        final_task = canonicalize_benchmark_task(candidate)
        final_task["id"] = compute_next_task_id(merged, category)
        final_task.pop("validation", None)
        final_task.pop("candidate_metadata", None)
        final_task.pop("review_decision", None)
        merged.append(final_task)
        existing_messages.add(message)
        added.append(final_task["id"])

    save_jsonl(output_path, merged)
    return {
        "input_candidates": len(reviewed_records),
        "approved_candidates": len(approved),
        "added": added,
        "skipped_duplicates": skipped_duplicates,
        "output": str(output_path),
    }


def main() -> None:
    args = parse_args()
    result = merge_candidates(
        reviewed_path=args.reviewed,
        benchmark_path=args.benchmark,
        output_path=args.output,
        include_auto_valid=not args.exclude_auto_valid,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
