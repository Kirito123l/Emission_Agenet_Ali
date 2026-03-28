from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


def _clamp_confidence(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number < 0.0:
        return 0.0
    if number > 1.0:
        return 1.0
    return number


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    cleaned: List[str] = []
    for item in values:
        text = _clean_text(item)
        if text:
            cleaned.append(text)
    return cleaned


@dataclass
class FileRelationshipFileSummary:
    file_path: Optional[str] = None
    file_name: Optional[str] = None
    file_type: Optional[str] = None
    task_type: Optional[str] = None
    confidence: Optional[float] = None
    columns: List[str] = field(default_factory=list)
    row_count: Optional[int] = None
    selected_primary_table: Optional[str] = None
    dataset_roles: List[Dict[str, Any]] = field(default_factory=list)
    spatial_metadata: Dict[str, Any] = field(default_factory=dict)
    role_candidate: Optional[str] = None
    source: Optional[str] = None

    @classmethod
    def from_analysis(
        cls,
        analysis_dict: Optional[Dict[str, Any]],
        *,
        role_candidate: Optional[str] = None,
        source: Optional[str] = None,
        file_path_override: Optional[str] = None,
    ) -> "FileRelationshipFileSummary":
        payload = analysis_dict if isinstance(analysis_dict, dict) else {}
        file_path = _clean_text(file_path_override or payload.get("file_path"))
        file_name = _clean_text(payload.get("filename"))
        if file_name is None and file_path:
            file_name = Path(file_path).name
        file_type = _clean_text(payload.get("format"))
        if file_type is None and file_path:
            suffix = Path(file_path).suffix.lower().lstrip(".")
            file_type = suffix or None
        return cls(
            file_path=file_path,
            file_name=file_name,
            file_type=file_type,
            task_type=_clean_text(payload.get("task_type")),
            confidence=(
                _clamp_confidence(payload.get("confidence"))
                if payload.get("confidence") is not None
                else None
            ),
            columns=[
                str(item)
                for item in (payload.get("columns") or [])
                if item is not None
            ][:20],
            row_count=payload.get("row_count"),
            selected_primary_table=_clean_text(payload.get("selected_primary_table")),
            dataset_roles=[
                dict(item)
                for item in (payload.get("dataset_roles") or [])
                if isinstance(item, dict)
            ][:8],
            spatial_metadata=dict(payload.get("spatial_metadata") or {}),
            role_candidate=_clean_text(role_candidate),
            source=_clean_text(source),
        )

    @classmethod
    def from_path(
        cls,
        file_path: Optional[str],
        *,
        role_candidate: Optional[str] = None,
        source: Optional[str] = None,
    ) -> "FileRelationshipFileSummary":
        normalized_path = _clean_text(file_path)
        file_name = Path(normalized_path).name if normalized_path else None
        suffix = Path(normalized_path).suffix.lower().lstrip(".") if normalized_path else ""
        return cls(
            file_path=normalized_path,
            file_name=file_name,
            file_type=suffix or None,
            role_candidate=_clean_text(role_candidate),
            source=_clean_text(source),
        )

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "FileRelationshipFileSummary":
        data = payload if isinstance(payload, dict) else {}
        return cls(
            file_path=_clean_text(data.get("file_path")),
            file_name=_clean_text(data.get("file_name")),
            file_type=_clean_text(data.get("file_type")),
            task_type=_clean_text(data.get("task_type")),
            confidence=(
                _clamp_confidence(data.get("confidence"))
                if data.get("confidence") is not None
                else None
            ),
            columns=[
                str(item)
                for item in (data.get("columns") or [])
                if item is not None
            ][:20],
            row_count=data.get("row_count"),
            selected_primary_table=_clean_text(data.get("selected_primary_table")),
            dataset_roles=[
                dict(item)
                for item in (data.get("dataset_roles") or [])
                if isinstance(item, dict)
            ][:8],
            spatial_metadata=dict(data.get("spatial_metadata") or {}),
            role_candidate=_clean_text(data.get("role_candidate")),
            source=_clean_text(data.get("source")),
        )

    def is_spatial_like(self) -> bool:
        if self.spatial_metadata:
            return True
        spatial_types = {"geojson", "json", "shp", "shx", "dbf", "prj", "zip", "gpkg"}
        if (self.file_type or "").lower() in spatial_types:
            return True
        dataset_roles = self.dataset_roles or []
        return any("spatial" in str(item.get("role") or "").lower() for item in dataset_roles)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "task_type": self.task_type,
            "confidence": self.confidence,
            "columns": list(self.columns),
            "row_count": self.row_count,
            "selected_primary_table": self.selected_primary_table,
            "dataset_roles": [dict(item) for item in self.dataset_roles],
            "spatial_metadata": dict(self.spatial_metadata),
            "role_candidate": self.role_candidate,
            "source": self.source,
        }


