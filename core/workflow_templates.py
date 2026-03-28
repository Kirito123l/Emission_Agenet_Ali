from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _coerce_string_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    result: List[str] = []
    for value in values:
        text = str(value).strip() if value is not None else ""
        if text:
            result.append(text)
    return result


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _message_contains_any(message: str, phrases: tuple[str, ...]) -> bool:
    lowered = message.lower()
    return any(phrase in lowered for phrase in phrases)


@dataclass
class WorkflowTemplateStep:
    step_id: str
    tool_name: str
    purpose: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    produces: List[str] = field(default_factory=list)
    argument_hints: Dict[str, Any] = field(default_factory=dict)
    optional: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "purpose": self.purpose,
            "depends_on": list(self.depends_on),
            "produces": list(self.produces),
            "argument_hints": dict(self.argument_hints),
            "optional": self.optional,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "WorkflowTemplateStep":
        payload = data if isinstance(data, dict) else {}
        return cls(
            step_id=str(payload.get("step_id") or "").strip() or "t1",
            tool_name=str(payload.get("tool_name") or "").strip(),
            purpose=str(payload.get("purpose")).strip() if payload.get("purpose") is not None else None,
            depends_on=_coerce_string_list(payload.get("depends_on")),
            produces=_coerce_string_list(payload.get("produces")),
            argument_hints=dict(payload.get("argument_hints") or {}),
            optional=bool(payload.get("optional", False)),
        )


