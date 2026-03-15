"""Helper functions extracted from ``core.router`` for frontend payload shaping."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

MAX_PREVIEW_ROWS = 4


def format_emission_factors_chart(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Format emission-factor tool output for the frontend chart payload."""
    if "pollutants" in data:
        formatted_pollutants = {}
        for pollutant, pol_data in data["pollutants"].items():
            curve_data = pol_data.get("speed_curve", []) or pol_data.get("curve", [])
            formatted_pollutants[pollutant] = {
                "curve": curve_data,
                "unit": pol_data.get("unit", "g/mile"),
            }

        return {
            "type": "emission_factors",
            "vehicle_type": data.get("vehicle_type", "Unknown"),
            "model_year": data.get("model_year", 2020),
            "pollutants": formatted_pollutants,
            "metadata": data.get("metadata", {}),
        }

    curve_data = data.get("speed_curve", []) or data.get("curve", [])
    if curve_data:
        pollutant = data.get("query_summary", {}).get("pollutant", "Unknown")
        vehicle_type = data.get("query_summary", {}).get("vehicle_type", "Unknown")
        model_year = data.get("query_summary", {}).get("model_year", 2020)

        return {
            "type": "emission_factors",
            "vehicle_type": vehicle_type,
            "model_year": model_year,
            "pollutants": {
                pollutant: {
                    "curve": curve_data,
                    "unit": data.get("unit", "g/mile"),
                }
            },
            "metadata": {
                "data_source": data.get("data_source", ""),
                "speed_range": data.get("speed_range", {}),
                "data_points": data.get("data_points", 0),
            },
        }

    return None


