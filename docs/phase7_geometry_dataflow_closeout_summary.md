# Phase 7 — Geometry Data-Flow Architecture Closeout Summary

## 1. Baseline Commits and Tags

| Phase | Commit | Tag | Description |
|-------|--------|-----|-------------|
| 7.1 | `f03e654` | — | Dispersion geometry data-flow audit (design doc) |
| 7.2 | `c686b8a` | `phase7_2-geometry-metadata-detection` | GeometryMetadata detection in FileContext |
| 7.3 | `6ab33b6` | `phase7_3-spatial-dependency-contracts` | ToolContract geometry requirements |
| 7.4A | `c9a6c3a` | `phase7_4a-spatial-emission-resolver` | SpatialEmissionCandidate + resolver |
| 7.4B | `e128ca7` | `phase7_4b-spatial-emission-preflight` | Spatial precondition in readiness |
| 7.4C | — | — | test_data geometry inventory (44 A, 6 C, 12 B) |
| 7.5 | `edb98de` | `phase7_5-direct-spatial-emission-bridge` | SpatialEmissionLayer model |
| 7.5B | `0d0fc69` | `phase7_5b-dispersion-spatial-layer-bridge` | Dispersion consumes direct layer |
| 7.5C | `e1d333e` | `phase7_5-direct-geometry-closed` | Verification + closeout |
| 7.6A | `7e9a7ef` | `phase7_6a-join-key-resolver-design` | Join-key resolver design |
| 7.6B/C | `b5f657d` | `phase7_6bc-join-key-geometry-resolver` | Resolver + synthetic fixtures |
| 7.6D | `74defcf` | `phase7_6d-join-key-readiness-integration` | Readiness integration |
| 7.6E | `5bbc1ff` | `phase7_6e-multifile-geometry-discovery` | Auto-discovery via context_store |
| 7.6F | `2d0e5fa` | `phase7_6f-filecontext-storage-wiring` | Router wiring for multi-file |

**Current baseline:** `2d0e5fa` on `phase3-governance-reset`

## 2. What Phase 7 Solved

**Problem (Phase 7.1 audit):** `calculate_dispersion` failed because the system had three gaps:
- **G1:** No `spatial_emission` product type in the dependency graph
- **G2:** `calculate_macro_emission` didn't signal geometry availability
- **G3:** No deterministic geometry check before dispersion execution

**Solution:** A three-path layered architecture spanning 16 phases:

### Path 1: Direct Geometry (7.1–7.5C)
File has WKT/GeoJSON/linestring → GeometryMetadata detected → macro emission → spatial_emission_layer → readiness READY → router bridge → dispersion executes. Zero formula changes.

### Path 2: Join-Key Geometry (7.6A–7.6F)
Emission file has link_id but no geometry + user provides geometry file with matching keys:
- analyze emission file → store FileContext (7.6F)
- analyze geometry file → store FileContext (7.6F)
- readiness auto-discovers geometry from context_store (7.6E)
- find_best_geometry_file_context evaluates overlap (7.6E)
- resolve_join_key_geometry_layer matches keys deterministically (7.6B/C)
- ≥95% match → auto-accept, spatial_emission_layer produced
- 80–95% match → needs user confirmation
- <80% match → rejected with diagnostic
- Dispersion consumes layer identically to direct path (7.5B)

### Path 3: Missing Geometry (7.4B)
No geometry, no geometry file → targeted Chinese diagnostic → REPAIRABLE. No fake geometry.

## 3. Direct Geometry Path

```
test_6links.xlsx (WKT column)
  → file_analyzer._detect_geometry_metadata()
  → geometry_type: wkt, road_geometry_available: True
  → calculate_macro_emission → success, 6 results
  → build_spatial_emission_layer() → layer_available: True
  → readiness → READY, spatial_emission_layer_available
  → router bridge → _spatial_emission_layer injected
  → _load_geometry_from_spatial_layer() → 6 WKT rows
  → EmissionToDispersionAdapter.adapt(geometry_source=...) → 6 LineString rows
  → DispersionCalculator.calculate() → concentration_grid, raster_grid, road_contributions
```

**Key invariant:** `EmissionToDispersionAdapter.adapt()` already supported
`geometry_source` parameter and WKT parsing via `shapely.wkt.loads()` — zero
formula or math changes needed for the entire direct geometry bridge.

## 4. Join-Key Geometry Path

