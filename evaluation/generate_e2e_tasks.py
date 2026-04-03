"""Generate LLM-authored end-to-end evaluation tasks."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence


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
    "incomplete": ("澄清", "补充", "协商", "clarify", "follow-up", "补全", "询问"),
    "constraint_violation": ("拦截", "约束", "阻止", "block", "warning", "警告", "constraint"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate end-to-end task candidates with Qwen.")
    parser.add_argument("--category", choices=tuple(CATEGORY_DESCRIPTIONS))
    parser.add_argument("--all", action="store_true", dest="generate_all")
    parser.add_argument("--count", type=int, default=None, help="Override generation count. If omitted, uses default per category.")
    parser.add_argument("--model", default=None, help="Model override. Precedence is CLI > env > default.")
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--max-rounds", type=int, default=6)
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


def _build_prompt(*, category: str, count: int, existing_tasks: Sequence[Dict[str, Any]]) -> tuple[str, str]:
    system_prompt = E2E_SYSTEM_PROMPT.format(system_capabilities=extract_system_capabilities())
    user_prompt = E2E_USER_PROMPT_TEMPLATE.format(
        category=category,
        count=count,
        category_description=CATEGORY_DESCRIPTIONS[category],
        coverage_requirements=json.dumps(E2E_COVERAGE_REQUIREMENTS, ensure_ascii=False, indent=2),
        existing_tasks=_existing_task_prompt_view(existing_tasks),
    )
    return system_prompt, user_prompt


def _select_default_test_file(category: str, tool_chain: Sequence[str], has_file: bool) -> Optional[str]:
    if not has_file:
        return None

    for tool_name in tool_chain:
        if tool_name in SAMPLE_TEST_FILES_BY_TOOL:
            return SAMPLE_TEST_FILES_BY_TOOL[tool_name]

    if any(tool_name in {"calculate_dispersion", "analyze_hotspots", "render_spatial_map", "compare_scenarios"} for tool_name in tool_chain):
        return "evaluation/file_tasks/data/macro_direct.csv"
    if category in {"multi_step", "constraint_violation"}:
        return "evaluation/file_tasks/data/macro_direct.csv"
    return None


def _derive_success_criteria(category: str, expected_behavior: str) -> Dict[str, Any]:
    behavior = expected_behavior.lower()
    if category == "incomplete":
        return {"tool_executed": False, "requires_user_response": True, "result_has_data": False}
    if category == "constraint_violation":
        if any(keyword in behavior for keyword in ("warning", "警告", "warn")):
            return {"tool_executed": True, "params_legal": True, "constraint_warning": True, "result_has_data": True}
        return {"tool_executed": False, "constraint_blocked": True, "result_has_data": False}
    return {"tool_executed": True, "params_legal": True, "result_has_data": True}


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

    if task["has_file"] and not task["test_file"]:
        default_test_file = _select_default_test_file(category, chain, task["has_file"])
        if default_test_file is None:
            critical_issues.append("has_file=true but no test_file could be assigned.")
        else:
            task["test_file"] = default_test_file
            auto_fixes.append(f"Assigned default test_file: {default_test_file}")

    if not task["has_file"]:
        task["test_file"] = None

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
        if chain:
            review_issues.append("incomplete tasks should normally not execute tools before clarification.")
        if not any(keyword.lower() in lowered_behavior for keyword in REVIEW_KEYWORDS["incomplete"]):
            review_issues.append("Incomplete task behavior should mention clarification or补全.")
    elif category == "constraint_violation":
        if not any(keyword.lower() in lowered_behavior for keyword in REVIEW_KEYWORDS["constraint_violation"]):
            review_issues.append("Constraint task behavior should mention interception, constraint, or warning.")
        warning_like = any(keyword in lowered_behavior for keyword in ("warning", "警告", "warn"))
        if warning_like and not chain:
            review_issues.append("Constraint warning cases should normally still have an executable tool chain.")
        if not warning_like and chain:
            review_issues.append("Blocked constraint cases should usually have an empty tool chain.")

    if category in {"simple", "parameter_ambiguous", "multi_step"} and not chain:
        critical_issues.append("Executable task is missing expected_tool_chain.")
    if not task["expected_params"]:
        review_issues.append("expected_params is empty and must be reviewed before merge.")

    success_criteria = _derive_success_criteria(category, expected_behavior)
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
) -> Dict[str, int]:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    benchmark_tasks = load_existing_end2end_tasks(BENCHMARK_PATH)
    existing_generated_records = _load_existing_generated_records(category)
    all_existing_tasks = benchmark_tasks + _load_all_existing_generated_tasks()
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
    existing_invalid = int((summary.get("categories", {}) or {}).get(category, {}).get("invalid", 0))
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
        )

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