@dataclass
class WorkflowTemplate:
    template_id: str
    name: str
    description: str
    supported_task_types: List[str] = field(default_factory=list)
    required_result_types: List[str] = field(default_factory=list)
    required_file_signals: List[str] = field(default_factory=list)
    step_skeleton: List[WorkflowTemplateStep] = field(default_factory=list)
    applicability_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "supported_task_types": list(self.supported_task_types),
            "required_result_types": list(self.required_result_types),
            "required_file_signals": list(self.required_file_signals),
            "step_skeleton": [step.to_dict() for step in self.step_skeleton],
            "applicability_notes": list(self.applicability_notes),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "WorkflowTemplate":
        payload = data if isinstance(data, dict) else {}
        return cls(
            template_id=str(payload.get("template_id") or "").strip(),
            name=str(payload.get("name") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            supported_task_types=_coerce_string_list(payload.get("supported_task_types")),
            required_result_types=_coerce_string_list(payload.get("required_result_types")),
            required_file_signals=_coerce_string_list(payload.get("required_file_signals")),
            step_skeleton=[
                WorkflowTemplateStep.from_dict(item)
                for item in payload.get("step_skeleton", [])
                if isinstance(item, dict)
            ],
            applicability_notes=_coerce_string_list(payload.get("applicability_notes")),
        )


@dataclass
class TemplateRecommendation:
    template_id: str
    confidence: float
    reason: str
    matched_signals: List[str] = field(default_factory=list)
    unmet_requirements: List[str] = field(default_factory=list)
    is_applicable: bool = False
    priority_rank: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_id": self.template_id,
            "confidence": round(float(self.confidence), 3),
            "reason": self.reason,
            "matched_signals": list(self.matched_signals),
            "unmet_requirements": list(self.unmet_requirements),
            "is_applicable": self.is_applicable,
            "priority_rank": self.priority_rank,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "TemplateRecommendation":
        payload = data if isinstance(data, dict) else {}
        return cls(
            template_id=str(payload.get("template_id") or "").strip(),
            confidence=_coerce_float(payload.get("confidence"), 0.0),
            reason=str(payload.get("reason") or "").strip(),
            matched_signals=_coerce_string_list(payload.get("matched_signals")),
            unmet_requirements=_coerce_string_list(payload.get("unmet_requirements")),
            is_applicable=bool(payload.get("is_applicable", False)),
            priority_rank=int(payload.get("priority_rank", 0) or 0),
        )


@dataclass
class TemplateSelectionResult:
    recommended_template_id: Optional[str] = None
    recommendations: List[TemplateRecommendation] = field(default_factory=list)
    selection_reason: Optional[str] = None
    template_prior_used: bool = False
    selected_template: Optional[WorkflowTemplate] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommended_template_id": self.recommended_template_id,
            "recommendations": [item.to_dict() for item in self.recommendations],
            "selection_reason": self.selection_reason,
            "template_prior_used": self.template_prior_used,
            "selected_template": self.selected_template.to_dict() if self.selected_template else None,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "TemplateSelectionResult":
        payload = data if isinstance(data, dict) else {}
        selected_payload = payload.get("selected_template")
        return cls(
            recommended_template_id=(
                str(payload.get("recommended_template_id")).strip()
                if payload.get("recommended_template_id") is not None
                else None
            ),
            recommendations=[
                TemplateRecommendation.from_dict(item)
                for item in payload.get("recommendations", [])
                if isinstance(item, dict)
            ],
            selection_reason=(
                str(payload.get("selection_reason")).strip()
                if payload.get("selection_reason") is not None
                else None
            ),
            template_prior_used=bool(payload.get("template_prior_used", False)),
            selected_template=(
                WorkflowTemplate.from_dict(selected_payload)
                if isinstance(selected_payload, dict)
                else None
            ),
        )


def _build_template_catalog() -> Dict[str, WorkflowTemplate]:
    templates = [
        WorkflowTemplate(
            template_id="macro_emission_baseline",
            name="Macro Emission Baseline",
            description="Baseline macro-scale emission analysis from grounded road-link data.",
            supported_task_types=["macro_emission"],
            required_file_signals=["macro_task"],
            step_skeleton=[
                WorkflowTemplateStep(
                    step_id="t1",
                    tool_name="calculate_macro_emission",
                    purpose="Compute link-level macro emissions from the grounded road-link dataset.",
                    produces=["emission"],
                ),
                WorkflowTemplateStep(
                    step_id="t2",
                    tool_name="render_spatial_map",
                    purpose="Optionally render the computed emission layer on a map.",
                    depends_on=["emission"],
                    argument_hints={"layer_type": "emission"},
                    optional=True,
                ),
            ],
            applicability_notes=[
                "Use when the file grounding is macro-oriented and required traffic fields are mostly available.",
                "This template stays close to the minimal compute-first workflow.",
            ],
        ),
        WorkflowTemplate(
            template_id="macro_spatial_chain",
            name="Macro Spatial Chain",
            description="Macro emission followed by dispersion, hotspot analysis, and spatial rendering.",
            supported_task_types=["macro_emission"],
            required_file_signals=["macro_task", "spatial_ready"],
            required_result_types=["emission", "dispersion", "hotspot"],
            step_skeleton=[
                WorkflowTemplateStep(
                    step_id="t1",
                    tool_name="calculate_macro_emission",
                    purpose="Compute link-level macro emissions.",
                    produces=["emission"],
                ),
                WorkflowTemplateStep(
                    step_id="t2",
                    tool_name="calculate_dispersion",
                    purpose="Propagate emissions into a dispersion result.",
                    depends_on=["emission"],
                    produces=["dispersion"],
                ),
                WorkflowTemplateStep(
                    step_id="t3",
                    tool_name="analyze_hotspots",
                    purpose="Identify concentration hotspots from the dispersion output.",
                    depends_on=["dispersion"],
                    produces=["hotspot"],
                ),
                WorkflowTemplateStep(
                    step_id="t4",
                    tool_name="render_spatial_map",
                    purpose="Render the hotspot layer on a spatial map.",
                    depends_on=["hotspot"],
                    argument_hints={"layer_type": "hotspot"},
                ),
            ],
            applicability_notes=[
                "Use when file grounding indicates a spatially actionable macro dataset.",
                "This template is only a prior; the planner may shorten it if the user asked for a narrower workflow.",
            ],
        ),
        WorkflowTemplate(
            template_id="micro_emission_baseline",
            name="Micro Emission Baseline",
            description="Micro-scale second-by-second emission analysis from grounded trajectory data.",
            supported_task_types=["micro_emission"],
            required_file_signals=["micro_task"],
            step_skeleton=[
                WorkflowTemplateStep(
                    step_id="t1",
                    tool_name="calculate_micro_emission",
                    purpose="Compute second-by-second micro emissions from the grounded trajectory dataset.",
                    produces=["emission"],
                )
            ],
            applicability_notes=[
                "Use when the file grounding clearly points to micro-scale trajectory analysis.",
                "This template stays compute-only unless the user explicitly asks for map rendering.",
            ],
        ),
        WorkflowTemplate(
            template_id="macro_render_focus",
            name="Macro Render Focus",
            description="Macro emission computation followed by immediate emission-layer rendering.",
            supported_task_types=["macro_emission"],
            required_file_signals=["macro_task", "spatial_ready", "render_intent"],
            step_skeleton=[
                WorkflowTemplateStep(
                    step_id="t1",
                    tool_name="calculate_macro_emission",
                    purpose="Compute macro emissions for the grounded road-link file.",
                    produces=["emission"],
                ),
                WorkflowTemplateStep(
                    step_id="t2",
                    tool_name="render_spatial_map",
                    purpose="Render the emission result on a spatial map.",
                    depends_on=["emission"],
                    argument_hints={"layer_type": "emission"},
                ),
            ],
            applicability_notes=[
                "Use when the user emphasizes map rendering rather than dispersion or hotspot derivation.",
            ],
        ),
        WorkflowTemplate(
            template_id="micro_render_focus",
            name="Micro Render Focus",
            description="Micro emission computation followed by bounded emission-layer rendering.",
            supported_task_types=["micro_emission"],
            required_file_signals=["micro_task", "spatial_ready", "render_intent"],
            step_skeleton=[
                WorkflowTemplateStep(
                    step_id="t1",
                    tool_name="calculate_micro_emission",
                    purpose="Compute micro emissions from trajectory data.",
                    produces=["emission"],
                ),
                WorkflowTemplateStep(
                    step_id="t2",
                    tool_name="render_spatial_map",
                    purpose="Render the micro emission result as an emission layer when spatial context is available.",
                    depends_on=["emission"],
                    argument_hints={"layer_type": "emission"},
                ),
            ],
            applicability_notes=[
                "Use only when the grounded micro dataset exposes actionable spatial context and the user explicitly asks for a map.",
            ],
        ),
    ]
    return {template.template_id: template for template in templates}


_TEMPLATE_CATALOG = _build_template_catalog()


def list_workflow_templates() -> List[WorkflowTemplate]:
    return [WorkflowTemplate.from_dict(item.to_dict()) for item in _TEMPLATE_CATALOG.values()]


def get_workflow_template(template_id: str) -> Optional[WorkflowTemplate]:
    template = _TEMPLATE_CATALOG.get(str(template_id or "").strip())
    return WorkflowTemplate.from_dict(template.to_dict()) if template else None


def _normalize_readiness_status(file_analysis: Dict[str, Any], task_type: str) -> str:
    diagnostics = file_analysis.get("missing_field_diagnostics") or {}
    status = str(diagnostics.get("status") or "").strip().lower()
    if status:
        return status
    if task_type == "macro_emission":
        return "complete" if file_analysis.get("macro_has_required") else "insufficient"
    if task_type == "micro_emission":
        return "complete" if file_analysis.get("micro_has_required") else "insufficient"
    return "unknown_task"


def _extract_grounding_signals(file_analysis: Dict[str, Any], user_message: str) -> Dict[str, Any]:
    task_type = str(file_analysis.get("task_type") or "unknown").strip()
    confidence = _coerce_float(file_analysis.get("confidence"), 0.0)
    readiness_status = _normalize_readiness_status(file_analysis, task_type)
    spatial_metadata = file_analysis.get("spatial_metadata") or {}
    dataset_roles = [
        dict(item)
        for item in (file_analysis.get("dataset_roles") or [])
        if isinstance(item, dict)
    ]
    selected_role = next((item for item in dataset_roles if item.get("selected")), None)
    geometry_types = [str(item) for item in (spatial_metadata.get("geometry_types") or []) if item]
    selected_format = str((selected_role or {}).get("format") or file_analysis.get("format") or "").lower()

    render_intent = _message_contains_any(
        user_message,
        ("地图", "渲染", "可视化", "render", "map", "visual", "visualize"),
    )
    dispersion_intent = _message_contains_any(
        user_message,
        ("扩散", "dispersion", "浓度", "concentration", "raster"),
    )
    hotspot_intent = _message_contains_any(
        user_message,
        ("热点", "hotspot"),
    )

    spatial_ready = bool(spatial_metadata) or selected_format in {"shapefile", "zip_shapefile"}
    if not spatial_ready:
        spatial_ready = any(role.get("role") == "spatial_context" for role in dataset_roles)

    has_line_geometry = any("line" in item.lower() for item in geometry_types)
    role_summary = file_analysis.get("dataset_role_summary") or {}

    return {
        "task_type": task_type,
        "grounding_confidence": confidence,
        "readiness_status": readiness_status,
        "spatial_ready": spatial_ready,
        "has_line_geometry": has_line_geometry,
        "render_intent": render_intent,
        "dispersion_intent": dispersion_intent,
        "hotspot_intent": hotspot_intent,
        "dataset_roles_present": bool(dataset_roles),
        "ambiguous_dataset_roles": bool(role_summary.get("ambiguous")),
        "selected_primary_table": str(file_analysis.get("selected_primary_table") or "").strip() or None,
    }


def _evaluate_template(
    template: WorkflowTemplate,
    signals: Dict[str, Any],
) -> Optional[TemplateRecommendation]:
    task_type = signals["task_type"]
    if task_type not in template.supported_task_types:
        return None

    matched: List[str] = []
    unmet: List[str] = []
    score = 0.0
    applicable = True

    if task_type == "macro_emission":
        matched.append("macro_task")
        score += 0.42
    elif task_type == "micro_emission":
        matched.append("micro_task")
        score += 0.42

    if signals["grounding_confidence"] >= 0.75:
        matched.append("grounding_confident")
        score += 0.1
    elif signals["grounding_confidence"] < 0.5:
        unmet.append("grounding_confidence_low")
        score -= 0.08

    readiness_status = signals["readiness_status"]
    if readiness_status == "complete":
        matched.append("file_readiness_complete")
        score += 0.2
    elif readiness_status == "partial":
        matched.append("file_readiness_partial")
        unmet.append("missing_required_fields_partial")
        score += 0.08
    elif readiness_status == "insufficient":
        unmet.append("file_readiness_insufficient")
        score -= 0.22
        applicable = False
    else:
        unmet.append("file_readiness_unknown")
        score -= 0.12
        applicable = False

    if "spatial_ready" in template.required_file_signals:
        if signals["spatial_ready"]:
            matched.append("spatial_ready")
            score += 0.16
            if signals["has_line_geometry"]:
                matched.append("line_geometry")
                score += 0.05
        else:
            unmet.append("spatial_ready_missing")
            score -= 0.18
            applicable = False

    if "render_intent" in template.required_file_signals and not signals["render_intent"]:
        return None
    if "render_intent" in template.required_file_signals and signals["render_intent"]:
        matched.append("render_intent")
        score += 0.12

    if template.template_id == "macro_spatial_chain":
        if signals["dispersion_intent"]:
            matched.append("dispersion_intent")
            score += 0.17
        if signals["hotspot_intent"]:
            matched.append("hotspot_intent")
            score += 0.17
        if not signals["dispersion_intent"] and not signals["hotspot_intent"]:
            score -= 0.22
    if template.template_id.endswith("render_focus") and signals["hotspot_intent"]:
        score -= 0.12
        unmet.append("hotspot_intent_prefers_spatial_chain")

    if template.template_id == "macro_emission_baseline" and signals["render_intent"]:
        score -= 0.02
    if template.template_id == "micro_emission_baseline" and signals["render_intent"] and signals["spatial_ready"]:
        score -= 0.01

    confidence = max(0.05, min(0.95, round(score, 3)))
    reason_parts = [
        f"task_type={task_type}",
        f"readiness={readiness_status}",
    ]
    if signals["spatial_ready"]:
        reason_parts.append("spatial context available")
    if signals["render_intent"]:
        reason_parts.append("render intent detected")
    if signals["dispersion_intent"] or signals["hotspot_intent"]:
        reason_parts.append("downstream spatial-analysis intent detected")
    if unmet:
        reason_parts.append(f"unmet={', '.join(unmet)}")

    return TemplateRecommendation(
        template_id=template.template_id,
        confidence=confidence,
        reason="; ".join(reason_parts),
        matched_signals=matched,
        unmet_requirements=unmet,
        is_applicable=applicable,
    )


def recommend_workflow_templates(
    file_analysis: Optional[Dict[str, Any]],
    *,
    user_message: Optional[str] = None,
    max_recommendations: int = 3,
    min_confidence: float = 0.3,
) -> List[TemplateRecommendation]:
    if not isinstance(file_analysis, dict):
        return []

    signals = _extract_grounding_signals(file_analysis, user_message or "")
    if signals["task_type"] not in {"macro_emission", "micro_emission"}:
        return []
    if signals["grounding_confidence"] < max(0.0, min_confidence - 0.1):
        return []

    recommendations: List[TemplateRecommendation] = []
    for template in _TEMPLATE_CATALOG.values():
        recommendation = _evaluate_template(template, signals)
        if recommendation is None:
            continue
        if recommendation.confidence < max(0.05, min_confidence - 0.2):
            continue
        recommendations.append(recommendation)

    recommendations.sort(
        key=lambda item: (
            not item.is_applicable,
            -item.confidence,
            item.template_id,
        )
    )
    trimmed = recommendations[: max(1, int(max_recommendations or 1))]
    for index, recommendation in enumerate(trimmed, start=1):
        recommendation.priority_rank = index
    return trimmed


def select_primary_template(
    recommendations: List[TemplateRecommendation],
    *,
    min_confidence: float = 0.55,
) -> TemplateSelectionResult:
    if not recommendations:
        return TemplateSelectionResult(
            recommended_template_id=None,
            recommendations=[],
            selection_reason="No workflow template recommendation was applicable.",
            template_prior_used=False,
            selected_template=None,
        )

    selected_recommendation = next(
        (
            item
            for item in recommendations
            if item.is_applicable and item.confidence >= min_confidence
        ),
        None,
    )
    if selected_recommendation is None:
        top = recommendations[0]
        return TemplateSelectionResult(
            recommended_template_id=None,
            recommendations=recommendations,
            selection_reason=(
                f"No workflow template prior was selected because the best recommendation "
                f"({top.template_id}) stayed below the planner-use threshold or was not applicable."
            ),
            template_prior_used=False,
            selected_template=None,
        )

    selected_template = get_workflow_template(selected_recommendation.template_id)
    return TemplateSelectionResult(
        recommended_template_id=selected_recommendation.template_id,
        recommendations=recommendations,
        selection_reason=(
            f"Selected {selected_recommendation.template_id} as the highest-ranked applicable template prior."
        ),
        template_prior_used=selected_template is not None,
        selected_template=selected_template,
    )


def summarize_template_prior(
    template: WorkflowTemplate,
    recommendation: TemplateRecommendation,
) -> str:
    lines = [
        "[Workflow template prior]",
        f"Template: {template.template_id} ({template.name})",
        f"Confidence: {recommendation.confidence:.2f}",
        f"Reason: {recommendation.reason}",
    ]
    if recommendation.matched_signals:
        lines.append(f"Matched signals: {', '.join(recommendation.matched_signals)}")
    if recommendation.unmet_requirements:
        lines.append(f"Unmet requirements: {', '.join(recommendation.unmet_requirements)}")
    lines.append("Step skeleton:")
    for step in template.step_skeleton:
        step_line = f"- {step.step_id}: {step.tool_name}"
        if step.depends_on:
            step_line += f" | depends_on={', '.join(step.depends_on)}"
        if step.produces:
            step_line += f" | produces={', '.join(step.produces)}"
        if step.argument_hints:
            step_line += f" | argument_hints={step.argument_hints}"
        if step.optional:
            step_line += " | optional=true"
        lines.append(step_line)
    lines.append(
        "Use this template as a bounded prior only. The planner should stay close to it when grounded signals agree, "
        "but may shorten or adapt the workflow when the current request is narrower."
    )
    return "\n".join(lines)
