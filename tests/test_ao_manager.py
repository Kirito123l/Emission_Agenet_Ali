import os

from core.analytical_objective import AORelationship, AOStatus, IntentConfidence, ToolCallRecord
from core.ao_manager import AOManager, TurnOutcome
from config import reset_config
from core.memory import FactMemory


def _make_manager() -> AOManager:
    return AOManager(FactMemory(session_id="ao-session"))


def test_create_ao_with_independent_relationship():
    manager = _make_manager()
    ao = manager.create_ao(
        objective_text="查 CO2 因子",
        relationship=AORelationship.INDEPENDENT,
        current_turn=1,
    )

    assert ao.ao_id == "AO#1"
    assert ao.status == AOStatus.ACTIVE
    assert manager.get_current_ao().ao_id == "AO#1"


def test_complete_ao_requires_all_conditions():
    manager = _make_manager()
    ao = manager.create_ao(
        objective_text="算排放",
        relationship=AORelationship.INDEPENDENT,
        current_turn=1,
    )
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

    incomplete = manager.complete_ao(
        ao.ao_id,
        end_turn=1,
        turn_outcome=TurnOutcome(
            tool_chain_succeeded=True,
            final_response_delivered=True,
            is_clarification=True,
            is_parameter_negotiation=False,
            is_partial_delivery=False,
        ),
    )
    complete = manager.complete_ao(
        ao.ao_id,
        end_turn=1,
        turn_outcome=TurnOutcome(
            tool_chain_succeeded=True,
            final_response_delivered=True,
            is_clarification=False,
            is_parameter_negotiation=False,
            is_partial_delivery=False,
        ),
    )

    assert incomplete is False
    assert complete is True
    assert manager.get_ao_by_id(ao.ao_id).status == AOStatus.COMPLETED


def test_revise_ao_keeps_parent_unchanged():
    manager = _make_manager()
    parent = manager.create_ao(
        objective_text="AO parent",
        relationship=AORelationship.INDEPENDENT,
        current_turn=1,
    )
    manager.append_tool_call(
        parent.ao_id,
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
        parent.ao_id,
        end_turn=1,
        turn_outcome=TurnOutcome(
            tool_chain_succeeded=True,
            final_response_delivered=True,
            is_clarification=False,
            is_parameter_negotiation=False,
            is_partial_delivery=False,
        ),
    )

    revision = manager.revise_ao(
        parent_ao_id=parent.ao_id,
        revised_objective_text="改成冬季再算",
        current_turn=2,
    )

    assert parent.status == AOStatus.COMPLETED
    assert revision.parent_ao_id == parent.ao_id
    assert revision.status == AOStatus.REVISING


def test_append_tool_call_and_block_summary():
    manager = _make_manager()
    ao = manager.create_ao(
        objective_text="做扩散",
        relationship=AORelationship.INDEPENDENT,
        current_turn=1,
    )
    manager.append_tool_call(
        ao.ao_id,
        ToolCallRecord(
            turn=1,
            tool="calculate_dispersion",
            args_compact={"pollutant": "NOx"},
            success=True,
            result_ref="dispersion:NOx",
            summary="ok",
        ),
    )
    manager.register_artifact(ao.ao_id, "dispersion", "NOx")

    summary = manager.get_summary_for_block()

    assert summary["current_ao"]["tool_call_log"][0]["tool"] == "calculate_dispersion"
    assert summary["current_ao"]["artifacts_produced"]["dispersion"] == "dispersion:NOx"


def test_multistep_objective_does_not_complete_after_first_tool():
    manager = _make_manager()
    ao = manager.create_ao(
        objective_text="先算排放再做扩散",
        relationship=AORelationship.INDEPENDENT,
        current_turn=1,
    )
    manager.append_tool_call(
        ao.ao_id,
        ToolCallRecord(
            turn=1,
            tool="calculate_macro_emission",
            args_compact={"pollutant": "CO2"},
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
            is_partial_delivery=False,
        ),
    )

    assert completed is False
    assert manager.get_ao_by_id(ao.ao_id).status == AOStatus.ACTIVE


def test_single_step_factor_query_completes_normally():
    manager = _make_manager()
    ao = manager.create_ao(
        objective_text="查 CO2 排放因子",
        relationship=AORelationship.INDEPENDENT,
        current_turn=1,
    )
    manager.append_tool_call(
        ao.ao_id,
        ToolCallRecord(
            turn=1,
            tool="query_emission_factors",
            args_compact={"pollutant": "CO2"},
            success=True,
            result_ref="emission_factors:baseline",
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
            is_partial_delivery=False,
        ),
    )

    assert completed is True
    assert manager.get_ao_by_id(ao.ao_id).status == AOStatus.COMPLETED


