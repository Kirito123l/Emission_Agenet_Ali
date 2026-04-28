# Phase 4 — PCM Redesign

## 1. Background

Phase 2 audit identified L3 (Optional Probe Over-Triggering) as a key
governance overreach failure mode.  The original Phase 2 P0 spec
(`docs/governance_p0_spec.md`) targeted PCM
`unfilled_optional_no_default_at_first_turn`, proposing to make
`_get_unfilled_optionals_without_default` aware of `_RUNTIME_DEFAULTS` (K4
knowledge injection) so that slots like `model_year` (which has
runtime_default=2020) would not trigger a probe.

That P0 spec was deferred in favor of Phase 3 systematic architecture reset
(knowledge injection + decision field).  Phase 3 Step 2.A trace analysis
(this conversation) revealed:

- PCM short-circuits **25/30 tasks** (83%) before Stage 2 / decision field
  can activate
- Only 8/30 tasks reach Stage 2; only 5/30 reach the Q3 gate
- The 80% ON-mode score is a PCM bottleneck, not a Q3 gate or LLM quality
  issue
- Phase 3's K4 runtime_defaults are NOT consumed by PCM's
  `_get_unfilled_optionals_without_default`, so optional slots with runtime
  defaults (e.g., `model_year=2020` for `query_emission_factors`) still
  trigger probes

PCM redesign is the unblocking work to let the Phase 3 decision field
actually govern first-turn task routing.

## 2. Current PCM Implementation Audit (Read-only)

### 2.1 PCM Trigger Conditions

PCM exists in **two waves** with partially overlapping logic:

#### Wave 1: `clarification_contract.py`

**Trigger resolution** (`_resolve_collection_mode`, lines 1337-1356):

| # | Trigger | Code Location | Semantic Intent | K4 Redundancy? |
|---|---------|---------------|-----------------|----------------|
| T1 | `missing_required_at_first_turn` | `clarification_contract.py:1351-1352` | Required tool slot empty on AO's first turn — must collect before execution | No — required slots are genuinely blocking |
| T2 | `unfilled_optional_no_default_at_first_turn` | `clarification_contract.py:1353-1354` | All required filled, but ≥1 optional slot has no YAML declarative default and is unfilled — probe before executing | **YES** — `_get_unfilled_optionals_without_default` (lines 1371-1388) only checks `tool_spec["defaults"]` (YAML declarative), NOT `_RUNTIME_DEFAULTS`. Slots like `model_year` with `_RUNTIME_DEFAULTS["query_emission_factors"]["model_year"] = 2020` are treated as no-default and trigger probes |
| T3 | `confirm_first_signal` | `clarification_contract.py:1348-1349` | User message matches substring patterns indicating "confirm before executing" intent | No — this is user-expressed intent, though substring matching is a P2 pattern |

**Probe execution** (`before_turn` lines 388-409):

| # | Mechanism | Code Location | Semantic Intent |
|---|-----------|---------------|-----------------|
| M1 | Pick first unfilled optional | `clarification_contract.py:392` | Probe one slot at a time, in order |
| M2 | `probe_turn_count >= 2` → abandon | `clarification_contract.py:396-398` | After 2 attempts at same slot, force-proceed |
| M3 | LLM-generated probe question | `clarification_contract.py:402-407, 1122-1176` | Natural-language question via separate LLM call |

#### Wave 2: `execution_readiness_contract.py`

| # | Trigger | Code Location | Semantic Intent | K4 Redundancy? |
|---|---------|---------------|-----------------|----------------|
| T4 | `no_default` optionals with missing values | `execution_readiness_contract.py:379` (deliberative branch), lines 227-239 (directive branch) | After `_classify_missing_optionals` (lines 666-692) separates optionals into `resolved_by_default` and `no_default`, only `no_default` slots become probe candidates | **Partially** — `_classify_missing_optionals` DOES check `has_runtime_default()` (line 684), so K4-aware. But when runtime_default_aware_readiness is false (config flag), all unfilled optionals become probe candidates. Also, the probe decision itself (whether to probe at all for `no_default` optionals) is still hardcoded |
| M4 | `probe_count >= probe_limit` (default 2) → force-proceed | `execution_readiness_contract.py:229, 388` | Same magic constant as Wave 1 M2 |
| M5 | `has_probe_abandon_marker` → abandon | `execution_readiness_contract.py:388` | User says "先算吧" etc. — explicit abandon signal |

### 2.2 PCM in the Governance Decision Path

#### Upstream → PCM entry points

```
User message
  → OASC contract (classification: NEW_AO / REVISION)
  → ClarificationContract.before_turn (Wave 1)  OR  ExecutionReadinessContract.before_turn (Wave 2, contract-split)
       ↓
  _resolve_collection_mode()  ← decides if PCM activates
       ↓
  [PCM ACTIVE] → probe optional / require required / confirm-first
       ↓
  [PCM INACTIVE or ABANDONED] → should_proceed = True
```

#### PCM → Downstream effects

**Wave 1 (clarification_contract.py):**

