"""
Create simplified case directories with only one road-network Shapefile set
and one preview image per case.
"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LOGGER = logging.getLogger("export_minimal_case_dirs")
DEFAULT_ROOT = PROJECT_ROOT / "GIS文件" / "test_subnets"
MINIMAL_DIRNAME = "精简文件"
REQUIRED_SOURCE_FILES = (
    "links.shp",
    "links.shx",
    "links.dbf",
    "links.prj",
    "links.cpg",
    "preview.png",
)
SHAPEFILE_EXTS = ("shp", "shx", "dbf", "prj", "cpg")
TARGET_CRS = "EPSG:32651"
CITY_CRS = "EPSG:4326"
DEFAULT_SPEED_KPH = {
    "motorway": 80,
    "motorway_link": 45,
    "trunk": 60,
    "trunk_link": 40,
    "primary": 50,
    "primary_link": 35,
    "secondary": 35,
    "secondary_link": 25,
}
DEFAULT_LANES = {
    "motorway": 4,
    "motorway_link": 1,
    "trunk": 3,
    "trunk_link": 1,
    "primary": 2,
    "primary_link": 1,
    "secondary": 2,
    "secondary_link": 1,
}
FLOW_PER_LANE_VPH = {
    "motorway": 1200,
    "motorway_link": 900,
    "trunk": 1000,
    "trunk_link": 800,
    "primary": 800,
    "primary_link": 650,
    "secondary": 550,
    "secondary_link": 450,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root-dir",
        type=Path,
        default=DEFAULT_ROOT,
        help="Directory containing manifest.csv and the exported full case directories.",
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


def validate_source_case(case_dir: Path, case_id: str) -> None:
    missing = [name for name in REQUIRED_SOURCE_FILES if not (case_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"{case_id}: missing source files: {', '.join(missing)}")


def parse_numeric(value) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group(0))


def build_minimal_roads(source_path: Path) -> gpd.GeoDataFrame:
    roads = gpd.read_file(source_path)
    if roads.crs is None:
        roads = roads.set_crs(CITY_CRS, allow_override=True)

    metric = roads.to_crs(TARGET_CRS)
    length_km = (metric.geometry.length / 1000.0).round(3)

    speeds: list[int] = []
    flows: list[int] = []
    link_ids: list[int] = []

    for idx, row in roads.iterrows():
        highway = str(row.get("highway", "") or "")
        default_speed = DEFAULT_SPEED_KPH.get(highway, 35)
        default_lanes = DEFAULT_LANES.get(highway, 1)
        flow_per_lane = FLOW_PER_LANE_VPH.get(highway, 500)

        lane_value = parse_numeric(row.get("lanes"))
        lanes = int(round(lane_value)) if lane_value and lane_value > 0 else default_lanes
        lanes = max(1, lanes)

        maxspeed_value = parse_numeric(row.get("maxspeed"))
        if maxspeed_value and maxspeed_value > 0:
            avg_speed = int(round(max(20.0, min(maxspeed_value * 0.8, 90.0))))
        else:
            avg_speed = default_speed

        flow = int(round(flow_per_lane * lanes))
        link_id_raw = row.get("link_id")
        link_id_val = parse_numeric(link_id_raw)
        link_ids.append(int(link_id_val) if link_id_val is not None else int(idx))
        speeds.append(avg_speed)
        flows.append(flow)

    minimal = gpd.GeoDataFrame(
        {
            "link_id": link_ids,
            "length": length_km,
            "flow": flows,
            "speed": speeds,
            "geometry": roads.geometry,
        },
        geometry="geometry",
        crs=roads.crs,
    )
    return minimal


def write_minimal_shapefile(gdf: gpd.GeoDataFrame, target_path: Path) -> None:
    gdf.to_file(target_path, driver="ESRI Shapefile", encoding="utf-8")


def write_minimal_excel(gdf: gpd.GeoDataFrame, target_path: Path) -> None:
    gdf[["link_id", "length", "flow", "speed"]].to_excel(target_path, index=False)


def copy_minimal_case(case_id: str, source_root: Path, target_root: Path) -> Path:
    source_dir = source_root / case_id
    validate_source_case(source_dir, case_id)

    target_dir = target_root / case_id
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    minimal_roads = build_minimal_roads(source_dir / "links.shp")
    write_minimal_shapefile(minimal_roads, target_dir / f"{case_id}.shp")
    write_minimal_excel(minimal_roads, target_dir / f"{case_id}.xlsx")
    shutil.copy2(source_dir / "preview.png", target_dir / "preview.png")
    return target_dir


def validate_minimal_case(case_id: str, target_dir: Path) -> None:
    required = [f"{case_id}.{ext}" for ext in SHAPEFILE_EXTS] + [f"{case_id}.xlsx", "preview.png"]
    missing = [name for name in required if not (target_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"{case_id}: missing minimal files: {', '.join(missing)}")

    files = sorted(p.name for p in target_dir.iterdir() if p.is_file())
    if len(files) != 7:
        raise ValueError(f"{case_id}: expected 7 files, found {len(files)} ({files})")

    roads = gpd.read_file(target_dir / f"{case_id}.shp")
    expected_cols = ["link_id", "length", "flow", "speed", "geometry"]
    if list(roads.columns) != expected_cols:
        raise ValueError(f"{case_id}: unexpected columns {list(roads.columns)}")
    if roads.empty:
        raise ValueError(f"{case_id}: empty road shapefile")

    excel = pd.read_excel(target_dir / f"{case_id}.xlsx")
    expected_excel_cols = ["link_id", "length", "flow", "speed"]
    if list(excel.columns) != expected_excel_cols:
        raise ValueError(f"{case_id}: unexpected excel columns {list(excel.columns)}")
    if len(excel) != len(roads):
        raise ValueError(f"{case_id}: excel row count {len(excel)} != shapefile row count {len(roads)}")


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)

    root_dir = args.root_dir.resolve()
    manifest_path = root_dir / "manifest.csv"
    minimal_root = root_dir / MINIMAL_DIRNAME
    minimal_root.mkdir(parents=True, exist_ok=True)

    manifest = pd.read_csv(manifest_path)
    created_dirs: list[Path] = []

    for case_id in manifest["case_id"].tolist():
        LOGGER.info("Creating minimal case for %s", case_id)
        target_dir = copy_minimal_case(case_id, root_dir, minimal_root)
        validate_minimal_case(case_id, target_dir)
        created_dirs.append(target_dir)

    LOGGER.info("Created %s minimal case directories in %s", len(created_dirs), minimal_root)


if __name__ == "__main__":
    main()