def test_three_step_objective_completes_after_all_implied_tools_run():
    manager = _make_manager()
    ao = manager.create_ao(
        objective_text="算排放并做扩散然后找热点",
        relationship=AORelationship.INDEPENDENT,
        current_turn=1,
    )
    for turn, tool, result_ref in [
        (1, "calculate_macro_emission", "emission:baseline"),
        (2, "calculate_dispersion", "dispersion:baseline"),
        (3, "analyze_hotspots", "hotspot:baseline"),
    ]:
        manager.append_tool_call(
            ao.ao_id,
            ToolCallRecord(
                turn=turn,
                tool=tool,
                args_compact={},
                success=True,
                result_ref=result_ref,
                summary="ok",
            ),
        )

    completed = manager.complete_ao(
        ao.ao_id,
        end_turn=3,
        turn_outcome=TurnOutcome(
            tool_chain_succeeded=True,
            final_response_delivered=True,
            is_clarification=False,
            is_parameter_negotiation=False,
            is_partial_delivery=False,
        ),
    )

    assert completed is True
    assert manager.get_ao_by_id(ao.ao_id).status == AOStatus.COMPLETED


def test_pending_clarification_blocks_completion():
    manager = _make_manager()
    ao = manager.create_ao(
        objective_text="查 CO2 因子",
        relationship=AORelationship.INDEPENDENT,
        current_turn=1,
    )
    ao.metadata["clarification_contract"] = {"pending": True}
    manager.append_tool_call(
        ao.ao_id,
        ToolCallRecord(
            turn=1,
            tool="query_emission_factors",
            args_compact={"pollutant": "CO2"},
            success=True,
            result_ref="emission_factors:baseline",
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
            is_partial_delivery=False,
        ),
    )

    assert completed is False
    assert manager.get_ao_by_id(ao.ao_id).status == AOStatus.ACTIVE


def test_collection_mode_blocks_implicit_create_completion():
    manager = _make_manager()
    active = manager.create_ao(
        objective_text="确认参数后查因子",
        relationship=AORelationship.INDEPENDENT,
        current_turn=1,
    )
    manager.append_tool_call(
        active.ao_id,
        ToolCallRecord(
            turn=1,
            tool="query_emission_factors",
            args_compact={"pollutant": "CO2"},
            success=True,
            result_ref="emission_factors:baseline",
            summary="ok",
        ),
    )
    active.parameter_state.collection_mode = True
    active.parameter_state.awaiting_slot = "model_year"

    created = manager.create_ao(
        objective_text="新任务",
        relationship=AORelationship.INDEPENDENT,
        current_turn=2,
    )

    events = manager.telemetry_slice()
    blocked = [event for event in events if event["event_type"] == "complete_blocked"]
    assert active.status == AOStatus.ACTIVE
    assert created.ao_id == "AO#2"
    assert blocked[-1]["completion_path"] == "create_ao_implicit"
    assert blocked[-1]["block_reason"] == "collection_mode_active"
    assert blocked[-1]["parameter_state_collection_mode"] is True
    assert blocked[-1]["parameter_state_awaiting_slot"] == "model_year"


def test_unresolved_intent_blocks_implicit_create_completion():
    manager = _make_manager()
    active = manager.create_ao(
        objective_text="待解析意图",
        relationship=AORelationship.INDEPENDENT,
        current_turn=1,
    )
    manager.append_tool_call(
        active.ao_id,
        ToolCallRecord(
            turn=1,
            tool="query_emission_factors",
            args_compact={"pollutant": "CO2"},
            success=True,
            result_ref="emission_factors:baseline",
            summary="ok",
        ),
    )
    active.tool_intent.confidence = IntentConfidence.NONE
    active.tool_intent.resolved_tool = None
    active.tool_intent.resolved_by = None

    manager.create_ao(
        objective_text="新任务",
        relationship=AORelationship.INDEPENDENT,
        current_turn=2,
    )

    blocked = [event for event in manager.telemetry_slice() if event["event_type"] == "complete_blocked"]
    assert active.status == AOStatus.ACTIVE
    assert blocked[-1]["completion_path"] == "create_ao_implicit"
    assert blocked[-1]["block_reason"] == "intent_not_resolved"
    assert blocked[-1]["tool_intent_confidence"] == "none"


