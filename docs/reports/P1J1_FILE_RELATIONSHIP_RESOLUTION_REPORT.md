# P1J1 File Relationship Resolution Report

## 1. Summary
This round adds a bounded `LLM-guided file relationship resolver` plus `backend-controlled state transition` path.

The new control layer classifies the relationship between a new upload and the current workflow as one of:

- `replace_primary_file`
- `attach_supporting_file`
- `merge_supplemental_columns`
- `continue_with_current_file`
- `ask_clarify`

The result is no longer just a natural-language interpretation. It is converted into a formal `FileRelationshipTransitionPlan` and applied inside `core/router.py` before normal continuation / grounding / readiness / completion logic runs.

The implementation reaches the intended goal for this round:

- LLM handles high-level semantic relationship judgment.
- Backend handles bounded state migration.
- New uploads no longer force a blunt reset.
- Old `input_completion_overrides`, pending completion, geometry recovery context, and residual re-entry are now invalidated or preserved selectively.

## 2. Files Changed
Files changed for this task:

- `core/file_relationship_resolution.py`
  Added the formal IR, bounded parser, fallback classifier, and transition planner.
- `core/router.py`
  Integrated the resolver into `_state_handle_input()`, added trigger / resolve / apply helpers, added a live relationship bundle, reused upload analysis during grounding, and fixed memory persistence so `active_file` follows the resolved primary file rather than the raw uploaded file.
- `core/task_state.py`
  Added observability fields for `incoming_file_path`, latest relationship decision, latest transition plan, pending upload summary, attached supporting file, and clarification state.
- `core/trace.py`
  Added file-relationship trace step types and user-facing formatting for triggered / decided / applied / failed paths.
- `config.py`
  Added feature flags:
  - `ENABLE_FILE_RELATIONSHIP_RESOLUTION=true`
  - `FILE_RELATIONSHIP_RESOLUTION_REQUIRE_NEW_UPLOAD=true`
  - `FILE_RELATIONSHIP_RESOLUTION_ALLOW_LLM_FALLBACK=true`
- `tests/test_file_relationship_resolution.py`
  Added direct IR / parser / transition-plan / fallback tests.
- `tests/test_router_state_loop.py`
  Added transcript-style regression tests for replace, attach, ambiguous clarify, skip, and memory persistence.
- `tests/test_trace.py`
  Added coverage for new trace-friendly rendering.
- `tests/test_task_state.py`
  Added serialization coverage for the new relationship-state observability fields.
- `P1J1_FILE_RELATIONSHIP_RESOLUTION_REPORT.md`
  Added this implementation report.

## 3. Relationship Resolution Design
The core IR is defined in `core/file_relationship_resolution.py`.

Main objects:

- `FileRelationshipType`
- `FileRelationshipDecision`
- `FileRelationshipParseResult`
- `FileRelationshipResolutionContext`
- `FileRelationshipTransitionPlan`
- `FileRelationshipFileSummary`

Why an LLM-guided layer was introduced:

- The problem is semantic, not purely structural.
- Phrases like “刚刚发错了”, “这是 GIS 配套文件”, and “把这一列加上” cannot be reduced to a single safe rule without losing context.
- The LLM output is bounded to a fixed JSON schema and fixed enum set, so it cannot directly mutate backend state.

Why this is not a blunt reset:

- `FileRelationshipDecision` only classifies the relationship.
- `FileRelationshipTransitionPlan` decides exactly which state slices are superseded, preserved, or clarified.
- Replacement invalidates old primary-file-bound repair state.
- Supporting-file attachment preserves the primary file and keeps the current workflow authoritative.
- Merge semantics are recorded but not executed.

Fallback design:

- Primary path: `self.llm.chat_json(...)` with `FILE_RELATIONSHIP_RESOLUTION_PROMPT`.
- Fallback path: `infer_file_relationship_fallback(...)`.
- The fallback exists to preserve runtime robustness and testability when structured LLM output is unavailable or invalid.
- It is bounded and only produces the same enum decisions, never arbitrary state mutations.

## 4. Transition Semantics
`build_file_relationship_transition_plan(...)` maps each relationship type to bounded state effects.

`replace_primary_file`

- Promotes the new upload to primary.
- Supersedes pending input completion.
- Clears `input_completion_overrides`.
- Resets geometry recovery / readiness refresh / supporting-spatial state.
- Clears residual re-entry.
- Clears the live residual workflow unless the decision explicitly preserves it.
- Preserves session trace, working memory, and locked parameters.

`attach_supporting_file`

- Preserves the current primary file.
- Records the upload as supporting context.
- Preserves residual workflow / geometry recovery authority when applicable.
- Does not clear primary-file-bound completion state by default.
- Lets existing geometry completion logic keep processing the uploaded support file.

`merge_supplemental_columns`

