"""Tests for the spatial renderer tool."""

import asyncio

import pytest

from tools.spatial_renderer import SpatialRendererTool, _parse_wkt_linestring


@pytest.fixture
def renderer():
    return SpatialRendererTool()


def _make_emission_result(with_geometry=True, pollutant="CO2"):
    """Create a mock emission result matching MacroEmissionTool output format."""
    link = {
        "link_id": "L001",
        "link_length_km": 2.0,
        "avg_speed_kph": 40.0,
        "traffic_flow_vph": 1000,
        "total_emissions_kg_per_hr": {pollutant: 5.0, "NOx": 0.5},
        "emission_rates_g_per_veh_km": {pollutant: 2.5, "NOx": 0.25},
    }
    if with_geometry:
        link["geometry"] = [[121.4, 31.2], [121.5, 31.3]]

    return {
        "success": True,
        "data": {
            "query_info": {"pollutants": [pollutant, "NOx"]},
            "results": [link],
            "summary": {"total_links": 1},
        },
    }


def _make_concentration_result(
    n_receptors=10,
    use_grid=True,
    mean_values=None,
):
    """Create a mock dispersion result with concentration data."""
    mean_values = mean_values or [float(i + 1) for i in range(n_receptors)]
    n_receptors = len(mean_values)
    results = []
    receptors = []

    for i in range(n_receptors):
        mean_conc = mean_values[i]
        max_conc = mean_conc * 2 if mean_conc > 0 else 0.0
        receptor = {
            "receptor_id": i,
            "lon": 121.4 + i * 0.001,
            "lat": 31.2 + i * 0.001,
            "local_x": float(i * 10),
            "local_y": float(i * 10),
            "concentrations": {"2024070112": mean_conc},
            "mean_conc": mean_conc,
            "max_conc": max_conc,
        }
        results.append(receptor)
        receptors.append(
            {
                "receptor_id": i,
                "lon": receptor["lon"],
                "lat": receptor["lat"],
                "mean_conc": mean_conc,
                "max_conc": max_conc,
            }
        )

    data = {
        "query_info": {"pollutant": "NOx"},
        "results": results,
        "summary": {
            "receptor_count": n_receptors,
            "mean_concentration": sum(mean_values) / len(mean_values) if mean_values else 0.0,
            "max_concentration": max(mean_values) if mean_values else 0.0,
            "unit": "μg/m³",
        },
    }
    if use_grid:
        data["concentration_grid"] = {
            "receptors": receptors,
            "bounds": {
                "min_lon": receptors[0]["lon"] if receptors else 0.0,
                "max_lon": receptors[-1]["lon"] if receptors else 0.0,
                "min_lat": receptors[0]["lat"] if receptors else 0.0,
                "max_lat": receptors[-1]["lat"] if receptors else 0.0,
            },
        }

    return {"success": True, "data": data}


def _make_raster_result():
    raster_grid = {
        "matrix_mean": [[0.0, 0.2, 1.5], [0.1, 0.5, 2.0]],
        "matrix_max": [[0.0, 0.3, 2.0], [0.2, 0.7, 2.5]],
        "resolution_m": 50,
        "rows": 2,
        "cols": 3,
        "bbox_wgs84": [121.4, 31.2, 121.406, 31.204],
        "cell_centers_wgs84": [
            {"row": 0, "col": 1, "lon": 121.402, "lat": 31.201, "mean_conc": 0.2, "max_conc": 0.3},
            {"row": 0, "col": 2, "lon": 121.404, "lat": 31.201, "mean_conc": 1.5, "max_conc": 2.0},
            {"row": 1, "col": 0, "lon": 121.400, "lat": 31.203, "mean_conc": 0.1, "max_conc": 0.2},
            {"row": 1, "col": 1, "lon": 121.402, "lat": 31.203, "mean_conc": 0.5, "max_conc": 0.7},
            {"row": 1, "col": 2, "lon": 121.404, "lat": 31.203, "mean_conc": 2.0, "max_conc": 2.5},
        ],
        "stats": {"total_cells": 6, "nonzero_cells": 5, "coverage_pct": 83.3},
    }
    return {
        "success": True,
        "data": {
            "type": "concentration",
            "query_info": {"pollutant": "NOx"},
            "raster_grid": raster_grid,
            "coverage_assessment": {"level": "partial_regional", "warnings": ["road network incomplete"]},
        },
    }


