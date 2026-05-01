# Phase 7.6 — Join-Key Geometry Resolver Design

## 1. Baseline and Motivation

### 1.1 Current State (Phase 7.5 closed)

The direct geometry path is fully operational:
```
file (WKT/GeoJSON) → file_analyzer (GeometryMetadata) →
  macro_emission → spatial_emission_layer →
  readiness (READY) → router bridge → dispersion execution
```

`test_6links.xlsx` passes end-to-end. `test_no_geometry.xlsx` correctly fails with
`join_key_without_geometry` and targeted Chinese diagnostic messages.

### 1.2 Remaining Gap

Seven C-class (join-key-only) files exist in `test_data/test_tables/`:

| File | Rows | Join Key Column | Key Type | Sample Values |
|------|------|----------------|----------|---------------|
| `test_no_geometry.xlsx` | 5 | `link_id` | string | L0001–L0005 |
| `macro_01_standard_en.csv` | 20 | `link_id` | string | Link_001–Link_020 |
| `macro_02_chinese_columns.xlsx` | 15 | `路段ID` | string | 路段_A1–路段_E5 |
| `macro_03_full_moves_types.csv` | 25 | `link_id` | string | Segment_01–Segment_25 |
| `macro_04_urban_network.xlsx` | 20 | `LinkName` | string | 快速路_R01–支路_R05 |
| `macro_05_highway_network1.csv` | 35 | `segment_id` | string | G1-K010–G5-K070 |
| `macro_05_highway_network - 副本.csv` | 35 | `segment_id` | string | G1-K010–G5-K070 (copy) |

These files contain no WKT, no GeoJSON, no lon/lat columns — only join keys.
They cannot produce a `spatial_emission_layer` today.

### 1.3 Problem Statement

When a user uploads an emission file with `link_id` / `road_id` / `segment_id`
but no geometry, the framework needs a **deterministic, non-LLM** path to bind
it to a user-provided geometry file, producing a valid `SpatialEmissionLayer`
that flows through the same readiness → router → dispersion bridge as direct
geometry (Phase 7.5).

### 1.4 Strict Non-Goals

- Do NOT implement the resolver yet (this is a design document).
- Do NOT use external map APIs (no OSM, no Baidu Maps, no network matching service).
- Do NOT invent geometry for join-key-only rows.
- Do NOT treat point-only files as road geometry.
- Do NOT change dispersion formula/math.
- Do NOT change macro emission formula/math.
- Do NOT change evaluator scoring, PCM, AO classifier, or canonical state logic.
- Do NOT run 30-task or 180-task benchmark.
- Do NOT modify existing tool execution paths.

## 2. Join-Key-Only File Inventory

### 2.1 Complete Inventory

Seven files in `test_data/` that are join-key-only (C-class from Phase 7.4C):

**File 1: `test_no_geometry.xlsx`**
- Rows: 5
- Columns: `link_id`, `length`, `flow`, `speed`
- Join key: `link_id` (string, pattern: `L0001`–`L0005`)
- Normalized key type: string with non-numeric prefix
- Geometry columns: none
- Notes: Minimal test file created specifically for negative geometry testing

**File 2: `test_tables/macro_01_standard_en.csv`**
- Rows: 20
- Columns: `link_id`, `link_length_km`, `traffic_flow_vph`, `avg_speed_kph`, `Passenger Car%`, `Bus%`, `Truck%`
- Join key: `link_id` (string, pattern: `Link_001`–`Link_020`)
- Normalized key type: string with `Link_` prefix + zero-padded numeric suffix
- Geometry columns: none

**File 3: `test_tables/macro_02_chinese_columns.xlsx`**
- Rows: 15
- Columns: `路段ID`, `长度(km)`, `交通流量(辆/小时)`, `平均速度(km/h)`, vehicle type percentages
- Join key: `路段ID` (string, pattern: `路段_A1`–`路段_E5`)
- Normalized key type: Chinese semantic identifier with letter-number suffix
- Geometry columns: none

**File 4: `test_tables/macro_03_full_moves_types.csv`**
- Rows: 25
- Columns: `link_id`, `length_km`, `flow_vph`, `speed_kph`, 13 MOVES vehicle type columns
- Join key: `link_id` (string, pattern: `Segment_01`–`Segment_25`)
- Normalized key type: string with `Segment_` prefix + zero-padded numeric suffix
- Geometry columns: none

**File 5: `test_tables/macro_04_urban_network.xlsx`**
- Rows: 20
- Columns: `LinkName`, `Type`, `Len_km`, `Flow`, `Speed`, `Car%`, `Taxi%`, `Bus%`, `Truck%`
- Join key: `LinkName` (string, pattern: `快速路_R01`–`支路_R05`)
- Normalized key type: Chinese road class + pseudonym
- Geometry columns: none
- Notes: `LinkName` is in Phase 7.2's `_JOIN_KEY_TOKENS` as `"link_name"`, `"linkname"` — this would be detected as a join key

