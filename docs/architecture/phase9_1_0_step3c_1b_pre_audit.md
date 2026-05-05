# Phase 9.1.0 阶段 1b Pre-Audit — Shortcut Path Contract Pipeline Invocation

**Date:** 2026-05-05
**Branch:** `phase9.1-v1.5-upgrade` (HEAD: `7a43de3`)
**Scope:** Read-only code audit. No code changes, no trial runs.

---

## Section 1: Shortcut Path Code Trajectory

### 1.1 `_consume_decision_field()` — Full Trace

**Definition:** `core/governed_router.py:924-1137`
**Caller:** `core/governed_router.py:329` — inside `chat()`, guarded by `enable_llm_decision_field` (True at runtime)

**Complete function body audit:**

| Line Range | What It Does | Key Variables |
|---|---|---|
| 937-947 | Extract `decision` from `stage2_payload` or `clarification.telemetry.stage2_decision` | `decision`, `stage2_payload` |
| 949-956 | Validate decision payload via `validate_decision()` | `is_valid`, `fallback_reason` |
| 959-965 | Build P1 (from stage2 LLM), P2 (from stage3 YAML), P3 (from readiness_gate) | `p1`, `p2`, `p3` |
| 967-975 | Extract P3: first from `context.metadata["readiness_gate"]`, then from `clarification_state["readiness_gate"]` | `readiness_gate`, `p3` |
| 977-980 | Run B-validator: filter missing_required through tool contract | `b_result` |
| 983-999 | **Write trace step `b_validator_filter`** (if trace is not None) | `trace["steps"]` |
| 1002-1016 | **Write trace step `reconciler_invoked`** (if trace is not None) | `trace["steps"]` |
| 1019 | **RUN RECONCILER:** `reconcile(p1, p2, p3, b_result, tool_name)` | `reconciled` |
| 1022-1030 | **Store `reconciled_decision` in `context.metadata`** | `context.metadata["reconciled_decision"]` |
| 1032-1034 | Determine `value`: `reconciled.decision_value` or fallback to `decision["value"]` | `value` |
| 1038-1048 | **Write trace step `reconciler_proceed`** (if value=="proceed" and trace is not None) | `trace["steps"]` |
| 1051-1117 | **`value == "proceed"` branch:** | |
| 1056-1059 | Extract snapshot; check `enable_cross_constraint_validation` config | `snapshot` |
| 1067-1074 | **IF snapshot exists: RUN CROSS-CONSTRAINT VALIDATION** via `get_cross_constraint_validator().validate(snapshot, tool_name, ...)` | `cc_result` |
| 1075-1115 | If violations found: record to violation_writer, write `cross_constraint_violation` trace step, return RouterResponse | |
| 1116-1117 | If clean: **return None** (falls through to snapshot/inner_router) | |
| 1119-1137 | **`value == "clarify"` branch:** Build question. If question empty → **return None** (falls through) | |
| 1139+ | **`value == "deliberate"` branch:** Return RouterResponse | |

**Key observation at line 1117 and 1130:** Both "proceed with clean constraint" and "clarify with empty question" return `None`, causing fall-through to `_maybe_execute_from_snapshot`. In the observed trace data, the reconciler returns `decision_value="clarify"` with empty `clarification_question` and empty `reconciled_missing_required` → `_consume_decision_field` returns `None` → execution continues to `_maybe_execute_from_snapshot`.

**Cross-constraint check on this path:** Only runs at line 1070 when `value == "proceed"`. Given that the reconciler returns "clarify" on all observed shortcut trials, **the cross-constraint check at line 1070 is NEVER invoked on current shortcut paths**. This is not a bug — the reconciler decided "clarify" rather than "proceed", so there's no "proceed" decision to validate constraints against. The constraint check still happens downstream (see §1.2).

### 1.2 `_maybe_execute_from_snapshot()` — Full Trace

**Definition:** `core/governed_router.py:641-694`
**Caller:** `core/governed_router.py:334` — inside `chat()`, unconditionally called if result is still None

**Complete function body audit:**

