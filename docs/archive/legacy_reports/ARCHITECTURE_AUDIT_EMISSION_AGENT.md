# Architecture Audit: EmissionAgent Codebase
**Date:** 2026-03-29
**Auditor:** Claude Sonnet 4.6 (code-grounded analysis)
**Scope:** Full repository, primary working directory `/home/kirito/Agent1/emission_agent/`
**Method:** Direct file reads of all key modules; all claims cite specific files, classes, functions, or code excerpts.

---

## 1. Executive Verdict

**The system is no longer a collection of ad hoc rules and tool calls. It has crossed a meaningful architectural threshold into a structured agent framework — but it is incomplete, unevenly implemented, and partially undermined by a 439 KB monolithic router that houses governance logic that should be independent.**

Specifically:

- The **state machine is real**: 7 explicitly defined `TaskStage` states, validated transition maps, and a loop guard in `_run_state_loop()` (`core/router.py:892`). The transitions are not implicit control flow — they are enforced via `TaskState.transition()` which raises `ValueError` on illegal moves (`core/task_state.py:400–407`).

- The **dependency graph is real**: `TOOL_GRAPH` in `core/tool_dependencies.py:30–67` is a declarative requires/provides registry. `validate_tool_prerequisites()` and `validate_plan_steps()` deterministically block illegal tool sequencing before execution.

- The **standardization layer is real**: `services/standardizer.py` and `services/standardization_engine.py` sit in front of every tool call, with a config-driven catalog loaded from `config/unified_mappings.yaml`. LLM parameters are standardized deterministically before reaching tools.

- The **trace layer is real**: `core/trace.py` defines ~100 `TraceStepType` enum values and records structured decision steps across the entire state loop. Every transition produces an audit record.

- But the **router (`core/router.py`) is 439 KB** — approximately 10,000+ lines — and it embeds governance sub-policies (file relationship cue detection, continuation keyword matching, output safety pattern lists, direct state mutation logic) that should be independent from the routing loop. This is the most significant architectural defect.

- A **dual execution path** still exists: `_run_legacy_loop()` and `_run_state_loop()`, gated by a config flag `enable_state_orchestration`. The new architecture is not yet the unconditional default.

- **Workflow templates are hardcoded Python objects**, not loaded from external configuration, which limits extensibility without code changes.

**One-sentence maturity judgment:** EmissionAgent has built a credible constraint-governed agent framework with explicit state machines, declarative dependency validation, and config-driven parameter standardization — but the governance machinery is architecturally entangled inside a massive router class that prevents clean separation of concerns and limits both extensibility and paper-level conceptual clarity.

---

## 2. Evidence-Based Architecture Summary

### Module Inventory

| Module | Role | Maturity |
|---|---|---|
| `core/task_state.py` | TaskState + TaskStage enum + validated transitions | Framework-grade |
| `core/tool_dependencies.py` | TOOL_GRAPH + prerequisite validation | Framework-grade |
| `core/parameter_negotiation.py` | Structured ambiguity handling | Framework-grade |
| `core/plan.py` | ExecutionPlan + PlanStep + PlanStatus | Framework-grade |
| `core/workflow_templates.py` | Pre-defined workflow skeletons | Framework-grade (but hardcoded) |
| `core/readiness.py` | Pre-execution gating + ActionAffordance | Framework-grade (68 KB) |
| `core/remediation_policy.py` | Policy-based missing field filling | Framework-grade |
| `core/trace.py` | Auditable decision trace | Framework-grade |
| `services/standardizer.py` | Config-driven parameter normalization | Framework-grade |
| `services/standardization_engine.py` | Multi-tier standardization coordinator | Framework-grade |
| `config/unified_mappings.yaml` | Vehicle/pollutant/season/road ontology | Config-layer present |
| `tools/base.py` | BaseTool ABC + ToolResult | Framework-grade |
| `tools/registry.py` | ToolRegistry singleton | Adequate |
| `tools/definitions.py` | Static JSON tool schemas | Patch-level (manual sync required) |
| `core/router.py` | State loop + all governance orchestration | Architecturally entangled |
| `core/output_safety.py` | Response safety rail | Ad hoc (string pattern list) |
| `core/intent_resolution.py` | LLM-driven deliverable intent classification | Framework-grade (bounded) |
| `core/artifact_memory.py` | Delivered artifact tracking | Framework-grade |
| `core/file_relationship_resolution.py` | New file vs. current workflow resolution | Framework-grade |
| `core/plan_repair.py` | Residual workflow repair | Framework-grade |
| `core/geometry_recovery.py` | Spatial data recovery | Specialized |

### Representative End-to-End Flow: File Upload → Grounding → Macro Emission Calculation

