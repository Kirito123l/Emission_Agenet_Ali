from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from services.standardizer import get_standardizer


class FallbackReason(str, Enum):
    LOW_TASK_CONFIDENCE = "low_task_confidence"
    TASK_TYPE_UNKNOWN = "task_type_unknown"
    INSUFFICIENT_COLUMN_MAPPING = "insufficient_column_mapping"
    ZIP_GIS_STRUCTURE_COMPLEX = "zip_gis_structure_complex"
    NONSTANDARD_COLUMN_NAMES = "nonstandard_column_names"


@dataclass
class FileAnalysisFallbackDecision:
    should_use_fallback: bool
    reasons: List[FallbackReason] = field(default_factory=list)
    reason_details: List[str] = field(default_factory=list)
    rule_task_type: Optional[str] = None
    rule_confidence: Optional[float] = None
    unresolved_columns: List[str] = field(default_factory=list)
    dominant_task_type: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "should_use_fallback": self.should_use_fallback,
            "reasons": [reason.value for reason in self.reasons],
            "reason_details": list(self.reason_details),
            "rule_task_type": self.rule_task_type,
            "rule_confidence": self.rule_confidence,
            "unresolved_columns": list(self.unresolved_columns),
            "dominant_task_type": self.dominant_task_type,
        }

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "FileAnalysisFallbackDecision":
        data = payload if isinstance(payload, dict) else {}
        reasons: List[FallbackReason] = []
        for item in data.get("reasons") or []:
            try:
                reasons.append(FallbackReason(str(item)))
            except ValueError:
                continue
        return cls(
            should_use_fallback=bool(data.get("should_use_fallback", False)),
            reasons=reasons,
            reason_details=[str(item) for item in data.get("reason_details") or []],
            rule_task_type=str(data.get("rule_task_type")).strip() if data.get("rule_task_type") is not None else None,
            rule_confidence=_safe_float(data.get("rule_confidence")),
            unresolved_columns=[str(item) for item in data.get("unresolved_columns") or []],
            dominant_task_type=(
                str(data.get("dominant_task_type")).strip()
                if data.get("dominant_task_type") is not None
                else None
            ),
        )


@dataclass
class LLMFileAnalysisResult:
    task_type: str
    confidence: float
    column_mapping: Dict[str, str] = field(default_factory=dict)  # canonical_field -> source_column
    reasoning_summary: Optional[str] = None
    evidence: List[str] = field(default_factory=list)
    fallback_used: bool = True
    unresolved_columns: List[str] = field(default_factory=list)
    candidate_task_types: List[str] = field(default_factory=list)
    selected_primary_table: Optional[str] = None
    dataset_roles: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_type": self.task_type,
            "confidence": self.confidence,
            "column_mapping": dict(self.column_mapping),
            "reasoning_summary": self.reasoning_summary,
            "evidence": list(self.evidence),
            "fallback_used": self.fallback_used,
            "unresolved_columns": list(self.unresolved_columns),
            "candidate_task_types": list(self.candidate_task_types),
            "selected_primary_table": self.selected_primary_table,
            "dataset_roles": [dict(item) for item in self.dataset_roles],
        }

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "LLMFileAnalysisResult":
        data = payload if isinstance(payload, dict) else {}
        return cls(
            task_type=str(data.get("task_type") or "unknown").strip() or "unknown",
            confidence=max(0.0, min(1.0, _safe_float(data.get("confidence"), 0.0))),
            column_mapping={
                str(key): str(value)
                for key, value in (data.get("column_mapping") or {}).items()
                if key is not None and value is not None
            },
            reasoning_summary=(
                str(data.get("reasoning_summary")).strip()
                if data.get("reasoning_summary") is not None
                else None
            ),
            evidence=[str(item) for item in data.get("evidence") or []],
            fallback_used=bool(data.get("fallback_used", True)),
            unresolved_columns=[str(item) for item in data.get("unresolved_columns") or []],
            candidate_task_types=[str(item) for item in data.get("candidate_task_types") or []],
            selected_primary_table=(
                str(data.get("selected_primary_table")).strip()
                if data.get("selected_primary_table") is not None
                else None
            ),
            dataset_roles=[
                dict(item)
                for item in data.get("dataset_roles") or []
                if isinstance(item, dict)
            ],
        )


