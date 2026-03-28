from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence


INTENT_RESOLUTION_PROMPT = """You are a bounded deliverable/progress intent resolver for an emission-analysis agent.

Return one JSON object only.

Classify:
1. The user's current desired deliverable form.
2. The user's progress intent relative to the current workflow.

Valid deliverable_intent values:
- spatial_map
- chart_or_ranked_summary
- downloadable_table
- quick_summary
- rough_estimate
- scenario_comparison
- unknown

Valid progress_intent values:
- continue_current_task
- resume_recovered_target
- shift_output_mode
- start_new_task
- ask_clarify

Rules:
- Deliverable intent is NOT a tool name.
- Progress intent is NOT permission to ignore readiness or legality checks.
- Prefer the current task when the user sounds like they are continuing or changing the output form of an existing result.
- Prefer ask_clarify when the message is too short or ambiguous for safe workflow biasing.
- Do not output backend state mutations or tool names as the final decision.

Required JSON keys:
- deliverable_intent
- progress_intent
- confidence
- reason
- current_task_relevance
- should_bias_existing_action
- should_preserve_residual_workflow
- should_trigger_clarification
- user_utterance_summary
"""


_MAP_ACTION_IDS = {
    "render_emission_map",
    "render_dispersion_map",
    "render_hotspot_map",
}


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


def _clean_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _clean_dict_list(values: Any) -> List[Dict[str, Any]]:
    if not isinstance(values, list):
        return []
    return [dict(item) for item in values if isinstance(item, dict)]


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


class DeliverableIntentType(str, Enum):
    SPATIAL_MAP = "spatial_map"
    CHART_OR_RANKED_SUMMARY = "chart_or_ranked_summary"
    DOWNLOADABLE_TABLE = "downloadable_table"
    QUICK_SUMMARY = "quick_summary"
    ROUGH_ESTIMATE = "rough_estimate"
    SCENARIO_COMPARISON = "scenario_comparison"
    UNKNOWN = "unknown"


class ProgressIntentType(str, Enum):
    CONTINUE_CURRENT_TASK = "continue_current_task"
    RESUME_RECOVERED_TARGET = "resume_recovered_target"
    SHIFT_OUTPUT_MODE = "shift_output_mode"
    START_NEW_TASK = "start_new_task"
    ASK_CLARIFY = "ask_clarify"


@dataclass
class IntentResolutionDecision:
    deliverable_intent: DeliverableIntentType = DeliverableIntentType.UNKNOWN
    progress_intent: ProgressIntentType = ProgressIntentType.ASK_CLARIFY
    confidence: float = 0.0
    reason: Optional[str] = None
    current_task_relevance: float = 0.0
    should_bias_existing_action: bool = False
    should_preserve_residual_workflow: bool = False
    should_trigger_clarification: bool = False
    user_utterance_summary: Optional[str] = None
    resolution_source: str = "llm"

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "IntentResolutionDecision":
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
            deliverable_intent=deliverable,
            progress_intent=progress,
            confidence=_clamp_confidence(data.get("confidence")),
            reason=_clean_text(data.get("reason")),
            current_task_relevance=_clamp_confidence(data.get("current_task_relevance")),
            should_bias_existing_action=bool(data.get("should_bias_existing_action", False)),
            should_preserve_residual_workflow=bool(
                data.get("should_preserve_residual_workflow", False)
            ),
            should_trigger_clarification=bool(
                data.get("should_trigger_clarification", False)
            ),
            user_utterance_summary=_clean_text(data.get("user_utterance_summary")),
            resolution_source=_clean_text(data.get("resolution_source")) or "llm",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "deliverable_intent": self.deliverable_intent.value,
            "progress_intent": self.progress_intent.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "current_task_relevance": self.current_task_relevance,
            "should_bias_existing_action": self.should_bias_existing_action,
            "should_preserve_residual_workflow": self.should_preserve_residual_workflow,
            "should_trigger_clarification": self.should_trigger_clarification,
            "user_utterance_summary": self.user_utterance_summary,
            "resolution_source": self.resolution_source,
        }


