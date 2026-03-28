"""Numerical equivalence and pipeline smoke tests for the dispersion refactor."""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Proj, transform
import pytest
from shapely.geometry import LineString

from calculators import dispersion
from calculators.dispersion_adapter import EmissionToDispersionAdapter


class ConstantModel:
    """Predicts a constant value for each input row."""

    def __init__(self, value: float):
        self.value = value

    def predict(self, data):
        if hasattr(data, "num_row"):
            size = data.num_row()
        else:
            size = len(data)
        return np.full(size, self.value, dtype=float)


class CapturingModel(ConstantModel):
    """Predicts a constant value and records each feature matrix it receives."""

    def __init__(self, value: float):
        super().__init__(value)
        self.calls: list[np.ndarray] = []

    def predict(self, data):
        if hasattr(data, "num_row"):
            matrix = np.asarray(data.get_data())
        else:
            matrix = np.asarray(data, dtype=float)
        self.calls.append(matrix.copy())
        return super().predict(data)


def _build_mock_models(value: float = 1.0):
    return {
        key: {"pos": ConstantModel(value), "neg": ConstantModel(value)}
        for key in ["VS", "S", "N1", "N2", "U", "VU"]
    }


@pytest.fixture
def minimal_dispersion_scenario():
    """Two short WGS-84 roads, one timestep of emissions, and one met timestep."""
    roads_gdf = gpd.GeoDataFrame(
        {
            "NAME_1": ["R1", "R2"],
            "width": [7.0, 7.0],
            "geometry": [
                LineString([(121.4000, 31.2000), (121.4010, 31.2000)]),
                LineString([(121.4000, 31.2009), (121.4010, 31.2009)]),
            ],
        },
        geometry="geometry",
        crs="EPSG:4326",
    )
    emissions_df = pd.DataFrame(
        {
            "NAME_1": ["R1", "R2"],
            "data_time": [pd.Timestamp("2024-07-01 12:00:00")] * 2,
            "nox": [1.0, 1.0],
            "length": [0.1, 0.1],
        }
    )
    met_df = pd.DataFrame(
        {
            "Date": [2024070112],
            "WSPD": [3.0],
            "WDIR": [270.0],
            "MixHGT_C": [800.0],
            "L": [-500.0],
            "H": [100.0],
            "Stab_Class": ["U"],
        }
    )
    return {
        "roads_gdf": roads_gdf,
        "emissions_df": emissions_df,
        "met_df": met_df,
    }


@lru_cache(maxsize=1)
def _load_legacy_functions():
    """Extract selected legacy functions without importing mode_inference.py."""
    legacy_path = (
        Path(__file__).resolve().parents[1]
        / "ps-xgb-aermod-rline-surrogate"
        / "mode_inference.py"
    )
    source = legacy_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function_sources: dict[str, str] = {}

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in {
            "convert_to_utm",
            "split_polyline_by_interval_with_angle",
        }:
            function_sources[node.name] = ast.get_source_segment(source, node)

    namespace = {
        "np": np,
        "Proj": Proj,
        "transform": transform,
        "wgs84": Proj(proj="latlong", datum="WGS84"),
        "utm51n": Proj(proj="utm", zone=51, datum="WGS84", hemisphere="north"),
    }
    exec(function_sources["convert_to_utm"], namespace)
    exec(function_sources["split_polyline_by_interval_with_angle"], namespace)
    return (
        namespace["convert_to_utm"],
        namespace["split_polyline_by_interval_with_angle"],
    )


def _legacy_classify_stability(L: float, wspd: float, mix_hgt: float) -> str:
    """Replicate the inline stability logic from mode_inference.py lines 448-457."""
    stability = "UNK"
    if (L > 0) and (L <= 200):
        stability = "VS"
    if (L > 200) and (L < 1000):
        stability = "S"
    if (L >= 1000) and (wspd != 999) and (L != -99999):
        stability = "N1"
    if (L <= -1000) and (wspd != 999) and (L != -99999) and (mix_hgt != -999):
        stability = "N2"
    if (L > -1000) and (L <= -200) and (mix_hgt != -999) and (wspd != 999):
        stability = "U"
    if (L > -200) and (L < 0) and (mix_hgt != -999) and (wspd != 999):
        stability = "VU"
    return stability


