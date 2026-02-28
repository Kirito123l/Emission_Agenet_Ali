"""
宏观排放计算器 - MOVES-Matrix 方法
"""
import pandas as pd
from pathlib import Path
from typing import Dict, List

class MacroEmissionCalculator:
    """宏观排放计算器"""

    # CSV列名
    COL_OPMODE = 'opModeID'
    COL_POLLUTANT = 'pollutantID'
    COL_SOURCE_TYPE = 'sourceTypeID'
    COL_MODEL_YEAR = 'modelYearID'
    COL_EMISSION = 'em'

    # 车型ID映射（与micro_emission保持一致）
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

    # 默认车队组成（如果用户未提供）
    DEFAULT_FLEET_MIX = {
        "Passenger Car": 70.0,
        "Passenger Truck": 20.0,
        "Light Commercial Truck": 5.0,
        "Transit Bus": 3.0,
        "Combination Long-haul Truck": 2.0,
    }

    def __init__(self):
        self.data_path = Path(__file__).parent / "data" / "macro_emission"
        self.csv_files = {
            "winter": "atlanta_2025_1_35_60 .csv",
            "spring": "atlanta_2025_4_75_65.csv",
            "summer": "atlanta_2025_7_80_60.csv"
        }

    def calculate(self, links_data: List[Dict], pollutants: List[str],
                 model_year: int, season: str, default_fleet_mix: Dict = None) -> Dict:
        """执行宏观排放计算"""

        try:
            # 1. 验证输入
            if not links_data or len(links_data) == 0:
                raise ValueError("路段数据不能为空")

            # 2. 加载排放矩阵
            emission_matrix = self._load_emission_matrix(season)

            # 3. 计算每个路段
            results = []
            for link in links_data:
                result = self._calculate_link(
                    link, pollutants, model_year, emission_matrix,
                    default_fleet_mix or self.DEFAULT_FLEET_MIX
                )
                results.append(result)

            # 4. 汇总统计
            summary = self._calculate_summary(results, pollutants)

            return {
                "status": "success",
                "data": {
                    "query_info": {
                        "model_year": model_year,
                        "pollutants": pollutants,
                        "season": season,
                        "links_count": len(links_data)
                    },
                    "results": results,
                    "summary": summary
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

        # 读取CSV - 格式: opModeID,pollutantID,sourceTypeID,modelYearID,em,extra
        return pd.read_csv(csv_path, header=None,
                          names=[self.COL_OPMODE, self.COL_POLLUTANT,
                                self.COL_SOURCE_TYPE, self.COL_MODEL_YEAR,
                                self.COL_EMISSION, 'extra'])

    def _calculate_link(self, link: Dict, pollutants: List[str],
                       model_year: int, matrix: pd.DataFrame,
                       default_fleet_mix: Dict) -> Dict:
        """计算单个路段排放"""

        # 单位转换 (km -> mile)
        length_mi = link["link_length_km"] * 0.621371
        speed_mph = link["avg_speed_kph"] * 0.621371

        # 获取车队组成
        fleet_mix = link.get("fleet_mix", default_fleet_mix).copy()

        # 归一化车队百分比到100%（修复：如果输入百分比总和不是100%，需要标准化）
        total_percentage = sum(fleet_mix.values())
        if total_percentage > 0 and abs(total_percentage - 100.0) > 0.01:  # 允许浮点误差
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"[MacroEmission] 车队百分比总和={total_percentage:.2f}%，标准化到100%")
            for vehicle_name in fleet_mix:
                fleet_mix[vehicle_name] = (fleet_mix[vehicle_name] / total_percentage) * 100.0

        # 初始化结果
        link_result = {
            "link_id": link.get("link_id", "unknown"),
            "link_length_km": link["link_length_km"],
            "traffic_flow_vph": link["traffic_flow_vph"],
            "avg_speed_kph": link["avg_speed_kph"],
            "fleet_composition": {},
            "emissions_by_vehicle": {},
            "total_emissions_kg_per_hr": {p: 0.0 for p in pollutants}
        }

        # 对每个车型计算
        for vehicle_name, percentage in fleet_mix.items():
            source_type_id = self.VEHICLE_TO_SOURCE_TYPE.get(vehicle_name)
            if source_type_id is None:
                continue

            vehicles_per_hour = link["traffic_flow_vph"] * percentage / 100

            link_result["fleet_composition"][vehicle_name] = {
                "source_type_id": source_type_id,
                "percentage": percentage,
                "vehicles_per_hour": round(vehicles_per_hour, 2)
            }

            vehicle_emissions = {}

            for pollutant in pollutants:
                pollutant_id = self.POLLUTANT_TO_ID.get(pollutant)
                if pollutant_id is None:
                    continue

                # 查询排放率 (使用平均opMode=300)
                emission_rate = self._query_emission_rate(
                    matrix, source_type_id, pollutant_id, model_year
                )

                # 计算排放量
                # MOVES EmissionQuant 单位是 g/hr (不是 g/mile)
                # 正确的物理逻辑：
                # 1. 单车排放率 (g/s) = emission_rate / 3600
                # 2. 单车通过路段的行驶时间 (s) = link_length_km / avg_speed_kph * 3600
                # 3. 单车通过路段的排放量 (g) = 排放率 × 行驶时间
                # 4. 路段每小时总排放 = 单车排放量(g) × vehicles_per_hour / 1000 = kg/hr

                # Original incorrect code:
                # emission_kg_per_hr = emission_rate * length_mi * vehicles_per_hour / 1000

                # Corrected code:
                emission_rate_g_per_sec = emission_rate / 3600  # g/hr → g/s
                travel_time_sec = (link["link_length_km"] / link["avg_speed_kph"]) * 3600  # 行驶时间(秒)
                emission_g_per_veh = emission_rate_g_per_sec * travel_time_sec  # 单车排放量
                emission_kg_per_hr = emission_g_per_veh * vehicles_per_hour / 1000  # kg/hr

                link_result["total_emissions_kg_per_hr"][pollutant] += emission_kg_per_hr
                vehicle_emissions[pollutant] = round(emission_kg_per_hr, 4)

            link_result["emissions_by_vehicle"][vehicle_name] = vehicle_emissions

        # 计算单位排放率 (g/veh-km)
        link_result["emission_rates_g_per_veh_km"] = {}
        for pollutant in pollutants:
            total_vehicles = link["traffic_flow_vph"]
            if total_vehicles > 0:
                rate = (
                    link_result["total_emissions_kg_per_hr"].get(pollutant, 0.0) * 1000 /
                    link["link_length_km"] / total_vehicles
                )
                link_result["emission_rates_g_per_veh_km"][pollutant] = round(rate, 4)

        # 四舍五入总排放
        for pollutant in link_result["total_emissions_kg_per_hr"]:
            link_result["total_emissions_kg_per_hr"][pollutant] = \
                round(link_result["total_emissions_kg_per_hr"][pollutant], 4)

        return link_result

    def _query_emission_rate(self, matrix: pd.DataFrame, source_type: int,
                            pollutant_id: int, model_year: int) -> float:
        """查询排放率 - 使用平均opMode (300)"""
        # 查询opMode=300的平均排放率
        result = matrix[
            (matrix[self.COL_OPMODE] == 300) &
            (matrix[self.COL_POLLUTANT] == pollutant_id) &
            (matrix[self.COL_SOURCE_TYPE] == source_type) &
            (matrix[self.COL_MODEL_YEAR] == model_year)
        ]

        if not result.empty:
            return float(result.iloc[0][self.COL_EMISSION])

        return 0.0  # 未找到数据

    def _calculate_summary(self, results: List[Dict], pollutants: List[str]) -> Dict:
        """计算汇总统计"""
        summary = {
            "total_links": len(results),
            "total_emissions_kg_per_hr": {p: 0 for p in pollutants}
        }

        for result in results:
            for pollutant in pollutants:
                summary["total_emissions_kg_per_hr"][pollutant] += \
                    result["total_emissions_kg_per_hr"].get(pollutant, 0)

        # 四舍五入
        for pollutant in pollutants:
            summary["total_emissions_kg_per_hr"][pollutant] = \
                round(summary["total_emissions_kg_per_hr"][pollutant], 4)

        return summary

