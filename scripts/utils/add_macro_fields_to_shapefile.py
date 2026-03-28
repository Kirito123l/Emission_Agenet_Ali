#!/usr/bin/env python3
"""Populate flow/speed fields on a shapefile using the repo default typical profile."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.remediation_policy import resolve_avg_speed_kph, resolve_traffic_flow_vph


NUMERIC_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
SHAPEFILE_SUFFIXES = (".shp", ".shx", ".dbf", ".prj", ".cpg")


def _parse_lane_count(value: object) -> Optional[int]:
    """Parse a lane count from shapefile values like 2, '2', or '2;3'."""
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return int(value)

    match = NUMERIC_PATTERN.search(str(value))
    if not match:
        return None

    try:
        return int(float(match.group(0)))
    except ValueError:
        return None


def _parse_maxspeed(value: object) -> Optional[float]:
    """Parse a numeric maxspeed from shapefile values like '40', '40.0', or '40;60'."""
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric if numeric > 0 else None

    match = NUMERIC_PATTERN.search(str(value))
    if not match:
        return None

    try:
        numeric = float(match.group(0))
    except ValueError:
        return None
    return numeric if numeric > 0 else None


def enrich_macro_fields(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Return a copy with populated flow/speed columns."""
    enriched = gdf.copy()

    flow_values = []
    speed_values = []
    for row in enriched.itertuples(index=False):
        row_dict = row._asdict()
        highway = row_dict.get("highway")
        lanes = _parse_lane_count(row_dict.get("lanes"))
        maxspeed = _parse_maxspeed(row_dict.get("maxspeed"))

        flow = int(round(resolve_traffic_flow_vph(highway=highway, lanes=lanes)))
        speed = int(round(resolve_avg_speed_kph(maxspeed=maxspeed, highway=highway)))
        flow_values.append(flow)
        speed_values.append(speed)

    enriched["flow"] = pd.Series(flow_values, dtype="int64")
    enriched["speed"] = pd.Series(speed_values, dtype="int64")
    return enriched


def _write_shapefile(gdf: gpd.GeoDataFrame, output_path: Path) -> None:
    """Write shapefile atomically by staging into a temp directory first."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=output_path.parent) as temp_dir:
        staged_path = Path(temp_dir) / output_path.name
        gdf.to_file(staged_path, driver="ESRI Shapefile", index=False)

        for suffix in SHAPEFILE_SUFFIXES:
            final_component = output_path.with_suffix(suffix)
            staged_component = staged_path.with_suffix(suffix)
            if final_component.exists():
                final_component.unlink()
            if staged_component.exists():
                shutil.move(str(staged_component), str(final_component))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Add flow/speed fields to a shapefile using repo default typical profile."
    )
    parser.add_argument("input_shp", help="Input shapefile path (.shp)")
    parser.add_argument(
        "--output-shp",
        help="Optional output shapefile path. If omitted, requires --in-place.",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the input shapefile components in place.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    input_path = Path(args.input_shp).resolve()
    if input_path.suffix.lower() != ".shp":
        parser.error("input_shp must point to a .shp file")
    if not input_path.exists():
        parser.error(f"input shapefile not found: {input_path}")
    if not args.in_place and not args.output_shp:
        parser.error("provide --output-shp or use --in-place")

    output_path = input_path if args.in_place else Path(args.output_shp).resolve()

    gdf = gpd.read_file(input_path)
    enriched = enrich_macro_fields(gdf)
    _write_shapefile(enriched, output_path)

    print(f"updated_shapefile={output_path}")
    print(f"rows={len(enriched)}")
    print(f"columns={list(enriched.columns)}")
    print(
        "flow_stats="
        f"min:{int(enriched['flow'].min())},max:{int(enriched['flow'].max())},"
        f"mean:{round(float(enriched['flow'].mean()), 2)}"
    )
    print(
        "speed_stats="
        f"min:{int(enriched['speed'].min())},max:{int(enriched['speed'].max())},"
        f"mean:{round(float(enriched['speed'].mean()), 2)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