**File 6: `test_tables/macro_05_highway_network1.csv`**
- Rows: 35
- Columns: `segment_id`, `highway`, `length_km`, `traffic_flow_vph`, `avg_speed`, vehicle percentages
- Join key: `segment_id` (string, pattern: `G1-K010`–`G5-K070`)
- Normalized key type: highway-km marker semantic code
- Geometry columns: none
- Notes: `segment_id` is in Phase 7.2's `_JOIN_KEY_TOKENS`

**File 7: `test_tables/macro_05_highway_network - 副本.csv`**
- Rows: 35
- Columns: `segment_id`, `highway`, `length_km`, `avg_speed`, vehicle percentages (no `traffic_flow_vph`)
- Join key: `segment_id` (same values as file 6)
- Normalized key type: same as file 6
- Notes: Copy of file 6 without the flow column

### 2.2 Common Characteristics

All seven C-class files share these traits:
1. **Synthetic keys**: All use human-readable semantic identifiers, not numeric network IDs
2. **String type**: All join keys are strings with alphanumeric/Chinese characters
3. **No geometry columns**: No WKT, GeoJSON, lon/lat columns of any kind
4. **Valid emission data**: All have the columns needed for macro emission (link length, flow, speed, vehicle composition)
5. **Self-contained**: Each file is a complete emission input — only missing geometry
6. **No external reference**: None reference an external geometry file by path or name

## 3. Geometry Mapping Candidate Inventory

### 3.1 Direct WKT XLSX Files

| File | Rows | Geometry | Key Column | Key Type | Has Emission Data |
|------|------|----------|------------|----------|-------------------|
| `test_6links.xlsx` | 6 | WKT LINESTRING | `link_id` | numeric | Yes (length, flow, speed) |
| `test_20links.xlsx` | 20 | WKT LINESTRING | `link_id` | numeric | Yes (length, flow, speed) |
| `test_shanghai_full.xlsx` | 150 | WKT LINESTRING | `link_id` | numeric | Yes (length, flow, speed) |
| `test_shanghai_allroads.xlsx` | 25,370 | WKT LINESTRING | `link_id` | numeric | Yes (length, flow, speed) |

These are **emission+geometry** files — they contain both emission data AND WKT
geometry. For Phase 7.5 they serve as direct-geometry inputs. For Phase 7.6 they
could serve as geometry *mapping* files if an emission-only file shared their
link_id space.

### 3.2 Shapefile Candidates

| File | Rows | Geometry | Key Column | Key Type |
|------|------|----------|------------|----------|
| `test_20links/test_20links.shp` | 20 | LineString | `link_id` | numeric |
| `test_shanghai_allroads/.../test_shanghai_allroads.shp` | 25,370 | LineString | `link_id` | numeric |
| `test_subnets/1km_hd_irregular_changning_02/links.shp` | 125 | LineString | `link_id` | numeric |
| `test_subnets/1km_hd_regular_jingan_01/links.shp` | 54 | LineString | `link_id` | numeric |
| `test_subnets/1km_ld_corridor_songjiang_06/links.shp` | 10 | LineString | `link_id` | numeric |
| `test_subnets/1km_ld_sparse_pudong_05/links.shp` | 13 | LineString | `link_id` | numeric |
| `test_subnets/1km_md_mixed_pudong_03/links.shp` | 18 | LineString | `link_id` | numeric |
| `test_subnets/1km_md_trunk_minhang_04/links.shp` | 40 | LineString | `link_id` | numeric |
| `test_subnets/2km_hd_irregular_minhang_02/links.shp` | 246 | LineString | `link_id` | numeric |
| `test_subnets/2km_hd_regular_jingan_01/links.shp` | 96 | LineString | `link_id` | numeric |
| `test_subnets/2km_ld_corridor_baoshan_06/links.shp` | 14 | LineString | `link_id` | numeric |
| `test_subnets/2km_ld_sparse_qingpu_05/links.shp` | 24 | LineString | `link_id` | numeric |
| `test_subnets/2km_md_mixed_qingpu_03/links.shp` | 48 | LineString | `link_id` | numeric |
| `test_subnets/2km_md_trunk_fengxian_04/links.shp` | 42 | LineString | `link_id` | numeric |

All subnet shapefiles share the same schema (20+ columns including `link_id`,
`id`, `highway`, `name`, `length`, etc.) and use numeric link_ids from the real
Shanghai OSM network.

