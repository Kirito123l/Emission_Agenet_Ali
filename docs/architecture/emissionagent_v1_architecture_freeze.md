# EmissionAgent v1 Architecture Freeze

## 1. Purpose and Freeze Baseline

This document is the authoritative EmissionAgent v1 architecture freeze for
benchmark, evaluation, and paper consolidation work after Phase 7.6F. It records
the closed architecture and the explicit limits of what has been proven.

Current HEAD at freeze time:

- Commit: `d2b36f568d1dea0f103a547689c108d30ead811c`
- Short commit: `d2b36f5`
- Branch: `phase3-governance-reset`
- Tag at HEAD: `phase7-geometry-dataflow-closed`

Important phase baselines and tags:

| Area | Tag or commit | Meaning |
| --- | --- | --- |
| Phase 5.3 | `multi-turn-upgrade-final` / `47da89b` | A/B/E narrow governance repairs |
| Phase 6.1 | `phase5.3-phase6.1-closed` / `e35170d` | AO-scoped execution idempotency |
| Phase 6.E | `phase6e-canonical-state-closed` / `e625bbc` | Canonical execution state closeout |
| Phase 6.E step tags | `phase6e2-canonical-state-consumption`, `phase6e2-canonical-duplicate-guard`, `phase6e3-downstream-chain-handoff`, `phase6e4a-revision-delta-telemetry`, `phase6e4b-revision-invalidation-engine`, `phase6e4c-runtime-revision-invalidation`, `phase6e4d-invalidated-step-consumption` | Canonical state, duplicate guard, downstream handoff, and revision invalidation chain |
| Phase 7 | `phase7-geometry-dataflow-closed` / `d2b36f5` | Geometry data-flow architecture closeout |
| Phase 7.6F | `phase7_6f-filecontext-storage-wiring` / `2d0e5fa` | FileContext storage wiring for multi-file geometry discovery |

## 2. Final v1 Architecture Overview

### User and File Input

EmissionAgent v1 accepts natural-language user requests and optional user files.
Files are analyzed before execution and represented as file context rather than
being treated as opaque uploads. User files remain the only source for road
geometry in v1; the system does not perform external geometry lookup.

### File-Grounded Task Understanding

The LLM handles semantic interpretation of user intent, including task type,
tool-chain intent, and clarification phrasing. File analysis supplies grounded
evidence about columns, detected geometry metadata, join-key candidates, and
available tabular data. The framework must preserve this file grounding across
split-contract and multi-turn flows.

### Parameter Governance

Parameter governance is a layered contract pipeline:

- Stage 2 LLM decisions propose intent and missing parameters.
- YAML-derived readiness and tool contracts provide deterministic required-slot
  evidence.
- The B validator filters hallucinated or contract-illegal missing slots.
- The reconciler arbitrates between LLM, YAML/readiness, and validator evidence
  with explicit rules and traceable source labels.

The reconciler is source arbitration, not a fixed "P2 always wins" rule.

### Readiness and Dependency Governance

Readiness decides whether a tool may execute, must clarify, or can repair input
state. Dependency governance enforces preconditions such as required upstream
results and spatial dependencies. For dispersion, readiness now recognizes
direct spatial emission layers and deterministic join-key geometry layers.

### Canonical Execution State

AO-scoped canonical execution state records tool-chain progress with step
status, effective arguments, result references, chain cursor position, and
revision provenance. It suppresses duplicate completed steps, advances to
pending downstream steps, invalidates stale upstream or downstream steps after
parameter revisions, and lets invalidated steps execute again when needed.

### Tool Execution

Tools execute only after governance marks the request legal and ready. Tool
execution remains separate from semantic understanding. Phase 8.1 makes no
runtime, tool, calculator, evaluator, PCM, AO classifier, or formula changes.

### Spatial Data-Flow Contract

The final v1 spatial contract has three deterministic paths:

1. Direct WKT, GeoJSON, or LineString road geometry in the emission file.
2. Join-key-only emission data plus a user-supplied geometry file with matching
   deterministic keys.
3. Missing or invalid geometry, which produces targeted clarification instead
   of invented geometry.

Dispersion consumes a `spatial_emission_layer` produced by these paths. The
contract rejects point-only geometry for road dispersion and never uses row
order, fuzzy matching, external lookup, or fake geometry.

### Trace and Telemetry

