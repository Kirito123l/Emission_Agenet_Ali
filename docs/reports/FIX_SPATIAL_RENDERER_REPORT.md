# Fix: Spatial Renderer WKT Geometry + Post-Calculation Visualization Prompt

## 1. Root Cause Analysis (WKT vs JSON)

### The Problem
`render_spatial_map`'s `_build_emission_map()` had a single geometry parsing path: `json.loads()`. When geometry was stored as a WKT string like `'LINESTRING (121.486 31.236, 121.487 31.235, ...)'`, `json.loads()` raised `JSONDecodeError`, the `except` block executed `continue`, the link was skipped, ALL links were skipped, `map_links` was empty, and the method returned `None`.

This manifested as the error: **"Could not build map from provided data"**.

### Why WKT Appears
Shapefile-based inputs go through `geopandas` → `_read_shapefile_from_zip()` which converts geometry to `[[lon, lat], ...]` lists. But Excel-based inputs may preserve the original WKT format from the data source (e.g., a column named "geometry" containing `LINESTRING(...)` strings). After Sprint 7B's geometry merge-back from original input to calculator results, these WKT strings flow through to `render_spatial_map`.

### The Fix
Added a WKT fallback parser. The geometry parsing now follows this cascade:
1. If geometry is already a list → use as-is (existing behavior)
2. If geometry is a string → try `json.loads()` first
3. If JSON fails → try `_parse_wkt_linestring()` (new)
4. If both fail → skip the link

## 2. The `_parse_wkt_linestring` Function

Added at module level in `tools/spatial_renderer.py`:

```python
def _parse_wkt_linestring(wkt_str: str) -> Optional[List[List[float]]]:
    """Parse WKT LINESTRING/MULTILINESTRING into [[lon, lat], ...] coordinates."""
    if not isinstance(wkt_str, str):
        return None

    s = wkt_str.strip()
    coords = []

    try:
        upper = s.upper()
        if upper.startswith("LINESTRING"):
            paren_start = s.index("(")
            paren_end = s.rindex(")")
            inner = s[paren_start + 1 : paren_end].strip()
            for pair in inner.split(","):
                parts = pair.strip().split()
                if len(parts) >= 2:
                    coords.append([float(parts[0]), float(parts[1])])

        elif upper.startswith("MULTILINESTRING"):
            groups = re.findall(r"\(([^()]+)\)", s)
            for group in groups:
                for pair in group.split(","):
                    parts = pair.strip().split()
                    if len(parts) >= 2:
                        coords.append([float(parts[0]), float(parts[1])])
    except (ValueError, IndexError):
        return None

    return coords if len(coords) >= 2 else None
```

Handles: `LINESTRING (...)`, `LINESTRING(...)` (no space), `MULTILINESTRING ((...), (...))`.
Returns `None` for single-point geometries, non-WKT strings, non-strings.

## 3. Where in `_build_emission_map` the Fix Was Applied

In `tools/spatial_renderer.py`, lines ~158-175 (the geometry parsing block inside the `for link in results:` loop).

**Before:**
```python
if isinstance(geometry, str):
    try:
        geom_parsed = json.loads(geometry)
        ...
    except (json.JSONDecodeError, TypeError):
        continue  # ← ALL WKT links silently skipped here
```

**After:**
```python
if isinstance(geometry, str):
    geom_str = geometry
    geometry = None

    # Try JSON first
    try:
        geom_parsed = json.loads(geom_str)
        if isinstance(geom_parsed, dict) and "coordinates" in geom_parsed:
            geometry = geom_parsed["coordinates"]
        elif isinstance(geom_parsed, list):
            geometry = geom_parsed
    except (json.JSONDecodeError, TypeError):
        pass

    # If JSON failed, try WKT
    if geometry is None:
        wkt_coords = _parse_wkt_linestring(geom_str)
        if wkt_coords:
            geometry = wkt_coords

    if geometry is None:
        continue
```

