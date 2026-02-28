"""
Emission Factors Query Tool

Simplified tool for querying emission factors from MOVES database.
Standardization is handled by the executor layer.
"""
from typing import Dict, Optional, List
from pathlib import Path
from .base import BaseTool, ToolResult
from calculators.emission_factors import EmissionFactorCalculator


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

                return ToolResult(
                    success=True,
                    error=None,
                    data=data,
                    summary=summary
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

