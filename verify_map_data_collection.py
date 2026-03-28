#!/usr/bin/env python3
"""Verify backend map_data extraction for multi-tool scenarios."""

from __future__ import annotations

from core.router_payload_utils import extract_map_data


def main() -> None:
    mock_tool_results = [
        {
            "tool_call_id": "call_1",
            "name": "render_spatial_map",
            "result": {
                "success": True,
                "data": {"type": "emission", "features": [{"id": 1}]},
                "map_data": {
                    "type": "emission",
                    "layers": [{"id": "emission_lines", "data": {"features": [{"id": 1}]}}],
                },
            },
        },
        {
            "tool_call_id": "call_2",
            "name": "calculate_dispersion",
            "result": {
                "success": True,
                "data": {
                    "raster_grid": {"matrix_mean": [[0.1, 0.2]], "resolution_m": 50},
                    "summary": {"mean_concentration": 0.15},
                },
                "map_data": {
                    "type": "raster",
                    "layers": [{"id": "concentration_raster", "data": {"features": [{"id": 2}]}}],
                },
            },
        },
    ]

    result = extract_map_data(mock_tool_results)

    print(f"Result type: {type(result)}")
    print(f"Result: {result}")

    if isinstance(result, dict) and result.get("type") == "map_collection":
        items = result.get("items", [])
        print(f"Map count: {len(items)}")
        for i, item in enumerate(items):
            print(f"  Item {i}: type={item.get('type')}, has_layers={bool(item.get('layers'))}")
        assert len(items) == 2, f"Expected 2 maps, got {len(items)}"
        assert items[0]["type"] == "emission"
        assert items[1]["type"] == "raster"
        print("Backend map_data collection: PASS")
        return

    if isinstance(result, dict) and result.get("type") in ("emission", "raster"):
        print("Only got single map_data, collection not working")
        raise SystemExit(1)

    print(f"Unexpected result: {result}")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
