"""Terminal summaries for frontend artifact payloads.

The frontend receives rich payloads for maps, charts, tables, and downloads.
This module keeps CLI rendering lightweight by producing compact summaries
without changing the payloads themselves.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


MAX_PREVIEW_ROWS = 3
MAX_COLUMNS = 8


@dataclass
class ArtifactSummary:
    """Compact terminal/debug summary for one frontend artifact."""

    kind: str
    artifact_type: str
    title: str
    frontend: str
    key_stats: Dict[str, Any] = field(default_factory=dict)
    preview: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "kind": self.kind,
            "artifact_type": self.artifact_type,
            "title": self.title,
            "frontend": self.frontend,
            "key_stats": dict(self.key_stats),
        }
        if self.preview is not None:
            payload["preview"] = list(self.preview)
        return payload


def summarize_frontend_artifacts(
    *,
    chart_data: Optional[Dict[str, Any]] = None,
    table_data: Optional[Dict[str, Any]] = None,
    map_data: Optional[Dict[str, Any]] = None,
    download_file: Optional[Dict[str, Any]] = None,
) -> List[ArtifactSummary]:
    """Build terminal-friendly summaries from frontend payloads."""
    summaries: List[ArtifactSummary] = []

    if map_data:
        for payload in _iter_map_payloads(map_data):
            summaries.append(_summarize_map(payload, has_download=bool(download_file)))

    if table_data:
        summaries.append(_summarize_table(table_data, has_download=bool(download_file)))

    if chart_data:
        summaries.append(_summarize_chart(chart_data))

    if download_file and not _table_has_download(table_data):
        summaries.append(_summarize_download(download_file))

    return summaries


def format_artifact_summaries(summaries: Iterable[ArtifactSummary]) -> str:
    """Render artifact summaries as concise terminal text."""
    items = list(summaries)
    if not items:
        return ""

    lines = ["[Artifacts]"]
    for index, item in enumerate(items, start=1):
        type_suffix = f" ({item.artifact_type})" if item.artifact_type else ""
        lines.append(f"{index}) {item.kind.title()}: {item.title}{type_suffix}")
        if item.key_stats:
            lines.append(f"   {_format_stats(item.key_stats)}")
        lines.append(f"   frontend: {item.frontend}")
        if item.preview:
            lines.append(f"   preview: {_format_preview(item.preview)}")
    return "\n".join(lines)


def _iter_map_payloads(map_data: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    if map_data.get("type") == "map_collection" and isinstance(map_data.get("items"), list):
        for item in map_data["items"]:
            if isinstance(item, dict):
                yield item
        return
    yield map_data


def _summarize_map(payload: Dict[str, Any], *, has_download: bool) -> ArtifactSummary:
    artifact_type = str(payload.get("type") or "map")
    title = str(payload.get("title") or _title_from_type(artifact_type))
    stats = _map_stats(payload)
    frontend = "map + legend"
    if has_download:
        frontend += " + download button"
    return ArtifactSummary(
        kind="map",
        artifact_type=artifact_type,
        title=title,
        frontend=frontend,
        key_stats=stats,
    )


def _summarize_table(payload: Dict[str, Any], *, has_download: bool) -> ArtifactSummary:
    columns = payload.get("columns") if isinstance(payload.get("columns"), list) else []
    preview_rows = _rows_preview(payload.get("preview_rows") or payload.get("rows"))
    total_rows = payload.get("total_rows")
    if total_rows is None and isinstance(payload.get("rows"), list):
        total_rows = len(payload["rows"])
    if total_rows is None and isinstance(payload.get("preview_rows"), list):
        total_rows = len(payload["preview_rows"])

    stats: Dict[str, Any] = {
        "rows": total_rows or 0,
        "columns": payload.get("total_columns") or len(columns),
    }
    if columns:
        stats["column_names"] = columns[:MAX_COLUMNS]

    artifact_type = str(payload.get("type") or "table")
    title = str(payload.get("title") or _title_from_type(artifact_type))
    frontend = "table"
    if has_download or _table_has_download(payload):
        frontend += " + download button"

    return ArtifactSummary(
        kind="table",
        artifact_type=artifact_type,
        title=title,
        frontend=frontend,
        key_stats=stats,
        preview=preview_rows,
    )


def _summarize_chart(payload: Dict[str, Any]) -> ArtifactSummary:
    artifact_type = str(payload.get("type") or payload.get("chart_type") or "chart")
    title = str(payload.get("title") or _title_from_type(artifact_type))
    stats: Dict[str, Any] = {}

    pollutants = payload.get("pollutants")
    if isinstance(pollutants, dict):
        series = list(pollutants.keys())
        stats["series"] = series
        points = 0
        for value in pollutants.values():
            if isinstance(value, dict):
                curve = value.get("curve") or value.get("speed_curve") or []
                if isinstance(curve, list):
                    points = max(points, len(curve))
        if points:
            stats["points_per_series"] = points
    elif isinstance(payload.get("series"), list):
        series_payload = payload["series"]
        stats["series_count"] = len(series_payload)
        points = 0
        for item in series_payload:
            if isinstance(item, dict) and isinstance(item.get("data"), list):
                points = max(points, len(item["data"]))
        if points:
            stats["points_per_series"] = points
    elif isinstance(payload.get("data"), list):
        stats["data_points"] = len(payload["data"])

    return ArtifactSummary(
        kind="chart",
        artifact_type=artifact_type,
        title=title,
        frontend="chart",
        key_stats=stats,
    )


def _summarize_download(payload: Dict[str, Any]) -> ArtifactSummary:
    filename = str(payload.get("filename") or "download")
    stats: Dict[str, Any] = {"filename": filename}
    if payload.get("path"):
        stats["path"] = payload["path"]
    return ArtifactSummary(
        kind="download",
        artifact_type="download",
        title=filename,
        frontend="download button",
        key_stats=stats,
    )


def _map_stats(payload: Dict[str, Any]) -> Dict[str, Any]:
    stats: Dict[str, Any] = {}
    if payload.get("pollutant"):
        stats["pollutant"] = payload["pollutant"]

    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    contour_stats = {}
    contour_bands = payload.get("contour_bands")
    if isinstance(contour_bands, dict) and isinstance(contour_bands.get("stats"), dict):
        contour_stats = contour_bands["stats"]

    _copy_first(summary, stats, ["unit"], "unit")
    _copy_first(summary, stats, ["mean_concentration", "avg_concentration", "average"], "avg")
    _copy_first(summary, stats, ["max_concentration", "maximum"], "max")
    _copy_first(contour_stats, stats, ["mean", "avg"], "avg")
    _copy_first(contour_stats, stats, ["max"], "max")
    _copy_first(summary, stats, ["receptor_count", "n_receptors_used"], "receptors")
    _copy_first(summary, stats, ["hotspot_count", "total_hotspots"], "hotspots")
    _copy_first(summary, stats, ["total_links", "link_count"], "links")
    _copy_first(summary, stats, ["n_levels"], "levels")

    links = payload.get("links")
    if isinstance(links, list) and "links" not in stats:
        stats["links"] = len(links)

    raster_grid = payload.get("raster_grid")
    if isinstance(raster_grid, dict):
        if raster_grid.get("rows") is not None and raster_grid.get("cols") is not None:
            stats["grid"] = f"{raster_grid.get('rows')}x{raster_grid.get('cols')}"
        if raster_grid.get("resolution_m") is not None:
            stats["resolution_m"] = raster_grid["resolution_m"]

    feature_count = _feature_count(payload)
    if feature_count:
        stats["features"] = feature_count

    layers = payload.get("layers")
    if isinstance(layers, list):
        stats["layers"] = len(layers)

    return stats


def _feature_count(payload: Dict[str, Any]) -> int:
    total = 0
    layers = payload.get("layers")
    if not isinstance(layers, list):
        return total
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        data = layer.get("data")
        if isinstance(data, dict) and isinstance(data.get("features"), list):
            total += len(data["features"])
    return total


def _copy_first(source: Dict[str, Any], target: Dict[str, Any], keys: List[str], label: str) -> None:
    if label in target:
        return
    for key in keys:
        value = source.get(key)
        if value is not None:
            target[label] = value
            return


def _rows_preview(rows: Any) -> Optional[List[Dict[str, Any]]]:
    if not isinstance(rows, list) or not rows:
        return None
    preview = []
    for row in rows[:MAX_PREVIEW_ROWS]:
        if isinstance(row, dict):
            preview.append(dict(row))
        else:
            preview.append({"value": row})
    return preview


def _table_has_download(table_data: Optional[Dict[str, Any]]) -> bool:
    return bool(isinstance(table_data, dict) and table_data.get("download"))


def _title_from_type(value: str) -> str:
    return value.replace("_", " ").strip().title() or "Artifact"


def _format_stats(stats: Dict[str, Any]) -> str:
    chunks = []
    for key, value in stats.items():
        if isinstance(value, float):
            chunks.append(f"{key}={value:.4g}")
        elif isinstance(value, list):
            chunks.append(f"{key}={', '.join(str(item) for item in value[:MAX_COLUMNS])}")
        else:
            chunks.append(f"{key}={value}")
    return ", ".join(chunks)


def _format_preview(rows: List[Dict[str, Any]]) -> str:
    rendered = []
    for row in rows:
        rendered.append("{" + ", ".join(f"{key}: {value}" for key, value in list(row.items())[:MAX_COLUMNS]) + "}")
    return "; ".join(rendered)

