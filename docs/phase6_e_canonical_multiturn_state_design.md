# Phase 6.E — Canonical Multi-Turn Execution State Design

## Baseline and Problem Statement

### Baseline commits
- Phase 5.3 A/B/E narrow closed: `47da89b`
- Phase 6.1 AO-scoped idempotency closed: `e35170d`
- Tag: `phase5.3-phase6.1-closed`

### What is solved
- **Phase 5.3 E narrow**: Chain handoff macro→dispersion is preserved across turns. Dispersion is attempted in single-task verification. Chain overwrite by single-tool intent is blocked. Pending queue replacement validates tool membership in projected_chain.
- **Phase 6.1**: Inter-AO duplicates (same tool, same effective-params after an AO completed) are blocked. Task 105 is full PASS. Rerun signals, true revisions, and active chain continuation are preserved.

### What is NOT solved (this design addresses)
1. **Intra-AO duplicate execution**: Same tool called multiple times within one AO (Task 120: 3 macro calls). Phase 6.1 pre-dispatch gate only fires when `tool_call_log` is empty. The executor wrapper does not intercept the `inner_router.chat()` fallback path.
2. **Chain state instability under eval**: While single-task verification shows chain working, the 180-task sanity shows macro repeating and dispersion missing in some eval runs. The chain state is scattered across four data structures with no single authoritative source.
3. **No canonical distinction** between: no-op follow-up, true revision, explicit rerun, and downstream chain continuation. These four intents all map to different governance behaviors but share overlapping detection logic.
4. **No skip/completion tracking**: `tool_call_log` records what was *executed*, not what was *skipped* (idempotent) or *failed*. The system cannot answer "what is the state of this chain?"
5. **Revision-aware chain invalidation**: When a user revises parameters mid-chain (e.g., change pollutant after macro before dispersion), the downstream chain should be invalidated — currently there is no mechanism for this.

### Non-goals (explicit)
- Do NOT fix dispersion spatial geometry / WKT / GeoJSON / coordinate data-flow.
- Do NOT change evaluator scoring.
- Do NOT redesign AO classifier.
- Do NOT modify tools, calculators, or PCM.
- Do NOT add a generic cache layer.
- Do NOT claim benchmark success.
- Do NOT paper-frame unresolved design debt.

---

## Current State Model Audit

### Where execution state lives today

| Location | What it holds | Issues |
|---|---|---|
| `AO.tool_intent.projected_chain` | LLM-predicted tool sequence (e.g., `["calculate_macro_emission", "calculate_dispersion"]`) | Written once by intent resolver. Can be overwritten by unrelated single-tool intent. No invalidation on revision. |
| `ExecutionContinuation` (in `AO.metadata["execution_continuation"]`) | `pending_objective`, `pending_next_tool`, `pending_tool_queue`, `probe_count`, `abandoned` | Opaque dict storage. No direct relationship to tool_call_log. Must be manually synced by OASC, ExecutionReadinessContract, and GovernedRouter. |
| `AO.tool_call_log` (`List[ToolCallRecord]`) | Flat list of executed tool calls with args_compact, success, result_ref, summary | No distinction between "executed", "skipped" (idempotent), or "failed". No chain position info. Flat list loses ordering relative to projected_chain. |
| `AO.parameters_used` (`Dict[str, Any]`) | Accumulated parameter fills across turns | Key-value store only. No provenance (which turn filled what). No linkage to specific tool executions. |
| `context.metadata["clarification"]["direct_execution"]` | Snapshot-based execution trigger: `tool_name`, `parameter_snapshot`, `trigger_mode` | Transient — lives only in context metadata, not persisted on AO. Lost after turn completes. |
| `context.router_executed` (bool) | Whether inner_router.chat() was called this turn | Boolean flag only. No record of WHAT was executed. |
| `result.executed_tool_calls` | Tool calls returned in RouterResponse | Per-turn transient. Not accumulated. Can be `[]` (empty list) when tools were executed by inner_router directly. |
| `memory.fact_memory` tool logs | Memory-layer copies of tool results | Duplicates state. Not the authoritative source. |
| Phase 6.1 `check_execution_idempotency()` | Semantic fingerprints, three-tier AO search scope | Read-only check. Does not mutate state. Does not track skips in tool_call_log. |

