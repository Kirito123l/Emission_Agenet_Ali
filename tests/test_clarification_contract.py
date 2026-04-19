from __future__ import annotations

from types import SimpleNamespace

import pytest

from config import get_config, reset_config
from core.ao_classifier import AOClassification, AOClassType
from core.ao_manager import AOManager
from core.analytical_objective import AORelationship, ConversationalStance, StanceConfidence
from core.contracts.base import ContractContext
from core.contracts.clarification_contract import ClarificationContract
from core.governed_router import GovernedRouter
from core.memory import FactMemory
from core.router import RouterResponse
from core.task_state import FileContext, TaskState


class AsyncMockLLM:
    def __init__(self, payload=None, error=None):
        self.payload = payload or {}
        self.error = error

    async def chat_json(self, *, messages, system=None, temperature=None):
        if self.error is not None:
            raise self.error
        return self.payload


class FakeInnerRouter:
    def __init__(self, hints: dict):
        self.session_id = "clarification-session"
        self.memory = SimpleNamespace(fact_memory=FactMemory(session_id="clarification-session"), turn_counter=0)
        self._hints = hints

    def _extract_message_execution_hints(self, state):
        return dict(self._hints)


def _make_contract(hints: dict, *, llm_payload=None, llm_error=None):
    reset_config()
    config = get_config()
    inner_router = FakeInnerRouter(hints)
    manager = AOManager(inner_router.memory.fact_memory)
    contract = ClarificationContract(
        inner_router=inner_router,
        ao_manager=manager,
        runtime_config=config,
    )
    contract.llm_client = AsyncMockLLM(payload=llm_payload, error=llm_error)
    return contract, manager, inner_router


def test_confirm_first_detects_先帮我确认():
    contract, _manager, _inner = _make_contract({})

    assert contract._detect_confirm_first("我需要公交车CO2那类因子，先帮我确认参数") == "signal:先帮我确认"


def test_confirm_first_detects_pattern_leading_sequence_marker():
    contract, _manager, _inner = _make_contract({})

    assert contract._detect_confirm_first("然后处理这个路网") == "pattern:leading_sequence_marker"