Trace and telemetry record governance decisions, grounded or dropped
clarification slots, canonical state events, revision deltas, invalidation
events, spatial readiness decisions, and join-key geometry resolution outcomes.
One remaining hygiene debt is to improve trace/log visibility around silent
FileContext storage exception handling.

## 3. Core Governance Principles

1. The LLM handles semantic understanding.
2. The framework enforces execution legality.
3. The B validator is advisory and filtering only; it is not a hard route gate.
4. The reconciler arbitrates between evidence sources; it is not "P2 always
   wins."
5. Geometry is deterministic and never invented.
6. Tool execution must be grounded in contracts, readiness, and canonical
   execution state rather than raw model preference.
7. Evaluation claims must be separated from architecture claims.

## 4. Final Closed Capabilities

### A/B/E Governance Repairs

Phase 5.3 closed narrow governance defects:

- B validator contract-grounding for missing-slot candidates.
- A reconciler arbitration across LLM, readiness/YAML, execution readiness, and
  B-validator evidence.
- E narrow handoff preservation for macro-to-dispersion chain continuation.
- File-grounded intent preservation, parameter snapshots, Stage 1 merge
  protection, OASC stale backfill guard, and stance handling during collection.

### Idempotency

Phase 6.1 introduced AO-scoped execution idempotency. It prevents duplicate
same-tool, same-effective-parameter execution where a completed objective already
satisfies the proposed work, while preserving explicit rerun semantics.

### Canonical Execution State

Phase 6.E introduced AO-scoped `AOExecutionState`, execution steps, chain cursor
management, duplicate-step guard, downstream handoff, revision deltas, and
invalidated-step consumption.

### Revision Invalidation

Parameter revisions now mark affected completed steps as invalidated, cascade
invalidation to dependent downstream steps, preserve stale result references,
and reset the chain cursor to the earliest invalidated executable step.

### Direct Geometry Path

Files containing direct WKT, GeoJSON, or LineString-compatible geometry can
produce a `spatial_emission_layer` that dispersion consumes without formula or
math changes.

### Join-Key Geometry Path

Emission files containing join keys can be joined to a user-supplied geometry
file through stored multi-file `FileContext` metadata and deterministic key
resolution. A sufficiently matched layer can become ready for dispersion.

### Missing Geometry Clarification

If road geometry is absent, point-only, ambiguous, or not join-resolvable,
readiness returns a targeted repairable diagnostic instead of inventing
geometry.

## 5. Geometry and Data-Flow Final Architecture

### Direct Geometry Path

The direct path is:

```text
user file with WKT/GeoJSON/LineString geometry
-> analyze_file
-> geometry metadata in FileContext
-> macro emission result
-> spatial_emission_layer
-> readiness marks spatial layer available
-> router bridge injects layer
-> dispersion consumes layer
```

This path changes data flow only. Dispersion and macro emission formulas are
unchanged.

### Join-Key Supplied Geometry Path

The join-key path is:

```text
emission file with link_id only
-> analyze_file
-> store_analyzed_file_context()
-> SessionContextStore stores emission FileContext
geometry file with link_id + WKT/GeoJSON/LineString
-> analyze_file
-> store_analyzed_file_context()
-> SessionContextStore stores geometry FileContext
readiness auto-discovers candidate geometry FileContext
-> deterministic join-key resolver
-> spatial_emission_layer
-> dispersion consumes layer
```

The resolver requires explicit normalized key matches. It allows deterministic
numeric string and integer equivalence, rejects conflicting duplicate geometry
keys, rejects row-order joins, rejects fuzzy matching, and classifies match
quality according to the Phase 7 thresholds.

### Missing Geometry Path

If direct geometry is unavailable and no suitable user-provided geometry file
can be resolved, readiness returns a targeted clarification. The v1 architecture
does not synthesize geometry, infer road shape from row order, or call external
map services.

### Point-Only Rejection

Point-only coordinates are not sufficient road geometry for dispersion. The
system rejects this path with a repairable diagnostic requiring line or polygon
road geometry.

### No External Lookup

EmissionAgent v1 has no OSM, Baidu Maps, network API, geocoding, or external
road-geometry lookup path.

## 6. Current Verification Evidence

Phase 7 closeout targeted tests:

- Result: `439/440`
- Known failure: one async-framework environment failure unrelated to geometry
  bridge logic.
- Geometry bridge failures: `0`

