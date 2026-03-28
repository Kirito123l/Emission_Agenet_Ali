"""
Road network coverage assessment for dispersion calculation.

Evaluates whether the input road network is spatially complete enough
to produce physically meaningful dispersion results, and assigns
a semantic coverage level that affects how results should be interpreted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import geopandas as gpd
import numpy as np
from pyproj import CRS
from shapely.geometry import MultiPolygon
from shapely.ops import unary_union

logger = logging.getLogger(__name__)

BUFFER_DISTANCE_M = 200.0


@dataclass
class CoverageAssessment:
    """Result of road network coverage evaluation."""

    level: str
    convex_hull_area_km2: float
    total_road_length_km: float
    road_density_km_per_km2: float
    road_count: int
    is_connected: bool
    max_gap_m: float
    result_semantics: str
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "convex_hull_area_km2": round(self.convex_hull_area_km2, 3),
            "total_road_length_km": round(self.total_road_length_km, 2),
            "road_density_km_per_km2": round(self.road_density_km_per_km2, 1),
            "road_count": self.road_count,
            "is_connected": self.is_connected,
            "max_gap_m": round(self.max_gap_m, 1),
            "result_semantics": self.result_semantics,
            "warnings": list(self.warnings),
        }


def _estimate_utm_crs(roads_gdf: gpd.GeoDataFrame) -> CRS:
    """Estimate a suitable UTM CRS from the road network centroid."""
    if roads_gdf.crs and roads_gdf.crs.is_geographic:
        geographic = roads_gdf
    elif roads_gdf.crs:
        geographic = roads_gdf.to_crs("EPSG:4326")
    else:
        geographic = roads_gdf.set_crs("EPSG:4326", allow_override=True)

    geometry_union = (
        geographic.geometry.union_all()
        if hasattr(geographic.geometry, "union_all")
        else unary_union(geographic.geometry)
    )
    centroid = geometry_union.centroid
    zone = int((float(centroid.x) + 180.0) // 6.0) + 1
    epsg = 32600 + zone if float(centroid.y) >= 0 else 32700 + zone
    return CRS.from_epsg(epsg)


def _to_metric_crs(roads_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Project roads into a metric CRS for distance/area computations."""
    if roads_gdf.crs is None:
        logger.warning("Coverage assessment received roads without CRS; assuming EPSG:4326")
        roads_gdf = roads_gdf.set_crs("EPSG:4326", allow_override=True)

    crs = roads_gdf.crs
    if crs and crs.is_projected:
        axis_info = list(getattr(crs, "axis_info", []) or [])
        unit_name = axis_info[0].unit_name.lower() if axis_info else ""
        if "metre" in unit_name or "meter" in unit_name:
            return roads_gdf.copy()

    return roads_gdf.to_crs(_estimate_utm_crs(roads_gdf))


def _extract_polygon_parts(buffered_union) -> list:
    """Extract polygon components from a buffered union geometry."""
    if buffered_union.is_empty:
        return []
    if isinstance(buffered_union, MultiPolygon):
        return list(buffered_union.geoms)
    if buffered_union.geom_type == "Polygon":
        return [buffered_union]
    if hasattr(buffered_union, "geoms"):
        return [geom for geom in buffered_union.geoms if geom.geom_type == "Polygon"]
    return []


def _compute_connectivity(projected_roads: gpd.GeoDataFrame) -> Tuple[bool, float]:
    """Approximate connectivity by buffering roads and checking cluster splits."""
    buffered_union = unary_union(projected_roads.geometry.buffer(BUFFER_DISTANCE_M))
    parts = _extract_polygon_parts(buffered_union)

    if len(parts) <= 1:
        return True, 0.0

    max_gap = 0.0
    for idx, part in enumerate(parts):
        for other in parts[idx + 1 :]:
            max_gap = max(max_gap, float(part.distance(other)))
    return False, max_gap


