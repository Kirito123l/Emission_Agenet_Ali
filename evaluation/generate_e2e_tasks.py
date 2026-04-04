"""Generate LLM-authored end-to-end evaluation tasks."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.context_extractor import (
    extract_system_capabilities,
    extract_tool_contracts,
    load_existing_end2end_tasks,
    load_jsonl_records,
)
from evaluation.llm_generator import LLMGenerator
from evaluation.utils import write_json, write_jsonl


logger = logging.getLogger(__name__)

BENCHMARK_PATH = PROJECT_ROOT / "evaluation" / "benchmarks" / "end2end_tasks.jsonl"
GENERATED_DIR = PROJECT_ROOT / "evaluation" / "generated"
SUMMARY_PATH = GENERATED_DIR / "e2e_tasks_summary.json"
CROSS_CONSTRAINTS_PATH = PROJECT_ROOT / "config" / "cross_constraints.yaml"

CATEGORY_DESCRIPTIONS = {
    "simple": "单步、参数明确，不需要澄清或协商。",
    "parameter_ambiguous": "参数表达口语化或非标准，需要标准化模块正确处理。",
    "multi_step": "请求隐含多个工具串联，测试工作流编排和依赖管理。",
    "incomplete": "缺少关键参数或上下文，需要系统发起澄清和补全。",
    "constraint_violation": "参数组合违反交叉约束，应触发约束拦截或警告。",
}
DEFAULT_COUNT_BY_CATEGORY = {category: 10 for category in CATEGORY_DESCRIPTIONS}

CATEGORY_ID_PREFIX = {
    "simple": "simple",
    "parameter_ambiguous": "ambiguous",
    "multi_step": "multistep",
    "incomplete": "incomplete",
    "constraint_violation": "constraint",
}

SAMPLE_TEST_FILES_BY_TOOL = {
    "analyze_file": "evaluation/file_tasks/data/macro_direct.csv",
    "calculate_micro_emission": "evaluation/file_tasks/data/micro_time_speed.csv",
    "calculate_macro_emission": "evaluation/file_tasks/data/macro_direct.csv",
}

E2E_SYSTEM_PROMPT = """你是一个交通环境分析系统的测试工程师。你需要模拟真实用户向系统提问的场景，生成测试任务。

系统能力：
{system_capabilities}

用户画像：
- 城市规划师：关注区域排放总量、空间分布、政策影响
- 环境研究者：关注排放因子、污染物浓度、扩散模拟
- 交通工程师：关注路段级排放、不同车型对比、情景分析
- 非专业人士：用口语表达，可能不清楚具体参数

生成规则：
- 用户消息要自然、口语化，像真人在对话框里打字
- 不要使用系统内部术语，用户不知道这些名字
- 每条任务都要有明确的预期行为
- 中文为主，允许少量中英混杂
- 必须显式覆盖这些测试面：文件驱动分流、参数协商、约束冲突、工具依赖链、多步执行、恢复路径
- 如果任务本身不会真正执行工具，expected_tool 设为 null，expected_tool_chain 设为空数组
- 如果 has_file=true 且不确定 test_file，可返回 null，我会补默认测试文件
- 只输出 JSON，不要附加解释"""

E2E_USER_PROMPT_TEMPLATE = """请为 "{category}" 类别生成 {count} 条测试任务。

类别说明：{category_description}

本轮优先覆盖这些测试面：
{coverage_requirements}

已有的任务（不要重复）：
{existing_tasks}

