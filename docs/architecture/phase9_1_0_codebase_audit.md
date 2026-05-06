# Phase 9.1.0 Pre-Design — Codebase Reality Audit

**Date:** 2026-05-05
**Branch:** `phase3-governance-reset` (HEAD: `edca378`)
**Scope:** Read-only audit. No code changes, no refactoring, no tests, no commits beyond this document.

## Prerequisite Document Status

Three prerequisite documents were specified. None exist at the specified paths:

| Specified Path | Closest Equivalent | Status |
|---|---|---|
| `EmissionAgent_Core_Anchors.md` | `docs/architecture/emissionagent_v1_architecture_freeze.md` | Specified file does not exist |
| `docs/handoff/v1.5_upgrade_handoff.md` | `EMISSIONAGENT_CONVERSATION_UPGRADE_PLAN.md` (root) | Specified file does not exist |
| `docs/architecture/v1_freeze_reality_audit.md` | Exact match exists | OK |

This audit uses the closest equivalents. Any references below to "the upgrade document" refer to `EMISSIONAGENT_CONVERSATION_UPGRADE_PLAN.md` at project root. References to "Anchors" / "freeze document" refer to `docs/architecture/emissionagent_v1_architecture_freeze.md`.

---

## Task 1: 4 State Machines — Real Structure + Cross-Machine Hand-Off

### 1.1 AO State Machine

**Main files:**
- `core/analytical_objective.py` — AO data model (enums, `AnalyticalObjective` dataclass, `AOExecutionState`)
- `core/ao_manager.py` — AO lifecycle manager (create, activate, complete, revise, fail, abandon)
- `core/ao_classifier.py` — AO classification (NEW_AO vs CONTINUATION vs REVISION)

**AO Classification enum** — `core/ao_classifier.py:27-30`:
```python
class AOClassType(Enum):
    CONTINUATION = "continuation"   # line 28
    REVISION = "revision"           # line 29
    NEW_AO = "new_ao"               # line 30
```

**AO Lifecycle Status enum** — `core/analytical_objective.py:10-16`:
```python
class AOStatus(Enum):
    CREATED = "created"         # line 11
    ACTIVE = "active"           # line 12
    REVISING = "revising"       # line 13
    COMPLETED = "completed"     # line 14
    FAILED = "failed"           # line 15
    ABANDONED = "abandoned"     # line 16
```

**State transitions (all in `core/ao_manager.py`):**

| Transition | File:Line | Method | Condition |
|---|---|---|---|
| (initial) → CREATED | `ao_manager.py:232` | `create_ao()` | Always on creation |
| CREATED → ACTIVE | `ao_manager.py:251` | `activate_ao()` | status == CREATED |
| COMPLETED → REVISING | `ao_manager.py:253` | `activate_ao()` | status == COMPLETED (revision resume) |
| ACTIVE/REVISING → COMPLETED | `ao_manager.py:180` | `create_ao()` (implicit) | `_can_complete_ao()` returns True |
| ACTIVE/REVISING → COMPLETED | `ao_manager.py:206` | `create_ao()` (implicit) | block_reason == `execution_continuation_active` |
| ACTIVE/REVISING → ABANDONED | `ao_manager.py:216` | `create_ao()` (implicit) | `_can_complete_ao()` returns False, other block_reason |
| CREATED → ACTIVE (promote) | `ao_manager.py:302-303` | `complete_ao()` | `_can_complete_ao()` returns False, promoted before blocking |
| → COMPLETED | `ao_manager.py:313` | `complete_ao()` | `_can_complete_ao()` returns True |
| → REVISING | `ao_manager.py:339` | `revise_ao()` | Creates child AO with `AORelationship.REVISION` |
| → FAILED | `ao_manager.py:351` | `fail_ao()` | Unconditional |
| → ABANDONED | `ao_manager.py:363` | `abandon_ao()` | Unconditional |

**Persistence mechanism (3 layers):**

1. AO objects → `FactMemory.ao_history: List[AnalyticalObjective]` (`core/memory.py:92`) + `FactMemory.current_ao_id` (`core/memory.py:93`)
2. `FactMemory` → `MemoryManager._save()` (`core/memory.py:825`) → JSON at `data/sessions/history/{session_id}.json`
3. `ao.metadata: Dict[str, Any]` (`core/analytical_objective.py:523`) — sub-objects stored as raw dicts

**CRITICAL FINDING:** AO objects in `FactMemory.ao_history` are NOT serialized to `router_state/{session_id}.json`. The router's `to_persisted_state()` (`core/router.py:744`) serializes `context_store` and `live_state` bundles, but NOT `ao_history`. AO persistence depends on `FactMemory` being loaded separately from `data/sessions/history/{session_id}.json`. Process restart loses AO history unless this file is intact.

**Input data sources:** `user_message: str`, `AOClassification` from `OAScopeClassifier.classify()` (`core/ao_classifier.py:122`), `result.executed_tool_calls` after router execution

**Output writes to:** `AnalyticalObjective` fields (status, tool_call_log, artifacts_produced, parameters_used, failure_reason, constraint_violations, tool_intent, parameter_state, stance, metadata), `FactMemory` fields, `SessionContextStore`

**Cross-machine hand-off — `ao.metadata` keys:**

| Key | Written By (File:Line) | Read By (File:Line) |
|---|---|---|
| `"clarification_contract"` | `governed_router.py:883-900` | `ao_manager.py:432,444` |
| `"execution_continuation"` | `execution_continuation_utils.py:20` | `execution_continuation_utils.py:8` |
| `"execution_state"` | `ao_manager.py:1647`, `oasc_contract.py:656` | `ao_manager.py:1640-1642` |
| `"execution_continuation_transition"` | `oasc_contract.py:228-235` | Trace metadata only |
| `"chain_active_hold"` | `oasc_contract.py:283-306` | Trace metadata only |
| `"clarification_contract"` | `clarification_contract.py:620,1365` | `clarification_contract.py:625`, `governed_router.py:900` |
| `"parameter_snapshot"` | `clarification_contract.py:1362,1562` | `clarification_contract.py:662` |
| `"execution_readiness"` | `execution_readiness_contract.py:984,1110` | `execution_readiness_contract.py:before_turn` |
| `"last_revision_invalidation"` | `execution_readiness_contract.py:872` | Same contract |
| `"last_revision_delta_telemetry"` | `execution_readiness_contract.py:886` | Same contract |

**Cross-machine hand-off — `context.metadata` keys (per-turn):**

| Key | Written By | Consumed By |
|---|---|---|
| `"oasc"` | `oasc_contract.py:63-71` | `oasc_contract.py:79`, `governed_router.py:1211` |
| `"stage2_payload"` | ClarificationContract | `governed_router.py:931-932` |
| `"readiness_gate"` | ClarificationContract / ERC | `governed_router.py:965-968` |
| `"clarification"` | ClarificationContract | `governed_router.py:263-264,336-341` |
| `"reconciled_decision"` | `governed_router.py:1016-1024` | Trace/debug only |
| `"projected_chain"` | `governed_router.py:313-317` | Trace metadata |
| `"b_validator_filter"` | `governed_router.py:993` | Trace metadata |
| `"execution_continuation_transition"` | `execution_readiness_contract.py:431,495,744` | `oasc_contract.py:156` |
| `"canonical_chain_handoff"` | `execution_readiness_contract.py:109` | `intent_resolution_contract.py:100` |

