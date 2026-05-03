# Phase 8.2.1 Benchmark Protocol Design (No Data Run)

**Date:** 2026-05-03
**Branch:** `phase3-governance-reset`
**Status:** Design — no benchmark execution.
**Scope:** Protocol design + resource audit + gap analysis for 3 evaluation layers.

Based on Anchors §五 sell point 4, this design implements 3 of the 4 evaluation layers
(Layer 4 user study deferred to paper-writing phase).

---

## §1 Layer 1: Parameter Standardization Benchmark

### §1.1 Existing Resource Audit

**Benchmark file:** `evaluation/benchmarks/standardization_benchmark.jsonl`
- **825 tasks**, 169 KB
- **6 dimensions:** vehicle_type (231), meteorology (168), stability_class (152), road_type (110), pollutant (94), season (70)
- **3 difficulty levels:** easy (220), medium (184), hard (421)
- **3 languages:** en (598), zh (182), mixed (45)

**Runner:** `evaluation/eval_standardization_benchmark.py` (228 lines)
- 4 modes: `auto`, `rule_only`, `rule_fuzzy`, `full`
- Mode controlled by env vars: `STANDARDIZATION_FUZZY_ENABLED`, `ENABLE_LLM_STANDARDIZATION`
- Metrics: accuracy, coverage, avg_confidence — broken down by dimension, difficulty, dimension×difficulty, strategy distribution
- Strategy tracking: exact, alias, fuzzy, LLM, abstain, unsupported

**Ablation runner:** `evaluation/eval_standardization_ablation.py` (2,746 bytes)
- Supports standalone ablation over standardization modes

**Task format (from actual data):**
```json
{
  "dimension": "vehicle_type",
  "difficulty": "easy",
  "raw_input": "Motorcycle",
  "expected_output": "Motorcycle",
  "language": "en",
  "notes": "direct known mapping",
  "id": "vehicle_type_easy_0001"
}
```

### §1.2 Alignment with Anchors Requirements

Anchors §三 defines 6 standardization tiers: exact, alias, fuzzy, LLM, default, abstain.
The existing benchmark maps cleanly:

| Anchors Tier | Existing Strategy Tag | Present in Benchmark? |
|---|---|---|
| exact | `exact` | Yes — easy tier, primarily |
| alias | `alias` | Yes — medium/hard, zh/mixed inputs |
| fuzzy | `fuzzy` | Yes — medium tier |
| LLM | `llm` | Yes — hard tier, only when `ENABLE_LLM_STANDARDIZATION=true` |
| default | `default` | Partial — covered by engine behavior when no match |
| abstain | `abstain` | Yes — failure/unknown cases |

**Scale assessment vs "large-scale" claim (Anchors §五):** 825 tasks is moderate.
For claims of "large-scale parameter standardization," consider expanding to
≥ 1,500 (Anchors mentions "≥ 500" as a lower bound, but 825 is above that
already). The 6 dimensions have uneven coverage (vehicle_type 231 vs season 70) —
balanced expansion would be 250/dimension.

### §1.3 Scoring Method

The existing runner computes:
- **Accuracy:** `correct / total` (exact match of `actual == expected`)
- **Coverage:** `covered / total` (non-abstained rate)
- **Avg Confidence:** mean of `StandardizationResult.confidence`
- **Strategy distribution:** count per strategy tag

**Gap:** No per-dimension accuracy×difficulty heatmap visualization.
No statistical significance reporting (CI for accuracy differences between modes).
These are nice-to-have for paper, not blockers for Phase 8.2.2.

### §1.4 Relation to end2end_tasks.jsonl

The standardization benchmark is an **independent Layer 1 asset** — it tests
the standardization engine in isolation (no LLM routing, no tool execution).
It is not a subset of the end-to-end tasks and should be evaluated separately.

The standardization engine IS used inside the end-to-end pipeline
(`enable_executor_standardization` flag), so Layer 1 scores are diagnostic
for Layer 2 failures: if a task fails at Layer 2, Layer 1 accuracy tells
whether the failure is a parameter recognition problem or a routing problem.

### §1.5 Gap Summary (Layer 1)

| Item | Status | Action for Phase 8.2.2 |
|---|---|---|
| Task volume ≥ 500 | 825 ✓ | None required |
| 6-dimension coverage | Uneven (70–231) | Optional: balance to 250/dim |
| Difficulty coverage | 3 tiers ✓ | None required |
| Language coverage | en/zh/mixed ✓ | None required |
| Runner + 4 modes | Complete ✓ | None required |
| Ablation runner | Complete ✓ | None required |
| Per-dim heatmap | Missing | Optional — nice-to-have |
| CI reporting | Missing | Optional — nice-to-have |

**Phase 8.2.2 action:** Run standardization eval in all 4 modes (rule_only,
rule_fuzzy, full, auto) with n=1. Only re-run if Layer 2 results show
standardization is a failure bottleneck.

---

## §2 Layer 2: End-to-End 180+75 Benchmark

### §2.1 Existing Task Set Audit

**Main benchmark:** `evaluation/benchmarks/end2end_tasks.jsonl` — **182 tasks**, 121 KB

**Category distribution:**

| Category | Count | Description |
|---|---|---|
| parameter_ambiguous | 24 | Ambiguous parameters requiring resolution |
| simple | 21 | Single-tool, clear parameters |
| multi_step | 20 | Multi-tool chain execution |
| multi_turn_clarification | 20 | Needs clarification, user provides follow-up |
| user_revision | 20 | User revises parameters mid-execution |
| ambiguous_colloquial | 20 | Colloquial/underspecified language |
| code_switch_typo | 20 | Mixed zh/en + typographical errors |
| constraint_violation | 19 | Cross-parameter constraint triggers |
| incomplete | 18 | Missing required parameters |

**Tool distribution (expected chains):**

| Tool | Count |
|---|---|
| query_emission_factors | 93 |
| calculate_macro_emission | 42 |
| calculate_dispersion | 27 |
| calculate_micro_emission | 16 |
| render_spatial_map | 10 |
| analyze_hotspots | 5 |
| query_knowledge | 2 |

**Other attributes:**
- smoke flag: 32 tasks
- has_file: 63 tasks
- Phase 8 tasks: 2 (e2e_constraint_181, e2e_constraint_182)

**Held-out test set:** `evaluation/benchmarks/held_out_tasks.jsonl` — **75 tasks**, 53 KB

| Category | Count |
|---|---|
| simple | 12 |
| ambiguous_colloquial | 10 |
| multi_turn_clarification | 10 |
| multi_step | 8 |
| user_revision | 8 |
| code_switch_typo | 8 |
| parameter_ambiguous | 7 |
| constraint_violation | 7 |
| incomplete | 5 |

### §2.2 Alignment with Anchors "180+75"

**Current split: 182 main + 75 held-out = 257 total.**

The Anchors §五 reference to "180+75" means 180 main benchmark tasks + 75
held-out test tasks. Current state:

| Split | Target | Actual | Status |
|---|---|---|---|
| Main (train/dev) | 180 | 182 | 2 over (noise from Phase 8.1.8 additions) |
| Held-out (test) | 75 | 75 | Exact |

