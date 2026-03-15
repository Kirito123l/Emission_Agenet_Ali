# Router And API Refactor Prep

This document prepares a future safe decomposition pass. It does not authorize a broad refactor by itself.

## Files Inspected

- `core/router.py`
- `api/routes.py`
- `RUNNING.md`
- `evaluation/README.md`
- `tests/test_smoke_suite.py`
- `tests/test_phase1b_consolidation.py`

## Why These Files Need Prep

- `core/router.py` is the main orchestration layer and is currently responsible for routing, file-context caching, tool execution loops, synthesis policy, frontend payload extraction, and memory updates.
- `api/routes.py` currently mixes route registration with request/session helpers, response normalization, streaming behavior, file preview/download/template logic, GIS asset serving, session CRUD, and auth endpoints.

Both files are still active and behavior-sensitive. They should be decomposed only through small, test-backed extractions.

## Current Responsibilities

### `core/router.py`

Current responsibilities observed in the live module:

- `UnifiedRouter.chat`
  - entry point for a user turn
  - file-analysis cache lookup and refresh
  - context assembly
  - LLM tool-call routing
  - memory updates
- `_process_response`
  - tool execution loop
  - retry/error handling
  - synthesis handoff
  - frontend payload extraction
- Rendering and synthesis helpers
  - `_render_single_tool_success`
  - `_filter_results_for_synthesis`
  - `_format_tool_errors`
  - `_format_tool_results`
  - `_format_results_as_fallback`
- Frontend payload shaping helpers
  - `_extract_chart_data`
  - `_format_emission_factors_chart`
  - `_extract_table_data`
  - `_extract_download_file`
  - `_extract_map_data`
- Memory compaction helpers
  - `_build_memory_tool_calls`
  - `_compact_tool_data`

### `api/routes.py`

Current responsibilities observed in the live module:

- Request/session helper logic
  - `get_user_id`
  - `friendly_error_message`
  - `clean_reply_text`
  - `normalize_download_file`
  - `attach_download_to_table_data`
  - chart/table helper utilities
- Chat endpoints
  - `/chat`
  - `/chat/stream`
- File/GIS/download endpoints
  - `/file/preview`
  - `/gis/basemap`
  - `/gis/roadnetwork`
  - `/file/download/*`
  - `/download/{filename}`
  - `/file/template/{template_type}`
- Session endpoints
  - `/sessions`
  - `/sessions/new`
  - `/sessions/{session_id}`
  - `/sessions/{session_id}/title`
  - `/sessions/{session_id}/history`
- Utility/auth endpoints
  - `/health`
  - `/test`
  - `/register`
  - `/login`
  - `/me`

## Candidate Extraction Seams

### First-pass seams for `core/router.py`

Safest extraction targets are the pure or mostly-pure helper methods:

1. Result rendering helpers
   - `_render_single_tool_success`
   - `_format_tool_errors`
   - `_format_tool_results`
   - `_format_results_as_fallback`
2. Frontend payload extraction helpers
   - `_extract_chart_data`
   - `_format_emission_factors_chart`
   - `_extract_table_data`
   - `_extract_download_file`
   - `_extract_map_data`
3. Memory compaction helpers
   - `_build_memory_tool_calls`
   - `_compact_tool_data`

Later seam, after helper extraction is stable:

4. File-context/cache preparation currently embedded in `chat`

Avoid extracting `_process_response` or `chat` first. They are still the highest-risk control-flow methods.

### First-pass seams for `api/routes.py`

Safest extraction targets are the pure helper functions:

1. Response normalization helpers
   - `friendly_error_message`
   - `clean_reply_text`
   - `normalize_download_file`
   - `attach_download_to_table_data`
2. Chart/table formatting helpers
   - `build_emission_chart_data`
   - `extract_key_points`
   - `_pick_key_points`

Second-pass seams, after helper extraction is stable:

3. File/download/GIS support functions
4. Session-route support functions

Only after those steps should route groups be split into submodules such as `chat_routes`, `file_routes`, `session_routes`, or `auth_routes`.

## Recommended Extraction Order

1. Add or expand regression coverage around payload shapes and smoke behavior.
2. Extract pure helper functions from `api/routes.py` without changing route signatures.
3. Extract pure helper functions from `core/router.py` without changing `UnifiedRouter.chat` or `_process_response`.
4. Extract the file-context/cache preparation block from `UnifiedRouter.chat` into a small helper module.
5. Reassess route grouping only after helper imports and tests are stable.

## Risks And Blockers

- `core/router.py` mixes orchestration and presentation logic, so accidental changes can alter frontend payload shape.
- `api/routes.py` contains session-history and download compatibility behavior that the frontend relies on.
- Streaming behavior in `/chat/stream` is sensitive to timing and payload order.
- Existing automated coverage is improving but still lighter on API route contracts than on helper/module imports.
- Some debug-style logging remains in large modules; logging cleanup should stay separate from semantic refactors.

## Tests And Guards Needed Before Future Decomposition

Minimum guards to have in place before a real split:

- `pytest`
- `python main.py health`
- `python evaluation/run_smoke_suite.py`
- Focused tests for route helper contracts:
  - download metadata normalization
  - table/download compatibility shape
  - reply-text cleanup
- Focused tests for router payload extraction:
  - chart payload shape
  - table payload shape
  - download/map extraction shape

## What Should Explicitly Remain Untouched First

Do not start the first decomposition pass by changing:

- `UnifiedRouter.chat`
- `UnifiedRouter._process_response`
- FastAPI route paths or response models
- session history storage schema
- streaming event ordering in `/chat/stream`
- auth/database flow

Those areas should stay fixed while helper extractions prove out the lower-risk seams.

## Definition Of A Safe First Refactor Pass

A safe first pass should:

- move only pure helpers or near-pure helpers
- preserve imports, route paths, and response payload keys
- land with explicit regression coverage
- avoid cross-cutting naming or architecture changes

If a proposed change needs router/executor/session semantics to shift at the same time, it is not a first-pass decomposition.
