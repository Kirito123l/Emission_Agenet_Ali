"""Dispersion calculation utilities extracted from the legacy surrogate script."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

import geopandas as gpd
import numpy as np
import pandas as pd
import xgboost as xgb
import yaml
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, Polygon
from shapely.ops import unary_union
from shapely.validation import make_valid

logger = logging.getLogger(__name__)

DEFAULT_MET_DATE = 2024010100
MAX_TRACKED_ROADS_PER_RECEPTOR = 10
DENSE_ROAD_CONTRIBUTION_LIMIT = 10_000_000


@dataclass
class DispersionConfig:
    """All configurable parameters for a dispersion calculation."""

    # CRS
    source_crs: str = "EPSG:4326"
    utm_zone: int = 51
    utm_hemisphere: str = "north"

    # Road segmentation
    segment_interval_m: float = 10.0
    default_road_width_m: float = 7.0

    # Receptor generation
    offset_rule: Dict[float, float] = field(default_factory=lambda: {3.5: 40, 8.5: 40})
    background_spacing_m: float = 50.0
    buffer_extra_m: float = 3.0
    display_grid_resolution_m: float = 50.0

    # Prediction ranges
    downwind_range: Tuple[float, float] = (0.0, 1000.0)
    upwind_range: Tuple[float, float] = (-100.0, 0.0)
    crosswind_range: Tuple[float, float] = (-100.0, 100.0)
    batch_size: int = 200000

    # Model
    roughness_height: float = 0.5
    model_base_dir: str = ""

    # Meteorology
    met_source: str = "preset"


SFC_COLUMN_NAMES = [
    "Year",
    "Month",
    "Day",
    "JulianDay",
    "Hour",
    "H",
    "USTAR",
    "WSTAR",
    "ThetaGrad",
    "MixHGT_C",
    "MixHGT_M",
    "L",
    "Z0",
    "B0",
    "Albedo",
    "WSPD",
    "WDIR",
    "AnemoHt",
    "Temp",
    "MeasHt",
    "PrecipType",
    "PrecipAmt",
    "RH",
    "Pressure",
    "CloudCover",
    "WindFlag",
    "CloudTempFlag",
]

ROUGHNESS_MAP = {0.05: "L", 0.5: "M", 1.0: "H"}
ROUGHNESS_DIR_MAP = {0.05: "model_z=0.05", 0.5: "model_z=0.5", 1.0: "model_z=1"}

STABILITY_CLASSES = ["stable", "verystable", "unstable", "veryunstable", "neutral1", "neutral2"]
STABILITY_ABBREV = {
    "VS": "verystable",
    "S": "stable",
    "N1": "neutral1",
    "N2": "neutral2",
    "U": "unstable",
    "VU": "veryunstable",
}


def _get_utm_crs(utm_zone: int, utm_hemisphere: str) -> str:
    """Build an EPSG CRS string for a UTM zone and hemisphere."""
    if not 1 <= utm_zone <= 60:
        raise ValueError(f"Invalid UTM zone: {utm_zone}")

    hemisphere = utm_hemisphere.lower()
    if hemisphere == "north":
        return f"EPSG:{32600 + utm_zone}"
    if hemisphere == "south":
        return f"EPSG:{32700 + utm_zone}"
    raise ValueError(f"Invalid UTM hemisphere: {utm_hemisphere}")


def _default_model_base_dir() -> Path:
    """Infer the surrogate model directory from the repository layout."""
    return Path(__file__).resolve().parents[1] / "ps-xgb-aermod-rline-surrogate" / "models"


def _default_presets_path() -> Path:
    """Return the meteorology preset configuration path."""
    return Path(__file__).resolve().parents[1] / "config" / "meteorology_presets.yaml"


def _extract_line_coords(geometry: Any) -> list[Tuple[float, float]]:
    """Flatten a line or multi-line geometry into an ordered coordinate list."""
    if geometry is None:
        return []
    if isinstance(geometry, LineString):
        return [(float(x), float(y)) for x, y in geometry.coords]
    if isinstance(geometry, MultiLineString):
        coords: list[Tuple[float, float]] = []
        for line in geometry.geoms:
            coords.extend((float(x), float(y)) for x, y in line.coords)
        return coords
    raise ValueError(f"Unsupported geometry type: {getattr(geometry, 'geom_type', type(geometry).__name__)}")


def _predict_with_model(model: Any, features: np.ndarray) -> np.ndarray:
    """Run inference against either sklearn-style or Booster-style XGBoost models."""
    if isinstance(model, xgb.Booster):
        return np.asarray(model.predict(xgb.DMatrix(features)), dtype=float)

    try:
        return np.asarray(model.predict(features), dtype=float)
    except TypeError:
        return np.asarray(model.predict(xgb.DMatrix(features)), dtype=float)


def _format_time_key(value: Any) -> str:
    """Normalize time values into stable string keys for result payloads."""
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y%m%d%H")
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value).strftime("%Y%m%d%H")
    return str(value)


def convert_coords(
    lon: Union[float, np.ndarray],
    lat: Union[float, np.ndarray],
    source_crs: str,
    utm_zone: int,
    utm_hemisphere: str,
) -> Tuple[Union[float, np.ndarray], Union[float, np.ndarray]]:
    """Convert coordinates from the source CRS into the configured UTM CRS."""
    transformer = Transformer.from_crs(
        source_crs,
        _get_utm_crs(utm_zone, utm_hemisphere),
        always_xy=True,
    )
    return transformer.transform(lon, lat)


def make_rectangular_buffer(line: LineString, half_width: float) -> Optional[Polygon]:
    """Build a rectangular road buffer polygon without semi-circle end caps."""
    coords = np.array(line.coords)
    if len(coords) < 2:
        return None

    left_points, right_points = [], []
    for i in range(len(coords) - 1):
        (x1, y1), (x2, y2) = coords[i], coords[i + 1]
        dx, dy = x2 - x1, y2 - y1
        seg_len = np.hypot(dx, dy)
        if seg_len == 0:
            continue
        nx, ny = -dy / seg_len, dx / seg_len
        left_points.append((x1 + nx * half_width, y1 + ny * half_width))
        right_points.append((x1 - nx * half_width, y1 - ny * half_width))
        if i == len(coords) - 2:
            left_points.append((x2 + nx * half_width, y2 + ny * half_width))
            right_points.append((x2 - nx * half_width, y2 - ny * half_width))

    if not left_points or not right_points:
        return None

    right_points.reverse()
    return Polygon(left_points + right_points)


def generate_receptors_custom_offset(
    e_road_df: pd.DataFrame,
    offset_rule: Dict[float, float] = {6.5: 2, 15: 4, 30: 7, 50: 12},
    background_spacing: float = 50,
    buffer_extra: float = 30,
    width_col: str = "width",
    global_extent: Optional[Tuple[float, float, float, float]] = None,
) -> gpd.GeoDataFrame:
    """Generate near-road and background receptor points for a road network."""
    receptor_list: list[dict[str, Any]] = []
    road_df = e_road_df.copy()

    if width_col not in road_df.columns:
        road_df[width_col] = 7.0

    buffers = []
    for _, row in road_df.iterrows():
        half_width = 0.5 * row[width_col] + buffer_extra
        try:
            coords = row["new_coords"]
            line = LineString(coords)
            poly = make_rectangular_buffer(line, half_width)
            if poly and not poly.is_empty:
                if not poly.is_valid:
                    poly = make_valid(poly)
                buffers.append(poly)
        except Exception as exc:
            logger.warning("Skip invalid geometry for road %s: %s", row.get("index", "?"), exc)

    if not buffers:
        raise ValueError("No valid buffer polygons generated.")
    buffer_union = unary_union(buffers)

    for _, row in road_df.iterrows():
        name = row.get("index", "road")
        coords = row["new_coords"]
        base_offset = 0.5 * row[width_col] + buffer_extra

        for i in range(len(coords) - 1):
            x1, y1 = coords[i]
            x2, y2 = coords[i + 1]
            dx, dy = x2 - x1, y2 - y1
            seg_len = np.hypot(dx, dy)
            if seg_len == 0:
                continue
            nx, ny = -dy / seg_len, dx / seg_len

            for offset, spacing in offset_rule.items():
                true_offset = base_offset + offset
                n_points = max(1, int(seg_len / spacing) + 1)
                t = np.linspace(0, 1, n_points)
                xs = x1 + t * dx
                ys = y1 + t * dy

                for side, sign in [("left", 1), ("right", -1)]:
                    x_offset = xs + sign * true_offset * nx
                    y_offset = ys + sign * true_offset * ny
                    for x, y in zip(x_offset, y_offset):
                        receptor_list.append(
                            {
                                "NAME_1": name,
                                "segment_id": f"{name}__{i}",
                                "x": x,
                                "y": y,
                                "offset_from_buffer": offset,
                                "true_offset": true_offset,
                                "type": "road_near",
                                "side": side,
                            }
                        )

    if global_extent is None:
        all_x = [x for coords in road_df["new_coords"] for x, _ in coords]
        all_y = [y for coords in road_df["new_coords"] for _, y in coords]
        xmin, xmax = min(all_x), max(all_x)
        ymin, ymax = min(all_y), max(all_y)
    else:
        xmin, xmax, ymin, ymax = global_extent

    gx = np.arange(xmin, xmax + background_spacing, background_spacing)
    gy = np.arange(ymin, ymax + background_spacing, background_spacing)
    grid_x, grid_y = np.meshgrid(gx, gy)

    for x, y in zip(grid_x.flatten(), grid_y.flatten()):
        receptor_list.append(
            {
                "NAME_1": "background",
                "segment_id": "grid",
                "x": x,
                "y": y,
                "offset_from_buffer": None,
                "true_offset": None,
                "type": "background",
            }
        )

    receptors_df = pd.DataFrame(receptor_list)
    receptors_gdf = gpd.GeoDataFrame(
        receptors_df,
        geometry=gpd.points_from_xy(receptors_df["x"], receptors_df["y"]),
    )

    receptors_gdf["in_buffer"] = receptors_gdf.geometry.intersects(buffer_union)
    receptors_gdf = receptors_gdf[~receptors_gdf["in_buffer"]].copy()

    logger.debug("Generated %s road buffers and %s receptors", len(buffers), len(receptors_gdf))
    return receptors_gdf


def split_polyline_by_interval_with_angle(
    coords: list[Tuple[float, float]],
    interval: float = 10,
) -> list[Tuple[float, float, float]]:
    """Split a polyline into fixed-distance subsegments and return midpoint bearings."""
    if len(coords) < 2:
        return []

    seg_lengths = [
        np.hypot(coords[i + 1][0] - coords[i][0], coords[i + 1][1] - coords[i][1])
        for i in range(len(coords) - 1)
    ]
    cum_lengths = np.cumsum([0] + seg_lengths)
    total_len = cum_lengths[-1]
    n_segments = int(np.ceil(total_len / interval))

    mids = []
    for i in range(n_segments):
        start_d = i * interval
        end_d = min((i + 1) * interval, total_len)
        mid_d = (start_d + end_d) / 2

        x_mid = np.interp(mid_d, cum_lengths, [p[0] for p in coords])
        y_mid = np.interp(mid_d, cum_lengths, [p[1] for p in coords])

        seg_idx = np.searchsorted(cum_lengths, mid_d) - 1
        seg_idx = min(seg_idx, len(coords) - 2)
        dx = coords[seg_idx + 1][0] - coords[seg_idx][0]
        dy = coords[seg_idx + 1][1] - coords[seg_idx][1]

        angle_deg = np.degrees(np.arctan2(dy, dx))
        angle_deg = (270 - angle_deg) % 360
        angle_deg = angle_deg % 180

        mids.append((x_mid, y_mid, angle_deg))
    return mids


def read_sfc(path: Union[str, Path]) -> pd.DataFrame:
    """Read an AERMOD surface meteorological file."""
    return pd.read_csv(
        path,
        sep=r"\s+",
        names=SFC_COLUMN_NAMES,
        skiprows=1,
        comment="#",
    )


def load_model(path: Union[str, Path]) -> xgb.XGBRegressor:
    """Load a single XGBoost regressor from disk."""
    model = xgb.XGBRegressor(n_jobs=1)
    model.load_model(path)
    return model


def predict_time_series_xgb(
    models: dict,
    receptors_x: np.ndarray,
    receptors_y: np.ndarray,
    sources: np.ndarray,
    met: pd.DataFrame,
    x_range0: Tuple[float, float] = (0, 1000.0),
    x_range1: Tuple[float, float] = (-100, 0.0),
    y_range: Tuple[float, float] = (-50.0, 50.0),
    batch_size: int = 200000,
    track_road_contributions: bool = False,
    segment_to_road_map: Optional[np.ndarray] = None,
) -> Union[pd.DataFrame, tuple[pd.DataFrame, dict]]:
    """
    XGBoost surrogate time-series inference.

    This preserves the legacy surrogate's numerical path:
    wind-aligned rotation, source-relative masking, directional model
    selection, and concentration accumulation per receptor per hour.
    """
    no_hc_classes = {"VS", "S", "N1"}

    rx = np.asarray(receptors_x, dtype=float)
    ry = np.asarray(receptors_y, dtype=float)
    if rx.shape != ry.shape:
        raise ValueError("receptors_x and receptors_y must have the same shape")

    src = np.asarray(sources, dtype=float)
    if src.ndim != 3 or src.shape[2] != 4:
        raise ValueError("sources must have shape (T, N_sources, 4)")

    met_df = met.copy().reset_index(drop=True)
    if "Stab_Class" not in met_df.columns:
        met_df["Stab_Class"] = met_df.apply(
            lambda row: classify_stability(
                float(row.get("L", 0.0)),
                float(row.get("WSPD", 0.0)),
                float(row.get("MixHGT_C", 0.0)),
            ),
            axis=1,
        )

    if len(met_df) != src.shape[0]:
        raise ValueError(
            f"Time dimension mismatch: met has {len(met_df)} rows but sources has {src.shape[0]}"
        )

    n_receptors = rx.size
    receptor_ids = np.arange(n_receptors)
    results: list[pd.DataFrame] = []
    progress_interval = 10
    dense_road_contribs: Optional[np.ndarray] = None
    sparse_road_contribs: Optional[list[dict[int, float]]] = None
    tracking_mode = "disabled"

    if track_road_contributions:
        if segment_to_road_map is None:
            raise ValueError("segment_to_road_map is required when track_road_contributions=True")
        road_map = np.asarray(segment_to_road_map, dtype=int)
        if road_map.ndim != 1 or road_map.shape[0] != src.shape[1]:
            raise ValueError(
                "segment_to_road_map must be a 1D array with one entry per source segment"
            )
        n_roads = int(np.max(road_map)) + 1 if road_map.size else 0
        if n_roads > 0 and (n_receptors * n_roads) <= DENSE_ROAD_CONTRIBUTION_LIMIT:
            dense_road_contribs = np.zeros((n_receptors, n_roads), dtype=np.float32)
            tracking_mode = "dense_exact"
        else:
            sparse_road_contribs = [defaultdict(float) for _ in range(n_receptors)]
            tracking_mode = "sparse_topk"
    else:
        road_map = None

    for t, row in met_df.iterrows():
        if t == 0 or (t + 1) % progress_interval == 0 or t + 1 == len(met_df):
            logger.info("Dispersion inference progress: %s/%s timesteps", t + 1, len(met_df))

        date = row["Date"]
        stab_class = row["Stab_Class"]
        model_group = models.get(stab_class)

        if not model_group:
            logger.warning("No model for stability class %s, skipping timestep %s", stab_class, date)
            continue

        model_pos = model_group.get("pos") or model_group.get("x0")
        model_neg = model_group.get("neg") or model_group.get("x-1")
        if model_pos is None or model_neg is None:
            raise KeyError(f"Directional models missing for stability class {stab_class}")

        wspd = float(row["WSPD"])
        l_val = float(row["L"])
        h_val = float(row.get("H", row.get("Temp", 0.0)))
        mix_hgt = float(row["MixHGT_C"])
        wind_deg = float(row["WDIR"])

        current_sources = src[t]
        sx = current_sources[:, 0]
        sy = current_sources[:, 1]
        strength = current_sources[:, 2]
        road_angle = current_sources[:, 3]

        theta = np.deg2rad(270 - wind_deg)
        cos_t = np.cos(theta)
        sin_t = np.sin(theta)

        rx_rot = rx * cos_t + ry * sin_t
        ry_rot = -rx * sin_t + ry * cos_t
        sx_rot = sx * cos_t + sy * sin_t
        sy_rot = -sx * sin_t + sy * cos_t

        x_hat = rx_rot[:, None] - sx_rot[None, :]
        y_hat = ry_rot[:, None] - sy_rot[None, :]
        total_conc = np.zeros(n_receptors, dtype=float)

        rel_wind_deg = (wind_deg - road_angle) % 360
        wind_sin_src = np.sin(np.deg2rad(rel_wind_deg))
        wind_cos_src = np.cos(np.deg2rad(rel_wind_deg))

        mask_pos = (
            (x_hat >= x_range0[0])
            & (x_hat <= x_range0[1])
            & (y_hat >= y_range[0])
            & (y_hat <= y_range[1])
        )
        r_idx, s_idx = np.where(mask_pos)
        if r_idx.size > 0:
            wind_sin_vals = wind_sin_src[s_idx]
            wind_cos_vals = wind_cos_src[s_idx]

            if stab_class in no_hc_classes:
                features = np.column_stack(
                    (
                        x_hat[mask_pos],
                        y_hat[mask_pos],
                        wind_sin_vals,
                        wind_cos_vals,
                        np.full(r_idx.size, h_val),
                        np.full(r_idx.size, l_val),
                        np.full(r_idx.size, wspd),
                    )
                )
            else:
                features = np.column_stack(
                    (
                        x_hat[mask_pos],
                        y_hat[mask_pos],
                        wind_sin_vals,
                        wind_cos_vals,
                        np.full(r_idx.size, h_val),
                        np.full(r_idx.size, mix_hgt),
                        np.full(r_idx.size, l_val),
                        np.full(r_idx.size, wspd),
                    )
                )

            preds = np.zeros(r_idx.size, dtype=float)
            for start in range(0, r_idx.size, batch_size):
                end = start + batch_size
                preds[start:end] = _predict_with_model(model_pos, features[start:end])
            preds = np.clip(preds, 0, None)
            contrib = preds * strength[s_idx] / 1e-6
            np.add.at(total_conc, r_idx, contrib)
            if track_road_contributions and road_map is not None:
                road_idx = road_map[s_idx]
                if dense_road_contribs is not None:
                    np.add.at(dense_road_contribs, (r_idx, road_idx), contrib.astype(np.float32))
                elif sparse_road_contribs is not None:
                    for receptor_idx, source_road_idx, value in zip(
                        r_idx.tolist(),
                        road_idx.tolist(),
                        contrib.tolist(),
                    ):
                        receptor_contribs = sparse_road_contribs[receptor_idx]
                        receptor_contribs[int(source_road_idx)] += float(value)
                        if len(receptor_contribs) > MAX_TRACKED_ROADS_PER_RECEPTOR * 4:
                            _prune_sparse_contributions(
                                receptor_contribs,
                                MAX_TRACKED_ROADS_PER_RECEPTOR * 2,
                            )

        mask_neg = (
            (x_hat >= x_range1[0])
            & (x_hat <= x_range1[1])
            & (y_hat >= y_range[0])
            & (y_hat <= y_range[1])
        )
        r_idx, s_idx = np.where(mask_neg)
        if r_idx.size > 0:
            wind_sin_vals = wind_sin_src[s_idx]
            wind_cos_vals = wind_cos_src[s_idx]

            if stab_class in no_hc_classes:
                features = np.column_stack(
                    (
                        x_hat[mask_neg],
                        y_hat[mask_neg],
                        wind_sin_vals,
                        wind_cos_vals,
                        np.full(r_idx.size, h_val),
                        np.full(r_idx.size, l_val),
                        np.full(r_idx.size, wspd),
                    )
                )
            else:
                features = np.column_stack(
                    (
                        x_hat[mask_neg],
                        y_hat[mask_neg],
                        wind_sin_vals,
                        wind_cos_vals,
                        np.full(r_idx.size, h_val),
                        np.full(r_idx.size, mix_hgt),
                        np.full(r_idx.size, l_val),
                        np.full(r_idx.size, wspd),
                    )
                )

            preds = np.zeros(r_idx.size, dtype=float)
            for start in range(0, r_idx.size, batch_size):
                end = start + batch_size
                preds[start:end] = _predict_with_model(model_neg, features[start:end])
            preds = np.clip(preds, 0, None)
            contrib = preds * strength[s_idx] / 1e-6
            np.add.at(total_conc, r_idx, contrib)
            if track_road_contributions and road_map is not None:
                road_idx = road_map[s_idx]
                if dense_road_contribs is not None:
                    np.add.at(dense_road_contribs, (r_idx, road_idx), contrib.astype(np.float32))
                elif sparse_road_contribs is not None:
                    for receptor_idx, source_road_idx, value in zip(
                        r_idx.tolist(),
                        road_idx.tolist(),
                        contrib.tolist(),
                    ):
                        receptor_contribs = sparse_road_contribs[receptor_idx]
                        receptor_contribs[int(source_road_idx)] += float(value)
                        if len(receptor_contribs) > MAX_TRACKED_ROADS_PER_RECEPTOR * 4:
                            _prune_sparse_contributions(
                                receptor_contribs,
                                MAX_TRACKED_ROADS_PER_RECEPTOR * 2,
                            )

        results.append(
            pd.DataFrame(
                {
                    "Date": date,
                    "Receptor_ID": receptor_ids,
                    "Receptor_X": np.round(rx, 1),
                    "Receptor_Y": np.round(ry, 1),
                    "Conc": total_conc,
                }
            )
        )

    if not results:
        empty = pd.DataFrame(columns=["Date", "Receptor_ID", "Receptor_X", "Receptor_Y", "Conc"])
        if not track_road_contributions:
            return empty
        return empty, _finalize_road_contributions(
            dense_matrix=dense_road_contribs,
            sparse_maps=sparse_road_contribs,
            effective_timesteps=0,
            top_k=MAX_TRACKED_ROADS_PER_RECEPTOR,
            tracking_mode=tracking_mode,
        )

    result_df = pd.concat(results, ignore_index=True)
    if not track_road_contributions:
        return result_df

    return result_df, _finalize_road_contributions(
        dense_matrix=dense_road_contribs,
        sparse_maps=sparse_road_contribs,
        effective_timesteps=len(results),
        top_k=MAX_TRACKED_ROADS_PER_RECEPTOR,
        tracking_mode=tracking_mode,
    )


def classify_stability(L: float, wspd: float, mix_hgt: float) -> str:
    """
    Classify atmospheric stability from Monin-Obukhov length.

    Matches the legacy inline classification in mode_inference.py lines 448-457.
    Returns one of: "VS", "S", "N1", "N2", "U", "VU", or "UNK".
    """
    if 0 < L <= 200:
        return "VS"
    if 200 < L < 1000:
        return "S"
    if L >= 1000 and wspd != 999 and L != -99999:
        return "N1"
    if L <= -1000 and wspd != 999 and L != -99999 and mix_hgt != -999:
        return "N2"
    if -1000 < L <= -200 and mix_hgt != -999 and wspd != 999:
        return "U"
    if -200 < L < 0 and mix_hgt != -999 and wspd != 999:
        return "VU"
    return "UNK"


def compute_local_origin(utm_coords: np.ndarray) -> Tuple[float, float]:
    """Compute local origin offset (min_x, min_y) for coordinate normalization."""
    coords = np.asarray(utm_coords, dtype=float)
    if coords.ndim != 2 or coords.shape[1] != 2 or coords.size == 0:
        raise ValueError("utm_coords must be a non-empty array of shape (N, 2)")
    return float(np.min(coords[:, 0])), float(np.min(coords[:, 1]))


def inverse_transform_coords(
    local_x: np.ndarray,
    local_y: np.ndarray,
    origin_x: float,
    origin_y: float,
    utm_zone: int,
    utm_hemisphere: str,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Convert local coordinates back to WGS-84 (lon, lat).

    This is the inverse of the forward chain: WGS84 -> UTM -> local.
    """
    utm_x = np.asarray(local_x, dtype=float) + origin_x
    utm_y = np.asarray(local_y, dtype=float) + origin_y
    transformer = Transformer.from_crs(
        _get_utm_crs(utm_zone, utm_hemisphere),
        "EPSG:4326",
        always_xy=True,
    )
    lon, lat = transformer.transform(utm_x, utm_y)
    return np.asarray(lon, dtype=float), np.asarray(lat, dtype=float)


