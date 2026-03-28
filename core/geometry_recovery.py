from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


_GEOMETRY_COLUMN_TOKENS: Sequence[str] = (
    "geometry",
    "geom",
    "wkt",
    "geojson",
    "longitude",
    "latitude",
    "lon",
    "lat",
    "lng",
    "x_coord",
    "y_coord",
    "coord_x",
    "coord_y",
    "start_lon",
    "start_lat",
    "end_lon",
    "end_lat",
)

_COORDINATE_PAIRS: Sequence[Tuple[str, str]] = (
    ("longitude", "latitude"),
    ("lon", "lat"),
    ("lng", "lat"),
    ("x_coord", "y_coord"),
    ("coord_x", "coord_y"),
    ("start_lon", "start_lat"),
    ("end_lon", "end_lat"),
)


class GeometryRecoveryStatus(str, Enum):
    ATTACHED = "attached"
    RE_GROUNDED = "re_grounded"
    FAILED = "failed"
    RESUMABLE = "resumable"


def _safe_lower_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_file_type(
    file_ref: Optional[str],
    file_type: Optional[str] = None,
) -> Optional[str]:
    if file_type:
        return _safe_lower_text(file_type) or None
    if not file_ref:
        return None
    suffix = Path(str(file_ref)).suffix.lower().lstrip(".")
    return suffix or None


