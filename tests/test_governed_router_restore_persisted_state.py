from __future__ import annotations

from types import SimpleNamespace

import pytest

from config import reset_config
import core.governed_router as governed_router


class FakeUnifiedRouter:
    def __init__(self, session_id: str, memory_storage_dir=None):
        self.session_id = session_id
        self.memory_storage_dir = memory_storage_dir
        self.memory = SimpleNamespace(
            fact_memory=SimpleNamespace(source="initial", session_id=session_id),
            turn_counter=0,
        )
        self.restore_payloads = []

    def to_persisted_state(self):
        return {"version": 2, "live_state": {"marker": self.session_id}}

    def restore_persisted_state(self, payload):
        self.restore_payloads.append(payload)
        self.memory = SimpleNamespace(
            fact_memory=SimpleNamespace(source="restored", session_id=self.session_id),
            turn_counter=0,
        )


class FakeDependencyContract:
    name = "dependency"


def _contract_type(name: str):
    class FakeContract:
        def __init__(self, inner_router=None, ao_manager=None, runtime_config=None):
            self.inner_router = inner_router
            self.ao_manager = ao_manager
            self.runtime_config = runtime_config

    FakeContract.name = name
    return FakeContract


@pytest.fixture(autouse=True)
def _reset_runtime_config():
    reset_config()
    yield
    reset_config()


@pytest.fixture
def patched_router_module(monkeypatch):
    monkeypatch.setattr(governed_router, "UnifiedRouter", FakeUnifiedRouter)
    monkeypatch.setattr(governed_router, "OASCContract", _contract_type("oasc"))
    monkeypatch.setattr(
        governed_router,
        "ClarificationContract",
        _contract_type("clarification"),
    )
    monkeypatch.setattr(
        governed_router,
        "IntentResolutionContract",
        _contract_type("intent_resolution"),
    )
    monkeypatch.setattr(
        governed_router,
        "StanceResolutionContract",
        _contract_type("stance_resolution"),
    )
    monkeypatch.setattr(
        governed_router,
        "ExecutionReadinessContract",
        _contract_type("execution_readiness"),
    )
    monkeypatch.setattr(governed_router, "DependencyContract", FakeDependencyContract)
    return governed_router


def _set_split_config(
    monkeypatch,
    *,
    split: bool,
    intent: bool = True,
    stance: bool = True,
    readiness: bool = True,
) -> None:
    monkeypatch.setenv("ENABLE_CONTRACT_SPLIT", "true" if split else "false")
    monkeypatch.setenv("ENABLE_SPLIT_INTENT_CONTRACT", "true" if intent else "false")
    monkeypatch.setenv("ENABLE_SPLIT_STANCE_CONTRACT", "true" if stance else "false")
    monkeypatch.setenv("ENABLE_SPLIT_READINESS_CONTRACT", "true" if readiness else "false")
    reset_config()


def _contract_names(router) -> list[str]:
    return [contract.name for contract in router.contracts]


def test_restore_default_contracts_when_split_disabled(monkeypatch, patched_router_module):
    _set_split_config(monkeypatch, split=False)
    router = patched_router_module.GovernedRouter("restore-default")
    dependency_contract = router.dependency_contract

    router.restore_persisted_state({"version": 2, "live_state": {}})

    assert _contract_names(router) == ["oasc", "clarification", "dependency"]
    assert router.dependency_contract is dependency_contract


def test_restore_split_contracts_when_all_split_flags_enabled(monkeypatch, patched_router_module):
    _set_split_config(monkeypatch, split=True)
    router = patched_router_module.GovernedRouter("restore-split")

    router.restore_persisted_state({"version": 2, "live_state": {}})

    assert _contract_names(router) == [
        "oasc",
        "intent_resolution",
        "stance_resolution",
        "execution_readiness",
        "dependency",
    ]


def test_restore_split_contracts_when_only_intent_enabled(monkeypatch, patched_router_module):
    _set_split_config(monkeypatch, split=True, intent=True, stance=False, readiness=False)
    router = patched_router_module.GovernedRouter("restore-intent-only")

    router.restore_persisted_state({"version": 2, "live_state": {}})

    assert _contract_names(router) == ["oasc", "intent_resolution", "dependency"]


def test_restore_rebuilds_contracts_from_current_config(monkeypatch, patched_router_module):
    _set_split_config(monkeypatch, split=True)
    saved_router = patched_router_module.GovernedRouter("cross-config")
    payload = saved_router.to_persisted_state()
    assert _contract_names(saved_router) == [
        "oasc",
        "intent_resolution",
        "stance_resolution",
        "execution_readiness",
        "dependency",
    ]

    _set_split_config(monkeypatch, split=False)
    restored_router = patched_router_module.GovernedRouter("cross-config")
    restored_router.restore_persisted_state(payload)

    assert restored_router.contract_split_enabled is False
    assert _contract_names(restored_router) == ["oasc", "clarification", "dependency"]
    assert restored_router.ao_manager._memory.source == "restored"