@dataclass
class IntentResolutionContext:
    user_message: Optional[str] = None
    current_task_type: Optional[str] = None
    residual_workflow_summary: Optional[str] = None
    recovered_target_summary: Dict[str, Any] = field(default_factory=dict)
    readiness_summary: Dict[str, Any] = field(default_factory=dict)
    delivered_artifacts: List[Dict[str, Any]] = field(default_factory=list)
    recent_result_types: List[str] = field(default_factory=list)
    recent_tool_results_summary: List[Dict[str, Any]] = field(default_factory=list)
    latest_file_or_recovery_summary: Dict[str, Any] = field(default_factory=dict)
    relevant_action_candidates: List[Dict[str, Any]] = field(default_factory=list)
    has_geometry_support: bool = False
    has_residual_workflow: bool = False
    has_recovered_target: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_message": self.user_message,
            "current_task_type": self.current_task_type,
            "residual_workflow_summary": self.residual_workflow_summary,
            "recovered_target_summary": dict(self.recovered_target_summary),
            "readiness_summary": dict(self.readiness_summary),
            "delivered_artifacts": [dict(item) for item in self.delivered_artifacts],
            "recent_result_types": list(self.recent_result_types),
            "recent_tool_results_summary": [dict(item) for item in self.recent_tool_results_summary],
            "latest_file_or_recovery_summary": dict(self.latest_file_or_recovery_summary),
            "relevant_action_candidates": [dict(item) for item in self.relevant_action_candidates],
            "has_geometry_support": self.has_geometry_support,
            "has_residual_workflow": self.has_residual_workflow,
            "has_recovered_target": self.has_recovered_target,
        }

    def to_llm_payload(self) -> Dict[str, Any]:
        return self.to_dict()


@dataclass
class IntentResolutionParseResult:
    is_resolved: bool = False
    decision: Optional[IntentResolutionDecision] = None
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
class IntentResolutionApplicationPlan:
    deliverable_intent: DeliverableIntentType = DeliverableIntentType.UNKNOWN
    progress_intent: ProgressIntentType = ProgressIntentType.ASK_CLARIFY
    preserve_current_task: bool = True
    preserve_residual_workflow: bool = False
    bias_existing_action: bool = False
    bias_followup_suggestions: bool = False
    bias_continuation: bool = False
    reset_current_task_context: bool = False
    supersede_recovered_target: bool = False
    require_clarification: bool = False
    preferred_action_ids: List[str] = field(default_factory=list)
    deprioritized_action_ids: List[str] = field(default_factory=list)
    preferred_artifact_kinds: List[str] = field(default_factory=list)
    guidance_summary: Optional[str] = None
    clarification_question: Optional[str] = None
    user_visible_summary: Optional[str] = None
    state_resets: List[str] = field(default_factory=list)
    state_preserved: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "IntentResolutionApplicationPlan":
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
            deliverable_intent=deliverable,
            progress_intent=progress,
            preserve_current_task=bool(data.get("preserve_current_task", True)),
            preserve_residual_workflow=bool(data.get("preserve_residual_workflow", False)),
            bias_existing_action=bool(data.get("bias_existing_action", False)),
            bias_followup_suggestions=bool(data.get("bias_followup_suggestions", False)),
            bias_continuation=bool(data.get("bias_continuation", False)),
            reset_current_task_context=bool(data.get("reset_current_task_context", False)),
            supersede_recovered_target=bool(data.get("supersede_recovered_target", False)),
            require_clarification=bool(data.get("require_clarification", False)),
            preferred_action_ids=_clean_list(data.get("preferred_action_ids")),
            deprioritized_action_ids=_clean_list(data.get("deprioritized_action_ids")),
            preferred_artifact_kinds=_clean_list(data.get("preferred_artifact_kinds")),
            guidance_summary=_clean_text(data.get("guidance_summary")),
            clarification_question=_clean_text(data.get("clarification_question")),
            user_visible_summary=_clean_text(data.get("user_visible_summary")),
            state_resets=_clean_list(data.get("state_resets")),
            state_preserved=_clean_list(data.get("state_preserved")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "deliverable_intent": self.deliverable_intent.value,
            "progress_intent": self.progress_intent.value,
            "preserve_current_task": self.preserve_current_task,
            "preserve_residual_workflow": self.preserve_residual_workflow,
            "bias_existing_action": self.bias_existing_action,
            "bias_followup_suggestions": self.bias_followup_suggestions,
            "bias_continuation": self.bias_continuation,
            "reset_current_task_context": self.reset_current_task_context,
            "supersede_recovered_target": self.supersede_recovered_target,
            "require_clarification": self.require_clarification,
            "preferred_action_ids": list(self.preferred_action_ids),
            "deprioritized_action_ids": list(self.deprioritized_action_ids),
            "preferred_artifact_kinds": list(self.preferred_artifact_kinds),
            "guidance_summary": self.guidance_summary,
            "clarification_question": self.clarification_question,
            "user_visible_summary": self.user_visible_summary,
            "state_resets": list(self.state_resets),
            "state_preserved": list(self.state_preserved),
        }