**No single shared state object exists across the 4 machines.** Each reads/writes its own namespace in `ao.metadata` and `context.metadata`. There is no unifying `ConversationState` or equivalent.

---

### 1.2 Chain Projection

**Main file:** `core/contracts/oasc_contract.py` (761 lines)

**Chain projection logic in two places:**

A. **IntentResolver** — `core/intent_resolver.py`:
- `resolve_fast()` (~line 72): Resolves user message to `ToolIntent` with `projected_chain: List[str]`
- `_advance_chain_cursor()` (line 81): Reads `AOExecutionState.planned_chain`, advances cursor
- `_projected_chain_from_ao()` (line 299): Extracts existing projected_chain from `ao.tool_intent`

B. **ExecutionReadinessContract** — `core/contracts/execution_readiness_contract.py`:
- `before_turn()` (line 39): Reads `tool_intent.projected_chain` (line 120), normalizes, writes `ExecutionContinuation` with `CHAIN_CONTINUATION` objective, setting `pending_tool_queue` (lines 275-283)

**Scope: Multi-turn.** Evidence:
- `ExecutionContinuation.updated_turn: Optional[int]` (`core/execution_continuation.py:22`)
- `_refresh_split_execution_continuation()` runs every turn (`oasc_contract.py:145`)
- `chain_cursor` in `AOExecutionState` tracks across turns (`core/analytical_objective.py:266`)
- `_maybe_complete_ao_with_chain_gate()` (`oasc_contract.py:250`) keeps AO ACTIVE across turns with pending steps, includes `MAX_CHAIN_STALL_TURNS=5` guard (line 267)
- `test_projected_chain_persistence.py` explicitly tests cross-turn chain persistence

**Pending chain persistence:**
- Primary: `ao.metadata["execution_continuation"]` — written via `execution_continuation_utils.py:20`, read via `execution_continuation_utils.py:8`
- Secondary: `ao.metadata["execution_state"]` — written via `ao_manager.py:1647`, `oasc_contract.py:656`; contains `planned_chain`, `chain_cursor`, `steps`, `chain_status`

**Data structures representing projected chain:**
1. `ToolIntent.projected_chain: List[str]` — `core/analytical_objective.py:357` — semantic plan (e.g., `["calculate_macro_emission", "calculate_dispersion"]`)
2. `ExecutionContinuation.pending_tool_queue: List[str]` — `core/execution_continuation.py:15-23` — actionable queue
3. `AOExecutionState.planned_chain: List[str]` + `chain_cursor: int` — `core/analytical_objective.py:262-271` — canonical multi-turn ledger

**Chain hand-off to other machines:**
- ClarificationContract → ERC: via `context.metadata` (OASC writes `oasc`, clarification reads at `clarification_contract.py:183`)
- ERC → Chain Continuation: `context.metadata["execution_continuation_transition"]` → OASC reads at `oasc_contract.py:156`
- AOManager → ERC: `ensure_execution_state()` → ERC reads at `execution_readiness_contract.py:88-115`

---

### 1.3 Clarification Contract

**Main file:** `core/contracts/clarification_contract.py` (1755 lines)

**State storage (two tracks):**

Track A — `ao.metadata["clarification_contract"]` (written at line 1365): dict with `tool_name`, `parameter_snapshot`, `clarification_question`, `pending`, `missing_slots`, `rejected_slots`, `followup_slots`, `confirm_first_detected`, `pcm_trigger_reason`, `pending_decision`, `probe_optional_slot`, `probe_turn_count`, `probe_abandoned`

Track B — `ao.parameter_state` first-class fields (lines 1381-1436): `collection_mode`, `collection_mode_reason`, `awaiting_slot`, `probe_turn_count`, `probe_abandoned`, `required_filled`, `optional_filled`

**Trigger conditions:**
- `enable_clarification_contract` config must be True (line 178)
- Two entry paths (line 188-194):
  - **Resume** (`is_resume=True`): prior turn left `pending=True` in clarification_contract state
  - **Fresh** (`is_fresh=True`): classification is NEW_AO or REVISION
- PCM sub-trigger `_detect_confirm_first()` (line 1694): checks `clarification_confirm_first_signals` from config (`config.py:130-141`): "先确认", "先帮我确认", "先看看", "确认参数", etc. + regex `r"需要.{0,12}参数"` (line 1704)

**Decision dependencies (3-stage pipeline):**
1. Stage 1 (line 313): Deterministic parameter fill from `_extract_message_execution_hints()` — no LLM
2. Stage 2 (line 354-392): LLM intent + parameter resolution via `_run_stage2_llm()` (line 797)
3. Stage 3 (line 394-399): `StandardizationEngine` normalization via `_run_stage3()` (line 1090)

**Final decision tree (lines 423-585):**
1. `missing_required` or `rejected_slots` non-empty → `final_decision="clarify"`, `pending_decision="clarify_required"`
2. NOT `collection_mode` → `should_proceed=True`
3. `enable_llm_decision_field` flag on → `should_proceed=True` (advisory mode)
4. `unfilled_optionals_without_default` exists → probe or abandon (max probe_count=2)
5. Else → `should_proceed=True`

**"好的" / "对" / "继续" handling:**
- NO dedicated handler in clarification_contract.py for these Chinese phrases
- `AOClassifier._is_short_clarification_reply()` (`core/ao_classifier.py:360-384`): checks `confirm_words` set: `{"是", "否", "对", "不对", "好的", "嗯", "确认", "取消", "yes", "no", "ok", "okay"}`
- `ParameterNegotiation._FAST_PATH_CONFIRM_WORDS` (`core/parameter_negotiation.py:212`): `frozenset({"好", "是", "对", "yes", "ok", "嗯", "行"})` — fast-path confirm/decline
- When classified as short reply → CONTINUATION on existing AO → `_get_pending_state()` (line 622) reads persisted clarification_contract state → `is_resume` case
- The "继续" case flows through AO classifier as CONTINUATION on the existing AO

**Cross-machine reads from:**
- `context.metadata["oasc"]` (line 183) — AO classification
- `context.state_snapshot` (line 196) — TaskState from OASC
- `ao.metadata["clarification_contract"]` (line 625) — own prior state
- `context.metadata["stance"]` (line 239) — stance contract
- `inner_router.memory.fact_memory` (line 707, 1535) — session facts

**Cross-machine writes to:**
- `ao.metadata["clarification_contract"]` (line 1365)
- `ao.metadata["parameter_snapshot"]` (line 1362, 1562)
- `ao.tool_intent` (line 1395-1405)
- `ao.parameter_state` (line 1407-1436)
- `fact_memory.recent_vehicle/pollutants/year` (lines 1548-1555)
- `fact_memory.session_confirmed_parameters` (line 1557)
- `context.metadata["clarification"]` (line 509-511, 562-567, 573-584)

---

### 1.4 Reconciler

**Main file:** `core/contracts/reconciler.py` (513 lines)

**Key data structures:**
- `Stage2RawSource` (line 235) — P1 (LLM)
- `ReadinessGateState` (line 255) — P3 (readiness)
- `ReconciledDecision` (line 271) — output
- `ContractGroundingResult` (line 29) — B validator result

**Reconciler function:** `reconcile(p1, p2, p3, b_result, tool_name)` at line 377

