"""
Tool: analyze_hotspots

Identifies pollution hotspot areas from dispersion results and traces
their contributing road sources.

Typical usage flow:
1. calculate_macro_emission -> per-link emissions
2. calculate_dispersion -> concentration raster + road contributions
3. analyze_hotspots -> hotspot clusters + source attribution
4. render_spatial_map -> hotspot visualization

This tool does not re-run dispersion. It operates on stored results,
so adjusting thresholds/percentiles is instant.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class HotspotTool(BaseTool):
    """Identify hotspot clusters and trace the roads that drive them."""

    def __init__(self):
        super().__init__()
        from calculators.hotspot_analyzer import HotspotAnalyzer

        self.name = "analyze_hotspots"
        self.description = "Identify pollution hotspots and trace contributing road sources"
        self._analyzer = HotspotAnalyzer()

    async def execute(self, **kwargs) -> ToolResult:
        """Execute hotspot analysis using the latest dispersion result."""
        try:
            dispersion_data = self._resolve_dispersion_data(kwargs)
            if dispersion_data is None:
                return ToolResult(
                    success=False,
                    error="No dispersion results available. Please run calculate_dispersion first.",
                    data=None,
                )

            raster_grid = dispersion_data.get("raster_grid")
            if not raster_grid:
                return ToolResult(
                    success=False,
                    error="Dispersion result does not contain raster grid data. Please re-run calculate_dispersion.",
                    data=None,
                )

            scenario_label = str(
                kwargs.get("scenario_label")
                or dispersion_data.get("scenario_label")
                or "baseline"
            )
            query_info = dispersion_data.get("query_info", {})
            pollutant = str(query_info.get("pollutant") or dispersion_data.get("pollutant") or "NOx")
            dispersion_summary = dispersion_data.get("summary", {})
            unit = str(dispersion_summary.get("unit") or query_info.get("unit") or "μg/m³")
            road_contributions = dispersion_data.get("road_contributions")
            coverage_assessment = dispersion_data.get("coverage_assessment")
            method = str(kwargs.get("method", "percentile"))
            threshold_value = kwargs.get("threshold_value")
            percentile = float(kwargs.get("percentile", 5.0))
            min_hotspot_area_m2 = float(kwargs.get("min_hotspot_area_m2", 2500.0))
            max_hotspots = int(kwargs.get("max_hotspots", 10))
            source_attribution = bool(kwargs.get("source_attribution", True))

            result = self._analyzer.analyze(
                raster_grid=raster_grid,
                road_contributions=road_contributions,
                coverage_assessment=coverage_assessment,
                method=method,
                threshold_value=threshold_value,
                percentile=percentile,
                min_hotspot_area_m2=min_hotspot_area_m2,
                max_hotspots=max_hotspots,
                source_attribution=source_attribution,
                unit=unit,
            )
            if result.get("status") != "success":
                return ToolResult(
                    success=False,
                    error=result.get("message", "Hotspot analysis failed"),
                    data=result,
                )

            analysis_data = dict(result["data"])
            analysis_data["raster_grid"] = raster_grid
            if road_contributions is not None:
                analysis_data["road_contributions"] = road_contributions
            if coverage_assessment is not None:
                analysis_data["coverage_assessment"] = coverage_assessment
            if "contour_bands" in dispersion_data:
                analysis_data["contour_bands"] = dispersion_data["contour_bands"]
            if "roads_wgs84" in dispersion_data:
                analysis_data["roads_wgs84"] = dispersion_data["roads_wgs84"]
            if "query_info" in dispersion_data:
                analysis_data["query_info"] = dispersion_data["query_info"]
            if "meteorology_used" in dispersion_data:
                analysis_data["meteorology_used"] = dispersion_data["meteorology_used"]
            analysis_data["pollutant"] = pollutant
            analysis_data["scenario_label"] = scenario_label

            summary = self._build_summary(analysis_data)
            map_data = self._build_map_data(analysis_data, dispersion_data)
            return ToolResult(
                success=True,
                error=None,
                data=analysis_data,
                summary=summary,
                map_data=map_data,
            )
        except Exception as exc:
            logger.error("Hotspot tool execution failed: %s", exc, exc_info=True)
            return ToolResult(
                success=False,
                error=f"Hotspot analysis error: {exc}",
                data=None,
            )

    def _resolve_dispersion_data(self, kwargs: Dict[str, Any]) -> Optional[dict]:
        """Resolve a previous dispersion-style result payload from _last_result."""
        last_result = kwargs.get("_last_result")
        if not isinstance(last_result, dict):
            return None

        data = last_result.get("data", last_result)
        if not isinstance(data, dict):
            return None

        if "raster_grid" in data or "concentration_grid" in data:
            return data
        return None

    def _build_summary(self, data: Dict[str, Any]) -> str:
        """Build a compact textual summary of hotspot findings."""
        parts: list[str] = []

        interpretation = data.get("interpretation", "")
        if interpretation:
            parts.append(str(interpretation))

        count = int(data.get("hotspot_count", 0))
        if count == 0:
            parts.append("未识别到符合条件的热点区域。")
            return "\n".join(parts)

        parts.append(f"识别出 {count} 个热点区域。")
        summary = data.get("summary", {})
        unit = str(summary.get("unit") or data.get("query_info", {}).get("unit") or "μg/m³")
        parts.append(
            f"热点总面积: {float(summary.get('total_hotspot_area_m2', 0.0)):.0f} m²，"
            f"占总区域 {float(summary.get('area_fraction_pct', 0.0)):.1f}%"
        )
        parts.append(f"最高浓度: {float(summary.get('max_concentration', 0.0)):.4f} {unit}")

        for hotspot in data.get("hotspots", [])[:3]:
            roads = hotspot.get("contributing_roads", [])
            road_desc = ""
            if roads:
                top_road = roads[0]
                road_desc = (
                    f"，主要贡献路段: {top_road.get('link_id')} "
                    f"({float(top_road.get('contribution_pct', 0.0)):.1f}%)"
                )
            parts.append(
                f"热点 #{int(hotspot.get('rank', 0))}: 最大浓度 {float(hotspot.get('max_conc', 0.0)):.4f} {unit}, "
                f"面积 {float(hotspot.get('area_m2', 0.0)):.0f} m²{road_desc}"
            )

        return "\n".join(parts)

    def _build_map_data(self, data: Dict[str, Any], dispersion_data: Dict[str, Any]) -> Dict[str, Any]:
        """Build map payload for hotspot rendering and later frontend layering."""
        query_info = data.get("query_info", {})
        summary = data.get("summary", {})
        pollutant = str(data.get("pollutant") or query_info.get("pollutant") or dispersion_data.get("pollutant") or "NOx")
        unit = str(summary.get("unit") or query_info.get("unit") or "μg/m³")
        map_data = {
            "type": "hotspot",
            "pollutant": pollutant,
            "unit": unit,
            "hotspots": data.get("hotspots", []),
            "summary": summary,
            "interpretation": data.get("interpretation", ""),
            "scenario_label": str(data.get("scenario_label") or dispersion_data.get("scenario_label") or "baseline"),
        }
        if "raster_grid" in dispersion_data:
            map_data["raster_grid"] = dispersion_data["raster_grid"]
        if "contour_bands" in dispersion_data:
            map_data["contour_bands"] = dispersion_data["contour_bands"]
        if "roads_wgs84" in dispersion_data:
            map_data["roads_wgs84"] = dispersion_data["roads_wgs84"]
        if "coverage_assessment" in dispersion_data:
            map_data["coverage_assessment"] = dispersion_data["coverage_assessment"]
        return map_data


__all__ = ["HotspotTool"]
