from __future__ import annotations

from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString

from calculators.dispersion import predict_time_series_xgb
from tools.dispersion import DispersionTool


class ConstantModel:
    def __init__(self, value: float = 1.0):
        self.value = value

    def predict(self, features):
        return np.full(len(features), self.value, dtype=float)


def _models():
    return {"U": {"pos": ConstantModel(), "neg": ConstantModel()}}


def _met_df():
    return pd.DataFrame(
        {
            "Date": [2024010100],
            "WSPD": [2.5],
            "WDIR": [270.0],
            "MixHGT_C": [800.0],
            "L": [-300.0],
            "H": [100.0],
            "Stab_Class": ["U"],
        }
    )


def test_predict_time_series_guard_rejects_large_grid():
    result = predict_time_series_xgb(
        models={},
        receptors_x=np.zeros(10_000, dtype=float),
        receptors_y=np.zeros(10_000, dtype=float),
        sources=np.zeros((1, 20_000, 4), dtype=float),
        met=_met_df(),
    )

    assert result["status"] == "grid_too_large"
    assert result["error_code"] == "DISPERSION_GRID_TOO_LARGE"
    assert result["estimated_pairs"] == 200_000_000
    assert result["limit"] == 100_000_000


def test_predict_time_series_small_grid_still_runs():
    receptors_x = np.linspace(0.0, 50.0, 100)
    receptors_y = np.zeros(100, dtype=float)
    sources = np.zeros((1, 100, 4), dtype=float)
    sources[0, :, 0] = np.linspace(0.0, 50.0, 100)
    sources[0, :, 2] = 1e-6
    sources[0, :, 3] = 90.0

    result = predict_time_series_xgb(
        models=_models(),
        receptors_x=receptors_x,
        receptors_y=receptors_y,
        sources=sources,
        met=_met_df(),
    )

    assert isinstance(result, pd.DataFrame)
    assert not result.empty
    assert {"Date", "Receptor_ID", "Conc"}.issubset(result.columns)


def test_predict_time_series_guard_uses_environment_override(monkeypatch):
    monkeypatch.setenv("DISPERSION_PAIR_LIMIT", "1000")

    result = predict_time_series_xgb(
        models={},
        receptors_x=np.zeros(100, dtype=float),
        receptors_y=np.zeros(100, dtype=float),
        sources=np.zeros((1, 20, 4), dtype=float),
        met=_met_df(),
    )

    assert result["status"] == "grid_too_large"
    assert result["estimated_pairs"] == 2_000
    assert result["limit"] == 1_000


@pytest.mark.anyio
async def test_dispersion_tool_returns_grid_too_large_as_tool_failure(monkeypatch):
    tool = DispersionTool()
    roads_gdf = gpd.GeoDataFrame(
        {"NAME_1": ["R1"], "geometry": [LineString([(121.4, 31.2), (121.401, 31.2)])]},
        geometry="geometry",
        crs="EPSG:4326",
    )
    emissions_df = pd.DataFrame({"NAME_1": ["R1"], "nox": [1.0]})
    tool._adapter = SimpleNamespace(adapt=lambda emission_data, pollutant: (roads_gdf, emissions_df))
    tool._get_calculator = lambda roughness: SimpleNamespace(
        calculate=lambda **kwargs: {
            "status": "grid_too_large",
            "error_code": "DISPERSION_GRID_TOO_LARGE",
            "receptors": 202_154,
            "sources": 7_506,
            "estimated_pairs": 1_517_367_924,
            "limit": 100_000_000,
            "message": "Dispersion grid has 1,517,367,924 receptor-source pairs.",
        }
    )

    result = await tool.execute(
        _last_result={
            "success": True,
            "data": {
                "results": [
                    {
                        "link_id": "R1",
                        "link_length_km": 1.0,
                        "total_emissions_kg_per_hr": {"NOx": 1.0},
                        "geometry": "LINESTRING (121.4 31.2, 121.401 31.2)",
                    }
                ]
            },
        },
        meteorology="urban_summer_day",
        pollutant="NOx",
    )

    assert result.success is False
    assert result.data["error_code"] == "DISPERSION_GRID_TOO_LARGE"
    assert result.data["estimated_pairs"] == 1_517_367_924
    assert "receptor-source pairs" in result.error