**The 180+75 split is structurally correct.** The 2 extra tasks in main
(e2e_constraint_181, e2e_constraint_182) are Phase 8.1.8 closed-loop
demo additions. They should either stay in main (they were added as
main-benchmark tasks with `smoke=true`) or be reclassified as a separate
`constraint_demo` subset.

### §2.3 Category and Tool Distribution Assessment

**Category balance:** Good spread across 9 categories (18–24 tasks each).
No single category dominates. Constraint_violation slightly lower at 19
(partially compensated by the 2 new Phase 8.1.8 tasks).

**Tool distribution skew:** `query_emission_factors` dominates (93 of 182,
51%), `calculate_macro_emission` second (42, 23%). The remaining 5 tools
share 26% of tasks. This is expected — simpler tools appear more frequently
because multi-step chains start with them — but the skew means aggregate
metrics are heavily influenced by `query_emission_factors` performance.

**Held-out tool distribution:** query_emission_factors 57 (76%),
calculate_macro_emission 10 (13%) — even more skewed toward simple tasks.
This means held-out metrics primarily reflect single-tool emission factor
lookup performance.

### §2.4 Held-Out Characteristics

The 75 held-out tasks follow the same category structure as main (9 categories)
but with a simpler tool distribution. This is appropriate for a held-out
set — it should measure generalization on the same task types, not entirely
novel categories.

**Concern:** Held-out has only 1 `calculate_micro_emission` task and 0
`query_knowledge` tasks. If micro-emission or knowledge-query performance
is important, the held-out set won't measure it.

### §2.5 Gap Summary (Layer 2)

| Item | Status | Action |
|---|---|---|
| 180 main tasks | 182 (+2) | Reclassify or keep |
| 75 held-out tasks | 75 ✓ | None |
| Category coverage | 9 categories, both sets ✓ | None |
| Tool coverage (held-out) | 5 of 7 tools | Optional: add micro_emission + knowledge tasks |
| Main/held-out overlap | Different task IDs ✓ | None |
| Constraint tasks | 19 main + 7 held-out = 26 | Adequate for constraint ablation |
| Multi-step tasks | 20 main + 8 held-out | Adequate |

**Phase 8.2.2 action:** Run main 182 on governed_router + naive_router.
Run held-out 75 only for the winning configuration (avoid held-out
contamination). The 2 extra main tasks (constraint_181, 182) can remain
or be flagged `smoke=false` to keep "clean 180" as a subset.

---

## §3 Baseline Configuration

### §3.1 Existing NaiveRouter Implementation

**File:** `core/naive_router.py` (340 lines)

The NaiveRouter is a minimal function-calling loop:
- **System prompt:** 2-line Chinese prompt ("你是一个交通排放分析助手...")
- **Tool definitions:** Loaded from `get_tool_contract_registry().get_naive_available_tools()`
- **LLM:** Same `LLMClientService` as governed router (same model, temperature=0.0)
- **Max tool iterations:** 4
- **Max history turns:** 5
- **No governance:** No AO, no dependency graph, no cross-constraint validation, no PCM, no standardization, no readiness gating
- **Tool execution:** Raw parameters passed directly to `tool.execute(**raw_parameters)` — no parameter normalization

### §3.2 Baseline Definition per Anchors §八 Chapter 6.5

Anchors §八 Ch.6.5 requires: "baseline 明确" (baseline explicit), meaning a
**generic LLM agent** that lacks the EmissionAgent governance architecture:

| Component | Governed Router | NaiveRouter Baseline |
|---|---|---|
| AO lifecycle | Yes | No |
| Parameter standardization | Yes (multi-tier) | No (raw LLM output) |
| Dependency graph (TOOL_GRAPH) | Yes | No |
| Readiness gating | Yes | No |
| Cross-constraint validation | Yes | No |
| Parameter negotiation | Yes | No |
| PCM (collection) | Yes | No |
| B validator | Yes | No |
| Reconciler | Yes | No |
| Trace (100+ step types) | Yes | No (4 step types) |
| Tool execution | Via executor with standardization | Direct, raw parameters |
| System prompt | Extensive (Stage 2, 19 rules) | 2-line generic |

**The NaiveRouter satisfies the Anchors baseline definition as "vanilla
function-calling agent without governance."**

### §3.3 Baseline Components Assessment

**System prompt:** Current 2-line prompt is appropriately minimal for a
"no domain engineering" baseline. It provides enough context to use tools
but no emission-domain scaffolding. This is the correct design for a
baseline that measures the VALUE of governance architecture.

**Tool definition format:** NaiveRouter uses the same OpenAI-style function
definitions as governed router (loaded from contract registry). This is
correct — the baseline should differ in orchestration, not tool schemas.
If tool schemas differed, you couldn't attribute performance differences
to governance.

**Model:** Same LLM (via `LLMClientService` with same model config). This
is correct for an architecture ablation — same foundation model, different
orchestration layers.

**No file analysis:** NaiveRouter appends file path to user message but
does not run `FileAnalyzerTool` pre-flight. This is different from the
governed router's `enable_file_analyzer` path but matches the "no governance"
design intent — file context extraction is part of the governance pipeline.

### §3.4 Evaluation Integration

`eval_end2end.py` already supports `--mode naive` (line 1807). The naive path:
1. Creates `NaiveRouter(session_id=f"eval_naive_{task['id']}")`
2. Calls `router.chat(user_message, file_path, trace)`
3. Returns same-shaped response as router/full modes
4. Metrics computed identically (completion_rate, tool_accuracy, etc.)

### §3.5 NaiveRouter LLM Config Audit (Phase 8.2.1.1)

**Audit question:** Does NaiveRouter use the same LLM instance and configuration
as GovernedRouter, or does it have an independent configuration path?

**NaiveRouter LLM instantiation** (`core/naive_router.py:61`):
```python
self.llm = llm or LLMClientService(temperature=0.0, purpose="agent")
```

**GovernedRouter LLM instantiation** (via `core/router.py:353`):
```python
self.llm = get_llm_client("agent")
```

**Resolution path comparison:**

| Aspect | NaiveRouter | GovernedRouter | Same? |
|---|---|---|---|
| Purpose key | `"agent"` | `"agent"` | Yes |
| Config resolution | `_get_assignment_for_purpose("agent")` → `config.agent_llm` | Same path | Yes |
| Model | `config.agent_llm.model` (deepseek-v4-pro) | Same | Yes |
| Provider | `config.agent_llm.provider` (deepseek) | Same | Yes |
| API key | `config.providers["deepseek"]["api_key"]` | Same | Yes |
| Base URL | `config.providers["deepseek"]["base_url"]` | Same | Yes |
| Temperature | Hardcoded `0.0` | `config.agent_llm.temperature` (also `0.0`) | Yes (identical value) |
| Max tokens | `config.agent_llm.max_tokens` (8000) | Same | Yes |
| Instance caching | New instance each `NaiveRouter()` call | Cached singleton (`get_llm_client`) | No (instance, not config) |
| Extra body (thinking) | Same provider_extra_kwargs path | Same | Yes |

