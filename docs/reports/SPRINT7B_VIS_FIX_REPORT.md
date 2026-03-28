# Sprint 7B: Activate render_spatial_map + Map Visual Quality

## 1. Files Modified and Why

| File | Change | Why |
|------|--------|-----|
| `config.py` | Added `enable_builtin_map_data` flag (default: `False`) | Controls whether macro_emission generates its own map_data or defers to render_spatial_map |
| `tools/macro_emission.py` | Guarded `_build_map_data()` call with config flag; added geometry merge-back | When flag is off, map_data=None, allowing auto-trigger. Geometry must be in results for render_spatial_map. |
| `web/app.js` | Basemap: `light_nolabels`; new color ramp; adaptive line weight/opacity; labels overlay | Clean academic map: no label clutter, vibrant 5-stop color gradient, thicker emission lines |
| `web/index.html` | Cache version v=25 → v=26 | Force browser cache refresh |

## 2. How Geometry Is Preserved in Emission Results

The calculator (`calculators/macro_emission.py`) does NOT include geometry in its output — it only computes emissions. The original input links DO have geometry (preserved by `_fix_common_errors` which copies geometry fields).

**New code in `tools/macro_emission.py`** (after calculator returns, before ToolResult):

```python
# Merge geometry from original input into calculator results
if links_results and links_data:
    original_geom_map = {}
    for link in links_data:
        lid = str(link.get("link_id", ""))
        geom = link.get("geometry") or link.get("geom") or link.get("wkt") or link.get("shape")
        if lid and geom:
            original_geom_map[lid] = geom
    for res_link in links_results:
        lid = str(res_link.get("link_id", ""))
        if lid in original_geom_map and "geometry" not in res_link:
            res_link["geometry"] = original_geom_map[lid]
```

This ensures `result["data"]["results"]` contains geometry for each link, so when render_spatial_map reads `_last_result["data"]["results"]`, it can build the map.

## 3. The Config Flag

In `config.py`:
```python
self.enable_builtin_map_data = os.getenv("ENABLE_BUILTIN_MAP_DATA", "false").lower() == "true"
```

Default: **False** (render_spatial_map handles visualization).
Set `ENABLE_BUILTIN_MAP_DATA=true` in `.env` to restore the old behavior as a fallback.

In `tools/macro_emission.py`:
```python
from config import get_config
config = get_config()
if config.enable_builtin_map_data:
    # ... existing _build_map_data() code ...
else:
    map_data = None  # Let render_spatial_map handle visualization
```

`_build_map_data()` method is NOT deleted — it remains as a safety net.

## 4. The Auto-Trigger Flow

With `enable_builtin_map_data=False`, the execution path is:

1. User uploads file + "计算排放"
2. LLM calls `calculate_macro_emission`
3. macro_emission returns `ToolResult(map_data=None)` — geometry is in `data.results[*].geometry`
4. Router's `_state_handle_executing` reaches the auto-trigger check:
   - `has_spatial_data` = True (results have geometry)
   - `already_visualized` = False (render_spatial_map not in completed_tools)
   - `has_map_data_from_tool` = False (no tool returned map_data)
5. Auto-calls `render_spatial_map` with `_last_result` = the macro_emission result
6. render_spatial_map builds map_data in legacy format `{type, center, zoom, links, color_scale, ...}`
7. Frontend renders the map identically to before

Expected server logs:
```
Executing tool: calculate_macro_emission
Spatial data detected, auto-triggering render_spatial_map
```

## 5. Frontend Changes

### Basemap: No Labels
**Before:** `light_all` (streets, shop names, transit stations all visible)
**After:** `light_nolabels` (clean gray/white geography only)

A separate `light_only_labels` layer is available as a toggleable overlay ("地名标注 / Labels") in the layer control.

### Line Weight (adaptive)
**Before:** 1–5 range, minimum 1 for >10k links
**After:** 2–4 range, minimum 2 for >10k links — always visible on screen

### Opacity (adaptive)
**Before:** Fixed 0.9
**After:** 0.6 for >5k links, 0.7 for >1k, 0.85 for fewer — reduces overlap clutter at scale

### Color Function
**Before:** 2-stop green→yellow→red, desaturated on light backgrounds
**After:** 5-stop blue→emerald→yellow→orange→red with logarithmic normalization:

| Ratio | Color | Hex |
|-------|-------|-----|
| 0.0 | Blue (low) | #3B82F6 |
| 0.25 | Emerald | #10B981 |
| 0.5 | Yellow | #F5D046 |
| 0.75 | Orange | #F97316 |
| 1.0 | Red (high) | #DC2626 |

### Legend
**Before:** Used `mapData.color_scale.colors` array (5 pinkish-red stops from macro_emission)
**After:** Hardcoded gradient matching `getEmissionColor()`: `linear-gradient(to right, #3B82F6, #10B981, #F5D046, #F97316, #DC2626)`

## 6. Test Results

### pytest (full suite)
```
181 passed in 6.47s
```

### python main.py health
```
OK query_emission_factors
OK calculate_micro_emission
OK calculate_macro_emission
OK analyze_file
OK query_knowledge
OK render_spatial_map

Total tools: 6
```

### node --check web/app.js
```
(no output — syntax valid)
```

## 7. Issues and Resolutions

1. **Geometry not in calculator output**: The `calculators/macro_emission.py` only computes emissions — it doesn't pass through geometry. Solved by adding a geometry merge-back step in `tools/macro_emission.py` that maps `link_id` → `geometry` from the original input and patches each result link.

2. **Config import placement**: The `from config import get_config` was already imported elsewhere in the file (line 680 for outputs_dir), so no circular import risk. Placed the new import next to the usage site for clarity.

3. **Legend gradient mismatch**: The old legend used `mapData.color_scale.colors` which came from macro_emission's `_build_map_data`. Since that method may no longer be called, the legend now uses a hardcoded gradient matching `getEmissionColor()` directly — they're always in sync regardless of which tool produces the map_data.
