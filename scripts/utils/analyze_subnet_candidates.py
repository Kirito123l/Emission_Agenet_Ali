"""
Analyze Shanghai road-network subnet candidates.

This script scans projected square windows over the Shanghai road network,
computes per-window metrics, and writes candidate tables for later selection.
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LOGGER = logging.getLogger("analyze_subnet_candidates")
TARGET_CRS = "EPSG:32651"
CITY_CRS = "EPSG:4326"
WINDOW_SPECS = (
    {"size_m": 1000, "stride_m": 500},
    {"size_m": 2000, "stride_m": 1000},
)
HIGHWAY_GROUPS = {
    "express": {"motorway", "motorway_link"},
    "arterial": {"trunk", "trunk_link", "primary", "primary_link"},
    "secondary": {"secondary", "secondary_link"},
}
HARD_FILTERS = {
    1000: {"min_links": 4, "min_nodes": 4, "min_total_length_m": 1500.0},
    2000: {"min_links": 6, "min_nodes": 6, "min_total_length_m": 4000.0},
}
MIN_CITY_COVER_RATIO = 0.70
MIN_LARGEST_COMPONENT_RATIO = 0.60
ORIENTATION_BIN_COUNT = 12
ORIENTATION_MAX_ENTROPY = math.log(ORIENTATION_BIN_COUNT)


@dataclass(frozen=True)
class WindowSpec:
    size_m: int
    stride_m: int


class DisjointSet:
    def __init__(self) -> None:
        self.parent: Dict[str, str] = {}
        self.rank: Dict[str, int] = {}

    def add(self, key: str) -> None:
        if key in self.parent:
            return
        self.parent[key] = key
        self.rank[key] = 0

    def find(self, key: str) -> str:
        parent = self.parent[key]
        if parent != key:
            self.parent[key] = self.find(parent)
        return self.parent[key]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if self.rank[left_root] < self.rank[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if self.rank[left_root] == self.rank[right_root]:
            self.rank[left_root] += 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "GIS文件",
        help="Directory containing 上海市底图 and 上海市路网.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for candidate outputs. Defaults to <data-dir>/test_subnets.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    return parser.parse_args()


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def load_inputs(data_dir: Path) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    links_path = data_dir / "上海市路网" / "opt_link.shp"
    nodes_path = data_dir / "上海市路网" / "opt_node.shp"
    districts_path = data_dir / "上海市底图" / "上海市.shp"

    LOGGER.info("Loading links from %s", links_path)
    links = gpd.read_file(links_path, encoding="gbk")
    LOGGER.info("Loading nodes from %s", nodes_path)
    nodes = gpd.read_file(nodes_path, encoding="gbk")
    LOGGER.info("Loading districts from %s", districts_path)
    districts = gpd.read_file(districts_path, encoding="utf-8")

    if links.crs is None:
        links = links.set_crs(CITY_CRS, allow_override=True)
    if nodes.crs is None:
        nodes = nodes.set_crs(CITY_CRS, allow_override=True)
    if districts.crs is None:
        districts = districts.set_crs(CITY_CRS, allow_override=True)

    return links.to_crs(TARGET_CRS), nodes.to_crs(TARGET_CRS), districts.to_crs(TARGET_CRS)


def expand_line_geometries(geometry: BaseGeometry) -> Iterable[BaseGeometry]:
    if geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry]
    if geometry.geom_type == "MultiLineString":
        return list(geometry.geoms)
    if hasattr(geometry, "geoms"):
        lines = [geom for geom in geometry.geoms if geom.geom_type in {"LineString", "MultiLineString"}]
        expanded: List[BaseGeometry] = []
        for geom in lines:
            expanded.extend(expand_line_geometries(geom))
        return expanded
    return []


def compute_orientation_entropy(geometries: Sequence[BaseGeometry]) -> float:
    bins = np.zeros(ORIENTATION_BIN_COUNT, dtype=float)
    for geom in geometries:
        for line in expand_line_geometries(geom):
            coords = list(line.coords)
            for start, end in zip(coords, coords[1:]):
                dx = end[0] - start[0]
                dy = end[1] - start[1]
                segment_length = math.hypot(dx, dy)
                if segment_length <= 1e-6:
                    continue
                angle = math.degrees(math.atan2(dy, dx)) % 180.0
                bin_idx = min(int(angle / (180.0 / ORIENTATION_BIN_COUNT)), ORIENTATION_BIN_COUNT - 1)
                bins[bin_idx] += segment_length
    total = float(bins.sum())
    if total <= 0.0:
        return 0.0
    probs = bins[bins > 0.0] / total
    return float(-(probs * np.log(probs)).sum())


def largest_component_ratio(links_subset: pd.DataFrame, clipped_lengths: np.ndarray) -> float:
    if links_subset.empty:
        return 0.0

    dsu = DisjointSet()
    component_lengths: Dict[str, float] = {}

    for idx, row in links_subset.iterrows():
        from_node = str(row["from_node"])
        to_node = str(row["to_node"])
        dsu.add(from_node)
        dsu.add(to_node)
        dsu.union(from_node, to_node)

    total_length = float(clipped_lengths.sum())
    if total_length <= 0.0:
        return 0.0

    for (idx, row), length in zip(links_subset.iterrows(), clipped_lengths, strict=False):
        from_node = str(row["from_node"])
        root = dsu.find(from_node)
        component_lengths[root] = component_lengths.get(root, 0.0) + float(length)

    return float(max(component_lengths.values(), default=0.0) / total_length)


def classify_highway_ratios(links_subset: pd.DataFrame, clipped_lengths: np.ndarray) -> tuple[float, float, float]:
    total_length = float(clipped_lengths.sum())
    if total_length <= 0.0:
        return 0.0, 0.0, 0.0

    group_lengths = {"express": 0.0, "arterial": 0.0, "secondary": 0.0}
    for (_, row), length in zip(links_subset.iterrows(), clipped_lengths, strict=False):
        highway = row["highway"]
        for name, classes in HIGHWAY_GROUPS.items():
            if highway in classes:
                group_lengths[name] += float(length)
                break

    return (
        float(group_lengths["express"] / total_length),
        float(group_lengths["arterial"] / total_length),
        float(group_lengths["secondary"] / total_length),
    )


def compute_filter_reasons(
    size_m: int,
    link_count: int,
    node_count: int,
    total_length_m: float,
    largest_ratio: float,
) -> list[str]:
    filters = HARD_FILTERS[size_m]
    reasons: list[str] = []
    if link_count < filters["min_links"]:
        reasons.append(f"link_count<{filters['min_links']}")
    if node_count < filters["min_nodes"]:
        reasons.append(f"node_count<{filters['min_nodes']}")
    if total_length_m < filters["min_total_length_m"]:
        reasons.append(f"total_length_m<{int(filters['min_total_length_m'])}")
    if largest_ratio < MIN_LARGEST_COMPONENT_RATIO:
        reasons.append(f"largest_component_ratio<{MIN_LARGEST_COMPONENT_RATIO}")
    return reasons


def analyze_windows(
    links: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
    districts: gpd.GeoDataFrame,
    window_spec: WindowSpec,
) -> tuple[pd.DataFrame, dict]:
    city_union = districts.geometry.union_all() if hasattr(districts.geometry, "union_all") else districts.unary_union
    district_sindex = districts.sindex
    link_sindex = links.sindex
    node_sindex = nodes.sindex
    transformer = Transformer.from_crs(TARGET_CRS, CITY_CRS, always_xy=True)

    minx, miny, maxx, maxy = districts.total_bounds
    xs = np.arange(minx, maxx - window_spec.size_m + 1, window_spec.stride_m)
    ys = np.arange(miny, maxy - window_spec.size_m + 1, window_spec.stride_m)

    LOGGER.info(
        "Scanning %sm windows with %sm stride (%s x %s grid)",
        window_spec.size_m,
        window_spec.stride_m,
        len(xs),
        len(ys),
    )

    window_area = float(window_spec.size_m * window_spec.size_m)
    rows: list[dict] = []
    scanned_windows = 0
    city_cover_kept = 0
    zero_link_windows = 0

    for x in xs:
        for y in ys:
            scanned_windows += 1
            window = box(x, y, x + window_spec.size_m, y + window_spec.size_m)
            district_idx = list(district_sindex.intersection(window.bounds))
            if not district_idx:
                continue

            district_subset = districts.iloc[district_idx]
            overlap_areas = district_subset.geometry.intersection(window).area
            city_cover_ratio = float(overlap_areas.sum() / window_area)
            if city_cover_ratio < MIN_CITY_COVER_RATIO:
                continue
            city_cover_kept += 1

            dominant_district = str(district_subset.iloc[int(overlap_areas.argmax())]["name"])

            link_idx = list(link_sindex.intersection(window.bounds))
            if not link_idx:
                zero_link_windows += 1
                continue

            links_subset = links.iloc[link_idx].copy()
            clipped_geometries = links_subset.geometry.intersection(window)
            non_empty_mask = ~clipped_geometries.is_empty
            if not non_empty_mask.any():
                zero_link_windows += 1
                continue

            links_subset = links_subset.loc[non_empty_mask].copy()
            links_subset["clipped_geometry"] = clipped_geometries.loc[non_empty_mask]
            clipped_lengths = links_subset["clipped_geometry"].length.to_numpy(dtype=float)
            total_length_m = float(clipped_lengths.sum())
            if total_length_m <= 0.0:
                zero_link_windows += 1
                continue

            links_subset["is_boundary_cut"] = ~links_subset.geometry.covered_by(window)
            link_count = int(len(links_subset))
            boundary_cut_ratio = float(links_subset["is_boundary_cut"].mean())
            express_ratio, arterial_ratio, secondary_ratio = classify_highway_ratios(links_subset, clipped_lengths)
            lcc_ratio = largest_component_ratio(links_subset, clipped_lengths)
            orientation_entropy = compute_orientation_entropy(list(links_subset["clipped_geometry"]))

            node_idx = list(node_sindex.intersection(window.bounds))
            if node_idx:
                node_subset = nodes.iloc[node_idx]
                node_count = int(node_subset.geometry.covered_by(window).sum())
            else:
                node_count = 0

            center_x = float(x + window_spec.size_m / 2.0)
            center_y = float(y + window_spec.size_m / 2.0)
            center_lon, center_lat = transformer.transform(center_x, center_y)
            density = float(total_length_m / 1000.0 / (window_area / 1_000_000.0))
            filter_reasons = compute_filter_reasons(
                window_spec.size_m,
                link_count,
                node_count,
                total_length_m,
                lcc_ratio,
            )

            rows.append(
                {
                    "candidate_id": f"cand_{window_spec.size_m}_{len(rows) + 1:05d}",
                    "size_m": window_spec.size_m,
                    "stride_m": window_spec.stride_m,
                    "x_min": float(x),
                    "y_min": float(y),
                    "x_max": float(x + window_spec.size_m),
                    "y_max": float(y + window_spec.size_m),
                    "center_x": center_x,
                    "center_y": center_y,
                    "center_lon": float(center_lon),
                    "center_lat": float(center_lat),
                    "dominant_district": dominant_district,
                    "city_cover_ratio": city_cover_ratio,
                    "link_count": link_count,
                    "node_count": node_count,
                    "total_length_m": total_length_m,
                    "length_density_km_per_km2": density,
                    "express_ratio": express_ratio,
                    "arterial_ratio": arterial_ratio,
                    "secondary_ratio": secondary_ratio,
                    "largest_component_ratio": lcc_ratio,
                    "orientation_entropy": orientation_entropy,
                    "orientation_entropy_norm": float(
                        orientation_entropy / ORIENTATION_MAX_ENTROPY if ORIENTATION_MAX_ENTROPY else 0.0
                    ),
                    "boundary_cut_ratio": boundary_cut_ratio,
                    "passes_hard_filter": not filter_reasons,
                    "hard_filter_reason": ";".join(filter_reasons),
                }
            )

        LOGGER.info(
            "Processed %s/%s x-steps for %sm windows",
            int((x - xs[0]) / window_spec.stride_m) + 1,
            len(xs),
            window_spec.size_m,
        )

    stats = {
        "size_m": window_spec.size_m,
        "stride_m": window_spec.stride_m,
        "scanned_windows": scanned_windows,
        "city_cover_kept_windows": city_cover_kept,
        "candidate_windows": len(rows),
        "zero_link_windows": zero_link_windows,
        "hard_filter_pass_windows": int(sum(row["passes_hard_filter"] for row in rows)),
    }
    return pd.DataFrame(rows), stats


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)

    data_dir = args.data_dir.resolve()
    output_dir = (args.output_dir or (data_dir / "test_subnets")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    LOGGER.info("Using data directory: %s", data_dir)
    LOGGER.info("Writing outputs to: %s", output_dir)

    links, nodes, districts = load_inputs(data_dir)
    links = links[["highway", "from_node", "to_node", "geometry"]].copy()
    nodes = nodes[["node_id", "geometry"]].copy()
    districts = districts[["name", "geometry"]].copy()

    all_candidates: list[pd.DataFrame] = []
    scan_stats: list[dict] = []

    for spec_dict in WINDOW_SPECS:
        spec = WindowSpec(**spec_dict)
        candidates, stats = analyze_windows(links, nodes, districts, spec)
        all_candidates.append(candidates)
        scan_stats.append(stats)

    candidates_df = pd.concat(all_candidates, ignore_index=True)
    candidates_df.sort_values(["size_m", "center_x", "center_y"], inplace=True)
    scan_stats_df = pd.DataFrame(scan_stats).sort_values("size_m")

    candidates_path = output_dir / "candidates_all.csv"
    stats_path = output_dir / "scan_stats.csv"
    candidates_df.to_csv(candidates_path, index=False)
    scan_stats_df.to_csv(stats_path, index=False)

    LOGGER.info("Wrote %s", candidates_path)
    LOGGER.info("Wrote %s", stats_path)
    LOGGER.info("Candidate totals by size:\n%s", scan_stats_df.to_string(index=False))


if __name__ == "__main__":
    main()
