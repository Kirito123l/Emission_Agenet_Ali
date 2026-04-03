"""Generate LLM-authored hard cases for parameter standardization benchmarks."""
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

from config import get_config, reset_config
from evaluation.context_extractor import (
    STANDARDIZATION_DIMENSIONS,
    extract_standardization_context,
    load_existing_cases,
    load_jsonl_records,
)
from evaluation.llm_generator import LLMGenerator
from evaluation.utils import write_json, write_jsonl
from services.standardization_engine import StandardizationEngine
from services.standardizer import StandardizationResult, reset_standardizer


logger = logging.getLogger(__name__)

BENCHMARK_PATH = PROJECT_ROOT / "evaluation" / "benchmarks" / "standardization_benchmark.jsonl"
GENERATED_DIR = PROJECT_ROOT / "evaluation" / "generated"
SUMMARY_PATH = GENERATED_DIR / "hard_cases_summary.json"

VALID_STATUSES = ("confirmed_correct", "confirmed_abstain", "needs_review", "invalid")
DEFAULT_COUNT_BY_DIMENSION = {
    "vehicle_type": 30,
    "pollutant": 30,
    "season": 20,
    "road_type": 25,
    "meteorology": 25,
    "stability_class": 20,
}

SYSTEM_PROMPT = """你是一个交通环境分析领域的测试数据生成专家。你的任务是为“参数标准化”模块生成高难度的测试用例。

参数标准化模块的作用：将用户的口语化、非标准化的参数表达映射到后端系统认可的标准参数值。

你需要生成两类测试用例：
1. “应该成功映射”的用例：用户用非标准方式表达，但系统应该能识别出对应的标准值
2. “应该拒绝/放弃”的用例：用户的输入存在歧义、超出范围或无法确定对应的标准值，系统应该放弃映射并请求用户澄清

生成规则：
- 每条用例必须是一个 JSON 对象
- 必须显式覆盖这些高难点：中英混杂、缩写别名、口语化、多义歧义、abstain-worthy、cross-constraint-risk
- 也可以补充：方言/地方用语、行业术语/俚语、拼写错误、超出范围表达
- 不要重复已有的别名，也不要重复已有测试用例
- “应该成功映射”和“应该拒绝”的比例大约 6:4
- notes 要说明为什么这个用例难
- expected_output 必须是我提供的标准值之一，或者为 null
- language 只能填 zh、en、mixed
- category 优先使用以下标签之一：中英混杂、缩写别名、口语化、多义歧义、abstain-worthy、cross-constraint-risk、方言、行业术语、拼写错误、超范围
- 只输出 JSON，不要附加解释"""

USER_PROMPT_TEMPLATE = """当前维度：{dimension}

标准值列表（系统只接受这些值）：
{standard_names}

每个标准值已有的别名（这些别名已经能被系统识别，不要重复生成）：
{existing_aliases}

已有的测试用例（不要重复）：
{existing_cases}

请生成 {count} 条高难度测试用例。

本轮必须尽量覆盖以下测试面：
{coverage_requirements}

关于 cross-constraint-risk 的提醒：
{cross_constraint_hint}

输出格式（严格 JSON 对象）：
{{
  "cases": [
    {{
      "raw_input": "用户可能的输入",
      "expected_output": "对应的标准值（如果应该拒绝则为 null）",
      "language": "zh/en/mixed",
      "notes": "说明为什么这个用例是难的",
      "category": "中英混杂/缩写别名/口语化/多义歧义/abstain-worthy/cross-constraint-risk/方言/行业术语/拼写错误/超范围"
    }}
  ]
}}"""

HARD_CASE_COVERAGE_REQUIREMENTS = [
    "中英混杂: 如中文标准词夹带英文简称或英文车型名。",
    "缩写别名: 如英文缩写、拼写压缩或行业缩略称呼。",
    "口语化: 如非正式说法、通俗叫法、民间表达。",
    "多义歧义: 如同一表达可能指向多个标准值，需要谨慎或拒绝。",
    "abstain-worthy: 无法安全映射、超出范围、信息不足时应返回 null。",
    "cross-constraint-risk: 单值本身可标准化，但在后续与其他参数组合时容易触发约束或 warning 风险。",
]