**Instance caching difference:**
- NaiveRouter creates `LLMClientService()` directly: a fresh `OpenAI` client per
  NaiveRouter instance. In eval, each task creates a new `NaiveRouter`
  (line 1476–1488 in `eval_end2end.py`), so each task gets a new client.
- GovernedRouter uses `get_llm_client("agent")` which caches by `purpose_model` key.
  The same `LLMClientService` instance is reused across tasks via `build_router()`.

This is a **performance difference, not a behavioral difference.** Both use the
same API endpoint with the same authentication. The fresh client per task in
NaiveRouter does not change model behavior (temperature=0.0 is deterministic).

**Verdict: NaiveRouter and GovernedRouter use identical LLM configuration.**
The baseline comparison isolates architecture (governance vs. none) without
confounding model/provider differences. This satisfies Anchors §八 Ch.6.5
"baseline 明确" requirement.

**LOC needed for correction:** 0 (no discrepancy found).

### §3.6 Gap Summary (Baseline)

| Item | Status | Action |
|---|---|---|
| NaiveRouter exists | Yes ✓ | None |
| Same LLM as governed | Yes ✓ | None (correct design) |
| Same tool schemas | Yes ✓ | None (correct design) |
| Mininal system prompt | Yes ✓ | None |
| Eval integration | Yes (--mode naive) ✓ | None |
| No governance at all | Confirmed ✓ | None |

**Phase 8.2.2 action:** Run `python3 evaluation/eval_end2end.py --mode naive`
on the main 182 tasks. No code changes needed.

---

## §4 Three Ablation Branches

Per Anchors §七 P1 requirement: "关闭 AO / 关闭依赖图 / 关闭约束反馈 三个消融分支"
(three ablation branches: AO off, dependency graph off, constraint feedback off).

### §4.1 Existing Ablation Configurations

`evaluation/eval_ablation.py` (174 lines) defines 5 ablation configs via env vars:

| Config | Env Overrides |
|---|---|
| `baseline` | (none — full governance) |
| `no_standardization` | `ENABLE_EXECUTOR_STANDARDIZATION=false` |
| `no_cross_constraint` | `ENABLE_CROSS_CONSTRAINT_VALIDATION=false` |
| `no_negotiation` | `ENABLE_PARAMETER_NEGOTIATION=false` |
| `no_readiness` | `ENABLE_READINESS_GATING=false` |

**Gap: The existing 5 configs do NOT match the Anchors 3 branches.** The
Anchors require: (1) no AO, (2) no dependency graph, (3) no constraint
feedback. The existing configs target different components.

### §4.2 Branch 1: AO Off (关闭 AO)

**What AO does:**
- `AnalyticalObjective` lifecycle: create AO, track state, merge AOs, close AOs
- `AOClassifier`: classifies messages as CONTINUATION/REVISION/NEW_AO
- `AOManager`: manages AO state transitions, chain progression
- AO classification determines whether clarification contract enters at `before_turn`

**How to disable:**
There is no single `ENABLE_AO` flag. AO is disabled by:
- **Option A (bypass governed_router):** Use `NaiveRouter` directly. This disables
  ALL governance, not just AO. Overshoot for this ablation branch.
- **Option B (AO classifier bypass):** Force all messages to NEW_AO classification.
  This would require a code change (not allowed in Phase 8.2.1 scope) or a new
  config flag `ENABLE_AO_CLASSIFIER` that skips classification and treats every
  message as NEW_AO.
- **Option C (remove AO from governed_router):** Skip AO lifecycle entirely in
  `governed_router.py`. Requires code change.

**Recommended design for Phase 8.2.2: Option B** — add `ENABLE_AO_CLASSIFIER`
flag (default true) to `config.py`. When false, `AOClassifier.classify()` returns
`NEW_AO` unconditionally. This gives a clean ablation: governance is preserved
(contracts, reconciler, B validator, cross-constraint) but AO lifecycle
(CONTINUATION, REVISION, multi-turn state) is disabled.

**LOC estimate:** ~15 LOC (config flag + 1 early-return in AO classifier).

**Expected behavior (ablation mode, fast_path forced off):**
- Multi-turn tasks (multi_step, multi_turn_clarification, user_revision) should
  DEGRADE — each turn treated as independent, no state persistence
- Single-turn tasks should be UNAFFECTED — no AO needed for single-turn
- Completion rate should drop for multi-turn categories
- All tasks pass through governed_router pipeline (fast_path disabled for clean ablation)

**Tasks expected to fail:** multi_turn_clarification (20), user_revision (20),
multi_step (20) — approximately 60 tasks should show degradation.

### §4.3 Branch 2: Dependency Graph Off (关闭依赖图)

**What the dependency graph provides:**
- `core/tool_dependencies.py` — `TOOL_GRAPH` declarative `requires`/`provides` per tool
- Readiness gating (`core/readiness.py`): checks whether a tool's required inputs
  are available before execution
- Reverse inference: from desired tool, infer what upstream tools are needed
- Tool ordering constraints: ensures prerequisite data exists before downstream tools run

**How to disable:**
- `ENABLE_READINESS_GATING` flag already exists (`config.py:221`, default true).
  Setting to false disables readiness checks — tools execute without verifying
  prerequisite data availability.
- `ENABLE_PARAMETER_NEGOTIATION` flag (`config.py:215`, default true) disables
  negotiation when tools can't proceed.

**Existing `no_readiness` config in `eval_ablation.py` partially matches.**
However, Anchors requires "dependency graph off" which is broader than just
readiness gating:
- Readiness gating: skips pre-execution prerequisite checks
- TOOL_GRAPH: still used for chain projection (even with readiness off)
- Reverse inference: still active in intent resolution

**Recommended design for Phase 8.2.2:**
Use `ENABLE_READINESS_GATING=false` as the primary flag. This is the correct
operational definition — tools execute in LLM-determined order without
architectural dependency enforcement. The TOOL_GRAPH data structure still
exists but its operational effect (blocking execution) is disabled.

**LOC estimate:** 0 (flag already exists).

**Expected behavior (ablation mode, fast_path forced off):**
- Multi-step tasks (multi_step) should DEGRADE — tools may execute in wrong order
  or skip prerequisites
- Dispersion/hotspot tasks that depend on prior emission results should fail
  more frequently when emission calculation is skipped
- Simple single-tool tasks should be UNAFFECTED

**Tasks expected to fail:** multi_step (20), some calculate_dispersion tasks
(27 total, ~half need prior macro_emission), analyze_hotspots (5),
render_spatial_map (10) — estimated 30–40 tasks affected.

### §4.4 Branch 3: Constraint Feedback Off (关闭约束反馈)

**What constraint feedback provides:**
- `CrossConstraintValidator` (`services/cross_constraints.py`): validates
  parameter pairs against 5 YAML-defined constraints
- `ConstraintViolationWriter` (`core/constraint_violation_writer.py`): persists
  violations to context store
- K7 `prior_violations` injection: violations fed back to Stage 2 LLM prompt
- User-facing violation text: blocked/warning messages shown to user

**How to disable:**
- `ENABLE_CROSS_CONSTRAINT_VALIDATION` flag already exists (`config.py:212`,
  default true). Setting to false disables the cross-constraint validator gate
  at `governed_router.py:1041`.

