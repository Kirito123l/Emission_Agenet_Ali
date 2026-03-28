from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence

from core.intent_resolution import IntentResolutionApplicationPlan


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _clean_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    cleaned: List[str] = []
    for item in values:
        text = _clean_text(item)
        if text:
            cleaned.append(text)
    return cleaned


class ArtifactType(str, Enum):
    DETAILED_CSV = "detailed_csv"
    TOPK_SUMMARY_TABLE = "topk_summary_table"
    RANKED_CHART = "ranked_chart"
    SPATIAL_MAP = "spatial_map"
    DISPERSION_MAP = "dispersion_map"
    HOTSPOT_MAP = "hotspot_map"
    QUICK_SUMMARY_TEXT = "quick_summary_text"
    COMPARISON_RESULT = "comparison_result"
    UNKNOWN = "unknown"


class ArtifactFamily(str, Enum):
    DOWNLOADABLE_TABLE = "downloadable_table"
    RANKED_SUMMARY = "ranked_summary"
    SPATIAL_VISUALIZATION = "spatial_visualization"
    TEXTUAL_SUMMARY = "textual_summary"
    COMPARISON_OUTPUT = "comparison_output"


class ArtifactDeliveryStatus(str, Enum):
    FULL = "full"
    PARTIAL = "partial"


_ARTIFACT_FAMILY_BY_TYPE: Dict[ArtifactType, ArtifactFamily] = {
    ArtifactType.DETAILED_CSV: ArtifactFamily.DOWNLOADABLE_TABLE,
    ArtifactType.TOPK_SUMMARY_TABLE: ArtifactFamily.RANKED_SUMMARY,
    ArtifactType.RANKED_CHART: ArtifactFamily.RANKED_SUMMARY,
    ArtifactType.SPATIAL_MAP: ArtifactFamily.SPATIAL_VISUALIZATION,
    ArtifactType.DISPERSION_MAP: ArtifactFamily.SPATIAL_VISUALIZATION,
    ArtifactType.HOTSPOT_MAP: ArtifactFamily.SPATIAL_VISUALIZATION,
    ArtifactType.QUICK_SUMMARY_TEXT: ArtifactFamily.TEXTUAL_SUMMARY,
    ArtifactType.COMPARISON_RESULT: ArtifactFamily.COMPARISON_OUTPUT,
    ArtifactType.UNKNOWN: ArtifactFamily.TEXTUAL_SUMMARY,
}


_ACTION_ARTIFACT_TYPE_MAP: Dict[str, ArtifactType] = {
    "download_detailed_csv": ArtifactType.DETAILED_CSV,
    "download_topk_summary": ArtifactType.TOPK_SUMMARY_TABLE,
    "render_rank_chart": ArtifactType.RANKED_CHART,
    "deliver_quick_structured_summary": ArtifactType.QUICK_SUMMARY_TEXT,
    "render_emission_map": ArtifactType.SPATIAL_MAP,
    "render_dispersion_map": ArtifactType.DISPERSION_MAP,
    "render_hotspot_map": ArtifactType.HOTSPOT_MAP,
    "compare_scenario": ArtifactType.COMPARISON_RESULT,
}


_DEFAULT_ACTION_BY_TYPE: Dict[ArtifactType, str] = {
    ArtifactType.DETAILED_CSV: "download_detailed_csv",
    ArtifactType.TOPK_SUMMARY_TABLE: "download_topk_summary",
    ArtifactType.RANKED_CHART: "render_rank_chart",
    ArtifactType.QUICK_SUMMARY_TEXT: "deliver_quick_structured_summary",
    ArtifactType.SPATIAL_MAP: "render_emission_map",
    ArtifactType.DISPERSION_MAP: "render_dispersion_map",
    ArtifactType.HOTSPOT_MAP: "render_hotspot_map",
    ArtifactType.COMPARISON_RESULT: "compare_scenario",
}