@dataclass
class MergedFileAnalysisResult:
    analysis: Dict[str, Any]
    used_fallback: bool
    merge_strategy: str
    reasoning_summary: Optional[str] = None
    decision: Optional[FileAnalysisFallbackDecision] = None
    fallback_result: Optional[LLMFileAnalysisResult] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "analysis": dict(self.analysis),
            "used_fallback": self.used_fallback,
            "merge_strategy": self.merge_strategy,
            "reasoning_summary": self.reasoning_summary,
            "decision": self.decision.to_dict() if self.decision else None,
            "fallback_result": self.fallback_result.to_dict() if self.fallback_result else None,
        }


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def get_allowed_task_types() -> List[str]:
    return ["macro_emission", "micro_emission", "unknown"]


def get_allowed_semantic_fields() -> Dict[str, List[str]]:
    standardizer = get_standardizer()
    task_fields: Dict[str, List[str]] = {}
    for task_type in ("macro_emission", "micro_emission"):
        patterns = standardizer.column_patterns.get(task_type, {})
        fields = sorted(
            {
                str(field_cfg.get("standard"))
                for field_cfg in patterns.values()
                if isinstance(field_cfg, dict) and field_cfg.get("standard")
            }
        )
        task_fields[task_type] = fields
    return task_fields


def get_allowed_dataset_roles() -> List[str]:
    return [
        "primary_analysis",
        "secondary_analysis",
        "trajectory_candidate",
        "spatial_context",
        "supporting_component",
        "supporting_asset",
        "metadata",
    ]


def invert_rule_mapping(source_to_canonical: Optional[Dict[str, str]]) -> Dict[str, str]:
    return {
        str(canonical): str(source)
        for source, canonical in (source_to_canonical or {}).items()
        if source is not None and canonical is not None
    }


def derive_primary_task_type(rule_analysis: Dict[str, Any]) -> Optional[str]:
    task_type = str(rule_analysis.get("task_type") or "").strip()
    if task_type in {"macro_emission", "micro_emission"}:
        return task_type

    macro_mapping = rule_analysis.get("macro_mapping") or {}
    micro_mapping = rule_analysis.get("micro_mapping") or {}
    if len(macro_mapping) > len(micro_mapping):
        return "macro_emission"
    if len(micro_mapping) > len(macro_mapping):
        return "micro_emission"
    return None


def collect_unresolved_columns(
    rule_analysis: Dict[str, Any],
    *,
    task_type: Optional[str] = None,
) -> List[str]:
    columns = [str(item) for item in rule_analysis.get("columns") or []]
    primary_task = task_type or derive_primary_task_type(rule_analysis)

    mapped_columns: set[str] = set()
    if primary_task == "macro_emission":
        mapped_columns = {str(key) for key in (rule_analysis.get("macro_mapping") or {}).keys()}
    elif primary_task == "micro_emission":
        mapped_columns = {str(key) for key in (rule_analysis.get("micro_mapping") or {}).keys()}
    else:
        mapped_columns = {
            str(key)
            for mapping in (
                rule_analysis.get("macro_mapping") or {},
                rule_analysis.get("micro_mapping") or {},
            )
            for key in mapping.keys()
        }

    return [column for column in columns if column not in mapped_columns]


