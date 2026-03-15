# Phase 3C Router First Extraction Report

## 1. Executive Summary

This round completed the first real structural extraction from `core/router.py`, but only for the exact approved seam:

- `_build_memory_tool_calls`
- `_compact_tool_data`

This seam was chosen because Phase 3B identified it as the smallest, least coupled, and best-protected helper pair in the router. It is deterministic, used from a single place in `_process_response`, and already had focused contract coverage.

Everything else in `core/router.py` was intentionally left untouched, including:

- `chat`
- `_process_response`
- payload extraction helpers
- synthesis/rendering helpers
- file-analysis/cache logic

## 2. Seam Verification Summary

### What was inspected

- `core/router.py`
- `tests/test_router_contracts.py`
- `PHASE3B_ROUTER_SEAM_REEVALUATION_REPORT.md`
- downstream consumers in `api/session.py` and `api/routes.py`

### How the approved seam was confirmed

- `_build_memory_tool_calls` and `_compact_tool_data` still existed as a self-contained helper pair in the live router.
- They were still only used to build `executed_tool_calls` for memory/follow-up grounding.
- Their only direct internal call site remained the final `RouterResponse` assembly path in `_process_response`.
- The Phase 3B recommendation still matched the live code exactly: this was still the smallest serious extraction seam and the larger payload/synthesis seams were still more coupled.

### Dependencies and constraints that mattered

- The seam depends only on:
  - standard typing imports
  - tool result dict structure
- The seam does not depend on:
  - router instance state
  - executor state
  - LLM calls
  - file-analysis/cache state
- Compatibility constraints that had to be preserved:
  - `_process_response` should keep calling `self._build_memory_tool_calls(...)`
  - tests using `router._build_memory_tool_calls(...)` and `router._compact_tool_data(...)` should keep working
  - the shape of `executed_tool_calls` must not change

## 3. Concrete Extraction Performed

### Files created

- `core/router_memory_utils.py`

### Files changed

- `core/router.py`
- `tests/test_router_contracts.py`
- `DEVELOPMENT.md`

### What moved out of `core/router.py`

Moved into `core/router_memory_utils.py`:

- `compact_tool_data(...)`
- `build_memory_tool_calls(...)`

### What remained in place

Left in `core/router.py`:

- thin compatibility wrappers named:
  - `_build_memory_tool_calls`
  - `_compact_tool_data`
- the existing `_process_response` call site
- all orchestration, synthesis, and payload-extraction logic

### How compatibility was preserved

- `core/router.py` now imports the extracted functions and delegates through wrapper methods instead of changing the live call site shape.
- `_process_response` still uses `self._build_memory_tool_calls(tool_results)` exactly as before.
- Existing tests that instantiate `UnifiedRouter` via `object.__new__(UnifiedRouter)` still work without modification to router construction behavior.
- A new compatibility test now checks that the extracted module functions and the `core.router` wrappers return the same results.

### Why this was low-risk

- Only the approved helper pair moved.
- No router control-flow behavior changed.
- No payload/result contract changed.
- No additional helper clusters were extracted opportunistically.

## 4. Regression Protection / Verification

### Tests added or updated

Updated:

- `tests/test_router_contracts.py`

Added one focused compatibility assertion layer:

- verifies `core.router_memory_utils.compact_tool_data(...)` matches `UnifiedRouter._compact_tool_data(...)`
- verifies `core.router_memory_utils.build_memory_tool_calls(...)` matches `UnifiedRouter._build_memory_tool_calls(...)`

Existing router contract coverage continues to protect:

- memory compaction shape
- chart payload extraction
- macro table preview shaping
- download/map extraction
- fallback formatting

### Commands run

```bash
pytest tests/test_router_contracts.py
python main.py health
pytest
```

### What passed

- `pytest tests/test_router_contracts.py`: passed (`7 passed`)
- `python main.py health`: passed
- full `pytest`: passed (`63 passed`)

### Remaining warnings / limitations

- Existing FastAPI `@app.on_event(...)` deprecation warnings remain.
- Existing `datetime.utcnow()` deprecation warning in `api/logging_config.py` remains.
- These were pre-existing and were intentionally left unchanged in this round.

## 5. What Was Intentionally NOT Refactored

Deferred `core/router.py` areas:

- `chat`
- `_process_response`
- `_analyze_file`
- `_synthesize_results`
- `_render_single_tool_success`
- `_filter_results_for_synthesis`
- `_format_tool_errors`
- `_format_tool_results`
- `_format_results_as_fallback`
- `_extract_chart_data`
- `_format_emission_factors_chart`
- `_extract_table_data`
- `_extract_download_file`
- `_extract_map_data`

Why they were deferred:

- They are either more orchestration-heavy, more semantically coupled to synthesis policy, or more dependent on under-protected payload branches than the approved memory-compaction seam.
- Extracting any of them in this round would have violated the explicit Phase 3B scope decision.

## 6. Risks / Follow-up Work

### Remaining `core/router.py` structural debt

- The router is still large and still mixes orchestration, synthesis policy, payload shaping, and memory preparation.
- The new extraction proves the mechanism, but it does not materially reduce the complexity of `chat` or `_process_response`.
- The payload-extraction cluster remains the largest helper-style block, but it is still only partially protected.

### What should or should not be the next candidate seam

Should not be next:

- `chat`
- `_process_response`
- a broad synthesis/rendering split
- the entire payload-extraction cluster as-is

Most plausible later direction:

- first add table-path protection for:
  - `query_emission_factors`
  - `calculate_micro_emission`
- then re-evaluate a smaller payload-extraction seam

## 7. Recommended Next Safe Step

Add the missing table-path contract protection in `tests/test_router_contracts.py` for:

- `query_emission_factors`
- `calculate_micro_emission`

Then re-evaluate whether a narrower second router extraction can safely target part of the payload-extraction block.

## Suggested Next Safe Actions

- [x] Verify that the approved seam still matched the live router.
- [x] Extract only `_build_memory_tool_calls` and `_compact_tool_data`.
- [x] Preserve `core/router.py` compatibility through thin wrappers.
- [x] Keep router contract tests green after the extraction.
- [x] Record the first extracted router seam in `DEVELOPMENT.md`.
- [ ] Add missing table-path protection before considering any larger router seam.
- [ ] Keep `chat` and `_process_response` out of scope until more protection exists.