**Additional files:**
- `test_data/师兄测试/路网图层/roads.shp` — 159 rows, has columns `OBJECTID`, `FID_sh2017`, `ID`, `siteid`, `NAME_1` but **no `link_id`** column. Not usable as a mapping file without column renaming.
- `test_data/精简文件/*/` — 12 shapefiles, duplicates of the `test_subnets/` shapefiles, also with `link_id` columns.
- `test_data/师兄测试/逐小时排放数据_插值以补全缺失值.csv` — 1,392,840 rows, has `site_name`, `vtype_id`, `volume`, `speed`, etc. Uses `site_name` not `link_id`. Emission file, no geometry.

### 3.3 Key Space Characteristics

All geometry-bearing files use **numeric link_ids** drawn from the real Shanghai
OSM road network. The link_ids range from single-digit (`2`) to 6-digit
(`163012`). They correspond to real road segments in Shanghai.

All C-class emission files use **string keys** with semantic prefixes
(`Link_`, `Segment_`, `G1-K`, `路段_`, `快速路_`, `L`). These are synthetic
identifiers generated for testing.

## 4. Matching Matrix and Findings

### 4.1 Full Cross-Product Result

7 C-class emission files × 18 geometry candidates = 126 pairs evaluated.
Complete inventory written to `/tmp/phase7_6a_join_key_geometry_inventory.json`.

**Result: ZERO pairs with any key overlap.**

| Metric | Value |
|--------|-------|
| Total pairs | 126 |
| ACCEPT (≥95% overlap) | 0 |
| NEEDS_USER_CONFIRMATION (80–95%) | 0 |
| REJECT (<80% or 0%) | 126 |
| Non-zero overlap | 0 |

### 4.2 Root Cause

The C-class files use **synthetic semantic keys** generated for isolated testing
(e.g., `Link_001`, `Segment_01`). The geometry files use **real numeric Shanghai
OSM link_ids** (e.g., `38625`, `14250`, `127489`). These are fundamentally
different key spaces with no possible deterministic match.

### 4.3 Implications for Resolver Design

1. **The current test_data cannot validate a join-key resolver end-to-end**
   without synthetic geometry files that share the C-class key space.

2. **In real user scenarios, keys WILL match**: A user who exports emission
   data from a network model and provides the matching shapefile will have
   the same link_ids in both files. The 0% overlap finding is an artifact of
   test data construction, not a reflection of real-world failure.

3. **For testing Phase 7.6, new synthetic test files are needed**:
   - Either: synthetic geometry files with matching synthetic keys
   - Or: synthetic emission files using real Shanghai link_ids

4. **The resolver must handle the zero-overlap case gracefully**: When a user
   provides a geometry file whose keys don't match, the resolver must produce
   a clear diagnostic showing the mismatch and asking for the correct file.

### 4.4 Key Type Compatibility Issues

Even if keys overlapped, type normalization would be required:

| Emission Key Type | Geometry Key Type | Normalization |
|-------------------|-------------------|---------------|
| string (`"Link_001"`) | numeric (`38625`) | Cannot normalize — different key spaces |
| string (`"38625"`) | numeric (`38625`) | String→numeric coercion or vice versa |
| string (`"L0001"`) | string (`"L0001"`) | Direct match after trim+normalize |
| Chinese (`"路段_A1"`) | Chinese (`"路段_A1"`) | Direct match after trim |

The current test_data has case 1 exclusively. Real usage is predominantly case 2
or case 3 (string representation of numeric IDs).

## 5. Proposed Join-Key Resolver Contract

### 5.1 Core Function Signature

```python
def resolve_join_key_geometry_layer(
    emission_file_context: Dict[str, Any],
    geometry_file_context: Dict[str, Any],
    emission_result_ref: Optional[str] = None,
    join_key_mapping: Optional[Dict[str, str]] = None,
) -> SpatialEmissionLayer:
```

### 5.2 Input Requirements

**emission_file_context** must contain:
- `file_path`: path to emission CSV/XLSX
- `geometry_metadata`: Phase 7.2 output with `geometry_type == "join_key_only"`
- `geometry_metadata.join_key_columns`: detected join key columns
- `row_count`: number of emission rows

**geometry_file_context** must contain:
- `file_path`: path to geometry file (XLSX with WKT column, SHP, GeoJSON)
- `geometry_metadata`: Phase 7.2 output with `road_geometry_available == True`
- `geometry_metadata.geometry_columns`: detected geometry column names
- `geometry_metadata.join_key_columns`: detected join key columns (may differ from emission)

**join_key_mapping** (optional):
- Maps emission join key column names to geometry file column names
- Example: `{"LinkName": "link_id"}` when column names differ
- When absent, the resolver infers mapping from normalized column name overlap

### 5.3 Processing Steps