def parse_intent_resolution_result(
    raw_payload: Optional[Dict[str, Any]],
    context: IntentResolutionContext,
) -> IntentResolutionParseResult:
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    deliverable_value = _clean_text(payload.get("deliverable_intent"))
    progress_value = _clean_text(payload.get("progress_intent"))
    if deliverable_value is None or progress_value is None:
        return IntentResolutionParseResult(
            is_resolved=False,
            raw_payload=payload,
            error="deliverable_intent or progress_intent was missing from the bounded intent result.",
        )

    decision = IntentResolutionDecision.from_dict(payload)
    if decision.user_utterance_summary is None and context.user_message:
        decision.user_utterance_summary = str(context.user_message).strip()[:180] or None
    if decision.reason is None:
        decision.reason = "The intent classifier did not include an explicit explanation."
    return IntentResolutionParseResult(
        is_resolved=True,
        decision=decision,
        raw_payload=payload,
    )


def infer_intent_resolution_fallback(
    context: IntentResolutionContext,
) -> IntentResolutionDecision:
    message = str(context.user_message or "").strip().lower()
    has_results = bool(context.recent_result_types)
    has_recovered_target = context.has_recovered_target or bool(context.recovered_target_summary)
    has_residual = context.has_residual_workflow or bool(context.residual_workflow_summary)
    task_relevance = 0.9 if (context.current_task_type or has_results or has_residual) else 0.35

    explicit_new_task_cues = (
        "换个任务",
        "另外一个任务",
        "新任务",
        "重新分析这个新问题",
        "不要管前面的",
        "重新来",
        "重新算一个新的",
        "start over",
        "new task",
        "another task",
        "ignore previous",
    )
    continuation_cues = (
        "继续",
        "接着",
        "下一步",
        "按这个",
        "先这样算",
        "就按这个",
        "continue",
        "keep going",
        "next step",
    )
    shift_output_cues = (
        "可视化",
        "画出来",
        "展示",
        "导出",
        "下载",
        "汇总",
        "总结",
        "排名",
        "排行",
        "top",
        "chart",
        "map",
        "地图",
        "导出一下",
        "换个方式展示",
        "换个方式",
        "visualize",
        "export",
        "download",
        "summary",
    )
    chart_cues = (
        "排名",
        "排行",
        "top",
        "图表",
        "chart",
        "条形图",
        "高排放路段",
        "rank",
    )
    download_cues = ("导出", "下载", "export", "download")
    summary_cues = ("分析一下", "帮我看下", "总结", "汇总", "summary", "quick summary")
    estimate_cues = ("估一下", "大概", "rough", "roughly", "粗算", "先估")
    scenario_cues = ("对比", "比较", "scenario", "换个情景", "不同方案", "compare")
    explicit_map_cues = ("地图", "map", "空间图", "spatial map")
    visualize_cues = ("可视化", "画出来", "visualize", "plot")
    ambiguous_cues = ("这个呢", "那就这样吧", "这样吧", "what about this")

    if any(cue in message for cue in explicit_new_task_cues):
        return IntentResolutionDecision(
            deliverable_intent=DeliverableIntentType.UNKNOWN,
            progress_intent=ProgressIntentType.START_NEW_TASK,
            confidence=0.9,
            reason="The user explicitly moved away from the prior workflow and started a new task direction.",
            current_task_relevance=0.15,
            should_bias_existing_action=False,
            should_preserve_residual_workflow=False,
            should_trigger_clarification=False,
            user_utterance_summary=_clean_text(context.user_message),
            resolution_source="fallback",
        )

    deliverable = DeliverableIntentType.UNKNOWN
    if any(cue in message for cue in scenario_cues):
        deliverable = DeliverableIntentType.SCENARIO_COMPARISON
    elif any(cue in message for cue in download_cues):
        deliverable = DeliverableIntentType.DOWNLOADABLE_TABLE
    elif any(cue in message for cue in estimate_cues):
        deliverable = DeliverableIntentType.ROUGH_ESTIMATE
    elif any(cue in message for cue in chart_cues):
        deliverable = DeliverableIntentType.CHART_OR_RANKED_SUMMARY
    elif any(cue in message for cue in summary_cues):
        deliverable = DeliverableIntentType.QUICK_SUMMARY
    elif any(cue in message for cue in explicit_map_cues):
        deliverable = (
            DeliverableIntentType.SPATIAL_MAP
            if context.has_geometry_support
            else DeliverableIntentType.CHART_OR_RANKED_SUMMARY
        )
    elif any(cue in message for cue in visualize_cues):
        deliverable = (
            DeliverableIntentType.SPATIAL_MAP
            if context.has_geometry_support
            else (
                DeliverableIntentType.CHART_OR_RANKED_SUMMARY
                if has_results
                else DeliverableIntentType.UNKNOWN
            )
        )

    progress = ProgressIntentType.ASK_CLARIFY
    if any(cue in message for cue in ambiguous_cues) and not (
        has_results or has_residual or has_recovered_target
    ):
        progress = ProgressIntentType.ASK_CLARIFY
    elif any(cue in message for cue in continuation_cues):
        if has_recovered_target:
            progress = ProgressIntentType.RESUME_RECOVERED_TARGET
        else:
            progress = ProgressIntentType.CONTINUE_CURRENT_TASK
    elif deliverable in {
        DeliverableIntentType.SPATIAL_MAP,
        DeliverableIntentType.CHART_OR_RANKED_SUMMARY,
        DeliverableIntentType.DOWNLOADABLE_TABLE,
        DeliverableIntentType.QUICK_SUMMARY,
        DeliverableIntentType.SCENARIO_COMPARISON,
    } and (has_results or has_residual or context.current_task_type):
        progress = ProgressIntentType.SHIFT_OUTPUT_MODE
    elif any(cue in message for cue in shift_output_cues) and (has_results or has_residual):
        progress = ProgressIntentType.SHIFT_OUTPUT_MODE
    elif has_recovered_target and any(cue in message for cue in continuation_cues):
        progress = ProgressIntentType.RESUME_RECOVERED_TARGET
    elif has_residual and any(cue in message for cue in continuation_cues):
        progress = ProgressIntentType.CONTINUE_CURRENT_TASK
    elif has_results and deliverable == DeliverableIntentType.UNKNOWN:
        progress = ProgressIntentType.ASK_CLARIFY
    else:
        progress = ProgressIntentType.ASK_CLARIFY

    confidence = 0.42
    if progress == ProgressIntentType.START_NEW_TASK:
        confidence = 0.9
    elif progress == ProgressIntentType.RESUME_RECOVERED_TARGET:
        confidence = 0.85
    elif progress == ProgressIntentType.CONTINUE_CURRENT_TASK:
        confidence = 0.8
    elif progress == ProgressIntentType.SHIFT_OUTPUT_MODE and deliverable != DeliverableIntentType.UNKNOWN:
        confidence = 0.84
    elif progress == ProgressIntentType.ASK_CLARIFY:
        confidence = 0.35

    if progress == ProgressIntentType.ASK_CLARIFY:
        reason = "The user message was too underspecified to safely decide whether to continue, resume, or change output mode."
    elif progress == ProgressIntentType.RESUME_RECOVERED_TARGET:
        reason = "The user sounded like they were continuing a recovered workflow target rather than starting a new task."
    elif progress == ProgressIntentType.CONTINUE_CURRENT_TASK:
        reason = "The user explicitly continued the current workflow instead of changing task direction."
    elif progress == ProgressIntentType.SHIFT_OUTPUT_MODE:
        if deliverable == DeliverableIntentType.CHART_OR_RANKED_SUMMARY and not context.has_geometry_support:
            reason = "The user asked for visualization, but the current context lacks safe spatial support, so a ranked summary/chart-style delivery is a better bounded fit."
        else:
            reason = "The user stayed on the current task but requested a different deliverable form."
    else:
        reason = "The user explicitly shifted to a new task direction."

    return IntentResolutionDecision(
        deliverable_intent=deliverable,
        progress_intent=progress,
        confidence=confidence,
        reason=reason,
        current_task_relevance=task_relevance,
        should_bias_existing_action=progress in {
            ProgressIntentType.CONTINUE_CURRENT_TASK,
            ProgressIntentType.RESUME_RECOVERED_TARGET,
            ProgressIntentType.SHIFT_OUTPUT_MODE,
        } or deliverable != DeliverableIntentType.UNKNOWN,
        should_preserve_residual_workflow=progress in {
            ProgressIntentType.CONTINUE_CURRENT_TASK,
            ProgressIntentType.RESUME_RECOVERED_TARGET,
            ProgressIntentType.SHIFT_OUTPUT_MODE,
        },
        should_trigger_clarification=progress == ProgressIntentType.ASK_CLARIFY,
        user_utterance_summary=_clean_text(context.user_message),
        resolution_source="fallback",
    )


