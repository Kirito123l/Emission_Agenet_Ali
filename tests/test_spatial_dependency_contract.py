"""Targeted tests for Phase 7.3 — spatial dependency contracts.

Verifies:
- tool_contracts.yaml exposes geometry_requirements for calculate_dispersion
- requires_road_geometry / is_acceptable_road_geometry_type work correctly
- WKT/GeoJSON/linestring geometry_metadata satisfies road geometry precondition
- lon/lat point-only, join_key_only, none do NOT satisfy precondition
- diagnostic reason codes are specific and actionable
- existing macro -> dispersion relation preserved in TOOL_GRAPH
- geometry_metadata detected by Phase 7.2 is wired into readiness
- existing core tests still pass
"""

from __future__ import annotations

import pytest

from config import get_config, reset_config
from core.task_state import GeometryMetadata


@pytest.fixture(autouse=True)
def _restore_config():
    reset_config()
    yield
    reset_config()


# ── 1. Contract loads with geometry_requirements ────────────────────


def test_tool_contracts_load_with_geometry_requirements():
    """tool_contracts.yaml loads and calculate_dispersion has geometry_requirements."""
    from tools.contract_loader import get_tool_contract_registry
    reg = get_tool_contract_registry()
    contract = reg._contracts.get("calculate_dispersion", {})
    assert "geometry_requirements" in contract
    gr = contract["geometry_requirements"]
    assert gr["requires_road_geometry"] is True
    assert "acceptable_geometry_types" in gr
    assert "rejected_geometry_types" in gr
    assert gr["missing_diagnostic_reason_code"] == "missing_road_geometry"


def test_macro_contract_still_loads():
    """calculate_macro_emission contract still loads without geometry_requirements."""
    from tools.contract_loader import get_tool_contract_registry
    reg = get_tool_contract_registry()
    macro = reg._contracts.get("calculate_macro_emission", {})
    deps = macro.get("dependencies", {})
    assert "emission" in deps.get("provides", [])
    # Macro does NOT require geometry (no geometry_requirements block)
    assert "geometry_requirements" not in macro or not macro.get("geometry_requirements", {}).get(
        "requires_road_geometry"
    )


# ── 2. calculate_dispersion exposes geometry requirement ─────────────


def test_calculate_dispersion_requires_road_geometry():
    """requires_road_geometry returns True for calculate_dispersion."""
    from core.tool_dependencies import requires_road_geometry
    assert requires_road_geometry("calculate_dispersion") is True


def test_calculate_macro_does_not_require_road_geometry():
    """requires_road_geometry returns False for calculate_macro_emission."""
    from core.tool_dependencies import requires_road_geometry
    assert requires_road_geometry("calculate_macro_emission") is False


def test_unknown_tool_requires_road_geometry_is_false():
    """Non-existent tool returns False."""
    from core.tool_dependencies import requires_road_geometry
    assert requires_road_geometry("some_fake_tool") is False


# ── 3. Macro emission dependency preserved ──────────────────────────


def test_macro_dispersion_dependency_preserved():
    """TOOL_GRAPH still has emission -> dispersion relationship."""
    from core.tool_dependencies import TOOL_GRAPH, normalize_tokens
    macro_provides = normalize_tokens(TOOL_GRAPH.get("calculate_macro_emission", {}).get("provides", []))
    dispersion_requires = normalize_tokens(TOOL_GRAPH.get("calculate_dispersion", {}).get("requires", []))
    assert "emission" in macro_provides
    assert "emission" in dispersion_requires


# ── 4. WKT geometry_metadata satisfies precondition ─────────────────


def test_wkt_road_geometry_satisfies_precondition():
    """geometry_metadata with wkt + road_geometry_available → satisfied."""
    from core.tool_dependencies import check_road_geometry_from_metadata
    gm = {"geometry_type": "wkt", "road_geometry_available": True}
    result = check_road_geometry_from_metadata(gm)
    assert result["satisfied"] is True
    assert result["reason_code"] == "road_geometry_available"
    assert result["geometry_type"] == "wkt"


# ── 5. GeoJSON geometry satisfies precondition ──────────────────────


def test_geojson_road_geometry_satisfies_precondition():
    """geometry_metadata with geojson + road_geometry_available → satisfied."""
    from core.tool_dependencies import check_road_geometry_from_metadata
    gm = {"geometry_type": "geojson", "road_geometry_available": True}
    result = check_road_geometry_from_metadata(gm)
    assert result["satisfied"] is True
    assert result["reason_code"] == "road_geometry_available"


# ── 6. start/end coordinate LineString satisfies precondition ───────


def test_lonlat_linestring_satisfies_precondition():
    """geometry_metadata with lonlat_linestring + road_geometry_available → satisfied."""
    from core.tool_dependencies import check_road_geometry_from_metadata
    gm = {
        "geometry_type": "lonlat_linestring",
        "road_geometry_available": True,
        "line_geometry_constructible": True,
    }
    result = check_road_geometry_from_metadata(gm)
    assert result["satisfied"] is True
    assert result["reason_code"] == "road_geometry_available"


def test_spatial_metadata_satisfies_precondition():
    """geometry_metadata with spatial_metadata + road_geometry_available → satisfied."""
    from core.tool_dependencies import check_road_geometry_from_metadata
    gm = {"geometry_type": "spatial_metadata", "road_geometry_available": True}
    result = check_road_geometry_from_metadata(gm)
    assert result["satisfied"] is True