def _iter_candidate_columns(analysis_dict: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(analysis_dict, dict):
        return []
    columns = analysis_dict.get("columns") or []
    return [str(item) for item in columns if str(item).strip()]


def _detect_geometry_columns(columns: Sequence[str]) -> List[str]:
    matches: List[str] = []
    for column_name in columns:
        normalized = _safe_lower_text(column_name)
        if any(token in normalized for token in _GEOMETRY_COLUMN_TOKENS):
            matches.append(str(column_name))
    return matches


def _detect_coordinate_pairs(columns: Sequence[str]) -> List[List[str]]:
    normalized = {_safe_lower_text(item): str(item) for item in columns}
    pairs: List[List[str]] = []
    for left, right in _COORDINATE_PAIRS:
        if left in normalized and right in normalized:
            pairs.append([normalized[left], normalized[right]])
    return pairs


def infer_geometry_capability_summary(
    analysis_dict: Optional[Dict[str, Any]],
    *,
    file_ref: Optional[str] = None,
) -> Dict[str, Any]:
    analysis = dict(analysis_dict or {})
    spatial_metadata = analysis.get("spatial_metadata") or {}
    dataset_roles = [
        dict(item)
        for item in (analysis.get("dataset_roles") or [])
        if isinstance(item, dict)
    ]
    columns = _iter_candidate_columns(analysis)
    geometry_columns = _detect_geometry_columns(columns)
    coordinate_pairs = _detect_coordinate_pairs(columns)
    support_modes: List[str] = []
    notes: List[str] = []

    if isinstance(spatial_metadata, dict) and spatial_metadata:
        support_modes.append("spatial_metadata")
        notes.append("Supporting file exposes bounded spatial metadata.")

    if geometry_columns:
        support_modes.append("geometry_column_signal")
        notes.append(
            "Supporting file exposes geometry-like columns: "
            + ", ".join(geometry_columns[:6])
            + (" ..." if len(geometry_columns) > 6 else "")
        )

    if coordinate_pairs:
        support_modes.append("coordinate_column_pair")
        notes.append(
            "Supporting file exposes bounded coordinate pairs: "
            + ", ".join("/".join(pair) for pair in coordinate_pairs[:4])
        )

    for role in dataset_roles:
        role_name = _safe_lower_text(role.get("role"))
        format_name = _safe_lower_text(role.get("format"))
        if role_name in {"spatial_context", "supporting_spatial_dataset"}:
            support_modes.append("supporting_spatial_role")
            notes.append("Supporting file was recognized as a supporting spatial dataset.")
            break
        if format_name in {"shapefile", "zip_shapefile", "geojson"}:
            support_modes.append("geospatial_format_role")
            notes.append("Supporting file contains a bounded geospatial dataset role.")
            break

    support_modes = sorted({item for item in support_modes if item})
    geometry_types = []
    if isinstance(spatial_metadata, dict):
        geometry_types = [
            str(item)
            for item in (spatial_metadata.get("geometry_types") or [])
            if str(item).strip()
        ]

    has_geometry_support = bool(support_modes)
    if not has_geometry_support:
        notes.append(
            "Bounded analysis did not find spatial metadata, geometry-like columns, or coordinate pairs "
            "that could safely serve as geometry support."
        )

    return {
        "has_geometry_support": has_geometry_support,
        "support_modes": support_modes,
        "recognized_geometry_columns": geometry_columns,
        "coordinate_column_pairs": coordinate_pairs,
        "geometry_types": geometry_types,
        "analysis_confidence": analysis.get("confidence"),
        "analysis_task_type": analysis.get("task_type"),
        "selected_primary_table": analysis.get("selected_primary_table"),
        "dataset_role_count": len(dataset_roles),
        "file_type": _normalize_file_type(file_ref, analysis.get("format")),
        "notes": notes,
    }


@dataclass
class SupportingSpatialInput:
    file_ref: str
    file_name: str
    file_type: Optional[str]
    source: str
    geometry_capability_summary: Dict[str, Any] = field(default_factory=dict)
    dataset_roles: List[Dict[str, Any]] = field(default_factory=list)
    spatial_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_ref": self.file_ref,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "source": self.source,
            "geometry_capability_summary": dict(self.geometry_capability_summary),
            "dataset_roles": [dict(item) for item in self.dataset_roles],
            "spatial_metadata": dict(self.spatial_metadata),
        }

    def to_summary(self) -> Dict[str, Any]:
        capability = dict(self.geometry_capability_summary or {})
        return {
            "file_name": self.file_name,
            "file_type": self.file_type,
            "source": self.source,
            "has_geometry_support": bool(capability.get("has_geometry_support")),
            "support_modes": list(capability.get("support_modes") or []),
            "geometry_types": list(capability.get("geometry_types") or []),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["SupportingSpatialInput"]:
        if not isinstance(data, dict):
            return None
        return cls(
            file_ref=str(data.get("file_ref") or "").strip(),
            file_name=str(data.get("file_name") or "").strip(),
            file_type=str(data.get("file_type")).strip() if data.get("file_type") is not None else None,
            source=str(data.get("source") or "").strip(),
            geometry_capability_summary=dict(data.get("geometry_capability_summary") or {}),
            dataset_roles=[
                dict(item)
                for item in (data.get("dataset_roles") or [])
                if isinstance(item, dict)
            ],
            spatial_metadata=dict(data.get("spatial_metadata") or {}),
        )

    @classmethod
    def from_analysis(
        cls,
        *,
        file_ref: str,
        source: str,
        analysis_dict: Optional[Dict[str, Any]] = None,
    ) -> "SupportingSpatialInput":
        analysis = dict(analysis_dict or {})
        return cls(
            file_ref=str(file_ref),
            file_name=Path(str(file_ref)).name,
            file_type=_normalize_file_type(file_ref, analysis.get("format")),
            source=str(source or "").strip() or "input_completion_upload",
            geometry_capability_summary=infer_geometry_capability_summary(
                analysis,
                file_ref=file_ref,
            ),
            dataset_roles=[
                dict(item)
                for item in (analysis.get("dataset_roles") or [])
                if isinstance(item, dict)
            ],
            spatial_metadata=dict(analysis.get("spatial_metadata") or {}),
        )


@dataclass
class GeometryRecoveryContext:
    primary_file_ref: Optional[str]
    supporting_spatial_input: SupportingSpatialInput
    target_action_id: Optional[str]
    target_task_type: Optional[str]
    residual_plan_summary: Optional[str]
    recovery_status: str = GeometryRecoveryStatus.ATTACHED.value
    re_grounding_notes: List[str] = field(default_factory=list)
    readiness_before: Optional[Dict[str, Any]] = None
    readiness_after: Optional[Dict[str, Any]] = None
    resume_hint: Optional[str] = None
    upstream_recompute_recommendation: Optional[str] = None
    failure_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "primary_file_ref": self.primary_file_ref,
            "supporting_spatial_input": self.supporting_spatial_input.to_dict(),
            "target_action_id": self.target_action_id,
            "target_task_type": self.target_task_type,
            "residual_plan_summary": self.residual_plan_summary,
            "recovery_status": self.recovery_status,
            "re_grounding_notes": list(self.re_grounding_notes),
            "readiness_before": dict(self.readiness_before or {}),
            "readiness_after": dict(self.readiness_after or {}),
            "resume_hint": self.resume_hint,
            "upstream_recompute_recommendation": self.upstream_recompute_recommendation,
            "failure_reason": self.failure_reason,
        }

    def to_summary(self) -> Dict[str, Any]:
        return {
            "primary_file_ref": self.primary_file_ref,
            "supporting_file_name": self.supporting_spatial_input.file_name,
            "target_action_id": self.target_action_id,
            "target_task_type": self.target_task_type,
            "recovery_status": self.recovery_status,
            "resume_hint": self.resume_hint,
            "upstream_recompute_recommendation": self.upstream_recompute_recommendation,
            "failure_reason": self.failure_reason,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["GeometryRecoveryContext"]:
        if not isinstance(data, dict):
            return None
        supporting = SupportingSpatialInput.from_dict(data.get("supporting_spatial_input"))
        if supporting is None:
            return None
        return cls(
            primary_file_ref=(
                str(data.get("primary_file_ref")).strip()
                if data.get("primary_file_ref") is not None
                else None
            ),
            supporting_spatial_input=supporting,
            target_action_id=(
                str(data.get("target_action_id")).strip()
                if data.get("target_action_id") is not None
                else None
            ),
            target_task_type=(
                str(data.get("target_task_type")).strip()
                if data.get("target_task_type") is not None
                else None
            ),
            residual_plan_summary=(
                str(data.get("residual_plan_summary")).strip()
                if data.get("residual_plan_summary") is not None
                else None
            ),
            recovery_status=str(data.get("recovery_status") or GeometryRecoveryStatus.ATTACHED.value).strip(),
            re_grounding_notes=[
                str(item)
                for item in (data.get("re_grounding_notes") or [])
                if str(item).strip()
            ],
            readiness_before=dict(data.get("readiness_before") or {}) or None,
            readiness_after=dict(data.get("readiness_after") or {}) or None,
            resume_hint=str(data.get("resume_hint")).strip() if data.get("resume_hint") is not None else None,
            upstream_recompute_recommendation=(
                str(data.get("upstream_recompute_recommendation")).strip()
                if data.get("upstream_recompute_recommendation") is not None
                else None
            ),
            failure_reason=(
                str(data.get("failure_reason")).strip()
                if data.get("failure_reason") is not None
                else None
            ),
        )


@dataclass
class GeometryReGroundingResult:
    success: bool
    updated_file_context: Dict[str, Any]
    geometry_support_established: bool
    canonical_signals: Dict[str, Any] = field(default_factory=dict)
    re_grounding_notes: List[str] = field(default_factory=list)
    geometry_support_facts: List[str] = field(default_factory=list)
    upstream_recompute_recommendation: Optional[str] = None
    failure_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "updated_file_context": dict(self.updated_file_context),
            "geometry_support_established": self.geometry_support_established,
            "canonical_signals": dict(self.canonical_signals),
            "re_grounding_notes": list(self.re_grounding_notes),
            "geometry_support_facts": list(self.geometry_support_facts),
            "upstream_recompute_recommendation": self.upstream_recompute_recommendation,
            "failure_reason": self.failure_reason,
        }


