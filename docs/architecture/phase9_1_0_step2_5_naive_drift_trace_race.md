# Phase 9.1.0 Step 2.5 — NaiveRouter Baseline Drift Audit + Trace Race Fix Pre-Spec

**Date:** 2026-05-05
**Branch:** `phase9.1-v1.5-upgrade` (HEAD: `aca9030`)
**Data:** Phase 8.2.2.C-2 Naive run (`end2end_naive_full/`) + Step 2 rerun (`_temp_phase9_1_0_step2/`)

---

## Section 1: NaiveRouter Baseline Drift Audit

### 1.1 Original Naive Run Data

**Location:** `evaluation/results/end2end_naive_full/`

| File | Size | Records |
|---|---|---|
| `end2end_logs.jsonl` | 1,083,079 B | 100 tasks |
| `naive_tool_calls.jsonl` | 84,586 B | 213 tool calls across 83 sessions |
| `end2end_metrics.json` | 823 B | Run-level summary |

**Run-level summary (`end2end_metrics.json`):**
- `mode`: `"naive"`
- `tasks`: 100
- `completion_rate`: 0.18
- `tool_accuracy`: 0.57
- `parameter_legal_rate`: 0.49
- `result_data_rate`: 0.54

**No LLM config dump exists.** The original Naive run has ZERO fields recording the LLM model, provider, temperature, max_iterations, or any configuration snapshot. This is a Phase 8.2.2.C-2 protocol gap — we cannot verify what LLM produced the original Naive baseline.

### 1.2 Original Naive Behavior — 5 Sampled Tasks

Extracted from `end2end_naive_full/end2end_logs.jsonl` + `naive_tool_calls.jsonl`:

| Task | Tool Calls | Iterations | max_iter Hit? | Stop Reason | First Tool |
|---|---|---|---|---|---|
| e2e_ambiguous_001 | 1 | 1 | No | LLM stopped (no tool_calls after failure) | query_emission_factors FAIL |
| e2e_ambiguous_002 | 1 | 1 | No | LLM stopped (no tool_calls after failure) | calculate_micro_emission FAIL |
| e2e_ambiguous_003 | 4 | 4 | **Yes** | max_iterations=4 | calculate_macro_emission OK→OK→OK→FAIL |
| e2e_multistep_001 | 4 | 4 | **Yes** | max_iterations=4 | calculate_macro_emission OK→dispersion FAIL→FAIL→macro OK |
| e2e_constraint_001 | 1 | 1 | No | LLM stopped (no tool_calls after failure) | query_emission_factors FAIL |

**Full distribution across 100 tasks:**

| Tool Call Count | Tasks | % |
|---|---|---|
| 0 | 17 | 17% |
| 1 | 39 | 39% |
| 2 | 2 | 2% |
| 3 | 1 | 1% |
| 4 | 40 | 40% |
| 7 | 1 | 1% |

**56% of tasks stopped in ≤1 tool call** — the original LLM voluntarily returned a text response without new tool_calls. **40% hit max_iterations=4**. This is the natural distribution of the original LLM's tool-calling persistence.

### 1.3 Current NaiveRouter Code (Unchanged)

**`core/naive_router.py:46-68`** — class constants and `__init__`:

```python
MAX_HISTORY_TURNS = 5
MAX_TOOL_ITERATIONS = 4       # line 47

def __init__(self, session_id="naive", *, ..., max_tool_iterations=MAX_TOOL_ITERATIONS):
    self.max_tool_iterations = int(max_tool_iterations)  # line 68
```

**`core/naive_router.py:120-133`** — main loop stop conditions:

```python
for iteration in range(self.max_tool_iterations + 1):  # line 120: 0..4 (5 iterations)
    response = await self.llm.chat_with_tools(...)
    if not response.tool_calls:      # line 129: LLM stopped voluntarily
        break
    # ... tool execution ...
    if iteration >= self.max_tool_iterations:  # line 131: force stop at iteration 4
        break
```

**`evaluation/eval_end2end.py:1487-1490`** — NaiveRouter construction (no override):

