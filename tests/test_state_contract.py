from types import SimpleNamespace
from unittest.mock import patch

from core.assembler import ContextAssembler
from core.context_store import SessionContextStore
from core.memory import FactMemory, MemoryManager
from core.task_state import ParamEntry, ParamStatus, TaskState
from services.config_loader import ConfigLoader


def _make_assembler(*, enabled: bool = True, ao_enabled: bool = False) -> ContextAssembler:
    ConfigLoader._prompts_cache = None
    with patch("config.get_config") as mock_cfg, patch("core.assembler.get_config") as mock_cfg2:
        for item in (mock_cfg, mock_cfg2):
            item.return_value.enable_skill_injection = False
            item.return_value.enable_file_context_injection = True
            item.return_value.enable_session_state_block = enabled
            item.return_value.enable_ao_block_injection = ao_enabled
            item.return_value.enable_ao_persistent_facts = ao_enabled
            item.return_value.ao_block_token_budget = 1200
        assembler = ContextAssembler()
    assembler.runtime_config.enable_skill_injection = False
    assembler.runtime_config.enable_file_context_injection = True
    assembler.runtime_config.enable_session_state_block = enabled
    assembler.runtime_config.enable_ao_block_injection = ao_enabled
    assembler.runtime_config.enable_ao_persistent_facts = ao_enabled
    assembler.runtime_config.ao_block_token_budget = 1200
    return assembler


def test_fact_memory_state_contract_fields_write_and_persist(tmp_path):
    memory = MemoryManager("state-contract", storage_dir=tmp_path)
    memory.update(
        "calculate emissions",
        "done",
        tool_calls=[
            {
                "name": "calculate_macro_emission",
                "arguments": {
                    "file_path": "/tmp/links.csv",
                    "pollutants": ["CO2"],
                    "unused_big": list(range(20)),
                },
                "result": {
                    "success": True,
                    "summary": "macro ok",
                    "data": {
                        "scenario_label": "default",
                        "results": [{"link_id": "L1", "geometry": "LINESTRING(0 0, 1 1)"}],
                    },
                },
            }
        ],
    )
    memory.fact_memory.snapshot_locked_parameters(
        {
            "season": ParamEntry(
                raw="冬天",
                normalized="冬季",
                status=ParamStatus.OK,
                locked=True,
            )
        }
    )
    memory.fact_memory.append_constraint_violation(
        2,
        "vehicle_road_compatibility",
        {"vehicle_type": "Motorcycle", "road_type": "高速公路"},
        True,
    )
    memory._save()

    restored = MemoryManager("state-contract", storage_dir=tmp_path)
    facts = restored.get_fact_memory()

    assert facts["tool_call_log"][0]["tool"] == "calculate_macro_emission"
    assert facts["tool_call_log"][0]["result_ref"] == "emission:default"
    assert facts["active_artifact_refs"]["emission"] == "emission:default"
    assert facts["active_artifact_refs"]["geometry"]["geometry_present"] is True
    assert facts["locked_parameters_display"] == {"season": "冬季"}
    assert facts["constraint_violations_seen"][0]["blocked"] is True


def test_session_context_store_from_dict_restores_persisted_data():
    store = SessionContextStore()
    stored = store.store_result(
        "calculate_macro_emission",
        {
            "success": True,
            "summary": "ok",
            "data": {"scenario_label": "default", "results": [{"link_id": "L1"}]},
        },
    )
    assert stored is not None

    restored = SessionContextStore.from_dict(store.to_persisted_dict())
    restored_result = restored.get_by_type("emission", label="default")

    assert restored_result is not None
    assert restored_result.data["data"]["results"][0]["link_id"] == "L1"


def test_fact_memory_sliding_windows():
    memory = FactMemory()
    for index in range(25):
        memory.append_tool_call_log(
            index,
            "query_emission_factors",
            {"pollutants": ["NOx"]},
            {"success": True, "summary": f"ok {index}", "data": {}},
        )
    for index in range(12):
        memory.append_constraint_violation(index, "c", {"value": index}, blocked=bool(index % 2))

    assert len(memory.tool_call_log) == 20
    assert memory.tool_call_log[0]["turn"] == 5
    assert len(memory.constraint_violations_seen) == 10
    assert memory.constraint_violations_seen[0]["turn"] == 2


def test_session_state_block_empty_session():
    assembler = _make_assembler()
    block = assembler._build_session_state_block({}, TaskState())

    assert "[Session State]" in block
    assert "Tools called this session:\nnone" in block
    assert "Active artifacts: none" in block
    assert "New task starts" in block


def test_session_state_block_single_tool_call():
    assembler = _make_assembler()
    memory = FactMemory()
    memory.append_tool_call_log(
        1,
        "calculate_macro_emission",
        {"file_path": "/tmp/links.csv", "pollutants": ["CO2"]},
        {"success": True, "summary": "Calculated emissions", "data": {"scenario_label": "default"}},
    )

    block = assembler._build_session_state_block(memory, TaskState())

    assert "calculate_macro_emission(file=links.csv, pollutants=[CO2])" in block
    assert "produced emission_default" in block
    assert "Active artifacts: emission(default)" in block