Phase 7 closeout 30-task sanity:

| Metric | Value |
| --- | --- |
| `completion_rate` | `0.7667` |
| `tool_accuracy` | `0.7667` |
| `parameter_legal_rate` | `0.8333` |
| `result_data_rate` | `0.7333` |

The 30-task sanity is evidence that Phase 7 did not regress the prior baseline
outside expected LLM-noise range. It is not a formal benchmark claim.

## 7. Explicit Non-Claims

- No 180-task benchmark has been run for this freeze.
- No claim is made of significant metric improvement from the 30-task smoke.
- No external geometry lookup exists.
- No fuzzy matching exists.
- No row-order join exists.
- No fake geometry is produced.
- No dispersion formula, macro emission formula, calculator math, evaluator
  scoring, PCM, AO classifier, or canonical execution state changes are made by
  Phase 8.1.

## 8. Remaining Debts

1. Full benchmark protocol still needs to be run and reported.
2. LLM colloquial, code-switch, and multi-turn understanding failures remain.
3. The async-framework test environment issue remains.
4. Optional trace/log hygiene remains for silent FileContext storage
   `try`/`except` handling.
5. Paper and evaluation artifacts need consolidation.

These debts are not hidden by the v1 freeze; they define the next evaluation and
paper-readiness work.

## 9. v1 Architecture Freeze Judgment

EmissionAgent v1 architecture is frozen for benchmark and evaluation work at
HEAD `d2b36f568d1dea0f103a547689c108d30ead811c`.

The freeze covers governance, canonical execution state, revision invalidation,
tool execution legality, and the three-path geometry data-flow contract. Future
changes require a new phase if they alter:

- runtime behavior or execution routing,
- evaluator scoring,
- tools, calculators, PCM, AO classifier, or canonical execution state,
- dispersion or emission formulas,
- geometry matching semantics,
- external geometry sourcing,
- FileContext storage semantics,
- benchmark protocol or formal metric claims.

Documentation cleanup and archive-only repository hygiene can proceed without a
new architecture phase when they do not change these contracts.

## 10. Recommended Next Work

1. Define the formal benchmark protocol.
2. Run the full evaluation.
3. Produce ablation tables for governance, canonical state, and geometry
   data-flow contributions.
4. Consolidate paper method and results sections around the frozen v1
   architecture.

## 11. Errata (post-freeze corrections)

This section records discrepancies between the v1 freeze document (commit
`1391b9f`) and codebase reality, discovered and resolved during Phase 8.1.2 audit.
Each entry states whether it has been resolved and, if so, in which commit.

### 11.1 Reconciler activation gap (RESOLVED)

**Discovery:** Phase 8.1.2 Step 1 audit (§6 of `v1_freeze_reality_audit.md`)
revealed that at freeze time (`1391b9f`), the production default
`ENABLE_LLM_DECISION_FIELD=false` kept the reconciler and B validator at **0%
production invocation**. The gate at `core/governed_router.py:267` prevents
`_consume_decision_field()` from being entered when the flag is `false`, and
`_consume_decision_field()` is the sole production caller of `reconcile()` (line
912) and `filter_stage2_missing_required()` (line 910).

