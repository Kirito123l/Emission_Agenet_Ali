"""Regression tests for session-scoped router persistence."""

from __future__ import annotations

from api.session import SessionManager
from tests.test_context_store import make_emission_result


def test_session_reload_restores_context_store_and_file_memory(tmp_path):
    storage_dir = tmp_path / "sessions"
    manager = SessionManager(storage_dir=str(storage_dir))
    session_id = manager.create_session()
    session = manager.get_session(session_id)
    assert session is not None

    emission_result = make_emission_result()
    session.router.context_store.store_result("calculate_macro_emission", emission_result)
    session.router.memory.fact_memory.last_spatial_data = emission_result["data"]
    session.router.memory.update(
        user_message="请记住这个文件",
        assistant_response="好的",
        file_path="/tmp/input.xlsx",
        file_analysis={"detected_type": "trajectory", "file_path": "/tmp/input.xlsx"},
    )
    manager.save_session()

    reloaded_manager = SessionManager(storage_dir=str(storage_dir))
    reloaded_session = reloaded_manager.get_session(session_id)
    assert reloaded_session is not None

    stored = reloaded_session.router.context_store.get_by_type("emission")
    assert stored is not None
    assert stored.data["data"]["results"][0]["link_id"] == "L1"

    prepared = reloaded_session.router._prepare_tool_arguments(
        "render_spatial_map",
        {"layer_type": "emission"},
    )
    assert prepared["_last_result"]["data"]["results"][0]["link_id"] == "L1"

    fact_memory = reloaded_session.router.memory.get_fact_memory()
    assert fact_memory["active_file"] == "/tmp/input.xlsx"
    assert fact_memory["file_analysis"]["detected_type"] == "trajectory"
    assert fact_memory["last_spatial_data"]["results"][0]["link_id"] == "L1"


def test_session_reload_restores_live_router_state(tmp_path):
    storage_dir = tmp_path / "sessions"
    manager = SessionManager(storage_dir=str(storage_dir))
    session_id = manager.create_session()
    session = manager.get_session(session_id)
    assert session is not None

    session.router._ensure_live_parameter_negotiation_bundle()["active_request"] = {
        "parameter": "vehicle_type",
        "options": ["Passenger Car", "Transit Bus"],
    }
    session.router._ensure_live_input_completion_bundle()["overrides"] = {
        "pollutant": "NOx",
    }
    session.router._ensure_live_continuation_bundle()["residual_plan_summary"] = "continue dispersion"
    manager.save_session()

    reloaded_manager = SessionManager(storage_dir=str(storage_dir))
    reloaded_session = reloaded_manager.get_session(session_id)
    assert reloaded_session is not None

    negotiation = reloaded_session.router._ensure_live_parameter_negotiation_bundle()
    completion = reloaded_session.router._ensure_live_input_completion_bundle()
    continuation = reloaded_session.router._ensure_live_continuation_bundle()
    assert negotiation["active_request"]["parameter"] == "vehicle_type"
    assert completion["overrides"]["pollutant"] == "NOx"
    assert continuation["residual_plan_summary"] == "continue dispersion"
