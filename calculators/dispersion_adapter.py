"""Adapter utilities for the macro-emission to dispersion pipeline."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple, Union

import geopandas as gpd
import pandas as pd
from shapely import wkt
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry
from shapely.geometry.geo import shape

logger = logging.getLogger(__name__)


class EmissionToDispersionAdapter:
    """
    Converts output from calculate_macro_emission tool into
    inputs suitable for DispersionCalculator.calculate().
    """

    @staticmethod
    def adapt(
        macro_result: Dict[str, Any],
        geometry_source: Union[List[Dict], gpd.GeoDataFrame, None] = None,
    ) -> Tuple[gpd.GeoDataFrame, pd.DataFrame]:
        """
        Transform macro emission result to dispersion inputs.

        Field mapping:
            macro_result.results[*].link_id -> NAME_1
            macro_result.results[*].total_emissions_kg_per_hr.NOx -> nox
            macro_result.results[*].link_length_km -> length
            macro_result.results[*].geometry -> geometry
        """
        if macro_result.get("status") != "success":
            raise ValueError("macro_result must be a successful macro emission calculation result")

        results = macro_result.get("data", {}).get("results", [])
        if not isinstance(results, list) or not results:
            raise ValueError("macro_result.data.results is required")

        roads_gdf = EmissionToDispersionAdapter._extract_geometry(results, geometry_source)
        emissions_df = EmissionToDispersionAdapter._build_emissions_df(results, "NOx")
        return roads_gdf, emissions_df

    @staticmethod
    def _extract_geometry(
        results: List[Dict],
        geometry_source: Union[List[Dict], gpd.GeoDataFrame, None],
    ) -> gpd.GeoDataFrame:
        """Extract and parse road geometry from result payloads or an external source."""
        geometry_map: Dict[str, Any] = {}

        def add_records(records: List[Dict]) -> None:
            for record in records:
                link_id = record.get("link_id") or record.get("NAME_1")
                if not link_id:
                    continue
                if "geometry" in record:
                    geometry_map[str(link_id)] = record.get("geometry")

        if isinstance(geometry_source, gpd.GeoDataFrame):
            gdf = geometry_source.copy()
            if "NAME_1" not in gdf.columns and "link_id" in gdf.columns:
                gdf = gdf.rename(columns={"link_id": "NAME_1"})
            if "NAME_1" not in gdf.columns or "geometry" not in gdf.columns:
                raise ValueError("geometry_source GeoDataFrame must contain NAME_1/link_id and geometry")
            return gpd.GeoDataFrame(gdf[["NAME_1", "geometry"]].copy(), geometry="geometry", crs=gdf.crs or "EPSG:4326")

        if isinstance(geometry_source, list):
            add_records(geometry_source)

        add_records(results)

        rows = []
        for record in results:
            link_id = record.get("link_id")
            if not link_id:
                continue
            raw_geometry = geometry_map.get(str(link_id))
            geometry = EmissionToDispersionAdapter._parse_geometry(raw_geometry)
            if geometry is None:
                logger.warning("Missing geometry for link_id=%s during dispersion adaptation", link_id)
                continue
            rows.append({"NAME_1": str(link_id), "geometry": geometry})

        if not rows:
            return gpd.GeoDataFrame({"NAME_1": [], "geometry": []}, geometry="geometry", crs="EPSG:4326")
        return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")

    @staticmethod
    def _parse_geometry(raw_geometry: Any) -> BaseGeometry | None:
        """Parse geometry payloads from WKT, GeoJSON, coordinate lists, or shapely objects."""
        if raw_geometry is None:
            return None
        if isinstance(raw_geometry, BaseGeometry):
            return raw_geometry
        if isinstance(raw_geometry, str):
            try:
                return wkt.loads(raw_geometry)
            except Exception:
                return None
        if isinstance(raw_geometry, dict):
            if "type" in raw_geometry and "coordinates" in raw_geometry:
                try:
                    return shape(raw_geometry)
                except Exception:
                    return None
            if "geometry" in raw_geometry:
                return EmissionToDispersionAdapter._parse_geometry(raw_geometry["geometry"])
            if "wkt" in raw_geometry:
                return EmissionToDispersionAdapter._parse_geometry(raw_geometry["wkt"])
            return None
        if isinstance(raw_geometry, (list, tuple)) and raw_geometry:
            first = raw_geometry[0]
            if isinstance(first, (list, tuple)) and len(first) >= 2:
                try:
                    return LineString(raw_geometry)
                except Exception:
                    return None
        return None

    @staticmethod
    def _build_emissions_df(results: List[Dict], pollutant: str) -> pd.DataFrame:
        """
        Build emissions DataFrame from macro results.

        Since macro emission gives a single time snapshot,
        we create a single-timestep emission with a synthetic data_time.
        """
        pollutant_key = pollutant
        rows = []
        for result in results:
            link_id = result.get("link_id")
            emissions = result.get("total_emissions_kg_per_hr", {})
            rows.append(
                {
                    "NAME_1": str(link_id),
                    "data_time": pd.Timestamp(result.get("data_time", "2024-01-01 00:00:00")),
                    pollutant.lower(): float(emissions.get(pollutant_key, 0.0)),
                    "length": float(result.get("link_length_km", 0.0)),
                }
            )
        return pd.DataFrame(rows)


__all__ = ["EmissionToDispersionAdapter"]