@pytest.mark.anyio
async def test_missing_factor_slots_short_circuits_with_question():
    hints = {
        "wants_factor": True,
        "desired_tool_chain": ["query_emission_factors"],
        "pollutants": [],
    }
    llm_payload = {
        "tool_name": "query_emission_factors",
        "parameter_snapshot": {
            "vehicle_type": {"value": None, "source": "missing", "confidence": None, "raw_text": None},
            "pollutants": {"value": None, "source": "missing", "confidence": None, "raw_text": None},
        },
        "missing_required": ["vehicle_type", "pollutants"],
        "needs_clarification": True,
        "clarification_question": "请告诉我车辆类型和污染物。",
        "ambiguous_slots": [],
    }
    contract, manager, _inner = _make_contract(hints, llm_payload=llm_payload)
    manager.create_ao("查排放因子", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState(user_message="帮我查一下排放因子", session_id="clarification-session")
    context = ContractContext(
        user_message="帮我查一下排放因子",
        file_path=None,
        trace={},
        state_snapshot=state,
        metadata={
            "oasc": {
                "classification": AOClassification(
                    classification=AOClassType.NEW_AO,
                    target_ao_id=None,
                    reference_ao_id=None,
                    new_objective_text="查排放因子",
                    confidence=1.0,
                    reasoning="test",
                    layer="rule",
                )
            }
        },
    )

    interception = await contract.before_turn(context)

    assert interception.proceed is False
    assert "车辆类型" in interception.response.text
    assert interception.metadata["clarification"]["telemetry"]["final_decision"] == "clarify"
    assert interception.metadata["clarification"]["telemetry"]["stage2_called"] is True


@pytest.mark.anyio
async def test_stage2_stance_hint_updates_ao_and_telemetry():
    hints = {
        "wants_factor": True,
        "desired_tool_chain": ["query_emission_factors"],
        "pollutants": [],
    }
    llm_payload = {
        "slots": {
            "vehicle_type": {"value": None, "source": "missing", "confidence": 0.0, "raw_text": None},
            "pollutants": {"value": None, "source": "missing", "confidence": 0.0, "raw_text": None},
        },
        "intent": {
            "resolved_tool": "query_emission_factors",
            "intent_confidence": "high",
            "reasoning": "因子查询",
        },
        "stance": {"value": "deliberative", "confidence": "high", "reasoning": "先确认参数"},
        "missing_required": ["vehicle_type", "pollutants"],
        "needs_clarification": True,
        "clarification_question": "请告诉我车辆类型和污染物。",
        "ambiguous_slots": [],
    }
    contract, manager, _inner = _make_contract(hints, llm_payload=llm_payload)
    ao = manager.create_ao("排放因子参数", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState(user_message="排放因子参数", session_id="clarification-session")
    context = ContractContext(
        user_message="排放因子参数",
        file_path=None,
        trace={},
        state_snapshot=state,
        metadata={
            "oasc": {
                "classification": AOClassification(
                    classification=AOClassType.NEW_AO,
                    target_ao_id=None,
                    reference_ao_id=None,
                    new_objective_text="排放因子参数",
                    confidence=1.0,
                    reasoning="test",
                    layer="rule",
                )
            }
        },
    )

    interception = await contract.before_turn(context)
    telemetry = interception.metadata["clarification"]["telemetry"]

    assert ao.stance == ConversationalStance.DELIBERATIVE
    assert ao.stance_confidence == StanceConfidence.HIGH
    assert ao.stance_resolved_by == "llm_slot_filler"
    assert ao.stance_history[-1] == (1, ConversationalStance.DELIBERATIVE)
    assert telemetry["stance_value"] == "deliberative"
    assert telemetry["stance_confidence"] == "high"
    assert telemetry["stance_resolved_by"] == "llm_slot_filler"
    assert telemetry["stance_llm_hint_parse_success"] is True


@pytest.mark.anyio
async def test_pcm_triggers_on_missing_required_first_turn():
    hints = {
        "wants_factor": True,
        "desired_tool_chain": ["query_emission_factors"],
        "pollutants": [],
    }
    llm_payload = {
        "tool_name": "query_emission_factors",
        "parameter_snapshot": {
            "vehicle_type": {"value": None, "source": "missing", "confidence": None, "raw_text": None},
            "pollutants": {"value": None, "source": "missing", "confidence": None, "raw_text": None},
        },
        "missing_required": ["vehicle_type", "pollutants"],
        "needs_clarification": True,
        "clarification_question": "请告诉我车辆类型和污染物。",
        "ambiguous_slots": [],
    }
    contract, manager, _inner = _make_contract(hints, llm_payload=llm_payload)
    ao = manager.create_ao("查排放因子", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState(user_message="帮我查一下排放因子", session_id="clarification-session")
    context = ContractContext(
        user_message="帮我查一下排放因子",
        file_path=None,
        trace={},
        state_snapshot=state,
        metadata={
            "oasc": {
                "classification": AOClassification(
                    classification=AOClassType.NEW_AO,
                    target_ao_id=None,
                    reference_ao_id=None,
                    new_objective_text="查排放因子",
                    confidence=1.0,
                    reasoning="test",
                    layer="rule",
                )
            }
        },
    )

    interception = await contract.before_turn(context)

    assert interception.proceed is False
    assert ao.parameter_state.collection_mode is True


@pytest.mark.anyio
async def test_colloquial_vehicle_inferred_candidate_can_proceed():
    hints = {
        "wants_factor": True,
        "desired_tool_chain": ["query_emission_factors"],
        "pollutants": ["CO"],
        "model_year": 2020,
    }
    llm_payload = {
        "tool_name": "query_emission_factors",
        "parameter_snapshot": {
            "vehicle_type": {
                "value": "Motorcycle",
                "source": "inferred",
                "confidence": 0.95,
                "raw_text": "三蹦子",
            },
            "pollutants": {
                "value": ["CO"],
                "source": "user",
                "confidence": 1.0,
                "raw_text": ["CO"],
            },
            "model_year": {
                "value": "2020",
                "source": "user",
                "confidence": 1.0,
                "raw_text": "2020",
            },
        },
        "missing_required": [],
        "needs_clarification": False,
        "clarification_question": None,
        "ambiguous_slots": [],
    }
    contract, manager, inner = _make_contract(hints, llm_payload=llm_payload)
    manager.create_ao("查 CO 因子", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState(user_message="三蹦子的CO排放因子查一下", session_id="clarification-session")
    context = ContractContext(
        user_message="三蹦子的CO排放因子查一下",
        file_path=None,
        trace={},
        state_snapshot=state,
        metadata={
            "oasc": {
                "classification": AOClassification(
                    classification=AOClassType.NEW_AO,
                    target_ao_id=None,
                    reference_ao_id=None,
                    new_objective_text="查 CO 因子",
                    confidence=1.0,
                    reasoning="test",
                    layer="rule",
                )
            }
        },
    )

    interception = await contract.before_turn(context)
    assert interception.proceed is True
    assert inner.memory.fact_memory.recent_vehicle == "Motorcycle"
    assert inner.memory.fact_memory.recent_pollutants == ["CO"]
    context.metadata.update(interception.metadata)

    response = RouterResponse(text="done", trace={})
    await contract.after_turn(context, response)
    assert response.trace["clarification_telemetry"][0]["final_decision"] == "proceed"


@pytest.mark.anyio
async def test_pending_factor_snapshot_asks_for_model_year_before_proceed():
    hints = {
        "desired_tool_chain": [],
        "pollutants": [],
    }
    contract, manager, _inner = _make_contract(hints, llm_payload={})
    ao = manager.create_ao("查因子", AORelationship.INDEPENDENT, current_turn=1)
    ao.metadata["collection_mode"] = True
    ao.metadata["clarification_contract"] = {
        "tool_name": "query_emission_factors",
        "parameter_snapshot": {
            "vehicle_type": {"value": "Passenger Car", "source": "user", "confidence": 1.0, "raw_text": "乘用车"},
            "pollutants": {"value": ["NOx"], "source": "user", "confidence": 1.0, "raw_text": ["NOx"]},
            "model_year": {"value": None, "source": "missing", "confidence": None, "raw_text": None},
        },
        "pending": True,
        "clarification_question": "旧问题",
        "followup_slots": ["model_year"],
    }
    state = TaskState(user_message="继续", session_id="clarification-session")
    context = ContractContext(
        user_message="继续",
        file_path=None,
        trace={},
        state_snapshot=state,
        metadata={},
    )

    interception = await contract.before_turn(context)

    assert interception.proceed is False
    assert "车型年份" in interception.response.text
    assert interception.metadata["clarification"]["telemetry"]["probe_optional_slot"] == "model_year"


@pytest.mark.anyio
async def test_stage2_failure_falls_back_to_deterministic_question():
    hints = {
        "wants_factor": True,
        "desired_tool_chain": ["query_emission_factors"],
        "pollutants": [],
    }
    contract, manager, _inner = _make_contract(hints, llm_error=TimeoutError("timeout"))
    manager.create_ao("查排放因子", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState(user_message="帮我查一下排放因子", session_id="clarification-session")
    context = ContractContext(
        user_message="帮我查一下排放因子",
        file_path=None,
        trace={},
        state_snapshot=state,
        metadata={
            "oasc": {
                "classification": AOClassification(
                    classification=AOClassType.NEW_AO,
                    target_ao_id=None,
                    reference_ao_id=None,
                    new_objective_text="查排放因子",
                    confidence=1.0,
                    reasoning="test",
                    layer="rule",
                )
            }
        },
    )

    interception = await contract.before_turn(context)

    assert interception.proceed is False
    assert interception.metadata["clarification"]["telemetry"]["stage2_called"] is True
    assert "车辆类型" in interception.response.text


@pytest.mark.anyio
async def test_confirm_first_promotes_defaulted_optional_slots_on_fresh_turn():
    hints = {
        "wants_factor": True,
        "desired_tool_chain": ["query_emission_factors"],
        "vehicle_type": "Transit Bus",
        "vehicle_type_raw": "公交车",
        "pollutants": ["CO2"],
    }
    contract, manager, _inner = _make_contract(hints, llm_payload={})
    ao = manager.create_ao("确认参数", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState(user_message="我需要公交车CO2那类因子，先帮我确认参数", session_id="clarification-session")
    context = ContractContext(
        user_message="我需要公交车CO2那类因子，先帮我确认参数",
        file_path=None,
        trace={},
        state_snapshot=state,
        metadata={
            "oasc": {
                "classification": AOClassification(
                    classification=AOClassType.NEW_AO,
                    target_ao_id=None,
                    reference_ao_id=None,
                    new_objective_text="确认参数",
                    confidence=1.0,
                    reasoning="test",
                    layer="rule",
                )
            }
        },
    )

    interception = await contract.before_turn(context)

    assert interception.proceed is False
    assert interception.metadata["clarification"]["telemetry"]["confirm_first_detected"] is True


@pytest.mark.anyio
async def test_pcm_triggers_on_confirm_first():
    hints = {
        "wants_factor": True,
        "desired_tool_chain": ["query_emission_factors"],
        "vehicle_type": "Transit Bus",
        "vehicle_type_raw": "公交车",
        "pollutants": ["CO2"],
    }
    contract, manager, _inner = _make_contract(hints, llm_payload={})
    ao = manager.create_ao("确认参数", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState(user_message="我需要公交车CO2那类因子，先帮我确认参数", session_id="clarification-session")
    context = ContractContext(
        user_message="我需要公交车CO2那类因子，先帮我确认参数",
        file_path=None,
        trace={},
        state_snapshot=state,
        metadata={
            "oasc": {
                "classification": AOClassification(
                    classification=AOClassType.NEW_AO,
                    target_ao_id=None,
                    reference_ao_id=None,
                    new_objective_text="确认参数",
                    confidence=1.0,
                    reasoning="test",
                    layer="rule",
                )
            }
        },
    )

    interception = await contract.before_turn(context)

    assert interception.proceed is False
    assert ao.parameter_state.collection_mode is True
    assert interception.metadata["clarification"]["telemetry"]["confirm_first_detected"] is True


@pytest.mark.anyio
async def test_resume_pending_missing_slots_remain_required_until_filled():
    hints = {
        "desired_tool_chain": [],
        "vehicle_type": "Transit Bus",
        "vehicle_type_raw": "公交车",
        "pollutants": ["CO2"],
    }
    contract, manager, _inner = _make_contract(hints, llm_payload={})
    ao = manager.create_ao("确认参数", AORelationship.INDEPENDENT, current_turn=1)
    ao.metadata["collection_mode"] = True
    ao.metadata["clarification_contract"] = {
        "tool_name": "query_emission_factors",
        "parameter_snapshot": {
            "vehicle_type": {"value": "Transit Bus", "source": "user", "confidence": 1.0, "raw_text": "公交车"},
            "pollutants": {"value": ["CO2"], "source": "user", "confidence": 1.0, "raw_text": ["CO2"]},
            "road_type": {"value": None, "source": "missing", "confidence": None, "raw_text": None},
        },
        "pending": True,
        "missing_slots": ["road_type"],
        "followup_slots": ["model_year"],
        "clarification_question": "请确认路型",
    }
    state = TaskState(user_message="公交车", session_id="clarification-session")
    context = ContractContext(
        user_message="公交车",
        file_path=None,
        trace={},
        state_snapshot=state,
        metadata={},
    )

    interception = await contract.before_turn(context)

    assert interception.proceed is False
    assert "车型年份" in interception.response.text
    assert interception.metadata["clarification"]["telemetry"]["probe_optional_slot"] == "model_year"


@pytest.mark.anyio
async def test_pcm_persists_across_turns_via_metadata():
    hints = {
        "desired_tool_chain": [],
        "vehicle_type": "Passenger Car",
        "vehicle_type_raw": "乘用车",
        "pollutants": ["NOx"],
    }
    contract, manager, _inner = _make_contract(hints, llm_payload={})
    ao = manager.create_ao("查因子", AORelationship.INDEPENDENT, current_turn=1)
    ao.metadata["collection_mode"] = True
    ao.metadata["clarification_contract"] = {
        "tool_name": "query_emission_factors",
        "parameter_snapshot": {
            "vehicle_type": {"value": "Passenger Car", "source": "user", "confidence": 1.0, "raw_text": "乘用车"},
            "pollutants": {"value": ["NOx"], "source": "user", "confidence": 1.0, "raw_text": ["NOx"]},
            "model_year": {"value": None, "source": "missing", "confidence": None, "raw_text": None},
        },
        "pending": True,
        "missing_slots": ["model_year"],
        "pending_decision": "probe_optional",
        "followup_slots": ["model_year"],
        "clarification_question": "请问哪一年的车型",
    }
    state = TaskState(user_message="乘用车", session_id="clarification-session")
    context = ContractContext(
        user_message="乘用车",
        file_path=None,
        trace={},
        state_snapshot=state,
        metadata={},
    )

    interception = await contract.before_turn(context)

    assert interception.proceed is False
    assert ao.parameter_state.collection_mode is True


@pytest.mark.anyio
async def test_pcm_probes_unfilled_optionals_without_default():
    hints = {
        "wants_factor": True,
        "desired_tool_chain": ["query_emission_factors"],
        "vehicle_type": "Transit Bus",
        "vehicle_type_raw": "公交车",
        "pollutants": ["CO2"],
    }
    contract, manager, _inner = _make_contract(hints, llm_payload={})
    ao = manager.create_ao("确认参数", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState(user_message="我需要公交车CO2那类因子，先帮我确认参数", session_id="clarification-session")
    context = ContractContext(
        user_message="我需要公交车CO2那类因子，先帮我确认参数",
        file_path=None,
        trace={},
        state_snapshot=state,
        metadata={
            "oasc": {
                "classification": AOClassification(
                    classification=AOClassType.NEW_AO,
                    target_ao_id=None,
                    reference_ao_id=None,
                    new_objective_text="确认参数",
                    confidence=1.0,
                    reasoning="test",
                    layer="rule",
                )
            }
        },
    )

    interception = await contract.before_turn(context)

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert interception.proceed is False
    assert telemetry["collection_mode"] is True
    assert telemetry["probe_optional_slot"] == "model_year"
    assert ao.parameter_state.collection_mode is True
    assert ao.parameter_state.awaiting_slot == "model_year"


@pytest.mark.anyio
async def test_llm_intent_hint_resolves_tool_when_fast_path_misses():
    hints = {
        "wants_factor": False,
        "desired_tool_chain": [],
    }
    llm_payload = {
        "slots": {
            "vehicle_type": {
                "value": "Transit Bus",
                "source": "inferred",
                "confidence": 0.95,
                "raw_text": "公交车",
            },
            "pollutants": {
                "value": ["CO2"],
                "source": "user",
                "confidence": 1.0,
                "raw_text": "CO2",
            },
            "model_year": {
                "value": None,
                "source": "missing",
                "confidence": None,
                "raw_text": None,
            },
        },
        "intent": {
            "resolved_tool": "query_emission_factors",
            "intent_confidence": "high",
            "reasoning": "因子查询意图明确",
        },
        "missing_required": [],
        "needs_clarification": False,
        "clarification_question": None,
        "ambiguous_slots": [],
    }
    contract, manager, _inner = _make_contract(hints, llm_payload=llm_payload)
    ao = manager.create_ao("确认公交车 CO2 因子参数", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState(user_message="我需要公交车CO2那类因子，先帮我确认参数", session_id="clarification-session")
    context = ContractContext(
        user_message="我需要公交车CO2那类因子，先帮我确认参数",
        file_path=None,
        trace={},
        state_snapshot=state,
        metadata={
            "oasc": {
                "classification": AOClassification(
                    classification=AOClassType.NEW_AO,
                    target_ao_id=None,
                    reference_ao_id=None,
                    new_objective_text="确认公交车 CO2 因子参数",
                    confidence=1.0,
                    reasoning="test",
                    layer="rule",
                )
            }
        },
    )

    interception = await contract.before_turn(context)

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert interception.proceed is False
    assert telemetry["tool_name"] == "query_emission_factors"
    assert telemetry["llm_intent_parse_success"] is True
    assert telemetry["tool_intent_confidence"] == "high"
    assert telemetry["tool_intent_resolved_by"] == "llm_slot_filler"
    assert telemetry["probe_optional_slot"] == "model_year"
    assert ao.tool_intent.resolved_tool == "query_emission_factors"
    assert ao.tool_intent.resolved_by == "llm_slot_filler"


def test_stage2_snapshot_normalizes_missing_sentinel_values():
    contract, _manager, _inner = _make_contract({})

    merged = contract._merge_stage2_snapshot(
        {},
        {
            "model_year": {
                "value": "Missing",
                "source": "missing",
                "confidence": 0.0,
                "raw_text": None,
            },
            "season": {
                "value": "UNKNOWN",
                "source": "inferred",
                "confidence": 0.4,
                "raw_text": None,
            },
        },
    )

    assert merged["model_year"]["value"] is None
    assert merged["model_year"]["source"] == "missing"
    assert merged["season"]["value"] is None
    assert merged["season"]["source"] == "missing"
    assert contract._missing_slots(merged, ["model_year", "season"]) == ["model_year", "season"]


def test_missing_slots_treats_sentinel_value_as_missing():
    contract, _manager, _inner = _make_contract({})
    snapshot = {
        "model_year": {
            "value": "n/a",
            "source": "user",
            "confidence": 1.0,
            "raw_text": "n/a",
        },
    }

    assert contract._missing_slots(snapshot, ["model_year"]) == ["model_year"]


@pytest.mark.anyio
async def test_pcm_triggers_on_first_turn_required_met_but_no_default_optional_empty():
    hints = {
        "wants_factor": True,
        "desired_tool_chain": ["query_emission_factors"],
        "vehicle_type": "Transit Bus",
        "vehicle_type_raw": "公交车",
        "pollutants": ["CO2"],
    }
    contract, manager, _inner = _make_contract(hints, llm_payload={})
    ao = manager.create_ao("查公交车 CO2 因子", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState(user_message="查公交车CO2因子", session_id="clarification-session")
    context = ContractContext(
        user_message="查公交车CO2因子",
        file_path=None,
        trace={},
        state_snapshot=state,
        metadata={
            "oasc": {
                "classification": AOClassification(
                    classification=AOClassType.NEW_AO,
                    target_ao_id=None,
                    reference_ao_id=None,
                    new_objective_text="查公交车 CO2 因子",
                    confidence=1.0,
                    reasoning="test",
                    layer="rule",
                )
            }
        },
    )

    interception = await contract.before_turn(context)

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert interception.proceed is False
    assert ao.parameter_state.collection_mode is True
    assert telemetry["pcm_trigger_reason"] == "unfilled_optional_no_default_at_first_turn"
    assert telemetry["probe_optional_slot"] == "model_year"


@pytest.mark.anyio
async def test_pcm_probe_abandons_after_max_turns():
    hints = {
        "desired_tool_chain": [],
        "vehicle_type": "Transit Bus",
        "vehicle_type_raw": "公交车",
        "pollutants": ["CO2"],
    }
    contract, manager, _inner = _make_contract(hints, llm_payload={})
    ao = manager.create_ao("查公交车 CO2 因子", AORelationship.INDEPENDENT, current_turn=1)
    ao.metadata["collection_mode"] = True
    ao.metadata["pcm_trigger_reason"] = "unfilled_optional_no_default_at_first_turn"
    ao.metadata["clarification_contract"] = {
        "tool_name": "query_emission_factors",
        "parameter_snapshot": {
            "vehicle_type": {"value": "Transit Bus", "source": "user", "confidence": 1.0, "raw_text": "公交车"},
            "pollutants": {"value": ["CO2"], "source": "user", "confidence": 1.0, "raw_text": ["CO2"]},
            "model_year": {"value": None, "source": "missing", "confidence": None, "raw_text": None},
        },
        "pending": True,
        "missing_slots": ["model_year"],
        "pending_decision": "probe_optional",
        "probe_optional_slot": "model_year",
        "probe_turn_count": 1,
        "followup_slots": ["model_year"],
        "clarification_question": "请问车型年份",
    }
    state = TaskState(user_message="继续", session_id="clarification-session")
    context = ContractContext(
        user_message="继续",
        file_path=None,
        trace={},
        state_snapshot=state,
        metadata={},
    )

    interception = await contract.before_turn(context)

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert interception.proceed is True
    assert telemetry["probe_optional_slot"] == "model_year"
    assert telemetry["probe_turn_count"] == 2
    assert telemetry["probe_abandoned"] is True
    assert ao.parameter_state.probe_abandoned is True


def test_probe_turn_count_resets_when_target_slot_changes():
    assert (
        ClarificationContract._next_probe_turn_count(
            {
                "pending_decision": "probe_optional",
                "probe_optional_slot": "model_year",
                "probe_turn_count": 1,
            },
            "road_type",
        )
        == 1
    )


@pytest.mark.anyio
async def test_pcm_proceeds_when_all_no_default_optionals_filled():
    hints = {
        "desired_tool_chain": [],
        "pollutants": [],
    }
    contract, manager, _inner = _make_contract(hints, llm_payload={})
    ao = manager.create_ao("查因子", AORelationship.INDEPENDENT, current_turn=1)
    ao.metadata["collection_mode"] = True
    ao.metadata["clarification_contract"] = {
        "tool_name": "query_emission_factors",
        "parameter_snapshot": {
            "vehicle_type": {"value": "Passenger Car", "source": "user", "confidence": 1.0, "raw_text": "乘用车"},
            "pollutants": {"value": ["NOx"], "source": "user", "confidence": 1.0, "raw_text": ["NOx"]},
            "model_year": {"value": "2022", "source": "user", "confidence": 1.0, "raw_text": "2022"},
        },
        "pending": True,
        "missing_slots": ["model_year"],
        "pending_decision": "probe_optional",
        "followup_slots": ["model_year"],
        "clarification_question": "请问哪一年的车型",
    }
    state = TaskState(user_message="继续", session_id="clarification-session")
    context = ContractContext(
        user_message="继续",
        file_path=None,
        trace={},
        state_snapshot=state,
        metadata={},
    )

    interception = await contract.before_turn(context)

    assert interception.proceed is True


@pytest.mark.anyio
async def test_simple_task_not_affected_by_pcm():
    hints = {
        "wants_factor": True,
        "desired_tool_chain": ["query_emission_factors"],
        "vehicle_type": "Passenger Car",
        "vehicle_type_raw": "乘用车",
        "pollutants": ["CO2"],
        "model_year": 2022,
    }
    llm_payload = {
        "tool_name": "query_emission_factors",
        "parameter_snapshot": {
            "vehicle_type": {"value": "Passenger Car", "source": "user", "confidence": 1.0, "raw_text": "乘用车"},
            "pollutants": {"value": ["CO2"], "source": "user", "confidence": 1.0, "raw_text": ["CO2"]},
            "model_year": {"value": "2022", "source": "user", "confidence": 1.0, "raw_text": "2022"},
        },
        "missing_required": [],
        "needs_clarification": False,
        "clarification_question": None,
        "ambiguous_slots": [],
    }
    contract, manager, _inner = _make_contract(hints, llm_payload=llm_payload)
    ao = manager.create_ao("查 CO2 因子", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState(user_message="查询2022年乘用车CO2排放因子", session_id="clarification-session")
    context = ContractContext(
        user_message="查询2022年乘用车CO2排放因子",
        file_path=None,
        trace={},
        state_snapshot=state,
        metadata={
            "oasc": {
                "classification": AOClassification(
                    classification=AOClassType.NEW_AO,
                    target_ao_id=None,
                    reference_ao_id=None,
                    new_objective_text="查 CO2 因子",
                    confidence=1.0,
                    reasoning="test",
                    layer="rule",
                )
            }
        },
    )

    interception = await contract.before_turn(context)

    assert interception.proceed is True
    assert ao.parameter_state.collection_mode is False


def test_snapshot_direct_success_clears_first_class_collection_state():
    reset_config()
    config = get_config()
    fact_memory = FactMemory(session_id="clarification-session")
    manager = AOManager(fact_memory)
    ao = manager.create_ao("确认参数", AORelationship.INDEPENDENT, current_turn=1)
    ao.parameter_state.collection_mode = True
    ao.parameter_state.awaiting_slot = "model_year"
    ao.parameter_state.probe_turn_count = 1
    ao.parameter_state.probe_abandoned = True

    router = object.__new__(GovernedRouter)
    router.runtime_config = config
    router.ao_manager = manager

    router._mark_parameter_collection_complete()

    assert ao.parameter_state.collection_mode is False
    assert ao.parameter_state.awaiting_slot is None
    assert ao.parameter_state.probe_turn_count == 0
    assert ao.parameter_state.probe_abandoned is False


def test_snapshot_to_tool_args_maps_factor_snapshot():
    snapshot = {
        "vehicle_type": {"value": "Passenger Car", "source": "user"},
        "pollutants": {"value": ["NOx"], "source": "user"},
        "model_year": {"value": "2022", "source": "user"},
        "season": {"value": "冬季", "source": "user"},
        "road_type": {"value": "主干道", "source": "user"},
    }

    args = GovernedRouter._snapshot_to_tool_args("query_emission_factors", snapshot)

    assert args == {
        "vehicle_type": "Passenger Car",
        "pollutants": ["NOx"],
        "model_year": 2022,
        "season": "冬季",
        "road_type": "主干道",
    }


def test_snapshot_to_tool_args_can_apply_factor_year_compat_default():
    snapshot = {
        "vehicle_type": {"value": "Motorcycle", "source": "inferred"},
        "pollutants": {"value": ["CO"], "source": "user"},
    }

    args = GovernedRouter._snapshot_to_tool_args(
        "query_emission_factors",
        snapshot,
        allow_factor_year_default=True,
    )

    assert args["vehicle_type"] == "Motorcycle"
    assert args["pollutants"] == ["CO"]
    assert args["model_year"] == 2020


def test_snapshot_to_tool_args_ignores_missing_model_year_without_crashing():
    snapshot = {
        "vehicle_type": {"value": "Transit Bus", "source": "user"},
        "pollutants": {"value": ["CO2"], "source": "user"},
        "model_year": {"value": "missing", "source": "missing"},
    }

    args = GovernedRouter._snapshot_to_tool_args("query_emission_factors", snapshot)

    assert args == {
        "vehicle_type": "Transit Bus",
        "pollutants": ["CO2"],
    }


def test_stage2_prompt_requests_stance_schema():
    prompt = ClarificationContract._stage2_system_prompt()

    assert "stance" in prompt
    assert "directive/deliberative/exploratory" in prompt


def test_stage2_stance_hint_parses_top_level_stance():
    hint, raw, parsed = ClarificationContract._extract_llm_stance_hint(
        {
            "slots": {},
            "intent": {"resolved_tool": "query_emission_factors", "intent_confidence": "high"},
            "stance": {"value": "deliberative", "confidence": "high", "reasoning": "先确认参数"},
        }
    )

    assert parsed is True
    assert raw == {"value": "deliberative", "confidence": "high", "reasoning": "先确认参数"}
    assert hint == {"value": "deliberative", "confidence": "high", "reasoning": "先确认参数"}


def test_stage2_stance_hint_missing_field_falls_back_to_directive():
    hint, raw, parsed = ClarificationContract._extract_llm_stance_hint({"slots": {}, "intent": {}})

    assert parsed is False
    assert raw is None
    assert hint == {
        "value": "directive",
        "confidence": "low",
        "reasoning": "missing stance fallback",
    }
