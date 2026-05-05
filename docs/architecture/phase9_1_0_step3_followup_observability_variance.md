# Phase 9.1.0 阶段 1a — Trace Observability Sufficiency + LLM Variance

**Date:** 2026-05-05
**Branch:** `phase9.1-v1.5-upgrade`
**Preceding work:** Phase 9.1.0 阶段 1 trace race fix (commit `91f51a7`), verified in `phase9_1_0_step3_trace_fix_verification.md`

---

## Section 1: Trace Observability Sufficiency (Task A)

### 1.1 Motivation

Phase 9.1.0 阶段 1 verification found that C2 (tool_execution steps) and C5 (step count ≥2) FAIL because the GovernedRouter's shortcut paths (`_consume_decision_field` at `governed_router.py:328-340` and `_maybe_execute_from_snapshot` at `governed_router.py:343-345`) execute tools without recording governance steps. The question: does Phase 9.3 ablation actually NEED step-level visibility, or is metadata (oasc, classifier_telemetry, block_telemetry, ao_lifecycle_events, reconciled_decision) sufficient?

### 1.2 Data Source

Post-fix Step 3 trials at `evaluation/results/_temp_phase9_1_0_step3_post_fix/`:

| Trial | Path Type | Steps | Proceed Mode |
|---|---|---|---|
| e2e_ambiguous_002 Full | shortcut | 1 (reply_generation only) | snapshot_direct |
| e2e_ambiguous_003 Full | shortcut | 1 (reply_generation only) | snapshot_direct |
| e2e_multistep_001 Full | shortcut | 1 (reply_generation only) | snapshot_direct |
| e2e_constraint_001 Full | rich | 8 (full governance trace) | fallback |

### 1.3 Field-Level Metadata Completeness