_ARTIFACT_KIND_BY_TYPE: Dict[ArtifactType, str] = {
    ArtifactType.DETAILED_CSV: "download",
    ArtifactType.TOPK_SUMMARY_TABLE: "table",
    ArtifactType.RANKED_CHART: "chart",
    ArtifactType.SPATIAL_MAP: "map",
    ArtifactType.DISPERSION_MAP: "map",
    ArtifactType.HOTSPOT_MAP: "map",
    ArtifactType.QUICK_SUMMARY_TEXT: "summary",
    ArtifactType.COMPARISON_RESULT: "comparison",
}


def artifact_family_for_type(artifact_type: ArtifactType) -> ArtifactFamily:
    return _ARTIFACT_FAMILY_BY_TYPE.get(artifact_type, ArtifactFamily.TEXTUAL_SUMMARY)


def artifact_type_for_action_id(action_id: Optional[str]) -> Optional[ArtifactType]:
    action_text = _clean_text(action_id)
    if not action_text:
        return None
    return _ACTION_ARTIFACT_TYPE_MAP.get(action_text)


@dataclass
class ArtifactRecord:
    artifact_id: str
    artifact_type: ArtifactType
    artifact_family: ArtifactFamily
    source_action_id: Optional[str] = None
    source_tool_name: Optional[str] = None
    delivery_turn_index: int = 0
    delivery_status: ArtifactDeliveryStatus = ArtifactDeliveryStatus.FULL
    file_ref: Optional[str] = None
    download_ref: Optional[Dict[str, Any]] = None
    summary: Optional[str] = None
    related_task_type: Optional[str] = None
    related_pollutant: Optional[str] = None
    related_scope: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "ArtifactRecord":
        data = payload if isinstance(payload, dict) else {}
        artifact_type_value = data.get("artifact_type") or ArtifactType.UNKNOWN.value
        artifact_family_value = data.get("artifact_family") or ArtifactFamily.TEXTUAL_SUMMARY.value
        delivery_status_value = data.get("delivery_status") or ArtifactDeliveryStatus.FULL.value
        try:
            artifact_type = ArtifactType(str(artifact_type_value).strip())
        except ValueError:
            artifact_type = ArtifactType.UNKNOWN
        try:
            artifact_family = ArtifactFamily(str(artifact_family_value).strip())
        except ValueError:
            artifact_family = artifact_family_for_type(artifact_type)
        try:
            delivery_status = ArtifactDeliveryStatus(str(delivery_status_value).strip())
        except ValueError:
            delivery_status = ArtifactDeliveryStatus.FULL
        return cls(
            artifact_id=_clean_text(data.get("artifact_id")) or "artifact",
            artifact_type=artifact_type,
            artifact_family=artifact_family,
            source_action_id=_clean_text(data.get("source_action_id")),
            source_tool_name=_clean_text(data.get("source_tool_name")),
            delivery_turn_index=int(data.get("delivery_turn_index") or 0),
            delivery_status=delivery_status,
            file_ref=_clean_text(data.get("file_ref")),
            download_ref=_clean_dict(data.get("download_ref")) or None,
            summary=_clean_text(data.get("summary")),
            related_task_type=_clean_text(data.get("related_task_type")),
            related_pollutant=_clean_text(data.get("related_pollutant")),
            related_scope=_clean_text(data.get("related_scope")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type.value,
            "artifact_family": self.artifact_family.value,
            "source_action_id": self.source_action_id,
            "source_tool_name": self.source_tool_name,
            "delivery_turn_index": self.delivery_turn_index,
            "delivery_status": self.delivery_status.value,
            "file_ref": self.file_ref,
            "download_ref": dict(self.download_ref or {}),
            "summary": self.summary,
            "related_task_type": self.related_task_type,
            "related_pollutant": self.related_pollutant,
            "related_scope": self.related_scope,
        }

    def to_summary(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type.value,
            "artifact_family": self.artifact_family.value,
            "delivery_status": self.delivery_status.value,
            "source_action_id": self.source_action_id,
            "source_tool_name": self.source_tool_name,
            "summary": self.summary,
            "related_scope": self.related_scope,
            "related_task_type": self.related_task_type,
        }


@dataclass
class ArtifactMemoryState:
    artifacts: List[ArtifactRecord] = field(default_factory=list)
    latest_by_family: Dict[str, ArtifactRecord] = field(default_factory=dict)
    latest_by_type: Dict[str, ArtifactRecord] = field(default_factory=dict)
    recent_artifact_summary: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "ArtifactMemoryState":
        data = payload if isinstance(payload, dict) else {}
        state = cls(
            artifacts=[
                ArtifactRecord.from_dict(item)
                for item in (data.get("artifacts") or [])
                if isinstance(item, dict)
            ]
        )
        state.refresh_indexes()
        if isinstance(data.get("recent_artifact_summary"), list):
            state.recent_artifact_summary = [
                dict(item)
                for item in data.get("recent_artifact_summary")
                if isinstance(item, dict)
            ]
        return state

    def refresh_indexes(self) -> "ArtifactMemoryState":
        latest_by_family: Dict[str, ArtifactRecord] = {}
        latest_by_type: Dict[str, ArtifactRecord] = {}
        ordered = sorted(
            self.artifacts,
            key=lambda item: (item.delivery_turn_index, item.artifact_id),
        )
        for record in ordered:
            latest_by_family[record.artifact_family.value] = record
            latest_by_type[record.artifact_type.value] = record
        self.latest_by_family = latest_by_family
        self.latest_by_type = latest_by_type
        summary_records = sorted(
            self.artifacts,
            key=lambda item: (item.delivery_turn_index, item.artifact_id),
            reverse=True,
        )
        self.recent_artifact_summary = [item.to_summary() for item in summary_records[:8]]
        return self

    def append(self, records: Sequence[ArtifactRecord]) -> "ArtifactMemoryState":
        if not records:
            return self
        self.artifacts.extend(records)
        self.refresh_indexes()
        return self

    def clone(self) -> "ArtifactMemoryState":
        return ArtifactMemoryState.from_dict(self.to_dict())

    def find_latest_type(
        self,
        artifact_type: ArtifactType,
        *,
        status: Optional[ArtifactDeliveryStatus] = None,
    ) -> Optional[ArtifactRecord]:
        candidates = [
            item
            for item in self.artifacts
            if item.artifact_type == artifact_type
            and (status is None or item.delivery_status == status)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item.delivery_turn_index, item.artifact_id))

    def find_latest_family(
        self,
        artifact_family: ArtifactFamily,
        *,
        status: Optional[ArtifactDeliveryStatus] = None,
    ) -> Optional[ArtifactRecord]:
        candidates = [
            item
            for item in self.artifacts
            if item.artifact_family == artifact_family
            and (status is None or item.delivery_status == status)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item.delivery_turn_index, item.artifact_id))

    def to_summary(self) -> Dict[str, Any]:
        return {
            "artifact_count": len(self.artifacts),
            "latest_by_family": {
                key: value.to_summary()
                for key, value in self.latest_by_family.items()
            },
            "latest_by_type": {
                key: value.to_summary()
                for key, value in self.latest_by_type.items()
            },
            "recent_artifact_summary": [dict(item) for item in self.recent_artifact_summary],
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifacts": [item.to_dict() for item in self.artifacts],
            "latest_by_family": {
                key: value.to_dict()
                for key, value in self.latest_by_family.items()
            },
            "latest_by_type": {
                key: value.to_dict()
                for key, value in self.latest_by_type.items()
            },
            "recent_artifact_summary": [dict(item) for item in self.recent_artifact_summary],
        }