When PCM is active and `should_proceed=False` (lines 429-503):
1. If `_decision_field_active(telemetry)` is True → **Q3 gate defer**: returns
   `ContractInterception` with `proceed=True` (default) but metadata containing
   `hardcoded_recommendation: "clarify"`.  GovernedRouter detects this at line
   128-138 and lets `_consume_decision_field` decide.
2. If decision field is NOT active → returns `ContractInterception(proceed=False)`
   with a hardcoded question.  GovernedRouter breaks the contract loop and
   returns the question directly to the user.

**Key insight**: In case (1), PCM still dictates *what* the probe is about
(`pending_slots`, `question`).  The Q3 gate only controls *whether* the
hardcoded question or the LLM's question is shown.  PCM's decision to probe
at all is NOT gated by the decision field — only the response routing is.

**Wave 2 (execution_readiness_contract.py):**

When `clarify_candidates` exist (lines 227-304) or deliberative branch
triggers (lines 379-469):
1. Creates `ExecutionContinuation(pending_objective=PARAMETER_COLLECTION)`
2. If `_split_decision_field_active(context)` → Q3 gate defer
3. Otherwise → `ContractInterception(proceed=False, response=question)`

#### PCM → Stage 2 relationship

```
[User message]
  → PCM trigger check (BEFORE Stage 2 is called in most cases*)
  → If PCM active → short-circuit, Stage 2 never runs
  → If PCM inactive → Stage 2 may run (if missing_required or other conditions)
```

\* Exception: Wave 1 calls Stage 2 early when `tool_name` is None (lines
233-271), but this is for intent resolution, not for slot-filling decisions.

