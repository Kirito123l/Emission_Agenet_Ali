"""Phase 9.1.0 Step 2 — Reproducibility Analysis Script.

Compares Step 2 re-run outcomes against Phase 8.2.2.C-2 original data.
Input: _temp_phase9_1_0_step2/ trial outputs + Phase 8.2.2.C-2 original logs
Output: Structured comparison JSON + diagnostic summary.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STEP2_DIR = PROJECT_ROOT / "evaluation" / "results" / "_temp_phase9_1_0_step2"

# Original Phase 8.2.2.C-2 data paths
ORIG_FULL_PATH = PROJECT_ROOT / "evaluation" / "results" / "end2end_full_v8_fix_E" / "end2end_logs.jsonl"
ORIG_NAIVE_PATH = PROJECT_ROOT / "evaluation" / "results" / "end2end_naive_full" / "end2end_logs.jsonl"


def load_original_data() -> Tuple[Dict[str, Dict], Dict[str, Dict]]:
    """Load original Full v8 and Naive outcomes per task."""
    full = {}
    if ORIG_FULL_PATH.exists():
        with open(ORIG_FULL_PATH) as f:
            for line in f:
                d = json.loads(line)
                actual = d.get("actual", {})
                full[d["task_id"]] = {
                    "success": d["success"],
                    "tool_chain": actual.get("tool_chain", []),
                    "tool_chain_match": actual.get("tool_chain_match"),
                    "failure_type": d.get("failure_type"),
                    "category": d["category"],
                    "expected_chain": d.get("expected", {}).get("tool_chain", []),
                    "final_stage": actual.get("final_stage"),
                    "trace_step_types": actual.get("trace_step_types", []),
                }
    naive = {}
    if ORIG_NAIVE_PATH.exists():
        with open(ORIG_NAIVE_PATH) as f:
            for line in f:
                d = json.loads(line)
                actual = d.get("actual", {})
                naive[d["task_id"]] = {
                    "success": d["success"],
                    "tool_chain": actual.get("tool_chain", []),
                    "tool_chain_match": actual.get("tool_chain_match"),
                    "failure_type": d.get("failure_type"),
                    "category": d["category"],
                    "expected_chain": d.get("expected", {}).get("tool_chain", []),
                    "final_stage": actual.get("final_stage"),
                    "trace_step_types": actual.get("trace_step_types", []),
                }
    return full, naive


def load_step2_data(base_dir: Path) -> Dict[str, Dict[str, Dict[str, Dict]]]:
    """Load all Step 2 trial outputs. Returns {task_id: {mode: {trial_N: data}}}."""
    data: Dict[str, Dict[str, Dict[str, Dict]]] = {}
    if not base_dir.exists():
        return data
    for task_dir in base_dir.iterdir():
        if not task_dir.is_dir():
            continue
        tid = task_dir.name
        data[tid] = {}
        for mode_dir in task_dir.iterdir():
            if not mode_dir.is_dir():
                continue
            mode = mode_dir.name
            data[tid][mode] = {}
            for trial_dir in mode_dir.iterdir():
                if not trial_dir.is_dir():
                    continue
                trial_name = trial_dir.name
                output_path = trial_dir / "trial_output.json"
                if output_path.exists():
                    with open(output_path) as f:
                        data[tid][mode][trial_name] = json.load(f)
    return data


def compare_outcome(orig: Dict[str, Any], rerun: Dict[str, Any]) -> Dict[str, Any]:
    """Compare a single task/mode outcome against original."""
    if not rerun:
        return {"match": False, "error": "no_rerun_data"}

    outcome = rerun.get("outcome", {})
    rerun_chain = outcome.get("tool_chain", [])
    rerun_successes = outcome.get("tool_successes", [])
    rerun_tool_count = outcome.get("tool_count", 0)

    orig_chain = orig.get("tool_chain", [])
    orig_success = orig.get("success", False)
    orig_match = orig.get("tool_chain_match")

    # Determine rerun "success" — did it execute the expected chain?
    step2_meta = rerun.get("trial_metadata", {})
    tid = step2_meta.get("task_id", "?")

    # Simple tool chain comparison
    chain_match = rerun_chain == orig_chain
    all_tools_succeeded = all(s is True for s in rerun_successes) if rerun_successes else (rerun_tool_count == 0 and orig_success is False)

    # Define rerun success: tool chain matches AND all tools succeeded
    # (for tasks that correctly block, success means empty chain)
    rerun_success = chain_match and all_tools_succeeded

    return {
        "task_id": tid,
        "orig_tool_chain": orig_chain,
        "rerun_tool_chain": rerun_chain,
        "orig_success": orig_success,
        "orig_chain_match": orig_match,
        "orig_failure_type": orig.get("failure_type"),
        "orig_final_stage": orig.get("final_stage"),
        "rerun_chain_match": chain_match,
        "rerun_all_tools_succeeded": all_tools_succeeded,
        "outcome_reproduced": rerun_success == orig_success,
        "chain_reproduced": chain_match,
        "match": chain_match and rerun_success == orig_success,
    }


def analyze_path_divergence(step2_data: Dict[str, Dict[str, Dict[str, Dict]]]) -> Dict[str, Any]:
    """Analyze trace step type distribution across trials for path divergence."""
    all_step_sequences: Dict[str, List[str]] = {}

    for tid, modes in step2_data.items():
        for mode, trials in modes.items():
            for trial_name, trial in trials.items():
                key = f"{tid}/{mode}/{trial_name}"
                steps = trial.get("trace_step_types", {})
                sequence = steps.get("sequence", [])
                all_step_sequences[key] = sequence

    # Group by task+mode to check consistency
    task_mode_steps: Dict[str, Dict[str, List[List[str]]]] = {}
    for key, seq in all_step_sequences.items():
        parts = key.split("/")
        tm_key = f"{parts[0]}/{parts[1]}"
        if tm_key not in task_mode_steps:
            task_mode_steps[tm_key] = {}
        trial_id = parts[2]
        task_mode_steps[tm_key][trial_id] = seq

    # Check if all trials for same task+mode have same step types
    divergence: Dict[str, Any] = {}
    for tm_key, trials in task_mode_steps.items():
        sequences = list(trials.values())
        if len(sequences) <= 1:
            divergence[tm_key] = {"consistent": True, "reason": "single_trial"}
            continue

        first_seq = tuple(sequences[0])
        all_same = all(tuple(s) == first_seq for s in sequences[1:])
        if all_same:
            divergence[tm_key] = {"consistent": True, "step_count": len(sequences[0]), "step_types": list(first_seq)}
        else:
            divergence[tm_key] = {
                "consistent": False,
                "sequences": {t: list(s) for t, s in trials.items()},
            }

    return divergence


def analyze_cache_telemetry(step2_data: Dict[str, Dict[str, Dict[str, Dict]]]) -> Dict[str, Any]:
    """Aggregate cache telemetry across all trials."""
    all_hits: List[int] = []
    all_misses: List[int] = []
    trials_with_cache_hits = 0
    total_trials = 0
    per_trial: Dict[str, Dict[str, int]] = {}

    for tid, modes in step2_data.items():
        for mode, trials in modes.items():
            for trial_name, trial in trials.items():
                total_trials += 1
                hit = trial.get("llm_cache_hit_tokens_total", 0)
                miss = trial.get("llm_cache_miss_tokens_total", 0)
                all_hits.append(hit)
                all_misses.append(miss)
                if hit > 0:
                    trials_with_cache_hits += 1
                key = f"{tid}/{mode}/{trial_name}"
                per_trial[key] = {"hit_tokens": hit, "miss_tokens": miss, "llm_calls": trial.get("llm_call_count", 0)}

    return {
        "total_trials": total_trials,
        "trials_with_cache_hits": trials_with_cache_hits,
        "total_hit_tokens": sum(all_hits),
        "total_miss_tokens": sum(all_misses),
        "avg_hit_tokens_per_trial": sum(all_hits) / max(total_trials, 1),
        "per_trial": per_trial,
    }


def compute_delta(
    step2_data: Dict[str, Dict[str, Dict[str, Dict]]],
    orig_full: Dict[str, Dict],
    orig_naive: Dict[str, Dict],
) -> Dict[str, Any]:
    """Compute Full - Naive delta for the 5-task subset, comparing original vs rerun."""
    # Find tasks with both Full and Naive data
    tasks_with_both = []
    for tid in step2_data:
        if "governance_full" in step2_data[tid] and "naive" in step2_data[tid]:
            tasks_with_both.append(tid)

    orig_delta = 0.0
    rerun_delta = 0.0
    task_deltas = []

    for tid in tasks_with_both:
        # Get first trial from each mode
        full_trials = step2_data[tid].get("governance_full", {})
        naive_trials = step2_data[tid].get("naive", {})

        if not full_trials or not naive_trials:
            continue

        full_trial = list(full_trials.values())[0]
        naive_trial = list(naive_trials.values())[0]

        full_chain = full_trial.get("outcome", {}).get("tool_chain", [])
        naive_chain = naive_trial.get("outcome", {}).get("tool_chain", [])

        # Original
        orig_f = orig_full.get(tid, {})
        orig_n = orig_naive.get(tid, {})

        task_deltas.append({
            "task_id": tid,
            "orig_full_chain": orig_f.get("tool_chain", []),
            "orig_naive_chain": orig_n.get("tool_chain", []),
            "rerun_full_chain": full_chain,
            "rerun_naive_chain": naive_chain,
        })

    return {
        "tasks_with_both_modes": len(tasks_with_both),
        "task_deltas": task_deltas,
    }


def main():
    base_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_STEP2_DIR

    # Load original data
    orig_full, orig_naive = load_original_data()
    print(f"Original Full v8 tasks: {len(orig_full)}")
    print(f"Original Naive tasks: {len(orig_naive)}")

    # Load Step 2 data
    step2 = load_step2_data(base_dir)
    print(f"Step 2 tasks: {len(step2)}")
    for tid, modes in step2.items():
        for mode, trials in modes.items():
            print(f"  {tid}/{mode}: {len(trials)} trials")

    # Per-task comparison
    comparisons = []
    for tid in sorted(step2.keys()):
        for mode in sorted(step2[tid].keys()):
            for trial_name in sorted(step2[tid][mode].keys()):
                trial = step2[tid][mode][trial_name]
                orig = (orig_full if mode == "governance_full" else orig_naive).get(tid, {})
                comp = compare_outcome(orig, trial)
                comp["mode"] = mode
                comp["trial"] = trial_name
                comparisons.append(comp)

    # Summarize
    reproduced = sum(1 for c in comparisons if c["outcome_reproduced"])
    chain_reproduced = sum(1 for c in comparisons if c["chain_reproduced"])
    total = len(comparisons)

    # Path divergence
    path_div = analyze_path_divergence(step2)

    # Cache telemetry
    cache = analyze_cache_telemetry(step2)

    # Delta computation
    delta = compute_delta(step2, orig_full, orig_naive)

    # State isolation check
    isolation_issues = []
    for tid, modes in step2.items():
        for mode, trials in modes.items():
            for trial_name, trial in trials.items():
                cleanup = trial.get("state_cleanup", {})
                if cleanup.get("files_present"):
                    isolation_issues.append({
                        "task_id": tid,
                        "mode": mode,
                        "trial": trial_name,
                        "pre_existing_files": cleanup["files_present"],
                    })

    output = {
        "analysis_timestamp_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "summary": {
            "total_comparisons": total,
            "outcome_reproduced": reproduced,
            "outcome_reproduced_rate": reproduced / max(total, 1),
            "chain_reproduced": chain_reproduced,
            "chain_reproduced_rate": chain_reproduced / max(total, 1),
            "isolation_issues": len(isolation_issues),
        },
        "reproducibility_verdict": (
            "full_reproduction"
            if reproduced == total
            else "partial_reproduction"
            if reproduced >= total * 0.6
            else "poor_reproduction"
        ),
        "per_task_comparisons": comparisons,
        "path_divergence_analysis": path_div,
        "cache_telemetry": cache,
        "delta_analysis": delta,
        "isolation_issues": isolation_issues,
    }

    output_path = base_dir / "step2_analysis.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))
    print(f"\nVerdict: {output['reproducibility_verdict']}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
