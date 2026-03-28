"""
Tool: compare_scenarios

Compare baseline and scenario results already stored in the session context store.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class ScenarioCompareTool(BaseTool):
    """Compare one or more scenario results against a baseline."""

    def __init__(self) -> None:
        super().__init__()
        from calculators.scenario_comparator import ScenarioComparator

        self.name = "compare_scenarios"
        self.description = "Compare stored baseline and scenario results"
        self._comparator = ScenarioComparator()

    async def execute(
        self,
        result_types: List[str],
        baseline: str = "baseline",
        scenarios: Optional[List[str]] = None,
        scenario: Optional[str] = None,
        metrics: Optional[List[str]] = None,
        _context_store: Any = None,
        **kwargs: Any,
    ) -> ToolResult:
        if _context_store is None:
            return ToolResult(
                success=False,
                error="No context store available. Please run calculations first.",
            )

        scenario_labels = scenarios or ([scenario] if scenario else [])
        if not scenario_labels:
            return ToolResult(
                success=False,
                error=(
                    "Please specify which scenario(s) to compare. "
                    f"Available: {_context_store.list_scenarios()}"
                ),
            )

        all_comparisons: Dict[str, Any] = {}
        for result_type in result_types:
            baseline_data, _ = _context_store.get_scenario_pair(result_type, baseline, baseline)
            if baseline_data is None:
                all_comparisons[result_type] = {
                    "error": f"No baseline '{baseline}' found for {result_type}"
                }
                continue

            if len(scenario_labels) == 1:
                _, scenario_data = _context_store.get_scenario_pair(
                    result_type, baseline, scenario_labels[0]
                )
                if scenario_data is None:
                    all_comparisons[result_type] = {
                        "error": (
                            f"No scenario '{scenario_labels[0]}' found for {result_type}. "
                            f"Available: {_context_store.list_scenarios(result_type)}"
                        )
                    }
                    continue
                all_comparisons[result_type] = self._comparator.compare(
                    result_type,
                    baseline_data,
                    scenario_data,
                    metrics,
                )
                continue

            results_dict = {baseline: baseline_data}
            missing: List[str] = []
            for label in scenario_labels:
                _, scenario_data = _context_store.get_scenario_pair(result_type, baseline, label)
                if scenario_data is None:
                    missing.append(label)
                    continue
                results_dict[label] = scenario_data

            if missing:
                all_comparisons[result_type] = {
                    "error": (
                        f"Missing scenarios: {missing}. "
                        f"Available: {_context_store.list_scenarios(result_type)}"
                    )
                }
                continue
            all_comparisons[result_type] = self._comparator.multi_compare(
                result_type,
                results_dict,
                baseline_label=baseline,
                metrics=metrics,
            )

        summary = self._build_comparison_summary(all_comparisons)
        chart_data = self._build_chart_data(all_comparisons)
        return ToolResult(
            success=True,
            data=all_comparisons,
            summary=summary,
            chart_data=chart_data,
        )

    def _build_comparison_summary(self, comparisons: Dict[str, Any]) -> str:
        parts: List[str] = []
        for result_type, comparison in comparisons.items():
            if not isinstance(comparison, dict):
                continue
            if "error" in comparison:
                parts.append(f"{result_type}: {comparison['error']}")
                continue

            if comparison.get("multi_comparison"):
                scenario_names = ", ".join(comparison.get("scenarios", []))
                parts.append(f"{result_type}: 已与 {scenario_names} 对比")
                continue

            if comparison.get("comparison_type") == "emission":
                aggregate = comparison.get("aggregate", {})
                for pollutant, values in aggregate.items():
                    parts.append(
                        f"{pollutant}: {values['baseline']} → {values['scenario']} "
                        f"({values['delta_pct']:+.1f}%)"
                    )
            elif comparison.get("comparison_type") == "dispersion":
                metric_values = comparison.get("metrics", {})
                for metric_name, values in metric_values.items():
                    parts.append(
                        f"{metric_name}: {values['baseline']:.4f} → {values['scenario']:.4f} "
                        f"({values['delta_pct']:+.1f}%)"
                    )
            elif comparison.get("comparison_type") == "hotspot":
                parts.append(
                    "hotspot: "
                    f"{comparison.get('baseline_hotspots', 0)} → {comparison.get('scenario_hotspots', 0)} 个热点"
                )

        if not parts:
            return "Scenario comparison: no comparison data"
        return "Scenario comparison: " + "; ".join(parts)

    def _build_chart_data(self, comparisons: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for result_type, comparison in comparisons.items():
            if not isinstance(comparison, dict) or "error" in comparison:
                continue

            if comparison.get("multi_comparison"):
                for scenario_label, sub_comparison in comparison.get("comparisons", {}).items():
                    if not isinstance(sub_comparison, dict) or "error" in sub_comparison:
                        continue
                    items.extend(self._chart_items_for_single(result_type, sub_comparison, scenario_label))
                continue

            items.extend(
                self._chart_items_for_single(
                    result_type,
                    comparison,
                    comparison.get("scenario_label"),
                )
            )

        if not items:
            return None
        return {
            "type": "scenario_comparison",
            "chart_type": "grouped_bar",
            "items": items,
        }

    def _chart_items_for_single(
        self,
        result_type: str,
        comparison: Dict[str, Any],
        scenario_label: Optional[str],
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        if comparison.get("comparison_type") == "emission":
            for pollutant, values in comparison.get("aggregate", {}).items():
                items.append(
                    {
                        "result_type": result_type,
                        "scenario_label": scenario_label,
                        "metric": f"{pollutant} ({values['unit']})",
                        "baseline": values["baseline"],
                        "scenario": values["scenario"],
                        "delta_pct": values["delta_pct"],
                    }
                )
        elif comparison.get("comparison_type") == "dispersion":
            for metric_name, values in comparison.get("metrics", {}).items():
                items.append(
                    {
                        "result_type": result_type,
                        "scenario_label": scenario_label,
                        "metric": f"{metric_name} ({values['unit']})",
                        "baseline": values["baseline"],
                        "scenario": values["scenario"],
                        "delta_pct": values["delta_pct"],
                    }
                )
        elif comparison.get("comparison_type") == "hotspot":
            items.append(
                {
                    "result_type": result_type,
                    "scenario_label": scenario_label,
                    "metric": "hotspot_count",
                    "baseline": comparison.get("baseline_hotspots", 0),
                    "scenario": comparison.get("scenario_hotspots", 0),
                    "delta_pct": 0.0,
                }
            )
        return items


__all__ = ["ScenarioCompareTool"]

