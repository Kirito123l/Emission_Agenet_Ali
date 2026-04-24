from __future__ import annotations

from types import SimpleNamespace

import pytest

import core.governed_router as governed_router_module
from config import reset_config
from core.analytical_objective import AORelationship
from core.ao_manager import AOManager
from core.constraint_violation_writer import (
    ConstraintViolationWriter,
    ViolationRecord,
    normalize_cross_constraint_violation,
)
from core.context_store import SessionContextStore
from core.memory import FactMemory
from core.router import RouterResponse, UnifiedRouter
from core.task_state import TaskStage
from services.cross_constraints import CrossConstraintViolation
from services.standardization_engine import BatchStandardizationError, StandardizationEngine


def _violation(
    *,
    constraint_name: str = "vehicle_road_compatibility",
    engine_type: str = "blocked",
) -> CrossConstraintViolation:
    return CrossConstraintViolation(
        constraint_name=constraint_name,
        description="test constraint",
        param_a_name="vehicle_type",
        param_a_value="Motorcycle",
        param_b_name="road_type",
        param_b_value="高速公路",
        violation_type=engine_type,
        reason="摩托车不允许上高速公路",
        suggestions=["改用城市道路"],
    )


def _fact_memory_with_ao(session_id: str = "writer-test") -> tuple[FactMemory, AOManager]:
    memory = FactMemory(session_id=session_id)
    manager = AOManager(memory)
    manager.create_ao(
        "test objective",
        AORelationship.INDEPENDENT,
        current_turn=1,
    )
    return memory, manager


def test_violation_record_round_trips_dict():
    record = ViolationRecord(
        violation_type="vehicle_road_compatibility",
        severity="reject",
        involved_params={"vehicle_type": "Motorcycle", "road_type": "高速公路"},
        suggested_resolution="改用城市道路",
        timestamp="2026-04-24T10:00:00",
        source_turn=3,
    )

    restored = ViolationRecord.from_dict(record.to_dict())

    assert restored == record


@pytest.mark.parametrize(
    ("severity", "engine_type"),
    [
        ("reject", "blocked"),
        ("negotiate", "inconsistent"),
        ("warn", "warning"),
    ],
)
def test_normalize_cross_constraint_violation_maps_severity_and_rule_id(
    severity: str,
    engine_type: str,
):
    violation = _violation(
        constraint_name=f"{engine_type}_rule",
        engine_type=engine_type,
    )

    record = normalize_cross_constraint_violation(
        violation,
        severity=severity,
        source_turn=4,
        timestamp="2026-04-24T10:00:00",
    )

    assert record.violation_type == f"{engine_type}_rule"
    assert record.severity == severity
    assert record.involved_params == {
        "vehicle_type": "Motorcycle",
        "road_type": "高速公路",
    }
    assert record.suggested_resolution == "改用城市道路"
    assert record.source_turn == 4


def test_writer_dual_writes_current_ao_and_context_store():
    _memory, manager = _fact_memory_with_ao()
    context_store = SessionContextStore()
    writer = ConstraintViolationWriter(manager, context_store)

    writer.record(
        ViolationRecord(
            violation_type="vehicle_road_compatibility",
            severity="reject",
            involved_params={"vehicle_type": "Motorcycle"},
            suggested_resolution="改用城市道路",
            timestamp="2026-04-24T10:00:00",
            source_turn=1,
        )
    )

    current_ao = manager.get_current_ao()
    assert current_ao is not None
    assert current_ao.constraint_violations == context_store.get_latest_constraint_violations()
    assert current_ao.constraint_violations[0]["severity"] == "reject"


def test_get_latest_returns_current_ao_violations_only():
    _memory, manager = _fact_memory_with_ao()
    writer = ConstraintViolationWriter(manager, SessionContextStore())
    writer.record(
        ViolationRecord(
            violation_type="first_rule",
            severity="warn",
            involved_params={"season": "冬季"},
            suggested_resolution="",
            timestamp="2026-04-24T10:00:00",
            source_turn=1,
        )
    )

    manager.create_ao(
        "second objective",
        AORelationship.INDEPENDENT,
        current_turn=2,
    )

    assert writer.get_latest() == []

    writer.record(
        ViolationRecord(
            violation_type="second_rule",
            severity="warn",
            involved_params={"pollutant": "CO2"},
            suggested_resolution="选择 NOx",
            timestamp="2026-04-24T10:01:00",
            source_turn=2,
        )
    )

    latest = writer.get_latest()
    assert len(latest) == 1
    assert latest[0].violation_type == "second_rule"


class _FakeInnerRouter:
    def __init__(self, session_id: str, memory_storage_dir=None):
        self.session_id = session_id
        self.memory_storage_dir = memory_storage_dir
        self.memory = SimpleNamespace(
            fact_memory=FactMemory(session_id=session_id),
            turn_counter=0,
        )
        self.context_store = SessionContextStore()
        self.restore_payloads = []
        self.response = RouterResponse(text="ok")

    def _ensure_context_store(self):
        return self.context_store

    async def chat(self, user_message: str, file_path=None, trace=None):
        self.memory.turn_counter = 1
        if isinstance(trace, dict) and isinstance(self.response.trace, dict):
            trace.update(self.response.trace)
        return self.response

    def to_persisted_state(self):
        return {"version": 2, "live_state": {"marker": self.session_id}}

    def restore_persisted_state(self, payload):
        self.restore_payloads.append(payload)
        self.memory = SimpleNamespace(
            fact_memory=FactMemory(session_id=self.session_id),
            turn_counter=0,
        )
        self.context_store = SessionContextStore()