class FileRelationshipType(str, Enum):
    REPLACE_PRIMARY_FILE = "replace_primary_file"
    ATTACH_SUPPORTING_FILE = "attach_supporting_file"
    MERGE_SUPPLEMENTAL_COLUMNS = "merge_supplemental_columns"
    CONTINUE_WITH_CURRENT_FILE = "continue_with_current_file"
    ASK_CLARIFY = "ask_clarify"


@dataclass
class FileRelationshipDecision:
    relationship_type: FileRelationshipType = FileRelationshipType.ASK_CLARIFY
    confidence: float = 0.0
    reason: Optional[str] = None
    primary_file_candidate: Optional[str] = None
    supporting_file_candidate: Optional[str] = None
    affected_contexts: List[str] = field(default_factory=list)
    should_supersede_pending_completion: bool = False
    should_reset_recovery_context: bool = False
    should_preserve_residual_workflow: bool = False
    user_utterance_summary: Optional[str] = None
    resolution_source: str = "llm"

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "FileRelationshipDecision":
        data = payload if isinstance(payload, dict) else {}
        relationship_type = data.get("relationship_type") or FileRelationshipType.ASK_CLARIFY.value
        try:
            normalized_type = FileRelationshipType(str(relationship_type).strip())
        except ValueError:
            normalized_type = FileRelationshipType.ASK_CLARIFY
        return cls(
            relationship_type=normalized_type,
            confidence=_clamp_confidence(data.get("confidence")),
            reason=_clean_text(data.get("reason")),
            primary_file_candidate=_clean_text(data.get("primary_file_candidate")),
            supporting_file_candidate=_clean_text(data.get("supporting_file_candidate")),
            affected_contexts=_clean_list(data.get("affected_contexts")),
            should_supersede_pending_completion=bool(
                data.get("should_supersede_pending_completion", False)
            ),
            should_reset_recovery_context=bool(
                data.get("should_reset_recovery_context", False)
            ),
            should_preserve_residual_workflow=bool(
                data.get("should_preserve_residual_workflow", False)
            ),
            user_utterance_summary=_clean_text(data.get("user_utterance_summary")),
            resolution_source=_clean_text(data.get("resolution_source")) or "llm",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relationship_type": self.relationship_type.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "primary_file_candidate": self.primary_file_candidate,
            "supporting_file_candidate": self.supporting_file_candidate,
            "affected_contexts": list(self.affected_contexts),
            "should_supersede_pending_completion": self.should_supersede_pending_completion,
            "should_reset_recovery_context": self.should_reset_recovery_context,
            "should_preserve_residual_workflow": self.should_preserve_residual_workflow,
            "user_utterance_summary": self.user_utterance_summary,
            "resolution_source": self.resolution_source,
        }


@dataclass
class FileRelationshipParseResult:
    is_resolved: bool = False
    decision: Optional[FileRelationshipDecision] = None
    raw_payload: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    used_fallback: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_resolved": self.is_resolved,
            "decision": self.decision.to_dict() if self.decision is not None else None,
            "raw_payload": dict(self.raw_payload or {}),
            "error": self.error,
            "used_fallback": self.used_fallback,
        }