@dataclass
class ArtifactAvailabilityDecision:
    requested_type: Optional[ArtifactType] = None
    requested_family: Optional[ArtifactFamily] = None
    same_type_full_provided: bool = False
    same_family_full_provided: bool = False
    matching_record: Optional[ArtifactRecord] = None
    family_record: Optional[ArtifactRecord] = None
    should_suppress_repeat: bool = False
    should_promote_new_family: bool = False
    explanation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requested_type": self.requested_type.value if self.requested_type is not None else None,
            "requested_family": self.requested_family.value if self.requested_family is not None else None,
            "same_type_full_provided": self.same_type_full_provided,
            "same_family_full_provided": self.same_family_full_provided,
            "matching_record": self.matching_record.to_dict() if self.matching_record is not None else None,
            "family_record": self.family_record.to_dict() if self.family_record is not None else None,
            "should_suppress_repeat": self.should_suppress_repeat,
            "should_promote_new_family": self.should_promote_new_family,
            "explanation": self.explanation,
        }


@dataclass
class ArtifactSuggestionPlan:
    suppressed_action_ids: List[str] = field(default_factory=list)
    promoted_action_ids: List[str] = field(default_factory=list)
    promoted_families: List[str] = field(default_factory=list)
    repeated_artifact_types: List[str] = field(default_factory=list)
    repeated_artifact_families: List[str] = field(default_factory=list)
    user_visible_summary: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    availability_decision: Optional[ArtifactAvailabilityDecision] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "suppressed_action_ids": list(self.suppressed_action_ids),
            "promoted_action_ids": list(self.promoted_action_ids),
            "promoted_families": list(self.promoted_families),
            "repeated_artifact_types": list(self.repeated_artifact_types),
            "repeated_artifact_families": list(self.repeated_artifact_families),
            "user_visible_summary": self.user_visible_summary,
            "notes": list(self.notes),
            "availability_decision": (
                self.availability_decision.to_dict()
                if self.availability_decision is not None
                else None
            ),
        }


