from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from config import get_config, reset_config
from core.ao_classifier import AOClassification, AOClassType
from core.ao_manager import AOManager
from core.analytical_objective import (
    AORelationship,
    AnalyticalObjective,
    AOStatus,
    ConversationalStance,
    IntentConfidence,
    StanceConfidence,
    ToolIntent,
)
from core.contracts.base import ContractContext
from core.contracts.execution_readiness_contract import ExecutionReadinessContract
from core.contracts.intent_resolution_contract import IntentResolutionContract
from core.contracts.stance_resolution_contract import StanceResolutionContract
from core.governed_router import GovernedRouter
from core.memory import FactMemory
from core.task_state import TaskState


@pytest.fixture(autouse=True)
def _restore_contract_split_env():
    old = os.environ.get("ENABLE_CONTRACT_SPLIT")
    yield
    if old is None:
        os.environ.pop("ENABLE_CONTRACT_SPLIT", None)
    else:
        os.environ["ENABLE_CONTRACT_SPLIT"] = old
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
    def __init__(self, hints: dict):
        self.session_id = "split-session"
        self.memory = SimpleNamespace(fact_memory=FactMemory(session_id="split-session"), turn_counter=0)
        self._hints = hints

    def _extract_message_execution_hints(self, state):
        return dict(self._hints)


def _config():
    os.environ["ENABLE_CONTRACT_SPLIT"] = "true"
    reset_config()
    return get_config()


def _classification(kind=AOClassType.NEW_AO):
    return AOClassification(
        classification=kind,
        target_ao_id=None,
        reference_ao_id=None,
        new_objective_text="split task",
        confidence=1.0,
        reasoning="test",
        layer="rule",
    )


def _context(message: str, state: TaskState | None = None, kind=AOClassType.NEW_AO):
    return ContractContext(
        user_message=message,
        file_path=None,
        trace={},
        state_snapshot=state or TaskState(user_message=message, session_id="split-session"),
        metadata={"oasc": {"classification": _classification(kind)}},
    )


def _manager():
    return AOManager(FactMemory(session_id="split-session"))


def _readiness_contract(hints: dict):
    config = _config()
    inner = FakeInnerRouter(hints)
    manager = AOManager(inner.memory.fact_memory)
    contract = ExecutionReadinessContract(inner_router=inner, ao_manager=manager, runtime_config=config)
    contract.llm_client = AsyncMockLLM()
    return contract, manager


