import json
import sys
from pathlib import Path
from typing import Dict, List

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills.emission_factors.skill import EmissionFactorsSkill


def _format_row(row: Dict) -> str:
    speed_mph = row.get("speed_mph", "")
    speed_kph = row.get("speed_kph", "")
    emission_rate = row.get("emission_rate", "")
    return f"{speed_mph}\t{speed_kph}\t{emission_rate}"


def _print_table(rows: List[Dict]) -> None:
    print("速度 (mph)\t速度 (kph)\tNOx排放因子 (g/mile)")
    for row in rows:
        print(_format_row(row))


def main() -> None:
    skill = EmissionFactorsSkill()
    result = skill.execute(
        vehicle_type="公交车",
        pollutant="NOx",
        model_year=2020,
        season="夏季",
        road_type="快速路",
        return_curve=False,
    )

    if not result.success:
        print(f"查询失败: {result.error}")
        if result.metadata:
            print(json.dumps(result.metadata, ensure_ascii=False, indent=2))
        return

    data = result.data or {}
    query_summary = data.get("query_summary", {})
    speed_curve = data.get("speed_curve", [])

    print("查询参数：")
    print(f"- 车型：{query_summary.get('vehicle_type', '')} (Transit Bus)")
    print(f"- 污染物：{query_summary.get('pollutant', '')}")
    print(f"- 年份：{query_summary.get('model_year', '')}")
    print(f"- 季节：{query_summary.get('season', '')}（默认值）")
    print(f"- 道路类型：{query_summary.get('road_type', '')}（默认值）")
    print()

    print("根据MOVES（Atlanta）模型数据，2020年公交车（Transit Bus）在快速路夏季工况下的NOx排放因子（单位：g/mile）随速度变化如下：")
    _print_table(speed_curve)
    print()

    speed_range = data.get("speed_range", {})
    print("关键说明：")
    if speed_range:
        print(
            f"数据覆盖速度范围：{speed_range.get('min_mph')} mph 至 {speed_range.get('max_mph')} mph"
            f"（约 {speed_range.get('min_kph')} kph 至 {speed_range.get('max_kph')} kph），"
            f"共{data.get('data_points', 0)}个数据点。"
        )
    print("排放因子单位为 g/mile（克/英里），使用时请注意单位换算。")
    print("典型速度点（25、50、70 mph）的排放因子已在上表中标出。")
    print("查询时未指定季节与道路类型，系统已应用默认值（夏季、快速路）。")
    print("如需其他速度点、季节、道路类型或不同单位的排放因子，请提供更具体的查询条件。")


if __name__ == "__main__":
    main()
