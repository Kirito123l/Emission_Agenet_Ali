"""Phase 4 Step 4.5: PCM advisory mode tests (flag=true).

These tests verify that when ENABLE_LLM_DECISION_FIELD=true:
- PCM computes advisory instead of hard-blocking
- pcm_advisory is in telemetry/metadata
- No hardcoded_recommendation is generated for optional-only probes
- flag=false preserves existing hard-blocking behavior
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from config import get_config, reset_config
from core.ao_classifier import AOClassification, AOClassType
from core.ao_manager import AOManager
from core.analytical_objective import AORelationship
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
        self.session_id = "pcm-advisory-session"
        self.memory = SimpleNamespace(
            fact_memory=FactMemory(session_id="pcm-advisory-session"), turn_counter=0
        )
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


def _new_ao_context(contract, manager, user_message, ao_text="测试参数"):
    """Create a fresh AO and ContractContext for a first-turn NEW_AO request."""
    ao = manager.create_ao(ao_text, AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState(user_message=user_message, session_id="pcm-advisory-session")
    context = ContractContext(
        user_message=user_message,
        file_path=None,
        trace={},
        state_snapshot=state,
        metadata={
            "oasc": {
                "classification": AOClassification(
                    classification=AOClassType.NEW_AO,
                    target_ao_id=None,
                    reference_ao_id=None,
                    new_objective_text=ao_text,
                    confidence=1.0,
                    reasoning="test",
                    layer="rule",
                )
            }
        },
    )
    return ao, state, context


# ── flag=true: Advisory mode tests ──────────────────────────────────────────


@pytest.mark.anyio
async def test_pcm_emits_advisory_when_flag_active():
    """flag=true: PCM computes advisory, does NOT hard-block."""
    hints = {
        "wants_factor": True,
        "desired_tool_chain": ["query_emission_factors"],
        "vehicle_type": "Transit Bus",
        "vehicle_type_raw": "公交车",
        "pollutants": ["CO2"],
    }
    contract, manager, _inner = _make_contract(hints, llm_payload={})
    contract.runtime_config.enable_llm_decision_field = True

    ao, state, context = _new_ao_context(
        contract, manager, "查询公交车CO2的排放因子"
    )

    interception = await contract.before_turn(context)

    telemetry = interception.metadata["clarification"]["telemetry"]
    # Should NOT hard-block
    assert interception.proceed is True, "flag=true should not hard-block PCM"
    # Advisory should be in telemetry
    assert telemetry.get("pcm_advisory") is not None, "pcm_advisory missing from telemetry"
    advisory = telemetry["pcm_advisory"]
    assert advisory["collection_mode_active"] is True
    assert "model_year" in advisory["unfilled_optionals_without_default"]
    assert advisory["runtime_defaults_available"].get("model_year") == 2020


@pytest.mark.anyio
async def test_pcm_advisory_includes_runtime_defaults_available():
    """flag=true: advisory correctly identifies runtime defaults for unfilled optionals."""
    hints = {
        "wants_factor": True,
        "desired_tool_chain": ["query_emission_factors"],
        "vehicle_type": "Transit Bus",
        "vehicle_type_raw": "公交车",
        "pollutants": ["CO2"],
    }
    contract, manager, _inner = _make_contract(hints, llm_payload={})
    contract.runtime_config.enable_llm_decision_field = True

    ao, state, context = _new_ao_context(
        contract, manager, "查询公交车CO2的排放因子"
    )

    interception = await contract.before_turn(context)

    telemetry = interception.metadata["clarification"]["telemetry"]
    advisory = telemetry["pcm_advisory"]
    assert advisory["unfilled_optionals_without_default"] == ["model_year"]
    assert advisory["runtime_defaults_available"] == {"model_year": 2020}
    assert advisory["confirm_first_detected"] is False
    assert advisory["suggested_probe_slot"] == "model_year"


@pytest.mark.anyio
async def test_pcm_no_hardcoded_recommendation_under_flag_true():
    """flag=true: optional-only PCM does not produce hardcoded_recommendation."""
    hints = {
        "wants_factor": True,
        "desired_tool_chain": ["query_emission_factors"],
        "vehicle_type": "Transit Bus",
        "vehicle_type_raw": "公交车",
        "pollutants": ["CO2"],
    }
    contract, manager, _inner = _make_contract(hints, llm_payload={})
    contract.runtime_config.enable_llm_decision_field = True

    ao, state, context = _new_ao_context(
        contract, manager, "查询公交车CO2的排放因子"
    )

    interception = await contract.before_turn(context)

    assert "hardcoded_recommendation" not in interception.metadata
    assert interception.metadata.get("hardcoded_reason") is None


@pytest.mark.anyio
async def test_pcm_advisory_proceed_mode_is_context_injection():
    """flag=true: advisory path reaches context_injection proceed mode."""
    hints = {
        "wants_factor": True,
        "desired_tool_chain": ["query_emission_factors"],
        "vehicle_type": "Transit Bus",
        "vehicle_type_raw": "公交车",
        "pollutants": ["CO2"],
    }
    contract, manager, _inner = _make_contract(hints, llm_payload={})
    contract.runtime_config.enable_llm_decision_field = True

    ao, state, context = _new_ao_context(
        contract, manager, "查询公交车CO2的排放因子"
    )

    interception = await contract.before_turn(context)

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert telemetry["final_decision"] == "proceed"
    assert telemetry["proceed_mode"] == "context_injection"
    assert "direct_execution" in interception.metadata["clarification"]


@pytest.mark.anyio
async def test_pcm_advisory_collection_mode_telemetry_preserved():
    """flag=true: collection_mode and pcm_trigger_reason still recorded for trace."""
    hints = {
        "wants_factor": True,
        "desired_tool_chain": ["query_emission_factors"],
        "vehicle_type": "Transit Bus",
        "vehicle_type_raw": "公交车",
        "pollutants": ["CO2"],
    }
    contract, manager, _inner = _make_contract(hints, llm_payload={})
    contract.runtime_config.enable_llm_decision_field = True

    ao, state, context = _new_ao_context(
        contract, manager, "查询公交车CO2的排放因子"
    )

    interception = await contract.before_turn(context)

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert telemetry["collection_mode"] is True
    assert telemetry["pcm_trigger_reason"] == "unfilled_optional_no_default_at_first_turn"


# ── flag=false: Backward-compat tests ────────────────────────────────────────


@pytest.mark.anyio
async def test_pcm_flag_false_preserves_hard_blocking():
    """flag=false (default): PCM still hard-blocks for unfilled optionals."""
    hints = {
        "wants_factor": True,
        "desired_tool_chain": ["query_emission_factors"],
        "vehicle_type": "Transit Bus",
        "vehicle_type_raw": "公交车",
        "pollutants": ["CO2"],
    }
    contract, manager, _inner = _make_contract(hints, llm_payload={})
    # flag=false is the default from reset_config()

    ao, state, context = _new_ao_context(
        contract, manager, "查询公交车CO2的排放因子"
    )

    interception = await contract.before_turn(context)

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert interception.proceed is False, "flag=false should hard-block"
    assert telemetry["collection_mode"] is True
    assert telemetry["probe_optional_slot"] == "model_year"
    assert telemetry["final_decision"] == "clarify"


@pytest.mark.anyio
async def test_pcm_flag_false_no_pcm_advisory_in_telemetry():
    """flag=false: pcm_advisory field is None (not populated)."""
    hints = {
        "wants_factor": True,
        "desired_tool_chain": ["query_emission_factors"],
        "vehicle_type": "Transit Bus",
        "vehicle_type_raw": "公交车",
        "pollutants": ["CO2"],
    }
    contract, manager, _inner = _make_contract(hints, llm_payload={})

    ao, state, context = _new_ao_context(
        contract, manager, "查询公交车CO2的排放因子"
    )

    interception = await contract.before_turn(context)

    telemetry = interception.metadata["clarification"]["telemetry"]
    assert telemetry.get("pcm_advisory") is None, "flag=false should not populate pcm_advisory"