### Overlap and inconsistency

1. **Three chain representations with no single source of truth:**
   - `AO.tool_intent.projected_chain` — the plan
   - `ExecutionContinuation.pending_tool_queue` — the remaining work
   - `AO.tool_call_log` — the completed work
   - These three must be kept consistent by hand. There is no function that reconciles them.

2. **Chain advancement is distributed across three locations:**
   - `OASCContract.after_turn` → `_refresh_split_execution_continuation()` advances queue
   - `ExecutionReadinessContract.before_turn` → `replace_queue_override` rebuilds queue
   - `ExecutionContinuationUtils.advance_tool_queue()` — pure function, no AO access
   - No single component is responsible for "after tool X succeeds, what happens to the chain?"

3. **Inner_router fallback bypasses governed governance:**
   - When contracts return `proceed=True` without snapshotted execution, `inner_router.chat()` is called directly (governed_router.py:240-244)
   - This path does NOT go through `_execute_from_snapshot()`, which has the Phase 6.1 idempotency gate
   - The `_IdempotencyAwareExecutor` wrapper wraps `executor.execute()` but `inner_router.chat()` may use a different execution path internally
   - Result: intra-AO tool calls via inner_router bypass the idempotency check

4. **No concept of "skipped" tool calls:**
   - Phase 6.1 marks idempotent skips in the result dict (`idempotent_skip: True`) and OASC skips them in `after_turn`
   - But `tool_call_log` never records skipped calls — so `has_produced_expected_artifacts()` cannot distinguish "executed successfully" from "skipped as duplicate"
   - The pre-dispatch gate returns `executed_tool_calls=[]` (empty), so OASC's `_refresh_split_execution_continuation` sees no executed tools and does not advance the chain

5. **Parameters used are not linked to tool executions:**
   - `AO.parameters_used` accumulates fills but doesn't record which turn or tool they apply to
   - When a revision changes a parameter mid-chain, there's no way to know which downstream tools are invalidated

---

## Task 120 Failure Reconstruction

### Why single-task Phase 5.3 E narrow can reach calculate_dispersion

In single-task verification (controlled turn sequence):
1. Turn 1 ("我需要扩散结果" + file): LLM outputs `projected_chain=["calculate_macro_emission", "calculate_dispersion"]`. Intent resolver writes chain. OASC creates AO. ERC proceeds with macro. `_execute_from_snapshot` runs macro. OASC after_turn writes `pending_next_tool=calculate_dispersion`.
2. Turn 2 ("先用这个路网算NOx"): Chain preserved (Fix 1). Stance=DIRECTIVE (continuation active). ERC proceeds with macro again (?!). Actually — this is the key question. Does Turn 2 re-execute macro or advance to dispersion?
3. Turn 3 ("windy_neutral"): Chain handoff intact (Fix 3). Dispersion attempted. Fails with spatial geometry debt.

### Why sanity/eval still sees macro repeats and no dispersion

Multiple interacting causes, any of which can break the chain:

1. **Intra-AO duplicate execution (primary cause):**
   - When `inner_router.chat()` is the fallback path (no snapshot execution), the inner_router's LLM may independently decide to call `calculate_macro_emission` again
   - The `_IdempotencyAwareExecutor` wrapper wraps `executor.execute()` but does not wrap `inner_router.chat()` — the inner router may have a different execution pipeline
   - Phase 6.1 pre-dispatch gate only fires on empty `tool_call_log` → intra-AO duplicates pass through
   - Result: 3 macro calls within one AO, dispersion never reached

2. **Chain state overwritten by LLM non-determinism:**
   - In eval runs, the LLM on Turn 2 may not output the same tool/chain as in single-task verification
   - The intent resolver can overwrite `projected_chain` with a single-tool intent if confidence is high enough
   - Fix 1 (Phase 5.3 E) guards against empty→non-empty and multi→single degradation, but the guard depends on what the LLM returns

3. **OASC after_turn ordering issue:**
   - When `executed_tool_calls` is empty (e.g., pre-dispatch idempotency block), `_refresh_split_execution_continuation` sees no executed tools
   - Chain is NOT advanced → stuck at `pending_next_tool` from previous turn
   - Next turn: same tool proposed again → macro repeats