**Invoke path (sole production caller):** `governed_router.py:1013` inside `_consume_decision_field()` (starting line 918):
```python
reconciled = reconcile(p1, p2, p3, b_result=b_result, tool_name=tool_name)
```

**Gates preventing reconciler invocation:**

| Gate | File:Line | Condition |
|---|---|---|
| Config flag | `governed_router.py:328` | `enable_llm_decision_field` must be True |
| Stage 2 payload | `governed_router.py:931-934` | `stage2_payload` must have `decision` dict |
| Fallback check | `governed_router.py:938-939` | Or `telemetry["stage2_decision"]` present |
| F1 validation | `governed_router.py:947-949` | `validate_decision()` must pass |

**Current production default:** `ENABLE_LLM_DECISION_FIELD` default = `"true"` (`config.py:191`) — reconciler IS active in production. (Changed from `"false"` at Phase 8.1.2 Step 3, documented in freeze doc errata §11.1.)

**State written before reconcile:** `context.metadata["stage2_payload"]`, `context.metadata["stage3_yaml"]`, `context.metadata["readiness_gate"]`

**State written after reconcile:** `context.metadata["reconciled_decision"]` (line 1016), `context.metadata["b_validator_filter"]` (line 993), trace steps: `reconciler_invoked`, `reconciler_proceed`, `decision_field_clarify`, `decision_field_deliberate`, `cross_constraint_violation`

**Internal reconcile rules (lines 430-512):**
- Rule A1: `p1.decision_value == "proceed"` AND F1 valid AND no p2/p3 conflict
- Rule A2: Triggers on non-empty `p2_missing` (always)
- Rule A3: p1 missing_required, b_result grounded empty, no p2/p3 conflict
- Rule A4: Triggers on p3 hard-block
- P3 force-proceed fallback
- P1 degrade fallback
- Default: clarify

---

## Task 2: ConversationState — Does It Exist?

**"ConversationState" does NOT exist anywhere in the codebase.** No class, variable, or import with this name.

**Closest existing mechanisms:**

### SessionContextStore — `core/context_store.py` (830 lines)

Session-scoped in-memory store for structured tool results. NOT AO-level state — it's the result-storage layer.

- `_store: Dict[str, StoredResult]` — keyed by `result_type:label` (line 66)
- `_history: List[StoredResult]` — all results in order
- `_current_turn_results` — transient, cleared per-turn
- `_analyzed_file_contexts` — multi-file geometry metadata

Lifecycle: created in `UnifiedRouter.__init__()` (`core/router.py:352`), persisted via `to_persisted_dict()` (line 558) → JSON.

### FactMemory — `core/memory.py:60`

Session-scoped `@dataclass`:
- `session_id` (line 63)
- `recent_vehicle`, `recent_pollutants`, `recent_year` (lines 64-66)
- `active_file`, `file_analysis` (lines 67-68)
- `ao_history: List[AnalyticalObjective]` (line 92)
- `current_ao_id` (line 93)
- `files_in_session` (line 87)
- `session_confirmed_parameters` (line 88)
- `cumulative_constraint_violations` (line 89)

### ao.metadata — the de-facto cross-turn state

All four state machines store their persistent state as independent dicts under separate keys on `ao.metadata` (`core/analytical_objective.py:523`). See Task 1.1 for the full key table.

**Key finding:** There is NO single shared state object. Each state machine writes to its own namespace in `ao.metadata` and `context.metadata`. No machine reads another machine's namespace directly — all cross-machine data flows through `context.metadata` orchestrated by `GovernedRouter.chat()`.

### NaiveRouter isolation from shared state

**NaiveRouter has NO access to ANY governance state.** Confirmed by grep across `core/naive_router.py`:
- Zero imports of: `SessionContextStore`, `MemoryManager`, `AOManager`, `AOExecutionState`, `ClarificationContract`, `OASCContract`, `ExecutionReadinessContract`, `reconciler`, any contract module, `context_store`, `ao_manager`
- No `.metadata` access
- State is only `self.history: List[Dict[str, str]]` (line 66) — pure user/assistant messages
- Persistence is only `self.history` via `to_persisted_state()` (line 73) to `naive_router_state/{session_id}.json`

### Session ID binding

- Router: `core/router.py:346` — `UnifiedRouter.__init__(self, session_id, ...)`
- Memory: `core/memory.py:63` — `FactMemory.session_id`
- AO: `core/analytical_objective.py:505` — `ao.session_id`
- API: `api/session.py:257-260` — sessions keyed by `session_id` in `self._sessions: Dict[str, Session]`
- Persistence: `router_state/{session_id}.json` (`api/session.py:112`), `naive_router_state/{session_id}.json` (`api/session.py:132`)
- CLI: `run_code.py:28` — `session_id="cli_session"`

---

## Task 3: AO 5-State — Current Real Implementation

### The "5 states" claim is incorrect

**`AOClassType` (`core/ao_classifier.py:27-30`) has exactly 3 states:**
```python
class AOClassType(Enum):
    CONTINUATION = "continuation"   # line 28
    REVISION = "revision"           # line 29
    NEW_AO = "new_ao"               # line 30
```

**REFINEMENT and TERMINATION do NOT exist anywhere in the codebase.** Grep for both strings across all `.py`, `.md`, `.yaml`, `.yml`, `.json` files returns zero matches.

### State-by-state reality check

| State | Enum Defined? | Real Transition Logic? | Status |
|---|---|---|---|
| NEW_AO | Yes — `ao_classifier.py:30` | Yes — `oasc_contract.py:377-386` calls `ao_manager.create_ao()` | Fully implemented |
| CONTINUATION | Yes — `ao_classifier.py:28` | Yes — `oasc_contract.py:368-369` reuses current AO | Fully implemented |
| REVISION | Yes — `ao_classifier.py:29` | Yes — `oasc_contract.py:370-375` calls `ao_manager.revise_ao()` (line 324-345), creates child AO with `AORelationship.REVISION` | Fully implemented |
| REFINEMENT | DOES NOT EXIST | DOES NOT EXIST | Absent |
| TERMINATION | DOES NOT EXIST | DOES NOT EXIST | Absent |

### The upgrade document claim (§1.3)

The claim states: "AO 5 状态机当前部分 (NEW_AO + CONTINUATION 2 状态)"

**Verdict:** **INCORRECT on both counts.**
1. There are exactly 3 states, not 5. REFINEMENT and TERMINATION are completely absent.
2. All 3 existing states have real transition logic — not just 2.

### The `classify()` pipeline — `core/ao_classifier.py:122-226`

1. Disabled check (line 129): if `enable_ao_classifier` is False → return NEW_AO
2. Rule Layer 1 (line 155-172, method at `ao_classifier.py:228-295`): deterministic rules
3. LLM Layer 2 (line 174-199, method at `ao_classifier.py:399-416`)
4. Fallback (line 203-226): if LLM fails → return NEW_AO

### AO state persistence across turns

AO state in `FactMemory.ao_history` is in-memory only within process lifetime. Cross-turn restore depends on `MemoryManager._load()` (`core/memory.py:893`) loading from `data/sessions/history/{session_id}.json`. The router's `to_persisted_state()` does NOT include `ao_history`.

---

## Task 4: Standardizer Fallback — Current Structure

### 6-Level Cascade — Implementation Map

