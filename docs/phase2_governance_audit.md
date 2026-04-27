# Phase 2 Governance Decision Point Audit

> Read-only audit produced from a static code walk on branch
> `task-pack-a-llm-reply-parser`. No code, env, or config files were modified.
> Today: 2026-04-27.

## 1. Scope and Method

### 1.1 What "governance decision point" means in this audit

A *governance decision point* is any code site where a non-LLM component
(GovernedRouter wrapper, AOManager, contracts, classifiers, readiness/affordance
layer, reply pipeline) **observes the LLM-bound state and then chooses to
override, gate, mutate, short-circuit, or rewrite** the user/LLM/tool
interaction. The criterion is behavioral, not file-location-based — a site in
`core/router.py` is in scope if it acts as governance even though `router.py`
is the inner router.

### 1.2 Files surveyed

Static read of:

- `core/governed_router.py` (the contract orchestrator)
- `core/contracts/{base,oasc,clarification,intent_resolution,stance_resolution,execution_readiness,dependency,split_contract_utils,runtime_defaults}.py`
- `core/ao_manager.py`, `core/ao_classifier.py`
- `core/intent_resolver.py`, `core/stance_resolver.py`
- `core/reply/{llm_parser,reply_context_builder,reply_context}.py`
- `core/constraint_violation_writer.py`
- Governance-adjacent hooks in `core/router.py` (cross-constraint preflight,
  readiness assessment, capability summary injection) — only the entry points,
  not the 12 K-line monolith in full
- `tools/contract_loader.py` + `config/tool_contracts.yaml` for slot/contract
  shape (referenced, not enumerated)

Surveyed for context only:

- `README.md`, `AGENTS.md`, `SYSTEM_FOR_PAPER_REFACTOR.md`
- `docs/phase2_a_completion_report.md`, `docs/phase2_b_completion_report.md`

### 1.3 Method

For each candidate site, I recorded the trigger, inputs, outputs, the actual
3–8 line excerpt, classified it under T5.2 categories, and flagged
implementation-vs-ideal alignment. When uncertain, I marked
`needs human review` rather than guess.

### 1.4 What this audit does NOT cover

- The 4 pre-existing fail-mode buckets (L1 evaluation isolation / L2 turn
  classification / L3 optional probe / L4 stage data flow) are **not defined
  inside the codebase under any name I could grep**. The mapping to those
  buckets in §3 is best-effort based on the names in the prompt; every
  cross-reference is marked `uncertain`. A human with the L1–L4 task list
  needs to confirm.
- `core/naive_router.py` is not in scope (it has its own reply path and
  bypasses GovernedRouter).
- Inner-router synthesis prompt construction is only sampled at the entry
  point (`_build_capability_summary_for_synthesis`); the deep planning /
  plan-repair / workflow-template machinery is referenced but not enumerated
  decision-point-by-decision-point.

## 2. Vertical Domain Context

### 2.1 What this agent does

EmissionAgent is a research-stage LLM-tool-use system for **vehicle traffic
emission analysis**. Per `README.md` and `SYSTEM_FOR_PAPER_REFACTOR.md` the
production scenarios are:

- Emission factor curves (MOVES-based, by vehicle type / pollutant / model
  year / season / road type)
- Microscopic emission calculation (VSP + MOVES factor matrix, second-by-
  second from trajectory data)
- Macroscopic emission calculation (MOVES-Matrix at link / road-network level)
- Air-quality dispersion modeling and hotspot analysis on top of emission
  output
- Spatial map rendering of emission/dispersion/hotspot results
- Knowledge / RAG retrieval over emission methods and standards

### 2.2 Domain-specific constraints visible in the code

- **Methodological lineage**: 13 MOVES vehicle types with VSP coefficients
  (A/B/C/M/m); pollutant set is bounded (CO2, NOx, PM2.5, PM10, CO, THC).
- **Standard-cited defaults**: `core/remediation_policy.py` cites HCM 6th ed.
  for default traffic-flow values per OSM road class (`motorway`, `trunk`,
  `primary`, etc.). This is unusual — it is a citable, audit-grade default.
- **Cross-parameter physical consistency**: `services/cross_constraints.py` +
  `config/tool_contracts.yaml` encode rules like
  `vehicle_road_compatibility`, `vehicle_pollutant_relevance`,
  `pollutant_task_applicability`, `season_meteorology_consistency`. These are
  domain rules, not generic schema rules.
- **Data-shape requirements per tool**: macro emission needs `link_id`,
  `link_length_km`, `traffic_flow_vph`, `avg_speed_kph`; micro emission needs
  `timestamp_s`, `speed_kph`, `vehicle_type`. The readiness layer encodes
  these as `_FIELD_LABELS` / `_FIELD_REPAIR_HINTS` (`core/readiness.py:47-67`).
- **Spatial-capability gating**: 14 geometry column tokens
  (`geometry`, `geom`, `wkt`, `geojson`, `lon`, `lat`, …) are used to detect
  whether a dataset can support map rendering — purely a domain check
  (`core/readiness.py:25-39`).
- **Bounded tool DAG**: TOOL_GRAPH defines a fixed pipeline
  (`emission` → `dispersion` → `hotspot` → render); upstream tokens gate
  downstream tools.
- **Result auditability requirement**: `core/trace.py` defines ~100
  `TraceStepType` values, and `phase2_b_completion_report.md` describes
  ViolationRecord with `source_turn` and HCM-cited defaults — i.e. the
  pipeline is built to be paper-publishable.

### 2.3 Where the governance layer reflects vertical domain (vs. is generic)

Reflected:

- Cross-constraint preflight in `core/router.py:2166-2308` is genuinely
  domain-specific (vehicle/road/pollutant/season relations).
- `core/readiness.py` field labels and repair hints are emission-domain
  (`link_length_km`, `traffic_flow_vph`, etc.).
- Runtime defaults in `core/contracts/runtime_defaults.py` (`model_year=2020`
  for `query_emission_factors`) are domain-aware.
- ClarificationContract fallback question text uses domain examples
  (`Passenger Car`, `Transit Bus`, `CO2`, `NOx`, `PM2.5`).
- AOManager's "objective implies which tool" logic in
  `_extract_implied_tools()` (lines 566-586) hardcodes Chinese/English
  emission-domain keywords (`因子`/`factor`, `扩散`/`dispersion`,
  `热点`/`hotspot`, …).

Generic / not domain-aware:

- Turn classification (`AOClassType`: NEW_AO/CONTINUATION/REVISION) is purely
  conversational and would apply to any agent.
- Stance classification (DIRECTIVE/DELIBERATIVE/EXPLORATORY) is generic
  conversational stance logic; domain enters only through the slot-filler's
  legal values.
- Probe limits, probe abandon markers, reversal markers — all generic.

## 3. Decision Point Inventory

Numbering: §3.1 GovernedRouter shell → §3.2 OASC contract / classifier →
§3.3 Clarification (legacy single contract) → §3.4 Wave-2 split contracts →
§3.5 AOManager lifecycle → §3.6 Reply pipeline →
§3.7 Inner-router governance hooks.

### 3.1 GovernedRouter shell

#### 3.1.1 Contract pipeline gate (proceed=False short-circuit)
- **Location**: `core/governed_router.py:112-128`, `chat()`
- **Trigger**: Any contract's `before_turn(...)` returns
  `ContractInterception(proceed=False, response=...)`. This gates the inner
  LLM call entirely.
- **Inputs**: ContractContext (user message, file path, trace, accumulated
  metadata).
- **Outputs**: Replaces inner-router invocation with the contract-supplied
  RouterResponse — the LLM never sees this turn.
- **Code Excerpt**:
```python
for contract in self.contracts:
    interception = await contract.before_turn(context)
    if interception.user_message_override is not None:
        context.user_message_override = interception.user_message_override
    if interception.metadata:
        context.metadata.update(interception.metadata)
    ...
    if not interception.proceed:
        result = interception.response or RouterResponse(text="")
        break
```
- **Classification**: Hard Constraint (it is the *mechanism*; semantic content
  comes from each contract).
- **Alignment**: aligned (clean orchestrator pattern).
- **Related Fail Mode**: uncertain — depending on which contract triggers, can
  surface as L2 (turn-class wrong) or L4 (stage data flow wrong).

#### 3.1.2 Snapshot direct execution (skip LLM, run tool directly)
- **Location**: `core/governed_router.py:355-408`,
  `_maybe_execute_from_snapshot()`
- **Trigger**: ClarificationContract `after_turn` produced a
  `direct_execution` block in `context.metadata["clarification"]` with a tool
  name and a parameter snapshot.
- **Inputs**: clarification telemetry, parameter snapshot, tool name,
  trigger_mode, runtime_defaults_allowed.
- **Outputs**: Calls `inner_router.executor.execute(tool_name, arguments,
  file_path)` directly, bypassing the LLM tool-selection path; flips telemetry
  `proceed_mode` to `snapshot_direct`.
