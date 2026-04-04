"""Static map export endpoints."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import hashlib
import json as _json
import logging
from pathlib import Path
import re
from typing import Optional
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from .auth import auth_service
from .models import ExportMapRequest
from .session import SessionRegistry
from config import get_config
from services.map_exporter import MapExporter

router = APIRouter()
_export_executor = ThreadPoolExecutor(max_workers=2)
logger = logging.getLogger(__name__)

MEDIA_TYPES = {
    "png": "image/png",
    "svg": "image/svg+xml",
    "pdf": "application/pdf",
}


def get_user_id(request: Request) -> str:
    """Extract user id using the same rules as the main API routes."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
        try:
            payload = auth_service.decode_token(token)
            if payload and "sub" in payload:
                return str(payload["sub"])
        except Exception:
            pass

    user_id = request.headers.get("X-User-ID")
    if user_id:
        return user_id.strip()
    return str(uuid.uuid4())


def _build_data_fingerprint(stored_data: dict) -> str:
    """Build a compact fingerprint from the stored result payload."""
    raw = _json.dumps(stored_data, sort_keys=True, default=str, ensure_ascii=False)
    truncated = raw[:2000]
    return hashlib.sha256(truncated.encode("utf-8")).hexdigest()[:16]


def _safe_label(value: Optional[str], fallback: str) -> str:
    label = (value or fallback).strip() or fallback
    sanitized = re.sub(r"[^0-9A-Za-z_\-]+", "_", label)
    return sanitized.strip("_") or fallback


def _make_export_cache_key(payload: ExportMapRequest, data_fingerprint: str) -> str:
    """Build a stable cache key from export params and result fingerprint."""
    key_dict = {
        "result_type": payload.result_type,
        "scenario_label": payload.scenario_label,
        "format": payload.format,
        "dpi": payload.dpi,
        "add_basemap": payload.add_basemap,
        "add_roads": payload.add_roads,
        "language": payload.language,
        "data": data_fingerprint,
    }
    raw = _json.dumps(key_dict, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _export_map_sync(
    *,
    exporter: MapExporter,
    result_type: str,
    stored_data: dict,
    output_path: Path,
    export_format: str,
    dpi: int,
    add_basemap: bool,
    add_roads: bool,
    language: str,
) -> str:
    if result_type == "dispersion":
        return exporter.export_dispersion_map(
            stored_data,
            output_path=output_path,
            format=export_format,
            dpi=dpi,
            add_basemap=add_basemap,
            add_roads=add_roads,
            language=language,
        )
    if result_type == "hotspot":
        return exporter.export_hotspot_map(
            stored_data,
            output_path=output_path,
            format=export_format,
            dpi=dpi,
            add_basemap=add_basemap,
            add_roads=add_roads,
            language=language,
        )
    if result_type == "emission":
        return exporter.export_emission_map(
            stored_data,
            output_path=output_path,
            format=export_format,
            dpi=dpi,
            add_basemap=add_basemap,
            add_roads=False,
            language=language,
        )
    raise ValueError(f"Unsupported result_type: {result_type}")


@router.post("/export_map")
async def export_map(payload: ExportMapRequest, request: Request):
    """Export the current session's stored spatial result as a static image."""
    config = get_config()
    result_type = str(payload.result_type or "dispersion").strip().lower()
    export_format = str(payload.format or config.map_export_default_format).strip().lower()
    if export_format not in MEDIA_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported export format: {export_format}")

    if not payload.session_id:
        raise HTTPException(status_code=400, detail="session_id is required for map export")

    user_id = get_user_id(request)
    manager = SessionRegistry.get(user_id)
    session = manager.get_session(str(payload.session_id))
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    context_store = getattr(session.router, "context_store", None)
    if context_store is None:
        raise HTTPException(status_code=404, detail="No in-memory analysis results available for this session")

    stored = context_store.get_by_type(result_type, label=str(payload.scenario_label or "baseline"))
    if stored is None or not isinstance(stored.data, dict):
        raise HTTPException(
            status_code=404,
            detail=f"No stored {result_type} result found for scenario '{payload.scenario_label}'",
        )

    exporter = MapExporter(runtime_config=config)
    exporter.cleanup_expired_exports()

    export_dir = Path(config.map_export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    data_fingerprint = _build_data_fingerprint(stored.data)
    cache_key = _make_export_cache_key(payload, data_fingerprint)
    scenario_fragment = _safe_label(payload.scenario_label, "baseline")
    cached_path = export_dir / f"{result_type}_{scenario_fragment}_{cache_key}.{export_format}"
    if cached_path.exists():
        logger.info("[export_map] cache hit: %s", cached_path.name)
        return FileResponse(
            path=str(cached_path),
            media_type=MEDIA_TYPES[export_format],
            filename=cached_path.name,
        )

    output_path = cached_path

    if result_type not in {"dispersion", "hotspot", "emission"}:
        raise HTTPException(status_code=400, detail=f"Unsupported result_type: {result_type}")
    loop = asyncio.get_running_loop()
    file_path = await loop.run_in_executor(
        _export_executor,
        partial(
            _export_map_sync,
            exporter=exporter,
            result_type=result_type,
            stored_data=stored.data,
            output_path=output_path,
            export_format=export_format,
            dpi=int(payload.dpi or config.map_export_dpi),
            add_basemap=bool(payload.add_basemap),
            add_roads=bool(payload.add_roads),
            language=str(payload.language or "zh"),
        ),
    )

    return FileResponse(
        path=file_path,
        media_type=MEDIA_TYPES[export_format],
        filename=output_path.name,
    )
