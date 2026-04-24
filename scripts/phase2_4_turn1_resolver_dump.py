from __future__ import annotations

import asyncio
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_config  # noqa: E402
from core.ao_manager import AOManager  # noqa: E402
from core.contracts.clarification_contract import ClarificationContract  # noqa: E402
from core.governed_router import build_router  # noqa: E402
from core.memory import FactMemory  # noqa: E402
from core.task_state import TaskState  # noqa: E402
from tools.file_analyzer import FileAnalyzerTool  # noqa: E402


BENCHMARK_PATH = PROJECT_ROOT / "evaluation" / "benchmarks" / "end2end_tasks.jsonl"
DIAG_DIR = PROJECT_ROOT / "evaluation" / "diagnostics"
CSV_PATH = DIAG_DIR / "phase2_4_turn1_resolver.csv"
SUMMARY_PATH = DIAG_DIR / "phase2_4_turn1_resolver_summary.md"


@dataclass
class ResolverRow:
    task_id: str
    category: str
    first_msg: str
    expected_tool: str
    resolver_outcome: str
    hit_step: str
    desired_chain_raw: str
    wants_factor: bool
    file_task_type: str
    has_因子: bool
    has_排放因子: bool
    has_排放: bool
    has_factor_en: bool
    has_emission_en: bool
    has_confirm_first: bool
    has_micro_keyword: bool
    has_macro_keyword: bool

    def as_csv_row(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "category": self.category,
            "first_msg": self.first_msg,
            "expected_tool": self.expected_tool,
            "resolver_outcome": self.resolver_outcome,
            "hit_step": self.hit_step,
            "desired_chain_raw": self.desired_chain_raw,
            "wants_factor": str(self.wants_factor).lower(),
            "file_task_type": self.file_task_type,
            "has_因子": str(self.has_因子).lower(),
            "has_排放因子": str(self.has_排放因子).lower(),
            "has_排放": str(self.has_排放).lower(),
            "has_factor_en": str(self.has_factor_en).lower(),
            "has_emission_en": str(self.has_emission_en).lower(),
            "has_confirm_first": str(self.has_confirm_first).lower(),
            "has_micro_keyword": str(self.has_micro_keyword).lower(),
            "has_macro_keyword": str(self.has_macro_keyword).lower(),
        }


class HintRouter:
    def __init__(self, hints: Dict[str, Any]):
        self._hints = dict(hints)

    def _extract_message_execution_hints(self, _state: Any) -> Dict[str, Any]:
        return dict(self._hints)


class NullAOManager:
    def get_ao_by_id(self, _ao_id: Optional[str]) -> None:
        return None


def load_tasks() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in BENCHMARK_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def expected_tool(task: Dict[str, Any]) -> str:
    chain = task.get("expected_tool_chain")
    if isinstance(chain, list) and chain:
        return str(chain[0])
    tool = task.get("expected_tool")
    return str(tool) if tool else "-"


def first_message(task: Dict[str, Any]) -> str:
    dialogue = task.get("dialogue")
    if isinstance(dialogue, list) and dialogue:
        first = dialogue[0]
        if isinstance(first, dict):
            return str(first.get("content") or first.get("message") or "")
        return str(first)
    return str(task.get("user_message") or "")


def resolve_project_path(path_value: Optional[str]) -> Optional[Path]:
    if not path_value:
        return None
    path = Path(str(path_value))
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


async def analyze_file_task_type(
    analyzer: FileAnalyzerTool,
    task: Dict[str, Any],
    errors: List[Dict[str, str]],
) -> tuple[str, Optional[Dict[str, Any]]]:
    if not task.get("has_file"):
        return "no_file", None
    file_path = resolve_project_path(task.get("test_file"))
    if file_path is None:
        return "analyzer_error", None
    try:
        result = await analyzer.execute(file_path=str(file_path))
    except Exception as exc:  # noqa: BLE001 - diagnostic script records exact failure.
        errors.append(
            {
                "task_id": str(task.get("id")),
                "exception_type": type(exc).__name__,
                "message": str(exc),
            }
        )
        return "analyzer_error", None
    if not result.success or not isinstance(result.data, dict):
        errors.append(
            {
                "task_id": str(task.get("id")),
                "exception_type": "ToolResultError",
                "message": str(getattr(result, "error", "") or getattr(result, "message", "") or "file analyzer failed"),
            }
        )
        return "analyzer_error", None
    task_type = str(result.data.get("task_type") or result.data.get("detected_type") or "其他")
    return task_type or "其他", dict(result.data)