**Existing `no_cross_constraint` config in `eval_ablation.py` matches this branch.**

**LOC estimate:** 0 (flag already exists).

**Expected behavior (ablation mode, fast_path forced off):**
- Constraint tasks (constraint_violation category, 19 main + 7 held-out) should
  show DIFFERENT behavior — illegal parameter combinations pass through without
  warning or blocking
- Non-constraint tasks should be UNAFFECTED
- `parameter_legal_rate` metric should DROP (more illegal combinations)
- BUT `completion_rate` may RISE (fewer tasks blocked by constraints)

**Tasks expected to change:** constraint_violation (19 main + 7 held-out = 26).

### §4.5 Ablation Branch Summary

| Branch | Config Flag | Exists? | LOC Needed | Tasks Affected |
|---|---|---|---|---|
| AO off | `ENABLE_AO_CLASSIFIER` (new) | No | ~15 | ~60 (multi-turn) |
| Dependency graph off | `ENABLE_READINESS_GATING` | Yes | 0 | ~30–40 (multi-step) |
| Constraint feedback off | `ENABLE_CROSS_CONSTRAINT_VALIDATION` | Yes | 0 | ~26 (constraint) |

### §4.6 Ablation Design Note

The existing 5-config ablation in `eval_ablation.py` (baseline, no_standardization,
no_cross_constraint, no_negotiation, no_readiness) targets DIFFERENT components
than the Anchors 3 branches. The existing configs were designed for Phase 5.3
internal verification, not for the Anchors paper evaluation.

For Phase 8.2.2, either:
- **Recommendation: Rename/remap existing configs** — `no_readiness` → Anchors
  "dependency graph off", `no_cross_constraint` remains → "constraint feedback
  off", add new `no_ao` config
- **Alternative: Keep both sets** — run Anchors 3 branches for paper metrics
  + existing 5 configs for internal diagnostics

**fast_path handling in ablation runs (Phase 8.2.1.1 adjustment):**
All ablation branches (Runs 3–5 in §7.3) force `--no-fast-path` to ensure
every task passes through the governed_router pipeline. This prevents the
`conversation_fast_path` bypass from silently skipping the ablated component
even in "ON" mode, which would compress ablation deltas. A supplementary
run (Run 8) measures fast_path bypass rate in production mode to quantify
the production-vs-ablation gap.

Also note: `ENABLE_STATE_ORCHESTRATION` flag (`config.py:68`, default true) and
`ENABLE_PARAMETER_NEGOTIATION` flag (`config.py:215`, default true) are
additional levers but not part of the Anchors 3-branch requirement.

### §4.7 Expected Telemetry per Ablation Branch

Ablation data attribution credibility depends on telemetry: each branch must
produce observable trace evidence that the component WAS or WAS NOT active.
Below, "expected present" means the TraceStepType must appear in at least one
task's trace_payload for the branch to be credible. "Expected absent" means
the step type should never appear — if it does, the ablation is leaking.

#### §4.7.1 Branch 1: AO Off

**Existing AO-related TraceStepType values:** None. AO classification and
lifecycle are not tracked via `TraceStepType` enum values. This is a
telemetry gap — there is no first-class trace evidence that AO classification
occurred. The only indirect evidence is `decision_field_clarify` showing up
in `GOVERNANCE_TRACE_STEPS` (which requires AO to route through the
clarification contract).

**Required new trace step for this ablation:**
- `AO_CLASSIFIER_FORCED_NEW_AO` — emitted when `ENABLE_AO_CLASSIFIER=false`
  and the classifier returns `NEW_AO` unconditionally. This confirms the
  ablation is active.

**LOC estimate for new trace step:** ~10 LOC (enum value + 1 emission point in `core/ao_classifier.py`).
Same pattern as Phase 8.1.4c governance trace steps.

**Expected telemetry when AO is OFF:**

| TraceStepType | Expected | Rationale |
|---|---|---|
| `AO_CLASSIFIER_FORCED_NEW_AO` (new) | **Present** (every turn) | Confirms ablation active |
| `reconciler_invoked` | Present (if task reaches governed path) | Reconciler is downstream of AO — not affected by AO-off |
| `pcm_advisory_injected` | Present (if PCM active) | PCM is independent of AO |
| `b_validator_filter` | Present (if B validator triggers) | B validator is independent of AO |
| `cross_constraint_validated` | Present (if validator gate reached) | Cross-constraint is independent of AO |
| `projected_chain_generated` | Present (if multi-step chain predicted) | Chain projection may still fire |
| `decision_field_clarify` | May be reduced | AO CONTINUATION no longer possible — fewer clarification contract entries |
| AoHistory persistence across turns | **Absent** | Core claim: every turn = fresh NEW_AO |
| `parameter_negotiation_*` | Present (if negotiation needed) | Negotiation is independent of AO |

**Silent-affected telemetry (requires 1-task verification):**
- `decision_field_clarify` count: should drop because AO CONTINUATION path is dead.
  Multi-turn tasks that previously relied on CONTINUATION will enter as NEW_AO
  each turn — the governance pipeline may produce different decisions.
- `file_relationship_resolution_*`: file context may be re-analyzed each turn
  instead of inherited from parent AO — telemetry may show more resolution
  triggers.

#### §4.7.2 Branch 2: Dependency Graph Off

**Existing readiness-related TraceStepType values:**
- `readiness_assessment_built` — readiness assessment constructed
- `action_readiness_ready` — tool ready to execute
- `action_readiness_blocked` — tool blocked by missing prerequisites
- `action_readiness_repairable` — blocked but repairable
- `action_readiness_already_provided` — prerequisite already satisfied
- `dependency_validated`, `dependency_blocked` — dependency graph checks

**Required new trace step for this ablation:**
- `READINESS_GATING_SKIPPED` — emitted when `ENABLE_READINESS_GATING=false`
  and the readiness check is bypassed. This confirms the ablation is active.

**LOC estimate for new trace step:** ~10 LOC (enum value + 1 emission point in `core/readiness.py` or `governed_router.py`).

**Expected telemetry when graph is OFF:**

| TraceStepType | Expected | Rationale |
|---|---|---|
| `READINESS_GATING_SKIPPED` (new) | **Present** (every tool execution) | Confirms ablation active |
| `readiness_assessment_built` | **Absent** | Readiness check bypassed |
| `action_readiness_ready` | **Absent** | No readiness check = no readiness states |
| `action_readiness_blocked` | **Absent** | Same |
| `action_readiness_repairable` | **Absent** | Same |
| `dependency_validated` | **Absent** | Dependency check bypassed |
| `dependency_blocked` | **Absent** | Same |
| `projected_chain_generated` | May be present | Chain projection uses TOOL_GRAPH but doesn't require readiness gating |
| `reconciler_invoked` | Present | Reconciler is independent |
| `cross_constraint_validated` | Present | Cross-constraint is independent |
| `pcm_advisory_injected` | Present | PCM is independent |

**Silent-affected telemetry:**
- `tool_selection`: LLM may select tools in wrong order (no graph enforcement).
  This is observable via `executed_tool_calls` order in eval logs, not via
  TraceStepType.
