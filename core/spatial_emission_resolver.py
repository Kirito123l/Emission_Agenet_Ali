"""Deterministic spatial emission resolver.

Phase 7.4A: resolve_spatial_emission_candidate — resolve road geometry from
    file analysis metadata.
Phase 7.5: build_spatial_emission_layer — build layer from direct geometry.
Phase 7.6B: resolve_join_key_geometry_layer — resolve join-key-only emission
    against a user-supplied geometry file via exact key matching.

Every decision is backed by deterministic evidence and does not invoke the LLM.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.spatial_emission import (
    SpatialEmissionCandidate,
    SpatialEmissionGeometry,
    SpatialEmissionLayer,
    JoinGeometryResolutionResult,
    JOIN_RESOLUTION_ACCEPT,
    JOIN_RESOLUTION_NEEDS_USER_CONFIRMATION,
    JOIN_RESOLUTION_REJECT,
    JOIN_RESOLUTION_INSUFFICIENT_INPUT,
)

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


# ── Phase 7.6B: join-key geometry resolver ──────────────────────────────

# Join key tokens used for column-name detection (mirrors file_analyzer).
_JOIN_KEY_NORMALIZED: Tuple[str, ...] = (
    "link_id", "road_id", "segment_id", "edge_id", "link", "road", "segment",
    "link_name", "linkname",
)
# Chinese join key column names.
_JOIN_KEY_CHINESE: Tuple[str, ...] = (
    "路段编号", "道路编号", "路段id", "路段ID",
)


def _norm_col(name: str) -> str:
    """Normalize a column name for cross-file matching."""
    return name.strip().lower().replace("-", "_").replace(" ", "_")


def _norm_key(value: Any) -> str:
    """Normalize a single key value for comparison.

    - Trims whitespace.
    - Floats with zero fractional part are coerced to int string.
    - Returns string representation.
    """
    if value is None:
        return ""
    if isinstance(value, float):
        if value == value and value == int(value):
            return str(int(value))
        return str(value)
    if isinstance(value, int):
        return str(value)
    return str(value).strip()


def _is_likely_join_key_col(col_name: str) -> bool:
    """Check whether a column name is a recognized join key token."""
    n = _norm_col(col_name)
    for tok in _JOIN_KEY_NORMALIZED:
        if tok in n or n in tok:
            return True
    for tok in _JOIN_KEY_CHINESE:
        if tok in col_name or tok in n:
            return True
    return False


def _find_compatible_join_keys(
    emission_cols: List[str],
    geometry_cols: List[str],
    join_key_mapping: Optional[Dict[str, str]],
) -> Optional[Tuple[str, str]]:
    """Find a compatible (emission_col, geometry_col) join key pair.

    Priority: explicit mapping > exact normalized name match > any join-key-
    -looking column pair.
    """
    # Explicit mapping
    if join_key_mapping:
        for em_col, geo_col in join_key_mapping.items():
            if em_col in emission_cols and geo_col in geometry_cols:
                return (em_col, geo_col)

    em_norm = {_norm_col(c): c for c in emission_cols}
    geo_norm = {_norm_col(c): c for c in geometry_cols}

    # Exact normalized name match
    for nk in sorted(em_norm):
        if nk in geo_norm and _is_likely_join_key_col(nk):
            return (em_norm[nk], geo_norm[nk])

    # Fallback: any join-key-looking column pair
    em_jk = [c for c in emission_cols if _is_likely_join_key_col(c)]
    geo_jk = [c for c in geometry_cols if _is_likely_join_key_col(c)]
    if em_jk and geo_jk:
        # Prefer exact normalized match even if not recognized token
        for e_nk, e_c in em_norm.items():
            if e_nk in geo_norm:
                return (e_c, geo_norm[e_nk])
        # Last resort: first join-key cols from each side
        return (em_jk[0], geo_jk[0])

    return None


def _load_keys_from_file(file_path: str, key_col: str) -> Optional[List[str]]:
    """Load key values from a file, returning a list of normalized key strings."""
    import pandas as _pd
    fp = Path(file_path)
    if not fp.exists():
        return None
    try:
        if fp.suffix in (".xlsx", ".xls"):
            df = _pd.read_excel(str(fp))
        elif fp.suffix == ".csv":
            df = _pd.read_csv(str(fp))
        elif fp.suffix == ".shp":
            import geopandas as _gpd
            gdf = _gpd.read_file(str(fp))
            return [_norm_key(v) for v in gdf[key_col].tolist()]
        else:
            return None
        if key_col not in df.columns:
            return None
        return [_norm_key(v) for v in df[key_col].tolist()]
    except Exception:
        return None


def _check_geometry_column_has_values(
    file_path: str, geometry_col: str,
) -> Tuple[bool, List[str]]:
    """Verify a geometry column has at least some recognizable geometry values.

    Returns (has_valid_geom, evidence_messages).
    """
    import pandas as _pd
    fp = Path(file_path)
    try:
        if fp.suffix in (".xlsx", ".xls"):
            df = _pd.read_excel(str(fp))
        elif fp.suffix == ".csv":
            df = _pd.read_csv(str(fp))
        elif fp.suffix == ".shp":
            # shapefiles carry geometry implicitly — already validated by geopandas read
            return True, ["Shapefile geometry column validated via geopandas read"]
        else:
            return False, [f"Unsupported geometry file type: {fp.suffix}"]
    except Exception:
        return False, [f"Could not read geometry file: {file_path}"]

    if geometry_col not in df.columns:
        return False, [f"Column '{geometry_col}' not found in geometry file"]

    samples = df[geometry_col].dropna().head(3).tolist()
    if not samples:
        return False, [f"No non-null values in geometry column '{geometry_col}'"]

    # Check for WKT content
    wkt_hits = 0
    for v in samples:
        s = str(v).strip().upper()
        if s.startswith(("LINESTRING", "POINT", "POLYGON", "MULTILINESTRING",
                          "MULTIPOINT", "MULTIPOLYGON", "GEOMETRYCOLLECTION")):
            wkt_hits += 1

    if wkt_hits > 0:
        return True, [f"{wkt_hits}/{len(samples)} sample(s) contain WKT geometry"]
    elif any("{" in str(v) and "type" in str(v) for v in samples):
        return True, ["GeoJSON-like geometry values found in samples"]
    else:
        return False, [
            f"No recognizable WKT/GeoJSON in geometry column '{geometry_col}' samples: "
            f"{[str(v)[:60] for v in samples]}"
        ]


def _resolve_duplicate_geometry_keys(
    file_path: str, key_col: str, geometry_col: str,
) -> Optional[Tuple[List[str], List[str]]]:
    """Check for duplicate geometry keys with conflicting geometry.

    Returns None if ambiguous (different geometry for same key), or
    (evidence, limitations) if safe (no duplicates or identical geometry).
    """
    import pandas as _pd
    fp = Path(file_path)
    try:
        if fp.suffix in (".xlsx", ".xls"):
            df = _pd.read_excel(str(fp))
        elif fp.suffix == ".csv":
            df = _pd.read_csv(str(fp))
        elif fp.suffix == ".shp":
            return (
                ["Shapefile rows treated as unique — no duplicate key check needed"],
                [],
            )
        else:
            return None
    except Exception:
        return None

    key_vals = df[key_col].tolist()
    geom_vals = df[geometry_col].tolist()
    key_counts: Dict[str, int] = {}
    key_geoms: Dict[str, str] = {}
    duplicate_keys: List[str] = []

    for k, g in zip(key_vals, geom_vals):
        nk = _norm_key(k)
        gs = str(g).strip() if g is not None else ""
        if nk in key_counts:
            key_counts[nk] += 1
            if key_geoms.get(nk, gs) != gs:
                duplicate_keys.append(nk)
        else:
            key_counts[nk] = 1
            key_geoms[nk] = gs

    if duplicate_keys:
        evidence = [f"Duplicate keys with conflicting geometry: {duplicate_keys[:5]}"]
        limitations = [
            f"Ambiguous duplicate keys ({len(duplicate_keys)} keys have conflicting geometry)"
        ]
        return None  # ambiguous

    dup_count = sum(1 for c in key_counts.values() if c > 1)
    if dup_count > 0:
        return (
            [f"{dup_count} duplicate geometry keys with identical geometry — safe to deduplicate"],
            [f"{dup_count} duplicate geometry keys deduplicated"],
        )
    return ([], [])


def resolve_join_key_geometry_layer(
    emission_file_context: Dict[str, Any],
    geometry_file_context: Dict[str, Any],
    emission_result_ref: Optional[str] = None,
    emission_output_path: Optional[str] = None,
    join_key_mapping: Optional[Dict[str, str]] = None,
    auto_accept_threshold: float = 0.95,
    confirmation_threshold: float = 0.80,
) -> JoinGeometryResolutionResult:
    """Deterministically resolve a join-key geometry layer between two files.

    Args:
        emission_file_context: FileContext dict for the emission file. Must have
            ``geometry_metadata`` with ``geometry_type == "join_key_only"`` or
            at least ``join_key_columns`` present.
        geometry_file_context: FileContext dict for the geometry file. Must have
            ``geometry_metadata`` with ``road_geometry_available == True``.
        emission_result_ref: Optional reference key for the upstream emission
            result (e.g. ``"macro_emission:baseline"``).
        emission_output_path: Optional output path.
        join_key_mapping: Optional explicit mapping from emission column names
            to geometry file column names (e.g. ``{"LinkName": "link_id"}``).
        auto_accept_threshold: Match rate above which resolution is auto-accepted.
        confirmation_threshold: Match rate below which resolution is rejected.

    Returns:
        JoinGeometryResolutionResult with status, match statistics, and an
        optional spatial_emission_layer when the join is accepted.
    """
    from core.spatial_emission import SpatialEmissionLayer

    def _result(
        status: str,
        reason_code: str,
        message: str,
        match_rate: float = 0.0,
        matched_count: int = 0,
        unmatched_emission_count: int = 0,
        duplicate_geometry_key_count: int = 0,
        join_key_mapping_dict: Optional[Dict[str, str]] = None,
        emission_key_col: Optional[str] = None,
        geometry_key_col: Optional[str] = None,
        evidence: Optional[List[str]] = None,
        limitations: Optional[List[str]] = None,
        spatial_emission_layer: Optional[Dict[str, Any]] = None,
    ) -> JoinGeometryResolutionResult:
        return JoinGeometryResolutionResult(
            status=status,
            reason_code=reason_code,
            message=message,
            match_rate=match_rate,
            matched_count=matched_count,
            unmatched_emission_count=unmatched_emission_count,
            duplicate_geometry_key_count=duplicate_geometry_key_count,
            join_key_mapping=dict(join_key_mapping_dict or {}),
            emission_key_column=emission_key_col,
            geometry_key_column=geometry_key_col,
            evidence=list(evidence or []),
            limitations=list(limitations or []),
            spatial_emission_layer=spatial_emission_layer,
        )

    # ── 1. Validate emission file context ──────────────────────────────
    em_fc = dict(emission_file_context or {})
    em_gm = dict(em_fc.get("geometry_metadata") or {})
    em_geom_type = str(em_gm.get("geometry_type", "none")).strip().lower()
    em_jk_cols = dict(em_gm.get("join_key_columns") or {})
    em_path = str(em_fc.get("file_path") or em_fc.get("path") or "").strip()

    # If emission file has direct geometry, delegate to direct path
    _DIRECT_TYPES = {"wkt", "geojson", "lonlat_linestring", "spatial_metadata"}
    if em_geom_type in _DIRECT_TYPES and em_gm.get("road_geometry_available"):
        return _result(
            JOIN_RESOLUTION_INSUFFICIENT_INPUT,
            "direct_geometry_present",
            "Emission file already contains direct road geometry. "
            "Use build_spatial_emission_layer() for direct geometry path.",
            evidence=["Direct geometry detected — join-key resolution not needed"],
        )

    if not em_path:
        return _result(
            JOIN_RESOLUTION_INSUFFICIENT_INPUT,
            "missing_emission_file_path",
            "Emission file context has no file_path.",
        )

    if not em_jk_cols:
        return _result(
            JOIN_RESOLUTION_INSUFFICIENT_INPUT,
            "no_join_keys_in_emission",
            "Emission file has no detected join key columns (link_id, road_id, "
            "segment_id, etc.). Cannot perform join-key resolution.",
        )

    # ── 2. Validate geometry file context ──────────────────────────────
    geo_fc = dict(geometry_file_context or {})
    geo_gm = dict(geo_fc.get("geometry_metadata") or {})
    geo_path = str(geo_fc.get("file_path") or geo_fc.get("path") or "").strip()

    if not geo_path:
        return _result(
            JOIN_RESOLUTION_INSUFFICIENT_INPUT,
            "missing_geometry_file_path",
            "Geometry file context has no file_path.",
        )

    if not geo_gm.get("road_geometry_available"):
        geo_type = str(geo_gm.get("geometry_type", "none"))
        if geo_type in ("lonlat_point", "spatial_metadata_point"):
            return _result(
                JOIN_RESOLUTION_REJECT,
                "point_geometry_not_road_geometry",
                "Geometry file contains only point coordinates — not road-segment "
                "line geometry. Dispersion requires line or polygon geometry.",
            )
        return _result(
            JOIN_RESOLUTION_REJECT,
            "geometry_file_no_road_geometry",
            "Geometry file does not have usable road geometry.",
        )

    geo_geom_cols = [str(c) for c in (geo_gm.get("geometry_columns") or [])]
    if not geo_geom_cols:
        return _result(
            JOIN_RESOLUTION_INSUFFICIENT_INPUT,
            "no_geometry_columns_in_geometry_file",
            "Geometry file has no detected geometry columns.",
        )

    # ── 3. Resolve join key column mapping ─────────────────────────────
    em_cols = list(em_fc.get("columns") or [])
    geo_cols = list(geo_fc.get("columns") or [])

    # If columns not in file_context, try loading headers from files
    if not em_cols:
        try:
            import pandas as _pd
            fp = Path(em_path)
            df = (_pd.read_excel(str(fp)) if fp.suffix in (".xlsx", ".xls")
                  else _pd.read_csv(str(fp)))
            em_cols = list(df.columns)
        except Exception:
            return _result(
                JOIN_RESOLUTION_INSUFFICIENT_INPUT,
                "cannot_read_emission_file_columns",
                f"Could not read columns from emission file: {em_path}",
            )

    if not geo_cols:
        try:
            import pandas as _pd
            fp = Path(geo_path)
            if fp.suffix == ".shp":
                import geopandas as _gpd
                gdf = _gpd.read_file(str(fp))
                geo_cols = list(gdf.columns)
            else:
                df = (_pd.read_excel(str(fp)) if fp.suffix in (".xlsx", ".xls")
                      else _pd.read_csv(str(fp)))
                geo_cols = list(df.columns)
        except Exception:
            return _result(
                JOIN_RESOLUTION_INSUFFICIENT_INPUT,
                "cannot_read_geometry_file_columns",
                f"Could not read columns from geometry file: {geo_path}",
            )

    key_pair = _find_compatible_join_keys(em_cols, geo_cols, join_key_mapping)
    if key_pair is None:
        return _result(
            JOIN_RESOLUTION_REJECT,
            "no_compatible_join_keys",
            f"No compatible join key columns between emission file "
            f"(columns: {em_cols[:8]}) and geometry file (columns: {geo_cols[:8]}). "
            f"Provide an explicit join_key_mapping if column names differ.",
            evidence=[f"Emission columns: {em_cols}", f"Geometry columns: {geo_cols}"],
        )

    em_key_col, geo_key_col = key_pair
    actual_mapping = {em_key_col: geo_key_col}

    # ── 4. Load and normalize keys ─────────────────────────────────────
    em_keys_raw = _load_keys_from_file(em_path, em_key_col)
    geo_keys_raw = _load_keys_from_file(geo_path, geo_key_col)

    if em_keys_raw is None:
        return _result(
            JOIN_RESOLUTION_INSUFFICIENT_INPUT,
            "cannot_read_emission_keys",
            f"Could not read key column '{em_key_col}' from emission file: {em_path}",
        )
    if geo_keys_raw is None:
        return _result(
            JOIN_RESOLUTION_INSUFFICIENT_INPUT,
            "cannot_read_geometry_keys",
            f"Could not read key column '{geo_key_col}' from geometry file: {geo_path}",
        )

    # Auto-detect join_key_mapping from emission gm if column names differ
    # but the actual key values match well
    if em_key_col != geo_key_col and not join_key_mapping:
        actual_mapping = {em_key_col: geo_key_col}

    # Build normalized key sets
    em_keys_set: Dict[str, List[int]] = {}  # normalized key -> [row indices]
    for i, k in enumerate(em_keys_raw):
        nk = _norm_key(k)
        if nk:
            em_keys_set.setdefault(nk, []).append(i)

    geo_key_to_geom_idx: Dict[str, int] = {}
    geo_duplicate_keys: Dict[str, List[int]] = {}
    for i, k in enumerate(geo_keys_raw):
        nk = _norm_key(k)
        if nk:
            if nk in geo_key_to_geom_idx:
                geo_duplicate_keys.setdefault(nk, []).append(i)
            else:
                geo_key_to_geom_idx[nk] = i

    em_norm_keys = set(em_keys_set.keys())
    geo_norm_keys = set(geo_key_to_geom_idx.keys())
    matched_keys = em_norm_keys & geo_norm_keys
    unmatched_em = em_norm_keys - geo_norm_keys

    match_rate = len(matched_keys) / max(len(em_norm_keys), 1)
    matched_count = len(matched_keys)
    unmatched_emission_count = len(unmatched_em)

    # ── 5. Check for conflicting duplicate geometry keys ────────────────
    # Only trigger when we have duplicate geo keys AND we can check geometry
    dup_conflict = False
    dup_evidence: List[str] = []
    dup_limitations: List[str] = []
    for dk in geo_duplicate_keys:
        if dk in matched_keys:
            # Check if geometry values differ for the duplicated key
            try:
                geo_col = geo_geom_cols[0] if geo_geom_cols else "geometry"
                import pandas as _pd
                fp = Path(geo_path)
                if fp.suffix in (".xlsx", ".xls"):
                    df = _pd.read_excel(str(fp))
                elif fp.suffix == ".csv":
                    df = _pd.read_csv(str(fp))
                else:
                    continue
                # Include first occurrence index from geo_key_to_geom_idx
                all_indices = [geo_key_to_geom_idx[dk]] + geo_duplicate_keys[dk]
                geom_vals = [str(df.iloc[idx][geo_col]).strip() for idx in all_indices]
                if len(set(geom_vals)) > 1:
                    dup_conflict = True
                    dup_limitations.append(
                        f"Duplicate key '{dk}' has {len(all_indices)} conflicting geometry values"
                    )
                else:
                    dup_evidence.append(
                        f"Duplicate key '{dk}' ({len(all_indices)} rows) has identical geometry — deduplicated"
                    )
            except Exception:
                pass

    if dup_conflict:
        return _result(
            JOIN_RESOLUTION_REJECT,
            "ambiguous_duplicate_geometry_keys",
            f"Geometry file contains duplicate keys ({len(geo_duplicate_keys)} keys) "
            f"with conflicting geometry values. Please deduplicate the geometry file.",
            match_rate=match_rate,
            matched_count=matched_count,
            unmatched_emission_count=unmatched_emission_count,
            duplicate_geometry_key_count=len(geo_duplicate_keys),
            join_key_mapping_dict=actual_mapping,
            emission_key_col=em_key_col,
            geometry_key_col=geo_key_col,
            evidence=dup_evidence,
            limitations=dup_limitations,
        )

    # ── 6. Apply thresholds ────────────────────────────────────────────
    evidence_msgs: List[str] = [
        f"Emission file: {em_path} ({len(em_norm_keys)} unique keys)",
        f"Geometry file: {geo_path} ({len(geo_norm_keys)} unique keys)",
        f"Join key: {em_key_col} ↔ {geo_key_col}",
        f"Matched: {matched_count}/{len(em_norm_keys)} ({match_rate:.1%})",
    ]
    evidence_msgs.extend(dup_evidence)

    limit_msgs: List[str] = list(dup_limitations)
    if unmatched_em:
        sample_unmatched = sorted(list(unmatched_em))[:5]
        limit_msgs.append(
            f"{unmatched_emission_count} unmatched emission keys "
            f"(e.g. {sample_unmatched})"
        )

    if match_rate == 0:
        em_samples = sorted(list(em_norm_keys))[:5]
        geo_samples = sorted(list(geo_norm_keys))[:5]
        return _result(
            JOIN_RESOLUTION_REJECT,
            "zero_key_overlap",
            f"No matching keys between emission file ({len(em_norm_keys)} keys, "
            f"e.g. {em_samples}) and geometry file ({len(geo_norm_keys)} keys, "
            f"e.g. {geo_samples}). Verify this is the correct geometry file.",
            match_rate=0.0,
            matched_count=0,
            unmatched_emission_count=len(em_norm_keys),
            duplicate_geometry_key_count=len(geo_duplicate_keys),
            join_key_mapping_dict=actual_mapping,
            emission_key_col=em_key_col,
            geometry_key_col=geo_key_col,
            evidence=evidence_msgs,
            limitations=limit_msgs,
        )

    if match_rate >= auto_accept_threshold:
        status = JOIN_RESOLUTION_ACCEPT
        reason_code = "join_key_resolved"
        message = (
            f"Join-key geometry resolved: {matched_count}/{len(em_norm_keys)} "
            f"emission keys matched ({match_rate:.1%})."
        )
    elif match_rate >= confirmation_threshold:
        status = JOIN_RESOLUTION_NEEDS_USER_CONFIRMATION
        reason_code = "partial_key_overlap"
        message = (
            f"Partial key match: {matched_count}/{len(em_norm_keys)} emission keys "
            f"matched ({match_rate:.1%}). {unmatched_emission_count} keys have no "
            f"geometry. User should confirm this is the correct geometry file."
        )
    else:
        status = JOIN_RESOLUTION_REJECT
        reason_code = "low_key_overlap"
        message = (
            f"Low key match: only {matched_count}/{len(em_norm_keys)} emission keys "
            f"matched ({match_rate:.1%}). This is likely the wrong geometry file."
        )

    # ── 7. Build SpatialEmissionLayer (for ACCEPT and NEEDS_USER_CONFIRMATION) ─
    spatial_layer_dict: Optional[Dict[str, Any]] = None

    if status in (JOIN_RESOLUTION_ACCEPT, JOIN_RESOLUTION_NEEDS_USER_CONFIRMATION):
        # Build layer
        geo_geom_type = str(geo_gm.get("geometry_type", "wkt")).strip().lower()
        geo_geom_col = geo_geom_cols[0] if len(geo_geom_cols) == 1 else (
            geo_geom_cols[0] if geo_geom_cols else None
        )
        em_row_count = em_fc.get("row_count") or len(em_keys_raw)

        layer = SpatialEmissionLayer(
            layer_available=True,
            spatial_product_type="spatial_emission_layer",
            source_file_path=geo_path,  # geometry file is the source for dispersion loader
            emission_result_ref=emission_result_ref,
            emission_output_path=emission_output_path,
            geometry_type=geo_geom_type,
            geometry_column=geo_geom_col,
            geometry_columns=list(geo_geom_cols),
            coordinate_columns={
                str(k): (str(v) if v is not None else None)
                for k, v in (geo_gm.get("coordinate_columns") or {}).items()
            },
            join_key_columns={em_key_col: geo_key_col},
            row_count=em_row_count,
            confidence=round(min(match_rate, 1.0), 3),
            evidence=evidence_msgs,
            limitations=limit_msgs,
            provenance={
                "builder_version": "7.6B",
                "resolver_version": "7.6B",
                "join_method": "deterministic_key_match",
                "emission_file": em_path,
                "geometry_file": geo_path,
                "key_mapping": actual_mapping,
                "match_rate": round(match_rate, 4),
                "matched_count": matched_count,
                "unmatched_emission_count": unmatched_emission_count,
                "unmatched_keys_sample": sorted(list(unmatched_em))[:10],
            },
        )
        spatial_layer_dict = layer.to_dict()

    return _result(
        status=status,
        reason_code=reason_code,
        message=message,
        match_rate=round(match_rate, 4),
        matched_count=matched_count,
        unmatched_emission_count=unmatched_emission_count,
        duplicate_geometry_key_count=len(geo_duplicate_keys),
        join_key_mapping_dict=actual_mapping,
        emission_key_col=em_key_col,
        geometry_key_col=geo_key_col,
        evidence=evidence_msgs,
        limitations=limit_msgs,
        spatial_emission_layer=spatial_layer_dict,
    )


# ── Phase 7.6E: auto-discover geometry file from stored contexts ────────


def find_best_geometry_file_context(
    emission_file_context: Dict[str, Any],
    candidate_geometry_contexts: List[Dict[str, Any]],
    auto_accept_threshold: float = 0.95,
) -> Dict[str, Any]:
    """Find the best matching geometry FileContext from stored candidates.

    Evaluates each candidate via resolve_join_key_geometry_layer() and returns
    the best result. Only ACCEPT-status candidates are considered for auto-selection.
    NEEDS_USER_CONFIRMATION candidates are reported but not selected.

    Args:
        emission_file_context: FileContext dict for the join-key-only emission file.
        candidate_geometry_contexts: List of stored FileContext dicts with
            road_geometry_available=true (from context_store).
        auto_accept_threshold: Match rate above which resolution is auto-accepted.

    Returns:
        Dict with keys:
        - selected: bool — whether a single best geometry context was auto-selected.
        - geometry_file_context: the selected FileContext dict (or None).
        - spatial_emission_layer: the resolved layer dict (or None).
        - reason_code: diagnostic code.
        - message: human-readable diagnostic.
        - candidates: list of dicts with {file_path, status, match_rate, matched_count}
          for all evaluated candidates (for user clarification when needed).
    """
    _EMPTY: Dict[str, Any] = {
        "selected": False,
        "geometry_file_context": None,
        "spatial_emission_layer": None,
        "reason_code": "no_geometry_candidates",
        "message": "No geometry file contexts available.",
        "candidates": [],
    }

    if not candidate_geometry_contexts:
        return _EMPTY

    from core.spatial_emission import JOIN_RESOLUTION_ACCEPT, JOIN_RESOLUTION_NEEDS_USER_CONFIRMATION

    evaluated = []
    for geo_fc in candidate_geometry_contexts:
        try:
            jk_result = resolve_join_key_geometry_layer(
                emission_file_context=emission_file_context,
                geometry_file_context=geo_fc,
                auto_accept_threshold=auto_accept_threshold,
            )
            evaluated.append({
                "geometry_file_context": geo_fc,
                "file_path": geo_fc.get("file_path", "unknown"),
                "status": jk_result.status,
                "reason_code": jk_result.reason_code,
                "match_rate": jk_result.match_rate,
                "matched_count": jk_result.matched_count,
                "unmatched_emission_count": jk_result.unmatched_emission_count,
                "message": jk_result.message,
                "spatial_emission_layer": jk_result.spatial_emission_layer,
            })
        except Exception:
            continue

    if not evaluated:
        return {
            **_EMPTY,
            "reason_code": "geometry_candidate_evaluation_failed",
            "message": "Could not evaluate any geometry file candidates.",
        }

    accept_candidates = [
        c for c in evaluated if c["status"] == JOIN_RESOLUTION_ACCEPT
    ]
    confirm_candidates = [
        c for c in evaluated if c["status"] == JOIN_RESOLUTION_NEEDS_USER_CONFIRMATION
    ]

    # Build candidate summary for diagnostics
    candidate_summaries = [
        {
            "file_path": c["file_path"],
            "status": c["status"],
            "match_rate": c["match_rate"],
            "matched_count": c["matched_count"],
        }
        for c in evaluated
    ]

    if accept_candidates:
        if len(accept_candidates) == 1:
            best = accept_candidates[0]
            return {
                "selected": True,
                "geometry_file_context": best["geometry_file_context"],
                "spatial_emission_layer": best["spatial_emission_layer"],
                "reason_code": "join_key_geometry_resolved",
                "message": (
                    f"Auto-selected geometry file: {best['file_path']} "
                    f"({best['match_rate']:.1%} match, {best['matched_count']} keys)"
                ),
                "candidates": candidate_summaries,
            }

        # Multiple ACCEPT candidates: select highest match_rate if strictly dominant
        best = max(accept_candidates, key=lambda c: c["match_rate"])
        ties = [
            c for c in accept_candidates
            if abs(c["match_rate"] - best["match_rate"]) < 0.001
        ]
        if len(ties) == 1:
            return {
                "selected": True,
                "geometry_file_context": best["geometry_file_context"],
                "spatial_emission_layer": best["spatial_emission_layer"],
                "reason_code": "join_key_geometry_resolved",
                "message": (
                    f"Auto-selected geometry file: {best['file_path']} "
                    f"({best['match_rate']:.1%} match, {best['matched_count']} keys)"
                ),
                "candidates": candidate_summaries,
            }

        # Tied ACCEPT candidates: need user confirmation
        tie_paths = [c["file_path"] for c in ties]
        return {
            "selected": False,
            "geometry_file_context": None,
            "spatial_emission_layer": None,
            "reason_code": "multiple_geometry_candidates_tied",
            "message": (
                f"Multiple geometry files match at {best['match_rate']:.1%}: "
                f"{tie_paths}. Please select one."
            ),
            "candidates": candidate_summaries,
        }

    if confirm_candidates:
        # Best partial-match candidate — needs user confirmation
        best = max(confirm_candidates, key=lambda c: c["match_rate"])
        return {
            "selected": False,
            "geometry_file_context": None,
            "spatial_emission_layer": None,
            "reason_code": "join_key_geometry_needs_confirmation",
            "message": (
                f"Best geometry file candidate: {best['file_path']} "
                f"({best['match_rate']:.1%} match, {best['matched_count']} keys). "
                f"Match is below the auto-accept threshold. User confirmation required."
            ),
            "candidates": candidate_summaries,
        }

    # All REJECT — return diagnostic for best rejection reason
    if evaluated:
        first = evaluated[0]
        return {
            "selected": False,
            "geometry_file_context": None,
            "spatial_emission_layer": None,
            "reason_code": first["reason_code"],
            "message": first["message"],
            "candidates": candidate_summaries,
        }

    return _EMPTY