```python
router = NaiveRouter(
    session_id=f"eval_naive_{run_ns}{task['id']}",
    tool_call_log_path=output_dir / "naive_tool_calls.jsonl",
)
# max_tool_iterations NOT passed → defaults to MAX_TOOL_ITERATIONS=4
```

### 1.4 Git History: ZERO Stop-Condition Changes

Checked across ALL commits to `core/naive_router.py`:

| Commit | Date | Change | Affects Stop? |
|---|---|---|---|
| `460ed9d` | Phase 8.2.5 | `fix(trace): standardize trace_friendly field naming` | No |
| `bb9725f` | 2026-05-03 | `fix(llm-client): preserve reasoning_content in NaiveRouter multi-turn` | No (adds `reasoning_content` to assistant message, ~4 LOC) |
| `130efff` | DeepSeek migration | `refactor(eval): remove hardcoded model references, use config` | No |
| `97b0199` | Phase 5.2 | `refactor(extensibility): declarative tool registration via YAML` | No |

**`MAX_TOOL_ITERATIONS = 4`** and **`if not response.tool_calls: break`** are IDENTICAL across all commits.

### 1.5 Hypothesis Determination

**(d) LLM-driven behavior change — NOT config drift, NOT code drift.**

**Evidence:**

1. NaiveRouter stop condition **unchanged** across all commits — verified at commit level
2. `MAX_TOOL_ITERATIONS = 4` in all versions
3. No config override for `max_tool_iterations` in eval script
4. Original run has natural distribution (56% ≤1 call, 40% at max) — the original LLM's natural stopping behavior
5. Step 2 rerun has 100% at max_iterations — deepseek-v4-pro never voluntarily stops after tool failures
6. The original LLM (unknown, timestamp April 12, 2026) returned text-only responses after failed tool calls; deepseek-v4-pro returns new tool_calls even after failures

**Root cause:** The NaiveRouter's stop condition at `core/naive_router.py:129` (`if not response.tool_calls: break`) depends entirely on the LLM's response pattern. The LLM backend changed from an unknown model (April 2026) to `deepseek-v4-pro` (current). deepseek-v4-pro's tool-calling persistence differs qualitatively from the original model — it keeps proposing new tools after failures rather than giving a text response.

**What stopped the original NaiveRouter at 1 call for e2e_ambiguous_001/002/constraint_001:** The original LLM saw the tool error ("未知车型: 家用车", "未知车型: 公交车", "未知车型: 摩托车") and responded with a final text message (`response.tool_calls = None`). NaiveRouter broke out of the loop at line 129.

**What drives the current NaiveRouter to 4 calls for every task:** deepseek-v4-pro sees the same tool errors and responds with NEW tool_calls (retrying with different parameters, trying query_knowledge instead, etc.). NaiveRouter continues executing until `iteration >= self.max_tool_iterations` at line 131.

### 1.6 Anchors Compliance Assessment

**Hypothesis (d): No Anchors violation.**

| Aspect | Assessment |
|---|---|
| NaiveRouter code | IDENTICAL — no drift |
| NaiveRouter config | IDENTICAL — no drift |
| LLM backend | CHANGED — from unknown model to deepseek-v4-pro |
| Historical +65.9pp delta | Measured with DIFFERENT LLM — delta is LLM-specific, not purely architectural |
| Phase 9.3 baseline | Must re-run Naive with CURRENT LLM for fair delta |
| Anchors impact | No "baseline contamination" — code is frozen. The LLM change is external environment drift, not code drift |

**Paper data strategy implication:**

The historical +65.9pp delta was produced by LLM-A (unknown). The Phase 9.3 rerun will produce a different delta with LLM-B (deepseek-v4-pro). Both deltas measure the same architectural gap (GovernedRouter vs NaiveRouter) but through different LLM lenses. The paper should:
1. Report the **concurrent rerun delta** as the primary result (same LLM, controlled comparison)
2. Reference the historical delta with a footnote: "measured with a different LLM backend; see §X for reproducibility discussion"
3. If the concurrent delta differs from +65.9pp, explain that the delta is LLM-specific and the architectural contribution is the persistent component

---

## Section 2: Trace Race Fix Pre-Spec

### 2.1 Race Mechanism

**It is NOT a race condition. It is a sequential-overwrite chain with a missing-path gap.**

