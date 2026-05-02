# v1 Architecture Freeze Reality Audit

**Date:** 2026-05-02
**Branch:** `phase3-governance-reset`
**Scope:** Recon only — no code changes, no commits beyond this document.

This audit verifies the v1 architecture freeze document
(`docs/architecture/emissionagent_v1_architecture_freeze.md`, commit `d2b36f5`)
against the actual codebase on `phase3-governance-reset`. It targets four
specific potential gaps raised during Phase 4–7 design work.

---

## §1 Audit 1: PCM Current Real State

### 1.1 Freeze Document Claim

The freeze document §2 Parameter Governance describes a "layered contract pipeline"
(Stage 2 → YAML/readiness → B validator → reconciler) but **never mentions PCM**
(Parameter Collection Module). The document §7 Explicit Non-Claims lists "PCM" among
components that Phase 8.1 does not change, but makes no statement about PCM's
current role in the governance pipeline.

### 1.2 Code-Level Evidence

#### 1.2.1 PCM Configuration

**File:** `config.py:189`

```python
self.enable_llm_decision_field = os.getenv("ENABLE_LLM_DECISION_FIELD", "false").lower() == "true"
```

There is no dedicated `ENABLE_PCM` or `PCM_MODE` flag. PCM behavior is gated by
`ENABLE_LLM_DECISION_FIELD`, which defaults to `false`. The semantics:

| Flag State        | PCM Mode       | Behavior                                        |
|-------------------|----------------|--------------------------------------------------|
| `false` (default) | Hard-block (Option C) | PCM probes optional slots, blocks execution with `proceed=False` |
| `true`            | Advisory (Option B)   | PCM computes `pcm_advisory` dict, sets `should_proceed=True`, injects into Stage 2 LLM payload |

This unifies Options B and C from the Phase 4 redesign document under one flag.

#### 1.2.2 PCM Logic Location

PCM has **no standalone module**. Logic is embedded in two contracts:

**Wave 1 (non-split):** `core/contracts/clarification_contract.py`

- `_resolve_collection_mode()` (line 1427): Activates PCM for three triggers:
  `confirm_first_signal`, `missing_required_at_first_turn`, `unfilled_optional_no_default_at_first_turn`
- `_get_unfilled_optionals_without_default()` (line 1462): Checks only YAML declarative
  defaults (not runtime defaults), so `model_year` (runtime default 2020) still triggers probes
- **Short-circuit (hard-block, lines 446–463):** Sets `pending_decision = "probe_optional"`,
  builds probe question, `should_proceed = False`
- **Short-circuit (advisory, lines 434–445):** Sets `should_proceed = True`,
  records PCM advisory delta

**Wave 2 (contract-split):** `core/contracts/execution_readiness_contract.py`

- `_classify_missing_optionals()` separates optionals into `no_default`, `resolved_by_default`, etc.
  Unlike Wave 1, this IS aware of `has_runtime_default()`
- **Short-circuit (hard-block, lines 375–656):** Persists `PARAMETER_COLLECTION` continuation state,
  returns `proceed=False`
- **Short-circuit (advisory, lines 349–374):** Sets `force_proceed_reason = "advisory_mode"`, proceeds

#### 1.2.3 PCM Short-Circuit Mechanism in Router

**File:** `core/governed_router.py:240–257`

```python
for contract in self.contracts:
    interception = await contract.before_turn(context)
    ...
    if not interception.proceed:
        result = interception.response or RouterResponse(text="")
        break  # <-- PCM hard-block exits here, Stage 2 / recon never reached
```

When PCM returns `proceed=False` (default mode), the loop breaks at line 257.
The reconciler is never called.

**File:** `core/governed_router.py:266–268`

```python
if result is None:
    if bool(getattr(get_config(), "enable_llm_decision_field", False)):
        decision_result = self._consume_decision_field(context, trace)
```

