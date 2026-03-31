"""Tests for the Sprint 8 dispersion calculator implementation."""

from __future__ import annotations

import inspect
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import yaml
from shapely.geometry import LineString

from calculators import dispersion
from calculators.dispersion_adapter import EmissionToDispersionAdapter


class ConstantModel:
    """Simple stand-in for XGBoost models in unit tests."""

    def __init__(self, value: float):
        self.value = value

    def predict(self, data):
        if hasattr(data, "num_row"):
            size = data.num_row()
        else:
            size = len(data)
        return np.full(size, self.value, dtype=float)


def _build_mock_models(value: float = 1.0):
    return {
        key: {"pos": ConstantModel(value), "neg": ConstantModel(value)}
        for key in ["VS", "S", "N1", "N2", "U", "VU"]
    }


def _build_roads_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "NAME_1": ["R1", "R2"],
            "width": [7.0, 8.0],
            "geometry": [
                LineString([(121.4000, 31.2000), (121.4010, 31.2000)]),
                LineString([(121.4002, 31.2003), (121.4012, 31.2003)]),
            ],
        },
        geometry="geometry",
        crs="EPSG:4326",
    )


def _build_emissions_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "NAME_1": ["R1", "R2"],
            "data_time": [pd.Timestamp("2024-07-01 12:00:00")] * 2,
            "nox": [1.0, 2.0],
            "length": [1.0, 1.2],
        }
    )


def _build_predict_sources(strength: float = 1e-6) -> np.ndarray:
    return np.array(
        [
            [
                [0.0, 0.0, strength, 90.0],
                [5.0, 0.0, strength, 90.0],
            ]
        ],
        dtype=float,
    )


def _build_met_df(stab_class: str = "U") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date": [2024070112],
            "WSPD": [2.5],
            "WDIR": [270.0],
            "MixHGT_C": [800.0],
            "L": [-300.0],
            "H": [100.0],
            "Stab_Class": [stab_class],
        }
    )


def _build_macro_result(include_geometry: bool = True) -> dict:
    result = {
        "status": "success",
        "data": {
            "results": [
                {
                    "link_id": "R1",
                    "link_length_km": 1.0,
                    "total_emissions_kg_per_hr": {"NOx": 1.5},
                },
                {
                    "link_id": "R2",
                    "link_length_km": 1.2,
                    "total_emissions_kg_per_hr": {"NOx": 2.5},
                },
            ]
        },
    }
    if include_geometry:
        result["data"]["results"][0]["geometry"] = "LINESTRING (121.4 31.2, 121.401 31.2)"
        result["data"]["results"][1]["geometry"] = "LINESTRING (121.4002 31.2003, 121.4012 31.2003)"
    return result


class TestDispersionConfig:
    def test_default_config_values(self):
        config = dispersion.DispersionConfig()

        assert config.source_crs == "EPSG:4326"
        assert config.utm_zone == 51
        assert config.utm_hemisphere == "north"
        assert config.segment_interval_m == 10.0
        assert config.default_road_width_m == 7.0
        assert config.offset_rule == {3.5: 40, 8.5: 40}
        assert config.background_spacing_m == 50.0
        assert config.buffer_extra_m == 3.0
        assert config.display_grid_resolution_m == 50.0
        assert config.contour_enabled is True
        assert config.contour_interp_resolution_m == 10.0
        assert config.contour_n_levels == 12
        assert config.contour_smooth_sigma == 1.0
        assert config.downwind_range == (0.0, 1000.0)
        assert config.upwind_range == (-100.0, 0.0)
        assert config.crosswind_range == (-100.0, 100.0)
        assert config.batch_size == 200000
        assert config.roughness_height == 0.5
        assert config.model_base_dir == ""
        assert config.met_source == "preset"

    def test_custom_config(self):
        config = dispersion.DispersionConfig(
            source_crs="EPSG:4490",
            utm_zone=50,
            utm_hemisphere="south",
            segment_interval_m=20.0,
            display_grid_resolution_m=100.0,
            contour_enabled=False,
            contour_interp_resolution_m=25.0,
            contour_n_levels=6,
            contour_smooth_sigma=0.5,
            roughness_height=1.0,
            model_base_dir="/tmp/models",
        )

        assert config.source_crs == "EPSG:4490"
        assert config.utm_zone == 50
        assert config.utm_hemisphere == "south"
        assert config.segment_interval_m == 20.0
        assert config.display_grid_resolution_m == 100.0
        assert config.contour_enabled is False
        assert config.contour_interp_resolution_m == 25.0
        assert config.contour_n_levels == 6
        assert config.contour_smooth_sigma == 0.5
        assert config.roughness_height == 1.0
        assert config.model_base_dir == "/tmp/models"