**The core problem**: PCM is a governance hard-rule that runs BEFORE Stage 2
LLM, preventing the LLM from ever seeing the full picture on 83% of tasks.
The decision field (Phase 3's key innovation) is only consulted on the 17%
of tasks that survive PCM's short-circuit.

### 2.3 PCM Abandon / probe_limit Mechanism

**probe_limit = 2** (magic constant):

- Defined in `ExecutionContinuation.probe_limit` (default 2, line 21)
- Enforced in two locations:
  - Wave 1: `probe_turn_count >= 2` at `clarification_contract.py:396`
  - Wave 2: `probe_count >= probe_limit` at `execution_readiness_contract.py:229` and `388`
- When limit reached:
  - Wave 1: sets `probe_abandoned = True`, `should_proceed = True`
  - Wave 2: sets `force_proceed_reason = "probe_limit_reached"`, clears continuation

**User abandon signals** (`continuation_signals.py:16-23`):
- `"先算吧"`, `"直接算吧"`, `"别问了"`, `"不用再问"`, `"先跑吧"`, `"直接继续"`
- Checked via `has_probe_abandon_marker()` substring match
- Only consumed in Wave 2 deliberative branch (line 388); Wave 1 does NOT check
  abandon markers at all

**After abandon**:
- Wave 1: `should_proceed = True` → context injection → tool execution
- Wave 2: `abandoned = True` on continuation, clears to NONE after turn

## 3. PCM Under Phase 3 Locking Principles

Phase 3 §7 locking principles:

- **F1**: Don't use confidence thresholds to override LLM decisions
- **F2**: Domain physics rules → governance; conversational pragmatics → LLM
- **F3**: Reply LLM references domain enums from ReplyContext

### 3.1 Trigger Classification

| Trigger | Code Location | Type | F1/F2/F3 Analysis | Recommendation |
|---------|---------------|------|-------------------|----------------|
| T1: `missing_required_at_first_turn` | `clarification_contract.py:1351-1352` | **Physics** (partial) | Detection of missing required slots is domain physics (tool contracts require specific params). But the *response strategy* (ask vs. use defaults vs. infer) is pragmatics. **Mixed compliance**: detection = F2 compliant; response = F2 violation. | Keep detection; route response decision through Stage 2 LLM |
| T2: `unfilled_optional_no_default_at_first_turn` | `clarification_contract.py:1353-1354` | **Pragmatics + Magic** | Probing optional slots before execution is conversational pragmatics — "do you want to specify model_year or shall I use 2020?" This is a user-preference question, not a domain constraint. **Violates F2**. Additionally, the K4 blindness (not checking `_RUNTIME_DEFAULTS`) makes this a **Magic** issue. | Delete as hard block; let Stage 2 LLM decide |
| T3: `confirm_first_signal` | `clarification_contract.py:1348-1349` | **Pragmatics** (borderline) | Respecting explicit user "confirm first" instruction is correct behavior. But substring-matching detection violates F2 — the LLM should detect conversational stance, not regex. **Violates F2** in detection; compliant in consequence. | Replace substring detection with LLM stance detection; keep consequence |
| T4: `no_default` optional probe (Wave 2) | `execution_readiness_contract.py:379` | **Pragmatics** | Same as T2 — deciding to probe optional slots is a conversational choice. Wave 2 is K4-aware (checks `has_runtime_default`), so no Magic issue. But the decision to probe at all is still governance-authored. **Violates F2**. | Delete as hard block |
| M2/M4: `probe_count >= 2` | `clarification_contract.py:396`, `execution_readiness_contract.py:229` | **Magic** | Fixed limit of 2 is a behavioral constant without domain rationale. Conversational patience is a pragmatics concern — the LLM should decide when to stop probing. **Violates F1** (magic threshold) and **F2** (pragmatics in governance). | Remove; LLM's decision field naturally handles this via `proceed` when slots are adequate |
| M3: LLM probe question generator | `clarification_contract.py:1122-1176` | **Hybrid** | Using LLM for question phrasing is good (F3-compliant), but governance decides WHEN to call it and WHICH slot to probe. **Partial F3 compliance**: text is LLM-generated, but slot selection is governance-authored. | If PCM becomes advisory, keep probe-question LLM for Stage 2 context enrichment |
| M5: `has_probe_abandon_marker` | `continuation_signals.py:33-37` | **Pragmatics** | Substring matching for conversational signals. **Violates F2** — LLM should detect user's intent to abandon probing, not regex. | Replace with LLM stance/intent detection in Stage 2 |

### 3.2 Summary Statistics

| Classification | Count | Triggers |
|----------------|-------|----------|
| **Pragmatics** (F2 violation) | 4 | T2, T3 (detection), T4, M5 |
| **Physics** (F2 compliant) | 1 | T1 (detection only) |
| **Magic** (F1 violation) | 2 | T2 (K4 blindness), M2/M4 (probe_limit=2) |
| **Hybrid** (partial F3) | 1 | M3 |

**Key finding**: 4 of 7 triggers are conversational pragmatics that violate F2.
The 2 magic triggers are fixable but the deeper issue is architectural: PCM as
a whole is a governance-authored conversational strategy that competes with the
LLM decision field.

## 4. Three PCM Redesign Options

### Option A — Complete PCM Deletion

**Design**: Remove PCM entirely from both Wave 1 and Wave 2.  Trust Stage 2
LLM decision field to handle all first-turn routing decisions (proceed /
clarify / deliberate).  No hardcoded probe logic, no collection_mode state,
no probe_turn_count.

**What gets removed**:
- `_resolve_collection_mode()` and all call sites
- `_get_unfilled_optionals_without_default()` and all call sites
- `_build_probe_question()` / `_run_probe_question_llm()`
- `_next_probe_turn_count()`
- `_mark_parameter_collection_complete()`
- `collection_mode` / `pcm_trigger_reason` / `probe_*` fields from:
  - `ClarificationTelemetry`
  - `ParameterState`
  - `ExecutionContinuation`
  - AO metadata persistence paths
- `PROBE_ABANDON_MARKERS` and `has_probe_abandon_marker()`
- `PendingObjective.PARAMETER_COLLECTION` (or keep as no-op for backward compat)
- PCM-related branches in `execution_readiness_contract.py`:
  - `_classify_missing_optionals` probe decision (keep classification for trace)
  - Deliberative optional probe (lines 379-469)
  - `probe_count`/`probe_limit` tracking
- PCM-related tests (~10-12 tests in `test_clarification_contract.py` and
  `test_contract_split.py`)

**What stays**:
- Stage 2 LLM call (intent + slot resolution + decision field)
- `missing_required` detection (T1 detection — domain physics)
- Stage 3 normalization
- Q3 gate (decision field consumption)
- Cross-constraint validation

**Advantages**:
- Cleanest F2 implementation — governance handles domain physics, LLM handles
  conversational strategy
- No dual-path maintenance (PCM vs. decision field)
- Removes ~300 lines of governance logic
- Eliminates the 83% short-circuit rate
- probe_limit magic constant eliminated
- No more PCM state persistence complexity across turns

**Disadvantages**:
- Stage 2 LLM failure → no safety net → falls through to inner router
  (raw LLM execution without governance guardrails)
- When `ENABLE_LLM_DECISION_FIELD=false` (current default), there is NO
  governance layer at all for first-turn optional probing → system becomes
  too permissive (executes with missing optional params)
- Removing PCM removes the only mechanism for multi-turn parameter collection
  when the LLM decision field is unavailable
- `confirm_first` user intent would need to be detected by LLM (currently
  substring match) — risk of LLM missing explicit user pause instructions
- Existing eval tasks that depend on PCM probing behavior will change output

**Risk level**: **HIGH** — removes safety net without guaranteed LLM
reliability.  Only viable if `ENABLE_LLM_DECISION_FIELD=true` is the
unconditional default and Stage 2 reliability is proven at scale.

**Effort**: **M** (medium) — ~300 lines removed, ~12 tests updated, careful
  wiring to ensure Stage 2 path remains intact.

**Representative task walkthroughs**:

- `e2e_ambiguous_034` ("轿车的总烃排放因子是多少"):
  - Without PCM: Stage 2 LLM sees vehicle_type=Passenger Car (standardized),
    pollutants=[THC], model_year has runtime_default=2020.  LLM outputs
    decision=proceed (slots complete with runtime defaults).
    → Tool executes successfully.  ✓

- `e2e_codeswitch_161` (vehicle+ pollutants filled, model_year unfilled):
  - Without PCM: Stage 2 LLM sees vehicle_type filled, pollutants filled,
    model_year has runtime_default=2020.  LLM outputs decision=proceed.
    → Tool executes with model_year=2020.  ✓

- `e2e_clarification_101` (very first message, no params at all):
  - Without PCM: Stage 2 LLM sees empty snapshot, detects missing required
    (vehicle_type, pollutants).  LLM outputs decision=clarify with a good
    question.  → Governance asks user for required params.  ✓

- `e2e_clarification_119` (missing_required at first turn):
  - Without PCM: Same as e2e_clarification_101 — LLM handles it.  ✓

### Option B — PCM Downgraded to Advisory

**Design**: PCM still computes unfilled optionals and generates probe
suggestions, but does NOT short-circuit the governance loop.  PCM output
becomes advisory context injected into the Stage 2 LLM payload.  Stage 2
LLM sees: "Governance noticed these optional slots are unfilled without
defaults: [model_year].  Runtime defaults available: model_year=2020.
You decide whether to proceed or clarify."  Governance does not consume
PCM output for hard blocking.

**What changes**:
1. PCM computation stays (detection of unfilled optionals, classification of
   no-default vs. resolved-by-default)
2. PCM output injected into Stage 2 payload as new `advisory` or `pcm_hints`
   field:
   ```yaml
   pcm_advisory:
     unfilled_optionals_without_default: [model_year]
     runtime_defaults_available: {model_year: 2020}
     confirm_first_detected: false
     suggested_probe_slot: model_year
     suggested_probe_question: "需要指定 model_year 吗？默认 2020。"
   ```
3. Stage 2 system prompt updated to consume `pcm_advisory`:
   "18. (K9) pcm_advisory 字段包含治理层检测到的未填可选参数及可用默认值。
   你拥有最终决策权：如果默认值合理，输出 proceed；如果需要用户确认，输出 clarify。"
4. Hard-rule short-circuit at `before_turn` lines 388-409 removed — instead of
   setting `pending_decision = "probe_optional"` and `should_proceed = False`,
   PCM appends advisory and lets the flow continue to Stage 2 / decision field
5. `collection_mode` state persists for multi-turn awareness but does not
   block execution
6. `probe_limit` and `probe_turn_count` become trace-only (informational),
   not gating
7. `_mark_parameter_collection_complete` becomes a trace cleanup, not a
   state reset

**What stays**:
- PCM computation infrastructure (reused for advisory generation)
- Stage 2 LLM + decision field (primary decision path)
- Q3 gate (still gates hardcoded vs. LLM routing)
- Cross-constraint validation

**What gets removed**:
- Hard `should_proceed = False` when PCM is active (lines 388-409)
- `probe_turn_count >= 2` gating (becomes advisory signal)
- PCM-authored user-facing questions (LLM generates from advisory context)
- `ContractInterception(proceed=False)` for PCM (Q3 gate defer path stays)

**Advantages**:
- PCM domain knowledge preserved (which slots are unfilled, what defaults exist)
- LLM gets richer context → better decisions
- Governance still provides value (computation) without overreaching (decision)
- F2 compliant: governance computes, LLM decides
- Graceful degradation: if LLM fails, advisory is still in trace for debugging
- Lower risk than Option A — safety net remains as informational signal
- probe_limit magic constant becomes non-gating (trace only)

**Disadvantages**:
- PCM code still exists (~200 lines of computation/classification remain)
- Stage 2 prompt grows (~1 new rule for K9 advisory consumption)
- Dual computation (PCM + Stage 2) for the same information — PCM classifies
  optionals, Stage 2 LLM also sees the full tool_spec and snapshot
- Advisory may be ignored by LLM (no guarantee LLM reads it correctly)
- When `ENABLE_LLM_DECISION_FIELD=false`, hardcoded path still needs a
  fallback (PCM would need to revert to hard-blocking behavior or the
  system becomes too permissive)
- PCM state persistence still needed (for multi-turn awareness)

**Risk level**: **MEDIUM** — preserves safety net information, but the
LLM-is-unavailable fallback path needs explicit design.

**Effort**: **M** (medium) — modify PCM call sites to emit advisory instead
  of blocking, update Stage 2 prompt, update ~8 tests.

**Representative task walkthroughs**:

- `e2e_ambiguous_034` ("轿车的总烃排放因子是多少"):
  - PCM classifies: unfilled_optionals=[model_year], runtime_defaults={model_year: 2020}
  - Advisory injected into Stage 2 payload
  - Stage 2 LLM sees advisory + snapshot + runtime_defaults
  - LLM: "model_year has runtime default 2020, user didn't specify, OK to proceed"
  - decision=proceed → tool executes.  ✓

- `e2e_codeswitch_161` (vehicle+pollutants filled, model_year unfilled):
  - PCM advisory: unfilled=[model_year], defaults={model_year: 2020}
  - LLM: "optional model_year has default 2020, proceed"
  - decision=proceed → executes.  ✓

- `e2e_clarification_101` (first message, no params):
  - PCM advisory: unfilled_optionals=[model_year, season, road_type]
  - Stage 2 LLM also detects missing_required=[vehicle_type, pollutants]
  - LLM: "missing required slots, must clarify"
  - decision=clarify → governance asks for required params.  ✓

- `e2e_clarification_119`:
  - Same pattern: LLM handles naturally.  ✓

### Option C — PCM as LLM-Unavailable Fallback

**Design**: Default path is Stage 2 LLM decision field.  PCM only activates
when:
1. `ENABLE_LLM_DECISION_FIELD = false` (current default), OR
2. `validate_decision()` fails (F1 safety net triggers), OR
3. Stage 2 LLM call fails (exception / timeout)

When PCM activates as fallback, it uses current hardcoded logic (probe
optional, probe_limit=2, etc.).  When LLM path is healthy, PCM is
completely dormant.

**What changes**:
1. In `before_turn` (both Wave 1 and Wave 2): add early-return check:
   ```python
   if self._decision_field_available() and not force_pcm_fallback:
       # Skip PCM, let Stage 2 / decision field handle routing
       # Still compute unfilled_optionals for trace
       return ContractInterception()  # or proceed with context injection
   ```
2. PCM code preserved as-is for fallback path
3. PCM activation gated on `not decision_field_available()` or explicit
   fallback flag
4. Fallback path is identical to current PCM behavior

**Advantages**:
- Clean separation: LLM path is primary, PCM is backup
- F1 compliant: fallback only when LLM unavailable/invalid
- Low implementation risk — no PCM logic changes, only activation gating
- Backward compatible: when flag=false, PCM works exactly as today
- Easy to test: toggle fallback conditions
- probe_limit magic constant stays but only applies in degraded mode

**Disadvantages**:
- Two parallel decision paths maintained indefinitely
- PCM code (~300 lines) kept entirely, just dormant most of the time
- When LLM is available, PCM's domain knowledge (unfilled optionals
  classification) is wasted — not even used as advisory