This outer gate means `_consume_decision_field()` (which calls the reconciler at line 912)
is **never entered** when `ENABLE_LLM_DECISION_FIELD=false` (default). The code falls through
to `_maybe_execute_from_snapshot` (line 273) or `inner_router.chat` (line 281).

**File:** `core/intent_resolver.py:154`

When `PendingObjective.PARAMETER_COLLECTION` is active, `_pending_tool_name()` returns
the already-resolved tool from the AO's `tool_intent`, short-circuiting fresh intent resolution.

#### 1.2.4 PCM Telemetry

PCM telemetry is **absent from `core/trace.py`**. There are zero `TraceStepType` values
for PCM short-circuit, `parameter_collection`, or `pcm_advisory`.

PCM telemetry lives in contract-level structs:

- `ClarificationTelemetry` (`clarification_contract.py:62–141`): fields `collection_mode`,
  `pcm_trigger_reason`, `probe_optional_slot`, `probe_turn_count`, `probe_abandoned`,
  `pcm_advisory`, `pcm_advisory_delta`
- `ExecutionReadinessContract` telemetry (execution_readiness_contract.py:961–1019):
  includes PCM continuation state via `execution_continuation` fields

#### 1.2.5 30-Task Smoke Telemetry

**Smoke suite status:** The full smoke suite (`python3 -m evaluation.run_smoke_suite`)
fails with `AttributeError: 'tuple' object has no attribute 'items'` in
`evaluation/eval_normalization.py:86` — a pre-existing evaluation bug.

**End2end component (10 tasks):** Ran successfully (9/10 completed, `completion_rate=0.9`).
Key findings:

| Metric | Value | Interpretation |
|--------|-------|----------------|
| `clarification_contract_metrics.trigger_count` | **0** | Clarification contract never activated on any task |
| `clarification_contract_metrics.stage2_hit_rate` | **0.0** | Stage 2 LLM never invoked |
| `clarification_contract_metrics.short_circuit_rate` | **0.0** | PCM short-circuit never triggered |
| Per-task `collection_mode` | **None** (all 10) | PCM collection mode never activated |
| Per-task `governed_router_used` | **None** (all 10) | Governed router bypassed; tasks used `mode="tool"` direct path |

**Root cause:** The end2end `mode="tool"` evaluation path bypasses the governed router
entirely. PCM, Stage 2, and the reconciler only execute through the governed router
contract pipeline (`governed_router.py:241–257`). These 10 single-turn emission factor
queries with all required parameters supplied do not exercise parameter collection.

**Impact on this audit:** The standard 30-task smoke cannot produce PCM short-circuit
telemetry because (a) the end2end samples are complete-parameter queries that don't
trigger PCM, and (b) the `mode="tool"` evaluation path skips the governed router.
A proper PCM telemetry benchmark would require multi-turn samples with intentionally
missing optional parameters, run through the governed router path.

### 1.3 Conclusion

**PCM in production (default) mode is hard-block (Option C).**
It prevents Stage 2 LLM invocation and reconciler arbitration on ~83% of tasks
where optional parameters are missing (per the Phase 4 design doc estimate).

**PCM in advisory mode (Option B) is opt-in via `ENABLE_LLM_DECISION_FIELD=true`.**
The decision field is the Phase 4 redesign doc's mechanism for switching between
Options B and C.

### 1.4 Gap vs. Freeze Document

| Gap | Severity |
|-----|----------|
| Freeze doc §2 Parameter Governance describes a "layered contract pipeline" (Stage 2 → YAML → B → reconciler) but **omits PCM entirely**. In default mode, PCM preempts this entire pipeline. | **High** |
| Freeze doc §7 lists "PCM" under Non-Claims as unchanged by Phase 8.1, but does not state PCM's current mode (hard-block vs advisory). Readers cannot reconstruct the actual governance flow. | **Medium** |
| Freeze doc §3 Principle 3 says "B validator is advisory and filtering only." PCM is not mentioned among the components that CAN hard-block, yet it does. | **Medium** |

