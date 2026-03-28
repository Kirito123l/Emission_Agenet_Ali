# Phase 2 Codebase Exploration Report

## 1. GIS/Visualization Architecture
### 1.1 How map_data flows through the system
Current `map_data` flow is:

1. `calculators/macro_emission.py:86-122`
   `MacroEmissionCalculator.calculate()` returns only calculator data:
   ```python
   {
     "status": "success",
     "data": {
       "query_info": {...},
       "results": [...],
       "summary": {...}
     }
   }
   ```
   It does not create `map_data`, does not keep geometry, and does not emit GeoJSON.

2. `tools/macro_emission.py:551-780`
   `MacroEmissionTool.execute()`:
   - normalizes input params
   - reads tabular / ZIP / shapefile inputs
   - preserves geometry from the input layer
   - calls the calculator
   - mutates `result["data"]`
   - calls `_build_map_data(...)` at `tools/macro_emission.py:761-768`
   - returns:
   ```python
   ToolResult(
       success=True,
       error=None,
       data=result["data"],
       summary=summary,
       map_data=map_data
   )
   ```

3. `core/executor.py:111-137`
   `ToolExecutor.execute()` converts `ToolResult` into a plain dict and exposes top-level `map_data`:
   ```python
   {
     "success": result.success,
     "data": result.data,
     "error": result.error,
     "summary": result.summary,
     "chart_data": result.chart_data,
     "table_data": result.table_data,
     "map_data": result.map_data,
     "download_file": result.download_file,
     "message": ...,
   }
   ```

4. `core/router_payload_utils.py:274-294`
   `extract_map_data(tool_results)` returns the first match in this order:
   - `item["result"]["map_data"]`
   - `item["result"]["data"]["map_data"]`
   - otherwise `None`

5. `core/router.py:816-828` and `core/router.py:957-977`
   Both the state-orchestration path and legacy path call `_extract_map_data(...)` and set `RouterResponse.map_data`.

6. `api/session.py:43-61`
   `Session.chat()` converts `RouterResponse` to a dict with keys:
   `text`, `chart_data`, `table_data`, `map_data`, `download_file`, `trace`, `trace_friendly`.

7. `api/routes.py:136-199`
   `/api/chat` reads `result.get("map_data")`, sets `data_type` to `"map"` or `"table_and_map"`, returns it in `ChatResponse.map_data`, and persists it via `session.save_turn(..., map_data=map_data, ...)`.

8. `api/routes.py:304-347`
   `/api/chat/stream` emits map payloads as:
   ```json
   {"type": "map", "content": map_data}
   ```
   It also includes `map_data` again in the final `"done"` event at `api/routes.py:373-382`.

9. `web/app.js:356-362`
   Streamed maps are rendered by `renderEmissionMap(data.content, container)`.

10. `web/app.js:1117-1187`
    Non-stream / history render path checks:
    ```js
    const hasValidMapData = data.map_data &&
                            data.map_data.links &&
                            data.map_data.links.length > 0;
    ```
    and then calls `renderEmissionMap(data.map_data, msgContainer)`.

Only one current producer creates `map_data`: `tools/macro_emission.py:761-779`.

Other GIS/map-adjacent routes:
- `api/routes.py:401-464` `/api/file/preview` treats `.zip` uploads as shapefiles and returns `detected_type="shapefile"` with a geometry warning, but it does not return `map_data`.
- `api/routes.py:471-562` `/api/gis/basemap` and `/api/gis/roadnetwork` serve the static GIS background layers.

### 1.2 GeoJSON Construction in macro_emission.py
`tools/macro_emission.py` does not construct a GeoJSON `FeatureCollection` or GeoJSON `Feature` objects anywhere.

All GeoJSON-related code in `tools/macro_emission.py` is:

1. Input geometry preservation:
   - `tools/macro_emission.py:130-135`
   - `_fix_common_errors()` copies the first geometry-like field whose lowercase name is one of:
     `geometry`, `geom`, `wkt`, `shape`, `几何`, `路段几何`, `坐标`

2. Input GeoJSON parsing:
   - `tools/macro_emission.py:309-317`
   - `_build_map_data()` handles `geom_str.startswith("{")` as GeoJSON text:
     - if `geojson["type"] == "LineString"`: use `geojson["coordinates"]`
     - else, if Shapely is available, `shape(geojson)` and read `.coords`

3. Shapefile-to-coordinate-list conversion:
   - `tools/macro_emission.py:467-534`
   - `_read_shapefile_from_zip()` reads a shapefile with GeoPandas and converts geometry to plain coordinate arrays:
     - `LineString` -> `[[x, y], ...]`
     - `MultiLineString` -> concatenated `[[x, y], ...]`
     - `Polygon` -> exterior ring `[[x, y], ...]`

4. Returned structure:
   - `_build_map_data()` at `tools/macro_emission.py:237-431` creates a custom payload:
   ```python
   {
     "type": "macro_emission_map",
     "center": [...],
     "zoom": 12,
     "pollutant": ...,
     "unit": "kg/(h·km)",
     "color_scale": {...},
     "links": [...],
     "summary": {...}
   }
   ```
   This is not GeoJSON.

Result: in the current macro-emission path, GeoJSON is accepted as one possible input geometry encoding, but the output sent to router/API/frontend is a custom line-map schema, not GeoJSON.

### 1.3 map_data Structure
`core/router.py:1104-1106` is only a wrapper around `core/router_payload_utils.py:274-294`.

`_extract_map_data()` does not reshape anything. It returns the first available `map_data` object as-is.

Current concrete `map_data` shape, produced by `tools/macro_emission.py:410-429`, is:

```python
{
  "type": "macro_emission_map",
  "center": [center_lon, center_lat],
  "zoom": 12,
  "pollutant": main_pollutant,
  "unit": "kg/(h·km)",
  "color_scale": {
    "min": float(min_emission),
    "max": float(max_emission),
    "colors": ["#fee5d9", "#fcae91", "#fb6a4a", "#de2d26", "#a50f15"]
  },
  "links": [
    {
      "link_id": str,
      "geometry": [[lon_or_x, lat_or_y], ...],
      "emissions": {
        pollutant_name: emission_intensity_kg_per_h_km,
        ...
      },
      "emission_rate": {
        pollutant_name: g_per_veh_km,
        ...
      },
      "link_length_km": float,
      "avg_speed_kph": float,
      "traffic_flow_vph": float
    },
    ...
  ],
  "summary": {
    "total_links": int,
    "total_emissions_kg_per_hr": {
      pollutant_name: summed_value,
      ...
    }
  }
}
```

