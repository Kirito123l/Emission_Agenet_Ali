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
from core.contracts.oasc_contract import OASCContract
from core.contracts.stance_resolution_contract import StanceResolutionContract
from core.execution_continuation import PendingObjective
from core.governed_router import GovernedRouter
from core.memory import FactMemory
from core.router import RouterResponse
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
        self._continuation_bundle = {"plan": None, "residual_plan_summary": None, "latest_repair_summary": None}
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


def _oasc_contract():
    config = _config()
    config.enable_ao_classifier_llm_layer = False
    inner = FakeInnerRouter({})
    inner.memory.turn_counter = 1
    manager = AOManager(inner.memory.fact_memory)
    contract = OASCContract(inner_router=inner, ao_manager=manager, runtime_config=config)
    return contract, manager, inner


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
async def test_deliberative_with_runtime_default_optional_proceeds():
    contract, manager = _readiness_contract({"vehicle_type": "Passenger Car", "pollutants": ["CO2"]})
    ao = manager.create_ao("先确认参数", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    ao.stance = ConversationalStance.DELIBERATIVE

    interception = await contract.before_turn(_context("小汽车CO2因子参数"))

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert interception.proceed is True
    assert telemetry["final_decision"] == "proceed"
    assert telemetry["execution_readiness"]["readiness_branch"] == "deliberative"
    assert telemetry["execution_readiness"]["pending_slot"] is None
    assert telemetry["execution_readiness"]["runtime_defaults_resolved"] == ["model_year"]
    assert telemetry["execution_readiness"]["no_default_optionals_probed"] == []
    assert "probe_turn_count" not in telemetry


@pytest.mark.anyio
async def test_deliberative_without_runtime_default_still_probes():
    contract, manager = _readiness_contract({"pollutants": ["CO2"], "stability_class": "D"})
    ao = manager.create_ao("先确认扩散参数", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("calculate_dispersion", IntentConfidence.HIGH)
    ao.stance = ConversationalStance.DELIBERATIVE

    interception = await contract.before_turn(_context("先确认CO2扩散参数"))

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert interception.proceed is False
    assert telemetry["final_decision"] == "clarify"
    assert telemetry["execution_readiness"]["readiness_branch"] == "deliberative"
    assert telemetry["execution_readiness"]["pending_slot"] == "meteorology"
    assert telemetry["execution_readiness"]["runtime_defaults_resolved"] == []
    assert telemetry["execution_readiness"]["no_default_optionals_probed"] == [
        "meteorology",
        "pollutant",
        "scenario_label",
    ]


@pytest.mark.anyio
async def test_multi_turn_clarification_not_broken():
    contract, manager = _readiness_contract({"pollutants": ["CO2"]})
    ao = manager.create_ao("先确认参数", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    ao.stance = ConversationalStance.DELIBERATIVE

    interception = await contract.before_turn(_context("先确认CO2因子"))

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert interception.proceed is False
    assert telemetry["final_decision"] == "clarify"
    assert telemetry["execution_readiness"]["pending_slot"] == "vehicle_type"


@pytest.mark.anyio
async def test_directive_path_unchanged():
    hints = {"vehicle_type": "Passenger Car", "pollutants": ["PM2.5"]}
    contract, manager = _readiness_contract(hints)
    ao = manager.create_ao("查因子", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    ao.stance = ConversationalStance.DIRECTIVE

    interception = await contract.before_turn(_context("查小汽车PM2.5因子"))

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert interception.proceed is True
    assert telemetry["final_decision"] == "proceed"
    assert telemetry["execution_readiness"]["readiness_branch"] == "directive"


@pytest.mark.anyio
async def test_directive_telemetry_records_runtime_defaults_resolved():
    hints = {"vehicle_type": "Passenger Car", "pollutants": ["PM2.5"]}
    contract, manager = _readiness_contract(hints)
    ao = manager.create_ao("查因子", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    ao.stance = ConversationalStance.DIRECTIVE

    interception = await contract.before_turn(_context("查小汽车PM2.5因子"))

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert telemetry["execution_readiness"]["readiness_decision"] == "proceed"
    assert telemetry["execution_readiness"]["runtime_defaults_resolved"] == ["model_year"]
    assert telemetry["execution_readiness"]["no_default_optionals_probed"] == []


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


@pytest.mark.anyio
async def test_stance_fallback_when_low_conf_deliberative_and_required_filled_no_hedging():
    config = _config()
    inner = FakeInnerRouter({})
    manager = AOManager(inner.memory.fact_memory)
    contract = StanceResolutionContract(inner_router=inner, ao_manager=manager, runtime_config=config)
    ao = manager.create_ao("factor", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    context = _context("Passenger Car PM2.5 夏季 factor")
    context.metadata["stage2_payload"] = {
        "slots": {
            "vehicle_type": {"value": "Passenger Car"},
            "pollutants": {"value": ["PM2.5"]},
        },
        "stance": {"value": "deliberative", "conf": "low"},
    }

    await contract.before_turn(context)

    assert ao.stance == ConversationalStance.DIRECTIVE
    assert ao.stance_resolved_by == "fallback_saturated_slots"
    assert context.metadata["stance"]["fallback_reason"] == "low_conf_nondirective_with_filled_required"


@pytest.mark.anyio
async def test_stance_not_fallback_when_hedging_present():
    config = _config()
    inner = FakeInnerRouter({})
    manager = AOManager(inner.memory.fact_memory)
    contract = StanceResolutionContract(inner_router=inner, ao_manager=manager, runtime_config=config)
    ao = manager.create_ao("factor", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    context = _context("如果 Passenger Car PM2.5")
    context.metadata["stage2_payload"] = {
        "slots": {
            "vehicle_type": {"value": "Passenger Car"},
            "pollutants": {"value": ["PM2.5"]},
        },
        "stance": {"value": "deliberative", "conf": "low"},
    }

    await contract.before_turn(context)

    assert ao.stance == ConversationalStance.DELIBERATIVE
    assert ao.stance_resolved_by == "llm_slot_filler"
    assert context.metadata["stance"]["stance_fallback_skipped_reason"] == "explicit_hedging"


@pytest.mark.anyio
async def test_stance_not_fallback_when_required_missing():
    config = _config()
    inner = FakeInnerRouter({})
    manager = AOManager(inner.memory.fact_memory)
    contract = StanceResolutionContract(inner_router=inner, ao_manager=manager, runtime_config=config)
    ao = manager.create_ao("factor", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    context = _context("Passenger Car factor")
    context.metadata["stage2_payload"] = {
        "slots": {
            "vehicle_type": {"value": "Passenger Car"},
        },
        "stance": {"value": "deliberative", "conf": "low"},
    }

    await contract.before_turn(context)

    assert ao.stance == ConversationalStance.DELIBERATIVE
    assert ao.stance_resolved_by == "llm_slot_filler"
    assert context.metadata["stance"]["stance_fallback_skipped_reason"] == "required_missing"


@pytest.mark.anyio
async def test_deliberative_high_conf_not_fallback():
    config = _config()
    inner = FakeInnerRouter({})
    manager = AOManager(inner.memory.fact_memory)
    contract = StanceResolutionContract(inner_router=inner, ao_manager=manager, runtime_config=config)
    ao = manager.create_ao("factor", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    context = _context("Passenger Car PM2.5 factor")
    context.metadata["stage2_payload"] = {
        "slots": {
            "vehicle_type": {"value": "Passenger Car"},
            "pollutants": {"value": ["PM2.5"]},
        },
        "stance": {"value": "deliberative", "conf": "high"},
    }

    await contract.before_turn(context)

    assert ao.stance == ConversationalStance.DELIBERATIVE
    assert ao.stance_confidence == StanceConfidence.HIGH
    assert "fallback_reason" not in context.metadata["stance"]


@pytest.mark.anyio
async def test_stance_fallback_skips_without_resolved_tool():
    config = _config()
    inner = FakeInnerRouter({})
    manager = AOManager(inner.memory.fact_memory)
    contract = StanceResolutionContract(inner_router=inner, ao_manager=manager, runtime_config=config)
    manager.create_ao("factor", AORelationship.INDEPENDENT, current_turn=1)
    context = _context("Passenger Car PM2.5 factor")
    context.metadata["stage2_payload"] = {
        "slots": {
            "vehicle_type": {"value": "Passenger Car"},
            "pollutants": {"value": ["PM2.5"]},
        },
        "stance": {"value": "deliberative", "conf": "low"},
    }

    await contract.before_turn(context)

    assert context.metadata["stance"]["stance_fallback_skipped_reason"] == "no_resolved_tool"


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


@pytest.mark.anyio
async def test_intent_contract_short_circuits_active_chain_continuation():
    config = _config()
    inner = FakeInnerRouter({})
    manager = AOManager(inner.memory.fact_memory)
    contract = IntentResolutionContract(inner_router=inner, ao_manager=manager, runtime_config=config)
    ao = manager.create_ao("继续扩散", AORelationship.INDEPENDENT, current_turn=1)
    ao.metadata["execution_continuation"] = {
        "pending_objective": "chain_continuation",
        "pending_next_tool": "calculate_dispersion",
        "pending_tool_queue": ["calculate_dispersion", "render_spatial_map"],
    }

    interception = await contract.before_turn(_context("继续", kind=AOClassType.CONTINUATION))

    assert interception.proceed is True
    assert ao.tool_intent.resolved_tool == "calculate_dispersion"
    assert ao.tool_intent.projected_chain == ["calculate_dispersion", "render_spatial_map"]
    assert ao.tool_intent.resolved_by == "continuation_state"


@pytest.mark.anyio
async def test_intent_contract_short_circuits_parameter_collection_to_bound_tool():
    config = _config()
    inner = FakeInnerRouter({})
    manager = AOManager(inner.memory.fact_memory)
    contract = IntentResolutionContract(inner_router=inner, ao_manager=manager, runtime_config=config)
    ao = manager.create_ao("继续补参数", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent(
        "calculate_micro_emission",
        IntentConfidence.HIGH,
        projected_chain=["calculate_micro_emission"],
    )
    ao.metadata["execution_continuation"] = {
        "pending_objective": "parameter_collection",
        "pending_slot": "season",
    }
    ao.metadata["execution_readiness"] = {
        "pending": True,
        "tool_name": "calculate_micro_emission",
        "pending_slot": "season",
        "missing_slots": ["season"],
    }

    interception = await contract.before_turn(_context("夏季", kind=AOClassType.CONTINUATION))

    assert interception.proceed is True
    assert ao.tool_intent.resolved_tool == "calculate_micro_emission"
    assert ao.tool_intent.projected_chain == ["calculate_micro_emission"]
    assert ao.tool_intent.resolved_by == "parameter_collection_state"


@pytest.mark.anyio
async def test_intent_contract_allows_queue_override_before_short_circuit():
    config = _config()
    inner = FakeInnerRouter({"desired_tool_chain": ["render_spatial_map"]})
    manager = AOManager(inner.memory.fact_memory)
    contract = IntentResolutionContract(inner_router=inner, ao_manager=manager, runtime_config=config)
    ao = manager.create_ao("继续扩散", AORelationship.INDEPENDENT, current_turn=1)
    ao.metadata["execution_continuation"] = {
        "pending_objective": "chain_continuation",
        "pending_next_tool": "calculate_dispersion",
        "pending_tool_queue": ["calculate_dispersion", "render_spatial_map"],
    }

    interception = await contract.before_turn(_context("先画地图", kind=AOClassType.CONTINUATION))

    assert interception.proceed is True
    assert ao.tool_intent.resolved_tool == "render_spatial_map"
    assert ao.tool_intent.projected_chain == ["render_spatial_map"]
    assert ao.tool_intent.resolved_by == "rule:desired_chain"


@pytest.mark.anyio
async def test_readiness_missing_required_beats_exploratory_scope_framing():
    contract, manager = _readiness_contract({})
    ao = manager.create_ao("先确认", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    ao.stance = ConversationalStance.EXPLORATORY
    context = _context("先看看", kind=AOClassType.CONTINUATION)
    context.metadata["stage2_payload"] = {
        "slots": {},
        "stance": {"value": "exploratory", "conf": "high"},
        "missing_required": ["vehicle_type", "pollutants"],
        "clarification_question": "请补充车型和污染物。",
    }

    interception = await contract.before_turn(context)

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert interception.proceed is False
    assert telemetry["execution_readiness"]["pending_slot"] == "vehicle_type"
    assert "scope" not in interception.response.text


@pytest.mark.anyio
async def test_readiness_multistep_projected_chain_skips_snapshot_direct():
    contract, manager = _readiness_contract({"pollutants": ["NOx"]})
    ao = manager.create_ao("算排放再扩散", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent(
        "calculate_macro_emission",
        IntentConfidence.HIGH,
        projected_chain=["calculate_macro_emission", "calculate_dispersion"],
    )
    ao.stance = ConversationalStance.DIRECTIVE

    interception = await contract.before_turn(_context("先算 NOx 排放，再扩散"))

    assert interception.proceed is True
    assert "direct_execution" not in interception.metadata["clarification"]
    assert interception.metadata["clarification"]["telemetry"]["final_decision"] == "proceed"


@pytest.mark.anyio
async def test_readiness_stage2_needs_clarification_blocks_fresh_proceed():
    contract, manager = _readiness_contract({"vehicle_type": "Passenger Car", "pollutants": ["NOx"]})
    ao = manager.create_ao("先查因子", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    ao.stance = ConversationalStance.DIRECTIVE
    context = _context("先查小汽车 NOx 因子")
    context.metadata["stage2_payload"] = {
        "slots": {
            "vehicle_type": {"value": "Passenger Car", "source": "user", "confidence": "high"},
            "pollutants": {"value": ["NOx"], "source": "user", "confidence": "high"},
        },
        "intent": {"tool": "query_emission_factors", "conf": "high"},
        "stance": {"value": "directive", "conf": "medium"},
        "missing_required": [],
        "needs_clarification": True,
        "clarification_question": "请先确认道路类型。",
    }
    ao.metadata["execution_readiness"] = {
        "pending": False,
        "tool_name": "query_emission_factors",
        "pending_slot": None,
        "missing_slots": [],
        "confirm_first_slots": ["road_type"],
    }

    interception = await contract.before_turn(context)

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert interception.proceed is False
    assert telemetry["final_decision"] == "clarify"
    assert telemetry["execution_readiness"]["pending_slot"] == "road_type"
    assert ao.metadata["execution_continuation"]["pending_objective"] == "parameter_collection"


@pytest.mark.anyio
async def test_readiness_preserves_followup_slot_after_proceed():
    contract, manager = _readiness_contract({"vehicle_type": "Passenger Car", "pollutants": ["CO2"]})
    ao = manager.create_ao("查因子", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    ao.stance = ConversationalStance.DIRECTIVE

    interception = await contract.before_turn(_context("查小汽车 CO2 因子"))

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert interception.proceed is True
    assert telemetry["execution_continuation"]["continuation_after"]["pending_objective"] == "parameter_collection"
    assert telemetry["execution_continuation"]["continuation_after"]["pending_slot"] == "model_year"
    assert ao.metadata["execution_readiness"]["followup_slots"] == ["model_year"]
    assert ao.metadata["execution_readiness"]["confirm_first_slots"] == ["road_type"]
    assert ao.metadata["execution_readiness"]["pending_slot"] == "model_year"


@pytest.mark.anyio
async def test_readiness_writes_parameter_collection_continuation_telemetry():
    contract, manager = _readiness_contract({"pollutants": ["CO2"]})
    ao = manager.create_ao("查因子", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    ao.stance = ConversationalStance.DIRECTIVE

    interception = await contract.before_turn(_context("查 CO2 因子"))

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert telemetry["execution_continuation"]["transition_reason"] == "initial_write"
    assert telemetry["execution_continuation"]["continuation_after"]["pending_objective"] == "parameter_collection"
    assert ao.metadata["execution_continuation"]["pending_slot"] == "vehicle_type"


@pytest.mark.anyio
async def test_readiness_reversal_clears_active_continuation():
    contract, manager = _readiness_contract({"pollutants": ["CO2"]})
    ao = manager.create_ao("继续扩散", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    ao.stance = ConversationalStance.DELIBERATIVE
    ao.metadata["execution_continuation"] = {
        "pending_objective": "chain_continuation",
        "pending_next_tool": "calculate_dispersion",
        "pending_tool_queue": ["calculate_dispersion", "render_spatial_map"],
    }
    context = _context("等等，先确认", kind=AOClassType.CONTINUATION)
    context.metadata["stance"] = {"reversal_detected": True}

    interception = await contract.before_turn(context)

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert telemetry["execution_continuation"]["transition_reason"] == "reset_reversal"
    assert ao.metadata["execution_continuation"]["pending_objective"] == "parameter_collection"


@pytest.mark.anyio
async def test_readiness_replace_queue_override_telemetry():
    contract, manager = _readiness_contract({"pollutants": ["CO2"]})
    ao = manager.create_ao("继续扩散", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("render_spatial_map", IntentConfidence.HIGH, projected_chain=["render_spatial_map"])
    ao.stance = ConversationalStance.DIRECTIVE
    ao.metadata["execution_continuation"] = {
        "pending_objective": "chain_continuation",
        "pending_next_tool": "calculate_dispersion",
        "pending_tool_queue": ["calculate_dispersion", "render_spatial_map"],
    }

    interception = await contract.before_turn(_context("先画地图", kind=AOClassType.CONTINUATION))

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert telemetry["execution_continuation"]["transition_reason"] == "replace_queue_override"
    assert ao.metadata["execution_continuation"]["pending_next_tool"] == "render_spatial_map"


@pytest.mark.anyio
async def test_readiness_uses_minimal_priors_when_split_intent_and_stance_disabled():
    os.environ["ENABLE_SPLIT_INTENT_CONTRACT"] = "false"
    os.environ["ENABLE_SPLIT_STANCE_CONTRACT"] = "false"
    config = _config()
    inner = FakeInnerRouter({"wants_factor": True, "vehicle_type": "Passenger Car", "pollutants": ["CO2"]})
    manager = AOManager(inner.memory.fact_memory)
    contract = ExecutionReadinessContract(inner_router=inner, ao_manager=manager, runtime_config=config)
    contract.llm_client = AsyncMockLLM()
    ao = manager.create_ao("查因子", AORelationship.INDEPENDENT, current_turn=1)

    interception = await contract.before_turn(_context("排放因子"))

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert interception.proceed is True
    assert telemetry["execution_readiness"]["readiness_branch"] == "directive"


@pytest.mark.anyio
async def test_readiness_runtime_default_aware_off_suppresses_runtime_default_resolution():
    os.environ["ENABLE_RUNTIME_DEFAULT_AWARE_READINESS"] = "false"
    config = _config()
    inner = FakeInnerRouter({"vehicle_type": "Passenger Car", "pollutants": ["CO2"]})
    manager = AOManager(inner.memory.fact_memory)
    contract = ExecutionReadinessContract(inner_router=inner, ao_manager=manager, runtime_config=config)
    contract.llm_client = AsyncMockLLM()
    ao = manager.create_ao("先确认参数", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    ao.stance = ConversationalStance.DELIBERATIVE

    interception = await contract.before_turn(_context("小汽车 CO2 因子"))

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert interception.proceed is True
    assert telemetry["execution_readiness"]["runtime_defaults_resolved"] == []
    assert interception.metadata["clarification"]["direct_execution"]["runtime_defaults_allowed"] == []


@pytest.mark.anyio
async def test_oasc_writes_chain_continuation_after_first_success():
    contract, manager, _inner = _oasc_contract()
    ao = manager.create_ao("算排放再扩散", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent(
        "calculate_macro_emission",
        IntentConfidence.HIGH,
        projected_chain=["calculate_macro_emission", "calculate_dispersion", "render_spatial_map"],
    )
    context = _context("先算排放再扩散")
    context.router_executed = True
    result = RouterResponse(
        text="ok",
        executed_tool_calls=[
            {
                "name": "calculate_macro_emission",
                "arguments": {"pollutants": ["NOx"]},
                "result": {"success": True, "summary": "ok"},
            }
        ],
        trace={},
    )

    await contract.after_turn(context, result)

    continuation = ao.metadata["execution_continuation"]
    assert continuation["pending_objective"] == "chain_continuation"
    assert continuation["pending_tool_queue"] == ["calculate_dispersion", "render_spatial_map"]


@pytest.mark.anyio
async def test_oasc_preserves_parameter_collection_after_execute_when_followup_remains():
    contract, manager, _inner = _oasc_contract()
    ao = manager.create_ao("查因子", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH, projected_chain=["query_emission_factors"])
    ao.metadata["execution_continuation"] = {
        "pending_objective": "parameter_collection",
        "pending_slot": "model_year",
        "probe_count": 0,
        "probe_limit": 2,
    }
    context = _context("查小汽车 CO2 因子", kind=AOClassType.CONTINUATION)
    context.router_executed = True
    context.metadata["execution_continuation_transition"] = {
        "continuation_before": dict(ao.metadata["execution_continuation"]),
        "continuation_after": {
            "pending_objective": "parameter_collection",
            "pending_slot": "model_year",
            "probe_count": 0,
            "probe_limit": 2,
            "abandoned": False,
            "updated_turn": 2,
        },
        "transition_reason": "initial_write",
    }
    result = RouterResponse(
        text="ok",
        executed_tool_calls=[
            {
                "name": "query_emission_factors",
                "arguments": {"vehicle_type": "Passenger Car", "pollutants": ["CO2"]},
                "result": {"success": True, "summary": "ok"},
            }
        ],
        trace={},
    )

    await contract.after_turn(context, result)

    continuation = ao.metadata["execution_continuation"]
    assert continuation["pending_objective"] == "parameter_collection"
    assert continuation["pending_slot"] == "model_year"
    assert context.metadata["execution_continuation_transition"]["transition_reason"] == "initial_write"


@pytest.mark.anyio
async def test_oasc_advances_chain_queue_on_subsequent_success():
    contract, manager, _inner = _oasc_contract()
    ao = manager.create_ao("继续扩散", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent(
        "calculate_dispersion",
        IntentConfidence.HIGH,
        projected_chain=["calculate_macro_emission", "calculate_dispersion", "render_spatial_map"],
    )
    ao.metadata["execution_continuation"] = {
        "pending_objective": "chain_continuation",
        "pending_next_tool": "calculate_dispersion",
        "pending_tool_queue": ["calculate_dispersion", "render_spatial_map"],
    }
    context = _context("继续扩散", kind=AOClassType.CONTINUATION)
    context.router_executed = True
    result = RouterResponse(
        text="ok",
        executed_tool_calls=[
            {
                "name": "calculate_dispersion",
                "arguments": {"pollutant": "NOx"},
                "result": {"success": True, "summary": "ok"},
            }
        ],
        trace={},
    )

    await contract.after_turn(context, result)

    continuation = ao.metadata["execution_continuation"]
    assert continuation["pending_tool_queue"] == ["render_spatial_map"]
    assert continuation["pending_next_tool"] == "render_spatial_map"


@pytest.mark.anyio
async def test_oasc_clears_chain_queue_when_final_tool_executes():
    contract, manager, _inner = _oasc_contract()
    ao = manager.create_ao("继续出图", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent(
        "render_spatial_map",
        IntentConfidence.HIGH,
        projected_chain=["calculate_macro_emission", "calculate_dispersion", "render_spatial_map"],
    )
    ao.metadata["execution_continuation"] = {
        "pending_objective": "chain_continuation",
        "pending_next_tool": "render_spatial_map",
        "pending_tool_queue": ["render_spatial_map"],
    }
    context = _context("继续出图", kind=AOClassType.CONTINUATION)
    context.router_executed = True
    result = RouterResponse(
        text="ok",
        executed_tool_calls=[
            {
                "name": "render_spatial_map",
                "arguments": {"layer_type": "dispersion"},
                "result": {"success": True, "summary": "ok"},
            }
        ],
        trace={},
    )

    await contract.after_turn(context, result)

    continuation = ao.metadata["execution_continuation"]
    assert continuation["pending_objective"] == "none"
    assert continuation["pending_tool_queue"] == []


@pytest.mark.anyio
async def test_readiness_after_turn_emits_continuation_block():
    contract, manager = _readiness_contract({"pollutants": ["CO2"]})
    ao = manager.create_ao("查因子", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("query_emission_factors", IntentConfidence.HIGH)
    ao.stance = ConversationalStance.DIRECTIVE
    context = _context("查 CO2 因子")

    interception = await contract.before_turn(context)
    context.metadata.update(interception.metadata)
    result = RouterResponse(text="请补充车型", trace={})

    await contract.after_turn(context, result)

    telemetry = result.trace["clarification_telemetry"][0]
    assert "execution_continuation" in telemetry
    assert telemetry["execution_continuation"]["transition_reason"] == "initial_write"


@pytest.mark.anyio
async def test_probe_limit_abandons_optional_probe_and_proceeds():
    contract, manager = _readiness_contract({"pollutants": ["CO2"], "stability_class": "D"})
    ao = manager.create_ao("先确认扩散参数", AORelationship.INDEPENDENT, current_turn=1)
    ao.tool_intent = ToolIntent("calculate_dispersion", IntentConfidence.HIGH)
    ao.stance = ConversationalStance.DELIBERATIVE
    ao.metadata["execution_continuation"] = {
        "pending_objective": "parameter_collection",
        "pending_slot": "meteorology",
        "probe_count": 1,
        "probe_limit": 2,
    }

    interception = await contract.before_turn(_context("继续"))

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert interception.proceed is True
    assert telemetry["execution_continuation"]["transition_reason"] in {"abandon_probe_limit", "advance"}
