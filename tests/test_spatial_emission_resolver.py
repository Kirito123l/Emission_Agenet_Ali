"""Targeted tests for Phase 7.4A — spatial emission resolver foundation.

Verifies:
- WKT/GeoJSON/LineString geometry → SpatialEmissionCandidate available=true
- lon/lat point-only → unavailable, point_geometry_not_road_geometry
- join_key_only → unavailable, join_key_without_geometry
- no geometry → unavailable, missing_road_geometry
- evidence, confidence, limitations preserved
- source_file_path and emission_result_ref preserved
- serialisation roundtrip works
- does NOT invent geometry
- Chinese geometry aliases flow through GeometryMetadata
- compatible with check_road_geometry_from_metadata
"""

from __future__ import annotations

import pytest

from config import get_config, reset_config


@pytest.fixture(autouse=True)
def _restore_config():
    reset_config()
    yield
    reset_config()


# ── helpers ───────────────────────────────────────────────────────────


def _resolve(**file_context_kwargs):
    from core.spatial_emission_resolver import resolve_spatial_emission_candidate
    return resolve_spatial_emission_candidate(
        file_context=dict(file_context_kwargs),
        emission_result_ref="macro_emission:baseline",
    )


def _gm(**kw):
    """Build a geometry_metadata dict quickly."""
    return dict(kw)


# ── 1. WKT geometry → available true ─────────────────────────────────


def test_wkt_road_geometry_candidate_available():
    fc = {
        "file_path": "/tmp/roads_wkt.csv",
        "row_count": 100,
        "geometry_metadata": _gm(
            geometry_type="wkt",
            road_geometry_available=True,
            geometry_columns=["wkt"],
            join_key_columns={"link_id": "link_id"},
            confidence=0.90,
            evidence=["WKT values confirmed"],
        ),
    }
    cand = _resolve(**fc)
    assert cand.available is True
    assert cand.reason_code == "spatial_emission_available"
    assert cand.source_file_path == "/tmp/roads_wkt.csv"
    assert cand.emission_result_ref == "macro_emission:baseline"
    assert cand.geometry.geometry_type == "wkt"
    assert cand.geometry.confidence == 0.90
    assert "wkt" in cand.geometry.geometry_columns
    assert "link_id" in cand.join_keys
    assert cand.row_count == 100
    assert "WKT values confirmed" in str(cand.provenance.get("geometry_metadata_evidence"))


# ── 2. GeoJSON geometry → available true ─────────────────────────────


def test_geojson_road_geometry_candidate_available():
    fc = {
        "file_path": "/tmp/roads.geojson",
        "geometry_metadata": _gm(
            geometry_type="geojson",
            road_geometry_available=True,
            geometry_columns=["geojson"],
            confidence=0.90,
            evidence=["GeoJSON values confirmed"],
        ),
    }
    cand = _resolve(**fc)
    assert cand.available is True
    assert cand.reason_code == "spatial_emission_available"
    assert cand.geometry.geometry_type == "geojson"


# ── 3. lonlat_linestring → available / constructible ─────────────────


def test_lonlat_linestring_candidate_available():
    fc = {
        "file_path": "/tmp/roads.csv",
        "geometry_metadata": _gm(
            geometry_type="lonlat_linestring",
            road_geometry_available=True,
            line_geometry_constructible=True,
            coordinate_columns={
                "start_lon": "start_lon",
                "start_lat": "start_lat",
                "end_lon": "end_lon",
                "end_lat": "end_lat",
            },
            confidence=0.85,
            evidence=["Start/end coordinate columns detected"],
        ),
    }
    cand = _resolve(**fc)
    assert cand.available is True
    assert cand.reason_code == "spatial_emission_available"
    assert cand.geometry.geometry_type == "lonlat_linestring"
    assert "LineString" in cand.message or "constructible" in cand.message.lower()


def test_lonlat_linestring_coordinates_preserved():
    fc = {
        "geometry_metadata": _gm(
            geometry_type="lonlat_linestring",
            road_geometry_available=True,
            line_geometry_constructible=True,
            coordinate_columns={
                "start_lon": "slon", "start_lat": "slat",
                "end_lon": "elon", "end_lat": "elat",
            },
            confidence=0.85,
        ),
    }
    cand = _resolve(**fc)
    assert cand.geometry.coordinate_columns["start_lon"] == "slon"
    assert cand.geometry.coordinate_columns["end_lat"] == "elat"


# ── 4. lonlat_point → unavailable ────────────────────────────────────


