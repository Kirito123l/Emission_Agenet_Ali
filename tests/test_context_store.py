"""Tests for SessionContextStore and output safety rails."""

from __future__ import annotations

import json

from core.context_store import SessionContextStore
from core.output_safety import MAX_RESPONSE_CHARS, sanitize_response
from core.router_render_utils import format_results_as_fallback


def make_emission_result(label: str = "baseline") -> dict:
    return {
        "success": True,
        "summary": "Emission calculation finished for 2 links",
        "data": {
            "scenario_label": label,
            "query_info": {"pollutants": ["CO2", "NOx"], "model_year": 2020},
            "summary": {
                "total_links": 2,
                "total_emissions_kg_per_hr": {"CO2": 120.5, "NOx": 0.34},
            },
            "results": [
                {
                    "link_id": "L1",
                    "geometry": "LINESTRING (121.4 31.2, 121.5 31.3)",
                    "total_emissions_kg_per_hr": {"CO2": 80.0, "NOx": 0.2},
                },
                {
                    "link_id": "L2",
                    "geometry": "LINESTRING (121.5 31.3, 121.6 31.4)",
                    "total_emissions_kg_per_hr": {"CO2": 40.5, "NOx": 0.14},
                },
            ],
        },
    }


def make_dispersion_result(label: str = "baseline") -> dict:
    return {
        "success": True,
        "summary": "Dispersion completed for 15 receptors",
        "data": {
            "scenario_label": label,
            "query_info": {"pollutant": "NOx"},
            "summary": {
                "receptor_count": 15,
                "mean_concentration": 1.2,
                "max_concentration": 4.5,
            },
            "raster_grid": {
                "rows": 3,
                "cols": 4,
                "matrix_mean": [[0.1, 0.2], [0.3, 0.4]],
                "cell_receptor_map": {"0,0": [1, 2]},
            },
            "coverage_assessment": {"warnings": ["local-only coverage"]},
            "defaults_used": {"meteorology": "urban_summer_day"},
        },
    }


def make_hotspot_result(label: str = "baseline") -> dict:
    return {
        "success": True,
        "summary": "Hotspot analysis identified 2 hotspots",
        "data": {
            "scenario_label": label,
            "hotspot_count": 2,
            "summary": {"hotspot_count": 2, "max_concentration": 5.5},
            "hotspots": [
                {"rank": 1, "max_conc": 5.5, "area_m2": 1000.0},
                {"rank": 2, "max_conc": 4.1, "area_m2": 500.0},
            ],
        },
    }


class TestStoreAndRetrieve:
    def test_store_emission_result(self):
        store = SessionContextStore()
        store.store_result("calculate_macro_emission", make_emission_result())

        stored = store.get_by_type("emission")
        assert stored is not None
        assert stored.tool_name == "calculate_macro_emission"
        assert stored.metadata["count"] == 2

    def test_store_dispersion_result(self):
        store = SessionContextStore()
        store.store_result("calculate_dispersion", make_dispersion_result())

        stored = store.get_by_type("dispersion")
        assert stored is not None
        assert stored.metadata["receptor_count"] == 15

    def test_emission_not_overwritten_by_dispersion(self):
        store = SessionContextStore()
        emission = make_emission_result()
        store.store_result("calculate_macro_emission", emission)
        store.store_result("calculate_dispersion", make_dispersion_result())

        assert store.get_by_type("emission").data == emission
        assert store.get_by_type("dispersion") is not None

    def test_emission_not_overwritten_by_hotspot(self):
        store = SessionContextStore()
        emission = make_emission_result()
        store.store_result("calculate_macro_emission", emission)
        store.store_result("analyze_hotspots", make_hotspot_result())

        assert store.get_by_type("emission").data == emission
        assert store.get_by_type("hotspot") is not None