class TestCoordinateTransforms:
    def test_convert_coords_wgs84_to_utm51n(self):
        easting, northing = dispersion.convert_coords(
            121.4,
            31.2,
            source_crs="EPSG:4326",
            utm_zone=51,
            utm_hemisphere="north",
        )

        assert 300000 < easting < 400000
        assert 3400000 < northing < 3600000

    def test_convert_coords_roundtrip(self):
        lon, lat = 121.4, 31.2
        easting, northing = dispersion.convert_coords(
            lon,
            lat,
            source_crs="EPSG:4326",
            utm_zone=51,
            utm_hemisphere="north",
        )

        local_x = np.array([100.0])
        local_y = np.array([200.0])
        back_lon, back_lat = dispersion.inverse_transform_coords(
            local_x=local_x,
            local_y=local_y,
            origin_x=easting - 100.0,
            origin_y=northing - 200.0,
            utm_zone=51,
            utm_hemisphere="north",
        )

        assert abs(back_lon[0] - lon) < 0.001
        assert abs(back_lat[0] - lat) < 0.001

    def test_compute_local_origin(self):
        coords = np.array([[3.0, 4.0], [1.5, 7.0], [2.0, 0.5]])

        origin_x, origin_y = dispersion.compute_local_origin(coords)

        assert origin_x == 1.5
        assert origin_y == 0.5

    def test_inverse_transform(self):
        lon, lat = 121.4, 31.2
        easting, northing = dispersion.convert_coords(
            lon,
            lat,
            source_crs="EPSG:4326",
            utm_zone=51,
            utm_hemisphere="north",
        )

        out_lon, out_lat = dispersion.inverse_transform_coords(
            local_x=np.array([0.0]),
            local_y=np.array([0.0]),
            origin_x=easting,
            origin_y=northing,
            utm_zone=51,
            utm_hemisphere="north",
        )

        assert abs(out_lon[0] - lon) < 0.001
        assert abs(out_lat[0] - lat) < 0.001


class TestStabilityClassification:
    def test_very_stable(self):
        assert dispersion.classify_stability(100, 2.0, 500) == "VS"

    def test_stable(self):
        assert dispersion.classify_stability(500, 2.0, 500) == "S"

    def test_neutral1(self):
        assert dispersion.classify_stability(2000, 2.0, 500) == "N1"

    def test_neutral2(self):
        assert dispersion.classify_stability(-2000, 2.0, 500) == "N2"

    def test_unstable(self):
        assert dispersion.classify_stability(-500, 2.0, 500) == "U"

    def test_very_unstable(self):
        assert dispersion.classify_stability(-100, 2.0, 500) == "VU"

    def test_missing_data(self):
        assert dispersion.classify_stability(-99999, 2.0, 500) == "UNK"


class TestEmissionConversion:
    def test_nox_kg_h_to_g_s_m2(self):
        value = dispersion.emission_to_line_source_strength(1.0, 1.0, 7.0)
        expected = 1000.0 / 3600.0 / 7000.0
        assert value == pytest.approx(expected)

    def test_zero_length_raises(self):
        with pytest.raises(ValueError):
            dispersion.emission_to_line_source_strength(1.0, 0.0)