| Level | Strategy Label | Confidence | Implementation (File:Line) |
|---|---|---|---|
| 1. Exact match | `"exact"` | 1.0 | `standardizer.py:255,324,399,448,506,557` |
| 2. Alias match | `"alias"` | 0.95 | Same dict lookup as Level 1, different strategy label |
| 3. Fuzzy match | `"fuzzy"` | Variable | `standardizer.py:268-284` (vehicle, threshold=70), 337-353 (pollutant, 80), 408-423 (season, 60), 457-472 (road_type, 60), 518-533 (meteorology, 75), 569-584 (stability, 75) |
| 4. LLM model | `"model"` | Variable | `standardization_engine.py:544-556` (engine fallthrough), 834-874 (model backend call) |
| 5. Default | `"default"` | 0.5 | `standardizer.py:425-432` (season), 474-481 (road_type) |
| 6. Abstain | `"abstain"` | 0.0 | `standardizer.py:296-304` (vehicle), 365-373 (pollutant), 535-541 (meteorology), 586-592 (stability); engine catch-all at `standardization_engine.py:561-569` |

### Fallback tier behavior

**Default tier (season, road_type only):**
- Returns `success=True` with default value (e.g., `season_default` from YAML)
- In engine: if `_should_accept_rule_result()` returns True (empty input or model disabled) → returns default immediately (`standardization_engine.py:542`)
- Caller (`standardize_batch`, line 621-622) assigns `standardized[key] = result.normalized` — execution proceeds with default

**Abstain tier (vehicle, pollutant, meteorology, stability_class, catch-all):**
- Returns `success=False`, `strategy="abstain"`, `confidence=0.0`, with suggestions
- In `standardize_batch()` (`standardization_engine.py:625-639`): raises `BatchStandardizationError` with `negotiation_eligible` determined by `_should_trigger_parameter_negotiation()` (line 935-954)
- The error propagates through `executor.py:224 → 350-359 → 231-251` → returns result dict with `error_type: "standardization"`, `negotiation_eligible: bool`
- Caller (router state loop) checks `result.get("negotiation_eligible")` and triggers parameter negotiation

### Clarification triggering mechanism

Exception-based, NOT callback or trace-based:
1. `standardization_engine.py:611-618` or `627-639`: `standardize_batch()` raises `BatchStandardizationError`
2. `executor.py:224`: `_standardize_arguments()` catches
3. `executor.py:350-359`: re-raises as `StandardizationError`
4. `executor.py:231-251`: returns error dict with `error_type: "standardization"`, `negotiation_eligible`, `trigger_reason`, `suggestions`
5. Caller reads `negotiation_eligible` and triggers parameter negotiation

### Claim: "Layer 1 data (89.3%, fallback tier 21.7%)"

**Neither 89.3 nor 21.7 appear anywhere in the codebase.** These are external benchmark measurements, not hardcoded constants. The code has no function or constant that computes or asserts these rates.

---

## Task 5: Stream Chunk Push Mechanism

### Chunk type list — `api/routes.py:277-440`

| Chunk type | File:Line | Content | Condition |
|---|---|---|---|
| `status` | `api/routes.py:310-313` | `"正在理解您的问题..."` | Always |
| `status` | `api/routes.py:318-323` | `"正在处理上传的文件..."` | If file uploaded |
| `status` | `api/routes.py:326-329` | `"正在分析任务..."` | Always |
| `heartbeat` | `api/routes.py:333, 348` | Empty heartbeat | Every 15s while processing |
| `text` | `api/routes.py:358-361` | 20-char typewriter chunks | Always |
| `chart` | `api/routes.py:379-382` | Full chart_data dict | If `turn.chart_data` |
| `table` | `api/routes.py:388-393` | table_data + download_file | If `turn.table_data` |
| `map` | `api/routes.py:401-404` | map_data dict | If `turn.map_data` |
| `done` | `api/routes.py:407-415` | session_id, mode, file_id, trace_friendly | Always |
| `error` | `api/routes.py:419-430` | content + error_code | On exception |

### Chunk push timing

Immediate (not batched):
- Status chunks have `await asyncio.sleep(0.1)` between them (lines 313, 323, 329)
- Text chunks have `await asyncio.sleep(0.05)` typewriter delay (line 362)
- Data chunks sent back-to-back with no delay (lines 379-404)
- No state-machine transition is pushed as a separate chunk — only trace data embedded in `done`'s `trace_friendly`

### No formal StreamChunk class

Chunks are inline raw dicts serialized via `json.dumps()`. No `StreamChunk` or `EventChunk` class exists. Test at `tests/test_api_route_contracts.py:383-435` validates chunk shapes by constructing equivalent dicts.

### G6 trace_friendly field naming — `core/trace.py:1158-1189`

`make_friendly_entry()` produces: `type` (line 1180), `step_type` (backward-compat alias, line 1181), `description` (line 1182), `status` (line 1183), `latency_ms` (optional, line 1188), `title` (optional, line 1186). Test at `tests/test_trace.py:840-866` validates `trace_friendly` carries `type` and `latency_ms`.

### ConversationState chunk type

**No ConversationState chunk type exists.** The only state-like information in the stream is `trace_friendly` inside the `done` chunk. If ConversationState writes need streaming to the frontend, a new chunk type would be required.

---

## Task 6: NaiveRouter vs GovernedRouter Boundary

### Class locations

| Class | File | Line |
|---|---|---|
| `NaiveRouter` | `core/naive_router.py` | 43 |
| `GovernedRouter` | `core/governed_router.py` | 160 |
| `UnifiedRouter` | `core/router.py` | 331 |

No shared base class. NaiveRouter is completely standalone.

### Shared resources

**LLM Client:**
- NaiveRouter: `naive_router.py:61` — `LLMClientService(temperature=0.0, purpose="agent")`
- GovernedRouter/UnifiedRouter: `router.py:353` — `get_llm_client("agent")` via `services/llm_client`
- **Separate instances.** No shared LLM state. No cross-contamination possible.

**Tool Registry:**
- NaiveRouter: `naive_router.py:62-64` — `get_registry()`; if empty calls `init_tools()`
- NaiveRouter filters to `get_tool_contract_registry().get_naive_available_tools()` only (line 98-105)
- GovernedRouter: accesses through `self.inner_router.executor`
- **Shared:** `get_tool_contract_registry()` returns same global singleton
- **Risk assessment:** The contract registry is read-only (no governance state stored). NaiveRouter filters to its allowed subset. No governance leak through this channel.

**Config:**
- NaiveRouter: indirect via `get_config()` — not stored as attribute
- GovernedRouter: `governed_router.py:164` — `self.runtime_config = get_config()`
- **Shared global singleton** (`config.py:get_config()`)
- **Config is read-only** for both routers. No governance data in config. Negligible leak risk.

### Governance data — verified NOT accessible to NaiveRouter

| Governance artifact | In NaiveRouter? | Evidence |
|---|---|---|
| `AOStatus` | NO | Not imported |
| `ao.metadata` | NO | Not referenced |
| `AOManager` | NO | Not imported |
| `SessionContextStore` | NO | Not imported |
| Any contract (`BaseContract`, `ClarificationContract`, `OASCContract`, etc.) | NO | Not imported |
| `reconciler` | NO | Not imported |
| `ExecutionContinuation` | NO | Not imported |
| `context_store` module | NO | Not imported |
| `MemoryManager` / `FactMemory` | NO | Not imported |

