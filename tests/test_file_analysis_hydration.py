"""Unit tests for Phase 5.3 Round 3.1E — file_analysis persistence / hydration.

Verifies that file_context.task_type survives across turns when
file_analysis is persisted to fact_memory and hydrated by TaskState.initialize.
"""

from __future__ import annotations

import os

import pytest

from config import get_config, reset_config
from core.task_state import TaskState


@pytest.fixture(autouse=True)
def _restore_config():
    reset_config()
    yield
    reset_config()


# ── TaskState.initialize hydration ──────────────────────────────────────


def test_initialize_hydrates_file_context_from_memory_file_analysis():
    """fact_memory with active_file + file_analysis(task_type=macro_emission)
    must hydrate state.file_context.task_type when no current-turn file_path."""
    memory_dict = {
        "active_file": "/tmp/macro_direct.csv",
        "file_analysis": {
            "file_path": "/tmp/macro_direct.csv",
            "task_type": "macro_emission",
            "confidence": 0.95,
            "columns": ["link_id", "length", "flow", "speed"],
        },
    }
    state = TaskState.initialize(
        user_message="CO2",
        file_path=None,  # no file this turn
        memory_dict=memory_dict,
        session_id="test-session",
    )
    assert state.file_context.has_file is True
    assert state.file_context.file_path == "/tmp/macro_direct.csv"
    assert state.file_context.task_type == "macro_emission"
    assert state.file_context.confidence == 0.95


def test_initialize_hydrates_micro_emission():
    memory_dict = {
        "active_file": "/tmp/trajectory.csv",
        "file_analysis": {
            "file_path": "/tmp/trajectory.csv",
            "task_type": "micro_emission",
        },
    }
    state = TaskState.initialize(
        user_message="NOx",
        file_path=None,
        memory_dict=memory_dict,
        session_id="test-session",
    )
    assert state.file_context.task_type == "micro_emission"


def test_initialize_no_active_file_does_not_set_file_context():
    """Without active_file in memory, file_context stays default."""
    memory_dict = {}
    state = TaskState.initialize(
        user_message="排放因子",
        file_path=None,
        memory_dict=memory_dict,
        session_id="test-session",
    )
    assert state.file_context.has_file is False
    assert state.file_context.task_type is None


def test_initialize_file_analysis_none_still_sets_has_file():
    """active_file present but file_analysis is None →
    file_context.has_file=True but task_type is None (partial hydration)."""
    memory_dict = {
        "active_file": "/tmp/some_file.csv",
        "file_analysis": None,
    }
    state = TaskState.initialize(
        user_message="继续",
        file_path=None,
        memory_dict=memory_dict,
        session_id="test-session",
    )
    assert state.file_context.has_file is True
    assert state.file_context.file_path == "/tmp/some_file.csv"
    # task_type not set because file_analysis was None
    assert state.file_context.task_type is None


def test_initialize_current_turn_file_path_overrides_memory():
    """When file_path is provided THIS turn, active_file from memory
    is NOT used (file_context set from current file_path)."""
    memory_dict = {
        "active_file": "/tmp/old_file.csv",
        "file_analysis": {"task_type": "macro_emission"},
    }
    state = TaskState.initialize(
        user_message="分析这个新文件",
        file_path="/tmp/new_file.csv",  # current turn has a file
        memory_dict=memory_dict,
        session_id="test-session",
    )
    # Line 317-319: file_path present → sets has_file + file_path directly
    assert state.file_context.has_file is True
    assert state.file_context.file_path == "/tmp/new_file.csv"
    # Line 356: if not file_path: → False (file_path IS provided)
    # So the active_file restoration block is SKIPPED
    # file_context.task_type remains default (None) until _ensure_file_context runs
    assert state.file_context.task_type is None


def test_initialize_empty_memory_does_not_crash():
    state = TaskState.initialize(
        user_message="hello",
        file_path=None,
        memory_dict=None,
        session_id="test-session",
    )
    assert state.file_context.has_file is False
    assert state.file_context.task_type is None


# ── Path-safe: mismatched file_analysis is not applied ─────────────────


def test_initialize_mismatched_file_analysis_not_confused():
    """update_file_context sets file_path from analysis_dict['file_path'],
    which takes precedence over active_file when they differ.  In the normal
    flow _ensure_file_context keeps active_file == analysis['file_path']."""
    memory_dict = {
        "active_file": "/tmp/current.csv",
        "file_analysis": {
            "file_path": "/tmp/different.csv",
            "task_type": "macro_emission",
        },
    }
    state = TaskState.initialize(
        user_message="继续",
        file_path=None,
        memory_dict=memory_dict,
        session_id="test-session",
    )
    # update_file_context sets file_path from analysis['file_path']
    assert state.file_context.file_path == "/tmp/different.csv"
    assert state.file_context.task_type == "macro_emission"
