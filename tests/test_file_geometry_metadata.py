"""Targeted tests for Phase 7.2 — geometry metadata detection in file analysis.

Verifies that _detect_geometry_metadata() correctly identifies:
- WKT columns (road geometry)
- GeoJSON columns (road geometry)
- start/end coordinate pairs (line-constructible road geometry)
- lon/lat point pairs (point only, not road)
- join key columns only (link_id, road_id)
- Chinese column aliases
- No geometry at all
- Serialisation roundtrip through GeometryMetadata dataclass
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from config import get_config, reset_config
from core.task_state import GeometryMetadata


@pytest.fixture(autouse=True)
def _restore_config():
    reset_config()
    yield
    reset_config()


# ── Helper ──────────────────────────────────────────────────────────


def _make_df(columns, sample_rows):
    """Create a pandas DataFrame with the given columns and sample data."""
    df = pd.DataFrame(sample_rows, columns=columns)
    return df


def _detect(columns, sample_rows, spatial_metadata=None):
    """Invoke the detector through a fresh FileAnalyzerTool instance."""
    from tools.file_analyzer import FileAnalyzerTool
    tool = FileAnalyzerTool()
    return tool._detect_geometry_metadata(
        columns=list(columns),
        sample_rows=sample_rows,
        spatial_metadata=spatial_metadata,
    )


# ── 1. WKT LINESTRING column ────────────────────────────────────────


def test_wkt_linestring_column_road_geometry_available():
    """Column named 'wkt' with LINESTRING values → road_geometry_available."""
    columns = ["link_id", "length_km", "flow", "wkt"]
    samples = [
        {
            "link_id": "L001",
            "length_km": 0.5,
            "flow": 1200,
            "wkt": "LINESTRING (121.4 31.2, 121.5 31.3, 121.6 31.4)",
        },
        {
            "link_id": "L002",
            "length_km": 1.2,
            "flow": 800,
            "wkt": "LINESTRING (121.7 31.5, 121.8 31.6)",
        },
    ]
    result = _detect(columns, samples)
    assert result["geometry_available"] is True
    assert result["road_geometry_available"] is True
    assert result["geometry_type"] == "wkt"
    assert result["confidence"] >= 0.85
    assert "wkt" in result["geometry_columns"]
    assert any("WKT geometry" in e for e in result["evidence"])


def test_wkt_column_name_no_value_fallback():
    """Column named 'geometry' but sample values are not WKT → limitation added."""
    columns = ["link_id", "geometry"]
    samples = [
        {"link_id": "L001", "geometry": "some_gis_id_12345"},
        {"link_id": "L002", "geometry": "some_gis_id_67890"},
    ]
    result = _detect(columns, samples)
    assert "geometry" in result["geometry_columns"]
    # Without recognized WKT/GeoJSON value evidence, road_geometry should not be set
    assert result["road_geometry_available"] is False
    assert any(
        "sample values do not contain recognizable WKT" in lm
        for lm in result["limitations"]
    )


# ── 2. GeoJSON LineString column ────────────────────────────────────


def test_geojson_linestring_column_road_geometry_available():
    """Column named 'geojson' with LineString Feature → road_geometry_available."""
    columns = ["link_id", "geojson"]
    geojson_val = json.dumps({
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[121.4, 31.2], [121.5, 31.3]]},
        "properties": {},
    })
    samples = [
        {"link_id": "L001", "geojson": geojson_val},
        {"link_id": "L002", "geojson": geojson_val},
    ]
    result = _detect(columns, samples)
    assert result["geometry_available"] is True
    assert result["road_geometry_available"] is True
    assert result["geometry_type"] == "geojson"
    assert result["confidence"] >= 0.85
    assert any("GeoJSON geometry" in e for e in result["evidence"])


# ── 3. start/end coordinates → line-constructible road geometry ─────


def test_start_end_coordinates_line_constructible():
    """start_lon/start_lat/end_lon/end_lat → line_geometry_constructible, road_geometry."""
    columns = ["link_id", "start_lon", "start_lat", "end_lon", "end_lat", "flow"]
    samples = [
        {"link_id": "L001", "start_lon": 121.4, "start_lat": 31.2,
         "end_lon": 121.5, "end_lat": 31.3, "flow": 1200},
        {"link_id": "L002", "start_lon": 121.7, "start_lat": 31.5,
         "end_lon": 121.8, "end_lat": 31.6, "flow": 800},
    ]
    result = _detect(columns, samples)
    assert result["geometry_available"] is True
    assert result["road_geometry_available"] is True
    assert result["line_geometry_constructible"] is True
    assert result["geometry_type"] == "lonlat_linestring"
    assert result["confidence"] >= 0.80
    assert result["coordinate_columns"]["start_lon"] == "start_lon"
    assert result["coordinate_columns"]["start_lat"] == "start_lat"
    assert result["coordinate_columns"]["end_lon"] == "end_lon"
    assert result["coordinate_columns"]["end_lat"] == "end_lat"


def test_start_end_coordinates_alt_names():
    """from_lon/from_lat/to_lon/to_lat aliases detected."""
    columns = ["link_id", "from_lon", "from_lat", "to_lon", "to_lat"]
    samples = [
        {"link_id": "L001", "from_lon": 121.4, "from_lat": 31.2,
         "to_lon": 121.5, "to_lat": 31.3},
    ]
    result = _detect(columns, samples)
    assert result["road_geometry_available"] is True
    assert result["line_geometry_constructible"] is True
    assert result["geometry_type"] == "lonlat_linestring"


# ── 4. lon/lat only → point, NOT road ───────────────────────────────


def test_lon_lat_point_only_not_road():
    """lon/lat columns → point_geometry_available, NOT road_geometry_available."""
    columns = ["link_id", "lon", "lat", "flow"]
    samples = [
        {"link_id": "L001", "lon": 121.4, "lat": 31.2, "flow": 1200},
        {"link_id": "L002", "lon": 121.7, "lat": 31.5, "flow": 800},
    ]
    result = _detect(columns, samples)
    assert result["geometry_available"] is True
    assert result["point_geometry_available"] is True
    assert result["road_geometry_available"] is False
    assert result["line_geometry_constructible"] is False
    assert result["geometry_type"] == "lonlat_point"
    assert result["confidence"] <= 0.70
    assert result["coordinate_columns"]["lon"] == "lon"
    assert result["coordinate_columns"]["lat"] == "lat"
    assert any(
        "not sufficient for road segment" in lm
        for lm in result["limitations"]
    )


def test_longitude_latitude_point_not_road():
    """longitude/latitude columns → same as lon/lat."""
    columns = ["link_id", "longitude", "latitude", "speed"]
    samples = [
        {"link_id": "L001", "longitude": 121.4, "latitude": 31.2, "speed": 50},
    ]
    result = _detect(columns, samples)
    assert result["point_geometry_available"] is True
    assert result["road_geometry_available"] is False
    assert result["geometry_type"] == "lonlat_point"


# ── 5. link_id only → join_key_only ────────────────────────────────


def test_link_id_only_join_key():
    """Only link_id, no geometry → geometry_available false, join_key_only."""
    columns = ["link_id", "length_km", "flow", "speed"]
    samples = [
        {"link_id": "L001", "length_km": 0.5, "flow": 1200, "speed": 50},
        {"link_id": "L002", "length_km": 1.2, "flow": 800, "speed": 45},
    ]
    result = _detect(columns, samples)
    assert result["geometry_available"] is False
    assert result["road_geometry_available"] is False
    assert result["point_geometry_available"] is False
    assert result["geometry_type"] == "join_key_only"
    assert result["confidence"] <= 0.45
    assert "link_id" in result["join_key_columns"]
    assert any(
        "external geometry mapping required" in lm
        for lm in result["limitations"]
    )


def test_road_id_only_join_key():
    """road_id without geometry → join_key_only."""
    columns = ["road_id", "length", "flow"]
    samples = [{"road_id": "R123", "length": 1.0, "flow": 500}]
    result = _detect(columns, samples)
    assert result["geometry_type"] == "join_key_only"
    assert "road_id" in result["join_key_columns"]


# ── 6. road_id + WKT → join key AND geometry both detected ──────────


def test_road_id_and_wkt_both_detected():
    """Columns include road_id and WKT → join keys present, geometry available."""
    columns = ["road_id", "flow", "wkt"]
    samples = [
        {"road_id": "R001", "flow": 500, "wkt": "LINESTRING(121.4 31.2, 121.5 31.3)"},
        {"road_id": "R002", "flow": 300, "wkt": "LINESTRING(121.7 31.5, 121.8 31.6)"},
    ]
    result = _detect(columns, samples)
    assert "road_id" in result["join_key_columns"]
    assert result["geometry_available"] is True
    assert result["road_geometry_available"] is True
    assert result["geometry_type"] == "wkt"


# ── 7. Chinese column aliases ────────────────────────────────────────


def test_chinese_lon_lat_aliases():
    """经度/纬度 → point geometry detected."""
    columns = ["link_id", "经度", "纬度", "flow"]
    samples = [
        {"link_id": "L001", "经度": 121.4, "纬度": 31.2, "flow": 500},
    ]
    result = _detect(columns, samples)
    assert result["point_geometry_available"] is True
    assert result["geometry_type"] == "lonlat_point"


def test_chinese_start_end_coordinate_aliases():
    """起点经度/起点纬度/终点经度/终点纬度 → line_geometry_constructible."""
    columns = ["link_id", "起点经度", "起点纬度", "终点经度", "终点纬度"]
    samples = [
        {
            "link_id": "L001",
            "起点经度": 121.4, "起点纬度": 31.2,
            "终点经度": 121.5, "终点纬度": 31.3,
        },
    ]
    result = _detect(columns, samples)
    assert result["road_geometry_available"] is True
    assert result["line_geometry_constructible"] is True
    assert result["geometry_type"] == "lonlat_linestring"


def test_chinese_join_key_aliases():
    """路段编号/道路编号 → join_key_only."""
    columns = ["路段编号", "flow", "speed"]
    samples = [
        {"路段编号": "R001", "flow": 500, "speed": 50},
    ]
    result = _detect(columns, samples)
    assert result["geometry_type"] == "join_key_only"
    assert "路段编号" in result["join_key_columns"]


def test_chinese_geometry_column_alias():
    """几何 column → geometry column detected but needs value verification."""
    columns = ["link_id", "几何", "flow"]
    # Values are WKT in a column named 几何
    samples = [
        {"link_id": "L001", "几何": "LINESTRING (121.4 31.2, 121.5 31.3)", "flow": 500},
    ]
    result = _detect(columns, samples)
    assert "几何" in result["geometry_columns"]
    assert result["road_geometry_available"] is True
    assert result["geometry_type"] == "wkt"


# ── 8. No geometry at all ───────────────────────────────────────────


def test_no_geometry_columns():
    """File with emission-related columns but no geometry → geometry_available false."""
    columns = ["link_length_km", "traffic_flow_vph", "avg_speed_kph"]
    samples = [
        {"link_length_km": 0.5, "traffic_flow_vph": 1200, "avg_speed_kph": 50},
    ]
    result = _detect(columns, samples)
    assert result["geometry_available"] is False
    assert result["road_geometry_available"] is False
    assert result["point_geometry_available"] is False
    assert result["geometry_type"] == "none"
    assert result["confidence"] == 0.0
    assert len(result["limitations"]) >= 1
    assert any(
        "No geometry columns" in lm
        for lm in result["limitations"]
    )


# ── 9. GeometryMetadata serialisation roundtrip ─────────────────────


def test_geometry_metadata_serialisation_roundtrip():
    """GeometryMetadata → to_dict → from_dict → same values."""
    original = GeometryMetadata(
        geometry_available=True,
        road_geometry_available=True,
        point_geometry_available=False,
        line_geometry_constructible=False,
        geometry_type="wkt",
        geometry_columns=["wkt"],
        coordinate_columns={},
        join_key_columns={"link_id": "link_id"},
        confidence=0.90,
        evidence=["Column 'wkt': 2/2 sample(s) contain WKT geometry"],
        limitations=[],
    )
    d = original.to_dict()
    restored = GeometryMetadata.from_dict(d)
    assert restored.geometry_available == original.geometry_available
    assert restored.road_geometry_available == original.road_geometry_available
    assert restored.point_geometry_available == original.point_geometry_available
    assert restored.line_geometry_constructible == original.line_geometry_constructible
    assert restored.geometry_type == original.geometry_type
    assert restored.geometry_columns == original.geometry_columns
    assert restored.coordinate_columns == original.coordinate_columns
    assert restored.join_key_columns == original.join_key_columns
    assert restored.confidence == pytest.approx(original.confidence)
    assert restored.evidence == original.evidence
    assert restored.limitations == original.limitations


def test_geometry_metadata_default_none():
    """from_dict(None) returns default GeometryMetadata."""
    gm = GeometryMetadata.from_dict(None)
    assert gm.geometry_available is False
    assert gm.geometry_type == "none"
    assert gm.confidence == 0.0
    assert gm.geometry_columns == []


def test_geometry_metadata_from_empty_dict():
    """from_dict({}) also returns defaults."""
    gm = GeometryMetadata.from_dict({})
    assert gm.geometry_available is False
    assert gm.road_geometry_available is False


# ── 10. Integration: _analyze_structure includes geometry_metadata ───


def test_analyze_structure_includes_geometry_metadata():
    """Tabular data with WKT → _analyze_structure output has geometry_metadata."""
    from tools.file_analyzer import FileAnalyzerTool

    tool = FileAnalyzerTool()
    df = pd.DataFrame({
        "link_id": ["L001", "L002"],
        "link_length_km": [0.5, 1.2],
        "traffic_flow_vph": [1200, 800],
        "avg_speed_kph": [50, 45],
        "wkt": [
            "LINESTRING (121.4 31.2, 121.5 31.3)",
            "LINESTRING (121.7 31.5, 121.8 31.6)",
        ],
    })
    analysis = tool._analyze_structure(df, "roads_with_wkt.csv")
    assert "geometry_metadata" in analysis
    gm = analysis["geometry_metadata"]
    assert gm["geometry_available"] is True
    assert gm["road_geometry_available"] is True
    assert gm["geometry_type"] == "wkt"
    assert "wkt" in gm["geometry_columns"]


def test_analyze_structure_no_geometry_includes_metadata():
    """Tabular data without geometry still has geometry_metadata with false."""
    from tools.file_analyzer import FileAnalyzerTool

    tool = FileAnalyzerTool()
    df = pd.DataFrame({
        "link_id": ["L001", "L002"],
        "link_length_km": [0.5, 1.2],
        "traffic_flow_vph": [1200, 800],
        "avg_speed_kph": [50, 45],
    })
    analysis = tool._analyze_structure(df, "roads_no_geometry.csv")
    assert "geometry_metadata" in analysis
    gm = analysis["geometry_metadata"]
    assert gm["geometry_available"] is False
    assert gm["geometry_type"] == "join_key_only"


# ── 11. Spatial metadata (shapefile-style) flows through ────────────


def test_spatial_metadata_with_linestring_produces_geometry():
    """spatial_metadata with LineString → road_geometry_available via bootstrap."""
    columns = ["link_id", "flow"]
    samples = [{"link_id": "L001", "flow": 500}]
    spatial_metadata = {
        "geometry_column": "geometry",
        "feature_count": 100,
        "geometry_types": ["LineString"],
        "crs": "EPSG:4326",
        "bounds": {"min_x": 121.0, "min_y": 31.0, "max_x": 122.0, "max_y": 32.0},
    }
    result = _detect(columns, samples, spatial_metadata=spatial_metadata)
    assert result["geometry_available"] is True
    assert result["road_geometry_available"] is True
    assert result["geometry_type"] == "spatial_metadata"
    assert result["confidence"] >= 0.90


def test_spatial_metadata_point_only():
    """spatial_metadata with Point only → point but not road."""
    columns = ["link_id", "name"]
    samples = [{"link_id": "L001", "name": "Station A"}]
    spatial_metadata = {
        "geometry_types": ["Point"],
        "feature_count": 50,
    }
    result = _detect(columns, samples, spatial_metadata=spatial_metadata)
    assert result["point_geometry_available"] is True
    assert result["road_geometry_available"] is False


# ── 12. Coordinate pair narrow detection (x/y) ──────────────────────


def test_single_letter_x_y_not_mistaken_for_lon_lat():
    """Columns named 'x' and 'y' alone should not be treated as lon/lat."""
    columns = ["link_id", "x", "y", "flow"]
    samples = [{"link_id": "L001", "x": 100, "y": 200, "flow": 500}]
    result = _detect(columns, samples)
    # x/y with those names only should bypass coordinate detection
    assert result["geometry_type"] == "join_key_only"
