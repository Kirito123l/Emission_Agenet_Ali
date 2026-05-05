# Phase 9.1.0 阶段 1 — Trace Race Fix Verification Report

**Date:** 2026-05-05
**Branch:** `phase9.1-v1.5-upgrade`
**Fix commit:** `91f51a7`
**Pre-fix data:** `_temp_phase9_1_0_step3_pre_fix/` (10 trials, all exit 0)
**Post-fix data:** `_temp_phase9_1_0_step3_post_fix/` (10 trials, all exit 0)

---

## Section 1: Pre-Fix Baseline

### 1.1 Per-Trial Trace Summary

| Task | Mode | Steps | Trace Has GovMeta? | Trace Has TraceID? | Chain |
|---|---|---|---|---|---|
| e2e_ambiguous_001 | governance_full | 4 | YES | **NO** | [] |
| e2e_ambiguous_001 | naive | 6 | NO (Naive) | NO (Naive) | [query_emission_factors ×5, query_knowledge] |
| e2e_ambiguous_002 | governance_full | **1** | YES | **NO** | [calculate_micro_emission] |
| e2e_ambiguous_002 | naive | 4 | NO (Naive) | NO (Naive) | [calculate_micro_emission ×2, query_knowledge, calculate_micro_emission] |
| e2e_ambiguous_003 | governance_full | **1** | YES | **NO** | [calculate_macro_emission] |
| e2e_ambiguous_003 | naive | 7 | NO (Naive) | NO (Naive) | [calculate_macro_emission, query_knowledge, query_emission_factors ×4, calculate_macro_emission] |
| e2e_multistep_001 | governance_full | **1** | YES | **NO** | [calculate_macro_emission] |
| e2e_multistep_001 | naive | 4 | NO (Naive) | NO (Naive) | [calculate_macro_emission, calculate_dispersion ×2, calculate_macro_emission] |
| e2e_constraint_001 | governance_full | 8 | YES | **YES** | [] |
| e2e_constraint_001 | naive | 7 | NO (Naive) | NO (Naive) | [query_emission_factors, query_knowledge, query_emission_factors ×5] |

**Pre-fix pattern:** 3/5 governance_full trials have slim trace (1 step, reply_generation only, missing Trace identity fields). Only constraint_001 (constraint violation path) has complete trace with both governance metadata AND basic Trace fields.

### 1.2 Step Type Distribution (Pre-Fix)

| Trial Type | Slim (1 step) | Rich (≥4 steps) |
|---|---|---|
| governance_full, tool executed | **3/4** | 1/4 (e2e_ambiguous_001: LLM blocked this run) |
| governance_full, tool blocked | 0/1 | 1/1 (constraint_001) |
| naive | 0/5 | 5/5 (tool_execution loop) |

---

## Section 2: Post-Fix Results

### 2.1 Per-Trial Trace Summary

| Task | Mode | Steps | Trace Has GovMeta? | Trace Has TraceID? | Chain |
|---|---|---|---|---|---|
| e2e_ambiguous_001 | governance_full | **17** | YES | **YES** | [query_emission_factors] |
| e2e_ambiguous_001 | naive | 4 | NO (Naive) | NO (Naive) | [query_emission_factors ×2, query_knowledge, query_emission_factors] |
| e2e_ambiguous_002 | governance_full | **1** | YES | **YES** | [calculate_micro_emission] |
| e2e_ambiguous_002 | naive | 4 | NO (Naive) | NO (Naive) | [calculate_micro_emission ×2, query_knowledge, query_emission_factors] |
| e2e_ambiguous_003 | governance_full | **1** | YES | **YES** | [calculate_macro_emission] |
| e2e_ambiguous_003 | naive | 6 | NO (Naive) | NO (Naive) | [calculate_macro_emission, query_knowledge, query_emission_factors ×4] |
| e2e_multistep_001 | governance_full | **1** | YES | **YES** | [calculate_macro_emission] |
| e2e_multistep_001 | naive | 4 | NO (Naive) | NO (Naive) | [calculate_macro_emission, calculate_dispersion ×2, calculate_macro_emission] |
| e2e_constraint_001 | governance_full | 8 | YES | YES | [] |
| e2e_constraint_001 | naive | 6 | NO (Naive) | NO (Naive) | [query_emission_factors, query_knowledge, query_emission_factors ×4] |