def aggregate_to_raster(
    receptor_x: np.ndarray,
    receptor_y: np.ndarray,
    concentrations: np.ndarray,
    resolution_m: float,
    origin_x: float,
    origin_y: float,
    utm_zone: int,
    utm_hemisphere: str,
) -> dict:
    """
    Aggregate receptor-level concentrations to a regular raster grid.

    This is a display-oriented post-processing layer and does not affect
    the surrogate computation grid or inference precision.
    """
    rx = np.asarray(receptor_x, dtype=float)
    ry = np.asarray(receptor_y, dtype=float)
    conc = np.asarray(concentrations, dtype=float)

    empty = {
        "matrix_mean": [],
        "matrix_max": [],
        "bbox_local": [0.0, 0.0, 0.0, 0.0],
        "bbox_wgs84": [0.0, 0.0, 0.0, 0.0],
        "resolution_m": float(resolution_m),
        "rows": 0,
        "cols": 0,
        "nodata": 0.0,
        "cell_receptor_map": {},
        "cell_centers_wgs84": [],
        "stats": {
            "total_cells": 0,
            "nonzero_cells": 0,
            "coverage_pct": 0.0,
        },
    }

    if rx.size == 0 or ry.size == 0 or conc.size == 0:
        return empty
    if not (rx.shape == ry.shape == conc.shape):
        raise ValueError("receptor_x, receptor_y, and concentrations must have the same shape")
    if resolution_m <= 0:
        raise ValueError("resolution_m must be greater than zero")

    x_min = float(np.min(rx))
    x_max = float(np.max(rx))
    y_min = float(np.min(ry))
    y_max = float(np.max(ry))
    cols = int(np.ceil((x_max - x_min) / resolution_m)) + 1
    rows = int(np.ceil((y_max - y_min) / resolution_m)) + 1

    col_idx = np.floor((rx - x_min) / resolution_m).astype(int)
    row_idx = np.floor((ry - y_min) / resolution_m).astype(int)
    col_idx = np.clip(col_idx, 0, cols - 1)
    row_idx = np.clip(row_idx, 0, rows - 1)

    matrix_sum = np.zeros((rows, cols), dtype=float)
    matrix_count = np.zeros((rows, cols), dtype=int)
    matrix_max = np.zeros((rows, cols), dtype=float)
    np.add.at(matrix_sum, (row_idx, col_idx), conc)
    np.add.at(matrix_count, (row_idx, col_idx), 1)
    np.maximum.at(matrix_max, (row_idx, col_idx), conc)

    matrix_mean = np.divide(
        matrix_sum,
        matrix_count,
        out=np.zeros_like(matrix_sum),
        where=matrix_count > 0,
    )

    cell_receptor_map: dict[str, list[int]] = {}
    for receptor_idx, (row, col) in enumerate(zip(row_idx.tolist(), col_idx.tolist())):
        key = f"{row}_{col}"
        cell_receptor_map.setdefault(key, []).append(int(receptor_idx))

    occupied_mask = matrix_count > 0
    nonzero_mask = matrix_mean > 0
    occupied_rows, occupied_cols = np.where(nonzero_mask)
    cell_centers_wgs84: list[dict[str, float]] = []
    if occupied_rows.size > 0:
        center_x = x_min + occupied_cols * resolution_m + resolution_m / 2.0
        center_y = y_min + occupied_rows * resolution_m + resolution_m / 2.0
        center_lon, center_lat = inverse_transform_coords(
            center_x,
            center_y,
            origin_x,
            origin_y,
            utm_zone,
            utm_hemisphere,
        )
        for row, col, lon, lat in zip(
            occupied_rows.tolist(),
            occupied_cols.tolist(),
            center_lon.tolist(),
            center_lat.tolist(),
        ):
            cell_centers_wgs84.append(
                {
                    "row": int(row),
                    "col": int(col),
                    "lon": float(lon),
                    "lat": float(lat),
                    "mean_conc": float(matrix_mean[row, col]),
                    "max_conc": float(matrix_max[row, col]),
                }
            )

    bbox_x = np.array([x_min, x_max, x_min, x_max], dtype=float)
    bbox_y = np.array([y_min, y_min, y_max, y_max], dtype=float)
    bbox_lon, bbox_lat = inverse_transform_coords(
        bbox_x,
        bbox_y,
        origin_x,
        origin_y,
        utm_zone,
        utm_hemisphere,
    )

    total_cells = int(rows * cols)
    nonzero_cells = int(np.count_nonzero(nonzero_mask))
    return {
        "matrix_mean": matrix_mean.tolist(),
        "matrix_max": matrix_max.tolist(),
        "bbox_local": [x_min, y_min, x_max, y_max],
        "bbox_wgs84": [
            float(np.min(bbox_lon)),
            float(np.min(bbox_lat)),
            float(np.max(bbox_lon)),
            float(np.max(bbox_lat)),
        ],
        "resolution_m": float(resolution_m),
        "rows": rows,
        "cols": cols,
        "nodata": 0.0,
        "cell_receptor_map": cell_receptor_map,
        "cell_centers_wgs84": cell_centers_wgs84,
        "stats": {
            "total_cells": total_cells,
            "nonzero_cells": nonzero_cells,
            "coverage_pct": float((nonzero_cells / total_cells) * 100.0) if total_cells else 0.0,
            "occupied_cells": int(np.count_nonzero(occupied_mask)),
        },
    }


