# Sprint 7: Activate render_spatial_map + De-Shanghai + available_results Tracking

## 1. Files Created or Modified

### Created
- `tests/test_available_results_tracking.py` — 9 tests for available_results tracking and dependency integration

### Modified
- `core/router.py` — Added available_results tracking, dependency checking, auto-visualization trigger
- `web/app.js` — De-Shanghai: CartoDB as primary basemap, GIS layers as optional overlays, generic fallback center
- `web/index.html` — Bumped cache version to v=25

## 2. available_results Tracking Code in router.py

In `_state_handle_executing()`, after each successful tool execution (after `state.execution.completed_tools.append()`):

```python
from core.tool_dependencies import get_missing_prerequisites, get_tool_provides, suggest_prerequisite_tool

# Track available_results after successful execution
if result.get("success"):
    provides = get_tool_provides(tool_call.name)
    state.execution.available_results.update(provides)
```

This populates `state.execution.available_results` with result types like `"emission_result"`, `"visualization"`, `"file_analysis"`, etc., enabling downstream dependency checks.

## 3. Dependency Checking Code in _state_handle_grounded

Added before the transition to EXECUTING:

```python
# Check tool dependencies before proceeding to execution
if state._llm_response and hasattr(state._llm_response, 'tool_calls') and state._llm_response.tool_calls:
    for tc in state._llm_response.tool_calls:
        missing = get_missing_prerequisites(tc.name, state.execution.available_results)
        if missing:
            prereq_tool = suggest_prerequisite_tool(missing[0])
            if prereq_tool:
                logger.info(
                    f"Tool {tc.name} requires {missing[0]}. "
                    f"Auto-injecting prerequisite: {prereq_tool}"
                )
                if trace_obj:
                    trace_obj.record(
                        step_type=TraceStepType.STATE_TRANSITION,
                        stage_before=TaskStage.GROUNDED.value,
                        action="dependency_check",
                        reasoning=f"{tc.name} requires {missing[0]}, will run {prereq_tool} first",
                    )
```

Currently "observe and log only" — no current tools have unmet prerequisites. Infrastructure ready for Sprint 9 (dispersion tool).

## 4. Auto-Visualization Trigger Code in _state_handle_executing

Added before the final `DONE` transition, after all tool calls complete:

```python
# Auto-trigger render_spatial_map if spatial data exists but no visualization was rendered
has_spatial_data = any(
    r.get("result", {}).get("success") and (
        r.get("result", {}).get("map_data") or
        (isinstance(r.get("result", {}).get("data"), dict) and
         r["result"]["data"].get("results") and
         any(link.get("geometry") for link in r["result"]["data"].get("results", [])[:3]))
    )
    for r in state.execution.tool_results
)
already_visualized = "render_spatial_map" in state.execution.completed_tools
has_map_data_from_tool = any(
    r.get("result", {}).get("map_data") for r in state.execution.tool_results
)

if has_spatial_data and not already_visualized and not has_map_data_from_tool:
    # Auto-trigger render_spatial_map with last spatial result
    # ... (executes render_spatial_map, appends to tool_results, records trace)
```

Key safeguard: Only triggers when `has_map_data_from_tool` is False, preventing double-rendering when macro_emission's built-in `_build_map_data` already produced a map.

## 5. Frontend Changes: Old vs New Basemap Loading Logic

### Old Logic (Shanghai-centric)
1. **Primary**: Load GIS basemap (`/api/gis/basemap`) with Shanghai administrative boundaries
2. **Fallback**: Only if GIS basemap fails, load CartoDB Positron tiles
3. **Road network**: Loaded and shown by default on map
4. **Fallback center**: `[31.2304, 121.4737]` (Shanghai) at zoom 12

### New Logic (Location-agnostic)
1. **Primary**: Always load CartoDB Positron tiles first (guaranteed availability)
2. **Optional overlays**: GIS basemap ("行政边界") and road network ("路网底图") available via layer control, NOT shown by default
3. **Fallback center**: `[35.0, 105.0]` (generic China center) at zoom 4, overridden by `fitBounds` from emission data
4. **Layer control**: Both GIS layers added as optional overlays with `.catch(() => {})` error suppression

## 6. Test Results

### Sprint 7 tests (9 new tests)
```
tests/test_available_results_tracking.py — 9 passed

TestAvailableResultsTracking:
  test_initial_available_results_empty          PASSED
  test_available_results_serializable           PASSED
  test_available_results_update                 PASSED
  test_available_results_sorted_in_dict         PASSED

TestDependencyIntegration:
  test_macro_emission_no_missing                PASSED
  test_dispersion_missing_emission              PASSED
  test_dispersion_satisfied_after_emission      PASSED
  test_suggest_macro_for_emission_result        PASSED
  test_render_spatial_map_no_prerequisites      PASSED
```

### Sprint 6 tests (still passing)
```
tests/test_spatial_renderer.py   — 13 passed
tests/test_spatial_types.py      — 7 passed
tests/test_tool_dependencies.py  — 9 passed
```

### Full test suite
```
181 passed in 5.21s
```

All 172 existing tests continue to pass. 9 new tests added.

## 7. Health Check Output

```
OK query_emission_factors
OK calculate_micro_emission
OK calculate_macro_emission
OK analyze_file
OK query_knowledge
OK render_spatial_map

Total tools: 6
```

## 8. node --check web/app.js

```
(no output — syntax valid)
```

## 9. Issues Encountered and Resolutions

1. **Tool result nesting**: The router stores tool results as `{"tool_call_id": ..., "name": ..., "result": {...}}`. The auto-visualization check needed to access `r.get("result", {}).get("success")` rather than `r.get("success")` directly. Same pattern for `map_data` and `data` checks.

2. **No other issues**: The import of `get_missing_prerequisites`, `get_tool_provides`, and `suggest_prerequisite_tool` from `core.tool_dependencies` worked cleanly. The `TaskState.initialize()` signature requires `session_id` as a keyword argument (found during test writing). The frontend changes were straightforward — the layer control API (`addOverlay`) works with deferred promise-based layer creation.
