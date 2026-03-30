"""Evaluate file-aware task recognition and column grounding."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.assembler import ContextAssembler
from evaluation.utils import (
    classify_failure,
    classify_recoverability,
    compare_expected_subset,
    load_jsonl,
    now_ts,
    resolve_project_path,
    runtime_overrides,
    safe_div,
    write_json,
    write_jsonl,
)
from skills.macro_emission.excel_handler import ExcelHandler as MacroExcelHandler
from skills.micro_emission.excel_handler import ExcelHandler as MicroExcelHandler
from tools.file_analyzer import FileAnalyzerTool


def _load_dataframe(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    return pd.read_excel(path)


def _extract_micro_mapping(path: Path) -> Dict[str, str]:
    handler = MicroExcelHandler(llm_client=None)
    df = _load_dataframe(path)
    df.columns = df.columns.str.strip()
    mapping = {}
    speed_col = handler._find_column(df, handler.SPEED_COLUMNS)
    time_col = handler._find_column(df, handler.TIME_COLUMNS)
    acc_col = handler._find_column(df, handler.ACCELERATION_COLUMNS)
    grade_col = handler._find_column(df, handler.GRADE_COLUMNS)
    if speed_col:
        mapping["speed"] = speed_col
    if time_col:
        mapping["time"] = time_col
    if acc_col:
        mapping["acceleration"] = acc_col
    if grade_col:
        mapping["grade"] = grade_col
    return mapping


def _extract_macro_mapping(path: Path) -> Dict[str, str]:
    handler = MacroExcelHandler(llm_client=None)
    df = _load_dataframe(path)
    df.columns = [str(col).strip() for col in df.columns]
    result = handler._resolve_column_mapping(df)
    return result.get("field_to_column", {})


def run_file_grounding_evaluation(
    samples_path: Path,
    output_dir: Path,
    enable_file_analyzer: bool = True,
    enable_file_context_injection: bool = True,
    macro_column_mapping_modes: tuple[str, ...] = ("direct", "ai", "fuzzy"),
) -> Dict[str, Any]:
    samples = load_jsonl(samples_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    logs: List[Dict[str, Any]] = []
    task_hits = 0
    mapping_hits = 0
    mapping_total = 0
    required_hits = 0
    context_hits = 0

    # Re-run with explicit async handling outside of override body to keep logic clearer.
    import asyncio

    async def _evaluate_async() -> None:
        nonlocal task_hits, mapping_hits, mapping_total, required_hits, context_hits, logs
        logs = []
        with runtime_overrides(
            enable_file_analyzer=enable_file_analyzer,
            enable_file_context_injection=enable_file_context_injection,
            macro_column_mapping_modes=macro_column_mapping_modes,
        ):
            analyzer = FileAnalyzerTool()
            assembler = ContextAssembler()
            for sample in samples:
                file_path = resolve_project_path(sample["file_path"])
                analysis = None
                if enable_file_analyzer:
                    analysis_result = await analyzer.execute(file_path=str(file_path))
                    analysis = analysis_result.data if analysis_result.success else None

                if sample["expected_task_type"] == "macro_emission":
                    actual_mapping = _extract_macro_mapping(file_path)
                else:
                    actual_mapping = _extract_micro_mapping(file_path)

                required_present = False
                if analysis:
                    required_present = bool(
                        analysis.get("macro_has_required")
                        if sample["expected_task_type"] == "macro_emission"
                        else analysis.get("micro_has_required")
                    )

                assembled = assembler.assemble(
                    user_message=sample["user_query"],
                    working_memory=[],
                    fact_memory={},
                    file_context=analysis,
                )
                last_message = assembled.messages[-1]["content"] if assembled.messages else ""
                context_injected = "Filename:" in last_message and "task_type:" in last_message

                task_match = bool(analysis and analysis.get("task_type") == sample["expected_task_type"])
                mapping_cmp = compare_expected_subset(actual_mapping, sample["expected_mapping"])
                task_hits += int(task_match)
                required_hits += int(required_present == sample["expected_required_present"])
                expected_context = enable_file_context_injection and bool(analysis)
                context_hits += int(context_injected == expected_context)
                mapping_total += len(sample["expected_mapping"])
                for detail in mapping_cmp["details"].values():
                    if detail.get("matched"):
                        mapping_hits += 1

                record = {
                    "sample_id": sample["sample_id"],
                    "input": {
                        "user_query": sample["user_query"],
                        "file_path": str(file_path),
                    },
                    "file_analysis": analysis,
                    "routing_result": {
                        "expected_task_type": sample["expected_task_type"],
                        "actual_task_type": analysis.get("task_type") if analysis else None,
                    },
                    "mapping_result": {
                        "expected_mapping": sample["expected_mapping"],
                        "actual_mapping": actual_mapping,
                        "comparison": mapping_cmp,
                    },
                    "context_injected": context_injected,
                    "required_present": required_present,
                    "success": task_match and mapping_cmp["matched"] and (required_present == sample["expected_required_present"]),
                }
                failure_type = classify_failure(record)
                record["failure_type"] = failure_type
                record["recoverability"] = classify_recoverability(failure_type)
                logs.append(record)

    asyncio.run(_evaluate_async())

    metrics = {
        "task": "file_grounding",
        "samples": len(samples),
        "routing_accuracy": round(safe_div(task_hits, len(samples)), 4),
        "column_mapping_accuracy": round(safe_div(mapping_hits, mapping_total), 4),
        "required_field_accuracy": round(safe_div(required_hits, len(samples)), 4),
        "file_context_injection_consistency": round(safe_div(context_hits, len(samples)), 4),
        "enable_file_analyzer": enable_file_analyzer,
        "enable_file_context_injection": enable_file_context_injection,
        "macro_column_mapping_modes": list(macro_column_mapping_modes),
        "logs_path": str(output_dir / "file_grounding_logs.jsonl"),
    }
    write_jsonl(output_dir / "file_grounding_logs.jsonl", logs)
    write_json(output_dir / "file_grounding_metrics.json", metrics)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate file task grounding.")
    parser.add_argument(
        "--samples",
        type=Path,
        default=PROJECT_ROOT / "evaluation/file_tasks/samples.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / f"evaluation/results/file_grounding/file_grounding_{now_ts()}",
    )
    parser.add_argument("--disable-file-analyzer", action="store_true")
    parser.add_argument("--disable-file-context-injection", action="store_true")
    parser.add_argument(
        "--macro-modes",
        default="direct,ai,fuzzy",
        help="Comma-separated macro column mapping modes.",
    )
    args = parser.parse_args()

    metrics = run_file_grounding_evaluation(
        samples_path=args.samples,
        output_dir=args.output_dir,
        enable_file_analyzer=not args.disable_file_analyzer,
        enable_file_context_injection=not args.disable_file_context_injection,
        macro_column_mapping_modes=tuple(mode.strip() for mode in args.macro_modes.split(",") if mode.strip()),
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
