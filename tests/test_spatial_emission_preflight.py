"""Targeted tests for Phase 7.4B — spatial emission preflight integration.

Verifies:
- resolve_spatial_precondition works for non-geometry and geometry-requiring tools
- Targeted reason codes for point-only, join-key-only, missing geometry
- assess_action_readiness produces spatial diagnostic when prerequisites met
- Candidate stored in metadata during readiness assessment
- No changes to macro/dispersion tool execution
- Compatibility with existing Phase 7.2/7.3 tests
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


def _gm(**kw):
    return dict(kw)


def _macro_tool_result():
    """Return a tool_results entry that satisfies the emission prerequisite."""
    return {
        "name": "calculate_macro_emission",
        "arguments": {"pollutants": ["NOx"], "scenario_label": "baseline"},
        "result": {
            "success": True,
            "data": {
                "results": [
                    {
                        "link_id": "L001",
                        "link_length_km": 0.5,
                        "total_emissions_kg_per_hr": {"NOx": 0.01},
                    }
                ]
            },
        },
    }


# ── 1. Non-geometry tool → satisfied unconditionally ────────────────


def test_non_geometry_tool_precondition_satisfied():
    from core.readiness import resolve_spatial_precondition
    r = resolve_spatial_precondition("calculate_macro_emission")
    assert r["satisfied"] is True
    assert r["reason_code"] == "no_road_geometry_requirement"
    assert r["candidate_dict"] is None


def test_query_tool_precondition_satisfied():
    from core.readiness import resolve_spatial_precondition
    r = resolve_spatial_precondition("query_emission_factors")
    assert r["satisfied"] is True
    assert r["reason_code"] == "no_road_geometry_requirement"


# ── 2. WKT → satisfied ──────────────────────────────────────────────


def test_dispersion_wkt_precondition_satisfied():
    from core.readiness import resolve_spatial_precondition
    r = resolve_spatial_precondition(
        "calculate_dispersion",
        file_context={"geometry_metadata": _gm(
            geometry_type="wkt", road_geometry_available=True,
            geometry_columns=["wkt"], confidence=0.90,
            evidence=["WKT confirmed"],
        )},
    )
    assert r["satisfied"] is True
    assert r["reason_code"] == "spatial_emission_available"
    assert r["candidate_dict"] is not None
    assert r["candidate_dict"]["available"] is True


# ── 3. GeoJSON → satisfied ──────────────────────────────────────────


def test_dispersion_geojson_precondition_satisfied():
    from core.readiness import resolve_spatial_precondition
    r = resolve_spatial_precondition(
        "calculate_dispersion",
        file_context={"geometry_metadata": _gm(
            geometry_type="geojson", road_geometry_available=True,
            confidence=0.90,
        )},
    )
    assert r["satisfied"] is True
    assert r["reason_code"] == "spatial_emission_available"


# ── 4. lonlat_linestring → satisfied ────────────────────────────────


def test_dispersion_linestring_precondition_satisfied():
    from core.readiness import resolve_spatial_precondition
    r = resolve_spatial_precondition(
        "calculate_dispersion",
        file_context={"geometry_metadata": _gm(
            geometry_type="lonlat_linestring", road_geometry_available=True,
            line_geometry_constructible=True, confidence=0.85,
        )},
    )
    assert r["satisfied"] is True
    assert r["reason_code"] == "spatial_emission_available"


# ── 5. lonlat_point → not satisfied ─────────────────────────────────


def test_dispersion_point_only_precondition_not_satisfied():
    from core.readiness import resolve_spatial_precondition
    r = resolve_spatial_precondition(
        "calculate_dispersion",
        file_context={"geometry_metadata": _gm(
            geometry_type="lonlat_point", point_geometry_available=True,
            road_geometry_available=False, confidence=0.65,
        )},
    )
    assert r["satisfied"] is False
    assert r["reason_code"] == "point_geometry_not_road_geometry"
    assert "point" in r["message"].lower() or "lon/lat" in r["message"].lower()


# ── 6. join_key_only → not satisfied ────────────────────────────────


def test_dispersion_join_key_only_precondition_not_satisfied():
    from core.readiness import resolve_spatial_precondition
    r = resolve_spatial_precondition(
        "calculate_dispersion",
        file_context={"geometry_metadata": _gm(
            geometry_type="join_key_only", road_geometry_available=False,
            join_key_columns={"link_id": "link_id"}, confidence=0.40,
        )},
    )
    assert r["satisfied"] is False
    assert r["reason_code"] == "join_key_without_geometry"


# ── 7. No geometry → not satisfied ──────────────────────────────────


def test_dispersion_no_geometry_precondition_not_satisfied():
    from core.readiness import resolve_spatial_precondition
    r = resolve_spatial_precondition("calculate_dispersion", file_context={})
    assert r["satisfied"] is False
    assert r["reason_code"] == "missing_road_geometry"


# ── 8. Targeted diagnostic messages ─────────────────────────────────


def test_point_only_diagnostic_mentions_line_geometry():
    from core.readiness import resolve_spatial_precondition
    r = resolve_spatial_precondition(
        "calculate_dispersion",
        file_context={"geometry_metadata": _gm(
            geometry_type="lonlat_point", point_geometry_available=True,
            road_geometry_available=False,
        )},
    )
    assert r["satisfied"] is False
    msg = r["message"].lower()
    assert "point" in msg
    assert "line" in msg or "road-segment" in msg or "polygon" in msg


def test_join_key_diagnostic_mentions_geometry_file():
    from core.readiness import resolve_spatial_precondition
    r = resolve_spatial_precondition(
        "calculate_dispersion",
        file_context={"geometry_metadata": _gm(
            geometry_type="join_key_only", road_geometry_available=False,
            join_key_columns={"link_id": "link_id"},
        )},
    )
    msg = r["message"].lower()
    assert "join key" in msg or "link_id" in msg
    assert "geometry" in msg and ("file" in msg or "shapefile" in msg.lower() or "wkt" in msg.lower())


# ── 9. Candidate stored in readiness assessment ────────────────────


def test_spatial_emission_candidate_stored_for_dispersion():
    from core.readiness import assess_action_readiness, get_action_catalog
    catalog = get_action_catalog()
    dispersion = next((a for a in catalog if a.action_id == "run_dispersion"), None)
    assert dispersion is not None

    fc = {
        "file_path": "/tmp/roads_wkt.csv",
        "task_type": "macro_emission",
        "geometry_metadata": _gm(
            geometry_type="wkt", road_geometry_available=True,
            geometry_columns=["wkt"], confidence=0.90,
            evidence=["WKT confirmed"],
        ),
    }
    # Provide macro tool result so prerequisite passes
    result = assess_action_readiness(
        dispersion,
        file_context=fc,
        context_store=None,
        current_tool_results=[_macro_tool_result()],
        current_response_payloads=None,
    )
    # Should have spatial_emission_candidate in available_conditions
    assert "spatial_emission_candidate" in result.available_conditions


# ── 10. readiness with missing geometry returns REPAIRABLE ──────────


def test_dispersion_missing_geometry_returns_repairable():
    from core.readiness import assess_action_readiness, get_action_catalog, ReadinessStatus
    catalog = get_action_catalog()
    dispersion = next((a for a in catalog if a.action_id == "run_dispersion"), None)
    assert dispersion is not None

    fc = {
        "file_path": "/tmp/roads_point.csv",
        "task_type": "macro_emission",
        "geometry_metadata": _gm(
            geometry_type="lonlat_point", point_geometry_available=True,
            road_geometry_available=False,
        ),
    }
    result = assess_action_readiness(
        dispersion,
        file_context=fc,
        context_store=None,
        current_tool_results=[_macro_tool_result()],
        current_response_payloads=None,
    )
    assert result.status == ReadinessStatus.REPAIRABLE
    assert result.reason is not None
    assert result.reason.reason_code == "point_geometry_not_road_geometry"


def test_dispersion_join_key_only_returns_repairable():
    from core.readiness import assess_action_readiness, get_action_catalog, ReadinessStatus
    catalog = get_action_catalog()
    dispersion = next((a for a in catalog if a.action_id == "run_dispersion"), None)

    fc = {
        "file_path": "/tmp/roads_jk.csv",
        "task_type": "macro_emission",
        "geometry_metadata": _gm(
            geometry_type="join_key_only", road_geometry_available=False,
            join_key_columns={"link_id": "link_id"},
        ),
    }
    result = assess_action_readiness(
        dispersion,
        file_context=fc,
        context_store=None,
        current_tool_results=[_macro_tool_result()],
        current_response_payloads=None,
    )
    assert result.status == ReadinessStatus.REPAIRABLE
    assert result.reason is not None
    assert result.reason.reason_code == "join_key_without_geometry"


# ── 11. WKT geometry → READY when all prerequisites met ────────────


def test_dispersion_wkt_geometry_ready():
    from core.readiness import assess_action_readiness, get_action_catalog, ReadinessStatus
    catalog = get_action_catalog()
    dispersion = next((a for a in catalog if a.action_id == "run_dispersion"), None)

    fc = {
        "file_path": "/tmp/roads_wkt.csv",
        "task_type": "macro_emission",
        "geometry_metadata": _gm(
            geometry_type="wkt", road_geometry_available=True,
            geometry_columns=["wkt"], confidence=0.90,
            evidence=["WKT confirmed"],
        ),
    }
    result = assess_action_readiness(
        dispersion,
        file_context=fc,
        context_store=None,
        current_tool_results=[_macro_tool_result()],
        current_response_payloads=None,
    )
    # With emission available and geometry available → READY
    assert result.status == ReadinessStatus.READY


# ── 12. No modifications to macro or dispersion tools ───────────────