def coerce_artifact_memory_state(payload: Any) -> ArtifactMemoryState:
    if isinstance(payload, ArtifactMemoryState):
        return payload.clone()
    if isinstance(payload, dict):
        return ArtifactMemoryState.from_dict(payload)
    return ArtifactMemoryState()


def build_artifact_record(
    *,
    artifact_type: ArtifactType,
    delivery_turn_index: int,
    source_tool_name: Optional[str] = None,
    source_action_id: Optional[str] = None,
    delivery_status: ArtifactDeliveryStatus = ArtifactDeliveryStatus.FULL,
    file_ref: Optional[str] = None,
    download_ref: Optional[Dict[str, Any]] = None,
    summary: Optional[str] = None,
    related_task_type: Optional[str] = None,
    related_pollutant: Optional[str] = None,
    related_scope: Optional[str] = None,
) -> ArtifactRecord:
    normalized_source_action = source_action_id or _DEFAULT_ACTION_BY_TYPE.get(artifact_type)
    family = artifact_family_for_type(artifact_type)
    artifact_id = f"{artifact_type.value}:{delivery_turn_index}:{normalized_source_action or source_tool_name or 'artifact'}"
    return ArtifactRecord(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        artifact_family=family,
        source_action_id=normalized_source_action,
        source_tool_name=source_tool_name,
        delivery_turn_index=delivery_turn_index,
        delivery_status=delivery_status,
        file_ref=file_ref,
        download_ref=dict(download_ref or {}) or None,
        summary=summary,
        related_task_type=related_task_type,
        related_pollutant=related_pollutant,
        related_scope=related_scope,
    )


def _extract_first_pollutant(tool_results: Sequence[Dict[str, Any]]) -> Optional[str]:
    for item in tool_results:
        if not isinstance(item, dict):
            continue
        arguments = item.get("arguments") or {}
        if isinstance(arguments, dict):
            pollutant = _clean_text(arguments.get("pollutant"))
            if pollutant:
                return pollutant
            pollutants = arguments.get("pollutants")
            if isinstance(pollutants, list) and pollutants:
                pollutant = _clean_text(pollutants[0])
                if pollutant:
                    return pollutant
        result = item.get("result") or {}
        data = result.get("data") if isinstance(result, dict) else {}
        query_info = data.get("query_info") if isinstance(data, dict) else {}
        if isinstance(query_info, dict):
            pollutant = _clean_text(query_info.get("pollutant"))
            if pollutant:
                return pollutant
            pollutants = query_info.get("pollutants")
            if isinstance(pollutants, list) and pollutants:
                pollutant = _clean_text(pollutants[0])
                if pollutant:
                    return pollutant
    return None


