"""Run 7: Shanghai e2e workflow — macro emission → dispersion → hotspot map.

Phase 9.1.0: Full trace export (not just steps). Output dir configurable via --output-dir.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.governed_router import GovernedRouter

logger = logging.getLogger(__name__)

SHANGHAI_WORKFLOW_PROMPTS = [
    "请用这个路网文件计算上海地区的CO2和NOx排放，车型是乘用车，季节选夏季",
    "请对刚才的排放结果做扩散模拟",
    "请根据扩散结果分析污染热点，并生成空间地图",
]

# ── Phase 9.1.0: known trace dict top-level keys (from code audit) ──────────
# These are the keys that _may_ appear on RouterResponse.trace after a full
# governed turn.  Presence depends on which code paths were exercised.
EXPECTED_TRACE_KEYS = [
    # From Trace.to_dict() (core/trace.py:235-245)
    "session_id",
    "start_time",
    "end_time",
    "total_duration_ms",
    "final_stage",
    "step_count",
    "steps",
    # From _attach_oasc_trace() (core/contracts/oasc_contract.py:720-759)
    "oasc",
    "classifier_telemetry",
    "ao_lifecycle_events",
    "block_telemetry",
    # Conditional from context.metadata (oasc_contract.py:748-759)
    "reconciled_decision",
    "b_validator_filter",
    "projected_chain",
]


def _safe_serialize(obj: Any, max_depth: int = 4, _depth: int = 0) -> Any:
    """Recursively convert trace objects to JSON-safe types with depth limit."""
    if _depth >= max_depth:
        return str(obj)[:500]
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(v, max_depth, _depth + 1) for v in obj[:200]]
    if isinstance(obj, dict):
        return {str(k): _safe_serialize(v, max_depth, _depth + 1) for k, v in obj.items()}
    if hasattr(obj, "value"):
        # enum
        return obj.value
    try:
        return str(obj)[:1000]
    except Exception:
        return f"<unserializable {type(obj).__name__}>"


def _extract_full_trace(response) -> Dict[str, Any]:
    """Extract the complete trace dict from a RouterResponse, coercing to JSON-safe types."""
    raw = getattr(response, "trace", None)
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return _safe_serialize(raw)
    return {"_raw": str(raw)[:2000]}


async def run_shanghai_workflow(
    output_dir: Path,
    demo_file: str = "evaluation/file_tasks/data/macro_direct.csv",
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    router = GovernedRouter(session_id="shanghai_e2e_demo")
    turn_results: List[Dict[str, Any]] = []
    all_tool_calls: List[Dict[str, Any]] = []
    all_trace_steps: List[Dict[str, Any]] = []

    started_at = time.time()
    for turn_idx, prompt in enumerate(SHANGHAI_WORKFLOW_PROMPTS):
        turn_start = time.time()
        file_path = str(PROJECT_ROOT / demo_file) if turn_idx == 0 else None
        response = await router.chat(
            user_message=prompt,
            file_path=file_path,
        )
        turn_elapsed = time.time() - turn_start

        full_trace = _extract_full_trace(response)
        trace_steps = full_trace.get("steps", []) if isinstance(full_trace, dict) else []

        turn_record = {
            "turn": turn_idx + 1,
            "prompt": prompt,
            "response_text": response.text[:500] if response.text else "",
            "tool_calls": response.executed_tool_calls or [],
            "trace": full_trace,
            "wall_clock_sec": round(turn_elapsed, 2),
        }
        turn_results.append(turn_record)

        if response.executed_tool_calls:
            all_tool_calls.extend(response.executed_tool_calls)
        if trace_steps:
            all_trace_steps.extend(trace_steps)

    total_elapsed = time.time() - started_at

    # Governance step distribution from all captured steps
    governance_steps: Dict[str, int] = {}
    for step in all_trace_steps:
        if isinstance(step, dict):
            step_type = step.get("step_type") or step.get("type") or "unknown"
        else:
            step_type = str(step)
        governance_steps[step_type] = governance_steps.get(step_type, 0) + 1

    # Per-key presence audit across all turns
    trace_key_presence: Dict[str, List[bool]] = {k: [] for k in EXPECTED_TRACE_KEYS}
    for tr in turn_results:
        t = tr.get("trace")
        for k in EXPECTED_TRACE_KEYS:
            trace_key_presence[k].append(k in t if isinstance(t, dict) else False)

    summary = {
        "workflow": "shanghai_e2e",
        "turns": len(SHANGHAI_WORKFLOW_PROMPTS),
        "total_wall_clock_sec": round(total_elapsed, 2),
        "total_tool_calls": len(all_tool_calls),
        "tool_chain": [tc.get("name") for tc in all_tool_calls],
        "governance_step_counts": governance_steps,
        "trace_key_presence_per_turn": {
            k: v for k, v in trace_key_presence.items() if any(v)
        },
        "trace_key_absent_all_turns": [k for k, v in trace_key_presence.items() if not any(v)],
        "turn_results": turn_results,
    }

    summary_path = output_dir / "shanghai_e2e_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    # ── Phase 9.1.0: Export one JSONL line per turn with full trace ──────
    traces_path = output_dir / "shanghai_e2e_traces.jsonl"
    with open(traces_path, "w", encoding="utf-8") as f:
        for tr in turn_results:
            line = {
                "turn": tr["turn"],
                "prompt": tr["prompt"],
                "tool_calls": tr["tool_calls"],
                "trace": tr["trace"],
                "wall_clock_sec": tr["wall_clock_sec"],
            }
            f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")

    # ── Phase 9.1.0: Recheck metadata ─────────────────────────────────────
    git_head = None
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=5,
        )
        if result.returncode == 0:
            git_head = result.stdout.strip()
    except Exception:
        pass

    recheck_meta = {
        "purpose": "Phase 9.1.0 diagnostic re-run of Run 7 Shanghai e2e with full trace export",
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": git_head,
        "comparison_original": {
            "original_run": "phase8_2_2_c2/run7_shanghai_e2e/",
            "original_commit": "edca378 (v1.0-data-frozen)",
            "original_exported_only": "trace_steps (response.trace.get('steps', []))",
            "this_exported": "full trace dict including oasc/classifier_telemetry/ao_lifecycle_events/block_telemetry/reconciled_decision/b_validator_filter/projected_chain",
            "note": "Temporary diagnostic data — not for Phase 9.3 ablation. Do not archive as benchmark.",
        },
    }
    meta_path = output_dir / "recheck_metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(recheck_meta, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({
        "workflow": "shanghai_e2e",
        "turns": len(SHANGHAI_WORKFLOW_PROMPTS),
        "total_wall_clock_sec": round(total_elapsed, 2),
        "tool_chain": summary["tool_chain"],
        "governance_steps": governance_steps,
        "trace_keys_found": sorted(summary["trace_key_presence_per_turn"].keys()),
        "trace_keys_absent": summary["trace_key_absent_all_turns"],
        "output_dir": str(output_dir),
    }, ensure_ascii=False, indent=2))

    return summary


def main():
    parser = argparse.ArgumentParser(description="Run 7: Shanghai e2e workflow")
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: evaluation/results/_temp_phase9_1_0_run7_recheck/)",
    )
    parser.add_argument(
        "--demo-file",
        type=str,
        default="evaluation/file_tasks/data/macro_direct.csv",
        help="Demo CSV file path relative to project root",
    )
    args = parser.parse_args()

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = (
            PROJECT_ROOT / "evaluation" / "results"
            / "_temp_phase9_1_0_run7_recheck"
        )
    asyncio.run(run_shanghai_workflow(output_dir, demo_file=args.demo_file))


if __name__ == "__main__":
    main()