def _ready_action_ids(context: IntentResolutionContext) -> List[str]:
    return [
        str(item.get("action_id"))
        for item in context.relevant_action_candidates
        if str(item.get("status") or "").strip().lower() == "ready"
        and str(item.get("action_id") or "").strip()
    ]


def _preferred_map_actions(context: IntentResolutionContext) -> List[str]:
    ready_actions = set(_ready_action_ids(context))
    preferred: List[str] = []

    if "hotspot" in context.recent_result_types and "render_hotspot_map" in ready_actions:
        preferred.append("render_hotspot_map")
    if "dispersion" in context.recent_result_types and "render_dispersion_map" in ready_actions:
        preferred.append("render_dispersion_map")
    if (
        ("emission" in context.recent_result_types or context.current_task_type in {"macro_emission", "micro_emission"})
        and "render_emission_map" in ready_actions
    ):
        preferred.append("render_emission_map")

    if not preferred:
        for action_id in ("render_hotspot_map", "render_dispersion_map", "render_emission_map"):
            if action_id in ready_actions and action_id not in preferred:
                preferred.append(action_id)
    return preferred


def build_intent_resolution_application_plan(
    decision: IntentResolutionDecision,
    context: IntentResolutionContext,
) -> IntentResolutionApplicationPlan:
    ready_actions = set(_ready_action_ids(context))
    preferred_action_ids: List[str] = []
    deprioritized_action_ids: List[str] = []
    preferred_artifact_kinds: List[str] = []
    state_resets: List[str] = []
    state_preserved: List[str] = []
    user_visible_summary: Optional[str] = None
    clarification_question: Optional[str] = None

    if decision.progress_intent == ProgressIntentType.START_NEW_TASK:
        state_resets.extend(
            [
                "active_parameter_negotiation",
                "active_input_completion",
                "geometry_recovery_context",
                "residual_reentry_context",
                "residual_workflow",
            ]
        )
        state_preserved.extend(["grounded_file_context", "session_trace", "working_memory"])
        return IntentResolutionApplicationPlan(
            deliverable_intent=decision.deliverable_intent,
            progress_intent=decision.progress_intent,
            preserve_current_task=False,
            preserve_residual_workflow=False,
            bias_existing_action=False,
            bias_followup_suggestions=False,
            bias_continuation=False,
            reset_current_task_context=True,
            supersede_recovered_target=True,
            require_clarification=False,
            preferred_action_ids=[],
            deprioritized_action_ids=[],
            preferred_artifact_kinds=[],
            guidance_summary=(
                "[Intent resolution]\n"
                "Progress intent=start_new_task.\n"
                "Treat this turn as a new task direction. Do not force residual continuation or recovered-target re-entry."
            ),
            user_visible_summary="您当前更像是在开始一个新的任务方向，而不是继续当前 residual workflow。",
            state_resets=state_resets,
            state_preserved=state_preserved,
        )

    if decision.progress_intent == ProgressIntentType.ASK_CLARIFY or decision.should_trigger_clarification:
        clarification_question = (
            "我现在还不确定您是想继续当前任务、切换输出形式，还是开始一个新任务。"
            " 请明确一下：是继续当前分析、改成地图/图表/导出，还是换成新任务？"
        )
        return IntentResolutionApplicationPlan(
            deliverable_intent=decision.deliverable_intent,
            progress_intent=ProgressIntentType.ASK_CLARIFY,
            preserve_current_task=True,
            preserve_residual_workflow=decision.should_preserve_residual_workflow,
            bias_existing_action=False,
            bias_followup_suggestions=False,
            bias_continuation=False,
            reset_current_task_context=False,
            supersede_recovered_target=False,
            require_clarification=True,
            clarification_question=clarification_question,
            user_visible_summary="当前我还不确定您是想继续当前任务，还是切换结果形式，请您确认一下。",
            state_preserved=["current_task_context", "readiness_state"],
        )

    if decision.progress_intent == ProgressIntentType.RESUME_RECOVERED_TARGET:
        recovered_action_id = _clean_text(context.recovered_target_summary.get("target_action_id"))
        if recovered_action_id:
            preferred_action_ids.append(recovered_action_id)
        state_preserved.extend(["current_task_context", "residual_workflow", "recovered_target"])
        user_visible_summary = "已识别您是在继续当前修复后的分析，下一步将优先围绕刚恢复的目标动作继续。"

    elif decision.progress_intent == ProgressIntentType.CONTINUE_CURRENT_TASK:
        state_preserved.extend(["current_task_context", "residual_workflow"])
        user_visible_summary = "已识别为继续当前任务，将优先沿用现有 workflow 上下文。"

    elif decision.progress_intent == ProgressIntentType.SHIFT_OUTPUT_MODE:
        state_preserved.extend(["current_task_context", "residual_workflow"])
        user_visible_summary = "您当前更像是在切换输出形式，而不是开始一个新任务。"

    if decision.deliverable_intent == DeliverableIntentType.SPATIAL_MAP:
        preferred_action_ids.extend(
            action_id for action_id in _preferred_map_actions(context) if action_id not in preferred_action_ids
        )
        preferred_artifact_kinds.append("map")
        if preferred_action_ids:
            user_visible_summary = user_visible_summary or "已识别您当前更偏向空间地图输出。"
        else:
            preferred_artifact_kinds.extend(["chart", "table", "summary"])
            deprioritized_action_ids.extend(sorted(_MAP_ACTION_IDS))
            user_visible_summary = (
                "当前尚不具备安全的空间地图输出条件；若需继续展示，现阶段更适合先用摘要表或排序概览。"
            )

    elif decision.deliverable_intent == DeliverableIntentType.CHART_OR_RANKED_SUMMARY:
        for action_id in ("render_rank_chart", "download_topk_summary", "deliver_quick_structured_summary"):
            if action_id in ready_actions and action_id not in preferred_action_ids:
                preferred_action_ids.append(action_id)
        deprioritized_action_ids.extend(sorted(_MAP_ACTION_IDS))
        preferred_artifact_kinds.extend(["chart", "table", "summary"])
        user_visible_summary = (
            "当前更适合用排序图和摘要表展示结果；若需地图仍需补充空间几何。"
        )

    elif decision.deliverable_intent == DeliverableIntentType.DOWNLOADABLE_TABLE:
        deprioritized_action_ids.extend(sorted(_MAP_ACTION_IDS))
        preferred_artifact_kinds.extend(["download", "table", "summary"])
        user_visible_summary = user_visible_summary or "当前更偏向结果导出或表格交付，而不是新的分析步骤。"

    elif decision.deliverable_intent == DeliverableIntentType.QUICK_SUMMARY:
        if "deliver_quick_structured_summary" in ready_actions:
            preferred_action_ids.append("deliver_quick_structured_summary")
        preferred_artifact_kinds.extend(["summary", "table"])
        deprioritized_action_ids.extend(sorted(_MAP_ACTION_IDS))
        user_visible_summary = user_visible_summary or "当前更偏向简洁结论和摘要展示。"

    elif decision.deliverable_intent == DeliverableIntentType.ROUGH_ESTIMATE:
        preferred_artifact_kinds.append("summary")
        user_visible_summary = user_visible_summary or "当前更偏向快速估计或粗粒度结论。"

    elif decision.deliverable_intent == DeliverableIntentType.SCENARIO_COMPARISON:
        if "compare_scenario" in ready_actions:
            preferred_action_ids.append("compare_scenario")
        preferred_artifact_kinds.extend(["summary", "chart", "table"])
        user_visible_summary = user_visible_summary or "当前更偏向情景对比结果。"

    guidance_lines = [
        "[Intent resolution]",
        f"Deliverable intent={decision.deliverable_intent.value}",
        f"Progress intent={decision.progress_intent.value}",
    ]
    if user_visible_summary:
        guidance_lines.append(user_visible_summary)
    if preferred_action_ids:
        guidance_lines.append(
            "Prefer these current actions if readiness allows: " + ", ".join(preferred_action_ids)
        )
    if deprioritized_action_ids:
        guidance_lines.append(
            "Deprioritize these actions unless the user explicitly insists and they are ready: "
            + ", ".join(dict.fromkeys(deprioritized_action_ids))
        )
    if preferred_artifact_kinds:
        guidance_lines.append(
            "Prefer this output form when no direct action is needed: "
            + ", ".join(dict.fromkeys(preferred_artifact_kinds))
        )
    guidance_lines.append(
        "Do not treat deliverable intent as a tool name. Readiness remains the legality boundary."
    )

    return IntentResolutionApplicationPlan(
        deliverable_intent=decision.deliverable_intent,
        progress_intent=decision.progress_intent,
        preserve_current_task=True,
        preserve_residual_workflow=decision.should_preserve_residual_workflow,
        bias_existing_action=decision.should_bias_existing_action,
        bias_followup_suggestions=True,
        bias_continuation=decision.progress_intent in {
            ProgressIntentType.CONTINUE_CURRENT_TASK,
            ProgressIntentType.RESUME_RECOVERED_TARGET,
        },
        reset_current_task_context=False,
        supersede_recovered_target=decision.progress_intent == ProgressIntentType.SHIFT_OUTPUT_MODE,
        require_clarification=False,
        preferred_action_ids=list(dict.fromkeys(preferred_action_ids)),
        deprioritized_action_ids=list(dict.fromkeys(deprioritized_action_ids)),
        preferred_artifact_kinds=list(dict.fromkeys(preferred_artifact_kinds)),
        guidance_summary="\n".join(guidance_lines),
        user_visible_summary=user_visible_summary,
        state_preserved=state_preserved,
        state_resets=state_resets,
    )


