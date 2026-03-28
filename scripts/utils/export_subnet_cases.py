"""
Export selected subnet cases from manifest.csv.

For each selected case, this script clips links and nodes, writes case-level
Shapefiles and metadata, generates a preview PNG, and validates the export.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

import geopandas as gpd
import matplotlib
import pandas as pd
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, Point, box
from shapely.geometry.base import BaseGeometry

matplotlib.use("Agg")
import matplotlib.pyplot as plt

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LOGGER = logging.getLogger("export_subnet_cases")
DATA_DIR_DEFAULT = PROJECT_ROOT / "GIS文件"
OUTPUT_DIR_DEFAULT = DATA_DIR_DEFAULT / "test_subnets"
TARGET_CRS = "EPSG:32651"
CITY_CRS = "EPSG:4326"
CASE_REQUIRED_FILES = (
    "links.shp",
    "links.shx",
    "links.dbf",
    "links.prj",
    "links.cpg",
    "nodes.shp",
    "nodes.shx",
    "nodes.dbf",
    "nodes.prj",
    "nodes.cpg",
    "summary.json",
    "preview.png",
)
PREVIEW_COLORS = {
    "motorway": "#c0392b",
    "motorway_link": "#e67e22",
    "trunk": "#d35400",
    "trunk_link": "#f39c12",
    "primary": "#2980b9",
    "primary_link": "#5dade2",
    "secondary": "#16a085",
    "secondary_link": "#48c9b0",
}
BOUNDARY_NODE_TOLERANCE_M = 1.0


@dataclass(frozen=True)
class Window:
    minx: float
    miny: float
    maxx: float
    maxy: float

    @property
    def geometry(self):
        return box(self.minx, self.miny, self.maxx, self.maxy)

    @property
    def area_m2(self) -> float:
        return (self.maxx - self.minx) * (self.maxy - self.miny)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.minx + self.maxx) / 2.0, (self.miny + self.maxy) / 2.0)


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
        default=DATA_DIR_DEFAULT,
        help="Directory containing source GIS data and manifest.csv outputs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR_DEFAULT,
        help="Directory containing manifest.csv and export outputs.",
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


def load_inputs(data_dir: Path) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    links_path = data_dir / "上海市路网" / "opt_link.shp"
    nodes_path = data_dir / "上海市路网" / "opt_node.shp"
    LOGGER.info("Loading links from %s", links_path)
    links = gpd.read_file(links_path, encoding="gbk")
    LOGGER.info("Loading nodes from %s", nodes_path)
    nodes = gpd.read_file(nodes_path, encoding="gbk")

    if links.crs is None:
        links = links.set_crs(CITY_CRS, allow_override=True)
    if nodes.crs is None:
        nodes = nodes.set_crs(CITY_CRS, allow_override=True)

    links_proj = links.to_crs(TARGET_CRS)
    nodes_proj = nodes.to_crs(TARGET_CRS)
    links_proj["from_node"] = links_proj["from_node"].astype(str)
    links_proj["to_node"] = links_proj["to_node"].astype(str)
    nodes_proj["node_id"] = nodes_proj["node_id"].astype(str)
    return links_proj, nodes_proj


def line_parts(geometry: BaseGeometry) -> list[LineString]:
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry]
    if geometry.geom_type == "MultiLineString":
        return [geom for geom in geometry.geoms if not geom.is_empty and geom.length > 0]
    if hasattr(geometry, "geoms"):
        parts: list[LineString] = []
        for geom in geometry.geoms:
            parts.extend(line_parts(geom))
        return parts
    return []


def normalize_linear_geometry(geometry: BaseGeometry) -> BaseGeometry | None:
    parts = line_parts(geometry)
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return MultiLineString(parts)


def largest_component_ratio(links_subset: pd.DataFrame) -> float:
    if links_subset.empty:
        return 0.0

    dsu = DisjointSet()
    component_lengths: Dict[str, float] = {}
    total_length = float(links_subset["clip_len_m"].sum())
    if total_length <= 0.0:
        return 0.0

    for _, row in links_subset.iterrows():
        dsu.add(str(row["from_node"]))
        dsu.add(str(row["to_node"]))
        dsu.union(str(row["from_node"]), str(row["to_node"]))

    for _, row in links_subset.iterrows():
        root = dsu.find(str(row["from_node"]))
        component_lengths[root] = component_lengths.get(root, 0.0) + float(row["clip_len_m"])

    return float(max(component_lengths.values(), default=0.0) / total_length)


def build_window(row: pd.Series) -> Window:
    size = float(row["size_m"])
    half = size / 2.0
    center_x = float(row["center_x"])
    center_y = float(row["center_y"])
    return Window(
        minx=center_x - half,
        miny=center_y - half,
        maxx=center_x + half,
        maxy=center_y + half,
    )


def nearest_node_id(point: Point, existing_nodes: Sequence[dict], tolerance_m: float) -> str | None:
    best_id = None
    best_dist = None
    for node in existing_nodes:
        dist = point.distance(node["geometry"])
        if dist <= tolerance_m and (best_dist is None or dist < best_dist):
            best_id = str(node["node_id"])
            best_dist = dist
    return best_id


def extract_endpoints(geometry: BaseGeometry) -> tuple[Point, Point]:
    parts = line_parts(geometry)
    first_part = parts[0]
    last_part = parts[-1]
    start = Point(first_part.coords[0])
    end = Point(last_part.coords[-1])
    return start, end


def prepare_nodes_for_case(
    nodes_proj: gpd.GeoDataFrame,
    links_case: gpd.GeoDataFrame,
    window: Window,
    case_id: str,
) -> gpd.GeoDataFrame:
    in_window = nodes_proj[nodes_proj.geometry.covered_by(window.geometry)].copy()
    original_nodes: list[dict] = []
    for _, row in in_window.iterrows():
        original_nodes.append(
            {
                "case_id": case_id,
                "node_id": str(row["node_id"]),
                "node_type": "original",
                "is_bound": 0,
                "src_node": str(row["node_id"]),
                "geometry": row.geometry,
            }
        )

    all_nodes = list(original_nodes)
    boundary_index = 1

    def ensure_node(point: Point) -> str:
        nonlocal boundary_index, all_nodes
        existing = nearest_node_id(point, all_nodes, BOUNDARY_NODE_TOLERANCE_M)
        if existing is not None:
            return existing
        node_id = f"bnd_{boundary_index:04d}"
        boundary_index += 1
        all_nodes.append(
            {
                "case_id": case_id,
                "node_id": node_id,
                "node_type": "boundary",
                "is_bound": 1,
                "src_node": "",
                "geometry": point,
            }
        )
        return node_id

    case_from_ids: list[str] = []
    case_to_ids: list[str] = []
    for _, row in links_case.iterrows():
        start_point, end_point = extract_endpoints(row.geometry)
        case_from_ids.append(ensure_node(start_point))
        case_to_ids.append(ensure_node(end_point))

    links_case["case_from"] = case_from_ids
    links_case["case_to"] = case_to_ids
    nodes_case = gpd.GeoDataFrame(all_nodes, geometry="geometry", crs=TARGET_CRS)
    return nodes_case


def clip_links_for_case(
    links_proj: gpd.GeoDataFrame,
    window: Window,
    case_id: str,
) -> gpd.GeoDataFrame:
    candidate_idx = list(links_proj.sindex.intersection(window.geometry.bounds))
    links_subset = links_proj.iloc[candidate_idx].copy()
    if links_subset.empty:
        return links_subset

    original_covered = links_subset.geometry.covered_by(window.geometry)
    clipped = links_subset.geometry.intersection(window.geometry)
    geometries: list[BaseGeometry] = []
    keep_mask: list[bool] = []
    for geom in clipped:
        linear = normalize_linear_geometry(geom)
        keep_mask.append(linear is not None and linear.length > 0)
        geometries.append(linear)

    links_subset = links_subset.loc[keep_mask].copy()
    if links_subset.empty:
        return links_subset

    kept_geometries = [geom for geom, keep in zip(geometries, keep_mask, strict=False) if keep]
    kept_covered = [covered for covered, keep in zip(original_covered, keep_mask, strict=False) if keep]
    links_subset["geometry"] = kept_geometries
    links_subset["clip_len_m"] = links_subset.geometry.length
    links_subset["cut_edge"] = [0 if covered else 1 for covered in kept_covered]
    links_subset["case_id"] = case_id
    return links_subset


def transform_bounds(bounds: tuple[float, float, float, float]) -> dict:
    transformer = Transformer.from_crs(TARGET_CRS, CITY_CRS, always_xy=True)
    minx, miny, maxx, maxy = bounds
    lon1, lat1 = transformer.transform(minx, miny)
    lon2, lat2 = transformer.transform(maxx, maxy)
    return {"minx": lon1, "miny": lat1, "maxx": lon2, "maxy": lat2}


def write_shapefile(gdf: gpd.GeoDataFrame, path: Path) -> None:
    gdf_wgs84 = gdf.to_crs(CITY_CRS)
    gdf_wgs84.to_file(path, driver="ESRI Shapefile", encoding="utf-8")


def create_preview(links_case: gpd.GeoDataFrame, window: Window, preview_path: Path, case_id: str) -> None:
    fig, ax = plt.subplots(figsize=(6, 6), dpi=160)
    plotted = False
    for highway, color in PREVIEW_COLORS.items():
        subset = links_case[links_case["highway"] == highway]
        if subset.empty:
            continue
        width = 1.6 if highway in {"motorway", "trunk", "primary"} else 1.1
        subset.plot(ax=ax, color=color, linewidth=width)
        plotted = True

    if not plotted and not links_case.empty:
        links_case.plot(ax=ax, color="#2c3e50", linewidth=1.1)

    boundary = gpd.GeoSeries([window.geometry], crs=TARGET_CRS)
    boundary.boundary.plot(ax=ax, color="#111111", linewidth=1.0, linestyle="--")
    ax.set_title(case_id, fontsize=10)
    ax.set_aspect("equal")
    ax.set_axis_off()
    fig.tight_layout(pad=0.4)
    fig.savefig(preview_path, bbox_inches="tight")
    plt.close(fig)


def build_summary(
    manifest_row: pd.Series,
    window: Window,
    links_case: gpd.GeoDataFrame,
    nodes_case: gpd.GeoDataFrame,
) -> dict:
    center_x, center_y = window.center
    transformer = Transformer.from_crs(TARGET_CRS, CITY_CRS, always_xy=True)
    center_lon, center_lat = transformer.transform(center_x, center_y)
    bbox_projected = {
        "minx": window.minx,
        "miny": window.miny,
        "maxx": window.maxx,
        "maxy": window.maxy,
    }
    bbox_wgs84 = transform_bounds((window.minx, window.miny, window.maxx, window.maxy))
    total_length_m = float(links_case["clip_len_m"].sum())
    size_m = int(manifest_row["size_m"])
    return {
        "case_id": manifest_row["case_id"],
        "profile": manifest_row["profile"],
        "size_m": size_m,
        "bbox_projected": bbox_projected,
        "bbox_wgs84": bbox_wgs84,
        "center_projected": {"x": center_x, "y": center_y},
        "center_wgs84": {"lon": center_lon, "lat": center_lat},
        "dominant_district": manifest_row["dominant_district"],
        "link_count": int(len(links_case)),
        "node_count": int(len(nodes_case)),
        "manifest_link_count": int(manifest_row["link_count"]),
        "manifest_node_count": int(manifest_row["node_count"]),
        "total_length_m": total_length_m,
        "length_density_km_per_km2": float(total_length_m / 1000.0 / (window.area_m2 / 1_000_000.0)),
        "largest_component_ratio": float(largest_component_ratio(links_case)),
        "boundary_cut_ratio": float(links_case["cut_edge"].mean() if len(links_case) else 0.0),
        "selection_reason": manifest_row["selection_reason"],
    }


def write_summary(summary: dict, path: Path) -> None:
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def build_export_index(rows: Sequence[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)[
        [
            "case_id",
            "profile",
            "size_m",
            "dominant_district",
            "link_count",
            "node_count",
            "total_length_m",
            "length_density_km_per_km2",
            "largest_component_ratio",
            "boundary_cut_ratio",
            "selection_reason",
            "case_dir",
        ]
    ].sort_values(["size_m", "case_id"])


def write_readme(output_dir: Path, export_index: pd.DataFrame) -> None:
    readme = f"""# Test Subnets

