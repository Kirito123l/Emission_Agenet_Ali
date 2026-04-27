from __future__ import annotations

from core.analytical_objective import AORelationship, ToolCallRecord
from core.ao_manager import AOManager
from core.constraint_violation_writer import ConstraintViolationWriter, ViolationRecord
from core.context_store import SessionContextStore
from core.memory import FactMemory
from core.reply import (
    AOStatusSummary,
    ClarificationRequest,
    ReplyContext,
    ReplyContextBuilder,
    ToolExecutionSummary,
)


def _violation_record() -> ViolationRecord:
    return ViolationRecord(
        violation_type="vehicle_road_compatibility",
        severity="reject",
        involved_params={"vehicle_type": "Motorcycle"},
        suggested_resolution="改用城市道路",
        timestamp="2026-04-25T10:00:00",
        source_turn=2,
    )


def test_reply_context_round_trips_valid_dict() -> None:
    context = ReplyContext(
        user_message="帮我算排放",
        router_text="router draft",
        tool_executions=[
            ToolExecutionSummary(
                tool_name="query_emission_factors",
                arguments={"vehicle_type": "Motorcycle"},
                success=True,
                summary="done",
            )
        ],
        violations=[_violation_record()],
        pending_clarifications=[
            ClarificationRequest(target_field="pollutants", reason="missing", options=["CO2"])
        ],
        ao_status=AOStatusSummary(state="active", objective="排放分析", completed_steps=["query"]),
        trace_highlights=[{"step_type": "tool_execution", "summary": "done"}],
        extra={"data_quality_report": {"row_count": 2}},
    )

    restored = ReplyContext.from_dict(context.to_dict())

    assert restored == context


def test_reply_context_rejects_unknown_top_level_field() -> None:
    payload = ReplyContext(user_message="u", router_text="r").to_dict()
    payload["typo"] = True

    try:
        ReplyContext.from_dict(payload)
    except ValueError as exc:
        assert "typo" in str(exc)
    else:
        raise AssertionError("ReplyContext.from_dict should reject unknown fields")


def test_reply_context_allows_arbitrary_extra_content() -> None:
    restored = ReplyContext.from_dict(
        {
            "user_message": "u",
            "router_text": "r",
            "extra": {"future_extension": {"nested": [1, 2, 3]}},
        }
    )

    assert restored.extra["future_extension"]["nested"] == [1, 2, 3]


def test_reply_context_child_dataclasses_are_strict() -> None:
    child_payloads = [
        (
            ToolExecutionSummary,
            {
                "tool_name": "query_knowledge",
                "arguments": {},
                "success": True,
                "summary": "ok",
                "unknown": "bad",
            },
        ),
        (
            ClarificationRequest,
            {
                "target_field": "pollutants",
                "reason": "missing",
                "unknown": "bad",
            },
        ),
        (
            AOStatusSummary,
            {
                "state": "active",
                "objective": "analysis",
                "unknown": "bad",
            },
        ),
    ]

    for cls, payload in child_payloads:
        try:
            cls.from_dict(payload)
        except ValueError as exc:
            assert "unknown" in str(exc)
        else:
            raise AssertionError(f"{cls.__name__}.from_dict should reject unknown fields")


def test_reply_context_builder_extracts_governance_context() -> None:
    memory = FactMemory(session_id="reply-builder")
    ao_manager = AOManager(memory)
    current_ao = ao_manager.create_ao("分析机动车排放", AORelationship.INDEPENDENT, current_turn=1)
    current_ao.tool_call_log.append(
        ToolCallRecord(
            turn=1,
            tool="query_emission_factors",
            args_compact={"vehicle_type": "Motorcycle"},
            success=True,
            result_ref="emission_factors:baseline",
            summary="factor query ok",
        )
    )
    context_store = SessionContextStore()
    context_store.store_result(
        "clean_dataframe",
        {
            "success": True,
            "data": {"report": {"row_count": 2}},
            "summary": "data quality report ready",
        },
    )
    writer = ConstraintViolationWriter(ao_manager, context_store)
    writer.record(_violation_record())
    trace_steps = [
        {
            "step_type": "tool_execution",
            "action": "query_emission_factors",
            "input_summary": {"arguments": {"vehicle_type": "Motorcycle"}},
            "output_summary": {"success": True, "message": "factor query ok"},
            "reasoning": "Emission factor query completed",
        },
        {
            "step_type": "clarification",
            "action": "pollutants",
            "output_summary": {"question": "请选择污染物", "options": ["CO2", "NOx"]},
            "reasoning": "Missing pollutant selection",
        },
    ]

    context = ReplyContextBuilder().build(
        user_message="帮我看这个文件",
        router_text="router draft",
        trace_steps=trace_steps,
        ao_manager=ao_manager,
        violation_writer=writer,
        context_store=context_store,
    )

    assert context.user_message == "帮我看这个文件"
    assert context.router_text == "router draft"
    assert context.tool_executions[0].tool_name == "query_emission_factors"
    assert context.violations[0].violation_type == "vehicle_road_compatibility"
    assert context.pending_clarifications[0].target_field == "pollutants"
    assert context.ao_status is not None
    assert context.ao_status.completed_steps == ["query_emission_factors"]
    assert context.extra["data_quality_report"]["result_type"] == "data_quality_report"


def test_reply_context_builder_handles_missing_dependencies() -> None:
    context = ReplyContextBuilder().build(
        user_message="hello",
        router_text="draft",
        trace_steps=[],
        ao_manager=None,
        violation_writer=None,
        context_store=None,
    )

    assert context.tool_executions == []
    assert context.violations == []
    assert context.pending_clarifications == []
    assert context.ao_status is None
    assert context.extra == {}


def test_reply_context_builder_is_pure_for_same_inputs() -> None:
    builder = ReplyContextBuilder()
    kwargs = {
        "user_message": "u",
        "router_text": "r",
        "trace_steps": [
            {
                "step_type": "tool_execution",
                "action": "query_knowledge",
                "input_summary": {"arguments": {"query": "x"}},
                "output_summary": {"success": True, "message": "ok"},
            }
        ],
        "ao_manager": None,
        "violation_writer": None,
        "context_store": None,
    }

    first = builder.build(**kwargs).to_dict()
    second = builder.build(**kwargs).to_dict()

    assert first == second


def test_reply_context_builder_routes_data_quality_report_to_extra() -> None:
    store = SessionContextStore()
    store.store_result(
        "clean_dataframe",
        {
            "success": True,
            "data": {"report": {"row_count": 0, "column_count": 2}},
            "summary": "empty CSV with headers",
        },
    )

    context = ReplyContextBuilder().build(
        user_message="清洗数据",
        router_text="done",
        trace_steps=[],
        ao_manager=None,
        violation_writer=None,
        context_store=store,
    )

    assert context.extra["data_quality_report"]["data"]["data"]["report"]["row_count"] == 0