Important code-level observations:
- `tools/macro_emission.py:387-395` computes `color_scale.min/max` from `pollutants[0]` only.
- `tools/macro_emission.py:423-427` labels `summary["total_emissions_kg_per_hr"]`, but the values are actually the sum of `link["emissions"]`, and `link["emissions"]` are intensities in `kg/(h·km)`, not total `kg/h`.
- `tools/macro_emission.py:397-408` computes `center`, but the frontend does not use it.
- `tools/macro_emission.py:413` fixes `zoom=12`, but the frontend does not use it.

Conditions for `map_data` to be populated vs `None`:
- `tools/macro_emission.py:383-384`: `_build_map_data()` returns `None` if no geometry was found or no usable `map_links` were built.
- `tools/macro_emission.py:763-772`: `execute()` catches map-building exceptions and forces `map_data = None`.
- `core/router_payload_utils.py:293-294`: router returns `None` if no tool result contains map data.
- `core/router.py:508`, `core/router.py:555`, `core/router.py:775-780`: direct LLM text responses never produce `map_data`.

### 1.4 Frontend Map Rendering
Search results in `web/app.js`:
- `renderEmissionMap` exists at `web/app.js:1669-1754`
- `initLeafletMap` exists at `web/app.js:1831-2014`
- `updateMapPollutant` exists at `web/app.js:1792-1829`
- `getEmissionColor` exists at `web/app.js:2016-2053`
- There is no generic `renderMap` function in `web/app.js`

Expected map data format:
- `web/app.js:1670-1679`
- renderer expects:
  - `mapData.links` array
  - `mapData.links[0].emissions` object for pollutant names
  - `mapData.pollutant` optional default pollutant
  - `mapData.color_scale.min`, `max`, `colors`
  - each link to have `geometry` or `coordinates` as `[[lon, lat], ...]`

Complete render flow:

1. `web/app.js:1669-1754` `renderEmissionMap(mapData, msgContainer)`
   - validates `mapData.links.length > 0`
   - generates a unique `mapId`
   - gets pollutant names from `Object.keys(mapData.links[0].emissions || {})`
   - uses `mapData.pollutant` or the first pollutant as default
   - builds a `<select>` pollutant switcher
   - builds a legend row from `mapData.color_scale`
   - inserts map HTML into `.message-content`
   - after `setTimeout(..., 150)`, calls `initLeafletMap(mapData, mapId, defaultPollutant)`
   - attaches a `change` listener that re-calls `initLeafletMap(...)`

2. `web/app.js:1831-2014` `initLeafletMap(mapData, mapId, pollutant)`
   - guards on global `L`
   - if the container already has `_leaflet_map` and `_emission_layer`, it does not rebuild the map; it only calls `updateMapPollutant(...)`
   - otherwise it creates `L.map(...)` with `preferCanvas: true` and `L.canvas(...)`
   - loads GIS basemap and road overlay
   - creates `L.polyline(...)` for each link
   - binds `bindPopup(...)`
   - stores references on the DOM node:
     - `_leaflet_map`
     - `_emission_layer`
     - `_map_data`
     - `_line_weight`
   - calls `fitBounds(...)` from emission-link bounds only
   - falls back to Shanghai `[31.2304, 121.4737], 12` if no emission bounds exist

3. `web/app.js:1792-1829` `updateMapPollutant(map, emissionLayer, mapData, pollutant)`
   - iterates each polyline
   - reads `polyline._linkData`
   - recalculates the color with `getEmissionColor(...)`
   - updates popup HTML with new pollutant values
   - does not rebuild legend or recompute min/max

Color scale computation:
- Backend:
  - `tools/macro_emission.py:389-395`
  - min/max are computed from `map_links[*]["emissions"][main_pollutant]`
  - `main_pollutant = pollutants[0]`
- Frontend:
  - `web/app.js:1687-1691`, `1796-1799`, `1917-1920`
  - frontend only reads `mapData.color_scale.min/max`
  - it does not compute new min/max itself
  - it uses those same min/max for all pollutant switches
- Actual line color function:
  - `web/app.js:2016-2053`
  - uses logarithmic scaling:
    - `safeMin = max(minVal, 0.001)`
    - `safeVal = max(value, 0.001)`
    - `safeMax = max(maxVal, 0.002)`
  - then maps to a hardcoded green -> yellow -> red gradient

Legend rendering:
- `web/app.js:1686-1716`
- legend uses `mapData.color_scale.colors` only for the gradient bar
- legend labels use `mapData.color_scale.min/max`
- the legend is static after first render
- pollutant switching does not update legend range or gradient

Important mismatch:
- backend legend colors are `["#fee5d9", "#fcae91", "#fb6a4a", "#de2d26", "#a50f15"]` (red palette)
- actual line colors come from `getEmissionColor(...)` (green/yellow/red)
- so the legend gradient does not match the rendered polyline colors

Pollutant switcher behavior:
- `web/app.js:1741-1748`
- changing the `<select>` triggers `initLeafletMap(mapData, mapId, newPollutant)`
- because the map already exists, the code path becomes `updateMapPollutant(...)`
- this updates polyline styles and popup text only
- it does not:
  - recompute pollutant-specific min/max
  - update the legend text
  - update the map subtitle

Basemap / roadnetwork loading:
- `web/app.js:1761-1774` `loadGISBasemap()`
- `web/app.js:1776-1789` `loadGISRoadNetwork()`
- both use process-global JS caches:
  - `GIS_BASEMAP_DATA`
  - `GIS_ROADNETWORK_DATA`
- `web/app.js:1869-1889`
  - GIS basemap is the primary background layer
  - CartoDB Positron is fallback only when GIS basemap is missing/error
- `web/app.js:1892-1912`
  - road network is loaded as an overlay and shown by default via `L.layerGroup().addTo(map)`
  - a Leaflet layer control exposes `"路网"`

Popups / tooltips:
- map features use popups only:
  - `web/app.js:1964-1979` initial `bindPopup(...)`
  - `web/app.js:1812-1825` popup HTML replacement on pollutant switch
- popup fields are:
  - `link.link_id`
  - active pollutant value in `kg/(h·km)`
  - `link.emission_rate[pollutant]` in `g/(veh·km)`
  - `link.avg_speed_kph`
  - `link.traffic_flow_vph`
  - `link.link_length_km`
- there is no Leaflet tooltip usage for map features

Unused current payload fields:
- `mapData.center` not used
- `mapData.zoom` not used
- `mapData.unit` not used
- `mapData.summary` not used

### 1.5 Static GIS Files
Contents of `static_gis/`:
- `static_gis/README.md`
- `static_gis/basemap.geojson`
- `static_gis/roadnetwork.geojson`

GeoJSON file inventory:

| File | Size | Feature count | Geometry types | Property keys |
|------|------|---------------|----------------|---------------|
| `static_gis/basemap.geojson` | 69,199 bytes | 16 | `Polygon`, `MultiPolygon` | `name` |
| `static_gis/roadnetwork.geojson` | 6,148,993 bytes | 25,370 | `LineString` | `highway`, `name` |

