"""Targeted end-to-end benchmark candidate generation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.context_extractor import extract_system_capabilities
from evaluation.llm_generator import LLMGenerator
from evaluation.pipeline_v2.common import (
    DEFAULT_BENCHMARK_PATH,
    DEFAULT_TEST_FILE_BY_TOOL,
    GEOMETRY_REQUIRED_TOOLS,
    VALID_CATEGORIES,
    build_success_criteria,
    get_tool_chain,
    load_jsonl_records,
    save_jsonl,
)


TARGETED_GENERATION_SYSTEM_PROMPT = """你是交通排放分析系统的测试工程师。

你的任务是根据覆盖率缺口生成端到端 benchmark 候选任务。候选任务必须可被现有 evaluation/eval_end2end.py 读取。

系统能力摘要：
{system_capabilities}

硬性规则：
1. user_message 必须自然口语化，像真人在对话框里打字。
2. 必须覆盖指定 gap 中的标准参数值。
3. 车型在 user_message 中必须优先使用中文口语别名，不要直接写 MOVES 标准英文名。
4. expected_params 中的车型必须是 MOVES 标准名，污染物/季节/道路/气象必须是系统标准值。
5. constraint_violation 只能使用 config/cross_constraints.yaml 中真实存在的规则，不要发明新约束。
6. 不要与已有任务重复或只做同义改写。
7. 严格输出 JSON 对象，不要附加解释。"""


TARGETED_GENERATION_USER_PROMPT = """当前 benchmark 覆盖率审计发现以下缺口：

{gap_description}

本缺口建议类别：{suggested_category}
建议消息模板：{suggested_template}
请生成 {count} 条候选任务。

如果缺口是 vehicle_type 或 pollutant：
- 至少一条 simple，至少一条 parameter_ambiguous（当 count>=2 时）。

如果缺口是 cross_constraints：
- category 必须是 constraint_violation。
- expected_params 应包含触发规则所需的标准参数值。
- candidate_metadata.violated_constraints 必须列出真实 constraint name。
- candidate_metadata.expected_constraint_action 必须是 reject、warn 或 negotiate。

如果缺口是 tool_chain_combo：
- expected_tool_chain 必须严格覆盖该工具链顺序。

已有任务（不要重复）：
{existing_messages}