```
1. user_message + file_path arrive at UnifiedRouter.chat()
2. router._run_state_loop() creates TaskState (stage=INPUT_RECEIVED)
3. _state_handle_input():
   a. Checks _should_resolve_file_relationship() - keyword+context heuristic
   b. If file relationship detected: calls LLM with FILE_RELATIONSHIP_RESOLUTION_PROMPT
      → bounded output parsed into FileRelationshipDecision (typed enum)
   c. If active_input_completion: handles pending completion
   d. If active_parameter_negotiation: handles pending confirmation
   e. Calls ToolExecutor to run analyze_file tool
   f. FileAnalyzerTool returns: task_type, column_mapping, micro/macro_has_required
   g. If confidence < threshold: _state_handle_llm_fallback() with bounded prompt
   h. state.update_file_context(analysis) → state.file_context.grounded = True
   i. state.transition(GROUNDED)
4. _state_handle_grounded():
   a. Calls ReadinessAssessment.build_readiness_assessment()
   b. If REPAIRABLE (missing required fields): build InputCompletionRequest
      → state.transition(NEEDS_INPUT_COMPLETION)
   c. If READY: call LLM with PLANNING_PROMPT + workflow_template_prior
      → parse ExecutionPlan from JSON response
      → validate_plan_steps() checks dependency chain
      → state.transition(EXECUTING)
5. _state_handle_executing():
   a. LLM selects next tool (guided by plan context in system prompt)
   b. ReadinessAssessment gates the tool call
   c. router._prepare_tool_arguments() injects _last_result from SessionContextStore
   d. StandardizationEngine.standardize_parameters() runs before tool.execute()
   e. ToolExecutor calls MacroEmissionTool.execute()
   f. Result stored in SessionContextStore + memory
   g. plan step marked COMPLETED
   h. If more steps: loop, else state.transition(DONE)
6. _state_build_response(): synthesis prompt → RouterResponse
```

---

## 3. Where Rules Exist and What Kind of Rules They Are

### 3.1 Task Classification Rules

**Location:** `tools/file_analyzer.py` (rule-based analysis) + `core/file_analysis_fallback.py` (LLM fallback)

**Classification:** **Partially architectural mechanism, partially ad hoc.**

The file analyzer performs column matching and task-type inference using the `unified_mappings.yaml` column pattern catalog. When confidence is low, `should_use_llm_fallback()` triggers an LLM pass with `FILE_ANALYSIS_FALLBACK_PROMPT` (router.py:222–235), which constrains the LLM output to `{"macro_emission", "micro_emission", "unknown"}` and uses only pre-defined canonical field names. This is a bounded fallback — the output is parsed deterministically (`parse_llm_file_analysis_result()`). The constraint is real, but the architecture requires an LLM call on the grounding path, which is a fragility point.

**Evidence:** `core/file_analysis_fallback.py::should_use_llm_fallback()`, `core/router.py::FILE_ANALYSIS_FALLBACK_PROMPT` (line 222)

### 3.2 File Schema / Column Inference Rules

**Location:** `config/unified_mappings.yaml` (column patterns), `services/standardizer.py::_build_lookup_tables()`, `services/standardization_engine.py`

**Classification:** **Explicit architecture mechanism.**

Column name mappings are fully externalized to `config/unified_mappings.yaml`. The `UnifiedStandardizer` loads these at startup and builds lookup tables. The `StandardizationEngine` chains rule-based lookup → fuzzy match → LLM fallback, with confidence scores tracked per parameter (`strategy` field: `exact / alias / fuzzy / abstain`).

```yaml
# config/unified_mappings.yaml (excerpt)
vehicle_types:
  - id: 21
    standard_name: "Passenger Car"
    display_name_zh: "乘用车"
    aliases: ["小汽车", "轿车", "SUV", "出租车", ...]
    vsp_params: {A: 0.156461, B: 0.002001, C: 0.000492, M: 1.4788}
```

VSP parameters are also externalized here, making them auditable and paper-citable. This is correct framework design.

### 3.3 Parameter Normalization Rules

**Location:** `services/standardizer.py`, `services/standardization_engine.py`, `core/parameter_negotiation.py`

**Classification:** **Explicit architecture mechanism.**

`StandardizationResult` (`services/standardizer.py:33`) is a typed dataclass: `{success, original, normalized, strategy, confidence, suggestions}`. Every parameter standardization produces this. When `strategy == "fuzzy"` and `confidence < threshold`, `ParameterNegotiationRequest` is created — a typed negotiation object with candidates, triggering `state.transition(NEEDS_PARAMETER_CONFIRMATION)`.

```python
# core/parameter_negotiation.py
class NegotiationDecisionType(str, Enum):
    CONFIRMED = "confirmed"
    NONE_OF_ABOVE = "none_of_above"
    AMBIGUOUS_REPLY = "ambiguous_reply"
```

The reply parsing (`parse_parameter_negotiation_reply()`) is entirely deterministic: index matching, exact match, partial match, Chinese character index map. No LLM involved.

### 3.4 Tool Dependency / Readiness Rules

**Location:** `core/tool_dependencies.py::TOOL_GRAPH`, `core/readiness.py`

**Classification:** **Explicit architecture mechanism.**

```python
# core/tool_dependencies.py:30–67
TOOL_GRAPH: Dict[str, Dict[str, List[str]]] = {
    "calculate_dispersion": {"requires": ["emission"], "provides": ["dispersion"]},
    "analyze_hotspots":     {"requires": ["dispersion"], "provides": ["hotspot"]},
    ...
}
```

`validate_tool_prerequisites()` is called before execution. It checks `SessionContextStore.get_result_availability()` against required tokens. `validate_plan_steps()` runs the full plan through the dependency graph, marking steps as READY, BLOCKED, or FAILED.

`ReadinessAssessment` in `core/readiness.py` (`build_readiness_assessment()`) produces typed `ActionAffordance` objects with `ReadinessStatus` (READY / BLOCKED / REPAIRABLE / ALREADY_PROVIDED). The router calls `build_action_blocked_response()` or `build_action_repairable_response()` based on the status — these are structured responses, not ad hoc messages.

**Evidence:** `core/tool_dependencies.py:159–242`, `core/readiness.py` (68 KB, reviewed via persisted output)