本目录包含根据 `manifest.csv` 从上海市完整路网裁剪出的测试子路网 case。

## 数据来源

- 原始路网：`上海市路网/opt_link.shp`、`上海市路网/opt_node.shp`
- 底图与筛选参考：`上海市底图/上海市.shp`
- 已确认的 case 清单：`manifest.csv`

## 筛选逻辑

- 先在 `EPSG:32651` 米制坐标系下按 `1km x 1km` 和 `2km x 2km` 滑窗扫描。
- 计算窗口内 `link_count`、`node_count`、总长度、密度、道路等级比例、连通性、方向熵、边界截断率。
- 按高密 / 中密 / 低密、规则 / 不规则、干道主导 / 混合 / 稀疏 / 走廊等类别筛选。
- 当前批次共导出 `{len(export_index)}` 个 case。

## 导出内容

每个 case 目录下包含：

- `links.*`：裁剪后的道路 Shapefile，全套文件
- `nodes.*`：case 节点 Shapefile，全套文件
- `summary.json`：核心统计与窗口范围
- `preview.png`：路网预览图

## 字段说明

`summary.json` 关键字段：

- `bbox_projected`：窗口投影坐标范围，单位米，坐标系 `EPSG:32651`
- `bbox_wgs84`：窗口经纬度范围，坐标系 `EPSG:4326`
- `center_projected` / `center_wgs84`：窗口中心点
- `link_count` / `node_count`：实际导出的 link / node 数量
- `manifest_link_count` / `manifest_node_count`：筛选阶段 manifest 中记录的数量
- `largest_component_ratio`：最大连通分量长度占比
- `boundary_cut_ratio`：被窗口边界截断的 link 比例

