from core.analytical_objective import (
    AORelationship,
    AOStatus,
    AnalyticalObjective,
    ConversationalStance,
    IncompatibleSessionError,
    IntentConfidence,
    ParameterState,
    StanceConfidence,
    ToolIntent,
    ToolCallRecord,
)
import pytest


def test_ao_state_transition_created_active_completed():
    ao = AnalyticalObjective(
        ao_id="AO#1",
        session_id="s1",
        objective_text="查排放因子",
        status=AOStatus.CREATED,
        start_turn=1,
    )
    ao.status = AOStatus.ACTIVE
    ao.tool_call_log.append(
        ToolCallRecord(
            turn=1,
            tool="query_emission_factors",
            args_compact={"pollutant": "CO2"},
            success=True,
            result_ref="emission_factors:baseline",
            summary="ok",
        )
    )
    ao.status = AOStatus.COMPLETED
    ao.end_turn = 1

    assert ao.has_produced_expected_artifacts() is True
    assert ao.status == AOStatus.COMPLETED


def test_ao_state_transition_active_revising_completed():
    ao = AnalyticalObjective(
        ao_id="AO#2",
        session_id="s1",
        objective_text="算 NOx 排放",
        status=AOStatus.ACTIVE,
        start_turn=2,
        relationship=AORelationship.REVISION,
        parent_ao_id="AO#1",
    )

    ao.status = AOStatus.REVISING
    ao.tool_call_log.append(
        ToolCallRecord(
            turn=3,
            tool="calculate_macro_emission",
            args_compact={"season": "冬季"},
            success=True,
            result_ref="emission:baseline",
            summary="recomputed",
        )
    )
    ao.status = AOStatus.COMPLETED

    assert ao.relationship == AORelationship.REVISION
    assert ao.parent_ao_id == "AO#1"
    assert ao.status == AOStatus.COMPLETED


def test_ao_failure_transition():
    ao = AnalyticalObjective(
        ao_id="AO#3",
        session_id="s1",
        objective_text="做扩散",
        status=AOStatus.ACTIVE,
        start_turn=4,
    )
    ao.status = AOStatus.FAILED
    ao.failure_reason = "tool execution failed"

    assert ao.status == AOStatus.FAILED
    assert ao.failure_reason == "tool execution failed"


def test_tool_call_record_round_trip():
    record = ToolCallRecord(
        turn=5,
        tool="calculate_dispersion",
        args_compact={"pollutant": "NOx"},
        success=True,
        result_ref="dispersion:NOx",
        summary="done",
    )

    payload = record.to_dict()
    restored = ToolCallRecord.from_dict(payload)

    assert restored == record


def test_ao_from_phase24_dict_raises_incompatible_session_error():
    payload = {
        "ao_id": "AO#legacy",
        "session_id": "legacy-session",
        "objective_text": "Legacy objective",
        "status": "completed",
        "start_turn": 1,
        "tool_call_log": [
            {
                "turn": 1,
                "tool": "query_emission_factors",
                "args_compact": {"vehicle_type": "Passenger Car"},
                "success": True,
                "result_ref": "emission_factors:baseline",
                "summary": "legacy",
            }
        ],
    }

    with pytest.raises(IncompatibleSessionError, match="migrate_phase_2_4_to_2r"):
        AnalyticalObjective.from_dict(payload)


def test_ao_first_class_state_round_trip():
    ao = AnalyticalObjective(
        ao_id="AO#4",
        session_id="s1",
        objective_text="确认参数后查因子",
        status=AOStatus.ACTIVE,
        start_turn=1,
        tool_intent=ToolIntent(
            resolved_tool="query_emission_factors",
            confidence=IntentConfidence.HIGH,
            evidence=["rule:wants_factor_strict"],
            resolved_at_turn=1,
            resolved_by="rule:wants_factor_strict",
        ),
        parameter_state=ParameterState(
            required_filled={"vehicle_type", "pollutants"},
            optional_filled={"season"},
            awaiting_slot="model_year",
            collection_mode=True,
            collection_mode_reason="confirm_first_signal",
            probe_turn_count=1,
        ),
        stance=ConversationalStance.DELIBERATIVE,
        stance_confidence=StanceConfidence.HIGH,
        stance_resolved_by="rule:deliberative_signal",
        stance_history=[(1, ConversationalStance.DELIBERATIVE)],
    )

    restored = AnalyticalObjective.from_dict(ao.to_dict())

    assert restored.tool_intent.resolved_tool == "query_emission_factors"
    assert restored.tool_intent.confidence == IntentConfidence.HIGH
    assert restored.parameter_state.collection_mode is True
    assert restored.parameter_state.awaiting_slot == "model_year"
    assert restored.parameter_state.required_filled == {"vehicle_type", "pollutants"}
    assert restored.stance == ConversationalStance.DELIBERATIVE
    assert restored.stance_confidence == StanceConfidence.HIGH
    assert restored.stance_resolved_by == "rule:deliberative_signal"
    assert restored.stance_history == [(1, ConversationalStance.DELIBERATIVE)]


def test_ao_from_metadata_migrates_first_class_state():
    restored = AnalyticalObjective.from_dict(
        {
            "ao_id": "AO#metadata",
            "session_id": "legacy-session",
            "objective_text": "查因子",
            "status": "active",
            "start_turn": 1,
            "stance": "directive",
            "stance_confidence": "low",
            "stance_resolved_by": "migration:test_fixture",
            "stance_history": [{"turn": 1, "stance": "directive"}],
            "metadata": {
                "collection_mode": True,
                "pcm_trigger_reason": "missing_required_at_first_turn",
                "clarification_contract": {
                    "tool_name": "query_emission_factors",
                    "pending": True,
                    "missing_slots": ["model_year"],
                    "probe_turn_count": 1,
                },
            },
        }
    )

    assert restored.tool_intent.resolved_tool == "query_emission_factors"
    assert restored.tool_intent.confidence == IntentConfidence.HIGH
    assert restored.tool_intent.resolved_by == "migration:metadata"
    assert restored.parameter_state.collection_mode is True
    assert restored.parameter_state.collection_mode_reason == "missing_required_at_first_turn"
    assert restored.parameter_state.awaiting_slot == "model_year"
    assert restored.parameter_state.probe_turn_count == 1