def _classify_download_artifact(download_payload: Any) -> tuple[ArtifactType, Optional[str], Optional[str], Optional[str]]:
    payload = _clean_dict(download_payload)
    filename = _clean_text(payload.get("filename") or payload.get("path"))
    filename_lower = str(filename or "").lower()
    if "top" in filename_lower or "summary" in filename_lower or "rank" in filename_lower:
        return ArtifactType.TOPK_SUMMARY_TABLE, filename, "topk", "已提供可下载的摘要/Top-K 结果文件。"
    return ArtifactType.DETAILED_CSV, filename, "full_table", "已提供可下载的详细结果文件。"


def _classify_table_artifact(
    table_payload: Any,
    *,
    source_tool_name: Optional[str],
) -> tuple[ArtifactType, Optional[str], Optional[str]]:
    payload = _clean_dict(table_payload)
    payload_type = str(payload.get("type") or "").strip().lower()
    if any(token in payload_type for token in ("top", "rank", "summary", "hotspot")):
        return ArtifactType.TOPK_SUMMARY_TABLE, "topk", "已提供摘要表或 Top-K 结果表。"
    if source_tool_name in {"analyze_hotspots", "compare_scenarios"}:
        return ArtifactType.TOPK_SUMMARY_TABLE, "topk", "已提供摘要表或 Top-K 结果表。"
    return ArtifactType.UNKNOWN, None, None


def _iter_map_payloads(map_payload: Any) -> Iterable[Dict[str, Any]]:
    if not isinstance(map_payload, dict) or not map_payload:
        return []
    if map_payload.get("type") == "map_collection" and isinstance(map_payload.get("items"), list):
        return [dict(item) for item in map_payload.get("items") if isinstance(item, dict)]
    return [dict(map_payload)]


def _classify_map_artifact(map_payload: Dict[str, Any]) -> tuple[ArtifactType, Optional[str]]:
    map_type = str(map_payload.get("type") or "").strip().lower()
    if map_type in {"macro_emission_map", "emission"}:
        return ArtifactType.SPATIAL_MAP, "已提供排放空间地图。"
    if map_type in {"raster", "concentration", "points", "dispersion"}:
        return ArtifactType.DISPERSION_MAP, "已提供扩散浓度空间地图。"
    if map_type == "hotspot":
        return ArtifactType.HOTSPOT_MAP, "已提供热点空间地图。"
    return ArtifactType.UNKNOWN, None


def _dedupe_records(records: Sequence[ArtifactRecord]) -> List[ArtifactRecord]:
    deduped: Dict[tuple[str, str, str, str], ArtifactRecord] = {}
    for record in records:
        key = (
            record.artifact_type.value,
            record.artifact_family.value,
            record.source_tool_name or "",
            record.related_scope or "",
        )
        deduped[key] = record
    return list(deduped.values())