def _make_hotspot_result():
    raster_result = _make_raster_result()
    return {
        "success": True,
        "data": {
            "type": "hotspot",
            "interpretation": "区域污染热点识别：浓度最高的 5% 栅格区域",
            "summary": {
                "hotspot_count": 2,
                "total_hotspot_area_m2": 7500.0,
                "area_fraction_pct": 50.0,
                "max_concentration": 2.5,
                "cutoff_value": 1.5,
                "method": "percentile",
                "unit": "μg/m³",
            },
            "hotspots": [
                {
                    "hotspot_id": 1,
                    "rank": 1,
                    "center": {"lon": 121.404, "lat": 31.203},
                    "bbox": [121.403, 31.202, 121.405, 31.204],
                    "area_m2": 5000.0,
                    "grid_cells": 2,
                    "max_conc": 2.5,
                    "mean_conc": 1.75,
                    "contributing_roads": [
                        {"link_id": "road_A", "contribution_pct": 60.0, "contribution_value": 1.5},
                        {"link_id": "road_B", "contribution_pct": 40.0, "contribution_value": 1.0},
                    ],
                },
                {
                    "hotspot_id": 2,
                    "rank": 2,
                    "center": {"lon": 121.402, "lat": 31.201},
                    "bbox": [121.401, 31.200, 121.403, 31.202],
                    "area_m2": 2500.0,
                    "grid_cells": 1,
                    "max_conc": 1.5,
                    "mean_conc": 1.5,
                    "contributing_roads": [
                        {"link_id": "road_C", "contribution_pct": 100.0, "contribution_value": 1.5},
                    ],
                },
            ],
            "raster_grid": raster_result["data"]["raster_grid"],
            "coverage_assessment": raster_result["data"]["coverage_assessment"],
            "query_info": {"pollutant": "NOx"},
        },
    }


def test_detect_layer_type_emission(renderer):
    data = {"data": {"results": [{"link_id": "1"}]}}
    assert renderer._detect_layer_type(data) == "emission"


def test_detect_layer_type_concentration(renderer):
    data = {"data": {"concentration_grid": []}}
    assert renderer._detect_layer_type(data) == "concentration"


def test_detect_layer_type_points(renderer):
    data = {"data": {"receptors": []}}
    assert renderer._detect_layer_type(data) == "points"


def test_detect_layer_type_fallback(renderer):
    data = {"data": {"something_else": True}}
    assert renderer._detect_layer_type(data) == "emission"


def test_build_emission_map_basic(renderer):
    result_data = _make_emission_result()
    map_data = renderer._build_emission_map(result_data, "CO2", "Test Map")

    assert map_data is not None
    assert map_data["type"] == "macro_emission_map"
    assert "center" in map_data
    assert "zoom" in map_data
    assert map_data["pollutant"] == "CO2"
    assert "color_scale" in map_data
    assert map_data["color_scale"]["min"] <= map_data["color_scale"]["max"]
    assert len(map_data["color_scale"]["colors"]) == 5
    assert "links" in map_data
    assert len(map_data["links"]) == 1
    assert map_data["links"][0]["link_id"] == "L001"
    assert "summary" in map_data
    assert map_data["summary"]["total_links"] == 1


def test_build_emission_map_no_geometry(renderer):
    result_data = _make_emission_result(with_geometry=False)
    map_data = renderer._build_emission_map(result_data, "CO2", "Test")
    assert map_data is None


def test_build_emission_map_can_reuse_source_links_geometry(renderer):
    result_data = _make_emission_result(with_geometry=False)
    source_links = [
        {
            "link_id": "L001",
            "geometry": "LINESTRING(121.4 31.2, 121.5 31.3)",
        }
    ]

    map_data = renderer._build_emission_map(
        result_data,
        "CO2",
        "Test",
        source_links=source_links,
    )

    assert map_data is not None
    assert map_data["links"][0]["geometry"] == [[121.4, 31.2], [121.5, 31.3]]


def test_build_emission_map_pollutant_selection(renderer):
    result_data = _make_emission_result(pollutant="NOx")
    map_data = renderer._build_emission_map(result_data, "NOx", "NOx Map")
    assert map_data["pollutant"] == "NOx"