def assess_coverage(roads_gdf) -> CoverageAssessment:
    """
    Assess road network coverage quality for dispersion calculation.

    Args:
        roads_gdf: GeoDataFrame with road geometries.

    Returns:
        CoverageAssessment with level, metrics, and interpretation.
    """
    if roads_gdf is None or len(roads_gdf) == 0:
        return CoverageAssessment(
            level="sparse_local",
            convex_hull_area_km2=0.0,
            total_road_length_km=0.0,
            road_density_km_per_km2=0.0,
            road_count=0,
            is_connected=False,
            max_gap_m=0.0,
            result_semantics=(
                "已上传道路范围内的局部热点贡献识别 / "
                "Local hotspot contribution analysis within uploaded roads only"
            ),
            warnings=["未检测到有效道路几何，扩散结果仅能解释为局部占位结果"],
        )

    projected = _to_metric_crs(roads_gdf)
    road_count = int(len(projected))
    total_road_length_km = float(projected.geometry.length.sum() / 1000.0)
    geometry_union = (
        projected.geometry.union_all()
        if hasattr(projected.geometry, "union_all")
        else unary_union(projected.geometry)
    )
    hull = geometry_union.convex_hull
    hull_area_km2 = float(hull.area / 1_000_000.0) if hull.geom_type == "Polygon" else 0.0
    density = total_road_length_km / hull_area_km2 if hull_area_km2 > 0 else 0.0
    is_connected, max_gap_m = _compute_connectivity(projected)

    warnings: list[str] = []
    sparse_semantics = (
        "已上传道路范围内的局部热点贡献识别 / "
        "Local hotspot contribution analysis within uploaded roads only"
    )

    if hull_area_km2 <= 0:
        warnings.append("道路几何形成的凸包面积接近 0，无法代表区域路网覆盖")
        return CoverageAssessment(
            level="sparse_local",
            convex_hull_area_km2=hull_area_km2,
            total_road_length_km=total_road_length_km,
            road_density_km_per_km2=density,
            road_count=road_count,
            is_connected=is_connected,
            max_gap_m=max_gap_m,
            result_semantics=sparse_semantics,
            warnings=warnings,
        )

    if road_count < 10:
        warnings.append(f"路段数量较少（{road_count}条），扩散浓度不具有区域代表性")
        return CoverageAssessment(
            level="sparse_local",
            convex_hull_area_km2=hull_area_km2,
            total_road_length_km=total_road_length_km,
            road_density_km_per_km2=density,
            road_count=road_count,
            is_connected=is_connected,
            max_gap_m=max_gap_m,
            result_semantics=sparse_semantics,
            warnings=warnings,
        )

    if density >= 8.0 and is_connected and hull_area_km2 >= 0.5:
        return CoverageAssessment(
            level="complete_regional",
            convex_hull_area_km2=hull_area_km2,
            total_road_length_km=total_road_length_km,
            road_density_km_per_km2=density,
            road_count=road_count,
            is_connected=is_connected,
            max_gap_m=max_gap_m,
            result_semantics="区域污染浓度场 / Regional pollution concentration field",
            warnings=warnings,
        )

    if density >= 3.0:
        if not is_connected:
            warnings.append("路网存在空间断裂，建议补充缺失区域的道路数据")
        return CoverageAssessment(
            level="partial_regional",
            convex_hull_area_km2=hull_area_km2,
            total_road_length_km=total_road_length_km,
            road_density_km_per_km2=density,
            road_count=road_count,
            is_connected=is_connected,
            max_gap_m=max_gap_m,
            result_semantics=(
                "区域浓度场（部分路网可能缺失，浓度可能偏低）/ "
                "Regional concentration field (partial network, concentrations may be underestimated)"
            ),
            warnings=warnings,
        )

    warnings.append(
        f"路网密度较低（{density:.1f} km/km²），扩散浓度可能被显著低估。建议上传目标区域的完整路网"
    )
    if not is_connected:
        warnings.append("路网存在空间断裂，建议补充缺失区域的道路数据")
    return CoverageAssessment(
        level="sparse_local",
        convex_hull_area_km2=hull_area_km2,
        total_road_length_km=total_road_length_km,
        road_density_km_per_km2=density,
        road_count=road_count,
        is_connected=is_connected,
        max_gap_m=max_gap_m,
        result_semantics=sparse_semantics,
        warnings=warnings,
    )


__all__ = ["CoverageAssessment", "assess_coverage"]
