"""Capability-aware follow-up guidance built on the unified readiness layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from core.artifact_memory import (
    ArtifactMemoryState,
    apply_artifact_memory_to_capability_summary,
)
from core.intent_resolution import IntentResolutionApplicationPlan
from core.readiness import build_readiness_assessment

if TYPE_CHECKING:
    from core.context_store import SessionContextStore


_FOLLOW_UP_ACTIONS_BY_TOOL: Dict[str, Sequence[str]] = {
    "calculate_macro_emission": (
        "render_rank_chart",
        "download_topk_summary",
        "deliver_quick_structured_summary",
        "render_emission_map",
        "run_dispersion",
        "compare_scenario",
    ),
    "calculate_micro_emission": ("render_emission_map", "run_dispersion"),
    "calculate_dispersion": ("run_hotspot_analysis", "render_dispersion_map", "compare_scenario"),
    "analyze_hotspots": ("render_hotspot_map", "compare_scenario"),
}


def build_capability_summary(
    file_context: Optional[Dict[str, Any]],
    context_store: Optional["SessionContextStore"],
    current_tool_results: Sequence[Dict[str, Any]],
    current_response_payloads: Optional[Dict[str, Any]] = None,
    parameter_locks: Optional[Dict[str, Any]] = None,
    artifact_memory_state: Optional[ArtifactMemoryState] = None,
    intent_plan: Optional[IntentResolutionApplicationPlan] = None,
) -> Dict[str, Any]:
    """Return the legacy capability-summary surface backed by readiness assessment."""
    assessment = build_readiness_assessment(
        file_context,
        context_store,
        current_tool_results,
        current_response_payloads,
        parameter_locks=parameter_locks,
        artifact_memory_state=artifact_memory_state,
    )
    summary = assessment.to_capability_summary()
    return apply_artifact_memory_to_capability_summary(
        summary,
        artifact_memory_state,
        intent_plan=intent_plan,
        dedup_by_family=True,
    ) or summary


def format_capability_summary_for_prompt(summary: Optional[Dict[str, Any]]) -> str:
    """Render one bounded prompt section for synthesis."""
    if not isinstance(summary, dict):
        return ""

    available_actions = summary.get("available_next_actions") or []
    repairable_actions = summary.get("repairable_actions") or []
    unavailable_actions = summary.get("unavailable_actions_with_reasons") or []
    already_provided = summary.get("already_provided") or []
    guidance_hints = summary.get("guidance_hints") or []
    intent_bias = summary.get("intent_bias") or {}
    artifact_bias = summary.get("artifact_bias") or {}

    blocked_only = [
        item for item in unavailable_actions
        if item not in repairable_actions
    ]

    lines = [
        "## 后续建议硬约束",
        "",
        "以下是当前数据的 readiness 边界。下面的约束优先级高于一般总结要求，你必须严格遵守：",
        "",
        "### 当前可直接执行的操作",
    ]

    if available_actions:
        for item in available_actions:
            lines.append(f"- {item.get('label')}: {item.get('description')}")
    else:
        lines.append("- 当前没有额外的可执行后续操作可以安全推荐。")

    lines.extend(["", "### 当前可修复但尚未就绪的操作（不要直接建议这些）"])
    if repairable_actions:
        for item in repairable_actions:
            repair_hint = str(item.get("repair_hint") or "").strip()
            reason = str(item.get("reason") or "").strip()
            if repair_hint:
                lines.append(f"- {item.get('label')}: {reason} 补救方向：{repair_hint}")
            else:
                lines.append(f"- {item.get('label')}: {reason}")
    else:
        lines.append("- 无。")

    lines.extend(["", "### 当前被阻断的操作（严禁将这些列为推荐选项）"])
    if blocked_only:
        for item in blocked_only:
            lines.append(f"- {item.get('label')}: {item.get('reason')}")
    else:
        lines.append("- 无。")

    lines.extend(["", "### 本次已提供的交付物（不要重复建议这些）"])
    if already_provided:
        for item in already_provided:
            lines.append(f"- {item.get('display_name') or item.get('label')}: {item.get('message') or item.get('reason')}")
    else:
        lines.append("- 无。")

    if guidance_hints:
        lines.extend(["", "### 能力边界提示"])
        for hint in guidance_hints:
            lines.append(f"- {hint}")

    if isinstance(intent_bias, dict) and intent_bias:
        deliverable = str(intent_bias.get("deliverable_intent") or "").strip()
        progress = str(intent_bias.get("progress_intent") or "").strip()
        preferred_actions = [
            str(item).strip()
            for item in (intent_bias.get("preferred_action_ids") or [])
            if str(item).strip()
        ]
        preferred_artifacts = [
            str(item).strip()
            for item in (intent_bias.get("preferred_artifact_kinds") or [])
            if str(item).strip()
        ]
        lines.extend(["", "### 当前高层意图偏置"])
        if deliverable or progress:
            lines.append(
                f"- deliverable_intent={deliverable or 'unknown'}; progress_intent={progress or 'unknown'}"
            )
        if preferred_actions:
            lines.append(f"- 优先动作: {', '.join(preferred_actions)}")
        if preferred_artifacts:
            lines.append(f"- 优先交付形态: {', '.join(preferred_artifacts)}")

    if isinstance(artifact_bias, dict) and artifact_bias:
        suppressed = [
            str(item).strip()
            for item in (artifact_bias.get("suppressed_action_ids") or [])
            if str(item).strip()
        ]
        promoted = [
            str(item).strip()
            for item in (artifact_bias.get("promoted_families") or [])
            if str(item).strip()
        ]
        repeated_types = [
            str(item).strip()
            for item in (artifact_bias.get("repeated_artifact_types") or [])
            if str(item).strip()
        ]
        lines.extend(["", "### 已交付 artifact 记忆"])
        if repeated_types:
            lines.append(f"- 已完整提供的类型: {', '.join(repeated_types)}")
        if suppressed:
            lines.append(f"- 需抑制重复动作: {', '.join(suppressed)}")
        if promoted:
            lines.append(f"- 更适合补充的输出族: {', '.join(promoted)}")

    lines.extend(
        [
            "",
            "### 最终硬性要求",
            "- 你只能建议“当前可直接执行的操作”中的项目。",
            "- 严禁把 repairable 或 blocked 的动作写成建议列表项、下一步选项或可点击动作。",
            "- repairable 动作如需提及，只能用一句前置条件说明，不能写成推荐。",
            "- 严禁重复建议已提供的下载文件、地图、图表或表格。",
            "- 严禁发明未列出的导出、可视化或分析步骤。",
            "- 如果当前没有安全的后续操作，就明确说“当前没有额外的安全后续操作建议”。",
        ]
    )
    return "\n".join(lines)


def get_capability_aware_follow_up(
    tool_name: str,
    capability_summary: Optional[Dict[str, Any]],
) -> Dict[str, List[str]]:
    """Return filtered follow-up suggestions and hints for deterministic rendering."""
    if not isinstance(capability_summary, dict):
        return {"suggestions": [], "hints": []}

    desired_action_ids = _FOLLOW_UP_ACTIONS_BY_TOOL.get(tool_name, ())
    intent_bias = capability_summary.get("intent_bias") or {}
    available_by_id = {
        item.get("action_id"): item
        for item in capability_summary.get("available_next_actions") or []
        if isinstance(item, dict) and item.get("action_id")
    }
    unavailable_by_id = {
        item.get("action_id"): item
        for item in capability_summary.get("unavailable_actions_with_reasons") or []
        if isinstance(item, dict) and item.get("action_id")
    }

    suggestions: List[str] = []
    hints: List[str] = []
    deliverable_intent = str(intent_bias.get("deliverable_intent") or "").strip()
    preferred_action_ids = [
        str(item).strip()
        for item in (intent_bias.get("preferred_action_ids") or [])
        if str(item).strip()
    ]
    deprioritized_action_ids = {
        str(item).strip()
        for item in (intent_bias.get("deprioritized_action_ids") or [])
        if str(item).strip()
    }
    artifact_bias = capability_summary.get("artifact_bias") or {}
    suppressed_by_artifact = {
        str(item).strip()
        for item in (artifact_bias.get("suppressed_action_ids") or [])
        if str(item).strip()
    }

    ordered_action_ids: List[str] = []
    for action_id in preferred_action_ids:
        if action_id in desired_action_ids and action_id not in ordered_action_ids:
            ordered_action_ids.append(action_id)
    for action_id in desired_action_ids:
        if action_id in ordered_action_ids:
            continue
        ordered_action_ids.append(action_id)

    if deliverable_intent in {
        "chart_or_ranked_summary",
        "downloadable_table",
        "quick_summary",
        "rough_estimate",
    } and not any(action_id in preferred_action_ids for action_id in desired_action_ids):
        ordered_action_ids = []

    for action_id in ordered_action_ids:
        if action_id in suppressed_by_artifact:
            continue
        if action_id in deprioritized_action_ids and action_id not in preferred_action_ids:
            continue
        item = available_by_id.get(action_id)
        if item and item.get("utterance"):
            suggestions.append(str(item["utterance"]))

    for action_id in ordered_action_ids or desired_action_ids:
        item = unavailable_by_id.get(action_id)
        if not item:
            continue
        reason_codes = item.get("reason_codes") or []
        if "missing_geometry" in reason_codes:
            hint = "如需空间分析，请补充路段坐标、WKT、GeoJSON 或其他几何信息。"
            if hint not in hints:
                hints.append(hint)
                continue
        repair_hint = str(item.get("repair_hint") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if repair_hint and repair_hint not in hints:
            hints.append(repair_hint)
        elif reason and reason not in hints:
            hints.append(reason)

    for hint in capability_summary.get("guidance_hints") or []:
        text = str(hint).strip()
        if text and text not in hints:
            hints.append(text)

    bias_summary = str(intent_bias.get("user_visible_summary") or "").strip()
    if bias_summary and bias_summary not in hints:
        hints.insert(0, bias_summary)

    artifact_summary = str(artifact_bias.get("user_visible_summary") or "").strip()
    if artifact_summary and artifact_summary not in hints:
        hints.insert(0, artifact_summary)

    return {
        "suggestions": suggestions,
        "hints": hints,
    }
