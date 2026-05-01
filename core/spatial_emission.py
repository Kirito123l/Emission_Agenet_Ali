"""Spatial emission data model — serializable geometry carrier for dispersion.

Lightweight dataclasses that represent the resolved spatial geometry state of
an emission result, independent of tool execution.  Used by the deterministic
spatial_emission_resolver to produce a bounded, auditable geometry candidate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SpatialEmissionGeometry:
    """Deterministic geometry-capability snapshot carried into a spatial emission.

    Mirrors the detection performed by GeometryMetadata but narrowed to the
    geometry actually available for this emission result.
    """

    geometry_type: str = "none"
    geometry_columns: List[str] = field(default_factory=list)
    coordinate_columns: Dict[str, Optional[str]] = field(default_factory=dict)
    join_key_columns: Dict[str, Optional[str]] = field(default_factory=dict)
    geometry_source: str = ""
    confidence: float = 0.0
    evidence: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "geometry_type": self.geometry_type,
            "geometry_columns": list(self.geometry_columns),
            "coordinate_columns": dict(self.coordinate_columns),
            "join_key_columns": dict(self.join_key_columns),
            "geometry_source": self.geometry_source,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_geometry_metadata(
        cls,
        geometry_metadata: Dict[str, Any],
        geometry_source: str = "file_context.geometry_metadata",
    ) -> "SpatialEmissionGeometry":
        gm = dict(geometry_metadata or {})
        return cls(
            geometry_type=str(gm.get("geometry_type", "none")),
            geometry_columns=[str(c) for c in (gm.get("geometry_columns") or [])],
            coordinate_columns={
                str(k): (str(v) if v is not None else None)
                for k, v in (gm.get("coordinate_columns") or {}).items()
            },
            join_key_columns={
                str(k): (str(v) if v is not None else None)
                for k, v in (gm.get("join_key_columns") or {}).items()
            },
            geometry_source=str(geometry_source or ""),
            confidence=float(gm.get("confidence", 0.0)),
            evidence=[str(e) for e in (gm.get("evidence") or [])],
            limitations=[str(li) for li in (gm.get("limitations") or [])],
        )


@dataclass
class SpatialEmissionLayer:
    """Serializable layer binding an emission result to its detected road geometry.

    Produced by build_spatial_emission_layer() after macro emission completes on a
    file with direct road geometry (WKT, GeoJSON, LineString, or shapefile).  Stored
    in readiness metadata so the dispersion preflight can recognize geometry availability
    without re-resolving from FileContext.
    """

    layer_available: bool = False
    spatial_product_type: str = "spatial_emission_layer"
    source_file_path: Optional[str] = None
    emission_result_ref: Optional[str] = None
    emission_output_path: Optional[str] = None
    geometry_type: str = "none"
    geometry_column: Optional[str] = None
    geometry_columns: List[str] = field(default_factory=list)
    coordinate_columns: Dict[str, Optional[str]] = field(default_factory=dict)
    join_key_columns: Dict[str, Optional[str]] = field(default_factory=dict)
    row_count: Optional[int] = None
    confidence: float = 0.0
    evidence: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer_available": self.layer_available,
            "spatial_product_type": self.spatial_product_type,
            "source_file_path": self.source_file_path,
            "emission_result_ref": self.emission_result_ref,
            "emission_output_path": self.emission_output_path,
            "geometry_type": self.geometry_type,
            "geometry_column": self.geometry_column,
            "geometry_columns": list(self.geometry_columns),
            "coordinate_columns": dict(self.coordinate_columns),
            "join_key_columns": dict(self.join_key_columns),
            "row_count": self.row_count,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "limitations": list(self.limitations),
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "SpatialEmissionLayer":
        return cls(
            layer_available=bool(payload.get("layer_available", False)),
            spatial_product_type=str(payload.get("spatial_product_type", "spatial_emission_layer")),
            source_file_path=payload.get("source_file_path"),
            emission_result_ref=payload.get("emission_result_ref"),
            emission_output_path=payload.get("emission_output_path"),
            geometry_type=str(payload.get("geometry_type", "none")),
            geometry_column=payload.get("geometry_column"),
            geometry_columns=[str(c) for c in (payload.get("geometry_columns") or [])],
            coordinate_columns={
                str(k): (str(v) if v is not None else None)
                for k, v in (payload.get("coordinate_columns") or {}).items()
            },
            join_key_columns={
                str(k): (str(v) if v is not None else None)
                for k, v in (payload.get("join_key_columns") or {}).items()
            },
            row_count=payload.get("row_count"),
            confidence=float(payload.get("confidence", 0.0)),
            evidence=[str(e) for e in (payload.get("evidence") or [])],
            limitations=[str(li) for li in (payload.get("limitations") or [])],
            provenance=dict(payload.get("provenance") or {}),
        )


@dataclass
class SpatialEmissionCandidate:
    """Deterministic result of resolving geometry for an emission result.

    Produced by resolve_spatial_emission_candidate() without touching any tool
    execution path.  Carries enough provenance to satisfy dependency validation
    and readiness checks.
    """

    available: bool = False
    reason_code: str = "missing_road_geometry"
    message: str = ""
    source_file_path: Optional[str] = None
    emission_result_ref: Optional[str] = None
    geometry: SpatialEmissionGeometry = field(default_factory=SpatialEmissionGeometry)
    join_keys: List[str] = field(default_factory=list)
    row_count: Optional[int] = None
    provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "reason_code": self.reason_code,
            "message": self.message,
            "source_file_path": self.source_file_path,
            "emission_result_ref": self.emission_result_ref,
            "geometry": self.geometry.to_dict(),
            "join_keys": list(self.join_keys),
            "row_count": self.row_count,
            "provenance": dict(self.provenance),
        }


# ── Phase 7.6: join-key geometry resolution ────────────────────────────

JOIN_RESOLUTION_ACCEPT = "ACCEPT"
JOIN_RESOLUTION_NEEDS_USER_CONFIRMATION = "NEEDS_USER_CONFIRMATION"
JOIN_RESOLUTION_REJECT = "REJECT"
JOIN_RESOLUTION_INSUFFICIENT_INPUT = "INSUFFICIENT_INPUT"


@dataclass
class JoinGeometryResolutionResult:
    """Deterministic result of join-key geometry resolution.

    Produced by resolve_join_key_geometry_layer() — never invokes the LLM.
    Carries enough provenance to decide whether the emission file's join keys
    reliably match the geometry file's keys so a valid SpatialEmissionLayer
    can be built.
    """

    status: str = JOIN_RESOLUTION_INSUFFICIENT_INPUT
    reason_code: str = "insufficient_input"
    message: str = ""
    match_rate: float = 0.0
    matched_count: int = 0
    unmatched_emission_count: int = 0
    duplicate_geometry_key_count: int = 0
    join_key_mapping: Dict[str, str] = field(default_factory=dict)
    emission_key_column: Optional[str] = None
    geometry_key_column: Optional[str] = None
    evidence: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    spatial_emission_layer: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "reason_code": self.reason_code,
            "message": self.message,
            "match_rate": self.match_rate,
            "matched_count": self.matched_count,
            "unmatched_emission_count": self.unmatched_emission_count,
            "duplicate_geometry_key_count": self.duplicate_geometry_key_count,
            "join_key_mapping": dict(self.join_key_mapping),
            "emission_key_column": self.emission_key_column,
            "geometry_key_column": self.geometry_key_column,
            "evidence": list(self.evidence),
            "limitations": list(self.limitations),
            "spatial_emission_layer": (
                dict(self.spatial_emission_layer) if self.spatial_emission_layer else None
            ),
        }
