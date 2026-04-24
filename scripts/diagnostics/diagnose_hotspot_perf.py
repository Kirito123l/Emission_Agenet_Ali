#!/usr/bin/env python3
"""Diagnose analyze_hotspots performance on real or fallback dispersion data."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

from calculators.hotspot_analyzer import HotspotAnalyzer
from core.executor import ToolExecutor
from tools.hotspot import HotspotTool


TRACE_HISTORY_CANDIDATES = [
    Path("data/sessions/fcfdcd66-0f4e-4aa0-9b2f-7ebb1c718f03/history/ed665754.json"),
]
PAYLOAD_CANDIDATES = [
    Path("data/sessions/history/4b5712e5.json"),
    Path("data/sessions/history/e6b46af6.json"),
]


def extract_historical_trace_ms() -> Tuple[Optional[float], Optional[Path]]:
    """Extract the historical 39.61s hotspot trace if available."""
    pattern = re.compile(r"analyze_hotspots completed \((\d+(?:\.\d+)?)ms\)")
    for path in TRACE_HISTORY_CANDIDATES:
        if not path.exists():
            continue
        messages = json.loads(path.read_text(encoding="utf-8"))
        for message in messages:
            for step in message.get("trace_friendly", []) or []:
                description = str(step.get("description", ""))
                match = pattern.search(description)
                if match:
                    return float(match.group(1)), path
    return None, None


def load_real_dispersion_payload() -> Tuple[Optional[Dict[str, Any]], Optional[Path]]:
    """Load a stored dispersion payload from session history if available."""
    for path in PAYLOAD_CANDIDATES:
        if not path.exists():
            continue
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        fact_memory = snapshot.get("fact_memory", {})
        payload = fact_memory.get("last_spatial_data")
        if isinstance(payload, dict) and "raster_grid" in payload and "road_contributions" in payload:
            return payload, path
    return None, None


def build_mock_dispersion_payload() -> Tuple[Dict[str, Any], str]:
    """Fallback: generate a small but real dispersion payload without starting the server."""
    from unittest.mock import MagicMock, patch

    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import LineString

    from calculators.dispersion import DispersionCalculator, DispersionConfig

    roads = gpd.GeoDataFrame(
        {
            "NAME_1": [f"road_{idx}" for idx in range(20)],
            "geometry": [
                LineString([(121.4 + idx * 0.005, 31.2), (121.4 + idx * 0.005, 31.21)])
                for idx in range(20)
            ],
            "width": [7.0] * 20,
        },
        crs="EPSG:4326",
    )
    emissions = pd.DataFrame(
        {
            "NAME_1": [f"road_{idx}" for idx in range(20)],
            "data_time": ["2024-07-01 12:00:00"] * 20,
            "nox": [0.1] * 20,
            "length": [1.0] * 20,
        }
    )

    def mock_load_all_models(*args, **kwargs):
        model = MagicMock()
        model.predict.side_effect = lambda features: np.ones(len(features)) * 0.5
        model.num_features.return_value = 7
        return {
            stability: {"x0": model, "x-1": model}
            for stability in ["VS", "S", "N1", "N2", "U", "VU"]
        }

    with patch("calculators.dispersion.load_all_models", mock_load_all_models):
        calculator = DispersionCalculator(config=DispersionConfig(roughness_height=0.5))
        result = calculator.calculate(
            roads_gdf=roads,
            emissions_df=emissions,
            met_input="urban_summer_day",
            pollutant="NOx",
        )
    if result.get("status") != "success":
        raise RuntimeError(f"Fallback dispersion generation failed: {result}")
    return result["data"], "mock dispersion payload"


def describe_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Build a compact payload summary for console output."""
    raster_grid = data.get("raster_grid", {})
    road_contributions = data.get("road_contributions", {})
    concentration_grid = data.get("concentration_grid", {})
    return {
        "rows": raster_grid.get("rows"),
        "cols": raster_grid.get("cols"),
        "resolution_m": raster_grid.get("resolution_m"),
        "receptors": len(concentration_grid.get("receptors", [])) if isinstance(concentration_grid.get("receptors"), list) else 0,
        "cell_receptor_map": len(raster_grid.get("cell_receptor_map", {})) if isinstance(raster_grid.get("cell_receptor_map"), dict) else 0,
        "cell_centers": len(raster_grid.get("cell_centers_wgs84", [])) if isinstance(raster_grid.get("cell_centers_wgs84"), list) else 0,
        "receptor_top_roads": len(road_contributions.get("receptor_top_roads", {})) if isinstance(road_contributions.get("receptor_top_roads"), dict) else 0,
        "road_id_map": len(road_contributions.get("road_id_map", [])) if isinstance(road_contributions.get("road_id_map"), list) else 0,
    }


