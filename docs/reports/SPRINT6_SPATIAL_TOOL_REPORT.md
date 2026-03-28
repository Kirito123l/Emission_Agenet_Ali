# Sprint 6: Spatial Rendering Tool + Type System + Tool Dependencies

## 1. Files Created or Modified

### Created
- `core/spatial_types.py` — SpatialLayer and SpatialDataPackage type system
- `core/tool_dependencies.py` — Tool dependency graph
- `tools/spatial_renderer.py` — render_spatial_map tool
- `tests/test_spatial_types.py` — 7 tests for spatial types
- `tests/test_spatial_renderer.py` — 13 tests for spatial renderer
- `tests/test_tool_dependencies.py` — 9 tests for tool dependencies

### Modified
- `core/task_state.py` — Added `available_results: Set[str]` to ExecutionContext
- `tools/definitions.py` — Added render_spatial_map tool definition
- `tools/registry.py` — Added SpatialRendererTool registration
- `core/router.py` — Added last_result injection for render_spatial_map
- `config/prompts/core.yaml` — Added map visualization guidance

## 2. Full Content: `core/spatial_types.py`

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class SpatialLayer:
    layer_id: str
    geometry_type: str  # "line" | "point" | "polygon" | "grid"
    geojson: Dict[str, Any]
    color_field: str
    value_range: List[float]
    classification_mode: str = "continuous"
    color_scale: str = "YlOrRd"
    legend_title: str = ""
    legend_unit: Optional[str] = None
    opacity: float = 0.8
    weight: float = 2.0
    radius: float = 5.0
    style_hint: Optional[str] = None
    popup_fields: Optional[List[Dict[str, str]]] = None
    threshold: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        # Serializes all fields, excludes None optionals

@dataclass
class SpatialDataPackage:
    layers: List[SpatialLayer] = field(default_factory=list)
    title: str = ""
    bounds: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]: ...
    @staticmethod
    def compute_bounds_from_geojson(geojson: Dict) -> Dict[str, Any]: ...

def _extract_coords_recursive(coords, result): ...
```

## 3. Full Content: `core/tool_dependencies.py`

```python
TOOL_GRAPH = {
    "query_emission_factors":    {"requires": [],                  "provides": ["emission_factors"]},
    "calculate_micro_emission":  {"requires": [],                  "provides": ["emission_result"]},
    "calculate_macro_emission":  {"requires": [],                  "provides": ["emission_result"]},
    "calculate_dispersion":      {"requires": ["emission_result"], "provides": ["dispersion_result"]},
    "render_spatial_map":        {"requires": [],                  "provides": ["visualization"]},
    "analyze_file":              {"requires": [],                  "provides": ["file_analysis"]},
    "query_knowledge":           {"requires": [],                  "provides": ["knowledge"]},
}

def get_missing_prerequisites(tool_name, available_results) -> List[str]: ...
def suggest_prerequisite_tool(missing_result) -> Optional[str]: ...
def get_tool_provides(tool_name) -> List[str]: ...
```

## 4. Key Code: `tools/spatial_renderer.py`

**execute method**: Accepts `data_source` (dict or "last_result"), `pollutant`, `title`, `layer_type`. Auto-detects layer type. Builds legacy-compatible map_data. Returns ToolResult with map_data.

**_build_emission_map**: Extracts results from data, computes emission intensity (kg/h/km), builds links array with geometry/emissions/rates, computes color scale min/max, computes center from coordinates. Output format: `{type, center, zoom, pollutant, unit, color_scale, links, summary}` — identical to existing macro_emission.py format.

## 5. Tool Definition Added to definitions.py

```python
{
    "type": "function",
    "function": {
        "name": "render_spatial_map",
        "description": "Render spatial data as an interactive map...",
        "parameters": {
            "type": "object",
            "properties": {
                "data_source": {"type": "string", "default": "last_result"},
                "pollutant": {"type": "string"},
                "title": {"type": "string"},
                "layer_type": {"type": "string", "enum": ["emission", "concentration", "points"]}
            },
            "required": []
        }
    }
}
```

## 6. How last_result Injection Works in the Router

In `core/router.py`'s `_state_handle_executing()`, before executing each tool call:

1. If the tool is `render_spatial_map`, create a mutable copy of arguments
2. Search this turn's accumulated `tool_results` in reverse for the first successful result with data
3. Inject it as `_last_result` into the arguments
4. Fallback: check `memory.get_fact_memory()["last_tool_snapshot"]` for cross-turn access
5. Pass `effective_arguments` (not original `tool_call.arguments`) to `executor.execute()`

## 7. System Prompt Additions

Added to `config/prompts/core.yaml` under new section "关于地图可视化":
- Use render_spatial_map after calculations when spatial visualization is needed
- Trigger on explicit visualization requests or geo-referenced data
- Use `data_source="last_result"` to chain with previous calculation
- Don't call it when user only wants numeric/tabular results
- For "calculate + show on map" requests: call calculation tool first, then render_spatial_map

## 8. Test Results

### Sprint 6 tests (29 new tests)
```
tests/test_spatial_types.py      — 7 passed
tests/test_spatial_renderer.py   — 13 passed
tests/test_tool_dependencies.py  — 9 passed
```

### Full test suite
```
172 passed in 5.36s
```

All 143 existing tests continue to pass. 29 new tests added.

## 9. Health Check Output

```
OK query_emission_factors
OK calculate_micro_emission
OK calculate_macro_emission
OK analyze_file
OK query_knowledge
OK render_spatial_map

Total tools: 6
```

## 10. Issues Encountered and Resolutions

1. **pytest-asyncio not installed**: Async test functions (`@pytest.mark.asyncio`) failed. Resolved by using `asyncio.run()` in synchronous test functions instead, matching the project's existing test patterns.

2. **No other issues**: The registry uses a `register(name, tool)` signature (not `register(tool)` with `tool.name`), so registration was straightforward. The router's `tool_call.arguments` is already a dict, so creating a mutable copy with `dict(tool_call.arguments or {})` was sufficient for injection.
