"""
Scenario comparator for baseline vs scenario analysis.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ScenarioComparator:
    """Compare stored analysis results across scenarios."""

    def compare(
        self,
        result_type: str,
        baseline_result: Dict[str, Any],
        scenario_result: Dict[str, Any],
        metrics: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if result_type == "emission":
            return self._compare_emission(baseline_result, scenario_result, metrics)
        if result_type == "dispersion":
            return self._compare_dispersion(baseline_result, scenario_result, metrics)
        if result_type == "hotspot":
            return self._compare_hotspot(baseline_result, scenario_result, metrics)
        return {"error": f"Unknown result type: {result_type}"}

    def multi_compare(
        self,
        result_type: str,
        results: Dict[str, Dict[str, Any]],
        baseline_label: str = "baseline",
        metrics: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        baseline = results.get(baseline_label)
        if not baseline:
            return {"error": f"Baseline '{baseline_label}' not found"}

        comparisons: Dict[str, Dict[str, Any]] = {}
        for label, result in results.items():
            if label == baseline_label:
                continue
            comparisons[label] = self.compare(result_type, baseline, result, metrics)

        return {
            "multi_comparison": True,
            "result_type": result_type,
            "baseline": baseline_label,
            "scenarios": list(comparisons.keys()),
            "comparisons": comparisons,
        }

    def _compare_emission(
        self,
        baseline_result: Dict[str, Any],
        scenario_result: Dict[str, Any],
        metrics: Optional[List[str]],
    ) -> Dict[str, Any]:
        baseline_data = baseline_result.get("data", {})
        scenario_data = scenario_result.get("data", {})
        baseline_summary = baseline_data.get("summary", {})
        scenario_summary = scenario_data.get("summary", {})
        baseline_query = baseline_data.get("query_info", {})
        scenario_query = scenario_data.get("query_info", {})
        unit = (
            scenario_summary.get("unit")
            or baseline_summary.get("unit")
            or scenario_query.get("unit")
            or baseline_query.get("unit")
            or "μg/m³"
        )

        baseline_totals = baseline_summary.get("total_emissions_kg_per_hr", {})
        scenario_totals = scenario_summary.get("total_emissions_kg_per_hr", {})
        pollutant_names = metrics or sorted(set(baseline_totals) | set(scenario_totals))

        aggregate: Dict[str, Dict[str, Any]] = {}
        for pollutant in pollutant_names:
            baseline_value = float(baseline_totals.get(pollutant, 0.0) or 0.0)
            scenario_value = float(scenario_totals.get(pollutant, 0.0) or 0.0)
            delta = scenario_value - baseline_value
            delta_pct = (delta / baseline_value * 100.0) if baseline_value else 0.0
            aggregate[pollutant] = {
                "baseline": round(baseline_value, 4),
                "scenario": round(scenario_value, 4),
                "delta": round(delta, 4),
                "delta_pct": round(delta_pct, 1),
                "unit": "kg/h",
            }

        baseline_links = {
            str(item.get("link_id")): item
            for item in baseline_data.get("results", [])
            if isinstance(item, dict) and item.get("link_id") is not None
        }
        scenario_links = {
            str(item.get("link_id")): item
            for item in scenario_data.get("results", [])
            if isinstance(item, dict) and item.get("link_id") is not None
        }

        link_changes: List[Dict[str, Any]] = []
        for link_id, baseline_link in baseline_links.items():
            scenario_link = scenario_links.get(link_id)
            if not isinstance(scenario_link, dict):
                continue
            for pollutant in pollutant_names:
                baseline_value = float(
                    baseline_link.get("total_emissions_kg_per_hr", {}).get(pollutant, 0.0) or 0.0
                )
                scenario_value = float(
                    scenario_link.get("total_emissions_kg_per_hr", {}).get(pollutant, 0.0) or 0.0
                )
                delta = scenario_value - baseline_value
                delta_pct = (delta / baseline_value * 100.0) if baseline_value else 0.0
                link_changes.append(
                    {
                        "link_id": link_id,
                        "pollutant": pollutant,
                        "baseline": round(baseline_value, 6),
                        "scenario": round(scenario_value, 6),
                        "delta": round(delta, 6),
                        "delta_pct": round(delta_pct, 1),
                    }
                )

        link_changes.sort(key=lambda item: abs(float(item.get("delta_pct", 0.0))), reverse=True)
        return {
            "comparison_type": "emission",
            "aggregate": aggregate,
            "top_link_changes": link_changes[:10],
            "total_links": baseline_summary.get("total_links", len(baseline_links)),
            "overrides_applied": list(scenario_data.get("overrides_applied", [])),
            "baseline_label": baseline_data.get("scenario_label", "baseline"),
            "scenario_label": scenario_data.get("scenario_label", "scenario"),
        }

    def _compare_dispersion(
        self,
        baseline_result: Dict[str, Any],
        scenario_result: Dict[str, Any],
        metrics: Optional[List[str]],
    ) -> Dict[str, Any]:
        baseline_data = baseline_result.get("data", {})
        scenario_data = scenario_result.get("data", {})
        baseline_summary = baseline_data.get("summary", {})
        scenario_summary = scenario_data.get("summary", {})
        baseline_query = baseline_data.get("query_info", {})
        scenario_query = scenario_data.get("query_info", {})
        unit = (
            scenario_summary.get("unit")
            or baseline_summary.get("unit")
            or scenario_query.get("unit")
            or baseline_query.get("unit")
            or "μg/m³"
        )

        metric_names = metrics or ["mean_concentration", "max_concentration"]
        metric_comparison: Dict[str, Dict[str, Any]] = {}
        for metric_name in metric_names:
            baseline_value = float(baseline_summary.get(metric_name, 0.0) or 0.0)
            scenario_value = float(scenario_summary.get(metric_name, 0.0) or 0.0)
            delta = scenario_value - baseline_value
            delta_pct = (delta / baseline_value * 100.0) if baseline_value else 0.0
            metric_comparison[metric_name] = {
                "baseline": round(baseline_value, 6),
                "scenario": round(scenario_value, 6),
                "delta": round(delta, 6),
                "delta_pct": round(delta_pct, 1),
                "unit": unit,
            }

        baseline_met = baseline_data.get("meteorology_used", {})
        scenario_met = scenario_data.get("meteorology_used", {})
        met_changes: Dict[str, Dict[str, Any]] = {}
        for key in ("wind_speed", "wind_direction", "stability_class", "mixing_height"):
            baseline_value = baseline_met.get(key)
            scenario_value = scenario_met.get(key)
            if baseline_value != scenario_value:
                met_changes[key] = {
                    "baseline": baseline_value,
                    "scenario": scenario_value,
                }

        return {
            "comparison_type": "dispersion",
            "metrics": metric_comparison,
            "meteorology_changes": met_changes,
            "pollutant": scenario_query.get("pollutant") or baseline_query.get("pollutant"),
            "unit": unit,
            "baseline_label": baseline_data.get("scenario_label", "baseline"),
            "scenario_label": scenario_data.get("scenario_label", "scenario"),
        }

    def _compare_hotspot(
        self,
        baseline_result: Dict[str, Any],
        scenario_result: Dict[str, Any],
        metrics: Optional[List[str]],
    ) -> Dict[str, Any]:
        baseline_data = baseline_result.get("data", {})
        scenario_data = scenario_result.get("data", {})
        baseline_summary = baseline_data.get("summary", {})
        scenario_summary = scenario_data.get("summary", {})

        return {
            "comparison_type": "hotspot",
            "baseline_label": baseline_data.get("scenario_label", "baseline"),
            "scenario_label": scenario_data.get("scenario_label", "scenario"),
            "baseline_hotspots": int(baseline_summary.get("hotspot_count", baseline_data.get("hotspot_count", 0)) or 0),
            "scenario_hotspots": int(scenario_summary.get("hotspot_count", scenario_data.get("hotspot_count", 0)) or 0),
            "baseline_max_conc": float(baseline_summary.get("max_concentration", 0.0) or 0.0),
            "scenario_max_conc": float(scenario_summary.get("max_concentration", 0.0) or 0.0),
            "baseline_area": float(baseline_summary.get("total_hotspot_area_m2", 0.0) or 0.0),
            "scenario_area": float(scenario_summary.get("total_hotspot_area_m2", 0.0) or 0.0),
        }
