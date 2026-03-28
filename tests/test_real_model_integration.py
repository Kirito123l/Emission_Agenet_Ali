"""Real-model integration tests for the dispersion pipeline."""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import time
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from calculators.dispersion import DispersionCalculator, DispersionConfig, load_all_models
from calculators.dispersion_adapter import EmissionToDispersionAdapter
from calculators.macro_emission import MacroEmissionCalculator
from tools.spatial_renderer import SpatialRendererTool


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = PROJECT_ROOT / "ps-xgb-aermod-rline-surrogate" / "models"
TEST_DATA_DIR = PROJECT_ROOT / "test_data"
TEST_20LINKS = TEST_DATA_DIR / "test_20links.xlsx"
TEST_6LINKS = TEST_DATA_DIR / "test_6links.xlsx"

REAL_MODELS_AVAILABLE = (MODELS_DIR / "model_z=0.5").is_dir()
REAL_DATA_AVAILABLE = TEST_20LINKS.is_file()
SKLEARN_AVAILABLE = importlib.util.find_spec("sklearn") is not None

skip_no_models = pytest.mark.skipif(
    not REAL_MODELS_AVAILABLE,
    reason="Real surrogate model files not available",
)

skip_no_data = pytest.mark.skipif(
    not REAL_DATA_AVAILABLE,
    reason="test_20links.xlsx not available",
)

skip_no_sklearn = pytest.mark.skipif(
    not SKLEARN_AVAILABLE,
    reason="scikit-learn not available for XGBoost sklearn model loading",
)


_PREPARED_INPUT_CACHE: dict[str, tuple[dict[str, Any], Any, pd.DataFrame]] = {}
_CALCULATOR_CACHE: dict[float, DispersionCalculator] = {}


def _load_links_data(excel_path: Path) -> list[dict[str, Any]]:
    df = pd.read_excel(excel_path)
    links_data: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        link = {
            "link_id": str(row.get("link_id", "")),
            "link_length_km": float(row.get("length", 0.0)),
            "traffic_flow_vph": float(row.get("flow", 0.0)),
            "avg_speed_kph": float(row.get("speed", 0.0)),
        }
        geometry = row.get("geometry", "")
        if geometry:
            link["geometry"] = str(geometry)
        links_data.append(link)
    return links_data


def _merge_geometry_back(
    macro_result: dict[str, Any],
    links_data: list[dict[str, Any]],
) -> dict[str, Any]:
    merged = copy.deepcopy(macro_result)
    geometry_by_id = {
        str(link.get("link_id", "")): link["geometry"]
        for link in links_data
        if link.get("geometry")
    }
    for result_row in merged.get("data", {}).get("results", []):
        link_id = str(result_row.get("link_id", ""))
        if "geometry" not in result_row and link_id in geometry_by_id:
            result_row["geometry"] = geometry_by_id[link_id]
    return merged


def _prepare_dispersion_inputs(excel_path: Path):
    cache_key = str(excel_path.resolve())
    cached = _PREPARED_INPUT_CACHE.get(cache_key)
    if cached is not None:
        macro_result, roads_gdf, emissions_df = cached
        return copy.deepcopy(macro_result), roads_gdf.copy(), emissions_df.copy()

    links_data = _load_links_data(excel_path)
    macro_calc = MacroEmissionCalculator()
    macro_result = macro_calc.calculate(
        links_data=links_data,
        pollutants=["NOx"],
        model_year=2020,
        season="夏季",
        default_fleet_mix=None,
    )
    if macro_result.get("status") != "success":
        raise AssertionError(f"Macro emission failed during test setup: {macro_result}")

    macro_with_geometry = _merge_geometry_back(macro_result, links_data)
    adapter_input = {"status": "success", "data": macro_with_geometry["data"]}
    roads_gdf, emissions_df = EmissionToDispersionAdapter.adapt(adapter_input)

    _PREPARED_INPUT_CACHE[cache_key] = (
        copy.deepcopy(macro_with_geometry),
        roads_gdf.copy(),
        emissions_df.copy(),
    )
    return copy.deepcopy(macro_with_geometry), roads_gdf.copy(), emissions_df.copy()


def _get_cached_calculator(roughness: float) -> DispersionCalculator:
    calculator = _CALCULATOR_CACHE.get(roughness)
    if calculator is None:
        calculator = DispersionCalculator(
            DispersionConfig(
                roughness_height=roughness,
                model_base_dir=str(MODELS_DIR),
            )
        )
        _CALCULATOR_CACHE[roughness] = calculator
    return calculator


