"""Sprint 9 integration tests for the dispersion toolchain."""

from __future__ import annotations

import asyncio
from copy import deepcopy

import numpy as np
import pytest
from shapely.geometry import LineString

import calculators.dispersion as dispersion_module
from calculators.dispersion import DispersionCalculator
from calculators.dispersion_adapter import EmissionToDispersionAdapter
from core.memory import FactMemory
from core.executor import ToolExecutor
from core.tool_dependencies import TOOL_GRAPH
from services.standardizer import UnifiedStandardizer
from tools.dispersion import DispersionTool
from tools.spatial_renderer import SpatialRendererTool


PRESET_NAMES = [
    "urban_summer_day",
    "urban_summer_night",
    "urban_winter_day",
    "urban_winter_night",
    "windy_neutral",
    "calm_stable",
]


class ConstantModel:
    """Simple mock model that returns a constant prediction value."""

    def __init__(self, value: float = 1.0):
        self.value = float(value)

    def predict(self, features):
        return np.full(len(features), self.value, dtype=float)


def _build_mock_models(value: float = 1.0):
    return {
        stability: {"x0": ConstantModel(value), "x-1": ConstantModel(value)}
        for stability in ["VS", "S", "N1", "N2", "U", "VU"]
    }


def _build_full_macro_result() -> dict:
    return {
        "success": True,
        "data": {
            "query_info": {
                "model_year": 2020,
                "pollutants": ["NOx", "CO2"],
                "season": "夏季",
                "links_count": 3,
            },
            "results": [
                {
                    "link_id": "road_A",
                    "link_length_km": 0.5,
                    "traffic_flow_vph": 1200,
                    "avg_speed_kph": 40,
                    "fleet_composition": {
                        "Passenger Car": {
                            "source_type_id": 21,
                            "percentage": 0.8,
                            "vehicles_per_hour": 960,
                        }
                    },
                    "emissions_by_vehicle": {"Passenger Car": {"NOx": 0.05}},
                    "total_emissions_kg_per_hr": {"NOx": 0.12, "CO2": 8.5},
                    "emission_rates_g_per_veh_km": {"NOx": 0.2, "CO2": 14.2},
                    "geometry": "LINESTRING(121.400 31.200, 121.405 31.200)",
                },
                {
                    "link_id": "road_B",
                    "link_length_km": 0.3,
                    "traffic_flow_vph": 800,
                    "avg_speed_kph": 50,
                    "fleet_composition": {
                        "Passenger Car": {
                            "source_type_id": 21,
                            "percentage": 0.8,
                            "vehicles_per_hour": 640,
                        }
                    },
                    "emissions_by_vehicle": {"Passenger Car": {"NOx": 0.03}},
                    "total_emissions_kg_per_hr": {"NOx": 0.08, "CO2": 5.2},
                    "emission_rates_g_per_veh_km": {"NOx": 0.33, "CO2": 21.7},
                    "geometry": "LINESTRING(121.405 31.200, 121.410 31.205)",
                },
                {
                    "link_id": "road_C",
                    "link_length_km": 0.4,
                    "traffic_flow_vph": 600,
                    "avg_speed_kph": 30,
                    "fleet_composition": {
                        "Passenger Car": {
                            "source_type_id": 21,
                            "percentage": 0.8,
                            "vehicles_per_hour": 480,
                        }
                    },
                    "emissions_by_vehicle": {"Passenger Car": {"NOx": 0.04}},
                    "total_emissions_kg_per_hr": {"NOx": 0.10, "CO2": 6.0},
                    "emission_rates_g_per_veh_km": {"NOx": 0.42, "CO2": 25.0},
                    "geometry": "LINESTRING(121.410 31.205, 121.408 31.210)",
                },
            ],
            "summary": {
                "total_links": 3,
                "total_emissions_kg_per_hr": {"NOx": 0.30, "CO2": 19.7},
            },
        },
        "summary": "Calculated macro emissions for 3 road links...",
        "map_data": {"type": "emission", "links": []},
    }