First-feature examples from the actual files:
- `static_gis/basemap.geojson`: `{"name": "黄浦区"}`
- `static_gis/roadnetwork.geojson`: `{"highway": "primary_link", "name": null}`

Where they are referenced:
- Runtime reader:
  - `api/routes.py:489`
  - `api/routes.py:536`
- Offline generator:
  - `preprocess_gis.py:15`
  - `preprocess_gis.py:32`
- Frontend does not reference file paths directly; it only calls `/api/gis/basemap` and `/api/gis/roadnetwork`.

Are these files referenced anywhere besides `api/routes.py`?
- In runtime code, only indirectly via the API endpoints.
- In repository code, `preprocess_gis.py` generates them.
- Docs/logs mention them, but no other runtime module reads them directly.

Can they be removed safely?
- `basemap.geojson`: not fully safe if Shanghai-specific administrative basemap is desired. If removed, `/api/gis/basemap` returns:
  ```json
  {"error": "GIS底图文件不存在", "available": false}
  ```
  and frontend falls back to CartoDB Positron.
- `roadnetwork.geojson`: not fully safe if the Shanghai road overlay is desired. If removed, frontend still renders the emission layer; it just loses the optional road overlay.
- Conclusion: they are optional for basic map rendering, but not removable if the current Shanghai-specific GIS context must be preserved.

## 2. Macro Emission Output Format
### 2.1 Calculator Output
`calculators/macro_emission.py:86-122` returns either:

Success:
```python
{
  "status": "success",
  "data": {
    "query_info": {
      "model_year": int,
      "pollutants": list[str],
      "season": str,
      "links_count": int
    },
    "results": [
      {
        "link_id": str,
        "link_length_km": float,
        "traffic_flow_vph": float,
        "avg_speed_kph": float,
        "fleet_composition": {
          vehicle_name: {
            "source_type_id": int,
            "percentage": float,
            "vehicles_per_hour": float
          }
        },
        "emissions_by_vehicle": {
          vehicle_name: {
            pollutant_name: float  # rounded kg/h contribution for this vehicle class
          }
        },
        "total_emissions_kg_per_hr": {
          pollutant_name: float
        },
        "emission_rates_g_per_veh_km": {
          pollutant_name: float
        }
      },
      ...
    ],
    "summary": {
      "total_links": int,
      "total_emissions_kg_per_hr": {
        pollutant_name: float,
        ...
      }
    }
  }
}
```

Error:
```python
{
  "status": "error",
  "error_code": "CALCULATION_ERROR",
  "message": str
}
```

There is no `link_results` key. The link-level array key is `results`.

There is no `total_emissions` top-level summary key. The summary key is `summary["total_emissions_kg_per_hr"]`.

Coordinates / geometry are not included anywhere in calculator output. Geometry exists only in the tool/file-input layer.

### 2.2 Tool Output
Exact `MacroEmissionTool.execute()` flow (`tools/macro_emission.py:551-780`):

1. `tools/macro_emission.py:565-568`
   Map `file_path -> input_file` if needed.

2. `tools/macro_emission.py:570-578`
   Extract:
   - `links_data`
   - `pollutants`
   - `model_year`
   - `season`
   - `default_fleet_mix`
   - `global_fleet_mix = kwargs.get("fleet_mix")`
   - `input_file`
   - `output_file`

3. `tools/macro_emission.py:580-602`
   Load links:
   - ZIP -> `_read_from_zip()`
   - non-ZIP file -> `ExcelHandler.read_links_from_excel()`
   - or use provided `links_data`
   - if missing both, return failure

4. `tools/macro_emission.py:604-610`
   Validate `links_data` is a non-empty list.

5. `tools/macro_emission.py:612-625`
   Preprocess links:
   - `_fix_common_errors(...)`
   - `_apply_global_fleet_mix(...)`
   - standardize `default_fleet_mix`
   - `_fill_missing_link_fleet_mix(...)`

6. `tools/macro_emission.py:627-634`
   Call calculator.

7. `tools/macro_emission.py:636-651`
   If calculator returns `"status" == "error"`, return failure `ToolResult`.

8. `tools/macro_emission.py:653-660`
   Add `fleet_mix_fill` metadata into `result["data"]`.

9. `tools/macro_emission.py:662-676`
   If `output_file` is requested, call `write_results_to_excel(...)`.
   Important actual behavior:
   - it uses `result["data"].get("links", [])`
   - calculator returns `results`, not `links`
   - so this code path currently passes an empty list unless some caller injected a `links` key

10. `tools/macro_emission.py:677-699`
    If `input_file` exists, generate a downloadable Excel file using:
    - `config.outputs_dir`
    - `ExcelHandler.generate_result_excel(...)`
    - this correctly uses `result["data"].get("results", [])`

11. `tools/macro_emission.py:702-759`
    Build human-readable summary text.

12. `tools/macro_emission.py:761-772`
    Build `map_data` from original input links plus calculator results.

13. `tools/macro_emission.py:774-780`
    Return `ToolResult`.

Exact success `ToolResult.data` structure:

Always present on success:
```python
{
  "query_info": {
    "model_year": int,
    "pollutants": list[str],
    "season": str,
    "links_count": int
  },
  "results": [link_result, ...],
  "summary": {
    "total_links": int,
    "total_emissions_kg_per_hr": {
      pollutant_name: float,
      ...
    }
  },
  "fleet_mix_fill": {
    "strategy": "default_fleet_mix",
    "filled_count": int,
    "filled_link_ids": list[str],
    "filled_row_indices": list[int],
    "default_fleet_mix_used": dict[str, float]
  }
}
```

Conditionally added keys on success:
```python
{
  "output_file_warning": str,   # if explicit output_file write failed
  "output_file": str,           # if explicit output_file write succeeded
  "download_file": {            # if input_file-based result Excel generation succeeded
    "path": str,
    "filename": str
  }
}
```

Important actual top-level `ToolResult` fields:
- `summary`: populated with the synthesized summary text
- `map_data`: populated from `_build_map_data(...)`
- `chart_data`: `None`
- `table_data`: `None`
- `download_file`: `None`

So download metadata for macro emission currently lives inside `ToolResult.data["download_file"]`, not in `ToolResult.download_file`.

How Excel download files are generated:
- `skills/macro_emission/excel_handler.py:176-223`
  - `write_results_to_excel(file_path, results, pollutants)` creates a new table with columns:
    - `link_id`
    - `link_length_km`
    - `traffic_flow_vph`
    - `avg_speed_kph`
    - one column per pollutant named `<pollutant>_kg_per_h`
  - it writes CSV or Excel based on output suffix