def build_geometry_recovery_context(
    *,
    primary_file_ref: Optional[str],
    supporting_spatial_input: SupportingSpatialInput,
    target_action_id: Optional[str],
    target_task_type: Optional[str],
    residual_plan_summary: Optional[str],
    readiness_before: Optional[Dict[str, Any]] = None,
) -> GeometryRecoveryContext:
    notes = [
        "Bounded geometry recovery paired the primary file with one supporting spatial input."
    ]
    if supporting_spatial_input.geometry_capability_summary.get("notes"):
        notes.extend(
            str(item)
            for item in supporting_spatial_input.geometry_capability_summary.get("notes", [])
            if str(item).strip()
        )
    return GeometryRecoveryContext(
        primary_file_ref=primary_file_ref,
        supporting_spatial_input=supporting_spatial_input,
        target_action_id=target_action_id,
        target_task_type=target_task_type,
        residual_plan_summary=residual_plan_summary,
        recovery_status=GeometryRecoveryStatus.ATTACHED.value,
        re_grounding_notes=notes,
        readiness_before=dict(readiness_before or {}) or None,
    )


def _build_upstream_recompute_recommendation(
    target_action_id: Optional[str],
    target_task_type: Optional[str],
) -> str:
    if target_action_id == "render_emission_map":
        return "现在已检测到可用空间支持文件，可在下一轮继续排放地图渲染。"
    if target_action_id == "run_dispersion":
        return "现在已检测到可用空间支持文件；如需扩散分析，请在下一轮基于补齐后的空间支持重新进入该动作。"
    if target_task_type == "macro_emission":
        return "空间支持已补齐，可在下一轮继续当前宏观排放相关空间动作。"
    if target_task_type == "micro_emission":
        return "空间支持已补齐，可在下一轮继续当前微观排放相关空间动作。"
    return "空间支持已补齐，可在下一轮继续当前空间相关动作。"