- Records merge intent only.
- Does not merge columns or tables.
- Stops the turn with a bounded user-visible summary explaining that merge semantics were recognized but not executed.

`continue_with_current_file`

- Restores / preserves the current primary file.
- Clears any pending unresolved relationship upload.
- Avoids unnecessary invalidation of completion / recovery / residual context.

`ask_clarify`

- Preserves the current primary file.
- Stores the pending uploaded file and primary-file summary in a live bundle.
- Moves the state to bounded clarification without guessing.
- Allows the next turn to resolve the already uploaded file without requiring a re-upload.

## 5. Router Integration
The integration point is early in `UnifiedRouter._state_handle_input()`.

Order now:

1. Hydrate live completion / parameter / file-relationship bundle state.
2. Call `_should_resolve_file_relationship(...)`.
3. If triggered:
   - build `FileRelationshipResolutionContext`
   - call `_resolve_file_relationship(...)`
   - derive `FileRelationshipTransitionPlan`
   - apply `_apply_file_relationship_transition(...)`
4. Only then continue into:
   - active input completion
   - new-task detection
   - geometry recovery continuation
   - normal grounding / readiness / continuation

Why this has higher priority than general continuation:

- A new upload can otherwise be misread as “continue current completion”.
- Old overrides / recovery context can otherwise leak into the new file.
- Residual workflow continuation should only run after the file relationship has been formalized.

Why it still does not steal explicit bounded replies:

- Plain continuation without upload does not trigger the resolver.
- Parameter confirmation replies keep precedence when a clear confirmation reply is detected.
- Geometry-support uploads during active completion are classified first, but the existing bounded geometry completion path still performs the actual support-file handling.

Additional important router change:

- `_run_state_loop()` no longer blindly persists the raw uploaded file into memory as `active_file`.
- It now persists the file selected by the transition plan.
- This prevents supporting uploads and unresolved uploads from poisoning future primary-file context.

## 6. Trace
New trace step types:

- `FILE_RELATIONSHIP_RESOLUTION_TRIGGERED`
- `FILE_RELATIONSHIP_RESOLUTION_DECIDED`
- `FILE_RELATIONSHIP_TRANSITION_APPLIED`
- `FILE_RELATIONSHIP_RESOLUTION_SKIPPED`
- `FILE_RELATIONSHIP_RESOLUTION_FAILED`

Where they are written:

- `_state_handle_input()` records `TRIGGERED`, `DECIDED`, `SKIPPED`, and `FAILED`.
- `_apply_file_relationship_transition()` records `TRANSITION_APPLIED`.

Recorded payloads include:

- trigger reason
- primary / uploaded file summaries
- relationship type
- confidence
- full decision payload
- full transition plan
- which contexts were reset / preserved
- whether clarification was required

Why these traces matter for the paper:

- They expose the semantic-control step explicitly instead of hiding it inside generic continuation logic.
- They show the split between semantic inference and backend state migration.
- They make “precise invalidation” auditable instead of rhetorical.

## 7. Tests
Test files added / extended:

- `tests/test_file_relationship_resolution.py`
- `tests/test_router_state_loop.py`
- `tests/test_trace.py`
- `tests/test_task_state.py`

Transcript-style behavior covered:

- replace primary file supersedes pending completion and clears stale overrides
- attach supporting GIS/spatial file preserves primary context
- plain continuation without upload skips relationship resolution
- ambiguous “用这个吧” enters bounded clarification instead of guessing
- supporting-file attachment no longer writes the support file into memory as the next primary file
- compatibility with input completion, geometry recovery, and residual re-entry transcript paths

Commands run:

```bash
pytest tests/test_file_relationship_resolution.py tests/test_task_state.py tests/test_trace.py tests/test_router_state_loop.py -q
pytest tests/test_input_completion_transcripts.py tests/test_geometry_recovery_transcripts.py tests/test_residual_reentry_transcripts.py -q
```

Result:

- `107 passed`

## 8. Known Limitations
This round only implements relationship judgment plus bounded state migration.

Explicitly not implemented:

- no actual supplemental-column merge
- still a bounded schema, not a general file dialogue agent
- no scheduler / auto replay / automatic multi-step recovery
- no durable cross-restart persistence
- no generalized supporting-file execution path beyond existing geometry-recovery wiring

Additional practical limitation:

- The primary LLM path is bounded, but the system still uses a bounded fallback classifier when structured JSON is unavailable. This was chosen to keep the router operational and to avoid regressing existing completion / geometry transcripts.

## 9. Suggested Next Step
Implement the execution-side path for `merge_supplemental_columns`.

Reason:

- The new resolver can now formally distinguish replacement vs attachment vs merge.
- `merge_supplemental_columns` is the only new relationship type that intentionally stops at a recorded transition without a downstream executor path.
- That makes it the cleanest and highest-leverage next increment on top of the new control layer.