def _prune_sparse_contributions(
    receptor_contributions: dict[int, float],
    keep: int,
) -> None:
    """Trim a sparse receptor contribution map to its largest entries."""
    if len(receptor_contributions) <= keep:
        return

    top_items = sorted(
        receptor_contributions.items(),
        key=lambda item: item[1],
        reverse=True,
    )[:keep]
    receptor_contributions.clear()
    receptor_contributions.update(top_items)


def _finalize_road_contributions(
    *,
    dense_matrix: Optional[np.ndarray],
    sparse_maps: Optional[list[dict[int, float]]],
    effective_timesteps: int,
    top_k: int,
    tracking_mode: str,
) -> dict:
    """Convert accumulated road contributions into per-receptor top-k lists."""
    divisor = max(effective_timesteps, 1)
    receptor_top_roads: dict[int, list[tuple[int, float]]] = {}

    if dense_matrix is not None:
        normalized = dense_matrix / divisor
        for receptor_idx in range(normalized.shape[0]):
            row = normalized[receptor_idx]
            nonzero_idx = np.flatnonzero(row > 0)
            if nonzero_idx.size == 0:
                continue
            order = nonzero_idx[np.argsort(row[nonzero_idx])[::-1][:top_k]]
            receptor_top_roads[receptor_idx] = [
                (int(road_idx), float(row[road_idx])) for road_idx in order.tolist()
            ]

    if sparse_maps is not None:
        for receptor_idx, contributions in enumerate(sparse_maps):
            if not contributions:
                continue
            sorted_items = sorted(
                contributions.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:top_k]
            receptor_top_roads[receptor_idx] = [
                (int(road_idx), float(value / divisor))
                for road_idx, value in sorted_items
                if value > 0
            ]

    return {
        "receptor_top_roads": receptor_top_roads,
        "top_k": top_k,
        "effective_timesteps": int(divisor),
        "tracking_mode": tracking_mode,
    }