def test_build_emission_map_auto_pollutant(renderer):
    """When pollutant is None, use first from query_info."""
    result_data = _make_emission_result(pollutant="CO2")
    map_data = renderer._build_emission_map(result_data, None, "Auto")
    assert map_data["pollutant"] == "CO2"


def test_build_emission_map_emission_intensity(renderer):
    """Verify emission intensity is computed as total / link_length."""
    result_data = _make_emission_result()
    map_data = renderer._build_emission_map(result_data, "CO2", "")
    link = map_data["links"][0]
    # CO2: 5.0 kg/h / 2.0 km = 2.5 kg/h/km
    assert link["emissions"]["CO2"] == 2.5


def test_execute_last_result(renderer):
    result_data = _make_emission_result()
    result = asyncio.run(renderer.execute(
        data_source="last_result",
        _last_result=result_data,
        pollutant="CO2",
    ))
    assert result.success is True
    assert result.map_data is not None
    assert result.map_data["type"] == "macro_emission_map"


def test_execute_no_last_result(renderer):
    result = asyncio.run(renderer.execute(data_source="last_result"))
    assert result.success is False
    assert "No previous result" in result.error


def test_execute_with_direct_data_and_source_links(renderer):
    result_data = _make_emission_result(with_geometry=False)["data"]
    source_links = [
        {
            "link_id": "L001",
            "geometry": [[121.4, 31.2], [121.5, 31.3]],
        }
    ]

    result = asyncio.run(
        renderer.execute(
            data_source=result_data,
            source_links=source_links,
            pollutant="CO2",
        )
    )

    assert result.success is True
    assert result.map_data is not None
    assert result.map_data["links"][0]["geometry"] == [[121.4, 31.2], [121.5, 31.3]]


def test_execute_direct_data(renderer):
    result_data = _make_emission_result()
    result = asyncio.run(renderer.execute(data_source=result_data, pollutant="CO2"))
    assert result.success is True
    assert result.map_data is not None


def test_build_emission_map_string_geometry(renderer):
    """Geometry stored as JSON string should be parsed."""
    import json
    result_data = _make_emission_result()
    link = result_data["data"]["results"][0]
    link["geometry"] = json.dumps([[121.4, 31.2], [121.5, 31.3]])
    map_data = renderer._build_emission_map(result_data, "CO2", "")
    assert map_data is not None
    assert len(map_data["links"]) == 1


# --- WKT geometry parsing tests ---


def test_parse_wkt_linestring_basic():
    coords = _parse_wkt_linestring("LINESTRING (121.4 31.2, 121.5 31.3)")
    assert coords == [[121.4, 31.2], [121.5, 31.3]]


def test_parse_wkt_linestring_no_space():
    coords = _parse_wkt_linestring("LINESTRING(121.4 31.2, 121.5 31.3)")
    assert coords == [[121.4, 31.2], [121.5, 31.3]]


def test_parse_wkt_linestring_many_points():
    wkt = "LINESTRING (121.4 31.2, 121.45 31.25, 121.5 31.3, 121.55 31.35)"
    coords = _parse_wkt_linestring(wkt)
    assert len(coords) == 4
    assert coords[0] == [121.4, 31.2]
    assert coords[3] == [121.55, 31.35]


def test_parse_wkt_multilinestring():
    wkt = "MULTILINESTRING ((121.4 31.2, 121.5 31.3), (121.6 31.4, 121.7 31.5))"
    coords = _parse_wkt_linestring(wkt)
    assert len(coords) == 4
    assert coords[0] == [121.4, 31.2]
    assert coords[2] == [121.6, 31.4]


def test_parse_wkt_returns_none_for_single_point():
    assert _parse_wkt_linestring("LINESTRING (121.4 31.2)") is None


def test_parse_wkt_returns_none_for_non_wkt():
    assert _parse_wkt_linestring("not a wkt string") is None


def test_parse_wkt_returns_none_for_non_string():
    assert _parse_wkt_linestring(12345) is None


