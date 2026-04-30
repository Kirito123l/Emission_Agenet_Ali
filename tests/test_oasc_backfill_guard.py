"""Unit tests for Phase 5.3 Round 3.1D — OASC stale backfill guard.

Verifies that executed_tool_calls=[] (clarify signal) does NOT trigger
backfill from working memory, while executed_tool_calls=None (legacy default)
still does.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from config import get_config, reset_config
from core.ao_classifier import AOClassification, AOClassType
from core.ao_manager import AOManager
from core.analytical_objective import AORelationship
from core.contracts.base import ContractContext
from core.contracts.oasc_contract import OASCContract
from core.memory import FactMemory
from core.router import RouterResponse


@pytest.fixture(autouse=True)
def _restore_env():
    old = os.environ.get("ENABLE_AO_AWARE_MEMORY")
    yield
    if old is None:
        os.environ.pop("ENABLE_AO_AWARE_MEMORY", None)
    else:
        os.environ["ENABLE_AO_AWARE_MEMORY"] = old
    reset_config()


class FakeMemoryTurn:
    """Simulates a working-memory turn entry with optional tool_calls."""
    def __init__(self, user="test user", assistant="test reply", tool_calls=None):
        self.user = user
        self.assistant = assistant
        self.tool_calls = tool_calls


def _oasc_contract(working_memory=None):
    """Build a minimal OASCContract with controlled working memory."""
    config = get_config()
    memory = FactMemory(session_id="backfill-test")
    inner = SimpleNamespace(
        session_id="backfill-test",
        memory=SimpleNamespace(
            fact_memory=memory,
            working_memory=working_memory or [],
            turn_counter=0,
        ),
        assembler=SimpleNamespace(last_telemetry={}),
    )
    inner._load_active_input_completion_request = lambda: None
    inner._load_active_parameter_negotiation_request = lambda: None
    inner._ensure_live_continuation_bundle = lambda: {
        "plan": None,
        "residual_plan_summary": None,
        "latest_repair_summary": None,
    }
    inner.memory.fact_memory._compact_payload = lambda args: dict(args)
    inner.memory.fact_memory._infer_result_ref = lambda name, result: "emission:test"
    inner.memory.fact_memory.append_cumulative_constraint_violation = lambda *a, **kw: None
    inner._get_recent_turns = lambda: []
    # Disable LLM classifier to avoid network calls in unit tests
    config.enable_ao_classifier_llm_layer = False
    manager = AOManager(memory)
    contract = OASCContract(inner_router=inner, ao_manager=manager, runtime_config=config)
    return contract, manager, inner


def _context(router_executed=True):
    return ContractContext(
        user_message="test",
        file_path=None,
        trace={},
        state_snapshot=SimpleNamespace(),
        router_executed=router_executed,
        metadata={
            "oasc": {
                "classification": AOClassification(
                    classification=AOClassType.NEW_AO,
                    target_ao_id=None,
                    reference_ao_id=None,
                    new_objective_text="test",
                    confidence=1.0,
                    reasoning="test",
                    layer="rule",
                ),
                "classifier_ms": 0.0,
                "classifier_telemetry_start": 0,
                "ao_telemetry_start": 0,
            }
        },
    )


# ── _backfill_executed_tool_calls_from_memory unit tests ─────────────


def test_backfill_returns_tool_calls_from_last_memory_turn():
    contract, _, _ = _oasc_contract(
        working_memory=[
            FakeMemoryTurn(tool_calls=[{"name": "some_tool", "result": {"success": True}}]),
        ]
    )
    result = contract._backfill_executed_tool_calls_from_memory()
    assert result == [{"name": "some_tool", "result": {"success": True}}]


def test_backfill_returns_none_when_working_memory_empty():
    contract, _, _ = _oasc_contract(working_memory=[])
    result = contract._backfill_executed_tool_calls_from_memory()
    assert result is None


def test_backfill_returns_none_when_last_turn_has_no_tool_calls():
    contract, _, _ = _oasc_contract(
        working_memory=[FakeMemoryTurn(tool_calls=None)]
    )
    result = contract._backfill_executed_tool_calls_from_memory()
    assert result is None


# ── after_turn guard: executed_tool_calls=[] does NOT backfill ───────


@pytest.mark.anyio
async def test_after_turn_empty_list_does_not_backfill():
    contract, manager, inner = _oasc_contract(
        working_memory=[
            FakeMemoryTurn(tool_calls=[{"name": "stale_tool", "result": {"success": True}}]),
        ]
    )
    ao = manager.create_ao("clarify task", AORelationship.INDEPENDENT, current_turn=1)

    result = RouterResponse(text="clarify question?", executed_tool_calls=[])
    await contract.after_turn(_context(), result)

    # Must NOT have backfilled — executed_tool_calls stays []
    assert result.executed_tool_calls == []

    # AO must NOT have a stale tool call appended
    tool_log = list(getattr(ao, "tool_call_log", []) or [])
    assert len(tool_log) == 0


# ── after_turn guard: executed_tool_calls=None still backfills ───────


@pytest.mark.anyio
async def test_after_turn_none_backfills_from_memory():
    contract, manager, inner = _oasc_contract(
        working_memory=[
            FakeMemoryTurn(tool_calls=[{"name": "memory_tool", "result": {"success": True}}]),
        ]
    )
    ao = manager.create_ao("legacy task", AORelationship.INDEPENDENT, current_turn=1)

    result = RouterResponse(text="legacy response", executed_tool_calls=None)
    await contract.after_turn(_context(), result)

    # Must have backfilled
    assert result.executed_tool_calls is not None
    assert len(result.executed_tool_calls) == 1
    assert result.executed_tool_calls[0]["name"] == "memory_tool"


# ── after_turn guard: real tool calls are not overwritten ────────────


@pytest.mark.anyio
async def test_after_turn_real_calls_not_backfilled():
    contract, manager, inner = _oasc_contract(
        working_memory=[
            FakeMemoryTurn(tool_calls=[{"name": "stale_tool", "result": {"success": True}}]),
        ]
    )
    ao = manager.create_ao("real exec", AORelationship.INDEPENDENT, current_turn=1)

    real_calls = [{"name": "real_tool", "arguments": {}, "result": {"success": True}}]
    result = RouterResponse(text="done", executed_tool_calls=real_calls)
    await contract.after_turn(_context(), result)

    # Must keep original real calls
    assert result.executed_tool_calls == real_calls
    assert result.executed_tool_calls[0]["name"] == "real_tool"