def _serialize_road_contributions(
    road_contributions: dict,
    road_id_map: list[str],
) -> dict:
    """Attach human-readable road IDs to per-receptor contribution records."""
    receptor_top_roads = road_contributions.get("receptor_top_roads", {})
    serialized: dict[str, list[dict[str, Any]]] = {}

    for receptor_idx, items in receptor_top_roads.items():
        serialized[str(int(receptor_idx))] = [
            {
                "road_idx": int(road_idx),
                "road_id": road_id_map[int(road_idx)]
                if 0 <= int(road_idx) < len(road_id_map)
                else None,
                "contribution": float(value),
            }
            for road_idx, value in items
        ]

    return {
        "receptor_top_roads": serialized,
        "road_id_map": list(road_id_map),
        "top_k": int(road_contributions.get("top_k", MAX_TRACKED_ROADS_PER_RECEPTOR)),
        "effective_timesteps": int(road_contributions.get("effective_timesteps", 1)),
        "tracking_mode": road_contributions.get("tracking_mode", "dense_exact"),
        "description": "Per-receptor top road contributions for hotspot attribution",
    }


def emission_to_line_source_strength(
    nox_kg_h: float,
    length_km: float,
    road_width_m: float = 7.0,
) -> float:
    """
    Convert macro emission (kg/h per link) to line source strength (g/s/m²).

    Formula: nox_kg_h * 1000 / 3600 / (length_km * 1000 * road_width_m)
    """
    if length_km <= 0:
        raise ValueError("length_km must be greater than zero")
    if road_width_m <= 0:
        raise ValueError("road_width_m must be greater than zero")
    return nox_kg_h * 1000 / 3600 / (length_km * 1000 * road_width_m)