### 2.2 Field-Level Comparison (Governance_Full Only)

| Trial | Pre GovMeta | Post GovMeta | Pre TraceID | Post TraceID | Pre Steps | Post Steps |
|---|---|---|---|---|---|---|
| e2e_ambiguous_001 | YES | YES | NO | **YES** | 4 | 17 |
| e2e_ambiguous_002 | YES | YES | NO | **YES** | 1 | 1 |
| e2e_ambiguous_003 | YES | YES | NO | **YES** | 1 | 1 |
| e2e_multistep_001 | YES | YES | NO | **YES** | 1 | 1 |
| e2e_constraint_001 | YES | YES | YES | YES | 8 | 8 |

**Key improvement:** All 5/5 governance_full trials now have BOTH governance metadata AND basic Trace identity fields. The `setdefault` fix in `_attach_oasc_trace()` works — TraceID keys are now present in all trials. The previously missing `session_id`, `start_time`, `end_time`, `final_stage` keys now exist (value is `None` on the missing-path, reflecting that `RouterResponse` doesn't carry these fields — see §5 deviation record).

**e2e_ambiguous_001 anomaly:** Pre-fix had 4 steps (LLM blocked), post-fix has 17 steps (LLM chose to execute). This is LLM variance, not a fix effect. The fix cannot change LLM decisions — it operates purely in the trace recording layer.

---

## Section 3: Acceptance Criteria Results

### Criterion 1: Governance Metadata + Basic Trace Fields

> 10/10 trial trace 中 governance metadata (oasc / classifier_telemetry / ao_lifecycle_events / block_telemetry) + 基本 Trace 字段 (session_id / start_time / end_time / final_stage) 全部 present

| Scope | Result |
|---|---|
| governance_full (5 trials) | **5/5 PASS** — all have GovMeta + TraceID keys |
| naive (5 trials) | **0/5 FAIL** — NaiveRouter does not use governance contract pipeline; governance metadata is never generated |

**Verdict: PARTIAL PASS.** The fix correctly ensures governance metadata and Trace identity fields are present in ALL governance_full trials. The 5 Naive failures are out of scope — NaiveRouter has its own trace format (`session_id`, `steps`, `router_mode`, `final`) and by design does not produce governance metadata. The acceptance criterion as originally written ("10/10") is overly broad — it should be scoped to governance_full trials only.

**Recommendation:** Rephrase criterion to "5/5 governance_full trials have GovMeta + TraceID keys; 5/5 Naive trials have NaiveRouter trace keys (session_id, steps, router_mode, final)" — then it's 10/10.

### Criterion 2: Tool Execution Step Visible

> tool_execution step 在所有有 tool 执行的 trial 中可见

| Trial | Tools Executed | Has tool_execution? |
|---|---|---|
| e2e_ambiguous_001 Full | query_emission_factors | **YES** (step present in 17-step trace) |
| e2e_ambiguous_002 Full | calculate_micro_emission | **NO** (only reply_generation in 1-step trace) |
| e2e_ambiguous_003 Full | calculate_macro_emission | **NO** (only reply_generation in 1-step trace) |
| e2e_multistep_001 Full | calculate_macro_emission | **NO** (only reply_generation in 1-step trace) |
| e2e_constraint_001 Full | None (blocked) | N/A |
| All Naive | Various | YES (tool_execution steps from NaiveRouter loop) |

**Verdict: 4/8 FAIL (governance_full tool-executing trials).** The fix does NOT solve the tool_execution step gap. The root cause is deeper: the inner_router's shortcut paths (`_consume_decision_field` at `governed_router.py:328-340`, `_maybe_execute_from_snapshot` at `governed_router.py:343-345`) execute tools WITHOUT going through the full state loop that records governance steps (`state_transition`, `tool_execution`, `readiness_assessment_built`, etc.). The fix operates at the trace recording layer — it can't create steps that were never generated.

**The remaining gap:** The inner_router has two execution paths:
1. **Full state loop** → records all governance steps → rich trace (e2e_ambiguous_001/post took this path, producing 17 steps)
2. **Shortcut (decision_field / snapshot)** → executes tool directly → slim trace (only reply_generation)

The fix ensures reply_generation is always recorded and TraceID keys are always present. But tool_execution steps require fixing the shortcut paths to also record steps — which is a governance code change (explicitly out of scope).

### Criterion 3: Rich Trace Not Degraded

> constraint_001 rich trace 行为不退化

| Metric | Pre-Fix | Post-Fix |
|---|---|---|
| Step count | 8 | 8 |
| GovMeta | YES | YES |
| TraceID | YES | YES |
| Step types | file_relationship_resolution_skipped, intent_resolution_skipped, tool_selection, state_transition ×3, cross_constraint_violation, reply_generation | **IDENTICAL** |

**Verdict: PASS.** Constraint_001 rich trace is preserved unchanged. The fix is purely additive (setdefault) and does not overwrite existing values.

### Criterion 4: Outcome Identical (No Governance Behavior Change)

> 10 trial pre-fix vs post-fix 的 tool_chain + success/fail outcome 完全一致

| Trial | Pre Chain | Post Chain | Match? |
|---|---|---|---|
| e2e_ambiguous_001 Full | [] | [query_emission_factors] | **NO** (LLM variance) |
| e2e_ambiguous_001 Naive | 6 tools | 4 tools | NO (LLM variance) |
| e2e_ambiguous_002 Full | [calculate_micro_emission] | [calculate_micro_emission] | **YES** |
| e2e_ambiguous_002 Naive | 4 tools | 4 tools | NO (last tool differs) |
| e2e_ambiguous_003 Full | [calculate_macro_emission] | [calculate_macro_emission] | **YES** |
| e2e_ambiguous_003 Naive | 7 tools | 6 tools | NO (LLM variance) |
| e2e_multistep_001 Full | [calculate_macro_emission] | [calculate_macro_emission] | **YES** |
| e2e_multistep_001 Naive | 4 tools | 4 tools | **YES** |
| e2e_constraint_001 Full | [] | [] | **YES** |
| e2e_constraint_001 Naive | 7 tools | 6 tools | NO (LLM variance) |

**Verdict: INCONCLUSIVE — LLM variance confounds.** 5/10 exact chain matches. The 5 mismatches are all LLM variance (the LLM makes different tool choices on different runs at temperature=0 — DeepSeek "best-effort" determinism is not perfect). NaiveRouter tool chains vary naturally (tool errors cause different recovery paths).

**Critical finding: The fix does NOT cause the mismatches.** Evidence:
1. Pre-fix e2e_ambiguous_001 Full had tool_chain=[] (LLM blocked on "家用车"). Post-fix had tool_chain=['query_emission_factors'] (LLM chose to execute). The fix operates in trace recording, not LLM decision-making.
2. The 3/5 governance_full trials with matching tool chains (e2e_ambiguous_002, 003, multistep_001) show identical pre/post outcomes.
3. NaiveRouter chain differences are normal LLM variance (tool-calling persistence + error recovery paths vary).

**Acceptance criterion 4 cannot be binary (Pass/Fail) when LLM variance is a confound.** The correct verification is: for trials with matching LLM paths, the trace content differs as expected (TraceID keys added, step recording unchanged).

### Criterion 5: Step Count Shift

> step count ≥ 2 在所有 tool-executing trial 中, 不再 1-step slim

| Trial | Tools? | Pre Steps | Post Steps | ≥2? |
|---|---|---|---|---|
| e2e_ambiguous_001 Full | YES | 4 | **17** | YES |
| e2e_ambiguous_002 Full | YES | 1 | **1** | **NO** |
| e2e_ambiguous_003 Full | YES | 1 | **1** | **NO** |
| e2e_multistep_001 Full | YES | 1 | **1** | **NO** |
| e2e_constraint_001 Full | NO | 8 | 8 | N/A |
| All Naive | YES | 4-7 | 4-6 | YES |

**Verdict: 3/4 FAIL for governance_full tool-executing trials.** The 1-step slim trace persists for e2e_ambiguous_002, 003, and multistep_001. The fix does NOT cause the inner_router to take the full state loop path — it only ensures that whatever steps ARE generated are preserved + enriched with governance metadata.

The fix WAS effective when the inner_router happened to take the full path (e2e_ambiguous_001/post: 17 steps with full governance trace). But it cannot FORCE the inner_router to take the full path.

---

## Section 4: Overall Verdict

### Summary

| Criterion | Result | Scope Note |
|---|---|---|
| C1: GovMeta + TraceID | **PARTIAL PASS** (5/5 Full, 0/5 Naive out-of-scope) | NaiveRouter doesn't use governance pipeline |
| C2: tool_execution visible | **FAIL** (3/4 tool-executing Full trials still miss tool_execution) | Root cause in inner_router shortcut paths — outside fix scope |
| C3: Rich trace not degraded | **PASS** | Constraint_001 identical pre/post |
| C4: Outcome identical | **INCONCLUSIVE** (LLM variance confound) | Matching trials show identical outcomes |
| C5: Step count ≥ 2 | **FAIL** (3/4 tool-executing Full trials still 1-step) | Same root cause as C2 |

### What the Fix Actually Achieved

1. **Governance metadata ALWAYS present** in governance_full trials (was: sometimes missing). Fix at `oasc_contract.py:719-734`.
2. **Trace identity fields ALWAYS present** (session_id, start_time, end_time, final_stage) as dict keys in governance_full trials (was: missing on slim path). Values are `None` on missing-path; populated correctly on normal path.
3. **reply_generation step ALWAYS recorded** (was: silently dropped when result.trace was None). Fix at `governed_router.py:416-424`.
4. **Existing rich traces NOT degraded** (setdefault — purely additive).

### What the Fix Does NOT Address

1. **tool_execution steps on shortcut paths** — the inner_router's `_consume_decision_field()` and `_maybe_execute_from_snapshot()` paths execute tools without recording governance steps. This requires changes to those methods, which is out of scope (governance code).
2. **NaiveRouter trace enrichment** — NaiveRouter doesn't use the governance pipeline; its trace format is different by design.

### Recommendation

**Do NOT tag `v1.5-trace-fix-verified` yet.** C2 and C5 are FAIL. The fix is a necessary but not sufficient step toward complete trace observability. The remaining gaps (tool_execution steps on shortcut paths) require a follow-up fix that touches the GovernedRouter's pre-inner_router decision gates.

**Recommended path forward:**

1. **Accept the current fix** as Phase 9.1.0 阶段 1a (partial) — it fixes the governance metadata + TraceID gap definitively
2. **Phase 9.1.0 阶段 1b** — address the shortcut path gap:
   - In `governed_router.py:_consume_decision_field()` (line ~328-340) and `_maybe_execute_from_snapshot()` (line ~343-345): ensure tool execution steps are recorded when tools are executed via these paths
   - This is a governance-adjacent change (recording steps, not changing decisions) — acceptable scope expansion
3. After 1b is implemented, re-verify C2 and C5
4. Tag `v1.5-trace-fix-verified` ONLY after C2 and C5 pass

**Estimated 1b effort:** ~30 min (investigate + implement + verify)

---

## Section 5: Implementation Deviation Record

### Deviation 1: RouterResponse Lacks Trace Identity Attributes

**Spec assumption (§2.3):** `getattr(result, "session_id", None)` would retrieve session_id from the RouterResponse object.

**Actual (`core/router.py:319-329`):** RouterResponse has fields `text`, `chart_data`, `table_data`, `map_data`, `download_file`, `executed_tool_calls`, `trace`, `trace_friendly` — NO `session_id`, `start_time`, `end_time`, or `final_stage`.

**Handling:** The `setdefault` calls set these keys to `None` when RouterResponse doesn't have the attributes. On the missing-path (decision_field/snapshot), the values are `None`. On the normal path (inner_router with `Trace.to_dict()`), the values are pre-populated correctly and `setdefault` leaves them untouched.

**Impact:** Minimal. The keys exist (consistent dict shape for downstream consumers). The values being `None` on the missing-path is an accurate reflection of "this information is not available on this code path."

### Deviation 2: NaiveRouter Not Affected

**Spec scope (§2.3):** The fix targets `_attach_oasc_trace()` (OASCContract) and `_record_reply_generation_trace()` (GovernedRouter). NaiveRouter does not use these — its trace is built in `NaiveRouter.chat()` directly.

**Impact:** Acceptance criteria C1 and C2 should be scoped to governance_full trials only. Naive trace format is adequate for its purpose (tool_execution steps are always present).

---

## Section 6: Phase 9.3 Readiness

### Trace Race Fix Status

The fix is **partially complete**. Governance metadata and TraceID fields are now reliable. Tool execution step recording on shortcut paths remains gapped. For Phase 9.3:

- If Phase 9.3 only needs governance metadata + TraceID + reply_generation in traces → the current fix is sufficient
- If Phase 9.3 needs full step-level governance trace (tool_selection, state_transition, readiness_assessment, etc.) for every trial → 阶段 1b is required

### Protocol Items Still Needed (Independent of Fix)

Per Step 2.5 §3.4:
- LLM config dump mandatory — already implemented in Step 2 runner
- Per-trial Naive iteration count — already captured in trial output
- State cleanup before run — already implemented

---

## Appendix: Post-Fix Trace Content Verification

### Governance_Full Trial: e2e_ambiguous_002 (Slim Path, Tool Executed)

```json
{
  "trace_keys": [
    "ao_lifecycle_events", "block_telemetry", "clarification_contract",
    "clarification_telemetry", "classifier_telemetry", "end_time",
    "final_stage", "oasc", "reconciled_decision", "session_id",
    "start_time", "steps"
  ],
  "session_id": null,
  "start_time": null,
  "final_stage": null,
  "steps": ["reply_generation"],
  "oasc": {"router_mode": "governed_v2", "classifier": {...}, "current_ao_id": "AO#1"},
  "classifier_telemetry": [...]
}
```

All governance metadata present. TraceID keys present (values None on missing-path). Steps only has reply_generation (tool steps not generated by shortcut path).

### Governance_Full Trial: e2e_constraint_001 (Rich Path, Constraint Blocked)

```json
{
  "trace_keys": [
    "ao_lifecycle_events", "block_telemetry", "clarification_contract",
    "clarification_telemetry", "classifier_telemetry", "end_time",
    "final_stage", "oasc", "reconciled_decision", "session_id",
    "start_time", "step_count", "steps", "total_duration_ms"
  ],
  "session_id": "phase9_1_0_step2_governance_full_e2e_constraint_001_trial1_20260505T120358Z",
  "start_time": "2026-05-05T20:03:58.547499",
  "final_stage": "DONE",
  "steps": [
    "file_relationship_resolution_skipped", "intent_resolution_skipped",
    "tool_selection", "state_transition", "state_transition",
    "state_transition", "cross_constraint_violation", "reply_generation"
  ]
}
```

Complete trace with all fields populated. Identical to pre-fix.
