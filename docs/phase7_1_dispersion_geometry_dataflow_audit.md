# Phase 7.1 — Dispersion Geometry and Data-Flow Contract Audit

**Date:** 2026-05-01
**Branch:** `phase3-governance-reset`
**Baseline commit:** `e625bbc` (phase6e-canonical-state-closed)
**Scope:** Architecture/code audit + design document only. No implementation.

---

## 1. Baseline and Motivation

### 1.1 Current accepted state

- Phase 5.3 closed: A/B/E narrow governance repairs.
- Phase 6.1 closed: AO-scoped idempotency.
- Phase 6.E closed: canonical execution state, downstream handoff, revision invalidation.
- 30-task sanity with all three flags:
  - `completion_rate=0.80`, `tool_accuracy=0.80`
  - `parameter_legal_rate=0.8333`, `result_data_rate=0.7333`

### 1.2 Known residual debt

Task 120 is not a full PASS because `calculate_dispersion` fails due to missing spatial
geometry input. The governance layer correctly advances the chain macro→dispersion, but
the dispersion tool itself cannot execute because the emission results carry no usable
geometry.

This is **not** Phase 6.E state-governance debt. It is a **tool-layer data-flow
contract gap**: the dependency graph says dispersion requires `emission`, but dispersion
actually requires `emission + geometry`, and no component in the system guarantees that
geometry is available when dispersion is called.

### 1.3 Non-goals (repeated from the task brief)

- Do NOT implement fixes.
- Do NOT fake geometry.
- Do NOT change evaluator scoring.
- Do NOT modify tools/calculators/PCM.
- Do NOT change canonical execution state.
- Do NOT claim Task 120 full PASS.
- Do NOT paper-frame this as acceptable tradeoff.

---

## 2. Current Dispersion Failure Reconstruction

### 2.1 The execution path for Task 120

```
Turn 1: User uploads road network file (CSV/Excel) + "我需要扩散结果"
  → AO created, projected_chain=["calculate_macro_emission", "calculate_dispersion"]
  → analyze_file runs: detects macro_emission task_type, maps columns
  → calculate_macro_emission executes successfully
  → Results stored: per-link emissions (link_id, total_emissions_kg_per_hr, link_length_km, ...)
  → OASC after_turn: advances chain cursor → pending_next_tool=calculate_dispersion

Turn 2: "先用这个路网算NOx" or continuation
  → Chain preserved (Phase 5.3 E narrow)
  → ExecutionReadinessContract: dispersion action has requires_geometry_support=true
  → _determine_geometry_support() → checks file_context → NO spatial_metadata
  → NO geometry columns detected in tabular data → returns (False, None)
  → Readiness status: REPAIRABLE, reason_code="missing_geometry"
  → BUT: tool still executes (readiness is advisory, not gating at tool-execution boundary)
  → calculate_dispersion.execute() called
  → _resolve_emission_source() → gets _last_result from macro
  → EmissionToDispersionAdapter.adapt() → _extract_geometry()
  → Iterates results, looks for "geometry" key per row → NOT FOUND
  → Returns empty GeoDataFrame
  → "No road geometry found in emission results. Cannot compute dispersion without spatial data."
```

### 2.2 Why the readiness check doesn't prevent the failure

The readiness layer (`core/readiness.py:1142-1157`) correctly identifies that geometry
support is missing and returns `ReadinessStatus.REPAIRABLE`. However, the tool-execution
boundary in `governed_router.py` does not gate on readiness status for every tool call.
The readiness assessment is consumed primarily for action affordance display and workflow
template selection — it is not a hard pre-execution gate for tools invoked through the
inner_router fallback path.

### 2.3 Three interacting gaps

| Gap | Location | Effect |
|-----|----------|--------|
| G1: No geometry product type | `core/tool_dependencies.py` TOOL_GRAPH | Dispersion only declares `requires: [emission]`, not `requires: [emission, geometry]` |
| G2: Macro doesn't produce spatial emission token | `tools/macro_emission.py` | Even when geometry IS in input, macro doesn't emit a `spatial_emission` result token |
| G3: No deterministic geometry check before dispersion execution | `tools/dispersion.py:133-139` | Geometry check happens inside execute(), not at readiness/preflight boundary |

---