- `skills/macro_emission/excel_handler.py:565-704`
  - `generate_result_excel(original_file_path, emission_results, pollutants, output_dir, fleet_fill_info=...)`
  - reads the original uploaded input if it is:
    - `.csv`
    - `.xlsx`
    - `.xls`
    - `.zip`
  - for a ZIP containing a shapefile, it cannot reconstruct the original shapefile table, so it starts from `pd.DataFrame(emission_results)` instead (`excel_handler.py:603-608`)
  - appends one emission column per pollutant:
    - `<pollutant>_kg_h`
  - optionally backfills missing fleet-mix columns for rows whose fleet mix was filled by default logic (`excel_handler.py:644-694`)
  - writes:
    - filename pattern: `{original_name}_emission_results_{timestamp}.xlsx`
    - output path: `os.path.join(output_dir, output_filename)`
  - returns `(success, output_path, output_filename, error_message)`

Failure `ToolResult.data` variants:

1. Input read failure (`tools/macro_emission.py:591-596`)
```python
{"input_file": input_file}
```

2. Missing `links_data` and `input_file` (`tools/macro_emission.py:597-602`)
```python
None
```

3. Invalid `links_data` type/emptiness (`tools/macro_emission.py:604-610`)
```python
None
```

4. Calculator error (`tools/macro_emission.py:636-651`)
```python
{
  "error_code": result.get("error_code"),
  "query_params": {
    "pollutants": pollutants,
    "model_year": model_year,
    "season": season,
    "links_count": len(links_data),
    "filled_fleet_mix_links": fill_info["filled_count"]
  }
}
```

### 2.3 GeoJSON Feature Properties
Current macro-emission output does not contain GeoJSON `Feature` objects.

So the exact answer is:
- There are no emitted GeoJSON feature properties in `MacroEmissionTool` output today.
- The tool emits custom per-link map objects inside `map_data["links"]`.

The equivalent per-link properties in the current custom map payload are:
- `link_id`
- `emissions`
- `emission_rate`
- `link_length_km`
- `avg_speed_kph`
- `traffic_flow_vph`

If you convert current `map_data.links[*]` to GeoJSON later, those six keys are the direct candidate `feature.properties` values.

For actual GeoJSON already in the repo:
- `static_gis/basemap.geojson` feature properties: `name`
- `static_gis/roadnetwork.geojson` feature properties: `highway`, `name`

### 2.4 Coordinate System
Current macro-emission map rendering has no explicit CRS contract.

What the code actually does:
- `tools/macro_emission.py:349-355`
  `_build_map_data()` only checks whether the first coordinate is inside WGS-84-like numeric ranges (`abs(lon) <= 180`, `abs(lat) <= 90`).
- If coordinates are outside that range, it logs a warning and still keeps them.
- `tools/macro_emission.py:487-525`
  `_read_shapefile_from_zip()` reads shapefile geometry as-is and never reprojects.
- `skills/macro_emission/excel_handler.py:161-166`
  tabular geometry values are preserved as raw text and later parsed as-is.
- `web/app.js:1950-1951`
  frontend assumes every pair is `[lon, lat]` and flips it to Leaflet `[lat, lon]`.

Practical result:
- If input geometry is already WGS-84 lon/lat, the map can render correctly.
- If input geometry is projected (for example UTM / local meters), the map payload still passes through, and the frontend will misinterpret it as lon/lat.
- No CRS metadata is stored in:
  - `links_data`
  - calculator output
  - `map_data`

So the current rendering path is effectively "WGS-84 expected, but not enforced and not transformed."

## 3. Dispersion Model Analysis
### 3.1 mode_inference.py Flow
`ps-xgb-aermod-rline-surrogate/mode_inference.py` has no `main()` function and no `if __name__ == "__main__":` guard. The full pipeline executes at import time.

Imports and dependencies (`ps-xgb-aermod-rline-surrogate/mode_inference.py:31-48`):
- `numpy`
- `matplotlib.pyplot`
- `itertools.product`
- `pandas`
- `math`
- `geopandas`
- `os`
- `shutil`
- `scipy.interpolate.griddata`
- `pyproj.Proj`, `pyproj.transform`
- `shapely.geometry.Polygon`, `LineString`, `Point`
- `shapely.ops.unary_union`
- `shapely.validation.make_valid`
- `xgboost`
- `sklearn.model_selection.train_test_split`
- `sklearn.metrics.mean_squared_error`, `r2_score`, `mean_absolute_error`
- `sklearn.preprocessing.StandardScaler`

User Configuration block (`ps-xgb-aermod-rline-surrogate/mode_inference.py:24-29`):
```python
ROAD_SHP     = r"YOUR_PATH\roads.shp"
EMISSION_CSV = r"YOUR_PATH\hourly_emission.csv"
MET_SFC      = r"YOUR_PATH\met_file.SFC"
MODEL_DIR    = r"models"
```

Complete top-level flow:

1. `ps-xgb-aermod-rline-surrogate/mode_inference.py:53-61`
   Load road shapefile and emission CSV, rename emission `NAME -> NAME_1`, merge on `NAME_1`.

2. `ps-xgb-aermod-rline-surrogate/mode_inference.py:63-66`
   Print unmatched roads whose geometry was not found.

3. `ps-xgb-aermod-rline-surrogate/mode_inference.py:72-111`
   Deduplicate roads, convert geometry from WGS-84 to UTM Zone 51N, then shift the entire network to local coordinates with origin `(min_x, min_y) -> (0, 0)`.

4. `ps-xgb-aermod-rline-surrogate/mode_inference.py:113-122`
   Parse emission timestamps and derive:
   - `data_time`
   - `day`
   - `hour`
   - categorical `index`
   - `nox_g_m_s2 = nox / (length * 7 * 1000 * 3600)`

5. `ps-xgb-aermod-rline-surrogate/mode_inference.py:131-309`
   Build road buffers and generate receptor points with `generate_receptors_custom_offset(...)`.

6. `ps-xgb-aermod-rline-surrogate/mode_inference.py:312-323`
   Call receptor generation with:
   - `offset_rule={3.5: 40, 8.5: 40}`
   - `background_spacing=50`
   - `buffer_extra=3`
   Then deduplicate by `(x, y)`.

7. `ps-xgb-aermod-rline-surrogate/mode_inference.py:330-416`
   Split each polyline into 10 m segments, compute midpoint and road angle, tile those source segments across all time steps, and merge hourly emission strength onto each segment midpoint.

8. `ps-xgb-aermod-rline-surrogate/mode_inference.py:422-459`
   Load AERMOD `.SFC` meteorology, construct integer `Date`, classify stability classes from `L`, `WSPD`, and `MixHGT_C`.

9. `ps-xgb-aermod-rline-surrogate/mode_inference.py:465-483`
   Load 12 XGBoost surrogate models for the `M` roughness set only.

10. `ps-xgb-aermod-rline-surrogate/mode_inference.py:490-668`
    `predict_time_series_xgb(...)`:
    - rotates receptors and sources into wind-aligned coordinates
    - computes receptor-source relative positions
    - selects downwind and upwind masks
    - builds feature matrices
    - batch-predicts with the class-specific models
    - accumulates concentration contributions by receptor
    - returns a DataFrame with one row per receptor per time step

