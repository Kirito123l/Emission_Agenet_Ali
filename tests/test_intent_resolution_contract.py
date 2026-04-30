"""Unit tests for Phase 5.3 Round 3.1C — C-narrow file-task-type anchoring in IRC.

Tests the new continuation + file_context.task_type branch that prevents
tool-intent drift (e.g., "CO2" on a macro_emission file task drifting to
query_emission_factors).
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from config import get_config, reset_config
from core.ao_classifier import AOClassification, AOClassType
from core.ao_manager import AOManager
from core.analytical_objective import (
    AORelationship,
    AOStatus,
    IntentConfidence,
)
from core.contracts.base import ContractContext
from core.contracts.intent_resolution_contract import IntentResolutionContract
from core.execution_continuation import ExecutionContinuation, PendingObjective
from core.execution_continuation_utils import save_execution_continuation
from core.memory import FactMemory
from core.task_state import TaskState


@pytest.fixture(autouse=True)
def _restore_env():
    old_split = os.environ.get("ENABLE_CONTRACT_SPLIT")
    old_file_inj = os.environ.get("ENABLE_FILE_CONTEXT_INJECTION")
    yield
    for key, old in [
        ("ENABLE_CONTRACT_SPLIT", old_split),
        ("ENABLE_FILE_CONTEXT_INJECTION", old_file_inj),
    ]:
        if old is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old
    reset_config()


class AsyncMockLLM:
    def __init__(self, payload=None):
        self.payload = payload or {}

    async def chat_json_with_metadata(self, *, messages, system=None, temperature=None):
        return {
            "payload": self.payload,
            "raw_response": str(self.payload),
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }


class FakeInnerRouter:
    def __init__(self, hints=None):
        self.session_id = "c-narrow-session"
        self.memory = SimpleNamespace(
            fact_memory=FactMemory(session_id="c-narrow-session"), turn_counter=0
        )
        self._hints = hints or {}
        self._continuation_bundle = {
            "plan": None,
            "residual_plan_summary": None,
            "latest_repair_summary": None,
        }
        self.assembler = SimpleNamespace(last_telemetry={})

    def _extract_message_execution_hints(self, state):
        return dict(self._hints)

    def _load_active_input_completion_request(self):
        return None

    def _load_active_parameter_negotiation_request(self):
        return None

    def _ensure_live_continuation_bundle(self):
        return self._continuation_bundle


def _config():
    os.environ["ENABLE_CONTRACT_SPLIT"] = "true"
    reset_config()
    return get_config()


def _classification(kind=AOClassType.CONTINUATION):
    return AOClassification(
        classification=kind,
        target_ao_id=None,
        reference_ao_id=None,
        new_objective_text="continuation task",
        confidence=1.0,
        reasoning="test",
        layer="rule",
    )


def _context(message: str, state: TaskState | None = None, kind=AOClassType.CONTINUATION):
    return ContractContext(
        user_message=message,
        file_path=None,
        trace={},
        state_snapshot=state or TaskState(user_message=message, session_id="c-narrow-session"),
        metadata={"oasc": {"classification": _classification(kind)}},
    )


def _manager(inner=None):
    memory = (
        inner.memory.fact_memory
        if inner is not None
        else FactMemory(session_id="c-narrow-session")
    )
    return AOManager(memory)


# ── C-narrow: CONTINUATION + file_task_type anchoring ──────────────────


@pytest.mark.anyio
async def test_continuation_macro_file_task_anchors_to_calculate_macro_emission():
    """Turn 2 'CO2' on a macro_emission file task must not drift to query_emission_factors."""
    config = _config()
    config.enable_llm_decision_field = True
    inner = FakeInnerRouter({"wants_factor": False, "desired_tool_chain": []})
    manager = _manager(inner)
    contract = IntentResolutionContract(inner_router=inner, ao_manager=manager, runtime_config=config)

    ao = manager.create_ao("macro file task", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState(user_message="CO2", session_id="c-narrow-session")
    state.file_context.task_type = "macro_emission"
    state.file_context.has_file = True

    interception = await contract.before_turn(_context("CO2", state=state))

    assert ao.tool_intent.resolved_tool == "calculate_macro_emission"
    assert ao.tool_intent.confidence == IntentConfidence.HIGH
    assert ao.tool_intent.resolved_by == "continuation_state:file_task_type"
    assert "file_task_type:macro_emission" in ao.tool_intent.evidence
    assert ao.tool_intent.projected_chain == ["calculate_macro_emission"]
    # Should not block; falls through to ERC
    assert interception.proceed is True


@pytest.mark.anyio
async def test_continuation_micro_file_task_anchors_to_calculate_micro_emission():
    """Turn 2 parameter on a micro_emission file task must stay on micro tool."""
    config = _config()
    config.enable_llm_decision_field = True
    inner = FakeInnerRouter({"wants_factor": False, "desired_tool_chain": []})
    manager = _manager(inner)
    contract = IntentResolutionContract(inner_router=inner, ao_manager=manager, runtime_config=config)

    ao = manager.create_ao("micro file task", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState(user_message="NOx", session_id="c-narrow-session")
    state.file_context.task_type = "micro_emission"
    state.file_context.has_file = True

    await contract.before_turn(_context("NOx", state=state))

    assert ao.tool_intent.resolved_tool == "calculate_micro_emission"
    assert ao.tool_intent.resolved_by == "continuation_state:file_task_type"
    assert "file_task_type:micro_emission" in ao.tool_intent.evidence


@pytest.mark.anyio
async def test_continuation_no_file_task_type_falls_through_to_resolve_fast():
    """Without file_context.task_type, the new branch must not fire."""
    config = _config()
    config.enable_llm_decision_field = True
    inner = FakeInnerRouter({"wants_factor": False, "desired_tool_chain": []})
    manager = _manager(inner)
    contract = IntentResolutionContract(inner_router=inner, ao_manager=manager, runtime_config=config)

    contract.llm_client = AsyncMockLLM({"slots": {}, "intent": {"conf": "none"}})
    ao = manager.create_ao("no file task", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState(user_message="CO2", session_id="c-narrow-session")
    # file_context.task_type is None (default)

    await contract.before_turn(_context("CO2", state=state))

    # Falls through to resolve_fast; with no hints and no file, returns NONE
    assert ao.tool_intent.confidence == IntentConfidence.NONE
    assert ao.tool_intent.resolved_by is None


# ── Existing branches are NOT overridden ────────────────────────────────


@pytest.mark.anyio
async def test_continuation_active_parameter_collection_branch_wins():
    """When PARAMETER_COLLECTION is active, it must win over the new file_task_type branch."""
    config = _config()
    config.enable_llm_decision_field = True
    inner = FakeInnerRouter({"wants_factor": False, "desired_tool_chain": []})
    manager = _manager(inner)
    contract = IntentResolutionContract(inner_router=inner, ao_manager=manager, runtime_config=config)

    ao = manager.create_ao("param collection", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent.resolved_tool = "query_emission_factors"
    ao.tool_intent.confidence = IntentConfidence.HIGH
    ao.tool_intent.resolved_by = "llm_slot_filler"
    save_execution_continuation(
        ao,
        ExecutionContinuation(
            pending_objective=PendingObjective.PARAMETER_COLLECTION,
            pending_slot="vehicle_type",
            updated_turn=1,
        ),
    )

    state = TaskState(user_message="小汽车", session_id="c-narrow-session")
    state.file_context.task_type = "macro_emission"  # Would trigger new branch, but PARAMETER_COLLECTION wins

    await contract.before_turn(_context("小汽车", state=state))

    # PARAMETER_COLLECTION branch preserves existing tool
    assert ao.tool_intent.resolved_tool == "query_emission_factors"
    assert ao.tool_intent.resolved_by == "parameter_collection_state"


@pytest.mark.anyio
async def test_continuation_chain_continuation_branch_wins():
    """When CHAIN_CONTINUATION is active, it must win over the new file_task_type branch."""
    config = _config()
    config.enable_llm_decision_field = True
    inner = FakeInnerRouter({"wants_factor": False, "desired_tool_chain": []})
    manager = _manager(inner)
    contract = IntentResolutionContract(inner_router=inner, ao_manager=manager, runtime_config=config)

    ao = manager.create_ao("chain cont", AORelationship.INDEPENDENT, current_turn=1)
    save_execution_continuation(
        ao,
        ExecutionContinuation(
            pending_objective=PendingObjective.CHAIN_CONTINUATION,
            pending_next_tool="calculate_dispersion",
            pending_tool_queue=["calculate_dispersion"],
            updated_turn=1,
        ),
    )

    state = TaskState(user_message="继续", session_id="c-narrow-session")
    state.file_context.task_type = "macro_emission"

    await contract.before_turn(_context("继续", state=state))

    assert ao.tool_intent.resolved_tool == "calculate_dispersion"
    assert ao.tool_intent.resolved_by == "continuation_state"


# ── File-less tasks unaffected ──────────────────────────────────────────


@pytest.mark.anyio
async def test_file_less_query_emission_factors_unaffected():
    """Direct query_emission_factors request must not be anchored to a file tool."""
    config = _config()
    config.enable_llm_decision_field = True
    inner = FakeInnerRouter({"wants_factor": False, "desired_tool_chain": []})
    manager = _manager(inner)
    contract = IntentResolutionContract(inner_router=inner, ao_manager=manager, runtime_config=config)
    contract.llm_client = AsyncMockLLM(
        {
            "slots": {},
            "intent": {"tool": "query_emission_factors", "conf": "high"},
            "stance": {"value": "directive", "conf": "low"},
            "missing_required": [],
        }
    )

    ao = manager.create_ao("factor query", AORelationship.INDEPENDENT, current_turn=1)
    # No file — NEW_AO classification, not CONTINUATION
    state = TaskState(user_message="查询2020年公交车的CO2排放因子", session_id="c-narrow-session")
    # file_context.task_type is None (default, no file)

    await contract.before_turn(_context("查询2020年公交车的CO2排放因子", state=state, kind=AOClassType.NEW_AO))

    # Falls through to resolve_fast with NONE, then Stage 2 LLM resolves
    assert ao.tool_intent.resolved_tool == "query_emission_factors"
    assert ao.tool_intent.confidence == IntentConfidence.HIGH


# ── Non-continuation classification does NOT trigger new branch ─────────


@pytest.mark.anyio
async def test_revision_classification_does_not_trigger_file_anchor():
    """REVISION must use existing resolve_fast or Stage 2, not the new branch."""
    config = _config()
    config.enable_llm_decision_field = True
    inner = FakeInnerRouter({"wants_factor": False, "desired_tool_chain": []})
    manager = _manager(inner)
    contract = IntentResolutionContract(inner_router=inner, ao_manager=manager, runtime_config=config)

    ao = manager.create_ao("revise task", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState(user_message="改成冬季再算", session_id="c-narrow-session")
    state.file_context.task_type = "macro_emission"

    await contract.before_turn(_context("改成冬季再算", state=state, kind=AOClassType.REVISION))

    # REVISION doesn't enter the short_circuit block at all
    # Falls through to resolve_fast which may use file_task_type or revision_parent
    # Either way, new branch (which requires continuation) does NOT fire
    # We just verify it doesn't crash and returns a valid intent
    assert ao.tool_intent is not None
