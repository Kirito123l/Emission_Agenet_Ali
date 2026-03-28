# Context Store Report

## 1. Architecture

```text
User message
  -> Router
     -> ContextAssembler
        -> system prompt + skills + compact session summary
     -> LLM tool selection
     -> ToolExecutor
        -> tool result
     -> SessionContextStore
        -> store full successful result by semantic type
        -> track current-turn results
     -> Router
        -> inject downstream _last_result from ContextStore
        -> feed compact tool summaries back to LLM
        -> extract frontend payloads from tool_results
        -> sanitize final text response
  -> API / Web
```

## 2. Storage Schema

`SessionContextStore` stores successful tool outputs by semantic result type instead of by last-tool slot:

- `emission`
  - produced by `calculate_macro_emission`, `calculate_micro_emission`
- `dispersion`
  - produced by `calculate_dispersion`
- `hotspot`
  - produced by `analyze_hotspots`
- `visualization`
  - produced by `render_spatial_map`
- `file_analysis`
- `emission_factors`
- `knowledge`

Each stored entry is:

```python
StoredResult(
    result_type="emission",
    tool_name="calculate_macro_emission",
    timestamp="<iso>",
    summary="<500 chars>",
    data=<full tool result>,
    metadata={<compact stats>}
)
```

Key point:

- full geometry-bearing / raster-bearing payloads stay inside the store
- LLM only sees compact summaries
- `last_spatial_data` is still written for backward compatibility, but it is no longer the primary dependency source

## 3. Dependency Resolution Decision Tree

### `calculate_dispersion`

1. ask Context Store for `emission`
2. if missing, fall back to `fact_memory.last_spatial_data`
3. inject as `_last_result`

### `analyze_hotspots`

1. ask Context Store for `dispersion`
2. if missing, fall back to `fact_memory.last_spatial_data`
3. inject as `_last_result`

### `render_spatial_map`

1. if `layer_type=emission` -> use `emission`
2. if `layer_type=raster` / `concentration` -> use `dispersion`
3. if `layer_type=hotspot` -> use `hotspot`
4. if no `layer_type` -> priority `hotspot > dispersion > emission`
5. if Context Store misses, fall back to `last_spatial_data`, then `last_tool_snapshot`

This fixes the old overwrite problem:

```text
Old:
emission -> last_spatial_data = emission
dispersion -> last_spatial_data = dispersion
hotspot -> last_spatial_data = hotspot
render(emission) after hotspot => broken

New:
emission -> store["emission"]
dispersion -> store["dispersion"]
hotspot -> store["hotspot"]
render(emission) after hotspot => still resolves store["emission"]
```

## 4. Tool Result Feedback Compression

Router no longer feeds full tool payloads back into the function-calling loop.

Current tool-role message format:

```text
Tool: calculate_dispersion
Status: success
Result: Dispersion completed for 15 receptors
Key stats: 15 receptors; mean=1.2000 μg/m³; max=4.5000 μg/m³; 1 coverage warnings; defaults: meteorology
```

Rules:

- one tool message <= 1000 chars
- only summary + key stats
- no `results`, no geometry WKT, no `matrix_mean`, no `cell_receptor_map`, no `receptor_top_roads`

## 5. Output Safety Rails

New module: `core/output_safety.py`

`sanitize_response()` is now applied on all user-visible output paths:

- state-loop clarification responses
- state-loop direct no-tool replies
- state-loop synthesized / LLM final replies
- legacy direct replies
- legacy synthesized replies
- visualization suggestion appended replies
- generic failure fallback

Dangerous patterns blocked:

- `LINESTRING`
- `MULTILINESTRING`
- `POLYGON`
- `matrix_mean`
- `cell_receptor_map`
- `receptor_top_roads`

Additional safeguards:

- final response text capped at `8000` chars
- deterministic fallback synthesis capped at `<3000` chars
- fallback synthesis now uses summaries only and never expands `data` fields

## 6. Modified Files

- `core/context_store.py`
  - new in-memory session result store
- `core/output_safety.py`
  - new response sanitization module
- `core/router.py`
  - Context Store integration
  - `_last_result` injection via store
  - compact tool-role feedback
  - output sanitization
  - compatibility `last_spatial_data` writes retained
- `core/router_render_utils.py`
  - safe fallback formatting
- `core/router_synthesis_utils.py`
  - normalized deterministic summary return path
- `core/assembler.py`
  - inject compact context summary into system prompt
- `tests/test_context_store.py`
  - unit coverage for store + output safety
- `tests/test_context_store_integration.py`
  - router integration coverage
- `tests/test_router_contracts.py`
  - updated fallback expectations
- `tests/test_dispersion_tool.py`
  - stabilized mock LLM loop for state orchestration

## 7. Validation

Targeted:

- `pytest tests/test_context_store.py -v`
  - 22 passed
- `pytest tests/test_context_store_integration.py -v`
  - 4 passed
- `pytest tests/test_router_contracts.py -q`
  - 18 passed
- `pytest tests/test_router_state_loop.py -q`
  - 8 passed
- `pytest tests/test_multi_step_execution.py -q`
  - 9 passed
- `pytest tests/test_multi_tool_map_data.py -q`
  - 5 passed
- `pytest tests/test_render_defaults.py -q`
  - 8 passed

Final validation:

- `node -c web/app.js`
  - passed
- `pytest -q`
  - 535 passed, 19 warnings
- `python main.py health`
  - 8 tools OK
- `python3 simulate_e2e.py`
  - passed
- safety check script
  - passed

## 8. Behavior Change Summary

### Before

- router relied on one mutable `last_spatial_data`
- newer spatial tools overwrote older results
- downstream tool injection depended on ad hoc router logic
- tool results could be overfed back to LLM
- fallback synthesis could expand raw `data`

### After

- router keeps full successful results by semantic type for the whole session
- downstream tools resolve what they need from Context Store, not from one fragile slot
- LLM gets only compact summaries and key stats
- every user-visible response passes through a raw-data safety rail
- fallback output is deterministic, short, and summary-only