# ── 7. lon/lat point-only does NOT satisfy ───────────────────────────


def test_lonlat_point_does_not_satisfy_precondition():
    """geometry_metadata with lonlat_point → not satisfied, point-only diagnostic."""
    from core.tool_dependencies import check_road_geometry_from_metadata
    gm = {
        "geometry_type": "lonlat_point",
        "point_geometry_available": True,
        "road_geometry_available": False,
    }
    result = check_road_geometry_from_metadata(gm)
    assert result["satisfied"] is False
    assert result["reason_code"] == "missing_road_geometry_point_only"
    assert "point" in result["message"].lower()


# ── 8. join_key_only does NOT satisfy ───────────────────────────────


def test_join_key_only_does_not_satisfy_precondition():
    """geometry_metadata with join_key_only → not satisfied, targeted diagnostic."""
    from core.tool_dependencies import check_road_geometry_from_metadata
    gm = {
        "geometry_type": "join_key_only",
        "join_key_columns": {"link_id": "link_id", "road_id": "road_id"},
        "road_geometry_available": False,
    }
    result = check_road_geometry_from_metadata(gm)
    assert result["satisfied"] is False
    assert result["reason_code"] == "missing_road_geometry_join_key_only"
    assert "link_id" in str(result["join_key_columns"])
    assert "join key" in result["message"].lower() or "link_id" in result["message"]


# ── 9. No geometry_metadata does NOT satisfy ────────────────────────


def test_no_geometry_metadata_does_not_satisfy_precondition():
    """Empty geometry_metadata → not satisfied, missing_road_geometry."""
    from core.tool_dependencies import check_road_geometry_from_metadata
    result = check_road_geometry_from_metadata({})
    assert result["satisfied"] is False
    assert result["reason_code"] == "missing_road_geometry"


def test_none_geometry_type_does_not_satisfy():
    """geometry_type='none' → not satisfied."""
    from core.tool_dependencies import check_road_geometry_from_metadata
    gm = {"geometry_type": "none", "road_geometry_available": False}
    result = check_road_geometry_from_metadata(gm)
    assert result["satisfied"] is False
    assert result["reason_code"] == "missing_road_geometry"


# ── 10. diagnostic reason codes are specific ────────────────────────


def test_diagnostic_reason_codes_are_distinct():
    """Each failure mode has a distinct reason_code."""
    from core.tool_dependencies import check_road_geometry_from_metadata
    codes = set()
    for gm, _label in [
        ({"geometry_type": "lonlat_point", "point_geometry_available": True}, "point"),
        ({"geometry_type": "join_key_only", "join_key_columns": {"id": "c"}}, "join_key"),
        ({}, "empty"),
        ({"geometry_type": "none"}, "none"),
    ]:
        result = check_road_geometry_from_metadata(gm)
        assert result["satisfied"] is False
        codes.add(result["reason_code"])
    assert len(codes) >= 3  # point_only, join_key_only, missing_road_geometry


def test_tool_without_road_geometry_requirement_is_always_satisfied():
    """Tools without geometry_requirements block are always satisfied."""
    from core.tool_dependencies import check_road_geometry_from_metadata
    result = check_road_geometry_from_metadata(
        {"geometry_type": "none"}, tool_name="calculate_macro_emission"
    )
    assert result["satisfied"] is True
    assert result["reason_code"] == "no_road_geometry_requirement"


# ── 11. GeometryMetadata dataclass roundtrip with contract check ────


def test_geometry_metadata_from_phase7_2_wires_into_check():
    """Full roundtrip: GeometryMetadata → to_dict → check_road_geometry_from_metadata."""
    from core.tool_dependencies import check_road_geometry_from_metadata

    # Simulate a WKT detection result from Phase 7.2
    gm = GeometryMetadata(
        geometry_available=True,
        road_geometry_available=True,
        geometry_type="wkt",
        geometry_columns=["wkt"],
        join_key_columns={"link_id": "link_id"},
        confidence=0.90,
        evidence=["WKT values confirmed"],
        limitations=[],
    )
    result = check_road_geometry_from_metadata(gm.to_dict())
    assert result["satisfied"] is True

    # Simulate a join_key_only result
    gm2 = GeometryMetadata(
        geometry_available=False,
        geometry_type="join_key_only",
        join_key_columns={"link_id": "link_id"},
        confidence=0.40,
        evidence=["Join key columns detected"],
        limitations=["External geometry mapping required"],
    )
    result2 = check_road_geometry_from_metadata(gm2.to_dict())
    assert result2["satisfied"] is False
    assert result2["reason_code"] == "missing_road_geometry_join_key_only"


# ── 12. is_acceptable/is_rejected classification ────────────────────


def test_acceptable_types_are_not_rejected():
    """Every acceptable type is NOT rejected."""
    from core.tool_dependencies import is_acceptable_road_geometry_type, is_rejected_road_geometry_type
    for gt in ["wkt", "geojson", "lonlat_linestring", "spatial_metadata"]:
        assert is_acceptable_road_geometry_type(gt) is True
        assert is_rejected_road_geometry_type(gt) is False


def test_rejected_types_are_not_acceptable():
    """Every rejected type is NOT acceptable."""
    from core.tool_dependencies import is_acceptable_road_geometry_type, is_rejected_road_geometry_type
    for gt in ["lonlat_point", "join_key_only", "none"]:
        assert is_rejected_road_geometry_type(gt) is True
        assert is_acceptable_road_geometry_type(gt) is False
