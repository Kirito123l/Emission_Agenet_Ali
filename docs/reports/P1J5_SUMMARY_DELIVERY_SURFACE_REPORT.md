# P1J5 Summary Delivery Surface Report

## 1. Summary

This round connects the already-existing high-level `chart_or_ranked_summary` intent to a real bounded delivery surface.

Implemented scope:

- Added a formal summary-delivery module in `core/summary_delivery.py`.
- Added a bounded output taxonomy:
  - `topk_summary_table`
  - `ranked_bar_chart`
  - `quick_structured_summary`
- Wired summary delivery through `core/router.py` so explicit chart/table/summary requests can resolve into actual payload delivery rather than generic follow-up wording.
- Kept readiness as the legality boundary and artifact memory as the dedup/switch-output-mode boundary.
- Recorded delivered chart/summary artifacts into artifact memory and exposed them through trace/state.
- Added frontend support for the ranked bar chart payload contract.
- Added regression coverage across unit, router-loop, trace, state, synthesis, frontend-contract, and config tests.

The target was reached with one deliberate control-layer constraint:

- explicit spatial-map requests are not auto-converted into chart delivery, even when intent resolution degrades the deliverable family to `chart_or_ranked_summary` because geometry is missing

That choice preserves the existing geometry-recovery / repairable path and avoids making the new surface behave like an uncontrolled fallback planner.

## 2. Files Changed

- `core/summary_delivery.py`
  - New bounded action-surface module.
  - Defines `SummaryDeliveryType`, `SummaryDeliveryRequest`, `SummaryDeliveryDecision`, `SummaryDeliveryContext`, `SummaryDeliveryPlan`, and `SummaryDeliveryResult`.
  - Implements delivery-type detection, bounded metric selection, Top-K ranking, CSV materialization, ranked-chart payload generation, structured-summary generation, and artifact-memory-aware repeat suppression.
- `core/router.py`
  - Adds:
    - `_build_summary_delivery_context(...)`
    - `_should_trigger_summary_delivery_surface(...)`
    - `_build_summary_delivery_synthetic_tool_result(...)`
    - `_apply_summary_delivery_surface(...)`
    - `_maybe_apply_summary_delivery_surface(...)`
  - Integrates summary delivery after intent resolution and before normal tool routing.
  - Persists `latest_summary_delivery_plan` / `latest_summary_delivery_result` into live state and cached `file_analysis`.
  - Narrows trigger semantics so direct delivery only happens for explicit chart/table/summary requests or non-spatial visualize requests, not for explicit map requests.
- `core/readiness.py`
  - Adds bounded delivery actions as first-class readiness entries:
    - `download_topk_summary`
    - `render_rank_chart`
    - `deliver_quick_structured_summary`
  - Adds `required_result_tokens` gating so these actions only become ready when an upstream result such as `emission` exists.
- `core/capability_summary.py`
  - Extends the macro-emission follow-up action surface to include chart/table/summary actions.
  - Lets capability-aware follow-up suggestions surface real executable summary/chart utterances instead of only map-oriented suggestions.
- `core/intent_resolution.py`
  - Extends `build_intent_resolution_application_plan(...)` so `chart_or_ranked_summary` and `quick_summary` can bias toward the new bounded delivery actions.
- `core/artifact_memory.py`
  - Maps the new action ids to artifact taxonomy:
    - `download_topk_summary` -> `topk_summary_table`
    - `render_rank_chart` -> `ranked_chart`
    - `deliver_quick_structured_summary` -> `quick_summary_text`
- `core/task_state.py`
  - Persists and restores:
    - `latest_summary_delivery_plan`
    - `latest_summary_delivery_result`
  - Exposes the new observability through `to_dict()`.
- `core/trace.py`
  - Adds:
    - `SUMMARY_DELIVERY_TRIGGERED`
    - `SUMMARY_DELIVERY_DECIDED`
    - `SUMMARY_DELIVERY_APPLIED`
    - `SUMMARY_DELIVERY_RECORDED`
    - `SUMMARY_DELIVERY_SKIPPED`
    - `SUMMARY_DELIVERY_FAILED`
  - Adds user-friendly trace rendering for the new surface.
- `config.py`
  - Adds:
    - `ENABLE_SUMMARY_DELIVERY_SURFACE`
    - `SUMMARY_DELIVERY_ENABLE_BAR_CHART`
    - `SUMMARY_DELIVERY_DEFAULT_TOPK`
    - `SUMMARY_DELIVERY_ALLOW_TEXT_FALLBACK`
- `web/app.js`
  - Adds ranked-bar-chart rendering and init dispatch:
    - `renderRankedBarChart(...)`
    - `renderChartCard(...)`
    - `initRankedBarChart(...)`
    - `initChartPayload(...)`
  - Keeps the existing chart rendering path but upgrades it from emission-factor-only handling to typed chart payload dispatch.
