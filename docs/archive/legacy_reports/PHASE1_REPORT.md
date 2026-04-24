# PHASE1_REPORT

## 1. Implementation

- `FactMemory` now persists `tool_call_log`, `active_artifact_refs`, `locked_parameters_display`, and `constraint_violations_seen`.
- `MemoryManager.update()` appends compact tool execution records from `executed_tool_calls`; successful tool calls infer active artifact refs such as `emission:baseline`.
- `ContextAssembler` appends `[Session State]` to the system prompt when `ENABLE_SESSION_STATE_BLOCK=true`; `ENABLE_SESSION_STATE_BLOCK=false` skips the block.
- `SessionContextStore.from_dict()` now restores full persisted payloads when given `to_persisted_dict()` data and preserves `data` if present in compact legacy payloads.

## 2. Session State Examples

### empty session
```text
[Session State]
Tools called this session:
none

Active artifacts: none [geometry: unknown]
Confirmed parameters (locked): none
Constraint violations seen: none
Current turn action required:
New task starts; handle the user's current message.
```

### single tool
```text
[Session State]
Tools called this session:
calculate_macro_emission(file=macro.csv, pollutants=[CO2]) -> success, produced emission_default, macro complete

Active artifacts: emission(default) [geometry: present]
Confirmed parameters (locked): none
Constraint violations seen: none
Current turn action required:
New task starts; handle the user's current message.
```

### multi-tool locked parameter
```text
[Session State]
Tools called this session:
calculate_macro_emission(file=macro.csv, pollutants=[NOx]) -> success, produced emission_baseline, emission ok
calculate_dispersion(meteorology=urban_summer_day, emission_ref=emission:baseline) -> success, produced dispersion_NOx, dispersion ok

Active artifacts: emission(baseline), dispersion(NOx) [geometry: unknown]
Confirmed parameters (locked): vehicle_type=Passenger Car
Constraint violations seen: none
Current turn action required:
New task starts; handle the user's current message.
```

### active input completion
```text
[Session State]
Tools called this session:
none

Active artifacts: none [geometry: unknown]
Confirmed parameters (locked): none
Constraint violations seen: none
Current turn action required:
The user is replying to an input-completion request. Use their answer to fill the missing parameter or file input.
```

### constraint violation
```text
[Session State]
Tools called this session:
none

Active artifacts: none [geometry: unknown]
Confirmed parameters (locked): none
Constraint violations seen: Motorcycle+高速公路 (blocked on turn 2)
Current turn action required:
New task starts; handle the user's current message.
```

## 3. Token Estimate

| count | min | median | max | avg |
|---:|---:|---:|---:|---:|
| 1934 | 121 | 128.0 | 772 | 171.9 |

## 4. 180 Benchmark Results

| run | tasks | completion_rate | tool_accuracy | parameter_legal_rate | result_data_rate |
|---|---:|---:|---:|---:|---:|
| Phase0 Full v3 | 180 | 0.6611 | 0.7778 | 0.7167 | 0.7778 |
| State off v4 | 180 | 0.6778 | 0.8389 | 0.7500 | 0.8444 |
| State on v4 | 180 | 0.6556 | 0.7944 | 0.6778 | 0.7667 |

| category | off completion | on completion | off tool_accuracy | on tool_accuracy |
|---|---:|---:|---:|---:|
| ambiguous_colloquial | 0.6000 | 0.6000 | 0.9000 | 0.8000 |
| code_switch_typo | 0.8000 | 0.8000 | 0.9500 | 0.8500 |
| constraint_violation | 1.0000 | 0.9412 | 1.0000 | 0.9412 |
| incomplete | 0.3333 | 0.5556 | 1.0000 | 1.0000 |
| multi_step | 0.7000 | 0.6500 | 0.7500 | 0.7000 |
| multi_turn_clarification | 0.2000 | 0.2500 | 0.2000 | 0.2500 |
| parameter_ambiguous | 0.5417 | 0.3333 | 0.8333 | 0.7500 |
| simple | 0.9524 | 0.9048 | 0.9524 | 0.9048 |
| user_revision | 1.0000 | 0.9500 | 1.0000 | 1.0000 |

## 5. Failure Buckets

| bucket | off count | on count | delta |
|---|---:|---:|---:|
| D_TOOL_ERROR | 1 | 1 | +0 |
| NO_TOOL_OR_TEXT_PATH | 13 | 21 | +8 |
| OTHER | 1 | 1 | +0 |
| PARAMS_LEGAL_FAIL | 10 | 14 | +4 |
| TOOL_EXECUTED_MISMATCH | 15 | 8 | -7 |
| USER_RESPONSE_MISMATCH | 2 | 1 | -1 |
| WRONG_TOOL_CHAIN | 16 | 16 | +0 |

