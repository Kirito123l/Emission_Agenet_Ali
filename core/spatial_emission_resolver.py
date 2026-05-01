"""Deterministic spatial emission resolver — Phase 7.4A foundation.

Resolves whether a file's geometry metadata can serve as road-segment geometry
for dispersion analysis.  Every decision is backed by the evidence already
captured in GeometryMetadata (Phase 7.2) and does not invoke the LLM.

Non-goals (7.4A):
- Does NOT read external files or perform spatial joins.
- Does NOT construct actual geometry objects (WKT strings, GeoDataFrames).
- Does NOT modify calculate_macro_emission or calculate_dispersion execution.
- Does NOT claim Task 120 full PASS.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.spatial_emission import SpatialEmissionCandidate, SpatialEmissionGeometry, SpatialEmissionLayer

# Geometry types that unambiguously carry road-segment geometry.
_ACCEPTABLE_TYPES = {"wkt", "geojson", "lonlat_linestring", "spatial_metadata"}

# Geometry types that are present but not usable as line/polygon road geometry.
_POINT_ONLY_TYPES = {"lonlat_point"}

_JOIN_KEY_ONLY_TYPE = "join_key_only"


def resolve_spatial_emission_candidate(
    file_context: Optional[Dict[str, Any]] = None,
    emission_result: Optional[Dict[str, Any]] = None,
    emission_result_ref: Optional[str] = None,
) -> SpatialEmissionCandidate:
    """Deterministically resolve road geometry from file analysis metadata.

    Args:
        file_context: FileContext serialised dict (or compatible mapping).
            Must contain ``geometry_metadata`` (Phase 7.2 output).
        emission_result: Reserved for future per-result geometry enrichment.
            Not consumed in Phase 7.4A.
        emission_result_ref: Optional reference key for the upstream emission
            result (e.g. ``"macro_emission:baseline"``).

    Returns:
        SpatialEmissionCandidate with ``available``, ``reason_code``, and
        bounded geometry provenance.
    """
    fc = dict(file_context or {})
    gm = dict(fc.get("geometry_metadata") or {})

    geometry_type = str(gm.get("geometry_type", "none")).strip().lower()
    road_available = bool(gm.get("road_geometry_available", False))
    point_available = bool(gm.get("point_geometry_available", False))
    line_constructible = bool(gm.get("line_geometry_constructible", False))
    join_keys = dict(gm.get("join_key_columns") or {})
    confidence = float(gm.get("confidence", 0.0))
    evidence = [str(e) for e in (gm.get("evidence") or [])]
    limitations = [str(li) for li in (gm.get("limitations") or [])]

    source_file_path = str(fc.get("file_path") or fc.get("path") or "").strip() or None
    row_count_raw = fc.get("row_count")
    row_count: Optional[int] = int(row_count_raw) if row_count_raw is not None else None

    geometry = SpatialEmissionGeometry.from_geometry_metadata(
        gm,
        geometry_source="file_context.geometry_metadata",
    )

    def _candidate(
        available: bool,
        reason_code: str,
        message: str,
    ) -> SpatialEmissionCandidate:
        return SpatialEmissionCandidate(
            available=available,
            reason_code=reason_code,
            message=message,
            source_file_path=source_file_path,
            emission_result_ref=emission_result_ref,
            geometry=geometry,
            join_keys=sorted(join_keys.keys()),
            row_count=row_count,
            provenance={
                "resolver_version": "7.4A",
                "geometry_metadata_confidence": confidence,
                "geometry_metadata_evidence": evidence,
                "geometry_metadata_limitations": limitations,
            },
        )

    # ── Road geometry available ──────────────────────────────────────
    if geometry_type in _ACCEPTABLE_TYPES and road_available:
        msg_parts: List[str] = [f"Road geometry available (type={geometry_type})."]
        if line_constructible:
            msg_parts.append("LineString geometry is deterministically constructible from start/end coordinates.")
        return _candidate(True, "spatial_emission_available", " ".join(msg_parts))

    # ── Point-only geometry — not road ───────────────────────────────
    if geometry_type in _POINT_ONLY_TYPES and point_available:
        return _candidate(
            False,
            "point_geometry_not_road_geometry",
            (
                "Only point coordinates (lon/lat) found in the uploaded file. "
                "Road-segment dispersion requires line or polygon geometry "
                "(WKT, GeoJSON, start-end coordinates, or shapefile). "
                "Please provide a file with road-segment geometry."
            ),
        )

    # ── Join keys only — no geometry at all ──────────────────────────
    if geometry_type == _JOIN_KEY_ONLY_TYPE:
        jk_names = sorted(join_keys.keys()) if join_keys else []
        jk_phrase = ", ".join(jk_names) if jk_names else "unknown"
        return _candidate(
            False,
            "join_key_without_geometry",
            (
                f"Join key columns found ({jk_phrase}) but no road geometry "
                "columns exist in the file.  Please provide a separate geometry "
                "file (shapefile/GeoJSON) or add WKT/start-end coordinate "
                "columns to enable road-segment dispersion."
            ),
        )

    # ── Accepted type but road_geometry_available is false (edge case)
    if geometry_type in _ACCEPTABLE_TYPES and not road_available:
        return _candidate(
            False,
            "road_geometry_unavailable",
            (
                f"Geometry type '{geometry_type}' matched an acceptable category "
                "but road_geometry_available=false in metadata.  "
                "Check whether geometry values are actually usable line/polygon "
                "geometries."
            ),
        )

    # ── No geometry at all ───────────────────────────────────────────
    return _candidate(
        False,
        "missing_road_geometry",
        (
            "No road geometry detected in the uploaded file. "
            "Dispersion requires road-segment line geometry. "
            "Please upload a file with WKT, GeoJSON, start-end coordinates, "
            "or a shapefile."
        ),
    )


# ── Phase 7.5: spatial emission layer builder ──────────────────────────

def build_spatial_emission_layer(
    file_context: Optional[Dict[str, Any]] = None,
    emission_result_ref: Optional[str] = None,
    emission_output_path: Optional[str] = None,
    macro_result: Optional[Dict[str, Any]] = None,
) -> SpatialEmissionLayer:
    """Build a spatial emission layer from FileContext geometry metadata.

    Only succeeds when the file has direct road geometry (WKT, GeoJSON,
    lonlat_linestring, or spatial_metadata).  Rejects point-only, join-key-only,
    and no-geometry files.

    Args:
        file_context: FileContext serialised dict (must contain geometry_metadata).
        emission_result_ref: Reference key for the upstream emission result
            (e.g. ``"macro_emission:baseline"``).
        emission_output_path: Optional output path for the emission result file.
        macro_result: Reserved for future per-result enrichment. Not consumed yet.

    Returns:
        SpatialEmissionLayer with ``layer_available``, geometry provenance,
        and metadata suitable for readiness assessment.
    """
    fc = dict(file_context or {})
    gm = dict(fc.get("geometry_metadata") or {})

    geometry_type = str(gm.get("geometry_type", "none")).strip().lower()
    road_available = bool(gm.get("road_geometry_available", False))
    geometry_columns = [str(c) for c in (gm.get("geometry_columns") or [])]
    geometry_column = geometry_columns[0] if len(geometry_columns) == 1 else (
        geometry_columns[0] if geometry_columns else None
    )
    coordinate_columns = {
        str(k): (str(v) if v is not None else None)
        for k, v in (gm.get("coordinate_columns") or {}).items()
    }
    join_key_columns = {
        str(k): (str(v) if v is not None else None)
        for k, v in (gm.get("join_key_columns") or {}).items()
    }
    confidence = float(gm.get("confidence", 0.0))
    evidence = [str(e) for e in (gm.get("evidence") or [])]
    limitations = [str(li) for li in (gm.get("limitations") or [])]

    source_file_path = str(fc.get("file_path") or fc.get("path") or "").strip() or None
    row_count_raw = fc.get("row_count")
    row_count: Optional[int] = int(row_count_raw) if row_count_raw is not None else None

    _ACCEPTABLE = {"wkt", "geojson", "lonlat_linestring", "spatial_metadata"}
    _REJECTED = {"lonlat_point", "join_key_only", "none"}

    layer_available = False
    if geometry_type in _ACCEPTABLE and road_available:
        layer_available = True

    return SpatialEmissionLayer(
        layer_available=layer_available,
        spatial_product_type="spatial_emission_layer",
        source_file_path=source_file_path,
        emission_result_ref=emission_result_ref,
        emission_output_path=emission_output_path,
        geometry_type=geometry_type,
        geometry_column=geometry_column,
        geometry_columns=geometry_columns,
        coordinate_columns=coordinate_columns,
        join_key_columns=join_key_columns,
        row_count=row_count,
        confidence=confidence,
        evidence=evidence,
        limitations=limitations,
        provenance={
            "builder_version": "7.5",
            "resolver_version": "7.4A",
            "geometry_metadata_confidence": confidence,
            "geometry_metadata_evidence": evidence,
            "geometry_metadata_limitations": limitations,
        },
    )
