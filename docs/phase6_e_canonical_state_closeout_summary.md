# Phase 6.E Closeout — Canonical Execution State (AO-Scoped)

**Date:** 2026-05-01
**Branch:** `phase3-governance-reset`
**Closeout commit:** `9f1dc94`

---

## 1. Baseline Commits and Tags

| Tag | Commit | Description |
|-----|--------|-------------|
| `phase6e2-canonical-state-consumption` | `99956c2` | 6.E.1 — canonical execution state telemetry |
| `phase6e2-canonical-duplicate-guard` | `6d6bd69` | 6.E.2 — duplicate-step guard |
| `phase6e3-downstream-chain-handoff` | `9ccc3e3` | 6.E.3 — downstream handoff stabilization |
| `phase6e4a-revision-delta-telemetry` | `3dfe675` | 6.E.4A — revision delta telemetry |
| `phase6e4b-revision-invalidation-engine` | `434e483` | 6.E.4B — invalidation engine |
| `phase6e4c-runtime-revision-invalidation` | `91900ac` | 6.E.4C — readiness-boundary invalidation integration |
| `phase6e4d-invalidated-step-consumption` | `9f1dc94` | 6.E.4D — invalidated-step consumption |

Preceding baseline tags:
- `phase5.3-phase6.1-closed` — Phase 6.1 AO-scoped execution idempotency (`e35170d`)
- `multi-turn-upgrade-final` — Phase 5.3 governance repairs
- `engineering-baseline-v1` — original engineering baseline

---

## 2. What Phase 6.E Solved

Phase 6.E introduced **AO-scoped canonical execution state** as a first-class persistence layer
for multi-turn tool-chain execution. Before 6.E, the agent had no memory of which tools had
already executed within an analytical objective across turns. This caused:

- **Duplicate execution:** The same tool with the same args could be called again on a
  continuation turn, wasting compute and producing redundant results.
- **No downstream awareness:** When the user revised a parameter (e.g. pollutant), the
  agent could not determine which previously-completed downstream steps depended on that
  parameter and needed re-execution.
- **No revision audit trail:** Parameter changes across turns had no structured telemetry,
  making it impossible to trace why a re-execution was triggered.

Phase 6.E solves all three by layering canonical execution state on top of the existing
`AnalyticalObjective` model:

- `AOExecutionState` records each tool execution as an `ExecutionStep` with status,
  args, result_ref, and provenance.
- `chain_cursor` tracks the current position within the projected tool chain.
- `revision_epoch` and per-step provenance fields (`invalidated_reason`,
  `stale_result_ref`, `revalidated_at_turn`) provide a complete audit trail for
  parameter-driven re-execution.

All new behaviour is gated behind two feature flags:
- `ENABLE_CANONICAL_EXECUTION_STATE` (env, default `false`)
- `ENABLE_REVISION_INVALIDATION` (env, default `false`)

An additional Phase 6.1 flag controls idempotency integration:
- `ENABLE_EXECUTION_IDEMPOTENCY` (env, default `false`)

---

## 3. Phase-by-Phase Summary

### 6.E.1 — Canonical Execution State Telemetry (`99956c2`)

**What it did:** Introduced `AOExecutionState`, `ExecutionStep`, and
`ExecutionStepStatus` data structures in `core/analytical_objective.py`.
Added `ensure_execution_state()` factory in `core/ao_manager.py` that lazily
creates execution state from `projected_chain` and `tool_call_log`.
Wired `_sync_execution_state_telemetry()` in `core/contracts/oasc_contract.py`
so every tool call writes a step record (PENDING → COMPLETED/FAILED).

**Key files:** `core/analytical_objective.py`, `core/ao_manager.py`,
`core/contracts/oasc_contract.py`

**Tests:** `tests/test_canonical_execution_state.py` (395 lines)

---

### 6.E.2 — Duplicate-Step Guard (`6d6bd69`)

**What it did:** Added `check_canonical_execution_state()` to `AOManager`.
When a tool is proposed and the step at `chain_cursor` is already `COMPLETED`
or `SKIPPED`, the guard returns `SKIP_COMPLETED_STEP`. The router uses this
to suppress duplicate execution within an active AO.

**Key files:** `core/ao_manager.py`, `core/governed_router.py`

**Tests:** `tests/test_canonical_execution_state_consumption.py` (513 lines)

---

### 6.E.3 — Downstream Handoff Stabilization (`9ccc3e3`)

**What it did:** Added `get_canonical_pending_next_tool()` and
`should_prefer_canonical_pending_tool()` to `AOManager`. When the canonical
state indicates the next tool should be a downstream tool (not the one the
LLM proposed), the guard returns `ADVANCE_TO_PENDING` with `pending_next_tool`
and `blocked_tool`. This handles the case where the LLM proposes re-running
an upstream tool when downstream work remains.

**Key files:** `core/ao_manager.py`, `core/governed_router.py`

