# Phase 6.E.4 — Revision-Aware Invalidation Design

## 1. Baseline and motivation

### Baseline commits
- Phase 6.E.3 chain handoff: `9ccc3e3`
- Phase 6.E.2 duplicate guard: `6d6bd69`
- Phase 6.E.1 telemetry: `99956c2`
- Phase 6.1 idempotency: `e35170d`

### What is solved
- **Phase 6.E.1–6.E.3**: AOExecutionState is the canonical execution record. Chain cursor tracks position. Duplicate execution is suppressed. Downstream handoff prefers pending steps.

### What is NOT solved (this design addresses)
When a user revises a parameter after one or more tools in a chain have completed:

1. **No step invalidation**: `ExecutionStepStatus.INVALIDATED` exists but is never written. Completed steps remain COMPLETED even when their effective_args no longer match what the user now wants.
2. **No revision_epoch usage**: `ExecutionStep.revision_epoch` and `AOExecutionState.revision_epoch` exist in the data model but are never incremented or checked.
3. **New-AO model silently discards canonical state**: When AO classifier detects revision cues ("改成CO2", "换成冬季"), `revise_ao()` creates a *new* AO with REVISION relationship. The current AO's execution state is abandoned, not invalidated. Completed steps are lost rather than selectively preserved.
4. **No transitive invalidation**: When upstream tool's effective_args change, downstream dependents have no mechanism to detect staleness. `TOOL_GRAPH.requires/provides` exists but is unused for invalidation.
5. **No parameter delta model**: The system cannot answer "which parameters changed?" or "which completed steps are now stale?"

**Motivating examples:**