- `plan_step_completed`: Multi-step tasks may complete steps out of order.
  Observable via eval log chain comparison.

#### §4.7.3 Branch 3: Constraint Feedback Off

**Existing constraint-related TraceStepType values:**
- `cross_constraint_validated` — validator ran, no violations
- `cross_constraint_violation` — hard block violation detected
- `cross_constraint_warning` — soft warning violation detected

**Required new trace step for this ablation:**
- `CROSS_CONSTRAINT_CHECK_SKIPPED` — emitted when `ENABLE_CROSS_CONSTRAINT_VALIDATION=false`.
  Confirms the validator gate was bypassed.

**LOC estimate for new trace step:** ~10 LOC (enum value + 1 emission point near `governed_router.py:1041`).

**Expected telemetry when constraint feedback is OFF:**

| TraceStepType | Expected | Rationale |
|---|---|---|
| `CROSS_CONSTRAINT_CHECK_SKIPPED` (new) | **Present** (every task that reaches validator gate) | Confirms ablation active |
| `cross_constraint_validated` | **Absent** | Validator bypassed entirely |
| `cross_constraint_violation` | **Absent** | Same |
| `cross_constraint_warning` | **Absent** | Same |
| `reconciler_invoked` | Present | Reconciler is independent — but K7 `prior_violations` field will be empty |
| `pcm_advisory_injected` | Present | PCM is independent |
| `parameter_negotiation_*` | May change | Without constraint blocking, fewer tasks reach negotiation |

**Silent-affected telemetry:**
- K7 `prior_violations` in Stage 2 LLM prompt: will be empty `"[]"`. This
  is NOT a TraceStepType — it's in the Stage 2 prompt payload. Must verify via
  Stage 2 instrumentation (same pattern as Phase 8.1.6 micro-audit).
- `parameter_legal_rate` eval metric: should drop because illegal parameter
  combinations are no longer blocked. This is an eval-level metric, not a
  TraceStepType.

#### §4.7.4 Telemetry Implementation Summary

| New TraceStepType | Branch | Enum Location | Emission Point | LOC |
|---|---|---|---|---|
| `AO_CLASSIFIER_FORCED_NEW_AO` | AO off | `core/trace.py` | `core/ao_classifier.py` (early-return) | ~10 |
| `READINESS_GATING_SKIPPED` | Graph off | `core/trace.py` | `core/readiness.py` or `governed_router.py` | ~10 |
| `CROSS_CONSTRAINT_CHECK_SKIPPED` | Constraint off | `core/trace.py` | `core/governed_router.py:1041` gate | ~10 |

**Total telemetry LOC:** ~30 LOC (3 enum values + 3 emission points).
Same pattern as Phase 8.1.4c which added 5 governance TraceStepType values
(reconciler_invoked, reconciler_proceed, b_validator_filter,
pcm_advisory_injected, projected_chain_generated) at ~50 LOC total.

**Verification protocol:** After implementing each flag + trace step, run
1 constraint task + 1 multi-step task + 1 multi-turn task in the respective
ablation mode. Check eval logs for the new trace step. If absent, the
ablation is not working as designed — STOP and diagnose before proceeding
to n=3 full runs.

### §4.8 AO-Off Pre-Sanity Plan (Phase 8.2.1.1)

Before running the full AO-off ablation (Run 3 in §7.3), a single-task sanity
check must pass. This gates the ablation run — a silent failure here would
produce uninterpretable results.

#### §4.8.1 Sanity Test Design

**Test task:** `e2e_multi_step_001` (multi_step category, 2-tool chain expected).

**Setup:**
1. Implement `ENABLE_AO_CLASSIFIER` flag in `config.py` (~5 LOC)
2. Add early-return in `AOClassifier.classify()`: when flag is false, return `NEW_AO` (~5 LOC)
3. Add `AO_CLASSIFIER_FORCED_NEW_AO` trace step emission (~5 LOC)
4. Run eval with `ENABLE_AO_CLASSIFIER=false` for this single task

**Pass criteria:**

| Check | Method | Must See |
|---|---|---|
| AO classifier returns NEW_AO | Trace step `AO_CLASSIFIER_FORCED_NEW_AO` present | **Yes** |
| No CONTINUATION classification | No `decision_field_clarify` from AO-inherited context | **Yes** (or significantly reduced) |
| Turn 2 treated as fresh | `AOExecutionState` not carried from Turn 1 | Turn 2 starts with fresh parameter slots |
| Multi-turn task degrades | `expected_tool_chain` ≠ `actual_tool_chain` | Mismatch (Turn 2 unaware of Turn 1 results) |
| Tool still executes | At least 1 tool call in Turn 1 | Yes (governance + tool execution preserved) |

**Fail criteria (STOP if any):**

| Symptom | Root Cause | Action |
|---|---|---|
| `AO_CLASSIFIER_FORCED_NEW_AO` absent | Flag not wired correctly | Fix flag path |
| Turn 2 successfully chains from Turn 1 | AO state leaking via non-classifier path (e.g., AOManager bypass) | Trace AO state persistence; may need additional gate |
| All tools fail | Flag broke something else | Revert, diagnose via standalone router run |
| Completion rate unchanged vs governed_router | Task doesn't depend on AO (wrong test task) | Try e2e_multi_turn_clarification_001 (clarification required) or e2e_user_revision_001 |

#### §4.8.2 Sanity Success Definition

The sanity passes when:
1. `AO_CLASSIFIER_FORCED_NEW_AO` trace step **present** in eval log (confirm ablation active)
2. Task completion behavior **differs** from governed_router mode (confirm ablation has effect)
3. Non-AO governance steps **still present** (confirm ablation is narrow — only AO removed)

If all 3 conditions met → proceed to Run 3 (full 182-task n=3 AO-off ablation).
If any condition fails → STOP, diagnose, report to user before continuing.

---

## §5 Evaluation Runner Audit

### §5.1 Current Runner Capabilities

`evaluation/eval_end2end.py` (73,751 bytes, ~2,000 lines):

**Modes:** `router`, `full`, `naive`, `tool` (CLI `--mode`, line 1807)
- `router`/`full`: Production `GovernedRouter.chat()` via `build_router()`
- `naive`: `NaiveRouter.chat()` — baseline
- `tool`: Direct `ToolExecutor.execute()` — offline validation, single-step only

**Execution:**
- Sequential (parallel=1) or parallel (ThreadPoolExecutor, default 8 workers)
- Per-task timeout (`BENCHMARK_TASK_TIMEOUT_SEC`, default 180s)
- Rate limiting (QPS limit, default 15.0)
- Infrastructure failsafe: retry (3x), billing abort, network abort (5 consecutive)
- Tool result caching (`ToolResultCache`)

**Runtime overrides:**
- `enable_file_analyzer`, `enable_file_context_injection`, `enable_executor_standardization`
- `macro_column_mapping_modes`
- Controlled via `runtime_overrides()` context manager in `evaluation/utils.py:47`

