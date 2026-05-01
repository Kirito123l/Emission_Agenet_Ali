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