class TestRoadSegmentation:
    def test_split_polyline_basic(self):
        segments = dispersion.split_polyline_by_interval_with_angle(
            [(0.0, 0.0), (20.0, 0.0), (20.0, 10.0)],
            interval=10.0,
        )

        assert len(segments) == 3
        assert segments[0][0] == pytest.approx(5.0)
        assert segments[0][1] == pytest.approx(0.0)
        assert segments[0][2] == pytest.approx(90.0)
        assert segments[1][0] == pytest.approx(15.0)
        assert segments[1][2] == pytest.approx(90.0)
        assert segments[2][0] == pytest.approx(20.0)
        assert segments[2][1] == pytest.approx(5.0)
        assert segments[2][2] == pytest.approx(0.0)

    def test_split_polyline_short_segment(self):
        segments = dispersion.split_polyline_by_interval_with_angle(
            [(0.0, 0.0), (5.0, 0.0)],
            interval=10.0,
        )

        assert len(segments) == 1
        assert segments[0][0] == pytest.approx(2.5)
        assert segments[0][1] == pytest.approx(0.0)
        assert segments[0][2] == pytest.approx(90.0)


class TestReceptorGeneration:
    def test_generate_receptors_returns_dataframe(self):
        road_df = pd.DataFrame(
            [
                {
                    "index": "R1",
                    "new_coords": [(0.0, 0.0), (100.0, 0.0)],
                    "width": 7.0,
                }
            ]
        )

        receptors = dispersion.generate_receptors_custom_offset(
            road_df,
            offset_rule={3.5: 40},
            background_spacing=50,
            buffer_extra=3,
            global_extent=(0.0, 100.0, 0.0, 100.0),
        )

        assert isinstance(receptors, pd.DataFrame)
        assert "x" in receptors.columns
        assert "y" in receptors.columns
        assert len(receptors) > 0

    def test_generate_receptors_no_matplotlib(self):
        source = inspect.getsource(dispersion.generate_receptors_custom_offset)

        assert "matplotlib" not in source
        assert "plt." not in source
        assert "plt" not in dispersion.generate_receptors_custom_offset.__code__.co_names


class TestModelLoading:
    def test_load_all_models_file_paths(self, monkeypatch):
        loaded_paths = []

        def fake_load_model(path):
            loaded_paths.append(Path(path))
            return str(path)

        monkeypatch.setattr(dispersion, "load_model", fake_load_model)

        models = dispersion.load_all_models("/base/models", 0.5)

        expected_paths = {
            Path("/base/models/model_z=0.5/model_RLINE_remet_multidir_verystable_2000_x0_M.json"),
            Path("/base/models/model_z=0.5/model_RLINE_remet_multidir_verystable_2000_x-1_M.json"),
            Path("/base/models/model_z=0.5/model_RLINE_remet_multidir_stable_2000_x0_M.json"),
            Path("/base/models/model_z=0.5/model_RLINE_remet_multidir_stable_2000_x-1_M.json"),
            Path("/base/models/model_z=0.5/model_RLINE_remet_multidir_neutral1_x0_M.json"),
            Path("/base/models/model_z=0.5/model_RLINE_remet_multidir_neutral1_x-1_M.json"),
            Path("/base/models/model_z=0.5/model_RLINE_remet_multidir_neutral2_x0_M.json"),
            Path("/base/models/model_z=0.5/model_RLINE_remet_multidir_neutral2_x-1_M.json"),
            Path("/base/models/model_z=0.5/model_RLINE_remet_multidir_unstable_2000_x0_M.json"),
            Path("/base/models/model_z=0.5/model_RLINE_remet_multidir_unstable_2000_x-1_M.json"),
            Path("/base/models/model_z=0.5/model_RLINE_remet_multidir_veryunstable_2000_x0_M.json"),
            Path("/base/models/model_z=0.5/model_RLINE_remet_multidir_veryunstable_2000_x-1_M.json"),
        }

        assert set(loaded_paths) == expected_paths
        assert len(loaded_paths) == 12
        assert set(models.keys()) == {"VS", "S", "N1", "N2", "U", "VU"}

    def test_roughness_to_suffix_mapping(self):
        assert dispersion.ROUGHNESS_MAP[0.05] == "L"
        assert dispersion.ROUGHNESS_MAP[0.5] == "M"
        assert dispersion.ROUGHNESS_MAP[1.0] == "H"

    def test_invalid_roughness_raises(self):
        with pytest.raises(ValueError):
            dispersion.load_all_models("/base/models", 0.3)


