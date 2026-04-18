from __future__ import annotations

import json
import json as json_module
from pathlib import Path

import pytest

from evaluation import eval_end2end as mod


@pytest.mark.anyio
async def test_failsafe_retries_transient_error_until_success():
    attempts = {"count": 0}

    async def operation():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("Connection error")
        return {"ok": True}

    result, status, retry_count, error = await mod._run_with_infrastructure_failsafe(
        operation,
        max_retries=3,
        retry_delay_sec=0.0,
    )

    assert result == {"ok": True}
    assert status == mod.InfrastructureErrorType.TRANSIENT_RETRIED
    assert retry_count == 2
    assert error is None


@pytest.mark.anyio
async def test_failsafe_classifies_billing_and_does_not_retry():
    attempts = {"count": 0}

    async def operation():
        attempts["count"] += 1
        raise RuntimeError("Arrearage: account overdue")

    result, status, retry_count, error = await mod._run_with_infrastructure_failsafe(
        operation,
        max_retries=3,
        retry_delay_sec=0.0,
    )

    assert result is None
    assert status == mod.InfrastructureErrorType.BILLING_FAILED
    assert retry_count == 0
    assert "Arrearage" in error["message"]
    assert attempts["count"] == 1


def test_aggregate_metrics_contains_health_summary_and_integrity():
    logs = [
        {
            "success": True,
            "category": "simple",
            "infrastructure_status": "ok",
            "expected": {"tool_chain": ["query_emission_factors"]},
            "actual": {
                "tool_chain_match": True,
                "criteria": {"params_legal": True, "result_has_data": True},
            },
        },
        {
            "success": False,
            "category": "simple",
            "infrastructure_status": "transient_retried",
            "expected": {"tool_chain": ["query_emission_factors"]},
            "actual": {
                "tool_chain_match": False,
                "criteria": {"params_legal": False, "result_has_data": False},
            },
        },
    ]

    metrics = mod._aggregate_metrics(logs, mode="router", skipped=0, run_status="completed")

    assert metrics["run_status"] == "completed"
    assert metrics["infrastructure_health"]["ok"] == 1
    assert metrics["infrastructure_health"]["transient_retried"] == 1
    assert metrics["data_integrity"] == "contaminated"


def test_aggregate_metrics_marks_clean_when_transient_ratio_below_threshold():
    logs = []
    for _ in range(20):
        logs.append(
            {
                "success": True,
                "category": "simple",
                "infrastructure_status": "ok",
                "expected": {"tool_chain": ["query_emission_factors"]},
                "actual": {
                    "tool_chain_match": True,
                    "criteria": {"params_legal": True, "result_has_data": True},
                },
            }
        )
    logs.append(
        {
            "success": True,
            "category": "simple",
            "infrastructure_status": "transient_retried",
            "expected": {"tool_chain": ["query_emission_factors"]},
            "actual": {
                "tool_chain_match": True,
                "criteria": {"params_legal": True, "result_has_data": True},
            },
        }
    )

    metrics = mod._aggregate_metrics(logs, mode="router", skipped=0, run_status="completed")

    assert metrics["data_integrity"] == "clean"


def test_run_end2end_evaluation_aborts_on_billing_failure(monkeypatch, tmp_path):
    samples_path = tmp_path / "samples.jsonl"
    samples_path.write_text(
        json.dumps(
            {
                "id": "t1",
                "category": "simple",
                "description": "billing fail test",
                "user_message": "hello",
                "expected_tool_chain": ["query_knowledge"],
                "expected_params": {},
                "success_criteria": {},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"

    async def fake_failsafe(*args, **kwargs):
        return None, mod.InfrastructureErrorType.BILLING_FAILED, 0, "Arrearage"

    monkeypatch.setattr(mod, "_run_with_infrastructure_failsafe", fake_failsafe)
    monkeypatch.setattr(mod, "rebuild_tool_registry", lambda: None)

    class DummyAnalyzer:
        async def execute(self, file_path: str):
            return type("Result", (), {"success": False, "data": None})()

    class DummyExecutor:
        pass

    monkeypatch.setattr(mod, "FileAnalyzerTool", lambda: DummyAnalyzer())
    monkeypatch.setattr(mod, "ToolExecutor", lambda: DummyExecutor())

    metrics = mod.run_end2end_evaluation(
        samples_path=samples_path,
        output_dir=output_dir,
        mode="router",
        enable_file_analyzer=False,
    )

    assert metrics["run_status"] == "aborted_billing"
    assert metrics["data_integrity"] == "contaminated"
    assert metrics["infrastructure_health"]["billing_failed"] == 1
    logs = [json.loads(line) for line in (output_dir / "end2end_logs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(logs) == 1
    assert logs[0]["infrastructure_status"] == "billing_failed"


@pytest.mark.anyio
async def test_failsafe_marks_value_error_as_execution_error():
    async def operation():
        raise ValueError("bad production value")

    result, status, retry_count, error = await mod._run_with_infrastructure_failsafe(
        operation,
        max_retries=3,
        retry_delay_sec=0.0,
    )

    assert result is None
    assert status == mod.InfrastructureErrorType.OK
    assert retry_count == 0
    assert error["type"] == "ValueError"
    assert "bad production value" in error["message"]
    assert "Traceback" in error["traceback"]


@pytest.mark.anyio
async def test_failsafe_marks_json_decode_error_as_execution_error():
    async def operation():
        raise json_module.JSONDecodeError("bad json", "not-json", 0)

    result, status, retry_count, error = await mod._run_with_infrastructure_failsafe(
        operation,
        max_retries=3,
        retry_delay_sec=0.0,
    )

    assert result is None
    assert status == mod.InfrastructureErrorType.OK
    assert retry_count == 0
    assert error["type"] == "JSONDecodeError"
    assert "Traceback" in error["traceback"]


def test_task_result_persists_execution_error_fields():
    record = mod._build_task_result(
        {
            "id": "t1",
            "category": "simple",
            "description": "execution error",
            "user_message": "hello",
            "test_file": None,
            "expected_tool_chain": ["query_emission_factors"],
            "expected_params": {},
            "success_criteria": {},
            "__legacy_expected_success": None,
            "expected_outputs": {},
        },
        executed_tool_calls=[],
        response_payload={},
        trace_payload=None,
        error_message="bad production value",
        duration_ms=1.0,
        file_analysis=None,
        execution_error={
            "repr": "ValueError('bad production value')",
            "message": "bad production value",
            "type": "ValueError",
            "traceback": "Traceback...",
        },
    )

    assert record["execution_error"] == "ValueError('bad production value')"
    assert record["execution_error_type"] == "ValueError"
    assert record["execution_traceback"] == "Traceback..."