节点导出策略：

- 保留窗口内部原始节点
- 为被裁剪后的 link 边界端点补生成 `boundary` 节点，便于后续局部网络使用

## 使用建议

- 前端地图渲染：直接读取每个 case 的 `links.*` 或转 GeoJSON
- 扩散 / 受体点 / 栅格化测试：优先从 `summary.json` 中读取窗口尺度与密度指标
- 批量遍历：使用 `export_index.csv` 作为主索引

## 当前导出索引

`export_index.csv` 已汇总所有 case 的主要指标和目录位置。
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")


def validate_exports(output_dir: Path, export_index: pd.DataFrame) -> list[str]:
    errors: list[str] = []
    for _, row in export_index.iterrows():
        case_dir = Path(row["case_dir"])
        if not case_dir.exists():
            errors.append(f"{row['case_id']}: missing case directory")
            continue
        for filename in CASE_REQUIRED_FILES:
            if not (case_dir / filename).exists():
                errors.append(f"{row['case_id']}: missing {filename}")

        links_path = case_dir / "links.shp"
        nodes_path = case_dir / "nodes.shp"
        summary_path = case_dir / "summary.json"
        if not links_path.exists() or not nodes_path.exists() or not summary_path.exists():
            continue

        links = gpd.read_file(links_path)
        nodes = gpd.read_file(nodes_path)
        summary = json.loads(summary_path.read_text(encoding="utf-8"))

        if links.empty:
            errors.append(f"{row['case_id']}: empty links shapefile")
        if nodes.empty:
            errors.append(f"{row['case_id']}: empty nodes shapefile")
        if len(links) != int(summary["link_count"]):
            errors.append(f"{row['case_id']}: link_count mismatch")
        if len(nodes) != int(summary["node_count"]):
            errors.append(f"{row['case_id']}: node_count mismatch")

    if not (output_dir / "README.md").exists():
        errors.append("missing README.md")
    if not (output_dir / "export_index.csv").exists():
        errors.append("missing export_index.csv")
    return errors