- **Code Excerpt**:
```python
direct_execution = clarification_state.get("direct_execution")
...
tool_name = str(direct_execution.get("tool_name") or "").strip()
snapshot = direct_execution.get("parameter_snapshot")
...
response = await self._execute_from_snapshot(
    tool_name=tool_name, snapshot=snapshot,
    allow_factor_year_default=allow_factor_year_default, ...)
```
- **Classification**: Hard Constraint — once governance has decided the tool
  and parameters, it commits to that decision and skips the LLM.
- **Alignment**: MISALIGNED (uncertain). It is unambiguously a governance
  override of the LLM's tool-selection role. Whether that is the intended
  contract depends on whether the LLM should ever see "all parameters
  filled — please call X". Marked uncertain — this is a load-bearing pattern
  and may be the intended design.
- **Related Fail Mode**: L4 (stage data flow) — if the snapshot is wrong, the
  LLM has no chance to repair it.

#### 3.1.3 Runtime default for `model_year` in factor queries
- **Location**: `core/governed_router.py:364-375` and
  `_snapshot_to_tool_args()` lines 667-685; `core/contracts/runtime_defaults.py`
- **Trigger**: tool_name is `query_emission_factors`, trigger_mode is `fresh`,
  `confirm_first_detected` is False, `model_year` slot empty.
- **Inputs**: snapshot, runtime_defaults_allowed, defaults from
  `unified_mappings.yaml`.
- **Outputs**: Injects `model_year=2020` (per `_RUNTIME_DEFAULTS`) into tool
  arguments without asking the user.
- **Code Excerpt**:
```python
allow_factor_year_default = bool(
    tool_name == "query_emission_factors"
    and str(direct_execution.get("trigger_mode") or "") == "fresh"
    and not bool(direct_execution.get("confirm_first_detected"))
)
...
if "model_year" in runtime_defaults_allowed and tool_name == "query_emission_factors":
    allow_factor_year_default = True
```
- **Classification**: Hard Constraint (with domain default).
- **Alignment**: aligned — this is a documented policy choice (factor query is
  parameter-tolerant; default year of 2020 is a domain convention). Comment
  in `runtime_defaults.py:31` explicitly says "runtime defaults reflect actual
  router execution behavior; YAML defaults are declarative-level hints that
  may lag behind operational reality."