def classify_artifacts_from_delivery(
    *,
    tool_results: Sequence[Dict[str, Any]],
    frontend_payloads: Optional[Dict[str, Any]],
    response_text: Optional[str],
    delivery_turn_index: int,
    related_task_type: Optional[str],
    track_textual_summary: bool = True,
) -> List[ArtifactRecord]:
    payloads = dict(frontend_payloads or {})
    related_pollutant = _extract_first_pollutant(tool_results)
    records: List[ArtifactRecord] = []
    source_tool_name = _clean_text(tool_results[-1].get("name")) if tool_results else None

    download_payload = payloads.get("download_file")
    if download_payload:
        artifact_type, file_ref, scope, summary = _classify_download_artifact(download_payload)
        records.append(
            build_artifact_record(
                artifact_type=artifact_type,
                delivery_turn_index=delivery_turn_index,
                source_tool_name=source_tool_name,
                delivery_status=ArtifactDeliveryStatus.FULL,
                file_ref=file_ref,
                download_ref=_clean_dict(download_payload) or None,
                summary=summary,
                related_task_type=related_task_type,
                related_pollutant=related_pollutant,
                related_scope=scope,
            )
        )

    table_payload = payloads.get("table_data")
    if table_payload:
        table_type, scope, summary = _classify_table_artifact(
            table_payload,
            source_tool_name=source_tool_name,
        )
        if table_type != ArtifactType.UNKNOWN:
            records.append(
                build_artifact_record(
                    artifact_type=table_type,
                    delivery_turn_index=delivery_turn_index,
                    source_tool_name=source_tool_name,
                    delivery_status=ArtifactDeliveryStatus.PARTIAL,
                    summary=summary,
                    related_task_type=related_task_type,
                    related_pollutant=related_pollutant,
                    related_scope=scope,
                )
            )

    chart_payload = payloads.get("chart_data")
    if isinstance(chart_payload, dict) and chart_payload:
        records.append(
            build_artifact_record(
                artifact_type=ArtifactType.RANKED_CHART,
                delivery_turn_index=delivery_turn_index,
                source_tool_name=source_tool_name,
                delivery_status=ArtifactDeliveryStatus.FULL,
                summary="已提供结果图表。",
                related_task_type=related_task_type,
                related_pollutant=related_pollutant,
            )
        )

    for map_item in _iter_map_payloads(payloads.get("map_data")):
        artifact_type, summary = _classify_map_artifact(map_item)
        if artifact_type == ArtifactType.UNKNOWN:
            continue
        records.append(
            build_artifact_record(
                artifact_type=artifact_type,
                delivery_turn_index=delivery_turn_index,
                source_tool_name="render_spatial_map",
                delivery_status=ArtifactDeliveryStatus.FULL,
                summary=summary,
                related_task_type=related_task_type,
                related_pollutant=related_pollutant,
            )
        )

    for item in tool_results:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").strip() != "compare_scenarios":
            continue
        result = item.get("result") or {}
        if isinstance(result, dict) and result.get("success"):
            records.append(
                build_artifact_record(
                    artifact_type=ArtifactType.COMPARISON_RESULT,
                    delivery_turn_index=delivery_turn_index,
                    source_tool_name="compare_scenarios",
                    delivery_status=ArtifactDeliveryStatus.FULL,
                    summary="已提供情景对比结果。",
                    related_task_type=related_task_type,
                    related_pollutant=related_pollutant,
                )
            )

    if track_textual_summary:
        text = _clean_text(response_text)
        if text:
            status = (
                ArtifactDeliveryStatus.PARTIAL
                if records
                else ArtifactDeliveryStatus.FULL
            )
            records.append(
                build_artifact_record(
                    artifact_type=ArtifactType.QUICK_SUMMARY_TEXT,
                    delivery_turn_index=delivery_turn_index,
                    source_tool_name=source_tool_name,
                    delivery_status=status,
                    summary=text[:160],
                    related_task_type=related_task_type,
                    related_pollutant=related_pollutant,
                )
            )

    return _dedupe_records(records)


def update_artifact_memory(
    current_state: Optional[ArtifactMemoryState],
    records: Sequence[ArtifactRecord],
) -> ArtifactMemoryState:
    state = coerce_artifact_memory_state(current_state)
    state.append(records)
    return state


def _requested_artifact_from_intent(
    intent_plan: Optional[IntentResolutionApplicationPlan],
) -> tuple[Optional[ArtifactType], Optional[ArtifactFamily]]:
    if intent_plan is None:
        return None, None

    for action_id in intent_plan.preferred_action_ids:
        artifact_type = artifact_type_for_action_id(action_id)
        if artifact_type is not None:
            return artifact_type, artifact_family_for_type(artifact_type)

    deliverable = intent_plan.deliverable_intent.value
    if deliverable == "downloadable_table":
        return ArtifactType.DETAILED_CSV, ArtifactFamily.DOWNLOADABLE_TABLE
    if deliverable == "chart_or_ranked_summary":
        return ArtifactType.RANKED_CHART, ArtifactFamily.RANKED_SUMMARY
    if deliverable == "spatial_map":
        return None, ArtifactFamily.SPATIAL_VISUALIZATION
    if deliverable in {"quick_summary", "rough_estimate"}:
        return ArtifactType.QUICK_SUMMARY_TEXT, ArtifactFamily.TEXTUAL_SUMMARY
    if deliverable == "scenario_comparison":
        return ArtifactType.COMPARISON_RESULT, ArtifactFamily.COMPARISON_OUTPUT
    return None, None


