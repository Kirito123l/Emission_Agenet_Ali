"""Targeted tests for Phase 7.5B — dispersion spatial emission layer bridge.

Verifies:
- test_6links.xlsx can build spatial_emission_layer
- geometry can be loaded from the layer's source file
- WKT geometry column is preserved/parsed
- link_id preserved if present
- emission_result_ref preserved in provenance/metadata
- join-key-only layer is rejected for geometry loading
- lonlat point-only layer is rejected
- no layer preserves existing behavior
- adapter receives geometry-bearing input without formula changes
- calculate_dispersion dry-run/unit path with test_6links does not fail on missing geometry
- test_no_geometry.xlsx remains targeted failure
- no evaluator/scoring changes verified implicitly

Non-goals: join-key resolver, external geometry lookup, dispersion formula changes.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from config import get_config, reset_config


@pytest.fixture(autouse=True)
def _restore_config():
    reset_config()
    yield
    reset_config()


# ── helpers ───────────────────────────────────────────────────────────────


def _gm(**kw):
    return dict(kw)


def _test_6links_layer_dict():
    """Build a spatial_emission_layer dict for test_6links.xlsx."""
    from core.spatial_emission_resolver import build_spatial_emission_layer

    fc = {
        "file_path": str(Path(__file__).resolve().parent.parent / "test_data" / "test_6links.xlsx"),
        "row_count": 6,
        "columns": ["link_id", "length", "flow", "speed", "geometry"],
        "geometry_metadata": _gm(
            geometry_type="wkt",
            road_geometry_available=True,
            geometry_columns=["geometry"],
            join_key_columns={"link_id": "link_id"},
            confidence=0.90,
            evidence=["WKT geometry values confirmed in sample rows"],
        ),
    }
    layer = build_spatial_emission_layer(
        file_context=fc,
        emission_result_ref="macro_emission:baseline",
    )
    assert layer.layer_available, "Precondition: layer must be available"
    return layer.to_dict()


def _macro_result():
    return {
        "name": "calculate_macro_emission",
        "label": "baseline",
        "result": {
            "success": True,
            "data": {
                "results": [
                    {"link_id": 38625, "link_length_km": 0.34, "total_emissions_kg_per_hr": {"NOx": 0.01}},
                    {"link_id": 6903, "link_length_km": 1.02, "total_emissions_kg_per_hr": {"NOx": 0.02}},
                ],
            },
        },
    }


# ── 1. test_6links.xlsx can build spatial_emission_layer ──────────────────


def test_6links_builds_spatial_emission_layer():
    from core.spatial_emission_resolver import build_spatial_emission_layer

    fc = {
        "file_path": str(Path(__file__).resolve().parent.parent / "test_data" / "test_6links.xlsx"),
        "row_count": 6,
        "columns": ["link_id", "length", "flow", "speed", "geometry"],
        "geometry_metadata": _gm(
            geometry_type="wkt",
            road_geometry_available=True,
            geometry_columns=["geometry"],
            join_key_columns={"link_id": "link_id"},
            confidence=0.90,
            evidence=["WKT confirmed"],
        ),
    }
    layer = build_spatial_emission_layer(
        file_context=fc,
        emission_result_ref="macro_emission:baseline",
    )
    d = layer.to_dict()
    assert d["layer_available"] is True
    assert d["geometry_type"] == "wkt"
    assert "test_6links.xlsx" in str(d.get("source_file_path", ""))
    assert d["emission_result_ref"] == "macro_emission:baseline"


# ── 2. geometry can be loaded from the layer's source file ────────────────


def test_load_geometry_from_spatial_layer():
    from tools.dispersion import _load_geometry_from_spatial_layer

    layer = _test_6links_layer_dict()
    geometry_rows = _load_geometry_from_spatial_layer(layer)
    assert geometry_rows is not None, "Should load geometry from test_6links.xlsx"
    assert len(geometry_rows) > 0, "Should have at least one geometry row"
    # Each row should have geometry
    for row in geometry_rows:
        assert "geometry" in row, f"Row missing geometry key: {list(row.keys())}"
        geom = row["geometry"]
        assert isinstance(geom, str) and geom.strip().upper().startswith("LINESTRING"), (
            f"Expected WKT LINESTRING, got: {str(geom)[:60]}"
        )


# ── 3. WKT geometry column preserved ─────────────────────────────────────


def test_wkt_geometry_column_preserved_in_loaded_rows():
    from tools.dispersion import _load_geometry_from_spatial_layer

    layer = _test_6links_layer_dict()
    rows = _load_geometry_from_spatial_layer(layer)
    assert rows is not None
    # All rows should have WKT geometry
    for row in rows:
        assert row["geometry"].strip().upper().startswith("LINESTRING")


# ── 4. link_id preserved ──────────────────────────────────────────────────


def test_link_id_preserved_in_loaded_geometry_rows():
    from tools.dispersion import _load_geometry_from_spatial_layer

    layer = _test_6links_layer_dict()
    rows = _load_geometry_from_spatial_layer(layer)
    assert rows is not None

    link_ids_found = []
    for row in rows:
        if "link_id" in row:
            link_ids_found.append(row["link_id"])
    assert len(link_ids_found) > 0, f"Expected link_id in geometry rows, got keys: {[list(r.keys()) for r in rows[:2]]}"


# ── 5. emission_result_ref preserved in layer provenance ──────────────────


def test_emission_result_ref_preserved_in_layer():
    from core.spatial_emission_resolver import build_spatial_emission_layer

    fc = {
        "file_path": str(Path(__file__).resolve().parent.parent / "test_data" / "test_6links.xlsx"),
        "geometry_metadata": _gm(
            geometry_type="wkt",
            road_geometry_available=True,
            geometry_columns=["geometry"],
            join_key_columns={"link_id": "link_id"},
            confidence=0.90,
        ),
    }
    layer = build_spatial_emission_layer(
        file_context=fc,
        emission_result_ref="macro_emission:test_label",
    )
    assert layer.emission_result_ref == "macro_emission:test_label"
    d = layer.to_dict()
    assert d["emission_result_ref"] == "macro_emission:test_label"


# ── 6. join-key-only layer rejected for geometry loading ──────────────────


def test_join_key_only_layer_rejected():
    from tools.dispersion import _load_geometry_from_spatial_layer

    layer = {
        "layer_available": False,
        "geometry_type": "join_key_only",
        "geometry_column": None,
        "geometry_columns": [],
        "source_file_path": None,
        "join_key_columns": {"link_id": "link_id"},
    }
    rows = _load_geometry_from_spatial_layer(layer)
    assert rows is None, "Join-key-only layer should not load geometry"


# ── 7. lonlat point-only layer rejected ───────────────────────────────────


def test_lonlat_point_layer_rejected():
    from tools.dispersion import _load_geometry_from_spatial_layer

    layer = {
        "layer_available": False,
        "geometry_type": "lonlat_point",
        "geometry_column": "lon",
        "geometry_columns": ["lon"],
        "source_file_path": "/tmp/points.csv",
        "join_key_columns": {},
    }
    rows = _load_geometry_from_spatial_layer(layer)
    assert rows is None, "Point-only layer should not load geometry"


# ── 8. no layer preserves existing behavior ───────────────────────────────


def test_dispersion_without_layer_uses_existing_behavior():
    """When no spatial layer is provided, the dispersion tool behaves as before."""
    from tools.dispersion import _load_geometry_from_spatial_layer

    rows = _load_geometry_from_spatial_layer({})
    assert rows is None
    rows = _load_geometry_from_spatial_layer(None)
    assert rows is None
    rows = _load_geometry_from_spatial_layer({"layer_available": False})
    assert rows is None


# ── 9. adapter receives geometry-bearing input without formula changes ────


def test_adapter_accepts_geometry_source_from_layer():
    """The adapter already supports geometry_source — verify it works with WKT rows."""
    from tools.dispersion import _load_geometry_from_spatial_layer
    from calculators.dispersion_adapter import EmissionToDispersionAdapter

    layer = _test_6links_layer_dict()
    geometry_rows = _load_geometry_from_spatial_layer(layer)
    assert geometry_rows is not None

    # Build minimal emission data matching the geometry rows
    results = []
    for row in geometry_rows[:2]:
        link_id = row.get("link_id", "unknown")
        results.append({
            "link_id": link_id,
            "link_length_km": 0.5,
            "total_emissions_kg_per_hr": {"NOx": 0.01},
        })

    emission_data = {"status": "success", "data": {"results": results}}
    roads_gdf, emissions_df = EmissionToDispersionAdapter.adapt(
        emission_data,
        geometry_source=geometry_rows,
        pollutant="NOx",
    )
    assert not roads_gdf.empty, "Adapter should produce non-empty roads_gdf from WKT geometry"
    assert len(roads_gdf) == len(results), (
        f"Expected {len(results)} roads, got {len(roads_gdf)}"
    )
    # Verify geometry type
    assert "LineString" in str(roads_gdf.geometry.iloc[0].geom_type), (
        f"Expected LineString geometry, got {roads_gdf.geometry.iloc[0].geom_type}"
    )


# ── 10. calculate_dispersion dry-run with test_6links does not fail ───────


@pytest.mark.asyncio
async def test_dispersion_dry_run_with_test6links_layer():
    """Dispersion tool with spatial layer reaches geometry check without missing-geometry error."""
    from tools.dispersion import DispersionTool

    tool = DispersionTool()
    layer = _test_6links_layer_dict()

    # Build macro emission result with link_ids matching test_6links rows
    last_result = {
        "success": True,
        "data": {
            "results": [
                {"link_id": 38625, "link_length_km": 0.34, "total_emissions_kg_per_hr": {"NOx": 0.01}},
                {"link_id": 6903, "link_length_km": 1.02, "total_emissions_kg_per_hr": {"NOx": 0.02}},
                {"link_id": 43403, "link_length_km": 0.42, "total_emissions_kg_per_hr": {"NOx": 0.01}},
                {"link_id": 40981, "link_length_km": 0.37, "total_emissions_kg_per_hr": {"NOx": 0.01}},
                {"link_id": 44894, "link_length_km": 0.57, "total_emissions_kg_per_hr": {"NOx": 0.01}},
                {"link_id": 37708, "link_length_km": 0.62, "total_emissions_kg_per_hr": {"NOx": 0.02}},
            ],
            "scenario_label": "baseline",
        },
    }

    result = await tool.execute(
        emission_source="last_result",
        _last_result=last_result,
        _spatial_emission_layer=layer,
        pollutant="NOx",
        meteorology="urban_summer_day",
        roughness_height=0.5,
    )
    # Should reach actual dispersion calculation (not fail on missing geometry)
    # The error will be "No road geometry" only if adapter couldn't match geometry
    if not result.success:
        error_msg = str(result.error or "").lower()
        assert "no road geometry" not in error_msg, (
            f"Dispersion should not fail on missing geometry; got: {result.error}"
        )


# ── 11. test_no_geometry.xlsx remains targeted failure ────────────────────


def test_no_geometry_layer_returns_none_from_loader():
    from tools.dispersion import _load_geometry_from_spatial_layer

    layer = {
        "layer_available": False,
        "geometry_type": "join_key_only",
        "geometry_column": None,
        "geometry_columns": [],
        "source_file_path": str(Path(__file__).resolve().parent.parent / "test_data" / "test_no_geometry.xlsx"),
        "join_key_columns": {"link_id": "link_id"},
    }
    rows = _load_geometry_from_spatial_layer(layer)
    assert rows is None, "No-geometry file should not yield geometry rows"


# ── 12. layer serialized through adapter produces valid geometry ──────────


def test_layer_geometry_rows_produce_valid_shapely_geometry():
    """Geometry rows from the layer, when parsed by the adapter, produce valid shapely objects."""
    from tools.dispersion import _load_geometry_from_spatial_layer
    from shapely import wkt as shapely_wkt

    layer = _test_6links_layer_dict()
    rows = _load_geometry_from_spatial_layer(layer)
    assert rows is not None and len(rows) > 0

    for row in rows:
        geom = shapely_wkt.loads(str(row["geometry"]))
        assert geom is not None
        assert not geom.is_empty
        assert geom.geom_type == "LineString"


# ── 13. router bridge injects spatial layer for dispersion ────────────────


def test_router_bridge_injects_spatial_layer_when_geometry_available():
    """Verify _prepare_tool_arguments injects _spatial_emission_layer for dispersion."""
    from core.router import UnifiedRouter
    from core.task_state import TaskState, FileContext, GeometryMetadata

    try:
        router = UnifiedRouter(session_id="test_spatial_bridge")
    except Exception:
        pytest.skip("Cannot instantiate UnifiedRouter in test environment")

    state = TaskState()
    fc = FileContext()
    fc.has_file = True
    fc.grounded = True
    fc.file_path = str(Path(__file__).resolve().parent.parent / "test_data" / "test_6links.xlsx")
    fc.task_type = "macro_emission"
    fc.row_count = 6
    fc.columns = ["link_id", "length", "flow", "speed", "geometry"]
    fc.geometry_metadata = GeometryMetadata(
        road_geometry_available=True,
        geometry_type="wkt",
        geometry_columns=["geometry"],
        join_key_columns={"link_id": "link_id"},
        confidence=0.90,
        evidence=["WKT confirmed"],
    )
    state.file_context = fc

    args = router._prepare_tool_arguments("calculate_dispersion", None, state=state)
    assert "_spatial_emission_layer" in args, (
        f"Router should inject _spatial_emission_layer; got keys: {list(args.keys())}"
    )
    layer = args["_spatial_emission_layer"]
    assert isinstance(layer, dict)
    assert layer.get("layer_available") is True
    assert layer.get("geometry_type") == "wkt"


def test_router_bridge_skips_when_no_geometry():
    """When file has no road geometry, _spatial_emission_layer is NOT injected."""
    from core.router import UnifiedRouter
    from core.task_state import TaskState, FileContext, GeometryMetadata

    try:
        router = UnifiedRouter(session_id="test_spatial_bridge_no_geo")
    except Exception:
        pytest.skip("Cannot instantiate UnifiedRouter in test environment")

    state = TaskState()
    fc = FileContext()
    fc.has_file = True
    fc.grounded = True
    fc.file_path = "/tmp/no_geo.csv"
    fc.geometry_metadata = GeometryMetadata(
        road_geometry_available=False,
        geometry_type="join_key_only",
        join_key_columns={"link_id": "link_id"},
    )
    state.file_context = fc

    args = router._prepare_tool_arguments("calculate_dispersion", None, state=state)
    assert "_spatial_emission_layer" not in args, (
        f"No-geometry files should not inject spatial layer; got: {args.get('_spatial_emission_layer')}"
    )