| Line Range | What It Does | Key Variables |
|---|---|---|
| 642-646 | Extract `direct_execution` from `clarification_state`. Return None if not a dict | `direct_execution` |
| 648-663 | Extract `tool_name`, `parameter_snapshot`, `allow_factor_year_default` | `tool_name`, `snapshot` |
| 662-663 | Return None if tool_name empty or snapshot not a dict | |
| 665-673 | **Call `_execute_from_snapshot()`** — the actual tool execution | `response` |
| 674-679 | If response is None: set `proceed_mode="fallback"`, return None → inner_router | |
| 681-694 | If response is not None: set `proceed_mode="snapshot_direct"`, **return RouterResponse** | |

**`_execute_from_snapshot()` internal (lines 696-820):**

| Line | What It Does |
|---|---|
| 707-711 | Convert snapshot to tool args via `_snapshot_to_tool_args()` |
| 715-739 | Idempotency check (if enabled) |
| 755 | Clear inner_router context store |
| 756 | **`result = await self.inner_router.executor.execute(tool_name, arguments, file_path)`** — DIRECT tool execution, bypassing inner_router state loop |
| 761-762 | If execution fails: return None |
| 764 | Save result to session context |
| 793 | **`response = await self.inner_router._state_build_response(state, ..., trace_obj=None)`** — note `trace_obj=None`! |
| 813-819 | **`if trace is not None:` record `tool_execution` step** — but trace IS None (context.trace defaults to None) |
| 820+ | Return response with memory update |

**Critical finding at line 813:** The code DOES attempt to record `tool_execution` step with `action: "clarification_contract_snapshot_direct"` and full output summary (tool_name, success, wall_time_ms). But this is guarded by `if trace is not None:`. Since `trace=context.trace` (passed at line 672) and the caller (`chat()`) defaults `trace=None`, this step recording **is silently skipped**.

### 1.3 Contract Pipeline Invocation Spectrum

**`governed_router.chat()` main flow (lines 228-381):**

| Phase | Lines | What Runs | Shortcut Path? |
|---|---|---|---|
| ContractContext creation | 235-239 | `ContractContext(user_message, file_path, trace)` | Always |
| **ALL contracts `before_turn()`** | 242-258 | OASCContract + ClarificationContract + DependencyContract | **Always — BEFORE any shortcut** |
| PCM advisory trace | 260-282 | Record PCM advisory steps (if trace not None) | Always |
| Projected chain trace | 284-317 | Record projected chain steps (if trace not None) | Always |
| Idempotency pre-check | 320-325 | `_check_pre_dispatch_idempotency()` | Always |
| **_consume_decision_field** | 327-332 | Reconciler (P1+P2+P3) + optional cross-constraint | Only if `enable_llm_decision_field=True` (IS True) |
| **_maybe_execute_from_snapshot** | 333-334 | Direct tool execution via executor | Always (if result still None) |
| **inner_router.chat()** | 342-346 | Full state loop with all governance steps | Only if BOTH shortcuts return None |
| Constraint violation recording | 351-355 | `_record_constraint_violations_from_trace()` | Always |
| **ALL contracts `after_turn()`** | 357-358 | OASCContract.after_turn (AO lifecycle sync + `_attach_oasc_trace`) | Always |
| Reply generation | 360-379 | LLM reply parser + `_record_reply_generation_trace` | Always |

### 1.4 Contract-by-Contract before_turn Call Analysis

| Contract | before_turn line | What it sets in context.metadata |
|---|---|---|
| **OASCContract** | `oasc_contract.py:44-72` | `oasc.classification`, `oasc.classifier_ms`, `state_snapshot` |
| **ClarificationContract** | `clarification_contract.py:177-?` | `clarification.telemetry` (stage1/2/3 results), `clarification.direct_execution` (parameter_snapshot + tool_name), `clarification.readiness_gate`, `stage2_payload`, `tool_intent`, `stance` |
| **DependencyContract** | (inherits BaseContract) | **NOTHING** — placeholder, always returns `proceed=True` |

**Key finding: DependencyContract is a NO-OP.** It has no `before_turn()` override and always passes through. The dependency/graph validation (TOOL_GRAPH prerequisite check) does NOT live in any contract — it lives in `core/router.py` inside the inner_router's state loop (`validate_tool_prerequisites` at lines 8811, 9305; `get_missing_prerequisites` at line 10763).