def _create_fresh_calculator(roughness: float) -> DispersionCalculator:
    return DispersionCalculator(
        DispersionConfig(
            roughness_height=roughness,
            model_base_dir=str(MODELS_DIR),
        )
    )


def _run_real_dispersion(
    excel_path: Path,
    met_input: Any,
    roughness: float = 0.5,
    fresh_calculator: bool = False,
):
    _, roads_gdf, emissions_df = _prepare_dispersion_inputs(excel_path)
    calculator = (
        _create_fresh_calculator(roughness)
        if fresh_calculator
        else _get_cached_calculator(roughness)
    )
    return calculator.calculate(
        roads_gdf=roads_gdf.copy(),
        emissions_df=emissions_df.copy(),
        met_input=met_input,
        pollutant="NOx",
    )


def _model_feature_dimensions(model: Any) -> int | None:
    if hasattr(model, "get_booster"):
        return int(model.get_booster().num_features())
    if hasattr(model, "num_features"):
        return int(model.num_features())
    if hasattr(model, "n_features_in_"):
        return int(model.n_features_in_)
    return None


@skip_no_models
@skip_no_sklearn
def test_load_all_real_models():
    """加载全部 36 个真实模型文件，验证每个都能成功加载。"""
    total_loaded = 0
    for roughness in [0.05, 0.5, 1.0]:
        models = load_all_models(str(MODELS_DIR), roughness)
        assert len(models) == 6, f"roughness={roughness}: expected 6 stability classes, got {len(models)}"
        per_roughness = 0
        for stab, sides in models.items():
            assert "x0" in sides or "pos" in sides, f"Missing positive model for {stab}"
            assert "x-1" in sides or "neg" in sides, f"Missing negative model for {stab}"
            per_roughness += len(sides)
        total_loaded += per_roughness
        print(
            f"REAL_MODELS roughness={roughness} stability_classes={len(models)} "
            f"directional_models={per_roughness}"
        )

    assert total_loaded == 36
    print(f"REAL_MODELS total_loaded={total_loaded} models_dir={MODELS_DIR}")


@skip_no_models
@skip_no_sklearn
def test_model_feature_dimensions():
    """验证模型特征维度与 predict_time_series_xgb 的期望一致。"""
    models = load_all_models(str(MODELS_DIR), 0.5)
    no_hc_classes = {"VS", "S", "N1"}
    hc_classes = {"N2", "U", "VU"}

    for stab, sides in models.items():
        for side_key, model in sides.items():
            n_features = _model_feature_dimensions(model)
            assert n_features is not None, f"Could not determine feature count for {stab}/{side_key}"

            if stab in no_hc_classes:
                assert n_features == 7, f"{stab}/{side_key}: expected 7 features, got {n_features}"
            elif stab in hc_classes:
                assert n_features == 8, f"{stab}/{side_key}: expected 8 features, got {n_features}"

            print(f"MODEL_DIM stability={stab} side={side_key} features={n_features}")


@skip_no_models
@skip_no_data
@skip_no_sklearn
def test_real_macro_to_dispersion_20links():
    """
    真实集成测试：test_20links.xlsx -> MacroEmissionCalculator -> Adapter -> DispersionCalculator。
    """
    macro_result, roads_gdf, emissions_df = _prepare_dispersion_inputs(TEST_20LINKS)

    assert macro_result["status"] == "success"
    assert len(macro_result["data"]["results"]) == 20
    assert not roads_gdf.empty
    assert not emissions_df.empty

    print(
        f"MACRO_CHAIN links={len(macro_result['data']['results'])} "
        f"roads={len(roads_gdf)} emissions={len(emissions_df)}"
    )

    result = _run_real_dispersion(TEST_20LINKS, "urban_summer_day", roughness=0.5, fresh_calculator=True)
    assert result["status"] == "success", f"Dispersion failed: {result.get('message', result)}"

    data = result["data"]
    assert "results" in data
    assert "summary" in data
    assert "concentration_grid" in data
    assert "query_info" in data
    assert len(data["results"]) > 0, "No receptor results"
    assert len(data["concentration_grid"]["receptors"]) > 0, "No concentration grid receptors"

    lon_values = [float(item["lon"]) for item in data["results"]]
    lat_values = [float(item["lat"]) for item in data["results"]]
    for receptor in data["results"][:5]:
        assert 120 < receptor["lon"] < 123, f"lon out of range: {receptor['lon']}"
        assert 30 < receptor["lat"] < 33, f"lat out of range: {receptor['lat']}"
        assert receptor["mean_conc"] >= 0, f"Negative concentration: {receptor['mean_conc']}"

    summary = data["summary"]
    assert summary["receptor_count"] > 0
    assert summary["mean_concentration"] >= 0
    assert summary["max_concentration"] >= summary["mean_concentration"]
    assert summary["unit"] == "μg/m³"

    print(
        "CHAIN_20LINKS "
        f"receptors={summary['receptor_count']} "
        f"time_steps={summary.get('time_steps', 'N/A')} "
        f"mean={summary['mean_concentration']:.6f} "
        f"max={summary['max_concentration']:.6f} "
        f"lon_range=({min(lon_values):.6f},{max(lon_values):.6f}) "
        f"lat_range=({min(lat_values):.6f},{max(lat_values):.6f})"
    )


