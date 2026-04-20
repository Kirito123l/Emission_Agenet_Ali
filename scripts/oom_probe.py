#!/usr/bin/env python3
"""One-off held-out has_file OOM diagnostics.

This script is intentionally outside production/evaluator code. It wraps the
existing end-to-end evaluator to record process RSS around each task and, in a
separate mode, collect a tracemalloc diff for one selected task.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import signal
import sys
import threading
import time
import tracemalloc
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_HELD_OUT = PROJECT_ROOT / "evaluation" / "benchmarks" / "held_out_tasks.jsonl"
DEFAULT_SUBSET = Path("/tmp/held_out_hasfile_only.jsonl")
DEFAULT_RSS_LOG = Path("/tmp/oom_rss.log")
DEFAULT_TASK_RECORDS = PROJECT_ROOT / "evaluation" / "diagnostics" / "oom_task_a_records.jsonl"
DEFAULT_TRACE_REPORT = PROJECT_ROOT / "evaluation" / "diagnostics" / "oom_tracemalloc_task.json"
RSS_LIMIT_MB = 8192.0
CURRENT_STAGE = "startup"


A_GROUP_ENV = {
    "ENABLE_AO_AWARE_MEMORY": "false",
    "ENABLE_SESSION_STATE_BLOCK": "false",
    "ENABLE_AO_CLASSIFIER_RULE_LAYER": "false",
    "ENABLE_AO_CLASSIFIER_LLM_LAYER": "false",
    "ENABLE_AO_BLOCK_INJECTION": "false",
    "ENABLE_AO_PERSISTENT_FACTS": "false",
    "ENABLE_GOVERNED_ROUTER": "false",
    "ENABLE_CLARIFICATION_CONTRACT": "false",
}


def _rss_mb() -> float:
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    return float(parts[1]) / 1024.0
    except OSError:
        return 0.0
    return 0.0


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_hasfile_subset(samples_path: Path, subset_path: Path) -> List[Dict[str, Any]]:
    tasks = [row for row in _load_jsonl(samples_path) if row.get("has_file")]
    subset_path.parent.mkdir(parents=True, exist_ok=True)
    with subset_path.open("w", encoding="utf-8") as handle:
        for row in tasks:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return tasks


def _start_rss_monitor(path: Path, stop_event: threading.Event, limit_mb: float) -> threading.Thread:
    path.parent.mkdir(parents=True, exist_ok=True)

    def _loop() -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"# oom_probe rss monitor start {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            handle.flush()
            while not stop_event.is_set():
                rss = _rss_mb()
                handle.write(f"{time.strftime('%H:%M:%S')} {os.getpid()} {rss:.1f}MB {CURRENT_STAGE}\n")
                handle.flush()
                if rss >= limit_mb:
                    handle.write(f"# RSS_LIMIT_EXCEEDED {rss:.1f}MB >= {limit_mb:.1f}MB\n")
                    handle.flush()
                    os.kill(os.getpid(), signal.SIGTERM)
                    return
                stop_event.wait(5.0)

    thread = threading.Thread(target=_loop, name="oom-rss-monitor", daemon=True)
    thread.start()
    return thread


def _set_a_group_env() -> None:
    os.environ.update(A_GROUP_ENV)
    os.environ["PYTHONUNBUFFERED"] = "1"


def _run_task_a(args: argparse.Namespace) -> int:
    _set_a_group_env()
    tasks = _write_hasfile_subset(args.samples, args.subset)
    print(f"Wrote {len(tasks)} has_file tasks to {args.subset}")

    from evaluation import eval_end2end

    records: List[Dict[str, Any]] = []
    original = eval_end2end._run_single_task_sync
    stop_event = threading.Event()
    _start_rss_monitor(args.rss_log, stop_event, args.rss_limit_mb)

    def wrapped(task: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        task_id = str(task.get("id") or "unknown")
        category = str(task.get("category") or "")
        test_file = str(task.get("test_file") or "")
        start_rss = _rss_mb()
        started = time.perf_counter()
        status = "ok"
        error = None
        try:
            return original(task, **kwargs)
        except BaseException as exc:  # noqa: BLE001
            status = "exception"
            error = repr(exc)
            raise
        finally:
            after_task_rss = _rss_mb()
            collected = gc.collect()
            after_gc_rss = _rss_mb()
            record = {
                "task_id": task_id,
                "category": category,
                "test_file": test_file,
                "status": status,
                "error": error,
                "duration_sec": round(time.perf_counter() - started, 3),
                "rss_before_mb": round(start_rss, 1),
                "rss_after_task_mb": round(after_task_rss, 1),
                "rss_after_gc_mb": round(after_gc_rss, 1),
                "rss_delta_task_mb": round(after_task_rss - start_rss, 1),
                "rss_delta_after_gc_mb": round(after_gc_rss - start_rss, 1),
                "gc_collected": int(collected),
            }
            records.append(record)
            _write_jsonl(args.records, records)
            print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)
            if after_gc_rss >= args.rss_limit_mb:
                raise SystemExit(f"RSS limit exceeded after {task_id}: {after_gc_rss:.1f}MB")

    eval_end2end._run_single_task_sync = wrapped
    try:
        metrics = eval_end2end.run_end2end_evaluation(
            samples_path=args.subset,
            output_dir=args.output_dir,
            mode="router",
            parallel=1,
            qps_limit=15.0,
            cache_enabled=True,
            task_timeout_sec=args.task_timeout_sec,
        )
        print(json.dumps({"metrics": metrics, "records_path": str(args.records)}, ensure_ascii=False, indent=2))
        return 0
    finally:
        stop_event.set()
        eval_end2end._run_single_task_sync = original
        _write_jsonl(args.records, records)


def _run_trace_task(args: argparse.Namespace) -> int:
    _set_a_group_env()
    rows = _load_jsonl(args.samples)
    selected = [row for row in rows if row.get("id") == args.task_id]
    if not selected:
        raise SystemExit(f"Task not found: {args.task_id}")
    single = Path("/tmp") / f"oom_trace_{args.task_id}.jsonl"
    with single.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(selected[0], ensure_ascii=False) + "\n")

    from evaluation import eval_end2end

    original = eval_end2end._run_single_task_sync
    trace_rows: List[Dict[str, Any]] = []
    stop_event = threading.Event()
    _start_rss_monitor(args.rss_log, stop_event, args.rss_limit_mb)

    def wrapped(task: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        gc.collect()
        rss_before = _rss_mb()
        tracemalloc.start(25)
        snap_before = tracemalloc.take_snapshot()
        try:
            return original(task, **kwargs)
        finally:
            snap_after = tracemalloc.take_snapshot()
            rss_after = _rss_mb()
            collected = gc.collect()
            rss_after_gc = _rss_mb()
            stats = snap_after.compare_to(snap_before, "lineno")[:20]
            trace_rows.append(
                {
                    "task_id": task.get("id"),
                    "rss_before_mb": round(rss_before, 1),
                    "rss_after_task_mb": round(rss_after, 1),
                    "rss_after_gc_mb": round(rss_after_gc, 1),
                    "gc_collected": int(collected),
                    "top_allocations": [
                        {
                            "trace": str(stat.traceback),
                            "size_diff_mb": round(stat.size_diff / 1024 / 1024, 3),
                            "count_diff": stat.count_diff,
                        }
                        for stat in stats
                    ],
                }
            )
            tracemalloc.stop()

    eval_end2end._run_single_task_sync = wrapped
    try:
        metrics = eval_end2end.run_end2end_evaluation(
            samples_path=single,
            output_dir=args.output_dir,
            mode="router",
            parallel=1,
            qps_limit=15.0,
            cache_enabled=True,
            task_timeout_sec=args.task_timeout_sec,
        )
        payload = {"metrics": metrics, "trace": trace_rows}
        args.trace_report.parent.mkdir(parents=True, exist_ok=True)
        args.trace_report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"trace_report": str(args.trace_report), "metrics": metrics}, ensure_ascii=False, indent=2))
        return 0
    finally:
        stop_event.set()
        eval_end2end._run_single_task_sync = original


def _run_stage_task(args: argparse.Namespace) -> int:
    _set_a_group_env()
    rows = _load_jsonl(args.samples)
    selected = [row for row in rows if row.get("id") == args.task_id]
    if not selected:
        raise SystemExit(f"Task not found: {args.task_id}")
    single = Path("/tmp") / f"oom_stage_{args.task_id}.jsonl"
    with single.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(selected[0], ensure_ascii=False) + "\n")

    from evaluation import eval_end2end
    from core.executor import ToolExecutor
    from tools.file_analyzer import FileAnalyzerTool
    import calculators.dispersion as dispersion_module
    from calculators.dispersion import DispersionCalculator

    stage_rows: List[Dict[str, Any]] = []

    def set_stage(name: str) -> None:
        global CURRENT_STAGE
        CURRENT_STAGE = name
        row = {"ts": time.strftime("%H:%M:%S"), "stage": name, "rss_mb": round(_rss_mb(), 1)}
        stage_rows.append(row)
        args.stage_report.parent.mkdir(parents=True, exist_ok=True)
        args.stage_report.write_text(json.dumps(stage_rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(row, ensure_ascii=False, sort_keys=True), flush=True)

    original_task = eval_end2end._run_single_task_sync
    original_tool_execute = ToolExecutor.execute
    original_file_execute = FileAnalyzerTool.execute
    original_calc = DispersionCalculator.calculate
    original_segment = DispersionCalculator._segment_roads
    original_receptors = DispersionCalculator._generate_receptors
    original_assemble = DispersionCalculator._assemble_result
    original_build_sources = DispersionCalculator._build_source_arrays
    original_process_met = DispersionCalculator._process_meteorology
    original_ensure_models = DispersionCalculator._ensure_models_loaded
    original_get_model = DispersionCalculator._get_or_load_model
    original_predict = dispersion_module.predict_time_series_xgb

    async def wrapped_tool_execute(self: Any, tool_name: str, arguments: Dict[str, Any], file_path: str = None) -> Dict[str, Any]:
        set_stage(f"tool:{tool_name}:before")
        try:
            return await original_tool_execute(self, tool_name, arguments, file_path=file_path)
        finally:
            set_stage(f"tool:{tool_name}:after")

    async def wrapped_file_execute(self: Any, **kwargs: Any) -> Any:
        set_stage("file_analyzer:before")
        try:
            return await original_file_execute(self, **kwargs)
        finally:
            set_stage("file_analyzer:after")

    def wrapped_calc(self: Any, *calc_args: Any, **calc_kwargs: Any) -> Dict[str, Any]:
        set_stage("dispersion.calculate:before")
        try:
            return original_calc(self, *calc_args, **calc_kwargs)
        finally:
            set_stage("dispersion.calculate:after")

    def wrapped_segment(self: Any, *stage_args: Any, **stage_kwargs: Any) -> Any:
        set_stage("dispersion._segment_roads:before")
        try:
            return original_segment(self, *stage_args, **stage_kwargs)
        finally:
            set_stage("dispersion._segment_roads:after")

    def wrapped_receptors(self: Any, *stage_args: Any, **stage_kwargs: Any) -> Any:
        set_stage("dispersion._generate_receptors:before")
        try:
            return original_receptors(self, *stage_args, **stage_kwargs)
        finally:
            set_stage("dispersion._generate_receptors:after")

    def wrapped_assemble(self: Any, *stage_args: Any, **stage_kwargs: Any) -> Any:
        set_stage("dispersion._assemble_result:before")
        try:
            return original_assemble(self, *stage_args, **stage_kwargs)
        finally:
            set_stage("dispersion._assemble_result:after")

    def wrapped_build_sources(self: Any, *stage_args: Any, **stage_kwargs: Any) -> Any:
        set_stage("dispersion._build_source_arrays:before")
        try:
            return original_build_sources(self, *stage_args, **stage_kwargs)
        finally:
            set_stage("dispersion._build_source_arrays:after")

    def wrapped_process_met(self: Any, *stage_args: Any, **stage_kwargs: Any) -> Any:
        set_stage("dispersion._process_meteorology:before")
        try:
            return original_process_met(self, *stage_args, **stage_kwargs)
        finally:
            set_stage("dispersion._process_meteorology:after")

    def wrapped_ensure_models(self: Any, *stage_args: Any, **stage_kwargs: Any) -> Any:
        set_stage("dispersion._ensure_models_loaded:before")
        try:
            return original_ensure_models(self, *stage_args, **stage_kwargs)
        finally:
            set_stage("dispersion._ensure_models_loaded:after")

    def wrapped_get_model(self: Any, *stage_args: Any, **stage_kwargs: Any) -> Any:
        set_stage(f"dispersion._get_or_load_model:{stage_args[0] if stage_args else 'unknown'}:before")
        try:
            return original_get_model(self, *stage_args, **stage_kwargs)
        finally:
            set_stage("dispersion._get_or_load_model:after")

    def wrapped_predict(*stage_args: Any, **stage_kwargs: Any) -> Any:
        try:
            receptors_x = stage_kwargs.get("receptors_x") if "receptors_x" in stage_kwargs else stage_args[1]
            sources = stage_kwargs.get("sources") if "sources" in stage_kwargs else stage_args[3]
            met = stage_kwargs.get("met") if "met" in stage_kwargs else stage_args[4]
            shape_note = (
                f"receptors={getattr(receptors_x, 'shape', ['?'])[0]},"
                f"sources_shape={getattr(sources, 'shape', '?')},"
                f"met_rows={len(met) if hasattr(met, '__len__') else '?'},"
                f"batch={stage_kwargs.get('batch_size')},"
                f"track={stage_kwargs.get('track_road_contributions')}"
            )
        except Exception:
            shape_note = "shape=unknown"
        set_stage(f"dispersion.predict_time_series_xgb:before:{shape_note}")
        try:
            return original_predict(*stage_args, **stage_kwargs)
        finally:
            set_stage("dispersion.predict_time_series_xgb:after")

    def wrapped_task(task: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        set_stage(f"task:{task.get('id')}:before")
        try:
            return original_task(task, **kwargs)
        finally:
            set_stage(f"task:{task.get('id')}:after")

    stop_event = threading.Event()
    _start_rss_monitor(args.rss_log, stop_event, args.rss_limit_mb)
    eval_end2end._run_single_task_sync = wrapped_task
    ToolExecutor.execute = wrapped_tool_execute
    FileAnalyzerTool.execute = wrapped_file_execute
    DispersionCalculator.calculate = wrapped_calc
    DispersionCalculator._segment_roads = wrapped_segment
    DispersionCalculator._generate_receptors = wrapped_receptors
    DispersionCalculator._assemble_result = wrapped_assemble
    DispersionCalculator._build_source_arrays = wrapped_build_sources
    DispersionCalculator._process_meteorology = wrapped_process_met
    DispersionCalculator._ensure_models_loaded = wrapped_ensure_models
    DispersionCalculator._get_or_load_model = wrapped_get_model
    dispersion_module.predict_time_series_xgb = wrapped_predict
    try:
        set_stage("eval:before")
        metrics = eval_end2end.run_end2end_evaluation(
            samples_path=single,
            output_dir=args.output_dir,
            mode="router",
            parallel=1,
            qps_limit=15.0,
            cache_enabled=True,
            task_timeout_sec=args.task_timeout_sec,
        )
        set_stage("eval:after")
        print(json.dumps({"stage_report": str(args.stage_report), "metrics": metrics}, ensure_ascii=False, indent=2))
        return 0
    finally:
        stop_event.set()
        eval_end2end._run_single_task_sync = original_task
        ToolExecutor.execute = original_tool_execute
        FileAnalyzerTool.execute = original_file_execute
        DispersionCalculator.calculate = original_calc
        DispersionCalculator._segment_roads = original_segment
        DispersionCalculator._generate_receptors = original_receptors
        DispersionCalculator._assemble_result = original_assemble
        DispersionCalculator._build_source_arrays = original_build_sources
        DispersionCalculator._process_meteorology = original_process_met
        DispersionCalculator._ensure_models_loaded = original_ensure_models
        DispersionCalculator._get_or_load_model = original_get_model
        dispersion_module.predict_time_series_xgb = original_predict


def main() -> None:
    parser = argparse.ArgumentParser(description="Held-out has_file OOM diagnostics.")
    sub = parser.add_subparsers(dest="command", required=True)

    task_a = sub.add_parser("task-a", help="Run has_file held-out tasks with RSS sampling only.")
    task_a.add_argument("--samples", type=Path, default=DEFAULT_HELD_OUT)
    task_a.add_argument("--subset", type=Path, default=DEFAULT_SUBSET)
    task_a.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "evaluation" / "results" / "oom_diag_hasfile_A")
    task_a.add_argument("--records", type=Path, default=DEFAULT_TASK_RECORDS)
    task_a.add_argument("--rss-log", type=Path, default=DEFAULT_RSS_LOG)
    task_a.add_argument("--rss-limit-mb", type=float, default=RSS_LIMIT_MB)
    task_a.add_argument("--task-timeout-sec", type=float, default=180.0)
    task_a.set_defaults(func=_run_task_a)

    trace_task = sub.add_parser("trace-task", help="Run one task with tracemalloc snapshots.")
    trace_task.add_argument("--samples", type=Path, default=DEFAULT_HELD_OUT)
    trace_task.add_argument("--task-id", required=True)
    trace_task.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "evaluation" / "results" / "oom_trace_task")
    trace_task.add_argument("--trace-report", type=Path, default=DEFAULT_TRACE_REPORT)
    trace_task.add_argument("--rss-log", type=Path, default=Path("/tmp/oom_trace_rss.log"))
    trace_task.add_argument("--rss-limit-mb", type=float, default=RSS_LIMIT_MB)
    trace_task.add_argument("--task-timeout-sec", type=float, default=180.0)
    trace_task.set_defaults(func=_run_trace_task)

    stage_task = sub.add_parser("stage-task", help="Run one task with RSS stage markers and no tracemalloc.")
    stage_task.add_argument("--samples", type=Path, default=DEFAULT_HELD_OUT)
    stage_task.add_argument("--task-id", required=True)
    stage_task.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "evaluation" / "results" / "oom_stage_task")
    stage_task.add_argument("--stage-report", type=Path, default=PROJECT_ROOT / "evaluation" / "diagnostics" / "oom_stage_task.json")
    stage_task.add_argument("--rss-log", type=Path, default=Path("/tmp/oom_stage_rss.log"))
    stage_task.add_argument("--rss-limit-mb", type=float, default=RSS_LIMIT_MB)
    stage_task.add_argument("--task-timeout-sec", type=float, default=180.0)
    stage_task.set_defaults(func=_run_stage_task)

    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