def should_use_llm_fallback(
    rule_analysis: Dict[str, Any],
    *,
    confidence_threshold: float = 0.72,
    allow_zip_table_selection: bool = True,
) -> FileAnalysisFallbackDecision:
    rule_task_type = str(rule_analysis.get("task_type") or "unknown").strip() or "unknown"
    rule_confidence = _safe_float(rule_analysis.get("confidence"), 0.0) or 0.0
    dominant_task_type = derive_primary_task_type(rule_analysis)
    unresolved_columns = collect_unresolved_columns(rule_analysis, task_type=dominant_task_type)
    reasons: List[FallbackReason] = []
    reason_details: List[str] = []
    columns = [str(item) for item in rule_analysis.get("columns") or []]

    if rule_task_type == "unknown":
        reasons.append(FallbackReason.TASK_TYPE_UNKNOWN)
        reason_details.append("Rule analyzer could not determine a stable task_type.")

    if rule_confidence < confidence_threshold and not _rule_mapping_is_complete(rule_analysis):
        reasons.append(FallbackReason.LOW_TASK_CONFIDENCE)
        reason_details.append(
            f"Rule confidence {rule_confidence:.2f} is below the fallback threshold {confidence_threshold:.2f}."
        )

    if _has_insufficient_mapping(rule_analysis, unresolved_columns):
        reasons.append(FallbackReason.INSUFFICIENT_COLUMN_MAPPING)
        reason_details.append(
            "Rule-based column mapping left key fields unresolved or did not satisfy required-field completeness."
        )

    if allow_zip_table_selection and _zip_gis_structure_is_complex(rule_analysis):
        reasons.append(FallbackReason.ZIP_GIS_STRUCTURE_COMPLEX)
        reason_details.append(
            "ZIP/GIS package contains multiple candidate tables or geospatial components that need semantic fallback."
        )

    if _has_nonstandard_column_risk(columns, rule_analysis, unresolved_columns):
        reasons.append(FallbackReason.NONSTANDARD_COLUMN_NAMES)
        reason_details.append(
            "Most unresolved columns look like abbreviations, pinyin, or internal project-specific names."
        )

    unique_reasons: List[FallbackReason] = []
    for reason in reasons:
        if reason not in unique_reasons:
            unique_reasons.append(reason)

    return FileAnalysisFallbackDecision(
        should_use_fallback=bool(unique_reasons),
        reasons=unique_reasons,
        reason_details=reason_details,
        rule_task_type=rule_task_type,
        rule_confidence=round(rule_confidence, 3),
        unresolved_columns=unresolved_columns,
        dominant_task_type=dominant_task_type,
    )


def build_file_analysis_fallback_payload(
    rule_analysis: Dict[str, Any],
    decision: FileAnalysisFallbackDecision,
    *,
    max_sample_rows: int = 3,
    max_columns: int = 25,
) -> Dict[str, Any]:
    allowed_fields = get_allowed_semantic_fields()
    return {
        "filename": rule_analysis.get("filename"),
        "file_path": rule_analysis.get("file_path"),
        "format": rule_analysis.get("format"),
        "row_count": rule_analysis.get("row_count"),
        "columns": [str(item) for item in (rule_analysis.get("columns") or [])[:max_columns]],
        "sample_rows": (rule_analysis.get("sample_rows") or [])[:max_sample_rows],
        "zip_contents": [str(item) for item in rule_analysis.get("zip_contents") or []],
        "candidate_tables": [str(item) for item in rule_analysis.get("candidate_tables") or []],
        "selected_primary_table": rule_analysis.get("selected_primary_table"),
        "dataset_roles": [dict(item) for item in rule_analysis.get("dataset_roles") or []],
        "dataset_role_summary": dict(rule_analysis.get("dataset_role_summary") or {}),
        "geometry_types": [str(item) for item in rule_analysis.get("geometry_types") or []],
        "spatial_metadata": dict(rule_analysis.get("spatial_metadata") or {}),
        "rule_analysis": {
            "task_type": rule_analysis.get("task_type"),
            "confidence": rule_analysis.get("confidence"),
            "column_mapping": dict(rule_analysis.get("column_mapping") or {}),
            "macro_mapping": dict(rule_analysis.get("macro_mapping") or {}),
            "micro_mapping": dict(rule_analysis.get("micro_mapping") or {}),
            "micro_has_required": rule_analysis.get("micro_has_required"),
            "macro_has_required": rule_analysis.get("macro_has_required"),
            "evidence": [str(item) for item in rule_analysis.get("evidence") or []][:8],
            "unresolved_columns": decision.unresolved_columns,
            "missing_field_diagnostics": dict(rule_analysis.get("missing_field_diagnostics") or {}),
        },
        "fallback_decision": decision.to_dict(),
        "allowed_task_types": get_allowed_task_types(),
        "allowed_semantic_fields": allowed_fields,
        "allowed_dataset_roles": get_allowed_dataset_roles(),
    }


