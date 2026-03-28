# P1J2 Supplemental Column Merge Report

## 1. Summary
This round turns the already-classified `merge_supplemental_columns` relationship into a real bounded execution path.

The implemented path now does all of the following:

- models the upload as a formal supplemental merge case instead of stopping at relationship recognition
- builds a bounded merge plan through deterministic key alignment
- imports only columns that target the current missing canonical fields
- materializes a merged primary CSV artifact for downstream execution
- refreshes grounding, `missing_field_diagnostics`, and readiness after the merge
- restores the current workflow to a resumable/actionable state when readiness becomes `ready`
- stays bounded: no scheduler, no auto replay, no general ETL engine

The target for this round was reached. The system now supports the full control chain:

`merge_supplemental_columns` relationship decision -> bounded merge plan -> materialized merged dataset -> diagnostics/readiness refresh -> resumable workflow state

## 2. Files Changed
- `core/supplemental_merge.py`
  Added the formal supplemental merge IR plus deterministic planner/executor.
- `core/router.py`
  Replaced the old merge placeholder with the real merge path, wired in diagnostics/readiness refresh, and added resumable workflow recovery and trace emission.
- `core/task_state.py`
  Added observability fields for latest merge plan/result so the state loop and memory payload can expose merge-side recovery state.
- `core/trace.py`
  Added dedicated supplemental merge trace step types and user-facing formatting.
- `core/file_relationship_resolution.py`
  Adjusted `merge_supplemental_columns` transition semantics so merge no longer halts immediately and can precisely supersede stale completion state.
- `config.py`
  Added feature flags for merge enablement, alias-key matching, and mandatory readiness refresh.
- `tests/test_supplemental_merge.py`
  Added direct tests for plan building, key alignment, materialization, and post-merge diagnostics refresh.
- `tests/test_router_state_loop.py`
  Added transcript-style regressions for successful merge, failed key alignment, and memory update to the merged primary artifact.
- `tests/test_trace.py`
  Added user-facing trace coverage for the new supplemental merge steps.
- `tests/test_task_state.py`
  Added serialization coverage for merge observability state.
- `P1J2_SUPPLEMENTAL_COLUMN_MERGE_REPORT.md`
  Added this implementation report.

## 3. Merge Path Design
The merge IR lives in `core/supplemental_merge.py`.

Formal objects added:

- `SupplementalMergeKey`
- `SupplementalColumnAttachment`
- `SupplementalMergePlan`
- `SupplementalMergeResult`
- `SupplementalMergeContext`

All of them support stable `to_dict()` serialization, and the main IR classes also support `from_dict(...)`.

### Merge Key Selection
The planner is deterministic and bounded.

`build_supplemental_merge_plan(...)` uses this order:

1. grounded canonical identifier reuse
   - if file grounding already mapped a source column to canonical `link_id`, reuse it first
2. exact bounded identifier alias match
   - e.g. `segment_id`, `link_id`
3. bounded alias fallback
   - e.g. `segment_id` vs `seg_id`

The alignment stays conservative:

- only identifier-like columns are considered
- no fuzzy row linkage is used
- duplicate supplemental keys fail the plan
- if no reliable key is found, the merge path stops with clarification instead of pretending success

### Import Columns and Canonical Targets
The planner does not import the whole supplemental table.

It starts from the primary file’s current `missing_field_diagnostics`, extracts unresolved canonical fields, and then only looks for supplemental columns that can satisfy those missing targets.

Current bounded targets are driven by:

- primary `missing_field_diagnostics`
- current task type
- supplemental `column_mapping` / `macro_mapping` / `micro_mapping`
- a small deterministic alias set for canonical fields like `traffic_flow_vph` and `avg_speed_kph`

This keeps the merge task-directed rather than turning it into a free-form join or ETL pipeline.

### Why This Is Bounded Merge, Not General ETL
The implementation intentionally does not attempt:

- arbitrary schema matching
- arbitrary join graph search
- fuzzy record linkage
- multi-file merge orchestration
- geometry/data fusion

Execution is limited to a single primary tabular file plus one supplemental tabular file, with a single bounded key path and bounded canonical target import.

## 4. Router Integration
The execution entry is in `core/router.py`, inside `_state_handle_input()`.

Flow now is:

1. file relationship resolution classifies the upload as `merge_supplemental_columns`
2. `_apply_file_relationship_transition(...)` performs precise state invalidation/preservation
3. `_handle_supplemental_merge(...)` builds `SupplementalMergeContext`
4. `build_supplemental_merge_plan(...)` selects the key and target columns
5. `execute_supplemental_merge(...)` materializes a merged primary CSV
6. router re-analyzes the merged artifact
7. `apply_supplemental_merge_analysis_refresh(...)` patches diagnostics so partial coverage does not get mislabeled as fully ready
8. router refreshes readiness and decides whether the workflow became resumable/actionable

Important integration choices:

- merge uses the prior file-relationship decision as the only trigger; it does not bypass that control layer
- merge supersedes stale pending completion, but does not blunt-reset the whole session
- old primary-field completion overrides are cleared precisely; unrelated geometry-support context can remain
- merged output becomes the new primary file reference for memory and future execution

### Why There Is No Auto Replay
Even after a successful merge, the router stops the turn after rebuilding grounded state and readiness.

That is deliberate:

- current workflow becomes resumable or explicitly still repairable
- downstream tools are not auto-executed
- no scheduler or replay engine is introduced in this round

One implementation note that matters for the paper narrative:

- merge recovery currently reuses the existing residual continuation bundle rather than adding a new merge-specific re-entry controller
- this keeps the code realistic and small, but it also means merge recovery does not get a new dedicated re-entry IR the way geometry recovery does

## 5. Diagnostics / Readiness Refresh
This round does not stop at “columns were merged”.

After materialization, router:

1. re-runs file grounding on the merged artifact
2. calls `apply_supplemental_merge_analysis_refresh(...)`
3. patches `missing_field_diagnostics` with merge coverage facts
4. re-runs readiness through `_build_readiness_assessment(..., purpose=\"input_completion_recheck\")`

The diagnostics patch step is important because raw re-grounding would otherwise over-credit a partially populated merged column as fully resolved just because the column now exists.

The refresh logic therefore distinguishes:

- full coverage: canonical field becomes `present`
- partial coverage: canonical field becomes `partial_merge`
- zero aligned values: canonical field remains unresolved

Readiness is then evaluated from the refreshed diagnostics, not from naive column existence.

Workflow actionability is judged from the refreshed affordance:

- if target action becomes `ready`, the workflow is marked resumable/actionable
- if it remains `repairable` or `blocked`, the system returns a bounded explanation and does not fake recovery

## 6. Trace
New trace steps:

- `SUPPLEMENTAL_MERGE_TRIGGERED`
- `SUPPLEMENTAL_MERGE_PLANNED`
- `SUPPLEMENTAL_MERGE_APPLIED`
- `SUPPLEMENTAL_MERGE_FAILED`
- `SUPPLEMENTAL_MERGE_READINESS_REFRESHED`
- `SUPPLEMENTAL_MERGE_RESUMED`

Where they are written:

- `_handle_supplemental_merge(...)` writes all merge-side trace steps
- `core/trace.py` exposes user-friendly formatting for them

Recorded information includes:

- primary/supplemental file summary
- missing canonical targets
- chosen merge key
- import columns
- canonical targets
- materialized merged file path
- post-merge diagnostics summary
- readiness before/after
- whether the workflow became resumable/actionable

Why this matters for the paper:

- it makes the merge path auditable as a separate control layer, not just a hidden data mutation
- it shows the boundary between semantic relationship classification and bounded backend execution
- it surfaces “merge success but readiness still not ready” as an explicit observable outcome

## 7. Tests
Added/extended tests:

- `tests/test_supplemental_merge.py`
- `tests/test_router_state_loop.py`
- `tests/test_trace.py`
- `tests/test_task_state.py`

Direct merge behavior now covered:

- successful `segment_id` key alignment
- alias key alignment (`segment_id` vs `seg_id`)
- no reliable key failure
- missing target-field failure
- materialized merged CSV output
- partial coverage diagnostics staying unresolved

Transcript-style behavior now covered:

- “这是补充流量表” triggers real merge execution
- “把这个表并到当前文件里” fails safely when key alignment is not reliable
- merged artifact becomes the persisted primary file in `_run_state_loop()`

Commands run:

```bash
pytest tests/test_supplemental_merge.py tests/test_task_state.py tests/test_trace.py tests/test_router_state_loop.py tests/test_file_relationship_resolution.py tests/test_input_completion_transcripts.py tests/test_geometry_recovery_transcripts.py tests/test_residual_reentry_transcripts.py -q
```

Result:

- `118 passed`

## 8. Known Limitations
This round is still intentionally bounded.

Explicit limitations:

- only bounded key-based supplemental merge is supported
- only one primary tabular file plus one supplemental tabular file is supported
- current execution path is limited to CSV/Excel materialization
- no general ETL engine or arbitrary join planner was added
- no fuzzy row linkage or record matching is used
- no geometry merge is implemented here; that remains under geometry recovery
- still no scheduler, persistence, or auto replay

Also important:

- import selection currently focuses on direct grounded/alias-mapped columns
- this round does not yet execute bounded derived transforms like `m/s -> km/h` during supplemental merge

## 9. Suggested Next Step
Extend `SupplementalColumnAttachment` and the merge executor with a very small bounded transform layer for already-signaled derivations.

Most realistic next target:

- support deterministic transforms that the current analyzer already hints at, especially speed unit normalization such as `m/s -> avg_speed_kph`

Reason:

- the current merge path already has formal planning, materialization, diagnostics refresh, and readiness recovery
- the highest-leverage remaining gap is not orchestration, but bounded execution of obvious derived imports that are already surfaced by existing file diagnostics