- `tests/test_summary_delivery.py`
  - New bounded unit coverage for delivery-type choice, artifact-memory switching, text fallback, and Top-K CSV materialization.
- `tests/test_router_state_loop.py`
  - Adds transcript-style regressions for:
    - visualize without geometry -> ranked chart/table delivery
    - repeated Top-K table -> switch to chart
    - quick summary -> direct structured summary delivery
  - Keeps prior intent/recovery tests stable by verifying explicit map requests still go through readiness/repair.
- `tests/test_task_state.py`
  - Adds serialization coverage for `latest_summary_delivery_plan` and `latest_summary_delivery_result`.
- `tests/test_trace.py`
  - Adds user-friendly trace coverage for summary delivery steps.
- `tests/test_capability_aware_synthesis.py`
  - Verifies the capability/follow-up surface now exposes chart and summary actions when geometry is absent.
- `tests/test_web_render_contracts.py`
  - Verifies the frontend source contract dispatches `ranked_bar_chart` payloads through render/init helpers.
- `tests/test_config.py`
  - Verifies the new feature flags and defaults.

## 3. Summary Delivery Design

### Bounded output taxonomy

The new execution surface is intentionally small:

- `topk_summary_table`
- `ranked_bar_chart`
- `quick_structured_summary`

This is enough to make `chart_or_ranked_summary` a real first-class deliverable family without turning the codebase into a general chart engine.

### Why a formal chart/summary action surface was needed

Before this round:

- intent resolution could classify a turn as `chart_or_ranked_summary`
- artifact memory could remember `topk_summary_table` / `ranked_chart`
- follow-up bias could prefer chart/summary suggestions

But there was still no stable execution path that actually turned those control-layer signals into a delivered artifact.

`core/summary_delivery.py` closes that gap with typed IR plus bounded execution:

- `build_summary_delivery_plan(...)`
  - chooses delivery type
  - chooses ranking metric
  - checks artifact-memory suppression / switching
  - checks readiness-like preconditions for emission-style row data
- `execute_summary_delivery_plan(...)`
  - materializes Top-K CSV when table delivery is chosen
  - builds chart payloads for ranked bar charts
  - builds structured textual summaries
  - emits typed artifact records

### Ranking metric selection

Metric selection is bounded and traceable:

- explicit pollutant mention in the user message wins
- otherwise current result/query context is reused
- otherwise the module falls back to a stable default metric if it is actually present

The surface does not let the LLM invent arbitrary metrics. If no stable metric exists, it either:

- falls back to `quick_structured_summary`, if `SUMMARY_DELIVERY_ALLOW_TEXT_FALLBACK` is enabled
- or fails honestly

### Why this is not a general BI system

This round does not add:

- arbitrary plot grammars
- arbitrary schema aggregation
- dashboard composition
- generic exploratory analytics

It only supports bounded ranked-summary delivery on top of already-produced analysis results, currently centered on emission-style row results.

## 4. Integration with Intent, Readiness, and Artifact-Memory

### How it accepts `chart_or_ranked_summary`

Intent resolution still decides the high-level goal. The new surface only consumes that decision under tight conditions:

- an active `IntentResolutionApplicationPlan` exists
- `progress_intent == shift_output_mode`
- the message explicitly asks for chart/table/summary output, or asks for non-spatial visualization
- there is an eligible upstream result
- readiness-like preconditions inside the summary-delivery planner are satisfied

This keeps the control split intact:

- intent resolution says what the user wants
- summary delivery says whether the bounded surface can safely deliver it now

### How readiness remains authoritative

The new actions are registered in `core/readiness.py`, but they are still bounded by required upstream results. For example:

- `render_rank_chart` is not ready unless an `emission` result exists
- `download_topk_summary` is not ready unless an `emission` result exists

The delivery surface does not bypass legality. It only materializes output when the current result context makes that safe.

### How artifact memory changes behavior

Artifact memory is now part of execution, not just follow-up dedup.

Examples:

- if `topk_summary_table` was already fully delivered, another Top-K table request can switch to `ranked_bar_chart` instead of repeating the same artifact
- if only `quick_summary_text` exists, a later chart request is treated as a legitimate output-mode shift, not a repeat
- if the same type is already fully delivered and no bounded alternative exists, the surface suppresses the repeat

That means artifact memory now influences:

- whether delivery is repeated
- whether a sibling output in the same family is chosen instead
- what gets written back after delivery

## 5. Router / Synthesis Integration

### Trigger path

The main router path is:

1. `_state_handle_input(...)`
2. intent resolution
3. `_maybe_apply_summary_delivery_surface(...)`
4. if summary delivery succeeds, the turn ends with direct bounded delivery
5. otherwise normal tool routing continues

This is intentionally not always-on. The router only direct-delivers when the turn is a genuine output request.

### Why explicit map requests are excluded

One important engineering choice was to keep explicit spatial requests out of the direct summary-delivery trigger.

