# P1J3 Intent Resolution Report

## 1. Summary

This round adds a bounded high-level semantic control layer for deliverable intent and progress intent resolution.

Implemented scope:

- Added a formal intent-resolution IR in `core/intent_resolution.py`.
- Added a bounded structured resolver path in `core/router.py` that runs before normal continuation / synthesis when the turn looks like a deliverable-follow-up or a recovered-workflow continuation.
- Converted the resolved intent into a formal `IntentResolutionApplicationPlan` instead of letting the LLM choose tools or mutate backend state directly.
- Applied the plan to:
  - continuation bias
  - follow-up suggestion ordering
  - clarification entry
  - bounded current-task reset for explicit new-task turns
- Added trace coverage and transcript-style regressions.

The target was reached with one important boundary choice: this layer is intentionally conservative and mainly activates in follow-up contexts with existing results, recovery context, or recovered targets. It does not replace first-turn task planning.

## 2. Files Changed

- `core/intent_resolution.py`
  - New IR module.
  - Defines `DeliverableIntentType`, `ProgressIntentType`, `IntentResolutionDecision`, `IntentResolutionContext`, `IntentResolutionParseResult`, and `IntentResolutionApplicationPlan`.
  - Implements bounded fallback classification, application-plan construction, and capability-summary biasing.
- `core/router.py`
  - Adds `_should_resolve_intent(...)`, `_resolve_deliverable_and_progress_intent(...)`, `_apply_intent_resolution_plan(...)`, `_apply_intent_bias_to_continuation_decision(...)`, and related context builders.
  - Integrates intent resolution into `_state_handle_input()` ahead of normal continuation handling.
  - Injects intent guidance into synthesis context and capability-aware follow-up construction.
  - Applies a conservative trigger boundary so the new layer does not over-fire on fresh first-turn workflow requests.
- `core/task_state.py`
  - Persists `latest_intent_resolution_decision` and `latest_intent_resolution_plan`.
  - Restores them from memory-backed file-analysis state and serializes them via `to_dict()`.
- `core/trace.py`
  - Adds `INTENT_RESOLUTION_TRIGGERED`, `INTENT_RESOLUTION_DECIDED`, `INTENT_RESOLUTION_APPLIED`, `INTENT_RESOLUTION_SKIPPED`, and `INTENT_RESOLUTION_FAILED`.
  - Adds user-friendly trace rendering for these steps.
- `core/capability_summary.py`
  - Accepts top-level `intent_bias` and uses it to reorder/suppress follow-up suggestions.
  - Lets intent resolution bias chart/summary/download suggestions without bypassing readiness.
- `config.py`
  - Adds:
    - `ENABLE_INTENT_RESOLUTION`
    - `INTENT_RESOLUTION_ALLOW_LLM_FALLBACK`
    - `INTENT_RESOLUTION_BIAS_FOLLOWUP_SUGGESTIONS`
    - `INTENT_RESOLUTION_BIAS_CONTINUATION`
- `tests/test_intent_resolution.py`
  - New unit coverage for parsing, fallback classification, and capability-summary bias application.
- `tests/test_router_state_loop.py`
  - Adds transcript-style regressions for:
    - visualize without geometry
    - recovered-target resume
    - output-mode shift
  - Also protects against over-triggering on ordinary continuation and first-turn planning.
- `tests/test_trace.py`
  - Verifies new intent-resolution trace steps.
- `tests/test_task_state.py`
  - Verifies state serialization/deserialization for the new decision and plan objects.

## 3. Intent Resolution Design

### Deliverable intent taxonomy

`DeliverableIntentType` is bounded to:

- `spatial_map`
- `chart_or_ranked_summary`
- `downloadable_table`
- `quick_summary`
- `rough_estimate`
- `scenario_comparison`
- `unknown`

This keeps the resolver focused on user-visible output forms instead of tool names.

### Progress intent taxonomy

`ProgressIntentType` is bounded to:

- `continue_current_task`
- `resume_recovered_target`
- `shift_output_mode`
- `start_new_task`
- `ask_clarify`

This is the core distinction that was missing before. A turn like “继续” and a turn like “继续，但换个方式展示” are no longer collapsed into the same continuation bucket.

### Why add LLM-guided high-level resolution

The existing stack already knew how to:

- ground files
- gate readiness
- recover missing inputs
- restore residual workflows

What it still lacked was a formal answer to:

> what deliverable does the user actually want now, and is this turn continuing, resuming, shifting output mode, or starting something new?

That answer is now produced as a bounded classification result. The LLM is used only for high-level semantic interpretation; the backend still owns action legality and state transitions.

### Why this is not tool-selection rewritten

The resolver does not return tool names as final decisions.

Instead it returns:

- deliverable intent
- progress intent
- confidence / reason
- bounded bias flags

The backend then transforms that into:

- preferred action IDs
- deprioritized action IDs
- preferred artifact kinds
- clarification requirements
- bounded task-context reset / recovered-target supersession

That keeps the layer aligned with the paper narrative: semantic control sits above readiness and execution, rather than replacing them.

## 4. Application Semantics

`build_intent_resolution_application_plan(...)` is the execution-side bridge from classification to bounded behavior.

### Deliverable bias

- `spatial_map`
  - prefers map-oriented action IDs only when the current action surface can support them.
  - does not override blocked / repairable status.