```
Step 1: Validate preconditions
  - emission_file_context.geometry_type == "join_key_only"
  - geometry_file_context.road_geometry_available == True
  - geometry_file_context has at least one geometry column with valid values

Step 2: Resolve join key column mapping
  - If join_key_mapping provided: use it directly
  - Otherwise: normalize all column names (lowercase, trim, strip underscores/hyphens)
  - Intersect normalized emission join keys with normalized geometry join keys
  - If no intersection: attempt fuzzy match (one column name contains the other)
  - If still no intersection: REJECT with diagnostic listing available columns

Step 3: Load and normalize keys
  - Load emission keys from emission_file_context.file_path
  - Load geometry keys from geometry_file_context.file_path
  - Normalize each key: str(v).strip()
  - For numeric keys stored as float (1.0 → "1"): strip trailing ".0"
  - Record key type (string vs numeric) for provenance

Step 4: Compute overlap
  - emission_only = emission_keys - geometry_keys
  - geometry_only = geometry_keys - emission_keys
  - matched = emission_keys ∩ geometry_keys
  - match_rate = len(matched) / len(emission_keys)
  - Record duplicate keys on geometry side (same link_id appears multiple times)

Step 5: Apply safety thresholds (see Section 6)
  - match_rate >= 95% and no duplicate geometry keys → ACCEPT
  - match_rate >= 80% and < 95% → NEEDS_USER_CONFIRMATION
  - match_rate < 80% → REJECT
  - Duplicate geometry keys with different geometry → REJECT (ambiguous)
  - Duplicate geometry keys with identical geometry → ACCEPT (deduplicate)

Step 6: Build SpatialEmissionLayer
  - geometry_type: from geometry_file_context
  - source_file_path: geometry_file_context.file_path (geometry source)
  - emission_result_ref: from parameter
  - join_key_columns: actual mapping used
  - row_count: len(emission_keys)
  - confidence: min(match_rate, 0.95) adjusted for type compatibility
  - evidence: [match statistics, key normalization method, column mapping]
  - limitations: [unmatched_rows list if any, type coercion notes]
  - provenance:
      resolver_version: "7.6"
      join_method: "deterministic_key_match"
      emission_file: emission_file_context.file_path
      geometry_file: geometry_file_context.file_path
      key_mapping: actual column mapping used
      match_rate: float
      unmatched_emission_keys: list (if any)
```

### 5.4 Return Value

Returns a `SpatialEmissionLayer` identical in structure to Phase 7.5's direct
geometry layer. Key differences in the returned layer:

| Field | Direct Geometry (7.5) | Join-Key (7.6) |
|-------|----------------------|----------------|
| `source_file_path` | Emission file (has geometry col) | Geometry file (separate file) |
| `geometry_type` | `wkt`/`geojson`/`lonlat_linestring` | Same, from geometry file |
| `geometry_column` | Column in emission file | Column in geometry file |
| `join_key_columns` | Present but unused | Present and **used for join** |
| `provenance.join_method` | `"direct"` | `"deterministic_key_match"` |
| `provenance.match_rate` | N/A | 0.0–1.0 |
| `provenance.unmatched_emission_keys` | N/A | List if partial match |

### 5.5 Error Modes

| Condition | reason_code | Return |
|-----------|-------------|--------|
| Emission file has direct geometry | `direct_geometry_present` | Delegate to `build_spatial_emission_layer()` (7.5) |
| No geometry file provided | `missing_geometry_file` | `layer_available=False`, message asking for geometry file |
| Geometry file has no road geometry | `geometry_file_no_road_geometry` | `layer_available=False` |
| No compatible join key columns | `no_compatible_join_keys` | `layer_available=False`, message listing available columns |
| Zero key overlap (match_rate=0) | `zero_key_overlap` | `layer_available=False`, message with sample keys from both sides |
| Partial match (80–95%) | `partial_key_overlap` | `layer_available=True`, `limitations` lists unmatched, recommend user review |
| Duplicate geometry keys (ambiguous) | `ambiguous_duplicate_geometry_keys` | `layer_available=False`, reject unless identical |
| All checks pass | `join_key_resolved` | `layer_available=True` |

## 6. Safety Rules and Thresholds

### 6.1 Match Rate Thresholds

| Match Rate | Auto Decision | Rationale |
|------------|---------------|-----------|
| ≥ 95% | ACCEPT | High confidence — emission and geometry files clearly from same network |
| 80%–95% | NEEDS_USER_CONFIRMATION | Some keys missing — user should verify this is the correct geometry file |
| < 80% | REJECT | Too many missing keys — likely wrong geometry file |

### 6.2 Duplicate Key Rules

- **Duplicate emission keys**: Allowed. Multiple emission rows per link are valid
  (e.g., different time periods, vehicle types, pollutants).
- **Duplicate geometry keys with identical geometry**: Allowed, deduplicated
  automatically. Same link_id appearing twice with the same LINESTRING is noise.
- **Duplicate geometry keys with different geometry**: **REJECTED**. Same
  link_id with two different LINESTRING values is ambiguous. User must resolve.
- **Never join on row order alone**: The resolver requires explicit key columns.
  Row-index-based joins are silently incorrect and must be rejected.