def parse_llm_file_analysis_result(
    payload: Dict[str, Any],
    rule_analysis: Dict[str, Any],
) -> LLMFileAnalysisResult:
    if not isinstance(payload, dict):
        raise ValueError("LLM file analysis result must be a JSON object.")

    result = LLMFileAnalysisResult.from_dict(payload)
    allowed_task_types = set(get_allowed_task_types())
    if result.task_type not in allowed_task_types:
        raise ValueError(f"Unsupported task_type '{result.task_type}' returned by LLM fallback.")

    allowed_fields = get_allowed_semantic_fields()
    available_columns = {str(item) for item in rule_analysis.get("columns") or []}
    allowed_union = set(allowed_fields["macro_emission"]) | set(allowed_fields["micro_emission"])

    for canonical_field, source_column in result.column_mapping.items():
        if canonical_field not in allowed_union:
            raise ValueError(f"Unsupported canonical field '{canonical_field}' returned by LLM fallback.")
        if available_columns and source_column not in available_columns:
            raise ValueError(
                f"Fallback column mapping references unknown source column '{source_column}'."
            )

    candidate_tables = {
        str(item)
        for item in (rule_analysis.get("candidate_tables") or rule_analysis.get("zip_contents") or [])
    }
    if result.selected_primary_table and candidate_tables and result.selected_primary_table not in candidate_tables:
        raise ValueError(
            f"Fallback selected_primary_table '{result.selected_primary_table}' is not in the ZIP candidate set."
        )

    cleaned_unresolved = []
    for column in result.unresolved_columns:
        if not available_columns or column in available_columns:
            cleaned_unresolved.append(column)
    result.unresolved_columns = cleaned_unresolved
    result.evidence = [item for item in result.evidence if item]
    result.candidate_task_types = [
        task_type for task_type in result.candidate_task_types if task_type in allowed_task_types
    ]
    allowed_roles = set(get_allowed_dataset_roles())
    cleaned_roles: List[Dict[str, Any]] = []
    seen_role_names: set[str] = set()
    for entry in result.dataset_roles:
        dataset_name = str(entry.get("dataset_name") or "").strip()
        role = str(entry.get("role") or "").strip()
        if not dataset_name or not role or role not in allowed_roles:
            continue
        if candidate_tables and dataset_name not in candidate_tables and dataset_name not in {
            str(item) for item in (rule_analysis.get("zip_contents") or [])
        }:
            continue
        key = f"{dataset_name}:{role}"
        if key in seen_role_names:
            continue
        seen_role_names.add(key)
        cleaned_roles.append(
            {
                "dataset_name": dataset_name,
                "role": role,
                "reason": str(entry.get("reason") or "").strip() or None,
                "confidence": _safe_float(entry.get("confidence")),
                "selected": bool(entry.get("selected", False)),
                "format": str(entry.get("format") or "").strip() or None,
                "task_type": str(entry.get("task_type") or "").strip() or None,
            }
        )
    result.dataset_roles = cleaned_roles
    result.confidence = max(0.0, min(1.0, result.confidence))
    return result