- `chart_or_ranked_summary`
  - suppresses default map bias and prefers chart/summary artifacts.
- `downloadable_table`
  - biases follow-up toward downloadable/tabular outputs instead of new analysis tools.
- `quick_summary`
  - suppresses default residual continuation when the user clearly wants a different presentation form.

### Progress bias

- `continue_current_task`
  - can keep the residual workflow authoritative when existing continuation logic was too weak.
- `resume_recovered_target`
  - biases toward the recovered/re-entry target, but does not auto-execute it.
  - preserves geometry-recovery continuation signals when they are already authoritative.
- `shift_output_mode`
  - suppresses default residual continuation unless the next residual step already matches the requested deliverable bias.
- `start_new_task`
  - performs bounded state reset of repair/completion/recovery context without destructive global clearing.
- `ask_clarify`
  - enters bounded clarification instead of guessing.

### Readiness / re-entry / follow-up coordination

This layer does not replace readiness.

- intent resolution decides what the turn is more like
- readiness still decides what is currently legal / ready / repairable / blocked
- re-entry logic still owns recovered-target semantics
- capability-aware synthesis and follow-up builders consume the bias and surface the most aligned next move

This is why “帮我可视化一下” with emission results but no geometry now biases toward ranked/chart-style follow-up instead of mechanically pushing `render_spatial_map`.

## 5. Router Integration

### Trigger timing

Intent resolution is integrated early in `_state_handle_input()`, after current file grounding but before ordinary continuation injection and tool-facing context assembly.

### Trigger conditions

`_should_resolve_intent(...)` is intentionally conservative. It triggers when:

- the user asks for a deliverable/output form and there is follow-up context:
  - existing result tokens
  - geometry recovery context
  - recovered/re-entry target
  - supplemental merge result
- the user sends a continuation-like turn while a recovered target or geometry-recovery context exists

It does not trigger for:

- ordinary parameter confirmations
- input-completion replies
- file-upload turns already handled by file-relationship resolution
- plain residual-plan continuation without recovery context
- fresh first-turn workflow requests that merely mention outputs like “地图”

That last constraint matters. During implementation, broad triggering caused extra classification calls on first-turn planning requests and generic residual continuations. The final integration narrows the layer to where it adds semantic value without perturbing planning.

### Application path

When triggered, the router now:

1. builds `IntentResolutionContext`
2. calls `_resolve_deliverable_and_progress_intent(...)`
3. parses or falls back to a bounded `IntentResolutionDecision`
4. builds `IntentResolutionApplicationPlan`
5. applies it through `_apply_intent_resolution_plan(...)`
6. continues through the existing state loop

### Why it does not replace readiness / continuation

The resolver does not:

- auto-select the final tool
- auto-execute the recovered target
- auto-replan the workflow
- bypass blocked / repairable status

It only biases existing bounded mechanisms.

## 6. Trace

Added trace steps:

- `INTENT_RESOLUTION_TRIGGERED`
- `INTENT_RESOLUTION_DECIDED`
- `INTENT_RESOLUTION_APPLIED`
- `INTENT_RESOLUTION_SKIPPED`
- `INTENT_RESOLUTION_FAILED`

These are emitted in `core/router.py` along the intent-resolution path and rendered in `core/trace.py`.

Recorded fields include:

- trigger reason
- context summary
- deliverable intent
- progress intent
- confidence and reason
- application plan
- clarification entry
- bias preview / guidance preview

Why this matters for the paper:

- it makes the high-level semantic controller inspectable
- it distinguishes “semantic interpretation” from “execution decision”
- it shows when the controller was deliberately skipped, which is as important as when it fired

## 7. Tests

Executed:

```bash
pytest tests/test_intent_resolution.py tests/test_task_state.py tests/test_trace.py tests/test_router_state_loop.py tests/test_file_relationship_resolution.py tests/test_supplemental_merge.py tests/test_input_completion_transcripts.py tests/test_geometry_recovery_transcripts.py tests/test_residual_reentry_transcripts.py -q
```

Result:

- `128 passed`

Newly covered behaviors include:

- visualize-without-geometry prefers `chart_or_ranked_summary` instead of forcing map bias
- visualize-with-geometry can bias toward `spatial_map` without bypassing readiness
- downloadable follow-ups are recognized as output intent rather than new tasks
- plain “继续” in recovered-target context biases resume
- “继续，但换个方式展示” becomes `shift_output_mode`
- ambiguous or low-context turns remain conservative
- geometry-recovery continuation signals are preserved when intent resolution agrees with the same resumed target
- fresh first-turn planning and generic residual continuation do not trigger extra intent-resolution passes

## 8. Known Limitations

- Deliverable/progress intent is still a bounded taxonomy, not an open-ended conversation manager.
- The resolver does not introduce scheduler, persistence, auto replay, or automatic multi-step orchestration.
- Readiness legality checks remain authoritative; intent bias cannot override them.
- The layer currently focuses on follow-up and restoration contexts. It does not act as a general first-turn task planner.
- Deliverable intent biases existing action IDs and suggestion artifacts; it does not yet manage a richer artifact inventory beyond the current capability-summary surface.

## 9. Suggested Next Step

Add a bounded artifact-memory layer that records which result forms have already been delivered in a more explicit typed inventory, then let intent resolution bias against redundant deliverables with finer granularity than the current `already_provided` summary.