输出格式（严格 JSON 对象）：
{{
  "tasks": [
    {{
      "category": "simple|parameter_ambiguous|multi_step|incomplete|constraint_violation",
      "description": "简要说明测试能力",
      "user_message": "用户实际输入",
      "has_file": true,
      "test_file": "相对仓库路径或 null",
      "expected_tool": "单步工具名或 null",
      "expected_tool_chain": ["按执行顺序列出工具"],
      "expected_params": {{"参数名": "标准值或标准值数组"}},
      "success_criteria": {{"tool_executed": true, "params_legal": true, "result_has_data": true}},
      "candidate_metadata": {{
        "violated_constraints": [],
        "expected_constraint_action": null,
        "target_gap": "{target_gap}"
      }}
    }}
  ]
}}"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate targeted benchmark candidates from gap_report.json.")
    parser.add_argument("--gaps", type=Path, required=True)
    parser.add_argument("--existing", type=Path, default=DEFAULT_BENCHMARK_PATH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count-per-gap", type=int, default=2)
    parser.add_argument("--limit-targets", type=int, default=None)
    parser.add_argument("--model", default="qwen3-max")
    parser.add_argument("--temperature", type=float, default=0.8)
    return parser.parse_args()


def _priority_rank(priority: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2}.get(str(priority), 9)


def _existing_message_block(records: Sequence[Dict[str, Any]], limit: int = 80) -> str:
    messages = []
    for record in records:
        message = str(record.get("user_message") or "").strip()
        if message:
            messages.append(f"- {message}")
    return "\n".join(messages[-limit:]) if messages else "- (none)"


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    return [str(item).strip() for item in value if str(item).strip()]


def _default_test_file(chain: Sequence[str]) -> Optional[str]:
    if any(tool in GEOMETRY_REQUIRED_TOOLS for tool in chain):
        return "test_data/test_6links.xlsx"
    for tool in chain:
        default_file = DEFAULT_TEST_FILE_BY_TOOL.get(tool)
        if default_file:
            return default_file
    return None


def _normalize_candidate(raw: Dict[str, Any], *, candidate_id: str, target: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    category = str(raw.get("category") or target.get("suggested_category") or "").strip()
    if category not in VALID_CATEGORIES:
        category = str(target.get("suggested_category") or "simple")
    if category not in VALID_CATEGORIES:
        return None

    user_message = str(raw.get("user_message") or "").strip()
    description = str(raw.get("description") or "").strip()
    if not user_message or not description:
        return None

    chain = _string_list(raw.get("expected_tool_chain"))
    expected_tool = raw.get("expected_tool")
    if expected_tool is None and len(chain) == 1:
        expected_tool = chain[0]
    expected_tool = str(expected_tool).strip() if expected_tool else None

    has_file = _bool_value(raw.get("has_file"))
    test_file = raw.get("test_file")
    test_file = str(test_file).strip() if test_file else None
    if test_file:
        has_file = True
    if has_file and not test_file:
        test_file = _default_test_file(chain)

    expected_params = raw.get("expected_params") if isinstance(raw.get("expected_params"), dict) else {}
    candidate = {
        "id": candidate_id,
        "category": category,
        "description": description,
        "user_message": user_message,
        "has_file": has_file,
        "test_file": test_file,
        "expected_tool": expected_tool,
        "expected_tool_chain": chain,
        "expected_params": dict(expected_params),
        "success_criteria": raw.get("success_criteria") if isinstance(raw.get("success_criteria"), dict) else {},
        "candidate_metadata": {
            "target": target,
            **(raw.get("candidate_metadata") if isinstance(raw.get("candidate_metadata"), dict) else {}),
        },
    }
    candidate["success_criteria"] = build_success_criteria(candidate)
    return candidate


def _build_prompt(target: Dict[str, Any], existing_records: Sequence[Dict[str, Any]], count: int) -> tuple[str, str]:
    system_prompt = TARGETED_GENERATION_SYSTEM_PROMPT.format(
        system_capabilities=extract_system_capabilities()
    )
    user_prompt = TARGETED_GENERATION_USER_PROMPT.format(
        gap_description=json.dumps(target, ensure_ascii=False, indent=2),
        suggested_category=target.get("suggested_category", ""),
        suggested_template=target.get("suggested_message_template", ""),
        count=count,
        existing_messages=_existing_message_block(existing_records),
        target_gap=str(target.get("gap") or ""),
    )
    return system_prompt, user_prompt


def generate_candidates(
    *,
    gaps_path: Path,
    existing_path: Path,
    output_path: Path,
    count_per_gap: int,
    limit_targets: Optional[int],
    model: str,
    temperature: float,
) -> List[Dict[str, Any]]:
    gap_report = json.loads(gaps_path.read_text(encoding="utf-8"))
    targets = sorted(gap_report.get("generation_targets", []) or [], key=lambda item: (_priority_rank(item.get("priority")), str(item.get("dimension")), str(item.get("gap"))))
    if limit_targets is not None:
        targets = targets[:limit_targets]

    existing_records = load_jsonl_records(existing_path)
    generator = LLMGenerator(model=model, temperature=temperature, call_interval=1.0)
    candidates: List[Dict[str, Any]] = []
    candidate_index = 1

    for target in targets:
        system_prompt, user_prompt = _build_prompt(target, existing_records + candidates, count_per_gap)
        payload = generator.generate_json(system_prompt, user_prompt, temperature=temperature)
        raw_tasks = payload.get("tasks", []) if isinstance(payload, dict) else []
        if not isinstance(raw_tasks, list):
            continue
        for raw_task in raw_tasks:
            if not isinstance(raw_task, dict):
                continue
            candidate = _normalize_candidate(
                raw_task,
                candidate_id=f"candidate_{candidate_index:04d}",
                target=target,
            )
            if candidate is None:
                continue
            message = candidate["user_message"]
            if any(message == str(item.get("user_message") or "") for item in existing_records + candidates):
                continue
            candidates.append(candidate)
            candidate_index += 1

    save_jsonl(output_path, candidates)
    return candidates


def main() -> None:
    args = parse_args()
    if args.count_per_gap <= 0:
        raise SystemExit("--count-per-gap must be > 0.")
    candidates = generate_candidates(
        gaps_path=args.gaps,
        existing_path=args.existing,
        output_path=args.output,
        count_per_gap=args.count_per_gap,
        limit_targets=args.limit_targets,
        model=args.model,
        temperature=args.temperature,
    )
    print(json.dumps({"generated": len(candidates), "output": str(args.output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