def merge_rule_and_fallback_analysis(
    rule_analysis: Dict[str, Any],
    llm_result: LLMFileAnalysisResult,
    *,
    min_fallback_confidence: float = 0.55,
) -> MergedFileAnalysisResult:
    analysis = dict(rule_analysis or {})
    rule_task_type = str(analysis.get("task_type") or "unknown").strip() or "unknown"
    rule_confidence = _safe_float(analysis.get("confidence"), 0.0) or 0.0

    if llm_result.confidence < min_fallback_confidence:
        return MergedFileAnalysisResult(
            analysis=analysis,
            used_fallback=False,
            merge_strategy="rule_only",
            reasoning_summary=(
                f"LLM fallback confidence {llm_result.confidence:.2f} was below the minimum "
                f"accepted threshold {min_fallback_confidence:.2f}; kept rule analysis."
            ),
            fallback_result=llm_result,
        )

    final_task_type = _select_final_task_type(rule_analysis, llm_result)
    mapping_task_type = final_task_type if final_task_type in {"macro_emission", "micro_emission"} else llm_result.task_type
    merged_source_mapping: Dict[str, str] = {}
    merge_strategy = "fallback_override"

    if mapping_task_type in {"macro_emission", "micro_emission"}:
        rule_mapping_key = "macro_mapping" if mapping_task_type == "macro_emission" else "micro_mapping"
        current_rule_mapping = analysis.get(rule_mapping_key) or {}
        rule_canonical_mapping = invert_rule_mapping(current_rule_mapping)
        merged_canonical_mapping = dict(rule_canonical_mapping)

        for canonical_field, source_column in llm_result.column_mapping.items():
            if canonical_field not in merged_canonical_mapping:
                merged_canonical_mapping[canonical_field] = source_column

        merged_source_mapping = {
            str(source_column): str(canonical_field)
            for canonical_field, source_column in merged_canonical_mapping.items()
        }
        merge_strategy = "fallback_merge" if current_rule_mapping else "fallback_override"

        if mapping_task_type == "macro_emission":
            analysis["macro_mapping"] = merged_source_mapping
            analysis["macro_has_required"] = _has_required_columns_for_task(merged_source_mapping, mapping_task_type)
        else:
            analysis["micro_mapping"] = merged_source_mapping
            analysis["micro_has_required"] = _has_required_columns_for_task(merged_source_mapping, mapping_task_type)
        analysis["column_mapping"] = merged_source_mapping

    analysis["task_type"] = final_task_type
    analysis["confidence"] = max(rule_confidence, llm_result.confidence) if final_task_type == rule_task_type else llm_result.confidence
    analysis["fallback_used"] = True
    analysis["analysis_strategy"] = merge_strategy
    analysis["fallback_confidence"] = llm_result.confidence
    analysis["fallback_reasoning_summary"] = llm_result.reasoning_summary
    analysis["fallback_column_mapping"] = dict(llm_result.column_mapping)
    analysis["selected_primary_table"] = llm_result.selected_primary_table or analysis.get("selected_primary_table")
    if llm_result.dataset_roles:
        analysis["dataset_roles"] = [dict(item) for item in llm_result.dataset_roles]
        analysis["dataset_role_summary"] = {
            "strategy": "llm_fallback" if not analysis.get("dataset_role_summary") else "rule_plus_fallback",
            "ambiguous": False,
            "selected_primary_table": analysis.get("selected_primary_table"),
            "selection_score_gap": None,
            "role_fallback_eligible": False,
        }
    analysis["unresolved_columns"] = collect_unresolved_columns(analysis, task_type=final_task_type)

    evidence = [str(item) for item in analysis.get("evidence") or []]
    if llm_result.reasoning_summary:
        evidence.append(f"LLM fallback: {llm_result.reasoning_summary}")
    for item in llm_result.evidence:
        if item not in evidence:
            evidence.append(item)
    analysis["evidence"] = evidence[:16]

    return MergedFileAnalysisResult(
        analysis=analysis,
        used_fallback=True,
        merge_strategy=merge_strategy,
        reasoning_summary=llm_result.reasoning_summary,
        fallback_result=llm_result,
    )