### 3.5 Workflow Gating Rules (State Transitions)

**Location:** `core/task_state.py::TaskState._valid_transitions()`

**Classification:** **Explicit architecture mechanism.**

```python
# core/task_state.py:409–434
def _valid_transitions(self) -> List[TaskStage]:
    transition_map = {
        TaskStage.INPUT_RECEIVED: [GROUNDED, NEEDS_CLARIFICATION, NEEDS_PARAMETER_CONFIRMATION,
                                    NEEDS_INPUT_COMPLETION, DONE],
        TaskStage.GROUNDED:       [EXECUTING, NEEDS_CLARIFICATION, DONE],
        TaskStage.NEEDS_CLARIFICATION: [],         # terminal
        TaskStage.NEEDS_PARAMETER_CONFIRMATION: [], # terminal
        TaskStage.NEEDS_INPUT_COMPLETION: [],       # terminal
        TaskStage.EXECUTING:      [DONE, NEEDS_CLARIFICATION, NEEDS_PARAMETER_CONFIRMATION,
                                    NEEDS_INPUT_COMPLETION],
        TaskStage.DONE: [],                         # terminal
    }
    return transition_map[self.stage]
```

`state.transition()` raises `ValueError` on illegal transitions. This is validated enforcement.

### 3.6 Remediation Policy Rules

**Location:** `core/remediation_policy.py`

**Classification:** **Explicit architecture mechanism.**

`RemediationPolicy` types: UNIFORM_SCALAR_FILL, UPLOAD_SUPPORTING_FILE, APPLY_DEFAULT_TYPICAL_PROFILE, PAUSE. The `apply_default_typical_profile` policy uses lookup tables explicitly sourced from HCM 6th ed. and OSM wiki — the code comment states: *"All lookup values are fixed, auditable, and paper-citable."* (`remediation_policy.py:18–20`). `check_default_typical_profile_eligibility()` is a deterministic eligibility check, not LLM-driven.

### 3.7 Continuation / Keyword Detection Rules

**Location:** `core/router.py:296–311`

**Classification:** **Ad hoc patch.**

```python
# core/router.py:296–311
CONTINUATION_TOOL_KEYWORDS = {
    "calculate_macro_emission": ["排放", "emission", "宏观"],
    "calculate_micro_emission": ["排放", "emission", "微观", "轨迹"],
    ...
}
```

This is a hardcoded keyword dict embedded as a module-level constant in the 439 KB router. It is used for heuristic detection of continuation intent. It is not config-driven, not parameterized, and not tested in isolation. It should either be part of `intent_resolution.py` or externalized to config.

### 3.8 File Relationship Cue Detection Rules

**Location:** `core/router.py::_message_has_file_relationship_cue()` (line ~1528)

**Classification:** **Ad hoc patch.**

```python
cues = ("发错", "重新上传", "替换", "gis", "shapefile", "geojson", "merge", ...)
```

A hardcoded Chinese/English phrase list embedded in the router. Should be config-driven or part of intent resolution.

### 3.9 Result Delivery / Follow-up Suggestion Rules

**Location:** `core/summary_delivery.py`, `core/artifact_memory.py`, `core/capability_summary.py`

**Classification:** **Explicit architecture mechanism.**

`SummaryDeliveryType` enum, `SummaryDeliveryPlan`, `ArtifactMemoryState` with `latest_by_family` and `latest_by_type` — these form a structured system for tracking what has been delivered and what follow-up is appropriate. `apply_artifact_memory_to_capability_summary()` modifies the capability summary based on delivered artifacts, which biases the LLM toward appropriate suggestions without LLM free-form hallucination.

---

## 4. State Machine and Execution Governance

### 4.1 Explicit State Machine

States defined in `core/task_state.py::TaskStage`:

```
                    ┌────────────────────────────────┐
                    │         INPUT_RECEIVED         │
                    └────┬───────┬───────┬───────────┘
                         │       │       │
              (grounded) │       │ (ambiguous/  │ (missing fields/
                         ▼       │  unknown)    │  param needed)
                    ┌────────┐   │              │
                    │GROUNDED│   ▼              ▼
                    └────┬───┘ ┌─────────────────────────────────┐
             (plan ready)│     │ NEEDS_CLARIFICATION             │ terminal
                         │     ├─────────────────────────────────┤
                         │     │ NEEDS_PARAMETER_CONFIRMATION    │ terminal
                         │     ├─────────────────────────────────┤
                         │     │ NEEDS_INPUT_COMPLETION          │ terminal
                         │     └─────────────────────────────────┘
                         ▼
                    ┌──────────┐
                    │EXECUTING │◄─────────────────────────────────┐
                    └────┬─────┘                                  │
              (completed)│    (missing param / ambiguous input)   │
                         │    → NEEDS_PARAMETER_CONFIRMATION ─────┘
                         ▼        → NEEDS_INPUT_COMPLETION  ─────┘
                    ┌────────┐
                    │  DONE  │  terminal
                    └────────┘
```

**Key properties:**
- `is_terminal()`: `{DONE, NEEDS_CLARIFICATION, NEEDS_PARAMETER_CONFIRMATION, NEEDS_INPUT_COMPLETION}` — correctly identifies paused user-interaction states as terminal for the current turn
- `should_stop()`: terminal OR steps_taken >= max_steps
- Loop guard: `max_state_iterations = max(6, max_steps * 3)` — prevents infinite loops
- `steps_taken` incremented on every `transition()` call

### 4.2 State Distinction for Failure Modes