CROSS_CONSTRAINT_HINTS = {
    "vehicle_type": "例如“摩托”“公交”“大巴”这类表达即使能标准化，也可能与 road_type 组合后触发兼容性风险。",
    "pollutant": "例如看似合理但在某些工具或任务链里不一定适用的污染物表达，可作为 downstream 风险提示。",
    "season": "例如冬季/夏季表达在与 meteorology 预设组合时可能触发 consistency warning。",
    "road_type": "例如高速/expressway/motorway 这类表达在与部分 vehicle_type 组合时可能触发 blocked combination。",
    "meteorology": "例如 urban_summer_day / urban_winter_day 这类预设在与 season 组合时可能触发 consistency warning。",
    "stability_class": "例如边界性稳定度表达虽然可尝试标准化，但在扩散任务中可能放大 downstream 风险。",
}


def build_engine() -> StandardizationEngine:
    reset_config()
    reset_standardizer()
    runtime_config = get_config()
    return StandardizationEngine(dict(runtime_config.standardization_config))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate hard standardization benchmark candidates with Qwen.")
    parser.add_argument("--dimension", choices=STANDARDIZATION_DIMENSIONS)
    parser.add_argument("--all", action="store_true", dest="generate_all")
    parser.add_argument("--count", type=int, default=None, help="Override generation count. If omitted, uses formal default per dimension.")
    parser.add_argument("--model", default=None, help="Model override. Precedence is CLI > env > default.")
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--max-rounds", type=int, default=6)
    return parser.parse_args()


def _normalize_key(value: str) -> str:
    return str(value).strip()


def _parse_id_suffix(raw_id: str) -> int:
    tail = str(raw_id).rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _infer_language(text: str) -> str:
    has_zh = any("\u4e00" <= char <= "\u9fff" for char in text)
    has_en = any(char.isascii() and char.isalpha() for char in text)
    if has_zh and has_en:
        return "mixed"
    if has_zh:
        return "zh"
    return "en"


def _normalize_expected_output(value: Any) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned or cleaned.lower() in {"null", "none", "nil"}:
        return None
    return cleaned


def _summarize_for_prompt(records: Sequence[Dict[str, Any]], limit: int = 120) -> str:
    simplified = [
        {
            "raw_input": str(record.get("raw_input", "")).strip(),
            "expected_output": record.get("expected_output"),
        }
        for record in records
        if str(record.get("raw_input", "")).strip()
    ]
    return json.dumps(simplified[:limit], ensure_ascii=False, indent=2)


def _load_existing_generated_records(dimension: str) -> List[Dict[str, Any]]:
    path = GENERATED_DIR / f"hard_cases_{dimension}.jsonl"
    return load_jsonl_records(path)


def _build_prompt(
    *,
    dimension: str,
    context: Dict[str, Any],
    existing_cases: Sequence[Dict[str, Any]],
    count: int,
) -> str:
    return USER_PROMPT_TEMPLATE.format(
        dimension=dimension,
        standard_names=json.dumps(context["standard_names"], ensure_ascii=False, indent=2),
        existing_aliases=json.dumps(context["aliases_by_standard"], ensure_ascii=False, indent=2),
        existing_cases=_summarize_for_prompt(existing_cases),
        count=count,
        coverage_requirements=json.dumps(HARD_CASE_COVERAGE_REQUIREMENTS, ensure_ascii=False, indent=2),
        cross_constraint_hint=CROSS_CONSTRAINT_HINTS.get(dimension, "生成一些即使能标准化，也会在后续参数组合中带来约束风险的表达。"),
    )


