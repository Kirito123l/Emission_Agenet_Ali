"""
排放因子计算器 - 修复版本
"""
import pandas as pd
from pathlib import Path
from typing import Dict, List

class EmissionFactorCalculator:
    """排放因子查询计算器"""

    # CSV实际列名映射
    COL_SPEED = 'Speed'           # 速度 (mph)
    COL_SOURCE_TYPE = 'SourceType'  # 车型ID
    COL_POLLUTANT = 'pollutantID'   # 污染物ID
    COL_MODEL_YEAR = 'ModelYear'    # 年份
    COL_EMISSION = 'EmissionQuant'  # 排放量

    # 车型 -> SourceType ID 映射
    VEHICLE_TO_SOURCE_TYPE = {
        "Motorcycle": 11,
        "Passenger Car": 21,
        "Passenger Truck": 31,
        "Light Commercial Truck": 32,
        "Intercity Bus": 41,
        "Transit Bus": 42,
        "School Bus": 43,
        "Refuse Truck": 51,
        "Single Unit Short-haul Truck": 52,
        "Single Unit Long-haul Truck": 53,
        "Motor Home": 54,
        "Combination Short-haul Truck": 61,
        "Combination Long-haul Truck": 62,
    }

    # 污染物 -> pollutantID 映射
    POLLUTANT_TO_ID = {
        "THC": 1,
        "CO": 2,
        "NOx": 3,
        "VOC": 5,
        "SO2": 30,
        "NH3": 35,
        "NMHC": 79,
        "CO2": 90,
        "Energy": 91,
        "PM10": 100,
        "PM2.5": 110,
    }

    # 季节代码
    SEASON_CODES = {
        "春季": 4,
        "夏季": 7,
        "秋季": 4,
        "冬季": 1,
    }

    # 道路类型映射（数据库中只有两种）
    ROAD_TYPE_MAPPING = {
        "快速路": 4,
        "高速公路": 4,  # 映射到快速路
        "城市道路": 4,  # 映射到快速路
        "地面道路": 5,
        "居民区道路": 5,  # 映射到地面道路
    }

    def __init__(self):
        # Data is in calculators/data/emission_factors/
        self.data_path = Path(__file__).parent / "data" / "emission_factors"
        self.csv_files = {
            "winter": "atlanta_2025_1_55_65.csv",
            "spring": "atlanta_2025_4_75_65.csv",
            "summer": "atlanta_2025_7_90_70.csv"
        }

    def query(self, vehicle_type: str, pollutant: str, model_year: int,
              season: str = "夏季", road_type: str = "快速路", return_curve: bool = False) -> Dict:
        """执行查询"""

        # 1. 获取ID
        source_type_id = self.VEHICLE_TO_SOURCE_TYPE.get(vehicle_type)
        pollutant_id = self.POLLUTANT_TO_ID.get(pollutant)

        if source_type_id is None:
            return {
                "status": "error",
                "error": f"未知车型: {vehicle_type}",
                "valid_vehicle_types": list(self.VEHICLE_TO_SOURCE_TYPE.keys())
            }

        if pollutant_id is None:
            return {
                "status": "error",
                "error": f"未知污染物: {pollutant}",
                "valid_pollutants": list(self.POLLUTANT_TO_ID.keys())
            }

        # 2. 加载数据
        try:
            df = self._load_data(season)
        except FileNotFoundError as e:
            return {
                "status": "error",
                "error": str(e)
            }

        # 3. 获取道路类型ID（数据库中只有4和5）
        road_type_id = self.ROAD_TYPE_MAPPING.get(road_type, 4)

        # 4. 筛选数据 - 使用正确的列名
        # 注意：Speed列的格式是 {speed}0{road_type}，例如 504 = 5mph + 道路类型4
        mask = (
            (df[self.COL_SOURCE_TYPE] == source_type_id) &
            (df[self.COL_POLLUTANT] == pollutant_id) &
            (df[self.COL_MODEL_YEAR] == model_year)
        )
        filtered = df[mask]

        # 5. 进一步筛选道路类型并解析速度
        # Speed格式：504 = 5mph + 0 + 4(快速路), 1005 = 10mph + 0 + 5(地面道路)
        speed_data = []
        for _, row in filtered.iterrows():
            # 重要：Speed列是浮点数，需要先转int再转str
            speed_code = str(int(row[self.COL_SPEED]))

            # 解析速度编码
            if len(speed_code) >= 2:
                road_type_in_data = int(speed_code[-1])  # 最后1位是道路类型
                speed_value = int(speed_code[:-2])  # 去掉最后2位（0和道路类型）

                # 只保留匹配道路类型的数据
                if road_type_in_data == road_type_id:
                    speed_data.append({
                        "speed_mph": speed_value,
                        "emission_rate": row[self.COL_EMISSION]
                    })

        # 6. 检查是否有数据
        if len(speed_data) == 0:
            # 返回详细的调试信息
            return {
                "status": "error",
                "error": "未找到匹配数据",
                "debug": {
                    "query": {
                        "vehicle_type": vehicle_type,
                        "source_type_id": source_type_id,
                        "pollutant": pollutant,
                        "pollutant_id": pollutant_id,
                        "model_year": model_year,
                        "season": season,
                        "road_type": road_type,
                        "road_type_id": road_type_id,
                    },
                    "available_years": sorted(df[self.COL_MODEL_YEAR].unique().tolist()),
                    "available_source_types": sorted(df[self.COL_SOURCE_TYPE].unique().tolist()),
                    "available_pollutants": sorted(df[self.COL_POLLUTANT].unique().tolist()),
                    "note": "数据库中只有道路类型4(快速路)和5(地面道路)"
                }
            }

        # 7. 按速度排序
        speed_data.sort(key=lambda x: x["speed_mph"])

        # 8. 根据return_curve参数决定返回格式
        if return_curve:
            # 返回完整曲线数据（单位转换为g/km）
            curve = []
            for item in speed_data:
                speed_kph = round(item["speed_mph"] * 1.60934, 1)
                # 单位转换: g/mile -> g/km (除以1.60934)
                emission_rate_g_per_km = round(item["emission_rate"] / 1.60934, 4)
                curve.append({
                    "speed_kph": speed_kph,
                    "emission_rate": emission_rate_g_per_km
                })

            return {
                "status": "success",
                "data": {
                    "curve": curve,
                    "unit": "g/km",
                    "speed_range": {
                        "min_kph": curve[0]["speed_kph"],
                        "max_kph": curve[-1]["speed_kph"],
                    } if curve else {},
                    "data_points": len(curve),
                }
            }
        else:
            # 返回传统格式（包含mph和kph，单位为g/mile）
            speed_curve = []
            for item in speed_data:
                speed_curve.append({
                    "speed_mph": item["speed_mph"],
                    "speed_kph": round(item["speed_mph"] * 1.60934, 1),
                    "emission_rate": round(item["emission_rate"], 4),
                    "unit": "g/mile"
                })

            # 提取典型值 (25, 50, 70 mph)
            typical_values = []
            for target_speed in [25, 50, 70]:
                if speed_curve:
                    closest = min(speed_curve, key=lambda x: abs(x["speed_mph"] - target_speed))
                    typical_values.append({
                        "label": f"{closest['speed_mph']} mph ({closest['speed_kph']} kph)",
                        **closest
                    })

            return {
                "status": "success",
                "data": {
                    "query_summary": {
                        "vehicle_type": vehicle_type,
                        "pollutant": pollutant,
                        "model_year": model_year,
                        "season": season,
                        "road_type": road_type,
                    },
                    "speed_curve": speed_curve,
                    "typical_values": typical_values,
                    "speed_range": {
                        "min_mph": speed_curve[0]["speed_mph"],
                        "max_mph": speed_curve[-1]["speed_mph"],
                        "min_kph": speed_curve[0]["speed_kph"],
                        "max_kph": speed_curve[-1]["speed_kph"],
                    } if speed_curve else {},
                    "data_points": len(speed_curve),
                    "unit": "g/mile",
                    "data_source": "MOVES (Atlanta)"
                }
            }

    def _load_data(self, season: str) -> pd.DataFrame:
        """加载CSV数据"""
        season_code = self.SEASON_CODES.get(season, 7)
        season_key = "winter" if season_code == 1 else ("spring" if season_code == 4 else "summer")
        csv_file = self.csv_files[season_key]
        csv_path = self.data_path / csv_file

        if not csv_path.exists():
            raise FileNotFoundError(f"数据文件不存在: {csv_path}")

        return pd.read_csv(csv_path)