def export_case(
    manifest_row: pd.Series,
    links_proj: gpd.GeoDataFrame,
    nodes_proj: gpd.GeoDataFrame,
    output_dir: Path,
) -> dict:
    case_id = str(manifest_row["case_id"])
    case_dir = output_dir / case_id
    if case_dir.exists():
        shutil.rmtree(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)

    window = build_window(manifest_row)
    links_case = clip_links_for_case(links_proj, window, case_id)
    if links_case.empty:
        raise ValueError(f"{case_id}: no links after clipping")

    nodes_case = prepare_nodes_for_case(nodes_proj, links_case, window, case_id)
    if nodes_case.empty:
        raise ValueError(f"{case_id}: no nodes after clipping")

    links_export = links_case[
        [
            "case_id",
            "highway",
            "name",
            "ref",
            "oneway",
            "bridge",
            "tunnel",
            "lanes",
            "motorroad",
            "maxspeed",
            "id",
            "osm_type",
            "from_node",
            "to_node",
            "length",
            "dir",
            "link_id",
            "case_from",
            "case_to",
            "cut_edge",
            "geometry",
        ]
    ].copy()
    nodes_export = nodes_case[["case_id", "node_id", "node_type", "is_bound", "src_node", "geometry"]].copy()

    write_shapefile(links_export, case_dir / "links.shp")
    write_shapefile(nodes_export, case_dir / "nodes.shp")

    summary = build_summary(manifest_row, window, links_case, nodes_case)
    write_summary(summary, case_dir / "summary.json")
    create_preview(links_case, window, case_dir / "preview.png", case_id)

    summary["case_dir"] = str(case_dir)
    return summary


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)

    data_dir = args.data_dir.resolve()
    output_dir = args.output_dir.resolve()
    manifest_path = output_dir / "manifest.csv"
    manifest = pd.read_csv(manifest_path)
    links_proj, nodes_proj = load_inputs(data_dir)

    exported_rows: list[dict] = []
    for _, manifest_row in manifest.iterrows():
        LOGGER.info("Exporting %s", manifest_row["case_id"])
        exported_rows.append(export_case(manifest_row, links_proj, nodes_proj, output_dir))

    export_index = build_export_index(exported_rows)
    export_index.to_csv(output_dir / "export_index.csv", index=False)
    write_readme(output_dir, export_index)

    errors = validate_exports(output_dir, export_index)
    if errors:
        for err in errors:
            LOGGER.error(err)
        raise SystemExit(f"Validation failed with {len(errors)} issue(s)")

    LOGGER.info("Exported %s cases successfully", len(export_index))


if __name__ == "__main__":
    main()