### Dispatch boundary — `api/session.py:80-103`

```python
async def chat(self, message, file_path=None, mode="full"):
    if mode == "naive":
        result = await self.naive_router.chat(...)
        self.save_naive_router_state()   # → naive_router_state/{session_id}.json
    else:
        result = await self.agent_router.chat(...)
        self.save_router_state(...)      # → router_state/{session_id}.json
```

Each router has its own persistence directory. Governance state never writes to `naive_router_state/`.

### Isolation enforcement points for v1.5 ConversationState

If ConversationState is added as governed-only:

1. **`api/session.py:80-103`** — The central dispatch. Naive-mode requests must never reach `agent_router.chat()`.
2. **`api/session.py:112` vs `132`** — Persistence paths are already separate.
3. **`core/naive_router.py` vs `core/governed_router.py`** — No shared mutable state exists.
4. **`tools/registry.py`** — The global `ToolRegistry` singleton is the ONLY shared mutable object. Currently safe (read-only contract metadata), but if ConversationState were to mutate tool availability, NaiveRouter must receive a snapshot. This is the only genuine isolation risk.

---

## Task 7: Tool Dependency Graph + Cross-Parameter Constraints

### Tool dependency graph

**Source of truth:** `config/tool_contracts.yaml` — each tool declares `dependencies.requires` and `dependencies.provides`

**Runtime structures:**
- `tools/contract_loader.py:93-102` — `ToolContractRegistry.get_tool_graph()` builds `{tool_name: {requires, provides}}`
- `core/tool_dependencies.py:35-37` — `TOOL_GRAPH` populated at module import time
- `core/tool_dependencies.py:20-30` — `CANONICAL_RESULT_ALIASES` normalizes legacy tokens

**Graph edges:**

| Tool | Requires | Provides |
|---|---|---|
| `query_emission_factors` | [] | `emission_factors` |
| `calculate_micro_emission` | [] | `emission` |
| `calculate_macro_emission` | [] | `emission` |
| `analyze_file` | [] | `file_analysis` |
| `clean_dataframe` | [] | `data_quality_report` |
| `query_knowledge` | [] | `knowledge` |
| `calculate_dispersion` | [`emission`] | `dispersion` |
| `analyze_hotspots` | [`dispersion`] | `hotspot` |
| `render_spatial_map` | []* | `visualization` |
| `compare_scenarios` | [] | `scenario_comparison` |

*`render_spatial_map` has dynamic requirements: if `layer_type` is `emission`/`dispersion`/`hotspot`, requires that token (`tool_dependencies.py:123-126`).

### Forward validation caller path

1. `core/router.py:10900-10906` — During EXECUTING stage: `_evaluate_cross_constraint_preflight()` first, returns early if blocked
2. `core/router.py:10907-10915` — Then `_assess_selected_action_readiness()` invoking ERC
3. ERC checks `required_result_tokens` against context_store, `requires_geometry_support`, uses `validate_tool_prerequisites()` (`tool_dependencies.py:184-268`)
4. `core/executor.py:224` — `_standardize_arguments()` runs cross-constraint validation during standardization

### Cross-turn awareness

**Yes, Turn 2 can know Turn 1 results are available.**

- `SessionContextStore.get_result_availability()` (`context_store.py:345-399`): queries stored results by canonical token type, includes staleness tracking
- `validate_tool_prerequisites()` (`tool_dependencies.py:203-234`): calls `context_store.get_result_availability()` with `include_stale=False`
- `_infer_result_tokens_from_payload()` (`tool_dependencies.py:73-98`): infers tokens from `_last_result` payload in arguments
- **Caveat:** Only within the governed state loop. The conversation fast path (`router.py:623-734`) does NOT consult context_store — only reads `fact_memory` for `last_tool_name` and `active_file`.

### Cross-parameter constraints

**Config file:** `config/cross_constraints.yaml` (93 lines, version 1.1)

**5 defined constraints:**

| # | Constraint Name | Type | Fields | Severity |
|---|---|---|---|---|
| 1 | `vehicle_road_compatibility` (line 4) | `blocked_combinations` | vehicle_type + road_type | Hard violation |
| 2 | `vehicle_pollutant_relevance` (line 17) | `conditional_warning` | vehicle_type + pollutants | Warning |
| 3 | `pollutant_task_applicability` (line 35) | `conditional_warning` | pollutant + tool_name | Warning |
| 4 | `season_meteorology_consistency` (line 55) | `consistency_warning` | season + meteorology | Warning |
| 5 | `motorcycle_dispersion_applicability` (line 76) | `conditional_warning` | vehicle_type + tool_name | Warning |

**Runtime validator:** `services/cross_constraints.py`:
- `CrossConstraintValidator.__init__` (line 75): loads YAML
- `validate()` (line 88): iterates constraints, resolves from `standardized_params` and context
- `CrossConstraintResult` (line 57): `all_valid`, `violations`, `warnings`

**Trigger timing (two paths):**

Path A — during standardization (`standardization_engine.py:641-664`):
- After per-param standardization, if `_cross_constraint_validation_enabled()` (default True)
- On violations: raises `BatchStandardizationError` with `negotiation_eligible=True`
- On warnings: appends `cross_constraint_warning` records, does NOT block

Path B — router preflight (`core/router.py:2180-2330`):
- Called at `router.py:10900-10906` during EXECUTING stage
- Uses standardizer directly, not the engine
- On violation: stores `state.execution.blocked_info`, records `CROSS_CONSTRAINT_VIOLATION` trace, returns True (block)

**Constraint interaction with chain projection:**
- Clarification contract creates its own `StandardizationEngine` with `enable_cross_constraint_validation: False` (`clarification_contract.py:164`) — constraint validation is disabled during clarification
- OASC contract (`oasc_contract.py:470-503`): syncs `current_ao.constraint_violations` and `fact_memory` after each turn

---

## Task 8: Run 7 Shanghai Turn-by-Turn Trace

### Log file locations

- `evaluation/results/phase8_2_2_c2/run7_shanghai_e2e/shanghai_e2e_summary.json`
- `evaluation/results/phase8_2_2_c2/run7_shanghai_e2e/shanghai_e2e_traces.jsonl`
- Evaluation runner: `evaluation/run_shanghai_e2e.py`

### Turn-by-turn analysis

**Turn 1** — `"请用这个路网文件计算上海地区的CO2和NOx排放，车型是乘用车，季节选夏季"`

| Field | Value |
|---|---|
| Response | "收到，我将用您上传的路网文件..." |
| Tool calls | `calculate_macro_emission` (SUCCESS) — CO2: 318.90 kg/hr, NOx: 67.40 g/hr |
| Trace steps | Only `reply_generation` (mode=llm, latency=118131ms) |
| router_text_chars | 532 |
| Wall clock | 168.25 sec |
| Log ref: `shanghai_e2e_summary.json` lines 13-95, `traces.jsonl:1` |

**Turn 2** — `"请对刚才的排放结果做扩散模拟"`

| Field | Value |
|---|---|
| Response | "请问您想对哪种污染物进行扩散模拟？可以告诉我是 NOx、PM2.5 还是其他污染物，我来继续处理。" |
| Tool calls | **NONE** |
| Trace steps | Only `reply_generation` (mode=llm, latency=14557ms) |
| router_text_chars | **17** (down from 532 in Turn 1) |
| Wall clock | 41.48 sec |
| Log ref: `shanghai_e2e_summary.json` lines 96-118 |

