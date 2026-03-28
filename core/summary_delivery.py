from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.artifact_memory import (
    ArtifactDeliveryStatus,
    ArtifactMemoryState,
    ArtifactRecord,
    ArtifactType,
    build_artifact_record,
    coerce_artifact_memory_state,
)
from core.intent_resolution import DeliverableIntentType, ProgressIntentType


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


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _sanitize_metric_token(value: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip())
    token = re.sub(r"_+", "_", token).strip("_")
    return token or "metric"


class SummaryDeliveryType(str, Enum):
    TOPK_SUMMARY_TABLE = "topk_summary_table"
    RANKED_BAR_CHART = "ranked_bar_chart"
    QUICK_STRUCTURED_SUMMARY = "quick_structured_summary"


@dataclass
class SummaryDeliveryRequest:
    delivery_type: Optional[SummaryDeliveryType] = None
    source_result_type: Optional[str] = None
    ranking_metric: Optional[str] = None
    topk: int = 5
    artifact_family: Optional[str] = None
    related_task_type: Optional[str] = None
    delivery_reason: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "SummaryDeliveryRequest":
        data = payload if isinstance(payload, dict) else {}
        delivery_type = None
        delivery_value = _clean_text(data.get("delivery_type"))
        if delivery_value:
            try:
                delivery_type = SummaryDeliveryType(delivery_value)
            except ValueError:
                delivery_type = None
        return cls(
            delivery_type=delivery_type,
            source_result_type=_clean_text(data.get("source_result_type")),
            ranking_metric=_clean_text(data.get("ranking_metric")),
            topk=max(1, _safe_int(data.get("topk"), 5)),
            artifact_family=_clean_text(data.get("artifact_family")),
            related_task_type=_clean_text(data.get("related_task_type")),
            delivery_reason=_clean_text(data.get("delivery_reason")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "delivery_type": self.delivery_type.value if self.delivery_type is not None else None,
            "source_result_type": self.source_result_type,
            "ranking_metric": self.ranking_metric,
            "topk": self.topk,
            "artifact_family": self.artifact_family,
            "related_task_type": self.related_task_type,
            "delivery_reason": self.delivery_reason,
        }


@dataclass
class SummaryDeliveryDecision:
    selected_delivery_type: Optional[SummaryDeliveryType] = None
    confidence: float = 0.0
    reason: Optional[str] = None
    ranking_metric: Optional[str] = None
    topk: int = 5
    should_generate_downloadable_table: bool = False
    should_generate_chart: bool = False
    should_generate_text_summary: bool = False
    switched_from_delivery_type: Optional[str] = None
    suppressed_by_artifact_memory: bool = False

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "SummaryDeliveryDecision":
        data = payload if isinstance(payload, dict) else {}
        selected = None
        selected_value = _clean_text(data.get("selected_delivery_type"))
        if selected_value:
            try:
                selected = SummaryDeliveryType(selected_value)
            except ValueError:
                selected = None
        return cls(
            selected_delivery_type=selected,
            confidence=_clamp_confidence(data.get("confidence")),
            reason=_clean_text(data.get("reason")),
            ranking_metric=_clean_text(data.get("ranking_metric")),
            topk=max(1, _safe_int(data.get("topk"), 5)),
            should_generate_downloadable_table=bool(data.get("should_generate_downloadable_table", False)),
            should_generate_chart=bool(data.get("should_generate_chart", False)),
            should_generate_text_summary=bool(data.get("should_generate_text_summary", False)),
            switched_from_delivery_type=_clean_text(data.get("switched_from_delivery_type")),
            suppressed_by_artifact_memory=bool(data.get("suppressed_by_artifact_memory", False)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_delivery_type": (
                self.selected_delivery_type.value if self.selected_delivery_type is not None else None
            ),
            "confidence": self.confidence,
            "reason": self.reason,
            "ranking_metric": self.ranking_metric,
            "topk": self.topk,
            "should_generate_downloadable_table": self.should_generate_downloadable_table,
            "should_generate_chart": self.should_generate_chart,
            "should_generate_text_summary": self.should_generate_text_summary,
            "switched_from_delivery_type": self.switched_from_delivery_type,
            "suppressed_by_artifact_memory": self.suppressed_by_artifact_memory,
        }


@dataclass
class SummaryDeliveryContext:
    user_message: Optional[str] = None
    current_task_type: Optional[str] = None
    deliverable_intent: DeliverableIntentType = DeliverableIntentType.UNKNOWN
    progress_intent: ProgressIntentType = ProgressIntentType.ASK_CLARIFY
    has_geometry_support: bool = False
    source_result_type: Optional[str] = None
    source_tool_name: Optional[str] = None
    source_label: Optional[str] = None
    source_result_summary: Dict[str, Any] = field(default_factory=dict)
    available_metrics: List[str] = field(default_factory=list)
    artifact_memory_summary: Dict[str, Any] = field(default_factory=dict)
    raw_source_result: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "SummaryDeliveryContext":
        data = payload if isinstance(payload, dict) else {}
        deliverable_value = data.get("deliverable_intent") or DeliverableIntentType.UNKNOWN.value
        progress_value = data.get("progress_intent") or ProgressIntentType.ASK_CLARIFY.value
        try:
            deliverable = DeliverableIntentType(str(deliverable_value).strip())
        except ValueError:
            deliverable = DeliverableIntentType.UNKNOWN
        try:
            progress = ProgressIntentType(str(progress_value).strip())
        except ValueError:
            progress = ProgressIntentType.ASK_CLARIFY
        return cls(
            user_message=_clean_text(data.get("user_message")),
            current_task_type=_clean_text(data.get("current_task_type")),
            deliverable_intent=deliverable,
            progress_intent=progress,
            has_geometry_support=bool(data.get("has_geometry_support", False)),
            source_result_type=_clean_text(data.get("source_result_type")),
            source_tool_name=_clean_text(data.get("source_tool_name")),
            source_label=_clean_text(data.get("source_label")),
            source_result_summary=_clean_dict(data.get("source_result_summary")),
            available_metrics=_clean_list(data.get("available_metrics")),
            artifact_memory_summary=_clean_dict(data.get("artifact_memory_summary")),
            raw_source_result=_clean_dict(data.get("raw_source_result")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_message": self.user_message,
            "current_task_type": self.current_task_type,
            "deliverable_intent": self.deliverable_intent.value,
            "progress_intent": self.progress_intent.value,
            "has_geometry_support": self.has_geometry_support,
            "source_result_type": self.source_result_type,
            "source_tool_name": self.source_tool_name,
            "source_label": self.source_label,
            "source_result_summary": dict(self.source_result_summary),
            "available_metrics": list(self.available_metrics),
            "artifact_memory_summary": dict(self.artifact_memory_summary),
        }


@dataclass
class SummaryDeliveryPlan:
    request: SummaryDeliveryRequest = field(default_factory=SummaryDeliveryRequest)
    decision: SummaryDeliveryDecision = field(default_factory=SummaryDeliveryDecision)
    source_result_type: Optional[str] = None
    source_tool_name: Optional[str] = None
    source_label: Optional[str] = None
    artifact_family: Optional[str] = None
    merge_with_existing_table_preview: bool = False
    preconditions: List[str] = field(default_factory=list)
    plan_status: str = "not_applicable"
    artifact_repeat_detected: bool = False
    suppression_reason: Optional[str] = None
    user_visible_summary: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "SummaryDeliveryPlan":
        data = payload if isinstance(payload, dict) else {}
        return cls(
            request=SummaryDeliveryRequest.from_dict(data.get("request")),
            decision=SummaryDeliveryDecision.from_dict(data.get("decision")),
            source_result_type=_clean_text(data.get("source_result_type")),
            source_tool_name=_clean_text(data.get("source_tool_name")),
            source_label=_clean_text(data.get("source_label")),
            artifact_family=_clean_text(data.get("artifact_family")),
            merge_with_existing_table_preview=bool(data.get("merge_with_existing_table_preview", False)),
            preconditions=_clean_list(data.get("preconditions")),
            plan_status=_clean_text(data.get("plan_status")) or "not_applicable",
            artifact_repeat_detected=bool(data.get("artifact_repeat_detected", False)),
            suppression_reason=_clean_text(data.get("suppression_reason")),
            user_visible_summary=_clean_text(data.get("user_visible_summary")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "decision": self.decision.to_dict(),
            "source_result_type": self.source_result_type,
            "source_tool_name": self.source_tool_name,
            "source_label": self.source_label,
            "artifact_family": self.artifact_family,
            "merge_with_existing_table_preview": self.merge_with_existing_table_preview,
            "preconditions": list(self.preconditions),
            "plan_status": self.plan_status,
            "artifact_repeat_detected": self.artifact_repeat_detected,
            "suppression_reason": self.suppression_reason,
            "user_visible_summary": self.user_visible_summary,
        }


@dataclass
class SummaryDeliveryResult:
    success: bool = False
    artifact_records: List[ArtifactRecord] = field(default_factory=list)
    table_preview: Optional[Dict[str, Any]] = None
    chart_ref: Optional[Dict[str, Any]] = None
    summary_text: Optional[str] = None
    delivery_summary: Optional[str] = None
    download_file: Optional[Dict[str, Any]] = None
    failure_reason: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "SummaryDeliveryResult":
        data = payload if isinstance(payload, dict) else {}
        return cls(
            success=bool(data.get("success", False)),
            artifact_records=[
                ArtifactRecord.from_dict(item)
                for item in (data.get("artifact_records") or [])
                if isinstance(item, dict)
            ],
            table_preview=_clean_dict(data.get("table_preview")) or None,
            chart_ref=_clean_dict(data.get("chart_ref")) or None,
            summary_text=_clean_text(data.get("summary_text")),
            delivery_summary=_clean_text(data.get("delivery_summary")),
            download_file=_clean_dict(data.get("download_file")) or None,
            failure_reason=_clean_text(data.get("failure_reason")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "artifact_records": [item.to_dict() for item in self.artifact_records],
            "table_preview": dict(self.table_preview or {}),
            "chart_ref": dict(self.chart_ref or {}),
            "summary_text": self.summary_text,
            "delivery_summary": self.delivery_summary,
            "download_file": dict(self.download_file or {}),
            "failure_reason": self.failure_reason,
        }


_POLLUTANT_ALIASES: Dict[str, Sequence[str]] = {
    "CO2": ("co2", "co₂", "二氧化碳"),
    "NOx": ("nox", "氮氧化物"),
    "PM2.5": ("pm2.5", "pm25", "细颗粒物"),
    "PM10": ("pm10", "可吸入颗粒物"),
    "CO": ("co", "一氧化碳"),
    "VOC": ("voc", "挥发性有机物"),
    "SO2": ("so2", "二氧化硫"),
}


def _extract_emission_rows(result_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = result_payload.get("data") if isinstance(result_payload, dict) else {}
    rows = data.get("results") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    return [dict(item) for item in rows if isinstance(item, dict)]


def _extract_summary_block(result_payload: Dict[str, Any]) -> Dict[str, Any]:
    data = result_payload.get("data") if isinstance(result_payload, dict) else {}
    summary = data.get("summary") if isinstance(data, dict) else {}
    return dict(summary) if isinstance(summary, dict) else {}


def _extract_query_info(result_payload: Dict[str, Any]) -> Dict[str, Any]:
    data = result_payload.get("data") if isinstance(result_payload, dict) else {}
    query_info = data.get("query_info") if isinstance(data, dict) else {}
    return dict(query_info) if isinstance(query_info, dict) else {}


def _extract_available_metrics(result_payload: Dict[str, Any]) -> List[str]:
    metrics: List[str] = []
    seen = set()
    for row in _extract_emission_rows(result_payload)[:20]:
        totals = row.get("total_emissions_kg_per_hr")
        if isinstance(totals, dict):
            for pollutant in totals.keys():
                metric = f"{pollutant}_kg_h"
                if metric not in seen:
                    seen.add(metric)
                    metrics.append(metric)
        for key, value in row.items():
            key_text = _clean_text(key)
            if (
                key_text
                and key_text.endswith("_kg_h")
                and isinstance(value, (int, float))
                and key_text not in seen
            ):
                seen.add(key_text)
                metrics.append(key_text)
    summary = _extract_summary_block(result_payload)
    totals = summary.get("total_emissions_kg_per_hr")
    if isinstance(totals, dict):
        for pollutant in totals.keys():
            metric = f"{pollutant}_kg_h"
            if metric not in seen:
                seen.add(metric)
                metrics.append(metric)
    return metrics


def _detect_requested_pollutant(
    message: Optional[str],
    available_metrics: Sequence[str],
    result_payload: Dict[str, Any],
) -> Optional[str]:
    normalized = str(message or "").strip().lower()
    if normalized:
        for canonical, aliases in _POLLUTANT_ALIASES.items():
            if any(alias in normalized for alias in aliases):
                metric = f"{canonical}_kg_h"
                if metric in set(available_metrics):
                    return metric

    query_info = _extract_query_info(result_payload)
    pollutants = query_info.get("pollutants")
    if isinstance(pollutants, list):
        for pollutant in pollutants:
            metric = f"{pollutant}_kg_h"
            if metric in set(available_metrics):
                return metric

    for preferred in ("CO2_kg_h", "NOx_kg_h", "PM2.5_kg_h", "PM10_kg_h"):
        if preferred in set(available_metrics):
            return preferred
    return available_metrics[0] if available_metrics else None


def _parse_topk(message: Optional[str], default_topk: int) -> int:
    normalized = str(message or "").strip().lower()
    patterns = (
        r"top\s*[-]?\s*(\d{1,2})",
        r"前\s*(\d{1,2})",
        r"(\d{1,2})\s*个",
        r"(\d{1,2})\s*条",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return max(1, _safe_int(match.group(1), default_topk))
    return max(1, default_topk)


def _detect_requested_delivery_type(
    context: SummaryDeliveryContext,
    *,
    default_topk: int,
    enable_bar_chart: bool,
) -> Tuple[SummaryDeliveryType, int, str]:
    normalized = str(context.user_message or "").strip().lower()
    topk = _parse_topk(context.user_message, default_topk)

    if any(token in normalized for token in ("条形图", "柱状图", "bar chart", "chart", "画出来", "画个图", "图表")):
        if enable_bar_chart:
            return SummaryDeliveryType.RANKED_BAR_CHART, topk, "The user explicitly requested a chart-style ranked visualization."
        return SummaryDeliveryType.TOPK_SUMMARY_TABLE, topk, "The user requested a chart, but bar-chart delivery is disabled so the surface fell back to a ranked table."

    if any(
        token in normalized
        for token in ("top", "前", "排行", "排名", "高排", "摘要表", "summary table", "ranked table")
    ):
        return SummaryDeliveryType.TOPK_SUMMARY_TABLE, topk, "The user explicitly requested a ranked or Top-K summary table."

    if any(token in normalized for token in ("总结", "汇总", "摘要", "概览", "summary")):
        return SummaryDeliveryType.QUICK_STRUCTURED_SUMMARY, topk, "The user explicitly requested a concise structured summary."

    if context.deliverable_intent == DeliverableIntentType.QUICK_SUMMARY:
        return SummaryDeliveryType.QUICK_STRUCTURED_SUMMARY, topk, "Intent resolution biased this turn toward a concise structured summary."

    if context.deliverable_intent == DeliverableIntentType.DOWNLOADABLE_TABLE:
        return SummaryDeliveryType.TOPK_SUMMARY_TABLE, topk, "Intent resolution biased this turn toward a bounded ranked summary table."

    if context.deliverable_intent == DeliverableIntentType.CHART_OR_RANKED_SUMMARY:
        if enable_bar_chart:
            return SummaryDeliveryType.RANKED_BAR_CHART, topk, "Intent resolution biased this turn toward a non-spatial ranked chart/summary output."
        return SummaryDeliveryType.TOPK_SUMMARY_TABLE, topk, "Intent resolution biased this turn toward a ranked summary, but chart delivery is disabled."

    return SummaryDeliveryType.QUICK_STRUCTURED_SUMMARY, topk, "The bounded delivery surface fell back to a concise structured summary."


def _extract_link_identifier(row: Dict[str, Any], index: int) -> str:
    for key in ("link_id", "segment_id", "seg_id", "road_id", "id"):
        value = _clean_text(row.get(key))
        if value:
            return value
    return f"row_{index + 1}"


def _metric_components(metric_name: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    metric_text = _clean_text(metric_name)
    if not metric_text:
        return None, None
    if metric_text.endswith("_kg_h"):
        return metric_text[:-5], "kg/h"
    return metric_text, None


def _extract_metric_value(row: Dict[str, Any], metric_name: Optional[str]) -> Optional[float]:
    metric_text = _clean_text(metric_name)
    if not metric_text:
        return None
    if metric_text in row and isinstance(row.get(metric_text), (int, float)):
        return float(row[metric_text])
    pollutant, _unit = _metric_components(metric_text)
    totals = row.get("total_emissions_kg_per_hr")
    if pollutant and isinstance(totals, dict) and isinstance(totals.get(pollutant), (int, float)):
        return float(totals[pollutant])
    return None


def _format_metric_label(metric_name: Optional[str]) -> str:
    pollutant, unit = _metric_components(metric_name)
    if pollutant and unit:
        return f"{pollutant} ({unit})"
    return _clean_text(metric_name) or "metric"


def _rank_emission_rows(
    result_payload: Dict[str, Any],
    metric_name: Optional[str],
    *,
    topk: int,
) -> List[Dict[str, Any]]:
    ranked: List[Dict[str, Any]] = []
    for index, row in enumerate(_extract_emission_rows(result_payload)):
        metric_value = _extract_metric_value(row, metric_name)
        if metric_value is None:
            continue
        ranked.append(
            {
                "rank": 0,
                "link_id": _extract_link_identifier(row, index),
                "metric_value": metric_value,
                "row": row,
            }
        )
    ranked.sort(key=lambda item: item["metric_value"], reverse=True)
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index
    return ranked[: max(1, topk)]


def _build_table_preview(
    ranked_rows: Sequence[Dict[str, Any]],
    *,
    metric_name: str,
    include_download: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    metric_label = _format_metric_label(metric_name)
    preview_rows: List[Dict[str, Any]] = []
    for item in ranked_rows:
        preview_rows.append(
            {
                "rank": item["rank"],
                "link_id": item["link_id"],
                metric_name: round(float(item["metric_value"]), 4),
                "metric_label": metric_label,
            }
        )
    payload = {
        "type": SummaryDeliveryType.TOPK_SUMMARY_TABLE.value,
        "columns": ["rank", "link_id", metric_name, "metric_label"],
        "preview_rows": preview_rows,
        "total_rows": len(preview_rows),
        "total_columns": 4,
        "summary": {
            "ranking_metric": metric_name,
            "metric_label": metric_label,
            "topk": len(preview_rows),
        },
    }
    if include_download:
        payload["download"] = dict(include_download)
    return payload


def _build_ranked_bar_chart(
    ranked_rows: Sequence[Dict[str, Any]],
    *,
    metric_name: str,
) -> Dict[str, Any]:
    metric_label = _format_metric_label(metric_name)
    return {
        "type": SummaryDeliveryType.RANKED_BAR_CHART.value,
        "title": f"Top {len(ranked_rows)} 路段排放排名",
        "subtitle": f"按 {metric_label} 排序",
        "ranking_metric": metric_name,
        "metric_label": metric_label,
        "topk": len(ranked_rows),
        "categories": [str(item["link_id"]) for item in ranked_rows],
        "values": [round(float(item["metric_value"]), 4) for item in ranked_rows],
    }


def _build_quick_structured_summary(
    result_payload: Dict[str, Any],
    *,
    metric_name: Optional[str],
    topk_rows: Sequence[Dict[str, Any]],
) -> str:
    summary = _extract_summary_block(result_payload)
    metric_label = _format_metric_label(metric_name)
    total_links = _safe_int(summary.get("total_links"), len(_extract_emission_rows(result_payload)))
    lines = ["已基于当前结果生成结构化摘要："]
    if total_links:
        lines.append(f"- 覆盖对象数: {total_links}")

    if metric_name:
        pollutant, _unit = _metric_components(metric_name)
        totals = summary.get("total_emissions_kg_per_hr")
        if pollutant and isinstance(totals, dict) and totals.get(pollutant) is not None:
            lines.append(f"- 总 {metric_label}: {_safe_float(totals.get(pollutant)):.4f}")

    if topk_rows:
        top_item = topk_rows[0]
        lines.append(
            f"- 最高值对象: {top_item['link_id']} ({_format_metric_label(metric_name)} {float(top_item['metric_value']):.4f})"
        )
        if metric_name and len(topk_rows) > 1:
            total_topk = sum(float(item["metric_value"]) for item in topk_rows)
            lines.append(f"- Top {len(topk_rows)} 累计 {metric_label}: {total_topk:.4f}")

    if len(lines) == 1:
        raw_summary = _clean_text(result_payload.get("summary"))
        if raw_summary:
            lines.append(f"- {raw_summary}")
    return "\n".join(lines)


def _materialize_topk_csv(
    ranked_rows: Sequence[Dict[str, Any]],
    *,
    metric_name: str,
    outputs_dir: Path,
) -> Dict[str, Any]:
    outputs_dir.mkdir(parents=True, exist_ok=True)
    safe_metric = _sanitize_metric_token(metric_name.lower())
    filename = f"top{len(ranked_rows)}_{safe_metric}_summary.csv"
    target = outputs_dir / filename
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["rank", "link_id", metric_name])
        writer.writeheader()
        for item in ranked_rows:
            writer.writerow(
                {
                    "rank": item["rank"],
                    "link_id": item["link_id"],
                    metric_name: round(float(item["metric_value"]), 6),
                }
            )
    return {"path": str(target), "filename": filename}


def build_summary_delivery_plan(
    context: SummaryDeliveryContext,
    artifact_memory_state: Optional[ArtifactMemoryState] = None,
    *,
    default_topk: int = 5,
    enable_bar_chart: bool = True,
    allow_text_fallback: bool = True,
) -> SummaryDeliveryPlan:
    request_type, requested_topk, reason = _detect_requested_delivery_type(
        context,
        default_topk=default_topk,
        enable_bar_chart=enable_bar_chart,
    )
    requested_metric = _detect_requested_pollutant(
        context.user_message,
        context.available_metrics,
        context.raw_source_result,
    )
    request = SummaryDeliveryRequest(
        delivery_type=request_type,
        source_result_type=context.source_result_type,
        ranking_metric=requested_metric,
        topk=requested_topk,
        artifact_family="ranked_summary"
        if request_type in {SummaryDeliveryType.TOPK_SUMMARY_TABLE, SummaryDeliveryType.RANKED_BAR_CHART}
        else "textual_summary",
        related_task_type=context.current_task_type,
        delivery_reason=reason,
    )

    state = coerce_artifact_memory_state(artifact_memory_state)
    selected_type = request_type
    switched_from: Optional[str] = None
    artifact_repeat_detected = False
    suppression_reason: Optional[str] = None

    if selected_type == SummaryDeliveryType.TOPK_SUMMARY_TABLE:
        if state.find_latest_type(ArtifactType.TOPK_SUMMARY_TABLE, status=ArtifactDeliveryStatus.FULL):
            artifact_repeat_detected = True
            if enable_bar_chart and not state.find_latest_type(ArtifactType.RANKED_CHART, status=ArtifactDeliveryStatus.FULL):
                switched_from = selected_type.value
                selected_type = SummaryDeliveryType.RANKED_BAR_CHART
            else:
                suppression_reason = "A Top-K summary table was already fully delivered in artifact memory."

    elif selected_type == SummaryDeliveryType.RANKED_BAR_CHART:
        if state.find_latest_type(ArtifactType.RANKED_CHART, status=ArtifactDeliveryStatus.FULL):
            artifact_repeat_detected = True
            if not state.find_latest_type(ArtifactType.TOPK_SUMMARY_TABLE, status=ArtifactDeliveryStatus.FULL):
                switched_from = selected_type.value
                selected_type = SummaryDeliveryType.TOPK_SUMMARY_TABLE
            else:
                suppression_reason = "A ranked chart was already fully delivered in artifact memory."

    elif selected_type == SummaryDeliveryType.QUICK_STRUCTURED_SUMMARY:
        if state.find_latest_type(ArtifactType.QUICK_SUMMARY_TEXT, status=ArtifactDeliveryStatus.FULL):
            artifact_repeat_detected = True
            if context.source_result_type == "emission" and not state.find_latest_type(
                ArtifactType.RANKED_CHART,
                status=ArtifactDeliveryStatus.FULL,
            ):
                switched_from = selected_type.value
                selected_type = SummaryDeliveryType.RANKED_BAR_CHART
            elif context.source_result_type == "emission" and not state.find_latest_type(
                ArtifactType.TOPK_SUMMARY_TABLE,
                status=ArtifactDeliveryStatus.FULL,
            ):
                switched_from = selected_type.value
                selected_type = SummaryDeliveryType.TOPK_SUMMARY_TABLE
            else:
                suppression_reason = "A quick structured summary was already fully delivered in artifact memory."

    decision = SummaryDeliveryDecision(
        selected_delivery_type=selected_type,
        confidence=0.9 if selected_type == request_type else 0.82,
        reason=reason,
        ranking_metric=requested_metric,
        topk=requested_topk,
        should_generate_downloadable_table=selected_type == SummaryDeliveryType.TOPK_SUMMARY_TABLE,
        should_generate_chart=selected_type == SummaryDeliveryType.RANKED_BAR_CHART,
        should_generate_text_summary=True,
        switched_from_delivery_type=switched_from,
        suppressed_by_artifact_memory=bool(suppression_reason),
    )

    preconditions: List[str] = []
    plan_status = "planned"
    user_visible_summary: Optional[str] = None

    if not context.raw_source_result:
        return SummaryDeliveryPlan(
            request=request,
            decision=decision,
            source_result_type=context.source_result_type,
            source_tool_name=context.source_tool_name,
            source_label=context.source_label,
            artifact_family=request.artifact_family,
            preconditions=["source_result"],
            plan_status="not_actionable",
            artifact_repeat_detected=artifact_repeat_detected,
            suppression_reason="No eligible upstream result was available for bounded summary delivery.",
            user_visible_summary="当前还没有可用于生成图表/摘要的结果输入，因此暂时不能直接交付该输出。",
        )

    if suppression_reason:
        return SummaryDeliveryPlan(
            request=request,
            decision=decision,
            source_result_type=context.source_result_type,
            source_tool_name=context.source_tool_name,
            source_label=context.source_label,
            artifact_family=request.artifact_family,
            preconditions=[],
            plan_status="suppressed",
            artifact_repeat_detected=True,
            suppression_reason=suppression_reason,
            user_visible_summary="同类型交付物刚才已经给过，当前更适合切换为另一种输出形式。",
        )

    if selected_type in {SummaryDeliveryType.TOPK_SUMMARY_TABLE, SummaryDeliveryType.RANKED_BAR_CHART}:
        preconditions.append("emission_result")
        if context.source_result_type != "emission":
            if allow_text_fallback:
                decision.selected_delivery_type = SummaryDeliveryType.QUICK_STRUCTURED_SUMMARY
                decision.should_generate_downloadable_table = False
                decision.should_generate_chart = False
                decision.reason = "The current source result is not emission-style row data, so the bounded surface fell back to a structured summary."
                return SummaryDeliveryPlan(
                    request=request,
                    decision=decision,
                    source_result_type=context.source_result_type,
                    source_tool_name=context.source_tool_name,
                    source_label=context.source_label,
                    artifact_family="textual_summary",
                    preconditions=["source_result"],
                    plan_status="planned",
                    artifact_repeat_detected=artifact_repeat_detected,
                    user_visible_summary="当前结果更适合先交付结构化摘要，而不是路段排名图表。",
                )
            plan_status = "failed"
            return SummaryDeliveryPlan(
                request=request,
                decision=decision,
                source_result_type=context.source_result_type,
                source_tool_name=context.source_tool_name,
                source_label=context.source_label,
                artifact_family=request.artifact_family,
                preconditions=preconditions,
                plan_status=plan_status,
                artifact_repeat_detected=artifact_repeat_detected,
                suppression_reason="The bounded chart/summary surface only supports ranked chart/table generation from emission-style results.",
                user_visible_summary="当前结果类型还不能安全生成这类排名图表。",
            )

        if request.ranking_metric is None:
            if allow_text_fallback:
                decision.selected_delivery_type = SummaryDeliveryType.QUICK_STRUCTURED_SUMMARY
                decision.should_generate_downloadable_table = False
                decision.should_generate_chart = False
                decision.reason = "No stable ranking metric was available, so the bounded surface fell back to a structured summary."
                return SummaryDeliveryPlan(
                    request=request,
                    decision=decision,
                    source_result_type=context.source_result_type,
                    source_tool_name=context.source_tool_name,
                    source_label=context.source_label,
                    artifact_family="textual_summary",
                    preconditions=["source_result"],
                    plan_status="planned",
                    artifact_repeat_detected=artifact_repeat_detected,
                    user_visible_summary="当前缺少稳定的排序指标，因此先回退为结构化摘要。",
                )
            return SummaryDeliveryPlan(
                request=request,
                decision=decision,
                source_result_type=context.source_result_type,
                source_tool_name=context.source_tool_name,
                source_label=context.source_label,
                artifact_family=request.artifact_family,
                preconditions=["ranking_metric"],
                plan_status="failed",
                artifact_repeat_detected=artifact_repeat_detected,
                suppression_reason="No stable ranking metric was available in the current result payload.",
                user_visible_summary="当前结果里没有稳定可排序的指标，因此不能安全生成排名图表。",
            )

        ranked_rows = _rank_emission_rows(
            context.raw_source_result,
            request.ranking_metric,
            topk=request.topk,
        )
        if not ranked_rows:
            if allow_text_fallback:
                decision.selected_delivery_type = SummaryDeliveryType.QUICK_STRUCTURED_SUMMARY
                decision.should_generate_downloadable_table = False
                decision.should_generate_chart = False
                decision.reason = "No row-level metric values were available, so the bounded surface fell back to a structured summary."
                return SummaryDeliveryPlan(
                    request=request,
                    decision=decision,
                    source_result_type=context.source_result_type,
                    source_tool_name=context.source_tool_name,
                    source_label=context.source_label,
                    artifact_family="textual_summary",
                    preconditions=["source_result"],
                    plan_status="planned",
                    artifact_repeat_detected=artifact_repeat_detected,
                    user_visible_summary="当前结果没有可用于安全排序的逐行指标，因此先回退为结构化摘要。",
                )
            return SummaryDeliveryPlan(
                request=request,
                decision=decision,
                source_result_type=context.source_result_type,
                source_tool_name=context.source_tool_name,
                source_label=context.source_label,
                artifact_family=request.artifact_family,
                preconditions=["rankable_rows"],
                plan_status="failed",
                artifact_repeat_detected=artifact_repeat_detected,
                suppression_reason="The current result payload did not contain rankable row-level values for the requested metric.",
                user_visible_summary="当前结果里没有足够的逐行排序值，因此不能安全生成这类摘要图表。",
            )
        decision.topk = len(ranked_rows)

    if selected_type == SummaryDeliveryType.RANKED_BAR_CHART:
        user_visible_summary = "已将当前请求承接为非空间排名图表交付。"
    elif selected_type == SummaryDeliveryType.TOPK_SUMMARY_TABLE:
        user_visible_summary = "已将当前请求承接为 Top-K 摘要表交付。"
    else:
        user_visible_summary = "已将当前请求承接为结构化摘要交付。"

    return SummaryDeliveryPlan(
        request=request,
        decision=decision,
        source_result_type=context.source_result_type,
        source_tool_name=context.source_tool_name,
        source_label=context.source_label,
        artifact_family=(
            "ranked_summary"
            if decision.selected_delivery_type in {SummaryDeliveryType.TOPK_SUMMARY_TABLE, SummaryDeliveryType.RANKED_BAR_CHART}
            else "textual_summary"
        ),
        merge_with_existing_table_preview=(
            decision.selected_delivery_type == SummaryDeliveryType.RANKED_BAR_CHART
            and not state.find_latest_type(ArtifactType.TOPK_SUMMARY_TABLE, status=ArtifactDeliveryStatus.FULL)
        ),
        preconditions=preconditions,
        plan_status=plan_status,
        artifact_repeat_detected=artifact_repeat_detected,
        suppression_reason=suppression_reason,
        user_visible_summary=user_visible_summary,
    )


def execute_summary_delivery_plan(
    plan: SummaryDeliveryPlan,
    context: SummaryDeliveryContext,
    *,
    outputs_dir: Path,
    delivery_turn_index: int,
    source_tool_name: Optional[str] = None,
) -> SummaryDeliveryResult:
    if plan.plan_status != "planned":
        return SummaryDeliveryResult(
            success=False,
            failure_reason=plan.suppression_reason or "Summary delivery plan was not executable.",
            summary_text=plan.user_visible_summary,
            delivery_summary=plan.user_visible_summary,
        )

    selected_type = plan.decision.selected_delivery_type
    if selected_type is None:
        return SummaryDeliveryResult(
            success=False,
            failure_reason="No summary delivery type was selected.",
        )

    source_name = source_tool_name or context.source_tool_name or "summary_delivery_surface"
    artifact_records: List[ArtifactRecord] = []
    table_preview: Optional[Dict[str, Any]] = None
    chart_ref: Optional[Dict[str, Any]] = None
    download_file: Optional[Dict[str, Any]] = None

    ranked_rows: List[Dict[str, Any]] = []
    if selected_type in {SummaryDeliveryType.TOPK_SUMMARY_TABLE, SummaryDeliveryType.RANKED_BAR_CHART}:
        ranked_rows = _rank_emission_rows(
            context.raw_source_result,
            plan.decision.ranking_metric,
            topk=plan.decision.topk,
        )
        if not ranked_rows:
            return SummaryDeliveryResult(
                success=False,
                failure_reason="No rankable rows were available for the selected metric.",
                summary_text="当前结果里没有可用于安全排序的逐行指标，因此这次没有假装生成图表或摘要表。",
                delivery_summary="当前结果暂时不能安全生成排名图表/摘要表。",
            )

    if selected_type == SummaryDeliveryType.TOPK_SUMMARY_TABLE:
        download_file = _materialize_topk_csv(
            ranked_rows,
            metric_name=plan.decision.ranking_metric or "metric",
            outputs_dir=outputs_dir,
        )
        table_preview = _build_table_preview(
            ranked_rows,
            metric_name=plan.decision.ranking_metric or "metric",
            include_download=download_file,
        )
        artifact_records.append(
            build_artifact_record(
                artifact_type=ArtifactType.TOPK_SUMMARY_TABLE,
                delivery_turn_index=delivery_turn_index,
                source_tool_name=source_name,
                source_action_id="download_topk_summary",
                delivery_status=ArtifactDeliveryStatus.FULL,
                file_ref=_clean_text(download_file.get("path")),
                download_ref=download_file,
                summary=f"已提供 Top {len(ranked_rows)} 摘要表及下载文件。",
                related_task_type=context.current_task_type,
                related_pollutant=_metric_components(plan.decision.ranking_metric)[0],
                related_scope=f"top{len(ranked_rows)}",
            )
        )

    elif selected_type == SummaryDeliveryType.RANKED_BAR_CHART:
        chart_ref = _build_ranked_bar_chart(
            ranked_rows,
            metric_name=plan.decision.ranking_metric or "metric",
        )
        artifact_records.append(
            build_artifact_record(
                artifact_type=ArtifactType.RANKED_CHART,
                delivery_turn_index=delivery_turn_index,
                source_tool_name=source_name,
                source_action_id="render_rank_chart",
                delivery_status=ArtifactDeliveryStatus.FULL,
                summary=f"已提供按 {chart_ref['metric_label']} 排序的排名图。",
                related_task_type=context.current_task_type,
                related_pollutant=_metric_components(plan.decision.ranking_metric)[0],
                related_scope=f"top{len(ranked_rows)}",
            )
        )
        if plan.merge_with_existing_table_preview:
            table_preview = _build_table_preview(
                ranked_rows,
                metric_name=plan.decision.ranking_metric or "metric",
            )
            artifact_records.append(
                build_artifact_record(
                    artifact_type=ArtifactType.TOPK_SUMMARY_TABLE,
                    delivery_turn_index=delivery_turn_index,
                    source_tool_name=source_name,
                    source_action_id="download_topk_summary",
                    delivery_status=ArtifactDeliveryStatus.PARTIAL,
                    summary=f"已附带 Top {len(ranked_rows)} 摘要表预览。",
                    related_task_type=context.current_task_type,
                    related_pollutant=_metric_components(plan.decision.ranking_metric)[0],
                    related_scope=f"top{len(ranked_rows)}",
                )
            )

    summary_text = _build_quick_structured_summary(
        context.raw_source_result,
        metric_name=plan.decision.ranking_metric,
        topk_rows=ranked_rows,
    )
    if selected_type == SummaryDeliveryType.QUICK_STRUCTURED_SUMMARY:
        artifact_records.append(
            build_artifact_record(
                artifact_type=ArtifactType.QUICK_SUMMARY_TEXT,
                delivery_turn_index=delivery_turn_index,
                source_tool_name=source_name,
                source_action_id="deliver_quick_structured_summary",
                delivery_status=ArtifactDeliveryStatus.FULL,
                summary=summary_text[:160],
                related_task_type=context.current_task_type,
                related_pollutant=_metric_components(plan.decision.ranking_metric)[0],
            )
        )

    delivery_lines: List[str] = []
    if not context.has_geometry_support and selected_type in {
        SummaryDeliveryType.RANKED_BAR_CHART,
        SummaryDeliveryType.TOPK_SUMMARY_TABLE,
    }:
        delivery_lines.append("当前缺少空间几何，因此先用非空间排名图/摘要表展示结果。")

    if selected_type == SummaryDeliveryType.TOPK_SUMMARY_TABLE:
        delivery_lines.append(
            f"已按 {_format_metric_label(plan.decision.ranking_metric)} 生成前 {len(ranked_rows)} 个对象的摘要表，并提供下载文件。"
        )
    elif selected_type == SummaryDeliveryType.RANKED_BAR_CHART:
        delivery_lines.append(
            f"已按 {_format_metric_label(plan.decision.ranking_metric)} 生成前 {len(ranked_rows)} 个对象的排名图。"
        )
        if table_preview is not None:
            delivery_lines.append("同时附上摘要表预览，方便直接查看前几名。")
    else:
        delivery_lines.append("已基于当前结果给出结构化摘要。")

    if plan.decision.switched_from_delivery_type:
        delivery_lines.append("由于同类型交付物刚刚已经提供过，这次自动切换到了另一种 bounded 输出形式。")

    summary_text_block = summary_text
    if summary_text_block:
        delivery_text = "\n".join(delivery_lines + ["", summary_text_block])
    else:
        delivery_text = "\n".join(delivery_lines)

    return SummaryDeliveryResult(
        success=True,
        artifact_records=artifact_records,
        table_preview=table_preview,
        chart_ref=chart_ref,
        summary_text=delivery_text,
        delivery_summary=delivery_lines[0] if delivery_lines else "已完成 bounded summary delivery。",
        download_file=download_file,
    )
