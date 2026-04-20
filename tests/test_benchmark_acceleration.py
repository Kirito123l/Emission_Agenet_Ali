from __future__ import annotations

import json
import time
from contextlib import nullcontext
from pathlib import Path

from evaluation import eval_end2end as mod
from evaluation.run_oasc_matrix import _resolve_groups
from evaluation.tool_cache import ToolResultCache


def test_smoke_subset_marks_30_tasks_and_covers_all_categories():
    rows = [
        json.loads(line)
        for line in Path("evaluation/benchmarks/end2end_tasks.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    smoke = [row for row in rows if row.get("smoke")]
    categories = {row["category"] for row in smoke}

    assert len(smoke) == 30
    assert len(categories) == 9
    for category in categories:
        assert sum(1 for row in smoke if row["category"] == category) >= 3


def test_tool_result_cache_hit_miss_cycle(tmp_path: Path):
    cache = ToolResultCache(cache_dir=tmp_path / "tool_cache", enabled=True, project_root=Path.cwd())
    args = {"pollutants": ["CO2"], "model_year": 2020}
    result = {"success": True, "summary": "ok", "data": {"value": 1}}

    assert cache.get("query_emission_factors", None, args) is None
    cache.put("query_emission_factors", None, args, result)
    cached = cache.get("query_emission_factors", None, args)

    assert cached == result
    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1


def test_parallel_runner_keeps_sorted_logs_and_consistent_metrics(monkeypatch, tmp_path: Path):
    samples_path = tmp_path / "samples.jsonl"
    samples = [
        {
            "id": "task_b",
            "category": "simple",
            "description": "b",
            "user_message": "b",
            "expected_tool_chain": ["query_emission_factors"],
            "expected_params": {},
            "success_criteria": {},
            "smoke": True,
        },
        {
            "id": "task_a",
            "category": "simple",
            "description": "a",
            "user_message": "a",
            "expected_tool_chain": ["query_emission_factors"],
            "expected_params": {},
            "success_criteria": {},
            "smoke": True,
        },
        {
            "id": "task_c",
            "category": "simple",
            "description": "c",
            "user_message": "c",
            "expected_tool_chain": ["query_emission_factors"],
            "expected_params": {},
            "success_criteria": {},
            "smoke": False,
        },
    ]
    samples_path.write_text(
        "\n".join(json.dumps(sample, ensure_ascii=False) for sample in samples) + "\n",
        encoding="utf-8",
    )

    delays = {"task_a": 0.03, "task_b": 0.01, "task_c": 0.02}

    def fake_single_task(task, *, mode, output_dir, enable_file_analyzer, resolved_task_timeout_sec):
        time.sleep(delays[task["id"]])
        return {
            "task": task,
            "executed_tool_calls": [
                {
                    "name": "query_emission_factors",
                    "arguments": {"pollutants": ["CO2"]},
                    "result": {"success": True, "summary": "ok", "data": {"value": 1}},
                }
            ],
            "response_payload": {"text": "done", "data": {"value": 1}},
            "trace_payload": None,
            "error_message": None,
            "duration_ms": 10.0,
            "file_analysis": None,
            "infrastructure_status": mod.InfrastructureErrorType.OK,
            "retry_count": 0,
        }

    monkeypatch.setattr(mod, "_run_single_task_sync", fake_single_task)
    monkeypatch.setattr(mod, "runtime_overrides", lambda **kwargs: nullcontext())
    monkeypatch.setattr(
        mod,
        "_evaluation_runtime_hooks",
        lambda **kwargs: nullcontext(),
    )
    monkeypatch.setattr(mod, "rebuild_tool_registry", lambda: None)

    serial_dir = tmp_path / "serial"
    parallel_dir = tmp_path / "parallel"
    serial = mod.run_end2end_evaluation(
        samples_path=samples_path,
        output_dir=serial_dir,
        parallel=1,
        cache_enabled=False,
    )
    parallel = mod.run_end2end_evaluation(
        samples_path=samples_path,
        output_dir=parallel_dir,
        parallel=4,
        cache_enabled=False,
    )

    serial_logs = [
        json.loads(line)
        for line in (serial_dir / "end2end_logs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    parallel_logs = [
        json.loads(line)
        for line in (parallel_dir / "end2end_logs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert [row["task_id"] for row in parallel_logs] == ["task_a", "task_b", "task_c"]
    assert serial["completion_rate"] == parallel["completion_rate"] == 1.0
    assert [row["actual"]["tool_chain"] for row in serial_logs] == [row["actual"]["tool_chain"] for row in parallel_logs]


def test_smoke_flag_filters_subset(monkeypatch, tmp_path: Path):
    samples_path = tmp_path / "samples.jsonl"
    samples = [
        {
            "id": "task_1",
            "category": "simple",
            "description": "1",
            "user_message": "1",
            "expected_tool_chain": ["query_emission_factors"],
            "expected_params": {},
            "success_criteria": {},
            "smoke": True,
        },
        {
            "id": "task_2",
            "category": "simple",
            "description": "2",
            "user_message": "2",
            "expected_tool_chain": ["query_emission_factors"],
            "expected_params": {},
            "success_criteria": {},
            "smoke": False,
        },
    ]
    samples_path.write_text(
        "\n".join(json.dumps(sample, ensure_ascii=False) for sample in samples) + "\n",
        encoding="utf-8",
    )

    def fake_single_task(task, *, mode, output_dir, enable_file_analyzer, resolved_task_timeout_sec):
        return {
            "task": task,
            "executed_tool_calls": [
                {
                    "name": "query_emission_factors",
                    "arguments": {"pollutants": ["CO2"]},
                    "result": {"success": True, "summary": "ok", "data": {"value": 1}},
                }
            ],
            "response_payload": {"text": "done", "data": {"value": 1}},
            "trace_payload": None,
            "error_message": None,
            "duration_ms": 1.0,
            "file_analysis": None,
            "infrastructure_status": mod.InfrastructureErrorType.OK,
            "retry_count": 0,
        }

    monkeypatch.setattr(mod, "_run_single_task_sync", fake_single_task)
    monkeypatch.setattr(mod, "runtime_overrides", lambda **kwargs: nullcontext())
    monkeypatch.setattr(mod, "_evaluation_runtime_hooks", lambda **kwargs: nullcontext())
    monkeypatch.setattr(mod, "rebuild_tool_registry", lambda: None)

    metrics = mod.run_end2end_evaluation(
        samples_path=samples_path,
        output_dir=tmp_path / "out",
        smoke=True,
        parallel=1,
        cache_enabled=False,
    )
    assert metrics["subset"] == "smoke"
    assert metrics["tasks"] == 1


def test_filter_categories_keeps_only_requested_categories(monkeypatch, tmp_path: Path):
    samples_path = tmp_path / "samples.jsonl"
    samples = [
        {
            "id": "task_1",
            "category": "simple",
            "description": "1",
            "user_message": "1",
            "expected_tool_chain": ["query_emission_factors"],
            "expected_params": {},
            "success_criteria": {},
            "smoke": True,
        },
        {
            "id": "task_2",
            "category": "ambiguous_colloquial",
            "description": "2",
            "user_message": "2",
            "expected_tool_chain": ["query_emission_factors"],
            "expected_params": {},
            "success_criteria": {},
            "smoke": True,
        },
    ]
    samples_path.write_text(
        "\n".join(json.dumps(sample, ensure_ascii=False) for sample in samples) + "\n",
        encoding="utf-8",
    )

    def fake_single_task(task, *, mode, output_dir, enable_file_analyzer, resolved_task_timeout_sec):
        return {
            "task": task,
            "executed_tool_calls": [
                {
                    "name": "query_emission_factors",
                    "arguments": {"pollutants": ["CO2"]},
                    "result": {"success": True, "summary": "ok", "data": {"value": 1}},
                }
            ],
            "response_payload": {"text": "done", "data": {"value": 1}},
            "trace_payload": None,
            "error_message": None,
            "duration_ms": 1.0,
            "file_analysis": None,
            "infrastructure_status": mod.InfrastructureErrorType.OK,
            "retry_count": 0,
        }

    monkeypatch.setattr(mod, "_run_single_task_sync", fake_single_task)
    monkeypatch.setattr(mod, "runtime_overrides", lambda **kwargs: nullcontext())
    monkeypatch.setattr(mod, "_evaluation_runtime_hooks", lambda **kwargs: nullcontext())
    monkeypatch.setattr(mod, "rebuild_tool_registry", lambda: None)

    metrics = mod.run_end2end_evaluation(
        samples_path=samples_path,
        output_dir=tmp_path / "out",
        filter_categories=["ambiguous_colloquial"],
        parallel=1,
        cache_enabled=False,
    )
    assert metrics["tasks"] == 1
    assert metrics["by_category"] == {
        "ambiguous_colloquial": {"tasks": 1, "success_rate": 1.0, "tool_accuracy": 1.0}
    }


def test_resolve_groups_filters_requested_names():
    groups = _resolve_groups("A,E")
    assert [group["name"] for group in groups] == ["A", "E"]


def test_resolve_groups_accepts_clarification_ablation_group():
    groups = _resolve_groups("G")
    assert [group["name"] for group in groups] == ["G"]
