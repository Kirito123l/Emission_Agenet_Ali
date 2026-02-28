"""
微观排放计算器
"""
import pandas as pd
from pathlib import Path
from typing import Dict, List
from .vsp import VSPCalculator

class MicroEmissionCalculator:
    """微观排放计算器"""

    # CSV列名
    COL_OPMODE = 'opModeID'
    COL_POLLUTANT = 'pollutantID'
    COL_SOURCE_TYPE = 'SourceType'
    COL_MODEL_YEAR = 'ModelYear'
    COL_EMISSION = 'EmissionQuant'

    # 车型ID映射（与emission_factors保持一致）
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

    # 污染物ID映射
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

    def __init__(self):
        self.data_path = Path(__file__).parent / "data"
        self.vsp_calculator = VSPCalculator()
        self.csv_files = {
            "winter": "atlanta_2025_1_55_65.csv",
            "spring": "atlanta_2025_4_75_65.csv",
            "summer": "atlanta_2025_7_90_70.csv"
        }

    def _year_to_age_group(self, model_year: int) -> int:
        """
        将实际年份转换为MOVES年龄组

        年龄组定义（相对于2025年）:
        - 1: 0-1年 (2024-2025)
        - 2: 2-9年 (2016-2023) - 扩展以覆盖更多年份
        - 5: 10-19年 (2006-2015)
        - 9: 20+年 (<=2005)

        注意：年龄组3在数据库中无数据，已跳过
        """
        age = 2025 - model_year

        if age <= 1:
            return 1
        elif age <= 9:  # 扩展到9年，覆盖2016-2023
            return 2
        elif age <= 19:
            return 5
        else:
            return 9

    def calculate(self, trajectory_data: List[Dict], vehicle_type: str,
                 pollutants: List[str], model_year: int, season: str) -> Dict:
        """执行微观排放计算"""

        try:
            # 1. 验证输入
            if not trajectory_data or len(trajectory_data) == 0:
                raise ValueError("轨迹数据不能为空")

            # 2. 获取车型ID
            source_type_id = self.VEHICLE_TO_SOURCE_TYPE.get(vehicle_type)
            if source_type_id is None:
                return {
                    "status": "error",
                    "error": f"未知车型: {vehicle_type}",
                    "valid_vehicle_types": list(self.VEHICLE_TO_SOURCE_TYPE.keys())
                }

            # 3. 计算VSP和opMode
            trajectory_with_vsp = self.vsp_calculator.calculate_trajectory_vsp(
                trajectory_data, source_type_id
            )

            # 4. 加载排放矩阵
            emission_matrix = self._load_emission_matrix(season)

            # 5. 计算每秒排放
            results = []
            for point in trajectory_with_vsp:
                emissions = {}
                for pollutant in pollutants:
                    pollutant_id = self.POLLUTANT_TO_ID.get(pollutant)
                    if pollutant_id is None:
                        continue

                    emission_rate = self._query_emission_rate(
                        emission_matrix, point["opmode"], pollutant_id,
                        source_type_id, model_year
                    )
                    emissions[pollutant] = round(emission_rate, 6)

                results.append({
                    "t": point.get("t", 0),
                    "speed_kph": point["speed_kph"],
                    "speed_mph": point["speed_mph"],
                    "vsp": point["vsp"],
                    "opmode": point["opmode"],
                    "emissions": emissions
                })

            # 6. 汇总统计
            summary = self._calculate_summary(results, trajectory_data)

            return {
                "status": "success",
                "data": {
                    "query_info": {
                        "vehicle_type": vehicle_type,
                        "pollutants": pollutants,
                        "model_year": model_year,
                        "season": season,
                        "trajectory_points": len(trajectory_data)
                    },
                    "summary": summary,
                    "results": results
                }
            }

        except Exception as e:
            return {
                "status": "error",
                "error_code": "CALCULATION_ERROR",
                "message": str(e)
            }

    def _load_emission_matrix(self, season: str) -> pd.DataFrame:
        """加载排放矩阵"""
        season_code = self.SEASON_CODES.get(season, 7)
        season_key = "winter" if season_code == 1 else ("spring" if season_code == 4 else "summer")
        csv_file = self.csv_files[season_key]
        csv_path = self.data_path / csv_file

        if not csv_path.exists():
            raise FileNotFoundError(f"数据文件不存在: {csv_path}")

        return pd.read_csv(csv_path)

    def _query_emission_rate(self, matrix: pd.DataFrame, opmode: int,
                            pollutant_id: int, source_type: int,
                            model_year: int) -> float:
        """查询排放率"""
        # 将实际年份转换为年龄组
        age_group = self._year_to_age_group(model_year)

        # 先尝试精确匹配
        result = matrix[
            (matrix[self.COL_OPMODE] == opmode) &
            (matrix[self.COL_POLLUTANT] == pollutant_id) &
            (matrix[self.COL_SOURCE_TYPE] == source_type) &
            (matrix[self.COL_MODEL_YEAR] == age_group)
        ]

        if not result.empty:
            return float(result.iloc[0][self.COL_EMISSION])

        # 如果没有找到，尝试使用平均值 (opModeID=300)
        result = matrix[
            (matrix[self.COL_OPMODE] == 300) &
            (matrix[self.COL_POLLUTANT] == pollutant_id) &
            (matrix[self.COL_SOURCE_TYPE] == source_type) &
            (matrix[self.COL_MODEL_YEAR] == age_group)
        ]

        if not result.empty:
            return float(result.iloc[0][self.COL_EMISSION])

        return 0.0  # 未找到数据

    def _calculate_summary(self, results: List[Dict], trajectory_data: List[Dict]) -> Dict:
        """计算汇总统计"""
        if not results:
            return {}

        # 计算总距离
        total_distance_km = 0
        for i in range(1, len(trajectory_data)):
            dt = trajectory_data[i].get("t", i) - trajectory_data[i-1].get("t", i-1)
            speed_kph = trajectory_data[i].get("speed_kph", 0)
            total_distance_km += speed_kph * dt / 3600

        # 计算总排放
        total_emissions = {}
        for result in results:
            for pollutant, emission in result["emissions"].items():
                if pollutant not in total_emissions:
                    total_emissions[pollutant] = 0
                total_emissions[pollutant] += emission

        # 计算单位排放
        emission_rates = {}
        if total_distance_km > 0:
            for pollutant, total in total_emissions.items():
                emission_rates[pollutant] = round(total / total_distance_km, 4)

        return {
            "total_distance_km": round(total_distance_km, 3),
            "total_time_s": len(results),
            "total_emissions_g": {k: round(v, 4) for k, v in total_emissions.items()},
            "emission_rates_g_per_km": emission_rates
        }
