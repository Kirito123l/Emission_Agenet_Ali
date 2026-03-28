"""Tests for the spatial type system."""

import pytest

from core.spatial_types import SpatialLayer, SpatialDataPackage, _extract_coords_recursive


def _make_layer(**overrides):
    defaults = {
        "layer_id": "test_layer",
        "geometry_type": "line",
        "geojson": {"type": "FeatureCollection", "features": []},
        "color_field": "CO2_KG_H",
        "value_range": [0.0, 10.0],
    }
    defaults.update(overrides)
    return SpatialLayer(**defaults)


def test_spatial_layer_to_dict():
    layer = _make_layer(
        legend_title="CO2 Emissions",
        legend_unit="kg/h",
        style_hint="choropleth",
        popup_fields=[{"field": "LINK_ID", "label": "Link"}],
        threshold={"value": 80, "above_color": "#ef4444"},
    )
    d = layer.to_dict()
    assert d["layer_id"] == "test_layer"
    assert d["geometry_type"] == "line"
    assert d["color_field"] == "CO2_KG_H"
    assert d["value_range"] == [0.0, 10.0]
    assert d["classification_mode"] == "continuous"
    assert d["color_scale"] == "YlOrRd"
    assert d["legend_title"] == "CO2 Emissions"
    assert d["legend_unit"] == "kg/h"
    assert d["opacity"] == 0.8
    assert d["weight"] == 2.0
    assert d["radius"] == 5.0
    assert d["style_hint"] == "choropleth"
    assert d["popup_fields"] == [{"field": "LINK_ID", "label": "Link"}]
    assert d["threshold"]["value"] == 80


def test_spatial_layer_excludes_none():
    layer = _make_layer()
    d = layer.to_dict()
    assert "legend_unit" not in d
    assert "style_hint" not in d
    assert "popup_fields" not in d
    assert "threshold" not in d
    # Required fields are always present
    assert "layer_id" in d
    assert "color_field" in d


def test_spatial_data_package_to_dict():
    layer1 = _make_layer(layer_id="layer_1")
    layer2 = _make_layer(layer_id="layer_2", geometry_type="point")
    pkg = SpatialDataPackage(
        layers=[layer1, layer2],
        title="Test Package",
        bounds={"center": [31.23, 121.47], "zoom": 12},
    )
    d = pkg.to_dict()
    assert d["title"] == "Test Package"
    assert d["layer_count"] == 2
    assert len(d["layers"]) == 2
    assert d["layers"][0]["layer_id"] == "layer_1"
    assert d["layers"][1]["geometry_type"] == "point"
    assert d["bounds"]["zoom"] == 12


def test_compute_bounds_from_geojson():
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [121.4, 31.2],
                        [121.5, 31.3],
                    ],
                },
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [121.45, 31.25],
                },
            },
        ],
    }
    bounds = SpatialDataPackage.compute_bounds_from_geojson(geojson)
    assert bounds["center"][0] == pytest.approx(31.25, abs=0.01)
    assert bounds["center"][1] == pytest.approx(121.45, abs=0.01)
    assert "zoom" in bounds
    assert "bbox" in bounds
    assert bounds["bbox"][0] == pytest.approx(121.4)
    assert bounds["bbox"][3] == pytest.approx(31.3)


def test_compute_bounds_empty():
    geojson = {"type": "FeatureCollection", "features": []}
    bounds = SpatialDataPackage.compute_bounds_from_geojson(geojson)
    # Fallback center
    assert bounds["center"] == [31.23, 121.47]
    assert bounds["zoom"] == 12


def test_compute_bounds_multilinestring():
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiLineString",
                    "coordinates": [
                        [[121.0, 31.0], [121.1, 31.1]],
                        [[121.2, 31.2], [121.3, 31.3]],
                    ],
                },
            },
        ],
    }
    bounds = SpatialDataPackage.compute_bounds_from_geojson(geojson)
    assert bounds["center"][0] == pytest.approx(31.15, abs=0.01)
    assert bounds["center"][1] == pytest.approx(121.15, abs=0.01)


def test_extract_coords_recursive_nested():
    """Test recursive extraction handles deeply nested coordinates."""
    coords = [[[1.0, 2.0], [3.0, 4.0]], [[5.0, 6.0]]]
    result = []
    _extract_coords_recursive(coords, result)
    assert len(result) == 3
    assert result[0] == [1.0, 2.0]
    assert result[2] == [5.0, 6.0]