- Fallback behavior is different from primary behavior (hardcoded probing
  vs. LLM clarification) — user-visible inconsistency
- Decision field reliability must be proven before PCM can be safely
  dormant — if Stage 2 LLM is flaky, fallback activates unpredictably
- Dual-path testing burden: must test LLM path AND PCM fallback path

**Risk level**: **LOW-MEDIUM** — safest option but highest long-term
  maintenance cost.

**Effort**: **S-M** (small-medium) — add activation gate at 2-3 call sites,
  no PCM logic changes, minimal test updates.

**Representative task walkthroughs**:

Same as current behavior when fallback activates; same as Option A when
LLM path is active.  The inconsistency between paths is the main concern.

### 4.1 Option Comparison Matrix

| Dimension | Option A (Delete) | Option B (Advisory) | Option C (Fallback) |
|-----------|-------------------|---------------------|---------------------|
| F1 compliance | ✓ (no thresholds) | ✓ (no thresholds) | Partial (thresholds in fallback) |
| F2 compliance | ✓ (full) | ✓ (governance computes, LLM decides) | Partial (F2 violation in fallback) |
| Code removed | ~300 lines | ~100 lines (blocking logic only) | ~5 lines (gating only) |
| LLM dependency | High (single point of failure) | Medium (advisory as safety net) | Low (PCM backup always available) |
| Maintenance burden | Low (one path) | Medium (advisory + LLM) | High (two full parallel paths) |
| Fallback when LLM unavailable | Raw LLM (no guardrails) | Raw LLM (advisory in trace only) | Full PCM (current behavior) |
| Risk of regression | High | Medium | Low |
| User-visible consistency | LLM only | LLM only | LLM vs. PCM differ |
| Eval impact | High (all PCM tasks change) | Medium (PCM tasks get LLM routing) | Low (flag-dependent) |

