"""Phase 9.1.0 Step 3b — LLM Variance Analysis.

Analyzes 5-task × 3-trial governance_full runs to measure chain/outcome consistency
across DeepSeek deepseek-v4-pro at temperature=0.

Outputs per-task variance metrics and Phase 9.3 trial count recommendation.

Usage:
  python evaluation/scripts/analyze_llm_variance.py [--data-dir PATH]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_DATA_DIR = PROJECT_ROOT / "evaluation" / "results" / "_temp_phase9_1_0_step3b_variance"


def load_trials(data_dir, task_id):
    """Load all trial outputs for a task."""
    trials = []
    task_dir = data_dir / task_id
    if not task_dir.exists():
        return trials
    for trial_dir in sorted(task_dir.iterdir(), key=lambda x: x.name):
        if trial_dir.is_dir():
            output_file = trial_dir / "trial_output.json"
            if output_file.exists():
                with open(output_file) as f:
                    trials.append(json.load(f))
    return trials


def classify_outcome(trial):
    """Classify trial outcome into standardized label."""
    oc = trial.get("outcome", {})
    label = oc.get("outcome_label", "unknown")
    chain = oc.get("tool_chain", [])
    successes = oc.get("tool_successes", [])

    if label == "blocked":
        return "blocked"
    if not chain:
        return "blocked"
    if not successes:
        return "success"  # no tool errors
    if all(s is True for s in successes):
        return "success"
    if any(s is False for s in successes):
        return "fail"
    return "partial"


def chain_key(chain):
    """Normalize chain to a hashable key."""
    return tuple(chain) if chain else ()


def analyze_variance(data_dir=None):
    if data_dir is None:
        data_dir = DEFAULT_DATA_DIR

    if isinstance(data_dir, str):
        data_dir = Path(data_dir)

    TASK_IDS = ["e2e_ambiguous_001", "e2e_ambiguous_002", "e2e_ambiguous_003",
                "e2e_multistep_001", "e2e_constraint_001"]

    print("=" * 80)
    print("PHASE 9.1.0 STEP 3b — LLM VARIANCE QUANTIFICATION")
    print(f"Data: {data_dir}")
    print("=" * 80)

    # ── Load all data ───────────────────────────────────────────────────
    all_trials = {}
    for tid in TASK_IDS:
        trials = load_trials(data_dir, tid)
        all_trials[tid] = trials
        print(f"\n  {tid}: {len(trials)} trials loaded")

    # ── Section 1: Per-Task Variance ────────────────────────────────────
    print("\n" + "=" * 80)
    print("## Section 1: Per-Task Variance Metrics\n")

    print(f"{'Task':30s} {'Chain':20s} {'Outcome':12s} {'1st-Tool':10s} "
          f"{'Count':8s} {'Chain Lengths':20s} {'Notes'}")
    print("-" * 130)

    results = {}
    for tid in TASK_IDS:
        trials = all_trials[tid]
        if not trials:
            print(f"{tid:30s} NO DATA")
            results[tid] = {"error": "no data"}
            continue

        chains = [tuple(t.get("outcome", {}).get("tool_chain", [])) for t in trials]
        outcomes = [classify_outcome(t) for t in trials]
        first_tools = [c[0] if c else None for c in chains]
        chain_lengths = [len(c) for c in chains]

        # Consistency metrics
        chain_match = "3/3" if len(set(chains)) == 1 else \
                      "2/3" if len(set(chains)) == 2 else "1/3"
        outcome_match = "3/3" if len(set(outcomes)) == 1 else \
                        "2/3" if len(set(outcomes)) == 2 else "1/3"
        first_tool_match = "3/3" if len(set(first_tools)) == 1 else \
                           "2/3" if len(set(first_tools)) == 2 else "1/3"
        count_match = "3/3" if len(set(chain_lengths)) == 1 else \
                      "2/3" if len(set(chain_lengths)) == 2 else "1/3"

        unique_lengths = sorted(set(chain_lengths))
        length_range = f"{unique_lengths}" if len(unique_lengths) > 1 else str(unique_lengths[0])

        notes = ""
        if chain_match == "1/3":
            notes = "HIGH VARIANCE"
        elif chain_match == "2/3":
            notes = "MODERATE"
        elif outcomes.count("success") == 3:
            notes = "stable-success"
        elif outcomes.count("blocked") == 3:
            notes = "stable-blocked"
        else:
            notes = "stable"

        print(f"{tid:30s} {chain_match:20s} {outcome_match:12s} {first_tool_match:10s} "
              f"{count_match:8s} {length_range:20s} {notes}")

        # Show individual chains
        for i, (ch, oc, ln) in enumerate(zip(chains, outcomes, chain_lengths)):
            print(f"  Trial {i+1}: chain={list(ch)}, outcome={oc}, len={ln}")

        results[tid] = {
            "chains": [list(c) for c in chains],
            "outcomes": outcomes,
            "first_tools": first_tools,
            "chain_lengths": chain_lengths,
            "chain_match": chain_match,
            "outcome_match": outcome_match,
            "first_tool_match": first_tool_match,
            "count_match": count_match,
            "notes": notes,
        }

    # ── Section 2: Cross-Task Summary ───────────────────────────────────
    print("\n" + "=" * 80)
    print("## Section 2: Cross-Task Variance Summary\n")

    chain_consistency = {"3/3": 0, "2/3": 0, "1/3": 0}
    outcome_consistency = {"3/3": 0, "2/3": 0, "1/3": 0}
    first_tool_consistency = {"3/3": 0, "2/3": 0, "1/3": 0}

    for tid, r in results.items():
        if "error" in r:
            continue
        chain_consistency[r["chain_match"]] += 1
        outcome_consistency[r["outcome_match"]] += 1
        first_tool_consistency[r["first_tool_match"]] += 1

    print("Chain consistency distribution:")
    for level in ["3/3", "2/3", "1/3"]:
        print(f"  {level}: {chain_consistency[level]}/5 tasks")

    print("\nOutcome consistency distribution:")
    for level in ["3/3", "2/3", "1/3"]:
        print(f"  {level}: {outcome_consistency[level]}/5 tasks")

    print("\nFirst-tool consistency distribution:")
    for level in ["3/3", "2/3", "1/3"]:
        print(f"  {level}: {first_tool_consistency[level]}/5 tasks")

    # ── Section 3: Task Category Analysis ────────────────────────────────
    print("\n## Section 3: Variance by Task Category\n")

    categories = {
        "ambiguous_success": ["e2e_ambiguous_002"],
        "ambiguous_value_delta": ["e2e_ambiguous_001"],
        "ambiguous_fail": ["e2e_ambiguous_003"],
        "multistep": ["e2e_multistep_001"],
        "constraint_blocked": ["e2e_constraint_001"],
    }

    for cat, task_ids in categories.items():
        for tid in task_ids:
            if tid in results and "error" not in results[tid]:
                r = results[tid]
                print(f"  {cat:30s} ({tid}): chain={r['chain_match']}, "
                      f"outcome={r['outcome_match']}, first_tool={r['first_tool_match']}")

    # ── Section 4: Phase 9.3 Trial Count Recommendation ──────────────────
    print("\n" + "=" * 80)
    print("## Section 4: Phase 9.3 Trial Count Recommendation\n")

    chain_3of3 = chain_consistency["3/3"]
    outcome_3of3 = outcome_consistency["3/3"]
    first_tool_3of3 = first_tool_consistency["3/3"]

    print(f"Tasks with 3/3 chain consistency:     {chain_3of3}/5")
    print(f"Tasks with 3/3 outcome consistency:   {outcome_3of3}/5")
    print(f"Tasks with 3/3 first-tool consistency: {first_tool_3of3}/5")
    print()

    if chain_3of3 == 5 and outcome_3of3 == 5:
        print("=> HIGH STABILITY: 1 trial × 182 default stands.")
        print("   Total trials: 182 (Full) + 100 (Naive) + 182×5 ablation = ~1,272")
        recommendation = "1_trial_default"
    elif chain_3of3 >= 3 and outcome_3of3 >= 4:
        print("=> MILD VARIANCE: Hybrid approach.")
        print("   - 1 trial default for stable categories")
        print("   - 3 trials for known-unstable categories")
        print("   Estimated total: ~250-350 trials")
        recommendation = "hybrid"
    elif chain_3of3 >= 1:
        print("=> MODERATE VARIANCE: Full 3-trial approach.")
        print("   3 trials × 182 Full + 100 Naive + 182×5 ablation = 1,638 trials")
        print("   Workload: high but data credible.")
        recommendation = "full_3_trial"
    else:
        print("=> HIGH VARIANCE: Methodological reassessment needed.")
        print("   T=0 DeepSeek cannot produce reproducible ablation baselines.")
        print("   Options: (a) multi-trial with confidence intervals,")
        print("   (b) majority-vote outcome per task,")
        print("   (c) switch to different LLM backend for ablation.")
        recommendation = "reassess_methodology"

    print(f"\n  RECOMMENDATION: {recommendation}")

    # ── Section 5: Comparison with Step 1/2/3 ───────────────────────────
    print("\n" + "=" * 80)
    print("## Section 5: Cross-Step Variance Comparison\n")
    print("  Step 1 (Run 7, 5 trials mode_A): 5/5 chain consistent (100%)")
    print("  Step 2 (5 tasks, 1 trial each): single-point, no cross-trial comparison")
    print("  Step 3 pre vs post (2 trials, ~40 min apart): 5/10 chain match (50%)")
    print(f"  Step 3b (5 tasks, 3 trials, ~min apart): see above")
    print()

    if chain_3of3 >= 4:
        print("  INTERPRETATION: Step 3 pre/post variance likely due to time gap (~40 min).")
        print("  Short-interval runs are stable. Step 1's 5/5 was representative of")
        print("  Run 7 stability specifically (multi-turn grounded prompt), not universal.")
    elif chain_3of3 >= 2:
        print("  INTERPRETATION: Mixed. Some tasks stable, some not. Step 1's Run 7")
        print("  was a best-case scenario (multi-turn context anchors LLM decisions).")
        print("  Step 3 pre/post time gap exacerbated but was not sole cause.")
    else:
        print("  INTERPRETATION: DeepSeek T=0 best-effort determinism is weak.")
        print("  Even short-interval runs show high variance. Step 1's 5/5 was")
        print("  Run 7 specific (grounded multi-turn prompt). Cannot generalize.")

    return {
        "results": results,
        "chain_consistency": chain_consistency,
        "outcome_consistency": outcome_consistency,
        "first_tool_consistency": first_tool_consistency,
        "recommendation": recommendation,
    }


if __name__ == "__main__":
    analyze_variance()
