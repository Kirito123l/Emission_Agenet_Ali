from types import SimpleNamespace

import pytest

from config import get_config, reset_config
from core.analytical_objective import AORelationship, ToolCallRecord
from core.ao_classifier import OAScopeClassifier
from core.ao_manager import AOManager, TurnOutcome
from core.assembler import ContextAssembler
from core.memory import FactMemory
from core.task_state import TaskState
from evaluation.eval_end2end import _aggregate_metrics, _build_task_result, _merge_trace_payloads


class AsyncMockLLM:
    def __init__(self, payload=None):
        self.payload = payload or {}

    async def chat_json(self, *, messages, system=None, temperature=None):
        return self.payload


class FailingList:
    def append(self, _item):
        raise RuntimeError("telemetry sink failed")

    def __getitem__(self, _item):
        return []


def _make_memory_and_manager():
    memory = FactMemory(session_id="telemetry-session")
    manager = AOManager(memory)
    return memory, manager


@pytest.mark.anyio
async def test_classifier_records_rule_layer_telemetry():
    reset_config()
    config = get_config()
    memory, manager = _make_memory_and_manager()
    manager.create_ao("算排放", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState()
    state.active_input_completion = SimpleNamespace(request_id="r1")
    classifier = OAScopeClassifier(manager, AsyncMockLLM(), config)

    result = await classifier.classify("冬天", [], state)
    telemetry = classifier.telemetry_slice()

    assert result.classification.value == "continuation"
    assert len(telemetry) == 1
    assert telemetry[0]["layer_hit"] == "rule_layer1"
    assert telemetry[0]["rule_signal"] == "active_input_completion"
    assert telemetry[0]["classification"] == "CONTINUATION"


def test_ao_lifecycle_records_complete_blocked_event():
    _memory, manager = _make_memory_and_manager()
    ao = manager.create_ao("算排放并扩散", AORelationship.INDEPENDENT, current_turn=1)
    manager.append_tool_call(
        ao.ao_id,
        ToolCallRecord(
            turn=1,
            tool="calculate_macro_emission",
            args_compact={"pollutant": "NOx"},
            success=True,
            result_ref="emission:baseline",
            summary="ok",
        ),
    )

    completed = manager.complete_ao(
        ao.ao_id,
        end_turn=1,
        turn_outcome=TurnOutcome(
            tool_chain_succeeded=True,
            final_response_delivered=True,
            is_clarification=False,
            is_parameter_negotiation=False,
            is_partial_delivery=True,
        ),
    )
    events = manager.telemetry_slice()

    assert completed is False
    assert [item["event_type"] for item in events[:3]] == ["create", "activate", "append_tool_call"]
    assert events[-1]["event_type"] == "complete_blocked"
    assert events[-1]["complete_check_results"]["is_partial_delivery"] is True


def test_block_telemetry_is_included_for_ao_block():
    reset_config()
    config = get_config()
    config.enable_ao_block_injection = True
    config.enable_session_state_block = False
    memory, manager = _make_memory_and_manager()
    completed = manager.create_ao("查 CO2 因子", AORelationship.INDEPENDENT, current_turn=1)
    manager.append_tool_call(
        completed.ao_id,
        ToolCallRecord(
            turn=1,
            tool="query_emission_factors",
            args_compact={"pollutant": "CO2"},
            success=True,
            result_ref="emission_factors:baseline",
            summary="ok",
        ),
    )
    manager.complete_ao(
        completed.ao_id,
        end_turn=1,
        turn_outcome=TurnOutcome(
            tool_chain_succeeded=True,
            final_response_delivered=True,
            is_clarification=False,
            is_parameter_negotiation=False,
            is_partial_delivery=False,
        ),
    )
    current = manager.create_ao("继续做扩散", AORelationship.REFERENCE, parent_ao_id=completed.ao_id, current_turn=2)
    manager.append_tool_call(
        current.ao_id,
        ToolCallRecord(
            turn=2,
            tool="calculate_dispersion",
            args_compact={"emission_ref": "emission:baseline"},
            success=True,
            result_ref="dispersion:baseline",
            summary="done",
        ),
    )
    assembler = ContextAssembler()

    fact_memory_payload = {
        "files_in_session": [item.to_dict() for item in memory.files_in_session],
        "session_confirmed_parameters": dict(memory.session_confirmed_parameters),
        "cumulative_constraint_violations": list(memory.cumulative_constraint_violations),
        "ao_history": [item.to_dict() for item in memory.ao_history],
        "current_ao_id": memory.current_ao_id,
        "last_turn_index": memory.last_turn_index,
    }
    _prompt, telemetry = assembler._append_session_state_block("base", fact_memory_payload, TaskState())

    block = telemetry["block_telemetry"]
    assert telemetry["enabled"] is True
    assert block["total_block_tokens"] > 0
    assert block["completed_aos_tokens"] > 0
    assert block["current_ao_tokens"] > 0
    assert block["num_completed_aos_in_block"] == 1
    assert block["num_tool_calls_in_current_ao"] == 1
    assert block["files_in_session_present"] is False
    assert block["session_confirmed_parameters_present"] is False
    assert block["cumulative_constraint_violations_present"] is False


@pytest.mark.anyio
async def test_telemetry_failures_do_not_change_oasc_behavior(monkeypatch):
    reset_config()
    config = get_config()
    memory, manager = _make_memory_and_manager()
    manager.create_ao("算排放", AORelationship.INDEPENDENT, current_turn=1)
    classifier = OAScopeClassifier(manager, AsyncMockLLM(), config)
    classifier._telemetry_log = FailingList()

    state = TaskState()
    state.active_input_completion = SimpleNamespace(request_id="r1")
    result = await classifier.classify("冬季", [], state)
    assert result.classification.value == "continuation"

    assembler = ContextAssembler()
    monkeypatch.setattr(assembler, "_build_block_telemetry", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    prompt, telemetry = assembler._append_session_state_block("base", memory.__dict__, TaskState())

    assert prompt.startswith("base")
    assert telemetry["enabled"] is True
    assert telemetry["block_telemetry"] is None


def test_evaluator_keeps_oasc_telemetry_in_task_record():
    trace_payload = _merge_trace_payloads(
        [
            {
                "steps": [],
                "classifier_telemetry": [{"turn": 1, "layer_hit": "rule_layer1"}],
                "ao_lifecycle_events": [{"turn": 1, "event_type": "create", "ao_id": "AO#1", "relationship": "independent", "parent_ao_id": None}],
                "block_telemetry": [{"turn": 1, "total_block_tokens": 123}],
                "final_stage": "DONE",
            }
        ]
    )
    task = {
        "id": "demo_task",
        "category": "simple",
        "description": "demo",
        "user_message": "hi",
        "test_file": None,
        "expected_tool_chain": [],
        "expected_params": {},
        "expected_outputs": {},
        "success_criteria": {},
        "__legacy_expected_success": None,
    }

    record = _build_task_result(
        task,
        executed_tool_calls=[],
        response_payload={"text": "done"},
        trace_payload=trace_payload,
        error_message=None,
        duration_ms=1.0,
        file_analysis=None,
    )

    assert record["classifier_telemetry"][0]["layer_hit"] == "rule_layer1"
    assert record["ao_lifecycle_events"][0]["event_type"] == "create"
    assert record["block_telemetry"][0]["total_block_tokens"] == 123


def test_aggregate_metrics_includes_clarification_contract_summary():
    logs = [
        {
            "task_id": "demo",
            "category": "simple",
            "success": True,
            "actual": {"tool_chain_match": True, "criteria": {"params_legal": True, "result_has_data": True}},
            "expected": {"tool_chain": ["query_emission_factors"]},
            "infrastructure_status": "ok",
            "classifier_telemetry": [{"classification": "NEW_AO"}],
            "clarification_telemetry": [
                {
                    "trigger_mode": "fresh",
                    "stage2_called": True,
                    "stage2_latency_ms": 1200,
                    "stage3_rejected_slots": [],
                    "final_decision": "proceed",
                }
            ],
        }
    ]

    metrics = _aggregate_metrics(logs, mode="router", skipped=0)

    assert metrics["clarification_contract_metrics"]["trigger_count"] == 1
    assert metrics["clarification_contract_metrics"]["trigger_rate_over_new_revision_turns"] == 1.0
    assert metrics["clarification_contract_metrics"]["stage2_hit_rate"] == 1.0
    assert metrics["clarification_contract_metrics"]["stage2_avg_latency_ms"] == 1200.0