## 3. Current Tool and Data Contracts

### 3.1 calculate_dispersion input contract (`config/tool_contracts.yaml:456-595`)

```yaml
calculate_dispersion:
  required_slots: []          # No domain parameters are required
  optional_slots: [meteorology, pollutant, scenario_label]
  parameters:
    emission_source:          # "last_result" or file path (default: last_result)
    meteorology:              # preset name, "custom", or .sfc path
    wind_speed, wind_direction, stability_class, mixing_height:
    roughness_height:         # 0.05 | 0.5 | 1.0
    grid_resolution:          # 50 | 100 | 200
    pollutant:                # NOx (default), CO, PM2.5, ...
    scenario_label:
  dependencies:
    requires: [emission]      # ← ONLY declares emission
    provides: [dispersion]
  readiness:
    requires_geometry_support: true  # ← geometry flag is set but not in dependency graph
```

**What's missing from this contract:**
- Geometry is not listed as a dependency token alongside `emission`.
- `emission_source` parameter documents "last_result" but the contract doesn't express that
  the last_result must carry spatial data.
- No parameter for an explicit geometry source (separate geometry file, column mapping).

### 3.2 calculate_macro_emission output contract (`config/tool_contracts.yaml:202-357`)

```yaml
calculate_macro_emission:
  dependencies:
    requires: []
    provides: [emission]      # ← Only "emission", no spatial variant
  readiness:
    requires_geometry_support: false  # ← Macro doesn't need geometry to compute
```

**What macro actually produces** (from `tools/macro_emission.py`):
- `data.results`: per-link dicts with `link_id`, `total_emissions_kg_per_hr`, `link_length_km`,
  `avg_speed_kph`, `traffic_flow_vph`, `emission_rates_g_per_veh_km`
- Geometry is preserved IF the input had it: lines 832-844 merge `geometry`/`geom`/`wkt`/`shape`
  from original input links_data into each result row by link_id
- `map_data` is built separately with coordinates for visualization (lines 237-431)
- `result_ref` is stored as `"macro_emission:baseline"` (or with scenario_label)

**Key observation:** Macro already has the code to preserve geometry (lines 130-135 in
`_fix_common_errors`, lines 832-844 in `execute`), but it doesn't signal whether geometry
was actually preserved. The downstream consumer (dispersion) has no way to know if the
emission result is "spatial" or "non-spatial."

### 3.3 The dependency graph (`core/tool_dependencies.py`)

```python
TOOL_GRAPH = get_tool_contract_registry().get_tool_graph()
# Derived from tool_contracts.yaml dependencies.requires/provides
# Current effective graph:
#   calculate_macro_emission → provides: emission
#   calculate_dispersion → requires: emission, provides: dispersion
#   analyze_hotspots → requires: dispersion, provides: hotspot
#   render_spatial_map → requires: [layer_type]
```

The graph has no `geometry` or `spatial_emission` token. The `CANONICAL_RESULT_ALIASES`
mapping has no entry for geometry-related tokens.

### 3.4 The dispersion adapter (`calculators/dispersion_adapter.py`)

`EmissionToDispersionAdapter.adapt()` is the sole bridge between macro output and
dispersion input:

1. `_extract_geometry(results, geometry_source)`:
   - If `geometry_source` is a GeoDataFrame → uses it directly
   - If `geometry_source` is a list → merges with results by link_id
   - Iterates results looking for `"geometry"` key per row
   - Parses WKT, GeoJSON, coordinate lists via `_parse_geometry()`
   - Returns empty GeoDataFrame if no geometry found → **this is the failure point**

2. `_build_emissions_df(results, pollutant)`:
   - Extracts per-link emissions for the requested pollutant
   - Produces a DataFrame with NAME_1, data_time, pollutant_col, length

3. The adapter has **no fallback** when geometry is absent. It either finds geometry or
   returns empty.

---

## 4. Geometry Availability Audit

### 4.1 What analyze_file detects today

