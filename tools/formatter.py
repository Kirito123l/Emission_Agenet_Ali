"""
数值格式化辅助模块
提供统一的排放量数值格式化功能
"""
from typing import Dict, List, Optional


def format_emission(value_g: float, unit: str = "g", per_unit: str = "") -> str:
    """
    格式化排放量数值

    Args:
        value_g: 数值（克）
        unit: 基础单位
        per_unit: 时间/距离单位 (如 "h", "km")

    Returns:
        格式化字符串
    """
    if value_g >= 1_000_000:  # >= 1吨
        tons = value_g / 1_000_000
        kg = value_g / 1000
        return f"{tons:.2f} 吨{per_unit} ({kg:.2f} kg{per_unit})"
    elif value_g >= 1000:  # >= 1kg
        kg = value_g / 1000
        return f"{kg:.2f} kg{per_unit} ({value_g:.2f} g{per_unit})"
    else:
        return f"{value_g:.2f} g{per_unit}"


def format_emission_multi_unit(value_g: float, context: str) -> str:
    """
    多单位显示排放量

    Args:
        value_g: 数值（克）
        context: 上下文类型 ("hour", "total", 等)

    Returns:
        格式化字符串，包含多个单位
    """
    if context == "hour":
        # 每小时排放量，同时显示每天排放量
        base = format_emission(value_g, "", "")
        per_day = value_g * 24
        return f"{base}/小时 ({format_emission(per_day, '', '')}/天)"
    elif context == "total":
        # 总排放量
        return format_emission(value_g, "", "")
    else:
        return format_emission(value_g, "", "")


def calculate_stats(values: List[float]) -> Dict:
    """
    计算统计值

    Args:
        values: 数值列表

    Returns:
        包含 count, avg, max, min 的字典
    """
    if not values:
        return {}
    return {
        "count": len(values),
        "avg": sum(values) / len(values),
        "max": max(values),
        "min": min(values)
    }


def format_emission_summary(
    total_emissions: Dict[str, float],
    context: str = "hour"
) -> List[str]:
    """
    格式化排放量汇总为多行文本

    Args:
        total_emissions: 污染物->排放量的字典
        context: 上下文类型

    Returns:
        格式化后的文本行列表
    """
    lines = []
    for pollutant, value in total_emissions.items():
        formatted = format_emission_multi_unit(value, context)
        lines.append(f"  - {pollutant}: {formatted}")
    return lines


def build_emission_table_summary(
    results: List[Dict],
    pollutants: List[str],
    prefix: str = "total_emissions_kg_per_hr"
) -> Dict:
    """
    构建表格统计汇总

    Args:
        results: 计算结果列表
        pollutants: 污染物列表
        prefix: 排放量字段前缀

    Returns:
        统计汇总字典
    """
    if not results:
        return {}

    main_pollutant = pollutants[0] if pollutants else "CO2"

    # 提取每个路段的排放量
    link_emissions = []
    for r in results:
        if prefix == "total_emissions_kg_per_hr":
            # 宏观排放：值已经是 kg
            value = r.get(prefix, {}).get(main_pollutant, 0) * 1000  # kg → g
        elif prefix == "total_emissions_g":
            # 微观排放：值已经是 g
            value = r.get(prefix, {}).get(main_pollutant, 0) if isinstance(r.get(prefix), dict) else 0
        else:
            value = 0
        link_emissions.append(value)

    stats = calculate_stats(link_emissions)

    return {
        "main_pollutant": main_pollutant,
        "total_emissions": sum(link_emissions),
        "avg_emission": stats.get("avg", 0),
        "max_emission": stats.get("max", 0),
        "min_emission": stats.get("min", 0),
        "count": stats.get("count", 0)
    }
