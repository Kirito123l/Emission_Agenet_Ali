"""Static map export endpoints."""

from __future__ import annotations

from datetime import datetime
import re
from pathlib import Path
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


def _safe_label(value: Optional[str], fallback: str) -> str:
    label = (value or fallback).strip() or fallback
    sanitized = re.sub(r"[^0-9A-Za-z_\-]+", "_", label)
    return sanitized.strip("_") or fallback


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
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    scenario_fragment = _safe_label(payload.scenario_label, "baseline")
    filename = f"{result_type}_{scenario_fragment}_{timestamp}.{export_format}"
    output_path = export_dir / filename

    if result_type == "dispersion":
        file_path = exporter.export_dispersion_map(
            stored.data,
            output_path=output_path,
            format=export_format,
            dpi=int(payload.dpi or config.map_export_dpi),
            add_basemap=bool(payload.add_basemap),
            add_roads=bool(payload.add_roads),
            language=str(payload.language or "zh"),
        )
    elif result_type == "hotspot":
        file_path = exporter.export_hotspot_map(
            stored.data,
            output_path=output_path,
            format=export_format,
            dpi=int(payload.dpi or config.map_export_dpi),
            add_basemap=bool(payload.add_basemap),
            add_roads=bool(payload.add_roads),
            language=str(payload.language or "zh"),
        )
    elif result_type == "emission":
        file_path = exporter.export_emission_map(
            stored.data,
            output_path=output_path,
            format=export_format,
            dpi=int(payload.dpi or config.map_export_dpi),
            add_basemap=bool(payload.add_basemap),
            add_roads=False,
            language=str(payload.language or "zh"),
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported result_type: {result_type}")

    return FileResponse(
        path=file_path,
        media_type=MEDIA_TYPES[export_format],
        filename=filename,
    )