def measure_analyzer_steps(data: Dict[str, Any]) -> Dict[str, Any]:
    """Measure each hotspot-analysis stage directly on the payload."""
    analyzer = HotspotAnalyzer()
    raster_grid = data["raster_grid"]
    road_contributions = data.get("road_contributions")
    coverage_assessment = data.get("coverage_assessment")
    resolution = float(raster_grid.get("resolution_m", 0.0) or 0.0)

    t0 = time.perf_counter()
    matrix = np.asarray(raster_grid.get("matrix_mean", []), dtype=float)
    t1 = time.perf_counter()

    nonzero_values = matrix[matrix > 0]
    cutoff = float(np.percentile(nonzero_values, 95.0)) if nonzero_values.size else 0.0
    t2 = time.perf_counter()

    hotspot_mask = matrix >= cutoff
    selected_cells = int(np.count_nonzero(hotspot_mask))
    t3 = time.perf_counter()

    clusters = analyzer._cluster_hotspot_cells(hotspot_mask)
    raw_cluster_count = len(clusters)
    cell_area = resolution * resolution
    clusters = [cluster for cluster in clusters if len(cluster) * cell_area >= 2500.0]
    clusters = sorted(
        clusters,
        key=lambda cluster: (
            max(float(matrix[row, col]) for row, col in cluster),
            float(np.mean([matrix[row, col] for row, col in cluster])),
            len(cluster),
        ),
        reverse=True,
    )[:10]
    t4 = time.perf_counter()

    hotspots = [
        analyzer._build_hotspot_area(
            rank=rank,
            cluster=cluster,
            matrix=matrix,
            raster_grid=raster_grid,
            road_contributions=road_contributions,
            resolution=resolution,
        )
        for rank, cluster in enumerate(clusters, start=1)
    ]
    t5 = time.perf_counter()

    result = analyzer.analyze(
        raster_grid=raster_grid,
        road_contributions=road_contributions,
        coverage_assessment=coverage_assessment,
        method="percentile",
        percentile=5.0,
    )
    t6 = time.perf_counter()

    return {
        "matrix_extraction_s": t1 - t0,
        "threshold_calculation_s": t2 - t1,
        "hotspot_masking_s": t3 - t2,
        "clustering_s": t4 - t3,
        "building_hotspot_areas_s": t5 - t4,
        "analyze_total_s": t6 - t0,
        "hotspot_count": result.get("data", {}).get("hotspot_count", 0),
        "raw_cluster_count": raw_cluster_count,
        "kept_cluster_count": len(clusters),
        "selected_cells": selected_cells,
        "road_summary_per_hotspot": [len(hotspot.contributing_roads) for hotspot in hotspots[:3]],
    }


async def measure_tool_and_executor(data: Dict[str, Any]) -> Dict[str, Any]:
    """Measure the tool layer and executor layer on the same payload."""
    tool = HotspotTool()
    tool_start = time.perf_counter()
    tool_result = await tool.execute(
        _last_result={"success": True, "data": data},
        method="percentile",
        percentile=5.0,
    )
    tool_end = time.perf_counter()

    log_path = Path("/tmp/hotspot_executor_perf.log")
    logging.basicConfig(
        level=logging.INFO,
        handlers=[logging.FileHandler(log_path, mode="w", encoding="utf-8")],
        format="%(message)s",
        force=True,
    )
    executor = ToolExecutor()
    executor_start = time.perf_counter()
    executor_result = await executor.execute(
        "analyze_hotspots",
        {
            "_last_result": {"success": True, "data": data},
            "method": "percentile",
            "percentile": 5.0,
        },
    )
    executor_end = time.perf_counter()

    return {
        "tool_success": tool_result.success,
        "tool_elapsed_s": tool_end - tool_start,
        "executor_success": executor_result.get("success"),
        "executor_elapsed_s": executor_end - executor_start,
        "executor_trace_ms": executor_result.get("_trace", {}).get("duration_ms"),
        "executor_log_size_mb": log_path.stat().st_size / (1024 * 1024) if log_path.exists() else 0.0,
    }


def simulate_legacy_verbose_logging(data: Dict[str, Any]) -> Dict[str, Any]:
    """Estimate the cost of the old full-payload argument logging."""
    arguments = {
        "_last_result": {"success": True, "data": data},
        "method": "percentile",
        "percentile": 5.0,
    }
    log_path = Path("/tmp/hotspot_legacy_verbose.log")
    start = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as handle:
        handle.write(f"[Executor] Original arguments from LLM for analyze_hotspots: {arguments}\n")
        handle.write(f"[Executor] Standardized arguments: {arguments}\n")
    end = time.perf_counter()
    return {
        "elapsed_s": end - start,
        "log_size_mb": log_path.stat().st_size / (1024 * 1024) if log_path.exists() else 0.0,
    }


def print_section(title: str) -> None:
    print(f"\n== {title} ==")


def main() -> None:
    historical_ms, historical_path = extract_historical_trace_ms()
    payload, payload_path = load_real_dispersion_payload()
    source_label = str(payload_path) if payload_path else None
    if payload is None:
        payload, source_label = build_mock_dispersion_payload()

    print_section("Historical Baseline")
    if historical_ms is not None and historical_path is not None:
        print(f"Historical trace: {historical_ms:.0f} ms from {historical_path}")
    else:
        print("Historical trace: unavailable")

    print_section("Payload Summary")
    print(f"Payload source: {source_label}")
    for key, value in describe_payload(payload).items():
        print(f"{key}: {value}")

    print_section("Analyzer Step Timings")
    analyzer_stats = measure_analyzer_steps(payload)
    for key, value in analyzer_stats.items():
        if key.endswith("_s"):
            print(f"{key}: {value:.6f}")
        else:
            print(f"{key}: {value}")

    print_section("Tool And Executor Timings")
    tool_stats = asyncio.run(measure_tool_and_executor(payload))
    for key, value in tool_stats.items():
        if isinstance(value, float):
            print(f"{key}: {value:.6f}")
        else:
            print(f"{key}: {value}")

    print_section("Legacy Verbose Logging Simulation")
    legacy_stats = simulate_legacy_verbose_logging(payload)
    for key, value in legacy_stats.items():
        if isinstance(value, float):
            print(f"{key}: {value:.6f}")
        else:
            print(f"{key}: {value}")


if __name__ == "__main__":
    main()