### 6.3 Key Normalization Rules

1. **Trim whitespace**: `str(v).strip()` for all keys
2. **Case normalization**: String keys normalized to lowercase for matching only
   when both sides are string-typed. If one side is numeric, numeric coercion is
   attempted first.
3. **Numeric string coercion**: If emission keys are strings containing only
   digits (e.g., `"38625"`) and geometry keys are numeric (`38625`), both are
   normalized to string form for matching. The coercion is recorded in
   provenance.
4. **Float→int coercion**: If geometry keys are float `38625.0` and emission
   keys are string `"38625"`, the float is converted to int string `"38625"`.
   Only applied when the float has zero fractional part.
5. **No prefix stripping**: The resolver does NOT strip semantic prefixes
   (`Link_`, `Segment_`, `路段_`). If emission uses `Link_001` and geometry uses
   `001`, this is treated as zero overlap. Automatic prefix removal would
   introduce silent false matches.
6. **No fuzzy matching**: The resolver does NOT use edit distance, substring
   matching, or LLM-based fuzzy key matching. Keys either match exactly (after
   normalization) or they don't.

### 6.4 Geometry Column Validation

When the geometry file is an XLSX/CSV with a WKT column:
- Sample at least 3 rows for valid WKT values using the same `_is_wkt_value()`
  check already in `_detect_geometry_metadata()`
- If zero samples contain valid WKT: REJECT with `geometry_file_no_valid_wkt`

When the geometry file is a shapefile:
- All rows must have non-null, non-empty geometry
- Geometry type must be LineString or MultiLineString (Polygon also acceptable)
- Point-only shapefiles: REJECT with `point_geometry_not_road_geometry`

### 6.5 Emission Column Preservation

The resolver matches geometry to emission rows but does NOT modify the emission
data. The `_load_geometry_from_spatial_layer()` function (Phase 7.5B) reads
geometry from the **geometry file**, keyed by `link_id`. The emission data flows
through separately via the existing emission path. The adapter joins them:

```
emission_rows (from macro_emission result) +
geometry_rows (from geometry file, keyed by link_id) →
  EmissionToDispersionAdapter.adapt(geometry_source=geometry_rows)
```

## 7. User Clarification Policy

### 7.1 When Emission File is Join-Key-Only and No Geometry File Present

**Trigger**: File analysis returns `geometry_type: "join_key_only"` and no
geometry file is in the session.

**Agent behavior** (readiness → REPAIRABLE):
- `reason_code`: `"join_key_without_geometry"`
- Chinese message: `"Join key columns found (link_id) but no road geometry columns exist. Please provide a separate geometry file (shapefile/GeoJSON) or add WKT/start-end coordinate columns to enable road-segment dispersion."`
- This is **already implemented** in Phase 7.4B. No changes needed.

**After Phase 7.6 implementation**, the message should additionally suggest:
- `"请上传含匹配 link_id 的路网几何文件（Shapefile/GeoJSON/含 WKT 的 Excel 文件）。"`

### 7.2 When User Provides a Geometry File but Keys Don't Match

**Trigger**: Resolver runs, `match_rate == 0`.

**Agent behavior**:
- `reason_code`: `"zero_key_overlap"`
- Message: `"No matching link_ids found between emission file ({n_em} keys, e.g. {samples}) and geometry file ({n_geo} keys, e.g. {samples}). Please verify this is the correct geometry file for this emission data."`
- Chinese: `"排放文件与几何文件中的路段 ID 完全不匹配。排放文件示例：{samples}，几何文件示例：{geo_samples}。请确认是否上传了正确的几何文件。"`

### 7.3 When Multiple Candidate Geometry Files Exist

**Trigger**: Multiple shapefiles/GeoJSON/WKT files in the session, any of which
could match.

**Decision**: Automatic selection when exactly one candidate has ≥95% match rate.
When multiple candidates meet the threshold: ask user to choose, presenting
match rates for each.

```
Multiple geometry files match the emission data:
1. roads_detail.shp — 98% overlap (49/50 links matched)
2. roads_simplified.shp — 92% overlap (46/50 links matched)
Which file should be used for dispersion?
```

### 7.4 When Join Key Column Names Differ

**Trigger**: Emission file uses `LinkName`, geometry file uses `link_id`.

**Agent behavior**:
- If the mapping is unambiguous (only one join key on each side, and key
  values overlap ≥95%): auto-accept, record the mapping in provenance.
- If both sides have multiple potential join key columns: present options to
  user.
- Never rename columns silently without recording the mapping.

### 7.5 When Match Rate is Partial (80–95%)

**Trigger**: Resolver runs, 80% ≤ `match_rate` < 95%.

