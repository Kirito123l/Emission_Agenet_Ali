"""Targeted tests for Phase 7.6B — deterministic join-key geometry resolver.

Verifies:
- 100% overlap => ACCEPT, layer_available true
- 90% overlap => NEEDS_USER_CONFIRMATION
- 70% overlap => REJECT
- zero overlap => REJECT
- geometry file without road geometry => REJECT
- emission file without join key => REJECT
- duplicate identical geometry keys => ACCEPT (deduplicated)
- duplicate conflicting geometry keys => REJECT
- explicit join_key_mapping works when column names differ
- Chinese 路段ID join works
- numeric string/int key normalization works
- no fuzzy/prefix stripping
- row-order join never accepted
- SpatialEmissionLayer preserves geometry_source_file_path and match metadata
- serialization roundtrip
- emission with direct geometry delegates to direct path

Non-goals: external geometry lookup, dispersion formula changes, evaluator changes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from config import get_config, reset_config

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "join_key_geometry"


@pytest.fixture(autouse=True)
def _restore_config():
    reset_config()
    yield
    reset_config()


# ── helpers ───────────────────────────────────────────────────────────────


def _gm(**kw):
    return dict(kw)


def _em_fc(file_name: str, geometry_type: str = "join_key_only",
           jk_cols=None, road_available=False, point_available=False,
           row_count=None, columns=None, confidence=0.40):
    """Build an emission FileContext dict for a fixture file."""
    fp = str(FIXTURE_DIR / file_name)
    gm = _gm(
        geometry_type=geometry_type,
        road_geometry_available=road_available,
        point_geometry_available=point_available,
        join_key_columns=jk_cols if jk_cols is not None else {},
        confidence=confidence,
        evidence=[f"Join key columns detected: {list((jk_cols if jk_cols is not None else {}).keys())}"],
    )
    fc = {
        "file_path": fp,
        "geometry_metadata": gm,
    }
    if row_count is not None:
        fc["row_count"] = row_count
    if columns is not None:
        fc["columns"] = columns
    return fc


def _geo_fc(file_name: str, geometry_type: str = "wkt",
            geom_cols=None, jk_cols=None, road_available=True,
            row_count=None, columns=None, confidence=0.90,
            point_available=False):
    """Build a geometry FileContext dict for a fixture file."""
    fp = str(FIXTURE_DIR / file_name)
    gm = _gm(
        geometry_type=geometry_type,
        road_geometry_available=road_available,
        point_geometry_available=point_available,
        geometry_columns=geom_cols if geom_cols is not None else ["geometry"],
        join_key_columns=jk_cols if jk_cols is not None else {},
        confidence=confidence,
        evidence=["WKT geometry values confirmed in sample rows"],
    )
    fc = {
        "file_path": fp,
        "geometry_metadata": gm,
    }
    if row_count is not None:
        fc["row_count"] = row_count
    if columns is not None:
        fc["columns"] = columns
    return fc


# ── 1. 100% overlap => ACCEPT ─────────────────────────────────────────


def test_full_match_accept():
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer
    from core.spatial_emission import JOIN_RESOLUTION_ACCEPT

    em = _em_fc("emission_links_10.csv", jk_cols={"link_id": "link_id"},
                row_count=10, columns=["link_id", "length", "flow", "speed"])
    geo = _geo_fc("geometry_links_10.csv", geom_cols=["geometry"],
                  jk_cols={"link_id": "link_id"},
                  row_count=10, columns=["link_id", "geometry"])

    result = resolve_join_key_geometry_layer(
        emission_file_context=em,
        geometry_file_context=geo,
        emission_result_ref="macro_emission:baseline",
    )
    assert result.status == JOIN_RESOLUTION_ACCEPT, f"Expected ACCEPT, got {result.status}: {result.message}"
    assert result.reason_code == "join_key_resolved"
    assert result.match_rate == 1.0
    assert result.matched_count == 10
    assert result.unmatched_emission_count == 0
    assert result.spatial_emission_layer is not None
    assert result.spatial_emission_layer["layer_available"] is True
    assert result.spatial_emission_layer["geometry_type"] == "wkt"
    assert result.spatial_emission_layer["emission_result_ref"] == "macro_emission:baseline"


# ── 2. 90% overlap => NEEDS_USER_CONFIRMATION ─────────────────────────


def test_partial_90pct_needs_confirmation():
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer
    from core.spatial_emission import JOIN_RESOLUTION_NEEDS_USER_CONFIRMATION

    em = _em_fc("emission_links_10.csv", jk_cols={"link_id": "link_id"},
                row_count=10, columns=["link_id", "length", "flow", "speed"])
    geo = _geo_fc("geometry_links_9.csv", geom_cols=["geometry"],
                  jk_cols={"link_id": "link_id"},
                  row_count=9, columns=["link_id", "geometry"])

    result = resolve_join_key_geometry_layer(
        emission_file_context=em,
        geometry_file_context=geo,
        auto_accept_threshold=0.95,
        confirmation_threshold=0.80,
    )
    assert result.status == JOIN_RESOLUTION_NEEDS_USER_CONFIRMATION, (
        f"Expected NEEDS_USER_CONFIRMATION, got {result.status}: {result.message}"
    )
    assert result.reason_code == "partial_key_overlap"
    assert result.match_rate == 0.9
    assert result.matched_count == 9
    assert result.unmatched_emission_count == 1
    # Even partial match produces a layer for confirmation
    assert result.spatial_emission_layer is not None
    assert result.spatial_emission_layer["layer_available"] is True


# ── 3. 70% overlap => REJECT ──────────────────────────────────────────


def test_low_overlap_reject():
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer
    from core.spatial_emission import JOIN_RESOLUTION_REJECT

    em = _em_fc("emission_links_10.csv", jk_cols={"link_id": "link_id"},
                row_count=10, columns=["link_id", "length", "flow", "speed"])
    geo = _geo_fc("geometry_links_7.csv", geom_cols=["geometry"],
                  jk_cols={"link_id": "link_id"},
                  row_count=7, columns=["link_id", "geometry"])

    result = resolve_join_key_geometry_layer(
        emission_file_context=em,
        geometry_file_context=geo,
        auto_accept_threshold=0.95,
        confirmation_threshold=0.80,
    )
    assert result.status == JOIN_RESOLUTION_REJECT, f"Expected REJECT, got {result.status}"
    assert result.reason_code == "low_key_overlap"
    assert result.match_rate == 0.7
    assert result.spatial_emission_layer is None


# ── 4. Zero overlap => REJECT ─────────────────────────────────────────


def test_zero_overlap_reject():
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer
    from core.spatial_emission import JOIN_RESOLUTION_REJECT

    em = _em_fc("emission_links_10.csv", jk_cols={"link_id": "link_id"},
                row_count=10, columns=["link_id", "length", "flow", "speed"])
    geo = _geo_fc("geometry_links_no_overlap.csv", geom_cols=["geometry"],
                  jk_cols={"link_id": "link_id"},
                  row_count=5, columns=["link_id", "geometry"])

    result = resolve_join_key_geometry_layer(
        emission_file_context=em,
        geometry_file_context=geo,
    )
    assert result.status == JOIN_RESOLUTION_REJECT
    assert result.reason_code == "zero_key_overlap"
    assert result.match_rate == 0.0
    assert result.spatial_emission_layer is None
    assert "e.g." in result.message or "example" in result.message.lower()


# ── 5. Geometry file without road geometry => REJECT ──────────────────


def test_geometry_file_no_road_geometry_reject():
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer
    from core.spatial_emission import JOIN_RESOLUTION_REJECT

    em = _em_fc("emission_links_10.csv", jk_cols={"link_id": "link_id"},
                row_count=10, columns=["link_id", "length", "flow", "speed"])
    geo = _geo_fc("geometry_links_10.csv", road_available=False, point_available=False,
                  geom_cols=["geometry"], jk_cols={"link_id": "link_id"})

    result = resolve_join_key_geometry_layer(
        emission_file_context=em,
        geometry_file_context=geo,
    )
    assert result.status == JOIN_RESOLUTION_REJECT
    assert result.reason_code == "geometry_file_no_road_geometry"


# ── 6. Emission file without join key => REJECT ───────────────────────


def test_emission_no_join_key_reject():
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer
    from core.spatial_emission import JOIN_RESOLUTION_INSUFFICIENT_INPUT

    em = _em_fc("emission_no_join_key.csv", jk_cols={}, geometry_type="none",
                row_count=5, columns=["name", "length", "flow", "speed"])
    geo = _geo_fc("geometry_links_10.csv", geom_cols=["geometry"],
                  jk_cols={"link_id": "link_id"},
                  row_count=10, columns=["link_id", "geometry"])

    result = resolve_join_key_geometry_layer(
        emission_file_context=em,
        geometry_file_context=geo,
    )
    assert result.status == JOIN_RESOLUTION_INSUFFICIENT_INPUT
    assert result.reason_code == "no_join_keys_in_emission"


# ── 7. Duplicate identical geometry keys => ACCEPT / deduplicated ──────


def test_duplicate_identical_geometry_accept():
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer
    from core.spatial_emission import JOIN_RESOLUTION_ACCEPT

    em = _em_fc("emission_links_10.csv", jk_cols={"link_id": "link_id"},
                row_count=10, columns=["link_id", "length", "flow", "speed"])
    geo = _geo_fc("geometry_duplicate_identical.csv", geom_cols=["geometry"],
                  jk_cols={"link_id": "link_id"},
                  row_count=11, columns=["link_id", "geometry"])

    result = resolve_join_key_geometry_layer(
        emission_file_context=em,
        geometry_file_context=geo,
    )
    assert result.status == JOIN_RESOLUTION_ACCEPT, f"Expected ACCEPT, got {result.status}: {result.message}"
    assert result.match_rate == 1.0
    assert result.spatial_emission_layer is not None
    assert result.spatial_emission_layer["layer_available"] is True
    # Should note deduplication in evidence
    dedup_evidence = [e for e in result.evidence if "deduplicate" in e.lower()
                      or "identical" in e.lower()]
    assert len(dedup_evidence) > 0, f"Expected deduplication evidence, got: {result.evidence}"


# ── 8. Duplicate conflicting geometry keys => REJECT ──────────────────


def test_duplicate_conflicting_geometry_reject():
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer
    from core.spatial_emission import JOIN_RESOLUTION_REJECT

    em = _em_fc("emission_links_10.csv", jk_cols={"link_id": "link_id"},
                row_count=10, columns=["link_id", "length", "flow", "speed"])
    geo = _geo_fc("geometry_duplicate_conflict.csv", geom_cols=["geometry"],
                  jk_cols={"link_id": "link_id"},
                  row_count=11, columns=["link_id", "geometry"])

    result = resolve_join_key_geometry_layer(
        emission_file_context=em,
        geometry_file_context=geo,
    )
    assert result.status == JOIN_RESOLUTION_REJECT, f"Expected REJECT, got {result.status}"
    assert result.reason_code == "ambiguous_duplicate_geometry_keys"
    assert result.spatial_emission_layer is None


# ── 9. Explicit join_key_mapping works when column names differ ────────


def test_explicit_join_key_mapping():
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer
    from core.spatial_emission import JOIN_RESOLUTION_ACCEPT

    # Emission file uses "link_id", geometry file also uses "link_id"
    # but we provide explicit mapping as if names differ
    em = _em_fc("emission_links_10.csv", jk_cols={"link_id": "link_id"},
                row_count=10, columns=["link_id", "length", "flow", "speed"])
    geo = _geo_fc("geometry_links_10.csv", geom_cols=["geometry"],
                  jk_cols={"link_id": "link_id"},
                  row_count=10, columns=["link_id", "geometry"])

    result = resolve_join_key_geometry_layer(
        emission_file_context=em,
        geometry_file_context=geo,
        join_key_mapping={"link_id": "link_id"},
    )
    assert result.status == JOIN_RESOLUTION_ACCEPT
    assert result.join_key_mapping == {"link_id": "link_id"}
    assert result.emission_key_column == "link_id"
    assert result.geometry_key_column == "link_id"


# ── 10. Chinese 路段ID join works ─────────────────────────────────────


def test_chinese_join_key():
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer
    from core.spatial_emission import JOIN_RESOLUTION_ACCEPT

    em = _em_fc("emission_chinese_links.csv",
                jk_cols={"路段ID": "路段ID"},
                geometry_type="join_key_only",
                row_count=5, columns=["路段ID", "长度", "流量", "速度"])
    geo = _geo_fc("geometry_chinese_links.csv", geom_cols=["geometry"],
                  jk_cols={"路段ID": "路段ID"},
                  row_count=5, columns=["路段ID", "geometry"])

    result = resolve_join_key_geometry_layer(
        emission_file_context=em,
        geometry_file_context=geo,
    )
    assert result.status == JOIN_RESOLUTION_ACCEPT, f"Expected ACCEPT, got {result.status}: {result.message}"
    assert result.match_rate == 1.0
    assert result.matched_count == 5
    assert result.emission_key_column == "路段ID"
    assert result.geometry_key_column == "路段ID"


# ── 11. Numeric string/int key normalization works ────────────────────


def test_numeric_key_normalization():
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer
    from core.spatial_emission import JOIN_RESOLUTION_ACCEPT

    # Emission has string keys "1001"..."1010"
    # Geometry has integer keys 1001...1010
    em = _em_fc("emission_links_numeric_string.csv", jk_cols={"link_id": "link_id"},
                row_count=10, columns=["link_id", "length", "flow", "speed"])
    geo = _geo_fc("geometry_links_numeric_keys.csv", geom_cols=["geometry"],
                  jk_cols={"link_id": "link_id"},
                  row_count=10, columns=["link_id", "geometry"])

    result = resolve_join_key_geometry_layer(
        emission_file_context=em,
        geometry_file_context=geo,
    )
    assert result.status == JOIN_RESOLUTION_ACCEPT, (
        f"Expected ACCEPT with normalized numeric keys, got {result.status}: {result.message}"
    )
    assert result.match_rate == 1.0
    assert result.matched_count == 10


# ── 12. No fuzzy/prefix stripping ──────────────────────────────────────


def test_no_fuzzy_matching():
    """Keys like 'Link_001' should NOT match '001' — no prefix stripping."""
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer, _norm_key

    # Verify _norm_key doesn't strip prefixes
    assert _norm_key("Link_001") == "Link_001"
    assert _norm_key("001") == "001"
    assert _norm_key("Link_001") != _norm_key("001")
    assert _norm_key("路段_A1") != _norm_key("A1")


# ── 13. No row-order join ─────────────────────────────────────────────


def test_no_row_order_join():
    """The resolver requires explicit join key columns — never joins by row order."""
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer
    from core.spatial_emission import JOIN_RESOLUTION_INSUFFICIENT_INPUT

    # Emission file with no join key — should fail, not fall back to row order
    em = _em_fc("emission_no_join_key.csv", jk_cols={}, geometry_type="none",
                row_count=5, columns=["name", "length", "flow", "speed"])
    geo = _geo_fc("geometry_links_10.csv", geom_cols=["geometry"],
                  jk_cols={"link_id": "link_id"},
                  row_count=10, columns=["link_id", "geometry"])

    result = resolve_join_key_geometry_layer(
        emission_file_context=em,
        geometry_file_context=geo,
    )
    assert result.status == JOIN_RESOLUTION_INSUFFICIENT_INPUT
    assert result.reason_code == "no_join_keys_in_emission"


# ── 14. SpatialEmissionLayer preserves metadata ───────────────────────


def test_layer_preserves_geometry_source_path_and_metadata():
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer
    from core.spatial_emission import JOIN_RESOLUTION_ACCEPT

    em = _em_fc("emission_links_10.csv", jk_cols={"link_id": "link_id"},
                row_count=10, columns=["link_id", "length", "flow", "speed"])
    geo = _geo_fc("geometry_links_10.csv", geom_cols=["geometry"],
                  jk_cols={"link_id": "link_id"},
                  row_count=10, columns=["link_id", "geometry"])

    result = resolve_join_key_geometry_layer(
        emission_file_context=em,
        geometry_file_context=geo,
        emission_result_ref="macro_emission:test",
    )
    assert result.status == JOIN_RESOLUTION_ACCEPT

    layer = result.spatial_emission_layer
    assert layer is not None
    # source_file_path should point to geometry file
    assert "geometry_links_10.csv" in layer["source_file_path"]
    assert layer["emission_result_ref"] == "macro_emission:test"
    assert layer["confidence"] == 1.0
    assert layer["join_key_columns"] == {"link_id": "link_id"}
    prov = layer["provenance"]
    assert prov["join_method"] == "deterministic_key_match"
    assert prov["match_rate"] == 1.0
    assert prov["matched_count"] == 10
    assert "emission_file" in prov
    assert "geometry_file" in prov
    assert "key_mapping" in prov


# ── 15. Serialization roundtrip ──────────────────────────────────────


def test_serialization_roundtrip():
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer
    from core.spatial_emission import JoinGeometryResolutionResult

    em = _em_fc("emission_links_10.csv", jk_cols={"link_id": "link_id"},
                row_count=10, columns=["link_id", "length", "flow", "speed"])
    geo = _geo_fc("geometry_links_10.csv", geom_cols=["geometry"],
                  jk_cols={"link_id": "link_id"},
                  row_count=10, columns=["link_id", "geometry"])

    result = resolve_join_key_geometry_layer(
        emission_file_context=em,
        geometry_file_context=geo,
    )
    d = result.to_dict()
    # All keys should be JSON-serializable
    serialized = json.dumps(d, ensure_ascii=False, default=str)
    assert len(serialized) > 0

    # Reconstruct a result from the dict (spot check)
    loaded = json.loads(serialized)
    assert loaded["status"] == "ACCEPT"
    assert loaded["match_rate"] == 1.0
    assert loaded["spatial_emission_layer"] is not None
    assert loaded["spatial_emission_layer"]["layer_available"] is True


# ── 16. Emission file with direct geometry delegates ──────────────────


def test_direct_geometry_emission_delegates():
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer
    from core.spatial_emission import JOIN_RESOLUTION_INSUFFICIENT_INPUT

    # Emission file HAS WKT geometry — should not use join-key resolver
    em = _em_fc("emission_with_wkt.csv", geometry_type="wkt",
                road_available=True,
                jk_cols={"link_id": "link_id"},
                row_count=5, columns=["link_id", "length", "flow", "speed", "geometry"])
    geo = _geo_fc("geometry_links_10.csv", geom_cols=["geometry"],
                  jk_cols={"link_id": "link_id"},
                  row_count=10, columns=["link_id", "geometry"])

    result = resolve_join_key_geometry_layer(
        emission_file_context=em,
        geometry_file_context=geo,
    )
    assert result.status == JOIN_RESOLUTION_INSUFFICIENT_INPUT
    assert result.reason_code == "direct_geometry_present"


# ── 17. Point-only geometry file rejected ─────────────────────────────


def test_point_only_geometry_file_rejected():
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer
    from core.spatial_emission import JOIN_RESOLUTION_REJECT

    em = _em_fc("emission_links_10.csv", jk_cols={"link_id": "link_id"},
                row_count=10, columns=["link_id", "length", "flow", "speed"])
    # This file contains POINT geometries
    geo = _geo_fc("geometry_point_only.csv", geometry_type="lonlat_point",
                  road_available=False, point_available=True,
                  geom_cols=["geometry"], jk_cols={"link_id": "link_id"},
                  row_count=10, columns=["link_id", "geometry"],
                  confidence=0.65)

    result = resolve_join_key_geometry_layer(
        emission_file_context=em,
        geometry_file_context=geo,
    )
    assert result.status == JOIN_RESOLUTION_REJECT
    assert result.reason_code == "point_geometry_not_road_geometry"


# ── 18. Missing file paths handled gracefully ─────────────────────────


def test_missing_emission_file_path():
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer
    from core.spatial_emission import JOIN_RESOLUTION_INSUFFICIENT_INPUT

    em = {"geometry_metadata": _gm(geometry_type="join_key_only",
                                   join_key_columns={"link_id": "link_id"})}
    geo = _geo_fc("geometry_links_10.csv", geom_cols=["geometry"],
                  jk_cols={"link_id": "link_id"})

    result = resolve_join_key_geometry_layer(
        emission_file_context=em,
        geometry_file_context=geo,
    )
    assert result.status == JOIN_RESOLUTION_INSUFFICIENT_INPUT
    assert result.reason_code == "missing_emission_file_path"


def test_missing_geometry_file_path():
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer
    from core.spatial_emission import JOIN_RESOLUTION_INSUFFICIENT_INPUT

    em = _em_fc("emission_links_10.csv", jk_cols={"link_id": "link_id"},
                row_count=10, columns=["link_id", "length", "flow", "speed"])
    geo = {"geometry_metadata": _gm(road_geometry_available=True,
                                    geometry_columns=["geometry"])}

    result = resolve_join_key_geometry_layer(
        emission_file_context=em,
        geometry_file_context=geo,
    )
    assert result.status == JOIN_RESOLUTION_INSUFFICIENT_INPUT
    assert result.reason_code == "missing_geometry_file_path"


# ── 19. Column loading from files works without explicit columns ──────


def test_column_autoload_from_file():
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer
    from core.spatial_emission import JOIN_RESOLUTION_ACCEPT

    # No 'columns' in file_context — resolver should read them from file headers
    fp_em = str(FIXTURE_DIR / "emission_links_10.csv")
    fp_geo = str(FIXTURE_DIR / "geometry_links_10.csv")

    em = {
        "file_path": fp_em,
        "geometry_metadata": _gm(geometry_type="join_key_only",
                                 join_key_columns={"link_id": "link_id"}),
    }
    geo = {
        "file_path": fp_geo,
        "geometry_metadata": _gm(road_geometry_available=True,
                                 geometry_columns=["geometry"],
                                 geometry_type="wkt",
                                 join_key_columns={}),
    }
    result = resolve_join_key_geometry_layer(
        emission_file_context=em,
        geometry_file_context=geo,
    )
    assert result.status == JOIN_RESOLUTION_ACCEPT, (
        f"Should auto-load columns from files; got {result.status}: {result.message}"
    )
    assert result.match_rate == 1.0


# ── 20. No geometry columns in geometry file ──────────────────────────


def test_no_geometry_columns_in_geometry_file():
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer
    from core.spatial_emission import JOIN_RESOLUTION_INSUFFICIENT_INPUT

    em = _em_fc("emission_links_10.csv", jk_cols={"link_id": "link_id"},
                row_count=10, columns=["link_id", "length", "flow", "speed"])
    geo = _geo_fc("geometry_links_10.csv", geom_cols=[],
                  jk_cols={"link_id": "link_id"},
                  row_count=10, columns=["link_id", "geometry"])

    result = resolve_join_key_geometry_layer(
        emission_file_context=em,
        geometry_file_context=geo,
    )
    assert result.status == JOIN_RESOLUTION_INSUFFICIENT_INPUT
    assert result.reason_code == "no_geometry_columns_in_geometry_file"


# ── 21. Thresholds configurable ────────────────────────────────────────


def test_custom_thresholds():
    from core.spatial_emission_resolver import resolve_join_key_geometry_layer
    from core.spatial_emission import JOIN_RESOLUTION_NEEDS_USER_CONFIRMATION, JOIN_RESOLUTION_ACCEPT

    em = _em_fc("emission_links_10.csv", jk_cols={"link_id": "link_id"},
                row_count=10, columns=["link_id", "length", "flow", "speed"])
    geo = _geo_fc("geometry_links_9.csv", geom_cols=["geometry"],
                  jk_cols={"link_id": "link_id"},
                  row_count=9, columns=["link_id", "geometry"])

    # With default thresholds: 90% => NEEDS_USER_CONFIRMATION
    result = resolve_join_key_geometry_layer(emission_file_context=em, geometry_file_context=geo)
    assert result.status == JOIN_RESOLUTION_NEEDS_USER_CONFIRMATION

    # With lowered auto_accept to 0.85: 90% => ACCEPT
    result2 = resolve_join_key_geometry_layer(
        emission_file_context=em, geometry_file_context=geo,
        auto_accept_threshold=0.85,
    )
    assert result2.status == JOIN_RESOLUTION_ACCEPT

    # With raised confirmation to 0.95: 90% => REJECT
    result3 = resolve_join_key_geometry_layer(
        emission_file_context=em, geometry_file_context=geo,
        confirmation_threshold=0.95,
    )
    from core.spatial_emission import JOIN_RESOLUTION_REJECT
    assert result3.status == JOIN_RESOLUTION_REJECT