```
Emission file (link_id only) + Geometry file (link_id + WKT)
  Step 1: analyze_file (emission) → store_analyzed_file_context()
          geometry_type: join_key_only, join_key_columns: {link_id: link_id}
  Step 2: analyze_file (geometry) → store_analyzed_file_context()
          geometry_type: wkt, road_geometry_available: True
  Step 3: SessionContextStore stores both FileContexts (metadata only)
  Step 4: Readiness for calculate_dispersion:
          - emission is join_key_only, no explicit geometry_file_context
          - find_geometry_file_contexts() → [geometry FileContext]
          - find_best_geometry_file_context() evaluates candidate
          - resolve_join_key_geometry_layer() resolves keys
          - ≥95% match → ACCEPT → spatial_emission_layer produced
          - READY, join_key_geometry_resolved, spatial_emission_layer_available
  Step 5: Router bridge + dispersion consume layer (identical to direct path)
```

### Resolver Safety Rules
| Rule | Behavior |
|------|----------|
| Exact normalized key match | Required — no fuzzy, no prefix stripping |
| Numeric string/int coercion | `"1001"` ↔ `1001` → matched |
| Float→int coercion | `1001.0` → `"1001"` → matched |
| Duplicate geometry keys (identical) | Deduplicated, accepted |
| Duplicate geometry keys (conflicting) | Rejected as ambiguous |
| Row-order join | Never accepted |
| ≥95% match | Auto-accept |
| 80–95% match | Needs user confirmation |
| <80% match | Rejected |

### Auto-Discovery Rules
| Scenario | Behavior |
|----------|----------|
| Single ACCEPT candidate | Auto-selected |
| Multiple ACCEPT with clear winner | Highest unique match_rate selected |
| Multiple ACCEPT tied | REPAIRABLE — user must choose |
| Only NEEDS_USER_CONFIRMATION | REPAIRABLE — user must confirm |
| All REJECT | REPAIRABLE with diagnostic |
| No candidates | join_key_without_geometry (existing) |

## 5. Missing Geometry Path

Three diagnostic tiers for files without usable road geometry:

| Condition | reason_code | Message |
|-----------|-------------|---------|
| No geometry columns or join keys | `missing_road_geometry` | "请上传含 WKT/GeoJSON/起终点坐标的几何文件" |
| Join keys only, no geometry file | `join_key_without_geometry` | "请额外上传含路段几何的 Shapefile/GeoJSON 文件" |
| Point-only coordinates | `point_geometry_not_road_geometry` | "仅检测到点位坐标，扩散分析需要线段或多边形几何" |
| Zero key overlap with geometry file | `zero_key_overlap` | "排放文件与几何文件中的路段ID完全不匹配" |
| Partial match (<95%) | `partial_key_overlap` | "部分路段ID匹配，请确认几何文件是否正确" |

All messages in Chinese for user remediation. No geometry invention.

## 6. Verification Evidence

### 6.1 Targeted Test Suite

**439/440 tests pass** (1 pre-existing async-framework environment failure, unrelated to geometry changes):

| Suite | Tests | Status |
|-------|-------|--------|
| `test_multifile_geometry_context_discovery.py` | 21 | All pass |
| `test_join_key_readiness_integration.py` | 16 | All pass |
| `test_join_key_geometry_resolver.py` | 22 | All pass |
| `test_dispersion_spatial_layer_bridge.py` | 14 | 13 pass, 1 async env |
| `test_spatial_emission_layer.py` | 21 | All pass |
| `test_spatial_emission_preflight.py` | 14 | All pass |
| `test_spatial_emission_resolver.py` | 20 | All pass |
| `test_spatial_dependency_contract.py` | 19 | All pass |
| `test_file_geometry_metadata.py` | 23 | All pass |
| `test_file_analysis_hydration.py` | 7 | All pass |
| Core/invalidation/canonical suites | ~242 | All pass |

### 6.2 30-Task Sanity (Phase 7 Closeout)

Configuration: `--mode router --parallel 4 --smoke --cache`

| Metric | Phase 7.6F | Phase 7.5C (baseline) |
|--------|-----------|----------------------|
| completion_rate | 0.7667 | 0.7333 |
| tool_accuracy | 0.7667 | 0.7333 |
| parameter_legal_rate | 0.8333 | 0.80 |
| result_data_rate | 0.7333 | 0.7333 |
| infrastructure_health | 30/30 OK | 30/30 OK |
| wall_clock | 295.39s | 285.97s |

By category:

| Category | Tasks | Success Rate |
|----------|-------|-------------|
| simple | 3 | 1.00 |
| code_switch_typo | 3 | 1.00 |
| constraint_violation | 3 | 1.00 |
| incomplete | 3 | 1.00 |
| user_revision | 3 | 1.00 |
| multi_step | 4 | 0.75 |
| parameter_ambiguous | 3 | 0.67 |
| ambiguous_colloquial | 4 | 0.50 |
| multi_turn_clarification | 4 | 0.25 |

