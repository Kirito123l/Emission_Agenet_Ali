"""
EmissionAgent - Spatial Map Rendering Tool

Independent tool for rendering spatial data to interactive maps.
Accepts emission results, dispersion results, or direct GeoJSON input.
Outputs map_data in a format compatible with the current frontend.
"""
import json
import logging
import math
import re
from typing import Any, Dict, List, Optional

from tools.base import BaseTool, ToolResult
from core.spatial_types import SpatialDataPackage

logger = logging.getLogger(__name__)


def _parse_wkt_linestring(wkt_str: str) -> Optional[List[List[float]]]:
    """Parse WKT LINESTRING/MULTILINESTRING into [[lon, lat], ...] coordinates.

    Handles:
    - 'LINESTRING (lon lat, lon lat, ...)'
    - 'LINESTRING(lon lat, lon lat, ...)'  (no space after keyword)
    - 'MULTILINESTRING ((lon lat, lon lat), (lon lat, lon lat))'
    """
    if not isinstance(wkt_str, str):
        return None

    s = wkt_str.strip()
    coords: List[List[float]] = []

    try:
        upper = s.upper()
        if upper.startswith("LINESTRING"):
            paren_start = s.index("(")
            paren_end = s.rindex(")")
            inner = s[paren_start + 1 : paren_end].strip()

            for pair in inner.split(","):
                parts = pair.strip().split()
                if len(parts) >= 2:
                    coords.append([float(parts[0]), float(parts[1])])

        elif upper.startswith("MULTILINESTRING"):
            groups = re.findall(r"\(([^()]+)\)", s)
            for group in groups:
                for pair in group.split(","):
                    parts = pair.strip().split()
                    if len(parts) >= 2:
                        coords.append([float(parts[0]), float(parts[1])])
    except (ValueError, IndexError):
        return None

    return coords if len(coords) >= 2 else None


def _zoom_from_span(span: float) -> int:
    """Estimate a reasonable Leaflet zoom level from geographic span in degrees."""
    if span > 10:
        return 6
    if span > 5:
        return 7
    if span > 2:
        return 8
    if span > 1:
        return 9
    if span > 0.5:
        return 10
    if span > 0.2:
        return 11
    if span > 0.1:
        return 12
    if span > 0.05:
        return 13
    return 14


def _has_valid_contour_bands(payload: Any) -> bool:
    """Return whether a contour_bands payload is usable for rendering."""
    if not isinstance(payload, dict):
        return False
    if payload.get("error"):
        return False
    geojson = payload.get("geojson")
    if not isinstance(geojson, dict):
        return False
    features = geojson.get("features")
    return isinstance(features, list)


def _resolve_dispersion_pollutant(
    data: Dict[str, Any],
    result_data: Optional[Dict[str, Any]] = None,
    explicit: Optional[str] = None,
) -> str:
    """Resolve pollutant from a dispersion-like payload, falling back only when absent."""
    query_info = data.get("query_info", {}) if isinstance(data, dict) else {}
    result_data = result_data or {}
    return str(
        explicit
        or query_info.get("pollutant")
        or data.get("pollutant")
        or result_data.get("pollutant")
        or "NOx"
    )


def _resolve_concentration_unit(data: Dict[str, Any]) -> str:
    """Resolve concentration unit from result summary/query metadata."""
    summary = data.get("summary", {}) if isinstance(data, dict) else {}
    query_info = data.get("query_info", {}) if isinstance(data, dict) else {}
    return str(summary.get("unit") or query_info.get("unit") or data.get("unit") or "μg/m³")


