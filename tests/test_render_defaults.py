"""Regression tests for deterministic single-tool rendering with defaults metadata."""

from __future__ import annotations

from core.router_render_utils import render_single_tool_success
from core.router_synthesis_utils import maybe_short_circuit_synthesis


def _make_macro_result(*, defaults_used=None, with_geometry: bool = True):
    result = {
        "success": True,
        "summary": "宏观计算完成",
        "data": {
            "query_info": {
                "links_count": 20,
                "model_year": 2020,
                "season": "夏季",
                "pollutants": ["CO2", "NOx"],
            },
            "summary": {
                "total_links": 20,
                "total_emissions_kg_per_hr": {
                    "CO2": 1134.8827,
                    "NOx": 0.2396,
                },
            },
            "results": [
                {
                    "link_id": "L1",
                    "geometry": "LINESTRING (0 0, 1 1)" if with_geometry else None,
                }
            ],
        },
    }
    if defaults_used is not None:
        result["data"]["defaults_used"] = defaults_used
    return result


def _make_dispersion_result(*, defaults_used=None):
    result = {
        "success": True,
        "summary": "扩散计算完成",
        "data": {
            "query_info": {
                "pollutant": "NOx",
                "n_receptors": 15,
                "n_time_steps": 1,
                "roughness_height": 0.5,
            },
            "summary": {
                "receptor_count": 15,
                "time_steps": 1,
                "mean_concentration": 1.2,
                "max_concentration": 2.9,
                "unit": "μg/m³",
            },
            "meteorology_used": {
                "_source_mode": "preset_override",
                "_preset_name": "urban_summer_day",
                "_overrides": {
                    "wind_speed": {"from": 3.0, "to": 4.0},
                },
                "wind_speed": 4.0,
                "wind_direction": 180.0,
                "stability_class": "N1",
                "mixing_height": 900.0,
            },
            "coverage_assessment": {
                "level": "sparse_local",
                "result_semantics": "局部热点贡献识别",
                "warnings": ["路段数量较少（3条），扩散浓度不具有区域代表性"],
            },
            "raster_grid": {
                "resolution_m": 50,
                "rows": 12,
                "cols": 10,
            },
        },
    }
    if defaults_used is not None:
        result["data"]["defaults_used"] = defaults_used
    return result


def _make_hotspot_result():
    return {
        "success": True,
        "summary": "热点识别完成",
        "data": {
            "interpretation": "局部热点贡献识别：仅对已上传道路范围内的高浓度区域进行解释",
            "hotspot_count": 2,
            "summary": {
                "max_concentration": 6.0,
                "total_hotspot_area_m2": 7500.0,
            },
            "hotspots": [
                {
                    "rank": 1,
                    "max_conc": 6.0,
                    "area_m2": 5000.0,
                    "contributing_roads": [
                        {"link_id": "road_A", "contribution_pct": 60.0},
                    ],
                },
                {
                    "rank": 2,
                    "max_conc": 5.4,
                    "area_m2": 2500.0,
                    "contributing_roads": [
                        {"link_id": "road_B", "contribution_pct": 35.0},
                    ],
                },
            ],
            "coverage_assessment": {
                "warnings": ["路网存在空间断裂，建议补充缺失区域的道路数据"],
            },
        },
    }


class TestDefaultsRendering:
    def test_macro_emission_render_includes_defaults(self):
        result = _make_macro_result(
            defaults_used={
                "fleet_mix": {"Passenger Car": 70.0, "Transit Bus": 3.0},
                "model_year": 2020,
                "season": "夏季",
                "pollutants": ["CO2", "NOx"],
            }
        )

        rendered = render_single_tool_success("calculate_macro_emission", result)

        assert "以下参数使用了系统默认值" in rendered
        assert "车队组成: 默认配置（Passenger Car 为主）" in rendered
        assert "模型年份: 2020" in rendered
        assert '如需修改可告诉我"用 2015 年的排放因子"' in rendered
        assert "污染物: CO2, NOx" in rendered

    def test_macro_emission_render_no_defaults_when_all_specified(self):
        rendered = render_single_tool_success(
            "calculate_macro_emission",
            _make_macro_result(defaults_used=None),
        )

        assert "以下参数使用了系统默认值" not in rendered

    def test_dispersion_render_includes_meteorology_used(self):
        rendered = render_single_tool_success(
            "calculate_dispersion",
            _make_dispersion_result(defaults_used={"grid_resolution": 50}),
        )

        assert rendered.startswith("## 扩散计算结果")
        assert "气象条件来源: 预设 urban_summer_day（含覆盖）" in rendered
        assert "气象覆盖参数: wind_speed: 3→4" in rendered
        assert "路段数量较少（3条），扩散浓度不具有区域代表性" in rendered
        assert "网格分辨率: 50" in rendered

    def test_hotspot_render_includes_interpretation_and_top_summary(self):
        rendered = render_single_tool_success("analyze_hotspots", _make_hotspot_result())

        assert rendered.startswith("## 热点分析结果")
        assert "局部热点贡献识别" in rendered
        assert "热点数量: 2" in rendered
        assert "主要贡献路段 road_A（60.0%）" in rendered

    def test_render_includes_next_step_suggestions(self):
        macro_rendered = render_single_tool_success(
            "calculate_macro_emission",
            _make_macro_result(defaults_used={"model_year": 2020}),
        )
        dispersion_rendered = render_single_tool_success(
            "calculate_dispersion",
            _make_dispersion_result(defaults_used={"meteorology": "urban_summer_day"}),
        )
        hotspot_rendered = render_single_tool_success("analyze_hotspots", _make_hotspot_result())

        assert "帮我可视化排放分布" in macro_rendered
        assert "帮我做扩散分析" in macro_rendered
        assert "帮我识别污染热点" in dispersion_rendered
        assert "在地图上展示浓度分布" in dispersion_rendered
        assert "在地图上展示热点" in hotspot_rendered

    def test_defaults_used_dict_format(self):
        rendered = render_single_tool_success(
            "calculate_macro_emission",
            _make_macro_result(defaults_used={"season": "冬季"}),
        )

        assert "季节: 冬季" in rendered
        assert '如需修改可说"用冬季条件"' in rendered

    def test_defaults_used_list_format(self):
        result = _make_macro_result(
            defaults_used=[
                {
                    "parameter": "model_year",
                    "value": 2018,
                    "how_to_customize": '如需修改可告诉我"用 2015 年的排放因子"',
                },
                {
                    "parameter": "pollutants",
                    "value": ["CO2", "PM2.5"],
                    "how_to_customize": '如需添加可说"加上 PM2.5"',
                },
            ]
        )

        rendered = render_single_tool_success("calculate_macro_emission", result)

        assert "模型年份: 2018" in rendered
        assert "污染物: CO2, PM2.5" in rendered


def test_single_tool_short_circuit_uses_friendly_render_for_dispersion_and_hotspots():
    dispersion_text = maybe_short_circuit_synthesis(
        [{"name": "calculate_dispersion", "result": _make_dispersion_result(defaults_used={"pollutant": "NOx"})}]
    )
    hotspot_text = maybe_short_circuit_synthesis(
        [{"name": "analyze_hotspots", "result": _make_hotspot_result()}]
    )

    assert dispersion_text.startswith("## 扩散计算结果")
    assert "气象条件来源" in dispersion_text
    assert hotspot_text.startswith("## 热点分析结果")
    assert "热点摘要" in hotspot_text