4. **continuation queue replacement race:**
   - `replace_queue_override` (ERC line 198-214) only triggers when `pending_next_tool in projected_chain`
   - If the new `projected_chain` doesn't contain the pending tool, the override is a no-op
   - But the existing continuation may be stale — no mechanism to detect "chain is no longer reachable"

5. **Evaluator/scripted-turn behavior:**
   - The eval runner drives turns programmatically. Non-deterministic LLM responses can cause different tool selections run-to-run.
   - Not a code bug per se, but the system has no mechanism to "commit" to a chain and resist LLM drift.

### Root cause summary

The root cause is not one bug but a structural gap: **there is no canonical execution state that binds the planned chain, the executed steps, the skipped steps, and the pending work into one coherent model.** Each component (ERC, OASC, GovernedRouter, AOManager) maintains its own partial view and tries to keep them consistent through ad-hoc synchronization.

---

## Design Goals and Non-Goals

### Goals
1. **Single canonical execution state model** — one data structure that owns chain plan, execution log, skip log, failure log, and pending work.
2. **Intra-AO duplicate suppression** — same tool with same effective params within one AO should not execute twice.
3. **Chain cursor / downstream handoff stability** — after tool N succeeds, the system reliably knows tool N+1 is next, regardless of LLM non-determinism on subsequent turns.
4. **Revision-aware chain invalidation** — when a user revises a parameter that a completed upstream tool depends on, downstream pending tools are invalidated.
5. **Separate no-op follow-up, true revision, rerun, and downstream continuation** — each intent has distinct governance behavior.
6. **Minimal change to existing contracts** — the canonical state should be consumed at well-defined boundaries, not scattered across every contract.

### Non-Goals (repeated for emphasis)
- No dispersion geometry fix
- No evaluator scoring change
- No AO classifier redesign
- No tool/calculator changes
- No PCM redesign
- No generic cache layer
- No benchmark claims

---

## Proposed Canonical Execution State Model

### `AOExecutionState` (new dataclass in `core/analytical_objective.py`)

```python
@dataclass
class ExecutionStep:
    """One step in the execution chain."""
    tool: str
    status: str                    # "pending" | "executing" | "completed" | "skipped" | "failed"
    effective_args: Dict[str, Any] # semantic fingerprint args
    result_ref: Optional[str]      # context_store key (e.g., "macro_emission:baseline")
    executed_at_turn: Optional[int]
    failure_reason: Optional[str]
    idempotent_skip: bool          # True if this step was skipped via idempotency
    skip_matched_step_index: Optional[int]  # index of the completed step this skip matched

@dataclass
class AOExecutionState:
    """Canonical multi-turn execution state for one AnalyticalObjective."""
    objective_id: str
    planned_chain: List[str]               # immutable after first tool execution (unless revision)
    chain_cursor: int                       # index into planned_chain (0-based)
    steps: List[ExecutionStep]              # ordered execution log
    revision_epoch: int                     # incremented on true revision
    last_updated_turn: Optional[int]

    # Derived / convenience
    @property
    def pending_steps(self) -> List[ExecutionStep]:
        return [s for s in self.steps if s.status == "pending"]

    @property
    def completed_steps(self) -> List[ExecutionStep]:
        return [s for s in self.steps if s.status == "completed"]

    @property
    def skipped_steps(self) -> List[ExecutionStep]:
        return [s for s in self.steps if s.status == "skipped"]

    @property
    def failed_steps(self) -> List[ExecutionStep]:
        return [s for s in self.steps if s.status == "failed"]

    @property
    def pending_next_tool(self) -> Optional[str]:
        pending = self.pending_steps
        return pending[0].tool if pending else None

    @property
    def current_tool(self) -> Optional[str]:
        if 0 <= self.chain_cursor < len(self.planned_chain):
            return self.planned_chain[self.chain_cursor]
        return None

    @property
    def is_chain_complete(self) -> bool:
        return all(s.status in ("completed", "skipped") for s in self.steps)

    def active_tool_matches(self, tool_name: str) -> bool:
        """Is tool_name the expected next step in the chain?"""
        return self.current_tool == tool_name
```

### Key design decisions

