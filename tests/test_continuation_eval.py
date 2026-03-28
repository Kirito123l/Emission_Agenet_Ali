"""Tests for continuation prompt calibration and evaluation harness."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import List

from config import get_config
from core.plan import ExecutionPlan, PlanStatus, PlanStep, PlanStepStatus
from core.router import UnifiedRouter
from evaluation.eval_continuation import ContinuationExecutionMode, run_continuation_evaluation
from services.llm_client import LLMResponse, ToolCall


def _make_router() -> UnifiedRouter:
    router = object.__new__(UnifiedRouter)
    router.session_id = "continuation-eval-test"
    router.runtime_config = get_config()
    router.memory = SimpleNamespace(get_fact_memory=lambda: {}, get_working_memory=lambda: [])
    router.context_store = None
    router._live_continuation_bundle = {
        "plan": None,
        "repair_history": [],
        "blocked_info": None,
        "file_path": None,
        "latest_repair_summary": None,
        "residual_plan_summary": None,
    }
    return router


def _write_cases(tmp_path: Path) -> Path:
    cases = [
        {
            "case_id": "repair_case",
            "category": "repair_applied_continue",
            "description": "goal-heavy should over-focus on rendering while next-step-heavy should focus on dispersion",
            "prior_state": {
                "plan": {
                    "goal": "Compute dispersion and render a hotspot map",
                    "status": "partial",
                    "steps": [
                        {"step_id": "s1", "tool_name": "calculate_macro_emission", "produces": ["emission"], "status": "completed"},
                        {"step_id": "repair_s1", "tool_name": "calculate_dispersion", "depends_on": ["emission"], "produces": ["dispersion"], "status": "ready"},
                        {"step_id": "s3", "tool_name": "analyze_hotspots", "depends_on": ["dispersion"], "produces": ["hotspot"], "status": "pending"},
                        {"step_id": "s4", "tool_name": "render_spatial_map", "depends_on": ["hotspot"], "argument_hints": {"layer_type": "hotspot"}, "status": "pending"},
                    ],
                },
                "repair_history": [
                    {
                        "trigger_type": "dependency_blocked",
                        "trigger_reason": "Need hotspot context before rendering the hotspot layer.",
                        "action_type": "REPLACE_STEP",
                        "target_step_id": "s2",
                        "affected_step_ids": ["s2", "repair_s1"],
                        "planner_notes": "Replace the blocked hotspot render step with a dispersion recovery step.",
                        "is_applicable": True,
                        "patch": {
                            "target_step_id": "s2",
                            "replacement_step": {
                                "step_id": "repair_s1",
                                "tool_name": "calculate_dispersion",
                                "depends_on": ["emission"],
                                "produces": ["dispersion"],
                            },
                        },
                    }
                ],
                "blocked_info": {
                    "tool_name": "render_spatial_map",
                    "message": "Cannot execute render_spatial_map; prerequisite validation failed (missing=['hotspot']).",
                    "missing_tokens": ["hotspot"],
                },
                "available_tokens": ["emission"],
            },
            "current_user_input": "继续",
            "expected_continuation_decision": True,
            "expected_new_task_override": False,
            "expected_next_tool": "calculate_dispersion",
            "expected_trace_markers": ["plan_continuation_decided", "plan_continuation_injected"],
        },
        {
            "case_id": "new_task_case",
            "category": "explicit_new_task_override",
            "description": "new task override should skip continuation",
            "prior_state": {
                "plan": {
                    "goal": "Compute dispersion and render a hotspot map",
                    "status": "partial",
                    "steps": [
                        {"step_id": "s1", "tool_name": "calculate_macro_emission", "produces": ["emission"], "status": "completed"},
                        {"step_id": "repair_s1", "tool_name": "calculate_dispersion", "depends_on": ["emission"], "produces": ["dispersion"], "status": "ready"},
                    ],
                },
                "repair_history": [],
                "blocked_info": None,
                "available_tokens": ["emission"],
            },
            "current_user_input": "换个任务，直接回答这个新问题",
            "expected_continuation_decision": False,
            "expected_new_task_override": True,
            "expected_next_tool": None,
            "expected_trace_markers": ["plan_continuation_skipped"],
        },
    ]
    path = tmp_path / "continuation_cases.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for case in cases:
            fh.write(json.dumps(case, ensure_ascii=False) + "\n")
    return path


class _FakeLiveLLM:
    def __init__(
        self,
        *,
        selected_tool: str | None = "calculate_dispersion",
        temperature: float = 0.0,
        seed: int | None = None,
        failure_message: str | None = None,
        return_direct_answer: bool = False,
    ) -> None:
        self.selected_tool = selected_tool
        self.temperature = temperature
        self.seed = seed
        self.failure_message = failure_message
        self.return_direct_answer = return_direct_answer
        self.calls: List[dict] = []

    async def chat_with_tools(self, *, messages, tools, system, temperature=None, seed=None):
        self.calls.append(
            {
                "messages": messages,
                "tools": tools,
                "system": system,
                "temperature": temperature,
                "seed": seed,
            }
        )
        if self.failure_message:
            raise RuntimeError(self.failure_message)
        if self.return_direct_answer or self.selected_tool is None:
            return LLMResponse(content="live model direct answer without tool")
        return LLMResponse(
            content=f"live model selected {self.selected_tool}",
            tool_calls=[
                ToolCall(
                    id="live-tool-call",
                    name=self.selected_tool,
                    arguments={},
                )
            ],
        )

    async def chat(self, *args, **kwargs):
        return LLMResponse(content="unused")

    async def chat_json(self, *args, **kwargs):
        return {}


def _live_factory(instances: List[_FakeLiveLLM], **factory_kwargs):
    def _factory(*, temperature: float, seed: int | None):
        llm = _FakeLiveLLM(
            temperature=temperature,
            seed=seed,
            **factory_kwargs,
        )
        instances.append(llm)
        return llm

    return _factory


def test_continuation_prompt_variants_change_summary_emphasis():
    router = _make_router()
    plan = ExecutionPlan(
        goal="Compute dispersion and render a hotspot map",
        steps=[
            PlanStep(step_id="s1", tool_name="calculate_macro_emission", status=PlanStepStatus.COMPLETED),
            PlanStep(step_id="repair_s1", tool_name="calculate_dispersion", status=PlanStepStatus.READY),
            PlanStep(
                step_id="s2",
                tool_name="render_spatial_map",
                argument_hints={"layer_type": "hotspot"},
                status=PlanStepStatus.PENDING,
            ),
        ],
        status=PlanStatus.PARTIAL,
    )

    goal_heavy = router._build_residual_plan_summary_for_prompt(
        plan,
        available_tokens=["emission"],
        latest_repair_summary="REPLACE_STEP: replace blocked hotspot render with dispersion.",
        blocked_info={"message": "Cannot execute render_spatial_map; prerequisite validation failed."},
        variant="goal_heavy",
    )
    next_step_heavy = router._build_residual_plan_summary_for_prompt(
        plan,
        available_tokens=["emission"],
        latest_repair_summary="REPLACE_STEP: replace blocked hotspot render with dispersion.",
        blocked_info={"message": "Cannot execute render_spatial_map; prerequisite validation failed."},
        variant="next_step_heavy",
    )
    balanced = router._build_residual_plan_summary_for_prompt(
        plan,
        available_tokens=["emission"],
        latest_repair_summary="REPLACE_STEP: replace blocked hotspot render with dispersion.",
        blocked_info={"message": "Cannot execute render_spatial_map; prerequisite validation failed."},
        variant="balanced_repair_aware",
    )

    assert "variant=goal_heavy" in goal_heavy
    assert "Residual next-step hint: repair_s1 -> calculate_dispersion" in goal_heavy
    assert "Immediate next pending step (highest priority): repair_s1 -> calculate_dispersion" in next_step_heavy
    assert "Tool-selection rule: if the user is continuing the same workflow" in next_step_heavy
    assert "variant=balanced_repair_aware" in balanced
    assert "Latest repair summary: REPLACE_STEP: replace blocked hotspot render with dispersion." in balanced


def test_run_continuation_evaluation_writes_outputs_and_compares_variants(tmp_path):
    samples_path = _write_cases(tmp_path)
    output_dir = tmp_path / "continuation_eval"

    summary = run_continuation_evaluation(
        samples_path=samples_path,
        output_dir=output_dir,
        variants=["goal_heavy", "next_step_heavy", "balanced_repair_aware"],
    )

    assert summary["task"] == "continuation"
    assert set(summary["variants"].keys()) == {"goal_heavy", "next_step_heavy", "balanced_repair_aware"}
    assert (output_dir / "continuation_variant_comparison.json").exists()
    assert (output_dir / "continuation_variant_comparison.md").exists()

    goal_metrics = summary["variants"]["goal_heavy"]["metrics"]
    next_metrics = summary["variants"]["next_step_heavy"]["metrics"]
    balanced_metrics = summary["variants"]["balanced_repair_aware"]["metrics"]

    assert next_metrics["next_step_alignment_rate"] >= goal_metrics["next_step_alignment_rate"]
    assert balanced_metrics["continuation_decision_accuracy"] == 1.0
    assert (output_dir / "goal_heavy" / "continuation_case_results.jsonl").exists()
    assert (output_dir / "next_step_heavy" / "continuation_summary.md").exists()


def test_goal_heavy_variant_can_increase_blocked_after_continuation_rate(tmp_path):
    samples_path = _write_cases(tmp_path)
    output_dir = tmp_path / "continuation_eval"

    summary = run_continuation_evaluation(
        samples_path=samples_path,
        output_dir=output_dir,
        variants=["goal_heavy"],
    )

    metrics = summary["variants"]["goal_heavy"]["metrics"]
    assert metrics["blocked_after_continuation_rate"] >= 0.0

    result_path = output_dir / "goal_heavy" / "continuation_case_results.jsonl"
    rows = [json.loads(line) for line in result_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    repair_case = next(row for row in rows if row["case_id"] == "repair_case")
    assert repair_case["trace_completeness"] == 1.0
    assert "plan_continuation_injected" in repair_case["observed_trace_markers"]


def test_execution_mode_switching_and_schema_compatibility(tmp_path):
    samples_path = _write_cases(tmp_path)
    output_dir = tmp_path / "continuation_eval_modes"
    live_instances: List[_FakeLiveLLM] = []

    summary = run_continuation_evaluation(
        samples_path=samples_path,
        output_dir=output_dir,
        variants=["balanced_repair_aware"],
        execution_modes=[
            ContinuationExecutionMode.DETERMINISTIC.value,
            ContinuationExecutionMode.LIVE_MODEL.value,
        ],
        live_llm_factory=_live_factory(live_instances, selected_tool="calculate_dispersion"),
    )

    assert set(summary["execution_modes"].keys()) == {"deterministic", "live_model"}
    assert live_instances
    assert summary["mode_comparison"]["recommended_live_model_variant"] == "balanced_repair_aware"
    assert (output_dir / "continuation_mode_comparison.json").exists()
    assert (output_dir / "continuation_mode_comparison.md").exists()

    det_rows = [
        json.loads(line)
        for line in (output_dir / "deterministic" / "balanced_repair_aware" / "continuation_case_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    live_rows = [
        json.loads(line)
        for line in (output_dir / "live_model" / "balanced_repair_aware" / "continuation_case_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]

    assert {row["execution_mode"] for row in det_rows} == {"deterministic"}
    assert {row["execution_mode"] for row in live_rows} == {"live_model"}
    assert set(det_rows[0].keys()) == set(live_rows[0].keys())
    assert "failure_type" in live_rows[0]
    assert "trace_ok" in live_rows[0]


def test_mode_comparison_aggregation_tracks_deterministic_vs_live_gaps(tmp_path):
    samples_path = _write_cases(tmp_path)
    output_dir = tmp_path / "continuation_eval_compare"

    summary = run_continuation_evaluation(
        samples_path=samples_path,
        output_dir=output_dir,
        variants=["goal_heavy", "balanced_repair_aware"],
        execution_modes=["deterministic", "live_model"],
        live_llm_factory=_live_factory([], selected_tool="calculate_dispersion"),
    )

    comparison = summary["mode_comparison"]
    assert "goal_heavy" in comparison["variants"]
    assert "balanced_repair_aware" in comparison["variants"]
    assert "metric_gaps" in comparison["variants"]["balanced_repair_aware"]
    assert isinstance(comparison["variants"]["balanced_repair_aware"]["largest_category_gaps"], list)
    assert (output_dir / "deterministic" / "continuation_variant_comparison.json").exists()
    assert (output_dir / "live_model" / "continuation_variant_comparison.md").exists()


def test_live_model_failure_recording_does_not_crash_runner(tmp_path):
    samples_path = _write_cases(tmp_path)
    output_dir = tmp_path / "continuation_eval_live_failure"

    summary = run_continuation_evaluation(
        samples_path=samples_path,
        output_dir=output_dir,
        variants=["balanced_repair_aware"],
        execution_modes=["live_model"],
        live_llm_factory=_live_factory([], failure_message="connection error to live model"),
    )

    metrics = summary["execution_modes"]["live_model"]["variants"]["balanced_repair_aware"]["metrics"]
    rows = [
        json.loads(line)
        for line in (output_dir / "live_model" / "balanced_repair_aware" / "continuation_case_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    repair_case = next(row for row in rows if row["case_id"] == "repair_case")

    assert metrics["failure_count"] >= 1
    assert metrics["failure_counts"]["llm_call_failure"] >= 1
    assert repair_case["failure_type"] == "llm_call_failure"
    assert "connection error" in repair_case["failure_message"]


def test_live_model_no_tool_selected_is_recorded_as_failure(tmp_path):
    samples_path = _write_cases(tmp_path)
    output_dir = tmp_path / "continuation_eval_live_no_tool"

    run_continuation_evaluation(
        samples_path=samples_path,
        output_dir=output_dir,
        variants=["balanced_repair_aware"],
        execution_modes=["live_model"],
        live_llm_factory=_live_factory([], return_direct_answer=True),
    )

    rows = [
        json.loads(line)
        for line in (output_dir / "live_model" / "balanced_repair_aware" / "continuation_case_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    repair_case = next(row for row in rows if row["case_id"] == "repair_case")

    assert repair_case["failure_type"] == "unexpected_direct_answer"
    assert "direct answer" in repair_case["failure_message"]
    assert repair_case["actual_next_tool"] is None


def test_live_model_backend_captures_trace_and_first_step_alignment(tmp_path):
    samples_path = _write_cases(tmp_path)
    output_dir = tmp_path / "continuation_eval_live_trace"
    live_instances: List[_FakeLiveLLM] = []

    summary = run_continuation_evaluation(
        samples_path=samples_path,
        output_dir=output_dir,
        variants=["balanced_repair_aware"],
        execution_modes=["live_model"],
        live_model_temperature=0.0,
        live_model_seed=7,
        live_llm_factory=_live_factory(live_instances, selected_tool="calculate_dispersion"),
    )

    rows = [
        json.loads(line)
        for line in (output_dir / "live_model" / "balanced_repair_aware" / "continuation_case_results.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    repair_case = next(row for row in rows if row["case_id"] == "repair_case")

    assert live_instances and live_instances[0].calls
    assert live_instances[0].temperature == 0.0
    assert live_instances[0].seed == 7
    assert repair_case["actual_next_tool"] == "calculate_dispersion"
    assert repair_case["next_step_alignment"] is True
    assert "plan_continuation_decided" in repair_case["observed_trace_markers"]
    assert "plan_continuation_injected" in repair_case["observed_trace_markers"]
    assert summary["execution_modes"]["live_model"]["variants"]["balanced_repair_aware"]["metrics"]["failure_count"] == 0