| Format | Geometry detection | Metadata produced |
|--------|-------------------|-------------------|
| Shapefile (.shp) | Full: `_extract_spatial_metadata()` → geometry_types, CRS, bounds, feature_count | `spatial_metadata` in analysis output |
| GeoJSON (.geojson) | Full: `_extract_geojson_spatial_metadata()` → geometry_types, bounds | `spatial_metadata` in analysis output |
| CSV/Excel with WKT column | **Partial**: column name detected but NOT classified as geometry column | No `spatial_metadata`; column appears in `columns` list only |
| CSV/Excel with lon/lat columns | **Partial**: columns detected as numeric, not classified as coordinate pairs | No `spatial_metadata`; columns appear in `columns` list |
| CSV/Excel with link_id only | No geometry | No spatial signals |

**The gap:** For tabular formats (CSV/Excel), `analyze_file` does excellent column-name
and value-range analysis for task_type identification, but does NOT produce
`spatial_metadata` or flag geometry-capable columns in the analysis output. The
`_analyze_structure()` method returns `columns` as a flat list with no geometry tagging.

### 4.2 What geometry_recovery.py detects (separate module)

`core/geometry_recovery.py` has a more comprehensive detection system:

- `_GEOMETRY_COLUMN_TOKENS`: geometry, geom, wkt, geojson, longitude, latitude, lon, lat, lng, x_coord, y_coord, coord_x, coord_y, start_lon, start_lat, end_lon, end_lat
- `_COORDINATE_PAIRS`: (longitude, latitude), (lon, lat), (lng, lat), (x_coord, y_coord), (coord_x, coord_y), (start_lon, start_lat), (end_lon, end_lat)
- `infer_geometry_capability_summary()`: checks spatial_metadata, geometry columns, coordinate pairs, dataset roles

**But this module is not called from the tool-execution hot path.** It's used by the
file_relationship_resolution and input_completion flows — not by the dispersion
readiness check or the dispersion tool itself.

### 4.3 What readiness.py checks (`_determine_geometry_support`)

The readiness layer checks geometry support in this order:

1. `file_context["spatial_metadata"]` — present for shapefiles/geojson, absent for CSV/Excel
2. `file_context["spatial_context"]` — present after geometry recovery re-grounding
3. `file_context["dataset_roles"]` — checks for spatial_context / supporting_spatial_dataset roles
4. Column name heuristics — checks if any column name matches geometry tokens
5. `result_payloads["emission"]` — checks if emission result has spatial payload

**Steps 1-3 fail for CSV/Excel without shapefile context.** Step 4 can work but only if
the column is named exactly "geometry", "wkt", etc. Step 5 fails because macro doesn't
tag its output with spatial metadata.

### 4.4 Geometry flow summary table

| Scenario | analyze_file detects geometry? | Macro preserves geometry? | Readiness sees geometry? | Dispersion gets geometry? |
|----------|-------------------------------|--------------------------|-------------------------|--------------------------|
| Shapefile input | Yes (spatial_metadata) | Yes (reads via geopandas, writes geometry) | Yes (spatial_metadata) | Yes (geometry in results) |
| GeoJSON input | Yes (spatial_metadata) | N/A (Goes through different path) | Yes (spatial_metadata) | Depends on adapter |
| CSV with WKT column | **No** (column detected but not tagged) | Yes (_fix_common_errors preserves it) | **No** (no spatial_metadata) | **No** (adapter looks for "geometry" key, WKT column name may not match) |
| CSV with lon/lat columns | **No** | **No** (lon/lat not in geometry field aliases) | **No** | **No** |
| CSV with link_id only | **No** | **No** | **No** | **No** |

**The critical failure case** (Task 120) is rows 3-5: tabular data without explicit
geometry metadata.

### 4.5 Are geometry signals persisted across turns?

- `AO.parameters_used` — does NOT include geometry-related keys
- `AO.metadata` — file analysis stored in `file_context` key, persists across turns
- `context_store` — stores tool results by type ("emission", "dispersion"), but no "geometry" type
- `fact_memory.file_analysis` — stores the analysis dict from analyze_file; contains columns list and spatial_metadata (if any)

**Verdict:** The raw column list and spatial_metadata ARE persisted in fact_memory and
available across turns. But the geometry-relevant columns are not tagged or flagged, so
downstream code cannot distinguish "this CSV has a WKT column" from "this CSV has no
spatial data at all."

---

## 5. Design Options

### 5.1 Option A: Macro output carries geometry forward unconditionally