def _build_full_dispersion_result() -> dict:
    return {
        "status": "success",
        "data": {
            "query_info": {
                "pollutant": "NOx",
                "n_roads": 3,
                "n_receptors": 15,
                "n_time_steps": 1,
                "roughness_height": 0.5,
                "met_source": "preset:urban_summer_day",
            },
            "results": [
                {
                    "receptor_id": i,
                    "lon": 121.400 + (i % 5) * 0.002,
                    "lat": 31.200 + (i // 5) * 0.002,
                    "local_x": float((i % 5) * 20),
                    "local_y": float((i // 5) * 20),
                    "concentrations": {"2024070112": 0.5 + i * 0.1},
                    "mean_conc": 0.5 + i * 0.1,
                    "max_conc": 0.8 + i * 0.15,
                }
                for i in range(15)
            ],
            "summary": {
                "receptor_count": 15,
                "time_steps": 1,
                "mean_concentration": 1.2,
                "max_concentration": 2.9,
                "unit": "μg/m³",
                "coordinate_system": "WGS-84",
            },
            "concentration_grid": {
                "receptors": [
                    {
                        "lon": 121.400 + (i % 5) * 0.002,
                        "lat": 31.200 + (i // 5) * 0.002,
                        "mean_conc": 0.5 + i * 0.1,
                        "max_conc": 0.8 + i * 0.15,
                    }
                    for i in range(15)
                ],
                "bounds": {
                    "min_lon": 121.400,
                    "max_lon": 121.408,
                    "min_lat": 31.200,
                    "max_lat": 31.204,
                },
            },
        },
    }


def _build_dispersion_tool_result() -> dict:
    dispersion_result = _build_full_dispersion_result()
    return {
        "success": True,
        "data": dispersion_result["data"],
        "summary": "Calculated concentration distribution for 15 receptors",
        "map_data": {
            "type": "concentration",
            "concentration_grid": dispersion_result["data"]["concentration_grid"],
        },
    }


def _build_contour_bands() -> dict:
    return {
        "type": "contour_bands",
        "interp_resolution_m": 10.0,
        "n_levels": 2,
        "levels": [0.1, 0.5],
        "bbox_wgs84": [121.4, 31.2, 121.408, 31.204],
        "n_receptors_used": 15,
        "geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "MultiPolygon",
                        "coordinates": [
                            [[
                                [121.401, 31.201],
                                [121.406, 31.201],
                                [121.406, 31.203],
                                [121.401, 31.203],
                                [121.401, 31.201],
                            ]]
                        ],
                    },
                    "properties": {
                        "level_min": 0.1,
                        "level_max": 0.5,
                        "level_index": 0,
                        "label": "0.10 - 0.50 μg/m³",
                    },
                }
            ],
        },
        "stats": {
            "min_concentration": 0.1,
            "max_concentration": 1.9,
            "mean_concentration": 0.8,
        },
    }


def _simulate_router_save_spatial_data(fact_memory: FactMemory, tool_results: list[dict]) -> bool:
    spatial_data_saved = False
    for tool_result_entry in tool_results:
        if not isinstance(tool_result_entry, dict):
            continue
        tool_name = tool_result_entry.get("name", "")
        if tool_name not in (
            "calculate_macro_emission",
            "calculate_micro_emission",
            "calculate_dispersion",
        ):
            continue

        actual = tool_result_entry.get("result", tool_result_entry)
        if not isinstance(actual, dict) or not actual.get("success"):
            continue

        data = actual.get("data", {})
        if not isinstance(data, dict):
            continue

        results_list = data.get("results", [])
        if results_list:
            has_geom = any(
                isinstance(item, dict) and item.get("geometry")
                for item in results_list[:5]
            )
            if has_geom:
                fact_memory.last_spatial_data = data
                spatial_data_saved = True
                break

        if not spatial_data_saved and "concentration_grid" in data:
            fact_memory.last_spatial_data = data
            spatial_data_saved = True
            break

    return spatial_data_saved


def _simulate_router_render_injection(
    fact_memory: FactMemory,
    tool_results: list[dict] | None = None,
) -> dict:
    effective_arguments: dict = {}
    injected = False

    for prev in reversed(tool_results or []):
        actual = prev.get("result", prev) if isinstance(prev, dict) else prev
        if not isinstance(actual, dict) or not actual.get("success"):
            continue
        prev_data = actual.get("data", {})
        if isinstance(prev_data, dict) and prev_data.get("results"):
            sample = prev_data["results"][:3]
            if any(isinstance(item, dict) and item.get("geometry") for item in sample):
                effective_arguments["_last_result"] = actual
                injected = True
                break

    if not injected:
        spatial = fact_memory.last_spatial_data
        if isinstance(spatial, dict) and spatial.get("results"):
            effective_arguments["_last_result"] = {"success": True, "data": spatial}

    return effective_arguments


