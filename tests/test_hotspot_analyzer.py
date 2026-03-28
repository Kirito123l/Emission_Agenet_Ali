"""Tests for HotspotAnalyzer."""

from __future__ import annotations

import numpy as np

from calculators.hotspot_analyzer import HotspotAnalyzer


def _build_raster_grid(matrix, resolution: float = 50.0) -> dict:
    arr = np.asarray(matrix, dtype=float)
    rows, cols = arr.shape
    cell_centers = []
    cell_receptor_map = {}
    receptor_idx = 0

    for row in range(rows):
        for col in range(cols):
            key = f"{row}_{col}"
            cell_receptor_map[key] = [receptor_idx]
            if arr[row, col] > 0:
                cell_centers.append(
                    {
                        "row": row,
                        "col": col,
                        "lon": 121.4 + col * 0.001,
                        "lat": 31.2 + row * 0.001,
                        "mean_conc": float(arr[row, col]),
                        "max_conc": float(arr[row, col]),
                    }
                )
            receptor_idx += 1

    return {
        "matrix_mean": arr.tolist(),
        "matrix_max": arr.tolist(),
        "resolution_m": resolution,
        "rows": rows,
        "cols": cols,
        "bbox_wgs84": [
            121.4,
            31.2,
            121.4 + max(cols - 1, 0) * 0.001,
            31.2 + max(rows - 1, 0) * 0.001,
        ],
        "cell_receptor_map": cell_receptor_map,
        "cell_centers_wgs84": cell_centers,
        "stats": {
            "total_cells": int(rows * cols),
            "nonzero_cells": int(np.count_nonzero(arr > 0)),
            "coverage_pct": float(np.count_nonzero(arr > 0) / (rows * cols) * 100.0) if rows and cols else 0.0,
        },
        "nodata": 0.0,
        "bbox_local": [0.0, 0.0, float(cols * resolution), float(rows * resolution)],
    }


class TestHotspotIdentification:
    def test_percentile_method(self):
        matrix = np.zeros((10, 10), dtype=float)
        matrix[0:2, 8:10] = 10.0
        analyzer = HotspotAnalyzer()

        result = analyzer.analyze(
            raster_grid=_build_raster_grid(matrix),
            method="percentile",
            percentile=5.0,
        )

        assert result["status"] == "success"
        assert result["data"]["hotspot_count"] == 1
        assert result["data"]["hotspots"][0]["grid_cells"] == 4

    def test_threshold_method(self):
        matrix = np.zeros((10, 10), dtype=float)
        matrix[0:2, 8:10] = 10.0
        analyzer = HotspotAnalyzer()

        result = analyzer.analyze(
            raster_grid=_build_raster_grid(matrix),
            method="threshold",
            threshold_value=5.0,
        )

        assert result["status"] == "success"
        assert result["data"]["hotspot_count"] == 1
        assert result["data"]["summary"]["cutoff_value"] == 5.0

    def test_no_hotspots(self):
        matrix = np.zeros((10, 10), dtype=float)
        matrix[0:2, 8:10] = 10.0
        analyzer = HotspotAnalyzer()

        result = analyzer.analyze(
            raster_grid=_build_raster_grid(matrix),
            method="threshold",
            threshold_value=100.0,
        )

        assert result["status"] == "success"
        assert result["data"]["hotspot_count"] == 0

    def test_all_zero_matrix(self):
        analyzer = HotspotAnalyzer()

        result = analyzer.analyze(
            raster_grid=_build_raster_grid(np.zeros((5, 5), dtype=float)),
            method="percentile",
            percentile=5.0,
        )

        assert result["status"] == "success"
        assert result["data"]["hotspot_count"] == 0

    def test_percentile_100(self):
        matrix = np.zeros((5, 5), dtype=float)
        matrix[1:3, 1:3] = 2.0
        analyzer = HotspotAnalyzer()

        result = analyzer.analyze(
            raster_grid=_build_raster_grid(matrix),
            method="percentile",
            percentile=100.0,
        )

        assert result["status"] == "success"
        assert result["data"]["hotspot_count"] == 1
        assert result["data"]["hotspots"][0]["grid_cells"] == 4


class TestSpatialClustering:
    def test_single_cluster(self):
        matrix = np.zeros((10, 10), dtype=float)
        matrix[2:5, 2:5] = 8.0
        analyzer = HotspotAnalyzer()

        result = analyzer.analyze(
            raster_grid=_build_raster_grid(matrix),
            method="threshold",
            threshold_value=1.0,
        )

        assert result["data"]["hotspot_count"] == 1
        assert result["data"]["hotspots"][0]["grid_cells"] == 9

    def test_two_separate_clusters(self):
        matrix = np.zeros((10, 10), dtype=float)
        matrix[1:3, 1:3] = 7.0
        matrix[7:9, 7:9] = 9.0
        analyzer = HotspotAnalyzer()

        result = analyzer.analyze(
            raster_grid=_build_raster_grid(matrix),
            method="threshold",
            threshold_value=1.0,
        )

        assert result["data"]["hotspot_count"] == 2

    def test_diagonal_not_connected(self):
        matrix = np.zeros((3, 3), dtype=float)
        matrix[0, 0] = 5.0
        matrix[1, 1] = 5.0
        analyzer = HotspotAnalyzer()

        result = analyzer.analyze(
            raster_grid=_build_raster_grid(matrix),
            method="threshold",
            threshold_value=1.0,
            min_hotspot_area_m2=0.0,
        )

        assert result["data"]["hotspot_count"] == 2

    def test_min_area_filter(self):
        matrix = np.zeros((5, 5), dtype=float)
        matrix[0, 0] = 8.0
        matrix[2:4, 2:4] = 6.0
        analyzer = HotspotAnalyzer()

        result = analyzer.analyze(
            raster_grid=_build_raster_grid(matrix),
            method="threshold",
            threshold_value=1.0,
            min_hotspot_area_m2=5000.0,
        )

        assert result["data"]["hotspot_count"] == 1
        assert result["data"]["hotspots"][0]["grid_cells"] == 4