def apply_intent_bias_to_capability_summary(
    summary: Optional[Dict[str, Any]],
    plan: Optional[IntentResolutionApplicationPlan],
) -> Optional[Dict[str, Any]]:
    if not isinstance(summary, dict):
        return summary
    if plan is None:
        return dict(summary)

    preferred = list(dict.fromkeys(plan.preferred_action_ids))
    preferred_index = {action_id: index for index, action_id in enumerate(preferred)}
    deprioritized = set(plan.deprioritized_action_ids)

    def _sort_actions(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        enumerated = [
            (index, dict(item))
            for index, item in enumerate(items)
            if isinstance(item, dict)
        ]

        def _rank(pair: tuple[int, Dict[str, Any]]) -> tuple[int, int, int]:
            index, item = pair
            action_id = str(item.get("action_id") or "").strip()
            if action_id in preferred_index:
                return (0, preferred_index[action_id], index)
            if action_id in deprioritized:
                return (2, 0, index)
            return (1, 0, index)

        return [item for _index, item in sorted(enumerated, key=_rank)]

    biased = dict(summary)
    for key in ("available_next_actions", "repairable_actions", "unavailable_actions_with_reasons"):
        biased[key] = _sort_actions(summary.get(key) or [])

    hints = [
        str(item).strip()
        for item in (summary.get("guidance_hints") or [])
        if str(item).strip()
    ]
    if plan.user_visible_summary and plan.user_visible_summary not in hints:
        hints.insert(0, plan.user_visible_summary)
    biased["guidance_hints"] = hints
    biased["intent_bias"] = {
        "deliverable_intent": plan.deliverable_intent.value,
        "progress_intent": plan.progress_intent.value,
        "preferred_action_ids": list(plan.preferred_action_ids),
        "deprioritized_action_ids": list(plan.deprioritized_action_ids),
        "preferred_artifact_kinds": list(plan.preferred_artifact_kinds),
        "user_visible_summary": plan.user_visible_summary,
    }
    return biased