class TestPredictTimeSeriesXgb:
    def test_smoke_with_mock_models(self):
        result = dispersion.predict_time_series_xgb(
            models=_build_mock_models(2.0),
            receptors_x=np.array([10.0, 20.0]),
            receptors_y=np.array([0.0, 0.0]),
            sources=_build_predict_sources(1e-6),
            met=_build_met_df("U"),
        )

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2
        assert (result["Conc"] > 0).all()

    def test_output_columns(self):
        result = dispersion.predict_time_series_xgb(
            models=_build_mock_models(1.0),
            receptors_x=np.array([10.0]),
            receptors_y=np.array([0.0]),
            sources=_build_predict_sources(1e-6)[:, :1, :],
            met=_build_met_df("VS"),
        )

        assert list(result.columns) == ["Date", "Receptor_ID", "Receptor_X", "Receptor_Y", "Conc"]

    def test_zero_emission_gives_zero_conc(self):
        result = dispersion.predict_time_series_xgb(
            models=_build_mock_models(5.0),
            receptors_x=np.array([10.0]),
            receptors_y=np.array([0.0]),
            sources=_build_predict_sources(0.0)[:, :1, :],
            met=_build_met_df("N1"),
        )

        assert result["Conc"].iloc[0] == pytest.approx(0.0)


class TestMeteorologyPresets:
    def test_load_presets(self):
        preset_path = Path(__file__).resolve().parents[1] / "config" / "meteorology_presets.yaml"
        data = yaml.safe_load(preset_path.read_text(encoding="utf-8"))

        assert "presets" in data
        assert len(data["presets"]) == 6

    def test_preset_fields_complete(self):
        preset_path = Path(__file__).resolve().parents[1] / "config" / "meteorology_presets.yaml"
        data = yaml.safe_load(preset_path.read_text(encoding="utf-8"))
        required_fields = {
            "description",
            "stability_class",
            "wind_speed_mps",
            "wind_direction_deg",
            "mixing_height_m",
            "monin_obukhov_length",
            "temperature_k",
        }

        for preset in data["presets"].values():
            assert required_fields.issubset(preset.keys())


