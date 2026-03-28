"""Tests for raster grid aggregation."""

from __future__ import annotations

import numpy as np

from calculators import dispersion


def _origin():
    origin_x, origin_y = dispersion.convert_coords(121.4, 31.2, "EPSG:4326", 51, "north")
    return float(origin_x), float(origin_y)


class TestAggregateToRaster:
    def test_basic_aggregation(self):
        """Simple case: 4 receptors in a 100m grid."""
        origin_x, origin_y = _origin()
        raster = dispersion.aggregate_to_raster(
            receptor_x=np.array([10.0, 20.0, 210.0, 220.0]),
            receptor_y=np.array([10.0, 20.0, 10.0, 20.0]),
            concentrations=np.array([1.0, 3.0, 2.0, 4.0]),
            resolution_m=100.0,
            origin_x=origin_x,
            origin_y=origin_y,
            utm_zone=51,
            utm_hemisphere="north",
        )

        matrix_mean = np.asarray(raster["matrix_mean"], dtype=float)
        matrix_max = np.asarray(raster["matrix_max"], dtype=float)

        assert raster["rows"] == 2
        assert raster["cols"] == 4
        assert matrix_mean[0, 0] == 2.0
        assert matrix_max[0, 0] == 3.0
        assert matrix_mean[0, 2] == 3.0
        assert matrix_max[0, 2] == 4.0

    def test_resolution_50(self):
        """50m resolution produces finer grid."""
        origin_x, origin_y = _origin()
        raster = dispersion.aggregate_to_raster(
            receptor_x=np.array([10.0, 20.0, 210.0, 220.0]),
            receptor_y=np.array([10.0, 20.0, 10.0, 20.0]),
            concentrations=np.array([1.0, 3.0, 2.0, 4.0]),
            resolution_m=50.0,
            origin_x=origin_x,
            origin_y=origin_y,
            utm_zone=51,
            utm_hemisphere="north",
        )

        assert raster["cols"] == 6

    def test_resolution_200(self):
        """200m resolution produces coarser grid."""
        origin_x, origin_y = _origin()
        raster = dispersion.aggregate_to_raster(
            receptor_x=np.array([10.0, 20.0, 210.0, 220.0]),
            receptor_y=np.array([10.0, 20.0, 10.0, 20.0]),
            concentrations=np.array([1.0, 3.0, 2.0, 4.0]),
            resolution_m=200.0,
            origin_x=origin_x,
            origin_y=origin_y,
            utm_zone=51,
            utm_hemisphere="north",
        )

        assert raster["cols"] == 3

    def test_cell_receptor_map(self):
        """Receptor-to-cell mapping is correct."""
        origin_x, origin_y = _origin()
        raster = dispersion.aggregate_to_raster(
            receptor_x=np.array([10.0, 20.0, 210.0, 220.0]),
            receptor_y=np.array([10.0, 20.0, 10.0, 20.0]),
            concentrations=np.array([1.0, 3.0, 2.0, 4.0]),
            resolution_m=100.0,
            origin_x=origin_x,
            origin_y=origin_y,
            utm_zone=51,
            utm_hemisphere="north",
        )

        assert raster["cell_receptor_map"]["0_0"] == [0, 1]
        assert raster["cell_receptor_map"]["0_2"] == [2, 3]

    def test_zero_concentration_filtered(self):
        """cell_centers_wgs84 excludes zero-concentration cells."""
        origin_x, origin_y = _origin()
        raster = dispersion.aggregate_to_raster(
            receptor_x=np.array([10.0, 20.0, 210.0, 220.0]),
            receptor_y=np.array([10.0, 20.0, 10.0, 20.0]),
            concentrations=np.array([0.0, 0.0, 2.0, 4.0]),
            resolution_m=100.0,
            origin_x=origin_x,
            origin_y=origin_y,
            utm_zone=51,
            utm_hemisphere="north",
        )

        assert len(raster["cell_centers_wgs84"]) == 1
        assert raster["cell_centers_wgs84"][0]["mean_conc"] == 3.0

    def test_bbox_wgs84(self):
        """Bounding box is in valid WGS-84 range."""
        origin_x, origin_y = _origin()
        raster = dispersion.aggregate_to_raster(
            receptor_x=np.array([10.0, 20.0, 210.0, 220.0]),
            receptor_y=np.array([10.0, 20.0, 10.0, 20.0]),
            concentrations=np.array([1.0, 3.0, 2.0, 4.0]),
            resolution_m=100.0,
            origin_x=origin_x,
            origin_y=origin_y,
            utm_zone=51,
            utm_hemisphere="north",
        )

        min_lon, min_lat, max_lon, max_lat = raster["bbox_wgs84"]
        assert 120.0 < min_lon < 123.0
        assert 30.0 < min_lat < 33.0
        assert min_lon < max_lon
        assert min_lat < max_lat

    def test_stats(self):
        """Stats are computed correctly."""
        origin_x, origin_y = _origin()
        raster = dispersion.aggregate_to_raster(
            receptor_x=np.array([10.0, 20.0, 210.0, 220.0]),
            receptor_y=np.array([10.0, 20.0, 10.0, 20.0]),
            concentrations=np.array([1.0, 3.0, 0.0, 0.0]),
            resolution_m=100.0,
            origin_x=origin_x,
            origin_y=origin_y,
            utm_zone=51,
            utm_hemisphere="north",
        )

        assert raster["stats"]["total_cells"] == 8
        assert raster["stats"]["nonzero_cells"] == 1
        assert raster["stats"]["coverage_pct"] == 12.5

    def test_empty_receptors(self):
        """Empty input doesn't crash."""
        origin_x, origin_y = _origin()
        raster = dispersion.aggregate_to_raster(
            receptor_x=np.array([]),
            receptor_y=np.array([]),
            concentrations=np.array([]),
            resolution_m=100.0,
            origin_x=origin_x,
            origin_y=origin_y,
            utm_zone=51,
            utm_hemisphere="north",
        )

        assert raster["rows"] == 0
        assert raster["cols"] == 0
        assert raster["cell_receptor_map"] == {}

    def test_single_receptor(self):
        """Single receptor produces 1x1 grid."""
        origin_x, origin_y = _origin()
        raster = dispersion.aggregate_to_raster(
            receptor_x=np.array([10.0]),
            receptor_y=np.array([20.0]),
            concentrations=np.array([5.0]),
            resolution_m=100.0,
            origin_x=origin_x,
            origin_y=origin_y,
            utm_zone=51,
            utm_hemisphere="north",
        )

        assert raster["rows"] == 1
        assert raster["cols"] == 1
        assert raster["matrix_mean"] == [[5.0]]