**Description:** Modify `calculate_macro_emission` to always include a `has_geometry:
true/false` flag in its output, and when geometry is present, tag the result with a
`spatial_emission` token. Dispersion then requires `spatial_emission` instead of (or in
addition to) `emission`.

**Files touched:**
- `tools/macro_emission.py` — add `has_geometry` flag to output data; register
  `spatial_emission` result token when geometry present
- `config/tool_contracts.yaml` — macro provides: [emission, spatial_emission]
  (conditional); dispersion requires: [spatial_emission]
- `core/tool_dependencies.py` — add `spatial_emission` to TOOL_GRAPH and aliases
- `core/context_store.py` — register `spatial_emission` as known result type

**Pros:**
- Minimal change to existing flow
- Macro already has geometry-preservation code (lines 130-135, 832-844)
- Dispersion adapter already reads geometry from macro results
- Backward compatible: non-spatial emission still works for non-dispersion consumers

**Cons:**
- Doesn't help when geometry is truly absent from input
- Doesn't make geometry dependency visible in the dependency graph as a separate concern
- Conditional token provision adds complexity to downstream dependency resolution
- Still no deterministic gate: if macro runs without geometry, dispersion will still be
  called and fail

**Risk:** Low. The geometry-preservation code already exists. The main risk is getting
the conditional token registration right.

### 5.2 Option B: Dispersion resolves geometry from original file_context/file_path

**Description:** `calculate_dispersion` (or the adapter) re-reads the original file,
detects geometry columns using the same heuristics as `geometry_recovery.py`, and joins
by `link_id`/`road_id`/`NAME_1`.

**Files touched:**
- `calculators/dispersion_adapter.py` — add geometry resolution from file path
- `tools/dispersion.py` — pass file_path to adapter; add file re-read logic
- `core/geometry_recovery.py` — reuse `_detect_geometry_columns` and coordinate-pair
  detection

**Pros:**
- Dispersion becomes self-sufficient for geometry
- No change to macro output contract
- No new intermediate product types

**Cons:**
- File re-read adds I/O and potential inconsistency (file may have changed)
- Column-name heuristics are fragile; WKT detection by column name is unreliable
- Geometry resolution logic belongs in a separate concern, not inside the dispersion tool
- No audit trail: trace won't show where geometry came from
- Breaks single-responsibility: dispersion shouldn't also be a file parser

**Risk:** Medium. Fragile column-name heuristics; file may not be available at dispersion
time (especially in multi-turn).

### 5.3 Option C: Introduce a deterministic geometry resolver step

**Description:** Add a bounded, deterministic step that sits between macro and dispersion.
This could be:
- A new tool `resolve_spatial_geometry` that checks geometry availability and produces a
  `spatial_emission_layer` product
- Or an enrichment step inside macro that deterministically tags output with geometry
  metadata
- Or a pre-execution contract check that gates dispersion on geometry availability

**Files touched:**
- `config/tool_contracts.yaml` — new product type `spatial_emission`; update dispersion
  dependencies
- `core/tool_dependencies.py` — TOOL_GRAPH: dispersion requires [spatial_emission];
  macro provides [emission, spatial_emission] when geometry present
- `core/readiness.py` — enhance `_determine_geometry_support()` to check for
  geometry-column presence in tabular data
- `core/geometry_recovery.py` — already has the detection logic; needs to be wired into
  the readiness/execution boundary
- `tools/macro_emission.py` — tag output with geometry availability flag and
  `spatial_emission` token
- `calculators/dispersion_adapter.py` — minimal change; already reads geometry from
  results
- `core/trace.py` — add `GEOMETRY_SOURCE_DETECTED`, `GEOMETRY_RESOLVED`,
  `SPATIAL_EMISSION_PRODUCED` trace step types

**Pros:**
- Clean separation of concerns: geometry is a first-class dependency
- Geometry availability is checked deterministically before dispersion
- Trace shows geometry source (file column, spatial_metadata, user upload)
- Works for all input formats (shapefile, GeoJSON, CSV with WKT, CSV with lon/lat)
- No user clarification needed when geometry exists in uploaded file
- Dependency graph accurately reflects real requirements

**Cons:**
- More files changed than Option A
- New product type adds complexity to dependency resolution
- Requires careful handling of the "geometry in original input but not in macro output"
  edge case