def build_artifact_availability_decision(
    memory_state: Optional[ArtifactMemoryState],
    *,
    requested_type: Optional[ArtifactType] = None,
    requested_family: Optional[ArtifactFamily] = None,
) -> ArtifactAvailabilityDecision:
    state = coerce_artifact_memory_state(memory_state)
    matching_record = (
        state.find_latest_type(requested_type, status=ArtifactDeliveryStatus.FULL)
        if requested_type is not None
        else None
    )
    family_record = (
        state.find_latest_family(requested_family, status=ArtifactDeliveryStatus.FULL)
        if requested_family is not None
        else None
    )
    same_type = matching_record is not None
    same_family = family_record is not None
    explanation = None
    if same_type and requested_type is not None:
        explanation = f"{requested_type.value} was already fully delivered."
    elif same_family and requested_family is not None:
        explanation = f"{requested_family.value} already has a delivered artifact in memory."
    return ArtifactAvailabilityDecision(
        requested_type=requested_type,
        requested_family=requested_family,
        same_type_full_provided=same_type,
        same_family_full_provided=same_family,
        matching_record=matching_record,
        family_record=family_record,
        should_suppress_repeat=same_type,
        should_promote_new_family=(same_family and not same_type),
        explanation=explanation,
    )


def _scan_repeated_available_actions(
    memory_state: ArtifactMemoryState,
    capability_summary: Optional[Dict[str, Any]],
) -> tuple[List[str], List[str], List[str]]:
    if not isinstance(capability_summary, dict):
        return [], [], []
    suppressed: List[str] = []
    repeated_types: List[str] = []
    repeated_families: List[str] = []
    for item in capability_summary.get("available_next_actions") or []:
        if not isinstance(item, dict):
            continue
        action_id = _clean_text(item.get("action_id"))
        artifact_type = artifact_type_for_action_id(action_id)
        if artifact_type is None:
            continue
        matching_record = memory_state.find_latest_type(
            artifact_type,
            status=ArtifactDeliveryStatus.FULL,
        )
        if matching_record is None:
            continue
        if action_id and action_id not in suppressed:
            suppressed.append(action_id)
        if artifact_type.value not in repeated_types:
            repeated_types.append(artifact_type.value)
        family_value = artifact_family_for_type(artifact_type).value
        if family_value not in repeated_families:
            repeated_families.append(family_value)
    return suppressed, repeated_types, repeated_families


def _promote_requested_family_if_partial_summary_exists(
    memory_state: ArtifactMemoryState,
    requested_family: Optional[ArtifactFamily],
) -> bool:
    if requested_family is None or requested_family == ArtifactFamily.TEXTUAL_SUMMARY:
        return False
    text_record = memory_state.find_latest_type(ArtifactType.QUICK_SUMMARY_TEXT)
    if text_record is None:
        return False
    return text_record.delivery_status == ArtifactDeliveryStatus.PARTIAL


