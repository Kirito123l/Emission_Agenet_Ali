# Phase 3A Router Contract Protection Report

## 1. Executive Summary

This round added a thin router-level protection layer focused on the most stable and externally relevant `core/router.py` payload/result behaviors:

- memory tool-call compaction shape
- chart payload extraction and formatting
- table payload extraction
- download/map payload extraction
- deterministic fallback formatting for failed tool runs

These cases were chosen because they are the pure or mostly-pure parts of `core/router.py` most likely to be extracted later and most likely to break frontend/API behavior if their payload shape drifts.

This round intentionally did **not** restructure `core/router.py`. It also left live orchestration paths such as `UnifiedRouter.chat`, `_process_response`, live tool execution, retries, and LLM synthesis unprotected for now because they are more coupled and expensive to test safely.

In support of the contract work, I made two tiny low-risk clarifications:

- aligned `RouterResponse.download_file` with the live dict-shaped metadata contract already consumed by `api/session.py` and `api/routes.py`
- added a maintainer note to `DEVELOPMENT.md` pointing future router work at the new focused test file

## 2. Router Inspection Summary

### Files inspected

- `core/router.py`
- `api/session.py`
- `api/routes.py`
- `tests/test_api_route_contracts.py`
- `ROUTER_REFACTOR_PREP.md`
- `DEVELOPMENT.md`

### Result/payload categories identified in the live router

- Response envelope:
  - `RouterResponse`
- Memory compaction helpers:
  - `_build_memory_tool_calls`
  - `_compact_tool_data`
- Frontend payload extraction helpers:
  - `_extract_chart_data`
  - `_format_emission_factors_chart`
  - `_extract_table_data`
  - `_extract_download_file`
  - `_extract_map_data`
- Deterministic fallback formatting:
  - `_format_results_as_fallback`
- Higher-risk orchestration and live branches:
  - `chat`
  - `_process_response`
  - `_synthesize_results`
  - `_render_single_tool_success`
  - file-analysis caching and trace handling

### Testability constraints

- `UnifiedRouter.__init__` wires in real config, executor, memory, and LLM client dependencies.
- Full `chat()` or `_process_response()` coverage would require either live tool/LLM behavior or heavier mocking than this round should introduce.
- The safest thin protection layer is therefore helper-level coverage against the stable payload/result formatting methods, using `object.__new__(UnifiedRouter)` to avoid live runtime setup.

## 3. Tests Added

### New test file

- `tests/test_router_contracts.py`

### Router behaviors now protected

1. Memory tool-call compaction
   - protects `_build_memory_tool_calls()` and `_compact_tool_data()`
   - checks that large/high-churn fields such as `results`, `speed_curve`, and `pollutants` are dropped
   - checks that compact follow-up context keeps high-value fields such as `query_info`, `summary`, `download_file`, scalar metadata, and truncated `columns`

2. Chart payload precedence
   - protects `_extract_chart_data()`
   - checks that tool-provided `chart_data` is returned unchanged when already present

3. Emission-factor chart formatting
   - protects `_extract_chart_data()` plus `_format_emission_factors_chart()`
   - checks the frontend-facing envelope shape for multi-pollutant emission-factor results
   - checks curve selection behavior for `speed_curve` vs `curve`

4. Macro table preview formatting
   - protects `_extract_table_data()`
   - checks the frontend-facing preview table shape for `calculate_macro_emission`
   - keeps assertions at the stable top-level shape and representative formatted values

5. Download and map payload extraction
   - protects `_extract_download_file()` and `_extract_map_data()`
   - checks current top-level payload locations plus legacy/nested compatibility locations

6. Deterministic fallback formatting
   - protects `_format_results_as_fallback()`
   - checks success/error section presence, summary inclusion, and suggestion rendering without snapshotting the entire response

### Why these checks are thin but high-value

- They cover the pure helper methods most likely to be extracted first from `core/router.py`.
- They protect the payload keys and envelopes that downstream API/session layers already rely on.
- They avoid live LLM, network, or async orchestration behavior, so they are stable enough to stay green during conservative refactoring.

## 4. Verification

### Commands run

```bash
pytest tests/test_router_contracts.py
python main.py health
pytest
```

### Results

- `pytest tests/test_router_contracts.py`: passed (`6 passed`)
- `python main.py health`: passed
- full `pytest`: passed (`62 passed`)

### Remaining warnings / limitations

- Existing FastAPI `@app.on_event(...)` deprecation warnings remain.
- Existing `datetime.utcnow()` deprecation warning from `api/logging_config.py` remains.
- These warnings were already present and were intentionally left unchanged in this round.

## 5. What Was Intentionally NOT Protected

The following router areas were explicitly deferred:

- `UnifiedRouter.chat`
  - large orchestration entry point
  - mixes context assembly, file-analysis cache handling, tool-call routing, and memory updates
- `UnifiedRouter._process_response`
  - central control-flow method with retries, tool execution, synthesis, and final payload assembly
- live synthesis behavior in `_synthesize_results`
  - depends on executor/LLM behavior and has higher setup cost
- human-readable rendering in `_render_single_tool_success`
  - useful, but more presentation-text-sensitive and therefore more brittle for this pass
- direct-response/no-tool-call behavior
- retry/error re-entry behavior after failed tool runs
- knowledge short-circuit behavior for `query_knowledge`
- table shaping for `query_emission_factors` and `calculate_micro_emission`
  - still valuable later, but not necessary for the first router contract layer

These were deferred because protecting them well would require heavier mocking or higher-brittleness assertions than this round should accept.

## 6. Risks / Follow-up Work

### Remaining fragility or ambiguity

- `core/router.py` still mixes orchestration, synthesis policy, payload shaping, and memory compaction in one module.
- The new tests protect helper-level contracts, not end-to-end router execution.
- `RouterResponse` now has a corrected `download_file` type hint, but the module still has other broad `Dict`-typed payloads that remain loosely specified.
- Debug-style logging in router helper paths still exists and was left untouched in this round to avoid mixing logging cleanup with contract work.

### Additional protection that would be useful before the first real router extraction

- one or two mocked async tests around `_process_response()` that verify:
  - direct-response branch shape
  - single-tool success branch produces `RouterResponse` with extracted payloads and compact `executed_tool_calls`
- one representative test for `query_emission_factors` table extraction if that helper cluster becomes the first extraction target

## 7. Recommended Next Safe Step

Use `tests/test_router_contracts.py` as the guardrail for a first router seam analysis, then choose **exactly one** of these small helper clusters for a future extraction round:

- memory compaction helpers:
  - `_build_memory_tool_calls`
  - `_compact_tool_data`
- frontend payload extraction helpers:
  - `_extract_chart_data`
  - `_format_emission_factors_chart`
  - `_extract_table_data`
  - `_extract_download_file`
  - `_extract_map_data`

Do **not** start with `chat`, `_process_response`, or synthesis flow refactoring yet.

## Suggested Next Safe Actions

- [x] Add thin router contract coverage around payload/result shaping helpers.
- [x] Keep the full regression baseline green after adding the new protection layer.
- [x] Record the new maintainer-facing router test command in `DEVELOPMENT.md`.
- [ ] Add at most one or two mocked `_process_response()` branch tests before any control-flow refactor.
- [ ] Re-evaluate the smaller of the memory-compaction or payload-extraction helper clusters as the first real `core/router.py` extraction seam.