**Risk:** Low-Medium. The detection logic already exists in `geometry_recovery.py`. The
main work is wiring it into the readiness and execution boundaries.

### 5.4 Option D: Targeted user clarification for missing geometry

**Description:** When geometry is absent, ask the user for a geometry file or column
specification. Use the existing input_completion flow. Avoid asking if the uploaded file
already contains usable geometry.

**Files touched:**
- `core/readiness.py` — enhance REPAIRABLE response with specific geometry prompts
- `core/input_completion.py` — add "missing_geometry" completion reason
- `core/geometry_recovery.py` — provide geometry-capability facts for clarification
  messages

**Pros:**
- Respects user intent: no invented geometry
- Uses existing input_completion infrastructure
- Can ask targeted questions: "Your file has lon/lat columns, should I use those as
  coordinates?" vs "Please upload a geometry file (shapefile/GeoJSON)"

**Cons:**
- Adds a turn: user must respond before dispersion proceeds
- User may not have a geometry file
- Doesn't fix the case where geometry IS in the file but not detected
- Only addresses the "geometry truly missing" case, not the detection gap

**Risk:** Low. Uses existing infrastructure. The main risk is asking when we shouldn't
(false positive for missing geometry).

---

## 6. Recommended Architecture

### 6.1 Recommendation: Option C + Option D (layered)

**Layer 1 — Deterministic geometry detection (Option C core):**

1. Enhance `analyze_file` output to include geometry-capability metadata for ALL formats
   (not just shapefile/GeoJSON). For tabular data, add:
   - `geometry_columns`: list of columns matching geometry tokens (wkt, geom, geometry, etc.)
   - `coordinate_columns`: list of lon/lat column pairs
   - `has_geometry_support`: boolean flag
   - `geometry_support_mode`: "spatial_metadata" | "geometry_column" | "coordinate_pair" | "none"

2. Add `spatial_emission` as a canonical result token:
   - `calculate_macro_emission` produces `spatial_emission` when geometry is present in
     input and preserved in output
   - `calculate_dispersion` requires `spatial_emission` (not just `emission`)
   - Readiness check validates `spatial_emission` availability before dispersion

3. Wire `geometry_recovery.py` detection into the readiness boundary:
   - `_determine_geometry_support()` already exists but needs to also check
     `file_context["geometry_columns"]` and `file_context["coordinate_columns"]`
   - These new fields flow from enhanced analyze_file output

**Layer 2 — Targeted clarification (Option D fallback):**

4. When geometry is truly absent (no spatial_metadata, no geometry columns, no coordinate
   pairs), the readiness layer returns REPAIRABLE with `reason_code="missing_geometry"`
   and a specific prompt:
   - "Your emission results don't contain spatial geometry. Please upload a geometry file
     (shapefile/GeoJSON/CSV with WKT or coordinate columns) or specify which columns
     contain coordinates."
   - This uses the existing `input_completion` infrastructure

5. When geometry IS in the file but wasn't detected (edge case), the enhanced
   analyze_file output ensures it IS detected.