11. `ps-xgb-aermod-rline-surrogate/mode_inference.py:674-708`
    Build `sources_re`, build the `models` dict, run inference, assign the result to `time_series_conc`.

There is no final save-to-file step.

### 3.2 Input Requirements
Road shapefile requirements, from actual column access:
- Required:
  - `NAME_1` for the merge (`mode_inference.py:59-60`)
  - `geometry`
- Optional:
  - `width` for receptor offsets (`mode_inference.py:169`, `192-193`)
    - if missing, default width is `7.0`
- Geometry handled:
  - `LineString`
  - `MultiLineString`

Emission CSV requirements:
- Required columns:
  - `NAME` or already `NAME_1` (`mode_inference.py:56`)
  - `data_time` (`mode_inference.py:114`)
  - `nox` (`mode_inference.py:120`)
  - `length` (`mode_inference.py:120`)
- Expected shape:
  - one row per road per hour
- Actual join logic:
  - non-spatial left join on road name only

Meteorology `.SFC` requirements:
- Read with `read_sfc(path)` (`mode_inference.py:431-434`)
- One skipped header row
- Whitespace-delimited columns matching:
  - `Year`, `Month`, `Day`, `Hour`
  - `H`
  - `MixHGT_C`
  - `L`
  - `WSPD`
  - `WDIR`
  - plus the other AERMOD surface-file columns in `col_names`

Meteorological parameters actually used:
- Direct model features:
  - `H`
  - `MixHGT_C` for classes `N2`, `U`, `VU`
  - `L`
  - `WSPD`
- Used for geometry rotation / directional encoding:
  - `WDIR`
- Used for time index:
  - `Year`, `Month`, `Day`, `Hour`
- Parsed but unused in inference:
  - `USTAR`, `WSTAR`, `ThetaGrad`, `MixHGT_M`, `Z0`, `B0`, `Albedo`, `Temp`, `RH`, `Pressure`, `CloudCover`, etc.

### 3.3 Key Functions to Extract
Functions that are reusable with relatively small refactoring:
- `convert_to_utm(lon, lat)` at `mode_inference.py:79-82`
  - reusable only after making the CRS / zone configurable
- `make_rectangular_buffer(...)` at `mode_inference.py:131-161`
  - reusable as-is
- `generate_receptors_custom_offset(...)` at `mode_inference.py:164-309`
  - reusable after removing the built-in plotting side effects
- `split_polyline_by_interval_with_angle(...)` at `mode_inference.py:330-374`
  - reusable as-is
- `read_sfc(path)` at `mode_inference.py:431-434`
  - reusable as-is
- `load_model(path)` at `mode_inference.py:465-468`
  - reusable as-is
- `predict_time_series_xgb(...)` at `mode_inference.py:490-668`
  - reusable after isolating it from the current top-level assumptions

Code that should be refactored before integration:
- `mode_inference.py:53-122`
  - top-level I/O and merge logic should become functions
- `mode_inference.py:76-77`
  - UTM Zone 51N is hardcoded
- `mode_inference.py:312-318`
  - actual receptor-generation parameters are hardcoded at module level
- `mode_inference.py:378-416`
  - midpoint generation / emission tiling should become a function
- `mode_inference.py:470-483`
  - model loading is hardcoded to the `M` roughness files
- `mode_inference.py:682-684`
  - `sources.reshape(len(met), len(base_midpoints_df), 4)` is fragile and assumes exact time alignment

### 3.4 Hardcoded Dependencies
Paths/constants/assumptions currently baked into `mode_inference.py`:
- User-configured file paths:
  - `ROAD_SHP`
  - `EMISSION_CSV`
  - `MET_SFC`
  - `MODEL_DIR`
- Fixed coordinate system:
  - WGS-84 input -> UTM Zone 51N (`mode_inference.py:76-82`)
- Fixed local-origin shift:
  - subtract global `min_x`, `min_y` (`mode_inference.py:99-105`)
- Fixed road-width assumption in emission-area conversion:
  - `7` meters in `nox_g_m_s2 = nox / (length * 7 * 1000 * 3600)` (`mode_inference.py:120`)
- Hardcoded pollutant:
  - NOx only
- Hardcoded actual receptor-generation call:
  - `offset_rule={3.5: 40, 8.5: 40}`
  - `background_spacing=50`
  - `buffer_extra=3`
- Hardcoded road segmentation:
  - `interval = 10` meters (`mode_inference.py:378`)
- Hardcoded plotting:
  - `plt.show()` (`mode_inference.py:307`)
  - `plt.xlim(1000, 1400)` / `plt.ylim(600, 900)` (`mode_inference.py:304-305`)
- Hardcoded model selection:
  - only `_M` models are loaded (`mode_inference.py:471-482`)
- Hardcoded model naming/path expectation:
  - `MODEL_DIR = "models"` expects files directly under `models/`
  - but this repo actually stores them under `models/model_z=0.05`, `models/model_z=0.5`, `models/model_z=1`
- Hardcoded shape assumption:
  - number of meteorology rows must match the number of tiled source time steps for `reshape(...)` to work

### 3.5 Output Format
Output of `predict_time_series_xgb(...)` (`mode_inference.py:660-668`):

```python
pd.DataFrame({
  "Date": date,
  "Receptor_ID": indices,
  "Receptor_X": np.round(rx, 1),
  "Receptor_Y": np.round(ry, 1),
  "Conc": total_conc
})
```

Returned columns are exactly:
- `Date`
- `Receptor_ID`
- `Receptor_X`
- `Receptor_Y`
- `Conc`

Important output facts:
- `Receptor_X` / `Receptor_Y` are local shifted UTM-like coordinates in meters, not WGS-84
- the script keeps the final result only in the Python variable `time_series_conc`
- there is no `to_csv`, `to_file`, or GeoJSON export in the file

How to convert to GeoJSON for the current project:

1. Join `time_series_conc` back to `receptors_unique`:
   - `Receptor_ID` is generated from `np.arange(n_receptors)` in `mode_inference.py:535-536`
   - it corresponds to the ordering of `x_rp = receptors_unique["x"]` and `y_rp = receptors_unique["y"]` at `mode_inference.py:686-687`

2. Restore absolute UTM coordinates:
   - current receptor coordinates are local coordinates
   - reverse with:
     - `utm_x = Receptor_X + min_x`
     - `utm_y = Receptor_Y + min_y`

3. Convert UTM back to WGS-84:
   - inverse-transform from `utm51n -> wgs84`

4. Build GeoJSON `Point` features with properties such as:
   - `Date`
   - `Receptor_ID`
   - `Conc`
   - receptor `type` / `side` / `offset_from_buffer` if joined from `receptors_unique`

