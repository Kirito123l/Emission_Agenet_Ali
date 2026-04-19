#!/usr/bin/env python3
"""One-off migration from Phase 2.4 AO payloads to Phase 2R stance schema."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable


def _has_successful_tool_call(ao: Dict[str, Any]) -> bool:
    for item in list(ao.get("tool_call_log") or []):
        if isinstance(item, dict) and bool(item.get("success")):
            return True
    return False


def _has_pending_clarification(ao: Dict[str, Any]) -> bool:
    metadata = ao.get("metadata") if isinstance(ao.get("metadata"), dict) else {}
    contract_state = (
        metadata.get("clarification_contract")
        if isinstance(metadata.get("clarification_contract"), dict)
        else {}
    )
    return bool(contract_state.get("pending"))


def migrate_ao_payload(ao: Dict[str, Any]) -> Dict[str, Any]:
    migrated = dict(ao)
    if "stance" in migrated:
        return migrated
    if _has_successful_tool_call(migrated):
        stance = "directive"
        confidence = "medium"
        resolved_by = "migration:had_execution"
    elif _has_pending_clarification(migrated):
        stance = "deliberative"
        confidence = "medium"
        resolved_by = "migration:had_pending_clarification"
    else:
        stance = "directive"
        confidence = "low"
        resolved_by = "migration:default"
    turn = int(migrated.get("start_turn") or 0)
    migrated["stance"] = stance
    migrated["stance_confidence"] = confidence
    migrated["stance_resolved_by"] = resolved_by
    migrated["stance_history"] = [{"turn": turn, "stance": stance}] if turn else []
    return migrated


def _ao_payloads(root: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    if isinstance(root.get("ao_id"), str):
        yield root
        return
    fact_memory = root.get("fact_memory") if isinstance(root.get("fact_memory"), dict) else {}
    for item in list(fact_memory.get("ao_history") or []):
        if isinstance(item, dict):
            yield item


def migrate_session_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    migrated = dict(payload)
    if isinstance(migrated.get("ao_id"), str):
        return migrate_ao_payload(migrated)

    fact_memory = (
        dict(migrated.get("fact_memory"))
        if isinstance(migrated.get("fact_memory"), dict)
        else {}
    )
    fact_memory["ao_history"] = [
        migrate_ao_payload(item)
        for item in list(fact_memory.get("ao_history") or [])
        if isinstance(item, dict)
    ]
    migrated["fact_memory"] = fact_memory
    return migrated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate Phase 2.4 session/AO JSON to Phase 2R stance schema."
    )
    parser.add_argument("input", type=Path, help="Input session JSON or AO JSON")
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        help="Output JSON path. Defaults to <input>.phase2r.json",
    )
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    migrated = migrate_session_payload(payload)
    output = args.output or args.input.with_suffix(args.input.suffix + ".phase2r.json")
    output.write_text(json.dumps(migrated, ensure_ascii=False, indent=2), encoding="utf-8")
    count = sum(1 for _ in _ao_payloads(migrated))
    print(f"Migrated {count} analytical objective(s) to {output}")


if __name__ == "__main__":
    main()
