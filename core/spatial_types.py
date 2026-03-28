"""
EmissionAgent - Spatial Data Types

Standard data structures for spatial rendering. These types define the
complete rendering contract between backend tools and frontend visualization.
Designed to support line, point, polygon, and grid geometries from day one.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SpatialLayer:
    """A single spatial layer with complete rendering instructions.

    Design principle: the backend specifies ALL rendering decisions.
    The frontend only executes -- it never guesses how to render.
    """
    # === Identity ===
    layer_id: str
    geometry_type: str  # "line" | "point" | "polygon" | "grid"

    # === Data ===
    geojson: Dict[str, Any]  # Standard GeoJSON FeatureCollection

    # === Color mapping ===
    color_field: str                    # Feature property to color by
    value_range: List[float]            # [min, max] -- backend computes this
    classification_mode: str = "continuous"  # "continuous" | "threshold" | "quantile" | "category"
    color_scale: str = "YlOrRd"        # Named color scale

    # === Legend ===
    legend_title: str = ""
    legend_unit: Optional[str] = None

    # === Style ===
    opacity: float = 0.8
    weight: float = 2.0                # Line width (line type)
    radius: float = 5.0                # Point radius (point type)
    style_hint: Optional[str] = None   # "heatmap" | "choropleth" | "bubble" | "border_only"

    # === Interaction ===
    popup_fields: Optional[List[Dict[str, str]]] = None

    # === Threshold rendering ===
    threshold: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize, excluding None optional fields."""
        result = {
            "layer_id": self.layer_id,
            "geometry_type": self.geometry_type,
            "geojson": self.geojson,
            "color_field": self.color_field,
            "value_range": self.value_range,
            "classification_mode": self.classification_mode,
            "color_scale": self.color_scale,
            "legend_title": self.legend_title,
            "opacity": self.opacity,
            "weight": self.weight,
            "radius": self.radius,
        }
        for key in ["legend_unit", "style_hint", "popup_fields", "threshold"]:
            val = getattr(self, key)
            if val is not None:
                result[key] = val
        return result


@dataclass
class SpatialDataPackage:
    """Complete spatial rendering package with one or more layers."""
    layers: List[SpatialLayer] = field(default_factory=list)
    title: str = ""
    bounds: Optional[Dict[str, Any]] = None  # {center: [lat, lon], zoom: int}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "bounds": self.bounds,
            "layers": [layer.to_dict() for layer in self.layers],
            "layer_count": len(self.layers),
        }

    @staticmethod
    def compute_bounds_from_geojson(geojson: Dict) -> Dict[str, Any]:
        """Compute map center and zoom from GeoJSON coordinates.

        Works with any geometry type (Point, LineString, Polygon, MultiLineString).
        Returns {center: [lat, lon], zoom: int, bbox: [min_lon, min_lat, max_lon, max_lat]}
        """
        all_coords: List[List[float]] = []
        features = geojson.get("features", [])
        for feature in features:
            geom = feature.get("geometry", {})
            coords = geom.get("coordinates", [])
            _extract_coords_recursive(coords, all_coords)

        if not all_coords:
            return {"center": [31.23, 121.47], "zoom": 12}  # fallback

        lons = [c[0] for c in all_coords]
        lats = [c[1] for c in all_coords]
        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)
        center_lat = (min_lat + max_lat) / 2
        center_lon = (min_lon + max_lon) / 2

        # Estimate zoom from span
        lat_span = max_lat - min_lat
        lon_span = max_lon - min_lon
        span = max(lat_span, lon_span)
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

        return {
            "center": [center_lat, center_lon],
            "zoom": zoom,
            "bbox": [min_lon, min_lat, max_lon, max_lat],
        }


def _extract_coords_recursive(coords, result):
    """Recursively extract [lon, lat] pairs from nested coordinate arrays."""
    if not coords:
        return
    if isinstance(coords[0], (int, float)):
        # This is a single coordinate [lon, lat] or [lon, lat, alt]
        result.append(coords[:2])
    elif isinstance(coords[0], list):
        for item in coords:
            _extract_coords_recursive(item, result)
