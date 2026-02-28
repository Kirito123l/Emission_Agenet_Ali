"""
Micro Emission Calculation Tool

Simplified tool for calculating second-by-second emissions from trajectory data.
Standardization is handled by the executor layer.
"""
from typing import Dict, Optional, List
from pathlib import Path
import logging
from .base import BaseTool, ToolResult
from .formatter import format_emission, calculate_stats
from calculators.micro_emission import MicroEmissionCalculator
from skills.micro_emission.excel_handler import ExcelHandler

logger = logging.getLogger(__name__)


class MicroEmissionTool(BaseTool):
    """Calculate micro-scale emissions from trajectory data"""

    def __init__(self):
        self._calculator = MicroEmissionCalculator()
        # Excel handler for file I/O
        try:
            from llm.client import get_llm
            llm_client = get_llm("agent")
            self._excel_handler = ExcelHandler(llm_client=llm_client)
            logger.info("[MicroEmission] Intelligent column mapping enabled")
        except Exception as e:
            logger.warning(f"[MicroEmission] Using hardcoded mapping: {e}")
            self._excel_handler = ExcelHandler(llm_client=None)

    @property
    def name(self) -> str:
        return "calculate_micro_emission"

    @property
    def description(self) -> str:
        return "Calculate second-by-second emissions from vehicle trajectory data"

    async def execute(self, **kwargs) -> ToolResult:
        """
        Execute micro emission calculation

        Parameters (already standardized by executor):
            vehicle_type: str - Standardized vehicle type (e.g., "Passenger Car")
            pollutants: List[str] - List of pollutants (e.g., ["CO2", "NOx"])
            model_year: int - Vehicle model year (default: 2020)
            season: str - Season (default: "夏季")
            trajectory_data: List[Dict] (optional) - Trajectory data points
            input_file: str (optional) - Path to Excel input file
            output_file: str (optional) - Path to Excel output file
        """
        try:
            # 参数名兼容：file_path → input_file
            if "file_path" in kwargs and "input_file" not in kwargs:
                kwargs["input_file"] = kwargs["file_path"]
                logger.info(f"[MicroEmission] Mapped file_path to input_file: {kwargs['file_path']}")

            # DIAGNOSTIC LOGGING
            logger.debug("=" * 50)
            logger.debug("[MicroEmission] FULL PARAMS DUMP:")
            for k, v in kwargs.items():
                logger.debug(f"  {k}: {v} (type: {type(v).__name__})")
            logger.debug("=" * 50)

            # 1. Extract parameters
            vehicle_type = kwargs.get("vehicle_type")
            pollutants = kwargs.get("pollutants", ["CO2", "NOx"])
            model_year = kwargs.get("model_year", 2020)
            season = kwargs.get("season", "夏季")
            input_file = kwargs.get("input_file")
            output_file = kwargs.get("output_file")
            trajectory_data = kwargs.get("trajectory_data")

            # 2. Validate required parameters
            if not vehicle_type:
                return ToolResult(
                    success=False,
                    error="Missing required parameter: vehicle_type",
                    data=None
                )

            # 3. Get trajectory data (from parameter or file)
            if input_file:
                # Read from Excel file
                success, trajectory_data, read_error = self._excel_handler.read_trajectory_from_excel(input_file)
                if not success:
                    return ToolResult(
                        success=False,
                        error=f"Failed to read input file: {read_error}",
                        data={"input_file": input_file}
                    )
            elif not trajectory_data:
                return ToolResult(
                    success=False,
                    error="Missing required parameter: trajectory_data or input_file",
                    data=None
                )

            # 4. Validate trajectory data
            if not isinstance(trajectory_data, list) or len(trajectory_data) == 0:
                return ToolResult(
                    success=False,
                    error="trajectory_data must be a non-empty list",
                    data=None
                )

            # 5. Execute calculation
            result = self._calculator.calculate(
                trajectory_data=trajectory_data,
                vehicle_type=vehicle_type,
                pollutants=pollutants,
                model_year=model_year,
                season=season
            )

            # 6. Handle calculation errors
            if result.get("status") == "error":
                return ToolResult(
                    success=False,
                    error=result.get("message", result.get("error")),
                    data={
                        "error_code": result.get("error_code"),
                        "query_params": {
                            "vehicle_type": vehicle_type,
                            "pollutants": pollutants,
                            "model_year": model_year,
                            "season": season,
                            "trajectory_points": len(trajectory_data)
                        }
                    }
                )

            # 7. Write output file (if specified)
            if output_file:
                results_data = result["data"].get("results", [])

                # Build trajectory data with VSP
                trajectory_for_excel = []
                emissions_for_excel = []

                for point in results_data:
                    trajectory_for_excel.append({
                        "t": point.get("t", 0),
                        "speed_kph": point.get("speed_kph", 0),
                        "acceleration_mps2": 0,
                        "grade_pct": 0,
                        "VSP": point.get("vsp", 0)
                    })
                    emissions_for_excel.append(point.get("emissions", {}))

                write_success, write_error = self._excel_handler.write_results_to_excel(
                    output_file,
                    trajectory_for_excel,
                    emissions_for_excel,
                    pollutants
                )

                if not write_success:
                    result["data"]["output_file_warning"] = f"Failed to write output file: {write_error}"
                else:
                    result["data"]["output_file"] = output_file

            # 8. Generate download file (if input_file provided)
            if input_file:
                try:
                    from config import get_config
                    config = get_config()
                    outputs_dir = str(config.outputs_dir)

                    results_data = result["data"].get("results", [])
                    emission_list = [point.get("emissions", {}) for point in results_data]

                    success, output_path, filename, error = self._excel_handler.generate_result_excel(
                        input_file,  # 修复：传递文件路径而不是轨迹数据
                        emission_list,
                        pollutants,
                        outputs_dir
                    )

                    if success:
                        result["data"]["download_file"] = {
                            "path": output_path,
                            "filename": filename
                        }
                except Exception as e:
                    logger.warning(f"Failed to generate download file: {e}")

            # 9. Return success result with enhanced summary
            results_data = result["data"].get("results", [])
            summary_data = result["data"].get("summary", {})

            num_points = len(results_data)
            pollutant_names = ", ".join(pollutants)
            total_emissions = summary_data.get("total_emissions_g", {})

            # Build enhanced summary with multi-unit display
            summary_parts = [
                f"已完成微观排放计算",
                f"**计算参数:**",
                f"  - 车型: {vehicle_type} ({model_year}年)",
                f"  - 季节: {season}",
                f"  - 污染物: {pollutant_names}",
                f"  - 轨迹数据点: {num_points} 个"
            ]

            # Total emissions with multi-unit display
            if total_emissions:
                summary_parts.append("**总排放量:**")
                for pollutant, value_g in total_emissions.items():
                    formatted = format_emission(value_g, "", "")
                    summary_parts.append(f"  - {pollutant}: {formatted}")

            # Additional statistics
            total_distance_km = summary_data.get("total_distance_km", 0)
            total_time_s = summary_data.get("total_time_s", 0)
            emission_rates = summary_data.get("emission_rates_g_per_km", {})

            if total_distance_km > 0:
                avg_speed_kph = (total_distance_km / (total_time_s / 3600)) if total_time_s > 0 else 0
                summary_parts.append("**运行统计:**")
                summary_parts.append(f"  - 总距离: {total_distance_km:.2f} km")
                summary_parts.append(f"  - 总时间: {total_time_s} 秒 ({total_time_s/60:.1f} 分钟)")
                summary_parts.append(f"  - 平均速度: {avg_speed_kph:.1f} km/h")

            if emission_rates:
                summary_parts.append("**排放率:**")
                for pollutant, rate in emission_rates.items():
                    summary_parts.append(f"  - {pollutant}: {rate:.2f} g/km")

            summary = "\n".join(summary_parts)

            return ToolResult(
                success=True,
                error=None,
                data=result["data"],
                summary=summary
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Micro emission calculation failed: {str(e)}",
                data=None
            )