def get_model_paths(
    stability_abbrev: str, roughness_height: float, model_base_dir: str = ""
) -> Tuple[Path, Path]:
    """Get model file paths for a given stability class and roughness height."""
    if roughness_height not in ROUGHNESS_MAP:
        raise ValueError(
            f"Unsupported roughness_height: {roughness_height}. "
            f"Expected one of {sorted(ROUGHNESS_MAP)}"
        )
    if stability_abbrev not in STABILITY_ABBREV:
        raise ValueError(f"Unknown stability class: {stability_abbrev}")

    roughness_suffix = ROUGHNESS_MAP[roughness_height]
    roughness_dir = ROUGHNESS_DIR_MAP[roughness_height]
    base_dir = Path(model_base_dir) if model_base_dir else _default_model_base_dir()
    model_dir = base_dir / roughness_dir

    stability_name = STABILITY_ABBREV[stability_abbrev]
    infix = "" if stability_name in {"neutral1", "neutral2"} else "_2000"
    x0_path = model_dir / f"model_RLINE_remet_multidir_{stability_name}{infix}_x0_{roughness_suffix}.json"
    xneg_path = model_dir / f"model_RLINE_remet_multidir_{stability_name}{infix}_x-1_{roughness_suffix}.json"
    return x0_path, xneg_path


def load_models_for_stability(
    stability_abbrev: str, roughness_height: float, model_base_dir: str = ""
) -> Dict[str, xgb.Booster]:
    """Load models for a single stability class. Returns {"x0": Booster, "x-1": Booster}."""
    x0_path, xneg_path = get_model_paths(stability_abbrev, roughness_height, model_base_dir)
    return {
        "x0": load_model(x0_path),
        "x-1": load_model(xneg_path),
    }


def load_all_models(model_base_dir: str, roughness_height: float) -> Dict[str, Dict[str, xgb.Booster]]:
    """
    Load all 12 XGBoost models for a given roughness height.

    Returns: {stability_abbrev: {"x0": Booster, "x-1": Booster}}

    Model file naming: model_RLINE_remet_multidir_{stability}[_2000]_{xside}_{roughness_suffix}.json
    Note: neutral1 and neutral2 don't have the "_2000" infix.
    """
    if roughness_height not in ROUGHNESS_MAP:
        raise ValueError(
            f"Unsupported roughness_height: {roughness_height}. "
            f"Expected one of {sorted(ROUGHNESS_MAP)}"
        )

    models: Dict[str, Dict[str, xgb.Booster]] = {}
    for stability_abbrev in STABILITY_ABBREV.keys():
        models[stability_abbrev] = load_models_for_stability(stability_abbrev, roughness_height, model_base_dir)
    return models