**BREAK POINT:** The system did NOT call `calculate_dispersion`. It did NOT recognize "扩散模拟" as a chain continuation. `router_text_chars=17` indicates minimal context carried forward. The trace shows no `tool_selection`, no `ao_classifier`, no `intent_resolution` steps — only `reply_generation`.

**Turn 3** — `"请根据扩散结果分析污染热点，并生成空间地图"`

| Field | Value |
|---|---|
| Response | "当前工具暂不支持扩散分析、污染热点识别和空间地图生成。您是否希望先进行宏观排放计算？..." |
| Tool calls | **NONE** |
| Trace steps | Only `reply_generation` (mode=llm, latency=11827ms) |
| router_text_chars | 66 |
| Wall clock | 36.72 sec |
| Log ref: `shanghai_e2e_summary.json` lines 119-143 |

**COMPLETE FAILURE.** No tools executed. The system fell back to a generic LLM response with no domain-specific handling.

### Root cause — where the chain breaks

**Break point: Turn 2, between turn completion and the next turn's AO classification.**

Evidence:
1. **No AO classification in trace.** The traces only contain `reply_generation`. The OASC contract stores classifier telemetry in `trace["oasc"]` (`oasc_contract.py:720-730`), not in `trace["steps"]`. The evaluation runner (`run_shanghai_e2e.py:50-51`) only captures `response.trace.get("steps", [])` — the AO lifecycle, classifier decisions, and governance metadata are not exported.

2. **Context collapse.** `router_text_chars=17` (Turn 2) vs `532` (Turn 1) — the inner router fell to a fast path or minimal prompt assembly, not the full state loop.

3. **AO likely completed.** The `calculate_macro_emission` AO from Turn 1 was likely auto-completed. With no active AO in Turn 2, `_maybe_complete_ao_with_chain_gate` (`oasc_contract.py:250-275`) would have allowed completion. `enable_continuation_override` (default `true` at `config.py:83`) would force CONTINUATION → NEW_AO. The new AO's `projected_chain` was `["calculate_macro_emission"]` — a single-tool chain that doesn't include dispersion.

4. **Missing data flow.** Emission result `outputs/macro_direct_emission_results_20260504_005233.xlsx` was produced but never referenced in Turn 2. The router's `_ensure_live_continuation_bundle()` (called at `oasc_contract.py:328`) should carry emission results across turns, but either it wasn't populated, or the inner router didn't use it during Turn 2's intent resolution.

5. **Trace deficiency.** The `run_shanghai_e2e.py` trace export only captures `trace["steps"]`, missing `trace["oasc"]`, `trace["classifier_telemetry"]`, and `trace["ao_lifecycle_events"]`. The true AO lifecycle and governance decisions are invisible in the Run 7 logs.

### v1.5 design target case

This is the canonical Class D "auto-chain doesn't work" case. Required fixes:
- Turn 1's projected chain must include `calculate_dispersion` as a downstream tool
- Turn 2's intent must be classified as CONTINUATION with chain awareness
- The emission result from Turn 1 must be available for Turn 2's dispersion call
- The AO must remain ACTIVE across turns (not auto-complete after single tool in a multi-step chain)

---

## Task 9: Conversation Fast-Path Bypass Audit

### Config
- `config.py:72` — `enable_conversation_fast_path`, env `ENABLE_CONVERSATION_FAST_PATH`, default `"true"`

### Trigger conditions

**Conversation fast path** (`router.py:623-734`):
- `enable_conversation_fast_path` must be True (line 629)
- `intent_result.fast_path_allowed` from `ConversationIntentClassifier` must be True (line 668)
- Intent classifier sets `fast_path_allowed=True` for:
  - `EXPLAIN_RESULT` + no blocking signals (`conversation_intent.py:163`)
  - `KNOWLEDGE_QA` + no blocking signals (line 175)
  - `CHITCHAT` + no blocking signals + text ≤ 40 chars (line 189)
- Blocking signals: `new_file_upload`, `active_parameter_negotiation`, `active_input_completion`, `file_relationship_clarification`, `residual_workflow` (`conversation_intent.py:100-109`)

**Parameter negotiation fast path** (`parameter_negotiation.py:303-378`):
- Reply ≤ 3 chars (line 319)
- Pure digit → candidate index (lines 323-344)
- Confirm words → single candidate acceptance (lines 347-363)
- Decline words → immediate (lines 366-376)

**Input completion fast path** (`input_completion.py:512-551`):
- Reply ≤ 3 chars (line 525)
- Digit → option index (lines 529-534)
- Pause words (lines 537-549)

### State machines bypassed on fast path

When conversation fast path activates, ALL of the following are skipped:

| State Machine / Component | File | What Is Skipped |
|---|---|---|
| Clarification contract | `clarification_contract.py` | Entire before_turn/after_turn |
| Execution readiness (ERC) | `execution_readiness_contract.py` | Prerequisite check, geometry check |
| OASC contract | `oasc_contract.py` | AO creation, continuation, state sync |
| Reconciler | `reconciler.py` | Post-execution arbitration |
| Stance resolution | `stance_resolution_contract.py` | Signal classification |
| Intent resolution | `intent_resolution_contract.py` | Intent classification |
| AO classifier | `ao_classifier.py` | New/continue/revise classification |
| AO manager | `ao_manager.py` | Turn management, AO lifecycle |
| TaskState machine | `task_state.py` | Stage transitions, guard loops |
| Cross-constraint preflight | `router.py:2180-2330` | Parameter compatibility check |

**What IS still used on fast path:**
- CHITCHAT/EXPLAIN_RESULT: `self.llm.chat()` (line 673-683) — raw LLM call with simplified prompt
- KNOWLEDGE_QA: `self.executor.execute("query_knowledge", ...)` (line 685-706) — full executor with standardization
- `self.memory.update()` (line 709-715) — memory write
- `self._save_result_to_session_context()` (line 698) — context store write for knowledge results

### Conflict surface: fast path vs. governed path

1. **Memory writes** (line 709-715 vs. state loop): Fast path writes `last_tool_name="query_knowledge"` but does NOT update AO state. Next governed turn reads `last_tool_name` from fact_memory but AO has no knowledge of the fast-path interleaving.

2. **Context store writes** (line 698): Fast path writes knowledge results. Governed path also writes through `ao_manager.TurnOutcome`. Potential stale/incomplete metadata on fast-path entries.

3. **AO state gap:** Fast path creates NO AO. Governed path expects `current_ao`. A fast-path KNOWLEDGE_QA turn ("what's NOx?") followed by governed turn ("now calculate dispersion") enters governed path with stale `current_ao`.

4. **Trace deduplication** (lines 654-666, 721-732): Both paths write to the same trace dict. Fast path gets reference to the same dict before state loop clears it.

### v1.5 vs v2 deferral assessment

**The conversation fast path IS a v1.5 concern, not deferrable to v2.**