- **Related Fail Mode**: uncertain (would manifest as L4 stage data flow if
  the year is wrong for the user's intent).

#### 3.1.4 Cross-constraint violation persistence
- **Location**: `core/governed_router.py:262-307`,
  `_record_constraint_violations_from_trace()`
- **Trigger**: After inner router returns, scan trace steps with type
  `cross_constraint_violation` (severity=`reject`),
  `cross_constraint_warning` (severity=`warn`), or standardization records
  with `record_type=cross_constraint_violation/warning`
  (severity=`negotiate`/`warn`).
- **Inputs**: trace steps, current turn index.
- **Outputs**: Calls `ConstraintViolationWriter.record(...)`, writing to AO
  `constraint_violations` and replacing context-store
  `_latest_constraint_violations`.
- **Code Excerpt**:
```python
for severity, payload, timestamp in self._iter_constraint_violation_events(steps):
    record = normalize_cross_constraint_violation(
        payload, severity=severity, source_turn=source_turn, timestamp=timestamp)
    signature = (record.violation_type, record.severity,
                 tuple(sorted((k, repr(v)) for k, v in record.involved_params.items())),
                 record.source_turn)
    if signature in seen: continue
    seen.add(signature)
    self.constraint_violation_writer.record(record)
```
- **Classification**: Hard Constraint (persistence; the *blocking* decision
  was already made upstream — see §3.7.1).
- **Alignment**: aligned. Explicitly designed in Task Pack B as event-based
  trace consumption.
- **Related Fail Mode**: none directly; downstream this feeds
  `ReplyContext.violations` (§3.6.2).

### 3.2 OASC contract and AO classifier

#### 3.2.1 OASCContract.before_turn classification call
- **Location**: `core/contracts/oasc_contract.py:44-72`
- **Trigger**: every turn, gated by `enable_ao_aware_memory` (default True).
- **Inputs**: user message, last 4 working-memory turns, fresh `TaskState`
  snapshot, file_path.
- **Outputs**: Sets `context.metadata["oasc"]["classification"]` and
  `context.state_snapshot`. Calls `_apply_classification(...)` which mutates
  AOManager (creates / revises AO).
- **Code Excerpt**:
```python
state_snapshot = self._build_state_snapshot(context.effective_user_message, context.file_path)
classification = await self.classifier.classify(
    user_message=context.effective_user_message,
    recent_conversation=self._get_recent_turns(),
    task_state=state_snapshot,
)
classifier_ms = round((time.perf_counter() - classifier_start) * 1000, 2)
self._apply_classification(classification, context.effective_user_message)
context.state_snapshot = state_snapshot
```
- **Classification**: **Pure Semantic** in T5.2 sense (turn classification).
- **Alignment**: MISALIGNED (the prompt explicitly flags turn classification
  as a category-3 case where governance should not be the decider). The
  classifier *does* defer to LLM via Layer-2 (§3.2.3), but only when Layer-1
  rules fail and only with confidence threshold — i.e. governance still owns
  the decision boundary.
- **Related Fail Mode**: L2 (turn classification) — high confidence.

#### 3.2.2 AOClassifier rule layer 1 — short-circuit branches
- **Location**: `core/ao_classifier.py:202-269`
- **Trigger**: Each turn when `enable_ao_classifier_rule_layer=True` (default).
- **Inputs**: current AO, ao_history, task_state (active_input_completion,
  active_parameter_negotiation, continuation, control.clarification_question),
  user_message.
- **Outputs**: Possibly returns a classification with `confidence>=0.9` and
  layer=`rule`, skipping LLM Layer-2.
- **Code Excerpt** (the actual branch tower; multiple decision points):
```python
if not ao_history:
    return AOClassification(NEW_AO, ..., confidence=1.0, reasoning="first_message_in_session")
if getattr(task_state, "active_input_completion", None):
    return self._make_continuation("active_input_completion")
if getattr(task_state, "active_parameter_negotiation", None):
    return self._make_continuation("active_parameter_negotiation")
continuation = getattr(task_state, "continuation", None)
if continuation is not None and (continuation.next_tool_name or continuation.residual_plan_summary):
    return self._make_continuation("continuation_pending")
if (current_ao is not None and current_ao.status in {AOStatus.ACTIVE, AOStatus.REVISING}
    and self._is_short_clarification_reply(user_message)):
    return self._make_continuation("short_clarification")
if self._is_pure_file_upload(user_message):
    if current_ao is not None and self._ao_waiting_for_file(current_ao, task_state):
        return self._make_continuation("file_supplement")
revision_target = self._detect_revision_target(user_message)
if revision_target is not None:
    return AOClassification(REVISION, target_ao_id=..., confidence=0.92, ...)
if current_ao is None and not self._has_revision_reference_signals(user_message):
    return AOClassification(NEW_AO, ..., confidence=0.9, ...)
return None  # fall through to LLM Layer-2
```
- **Classification**: each branch is **Pure Semantic** at the T5.2 level
  (continuation vs. new vs. revision is a semantic judgment).
- **Alignment**: MISALIGNED for `_is_short_clarification_reply` (matches
  against a hardcoded list of confirm words and YAML-loaded aliases — this
  is a fragile rule for "the user is replying to my question"); MISALIGNED
  for `_detect_revision_target` (six hardcoded substrings: "改成", "换成",
  "重新算", "重新计算", "instead", "change to", "revise"). All of these
  encode the LLM's job in regex.
- **Related Fail Mode**: L2 (turn classification) — almost certainly the
  primary site for L2 failures, since this returns confidence 0.9–1.0 and
  *does not consult the LLM*.

#### 3.2.3 AOClassifier LLM layer 2
- **Location**: `core/ao_classifier.py:148-200`
- **Trigger**: Layer-1 returned None and `enable_ao_classifier_llm_layer=True`.
- **Inputs**: user message, last 6 conversation messages, AO summary
  (current AO, completed AOs, files_in_session, session_confirmed_parameters).
- **Outputs**: AOClassification with layer=`llm`. Used only if confidence
  ≥ `ao_classifier_confidence_threshold` (default 0.7); otherwise falls
  through to a `NEW_AO` fallback at confidence 0.3.
- **Code Excerpt**:
```python
llm_result = await self._llm_layer2(user_message, recent_conversation)
if llm_result.confidence >= getattr(
    self.config, "ao_classifier_confidence_threshold", 0.7,
):
    self._record_telemetry(...)
    return llm_result
...
fallback = AOClassification(NEW_AO, ..., confidence=0.3,
    reasoning="Fallback: Layer 2 unavailable or low confidence", layer="fallback")
```
- **Classification**: Pure Semantic — LLM-driven, but the *gate* (confidence
  threshold) is governance-owned.
- **Alignment**: aligned in spirit (LLM is consulted), MISALIGNED in detail
  (rejecting the LLM verdict at 0.69 and substituting `NEW_AO` is governance
  overriding LLM).
- **Related Fail Mode**: L2 (turn classification).

#### 3.2.4 OASCContract `_apply_classification`: AO mutation
- **Location**: `core/contracts/oasc_contract.py:244-271`
- **Trigger**: Always after classify().
- **Inputs**: AOClassification, current AO list.
- **Outputs**: Either
  (a) does nothing (continuation with existing AO),
  (b) creates a placeholder AO when continuation but no AO exists,
  (c) revises an AO,
  (d) creates a NEW_AO with INDEPENDENT or REFERENCE relationship.
- **Code Excerpt**:
```python
if cls.classification.value == "continuation":
    if current is None:
        self.ao_manager.create_ao(objective_text=(user_message or "")[:200],
            relationship=AORelationship.INDEPENDENT, current_turn=current_turn)
    return
if cls.classification.value == "revision" and cls.target_ao_id:
    self.ao_manager.revise_ao(parent_ao_id=cls.target_ao_id, ...)
    return
self.ao_manager.create_ao(objective_text=cls.new_objective_text or ...,
    relationship=(AORelationship.REFERENCE if cls.reference_ao_id else AORelationship.INDEPENDENT),
    parent_ao_id=cls.reference_ao_id, current_turn=current_turn)
```
- **Classification**: Hard Constraint (state mutation given a classification),
  but the underlying decision is Pure Semantic (which case to take).
- **Alignment**: aligned given §3.2.1's classification.
- **Related Fail Mode**: L2 (cascades from §3.2.1).

#### 3.2.5 OASCContract.after_turn AO completion
- **Location**: `core/contracts/oasc_contract.py:74-106`,
  feeds `AOManager.complete_ao` (§3.5.2).
- **Trigger**: After router executes; current AO exists.
- **Inputs**: tool calls executed in this turn, working-memory state, file
  context, continuation bundle.
- **Outputs**: Builds `TurnOutcome`, calls `complete_ao(...)` which can
  succeed or be blocked.
- **Code Excerpt**:
```python
if context.router_executed and getattr(self.runtime_config, "enable_ao_aware_memory", True):
    self._sync_ao_from_turn_result(result)
    current_ao = self.ao_manager.get_current_ao()
    if current_ao is not None:
        self._refresh_split_execution_continuation(context, result, current_ao)
        turn_outcome = self._build_turn_outcome(result)
        self.ao_manager.complete_ao(current_ao.ao_id,
            end_turn=self._current_turn_index(), turn_outcome=turn_outcome)
```
- **Classification**: Hard Constraint (lifecycle).
- **Alignment**: aligned.
- **Related Fail Mode**: L4 (stage data flow) — uncertain.

### 3.3 ClarificationContract (legacy, single contract)

> Used when `enable_contract_split=False`. Wave-2 split (§3.4) reuses these
> helpers.

#### 3.3.1 Trigger gate (is_resume OR is_fresh)
- **Location**: `core/contracts/clarification_contract.py:141-159`
- **Trigger**: feature-flag on, classification is NEW_AO/REVISION
  (`is_fresh`) OR previous metadata has `pending=True` (`is_resume`).
- **Inputs**: classification, current AO metadata.
- **Outputs**: If neither fresh nor resume, returns empty interception (LLM
  proceeds normally).
- **Code Excerpt**:
```python
is_resume = bool(pending_state and pending_state.get("pending"))
is_fresh = bool(classification is not None and
    classification.classification in {AOClassType.NEW_AO, AOClassType.REVISION})
if not is_resume and not is_fresh:
    return ContractInterception()
```
- **Classification**: Hard Constraint (controls *whether* this contract acts).
- **Alignment**: aligned.
- **Related Fail Mode**: cascades from §3.2 (turn classification wrong →
  this gate fires when it shouldn't, or vice-versa).

#### 3.3.2 Stage 1 — heuristic slot extraction from message hints
- **Location**: `core/contracts/clarification_contract.py:615-649`,
  `_run_stage1`
- **Trigger**: Always, after gate passes.
- **Inputs**: regex-extracted hints from user message (via
  `inner_router._extract_message_execution_hints`) — `vehicle_type`,
  `pollutants`, `season`, `road_type`, `meteorology`, `stability_class`,
  `model_year`.
- **Outputs**: Pre-fills snapshot slots with `source=user, confidence=1.0`.
- **Code Excerpt**:
```python
def apply(slot_name, value, raw_text):
    if value in (None, "", []): return
    snapshot[slot_name] = self._slot_record(value, "user", 1.0, raw_text)
    filled.append(slot_name)
apply("vehicle_type", hints.get("vehicle_type"), hints.get("vehicle_type_raw") or hints.get("vehicle_type"))
if hints.get("pollutants"):
    pollutants = list(hints.get("pollutants") or [])
    apply("pollutants", pollutants, pollutants)
apply("season", hints.get("season"), hints.get("season_raw") or hints.get("season"))
```
- **Classification**: Soft Guidance (pre-extraction only; can be overwritten
  by Stage 2 LLM).
- **Alignment**: uncertain — Stage 1 hardcodes `confidence=1.0` for regex
  extractions, which makes them unreviewable by Stage 2 unless Stage 2
  explicitly overwrites. needs human review.
- **Related Fail Mode**: L4 (stage data flow) — fixed-confidence regex output
  may dominate Stage 2 LLM output silently.

#### 3.3.3 Stage 2 LLM — slot/intent/stance bundle
- **Location**: `core/contracts/clarification_contract.py:651-714`,
  `_run_stage2_llm` and `_stage2_system_prompt`
- **Trigger**: Stage 1 leaves required slots missing AND
  `enable_clarification_stage2_llm=True` AND llm_client available; or
  `tool_name` cannot be resolved at all.
- **Inputs**: user_message, tool_name, available_tools description, file
  context, snapshot, tool_spec (required/optional/defaults/legal_values),
  classification name.
- **Outputs**: dict with `slots`, `intent`, `stance`, `chain`,
  `missing_required`, `needs_clarification`, `clarification_question`,
  `ambiguous_slots`. Used to merge into snapshot, drive intent, drive stance.
- **Code Excerpt** (system prompt fragment showing the contract):
```python
"6. 可用工具: query_emission_factors=查询排放因子; "
"calculate_micro_emission=VSP逐秒微观排放; calculate_macro_emission=路段级宏观排放; "
"query_knowledge=知识库检索。\n"
"7. 如果用户明确说先确认参数但未指定工具类别，intent_confidence=none；"
"如果说"那类因子"等工具关键词，intent_confidence=high。\n"
"8. 同时判断用户的对话姿态 stance: {value, confidence, reasoning}。"
"value 只能是 directive/deliberative/exploratory。\n"
```
- **Classification**: Pure Semantic by content (intent/stance/slot semantics
  belong to the LLM), but the *prompt envelope and post-processing* are
  governance-owned.
- **Alignment**: aligned that Stage 2 calls the LLM; MISALIGNED that one LLM
  call simultaneously decides slots, intent, AND stance — coupling three
  semantic decisions through one prompt makes failure modes hard to isolate.
- **Related Fail Mode**: L1 (evaluation isolation — one LLM call covers three
  semantic axes; correlated failures collapse into one event), L4 (stage
  data flow — Stage 2 output drives downstream snapshot).

#### 3.3.4 Stage 3 — value standardization, defaults, rejection
- **Location**: `core/contracts/clarification_contract.py:879-948`,
  `_run_stage3`
- **Trigger**: Always, after Stage 1 & 2.
- **Inputs**: snapshot, tool_spec defaults, suppress_defaults_for, confidence
  threshold.
- **Outputs**: Normalized snapshot, list of normalizations, list of
  rejected_slots. **Inferred slots below confidence threshold are demoted to
  `source=missing`. Slots that fail standardization (and are not LLM-validated
  candidates) are marked `source=rejected`** with suggestions.
- **Code Excerpt**:
```python
if source == "inferred" and confidence is not None and float(confidence) < confidence_threshold:
    updated[slot_name] = self._slot_record(None, "missing", None, raw_text)
    continue
normalized, success, strategy, suggestions = self._standardize_slot(
    slot_name, value=value, raw_text=raw_text)
if success:
    updated[slot_name]["value"] = normalized
    normalizations.append({...})
    continue
if source == "inferred" and self._is_legal_candidate(slot_name, value):
    ...; continue
updated[slot_name]["source"] = "rejected"
updated[slot_name]["value"] = None
updated[slot_name]["suggestions"] = list(suggestions or [])
rejected_slots.append(slot_name)
```
- **Classification**: Hard Constraint (legal-value enforcement) +
  Soft Guidance (default injection).
- **Alignment**: aligned for legal-value enforcement (domain hard rule);
  MISALIGNED for the inferred-confidence threshold — the threshold itself
  (default 0.7) is a *prior* governance imposes on the LLM's slot
  confidence.
- **Related Fail Mode**: L4 (stage data flow) — silent demotion of
  `inferred` slots to `missing` is a quiet override of the LLM's hint.

#### 3.3.5 Collection-mode resolution (PCM trigger)
- **Location**: `core/contracts/clarification_contract.py:1237-1269`,
  `_resolve_collection_mode`
- **Trigger**: After Stage 3 produces missing/rejected counts.
- **Inputs**: ao, missing_required, confirm_first_detected,
  unfilled_optionals_without_default, is_resume.
- **Outputs**: `(collection_mode: bool, pcm_trigger_reason: Optional[str])`.
  Drives optional-slot probing.
- **Code Excerpt**:
```python
if is_resume:
    return self._current_collection_mode(ao)
if confirm_first_detected:
    return True, "confirm_first_signal"
if self._is_first_ao_turn(ao):
    if missing_required:
        return True, "missing_required_at_first_turn"
    if unfilled_optionals_without_default:
        return True, "unfilled_optional_no_default_at_first_turn"
    return False, None
return self._current_collection_mode(ao)
```
- **Classification**: Soft Guidance (governance suggests collecting more
  before executing).
- **Alignment**: uncertain — "first AO turn AND any unfilled optional with no
  default → collect" is a strong prior that may cause unnecessary probing.
- **Related Fail Mode**: L3 (optional probe) — direct site.

#### 3.3.6 Optional-slot probe with abandon at probe_turn_count >= 2
- **Location**: `core/contracts/clarification_contract.py:367-385`
- **Trigger**: collection_mode=True AND no missing required AND there is at
  least one unfilled optional without a default.
- **Inputs**: pending_state (carries `probe_optional_slot`,
  `probe_turn_count`).
- **Outputs**: If probe_turn_count would reach 2, abandons probing and
  proceeds. Otherwise asks a probe question (LLM-generated, §3.3.7).
- **Code Excerpt**:
```python
if unfilled_optionals_without_default:
    probe_optional_slot = unfilled_optionals_without_default[0]
    probe_turn_count = self._next_probe_turn_count(pending_state, probe_optional_slot)
    if probe_turn_count >= 2:
        telemetry.probe_abandoned = True
        should_proceed = True
    else:
        pending_decision = "probe_optional"
        pending_slots = [probe_optional_slot]
        question = await self._build_probe_question(...)
```
- **Classification**: Soft Guidance (probing optional fields is advisory).
- **Alignment**: MISALIGNED in the magic constant — `>= 2` is a hardcoded
  ceiling that the LLM cannot influence. The *decision to probe at all* is
  also governance-side, not LLM-side.
- **Related Fail Mode**: L3 (optional probe) — direct site.

#### 3.3.7 Probe question generation (LLM-backed) and fallback
- **Location**: `core/contracts/clarification_contract.py:1026-1082`,
  `_run_probe_question_llm` and `_build_probe_question`
- **Trigger**: Probe slot decided in §3.3.6.
- **Inputs**: tool_name, slot_name, slot display name, valid-values
  description, snapshot, current AO objective.
- **Outputs**: Asks LLM for a "one-sentence clarification question" then
  falls back to a templated string `f"请指定{slot_display_name}（{values}）。"`.
- **Code Excerpt**:
```python
response = await asyncio.wait_for(
    self.llm_client.chat_json(
        messages=[{"role": "user", "content": yaml.safe_dump(prompt_payload, ...)}],
        system=("你是交通排放分析的澄清问题生成器。"
                "请针对指定参数生成一句简洁自然的追问，..."
                '输出 JSON: {"clarification_question": "..."}'),
        temperature=0.0,
    ),
    timeout=float(getattr(self.runtime_config, "clarification_llm_timeout_sec", 5.0)),
)
question = str((response or {}).get("clarification_question") or "").strip()
return question or None
```
- **Classification**: Pure Semantic (asking a question is the LLM's job).
- **Alignment**: aligned that LLM is asked; MISALIGNED that the *decision to
  probe at all* is upstream and governance-owned.
- **Related Fail Mode**: L3 (optional probe).

#### 3.3.8 confirm-first signal detection
- **Location**: `core/contracts/clarification_contract.py:1447-1508`,
  `_detect_confirm_first` and pattern helpers
- **Trigger**: trigger_mode=fresh.
- **Inputs**: user_message, runtime_config signals/patterns lists.
- **Outputs**: `confirm_first_trigger` string or None — flips
  `collection_mode` to True with reason `confirm_first_signal`.
- **Code Excerpt**:
```python
signals = tuple(getattr(self.runtime_config, "clarification_confirm_first_signals", ()) or ())
for signal in signals:
    if signal and signal in text:
        return f"signal:{signal}"
patterns = set(getattr(self.runtime_config, "clarification_confirm_first_patterns", ()) or ())
if "need_parameters_fuzzy" in patterns and re.search(r"需要.{0,12}参数", text):
    return "pattern:need_parameters_fuzzy"
if "leading_sequence_marker" in patterns and self._matches_leading_sequence_marker(text):
    return "pattern:leading_sequence_marker"
if "parameter_request" in patterns and self._matches_parameter_request(text):
    return "pattern:parameter_request"
```
- **Classification**: **Pure Semantic** (deciding whether the user wants to
  confirm first is intent inference).
- **Alignment**: MISALIGNED — this duplicates intent inference that Stage 2
  LLM also returns as `stance=deliberative`. Two parallel rules disagree
  silently.
- **Related Fail Mode**: L1 (evaluation isolation — parallel signals are not
  reconciled), L2 (turn classification — what the user wants).

#### 3.3.9 Question-vs-proceed final decision
- **Location**: `core/contracts/clarification_contract.py:354-440`
- **Trigger**: After Stage 3 + collection mode resolution.
- **Inputs**: missing_required, rejected_slots, collection_mode,
  unfilled_optionals_without_default, probe state.
- **Outputs**: Either `proceed=False` with question (short-circuit) or
  `proceed=True` with `direct_execution` block.
- **Code Excerpt** (decision tree):
```python
if missing_required or rejected_slots:
    pending_decision = "clarify_required"
    pending_slots = list(dict.fromkeys([*missing_required, *rejected_slots]))
    question = self._build_question(...)
elif not collection_mode:
    should_proceed = True
else:
    if unfilled_optionals_without_default:
        probe_optional_slot = unfilled_optionals_without_default[0]
        probe_turn_count = self._next_probe_turn_count(...)
        if probe_turn_count >= 2:
            telemetry.probe_abandoned = True; should_proceed = True
        else:
            pending_decision = "probe_optional"; question = await self._build_probe_question(...)
    else:
        should_proceed = True
```
- **Classification**: Hard Constraint (controls whether the LLM gets the
  turn) over Pure Semantic input.
- **Alignment**: aligned given the upstream decisions, but the cumulative
  effect is that governance can ask the user a question instead of letting
  the LLM ask.
- **Related Fail Mode**: L4 (stage data flow); upstream L2/L3.

#### 3.3.10 Snapshot injection into context (silent override)
- **Location**: `core/contracts/clarification_contract.py:1307-1342`,
  `_inject_snapshot_into_context`
- **Trigger**: should_proceed=True (i.e. governance committed to executing).
- **Inputs**: confirmed snapshot.
- **Outputs**: Mutates `fact_memory.recent_vehicle/recent_pollutants/
  recent_year`, `session_confirmed_parameters`, `locked_parameters_display`,
  current_ao parameters_used, and AO metadata `parameter_snapshot`.
- **Code Excerpt**:
```python
fact_memory.recent_vehicle = str(confirmed["vehicle_type"])
fact_memory.update_session_confirmed_parameters(confirmed)
fact_memory.locked_parameters_display = dict(confirmed)
if current_ao is not None:
    current_ao.metadata["parameter_snapshot"] = copy.deepcopy(snapshot)
    for key, value in confirmed.items():
        current_ao.parameters_used[key] = value
```
- **Classification**: Hard Constraint (parameter lock).
- **Alignment**: aligned (locks in what was confirmed); MISALIGNED in that
  the LLM is not informed *why* a value is locked, only that
  `locked_parameters_display` exists.
- **Related Fail Mode**: L4 (stage data flow).

### 3.4 Wave-2 split contracts

Active when `enable_contract_split=True`. They split §3.3 into
intent / stance / readiness contracts but reuse the same Stage 2 LLM call.

#### 3.4.1 IntentResolutionContract — short-circuit from continuation state
- **Location**: `core/contracts/intent_resolution_contract.py:36-83`
- **Trigger**: classification=continuation, no reversal markers, AO has
  active execution_continuation (chain or parameter collection).
- **Inputs**: `ExecutionContinuation` snapshot, fast-rule intent.
- **Outputs**: Sets tool_intent to `pending_next_tool` or AO-bound tool with
  HIGH confidence, **without consulting LLM Stage 2**.
- **Code Excerpt**:
```python
if continuation.pending_objective == PendingObjective.CHAIN_CONTINUATION \
   and continuation.pending_next_tool \
   and (not fast.projected_chain or fast.projected_chain[0] == continuation.pending_next_tool):
    tool_intent = self.intent_resolver._intent(
        continuation.pending_next_tool, IntentConfidence.HIGH,
        resolved_by="continuation_state", evidence=["continuation_state"], ...)
    short_circuit_intent = True
elif continuation.pending_objective == PendingObjective.PARAMETER_COLLECTION:
    bound_tool = str(getattr(getattr(current_ao, "tool_intent", None), "resolved_tool", "") or "").strip()
    ...
```
- **Classification**: Hard Constraint (governance binds tool from prior
  state).
- **Alignment**: aligned only if continuation tracking is correct; MISALIGNED
  if user has shifted intent without using the configured reversal markers
  ("等等" / "重新" / "改成" / etc.).
- **Related Fail Mode**: L2 (turn classification) cascade, L4 (stage data
  flow).

#### 3.4.2 IntentResolutionContract — clarify-required when intent unresolved
- **Location**: `core/contracts/intent_resolution_contract.py:116-131`
- **Trigger**: After fast resolver and (optionally) Stage 2 LLM, intent
  confidence is still NONE.
- **Inputs**: tool_intent.
- **Outputs**: `proceed=False` with hardcoded question text:
  `"请先说明您想执行哪类交通排放分析：排放因子查询、微观排放、宏观排放或知识库问答。"`
- **Code Excerpt**:
```python
if tool_intent.confidence == IntentConfidence.NONE:
    telemetry = self._telemetry(tool_name=None, decision="clarify",
        branch="intent", pending_slot="tool_intent", stage2_meta=...)
    return ContractInterception(
        proceed=False,
        response=RouterResponse(
            text="请先说明您想执行哪类交通排放分析：排放因子查询、微观排放、宏观排放或知识库问答。",
            ...))
```
- **Classification**: Pure Semantic content (asking which tool) wrapped in a
  Hard Constraint (skip LLM).
- **Alignment**: MISALIGNED — the response text is hardcoded, ignoring user
  context. The LLM would have answered the intent question itself.
- **Related Fail Mode**: L2 (turn classification cascade).

#### 3.4.3 StanceResolutionContract — continuation-side reversal
- **Location**: `core/contracts/stance_resolution_contract.py:32-52`
- **Trigger**: classification=continuation.
- **Inputs**: user message, current AO stance.
- **Outputs**: If user message contains `reversal_signals` ("等等",
  "再想想", "换成", "不对", "改成", "算了还是", "重新"), **forces stance
  to DELIBERATIVE**.
- **Code Excerpt**:
```python
if classification_value == "continuation":
    reversal = self.stance_resolver.detect_reversal(context.effective_user_message, current_ao.stance)
    if reversal is not None:
        evidence = self.stance_resolver.reversal_evidence(context.effective_user_message)
        resolution = StanceResolution(stance=reversal,
            confidence=current_ao.stance_confidence,
            evidence=[evidence or "user_reversal"], resolved_by="user_reversal")
        reversal_detected = True
    else:
        resolution = StanceResolution(stance=current_ao.stance ..., ...)
```
- **Classification**: Pure Semantic (reversal is a semantic intent).
- **Alignment**: MISALIGNED — substring matching for reversal is brittle
  ("重新" appears in "重新查询" which is a continuation, not a reversal).
- **Related Fail Mode**: L2 (turn classification).

#### 3.4.4 StanceResolutionContract — saturated-slot fallback to DIRECTIVE
- **Location**: `core/contracts/stance_resolution_contract.py:99-131`
- **Trigger**: stance is DELIBERATIVE/EXPLORATORY at LOW confidence.
- **Inputs**: tool_intent, payload slots, user_message hedging terms.
- **Outputs**: If a tool is resolved AND all required slots present AND no
  hedging words, **forces stance to DIRECTIVE**.
- **Code Excerpt**:
```python
if (resolution.stance not in {ConversationalStance.DELIBERATIVE, ConversationalStance.EXPLORATORY}
    or resolution.confidence != StanceConfidence.LOW):
    return resolution
...
slots = self._extract_payload_slots(payload)
if not self._check_required_filled_presence(tool_name, slots):
    metadata["stance_fallback_skipped_reason"] = "required_missing"; return resolution
if self._has_explicit_hedging(context.effective_user_message):
    metadata["stance_fallback_skipped_reason"] = "explicit_hedging"; return resolution
metadata["fallback_reason"] = "low_conf_nondirective_with_filled_required"
return StanceResolution(stance=ConversationalStance.DIRECTIVE,
    confidence=StanceConfidence.LOW,
    evidence=list(resolution.evidence) + ["fallback_saturated_slots"],
    resolved_by="fallback_saturated_slots")
```
- **Classification**: Pure Semantic.
- **Alignment**: MISALIGNED — overrides LLM's stance verdict because slots
  are filled. The user might genuinely want to deliberate even with all
  slots set.
- **Related Fail Mode**: L1 (evaluation isolation — slot saturation is being
  used as a stance signal, conflating two axes).

#### 3.4.5 ExecutionReadinessContract — clarify candidates aggregation
- **Location**: `core/contracts/execution_readiness_contract.py:177-225`
- **Trigger**: Always while contract active.
- **Inputs**: missing_required, rejected_slots, missing_followup,
  missing_confirm_first, stage2_needs_clarification, executed_tool_count,
  pending_state.
- **Outputs**: A combined `clarify_candidates` list whose first element
  becomes the next probe slot.
- **Code Excerpt**:
```python
clarify_candidates = list(missing_required) + list(rejected_slots)
clarify_required_candidates = list(missing_required)
clarify_optional_candidates = [s for s in rejected_slots if s not in active_required_slots]
if continuation_before.pending_objective == PendingObjective.PARAMETER_COLLECTION:
    carried_missing = self._missing_named_slots(snapshot, pending_state.get("missing_slots") or [])
    clarify_candidates.extend(carried_missing)
    clarify_candidates.extend(missing_confirm_first)
    clarify_candidates.extend(missing_followup)
if confirm_first_active:
    clarify_candidates.extend(missing_confirm_first)
if stage2_needs_clarification and executed_tool_count == 0:
    stage2_required_candidates = self._missing_named_slots(snapshot, stage2_meta.get("stage2_missing_required") or [])
    clarify_candidates.extend(stage2_required_candidates)
    ...
```
- **Classification**: Hard Constraint (pipeline aggregation logic).
- **Alignment**: MISALIGNED — nine sources feed into one list without a
  documented priority rule beyond list-extend order. Source-of-truth for
  "what to ask next" is opaque.
- **Related Fail Mode**: L4 (stage data flow), L3 (optional probe).

#### 3.4.6 ExecutionReadinessContract — probe-limit force-proceed
- **Location**: `core/contracts/execution_readiness_contract.py:227-244`
- **Trigger**: Optional-only probe AND probe_count >= probe_limit (default 2).
- **Inputs**: optional_only_probe, probe_count_value, probe_limit.
- **Outputs**: Sets `force_proceed_reason="probe_limit_reached"`, clears
  continuation, proceeds to executor.
- **Code Excerpt**:
```python
if optional_only_probe and probe_count_value >= probe_limit:
    force_proceed_reason = "probe_limit_reached"
    continuation_after = ExecutionContinuation(
        pending_objective=PendingObjective.NONE,
        probe_count=probe_count_value, probe_limit=probe_limit, ...)
    save_execution_continuation(current_ao, continuation_after)
    if transition_reason == "no_change": transition_reason = "advance"
```
- **Classification**: Soft Guidance (procedural cap).
- **Alignment**: MISALIGNED — fixed `probe_limit=2` is a magic constant.
- **Related Fail Mode**: L3 (optional probe) — direct site.

#### 3.4.7 ExecutionReadinessContract — exploratory branch short-circuit
- **Location**: `core/contracts/execution_readiness_contract.py:313-346`
- **Trigger**: stance=EXPLORATORY (resolved by §3.4.3/§3.4.4 or LLM).
- **Inputs**: stance_value.
- **Outputs**: Skips all execution, replies with hardcoded:
  `"您想先比较哪类交通排放分析目标？可以指定排放因子、微观排放、宏观排放或扩散影响。"`
- **Code Excerpt**:
```python
if branch == ConversationalStance.EXPLORATORY.value:
    telemetry = self._telemetry(decision="clarify", branch=branch, pending_slot="scope", ...)
    return ContractInterception(
        proceed=False,
        response=RouterResponse(
            text="您想先比较哪类交通排放分析目标？可以指定排放因子、微观排放、宏观排放或扩散影响。",
            ...))
```
- **Classification**: Pure Semantic content wrapped in Hard Constraint.
- **Alignment**: MISALIGNED — same as §3.4.2.
- **Related Fail Mode**: L2 (turn classification cascade).

#### 3.4.8 ExecutionReadinessContract — deliberative probe abandonment
- **Location**: `core/contracts/execution_readiness_contract.py:348-371`
- **Trigger**: branch=deliberative AND there is an unfilled optional with no
  default AND user message has probe-abandon marker OR probe_count >=
  probe_limit.
- **Inputs**: `has_probe_abandon_marker(user_message)`, probe_count.
- **Outputs**: Marks continuation `abandoned=True`, lets execution proceed.
- **Code Excerpt**:
```python
if has_probe_abandon_marker(context.effective_user_message) or probe_count >= probe_limit:
    continuation_after = ExecutionContinuation(
        pending_objective=PendingObjective.PARAMETER_COLLECTION,
        pending_slot=pending_slot, probe_count=probe_count, probe_limit=probe_limit,
        abandoned=True, updated_turn=self._current_turn_index())
    save_execution_continuation(current_ao, continuation_after)
    transition_reason = "abandon_probe_limit"
```
- **Classification**: Soft Guidance.
- **Alignment**: MISALIGNED in the marker-based abandon detection (substring
  match again).
- **Related Fail Mode**: L3 (optional probe).

#### 3.4.9 ExecutionReadinessContract — followup-slot retention after proceed
- **Location**: `core/contracts/execution_readiness_contract.py:431-463`
- **Trigger**: proceed branch reached.
- **Inputs**: followup_slots (from tool_spec), runtime_defaults.
- **Outputs**: If a followup slot is in runtime_defaults AND still empty in
  snapshot, marks continuation pending so we ask the followup *after* the
  tool runs.
- **Code Excerpt**:
```python
preserve_followup_slot = next(
    (slot_name for slot_name in followup_slots
     if slot_name in runtime_defaults and self._snapshot_missing_value(snapshot, slot_name)),
    None,)
if force_proceed_reason: preserve_followup_slot = None
self._persist_split_pending(current_ao, tool_name, preserve_followup_slot, snapshot,
    missing_slots=[preserve_followup_slot] if preserve_followup_slot else [], ...)
```
- **Classification**: Soft Guidance.
- **Alignment**: aligned (unique to the followup-slots concept).
- **Related Fail Mode**: L3 (optional probe).

### 3.5 AOManager lifecycle gates

#### 3.5.1 `_can_complete_ao` — multi-condition completion guard
- **Location**: `core/ao_manager.py:370-410`
- **Trigger**: Called by `complete_ao` and `create_ao` (implicit prior-AO
  closure).
- **Inputs**: parameter_state.collection_mode, execution_continuation,
  tool_intent.confidence, metadata.clarification_contract.pending,
  TurnOutcome (for explicit completions), `_ao_objective_satisfied`.
- **Outputs**: `(should_complete: bool, block_reason: Optional[str], check_results: Dict)`.
  Block reasons: `collection_mode_active`, `execution_continuation_active`,
  `intent_not_resolved`, `metadata_clarification_pending`,
  `basic_checks_failed`, `objective_not_satisfied`.
- **Code Excerpt**:
```python
if self._lifecycle_alignment_enabled():
    if not self._contract_split_enabled():
        if bool(getattr(parameter_state, "collection_mode", False)):
            return False, "collection_mode_active", check_results
    elif continuation_state.is_active():
        return False, "execution_continuation_active", check_results
    if getattr(tool_intent, "confidence", IntentConfidence.NONE) == IntentConfidence.NONE:
        return False, "intent_not_resolved", check_results
if isinstance(clarification_state, dict) and clarification_state.get("pending"):
    return False, "metadata_clarification_pending", check_results
```
- **Classification**: Hard Constraint (lifecycle gate).
- **Alignment**: aligned, but the criteria are *governance-defined* (the LLM
  cannot say "we're done" if any of these are set).
- **Related Fail Mode**: L4 (stage data flow).

#### 3.5.2 `_sync_tool_intent_from_tool_call` — intent backfill from observed execution
- **Location**: `core/ao_manager.py:446-462`
- **Trigger**: A tool call is appended to AO with confidence still NONE.
- **Inputs**: tool_call.tool, current intent.
- **Outputs**: Sets `intent.confidence=HIGH`, `resolved_by=tool_call`.
- **Code Excerpt**:
```python
if getattr(tool_intent, "confidence", IntentConfidence.NONE) != IntentConfidence.NONE:
    return
tool_name = str(getattr(tool_call, "tool", "") or "").strip()
if not tool_name or tool_name == "unknown": return
tool_intent.resolved_tool = tool_name
tool_intent.confidence = IntentConfidence.HIGH
tool_intent.resolved_by = "tool_call"
```
- **Classification**: Hard Constraint (state reconciliation).
- **Alignment**: aligned.
- **Related Fail Mode**: none.

#### 3.5.3 `create_ao` implicit predecessor closure
- **Location**: `core/ao_manager.py:114-171`
- **Trigger**: A new AO is being created while an active/revising AO exists.
- **Inputs**: `_can_complete_ao(active, turn_outcome=None)` result.
- **Outputs**: Active AO becomes COMPLETED, ABANDONED, or remains active
  (with `complete_blocked` telemetry).
- **Code Excerpt**:
```python
if can_complete:
    active.status = AOStatus.COMPLETED
    active.end_turn = max(active.start_turn, int(current_turn or 0) - 1)
    self._record_event(turn=..., event_type="complete", ao=active, ...)
elif block_reason in {"collection_mode_active","intent_not_resolved",
                     "metadata_clarification_pending","execution_continuation_active"}:
    self._record_event(turn=..., event_type="complete_blocked", ...)
else:
    active.status = AOStatus.ABANDONED
    active.end_turn = max(active.start_turn, int(current_turn or 0) - 1)
```
- **Classification**: Hard Constraint.
- **Alignment**: aligned.
- **Related Fail Mode**: L4 (stage data flow).

### 3.6 Reply pipeline

#### 3.6.1 LLM reply parser final rewrite (Phase 2 A)
- **Location**: `core/governed_router.py:179-201`, `_generate_final_reply`;
  `core/reply/llm_parser.py:46-74`
- **Trigger**: Always (when `enable_llm_reply_parser=True`, default), after
  inner router returns and after constraint persistence and contract
  `after_turn` hooks.
- **Inputs**: ReplyContext (user_message, router_text, tool_executions,
  violations, pending_clarifications, ao_status, trace_highlights, extra).
- **Outputs**: Replaces `result.text` with LLM-generated reply or falls back
  to `router_text` on timeout/empty/exception.
- **Code Excerpt**:
```python
if not bool(getattr(runtime_config, "enable_llm_reply_parser", True)):
    return ctx.router_text, {"mode": "legacy_render"}
parser = self.__dict__.get("_reply_parser")
...
try:
    return await parser.parse(ctx)
except (LLMReplyTimeout, LLMReplyError) as exc:
    logger.warning("LLM reply parser failed (%s: %s), keeping router_text", ...)
    return ctx.router_text, {"mode": "fallback", "fallback": True, "reason": ...}
```
- **Classification**: Pure Semantic (rewriting natural language is the LLM's
  domain), wrapped in a governance-defined fallback.
- **Alignment**: aligned (LLM-driven). MISALIGNED only in a subtle sense:
  the system prompt forbids the LLM from "inventing values" and instructs it
  to ask the next question if blocked — that prescription is governance-side.
- **Related Fail Mode**: L1 (evaluation isolation — the rewrite step occurs
  after all upstream decisions; if upstream is wrong, the rewrite makes it
  fluent and harder to diagnose).

#### 3.6.2 ReplyContextBuilder — trace highlight gating
- **Location**: `core/reply/reply_context_builder.py:19-30`,
  `IMPORTANT_TRACE_TYPES`; `_trace_highlights` lines 148-167
- **Trigger**: Always while parser is enabled.
- **Inputs**: trace steps from result.
- **Outputs**: Filters trace to a 9-element allowlist of "important" types
  shown to the reply LLM.
- **Code Excerpt**:
```python
IMPORTANT_TRACE_TYPES = {
    "cross_constraint_violation","cross_constraint_warning","clarification",
    "parameter_standardization","tool_execution","synthesis",
    "parameter_negotiation_required","input_completion_required",
    "action_readiness_blocked","action_readiness_repairable",
}
```
- **Classification**: Soft Guidance (decides which trace events the reply
  LLM can rely on).
- **Alignment**: uncertain — silently dropping events the LLM might need.
- **Related Fail Mode**: L4 (stage data flow).

#### 3.6.3 ConstraintViolationWriter scope: current AO only
- **Location**: `core/constraint_violation_writer.py:90-117`,
  `record(...)` and `get_latest()`
- **Trigger**: Each persisted violation event.
- **Inputs**: ViolationRecord, current AO.
- **Outputs**: Writes to `current_ao.constraint_violations` and replaces
  `context_store.latest_constraint_violations` (previous list overwritten).
  `get_latest()` returns only the *current AO's* violations.
- **Code Excerpt**:
```python
if current_ao is not None:
    current_violations = getattr(current_ao, "constraint_violations", None)
    if not isinstance(current_violations, list):
        current_violations = []
        current_ao.constraint_violations = current_violations
    current_violations.append(record)
    latest = [dict(item) for item in current_violations if isinstance(item, dict)]
else:
    latest = [record]
self.context_store.set_latest_constraint_violations(latest)
```
- **Classification**: Hard Constraint (boundary policy: violations belong to
  the AO that produced them).
- **Alignment**: aligned per Phase 2 B design.
- **Related Fail Mode**: L4 (stage data flow) if AO boundary is wrong.

### 3.7 Inner-router governance hooks

> Calls inside `core/router.py` whose role is governance even though they
> live in the inner router file.

#### 3.7.1 Cross-constraint preflight blocker
- **Location**: `core/router.py:2166-2308`,
  `_evaluate_cross_constraint_preflight`
- **Trigger**: Before each tool execution, after standardizing message hints.
- **Inputs**: vehicle/road/season/meteorology/pollutant standardized values,
  tool_name, `services/cross_constraints.CrossConstraintValidator`.
- **Outputs**: If validator returns violations, sets
  `state.execution.blocked_info`, transitions stage to DONE with a domain
  explanation, and emits `CROSS_CONSTRAINT_VIOLATION` trace step. Returns
  True (skip tool execution).
- **Code Excerpt**:
```python
constraint_result = get_cross_constraint_validator().validate(
    standardized_params, tool_name=tool_name)
...
if not constraint_result.violations: return False
violation = constraint_result.violations[0]
suggestions = list(violation.suggestions or [])
suggestion_text = ("\n\nDid you mean one of these? " + ", ".join(suggestions[:5])
                   if suggestions else "")
message = f"参数组合不合法: {violation.reason}{suggestion_text}"
state.execution.blocked_info = {"message": message, ...}
self._transition_state(state, TaskStage.DONE, ...)
```
- **Classification**: **Hard Constraint** (domain physical/policy rule:
  vehicle/road/pollutant/season compatibility).
- **Alignment**: aligned (this is exactly the kind of thing governance
  should own — it cites domain rules and stops physically inconsistent
  computation).
- **Related Fail Mode**: none from L1–L4 (this is the rare correctly-placed
  governance decision).

#### 3.7.2 Action readiness affordance gate
- **Location**: `core/router.py:9886-9921`,
  `_assess_selected_action_readiness`; readiness layer in
  `core/readiness.py:1-1360`
- **Trigger**: Before tool execution AND before synthesis.
- **Inputs**: tool_name, arguments, prior tool_results, file_context, frontend
  payloads.
- **Outputs**: ReadinessAssessment + ActionAffordance with status in
  {READY, BLOCKED, REPAIRABLE, ALREADY_PROVIDED}. BLOCKED/REPAIRABLE produces
  trace events that propagate via §3.6.2 into pending_clarifications.
- **Code Excerpt**:
```python
assessment = self._build_readiness_assessment(
    tool_results, state=state, frontend_payloads=frontend_payloads,
    trace_obj=trace_obj, stage_before=stage_before, purpose=purpose)
if assessment is None: return None, None
action_id = map_tool_call_to_action_id(tool_name, arguments)
if action_id is None: return assessment, None
affordance = assessment.get_action(action_id)
```
- **Classification**: Hard Constraint (data-shape, geometry, prerequisite
  artifact dependencies — domain rules).
- **Alignment**: aligned (this is governance-appropriate: enforce that
  hotspot analysis can't run without dispersion output).
- **Related Fail Mode**: uncertain.

#### 3.7.3 Capability-aware synthesis hard-constraint injection
- **Location**: `core/router.py:9923-9970`,
  `_build_capability_summary_for_synthesis`; rendering in
  `core/capability_summary.py:60-...`
- **Trigger**: Just before synthesis prompt construction
  (`enable_capability_aware_synthesis=True`, default).
- **Inputs**: tool_results, ReadinessAssessment, IntentResolutionApplicationPlan,
  ArtifactMemoryState.
- **Outputs**: Summary block prefixed with `## 后续建议硬约束` (hard
  constraints for follow-up suggestions) — explicitly inserted into the
  synthesis prompt to **block the LLM** from suggesting unavailable actions.
- **Code Excerpt**:
```python
assessment = self._build_readiness_assessment(...)
if assessment is None: return None
summary = assessment.to_capability_summary()
if (state is not None and state.latest_intent_resolution_plan is not None
    and getattr(self.runtime_config, "intent_resolution_bias_followup_suggestions", True)):
    summary = apply_intent_bias_to_capability_summary(summary, state.latest_intent_resolution_plan)
if (state is not None and getattr(self.runtime_config, "enable_artifact_memory", True)):
    artifact_plan = build_artifact_suggestion_plan(...)
```
- **Classification**: Hard Constraint (constrains what the LLM may say).
- **Alignment**: aligned in spirit (avoid hallucinated next-step suggestions);
  uncertain on whether the *hard* framing is too strict — the prompt label
  literally is "硬约束" / hard constraint.
- **Related Fail Mode**: uncertain.

## 4. Cross-cutting Patterns

### 4.1 Three contract waves use the same Stage 2 LLM call

OASCContract → ClarificationContract (legacy) and IntentResolutionContract +
ExecutionReadinessContract (split) all rely on the same `_run_stage2_llm[_with_telemetry]`
prompt that returns `slots`, `intent`, `stance`, `chain` in one JSON. This
means:

- A single LLM error cascades into intent + stance + slot decisions
  simultaneously.
- The split contracts cannot independently retry one axis; they must replay
  the whole prompt.
- Telemetry separation (intent vs. stance vs. slot) is post-hoc parsing.

### 4.2 Two parallel intent-detection paths

- §3.3.8 `_detect_confirm_first` — substring/regex on user text,
  governance-side, returns `confirm_first_signal` with no LLM input.
- §3.3.3 Stage 2 LLM — returns `stance.value=deliberative` and
  `intent.intent_confidence`.

These run on the same input but via different mechanisms, and the
governance-side detection unconditionally flips `collection_mode=True` even
if the LLM disagreed.

### 4.3 Snapshot pipeline coupling

ClarificationContract (or ExecutionReadinessContract) populates a snapshot →
GovernedRouter `_maybe_execute_from_snapshot` reads the snapshot →
`_snapshot_to_tool_args` converts it per tool. A snapshot field decided in
Stage 1 regex with confidence=1.0 becomes a tool argument with no further
LLM review. Three-decision-point chain: §3.3.2 → §3.3.10 → §3.1.2.

### 4.4 Clarification short-circuit set produces hardcoded user-visible text

§3.3.9 (default fallback question), §3.4.2 (intent clarification), §3.4.7
(exploratory framing), §3.7.1 (constraint violation message in Chinese) all
produce hardcoded `text=`. The reply parser (§3.6.1) can rewrite these
into more natural Chinese, but the *content* is governance-prescribed.

### 4.5 Reversal/abandon detection is substring-based and centralized in `core/continuation_signals.py`

`has_reversal_marker`, `has_probe_abandon_marker`,
`StanceResolver.detect_reversal`, and `_detect_revision_target` are four
independent substring matchers on overlapping marker lists ("等等", "重新",
"换成", "改成", "再想想", …). They feed §3.4.1 (continuation short-circuit
override), §3.4.3 (stance reversal), §3.4.6/§3.4.8 (probe abandon),
§3.2.2 (revision target detection).

### 4.6 Probe-limit duplicated in two places with the same constant

§3.3.6 hardcodes `probe_turn_count >= 2` to abandon the probe;
§3.4.6/§3.4.8 hardcode `probe_count >= probe_limit` with `probe_limit`
defaulting to 2. Same domain decision in two places.

### 4.7 Three governance-LLM decision points use slightly different LLM clients/prompts

- `OAScopeClassifier` Layer-2 — own system prompt
  (`AO_CLASSIFIER_SYSTEM_PROMPT`), threshold 0.7.
- `_run_stage2_llm[_with_telemetry]` — different system prompt (legacy vs.
  split-mode compact variant).
- `LLMReplyParser` — own system prompt (final reply rewriter).

Three separate prompt surfaces, three separate timeout configs
(`ao_classifier_timeout_sec`, `clarification_llm_timeout_sec`,
`LLMReplyParser.timeout_seconds=20.0`).

## 5. Questions for Human Review

### 5.1 What are the L1–L4 fail modes? (architecture)
- **Decision points**: every §3 entry that touches turn-classification,
  optional-probe, evaluation isolation, or stage data flow.
- **Question nature**: missing context. The prompt references
  "L1 evaluation isolation / L2 turn classification / L3 optional probe /
  L4 stage data flow" and asks to cross-reference fail task IDs, but the
  codebase contains no L1/L2/L3/L4 mapping under any obvious name. My
  cross-references in §3 are best-guess based on the labels.
- **My initial view**: I have reasonable confidence on which sites *are*
  load-bearing for each axis (turn classification = §3.2; optional probe =
  §3.3.6/§3.4.6/§3.4.8; stage data flow = the snapshot pipeline §3.3 +
  §3.4 → §3.1.2). What I cannot do is map specific failing benchmark task
  IDs to sites.
- **Resolution path**: human reviewer to share the L1–L4 fail task list so
  the §3 entries can be properly back-cited.

### 5.2 Should turn classification (NEW_AO/CONTINUATION/REVISION) be governance-owned at all? (architecture)
- **Decision points**: §3.2.1, §3.2.2, §3.2.3, §3.2.4.
- **Question nature**: architectural. Per the prompt's category-3 definition,
  turn type classification is "Pure Semantic — LLM should lead, governance
  should not intervene". Today the implementation has Layer-1 rules with
  confidence 0.9–1.0 returning before LLM is consulted, plus a 0.7
  confidence floor on Layer-2 LLM verdicts.
- **My initial view**: at minimum, the rule layer's
  `_is_short_clarification_reply` and `_detect_revision_target` short-circuits
  look like substituting governance for the LLM on a semantic axis.
- **Uncertain part**: the rule layer is also doing latency/cost control. A
  rules-first path has obvious benefits when the LLM is paid-per-call. The
  trade-off is real and not purely architectural.

### 5.3 Is `_detect_confirm_first` redundant with Stage 2 LLM stance? (implementation detail)
- **Decision points**: §3.3.8, §3.3.3.
- **Question nature**: implementation. Two parallel signals decide the same
  thing (does the user want to confirm first?) and use different mechanisms
  (regex vs. LLM). They can disagree silently.
- **My initial view**: drop the regex path or make it advisory only — but
  this would change benchmark behavior, which needs separate evidence.

### 5.4 Is one-LLM-call-decides-three-axes (slots/intent/stance) the right boundary? (architecture)
- **Decision points**: §3.3.3, §3.4.1, §3.4.4 (saturated-slot stance fallback).
- **Question nature**: architectural. Currently the same Stage 2 prompt
  returns `slots`, `intent`, and `stance`. The split contracts then post-
  process the same response into separate decisions.
- **My initial view**: the coupling is what enables the cheap "one LLM call
  per turn" budget but causes correlated failure modes (L1 evaluation
  isolation). Splitting would be expensive.

### 5.5 Why are clarification short-circuit texts hardcoded? (implementation detail)
- **Decision points**: §3.3.9 fallback questions, §3.4.2 intent clarification,
  §3.4.7 exploratory framing, §3.1 cross-constraint message in §3.7.1.
- **Question nature**: implementation. The reply parser (§3.6.1) is supposed
  to rewrite outputs, but these short-circuits return *with* `proceed=False`,
  meaning the reply parser still runs on the hardcoded text. Yet it might
  have already been domain-perfect, or it might lose information.
- **My initial view**: the reply parser does process these (it consumes
  `router_text`), so they get rewritten. But the *content* is
  governance-determined. needs human review on whether the LLM's rewrite is
  preserving information.

### 5.6 Probe limit is hardcoded `2` in two places (implementation detail)
- **Decision points**: §3.3.6, §3.4.6/§3.4.8.
- **Question nature**: implementation. `probe_turn_count >= 2` and
  `probe_limit=2` magic numbers should at minimum live in one place.
- **My initial view**: trivial fix — externalize to runtime_config. Not
  blocking.

### 5.7 Capability summary's "硬约束" framing — does it cause LLM compliance over-correction? (architecture)
- **Decision points**: §3.7.3.
- **Question nature**: architectural. The synthesis prompt explicitly labels
  capability summary as "后续建议硬约束" (hard constraints for follow-up
  suggestions). This is governance prescribing the LLM's *language*, not just
  blocking actions.
- **My initial view**: the strong wording is probably necessary to prevent
  the LLM from suggesting `render_spatial_map` when no geometry exists.
  Whether it overshoots into discouraging legitimate suggestions needs
  benchmark evidence.

### 5.8 Substring-based reversal/abandon markers (implementation + domain)
- **Decision points**: §3.4.3 (`detect_reversal`), §3.4.6/§3.4.8
  (`has_probe_abandon_marker`), §3.2.2 (`_detect_revision_target`),
  §3.3.8 (confirm_first patterns).
- **Question nature**: domain knowledge + implementation. Marker lists
  contain ambiguous tokens — `重新` ("re-do") appears in
  `重新查询` (continuation) and `重新计算` (revision) and `算了还是重新`
  (reversal). Pure substring matching cannot tell these apart.
- **My initial view**: should be replaced by LLM Stage 2's stance/intent
  output where they overlap, or moved into `unified_mappings.yaml` so
  domain experts can curate them, but **uncertain** — these matchers are
  the cheap pre-LLM gate that controls cost.

### 5.9 Snapshot direct execution (`_maybe_execute_from_snapshot`) is the most opaque governance override (architecture)
- **Decision points**: §3.1.2.
- **Question nature**: architectural. When ClarificationContract decides
  `direct_execution`, the LLM never sees the turn at all — governance
  selects tool, fills arguments, calls executor, and constructs the response.
- **My initial view**: this is a major efficiency win when the contract is
  confident, but it is the cleanest possible counterexample to the
  AI-First Architecture claim in `README.md` ("Trust LLM intelligence,
  minimal rules"). The contract is making the entire turn decision.

### 5.10 OASCContract.before_turn always builds a fresh state snapshot (implementation detail)
- **Decision points**: §3.2.1 (state_snapshot construction).
- **Question nature**: implementation. Each turn creates a new TaskState
  from scratch, then re-attaches active_input_completion,
  active_parameter_negotiation, and continuation. If any of these loaders
  has a side-effect or differs from what the inner router computes later,
  classification will see a different state than the inner router uses.
- **My initial view**: there's a coupling risk between the contract's view
  of state and the inner router's view. needs human review on whether this
  has caused divergence.

## 6. Summary Statistics

- **Total decision points enumerated**: 40
  - GovernedRouter shell (§3.1): 4
  - OASC + AO classifier (§3.2): 5
  - Legacy ClarificationContract (§3.3): 10
  - Wave-2 split contracts (§3.4): 9
  - AOManager lifecycle (§3.5): 3
  - Reply pipeline (§3.6): 3
  - Inner-router governance hooks (§3.7): 3
  - (§3.5 has 3, §3.6 has 3, §3.7 has 3 — totals add to 40.)
- **By T5.2 classification**:
  - Hard Constraint: 18
    (§3.1.1, §3.1.2, §3.1.3, §3.1.4, §3.2.4, §3.2.5, §3.3.1, §3.3.4 (legal-value half), §3.3.9, §3.3.10, §3.4.1, §3.4.5, §3.5.1, §3.5.2, §3.5.3, §3.6.3, §3.7.1, §3.7.3)
  - Soft Guidance: 9
    (§3.3.2, §3.3.4 (defaults half), §3.3.5, §3.3.6, §3.4.6, §3.4.8, §3.4.9, §3.6.2, §3.7.2)
  - Pure Semantic: 11
    (§3.2.1, §3.2.2, §3.2.3, §3.3.3, §3.3.7, §3.3.8, §3.4.2, §3.4.3, §3.4.4, §3.4.7, §3.6.1)
  - uncertain: 2 (§3.3.2 alignment is uncertain; §3.3.5 alignment is uncertain — they were classified but flagged in §5)
  - (Decision points marked Hard+Soft hybrid in body counted under Hard above.)
- **MISALIGNED count**: 14
  (§3.1.2 uncertain-MISALIGNED, §3.2.1, §3.2.2, §3.2.3 (LLM gate), §3.3.3 (one-call-three-axes), §3.3.4 (inferred-confidence threshold), §3.3.6 (magic constant), §3.3.8, §3.4.1, §3.4.2, §3.4.3, §3.4.4, §3.4.5, §3.4.7)
- **Decision points related to fail-mode buckets** (uncertain mapping; see §5.1):
  - L1 evaluation isolation: 3 (§3.3.3, §3.3.8, §3.4.4) + §3.6.1 indirect
  - L2 turn classification: 8 (§3.1.1 cascade, §3.2.1, §3.2.2, §3.2.3,
    §3.3.8, §3.4.1, §3.4.2, §3.4.3)
  - L3 optional probe: 6 (§3.3.5, §3.3.6, §3.3.7, §3.4.6, §3.4.8, §3.4.9)
  - L4 stage data flow: 9 (§3.1.2, §3.1.3, §3.2.5, §3.3.2, §3.3.4, §3.3.9,
    §3.3.10, §3.4.5, §3.6.2, §3.6.3 — actually 10 if §3.6.3 is L4-relevant)
  - none / domain-correct: 3 (§3.1.4, §3.5.2, §3.7.1)
  - uncertain: remainder

> All L1–L4 cross-references are best-guess against the labels in the
> prompt. Section 5.1 explains why.
