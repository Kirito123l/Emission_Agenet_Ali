"""Tests for dispersion contour-band generation."""

from __future__ import annotations

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from calculators import dispersion
from calculators.hotspot_analyzer import HotspotAnalyzer
from config import reset_config
from tools.definitions import TOOL_DEFINITIONS
from tools.dispersion import DispersionTool


class ConstantModel:
    """Simple deterministic surrogate stand-in."""

    def __init__(self, value: float):
        self.value = float(value)

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


def _origin() -> tuple[float, float]:
    origin_x, origin_y = dispersion.convert_coords(121.4, 31.2, "EPSG:4326", 51, "north")
    return float(origin_x), float(origin_y)


def _gaussian_field(
    nx: int = 11,
    ny: int = 11,
    spacing: float = 25.0,
    amplitude: float = 2.5,
    sigma: float = 90.0,
) -> tuple[np.ndarray, np.ndarray]:
    x_values = np.linspace(0.0, spacing * (nx - 1), nx)
    y_values = np.linspace(0.0, spacing * (ny - 1), ny)
    grid_x, grid_y = np.meshgrid(x_values, y_values)
    center_x = float(np.mean(x_values))
    center_y = float(np.mean(y_values))
    distances = (grid_x - center_x) ** 2 + (grid_y - center_y) ** 2
    concentrations = amplitude * np.exp(-(distances / (2.0 * sigma * sigma)))
    coords = np.column_stack((grid_x.ravel(), grid_y.ravel()))
    return coords, concentrations.ravel()


def _flatten_geojson_coords(geometry: dict) -> list[tuple[float, float]]:
    coords: list[tuple[float, float]] = []
    geometry_type = geometry.get("type")
    geometry_coords = geometry.get("coordinates", [])

    if geometry_type == "Polygon":
        for ring in geometry_coords:
            for lon, lat in ring:
                coords.append((float(lon), float(lat)))
    elif geometry_type == "MultiPolygon":
        for polygon in geometry_coords:
            for ring in polygon:
                for lon, lat in ring:
                    coords.append((float(lon), float(lat)))
    return coords


def _build_assembled_result(*, contour_enabled: bool) -> dict:
    calculator = dispersion.DispersionCalculator(
        config=dispersion.DispersionConfig(
            contour_enabled=contour_enabled,
            contour_interp_resolution_m=10.0,
            contour_n_levels=6,
            contour_smooth_sigma=0.0,
        )
    )
    calculator._matched_road_count = 2
    calculator._met_source_used = "preset"

    receptors_df = pd.DataFrame({"x": [0.0, 10.0, 80.0, 90.0], "y": [0.0, 0.0, 80.0, 80.0]})
    conc_df = pd.DataFrame(
        {
            "Date": [2024070112, 2024070112, 2024070112, 2024070112],
            "Receptor_ID": [0, 1, 2, 3],
            "Receptor_X": [0.0, 10.0, 80.0, 90.0],
            "Receptor_Y": [0.0, 0.0, 80.0, 80.0],
            "Conc": [0.4, 0.8, 1.2, 1.6],
        }
    )
    return calculator._assemble_result(
        conc_df=conc_df,
        receptors_df=receptors_df,
        lons=np.array([121.4, 121.4001, 121.4010, 121.4011]),
        lats=np.array([31.2, 31.20005, 31.2010, 31.20105]),
        met_df=pd.DataFrame(
            {
                "Date": [2024070112],
                "WSPD": [2.5],
                "WDIR": [270.0],
                "MixHGT_C": [800.0],
                "L": [-300.0],
                "H": [100.0],
                "Stab_Class": ["U"],
            }
        ),
        pollutant="NOx",
        origin=(100.0, 200.0),
    )


def _build_macro_result() -> dict:
    return {
        "status": "success",
        "data": {
            "results": [
                {
                    "link_id": "R1",
                    "link_length_km": 1.0,
                    "data_time": "2024-07-01 12:00:00",
                    "total_emissions_kg_per_hr": {"NOx": 1.5},
                    "geometry": "LINESTRING (121.4 31.2, 121.401 31.2)",
                },
                {
                    "link_id": "R2",
                    "link_length_km": 1.2,
                    "data_time": "2024-07-01 12:00:00",
                    "total_emissions_kg_per_hr": {"NOx": 2.5},
                    "geometry": "LINESTRING (121.4002 31.2003, 121.4012 31.2003)",
                },
            ]
        },
    }


@pytest.fixture(autouse=True)
def _reset_runtime_config():
    reset_config()
    yield
    reset_config()