@skip_no_models
@skip_no_data
@skip_no_sklearn
@pytest.mark.parametrize(
    "preset",
    [
        "urban_summer_day",
        "urban_summer_night",
        "urban_winter_day",
        "urban_winter_night",
        "windy_neutral",
        "calm_stable",
    ],
)
def test_real_dispersion_all_presets(preset: str):
    """用 6 个气象预设分别跑真实扩散，验证每个预设都能正常完成。"""
    if not TEST_6LINKS.is_file():
        pytest.skip("test_6links.xlsx not available")

    result = _run_real_dispersion(TEST_6LINKS, preset, roughness=0.5, fresh_calculator=False)
    assert result["status"] == "success", f"Preset {preset} failed: {result.get('message', result)}"
    assert len(result["data"]["results"]) > 0

    summary = result["data"]["summary"]
    print(
        f"PRESET preset={preset} receptors={summary['receptor_count']} "
        f"mean={summary['mean_concentration']:.6f} max={summary['max_concentration']:.6f}"
    )


@skip_no_models
@skip_no_data
@skip_no_sklearn
@pytest.mark.parametrize("roughness", [0.05, 0.5, 1.0])
def test_real_dispersion_all_roughness(roughness: float):
    """用 3 个粗糙度分别跑真实扩散，验证不同模型集都能正常工作。"""
    if not TEST_6LINKS.is_file():
        pytest.skip("test_6links.xlsx not available")

    result = _run_real_dispersion(
        TEST_6LINKS,
        "urban_summer_day",
        roughness=roughness,
        fresh_calculator=False,
    )
    assert result["status"] == "success", f"Roughness {roughness} failed: {result.get('message', result)}"

    summary = result["data"]["summary"]
    print(
        f"ROUGHNESS roughness={roughness} receptors={summary['receptor_count']} "
        f"mean={summary['mean_concentration']:.6f} max={summary['max_concentration']:.6f}"
    )


@skip_no_models
@skip_no_data
@skip_no_sklearn
def test_real_dispersion_result_to_spatial_renderer():
    """验证真实扩散结果能被 SpatialRendererTool 渲染为 raster map。"""
    result = _run_real_dispersion(TEST_6LINKS, "urban_summer_day", roughness=0.5, fresh_calculator=False)
    assert result["status"] == "success"

    renderer = SpatialRendererTool()
    render_result = asyncio.run(renderer.execute(data_source=result["data"]))

    assert render_result.success, f"Renderer failed: {render_result.error}"
    assert render_result.map_data is not None
    assert render_result.map_data.get("type") == "raster"

    features = render_result.map_data["layers"][0]["data"]["features"]
    assert len(features) > 0
    print(
        f"SPATIAL_RENDERER type={render_result.map_data.get('type')} "
        f"features={len(features)}"
    )


@skip_no_models
@skip_no_data
@skip_no_sklearn
def test_real_dispersion_performance_baseline():
    """
    记录真实扩散计算的性能基线。
    不做耗时阈值断言，只验证计算成功并打印结构化指标。
    """
    _, roads_gdf, emissions_df = _prepare_dispersion_inputs(TEST_20LINKS)
    disp_calc = _create_fresh_calculator(roughness=0.5)

    start = time.time()
    result = disp_calc.calculate(
        roads_gdf=roads_gdf,
        emissions_df=emissions_df,
        met_input="urban_summer_day",
        pollutant="NOx",
    )
    elapsed = time.time() - start

    assert result["status"] == "success"

    summary = result["data"]["summary"]
    print("\n============================================================")
    print("PERFORMANCE BASELINE (20 links, 1 time step, roughness=0.5)")
    print("============================================================")
    print(f"  Total time: {elapsed:.2f}s")
    print(f"  Receptors: {summary['receptor_count']}")
    print(f"  Mean conc: {summary['mean_concentration']:.6f} μg/m³")
    print(f"  Max conc: {summary['max_concentration']:.6f} μg/m³")
    print(f"  Time per receptor: {elapsed / max(summary['receptor_count'], 1) * 1000:.4f}ms")
    print("============================================================\n")