### 3.6 Model Files
Current directory contents:
- `ps-xgb-aermod-rline-surrogate/models/README_models.md` (2,480 bytes)
- 36 `.json` model files across 3 subdirectories

Directory totals:
- `model_z=0.05`: 12 files, 51,902,763 bytes
- `model_z=0.5`: 12 files, 48,307,193 bytes
- `model_z=1`: 12 files, 48,300,376 bytes

All model files and sizes:

#### `model_z=0.05`
- `model_RLINE_remet_multidir_neutral1_x-1_L.json` — 4,025,034 bytes
- `model_RLINE_remet_multidir_neutral1_x0_L.json` — 4,029,569 bytes
- `model_RLINE_remet_multidir_neutral2_x-1_L.json` — 4,013,088 bytes
- `model_RLINE_remet_multidir_neutral2_x0_L.json` — 4,007,701 bytes
- `model_RLINE_remet_multidir_stable_2000_x-1_L.json` — 4,018,376 bytes
- `model_RLINE_remet_multidir_stable_2000_x0_L.json` — 4,029,759 bytes
- `model_RLINE_remet_multidir_unstable_2000_x-1_L.json` — 4,019,001 bytes
- `model_RLINE_remet_multidir_unstable_2000_x0_L.json` — 4,023,484 bytes
- `model_RLINE_remet_multidir_verystable_2000_x-1_L.json` — 3,993,817 bytes
- `model_RLINE_remet_multidir_verystable_2000_x0_L.json` — 4,005,528 bytes
- `model_RLINE_remet_multidir_veryunstable_2000_x-1_L.json` — 4,011,757 bytes
- `model_RLINE_remet_multidir_veryunstable_2000_x0_L.json` — 7,725,649 bytes

#### `model_z=0.5`
- `model_RLINE_remet_multidir_neutral1_x-1_M.json` — 4,022,827 bytes
- `model_RLINE_remet_multidir_neutral1_x0_M.json` — 4,023,004 bytes
- `model_RLINE_remet_multidir_neutral2_x-1_M.json` — 4,021,650 bytes
- `model_RLINE_remet_multidir_neutral2_x0_M.json` — 4,027,256 bytes
- `model_RLINE_remet_multidir_stable_2000_x-1_M.json` — 4,027,036 bytes
- `model_RLINE_remet_multidir_stable_2000_x0_M.json` — 4,029,705 bytes
- `model_RLINE_remet_multidir_unstable_2000_x-1_M.json` — 4,025,102 bytes
- `model_RLINE_remet_multidir_unstable_2000_x0_M.json` — 4,032,801 bytes
- `model_RLINE_remet_multidir_verystable_2000_x-1_M.json` — 4,027,535 bytes
- `model_RLINE_remet_multidir_verystable_2000_x0_M.json` — 4,026,125 bytes
- `model_RLINE_remet_multidir_veryunstable_2000_x-1_M.json` — 4,023,740 bytes
- `model_RLINE_remet_multidir_veryunstable_2000_x0_M.json` — 4,020,412 bytes

#### `model_z=1`
- `model_RLINE_remet_multidir_neutral1_x-1_H.json` — 4,016,793 bytes
- `model_RLINE_remet_multidir_neutral1_x0_H.json` — 4,024,287 bytes
- `model_RLINE_remet_multidir_neutral2_x-1_H.json` — 4,024,768 bytes
- `model_RLINE_remet_multidir_neutral2_x0_H.json` — 4,031,409 bytes
- `model_RLINE_remet_multidir_stable_2000_x-1_H.json` — 4,025,240 bytes
- `model_RLINE_remet_multidir_stable_2000_x0_H.json` — 4,031,012 bytes
- `model_RLINE_remet_multidir_unstable_2000_x-1_H.json` — 4,025,635 bytes
- `model_RLINE_remet_multidir_unstable_2000_x0_H.json` — 4,029,645 bytes
- `model_RLINE_remet_multidir_verystable_2000_x-1_H.json` — 4,022,214 bytes
- `model_RLINE_remet_multidir_verystable_2000_x0_H.json` — 4,020,030 bytes
- `model_RLINE_remet_multidir_veryunstable_2000_x-1_H.json` — 4,026,999 bytes
- `model_RLINE_remet_multidir_veryunstable_2000_x0_H.json` — 4,022,344 bytes

Naming convention from actual files plus `README_models.md`:

Pattern:
```text
model_RLINE_remet_multidir_<stability>[_2000]_<x-branch>_<roughness-tier>.json
```

Observed meaning:
- `RLINE_remet_multidir`: fixed model family prefix
- `<stability>`:
  - `stable`
  - `verystable`
  - `unstable`
  - `veryunstable`
  - `neutral1`
  - `neutral2`
- `_x0`:
  - downwind / positive-x model
- `_x-1`:
  - upwind / negative-x model
- `<roughness-tier>`:
  - `L` in `model_z=0.05`
  - `M` in `model_z=0.5`
  - `H` in `model_z=1`
- `_2000`:
  - present on stable/unstable/very stable/very unstable files
  - absent on `neutral1` / `neutral2`
  - its meaning is not documented in `README_models.md`

Important repo mismatch:
- `README_models.md:11-26` says model files should sit directly under `models/`
- actual repo stores them in subdirectories by roughness
- `mode_inference.py:471-482` loads from `MODEL_DIR` directly, so the script will not find the bundled files unless `MODEL_DIR` is changed or files are flattened/copied

### 3.7 New Dependencies Needed
Dependencies listed in `ps-xgb-aermod-rline-surrogate/requirements.txt`:
- `numpy`
- `pandas`
- `geopandas`
- `shapely`
- `pyproj`
- `xgboost`
- `scikit-learn`
- `matplotlib`
- `seaborn`
- `scipy`

Already present in main `requirements.txt`:
- `numpy`
- `pandas`
- `geopandas`
- `shapely`

Not already present in main `requirements.txt`:
- `pyproj`
- `xgboost`
- `scikit-learn`
- `matplotlib`
- `seaborn`
- `scipy`

Cross-check against actual imports in `mode_inference.py`:
- used in code:
  - `pyproj`
  - `xgboost`
  - `scipy`
  - `matplotlib`
  - `scikit-learn`
- listed in surrogate requirements but not imported in `mode_inference.py`:
  - `seaborn`

## 4. Integration Points
### 4.1 Where to decouple visualization from macro_emission
Exact code blocks to extract or isolate:

1. Geometry preservation in tool preprocessing:
   - `tools/macro_emission.py:130-135`
   - `_fix_common_errors()` currently keeps geometry-like columns for later visualization

2. Geometry extraction from shapefile ZIP:
   - `tools/macro_emission.py:500-525`
   - `_read_shapefile_from_zip()` serializes shapefile geometry into JSON-friendly coordinate lists