@dataclass
class FileRelationshipResolutionContext:
    current_primary_file: Optional[FileRelationshipFileSummary] = None
    latest_uploaded_file: Optional[FileRelationshipFileSummary] = None
    attached_supporting_file: Optional[FileRelationshipFileSummary] = None
    current_task_type: Optional[str] = None
    has_pending_completion: bool = False
    pending_completion_reason_code: Optional[str] = None
    has_geometry_recovery: bool = False
    has_residual_reentry: bool = False
    has_residual_workflow: bool = False
    has_completion_overrides: bool = False
    has_active_parameter_negotiation: bool = False
    awaiting_relationship_clarification: bool = False
    user_message: Optional[str] = None
    recent_file_candidates: List[FileRelationshipFileSummary] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_primary_file": (
                self.current_primary_file.to_dict()
                if self.current_primary_file is not None
                else None
            ),
            "latest_uploaded_file": (
                self.latest_uploaded_file.to_dict()
                if self.latest_uploaded_file is not None
                else None
            ),
            "attached_supporting_file": (
                self.attached_supporting_file.to_dict()
                if self.attached_supporting_file is not None
                else None
            ),
            "current_task_type": self.current_task_type,
            "has_pending_completion": self.has_pending_completion,
            "pending_completion_reason_code": self.pending_completion_reason_code,
            "has_geometry_recovery": self.has_geometry_recovery,
            "has_residual_reentry": self.has_residual_reentry,
            "has_residual_workflow": self.has_residual_workflow,
            "has_completion_overrides": self.has_completion_overrides,
            "has_active_parameter_negotiation": self.has_active_parameter_negotiation,
            "awaiting_relationship_clarification": self.awaiting_relationship_clarification,
            "user_message": self.user_message,
            "recent_file_candidates": [item.to_dict() for item in self.recent_file_candidates],
        }

    def to_llm_payload(self) -> Dict[str, Any]:
        payload = self.to_dict()
        payload["role_candidates"] = [
            {
                "file_name": item.file_name,
                "file_path": item.file_path,
                "role_candidate": item.role_candidate,
                "file_type": item.file_type,
                "task_type": item.task_type,
            }
            for item in self.recent_file_candidates
        ]
        return payload


