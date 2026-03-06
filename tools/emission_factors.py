"""
Emission Factors Query Tool

Simplified tool for querying emission factors from MOVES database.
Standardization is handled by the executor layer.
"""
from typing import Dict, Optional, List, Tuple
from pathlib import Path
import pandas as pd
import logging
from datetime import datetime
import os

from .base import BaseTool, ToolResult
from calculators.emission_factors import EmissionFactorCalculator

logger = logging.getLogger(__name__)


class EmissionFactorsTool(BaseTool):
    """Query emission factors from MOVES database"""

    def __init__(self):
        self._calculator = EmissionFactorCalculator()

    @property
    def name(self) -> str:
        return "query_emission_factors"

    @property
    def description(self) -> str:
        return "Query emission factors for specific vehicle types and pollutants"

    def _generate_emission_factor_excel(
        self,
        query_data: Dict,
        outputs_dir: str
    ) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
        """
        生成排放因子查询结果的 Excel 文件

        Args:
            query_data: 查询结果数据
            outputs_dir: 输出目录

        Returns:
            (success, output_path, filename, error_message)
        """
        try:
            # 提取 speed_curve 数据
            speed_curve = query_data.get("speed_curve", [])
            if not speed_curve:
                return False, None, None, "没有速度曲线数据可导出"

            # 构建数据框架
            df_data = []
            for item in speed_curve:
                df_data.append({
                    "速度": item.get("speed_kph"),
                    "单位": "km/h",
                    "排放因子": item.get("emission_rate"),
                    "排放单位": item.get("unit", "g/mile"),
                    "原始速度": item.get("speed_mph"),
                    "原始单位": "mph"
                })

            df = pd.DataFrame(df_data)

            # 生成文件名
            vehicle_type = query_data.get("query_summary", {}).get("vehicle_type", "unknown").replace(" ", "_")
            pollutant = query_data.get("query_summary", {}).get("pollutant", "unknown")
            model_year = query_data.get("query_summary", {}).get("model_year", "2020")
            season = query_data.get("query_summary", {}).get("season", "夏季").replace("夏", "summer").replace("春", "spring").replace("秋", "autumn").replace("冬", "winter")
            road_type = query_data.get("query_summary", {}).get("road_type", "快速路").replace("/", "_")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"emission_factors_{vehicle_type}_{pollutant}_{model_year}_{timestamp}.xlsx"
            output_path = os.path.join(outputs_dir, filename)

            # 保存 Excel
            df.to_excel(output_path, index=False, engine='openpyxl')

            logger.info(f"生成排放因子 Excel 文件: {output_path}")
            return True, output_path, filename, None

        except Exception as e:
            error_msg = f"生成 Excel 文件失败: {str(e)}"
            logger.error(error_msg)
            return False, None, None, error_msg

    async def execute(self, **kwargs) -> ToolResult:
        """
        Execute emission factor query

        Parameters (already standardized by executor):
            vehicle_type: str - Standardized vehicle type (e.g., "Passenger Car")
            pollutant: str (optional) - Single pollutant (e.g., "CO2")
            pollutants: List[str] (optional) - Multiple pollutants
            model_year: int - Vehicle model year (1995-2025)
            season: str (optional) - Season (default: "夏季")
            road_type: str (optional) - Road type (default: "快速路")
            return_curve: bool (optional) - Return full speed-emission curve (default: False)
        """
        try:
            # 1. Extract parameters
            vehicle_type = kwargs.get("vehicle_type")
            model_year = kwargs.get("model_year")
            season = kwargs.get("season", "夏季")
            road_type = kwargs.get("road_type", "快速路")
            return_curve = kwargs.get("return_curve", False)

            # 2. Handle pollutant parameters (single or multiple)
            pollutants_list = []
            if kwargs.get("pollutants"):
                pollutants_list = kwargs["pollutants"]
            elif kwargs.get("pollutant"):
                pollutants_list = [kwargs["pollutant"]]
            else:
                return ToolResult(
                    success=False,
                    error="Missing required parameter: pollutant or pollutants",
                    data=None
                )

            # 3. Validate required parameters
            if not vehicle_type or not model_year:
                missing = []
                if not vehicle_type:
                    missing.append("vehicle_type")
                if not model_year:
                    missing.append("model_year")
                return ToolResult(
                    success=False,
                    error=f"Missing required parameters: {', '.join(missing)}",
                    data=None
                )

            # 4. Query each pollutant
            pollutants_data = {}
            for pollutant in pollutants_list:
                result = self._calculator.query(
                    vehicle_type=vehicle_type,
                    pollutant=pollutant,
                    model_year=model_year,
                    season=season,
                    road_type=road_type,
                    return_curve=return_curve
                )

                # Handle query errors
                if result.get("status") == "error":
                    return ToolResult(
                        success=False,
                        error=result.get("error"),
                        data=result.get("debug")
                    )

                pollutants_data[pollutant] = result["data"]

            # 5. Format response
            if len(pollutants_list) == 1 and not return_curve:
                # Single pollutant, traditional format
                pollutant = pollutants_list[0]
                data = pollutants_data[pollutant]

                # Create summary
                if "speed_curve" in data:
                    num_points = len(data["speed_curve"])
                    summary = f"Found {pollutant} emission factors for {vehicle_type} ({model_year}) with {num_points} speed points. Season: {season}, Road type: {road_type}."
                else:
                    summary = f"Found {pollutant} emission data for {vehicle_type} ({model_year}). Season: {season}, Road type: {road_type}."

                # Generate download file
                download_file_info = None
                if "speed_curve" in data and len(data["speed_curve"]) > 0:
                    try:
                        from config import get_config
                        config = get_config()
                        outputs_dir = str(config.outputs_dir)

                        success, output_path, filename, error = self._generate_emission_factor_excel(
                            data, outputs_dir
                        )

                        if success:
                            download_file_info = {
                                "path": output_path,
                                "filename": filename
                            }
                            logger.info(f"生成排放因子下载文件: {filename}")
                        else:
                            logger.warning(f"生成下载文件失败: {error}")
                    except Exception as e:
                        logger.warning(f"生成下载文件时出错: {e}")

                return ToolResult(
                    success=True,
                    error=None,
                    data=data,
                    summary=summary,
                    download_file=download_file_info
                )
            else:
                # Multiple pollutants or curve format
                pollutant_names = ", ".join(pollutants_list)
                summary = f"Found emission factors for {len(pollutants_list)} pollutants ({pollutant_names}) for {vehicle_type} ({model_year}). Season: {season}, Road type: {road_type}."

                return ToolResult(
                    success=True,
                    error=None,
                    data={
                        "vehicle_type": vehicle_type,
                        "model_year": model_year,
                        "pollutants": pollutants_data,
                        "metadata": {
                            "season": season,
                            "road_type": road_type,
                        }
                    },
                    summary=summary
                )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Emission factor query failed: {str(e)}",
                data=None
            )