## 5. Cross-Cutting Impact Analysis

### 5.1 probe_limit Magic Constant

- **Option A**: Eliminated entirely (no probe logic remains).
- **Option B**: Becomes trace-only informational field, not gating.  Still
  computed but never blocks execution.
- **Option C**: Preserved as-is for fallback path; dormant in LLM path.

### 5.2 Hardcoded "请指定" Text Generation

(`_build_question` at `clarification_contract.py:1092-1120`)

- **Option A**: Removed.  All user-facing questions come from Stage 2 LLM
  decision field `clarification_question`.
- **Option B**: Retained for trace but not user-facing.  LLM question
  generation takes over.  PCM's `_build_probe_question` still runs for
  advisory context (`suggested_probe_question`) but doesn't reach user.
- **Option C**: Preserved for fallback path.

### 5.3 Q3 Gate After PCM Redesign

The Q3 gate (Step 1.B, `clarification_contract.py:429-460` and
`governed_router.py:128-138`) currently detects when `should_proceed=False`
and `_decision_field_active(telemetry)` and defers to the decision field.

After PCM redesign:

- **Option A**: PCM is gone, so `should_proceed=False` is only set by
  `missing_required` detection (T1, physics).  Q3 gate still fires when
  hardcoded missing_required logic says "clarify" and decision field is
  active.  Q3 gate logic itself does NOT change — it still defers
  hardcoded clarify to LLM decision.  But the volume of Q3 gate
  activations drops significantly (only missing_required case remains).

- **Option B**: When `flag=true`, PCM doesn't set `should_proceed=False`,
  so Q3 gate only fires for `missing_required` case.  When `flag=false`,
  PCM retains current full hard-blocking behavior including Q3 gate
  deferral.  (See §7 Q2 for flag semantics.)

- **Option C**: Q3 gate unchanged — PCM fallback uses the same Q3 gate
  deferral path as today.