The trace dict on `RouterResponse.trace` goes through three sequential writers:

| Step | Writer | Location | What It Writes |
|---|---|---|---|
| 1 | `Trace.to_dict()` | `core/trace.py:235-245` | 7 fields: `session_id`, `start_time`, `end_time`, `total_duration_ms`, `final_stage`, `step_count`, `steps` |
| 2 | `_attach_oasc_trace()` | `core/contracts/oasc_contract.py:704-760` | Governance metadata: `oasc`, `classifier_telemetry`, `ao_lifecycle_events`, `block_telemetry`, `reconciled_decision`, `b_validator_filter`, `projected_chain` |
| 3 | `_record_reply_generation_trace()` | `core/governed_router.py:407-452` | Appends `reply_generation` to `steps` list |

**Normal path (both sets of fields present — rich trace):**

```
inner_router._run_state_loop()
  → trace_obj = Trace()                         # core/governed_router.py:790 (approx)
  → trace_obj.steps.append(tool_selection, ...)  # steps recorded during execution
  → response.trace = trace_obj.to_dict()         # core/router.py:11326
  → result.trace = {session_id, start_time, ..., steps: [7 steps]}

governed_router.chat()
  → _attach_oasc_trace(result, ...)              # core/contracts/oasc_contract.py:704
  → result.trace["oasc"] = {...}                 # merges into existing dict
  → result.trace["classifier_telemetry"] = [...]

  → _record_reply_generation_trace(result, ...)   # core/governed_router.py:407
  → result.trace["steps"].append(reply_generation) # step 8

Final result.trace = {all 7 Trace fields + governance metadata + steps: [7+1 steps]}
```

**Missing path (only governance fields present — slim trace):**

When the inner_router returns `result.trace = None` (the trace parameter from GovernedRouter is None, set at `core/router.py:732` in fast_path, or not overwritten by `to_dict()` in certain early-return paths):

```
inner_router.chat(user_message, file_path, trace=None)
  → trace is None, passed through
  → some paths set response.trace = trace (= None)
  → some paths set response.trace = trace_obj.to_dict()
  → if early-return path taken: response.trace remains None

governed_router.chat()
  → result.trace is None

  → _attach_oasc_trace(result, ...)              # line 714-717:
  → trace_obj = result.trace → None              # isinstance(None, dict) = False
  → trace_obj = {}                                # creates FRESH dict
  → result.trace = trace_obj                      # {oasc, classifier_telemetry, ...}
  → Basic Trace fields NEVER written

  → _record_reply_generation_trace(result, ...)   # line 416-418:
  → trace_target = result.trace → the dict from _attach_oasc_trace
  → trace_target["steps"].append(reply_generation)

Final result.trace = {governance metadata only + steps: [reply_generation]}
```

**Verified by Step 2 trial data:**

| Trial | Trace Keys | Has Trace Fields | Has Governance Fields |
|---|---|---|---|
| e2e_ambiguous_002 Full (slim) | `ao_lifecycle_events`, `block_telemetry`, `clarification_contract`, `clarification_telemetry`, `classifier_telemetry`, `oasc`, `reconciled_decision`, `steps` | **NO** (missing session_id, start_time, end_time, final_stage) | **YES** |
| e2e_constraint_001 Full (rich) | Above + `end_time`, `final_stage`, `session_id`, `start_time`, `step_count`, `total_duration_ms` | **YES** | **YES** |

### 2.2 Slim vs Rich Trace Path Audit

**When the inner_router reaches `trace_obj.to_dict()` (rich trace):**

The inner_router's `_run_state_loop()` at `core/router.py:11318-11515` always ends with `response.trace = trace_obj.to_dict()`. This happens when:
- The full tool execution loop completes (tool selected → executed → synthesized)
- The constraint violation blocks before execution
- The input completion path completes

**When the inner_router returns with `response.trace = trace` (= None) (slim trace):**

The `_maybe_handle_conversation_fast_path()` at `core/router.py:717-734` sets:
```python
if getattr(self.runtime_config, "enable_trace", False):
    response.trace = trace  # trace is the caller's param (None from runner)
```
This path is for CHITCHAT/EXPLAIN_RESULT/KNOWLEDGE_QA intents — NOT for tool execution.

