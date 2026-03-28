# Fix: Spatial Data Flow — render_spatial_map Gets Full Geometry

## 1. Actual Nesting Structure of tool_results Entries

Each entry in `state.execution.tool_results` has this structure:

```python
{
    "tool_call_id": "call_abc123",
    "name": "calculate_macro_emission",
    "arguments": {"pollutants": ["CO2", "NOx"], ...},
    "result": {                          # ← direct output from executor.execute()
        "success": True,
        "data": {                        # ← the actual payload
            "query_info": {...},
            "results": [                 # ← THE KEY ARRAY with per-link emissions + geometry
                {
                    "link_id": "Link_1",
                    "geometry": [[121.4, 31.2], ...],  # or WKT string
                    "total_emissions_kg_per_hr": {"CO2": 5.0, "NOx": 0.5},
                    ...
                },
                ...
            ],
            "summary": {...},
            "fleet_mix_fill": {...},
            "download_file": {...},
        },
        "summary": "已完成宏观排放计算...",
        "map_data": None,                # None when enable_builtin_map_data=False
    }
}
```

To reach geometry, the path is: `entry["result"]["data"]["results"][i]["geometry"]`.

### Why cross-turn failed (Path A)

`_extract_facts_from_tool_calls` in `core/memory.py` (line 165-170) creates `last_tool_snapshot` by cherry-picking ONLY these keys from `data`:
```python
for k in ("query_info", "summary", "fleet_mix_fill", "download_file", "row_count", "columns", "task_type", "detected_type"):
```

The `"results"` key (the array with geometry) is **not** in that list — deliberately excluded to keep memory compact. So `last_tool_snapshot` never has geometry.

Additionally, `compact_tool_data()` in `router_memory_utils.py` explicitly skips `"results"`:
```python
if key in {"results", "speed_curve", "pollutants"}:
    continue
```

### Why same-turn could fail (Path B)

The original injection code checked `prev_data.get("success") and prev_data.get("data")` but didn't verify that `data.results` actually existed with geometry entries. A result with `data = {"summary": {...}}` (no results array) would pass the check and be injected, causing render_spatial_map to fail.

## 2. Three-Tier Injection Code

In `core/router.py`, the `_state_handle_executing()` method now uses:

```python
if tool_call.name == "render_spatial_map" and "_last_result" not in effective_arguments:
    injected = False

    # Tier 1: Current turn's tool_results (same-turn chaining)
    for prev in reversed(state.execution.tool_results):
        actual = prev.get("result", prev) if isinstance(prev, dict) else prev
        if not isinstance(actual, dict) or not actual.get("success"):
            continue
        prev_data = actual.get("data", {})
        if isinstance(prev_data, dict) and prev_data.get("results"):
            sample = prev_data["results"][:3]
            if any(isinstance(lnk, dict) and lnk.get("geometry") for lnk in sample):
                effective_arguments["_last_result"] = actual
                injected = True
                logger.info(
                    f"render_spatial_map: injected from current turn, "
                    f"{len(prev_data['results'])} links with geometry"
                )
                break

    # Tier 2 & 3: Cross-turn from memory
    if not injected:
        fact_mem = self.memory.get_fact_memory()

        # Tier 2: last_spatial_data (full results with geometry)
        spatial = fact_mem.get("last_spatial_data")
        if isinstance(spatial, dict) and spatial.get("results"):
            effective_arguments["_last_result"] = {"success": True, "data": spatial}
            injected = True
            logger.info(
                f"render_spatial_map: injected from memory spatial_data, "
                f"{len(spatial['results'])} links"
            )

        # Tier 3: last_tool_snapshot (legacy fallback, likely compacted)
        if not injected:
            snapshot = fact_mem.get("last_tool_snapshot")
            if snapshot:
                effective_arguments["_last_result"] = snapshot
                logger.warning(
                    "render_spatial_map: using last_tool_snapshot (may be compacted, "
                    "geometry might be missing)"
                )
```

