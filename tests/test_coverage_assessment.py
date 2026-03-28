"""Tests for road network coverage assessment."""

from __future__ import annotations

import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import LineString

from core.coverage_assessment import assess_coverage


BASE_LON = 121.4
BASE_LAT = 31.2
WGS84_TO_UTM51 = Transformer.from_crs("EPSG:4326", "EPSG:32651", always_xy=True)
UTM51_TO_WGS84 = Transformer.from_crs("EPSG:32651", "EPSG:4326", always_xy=True)
BASE_X, BASE_Y = WGS84_TO_UTM51.transform(BASE_LON, BASE_LAT)


def _to_wgs84_line(points_m):
    lon_lat = [UTM51_TO_WGS84.transform(BASE_X + x, BASE_Y + y) for x, y in points_m]
    return LineString(lon_lat)


def _make_grid_network(width_m, height_m, n_vertical, n_horizontal, start_x=0.0, start_y=0.0):
    lines = []
    if n_vertical > 0:
        xs = [start_x + width_m * idx / max(n_vertical - 1, 1) for idx in range(n_vertical)]
        for x in xs:
            lines.append(_to_wgs84_line([(x, start_y), (x, start_y + height_m)]))
    if n_horizontal > 0:
        ys = [start_y + height_m * idx / max(n_horizontal - 1, 1) for idx in range(n_horizontal)]
        for y in ys:
            lines.append(_to_wgs84_line([(start_x, y), (start_x + width_m, y)]))
    return gpd.GeoDataFrame(
        {"road_id": [f"road_{idx}" for idx in range(len(lines))], "geometry": lines},
        geometry="geometry",
        crs="EPSG:4326",
    )


class TestCoverageAssessment:
    def test_complete_regional(self):
        """Dense connected network -> complete_regional."""
        roads_gdf = _make_grid_network(1000.0, 1000.0, n_vertical=5, n_horizontal=5)

        coverage = assess_coverage(roads_gdf)

        assert coverage.level == "complete_regional"
        assert coverage.road_density_km_per_km2 > 8.0
        assert coverage.is_connected is True

    def test_partial_regional(self):
        """Medium density network -> partial_regional."""
        roads_gdf = _make_grid_network(2000.0, 2000.0, n_vertical=6, n_horizontal=6)

        coverage = assess_coverage(roads_gdf)

        assert coverage.level == "partial_regional"
        assert 3.0 <= coverage.road_density_km_per_km2 < 8.0

    def test_sparse_local(self):
        """Sparse disconnected roads -> sparse_local."""
        roads_gdf = _make_grid_network(800.0, 800.0, n_vertical=3, n_horizontal=1, start_x=0.0)
        extra = _make_grid_network(500.0, 500.0, n_vertical=1, n_horizontal=0, start_x=2500.0)
        roads_gdf = gpd.GeoDataFrame(
            {"geometry": list(roads_gdf.geometry) + list(extra.geometry)},
            geometry="geometry",
            crs="EPSG:4326",
        )

        coverage = assess_coverage(roads_gdf)

        assert coverage.level == "sparse_local"
        assert coverage.warnings

    def test_too_few_roads(self):
        """Less than 10 roads -> always sparse_local."""
        roads_gdf = _make_grid_network(500.0, 500.0, n_vertical=3, n_horizontal=2)

        coverage = assess_coverage(roads_gdf)

        assert coverage.road_count == 5
        assert coverage.level == "sparse_local"

    def test_disconnected_network(self):
        """Connected check: two distant clusters -> not connected."""
        cluster_a = _make_grid_network(500.0, 500.0, n_vertical=3, n_horizontal=2, start_x=0.0)
        cluster_b = _make_grid_network(500.0, 500.0, n_vertical=3, n_horizontal=2, start_x=3000.0)
        roads_gdf = gpd.GeoDataFrame(
            {"geometry": list(cluster_a.geometry) + list(cluster_b.geometry)},
            geometry="geometry",
            crs="EPSG:4326",
        )

        coverage = assess_coverage(roads_gdf)

        assert coverage.is_connected is False
        assert coverage.max_gap_m > 1000.0

    def test_connected_network(self):
        """Connected check: nearby roads -> connected."""
        roads_gdf = _make_grid_network(1000.0, 1000.0, n_vertical=5, n_horizontal=5)

        coverage = assess_coverage(roads_gdf)

        assert coverage.is_connected is True
        assert coverage.max_gap_m == 0.0

    def test_single_road(self):
        """Edge case: only 1 road."""
        roads_gdf = _make_grid_network(500.0, 500.0, n_vertical=1, n_horizontal=0)

        coverage = assess_coverage(roads_gdf)

        assert coverage.level == "sparse_local"
        assert coverage.road_count == 1

    def test_to_dict(self):
        """Serialization works."""
        coverage = assess_coverage(_make_grid_network(1000.0, 1000.0, n_vertical=5, n_horizontal=5))
        payload = coverage.to_dict()

        assert {
            "level",
            "convex_hull_area_km2",
            "total_road_length_km",
            "road_density_km_per_km2",
            "road_count",
            "is_connected",
            "max_gap_m",
            "result_semantics",
            "warnings",
        } == set(payload)
