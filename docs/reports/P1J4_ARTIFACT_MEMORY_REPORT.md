# P1J4 Artifact Memory Report

## 1. Summary

This round adds a bounded artifact-memory layer above readiness and intent resolution.

Implemented scope:

- Added a formal artifact-memory IR in `core/artifact_memory.py`.
- Recorded delivered artifacts at actual response delivery points instead of relying on free-form LLM claims.
- Persisted artifact memory through `TaskState` and `file_analysis` memory payloads so follow-up turns can see prior deliverables.
- Upgraded readiness `already_provided` from current-turn payload heuristics to artifact-memory-aware detection across turns.
- Fed artifact memory into intent context, capability summary, and follow-up suggestion biasing.
- Added trace coverage and regression tests.

The target was reached with one important engineering boundary: the current codebase still does not have a standalone chart-generation action in the follow-up action surface. Because of that, this round focuses on structured deliverable tracking, cross-turn deduplication, and output-mode biasing, rather than inventing new artifact-producing actions.

## 2. Files Changed

- `core/artifact_memory.py`
  - New bounded artifact-memory module.
  - Defines `ArtifactType`, `ArtifactFamily`, `ArtifactRecord`, `ArtifactMemoryState`, `ArtifactAvailabilityDecision`, and `ArtifactSuggestionPlan`.
  - Implements deterministic delivery classification, memory updates, repeat detection, and follow-up bias planning.
- `core/router.py`
  - Adds delivery-side recording through `_record_delivered_artifacts(...)`.
  - Persists artifact memory into the active state and cached `file_analysis`.
  - Reuses artifact memory in readiness, intent context, and capability-summary construction.
  - Applies artifact-memory-driven follow-up suppression and trace emission.
  - Fixes memory persistence fallback so follow-up turns without a fresh upload still write back `file_analysis`.
- `core/task_state.py`
  - Persists `artifact_memory_state`.
  - Restores it from `file_analysis`.
  - Exposes `artifact_memory_summary`, `latest_artifact_by_family`, `latest_artifact_by_type`, and `recent_delivery_summary`.
- `core/readiness.py`
  - Extends `_collect_already_provided_artifacts(...)` and `build_readiness_assessment(...)` with artifact-memory input.
  - Maps full artifact-memory records into readiness `already_provided` affordances across turns.
- `core/capability_summary.py`
  - Accepts artifact-memory-aware summaries.
  - Renders artifact-memory bias in the bounded synthesis prompt.
  - Suppresses repeated follow-up suggestions via `artifact_bias`.
- `core/trace.py`
  - Adds `ARTIFACT_RECORDED`, `ARTIFACT_MEMORY_UPDATED`, `ARTIFACT_ALREADY_PROVIDED_DETECTED`, `ARTIFACT_SUGGESTION_BIAS_APPLIED`, and `ARTIFACT_MEMORY_SKIPPED`.
  - Adds user-friendly rendering for these steps.
- `config.py`
  - Adds:
    - `ENABLE_ARTIFACT_MEMORY`
    - `ARTIFACT_MEMORY_TRACK_TEXTUAL_SUMMARY`
    - `ARTIFACT_MEMORY_DEDUP_BY_FAMILY`
    - `ARTIFACT_MEMORY_BIAS_FOLLOWUP`
- `tests/test_artifact_memory.py`
  - New bounded unit coverage for classification, repeat detection, family/type distinction, and suggestion bias.
- `tests/test_router_state_loop.py`
  - Adds cross-turn persistence and readiness regressions for artifact memory.
- `tests/test_trace.py`
  - Verifies new artifact-memory trace rendering.
- `tests/test_task_state.py`
  - Verifies artifact-memory serialization through `TaskState`.
- `tests/test_config.py`
  - Verifies new artifact-memory feature flags.

## 3. Artifact Memory Design

### Artifact taxonomy

`ArtifactType` is intentionally bounded to the output forms the current system actually surfaces:

- `detailed_csv`
- `topk_summary_table`
- `ranked_chart`
- `spatial_map`
- `dispersion_map`
- `hotspot_map`
- `quick_summary_text`
- `comparison_result`
- `unknown`

`ArtifactFamily` is deliberately coarser:

- `downloadable_table`
- `ranked_summary`
- `spatial_visualization`
- `textual_summary`
- `comparison_output`

### Type/family distinction

This split matters because the system now distinguishes:

- exact-repeat requests
  - for example `detailed_csv` after a full CSV export was already delivered
- same-family but different-type follow-ups
  - for example `topk_summary_table` already exists, but `ranked_chart` is still a legitimate “switch output mode” continuation

The core records live in:

- `ArtifactRecord`
  - one delivered artifact instance with `artifact_type`, `artifact_family`, source action/tool, turn index, delivery status, and bounded metadata
- `ArtifactMemoryState`
  - the full bounded artifact memory for the active workflow, including:
    - `artifacts`
    - `latest_by_family`
    - `latest_by_type`
    - `recent_artifact_summary`

### Why bounded artifact memory instead of scattered flags

The old readiness surface could only answer a narrow current-turn question:

> is this exact artifact-equivalent action already in the payload I just built?

That was not enough for:

- cross-turn duplicate suppression
- partial-vs-full delivery tracking
- same-family/different-type follow-up control
- intent-aware “switch output mode” handling

`core/artifact_memory.py` solves this with typed IR and deterministic classification rather than accumulating more ad hoc booleans in router state.

## 4. Integration with Intent and Readiness

### Deliverable/progress intent coordination

Intent resolution still answers:

- what output form the user wants
- whether they are continuing, resuming, shifting output mode, or starting a new task

Artifact memory now answers:

- what has already been delivered
- whether that delivery was full or partial
- whether the current turn is asking for an exact repeat or a new form in the same family

The main execution-side bridge is `build_artifact_suggestion_plan(...)`, which turns:

- `ArtifactMemoryState`
- current capability summary
- current `IntentResolutionApplicationPlan`

into bounded bias:

- `suppressed_action_ids`
- `promoted_families`
- `repeated_artifact_types`
- `repeated_artifact_families`
- a short `user_visible_summary`

### Readiness / `already_provided` coordination

`build_readiness_assessment(...)` now accepts artifact memory and uses it inside `_collect_already_provided_artifacts(...)`.

That means `already_provided` is no longer limited to “this payload already contains a download/map/chart”.

It can now also detect:

- a full CSV delivered in a previous turn
- a map delivered in a previous turn
- a chart delivered in a previous turn

while still preserving the bounded legality contract:

- readiness remains the final legality boundary
- artifact memory only enriches `already_provided`, it does not bypass blocked/repairable checks

### Follow-up suggestion effect

`_build_capability_summary_for_synthesis(...)` now combines:

1. readiness
2. intent bias
3. artifact-memory bias

This is the path that suppresses repeated same-type suggestions and prefers genuinely new output forms.

## 5. Router / Synthesis Integration

### Where artifacts are recorded

Artifacts are recorded in `core/router.py` by `_record_delivered_artifacts(...)`, which runs from `_state_build_response(...)` after the response payload is actually assembled.

This was a deliberate boundary choice:

- artifacts are recorded from real delivery payloads
  - `download_file`
  - `table_data`
  - `chart_data`
  - `map_data`
  - bounded textual summaries
- the system does not trust the LLM to self-report delivery

### Where artifacts are consumed

Artifacts are consumed in three places:

- readiness
  - cross-turn `already_provided`
- intent resolution context
  - `delivered_artifacts` now prefers bounded artifact-memory summaries when available
- capability summary / follow-up builder
  - repeated suggestions are suppressed and new-family output forms are promoted

### Why this is not simple wording optimization

This round is not just “say don’t repeat CSV”.

The behavior is now driven by:

- formal memory state in `TaskState`
- persisted `file_analysis["artifact_memory"]`
- readiness affordances
- bounded follow-up bias application
- explicit trace steps

That is a state-governance change, not a prompt-only change.

## 6. Trace

Added trace steps:

- `ARTIFACT_RECORDED`
- `ARTIFACT_MEMORY_UPDATED`
- `ARTIFACT_ALREADY_PROVIDED_DETECTED`
- `ARTIFACT_SUGGESTION_BIAS_APPLIED`
- `ARTIFACT_MEMORY_SKIPPED`

### Where they are emitted

- `ARTIFACT_RECORDED`
  - once each bounded artifact is materialized from the delivered response
- `ARTIFACT_MEMORY_UPDATED`
  - after the state-level artifact memory is updated
- `ARTIFACT_ALREADY_PROVIDED_DETECTED`
  - when readiness or capability-summary bias detects a repeated deliverable
- `ARTIFACT_SUGGESTION_BIAS_APPLIED`
  - when follow-up bias suppresses repeated suggestions or promotes a new family
- `ARTIFACT_MEMORY_SKIPPED`
  - when no bounded artifact should be tracked for the turn

### Why these traces matter for the paper

They make the new layer auditable in exactly the way the prior rounds required:

- semantic intent is no longer a black box
- deliverable tracking is no longer implicit
- repeated-output suppression can be explained from structured state rather than hidden heuristics

## 7. Tests

Ran:

```bash
pytest tests/test_artifact_memory.py tests/test_capability_aware_synthesis.py tests/test_readiness_gating.py tests/test_task_state.py tests/test_trace.py tests/test_router_state_loop.py tests/test_file_relationship_resolution.py tests/test_supplemental_merge.py tests/test_intent_resolution.py tests/test_input_completion_transcripts.py tests/test_geometry_recovery_transcripts.py tests/test_residual_reentry_transcripts.py -q
```

Result:

- `148 passed`

### New or expanded coverage

- `tests/test_artifact_memory.py`
  - delivery classification
  - exact-repeat detection
  - same-family/different-type handling
  - partial textual-summary expansion bias
- `tests/test_router_state_loop.py`
  - artifact memory is persisted into `file_analysis`
  - cross-turn readiness marks `download_detailed_csv` as `already_provided`
- `tests/test_trace.py`
  - artifact-memory trace steps render correctly
- `tests/test_task_state.py`
  - artifact-memory serialization/deserialization through `TaskState`
- `tests/test_config.py`
  - new feature flags default correctly

Existing neighboring suites were also rerun to check that readiness, intent resolution, file relationship resolution, supplemental merge, geometry recovery, and residual re-entry still behave.

## 8. Known Limitations

- The artifact taxonomy is still bounded.
  - It only models the current system’s high-value deliverable surface.
- This is not a general memory system.
  - It tracks delivered artifacts for the active workflow, not arbitrary long-horizon knowledge.
- It does not introduce scheduler / persistence / auto replay semantics.
  - Artifact memory changes follow-up control and readiness deduplication only.
- It still does not replace readiness legality checks.
  - A requested output can still be blocked or repairable even if intent bias prefers it.
- The current action surface still lacks a standalone chart-generation tool.
  - As a result, same-family/different-type reasoning is already modeled in memory and suggestion bias, but it cannot invent new executable chart actions that do not exist in the runtime action catalog.

## 9. Suggested Next Step

The highest-value next step is:

- add one bounded chart/summary delivery action surface that is explicitly mapped to `ranked_chart` / `topk_summary_table`

Why this is the most realistic next step:

- intent resolution already knows when the user wants `chart_or_ranked_summary`
- artifact memory now knows whether that family/type has already been delivered
- readiness and follow-up bias now know how to suppress repeats and promote family shifts

What is still missing is one execution-side action that lets the system turn those biases into a first-class, non-spatial deliverable path rather than only a better suppression/guidance layer.
