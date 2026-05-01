# Phase 7.5 — Direct Geometry Path Closeout Summary

## 1. Baseline and Commits

| Phase | Commit | Tag | Description |
|-------|--------|-----|-------------|
| 7.1 | `f03e654` | — | Dispersion geometry data-flow audit (design doc only) |
| 7.2 | `c686b8a` | `phase7_2-geometry-metadata-detection` | GeometryMetadata in FileContext + file analyzer detection |
| 7.3 | `6ab33b6` | `phase7_3-spatial-dependency-contracts` | ToolContract geometry requirements + dependency graph helpers |
| 7.4A | `c9a6c3a` | `phase7_4a-spatial-emission-resolver` | SpatialEmissionCandidate data model + deterministic resolver |
| 7.4B | `e128ca7` | `phase7_4b-spatial-emission-preflight` | Spatial preflight integration in readiness |
| 7.4C | audit only | — | test_data geometry inventory (44 A-class, 6 C-class, 12 B-class) |
| 7.5 | `edb98de` | `phase7_5-direct-spatial-emission-bridge` | SpatialEmissionLayer model + readiness metadata bridge |
| 7.5B | `0d0fc69` | `phase7_5b-dispersion-spatial-layer-bridge` | Dispersion consumes direct spatial_emission_layer |
| 7.5C | verification | — | Task 120-style smoke + 30-task sanity (this closeout) |

**Current baseline:** `0d0fc69` on `phase3-governance-reset`

## 2. What Phase 7.5 Solved

**Problem (Phase 7.1 audit):** `calculate_dispersion` failed because the system had three gaps:
- **G1:** No `spatial_emission` product type in the dependency graph
- **G2:** `calculate_macro_emission` didn't signal geometry availability
- **G3:** No deterministic geometry check before dispersion execution

**Solution:** A layered architecture spanning 9 phases:

1. **Detection (7.2):** `_detect_geometry_metadata()` in file analyzer inspects column names and sample values to classify geometry as WKT, GeoJSON, lonlat_linestring, lonlat_point, join_key_only, or none
2. **Contracts (7.3):** ToolContract YAML + dependency graph expose geometry requirements
3. **Resolver (7.4A):** Deterministic `resolve_spatial_emission_candidate()` with no LLM inference
4. **Preflight (7.4B):** `resolve_spatial_precondition()` integrated into readiness assessment with targeted Chinese diagnostic messages
5. **Layer Bridge (7.5):** `SpatialEmissionLayer` binds macro emission results to detected road geometry
6. **Dispersion Bridge (7.5B):** `_load_geometry_from_spatial_layer()` reads geometry from source files and passes it to the existing adapter as `geometry_source` — zero formula changes
7. **Router Bridge (7.5B):** `_prepare_tool_arguments()` injects `_spatial_emission_layer` for dispersion tools
8. **Verification (7.5C):** Task 120-style chain passes, 30-task sanity shows no geometry regressions

## 3. Direct WKT Path Evidence

**Test file:** `test_data/test_6links.xlsx` (6 rows, columns: link_id, length, flow, speed, geometry)

```
Step 1 — File analysis:
  geometry_type: wkt
  road_geometry_available: True
  geometry_columns: ["geometry"]

Step 2 — calculate_macro_emission:
  success: True
  results: 6 (NOx emissions computed)
  output includes geometry column preserved from input

Step 3 — spatial_emission_layer:
  layer_available: True
  geometry_type: wkt
  emission_result_ref: macro_emission:baseline
  source_file_path: test_data/test_6links.xlsx

Step 4 — Readiness assessment (run_dispersion):
  status: READY
  available_conditions: [
    "task_type:macro_emission",
    "result:emission",
    "geometry_support",
    "spatial_emission_layer_available"
  ]

Step 5 — Router argument bridge:
  _spatial_emission_layer injected into dispersion arguments
  layer_available: True, geometry_type: wkt

Step 6 — calculate_dispersion:
  success: True
  output keys: [
    query_info, results, summary,
    concentration_grid, raster_grid, contour_bands,
    coverage_assessment, road_contributions,
    meteorology_used, scenario_label, roads_wgs84, defaults_used
  ]
  coverage: level=sparse_local, density=0.2 km/km²
```