def test_lonlat_point_candidate_unavailable():
    fc = {
        "file_path": "/tmp/roads_point.csv",
        "geometry_metadata": _gm(
            geometry_type="lonlat_point",
            road_geometry_available=False,
            point_geometry_available=True,
            coordinate_columns={"lon": "lon", "lat": "lat"},
            confidence=0.65,
            evidence=["Point coordinate columns detected"],
            limitations=["Not sufficient for road segment line geometry."],
        ),
    }
    cand = _resolve(**fc)
    assert cand.available is False
    assert cand.reason_code == "point_geometry_not_road_geometry"
    assert "point" in cand.message.lower()
    assert "lon/lat" in cand.message.lower() or "point coordinates" in cand.message.lower()
    assert cand.provenance["geometry_metadata_evidence"] == ["Point coordinate columns detected"]
    assert "Not sufficient for road segment line geometry." in str(
        cand.provenance["geometry_metadata_limitations"]
    )


# ── 5. join_key_only → unavailable ───────────────────────────────────


def test_join_key_only_candidate_unavailable():
    fc = {
        "file_path": "/tmp/roads_no_geo.csv",
        "geometry_metadata": _gm(
            geometry_type="join_key_only",
            road_geometry_available=False,
            join_key_columns={"link_id": "link_id", "road_id": "road_id"},
            confidence=0.40,
            evidence=["Join key columns detected"],
            limitations=["External geometry mapping required."],
        ),
    }
    cand = _resolve(**fc)
    assert cand.available is False
    assert cand.reason_code == "join_key_without_geometry"
    assert "join key" in cand.message.lower() or "link_id" in cand.message.lower()
    assert sorted(cand.join_keys) == ["link_id", "road_id"]


def test_join_key_only_single_column():
    fc = {
        "geometry_metadata": _gm(
            geometry_type="join_key_only",
            road_geometry_available=False,
            join_key_columns={"link_id": "link_id"},
            confidence=0.40,
        ),
    }
    cand = _resolve(**fc)
    assert cand.available is False
    assert cand.reason_code == "join_key_without_geometry"
    assert "link_id" in cand.join_keys


# ── 6. no geometry → unavailable ─────────────────────────────────────


def test_no_geometry_candidate_unavailable():
    fc = {
        "geometry_metadata": _gm(
            geometry_type="none",
            road_geometry_available=False,
            confidence=0.0,
            limitations=["No geometry columns detected."],
        ),
    }
    cand = _resolve(**fc)
    assert cand.available is False
    assert cand.reason_code == "missing_road_geometry"
    assert "No road geometry" in cand.message


def test_missing_geometry_metadata_candidate_unavailable():
    """File context without geometry_metadata key → unavailable."""
    fc = {"file_path": "/tmp/plain.csv"}
    cand = _resolve(**fc)
    assert cand.available is False
    assert cand.reason_code == "missing_road_geometry"


def test_empty_file_context_candidate_unavailable():
    """None file_context → unavailable."""
    from core.spatial_emission_resolver import resolve_spatial_emission_candidate
    cand = resolve_spatial_emission_candidate(file_context=None)
    assert cand.available is False
    assert cand.reason_code == "missing_road_geometry"


# ── 7. evidence/confidence preserved ─────────────────────────────────


def test_accepted_type_without_road_geometry_available_edge_case():
    """WKT type but road_geometry_available=False → road_geometry_unavailable."""
    fc = {
        "geometry_metadata": _gm(
            geometry_type="wkt",
            road_geometry_available=False,
            confidence=0.30,
            evidence=["Column named wkt but values unrecognized"],
        ),
    }
    cand = _resolve(**fc)
    assert cand.available is False
    assert cand.reason_code == "road_geometry_unavailable"
    assert "road_geometry_available=false" in cand.message.lower()


# ── 8. limitations preserved ─────────────────────────────────────────


def test_limitations_preserved_in_candidate():
    limitations = [
        "Only point coordinates found.",
        "External geometry mapping required for full road geometry.",
    ]
    fc = {
        "geometry_metadata": _gm(
            geometry_type="lonlat_point",
            point_geometry_available=True,
            road_geometry_available=False,
            limitations=limitations,
        ),
    }
    cand = _resolve(**fc)
    stored = cand.provenance.get("geometry_metadata_limitations") or []
    for lim in limitations:
        assert lim in stored


# ── 9. source_file_path preserved ────────────────────────────────────


def test_source_file_path_none_when_missing():
    fc = {"geometry_metadata": _gm(geometry_type="wkt", road_geometry_available=True)}
    cand = _resolve(**fc)
    assert cand.source_file_path is None


def test_emission_result_ref_none_when_not_provided():
    from core.spatial_emission_resolver import resolve_spatial_emission_candidate
    cand = resolve_spatial_emission_candidate(
        file_context={"geometry_metadata": _gm(geometry_type="wkt", road_geometry_available=True)},
    )
    assert cand.available is True
    assert cand.emission_result_ref is None


# ── 10. serialization roundtrip ──────────────────────────────────────