- NO_TOOL_OR_TEXT_PATH: 13 -> 21.
- WRONG_TOOL_CHAIN: 16 -> 16.

## 6. State On Still-Failing Cases
- NO_TOOL_OR_TEXT_PATH (21): e2e_simple_001, e2e_multistep_004, e2e_simple_011, e2e_multistep_008, e2e_multistep_009, e2e_multistep_010, e2e_multistep_011, e2e_ambiguous_020, e2e_ambiguous_026, e2e_ambiguous_028, e2e_ambiguous_032, e2e_constraint_035, e2e_ambiguous_038, e2e_ambiguous_039, e2e_colloquial_145, e2e_colloquial_146, e2e_colloquial_157, e2e_colloquial_160, e2e_codeswitch_168, e2e_codeswitch_169, e2e_codeswitch_177
- WRONG_TOOL_CHAIN (16): e2e_multistep_050, e2e_clarification_101, e2e_clarification_102, e2e_clarification_104, e2e_clarification_107, e2e_clarification_108, e2e_clarification_110, e2e_clarification_111, e2e_clarification_112, e2e_clarification_113, e2e_clarification_114, e2e_clarification_115, e2e_clarification_116, e2e_clarification_117, e2e_clarification_119, e2e_clarification_120
- PARAMS_LEGAL_FAIL (14): e2e_ambiguous_003, e2e_ambiguous_005, e2e_ambiguous_006, e2e_ambiguous_007, e2e_ambiguous_009, e2e_ambiguous_010, e2e_ambiguous_011, e2e_ambiguous_024, e2e_ambiguous_034, e2e_revision_137, e2e_colloquial_143, e2e_colloquial_147, e2e_colloquial_148, e2e_colloquial_149
- TOOL_EXECUTED_MISMATCH (8): e2e_incomplete_003, e2e_incomplete_005, e2e_incomplete_013, e2e_incomplete_015, e2e_incomplete_017, e2e_incomplete_051, e2e_incomplete_052, e2e_codeswitch_178
- D_TOOL_ERROR (1): e2e_incomplete_053
- OTHER (1): e2e_multistep_043
- USER_RESPONSE_MISMATCH (1): e2e_incomplete_014

## 7. Off/On Case Changes
- fail_to_pass (13): e2e_clarification_103, e2e_clarification_106, e2e_clarification_109, e2e_codeswitch_163, e2e_codeswitch_179, e2e_constraint_013, e2e_incomplete_002, e2e_incomplete_006, e2e_incomplete_008, e2e_incomplete_010, e2e_incomplete_011, e2e_incomplete_018, e2e_multistep_040
- pass_to_fail (17): e2e_ambiguous_006, e2e_ambiguous_007, e2e_ambiguous_009, e2e_ambiguous_010, e2e_ambiguous_011, e2e_ambiguous_024, e2e_ambiguous_028, e2e_clarification_104, e2e_clarification_117, e2e_codeswitch_168, e2e_codeswitch_177, e2e_constraint_035, e2e_incomplete_052, e2e_multistep_008, e2e_multistep_050, e2e_revision_137, e2e_simple_001

## 8. Verification

- `python -m py_compile core/memory.py core/assembler.py core/context_store.py config.py tests/test_state_contract.py`: pass
- `pytest tests/test_state_contract.py tests/test_context_store.py tests/test_session_persistence.py -q`: 38 passed
- `pytest tests/test_layered_memory_context.py tests/test_assembler_skill_injection.py tests/test_config.py -q`: 27 passed
- `pytest -q`: 1020 passed, 8 failed. The residual reentry failure also reproduces with `ENABLE_SESSION_STATE_BLOCK=false`; representative compare/scenario/hotspot failures reproduce independently of this change. Full failing modules: `tests/test_compare_tool.py`, `tests/test_hotspot_analyzer.py`, `tests/test_residual_reentry_transcripts.py`, `tests/test_scenario_comparator.py`.
- `ENABLE_SESSION_STATE_BLOCK=false python evaluation/eval_end2end.py --samples evaluation/benchmarks/end2end_tasks.jsonl --output-dir evaluation/results/end2end_full_v4_state_off --mode router`: completed with network escalation after a sandbox-network run was aborted.
- `ENABLE_SESSION_STATE_BLOCK=true python evaluation/eval_end2end.py --samples evaluation/benchmarks/end2end_tasks.jsonl --output-dir evaluation/results/end2end_full_v4_state --mode router`: completed with network escalation.