def _build_minimal_macro_result() -> dict:
    return {
        "status": "success",
        "data": {
            "results": [
                {
                    "link_id": "R1",
                    "link_length_km": 0.1,
                    "total_emissions_kg_per_hr": {"NOx": 1.0},
                    "geometry": "LINESTRING (121.4 31.2, 121.401 31.2)",
                    "data_time": "2024-07-01 12:00:00",
                },
                {
                    "link_id": "R2",
                    "link_length_km": 0.1,
                    "total_emissions_kg_per_hr": {"NOx": 1.0},
                    "geometry": "LINESTRING (121.4 31.2009, 121.401 31.2009)",
                    "data_time": "2024-07-01 12:00:00",
                },
            ]
        },
    }


def _build_smoke_config() -> dispersion.DispersionConfig:
    return dispersion.DispersionConfig(
        segment_interval_m=50.0,
        offset_rule={3.5: 60.0},
        background_spacing_m=100.0,
        buffer_extra_m=3.0,
        batch_size=1000,
    )


def test_convert_coords_equivalence():
    legacy_convert_to_utm, _ = _load_legacy_functions()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        legacy_x, legacy_y = legacy_convert_to_utm(121.4, 31.2)

    new_x, new_y = dispersion.convert_coords(121.4, 31.2, "EPSG:4326", 51, "north")

    assert abs(new_x - legacy_x) < 0.01
    assert abs(new_y - legacy_y) < 0.01


def test_classify_stability_equivalence():
    values = [50, 100, 200, 500, 999, 1000, 2000, -50, -100, -200, -500, -999, -1000, -2000, -99999]

    for L in values:
        expected = _legacy_classify_stability(L, 3.0, 800.0)
        actual = dispersion.classify_stability(L, 3.0, 800.0)
        assert actual == expected


def test_split_polyline_equivalence():
    _, legacy_split = _load_legacy_functions()
    coords = [(0.0, 0.0), (20.0, 0.0), (20.0, 10.0)]

    legacy_segments = legacy_split(coords, interval=10.0)
    new_segments = dispersion.split_polyline_by_interval_with_angle(coords, interval=10.0)

    assert len(new_segments) == len(legacy_segments)
    for new_segment, legacy_segment in zip(new_segments, legacy_segments):
        assert new_segment[0] == pytest.approx(legacy_segment[0], abs=1e-6)
        assert new_segment[1] == pytest.approx(legacy_segment[1], abs=1e-6)
        assert new_segment[2] == pytest.approx(legacy_segment[2], abs=1e-6)


def test_emission_conversion_equivalence():
    nox_kg_h = 1.0
    length_km = 0.1
    expected = nox_kg_h * 1000.0 / 3600.0 / (length_km * 1000.0 * 7.0)

    actual = dispersion.emission_to_line_source_strength(nox_kg_h, length_km, 7.0)

    assert actual == expected