---

## §2 Audit 2: AOExecutionState Five-State-Machine Unification

### 2.1 Freeze Document Claim

Freeze doc §2 Canonical Execution State:

> "AO-scoped canonical execution state records tool-chain progress with step
> status, effective arguments, result references, chain cursor position, and
> revision provenance."

The freeze doc §3 item 6 implies canonical execution state is one of the pillars
that tool execution is "grounded in." §4 lists it as a "Final Closed Capability."

### 2.2 The Five State Machines (Round 1.5 Class E Full)

The Round 1.5 audit identified five supposedly independent state machines that
the Phase 6.E canonical state was meant to unify:

1. **ClarificationContract** — clarification pending state, missing slots, probe state
2. **ExecutionReadiness** — readiness gate disposition, tool preconditions
3. **AO scope** — AO lifecycle, classification, relationship, tool intent
4. **ExecutionContinuation** — pending objective, next tool in chain, probe count
5. **Evaluator follow-up** — post-execution LLM follow-up state

### 2.3 AOExecutionState Actual Schema

**File:** `core/analytical_objective.py:262–271`

```python
@dataclass
class AOExecutionState:
    objective_id: str
    planned_chain: List[str]
    chain_cursor: int
    steps: List[ExecutionStep]        # tool_name, status, effective_args, result_ref, source, revision_epoch
    revision_epoch: int
    chain_status: str                 # "active" | "complete" | "failed" | "abandoned"
    last_updated_turn: Optional[int]
    provenance: Dict[str, Any]
```

**File:** `core/analytical_objective.py:202–218`

```python
@dataclass
class ExecutionStep:
    tool_name: str
    status: ExecutionStepStatus       # PENDING | COMPLETED | SKIPPED | FAILED | INVALIDATED
    effective_args: Dict[str, Any]
    result_ref: Optional[str]
    error_summary: Optional[str]
    source: str                       # "projected_chain" | "tool_call" | "idempotent_skip" | "manual"
    created_turn: Optional[int]
    updated_turn: Optional[int]
    revision_epoch: int
    provenance: Dict[str, Any]
```

The schema matches the freeze doc claim. The question is whether it **unifies**
the five state machines or is a **new, additional** state machine.

### 2.4 Per-Machine Audit

#### 2.4.1 ClarificationContract — (c) No Connection

**File:** `core/contracts/clarification_contract.py`

- State storage: `ao.metadata["clarification_contract"]` — standalone dict
- Fields: `pending`, `missing_slots`, `followup_slots`, `probe_abandoned`,
  `collection_mode`, `pcm_trigger_reason`, `pending_decision`, etc.
- **Zero imports** or references to `AOExecutionState`, `ensure_execution_state`,
  or `execution_state`
- The only cross-reference is that `ExecutionReadinessContract` reads
  clarification_contract state

**Classification: (c)** — Fully independent. Never reads or writes AOExecutionState.

#### 2.4.2 ExecutionReadiness — (a) Reads for One Guard Only

**File:** `core/contracts/execution_readiness_contract.py:87–114`

- Calls `ensure_execution_state(current_ao)` imported from `core.ao_manager`
- **Only for the Phase 6.E.3 canonical chain handoff guard** — checks `chain_cursor`
  and `steps` to decide whether to hand off to the next tool in the chain
- Does NOT write AOExecutionState
- The contract's primary decision logic comes from ClarificationContract state
  and ExecutionContinuation (independent metadata keys), not from AOExecutionState

**Classification: (a)** — Reads AOExecutionState, but only for one narrow guard clause.

#### 2.4.3 AO Scope — (b) Bidirectional Sync

**File:** `core/ao_manager.py:1608–1689`

- `_derive_execution_state(ao)` builds AOExecutionState FROM AO fields:
  `tool_intent.projected_chain` and `tool_call_log` (lines 1613–1621)