The system correctly distinguishes:

| Situation | State | Handler |
|---|---|---|
| Ambiguous task type | NEEDS_CLARIFICATION | `_identify_critical_missing()` |
| Ambiguous parameter (low confidence) | NEEDS_PARAMETER_CONFIRMATION | `ParameterNegotiationRequest` |
| Missing required input data | NEEDS_INPUT_COMPLETION | `InputCompletionRequest` |
| Missing dependencies (tool ordering) | Blocked (in plan) | `validate_tool_prerequisites()` |
| Recoverable missing fields | NEEDS_INPUT_COMPLETION (REPAIRABLE) | `RemediationPolicy` offered |
| Plan execution failure | Step → FAILED status, plan repair triggered | `plan_repair.py` |

**Notable gap:** There is no explicit `FAILED` state in `TaskStage`. Execution failures route to `DONE` with an error response, or to `NEEDS_CLARIFICATION`. This means the state machine does not distinguish between "successfully completed" and "terminated with error" — both become `DONE`. For a paper-level framework, this should be a distinct terminal state.

### 4.3 State Transition Implementation

Transitions are executed via `_transition_state()` in the router (`core/router.py:1078`), which calls `state.transition()` and records to the trace:

```python
def _transition_state(self, state, new_stage, reason="", trace_obj=None):
    stage_before = state.stage.value
    state.transition(new_stage, reason=reason)   # raises ValueError if illegal
    if trace_obj:
        trace_obj.record(step_type=TraceStepType.STATE_TRANSITION, ...)
```

Every transition is traced. This is correct.

### 4.4 What Is NOT Explicitly in the State Machine

- The `_state_handle_input()` function is ~500+ lines of orchestration code inside the router. While it enforces state transitions correctly, the *decision logic* for which transition to take is embedded procedurally rather than declared in a policy table or transition guard system. This makes it difficult to reason about transition correctness without reading all 500 lines.

- No explicit "guard functions" per transition — the conditions for transitioning to each state are embedded in the handler method body, not in a separate declarative structure.

---

## 5. Constraint-First Design: Confirmed vs. Not Yet Achieved

### 5.1 Confirmed: LLM Output Does Not Directly Drive Tool Parameters

The executor (`core/executor.py`) calls `StandardizationEngine.standardize_parameters()` before invoking any tool. Raw LLM-supplied strings (vehicle type, pollutant name, season) are intercepted, normalized to canonical values from `unified_mappings.yaml`, and if confidence is insufficient, the execution is halted pending user confirmation.

Evidence:
- `services/standardization_engine.py::StandardizationEngine` — multi-tier standardization before tool execution
- `core/task_state.py::ParamEntry.locked` — confirmed parameters are locked and cannot be overridden by subsequent LLM outputs
- `core/router.py::_prepare_tool_arguments()` (line 545) — applies locked parameter values from `state.parameters` before passing args to tools

### 5.2 Confirmed: Dependency Gating Blocks Illegal Sequences

`validate_tool_prerequisites()` is called before any tool that has requirements in `TOOL_GRAPH`. If `emission` result is not in `SessionContextStore`, `calculate_dispersion` will be blocked with a typed `DependencyValidationResult` (`is_valid=False`, `missing_tokens=["emission"]`). The router converts this to `ActionAffordance(status=BLOCKED)` and returns a structured refusal to the LLM.

### 5.3 Confirmed: Remediation Uses Deterministic Lookup Tables

`apply_default_typical_profile()` in `core/remediation_policy.py` generates `FieldOverride` objects using lookup tables — not LLM inference. The lookup tables cite their sources. Row-level values are resolved by `resolve_traffic_flow_vph()` and `resolve_avg_speed_kph()` (pure functions, fully testable).

### 5.4 Confirmed: Output Has a Safety Rail

`core/output_safety.py::sanitize_response()` intercepts every user-facing response and strips raw spatial data leaking into text (LINESTRING, MULTILINESTRING, POLYGON, matrix patterns). This is a deterministic constraint on synthesis output.

### 5.5 Partial: Intent Resolution Is Bounded but LLM-Driven

`INTENT_RESOLUTION_PROMPT` constrains LLM output to an enum of `deliverable_intent` values (`spatial_map`, `chart_or_ranked_summary`, `downloadable_table`, etc.) and `progress_intent` values (`continue_current_task`, `start_new_task`, etc.). The output is parsed into typed dataclasses (`IntentResolutionDecision`, `IntentResolutionApplicationPlan`). However, the resolution itself is an LLM call on the hot path. If the LLM produces malformed JSON, `infer_intent_resolution_fallback()` provides a deterministic fallback.

This is a reasonable design choice, but it means a governing decision is LLM-dependent rather than deterministic.

### 5.6 Not Yet Achieved: Planning Is LLM-Driven With Post-Hoc Validation

`PLANNING_PROMPT` (router.py:206) asks the LLM to produce an `ExecutionPlan`. The plan is then validated by `validate_plan_steps()`. This is correct — plan is validated after generation. However, the plan itself is not produced by a deterministic planner: it is LLM output constrained only by the prompt and post-hoc validation. A plan with illegal tool names is caught (`PlanStepStatus.FAILED`), but a planner that produces semantically wrong steps (wrong tool order that still passes dependency checks) may not be caught.

### 5.7 Not Yet Achieved: Workflow Template Selection Is Also Partially LLM-Dependent

