from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd


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


def _normalize_token(value: Any) -> str:
    text = str(value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", text)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized


def _normalize_merge_key_value(value: Any) -> Optional[str]:
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    if value is None:
        return None

    if isinstance(value, bool):
        return str(value).lower()

    if isinstance(value, int):
        return str(value)

    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        if abs(value - round(value)) < 1e-9:
            return str(int(round(value)))
        return str(value).strip().lower()

    text = str(value).strip()
    if not text:
        return None

    if re.fullmatch(r"[-+]?\d+\.0+", text):
        try:
            return str(int(float(text)))
        except (TypeError, ValueError):
            return text.lower()

    return text.lower()


def _clean_dict(payload: Any) -> Dict[str, Any]:
    return dict(payload or {}) if isinstance(payload, dict) else {}


def _clean_dict_list(values: Any) -> List[Dict[str, Any]]:
    if not isinstance(values, list):
        return []
    return [dict(item) for item in values if isinstance(item, dict)]


def _dedupe_strings(values: Iterable[str]) -> List[str]:
    ordered: List[str] = []
    seen = set()
    for item in values:
        text = _clean_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


_TABULAR_SUFFIXES = {".csv", ".xlsx", ".xls"}

_IDENTIFIER_ALIAS_GROUPS: Dict[str, Tuple[str, ...]] = {
    "link_id": (
        "link_id",
        "segment_id",
        "seg_id",
        "segid",
        "segment",
        "segmentid",
        "link",
        "linkid",
        "edge_id",
        "road_id",
        "road_segment_id",
        "road_segment",
    ),
}

_CANONICAL_IMPORT_ALIASES: Dict[str, Tuple[str, ...]] = {
    "traffic_flow_vph": (
        "traffic_flow_vph",
        "traffic_flow",
        "flow",
        "volume",
        "traffic_volume",
        "daily_traffic",
        "veh_per_hour",
        "vph",
        "aadt",
    ),
    "avg_speed_kph": (
        "avg_speed_kph",
        "avg_speed",
        "speed",
        "speed_kph",
        "speed_kmh",
        "avg_spd",
        "spd",
        "average_speed",
    ),
    "link_length_km": (
        "link_length_km",
        "length_km",
        "len_km",
        "distance_km",
        "road_length_km",
    ),
}


@dataclass
class SupplementalMergeKey:
    primary_column: Optional[str] = None
    supplemental_column: Optional[str] = None
    confidence: float = 0.0
    reason: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "SupplementalMergeKey":
        data = _clean_dict(payload)
        return cls(
            primary_column=_clean_text(data.get("primary_column")),
            supplemental_column=_clean_text(data.get("supplemental_column")),
            confidence=_clamp_confidence(data.get("confidence")),
            reason=_clean_text(data.get("reason")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "primary_column": self.primary_column,
            "supplemental_column": self.supplemental_column,
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass
class SupplementalColumnAttachment:
    canonical_field: Optional[str] = None
    supplemental_column: Optional[str] = None
    target_column: Optional[str] = None
    source_strategy: Optional[str] = None
    reason: Optional[str] = None
    status: str = "planned"
    coverage_ratio: Optional[float] = None
    non_null_value_count: Optional[int] = None

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "SupplementalColumnAttachment":
        data = _clean_dict(payload)
        return cls(
            canonical_field=_clean_text(data.get("canonical_field")),
            supplemental_column=_clean_text(data.get("supplemental_column")),
            target_column=_clean_text(data.get("target_column")),
            source_strategy=_clean_text(data.get("source_strategy")),
            reason=_clean_text(data.get("reason")),
            status=_clean_text(data.get("status")) or "planned",
            coverage_ratio=(
                _clamp_confidence(data.get("coverage_ratio"))
                if data.get("coverage_ratio") is not None
                else None
            ),
            non_null_value_count=(
                int(data.get("non_null_value_count"))
                if data.get("non_null_value_count") is not None
                else None
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "canonical_field": self.canonical_field,
            "supplemental_column": self.supplemental_column,
            "target_column": self.target_column,
            "source_strategy": self.source_strategy,
            "reason": self.reason,
            "status": self.status,
            "coverage_ratio": self.coverage_ratio,
            "non_null_value_count": self.non_null_value_count,
        }


@dataclass
class SupplementalMergePlan:
    primary_file_ref: Optional[str] = None
    supplemental_file_ref: Optional[str] = None
    merge_keys: List[SupplementalMergeKey] = field(default_factory=list)
    candidate_columns_to_import: List[str] = field(default_factory=list)
    canonical_targets: Dict[str, str] = field(default_factory=dict)
    attachments: List[SupplementalColumnAttachment] = field(default_factory=list)
    merge_mode: str = "left_join_by_key"
    preconditions: List[str] = field(default_factory=list)
    plan_status: str = "unavailable"
    failure_reason: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "SupplementalMergePlan":
        data = _clean_dict(payload)
        return cls(
            primary_file_ref=_clean_text(data.get("primary_file_ref")),
            supplemental_file_ref=_clean_text(data.get("supplemental_file_ref")),
            merge_keys=[
                SupplementalMergeKey.from_dict(item)
                for item in (data.get("merge_keys") or [])
                if isinstance(item, dict)
            ],
            candidate_columns_to_import=_clean_list(data.get("candidate_columns_to_import")),
            canonical_targets={
                str(key): str(value)
                for key, value in _clean_dict(data.get("canonical_targets")).items()
                if _clean_text(key) and _clean_text(value)
            },
            attachments=[
                SupplementalColumnAttachment.from_dict(item)
                for item in (data.get("attachments") or [])
                if isinstance(item, dict)
            ],
            merge_mode=_clean_text(data.get("merge_mode")) or "left_join_by_key",
            preconditions=_clean_list(data.get("preconditions")),
            plan_status=_clean_text(data.get("plan_status")) or "unavailable",
            failure_reason=_clean_text(data.get("failure_reason")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "primary_file_ref": self.primary_file_ref,
            "supplemental_file_ref": self.supplemental_file_ref,
            "merge_keys": [item.to_dict() for item in self.merge_keys],
            "candidate_columns_to_import": list(self.candidate_columns_to_import),
            "canonical_targets": dict(self.canonical_targets),
            "attachments": [item.to_dict() for item in self.attachments],
            "merge_mode": self.merge_mode,
            "preconditions": list(self.preconditions),
            "plan_status": self.plan_status,
            "failure_reason": self.failure_reason,
        }


@dataclass
class SupplementalMergeResult:
    success: bool = False
    merged_columns: List[str] = field(default_factory=list)
    materialized_primary_file_ref: Optional[str] = None
    updated_file_context_summary: Optional[Dict[str, Any]] = None
    updated_missing_field_diagnostics: Optional[Dict[str, Any]] = None
    updated_readiness_summary: Optional[Dict[str, Any]] = None
    failure_reason: Optional[str] = None
    attachments: List[SupplementalColumnAttachment] = field(default_factory=list)
    merge_stats: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "SupplementalMergeResult":
        data = _clean_dict(payload)
        return cls(
            success=bool(data.get("success", False)),
            merged_columns=_clean_list(data.get("merged_columns")),
            materialized_primary_file_ref=_clean_text(data.get("materialized_primary_file_ref")),
            updated_file_context_summary=_clean_dict(data.get("updated_file_context_summary")) or None,
            updated_missing_field_diagnostics=_clean_dict(data.get("updated_missing_field_diagnostics")) or None,
            updated_readiness_summary=_clean_dict(data.get("updated_readiness_summary")) or None,
            failure_reason=_clean_text(data.get("failure_reason")),
            attachments=[
                SupplementalColumnAttachment.from_dict(item)
                for item in (data.get("attachments") or [])
                if isinstance(item, dict)
            ],
            merge_stats=_clean_dict(data.get("merge_stats")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "merged_columns": list(self.merged_columns),
            "materialized_primary_file_ref": self.materialized_primary_file_ref,
            "updated_file_context_summary": _clean_dict(self.updated_file_context_summary) or None,
            "updated_missing_field_diagnostics": _clean_dict(self.updated_missing_field_diagnostics) or None,
            "updated_readiness_summary": _clean_dict(self.updated_readiness_summary) or None,
            "failure_reason": self.failure_reason,
            "attachments": [item.to_dict() for item in self.attachments],
            "merge_stats": dict(self.merge_stats),
        }


@dataclass
class SupplementalMergeContext:
    primary_file_summary: Dict[str, Any] = field(default_factory=dict)
    supplemental_file_summary: Dict[str, Any] = field(default_factory=dict)
    primary_file_analysis: Dict[str, Any] = field(default_factory=dict)
    supplemental_file_analysis: Dict[str, Any] = field(default_factory=dict)
    current_task_type: Optional[str] = None
    target_missing_canonical_fields: List[str] = field(default_factory=list)
    current_residual_workflow_summary: Optional[str] = None
    relationship_decision_summary: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "SupplementalMergeContext":
        data = _clean_dict(payload)
        return cls(
            primary_file_summary=_clean_dict(data.get("primary_file_summary")),
            supplemental_file_summary=_clean_dict(data.get("supplemental_file_summary")),
            primary_file_analysis=_clean_dict(data.get("primary_file_analysis")),
            supplemental_file_analysis=_clean_dict(data.get("supplemental_file_analysis")),
            current_task_type=_clean_text(data.get("current_task_type")),
            target_missing_canonical_fields=_clean_list(data.get("target_missing_canonical_fields")),
            current_residual_workflow_summary=_clean_text(data.get("current_residual_workflow_summary")),
            relationship_decision_summary=_clean_dict(data.get("relationship_decision_summary")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "primary_file_summary": dict(self.primary_file_summary),
            "supplemental_file_summary": dict(self.supplemental_file_summary),
            "primary_file_analysis": dict(self.primary_file_analysis),
            "supplemental_file_analysis": dict(self.supplemental_file_analysis),
            "current_task_type": self.current_task_type,
            "target_missing_canonical_fields": list(self.target_missing_canonical_fields),
            "current_residual_workflow_summary": self.current_residual_workflow_summary,
            "relationship_decision_summary": dict(self.relationship_decision_summary),
        }


def _read_tabular_file(file_ref: Optional[str]) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    normalized = _clean_text(file_ref)
    if not normalized:
        return None, "Tabular merge requires a concrete file reference."

    path = Path(normalized)
    suffix = path.suffix.lower()
    if suffix not in _TABULAR_SUFFIXES:
        return None, (
            f"Tabular supplemental merge currently supports CSV/Excel only. "
            f"Got unsupported file type '{suffix or 'unknown'}'."
        )

    try:
        if suffix == ".csv":
            df = pd.read_csv(path)
        else:
            df = pd.read_excel(path)
    except Exception as exc:
        return None, f"Failed to read '{normalized}' for supplemental merge: {exc}"

    if df.empty:
        return None, f"File '{normalized}' was empty and could not be used for supplemental merge."

    df = df.copy()
    df.columns = [str(item).strip() for item in df.columns]
    return df, None


def _invert_mapping(mapping: Dict[str, Any]) -> Dict[str, str]:
    inverted: Dict[str, str] = {}
    for source_column, canonical_field in (mapping or {}).items():
        source_text = _clean_text(source_column)
        canonical_text = _clean_text(canonical_field)
        if not source_text or not canonical_text:
            continue
        inverted.setdefault(canonical_text, source_text)
    return inverted


def _select_relevant_mapping(
    analysis: Dict[str, Any],
    *,
    task_type: Optional[str],
) -> Dict[str, str]:
    if task_type == "macro_emission":
        preferred = _clean_dict(analysis.get("macro_mapping"))
        if preferred:
            return {str(key): str(value) for key, value in preferred.items()}
    if task_type == "micro_emission":
        preferred = _clean_dict(analysis.get("micro_mapping"))
        if preferred:
            return {str(key): str(value) for key, value in preferred.items()}

    column_mapping = _clean_dict(analysis.get("column_mapping"))
    if column_mapping:
        return {str(key): str(value) for key, value in column_mapping.items()}

    merged: Dict[str, str] = {}
    for key in ("macro_mapping", "micro_mapping"):
        for source_column, canonical_field in _clean_dict(analysis.get(key)).items():
            source_text = _clean_text(source_column)
            canonical_text = _clean_text(canonical_field)
            if not source_text or not canonical_text:
                continue
            merged.setdefault(source_text, canonical_text)
    return merged


def _extract_missing_fields(diagnostics: Dict[str, Any]) -> List[str]:
    fields: List[str] = []
    for item in (diagnostics.get("required_field_statuses") or []):
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        field_name = _clean_text(item.get("field"))
        if field_name and status != "present":
            fields.append(field_name)
    if fields:
        return _dedupe_strings(fields)
    fallback = [
        _clean_text(item.get("field"))
        for item in (diagnostics.get("missing_fields") or [])
        if isinstance(item, dict)
    ]
    return _dedupe_strings(item for item in fallback if item)


def _find_exact_column(columns: Sequence[str], aliases: Sequence[str]) -> Optional[str]:
    alias_tokens = {_normalize_token(item) for item in aliases if _clean_text(item)}
    for column in columns:
        if _normalize_token(column) in alias_tokens:
            return str(column)
    return None


def _collect_identifier_candidates(
    analysis: Dict[str, Any],
    *,
    columns: Sequence[str],
    task_type: Optional[str],
    allow_alias_keys: bool,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    seen = set()
    canonical_to_source = _invert_mapping(_select_relevant_mapping(analysis, task_type=task_type))

    mapped_link_id = canonical_to_source.get("link_id")
    if mapped_link_id:
        normalized = _normalize_token(mapped_link_id)
        candidates.append(
            {
                "column": mapped_link_id,
                "canonical_field": "link_id",
                "score": 0.98,
                "reason": "File grounding already mapped this column to canonical link_id.",
                "normalized": normalized,
            }
        )
        seen.add(normalized)

    for canonical_field, aliases in _IDENTIFIER_ALIAS_GROUPS.items():
        direct = _find_exact_column(columns, aliases)
        if direct is None:
            continue
        normalized = _normalize_token(direct)
        if normalized in seen:
            continue
        score = 0.93 if normalized in {_normalize_token(item) for item in aliases[:2]} else 0.84
        candidates.append(
            {
                "column": direct,
                "canonical_field": canonical_field,
                "score": score,
                "reason": f"Column '{direct}' matched a bounded identifier alias for {canonical_field}.",
                "normalized": normalized,
            }
        )
        seen.add(normalized)

    if allow_alias_keys:
        for column in columns:
            normalized = _normalize_token(column)
            if normalized in seen:
                continue
            if "link" in normalized or "segment" in normalized or normalized.endswith("_id"):
                candidates.append(
                    {
                        "column": str(column),
                        "canonical_field": "link_id",
                        "score": 0.76,
                        "reason": f"Column '{column}' matched a bounded identifier-name heuristic.",
                        "normalized": normalized,
                    }
                )
                seen.add(normalized)

    return candidates


def _choose_merge_key(
    context: SupplementalMergeContext,
    *,
    allow_alias_keys: bool,
) -> Optional[SupplementalMergeKey]:
    primary_analysis = _clean_dict(context.primary_file_analysis)
    supplemental_analysis = _clean_dict(context.supplemental_file_analysis)
    task_type = _clean_text(context.current_task_type)
    primary_columns = [str(item) for item in (primary_analysis.get("columns") or [])]
    supplemental_columns = [str(item) for item in (supplemental_analysis.get("columns") or [])]

    primary_candidates = _collect_identifier_candidates(
        primary_analysis,
        columns=primary_columns,
        task_type=task_type,
        allow_alias_keys=allow_alias_keys,
    )
    supplemental_candidates = _collect_identifier_candidates(
        supplemental_analysis,
        columns=supplemental_columns,
        task_type=task_type,
        allow_alias_keys=allow_alias_keys,
    )

    best_pair: Optional[Tuple[Dict[str, Any], Dict[str, Any], float, str]] = None
    for primary_candidate in primary_candidates:
        for supplemental_candidate in supplemental_candidates:
            if primary_candidate["canonical_field"] != supplemental_candidate["canonical_field"]:
                continue

            same_name = primary_candidate["normalized"] == supplemental_candidate["normalized"]
            if not allow_alias_keys and not same_name:
                continue

            score = min(primary_candidate["score"], supplemental_candidate["score"])
            reasons = [
                primary_candidate["reason"],
                supplemental_candidate["reason"],
            ]
            if same_name:
                score += 0.03
                reasons.append("Both files expose the same bounded identifier column name.")
            else:
                score -= 0.02
                reasons.append("The identifier columns were aligned through a bounded alias match.")

            if best_pair is None or score > best_pair[2]:
                best_pair = (
                    primary_candidate,
                    supplemental_candidate,
                    score,
                    " ".join(reasons),
                )

    if best_pair is None:
        return None

    primary_candidate, supplemental_candidate, score, reason = best_pair
    return SupplementalMergeKey(
        primary_column=primary_candidate["column"],
        supplemental_column=supplemental_candidate["column"],
        confidence=_clamp_confidence(score),
        reason=reason,
    )


def _resolve_attachment_candidates(
    context: SupplementalMergeContext,
    *,
    allow_alias_keys: bool,
) -> List[SupplementalColumnAttachment]:
    supplemental_analysis = _clean_dict(context.supplemental_file_analysis)
    task_type = _clean_text(context.current_task_type)
    supplemental_columns = [str(item) for item in (supplemental_analysis.get("columns") or [])]
    canonical_to_source = _invert_mapping(
        _select_relevant_mapping(supplemental_analysis, task_type=task_type)
    )
    attachments: List[SupplementalColumnAttachment] = []
    seen_targets = set()

    for canonical_field in context.target_missing_canonical_fields:
        field_name = _clean_text(canonical_field)
        if not field_name or field_name in seen_targets:
            continue

        direct_source = canonical_to_source.get(field_name)
        if direct_source:
            attachments.append(
                SupplementalColumnAttachment(
                    canonical_field=field_name,
                    supplemental_column=direct_source,
                    target_column=field_name,
                    source_strategy="grounded_mapping",
                    reason=(
                        f"Supplemental grounding already mapped '{direct_source}' "
                        f"to canonical field '{field_name}'."
                    ),
                )
            )
            seen_targets.add(field_name)
            continue

        aliases = _CANONICAL_IMPORT_ALIASES.get(field_name, (field_name,))
        direct_alias = _find_exact_column(supplemental_columns, aliases)
        if direct_alias:
            attachments.append(
                SupplementalColumnAttachment(
                    canonical_field=field_name,
                    supplemental_column=direct_alias,
                    target_column=field_name,
                    source_strategy="direct_alias",
                    reason=(
                        f"Supplemental column '{direct_alias}' matched the bounded alias set "
                        f"for canonical field '{field_name}'."
                    ),
                )
            )
            seen_targets.add(field_name)
            continue

        if not allow_alias_keys:
            continue

        normalized_aliases = {_normalize_token(item) for item in aliases}
        heuristic_match = next(
            (
                str(column)
                for column in supplemental_columns
                if _normalize_token(column) in normalized_aliases
            ),
            None,
        )
        if heuristic_match:
            attachments.append(
                SupplementalColumnAttachment(
                    canonical_field=field_name,
                    supplemental_column=heuristic_match,
                    target_column=field_name,
                    source_strategy="bounded_alias",
                    reason=(
                        f"Supplemental column '{heuristic_match}' matched the bounded alias set "
                        f"for canonical field '{field_name}'."
                    ),
                )
            )
            seen_targets.add(field_name)

    return attachments


def build_supplemental_merge_plan(
    context: SupplementalMergeContext,
    *,
    allow_alias_keys: bool = True,
) -> SupplementalMergePlan:
    primary_file_ref = (
        _clean_text(context.primary_file_analysis.get("file_path"))
        or _clean_text(context.primary_file_summary.get("file_path"))
    )
    supplemental_file_ref = (
        _clean_text(context.supplemental_file_analysis.get("file_path"))
        or _clean_text(context.supplemental_file_summary.get("file_path"))
    )
    target_missing_fields = (
        list(context.target_missing_canonical_fields)
        or _extract_missing_fields(_clean_dict(context.primary_file_analysis.get("missing_field_diagnostics")))
    )

    plan = SupplementalMergePlan(
        primary_file_ref=primary_file_ref,
        supplemental_file_ref=supplemental_file_ref,
        merge_mode="left_join_by_key",
        preconditions=[],
        plan_status="unavailable",
    )

    if not primary_file_ref or not supplemental_file_ref:
        plan.failure_reason = "Supplemental merge requires both a primary file and a supplemental file reference."
        plan.preconditions.append(plan.failure_reason)
        return plan

    if not target_missing_fields:
        plan.failure_reason = (
            "The current primary file did not expose unresolved canonical fields, "
            "so there was no bounded merge target."
        )
        plan.preconditions.append(plan.failure_reason)
        return plan

    merge_key = _choose_merge_key(context, allow_alias_keys=allow_alias_keys)
    if merge_key is None:
        plan.failure_reason = (
            "The supplemental file did not expose a reliable key that could be aligned "
            "to the current primary file."
        )
        plan.preconditions.append(plan.failure_reason)
        return plan

    attachments = _resolve_attachment_candidates(context, allow_alias_keys=allow_alias_keys)
    if not attachments:
        plan.failure_reason = (
            "The supplemental file did not contain columns that matched the current missing canonical fields."
        )
        plan.preconditions.append(plan.failure_reason)
        plan.merge_keys = [merge_key]
        return plan

    plan.merge_keys = [merge_key]
    plan.attachments = attachments
    plan.candidate_columns_to_import = _dedupe_strings(
        attachment.supplemental_column for attachment in attachments if attachment.supplemental_column
    )
    plan.canonical_targets = {
        attachment.canonical_field: attachment.target_column
        for attachment in attachments
        if attachment.canonical_field and attachment.target_column
    }
    plan.plan_status = "ready"
    plan.preconditions.extend(
        [
            f"bounded_key_alignment:{merge_key.primary_column}->{merge_key.supplemental_column}",
            "bounded_target_import_only",
        ]
    )
    unresolved_fields = [
        field_name
        for field_name in target_missing_fields
        if field_name not in plan.canonical_targets
    ]
    if unresolved_fields:
        plan.preconditions.append(
            "remaining_missing_targets:" + ",".join(sorted(unresolved_fields))
        )
    return plan


def _build_materialized_output_path(
    *,
    outputs_dir: Path,
    primary_file_ref: str,
    supplemental_file_ref: str,
    session_id: Optional[str],
) -> Path:
    primary_stem = Path(primary_file_ref).stem or "primary"
    supplemental_stem = Path(supplemental_file_ref).stem or "supplemental"
    session_fragment = _normalize_token(session_id or "session") or "session"
    timestamp = int(time.time() * 1000)
    target_dir = outputs_dir / "supplemental_merges" / session_fragment
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{primary_stem}__merged__{supplemental_stem}__{timestamp}.csv"
    return target_dir / filename


def execute_supplemental_merge(
    plan: SupplementalMergePlan,
    *,
    outputs_dir: Path,
    session_id: Optional[str] = None,
) -> SupplementalMergeResult:
    if plan.plan_status != "ready":
        return SupplementalMergeResult(
            success=False,
            failure_reason=plan.failure_reason or "Supplemental merge plan was not executable.",
        )

    if not plan.merge_keys:
        return SupplementalMergeResult(
            success=False,
            failure_reason="Supplemental merge plan was missing a bounded merge key.",
        )

    merge_key = plan.merge_keys[0]
    primary_df, primary_error = _read_tabular_file(plan.primary_file_ref)
    if primary_error:
        return SupplementalMergeResult(success=False, failure_reason=primary_error)

    supplemental_df, supplemental_error = _read_tabular_file(plan.supplemental_file_ref)
    if supplemental_error:
        return SupplementalMergeResult(success=False, failure_reason=supplemental_error)

    assert primary_df is not None
    assert supplemental_df is not None

    if merge_key.primary_column not in primary_df.columns:
        return SupplementalMergeResult(
            success=False,
            failure_reason=(
                f"Primary merge key '{merge_key.primary_column}' was not present in the primary file."
            ),
        )
    if merge_key.supplemental_column not in supplemental_df.columns:
        return SupplementalMergeResult(
            success=False,
            failure_reason=(
                f"Supplemental merge key '{merge_key.supplemental_column}' was not present in the supplemental file."
            ),
        )

    import_columns = [
        attachment.supplemental_column
        for attachment in plan.attachments
        if attachment.supplemental_column
    ]
    unique_import_columns = _dedupe_strings(import_columns)
    if not unique_import_columns:
        return SupplementalMergeResult(
            success=False,
            failure_reason="No bounded supplemental columns were selected for import.",
        )

    for column in unique_import_columns:
        if column not in supplemental_df.columns:
            return SupplementalMergeResult(
                success=False,
                failure_reason=f"Supplemental import column '{column}' was not present in the supplemental file.",
            )

    primary_work = primary_df.copy()
    supplemental_work = supplemental_df.copy()
    primary_work["__merge_key__"] = primary_work[merge_key.primary_column].apply(_normalize_merge_key_value)
    supplemental_work["__merge_key__"] = supplemental_work[merge_key.supplemental_column].apply(_normalize_merge_key_value)

    primary_non_null_key_count = int(primary_work["__merge_key__"].notna().sum())
    supplemental_non_null_key_count = int(supplemental_work["__merge_key__"].notna().sum())
    if primary_non_null_key_count == 0:
        return SupplementalMergeResult(
            success=False,
            failure_reason="Primary merge key values were empty, so a bounded row alignment could not be established.",
        )
    if supplemental_non_null_key_count == 0:
        return SupplementalMergeResult(
            success=False,
            failure_reason="Supplemental merge key values were empty, so a bounded row alignment could not be established.",
        )

    duplicates = supplemental_work.loc[
        supplemental_work["__merge_key__"].notna(),
        "__merge_key__",
    ].duplicated(keep=False)
    if bool(duplicates.any()):
        return SupplementalMergeResult(
            success=False,
            failure_reason=(
                "Supplemental merge key values were not unique, so the bounded merge path could not "
                "safely align rows."
            ),
        )

    rename_map: Dict[str, str] = {}
    for attachment in plan.attachments:
        if not attachment.supplemental_column or not attachment.canonical_field:
            continue
        rename_map[attachment.supplemental_column] = f"__supp_{attachment.canonical_field}"

    supplemental_subset = supplemental_work[["__merge_key__", *unique_import_columns]].copy()
    supplemental_subset = supplemental_subset.rename(columns=rename_map)

    merged_df = primary_work.merge(
        supplemental_subset,
        on="__merge_key__",
        how="left",
    )

    attachments: List[SupplementalColumnAttachment] = []
    merged_columns: List[str] = []
    matched_rows = 0
    for attachment in plan.attachments:
        imported_column = rename_map.get(attachment.supplemental_column or "")
        target_column = attachment.target_column
        if not imported_column or not target_column:
            continue

        imported_series = merged_df[imported_column]
        if target_column in merged_df.columns:
            merged_df[target_column] = merged_df[target_column].where(
                merged_df[target_column].notna(),
                imported_series,
            )
        else:
            merged_df[target_column] = imported_series

        non_null_count = int(merged_df[target_column].notna().sum())
        coverage_ratio = (
            round(non_null_count / max(len(primary_df), 1), 4)
            if len(primary_df) > 0
            else 0.0
        )
        matched_rows = max(matched_rows, int(imported_series.notna().sum()))
        cloned = SupplementalColumnAttachment.from_dict(attachment.to_dict())
        cloned.status = "imported" if non_null_count > 0 else "unmatched"
        cloned.coverage_ratio = coverage_ratio
        cloned.non_null_value_count = non_null_count
        attachments.append(cloned)
        if non_null_count > 0 and target_column not in merged_columns:
            merged_columns.append(target_column)

    if matched_rows == 0 or not merged_columns:
        return SupplementalMergeResult(
            success=False,
            failure_reason=(
                "The supplemental file was aligned by key, but none of the targeted canonical fields "
                "received matched values."
            ),
            attachments=attachments,
            merge_stats={
                "primary_row_count": int(len(primary_df)),
                "supplemental_row_count": int(len(supplemental_df)),
                "matched_primary_rows": matched_rows,
            },
        )

    merged_df = merged_df.drop(columns=["__merge_key__", *rename_map.values()], errors="ignore")
    output_path = _build_materialized_output_path(
        outputs_dir=outputs_dir,
        primary_file_ref=plan.primary_file_ref or "primary.csv",
        supplemental_file_ref=plan.supplemental_file_ref or "supplemental.csv",
        session_id=session_id,
    )
    merged_df.to_csv(output_path, index=False)

    return SupplementalMergeResult(
        success=True,
        merged_columns=merged_columns,
        materialized_primary_file_ref=str(output_path),
        attachments=attachments,
        merge_stats={
            "primary_row_count": int(len(primary_df)),
            "supplemental_row_count": int(len(supplemental_df)),
            "matched_primary_rows": matched_rows,
            "merge_key": merge_key.to_dict(),
            "coverage_by_target": {
                attachment.canonical_field: attachment.coverage_ratio
                for attachment in attachments
                if attachment.canonical_field
            },
        },
    )


def _recompute_diagnostics_status(field_statuses: Sequence[Dict[str, Any]]) -> str:
    normalized_statuses = [
        str(item.get("status") or "").strip().lower()
        for item in field_statuses
        if isinstance(item, dict)
    ]
    if normalized_statuses and all(status == "present" for status in normalized_statuses):
        return "complete"
    if any(status in {"present", "derivable"} for status in normalized_statuses):
        return "partial"
    return "insufficient"


def apply_supplemental_merge_analysis_refresh(
    analysis_dict: Dict[str, Any],
    *,
    plan: SupplementalMergePlan,
    result: SupplementalMergeResult,
) -> Dict[str, Any]:
    analysis = dict(analysis_dict or {})
    task_type = _clean_text(analysis.get("task_type"))
    mapping_key = None
    if task_type == "macro_emission":
        mapping_key = "macro_mapping"
    elif task_type == "micro_emission":
        mapping_key = "micro_mapping"

    if mapping_key is not None:
        updated_mapping = _clean_dict(analysis.get(mapping_key))
    else:
        updated_mapping = _clean_dict(analysis.get("column_mapping"))
    for attachment in result.attachments:
        if attachment.target_column and attachment.canonical_field:
            updated_mapping.setdefault(attachment.target_column, attachment.canonical_field)

    analysis["column_mapping"] = dict(updated_mapping)
    if mapping_key is not None:
        analysis[mapping_key] = dict(updated_mapping)

    diagnostics = _clean_dict(analysis.get("missing_field_diagnostics"))
    field_statuses = _clean_dict_list(diagnostics.get("required_field_statuses"))
    if field_statuses:
        attachment_by_field = {
            attachment.canonical_field: attachment
            for attachment in result.attachments
            if attachment.canonical_field
        }
        refreshed_statuses: List[Dict[str, Any]] = []
        for item in field_statuses:
            field_name = _clean_text(item.get("field"))
            attachment = attachment_by_field.get(field_name or "")
            if attachment is None:
                refreshed_statuses.append(dict(item))
                continue

            patched = dict(item)
            patched["mapped_from"] = attachment.target_column or attachment.supplemental_column
            coverage_ratio = attachment.coverage_ratio or 0.0
            if coverage_ratio >= 0.999:
                patched["status"] = "present"
                patched["reason"] = (
                    f"Resolved by bounded supplemental merge via key "
                    f"'{plan.merge_keys[0].primary_column}' -> '{plan.merge_keys[0].supplemental_column}'."
                )
                patched["candidate_columns"] = []
            elif coverage_ratio > 0.0:
                patched["status"] = "partial_merge"
                patched["reason"] = (
                    f"Supplemental merge imported '{attachment.supplemental_column}', "
                    f"but only covered {coverage_ratio:.0%} of primary rows."
                )
            else:
                patched["status"] = "missing"
                patched["reason"] = (
                    f"Supplemental merge targeted '{attachment.supplemental_column}', "
                    "but no aligned values were materialized."
                )
            refreshed_statuses.append(patched)

        diagnostics["required_field_statuses"] = refreshed_statuses
        diagnostics["missing_fields"] = [
            item
            for item in refreshed_statuses
            if str(item.get("status") or "").strip().lower() != "present"
        ]
        diagnostics["status"] = _recompute_diagnostics_status(refreshed_statuses)
        diagnostics["supplemental_merge_summary"] = {
            "merge_key": plan.merge_keys[0].to_dict() if plan.merge_keys else None,
            "merged_columns": list(result.merged_columns),
            "coverage_by_target": {
                attachment.canonical_field: attachment.coverage_ratio
                for attachment in result.attachments
                if attachment.canonical_field
            },
        }
        analysis["missing_field_diagnostics"] = diagnostics

    evidence = [str(item) for item in (analysis.get("evidence") or []) if item is not None]
    evidence.append(
        "supplemental_merge="
        + ",".join(
            f"{attachment.canonical_field}:{attachment.coverage_ratio}"
            for attachment in result.attachments
            if attachment.canonical_field
        )
    )
    analysis["evidence"] = evidence
    analysis["supplemental_merge_plan"] = plan.to_dict()
    analysis["supplemental_merge_result"] = result.to_dict()
    analysis["supplemental_column_attachments"] = [
        attachment.to_dict() for attachment in result.attachments
    ]
    return analysis