class TestContourBands:
    def test_generate_contour_bands_basic(self):
        coords, concentrations = _gaussian_field()
        calculator = dispersion.DispersionCalculator(
            config=dispersion.DispersionConfig(
                contour_enabled=True,
                contour_interp_resolution_m=10.0,
                contour_n_levels=6,
                contour_smooth_sigma=0.0,
            )
        )

        result = calculator._generate_contour_bands(
            receptor_local_coords=coords,
            receptor_concentrations=concentrations,
            origin=_origin(),
            interp_resolution_m=10.0,
            n_levels=6,
            smooth_sigma=0.0,
        )

        assert result["geojson"]["type"] == "FeatureCollection"
        assert len(result["geojson"]["features"]) == 6
        assert result["levels"] == sorted(result["levels"])
        for feature in result["geojson"]["features"]:
            assert feature["geometry"]["type"] in {"Polygon", "MultiPolygon"}
            assert feature["properties"]["level_min"] < feature["properties"]["level_max"]

    def test_contour_wgs84_bbox_contains_all_vertices(self):
        coords, concentrations = _gaussian_field()
        calculator = dispersion.DispersionCalculator(
            config=dispersion.DispersionConfig(
                contour_enabled=True,
                contour_interp_resolution_m=10.0,
                contour_n_levels=6,
                contour_smooth_sigma=0.0,
            )
        )
        result = calculator._generate_contour_bands(
            receptor_local_coords=coords,
            receptor_concentrations=concentrations,
            origin=_origin(),
            interp_resolution_m=10.0,
            n_levels=6,
            smooth_sigma=0.0,
        )

        min_lon, min_lat, max_lon, max_lat = result["bbox_wgs84"]
        assert -180.0 <= min_lon <= 180.0
        assert -90.0 <= min_lat <= 90.0
        assert -180.0 <= max_lon <= 180.0
        assert -90.0 <= max_lat <= 90.0
        assert min_lon < max_lon
        assert min_lat < max_lat

        for feature in result["geojson"]["features"]:
            for lon, lat in _flatten_geojson_coords(feature["geometry"]):
                assert min_lon - 1e-9 <= lon <= max_lon + 1e-9
                assert min_lat - 1e-9 <= lat <= max_lat + 1e-9

    def test_all_zero_concentrations_return_empty_features(self):
        coords, concentrations = _gaussian_field()
        calculator = dispersion.DispersionCalculator(
            config=dispersion.DispersionConfig(contour_enabled=True)
        )
        result = calculator._generate_contour_bands(
            receptor_local_coords=coords,
            receptor_concentrations=np.zeros_like(concentrations),
            origin=_origin(),
        )

        assert result["geojson"]["features"] == []
        assert result["n_receptors_used"] == 0

    def test_single_receptor_gracefully_returns_error(self):
        calculator = dispersion.DispersionCalculator(
            config=dispersion.DispersionConfig(contour_enabled=True)
        )
        result = calculator._generate_contour_bands(
            receptor_local_coords=np.array([[10.0, 20.0]], dtype=float),
            receptor_concentrations=np.array([1.0], dtype=float),
            origin=_origin(),
        )

        assert "error" in result
        assert result["geojson"]["features"] == []

    def test_sparse_points_degrade_to_nearest_interpolation(self):
        calculator = dispersion.DispersionCalculator(
            config=dispersion.DispersionConfig(
                contour_enabled=True,
                contour_interp_resolution_m=20.0,
                contour_n_levels=4,
                contour_smooth_sigma=0.0,
            )
        )
        coords = np.array(
            [
                [0.0, 0.0],
                [0.0, 80.0],
                [80.0, 0.0],
                [80.0, 80.0],
                [40.0, 40.0],
            ],
            dtype=float,
        )
        concentrations = np.array([0.2, 0.4, 0.6, 0.8, 1.0], dtype=float)

        result = calculator._generate_contour_bands(
            receptor_local_coords=coords,
            receptor_concentrations=concentrations,
            origin=_origin(),
            interp_resolution_m=20.0,
            n_levels=4,
            smooth_sigma=0.0,
        )

        assert result["geojson"]["features"]
        assert {
            feature["properties"]["interp_method"]
            for feature in result["geojson"]["features"]
        } == {"nearest"}

    def test_raster_grid_structure_unchanged_and_hotspot_still_works(self):
        result = _build_assembled_result(contour_enabled=True)
        raster = result["data"]["raster_grid"]

        assert set(raster.keys()) == {
            "matrix_mean",
            "matrix_max",
            "bbox_local",
            "bbox_wgs84",
            "resolution_m",
            "rows",
            "cols",
            "nodata",
            "cell_receptor_map",
            "cell_centers_wgs84",
            "stats",
        }
        assert "contour_bands" in result["data"]

        analyzer = HotspotAnalyzer()
        hotspot_result = analyzer.analyze(raster_grid=deepcopy(raster))
        assert hotspot_result["status"] == "success"

    def test_disable_contour_output_omits_contour_bands(self):
        disabled_result = _build_assembled_result(contour_enabled=False)
        enabled_result = _build_assembled_result(contour_enabled=True)

        assert "contour_bands" not in disabled_result["data"]
        assert "contour_bands" in enabled_result["data"]

    def test_tool_contract_exposes_contour_resolution_parameter(self):
        dispersion_schema = next(
            item for item in TOOL_DEFINITIONS if item["function"]["name"] == "calculate_dispersion"
        )
        properties = dispersion_schema["function"]["parameters"]["properties"]
        assert "contour_resolution" in properties


class TestContourToolIntegration:
    @pytest.mark.anyio
    async def test_dispersion_tool_returns_contour_bands(self, monkeypatch):
        monkeypatch.setattr(dispersion, "load_all_models", lambda *args, **kwargs: _build_mock_models())
        tool = DispersionTool()

        result = await tool.execute(
            _last_result=deepcopy(_build_macro_result()),
            meteorology="urban_summer_day",
            pollutant="NOx",
            contour_resolution=20.0,
        )

        assert result.success is True
        assert "contour_bands" in result.data
        assert "contour_bands" in result.map_data
        assert result.data["query_info"]["contour_interp_resolution_m"] == pytest.approx(20.0)
        assert result.data["contour_bands"]["interp_resolution_m"] == pytest.approx(20.0)

    @pytest.mark.anyio
    async def test_enable_contour_output_flag_controls_tool_result(self, monkeypatch):
        monkeypatch.setattr(dispersion, "load_all_models", lambda *args, **kwargs: _build_mock_models())
        monkeypatch.setenv("ENABLE_CONTOUR_OUTPUT", "false")
        reset_config()

        tool = DispersionTool()
        result = await tool.execute(
            _last_result=deepcopy(_build_macro_result()),
            meteorology="urban_summer_day",
            pollutant="NOx",
        )

        assert result.success is True
        assert "contour_bands" not in result.data
        assert "contour_bands" not in result.map_data