`recommend_workflow_templates()` in `core/workflow_templates.py` applies rule-based signal matching (task type, spatial readiness, intent signals). The output is a ranked list of `TemplateRecommendation`. However, the LLM planner still has freedom to deviate from the recommended template. The template is a "prior" (`PLANNING_PROMPT: 210`), not an enforced constraint.

---

## 6. Extensibility Assessment

### 6.1 Adding a New Tool

**Difficulty: Medium-high. Extension path: partly patch-driven.**

Requires four manually synchronized changes:
1. `tools/definitions.py` — add JSON schema (static dict, not auto-generated)
2. `tools/registry.py::init_tools()` — add import + `register_tool()` call
3. `core/tool_dependencies.py::TOOL_GRAPH` — declare requires/provides tokens
4. Implement `tools/newtool.py` extending `BaseTool`

There is no single tool specification file that drives all four. The `TOOL_GRAPH` is separate from `tools/definitions.py`, which is separate from `tools/registry.py`. If any of the three are out of sync, behavior is undefined (e.g., a tool missing from `TOOL_GRAPH` will have no dependency checking).

**Verdict:** Not disciplined extensibility — it is parallel-modification extensibility. A schema-driven approach would generate `definitions.py` entries and `TOOL_GRAPH` entries from a single tool descriptor.

### 6.2 Adding a New Parameter Family or Ontology

**Difficulty: Low (the best-designed extension path in the codebase).**

Add entries to `config/unified_mappings.yaml`. `UnifiedStandardizer._build_lookup_tables()` reads from the YAML at startup and builds in-memory lookup tables. No code changes required for purely additive ontology changes (new vehicle type aliases, new pollutant, new season). The `StandardizationEngine._load_catalog()` also reads from the same YAML.

**Caveat:** Adding a completely new parameter *family* (e.g., "fuel type") would require adding a new standardization method to `StandardizationEngine` and a new `ParamEntry` key. The config handles new values within existing families cleanly, but new families still require code changes.

### 6.3 Adding a New Input File Pattern

**Difficulty: Medium. Extension path: code-driven.**

`tools/file_analyzer.py` contains the rule-based grounding logic. The column pattern catalog comes from `unified_mappings.yaml::column_patterns`, which is good. But `FileAnalyzerTool` currently supports CSV, Excel, and ZIP/GeoPackage/Shapefile patterns. Adding a new format (e.g., Parquet, HDF5) requires code changes to `file_analyzer.py` regardless of config changes.

Additionally, the `file_analysis_fallback.py` LLM fallback only knows about `macro_emission` and `micro_emission` task types. Adding a new task type (e.g., intersection-level analysis) would require updating the fallback prompt, the `TaskStage` logic, workflow templates, and tool definitions simultaneously.

### 6.4 Router Logic Changes Per New Capability

**Difficulty: Moderate for simple additions; high for new interaction patterns.**

The router (`core/router.py`) dispatches to specific handlers based on `state.stage`. Adding a tool that fits existing patterns (emit result → render map → done) requires no router changes. Adding a new interaction pattern (e.g., a new form of "pending user input" beyond the current three NEEDS_* states) would require:
- Adding a new `TaskStage` variant
- Adding a new handler method in the router
- Adding a new "live bundle" dict to maintain cross-turn state
- Adding trace step types

This is not catastrophically hard, but the pattern of "add a new 500-line handler method to the 439 KB router" is not a disciplined extension path.

### 6.5 Workflow Template Changes

**Difficulty: Medium. Extension path: code-driven (should be config-driven).**

`_build_template_catalog()` in `core/workflow_templates.py` returns a hardcoded dict of `WorkflowTemplate` objects. There is no YAML or JSON loading here — despite all the infrastructure for `from_dict()` serialization. Adding a new template requires editing Python code and redeploying. This is a missed opportunity: the `WorkflowTemplate.from_dict()` method exists, suggesting templates were intended to be loaded from config.

---

## 7. Gap Analysis Against the Ideal Agent Architecture

### Layer 1: Semantic Layer (LLM for Intent and Ambiguity)

**Status: Present.**

LLM is used for: intent resolution (bounded enum output), planning (validated JSON plan), file relationship classification (bounded enum output), file analysis fallback (bounded task type output), synthesis (final natural language). All LLM interactions are bounded by structured prompts with explicit allowed output values. Fallback functions exist for each LLM-driven decision. This layer is architecturally sound.

**Weakness:** The planning LLM call is unbounded within the allowed tool space — it can produce syntactically valid but semantically suboptimal plans.

### Layer 2: Grounding Layer (File + Language → Structured Task Representation)

**Status: Present but fragile.**

File analysis produces `FileContext` with `task_type`, `column_mapping`, `micro/macro_has_required`, `missing_field_diagnostics`, `spatial_metadata`. This is a proper structured task representation. The `update_file_context()` method on `TaskState` accepts typed dict input.

**Fragility:** Grounding confidence is a float, and the threshold for triggering LLM fallback is not explicitly declared as a named constant — it is embedded in `should_use_llm_fallback()`. Multi-file (ZIP) grounding and supplemental merge are complex enough that the grounding layer has become partially procedural (5+ router methods dedicated to file relationship handling).

### Layer 3: Governance Layer (Standardization, Negotiation, Dependency Checking, Gating, State Transitions)

**Status: Present for most sub-concerns; FRAGILE due to router entanglement.**

Standardization (config-driven, multi-tier) — present.
Parameter negotiation (typed, deterministic reply parsing) — present.
Dependency checking (`TOOL_GRAPH`, deterministic) — present.
Readiness gating (`ReadinessAssessment`, typed affordances) — present.
State transitions (validated transition map) — present.
Remediation policy (enum types, lookup tables) — present.