3. Geometry preservation from Excel/CSV:
   - `skills/macro_emission/excel_handler.py:161-166`
   - `read_links_from_excel()` copies a `geometry` column into each `link_data`

4. Map-payload construction:
   - `tools/macro_emission.py:237-431`
   - entire `_build_map_data(...)` method
   - this is the main visualization-specific block

5. Tool return-site coupling:
   - `tools/macro_emission.py:761-779`
   - `execute()` currently calls `_build_map_data(...)` and puts the result directly into `ToolResult.map_data`

Recommended extraction boundary:
- keep macro-emission calculation path responsible for:
  - input normalization
  - calculator invocation
  - tabular `ToolResult.data`
- move these spatial responsibilities into a separate shared component or new tool:
  - geometry parsing
  - coordinate validation
  - `map_data` schema assembly
  - pollutant/color-range selection

### 4.2 Where to add render_spatial_map tool
Current registration path for a new tool:

1. Tool implementation file:
   - create `tools/render_spatial_map.py`

2. Tool registration:
   - `tools/registry.py:74-113`
   - add a `try:` block in `init_tools()` similar to the existing ones

3. Tool definition for LLM tool-calling:
   - `tools/definitions.py:6-165`
   - add a new function entry to `TOOL_DEFINITIONS`

4. Tool exposure to context assembly:
   - `services/config_loader.py:64-73`
   - no extra code needed if `TOOL_DEFINITIONS` is updated
   - `core/assembler.py:34-37` already loads tool definitions automatically

5. Tool execution:
   - `core/executor.py:25-34`
   - no extra code needed beyond registry/init

6. Router/API integration:
   - for a single returned map payload, no router changes are required
   - `core/router_payload_utils.py:274-294`
   - `core/router.py:816-828`, `957-977`
   - `api/session.py:43-61`
   - `api/routes.py:136-199`, `304-347`
   already pass through any top-level `ToolResult.map_data`

Important limitation for Phase 2:
- `core/router_payload_utils.py:274-294` returns only the first `map_data`
- if Phase 2 needs multiple simultaneous spatial layers from multiple tools, this helper will need redesign

### 4.3 How to adapt emission output for dispersion input
Current macro-emission outputs vs current surrogate inputs:

Macro-emission per-link result provides:
- `link_id`
- `link_length_km`
- `traffic_flow_vph`
- `avg_speed_kph`
- `fleet_composition`
- `emissions_by_vehicle`
- `total_emissions_kg_per_hr`
- `emission_rates_g_per_veh_km`
- geometry only exists in original `links_data`, not calculator output

Current surrogate script expects:
- road geometry source:
  - shapefile with `NAME_1`, `geometry`, optional `width`
- emission time-series source:
  - CSV with `NAME`/`NAME_1`
  - `data_time`
  - `nox`
  - `length`

Field mapping needed:
- `link_id` -> `NAME_1` and/or `NAME`
- original geometry column -> shapefile/GeoDataFrame geometry
- `link_length_km` -> `length`
- `total_emissions_kg_per_hr["NOx"]` -> `nox`
- new/generated timestamp column -> `data_time`
- optional road width -> `width`

Unit conversion gap:
- `MacroEmissionTool` outputs `NOx` totals in `kg/h`
- `mode_inference.py:120` treats `nox` as if it can be converted to `g/s/m²` by dividing by `3600` and by road area
- inference from the code: `nox` is expected in `g/h`, not `kg/h`
- so Phase 2 must convert:
  - `NOx_kg_h * 1000 -> nox_g_h`

Format gap:
- macro-emission output is a single scenario snapshot unless the caller creates multiple hourly rows
- surrogate inference expects a time series aligned to meteorology rows
- Phase 2 must either:
  - generate hourly emission rows, or
  - refactor the surrogate interface to accept a single snapshot with a matching meteorology slice

Recommended adaptation target:
- do not force the current two-file (`roads.shp` + `hourly_emission.csv`) interface inside the app
- instead refactor the surrogate pipeline to accept one in-memory GeoDataFrame with:
  - stable road ID
  - geometry
  - length
  - optional width
  - timestamp
  - pollutant emission rate/value

### 4.4 Receptor grid -> GeoJSON conversion
Current receptor/intermediate geometry facts:
- `generate_receptors_custom_offset(...)` returns a `GeoDataFrame` with:
  - `NAME_1`
  - `segment_id`
  - `x`
  - `y`
  - `offset_from_buffer`
  - `true_offset`
  - `type`
  - `side` for near-road points
  - `geometry`
- `receptors_unique` keeps those columns
- final `time_series_conc` only keeps:
  - `Date`
  - `Receptor_ID`
  - `Receptor_X`
  - `Receptor_Y`
  - `Conc`

Conversion steps needed:

1. Join concentration results back to receptor metadata:
   - `Receptor_ID` -> row index of `receptors_unique`

2. Restore absolute UTM coordinates:
   - add `min_x`, `min_y` back

3. Convert to WGS-84:
   - inverse `utm51n -> wgs84`

4. Build GeoJSON:
   - geometry: `Point`
   - properties:
     - `Date`
     - `Conc`
     - `Receptor_ID`
     - `type`
     - `offset_from_buffer`
     - `true_offset`
     - `side`
     - maybe `segment_id`

5. If a continuous concentration surface is wanted instead of points:
   - current output is insufficient by itself
   - you must add an interpolation/contouring step or render points directly

### 4.5 Frontend changes needed for multi-layer rendering
What can be kept:
- Leaflet initialization approach:
  - `web/app.js:1831-1916`
- GIS basemap loader:
  - `web/app.js:1761-1774`
- GIS roadnetwork overlay loader:
  - `web/app.js:1776-1789`
- Leaflet layer control concept:
  - `web/app.js:1906-1912`

What must be rewritten:
- `web/app.js:1669-1754` `renderEmissionMap(...)`
  - hardcoded to one map card, one pollutant selector, one line-layer schema
- `web/app.js:1792-1829` `updateMapPollutant(...)`
  - hardcoded to polyline `_linkData`
- `web/app.js:1938-1984`
  - hardcoded to draw line `geometry` / `coordinates`

What must be added:
- geometry-type-aware rendering:
  - `LineString` / road segments
  - `Point` / receptors
  - optional `Polygon` or raster/contour layers
- multi-layer state:
  - road emissions
  - background GIS
  - receptor points
  - optional concentration surface
- legend recalculation for the active layer and active pollutant/time slice
- time-step switcher if dispersion results are temporal
- schema/version handling if `map_data` evolves away from `links`

Current frontend constraints that will block Phase 2 if left unchanged:
- it requires `map_data.links`
- it assumes line geometry only
- it assumes a single global color scale
- it does not support multiple independent map layers from the payload

## 5. Risk Assessment
### 5.1 Breaking changes if visualization is decoupled
Breaking points if `_build_map_data()` is removed without compatibility work:
- `tools/macro_emission.py:761-779`
  - macro emission would stop returning `ToolResult.map_data`