---

## Section 2: Dependency Check + Constraint Check — Invocation Analysis

### 2.1 Cross-Parameter Constraint Check

**Two invocation points found:**

| # | Location | When Fires | Shortcut Path? |
|---|---|---|---|
| 1 | `governed_router.py:1070` (inside `_consume_decision_field`) | reconciler says "proceed" + snapshot exists | **NO on current data** — reconciler says "clarify" |
| 2 | `services/standardization_engine.py:641-655` (inside executor's `_standardize_arguments()`) | During tool parameter standardization | **YES — fires on every executor.execute() call** |

**Invocation #2 detail:** The standardization engine calls `get_cross_constraint_validator().validate(normalized_params, tool_name)` during parameter normalization. Result stored in `self._last_constraint_result`. Then retrieved by executor at `executor.py:230, 285` as `exec_trace["cross_constraint_validation"]` and `result["_trace"]["cross_constraint_validation"]`.

**Data flow gap:** The result is in `result["_trace"]["cross_constraint_validation"]` (the tool execution result dict), but `_execute_from_snapshot()` at line 756-820 does NOT propagate this to `trace["block_telemetry"]`. The data EXISTS but is not surfaced.

**Verdict: EASY for cross-constraint.** The check runs inside the executor. Result is accessible in `result.get("_trace", {}).get("cross_constraint_validation")`. Fix: after line 756, extract and dump to trace.

### 2.2 Tool Dependency Forward Validation (TOOL_GRAPH)

**Invocation points found in `core/router.py`:**

| # | Location | Context |
|---|---|---|
| 1 | `router.py:8811` | `validate_tool_prerequisites()` in state loop |
| 2 | `router.py:9305` | `validate_tool_prerequisites()` in tool execution orchestration |
| 3 | `router.py:10763` | `get_missing_prerequisites()` in tool selection grounded check |

**All three invocations are inside `inner_router.chat()` (full state loop), which is BYPASSED on the shortcut path.**

The executor (`core/executor.py:176-288`) does NOT perform dependency validation. It only:
1. Gets tool from registry
2. Standardizes parameters (which triggers cross-constraint check)
3. Executes tool

**Verdict: HARD for dependency validation.** The TOOL_GRAPH prerequisite check does NOT run on the shortcut path. Adding it would require calling `validate_tool_prerequisites(tool_name, available_results)` before `executor.execute()` — a new governance check that could block tool execution on the shortcut path (governance behavior change).

### 2.3 Indirect Evidence from Step 3b Trace Data

All 9 shortcut-path trials (e2e_ambiguous_002 × 3 + e2e_ambiguous_003 × 3 + e2e_multistep_001 × 3) show:

| Field | Status | Evidence |
|---|---|---|
| `clarification_telemetry.stage3_normalizations` | **PRESENT** (populated) | Standardization ran during executor → cross-constraint check via invocation #2 ran |
| `reconciled_decision` | **PRESENT** (`decision_value="clarify"`, `R_A_DEFER_TO_READINESS`) | Reconciler ran in `_consume_decision_field` |
| `reconciled_decision.source_trace.p3` | **PRESENT** (`disposition=""`, `has_direct_execution="False"`) | P3/readiness_gate was consulted by reconciler |
| `block_telemetry` | **EMPTY []** on all 9 trials | **Neither dependency check (no run) nor cross-constraint (runs but result not dumped) recorded** |
| `ao_lifecycle_events.complete_check_results` | **PRESENT** | AO lifecycle events record outcome but not dependency/constraint checks |

**Interpretation:** The `block_telemetry: []` accurately reflects that no dependency/constraint checks were **recorded** — not that no checks ran. The cross-constraint check DID run (inside executor via standardization engine) but wasn't dumped. The dependency check genuinely did NOT run.

---

## Section 3: 1b Real Scope Estimation

### 3.1 Cross-Constraint: Easy (data exists, needs dump)

**What's available after `executor.execute()` at line 756:**
- `result["_trace"]["cross_constraint_validation"]` — dict with violations/warnings from standardization engine
- `result["_standardization_records"]` — list of per-param standardization records including `cross_constraint_violation` entries

**Fix approach:**
```python
# After line 756 in _execute_from_snapshot:
cc_trace = result.get("_trace", {}).get("cross_constraint_validation")
if cc_trace and trace is not None:
    trace.setdefault("block_telemetry", []).append({
        "source": "standardization_engine",
        "check_type": "cross_constraint",
        "result": cc_trace,
    })
```

**LOC estimate:** ~8 LOC in `_execute_from_snapshot()`.
**Governance behavior change:** No — purely data dump from existing execution result.

### 3.2 Tool Execution Step: Easy (code exists, trace object is None)

**Code already present at lines 813-819** but guarded by `if trace is not None:`. The trace object (`context.trace`) is None because `chat()` defaults trace=None.

**Fix approach:**
```python
# At line 811, before existing code:
trace = trace or {}
# Then line 813-819 will execute
```

Or create a local trace dict early in `_execute_from_snapshot()`:
```python
if trace is None:
    trace = {}
```

**LOC estimate:** ~2 LOC (ensure trace is dict before step recording).
**Governance behavior change:** No — purely recording what already executes.

### 3.3 Dependency Validation: Hard (check doesn't run)

**What would be needed:**
1. Import `validate_tool_prerequisites` from `core.tool_dependencies`
2. Get available_results from session context (`self.inner_router._ensure_context_store()`)
3. Call `validate_tool_prerequisites(tool_name, available_results)` before line 756
4. Record result in `trace["block_telemetry"]`
5. Handle blocking: if prerequisites missing, return None (fall through to inner_router) or return RouterResponse with error

**LOC estimate:** ~20-30 LOC in `_execute_from_snapshot()`.
**Governance behavior change:** YES — tools that currently execute on shortcut path could be BLOCKED by dependency validation. This is a new governance gate on a path specifically designed to skip governance.

**Risk:** The shortcut path exists to execute tools quickly when the ClarificationContract has determined all parameters are ready. Adding dependency validation could block tools that were previously executing successfully, causing regression in success rates. Testing required.

### 3.4 Overall Classification

| Check | Runs on Shortcut? | Result Accessible? | Fix Difficulty | LOC | Gov Behavior Change? |
|---|---|---|---|---|---|
| Cross-constraint validation | YES (via executor) | YES (`result._trace.cross_constraint_validation`) | Easy | ~8 | No |
| Tool execution step recording | YES (code at line 813) | Code present but trace=None guard | Easy | ~2 | No |
| Dependency/graph validation | NO | N/A (must add check) | Hard | ~20-30 | **YES** |

**Overall: MIXED (Easy + Hard).** Not purely Easy, not purely Hard.

---

## Section 4: 1b Real Scope Recommendation

### 4.1 What "Narrow 1b" Actually Means

The Phase 9.1.0 阶段 1a report recommended "narrow 1b (~20-30 LOC)" assuming both checks ran and just needed dumping. The audit reveals:

- **Cross-constraint: matches expectation** — check runs, result accessible, ~8 LOC dump
- **Dependency: does NOT match expectation** — check doesn't run, ~20-30 LOC to add, governance behavior change

The cross-constraint dump is genuinely 8 LOC. The tool_execution step fix is 2 LOC. But the dependency validation part of 1b would require NEW governance logic on the shortcut path.

### 4.2 LOC Estimate Breakdown

| Component | Difficulty | LOC | Notes |
|---|---|---|---|
| Ensure trace dict exists in `_execute_from_snapshot` | Trivial | 2 | Fix silent drop of existing tool_execution step |
| Dump cross_constraint_validation to block_telemetry | Easy | 8 | Extract from `result._trace` after executor.execute() |
| Add tool_selection step before executor.execute() | Easy | 10 | Record which tool was selected + reasoning from context.metadata |
| Add dependency validation call | Hard | 25 | New `validate_tool_prerequisites()` call + result recording + block handling |
| **Total (with dependency)** | Mixed | **~45** | 20 LOC Easy + 25 LOC Hard |
| **Total (without dependency)** | Easy | **~20** | Cross-constraint dump + tool_selection + trace fix |

### 4.3 Hard Component Trade-off

Adding dependency validation to the shortcut path:

**Pro:** Phase 9.3 Run 4 (no_graph) ablation gets direct evidence. Every tool execution on shortcut path would have a recorded dependency check in `block_telemetry`.

**Con:** Governance behavior change — tools that currently execute via shortcut could be blocked by missing prerequisites. This changes the very behavior Phase 9.3 is trying to measure against NaiveRouter baseline.

**Risk mitigation:** The dependency check result could be recorded as a WARNING rather than a BLOCK on the shortcut path. This preserves current behavior while still recording the dependency check for Phase 9.3 evidence.

---

## Section 5: Recommended Next-Step Options

| # | Option | Scope | LOC | Gov Change? | Phase 9.3 Impact |
|---|---|---|---|---|---|
| **A** | **Narrow-Easy 1b** (cross-constraint + tool_selection trace) | Dump cross-constraint result to block_telemetry + fix tool_execution step recording + add tool_selection step | ~20 | No | Run 5 (no_constraint) gets full evidence. Run 4 (no_graph) still PARTIAL — dependency evidence from reconciler.source_trace.p3 only |
| **B** | **Narrow-Full 1b** (A + dependency validation) | A + add `validate_tool_prerequisites()` call to `_execute_from_snapshot` | ~45 | **YES** (new blocking gate) | Run 4 + Run 5 both get full evidence. Risk of regression on shortcut-path success rates |
| **C** | **Narrow-Full with soft dependency** (A + dependency recording without blocking) | A + run `validate_tool_prerequisites()` but record result as warning, don't block execution | ~45 | No (recording only) | Run 4 gets evidence without behavior change. Dependency violations still recorded but don't prevent execution |
| **D** | **No 1b** (accept partial evidence) | None | 0 | No | Run 4/5 use reconciler.source_trace.p3 + clarification_telemetry.stage3_normalizations as partial evidence. Accept limitation |

### Recommendation: Option C (Narrow-Full with soft dependency)

Option C provides the most complete Phase 9.3 evidence without governance behavior regression:
- Cross-constraint evidence: from executor's standardization engine dump (guaranteed to run)
- Dependency evidence: from `validate_tool_prerequisites()` called as a check-only (record, don't block)
- Tool execution recording: fix the trace=None guard so existing code works
- Tool selection recording: add step showing which tool was selected

**Wait:** Prior to recommending, note that Option C requires calling `validate_tool_prerequisites()` which takes `(tool_name, available_results)` and returns a validation result. The `available_results` must be populated from session context. On the shortcut path, the session context is populated by `_execute_from_snapshot` at line 755 (`self.inner_router._ensure_context_store().clear_current_turn()`) and line 764 (`self.inner_router._save_result_to_session_context()`). At the point before `executor.execute()` (line 756), the available_results may be empty (context was just cleared at line 755). So `validate_tool_prerequisites()` would check against an empty result set and always report "all prerequisites missing" — which is technically correct for a fresh session but provides limited ablation value (the absence of prerequisite results IS the evidence for Run 4).

This is a nuance the user needs to consider when choosing.

---

## Section 6: STOP Checklist

| Condition | Triggered? | Detail |
|---|---|---|
| 1. Contract/check inconsistency with audit Task 6 | **No** | NaiveRouter and GovernedRouter are properly isolated. No cross-contamination found. |
| 2. Check ran but result immediately discarded | **Partial** | Cross-constraint result in `exec_trace["cross_constraint_validation"]` is not propagated to trace.block_telemetry. Not "swallowed by try/except" — it's accessible in the returned dict, just not dumped. |
| 3. Third shortcut path not identified | **No** | Only two paths found: `_consume_decision_field` (line 924) and `_maybe_execute_from_snapshot` (line 641). The idempotency pre-check at line 320 is a pre-dispatch gate, not a separate execution path. |
| 4. All indirect evidence also empty | **No** | stage3_normalizations, reconciled_decision, source_trace.p3 all present on all 9 shortcut trials. |
| 5. Mismatch with audit Task 7 | **No** | Dependency check at router.py:8811/9305/10763 confirmed; cross-constraint at standardization_engine.py:641 confirmed. File locations match audit expectations. |

**No STOP conditions triggered.** Report complete, ready for user review.