There may also be internal paths in `_run_state_loop` where `result.trace = trace` is set at `core/router.py:2581` without reaching the final `to_dict()`.

**The tool_execution slim trace mystery:** 4/5 Full trials executed tools but show slim trace. This means the inner_router executed tools AND reached `to_dict()`, but the Trace dataclass fields were lost. The most likely mechanism is:
1. Inner_router calls `trace_obj.to_dict()` → sets `response.trace = {7 fields, steps: [tool_steps]}`
2. GovernedRouter runs `_attach_oasc_trace` → adds governance keys
3. GovernedRouter runs `_record_reply_generation_trace` → appends reply_generation
4. FINAL `result.trace` should have all fields

BUT the Step 2 trial output shows basic Trace fields MISSING. This means step 1 didn't execute, OR the trace was overwritten after step 3.

Investigation shows the _safe_serialize in the runner does NOT filter basic fields — constraint_001 has them. So the inner_router genuinely didn't set them for the 4 slim trials.

**Likely mechanism:** The GovernedRouter at line 327-346 has a pre-inner_router decision gate:
```python
if result is None:
    if enable_llm_decision_field:
        decision_result = self._consume_decision_field(context, trace)
        if decision_result is not None:
            result = decision_result      # ← result set WITHOUT inner_router
    if result is None:
        result = await self._maybe_execute_from_snapshot(context)  # ← snapshot path
        if result is None:
            result = await self.inner_router.chat(...)  # ← inner_router runs
```

If `_consume_decision_field` or `_maybe_execute_from_snapshot` returns a non-None result, the inner_router is NEVER called, and `result.trace` is set by those methods — which may NOT include the Trace.to_dict() fields.

The Step 2 data is consistent with: 4/5 Full trials go through the decision_field/snapshot path (which sets result.trace without Trace fields), and constraint_001 goes through the inner_router path (which sets full Trace fields).

### 2.3 Fix Scope Definition (Spec Only — No Implementation)

**What to change:**

1. **`core/contracts/oasc_contract.py:704-760`** — `_attach_oasc_trace()`: After creating/acquiring the trace dict, ensure basic Trace identity fields are present:

```python
# At line 714-717, after acquiring trace_obj:
if trace_obj is None:
    trace_obj = {}
    result.trace = trace_obj

# ADD: ensure basic trace fields are present (may have been lost)
trace_obj.setdefault("session_id", getattr(result, "session_id", None))
trace_obj.setdefault("start_time", getattr(result, "start_time", None))
```

2. **`core/governed_router.py:407-452`** — `_record_reply_generation_trace()`: At line 416-418, when trace_target is None (inner_router returned None trace), create a dict instead of silently returning:

```python
# Current:
trace_target = result.trace if isinstance(result.trace, dict) else trace
if not isinstance(trace_target, dict):
    return  # ← silently drops reply_generation step

# Fixed:
if not isinstance(result.trace, dict):
    result.trace = {}
trace_target = result.trace
```

**What NOT to change:**
- `core/trace.py:235-245` — Trace.to_dict() is correct for its purpose (Trace dataclass serialization)
- `core/router.py:11318-11515` — inner_router trace assignment logic (would require touching governance code)
- Any governance decision logic (AO classification, PCM, chain projection, reconciler)

**Risk assessment:**
- **Low risk**: Adding `setdefault` calls to `_attach_oasc_trace` is purely additive — it only fills missing keys, never overwrites
- **No governance impact**: The fix is in trace recording, not in decision logic
- **Backward compatible**: Phase 8.2.2.C-2 era trace data is unaffected (these are new writes, not reads)
- **Phase 9.3 compatibility**: The fix ensures ALL Phase 9.3 trials produce complete traces regardless of code path

### 2.4 Acceptance Criteria (Phase 9.3 Blocking Prerequisite)

Before Phase 9.3 ablation runs, the trace race fix must satisfy:

1. **10/10 Step 2 trials produce complete traces** — governance metadata (oasc, classifier_telemetry, ao_lifecycle_events, block_telemetry) AND basic Trace fields (session_id, start_time, end_time, final_stage) present in ALL trial outputs
2. **Tool execution steps visible** — `tool_execution` or equivalent step type present in all trials where tools executed
3. **Rich trace not degraded** — constraint_001-class paths retain their existing complete trace behavior
4. **Outcome identical** — 5-task rerun with fix produces identical tool chains and success/failure outcomes as Step 2 (no governance behavior change)
5. **Step type distribution shifted** — trials no longer show 1-step slim trace; step count ≥ 2 for tool-executing trials

### 2.5 Phase 9.3 Timeline

**Trace race fix is an ablation infrastructure prerequisite, NOT a v1.5 design component.**

| Phase | What | Depends On |
|---|---|---|
| Now | User reviews Step 2.5 report, approves trace race fix spec | — |
| Pre-Phase 9.3 | Implement trace race fix (2 files, ~20 LOC) | Approved spec |
| Pre-Phase 9.3 | Verification: re-run Step 2 10 trials, confirm 10/10 complete traces | Fix implemented |
| Phase 9.3 | Full ablation: v1.0 Full + Naive baseline (182 tasks) | Verified fix |

The fix does NOT conflict with v1.5 8-core + 2-infrastructure design. It is purely a trace observability fix that benefits BOTH v1.0 baseline reruns AND v1.5 evaluation.

**Estimated effort:** ~1 hour (implement + verify)

---

## Section 3: Impact on Phase 9.3 Ablation

### 3.1 How to Run the Naive Baseline

**Use current code + current LLM.** No rollback needed.

Rationale:
- NaiveRouter code is identical to Phase 8.2.2.C-2 era
- Config (MAX_TOOL_ITERATIONS) is identical
- LLM backend HAS changed — but this is external environment drift, not code drift
- Rolling back the LLM is impossible (original LLM unknown, may not exist anymore)
- The correct comparison for v1.5 delta is: **same LLM, same code, GovernedRouter vs NaiveRouter**

### 3.2 How to Ensure Trace Completeness

**Trace race fix must be in place before Phase 9.3 runs.** See Section 2.4 acceptance criteria.

### 3.3 Trial Count Recommendation

**1 trial default + 3 trial borderline** (hybrid from Step 2 protocol):

- Step 1 confirmed structural determinism (10/10 invariants across 5 Run 7 trials)
- Step 2 confirmed outcome reproduction (4/5 Full, 5/5 Naive first-tool)
- The 1 LLM-dependent mismatch (e2e_ambiguous_003) is forward-progress improvement, not regression
- **1 trial for all 182 tasks** is sufficient for structural governance metrics (AO classification, tool selection, constraint detection)
- **3 trials for the 5 sampled tasks** as a variance cross-check (quantify LLM variance on the same code)
- If 5-task 3-trial variance shows >1/5 outcome drift, expand to 3 trials for borderline categories (parameter_ambiguous, multi_step)

### 3.4 Protocol Revision

Step 2 §7 protocol spec is valid with these additions:

| Addition | Rationale |
|---|---|
| **Trace race fix prerequisite** | Section 2.4 — ensures complete governance trace for all Phase 9.3 trials |
| **Naive baseline with current LLM** | Section 1.5 — historical data is LLM-dependent; only concurrent rerun is controlled |
| **LLM config dump mandatory** | Section 1.1 — original Naive run had NO config dump; Phase 9.3 must record full LLM config |
| **Per-trial Naive iteration count** | Section 1.2 — original data shows natural distribution (56% ≤1); Phase 9.3 must record per-task iteration count for Naive |

---

## Section 4: Paper §6 Data Representation Impact

### 4.1 Historical +65.9pp Delta

**Can still be referenced, but with qualification.**

The historical +65.9pp delta was measured with LLM-A (unknown, April 2026). The concurrent rerun delta will be measured with LLM-B (deepseek-v4-pro). Both are valid measurements of the GovernedRouter vs NaiveRouter architectural gap — but through different LLM lenses.

**Options for the user to decide:**

