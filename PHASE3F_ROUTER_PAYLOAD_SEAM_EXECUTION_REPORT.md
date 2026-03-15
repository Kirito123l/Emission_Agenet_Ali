# Phase 3F Router Payload Seam Execution Report

## 1. Executive Summary

Result: **GO + extraction performed**

This round re-evaluated the `core/router.py` payload-helper area against the expanded router contract layer and concluded that the seam was now sufficiently coherent and protected for extraction.

Extraction performed:

- `_extract_chart_data`
- `_format_emission_factors_chart`
- `_extract_table_data`
- `_extract_download_file`
- `_extract_map_data`

What changed:

- the full payload-helper cluster moved into `core/router_payload_utils.py`
- `core/router.py` kept thin compatibility wrappers so existing internal call sites and test usage remain stable
- one focused compatibility test layer was added for the extracted payload helpers

What was intentionally deferred:

- `chat`
- `_process_response`
- synthesis/rendering helpers
- any router behavior or payload-format redesign

## 2. Seam Re-evaluation Summary

### Current assessment of the payload-helper area

The payload-helper area is now a coherent extraction target.

Why:

- all five helpers are deterministic and operate on tool-result dictionaries rather than router instance state
- they are used together as one payload-assembly cluster in `_process_response`
- the previously missing table-branch protections identified in Phase 3D were added in Phase 3E
- the extraction provides meaningful maintainability value without fragmenting the router into overly small pieces

### Why it was now ready

Compared with the earlier NO-GO:

- `query_emission_factors` table shaping is now covered
- `calculate_micro_emission` table shaping is now covered
- macro table shaping was already covered
- chart formatting, download extraction, and map extraction were already covered

That means the full helper cluster is now protected across:

- chart payload shaping
- all currently important table-shaping branches
- download payload extraction
- map payload extraction

### Protections/tests relied on

- `tests/test_router_contracts.py`
  - chart payload precedence and formatting
  - table shaping for:
    - `calculate_macro_emission`
    - `query_emission_factors`
    - `calculate_micro_emission`
  - download/map extraction
  - compatibility between extracted helper modules and `core.router` wrappers

## 3. Concrete Work Performed

### Files created

- `core/router_payload_utils.py`
- `PHASE3F_ROUTER_PAYLOAD_SEAM_EXECUTION_REPORT.md`

### Files changed

- `core/router.py`
- `tests/test_router_contracts.py`
- `DEVELOPMENT.md`

### What moved out of `core/router.py`

Moved into `core/router_payload_utils.py`:

- `format_emission_factors_chart(...)`
- `extract_chart_data(...)`
- `extract_table_data(...)`
- `extract_download_file(...)`
- `extract_map_data(...)`

### What remained in place

Left in `core/router.py`:

- thin compatibility wrappers named:
  - `_extract_chart_data(...)`
  - `_format_emission_factors_chart(...)`
  - `_extract_table_data(...)`
  - `_extract_download_file(...)`
  - `_extract_map_data(...)`
- the existing `_process_response(...)` call sites
- all orchestration, control-flow, synthesis, and memory logic

### How compatibility was preserved

- `core/router.py` now imports the extracted helper functions and delegates through wrapper methods
- `_process_response(...)` still uses the same `self._extract_*` method names
- tests that instantiate `UnifiedRouter` through `object.__new__(UnifiedRouter)` continue to work without router-construction changes
- a new compatibility test checks that the extracted payload helpers and the `core.router` wrappers return the same results

## 4. Tests / Verification

### Commands run

```bash
pytest tests/test_router_contracts.py
python main.py health
pytest
```

### What passed

- `pytest tests/test_router_contracts.py`: passed (`10 passed`)
- `python main.py health`: passed
- full `pytest`: passed (`66 passed`)

### Warnings / limitations

- existing FastAPI `@app.on_event(...)` deprecation warnings remain
- existing `datetime.utcnow()` deprecation warning from `api/logging_config.py` remains
- the optional `FlagEmbedding` warning during `python main.py health` remains

These were already present and were intentionally left unchanged.

## 5. What Was Intentionally Left Untouched

Deferred router areas:

- `chat`
- `_process_response`
- `_analyze_file`
- `_synthesize_results`
- `_render_single_tool_success`
- `_filter_results_for_synthesis`
- `_format_tool_errors`
- `_format_tool_results`
- `_format_results_as_fallback`

These were left untouched because this round was limited to one coherent payload-helper extraction only.

## 6. Recommended Next Step

The next safe move is a fresh seam decision for the synthesis/rendering helper area, but only after explicitly deciding whether its current protection level is good enough. Do not jump directly into `chat` or `_process_response` refactoring.

## Suggested Next Safe Actions

- [x] Re-evaluate the payload-helper seam against the current contract layer.
- [x] Extract the full payload-helper cluster into one helper module.
- [x] Preserve `core/router.py` compatibility through thin wrappers.
- [x] Add compatibility coverage for the new helper module.
- [ ] Reassess the synthesis/rendering helper cluster as the next possible router seam.
- [ ] Keep `chat` and `_process_response` out of scope until a later dedicated decision round.