**Fragility:** Most of this governance machinery is invoked from within `_state_handle_input()`, `_state_handle_grounded()`, and `_state_handle_executing()` — three 200–500 line methods inside `core/router.py`. The governance layer is not a separate class or subsystem. It is embedded governance. A reader cannot understand the governance policy without reading the full router. A test of the governance policy cannot be isolated from the router.

### Layer 4: Capability Layer (Tools With Explicit Contracts)

**Status: Partially present.**

`BaseTool` ABC with `execute()` and `preflight_check()` is correct. `ToolResult` is a standardized return type. The `TOOL_GRAPH` declares requires/provides at the router layer.

**Partial:** Tools do not declare their own preconditions in code — the `TOOL_GRAPH` is a separate module that must be maintained in sync with the tool implementations. `preflight_check()` in `BaseTool` defaults to `is_ready=True` and is rarely overridden. There is no machine-readable tool contract that bundles: parameter schema + preconditions + postconditions + TOOL_GRAPH entry.

### Layer 5: Config / Resource Layer (Mappings, Domain Vocabularies, Templates, Knowledge)

**Status: Partially present.**

Present:
- `config/unified_mappings.yaml` — vehicle types, pollutants, seasons, road types, meteorology presets, VSP parameters
- `config/meteorology_presets.yaml` — meteorology profiles
- `config/skills/*.yaml` — skill descriptions injected into prompts
- `config/prompts/core_v3.yaml` — core prompt template

Missing from config (hardcoded in Python):
- `core/workflow_templates.py` — 5 workflow templates
- `core/router.py::CONTINUATION_TOOL_KEYWORDS` — continuation keyword dict
- `core/router.py::_message_has_file_relationship_cue()` — phrase list
- `core/output_safety.py::DANGEROUS_PATTERNS` — output safety patterns
- `core/readiness.py::_GEOMETRY_COLUMN_TOKENS` — geometry column name tokens
- `core/remediation_policy.py` — lookup tables (well-structured Python, but not externalized)

### Layer 6: Trace / Recovery Layer

**Status: Present.**

`core/trace.py` defines `Trace` with ~100 `TraceStepType` values. Every state transition, every tool execution, every governance decision (readiness, repair, negotiation) produces a trace record. The trace is attached to `RouterResponse` and includes `trace_friendly` (human-readable) and full dict form.

`core/plan_repair.py` — `PlanRepairDecision` with `RepairActionType` enum (7 allowed repair actions). Repair decisions are validated by `validate_plan_repair()` before application.

`core/residual_reentry.py` — recovers cross-session workflow context.

**Weakness:** Recovery from hard failures (exception in tool execution) is ad hoc — the tool catches exceptions and returns `ToolResult(success=False, ...)`. There is no formal retry policy or fault classification at the tool level. The router does not distinguish between "tool returned error" and "tool raised exception" in a systematically classified way.

### Layer 7: Constrained Synthesis Layer

**Status: Partially present.**

`SYNTHESIS_PROMPT` in `core/router.py:192` explicitly constrains the LLM: "Use only actual data returned by tools, do not fabricate or infer values." `core/output_safety.py::sanitize_response()` strips raw data leaks. `detect_hallucination_keywords()` in `core/router_synthesis_utils.py` provides a simple keyword-based hallucination detector.

**Weakness:** The synthesis constraint is a prompt instruction + keyword check. There is no formal grounding verification that numerical claims in the synthesis text match the tool result data. The hallucination detector is a simple string match, not a semantic consistency check.

---

## 8. Top Architectural Risks

### Risk 1: The 439 KB Router is a Maintenance and Correctness Liability (CRITICAL)

`core/router.py` is approximately 10,000+ lines. It contains: state machine orchestration, file relationship resolution, supplemental merge handling, parameter negotiation handling, input completion handling, intent resolution application, artifact memory management, residual plan restoration, continuation bundle management, synthesis, memory updates, and trace recording — all entangled in one class.

**Consequence:** Any governance policy change requires navigating thousands of lines. Bugs in one subsystem can affect adjacent subsystems. Tests that exercise individual governance decisions must instantiate the full router. The paper-level conceptual separation (semantic / grounding / governance / capability / synthesis) is invisible from the code structure.

### Risk 2: Dual Execution Paths Undermine Framework Claims (HIGH)

`_run_legacy_loop()` and `_run_state_loop()` coexist, gated by `config.enable_state_orchestration`. The legacy loop does not use `TaskState`, `TOOL_GRAPH` validation, `ReadinessAssessment`, or `ParameterNegotiationRequest`. A deployment running the legacy loop has none of the framework properties described in sections 4–5.

**Consequence:** Any benchmark, paper claim, or reproducibility test must specify which loop was active. The framework properties are conditional on a config flag.

### Risk 3: Workflow Templates Are Not Config-Driven (MEDIUM)

Five templates are hardcoded in `_build_template_catalog()` in Python. Despite `WorkflowTemplate.from_dict()` existing, there is no YAML loader. Domain experts cannot modify workflow templates without code changes.

### Risk 4: Tool Specification Is Fragmented Across Three Files (MEDIUM)

A tool's complete specification requires reading `tools/definitions.py` (LLM schema), `core/tool_dependencies.py::TOOL_GRAPH` (dependency graph), and the tool implementation class itself. These are not unified. Inconsistencies between them are possible and not caught at startup.