**Q3 gate is NOT made redundant by PCM redesign** — it still serves the
critical function of deferring hardcoded `missing_required` clarify
decisions to the LLM decision field.

### 5.4 Decision Field Consumption Layer

(`_consume_decision_field` at `governed_router.py:565-730`)

After PCM redesign:
- Higher volume of decisions reach `_consume_decision_field` (83% → near 100%
  of first turns)
- Cross-constraint preflight (proceed path, lines 614-669) may see more
  activations with runtime_defaults filling optional slots
- No API changes needed — the method already handles all three decision
  values correctly
- Trace coverage naturally expands (more decisions flowing through)

**No changes needed to `_consume_decision_field`.**

### 5.5 PCM State Persistence

- **Option A**: Remove `collection_mode`, `pcm_trigger_reason`,
  `probe_turn_count`, `probe_abandoned`, `probe_optional_slot` from
  `ParameterState`, `ClarificationTelemetry`, AO metadata, and
  `ExecutionContinuation`.  `PendingObjective.PARAMETER_COLLECTION`
  removed or deprecated.
- **Option B**: Keep fields for trace/advisory context; remove gating
  consumption.
- **Option C**: Keep all fields unchanged.

### 5.6 Impact on `confirm_first` Path

- **Option A**: `confirm_first` detection must move to Stage 2 LLM
  (stance detection) or be removed.  If removed, users who say "先确认"
  may get unexpected tool execution.
- **Option B**: `confirm_first_detected` becomes advisory signal in
  Stage 2 payload.  LLM decides whether to honor it.
- **Option C**: Unchanged.

### 5.7 Contract-Split (Wave 2) vs. Legacy (Wave 1)

Both Wave 1 (`clarification_contract.py`) and Wave 2
(`execution_readiness_contract.py`) have PCM logic.  Any redesign must
address both:

| Component | Wave 1 Location | Wave 2 Location |
|-----------|----------------|-----------------|
| Trigger resolution | `_resolve_collection_mode` (L1337-1356) | Implicit in `before_turn` flow (L127, L379) |
| Optional classification | `_get_unfilled_optionals_without_default` (L1371-1388) | `_classify_missing_optionals` (L666-692) |
| Probe execution | `before_turn` L388-409 | `before_turn` L227-304, L379-469 |
| probe_limit enforcement | L396 | L229, L388 |
| State persistence | `_persist_snapshot_state` (L1216-1269) | `save_execution_continuation` |
| Abandon detection | (none in Wave 1) | `has_probe_abandon_marker` (L388) |

### 5.8 Eval Framework Impact

- PCM redesign changes the golden output for any eval task where PCM
  currently triggers (T2/T4 tasks — optional probes on first turn)
- `clarification_telemetry` fields `pcm_trigger_reason`, `probe_*`,
  `collection_mode` will change values or disappear
- `proceed_mode` field may show different values (e.g., "decision_field"
  instead of "context_injection")
- Eval comparators that check `tool_chain` length or `final_decision`
  need updating
- Baseline (OFF mode) scores may shift because OFF mode also uses PCM

## 6. Recommendation: Option B (PCM as Advisory)

### Rationale

**Note**: Option B advisory routing is gated by the `ENABLE_LLM_DECISION_FIELD`
flag.  When `flag=false`, PCM retains its current full hard-blocking behavior
(missing_required hard-block + optional probe + confirm_first detection +
probe_limit), effectively providing an Option C fallback.  When `flag=true`,
PCM operates in advisory-only mode as described below.  See §7 Q2 for the
design rationale behind this two-mode architecture.

Option B is the strongest alignment with Phase 3 locking principles while
maintaining a practical safety margin:

1. **F2 compliance**: Governance computes domain facts (which slots are
   unfilled, what defaults exist, whether confirm_first was detected) and
   presents them to the LLM.  The LLM makes the conversational decision
   (proceed/clarify/deliberate).  This is the clean separation F2 demands.

2. **Engineering reality**: Option A (complete deletion) is architecturally
   pure but operationally risky — when `ENABLE_LLM_DECISION_FIELD=false`
   (current default), there would be no first-turn governance at all.
   Option B preserves PCM's computational value (classification, defaults
   lookup) as LLM context, so the LLM can make better-informed decisions.

3. **Lower risk than A, more F2-compliant than C**: Option B degrades
   gracefully — if the LLM ignores advisory, the system still functions
   (advisory is non-blocking).  If the LLM is unavailable, the advisory
   is still in trace for debugging.  Option C maintains two full paths
   indefinitely, which is the maintenance burden Phase 3 was designed to
   eliminate.

4. **The magic constants dissolve naturally**: `probe_limit=2` becomes a
   trace annotation, not a gating decision.  The LLM's decision field
   naturally handles "should I ask again or proceed?" with richer context
   than a fixed counter.