- AO is the **primary** state machine; AOExecutionState is a **derived** secondary layer
- `_sync_execution_state_telemetry()` (`core/contracts/oasc_contract.py:398`)
  reads AOExecutionState and writes turn results INTO it

**Classification: (b)** — AO scope remains the source of truth. AOExecutionState is
derived from AO and synced back as telemetry. Not a unification — a derived view.

#### 2.4.4 ExecutionContinuation — (c) No Connection

**File:** `core/execution_continuation.py:15–32`

- State storage: `ao.metadata["execution_continuation"]` — **different key** from
  `ao.metadata["execution_state"]`
- Fields: `pending_objective` (NONE | PARAMETER_COLLECTION | CHAIN_CONTINUATION),
  `pending_slot`, `pending_next_tool`, `pending_tool_queue`, `probe_count`,
  `probe_limit`, `abandoned`, `updated_turn`
- Despite `_derive_execution_state`'s docstring claiming "and continuation" (line 1609),
  the implementation (lines 1608–1689) **never reads** from `ExecutionContinuation`
  or `ao.metadata["execution_continuation"]`
- `ensure_execution_state` (`ao_manager.py:1586`) checks `ao.metadata.get("execution_state")`,
  NOT `ao.metadata.get("execution_continuation")`
- Both track "chain position" independently: ExecutionContinuation is forward-looking
  (what to do next), AOExecutionState is historical+current (what happened)

**Classification: (c)** — Fully independent, parallel state machine. Lives under
a different metadata key, neither reads the other.

#### 2.4.5 Evaluator Follow-Up — (c) Does Not Exist

No `Evaluator`, `Assessor`, or `PostExecution` class exists anywhere in `core/`.
The closest patterns:

- `router.py:11204–11228`: `follow_up_response` in the normal LLM chat loop
- `governed_router.py:808`: `_retain_pending_followups_after_direct_execution()` —
  writes to `ao.metadata["clarification_contract"]["followup_slots"]`, a sub-feature
  of ClarificationContract
- `router_render_utils.py:123–132`: `_append_follow_up_section()` — prompt rendering helper

**Classification: (c)** — "Evaluator follow-up" was never a distinct state machine.

### 2.5 Who Reads/Writes AOExecutionState

| Consumer | File:Line | Action |
|----------|-----------|--------|
| `check_canonical_execution_state` | `ao_manager.py:648` | Reads — duplicate suppression |
| `should_prefer_canonical_pending_tool` | `ao_manager.py:735` | Reads — chain cursor |
| `detect_revision_delta_telemetry` | `ao_manager.py:800` | Reads — fingerprint comparison |
| `apply_revision_invalidation` | `ao_manager.py:1028` | Reads AND mutates — invalidates steps, resets cursor |
| `ensure_execution_state` | `ao_manager.py:1586` | Creates/loads — writes to `ao.metadata["execution_state"]` |
| `_derive_execution_state` | `ao_manager.py:1608` | Derives from AO fields (tool_intent, tool_call_log) |
| `_sync_execution_state_telemetry` | `oasc_contract.py:398` | Reads + writes turn results |
| `GovernedToolExecutor.execute` | `governed_router.py:66` | Reads — duplicate suppression via `check_canonical_execution_state` |

**`core/router.py` itself has zero references** to `AOExecutionState`,
`ensure_execution_state`, or `execution_state`. Interaction is through the
governed router wrapper and contracts.

### 2.6 Conclusion

**AOExecutionState is NOT a unification of the five state machines.**
It is a **new, additional execution ledger** added alongside the existing machines.

| State Machine           | Still Exists? | Data Location                        | Connected to AOExecutionState? |
|-------------------------|---------------|--------------------------------------|--------------------------------|
| ClarificationContract   | Yes           | `ao.metadata["clarification_contract"]` | No                             |
| ExecutionContinuation   | Yes           | `ao.metadata["execution_continuation"]` | No                             |
| AO scope                | Yes           | `AnalyticalObjective` fields + `AOManager` | Bidirectional sync (derived view) |
| ExecutionReadiness      | Yes           | Same as ClarificationContract + ExecutionContinuation | Reads for one guard clause |
| Evaluator follow-up     | Never existed | N/A                                  | N/A                            |