### Risk 5: No Explicit FAILED State in the Task State Machine (LOW-MEDIUM)

`DONE` absorbs both success and failure. This means the state machine cannot be used to distinguish "execution completed normally" from "execution terminated with unrecoverable error." This weakens the claim that the state machine is a complete execution governance model.

### Risk 6: File Grounding LLM Fallback Is On the Correctness-Critical Path (LOW-MEDIUM)

The file analysis fallback uses an LLM call to determine `task_type` when rule-based confidence is low. This is the single most consequential decision in the system — if task_type is wrong, all downstream tool selection, column mapping, and readiness assessment will be wrong. An LLM fallback on this critical path is a fragility that a production framework should minimize.

### Risk 7: Cross-Turn State Stored in Ad Hoc Dicts (LOW)

`_live_continuation_bundle`, `_live_parameter_negotiation`, `_live_input_completion`, `_live_file_relationship`, `_live_intent_resolution` — five separate dict-keyed bundles in the router instance, with `_ensure_*()` guard methods to reinitialize them if missing. This is functional but fragile: the keys are stringly-typed, not type-safe, and each bundle has a different structure that must be manually synchronized.

---

## 9. Top Priority Refactor / Design Actions

These are listed in order of impact on paper-level framework credibility and engineering soundness. They are not feature additions — they are structural refactors that convert confirmed-but-entangled mechanisms into cleanly separable framework layers.

### Priority 1: Extract the Governance Layer from the Router

**What:** Create a `GovernanceEngine` (or `PolicyController`) class that owns:
- State transition decision logic (currently in `_state_handle_input`, `_state_handle_grounded`, `_state_handle_executing`)
- Readiness evaluation invocation
- Parameter negotiation triggering
- Input completion triggering
- Plan repair triggering

The `UnifiedRouter` should become a thin orchestration shell that calls `GovernanceEngine.evaluate(state)` and acts on the returned `GovernanceDecision`. This makes the governance layer independently testable, readable, and publishable.

**Impact:** Reduces router to ~1,000 lines. Makes governance independently testable. Creates the conceptual clarity needed for a framework paper.

### Priority 2: Commit to the State Loop as the Unconditional Default

**What:** Remove `_run_legacy_loop()` or move it behind a clearly deprecated flag. The new state machine is the architecture — running the old loop silently undermines all framework claims.

**Impact:** Eliminates split-brain architecture. All benchmarks and paper claims can refer to a single, well-defined execution path.

### Priority 3: Externalize Workflow Templates to Configuration

**What:** Load `WorkflowTemplate` objects from `config/workflows/*.yaml` using the existing `WorkflowTemplate.from_dict()` method. The Python catalog becomes a YAML loader with a validation step.

**Impact:** Domain experts can add/modify workflows without code changes. This directly supports the "config/resource layer" paper claim.

### Priority 4: Unify the Tool Specification

**What:** Create a single `tool_specs/` directory where each tool has a YAML file declaring: LLM schema (currently in `definitions.py`), dependency tokens (currently in `TOOL_GRAPH`), and a reference to the implementation class. Generate `definitions.py` and `TOOL_GRAPH` entries from this specification at startup or build time.

**Impact:** Adding a tool becomes a single-file operation. Eliminates fragmentation risk.

### Priority 5: Add an Explicit FAILED State to the Task State Machine

**What:** Add `TaskStage.FAILED` as a terminal state. Route unrecoverable errors from `EXECUTING` to `FAILED` rather than `DONE`. Allow the synthesis step to inspect `state.stage == FAILED` and generate appropriate error responses.

**Impact:** State machine becomes a complete execution model. Enables formal reasoning about failure modes.

### Priority 6: Extract Hardcoded Rule Lists to Configuration

**What:** Move `CONTINUATION_TOOL_KEYWORDS`, `_message_has_file_relationship_cue()` phrase list, `DANGEROUS_PATTERNS`, and `_GEOMETRY_COLUMN_TOKENS` to `config/unified_mappings.yaml` or dedicated config files. These are domain knowledge, not code.

**Impact:** Removes the last remaining patch-level rules from the implementation. Makes the config layer complete.

### Priority 7: Formalize Tool Preconditions in Tool Implementations

**What:** Override `preflight_check()` in each tool to perform its own readiness check (not just `is_ready=True`). The TOOL_GRAPH dependency check should be a system-level layer, while `preflight_check()` should be the tool-level contract check (e.g., "is a valid emission result in context?"). This makes tool contracts self-documenting.

**Impact:** Makes the capability layer self-contained. Reduces reliance on the router for tool-level readiness logic.

---

## 10. Appendix: File-by-File Evidence Table

