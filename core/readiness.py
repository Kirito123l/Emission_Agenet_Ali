"""Unified readiness assessment for action guidance and pre-execution gating."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Sequence, Set

from core.artifact_memory import (
    ArtifactDeliveryStatus,
    ArtifactMemoryState,
    ArtifactType,
    coerce_artifact_memory_state,
)
from core.tool_dependencies import (
    check_road_geometry_from_metadata,
    requires_road_geometry,
    suggest_prerequisite_tool,
    validate_tool_prerequisites,
)
from tools.contract_loader import get_tool_contract_registry

if TYPE_CHECKING:
    from core.context_store import SessionContextStore


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
)

_RESULT_LABELS: Dict[str, str] = {
    "emission": "排放结果",
    "dispersion": "扩散结果",
    "hotspot": "热点分析结果",
}

_FIELD_LABELS: Dict[str, str] = {
    "link_id": "路段标识",
    "link_length_km": "路段长度",
    "traffic_flow_vph": "交通流量",
    "avg_speed_kph": "平均速度",
    "speed_kph": "速度",
    "timestamp_s": "时间戳",
    "vehicle_type": "车型",
    "acceleration_mps2": "加速度",
}

_FIELD_REPAIR_HINTS: Dict[str, str] = {
    "link_id": "请补充路段唯一标识列，例如 link_id 或可稳定映射到路段 ID 的字段。",
    "link_length_km": "请补充 link_length_km 路段长度字段，或提供可稳定换算为公里长度的列。",
    "traffic_flow_vph": "请补充 traffic_flow_vph 流量字段，或提供可换算的 flow / volume / AADT 数据列。",
    "avg_speed_kph": "请补充 avg_speed_kph 平均速度字段，或提供可稳定换算的速度列。",
    "speed_kph": "请补充 speed_kph 速度字段，或提供可稳定换算的速度列。",
    "timestamp_s": "请补充时间戳或时间列，以便形成逐秒或逐点轨迹序列。",
    "vehicle_type": "请明确或补充车型字段，以便选择正确的排放因子。",
    "acceleration_mps2": "请补充 acceleration_mps2 加速度字段，或提供可稳定推导的轨迹列。",
}

_REASON_HINTS: Dict[str, str] = {
    "missing_geometry": "如需空间分析，请补充路段坐标、WKT、GeoJSON 或其他几何信息。",
    "missing_spatial_payload": "当前结果不含可直接渲染的空间载荷，请先使用带几何信息的数据重新计算上游结果。",
    "unknown_task_type": "请先提供更明确的文件结构或分析目标，让系统能判断任务类型。",
    "incompatible_task_type": "请改用与当前任务类型一致的分析动作，或重新上传匹配的数据文件。",
    "missing_scenarios": "请先生成至少两个可比较的情景结果，再进行情景对比。",
}


class ReadinessStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"
    REPAIRABLE = "repairable"
    ALREADY_PROVIDED = "already_provided"


@dataclass
class BlockedReason:
    reason_code: str
    message: str
    missing_requirements: List[str] = field(default_factory=list)
    repair_hint: Optional[str] = None
    severity: str = "warning"
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reason_code": self.reason_code,
            "message": self.message,
            "missing_requirements": list(self.missing_requirements),
            "repair_hint": self.repair_hint,
            "severity": self.severity,
            "details": dict(self.details),
        }


@dataclass
class AlreadyProvidedArtifact:
    artifact_id: str
    display_name: str
    message: str
    kind: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "display_name": self.display_name,
            "label": self.display_name,
            "message": self.message,
            "reason": self.message,
            "kind": self.artifact_id,
            "source_kind": self.kind,
        }


@dataclass
class ActionCatalogEntry:
    action_id: str
    display_name: str
    description: str
    tool_name: Optional[str] = None
    arguments: Dict[str, Any] = field(default_factory=dict)
    guidance_utterance: Optional[str] = None
    required_task_types: List[str] = field(default_factory=list)
    required_result_tokens: List[str] = field(default_factory=list)
    requires_geometry_support: bool = False
    requires_spatial_result_token: Optional[str] = None
    provided_conflicts: List[str] = field(default_factory=list)
    artifact_key: Optional[str] = None
    alternative_action_ids: List[str] = field(default_factory=list)
    guidance_enabled: bool = True
    pre_execution_enabled: bool = True
    category: str = "analysis"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "display_name": self.display_name,
            "description": self.description,
            "tool_name": self.tool_name,
            "arguments": dict(self.arguments),
            "guidance_utterance": self.guidance_utterance,
            "required_task_types": list(self.required_task_types),
            "required_result_tokens": list(self.required_result_tokens),
            "requires_geometry_support": self.requires_geometry_support,
            "requires_spatial_result_token": self.requires_spatial_result_token,
            "provided_conflicts": list(self.provided_conflicts),
            "artifact_key": self.artifact_key,
            "alternative_action_ids": list(self.alternative_action_ids),
            "guidance_enabled": self.guidance_enabled,
            "pre_execution_enabled": self.pre_execution_enabled,
            "category": self.category,
        }


@dataclass
class ActionAffordance:
    action_id: str
    status: ReadinessStatus
    display_name: str
    description: str
    tool_name: Optional[str] = None
    arguments: Dict[str, Any] = field(default_factory=dict)
    reason: Optional[BlockedReason] = None
    required_conditions: List[str] = field(default_factory=list)
    available_conditions: List[str] = field(default_factory=list)
    alternative_actions: List[str] = field(default_factory=list)
    guidance_utterance: Optional[str] = None
    guidance_enabled: bool = True
    provided_artifact: Optional[AlreadyProvidedArtifact] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "status": self.status.value,
            "display_name": self.display_name,
            "description": self.description,
            "tool_name": self.tool_name,
            "arguments": dict(self.arguments),
            "reason": self.reason.to_dict() if self.reason else None,
            "required_conditions": list(self.required_conditions),
            "available_conditions": list(self.available_conditions),
            "alternative_actions": list(self.alternative_actions),
            "guidance_utterance": self.guidance_utterance,
            "guidance_enabled": self.guidance_enabled,
            "provided_artifact": (
                self.provided_artifact.to_dict()
                if self.provided_artifact is not None
                else None
            ),
        }


@dataclass
class ReadinessAssessment:
    available_actions: List[ActionAffordance] = field(default_factory=list)
    blocked_actions: List[ActionAffordance] = field(default_factory=list)
    repairable_actions: List[ActionAffordance] = field(default_factory=list)
    already_provided_actions: List[ActionAffordance] = field(default_factory=list)
    summary_notes: List[str] = field(default_factory=list)
    key_signals: Dict[str, Any] = field(default_factory=dict)
    catalog: List[ActionCatalogEntry] = field(default_factory=list)

    def get_action(self, action_id: Optional[str]) -> Optional[ActionAffordance]:
        if not action_id:
            return None
        for item in (
            self.available_actions
            + self.blocked_actions
            + self.repairable_actions
            + self.already_provided_actions
        ):
            if item.action_id == action_id:
                return item
        return None

    def counts(self) -> Dict[str, int]:
        return {
            "ready": len(self.available_actions),
            "blocked": len(self.blocked_actions),
            "repairable": len(self.repairable_actions),
            "already_provided": len(self.already_provided_actions),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available_actions": [item.to_dict() for item in self.available_actions],
            "blocked_actions": [item.to_dict() for item in self.blocked_actions],
            "repairable_actions": [item.to_dict() for item in self.repairable_actions],
            "already_provided_actions": [item.to_dict() for item in self.already_provided_actions],
            "summary_notes": list(self.summary_notes),
            "key_signals": dict(self.key_signals),
            "catalog": [item.to_dict() for item in self.catalog],
            "counts": self.counts(),
        }

    def to_capability_summary(self) -> Dict[str, Any]:
        def _serialize(items: List[ActionAffordance]) -> List[Dict[str, Any]]:
            return [
                {
                    "action_id": item.action_id,
                    "tool_name": item.tool_name,
                    "arguments": dict(item.arguments),
                    "label": item.display_name,
                    "description": item.description,
                    "utterance": item.guidance_utterance,
                    "reason": item.reason.message if item.reason else item.description,
                    "reason_codes": (
                        [item.reason.reason_code]
                        if item.reason is not None and item.reason.reason_code
                        else []
                    ),
                    "missing_requirements": (
                        list(item.reason.missing_requirements)
                        if item.reason is not None
                        else []
                    ),
                    "repair_hint": item.reason.repair_hint if item.reason else None,
                }
                for item in items
                if item.guidance_enabled
            ]

        already_provided = [
            item.provided_artifact.to_dict()
            for item in self.already_provided_actions
            if item.provided_artifact is not None
        ]
        unavailable = _serialize(self.repairable_actions) + _serialize(self.blocked_actions)

        guidance_hints: List[str] = []
        for note in self.summary_notes:
            text = str(note).strip()
            if text and text not in guidance_hints:
                guidance_hints.append(text)

        return {
            "available_next_actions": _serialize(self.available_actions),
            "repairable_actions": _serialize(self.repairable_actions),
            "unavailable_actions_with_reasons": unavailable,
            "already_provided": already_provided,
            "guidance_hints": guidance_hints,
            "metadata": dict(self.key_signals),
            "readiness": self.to_dict(),
        }


def _safe_lower_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _coerce_file_context(file_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return dict(file_context) if isinstance(file_context, dict) else {}


def _iter_candidate_column_names(file_context: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    columns = file_context.get("columns") or []
    if isinstance(columns, list):
        names.extend(str(item) for item in columns)
    mapping = file_context.get("column_mapping") or {}
    if isinstance(mapping, dict):
        names.extend(str(item) for item in mapping.keys())
        names.extend(str(item) for item in mapping.values())
    return names


def _extract_map_kinds(map_payload: Any) -> Set[str]:
    kinds: Set[str] = set()
    if not isinstance(map_payload, dict) or not map_payload:
        return kinds
    if map_payload.get("type") == "map_collection" and isinstance(map_payload.get("items"), list):
        for item in map_payload["items"]:
            kinds.update(_extract_map_kinds(item))
        return kinds or {"any"}

    map_type = _safe_lower_text(map_payload.get("type"))
    if map_type in {"macro_emission_map", "emission"}:
        kinds.add("emission")
    elif map_type in {"contour", "dispersion", "filled_contour", "raster", "concentration", "points"}:
        kinds.add("dispersion")
    elif map_type == "hotspot":
        kinds.add("hotspot")
    elif map_type:
        kinds.add("any")
    return kinds


def _result_has_spatial_payload(token: str, result: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(result, dict):
        return False
    if isinstance(result.get("map_data"), dict):
        return True

    data = result.get("data", {})
    if not isinstance(data, dict):
        return False
    if isinstance(data.get("map_data"), dict) or isinstance(data.get("map_config"), dict):
        return True

    if token == "emission":
        results = data.get("results", [])
        if isinstance(results, list):
            return any(isinstance(item, dict) and item.get("geometry") for item in results[:10])
        return False
    if token == "dispersion":
        return any(
            data.get(key)
            for key in ("raster_grid", "concentration_grid", "concentration_geojson", "receptors")
        )
    if token == "hotspot":
        return bool(data.get("hotspots") or data.get("hotspots_geojson") or data.get("raster_grid"))
    return False


def _collect_result_payloads(
    tool_results: Sequence[Dict[str, Any]],
    context_store: Optional["SessionContextStore"],
) -> Dict[str, Dict[str, Any]]:
    payloads: Dict[str, Dict[str, Any]] = {}

    from core.tool_dependencies import get_tool_provides

    for item in tool_results or []:
        if not isinstance(item, dict):
            continue
        result = item.get("result", {})
        if not isinstance(result, dict) or not result.get("success"):
            continue
        for token in get_tool_provides(str(item.get("name") or "")):
            if token in {"emission", "dispersion", "hotspot"}:
                payloads[token] = result

    if context_store is None:
        return payloads

    for token in ("emission", "dispersion", "hotspot"):
        if token in payloads:
            continue
        stored = context_store.get_by_type(token)
        if stored is not None and isinstance(stored.data, dict):
            payloads[token] = stored.data
    return payloads


def _collect_available_tokens(
    tool_results: Sequence[Dict[str, Any]],
    context_store: Optional["SessionContextStore"],
) -> List[str]:
    from core.tool_dependencies import get_tool_provides, normalize_tokens

    tokens: Set[str] = set()
    if context_store is not None:
        tokens.update(context_store.get_available_types(include_stale=False))
    for item in tool_results or []:
        if not isinstance(item, dict):
            continue
        result = item.get("result", {})
        if not isinstance(result, dict) or not result.get("success"):
            continue
        tokens.update(get_tool_provides(str(item.get("name") or "")))
    return normalize_tokens(tokens)


def _determine_geometry_support(
    file_context: Dict[str, Any],
    result_payloads: Dict[str, Dict[str, Any]],
    geometry_file_context: Optional[Dict[str, Any]] = None,
) -> tuple[bool, Optional[str]]:
    # 1. Spatial metadata from shapefile/geojson (existing)
    spatial_metadata = file_context.get("spatial_metadata") or {}
    if isinstance(spatial_metadata, dict) and spatial_metadata:
        return True, "file_spatial_metadata"

    # 2. Spatial context from geometry recovery (existing)
    spatial_context = file_context.get("spatial_context") or {}
    if isinstance(spatial_context, dict) and spatial_context:
        if _safe_lower_text(spatial_context.get("mode")) == "supporting_spatial_input":
            return True, "supporting_spatial_input"
        return True, "file_spatial_context"

    # 3. Phase 7.2 geometry_metadata — deterministic, evidence-backed (new)
    geometry_metadata = file_context.get("geometry_metadata") or {}
    if isinstance(geometry_metadata, dict):
        if geometry_metadata.get("road_geometry_available"):
            return True, "geometry_metadata"
        if geometry_metadata.get("point_geometry_available"):
            # Point geometry exists but not sufficient for road dispersion.
            # Mark as False with source info for diagnostic messages.
            return False, "geometry_metadata_point_only"

    # 4. Phase 7.6D: geometry_file_context provides geometry support when
    # emission file is join_key_only and a geometry file is available.
    if isinstance(geometry_file_context, dict):
        geo_gm = dict(geometry_file_context.get("geometry_metadata") or {})
        if geo_gm.get("road_geometry_available"):
            return True, "join_key_geometry_file_context"

    # 5. Dataset roles (existing, fallback)
    dataset_roles = file_context.get("dataset_roles") or []
    if isinstance(dataset_roles, list):
        for item in dataset_roles:
            if not isinstance(item, dict):
                continue
            if item.get("selected") and _safe_lower_text(item.get("format")) == "geospatial":
                return True, "selected_geospatial_dataset"
            if _safe_lower_text(item.get("role")) in {"spatial_context", "supporting_spatial_dataset"}:
                return True, "supporting_spatial_dataset"

    # 6. Column-name heuristics (existing, fallback)
    for column_name in _iter_candidate_column_names(file_context):
        normalized = _safe_lower_text(column_name)
        if any(token in normalized for token in _GEOMETRY_COLUMN_TOKENS):
            return True, "geometry_column_signal"

    # 7. Emission result payload (existing, fallback)
    if _result_has_spatial_payload("emission", result_payloads.get("emission")):
        return True, "emission_result_geometry"

    return False, None


def _collect_already_provided_artifacts(
    current_response_payloads: Optional[Dict[str, Any]],
    tool_results: Sequence[Dict[str, Any]],
    artifact_memory_state: Optional[ArtifactMemoryState] = None,
) -> tuple[List[AlreadyProvidedArtifact], Set[str]]:
    payloads = dict(current_response_payloads or {})
    artifacts: List[AlreadyProvidedArtifact] = []
    provided_ids: Set[str] = set()
    seen_ids: Set[str] = set()

    def _append_artifact(artifact: AlreadyProvidedArtifact) -> None:
        if artifact.artifact_id in seen_ids:
            return
        artifacts.append(artifact)
        seen_ids.add(artifact.artifact_id)
        provided_ids.add(artifact.artifact_id)

    for item in tool_results or []:
        if not isinstance(item, dict):
            continue
        result = item.get("result", {})
        if not isinstance(result, dict):
            continue
        data = result.get("data", {})
        if not payloads.get("download_file") and isinstance(data, dict) and data.get("download_file"):
            payloads["download_file"] = data.get("download_file")
        if not payloads.get("map_data") and isinstance(result.get("map_data"), dict):
            payloads["map_data"] = result.get("map_data")
        if not payloads.get("chart_data") and isinstance(result.get("chart_data"), dict):
            payloads["chart_data"] = result.get("chart_data")
        if not payloads.get("table_data") and isinstance(result.get("table_data"), dict):
            payloads["table_data"] = result.get("table_data")

    download_payload = payloads.get("download_file")
    if download_payload:
        filename = ""
        if isinstance(download_payload, dict):
            filename = str(download_payload.get("filename") or download_payload.get("path") or "")
        else:
            filename = str(download_payload)
        filename_lower = filename.lower()
        artifact_id = "download_topk_summary" if "top" in filename_lower and "summary" in filename_lower else "download_detailed_csv"
        _append_artifact(
            AlreadyProvidedArtifact(
                artifact_id=artifact_id,
                display_name="结果下载文件",
                message="本次回复已经提供了可下载结果文件。",
                kind="download_file",
            )
        )
        provided_ids.add("download_file")

    if payloads.get("table_data"):
        _append_artifact(
            AlreadyProvidedArtifact(
                artifact_id="summary_table",
                display_name="结果表格预览",
                message="本次回复已经附带结果表格预览。",
                kind="table_data",
            )
        )
        provided_ids.add("table_data")

    if payloads.get("chart_data"):
        _append_artifact(
            AlreadyProvidedArtifact(
                artifact_id="render_rank_chart",
                display_name="结果图表",
                message="本次回复已经提供图表数据。",
                kind="chart_data",
            )
        )
        provided_ids.add("chart_data")

    map_kinds = _extract_map_kinds(payloads.get("map_data"))
    for kind in sorted(map_kinds):
        _append_artifact(
            AlreadyProvidedArtifact(
                artifact_id=f"map:{kind}",
                display_name={
                    "emission": "排放空间地图",
                    "dispersion": "浓度空间地图",
                    "hotspot": "热点空间地图",
                    "any": "空间地图",
                }.get(kind, "空间地图"),
                message="本次回复已经提供了对应的空间可视化结果。",
                kind="map_data",
            )
        )

    artifact_state = coerce_artifact_memory_state(artifact_memory_state)
    for record in artifact_state.artifacts:
        if record.delivery_status != ArtifactDeliveryStatus.FULL:
            continue
        artifact_id: Optional[str] = None
        display_name: Optional[str] = None
        if record.artifact_type == ArtifactType.DETAILED_CSV:
            artifact_id = "download_detailed_csv"
            display_name = "详细结果文件"
        elif record.artifact_type == ArtifactType.TOPK_SUMMARY_TABLE:
            artifact_id = "download_topk_summary" if record.download_ref or record.file_ref else "summary_table"
            display_name = "摘要结果文件" if artifact_id == "download_topk_summary" else "摘要表"
        elif record.artifact_type == ArtifactType.RANKED_CHART:
            artifact_id = "render_rank_chart"
            display_name = "结果图表"
        elif record.artifact_type == ArtifactType.SPATIAL_MAP:
            artifact_id = "map:emission"
            display_name = "排放空间地图"
        elif record.artifact_type == ArtifactType.DISPERSION_MAP:
            artifact_id = "map:dispersion"
            display_name = "浓度空间地图"
        elif record.artifact_type == ArtifactType.HOTSPOT_MAP:
            artifact_id = "map:hotspot"
            display_name = "热点空间地图"
        elif record.artifact_type == ArtifactType.QUICK_SUMMARY_TEXT:
            artifact_id = "quick_summary_text"
            display_name = "文字摘要"
        elif record.artifact_type == ArtifactType.COMPARISON_RESULT:
            artifact_id = "comparison_result"
            display_name = "情景对比结果"
        if not artifact_id or not display_name:
            continue
        _append_artifact(
            AlreadyProvidedArtifact(
                artifact_id=artifact_id,
                display_name=display_name,
                message=record.summary or "该交付物已在近期回复中完整提供。",
                kind="artifact_memory",
            )
        )

    return artifacts, provided_ids


def _field_label(field_name: str) -> str:
    return _FIELD_LABELS.get(field_name, field_name)


def _build_missing_field_reason(
    *,
    expected_task_type: str,
    diagnostics: Dict[str, Any],
) -> Optional[BlockedReason]:
    field_statuses = diagnostics.get("required_field_statuses") or []
    if not isinstance(field_statuses, list) or not field_statuses:
        return BlockedReason(
            reason_code="insufficient_file_readiness",
            message="当前文件尚未形成稳定的必需字段诊断，不能安全启动该计算。",
            missing_requirements=[],
            repair_hint="请补充更完整的文件字段，或重新上传结构更明确的数据文件。",
            severity="warning",
        )

    unresolved = []
    hints: List[str] = []
    for item in field_statuses:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        if status == "present":
            continue
        field_name = str(item.get("field") or "").strip()
        if not field_name:
            continue
        unresolved.append(f"{_field_label(field_name)}({field_name})")
        hint = _FIELD_REPAIR_HINTS.get(field_name)
        if hint and hint not in hints:
            hints.append(hint)

    if not unresolved:
        return None

    message = (
        f"当前还不能安全执行{expected_task_type}计算，因为关键输入字段尚未齐备："
        f"{'、'.join(unresolved)}。"
    )
    return BlockedReason(
        reason_code="missing_required_fields",
        message=message,
        missing_requirements=unresolved,
        repair_hint=hints[0] if hints else "请补齐缺失字段后再继续执行该计算。",
        severity="warning",
        details={"diagnostics_status": diagnostics.get("status")},
    )


def _build_dependency_reason(tool_name: str, validation: Any) -> BlockedReason:
    readable_missing = [_RESULT_LABELS.get(token, token) for token in validation.missing_tokens]
    readable_stale = [_RESULT_LABELS.get(token, token) for token in validation.stale_tokens]
    missing_requirements = readable_missing + readable_stale
    missing_tool = suggest_prerequisite_tool(validation.missing_tokens[0]) if validation.missing_tokens else None

    if validation.missing_tokens:
        if len(readable_missing) == 1:
            message = f"当前还没有可用的{readable_missing[0]}，因此不能直接执行 {tool_name}。"
        else:
            message = f"当前缺少前置结果：{'、'.join(readable_missing)}，因此不能直接执行 {tool_name}。"
        repair_hint = (
            f"请先完成上游步骤 {missing_tool}，再继续当前动作。"
            if missing_tool
            else "请先完成缺失的上游分析结果，再继续当前动作。"
        )
        reason_code = "missing_prerequisite_result"
    else:
        message = f"{tool_name} 所需的前置结果当前只有 stale 版本，不能作为本次执行输入。"
        repair_hint = "请先重新生成最新的上游结果，再继续当前动作。"
        reason_code = "stale_prerequisite_result"

    return BlockedReason(
        reason_code=reason_code,
        message=message,
        missing_requirements=missing_requirements,
        repair_hint=repair_hint,
        severity="warning",
        details=validation.to_dict() if hasattr(validation, "to_dict") else {},
    )


def _build_geometry_reason() -> BlockedReason:
    return BlockedReason(
        reason_code="missing_geometry",
        message="当前文件或结果中没有可用于空间分析的几何信息，因此不能直接进行地图渲染或扩散分析。",
        missing_requirements=["geometry"],
        repair_hint=_REASON_HINTS["missing_geometry"],
        severity="warning",
    )


def _build_spatial_payload_reason(token: str) -> BlockedReason:
    readable = _RESULT_LABELS.get(token, token)
    return BlockedReason(
        reason_code="missing_spatial_payload",
        message=f"当前{readable}不包含可直接渲染的空间数据载荷，因此该空间动作尚未就绪。",
        missing_requirements=[f"{token}_spatial_payload"],
        repair_hint=_REASON_HINTS["missing_spatial_payload"],
        severity="warning",
    )


# ── Spatial emission precondition (Phase 7.4B) ──────────────────────────

_SPATIAL_REASON_HINTS: Dict[str, str] = {
    "spatial_emission_layer_available": "",
    "spatial_emission_available": "",
    "point_geometry_not_road_geometry": (
        "文件仅包含点坐标 (lon/lat)，不具备路段线几何。"
        "请提供含 WKT、GeoJSON 或起终点坐标的路段几何文件。"
    ),
    "join_key_without_geometry": (
        "文件仅包含路段标识列，不包含几何列。"
        "请额外上传含路段几何的 Shapefile/GeoJSON 文件，或补充 WKT/起终点坐标列。"
    ),
    "missing_road_geometry": (
        "文件中未检测到路段几何。"
        "请上传含 WKT、GeoJSON、起终点坐标的几何文件，或使用 Shapefile。"
    ),
    "road_geometry_unavailable": (
        "检测到几何候选列但内容不含可用路段线几何。"
        "请检查几何列是否确实包含 LINESTRING/POLYGON 类型的空间数据。"
    ),
}


def _build_spatial_emission_reason(reason_code: str, message: str) -> BlockedReason:
    return BlockedReason(
        reason_code=reason_code,
        message=message,
        missing_requirements=["road_geometry"],
        repair_hint=_SPATIAL_REASON_HINTS.get(reason_code, ""),
        severity="warning",
    )


def _build_spatial_emission_layer_from_results(
    file_context: Dict[str, Any],
    current_tool_results: Sequence[Dict[str, Any]],
    geometry_file_context: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Try to build a spatial emission layer from a prior macro emission result.

    When calculate_macro_emission has succeeded and the file has direct road
    geometry, this helper produces a spatial_emission_layer dict that the
    dispersion preflight can consume without re-resolving from FileContext.

    When the emission file is join_key_only and a geometry_file_context is
    provided, the join-key resolver (Phase 7.6B) is invoked.  If the resolver
    returns ACCEPT, the resulting layer is returned so that readiness can
    treat it identically to a direct-geometry layer.

    Returns None when no macro result exists, geometry is not available, or
    join-key resolution is rejected.
    """
    # Find a successful macro emission result
    macro_result = None
    macro_result_ref = None
    for item in (current_tool_results or []):
        if isinstance(item, dict) and item.get("name") == "calculate_macro_emission":
            result = item.get("result") or {}
            if isinstance(result, dict) and result.get("success"):
                macro_result = result
                label = item.get("label") or "baseline"
                macro_result_ref = f"macro_emission:{label}"
                break

    if macro_result is None:
        return None

    # Phase 7.6D: try join-key resolver when emission is join_key_only and a
    # geometry FileContext is explicitly provided.
    gm = dict(file_context.get("geometry_metadata") or {})
    geo_type = str(gm.get("geometry_type", "none")).strip().lower()
    if geo_type == "join_key_only" and isinstance(geometry_file_context, dict):
        from core.spatial_emission_resolver import resolve_join_key_geometry_layer

        jk_result = resolve_join_key_geometry_layer(
            emission_file_context=file_context,
            geometry_file_context=geometry_file_context,
            emission_result_ref=macro_result_ref,
        )
        if jk_result.status == "ACCEPT" and jk_result.spatial_emission_layer:
            return jk_result.spatial_emission_layer
        # For NEEDS_USER_CONFIRMATION, REJECT, or INSUFFICIENT_INPUT:
        # return None so readiness uses the resolver's diagnostic via
        # resolve_spatial_precondition (which also receives geometry_file_context).
        return None

    from core.spatial_emission_resolver import build_spatial_emission_layer

    layer = build_spatial_emission_layer(
        file_context=file_context,
        emission_result_ref=macro_result_ref,
        emission_output_path=None,
        macro_result=macro_result,
    )

    if not layer.layer_available:
        return None

    return layer.to_dict()


