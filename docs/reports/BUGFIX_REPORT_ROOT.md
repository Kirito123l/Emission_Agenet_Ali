# BUGFIX Report

## Scope

This change fixes two urgent issues:

1. Leaflet maps floating above later chat messages while scrolling.
2. `analyze_hotspots` showing a historical `39610ms` tool duration even though the hotspot algorithm should be lightweight.

## Bug 1: Map Overlay Blocking Chat Content

### Root Cause

The chat message card and map container did not create a constrained stacking context. Leaflet's default pane/control z-index values could therefore escape the map block and visually sit above later chat messages while scrolling.

Affected map types:

- Emission line map
- Raster concentration map
- Hotspot map
- Concentration point map

### Fix

Implemented a unified Leaflet stacking fix in `web/app.js`:

- Added `ensureLeafletStackingStyles()` to inject one global CSS override for all Leaflet maps.
- Added `assistant-message-row` and `assistant-message-card` wrappers with `position: relative` and `isolation: isolate`.
- Added `message-map-wrapper`, `message-map-surface`, and `message-map-container` classes to every map card/container.
- Forced Leaflet internals (`.leaflet-pane`, `.leaflet-top`, `.leaflet-bottom`, `.leaflet-control`, `.leaflet-popup-pane`) to stay inside the map container's lower z-index range.

Key locations:

- `web/app.js:121-214`
- `web/app.js:1238-1254`
- `web/app.js:1826-1840`
- `web/app.js:2632-2702`
- `web/app.js:2847-2859`

### Result

All four map renderers now scroll with their chat card instead of visually punching through later messages.

## Bug 2: Hotspot Analysis Showing 40s Duration

### Historical Symptom

Historical session trace:

- `data/sessions/fcfdcd66-0f4e-4aa0-9b2f-7ebb1c718f03/history/ed665754.json`
- `analyze_hotspots completed (39610ms)`

### Diagnosis

I replayed the real stored dispersion payload used by the hotspot flow:

- Source: `data/sessions/history/4b5712e5.json`
- Grid: `210 x 205`
- Receptors: `44172`
- `cell_receptor_map`: `42635`
- `receptor_top_roads`: `4935`

Diagnostic script output from `python3 diagnose_hotspot_perf.py`:

```text
== Historical Baseline ==
Historical trace: 39610 ms from data/sessions/fcfdcd66-0f4e-4aa0-9b2f-7ebb1c718f03/history/ed665754.json

== Payload Summary ==
Payload source: data/sessions/history/4b5712e5.json
rows: 210
cols: 205
resolution_m: 50.0
receptors: 44172
cell_receptor_map: 42635
cell_centers: 3422
receptor_top_roads: 4935
road_id_map: 20

== Analyzer Step Timings ==
matrix_extraction_s: 0.000667
threshold_calculation_s: 0.000326
hotspot_masking_s: 0.000025
clustering_s: 0.002383
building_hotspot_areas_s: 0.004826
analyze_total_s: 0.015594
hotspot_count: 10
raw_cluster_count: 36
kept_cluster_count: 10
selected_cells: 172
road_summary_per_hotspot: [1, 1, 3]

== Tool And Executor Timings ==
tool_success: True
tool_elapsed_s: 0.007882
executor_success: True
executor_elapsed_s: 0.008188
executor_trace_ms: 8.180000
executor_log_size_mb: 0.003805

== Legacy Verbose Logging Simulation ==
elapsed_s: 0.418185
log_size_mb: 29.153456
```

### Root Cause

`HotspotAnalyzer` itself was not slow.

The actual hotspot computation is millisecond-level:

- Analyzer total: `15.6ms`
- `HotspotTool.execute()`: `7.9ms`

The historical long duration came from the executor path handling a huge injected `_last_result` payload. Before the fix, `core/executor.py` logged and traced the full `_last_result` object. That payload contains:

- full `raster_grid`
- full `concentration_grid`
- `road_contributions`
- other nested spatial metadata

The old verbose argument logging produced about `29.15MB` of log text for a single hotspot call. On the historical runtime path, that overhead was counted inside the tool execution window and amplified into the observed `39610ms`.

### Fix

Implemented argument summarization in `core/executor.py`:

- Added `summarize_arguments()` and spatial payload summarizers.
- `_last_result` is now represented in logs and `_trace` as a compact summary.
- The executor no longer stringifies the full injected dispersion result.

Added debug-only hotspot step timing in `calculators/hotspot_analyzer.py`:

- matrix extraction
- threshold calculation
- hotspot masking
- clustering
- hotspot-area build
- source attribution
- total analyze time

Key locations:

- `core/executor.py:14-149`
- `core/executor.py:193-225`
- `calculators/hotspot_analyzer.py:103-141`
- `calculators/hotspot_analyzer.py:223-279`
- `calculators/hotspot_analyzer.py:426-494`

### Before / After

Before:

- Historical trace: `39610ms`
- Full payload argument logging
- Local legacy logging simulation: `0.418s`, `29.15MB` log file

After:

- `ToolExecutor.execute()`: `8.18ms`
- Executor log output for the same payload: `0.0038MB`
- Hotspot math remains millisecond-level

## Modified Files

- `web/app.js`
- `core/executor.py`
- `calculators/hotspot_analyzer.py`
- `diagnose_hotspot_perf.py`
- `tests/test_executor_large_args.py`

## Tests

Targeted:

- `pytest -q tests/test_executor_large_args.py tests/test_hotspot_analyzer.py tests/test_hotspot_tool.py`
- Result: `35 passed`

Router regression:

- `pytest tests/test_router_contracts.py -q`
- Result: `18 passed`

- `pytest tests/test_router_state_loop.py -q`
- Result: `8 passed`

Frontend syntax:

- `node -c web/app.js`
- Result: passed

Health check:

- `python main.py health`
- Result: all 8 tools OK

Full regression:

- `pytest -q`
- Result: `490 passed, 19 warnings in 45.85s`

## Final Outcome

- Leaflet maps no longer overlay later chat messages during scroll.
- Hotspot analysis no longer pays multi-MB executor logging overhead.
- The real hotspot algorithm remains lightweight, and the executor path now reports millisecond-level timings that match the actual computation.