Evidence:
- **Measured impact:** Phase 8.2.2 C1 pilot results show disabling fast_path improves metrics +2-4pp. The current fast path skips governance that would be helpful.
- **Governance gap:** Three intents (CHITCHAT, EXPLAIN_RESULT, KNOWLEDGE_QA) bypass all 8+ state machines. For CHITCHAT and EXPLAIN_RESULT, even the executor is skipped — raw LLM call with no standardization or guardrails.
- **Known issue:** `docs/codebase_audit_part1_oa_reality.md:390` explicitly calls it out as a known shortcut.

**Sub-component fast paths** (parameter_negotiation `_try_fast_path`, input_completion `_try_fast_path`) are NOT a concern for v1.5. They are well-scoped regex shortcuts within already-governed interactions — they don't bypass any contract or state machine.

---

## Task 10: Test Coverage + Trace Observability Gaps

### State machine test coverage

| State Machine | Dedicated Tests | Integration Tests | Coverage Level |
|---|---|---|---|
| ClarificationContract | 29 tests (`test_clarification_contract.py`) | 47 tests (`test_contract_split.py`) | **High** — PCM probe logic, Stage 2 stance, snapshots, probe abandonment covered |
| OASCContract | 6 tests (`test_oasc_backfill_guard.py`) | Heavy in `test_contract_split.py` | **Partial** — No standalone `test_oasc_contract.py`. Classification logic, chain queue advancement, state transitions not directly tested |
| ExecutionReadinessContract | 13 + 7 tests (`test_execution_readiness_parameter_snapshot.py`, `test_execution_readiness_chain_guard.py`) | Heavy in `test_contract_split.py` | **High** — Snapshots, readiness branches, runtime defaults, probe limits, force_proceed, chain guard all covered |
| ExecutionContinuation | 7 + 7 + 2 tests (`test_phase8_1_4e_chain_gate.py`, `test_stance_parameter_collection.py`, `test_ao_manager.py:390-489`) | Heavy in `test_contract_split.py` | **Partial** — No standalone `test_execution_continuation.py`. Only chain continuation blocking logic, parameter collection escalation, max stall turns tested. The dataclass itself is not directly tested |
| Reconciler | 19 tests (`test_reconciler.py`) | `test_ablation_flags.py` | **Complete** — All 4 rules (A1-A4), builders, source trace, degrade paths covered |
| AO Classifier | 14 tests (`test_ao_classifier.py`) | `test_ablation_flags.py`, `test_oasc_telemetry.py` | **High** — 5 rule layer branches, LLM layer, fallback, error paths, 13/15 accuracy check |
| AO Manager | 14 + 12 tests (`test_ao_manager.py`, `test_ao_manager_completion.py`) | `test_canonical_execution_state.py` | **High** — CRUD, completion conditions, revision, tool calls, blocking |

### Transition logic test status

**No state machine has dedicated unit tests for internal state transition functions.** All test coverage is through behavioral/integration tests that observe outputs after transitions. No test directly asserts "state X transitions to Y under condition Z."

### TraceStepType — cross-machine coordination coverage

`core/trace.py:17-128` — 108 enum members total.

**Trace types covering cross-machine data hand-off:**

| TraceStepType | String Value (File:Line) | Hand-off Coverage |
|---|---|---|
| `STATE_TRANSITION` | `"state_transition"` (line 111) | Generic task-level transition |
| `CLARIFICATION` | `"clarification"` (line 112) | System→user clarification signal |
| `RECONCILER_INVOKED` | `"reconciler_invoked"` (line 117) | P1/P2/P3 arbitration triggered |
| `RECONCILER_PROCEED` | `"reconciler_proceed"` (line 118) | Reconciler decided proceed |
| `AO_CLASSIFIER_FORCED_NEW_AO` | `"ao_classifier_forced_new_ao"` (line 122) | Classifier override |
| `CONTINUATION_OVERRIDDEN_TO_NEW_AO` | `"continuation_overridden_to_new_ao"` (line 126) | Continuation override |
| `CROSS_CONSTRAINT_VALIDATED` | `"cross_constraint_validated"` (line 106) | Constraint check passed |
| `CROSS_CONSTRAINT_VIOLATION` | `"cross_constraint_violation"` (line 107) | Constraint violation |
| `CROSS_CONSTRAINT_WARNING` | `"cross_constraint_warning"` (line 108) | Constraint warning |

### Silent gaps in trace observability

**The following state transitions have NO trace events:**

1. **ClarificationContract internal transitions** — Zero `trace.record()` calls in `clarification_contract.py`. PCM state changes (`probe → proceed → snapshot`) are silent.
2. **ExecutionReadinessContract internal transitions** — Zero `trace.record()` calls in `execution_readiness_contract.py`. Readiness branch decisions are silent.
3. **OASCContract internal transitions** — Zero `trace.record()` calls in `oasc_contract.py`. AO lifecycle transitions are silent at the trace level.
4. **ExecutionContinuation transitions** — Zero `trace.record()` calls in `execution_continuation.py` or `execution_continuation_utils.py`.
5. **Reconciler internal logic** — Zero `trace.record()` calls in `reconciler.py`. Only the invoker (`governed_router.py`) records the reconcile outcome.

**Consequence:** Current trace can show the RESULT of coordination (what the governed router decided) but NOT the PATH through each state machine (what internal state changes happened). A governed turn's full state machine coordination cannot be reconstructed from trace alone — only the governed router's external view is visible.

### v1.5 test impact estimate (broad)

**High impact** (class/method signatures change, imports break):
- `test_clarification_contract.py` — directly instantiates ClarificationContract
- `test_contract_split.py` — instantiates all three contracts, tests pipeline integration
- `test_execution_readiness_parameter_snapshot.py` — directly tests ERC snapshots
- `test_execution_readiness_chain_guard.py` — directly tests ERC chain guard
- `test_reconciler.py` — directly imports `reconcile()` and builders
- `test_phase8_1_4e_chain_gate.py` — directly imports ExecutionContinuation
- `test_stance_parameter_collection.py` — directly creates ExecutionContinuation objects

**Medium impact** (behavior changes, AO lifecycle changes):
- `test_ao_manager.py`, `test_ao_classifier.py`, `test_oasc_backfill_guard.py`, `test_intent_resolution_contract.py`, `test_canonical_execution_state.py`, `test_pcm_advisory.py`

**Low impact** (pure logic, no state machine interaction):
- `test_ao_manager_completion.py`, `test_stance_resolver.py`

**Core files requiring changes:**
- `core/contracts/clarification_contract.py`, `execution_readiness_contract.py`, `oasc_contract.py`, `reconciler.py`
- `core/execution_continuation.py`, `execution_continuation_utils.py`
- `core/governed_router.py`
- `config.py`

---

## Task 11: Anchors Compliance — Current State Spot Check

### Selling Point #1: Formalized Traffic Emission Workflow

**Freeze doc claim:** §2 describes a "layered contract pipeline" implying formalization.

**Code reality:** Workflow templates are hardcoded in `core/workflow_templates.py:188-330` as Python `WorkflowTemplate` dataclass instances. There is no `config/workflow_templates.yaml`. The 5 templates are code, not configuration.

**Verdict:** **Partially formalized.** The workflow model exists (as Python classes) but is not externalized to YAML like tool contracts and cross-constraints are. Flag: workflow formalization is code-internal, not config-external.

### Selling Point #3a: Tool Dependency Forward Validation