**Outputs:**
- `end2end_logs.jsonl` — per-task records with trace_payload, executed_tool_calls, response
- `end2end_metrics.json` — aggregate metrics by category, tool, failure mode

**Multi-rep support:** NOT built into `eval_end2end.py` directly. Multi-rep is
handled by `eval_ablation.py` which calls `eval_end2end.py` as a subprocess
n=3 times and aggregates results with mean/median/stdev/min/max.

### §5.2 Ablation Mode Switching

**Current mechanism:** `eval_ablation.py` sets env vars before subprocess call:
```python
ABLATION_CONFIGS = {
    "baseline": {},
    "no_standardization": {"ENABLE_EXECUTOR_STANDARDIZATION": "false"},
    "no_cross_constraint": {"ENABLE_CROSS_CONSTRAINT_VALIDATION": "false"},
    "no_negotiation": {"ENABLE_PARAMETER_NEGOTIATION": "false"},
    "no_readiness": {"ENABLE_READINESS_GATING": "false"},
}
```

**This works but is fragile:** env vars must be read by `config.py` at init
time, and `reset_config()` must be called between runs. Currently,
`eval_ablation.py` uses subprocess isolation which is correct but slow
(process spawn per run × rep).

**`runtime_overrides()` context manager** in `eval_end2end.py:1643` only
covers file_analyzer, file_context_injection, executor_standardization, and
macro_column_mapping_modes. It does NOT accept ablation env vars like
`ENABLE_READINESS_GATING` or `ENABLE_CROSS_CONSTRAINT_VALIDATION`.

### §5.3 fast_path Handling in Ablation Mode

**Problem:** The `conversation_fast_path` in `router.py:721-732` can bypass
the full governed_router pipeline including cross-constraint validation.
This is a pre-existing code path issue, not an evaluation runner issue.

**Impact on ablation:**
- `no_cross_constraint` ablation: fast_path bypass means constraint validation
  is already bypassed for some tasks even in "ON" mode — the ablation delta
  may be smaller than expected
- `no_ao` ablation: fast_path tasks skip AO lifecycle — the ablation delta
  for AO-off may be smaller than expected

**Recommended handling for Phase 8.2.2 (updated Phase 8.2.1.1 — mixed approach):**

**Main ablation runs (Runs 1–5):** Force fast_path off via `ENABLE_FAST_PATH=false`
flag (~5 LOC). Every task passes through the full governed_router pipeline.
Clean ablation measurement — no component can be silently bypassed.

**Supplementary run (Run 8):** Governed_router in production mode (fast_path enabled)
vs. ablation mode (fast_path disabled), same 182-task set. This measures:
- fast_path bypass rate (what fraction of tasks take the shortcut)
- Metric delta between production and ablation modes (quantifies how much
  fast_path compresses ablation deltas)
- Per-category breakdown of bypass rate (which task categories are most affected)

**Rationale:** The Anchors 3-branch ablation measures the contribution of individual
governance components. If fast_path silently bypasses those components for X% of
tasks in "ON" mode, the measured ablation delta is diluted by a factor of (1-X).
Reporting X alongside ablation deltas makes the attribution credible.

### §5.4 Runner Gap Summary

| Capability | Status | LOC Estimate |
|---|---|---|
| Multi-mode (router/full/naive/tool) | Complete ✓ | 0 |
| Ablation via env vars + subprocess | Works but fragile | 0 |
| Ablation via runtime_overrides | Incomplete (missing governance flags) | ~20 |
| Multi-rep n=3 | Supported via eval_ablation.py | 0 |
| Raw trace serialization | Complete (Phase 8.1.6 fix applied) ✓ | 0 |
| fast_path control | Not supported | ~5 (optional) |
| AO-off flag | Not implemented | ~15 |
| Per-category breakdown | Complete ✓ | 0 |
| Infrastructure failsafe | Complete ✓ | 0 |
| Tool result caching | Complete ✓ | 0 |
| Parallel execution | Complete ✓ | 0 |

**Phase 8.2.2 runner modifications needed:**
1. Add `ENABLE_AO_CLASSIFIER` flag to `config.py` (~5 LOC)
2. Add `ENABLE_FAST_PATH` flag to `config.py` (~5 LOC)
3. Add `--ablation` flag to `eval_end2end.py` that accepts: `governance_full`,
   `no_ao`, `no_graph`, `no_constraint`, `baseline` (~25 LOC) — optional
4. Extend `runtime_overrides()` to accept governance flags (~10 LOC) — optional
5. Add 3 new TraceStepType enum values + emission points: `AO_CLASSIFIER_FORCED_NEW_AO`,
   `READINESS_GATING_SKIPPED`, `CROSS_CONSTRAINT_CHECK_SKIPPED` (~30 LOC)

**Total LOC estimate for runner modifications: ~50–85 LOC (minimum ~50 LOC).**

### §5.5 Independent vs Integrated Ablation Runs

**Current approach** (`eval_ablation.py`): separate subprocess per config × rep.
- Pros: clean isolation, proven working
- Cons: slow (process spawn), log fragmentation

**Alternative:** single-process multi-config runner.
- Pros: faster warm-up, unified log
- Cons: state leak risk between configs

**Recommendation:** Keep subprocess isolation for Phase 8.2.2 main runs
(guarantees clean state). Add single-process optional path for smoke testing
only. The `runtime_overrides` extension (§5.4 item 3) enables single-process
smoke without committing to it for production runs.

---

## §6 Layer 3: Shanghai End-to-End Case Data

### §6.1 Data Requirements per Anchors §八 Ch.5.3

Anchors §八 Chapter 5.3 describes the Shanghai end-to-end case as a
"complete city-scale emission analysis workflow":
1. Road network data (link-level geometry, traffic flow attributes)
2. Emission factor source (vehicle composition, model year distribution)
3. Meteorological data (resolution, time period)
4. End-to-end execution: emission calculation → dispersion → hotspot → map

### §6.2 Existing Shanghai Data Inventory

**Road network (GIS):** `GIS文件/上海市路网/`
- `opt_link.shp` + `.dbf` + `.shx` + `.prj` — link-level road geometry
  - `.dbf` is 20.5 MB — substantial attribute table
  - Links have geometry (`.shp` = 4.8 MB, `.shx` = 203 KB)
  - `.xlsx` version available (5.3 MB)
- `opt_node.shp` + `.dbf` + `.shx` + `.prj` — node-level topology
  - `.dbf` = 316 KB
  - `.shp` = 466 KB

**Road network (test):** `test_data/`
- `test_shanghai_full.xlsx` — 150 links, central Shanghai (121.34°–121.56°E, 31.14°–31.35°N)
  - 66 primary, 38 secondary, 17 trunk, 14 trunk_link, 6 motorway_link, 9 other
  - Average 9.5 coordinate points per link (range 3–47)
- `test_shanghai_allroads.xlsx` / `.zip` — full Shanghai road network (larger)
- `test_20links.xlsx` / `test_6links.xlsx` — smaller subsets for testing
- `test_no_geometry.xlsx` — edge case testing

**Shanghai base map:** `GIS文件/上海市底图/`
- `上海市.shp` + `.dbf` + `.shx` + `.prj` + `.sbn` + `.sbx` + `.cpg`
- Administrative boundary for map rendering

