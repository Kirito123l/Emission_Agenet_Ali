"""Phase 9.1.0 Step 1 — Run 7 Variance Analysis Script.

Classifies failure modes across multi-trial Shanghai e2e runs.
Input:  _temp_phase9_1_0_variance/trial_{1..5}/shanghai_e2e_summary.json
Output: variance_summary.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE = PROJECT_ROOT / "evaluation" / "results" / "_temp_phase9_1_0_variance"

# ── Cross-trial invariant keys ──────────────────────────────────────────
INVARIANT_CHECKS = [
    "turn1_tool_executed",
    "turn1_ao_new",
    "turn1_collection_mode_false",
    "turn2_ao_new_ao",
    "turn2_collection_mode_true",
    "turn2_no_tools",
    "turn3_ao_new_ao",
    "turn3_collection_mode_true",
    "turn3_no_tools",
    "projected_chain_never_present",
]


def classify_trial(summary: Dict[str, Any]) -> str:
    """Classify a single trial into mode_A/B/C/D.

    mode_A (original_run7_like): Turn 1 macro_emission success, Turn 2/3 no tools
    mode_B (pcm_blocked_throughout): All 3 turns PCM-blocked, zero tools
    mode_C (full_chain_success): Turn 1+2+3 all execute tools
    mode_D (other): Any other pattern
    """
    tc = summary.get("tool_chain", [])
    trs = summary.get("turn_results", [])

    turn_tools = []
    for tr in trs:
        tcs = tr.get("tool_calls", [])
        names = [t.get("name", "?") for t in tcs] if tcs else []
        turn_tools.append(names)

    t1_tools = turn_tools[0] if len(turn_tools) > 0 else []
    t2_tools = turn_tools[1] if len(turn_tools) > 1 else []
    t3_tools = turn_tools[2] if len(turn_tools) > 2 else []

    if t1_tools and not t2_tools and not t3_tools:
        return "mode_A"
    if not t1_tools and not t2_tools and not t3_tools:
        return "mode_B"
    if t1_tools and t2_tools and t3_tools:
        return "mode_C"
    return "mode_D"


def extract_turn_key_fields(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract key fields per turn from a trial summary."""
    rows = []
    for tr in summary.get("turn_results", []):
        t = tr.get("trace", {})
        oasc = t.get("oasc", {})
        cls = oasc.get("classifier", {})
        lifecycle = t.get("ao_lifecycle_events", [])
        collection_mode = None
        pending_queue = None
        for evt in lifecycle:
            if isinstance(evt, dict):
                ccr = evt.get("complete_check_results", {})
                if ccr:
                    collection_mode = ccr.get("collection_mode_active")
                    ec = ccr.get("execution_continuation", "")
                    # parse pending_tool_queue from string repr
                    if isinstance(ec, str) and "pending_tool_queue" in ec:
                        try:
                            import ast
                            parsed = ast.literal_eval(ec)
                            pending_queue = parsed.get("pending_tool_queue", [])
                        except Exception:
                            pending_queue = None
                    break

        steps = t.get("steps", [])
        step_types = [s.get("step_type", "?") for s in steps if isinstance(s, dict)]

        tcs = tr.get("tool_calls", [])
        tc_info = [
            {"name": tc.get("name", "?"), "success": tc.get("result", {}).get("success") if isinstance(tc.get("result"), dict) else None}
            for tc in tcs
        ] if tcs else []

        projected_chain_present = "projected_chain" in t

        rows.append({
            "turn": tr["turn"],
            "ao_classification": cls.get("classification"),
            "current_ao_id": oasc.get("current_ao_id"),
            "collection_mode_active": collection_mode,
            "pending_tool_queue": pending_queue,
            "projected_chain_present": projected_chain_present,
            "tool_calls": tc_info,
            "tool_count": len(tc_info),
            "step_types": step_types,
            "response_prefix": tr.get("response_text", "")[:150],
            "wall_clock_sec": tr.get("wall_clock_sec"),
        })
    return rows