### 2.7 Gap vs. Freeze Document

| Gap | Severity |
|-----|----------|
| Freeze doc §2 implies canonical execution state is THE execution state. In reality, it is ONE execution state ledger coexisting with two fully independent state machines (ClarificationContract, ExecutionContinuation). | **High** |
| Freeze doc §4 asserts canonical execution state as a "Final Closed Capability." The capability IS closed (AOExecutionState is feature-complete for what it does), but its scope is narrower than the freeze doc implies — it covers chain progress, not all execution state. | **Medium** |
| ExecutionContinuation persists independently under a different metadata key — chain position is tracked in two places with no synchronization. | **Medium** |

---

## §3 Audit 3: Phase 7 Spatial Component Layer归属

### 3.1 Freeze Document Claim

Freeze doc §2 Spatial Data-Flow Contract and §5 Geometry and Data-Flow Final
Architecture describe spatial components (`spatial_emission_layer`,
`GeometryMetadata`, join-key resolution) as part of the data-flow architecture.
The document does not explicitly assign these to a numbered architecture layer.

### 3.2 Component Definitions

All three components are pure `@dataclass` types with no decision logic:

| Component | File | Line | Fields |
|-----------|------|------|--------|
| `GeometryMetadata` | `core/task_state.py` | 141 | `geometry_type`, `geometry_columns`, `coordinate_columns`, `join_key_columns`, `confidence`, `evidence`, `limitations` |
| `SpatialEmissionLayer` | `core/spatial_emission.py` | 69 | `layer_available`, `spatial_product_type`, `source_file_path`, `geometry` (SpatialEmissionGeometry), `provenance`, `reason_code`, etc. |
| `SpatialEmissionCandidate` | `core/spatial_emission.py` | 141 | `candidate_type`, `source_file_contexts`, `geometry` (SpatialEmissionGeometry), `join_key_match_quality`, `provenance`, `reason_code` |
| `SpatialEmissionGeometry` | `core/spatial_emission.py` | 15 | `geometry_type`, `geometry_columns`, `coordinate_columns`, `join_key_columns`, `geometry_source`, `confidence`, `evidence`, `limitations` |

### 3.3 Call-Chain Evidence