### 6.2 Architecture diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        analyze_file                                  │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ Enhanced output:                                              │   │
│  │  - spatial_metadata (existing: shapefile/geojson)             │   │
│  │  - geometry_columns: ["wkt", "geom", ...]     ← NEW          │   │
│  │  - coordinate_columns: [["lon","lat"], ...]    ← NEW          │   │
│  │  - has_geometry_support: true/false             ← NEW          │   │
│  │  - geometry_support_mode: "spatial_metadata" |                │   │
│  │      "geometry_column" | "coordinate_pair" | "none"  ← NEW   │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ persisted in fact_memory.file_analysis
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    calculate_macro_emission                          │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ Input has geometry?                                           │   │
│  │  YES → preserve geometry in results                           │   │
│  │       → set output.has_geometry = true                        │   │
│  │       → register "spatial_emission" result token              │   │
│  │  NO  → set output.has_geometry = false                        │   │
│  │       → register "emission" result token only                 │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ result stored in context_store
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Readiness boundary (before dispersion)                  │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ Check: is "spatial_emission" available in context_store?      │   │
│  │  YES → READY                                                  │   │
│  │  NO  → Check file_context for geometry_columns/coords         │   │
│  │         → REPAIRABLE: "run macro first with geometry file"    │   │
│  │         → OR: REPAIRABLE: "upload geometry file"              │   │
│  │  NO + no file geometry → REPAIRABLE: "missing_geometry"       │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    calculate_dispersion                              │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ Requires: spatial_emission (not just emission)                │   │
│  │ Adapter reads geometry from macro results (already works)     │   │
│  │ If no geometry → hard error (shouldn't reach here)            │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.3 Dependency graph changes

```python
# Current
TOOL_GRAPH = {
    "calculate_macro_emission": {"requires": [], "provides": ["emission"]},
    "calculate_dispersion":    {"requires": ["emission"], "provides": ["dispersion"]},
}

# Recommended
TOOL_GRAPH = {
    "calculate_macro_emission": {"requires": [], "provides": ["emission", "spatial_emission"]},
    "calculate_dispersion":    {"requires": ["spatial_emission"], "provides": ["dispersion"]},
}

# With alias for backward compatibility
CANONICAL_RESULT_ALIASES = {
    "emission_result": "emission",
    "spatial_emission_result": "spatial_emission",
    "spatial_emission_layer": "spatial_emission",
    ...
}
```

### 6.4 Design principles satisfied

| Principle | How |
|-----------|-----|
| LLM should not invent geometry | Geometry only comes from file analysis (deterministic column detection) or user upload |
| Framework should deterministically check geometry availability | Readiness layer checks `spatial_emission` token + file_context geometry fields before allowing dispersion |
| Geometry dependency should be visible in ToolContract / readiness | `requires_geometry_support: true` already set; enhanced with `spatial_emission` token in dependency graph |
| If geometry missing, ask specifically for geometry file/columns | input_completion flow with "missing_geometry" reason code and specific prompts |
| If geometry exists in uploaded file, no user clarification needed | Enhanced analyze_file detects it; macro preserves it; readiness sees it |
| Trace should show geometry source and join method | New TraceStepType values: `SPATIAL_EMISSION_PRODUCED`, `GEOMETRY_DETECTED_IN_FILE`, `GEOMETRY_RESOLVED_FROM_COLUMN` |

---

## 7. Minimal Implementation Roadmap

### Phase 7.1 — Design/Audit (this document)
- [x] Audit all tool contracts, dependency graph, file analysis, geometry detection
- [x] Document failure reconstruction
- [x] Compare design options
- [x] Recommend architecture
- **Deliverable:** This document.

### Phase 7.2 — Geometry metadata detection in file analysis
- [ ] Enhance `tools/file_analyzer.py::_analyze_structure()` to detect geometry columns
  - Add `geometry_columns` field: detect columns matching geometry tokens (wkt, geom,
    geometry, shape, geojson)
  - Add `coordinate_columns` field: detect lon/lat, longitude/latitude, x/y pairs
  - Add `has_geometry_support` and `geometry_support_mode` fields
- [ ] Enhance `_analyze_shapefile_structure()` and `_analyze_geojson_structure()` to
  consistently populate these new fields
- [ ] Wire `geometry_recovery.py::_detect_geometry_columns` and `_detect_coordinate_pairs`
  into the file analysis path (or deduplicate: keep one canonical implementation)
- [ ] Add `spatial_metadata` to tabular analysis when geometry columns are detected
  (currently only produced for shapefile/GeoJSON)
- **Tests:** CSV with WKT column → geometry detected; CSV with lon/lat → coordinates
  detected; CSV without geometry → no false positive

### Phase 7.3 — ToolContract and dependency graph updates
- [ ] Add `spatial_emission` to `CANONICAL_RESULT_ALIASES` in
  `core/tool_dependencies.py`
- [ ] Update `TOOL_GRAPH` (via `tool_contracts.yaml`):
  - `calculate_macro_emission.provides`: add `spatial_emission`
  - `calculate_dispersion.requires`: change from `[emission]` to `[spatial_emission]`
- [ ] Update `config/tool_contracts.yaml`:
  - `calculate_dispersion.dependencies.requires`: `[spatial_emission]`
  - Keep `readiness.requires_geometry_support: true`
- [ ] Add `spatial_emission` to `context_store` known result types
- [ ] Add trace step types: `SPATIAL_EMISSION_PRODUCED`, `GEOMETRY_DETECTED_IN_FILE`,
  `GEOMETRY_RESOLVED_FROM_COLUMN`
- **Tests:** Dependency validation correctly requires spatial_emission for dispersion;
  macro with geometry produces spatial_emission token; macro without geometry does not

### Phase 7.4 — Geometry propagation and readiness gating
- [ ] Modify `tools/macro_emission.py::execute()`:
  - After calculation, check if results contain geometry
  - Set `data["has_geometry"] = True/False`
  - When True, register `spatial_emission` result token in addition to `emission`
- [ ] Enhance `core/readiness.py::_determine_geometry_support()`:
  - Check for `spatial_emission` in available result tokens
  - Check `file_context["geometry_columns"]` and `file_context["coordinate_columns"]`
    from enhanced analyze_file
- [ ] Ensure readiness REPAIRABLE reason for missing geometry includes specific,
  actionable prompts based on what IS available (e.g., "Your file has lon/lat columns but
  macro was run without them — re-run macro")
- [ ] Add trace emission for geometry source detection
- **Tests:** Shapefile input → dispersion ready after macro; CSV with WKT → dispersion
  ready after macro; CSV without geometry → dispersion REPAIRABLE; geometry source
  appears in trace

### Phase 7.5 — Task 120 and 30-task sanity verification
- [ ] Run Task 120 with geometry-capable input → full PASS
- [ ] Run Task 120 without geometry → targeted clarification, no crash
- [ ] Run 30-task sanity with all three flags → verify no regression
- [ ] Verify: macro repeat rate unchanged or improved
- [ ] Verify: parameter_legal_rate and result_data_rate unchanged or improved
- **Tests:** All Phase 7.2-7.4 targeted tests pass; existing tests pass

---

## 8. Test and Verification Plan

### 8.1 Unit tests for geometry detection (Phase 7.2)

| Test | Input | Expected |
|------|-------|----------|
| CSV with WKT column named "wkt" | CSV: link_id, length, flow, speed, wkt | `has_geometry_support=true`, `geometry_columns=["wkt"]`, `geometry_support_mode="geometry_column"` |
| CSV with geometry column named "geometry" | CSV: link_id, length, flow, geometry | `has_geometry_support=true`, `geometry_columns=["geometry"]` |
| CSV with lon/lat columns | CSV: link_id, length, lon, lat | `has_geometry_support=true`, `coordinate_columns=[["lon","lat"]]`, `geometry_support_mode="coordinate_pair"` |
| CSV with longitude/latitude columns | CSV: link_id, longitude, latitude | `has_geometry_support=true`, `coordinate_columns=[["longitude","latitude"]]` |
| CSV with no geometry columns | CSV: link_id, length, flow, speed | `has_geometry_support=false`, `geometry_support_mode="none"` |
| Shapefile input | .shp with link attributes | `has_geometry_support=true`, `geometry_support_mode="spatial_metadata"`, `spatial_metadata` populated |
| GeoJSON input | .geojson FeatureCollection | `has_geometry_support=true`, `geometry_support_mode="spatial_metadata"` |

### 8.2 Unit tests for dependency graph (Phase 7.3)

| Test | Input | Expected |
|------|-------|----------|
| dispersion requires spatial_emission | TOOL_GRAPH lookup | `get_required_result_tokens("calculate_dispersion")` returns `["spatial_emission"]` |
| macro provides spatial_emission | TOOL_GRAPH lookup | `"spatial_emission" in TOOL_GRAPH["calculate_macro_emission"]["provides"]` |
| dispersion missing spatial_emission | No spatial_emission in available tokens | `get_missing_prerequisites` returns `["spatial_emission"]` |
| dispersion ready with spatial_emission | spatial_emission available | `get_missing_prerequisites` returns `[]` |

### 8.3 Unit tests for geometry propagation (Phase 7.4)

| Test | Input | Expected |
|------|-------|----------|
| Macro with geometry input | links_data with geometry field | `result.data.has_geometry == True`, spatial_emission token registered |
| Macro without geometry input | links_data without geometry | `result.data.has_geometry == False`, only emission token registered |
| Readiness: geometry in file_context | file_context with geometry_columns | `_determine_geometry_support()` → (True, "geometry_column_signal") |
| Readiness: spatial_emission in results | result_payloads with spatial_emission | `_determine_geometry_support()` → (True, "spatial_emission_token") |
| Readiness: no geometry anywhere | bare file_context, no spatial_emission | `_determine_geometry_support()` → (False, None) |
| Dispersion blocked when no spatial_emission | Readiness assessment for run_dispersion | status=REPAIRABLE, reason_code="missing_geometry" |
| Dispersion proceeds when geometry available | spatial_emission token available | status=READY |

### 8.4 Integration tests (Phase 7.5)

| Test | Scenario | Expected |
|------|----------|----------|
| Shapefile → macro → dispersion | Full chain with shapefile input | Both tools succeed, dispersion produces concentration field |
| CSV with WKT → macro → dispersion | CSV has WKT column | Both tools succeed |
| CSV without geometry → macro → dispersion | CSV has no spatial columns | Macro succeeds, dispersion returns REPAIRABLE, user asked for geometry |
| CSV with lon/lat → macro → dispersion | CSV has coordinate pairs | Both tools succeed (macro handles lon/lat → geometry conversion) |
| Multi-turn: geometry file uploaded on turn 2 | Turn 1: CSV without geometry → macro; Turn 2: geometry file upload → dispersion | Turn 2: geometry recovery attaches spatial support, dispersion succeeds |
| Task 120 with geometry input | Full e2e Task 120 | Dispersion executes successfully, task reaches full PASS |
| Trace contains geometry source | Any geometry-capable run | Trace shows GEOMETRY_DETECTED_IN_FILE or SPATIAL_EMISSION_PRODUCED |

---

## 9. Risks and User Decision Points

### 9.1 Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| CSV column name heuristics miss geometry | Medium | Use `geometry_recovery.py` token list (already comprehensive); add value-based WKT detection (string starts with "LINESTRING", "POLYGON", etc.) |
| Macro geometry-preservation breaks for edge cases | Low | Existing code already handles WKT, GeoJSON, coordinate lists, and shapefile; just needs flagging |
| `spatial_emission` token backward compatibility | Low | Keep `emission` token as well; non-dispersion consumers (render_spatial_map for emission map) still use `emission` |
| Multi-turn: geometry file uploaded late | Medium | Existing geometry_recovery.py handles re-grounding; wire into readiness refresh |
| Evaluator changes needed | Low | No evaluator changes; only tool-contract changes that make dependencies more accurate |

### 9.2 User decision points

1. **Should `spatial_emission` be a hard dependency for dispersion?**
   - Yes. The current soft-check (readiness advisory) allows dispersion to execute and
     fail. A hard dependency in the dependency graph means the governance layer
     deterministically blocks dispersion before execution when geometry is absent.

2. **Should we ask the user for geometry or try harder to find it automatically?**
   - Try deterministically first (column detection, spatial_metadata, coordinate pairs).
     Only ask when all deterministic methods fail. The clarification prompt should be
     specific: "I found columns 'lon' and 'lat' in your file but they weren't used in
     the emission calculation. Would you like me to re-run with these as coordinates?"

3. **Should we convert lon/lat pairs to LineString geometry automatically?**
   - For dispersion purposes, yes. If the file has start_lon/start_lat and
     end_lon/end_lat per row, these can be deterministically converted to LineString
     geometry. If the file has only single lon/lat per row (point locations), these are
     not usable for line-source dispersion and should trigger clarification.

4. **What about the case where link_id exists but no geometry?**
   - This is the "external geometry lookup" case (link_id → road network database). It
     is out of scope for Phase 7.x. The system should ask the user for a geometry file
     rather than attempting to fetch from an external service.

---

## 10. Non-Goals (Repeated)

- Do NOT implement fixes in this phase (7.1 is audit only).
- Do NOT fake or synthesize geometry from link attributes.
- Do NOT change evaluator scoring or benchmarks.
- Do NOT modify tools/calculators/PCM.
- Do NOT change canonical execution state.
- Do NOT claim Task 120 full PASS until Phase 7.5 verification.
- Do NOT paper-frame missing geometry as an acceptable tradeoff.
- Do NOT add external geometry lookup services (GIS database, OSM, etc.).