@pytest.fixture
def standardizer() -> UnifiedStandardizer:
    return UnifiedStandardizer()


@pytest.fixture
def realistic_macro_result() -> dict:
    return {
        "status": "success",
        "data": {
            "query_info": {
                "model_year": 2024,
                "pollutants": ["NOx", "CO2"],
                "season": "夏季",
                "links_count": 2,
            },
            "results": [
                {
                    "link_id": "road_001",
                    "data_time": "2024-07-01 12:00:00",
                    "link_length_km": 0.10,
                    "traffic_flow_vph": 1200,
                    "avg_speed_kph": 45.0,
                    "fleet_composition": {
                        "Passenger Car": {"percentage": 70.0, "vehicles_per_hour": 840.0},
                    },
                    "emissions_by_vehicle": {
                        "Passenger Car": {"NOx": 0.60, "CO2": 30.0},
                    },
                    "total_emissions_kg_per_hr": {"NOx": 1.0, "CO2": 40.0},
                    "emission_rates_g_per_veh_km": {"NOx": 0.5, "CO2": 20.0},
                    "geometry": "LINESTRING(121.4000 31.2000, 121.4010 31.2000)",
                },
                {
                    "link_id": "road_002",
                    "data_time": "2024-07-01 12:00:00",
                    "link_length_km": 0.11,
                    "traffic_flow_vph": 900,
                    "avg_speed_kph": 38.0,
                    "fleet_composition": {
                        "Passenger Car": {"percentage": 65.0, "vehicles_per_hour": 585.0},
                    },
                    "emissions_by_vehicle": {
                        "Passenger Car": {"NOx": 0.55, "CO2": 28.0},
                    },
                    "total_emissions_kg_per_hr": {"NOx": 1.0, "CO2": 35.0},
                    "emission_rates_g_per_veh_km": {"NOx": 0.48, "CO2": 18.0},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[121.4010, 31.2000], [121.4020, 31.2006]],
                    },
                },
            ],
            "summary": {
                "total_links": 2,
                "total_emissions_kg_per_hr": {"NOx": 2.0, "CO2": 75.0},
            },
        },
    }


def _run_pipeline(monkeypatch, macro_result: dict, met_input):
    monkeypatch.setattr(dispersion_module, "load_all_models", lambda *args, **kwargs: _build_mock_models())
    roads_gdf, emissions_df = EmissionToDispersionAdapter.adapt(macro_result)
    calculator = DispersionCalculator()
    return calculator.calculate(
        roads_gdf=roads_gdf,
        emissions_df=emissions_df,
        met_input=met_input,
        pollutant="NOx",
    )