```
┌─ Layer 4 (Agent Decision) ──────────────────────────────────────────┐
│                                                                       │
│  analyze_file (tool)                                                  │
│    → produces GeometryMetadata in FileContext                         │
│         (core/task_state.py:1018)                                     │
│    → stored via SessionContextStore                                   │
│         (core/context_store.py:505, 548)                              │
│                                                                       │
│  spatial_emission_resolver (core/spatial_emission_resolver.py)        │
│    → reads GeometryMetadata from FileContext                          │
│    → produces SpatialEmissionCandidate / SpatialEmissionLayer         │
│         (line 83, 218, 810)                                           │
│                                                                       │
│  readiness.py (core/readiness.py)                                     │
│    → consumes SpatialEmissionCandidate (line 897–906)                 │
│    → checks layer_available (line 855–861)                            │
│    → returns BlockedReason with spatial diagnostics (line 1404–1407)  │
│    → build_spatial_emission_reason() (line 736)                       │
│                                                                       │
│  router.py (core/router.py)                                           │
│    → injects spatial_emission_layer into tool params (line 891, 897)  │
│                                                                       │
│  tool_dependencies.py (core/tool_dependencies.py)                     │
│    → check_road_geometry_from_metadata() (line 336)                   │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘

┌─ Layer 3 (Domain Schema) ────────────────────────────────────────────┐
│                                                                       │
│  emission_domain_schema.yaml (config/emission_domain_schema.yaml)     │
│    → 0 spatial/geometry references                                    │
│  emission_schema.py (core/contracts/emission_schema.py)               │
│    → 0 spatial references                                             │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘

┌─ Tools (Layer 5) ─────────────────────────────────────────────────────┐
│                                                                        │
│  Tools import SpatialDataPackage from core/spatial_types.py            │
│  (a separate, render-oriented type, NOT the agent diagnostic types)    │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

### 3.4 Evidence for Layer 4归属

1. **Domain schema (Layer 3) has zero spatial awareness.** `emission_domain_schema.yaml`
   defines 6 dimensions (vehicle_type, pollutant, model_year, road_type, season,
   meteorology) with no spatial dimension. `emission_schema.py` has no spatial references.

2. **These types represent agent decision state, not domain data.** They carry
   `provenance`, `reason_code`, and `confidence` fields — diagnostic metadata
   characteristic of agent reasoning, not domain modeling.

3. **They are consumed exclusively by Layer 4 components.** readiness.py, router.py,
   spatial_emission_resolver.py are all agent orchestration/decision modules. Tools
   consume a different type (`SpatialDataPackage` from `core/spatial_types.py`).

4. **They participate in agent gating.** `build_spatial_emission_reason()` (readiness.py:736)
   uses spatial reason codes to build `BlockedReason` objects that gate tool execution.

5. **Dependency direction is unidirectional.** Layer 3 schema is read by Layer 4,
   but spatial types are never referenced by Layer 3.

### 3.5 Conclusion

**GeometryMetadata, SpatialEmissionLayer, and SpatialEmissionCandidate are Layer 4
(Agent Decision) components,** parallel to readiness, canonical execution state, and
reconciler — NOT Layer 3 domain schema parallel to `emission_domain_schema.yaml`.

### 3.6 Gap vs. Freeze Document

| Gap | Severity |
|-----|----------|
| Freeze doc is **correct** about the spatial data-flow contract. The three paths (direct, join-key, missing geometry) are accurately described. | **None** |
| Freeze doc does not assign spatial types to a numbered layer. This is a documentation gap, not a code gap — the implementation is clean. | **Low** |

---

## §4 Audit 4: Reconciler Effectiveness Under PCM

### 4.1 Freeze Document Claim

Freeze doc §2 Parameter Governance:

> "The reconciler arbitrates between LLM, YAML/readiness, and validator evidence
> with explicit rules and traceable source labels."

Freeze doc §3 Principle 4:

> "The reconciler arbitrates between evidence sources; it is not 'P2 always wins.'"

### 4.2 Reconciler Interface

**File:** `core/contracts/reconciler.py:377–383`

```python
def reconcile(
    p1: Stage2RawSource,        # Stage 2 LLM decision
    p2: Dict[str, Any],         # YAML stage 3 contract state
    p3: ReadinessGateState,     # ERC readiness disposition
    b_result: Optional[ContractGroundingResult] = None,  # B validator filter
    tool_name: str = "",
) -> ReconciledDecision:
```

The reconciler takes **4 inputs** (P1, P2, P3, optional B). PCM is NOT an input.
The reconciler has **zero awareness** of:
- Whether PCM is in hard-block or advisory mode
- Whether `collection_mode` is active
- What `pcm_advisory` recommended
- Whether `ENABLE_LLM_DECISION_FIELD` is true or false

### 4.3 Reconciler Call Chain

**File:** `core/governed_router.py:888–912`

```python
# Lazy import inside _consume_decision_field()
from core.contracts.reconciler import (
    build_p1_from_stage2_payload,
    build_p2_from_stage3_yaml,
    build_p3_from_readiness_gate,
    filter_stage2_missing_required,
    reconcile,
)

p1 = build_p1_from_stage2_payload(stage2_payload, is_valid=True)
stage3_yaml = context.metadata.get("stage3_yaml")
p2 = build_p2_from_stage3_yaml(stage3_yaml)
readiness_gate = context.metadata.get("readiness_gate") or ...
p3 = build_p3_from_readiness_gate(readiness_gate)
b_result = filter_stage2_missing_required(tool_name, p1.missing_required) if ...

