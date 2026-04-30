"""Unit tests for Phase 5.3 Round 3.3 — ERC parameter snapshot persistence.

Verifies that _persist_split_pending mirrors parameter_snapshot to top-level
AO metadata and updates parameters_used, matching legacy ClarificationContract
behaviour.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from core.contracts.execution_readiness_contract import ExecutionReadinessContract


# ── Minimal AO stub ────────────────────────────────────────────────────


def _ao_with_metadata(metadata=None):
    """Create an AO-like object with a metadata dict."""
    ao = SimpleNamespace()
    ao.metadata = dict(metadata) if metadata is not None else {}
    ao.parameters_used = {}
    return ao


# ── Snapshot builder helpers ───────────────────────────────────────────


def _slot(value, source="user", confidence=1.0, raw_text=None):
    return {"value": value, "source": source, "confidence": confidence, "raw_text": raw_text}


def _snapshot_with_vehicle_type():
    return {
        "vehicle_type": _slot("Refuse Truck"),
        "pollutants": _slot(None, "missing"),
        "model_year": _slot(None, "missing"),
        "season": _slot(None, "missing"),
        "road_type": _slot(None, "missing"),
    }


def _snapshot_with_vehicle_and_pollutant():
    return {
        "vehicle_type": _slot("Refuse Truck"),
        "pollutants": _slot(["PM10"]),
        "model_year": _slot("2020"),
        "season": _slot(None, "missing"),
        "road_type": _slot(None, "missing"),
    }


# ── Tests ──────────────────────────────────────────────────────────────


class TestPersistSplitPendingMirrors:
    """Verify _persist_split_pending mirrors snapshot to top-level AO metadata."""

    def test_mirrors_to_top_level_parameter_snapshot(self):
        ao = _ao_with_metadata()
        snapshot = _snapshot_with_vehicle_type()
        ExecutionReadinessContract._persist_split_pending(
            ao, "query_emission_factors", "pollutants", snapshot,
        )
        assert "parameter_snapshot" in ao.metadata
        top = ao.metadata["parameter_snapshot"]
        assert isinstance(top, dict)
        assert top["vehicle_type"]["value"] == "Refuse Truck"
        # Must be a deep copy, not the same object
        assert top is not snapshot

    def test_preserves_execution_readiness_nested_snapshot(self):
        ao = _ao_with_metadata()
        snapshot = _snapshot_with_vehicle_type()
        ExecutionReadinessContract._persist_split_pending(
            ao, "query_emission_factors", "pollutants", snapshot,
        )
        er = ao.metadata.get("execution_readiness")
        assert isinstance(er, dict)
        assert "parameter_snapshot" in er
        assert er["parameter_snapshot"]["vehicle_type"]["value"] == "Refuse Truck"

    def test_top_level_and_nested_are_independent_copies(self):
        ao = _ao_with_metadata()
        snapshot = _snapshot_with_vehicle_type()
        ExecutionReadinessContract._persist_split_pending(
            ao, "query_emission_factors", "pollutants", snapshot,
        )
        top = ao.metadata["parameter_snapshot"]
        nested = ao.metadata["execution_readiness"]["parameter_snapshot"]
        # Mutating top should not affect nested
        top["vehicle_type"]["value"] = "Sedan"
        assert nested["vehicle_type"]["value"] == "Refuse Truck"

    def test_updates_parameters_used_with_non_missing_values(self):
        ao = _ao_with_metadata()
        snapshot = _snapshot_with_vehicle_and_pollutant()
        ExecutionReadinessContract._persist_split_pending(
            ao, "query_emission_factors", None, snapshot, missing_slots=[],
        )
        assert ao.parameters_used["vehicle_type"] == "Refuse Truck"
        assert ao.parameters_used["pollutants"] == ["PM10"]
        assert ao.parameters_used["model_year"] == "2020"

    def test_missing_values_not_added_to_parameters_used(self):
        ao = _ao_with_metadata()
        snapshot = _snapshot_with_vehicle_type()
        ExecutionReadinessContract._persist_split_pending(
            ao, "query_emission_factors", "pollutants", snapshot,
        )
        assert "pollutants" not in ao.parameters_used
        assert "model_year" not in ao.parameters_used
        assert "vehicle_type" in ao.parameters_used

    def test_rejected_values_not_added_to_parameters_used(self):
        ao = _ao_with_metadata()
        snapshot = {
            "vehicle_type": _slot("Bus"),
            "pollutants": _slot(["PM10"], source="rejected"),
        }
        ExecutionReadinessContract._persist_split_pending(
            ao, "query_emission_factors", None, snapshot, missing_slots=[],
        )
        assert "vehicle_type" in ao.parameters_used
        assert "pollutants" not in ao.parameters_used  # rejected source

    def test_empty_list_value_not_added_to_parameters_used(self):
        ao = _ao_with_metadata()
        snapshot = {
            "vehicle_type": _slot("Bus"),
            "pollutants": _slot([], source="user"),
        }
        ExecutionReadinessContract._persist_split_pending(
            ao, "query_emission_factors", None, snapshot, missing_slots=[],
        )
        assert "vehicle_type" in ao.parameters_used
        assert "pollutants" not in ao.parameters_used  # empty list

    def test_none_ao_does_not_crash(self):
        ExecutionReadinessContract._persist_split_pending(
            None, "query_emission_factors", "pollutants", {},
        )

    def test_ao_without_metadata_does_not_crash(self):
        ao = SimpleNamespace()
        ao.metadata = None
        ao.parameters_used = {}
        ExecutionReadinessContract._persist_split_pending(
            ao, "query_emission_factors", "pollutants", {"a": _slot(1)},
        )

    def test_parameters_used_accumulates_across_calls(self):
        ao = _ao_with_metadata()
        snap1 = _snapshot_with_vehicle_type()
        ExecutionReadinessContract._persist_split_pending(
            ao, "query_emission_factors", "pollutants", snap1,
        )
        assert ao.parameters_used["vehicle_type"] == "Refuse Truck"

        snap2 = _snapshot_with_vehicle_and_pollutant()
        ExecutionReadinessContract._persist_split_pending(
            ao, "query_emission_factors", None, snap2, missing_slots=[],
        )
        assert ao.parameters_used["vehicle_type"] == "Refuse Truck"  # preserved
        assert ao.parameters_used["pollutants"] == ["PM10"]
        assert ao.parameters_used["model_year"] == "2020"


class TestInitialSnapshotFallback:
    """Verify _initial_snapshot can find the mirrored top-level snapshot."""

    def test_fallback_reads_top_level_parameter_snapshot(self):
        from core.contracts.clarification_contract import ClarificationContract

        contract = ClarificationContract.__new__(ClarificationContract)
        contract.ao_manager = None
        contract.inner_router = None
        contract.runtime_config = None

        ao = _ao_with_metadata({
            "parameter_snapshot": {
                "vehicle_type": _slot("Refuse Truck"),
                "pollutants": _slot(None, "missing"),
                "model_year": _slot(None, "missing"),
                "season": _slot(None, "missing"),
                "road_type": _slot(None, "missing"),
            }
        })
        ao.parameters_used = {}

        # Without pending_state (empty), should fall back to top-level metadata
        snap = contract._initial_snapshot(
            tool_name="query_emission_factors",
            current_ao=ao,
            pending_state={},
            classification=None,
        )
        assert snap["vehicle_type"]["value"] == "Refuse Truck"

    def test_pending_state_takes_priority_over_top_level(self):
        from core.contracts.clarification_contract import ClarificationContract

        contract = ClarificationContract.__new__(ClarificationContract)
        contract.ao_manager = None
        contract.inner_router = None
        contract.runtime_config = None

        ao = _ao_with_metadata({
            "parameter_snapshot": {
                "vehicle_type": _slot("Old Car"),
            }
        })
        ao.parameters_used = {}

        pending_state = {
            "parameter_snapshot": {
                "vehicle_type": _slot("Refuse Truck"),
            }
        }

        snap = contract._initial_snapshot(
            tool_name="query_emission_factors",
            current_ao=ao,
            pending_state=pending_state,
            classification=None,
        )
        # pending_state wins over top-level
        assert snap["vehicle_type"]["value"] == "Refuse Truck"

    def test_task110_style_accumulation(self):
        """Simulate Task 110 flow: Turn 2 snapshot has vehicle_type,
        Turn 3 current extraction adds pollutant, merged snapshot has both."""
        from core.contracts.clarification_contract import ClarificationContract

        contract = ClarificationContract.__new__(ClarificationContract)
        contract.ao_manager = None
        contract.inner_router = None
        contract.runtime_config = None

        # Turn 2 persisted: vehicle_type filled, pollutants missing
        turn2_snapshot = _snapshot_with_vehicle_type()
        ao = _ao_with_metadata()
        ao.parameters_used = {}
        ExecutionReadinessContract._persist_split_pending(
            ao, "query_emission_factors", "pollutants", turn2_snapshot,
        )

        # Turn 3: _get_split_pending_state reads execution_readiness
        pending_state = ExecutionReadinessContract._get_split_pending_state(ao)
        assert isinstance(pending_state, dict)
        assert "parameter_snapshot" in pending_state

        # _initial_snapshot restores Turn 2's snapshot
        restored = contract._initial_snapshot(
            tool_name="query_emission_factors",
            current_ao=ao,
            pending_state=pending_state,
            classification=None,
        )
        assert restored["vehicle_type"]["value"] == "Refuse Truck"

        # Simulate Stage 1 filling pollutants from Turn 3 user message
        restored["pollutants"] = _slot(["PM10"])

        # Now the merged snapshot has both vehicle_type AND pollutants
        assert restored["vehicle_type"]["value"] == "Refuse Truck"
        assert restored["pollutants"]["value"] == ["PM10"]