**Severity at freeze:** The freeze document §3 governance principle 4 ("reconciler
arbitrates between evidence sources; it is not 'P2 always wins'") was a
**substantive error** — not a limitation, an advisory-mode-by-design caveat, or a
future-work item. In production (default) mode, the reconciler was dead code.
Section §2 Parameter Governance described a "layered contract pipeline" (Stage 2 →
YAML/readiness → B validator → reconciler) that omitted PCM entirely, and PCM
short-circuited that entire pipeline on ~83% of tasks with unfilled optional
parameters (per Phase 4 design doc estimate).

**Historical context:** Phase 4 (`9e7fd85`) explicitly designed `flag=false` as
Option C hard-block fallback and `flag=true` as Option B advisory mode, for backward
compatibility and controlled comparison. Phase 5.3 (`47da89b`) repaired the A/B/E
narrow paths but verified them only under `governance_full` ablation (flag=true).
Phase 5.3 sanity 23/30 (76.67%) was run with flag=true, not with the production
default flag=false. No later phase changed the default or verified reconciler
activation under default routing.

**Resolution:** Phase 8.1.2 Step 3 production-default switch (this commit) changes
`config.py:189` default from `"false"` to `"true"`. The reconciler is now an active
component on the production main path.

**Verification:**
- Step 2 sanity (commit `880ad1f`): OFF vs ON n=3 — ON completion_rate=0.80 vs
  OFF 0.7333 (+6.67pp), incomplete category rescued from 33.3% to 100%.
- Step 2.5 telemetry verification (commit `cd9a2e0`): OFF reconciler=0 confirmed
  (0 `decision_field_clarify` traces); ON reconciler ≥6 confirmed (6
  `decision_field_clarify` traces across 6 tasks, 3 of which are the incomplete
  rescue tasks).
- Step 3 default-verify sanity (this commit): n=1 with no `ENABLE_LLM_DECISION_FIELD`
  env var, completion_rate=0.80, reconciler activity confirmed (5 tasks, 6
  `decision_field_clarify` events), consistent with Step 2B ON explicit-flag data.

### 11.2 PCM role in the governance pipeline

**Discovery:** Phase 8.1.2 Step 1 audit revealed that PCM (Parameter Collection
Module) is absent from the freeze document §2 Parameter Governance description, yet
PCM is the pre-Stage-2 gate that determines whether Stage 2, B validator, and
reconciler are reached at all.

**Current state (post-resolution):**

| Flag State | PCM Mode | Behavior |
|-----------|----------|----------|
| `true` (new default) | Advisory (Option B) | PCM computes `pcm_advisory` dict, sets `should_proceed=True`, injects advisory context into Stage 2 LLM payload. Does NOT block Stage 2 or reconciler. |
| `false` (opt-out fallback) | Hard-block (Option C) | PCM probes optional slots, blocks execution with `proceed=False` when optional parameters are missing. Prevents Stage 2 and reconciler invocation on ~83% of affected tasks. |

**Documentation note:** The freeze document §2 Parameter Governance should be read
with the understanding that PCM is a pre-pipeline gate whose mode determines whether
the described pipeline (Stage 2 → YAML/readiness → B validator → reconciler) is
reached. Under the new default (`true`), PCM is advisory and the pipeline is
reached. Under the opt-out fallback (`false`), PCM hard-blocks and the pipeline is
bypassed.

### 11.3 AOExecutionState scope (PENDING Phase 8.1.3)

**Discovery:** Phase 8.1.2 Step 1 audit §2 revealed that `AOExecutionState`
(`core/analytical_objective.py:262-271`) is not a unification of the five
state machines as the freeze document §2 implies. It is a new, additional execution
ledger that covers chain progress (tool-by-tool step tracking), while
`ClarificationContract` and `ExecutionContinuation` persist independently under
separate `ao.metadata` keys with zero connection to `AOExecutionState`.

The Round 1.5 audit Class E full identified five supposedly independent state
machines (ClarificationContract, ExecutionReadiness, AO scope,
ExecutionContinuation, Evaluator follow-up). Phase 6.E canonical execution state
resolved 1 of 5 (AO scope → bidirectional sync with AOExecutionState), but
ExecutionContinuation and ClarificationContract remain fully independent, and
Evaluator follow-up was never a distinct state machine.

**Status: PENDING.** Phase 8.1.3 will audit the five state-machine co-design and
produce a scoping decision (merge, synchronize, or document as intentional
separation). This errata entry is a placeholder until Phase 8.1.3 closes.

### 11.4 Spatial component layer assignment (Cosmetic)

**Discovery:** Phase 8.1.2 Step 1 audit §3 found that `GeometryMetadata`
(`core/task_state.py:141`), `SpatialEmissionLayer` (`core/spatial_emission.py:69`),
and `SpatialEmissionCandidate` (`core/spatial_emission.py:141`) are not explicitly
assigned to an architecture layer in the freeze document. Code-level evidence
confirms they belong to **Layer 4 (Agent Decision)**, not Layer 3 (Domain Schema):
they carry `provenance`, `reason_code`, and `confidence` diagnostic fields; they are
consumed exclusively by Layer 4 components (readiness.py, router.py,
spatial_emission_resolver.py); and Layer 3 (`emission_domain_schema.yaml`,
`emission_schema.py`) has zero spatial references.

**Severity:** Low. No code change needed. The three-path spatial data-flow contract
described in freeze doc §2 and §5 is accurate. Only the layer assignment is missing
from documentation.

**Status:** Cosmetic, low priority. Corrected in this errata; paper writing can
reference this assignment.