**Existing test guides:**
- `test_data/SHANGHAI_FULL_TEST_GUIDE.md` — detailed test protocol
- `test_data/ALLROADS_README.md`
- `test_data/TESTING_GUIDE.md`

### §6.3 Data Completeness Assessment

| Requirement | Available? | Format | Notes |
|---|---|---|---|
| Link-level road geometry | Yes | Shapefile (.shp) + Excel | Both node and link layers |
| Traffic flow attributes | Partial | .dbf attribute table | Unknown which fields exist (speed, volume, capacity?) |
| Vehicle composition | No | — | Not in test data. Can use MOVES defaults |
| Emission factor source | No | — | Not in test data. `query_emission_factors` tool provides MOVES EFs |
| Meteorological data | No | — | Not in test data. Dispersion tool has hardcoded presets (urban_summer_day etc.) |
| Season/time period | No | — | User specifies per-task |
| 150-link demo workflow | Yes | .xlsx + test guide | Existing end-to-end test documented |

### §6.4 Gap Analysis for Anchors §八 Ch.5.3

**Gap 1: Traffic flow data is unverified.** The `opt_link.dbf` attribute table
is large (20.5 MB) suggesting rich attributes, but the actual fields (speed,
flow, capacity) have not been audited against the `calculate_macro_emission`
input schema. The tool expects columns like `speed_kmh`, `flow_veh_h`, etc.
Without field mapping, the Shanghai road network may not be directly computable.

**Gap 2: No meteorological data files.** The dispersion tool uses presets
(`urban_summer_day`, etc.) hardcoded in the tool, not real meteorological
data. For a "real Shanghai case" claim, the paper would need either:
- Real Shanghai meteorological data (temperature, wind speed/direction,
  stability class) for a specific date
- OR explicit statement that meteorological presets were used (acceptable
  for a framework paper, less compelling for a case study)

**Gap 3: No vehicle composition data.** Real Shanghai traffic would have a
mix of vehicle types (passenger cars, buses, trucks, motorcycles). The
current test data likely has a single vehicle type assumption per road.
For a credible case study, vehicle composition percentages by road type
are needed. This data COULD be sourced from Shanghai traffic bureau reports
but is not in the repository.

**Gap 4: No "ground truth" for validation.** The Shanghai case would
demonstrate workflow execution but cannot validate accuracy without
reference data (monitoring station measurements, published emission
inventories). This is acceptable for a framework paper — the claim is
"framework enables city-scale analysis," not "framework produces validated
Shanghai emissions."

### §6.5 Minimum Viable Shanghai Case for Phase 8.2.2

To run an Anchors-compliant Shanghai case without new data acquisition:

1. **Use `test_shanghai_full.xlsx`** (150 links, central Shanghai) as road network
2. **Use MOVES emission factors** from `query_emission_factors` (already in tool)
3. **Use meteorological presets** for Shanghai summer/winter (urban_summer_day etc.)
4. **Assume uniform vehicle composition** (e.g., 80% Passenger Car, 15% Light Commercial Truck, 5% Combination Truck) — document assumption
5. **Execute the full chain:** macro_emission → dispersion → hotspots → spatial_map
6. **Report as "demonstration case,"** not "validated case study"

This is sufficient for a framework paper's Layer 3 claim. The data limitations
should be explicitly documented as scope boundaries.

### §6.6 Layer 3 Gap Summary

| Requirement | Status | Action for Phase 8.2.2 |
|---|---|---|
| Road network (link geometry) | Available (.shp, 150-link subset) ✓ | Use test_shanghai_full.xlsx |
| Traffic flow attributes | Needs field audit | Inspect .dbf columns; map to tool schema |
| Vehicle composition | Not available | Document assumed distribution |
| Emission factors | Available (MOVES via tool) ✓ | Use query_emission_factors |
| Meteorological data | Presets only (no real data) | Use presets; document limitation |
| Base map | Available (.shp) ✓ | Use for render_spatial_map |
| Ground truth validation | Not available | Explicitly scope as "demonstration" |
| Workflow script | Not written | Write in Phase 8.2.2 |

---

## §7 Phase 8.2.2 Launch Prerequisites

### §7.1 Design Decisions Requiring User Approval

Before Phase 8.2.2 (data run) can begin, the following design choices must
be explicitly approved:

**Decision 1: Baseline LLM model**
- Current: NaiveRouter uses same LLM as governed router (deepseek-v4-pro)
- Option A: Same model ✓ (isolates architecture, not model capability)
- Option B: Different model (e.g., deepseek-v4-flash for baseline) — tests
  whether governance + cheap model beats vanilla + expensive model
- **Recommendation:** Option A for Phase 8.2.2. Option B is a Phase 9 variant.

**Decision 2: Ablation scope**
- Option A: Anchors 3 branches only (AO off, graph off, constraint off)
- Option B: Anchors 3 + existing 5 (no_standardization, no_negotiation)
- **Recommendation:** Option A for Anchors paper compliance. The existing
  5 configs can be a supplementary run.

**Decision 3: AO-off implementation**
- Option A: New `ENABLE_AO_CLASSIFIER` flag (~15 LOC)
- Option B: Use NaiveRouter as AO-off proxy (overshoots — disables ALL governance)
- **Recommendation:** Option A. Option B conflates AO ablation with full
  governance removal.

**Decision 4: fast_path handling (updated Phase 8.2.1.1)**
- **New plan — Mixed approach:**
  - Main ablation runs (Runs 1–5): Force fast_path OFF via `ENABLE_FAST_PATH=false`
    flag (~5 LOC). All tasks go through governed_router for clean ablation measurement.
  - Supplementary Run 8: Compare production mode (fast_path ON) vs. ablation
    mode (fast_path OFF) on same 182-task set. Report bypass rate + metric deltas.
- **Rationale:** Clean ablation deltas (Runs 1–5) + transparency about production
  behavior (Run 8). The 5 LOC flag cost is justified.

**Decision 5: Held-out protocol**
- Option A: Run held-out only on winning configuration (prevents contamination)
- Option B: Run held-out on all configs (richer comparison, risky for paper claims)
- **Recommendation:** Option A. Held-out is the test set — use once.

**Decision 6: Shanghai case data**
- Option A: Run with existing data + documented assumptions
- Option B: Acquire real Shanghai meteorological + traffic data first
- **Recommendation:** Option A for Phase 8.2.2. Option B is a Phase 9+
  effort (external data acquisition timeline unknown).

### §7.2 Minimum Code Changes for Phase 8.2.2

| Change | LOC | Required? |
|---|---|---|
| `ENABLE_AO_CLASSIFIER` flag in config.py | ~5 | Yes (for AO-off ablation) |
| `--ablation` flag in eval_end2end.py | ~25 | No (can use eval_ablation.py wrapper) |
| Extend `runtime_overrides()` | ~10 | No (can use eval_ablation.py + env vars) |
| `--no-fast-path` flag | ~5 | Yes (required for ablation Runs 1–5) |
| AO classifier early-return | ~10 | Yes (for AO-off ablation) |
| **Total** | **~20–60 LOC** | **~20 LOC minimum** |

