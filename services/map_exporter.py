"""Server-side static map export utilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, Iterable, Optional, Sequence

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "emission_agent_mpl"))

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.cm import ScalarMappable
from matplotlib.colors import BoundaryNorm, ListedColormap, LogNorm, Normalize
from matplotlib.figure import Figure
import numpy as np
from shapely.geometry import LineString, Point, Polygon, box, shape

from config import get_config

logger = logging.getLogger(__name__)


def _setup_chinese_font() -> Optional[str]:
    """Configure a best-effort CJK font fallback chain for matplotlib."""
    try:
        import matplotlib.font_manager as fm
    except Exception:
        matplotlib.rcParams["font.sans-serif"] = ["DejaVu Sans"]
        matplotlib.rcParams["axes.unicode_minus"] = False
        return None

    candidates = [
        "WenQuanYi Micro Hei",
        "WenQuanYi Zen Hei",
        "Noto Sans CJK SC",
        "Noto Sans SC",
        "Source Han Sans SC",
        "SimHei",
        "Microsoft YaHei",
        "PingFang SC",
        "Hiragino Sans GB",
        "Arial Unicode MS",
    ]
    available = {font.name for font in fm.fontManager.ttflist}
    for font_name in candidates:
        if font_name in available:
            matplotlib.rcParams["font.sans-serif"] = [font_name, "DejaVu Sans"]
            matplotlib.rcParams["axes.unicode_minus"] = False
            return font_name

    matplotlib.rcParams["font.sans-serif"] = ["DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    return None


_CJK_FONT = _setup_chinese_font()

try:  # pragma: no cover - optional dependency
    import contextily as ctx
except Exception:  # pragma: no cover - optional dependency
    ctx = None
HAS_CONTEXTILY = ctx is not None

try:  # pragma: no cover - optional dependency
    from matplotlib_scalebar.scalebar import ScaleBar
except Exception:  # pragma: no cover - optional dependency
    ScaleBar = None
HAS_SCALEBAR = ScaleBar is not None


@dataclass
class PlotPayload:
    """Prepared plotting payload for one exported map."""

    kind: str
    gdf: gpd.GeoDataFrame
    cmap: Any
    norm: Any
    colorbar_norm: Any
    legend_label: str
    stats: Dict[str, Any]
    title: str
    subtitle: str
    resolution_label: str = ""
    boundaries: Optional[list[float]] = None


class MapExporter:
    """服务端静态地图导出器，基于 matplotlib + geopandas。"""

    def __init__(self, runtime_config: Optional[Any] = None):
        self.runtime_config = runtime_config or get_config()
        self._tile_server_reachable: Optional[bool] = None

    def _create_figure(self, figsize: tuple[float, float]) -> tuple[Figure, Any]:
        fig = Figure(figsize=figsize)
        FigureCanvasAgg(fig)
        ax = fig.add_subplot(1, 1, 1)
        return fig, ax

    def cleanup_expired_exports(
        self,
        output_dir: Optional[Path | str] = None,
        ttl_hours: Optional[int] = None,
    ) -> None:
        """Delete exported files older than the configured TTL."""
        export_dir = Path(output_dir or self.runtime_config.map_export_dir)
        if not export_dir.exists():
            return

        ttl = int(ttl_hours if ttl_hours is not None else self.runtime_config.map_export_ttl_hours)
        cutoff = datetime.now() - timedelta(hours=max(ttl, 0))
        for path in export_dir.iterdir():
            if not path.is_file():
                continue
            try:
                modified_at = datetime.fromtimestamp(path.stat().st_mtime)
            except OSError:
                continue
            if modified_at < cutoff:
                try:
                    path.unlink()
                except OSError:
                    logger.warning("Failed to remove expired export %s", path, exc_info=True)

    def export_dispersion_map(
        self,
        dispersion_result: dict,
        output_path: str | Path,
        format: str = "png",
        dpi: int = 300,
        figsize: tuple[float, float] = (12, 10),
        add_basemap: bool = True,
        add_roads: bool = True,
        add_colorbar: bool = True,
        add_title: bool = True,
        add_scalebar: bool = True,
        title: str | None = None,
        language: str = "zh",
    ) -> str:
        """导出扩散浓度场静态地图。"""
        export_language = self._resolve_language(language)
        data = self._unwrap_result_data(dispersion_result)
        plot_payload = self._build_dispersion_plot_payload(
            data,
            title=title,
            language=export_language,
        )
        roads_gdf = self._extract_roads_gdf(data) if add_roads else None

        fig, ax = self._create_figure(figsize)
        self._plot_payload(
            fig=fig,
            ax=ax,
            plot_payload=plot_payload,
            roads_gdf=roads_gdf,
            add_basemap=add_basemap,
            add_colorbar=add_colorbar,
            add_title=add_title,
            add_scalebar=add_scalebar,
        )
        self._add_metadata_footer(fig, data)
        return self._save_figure(fig, output_path, format=format, dpi=dpi)

    def export_hotspot_map(
        self,
        hotspot_result: dict,
        output_path: str | Path,
        format: str = "png",
        dpi: int = 300,
        figsize: tuple[float, float] = (12, 10),
        add_basemap: bool = True,
        add_roads: bool = True,
        add_colorbar: bool = True,
        add_title: bool = True,
        add_scalebar: bool = True,
        title: str | None = None,
        language: str = "zh",
    ) -> str:
        """导出热点分析静态地图。"""
        export_language = self._resolve_language(language)
        data = self._unwrap_result_data(hotspot_result)
        plot_payload = self._build_hotspot_plot_payload(
            data,
            title=title,
            language=export_language,
        )
        roads_gdf = self._extract_roads_gdf(data) if add_roads else None
        hotspots_gdf = self._extract_hotspots_gdf(data)

        fig, ax = self._create_figure(figsize)
        self._plot_payload(
            fig=fig,
            ax=ax,
            plot_payload=plot_payload,
            roads_gdf=roads_gdf,
            add_basemap=add_basemap,
            add_colorbar=add_colorbar,
            add_title=add_title,
            add_scalebar=add_scalebar,
        )
        self._overlay_hotspots(ax, hotspots_gdf)
        self._add_metadata_footer(fig, data)
        return self._save_figure(fig, output_path, format=format, dpi=dpi)

    def export_emission_map(
        self,
        emission_result: dict,
        output_path: str | Path,
        format: str = "png",
        dpi: int = 300,
        figsize: tuple[float, float] = (12, 10),
        add_basemap: bool = True,
        add_roads: bool = False,
        add_colorbar: bool = True,
        add_title: bool = True,
        add_scalebar: bool = True,
        title: str | None = None,
        language: str = "zh",
    ) -> str:
        """导出排放强度线图。"""
        export_language = self._resolve_language(language)
        data = self._unwrap_result_data(emission_result)
        plot_payload = self._build_emission_plot_payload(
            data,
            title=title,
            language=export_language,
        )

        fig, ax = self._create_figure(figsize)
        self._plot_payload(
            fig=fig,
            ax=ax,
            plot_payload=plot_payload,
            roads_gdf=None,
            add_basemap=add_basemap,
            add_colorbar=add_colorbar,
            add_title=add_title,
            add_scalebar=add_scalebar,
        )
        self._add_metadata_footer(fig, data)
        return self._save_figure(fig, output_path, format=format, dpi=dpi)

    def _unwrap_result_data(self, result_payload: dict) -> dict:
        """Normalize a stored tool payload to its underlying data dict."""
        data = result_payload
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            nested = data["data"]
            if any(
                key in nested
                for key in ("contour_bands", "raster_grid", "hotspots", "results", "roads_wgs84")
            ):
                data = nested
        return data if isinstance(data, dict) else {}

    def _build_dispersion_plot_payload(
        self,
        data: dict,
        *,
        title: Optional[str],
        language: str,
    ) -> PlotPayload:
        contour_payload = self._extract_contour_payload(data)
        pollutant = str(data.get("query_info", {}).get("pollutant") or data.get("pollutant") or "NOx")

        if contour_payload is not None:
            stats = contour_payload["stats"]
            interp_resolution = contour_payload["interp_resolution_m"]
            title_text = title or self._localized_title(language, pollutant, "dispersion")
            subtitle = self._build_dispersion_subtitle(
                language=language,
                mean_value=float(stats.get("mean_concentration", 0.0)),
                max_value=float(stats.get("max_concentration", 0.0)),
                resolution_text=f"{int(round(interp_resolution))}m",
            )
            return PlotPayload(
                kind="contour",
                gdf=contour_payload["gdf"],
                cmap=contour_payload["cmap"],
                norm=contour_payload["norm"],
                colorbar_norm=BoundaryNorm(contour_payload["boundaries"], contour_payload["cmap"].N),
                legend_label=f"{pollutant} Concentration (μg/m³)",
                stats=stats,
                title=title_text,
                subtitle=subtitle,
                resolution_label=f"{int(round(interp_resolution))}m interpolation",
                boundaries=contour_payload["boundaries"],
            )

        raster_payload = self._extract_raster_payload(data)
        if raster_payload is None:
            raise ValueError("Dispersion result does not contain contour_bands or raster_grid")

        summary = data.get("summary", {})
        resolution = raster_payload["resolution_m"]
        title_text = title or self._localized_title(language, pollutant, "dispersion")
        subtitle = self._build_dispersion_subtitle(
            language=language,
            mean_value=float(summary.get("mean_concentration", 0.0)),
            max_value=float(summary.get("max_concentration", 0.0)),
            resolution_text=f"{int(round(resolution))}m",
        )
        return PlotPayload(
            kind="raster",
            gdf=raster_payload["gdf"],
            cmap=matplotlib.colormaps.get_cmap("YlOrRd"),
            norm=raster_payload["norm"],
            colorbar_norm=raster_payload["norm"],
            legend_label=f"{pollutant} Concentration (μg/m³)",
            stats={
                "mean_concentration": float(summary.get("mean_concentration", 0.0)),
                "max_concentration": float(summary.get("max_concentration", 0.0)),
            },
            title=title_text,
            subtitle=subtitle,
            resolution_label=f"{int(round(resolution))}m grid",
        )

    def _build_hotspot_plot_payload(
        self,
        data: dict,
        *,
        title: Optional[str],
        language: str,
    ) -> PlotPayload:
        pollutant = str(data.get("query_info", {}).get("pollutant") or data.get("pollutant") or "NOx")
        dispersion_payload = self._build_dispersion_plot_payload(data, title=None, language=language)
        summary = data.get("summary", {})
        hotspot_count = len(data.get("hotspots", []))
        dispersion_payload.title = title or self._localized_title(language, pollutant, "hotspot")
        dispersion_payload.subtitle = self._build_hotspot_subtitle(
            language=language,
            hotspot_count=hotspot_count,
            max_concentration=float(summary.get("max_concentration", 0.0)),
            total_area=float(summary.get("total_hotspot_area_m2", 0.0)),
        )
        return dispersion_payload

    def _build_emission_plot_payload(
        self,
        data: dict,
        *,
        title: Optional[str],
        language: str,
    ) -> PlotPayload:
        results = data.get("results", [])
        if not isinstance(results, list) or not results:
            raise ValueError("Emission result does not contain road results")

        pollutant = self._pick_emission_pollutant(data)
        rows = []
        for record in results:
            if not isinstance(record, dict):
                continue
            geometry = self._parse_geometry(record.get("geometry") or record.get("coordinates"))
            if geometry is None or geometry.is_empty:
                continue
            total_emissions = record.get("total_emissions_kg_per_hr", {})
            link_length = float(record.get("link_length_km", 0.0) or 0.0)
            raw_value = float(total_emissions.get(pollutant, 0.0))
            value = raw_value / link_length if link_length > 0 else raw_value
            rows.append(
                {
                    "geometry": geometry,
                    "value": value,
                    "road_id": str(record.get("link_id") or record.get("NAME_1") or ""),
                }
            )

        if not rows:
            raise ValueError("Emission result does not contain renderable road geometries")

        gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326").to_crs(epsg=3857)
        values = gdf["value"].to_numpy(dtype=float)
        positive_values = values[values > 0]
        if positive_values.size > 0 and np.max(positive_values) > np.min(positive_values):
            norm = LogNorm(vmin=max(float(np.min(positive_values)), 1e-6), vmax=float(np.max(positive_values)))
        else:
            vmin = float(np.min(values))
            vmax = float(np.max(values))
            if vmax <= vmin:
                vmax = vmin + 1e-6
            norm = Normalize(vmin=vmin, vmax=vmax)
        title_text = title or self._localized_title(language, pollutant, "emission")
        subtitle = self._build_emission_subtitle(language=language, road_count=len(gdf))
        return PlotPayload(
            kind="emission",
            gdf=gdf,
            cmap=matplotlib.colormaps.get_cmap("YlOrRd"),
            norm=norm,
            colorbar_norm=norm,
            legend_label=f"{pollutant} Emission Intensity (kg/(h·km))",
            stats={"road_count": len(gdf)},
            title=title_text,
            subtitle=subtitle,
        )

    def _plot_payload(
        self,
        *,
        fig: Any,
        ax: Any,
        plot_payload: PlotPayload,
        roads_gdf: Optional[gpd.GeoDataFrame],
        add_basemap: bool,
        add_colorbar: bool,
        add_title: bool,
        add_scalebar: bool,
    ) -> None:
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")
        total_bounds = np.array(plot_payload.gdf.total_bounds, dtype=float)
        if roads_gdf is not None and not roads_gdf.empty:
            road_bounds = np.array(roads_gdf.total_bounds, dtype=float)
            total_bounds[0] = min(total_bounds[0], road_bounds[0])
            total_bounds[1] = min(total_bounds[1], road_bounds[1])
            total_bounds[2] = max(total_bounds[2], road_bounds[2])
            total_bounds[3] = max(total_bounds[3], road_bounds[3])

        self._set_axis_extent(ax, total_bounds)
        if add_basemap:
            self._try_add_basemap(ax)

        if plot_payload.kind == "contour":
            plot_payload.gdf.plot(
                ax=ax,
                column="level_index",
                cmap=plot_payload.cmap,
                norm=plot_payload.norm,
                alpha=0.75,
                edgecolor="white",
                linewidth=0.3,
                zorder=10,
            )
        elif plot_payload.kind == "raster":
            plot_payload.gdf.plot(
                ax=ax,
                column="value",
                cmap=plot_payload.cmap,
                norm=plot_payload.norm,
                alpha=0.75,
                edgecolor="none",
                linewidth=0.0,
                zorder=10,
            )
        elif plot_payload.kind == "emission":
            plot_payload.gdf.plot(
                ax=ax,
                column="value",
                cmap=plot_payload.cmap,
                norm=plot_payload.norm,
                linewidth=2.5,
                alpha=0.92,
                zorder=10,
            )

        if roads_gdf is not None and not roads_gdf.empty:
            roads_gdf.plot(
                ax=ax,
                color="#C0C0C0",
                linewidth=0.3,
                alpha=0.25,
                zorder=2,
            )

        if add_colorbar:
            self._add_colorbar(fig, ax, plot_payload)
        if add_title:
            self._add_title_block(fig, plot_payload)
        if add_scalebar:
            self._add_scalebar(ax, total_bounds)
        self._add_north_arrow(ax)

        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(True)
            spine.set_color("#E0E0E0")
            spine.set_linewidth(0.5)

    def _extract_contour_payload(self, data: dict) -> Optional[dict]:
        contour_bands = data.get("contour_bands")
        if not isinstance(contour_bands, dict) or contour_bands.get("error"):
            return None

        geojson = contour_bands.get("geojson")
        features = geojson.get("features") if isinstance(geojson, dict) else None
        if not isinstance(features, list) or not features:
            return None

        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        if gdf.empty:
            return None
        gdf = gdf.to_crs(epsg=3857)
        gdf["level_index"] = gdf["level_index"].astype(int)
        band_count = max(int(contour_bands.get("n_levels", len(gdf))), 1)
        cmap = ListedColormap(
            matplotlib.colormaps.get_cmap("YlOrRd")(np.linspace(0.1, 0.98, band_count))
        )
        level_boundaries = self._derive_contour_boundaries(features)
        norm = BoundaryNorm(np.arange(-0.5, band_count + 0.5, 1.0), cmap.N)
        return {
            "gdf": gdf,
            "cmap": cmap,
            "norm": norm,
            "boundaries": level_boundaries,
            "stats": contour_bands.get("stats", {}) if isinstance(contour_bands.get("stats"), dict) else {},
            "interp_resolution_m": float(contour_bands.get("interp_resolution_m", 10.0)),
        }

    def _extract_raster_payload(self, data: dict) -> Optional[dict]:
        raster_grid = data.get("raster_grid")
        if not isinstance(raster_grid, dict):
            return None
        cell_centers = raster_grid.get("cell_centers_wgs84", [])
        if not isinstance(cell_centers, list) or not cell_centers:
            return None

        resolution = float(raster_grid.get("resolution_m", 50.0))
        rows = []
        for cell in cell_centers:
            try:
                mean_conc = float(cell.get("mean_conc", 0.0))
                lon = float(cell["lon"])
                lat = float(cell["lat"])
            except (KeyError, TypeError, ValueError):
                continue
            if mean_conc <= 0:
                continue
            cos_lat = max(abs(np.cos(np.radians(lat))), 1e-6)
            dlat = (resolution / 2.0) / 111320.0
            dlon = (resolution / 2.0) / (111320.0 * cos_lat)
            rows.append(
                {
                    "geometry": Polygon(
                        [
                            (lon - dlon, lat - dlat),
                            (lon + dlon, lat - dlat),
                            (lon + dlon, lat + dlat),
                            (lon - dlon, lat + dlat),
                            (lon - dlon, lat - dlat),
                        ]
                    ),
                    "value": mean_conc,
                }
            )
        if not rows:
            return None

        gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326").to_crs(epsg=3857)
        values = gdf["value"].to_numpy(dtype=float)
        positive = values[values > 0]
        if positive.size > 0 and np.max(positive) > np.min(positive):
            norm = LogNorm(vmin=max(float(np.min(positive)), 1e-6), vmax=float(np.max(positive)))
        else:
            vmin = float(np.min(values))
            vmax = float(np.max(values))
            if vmax <= vmin:
                vmax = vmin + 1e-6
            norm = Normalize(vmin=vmin, vmax=vmax)
        return {"gdf": gdf, "norm": norm, "resolution_m": resolution}

    def _extract_roads_gdf(self, data: dict) -> Optional[gpd.GeoDataFrame]:
        roads_geojson = data.get("roads_wgs84")
        if not isinstance(roads_geojson, dict) or not isinstance(roads_geojson.get("features"), list):
            return None
        gdf = gpd.GeoDataFrame.from_features(roads_geojson["features"], crs="EPSG:4326")
        if gdf.empty:
            return None
        return gdf.to_crs(epsg=3857)

    def _extract_hotspots_gdf(self, data: dict) -> gpd.GeoDataFrame:
        hotspots = data.get("hotspots", [])
        rows = []
        for hotspot in hotspots if isinstance(hotspots, list) else []:
            if not isinstance(hotspot, dict):
                continue
            bbox = hotspot.get("bbox")
            if not isinstance(bbox, list) or len(bbox) < 4:
                continue
            rows.append(
                {
                    "geometry": box(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])),
                    "rank": int(hotspot.get("rank", 0) or 0),
                    "center_lon": float(hotspot.get("center", {}).get("lon", 0.0) or 0.0),
                    "center_lat": float(hotspot.get("center", {}).get("lat", 0.0) or 0.0),
                }
            )
        if not rows:
            return gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs="EPSG:4326")
        return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326").to_crs(epsg=3857)

    def _overlay_hotspots(self, ax: Any, hotspots_gdf: gpd.GeoDataFrame) -> None:
        if hotspots_gdf.empty:
            return
        hotspots_gdf.plot(
            ax=ax,
            facecolor=(1.0, 1.0, 1.0, 0.08),
            edgecolor="#B71C1C",
            linewidth=0.8,
            linestyle="-",
            zorder=8,
        )
        for _, row in hotspots_gdf.iterrows():
            point_gdf = gpd.GeoDataFrame(
                {"geometry": [Point(row["center_lon"], row["center_lat"])]},
                geometry="geometry",
                crs="EPSG:4326",
            ).to_crs(epsg=3857)
            x = float(point_gdf.geometry.iloc[0].x)
            y = float(point_gdf.geometry.iloc[0].y)
            ax.annotate(
                f"#{int(row['rank'])}",
                xy=(x, y),
                fontsize=8,
                fontweight="bold",
                color="#333333",
                ha="center",
                va="center",
                bbox={
                    "boxstyle": "circle,pad=0.3",
                    "fc": "white",
                    "ec": "#B71C1C",
                    "lw": 1.0,
                    "alpha": 0.9,
                },
                zorder=10,
            )

    def _add_colorbar(self, fig: Any, ax: Any, plot_payload: PlotPayload) -> None:
        sm = ScalarMappable(cmap=plot_payload.cmap, norm=plot_payload.colorbar_norm)
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax, orientation="vertical", shrink=0.7, pad=0.02)
        cbar.set_label(plot_payload.legend_label, fontsize=10)
        cbar.ax.tick_params(labelsize=9, length=3, width=0.5, colors="#4B5563")
        cbar.outline.set_linewidth(0.5)
        cbar.outline.set_edgecolor("#E0E0E0")

        if plot_payload.boundaries and len(plot_payload.boundaries) > 1:
            display_boundaries = self._filter_colorbar_boundaries(plot_payload.boundaries)
            ticks = self._pick_colorbar_ticks(display_boundaries)
            cbar.set_ticks(ticks)
            cbar.ax.set_yticklabels([self._format_numeric_tick(value) for value in ticks])

    def _add_title_block(self, fig: Figure, plot_payload: PlotPayload) -> None:
        fig.subplots_adjust(top=0.90)
        fig.text(
            0.5,
            0.96,
            plot_payload.title,
            ha="center",
            va="top",
            fontsize=14,
            fontweight=600,
            color="#333333",
        )
        fig.text(
            0.5,
            0.93,
            plot_payload.subtitle,
            ha="center",
            va="top",
            fontsize=9,
            color="#666666",
        )

    def _add_scalebar(self, ax: Any, bounds: Sequence[float]) -> None:
        if HAS_SCALEBAR:  # pragma: no branch - optional dependency
            try:
                ax.add_artist(ScaleBar(dx=1.0, units="m", location="lower left", box_alpha=0.7))
                return
            except Exception:
                logger.warning("Failed to add matplotlib_scalebar, falling back to manual scalebar", exc_info=True)

        min_x, min_y, max_x, max_y = [float(value) for value in bounds]
        width = max_x - min_x
        height = max_y - min_y
        if width <= 0 or height <= 0:
            return

        scale_length = self._nice_distance(width * 0.2)
        x0 = min_x + width * 0.06
        y0 = min_y + height * 0.05
        ax.plot([x0, x0 + scale_length], [y0, y0], color="black", linewidth=3.0, zorder=30)
        ax.text(
            x0 + scale_length / 2.0,
            y0 + height * 0.015,
            self._format_distance_label(scale_length),
            ha="center",
            va="bottom",
            fontsize=9,
            color="black",
            zorder=30,
        )

    def _add_north_arrow(self, ax: Any) -> None:
        ax.annotate(
            "N",
            xy=(0.96, 0.92),
            xytext=(0.96, 0.80),
            xycoords="axes fraction",
            textcoords="axes fraction",
            ha="center",
            va="center",
            fontsize=11,
            fontweight="bold",
            arrowprops={"arrowstyle": "-|>", "color": "#111827", "lw": 1.5},
            zorder=40,
        )

    def _can_reach_tile_server(self, timeout: float = 2.0) -> bool:
        """Quickly probe tile-server reachability to avoid long contextily timeouts."""
        import socket

        try:
            with socket.create_connection(
                ("a.basemaps.cartocdn.com", 443),
                timeout=max(float(timeout), 0.1),
            ):
                return True
        except (socket.timeout, OSError):
            return False

    def _try_add_basemap(self, ax: Any) -> None:
        if not bool(getattr(self.runtime_config, "map_export_basemap_enabled", True)):
            return
        if not HAS_CONTEXTILY:
            return
        timeout = float(getattr(self.runtime_config, "map_export_basemap_timeout", 2) or 2)
        if self._tile_server_reachable is None:
            self._tile_server_reachable = self._can_reach_tile_server(timeout=timeout)
        if not self._tile_server_reachable:
            logger.info("Tile server is unreachable, skipping basemap overlay")
            return
        try:  # pragma: no cover - depends on optional dependency + network
            ctx.add_basemap(
                ax,
                crs="EPSG:3857",
                source=ctx.providers.CartoDB.PositronNoLabels,
                attribution=False,
                reset_extent=False,
            )
        except Exception:
            logger.warning("Basemap rendering failed, exporting without basemap", exc_info=True)

    def _save_figure(
        self,
        fig: Any,
        output_path: str | Path,
        *,
        format: str,
        dpi: int,
    ) -> str:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white", transparent=False, format=format)
        fig.clear()
        return str(path)

    def _add_metadata_footer(self, fig: Figure, data: dict) -> None:
        footer_text = self._build_metadata_footer_text(data)
        if not footer_text:
            return
        fig.subplots_adjust(bottom=max(fig.subplotpars.bottom, 0.08))
        fig.text(
            0.5,
            0.012,
            footer_text,
            ha="center",
            va="bottom",
            fontsize=7,
            color="#999999",
            style="italic",
        )

    def _build_metadata_footer_text(self, data: dict) -> str:
        metadata_parts: list[str] = []
        payload = data if isinstance(data, dict) else {}
        query_info = payload.get("query_info", {}) if isinstance(payload.get("query_info"), dict) else {}

        pollutant = query_info.get("pollutant")
        if not pollutant:
            pollutants = query_info.get("pollutants")
            if isinstance(pollutants, list) and pollutants:
                pollutant = pollutants[0]
        if pollutant:
            metadata_parts.append(f"Pollutant: {pollutant}")

        met_source = query_info.get("met_source") or payload.get("met_source")
        if met_source:
            metadata_parts.append(f"Met: {met_source}")

        scenario = str(payload.get("scenario_label") or "").strip()
        if scenario and scenario != "baseline":
            metadata_parts.append(f"Scenario: {scenario}")

        metadata_parts.append(datetime.now().strftime("%Y-%m-%d %H:%M"))
        metadata_parts.append("Emission Agent")
        return " | ".join(metadata_parts)

    def _set_axis_extent(self, ax: Any, bounds: Sequence[float]) -> None:
        min_x, min_y, max_x, max_y = [float(value) for value in bounds]
        width = max(max_x - min_x, 1.0)
        height = max(max_y - min_y, 1.0)
        pad_x = width * 0.05
        pad_y = height * 0.05
        ax.set_xlim(min_x - pad_x, max_x + pad_x)
        ax.set_ylim(min_y - pad_y, max_y + pad_y)
        ax.set_aspect("equal")

    def _pick_emission_pollutant(self, data: dict) -> str:
        query_info = data.get("query_info", {})
        pollutant = query_info.get("pollutants")
        if isinstance(pollutant, list) and pollutant:
            return str(pollutant[0])
        results = data.get("results", [])
        for record in results if isinstance(results, list) else []:
            emissions = record.get("total_emissions_kg_per_hr")
            if isinstance(emissions, dict) and emissions:
                return str(next(iter(emissions.keys())))
        return "NOx"

    def _parse_geometry(self, raw_geometry: Any) -> Optional[Any]:
        if raw_geometry is None:
            return None
        if hasattr(raw_geometry, "geom_type"):
            return raw_geometry
        if isinstance(raw_geometry, dict) and "type" in raw_geometry and "coordinates" in raw_geometry:
            return shape(raw_geometry)
        if isinstance(raw_geometry, (list, tuple)) and raw_geometry:
            first = raw_geometry[0]
            if isinstance(first, (list, tuple)) and len(first) >= 2:
                return LineString(raw_geometry)
        if isinstance(raw_geometry, str):
            try:
                from shapely import wkt

                return wkt.loads(raw_geometry)
            except Exception:
                return None
        return None

    def _derive_contour_boundaries(self, features: Iterable[dict]) -> list[float]:
        sorted_features = sorted(
            (feature for feature in features if isinstance(feature, dict)),
            key=lambda item: int(item.get("properties", {}).get("level_index", 0)),
        )
        if not sorted_features:
            return [0.0, 1.0]

        boundaries = [float(sorted_features[0]["properties"].get("level_min", 0.0))]
        for feature in sorted_features:
            boundaries.append(float(feature["properties"].get("level_max", boundaries[-1])))
        return boundaries

    def _pick_colorbar_ticks(self, boundaries: list[float]) -> list[float]:
        if len(boundaries) <= 6:
            return boundaries
        step = max(1, int(round((len(boundaries) - 1) / 5)))
        ticks = boundaries[::step]
        if ticks[-1] != boundaries[-1]:
            ticks.append(boundaries[-1])
        if ticks[0] != boundaries[0]:
            ticks.insert(0, boundaries[0])
        return ticks

    def _filter_colorbar_boundaries(
        self,
        boundaries: Sequence[float],
        display_threshold: float = 0.001,
    ) -> list[float]:
        cleaned = sorted(
            {
                float(value)
                for value in boundaries
                if value is not None and np.isfinite(float(value))
            }
        )
        if len(cleaned) <= 1:
            return cleaned

        filtered = [value for value in cleaned if value >= display_threshold]
        if not filtered:
            return [cleaned[-1]]

        if filtered[0] > cleaned[0]:
            filtered.insert(0, display_threshold)
        return filtered

    def _format_numeric_tick(self, value: float) -> str:
        if value >= 1.0:
            return f"{value:.2f}"
        if value >= 0.01:
            return f"{value:.3f}"
        if value >= 0.001:
            return f"{value:.4f}"
        return f"{value:.1e}"

    def _nice_distance(self, value_m: float) -> float:
        value_m = max(float(value_m), 1.0)
        exponent = int(np.floor(np.log10(value_m)))
        base = value_m / (10 ** exponent)
        if base < 2:
            nice = 1
        elif base < 5:
            nice = 2
        else:
            nice = 5
        return float(nice * (10 ** exponent))

    def _format_distance_label(self, value_m: float) -> str:
        if value_m >= 1000:
            return f"{value_m / 1000:.1f} km"
        return f"{int(round(value_m))} m"

    def _localized_title(self, language: str, pollutant: str, kind: str) -> str:
        if str(language).lower().startswith("en"):
            if kind == "hotspot":
                return f"{pollutant} Pollution Hotspot Analysis"
            if kind == "emission":
                return f"{pollutant} Emission Intensity"
            return f"{pollutant} Concentration Field"
        if kind == "hotspot":
            return f"{pollutant} 热点分析图"
        if kind == "emission":
            return f"{pollutant} 排放强度图"
        return f"{pollutant} 浓度场"

    def _build_dispersion_subtitle(
        self,
        *,
        language: str,
        mean_value: float,
        max_value: float,
        resolution_text: str,
    ) -> str:
        if str(language).lower().startswith("en"):
            return (
                f"Mean: {mean_value:.4f} μg/m³ | "
                f"Max: {max_value:.4f} μg/m³ | "
                f"Resolution: {resolution_text}"
            )
        return (
            f"平均浓度: {mean_value:.4f} μg/m³ | "
            f"最大浓度: {max_value:.4f} μg/m³ | "
            f"分辨率: {resolution_text}"
        )

    def _build_hotspot_subtitle(
        self,
        *,
        language: str,
        hotspot_count: int,
        max_concentration: float,
        total_area: float,
    ) -> str:
        if str(language).lower().startswith("en"):
            return (
                f"Hotspots: {hotspot_count} | "
                f"Max: {max_concentration:.4f} μg/m³ | "
                f"Area: {total_area:.0f} m²"
            )
        return (
            f"热点数量: {hotspot_count} | "
            f"最高浓度: {max_concentration:.4f} μg/m³ | "
            f"总面积: {total_area:.0f} m²"
        )

    def _build_emission_subtitle(self, *, language: str, road_count: int) -> str:
        if str(language).lower().startswith("en"):
            return f"Road segments: {road_count}"
        return f"路段数量: {road_count}"

    def _resolve_language(self, language: str) -> str:
        resolved = str(language or "zh")
        normalized = resolved.lower()
        if normalized.startswith("zh") and _CJK_FONT is None:
            return "en"
        return resolved


__all__ = ["MapExporter"]