- `core/router_payload_utils.py:274-294`
  - router/API would have no map payload to forward
- `web/app.js:1117-1119`
  - frontend validity check requires `map_data.links.length > 0`
- `web/app.js:1669-1679`
  - renderer assumes `mapData.links[0].emissions`
- `web/app.js:1942-1951`
  - drawing assumes `link.geometry || link.coordinates`

Backward-compatibility requirement:
- if Phase 2 introduces GeoJSON `FeatureCollection` output directly, the existing frontend will break immediately
- either:
  - keep emitting the current `links` schema during migration, or
  - add a frontend adapter that can read both schemas

Additional payload risk:
- `core/router_payload_utils.py:274-294` only returns the first `map_data`
- a second spatial tool in the same turn would be silently ignored

### 5.2 Performance concerns
Observed current GIS asset sizes:
- `static_gis/roadnetwork.geojson`: 6,148,993 bytes, 25,370 features
- `static_gis/basemap.geojson`: 69,199 bytes, 16 features

Current mitigations already in code:
- API caches full GIS responses:
  - `api/routes.py:466-468`, `479-508`, `526-555`
- frontend caches loaded GIS JSON in memory:
  - `web/app.js:1758-1759`
- frontend uses Leaflet Canvas renderer:
  - `web/app.js:1856-1861`
- frontend uses adaptive line weights:
  - `web/app.js:1922-1936`

Remaining concerns:
- first-load parse/render cost for 25k-line road overlay is still substantial in the browser
- `mode_inference.py` loads 12 XGBoost models into memory at once for the selected roughness tier
- bundled model directory size is `142M`

Inference from `predict_time_series_xgb(...)` implementation:
- it constructs dense pairwise arrays:
  - `x_hat = rx_rot[:, None] - sx_rot[None, :]`
  - `y_hat = ry_rot[:, None] - sy_rot[None, :]`
- memory/time therefore scale with `num_receptors * num_sources` before model batching happens
- for large networks/grids, these dense masks will dominate runtime and memory

Operational concern:
- `generate_receptors_custom_offset(...)` always plots and calls `plt.show()`
- that blocks headless/server execution unless removed

### 5.3 Missing pieces
Missing for Phase 2 based on current codebase:
- no dedicated dispersion tool in `tools/`
- no router payload schema for multiple spatial layers
- no frontend support for point/grid/contour concentration layers
- no CRS metadata in current `map_data`
- no inverse coordinate transform from local UTM back to WGS-84 in the surrogate pipeline
- no export/write step for surrogate outputs
- no time-alignment validation between emission snapshots and meteorology rows
- no tests that lock the current `map_data` schema or GIS rendering behavior

## 6. Current Project Stats
Requested command results:

- `pytest --co -q 2>&1 | tail -5`
  - result: `143 tests collected in 1.21s`

- `python main.py health`
  - warning: `FlagEmbedding` not installed, local embedding mode unavailable
  - tool health:
    - `query_emission_factors` OK
    - `calculate_micro_emission` OK
    - `calculate_macro_emission` OK
    - `analyze_file` OK
    - `query_knowledge` OK
  - total tools: `5`

- `wc -l tools/macro_emission.py`
  - `788`

- `wc -l web/app.js`
  - `2166`

- `wc -l ps-xgb-aermod-rline-surrogate/mode_inference.py`
  - `708`

- `du -sh ps-xgb-aermod-rline-surrogate/models/`
  - `142M`

Dependency overlap summary:
- Surrogate requirements already in main project:
  - `numpy`
  - `pandas`
  - `geopandas`
  - `shapely`
- Surrogate requirements missing from main project:
  - `pyproj`
  - `xgboost`
  - `scikit-learn`
  - `matplotlib`
  - `seaborn`
  - `scipy`

Prompt / tool-selection state:
- `config/prompts/core.yaml:7-64`
  - no map/visualization-specific instructions
  - tool-selection instructions are limited to:
    - use tools rather than invent data
    - ask clarifying questions when needed
    - never guess vehicle type
    - if uploaded file `task_type` is already `micro_emission` or `macro_emission`, directly call the corresponding tool
- `core/task_state.py:94-107`
  - `ExecutionContext` fields are:
    - `selected_tool`
    - `completed_tools`
    - `tool_results`
    - `last_error`
  - result tracking / tool chaining today is entirely list-based:
    - `completed_tools` records the tool names already run
    - `tool_results` stores each executed tool call payload/result
    - there is no dedicated field for chained map layers, tool dependencies, or intermediate spatial artifacts
- `core/task_state.py:128-281`
  - `TaskState` fields are:
    - `stage`
    - `file_context`
    - `parameters`
    - `execution`
    - `control`
    - `session_id`
    - `user_message`
    - `_llm_response` (internal, not serialized)
  - `FileContext` fields are:
    - `has_file`
    - `file_path`
    - `grounded`
    - `task_type`
    - `confidence`
    - `column_mapping`
    - `evidence`
    - `row_count`
    - `columns`
    - `sample_rows`
    - `micro_mapping`
    - `macro_mapping`
    - `micro_has_required`
    - `macro_has_required`
  - `ControlState` fields are:
    - `steps_taken`
    - `max_steps`
    - `needs_user_input`
    - `clarification_question`
    - `stop_reason`

Current tool definitions from `tools/definitions.py:6-165`:

1. `query_emission_factors`
   - description: `Query vehicle emission factor curves by speed. Returns chart and data table.`
   - params:
     - `vehicle_type` string
     - `pollutants` array[string]
     - `model_year` integer
     - `season` string
     - `road_type` string
     - `return_curve` boolean
   - required:
     - `vehicle_type`
     - `model_year`

2. `calculate_micro_emission`
   - description: `Calculate second-by-second emissions from vehicle trajectory data (time + speed). Use file_path for uploaded files.`
   - params:
     - `file_path` string
     - `trajectory_data` array[object]
     - `vehicle_type` string
     - `pollutants` array[string]
     - `model_year` integer
     - `season` string
   - required:
     - `vehicle_type`

3. `calculate_macro_emission`
   - description: `Calculate road link emissions from traffic data (length + flow + speed). Use file_path for uploaded files.`
   - params:
     - `file_path` string
     - `links_data` array[object]
     - `pollutants` array[string]
     - `fleet_mix` object
     - `model_year` integer
     - `season` string
   - required:
     - none

4. `analyze_file`
   - description: `Analyze uploaded file structure. Returns columns, data type, and preview.`
   - params:
     - `file_path` string
   - required:
     - `file_path`

5. `query_knowledge`
   - description: `Search emission knowledge base for standards, regulations, and technical concepts.`
   - params:
     - `query` string
     - `top_k` integer
     - `expectation` string
   - required:
     - `query`
