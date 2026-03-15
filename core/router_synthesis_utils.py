"""Helper functions extracted from ``core.router`` for synthesis preparation."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from core.router_render_utils import (
    filter_results_for_synthesis,
    format_results_as_fallback,
    render_single_tool_success,
)

TOOLS_NEEDING_RENDERING = {
    "query_emission_factors",
    "calculate_micro_emission",
    "calculate_macro_emission",
    "analyze_file",
}


def maybe_short_circuit_synthesis(tool_results: list[Dict[str, Any]]) -> Optional[str]:
    """Return a deterministic synthesis result when no LLM call is needed."""
    if len(tool_results) == 1 and tool_results[0].get("name") == "query_knowledge":
        knowledge_result = tool_results[0].get("result", {})
        if knowledge_result.get("success") and knowledge_result.get("summary"):
            return knowledge_result["summary"]

    if any(not item.get("result", {}).get("success") for item in tool_results):
        return format_results_as_fallback(tool_results)

    if len(tool_results) == 1:
        only_result = tool_results[0].get("result", {})
        only_name = tool_results[0].get("name", "unknown")

        if only_result.get("success"):
            if only_name in TOOLS_NEEDING_RENDERING:
                return render_single_tool_success(only_name, only_result)
            if only_result.get("summary"):
                return only_result["summary"]
            return render_single_tool_success(only_name, only_result)

    return None


def build_synthesis_request(
    last_user_message: Optional[str],
    tool_results: list[Dict[str, Any]],
    prompt_template: str,
) -> Dict[str, Any]:
    """Build the filtered synthesis payload, prompt, and message list."""
    filtered_results = filter_results_for_synthesis(tool_results)
    results_json = json.dumps(filtered_results, ensure_ascii=False, indent=2)
    synthesis_prompt = prompt_template.replace("{results}", results_json)
    synthesis_messages = [{"role": "user", "content": last_user_message or "请总结计算结果"}]

    return {
        "filtered_results": filtered_results,
        "results_json": results_json,
        "system_prompt": synthesis_prompt,
        "messages": synthesis_messages,
    }


def detect_hallucination_keywords(content: str, keywords: list[str]) -> list[str]:
    """Return the subset of warning keywords found in synthesis output."""
    return [keyword for keyword in keywords if keyword in content]