class TestSourceAttribution:
    def test_attribution_basic(self):
        matrix = np.array([[5.0, 6.0]], dtype=float)
        raster_grid = _build_raster_grid(matrix)
        raster_grid["cell_receptor_map"] = {"0_0": [0, 1], "0_1": [2]}
        road_contributions = {
            "receptor_top_roads": {
                "0": [(0, 5.0), (1, 3.0)],
                "1": [(0, 4.0)],
                "2": [(1, 7.0)],
            },
            "road_id_map": ["road_A", "road_B"],
            "tracking_mode": "dense_exact",
        }
        analyzer = HotspotAnalyzer()

        result = analyzer.analyze(
            raster_grid=raster_grid,
            road_contributions=road_contributions,
            method="threshold",
            threshold_value=1.0,
        )

        roads = result["data"]["hotspots"][0]["contributing_roads"]
        assert roads[0]["link_id"] == "road_B"
        assert roads[0]["contribution_value"] == 10.0
        assert roads[1]["link_id"] == "road_A"
        assert roads[1]["contribution_value"] == 9.0

    def test_attribution_disabled(self):
        matrix = np.array([[5.0, 6.0]], dtype=float)
        raster_grid = _build_raster_grid(matrix)
        analyzer = HotspotAnalyzer()

        result = analyzer.analyze(
            raster_grid=raster_grid,
            road_contributions={
                "receptor_top_roads": {"0": [(0, 5.0)]},
                "road_id_map": ["road_A"],
            },
            method="threshold",
            threshold_value=1.0,
            source_attribution=False,
        )

        assert result["data"]["hotspots"][0]["contributing_roads"] == []

    def test_attribution_no_road_data(self):
        matrix = np.array([[5.0, 6.0]], dtype=float)
        analyzer = HotspotAnalyzer()

        result = analyzer.analyze(
            raster_grid=_build_raster_grid(matrix),
            road_contributions=None,
            method="threshold",
            threshold_value=1.0,
        )

        assert result["data"]["hotspots"][0]["contributing_roads"] == []

    def test_contribution_percentage_sum(self):
        matrix = np.array([[5.0, 6.0]], dtype=float)
        raster_grid = _build_raster_grid(matrix)
        raster_grid["cell_receptor_map"] = {"0_0": [0, 1], "0_1": [2]}
        road_contributions = {
            "receptor_top_roads": {
                "0": [{"road_idx": 0, "road_id": "road_A", "contribution": 5.0}],
                "1": [{"road_idx": 0, "road_id": "road_A", "contribution": 4.0}],
                "2": [{"road_idx": 1, "road_id": "road_B", "contribution": 9.0}],
            },
            "road_id_map": ["road_A", "road_B"],
            "tracking_mode": "dense_exact",
        }
        analyzer = HotspotAnalyzer()

        result = analyzer.analyze(
            raster_grid=raster_grid,
            road_contributions=road_contributions,
            method="threshold",
            threshold_value=1.0,
        )

        pct_sum = sum(road["contribution_pct"] for road in result["data"]["hotspots"][0]["contributing_roads"])
        assert 99.0 <= pct_sum <= 101.0


class TestInterpretation:
    def test_complete_regional_interpretation(self):
        analyzer = HotspotAnalyzer()

        interpretation = analyzer._build_interpretation(
            {"level": "complete_regional"},
            "percentile",
            5.0,
            None,
        )

        assert "区域污染热点识别" in interpretation

    def test_sparse_local_interpretation(self):
        analyzer = HotspotAnalyzer()

        interpretation = analyzer._build_interpretation(
            {"level": "sparse_local"},
            "percentile",
            5.0,
            None,
        )

        assert "局部热点贡献识别" in interpretation

    def test_partial_regional_interpretation(self):
        analyzer = HotspotAnalyzer()

        interpretation = analyzer._build_interpretation(
            {"level": "partial_regional"},
            "threshold",
            None,
            5.0,
        )

        assert "路网部分缺失" in interpretation


class TestMaxHotspots:
    def test_max_hotspots_limit(self):
        matrix = np.zeros((7, 7), dtype=float)
        matrix[0, 0] = 10.0
        matrix[0, 6] = 9.0
        matrix[3, 3] = 8.0
        matrix[6, 0] = 7.0
        matrix[6, 6] = 6.0
        analyzer = HotspotAnalyzer()

        result = analyzer.analyze(
            raster_grid=_build_raster_grid(matrix),
            method="threshold",
            threshold_value=1.0,
            min_hotspot_area_m2=0.0,
            max_hotspots=3,
        )

        assert result["data"]["hotspot_count"] == 3

    def test_ranking_by_max_concentration(self):
        matrix = np.zeros((5, 5), dtype=float)
        matrix[0, 0] = 5.0
        matrix[2, 2] = 8.0
        matrix[4, 4] = 6.0
        analyzer = HotspotAnalyzer()

        result = analyzer.analyze(
            raster_grid=_build_raster_grid(matrix),
            method="threshold",
            threshold_value=1.0,
            min_hotspot_area_m2=0.0,
        )

        max_concs = [hotspot["max_conc"] for hotspot in result["data"]["hotspots"]]
        assert max_concs == [8.0, 6.0, 5.0]
