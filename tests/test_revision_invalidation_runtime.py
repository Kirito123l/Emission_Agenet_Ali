"""Phase 6.E.4C — Runtime integration for revision invalidation.

These tests exercise the ExecutionReadinessContract integration point.  They
verify metadata and AOExecutionState mutation only; E.4C must not dispatch,
force, or suppress tool execution directly.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.expanduser("~/Agent1/emission_agent"))

from core.analytical_objective import (
    AORelationship,
    AOStatus,
    AnalyticalObjective,
    CanonicalExecutionDecision,
    ConversationalStance,
    ExecutionStepStatus,
    IdempotencyDecision,
    IntentConfidence,
    RevisionDeltaDecisionPreview,
    ToolCallRecord,
    ToolIntent,
)
from core.ao_classifier import AOClassification, AOClassType
from core.ao_manager import AOManager, ensure_execution_state
from core.contracts.base import ContractContext
from core.contracts.execution_readiness_contract import ExecutionReadinessContract
from core.execution_continuation import ExecutionContinuation, PendingObjective
from core.execution_continuation_utils import load_execution_continuation, save_execution_continuation
from core.memory import FactMemory
from core.task_state import TaskState


class FakeInnerRouter:
    def __init__(self, hints: dict):
        self.session_id = "revision-runtime-session"
        self.memory = SimpleNamespace(
            fact_memory=FactMemory(session_id=self.session_id),
            turn_counter=2,
        )
        self._hints = dict(hints)
        self._continuation_bundle = {
            "plan": None,
            "residual_plan_summary": None,
            "latest_repair_summary": None,
        }

    def _extract_message_execution_hints(self, state):
        return dict(self._hints)

    def _load_active_input_completion_request(self):
        return None

    def _load_active_parameter_negotiation_request(self):
        return None

    def _ensure_live_continuation_bundle(self):
        return self._continuation_bundle


def _mock_config(*, canonical=True, revision=True, idempotency=False):
    cfg = MagicMock()
    cfg.enable_contract_split = True
    cfg.enable_split_readiness_contract = True
    cfg.enable_split_intent_contract = True
    cfg.enable_split_stance_contract = True
    cfg.enable_split_continuation_state = True
    cfg.enable_llm_decision_field = False
    cfg.enable_runtime_default_aware_readiness = True
    cfg.enable_cross_constraint_validation = True
    cfg.enable_clarification_stage2_llm = False
    cfg.clarification_llm_confidence_threshold = 0.7
    cfg.enable_canonical_execution_state = canonical
    cfg.enable_revision_invalidation = revision
    cfg.enable_execution_idempotency = idempotency
    return cfg


def _classification(kind=AOClassType.CONTINUATION):
    return AOClassification(
        classification=kind,
        target_ao_id=None,
        reference_ao_id=None,
        new_objective_text="runtime revision",
        confidence=1.0,
        reasoning="test",
        layer="rule",
    )


def _context(message: str, *, tool_name: str, chain: list[str]):
    return ContractContext(
        user_message=message,
        file_path="/tmp/links.csv",
        trace={},
        state_snapshot=TaskState(user_message=message, session_id="revision-runtime-session"),
        metadata={
            "oasc": {"classification": _classification()},
            "tool_intent": ToolIntent(
                resolved_tool=tool_name,
                confidence=IntentConfidence.HIGH,
                projected_chain=list(chain),
            ),
        },
    )


def _make_contract(hints: dict, cfg):
    inner = FakeInnerRouter(hints)
    manager = AOManager(inner.memory.fact_memory)
    contract = ExecutionReadinessContract(
        inner_router=inner,
        ao_manager=manager,
        runtime_config=cfg,
    )
    return contract, manager


def _make_ao(manager: AOManager, *, tool_name="calculate_macro_emission"):
    ao = manager.create_ao(
        "runtime revision objective",
        AORelationship.INDEPENDENT,
        current_turn=1,
    )
    ao.status = AOStatus.ACTIVE
    ao.stance = ConversationalStance.DIRECTIVE
    ao.tool_intent = ToolIntent(
        resolved_tool=tool_name,
        confidence=IntentConfidence.HIGH,
        projected_chain=["calculate_macro_emission", "calculate_dispersion"],
    )
    return ao


def _seed_completed_macro_dispersion(ao: AnalyticalObjective, cfg):
    ao.tool_call_log = [
        ToolCallRecord(
            turn=1,
            tool="calculate_macro_emission",
            args_compact={
                "pollutants": ["NOx"],
                "season": "夏季",
                "file_path": "/tmp/links.csv",
            },
            success=True,
            result_ref="macro_emission:nox",
            summary="ok",
        ),
        ToolCallRecord(
            turn=2,
            tool="calculate_dispersion",
            args_compact={
                "pollutant": "NOx",
                "meteorology": "windy_neutral",
                "file_path": "/tmp/links.csv",
            },
            success=True,
            result_ref="dispersion:nox",
            summary="ok",
        ),
    ]
    seed_cfg = _mock_config(canonical=True, revision=True)
    with patch("config.get_config", return_value=seed_cfg):
        state = ensure_execution_state(ao)
        assert state is not None
        ao.metadata["execution_state"] = state.to_dict()


async def _run_readiness(hints: dict, cfg, *, tool_name: str, message: str):
    contract, manager = _make_contract(hints, cfg)
    ao = _make_ao(manager, tool_name=tool_name)
    _seed_completed_macro_dispersion(ao, cfg)
    context = _context(
        message,
        tool_name=tool_name,
        chain=["calculate_macro_emission", "calculate_dispersion"],
    )
    with patch("config.get_config", return_value=cfg):
        interception = await contract.before_turn(context)
    return context, interception, ao, manager


def _state(ao):
    state = ensure_execution_state(ao)
    assert state is not None
    return state


@pytest.mark.anyio
async def test_flags_off_no_telemetry_no_invalidation():
    cfg = _mock_config(canonical=False, revision=False)
    context, _, ao, _ = await _run_readiness(
        {"pollutants": ["CO2"]},
        cfg,
        tool_name="calculate_macro_emission",
        message="改成CO2",
    )

    assert "revision_delta_telemetry" not in context.metadata
    assert "revision_invalidation_result" not in context.metadata
    assert "last_revision_delta_telemetry" not in ao.metadata


@pytest.mark.anyio
async def test_canonical_flag_off_no_invalidation():
    cfg = _mock_config(canonical=False, revision=True)
    context, _, ao, _ = await _run_readiness(
        {"pollutants": ["CO2"]},
        cfg,
        tool_name="calculate_macro_emission",
        message="改成CO2",
    )

    assert "revision_delta_telemetry" not in context.metadata
    assert "revision_invalidation_result" not in context.metadata
    assert "last_revision_invalidation" not in ao.metadata


@pytest.mark.anyio
async def test_revision_flag_off_no_invalidation():
    cfg = _mock_config(canonical=True, revision=False)
    context, _, ao, _ = await _run_readiness(
        {"pollutants": ["CO2"]},
        cfg,
        tool_name="calculate_macro_emission",
        message="改成CO2",
    )

    assert "revision_delta_telemetry" not in context.metadata
    assert "revision_invalidation_result" not in context.metadata
    with patch("config.get_config", return_value=_mock_config(canonical=True, revision=True)):
        state = _state(ao)
        assert all(s.status == ExecutionStepStatus.COMPLETED for s in state.steps)


@pytest.mark.anyio
async def test_no_delta_telemetry_no_invalidation():
    cfg = _mock_config(canonical=True, revision=True)
    context, _, ao, _ = await _run_readiness(
        {"pollutants": ["NOx"]},
        cfg,
        tool_name="calculate_macro_emission",
        message="还是NOx",
    )

    assert context.metadata["revision_delta_telemetry"]["decision_preview"] == RevisionDeltaDecisionPreview.NO_DELTA
    assert "revision_invalidation_result" not in context.metadata
    with patch("config.get_config", return_value=cfg):
        assert all(s.status == ExecutionStepStatus.COMPLETED for s in _state(ao).steps)


@pytest.mark.anyio
async def test_rerun_same_params_no_invalidation():
    cfg = _mock_config(canonical=True, revision=True)
    context, _, ao, _ = await _run_readiness(
        {"pollutants": ["NOx"]},
        cfg,
        tool_name="calculate_macro_emission",
        message="重新算一遍NOx",
    )

    telemetry = context.metadata["revision_delta_telemetry"]
    assert telemetry["decision_preview"] == RevisionDeltaDecisionPreview.RERUN_SAME_PARAMS
    assert "revision_invalidation_result" not in context.metadata
    with patch("config.get_config", return_value=cfg):
        assert all(s.status == ExecutionStepStatus.COMPLETED for s in _state(ao).steps)


@pytest.mark.anyio
async def test_insufficient_evidence_no_invalidation():
    cfg = _mock_config(canonical=True, revision=True)
    context, _, ao, _ = await _run_readiness(
        {},
        cfg,
        tool_name="calculate_macro_emission",
        message="改一下",
    )

    telemetry = context.metadata["revision_delta_telemetry"]
    assert telemetry["decision_preview"] == RevisionDeltaDecisionPreview.INSUFFICIENT_EVIDENCE
    assert "revision_invalidation_result" not in context.metadata
    with patch("config.get_config", return_value=cfg):
        assert all(s.status == ExecutionStepStatus.COMPLETED for s in _state(ao).steps)


@pytest.mark.anyio
async def test_macro_pollutant_change_runtime_invalidates_macro_and_dispersion():
    cfg = _mock_config(canonical=True, revision=True)
    context, _, ao, _ = await _run_readiness(
        {"pollutants": ["CO2"]},
        cfg,
        tool_name="calculate_macro_emission",
        message="改成CO2",
    )

    telemetry = context.metadata["revision_delta_telemetry"]
    result = context.metadata["revision_invalidation_result"]
    assert "pollutants" in telemetry["changed_keys"]
    assert set(result["invalidated_tools"]) == {
        "calculate_macro_emission",
        "calculate_dispersion",
    }
    with patch("config.get_config", return_value=cfg):
        state = _state(ao)
        assert [s.status for s in state.steps] == [
            ExecutionStepStatus.INVALIDATED,
            ExecutionStepStatus.INVALIDATED,
        ]
        assert all(s.result_ref is None for s in state.steps)
        assert state.steps[0].provenance["stale_result_ref"] == "macro_emission:nox"
        assert state.steps[1].provenance["stale_result_ref"] == "dispersion:nox"


@pytest.mark.anyio
async def test_macro_invalidation_sets_chain_cursor_zero():
    cfg = _mock_config(canonical=True, revision=True)
    _, _, ao, _ = await _run_readiness(
        {"pollutants": ["CO2"]},
        cfg,
        tool_name="calculate_macro_emission",
        message="改成CO2",
    )

    with patch("config.get_config", return_value=cfg):
        assert _state(ao).chain_cursor == 0


@pytest.mark.anyio
async def test_dispersion_meteorology_runtime_invalidates_dispersion_only():
    cfg = _mock_config(canonical=True, revision=True)
    context, _, ao, _ = await _run_readiness(
        {"meteorology": "urban_summer_day", "pollutants": ["NOx"]},
        cfg,
        tool_name="calculate_dispersion",
        message="扩散气象改成urban_summer_day",
    )

    telemetry = context.metadata["revision_delta_telemetry"]
    result = context.metadata["revision_invalidation_result"]
    assert "meteorology" in telemetry["changed_keys"]
    assert result["invalidated_tools"] == ["calculate_dispersion"]
    with patch("config.get_config", return_value=cfg):
        state = _state(ao)
        assert state.steps[0].status == ExecutionStepStatus.COMPLETED
        assert state.steps[1].status == ExecutionStepStatus.INVALIDATED


@pytest.mark.anyio
async def test_dispersion_only_invalidation_cursor_one_preserves_macro_ref():
    cfg = _mock_config(canonical=True, revision=True)
    _, _, ao, _ = await _run_readiness(
        {"meteorology": "urban_summer_day", "pollutants": ["NOx"]},
        cfg,
        tool_name="calculate_dispersion",
        message="扩散气象改成urban_summer_day",
    )

    with patch("config.get_config", return_value=cfg):
        state = _state(ao)
        assert state.chain_cursor == 1
        assert state.steps[0].result_ref == "macro_emission:nox"
        assert state.steps[1].result_ref is None
        assert state.steps[1].provenance["stale_result_ref"] == "dispersion:nox"


@pytest.mark.anyio
async def test_runtime_metadata_contains_delta_and_invalidation_result():
    cfg = _mock_config(canonical=True, revision=True)
    context, _, ao, _ = await _run_readiness(
        {"pollutants": ["CO2"]},
        cfg,
        tool_name="calculate_macro_emission",
        message="改成CO2",
    )

    assert "revision_delta_telemetry" in context.metadata
    assert "revision_invalidation_result" in context.metadata
    assert "last_revision_delta_telemetry" in ao.metadata
    assert "last_revision_invalidation" in ao.metadata
    result = context.metadata["revision_invalidation_result"]
    assert result["previous_chain_cursor"] == 2
    assert result["new_chain_cursor"] == 0
    assert result["revision_epoch"] == 1
    assert result["reason"]


@pytest.mark.anyio
async def test_invalidated_step_not_treated_as_completed_by_canonical_decision():
    cfg = _mock_config(canonical=True, revision=True)
    _, _, ao, manager = await _run_readiness(
        {"pollutants": ["CO2"]},
        cfg,
        tool_name="calculate_macro_emission",
        message="改成CO2",
    )

    with patch("config.get_config", return_value=cfg):
        result = manager.check_canonical_execution_state(
            ao,
            proposed_tool="calculate_macro_emission",
        )
    assert result.decision == CanonicalExecutionDecision.PROCEED


@pytest.mark.anyio
async def test_invalidated_step_not_suppressed_by_phase61_idempotency():
    cfg = _mock_config(canonical=True, revision=True, idempotency=True)
    _, _, ao, manager = await _run_readiness(
        {"pollutants": ["CO2"]},
        cfg,
        tool_name="calculate_macro_emission",
        message="改成CO2",
    )

    with patch("config.get_config", return_value=cfg):
        idem = manager.check_execution_idempotency(
            ao,
            proposed_tool="calculate_macro_emission",
            proposed_args={"pollutants": ["NOx"], "file_path": "/tmp/links.csv"},
            user_message="NOx",
        )
    assert idem.decision != IdempotencyDecision.EXACT_DUPLICATE


@pytest.mark.anyio
async def test_tool_call_log_unchanged_during_runtime_invalidation():
    cfg = _mock_config(canonical=True, revision=True)
    contract, manager = _make_contract({"pollutants": ["CO2"]}, cfg)
    ao = _make_ao(manager, tool_name="calculate_macro_emission")
    _seed_completed_macro_dispersion(ao, cfg)
    before = [(r.turn, r.tool, dict(r.args_compact), r.result_ref) for r in ao.tool_call_log]
    context = _context(
        "CO2",
        tool_name="calculate_macro_emission",
        chain=["calculate_macro_emission", "calculate_dispersion"],
    )

    with patch("config.get_config", return_value=cfg):
        await contract.before_turn(context)

    after = [(r.turn, r.tool, dict(r.args_compact), r.result_ref) for r in ao.tool_call_log]
    assert after == before


@pytest.mark.anyio
async def test_execution_continuation_unchanged_during_runtime_invalidation():
    cfg = _mock_config(canonical=True, revision=True)
    contract, manager = _make_contract({"pollutants": ["CO2"]}, cfg)
    ao = _make_ao(manager, tool_name="calculate_macro_emission")
    _seed_completed_macro_dispersion(ao, cfg)
    cont = ExecutionContinuation(
        pending_objective=PendingObjective.CHAIN_CONTINUATION,
        pending_next_tool="calculate_macro_emission",
        pending_tool_queue=["calculate_macro_emission", "calculate_dispersion"],
        updated_turn=1,
    )
    save_execution_continuation(ao, cont)
    before = load_execution_continuation(ao).to_dict()
    context = _context(
        "CO2",
        tool_name="calculate_macro_emission",
        chain=["calculate_macro_emission", "calculate_dispersion"],
    )

    with patch("config.get_config", return_value=cfg):
        await contract.before_turn(context)

    after = load_execution_continuation(ao).to_dict()
    assert after == before


@pytest.mark.anyio
async def test_scope_expansion_detected_no_mutation():
    cfg = _mock_config(canonical=True, revision=True)
    context, _, ao, _ = await _run_readiness(
        {"pollutants": ["NOx", "CO2"]},
        cfg,
        tool_name="calculate_macro_emission",
        message="NOx再加CO2",
    )

    telemetry = context.metadata["revision_delta_telemetry"]
    assert telemetry["scope_expansion_detected"] is True
    assert "revision_invalidation_result" not in context.metadata
    with patch("config.get_config", return_value=cfg):
        assert all(s.status == ExecutionStepStatus.COMPLETED for s in _state(ao).steps)