**All failures are LLM understanding issues** (colloquial Chinese, multi-turn clarification, code-switching). Zero geometry bridge failures. The 0.7667 tool_accuracy is within normal LLM noise range compared to the Phase 7.5C 0.7333 baseline.

### 6.3 Controlled Smokes

| Smoke | Result |
|-------|--------|
| Direct WKT (test_6links) | ACCEPT, layer_available=true, dispersion executes |
| Synthetic 100% match | ACCEPT, join_key_geometry_resolved |
| Synthetic 90% match | NEEDS_USER_CONFIRMATION, not auto-ready |
| Synthetic 70% / 0% match | REJECT |
| Real C-class × real geometry | zero_key_overlap, no fake geometry |
| No geometry file | join_key_without_geometry |
| Point-only geometry | point_geometry_not_road_geometry |
| Auto-discovery from store | READY, spatial_emission_layer_available |

## 7. Explicit Non-Claims

- **No external geometry lookup** — no OSM, Baidu Maps, or network matching APIs.
- **No fuzzy matching** — keys matched exactly after deterministic normalization.
- **No row-order join** — explicit key columns required.
- **No dispersion formula/math changes** — `EmissionToDispersionAdapter.adapt()` and
  `DispersionCalculator.calculate()` are unchanged from before Phase 7.
- **No macro emission formula changes** — `MacroEmissionTool` is unchanged.
- **No evaluator/scoring changes** — evaluation metrics unchanged.
- **No 180-task benchmark** — only 30-task smoke run for sanity.
- **No PCM, AO classifier, or canonical state changes** — these subsystems are
  untouched by Phase 7.

## 8. Remaining Debts

| Debt | Status | Recommendation |
|------|--------|---------------|
| Async-framework test env | 1 test fails in `test_dispersion_spatial_layer_bridge.py` due to missing `pytest-asyncio` | Install `pytest-asyncio` or use `anyio` plugin |
| FileContext storage try/except silence | `store_analyzed_file_context` call in router wraps with `except: pass` | Add debug-level logging for transparency |
| Real external geometry mapping UX | No UI for user to upload separate geometry file mid-workflow | Phase 7.7 UX design if needed |
| LLM multi-turn clarification (25%) | LLM understanding, not geometry bridge | Separate LLM capability work |
| LLM colloquial/code-switch handling (~50%) | LLM understanding, not geometry bridge | Separate LLM capability work |
| 180-task benchmark | Not run | Deferred per non-goals |

## 9. Architecture Finalization Judgment

The Phase 7 geometry data-flow architecture is now a **deterministic, three-path
framework** with zero LLM involvement in geometry decisions:

1. **Direct geometry path** (7.1–7.5C): WKT/GeoJSON/lonlat_linestring in emission file
   → GeometryMetadata → spatial_emission_layer → dispersion.
2. **Join-key geometry path** (7.6A–7.6F): link_id-only emission file + user-supplied
   geometry file → store FileContexts → auto-discover → resolve join keys →
   spatial_emission_layer → dispersion.
3. **Missing geometry path** (7.4B): no geometry → targeted Chinese diagnostic →
   REPAIRABLE. No geometry invention.

All three paths are:
- **Deterministic** — no LLM inference in geometry classification or key matching
- **Test-covered** — 439 passing tests across spatial, resolver, integration, and core suites
- **No-regression** — 30-task sanity within LLM noise range of prior baseline
- **Formula-unchanged** — dispersion and macro emission math untouched
- **Serializable** — all models use dataclasses with `to_dict()`/`from_dict()`

### Complete Phase 7 chain:
```
f03e654 → 7.1 audit
c686b8a → 7.2 geometry metadata detection
6ab33b6 → 7.3 spatial dependency contracts
c9a6c3a → 7.4A spatial emission resolver
e128ca7 → 7.4B spatial emission preflight
edb98de → 7.5 spatial emission layer model
0d0fc69 → 7.5B dispersion layer bridge
e1d333e → 7.5C direct geometry closeout
7e9a7ef → 7.6A join-key design
b5f657d → 7.6B/C join-key resolver + fixtures
74defcf → 7.6D readiness integration
5bbc1ff → 7.6E multi-file auto-discovery
2d0e5fa → 7.6F router wiring
```

## 10. Recommended Next Phase

**Phase 8: 30-task stability or paper/evaluation consolidation.**
- Run clean 30-task sanity with active governance/canonical flags to establish a
  stable multi-phase baseline.
- Consider consolidating evaluation artifacts and trace quality for paper readiness.
- LLM understanding cleanup (multi-turn clarification, colloquial handling) is a
  separate concern and should not block architecture closure.