5. **K4 knowledge injection finally reaches the decision point**: PCM
   currently computes `_RUNTIME_DEFAULTS` but doesn't use them to prevent
   probes (the Phase 2 P0 spec's original goal).  Option B fixes this by
   injecting `runtime_defaults_available` into the Stage 2 payload, where
   the LLM can factor it into its decision.

### Implementation Steps

**Step 4.1 — Add `pcm_advisory` to Stage 2 payload (Wave 1, flag=true only)**

- File: `core/contracts/clarification_contract.py`
- In `before_turn`, after `_resolve_collection_mode` (line 369):
  - When `ENABLE_LLM_DECISION_FIELD=true`: instead of entering the probe block
    (lines 388-409), compute `pcm_advisory` dict with:
    - `unfilled_optionals_without_default`
    - `runtime_defaults_available` (from `_RUNTIME_DEFAULTS` + tool_spec defaults)
    - `confirm_first_detected`
    - `suggested_probe_slot` (first unfilled optional, if any)
    - `collection_mode_active: true/false`
  - Set `should_proceed = True` (don't block)
  - Inject `pcm_advisory` into Stage 2 payload (when Stage 2 is called)
  - Keep telemetry recording of PCM state for trace
  - When `ENABLE_LLM_DECISION_FIELD=false`: PCM continues to set
    `should_proceed=False` and return `ContractInterception` as before
    (unchanged current behavior)

**Step 4.2 — Add `pcm_advisory` to Stage 2 payload (Wave 2, flag=true only)**

- File: `core/contracts/execution_readiness_contract.py`
- When `ENABLE_LLM_DECISION_FIELD=true`: compute advisory from
  `_classify_missing_optionals`, inject into Stage 2 payload.  Remove hard
  `ContractInterception(proceed=False)` for optional-only probes.
- When `ENABLE_LLM_DECISION_FIELD=false`: retain current hard-blocking behavior
  (unchanged)

**Step 4.3 — Update Stage 2 system prompt (K9 rule)**

- File: `core/contracts/clarification_contract.py` (Stage 2 system prompt)
- Add rule 18 (K9): consume `pcm_advisory` field, treat as non-binding
  recommendation

**Step 4.4 — Remove hard-blocking PCM consumption (flag=true only)**

- Remove `should_proceed = False` for PCM cases (gated by `ENABLE_LLM_DECISION_FIELD`)
- Remove `pending_decision = "probe_optional"` path (gated by flag)
- `probe_limit`/`probe_turn_count` become trace-only when flag=true

**Step 4.5 — Update tests (two-mode)**

- Keep existing PCM hard-blocking tests as-is for `flag=false` regression
  protection (unchanged).
- Add `flag=true` advisory-mode tests:
  - PCM trigger tests → assert advisory is generated AND execution is not
    blocked (proceed/decision_field path taken)
  - `probe_abandoned` tests → assert trace contains abandon signal but
    execution proceeds
  - Contract split tests → verify PARAMETER_COLLECTION continuation is
    non-blocking under flag=true

**Step 4.6 — Smoke verification**

- Run 30-task smoke with `ENABLE_LLM_DECISION_FIELD=true`:
  - Expected: ON mode ≥ 86.67% (closing the ON/OFF gap)
  - Key metrics: `decision_field_evaluation` trace steps per task,
    `clarify` vs `proceed` ratio
- Run 30-task smoke with `ENABLE_LLM_DECISION_FIELD=false`:
  - Verify OFF mode is completely unchanged from baseline (same PCM
    hard-blocking behavior as pre-Phase-4)
- Sample tasks to trace-walk:
  - `e2e_codeswitch_161` (L3 reference task — should proceed with model_year default)
  - `e2e_ambiguous_034` (simple missing optional — should proceed)
  - `e2e_clarification_101` (genuinely missing required — should clarify)
- Compare `clarification_question` quality between Stage 2 LLM (advisory
  path) and `_run_probe_question_llm` (legacy path) on 5-10 sample tasks.
  Decision on whether to remove `_run_probe_question_llm` depends on this
  comparison (see §7 Q5).

**Effort**: **M** (medium, ~4-6 files changed, ~150 lines net code change)

## 7. Uncertainties / Needs Human Review

1. **Wave 1 vs Wave 2 consolidation**: Both waves have PCM logic.  Should
   Option B be applied to both waves simultaneously, or should Wave 1
   (legacy, non-contract-split) be handled first as the lower-risk path?
   My preliminary view: do both simultaneously to avoid a partial-PCM
   state where one wave blocks and the other advises.  Flag-gating reduces
   this risk (both waves change behavior only when flag=true; flag=false
   keeps both waves at current behavior), but the change surface size is
   still a consideration.

2. **`ENABLE_LLM_DECISION_FIELD=false` default behavior**: **Final decision:
   flag=false keeps PCM's current full hardcoded governance behavior
   (missing_required hard-block + optional probe + confirm_first detection +
   probe_limit).  flag=true enables Option B advisory routing.**  This means
   Option B and Option C are unified under a single flag: flag=false = Option C
   fallback (hardcoded PCM), flag=true = Option B (PCM advisory + LLM
   decision field).  The flag carries the semantic "enable LLM-deferential
   routing," consistent with §7.1 F1 locking principle.

   Reasons:
   1. **Backward compatibility**: flag=false default configuration behaves
      identically to pre-Phase-3 system.  No surprise behavior change for
      production deployments.
   2. **Baseline comparability**: If flag=false behavior changed (e.g., letting
      optional probes fall through to execution), the OFF baseline 86.67%
      would shift, requiring re-baselining.  With this decision, OFF baseline
      stays at 86.67%, giving clean ON vs OFF comparison for experimental
      rigor.
   3. **Flag semantics clarity**: `flag=true` is not merely "decision field
      enabled" — it means "the full LLM-deferential decision path is active
      (PCM advisory + decision field + Q3 gate deferral)."  `flag=false` means
      "the full hardcoded governance path is active (PCM hard-block + legacy
      contract path)."  These two paths are mutually exclusive and
      independently testable.
   4. **Risk reduction**: Option B under flag=true is a new code path.  If
      production issues arise, operators can roll back instantly via
      `export ENABLE_LLM_DECISION_FIELD=false` without redeployment.  The
      flag=false path is the proven, tested fallback.

3. **`confirm_first` detection**: Currently substring-matched.  Under
   flag=true, should `confirm_first_detected` be injected as an advisory
   signal into Stage 2, or should detection move entirely to Stage 2 LLM
   stance detection?  (Under flag=false, current substring-match
   hard-blocking is preserved unchanged.)  Preliminary view: inject as
   advisory signal (`confirm_first_detected: true`) and let LLM decide.
   The substring match stays as a high-recall detector; LLM stance
   resolution provides precision.  This is a P2 pattern improvement
   without full removal.

4. **Multi-turn PCM state**: Under flag=true (PCM advisory-only), does
   `collection_mode` state still need to persist across turns?  (Under
   flag=false, current collection_mode persistence is preserved unchanged.)
   Preliminary view: keep `collection_mode` as a trace/context signal for
   multi-turn awareness but don't let it gate execution.  The LLM sees
   "this is turn 2 of parameter collection for slot X" in advisory and
   can factor it into its decision.  Remove if it proves unnecessary
   after smoke testing.

5. **`probe_question` LLM call**: **Final decision: keep
   `_run_probe_question_llm` unchanged during Phase 4 implementation.**
   Decide whether to remove it after Step 4.6 smoke verification.

   Reasons:
   1. **Stage 2 LLM clarification_question quality is unverified**: Phase 3
      Step 1 did not independently evaluate the quality of
      `clarification_question` output from Stage 2 LLM under the combined
      prompt schema `{value, confidence, reasoning, clarification_question}`.
      It is unknown whether Stage 2's question quality matches the dedicated
      single-purpose `_run_probe_question_llm`.
   2. **UX regression risk**: If Stage 2 LLM's `clarification_question` is
      weaker than `_run_probe_question_llm` (e.g., inconsistent format,
      less user-friendly phrasing), removing the dedicated call would degrade
      user experience.
   3. **Scope discipline**: Phase 4 task scope is PCM hard-block → advisory.
      Expanding scope to LLM call simplification adds risk without addressing
      the 83% short-circuit bottleneck.
   4. **Data-driven decision**: After Step 4.6 smoke, sample 5-10 tasks that
      take the ON PCM advisory path.  Compare Stage 2 LLM
      `clarification_question` against `_run_probe_question_llm` output on
      quality dimensions: tone appropriateness, factual accuracy, context
      usage.  Decide based on comparative data.

6. **Backward compatibility of eval baselines**: **Final decision: only ON
   baseline changes (from 80% rising to ≥ 86.67%, i.e., catching up to or
   exceeding OFF baseline).  OFF baseline stays at 86.67% unchanged, because
   revision 1 (§7 Q2) ensures PCM keeps its current full hard-blocking
   behavior when `flag=false`.**

   Reasons:
   1. **Experimental rigor**: OFF is the control group (no LLM-deferential
      path).  Keeping it unchanged makes ON vs OFF comparison meaningful.
      ON baseline change reflects the true gain from LLM-deferential routing;
      OFF baseline as control is not confounded.
   2. **Paper narrative clarity**: "Introduce LLM-deferential routing as an
      opt-in via `ENABLE_LLM_DECISION_FIELD=true`.  Baseline 86.67% (control)
      → X% (LLM-deferential)" is more convincing than "both re-baselined."
      The former reads like "we added one carefully gated optimization"; the
      latter reads like "we changed everything."
   3. **Production deployment safety**: OFF unchanged means any user on the
      default configuration sees zero behavior change.
      `ENABLE_LLM_DECISION_FIELD=true` is an explicit opt-in; behavior change
      is expected, not a surprise.
   4. **Step 4.6 verification simplified**: Smoke checklist only needs to
      verify (a) ON rises to ≥ OFF, (b) OFF is completely unchanged (matches
      pre-Phase-4 OFF data).  No "establish new baseline for both" step
      needed.

7. **Q3 gate scope after PCM reduction**: When `flag=true`, PCM no longer
   produces `should_proceed=False`, so the Q3 gate only fires for
   `missing_required` cases.  When `flag=false`, Q3 gate behavior is
   unchanged (fires for both missing_required and optional probes).  The
   remaining question: should `missing_required` be deferred to LLM decision
   field at all, or should it always hard-clarify regardless of decision
   field?  Preliminary view: current Q3 gate deferral for `missing_required`
   is correct, because the LLM may infer missing values from context or
   decide to ask a better question than the hardcoded template.  No change
   needed.