class DispersionCalculator:
    """
    PS-XGB-RLINE surrogate dispersion calculator.

    Encapsulates the full pipeline from mode_inference.py:
    road loading -> coordinate transform -> segmentation -> receptor generation
    -> meteorology processing -> model inference -> result assembly
    """

    def __init__(self, config: Optional[DispersionConfig] = None):
        """Initialize the calculator and defer model loading until first use."""
        self.config = config or DispersionConfig()
        self._models: Optional[Dict[str, Dict[str, Any]]] = None
        self._model_base_dir: str = ""
        self._source_times: pd.Index = pd.Index([])
        self._matched_road_count: int = 0
        self._met_source_used: str = self.config.met_source

    def calculate(
        self,
        roads_gdf: gpd.GeoDataFrame,
        emissions_df: pd.DataFrame,
        met_input: Union[str, pd.DataFrame, Dict],
        pollutant: str = "NOx",
        coverage_assessment: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Run the end-to-end surrogate dispersion pipeline."""
        try:
            self._validate_inputs(roads_gdf, emissions_df, pollutant)
            merged = self._merge_roads_and_emissions(roads_gdf, emissions_df, pollutant)
            utm_roads, origin = self._transform_to_local(merged)
            segments_df = self._segment_roads(utm_roads)
            receptors_df = self._generate_receptors(utm_roads)
            _, sources_re = self._build_source_arrays(segments_df, utm_roads)
            met_df = self._process_meteorology(met_input)
            met_df, sources_re = self._align_sources_and_met(met_df, sources_re)
            self._ensure_models_loaded()
            road_id_map = (
                merged[["road_index", "NAME_1"]]
                .drop_duplicates()
                .sort_values("road_index")["NAME_1"]
                .tolist()
            )

            stab_classes = met_df["Stab_Class"].unique()
            models_for_prediction = {}
            for stab_class in stab_classes:
                models_for_prediction[stab_class] = self._get_or_load_model(stab_class)

            prediction_result = predict_time_series_xgb(
                models=models_for_prediction,
                receptors_x=receptors_df["x"].to_numpy(dtype=float),
                receptors_y=receptors_df["y"].to_numpy(dtype=float),
                sources=sources_re,
                met=met_df,
                x_range0=self.config.downwind_range,
                x_range1=self.config.upwind_range,
                y_range=self.config.crosswind_range,
                batch_size=self.config.batch_size,
                track_road_contributions=True,
                segment_to_road_map=segments_df["road_idx"].to_numpy(dtype=int),
            )
            if isinstance(prediction_result, tuple):
                conc_df, road_contributions = prediction_result
            else:
                conc_df = prediction_result
                road_contributions = None

            lons, lats = inverse_transform_coords(
                receptors_df["x"].to_numpy(dtype=float),
                receptors_df["y"].to_numpy(dtype=float),
                origin[0],
                origin[1],
                self.config.utm_zone,
                self.config.utm_hemisphere,
            )

            return self._assemble_result(
                conc_df,
                receptors_df,
                lons,
                lats,
                met_df,
                pollutant,
                origin,
                coverage_assessment=coverage_assessment,
                road_contributions=road_contributions,
                road_id_map=road_id_map,
            )
        except FileNotFoundError as exc:
            logger.error("Model file missing: %s", exc, exc_info=True)
            return {
                "status": "error",
                "error_code": "MODEL_ASSET_MISSING",
                "message": str(exc),
                "failure_detail": {
                    "error_type": "MODEL_ASSET_MISSING",
                    "details": str(exc),
                },
            }
        except Exception as exc:
            logger.error("Dispersion calculation failed: %s", exc, exc_info=True)
            return {
                "status": "error",
                "error_code": "CALCULATION_ERROR",
                "message": str(exc),
            }

    def _validate_inputs(
        self,
        roads_gdf: gpd.GeoDataFrame,
        emissions_df: pd.DataFrame,
        pollutant: str,
    ) -> None:
        if pollutant != "NOx":
            raise ValueError("Only NOx is currently supported by the surrogate model")

        if not isinstance(roads_gdf, gpd.GeoDataFrame):
            raise TypeError("roads_gdf must be a GeoDataFrame")

        road_required = {"NAME_1", "geometry"}
        missing_roads = road_required - set(roads_gdf.columns)
        if missing_roads:
            raise ValueError(f"roads_gdf missing required columns: {sorted(missing_roads)}")

        pollutant_col = pollutant.lower()
        emission_required = {"NAME_1", "data_time", pollutant_col, "length"}
        missing_emissions = emission_required - set(emissions_df.columns)
        if missing_emissions:
            raise ValueError(
                f"emissions_df missing required columns: {sorted(missing_emissions)}"
            )

    def _merge_roads_and_emissions(
        self,
        roads_gdf: gpd.GeoDataFrame,
        emissions_df: pd.DataFrame,
        pollutant: str,
    ) -> gpd.GeoDataFrame:
        pollutant_col = pollutant.lower()
        roads = roads_gdf.copy()
        emissions = emissions_df.copy()

        if "NAME_1" not in roads.columns and "NAME" in roads.columns:
            roads = roads.rename(columns={"NAME": "NAME_1"})
        if "NAME_1" not in emissions.columns and "NAME" in emissions.columns:
            emissions = emissions.rename(columns={"NAME": "NAME_1"})

        width_columns = ["NAME_1", "geometry"]
        if "width" in roads.columns:
            width_columns.append("width")

        roads_unique = roads.drop_duplicates(subset="NAME_1")[width_columns].copy()
        merged = pd.merge(emissions, roads_unique, on="NAME_1", how="left")
        merged_gdf = gpd.GeoDataFrame(merged, geometry="geometry", crs=roads.crs)

        unmatched = merged_gdf[merged_gdf["geometry"].isna()]
        if not unmatched.empty:
            logger.warning(
                "Roads without geometry after merge: %s",
                unmatched["NAME_1"].dropna().unique().tolist(),
            )

        merged_gdf = merged_gdf[merged_gdf["geometry"].notna()].copy()
        if merged_gdf.empty:
            raise ValueError("No matched road geometries available for dispersion calculation")

        if "width" not in merged_gdf.columns:
            merged_gdf["width"] = self.config.default_road_width_m
        merged_gdf["width"] = merged_gdf["width"].fillna(self.config.default_road_width_m)

        merged_gdf["data_time"] = pd.to_datetime(merged_gdf["data_time"])
        merged_gdf = merged_gdf.sort_values("data_time").reset_index(drop=True)
        merged_gdf["road_index"] = merged_gdf["NAME_1"].astype("category").cat.codes
        merged_gdf["day"] = merged_gdf["data_time"].dt.date
        merged_gdf["hour"] = merged_gdf["data_time"].dt.hour
        merged_gdf["nox_g_m_s2"] = merged_gdf.apply(
            lambda row: emission_to_line_source_strength(
                float(row[pollutant_col]),
                float(row["length"]),
                float(row["width"]),
            ),
            axis=1,
        )

        self._matched_road_count = int(merged_gdf["NAME_1"].nunique())
        return merged_gdf

    def _transform_to_local(self, merged: gpd.GeoDataFrame) -> Tuple[gpd.GeoDataFrame, Tuple[float, float]]:
        unique_roads = (
            merged.drop_duplicates(subset="NAME_1")[["NAME_1", "road_index", "width", "geometry"]]
            .reset_index(drop=True)
            .copy()
        )

        source_crs = merged.crs.to_string() if merged.crs else self.config.source_crs
        utm_sources: list[list[Tuple[float, float]]] = []
        all_points: list[Tuple[float, float]] = []

        for _, row in unique_roads.iterrows():
            coords = _extract_line_coords(row["geometry"])
            if len(coords) < 2:
                raise ValueError(f"Road {row['NAME_1']} has insufficient coordinates for segmentation")

            lons = np.asarray([pt[0] for pt in coords], dtype=float)
            lats = np.asarray([pt[1] for pt in coords], dtype=float)
            utm_x, utm_y = convert_coords(
                lons,
                lats,
                source_crs=source_crs,
                utm_zone=self.config.utm_zone,
                utm_hemisphere=self.config.utm_hemisphere,
            )
            utm_coords = list(zip(np.asarray(utm_x, dtype=float), np.asarray(utm_y, dtype=float)))
            utm_sources.append(utm_coords)
            all_points.extend(utm_coords)

        origin_x, origin_y = compute_local_origin(np.asarray(all_points, dtype=float))
        unique_roads["utm_coords"] = utm_sources
        unique_roads["new_coords"] = [
            [(x - origin_x, y - origin_y) for x, y in line] for line in utm_sources
        ]

        transformed = merged.merge(
            unique_roads[["NAME_1", "utm_coords", "new_coords"]],
            on="NAME_1",
            how="left",
        )
        return gpd.GeoDataFrame(transformed, geometry="geometry", crs=merged.crs), (
            origin_x,
            origin_y,
        )

    def _segment_roads(self, utm_roads: gpd.GeoDataFrame) -> pd.DataFrame:
        base_roads = utm_roads.drop_duplicates(subset="NAME_1").copy()
        segments: list[dict[str, Any]] = []

        for _, row in base_roads.iterrows():
            coords = row["new_coords"]
            if not coords or len(coords) < 2:
                continue

            split_segments = split_polyline_by_interval_with_angle(
                coords,
                interval=self.config.segment_interval_m,
            )
            for idx, (xm, ym, angle_deg) in enumerate(split_segments):
                segments.append(
                    {
                        "road_id": int(row["road_index"]),
                        "road_idx": int(row["road_index"]),
                        "NAME_1": row["NAME_1"],
                        "segment_id": f"{row['road_index']}_{idx}",
                        "xm": float(xm),
                        "ym": float(ym),
                        "angle_deg": float(angle_deg),
                        "interval": self.config.segment_interval_m,
                    }
                )

        segments_df = pd.DataFrame(segments)
        if segments_df.empty:
            raise ValueError("No road segments generated for dispersion calculation")
        return segments_df

    def _generate_receptors(self, utm_roads: gpd.GeoDataFrame) -> pd.DataFrame:
        unique_roads = utm_roads.drop_duplicates(subset="NAME_1").copy()
        receptor_input = unique_roads[["NAME_1", "width", "new_coords"]].copy()
        receptor_input["index"] = receptor_input["NAME_1"]

        receptors = generate_receptors_custom_offset(
            receptor_input,
            offset_rule=self.config.offset_rule,
            background_spacing=self.config.background_spacing_m,
            buffer_extra=self.config.buffer_extra_m,
            global_extent=None,
        )
        receptors_unique = receptors.drop_duplicates(subset=["x", "y"]).reset_index(drop=True)
        if receptors_unique.empty:
            raise ValueError("No receptors generated for dispersion calculation")
        return receptors_unique

    def _build_source_arrays(
        self,
        segments_df: pd.DataFrame,
        merged: gpd.GeoDataFrame,
    ) -> Tuple[np.ndarray, np.ndarray]:
        unique_data_times = pd.Index(sorted(pd.to_datetime(merged["data_time"]).unique()))
        self._source_times = unique_data_times

        tiled = segments_df.loc[segments_df.index.repeat(len(unique_data_times))].copy()
        tiled["data_time"] = np.tile(unique_data_times.to_numpy(), len(segments_df))

        emission_df = merged[["road_index", "data_time", "nox_g_m_s2"]].copy()
        tiled = tiled.merge(
            emission_df,
            left_on=["road_id", "data_time"],
            right_on=["road_index", "data_time"],
            how="left",
        )
        tiled = tiled.sort_values(["data_time", "road_id", "segment_id"]).reset_index(drop=True)
        tiled["nox_g_m_s2"] = tiled["nox_g_m_s2"].fillna(0.0)
        tiled.rename(columns={"nox_g_m_s2": "emission"}, inplace=True)

        pollution_sources = np.array(
            [
                (x, y, strength, road_angle)
                for x, y, strength, road_angle in zip(
                    tiled["xm"],
                    tiled["ym"],
                    tiled["emission"],
                    tiled["angle_deg"],
                )
            ],
            dtype=float,
        )
        sources_re = pollution_sources.reshape(len(unique_data_times), len(segments_df), 4)
        return pollution_sources, sources_re

    def _process_meteorology(self, met_input: Union[str, pd.DataFrame, Dict]) -> pd.DataFrame:
        if isinstance(met_input, pd.DataFrame):
            self._met_source_used = "dataframe"
            return self._normalize_met_df(met_input.copy())

        if isinstance(met_input, dict):
            self._met_source_used = "custom"
            record = {
                "Date": met_input.get("Date", met_input.get("date", DEFAULT_MET_DATE)),
                "WSPD": met_input.get("WSPD", met_input.get("wind_speed", met_input.get("wind_speed_mps"))),
                "WDIR": met_input.get(
                    "WDIR",
                    met_input.get("wind_direction", met_input.get("wind_direction_deg")),
                ),
                "MixHGT_C": met_input.get(
                    "MixHGT_C",
                    met_input.get("mixing_height", met_input.get("mixing_height_m")),
                ),
                "L": met_input.get(
                    "L",
                    met_input.get("monin_obukhov_length", met_input.get("stability_length")),
                ),
                "H": met_input.get(
                    "H",
                    met_input.get("surface_heat_flux", met_input.get("temperature_k", 0.0)),
                ),
                "Stab_Class": met_input.get("Stab_Class", met_input.get("stability_class")),
            }
            return self._normalize_met_df(pd.DataFrame([record]))

        if isinstance(met_input, str):
            candidate = Path(met_input)
            if candidate.suffix.lower() == ".sfc":
                self._met_source_used = "sfc_file"
                sfc = read_sfc(candidate)
                years = sfc["Year"].astype(int) % 100
                months = sfc["Month"].astype(int)
                days = sfc["Day"].astype(int)
                hours = sfc["Hour"].astype(int)
                sfc["Date"] = (years * 1000000 + months * 10000 + days * 100 + hours).astype(int)
                sfc["Stab_Class"] = sfc.apply(
                    lambda row: classify_stability(
                        float(row["L"]),
                        float(row["WSPD"]),
                        float(row["MixHGT_C"]),
                    ),
                    axis=1,
                )
                met_df = sfc[["Date", "WSPD", "WDIR", "MixHGT_C", "L", "H", "Stab_Class"]].copy()
                return self._normalize_met_df(met_df)

            self._met_source_used = "preset"
            presets_path = _default_presets_path()
            preset_data = yaml.safe_load(presets_path.read_text(encoding="utf-8"))
            preset = preset_data.get("presets", {}).get(met_input)
            if preset is None:
                raise ValueError(f"Unknown meteorology preset: {met_input}")

            record = {
                "Date": DEFAULT_MET_DATE,
                "WSPD": preset["wind_speed_mps"],
                "WDIR": preset["wind_direction_deg"],
                "MixHGT_C": preset["mixing_height_m"],
                "L": preset["monin_obukhov_length"],
                "H": preset.get("surface_heat_flux", preset.get("temperature_k", 0.0)),
                "Stab_Class": preset.get("stability_class"),
                "Temp": preset.get("temperature_k"),
            }
            return self._normalize_met_df(pd.DataFrame([record]))

        raise TypeError(f"Unsupported meteorology input type: {type(met_input).__name__}")

    def _normalize_met_df(self, met_df: pd.DataFrame) -> pd.DataFrame:
        required = {"Date", "WSPD", "WDIR", "MixHGT_C", "L"}
        missing = required - set(met_df.columns)
        if missing:
            raise ValueError(f"Meteorology data missing required columns: {sorted(missing)}")

        normalized = met_df.copy().reset_index(drop=True)
        if "H" not in normalized.columns:
            normalized["H"] = normalized.get("Temp", 0.0)

        if "Stab_Class" not in normalized.columns:
            normalized["Stab_Class"] = normalized.apply(
                lambda row: classify_stability(
                    float(row["L"]),
                    float(row["WSPD"]),
                    float(row["MixHGT_C"]),
                ),
                axis=1,
            )
        elif normalized["Stab_Class"].isna().any():
            mask = normalized["Stab_Class"].isna()
            normalized.loc[mask, "Stab_Class"] = normalized.loc[mask].apply(
                lambda row: classify_stability(
                    float(row["L"]),
                    float(row["WSPD"]),
                    float(row["MixHGT_C"]),
                ),
                axis=1,
            )

        for column in ["WSPD", "WDIR", "MixHGT_C", "L", "H"]:
            normalized[column] = normalized[column].astype(float)
        return normalized[["Date", "WSPD", "WDIR", "MixHGT_C", "L", "H", "Stab_Class"]]

    def _align_sources_and_met(
        self,
        met_df: pd.DataFrame,
        sources_re: np.ndarray,
    ) -> Tuple[pd.DataFrame, np.ndarray]:
        if len(met_df) == sources_re.shape[0]:
            return met_df.reset_index(drop=True), sources_re

        if sources_re.shape[0] == 1 and len(met_df) > 1:
            logger.info(
                "Replicating single emission timestep across %s meteorology timesteps",
                len(met_df),
            )
            return met_df.reset_index(drop=True), np.repeat(sources_re, len(met_df), axis=0)

        if len(met_df) == 1 and sources_re.shape[0] > 1:
            logger.info(
                "Replicating single meteorology timestep across %s emission timesteps",
                sources_re.shape[0],
            )
            repeated = pd.concat([met_df.iloc[[0]]] * sources_re.shape[0], ignore_index=True)
            if len(self._source_times) == sources_re.shape[0]:
                repeated["Date"] = self._source_times
            return repeated.reset_index(drop=True), sources_re

        raise ValueError(
            f"Cannot align {sources_re.shape[0]} emission timesteps with {len(met_df)} "
            "meteorology timesteps"
        )

    def _ensure_models_loaded(self) -> Dict[str, Dict[str, Any]]:
        if self._models is None:
            resolved_base_dir = self.config.model_base_dir or str(_default_model_base_dir())
            self._model_base_dir = resolved_base_dir
            logger.info(
                "Loading dispersion models from %s for roughness %s",
                resolved_base_dir,
                self.config.roughness_height,
            )
            self._models = {}
        return self._models

    def _get_or_load_model(self, stability_abbrev: str) -> Dict[str, xgb.Booster]:
        """Lazily load model for a specific stability class."""
        if stability_abbrev not in self._models:
            try:
                self._models[stability_abbrev] = load_models_for_stability(
                    stability_abbrev, self.config.roughness_height, self._model_base_dir
                )
            except FileNotFoundError as exc:
                raise FileNotFoundError(
                    f"Model file missing for stability class '{stability_abbrev}': {exc}"
                ) from exc
        return self._models[stability_abbrev]

    def _assemble_result(
        self,
        conc_df: pd.DataFrame,
        receptors_df: pd.DataFrame,
        lons: np.ndarray,
        lats: np.ndarray,
        met_df: pd.DataFrame,
        pollutant: str,
        origin: Tuple[float, float],
        coverage_assessment: Optional[Any] = None,
        road_contributions: Optional[dict] = None,
        road_id_map: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        receptor_frame = receptors_df[["x", "y"]].copy()
        receptor_frame["lon"] = np.asarray(lons, dtype=float)
        receptor_frame["lat"] = np.asarray(lats, dtype=float)
        receptor_frame["receptor_id"] = np.arange(len(receptor_frame))

        results: list[dict[str, Any]] = []
        grid_receptors: list[dict[str, float]] = []
        mean_concs = np.zeros(len(receptor_frame), dtype=float)
        max_concs = np.zeros(len(receptor_frame), dtype=float)
        grouped = conc_df.sort_values(["Receptor_ID", "Date"]).groupby("Receptor_ID", sort=True)
        conc_by_receptor = {int(receptor_id): group.copy() for receptor_id, group in grouped}

        for receptor_id, receptor_row in receptor_frame.iterrows():
            receptor_conc = conc_by_receptor.get(int(receptor_id))
            if receptor_conc is None or receptor_conc.empty:
                concentrations = {}
                mean_conc = 0.0
                max_conc = 0.0
            else:
                concentrations = {
                    _format_time_key(date): float(value)
                    for date, value in zip(receptor_conc["Date"], receptor_conc["Conc"])
                }
                mean_conc = float(receptor_conc["Conc"].mean())
                max_conc = float(receptor_conc["Conc"].max())

            mean_concs[int(receptor_id)] = mean_conc
            max_concs[int(receptor_id)] = max_conc
            results.append(
                {
                    "receptor_id": int(receptor_id),
                    "lon": float(receptor_row["lon"]),
                    "lat": float(receptor_row["lat"]),
                    "local_x": float(receptor_row["x"]),
                    "local_y": float(receptor_row["y"]),
                    "concentrations": concentrations,
                    "mean_conc": mean_conc,
                    "max_conc": max_conc,
                }
            )
            grid_receptors.append(
                {
                    "lon": float(receptor_row["lon"]),
                    "lat": float(receptor_row["lat"]),
                    "mean_conc": mean_conc,
                    "max_conc": max_conc,
                }
            )

        if grid_receptors:
            lon_values = [item["lon"] for item in grid_receptors]
            lat_values = [item["lat"] for item in grid_receptors]
            bounds = {
                "min_lon": float(min(lon_values)),
                "max_lon": float(max(lon_values)),
                "min_lat": float(min(lat_values)),
                "max_lat": float(max(lat_values)),
            }
        else:
            bounds = {"min_lon": 0.0, "max_lon": 0.0, "min_lat": 0.0, "max_lat": 0.0}

        mean_concentration = (
            float(np.mean([item["mean_conc"] for item in results])) if results else 0.0
        )
        max_concentration = float(max((item["max_conc"] for item in results), default=0.0))
        result_data = {
            "query_info": {
                "pollutant": pollutant,
                "n_roads": self._matched_road_count,
                "n_receptors": len(receptors_df),
                "n_time_steps": int(len(met_df)),
                "roughness_height": self.config.roughness_height,
                "met_source": self._met_source_used,
                "local_origin": {"x": float(origin[0]), "y": float(origin[1])},
                "display_grid_resolution_m": float(self.config.display_grid_resolution_m),
            },
            "results": results,
            "summary": {
                "receptor_count": len(results),
                "time_steps": int(len(met_df)),
                "mean_concentration": mean_concentration,
                "max_concentration": max_concentration,
                "unit": "μg/m³",
                "coordinate_system": "WGS-84",
            },
            "concentration_grid": {
                "receptors": grid_receptors,
                "bounds": bounds,
            },
            "raster_grid": aggregate_to_raster(
                receptor_x=receptors_df["x"].to_numpy(dtype=float),
                receptor_y=receptors_df["y"].to_numpy(dtype=float),
                concentrations=mean_concs,
                resolution_m=self.config.display_grid_resolution_m,
                origin_x=origin[0],
                origin_y=origin[1],
                utm_zone=self.config.utm_zone,
                utm_hemisphere=self.config.utm_hemisphere,
            ),
        }
        if coverage_assessment is not None:
            result_data["coverage_assessment"] = (
                coverage_assessment.to_dict()
                if hasattr(coverage_assessment, "to_dict")
                else coverage_assessment
            )
        if road_contributions is not None:
            result_data["road_contributions"] = _serialize_road_contributions(
                road_contributions,
                road_id_map or [],
            )

        return {"status": "success", "data": result_data}


__all__ = [
    "DispersionCalculator",
    "DispersionConfig",
    "ROUGHNESS_DIR_MAP",
    "ROUGHNESS_MAP",
    "SFC_COLUMN_NAMES",
    "STABILITY_ABBREV",
    "STABILITY_CLASSES",
    "aggregate_to_raster",
    "classify_stability",
    "compute_local_origin",
    "convert_coords",
    "emission_to_line_source_strength",
    "generate_receptors_custom_offset",
    "inverse_transform_coords",
    "load_all_models",
    "load_model",
    "make_rectangular_buffer",
    "predict_time_series_xgb",
    "read_sfc",
    "split_polyline_by_interval_with_angle",
]