**Agent behavior**:
- Produce `layer_available=True` with `limitations` listing unmatched keys.
- Readiness returns READY but with caveat in available_conditions.
- User is informed: `"几何匹配率 {rate:.0%}，{n_unmatched} 个路段在几何文件中未找到。将继续计算已匹配路段的扩散。"`
- Unmatched emission rows are excluded from dispersion (not from emission
  results).

### 7.6 Clarification Flow Diagram

```
File Upload
    │
    ▼
file_analyzer → geometry_type?
    │
    ├── wkt/geojson/lonlat_linestring → Phase 7.5 direct path (READY)
    ├── lonlat_point → Phase 7.4B REJECT (point not road)
    ├── join_key_only → check for geometry files in session
    │       │
    │       ├── no geometry file → REPAIRABLE (ask user)
    │       ├── one or more geometry files → run resolver
    │       │       │
    │       │       ├── match ≥ 95% → READY (auto)
    │       │       ├── match 80–95% → READY with caveat
    │       │       ├── match = 0% → REPAIRABLE (wrong file?)
    │       │       └── multiple high-match → ask user to choose
    │       └── (user uploads geometry file) → re-run resolver
    └── none → Phase 7.4B REJECT (no geometry)
```

## 8. Integration Architecture

### 8.1 Where the Resolver Fits

```
Phase 7.2: file_analyzer._detect_geometry_metadata()
    → produces GeometryMetadata (including join_key_only detection)
    ↓
Phase 7.6: resolve_join_key_geometry_layer()  ← NEW
    → consumes emission FileContext + geometry FileContext
    → produces SpatialEmissionLayer
    ↓
Phase 7.5: readiness._build_spatial_emission_layer_from_results()
    → recognizes spatial_emission_layer_available
    → passes to assess_action_readiness()
    ↓
Phase 7.5B: router._prepare_tool_arguments()
    → injects _spatial_emission_layer for calculate_dispersion
    ↓
Phase 7.5B: dispersion._load_geometry_from_spatial_layer()
    → reads geometry from source file (now: geometry file, not emission file)
    → passes to EmissionToDispersionAdapter.adapt(geometry_source=...)
```

The key integration point is in `_build_spatial_emission_layer_from_results()` in
`core/readiness.py`. Currently it only calls `build_spatial_emission_layer()`
for direct geometry. After Phase 7.6, it should also check for join-key-only
files and attempt resolution:

```python
def _build_spatial_emission_layer_from_results(
    file_context, current_tool_results, context_store=None,
) -> Optional[Dict[str, Any]]:
    gm = file_context.get("geometry_metadata") or {}
    geometry_type = gm.get("geometry_type", "none")

    # Phase 7.5: direct geometry
    if geometry_type in _ACCEPTABLE_TYPES:
        layer = build_spatial_emission_layer(file_context=file_context, ...)
        if layer.layer_available:
            return layer.to_dict()

    # Phase 7.6: join-key resolution  ← NEW
    if geometry_type == "join_key_only":
        geometry_fc = _find_geometry_file_in_context(context_store)
        if geometry_fc:
            layer = resolve_join_key_geometry_layer(
                emission_file_context=file_context,
                geometry_file_context=geometry_fc,
            )
            return layer.to_dict()
        # else: return None → readiness will flag as REPAIRABLE (existing behavior)

    return None
```

### 8.2 Geometry File Discovery

`_find_geometry_file_in_context()` scans `context_store` for previously analyzed
files whose `geometry_metadata.road_geometry_available == True`. Returns the
most recent such FileContext, or None.

This avoids a separate "upload geometry file" step — any geometry-bearing file
already in the session is automatically considered as a candidate.

### 8.3 File Analysis Stage

`file_analyzer.py` requires zero changes for Phase 7.6. It already:
- Detects `join_key_only` geometry type
- Extracts join key column names
- Records evidence and limitations

The new resolver consumes this output as-is.

### 8.4 Dispersion Consumption

`tools/dispersion.py` requires **zero changes** for Phase 7.6. It already:
- Accepts `_spatial_emission_layer` kwarg
- Calls `_load_geometry_from_spatial_layer()` which reads geometry from the
  layer's `source_file_path`
- Passes geometry rows to `EmissionToDispersionAdapter.adapt(geometry_source=...)`

For join-key resolution, the only difference is that `source_file_path` points
to the **geometry file** instead of the emission file. The loader reads geometry
rows from that file, keyed by link_id, and the adapter matches them to emission
results by link_id — identical to the direct path.

### 8.5 Trace Recording

In `core/trace.py`, add a new `TraceStepType`:
```python
JOIN_KEY_GEOMETRY_RESOLVED = "join_key_geometry_resolved"
```

Record when the resolver produces a layer:
- `join_method`: `"deterministic_key_match"`
- `match_rate`: match fraction
- `key_mapping`: column mapping used
- `unmatched_count`: count of emission keys without geometry
- `geometry_file`: geometry file path

