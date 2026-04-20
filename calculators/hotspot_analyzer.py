"""
Hotspot analysis engine for dispersion concentration rasters.

Identifies pollution hotspot areas from raster grids, clusters adjacent
hotspot cells, and traces contributing road sources using per-receptor
road contribution data.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class HotspotArea:
    """A single identified hotspot cluster."""

    hotspot_id: int
    rank: int
    center_lon: float
    center_lat: float
    bbox: List[float]
    area_m2: float
    grid_cells: int
    max_conc: float
    mean_conc: float
    cell_keys: List[str] = field(default_factory=list)
    contributing_roads: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "hotspot_id": int(self.hotspot_id),
            "rank": int(self.rank),
            "center": {"lon": float(self.center_lon), "lat": float(self.center_lat)},
            "bbox": [float(value) for value in self.bbox],
            "area_m2": round(float(self.area_m2), 1),
            "grid_cells": int(self.grid_cells),
            "max_conc": round(float(self.max_conc), 4),
            "mean_conc": round(float(self.mean_conc), 4),
            "cell_keys": list(self.cell_keys),
            "contributing_roads": list(self.contributing_roads),
        }


@dataclass
class HotspotAnalysisResult:
    """Complete hotspot analysis output."""

    method: str
    threshold_value: Optional[float]
    percentile: Optional[float]
    coverage_level: str
    interpretation: str
    hotspots: List[HotspotArea]
    summary: Dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "threshold_value": round(float(self.threshold_value), 4)
            if self.threshold_value is not None
            else None,
            "percentile": round(float(self.percentile), 2) if self.percentile is not None else None,
            "coverage_level": self.coverage_level,
            "interpretation": self.interpretation,
            "hotspot_count": len(self.hotspots),
            "hotspots": [hotspot.to_dict() for hotspot in self.hotspots],
            "summary": dict(self.summary),
        }


class HotspotAnalyzer:
    """
    Identifies and analyzes pollution hotspots from dispersion raster results.

    Takes raster_grid and road_contributions from DispersionCalculator output,
    identifies hotspot cells, clusters them spatially, and traces contributing roads.

    This is a lightweight post-processing class and does not re-run dispersion.
    """

    def analyze(
        self,
        raster_grid: dict,
        road_contributions: Optional[dict] = None,
        coverage_assessment: Optional[dict] = None,
        method: str = "percentile",
        threshold_value: Optional[float] = None,
        percentile: float = 5.0,
        min_hotspot_area_m2: float = 2500.0,
        max_hotspots: int = 10,
        source_attribution: bool = True,
        unit: str = "μg/m³",
    ) -> Dict[str, Any]:
        """Run hotspot analysis against a dispersion raster grid."""
        try:
            perf_enabled = logger.isEnabledFor(logging.DEBUG)
            perf_start = time.perf_counter()

            if not isinstance(raster_grid, dict):
                return {
                    "status": "error",
                    "error_code": "INVALID_INPUT",
                    "message": "raster_grid must be a dictionary",
                }

            matrix = np.asarray(raster_grid.get("matrix_mean", []), dtype=float)
            matrix_ready = time.perf_counter()
            if perf_enabled:
                logger.debug(
                    "[PERF][Hotspot] Matrix extraction: %.4fs shape=%s",
                    matrix_ready - perf_start,
                    getattr(matrix, "shape", None),
                )
            if matrix.size == 0:
                empty_matrix = np.zeros((0, 0), dtype=float)
                interpretation = self._build_interpretation(
                    coverage_assessment,
                    method,
                    percentile,
                    threshold_value,
                    unit,
                )
                result = self._empty_result(
                    method=method,
                    coverage_assessment=coverage_assessment,
                    interpretation=interpretation,
                    matrix=empty_matrix,
                    resolution=float(raster_grid.get("resolution_m", 0.0) or 0.0),
                    cutoff=float(threshold_value or 0.0),
                    percentile=percentile,
                    threshold_value=threshold_value,
                    unit=unit,
                )
                if perf_enabled:
                    logger.debug("[PERF][Hotspot] Empty matrix path total: %.4fs", time.perf_counter() - perf_start)
                return {"status": "success", "data": result.to_dict()}

            if matrix.ndim != 2:
                return {
                    "status": "error",
                    "error_code": "INVALID_INPUT",
                    "message": "raster_grid.matrix_mean must be a 2D matrix",
                }

            resolution = float(raster_grid.get("resolution_m", 0.0) or 0.0)
            if resolution <= 0:
                return {
                    "status": "error",
                    "error_code": "INVALID_INPUT",
                    "message": "raster_grid.resolution_m must be greater than zero",
                }

            normalized_method = str(method or "percentile").strip().lower()
            if normalized_method not in {"percentile", "threshold"}:
                return {
                    "status": "error",
                    "error_code": "INVALID_INPUT",
                    "message": "method must be either 'percentile' or 'threshold'",
                }

            percentile = float(percentile)
            if normalized_method == "percentile" and not 0 < percentile <= 100:
                return {
                    "status": "error",
                    "error_code": "INVALID_INPUT",
                    "message": "percentile must be between 0 and 100",
                }

            min_hotspot_area_m2 = float(min_hotspot_area_m2)
            if min_hotspot_area_m2 < 0:
                return {
                    "status": "error",
                    "error_code": "INVALID_INPUT",
                    "message": "min_hotspot_area_m2 must be non-negative",
                }

            max_hotspots = int(max_hotspots)
            if max_hotspots <= 0:
                return {
                    "status": "error",
                    "error_code": "INVALID_INPUT",
                    "message": "max_hotspots must be greater than zero",
                }

            if normalized_method == "threshold":
                if threshold_value is None:
                    return {
                        "status": "error",
                        "error_code": "INVALID_INPUT",
                        "message": "threshold_value required for threshold method",
                    }
                cutoff = float(threshold_value)
            else:
                nonzero_values = matrix[matrix > 0]
                if nonzero_values.size == 0:
                    interpretation = self._build_interpretation(
                        coverage_assessment,
                        normalized_method,
                        percentile,
                        threshold_value,
                        unit,
                    )
                    result = self._empty_result(
                        method=normalized_method,
                        coverage_assessment=coverage_assessment,
                        interpretation=interpretation,
                        matrix=matrix,
                        resolution=resolution,
                        cutoff=0.0,
                        percentile=percentile,
                        threshold_value=None,
                        unit=unit,
                    )
                    if perf_enabled:
                        logger.debug("[PERF][Hotspot] All-zero matrix path total: %.4fs", time.perf_counter() - perf_start)
                    return {"status": "success", "data": result.to_dict()}
                cutoff = float(np.percentile(nonzero_values, 100.0 - percentile))

            threshold_ready = time.perf_counter()
            if perf_enabled:
                logger.debug(
                    "[PERF][Hotspot] Threshold calculation: %.4fs method=%s cutoff=%.4f",
                    threshold_ready - matrix_ready,
                    normalized_method,
                    cutoff,
                )

            hotspot_mask = matrix >= cutoff
            mask_ready = time.perf_counter()
            if perf_enabled:
                logger.debug(
                    "[PERF][Hotspot] Hotspot masking: %.4fs selected_cells=%s",
                    mask_ready - threshold_ready,
                    int(np.count_nonzero(hotspot_mask)),
                )
            clusters = self._cluster_hotspot_cells(hotspot_mask)
            raw_cluster_count = len(clusters)
            cell_area = resolution * resolution
            clusters = [cluster for cluster in clusters if len(cluster) * cell_area >= min_hotspot_area_m2]
            clusters = sorted(
                clusters,
                key=lambda cluster: (
                    max(float(matrix[row, col]) for row, col in cluster),
                    float(np.mean([matrix[row, col] for row, col in cluster])),
                    len(cluster),
                ),
                reverse=True,
            )[:max_hotspots]
            clustering_ready = time.perf_counter()
            if perf_enabled:
                logger.debug(
                    "[PERF][Hotspot] Clustering: %.4fs clusters=%s kept=%s",
                    clustering_ready - mask_ready,
                    raw_cluster_count,
                    len(clusters),
                )

            hotspots = [
                self._build_hotspot_area(
                    rank=rank,
                    cluster=cluster,
                    matrix=matrix,
                    raster_grid=raster_grid,
                    road_contributions=road_contributions if source_attribution else None,
                    resolution=resolution,
                )
                for rank, cluster in enumerate(clusters, start=1)
            ]
            hotspots_ready = time.perf_counter()
            if perf_enabled:
                logger.debug(
                    "[PERF][Hotspot] Building hotspot areas: %.4fs hotspots=%s",
                    hotspots_ready - clustering_ready,
                    len(hotspots),
                )

            interpretation = self._build_interpretation(
                coverage_assessment,
                normalized_method,
                percentile,
                threshold_value,
                unit,
            )
            result = HotspotAnalysisResult(
                method=normalized_method,
                threshold_value=float(threshold_value) if normalized_method == "threshold" else None,
                percentile=float(percentile) if normalized_method == "percentile" else None,
                coverage_level=(
                    coverage_assessment.get("level", "unknown")
                    if isinstance(coverage_assessment, dict)
                    else "unknown"
                ),
                interpretation=interpretation,
                hotspots=hotspots,
                summary=self._build_summary(hotspots, matrix, resolution, normalized_method, cutoff, unit),
            )
            if perf_enabled:
                logger.debug("[PERF][Hotspot] Total analyze: %.4fs", time.perf_counter() - perf_start)
            return {"status": "success", "data": result.to_dict()}
        except Exception as exc:
            logger.error("Hotspot analysis failed: %s", exc, exc_info=True)
            return {
                "status": "error",
                "error_code": "ANALYSIS_ERROR",
                "message": str(exc),
            }

    def _empty_result(
        self,
        *,
        method: str,
        coverage_assessment: Optional[dict],
        interpretation: str,
        matrix: np.ndarray,
        resolution: float,
        cutoff: float,
        percentile: Optional[float],
        threshold_value: Optional[float],
        unit: str,
    ) -> HotspotAnalysisResult:
        coverage_level = coverage_assessment.get("level", "unknown") if isinstance(coverage_assessment, dict) else "unknown"
        return HotspotAnalysisResult(
            method=method,
            threshold_value=float(threshold_value) if method == "threshold" and threshold_value is not None else None,
            percentile=float(percentile) if method == "percentile" and percentile is not None else None,
            coverage_level=coverage_level,
            interpretation=interpretation,
            hotspots=[],
            summary=self._build_summary([], matrix, resolution, method, cutoff, unit),
        )

    def _cluster_hotspot_cells(self, hotspot_mask: np.ndarray) -> List[List[Tuple[int, int]]]:
        """Find connected hotspot components using 4-neighbour BFS."""
        if hotspot_mask.size == 0:
            return []

        rows, cols = hotspot_mask.shape
        visited = np.zeros_like(hotspot_mask, dtype=bool)
        clusters: list[list[tuple[int, int]]] = []

        for row in range(rows):
            for col in range(cols):
                if not hotspot_mask[row, col] or visited[row, col]:
                    continue

                queue: deque[tuple[int, int]] = deque([(row, col)])
                visited[row, col] = True
                cluster: list[tuple[int, int]] = []

                while queue:
                    current_row, current_col = queue.popleft()
                    cluster.append((current_row, current_col))
                    for delta_row, delta_col in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        next_row = current_row + delta_row
                        next_col = current_col + delta_col
                        if not (0 <= next_row < rows and 0 <= next_col < cols):
                            continue
                        if not hotspot_mask[next_row, next_col] or visited[next_row, next_col]:
                            continue
                        visited[next_row, next_col] = True
                        queue.append((next_row, next_col))

                clusters.append(cluster)

        return clusters

    def _build_hotspot_area(
        self,
        *,
        rank: int,
        cluster: List[Tuple[int, int]],
        matrix: np.ndarray,
        raster_grid: dict,
        road_contributions: Optional[dict],
        resolution: float,
    ) -> HotspotArea:
        """Build a hotspot area object from one raster cluster."""
        cell_values = np.array([matrix[row, col] for row, col in cluster], dtype=float)
        cell_keys = [f"{row}_{col}" for row, col in cluster]
        area_m2 = float(len(cluster) * resolution * resolution)

        centers_lookup = {
            (int(cell.get("row", -1)), int(cell.get("col", -1))): cell
            for cell in raster_grid.get("cell_centers_wgs84", [])
            if isinstance(cell, dict)
        }
        center_points = [
            centers_lookup.get((row, col)) or self._estimate_cell_center(row, col, raster_grid)
            for row, col in cluster
        ]
        lons = [float(point.get("lon", 0.0)) for point in center_points]
        lats = [float(point.get("lat", 0.0)) for point in center_points]

        contributing_roads = []
        if road_contributions:
            contributing_roads = self._compute_source_attribution(cluster, raster_grid, road_contributions)

        return HotspotArea(
            hotspot_id=rank,
            rank=rank,
            center_lon=float(np.mean(lons)) if lons else 0.0,
            center_lat=float(np.mean(lats)) if lats else 0.0,
            bbox=[
                float(min(lons)) if lons else 0.0,
                float(min(lats)) if lats else 0.0,
                float(max(lons)) if lons else 0.0,
                float(max(lats)) if lats else 0.0,
            ],
            area_m2=area_m2,
            grid_cells=len(cluster),
            max_conc=float(np.max(cell_values)) if cell_values.size else 0.0,
            mean_conc=float(np.mean(cell_values)) if cell_values.size else 0.0,
            cell_keys=cell_keys,
            contributing_roads=contributing_roads,
        )

    def _estimate_cell_center(self, row: int, col: int, raster_grid: dict) -> Dict[str, float]:
        """Approximate a cell center from the raster bbox when explicit cell center data is unavailable."""
        bbox = raster_grid.get("bbox_wgs84", [0.0, 0.0, 0.0, 0.0])
        min_lon, min_lat, max_lon, max_lat = [float(value) for value in bbox]
        rows = max(int(raster_grid.get("rows", 0)), 1)
        cols = max(int(raster_grid.get("cols", 0)), 1)

        if cols == 1:
            lon = (min_lon + max_lon) / 2.0
        else:
            lon = min_lon + (float(col) / float(cols - 1)) * (max_lon - min_lon)
        if rows == 1:
            lat = (min_lat + max_lat) / 2.0
        else:
            lat = min_lat + (float(row) / float(rows - 1)) * (max_lat - min_lat)

        return {"row": int(row), "col": int(col), "lon": lon, "lat": lat}

    def _compute_source_attribution(
        self,
        cluster: List[Tuple[int, int]],
        raster_grid: dict,
        road_contributions: dict,
    ) -> List[Dict[str, Any]]:
        """Aggregate receptor-level road contributions to cluster-level hotspot attribution."""
        perf_enabled = logger.isEnabledFor(logging.DEBUG)
        perf_start = time.perf_counter()
        cell_receptor_map = raster_grid.get("cell_receptor_map", {})
        receptor_top_roads = road_contributions.get("receptor_top_roads", {})
        road_id_map = road_contributions.get("road_id_map", [])

        receptor_indices: set[int] = set()
        for row, col in cluster:
            receptor_indices.update(int(idx) for idx in cell_receptor_map.get(f"{row}_{col}", []))

        if not receptor_indices or not isinstance(receptor_top_roads, dict):
            return []

        if perf_enabled:
            logger.debug(
                "[PERF][Hotspot] Source attribution input: cluster_cells=%s mapped_cells=%s receptors=%s top_road_entries=%s",
                len(cluster),
                len(cell_receptor_map) if isinstance(cell_receptor_map, dict) else 0,
                len(receptor_indices),
                len(receptor_top_roads),
            )

        road_totals: dict[int, float] = {}
        road_labels: dict[int, str] = {}
        for receptor_idx in receptor_indices:
            contributions = receptor_top_roads.get(str(receptor_idx))
            if contributions is None:
                contributions = receptor_top_roads.get(receptor_idx, [])
            for item in contributions or []:
                if isinstance(item, dict):
                    road_idx = item.get("road_idx")
                    contribution = item.get("contribution", item.get("contribution_value", 0.0))
                    road_id = item.get("road_id")
                else:
                    if not isinstance(item, (list, tuple)) or len(item) < 2:
                        continue
                    road_idx, contribution = item[0], item[1]
                    road_id = None
                try:
                    normalized_idx = int(road_idx)
                except (TypeError, ValueError):
                    continue
                contribution_value = float(contribution)
                if contribution_value <= 0:
                    continue
                road_totals[normalized_idx] = road_totals.get(normalized_idx, 0.0) + contribution_value
                if road_id:
                    road_labels[normalized_idx] = str(road_id)

        if not road_totals:
            return []

        total_contribution = float(sum(road_totals.values()))
        sorted_roads = sorted(road_totals.items(), key=lambda item: item[1], reverse=True)[:10]
        result: list[dict[str, Any]] = []
        for road_idx, contribution in sorted_roads:
            road_id = road_labels.get(road_idx)
            if road_id is None and 0 <= road_idx < len(road_id_map):
                road_id = str(road_id_map[road_idx])
            if road_id is None:
                road_id = f"road_{road_idx}"
            result.append(
                {
                    "link_id": road_id,
                    "contribution_pct": round((contribution / total_contribution) * 100.0, 1)
                    if total_contribution > 0
                    else 0.0,
                    "contribution_value": round(float(contribution), 6),
                }
            )
        if perf_enabled:
            logger.debug(
                "[PERF][Hotspot] Source attribution: %.4fs roads=%s",
                time.perf_counter() - perf_start,
                len(result),
            )
        return result

    def _build_interpretation(
        self,
        coverage_assessment: Optional[dict],
        method: str,
        percentile: Optional[float],
        threshold_value: Optional[float],
        unit: str,
    ) -> str:
        """Adjust hotspot wording according to road network coverage quality."""
        level = coverage_assessment.get("level", "unknown") if isinstance(coverage_assessment, dict) else "unknown"

        if method == "percentile":
            method_desc = f"浓度最高的 {float(percentile):g}% 栅格区域"
        else:
            method_desc = f"浓度超过 {float(threshold_value):g} {unit} 的区域"

        if level == "complete_regional":
            return f"区域污染热点识别：{method_desc}"
        if level == "partial_regional":
            return f"区域污染热点识别（路网部分缺失，热点分布可能不完整）：{method_desc}"
        return f"已上传道路范围内的局部热点贡献识别（非完整区域分析）：{method_desc}"

    def _build_summary(
        self,
        hotspots: List[HotspotArea],
        matrix: np.ndarray,
        resolution: float,
        method: str,
        cutoff: float,
        unit: str = "μg/m³",
    ) -> Dict[str, Any]:
        """Build compact numeric summary of the hotspot extraction result."""
        total_hotspot_area = float(sum(hotspot.area_m2 for hotspot in hotspots))
        total_grid_area = float(matrix.shape[0] * matrix.shape[1] * resolution * resolution)
        return {
            "hotspot_count": len(hotspots),
            "total_hotspot_area_m2": round(total_hotspot_area, 1),
            "area_fraction_pct": round((total_hotspot_area / total_grid_area) * 100.0, 2)
            if total_grid_area > 0
            else 0.0,
            "max_concentration": round(max((hotspot.max_conc for hotspot in hotspots), default=0.0), 4),
            "cutoff_value": round(float(cutoff), 4),
            "method": method,
            "unit": unit,
        }


__all__ = ["HotspotAnalyzer", "HotspotArea", "HotspotAnalysisResult"]
