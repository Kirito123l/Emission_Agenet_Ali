"""Minimal human review CLI for validated benchmark candidates."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.pipeline_v2.common import load_jsonl_records, save_jsonl


EDITABLE_FIELDS = ("user_message", "description", "expected_params", "expected_tool_chain", "success_criteria")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review needs_review benchmark candidates.")
    parser.add_argument("--input", type=Path, default=PROJECT_ROOT / "evaluation" / "pipeline_v2" / "validated_candidates.jsonl")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "evaluation" / "pipeline_v2" / "reviewed_candidates.jsonl")
    return parser.parse_args()


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _print_task(task: Dict[str, Any], index: int, total: int) -> None:
    validation = task.get("validation") or {}
    layers = validation.get("layers") or {}
    llm_review = (((layers.get("llm_review") or {}).get("details") or {}).get("review") or {})
    print("=" * 72)
    print(f"Task {index}/{total} ({validation.get('status', 'unknown')})")
    print(f"ID: {task.get('id')}")
    print(f"Category: {task.get('category')}")
    print(f"Message: {task.get('user_message')}")
    print(f"Tool chain: {task.get('expected_tool_chain')}")
    print(f"Expected params: {_compact_json(task.get('expected_params', {}))}")
    print(f"Success criteria: {_compact_json(task.get('success_criteria', {}))}")
    if validation.get("issues"):
        print("Issues:")
        for issue in validation["issues"]:
            print(f"  - {issue}")
    if llm_review:
        print("LLM Review:")
        print(_compact_json(llm_review))
    print("[A]pprove  [R]eject  [E]dit  [S]kip")


def _edit_task(task: Dict[str, Any]) -> None:
    print("Editable fields:", ", ".join(EDITABLE_FIELDS))
    field = input("Field to edit (blank to cancel): ").strip()
    if not field:
        return
    if field not in EDITABLE_FIELDS:
        print(f"Unsupported field: {field}")
        return
    current = task.get(field)
    print("Current value:")
    print(_compact_json(current))
    raw_value = input("New value (JSON for dict/list fields): ").strip()
    if not raw_value:
        return
    if field in {"expected_params", "expected_tool_chain", "success_criteria"}:
        try:
            task[field] = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON: {exc}")
            return
    else:
        task[field] = raw_value
    task["review_decision"] = "edited"


def review(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    needs_review = [
        task for task in records if (task.get("validation") or {}).get("status") == "needs_review"
    ]
    if not needs_review:
        return records
    if not sys.stdin.isatty():
        raise SystemExit("review_cli.py requires an interactive TTY when tasks need review.")

    for index, task in enumerate(needs_review, start=1):
        while True:
            _print_task(task, index, len(needs_review))
            choice = input("> ").strip().lower()
            if choice in {"a", "approve"}:
                task["review_decision"] = "approved"
                break
            if choice in {"r", "reject"}:
                task["review_decision"] = "rejected"
                break
            if choice in {"s", "skip"}:
                task["review_decision"] = "skipped"
                break
            if choice in {"e", "edit"}:
                _edit_task(task)
                continue
            print("Unknown choice.")
    return records


def main() -> None:
    args = parse_args()
    records = load_jsonl_records(args.input)
    reviewed = review(records)
    save_jsonl(args.output, reviewed)
    counts: Dict[str, int] = {}
    for task in reviewed:
        decision = str(task.get("review_decision") or (task.get("validation") or {}).get("status") or "unknown")
        counts[decision] = counts.get(decision, 0) + 1
    print(json.dumps({"reviewed": len(reviewed), "decision_counts": counts, "output": str(args.output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
