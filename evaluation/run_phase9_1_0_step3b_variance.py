"""Phase 9.1.0 Step 3b — LLM Variance Quantification Runner.

Runs 5 benchmark tasks × 3 trials in governance_full mode to measure
chain/outcome consistency across trials for DeepSeek deepseek-v4-pro.

Usage:
  python evaluation/run_phase9_1_0_step3b_variance.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.governed_router import GovernedRouter
from tools.registry import init_tools


TASK_IDS = [
    "e2e_ambiguous_001",
    "e2e_ambiguous_002",
    "e2e_ambiguous_003",
    "e2e_multistep_001",
    "e2e_constraint_001",
]
NUM_TRIALS = 3
BASE_DIR = PROJECT_ROOT / "evaluation" / "results" / "_temp_phase9_1_0_step3b_variance"


def _load_benchmark():
    benchmark_path = PROJECT_ROOT / "evaluation" / "benchmarks" / "end2end_tasks.jsonl"
    tasks = {}
    with open(benchmark_path) as f:
        for line in f:
            d = json.loads(line)
            tasks[d["id"]] = d
    return tasks


def _cleanup_state():
    for sub in ["history", "router_state"]:
        d = PROJECT_ROOT / "data" / "sessions" / sub
        if d.exists():
            for f in d.glob("*.json"):
                f.unlink()


async def run_one_trial(task, task_id, trial_n):
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    session_id = f"phase9_1_0_step3b_variance_{task_id}_trial{trial_n}_{timestamp}"

    output_dir = BASE_DIR / task_id / f"trial_{trial_n}"
    output_dir.mkdir(parents=True, exist_ok=True)

    user_message = f"[step3b_trial={trial_n}_{timestamp}]\n\n{task['user_message']}"

    # Resolve file path from benchmark test_file field
    file_path = None
    test_file = task.get("test_file")
    if test_file:
        fp = PROJECT_ROOT / test_file
        if fp.exists():
            file_path = str(fp)

    _cleanup_state()
    init_tools()

    t0 = time.time()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting {task_id} trial {trial_n}...", flush=True)

    router = GovernedRouter(session_id=session_id)
    result = await router.chat(
        user_message=user_message,
        file_path=file_path,
    )
    elapsed = time.time() - t0

    trace = getattr(result, "trace", None) or {}
    steps = trace.get("steps", [])
    step_types = []
    for s in steps:
        if isinstance(s, dict):
            step_types.append(s.get("step_type", "?"))

    tool_calls = getattr(result, "executed_tool_calls", None) or []
    tool_names = [tc.get("name", "?") for tc in tool_calls if tc is not None]
    tool_successes = [
        (tc.get("result", {}).get("success") if isinstance(tc.get("result"), dict) else None)
        for tc in tool_calls if tc is not None
    ]
    response_text = getattr(result, "text", "") or ""

    if tool_successes and all(s is True for s in tool_successes):
        outcome = "success"
    elif tool_successes and any(s is False for s in tool_successes):
        outcome = "fail"
    elif not tool_names:
        outcome = "blocked"
    else:
        outcome = "partial"

    trial_output = {
        "trial_metadata": {
            "task_id": task_id,
            "trial_id": trial_n,
            "session_id": session_id,
            "run_started_utc": datetime.now(timezone.utc).isoformat(),
            "user_message": user_message,
        },
        "outcome": {
            "tool_chain": tool_names,
            "tool_successes": tool_successes,
            "tool_count": len(tool_names),
            "response_text": response_text[:1000],
            "wall_clock_sec": round(elapsed, 2),
            "outcome_label": outcome,
        },
        "trace_step_types": {
            "sequence": step_types,
            "total_steps": len(step_types),
        },
        "trace": trace,
    }

    with open(output_dir / "trial_output.json", "w", encoding="utf-8") as f:
        json.dump(trial_output, f, ensure_ascii=False, indent=2, default=str)

    print(f"  -> {outcome} | chain={tool_names} | success={tool_successes} | "
          f"steps={len(step_types)} | {elapsed:.1f}s", flush=True)

    return {
        "task_id": task_id,
        "trial": trial_n,
        "outcome": outcome,
        "tool_chain": tool_names,
        "tool_successes": tool_successes,
        "step_count": len(step_types),
        "wall_sec": round(elapsed, 1),
        "response_preview": response_text[:200],
    }


async def main():
    tasks = _load_benchmark()
    results = []

    for task_id in TASK_IDS:
        for trial_n in range(1, NUM_TRIALS + 1):
            try:
                r = await run_one_trial(tasks[task_id], task_id, trial_n)
                results.append(r)
            except Exception as exc:
                print(f"  -> ERROR: {exc}", flush=True)
                results.append({
                    "task_id": task_id, "trial": trial_n,
                    "outcome": "ERROR", "error": str(exc),
                })

    print("\n=== ALL 15 TRIALS COMPLETE ===")
    print(json.dumps(results, ensure_ascii=False, indent=2))

    # Write summary
    summary_path = BASE_DIR / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSummary written to {summary_path}")


if __name__ == "__main__":
    asyncio.run(main())
