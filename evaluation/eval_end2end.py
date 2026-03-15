"""Evaluate end-to-end grounded execution for benchmark tasks."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.executor import ToolExecutor
from core.router import UnifiedRouter
from evaluation.utils import (
    classify_failure,
    classify_recoverability,
    load_jsonl,
    now_ts,
    rebuild_tool_registry,
    resolve_project_path,
    runtime_overrides,
    safe_div,
    write_json,
    write_jsonl,
)
from tools.file_analyzer import FileAnalyzerTool


def _check_outputs(result_like: Dict[str, Any], expected_outputs: Dict[str, bool]) -> Dict[str, Any]:
    data = result_like.get("data") or {}
    actual_outputs = {
        "has_chart_data": bool(result_like.get("chart_data")),
        "has_table_data": bool(result_like.get("table_data")),
        "has_map_data": bool(result_like.get("map_data")),
        "has_download_file": bool(result_like.get("download_file") or data.get("download_file")),
    }
    matched = True
    details = {}
    for key, expected in expected_outputs.items():
        actual = actual_outputs.get(key)
        details[key] = {"expected": expected, "actual": actual, "matched": actual == expected}
        matched = matched and actual == expected
    return {"matched": matched, "details": details, "actual_outputs": actual_outputs}


def run_end2end_evaluation(
    samples_path: Path,
    output_dir: Path,
    mode: str = "tool",
    enable_file_analyzer: bool = True,
    enable_file_context_injection: bool = True,
    enable_executor_standardization: bool = True,
    macro_column_mapping_modes: tuple[str, ...] = ("direct", "ai", "fuzzy"),
    only_task: Optional[str] = None,
) -> Dict[str, Any]:
    samples = load_jsonl(samples_path)
    if only_task:
        samples = [sample for sample in samples if sample["expected_tool_name"] == only_task]
    output_dir.mkdir(parents=True, exist_ok=True)
    logs: List[Dict[str, Any]] = []

    async def _run_async() -> Dict[str, Any]:
        tool_successes = 0
        completion_successes = 0
        route_successes = 0
        total_turns = 0
        skipped = 0

        with runtime_overrides(
            enable_file_analyzer=enable_file_analyzer,
            enable_file_context_injection=enable_file_context_injection,
            enable_executor_standardization=enable_executor_standardization,
            macro_column_mapping_modes=macro_column_mapping_modes,
        ):
            rebuild_tool_registry()
            executor = ToolExecutor()
            analyzer = FileAnalyzerTool()

            for sample in samples:
                file_path = resolve_project_path(sample.get("file_path"))
                file_analysis = None
                if file_path and enable_file_analyzer:
                    analysis_result = await analyzer.execute(file_path=str(file_path))
                    file_analysis = analysis_result.data if analysis_result.success else None

                start = time.perf_counter()
                route_result: Dict[str, Any] = {}
                raw_result: Dict[str, Any]
                error_message = None
                success = False
                interaction_turns = 1
                standardization_trace = None
                tool_logs = None

                try:
                    if mode == "router":
                        router = UnifiedRouter(session_id=f"eval_{sample['sample_id']}")
                        trace: Dict[str, Any] = {}
                        router_result = await router.chat(
                            user_message=sample["user_query"],
                            file_path=str(file_path) if file_path else None,
                            trace=trace,
                        )
                        raw_result = {
                            "text": router_result.text,
                            "chart_data": router_result.chart_data,
                            "table_data": router_result.table_data,
                            "map_data": router_result.map_data,
                            "download_file": router_result.download_file,
                        }
                        routed_tools = trace.get("routing", {}).get("tool_calls", [])
                        route_result = {
                            "expected_tool_name": sample["expected_tool_name"],
                            "actual_tool_name": routed_tools[0]["name"] if routed_tools else None,
                            "tool_calls": routed_tools,
                        }
                        interaction_turns = max(1, len(trace.get("tool_execution", [])))
                        tool_logs = trace.get("tool_execution", [])
                        if tool_logs:
                            first_batch = tool_logs[0].get("tool_results", [])
                            if first_batch:
                                standardization_trace = first_batch[0].get("trace")
                        success = bool(router_result.text)
                    else:
                        raw_result = await executor.execute(
                            tool_name=sample["expected_tool_name"],
                            arguments=sample["tool_arguments"],
                            file_path=str(file_path) if file_path else None,
                        )
                        route_result = {
                            "expected_tool_name": sample["expected_tool_name"],
                            "actual_tool_name": sample["expected_tool_name"],
                            "tool_calls": [{"name": sample["expected_tool_name"], "arguments": sample["tool_arguments"]}],
                        }
                        standardization_trace = raw_result.get("_trace")
                        tool_logs = [raw_result.get("_trace")]
                        success = bool(raw_result.get("success"))
                except Exception as exc:
                    if mode == "router":
                        skipped += 1
                    raw_result = {}
                    error_message = str(exc)

                duration_ms = round((time.perf_counter() - start) * 1000, 2)
                output_check = _check_outputs(raw_result, sample.get("expected_outputs", {}))
                route_match = route_result.get("actual_tool_name") == sample["expected_tool_name"]
                completion = (success == sample.get("expected_success", True)) and output_check["matched"]
                tool_successes += int(success)
                route_successes += int(route_match)
                completion_successes += int(completion)
                total_turns += interaction_turns

                record = {
                    "sample_id": sample["sample_id"],
                    "mode": mode,
                    "input": {
                        "user_query": sample["user_query"],
                        "file_path": str(file_path) if file_path else None,
                        "tool_arguments": sample["tool_arguments"],
                    },
                    "file_analysis": file_analysis,
                    "routing_result": route_result,
                    "standardization_result": standardization_trace,
                    "tool_call_logs": tool_logs,
                    "final_status": {
                        "success": success,
                        "completion": completion,
                        "output_check": output_check,
                        "message": raw_result.get("message") or raw_result.get("text") or error_message,
                    },
                    "timing_ms": duration_ms,
                    "success": completion,
                    "error": error_message or raw_result.get("message"),
                    "error_type": None if completion else ("router" if mode == "router" and not route_match else "execution"),
                }
                failure_type = classify_failure(record)
                record["failure_type"] = failure_type
                record["recoverability"] = classify_recoverability(failure_type)
                logs.append(record)

        metrics = {
            "task": "end2end",
            "mode": mode,
            "samples": len(samples),
            "tool_call_success_rate": round(safe_div(tool_successes, len(samples)), 4),
            "route_accuracy": round(safe_div(route_successes, len(samples)), 4),
            "end2end_completion_rate": round(safe_div(completion_successes, len(samples)), 4),
            "average_interaction_turns": round(safe_div(total_turns, len(samples)), 4),
            "skipped_samples": skipped,
            "enable_file_analyzer": enable_file_analyzer,
            "enable_file_context_injection": enable_file_context_injection,
            "enable_executor_standardization": enable_executor_standardization,
            "macro_column_mapping_modes": list(macro_column_mapping_modes),
            "logs_path": str(output_dir / "end2end_logs.jsonl"),
        }
        return metrics

    metrics = asyncio.run(_run_async())
    write_jsonl(output_dir / "end2end_logs.jsonl", logs)
    write_json(output_dir / "end2end_metrics.json", metrics)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate end-to-end tasks.")
    parser.add_argument(
        "--samples",
        type=Path,
        default=PROJECT_ROOT / "evaluation/end2end/samples.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / f"evaluation/logs/end2end_{now_ts()}",
    )
    parser.add_argument("--mode", choices=["tool", "router"], default="tool")
    parser.add_argument("--disable-file-analyzer", action="store_true")
    parser.add_argument("--disable-file-context-injection", action="store_true")
    parser.add_argument("--disable-executor-standardization", action="store_true")
    parser.add_argument("--macro-modes", default="direct,ai,fuzzy")
    parser.add_argument("--only-task", choices=["query_emission_factors", "calculate_micro_emission", "calculate_macro_emission"])
    args = parser.parse_args()

    metrics = run_end2end_evaluation(
        samples_path=args.samples,
        output_dir=args.output_dir,
        mode=args.mode,
        enable_file_analyzer=not args.disable_file_analyzer,
        enable_file_context_injection=not args.disable_file_context_injection,
        enable_executor_standardization=not args.disable_executor_standardization,
        macro_column_mapping_modes=tuple(mode.strip() for mode in args.macro_modes.split(",") if mode.strip()),
        only_task=args.only_task,
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