| Scenario | Current behavior | Desired behavior |
|---|---|---|
| macro(NOx)→dispersion, user says "改成CO2" | New AO created; macro(NOx) result abandoned; dispersion never re-planned | Invalidate macro step (pollutant changed) + dispersion (depends on macro); re-execute both as CO2 |
| macro(NOx)→dispersion, user says "换成稳定度N1" | New AO created or unclear | Keep macro(NOx) completed (meteorology doesn't affect macro); invalidate dispersion only (stability_class affects dispersion) |
| query(year=2020), user says "2021" | New query execution or confusion | Invalidate query step (model_year changed); re-execute with 2021 |
| macro(NOx), user says "重新算一遍" | Explicit rerun detected; re-executes | Allow re-execution (explicit rerun); update revision_epoch if result changes; no invalidation needed for param delta |
| macro(NOx)→hotspot→map, user changes pollutant | New AO; all lost | Invalidate macro + hotspot (depends on macro→emission) + map (depends on hotspot→dispersion); re-execute chain |

### Non-goals (explicit)
- Do NOT implement code in this round.
- Do NOT redesign AO classifier (unless audit proves unavoidable narrow input signal).
- Do NOT remove ExecutionContinuation.
- Do NOT fix dispersion geometry / WKT / GeoJSON / coordinate data-flow.
- Do NOT change evaluator scoring.
- Do NOT modify tools/calculators.
- Do NOT touch PCM.
- Do NOT claim benchmark success.
- Do NOT paper-frame unresolved design debt.

---

## 2. Current revision / invalidation signal audit

### 2.1 Where revision signals appear today

| Location | Signal | Reliability for invalidation |
|---|---|---|
| **AO classifier** (`core/ao_classifier.py:285`) | Text cues: `改成, 换成, 重新算, 重新计算, instead, change to, revise` | **High** — classifier is the gate; correctly maps to `AOClassType.REVISION` |
| **AO classifier** (`core/ao_classifier.py:100-102`) | More text cues in rule layer | **High** — rule-based layer catches most revisions before LLM |
| **AOManager.revise_ao()** (`core/ao_manager.py:308-329`) | Creates new AO with `AORelationship.REVISION` | **High structural** — but creates new AO (no invalidation) |
| **AOManager._RERUN_SIGNALS** (`core/ao_manager.py:63`) | `重新算, 再算一遍, 重跑, rerun, recalculate` | **High** — explicit rerun intent |
| **continuation_signals.has_reversal_marker()** | `等等, 先确认, 换成, 改成, 先别, 不做了, 不用了, 还是, 要不` | **Medium** — some are true revisions, some are abandonment/hesitation |
| **stance_resolver.reversal_signals** (`core/stance_resolver.py:43`) | `等等, 再想想, 换成, 不对, 改成, 算了还是, 重新` | **Medium** — stance-level, not parameter-level |
| **Phase 6.1 IdempotencyDecision.REVISION_DETECTED** | Same tool, different semantic fingerprint | **High** — directly signals effective-args delta |
| **Phase 6.1 IdempotencyDecision.EXPLICIT_RERUN** | Rerun signal + matching prior execution | **High** — explicit user intent |
| **AO.relationship == REVISION** | Set by `revise_ao()` / AO classifier | **Structural** — indicates parent→child AO link |
| **AO.status == REVISING** | Set when completed AO is reactivated | **Structural** — indicates AO is being revised |
| **Memory.correction_patterns** (`core/memory.py:693`) | `不对, 不是, 应该是, 我说的是, 换成, 改成` | **Low** — conversational correction, not parametric revision |
| **reply_parser_llm** | Natural-language clarification parsing | **Low** — ambiguous; "改成冬季夜间" could be missing-param fill or revision |

### 2.2 Which signals are reliable enough for invalidation?

**Reliable (use directly):**
1. `IdempotencyDecision.REVISION_DETECTED` — semantic fingerprint delta is the gold standard for "same tool, different params"
2. `IdempotencyDecision.EXPLICIT_RERUN` — explicit rerun intent
3. `AOClassType.REVISION` from classifier — gates revision path
4. `_RERUN_SIGNALS` text cues — explicit, unambiguous

**Needs context (use with guard):**
5. `has_reversal_marker()` — some markers indicate param change ("换成", "改成"), others indicate abandonment ("不做了", "不用了")
6. stance reversal — stance-level, not always parametric

**Unreliable for invalidation (do not use):**
7. memory.correction_patterns — conversational, not parametric
8. reply_parser_llm — ambiguous parsing context

### 2.3 Structural issue: New-AO vs Intra-AO revision

The current `revise_ao()` creates a NEW AO with REVISION relationship. This means:
- AOExecutionState of the *current* AO is abandoned, not invalidated
- `ExecutionStepStatus.INVALIDATED` is never written
- `revision_epoch` is never incremented
- All tool_call_log entries from the current AO are lost (they remain in the abandoned AO but aren't carried forward)

**Recommendation**: For Phase 6.E.4, add an *intra-AO invalidation path* that runs BEFORE the new-AO path. When the revision is a parameter change within the same chain (same objective, different effective args), invalidate steps in-place rather than creating a new AO. The new-AO path remains for structural revisions (different tool, different objective text).

---

## 3. Dependency and parameter-delta audit

### 3.1 Tool dependency graph from tool_contracts.yaml

```
query_emission_factors  provides: [emission_factors]       requires: []
calculate_micro_emission provides: [emission]              requires: []
calculate_macro_emission provides: [emission]              requires: []
analyze_file           provides: [file_analysis]           requires: []
clean_dataframe        provides: [data_quality_report]     requires: []
query_knowledge        provides: []                        requires: []
calculate_dispersion   provides: [dispersion]              requires: [emission]
analyze_hotspots       provides: [hotspot]                 requires: [dispersion]
render_spatial_map     provides: []                        requires: []  (layer_type resolved at runtime)
compare_scenarios      provides: []                        requires: []
```

**Transitive invalidation chains:**
- `calculate_macro_emission` → `calculate_dispersion` → `analyze_hotspots` → `render_spatial_map`
- If macro is invalidated: dispersion, hotspot, and map are ALL transitively invalidated
- If only dispersion is invalidated (meteorology change): hotspot and map are invalidated; macro is not
- `query_emission_factors` has no dependents — invalidation is self-contained
- `calculate_micro_emission` has no downstream dependents in the current tool graph

### 3.2 Parameter dimensions from TOOL_SEMANTIC_KEYS

From `core/ao_manager.py:30-61`:

| Tool | Semantic keys (affect output) |
|---|---|
| `calculate_macro_emission` | `vehicle_type, pollutant, pollutants, season, road_type, model_year, meteorology, stability_class, file_path` |
| `calculate_dispersion` | `source_tool, pollutant, meteorology, stability_class, spatial_geometry, file_path` |
| `query_emission_factors` | `vehicle_type, pollutant, pollutants, model_year, season, road_type` |
| `calculate_micro_emission` | `vehicle_type, pollutant, pollutants, trajectory_file, file_path` |
| `analyze_hotspots` | `source_tool, method, threshold` |
| `render_spatial_map` | `source_tool, layer, basemap` |
| `analyze_file` | `file_path` |
| `query_knowledge` | `query_text` |
| `compare_scenarios` | `scenario_a_tool, scenario_b_tool` |

### 3.3 Which parameter changes affect which tools?

Using the dependency graph + semantic keys:

| Changed parameter | Tools directly affected | Tools transitively invalidated |
|---|---|---|
| `pollutant` (macro) | `calculate_macro_emission` | `calculate_dispersion`, `analyze_hotspots`, `render_spatial_map` |
| `vehicle_type` (macro) | `calculate_macro_emission` | `calculate_dispersion`, `analyze_hotspots`, `render_spatial_map` |
| `file_path` (macro) | `calculate_macro_emission`, `analyze_file` | `calculate_dispersion`, `analyze_hotspots`, `render_spatial_map` |
| `meteorology` (dispersion-only) | `calculate_dispersion` | `analyze_hotspots`, `render_spatial_map` |
| `stability_class` (dispersion-only) | `calculate_dispersion` | `analyze_hotspots`, `render_spatial_map` |
| `spatial_geometry` (dispersion-only) | `calculate_dispersion` | `analyze_hotspots`, `render_spatial_map` |
| `model_year` (query-only) | `query_emission_factors` | (none — no dependents) |
| `season` (query/macro) | `query_emission_factors`, `calculate_macro_emission` | `calculate_dispersion`, `analyze_hotspots`, `render_spatial_map` |
| `source_tool` (downstream) | `analyze_hotspots` or `render_spatial_map` | (the tool whose source changed + its downstream) |
| `method` / `threshold` (hotspot-only) | `analyze_hotspots` | `render_spatial_map` (if depends on hotspot) |

### 3.4 Can TOOL_GRAPH express transitive invalidation?

**Current state**: `TOOL_GRAPH` provides `requires` / `provides` per tool. This is sufficient to express transitive invalidation by walking the provides→requires chain.

**What's missing**: The graph doesn't express *which parameters* of a downstream tool depend on upstream output. For example, `calculate_dispersion.requires: [emission]` tells us that dispersion depends on emission output, but not *which dispersion parameters* are affected by upstream changes.

**Recommended approach**: The dependency graph (`requires`/`provides`) alone is sufficient for transitive invalidation. We don't need per-parameter dependency tracking for Phase 6.E.4 — if a tool's provides token is consumed by a downstream tool's requires, invalidate the downstream tool when the upstream is invalidated. This is conservative (may invalidate more than strictly necessary) but correct and simple.

---

## 4. Proposed revision-aware invalidation model

### 4.1 New enum and dataclass additions

```python
class RevisionInvalidationDecision(Enum):
    NO_OP = "no_op"                          # no parameter changes detected
    INVALIDATE_SELF = "invalidate_self"       # only this step changed
    INVALIDATE_DOWNSTREAM = "invalidate_downstream"  # step + transitive dependents
    INVALIDATE_ALL = "invalidate_all"         # entire chain invalidated
    NEW_AO = "new_ao"                         # fundamental revision → new AO

@dataclass
class RevisionInvalidationResult:
    decision: RevisionInvalidationDecision
    invalidated_step_indices: List[int]       # indices into AOExecutionState.steps
    preserved_step_indices: List[int]         # steps that remain valid
    changed_keys: List[str]                   # semantic keys that changed
    new_effective_args: Dict[str, Any]        # proposed new effective args
    previous_effective_args: Dict[str, Any]   # args of the matched completed step
    target_tool: str                          # the tool whose params changed
    reason: str
    new_revision_epoch: int                   # incremented revision_epoch
```

### 4.2 Invalidation flow

```
User message ("改成CO2")
    │
    ▼
AO Classifier → AOClassType.REVISION
    │
    ▼
AOManager.detect_revision_invalidation(ao, proposed_tool, proposed_effective_args)
    │
    ├─ 1. Get AOExecutionState from current AO
    ├─ 2. Find completed steps matching proposed_tool
    ├─ 3. Compare proposed effective_args vs completed step effective_args
    ├─ 4. If no semantic-key delta → NO_OP (idempotent skip)
    ├─ 5. If delta found:
    │      ├─ Identify changed semantic keys
    │      ├─ Compute transitive dependents via TOOL_GRAPH
    │      ├─ Build invalidation set (changed step + transitive dependents)
    │      ├─ Increment revision_epoch
    │      ├─ Mark affected steps as INVALIDATED
    │      └─ Reset chain_cursor to earliest invalidated step index
    └─ 6. Return RevisionInvalidationResult
    │
    ▼
Intent Resolution → reads earliest invalidated step → resolves intent to that tool
    │
    ▼
Execution → re-executes from earliest invalidated step
```

### 4.3 Data model changes (minimal)

**AOExecutionState additions:**
```python
@dataclass
class AOExecutionState:
    # ... existing fields ...
    revision_epoch: int = 0         # already exists — will be incremented
    invalidated_steps_count: int = 0  # new: count of invalidated steps
    last_invalidation_turn: Optional[int] = None  # new: turn when invalidated
    last_invalidation_reason: str = ""  # new: human-readable reason

    # New computed properties:
    @property
    def invalidated_steps(self) -> List[ExecutionStep]:
        return [s for s in self.steps if s.status == ExecutionStepStatus.INVALIDATED]

    @property
    def earliest_invalidated_index(self) -> Optional[int]:
        for i, s in enumerate(self.steps):
            if s.status == ExecutionStepStatus.INVALIDATED:
                return i
        return None

    @property
    def valid_completed_steps(self) -> List[ExecutionStep]:
        """Completed steps that have NOT been invalidated."""
        return [s for s in self.steps
                if s.status == ExecutionStepStatus.COMPLETED
                and s.revision_epoch == self.revision_epoch]
```

**ExecutionStep additions (minimal):**
```python
@dataclass
class ExecutionStep:
    # ... existing fields ...
    revision_epoch: int = 0         # already exists
    invalidated_at_turn: Optional[int] = None   # new
    invalidated_reason: str = ""               # new
    previous_status: Optional[str] = None       # new: status before invalidation
```

### 4.4 When invalidation runs

Invalidation runs at the **pre-execution boundary**, inside the intent resolution flow:

1. AO classifier detects REVISION → enters revision path
2. IntentResolution or AOManager calls `detect_revision_invalidation()`
3. If INVALIDATE_* → mutate AOExecutionState in-place (no new AO)
4. If NEW_AO → delegate to existing `revise_ao()` path
5. If NO_OP → fall through to idempotency (Phase 6.1)

---

## 5. Invalidation rules and decision matrix

### 5.1 Exact decision rules

| # | Condition | Decision | Chain behavior |
|---|---|---|---|
| R1 | No semantic-keys delta (same effective args) + no rerun signal | `NO_OP` | Idempotent skip |
| R2 | Same effective args + explicit rerun signal | `EXPLICIT_RERUN` | Allow re-execution; trace as rerun; no invalidation needed |
| R3 | Changed upstream parameter (pollutant, vehicle_type, file_path) → matching completed step found | `INVALIDATE_DOWNSTREAM` | Invalidate matched step + all transitive dependents; cursor → earliest invalidated |
| R4 | Changed downstream-only parameter (meteorology, stability_class when macro params unchanged) | `INVALIDATE_DOWNSTREAM` | Invalidate dispersion + downstream; keep macro completed |
| R5 | Changed file_path/data source | `INVALIDATE_ALL` | Invalidate ALL steps using that data source + all dependents |
| R6 | Failed step retry with same params | `NO_OP` (for invalidation) | Allow retry — Phase 6.E.3 already returns FAILED step as pending |
| R7 | Failed step retry with changed params | `INVALIDATE_SELF` + `INVALIDATE_DOWNSTREAM` | Invalidate failed step (mark INVALIDATED, re-create as PENDING) + downstream |
| R8 | New independent objective (different tool from chain) | `NEW_AO` | Delegate to `revise_ao()` |
| R9 | Proposed tool not in planned_chain | Check if revision → `NEW_AO` | If truly new intent, create new AO |
| R10 | Multi-pollutant list change (e.g., [NOx] → [NOx, CO2]) | `INVALIDATE_DOWNSTREAM` | Changed effective args → invalidate affected step + downstream |
| R11 | Canonical state disabled | Consult `should_prefer_canonical_pending_tool` → fallback to existing idempotency + continuation logic |

### 5.2 Decision matrix (compact)

```
                    │ effective_args same    │ effective_args changed
────────────────────┼────────────────────────┼──────────────────────────
no rerun signal     │ NO_OP (idempotent)     │ INVALIDATE_DOWNSTREAM
explicit rerun      │ EXPLICIT_RERUN         │ INVALIDATE_DOWNSTREAM
                    │ (allow re-exec)        │ (invalidate + re-exec)
```

### 5.3 Transitive invalidation algorithm

```
def compute_transitive_invalidations(state, invalidated_tool):
    invalidated = {invalidated_tool}
    queue = [invalidated_tool]

    while queue:
        tool = queue.pop(0)
        # What does this tool provide?
        provides = TOOL_GRAPH.get(tool, {}).get("provides", [])
        for token in provides:
            # Which downstream tools require this token?
            for downstream_tool, deps in TOOL_GRAPH.items():
                if token in deps.get("requires", []):
                    if downstream_tool not in invalidated:
                        invalidated.add(downstream_tool)
                        queue.append(downstream_tool)

    return invalidated
```

### 5.4 result_ref handling after invalidation

When a step is invalidated:
- Its `result_ref` is preserved but marked as "stale" in the provenance dict: `provenance["stale_result_ref"] = step.result_ref`
- The step's `result_ref` is set to `None` (so `get_result_ref_for_tool()` doesn't return stale refs)
- No context_store entries are deleted — stale refs coexist; new executions create fresh refs
- `revision_epoch` is incremented on the step, so `valid_completed_steps` filters out stale steps

For downstream invalidated steps:
- Their `result_ref` is also cleared (they're INVALIDATED status anyway)
- Their `provenance["invalidated_because_upstream"]` records which upstream step caused their invalidation

---

## 6. Chain cursor and result_ref handling

### 6.1 Chain cursor behavior after invalidation

| Scenario | Cursor before | Cursor after | Rationale |
|---|---|---|---|
| Macro invalidated (pollutant change) | 1 (dispersion) | 0 (macro) | Macro must re-execute; dispersion is also invalidated |
| Only dispersion invalidated (met change) | 1 (dispersion) | 1 (dispersion) | Macro stays completed; cursor stays at dispersion |
| Macro + dispersion + hotspot invalidated | 2 (hotspot) | 0 (macro) | Cursor returns to earliest invalidated step |
| No invalidation (NO_OP) | N | N (unchanged) | Nothing to invalidate |
| Explicit rerun | N | N (unchanged) | Re-execute at cursor; downstream re-evaluated after |

**Rule**: After invalidation, `chain_cursor = min(earliest_invalidated_index, chain_cursor)`. The cursor always points to the earliest unfinished (PENDING or INVALIDATED→PENDING) step.

### 6.2 Re-creating pending steps after invalidation

When a step is INVALIDATED, the system creates a *new* PENDING step at the same position:
1. Mark old step as `INVALIDATED` (preserves audit trail)
2. Insert new `ExecutionStep(tool_name=same, status=PENDING, revision_epoch=state.revision_epoch + 1)` at the same index
3. Alternatively: change the INVALIDATED step back to PENDING with `revision_epoch` incremented and `previous_status = "completed"`

**Recommendation**: Use the "mutate back to PENDING" approach (option 3) to keep the steps list stable and avoid index shifting. The `revision_epoch` field distinguishes the new execution from the old one, and `previous_status` preserves audit trail.

```python
def invalidate_step(step: ExecutionStep, new_epoch: int, reason: str) -> None:
    step.previous_status = step.status.value          # e.g., "completed"
    step.status = ExecutionStepStatus.INVALIDATED      # mark as invalidated
    step.invalidated_at_turn = current_turn
    step.invalidated_reason = reason
    step.provenance["stale_result_ref"] = step.result_ref
    step.result_ref = None                             # clear stale ref

def re_create_pending_step(ao_state, tool_name: str, new_epoch: int) -> ExecutionStep:
    """Create a fresh PENDING step after invalidation."""
    step = ExecutionStep(
        tool_name=tool_name,
        status=ExecutionStepStatus.PENDING,
        source="revision_invalidation",
        revision_epoch=new_epoch,
        created_turn=current_turn,
    )
    ao_state.steps.append(step)  # appended at end
    return step
```

### 6.3 Chain_status updates

After invalidation:
- `chain_status` transitions from `"complete"` or `"active"` → `"active"` (if any steps left to execute)
- `chain_status` stays `"failed"` if failed steps exist that were not invalidated
- `chain_status` only becomes `"complete"` when ALL steps are COMPLETED/SKIPPED with current `revision_epoch`

---

## 7. Component ownership

| Component | Owns | Rationale |
|---|---|---|
| **AOManager** | `detect_revision_invalidation()` — parameter delta detection, invalidation set computation, state mutation | Already owns AO lifecycle and canonical state; natural extension |
| **AOManager** | `_compute_parameter_delta()` — compares old vs new effective_args for a specific step | Reuses `TOOL_SEMANTIC_KEYS`, `_build_semantic_fingerprint()`, `_canonicalize_value()` |
| **AOManager** | `_compute_transitive_dependents()` — walks TOOL_GRAPH to find downstream tools | Uses existing `TOOL_GRAPH` from `tool_dependencies.py` |
| **IntentResolutionContract** | Detects candidate revision intent (REVISION classification, rerun signals) and triggers invalidation check | Already owns intent resolution; natural gate for "is this a revision?" |
| **ExecutionReadinessContract** | Consumes invalidation result to determine active tool and effective args | Already the pre-execution gate; reads canonical state |
| **OASCContract after_turn** | Records invalidation telemetry; syncs updated AOExecutionState | Already the after-turn sync point |
| **GovernedRouter** | Consumes resulting pending tool; invalidation does not directly affect routing (chain cursor handles it) | Phase 6.E.3 already reads cursor for downstream handoff |

### Component ownership diagram

```
User message ("改成CO2")
        │
        ▼
┌─ OASCContract.before_turn ───────────────────────┐
│  AO Classifier → REVISION                        │
│  classification = REVISION                       │
└──────────────────────┬───────────────────────────┘
                       │
                       ▼
┌─ IntentResolutionContract.before_turn ────────────┐
│  1. Detect REVISION classification               │
│  2. Call AOManager.detect_revision_invalidation()│
│  3. If INVALIDATE_*: override intent → earliest  │
│     invalidated tool                             │
│  4. If NO_OP: fall through to idempotency        │
│  5. If NEW_AO: delegate to revise_ao()           │
└──────────────────────┬───────────────────────────┘
                       │
                       ▼
┌─ AOManager.detect_revision_invalidation() ────────┐
│  1. Get AOExecutionState from current AO         │
│  2. Find completed step matching proposed_tool   │
│  3. Compare effective_args via semantic keys     │
│  4. Compute transitive dependents via TOOL_GRAPH │
│  5. Increment revision_epoch                     │
│  6. Mark affected steps INVALIDATED              │
│  7. Set chain_cursor = earliest_invalidated_index│
│  8. Return RevisionInvalidationResult            │
└──────────────────────┬───────────────────────────┘
                       │
                       ▼
┌─ ExecutionReadinessContract.before_turn ──────────┐
│  Reads AOExecutionState.current_tool             │
│  (already points to earliest invalidated step)   │
│  Normal readiness flow follows                   │
└──────────────────────┬───────────────────────────┘
                       │
                       ▼
                Execution (re-execute from cursor)
                       │
                       ▼
┌─ OASCContract.after_turn ────────────────────────┐
│  Sync execution state telemetry                  │
│  Record invalidation event in AO lifecycle log   │
└──────────────────────────────────────────────────┘
```

---

## 8. Interaction with Phase 6.1 idempotency and Phase 6.E canonical state

### 8.1 Ordering: Invalidation before idempotency

```
Intent Resolution → Invalidation Check → Canonical Duplicate Guard → Idempotency Check → Execution
```

1. **Invalidation first**: If the proposed tool's step is INVALIDATED due to parameter change, the canonical duplicate guard (Phase 6.E.2) naturally allows re-execution — the step is no longer COMPLETED, it's INVALIDATED/PENDING.
2. **Canonical guard second**: If the step is still COMPLETED (no invalidation needed) and the LLM proposes it again, Phase 6.E.2 blocks it.
3. **Idempotency third**: If the step is PENDING (re-created after invalidation) and the effective args match a PRIOR AO's execution, Phase 6.1 idempotency may skip it and reuse the cached result.

### 8.2 Interaction summary

| Scenario | Invalidation (6.E.4) | Canonical guard (6.E.2) | Idempotency (6.1) | Result |
|---|---|---|---|---|
| Same params, no rerun | NO_OP | SKIP_COMPLETED_STEP | EXACT_DUPLICATE | Blocked (correct) |
| Same params, explicit rerun | NO_OP (allow) | PROCEED (step stays COMPLETED but user wants rerun) | EXPLICIT_RERUN (bypass) | Re-execute (correct) |
| Changed param | INVALIDATE → PENDING | PROCEED (step now PENDING) | NO_DUPLICATE or EXACT_DUPLICATE | Re-execute (correct) |
| Changed downstream-only param | INVALIDATE downstream | PROCEED for pending step | NO_DUPLICATE | Re-execute downstream (correct) |
| New independent AO | NEW_AO → revise_ao() | N/A (new AO) | Separate scope | New AO created (correct) |

### 8.3 Phase 6.E.3 chain handoff after invalidation

When invalidation resets the chain cursor:
- `get_canonical_pending_next_tool()` returns the earliest PENDING step (which may be the re-created step at cursor)
- `should_prefer_canonical_pending_tool()` continues to prefer the pending downstream tool over completed upstream tools
- The invalidation creates new PENDING steps that naturally become the preferred target

No changes needed to Phase 6.E.3 — it reads the canonical state, which invalidation has already mutated correctly.

---

## 9. Implementation roadmap

### Round 6.E.4A — Data model extensions + read-only revision delta telemetry
- Add `RevisionInvalidationDecision` enum, `RevisionInvalidationResult` dataclass to `core/analytical_objective.py`
- Add `previous_status`, `invalidated_at_turn`, `invalidated_reason` to `ExecutionStep`
- Add `invalidated_steps_count`, `last_invalidation_turn`, `last_invalidation_reason` to `AOExecutionState`
- Add `invalidated_steps`, `earliest_invalidated_index`, `valid_completed_steps` computed properties
- Add `_compute_parameter_delta()` to AOManager (compares effective_args using TOOL_SEMANTIC_KEYS)
- Add `_compute_transitive_dependents()` to AOManager (walks TOOL_GRAPH)
- Add read-only telemetry: log parameter deltas in OASC after_turn without mutating state
- Feature flag: `ENABLE_REVISION_INVALIDATION` (default false)
- ~15 unit tests for data model + parameter delta

### Round 6.E.4B — Invalidation engine with unit tests
- Add `detect_revision_invalidation()` to AOManager
- Implement the decision matrix (R1–R11)
- Implement transitive invalidation algorithm
- Implement state mutation: INVALIDATED status, revision_epoch increment, chain_cursor reset
- ~20 unit tests: all scenarios from decision matrix, transitive invalidation chains, edge cases

### Round 6.E.4C — Apply invalidation at intent resolution boundary
- Integrate `detect_revision_invalidation()` call into `IntentResolutionContract.before_turn()`
- Gate behind `ENABLE_REVISION_INVALIDATION` flag
- Handle INVALIDATE_* → override intent to earliest invalidated tool
- Handle NO_OP → fall through to existing idempotency
- Handle NEW_AO → delegate to `revise_ao()`
- Ensure `has_reversal_marker()` guard remains (don't override explicit reversal)
- ~5 integration tests

### Round 6.E.4D — Execution boundary consumes invalidated cursor
- Ensure `ExecutionReadinessContract` reads updated chain_cursor after invalidation
- Ensure `_IdempotencyAwareExecutor` allows re-execution of INVALIDATED→PENDING steps
- Ensure OASC after_turn syncs updated AOExecutionState
- ~5 integration tests

### Round 6.E.4E — Targeted task verification
- Task 105 with param revision (夏天 → 冬天): macro re-executes with winter season
- Task 120 with pollutant revision (NOx → CO2): macro + dispersion invalidated and re-executed
- Task 120 with met revision (windy_neutral → N2): macro stays, dispersion invalidated
- Explicit rerun verification
- 30-task diagnostic (informational, not benchmark)

**Total estimated tests**: ~45 new tests across all rounds

---

## 10. Test and verification plan

### Unit tests (6.E.4A–B)

| # | Test | Verifies |
|---|---|---|
| 1 | `test_parameter_delta_same_args_no_delta` | Same effective_args → empty delta |
| 2 | `test_parameter_delta_changed_pollutant` | Different pollutant → delta with "pollutant" key |
| 3 | `test_parameter_delta_changed_meteorology` | Different meteorology → delta with "meteorology" key |
| 4 | `test_parameter_delta_ignores_runtime_noise` | timestamp, run_id, etc. excluded from delta |
| 5 | `test_parameter_delta_empty_previous_args` | Empty previous args → treat as delta (conservative) |
| 6 | `test_transitive_dependents_macro_to_dispersion` | Invalidating macro → dispersion in set |
| 7 | `test_transitive_dependents_macro_to_hotspot` | Invalidating macro → dispersion + hotspot in set |
| 8 | `test_transitive_dependents_dispersion_only` | Invalidating dispersion → hotspot + map, NOT macro |
| 9 | `test_transitive_dependents_query_no_dependents` | Invalidating query → only query in set |
| 10 | `test_invalidation_macro_pollutant_change` | Rule R3: macro + dispersion INVALIDATED |
| 11 | `test_invalidation_dispersion_met_change` | Rule R4: macro stays COMPLETED, dispersion INVALIDATED |
| 12 | `test_invalidation_file_path_change` | Rule R5: all steps using file_path INVALIDATED |
| 13 | `test_invalidation_same_params_no_op` | Rule R1: NO_OP, nothing invalidated |
| 14 | `test_invalidation_explicit_rerun_not_invalidated` | Rule R2: EXPLICIT_RERUN, allow re-exec |
| 15 | `test_invalidation_failed_step_retry_same_params` | Rule R6: failed step retry, NO_OP invalidation |
| 16 | `test_invalidation_failed_step_changed_params` | Rule R7: failed step + downstream invalidated |
| 17 | `test_invalidation_unrelated_tool_new_ao` | Rule R8: NEW_AO, delegate to revise_ao |
| 18 | `test_invalidation_no_state_feature_off` | Feature flag off → no invalidation |
| 19 | `test_chain_cursor_resets_to_earliest_invalidated` | Cursor moves back to earliest INVALIDATED step |
| 20 | `test_result_ref_cleared_on_invalidation` | Invalidated step's result_ref → None |
| 21 | `test_revision_epoch_incremented` | revision_epoch incremented after invalidation |
| 22 | `test_valid_completed_steps_excludes_invalidated` | valid_completed_steps filters by revision_epoch |
| 23 | `test_multi_pollutant_list_change` | Rule R10: [NOx] → [NOx, CO2] triggers invalidation |
| 24 | `test_invalidation_chain_status_transitions` | complete → active after invalidation |

### Integration tests (6.E.4C–D)

| # | Test | Verifies |
|---|---|---|
| 25 | `test_intent_resolution_triggers_invalidation_on_revision` | REVISION classification → detect_revision_invalidation called |
| 26 | `test_intent_overrides_to_earliest_invalidated_tool` | Invalidated macro → intent resolved to calculate_macro_emission |
| 27 | `test_execution_readiness_sees_invalidated_cursor` | Readiness uses chain_cursor after invalidation |
| 28 | `test_canonical_guard_allows_re_execution_after_invalidation` | INVALIDATED step not blocked by Phase 6.E.2 |
| 29 | `test_idempotency_runs_after_invalidation` | Phase 6.1 check fires for re-created PENDING step |
| 30 | `test_oasc_telemetry_records_invalidation` | OASC after_turn logs invalidation event |

### Smoke tests (6.E.4E)

| # | Test | Expected |
|---|---|---|
| 31 | Task 105: "夏天" macro, then "改成冬天" | Macro re-executes with winter; 2 executions total |
| 32 | Task 120: macro(NOx)→cursor=1, then "改成CO2" | Macro invalidated; dispersion invalidated; both re-execute for CO2 |
| 33 | Task 120: macro(NOx)→cursor=1, then "换成N2稳定度" | Macro stays COMPLETED; dispersion invalidated and re-executed with N2 |
| 34 | Task 120: macro(NOx), then "重新算一遍" | Explicit rerun; macro re-executes; downstream re-evaluated |
| 35 | Task 120: macro(NOx)→cursor=1, then "改成CO2" with feature flag off | Existing behavior preserved (revision creates new AO) |

---

## 11. Risks and user decision points

### 11.1 Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **Over-invalidation**: Conservative transitive invalidation may invalidate steps whose output is still valid | Medium | Acceptable for Phase 6.E.4; per-parameter dependency tracking deferred |
| **New-AO vs intra-AO ambiguity**: Classifier may classify some revisions as NEW_AO when intra-AO invalidation would be better | Medium | Both paths coexist; intra-AO path tried first; new-AO path is fallback |
| **result_ref churn**: Clearing result_refs may cause context_store cache misses for downstream tools | Low | Context store entries are not deleted; stale refs are just not returned by `get_result_ref_for_tool()` |
| **chain_cursor instability**: Invalidation may reset cursor backward, confusing ExecutionContinuation consumers | Low | ExecutionContinuation is bypassed when canonical state is authoritative; Phase 6.E.3 already establishes this |
| **Interaction with AO completion**: `has_produced_expected_artifacts()` may return False after invalidation clears result_refs | Medium | Expected behavior — AO with invalidated steps is not complete |
| **LLM non-determinism**: LLM may not consistently produce revision intent when user changes parameters | Medium | AO classifier rule layer catches explicit revision cues before LLM |

### 11.2 User decision points

1. **New-AO vs intra-AO boundary**: Should "改成算微观排放" (change objective from macro to micro) use intra-AO invalidation or create a new AO?
   - **Recommendation**: New AO. The planned_chain changes fundamentally (different tools). Intra-AO invalidation only applies when the chain is the same but parameters differ.

2. **Multi-pollutant expansion**: If user computes NOx macro, then asks "also compute CO2", is this revision or continuation?
   - **Recommendation**: Continuation. The NOx result stays valid; CO2 is an *additional* computation within the same AO. Invalidation should NOT fire — this is handled by parameter_collection adding a new pollutant.

3. **result_ref staleness vs deletion**: Should stale result_refs be deleted or preserved?
   - **Recommendation**: Preserve in provenance (`stale_result_ref`), clear from the step's `result_ref` field. Context store entries are NOT deleted (they may be referenced by other AOs).

4. **Feature flag scope**: Should `ENABLE_REVISION_INVALIDATION` be independent of `ENABLE_CANONICAL_EXECUTION_STATE`?
   - **Recommendation**: Dependent. `ENABLE_REVISION_INVALIDATION` requires `ENABLE_CANONICAL_EXECUTION_STATE=true`. If canonical state is off, revision invalidation has no data to work with.

5. **Explicit rerun vs invalidation priority**: When user says "改成CO2重新算", which wins?
   - **Recommendation**: Invalidation wins. The parameter change is the primary signal; the rerun confirmation is secondary. Invalidate first, then allow re-execution.

---

## 12. Non-goals

- Do NOT fix dispersion spatial geometry / WKT / GeoJSON / coordinate data-flow.
- Do NOT change evaluator scoring.
- Do NOT redesign AO classifier (existing REVISION classification + rule-layer cues are sufficient).
- Do NOT modify tools/calculators.
- Do NOT touch PCM.
- Do NOT remove ExecutionContinuation.
- Do NOT add a generic cache/invalidation framework beyond AOExecutionState.
- Do NOT claim benchmark success in this round.
- Do NOT commit in this round (design only).