1. **`steps` is the single source of truth.** It replaces the trio of `tool_call_log`, `pending_tool_queue`, and `projected_chain` for execution tracking. `tool_call_log` continues to exist for backward compatibility (AO serialization, `has_produced_expected_artifacts()`) but is derived from `steps` rather than independently maintained.

2. **`chain_cursor` points to the current position.** After step N completes, cursor advances to N+1. The cursor is the authoritative "what's next" — no separate `pending_next_tool` field that can drift.

3. **Skip steps are first-class.** When idempotency blocks a tool, a `status="skipped"` step is appended (with `idempotent_skip=True`). This means the chain can advance through a skipped step without losing the audit record.

4. **`revision_epoch` enables invalidation.** When a true revision is detected, `revision_epoch += 1`. Downstream pending steps with `epoch < current_epoch` are invalidated (status → `"pending"` with cleared args).

5. **Existing `ExecutionContinuation` is NOT removed in Phase 6.E.** It continues to serve parameter-collection flows (`PARAMETER_COLLECTION`). The `CHAIN_CONTINUATION` objective is migrated to `AOExecutionState`. A compatibility bridge derives `ExecutionContinuation` from `AOExecutionState` for consumers that still read it.

---

## Component Ownership

| Component | Owns | Rationale |
|---|---|---|
| **AOExecutionState** (data) | Canonical chain plan + execution log | Single source of truth |
| **AOManager** | State transitions, step append, chain advancement, revision invalidation | Already owns AO lifecycle; execution state is a natural extension |
| **ExecutionReadinessContract** | Reads chain state to determine "what tool next?" and whether to proceed or clarify | Already the pre-execution gate; should consume canonical state instead of reconstructing from continuation |
| **OASCContract after_turn** | Reads `result.executed_tool_calls` to advance chain cursor | Already the post-execution sync point; should call AOManager to advance chain |
| **GovernedRouter pre-dispatch** | Reads chain state for intra-AO idempotency decisions | Phase 6.1 gate already exists; extends to intra-AO scope |
| **IntentResolver** | Writes initial `planned_chain` to AOExecutionState | Already resolves tool intent; writes chain plan once |
| **ExecutionContinuation** (existing) | Retained for PARAMETER_COLLECTION flows only | Parameter collection is a separate concern from chain execution |

### What changes and what stays

| Structure | Fate |
|---|---|
| `AO.tool_call_log` | **Kept** — derived from `AOExecutionState.steps` (filtered to completed + skipped). Backward compat for serialization and `has_produced_expected_artifacts()`. |
| `AO.tool_intent.projected_chain` | **Kept** — used by intent resolver. After first execution, `AOExecutionState.planned_chain` is the authoritative copy; `projected_chain` becomes a write-once hint. |
| `ExecutionContinuation.pending_next_tool` | **Deprecated for chain** — replaced by `AOExecutionState.pending_next_tool`. Kept for PARAMETER_COLLECTION. |
| `ExecutionContinuation.pending_tool_queue` | **Deprecated** — replaced by `AOExecutionState.steps` filtered to pending. |
| `context.metadata["clarification"]["direct_execution"]` | **Kept** — unchanged. It's the trigger; canonical state is the recorder. |
| `context.router_executed` | **Kept** — unchanged. |

---

## Transition Rules

### 1. New AO with single tool
```
planned_chain = [tool_name]
chain_cursor = 0
steps = [ExecutionStep(tool=tool_name, status="pending")]
```
ERC reads `current_tool == tool_name`, proceeds to execution.

### 2. New AO with multi-step chain
```
planned_chain = ["calculate_macro_emission", "calculate_dispersion"]
chain_cursor = 0
steps = [
    ExecutionStep(tool="calculate_macro_emission", status="pending"),
    ExecutionStep(tool="calculate_dispersion", status="pending"),
]
```

### 3. Parameter collection before first execution
No change to current flow. ERC continues to handle parameter collection via `ExecutionContinuation(PARAMETER_COLLECTION)`. The pending ExecutionStep accumulates `effective_args` as parameters are filled.

### 4. First tool success
```
step[0].status = "completed"
step[0].result_ref = "macro_emission:baseline"
step[0].executed_at_turn = current_turn
step[0].effective_args = {vehicle_type: "Light Duty", pollutant: "NOx", ...}
chain_cursor = 1
```
OASC after_turn calls `ao_manager.advance_chain(ao, executed_tool, result_ref)`.