### 8.6 No Changes Required In

- `tools/macro_emission.py` — no formula or execution changes
- `calculators/dispersion_adapter.py` — already supports `geometry_source`
- `calculators/dispersion_calculator.py` — no formula changes
- `core/tool_dependencies.py` — `spatial_emission_layer` already declared
- `core/router.py` — already injects `_spatial_emission_layer`
- `core/evaluator.py` — no scoring changes
- `core/parameter_negotiation.py` — no parameter changes
- `core/canonical_execution_state.py` — no state model changes

## 9. Implementation Roadmap

### Phase 7.6A (this document)
- [x] Audit C-class files
- [x] Inventory geometry candidates
- [x] Build matching matrix
- [x] Design resolver contract
- [x] Define thresholds and safety rules
- [x] Design user clarification policy
- [x] Specify integration architecture

### Phase 7.6B — Resolver Implementation (~3 files, ~200 lines)
1. `core/spatial_emission_resolver.py`: Add `resolve_join_key_geometry_layer()`
   (~120 lines)
2. `core/readiness.py`: Add `_find_geometry_file_in_context()`, update
   `_build_spatial_emission_layer_from_results()` to call resolver (~30 lines)
3. `core/trace.py`: Add `JOIN_KEY_GEOMETRY_RESOLVED` TraceStepType (~5 lines)

### Phase 7.6C — Synthetic Test Data Generation
1. Create matching emission-geometry file pairs:
   - `test_tables/macro_join_test_emission.csv`: 10 rows, link_ids `J001`–`J010`
   - `test_tables/macro_join_test_geometry.xlsx`: 10 rows, link_ids `J001`–`J010`,
     WKT geometry column
   - `test_tables/macro_join_test_partial_emission.csv`: 10 rows, link_ids
     `J001`–`J010`, geometry for J001–J008 only (80% match)
   - `test_tables/macro_join_test_mismatch_emission.csv`: 10 rows, link_ids
     `X001`–`X010` (0% match with any geometry file)

### Phase 7.6D — Targeted Tests (~15 tests)
Test file: `tests/test_join_key_geometry_resolver.py`
1. Full match → layer_available=True
2. Partial match (80%) → layer_available=True with limitations
3. Zero overlap → layer_available=False, zero_key_overlap
4. No geometry file → layer_available=False, missing_geometry_file
5. Point-only geometry file → rejected
6. Duplicate geometry keys (identical) → accepted
7. Duplicate geometry keys (different) → rejected
8. String↔numeric key coercion
9. Float↔int key coercion
10. Different column names (LinkName ↔ link_id) → resolved via mapping
11. Chinese column names (路段ID) → resolved via mapping
12. Emission file with direct geometry → delegates to 7.5 path
13. Empty emission file → handled gracefully
14. Empty geometry file → handled gracefully
15. Readiness bridge calls resolver for join_key_only files

### Phase 7.6E — Documentation Closeout
1. Update `docs/phase7_6_join_key_geometry_resolver_design.md` with
   implementation notes
2. Commit with tag `phase7_6-join-key-resolver`

## 10. Test and Verification Plan

### 10.1 Unit Tests (Phase 7.6D)

See Section 9, Phase 7.6D — 15 targeted tests.

### 10.2 Integration Smoke (Phase 7.6E)

**Smoke A**: Happy path — matching emission + geometry files
- File: `macro_join_test_emission.csv` (10 links, join_key_only)
- Geometry: `macro_join_test_geometry.xlsx` (10 links, WKT, same keys)
- Expected: macro_emission success → spatial_emission_layer from join resolver
  → readiness READY → dispersion success

**Smoke B**: Partial match — 80% overlap
- File: `macro_join_test_partial_emission.csv` (10 links, geometry for 8)
- Expected: macro_emission success → spatial_emission_layer with 80% match_rate
  → readiness READY with limitations → dispersion for 8/10 links

**Smoke C**: Mismatch — wrong geometry file
- File: `macro_join_test_mismatch_emission.csv` (X001–X010)
- Geometry: `macro_join_test_geometry.xlsx` (J001–J010)
- Expected: resolver returns layer_available=False, reason_code=zero_key_overlap,
  readiness REPAIRABLE

**Smoke D**: No geometry file (existing behavior)
- File: `macro_01_standard_en.csv` (join_key_only, no geometry file)
- Expected: join_key_without_geometry diagnostic (already passes in Phase 7.5C)

### 10.3 Regression Check

Run existing test suites:
- `tests/test_spatial_emission_layer.py` (21 tests)
- `tests/test_dispersion_spatial_layer_bridge.py` (14 tests)
- `tests/test_spatial_emission_preflight.py` (12 tests)
- `tests/test_spatial_emission.py` (Phase 7.4A tests)
- `tests/test_spatial_emission_candidate.py` (Phase 7.4A tests)