**Referenced from Task 7.** Dependency graph exists in `config/tool_contracts.yaml`, loaded at `core/tool_dependencies.py:35-37`. Forward validation via `validate_tool_prerequisites()` (`tool_dependencies.py:184-268`). Pre-execution call chain confirmed. Cross-turn result availability exists via `SessionContextStore.get_result_availability()` (`context_store.py:345-399`).

**Verdict:** **Implemented as claimed.** No flag.

### Selling Point #3b: Cross-Parameter Constraints + Negotiation Loop

**Referenced from Task 7.** 5 cross-parameter constraints in `config/cross_constraints.yaml`. Two trigger paths: during standardization (`standardization_engine.py:641-664`) and router preflight (`router.py:2180-2330`). On violation: blocks execution, sets `negotiation_eligible=True`, offers suggestions. Constraint violations persist across turns via `ao.constraint_violations` and `FactMemory`.

**Verdict:** **Implemented as claimed.** No flag.

### Selling Point #3c: AO State Machine (Currently Partial)

**Referenced from Task 3.** The "5-state AO machine" claim is **INCORRECT.** Only 3 states exist: NEW_AO, CONTINUATION, REVISION. REFINEMENT and TERMINATION do not exist. All 3 existing states have real transition logic — not "partial" as claimed. The upgrade document's assertion of "2 states with logic" is wrong — all 3 have logic.

**Verdict:** **Flag — documentation overstates the gap (missing 2 states, not just logic) and understates the implementation (all 3 existing states work).**

### §26 Backend Capability — Tool Production-Ready Spot Check

**1 Full tool: `calculate_dispersion` (`tools/dispersion.py`):**
- `preflight_check()` at line 475 — checks model file existence, can return `is_ready=False`
- `execute()` at line 475 — full async implementation with error handling
- Result: **Production-ready.** The only tool with non-trivial preflight check.

**2 Partial tools:**

`tools/macro_emission.py` (951 lines):
- `execute()` at line 614 — full async implementation
- `preflight_check()` — inherits `BaseTool.preflight_check()` at `tools/base.py:79`, which returns `PreflightCheckResult(is_ready=True)` unconditionally
- `_fix_common_errors()` patches field names (link_length ← length, road_length, etc.)
- Result: **Functional but preflight is a no-op.** Always reports ready.

`tools/file_analyzer.py` (1911 lines):
- `execute()` at line 39 — full async implementation with column mapping via `get_standardizer()`
- `preflight_check()` — inherits `BaseTool.preflight_check()` — always returns `is_ready=True`
- Result: **Functional but preflight is a no-op.** Always reports ready.

**Summary:** 9 out of 10 tools inherit `BaseTool.preflight_check()` which returns `is_ready=True` unconditionally (`tools/base.py:79`). Only `calculate_dispersion` overrides it.

### Reconciler Production Default

**Config:** `config.py:191` — `enable_llm_decision_field` default = `"true"`

**Freeze doc errata §11.1 (`emissionagent_v1_architecture_freeze.md:304-345`):** Documents that at freeze time (commit `1391b9f`), default was `"false"` — reconciler was dead code. Changed to `"true"` at Phase 8.1.2 Step 3.

**Current state:** Reconciler IS active in production. The freeze document's original claim (§3 Principle 4: "reconciler arbitrates between evidence sources") was a substantive error at freeze time but is NOW correct.

**Verdict:** **Resolved — no current flag.** The errata entry is accurate.

### Summary of all mismatches

| # | Doc Claim | Code Reality | Severity |
|---|---|---|---|
| 1 | AO has 5 states (upgrade doc §1.3) | `AOClassType` has 3 states, all with real logic. REFINEMENT/TERMINATION do not exist (`core/ao_classifier.py:27-30`) | **Critical** — v1.5 design must start from 3-state reality |
| 2 | "Only 2 states have logic" (upgrade doc §1.3) | All 3 states have real transition logic | **High** — understates current implementation |
| 3 | Workflow is "formalized" (freeze doc §2) | Workflow templates hardcoded in `core/workflow_templates.py`, not YAML-externalized | **Medium** — formalization exists in code but not in config |
| 4 | Reconciler is active governance component (freeze doc §2) | WAS false at freeze time (`config.py:191` was `"false"`). NOW correct after Phase 8.1.2 fix. Errata §11.1 documents this. | **None** (resolved) |
| 5 | 10 tools production-ready (§26) | 9/10 tools have no-op preflight check (`tools/base.py:79`). Only `dispersion.py:475` has real preflight. | **Low** — tools functionally work, preflight is just a trivial gate |
| 6 | ConversationState-like mechanism exists | **Does not exist.** No `ConversationState`, `session_state`, or shared state machine object. 4 state machines use independent `ao.metadata` keys + `context.metadata`. | **Critical** — v1.5 must create this from scratch |
| 7 | PCM mentioned in governance pipeline (freeze doc §2) | PCM is pre-pipeline gate, not in pipeline — hard-blocks Stage 2 + reconciler in hard-block mode (Errata §11.2) | **Medium** — documented in errata |

---

## Cross-Cutting Findings Summary

### What exists (v1.5 building blocks)

1. **4 independent state machines** (Clarification, OASC/chain-projection, ExecutionReadiness, ExecutionContinuation) — all functional with their own persistence in `ao.metadata`
2. **AOExecutionState** — canonical chain progress ledger (`core/analytical_objective.py:262-271`)
3. **3-state AO classifier** (NEW_AO, CONTINUATION, REVISION) — fully implemented with rule + LLM layers
4. **Reconciler** — active in production (`ENABLE_LLM_DECISION_FIELD=true`), 4-rule arbitration
5. **SessionContextStore** — cross-turn tool result cache with staleness tracking
6. **Cross-parameter constraints** — 5 constraints in YAML, dual trigger paths
7. **Tool dependency graph** — YAML-based, cross-turn-aware via SessionContextStore
8. **NaiveRouter fully isolated** — no governance data leak
9. **Stream chunks** — 7 chunk types, trace_friendly in done chunk

### What does NOT exist (v1.5 must create)

1. **ConversationState** — no single shared state object across the 4 state machines
2. **REFINEMENT state** — absent from `AOClassType` enum
3. **TERMINATION state** — absent from `AOClassType` enum
4. **Trace observability for internal state machine transitions** — Clarification, ERC, OASC, ExecutionContinuation have zero `trace.record()` calls
5. **Workflow template YAML externalization** — templates hardcoded in Python
6. **Cross-turn AO persistence through process restart** — `ao_history` not in `router_state/{session_id}.json`

### Critical flags for v1.5 design

1. **AO 5-state design starts from 3-state reality, not 2.** All 3 existing states work. v1.5 adds REFINEMENT and TERMINATION on top of 3, not on top of 2.
2. **ConversationState is greenfield.** No existing shared object to extend. Must be created and wired into 4 state machines.
3. **Run 7 chain break is the canonical test case.** Turn 2 context collapse (17 chars), AO auto-completion, missing chain projection — all must be fixed.
4. **Fast path is a v1.5 concern.** It bypasses ALL governance and measurably degrades metrics (-2 to -4pp). v1.5 must either make fast path governance-aware or make ConversationState writes fast-path-safe.
5. **NaiveRouter isolation is complete** — only `ToolRegistry` singleton is shared. Enforcement is straightforward.
6. **Trace gap is significant.** 4 state machines have zero internal trace events. v1.5 ConversationState writes should add trace observability.