class TestMacroToDispersionPipeline:
    def test_adapter_field_mapping_from_real_macro_output(self, realistic_macro_result):
        roads_gdf, emissions_df = EmissionToDispersionAdapter.adapt(realistic_macro_result)

        assert list(roads_gdf.columns) == ["NAME_1", "geometry"]
        assert {"NAME_1", "data_time", "nox", "length"}.issubset(emissions_df.columns)
        assert roads_gdf.iloc[0]["NAME_1"] == "road_001"
        assert roads_gdf.geometry.iloc[0].geom_type == "LineString"
        assert emissions_df.loc[emissions_df["NAME_1"] == "road_001", "nox"].iloc[0] == pytest.approx(1.0)

    @pytest.mark.parametrize(
        "geometry_payload",
        [
            "LINESTRING(121.4 31.2, 121.405 31.2)",
            {"type": "LineString", "coordinates": [[121.4, 31.2], [121.405, 31.2]]},
            [[121.4, 31.2], [121.405, 31.2]],
        ],
    )
    def test_adapter_handles_wkt_and_geojson_geometry(self, realistic_macro_result, geometry_payload):
        payload = deepcopy(realistic_macro_result)
        payload["data"]["results"] = [payload["data"]["results"][0]]
        payload["data"]["results"][0]["geometry"] = geometry_payload

        roads_gdf, _ = EmissionToDispersionAdapter.adapt(payload)

        geometry = roads_gdf.geometry.iloc[0]
        assert isinstance(geometry, LineString)
        assert geometry.coords[0] == pytest.approx((121.4, 31.2))

    def test_full_pipeline_macro_to_dispersion_smoke(self, monkeypatch, realistic_macro_result):
        result = _run_pipeline(monkeypatch, realistic_macro_result, "urban_summer_day")

        assert result["status"] == "success"
        data = result["data"]
        assert data["results"]
        assert "concentration_grid" in data
        assert "raster_grid" in data
        assert {"receptor_count", "time_steps", "mean_concentration", "max_concentration", "unit"} <= set(
            data["summary"]
        )

    def test_result_contains_raster_grid(self, monkeypatch, realistic_macro_result):
        """Dispersion result includes raster_grid when grid_resolution specified."""
        monkeypatch.setattr(dispersion_module, "load_all_models", lambda *args, **kwargs: _build_mock_models())
        roads_gdf, emissions_df = EmissionToDispersionAdapter.adapt(realistic_macro_result)
        calculator = DispersionCalculator(
            config=dispersion_module.DispersionConfig(display_grid_resolution_m=100.0)
        )

        result = calculator.calculate(
            roads_gdf=roads_gdf,
            emissions_df=emissions_df,
            met_input="urban_summer_day",
            pollutant="NOx",
        )

        raster = result["data"]["raster_grid"]
        assert raster["resolution_m"] == 100.0
        assert raster["rows"] > 0
        assert raster["cols"] > 0
        assert "cell_receptor_map" in raster

    @pytest.mark.anyio
    async def test_result_contains_coverage_assessment(self, monkeypatch, realistic_macro_result):
        """Dispersion result includes coverage_assessment."""
        monkeypatch.setattr(dispersion_module, "load_all_models", lambda *args, **kwargs: _build_mock_models())
        tool = DispersionTool()

        result = await tool.execute(
            _last_result=deepcopy(realistic_macro_result),
            meteorology="urban_summer_day",
            pollutant="NOx",
        )

        assert result.success is True
        assert "coverage_assessment" in result.data
        assert "coverage_assessment" in result.map_data
        assert result.data["coverage_assessment"]["level"] == "sparse_local"
        assert "⚠️" in result.summary

    def test_grid_resolution_parameter(self, monkeypatch, realistic_macro_result):
        """Different grid_resolution values produce different grid sizes."""
        monkeypatch.setattr(dispersion_module, "load_all_models", lambda *args, **kwargs: _build_mock_models())
        roads_gdf, emissions_df = EmissionToDispersionAdapter.adapt(realistic_macro_result)
        sizes = {}

        for resolution in (50.0, 100.0, 200.0):
            calculator = DispersionCalculator(
                config=dispersion_module.DispersionConfig(display_grid_resolution_m=resolution)
            )
            result = calculator.calculate(
                roads_gdf=roads_gdf,
                emissions_df=emissions_df,
                met_input="urban_summer_day",
                pollutant="NOx",
            )
            sizes[resolution] = (
                result["data"]["raster_grid"]["rows"],
                result["data"]["raster_grid"]["cols"],
            )

        assert sizes[50.0][0] >= sizes[100.0][0] >= sizes[200.0][0]
        assert sizes[50.0][1] >= sizes[100.0][1] >= sizes[200.0][1]

    @pytest.mark.parametrize("preset_name", PRESET_NAMES)
    def test_full_pipeline_with_preset_meteorology(self, monkeypatch, realistic_macro_result, preset_name):
        result = _run_pipeline(monkeypatch, realistic_macro_result, preset_name)

        assert result["status"] == "success"
        assert result["data"]["query_info"]["met_source"] == "preset"
        assert result["data"]["summary"]["time_steps"] == 1

    def test_full_pipeline_with_custom_meteorology(self, monkeypatch, realistic_macro_result):
        met_input = {
            "wind_speed": 3.0,
            "wind_direction": 270,
            "stability_class": "U",
            "mixing_height": 800,
        }

        result = _run_pipeline(monkeypatch, realistic_macro_result, met_input)

        assert result["status"] == "success"
        assert result["data"]["query_info"]["met_source"] == "custom"
        assert result["data"]["results"]