class TestToolDependencyResolution:
    def test_dispersion_gets_emission(self):
        store = SessionContextStore()
        store.store_result("calculate_macro_emission", make_emission_result())
        store.store_result("analyze_hotspots", make_hotspot_result())

        data = store.get_result_for_tool("calculate_dispersion")
        assert data is not None
        assert "results" in data.get("data", {})

    def test_hotspot_gets_dispersion(self):
        store = SessionContextStore()
        store.store_result("calculate_macro_emission", make_emission_result())
        dispersion = make_dispersion_result()
        store.store_result("calculate_dispersion", dispersion)

        data = store.get_result_for_tool("analyze_hotspots")
        assert data == dispersion

    def test_render_emission_gets_emission(self):
        store = SessionContextStore()
        emission = make_emission_result()
        store.store_result("calculate_macro_emission", emission)
        store.store_result("calculate_dispersion", make_dispersion_result())
        store.store_result("analyze_hotspots", make_hotspot_result())

        data = store.get_result_for_tool("render_spatial_map", layer_type="emission")
        assert data == emission

    def test_render_raster_gets_dispersion(self):
        store = SessionContextStore()
        dispersion = make_dispersion_result()
        store.store_result("calculate_dispersion", dispersion)

        data = store.get_result_for_tool("render_spatial_map", layer_type="raster")
        assert data == dispersion

    def test_render_contour_gets_dispersion(self):
        store = SessionContextStore()
        dispersion = make_dispersion_result()
        store.store_result("calculate_dispersion", dispersion)

        data = store.get_result_for_tool("render_spatial_map", layer_type="contour")
        assert data == dispersion

    def test_render_hotspot_gets_hotspot(self):
        store = SessionContextStore()
        hotspot = make_hotspot_result()
        store.store_result("analyze_hotspots", hotspot)

        data = store.get_result_for_tool("render_spatial_map", layer_type="hotspot")
        assert data == hotspot

    def test_render_default_priority(self):
        store = SessionContextStore()
        emission = make_emission_result()
        dispersion = make_dispersion_result()
        hotspot = make_hotspot_result()
        store.store_result("calculate_macro_emission", emission)
        store.store_result("calculate_dispersion", dispersion)
        store.store_result("analyze_hotspots", hotspot)

        data = store.get_result_for_tool("render_spatial_map")
        assert data == hotspot


class TestCompactSummary:
    def test_compact_excludes_raw_data(self):
        store = SessionContextStore()
        store.store_result("calculate_macro_emission", make_emission_result())

        compact = store.get_by_type("emission").compact()
        serialized = json.dumps(compact, ensure_ascii=False)
        assert "LINESTRING" not in serialized
        assert "matrix_mean" not in serialized

    def test_context_summary_readable(self):
        store = SessionContextStore()
        store.store_result("calculate_macro_emission", make_emission_result())
        store.store_result("calculate_dispersion", make_dispersion_result())

        summary = store.get_context_summary()
        assert "emission" in summary
        assert "dispersion" in summary
        assert "links" in summary or "receptors" in summary

    def test_context_summary_under_limit(self):
        store = SessionContextStore()
        store.store_result("calculate_macro_emission", make_emission_result())
        store.store_result("calculate_dispersion", make_dispersion_result())
        store.store_result("analyze_hotspots", make_hotspot_result())

        assert len(store.get_context_summary()) <= 500


class TestCurrentTurn:
    def test_current_turn_tracking(self):
        store = SessionContextStore()
        store.add_current_turn_result("calculate_macro_emission", make_emission_result())

        assert len(store.get_current_turn_results()) == 1
        assert store.get_current_turn_results()[0]["name"] == "calculate_macro_emission"

    def test_clear_current_turn(self):
        store = SessionContextStore()
        store.add_current_turn_result("calculate_macro_emission", make_emission_result())
        store.clear_current_turn()

        assert store.get_current_turn_results() == []

    def test_cross_turn_result_access(self):
        store = SessionContextStore()
        store.add_current_turn_result("calculate_macro_emission", make_emission_result())
        store.clear_current_turn()

        data = store.get_result_for_tool("calculate_dispersion")
        assert data is not None
        assert "results" in data.get("data", {})


class TestOutputSafety:
    def test_sanitize_normal_text(self):
        assert sanitize_response("Hello") == "Hello"

    def test_sanitize_geometry_dump(self):
        bad = "Results:\n" + ("LINESTRING(121.4 31.2, 121.5 31.3)\n" * 20)
        safe = sanitize_response(bad)
        assert "LINESTRING" not in safe or "已省略" in safe

    def test_sanitize_matrix_dump(self):
        bad = "matrix_mean = [[0.1, 0.2], [0.3, 0.4]]"
        safe = sanitize_response(bad)
        assert "matrix_mean" not in safe or "已省略" in safe

    def test_sanitize_long_text(self):
        text = "abc" * (MAX_RESPONSE_CHARS // 2 + 10)
        safe = sanitize_response(text)
        assert len(safe) <= MAX_RESPONSE_CHARS
        assert "已截断" in safe

    def test_fallback_no_raw_data(self):
        fallback = format_results_as_fallback(
            [
                {
                    "name": "calculate_macro_emission",
                    "result": {
                        "success": True,
                        "summary": "Calculated 20 links",
                        "data": {"results": [{"geometry": "LINESTRING(...)"}] * 20},
                    },
                }
            ]
        )
        assert "LINESTRING" not in fallback
        assert "Calculated 20 links" in fallback

    def test_fallback_under_limit(self):
        fallback = format_results_as_fallback(
            [
                {
                    "name": f"tool_{idx}",
                    "result": {
                        "success": True,
                        "summary": "x" * 1200,
                    },
                }
                for idx in range(4)
            ]
        )
        assert len(fallback) < 3000