def keyword_flags(message: str, config: Any) -> Dict[str, bool]:
    lower = message.lower()
    signals = tuple(getattr(config, "clarification_confirm_first_signals", ()) or ())
    return {
        "has_因子": "因子" in message,
        "has_排放因子": "排放因子" in message,
        "has_排放": "排放" in message,
        "has_factor_en": "factor" in lower,
        "has_emission_en": "emission" in lower,
        "has_confirm_first": any(signal and signal in lower for signal in signals),
        "has_micro_keyword": any(token in lower for token in ("逐秒", "微观", "vsp", "second-by-second")),
        "has_macro_keyword": any(token in lower for token in ("宏观", "路段级", "link-level", "总排放", "年排放")),
    }


def hit_step_for(
    *,
    pending_tool: Optional[str],
    desired_chain: List[str],
    file_task_type: str,
    wants_factor: bool,
    resolver: Optional[str],
) -> str:
    if pending_tool:
        return "pending"
    if desired_chain:
        return "desired_chain"
    if file_task_type == "macro_emission" and resolver == "calculate_macro_emission":
        return "file_task_type"
    if file_task_type == "micro_emission" and resolver == "calculate_micro_emission":
        return "file_task_type"
    if wants_factor and resolver == "query_emission_factors":
        return "wants_factor_fallback"
    return "none" if resolver is None else "revision_parent"


async def build_rows() -> tuple[List[ResolverRow], List[Dict[str, str]]]:
    config = get_config()
    tasks = load_tasks()
    router = build_router(session_id="phase2_4_resolver_dump", router_mode="full")
    analyzer = FileAnalyzerTool()
    analyzer_errors: List[Dict[str, str]] = []
    rows: List[ResolverRow] = []

    for task in tasks:
        message = first_message(task)
        file_task_type, analysis = await analyze_file_task_type(analyzer, task, analyzer_errors)
        state = TaskState.initialize(
            user_message=message,
            file_path=str(resolve_project_path(task.get("test_file"))) if task.get("has_file") and task.get("test_file") else None,
            memory_dict={},
            session_id=f"phase2_4_{task.get('id')}",
        )
        if isinstance(analysis, dict):
            state.update_file_context(analysis)

        hints = router._extract_message_execution_hints(state)
        fake_inner = HintRouter(hints)
        contract = ClarificationContract(
            inner_router=fake_inner,
            ao_manager=NullAOManager(),
            runtime_config=config,
        )
        resolver = contract._resolve_tool_name(
            state=state,
            current_ao=None,
            pending_state={},
            classification=None,
        )
        desired_chain = [str(item) for item in hints.get("desired_tool_chain") or [] if item]
        flags = keyword_flags(message, config)
        rows.append(
            ResolverRow(
                task_id=str(task.get("id") or ""),
                category=str(task.get("category") or ""),
                first_msg=message,
                expected_tool=expected_tool(task),
                resolver_outcome=resolver or "None",
                hit_step=hit_step_for(
                    pending_tool=None,
                    desired_chain=desired_chain,
                    file_task_type=file_task_type,
                    wants_factor=bool(hints.get("wants_factor")),
                    resolver=resolver,
                ),
                desired_chain_raw=";".join(desired_chain),
                wants_factor=bool(hints.get("wants_factor")),
                file_task_type=file_task_type,
                **flags,
            )
        )
    return rows, analyzer_errors


def write_csv(rows: List[ResolverRow]) -> None:
    DIAG_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "task_id",
        "category",
        "first_msg",
        "expected_tool",
        "resolver_outcome",
        "hit_step",
        "desired_chain_raw",
        "wants_factor",
        "file_task_type",
        "has_因子",
        "has_排放因子",
        "has_排放",
        "has_factor_en",
        "has_emission_en",
        "has_confirm_first",
        "has_micro_keyword",
        "has_macro_keyword",
    ]
    with CSV_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_csv_row())


