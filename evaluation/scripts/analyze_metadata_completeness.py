"""Phase 9.1.0 Step 3a — Metadata Completeness Analysis for Phase 9.3 Ablation.

Analyzes whether shortcut-path governance_full traces contain sufficient metadata
(without step-level tool_execution visibility) to satisfy Phase 9.3 ablation evidence needs.

The key question: can Phase 9.3 ablation runs prove their claims using only the metadata
keys present in shortcut-path traces, or do they require step-level visibility?

Usage:
  python evaluation/scripts/analyze_metadata_completeness.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

POST_FIX_DIR = PROJECT_ROOT / "evaluation" / "results" / "_temp_phase9_1_0_step3_post_fix"

SHORTCUT_TASKS = ["e2e_ambiguous_002", "e2e_ambiguous_003", "e2e_multistep_001"]
RICH_TASK = "e2e_constraint_001"


def load_trial(task_id):
    path = POST_FIX_DIR / task_id / "governance_full" / "trial_1" / "trial_output.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def has_step_type(trace, step_type):
    """Check if trace.steps list contains a step with given step_type."""
    steps = trace.get("steps", [])
    for s in steps:
        if isinstance(s, dict) and s.get("step_type") == step_type:
            return True
    return False


def step_type_contains_any(trace, substrs):
    """Check if any step_type in trace contains any of the given substrings."""
    steps = trace.get("steps", [])
    for s in steps:
        if isinstance(s, dict):
            st = s.get("step_type", "")
            for sub in substrs:
                if sub in st:
                    return True
    return False


def analyze():
    # Load trials
    shortcut_traces = {}
    for tid in SHORTCUT_TASKS:
        data = load_trial(tid)
        if data:
            shortcut_traces[tid] = data["trace"]

    rich_data = load_trial(RICH_TASK)
    rich_trace = rich_data["trace"] if rich_data else {}

    print("=" * 80)
    print("PHASE 9.1.0 STEP 3a — METADATA COMPLETENESS FOR PHASE 9.3 ABLATION")
    print("=" * 80)

    # ── Section 1: Per-field comparison shortcut vs rich ──────────────────
    print("\n## Section 1: Shortcut vs Rich — Per-Field Comparison\n")

    # Column headers
    print(f"{'Field':40s} {'Shortcut (3/3)':20s} {'Rich':10s} {'Note'}")
    print("-" * 100)

    fields = [
        ("oasc.classifier", "AO classification result"),
        ("oasc.ao_block", "AO block (token estimation)"),
        ("classifier_telemetry", "Classifier rule/LLM layer result"),
        ("ao_lifecycle_events", "AO create/activate/complete events"),
        ("block_telemetry", "Constraint/dependency check records"),
        ("reconciled_decision", "Reconciler decision output"),
        ("clarification_contract", "Clarification contract state"),
        ("clarification_telemetry", "Clarification stage1/2/3 details"),
        ("steps (any)", "Step entries present"),
        ("steps.reply_generation", "reply_generation step"),
        ("steps.tool_selection", "tool_selection step"),
        ("steps.tool_execution", "tool_execution step (B.2/C.5 gap)"),
        ("steps.state_transition", "state_transition step"),
        ("steps.cross_constraint_violation", "constraint violation step"),
    ]

    for field, note in fields:
        if field == "steps (any)":
            sc_ok = all(len(shortcut_traces[tid].get("steps", [])) > 0 for tid in SHORTCUT_TASKS)
            ri_ok = len(rich_trace.get("steps", [])) > 0
        elif field.startswith("steps."):
            stype = field.split(".", 1)[1]
            sc_ok = all(has_step_type(shortcut_traces[tid], stype) for tid in SHORTCUT_TASKS)
            ri_ok = has_step_type(rich_trace, stype)
        elif field.startswith("oasc."):
            sub = field.split(".", 1)[1]
            sc_ok = all(
                isinstance(shortcut_traces[tid].get("oasc", {}).get(sub), dict)
                for tid in SHORTCUT_TASKS
            )
            ri_ok = isinstance(rich_trace.get("oasc", {}).get(sub), dict)
        else:
            sc_ok = all(
                shortcut_traces[tid].get(field) is not None and
                (not isinstance(shortcut_traces[tid].get(field), list) or
                 len(shortcut_traces[tid].get(field, [])) > 0)
                for tid in SHORTCUT_TASKS
            )
            ri_val = rich_trace.get(field)
            ri_ok = ri_val is not None and (not isinstance(ri_val, list) or len(ri_val) > 0)

        sc_str = "OK (3/3)" if sc_ok else "GAP"
        ri_str = "OK" if ri_ok else "GAP"
        flag = " ***" if not sc_ok else ""
        print(f"{field:40s} {sc_str:20s} {ri_str:10s} {note}{flag}")

    # ── Section 2: Deep content check of shortcut metadata ────────────────
    print("\n## Section 2: Shortcut-Path Metadata Content Audit\n")

    for tid in SHORTCUT_TASKS:
        trace = shortcut_traces[tid]
        print(f"\n--- {tid} ---")

        # oasc
        oasc = trace.get("oasc", {})
        cls = oasc.get("classifier", {})
        print(f"  oasc.classifier: {json.dumps(cls, ensure_ascii=False)}")
        print(f"  oasc.current_ao_id: {oasc.get('current_ao_id')}")
        print(f"  oasc.ao_block: {'present' if oasc.get('ao_block') else 'None (no token estimation on shortcut)'}")

        # classifier_telemetry
        ct = trace.get("classifier_telemetry", [])
        if ct:
            c0 = ct[0]
            print(f"  classifier_telemetry[0]: layer={c0.get('layer_hit')}, "
                  f"classification={c0.get('classification')}, "
                  f"confidence={c0.get('confidence')}, "
                  f"layer2_latency_ms={c0.get('layer2_latency_ms')}")

        # ao_lifecycle_events
        ale = trace.get("ao_lifecycle_events", [])
        for e in ale:
            cc = e.get("complete_check_results")
            print(f"  ao_event: type={e.get('event_type')}, ao_id={e.get('ao_id')}, "
                  f"tool_intent={e.get('tool_intent_confidence')}, "
                  f"collection_mode={e.get('parameter_state_collection_mode')}, "
                  f"complete_check={'present' if cc else 'none'}")

        # block_telemetry — critical for Run 4 and Run 5
        bt = trace.get("block_telemetry", [])
        print(f"  block_telemetry: {len(bt)} entries {'(EMPTY — no dependency/constraint check recorded)' if not bt else ''}")

        # reconciled_decision
        rd = trace.get("reconciled_decision")
        if rd:
            print(f"  reconciled_decision: value={rd.get('decision_value')}, "
                  f"rule={rd.get('applied_rule_id')}, "
                  f"missing_required={rd.get('reconciled_missing_required')}")

        # clarification_telemetry
        clt = trace.get("clarification_telemetry", [])
        if clt:
            c0 = clt[0]
            print(f"  clarification: proceed_mode={c0.get('proceed_mode')}, "
                  f"collection_mode={c0.get('collection_mode')}, "
                  f"stage2_called={c0.get('stage2_called')}, "
                  f"stage2_latency_ms={c0.get('stage2_latency_ms')}")
            chain = (c0.get("llm_intent_raw") or {}).get("chain")
            print(f"  llm_intent.chain: {chain}")
            pcm = c0.get("pcm_advisory")
            if pcm:
                print(f"  pcm_advisory: unfilled_optionals={pcm.get('unfilled_optionals_without_default')}, "
                      f"collection_mode_active={pcm.get('collection_mode_active')}")

    # ── Section 3: Ablation Evidence Mapping ──────────────────────────────
    print("\n" + "=" * 80)
    print("## Section 3: Phase 9.3 Ablation Evidence Mapping\n")

    ABLATIONS = [
        {
            "id": "Run_1_vs_Run_2",
            "label": "Full vs Naive — overall governance value",
            "needs": "Outcome (chain + success/fail)",
            "checks": [
                ("ao_lifecycle_events.complete_check_results",
                 lambda t: any(e.get("complete_check_results") for e in t.get("ao_lifecycle_events", [])
                              if e.get("event_type") in ("complete", "complete_blocked"))),
                ("steps present", lambda t: len(t.get("steps", [])) > 0),
            ],
            "verdict_hint": "metadata sufficient — outcome from ao_lifecycle_events",
        },
        {
            "id": "Run_1_vs_Run_3",
            "label": "Full vs no_ao — AO classifier contribution",
            "needs": "AO classification (type/layer/confidence) + AO lifecycle",
            "checks": [
                ("classifier_telemetry non-empty",
                 lambda t: len(t.get("classifier_telemetry", [])) > 0),
                ("oasc.classifier present",
                 lambda t: isinstance(t.get("oasc", {}).get("classifier"), dict)),
                ("ao_lifecycle_events non-empty",
                 lambda t: len(t.get("ao_lifecycle_events", [])) > 0),
            ],
            "verdict_hint": "metadata sufficient — all classifier data present on shortcut",
        },
        {
            "id": "Run_1_vs_Run_4",
            "label": "Full vs no_graph — tool dependency graph contribution",
            "needs": "Dependency check trigger + prerequisite-missing detection + tool_selection evidence",
            "checks": [
                ("block_telemetry non-empty",
                 lambda t: len(t.get("block_telemetry", [])) > 0),
                ("steps.tool_selection present",
                 lambda t: has_step_type(t, "tool_selection")),
                ("reconciled_decision present",
                 lambda t: isinstance(t.get("reconciled_decision"), dict)),
            ],
            "verdict_hint": "block_telemetry EMPTY on shortcut — dependency checks not recorded",
        },
        {
            "id": "Run_1_vs_Run_5",
            "label": "Full vs no_constraint — cross-parameter constraint contribution",
            "needs": "Constraint check trigger + violation detection + block evidence",
            "checks": [
                ("block_telemetry non-empty",
                 lambda t: len(t.get("block_telemetry", [])) > 0),
                ("steps.cross_constraint_violation present",
                 lambda t: has_step_type(t, "cross_constraint_violation")),
                ("clarification_telemetry.stage3_normalizations present",
                 lambda t: any(
                     e.get("stage3_normalizations")
                     for e in t.get("clarification_telemetry", [])
                 )),
            ],
            "verdict_hint": "block_telemetry EMPTY on shortcut — but normalizations in clarification_telemetry",
        },
        {
            "id": "Run_6",
            "label": "Held-out — generalization",
            "needs": "Same as Run 1 evidence",
            "checks": [
                ("outcome evidence (same as Run 1)",
                 lambda t: any(e.get("complete_check_results") for e in t.get("ao_lifecycle_events", [])
                              if e.get("event_type") in ("complete", "complete_blocked"))),
            ],
            "verdict_hint": "inherits Run 1 verdict — metadata sufficient for outcome evidence",
        },
        {
            "id": "Run_7",
            "label": "Shanghai e2e — multi-turn AO transition + chain projection",
            "needs": "AO lifecycle across turns + chain projection + collection_mode transitions",
            "checks": [
                ("ao_lifecycle_events non-empty",
                 lambda t: len(t.get("ao_lifecycle_events", [])) > 0),
                ("oasc.classifier present",
                 lambda t: isinstance(t.get("oasc", {}).get("classifier"), dict)),
                ("llm_intent_raw.chain present in clarification",
                 lambda t: any(
                     (e.get("llm_intent_raw") or {}).get("chain")
                     for e in t.get("clarification_telemetry", [])
                 )),
            ],
            "verdict_hint": "metadata sufficient — chain projection in clarification_telemetry.llm_intent_raw",
        },
    ]

    results = {}
    for abl in ABLATIONS:
        print(f"\n### {abl['id']}: {abl['label']}")
        print(f"  Evidence needed: {abl['needs']}")

        all_sc_pass = all(
            check(shortcut_traces[tid])
            for check_name, check in abl["checks"]
            for tid in SHORTCUT_TASKS
        )
        all_ri_pass = all(
            check(rich_trace)
            for check_name, check in abl["checks"]
        )

        for check_name, check in abl["checks"]:
            sc_pass = all(check(shortcut_traces[tid]) for tid in SHORTCUT_TASKS)
            ri_pass = check(rich_trace)
            sc_flag = "PASS" if sc_pass else "FAIL"
            ri_flag = "PASS" if ri_pass else "FAIL"
            print(f"  {check_name:55s} shortcut={sc_flag:5s}  rich={ri_flag:5s}")

        # Determine verdict
        shortcut_pass = all(
            all(check(shortcut_traces[tid]) for check_name, check in abl["checks"])
            for tid in SHORTCUT_TASKS
        )

        if shortcut_pass:
            verdict = "SUFFICIENT"
        else:
            # Check if it's a partial (some checks pass) or complete failure
            n_checks = len(abl["checks"])
            n_pass = sum(
                1 for check_name, check in abl["checks"]
                if all(check(shortcut_traces[tid]) for tid in SHORTCUT_TASKS)
            )
            if n_pass > 0:
                verdict = f"PARTIAL ({n_pass}/{n_checks} checks pass)"
            else:
                verdict = f"INSUFFICIENT (0/{n_checks} checks pass)"

        print(f"  VERDICT: {verdict}")
        print(f"  Hint: {abl['verdict_hint']}")
        results[abl["id"]] = verdict

    # ── Section 4: Resolution ─────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("## Section 4: Option C Resolution\n")

    sufficient = {k: v for k, v in results.items() if v.startswith("SUFFICIENT")}
    partial = {k: v for k, v in results.items() if v.startswith("PARTIAL")}
    insufficient = {k: v for k, v in results.items() if v.startswith("INSUFFICIENT")}

    print(f"SUFFICIENT:   {len(sufficient)}/{len(results)} — {list(sufficient.keys())}")
    print(f"PARTIAL:      {len(partial)}/{len(results)} — {list(partial.keys())}")
    print(f"INSUFFICIENT: {len(insufficient)}/{len(results)} — {list(insufficient.keys())}")
    print()

    # Determine Option C
    if not insufficient and not partial:
        print("=> OPTION C1: Metadata sufficient. NO 1b needed.")
        print("   Tag v1.5-trace-fix-verified with criterion restatement.")
    elif not insufficient:
        print(f"=> OPTION C2: Narrow 1b — targeted fix for: {list(partial.keys())}")
        print("   Add minimal step recording to shortcut paths for gap areas.")
    else:
        print("=> OPTION C3: Metadata gap on shortcut paths.")
        print("   See detailed analysis below for scope determination.")

    # ── Section 5: Detailed gap analysis ──────────────────────────────────
    print("\n## Section 5: Gap Detail\n")

    # Run 4 (no_graph): What's missing?
    print("### Run 1 vs Run 4 (no_graph):")
    print("  block_telemetry on shortcut: EMPTY on all 3 trials")
    print("  block_telemetry on rich (constraint_001): 1 entry with token stats")
    print("  steps.tool_selection on shortcut: ABSENT (only reply_generation)")
    print("  steps.tool_selection on rich: PRESENT (tool_selection step at index 2)")
    print()
    print("  Interpretation: On shortcut paths, tools execute via snapshot_direct")
    print("  without going through tool_selection step recording. The dependency")
    print("  graph may still have been consulted internally (via readiness/preflight)")
    print("  but the telemetry is not written to trace.")
    print("  For ablation: cannot prove graph WAS consulted — only that no blocking occurred.")
    print()

    # Run 5 (no_constraint): What's missing?
    print("### Run 1 vs Run 5 (no_constraint):")
    print("  block_telemetry on shortcut: EMPTY on all 3 trials")
    print("  steps.cross_constraint_violation on shortcut: ABSENT")
    print("  steps.cross_constraint_violation on rich: PRESENT (blocked motorcycle on highway)")
    print("  clarification_telemetry.stage3_normalizations on shortcut: PRESENT")
    print()
    print("  Interpretation: Normalization records (stage3) show parameter standardization")
    print("  but cross-constraint checks (vehicle_road_compatibility etc.) are NOT recorded")
    print("  on shortcut paths. The rich path recorded the constraint violation explicitly")
    print("  as a step with violation details.")
    print("  For ablation: stage3_normalizations in clarification_telemetry provide partial")
    print("  evidence (parameter values visible), but the specific constraint-check-trigger")
    print("  and violation-reasoning are missing on shortcut paths.")

    return results


if __name__ == "__main__":
    analyze()