class TestMeteorologyPresetOverride:
    """Tests for preset + override meteorology mode."""

    def test_pure_preset_returns_string(self):
        tool = DispersionTool()

        result = tool._build_met_input("urban_summer_day", {})

        assert isinstance(result, str)
        assert result == "urban_summer_day"

    def test_preset_with_wind_direction_override(self):
        tool = DispersionTool()

        result = tool._build_met_input("urban_summer_day", {"wind_direction": 315})

        assert isinstance(result, dict)
        assert result["wind_direction"] == 315
        assert result["_preset_name"] == "urban_summer_day"
        assert "wind_direction" in result.get("_overrides", {})
        assert result["stability_class"] == "VU"

    def test_preset_with_wind_speed_override(self):
        tool = DispersionTool()

        result = tool._build_met_input("urban_summer_day", {"wind_speed": 5.0})

        assert isinstance(result, dict)
        assert result["wind_speed"] == 5.0
        assert result["_preset_name"] == "urban_summer_day"

    def test_preset_with_multiple_overrides(self):
        tool = DispersionTool()

        result = tool._build_met_input(
            "urban_summer_day",
            {
                "wind_speed": 5.0,
                "wind_direction": 0,
                "stability_class": "S",
            },
        )

        assert result["wind_speed"] == 5.0
        assert result["wind_direction"] == 0
        assert result["stability_class"] == "S"
        assert result["mixing_height"] == 1500
        assert result["monin_obukhov_length"] == 500.0

    def test_calm_stable_with_direction_override(self):
        tool = DispersionTool()

        result = tool._build_met_input("calm_stable", {"wind_direction": 90})

        assert result["wind_direction"] == 90
        assert result["wind_speed"] == 0.5
        assert result["stability_class"] == "VS"

    def test_custom_mode_no_preset(self):
        tool = DispersionTool()

        result = tool._build_met_input(
            "custom",
            {
                "wind_speed": 3.0,
                "wind_direction": 270,
                "stability_class": "U",
                "mixing_height": 800,
            },
        )

        assert isinstance(result, dict)
        assert result["wind_speed"] == 3.0
        assert result["_preset_name"] is None
        assert result["_source_mode"] == "custom"

    def test_sfc_file_path_passthrough(self):
        tool = DispersionTool()

        result = tool._build_met_input("/path/to/met.sfc", {})

        assert isinstance(result, str)
        assert result == "/path/to/met.sfc"

    def test_overrides_record_original_values(self):
        tool = DispersionTool()

        result = tool._build_met_input("urban_summer_day", {"wind_direction": 315})
        overrides = result.get("_overrides", {})

        assert "wind_direction" in overrides
        assert overrides["wind_direction"]["from"] == 225.0
        assert overrides["wind_direction"]["to"] == 315.0

    def test_none_values_not_treated_as_override(self):
        tool = DispersionTool()

        result = tool._build_met_input(
            "urban_summer_day",
            {"wind_speed": None, "wind_direction": None},
        )

        assert isinstance(result, str)
        assert result == "urban_summer_day"


class TestMeteorologyStandardization:
    def test_preset_exact_match(self, standardizer):
        result = standardizer.standardize_meteorology("urban_summer_day")

        assert result.success is True
        assert result.normalized == "urban_summer_day"
        assert result.strategy == "exact"

    @pytest.mark.parametrize(
        ("raw_value", "expected"),
        [("城市夏季白天", "urban_summer_day"), ("静风稳定", "calm_stable")],
    )
    def test_preset_chinese_alias(self, standardizer, raw_value, expected):
        result = standardizer.standardize_meteorology(raw_value)

        assert result.success is True
        assert result.normalized == expected
        assert result.strategy == "alias"

    @pytest.mark.parametrize(
        ("raw_value", "expected"),
        [("summer day", "urban_summer_day"), ("windy", "windy_neutral")],
    )
    def test_preset_english_alias(self, standardizer, raw_value, expected):
        result = standardizer.standardize_meteorology(raw_value)

        assert result.success is True
        assert result.normalized == expected
        assert result.strategy == "alias"

    def test_preset_unknown_abstains(self, standardizer):
        result = standardizer.standardize_meteorology("hurricane")

        assert result.success is False
        assert result.strategy == "abstain"
        assert len(result.suggestions) == 6

    @pytest.mark.parametrize(
        ("raw_value", "expected"),
        [("very stable", "VS"), ("stable", "S"), ("不稳定", "U"), ("中性", "N1")],
    )
    def test_stability_class_standardization(self, standardizer, raw_value, expected):
        result = standardizer.standardize_stability_class(raw_value)

        assert result.success is True
        assert result.normalized == expected

    @pytest.mark.parametrize(("raw_value", "expected"), [("vs", "VS"), ("vu", "VU")])
    def test_stability_class_case_insensitive(self, standardizer, raw_value, expected):
        result = standardizer.standardize_stability_class(raw_value)

        assert result.success is True
        assert result.normalized == expected