def test_session_state_block_multi_tool_chain_and_locked_params():
    assembler = _make_assembler()
    memory = FactMemory()
    memory.append_tool_call_log(
        1,
        "calculate_macro_emission",
        {"file_path": "/tmp/links.csv", "pollutants": ["NOx"]},
        {"success": True, "summary": "emission ok", "data": {"scenario_label": "baseline"}},
    )
    memory.append_tool_call_log(
        2,
        "calculate_dispersion",
        {"emission_ref": "emission:baseline", "meteorology": "urban_summer_day"},
        {"success": True, "summary": "dispersion ok", "data": {"scenario_label": "NOx"}},
    )
    state = TaskState()
    state.parameters["vehicle_type"] = ParamEntry(
        raw="家用车",
        normalized="Passenger Car",
        status=ParamStatus.OK,
        locked=True,
    )

    block = assembler._build_session_state_block(memory, state)

    assert "calculate_dispersion" in block
    assert "emission(baseline), dispersion(NOx)" in block
    assert "vehicle_type=Passenger Car" in block


def test_session_state_block_active_input_completion_action():
    assembler = _make_assembler()
    state = TaskState()
    state.active_input_completion = SimpleNamespace(request_id="input-1")

    block = assembler._build_session_state_block({}, state)

    assert "input-completion request" in block


def test_session_state_block_constraint_violation():
    assembler = _make_assembler()
    memory = FactMemory()
    memory.append_constraint_violation(
        2,
        "vehicle_road_compatibility",
        {"vehicle_type": "Motorcycle", "road_type": "高速公路"},
        True,
    )

    block = assembler._build_session_state_block(memory, TaskState())

    assert "Motorcycle+高速公路 (blocked on turn 2)" in block


def test_session_state_token_budget_keeps_recent_tool_calls():
    assembler = _make_assembler()
    memory = FactMemory()
    for index in range(20):
        memory.append_tool_call_log(
            index,
            "query_emission_factors",
            {"vehicle_type": f"Vehicle {index}", "pollutants": ["NOx"], "extra": "x" * 200},
            {"success": True, "summary": "y" * 300, "data": {"scenario_label": f"s{index}"}},
        )

    prompt, telemetry = assembler._append_session_state_block("base", memory.__dict__, TaskState())

    assert telemetry["truncated"] is True
    assert telemetry["estimated_tokens"] <= assembler.SESSION_STATE_TOKEN_BUDGET
    assert "Vehicle 19" in prompt


def test_session_state_feature_flag_false_keeps_system_prompt_unchanged():
    assembler = _make_assembler(enabled=False)
    ctx = assembler.assemble("hello", [], {}, state=TaskState())

    assert "[Session State]" not in ctx.system_prompt
    assert ctx.telemetry["session_state_block"]["enabled"] is False


def test_oasc_block_empty_session():
    assembler = _make_assembler(enabled=False, ao_enabled=True)

    block = assembler._build_session_state_block({}, TaskState())

    assert "Persistent facts (across all analytical objectives):" in block
    assert "Files available: none" in block
    assert "Completed analytical objectives:\nnone" in block


def test_oasc_block_current_ao_only_shows_current_tool_log():
    assembler = _make_assembler(enabled=False, ao_enabled=True)
    memory = FactMemory(session_id="ao-session")
    memory.ao_history = [
        {
            "ao_id": "AO#1",
            "session_id": "ao-session",
            "objective_text": "查 CO2 因子",
            "status": "completed",
            "start_turn": 1,
            "tool_call_log": [
                {
                    "turn": 1,
                    "tool": "query_emission_factors",
                    "args_compact": {"pollutant": "CO2"},
                    "success": True,
                    "result_ref": "emission_factors:baseline",
                    "summary": "ok",
                }
            ],
            "artifacts_produced": {"emission_factors": "emission_factors:baseline"},
        },
        {
            "ao_id": "AO#2",
            "session_id": "ao-session",
            "objective_text": "算 NOx 排放",
            "status": "active",
            "start_turn": 2,
            "relationship": "independent",
            "tool_call_log": [
                {
                    "turn": 2,
                    "tool": "calculate_macro_emission",
                    "args_compact": {"pollutants": ["NOx"]},
                    "success": True,
                    "result_ref": "emission:baseline",
                    "summary": "computed",
                }
            ],
            "artifacts_produced": {"emission": "emission:baseline"},
        },
    ]
    memory.current_ao_id = "AO#2"

    block = assembler._build_session_state_block(memory.__dict__, TaskState())

    assert '[AO#1] "查 CO2 因子" -> produced emission_factors(baseline)' in block
    assert "Tools executed this objective: calculate_macro_emission(pollutants=[NOx])" in block
    assert "query_emission_factors" not in block.split("Current analytical objective:")[1]


def test_oasc_block_persistent_facts_can_be_disabled():
    assembler = _make_assembler(enabled=False, ao_enabled=True)
    assembler.runtime_config.enable_ao_persistent_facts = False
    block = assembler._build_session_state_block(
        {
            "files_in_session": [{"filename": "roads.csv", "path": "/tmp/roads.csv"}],
            "session_confirmed_parameters": {"season": "冬季"},
            "cumulative_constraint_violations": [
                {"constraint": "c1", "values": {"vehicle_type": "Motorcycle"}, "blocked": True}
            ],
        },
        TaskState(),
    )

    assert "Files available: none" in block
    assert "Session-confirmed parameters: none" in block
