"""Helper functions extracted from ``core.router`` for synthesis-side rendering."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from core.capability_summary import get_capability_aware_follow_up


def _format_scalar(value: Any, precision: int = 4) -> str:
    """Render scalar values without noisy trailing zeros for simple metadata fields."""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.{precision}f}".rstrip("0").rstrip(".")
    if value is None:
        return "未知"
    return str(value)


def _format_default_value(value: Any) -> str:
    """Render default-value payloads, including compact fleet summaries."""
    if isinstance(value, list):
        return ", ".join(_format_default_value(item) for item in value)

    if isinstance(value, dict):
        numeric_items: list[tuple[str, float]] = []
        for key, item in value.items():
            if isinstance(item, (int, float)):
                numeric_items.append((str(key), float(item)))
        if numeric_items:
            dominant = max(numeric_items, key=lambda item: item[1])[0]
            return f"默认配置（{dominant} 为主）"

        preview = [f"{key}={_format_default_value(item)}" for key, item in list(value.items())[:3]]
        if len(value) > 3:
            preview.append("...")
        return ", ".join(preview)

    return _format_scalar(value, precision=2)


def _normalize_default_items(
    defaults_used: Any,
    *,
    preferred_order: list[str],
    label_map: Dict[str, str],
    customize_map: Dict[str, str],
) -> list[Dict[str, str]]:
    """Normalize defaults_used into render-ready rows for both dict and list payloads."""
    items: list[Dict[str, str]] = []

    if isinstance(defaults_used, dict):
        ordered_keys = [key for key in preferred_order if key in defaults_used]
        ordered_keys.extend(key for key in defaults_used if key not in ordered_keys)

        for key in ordered_keys:
            value = defaults_used.get(key)
            items.append(
                {
                    "label": label_map.get(key, str(key)),
                    "value": _format_default_value(value),
                    "how_to_customize": customize_map.get(key, ""),
                }
            )
        return items

    if isinstance(defaults_used, list):
        for entry in defaults_used:
            if not isinstance(entry, dict):
                continue
            raw_key = entry.get("parameter") or entry.get("name") or entry.get("key") or "默认参数"
            key = str(raw_key)
            value = entry.get("value", entry.get("default"))
            items.append(
                {
                    "label": label_map.get(key, key),
                    "value": _format_default_value(value),
                    "how_to_customize": str(
                        entry.get("how_to_customize")
                        or entry.get("how")
                        or customize_map.get(key, "")
                    ),
                }
            )
        return items

    return items


def _append_defaults_section(
    lines: list[str],
    defaults_used: Any,
    *,
    preferred_order: list[str],
    label_map: Dict[str, str],
    customize_map: Dict[str, str],
) -> None:
    """Append a defaults-used section when the tool surfaced default parameters."""
    items = _normalize_default_items(
        defaults_used,
        preferred_order=preferred_order,
        label_map=label_map,
        customize_map=customize_map,
    )
    if not items:
        return

    lines.extend(["", "**以下参数使用了系统默认值**"])
    for item in items:
        text = f"- {item['label']}: {item['value']}"
        how_to_customize = item.get("how_to_customize", "").strip()
        if how_to_customize:
            text += f"，{how_to_customize}"
        lines.append(text)


def _append_follow_up_section(lines: list[str], heading: str, suggestions: list[str]) -> None:
    """Append a simple follow-up section with suggested next steps."""
    if not suggestions:
        return

    lines.extend(["", f"**{heading}**"])
    for suggestion in suggestions:
        lines.append(f"- {suggestion}")


def _append_hint_section(lines: list[str], heading: str, hints: list[str]) -> None:
    """Append capability-boundary hints when some follow-up paths are unavailable."""
    if not hints:
        return

    lines.extend(["", f"**{heading}**"])
    for hint in hints:
        lines.append(f"- {hint}")


def _format_macro_overview(links_count: int, totals: Dict[str, Any]) -> str:
    """Build a one-line macro-emission summary sentence."""
    if not totals:
        return f"计算了 {links_count} 条路段的排放。"

    emission_parts = []
    for pollutant, value in totals.items():
        try:
            emission_parts.append(f"{pollutant} 排放 {float(value):.2f} kg/h")
        except (TypeError, ValueError):
            emission_parts.append(f"{pollutant} 排放 {_format_scalar(value)} kg/h")
    return f"计算了 {links_count} 条路段的排放，总 " + "，".join(emission_parts) + "。"


def _describe_meteorology_source(meteorology_used: Dict[str, Any]) -> str:
    """Describe where the meteorology configuration came from."""
    if not isinstance(meteorology_used, dict) or not meteorology_used:
        return "未知"

    source_mode = meteorology_used.get("_source_mode")
    preset_name = meteorology_used.get("_preset_name")
    if source_mode == "preset_override":
        return f"预设 {preset_name or '未知'}（含覆盖）"
    if source_mode == "preset":
        return f"预设 {preset_name or '未知'}"
    if source_mode == "custom":
        return "用户指定"
    if source_mode == "sfc_file":
        return f"SFC 文件: {meteorology_used.get('path', '未知')}"
    if preset_name:
        return f"预设 {preset_name}"
    return _format_scalar(source_mode)


def _format_meteorology_detail(meteorology_used: Dict[str, Any]) -> str:
    """Render concrete meteorology values for the result summary."""
    if not isinstance(meteorology_used, dict) or not meteorology_used:
        return "未知"

    parts = []
    if "wind_speed" in meteorology_used:
        parts.append(f"风速 {_format_scalar(meteorology_used['wind_speed'])} m/s")
    if "wind_direction" in meteorology_used:
        parts.append(f"风向 {_format_scalar(meteorology_used['wind_direction'])}°")
    if meteorology_used.get("stability_class"):
        parts.append(f"稳定度 {meteorology_used['stability_class']}")
    if "mixing_height" in meteorology_used:
        parts.append(f"混合层 {_format_scalar(meteorology_used['mixing_height'])} m")
    return "，".join(parts) or "未知"


def _format_meteorology_overrides(meteorology_used: Dict[str, Any]) -> str:
    """Render preset-override details when present."""
    if not isinstance(meteorology_used, dict):
        return ""

    overrides = meteorology_used.get("_overrides", {})
    if not isinstance(overrides, dict) or not overrides:
        return ""

    override_parts = []
    for key, change in overrides.items():
        if not isinstance(change, dict):
            continue
        override_parts.append(
            f"{key}: {_format_scalar(change.get('from'))}→{_format_scalar(change.get('to'))}"
        )
    return "，".join(override_parts)


def _format_hotspot_summary_line(hotspot: Dict[str, Any]) -> str:
    """Render one hotspot row for the friendly summary."""
    rank = int(hotspot.get("rank", hotspot.get("hotspot_id", 0)) or 0)
    area = float(hotspot.get("area_m2", 0.0))
    max_conc = float(hotspot.get("max_conc", 0.0))
    line = f"- 热点 #{rank}: 最大浓度 {max_conc:.4f} μg/m³，面积 {area:.0f} m²"

    roads = hotspot.get("contributing_roads", [])
    if isinstance(roads, list) and roads:
        top_road = roads[0]
        line += (
            f"，主要贡献路段 {top_road.get('link_id', '未知')}"
            f"（{float(top_road.get('contribution_pct', 0.0)):.1f}%）"
        )
    return line


def _render_spatial_map_result(result: Dict[str, Any]) -> str:
    """Render stable markdown for render_spatial_map outputs."""
    data = result.get("data", {})
    map_data = result.get("map_data")
    if not isinstance(map_data, dict):
        map_data = data.get("map_config", {})
    map_data = map_data if isinstance(map_data, dict) else {}

    map_type = str(map_data.get("type") or "unknown")
    summary = map_data.get("summary", {}) if isinstance(map_data.get("summary"), dict) else {}
    coverage = map_data.get("coverage_assessment", {}) if isinstance(map_data.get("coverage_assessment"), dict) else {}
    lines = ["## 空间渲染结果", ""]

    if map_type in {"macro_emission_map", "emission"}:
        title = map_data.get("title") or "路段排放地图"
        total_links = int(summary.get("total_links", len(map_data.get("links", []))) or 0)
        color_scale = map_data.get("color_scale", {}) if isinstance(map_data.get("color_scale"), dict) else {}
        unit = map_data.get("unit", "")
        value_min = color_scale.get("min")
        value_max = color_scale.get("max")

        lines.extend(
            [
                f"**{title}**",
                f"已渲染 {total_links} 条路段的排放分布。",
            ]
        )
        if value_min is not None and value_max is not None:
            lines.append(
                "排放强度范围: "
                f"{_format_scalar(value_min)} - {_format_scalar(value_max)} {unit}".rstrip()
            )

    elif map_type == "raster":
        title = map_data.get("title") or "浓度场地图"
        nonzero_cells = int(summary.get("nonzero_cells", 0) or 0)
        resolution = summary.get("resolution_m", 50)
        max_concentration = summary.get("max_concentration")
        unit = summary.get("unit", "μg/m³")

        lines.extend(
            [
                f"**{title}**",
                f"已渲染 {nonzero_cells} 个浓度栅格单元，分辨率 {_format_scalar(resolution)} m。",
            ]
        )
        if max_concentration is not None:
            lines.append(f"最大浓度 {_format_scalar(max_concentration)} {unit}")

    elif map_type == "contour":
        title = map_data.get("title") or "等值填色浓度场地图"
        n_levels = int(summary.get("n_levels", 0) or 0)
        resolution = summary.get("interp_resolution_m", 10)
        max_concentration = summary.get("max_concentration")
        unit = summary.get("unit", "μg/m³")

        lines.extend(
            [
                f"**{title}**",
                f"已渲染 {n_levels} 档连续等值填色区域，插值分辨率 {_format_scalar(resolution)} m。",
            ]
        )
        if max_concentration is not None:
            lines.append(f"最大浓度 {_format_scalar(max_concentration)} {unit}")

    elif map_type == "hotspot":
        title = map_data.get("title") or "热点分析地图"
        interpretation = str(map_data.get("interpretation") or "").strip()
        hotspots_detail = map_data.get("hotspots_detail", [])
        hotspot_count = len(hotspots_detail) if isinstance(hotspots_detail, list) else 0

        lines.append(f"**{title}**")
        if interpretation:
            lines.append(interpretation)
        if hotspot_count:
            lines.append(f"展示 {hotspot_count} 个热点区域。")
            top_hotspot = hotspots_detail[0] if isinstance(hotspots_detail[0], dict) else None
            if top_hotspot:
                lines.append(_format_hotspot_summary_line(top_hotspot).lstrip("- "))

    elif map_type == "concentration":
        title = map_data.get("title") or "浓度点位地图"
        receptor_count = int(summary.get("receptor_count", 0) or 0)
        unit = summary.get("unit", "μg/m³")
        max_concentration = summary.get("max_concentration")

        lines.extend(
            [
                f"**{title}**",
                f"已渲染 {receptor_count} 个受体点的浓度分布。",
            ]
        )
        if max_concentration is not None:
            lines.append(f"最高浓度 {_format_scalar(max_concentration)} {unit}")

    else:
        rendered_summary = result.get("summary") or "地图渲染完成。"
        lines.append(str(rendered_summary))

    if coverage.get("warnings"):
        lines.extend(["", "**覆盖范围提示**"])
        for warning in coverage.get("warnings", []):
            lines.append(f"- 注意: {warning}")

    return "\n".join(lines)


def render_single_tool_success(
    tool_name: str,
    result: Dict[str, Any],
    capability_summary: Optional[Dict[str, Any]] = None,
) -> str:
    """Render stable markdown for single-tool success cases."""
    if tool_name == "calculate_micro_emission":
        data = result.get("data", {})
        query_info = data.get("query_info", {})
        summary = data.get("summary", {})
        emissions = summary.get("total_emissions_g", {})

        lines = [
            "## 微观排放计算结果",
            "",
            "**计算参数**",
            f"- 车型: {query_info.get('vehicle_type', '未知')}",
            f"- 年份: {query_info.get('model_year', '未知')}",
            f"- 季节: {query_info.get('season', '未知')}",
            f"- 污染物: {', '.join(query_info.get('pollutants', [])) or '未知'}",
            f"- 轨迹点数: {query_info.get('trajectory_points', 0)}",
            "",
            "**汇总结果**",
            f"- 总距离: {summary.get('total_distance_km', 0):.3f} km",
            f"- 总时间: {summary.get('total_time_s', 0)} s",
            "- 总排放量:",
        ]

        for pollutant, value in emissions.items():
            lines.append(f"  - {pollutant}: {value:.4f} g")

        rates = summary.get("emission_rates_g_per_km", {})
        if rates:
            lines.append("- 单位排放:")
            for pollutant, value in rates.items():
                lines.append(f"  - {pollutant}: {value:.4f} g/km")

        return "\n".join(lines)

    if tool_name == "calculate_macro_emission":
        data = result.get("data", {})
        query_info = data.get("query_info", {})
        summary = data.get("summary", {})
        totals = summary.get("total_emissions_kg_per_hr", {})
        defaults_used = data.get("defaults_used")
        has_spatial_data = any(
            isinstance(link, dict) and bool(link.get("geometry"))
            for link in data.get("results", [])
        )
        follow_up = get_capability_aware_follow_up(tool_name, capability_summary)
        overview = _format_macro_overview(int(query_info.get("links_count", 0) or 0), totals)

        lines = [
            "## 宏观排放计算结果",
            "",
            overview,
            "",
            "**计算参数**",
            f"- 路段数: {query_info.get('links_count', 0)}",
            f"- 年份: {query_info.get('model_year', '未知')}",
            f"- 季节: {query_info.get('season', '未知')}",
            f"- 污染物: {', '.join(query_info.get('pollutants', [])) or '未知'}",
            "",
            "**汇总结果**",
            "- 总排放量 (kg/h):",
        ]

        for pollutant, value in totals.items():
            lines.append(f"  - {pollutant}: {value:.4f}")

        _append_defaults_section(
            lines,
            defaults_used,
            preferred_order=["fleet_mix", "model_year", "season", "pollutants"],
            label_map={
                "fleet_mix": "车队组成",
                "model_year": "模型年份",
                "season": "季节",
                "pollutants": "污染物",
            },
            customize_map={
                "fleet_mix": "如需自定义可在文件中添加 fleet_mix 列",
                "model_year": '如需修改可告诉我"用 2015 年的排放因子"',
                "season": '如需修改可说"用冬季条件"',
                "pollutants": '如需添加可说"加上 PM2.5"',
            },
        )

        if follow_up["suggestions"]:
            _append_follow_up_section(
                lines,
                "您可以进一步",
                follow_up["suggestions"],
            )
        elif has_spatial_data and capability_summary is None:
            _append_follow_up_section(
                lines,
                "您可以进一步",
                [
                    '“帮我可视化排放分布” - 在地图上查看各路段排放强度',
                    '“帮我做扩散分析” - 了解污染物如何在大气中扩散',
                    '“把速度降到 30 看看效果” - 新建情景并与基准结果对比',
                ],
            )

        _append_hint_section(lines, "能力边界提示", follow_up["hints"])

        return "\n".join(lines)

    if tool_name == "calculate_dispersion":
        data = result.get("data", {})
        query_info = data.get("query_info", {})
        summary = data.get("summary", {})
        meteorology_used = data.get("meteorology_used", {})
        coverage = data.get("coverage_assessment", {})
        defaults_used = data.get("defaults_used")
        pollutant = query_info.get("pollutant", "未知")
        unit = summary.get("unit", "μg/m³")
        follow_up = get_capability_aware_follow_up(tool_name, capability_summary)

        lines = [
            "## 扩散计算结果",
            "",
            (
                f"完成 {pollutant} 扩散计算，平均浓度 "
                f"{float(summary.get('mean_concentration', 0.0)):.4f} {unit}，"
                f"最高浓度 {float(summary.get('max_concentration', 0.0)):.4f} {unit}。"
            ),
            "",
            "**计算参数**",
            f"- 污染物: {pollutant}",
            f"- 受体点: {summary.get('receptor_count', query_info.get('n_receptors', '未知'))}",
            f"- 时间步: {summary.get('time_steps', query_info.get('n_time_steps', '未知'))}",
            f"- 地表粗糙度: {_format_scalar(query_info.get('roughness_height', '未知'))} m",
            f"- 气象条件来源: {_describe_meteorology_source(meteorology_used)}",
            f"- 气象条件详情: {_format_meteorology_detail(meteorology_used)}",
        ]

        overrides = _format_meteorology_overrides(meteorology_used)
        if overrides:
            lines.append(f"- 气象覆盖参数: {overrides}")

        raster = data.get("raster_grid", {})
        if isinstance(raster, dict) and raster:
            lines.append(
                "- 栅格分辨率: "
                f"{_format_scalar(raster.get('resolution_m', 0))} m "
                f"({raster.get('rows', 0)}x{raster.get('cols', 0)} cells)"
            )

        if isinstance(coverage, dict) and coverage:
            lines.extend(["", "**覆盖范围提示**"])
            if coverage.get("level"):
                lines.append(f"- 覆盖级别: {coverage.get('level')}")
            if coverage.get("result_semantics"):
                lines.append(f"- 结果语义: {coverage.get('result_semantics')}")
            for warning in coverage.get("warnings", []):
                lines.append(f"- 注意: {warning}")

        _append_defaults_section(
            lines,
            defaults_used,
            preferred_order=["meteorology", "roughness_height", "pollutant", "grid_resolution"],
            label_map={
                "meteorology": "气象条件",
                "roughness_height": "地表粗糙度",
                "pollutant": "污染物",
                "grid_resolution": "网格分辨率",
            },
            customize_map={
                "meteorology": "如需修改可指定气象预设、覆盖风速风向，或提供 SFC 文件",
                "roughness_height": "如需修改可指定 roughness_height",
                "pollutant": '如需修改可说"改算 CO2"',
                "grid_resolution": '如需修改可说"把网格改成 100 米"',
            },
        )

        _append_follow_up_section(
            lines,
            "后续分析建议",
            follow_up["suggestions"] if capability_summary is not None else [
                '“帮我识别污染热点” - 找出高浓度区域和主要贡献路段',
                '“在地图上展示浓度分布” - 查看栅格浓度场',
                '“把风向改成西北再比较一下” - 对比不同情景下的浓度变化',
            ],
        )
        _append_hint_section(lines, "能力边界提示", follow_up["hints"])
        return "\n".join(lines)

    if tool_name == "analyze_hotspots":
        data = result.get("data", {})
        summary = data.get("summary", {})
        hotspots = data.get("hotspots", [])
        interpretation = data.get("interpretation", "")
        coverage = data.get("coverage_assessment", {})
        follow_up = get_capability_aware_follow_up(tool_name, capability_summary)

        lines = [
            "## 热点分析结果",
            "",
        ]
        if interpretation:
            lines.extend([
                "**结果解释**",
                f"- {interpretation}",
            ])

        count = int(data.get("hotspot_count", 0) or 0)
        if count == 0:
            lines.extend([
                "",
                "未识别到符合条件的热点区域。",
            ])
        else:
            lines.extend(
                [
                    f"识别出 {count} 个热点区域，最高浓度 {float(summary.get('max_concentration', 0.0)):.4f} μg/m³。",
                    "",
                    "**热点摘要**",
                    f"- 热点数量: {count}",
                    f"- 热点总面积: {float(summary.get('total_hotspot_area_m2', 0.0)):.0f} m²",
                ]
            )
            for hotspot in hotspots[:3]:
                if isinstance(hotspot, dict):
                    lines.append(_format_hotspot_summary_line(hotspot))

        if isinstance(coverage, dict) and coverage.get("warnings"):
            lines.extend(["", "**覆盖范围提示**"])
            for warning in coverage.get("warnings", []):
                lines.append(f"- 注意: {warning}")

        _append_follow_up_section(
            lines,
            "后续操作",
            follow_up["suggestions"] if capability_summary is not None else [
                '“在地图上展示热点” - 查看热点区域和贡献路段',
                '“把阈值改成 top 3% 再看看” - 调整识别灵敏度',
                '“换一个情景重新算再对比” - 比较不同速度、流量或气象条件下的热点变化',
            ],
        )
        _append_hint_section(lines, "能力边界提示", follow_up["hints"])
        return "\n".join(lines)

    if tool_name == "render_spatial_map":
        return _render_spatial_map_result(result)

    if tool_name == "query_emission_factors":
        data = result.get("data", {})

        if "query_summary" in data:
            query_summary = data.get("query_summary", {})
            pollutant_names = query_summary.get("pollutant", "未知")
            vehicle_type = query_summary.get("vehicle_type", "未知")
            model_year = query_summary.get("model_year", "未知")
            season = query_summary.get("season", "未知")
            road_type = query_summary.get("road_type", "未知")
            pollutants_data = {pollutant_names: data}
        else:
            vehicle_type = data.get("vehicle_type", "未知")
            model_year = data.get("model_year", "未知")
            metadata = data.get("metadata", {})
            season = metadata.get("season", "未知")
            road_type = metadata.get("road_type", "未知")
            pollutants_data = data.get("pollutants", {})
            pollutant_names = ", ".join(pollutants_data.keys())

        lines = [
            "## 排放因子查询结果",
            "",
            "**查询参数**",
            f"- 车型: {vehicle_type}",
            f"- 年份: {model_year}",
            f"- 季节: {season}",
            f"- 道路类型: {road_type}",
            f"- 污染物: {pollutant_names}",
        ]

        speed_labels = {25: "低速", 50: "中速", 70: "高速"}
        for pollutant_name, pollutant_data in pollutants_data.items():
            unit = pollutant_data.get("unit", "g/mile")
            typical = pollutant_data.get("typical_values", [])

            lines.append("")
            if len(pollutants_data) > 1:
                lines.append(f"**{pollutant_name} 典型排放值 ({unit})**")
            else:
                lines.append(f"**典型排放值 ({unit})**")

            if typical:
                for value in typical:
                    speed_kph = value.get("speed_kph", 0)
                    rate = value.get("emission_rate", 0)
                    label = speed_labels.get(value.get("speed_mph"), f"{speed_kph} km/h")
                    lines.append(f"- {label} ({speed_kph} km/h): {rate:.4f}")
            else:
                lines.append("- 暂无典型值数据")

        first_pollutant = next(iter(pollutants_data.values()), {})
        speed_range = first_pollutant.get("speed_range", {})
        data_points = first_pollutant.get("data_points", 0)
        data_source = first_pollutant.get("data_source", "")

        lines.append("")
        lines.append("**数据概况**")
        if speed_range:
            lines.append(f"- 速度范围: {speed_range.get('min_kph', 0)} - {speed_range.get('max_kph', 0)} km/h")
        lines.append(f"- 数据点数: {data_points}")
        if data_source:
            lines.append(f"- 数据来源: {data_source}")

        return "\n".join(lines)

    if tool_name == "analyze_file":
        data = result.get("data", {})
        filename = data.get("filename", "未知文件")
        row_count = data.get("row_count", 0)
        columns = data.get("columns", [])
        task_type = data.get("task_type", "未知")
        confidence = data.get("confidence", 0)

        lines = [
            "## 文件分析结果",
            "",
            "**文件信息**",
            f"- 文件名: {filename}",
            f"- 数据行数: {row_count}",
            f"- 识别类型: {task_type}",
            f"- 置信度: {confidence:.0%}",
            "",
            "**数据列**",
            f"- 列数: {len(columns)}",
            f"- 列名: {', '.join(columns[:10])}",
        ]
        if len(columns) > 10:
            lines.append(f"  (还有 {len(columns) - 10} 列...)")

        if task_type == "micro_emission":
            lines.extend(["", "**💡 建议**: 该文件适合用于微观排放计算（基于轨迹数据）"])
        elif task_type == "macro_emission":
            lines.extend(["", "**💡 建议**: 该文件适合用于宏观排放计算（基于路段流量）"])

        return "\n".join(lines)

    return result.get("summary") or "执行完成。"


HEAVY_SYNTHESIS_KEYS = {
    "raster_grid",
    "matrix_mean",
    "concentration_grid",
    "cell_centers_wgs84",
    "contour_bands",
    "contour_geojson",
    "receptor_top_roads",
    "cell_receptor_map",
    "map_data",
    "geojson",
    "features",
}


def _estimate_payload_chars(value: Any) -> int:
    """Return a best-effort character size for synthesis strip markers."""
    try:
        return len(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return len(str(value))


def _strip_heavy_payload_for_synthesis(value: Any) -> Any:
    """Return a compact copy suitable for synthesis prompts without raw spatial payloads."""
    if isinstance(value, dict):
        stripped: Dict[str, Any] = {}
        for key, child in value.items():
            if key in HEAVY_SYNTHESIS_KEYS:
                stripped[key] = (
                    f"[{key}: stripped for synthesis, "
                    f"~{_estimate_payload_chars(child)} chars]"
                )
            else:
                stripped[key] = _strip_heavy_payload_for_synthesis(child)
        return stripped

    if isinstance(value, list):
        if len(value) <= 20:
            return [_strip_heavy_payload_for_synthesis(item) for item in value]
        preview = [_strip_heavy_payload_for_synthesis(item) for item in value[:5]]
        preview.append(f"... ({len(value) - 5} more items)")
        return preview

    return value


def filter_results_for_synthesis(tool_results: list[Dict[str, Any]]) -> Dict[str, Any]:
    """Keep only the high-value fields needed by synthesis."""
    filtered: Dict[str, Any] = {}

    for item in tool_results:
        tool_name = item["name"]
        result = item["result"]

        if not result.get("success"):
            filtered[tool_name] = {
                "success": False,
                "error": result.get("message") or result.get("error") or "未知错误",
            }
            continue

        data = result.get("data", {})
        if tool_name in ["calculate_micro_emission", "calculate_macro_emission"]:
            summary = data.get("summary", {})
            results_list = data.get("results", [])
            query_params = {}
            if data.get("vehicle_type"):
                query_params["vehicle_type"] = data["vehicle_type"]
            if data.get("pollutants"):
                query_params["pollutants"] = data["pollutants"]
            if data.get("model_year"):
                query_params["model_year"] = data["model_year"]
            if data.get("season"):
                query_params["season"] = data["season"]

            filtered[tool_name] = {
                "success": True,
                "summary": result.get("summary", "计算完成"),
                "num_points": len(results_list),
                "total_emissions": summary.get("total_emissions_g", {}) or summary.get("total_emissions", {}),
                "total_distance_km": summary.get("total_distance_km"),
                "total_time_s": summary.get("total_time_s"),
                "query_params": query_params,
                "has_download_file": bool(data.get("download_file")),
            }
        elif tool_name == "query_emission_factors":
            filtered[tool_name] = {
                "success": True,
                "summary": result.get("summary", "查询完成"),
                "data": data,
            }
        elif tool_name == "analyze_file":
            filtered[tool_name] = {
                "success": True,
                "file_type": data.get("detected_type") or data.get("task_type"),
                "columns": data.get("columns"),
                "row_count": data.get("row_count"),
                "file_path": data.get("file_path"),
            }
        else:
            filtered[tool_name] = {
                "success": True,
                "summary": result.get("summary"),
                "data": _strip_heavy_payload_for_synthesis(data),
            }

    return filtered


def format_tool_errors(tool_results: list[Dict[str, Any]]) -> str:
    """Format tool errors for the retry path."""
    errors = []
    for item in tool_results:
        if item["result"].get("error"):
            message = item["result"].get("message") or item["result"].get("error") or "Unknown error"
            suggestions = item["result"].get("suggestions")
            error_text = f"[{item['name']}] Error: {message}"
            if suggestions:
                error_text += f"\nSuggestions: {', '.join(suggestions)}"
            errors.append(error_text)
    return "\n".join(errors)


def format_tool_results(tool_results: list[Dict[str, Any]]) -> str:
    """Format tool results as short summaries."""
    summaries = []
    for item in tool_results:
        if item["result"].get("success"):
            summary = item["result"].get("summary", "Execution successful")
            summaries.append(f"[{item['name']}] {summary}")
        else:
            error = item["result"].get("message") or item["result"].get("error") or "Unknown error"
            summaries.append(f"[{item['name']}] Error: {error}")
    return "\n".join(summaries)


def format_results_as_fallback(tool_results: list[Dict[str, Any]]) -> str:
    """Build deterministic markdown when LLM synthesis is skipped."""
    max_chars = 3000
    lines = ["## 工具执行结果\n"]

    success_count = sum(1 for item in tool_results if item["result"].get("success"))
    error_count = len(tool_results) - success_count
    if error_count > 0:
        lines.append(f"⚠️ {error_count} 个工具执行失败，{success_count} 个成功\n")
    else:
        lines.append("✅ 所有工具执行成功\n")

    for index, item in enumerate(tool_results, 1):
        tool_name = item["name"]
        result = item["result"]
        lines.append(f"### {index}. {tool_name}\n")

        if result.get("success"):
            lines.append("**状态**: ✅ 成功\n")
            summary = str(result.get("summary") or f"{tool_name} completed")
            if len(summary) > 300:
                summary = summary[:297].rstrip() + "..."
            lines.append(f"**结果**: {summary}\n")
        else:
            lines.append("**状态**: ❌ 失败\n")
            error_text = str(result.get("message") or result.get("error") or "Unknown error")
            if len(error_text) > 300:
                error_text = error_text[:297].rstrip() + "..."
            if error_text:
                lines.append(f"**错误**: {error_text}\n")
            if result.get("suggestions"):
                lines.append("**建议**:\n")
                for suggestion in result["suggestions"][:5]:
                    suggestion_text = str(suggestion)
                    if len(suggestion_text) > 200:
                        suggestion_text = suggestion_text[:197].rstrip() + "..."
                    lines.append(f"- {suggestion_text}\n")

        lines.append("\n")

    content = "".join(lines)
    if len(content) <= max_chars:
        return content
    return content[: max_chars - 19].rstrip() + "\n[... 已截断 ...]"