class TestExecutorDispersionStandardization:
    def test_executor_standardizes_meteorology(self):
        executor = ToolExecutor()

        args, records = executor._standardize_arguments(
            "calculate_dispersion",
            {"meteorology": "夏季白天", "pollutant": "氮氧化物"},
        )

        assert args["meteorology"] == "urban_summer_day"
        assert args["pollutant"] == "NOx"
        assert {record["param"] for record in records} == {"meteorology", "pollutant"}

    def test_executor_passes_through_sfc_path(self):
        executor = ToolExecutor()

        args, records = executor._standardize_arguments(
            "calculate_dispersion",
            {"meteorology": "/path/to/met.sfc"},
        )

        assert args["meteorology"] == "/path/to/met.sfc"
        assert records == []

    def test_executor_passes_through_numeric_params(self):
        executor = ToolExecutor()

        args, records = executor._standardize_arguments(
            "calculate_dispersion",
            {"wind_speed": 3.0, "roughness_height": 0.5},
        )

        assert args["wind_speed"] == 3.0
        assert args["roughness_height"] == 0.5
        assert records == []

    def test_executor_preserves_preset_overrides_and_grid_resolution(self):
        executor = ToolExecutor()

        args, records = executor._standardize_arguments(
            "calculate_dispersion",
            {
                "meteorology": "夏季白天",
                "wind_direction": 315,
                "stability_class": "stable",
                "grid_resolution": 100,
            },
        )

        assert args["meteorology"] == "urban_summer_day"
        assert args["wind_direction"] == 315
        assert args["stability_class"] == "S"
        assert args["grid_resolution"] == 100
        assert {record["param"] for record in records} == {"meteorology", "stability_class"}


class TestMeteorologyUsedInResult:
    """Tests that meteorology details are properly reported in results."""

    @pytest.mark.anyio
    async def test_result_contains_meteorology_used(self, monkeypatch, realistic_macro_result):
        monkeypatch.setattr(dispersion_module, "load_all_models", lambda *args, **kwargs: _build_mock_models())
        tool = DispersionTool()

        result = await tool.execute(
            _last_result=deepcopy(realistic_macro_result),
            meteorology="urban_summer_day",
            pollutant="NOx",
        )

        assert result.success is True
        assert "meteorology_used" in result.data
        assert result.data["meteorology_used"]["_preset_name"] == "urban_summer_day"
        assert result.data["meteorology_used"]["wind_direction"] == 225.0

    @pytest.mark.anyio
    async def test_summary_shows_preset_name(self, monkeypatch, realistic_macro_result):
        monkeypatch.setattr(dispersion_module, "load_all_models", lambda *args, **kwargs: _build_mock_models())
        tool = DispersionTool()

        result = await tool.execute(
            _last_result=deepcopy(realistic_macro_result),
            meteorology="urban_summer_day",
            pollutant="NOx",
        )

        assert result.success is True
        assert "preset 'urban_summer_day'" in result.summary

    @pytest.mark.anyio
    async def test_summary_shows_overrides(self, monkeypatch, realistic_macro_result):
        monkeypatch.setattr(dispersion_module, "load_all_models", lambda *args, **kwargs: _build_mock_models())
        tool = DispersionTool()

        result = await tool.execute(
            _last_result=deepcopy(realistic_macro_result),
            meteorology="urban_summer_day",
            wind_direction=315,
            pollutant="NOx",
        )

        assert result.success is True
        assert "overrides" in result.summary
        assert "225→315" in result.summary

    @pytest.mark.anyio
    async def test_summary_shows_coverage_warning(self, monkeypatch, realistic_macro_result):
        monkeypatch.setattr(dispersion_module, "load_all_models", lambda *args, **kwargs: _build_mock_models())
        tool = DispersionTool()

        result = await tool.execute(
            _last_result=deepcopy(realistic_macro_result),
            meteorology="urban_summer_day",
            pollutant="NOx",
        )

        assert result.success is True
        assert "⚠️" in result.summary


