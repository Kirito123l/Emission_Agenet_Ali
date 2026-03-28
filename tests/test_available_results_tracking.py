"""Tests for available_results tracking and dependency checking."""
import json

import pytest

from core.task_state import TaskState, TaskStage, ExecutionContext
from core.tool_dependencies import get_missing_prerequisites, suggest_prerequisite_tool


class TestAvailableResultsTracking:
    def test_initial_available_results_empty(self):
        state = TaskState.initialize(
            user_message="test", file_path=None, memory_dict={}, session_id=None
        )
        assert len(state.execution.available_results) == 0

    def test_available_results_serializable(self):
        state = TaskState.initialize(
            user_message="test", file_path=None, memory_dict={}, session_id=None
        )
        state.execution.available_results.add("emission")
        d = state.to_dict()
        json.dumps(d)  # must not raise

    def test_available_results_update(self):
        ctx = ExecutionContext()
        ctx.available_results.update(["emission", "visualization"])
        assert "emission" in ctx.available_results
        assert "visualization" in ctx.available_results

    def test_available_results_sorted_in_dict(self):
        ctx = ExecutionContext()
        ctx.available_results.update(["visualization", "emission", "file_analysis"])
        d = ctx.to_dict()
        assert d["available_results"] == ["emission", "file_analysis", "visualization"]


class TestDependencyIntegration:
    def test_macro_emission_no_missing(self):
        missing = get_missing_prerequisites("calculate_macro_emission", set())
        assert missing == []

    def test_dispersion_missing_emission(self):
        missing = get_missing_prerequisites("calculate_dispersion", set())
        assert "emission" in missing

    def test_dispersion_satisfied_after_emission(self):
        available = {"emission"}
        missing = get_missing_prerequisites("calculate_dispersion", available)
        assert missing == []

    def test_suggest_macro_for_emission_result(self):
        tool = suggest_prerequisite_tool("emission_result")
        assert tool in ("calculate_macro_emission", "calculate_micro_emission")

    def test_render_spatial_map_no_prerequisites(self):
        missing = get_missing_prerequisites("render_spatial_map", set())
        assert missing == []
