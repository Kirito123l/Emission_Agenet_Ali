"""Regression tests for executor handling of large injected payloads."""

from __future__ import annotations

import asyncio

from core.executor import ToolExecutor, summarize_arguments


def _build_large_last_result() -> dict:
    return {
        "success": True,
        "data": {
            "query_info": {
                "pollutant": "NOx",
                "pollutants": ["NOx"],
                "model_year": 2020,
                "season": "夏季",
            },
            "summary": {
                "mean_concentration": 0.013,
                "max_concentration": 1.0441,
                "unit": "μg/m³",
            },
            "results": [{} for _ in range(20)],
            "concentration_grid": {
                "receptors": [{"receptor_id": idx} for idx in range(4)],
                "time_keys": ["2024010100"],
            },
            "raster_grid": {
                "matrix_mean": [[0.1, 0.2], [0.3, 0.4]],
                "rows": 2,
                "cols": 2,
                "resolution_m": 50,
                "cell_centers_wgs84": [{"row": 0, "col": 0}, {"row": 1, "col": 1}],
                "cell_receptor_map": {"0_0": [0, 1], "1_1": [2, 3]},
                "stats": {"nonzero_cells": 2},
            },
            "road_contributions": {
                "tracking_mode": "dense_exact",
                "receptor_top_roads": {"0": [(0, 1.0)], "1": [(1, 2.0)]},
                "road_id_map": ["road_A", "road_B"],
            },
            "coverage_assessment": {"level": "sparse_local", "warnings": ["missing roads"]},
            "meteorology_used": {
                "_source_mode": "preset",
                "_preset_name": "urban_summer_day",
                "wind_speed": 2.5,
                "wind_direction": 225.0,
                "stability_class": "VU",
                "mixing_height": 1500.0,
            },
        },
    }


def test_summarize_arguments_compacts_injected_last_result() -> None:
    summary = summarize_arguments(
        {
            "_last_result": _build_large_last_result(),
            "method": "percentile",
            "percentile": 5.0,
        }
    )

    injected = summary["_last_result"]
    assert injected["type"] == "injected_last_result"
    assert injected["success"] is True
    assert injected["data"]["raster_grid"]["rows"] == 2
    assert injected["data"]["raster_grid"]["cell_receptor_map"] == 2
    assert injected["data"]["road_contributions"]["receptor_top_roads"] == 2
    assert "matrix_mean" not in str(injected)


def test_executor_trace_keeps_large_last_result_summarized() -> None:
    executor = ToolExecutor()
    result = asyncio.run(
        executor.execute(
            "analyze_hotspots",
            {
                "_last_result": _build_large_last_result(),
                "method": "threshold",
                "threshold_value": 0.1,
            },
        )
    )

    assert result["success"] is True
    trace = result["_trace"]
    injected = trace["original_arguments"]["_last_result"]
    assert injected["type"] == "injected_last_result"
    assert injected["data"]["raster_grid"]["rows"] == 2
    assert "matrix_mean" not in str(trace["original_arguments"])
    assert "matrix_mean" not in str(trace["standardized_arguments"])