def _normalize_case(raw_case: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    raw_input = str(raw_case.get("raw_input", "")).strip()
    if not raw_input:
        return None

    language = str(raw_case.get("language", "")).strip().lower()
    if language not in {"zh", "en", "mixed"}:
        language = _infer_language(raw_input)

    notes = str(raw_case.get("notes", "")).strip() or "LLM-generated hard case"
    category = str(raw_case.get("category", "")).strip() or "其他"
    expected_output = _normalize_expected_output(raw_case.get("expected_output"))

    return {
        "raw_input": raw_input,
        "expected_output": expected_output,
        "language": language,
        "notes": notes,
        "category": category,
    }


def _validate_case(
    *,
    dimension: str,
    case: Dict[str, Any],
    standard_names: Sequence[str],
    engine: StandardizationEngine,
) -> Dict[str, Any]:
    expected_output = case["expected_output"]
    if expected_output is not None and expected_output not in set(standard_names):
        return {
            "status": "invalid",
            "actual_output": None,
            "actual_strategy": "not_run",
            "actual_confidence": 0.0,
        }

    result: StandardizationResult = engine.standardize(dimension, case["raw_input"])
    actual_output = result.normalized
    actual_strategy = result.strategy
    actual_confidence = float(result.confidence or 0.0)
    abstained = (not result.success) or actual_strategy in {"abstain", "none"}

    if expected_output is None:
        status = "confirmed_abstain" if abstained or actual_output is None else "needs_review"
    else:
        status = "confirmed_correct" if actual_output == expected_output else "needs_review"

    return {
        "status": status,
        "actual_output": actual_output,
        "actual_strategy": actual_strategy,
        "actual_confidence": actual_confidence,
    }


def _build_record(
    *,
    dimension: str,
    case: Dict[str, Any],
    validation: Dict[str, Any],
    generated_index: int,
) -> Dict[str, Any]:
    return {
        "id": f"{dimension}_hard_gen_{generated_index:03d}",
        "dimension": dimension,
        "difficulty": "hard",
        "raw_input": case["raw_input"],
        "expected_output": case["expected_output"],
        "language": case["language"],
        "notes": case["notes"],
        "category": case["category"],
        "validation": validation,
    }


def _compute_file_counts(records: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts = {status: 0 for status in VALID_STATUSES}
    for record in records:
        status = str((record.get("validation") or {}).get("status", "needs_review"))
        if status in counts:
            counts[status] += 1
    return counts


def _aggregate_dimension_statuses(dimensions: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    totals = {status: 0 for status in VALID_STATUSES}
    for entry in dimensions.values():
        status_counts = entry.get("status_counts", {})
        if not status_counts:
            status_counts = {status: int(entry.get(status, 0)) for status in VALID_STATUSES}
        for status in VALID_STATUSES:
            totals[status] += int(status_counts.get(status, 0))
    return totals


def _normalize_dimension_entries(summary: Dict[str, Any]) -> None:
    for entry in (summary.get("dimensions", {}) or {}).values():
        if "status_counts" not in entry:
            entry["status_counts"] = {status: int(entry.get(status, 0)) for status in VALID_STATUSES}


def _load_summary() -> Dict[str, Any]:
    if not SUMMARY_PATH.exists():
        return {"generated_at": None, "model": None, "dimensions": {}}
    with SUMMARY_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _save_summary(summary: Dict[str, Any]) -> None:
    summary["generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    _normalize_dimension_entries(summary)
    summary["status_totals"] = _aggregate_dimension_statuses(summary.get("dimensions", {}))
    write_json(SUMMARY_PATH, summary)


def _resolve_count(dimension: str, count_override: Optional[int]) -> int:
    if count_override is not None:
        return count_override
    return DEFAULT_COUNT_BY_DIMENSION[dimension]


def generate_for_dimension(
    *,
    dimension: str,
    count: int,
    generator: LLMGenerator,
    max_rounds: int,
) -> Dict[str, int]:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    context = extract_standardization_context(dimension)
    benchmark_records = load_existing_cases(BENCHMARK_PATH, dimension=dimension)
    existing_generated_records = _load_existing_generated_records(dimension)
    output_path = GENERATED_DIR / f"hard_cases_{dimension}.jsonl"
    engine = build_engine()

    prompt_history = benchmark_records + existing_generated_records
    reserved_inputs = {
        _normalize_key(str(record.get("raw_input", "")))
        for record in prompt_history
        if _normalize_key(str(record.get("raw_input", "")))
    }
    attempted_inputs = set(reserved_inputs)

    next_index = max((_parse_id_suffix(record.get("id", "")) for record in existing_generated_records), default=0) + 1
    newly_generated: List[Dict[str, Any]] = []
    new_invalid_count = 0
    round_index = 0

    while len(newly_generated) < count and round_index < max_rounds:
        remaining = count - len(newly_generated)
        request_count = min(max(remaining * 2, 6), 40)
        prompt = _build_prompt(
            dimension=dimension,
            context=context,
            existing_cases=prompt_history + newly_generated,
            count=request_count,
        )
        round_index += 1

        try:
            payload = generator.generate_json(SYSTEM_PROMPT, prompt)
        except Exception as exc:
            logger.warning("Generation failed for %s round %s: %s", dimension, round_index, exc)
            payload = None

        if not payload:
            continue

        raw_cases = payload.get("cases", [])
        if not isinstance(raw_cases, list):
            logger.warning("Dimension %s returned a non-list cases payload.", dimension)
            continue

        for raw_case in raw_cases:
            if not isinstance(raw_case, dict):
                continue

            case = _normalize_case(raw_case)
            if case is None:
                continue

            dedupe_key = _normalize_key(case["raw_input"])
            if not dedupe_key or dedupe_key in attempted_inputs:
                continue
            attempted_inputs.add(dedupe_key)

            validation = _validate_case(
                dimension=dimension,
                case=case,
                standard_names=context["standard_names"],
                engine=engine,
            )

            if validation["status"] == "invalid":
                new_invalid_count += 1
                continue

            record = _build_record(
                dimension=dimension,
                case=case,
                validation=validation,
                generated_index=next_index,
            )
            newly_generated.append(record)
            prompt_history.append(record)
            reserved_inputs.add(dedupe_key)
            next_index += 1

            if len(newly_generated) >= count:
                break

    combined_records = existing_generated_records + newly_generated
    write_jsonl(output_path, combined_records)

    summary = _load_summary()
    existing_invalid = int((summary.get("dimensions", {}) or {}).get(dimension, {}).get("invalid", 0))
    file_counts = _compute_file_counts(combined_records)
    dimension_summary = {
        "requested_count": count,
        "total_generated": len(combined_records),
        "status_counts": {
            "confirmed_correct": file_counts["confirmed_correct"],
            "confirmed_abstain": file_counts["confirmed_abstain"],
            "needs_review": file_counts["needs_review"],
            "invalid": existing_invalid + new_invalid_count,
        },
        "confirmed_correct": file_counts["confirmed_correct"],
        "confirmed_abstain": file_counts["confirmed_abstain"],
        "needs_review": file_counts["needs_review"],
        "invalid": existing_invalid + new_invalid_count,
        "last_run": {
            "new_usable": len(newly_generated),
            "new_invalid": new_invalid_count,
        },
    }
    summary["model"] = generator.model
    summary.setdefault("dimensions", {})[dimension] = dimension_summary
    _save_summary(summary)

    logger.info(
        "Dimension %s generated %s new usable cases (%s invalid discarded).",
        dimension,
        len(newly_generated),
        new_invalid_count,
    )
    return dimension_summary


def main() -> None:
    args = parse_args()
    if args.generate_all == bool(args.dimension):
        raise SystemExit("Use exactly one of --all or --dimension.")
    if args.count is not None and args.count <= 0:
        raise SystemExit("--count must be > 0.")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    generator = LLMGenerator(model=args.model, temperature=args.temperature, call_interval=1.0)
    dimensions = list(STANDARDIZATION_DIMENSIONS) if args.generate_all else [str(args.dimension)]

    results: Dict[str, Dict[str, int]] = {}
    for dimension in dimensions:
        dimension_count = _resolve_count(dimension, args.count)
        results[dimension] = generate_for_dimension(
            dimension=dimension,
            count=dimension_count,
            generator=generator,
            max_rounds=args.max_rounds,
        )

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