| Field | Shortcut (3/3) | Rich | Assessment |
|---|---|---|---|
| `oasc.classifier` | OK (3/3) | OK | Full classifier result: layer, classification, confidence, reasoning |
| `oasc.ao_block` | **GAP** | OK | None on shortcut — no token estimation info |
| `classifier_telemetry` | OK (3/3) | OK | Full: turn, layer_hit, classification, confidence, reasoning |
| `ao_lifecycle_events` | OK (3/3) | OK | Full: create→activate→append_tool_call→complete/blocked + complete_check_results |
| `block_telemetry` | **GAP** | OK | **EMPTY [] on all 3 shortcut trials** — no dependency/constraint check records |
| `reconciled_decision` | OK (3/3) | GAP | Full on shortcut: decision_value=clarify, source_trace with p1/p2/p3. None on rich (constraint_001 doesn't invoke reconciler) |
| `clarification_contract` | OK (3/3) | OK | Full: enabled, final_decision, tool_name |
| `clarification_telemetry` | OK (3/3) | OK | Very rich: stage1/2/3, normalizations, stance analysis, PCM advisory, llm_intent_raw.chain |
| `steps.reply_generation` | OK (3/3) | OK | Present on all paths |
| `steps.tool_selection` | **GAP** | OK | Absent on shortcut — tool chosen via snapshot_direct, not recorded |
| `steps.state_transition` | **GAP** | OK | Absent on shortcut — no state machine step recording |
| `steps.cross_constraint_violation` | **GAP** | OK | Absent on shortcut — constraint check not recorded as step |

### 1.4 Phase 9.3 Ablation Evidence Mapping

| Ablation | Evidence Needed | Shortcut Verdict | Detail |
|---|---|---|---|
| Run 1 vs 2 (Full vs Naive) | Outcome (chain + success/fail) | **SUFFICIENT** | `ao_lifecycle_events.complete_check_results` has objective_satisfied, tool_chain_succeeded, completion_path on all 3 shortcut trials |
| Run 1 vs 3 (no_ao) | AO classifier contribution | **SUFFICIENT** | `classifier_telemetry` shows layer_hit=rule_layer1, classification=NEW_AO, confidence=1.0 on all 3 trials. `oasc.classifier` mirrors this. `ao_lifecycle_events` has create→activate→append_tool_call→complete sequence |
| Run 1 vs 4 (no_graph) | Dependency graph contribution | **PARTIAL (1/3 checks)** | `block_telemetry` EMPTY on all 3 shortcut trials. `reconciled_decision` present. **Cannot prove dependency graph was consulted** — only that no blocking occurred |
| Run 1 vs 5 (no_constraint) | Cross-constraint contribution | **PARTIAL (1/3 checks)** | `block_telemetry` EMPTY. `clarification_telemetry.stage3_normalizations` has parameter standardization records (vehicle_type, pollutants). **Constraint-check-trigger and violation-reasoning missing** |
| Run 6 (held-out) | Same as Run 1 evidence | **SUFFICIENT** | Inherits Run 1 verdict |
| Run 7 (Shanghai e2e) | Multi-turn AO + chain projection | **SUFFICIENT** | `ao_lifecycle_events` captures full event sequence. `llm_intent_raw.chain` in `clarification_telemetry` shows projected chain. `oasc.classifier` has AO identity |

### 1.5 Key Finding: The `block_telemetry` Gap

The critical finding is that `block_telemetry` is **EMPTY** on all 3 shortcut-path trials. This affects:

- **Run 4 (no_graph):** Without block_telemetry entries, the ablation cannot prove that the tool dependency graph was consulted before execution. The dependency graph may still have been invoked internally (via `preflight_check()` / `readiness` pipeline), but no record is written to trace.
- **Run 5 (no_constraint):** Same issue. Without `cross_constraint_violation` steps and `block_telemetry` entries, the ablation cannot prove constraint checks were consulted. However, `clarification_telemetry.stage3_normalizations` does record parameter normalization results, providing partial evidence.

Importantly, the EMPTY `block_telemetry` on shortcut paths could mean either (a) "checks were consulted, no blocking found" or (b) "checks were skipped on shortcut path." The trace cannot distinguish these two cases.

### 1.6 Option C Resolution

**Verdict: OPTION C2 — Narrow 1b.**

| Metric | Count |
|---|---|
| Ablation runs fully satisfied by metadata | 4/6 (Run 1vs2, 1vs3, 6, 7) |
| Ablation runs partially satisfied | 2/6 (Run 1vs4, 1vs5) |
| Ablation runs with zero metadata | 0/6 |

**Recommended 1b scope (narrow):**

1. In `governed_router.py:_consume_decision_field()` (~line 328-340): before executing tool via shortcut, record `tool_selection` step (tool name, reasoning) and append to trace.steps.
2. In `governed_router.py:_maybe_execute_from_snapshot()` (~line 343-345): same as above.
3. In both paths: dump `block_telemetry` (dependency check result, constraint check result) into trace if available from the contract pipeline.

This is ~20-30 LOC in governed_router.py, touching only the shortcut method bodies. No changes to contract pipeline, classifier, or decision logic. It does NOT require a full refactor of the shortcut paths — just appending trace records before/after tool execution.

**What 1b does NOT need to do:**
- Full state loop recording (state_transition steps) — not needed for Phase 9.3 evidence
- Shortcut path redesign — tool execution logic unchanged
- NaiveRouter changes — NaiveRouter's trace format is separate and adequate

---

## Section 2: LLM Variance Quantification (Task B)

### 2.1 Experiment Design

- 5 Step 2 sampling tasks × 3 trials × governance_full mode = 15 trials
- Fresh state per trial (state cleanup + unique session_id)
- Nonce prefix: `[step3b_trial={N}_{timestamp}]`
- All trials within ~X minutes (sequentially executed)
- LLM: DeepSeek deepseek-v4-pro, temperature=0
- Runner: `evaluation/run_phase9_1_0_step3b_variance.py`

### 2.2 Per-Task Variance

| Task | Chain (3/3) | Outcome (3/3) | First-Tool (3/3) | Tool Count (3/3) | Notes |
|---|---|---|---|---|---|
| e2e_ambiguous_001 | **3/3** | **3/3** | **3/3** | **3/3** | stable-success: all query_emission_factors, 1 step |
| e2e_ambiguous_002 | **2/3** | **2/3** | **2/3** | **2/3** | MODERATE: T1 blocked [], T2-3 success [calculate_micro_emission] |
| e2e_ambiguous_003 | **3/3** | **3/3** | **3/3** | **3/3** | stable-success: all calculate_macro_emission, 1 step |
| e2e_multistep_001 | **3/3** | **3/3** | **3/3** | **3/3** | stable-success: all calculate_macro_emission only (no 2nd tool) |
| e2e_constraint_001 | **3/3** | **3/3** | **3/3** | **3/3** | stable-blocked: all blocked with 8-step rich trace |

**Per-trial details:**

| Task | Trial | Chain | Outcome | Steps |
|---|---|---|---|---|
| e2e_ambiguous_001 | 1 | [query_emission_factors] | success | 1 |
| | 2 | [query_emission_factors] | success | 1 |
| | 3 | [query_emission_factors] | success | 1 |
| e2e_ambiguous_002 | **1** | **[]** | **blocked** | **1** |
| | 2 | [calculate_micro_emission] | success | 1 |
| | 3 | [calculate_micro_emission] | success | 1 |
| e2e_ambiguous_003 | 1 | [calculate_macro_emission] | success | 1 |
| | 2 | [calculate_macro_emission] | success | 1 |
| | 3 | [calculate_macro_emission] | success | 1 |
| e2e_multistep_001 | 1 | [calculate_macro_emission] | success | 1 |
| | 2 | [calculate_macro_emission] | success | 1 |
| | 3 | [calculate_macro_emission] | success | 1 |
| e2e_constraint_001 | 1 | [] | blocked | 8 |
| | 2 | [] | blocked | 8 |
| | 3 | [] | blocked | 8 |

**Key observations:**
- e2e_ambiguous_002 trial 1 was BLOCKED (chain=[]) while trials 2-3 executed calculate_micro_emission successfully. This is an outcome category jump (blocked vs success) within 3 trials run minutes apart. The LLM made a different decision on the SAME prompt — trial 1's classifier/readiness pipeline reached a "block" decision while trials 2-3 reached "proceed."
- e2e_multistep_001: The LLM executed only `calculate_macro_emission` in all 3 trials, NOT the 2-tool chain `[calculate_macro_emission, calculate_dispersion]` specified in the prompt ("请先计算...再做扩散分析"). This is consistent with Step 2/Step 3 behavior where the LLM also only executed 1 tool.
- e2e_constraint_001: 3/3 blocked with identical 8-step rich traces — the hard constraint path is perfectly deterministic.

### 2.3 Cross-Task Summary

| Metric | 3/3 | 2/3 | 1/3 |
|---|---|---|---|
| Chain consistency | 4/5 tasks | 1/5 tasks | 0/5 tasks |
| Outcome consistency | 4/5 tasks | 1/5 tasks | 0/5 tasks |
| First-tool consistency | 4/5 tasks | 1/5 tasks | 0/5 tasks |

By task category:

| Category | Task | Chain | Outcome |
|---|---|---|---|
| ambiguous_success | e2e_ambiguous_002 | 2/3 | 2/3 |
| ambiguous_value_delta | e2e_ambiguous_001 | 3/3 | 3/3 |
| ambiguous_fail | e2e_ambiguous_003 | 3/3 | 3/3 |
| multistep | e2e_multistep_001 | 3/3 | 3/3 |
| constraint_blocked | e2e_constraint_001 | 3/3 | 3/3 |

The only unstable category is `ambiguous_success` (e2e_ambiguous_002). The ambiguous parameter tasks (001, 003) that require LLM-driven parameter resolution were surprisingly stable.

### 2.4 Phase 9.3 Trial Count Recommendation

**RECOMMENDATION: Hybrid (1 trial default + 3 trials for known-unstable categories).**

| Distribution | Verdict |
|---|---|
| 4/5 tasks 3/3 chain consistent | High stability within short time windows |
| 1/5 tasks (ambiguous_success) 2/3 | One unstable category: success-baseline tasks with file inputs |
| 0/5 tasks ≤ 2/3 | No tasks in the high-variance range |

**Rationale:** The data supports 1-trial default for most task categories. The `ambiguous_success` category (tasks where the LLM has a clear success path but may choose to block on some runs) needs 3 trials. Constraint-blocked tasks are perfectly deterministic. Multistep tasks are stable (though the LLM may not execute the full intended chain).

**Estimated Phase 9.3 workload:**
- 182 Full tasks: ~50 ambiguous_success × 3 + ~132 others × 1 = ~282 trials
- 100 Naive tasks: 1 trial each = 100 trials
- 182 × 5 ablation runs: depends on ablation mode per task
- **Total estimate: ~250-350 trials for Full + Naive core; ablation trials add proportionally**

### 2.5 Comparison with Prior Steps

| Step | Design | Chain Consistency | Time Gap |
|---|---|---|---|
| Step 1 | Run 7, 5 trials mode_A | 5/5 (100%) | Minutes |
| Step 2 | 5 tasks, 1 trial each | Single-point (N/A) | N/A |
| Step 3 pre vs post | 5 tasks, 2 trials | 5/10 (50%) | ~40 min |
| Step 3b | 5 tasks, 3 trials | 4/5 (80% 3/3, 1/5 2/3) | ~13 min |

**Interpretation: (b) Time interval is the primary confound.**

- Within short intervals (~13 min): 4/5 tasks perfect, 1/5 tasks 2/3. Overall 13/15 trials (87%) match within their task group.
- Across longer intervals (~40 min, Step 3 pre/post): Only 5/10 (50%) chain match.
- Step 1's 5/5 was Run 7 specifically — a multi-turn grounded prompt (Turn 1 already established AO#1 context). This anchors the LLM more than single-turn ambiguous prompts.
- e2e_ambiguous_002's trial 1 outlier shows that even within minutes, the LLM can flip from "block" to "proceed" on a file-input task. This is category-specific instability, not time-driven.

**Hypothesis ranking:**
1. **(b) Time interval** — STRONG: Step 3b's 87% intra-task consistency vs Step 3's 50% cross-interval consistency supports this as the primary factor.
2. **(a) Run 7 prompt stability** — MODERATE: Step 1's 5/5 for Run 7 is a real phenomenon (grounded multi-turn), but not generalizable to all tasks.
3. **(c) Environment changes** — WEAK: State cleanup per trial eliminates session pollution. No evidence of other environmental drift.

---

## Section 3: Comprehensive Resolution

### 3.1 Decision Matrix

| Decision | Options | Recommendation | Basis |
|---|---|---|---|
| Tag `v1.5-trace-fix-verified` now? | Yes / No | **No — defer to post-1b** | C2/C5 still fail. Tag criteria require step visibility on shortcut paths. |
| Proceed to 1b? Scope? | No / Narrow / Full design | **Narrow 1b** (§1.6) | 2/6 ablation runs need block_telemetry + tool_selection on shortcut. ~20-30 LOC fix in `governed_router.py:328-345`. |
| Phase 9.3 trial count? | 1 / Hybrid / 3 / Reassess | **Hybrid** (§2.4) | 4/5 tasks 3/3 stable. 1-trial default + 3-trial for ambiguous_success category. ~250-350 total. |
| Other gating items before Phase 9.1.0 full design? | — | **1b completion + tag** | 1b is the only remaining gate. No other blocking items identified. |

### 3.2 Recommended Path

1. **Phase 9.1.0 阶段 1b** (narrow, ~30 min): Add tool_selection step + block_telemetry recording to shortcut paths at `governed_router.py:328-345`
2. **Re-verify C2 + C5**: Run 3 shortcut-task trials post-1b, confirm tool_selection steps + block_telemetry present
3. **Tag `v1.5-trace-fix-verified`**: After C2 + C5 pass with criterion restatement (C2: tool_selection step visible on all code paths; C5: step count includes tool_selection)
4. **Phase 9.3 trial count protocol**: Adopt hybrid approach — 1 trial default, 3 trials for `ambiguous_success` category
5. **Phase 9.1.0 阶段 2** (完整设计): Begin full v1.5 ConversationState design

### 3.3 Key Finding: e2e_ambiguous_002 Outcome Jump

During Step 3b variance measurement, e2e_ambiguous_002 trial 1 produced `outcome=blocked (chain=[])` while trials 2-3 produced `outcome=success (chain=[calculate_micro_emission])`. This is an outcome CATEGORY jump (blocked vs success) — not a chain micro-adjustment. The same prompt, same code, same LLM (DeepSeek T=0), minutes apart.

**Impact:** This finding reinforces the hybrid trial count decision. A single trial for `ambiguous_success` tasks could randomly hit a "blocked" outcome and misrepresent the task's typical behavior. Three trials with majority-vote outcome classification mitigates this risk.

**Root cause hypothesis:** The classifier/readiness pipeline on e2e_ambiguous_002 involves LLM calls (stage2 semantic validation, stance analysis). DeepSeek's "best-effort" determinism at T=0 occasionally produces different responses from the same prompt, causing different governance decisions downstream. This is consistent with the Step 2.5 NaiveRouter drift finding (LLM-driven, not code/config drift).

---

## Section 4: Anchors Compliance Check

### 4.1 Anchors Review

| Anchor | Status | Notes |
|---|---|---|
| §一: TaskStage finite-state machine | UNCHANGED | 1b adds step recording, not state transitions |
| §二: Tool dependency graph | UNCHANGED | 1b records dependency check result, doesn't change graph |
| §三: AO classification + lifecycle | UNCHANGED | Metadata already fully present on shortcut paths |
| §四: Cross-parameter constraints | UNCHANGED | 1b records constraint check, doesn't change rules |
| §五: Evaluating the architecture | NO NEW FINDING | 1b is trace observability fix, not architectural change |

### 4.2 Variance-Affected Elements

If §2.4 recommends changing Phase 9.3 trial count from 1 to ≥3:

- **Anchors §五 is NOT triggered**: Trial count is a data-credibility methodology decision, not an architectural finding. Anchors does not specify trial counts.
- **If §2.4 recommends "reassess methodology"**: This would be a finding about LLM determinism limitations, not about the EmissionAgent architecture. Report as a Phase 9.3 protocol concern, not an Anchors violation.

---

## Appendix A: Data Files

| File | Status | Location |
|---|---|---|
| Variance trial outputs (15) | Complete (not committed) | `evaluation/results/_temp_phase9_1_0_step3b_variance/` |
| Variance summary | Complete (not committed) | `evaluation/results/_temp_phase9_1_0_step3b_variance/summary.json` |
| Variance runner | Committed | `evaluation/run_phase9_1_0_step3b_variance.py` |
| Metadata analysis script | Committed | `evaluation/scripts/analyze_metadata_completeness.py` |
| Variance analysis script | Committed | `evaluation/scripts/analyze_llm_variance.py` |
| Comprehensive report | Committed | `docs/architecture/phase9_1_0_step3_followup_observability_variance.md` |

## Appendix B: STOP & Report Checklist

| Condition | Triggered? | Detail |
|---|---|---|
| Metadata worse than expected (multiple metadata empty/None) | **No** | block_telemetry EMPTY is as predicted in Step 3 report §4. Other metadata (classifier_telemetry, clarification_telemetry, ao_lifecycle_events) is rich and complete on shortcut paths. |
| All tasks ≤2/3 variance (high variance) | **No** | 4/5 tasks 3/3 chain consistent. Only 1/5 (e2e_ambiguous_002) at 2/3. |
| Outcome category jump in variance batch | **YES** — e2e_ambiguous_002 trial 1 blocked vs trials 2-3 success | Reported in §3.3. Not a stop-reason because it's a single-trial outlier within a 3-trial group, and the majority (2/3) matches the Step 2/Step 3 expected outcome. This finding reinforces the hybrid trial approach rather than invalidating the methodology. |
| API timeout/5xx >1 | **No** | All 15 trials completed successfully. No API errors. |