class _NoopContract:
    name = "noop"

    def __init__(self, *args, **kwargs):
        pass

    async def before_turn(self, context):
        return SimpleNamespace(
            proceed=True,
            response=None,
            user_message_override=None,
            metadata={},
        )

    async def after_turn(self, context, result):
        return None


class _NoopDependencyContract(_NoopContract):
    name = "dependency"


@pytest.fixture
def patched_governed_router(monkeypatch):
    monkeypatch.setenv("ENABLE_CONTRACT_SPLIT", "false")
    reset_config()
    monkeypatch.setattr(governed_router_module, "UnifiedRouter", _FakeInnerRouter)
    monkeypatch.setattr(governed_router_module, "OASCContract", _NoopContract)
    monkeypatch.setattr(governed_router_module, "ClarificationContract", _NoopContract)
    monkeypatch.setattr(governed_router_module, "DependencyContract", _NoopDependencyContract)
    yield governed_router_module
    reset_config()


def _trace_with_cross_constraint_violation() -> dict:
    violation = _violation().to_dict()
    return {
        "steps": [
            {
                "step_type": "cross_constraint_violation",
                "timestamp": "2026-04-24T10:00:00",
                "input_summary": {
                    "standardized_params": {
                        "vehicle_type": "Motorcycle",
                        "road_type": "高速公路",
                    },
                    "cross_constraint_violations": [violation],
                },
            }
        ]
    }


@pytest.mark.anyio
async def test_governed_router_records_trace_constraint_violations(patched_governed_router):
    router = patched_governed_router.GovernedRouter("governed-writer")
    router.ao_manager.create_ao(
        "test governed writer",
        AORelationship.INDEPENDENT,
        current_turn=1,
    )
    router.inner_router.response = RouterResponse(
        text="blocked",
        trace=_trace_with_cross_constraint_violation(),
    )

    await router.chat("test")

    current_ao = router.ao_manager.get_current_ao()
    assert current_ao is not None
    assert len(current_ao.constraint_violations) == 1
    assert current_ao.constraint_violations[0]["severity"] == "reject"
    assert current_ao.constraint_violations[0]["violation_type"] == "vehicle_road_compatibility"
    assert (
        router.inner_router.context_store.get_latest_constraint_violations()
        == current_ao.constraint_violations
    )


def test_unified_router_preflight_does_not_write_ao_or_context_store():
    memory, manager = _fact_memory_with_ao("pure-router")
    context_store = SessionContextStore()
    router = object.__new__(UnifiedRouter)
    router.context_store = context_store
    router.memory = SimpleNamespace(fact_memory=memory)
    router._extract_message_execution_hints = lambda state: {}
    router._transition_state = lambda state, stage, reason, trace_obj=None: setattr(state, "stage", stage)
    router._get_message_standardizer = lambda: SimpleNamespace(
        standardize_vehicle_detailed=lambda raw: SimpleNamespace(success=True, normalized="Motorcycle"),
        standardize_road_type=lambda raw: SimpleNamespace(success=True, normalized="高速公路"),
    )
    state = SimpleNamespace(
        execution=SimpleNamespace(blocked_info=None, last_error=None),
        stage=TaskStage.EXECUTING,
    )

    blocked = router._evaluate_cross_constraint_preflight(
        state,
        "query_emission_factors",
        {"vehicle_type": "Motorcycle", "road_type": "高速公路"},
        trace_obj=None,
    )

    current_ao = manager.get_current_ao()
    assert blocked is True
    assert state.execution.blocked_info is not None
    assert current_ao is not None
    assert current_ao.constraint_violations == []
    assert context_store.get_latest_constraint_violations() == []


def test_restore_persisted_state_rebinds_writer(patched_governed_router):
    router = patched_governed_router.GovernedRouter("restore-writer")
    original_context_store = router.constraint_violation_writer.context_store

    router.restore_persisted_state({"version": 2, "live_state": {}})

    assert router.constraint_violation_writer.ao_manager is router.ao_manager
    assert router.constraint_violation_writer.context_store is router.inner_router.context_store
    assert router.constraint_violation_writer.context_store is not original_context_store

    router.ao_manager.create_ao(
        "restored writer",
        AORelationship.INDEPENDENT,
        current_turn=1,
    )
    router._record_constraint_violations_from_trace(
        RouterResponse(text="blocked", trace=_trace_with_cross_constraint_violation()),
        None,
        source_turn=1,
    )

    assert len(router.constraint_violation_writer.get_latest()) == 1
    assert router.inner_router.context_store.get_latest_constraint_violations()


def test_constraint_control_flow_remains_unchanged():
    engine = StandardizationEngine({"llm_enabled": False, "enable_cross_constraint_validation": True})

    with pytest.raises(BatchStandardizationError) as exc_info:
        engine.standardize_batch(
            {
                "vehicle_type": "Motorcycle",
                "road_type": "高速公路",
            },
            tool_name="query_emission_factors",
        )
    assert exc_info.value.negotiation_eligible is True
    assert exc_info.value.trigger_reason == "cross_constraint_violation:vehicle_road_compatibility"

    standardized, records = engine.standardize_batch(
        {
            "season": "冬季",
            "meteorology": "urban_summer_day",
        },
        tool_name="calculate_dispersion",
    )
    assert standardized["season"] == "冬季"
    assert any(record.get("record_type") == "cross_constraint_warning" for record in records)