All must pass unchanged. Target: 0 regressions.

### 10.4 30-Task Sanity (deferred to user request)

Run with `--mode router --parallel 4 --smoke --cache` to verify no regression
in multi-task scenarios.

## 11. Risks and User Decision Points

### 11.1 Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Keys don't match (wrong geometry file) | Medium | Low — user retries | Clear diagnostic with sample keys from both sides |
| Keys look numeric but are stored as float (1.0 vs "1") | Medium | Low — silent mismatch | Float→int→string coercion in normalization |
| Geometry file has more links than emission (coverage high but inverse low) | Low | Low — user can verify | Report both match_rate and geo_coverage |
| Duplicate link_ids in geometry with different shapes | Low | High — ambiguous geometry | Reject with diagnostic, ask user to deduplicate |
| Large geometry file (25K+ rows) with small emission (10 rows) — loading cost | Medium | Low — performance | Load only matching rows if key set is small |
| User provides geometry file that is also an emission file (has flow, speed) | Medium | Low — extra columns ignored | Take only the geometry column + join key column |

### 11.2 User Decision Points

1. **Which geometry file to use?** — When multiple candidates exist, user must
   choose. Auto-select when exactly one has ≥95% match.

2. **Partial match confirmation** — When 80–95% of emission links have matching
   geometry, user must confirm. The unmatched links will be excluded from
   dispersion.

3. **Column name mismatch** — When join key column names differ between files
   and the mapping is ambiguous, user must specify the mapping.

4. **Geometry file with emission data** — When the geometry file also contains
   flow/speed columns, the resolver uses it only for geometry — emission data
   still flows from the emission file's macro result. User must confirm this
   behavior.

## 12. Non-Goals (Reiterated)

This design does NOT cover:
- External geometry lookup services (OSM, Baidu Maps, network matching APIs)
- LLM-based geometry inference or generation
- Spatial join (matching by proximity rather than link_id)
- Point-source dispersion mode (point geometry → point dispersion)
- Join-key resolution for micro_emission (currently macro only)
- Automatic geometry file discovery outside the current session
- Geometry file format conversion (SHP→WKT, GeoJSON→WKT) — user must provide
  a compatible format
- 180-task full benchmark
```

## 13. Appendix: Inventory Data

Complete inventory written to `/tmp/phase7_6a_join_key_geometry_inventory.json`.

### 13.1 C-Class Files Summary

| # | File | Rows | Join Key Col | Key Type | Key Pattern |
|---|------|------|-------------|----------|-------------|
| 1 | `test_no_geometry.xlsx` | 5 | `link_id` | string | `L0001`–`L0005` |
| 2 | `macro_01_standard_en.csv` | 20 | `link_id` | string | `Link_001`–`Link_020` |
| 3 | `macro_02_chinese_columns.xlsx` | 15 | `路段ID` | string | `路段_A1`–`路段_E5` |
| 4 | `macro_03_full_moves_types.csv` | 25 | `link_id` | string | `Segment_01`–`Segment_25` |
| 5 | `macro_04_urban_network.xlsx` | 20 | `LinkName` | string | `快速路_R01`–`支路_R05` |
| 6 | `macro_05_highway_network1.csv` | 35 | `segment_id` | string | `G1-K010`–`G5-K070` |
| 7 | `macro_05_highway_network - 副本.csv` | 35 | `segment_id` | string | `G1-K010`–`G5-K070` |

### 13.2 Geometry Candidates Summary

| # | File | Rows | Geometry | Key Col | Key Type |
|---|------|------|----------|---------|----------|
| 1 | `test_6links.xlsx` | 6 | WKT | `link_id` | numeric |
| 2 | `test_20links.xlsx` | 20 | WKT | `link_id` | numeric |
| 3 | `test_shanghai_full.xlsx` | 150 | WKT | `link_id` | numeric |
| 4 | `test_shanghai_allroads.xlsx` | 25,370 | WKT | `link_id` | numeric |
| 5 | `test_20links/test_20links.shp` | 20 | LineString | `link_id` | numeric |
| 6 | `test_shanghai_allroads/.../test_shanghai_allroads.shp` | 25,370 | LineString | `link_id` | numeric |
| 7–18 | 12 subnet `links.shp` files | 10–246 | LineString | `link_id` | numeric |

### 13.3 Key Finding

**Zero overlap** between all C-class keys (synthetic strings: `Link_001`,
`路段_A1`, `Segment_01`, `G1-K010`, `快速路_R01`, `L0001`) and all geometry
keys (real numeric Shanghai OSM link_ids: `2`–`163012`).

This is an artifact of synthetic test data construction, not a failure of the
join-key approach. In real usage, emission files and geometry files from the
same network will share the same key space. Phase 7.6C will create synthetic
test data with matching keys to validate the resolver.