class TestDispersionCalculator:
    def test_init_default_config(self):
        calculator = dispersion.DispersionCalculator()

        assert isinstance(calculator.config, dispersion.DispersionConfig)
        assert calculator._models is None

    def test_init_custom_config(self):
        config = dispersion.DispersionConfig(batch_size=128, roughness_height=1.0)
        calculator = dispersion.DispersionCalculator(config)

        assert calculator.config.batch_size == 128
        assert calculator.config.roughness_height == 1.0

    def test_validate_inputs_missing_column(self):
        calculator = dispersion.DispersionCalculator()
        roads = _build_roads_gdf().drop(columns=["NAME_1"])

        with pytest.raises(ValueError):
            calculator._validate_inputs(roads, _build_emissions_df(), "NOx")

    def test_validate_inputs_unsupported_pollutant(self):
        calculator = dispersion.DispersionCalculator()

        with pytest.raises(ValueError):
            calculator._validate_inputs(_build_roads_gdf(), _build_emissions_df(), "CO2")

    def test_process_meteorology_preset(self):
        calculator = dispersion.DispersionCalculator()
        met_df = calculator._process_meteorology("urban_summer_day")

        assert len(met_df) == 1
        assert met_df.iloc[0]["Stab_Class"] == "VU"
        assert "H" in met_df.columns

    def test_process_meteorology_dict(self):
        calculator = dispersion.DispersionCalculator()
        met_df = calculator._process_meteorology(
            {
                "wind_speed_mps": 3.0,
                "wind_direction_deg": 225,
                "mixing_height_m": 800,
                "monin_obukhov_length": -300,
                "stability_class": "U",
                "temperature_k": 290,
            }
        )

        assert len(met_df) == 1
        assert met_df.iloc[0]["WSPD"] == pytest.approx(3.0)
        assert met_df.iloc[0]["Stab_Class"] == "U"

    def test_process_meteorology_sfc_file(self, tmp_path):
        sfc_path = tmp_path / "sample.sfc"
        sfc_path.write_text(
            "\n".join(
                [
                    "HEADER",
                    "2024 7 1 183 12 100 0.3 0 0 1500 1500 -50 0.5 0 0.2 2.5 225 10 305 10 0 0 50 1013 0 0 0",
                ]
            ),
            encoding="utf-8",
        )

        calculator = dispersion.DispersionCalculator()
        met_df = calculator._process_meteorology(str(sfc_path))

        assert len(met_df) == 1
        assert met_df.iloc[0]["Stab_Class"] == "VU"
        assert met_df.iloc[0]["Date"] == 24070112

    def test_calculate_returns_error_on_bad_input(self):
        calculator = dispersion.DispersionCalculator()
        bad_roads = pd.DataFrame({"NAME_1": ["R1"]})

        result = calculator.calculate(bad_roads, _build_emissions_df(), "urban_summer_day")

        assert result["status"] == "error"
        assert result["error_code"] == "CALCULATION_ERROR"

    def test_assemble_result_structure(self):
        calculator = dispersion.DispersionCalculator()
        calculator._matched_road_count = 2
        calculator._met_source_used = "preset"

        receptors_df = pd.DataFrame({"x": [0.0, 10.0], "y": [0.0, 5.0]})
        conc_df = pd.DataFrame(
            {
                "Date": [2024070112, 2024070112],
                "Receptor_ID": [0, 1],
                "Receptor_X": [0.0, 10.0],
                "Receptor_Y": [0.0, 5.0],
                "Conc": [12.0, 18.0],
            }
        )
        result = calculator._assemble_result(
            conc_df=conc_df,
            receptors_df=receptors_df,
            lons=np.array([121.4, 121.401]),
            lats=np.array([31.2, 31.201]),
            met_df=_build_met_df("U"),
            pollutant="NOx",
            origin=(100.0, 200.0),
        )

        assert result["status"] == "success"
        assert "query_info" in result["data"]
        assert "results" in result["data"]
        assert "summary" in result["data"]
        assert "concentration_grid" in result["data"]
        assert "raster_grid" in result["data"]
        assert len(result["data"]["results"]) == 2

    def test_calculate_success_with_mock_models(self, monkeypatch):
        monkeypatch.setattr(dispersion, "load_all_models", lambda *args, **kwargs: _build_mock_models(1.0))

        calculator = dispersion.DispersionCalculator()
        result = calculator.calculate(
            roads_gdf=_build_roads_gdf(),
            emissions_df=_build_emissions_df(),
            met_input="urban_summer_day",
        )

        assert result["status"] == "success"
        assert result["data"]["query_info"]["n_roads"] == 2
        assert result["data"]["summary"]["receptor_count"] > 0


class TestEmissionToDispersionAdapter:
    def test_adapt_basic(self):
        roads_gdf, emissions_df = EmissionToDispersionAdapter.adapt(_build_macro_result())

        assert isinstance(roads_gdf, gpd.GeoDataFrame)
        assert list(emissions_df.columns) == ["NAME_1", "data_time", "nox", "length"]
        assert len(roads_gdf) == 2
        assert len(emissions_df) == 2

    def test_adapt_field_mapping(self):
        _, emissions_df = EmissionToDispersionAdapter.adapt(_build_macro_result())

        row = emissions_df.iloc[0]
        assert row["NAME_1"] == "R1"
        assert row["nox"] == pytest.approx(1.5)
        assert row["length"] == pytest.approx(1.0)

    def test_adapt_with_geometry_source(self):
        macro_result = _build_macro_result(include_geometry=False)
        geometry_source = [
            {"link_id": "R1", "geometry": "LINESTRING (121.4 31.2, 121.401 31.2)"},
            {"link_id": "R2", "geometry": "LINESTRING (121.4002 31.2003, 121.4012 31.2003)"},
        ]

        roads_gdf, _ = EmissionToDispersionAdapter.adapt(macro_result, geometry_source=geometry_source)

        assert len(roads_gdf) == 2
        assert roads_gdf.iloc[0].geometry.geom_type == "LineString"

    def test_adapt_missing_geometry_warning(self, caplog):
        caplog.set_level("WARNING")
        roads_gdf, emissions_df = EmissionToDispersionAdapter.adapt(
            _build_macro_result(include_geometry=False)
        )

        assert roads_gdf.empty
        assert len(emissions_df) == 2
        assert "Missing geometry for link_id=R1" in caplog.text