### §7.3 Phase 8.2.2 Run Matrix

| Run | Mode/Config | Tasks | Reps | Purpose |
|---|---|---|---|---|
| 1 | governed_router (full) | main 182 | n=3 | Primary result |
| 2 | naive_router (baseline) | main 182 | n=3 | Baseline comparison |
| 3 | no_ao ablation | main 182 | n=3 | AO contribution |
| 4 | no_graph ablation | main 182 | n=3 | Dependency graph contribution |
| 5 | no_constraint ablation | main 182 | n=3 | Constraint feedback contribution |
| 6 | governed_router (full) | held-out 75 | n=1 | Final held-out (winning config verification) |
| 7 | Shanghai e2e case | 1 workflow | n=1 | Layer 3 demonstration |
| 8 | governed_router production (fast_path ON) vs ablation (fast_path OFF) | main 182 | n=1 | fast_path bypass rate + metric delta |

**Estimated runtime:** (182 tasks × 30s avg × 3 reps × 5 configs) / 8 parallel
≈ 170 minutes for Layer 2. Held-out: 75 × 30s / 8 ≈ 5 minutes. Shanghai: ~2
minutes. Run 8: 182 × 30s × 2 / 8 ≈ 23 minutes. **Total: ~3.5 hours.**

### §7.4 Standardization Layer Priority

Layer 1 (standardization benchmark) is independent of the other layers and
can be run in parallel with Layer 2. The standardization eval takes < 1
minute (825 rule-based matches, only hard-tier tasks go to LLM). Run it
once at Phase 8.2.2 start for diagnostic value — if standardization accuracy
is low, it explains Layer 2 parameter-ambiguous failures.

---

## §8 References

- `docs/architecture/v1_freeze_reality_audit.md` §21 — Phase 8.1.8 constraint compliance (Anchors §三 Failure Mode 3)
- `docs/architecture/v1_freeze_reality_audit.md` §1–§20 — Full v1 architecture reality audit
- `core/naive_router.py` — Baseline router implementation (340 lines)
- `evaluation/eval_end2end.py` — Main evaluation runner (~2,000 lines)
- `evaluation/eval_ablation.py` — Ablation wrapper (174 lines)
- `evaluation/eval_standardization_benchmark.py` — Standardization eval (228 lines)
- `config.py:67-221` — Runtime configuration flags
- `test_data/SHANGHAI_FULL_TEST_GUIDE.md` — Shanghai test case documentation

---

## §9 Phase 8.2.1.1 Adjustments Summary

**Date:** 2026-05-03
**Status:** Design adjustment — no benchmark execution.

### §9.1 Sections Modified

| Section | Change | Task |
|---|---|---|
| §3.5 (new) | NaiveRouter LLM Config Audit — verified same LLM config as GovernedRouter via `purpose="agent"` → `config.agent_llm` path. No discrepancy found. | Task 2 |
| §3.6 (renumbered) | Former §3.5 Gap Summary | — |
| §4.2 | AO-off expected behavior: added "fast_path forced off" qualifier | Task 1 |
| §4.3 | Graph-off expected behavior: added "fast_path forced off" qualifier | Task 1 |
| §4.4 | Constraint-off expected behavior: added "fast_path forced off" qualifier | Task 1 |
| §4.6 | Added fast_path handling paragraph for ablation runs | Task 1 |
| §4.7 (new) | Expected telemetry per ablation branch — 3 new TraceStepType values needed, total ~30 LOC | Task 3 |
| §4.8 (new) | AO-off pre-sanity plan — single-task gate before full n=3 ablation | Task 4 |
| §5.3 | fast_path handling changed from Option A to mixed approach (Option B for ablations + Run 8 for prod comparison) | Task 1 |
| §7.1 Decision 4 | Updated to mixed approach with rationale | Task 1 |
| §7.2 LOC table | `--no-fast-path` flag changed from No to Yes (Required). Total min LOC: 15→20 | Task 1 |
| §7.3 Run Matrix | Added Run 8 (production vs ablation fast_path comparison). Total runtime: 3→3.5 hours | Task 1 |

### §9.2 Key Decisions Made

1. **fast_path:** Mixed approach — forced off for ablation Runs 1–5 (+5 LOC), measured in production Run 8. Clean ablation deltas + transparency about production behavior.

2. **NaiveRouter LLM:** Verified identical to GovernedRouter (same `purpose="agent"` → `config.agent_llm` → `deepseek-v4-pro`). No correction needed.

3. **Ablation telemetry:** Three new TraceStepType values required (`AO_CLASSIFIER_FORCED_NEW_AO`, `READINESS_GATING_SKIPPED`, `CROSS_CONSTRAINT_CHECK_SKIPPED`). Each ~10 LOC, same pattern as Phase 8.1.4c. These are REQUIRED for ablation data credibility.

4. **AO-off sanity gate:** Before running full 182-task n=3 AO-off ablation, a single `e2e_multi_step_001` sanity check must pass. If `AO_CLASSIFIER_FORCED_NEW_AO` trace step is absent or task behavior unchanged, STOP and diagnose.

### §9.3 Updated Phase 8.2.2 LOC Budget

| Change | LOC | Required? |
|---|---|---|
| `ENABLE_AO_CLASSIFIER` flag in config.py | ~5 | Yes (AO-off ablation) |
| `ENABLE_FAST_PATH` flag in config.py | ~5 | Yes (clean ablation for all 3 branches) |
| AO classifier early-return | ~5 | Yes (AO-off ablation) |
| Fast path gate in governed_router | ~5 | Yes (all ablation runs) |
| `AO_CLASSIFIER_FORCED_NEW_AO` trace step | ~10 | Yes (AO-off telemetry) |
| `READINESS_GATING_SKIPPED` trace step | ~10 | Yes (graph-off telemetry) |
| `CROSS_CONSTRAINT_CHECK_SKIPPED` trace step | ~10 | Yes (constraint-off telemetry) |
| `--ablation` flag in eval_end2end.py | ~25 | Optional (eval_ablation.py wrapper works) |
| Extend `runtime_overrides()` | ~10 | Optional |
| **Total** | **~45–85 LOC** | **~50 LOC minimum** |

### §9.4 Launch Prerequisites Status

All 6 decisions from §7.1 now have explicit answers:

| Decision | Resolution |
|---|---|
| 1. Baseline LLM model | Option A: Same model (deepseek-v4-pro). Verified by §3.5 audit. |
| 2. Ablation scope | Option A: Anchors 3 branches only. |
| 3. AO-off implementation | Option A: `ENABLE_AO_CLASSIFIER` flag + early return (~10 LOC). Gated by §4.8 sanity. |
| 4. fast_path handling | Mixed: forced off for ablations (Runs 1–5) + measured in production (Run 8). |
| 5. Held-out protocol | Option A: Run held-out only on winning (Run 1) configuration. |
| 6. Shanghai case data | Option A: Existing data + documented assumptions. |

**Phase 8.2.2 is unblocked.** Minimum code changes: ~50 LOC. Estimated
runtime: ~3.5 hours. User review of this §9 summary is the final gate.