def category_summary(rows: List[ResolverRow]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[ResolverRow]] = defaultdict(list)
    for row in rows:
        grouped[row.category].append(row)
    summary: List[Dict[str, Any]] = []
    for category in sorted(grouped):
        bucket = grouped[category]
        resolver_none = sum(1 for row in bucket if row.resolver_outcome == "None")
        resolver_expected = sum(1 for row in bucket if row.resolver_outcome == row.expected_tool)
        resolver_wrong = len(bucket) - resolver_none - resolver_expected
        summary.append(
            {
                "category": category,
                "total": len(bucket),
                "resolver_none": resolver_none,
                "resolver_expected": resolver_expected,
                "resolver_wrong": resolver_wrong,
                "none_rate": resolver_none / len(bucket) if bucket else 0,
            }
        )
    return summary


def miss_breakdown(rows: List[ResolverRow]) -> Counter:
    counter: Counter = Counter()
    for row in rows:
        if row.resolver_outcome != "None":
            continue
        key = (
            row.expected_tool,
            "因子" if row.has_因子 else "-",
            "排放因子" if row.has_排放因子 else "-",
            "排放" if row.has_排放 else "-",
            "factor" if row.has_factor_en else "-",
            "emission" if row.has_emission_en else "-",
            "confirm_first" if row.has_confirm_first else "-",
            "micro_kw" if row.has_micro_keyword else "-",
            "macro_kw" if row.has_macro_keyword else "-",
            row.file_task_type,
        )
        counter[key] += 1
    return counter


def write_summary(rows: List[ResolverRow], analyzer_errors: List[Dict[str, str]]) -> None:
    summary = category_summary(rows)
    breakdown = miss_breakdown(rows)

    factor_misses = [
        row for row in rows
        if row.resolver_outcome == "None" and row.expected_tool == "query_emission_factors"
    ]
    factor_misses_with_因子 = [row for row in factor_misses if row.has_因子]
    false_factor_risk = [
        row for row in rows
        if row.expected_tool != "query_emission_factors" and row.has_因子 and not row.has_排放因子
    ]
    no_file_micro_macro_misses = [
        row for row in rows
        if row.resolver_outcome == "None"
        and row.expected_tool in {"calculate_micro_emission", "calculate_macro_emission"}
        and row.file_task_type == "no_file"
    ]

    lines: List[str] = ["# Phase 2.4 Turn-1 Resolver Summary", ""]
    lines.extend(
        [
            "| category | total | resolver=None | resolver=expected | resolver=wrong | none_rate |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for item in summary:
        lines.append(
            f"| {item['category']} | {item['total']} | {item['resolver_none']} | "
            f"{item['resolver_expected']} | {item['resolver_wrong']} | {item['none_rate']:.1%} |"
        )

    lines.extend(["", "## Miss Breakdown", ""])
    lines.extend(
        [
            "| expected_tool | 因子 | 排放因子 | 排放 | factor | emission | confirm_first | micro_kw | macro_kw | file_task_type | count |",
            "|---|---|---|---|---|---|---|---|---|---|---:|",
        ]
    )
    for key, count in breakdown.most_common():
        lines.append("| " + " | ".join(str(item) for item in key) + f" | {count} |")

    lines.extend(
        [
            "",
            "## Decision Questions",
            "",
            f"- `query_emission_factors` resolver=None misses: {len(factor_misses)}",
            f"- Of those, messages containing `因子`: {len(factor_misses_with_因子)}",
            f"- Expected != `query_emission_factors` tasks containing `因子` but not `排放因子`: {len(false_factor_risk)}",
            (
                "- Expected micro/macro resolver=None tasks with `file_task_type=no_file`: "
                f"{len(no_file_micro_macro_misses)}"
            ),
        ]
    )
    if false_factor_risk:
        lines.append("")
        lines.append("### Potential false-positive examples for expanding wants_factor to `因子`")
        for row in false_factor_risk[:20]:
            lines.append(f"- `{row.task_id}` ({row.expected_tool}): {row.first_msg}")

    lines.extend(["", "## Analyzer Errors", ""])
    if not analyzer_errors:
        lines.append("No analyzer errors.")
    else:
        lines.extend(["| task_id | exception_type | message |", "|---|---|---|"])
        for item in analyzer_errors:
            message = str(item.get("message") or "").replace("\n", " ")[:300]
            lines.append(f"| {item.get('task_id')} | {item.get('exception_type')} | {message} |")

    SUMMARY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> None:
    rows, analyzer_errors = await build_rows()
    write_csv(rows)
    write_summary(rows, analyzer_errors)
    print(json.dumps({"rows": len(rows), "csv": str(CSV_PATH), "summary": str(SUMMARY_PATH)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