def build_artifact_suggestion_plan(
    memory_state: Optional[ArtifactMemoryState],
    capability_summary: Optional[Dict[str, Any]],
    intent_plan: Optional[IntentResolutionApplicationPlan],
    *,
    dedup_by_family: bool = True,
) -> ArtifactSuggestionPlan:
    state = coerce_artifact_memory_state(memory_state)
    requested_type, requested_family = _requested_artifact_from_intent(intent_plan)
    availability = build_artifact_availability_decision(
        state,
        requested_type=requested_type,
        requested_family=requested_family,
    )
    suppressed_action_ids, repeated_types, repeated_families = _scan_repeated_available_actions(
        state,
        capability_summary,
    )
    promoted_families: List[str] = []
    notes: List[str] = []
    user_visible_summary: Optional[str] = None

    if availability.should_suppress_repeat and availability.matching_record is not None:
        repeated_type = availability.matching_record.artifact_type.value
        if repeated_type not in repeated_types:
            repeated_types.append(repeated_type)
        family_value = availability.matching_record.artifact_family.value
        if family_value not in repeated_families:
            repeated_families.append(family_value)
        action_id = availability.matching_record.source_action_id or _DEFAULT_ACTION_BY_TYPE.get(
            availability.matching_record.artifact_type
        )
        if action_id and action_id not in suppressed_action_ids:
            suppressed_action_ids.append(action_id)
        summary = _clean_text(availability.matching_record.summary)
        user_visible_summary = summary or "当前请求的交付物已经完整提供过，下一步更适合切换为另一种输出形式。"
        notes.append("exact_artifact_repeat_detected")

    elif (
        dedup_by_family
        and
        availability.should_promote_new_family
        and requested_family is not None
        and requested_family.value not in promoted_families
    ):
        promoted_families.append(requested_family.value)
        notes.append("same_family_different_type")
        family_record = availability.family_record
        family_label = family_record.artifact_type.value if family_record is not None else requested_family.value
        if requested_type is not None:
            user_visible_summary = (
                f"当前已提供同一交付族的 {family_label}，如需换一种形式展示，可继续切到 {requested_type.value}。"
            )

    if _promote_requested_family_if_partial_summary_exists(state, requested_family):
        if requested_family is not None and requested_family.value not in promoted_families:
            promoted_families.append(requested_family.value)
        notes.append("partial_summary_can_expand")
        if user_visible_summary is None and requested_family is not None:
            user_visible_summary = (
                f"当前已有文本摘要，可继续补成 {requested_family.value} 这类更完整的交付。"
            )

    if suppressed_action_ids and user_visible_summary is None:
        user_visible_summary = "部分同类交付物已经完整提供，后续建议将优先切换为新的输出形式。"
        notes.append("repeated_available_action_suppressed")

    return ArtifactSuggestionPlan(
        suppressed_action_ids=list(dict.fromkeys(suppressed_action_ids)),
        promoted_action_ids=[],
        promoted_families=list(dict.fromkeys(promoted_families)),
        repeated_artifact_types=list(dict.fromkeys(repeated_types)),
        repeated_artifact_families=list(dict.fromkeys(repeated_families)),
        user_visible_summary=user_visible_summary,
        notes=list(dict.fromkeys(notes)),
        availability_decision=availability,
    )


def apply_artifact_memory_to_capability_summary(
    summary: Optional[Dict[str, Any]],
    memory_state: Optional[ArtifactMemoryState],
    intent_plan: Optional[IntentResolutionApplicationPlan],
    *,
    dedup_by_family: bool = True,
) -> Optional[Dict[str, Any]]:
    if not isinstance(summary, dict):
        return summary
    state = coerce_artifact_memory_state(memory_state)
    if not state.artifacts:
        biased = dict(summary)
        biased["artifact_memory"] = state.to_summary()
        return biased

    suggestion_plan = build_artifact_suggestion_plan(
        state,
        capability_summary=summary,
        intent_plan=intent_plan,
        dedup_by_family=dedup_by_family,
    )
    suppressed = set(suggestion_plan.suppressed_action_ids)

    def _filter_items(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        filtered: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            action_id = _clean_text(item.get("action_id"))
            if action_id and action_id in suppressed:
                continue
            filtered.append(dict(item))
        return filtered

    biased = dict(summary)
    biased["available_next_actions"] = _filter_items(summary.get("available_next_actions") or [])
    hints = [
        str(item).strip()
        for item in (summary.get("guidance_hints") or [])
        if str(item).strip()
    ]
    if suggestion_plan.user_visible_summary and suggestion_plan.user_visible_summary not in hints:
        hints.insert(0, suggestion_plan.user_visible_summary)
    biased["guidance_hints"] = hints
    biased["artifact_memory"] = state.to_summary()
    biased["artifact_bias"] = suggestion_plan.to_dict()
    return biased