**Tests:** `tests/test_canonical_chain_handoff.py` (397 lines)

---

### 6.E.4A — Revision Delta Telemetry (`3dfe675`)

**What it did:** Added parameter-delta computation in `ao_manager.py`.
When a tool is proposed with arguments that differ from the previously
executed step's `effective_args`, the system computes a structured delta
(`param_delta_self`, `param_delta_downstream`, `param_delta_superset`)
and stores it in a `revision_epoch` within the execution state.

**Key files:** `core/ao_manager.py`

**Tests:** `tests/test_revision_delta_telemetry.py` (437 lines)

---

### 6.E.4B — Invalidation Engine (`434e483`)

**What it did:** Built the invalidation logic on top of revision deltas.
When a parameter change is detected, the engine:
- Marks the directly-affected step as `INVALIDATED` with `invalidated_reason`
- Cascades invalidation to all downstream steps that consumed the stale result
- Stores `stale_result_ref` in each invalidated step's provenance
- Resets `chain_cursor` to the earliest invalidated position

**Key files:** `core/ao_manager.py`, `core/analytical_objective.py`

**Tests:** `tests/test_revision_invalidation_engine.py` (704 lines)

---

### 6.E.4C — Readiness-Boundary Invalidation Integration (`91900ac`)

**What it did:** Integrated the invalidation engine into the readiness/preflight
boundary. Before a tool executes, the system checks whether the proposed
arguments constitute a revision of previously-executed parameters. If so,
invalidation is triggered before the tool runs, ensuring the execution state
reflects the new reality before any new results are written.

**Key files:** `core/ao_manager.py`, `core/readiness.py`

**Tests:** `tests/test_revision_invalidation_runtime.py` (493 lines)

---

### 6.E.4D — Invalidated-Step Consumption (`9f1dc94`)

**What it did:** Made the execution boundary consume `INVALIDATED` steps as
executable work:
- `check_canonical_execution_state()` returns `PROCEED` (not `SKIP_COMPLETED_STEP`)
  for `INVALIDATED` steps at `chain_cursor`
- `check_execution_idempotency()` returns `NO_DUPLICATE` (with reason
  `canonical_step_invalidated`) before fingerprint comparison, allowing
  INVALIDATED steps to bypass idempotency suppression
- `pending_next_tool` property includes `INVALIDATED` steps as fallback after
  `PENDING` steps
- `_sync_execution_state_telemetry()` writes `revalidated_at_turn` provenance
  and preserves `stale_result_ref` on successful re-execution
- `chain_cursor` advances past revalidated steps after they complete

**Key files:** `core/ao_manager.py`, `core/analytical_objective.py`,
`core/contracts/oasc_contract.py`

**Tests:** `tests/test_revision_invalidation_consumption.py` (407 lines, 12 tests)

---

### 6.E.4E — Clean Bounded Verification

**What it did:** Smoke-verified the full 6.E chain on single-task scenarios:

| Scenario | Task | Result |
|----------|------|--------|
| Basic macro emission | 105 | One execution, no duplicate |
| Basic query | 110 | One execution, no duplicate |
| Macro with geometry gap | 120 | One execution, geometry/input-completion debt remains (pre-existing) |
| Pollutant revision (NOx→CO2) | custom | Macro + dispersion both invalidated, cursor=0 |
| Meteorology-only change | custom | Dispersion only invalidated, cursor=1, macro preserved |
| Explicit rerun (same params) | custom | Correctly treated as rerun, not param-delta invalidation |

---

## 4. Current Expected Behavior

1. **Completed step duplicate suppressed:** When a tool at `chain_cursor` has
   status `COMPLETED` or `SKIPPED`, `check_canonical_execution_state()` returns
   `SKIP_COMPLETED_STEP`, preventing redundant re-execution.

2. **Downstream pending tool preferred:** When the LLM proposes an upstream tool
   but the canonical state shows a downstream `PENDING` or `INVALIDATED` step,
   the guard returns `ADVANCE_TO_PENDING` with `pending_next_tool` and
   `blocked_tool`, redirecting execution to the next pending step.

3. **Revised upstream params invalidate upstream + downstream:** When a parameter
   used by an upstream tool is revised, both the upstream step and all downstream
   steps that consumed its result are marked `INVALIDATED`. `chain_cursor` resets
   to the earliest affected position.

4. **Downstream-only params invalidate downstream only:** When a parameter used
   only by a downstream tool is revised, only that downstream step is invalidated.
   The upstream step remains `COMPLETED` with its result_ref intact.

5. **Explicit rerun remains separate:** When the user explicitly requests a rerun
   (e.g. "重新算一遍") with identical parameters, the idempotency guard returns
   `EXPLICIT_RERUN`, not a parameter-delta invalidation. The two code paths are
   distinct and do not interfere.

---

## 5. Verification Evidence

### Targeted Tests: 270 passed, 0 failed