@pytest.mark.anyio
async def test_directive_required_filled_optional_missing_proceeds_with_runtime_default():
    hints = {
        "vehicle_type": "Passenger Car",
        "pollutants": ["PM2.5"],
        "season": "夏季",
    }
    contract, manager = _readiness_contract(hints)
    ao = manager.create_ao("查因子", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    ao.stance = ConversationalStance.DIRECTIVE
    context = _context("查小汽车PM2.5夏季因子")

    interception = await contract.before_turn(context)

    state = interception.metadata["clarification"]
    telemetry = state["telemetry"]
    assert telemetry["final_decision"] == "proceed"
    assert "collection_mode" not in telemetry
    assert telemetry["execution_readiness"]["readiness_branch"] == "directive"
    assert telemetry["execution_readiness"]["runtime_defaults_applied"] == ["model_year"]
    args = GovernedRouter._snapshot_to_tool_args(
        "query_emission_factors",
        state["direct_execution"]["parameter_snapshot"],
        allow_factor_year_default=True,
    )
    assert args["model_year"] == 2020


@pytest.mark.anyio
async def test_deliberative_required_filled_optional_missing_probes():
    contract, manager = _readiness_contract({"vehicle_type": "Passenger Car", "pollutants": ["CO2"]})
    ao = manager.create_ao("先确认参数", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    ao.stance = ConversationalStance.DELIBERATIVE

    interception = await contract.before_turn(_context("先确认小汽车CO2因子参数"))

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert interception.proceed is False
    assert telemetry["final_decision"] == "clarify"
    assert telemetry["execution_readiness"]["readiness_branch"] == "deliberative"
    assert telemetry["execution_readiness"]["pending_slot"] == "model_year"
    assert "probe_turn_count" not in telemetry


@pytest.mark.anyio
async def test_directive_required_missing_clarifies_single_slot():
    contract, manager = _readiness_contract({"pollutants": ["CO2"]})
    ao = manager.create_ao("查因子", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    ao.stance = ConversationalStance.DIRECTIVE

    interception = await contract.before_turn(_context("查CO2因子"))

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert interception.proceed is False
    assert telemetry["execution_readiness"]["readiness_branch"] == "directive"
    assert telemetry["execution_readiness"]["pending_slot"] == "vehicle_type"


@pytest.mark.anyio
async def test_code_switch_pollutants_not_rejected_by_stage3():
    contract, manager = _readiness_contract({"vehicle_type": "bus", "pollutants": ["pm2.5"]})
    ao = manager.create_ao("bus factor", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    ao.stance = ConversationalStance.DIRECTIVE

    interception = await contract.before_turn(_context("bus的pm2.5 factor给我一个"))

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert telemetry["final_decision"] == "proceed"
    assert "pollutants" not in telemetry["stage3_rejected_slots"]


@pytest.mark.anyio
async def test_stage3_accepts_canonical_vehicle_type():
    contract, manager = _readiness_contract({"vehicle_type": "Light Commercial Truck", "pollutants": ["PM2.5"]})
    ao = manager.create_ao("truck factor", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    ao.stance = ConversationalStance.DIRECTIVE

    interception = await contract.before_turn(_context("查小货车PM2.5因子"))

    telemetry = interception.metadata["clarification"]["telemetry"]
    snapshot = interception.metadata["clarification"]["direct_execution"]["parameter_snapshot"]
    assert telemetry["final_decision"] == "proceed"
    assert "vehicle_type" not in telemetry["stage3_rejected_slots"]
    assert snapshot["vehicle_type"]["value"] == "Light Commercial Truck"


@pytest.mark.anyio
async def test_stage3_accepts_canonical_pollutant_list():
    contract, manager = _readiness_contract({"vehicle_type": "Passenger Car", "pollutants": ["PM2.5", "NOx"]})
    ao = manager.create_ao("car factor", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    ao.stance = ConversationalStance.DIRECTIVE

    interception = await contract.before_turn(_context("查小汽车PM2.5和NOx因子"))

    telemetry = interception.metadata["clarification"]["telemetry"]
    snapshot = interception.metadata["clarification"]["direct_execution"]["parameter_snapshot"]
    assert telemetry["final_decision"] == "proceed"
    assert "pollutants" not in telemetry["stage3_rejected_slots"]
    assert snapshot["pollutants"]["value"] == ["PM2.5", "NOx"]


@pytest.mark.anyio
async def test_stage3_accepts_canonical_road_type():
    contract, manager = _readiness_contract(
        {"vehicle_type": "Passenger Car", "pollutants": ["CO"], "road_type": "次干道"}
    )
    ao = manager.create_ao("road factor", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    ao.stance = ConversationalStance.DIRECTIVE

    interception = await contract.before_turn(_context("查次干道小汽车CO因子"))

    telemetry = interception.metadata["clarification"]["telemetry"]
    snapshot = interception.metadata["clarification"]["direct_execution"]["parameter_snapshot"]
    assert telemetry["final_decision"] == "proceed"
    assert "road_type" not in telemetry["stage3_rejected_slots"]
    assert snapshot["road_type"]["value"] == "次干道"


@pytest.mark.anyio
async def test_stage3_accepts_alias_still_works():
    contract, manager = _readiness_contract({"vehicle_type": "bus", "pollutants": ["pm25"]})
    ao = manager.create_ao("bus factor", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    ao.stance = ConversationalStance.DIRECTIVE

    interception = await contract.before_turn(_context("bus pm25 factor"))

    telemetry = interception.metadata["clarification"]["telemetry"]
    snapshot = interception.metadata["clarification"]["direct_execution"]["parameter_snapshot"]
    assert telemetry["final_decision"] == "proceed"
    assert snapshot["vehicle_type"]["value"] == "Transit Bus"
    assert snapshot["pollutants"]["value"] == ["PM2.5"]


def test_pollutant_strip_chinese_emission_suffix():
    normalized, success = ExecutionReadinessContract._standardize_pollutant_value(["NOx排放"])

    assert success is True
    assert normalized == ["NOx"]


def test_pollutant_strip_english_emission_suffix():
    normalized, success = ExecutionReadinessContract._standardize_pollutant_value(["PM2.5 emission"])

    assert success is True
    assert normalized == ["PM2.5"]


def test_pollutant_plain_canonical_still_works():
    normalized, success = ExecutionReadinessContract._standardize_pollutant_value(["CO2"])

    assert success is True
    assert normalized == ["CO2"]


@pytest.mark.anyio
async def test_intent_contract_uses_compact_stage2_hint():
    config = _config()
    inner = FakeInnerRouter({})
    manager = AOManager(inner.memory.fact_memory)
    contract = IntentResolutionContract(inner_router=inner, ao_manager=manager, runtime_config=config)
    contract.llm_client = AsyncMockLLM(
        {
            "slots": {},
            "intent": {"tool": "query_emission_factors", "conf": "high"},
            "stance": {"value": "directive", "conf": "low"},
            "missing_required": [],
        }
    )
    ao = manager.create_ao("factor", AORelationship.INDEPENDENT, current_turn=1)

    interception = await contract.before_turn(_context("factor"))

    assert interception.proceed is True
    assert ao.tool_intent.resolved_tool == "query_emission_factors"
    assert ao.tool_intent.confidence == IntentConfidence.HIGH


@pytest.mark.anyio
async def test_intent_contract_clarifies_when_unresolved():
    config = _config()
    inner = FakeInnerRouter({})
    manager = AOManager(inner.memory.fact_memory)
    contract = IntentResolutionContract(inner_router=inner, ao_manager=manager, runtime_config=config)
    contract.llm_client = AsyncMockLLM({"slots": {}, "intent": {"conf": "none"}})
    manager.create_ao("unknown", AORelationship.INDEPENDENT, current_turn=1)

    interception = await contract.before_turn(_context("帮我看看"))

    assert interception.proceed is False
    assert interception.metadata["clarification"]["telemetry"]["execution_readiness"]["pending_slot"] == "tool_intent"


@pytest.mark.anyio
async def test_stance_contract_defaults_unknown_to_directive():
    config = _config()
    inner = FakeInnerRouter({})
    manager = AOManager(inner.memory.fact_memory)
    contract = StanceResolutionContract(inner_router=inner, ao_manager=manager, runtime_config=config)
    ao = manager.create_ao("查因子", AORelationship.INDEPENDENT, current_turn=1)

    await contract.before_turn(_context("排放因子"))

    assert ao.stance == ConversationalStance.DIRECTIVE
    assert ao.stance_confidence == StanceConfidence.LOW


@pytest.mark.anyio
async def test_stance_contract_detects_reversal_and_updates_history():
    config = _config()
    inner = FakeInnerRouter({})
    manager = AOManager(inner.memory.fact_memory)
    contract = StanceResolutionContract(inner_router=inner, ao_manager=manager, runtime_config=config)
    ao = manager.create_ao("查因子", AORelationship.INDEPENDENT, current_turn=1)
    ao.stance = ConversationalStance.DIRECTIVE
    ao.stance_confidence = StanceConfidence.MEDIUM

    await contract.before_turn(_context("等等，先确认参数", kind=AOClassType.CONTINUATION))

    assert ao.stance == ConversationalStance.DELIBERATIVE
    assert ao.stance_history[-1][1] == ConversationalStance.DELIBERATIVE


def test_split_serialization_excludes_pcm_fields():
    _config()
    ao = AnalyticalObjective(
        ao_id="AO#1",
        session_id="s",
        objective_text="x",
        status=AOStatus.ACTIVE,
        start_turn=1,
    )
    ao.parameter_state.collection_mode = True
    payload = ao.to_dict()
    assert "collection_mode" not in payload["parameter_state"]
    assert "probe_turn_count" not in payload["parameter_state"]