def check_invariants(all_extracts: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Check cross-trial invariants."""
    n = len(all_extracts)
    results = {}
    for inv in INVARIANT_CHECKS:
        results[inv] = [None] * n

    for trial_idx, turns in enumerate(all_extracts):
        if len(turns) < 3:
            continue
        t1, t2, t3 = turns[0], turns[1], turns[2]
        i = trial_idx

        results["turn1_tool_executed"][i] = t1["tool_count"] > 0
        results["turn1_ao_new"][i] = t1["ao_classification"] == "new_ao"
        results["turn1_collection_mode_false"][i] = t1["collection_mode_active"] is False

        results["turn2_ao_new_ao"][i] = t2["ao_classification"] == "new_ao"
        results["turn2_collection_mode_true"][i] = t2["collection_mode_active"] is True
        results["turn2_no_tools"][i] = t2["tool_count"] == 0

        results["turn3_ao_new_ao"][i] = t3["ao_classification"] == "new_ao"
        results["turn3_collection_mode_true"][i] = t3["collection_mode_active"] is True
        results["turn3_no_tools"][i] = t3["tool_count"] == 0

        results["projected_chain_never_present"][i] = (
            not t1["projected_chain_present"]
            and not t2["projected_chain_present"]
            and not t3["projected_chain_present"]
        )

    # Summarize
    invariant_summary = {}
    for inv, values in results.items():
        true_count = sum(1 for v in values if v is True)
        false_count = sum(1 for v in values if v is False)
        none_count = sum(1 for v in values if v is None)
        invariant_summary[inv] = {
            "true_count": true_count,
            "false_count": false_count,
            "none_count": none_count,
            "holds_5of5": true_count == n,
            "by_trial": values,
        }
    return invariant_summary


def evaluate_hypothesis(modes: List[str]) -> Dict[str, Any]:
    """Evaluate H1/H2/H3 based on failure mode distribution."""
    from collections import Counter
    counts = Counter(modes)
    n = len(modes)

    mode_a_count = counts.get("mode_A", 0)
    mode_b_count = counts.get("mode_B", 0)
    mode_c_count = counts.get("mode_C", 0)
    mode_d_count = counts.get("mode_D", 0)
    unique_modes = len([c for c in [mode_a_count, mode_b_count, mode_c_count, mode_d_count] if c > 0])

    if mode_b_count >= 4:
        h = "H1"
        strength = "strong" if mode_b_count == 5 else "moderate"
    elif unique_modes >= 2:
        h = "H2"
        strength = "strong" if unique_modes >= 3 else "moderate" if unique_modes == 2 else "weak"
    elif mode_a_count >= 4:
        h = "H3"
        strength = "strong" if mode_a_count == 5 else "moderate"
    else:
        h = "indeterminate"
        strength = "N/A"

    return {
        "supported_hypothesis": h,
        "strength": strength,
        "mode_counts": {
            "mode_A (original_run7_like)": mode_a_count,
            "mode_B (pcm_blocked_throughout)": mode_b_count,
            "mode_C (full_chain_success)": mode_c_count,
            "mode_D (other)": mode_d_count,
        },
        "unique_modes_observed": unique_modes,
        "rationale": (
            f"H1 requires mode_B ≥ 4/5 (mode_B={mode_b_count}/5)"
            f"; H2 requires ≥ 2 modes ({unique_modes} observed)"
            f"; H3 requires mode_A ≥ 4/5 (mode_A={mode_a_count}/5)"
        ),
    }


def main():
    base_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_BASE

    all_summaries = []
    all_extracts = []
    all_modes = []

    for trial_id in range(1, 6):
        summary_path = base_dir / f"trial_{trial_id}" / "shanghai_e2e_summary.json"
        if not summary_path.exists():
            print(f"WARNING: Trial {trial_id} summary missing at {summary_path}", file=sys.stderr)
            continue
        with open(summary_path) as f:
            data = json.load(f)
        all_summaries.append(data)
        mode = classify_trial(data)
        all_modes.append(mode)
        extracts = extract_turn_key_fields(data)
        all_extracts.append(extracts)

    invariants = check_invariants(all_extracts)
    hypothesis = evaluate_hypothesis(all_modes)

    # Build cross-trial comparison table
    comparison_rows = []
    for trial_idx, extracts in enumerate(all_extracts):
        trial_id = trial_idx + 1
        for turn_data in extracts:
            comparison_rows.append({
                "Trial": trial_id,
                "Turn": turn_data["turn"],
                "AO_Class": turn_data["ao_classification"],
                "AO_ID": turn_data["current_ao_id"],
                "PCM_Active": turn_data["collection_mode_active"],
                "Pending_Queue": turn_data["pending_tool_queue"],
                "Tools": [tc["name"] for tc in turn_data["tool_calls"]],
                "Tool_Success": [tc["success"] for tc in turn_data["tool_calls"]],
                "Step_Types": turn_data["step_types"],
                "Resp_Prefix": turn_data["response_prefix"],
                "Wall_Clock": turn_data["wall_clock_sec"],
            })

    # Per-trial triage
    trial_modes = []
    for trial_idx, (summary, extracts) in enumerate(zip(all_summaries, all_extracts)):
        t1_tools = [tc["name"] for tc in extracts[0]["tool_calls"]] if len(extracts) > 0 else []
        t2_tools = [tc["name"] for tc in extracts[1]["tool_calls"]] if len(extracts) > 1 else []
        t3_tools = [tc["name"] for tc in extracts[2]["tool_calls"]] if len(extracts) > 2 else []
        trial_modes.append({
            "trial_id": trial_idx + 1,
            "session_id": summary.get("session_id", "?"),
            "mode": all_modes[trial_idx] if trial_idx < len(all_modes) else "?",
            "tool_chain": summary.get("tool_chain", []),
            "governance_steps": summary.get("governance_step_counts", {}),
            "trace_keys_absent": summary.get("trace_key_absent_all_turns", []),
            "turn1_tools": t1_tools,
            "turn2_tools": t2_tools,
            "turn3_tools": t3_tools,
        })

    output = {
        "analysis_timestamp_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "num_trials": len(all_summaries),
        "per_trial_triage": trial_modes,
        "cross_trial_comparison_table": comparison_rows,
        "invariant_checks": invariants,
        "hypothesis_evaluation": hypothesis,
        "step2_sample_size_recommendation": {
            "if_H1": "5 task × 1 trial (systematic offset confirmed, each trial reliable)",
            "if_H2": "5 task × ≥3 trial (high variance, need task-level variance quantification)",
            "if_H3": "5 task × 1 trial (original behavior stable, single trial representative)",
            "actual_recommendation": (
                "5 task × 1 trial"
                if hypothesis["supported_hypothesis"] in ("H1", "H3")
                else "5 task × 3 trial"
            ),
        },
    }

    output_path = base_dir / "variance_summary.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({
        "num_trials": len(all_summaries),
        "modes": dict(__import__("collections").Counter(all_modes)),
        "hypothesis": hypothesis["supported_hypothesis"],
        "strength": hypothesis["strength"],
        "step2_recommendation": output["step2_sample_size_recommendation"]["actual_recommendation"],
        "output_path": str(output_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