class SpatialRendererTool(BaseTool):
    name = "render_spatial_map"
    description = "Render spatial data as an interactive map"

    async def execute(self, **kwargs) -> ToolResult:
        """Render spatial data to a map.

        Args:
            data_source: "last_result" to use previous tool output, or direct data dict
            pollutant: Which pollutant to visualize (for color mapping)
            title: Map title
            layer_type: "emission" | "concentration" | "points" (default: auto-detect)
        """
        try:
            data_source = kwargs.get("data_source", "last_result")
            pollutant = kwargs.get("pollutant")
            title = kwargs.get("title", "")
            layer_type = kwargs.get("layer_type")
            source_links = kwargs.get("source_links")

            # 1. Get the data to render
            if isinstance(data_source, dict):
                result_data = data_source
            elif data_source == "last_result":
                result_data = kwargs.get("_last_result")
                if not result_data:
                    return ToolResult(
                        success=False,
                        error="No previous result available to render",
                        data=None,
                        summary="No data source available for visualization",
                    )
            else:
                return ToolResult(
                    success=False,
                    error=f"Unknown data source: {data_source}",
                    data=None,
                    summary="Invalid data source",
                )

            # 2. Auto-detect layer type if not specified
            if not layer_type:
                layer_type = self._detect_layer_type(result_data)
            elif layer_type == "dispersion":
                layer_type = self._detect_dispersion_layer_type(result_data)

            # 3. Build map_data based on layer type
            if layer_type == "hotspot":
                map_data = self._build_hotspot_map(result_data, title)
            elif layer_type == "contour":
                map_data = self._build_contour_map(result_data, pollutant, title)
            elif layer_type == "raster":
                map_data = self._build_raster_map(result_data, pollutant, title)
            elif layer_type == "emission":
                map_data = self._build_emission_map(result_data, pollutant, title, source_links=source_links)
            elif layer_type == "concentration":
                map_data = self._build_concentration_map(result_data, pollutant, title)
            elif layer_type == "points":
                map_data = self._build_points_map(result_data, pollutant, title)
            else:
                map_data = self._build_emission_map(result_data, pollutant, title, source_links=source_links)

            if not map_data:
                error_messages = {
                    "hotspot": "Could not build hotspot map from provided data",
                    "contour": "Could not build contour concentration map from provided data",
                    "raster": "Could not build raster concentration map from provided data",
                    "concentration": "Could not build concentration map from provided data",
                    "points": "Could not build points map from provided data",
                    "emission": "Could not build emission map from provided data",
                }
                summary_messages = {
                    "hotspot": "Map rendering failed - no hotspot data found",
                    "contour": "Map rendering failed - no contour concentration data found",
                    "raster": "Map rendering failed - no raster concentration data found",
                    "concentration": "Map rendering failed - no concentration data found",
                    "points": "Map rendering failed - no point data found",
                    "emission": "Map rendering failed - no spatial data found",
                }
                return ToolResult(
                    success=False,
                    error=error_messages.get(layer_type, "Could not build map from provided data"),
                    data=None,
                    summary=summary_messages.get(layer_type, "Map rendering failed - no spatial data found"),
                )

            feature_count = (
                map_data.get("summary", {}).get("total_links")
                or map_data.get("summary", {}).get("receptor_count")
                or len(map_data.get("links", []))
                or len(map_data.get("layers", [{}])[0].get("data", {}).get("features", []))
            )

            return ToolResult(
                success=True,
                data={"map_config": map_data},
                summary=f"Map rendered: {feature_count} features",
                map_data=map_data,
            )

        except Exception as e:
            logger.error(f"Spatial rendering failed: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=str(e),
                data=None,
                summary=f"Map rendering error: {e}",
            )

    def _detect_layer_type(self, result_data: Dict) -> str:
        """Auto-detect what kind of spatial data this is."""
        if isinstance(result_data, dict):
            data = result_data.get("data", result_data)
            if data.get("type") == "hotspot" or "hotspots" in data:
                return "hotspot"
            if data.get("type") == "contour" or _has_valid_contour_bands(data.get("contour_bands")):
                return "contour"
            if data.get("type") == "raster" or "raster_grid" in data:
                return "raster"
            if "concentration_grid" in data or "concentration_geojson" in data:
                return "concentration"
            if "results" in data or "links" in data:
                return "emission"
            if "receptors" in data:
                return "points"
        return "emission"

    def _detect_dispersion_layer_type(self, result_data: Dict) -> str:
        """Choose the best dispersion visualization mode for current data."""
        data = result_data.get("data", result_data) if isinstance(result_data, dict) else {}
        if data.get("type") == "contour":
            return "contour"
        if _has_valid_contour_bands(data.get("contour_bands")):
            return "contour"
        if isinstance(data.get("raster_grid"), dict):
            return "raster"
        return "concentration"

    def _build_emission_map(
        self,
        result_data: Dict,
        pollutant: Optional[str],
        title: str,
        source_links: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict]:
        """Build map_data for emission results.

        Output format matches the current legacy format that the frontend expects:
        {type, center, zoom, pollutant, unit, color_scale, links, summary}
        """
        # Extract the actual data dict (handle both direct and wrapped formats)
        data = result_data.get("data", result_data)
        results = data.get("results", [])

        if not results:
            return None

        # Determine pollutant
        if not pollutant:
            query_info = data.get("query_info", {})
            pollutants = query_info.get("pollutants", [])
            if pollutants:
                pollutant = pollutants[0]
            else:
                first_result = results[0]
                emissions = first_result.get("total_emissions_kg_per_hr", {})
                if emissions:
                    pollutant = list(emissions.keys())[0]
                else:
                    pollutant = "CO2"

        geometry_lookup: Dict[str, Any] = {}
        if isinstance(source_links, list):
            for source_link in source_links:
                if not isinstance(source_link, dict):
                    continue
                link_id = str(source_link.get("link_id", "")).strip()
                geometry = source_link.get("geometry") or source_link.get("coordinates")
                if link_id and geometry:
                    geometry_lookup[link_id] = geometry

        # Build links array in legacy format
        map_links: List[Dict] = []
        emission_values: List[float] = []

        for link in results:
            geometry = (
                link.get("geometry")
                or link.get("coordinates")
                or geometry_lookup.get(str(link.get("link_id", "")).strip())
            )
            if not geometry:
                continue

            # Parse geometry if it's a string (JSON, GeoJSON, or WKT)
            if isinstance(geometry, str):
                geom_str = geometry
                geometry = None

                # Try JSON first
                try:
                    geom_parsed = json.loads(geom_str)
                    if isinstance(geom_parsed, dict) and "coordinates" in geom_parsed:
                        geometry = geom_parsed["coordinates"]
                    elif isinstance(geom_parsed, list):
                        geometry = geom_parsed
                except (json.JSONDecodeError, TypeError):
                    pass

                # If JSON failed, try WKT
                if geometry is None:
                    wkt_coords = _parse_wkt_linestring(geom_str)
                    if wkt_coords:
                        geometry = wkt_coords

                if geometry is None:
                    continue

            # Get emission values
            total_emissions = link.get("total_emissions_kg_per_hr", {})
            emission_rates = link.get("emission_rates_g_per_veh_km", {})
            link_length = link.get("link_length_km", 0)

            # Compute emission intensity (kg/h/km)
            emissions_intensity: Dict[str, float] = {}
            for pol, val in total_emissions.items():
                if link_length > 0:
                    emissions_intensity[pol] = round(val / link_length, 4)
                else:
                    emissions_intensity[pol] = round(val, 4)

            map_link = {
                "link_id": str(link.get("link_id", "")),
                "geometry": geometry,
                "emissions": emissions_intensity,
                "emission_rate": {k: round(v, 4) for k, v in emission_rates.items()},
                "link_length_km": round(link_length, 3),
                "avg_speed_kph": round(link.get("avg_speed_kph", 0), 1),
                "traffic_flow_vph": round(link.get("traffic_flow_vph", 0), 0),
            }
            map_links.append(map_link)

            pol_val = emissions_intensity.get(pollutant, 0)
            if pol_val > 0:
                emission_values.append(pol_val)

        if not map_links:
            return None

        # Compute color scale
        if emission_values:
            min_val = min(emission_values)
            max_val = max(emission_values)
        else:
            min_val, max_val = 0, 1

        # Compute bounds from geometry
        all_coords: List[List[float]] = []
        for link in map_links:
            geom = link.get("geometry", [])
            if isinstance(geom, list) and geom:
                for coord in geom:
                    if isinstance(coord, (list, tuple)) and len(coord) >= 2:
                        all_coords.append(coord)

        if all_coords:
            lons = [c[0] for c in all_coords]
            lats = [c[1] for c in all_coords]
            center = [(min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2]
        else:
            center = [31.23, 121.47]

        # Build pollutant list for summary
        all_pollutants: set = set()
        for link in map_links:
            all_pollutants.update(link.get("emissions", {}).keys())

        total_emissions_summary: Dict[str, float] = {}
        for pol in all_pollutants:
            total_emissions_summary[pol] = round(
                sum(link.get("emissions", {}).get(pol, 0) for link in map_links), 4
            )

        return {
            "type": "macro_emission_map",
            "center": center,
            "zoom": 12,
            "pollutant": pollutant,
            "scenario_label": str(data.get("scenario_label") or "baseline"),
            "unit": "kg/(h\u00b7km)",
            "color_scale": {
                "min": round(min_val, 4),
                "max": round(max_val, 4),
                "colors": ["#fee5d9", "#fcae91", "#fb6a4a", "#de2d26", "#a50f15"],
            },
            "links": map_links,
            "summary": {
                "total_links": len(map_links),
                "total_emissions_kg_per_hr": total_emissions_summary,
            },
        }

    def _build_concentration_map(
        self,
        result_data: Dict[str, Any],
        pollutant: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Build map data from concentration/dispersion results."""
        data = result_data.get("data", result_data)

        if not pollutant:
            pollutant = _resolve_dispersion_pollutant(data, result_data)

        source_receptors: List[Dict[str, Any]] = []
        concentration_grid = data.get("concentration_grid", {})
        grid_bounds = concentration_grid.get("bounds", {}) if isinstance(concentration_grid, dict) else {}

        if isinstance(concentration_grid, dict) and concentration_grid.get("receptors"):
            for index, receptor in enumerate(concentration_grid.get("receptors", [])):
                if not isinstance(receptor, dict):
                    continue
                source_receptors.append(
                    {
                        "receptor_id": receptor.get("receptor_id", index),
                        "lon": receptor.get("lon"),
                        "lat": receptor.get("lat"),
                        "mean_conc": receptor.get("mean_conc", receptor.get("value", 0.0)),
                        "max_conc": receptor.get("max_conc", receptor.get("mean_conc", 0.0)),
                    }
                )
        elif isinstance(data.get("results"), list):
            for index, receptor in enumerate(data.get("results", [])):
                if not isinstance(receptor, dict):
                    continue
                source_receptors.append(
                    {
                        "receptor_id": receptor.get("receptor_id", index),
                        "lon": receptor.get("lon"),
                        "lat": receptor.get("lat"),
                        "mean_conc": receptor.get("mean_conc", receptor.get("value", 0.0)),
                        "max_conc": receptor.get("max_conc", receptor.get("mean_conc", 0.0)),
                    }
                )

        if not source_receptors:
            return None

        positive_features: List[Dict[str, Any]] = []
        zero_features: List[Dict[str, Any]] = []
        all_mean_values: List[float] = []
        all_max_values: List[float] = []

        for receptor in source_receptors:
            try:
                lon = float(receptor.get("lon"))
                lat = float(receptor.get("lat"))
                mean_conc = float(receptor.get("mean_conc", 0.0))
                max_conc = float(receptor.get("max_conc", mean_conc))
            except (TypeError, ValueError):
                continue

            if any(value != value for value in (lon, lat, mean_conc, max_conc)):
                continue

            all_mean_values.append(mean_conc)
            all_max_values.append(max_conc)

            receptor_id = receptor.get("receptor_id", len(all_mean_values) - 1)
            if not isinstance(receptor_id, int):
                try:
                    receptor_id = int(receptor_id)
                except (TypeError, ValueError):
                    receptor_id = len(all_mean_values) - 1

            feature = {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "receptor_id": receptor_id,
                    "mean_conc": mean_conc,
                    "max_conc": max_conc,
                    "value": mean_conc,
                },
            }

            if mean_conc > 0:
                positive_features.append(feature)
            else:
                zero_features.append(feature)

        if not positive_features and not zero_features:
            return None

        features = positive_features
        if not features:
            logger.warning("All concentration receptors are zero or non-positive; rendering zero-value receptors")
            features = zero_features

        feature_collection = {
            "type": "FeatureCollection",
            "features": features,
        }

        bounds_info = SpatialDataPackage.compute_bounds_from_geojson(feature_collection)
        center = bounds_info.get("center", [31.23, 121.47])
        zoom = bounds_info.get("zoom", 12)

        if isinstance(grid_bounds, dict) and all(
            key in grid_bounds for key in ("min_lon", "max_lon", "min_lat", "max_lat")
        ):
            try:
                min_lon = float(grid_bounds["min_lon"])
                max_lon = float(grid_bounds["max_lon"])
                min_lat = float(grid_bounds["min_lat"])
                max_lat = float(grid_bounds["max_lat"])
                center = [(min_lat + max_lat) / 2, (min_lon + max_lon) / 2]
                span = max(max_lon - min_lon, max_lat - min_lat)
                if span > 10:
                    zoom = 6
                elif span > 5:
                    zoom = 7
                elif span > 2:
                    zoom = 8
                elif span > 1:
                    zoom = 9
                elif span > 0.5:
                    zoom = 10
                elif span > 0.2:
                    zoom = 11
                elif span > 0.1:
                    zoom = 12
                elif span > 0.05:
                    zoom = 13
                else:
                    zoom = 14
            except (TypeError, ValueError):
                pass

        summary = data.get("summary", {})
        unit = _resolve_concentration_unit(data)
        min_value = min((feature["properties"]["value"] for feature in features), default=0.0)
        max_value = max((feature["properties"]["value"] for feature in features), default=0.0)

        return {
            "type": "concentration",
            "title": title or f"{pollutant} Concentration Distribution",
            "pollutant": pollutant,
            "scenario_label": str(data.get("scenario_label") or "baseline"),
            "center": center,
            "zoom": zoom,
            "layers": [
                {
                    "id": "concentration_points",
                    "type": "circle",
                    "data": feature_collection,
                    "style": {
                        "radius": 6,
                        "color_field": "value",
                        "color_scale": "YlOrRd",
                        "value_range": [float(min_value), float(max_value)],
                        "opacity": 0.85,
                        "legend_title": f"{pollutant} Concentration",
                        "legend_unit": unit,
                    },
                }
            ],
            "summary": {
                "receptor_count": int(summary.get("receptor_count", len(source_receptors))),
                "mean_concentration": float(
                    summary.get(
                        "mean_concentration",
                        sum(all_mean_values) / len(all_mean_values) if all_mean_values else 0.0,
                    )
                ),
                "max_concentration": float(
                    summary.get("max_concentration", max(all_max_values) if all_max_values else 0.0)
                ),
                "unit": unit,
            },
        }

    def _build_raster_map(
        self,
        result_data: Dict[str, Any],
        pollutant: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Build polygon-based concentration map data from a raster grid."""
        data = result_data.get("data", result_data)
        raster = data.get("raster_grid")
        if not isinstance(raster, dict):
            return None

        cell_centers = raster.get("cell_centers_wgs84", [])
        if not isinstance(cell_centers, list) or not cell_centers:
            return None

        resolution = float(raster.get("resolution_m", 50.0))
        pollutant = _resolve_dispersion_pollutant(data, result_data, pollutant)
        unit = _resolve_concentration_unit(data)

        values: List[float] = []
        features: List[Dict[str, Any]] = []
        lons: List[float] = []
        lats: List[float] = []

        for cell in cell_centers:
            try:
                mean_conc = float(cell.get("mean_conc", 0.0))
                max_conc = float(cell.get("max_conc", mean_conc))
                lon = float(cell["lon"])
                lat = float(cell["lat"])
            except (KeyError, TypeError, ValueError):
                continue

            if mean_conc <= 0:
                continue

            cos_lat = math.cos(math.radians(lat))
            if abs(cos_lat) < 1e-6:
                cos_lat = 1e-6
            dlat = (resolution / 2.0) / 111320.0
            dlon = (resolution / 2.0) / (111320.0 * cos_lat)

            values.append(mean_conc)
            lons.append(lon)
            lats.append(lat)

            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [lon - dlon, lat - dlat],
                            [lon + dlon, lat - dlat],
                            [lon + dlon, lat + dlat],
                            [lon - dlon, lat + dlat],
                            [lon - dlon, lat - dlat],
                        ]],
                    },
                    "properties": {
                        "row": cell.get("row"),
                        "col": cell.get("col"),
                        "mean_conc": round(mean_conc, 4),
                        "max_conc": round(max_conc, 4),
                        "value": round(mean_conc, 4),
                    },
                }
            )

        if not features or not values:
            logger.warning("All raster cells have zero concentration; skipping raster map build")
            return None

        min_lon = min(lons)
        max_lon = max(lons)
        min_lat = min(lats)
        max_lat = max(lats)
        center = [(min_lat + max_lat) / 2.0, (min_lon + max_lon) / 2.0]
        zoom = _zoom_from_span(max(max_lon - min_lon, max_lat - min_lat))
        stats = raster.get("stats", {}) if isinstance(raster.get("stats"), dict) else {}

        return {
            "type": "raster",
            "title": title or f"{pollutant} Concentration Field ({int(round(resolution))}m grid)",
            "pollutant": pollutant,
            "scenario_label": str(data.get("scenario_label") or "baseline"),
            "center": center,
            "zoom": zoom,
            "layers": [
                {
                    "id": "concentration_raster",
                    "type": "polygon",
                    "data": {"type": "FeatureCollection", "features": features},
                    "style": {
                        "color_field": "value",
                        "color_scale": "YlOrRd",
                        "value_range": [round(min(values), 4), round(max(values), 4)],
                        "opacity": 0.7,
                        "stroke": False,
                        "legend_title": f"{pollutant} Concentration",
                        "legend_unit": unit,
                        "resolution_m": resolution,
                    },
                }
            ],
            "coverage_assessment": data.get("coverage_assessment", {}),
            "summary": {
                "total_cells": int(stats.get("total_cells", 0)),
                "nonzero_cells": int(stats.get("nonzero_cells", len(features))),
                "resolution_m": resolution,
                "mean_concentration": round(sum(values) / len(values), 4),
                "max_concentration": round(max(values), 4),
                "unit": unit,
            },
        }

    def _build_contour_map(
        self,
        result_data: Dict[str, Any],
        pollutant: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Build contour-band map data from dispersion contour output."""
        data = result_data.get("data", result_data)
        contour_bands = data.get("contour_bands")
        if not _has_valid_contour_bands(contour_bands):
            return None

        geojson = contour_bands.get("geojson", {})
        features = geojson.get("features", [])
        if not isinstance(features, list):
            return None

        pollutant = _resolve_dispersion_pollutant(data, result_data, pollutant)

        bbox = contour_bands.get("bbox_wgs84")
        center = [31.23, 121.47]
        zoom = 12
        if isinstance(bbox, list) and len(bbox) >= 4:
            try:
                min_lon, min_lat, max_lon, max_lat = [float(value) for value in bbox[:4]]
                center = [(min_lat + max_lat) / 2.0, (min_lon + max_lon) / 2.0]
                zoom = _zoom_from_span(max(max_lon - min_lon, max_lat - min_lat))
            except (TypeError, ValueError):
                pass

        stats = contour_bands.get("stats", {}) if isinstance(contour_bands.get("stats"), dict) else {}
        interp_resolution = float(contour_bands.get("interp_resolution_m", 10.0))
        n_levels = int(contour_bands.get("n_levels", len(contour_bands.get("levels", [])) or 0))
        unit = _resolve_concentration_unit(data)

        return {
            "type": "contour",
            "title": title or f"{pollutant} Concentration Field (contour)",
            "pollutant": pollutant,
            "scenario_label": str(data.get("scenario_label") or "baseline"),
            "center": center,
            "zoom": zoom,
            "layers": [
                {
                    "id": "concentration_contour",
                    "type": "filled_contour",
                    "data": geojson,
                    "style": {
                        "color_field": "level_index",
                        "color_scale": "YlOrRd",
                        "n_levels": n_levels,
                        "levels": contour_bands.get("levels", []),
                        "opacity": 0.75,
                        "stroke": True,
                        "stroke_color": "rgba(255,255,255,0.15)",
                        "stroke_width": 0.5,
                        "legend_title": f"{pollutant} Concentration",
                        "legend_unit": unit,
                        "resolution_info": f"{int(round(interp_resolution))}m interpolation",
                    },
                }
            ],
            "contour_bands": contour_bands,
            "coverage_assessment": data.get("coverage_assessment", {}),
            "summary": {
                "n_levels": n_levels,
                "interp_resolution_m": interp_resolution,
                "min_concentration": float(stats.get("min_concentration", 0.0)),
                "max_concentration": float(stats.get("max_concentration", 0.0)),
                "mean_concentration": float(stats.get("mean_concentration", 0.0)),
                "unit": unit,
                "n_receptors_used": int(contour_bands.get("n_receptors_used", 0)),
                "feature_count": len(features),
            },
        }

    def _build_hotspot_map(
        self,
        result_data: Dict[str, Any],
        title: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Build hotspot overlay map data, optionally with raster background."""
        data = result_data.get("data", result_data)
        hotspots = data.get("hotspots", [])
        if not isinstance(hotspots, list) or not hotspots:
            return None

        hotspot_features: List[Dict[str, Any]] = []
        contributing_road_ids: set[str] = set()
        center_lons: List[float] = []
        center_lats: List[float] = []
        pollutant = _resolve_dispersion_pollutant(data)
        unit = _resolve_concentration_unit(data)

        for hotspot in hotspots:
            if not isinstance(hotspot, dict):
                continue

            bbox = hotspot.get("bbox", [])
            if not isinstance(bbox, list) or len(bbox) < 4:
                center = hotspot.get("center", {})
                if not isinstance(center, dict):
                    continue
                lon = float(center.get("lon", 0.0))
                lat = float(center.get("lat", 0.0))
                bbox = [lon - 0.001, lat - 0.001, lon + 0.001, lat + 0.001]

            center = hotspot.get("center", {})
            if isinstance(center, dict):
                try:
                    center_lon = float(center.get("lon", 0.0))
                    center_lat = float(center.get("lat", 0.0))
                    center_lons.append(center_lon)
                    center_lats.append(center_lat)
                except (TypeError, ValueError):
                    pass

            hotspot_features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [float(bbox[0]), float(bbox[1])],
                            [float(bbox[2]), float(bbox[1])],
                            [float(bbox[2]), float(bbox[3])],
                            [float(bbox[0]), float(bbox[3])],
                            [float(bbox[0]), float(bbox[1])],
                        ]],
                    },
                    "properties": {
                        "hotspot_id": hotspot.get("hotspot_id"),
                        "rank": hotspot.get("rank"),
                        "max_conc": hotspot.get("max_conc", 0.0),
                        "mean_conc": hotspot.get("mean_conc", 0.0),
                        "area_m2": hotspot.get("area_m2", 0.0),
                        "grid_cells": hotspot.get("grid_cells", 0),
                    },
                }
            )

            for road in hotspot.get("contributing_roads", []):
                if isinstance(road, dict):
                    road_id = str(road.get("link_id", "")).strip()
                    if road_id:
                        contributing_road_ids.add(road_id)

        if not hotspot_features:
            return None

        if center_lons and center_lats:
            min_lon = min(center_lons)
            max_lon = max(center_lons)
            min_lat = min(center_lats)
            max_lat = max(center_lats)
            center = [(min_lat + max_lat) / 2.0, (min_lon + max_lon) / 2.0]
            zoom = _zoom_from_span(max(max_lon - min_lon, max_lat - min_lat))
        else:
            center = [31.23, 121.47]
            zoom = 12

        layers: List[Dict[str, Any]] = []
        contour_map = self._build_contour_map(data, pollutant=pollutant)
        if contour_map and contour_map.get("layers"):
            layers.append(contour_map["layers"][0])
        elif "raster_grid" in data:
            raster_map = self._build_raster_map(data, pollutant=pollutant)
            if raster_map and raster_map.get("layers"):
                layers.append(raster_map["layers"][0])

        layers.append(
            {
                "id": "hotspot_areas",
                "type": "hotspot_polygon",
                "data": {"type": "FeatureCollection", "features": hotspot_features},
                "style": {
                    "color": "#D32F2F",
                    "weight": 1.2,
                    "dashArray": None,
                    "fillColor": "white",
                    "fillOpacity": 0.12,
                    "opacity": 0.95,
                },
            }
        )

        return {
            "type": "hotspot",
            "title": title or "Pollution Hotspot Analysis",
            "pollutant": pollutant,
            "unit": unit,
            "scenario_label": str(data.get("scenario_label") or "baseline"),
            "center": center,
            "zoom": zoom,
            "interpretation": data.get("interpretation", ""),
            "layers": layers,
            "hotspots_detail": hotspots,
            "contributing_road_ids": sorted(contributing_road_ids),
            "coverage_assessment": data.get("coverage_assessment"),
            "summary": data.get("summary", {}),
        }

    def _build_points_map(self, result_data, pollutant, title):
        """Build map for point data (receptors, monitors).
        Placeholder for Sprint 9."""
        logger.info("Points map rendering not yet implemented")
        return None