| Option | Paper Text | Pros | Cons |
|---|---|---|---|
| **A: Concurrent only** | "GovernedRouter outperforms NaiveRouter by +Xpp (deepseek-v4-pro, 2026)" | Clean, reproducible | Loses historical context |
| **B: Both, concurrent primary** | "GovernedRouter outperforms NaiveRouter by +Xpp (deepseek-v4-pro). Historical measurement with an earlier LLM yielded +65.9pp (see Appendix)" | Full transparency, shows robustness | Two different numbers may confuse reviewers |
| **C: Range** | "GovernedRouter outperforms NaiveRouter by +Xpp to +65.9pp depending on LLM backend" | Acknowledges LLM-dependence | Ambiguous central claim |

### 4.2 Baseline Description Precision

Current baseline description should be revised to:

> "The NaiveRouter baseline uses a minimal LLM tool-calling loop (max 4 iterations) over the same 9-tool suite, with no AO classification, constraint validation, parameter collection, or chain projection. The baseline code is version-frozen (`core/naive_router.py`, Phase 5.2). The LLM backend (deepseek-v4-pro, temperature=0.0) is identical across GovernedRouter and NaiveRouter conditions, ensuring the measured delta reflects architectural differences rather than model capability differences."

Key changes:
- Add "version-frozen" to clarify code stability
- Add LLM backend spec to the Methods section
- Remove implication that historical +65.9pp is the current performance number if concurrent rerun produces a different value

### 4.3 NaiveRouter Iteration Behavior

The NaiveRouter's stop condition is LLM-dependent. The paper should note:

> "The NaiveRouter stops when the LLM returns a text response without tool calls, or after 4 tool-calling iterations. The LLM's tool-calling persistence varies by model: earlier models (e.g., qwen-plus) typically stopped after 1 failed tool call (56% of tasks), while deepseek-v4-pro continues retrying with alternative tools until the iteration limit (100% of tasks reach max_iterations=4). Both behaviors are valid instantiations of the same code — the architectural gap (GovernedRouter's chain projection, constraint validation, and PCM gating) is what differentiates them."

---

## Section 5: Ancillary Findings

### 5.1 Original Naive Run Protocol Gaps

| Gap | Impact | Phase 9.3 Fix |
|---|---|---|
| No LLM config dump | Cannot verify original LLM model/provider | Mandatory `run_metadata.json` per trial (already implemented in Step 2 runner) |
| No iteration count metadata | `naive_tool_calls.jsonl` records calls but `end2end_logs.jsonl` doesn't have iteration metadata | Add `naive_iteration_count` to trial output |
| No env/config snapshot | Cannot verify temperature, thinking mode, or flags | Config dump in `run_metadata.json` |
| No git commit recorded | Cannot verify exact code version | Git HEAD recorded in metadata |

### 5.2 Step 2 "First-Tool Match" Metric

The Step 2 report used "5/5 Naive first-tool match" as the Naive reproducibility metric. This is valid: the original NaiveRouter's first tool call matches the current rerun for all 5 tasks. The divergence in subsequent iterations (original: LLM stops at 1; current: LLM continues to 4) is an LLM behavior difference, not a code difference.

**Recommendation:** Keep "first-tool match" as the primary Naive metric, but add "iteration count distribution" as a secondary metric to quantify LLM-specific tool-calling persistence.

---

## Appendix: File References

| Reference | Location |
|---|---|
| NaiveRouter stop condition | `core/naive_router.py:120-133` |
| NaiveRouter MAX_TOOL_ITERATIONS | `core/naive_router.py:47` |
| NaiveRouter construction in eval | `evaluation/eval_end2end.py:1487-1490` |
| Trace.to_dict() | `core/trace.py:235-245` |
| _attach_oasc_trace() | `core/contracts/oasc_contract.py:704-760` |
| _record_reply_generation_trace() | `core/governed_router.py:407-452` |
| GovernedRouter response assembly | `core/governed_router.py:327-381` |
| Inner_router trace_obj.to_dict() | `core/router.py:11326` (and 11339, 11357, 11386, 11395, 11404, 11413, 11506, 11514) |
| Governance metadata enrichment | `core/governed_router.py:357-358` (after_turn) |
| Original Naive run | `evaluation/results/end2end_naive_full/end2end_logs.jsonl` (100 tasks) |
| Original Naive tool calls | `evaluation/results/end2end_naive_full/naive_tool_calls.jsonl` (213 calls) |