@dataclass
class FileRelationshipTransitionPlan:
    relationship_type: FileRelationshipType
    replace_primary_file: bool = False
    attach_supporting_file: bool = False
    preserve_primary_file: bool = False
    supersede_pending_completion: bool = False
    supersede_parameter_negotiation: bool = False
    clear_input_completion_overrides: bool = False
    reset_geometry_recovery_context: bool = False
    reset_geometry_readiness_refresh: bool = False
    preserve_residual_workflow: bool = False
    clear_residual_reentry_context: bool = False
    preserve_supporting_file_context: bool = False
    require_clarification: bool = False
    pending_merge_semantics: bool = False
    should_halt_after_transition: bool = False
    suppress_generic_new_task_reset: bool = False
    new_primary_file_candidate: Optional[str] = None
    supporting_file_candidate: Optional[str] = None
    clarification_question: Optional[str] = None
    user_visible_summary: Optional[str] = None
    affected_contexts: List[str] = field(default_factory=list)
    state_resets: List[str] = field(default_factory=list)
    state_preserved: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "FileRelationshipTransitionPlan":
        data = payload if isinstance(payload, dict) else {}
        relationship_type = data.get("relationship_type") or FileRelationshipType.ASK_CLARIFY.value
        try:
            normalized_type = FileRelationshipType(str(relationship_type).strip())
        except ValueError:
            normalized_type = FileRelationshipType.ASK_CLARIFY
        return cls(
            relationship_type=normalized_type,
            replace_primary_file=bool(data.get("replace_primary_file", False)),
            attach_supporting_file=bool(data.get("attach_supporting_file", False)),
            preserve_primary_file=bool(data.get("preserve_primary_file", False)),
            supersede_pending_completion=bool(data.get("supersede_pending_completion", False)),
            supersede_parameter_negotiation=bool(data.get("supersede_parameter_negotiation", False)),
            clear_input_completion_overrides=bool(data.get("clear_input_completion_overrides", False)),
            reset_geometry_recovery_context=bool(data.get("reset_geometry_recovery_context", False)),
            reset_geometry_readiness_refresh=bool(data.get("reset_geometry_readiness_refresh", False)),
            preserve_residual_workflow=bool(data.get("preserve_residual_workflow", False)),
            clear_residual_reentry_context=bool(data.get("clear_residual_reentry_context", False)),
            preserve_supporting_file_context=bool(data.get("preserve_supporting_file_context", False)),
            require_clarification=bool(data.get("require_clarification", False)),
            pending_merge_semantics=bool(data.get("pending_merge_semantics", False)),
            should_halt_after_transition=bool(data.get("should_halt_after_transition", False)),
            suppress_generic_new_task_reset=bool(data.get("suppress_generic_new_task_reset", False)),
            new_primary_file_candidate=_clean_text(data.get("new_primary_file_candidate")),
            supporting_file_candidate=_clean_text(data.get("supporting_file_candidate")),
            clarification_question=_clean_text(data.get("clarification_question")),
            user_visible_summary=_clean_text(data.get("user_visible_summary")),
            affected_contexts=_clean_list(data.get("affected_contexts")),
            state_resets=_clean_list(data.get("state_resets")),
            state_preserved=_clean_list(data.get("state_preserved")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relationship_type": self.relationship_type.value,
            "replace_primary_file": self.replace_primary_file,
            "attach_supporting_file": self.attach_supporting_file,
            "preserve_primary_file": self.preserve_primary_file,
            "supersede_pending_completion": self.supersede_pending_completion,
            "supersede_parameter_negotiation": self.supersede_parameter_negotiation,
            "clear_input_completion_overrides": self.clear_input_completion_overrides,
            "reset_geometry_recovery_context": self.reset_geometry_recovery_context,
            "reset_geometry_readiness_refresh": self.reset_geometry_readiness_refresh,
            "preserve_residual_workflow": self.preserve_residual_workflow,
            "clear_residual_reentry_context": self.clear_residual_reentry_context,
            "preserve_supporting_file_context": self.preserve_supporting_file_context,
            "require_clarification": self.require_clarification,
            "pending_merge_semantics": self.pending_merge_semantics,
            "should_halt_after_transition": self.should_halt_after_transition,
            "suppress_generic_new_task_reset": self.suppress_generic_new_task_reset,
            "new_primary_file_candidate": self.new_primary_file_candidate,
            "supporting_file_candidate": self.supporting_file_candidate,
            "clarification_question": self.clarification_question,
            "user_visible_summary": self.user_visible_summary,
            "affected_contexts": list(self.affected_contexts),
            "state_resets": list(self.state_resets),
            "state_preserved": list(self.state_preserved),
        }


def parse_file_relationship_result(
    raw_payload: Optional[Dict[str, Any]],
    context: FileRelationshipResolutionContext,
) -> FileRelationshipParseResult:
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    relationship_value = _clean_text(payload.get("relationship_type"))
    if relationship_value is None:
        return FileRelationshipParseResult(
            is_resolved=False,
            raw_payload=payload,
            error="relationship_type was missing from the bounded file-relationship result.",
        )

    decision = FileRelationshipDecision.from_dict(payload)
    if decision.relationship_type == FileRelationshipType.REPLACE_PRIMARY_FILE:
        decision.primary_file_candidate = (
            decision.primary_file_candidate
            or (context.latest_uploaded_file.file_path if context.latest_uploaded_file is not None else None)
        )
    elif decision.relationship_type in {
        FileRelationshipType.ATTACH_SUPPORTING_FILE,
        FileRelationshipType.MERGE_SUPPLEMENTAL_COLUMNS,
    }:
        decision.supporting_file_candidate = (
            decision.supporting_file_candidate
            or (context.latest_uploaded_file.file_path if context.latest_uploaded_file is not None else None)
        )

    if decision.user_utterance_summary is None and context.user_message:
        summary = str(context.user_message).strip()
        decision.user_utterance_summary = summary[:180]

    if decision.reason is None:
        decision.reason = (
            "The relationship classification did not include an explicit explanation."
            if decision.relationship_type != FileRelationshipType.ASK_CLARIFY
            else "The user intent remained too ambiguous to safely bind the new file."
        )

    return FileRelationshipParseResult(
        is_resolved=True,
        decision=decision,
        raw_payload=payload,
    )


def infer_file_relationship_fallback(
    context: FileRelationshipResolutionContext,
) -> FileRelationshipDecision:
    message = (context.user_message or "").strip().lower()
    latest_upload = context.latest_uploaded_file
    has_upload = latest_upload is not None and latest_upload.file_path is not None
    spatial_like = latest_upload.is_spatial_like() if latest_upload is not None else False

    replace_cues = (
        "发错",
        "重新上传",
        "换这个",
        "替换",
        "用这个新的算",
        "用新的计算",
        "换成这个",
        "重新算",
        "use this new",
        "replace",
        "wrong file",
    )
    attach_cues = (
        "配套",
        "补充文件",
        "辅助文件",
        "supporting",
        "gis",
        "shapefile",
        "geojson",
        "空间文件",
        "地图分析",
        "spatial",
    )
    merge_cues = (
        "加上这一列",
        "补一列",
        "补充列",
        "补充表",
        "并入",
        "合并",
        "merge",
        "add this column",
        "supplemental columns",
    )
    current_cues = (
        "还是按原来的",
        "继续当前",
        "继续原来的",
        "默认就好",
        "continue with current",
        "keep current",
        "use the original",
    )
    ambiguous_new_file_cues = (
        "用这个吧",
        "用这个新的吧",
        "就这个吧",
        "this one",
        "use this",
    )

    if any(cue in message for cue in merge_cues):
        return FileRelationshipDecision(
            relationship_type=FileRelationshipType.MERGE_SUPPLEMENTAL_COLUMNS,
            confidence=0.84,
            reason="The upload was described as a supplemental column or table rather than a full replacement.",
            supporting_file_candidate=latest_upload.file_path if latest_upload is not None else None,
            affected_contexts=["primary_file", "supplemental_merge"],
            should_supersede_pending_completion=context.has_pending_completion,
            should_reset_recovery_context=False,
            should_preserve_residual_workflow=False,
            user_utterance_summary=_clean_text(context.user_message),
            resolution_source="fallback",
        )

    if any(cue in message for cue in replace_cues):
        return FileRelationshipDecision(
            relationship_type=FileRelationshipType.REPLACE_PRIMARY_FILE,
            confidence=0.9,
            reason="The user explicitly framed the upload as a replacement for the previous primary file.",
            primary_file_candidate=latest_upload.file_path if latest_upload is not None else None,
            affected_contexts=[
                "primary_file",
                "pending_completion",
                "completion_overrides",
                "geometry_recovery",
                "residual_workflow",
            ],
            should_supersede_pending_completion=True,
            should_reset_recovery_context=True,
            should_preserve_residual_workflow=False,
            user_utterance_summary=_clean_text(context.user_message),
            resolution_source="fallback",
        )

    if context.awaiting_relationship_clarification and any(cue in message for cue in current_cues):
        return FileRelationshipDecision(
            relationship_type=FileRelationshipType.CONTINUE_WITH_CURRENT_FILE,
            confidence=0.85,
            reason="The clarification explicitly kept the current primary file authoritative.",
            primary_file_candidate=(
                context.current_primary_file.file_path
                if context.current_primary_file is not None
                else None
            ),
            affected_contexts=["primary_file", "residual_workflow"],
            should_supersede_pending_completion=False,
            should_reset_recovery_context=False,
            should_preserve_residual_workflow=True,
            user_utterance_summary=_clean_text(context.user_message),
            resolution_source="fallback",
        )

    if (
        has_upload
        and (
            any(cue in message for cue in attach_cues)
            or (
                spatial_like
                and (
                    context.has_geometry_recovery
                    or context.pending_completion_reason_code == "missing_geometry"
                )
            )
        )
    ):
        return FileRelationshipDecision(
            relationship_type=FileRelationshipType.ATTACH_SUPPORTING_FILE,
            confidence=0.83,
            reason="The upload aligned with a supporting-file path rather than a replacement of the current primary file.",
            primary_file_candidate=(
                context.current_primary_file.file_path
                if context.current_primary_file is not None
                else None
            ),
            supporting_file_candidate=latest_upload.file_path if latest_upload is not None else None,
            affected_contexts=["supporting_file_context", "geometry_recovery", "residual_workflow"],
            should_supersede_pending_completion=False,
            should_reset_recovery_context=False,
            should_preserve_residual_workflow=True,
            user_utterance_summary=_clean_text(context.user_message),
            resolution_source="fallback",
        )

    if has_upload and context.pending_completion_reason_code == "missing_geometry":
        return FileRelationshipDecision(
            relationship_type=FileRelationshipType.ATTACH_SUPPORTING_FILE,
            confidence=0.76,
            reason=(
                "The current completion flow was explicitly waiting for a supporting geometry file, "
                "so the upload was treated as an attempt to continue that bounded remediation path."
            ),
            primary_file_candidate=(
                context.current_primary_file.file_path
                if context.current_primary_file is not None
                else None
            ),
            supporting_file_candidate=latest_upload.file_path if latest_upload is not None else None,
            affected_contexts=["supporting_file_context", "geometry_recovery", "pending_completion"],
            should_supersede_pending_completion=False,
            should_reset_recovery_context=False,
            should_preserve_residual_workflow=True,
            user_utterance_summary=_clean_text(context.user_message),
            resolution_source="fallback",
        )

    if not has_upload and any(cue in message for cue in current_cues):
        return FileRelationshipDecision(
            relationship_type=FileRelationshipType.CONTINUE_WITH_CURRENT_FILE,
            confidence=0.8,
            reason="The user explicitly chose to continue with the current file context.",
            primary_file_candidate=(
                context.current_primary_file.file_path
                if context.current_primary_file is not None
                else None
            ),
            affected_contexts=["primary_file", "residual_workflow"],
            should_supersede_pending_completion=False,
            should_reset_recovery_context=False,
            should_preserve_residual_workflow=True,
            user_utterance_summary=_clean_text(context.user_message),
            resolution_source="fallback",
        )

    if has_upload and any(cue in message for cue in ambiguous_new_file_cues):
        return FileRelationshipDecision(
            relationship_type=FileRelationshipType.ASK_CLARIFY,
            confidence=0.35,
            reason="The user referenced the new file, but did not specify whether it replaces or supplements the current file.",
            primary_file_candidate=(
                context.current_primary_file.file_path
                if context.current_primary_file is not None
                else None
            ),
            supporting_file_candidate=latest_upload.file_path if latest_upload is not None else None,
            affected_contexts=["primary_file", "pending_completion"],
            should_supersede_pending_completion=False,
            should_reset_recovery_context=False,
            should_preserve_residual_workflow=False,
            user_utterance_summary=_clean_text(context.user_message),
            resolution_source="fallback",
        )

    if has_upload and context.current_primary_file is not None:
        return FileRelationshipDecision(
            relationship_type=FileRelationshipType.ASK_CLARIFY,
            confidence=0.3,
            reason="A new file arrived while a current primary file existed, but the relationship remained underspecified.",
            primary_file_candidate=context.current_primary_file.file_path,
            supporting_file_candidate=latest_upload.file_path if latest_upload is not None else None,
            affected_contexts=["primary_file", "pending_completion", "residual_workflow"],
            should_supersede_pending_completion=False,
            should_reset_recovery_context=False,
            should_preserve_residual_workflow=False,
            user_utterance_summary=_clean_text(context.user_message),
            resolution_source="fallback",
        )

    return FileRelationshipDecision(
        relationship_type=FileRelationshipType.CONTINUE_WITH_CURRENT_FILE,
        confidence=0.65,
        reason="No strong file-rebinding signal was detected, so the existing current-file context remained authoritative.",
        primary_file_candidate=(
            context.current_primary_file.file_path
            if context.current_primary_file is not None
            else None
        ),
        affected_contexts=["primary_file"],
        should_supersede_pending_completion=False,
        should_reset_recovery_context=False,
        should_preserve_residual_workflow=context.has_residual_workflow,
        user_utterance_summary=_clean_text(context.user_message),
        resolution_source="fallback",
    )


def build_file_relationship_transition_plan(
    decision: FileRelationshipDecision,
    context: FileRelationshipResolutionContext,
) -> FileRelationshipTransitionPlan:
    relationship_type = decision.relationship_type
    if relationship_type == FileRelationshipType.REPLACE_PRIMARY_FILE:
        state_resets = [
            "active_input_completion" if context.has_pending_completion else None,
            "input_completion_overrides" if context.has_completion_overrides else None,
            "geometry_recovery_context" if context.has_geometry_recovery else None,
            "residual_reentry_context" if context.has_residual_reentry else None,
            "residual_workflow" if context.has_residual_workflow else None,
        ]
        state_preserved = [
            "session_trace",
            "locked_parameters",
            "working_memory",
        ]
        return FileRelationshipTransitionPlan(
            relationship_type=relationship_type,
            replace_primary_file=True,
            preserve_primary_file=False,
            supersede_pending_completion=(
                decision.should_supersede_pending_completion or context.has_pending_completion
            ),
            supersede_parameter_negotiation=True,
            clear_input_completion_overrides=context.has_completion_overrides,
            reset_geometry_recovery_context=(
                decision.should_reset_recovery_context or context.has_geometry_recovery
            ),
            reset_geometry_readiness_refresh=context.has_geometry_recovery,
            preserve_residual_workflow=decision.should_preserve_residual_workflow,
            clear_residual_reentry_context=context.has_residual_reentry,
            preserve_supporting_file_context=False,
            require_clarification=False,
            pending_merge_semantics=False,
            should_halt_after_transition=False,
            suppress_generic_new_task_reset=True,
            new_primary_file_candidate=(
                decision.primary_file_candidate
                or (context.latest_uploaded_file.file_path if context.latest_uploaded_file is not None else None)
            ),
            user_visible_summary="已将新上传文件视为当前任务的主输入，并替换先前文件。",
            affected_contexts=list(decision.affected_contexts),
            state_resets=[item for item in state_resets if item],
            state_preserved=[item for item in state_preserved if item],
        )

    if relationship_type == FileRelationshipType.ATTACH_SUPPORTING_FILE:
        return FileRelationshipTransitionPlan(
            relationship_type=relationship_type,
            replace_primary_file=False,
            attach_supporting_file=True,
            preserve_primary_file=True,
            supersede_pending_completion=False,
            supersede_parameter_negotiation=False,
            clear_input_completion_overrides=False,
            reset_geometry_recovery_context=False,
            reset_geometry_readiness_refresh=False,
            preserve_residual_workflow=(
                decision.should_preserve_residual_workflow or context.has_residual_workflow
            ),
            clear_residual_reentry_context=False,
            preserve_supporting_file_context=True,
            require_clarification=False,
            pending_merge_semantics=False,
            should_halt_after_transition=False,
            suppress_generic_new_task_reset=True,
            new_primary_file_candidate=(
                context.current_primary_file.file_path
                if context.current_primary_file is not None
                else None
            ),
            supporting_file_candidate=(
                decision.supporting_file_candidate
                or (context.latest_uploaded_file.file_path if context.latest_uploaded_file is not None else None)
            ),
            user_visible_summary="已将新文件识别为补充文件，并保留当前主文件上下文。",
            affected_contexts=list(decision.affected_contexts),
            state_resets=[],
            state_preserved=[
                item
                for item in [
                    "primary_file",
                    "residual_workflow" if context.has_residual_workflow else None,
                    "geometry_recovery_context" if context.has_geometry_recovery else None,
                ]
                if item
            ],
        )

    if relationship_type == FileRelationshipType.MERGE_SUPPLEMENTAL_COLUMNS:
        state_preserved = [
            "primary_file",
            "session_trace",
            "supporting_file_context",
        ]
        if context.has_residual_workflow:
            state_preserved.append("residual_workflow")
        if context.has_geometry_recovery:
            state_preserved.append("geometry_recovery_context")
        return FileRelationshipTransitionPlan(
            relationship_type=relationship_type,
            replace_primary_file=False,
            attach_supporting_file=False,
            preserve_primary_file=True,
            supersede_pending_completion=context.has_pending_completion,
            supersede_parameter_negotiation=False,
            clear_input_completion_overrides=context.has_completion_overrides,
            reset_geometry_recovery_context=False,
            reset_geometry_readiness_refresh=False,
            preserve_residual_workflow=context.has_residual_workflow,
            clear_residual_reentry_context=False,
            preserve_supporting_file_context=True,
            require_clarification=False,
            pending_merge_semantics=True,
            should_halt_after_transition=True,
            suppress_generic_new_task_reset=True,
            new_primary_file_candidate=(
                context.current_primary_file.file_path
                if context.current_primary_file is not None
                else None
            ),
            supporting_file_candidate=(
                decision.supporting_file_candidate
                or (context.latest_uploaded_file.file_path if context.latest_uploaded_file is not None else None)
            ),
            user_visible_summary=(
                "已将新文件识别为补充列/补充表，将进入受控的主键对齐与列补充路径。"
            ),
            affected_contexts=list(decision.affected_contexts),
            state_resets=[
                item
                for item in [
                    "active_input_completion" if context.has_pending_completion else None,
                    "input_completion_overrides" if context.has_completion_overrides else None,
                ]
                if item
            ],
            state_preserved=state_preserved,
        )

    if relationship_type == FileRelationshipType.CONTINUE_WITH_CURRENT_FILE:
        return FileRelationshipTransitionPlan(
            relationship_type=relationship_type,
            replace_primary_file=False,
            attach_supporting_file=False,
            preserve_primary_file=True,
            supersede_pending_completion=False,
            supersede_parameter_negotiation=False,
            clear_input_completion_overrides=False,
            reset_geometry_recovery_context=False,
            reset_geometry_readiness_refresh=False,
            preserve_residual_workflow=(
                decision.should_preserve_residual_workflow or context.has_residual_workflow
            ),
            clear_residual_reentry_context=False,
            preserve_supporting_file_context=True,
            require_clarification=False,
            pending_merge_semantics=False,
            should_halt_after_transition=False,
            suppress_generic_new_task_reset=True,
            new_primary_file_candidate=(
                decision.primary_file_candidate
                or (
                    context.current_primary_file.file_path
                    if context.current_primary_file is not None
                    else None
                )
            ),
            user_visible_summary="当前仍沿用原来的主文件上下文。",
            affected_contexts=list(decision.affected_contexts),
            state_resets=[],
            state_preserved=[
                item
                for item in [
                    "primary_file",
                    "residual_workflow" if context.has_residual_workflow else None,
                ]
                if item
            ],
        )

    clarification_question = (
        "当前我还不能安全判断这个新文件是替换旧文件，还是作为补充文件使用。"
        " 请明确回复：替换主文件，还是作为补充文件附加？"
    )
    return FileRelationshipTransitionPlan(
        relationship_type=FileRelationshipType.ASK_CLARIFY,
        replace_primary_file=False,
        attach_supporting_file=False,
        preserve_primary_file=True,
        supersede_pending_completion=False,
        supersede_parameter_negotiation=False,
        clear_input_completion_overrides=False,
        reset_geometry_recovery_context=False,
        reset_geometry_readiness_refresh=False,
        preserve_residual_workflow=context.has_residual_workflow,
        clear_residual_reentry_context=False,
        preserve_supporting_file_context=True,
        require_clarification=True,
        pending_merge_semantics=False,
        should_halt_after_transition=True,
        suppress_generic_new_task_reset=True,
        new_primary_file_candidate=(
            context.current_primary_file.file_path
            if context.current_primary_file is not None
            else None
        ),
        supporting_file_candidate=(
            decision.supporting_file_candidate
            or (context.latest_uploaded_file.file_path if context.latest_uploaded_file is not None else None)
        ),
        clarification_question=clarification_question,
        user_visible_summary=clarification_question,
        affected_contexts=list(decision.affected_contexts),
        state_resets=[],
        state_preserved=[
            item
            for item in [
                "primary_file",
                "residual_workflow" if context.has_residual_workflow else None,
            ]
            if item
        ],
    )