Without this guard, a request like “把排放画在地图上” could be auto-converted into ranked chart delivery merely because intent resolution degraded the deliverable family after detecting missing geometry. That would undermine:

- geometry recovery
- repairable readiness behavior
- the paper’s bounded-state-transition narrative

So `_should_trigger_summary_delivery_surface(...)` now rejects direct summary delivery when the message explicitly asks for a spatial map/layer.

### How actual delivery is formed

This round does not stop at recommendations.

- `topk_summary_table`
  - generates a preview table
  - materializes a downloadable Top-K CSV file
- `ranked_bar_chart`
  - generates a typed `chart_data` payload
  - can include a paired table preview
- `quick_structured_summary`
  - generates deterministic structured summary text

The router then wraps the result as a bounded synthetic tool result named `summary_delivery_surface` so the rest of the response/artifact pipeline can treat it like a real delivered execution artifact.

### Why this is not only wording optimization

This round changes execution behavior:

- there is a new delivery planner/executor
- the router can now terminate a turn on direct chart/summary delivery
- artifact memory receives real chart/summary records
- frontend payload contracts now render ranked charts

That is a delivery surface, not a prompt tweak.

## 6. Trace

Added trace steps:

- `SUMMARY_DELIVERY_TRIGGERED`
- `SUMMARY_DELIVERY_DECIDED`
- `SUMMARY_DELIVERY_APPLIED`
- `SUMMARY_DELIVERY_RECORDED`
- `SUMMARY_DELIVERY_SKIPPED`
- `SUMMARY_DELIVERY_FAILED`

### Where they are written

- `SUMMARY_DELIVERY_TRIGGERED`
  - when the router decides the current turn should be evaluated by the bounded summary-delivery surface
- `SUMMARY_DELIVERY_DECIDED`
  - after `build_summary_delivery_plan(...)`
  - records selected delivery type, metric, top-k, and plan summary
- `SUMMARY_DELIVERY_APPLIED`
  - after execution payloads are materialized
- `SUMMARY_DELIVERY_RECORDED`
  - after artifact records are created for chart/table/summary delivery
- `SUMMARY_DELIVERY_SKIPPED`
  - when the surface is intentionally not applied or is suppressed by artifact memory
- `SUMMARY_DELIVERY_FAILED`
  - when preconditions or execution fail

### Why these traces matter for the paper

They make the new control layer legible:

- when the router chose direct bounded delivery
- why that type was selected
- when artifact memory suppressed a repeat
- when the system deliberately refused to auto-convert an explicit map request into chart delivery

That is important because otherwise the new surface would look like prompt behavior rather than explicit state-governed execution.

## 7. Tests

Ran:

```bash
pytest tests/test_summary_delivery.py tests/test_artifact_memory.py tests/test_capability_aware_synthesis.py tests/test_readiness_gating.py tests/test_task_state.py tests/test_trace.py tests/test_router_state_loop.py tests/test_file_relationship_resolution.py tests/test_supplemental_merge.py tests/test_intent_resolution.py tests/test_input_completion_transcripts.py tests/test_geometry_recovery_transcripts.py tests/test_residual_reentry_transcripts.py tests/test_web_render_contracts.py tests/test_config.py -q
```

Result:

- `170 passed`

### Key behaviors covered

- visualize without geometry can directly deliver ranked chart/table instead of forcing spatial-map suggestions
- repeated Top-K table requests can switch to chart via artifact memory
- quick summary requests can directly deliver structured summary output
- metric-missing cases do not fake ranked delivery and instead fall back or fail boundedly
- delivery artifacts are recorded into artifact memory
- state serialization preserves summary-delivery observability
- trace exposes summary-delivery decisions
- frontend source contract can render/init `ranked_bar_chart`
- explicit map requests still go through readiness / geometry-recovery behavior instead of being silently rewritten

## 8. Known Limitations

- The summary-delivery taxonomy is still bounded.
  - It only supports a small set of ranked table/chart/summary outputs.
- This is not a general charting or BI platform.
  - There is no arbitrary chart grammar, dashboarding, or user-defined aggregation system.
- The current ranked delivery path is still centered on emission-style row results.
  - It is not yet a generic adapter for every result family in the system.
- This round does not introduce scheduler, persistence, or auto replay.
  - Delivery can resume the workflow into a better output state, but it does not automatically chain the next analysis step.
- The surface does not replace readiness legality checks.
  - If the upstream result or stable ranking metric is missing, it will not fake a chart/table.

## 9. Suggested Next Step

The next most useful step is to add a bounded result-normalization layer for summary delivery inputs.

Concretely:

- keep the current summary-delivery IR and router trigger model
- add a small adapter that normalizes `emission`, `dispersion`, and `hotspot` results into one bounded ranked-summary input schema

That would let the existing chart/summary delivery surface expand to more result families without turning into a general ETL or BI subsystem.