def _rule_mapping_is_complete(rule_analysis: Dict[str, Any]) -> bool:
    task_type = str(rule_analysis.get("task_type") or "unknown").strip()
    if task_type == "macro_emission":
        return bool(rule_analysis.get("macro_has_required"))
    if task_type == "micro_emission":
        return bool(rule_analysis.get("micro_has_required"))
    return False


def _has_insufficient_mapping(
    rule_analysis: Dict[str, Any],
    unresolved_columns: List[str],
) -> bool:
    columns = [str(item) for item in rule_analysis.get("columns") or []]
    if not columns:
        return False

    task_type = str(rule_analysis.get("task_type") or "unknown").strip() or "unknown"
    if task_type == "macro_emission":
        mapped_count = len(rule_analysis.get("macro_mapping") or {})
        if rule_analysis.get("macro_has_required"):
            return False
        return mapped_count < 2 or len(unresolved_columns) >= max(2, len(columns) - mapped_count)

    if task_type == "micro_emission":
        mapped_count = len(rule_analysis.get("micro_mapping") or {})
        if rule_analysis.get("micro_has_required"):
            return False
        return mapped_count < 2 or len(unresolved_columns) >= max(2, len(columns) - mapped_count)

    max_mapping_count = max(
        len(rule_analysis.get("macro_mapping") or {}),
        len(rule_analysis.get("micro_mapping") or {}),
    )
    return len(columns) >= 3 and max_mapping_count < 2


def _zip_gis_structure_is_complex(rule_analysis: Dict[str, Any]) -> bool:
    file_format = str(rule_analysis.get("format") or "").strip().lower()
    candidate_tables = rule_analysis.get("candidate_tables") or []
    geometry_types = rule_analysis.get("geometry_types") or []
    role_summary = rule_analysis.get("dataset_role_summary") or {}
    return (
        file_format.startswith("zip")
        and len(candidate_tables) > 1
        and bool(role_summary.get("ambiguous", True) or not role_summary.get("selected_primary_table"))
    ) or (
        bool(geometry_types)
        and not _rule_mapping_is_complete(rule_analysis)
    )


def _has_nonstandard_column_risk(
    columns: List[str],
    rule_analysis: Dict[str, Any],
    unresolved_columns: List[str],
) -> bool:
    if len(columns) < 3 or len(unresolved_columns) < max(2, len(columns) // 2):
        return False

    weird_like = 0
    for column in unresolved_columns:
        normalized = str(column).strip().lower().replace("-", "_")
        if len(normalized) <= 6:
            weird_like += 1
            continue
        if normalized.replace("_", "").isalnum() and not any(ch in normalized for ch in ("speed", "flow", "length", "time")):
            weird_like += 1
    return weird_like >= max(2, len(unresolved_columns) // 2)


def _has_required_columns_for_task(mapping: Dict[str, str], task_type: str) -> bool:
    standardizer = get_standardizer()
    required = standardizer.get_required_columns(task_type)
    mapped_fields = set(mapping.values())
    return all(field in mapped_fields for field in required)


def _select_final_task_type(rule_analysis: Dict[str, Any], llm_result: LLMFileAnalysisResult) -> str:
    rule_task_type = str(rule_analysis.get("task_type") or "unknown").strip() or "unknown"
    rule_confidence = _safe_float(rule_analysis.get("confidence"), 0.0) or 0.0

    if llm_result.task_type == "unknown":
        return rule_task_type
    if rule_task_type == "unknown":
        return llm_result.task_type
    if llm_result.task_type == rule_task_type:
        return rule_task_type
    if llm_result.confidence >= max(rule_confidence + 0.05, 0.68):
        return llm_result.task_type
    return rule_task_type
