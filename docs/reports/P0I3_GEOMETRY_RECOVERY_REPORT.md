# P0I3 Geometry Recovery Report

## 1. Summary

This round implemented a bounded geometry completion recovery path for `missing_geometry` repairable actions.

- Supporting spatial files uploaded through structured input completion are now materialized as formal backend objects instead of being left as a raw conversational attachment reference.
- The router now performs a bounded re-grounding step against the current primary file plus one supporting spatial file.
- Readiness is refreshed after geometry remediation, and the repaired workflow becomes resumable again without introducing scheduler semantics or automatic chain replay.

The target was met for the scoped backend path:

- `missing_geometry` no longer stops at completion-context attachment.
- supporting spatial inputs are formally represented and serialized.
- bounded re-grounding updates file context with geometry-support facts.
- readiness refresh is explicit and traceable.
- recovery success restores resumability, but does not auto-execute downstream tools.

## 2. Files Changed

- `core/geometry_recovery.py`
  Added the bounded recovery model layer:
  `SupportingSpatialInput`, `GeometryRecoveryContext`, `GeometryReGroundingResult`, geometry capability inference, recovery context construction, and file-aware re-grounding helpers.

- `core/router.py`
  Integrated geometry recovery into the input completion path, live input-completion bundle, readiness refresh, geometry-aware continuation, bounded resume behavior, and geometry-specific traces.

- `core/task_state.py`
  Added observability for supporting spatial input, geometry recovery context, recovery status, readiness refresh result, and richer file-context fields (`spatial_context`, `dataset_roles`, `spatial_metadata`, `missing_field_diagnostics`, `selected_primary_table`).

- `core/trace.py`
  Added geometry recovery trace step types and user-friendly trace formatting.

- `core/readiness.py`
  Extended geometry-support detection so `spatial_context.mode == supporting_spatial_input` becomes a canonical geometry support source during readiness refresh.

- `tools/file_analyzer.py`
  Extended bounded analyzer support to direct `.geojson/.json` and `.shp` inputs and reused the existing rule-first grounding path for supporting spatial files.

- `config.py`
  Added `ENABLE_GEOMETRY_RECOVERY_PATH`, `GEOMETRY_RECOVERY_SUPPORTED_FILE_TYPES`, and `GEOMETRY_RECOVERY_REQUIRE_READINESS_REFRESH`.

- `tests/test_geometry_recovery.py`
  Added unit coverage for formal supporting-spatial attach, re-grounding success, re-grounding failure, and bounded recompute recommendation.

- `tests/test_geometry_recovery_transcripts.py`
  Added transcript-style regressions for successful geometry remediation and failed/irrelevant supporting-file uploads.

- `tests/test_router_state_loop.py`
  Added router integration coverage for geometry completion recovery, residual workflow preservation, and explicit new-task override.

- `tests/test_trace.py`
  Added friendly-trace coverage for all geometry recovery trace types.

- `tests/test_task_state.py`
  Added serialization coverage for geometry recovery observability.

- `tests/test_config.py`
  Added config default coverage for the new geometry recovery flags.

## 3. Geometry Recovery Design

### Supporting spatial input representation

`core/geometry_recovery.py` introduces `SupportingSpatialInput` with:

- `file_ref`
- `file_name`
- `file_type`
- `source`
- `geometry_capability_summary`
- `dataset_roles`
- `spatial_metadata`

This is the formal, bounded representation used after `upload_supporting_file` is chosen in a `missing_geometry` completion flow.

### Re-grounding context

`GeometryRecoveryContext` captures:

- `primary_file_ref`
- `supporting_spatial_input`
- `target_action_id`
- `target_task_type`
- `residual_plan_summary`
- `recovery_status`
- `re_grounding_notes`
- readiness before/after summaries
- bounded resume and recompute hints

The design is intentionally pairwise:

- one primary file
- one supporting spatial file
- one active recovery target

No general multi-file graph or GIS fusion layer was introduced.

### Readiness refresh logic

The recovery path does not assume success from upload alone.

After re-grounding:

- the primary file context is augmented with a bounded `spatial_context`
- `build_readiness_assessment(...)` is rerun
- the original target action is checked again
- the before/after delta is stored in state and traces

If the supporting file does not expose usable geometry support, the flow remains in `NEEDS_INPUT_COMPLETION`.

### Why this is bounded recovery, not a scheduler

The new path only does:

- attach supporting file
- bounded file-aware re-grounding
- readiness refresh
- resumability restoration

It explicitly does not:

- auto-execute the target tool
- replay the whole residual workflow
- recompute upstream tools automatically
- introduce a general GIS integration engine

## 4. Router Integration

### How `missing_geometry` completion enters the recovery path

In `core/router.py`, `_handle_active_input_completion(...)` now special-cases:

- `reason_code == missing_geometry`
- selected option type `UPLOAD_SUPPORTING_FILE`

That path now:

1. validates the supporting file type against `GEOMETRY_RECOVERY_SUPPORTED_FILE_TYPES`
2. analyzes the supporting file through the existing analyzer/fallback path
3. builds `SupportingSpatialInput`
4. builds `GeometryRecoveryContext`
5. calls `re_ground_with_supporting_spatial_input(...)`
6. refreshes readiness
7. either reopens completion on failure or marks the workflow resumable on success

### How current-task recovery works after success

On success, the router:

- stores the re-grounded file context in the live completion bundle
- keeps residual workflow state intact
- records a geometry recovery context with status `resumable`
- stores a bounded resume hint and upstream recompute recommendation
- returns a user-facing response stating that the workflow is resumable

The current turn stops there.

### Why there is no automatic replay

Success transitions to a resumable/done state rather than immediately selecting/executing tools again.

That preserves the bounded philosophy:

- the upload turn repairs context
- the next turn can continue the workflow
- no scheduler semantics are introduced inside the repair turn

## 5. Readiness / Resume Interaction

Geometry recovery affects readiness through the new bounded `spatial_context` injected into the primary file context.

That lets readiness see:

- geometry support is now available
- the support source is `supporting_spatial_input`
- the target action may move from `repairable` to `ready`

When success occurs:

- `geometry_readiness_refresh_result` stores the before/after delta
- the residual workflow stays authoritative if one exists
- a geometry-aware continuation path can resume the recovered residual workflow on the next turn even when general repair-aware continuation is not enabled

This keeps residual workflow ownership intact rather than letting fresh template recommendation or fresh planning override it.

## 6. Trace Extensions

New trace step types:

- `GEOMETRY_COMPLETION_ATTACHED`
- `GEOMETRY_RE_GROUNDING_TRIGGERED`
- `GEOMETRY_RE_GROUNDING_APPLIED`
- `GEOMETRY_RE_GROUNDING_FAILED`
- `GEOMETRY_READINESS_REFRESHED`
- `GEOMETRY_RECOVERY_RESUMED`

Where they are written:

- attach trace is written as soon as the uploaded supporting file becomes `SupportingSpatialInput`
- re-grounding triggered/applied/failed traces are written inside the geometry recovery helper path in `core/router.py`
- readiness refreshed is written after the post-recovery readiness assessment
- recovery resumed is written only when the workflow becomes resumable again without auto-execution

Why these traces matter for the paper:

- they show that geometry remediation is formal rather than ad hoc conversation
- they make the support-file-aware re-grounding step auditable
- they expose readiness delta and bounded resume semantics clearly enough for appendix/artifact examples

## 7. Tests

Commands run:

- `pytest -q tests/test_geometry_recovery.py tests/test_geometry_recovery_transcripts.py tests/test_trace.py tests/test_task_state.py tests/test_config.py tests/test_router_state_loop.py -q`
- `pytest -q tests/test_input_completion.py tests/test_input_completion_transcripts.py tests/test_readiness_gating.py -q`
- `python -m py_compile core/router.py core/task_state.py core/geometry_recovery.py core/trace.py tools/file_analyzer.py core/readiness.py config.py`

Results:

- targeted pytest set: `102 passed`
- adjacent completion/readiness regression set: `12 passed`
- `py_compile`: passed

New coverage added:

- formal supporting spatial attach
- re-grounding success
- re-grounding failure
- bounded recompute recommendation without scheduler behavior
- router recovery path after `missing_geometry`
- residual workflow preservation after geometry recovery
- explicit new-task override over active geometry recovery context
- geometry trace formatting
- task-state geometry recovery observability
- transcript-style success/failure recovery paths

## 8. Known Limitations

- no full workflow replay was introduced
- no durable persistence or cross-restart resume was introduced
- only bounded supporting-file-aware geometry recovery is supported
- no general GIS integration engine was introduced
- recovery still depends on supporting file quality and the bounded re-grounding logic
- direct shapefile handling still depends on the runtime geospatial stack being available

## 9. Suggested Next Step

Add a small bounded residual-step re-entry controller for geometry-recovered workflows so the post-recovery next turn can deterministically prefer the recovered target action without expanding into multi-step auto replay.