| Test file | Lines | Focus |
|-----------|-------|-------|
| `test_revision_invalidation_consumption.py` | 407 | 6.E.4D — INVALIDATED step consumption (12 tests) |
| `test_revision_invalidation_runtime.py` | 493 | 6.E.4C — runtime invalidation integration |
| `test_revision_invalidation_engine.py` | 704 | 6.E.4B — invalidation engine logic |
| `test_revision_delta_telemetry.py` | 437 | 6.E.4A — parameter delta computation |
| `test_canonical_chain_handoff.py` | 397 | 6.E.3 — downstream handoff stabilization |
| `test_canonical_execution_state_consumption.py` | 513 | 6.E.2 — duplicate-step guard |
| `test_canonical_execution_state.py` | 395 | 6.E.1 — execution state telemetry |
| `test_execution_idempotency.py` | 657 | 6.1 — execution idempotency guard |
| `test_projected_chain_persistence.py` | 144 | Chain persistence across turns |
| `test_execution_readiness_chain_guard.py` | 192 | Chain readiness gating |
| `test_stance_parameter_collection.py` | 219 | Parameter collection stance |
| `test_stage1_merge_protection.py` | 188 | Stage 1 merge integrity |
| `test_execution_readiness_parameter_snapshot.py` | 271 | Parameter snapshot at readiness |
| `test_reconciler.py` | 348 | Parameter reconciliation |
| `test_contract_grounding_validator.py` | 252 | Grounding validation |
| `test_intent_resolution_contract.py` | 311 | Intent resolution |
| `test_oasc_backfill_guard.py` | 190 | OASC backfill guard |
| `test_file_analysis_hydration.py` | 155 | File analysis hydration |

**Total: 6,273 lines across 18 files**

### Clean Bounded Smoke (6.E.4E)

- Task 105: one macro execution, no duplicate — PASS
- Task 110: one query execution, no duplicate — PASS
- Task 120: one macro execution, geometry debt remains — PASS (E.4D behaviours verified)
- Revision NOx→CO2: macro + dispersion invalidated, cursor=0 — PASS
- Meteorology-only change: dispersion invalidated, cursor=1 — PASS
- Explicit rerun same params: correctly separate from param-delta — PASS

---

## 6. Explicit Non-Claims

This phase does **not** claim to solve:

- **Dispersion geometry / data-flow:** WKT, GeoJSON, coordinate handling, and
  spatial geometry requirements are unchanged. Task 120 still fails on geometry
  input-completion for the same pre-existing reasons.
- **Evaluator scoring:** No evaluator thresholds, metrics, or scoring logic
  were modified.
- **AO classifier redesign:** The AO classification logic (which determines
  tool chains from user intent) was not changed.
- **ExecutionContinuation removal:** The legacy `ExecutionContinuation`
  mechanism was not removed. It coexists with canonical execution state.
- **Full benchmark success:** Only bounded single-task smoke was verified.
  Broader multi-task or 180-task benchmarks have not been run.

---

## 7. Residual Debts

| Debt | Description | Severity |
|------|-------------|----------|
| Dispersion geometry/data-flow | DispersionTool requires spatial coordinates (WKT/GeoJSON) that the current file-analysis→parameter-collection pipeline does not reliably produce. This is the root cause of Task 120 input-completion failures. | Medium |
| Eval/session isolation hygiene | Smoke runs may be affected by shared session state or cached AO history from prior runs. Dedicated isolation (temp output dirs, clean session fixtures) is recommended for future sanity runs. | Low |
| ExecutionContinuation compatibility | The legacy continuation views coexist with canonical state. Future cleanup should remove or fully subsume them. | Low |
| `pending_next_tool` fallback hardening | The property falls back from PENDING to INVALIDATED, which is correct but could benefit from cursor-scoped validation to prevent edge cases with multi-invalidated chains. | Low |

---

## 8. Recommended Next Phases

1. **30-task sanity with all three flags enabled** (immediate):
   Run a controlled 30-task sample with `ENABLE_CANONICAL_EXECUTION_STATE=true`,
   `ENABLE_REVISION_INVALIDATION=true`, `ENABLE_EXECUTION_IDEMPOTENCY=true` to
   validate the full 6.E stack on a broader but bounded task set.

2. **Decision point — dispersion data-flow design vs. broader benchmark:**
   - If dispersion/geometry is considered blocking, design the spatial data
     contract (WKT/GeoJSON normalization, coordinate extraction from file
     analysis output) next.
   - If the current state is acceptable and dispersion debt is deferred,
     proceed to a broader (180-task) benchmark to measure end-to-end
     completion/accuracy with canonical state enabled.

3. **Phase 6.F cleanup** (after decision):
   - Remove or subsume legacy `ExecutionContinuation` compatibility views
   - Externalize remaining hardcoded workflow templates to YAML
   - Add cursor-scoped hardening for `pending_next_tool`
