"""Tests for per-road contribution tracking in predict_time_series_xgb."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString

from calculators import dispersion


class ConstantModel:
    def __init__(self, value: float):
        self.value = float(value)

    def predict(self, features):
        if hasattr(features, "num_row"):
            size = features.num_row()
        else:
            size = len(features)
        return np.full(size, self.value, dtype=float)


class DistanceDecayModel:
    def predict(self, features):
        if hasattr(features, "get_data"):
            data = np.asarray(features.get_data())
        else:
            data = np.asarray(features, dtype=float)
        return 1.0 / (1.0 + np.abs(data[:, 0]) + np.abs(data[:, 1]))


def _build_models(model):
    return {key: {"pos": model, "neg": model} for key in ["VS", "S", "N1", "N2", "U", "VU"]}


def _build_met_df():
    return pd.DataFrame(
        {
            "Date": [2024070112],
            "WSPD": [2.5],
            "WDIR": [270.0],
            "MixHGT_C": [800.0],
            "L": [-300.0],
            "H": [100.0],
            "Stab_Class": ["U"],
        }
    )


def _build_sources():
    return np.array(
        [
            [
                [0.0, 0.0, 1e-6, 90.0],
                [100.0, 0.0, 2e-6, 90.0],
            ]
        ],
        dtype=float,
    )


def _build_roads_gdf():
    return gpd.GeoDataFrame(
        {
            "NAME_1": ["R1", "R2", "R3"],
            "width": [7.0, 7.0, 7.0],
            "geometry": [
                LineString([(121.4000, 31.2000), (121.4010, 31.2000)]),
                LineString([(121.4000, 31.2005), (121.4010, 31.2005)]),
                LineString([(121.4000, 31.2010), (121.4010, 31.2010)]),
            ],
        },
        geometry="geometry",
        crs="EPSG:4326",
    )


def _build_emissions_df():
    return pd.DataFrame(
        {
            "NAME_1": ["R1", "R2", "R3"],
            "data_time": [pd.Timestamp("2024-07-01 12:00:00")] * 3,
            "nox": [1.0, 1.0, 1.0],
            "length": [0.1, 0.1, 0.1],
        }
    )


class TestRoadContributions:
    def test_contributions_disabled_by_default(self):
        """When track_road_contributions=False, returns DataFrame only."""
        result = dispersion.predict_time_series_xgb(
            models=_build_models(ConstantModel(1.0)),
            receptors_x=np.array([10.0, 20.0]),
            receptors_y=np.array([0.0, 0.0]),
            sources=_build_sources(),
            met=_build_met_df(),
        )

        assert isinstance(result, pd.DataFrame)

    def test_contributions_enabled(self):
        """When track_road_contributions=True, returns (DataFrame, dict)."""
        result = dispersion.predict_time_series_xgb(
            models=_build_models(ConstantModel(1.0)),
            receptors_x=np.array([10.0, 20.0]),
            receptors_y=np.array([0.0, 0.0]),
            sources=_build_sources(),
            met=_build_met_df(),
            track_road_contributions=True,
            segment_to_road_map=np.array([0, 1]),
        )

        assert isinstance(result, tuple)
        conc_df, road_contributions = result
        assert isinstance(conc_df, pd.DataFrame)
        assert set(road_contributions) >= {
            "receptor_top_roads",
            "top_k",
            "effective_timesteps",
            "tracking_mode",
        }

    def test_contributions_sum_matches_total(self):
        """Sum of road contributions ~= total concentration for each receptor."""
        conc_df, road_contributions = dispersion.predict_time_series_xgb(
            models=_build_models(ConstantModel(1.0)),
            receptors_x=np.array([10.0, 20.0]),
            receptors_y=np.array([0.0, 0.0]),
            sources=_build_sources(),
            met=_build_met_df(),
            track_road_contributions=True,
            segment_to_road_map=np.array([0, 1]),
        )

        totals = conc_df.groupby("Receptor_ID")["Conc"].first().to_dict()
        for receptor_idx, expected_total in totals.items():
            actual_total = sum(value for _, value in road_contributions["receptor_top_roads"][receptor_idx])
            assert actual_total == pytest.approx(expected_total)

    def test_segment_to_road_map(self):
        """Segment-to-road mapping is consistent with segmentation."""
        calculator = dispersion.DispersionCalculator(
            config=dispersion.DispersionConfig(segment_interval_m=50.0)
        )
        merged = calculator._merge_roads_and_emissions(_build_roads_gdf(), _build_emissions_df(), "NOx")
        transformed, _ = calculator._transform_to_local(merged)
        segments_df = calculator._segment_roads(transformed)

        assert len(segments_df) > 0
        assert len(segments_df["road_idx"]) == len(segments_df)
        assert set(segments_df["road_idx"]) == {0, 1, 2}
        assert segments_df.groupby("NAME_1")["road_idx"].nunique().eq(1).all()

    def test_contributions_with_multiple_roads(self):
        """Multiple roads produce different contribution patterns."""
        conc_df, road_contributions = dispersion.predict_time_series_xgb(
            models=_build_models(DistanceDecayModel()),
            receptors_x=np.array([10.0, 190.0]),
            receptors_y=np.array([0.0, 0.0]),
            sources=np.array([[[0.0, 0.0, 1e-6, 90.0], [200.0, 0.0, 1e-6, 90.0]]], dtype=float),
            met=_build_met_df(),
            track_road_contributions=True,
            segment_to_road_map=np.array([0, 1]),
        )

        assert not conc_df.empty
        receptor_0_top = road_contributions["receptor_top_roads"][0][0][0]
        receptor_1_top = road_contributions["receptor_top_roads"][1][0][0]
        assert receptor_0_top == 0
        assert receptor_1_top == 1