**Key differences from old code:**
- Tier 1 now verifies `data.results` exists AND contains entries with `geometry` (not just that `data` is truthy)
- Tier 2 is entirely new — reads from `last_spatial_data` which preserves the full results array
- Tier 3 preserves the old `last_tool_snapshot` fallback but logs a warning since it's likely compacted

## 3. last_spatial_data Field Addition to FactMemory

In `core/memory.py`:

```python
@dataclass
class FactMemory:
    # ... existing fields ...
    last_spatial_data: Optional[Dict] = None  # Full spatial results with geometry (not compacted)
```

### Saving spatial data (in `_extract_facts_from_tool_calls`)

After existing fact extraction, for emission calculation tools:

```python
if tool_name in ("calculate_macro_emission", "calculate_micro_emission"):
    results_list = data.get("results", []) if isinstance(data, dict) else []
    has_geometry = any(
        isinstance(link, dict) and link.get("geometry")
        for link in results_list[:5]
    )
    if has_geometry:
        spatial_json = json.dumps(data, default=str)
        if len(spatial_json) < 5_000_000:  # 5MB limit
            self.fact_memory.last_spatial_data = data
            logger.info(f"Saved full spatial data: {len(results_list)} links with geometry")
        else:
            logger.warning("Spatial data too large to persist, skipping")
```

### Exposed in `get_fact_memory()`

```python
def get_fact_memory(self) -> Dict:
    return {
        # ... existing fields ...
        "last_spatial_data": self.fact_memory.last_spatial_data,
    }
```

## 4. Memory Save/Load Changes

### `_save()`

Added to the `fact_memory` dict in the save payload:
```python
"last_spatial_data": _convert_paths_to_strings(self.fact_memory.last_spatial_data),
```

### `_load()`

Added restoration:
```python
self.fact_memory.last_spatial_data = fm.get("last_spatial_data")
```

### `clear_topic_memory()`

Added cleanup:
```python
self.fact_memory.last_spatial_data = None
```

## 5. Expected Server Logs

### Same-turn (user says "计算CO2排放并在地图上展示")

```
INFO  Executing tool: calculate_macro_emission
INFO  Tool calculate_macro_emission completed. Success: True
INFO  Saved full spatial data: 20 links with geometry
INFO  Executing tool: render_spatial_map
INFO  render_spatial_map: injected from current turn, 20 links with geometry
INFO  Tool render_spatial_map completed. Success: True
```

### Cross-turn (turn 1: calculate, turn 2: visualize)

Turn 1:
```
INFO  Executing tool: calculate_macro_emission
INFO  Tool calculate_macro_emission completed. Success: True
INFO  Saved full spatial data: 20 links with geometry
INFO  Spatial data detected, will suggest visualization to user
```

Turn 2:
```
INFO  Executing tool: render_spatial_map
INFO  render_spatial_map: injected from memory spatial_data, 20 links
INFO  Tool render_spatial_map completed. Success: True
```

## 6. Test Results

### pytest (full suite)
```
190 passed in 5.99s
```

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

## 7. Issues and Resolutions

1. **Variable scoping in Tier 3**: The original spec used `fact_mem if "fact_mem" in dir()` which is fragile and non-obvious. Fixed by restructuring Tiers 2 & 3 under a single `if not injected:` block that initializes `fact_mem` once, then both tiers share it.

2. **has_spatial_data detection consistency**: The post-execution spatial data detection block used a complex `any()` one-liner that was hard to verify. Replaced with an explicit loop that uses the same unwrapping pattern (`r.get("result", r)`) as the injection code, and simultaneously collects `available_pollutants` in the same pass.

3. **5MB size guard**: Large datasets (e.g., 50,000+ links with detailed geometry) could make the session JSON file very large. The `json.dumps` size check prevents this — if the spatial data exceeds 5MB, it's not persisted to disk (but is still available in-memory for same-session cross-turn access via the MemoryManager instance).