## 4. The Visualization Suggestion Code

### In `_state_handle_executing` (router.py)

Replaced the silent auto-trigger with a detection-only block:

```python
if has_spatial_data and not already_visualized and not has_map_data_from_tool:
    logger.info("Spatial data detected, will suggest visualization to user")
    state.execution._visualization_available = True

    available_pollutants = set()
    for r in state.execution.tool_results:
        res = r.get("result", {})
        data = res.get("data", {})
        for res_link in data.get("results", [])[:5]:
            if isinstance(res_link, dict):
                available_pollutants.update(
                    res_link.get("total_emissions_kg_per_hr", {}).keys()
                )
    state.execution._available_pollutants = sorted(available_pollutants)
```

### In `_state_build_response` (router.py)

After building the main response, appends a visualization prompt:

```python
if getattr(state.execution, '_visualization_available', False) and not map_data:
    pollutants = getattr(state.execution, '_available_pollutants', [])
    pollutant_options = "、".join(pollutants) if pollutants else "CO2, NOx"
    first_pol = pollutants[0] if pollutants else "CO2"
    viz_suggestion = (
        "\n\n---\n"
        "📍 **检测到空间数据，可以进行地图可视化**\n\n"
        f"可用污染物：{pollutant_options}\n\n"
        "您可以说：\n"
        f'- "帮我可视化 {first_pol} 的排放分布"\n'
        '- "在地图上展示所有污染物"\n'
        '- "不需要可视化"'
    )
    response.text += viz_suggestion
```

The `and not map_data` guard ensures the suggestion only appears when no map was already rendered (e.g., if the LLM already called render_spatial_map, or if `enable_builtin_map_data=true`).

### User Flow

1. User: "计算CO2和NOx排放" → LLM calls calculate_macro_emission
2. Response: calculation results + "📍 检测到空间数据，可以进行地图可视化..."
3. User: "帮我可视化CO2排放" → LLM calls render_spatial_map(pollutant="CO2")
4. Response: map renders in frontend

## 5. Test Results

### New WKT tests added to `tests/test_spatial_renderer.py` (9 tests)

```
test_parse_wkt_linestring_basic              PASSED
test_parse_wkt_linestring_no_space           PASSED
test_parse_wkt_linestring_many_points        PASSED
test_parse_wkt_multilinestring               PASSED
test_parse_wkt_returns_none_for_single_point PASSED
test_parse_wkt_returns_none_for_non_wkt      PASSED
test_parse_wkt_returns_none_for_non_string   PASSED
test_build_emission_map_wkt_geometry         PASSED
test_build_emission_map_wkt_no_space         PASSED
```

### Full test suite
```
190 passed in 5.09s
```

All 181 existing tests continue to pass. 9 new WKT tests added.

### Health check
```
OK query_emission_factors
OK calculate_micro_emission
OK calculate_macro_emission
OK analyze_file
OK query_knowledge
OK render_spatial_map

Total tools: 6
```

## 6. Expected Server Log for render_spatial_map Success

After fix, when user says "帮我可视化CO2排放":

```
INFO  Executing tool: render_spatial_map
DEBUG Tool arguments: {'pollutant': 'CO2', 'data_source': 'last_result'}
INFO  Tool render_spatial_map completed. Success: True, Error: None
```

For the preceding calculation step:
```
INFO  Executing tool: calculate_macro_emission
INFO  Spatial data detected, will suggest visualization to user
```

## Files Modified

| File | Change |
|------|--------|
| `tools/spatial_renderer.py` | Added `_parse_wkt_linestring()` helper; updated `_build_emission_map()` geometry parsing to cascade JSON → WKT |
| `core/router.py` | Replaced silent auto-trigger with `_visualization_available` flag + suggestion text in `_state_build_response` |
| `tests/test_spatial_renderer.py` | Added 9 WKT parsing and integration tests |