def resolve_spatial_precondition(
    tool_name: str,
    file_context: Optional[Dict[str, Any]] = None,
    emission_result_ref: Optional[str] = None,
    spatial_emission_layer: Optional[Dict[str, Any]] = None,
    geometry_file_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate spatial emission precondition for a tool.

    Wraps the Phase 7.4A spatial emission resolver and returns a readiness-
    compatible diagnostic dict.  When a spatial_emission_layer (Phase 7.5) is
    provided and layer_available is true, the precondition is satisfied via
    the direct geometry bridge rather than re-resolving from FileContext.

    Phase 7.6D: when the emission file_context is join_key_only and a
    geometry_file_context is provided, the join-key resolver is invoked
    to produce a targeted diagnostic (ACCEPT / NEEDS_USER_CONFIRMATION /
    REJECT / INSUFFICIENT_INPUT).  ACCEPT results carry a spatial_emission_layer
    dict; other statuses carry the resolver's reason_code and message.

    For tools that do NOT require road geometry, returns satisfied=true
    immediately with reason_code=no_road_geometry_requirement.

    Returns:
        Dict with keys: satisfied, reason_code, message, candidate_dict, layer_dict.
        candidate_dict is the serialised SpatialEmissionCandidate (or None).
        layer_dict is the spatial_emission_layer (or None).
    """
    from core.tool_dependencies import requires_road_geometry
    from core.spatial_emission_resolver import resolve_spatial_emission_candidate

    if not requires_road_geometry(tool_name):
        return {
            "satisfied": True,
            "reason_code": "no_road_geometry_requirement",
            "message": f"Tool '{tool_name}' does not require road geometry.",
            "candidate_dict": None,
            "layer_dict": None,
        }

    # Phase 7.5: spatial_emission_layer bridge takes priority
    if isinstance(spatial_emission_layer, dict) and spatial_emission_layer.get("layer_available"):
        return {
            "satisfied": True,
            "reason_code": "spatial_emission_layer_available",
            "message": "Spatial emission layer available from upstream macro emission result.",
            "candidate_dict": None,
            "layer_dict": dict(spatial_emission_layer),
        }

    # Phase 7.6D: join-key resolver when emission is join_key_only and a
    # geometry FileContext is explicitly provided.
    fc = dict(file_context or {})
    gm = dict(fc.get("geometry_metadata") or {})
    geo_type = str(gm.get("geometry_type", "none")).strip().lower()
    if geo_type == "join_key_only" and isinstance(geometry_file_context, dict):
        from core.spatial_emission_resolver import resolve_join_key_geometry_layer

        jk_result = resolve_join_key_geometry_layer(
            emission_file_context=fc,
            geometry_file_context=geometry_file_context,
            emission_result_ref=emission_result_ref,
        )

        if jk_result.status == "ACCEPT" and jk_result.spatial_emission_layer:
            return {
                "satisfied": True,
                "reason_code": "join_key_geometry_resolved",
                "message": jk_result.message,
                "candidate_dict": None,
                "layer_dict": jk_result.spatial_emission_layer,
            }

        # NEEDS_USER_CONFIRMATION, REJECT, INSUFFICIENT_INPUT:
        # surface the resolver's diagnostic
        return {
            "satisfied": False,
            "reason_code": jk_result.reason_code,
            "message": jk_result.message,
            "candidate_dict": jk_result.to_dict(),
            "layer_dict": None,
        }

    candidate = resolve_spatial_emission_candidate(
        file_context=file_context,
        emission_result_ref=emission_result_ref,
    )

    return {
        "satisfied": candidate.available,
        "reason_code": candidate.reason_code,
        "message": candidate.message,
        "candidate_dict": candidate.to_dict() if candidate.available or True else candidate.to_dict(),
        "layer_dict": None,
    }


def _build_required_result_reason(tokens: Sequence[str]) -> BlockedReason:
    readable = [_RESULT_LABELS.get(token, token) for token in tokens]
    if len(readable) == 1:
        message = f"当前还没有可用于该交付动作的{readable[0]}，因此不能直接生成这类结果。"
    else:
        message = f"当前缺少可用于该交付动作的前置结果：{'、'.join(readable)}。"
    return BlockedReason(
        reason_code="missing_prerequisite_result",
        message=message,
        missing_requirements=[f"result:{token}" for token in tokens],
        repair_hint="请先生成上游分析结果，再继续当前图表/摘要交付。",
        severity="warning",
        details={"required_result_tokens": list(tokens)},
    )


def _build_task_type_reason(action: ActionCatalogEntry, task_type: Optional[str]) -> BlockedReason:
    normalized_task_type = str(task_type or "unknown").strip() or "unknown"
    if normalized_task_type == "unknown":
        return BlockedReason(
            reason_code="unknown_task_type",
            message=f"当前文件任务类型尚未明确，因此不能安全执行“{action.display_name}”。",
            missing_requirements=["task_type"],
            repair_hint=_REASON_HINTS["unknown_task_type"],
            severity="warning",
        )
    return BlockedReason(
        reason_code="incompatible_task_type",
        message=(
            f"当前任务类型为 {normalized_task_type}，与动作“{action.display_name}”"
            "不匹配，因此该动作被阻断。"
        ),
        missing_requirements=[normalized_task_type],
        repair_hint=_REASON_HINTS["incompatible_task_type"],
        severity="error",
    )


def _build_already_provided_affordance(
    entry: ActionCatalogEntry,
    artifact: AlreadyProvidedArtifact,
    available_conditions: List[str],
) -> ActionAffordance:
    return ActionAffordance(
        action_id=entry.action_id,
        status=ReadinessStatus.ALREADY_PROVIDED,
        display_name=entry.display_name,
        description=entry.description,
        tool_name=entry.tool_name,
        arguments=dict(entry.arguments),
        reason=BlockedReason(
            reason_code="artifact_already_provided",
            message=artifact.message,
            missing_requirements=[],
            repair_hint=None,
            severity="info",
            details={"artifact_id": artifact.artifact_id},
        ),
        required_conditions=[],
        available_conditions=available_conditions,
        alternative_actions=list(entry.alternative_action_ids),
        guidance_utterance=entry.guidance_utterance,
        guidance_enabled=entry.guidance_enabled,
        provided_artifact=artifact,
    )


def get_action_catalog() -> List[ActionCatalogEntry]:
    registry = get_tool_contract_registry()
    return [
        ActionCatalogEntry(**entry)
        for entry in registry.get_action_catalog_entries()
    ]


def map_tool_call_to_action_id(
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    normalized_tool = str(tool_name or "").strip()
    args = dict(arguments or {})
    if normalized_tool == "calculate_macro_emission":
        return "run_macro_emission"
    if normalized_tool == "calculate_micro_emission":
        return "run_micro_emission"
    if normalized_tool == "calculate_dispersion":
        return "run_dispersion"
    if normalized_tool == "analyze_hotspots":
        return "run_hotspot_analysis"
    if normalized_tool == "compare_scenarios":
        return "compare_scenario"
    if normalized_tool == "render_spatial_map":
        layer_type = _safe_lower_text(args.get("layer_type"))
        if layer_type in {"dispersion", "raster", "concentration", "contour"}:
            return "render_dispersion_map"
        if layer_type == "hotspot":
            return "render_hotspot_map"
        if layer_type == "emission":
            return "render_emission_map"
    return None


def _count_scenarios(context_store: Optional["SessionContextStore"]) -> int:
    if context_store is None:
        return 0
    max_count = 0
    for result_type in ("emission", "dispersion", "hotspot"):
        labels = context_store.list_scenarios(result_type).get(result_type, [])
        max_count = max(max_count, len(labels))
    return max_count


def _build_available_conditions(
    *,
    available_tokens: Set[str],
    has_geometry_support: bool,
    provided_artifact_ids: Set[str],
    task_type: Optional[str],
    parameter_locks: Optional[Dict[str, Any]],
    input_completion_overrides: Optional[Dict[str, Any]],
) -> List[str]:
    conditions: List[str] = []
    if task_type:
        conditions.append(f"task_type:{task_type}")
    for token in sorted(available_tokens):
        conditions.append(f"result:{token}")
    if has_geometry_support:
        conditions.append("geometry_support")
    for item in sorted(provided_artifact_ids):
        conditions.append(f"artifact:{item}")
    if parameter_locks:
        for name in sorted(parameter_locks.keys()):
            conditions.append(f"locked_param:{name}")
    if input_completion_overrides:
        for name in sorted(input_completion_overrides.keys()):
            conditions.append(f"completion_override:{name}")
    return conditions


def _normalize_input_completion_overrides(
    overrides: Optional[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    normalized: Dict[str, Dict[str, Any]] = {}
    for key, value in (overrides or {}).items():
        if isinstance(value, dict):
            normalized[str(key)] = dict(value)
    return normalized


def _missing_field_resolved_by_override(
    field_name: str,
    input_completion_overrides: Dict[str, Dict[str, Any]],
) -> bool:
    override = input_completion_overrides.get(field_name)
    if not isinstance(override, dict):
        return False
    mode = str(override.get("mode") or "").strip().lower()
    if mode == "uniform_scalar":
        return override.get("value") is not None
    if mode in {"source_column_derivation", "use_derivation"}:
        return bool(override.get("source_column"))
    if mode == "uploaded_supporting_file":
        return bool(override.get("file_ref"))
    if mode == "default_typical_profile":
        return True
    return False


def _run_tool_preflight_check(
    tool_name: Optional[str],
    parameter_locks: Optional[Dict[str, Any]],
    normalized_completion_overrides: Optional[Dict[str, Any]],
) -> Optional[BlockedReason]:
    """
    Invoke the tool's preflight_check() via the registry and convert the result to a
    BlockedReason.  Returns None when the tool is ready or when the check cannot run.
    Exceptions inside the check are swallowed so a broken check never blocks execution.
    """
    if not tool_name:
        return None
    try:
        from tools.registry import get_registry

        tool = get_registry().get(tool_name)
        if tool is None or not hasattr(tool, "preflight_check"):
            return None

        params: Dict[str, Any] = {}
        if parameter_locks:
            params.update(parameter_locks)
        if normalized_completion_overrides:
            params.update(normalized_completion_overrides)

        result = tool.preflight_check(params)
        if result.is_ready:
            return None

        return BlockedReason(
            reason_code=result.reason_code or "asset_check_failed",
            message=result.message or "工具资产检查失败。",
            missing_requirements=list(result.missing_requirements or []),
            repair_hint="请确认所需的模型文件或配置资源完整可用。",
            severity="error",
            details=dict(result.details or {}),
        )
    except Exception:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "Preflight check for tool '%s' raised an exception, skipping", tool_name, exc_info=True
        )
        return None


def assess_action_readiness(
    action: ActionCatalogEntry,
    *,
    file_context: Dict[str, Any],
    context_store: Optional["SessionContextStore"],
    current_tool_results: Sequence[Dict[str, Any]],
    current_response_payloads: Optional[Dict[str, Any]],
    parameter_locks: Optional[Dict[str, Any]] = None,
    input_completion_overrides: Optional[Dict[str, Any]] = None,
    already_provided_dedup_enabled: bool = True,
    artifact_memory_state: Optional[ArtifactMemoryState] = None,
    geometry_file_context: Optional[Dict[str, Any]] = None,
) -> ActionAffordance:
    diagnostics = file_context.get("missing_field_diagnostics") or {}
    task_type = str(file_context.get("task_type") or "").strip() or None
    normalized_completion_overrides = _normalize_input_completion_overrides(input_completion_overrides)
    has_grounded_file_context = bool(
        task_type
        or file_context.get("columns")
        or file_context.get("missing_field_diagnostics")
        or file_context.get("spatial_metadata")
        or file_context.get("dataset_roles")
    )
    result_payloads = _collect_result_payloads(current_tool_results, context_store)
    available_tokens = set(_collect_available_tokens(current_tool_results, context_store))
    if already_provided_dedup_enabled:
        already_provided, provided_ids = _collect_already_provided_artifacts(
            current_response_payloads,
            current_tool_results,
            artifact_memory_state=artifact_memory_state,
        )
    else:
        already_provided, provided_ids = [], set()
    artifact_by_id = {item.artifact_id: item for item in already_provided}
    has_geometry_support, _geometry_source = _determine_geometry_support(
        file_context, result_payloads, geometry_file_context=geometry_file_context,
    )
    available_conditions = _build_available_conditions(
        available_tokens=available_tokens,
        has_geometry_support=has_geometry_support,
        provided_artifact_ids=provided_ids,
        task_type=task_type,
        parameter_locks=parameter_locks,
        input_completion_overrides=normalized_completion_overrides,
    )

    if action.artifact_key and action.artifact_key in artifact_by_id:
        return _build_already_provided_affordance(action, artifact_by_id[action.artifact_key], available_conditions)

    for conflict in action.provided_conflicts:
        if conflict in provided_ids:
            artifact = artifact_by_id.get(conflict)
            if artifact is None:
                artifact = AlreadyProvidedArtifact(
                    artifact_id=conflict,
                    display_name=action.display_name,
                    message="本次回复已经提供了对应交付物。",
                    kind="provided_conflict",
                )
            return _build_already_provided_affordance(action, artifact, available_conditions)

    if has_grounded_file_context and action.required_task_types and task_type not in set(action.required_task_types):
        reason = _build_task_type_reason(action, task_type)
        return ActionAffordance(
            action_id=action.action_id,
            status=ReadinessStatus.BLOCKED,
            display_name=action.display_name,
            description=action.description,
            tool_name=action.tool_name,
            arguments=dict(action.arguments),
            reason=reason,
            required_conditions=[f"task_type:{item}" for item in action.required_task_types],
            available_conditions=available_conditions,
            alternative_actions=list(action.alternative_action_ids),
            guidance_utterance=action.guidance_utterance,
            guidance_enabled=action.guidance_enabled,
        )

    if action.required_result_tokens:
        missing_tokens = [
            token for token in action.required_result_tokens
            if token not in available_tokens
        ]
        if missing_tokens:
            reason = _build_required_result_reason(missing_tokens)
            return ActionAffordance(
                action_id=action.action_id,
                status=ReadinessStatus.BLOCKED,
                display_name=action.display_name,
                description=action.description,
                tool_name=action.tool_name,
                arguments=dict(action.arguments),
                reason=reason,
                required_conditions=[f"result:{item}" for item in action.required_result_tokens],
                available_conditions=available_conditions,
                alternative_actions=list(action.alternative_action_ids),
                guidance_utterance=action.guidance_utterance,
                guidance_enabled=action.guidance_enabled,
            )

    if (
        has_grounded_file_context
        and action.action_id == "run_macro_emission"
        and isinstance(diagnostics, dict)
        and task_type == "macro_emission"
    ):
        adjusted_diagnostics = dict(diagnostics)
        field_statuses = []
        for item in (diagnostics.get("required_field_statuses") or []):
            if not isinstance(item, dict):
                continue
            field_name = str(item.get("field") or "").strip()
            if (
                field_name
                and str(item.get("status") or "").strip().lower() != "present"
                and _missing_field_resolved_by_override(field_name, normalized_completion_overrides)
            ):
                patched = dict(item)
                patched["status"] = "present"
                patched["mapped_from"] = patched.get("mapped_from") or "input_completion_override"
                patched["reason"] = "Resolved by bounded input completion override."
                field_statuses.append(patched)
                continue
            field_statuses.append(item)
        adjusted_diagnostics["required_field_statuses"] = field_statuses
        adjusted_diagnostics["missing_fields"] = [
            item
            for item in field_statuses
            if str(item.get("status") or "").strip().lower() != "present"
        ]
        reason = _build_missing_field_reason(expected_task_type="macro_emission", diagnostics=adjusted_diagnostics)
        if reason is not None:
            return ActionAffordance(
                action_id=action.action_id,
                status=ReadinessStatus.REPAIRABLE,
                display_name=action.display_name,
                description=action.description,
                tool_name=action.tool_name,
                arguments=dict(action.arguments),
                reason=reason,
                required_conditions=[f"field:{item}" for item in diagnostics.get("required_fields", [])],
                available_conditions=available_conditions,
                alternative_actions=list(action.alternative_action_ids),
                guidance_utterance=action.guidance_utterance,
                guidance_enabled=action.guidance_enabled,
            )

    if (
        has_grounded_file_context
        and action.action_id == "run_micro_emission"
        and isinstance(diagnostics, dict)
        and task_type == "micro_emission"
    ):
        adjusted_diagnostics = dict(diagnostics)
        field_statuses = []
        for item in (diagnostics.get("required_field_statuses") or []):
            if not isinstance(item, dict):
                continue
            field_name = str(item.get("field") or "").strip()
            if (
                field_name
                and str(item.get("status") or "").strip().lower() != "present"
                and _missing_field_resolved_by_override(field_name, normalized_completion_overrides)
            ):
                patched = dict(item)
                patched["status"] = "present"
                patched["mapped_from"] = patched.get("mapped_from") or "input_completion_override"
                patched["reason"] = "Resolved by bounded input completion override."
                field_statuses.append(patched)
                continue
            field_statuses.append(item)
        adjusted_diagnostics["required_field_statuses"] = field_statuses
        adjusted_diagnostics["missing_fields"] = [
            item
            for item in field_statuses
            if str(item.get("status") or "").strip().lower() != "present"
        ]
        reason = _build_missing_field_reason(expected_task_type="micro_emission", diagnostics=adjusted_diagnostics)
        if reason is not None:
            return ActionAffordance(
                action_id=action.action_id,
                status=ReadinessStatus.REPAIRABLE,
                display_name=action.display_name,
                description=action.description,
                tool_name=action.tool_name,
                arguments=dict(action.arguments),
                reason=reason,
                required_conditions=[f"field:{item}" for item in diagnostics.get("required_fields", [])],
                available_conditions=available_conditions,
                alternative_actions=list(action.alternative_action_ids),
                guidance_utterance=action.guidance_utterance,
                guidance_enabled=action.guidance_enabled,
            )

    if action.action_id == "compare_scenario":
        scenario_count = _count_scenarios(context_store)
        if scenario_count < 2:
            reason = BlockedReason(
                reason_code="missing_scenarios",
                message="当前可比较的情景数量不足，暂时不能执行情景对比。",
                missing_requirements=["at_least_two_scenarios"],
                repair_hint=_REASON_HINTS["missing_scenarios"],
                severity="warning",
                details={"scenario_count": scenario_count},
            )
            return ActionAffordance(
                action_id=action.action_id,
                status=ReadinessStatus.REPAIRABLE,
                display_name=action.display_name,
                description=action.description,
                tool_name=action.tool_name,
                arguments=dict(action.arguments),
                reason=reason,
                required_conditions=["scenario_count>=2"],
                available_conditions=available_conditions,
                alternative_actions=list(action.alternative_action_ids),
                guidance_utterance=action.guidance_utterance,
                guidance_enabled=action.guidance_enabled,
            )

    if action.tool_name:
        validation = validate_tool_prerequisites(
            action.tool_name,
            arguments=dict(action.arguments),
            available_tokens=available_tokens,
            context_store=context_store,
            include_stale=False,
        )
        if not validation.is_valid:
            reason = _build_dependency_reason(action.tool_name, validation)
            return ActionAffordance(
                action_id=action.action_id,
                status=ReadinessStatus.REPAIRABLE,
                display_name=action.display_name,
                description=action.description,
                tool_name=action.tool_name,
                arguments=dict(action.arguments),
                reason=reason,
                required_conditions=[f"result:{item}" for item in validation.required_tokens],
                available_conditions=available_conditions,
                alternative_actions=list(action.alternative_action_ids),
                guidance_utterance=action.guidance_utterance,
                guidance_enabled=action.guidance_enabled,
            )

    # Phase 7.6E: auto-discover geometry FileContext from stored analyzed files
    # when emission is join_key_only and no explicit geometry_file_context provided.
    _effective_geo_fc: Optional[Dict[str, Any]] = geometry_file_context
    _discovery_diagnostic: Optional[Dict[str, Any]] = None
    if _effective_geo_fc is None and context_store is not None:
        gm = dict(file_context.get("geometry_metadata") or {})
        if str(gm.get("geometry_type", "")).strip().lower() == "join_key_only":
            geo_candidates = context_store.find_geometry_file_contexts()
            if geo_candidates:
                from core.spatial_emission_resolver import find_best_geometry_file_context
                _discovery = find_best_geometry_file_context(
                    emission_file_context=file_context,
                    candidate_geometry_contexts=geo_candidates,
                )
                if _discovery.get("selected"):
                    _effective_geo_fc = _discovery["geometry_file_context"]
                else:
                    # Store diagnostic for surfacing when auto-select fails
                    _discovery_diagnostic = dict(_discovery)

    # Phase 7.5/7.6D/7.6E: build spatial emission layer from upstream macro result.
    spatial_layer = _build_spatial_emission_layer_from_results(
        file_context=file_context,
        current_tool_results=current_tool_results,
        geometry_file_context=_effective_geo_fc,
    )

    # Phase 7.4B/7.5/7.6D/7.6E: spatial emission precondition.
    spatial_precondition = resolve_spatial_precondition(
        tool_name=action.tool_name,
        file_context=file_context,
        emission_result_ref=None,
        spatial_emission_layer=spatial_layer,
        geometry_file_context=_effective_geo_fc,
    )
    if spatial_precondition.get("candidate_dict"):
        available_conditions.append("spatial_emission_candidate")
    if spatial_precondition.get("layer_dict"):
        available_conditions.append("spatial_emission_layer_available")

    # Phase 7.6D/7.6E: when geometry support comes from a join-key geometry file
    # (explicit or auto-discovered) but the resolver rejected or needs confirmation,
    # surface the resolver's diagnostic.  Also surface auto-discovery diagnostics
    # when candidates were found but none could be auto-selected.
    _join_key_geo_needs_diagnostic = (
        _geometry_source == "join_key_geometry_file_context"
        or _effective_geo_fc is not None
        or _discovery_diagnostic is not None
    ) and not spatial_precondition["satisfied"]

    if (
        not spatial_precondition["satisfied"]
        and (
            (action.requires_geometry_support and not has_geometry_support)
            or _join_key_geo_needs_diagnostic
        )
    ):
        # Phase 7.6E: prefer auto-discovery diagnostic over generic join_key_without_geometry
        _reason_code = spatial_precondition["reason_code"]
        _reason_msg = spatial_precondition["message"]
        if (
            _discovery_diagnostic is not None
            and _reason_code in ("join_key_without_geometry", "no_road_geometry_requirement")
        ):
            _reason_code = _discovery_diagnostic.get("reason_code", _reason_code)
            _reason_msg = _discovery_diagnostic.get("message", _reason_msg)

        if not spatial_precondition["satisfied"] and _reason_code != "no_road_geometry_requirement":
            reason = _build_spatial_emission_reason(
                reason_code=_reason_code,
                message=_reason_msg,
            )
        else:
            reason = _build_geometry_reason()
        return ActionAffordance(
            action_id=action.action_id,
            status=ReadinessStatus.REPAIRABLE,
            display_name=action.display_name,
            description=action.description,
            tool_name=action.tool_name,
            arguments=dict(action.arguments),
            reason=reason,
            required_conditions=["geometry_support"],
            available_conditions=available_conditions,
            alternative_actions=list(action.alternative_action_ids),
            guidance_utterance=action.guidance_utterance,
            guidance_enabled=action.guidance_enabled,
        )

    if action.requires_spatial_result_token and not _result_has_spatial_payload(
        action.requires_spatial_result_token,
        result_payloads.get(action.requires_spatial_result_token),
    ):
        reason = _build_spatial_payload_reason(action.requires_spatial_result_token)
        return ActionAffordance(
            action_id=action.action_id,
            status=ReadinessStatus.REPAIRABLE,
            display_name=action.display_name,
            description=action.description,
            tool_name=action.tool_name,
            arguments=dict(action.arguments),
            reason=reason,
            required_conditions=[f"{action.requires_spatial_result_token}_spatial_payload"],
            available_conditions=available_conditions,
            alternative_actions=list(action.alternative_action_ids),
            guidance_utterance=action.guidance_utterance,
            guidance_enabled=action.guidance_enabled,
        )

    preflight_reason = _run_tool_preflight_check(
        action.tool_name,
        parameter_locks,
        normalized_completion_overrides,
    )
    if preflight_reason is not None:
        return ActionAffordance(
            action_id=action.action_id,
            status=ReadinessStatus.BLOCKED,
            display_name=action.display_name,
            description=action.description,
            tool_name=action.tool_name,
            arguments=dict(action.arguments),
            reason=preflight_reason,
            required_conditions=[
                f"asset:{req}" for req in (preflight_reason.missing_requirements or [])
            ],
            available_conditions=available_conditions,
            alternative_actions=list(action.alternative_action_ids),
            guidance_utterance=action.guidance_utterance,
            guidance_enabled=action.guidance_enabled,
        )

    return ActionAffordance(
        action_id=action.action_id,
        status=ReadinessStatus.READY,
        display_name=action.display_name,
        description=action.description,
        tool_name=action.tool_name,
        arguments=dict(action.arguments),
        required_conditions=[],
        available_conditions=available_conditions,
        alternative_actions=list(action.alternative_action_ids),
        guidance_utterance=action.guidance_utterance,
        guidance_enabled=action.guidance_enabled,
    )


def build_readiness_assessment(
    file_context: Optional[Dict[str, Any]],
    context_store: Optional["SessionContextStore"],
    current_tool_results: Sequence[Dict[str, Any]],
    current_response_payloads: Optional[Dict[str, Any]] = None,
    parameter_locks: Optional[Dict[str, Any]] = None,
    input_completion_overrides: Optional[Dict[str, Any]] = None,
    already_provided_dedup_enabled: bool = True,
    artifact_memory_state: Optional[ArtifactMemoryState] = None,
    geometry_file_context: Optional[Dict[str, Any]] = None,
) -> ReadinessAssessment:
    normalized_file_context = _coerce_file_context(file_context)
    catalog = get_action_catalog()
    result_payloads = _collect_result_payloads(current_tool_results, context_store)
    available_tokens = set(_collect_available_tokens(current_tool_results, context_store))
    if already_provided_dedup_enabled:
        already_provided, provided_ids = _collect_already_provided_artifacts(
            current_response_payloads,
            current_tool_results,
            artifact_memory_state=artifact_memory_state,
        )
    else:
        already_provided, provided_ids = [], set()
    has_geometry_support, geometry_source = _determine_geometry_support(
        normalized_file_context,
        result_payloads,
        geometry_file_context=geometry_file_context,
    )

    assessment = ReadinessAssessment(
        summary_notes=[],
        key_signals={
            "task_type": normalized_file_context.get("task_type"),
            "has_geometry_support": has_geometry_support,
            "geometry_support_source": geometry_source,
            "available_result_tokens": sorted(available_tokens),
            "provided_artifact_ids": sorted(provided_ids),
            "missing_field_status": (
                (normalized_file_context.get("missing_field_diagnostics") or {}).get("status")
                if isinstance(normalized_file_context.get("missing_field_diagnostics"), dict)
                else None
            ),
            "selected_primary_table": normalized_file_context.get("selected_primary_table"),
            "dataset_role_count": len(normalized_file_context.get("dataset_roles") or []),
            "parameter_locks": sorted((parameter_locks or {}).keys()),
            "input_completion_overrides": sorted((input_completion_overrides or {}).keys()),
        },
        catalog=catalog,
    )

    for entry in catalog:
        affordance = assess_action_readiness(
            entry,
            file_context=normalized_file_context,
            context_store=context_store,
            current_tool_results=current_tool_results,
            current_response_payloads=current_response_payloads,
            parameter_locks=parameter_locks,
            input_completion_overrides=input_completion_overrides,
            already_provided_dedup_enabled=already_provided_dedup_enabled,
            artifact_memory_state=artifact_memory_state,
            geometry_file_context=geometry_file_context,
        )
        if affordance.status == ReadinessStatus.READY:
            assessment.available_actions.append(affordance)
        elif affordance.status == ReadinessStatus.BLOCKED:
            assessment.blocked_actions.append(affordance)
        elif affordance.status == ReadinessStatus.REPAIRABLE:
            assessment.repairable_actions.append(affordance)
        else:
            assessment.already_provided_actions.append(affordance)

    if any(
        item.reason is not None and item.reason.reason_code == "missing_geometry"
        for item in assessment.repairable_actions + assessment.blocked_actions
    ):
        assessment.summary_notes.append(_REASON_HINTS["missing_geometry"])

    diagnostics = normalized_file_context.get("missing_field_diagnostics") or {}
    if isinstance(diagnostics, dict) and diagnostics.get("status") in {"partial", "insufficient"}:
        assessment.summary_notes.append("当前文件关键字段仍不完整，部分分析动作只能视为 repairable，不能直接执行。")

    return assessment


def build_action_blocked_response(
    affordance: ActionAffordance,
    assessment: ReadinessAssessment,
) -> str:
    reason = affordance.reason
    alternatives = [
        item.display_name
        for item in assessment.available_actions
        if item.action_id != affordance.action_id and item.guidance_enabled and item.tool_name
    ][:3]
    lines = [f"当前不能执行“{affordance.display_name}”。"]
    if reason is not None:
        lines.append(f"原因：{reason.message}")
        if reason.missing_requirements:
            lines.append(f"受限条件：{'、'.join(reason.missing_requirements)}")
    if alternatives:
        lines.append(f"当前可直接继续的动作：{'、'.join(alternatives)}。")
    else:
        lines.append("当前没有额外的安全替代动作可直接继续。")
    return "\n".join(lines)


def build_action_repairable_response(
    affordance: ActionAffordance,
    assessment: ReadinessAssessment,
) -> str:
    reason = affordance.reason
    alternatives = [
        item.display_name
        for item in assessment.available_actions
        if item.action_id != affordance.action_id and item.guidance_enabled and item.tool_name
    ][:3]
    lines = [f"当前还不能直接执行“{affordance.display_name}”。"]
    if reason is not None:
        lines.append(f"原因：{reason.message}")
        if reason.missing_requirements:
            lines.append(f"缺失条件：{'、'.join(reason.missing_requirements)}")
        if reason.repair_hint:
            lines.append(f"补救方向：{reason.repair_hint}")
    if alternatives:
        lines.append(f"当前可先执行的动作：{'、'.join(alternatives)}。")
    else:
        lines.append("当前没有其他额外的安全后续动作可以直接继续。")
    return "\n".join(lines)


def build_action_already_provided_response(
    affordance: ActionAffordance,
    assessment: ReadinessAssessment,
) -> str:
    artifact = affordance.provided_artifact
    alternatives = [
        item.display_name
        for item in assessment.available_actions
        if item.action_id != affordance.action_id and item.guidance_enabled and item.tool_name
    ][:3]
    display_name = artifact.display_name if artifact is not None else affordance.display_name
    message = artifact.message if artifact is not None else "本次回复已经提供了对应交付物。"
    lines = [f"“{display_name}”本轮已经提供过，不需要重复执行或重复建议。", f"说明：{message}"]
    if alternatives:
        lines.append(f"如果继续分析，可考虑：{'、'.join(alternatives)}。")
    return "\n".join(lines)
