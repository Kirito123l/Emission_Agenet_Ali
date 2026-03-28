#!/usr/bin/env python3
"""End-to-end data flow simulation without server."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))


async def simulate() -> None:
    print("=" * 60)
    print("End-to-End Data Flow Simulation")
    print("=" * 60)

    print("\n--- Step 1: Macro Emission ---")
    from calculators.macro_emission import MacroEmissionCalculator

    source_links = [
        {
            "link_id": "road_1",
            "link_length_km": 0.5,
            "traffic_flow_vph": 1000,
            "avg_speed_kph": 40,
            "geometry": "LINESTRING(121.4 31.2, 121.405 31.2)",
        },
        {
            "link_id": "road_2",
            "link_length_km": 0.3,
            "traffic_flow_vph": 800,
            "avg_speed_kph": 50,
            "geometry": "LINESTRING(121.405 31.2, 121.41 31.205)",
        },
    ]

    calc = MacroEmissionCalculator()
    result = calc.calculate(
        links_data=source_links,
        pollutants=["NOx"],
        model_year=2020,
        season="夏季",
        default_fleet_mix=None,
    )
    print(f"Emission status: {result['status']}")
    print(f"Links calculated: {len(result['data']['results'])}")

    print("\n--- Step 2: Spatial Renderer ---")
    from tools.spatial_renderer import SpatialRendererTool

    renderer = SpatialRendererTool()
    render_result = await renderer.execute(data_source=result["data"], source_links=source_links)
    print(f"Render success: {render_result.success}")
    print(f"Has map_data: {render_result.map_data is not None}")
    if not render_result.success:
        print(f"Render error: {render_result.error}")
    if render_result.map_data:
        print(f"Map type: {render_result.map_data.get('type', 'unknown')}")
        layers = render_result.map_data.get("layers", [])
        print(f"Layers: {len(layers)}")
        if render_result.map_data.get("links"):
            print(f"Links: {len(render_result.map_data['links'])}")
        for layer in layers:
            features = layer.get("data", {}).get("features", [])
            print(f"  Layer '{layer.get('id')}': {len(features)} features")

    print("\n--- Step 3: Map Data Collection ---")
    from core.router_payload_utils import extract_map_data

    mock_tool_results = [
        {
            "name": "render_spatial_map",
            "result": {
                "success": True,
                "data": render_result.data,
                "map_data": render_result.map_data,
            },
        },
        {
            "name": "calculate_dispersion",
            "result": {
                "success": True,
                "data": {"summary": {"mean_concentration": 0.5}},
                "map_data": {
                    "type": "raster",
                    "layers": [{"id": "concentration_raster", "data": {"features": [{"id": "mock"}]}}],
                },
            },
        },
    ]

    collected = extract_map_data(mock_tool_results)
    print(f"Collected map_data type: {collected.get('type') if collected else None}")
    if collected and collected.get("type") == "map_collection":
        items = collected.get("items", [])
        print(f"Map items: {len(items)}")
        for i, item in enumerate(items):
            print(f"  Item {i}: type={item.get('type')}")
    elif collected:
        print(f"Single map: type={collected.get('type')}")
    else:
        print("No map_data collected!")

    print("\n--- Step 4: Frontend Payload Structure ---")
    if collected:
        if collected.get("type") == "map_collection":
            items = collected.get("items", [])
        elif isinstance(collected, list):
            items = collected
        else:
            items = [collected]

        print(f"Frontend would render {len(items)} map(s):")
        for item in items:
            map_type = item.get("type", "unknown")
            layers = item.get("layers", [])
            print(f"  - {map_type}: {len(layers)} layer(s)")
            for layer in layers:
                feat_count = len(layer.get("data", {}).get("features", []))
                print(f"    Layer '{layer.get('id')}': {feat_count} features")

    print("\n" + "=" * 60)
    print("Simulation Complete")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(simulate())
