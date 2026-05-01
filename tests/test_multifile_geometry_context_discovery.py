"""Targeted tests for Phase 7.6E — multi-file geometry context discovery.

Verifies:
- storing multiple FileContexts preserves them
- list_analyzed_file_contexts returns metadata-only contexts
- join-key-only + one matching geometry context => READY with layer
- join-key-only + no geometry context => join_key_without_geometry
- join-key-only + point-only geometry context => rejected
- join-key-only + 90% overlap => needs confirmation
- join-key-only + two ACCEPT ambiguous => needs confirmation
- join-key-only + one 100% and one 90% => select 100%
- zero-overlap real-style candidate remains rejected
- direct WKT emission unchanged
- existing explicit geometry_file_context path still works
- no raw dataframe stored in context
- serialization roundtrip
- no dispersion tool changes

Non-goals: external geometry lookup, fuzzy matching, dispersion math changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

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


def _em_fc(file_name: str, **kw):
    fp = str(FIXTURE_DIR / file_name)
    gm = kw.pop("gm", {})
    return {"file_path": fp, "geometry_metadata": gm, **kw}


def _geo_fc(file_name: str, **kw):
    fp = str(FIXTURE_DIR / file_name)
    gm = kw.pop("gm", {})
    return {"file_path": fp, "geometry_metadata": gm, **kw}


def _macro_tool_result():
    return {
        "name": "calculate_macro_emission",
        "label": "baseline",
        "arguments": {"pollutants": ["NOx"]},
        "result": {
            "success": True,
            "data": {"results": [
                {"link_id": "L001", "link_length_km": 0.5,
                 "total_emissions_kg_per_hr": {"NOx": 0.01}},
            ]},
        },
    }


def _make_context_store():
    from core.context_store import SessionContextStore
    return SessionContextStore()


# ── 1. Store and retrieve multiple FileContexts ────────────────────────


def test_store_and_list_analyzed_file_contexts():
    store = _make_context_store()

    fc1 = _em_fc("emission_links_10.csv",
                 columns=["link_id", "length", "flow", "speed"],
                 gm=_gm(geometry_type="join_key_only",
                        join_key_columns={"link_id": "link_id"}))

    fc2 = _geo_fc("geometry_links_10.csv",
                  columns=["link_id", "geometry"],
                  gm=_gm(geometry_type="wkt", road_geometry_available=True,
                         geometry_columns=["geometry"],
                         join_key_columns={"link_id": "link_id"}))

    store.store_analyzed_file_context(fc1)
    store.store_analyzed_file_context(fc2)

    all_fcs = store.list_analyzed_file_contexts()
    assert len(all_fcs) == 2

    geo_fcs = store.find_geometry_file_contexts()
    assert len(geo_fcs) == 1
    assert "geometry_links_10" in geo_fcs[0].get("file_path", "")
    assert geo_fcs[0]["geometry_metadata"]["road_geometry_available"] is True


# ── 2. Stored contexts are metadata-only (no raw data) ─────────────────


def test_stored_context_is_metadata_only():
    store = _make_context_store()

    fc = _em_fc("emission_links_10.csv",
                columns=["link_id", "length", "flow", "speed"],
                gm=_gm(geometry_type="join_key_only",
                       join_key_columns={"link_id": "link_id"}))
    # Try to sneak in raw data
    fc["_raw_dataframe"] = "pretend this is a big dataframe"

    store.store_analyzed_file_context(fc)
    stored = store.list_analyzed_file_contexts()[0]
    assert "_raw_dataframe" not in stored
    assert "_raw_dataframe" not in stored.get("geometry_metadata", {})
    assert "file_path" in stored
    assert "geometry_metadata" in stored


# ── 3. Deduplication by file_path ─────────────────────────────────────


def test_store_deduplicates_by_file_path():
    store = _make_context_store()

    fc_v1 = _em_fc("emission_links_10.csv",
                   columns=["link_id", "length", "flow", "speed"],
                   gm=_gm(geometry_type="join_key_only",
                          join_key_columns={"link_id": "link_id"},
                          confidence=0.40))

    fc_v2 = _em_fc("emission_links_10.csv",
                   columns=["link_id", "length", "flow", "speed", "extra"],
                   gm=_gm(geometry_type="join_key_only",
                          join_key_columns={"link_id": "link_id"},
                          confidence=0.80))

    store.store_analyzed_file_context(fc_v1)
    store.store_analyzed_file_context(fc_v2)

    all_fcs = store.list_analyzed_file_contexts()
    assert len(all_fcs) == 1
    assert "extra" in all_fcs[0]["columns"]
    assert all_fcs[0]["geometry_metadata"]["confidence"] == 0.80


# ── 4. Empty file_context handled gracefully ──────────────────────────


def test_store_handles_empty_and_none():
    store = _make_context_store()
    store.store_analyzed_file_context({})
    store.store_analyzed_file_context(None)  # type: ignore
    assert len(store.list_analyzed_file_contexts()) == 0


# ── 5. Join-key-only + matching geometry in store => READY ────────────


def test_auto_discovery_matching_geometry_ready():
    from core.readiness import assess_action_readiness, get_action_catalog, ReadinessStatus

    store = _make_context_store()
    store.store_analyzed_file_context(_geo_fc(
        "geometry_links_10.csv",
        columns=["link_id", "geometry"],
        gm=_gm(geometry_type="wkt", road_geometry_available=True,
               geometry_columns=["geometry"],
               join_key_columns={"link_id": "link_id"}, confidence=0.90),
    ))

    em = _em_fc("emission_links_10.csv",
                columns=["link_id", "length", "flow", "speed"],
                gm=_gm(geometry_type="join_key_only",
                       join_key_columns={"link_id": "link_id"}, confidence=0.40))

    catalog = get_action_catalog()
    dispersion = next((a for a in catalog if a.action_id == "run_dispersion"), None)
    assert dispersion is not None

    result = assess_action_readiness(
        dispersion,
        file_context=em,
        context_store=store,
        current_tool_results=[_macro_tool_result()],
        current_response_payloads=None,
        geometry_file_context=None,
    )
    assert result.status == ReadinessStatus.READY, (
        f"Expected READY, got {result.status}: {result.reason.message if result.reason else 'no reason'}"
    )
    assert "spatial_emission_layer_available" in result.available_conditions


# ── 6. Join-key-only + no geometry in store => join_key_without_geometry ─


def test_auto_discovery_no_geometry_context_preserves_diagnostic():
    from core.readiness import assess_action_readiness, get_action_catalog, ReadinessStatus

    store = _make_context_store()
    # No geometry file contexts stored

    em = _em_fc("emission_links_10.csv",
                columns=["link_id", "length", "flow", "speed"],
                gm=_gm(geometry_type="join_key_only",
                       join_key_columns={"link_id": "link_id"}, confidence=0.40))

    catalog = get_action_catalog()
    dispersion = next((a for a in catalog if a.action_id == "run_dispersion"), None)
    assert dispersion is not None

    result = assess_action_readiness(
        dispersion,
        file_context=em,
        context_store=store,
        current_tool_results=[_macro_tool_result()],
        current_response_payloads=None,
        geometry_file_context=None,
    )
    assert result.status == ReadinessStatus.REPAIRABLE
    assert result.reason is not None
    assert result.reason.reason_code == "join_key_without_geometry"


# ── 7. Point-only geometry context not selected ────────────────────────


def test_auto_discovery_rejects_point_only():
    from core.readiness import ReadinessStatus
    from core.readiness import assess_action_readiness, get_action_catalog

    store = _make_context_store()
    store.store_analyzed_file_context(_geo_fc(
        "geometry_point_only.csv",
        columns=["link_id", "geometry"],
        gm=_gm(geometry_type="lonlat_point", road_geometry_available=False,
               point_geometry_available=True,
               geometry_columns=["geometry"],
               join_key_columns={"link_id": "link_id"}, confidence=0.65),
    ))

    em = _em_fc("emission_links_10.csv",
                columns=["link_id", "length", "flow", "speed"],
                gm=_gm(geometry_type="join_key_only",
                       join_key_columns={"link_id": "link_id"}, confidence=0.40))

    catalog = get_action_catalog()
    dispersion = next((a for a in catalog if a.action_id == "run_dispersion"), None)
    assert dispersion is not None

    result = assess_action_readiness(
        dispersion,
        file_context=em,
        context_store=store,
        current_tool_results=[_macro_tool_result()],
        current_response_payloads=None,
        geometry_file_context=None,
    )
    # Point-only should not be in geometry candidates (find_geometry_file_contexts filters them)
    assert result.status == ReadinessStatus.REPAIRABLE
    assert result.reason is not None
    # Falls back to join_key_without_geometry since no usable geometry context
    assert result.reason.reason_code == "join_key_without_geometry"


# ── 8. 90% overlap => needs confirmation, not auto-ready ──────────────


def test_auto_discovery_90pct_overlap_needs_confirmation():
    from core.readiness import assess_action_readiness, get_action_catalog, ReadinessStatus

    store = _make_context_store()
    store.store_analyzed_file_context(_geo_fc(
        "geometry_links_9.csv",
        columns=["link_id", "geometry"],
        gm=_gm(geometry_type="wkt", road_geometry_available=True,
               geometry_columns=["geometry"],
               join_key_columns={"link_id": "link_id"}, confidence=0.90),
    ))

    em = _em_fc("emission_links_10.csv",
                columns=["link_id", "length", "flow", "speed"],
                gm=_gm(geometry_type="join_key_only",
                       join_key_columns={"link_id": "link_id"}, confidence=0.40))

    catalog = get_action_catalog()
    dispersion = next((a for a in catalog if a.action_id == "run_dispersion"), None)
    assert dispersion is not None

    result = assess_action_readiness(
        dispersion,
        file_context=em,
        context_store=store,
        current_tool_results=[_macro_tool_result()],
        current_response_payloads=None,
        geometry_file_context=None,
    )
    assert result.status == ReadinessStatus.REPAIRABLE
    assert result.reason is not None
    # NEEDS_USER_CONFIRMATION from resolver → partial_key_overlap
    assert result.reason.reason_code in (
        "partial_key_overlap", "join_key_geometry_needs_confirmation",
    )


# ── 9. Two ACCEPT candidates at same rate => needs confirmation ───────


def test_auto_discovery_two_tied_accept_candidates():
    from core.spatial_emission_resolver import find_best_geometry_file_context
    from core.spatial_emission import JOIN_RESOLUTION_ACCEPT

    em = _em_fc("emission_links_10.csv",
                columns=["link_id", "length", "flow", "speed"],
                gm=_gm(geometry_type="join_key_only",
                       join_key_columns={"link_id": "link_id"}, confidence=0.40))

    # Two identical geometry files
    geo1 = _geo_fc("geometry_links_10.csv",
                   columns=["link_id", "geometry"],
                   gm=_gm(geometry_type="wkt", road_geometry_available=True,
                          geometry_columns=["geometry"],
                          join_key_columns={"link_id": "link_id"}, confidence=0.90))
    geo2 = _geo_fc("geometry_links_10.csv",
                   columns=["link_id", "geometry"],
                   gm=_gm(geometry_type="wkt", road_geometry_available=True,
                          geometry_columns=["geometry"],
                          join_key_columns={"link_id": "link_id"}, confidence=0.90))

    # Give them different paths so they're not deduplicated
    geo1["file_path"] = str(FIXTURE_DIR / "geometry_links_10.csv")
    geo2["file_path"] = str(FIXTURE_DIR / "geometry_links_10_copy.csv")

    result = find_best_geometry_file_context(
        emission_file_context=em,
        candidate_geometry_contexts=[geo1, geo2],
    )
    # Both are 100% ACCEPT — tied → needs confirmation
    assert result["selected"] is False
    assert result["reason_code"] == "multiple_geometry_candidates_tied"
    assert len(result["candidates"]) == 2
    assert all(c["status"] == JOIN_RESOLUTION_ACCEPT for c in result["candidates"])


# ── 10. One 100% and one 90% => select 100% ────────────────────────────


def test_auto_discovery_selects_highest_match():
    from core.spatial_emission_resolver import find_best_geometry_file_context

    em = _em_fc("emission_links_10.csv",
                columns=["link_id", "length", "flow", "speed"],
                gm=_gm(geometry_type="join_key_only",
                       join_key_columns={"link_id": "link_id"}, confidence=0.40))

    geo_full = _geo_fc("geometry_links_10.csv",
                       columns=["link_id", "geometry"],
                       gm=_gm(geometry_type="wkt", road_geometry_available=True,
                              geometry_columns=["geometry"],
                              join_key_columns={"link_id": "link_id"}, confidence=0.90))
    geo_partial = _geo_fc("geometry_links_9.csv",
                          columns=["link_id", "geometry"],
                          gm=_gm(geometry_type="wkt", road_geometry_available=True,
                                 geometry_columns=["geometry"],
                                 join_key_columns={"link_id": "link_id"}, confidence=0.90))

    result = find_best_geometry_file_context(
        emission_file_context=em,
        candidate_geometry_contexts=[geo_full, geo_partial],
    )
    assert result["selected"] is True
    assert result["reason_code"] == "join_key_geometry_resolved"
    # Selected the 100% one
    assert "geometry_links_10.csv" in result["geometry_file_context"].get("file_path", "")
    assert result["spatial_emission_layer"] is not None


# ── 11. Zero-overlap real-style candidate remains rejected ─────────────


def test_auto_discovery_zero_overlap_rejected():
    from core.spatial_emission_resolver import find_best_geometry_file_context

    em = _em_fc("emission_links_10.csv",
                columns=["link_id", "length", "flow", "speed"],
                gm=_gm(geometry_type="join_key_only",
                       join_key_columns={"link_id": "link_id"}, confidence=0.40))
    geo_no_overlap = _geo_fc("geometry_links_no_overlap.csv",
                             columns=["link_id", "geometry"],
                             gm=_gm(geometry_type="wkt", road_geometry_available=True,
                                    geometry_columns=["geometry"],
                                    join_key_columns={"link_id": "link_id"}, confidence=0.90))

    result = find_best_geometry_file_context(
        emission_file_context=em,
        candidate_geometry_contexts=[geo_no_overlap],
    )
    assert result["selected"] is False
    assert result["reason_code"] == "zero_key_overlap"
    assert result["spatial_emission_layer"] is None


# ── 12. Direct WKT file from Phase 7.5 unchanged ──────────────────────


def test_direct_wkt_emission_unchanged_by_auto_discovery():
    from core.readiness import assess_action_readiness, get_action_catalog, ReadinessStatus

    store = _make_context_store()
    # Store a geometry file in the store — should NOT affect direct WKT emission
    store.store_analyzed_file_context(_geo_fc(
        "geometry_links_10.csv",
        columns=["link_id", "geometry"],
        gm=_gm(geometry_type="wkt", road_geometry_available=True,
               geometry_columns=["geometry"],
               join_key_columns={"link_id": "link_id"}, confidence=0.90),
    ))

    em = _em_fc("emission_with_wkt.csv",
                columns=["link_id", "length", "flow", "speed", "geometry"],
                gm=_gm(geometry_type="wkt", road_geometry_available=True,
                       geometry_columns=["geometry"],
                       join_key_columns={"link_id": "link_id"}, confidence=0.90))

    catalog = get_action_catalog()
    dispersion = next((a for a in catalog if a.action_id == "run_dispersion"), None)
    assert dispersion is not None

    result = assess_action_readiness(
        dispersion,
        file_context=em,
        context_store=store,
        current_tool_results=[_macro_tool_result()],
        current_response_payloads=None,
        geometry_file_context=None,
    )
    # Direct WKT files have road_geometry_available → they don't trigger auto-discovery
    # (only join_key_only triggers discovery)
    assert result.status == ReadinessStatus.READY
    assert "spatial_emission_layer_available" in result.available_conditions


# ── 13. Explicit geometry_file_context path still works ────────────────


def test_explicit_geo_fc_still_works_with_auto_discovery():
    from core.readiness import assess_action_readiness, get_action_catalog, ReadinessStatus

    store = _make_context_store()
    # Store a DIFFERENT geometry file in the store
    store.store_analyzed_file_context(_geo_fc(
        "geometry_links_7.csv",
        columns=["link_id", "geometry"],
        gm=_gm(geometry_type="wkt", road_geometry_available=True,
               geometry_columns=["geometry"],
               join_key_columns={"link_id": "link_id"}, confidence=0.90),
    ))

    em = _em_fc("emission_links_10.csv",
                columns=["link_id", "length", "flow", "speed"],
                gm=_gm(geometry_type="join_key_only",
                       join_key_columns={"link_id": "link_id"}, confidence=0.40))
    geo_explicit = _geo_fc("geometry_links_10.csv",
                           columns=["link_id", "geometry"],
                           gm=_gm(geometry_type="wkt", road_geometry_available=True,
                                  geometry_columns=["geometry"],
                                  join_key_columns={"link_id": "link_id"}, confidence=0.90))

    catalog = get_action_catalog()
    dispersion = next((a for a in catalog if a.action_id == "run_dispersion"), None)
    assert dispersion is not None

    # Explicit geo_fc should take priority over auto-discovery
    result = assess_action_readiness(
        dispersion,
        file_context=em,
        context_store=store,
        current_tool_results=[_macro_tool_result()],
        current_response_payloads=None,
        geometry_file_context=geo_explicit,
    )
    assert result.status == ReadinessStatus.READY
    assert "spatial_emission_layer_available" in result.available_conditions


# ── 14. No dispersion tool changes ─────────────────────────────────────


def test_dispersion_tool_unchanged_by_discovery():
    from tools.dispersion import DispersionTool
    tool = DispersionTool()
    assert hasattr(tool, "execute")
    assert hasattr(tool, "name")


# ── 15. find_geometry_file_contexts filters correctly ──────────────────


def test_find_geometry_filters_by_road_geometry():
    store = _make_context_store()

    store.store_analyzed_file_context(_em_fc(
        "emission_links_10.csv",
        columns=["link_id", "length", "flow", "speed"],
        gm=_gm(geometry_type="join_key_only",
               join_key_columns={"link_id": "link_id"}, confidence=0.40),
    ))
    store.store_analyzed_file_context(_geo_fc(
        "geometry_point_only.csv",
        columns=["link_id", "geometry"],
        gm=_gm(geometry_type="lonlat_point", road_geometry_available=False,
               point_geometry_available=True,
               geometry_columns=["geometry"], confidence=0.65),
    ))
    store.store_analyzed_file_context(_geo_fc(
        "geometry_links_10.csv",
        columns=["link_id", "geometry"],
        gm=_gm(geometry_type="wkt", road_geometry_available=True,
               geometry_columns=["geometry"], confidence=0.90),
    ))

    geo = store.find_geometry_file_contexts()
    assert len(geo) == 1
    assert "geometry_links_10" in geo[0].get("file_path", "")


# ── 16. find_best_geometry_file_context handles empty candidates ───────


def test_find_best_handles_empty():
    from core.spatial_emission_resolver import find_best_geometry_file_context

    em = _em_fc("emission_links_10.csv",
                columns=["link_id", "length", "flow", "speed"],
                gm=_gm(geometry_type="join_key_only",
                       join_key_columns={"link_id": "link_id"}, confidence=0.40))

    result = find_best_geometry_file_context(
        emission_file_context=em,
        candidate_geometry_contexts=[],
    )
    assert result["selected"] is False
    assert result["reason_code"] == "no_geometry_candidates"


# ── 17. Non-join-key emission doesn't trigger auto-discovery ───────────


def test_non_join_key_emission_no_auto_discovery():
    from core.readiness import assess_action_readiness, get_action_catalog, ReadinessStatus

    store = _make_context_store()
    store.store_analyzed_file_context(_geo_fc(
        "geometry_links_10.csv",
        columns=["link_id", "geometry"],
        gm=_gm(geometry_type="wkt", road_geometry_available=True,
               geometry_columns=["geometry"],
               join_key_columns={"link_id": "link_id"}, confidence=0.90),
    ))

    # Emission file with "none" geometry type (not join_key_only)
    em = _em_fc("emission_no_join_key.csv",
                columns=["name", "length", "flow", "speed"],
                gm=_gm(geometry_type="none", confidence=0.0))

    catalog = get_action_catalog()
    dispersion = next((a for a in catalog if a.action_id == "run_dispersion"), None)
    assert dispersion is not None

    result = assess_action_readiness(
        dispersion,
        file_context=em,
        context_store=store,
        current_tool_results=[_macro_tool_result()],
        current_response_payloads=None,
        geometry_file_context=None,
    )
    assert result.status == ReadinessStatus.REPAIRABLE
    # Should be general "missing geometry", not join_key_without_geometry
    assert result.reason is not None
    assert result.reason.reason_code in (
        "missing_road_geometry", "missing_geometry_support",
    )