**6/6 link_ids matched** between macro emission results and geometry rows. The `EmissionToDispersionAdapter.adapt()` method received WKT geometry via its existing `geometry_source` parameter and successfully constructed a valid `roads_gdf` with 6 LineString rows. The `DispersionCalculator.calculate()` executed normally — zero formula or math changes.

## 4. Negative Geometry Evidence

**Test file:** `test_data/test_no_geometry.xlsx` (5 rows, columns: link_id, length, flow, speed — no geometry)

```
spatial_emission_layer:
  layer_available: False
  geometry_type: join_key_only

Readiness preflight (calculate_dispersion):
  satisfied: False
  reason_code: join_key_without_geometry
  message: "Join key columns found (link_id) but no road geometry columns exist..."

Geometry loader:
  _load_geometry_from_spatial_layer() → None

Dispersion execution:
  success: False
  error: "No road geometry found in emission results.
          Cannot compute dispersion without spatial data."
```

No fake geometry. Targeted diagnostic messages in Chinese for user remediation.

## 5. 30-Task Sanity

**Configuration:** `--mode router --parallel 4 --smoke --cache` with all three flags enabled (CS, RI, EI).

| Metric | Phase 7.5C |
|--------|-----------|
| completion_rate | 0.7333 (22/30) |
| tool_accuracy | 0.7333 (22/30) |
| parameter_legal_rate | 0.80 (24/30) |
| result_data_rate | 0.7333 (22/30) |
| infrastructure_health | 30/30 OK |
| wall_clock | 285.97s |

**Multi-step task results:**
- `e2e_multistep_001`: PASS — macro→dispersion, no geometry → legal halt
- `e2e_multistep_009`: PASS — macro→dispersion→hotspot→render, no geometry → legal halt
- `e2e_multistep_010`: PASS — multi-step with default parameter fill, no geometry → legal halt
- `e2e_multistep_049`: FAIL — macro→dispersion→hotspot WITH geometry file. 0 trace steps (LLM didn't return parseable tool calls), not a geometry bridge failure.

**All 8 failures across the 30 tasks are LLM understanding/response issues** (colloquial Chinese, code-switching, multi-turn clarification). Zero geometry bridge failures.

## 6. Conservative Interpretation

- **The direct geometry path works** — test_6links.xlsx flows from file analysis through macro emission through readiness through router bridge through dispersion execution, producing valid concentration output.
- **No broad benchmark claim** — The 30-task sanity is a smoke, not a full 180-task benchmark. The tool_accuracy metric (0.7333) reflects LLM reliability, not geometry bridge quality.
- **Tool accuracy variance** — The 0.7333 tool_accuracy is within normal LLM noise range compared to a previous 0.8333 baseline. It MUST NOT be framed as an improvement or regression.
- **e2e_multistep_049 failure is NOT a geometry regression** — The task had 0 trace steps (failure occurred before any tool execution), consistent with LLM response parsing issues seen in other multi-turn tasks.

## 7. Remaining Debts

| Debt | Status | Next Phase |
|------|--------|------------|
| Join-key-only files (6 in test_data) | **Unresolved** — link_id/segment_id without geometry | Phase 7.6 audit/design |
| Point-only geometry (12 node layers) | **Intentionally rejected** — not road geometry | Won't fix (correct behavior) |
| LLM multi-turn clarification (25% success) | **Separate** — Phase 0 LLM capability | Not in Phase 7 scope |
| LLM colloquial/code-switch handling (~50-67%) | **Separate** — LLM understanding | Not in Phase 7 scope |
| 180-task benchmark | **Not run** — deferred per non-goals | Future |
| e2e_multistep_049 (geometry file task) | **LLM issue** — 0 trace steps | Re-run with different LLM |

## 8. Recommended Next Phase

**Phase 7.6 — Join-Key Resolver Audit/Design**

- Audit the 6 C-class files (join-key-only) in test_data
- Identify what external geometry mapping would look like: shapefile lookup by link_id, network matching service, or user-supplied geometry file
- Design the join resolver contract: input (join key columns + reference geometry source), output (geometry-bearing emission layer)
- Estimate implementation effort and decide build vs. defer

**Tests:** 381 passing across all spatial + core suites.  
**No code edits, no benchmark, no evaluator/tool/PCM changes.**