输出格式（严格 JSON 对象）：
{{
  "tasks": [
    {{
      "category": "{category}",
      "description": "简要说明这条任务测试什么",
      "user_message": "用户实际会说的话",
      "has_file": true,
      "test_file": null,
      "expected_tool": "期望调用的主要工具名称；如果不会执行则为 null",
      "expected_tool_chain": ["按执行顺序列出工具；如果不会执行则为空数组"],
      "expected_params": {{
        "参数名": "期望的参数值"
      }},
      "expected_behavior": "期望系统行为，如成功执行/触发参数协商/触发交叉约束拦截/说明恢复路径",
      "notes": "补充说明"
    }}
  ]
}}"""

E2E_COVERAGE_REQUIREMENTS = [
    "文件驱动分流: 用户是否上传文件会影响进入 query / micro / macro / post-processing 路径。",
    "参数协商: 参数缺失、模糊或无法安全标准化时需要补问。",
    "约束冲突: 既包含应被拦截的 blocked case，也包含 warning-only case。",
    "工具依赖链: 体现 emission -> dispersion -> hotspot / render 等依赖关系。",
    "多步执行: 用户一句话隐含多个连续动作。",
    "恢复路径: 当请求缺参、冲突或被阻断时，expected_behavior 应描述后续如何恢复。",
]

REVIEW_KEYWORDS = {
    "incomplete": ("澄清", "补充", "协商", "clarify", "follow-up", "补全", "询问", "追问", "提示", "引导", "确认", "说明"),
    "constraint_violation": ("拦截", "约束", "阻止", "block", "warning", "警告", "constraint", "拒绝", "确认"),
}

INCOMPLETE_CANDIDATE_META_KEYS = {
    "target_tool",
    "known_params",
    "missing_required_params",
    "negotiable_params",
}
CONSTRAINT_CANDIDATE_META_KEYS = {
    "target_tool",
    "known_params",
    "conflicting_params",
    "violated_constraints",
    "expected_negotiation_or_rejection",
}
CONSTRAINT_ACTION_ALIASES = {
    "reject": "reject",
    "rejection": "reject",
    "block": "reject",
    "blocked": "reject",
    "warning": "warn",
    "warn": "warn",
    "continue": "warn",
    "proceed_with_warning": "warn",
    "negotiate": "negotiate",
    "clarify": "negotiate",
    "ask_user": "negotiate",
    "parameter_negotiation": "negotiate",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate end-to-end task candidates with Qwen.")
    parser.add_argument("--category", choices=tuple(CATEGORY_DESCRIPTIONS))
    parser.add_argument("--all", action="store_true", dest="generate_all")
    parser.add_argument("--count", type=int, default=None, help="Override generation count. If omitted, uses default per category.")
    parser.add_argument("--model", default=None, help="Model override. Precedence is CLI > env > default.")
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--max-rounds", type=int, default=6)
    parser.add_argument("--replace-existing", action="store_true", help="Regenerate the target category from scratch instead of appending to existing candidates.")
    return parser.parse_args()


def _parse_id_suffix(raw_id: str) -> int:
    tail = str(raw_id).rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _normalize_message(value: Any) -> str:
    return str(value).strip()


def _normalize_optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned or cleaned.lower() in {"null", "none", "nil"}:
        return None
    return cleaned


def _normalize_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    items: List[str] = []
    seen = set()
    for item in value:
        cleaned = str(item).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        items.append(cleaned)
    return items


def _normalize_conflicting_params(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    normalized: List[Dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            param = _normalize_optional_string(item.get("param") or item.get("name"))
            if not param:
                continue
            normalized.append({"param": param, "value": item.get("value")})
        else:
            param = _normalize_optional_string(item)
            if param:
                normalized.append({"param": param, "value": None})
    return normalized


def _normalize_constraint_action(value: Any, expected_behavior: str) -> Optional[str]:
    cleaned = _normalize_optional_string(value)
    if cleaned:
        alias = CONSTRAINT_ACTION_ALIASES.get(cleaned.strip().lower())
        if alias:
            return alias

    lowered = expected_behavior.lower()
    if any(token in lowered for token in ("warning", "警告", "warn")):
        return "warn"
    if any(token in lowered for token in ("协商", "澄清", "clarify", "negotiate", "询问")):
        return "negotiate"
    if any(token in lowered for token in ("拦截", "阻止", "拒绝", "block", "reject", "constraint")):
        return "reject"
    return None


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return bool(value)


def _existing_task_prompt_view(records: Sequence[Dict[str, Any]], limit: int = 80) -> str:
    simplified = []
    for record in records[:limit]:
        simplified.append(
            {
                "category": record.get("category"),
                "user_message": record.get("user_message"),
                "expected_tool_chain": record.get("expected_tool_chain", []),
            }
        )
    return json.dumps(simplified, ensure_ascii=False, indent=2)


def _load_existing_generated_records(category: str) -> List[Dict[str, Any]]:
    path = GENERATED_DIR / f"e2e_tasks_{category}.jsonl"
    return load_jsonl_records(path)


def _load_cross_constraints() -> Dict[str, Dict[str, Any]]:
    with CROSS_CONSTRAINTS_PATH.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}

    constraints: Dict[str, Dict[str, Any]] = {}
    for item in payload.get("constraints", []) or []:
        if not isinstance(item, dict):
            continue
        name = _normalize_optional_string(item.get("name"))
        if not name:
            continue
        constraints[name] = item
    return constraints


def _constraint_prompt_context() -> str:
    constraints = _load_cross_constraints()
    if not constraints:
        return "当前仓库未配置 cross constraints，请不要生成该类别。"

    lines: List[str] = ["当前仓库已配置的合法约束场景："]
    for name, item in constraints.items():
        description = str(item.get("description", "")).strip()
        constraint_type = str(item.get("type", "")).strip()
        lines.append(f"- {name}: {constraint_type}; {description}")
        rules = item.get("rules", {}) or {}
        for key, rule in list(rules.items())[:3]:
            if isinstance(rule, dict):
                lines.append(f"  触发示例: {key} -> {json.dumps(rule, ensure_ascii=False)}")
    return "\n".join(lines)


def _category_specific_requirements(category: str) -> str:
    if category == "incomplete":
        return (
            "Incomplete 类别专用要求:\n"
            "- expected_tool 必须为 null。\n"
            "- expected_tool_chain 必须为空数组。\n"
            "- expected_params 必须使用结构化候选格式:\n"
            '  {"target_tool": "...", "known_params": {...}, "missing_required_params": ["..."], "negotiable_params": ["..."]}\n'
            "- target_tool 表示补全完成后准备执行的目标工具。\n"
            "- missing_required_params 必须明确列出当前缺失的必填参数，不能为空。\n"
            "- negotiable_params 用于列出可通过追问确认的参数，可为空。\n"
            "- 优先生成“可协商补全”的样本，不要生成只能失败不能恢复的空洞请求。\n"
            "- 不要让 incomplete 样本通过 analyze_file 或其他工具先执行后再澄清。"
        )
    if category == "constraint_violation":
        return (
            "Constraint_violation 类别专用要求:\n"
            "- 只生成基于当前仓库合法约束的场景，严格使用 config/cross_constraints.yaml 中已有规则。\n"
            f"{_constraint_prompt_context()}\n"
            "- 当前最可靠的合法场景只有两类：\n"
            "  1. vehicle_road_compatibility: Motorcycle + 高速公路 -> reject 或 negotiate。\n"
            "  2. season_meteorology_consistency: 冬季+urban_summer_day/night 或 夏季+urban_winter_day/night -> warn。\n"
            "- 不要发明新约束，不要把 School Bus/Refuse Truck/其他车型 + 高速公路写成合法 violated_constraints，除非 config 明确配置。\n"
            "- 不要生成“已经修正为合法组合”的恢复成功样本，这不属于 constraint_violation。\n"
            "- expected_params 必须使用结构化候选格式:\n"
            '  {"target_tool": "...", "known_params": {...}, "conflicting_params": [{"param": "...", "value": "..."}], '
            '"violated_constraints": ["..."], "expected_negotiation_or_rejection": "reject|warn|negotiate"}\n'
            "- reject: 应拦截，不执行工具，expected_tool=null，expected_tool_chain=[]。\n"
            "- negotiate: 应先协商，不执行工具，expected_tool=null，expected_tool_chain=[]。\n"
            "- warn: 可继续执行但必须带 warning，expected_tool_chain 应是合法可执行链。\n"
            "- 每条 constraint_violation 样本都必须在 conflicting_params 里显式写出触发冲突的参数值对；如果信息不完整，就不要生成该样本。"
        )
    return ""


def _build_prompt(*, category: str, count: int, existing_tasks: Sequence[Dict[str, Any]]) -> tuple[str, str]:
    system_prompt = E2E_SYSTEM_PROMPT.format(system_capabilities=extract_system_capabilities())
    user_prompt = E2E_USER_PROMPT_TEMPLATE.format(
        category=category,
        count=count,
        category_description=CATEGORY_DESCRIPTIONS[category],
        coverage_requirements=json.dumps(E2E_COVERAGE_REQUIREMENTS, ensure_ascii=False, indent=2),
        existing_tasks=_existing_task_prompt_view(existing_tasks),
    )
    category_specific = _category_specific_requirements(category)
    if category_specific:
        user_prompt = f"{user_prompt}\n\n{category_specific}"
    return system_prompt, user_prompt


def _select_default_test_file(
    category: str,
    tool_chain: Sequence[str],
    has_file: bool,
    target_tool: Optional[str] = None,
) -> Optional[str]:
    if not has_file:
        return None

    if target_tool and target_tool in SAMPLE_TEST_FILES_BY_TOOL:
        return SAMPLE_TEST_FILES_BY_TOOL[target_tool]

    for tool_name in tool_chain:
        if tool_name in SAMPLE_TEST_FILES_BY_TOOL:
            return SAMPLE_TEST_FILES_BY_TOOL[tool_name]

    candidate_tools = list(tool_chain)
    if target_tool:
        candidate_tools.append(target_tool)

    if any(tool_name in {"calculate_dispersion", "analyze_hotspots", "render_spatial_map", "compare_scenarios"} for tool_name in candidate_tools):
        return "evaluation/file_tasks/data/macro_direct.csv"
    if category in {"multi_step", "constraint_violation"}:
        return "evaluation/file_tasks/data/macro_direct.csv"
    return None


def _derive_success_criteria(category: str, expected_behavior: str, expected_params: Dict[str, Any]) -> Dict[str, Any]:
    behavior = expected_behavior.lower()
    if category == "incomplete":
        return {"tool_executed": False, "requires_user_response": True, "result_has_data": False}
    if category == "constraint_violation":
        action = _normalize_constraint_action(expected_params.get("expected_negotiation_or_rejection"), expected_behavior)
        if action == "negotiate":
            return {"tool_executed": False, "requires_user_response": True, "result_has_data": False}
        if action == "warn" or any(keyword in behavior for keyword in ("warning", "警告", "warn")):
            return {"tool_executed": True, "params_legal": True, "constraint_warning": True, "result_has_data": True}
        return {"tool_executed": False, "constraint_blocked": True, "result_has_data": False}
    return {"tool_executed": True, "params_legal": True, "result_has_data": True}


def _normalize_incomplete_expected_params(expected_params: Dict[str, Any]) -> Dict[str, Any]:
    raw_known = expected_params.get("known_params", {})
    if not isinstance(raw_known, dict):
        raw_known = {}
    fallback_known = {
        key: value for key, value in expected_params.items() if key not in INCOMPLETE_CANDIDATE_META_KEYS
    }
    known_params = raw_known or fallback_known
    return {
        "target_tool": _normalize_optional_string(expected_params.get("target_tool")),
        "known_params": known_params,
        "missing_required_params": _normalize_string_list(expected_params.get("missing_required_params")),
        "negotiable_params": _normalize_string_list(expected_params.get("negotiable_params")),
    }


def _normalize_constraint_expected_params(expected_params: Dict[str, Any], expected_behavior: str) -> Dict[str, Any]:
    raw_known = expected_params.get("known_params", {})
    if not isinstance(raw_known, dict):
        raw_known = {}
    fallback_known = {
        key: value for key, value in expected_params.items() if key not in CONSTRAINT_CANDIDATE_META_KEYS
    }
    return {
        "target_tool": _normalize_optional_string(expected_params.get("target_tool")),
        "known_params": raw_known or fallback_known,
        "conflicting_params": _normalize_conflicting_params(expected_params.get("conflicting_params")),
        "violated_constraints": _normalize_string_list(expected_params.get("violated_constraints")),
        "expected_negotiation_or_rejection": _normalize_constraint_action(
            expected_params.get("expected_negotiation_or_rejection"),
            expected_behavior,
        ),
    }


def _normalize_candidate_expected_params(category: str, expected_params: Dict[str, Any], expected_behavior: str) -> Dict[str, Any]:
    if category == "incomplete":
        return _normalize_incomplete_expected_params(expected_params)
    if category == "constraint_violation":
        return _normalize_constraint_expected_params(expected_params, expected_behavior)
    return expected_params


def _normalize_task_payload(category: str, raw_task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    user_message = _normalize_message(raw_task.get("user_message", ""))
    description = _normalize_message(raw_task.get("description", ""))
    if not user_message or not description:
        return None

    expected_tool = _normalize_optional_string(raw_task.get("expected_tool"))
    raw_chain = raw_task.get("expected_tool_chain", [])
    if isinstance(raw_chain, list):
        expected_tool_chain = [_normalize_message(item) for item in raw_chain if _normalize_message(item)]
    else:
        expected_tool_chain = []

    if not expected_tool_chain and expected_tool:
        expected_tool_chain = [expected_tool]
    if expected_tool is None and len(expected_tool_chain) == 1:
        expected_tool = expected_tool_chain[0]

    expected_params = raw_task.get("expected_params", {})
    if not isinstance(expected_params, dict):
        expected_params = {}

    has_file = _bool_value(raw_task.get("has_file"))
    test_file = _normalize_optional_string(raw_task.get("test_file"))
    expected_behavior = _normalize_message(raw_task.get("expected_behavior", ""))
    notes = _normalize_message(raw_task.get("notes", ""))
    expected_params = _normalize_candidate_expected_params(category, expected_params, expected_behavior)

    return {
        "category": category,
        "description": description,
        "user_message": user_message,
        "has_file": has_file,
        "test_file": test_file,
        "expected_tool": expected_tool,
        "expected_tool_chain": expected_tool_chain,
        "expected_params": expected_params,
        "expected_behavior": expected_behavior,
        "notes": notes,
    }


def _tool_param_context(tool_name: Optional[str], tool_contracts: Dict[str, Any]) -> tuple[set[str], set[str]]:
    if not tool_name or tool_name not in tool_contracts:
        return set(), set()
    parameters = ((tool_contracts.get(tool_name) or {}).get("parameters", {}) or {})
    valid = set(parameters.keys())
    required = {
        name for name, info in parameters.items()
        if isinstance(info, dict) and bool(info.get("required"))
    }
    return valid, required


def _reference_tool_for_review(category: str, chain: Sequence[str], task: Dict[str, Any]) -> Optional[str]:
    if chain:
        return chain[0]
    if category in {"incomplete", "constraint_violation"}:
        expected_params = task.get("expected_params", {})
        if isinstance(expected_params, dict):
            return _normalize_optional_string(expected_params.get("target_tool"))
    return None


def _constraint_name_map() -> Dict[str, str]:
    return {
        name: str(item.get("type", "")).strip()
        for name, item in _load_cross_constraints().items()
    }


def _conflicting_param_map(conflicting_params: Sequence[Dict[str, Any]], known_params: Dict[str, Any]) -> Dict[str, Any]:
    values = dict(known_params)
    for item in conflicting_params:
        if not isinstance(item, dict):
            continue
        param = _normalize_optional_string(item.get("param"))
        if not param:
            continue
        values[param] = item.get("value")
    return values


def _constraint_rule_matches(expected_params: Dict[str, Any]) -> tuple[bool, List[str]]:
    issues: List[str] = []
    constraints = _load_cross_constraints()
    violated_constraints = expected_params.get("violated_constraints", [])
    known_params = expected_params.get("known_params", {})
    conflicting_values = _conflicting_param_map(expected_params.get("conflicting_params", []), known_params)

    for constraint_name in violated_constraints:
        constraint = constraints.get(constraint_name)
        if not constraint:
            continue

        param_a = _normalize_optional_string(constraint.get("param_a"))
        param_b = _normalize_optional_string(constraint.get("param_b"))
        constraint_type = _normalize_optional_string(constraint.get("type"))
        rules = constraint.get("rules", {}) or {}
        if not rules:
            issues.append(f"Constraint {constraint_name} has no configured rules to validate against.")
            continue

        value_a = conflicting_values.get(param_a)
        value_b = conflicting_values.get(param_b)
        if value_a is None or value_b is None:
            issues.append(f"Constraint {constraint_name} is missing explicit conflicting values for {param_a} and/or {param_b}.")
            continue

        rule = rules.get(str(value_a))
        if not isinstance(rule, dict):
            issues.append(f"Constraint {constraint_name} has no configured rule for {param_a}={value_a}.")
            continue

        if constraint_type == "blocked_combinations":
            blocked = {str(item) for item in rule.get("blocked", [])}
            if str(value_b) not in blocked:
                issues.append(
                    f"Constraint {constraint_name} does not block {param_a}={value_a} with {param_b}={value_b}."
                )
        elif constraint_type == "consistency_warning":
            inconsistent = {str(item) for item in rule.get("inconsistent", [])}
            if str(value_b) not in inconsistent:
                issues.append(
                    f"Constraint {constraint_name} does not warn on {param_a}={value_a} with {param_b}={value_b}."
                )

    return len(issues) == 0, issues


def _validate_task(
    *,
    category: str,
    task: Dict[str, Any],
    tool_contracts: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    critical_issues: List[str] = []
    review_issues: List[str] = []
    auto_fixes: List[str] = []

    chain = list(task["expected_tool_chain"])
    expected_tool = task["expected_tool"]
    expected_behavior = task["expected_behavior"]

    unknown_tools = [tool for tool in chain if tool not in tool_contracts]
    if expected_tool and expected_tool not in tool_contracts and chain:
        unknown_tools.append(expected_tool)
    if unknown_tools:
        critical_issues.append(f"Unknown tool(s): {sorted(set(unknown_tools))}")

    reference_tool = _reference_tool_for_review(category, chain, task)
    if task["has_file"] and not task["test_file"]:
        default_test_file = _select_default_test_file(category, chain, task["has_file"], target_tool=reference_tool)
        if default_test_file is None:
            critical_issues.append("has_file=true but no test_file could be assigned.")
        else:
            task["test_file"] = default_test_file
            auto_fixes.append(f"Assigned default test_file: {default_test_file}")

    if not task["has_file"]:
        task["test_file"] = None

    valid_params = set()
    required_params = set()
    reference_tools = list(chain)
    if reference_tool and reference_tool not in reference_tools:
        reference_tools.append(reference_tool)
    for tool_name in reference_tools:
        valid, required = _tool_param_context(tool_name, tool_contracts)
        valid_params.update(valid)
        required_params.update(required)

    if category == "incomplete":
        expected_params = task["expected_params"]
        known_params = expected_params.get("known_params", {})
        invalid_params = sorted(param_name for param_name in known_params if param_name not in valid_params) if valid_params else []
        if invalid_params:
            critical_issues.append(f"Invalid known_params for target tool {reference_tool}: {invalid_params}")
        if chain:
            review_issues.append("incomplete tasks should normally not execute tools before clarification.")
        if task["expected_tool"] is not None:
            review_issues.append("incomplete tasks should keep expected_tool=null until clarification is complete.")
        if not reference_tool:
            review_issues.append("Incomplete task should declare target_tool inside expected_params.")
        if not expected_params.get("missing_required_params"):
            review_issues.append("Incomplete task should list missing_required_params explicitly.")
        missing_required = set(expected_params.get("missing_required_params", []))
        if required_params and not missing_required.issubset(valid_params):
            review_issues.append("missing_required_params contains names that are not valid params for the target tool.")
        unresolved_required = required_params.difference(set(known_params.keys())).difference(missing_required)
        if required_params and unresolved_required:
            review_issues.append(f"Incomplete task does not account for all required params: {sorted(unresolved_required)}")
        negotiable = set(expected_params.get("negotiable_params", []))
        if not negotiable.issubset(valid_params):
            review_issues.append("negotiable_params contains names that are not valid params for the target tool.")
        if not (known_params or missing_required or negotiable):
            review_issues.append("Incomplete task must carry known_params and/or explicit missing/negotiable params.")
    elif category == "constraint_violation":
        expected_params = task["expected_params"]
        known_params = expected_params.get("known_params", {})
        invalid_params = sorted(param_name for param_name in known_params if param_name not in valid_params) if valid_params else []
        if invalid_params:
            critical_issues.append(f"Invalid known_params for constraint scenario: {invalid_params}")
        violated_constraints = expected_params.get("violated_constraints", [])
        constraint_types = _constraint_name_map()
        if not violated_constraints:
            review_issues.append("Constraint scenario should explicitly list violated_constraints.")
        unknown_constraints = sorted(name for name in violated_constraints if name not in constraint_types)
        if unknown_constraints:
            review_issues.append(f"violated_constraints are not backed by config/cross_constraints.yaml: {unknown_constraints}")
        if not expected_params.get("conflicting_params"):
            review_issues.append("Constraint scenario should explicitly list conflicting_params.")
        action = expected_params.get("expected_negotiation_or_rejection")
        if action is None:
            review_issues.append("Constraint scenario should declare expected_negotiation_or_rejection.")
        if not reference_tool:
            review_issues.append("Constraint scenario should declare target_tool or a runnable expected_tool_chain.")

        rules_match, rule_issues = _constraint_rule_matches(expected_params)
        if not rules_match:
            review_issues.extend(rule_issues)

        blocked_constraints = {name for name, ctype in constraint_types.items() if ctype == "blocked_combinations"}
        warning_constraints = {name for name, ctype in constraint_types.items() if ctype == "consistency_warning"}

        if action == "warn":
            if not chain:
                review_issues.append("Warning-only constraint cases should keep a runnable expected_tool_chain.")
            if any(name in blocked_constraints for name in violated_constraints):
                review_issues.append("Blocked-combination constraints should not be labeled as warn.")
        elif action in {"reject", "negotiate"}:
            if chain:
                review_issues.append("Reject/negotiate constraint cases should not have executable expected_tool_chain.")
            if action == "reject" and any(name in warning_constraints for name in violated_constraints):
                review_issues.append("Consistency-warning constraints should usually be labeled warn, not reject.")
        else:
            if violated_constraints:
                review_issues.append("Constraint scenario action is missing or unsupported.")
    else:
        valid_params = set()
        for tool_name in chain:
            valid_params.update(((tool_contracts.get(tool_name) or {}).get("parameters", {}) or {}).keys())

        invalid_params = sorted(param_name for param_name in task["expected_params"] if param_name not in valid_params)
        if invalid_params and chain:
            critical_issues.append(f"Invalid params for tool chain {chain}: {invalid_params}")
        elif invalid_params and not chain:
            critical_issues.append(f"Expected params present without executable tool chain: {invalid_params}")

    lowered_behavior = expected_behavior.lower()
    if category == "simple":
        if len(chain) != 1:
            review_issues.append("Simple tasks should have exactly one tool in expected_tool_chain.")
        if any(token in lowered_behavior for token in ("澄清", "clarify", "约束", "block", "警告", "warning")):
            review_issues.append("Simple task behavior looks inconsistent with direct execution.")
    elif category == "parameter_ambiguous":
        if len(chain) != 1:
            review_issues.append("parameter_ambiguous tasks should have exactly one tool in expected_tool_chain.")
        if not task["expected_params"]:
            review_issues.append("parameter_ambiguous task should usually declare normalized expected_params.")
    elif category == "multi_step":
        if len(chain) < 2:
            review_issues.append("multi_step tasks should contain at least two tools in expected_tool_chain.")
    elif category == "incomplete":
        if not any(keyword.lower() in lowered_behavior for keyword in REVIEW_KEYWORDS["incomplete"]):
            review_issues.append("Incomplete task behavior should mention clarification or补全.")
    elif category == "constraint_violation":
        action = task["expected_params"].get("expected_negotiation_or_rejection")
        if action == "warn":
            if not any(keyword in lowered_behavior for keyword in ("warning", "警告", "warn")):
                review_issues.append("Constraint warning cases should mention warning semantics in expected_behavior.")
        elif action == "negotiate":
            if not any(keyword in lowered_behavior for keyword in ("澄清", "协商", "clarify", "negotiate", "询问")):
                review_issues.append("Negotiated constraint cases should mention clarification in expected_behavior.")
        else:
            if not any(keyword in lowered_behavior for keyword in ("拦截", "阻止", "拒绝", "block", "reject", "约束")):
                review_issues.append("Rejected constraint cases should mention rejection/block semantics in expected_behavior.")

    if category in {"simple", "parameter_ambiguous", "multi_step"} and not chain:
        critical_issues.append("Executable task is missing expected_tool_chain.")
    if category in {"simple", "parameter_ambiguous", "multi_step"} and not task["expected_params"]:
        review_issues.append("expected_params is empty and must be reviewed before merge.")

    success_criteria = _derive_success_criteria(category, expected_behavior, task["expected_params"])
    status = "invalid" if critical_issues else "needs_review" if review_issues else "valid"
    validation = {
        "status": status,
        "issues": critical_issues + review_issues,
        "auto_fixes": auto_fixes,
        "expected_behavior": expected_behavior,
        "notes": task["notes"],
    }

    record: Dict[str, Any] = {
        "category": category,
        "description": task["description"],
        "user_message": task["user_message"],
        "has_file": task["has_file"],
        "test_file": task["test_file"],
        "expected_tool_chain": chain,
        "expected_params": task["expected_params"],
        "success_criteria": success_criteria,
        "validation": validation,
    }
    if expected_tool:
        record["expected_tool"] = expected_tool
    return record, validation


def _build_record_id(category: str, index: int) -> str:
    return f"e2e_{CATEGORY_ID_PREFIX[category]}_gen_{index:03d}"


def _compute_status_counts(records: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"valid": 0, "needs_review": 0, "invalid": 0}
    for record in records:
        status = str((record.get("validation") or {}).get("status", "needs_review"))
        if status in counts:
            counts[status] += 1
    return counts


def _aggregate_category_statuses(categories: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    totals = {"valid": 0, "needs_review": 0, "invalid": 0}
    for entry in categories.values():
        status_counts = entry.get("status_counts", {})
        if not status_counts:
            status_counts = {status: int(entry.get(status, 0)) for status in totals}
        for status in totals:
            totals[status] += int(status_counts.get(status, 0))
    return totals


def _normalize_category_entries(summary: Dict[str, Any]) -> None:
    for entry in (summary.get("categories", {}) or {}).values():
        if "status_counts" not in entry:
            entry["status_counts"] = {status: int(entry.get(status, 0)) for status in ("valid", "needs_review", "invalid")}


def _load_summary() -> Dict[str, Any]:
    if not SUMMARY_PATH.exists():
        return {"generated_at": None, "model": None, "categories": {}}
    with SUMMARY_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _save_summary(summary: Dict[str, Any]) -> None:
    summary["generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    _normalize_category_entries(summary)
    summary["status_totals"] = _aggregate_category_statuses(summary.get("categories", {}))
    write_json(SUMMARY_PATH, summary)


def _resolve_count(category: str, count_override: Optional[int]) -> int:
    if count_override is not None:
        return count_override
    return DEFAULT_COUNT_BY_CATEGORY[category]


def _load_all_existing_generated_tasks() -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for category in CATEGORY_DESCRIPTIONS:
        path = GENERATED_DIR / f"e2e_tasks_{category}.jsonl"
        if path.exists():
            records.extend(load_jsonl_records(path))
    return records


def generate_for_category(
    *,
    category: str,
    count: int,
    generator: LLMGenerator,
    max_rounds: int,
    tool_contracts: Dict[str, Any],
    replace_existing: bool = False,
) -> Dict[str, int]:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    benchmark_tasks = load_existing_end2end_tasks(BENCHMARK_PATH)
    existing_generated_records = [] if replace_existing else _load_existing_generated_records(category)
    all_existing_tasks = benchmark_tasks + _load_all_existing_generated_tasks()
    if replace_existing:
        all_existing_tasks = [task for task in all_existing_tasks if task.get("category") != category]
    prompt_history = [task for task in all_existing_tasks if isinstance(task, dict)]

    output_path = GENERATED_DIR / f"e2e_tasks_{category}.jsonl"
    seen_messages = {
        _normalize_message(record.get("user_message", ""))
        for record in prompt_history
        if _normalize_message(record.get("user_message", ""))
    }
    attempted_messages = set(seen_messages)
    next_index = max((_parse_id_suffix(record.get("id", "")) for record in existing_generated_records), default=0) + 1

    newly_generated: List[Dict[str, Any]] = []
    new_invalid_count = 0
    round_index = 0

    while len(newly_generated) < count and round_index < max_rounds:
        remaining = count - len(newly_generated)
        request_count = min(max(remaining * 2, 4), 24)
        system_prompt, user_prompt = _build_prompt(
            category=category,
            count=request_count,
            existing_tasks=prompt_history + existing_generated_records + newly_generated,
        )
        round_index += 1

        try:
            payload = generator.generate_json(system_prompt, user_prompt)
        except Exception as exc:
            logger.warning("Generation failed for %s round %s: %s", category, round_index, exc)
            payload = None

        if not payload:
            continue

        raw_tasks = payload.get("tasks", [])
        if not isinstance(raw_tasks, list):
            logger.warning("Category %s returned a non-list tasks payload.", category)
            continue

        for raw_task in raw_tasks:
            if not isinstance(raw_task, dict):
                continue

            normalized_task = _normalize_task_payload(category, raw_task)
            if normalized_task is None:
                continue

            message_key = _normalize_message(normalized_task["user_message"])
            if not message_key or message_key in attempted_messages:
                continue
            attempted_messages.add(message_key)

            record, validation = _validate_task(
                category=category,
                task=normalized_task,
                tool_contracts=tool_contracts,
            )
            if validation["status"] == "invalid":
                new_invalid_count += 1
                continue

            record["id"] = _build_record_id(category, next_index)
            next_index += 1
            newly_generated.append(record)
            prompt_history.append(record)
            seen_messages.add(message_key)

            if len(newly_generated) >= count:
                break

    combined_records = existing_generated_records + newly_generated
    write_jsonl(output_path, combined_records)

    summary = _load_summary()
    existing_invalid = 0 if replace_existing else int((summary.get("categories", {}) or {}).get(category, {}).get("invalid", 0))
    file_counts = _compute_status_counts(combined_records)
    category_summary = {
        "requested_count": count,
        "total_generated": len(combined_records),
        "status_counts": {
            "valid": file_counts["valid"],
            "needs_review": file_counts["needs_review"],
            "invalid": existing_invalid + new_invalid_count,
        },
        "valid": file_counts["valid"],
        "needs_review": file_counts["needs_review"],
        "invalid": existing_invalid + new_invalid_count,
        "last_run": {
            "new_usable": len(newly_generated),
            "new_invalid": new_invalid_count,
        },
    }
    summary["model"] = generator.model
    summary.setdefault("categories", {})[category] = category_summary
    _save_summary(summary)

    logger.info(
        "Category %s generated %s new usable tasks (%s invalid discarded).",
        category,
        len(newly_generated),
        new_invalid_count,
    )
    return category_summary


def main() -> None:
    args = parse_args()
    if args.generate_all == bool(args.category):
        raise SystemExit("Use exactly one of --all or --category.")
    if args.count is not None and args.count <= 0:
        raise SystemExit("--count must be > 0.")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    generator = LLMGenerator(model=args.model, temperature=args.temperature, call_interval=1.0)
    tool_contracts = extract_tool_contracts()
    categories = list(CATEGORY_DESCRIPTIONS) if args.generate_all else [str(args.category)]

    results: Dict[str, Dict[str, int]] = {}
    for category in categories:
        category_count = _resolve_count(category, args.count)
        results[category] = generate_for_category(
            category=category,
            count=category_count,
            generator=generator,
            max_rounds=args.max_rounds,
            tool_contracts=tool_contracts,
            replace_existing=args.replace_existing,
        )

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