reconciled = reconcile(p1, p2, p3, b_result=b_result, tool_name=tool_name)
```

The ONLY production caller of `reconcile()` is `governed_router.py:912`.

### 4.4 Gates That Prevent Reconciler Invocation

| Gate | File:Line | Condition | Effect |
|------|-----------|-----------|--------|
| **PCM hard-block** | `governed_router.py:255–257` | Any contract returns `proceed=False` | Loop breaks → reconciler never reached |
| **Decision field gate** | `governed_router.py:267` | `enable_llm_decision_field` is `False` | `_consume_decision_field` never entered |
| **No Stage 2 decision** | `governed_router.py:877` | Stage 2 LLM was not called or produced no valid decision | `_consume_decision_field` returns `None` |
| **Validation failure** | `governed_router.py:886` | F1 validation fails on decision dict | `_consume_decision_field` returns `None` |

### 4.5 Effective Invocation Percentage

| Scenario | Reconciler Called? | Estimated Task % |
|----------|-------------------|-------------------|
| **Production (default mode)**: hard-block PCM active | **Never** | **~83%** of tasks with unfilled optionals |
| **Production (default mode)**: no unfilled optionals | **Never** (line 267 gate is `False`) | **~17%** of tasks |
| **Advisory mode**: Stage 2 called, valid decision, no hard-block | **Yes** | ~50–70% of advisory-mode paths |
| **Advisory mode**: no Stage 2 call needed | **No** (line 877 early return) | ~30–50% of advisory-mode paths |

**Key finding:** In the production default mode (`ENABLE_LLM_DECISION_FIELD=false`),
the reconciler is invoked on **0% of task paths**. The line 267 gate and PCM
hard-block together ensure `_consume_decision_field` is never reached.

### 4.6 Conclusion

**The reconciler is dead code in production (default) mode.**
It only activates when `ENABLE_LLM_DECISION_FIELD=true`, which is opt-in.

### 4.7 Gap vs. Freeze Document

| Gap | Severity |
|-----|----------|
| Freeze doc §2 describes the reconciler as an active component of the parameter governance pipeline. In production mode, it is never invoked. | **Critical** |
| Freeze doc §3 Principle 4 ("reconciler arbitrates between evidence sources") is factually correct about the reconciler's design, but misleading about its operational relevance. | **High** |
| The freeze doc never mentions that reconciler activation depends on `ENABLE_LLM_DECISION_FIELD=true`, which also changes PCM from hard-block to advisory. | **Critical** |

---

## §5 Comprehensive Judgment

### 5.1 The Seven Governance Principles: Code-Level Reality Check

| # | Freeze Doc Principle | Actually Implemented? | Evidence |
|---|---------------------|----------------------|----------|
| 1 | "LLM handles semantic understanding" | **Yes** | Stage 2 LLM in clarification_contract.py, Stage 1 in intent_resolver.py |
| 2 | "Framework enforces execution legality" | **Yes** | Readiness (readiness.py), contracts (oasc_contract.py, execution_readiness_contract.py), tool_dependencies.py |
| 3 | "B validator is advisory and filtering only" | **Yes** | `reconciler.py:386`: "B result is advisory only — it does not decide" |
| 4 | "Reconciler arbitrates between evidence sources" | **Design yes, operational no** | Reconciler logic exists and is sound, but is never invoked in production mode (see §4) |
| 5 | "Geometry is deterministic and never invented" | **Yes** | spatial_emission_resolver.py enforces deterministic key matching, point-only rejection |
| 6 | "Tool execution grounded in contracts, readiness, canonical execution state" | **Partially** | Readiness and contracts are active. Canonical execution state is only consumed for idempotency (duplicate guard) and chain handoff — not for general execution grounding |
| 7 | "Evaluation claims separated from architecture claims" | **Yes** | Freeze doc §6–7 explicitly separates evaluation results from architecture claims |

**Score: 5/7 fully implemented, 1 operational gap (reconciler), 1 partial (canonical state).**

### 5.2 What Is Really Locked vs. Documentation Claims

| Component | Freeze Doc Status | Code Reality | Verdict |
|-----------|------------------|--------------|---------|
| PCM | Not in governance pipeline description | Active hard-block, preempts Stage 2 + reconciler | **Major documentation gap** |
| Reconciler | Active governance component | Not invoked in production mode | **Critical documentation gap** |
| AOExecutionState | Unified canonical execution state | New, additional ledger; 2 of 4 actual state machines are fully independent | **Scope inflation in docs** |
| Spatial data-flow | Three deterministic paths | Code matches docs exactly | **Accurate** |
| Readiness | Dependency governance | Code matches docs | **Accurate** |
| Tool execution separation | Tools separate from semantics | Code matches docs | **Accurate** |
| B validator | Advisory only | Code matches docs | **Accurate** |
| Revision invalidation | Parameter revision cascades | Code matches docs (`apply_revision_invalidation` at ao_manager.py:1028) | **Accurate** |
| Idempotency | Duplicate suppression | Code matches docs | **Accurate** |

### 5.3 Gaps That Should Be Closed Before Phase 8.2

1. **[Critical] Reconciler is dead code in production.**
   Either: (a) enable `ENABLE_LLM_DECISION_FIELD=true` as production default and
   verify reconciler behavior on 180-task benchmark, or (b) update the freeze doc
   to state that reconciler is advisory-mode-only.

2. **[High] PCM is absent from the governance pipeline description.**
   The freeze doc §2 Parameter Governance should acknowledge PCM as a pre-Stage-2
   gate with hard-block semantics in default mode.

3. **[High] AOExecutionState scope should be narrowed in docs.**
   The freeze doc should clarify that AOExecutionState covers chain progress
   (not all execution state), and that ClarificationContract and ExecutionContinuation
   remain independent state machines.

4. **[Medium] ExecutionContinuation and AOExecutionState independently track chain position.**
   Consider merging or synchronizing them in a future phase to eliminate the
   dual-source-of-truth risk.

5. **[Low] Phase 7 spatial types should be explicitly assigned to Layer 4** in the
   architecture documentation, distinguishing them from Layer 3 domain schema and
   Layer 5 tool types (`SpatialDataPackage`).

---

## Appendix A: Key File Reference

| Component | File | Key Lines |
|-----------|------|-----------|
| PCM flag | `config.py` | 189 |
| PCM hard-block (Wave 1) | `core/contracts/clarification_contract.py` | 310–465 |
| PCM hard-block (Wave 2) | `core/contracts/execution_readiness_contract.py` | 349–656 |
| PCM short-circuit break | `core/governed_router.py` | 255–257 |
| Decision field gate | `core/governed_router.py` | 267 |
| Reconciler call | `core/governed_router.py` | 912 |
| Reconciler interface | `core/contracts/reconciler.py` | 377–383 |
| AOExecutionState | `core/analytical_objective.py` | 262–271 |
| ExecutionStep | `core/analytical_objective.py` | 202–218 |
| ExecutionContinuation | `core/execution_continuation.py` | 15–32 |
| _derive_execution_state | `core/ao_manager.py` | 1608–1689 |
| ensure_execution_state | `core/ao_manager.py` | 1586 |
| GeometryMetadata | `core/task_state.py` | 141 |
| SpatialEmissionLayer | `core/spatial_emission.py` | 69 |
| SpatialEmissionCandidate | `core/spatial_emission.py` | 141 |
| ParameterState (PCM) | `core/analytical_objective.py` | 406–413 |
| PendingObjective.PARAMETER_COLLECTION | `core/execution_continuation.py` | 10 |
