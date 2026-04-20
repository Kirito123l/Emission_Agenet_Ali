# Phase 1.6 Report

## Implementation Summary

Changed files:
- [core/ao_manager.py](/home/kirito/Agent1/emission_agent/core/ao_manager.py)
- [core/ao_classifier.py](/home/kirito/Agent1/emission_agent/core/ao_classifier.py)
- [core/governed_router.py](/home/kirito/Agent1/emission_agent/core/governed_router.py)
- [tests/test_ao_manager.py](/home/kirito/Agent1/emission_agent/tests/test_ao_manager.py)
- [tests/test_ao_classifier.py](/home/kirito/Agent1/emission_agent/tests/test_ao_classifier.py)

### Fix A: AO premature complete
- `complete_ao()` now requires `objective_satisfied=true` in addition to the original checks.
- Multi-step intent detection is rule-based in [core/ao_manager.py](/home/kirito/Agent1/emission_agent/core/ao_manager.py): signal phrases + implied tool-group extraction.
- Single-step factor queries still complete normally.
- `create_ao()` implicit completion path now also checks objective satisfaction before marking the previous AO `COMPLETED`; otherwise it marks it `ABANDONED`.

### Fix B: governed tool-chain extraction
- [core/governed_router.py](/home/kirito/Agent1/emission_agent/core/governed_router.py) now backfills `result.executed_tool_calls` from the just-written memory turn when the wrapped router response omitted them.
- Targeted validation subset output: [end2end_phase16_fixb_check/end2end_logs.jsonl](/home/kirito/Agent1/emission_agent/evaluation/results/end2end_phase16_fixb_check/end2end_logs.jsonl)
- All 9 previously affected task_ids now have non-empty `actual.tool_chain`: {"e2e_ambiguous_020": ["query_emission_factors"], "e2e_clarification_102": ["query_emission_factors", "query_emission_factors", "query_emission_factors"], "e2e_constraint_008": ["calculate_micro_emission"], "e2e_constraint_014": ["calculate_micro_emission"], "e2e_constraint_047": ["calculate_macro_emission"], "e2e_multistep_009": ["calculate_macro_emission"], "e2e_multistep_041": ["calculate_macro_emission"], "e2e_multistep_042": ["calculate_macro_emission"], "e2e_simple_011": ["query_emission_factors"]}

### Fix C: Layer 1 hit-rate uplift
- [core/ao_classifier.py](/home/kirito/Agent1/emission_agent/core/ao_classifier.py) adds:
  - rule 6: `first_message_in_session -> NEW_AO`
  - rule 7: `no_active_ao_no_revision_signal -> NEW_AO`
- Revision/reference signal guard prevents rule 7 from taking explicit revision-style messages.

## Verification

Executed:
- `python -m py_compile core/ao_manager.py core/ao_classifier.py core/governed_router.py evaluation/eval_end2end.py evaluation/run_oasc_matrix.py`
- `pytest -q tests/test_ao_manager.py tests/test_ao_classifier.py tests/test_benchmark_acceleration.py tests/test_eval_failsafe.py`
- Result: `31 passed`

## Smoke Results

Artifacts:
- [end2end_smoke_v7_fix_A/end2end_metrics.json](/home/kirito/Agent1/emission_agent/evaluation/results/end2end_smoke_v7_fix_A/end2end_metrics.json)
- [end2end_smoke_v7_fix_E/end2end_metrics.json](/home/kirito/Agent1/emission_agent/evaluation/results/end2end_smoke_v7_fix_E/end2end_metrics.json)

| Group | completion_rate | tool_accuracy | data_integrity | wall_clock_sec |
|---|---:|---:|---|---:|
| A | 0.8000 | 0.8333 | clean | 75.68 |
| E | 0.7000 | 0.8333 | clean | 100.26 |

## Full A vs E

Artifacts:
- [end2end_full_v7_fix_A/end2end_metrics.json](/home/kirito/Agent1/emission_agent/evaluation/results/end2end_full_v7_fix_A/end2end_metrics.json)
- [end2end_full_v7_fix_E/end2end_metrics.json](/home/kirito/Agent1/emission_agent/evaluation/results/end2end_full_v7_fix_E/end2end_metrics.json)

| Group | completion_rate | tool_accuracy | parameter_legal | result_data | data_integrity | wall_clock_sec |
|---|---:|---:|---:|---:|---|---:|
| A | 0.6778 | 0.7611 | 0.6889 | 0.7556 | clean | 361.71 |
| E | 0.7389 | 0.8611 | 0.7611 | 0.8333 | clean | 470.22 |

Per-category A -> E completion deltas:
- ambiguous_colloquial: +25.0 pp
- code_switch_typo: +5.0 pp
- constraint_violation: +17.6 pp
- incomplete: -16.7 pp
- multi_step: -5.0 pp
- multi_turn_clarification: +15.0 pp
- parameter_ambiguous: +12.5 pp
- simple: +0.0 pp
- user_revision: +0.0 pp

