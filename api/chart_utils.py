"""Chart/table response helpers extracted from ``api.routes``.

These helpers are kept pure enough for reuse and testing while route
registration continues to live in ``api.routes`` during the staged extraction
process.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def build_emission_chart_data(skill_name: Optional[str], data: Dict) -> Optional[Dict]:
    """Normalize emission-factor results for frontend chart rendering."""
    if not skill_name or not isinstance(data, dict):
        return None

    if "speed_curve" in data and "query_summary" in data:
        query_summary = data.get("query_summary", {})
        vehicle_type = query_summary.get("vehicle_type", "Unknown")
        model_year = query_summary.get("model_year", 2020)
        pollutant = query_summary.get("pollutant", "NOx")
        speed_curve = data.get("speed_curve", [])

        return {
            "type": "emission_factors",
            "vehicle_type": vehicle_type,
            "model_year": model_year,
            "pollutants": {
                pollutant: {
                    "curve": speed_curve,
                    "unit": data.get("unit", "g/mile"),
                }
            },
            "metadata": {
                "data_source": data.get("data_source", ""),
                "speed_range": data.get("speed_range", {}),
                "data_points": data.get("data_points", 0),
            },
            "key_points": extract_key_points({"pollutant": pollutant, "curve": speed_curve}),
        }

    if skill_name == "query_emission_factors" and "pollutants" in data:
        pollutants_data = data.get("pollutants", {})
        if isinstance(pollutants_data, dict):
            normalized_pollutants = {}
            for pollutant, poll_data in pollutants_data.items():
                if isinstance(poll_data, dict):
                    if "speed_curve" in poll_data and "curve" not in poll_data:
                        speed_curve = poll_data.get("speed_curve", [])
                        curve = []
                        for point in speed_curve:
                            curve.append(
                                {
                                    "speed_kph": point.get("speed_kph", 0),
                                    "emission_rate": round(point.get("emission_rate", 0) / 1.60934, 4),
                                }
                            )
                        normalized_pollutants[pollutant] = {
                            "curve": curve,
                            "unit": "g/km",
                        }
                    else:
                        normalized_pollutants[pollutant] = poll_data

            return {
                "type": "emission_factors",
                "vehicle_type": data.get("vehicle_type", "Unknown"),
                "model_year": data.get("model_year", 2020),
                "pollutants": normalized_pollutants,
                "metadata": data.get("metadata", {}),
                "key_points": extract_key_points(normalized_pollutants),
            }

    if "data" in data and isinstance(data["data"], dict):
        return build_emission_chart_data(skill_name, data["data"])

    if "curve" in data or "emission_curve" in data:
        curve = data.get("curve") or data.get("emission_curve", [])
        return {
            "type": "emission_factors",
            "vehicle_type": data.get("vehicle_type", "Unknown"),
            "model_year": data.get("model_year", 2020),
            "pollutants": {
                "default": {
                    "curve": curve,
                    "unit": "g/km",
                }
            },
            "metadata": {},
            "key_points": extract_key_points({"default": {"curve": curve}}),
        }

    logger.warning("Unrecognized chart data format keys: %s", list(data.keys()))
    return None


def extract_key_points(pollutants_data) -> list:
    """Extract key speed points (30/60/90 km/h) for table display."""
    if not pollutants_data:
        return []

    if isinstance(pollutants_data, dict) and "curve" in pollutants_data:
        pollutant = pollutants_data.get("pollutant", "Unknown")
        curve = pollutants_data.get("curve", [])
        return _pick_key_points(curve, pollutant)

    if isinstance(pollutants_data, dict):
        for pollutant, info in pollutants_data.items():
            curve = info.get("curve", []) if isinstance(info, dict) else []
            if curve:
                return _pick_key_points(curve, pollutant)

    return []


def _pick_key_points(curve, pollutant: str) -> list:
    if not curve:
        return []

    targets = [30, 60, 90]
    labels = ["City Congestion", "City Cruise", "Highway"]
    points = []
    for target, label in zip(targets, labels):
        closest = min(curve, key=lambda p: abs(p.get("speed_kph", 0) - target))
        points.append(
            {
                "speed": closest.get("speed_kph"),
                "rate": closest.get("emission_rate"),
                "label": label,
                "pollutant": pollutant,
            }
        )
    return points


__all__ = [
    "_pick_key_points",
    "build_emission_chart_data",
    "extract_key_points",
]