def test_predict_core_logic_equivalence():
    capturing_model = CapturingModel(1.0)
    models = {
        "U": {
            "pos": capturing_model,
            "neg": ConstantModel(1.0),
        }
    }
    receptors_x = np.array([100.0], dtype=float)
    receptors_y = np.array([50.0], dtype=float)
    sources = np.array([[[50.0, 50.0, 0.001, 45.0]]], dtype=float)
    met_df = pd.DataFrame(
        {
            "Date": [2024070112],
            "WSPD": [3.0],
            "WDIR": [270.0],
            "MixHGT_C": [800.0],
            "L": [-500.0],
            "H": [100.0],
            "Stab_Class": ["U"],
        }
    )

    result = dispersion.predict_time_series_xgb(
        models=models,
        receptors_x=receptors_x,
        receptors_y=receptors_y,
        sources=sources,
        met=met_df,
        x_range0=(0.0, 1000.0),
        x_range1=(-100.0, 0.0),
        y_range=(-100.0, 100.0),
        batch_size=1000,
    )

    theta = np.deg2rad(270.0 - 270.0)
    rx_rot = receptors_x[0] * np.cos(theta) + receptors_y[0] * np.sin(theta)
    ry_rot = -receptors_x[0] * np.sin(theta) + receptors_y[0] * np.cos(theta)
    sx_rot = sources[0, 0, 0] * np.cos(theta) + sources[0, 0, 1] * np.sin(theta)
    sy_rot = -sources[0, 0, 0] * np.sin(theta) + sources[0, 0, 1] * np.cos(theta)
    x_hat = rx_rot - sx_rot
    y_hat = ry_rot - sy_rot
    rel_wind_deg = (270.0 - 45.0) % 360
    expected_features = np.array(
        [[
            x_hat,
            y_hat,
            np.sin(np.deg2rad(rel_wind_deg)),
            np.cos(np.deg2rad(rel_wind_deg)),
            100.0,
            800.0,
            -500.0,
            3.0,
        ]]
    )

    assert len(capturing_model.calls) == 1
    assert capturing_model.calls[0] == pytest.approx(expected_features)
    assert list(result.columns) == ["Date", "Receptor_ID", "Receptor_X", "Receptor_Y", "Conc"]
    assert result.iloc[0]["Conc"] == pytest.approx(1000.0)


def test_calculator_end_to_end_smoke(minimal_dispersion_scenario, monkeypatch):
    monkeypatch.setattr(dispersion, "load_all_models", lambda *args, **kwargs: _build_mock_models(1.0))

    calculator = dispersion.DispersionCalculator(config=_build_smoke_config())
    result = calculator.calculate(
        roads_gdf=minimal_dispersion_scenario["roads_gdf"],
        emissions_df=minimal_dispersion_scenario["emissions_df"],
        met_input=minimal_dispersion_scenario["met_df"],
        pollutant="NOx",
    )

    assert result["status"] == "success"
    assert result["data"]["results"]
    first_result = result["data"]["results"][0]
    assert {"lon", "lat", "mean_conc", "max_conc"}.issubset(first_result.keys())
    assert 120.0 < first_result["lon"] < 123.0
    assert 30.0 < first_result["lat"] < 33.0
    assert "receptors" in result["data"]["concentration_grid"]
    assert "bounds" in result["data"]["concentration_grid"]
    assert {
        "receptor_count",
        "time_steps",
        "mean_concentration",
        "max_concentration",
        "unit",
        "coordinate_system",
    }.issubset(result["data"]["summary"].keys())


def test_adapter_to_calculator_pipeline(monkeypatch):
    monkeypatch.setattr(dispersion, "load_all_models", lambda *args, **kwargs: _build_mock_models(1.0))

    roads_gdf, emissions_df = EmissionToDispersionAdapter.adapt(_build_minimal_macro_result())
    calculator = dispersion.DispersionCalculator(config=_build_smoke_config())
    result = calculator.calculate(
        roads_gdf=roads_gdf,
        emissions_df=emissions_df,
        met_input={
            "wind_speed_mps": 3.0,
            "wind_direction_deg": 270.0,
            "mixing_height_m": 800.0,
            "monin_obukhov_length": -500.0,
            "stability_class": "U",
            "temperature_k": 290.0,
        },
        pollutant="NOx",
    )

    assert result["status"] == "success"
    assert result["data"]["results"]
    assert result["data"]["query_info"]["n_roads"] == 2
    assert result["data"]["summary"]["receptor_count"] > 0