def test_build_emission_map_wkt_geometry(renderer):
    """WKT LINESTRING geometry should be parsed and produce a valid map."""
    result_data = _make_emission_result()
    link = result_data["data"]["results"][0]
    link["geometry"] = "LINESTRING (121.4 31.2, 121.45 31.25, 121.5 31.3)"
    map_data = renderer._build_emission_map(result_data, "CO2", "WKT Test")
    assert map_data is not None
    assert len(map_data["links"]) == 1
    assert len(map_data["links"][0]["geometry"]) == 3


def test_build_emission_map_wkt_no_space(renderer):
    """WKT without space after keyword should also work."""
    result_data = _make_emission_result()
    link = result_data["data"]["results"][0]
    link["geometry"] = "LINESTRING(121.486 31.236, 121.487 31.235)"
    map_data = renderer._build_emission_map(result_data, "CO2", "")
    assert map_data is not None
    assert len(map_data["links"]) == 1


def test_build_concentration_map_basic(renderer):
    result_data = _make_concentration_result()
    map_data = renderer._build_concentration_map(result_data, "NOx", "NOx Concentration")

    assert map_data is not None
    assert map_data["type"] == "concentration"
    assert map_data["title"] == "NOx Concentration"
    assert "center" in map_data
    assert "zoom" in map_data
    assert "layers" in map_data
    assert len(map_data["layers"]) == 1
    assert map_data["layers"][0]["type"] == "circle"
    assert len(map_data["layers"][0]["data"]["features"]) == 10
    assert map_data["summary"]["receptor_count"] == 10


def test_build_concentration_map_from_results(renderer):
    result_data = _make_concentration_result(use_grid=False)
    map_data = renderer._build_concentration_map(result_data, "NOx", "")

    assert map_data is not None
    assert map_data["type"] == "concentration"
    assert len(map_data["layers"][0]["data"]["features"]) == 10


def test_build_concentration_map_empty_receptors(renderer):
    result_data = _make_concentration_result(n_receptors=0)
    result_data["data"]["concentration_grid"] = {"receptors": [], "bounds": {}}
    map_data = renderer._build_concentration_map(result_data, "NOx", "")
    assert map_data is None


def test_build_concentration_map_zero_concentration(renderer):
    result_data = _make_concentration_result(mean_values=[0.0] * 5)
    map_data = renderer._build_concentration_map(result_data, "NOx", "")

    assert map_data is not None
    assert len(map_data["layers"][0]["data"]["features"]) == 5
    assert map_data["layers"][0]["style"]["value_range"] == [0.0, 0.0]


def test_build_concentration_map_value_range(renderer):
    result_data = _make_concentration_result(mean_values=[1.5, 5.0, 10.5])
    map_data = renderer._build_concentration_map(result_data, "NOx", "")

    assert map_data["layers"][0]["style"]["value_range"] == [1.5, 10.5]


def test_detect_layer_type_with_concentration_grid(renderer):
    data = {"data": {"concentration_grid": {"receptors": [{"lon": 121.4, "lat": 31.2}]}}}
    assert renderer._detect_layer_type(data) == "concentration"


def test_execute_concentration_layer(renderer):
    result_data = _make_concentration_result()
    result = asyncio.run(
        renderer.execute(
            data_source="last_result",
            _last_result=result_data,
            pollutant="NOx",
        )
    )

    assert result.success is True
    assert result.map_data is not None
    assert result.map_data["type"] == "concentration"
    assert len(result.map_data["layers"][0]["data"]["features"]) == 10


class TestBuildRasterMap:
    def test_basic_raster(self, renderer):
        result_data = _make_raster_result()
        map_data = renderer._build_raster_map(result_data, "NOx", "Raster")

        assert map_data is not None
        assert map_data["type"] == "raster"
        assert map_data["layers"][0]["type"] == "polygon"
        features = map_data["layers"][0]["data"]["features"]
        assert len(features) == 5
        assert all(feature["geometry"]["type"] == "Polygon" for feature in features)

    def test_raster_polygon_coordinates(self, renderer):
        result_data = _make_raster_result()
        map_data = renderer._build_raster_map(result_data, "NOx", "")

        feature = map_data["layers"][0]["data"]["features"][0]
        coords = feature["geometry"]["coordinates"][0]
        assert len(coords) == 5
        assert coords[0] == coords[-1]

    def test_raster_value_range(self, renderer):
        result_data = _make_raster_result()
        map_data = renderer._build_raster_map(result_data, "NOx", "")
        assert map_data["layers"][0]["style"]["value_range"] == [0.1, 2.0]

    def test_raster_empty_cells(self, renderer):
        result_data = _make_raster_result()
        result_data["data"]["raster_grid"]["cell_centers_wgs84"] = []
        assert renderer._build_raster_map(result_data, "NOx", "") is None

    def test_raster_all_zero(self, renderer):
        result_data = _make_raster_result()
        for cell in result_data["data"]["raster_grid"]["cell_centers_wgs84"]:
            cell["mean_conc"] = 0.0
            cell["max_conc"] = 0.0
        assert renderer._build_raster_map(result_data, "NOx", "") is None

    def test_raster_resolution_in_title(self, renderer):
        result_data = _make_raster_result()
        map_data = renderer._build_raster_map(result_data, "NOx", None)
        assert "50m grid" in map_data["title"]