class TestSchemaValidation:
    """Tests that schema changes work correctly with executor."""

    def test_grid_resolution_in_schema(self):
        from tools.definitions import TOOL_DEFINITIONS

        dispersion_schema = next(t for t in TOOL_DEFINITIONS if t["function"]["name"] == "calculate_dispersion")
        props = dispersion_schema["function"]["parameters"]["properties"]

        assert "grid_resolution" in props

    def test_wind_direction_description_no_custom_only(self):
        from tools.definitions import TOOL_DEFINITIONS

        dispersion_schema = next(t for t in TOOL_DEFINITIONS if t["function"]["name"] == "calculate_dispersion")
        props = dispersion_schema["function"]["parameters"]["properties"]
        desc = props["wind_direction"]["description"]

        assert "Only used when" not in desc

    def test_meteorology_description_mentions_preset_or_custom(self):
        """Meteorology description should mention preset/custom options.

        Note: detailed override instructions moved to config/skills/dispersion_skill.yaml
        as part of the skill injection architecture (v3).
        """
        from tools.definitions import TOOL_DEFINITIONS

        dispersion_schema = next(t for t in TOOL_DEFINITIONS if t["function"]["name"] == "calculate_dispersion")
        props = dispersion_schema["function"]["parameters"]["properties"]
        desc = props["meteorology"]["description"]

        assert "preset" in desc.lower() or "custom" in desc.lower()


class TestToolDependencyChain:
    def test_dispersion_requires_emission_result(self):
        assert "emission" in TOOL_GRAPH["calculate_dispersion"]["requires"]

    def test_macro_provides_emission_result(self):
        assert "emission" in TOOL_GRAPH["calculate_macro_emission"]["provides"]

    def test_dispersion_provides_dispersion_result(self):
        assert "dispersion" in TOOL_GRAPH["calculate_dispersion"]["provides"]


class TestDispersionToSpatialRenderer:
    def test_dispersion_result_renders_as_concentration_map(self):
        renderer = SpatialRendererTool()
        dispersion_tool_result = _build_dispersion_tool_result()

        result = asyncio.run(
            renderer.execute(
                data_source="last_result",
                _last_result=dispersion_tool_result,
                pollutant="NOx",
            )
        )

        assert result.success is True
        assert result.map_data is not None
        assert result.map_data["type"] == "concentration"
        assert result.map_data["layers"][0]["type"] == "circle"
        assert result.map_data["layers"][0]["data"]["features"]
        assert {"receptor_count", "unit"} <= set(result.map_data["summary"])

    def test_dispersion_result_detect_layer_type(self):
        renderer = SpatialRendererTool()

        assert renderer._detect_layer_type({"data": {"concentration_grid": {"receptors": []}}}) == "concentration"
        assert renderer._detect_layer_type(
            {"data": {"concentration_geojson": {"type": "FeatureCollection", "features": []}}}
        ) == "concentration"
        assert renderer._detect_layer_type({"data": {"results": [{"link_id": "road_A"}]}}) != "concentration"

    def test_concentration_map_geojson_structure(self):
        renderer = SpatialRendererTool()
        dispersion_tool_result = _build_dispersion_tool_result()

        map_data = renderer._build_concentration_map(dispersion_tool_result, pollutant="NOx", title="NOx Map")

        assert map_data is not None
        features = map_data["layers"][0]["data"]["features"]
        assert features

        for feature in features:
            coords = feature["geometry"]["coordinates"]
            props = feature["properties"]
            assert feature["geometry"]["type"] == "Point"
            assert isinstance(coords, list)
            assert len(coords) == 2
            assert 120.0 <= coords[0] <= 123.0
            assert 30.0 <= coords[1] <= 33.0
            assert {"receptor_id", "mean_conc", "max_conc", "value"} <= set(props)
            assert props["value"] == props["mean_conc"]

    def test_dispersion_result_prefers_contour_when_available(self):
        renderer = SpatialRendererTool()
        dispersion_tool_result = _build_dispersion_tool_result()
        dispersion_tool_result["data"]["contour_bands"] = _build_contour_bands()
        dispersion_tool_result["data"]["raster_grid"] = {
            "cell_centers_wgs84": [{"lon": 121.4, "lat": 31.2, "mean_conc": 1.0, "max_conc": 1.1}],
            "resolution_m": 50,
        }

        result = asyncio.run(
            renderer.execute(
                data_source="last_result",
                _last_result=dispersion_tool_result,
                pollutant="NOx",
            )
        )

        assert result.success is True
        assert result.map_data["type"] == "contour"
        assert result.map_data["layers"][0]["type"] == "filled_contour"


