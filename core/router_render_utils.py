"""Helper functions extracted from ``core.router`` for synthesis-side rendering."""

from __future__ import annotations

from typing import Any, Dict


def render_single_tool_success(tool_name: str, result: Dict[str, Any]) -> str:
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

        lines = [
            "## 宏观排放计算结果",
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

        return "\n".join(lines)

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
                "data": data,
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
            if result.get("summary"):
                lines.append(f"**结果**: {result['summary']}\n")
            if result.get("data"):
                data = result["data"]
                if isinstance(data, dict):
                    for key, value in list(data.items())[:5]:
                        lines.append(f"- {key}: {value}\n")
                    if len(data) > 5:
                        lines.append(f"  ... (共 {len(data)} 项数据)\n")
        else:
            lines.append("**状态**: ❌ 失败\n")
            error_text = result.get("message") or result.get("error")
            if error_text:
                lines.append(f"**错误**: {error_text}\n")
            if result.get("suggestions"):
                lines.append("**建议**:\n")
                for suggestion in result["suggestions"]:
                    lines.append(f"- {suggestion}\n")

        lines.append("\n")

    return "".join(lines)