def test_candidate_serializes_to_dict():
    from core.spatial_emission_resolver import resolve_spatial_emission_candidate
    cand = resolve_spatial_emission_candidate(
        file_context={
            "file_path": "/tmp/test.csv",
            "geometry_metadata": _gm(
                geometry_type="wkt",
                road_geometry_available=True,
                geometry_columns=["wkt"],
                join_key_columns={"link_id": "link_id"},
                confidence=0.90,
                evidence=["ev1"],
                limitations=["lim1"],
            ),
        },
        emission_result_ref="macro_emission:baseline",
    )
    d = cand.to_dict()
    assert isinstance(d, dict)
    assert d["available"] is True
    assert d["reason_code"] == "spatial_emission_available"
    assert d["source_file_path"] == "/tmp/test.csv"
    assert d["emission_result_ref"] == "macro_emission:baseline"
    geom = d["geometry"]
    assert geom["geometry_type"] == "wkt"
    assert geom["geometry_columns"] == ["wkt"]
    assert geom["confidence"] == 0.90
    assert "ev1" in geom["evidence"]
    assert "lim1" in geom["limitations"]
    assert d["join_keys"] == ["link_id"]
    assert "resolver_version" in d["provenance"]


# ── 11. Does NOT invent geometry ─────────────────────────────────────


def test_no_geometry_invented_for_missing_metadata():
    """Even when the candidate is available, it carries only what was detected."""
    fc = {
        "geometry_metadata": _gm(
            geometry_type="wkt",
            road_geometry_available=True,
            geometry_columns=["wkt"],
            confidence=0.90,
        ),
    }
    cand = _resolve(**fc)
    # available=true but geometry_columns are exactly what was detected
    assert cand.geometry.geometry_columns == ["wkt"]
    assert cand.geometry.geometry_type == "wkt"
    # No fabricated data
    assert "invented" not in cand.message.lower()
    assert "default" not in cand.message.lower()
    assert "synthesized" not in cand.provenance.get("resolver_version", "")


# ── 12. Chinese geometry aliases flow through metadata ───────────────


def test_chinese_wkt_alias_flows_to_candidate():
    fc = {
        "geometry_metadata": _gm(
            geometry_type="wkt",
            road_geometry_available=True,
            geometry_columns=["几何"],
            confidence=0.90,
            evidence=["Column '几何' contains WKT geometry"],
        ),
    }
    cand = _resolve(**fc)
    assert cand.available is True
    assert "几何" in cand.geometry.geometry_columns
    assert "几何" in str(cand.provenance.get("geometry_metadata_evidence"))


def test_chinese_start_end_aliases_flow_to_candidate():
    fc = {
        "geometry_metadata": _gm(
            geometry_type="lonlat_linestring",
            road_geometry_available=True,
            line_geometry_constructible=True,
            coordinate_columns={
                "start_lon": "起点经度", "start_lat": "起点纬度",
                "end_lon": "终点经度", "end_lat": "终点纬度",
            },
            confidence=0.85,
        ),
    }
    cand = _resolve(**fc)
    assert cand.available is True
    assert cand.geometry.coordinate_columns["start_lon"] == "起点经度"


# ── 13. spatial_metadata type → available ────────────────────────────


def test_spatial_metadata_type_candidate_available():
    fc = {
        "geometry_metadata": _gm(
            geometry_type="spatial_metadata",
            road_geometry_available=True,
            confidence=0.95,
            evidence=["Shapefile metadata with LineString geometry"],
        ),
    }
    cand = _resolve(**fc)
    assert cand.available is True
    assert cand.reason_code == "spatial_emission_available"
    assert cand.geometry.geometry_type == "spatial_metadata"


# ── 14. Compatibility with Phase 7.3 check_road_geometry_from_metadata


def test_compatible_with_phase73_check():
    """Resolver result is consistent with check_road_geometry_from_metadata."""
    from core.tool_dependencies import check_road_geometry_from_metadata
    from core.spatial_emission_resolver import resolve_spatial_emission_candidate

    scenarios = [
        ("wkt", True),
        ("geojson", True),
        ("lonlat_linestring", True),
        ("spatial_metadata", True),
        ("lonlat_point", False),
        ("join_key_only", False),
        ("none", False),
    ]
    for geom_type, expected_available in scenarios:
        gm = {
            "geometry_type": geom_type,
            "road_geometry_available": geom_type not in ("lonlat_point", "join_key_only", "none"),
            "point_geometry_available": geom_type == "lonlat_point",
            "join_key_columns": {"link_id": "link_id"} if geom_type == "join_key_only" else {},
        }
        fc = {"geometry_metadata": gm}
        cand = resolve_spatial_emission_candidate(file_context=fc)
        check = check_road_geometry_from_metadata(gm)
        assert cand.available == check["satisfied"], (
            f"Mismatch for {geom_type}: resolver.available={cand.available}, "
            f"check.satisfied={check['satisfied']}"
        )
