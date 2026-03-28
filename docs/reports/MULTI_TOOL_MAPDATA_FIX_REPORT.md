# Multi-Tool `map_data` Fix Report

## 1. Diagnosis

### Path A: single-tool friendly render

```text
LLM -> 1 tool_call
   -> tool result contains map_data
   -> router builds RouterResponse from tool_results
   -> api/routes.py forwards result.map_data
   -> web/app.js calls renderMapData(map_data)
```

This path worked because there was only one `map_data` payload.

### Path B: multi-tool + final LLM text

```text
LLM -> multiple tool_calls / multiple tool rounds
   -> each tool result may contain map_data
   -> router feeds compact tool results back to LLM
   -> LLM returns final plain-text answer
   -> router builds RouterResponse from accumulated tool_results
   -> old extract_map_data() returned only the first map_data
   -> later map payloads (for example raster dispersion) were dropped
```

### Actual root cause

The loss was not only "LLM final text path forgot map_data".  
The deeper issue was `core/router_payload_utils.py:extract_map_data()` only returning the **first** `map_data` found in `tool_results`.

That meant:

- single-tool path looked correct
- multi-tool path always truncated to the first map payload
- `download_file` and `table_data` were already preserved by router extraction, but multi-map rendering was impossible

## 2. Fix

### Backend

Changed [core/router_payload_utils.py](/home/kirito/Agent1/emission_agent/core/router_payload_utils.py):

- added `_collect_map_payloads()` to gather every map payload in execution order
- kept legacy behavior for a single map:
  - return the original map object unchanged
- added a backward-compatible multi-map wrapper for multiple maps:

```python
{
  "type": "map_collection",
  "items": [...],
  "summary": {
    "map_count": N,
    "map_types": [...]
  }
}
```

Changed [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py):

- added `_extract_frontend_payloads()` so both response paths use the same payload extraction
- updated `_state_build_response()` and legacy `_process_response()` to use the shared payload bundle
- kept `download_file`, `chart_data`, and `table_data` extraction behavior intact

### Frontend

Changed [web/app.js](/home/kirito/Agent1/emission_agent/web/app.js):

- added `getMapPayloadItems()` to flatten:
  - legacy single-map objects
  - `map_collection`
  - raw arrays for forward compatibility
- changed `hasRenderableMapData()` to validate any item in the collection
- changed `renderMapData()` to render every collected map payload in order

### API

No change required in `api/routes.py`.

Reason:

- `map_data` remains a single JSON object
- `map_collection` is still a dict, so existing response wiring stays valid
- chat, stream, and history storage continue to use the same field name

## 3. Behavior After Fix

For a turn such as:

```text
render_spatial_map + calculate_dispersion
```

the final response now carries:

```python
{
  "map_data": {
    "type": "map_collection",
    "items": [
      {"type": "emission", ...},
      {"type": "raster", ...}
    ],
    "summary": {"map_count": 2, "map_types": ["emission", "raster"]}
  }
}
```

The frontend renders both maps in the same assistant message, in tool execution order.

Single-tool responses are unchanged and still send the original single `map_data` object.

## 4. Files Changed

- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py)
- [core/router_payload_utils.py](/home/kirito/Agent1/emission_agent/core/router_payload_utils.py)
- [web/app.js](/home/kirito/Agent1/emission_agent/web/app.js)
- [tests/test_multi_tool_map_data.py](/home/kirito/Agent1/emission_agent/tests/test_multi_tool_map_data.py)
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py)

## 5. Tests

Targeted checks:

- `pytest tests/test_multi_tool_map_data.py -v` -> 5 passed
- `pytest tests/test_router_contracts.py -q` -> 18 passed
- `pytest tests/test_router_state_loop.py -q` -> 8 passed
- `node -c web/app.js` -> passed

Regression:

- `pytest -q` -> 505 passed
- `python main.py health` -> 8 tools OK

## 6. Notes

- Path A behavior was preserved.
- No calculator or tool implementation was changed.
- No API contract change was required because the multi-map payload is wrapped in a dict instead of switching `map_data` to an array type.