def re_ground_with_supporting_spatial_input(
    *,
    primary_file_context: Optional[Dict[str, Any]],
    supporting_spatial_input: SupportingSpatialInput,
    target_action_id: Optional[str],
    target_task_type: Optional[str],
    residual_plan_summary: Optional[str],
) -> GeometryReGroundingResult:
    primary = dict(primary_file_context or {})
    support_summary = dict(supporting_spatial_input.geometry_capability_summary or {})
    if not support_summary.get("has_geometry_support"):
        failure_reason = (
            "The uploaded supporting file was analyzed, but it did not expose usable geometry support "
            "signals for bounded recovery."
        )
        return GeometryReGroundingResult(
            success=False,
            updated_file_context=primary,
            geometry_support_established=False,
            canonical_signals={"has_geometry_support": False, "geometry_support_source": None},
            re_grounding_notes=[failure_reason],
            geometry_support_facts=[],
            upstream_recompute_recommendation=None,
            failure_reason=failure_reason,
        )

    updated = dict(primary)
    geometry_support_facts = [
        f"supporting_file={supporting_spatial_input.file_name}",
        "geometry_support=available",
        "geometry_support_source=supporting_spatial_input",
    ]
    support_modes = list(support_summary.get("support_modes") or [])
    if support_modes:
        geometry_support_facts.append("support_modes=" + ",".join(support_modes))

    notes = [
        "Re-grounded the current task against the primary file plus one supporting spatial input.",
        (
            f"Primary file remained {primary.get('file_path') or 'unknown'}, while "
            f"{supporting_spatial_input.file_name} was attached as bounded geometry support."
        ),
    ]
    notes.extend(
        str(item)
        for item in support_summary.get("notes", [])
        if str(item).strip()
    )

    merged_roles = [
        dict(item)
        for item in (updated.get("dataset_roles") or [])
        if isinstance(item, dict)
    ]
    merged_roles.append(
        {
            "dataset_name": supporting_spatial_input.file_name,
            "role": "supporting_spatial_dataset",
            "format": supporting_spatial_input.file_type,
            "task_type": target_task_type,
            "confidence": support_summary.get("analysis_confidence"),
            "selected": False,
            "reason": "Attached through structured geometry completion as bounded spatial support.",
        }
    )

    updated["dataset_roles"] = merged_roles
    updated["spatial_context"] = {
        "mode": "supporting_spatial_input",
        "primary_file_ref": updated.get("file_path"),
        "supporting_file_ref": supporting_spatial_input.file_ref,
        "supporting_file_name": supporting_spatial_input.file_name,
        "supporting_file_type": supporting_spatial_input.file_type,
        "source": supporting_spatial_input.source,
        "geometry_capability_summary": support_summary,
        "spatial_metadata": dict(supporting_spatial_input.spatial_metadata or {}),
        "dataset_roles": [dict(item) for item in supporting_spatial_input.dataset_roles],
        "target_action_id": target_action_id,
        "target_task_type": target_task_type,
        "residual_plan_summary": residual_plan_summary,
    }
    updated["supporting_spatial_input"] = supporting_spatial_input.to_dict()
    updated["geometry_recovery_pairing"] = {
        "mode": "bounded_primary_plus_supporting_spatial_input",
        "primary_file_ref": updated.get("file_path"),
        "supporting_file_ref": supporting_spatial_input.file_ref,
    }

    canonical_signals = {
        "has_geometry_support": True,
        "geometry_support_source": "supporting_spatial_input",
        "support_modes": support_modes,
        "supporting_file_type": supporting_spatial_input.file_type,
        "target_action_id": target_action_id,
    }

    return GeometryReGroundingResult(
        success=True,
        updated_file_context=updated,
        geometry_support_established=True,
        canonical_signals=canonical_signals,
        re_grounding_notes=notes,
        geometry_support_facts=geometry_support_facts,
        upstream_recompute_recommendation=_build_upstream_recompute_recommendation(
            target_action_id,
            target_task_type,
        ),
        failure_reason=None,
    )
