import json

from core.analytical_objective import AOStatus
from core.memory import FactMemory, MemoryManager


def test_legacy_session_file_loads_into_ao_history(tmp_path):
    payload = {
        "session_id": "legacy-session",
        "turn_counter": 2,
        "fact_memory": {
            "tool_call_log": [
                {
                    "turn": 1,
                    "tool": "query_emission_factors",
                    "args_compact": {"pollutant": "CO2"},
                    "success": True,
                    "result_ref": "emission_factors:baseline",
                    "summary": "legacy",
                }
            ]
        },
        "working_memory": [],
    }
    (tmp_path / "legacy-session.json").write_text(json.dumps(payload), encoding="utf-8")

    memory = MemoryManager("legacy-session", storage_dir=tmp_path)

    assert len(memory.fact_memory.ao_history) == 1
    assert memory.fact_memory.ao_history[0].ao_id == "AO#legacy"
    assert memory.fact_memory.ao_history[0].status == AOStatus.COMPLETED


def test_ao_history_round_trip_persistence(tmp_path):
    memory = MemoryManager("ao-round-trip", storage_dir=tmp_path)
    memory.fact_memory.ao_history = []
    memory.fact_memory.current_ao_id = "AO#1"
    memory.fact_memory._ao_counter = 1
    memory.fact_memory.files_in_session = []
    memory.fact_memory.session_confirmed_parameters = {"season": "冬季"}
    memory.fact_memory.append_tool_call_log(
        1,
        "query_emission_factors",
        {"pollutant": "CO2"},
        {"success": True, "summary": "ok", "data": {"scenario_label": "baseline"}},
    )
    memory._migrate_legacy_fact_memory_if_needed()
    memory._save()

    restored = MemoryManager("ao-round-trip", storage_dir=tmp_path)

    assert restored.fact_memory.session_confirmed_parameters["season"] == "冬季"
    assert restored.fact_memory.ao_history[0].tool_call_log[0].tool == "query_emission_factors"


def test_files_in_session_append_and_dedup():
    memory = FactMemory(session_id="s1")
    memory.register_file_reference(path="/tmp/a.csv", task_type="macro_emission", uploaded_turn=1)
    memory.register_file_reference(path="/tmp/b.csv", task_type="trajectory", uploaded_turn=2)
    memory.register_file_reference(path="/tmp/a.csv", task_type="macro_emission", uploaded_turn=3)

    assert len(memory.files_in_session) == 2
    assert memory.files_in_session[0].filename == "a.csv"
    assert memory.files_in_session[1].filename == "b.csv"


def test_session_confirmed_parameters_persist_across_aos():
    memory = FactMemory(session_id="s1")
    memory.update_session_confirmed_parameters({"vehicle_type": "Passenger Car"})
    memory.update_session_confirmed_parameters({"season": "冬季"})

    assert memory.session_confirmed_parameters == {
        "vehicle_type": "Passenger Car",
        "season": "冬季",
    }
