"""Evaluate end-to-end routing and execution over structured benchmark tasks.

Notes:
- `router` mode exercises `UnifiedRouter.chat()` and is the primary end-to-end path.
- `tool` mode remains available for offline validation and smoke-style checks.
- Router-mode evaluation may require provider/API access depending on the configured LLM stack.
"""
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
    compare_expected_subset,
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


DEFAULT_SAMPLES = PROJECT_ROOT / "evaluation" / "benchmarks" / "end2end_tasks.jsonl"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "evaluation" / "results" / "end2end"
LEGACY_NEEDS_USER_STAGE = {
    "NEEDS_INPUT_COMPLETION",
    "NEEDS_PARAMETER_CONFIRMATION",
    "NEEDS_CLARIFICATION",
}
GEOMETRY_REQUIRED_TOOLS = {
    "calculate_dispersion",
    "render_spatial_map",
}
GEOMETRY_TEXT_CUES = ("geometry", "几何", "geojson", "wkt", "坐标")


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


def _extract_trace_steps(trace_payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(trace_payload, dict):
        return []
    steps = trace_payload.get("steps")
    if isinstance(steps, list):
        return [step for step in steps if isinstance(step, dict)]
    return []


def _collect_standardization_records(trace_steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for step in trace_steps:
        step_records = step.get("standardization_records")
        if isinstance(step_records, list):
            records.extend(record for record in step_records if isinstance(record, dict))
    return records


def _has_result_payload(
    response_payload: Dict[str, Any],
    executed_tool_calls: List[Dict[str, Any]],
) -> bool:
    if response_payload.get("chart_data") or response_payload.get("table_data"):
        return True
    if response_payload.get("map_data") or response_payload.get("download_file"):
        return True

    for tool_call in executed_tool_calls:
        result = tool_call.get("result", {})
        if not isinstance(result, dict):
            continue
        if result.get("summary") or result.get("data"):
            return True
    return False


def _tool_chain_matches(actual: List[str], expected: List[str]) -> bool:
    if not expected:
        return True
    return actual == expected


def _file_has_explicit_geometry(file_analysis: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(file_analysis, dict):
        return False

    columns = file_analysis.get("columns")
    if isinstance(columns, list):
        lowered = {str(column).strip().lower() for column in columns}
        if any(marker in lowered for marker in {"geometry", "geom", "wkt", "geojson"}):
            return True

    spatial_metadata = file_analysis.get("spatial_metadata")
    if isinstance(spatial_metadata, dict) and spatial_metadata:
        return True

    return False


def _geometry_gate_prefix(expected_tool_chain: List[str]) -> Optional[List[str]]:
    if not expected_tool_chain:
        return None

    prefix: List[str] = []
    for tool_name in expected_tool_chain:
        if tool_name in GEOMETRY_REQUIRED_TOOLS:
            return prefix
        prefix.append(tool_name)
    return None


def _is_geometry_gated_multistep_success(
    task: Dict[str, Any],
    *,
    actual_tool_chain: List[str],
    criteria_actuals: Dict[str, bool],
    response_payload: Dict[str, Any],
    file_analysis: Optional[Dict[str, Any]],
) -> bool:
    if task.get("category") != "multi_step":
        return False

    expected_tool_chain = [str(item) for item in task.get("expected_tool_chain", []) if item]
    expected_prefix = _geometry_gate_prefix(expected_tool_chain)
    if not expected_prefix or actual_tool_chain != expected_prefix:
        return False

    if _file_has_explicit_geometry(file_analysis):
        return False

    missing_field_diagnostics = (file_analysis or {}).get("missing_field_diagnostics")
    if isinstance(missing_field_diagnostics, dict):
        if str(missing_field_diagnostics.get("status") or "").strip().lower() != "complete":
            return False

    if not criteria_actuals.get("tool_executed"):
        return False
    if not criteria_actuals.get("params_legal"):
        return False
    if not criteria_actuals.get("result_has_data"):
        return False
    if not criteria_actuals.get("requires_user_response"):
        return False
    if criteria_actuals.get("trace_has_error"):
        return False

    response_text = str(response_payload.get("text") or "").lower()
    return any(cue in response_text for cue in GEOMETRY_TEXT_CUES)


def _normalize_task(sample: Dict[str, Any]) -> Dict[str, Any]:
    if "sample_id" in sample:
        expected_tool = sample.get("expected_tool_name")
        return {
            "id": sample["sample_id"],
            "category": "legacy",
            "description": sample.get("user_query", sample["sample_id"]),
            "user_message": sample.get("user_query", ""),
            "has_file": bool(sample.get("file_path")),
            "test_file": sample.get("file_path"),
            "expected_tool": expected_tool,
            "expected_tool_chain": [expected_tool] if expected_tool else [],
            "expected_params": sample.get("tool_arguments", {}),
            "expected_outputs": sample.get("expected_outputs", {}),
            "success_criteria": {},
            "__legacy_expected_success": bool(sample.get("expected_success", True)),
            "__legacy_tool_arguments": sample.get("tool_arguments", {}),
        }

    expected_tool = sample.get("expected_tool")
    chain = sample.get("expected_tool_chain")
    if not isinstance(chain, list):
        chain = [expected_tool] if expected_tool else []

    return {
        "id": sample.get("id", "unknown_task"),
        "category": sample.get("category", "uncategorized"),
        "description": sample.get("description", sample.get("user_message", "")),
        "user_message": sample.get("user_message", ""),
        "has_file": bool(sample.get("has_file")),
        "test_file": sample.get("test_file"),
        "expected_tool": expected_tool,
        "expected_tool_chain": [item for item in chain if item],
        "expected_params": sample.get("expected_params", {}),
        "expected_outputs": sample.get("expected_outputs", {}),
        "success_criteria": sample.get("success_criteria", {}),
        "__legacy_expected_success": None,
        "__legacy_tool_arguments": sample.get("tool_arguments"),
    }


def _build_task_result(
    task: Dict[str, Any],
    *,
    executed_tool_calls: List[Dict[str, Any]],
    response_payload: Dict[str, Any],
    trace_payload: Optional[Dict[str, Any]],
    error_message: Optional[str],
    duration_ms: float,
    file_analysis: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    trace_steps = _extract_trace_steps(trace_payload)
    trace_step_types = [str(step.get("step_type", "")).lower() for step in trace_steps]
    standardization_records = _collect_standardization_records(trace_steps)
    actual_tool_chain = [str(call.get("name")) for call in executed_tool_calls if call.get("name")]
    actual_arguments = executed_tool_calls[0].get("arguments", {}) if executed_tool_calls else {}
    params_comparison = compare_expected_subset(actual_arguments, task.get("expected_params", {}))

    tool_executed = bool(executed_tool_calls)
    params_legal = params_comparison["matched"] if task.get("expected_params") else tool_executed
    result_has_data = _has_result_payload(response_payload, executed_tool_calls)
    final_stage = str((trace_payload or {}).get("final_stage") or "")
    requires_user_response = (
        final_stage in LEGACY_NEEDS_USER_STAGE
        or any(step_type in {"clarification", "input_completion_required", "parameter_negotiation_required"} for step_type in trace_step_types)
    )
    constraint_blocked = (
        "参数组合不合法" in str(response_payload.get("text", ""))
        or any(
            record.get("record_type") == "cross_constraint_violation"
            for record in standardization_records
        )
    )
    constraint_warning = any(
        record.get("record_type") == "cross_constraint_warning"
        for record in standardization_records
    )
    trace_has_error = any(step.get("error") for step in trace_steps) or any(
        step_type == "error" for step_type in trace_step_types
    )

    criteria_actuals = {
        "tool_executed": tool_executed,
        "params_legal": params_legal,
        "result_has_data": result_has_data,
        "requires_user_response": requires_user_response,
        "constraint_blocked": constraint_blocked,
        "constraint_warning": constraint_warning,
        "trace_has_error": trace_has_error,
    }
    geometry_gated_success = _is_geometry_gated_multistep_success(
        task,
        actual_tool_chain=actual_tool_chain,
        criteria_actuals=criteria_actuals,
        response_payload=response_payload,
        file_analysis=file_analysis,
    )
    tool_match = (
        _tool_chain_matches(actual_tool_chain, task.get("expected_tool_chain", []))
        or geometry_gated_success
    )

    if task["__legacy_expected_success"] is not None:
        output_check = _check_outputs(response_payload, task.get("expected_outputs", {}))
        success = (
            (tool_executed == task["__legacy_expected_success"])
            and output_check["matched"]
            and tool_match
        )
    else:
        output_check = None
        success = tool_match
        for key, expected_value in (task.get("success_criteria") or {}).items():
            if key not in criteria_actuals:
                continue
            success = success and (criteria_actuals[key] == expected_value)

    record = {
        "task_id": task["id"],
        "category": task["category"],
        "description": task["description"],
        "input": {
            "user_message": task["user_message"],
            "test_file": task.get("test_file"),
        },
        "file_analysis": file_analysis,
        "expected": {
            "tool_chain": task.get("expected_tool_chain", []),
            "params": task.get("expected_params", {}),
            "success_criteria": task.get("success_criteria", {}),
            "legacy_expected_success": task["__legacy_expected_success"],
            "legacy_expected_outputs": task.get("expected_outputs", {}),
        },
        "actual": {
            "tool_chain": actual_tool_chain,
            "tool_chain_match": tool_match,
            "geometry_gated_success": geometry_gated_success,
            "tool_calls": executed_tool_calls,
            "params_comparison": params_comparison,
            "criteria": criteria_actuals,
            "response_payload": response_payload,
            "trace_step_types": trace_step_types,
            "standardization_records": standardization_records,
            "final_stage": final_stage or None,
        },
        "success": success,
        "timing_ms": duration_ms,
        "error": error_message,
        "output_check": output_check,
    }
    failure_type = classify_failure(record)
    record["failure_type"] = failure_type
    record["recoverability"] = classify_recoverability(failure_type)
    return record


def _aggregate_metrics(logs: List[Dict[str, Any]], mode: str, skipped: int) -> Dict[str, Any]:
    categories = sorted({str(log.get("category", "uncategorized")) for log in logs})
    success_count = sum(1 for log in logs if log.get("success"))
    tool_match_count = sum(
        1
        for log in logs
        if log.get("actual", {}).get("tool_chain_match")
        or not log.get("expected", {}).get("tool_chain")
    )
    params_legal_count = sum(
        1 for log in logs if log.get("actual", {}).get("criteria", {}).get("params_legal")
    )
    result_data_count = sum(
        1 for log in logs if log.get("actual", {}).get("criteria", {}).get("result_has_data")
    )

    by_category: Dict[str, Dict[str, Any]] = {}
    for category in categories:
        bucket = [log for log in logs if log.get("category") == category]
        by_category[category] = {
            "tasks": len(bucket),
            "success_rate": round(safe_div(sum(1 for log in bucket if log.get("success")), len(bucket)), 4),
            "tool_accuracy": round(
                safe_div(
                    sum(
                        1
                        for log in bucket
                        if log.get("actual", {}).get("tool_chain_match")
                        or not log.get("expected", {}).get("tool_chain")
                    ),
                    len(bucket),
                ),
                4,
            ),
        }

    return {
        "task": "end2end",
        "mode": mode,
        "tasks": len(logs),
        "completion_rate": round(safe_div(success_count, len(logs)), 4),
        "tool_accuracy": round(safe_div(tool_match_count, len(logs)), 4),
        "parameter_legal_rate": round(safe_div(params_legal_count, len(logs)), 4),
        "result_data_rate": round(safe_div(result_data_count, len(logs)), 4),
        "skipped_tasks": skipped,
        "by_category": by_category,
    }


def run_end2end_evaluation(
    samples_path: Path,
    output_dir: Path,
    mode: str = "router",
    enable_file_analyzer: bool = True,
    enable_file_context_injection: bool = True,
    enable_executor_standardization: bool = True,
    macro_column_mapping_modes: tuple[str, ...] = ("direct", "ai", "fuzzy"),
    only_task: Optional[str] = None,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    raw_samples = load_jsonl(samples_path)
    tasks = [_normalize_task(sample) for sample in raw_samples]
    if only_task:
        tasks = [task for task in tasks if only_task in task.get("expected_tool_chain", [])]
    if category:
        tasks = [task for task in tasks if task.get("category") == category]

    output_dir.mkdir(parents=True, exist_ok=True)
    logs: List[Dict[str, Any]] = []

    async def _run_async() -> Dict[str, Any]:
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

            for task in tasks:
                file_path = resolve_project_path(task.get("test_file"))
                file_analysis = None
                if file_path and enable_file_analyzer:
                    analysis_result = await analyzer.execute(file_path=str(file_path))
                    file_analysis = analysis_result.data if analysis_result.success else None

                start = time.perf_counter()
                error_message: Optional[str] = None
                response_payload: Dict[str, Any] = {}
                trace_payload: Optional[Dict[str, Any]] = None
                executed_tool_calls: List[Dict[str, Any]] = []

                try:
                    if mode == "router":
                        router = UnifiedRouter(session_id=f"eval_{task['id']}")
                        trace: Dict[str, Any] = {}
                        result = await router.chat(
                            user_message=task["user_message"],
                            file_path=str(file_path) if file_path else None,
                            trace=trace,
                        )
                        response_payload = {
                            "text": result.text,
                            "chart_data": result.chart_data,
                            "table_data": result.table_data,
                            "map_data": result.map_data,
                            "download_file": result.download_file,
                        }
                        executed_tool_calls = list(result.executed_tool_calls or [])
                        trace_payload = result.trace or trace
                    else:
                        expected_chain = task.get("expected_tool_chain", [])
                        if len(expected_chain) != 1:
                            skipped += 1
                            logs.append(
                                {
                                    "task_id": task["id"],
                                    "category": task["category"],
                                    "description": task["description"],
                                    "success": False,
                                    "error": "tool mode only supports single-step benchmark tasks",
                                    "failure_type": "工具执行异常",
                                    "recoverability": "可恢复失败",
                                    "timing_ms": round((time.perf_counter() - start) * 1000, 2),
                                }
                            )
                            continue

                        tool_name = expected_chain[0]
                        tool_arguments = dict(task.get("__legacy_tool_arguments") or task.get("expected_params") or {})
                        tool_result = await executor.execute(
                            tool_name=tool_name,
                            arguments=tool_arguments,
                            file_path=str(file_path) if file_path else None,
                        )
                        response_payload = {
                            "text": tool_result.get("message"),
                            "chart_data": tool_result.get("chart_data"),
                            "table_data": tool_result.get("table_data"),
                            "map_data": tool_result.get("map_data"),
                            "download_file": tool_result.get("download_file"),
                            "data": tool_result.get("data"),
                        }
                        executed_tool_calls = [
                            {
                                "name": tool_name,
                                "arguments": tool_arguments,
                                "result": {
                                    "success": bool(tool_result.get("success")),
                                    "summary": tool_result.get("summary"),
                                    "data": tool_result.get("data"),
                                },
                            }
                        ]
                        trace_payload = tool_result.get("_trace")
                except Exception as exc:
                    error_message = str(exc)

                duration_ms = round((time.perf_counter() - start) * 1000, 2)
                logs.append(
                    _build_task_result(
                        task,
                        executed_tool_calls=executed_tool_calls,
                        response_payload=response_payload,
                        trace_payload=trace_payload,
                        error_message=error_message,
                        duration_ms=duration_ms,
                        file_analysis=file_analysis,
                    )
                )

        return _aggregate_metrics(logs, mode=mode, skipped=skipped)

    metrics = asyncio.run(_run_async())
    metrics["logs_path"] = str(output_dir / "end2end_logs.jsonl")
    write_jsonl(output_dir / "end2end_logs.jsonl", logs)
    write_json(output_dir / "end2end_metrics.json", metrics)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate end-to-end benchmark tasks.")
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR / f"end2end_{now_ts()}")
    parser.add_argument("--mode", choices=["router", "tool"], default="router")
    parser.add_argument("--disable-file-analyzer", action="store_true")
    parser.add_argument("--disable-file-context-injection", action="store_true")
    parser.add_argument("--disable-executor-standardization", action="store_true")
    parser.add_argument("--macro-modes", default="direct,ai,fuzzy")
    parser.add_argument("--only-task")
    parser.add_argument("--category")
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
        category=args.category,
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