## Hard Floor

| Metric | Hard Floor | Actual | Pass |
|---|---:|---:|---|
| E completion rate | >= 72% | 73.89% | YES |
| E vs A | >= +6 pp | 6.11 pp | YES |
| pass_to_fail (E vs A) | < 8 | 14 | NO |
| parameter_ambiguous category | >= 50% | 66.67% | YES |

Hard floor verdict: **NOT MET**

Because `pass_to_fail=14`, I stopped after A+E and did **not** run the remaining 6-group ablation matrix.

## Classifier Telemetry Comparison

| Metric | v6 (pre-fix) | v7 (post-fix) |
|---|---:|---:|
| Layer 1 hit rate | 26.2% | 67.9% |
| Layer 2 call count | 242 | 105 |
| Layer 2 avg latency | 4719.8 ms | 5209.3 ms |

Artifacts:
- [end2end_full_v6_telemetry_E/end2end_logs.jsonl](/home/kirito/Agent1/emission_agent/evaluation/results/end2end_full_v6_telemetry_E/end2end_logs.jsonl)
- [end2end_full_v7_fix_E/end2end_logs.jsonl](/home/kirito/Agent1/emission_agent/evaluation/results/end2end_full_v7_fix_E/end2end_logs.jsonl)

## Pass / Fail Analysis (E vs A)

pass_to_fail (14):
["e2e_ambiguous_002", "e2e_ambiguous_038", "e2e_clarification_110", "e2e_clarification_119", "e2e_codeswitch_163", "e2e_codeswitch_178", "e2e_constraint_035", "e2e_constraint_048", "e2e_incomplete_001", "e2e_incomplete_011", "e2e_incomplete_013", "e2e_multistep_001", "e2e_multistep_002", "e2e_multistep_010"]

fail_to_pass (25):
["e2e_ambiguous_024", "e2e_ambiguous_026", "e2e_ambiguous_028", "e2e_ambiguous_030", "e2e_ambiguous_039", "e2e_clarification_103", "e2e_clarification_104", "e2e_clarification_114", "e2e_clarification_117", "e2e_clarification_118", "e2e_codeswitch_172", "e2e_codeswitch_177", "e2e_codeswitch_180", "e2e_colloquial_147", "e2e_colloquial_152", "e2e_colloquial_153", "e2e_colloquial_154", "e2e_colloquial_158", "e2e_constraint_005", "e2e_constraint_007", "e2e_constraint_008", "e2e_constraint_011", "e2e_constraint_047", "e2e_multistep_009", "e2e_multistep_043"]

Observations from the diff:
- Net gain = +11 tasks.
- All pass_to_fail and fail_to_pass tasks are still classified as `输出不完整` in the evaluator.
- Fix A/B/C improved `parameter_ambiguous`, `constraint_violation`, `ambiguous_colloquial`, and `multi_turn_clarification`.
- `incomplete` and `multi_step` regressed versus A.

## Remaining E Failures (Phase 2 target set)

E still fails on 47 tasks:
["e2e_ambiguous_002", "e2e_ambiguous_003", "e2e_ambiguous_005", "e2e_ambiguous_020", "e2e_ambiguous_038", "e2e_clarification_101", "e2e_clarification_102", "e2e_clarification_106", "e2e_clarification_107", "e2e_clarification_108", "e2e_clarification_109", "e2e_clarification_110", "e2e_clarification_111", "e2e_clarification_112", "e2e_clarification_113", "e2e_clarification_115", "e2e_clarification_116", "e2e_clarification_119", "e2e_clarification_120", "e2e_codeswitch_163", "e2e_codeswitch_169", "e2e_codeswitch_178", "e2e_colloquial_143", "e2e_colloquial_144", "e2e_colloquial_145", "e2e_colloquial_146", "e2e_colloquial_148", "e2e_colloquial_149", "e2e_colloquial_157", "e2e_colloquial_160", "e2e_constraint_013", "e2e_constraint_035", "e2e_constraint_048", "e2e_incomplete_001", "e2e_incomplete_002", "e2e_incomplete_008", "e2e_incomplete_011", "e2e_incomplete_013", "e2e_incomplete_015", "e2e_multistep_001", "e2e_multistep_002", "e2e_multistep_003", "e2e_multistep_004", "e2e_multistep_010", "e2e_multistep_041", "e2e_multistep_044", "e2e_simple_011"]

## Simplifications Made

- The full B/C/D/F ablation matrix was not run because the hard-floor gate failed after A+E.
- Fix B validation used a 9-task targeted subset before the full run.

## Remaining Risks

- Hard floor is still blocked by `pass_to_fail=14`.
- `multi_step` remains below A after Fix A (`70.0% -> 65.0%`).
- `incomplete` regressed materially (`94.4% -> 77.8%`).

READY FOR PHASE 2: NO