class TestBuildHotspotMap:
    def test_basic_hotspot(self, renderer):
        result_data = _make_hotspot_result()
        map_data = renderer._build_hotspot_map(result_data, "Hotspots")

        assert map_data is not None
        assert map_data["type"] == "hotspot"
        assert any(layer["id"] == "hotspot_areas" for layer in map_data["layers"])

    def test_hotspot_with_raster_background(self, renderer):
        result_data = _make_hotspot_result()
        map_data = renderer._build_hotspot_map(result_data, "")
        layer_ids = [layer["id"] for layer in map_data["layers"]]
        assert "concentration_raster" in layer_ids
        assert "hotspot_areas" in layer_ids

    def test_hotspot_popup_data(self, renderer):
        result_data = _make_hotspot_result()
        map_data = renderer._build_hotspot_map(result_data, "")
        hotspot_layer = next(layer for layer in map_data["layers"] if layer["id"] == "hotspot_areas")
        props = hotspot_layer["data"]["features"][0]["properties"]
        assert {"rank", "max_conc", "area_m2"} <= set(props)

    def test_contributing_road_ids(self, renderer):
        result_data = _make_hotspot_result()
        map_data = renderer._build_hotspot_map(result_data, "")
        assert set(map_data["contributing_road_ids"]) == {"road_A", "road_B", "road_C"}

    def test_empty_hotspots(self, renderer):
        result_data = _make_hotspot_result()
        result_data["data"]["hotspots"] = []
        assert renderer._build_hotspot_map(result_data, "") is None


class TestDetectLayerType:
    def test_detect_raster(self, renderer):
        data = {"data": {"raster_grid": {"cell_centers_wgs84": []}}}
        assert renderer._detect_layer_type(data) == "raster"

    def test_detect_hotspot(self, renderer):
        data = {"data": {"type": "hotspot", "hotspots": []}}
        assert renderer._detect_layer_type(data) == "hotspot"

    def test_detect_hotspot_by_hotspots_key(self, renderer):
        data = {"data": {"hotspots": [{"hotspot_id": 1}]}}
        assert renderer._detect_layer_type(data) == "hotspot"

    def test_detect_concentration_fallback(self, renderer):
        data = {"data": {"concentration_grid": {"receptors": [{"lon": 121.4, "lat": 31.2}]}}}
        assert renderer._detect_layer_type(data) == "concentration"

    def test_raster_priority_over_concentration(self, renderer):
        data = {
            "data": {
                "raster_grid": {"cell_centers_wgs84": [{"lon": 121.4, "lat": 31.2, "mean_conc": 1.0}]},
                "concentration_grid": {"receptors": [{"lon": 121.4, "lat": 31.2}]},
            }
        }
        assert renderer._detect_layer_type(data) == "raster"


class TestExecuteRasterAndHotspot:
    def test_execute_raster_type(self, renderer):
        result_data = _make_raster_result()
        result = asyncio.run(
            renderer.execute(
                data_source="last_result",
                _last_result=result_data,
                pollutant="NOx",
            )
        )

        assert result.success is True
        assert result.map_data is not None
        assert result.map_data["type"] == "raster"

    def test_execute_hotspot_type(self, renderer):
        result_data = _make_hotspot_result()
        result = asyncio.run(
            renderer.execute(
                data_source="last_result",
                _last_result=result_data,
            )
        )

        assert result.success is True
        assert result.map_data is not None
        assert result.map_data["type"] == "hotspot"