### 5. Downstream tool readiness
ERC reads `AOExecutionState.current_tool` → "calculate_dispersion". Checks readiness for dispersion. If missing required params → clarify. If ready → proceed.

### 6. Downstream tool failure
```
step[1].status = "failed"
step[1].failure_reason = "missing spatial geometry"
```
Chain is NOT marked complete. `is_chain_complete` returns False. AO cannot complete until all steps are completed or skipped.

### 7. No-op follow-up (e.g., "夏天" after macro completed)
- User message is short-param-like (≤6 chars, known alias)
- `AOExecutionState.current_tool` is None (chain complete or cursor past end) OR the proposed tool matches an already-completed step
- Phase 6.1 idempotency check: EXACT_DUPLICATE
- **Action**: Append `ExecutionStep(status="skipped", idempotent_skip=True)`. Return cached response. Do NOT re-execute.

### 8. Explicit rerun (e.g., "重新算")
- User message contains rerun signal
- Current AO has completed steps
- **Action**: Create new AO with `relationship=REVISION`. Do NOT reuse completed steps. Execute fresh.

### 9. True revision before downstream tool
Example: macro completed with NOx, user says "改成PM2.5" before dispersion runs.
- `chain_cursor == 1` (macro done, dispersion pending)
- Revision detected: `pollutant` changed in effective_args
- **Action**: `revision_epoch += 1`. step[1] (dispersion) status reset to "pending" with cleared effective_args. Macro result is still valid (same tool, different pollutant doesn't invalidate macro — but dispersion must re-run with new pollutant). Actually: macro should re-run with new pollutant because the macro output for NOx is different from PM2.5. So: step[0] status → "pending" (invalidated), effective_args cleared. `chain_cursor = 0`.

   *Decision point for user*: Should pollutant revision invalidate only the downstream tool, or the entire chain including the completed upstream tool? If macro(NOx) and macro(PM2.5) produce different outputs, the downstream tool needs the revised upstream output. Answer: **invalidate completed upstream step if its effective_args semantically overlap with the revision.** Overlap is defined as: the revised parameter key appears in the upstream tool's TOOL_SEMANTIC_KEYS.

### 10. Abandoned / failed objective
- `AO.status = FAILED` or `ABANDONED`
- All pending steps remain pending (no cleanup needed)
- Next user message starts a new AO

---

## Interaction with Phase 6.1 Idempotency

### What Phase 6.1 already solves
- Inter-AO exact duplicates (fresh AO after completed AO) → blocked by pre-dispatch gate
- Explicit rerun signals → bypass idempotency
- True revisions (different effective args) → REVISION_DETECTED, not blocked
- Active chain continuation → bypass idempotency (so downstream tools execute)

### What Phase 6.E adds
- **Intra-AO duplicates**: Same tool within same AO. `AOExecutionState.steps` already has a completed step for this tool with same effective_args → `status="skipped"` step appended, execution suppressed.
- **Skip propagated to chain cursor**: When a step is skipped, cursor advances — the chain does not stall.
- **Revision invalidation**: When effective_args change mid-chain, affected steps are reset. Phase 6.1 would see the new args as a revision (REVISION_DETECTED) and allow re-execution.

### Integration point
Phase 6.1's `check_execution_idempotency()` is called at two places today:
1. `GovernedRouter._check_pre_dispatch_idempotency()` — inter-AO, short-param, empty tool_call_log
2. `GovernedRouter._execute_from_snapshot()` — snapshot execution path

Phase 6.E adds a third call site:
3. **Before any tool dispatch within an active AO**, regardless of path (snapshot or inner_router fallback). The check is against `AOExecutionState.completed_steps` within the same AO, not just across AO boundaries.

### What Phase 6.1 intentionally does NOT solve (and Phase 6.E still won't)
- Dispersion spatial geometry / data-flow
- Evaluator scoring changes
- AO classifier redesign

---

## Minimal Implementation Roadmap

### Phase 6.E.1 — Data model + read-only telemetry (smallest round)
- Add `ExecutionStep` and `AOExecutionState` dataclasses to `core/analytical_objective.py`
- Add `AOExecutionState` field to `AnalyticalObjective` (default None, feature-gated)
- Add `AOManager.init_execution_state(ao, planned_chain)` — creates initial state
- Add `AOManager.get_execution_state(ao) -> Optional[AOExecutionState]` — reader
- Add telemetry: log state transitions as trace steps (no behavior change)
- Add `AOManager.advance_chain(ao, completed_tool, result_ref)` — cursor advance
- Add `AOManager.append_skipped_step(ao, tool_name, matched_step_index)` — skip recording
- Feature gate: `ENABLE_CANONICAL_EXECUTION_STATE` (default false)
- Tests: 15 unit tests for state transitions, cursor advance, serialization round-trip
- **No behavior change.** All existing code paths unchanged. Only telemetry is emitted.
- Verify: 154 existing tests still pass. Can run with flag on, observe telemetry.

### Phase 6.E.2 — Consume canonical state for intra-AO duplicate suppression
- In `GovernedRouter.chat()`, after contract pipeline but before dispatch:
  - If `ENABLE_CANONICAL_EXECUTION_STATE` and `AOExecutionState` exists:
  - Check proposed tool against `completed_steps` (intra-AO scope)
  - If exact duplicate → `append_skipped_step()`, return cached response
  - This extends Phase 6.1 gate from inter-AO-only to intra+inter-AO
- In `_execute_from_snapshot()`: same intra-AO check
- In executor wrapper: same intra-AO check (catches inner_router fallback too)
- Tests: Task 120 pattern — macro executes once, second and third calls skipped
- Verify: targeted tests + Task 120 single-task verification (no repeated macro)

### Phase 6.E.3 — Chain cursor / downstream handoff stabilization
- Replace OASC after_turn chain advancement with `AOManager.advance_chain()`
- Replace ERC chain continuation reads with `AOExecutionState.current_tool` / `pending_next_tool`
- Intent resolver writes initial `planned_chain` to `AOExecutionState`
- Compatibility bridge: derive `ExecutionContinuation(CHAIN_CONTINUATION)` from `AOExecutionState` for legacy consumers
- Guard: if `AOExecutionState` exists AND chain is active, do NOT let LLM-intent overwrite `planned_chain`
- Tests: Task 120 full chain (macro→dispersion) with cursor preserved across turns
- Verify: projected_chain_persistence tests still pass; chain_guard tests adapted

### Phase 6.E.4 — Revision-aware invalidation
- On true revision (Phase 6.1 `REVISION_DETECTED`):
  - `revision_epoch += 1`
  - Find affected steps: any step whose `effective_args` keys overlap with revised keys
  - Reset affected steps to `status="pending"`, clear `effective_args` and `result_ref`
  - Reset `chain_cursor` to earliest affected step index
- "冬天" after "夏天" macro: season revision → macro step invalidated → re-executes with winter
- "改成PM2.5" after macro(NOx) and before dispersion: pollutant revision → both macro AND dispersion invalidated (pollutant in both tools' semantic keys)
- Tests: season revision, pollutant revision mid-chain, single-param revision

### Phase 6.E.5 — Validation on 30-task sanity
- Run 30-task sanity with `ENABLE_CANONICAL_EXECUTION_STATE=true`
- Compare metrics to Phase 6.1 baseline (0.8056 completion_rate)
- Expected: completion_rate stable or improved; Task 120 chain_match improved; no regressions on Tasks 105, 110
- Explicitly do NOT claim benchmark success

---

## Test and Verification Plan

### Unit tests (Phase 6.E.1)
1. `test_init_execution_state_single_tool` — single-tool AO creates correct state
2. `test_init_execution_state_chain` — multi-step chain creates correct state
3. `test_advance_chain_cursor` — after step completes, cursor advances
4. `test_advance_chain_last_step` — after last step, chain is complete
5. `test_append_skipped_step` — skipped step recorded with idempotent_skip=True
6. `test_skip_advances_cursor` — skip also advances cursor
7. `test_pending_next_tool_after_advance` — pending_next_tool reflects cursor
8. `test_is_chain_complete_all_done` — all completed/skipped → True
9. `test_is_chain_complete_with_pending` — has pending → False
10. `test_is_chain_complete_with_failed` — has failed → False
11. `test_serialization_round_trip` — to_dict/from_dict preserves state
12. `test_revision_epoch_increment` — revision increments epoch
13. `test_revision_invalidates_affected_steps` — changed param resets matching steps
14. `test_revision_preserves_unaffected_steps` — steps without overlap stay completed
15. `test_feature_flag_off_no_effect` — flag false → no AOExecutionState created

### Unit tests (Phase 6.E.2)
16. `test_intra_ao_duplicate_blocked` — same tool same args within AO → skipped
17. `test_intra_ao_duplicate_not_blocked_different_args` — same tool different args → REVISION
18. `test_intra_ao_chain_continuation_not_blocked` — pending_next_tool bypasses idempotency
19. `test_explicit_rerun_bypasses_intra_ao` — rerun signal → fresh execution
20. `test_idempotent_skip_recorded_in_steps` — skip appears in AOExecutionState.steps

### E2E / task verification
21. `test_task120_no_repeated_macro` — macro executes once, not 3 times
22. `test_task120_chain_cursor_preserved` — cursor advances macro→dispersion
23. `test_task120_dispersion_attempted` — dispersion tool is called (may fail on geometry — that's OK)
24. `test_idempotency_does_not_block_downstream` — skipped duplicates don't stall chain
25. `test_true_revision_invalidates_downstream` — pollutant change resets dispersion
26. `test_explicit_rerun_re_executes` — "重新算" → fresh execution
27. `test_failed_dispersion_does_not_mark_chain_complete` — failure ≠ completion
28. `test_skipped_duplicate_not_counted_as_normal_tool_call` — OASC/results distinguish skip from execution

### Regression guard
- All 154 existing targeted tests must continue to pass
- 30-task sanity with flag on shows no regression in completion_rate

---

## Risks and User Decision Points

### Risks
1. **Serialization compatibility**: Adding `AOExecutionState` to `AnalyticalObjective` requires a migration path for persisted sessions. Mitigation: field defaults to None; old sessions load without it; feature gate controls whether it's created.
2. **ExecutionContinuation dual-use**: Keeping `ExecutionContinuation` for parameter collection while migrating chain tracking to `AOExecutionState` creates a temporary dual-path. Risk of inconsistency. Mitigation: compatibility bridge derives one from the other; telemetry in Phase 6.E.1 detects drift.
3. **Inner_router fallback path**: The Phase 6.E.2 executor wrapper approach may still miss some execution paths if inner_router has yet another internal dispatch mechanism. Mitigation: the intra-AO check in `GovernedRouter.chat()` pre-dispatch covers all paths, since it runs before any dispatch.
4. **Revision invalidation scope**: Determining which steps to invalidate on a parameter change is non-trivial. TOOL_SEMANTIC_KEYS provides a starting point but may need refinement for cross-tool data dependencies (e.g., macro output feeds dispersion input — even if pollutant isn't in dispersion's semantic keys, changing pollutant in macro changes the dispersion input). Mitigation: start conservative (over-invalidate), observe in Phase 6.E.4 validation, narrow if needed.

### User Decision Points
1. **Revision invalidation scope** (Phase 6.E.4): Should a parameter revision invalidate only downstream steps, or also the upstream step whose output feeds downstream? Proposed answer: invalidate any step whose TOOL_SEMANTIC_KEYS include the revised parameter, plus any step that depends on the output of an invalidated step (transitive closure via TOOL_GRAPH `requires`).
2. **ExecutionContinuation migration**: Should `CHAIN_CONTINUATION` be fully removed from `ExecutionContinuation` or kept as a derived view? Proposed answer: keep as derived view in Phase 6.E, remove in Phase 6.F after validation.
3. **Feature gate graduation**: Should `ENABLE_CANONICAL_EXECUTION_STATE` replace `ENABLE_EXECUTION_IDEMPOTENCY` or be independent? Proposed answer: independent flags. Canonical state is the data model; idempotency is one consumer. Both can be independently toggled.
4. **Backward compat for persisted sessions**: Should old sessions without `AOExecutionState` be auto-migrated or rejected? Proposed answer: load with `AOExecutionState=None`, lazy-init on first execution. No migration script needed.