def extract_chart_data(tool_results: list[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Extract chart payloads from tool results."""
    for item in tool_results:
        if item["result"].get("chart_data"):
            return item["result"]["chart_data"]

        if item["name"] == "query_emission_factors" and item["result"].get("success"):
            data = item["result"].get("data", {})
            if data:
                return format_emission_factors_chart(data)

    return None


def extract_table_data(tool_results: list[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Extract table payloads in the shape expected by the frontend."""
    for item in tool_results:
        if item["result"].get("table_data"):
            return item["result"]["table_data"]

        if item["name"] == "query_emission_factors" and item["result"].get("success"):
            logger.info("[DEBUG TABLE] Processing query_emission_factors")
            data = item["result"].get("data", {})
            logger.info(f"[DEBUG TABLE] Data keys: {list(data.keys())}")

            if "pollutants" in data:
                logger.info("[DEBUG TABLE] Multi-pollutant format detected")
                pollutants_data = data["pollutants"]
                first_pollutant = list(pollutants_data.keys())[0]
                logger.info(f"[DEBUG TABLE] First pollutant: {first_pollutant}")
                logger.info(
                    "[DEBUG TABLE] First pollutant data keys: "
                    f"{list(pollutants_data[first_pollutant].keys())}"
                )
                first_curve = pollutants_data[first_pollutant].get("speed_curve", []) or pollutants_data[
                    first_pollutant
                ].get("curve", [])
                logger.info(f"[DEBUG TABLE] Curve length: {len(first_curve)}")

                if first_curve:
                    step = max(1, len(first_curve) // MAX_PREVIEW_ROWS)
                    key_points = first_curve[::step][:MAX_PREVIEW_ROWS]
                    columns = ["速度 (km/h)"] + [f"{pollutant} (g/km)" for pollutant in pollutants_data.keys()]

                    preview_rows = []
                    for index, point in enumerate(key_points):
                        row_data = {"速度 (km/h)": f"{point['speed_kph']:.1f}"}
                        for pollutant, pol_data in pollutants_data.items():
                            pol_curve = pol_data.get("speed_curve", []) or pol_data.get("curve", [])
                            curve_index = index * step
                            if curve_index < len(pol_curve):
                                emission_rate = pol_curve[curve_index].get("emission_rate", 0)
                                row_data[f"{pollutant} (g/km)"] = f"{emission_rate:.4f}"
                        preview_rows.append(row_data)

                    logger.info(f"[DEBUG TABLE] Generated {len(preview_rows)} preview rows")
                    table_result = {
                        "type": "query_emission_factors",
                        "columns": columns,
                        "preview_rows": preview_rows,
                        "total_rows": len(first_curve),
                        "total_columns": len(columns),
                        "summary": {
                            "vehicle_type": data.get("vehicle_type", "Unknown"),
                            "model_year": data.get("model_year", 2020),
                            "season": data.get("metadata", {}).get("season", ""),
                            "road_type": data.get("metadata", {}).get("road_type", ""),
                        },
                    }
                    logger.info("[DEBUG TABLE] Returning table data")
                    return table_result

            elif "speed_curve" in data or "curve" in data:
                logger.info("[DEBUG TABLE] Single-pollutant format detected")
                curve = data.get("speed_curve", []) or data.get("curve", [])
                pollutant = data.get("query_summary", {}).get("pollutant", "Unknown")
                step = max(1, len(curve) // MAX_PREVIEW_ROWS)
                key_points = curve[::step][:MAX_PREVIEW_ROWS]
                columns = ["速度 (km/h)", f"{pollutant} (g/km)"]
                preview_rows = [
                    {
                        "速度 (km/h)": f"{point['speed_kph']:.1f}",
                        f"{pollutant} (g/km)": f"{point['emission_rate']:.4f}",
                    }
                    for point in key_points
                ]

                return {
                    "type": "query_emission_factors",
                    "columns": columns,
                    "preview_rows": preview_rows,
                    "total_rows": len(curve),
                    "total_columns": 2,
                    "summary": data.get("query_summary", {}),
                }

        if item["name"] in ["calculate_micro_emission", "calculate_macro_emission"]:
            data = item["result"].get("data", {})
            results = data.get("results", [])
            summary = data.get("summary", {})

            if not results:
                if summary:
                    total_emissions = summary.get("total_emissions_g", {}) or summary.get("total_emissions", {})
                    return {
                        "type": item["name"],
                        "columns": ["指标", "数值"],
                        "preview_rows": [{"指标": key, "数值": f"{value:.2f} g"} for key, value in total_emissions.items()],
                        "total_rows": len(total_emissions),
                        "total_columns": 2,
                        "summary": summary,
                    }
                continue

            first_result = results[0]
            if item["name"] == "calculate_micro_emission":
                columns = ["t", "speed_kph"]
                if "acceleration_mps2" in first_result:
                    columns.append("acceleration_mps2")
                if "vsp" in first_result or "VSP" in first_result:
                    columns.append("VSP")
                emissions = first_result.get("emissions", {})
                columns.extend(list(emissions.keys()))

                preview_rows = []
                for row in results[:MAX_PREVIEW_ROWS]:
                    row_data = {
                        "t": row.get("t", row.get("time", "")),
                        "speed_kph": f"{row.get('speed_kph', row.get('speed', 0)):.1f}",
                    }
                    if "acceleration_mps2" in row:
                        row_data["acceleration_mps2"] = f"{row['acceleration_mps2']:.2f}"
                    if "vsp" in row:
                        row_data["VSP"] = f"{row['vsp']:.2f}"
                    elif "VSP" in row:
                        row_data["VSP"] = f"{row['VSP']:.2f}"
                    for pollutant, value in row.get("emissions", {}).items():
                        row_data[pollutant] = f"{value:.4f}"
                    preview_rows.append(row_data)
            else:
                query_info = data.get("query_info", {})
                result_pollutants = query_info.get("pollutants", ["CO2"])
                main_pollutant = result_pollutants[0] if result_pollutants else "CO2"
                columns = ["link_id", f"{main_pollutant}_kg_h", f"{main_pollutant}_g_veh_km"]
                if len(result_pollutants) > 1:
                    columns.append(f"{result_pollutants[1]}_kg_h")

                preview_rows = []
                for row in results[:MAX_PREVIEW_ROWS]:
                    total_emiss = row.get("total_emissions_kg_per_hr", {}).get(main_pollutant, 0)
                    emission_rate = row.get("emission_rates_g_per_veh_km", {}).get(main_pollutant, 0)
                    row_data = {
                        "link_id": row.get("link_id", ""),
                        f"{main_pollutant}_kg_h": f"{total_emiss:.2f}",
                        f"{main_pollutant}_g_veh_km": f"{emission_rate:.2f}",
                    }
                    if len(result_pollutants) > 1:
                        second_pollutant = result_pollutants[1]
                        second_emiss = row.get("total_emissions_kg_per_hr", {}).get(second_pollutant, 0)
                        row_data[f"{second_pollutant}_kg_h"] = f"{second_emiss:.2f}"
                    preview_rows.append(row_data)

            return {
                "type": item["name"],
                "columns": columns,
                "preview_rows": preview_rows,
                "total_rows": len(results),
                "total_columns": len(columns),
                "summary": summary,
                "total_emissions": summary.get("total_emissions_g", {}) or summary.get("total_emissions", {}),
            }

    return None


def extract_download_file(tool_results: list[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Extract download-file metadata from tool results."""
    logger.info(f"[DEBUG] Extracting download_file from {len(tool_results)} tool results")

    for item in tool_results:
        result = item["result"]
        logger.info(f"[DEBUG] Checking tool: {item['name']}")
        logger.info(f"[DEBUG] Result keys: {result.keys()}")

        if result.get("download_file"):
            download_file = result["download_file"]
            logger.info(f"[DEBUG] Found download_file at top level: {download_file}")
            if isinstance(download_file, str):
                return {
                    "path": download_file,
                    "filename": download_file.split("/")[-1].split("\\")[-1],
                }
            if isinstance(download_file, dict):
                return download_file

        data = result.get("data", {})
        if data and data.get("download_file"):
            download_file = data["download_file"]
            logger.info(f"[DEBUG] Found download_file in data: {download_file}")
            if isinstance(download_file, str):
                return {
                    "path": download_file,
                    "filename": download_file.split("/")[-1].split("\\")[-1],
                }
            if isinstance(download_file, dict):
                return download_file

        metadata = result.get("metadata", {})
        if metadata and metadata.get("download_file"):
            logger.info(f"[DEBUG] Found download_file in metadata: {metadata['download_file']}")
            return metadata["download_file"]

    logger.warning("[DEBUG] No download_file found in any tool result")
    return None


def extract_map_data(tool_results: list[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Extract map payloads from tool results."""
    logger.info(f"[DEBUG] Extracting map_data from {len(tool_results)} tool results")

    for item in tool_results:
        result = item["result"]
        logger.info(f"[DEBUG] Checking tool: {item['name']}")

        if result.get("map_data"):
            map_data = result["map_data"]
            logger.info(f"[DEBUG] Found map_data with {len(map_data.get('links', []))} links")
            return map_data

        data = result.get("data", {})
        if data and data.get("map_data"):
            map_data = data["map_data"]
            logger.info(f"[DEBUG] Found map_data in data with {len(map_data.get('links', []))} links")
            return map_data

    logger.info("[DEBUG] No map_data found in any tool result")
    return None