class TestFullToolChain:
    def test_macro_emission_to_dispersion_data_flow(self):
        macro_tool_result = _build_full_macro_result()
        tool = DispersionTool()

        emission_result = tool._resolve_emission_source("last_result", {"_last_result": macro_tool_result})

        assert emission_result is not None
        roads_gdf, emissions_df = EmissionToDispersionAdapter.adapt(emission_result)

        assert list(roads_gdf.columns) == ["NAME_1", "geometry"]
        assert {"NAME_1", "data_time", "nox", "length"} <= set(emissions_df.columns)
        assert roads_gdf.geometry.iloc[0].geom_type == "LineString"
        assert emissions_df.loc[emissions_df["NAME_1"] == "road_A", "nox"].iloc[0] == pytest.approx(0.12)
        assert emissions_df.loc[emissions_df["NAME_1"] == "road_C", "length"].iloc[0] == pytest.approx(0.4)

    def test_dispersion_to_render_data_flow(self):
        fact_memory = FactMemory()
        dispersion_tool_result = _build_dispersion_tool_result()
        tool_results = [
            {
                "tool_call_id": "call-dispersion",
                "name": "calculate_dispersion",
                "arguments": {"meteorology": "urban_summer_day"},
                "result": dispersion_tool_result,
            }
        ]

        assert _simulate_router_save_spatial_data(fact_memory, tool_results) is True
        effective_arguments = _simulate_router_render_injection(fact_memory)
        assert "concentration_grid" in effective_arguments["_last_result"]["data"]

        renderer = SpatialRendererTool()
        render_result = asyncio.run(
            renderer.execute(
                data_source="last_result",
                pollutant="NOx",
                **effective_arguments,
            )
        )

        assert render_result.success is True
        assert render_result.map_data["type"] == "concentration"
        assert render_result.map_data["layers"][0]["data"]["features"]

    def test_dispersion_tool_map_data_type_prefers_contour(self):
        tool = DispersionTool()
        data = {
            "concentration_grid": {"receptors": []},
            "raster_grid": {"rows": 1, "cols": 1},
            "contour_bands": _build_contour_bands(),
            "summary": {"mean_concentration": 1.0},
            "query_info": {"pollutant": "NOx"},
        }

        map_data = tool._build_map_data(data, "NOx")

        assert map_data["type"] == "contour"
        assert "contour_bands" in map_data

    def test_tool_dependency_chain_completeness(self):
        assert "emission" in TOOL_GRAPH["calculate_macro_emission"]["provides"]
        assert "emission" in TOOL_GRAPH["calculate_dispersion"]["requires"]
        assert "dispersion" in TOOL_GRAPH["calculate_dispersion"]["provides"]
        assert TOOL_GRAPH["render_spatial_map"]["requires"] == []

        available_results = set()
        chain = ["calculate_macro_emission", "calculate_dispersion", "render_spatial_map"]
        for tool_name in chain:
            requires = set(TOOL_GRAPH[tool_name]["requires"])
            assert requires <= available_results
            available_results.update(TOOL_GRAPH[tool_name]["provides"])


class TestRouterConcentrationSpatialData:
    def test_router_saves_concentration_grid_to_last_spatial_data(self):
        fact_memory = FactMemory()
        dispersion_tool_result = _build_dispersion_tool_result()
        tool_results = [
            {
                "tool_call_id": "call-dispersion",
                "name": "calculate_dispersion",
                "arguments": {"meteorology": "urban_summer_day"},
                "result": dispersion_tool_result,
            }
        ]

        saved = _simulate_router_save_spatial_data(fact_memory, tool_results)

        assert saved is True
        assert fact_memory.last_spatial_data is not None
        assert "concentration_grid" in fact_memory.last_spatial_data
        assert len(fact_memory.last_spatial_data["concentration_grid"]["receptors"]) == 15

    def test_router_injects_concentration_data_for_render(self):
        fact_memory = FactMemory(last_spatial_data=_build_full_dispersion_result()["data"])

        effective_arguments = _simulate_router_render_injection(fact_memory)

        assert "_last_result" in effective_arguments
        injected = effective_arguments["_last_result"]
        assert injected["success"] is True
        assert "concentration_grid" in injected["data"]
        assert len(injected["data"]["results"]) == 15