def test_satisfied_active_ao_completes_on_implicit_create():
    manager = _make_manager()
    active = manager.create_ao(
        objective_text="查 CO2 因子",
        relationship=AORelationship.INDEPENDENT,
        current_turn=1,
    )
    manager.append_tool_call(
        active.ao_id,
        ToolCallRecord(
            turn=1,
            tool="query_emission_factors",
            args_compact={"pollutant": "CO2"},
            success=True,
            result_ref="emission_factors:baseline",
            summary="ok",
        ),
    )

    created = manager.create_ao(
        objective_text="新任务",
        relationship=AORelationship.INDEPENDENT,
        current_turn=2,
    )

    complete_events = [event for event in manager.telemetry_slice() if event["event_type"] == "complete"]
    assert active.status == AOStatus.COMPLETED
    assert created.ao_id == "AO#2"
    assert complete_events[-1]["completion_path"] == "create_ao_implicit"
    assert complete_events[-1]["block_reason"] is None


def test_execution_continuation_blocks_completion_under_split():
    os.environ["ENABLE_CONTRACT_SPLIT"] = "true"
    reset_config()
    manager = _make_manager()
    ao = manager.create_ao(
        objective_text="先算再扩散",
        relationship=AORelationship.INDEPENDENT,
        current_turn=1,
    )
    ao.tool_intent.confidence = IntentConfidence.HIGH
    ao.tool_intent.resolved_tool = "calculate_macro_emission"
    ao.metadata["execution_continuation"] = {
        "pending_objective": "chain_continuation",
        "pending_next_tool": "calculate_dispersion",
        "pending_tool_queue": ["calculate_dispersion"],
    }
    manager.append_tool_call(
        ao.ao_id,
        ToolCallRecord(
            turn=1,
            tool="calculate_macro_emission",
            args_compact={"pollutants": ["NOx"]},
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
            is_partial_delivery=False,
        ),
    )

    assert completed is False
    blocked = [event for event in manager.telemetry_slice() if event["event_type"] == "complete_blocked"]
    assert blocked[-1]["block_reason"] == "execution_continuation_active"
    assert blocked[-1]["complete_check_results"]["execution_continuation_active"] is True
    os.environ.pop("ENABLE_CONTRACT_SPLIT", None)
    reset_config()


def test_execution_continuation_yields_to_implicit_create_completion():
    """Phase 8.1.4e: chain continuation yields when a new AO is created.

    When create_ao is called with an ACTIVE AO that has pending chain
    continuation, the old AO is force-completed (not blocked) because
    the new AO overrides the pending chain.
    """
    os.environ["ENABLE_CONTRACT_SPLIT"] = "true"
    reset_config()
    manager = _make_manager()
    active = manager.create_ao(
        objective_text="先算再扩散",
        relationship=AORelationship.INDEPENDENT,
        current_turn=1,
    )
    active.tool_intent.confidence = IntentConfidence.HIGH
    active.tool_intent.resolved_tool = "calculate_macro_emission"
    active.metadata["execution_continuation"] = {
        "pending_objective": "chain_continuation",
        "pending_next_tool": "calculate_dispersion",
        "pending_tool_queue": ["calculate_dispersion", "render_spatial_map"],
    }
    manager.append_tool_call(
        active.ao_id,
        ToolCallRecord(
            turn=1,
            tool="calculate_macro_emission",
            args_compact={"pollutants": ["NOx"]},
            success=True,
            result_ref="emission:baseline",
            summary="ok",
        ),
    )

    created = manager.create_ao(
        objective_text="新任务",
        relationship=AORelationship.INDEPENDENT,
        current_turn=2,
    )

    # Phase 8.1.4e: old AO is COMPLETED (chain continuation yielded to new AO)
    completed = [e for e in manager.telemetry_slice() if e["event_type"] == "complete"]
    assert active.status == AOStatus.COMPLETED
    assert created.ao_id == "AO#2"
    # Verify the old AO was completed via create_ao_implicit path
    implicit_completes = [e for e in completed if e.get("completion_path") == "create_ao_implicit"]
    assert len(implicit_completes) >= 1
    os.environ.pop("ENABLE_CONTRACT_SPLIT", None)
    reset_config()


def test_complete_check_results_include_execution_continuation_snapshot():
    os.environ["ENABLE_CONTRACT_SPLIT"] = "true"
    reset_config()
    manager = _make_manager()
    ao = manager.create_ao(
        objective_text="继续做图",
        relationship=AORelationship.INDEPENDENT,
        current_turn=1,
    )
    ao.tool_intent.confidence = IntentConfidence.HIGH
    ao.tool_intent.resolved_tool = "render_spatial_map"
    ao.metadata["execution_continuation"] = {
        "pending_objective": "chain_continuation",
        "pending_next_tool": "render_spatial_map",
        "pending_tool_queue": ["render_spatial_map"],
    }

    check_results = manager._build_complete_check_results(ao, turn_outcome=None)

    assert check_results["execution_continuation_active"] is True
    assert check_results["execution_continuation"]["pending_next_tool"] == "render_spatial_map"
    os.environ.pop("ENABLE_CONTRACT_SPLIT", None)
    reset_config()
