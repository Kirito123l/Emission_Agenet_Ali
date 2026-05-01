"""Targeted tests for Phase 7.5 — spatial emission layer + bridge.

Verifies:
- test_6links.xlsx FileContext has WKT road geometry
- build_spatial_emission_layer succeeds for WKT geometry
- layer preserves emission_result_ref, output_path, source_file_path
- layer preserves geometry column and join keys
- lonlat_point and join_key_only rejected
- LinkName alias recognized as join key
- spatial preflight satisfied by spatial_emission_layer metadata
- no layer => existing missing geometry diagnostics still work
- layer serialization roundtrip
- macro post-execution metadata attachment works with fake results

Non-goals: dispersion argument bridge (requires tool internals, Phase 7.5B).
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


def _test_6links_file_context():
    """Return a FileContext-like dict matching test_data/test_6links.xlsx."""
    return {
        "file_path": str(Path(__file__).resolve().parent.parent / "test_data" / "test_6links.xlsx"),
        "row_count": 6,
        "task_type": "macro_emission",
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


# ── 1. test_6links real file has WKT road geometry ────────────────────────


def test_6links_real_file_has_wkt_geometry():
    """Verify the real test_6links.xlsx has a geometry column with WKT values."""
    test_data_dir = Path(__file__).resolve().parent.parent / "test_data"
    path = test_data_dir / "test_6links.xlsx"
    if not path.exists():
        pytest.skip("test_data/test_6links.xlsx not found")

    df = pd.read_excel(path)
    assert "geometry" in [c.lower() for c in df.columns], f"Expected geometry column, got {list(df.columns)}"
    geom_col = [c for c in df.columns if c.lower() == "geometry"][0]
    sample = str(df[geom_col].iloc[0]).upper().strip()
    assert sample.startswith("LINESTRING"), f"Expected WKT LINESTRING, got: {sample[:60]}"


# ── 2. build_spatial_emission_layer succeeds for WKT ──────────────────────


def test_build_layer_from_wkt_file_context():
    from core.spatial_emission_resolver import build_spatial_emission_layer
    fc = _test_6links_file_context()
    layer = build_spatial_emission_layer(
        file_context=fc,
        emission_result_ref="macro_emission:baseline",
    )
    assert layer.layer_available is True
    assert layer.geometry_type == "wkt"
    assert layer.spatial_product_type == "spatial_emission_layer"


# ── 3. layer preserves emission_result_ref ────────────────────────────────


def test_layer_preserves_emission_result_ref():
    from core.spatial_emission_resolver import build_spatial_emission_layer
    fc = _test_6links_file_context()
    layer = build_spatial_emission_layer(
        file_context=fc,
        emission_result_ref="macro_emission:test_scenario",
    )
    assert layer.emission_result_ref == "macro_emission:test_scenario"


# ── 4. layer preserves emission_output_path ───────────────────────────────


def test_layer_preserves_emission_output_path():
    from core.spatial_emission_resolver import build_spatial_emission_layer
    fc = _test_6links_file_context()
    layer = build_spatial_emission_layer(
        file_context=fc,
        emission_result_ref="macro_emission:baseline",
        emission_output_path="/tmp/emission_output.json",
    )
    assert layer.emission_output_path == "/tmp/emission_output.json"


# ── 5. layer preserves source_file_path ───────────────────────────────────


def test_layer_preserves_source_file_path():
    from core.spatial_emission_resolver import build_spatial_emission_layer
    fc = _test_6links_file_context()
    layer = build_spatial_emission_layer(file_context=fc)
    assert layer.source_file_path is not None
    assert "test_6links.xlsx" in layer.source_file_path


# ── 6. layer preserves geometry column ────────────────────────────────────


def test_layer_preserves_geometry_column():
    from core.spatial_emission_resolver import build_spatial_emission_layer
    fc = _test_6links_file_context()
    layer = build_spatial_emission_layer(file_context=fc)
    assert "geometry" in layer.geometry_columns
    assert layer.geometry_column == "geometry"


# ── 7. layer preserves join_key_columns ───────────────────────────────────


def test_layer_preserves_join_key_columns():
    from core.spatial_emission_resolver import build_spatial_emission_layer
    fc = _test_6links_file_context()
    layer = build_spatial_emission_layer(file_context=fc)
    assert "link_id" in layer.join_key_columns
    assert layer.join_key_columns["link_id"] == "link_id"


# ── 8. lonlat_point rejected ──────────────────────────────────────────────


def test_build_layer_rejects_lonlat_point():
    from core.spatial_emission_resolver import build_spatial_emission_layer
    fc = {
        "file_path": "/tmp/points.csv",
        "geometry_metadata": _gm(
            geometry_type="lonlat_point",
            point_geometry_available=True,
            road_geometry_available=False,
            confidence=0.65,
        ),
    }
    layer = build_spatial_emission_layer(file_context=fc)
    assert layer.layer_available is False
    assert layer.geometry_type == "lonlat_point"


# ── 9. join_key_only rejected ─────────────────────────────────────────────


def test_build_layer_rejects_join_key_only():
    from core.spatial_emission_resolver import build_spatial_emission_layer
    fc = {
        "file_path": "/tmp/roads_jk.csv",
        "geometry_metadata": _gm(
            geometry_type="join_key_only",
            road_geometry_available=False,
            join_key_columns={"link_id": "link_id"},
            confidence=0.40,
        ),
    }
    layer = build_spatial_emission_layer(file_context=fc)
    assert layer.layer_available is False
    assert layer.geometry_type == "join_key_only"


# ── 10. LinkName alias recognized as join key ─────────────────────────────


def test_linkname_alias_recognized_as_join_key():
    """Phase 7.5 alias hardening: LinkName column should be detected as join key."""
    from tools.file_analyzer import FileAnalyzerTool
    analyzer = FileAnalyzerTool()
    columns = ["LinkName", "Type", "Len_km", "Flow", "Speed"]
    gm = analyzer._detect_geometry_metadata(
        columns=columns,
        sample_rows=[
            {"LinkName": "快速路_R01", "Type": "快速路", "Len_km": 4.5, "Flow": 8027, "Speed": 80},
        ],
        spatial_metadata=None,
    )
    # Should be recognized as join_key_only since LinkName is a join key alias
    assert gm["geometry_type"] == "join_key_only"
    assert "linkname" in gm["join_key_columns"] or "link_name" in gm["join_key_columns"]
    assert gm["road_geometry_available"] is False


# ── 11. spatial preflight satisfied by layer metadata ─────────────────────


def test_preflight_satisfied_by_spatial_emission_layer():
    from core.readiness import resolve_spatial_precondition

    layer = {
        "layer_available": True,
        "spatial_product_type": "spatial_emission_layer",
        "geometry_type": "wkt",
        "source_file_path": "/tmp/test.csv",
        "emission_result_ref": "macro_emission:baseline",
    }
    result = resolve_spatial_precondition(
        tool_name="calculate_dispersion",
        file_context={},
        spatial_emission_layer=layer,
    )
    assert result["satisfied"] is True
    assert result["reason_code"] == "spatial_emission_layer_available"
    assert result["layer_dict"] is not None
    assert result["layer_dict"]["layer_available"] is True


# ── 12. no layer => existing diagnostics still work ───────────────────────


def test_preflight_missing_geometry_without_layer():
    from core.readiness import resolve_spatial_precondition

    result = resolve_spatial_precondition(
        tool_name="calculate_dispersion",
        file_context={},
        spatial_emission_layer=None,
    )
    assert result["satisfied"] is False
    assert result["reason_code"] == "missing_road_geometry"
    assert result["layer_dict"] is None


def test_preflight_join_key_only_without_layer():
    from core.readiness import resolve_spatial_precondition

    fc = {
        "geometry_metadata": _gm(
            geometry_type="join_key_only",
            road_geometry_available=False,
            join_key_columns={"link_id": "link_id"},
            confidence=0.40,
        ),
    }
    result = resolve_spatial_precondition(
        tool_name="calculate_dispersion",
        file_context=fc,
        spatial_emission_layer=None,
    )
    assert result["satisfied"] is False
    assert result["reason_code"] == "join_key_without_geometry"


# ── 13. layer serialization roundtrip ─────────────────────────────────────


def test_layer_serialization_roundtrip():
    from core.spatial_emission_resolver import build_spatial_emission_layer
    from core.spatial_emission import SpatialEmissionLayer

    fc = _test_6links_file_context()
    original = build_spatial_emission_layer(
        file_context=fc,
        emission_result_ref="macro_emission:baseline",
        emission_output_path="/tmp/out.json",
    )
    d = original.to_dict()
    restored = SpatialEmissionLayer.from_dict(d)

    assert restored.layer_available == original.layer_available
    assert restored.geometry_type == original.geometry_type
    assert restored.emission_result_ref == original.emission_result_ref
    assert restored.emission_output_path == original.emission_output_path
    assert restored.source_file_path == original.source_file_path
    assert restored.geometry_columns == original.geometry_columns
    assert restored.join_key_columns == original.join_key_columns
    assert restored.confidence == original.confidence


# ── 14. macro post-execution metadata bridge ──────────────────────────────


def test_build_layer_from_macro_result_in_tool_results():
    """Simulate the readiness check detecting a spatial emission layer from a completed macro run."""
    from core.readiness import _build_spatial_emission_layer_from_results

    fc = _test_6links_file_context()
    tool_results = [
        {
            "name": "calculate_macro_emission",
            "label": "baseline",
            "result": {
                "success": True,
                "data": {
                    "results": [{"link_id": "L001", "total_emissions_kg_per_hr": {"NOx": 0.01}}],
                },
            },
        },
    ]
    layer_dict = _build_spatial_emission_layer_from_results(
        file_context=fc,
        current_tool_results=tool_results,
    )
    assert layer_dict is not None
    assert layer_dict["layer_available"] is True
    assert layer_dict["geometry_type"] == "wkt"
    assert layer_dict["emission_result_ref"] == "macro_emission:baseline"


def test_no_layer_when_macro_not_completed():
    from core.readiness import _build_spatial_emission_layer_from_results

    fc = _test_6links_file_context()
    # No macro emission result
    tool_results: list = []
    layer_dict = _build_spatial_emission_layer_from_results(
        file_context=fc,
        current_tool_results=tool_results,
    )
    assert layer_dict is None


def test_no_layer_when_macro_failed():
    from core.readiness import _build_spatial_emission_layer_from_results

    fc = _test_6links_file_context()
    tool_results = [
        {
            "name": "calculate_macro_emission",
            "label": "baseline",
            "result": {"success": False, "error": "Calculation failed"},
        },
    ]
    layer_dict = _build_spatial_emission_layer_from_results(
        file_context=fc,
        current_tool_results=tool_results,
    )
    assert layer_dict is None


def test_no_layer_when_no_road_geometry_in_file_context():
    from core.readiness import _build_spatial_emission_layer_from_results

    fc = {
        "file_path": "/tmp/no_geo.csv",
        "geometry_metadata": _gm(
            geometry_type="join_key_only",
            road_geometry_available=False,
            join_key_columns={"link_id": "link_id"},
        ),
    }
    tool_results = [_macro_tool_result()]
    layer_dict = _build_spatial_emission_layer_from_results(
        file_context=fc,
        current_tool_results=tool_results,
    )
    assert layer_dict is None


# ── 15. assess_action_readiness sees spatial_emission_layer ───────────────


def test_assess_readiness_sees_spatial_emission_layer_for_dispersion():
    """When macro result exists and file has WKT, readiness for dispersion includes layer."""
    from core.readiness import assess_action_readiness, get_action_catalog, ReadinessStatus

    catalog = get_action_catalog()
    dispersion = next((a for a in catalog if a.action_id == "run_dispersion"), None)
    assert dispersion is not None, "run_dispersion action not found in catalog"

    fc = _test_6links_file_context()
    result = assess_action_readiness(
        dispersion,
        file_context=fc,
        context_store=None,
        current_tool_results=[_macro_tool_result()],
        current_response_payloads=None,
    )
    # With emission available, WKT geometry, and layer bridge → READY
    assert result.status == ReadinessStatus.READY
    assert "spatial_emission_layer_available" in result.available_conditions


def test_assess_readiness_dispersion_without_macro_still_repairable():
    """Without macro result, dispersion readiness falls through to candidate check."""
    from core.readiness import assess_action_readiness, get_action_catalog, ReadinessStatus

    catalog = get_action_catalog()
    dispersion = next((a for a in catalog if a.action_id == "run_dispersion"), None)
    assert dispersion is not None

    fc = _test_6links_file_context()
    # No macro tool result → no emission token → blocked on missing result
    result = assess_action_readiness(
        dispersion,
        file_context=fc,
        context_store=None,
        current_tool_results=[],
        current_response_payloads=None,
    )
    # Without emission result token, dependency validation blocks first
    assert result.status in (ReadinessStatus.REPAIRABLE, ReadinessStatus.BLOCKED)


def test_layer_available_when_precondition_satisfied():
    """When the spatial precondition is satisfied by a layer, available_conditions includes it."""
    from core.readiness import assess_action_readiness, get_action_catalog, ReadinessStatus

    catalog = get_action_catalog()
    dispersion = next((a for a in catalog if a.action_id == "run_dispersion"), None)
    assert dispersion is not None

    fc = _test_6links_file_context()
    result = assess_action_readiness(
        dispersion,
        file_context=fc,
        context_store=None,
        current_tool_results=[_macro_tool_result()],
        current_response_payloads=None,
    )
    assert result.status == ReadinessStatus.READY
    assert "spatial_emission_layer_available" in result.available_conditions
    # When layer bridge fires, spatial_emission_candidate is not populated
    # because the layer short-circuits the resolver — that's correct behavior.