| File | Size (est.) | Key Evidence | Classification |
|---|---|---|---|
| `core/task_state.py` | ~970 lines | `TaskStage` enum, `_valid_transitions()`, `TaskState` composite, `ParamEntry` with confidence/strategy/lock | Framework-grade state machine |
| `core/tool_dependencies.py` | ~362 lines | `TOOL_GRAPH` dict, `validate_tool_prerequisites()`, `validate_plan_steps()`, `suggest_prerequisite_tool()` | Framework-grade dependency graph |
| `core/parameter_negotiation.py` | ~436 lines | `ParameterNegotiationRequest`, `parse_parameter_negotiation_reply()`, deterministic index/alias/fuzzy matching | Framework-grade mechanism |
| `core/plan.py` | ~232 lines | `ExecutionPlan`, `PlanStep`, `PlanStatus` enum, `PlanStepStatus` enum, `mark_step_status()` | Framework-grade |
| `core/workflow_templates.py` | ~500+ lines | `WorkflowTemplate`, `WorkflowTemplateStep`, `_build_template_catalog()` (hardcoded), `recommend_workflow_templates()` | Framework-grade (but hardcoded catalog) |
| `core/remediation_policy.py` | ~368 lines | `RemediationPolicyType` enum, HCM-sourced lookup tables, `check_default_typical_profile_eligibility()`, row-level resolver functions | Framework-grade policy mechanism |
| `core/trace.py` | ~200+ lines | `TraceStepType` enum (~100 values), `Trace.record()`, structured step output | Framework-grade audit layer |
| `core/readiness.py` | ~68 KB | `ReadinessStatus`, `ActionAffordance`, `build_readiness_assessment()`, `build_action_blocked_response()` | Framework-grade, complex |
| `core/intent_resolution.py` | ~300+ lines | `DeliverableIntentType` + `ProgressIntentType` enums, `INTENT_RESOLUTION_PROMPT` (bounded), `infer_intent_resolution_fallback()` | Framework-grade (LLM-driven, bounded) |
| `core/output_safety.py` | ~48 lines | `DANGEROUS_PATTERNS` list, `sanitize_response()` | Ad hoc (string-based) |
| `core/router.py` | 439 KB | State loop, all governance invocations, `CONTINUATION_TOOL_KEYWORDS`, `_message_has_file_relationship_cue()` | Entangled monolith |
| `tools/base.py` | ~128 lines | `BaseTool` ABC, `ToolResult` dataclass, `preflight_check()` default=True | Framework-grade interface |
| `tools/registry.py` | ~80 lines | `ToolRegistry` singleton, `init_tools()` — manually enumerates 9 tools | Adequate, patch-extensible |
| `tools/definitions.py` | ~403 lines | Static JSON schema list — must be manually synced with registry and TOOL_GRAPH | Patch-level (no generation) |
| `services/standardizer.py` | ~400+ lines | `UnifiedStandardizer`, config-driven lookup tables, 5 parameter families, fuzzy fallback | Framework-grade |
| `services/standardization_engine.py` | ~600+ lines | `StandardizationEngine`, `RuleBackend`, `LLMBackend`, `PARAM_TYPE_REGISTRY` | Framework-grade coordinator |
| `config/unified_mappings.yaml` | ~600+ lines | 13 MOVES vehicle types with VSP params, pollutants, seasons, road types, meteorology, column patterns | Config layer present |
| `config/meteorology_presets.yaml` | — | Meteorology presets for dispersion | Config layer present |
| `config/skills/*.yaml` | — | Skill descriptions injected into prompts | Config layer present |
| `core/artifact_memory.py` | ~300+ lines | `ArtifactMemoryState`, `ArtifactType`, delivery tracking, `classify_artifacts_from_delivery()` | Framework-grade |
| `core/file_relationship_resolution.py` | ~400+ lines | `FileRelationshipType` enum, `FileRelationshipDecision`, `build_file_relationship_transition_plan()` | Framework-grade |
| `core/plan_repair.py` | ~300+ lines | `RepairActionType` enum (7 types), `RepairTriggerType`, `validate_plan_repair()` | Framework-grade |
| `tests/test_task_state.py` | ~80+ lines reviewed | Tests for state initialization, parameter locking, transition validation | Unit test coverage present |
| `tests/test_tool_dependencies.py` | — | Dependency validation tests | Present |
| `tests/test_parameter_negotiation.py` | — | Negotiation parsing tests | Present |
| `tests/test_workflow_templates.py` | — | Template selection tests | Present |
| `tests/test_readiness_gating.py` | — | Readiness assessment tests | Present |
| `tests/test_remediation_policy.py` | — | Policy application tests | Present |

---

## Paper Positioning Judgment

The current codebase **can be credibly presented as a framework paper**, but with important conditions.

The evidence for a framework claim is substantial: a validated 7-state machine with bounded transitions; a declarative tool dependency graph with deterministic pre-execution gating; a multi-tier config-driven parameter standardization system; a formal parameter negotiation protocol with deterministic reply parsing; a policy-based remediation system with citable lookup tables; a ~100-type auditable decision trace; and typed dataclasses throughout that produce auditable, serializable state.

The evidence **against** a framework claim is also substantial: the primary implementation vehicle is a 439 KB monolithic router class; the new state machine is not the unconditional execution default; workflow templates cannot be extended without code changes; tool specification is fragmented across three files; and several governance rules remain as hardcoded Python constants embedded in the router.

For a strong paper positioning, the following gap must be closed: **the governance machinery must be demonstrably separable from the routing machinery**. As currently implemented, a reviewer can point to `core/router.py` and argue that the "framework" is just a complex router with some typed helper classes, not a principled governance architecture. The refactor described in Priority 1 (extracting `GovernanceEngine`) is the single change that would most directly elevate the paper's architectural credibility. Without it, the framework layers described in this audit are real but invisible at the architectural boundary level.

A secondary but important gap: the **legacy execution path must be removed**. A paper cannot claim that "the system enforces dependency constraints" while the config default may run a path that enforces none of them.

With these two changes, plus workflow template externalization (Priority 3), the codebase would constitute a credible and original framework paper: a domain-grounded agent architecture for emission analysis with a formally specified state machine, constraint-governed tool execution, and structured interaction protocols for handling ambiguity and missing data.
