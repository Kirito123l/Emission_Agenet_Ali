# Phase 2.4 Gate 1 Diagnosis

## Gate Result

Command:

```bash
python evaluation/run_oasc_matrix.py --groups E \
  --filter-categories multi_turn_clarification \
  --parallel 8 --qps-limit 15 --cache
```

Artifact:

- `evaluation/results/end2end_full_v5_oasc_E/end2end_metrics.json`
- `evaluation/results/end2end_full_v5_oasc_E/end2end_logs.jsonl`

| Metric | Gate | Actual |
|---|---:|---:|
| multi_turn_clarification success | >= 50% | 40% (8/20) |
| tool_accuracy | - | 45% |
| parameter_legal_rate | - | 55% |
| result_data_rate | - | 70% |
| data_integrity | clean | clean |

Execution stopped at Gate 1.

## Intent Telemetry Distribution

Across 44 ClarificationContract telemetry entries:

| tool_intent.confidence | Count |
|---|---:|
| high | 44 |
| low | 0 |
| none | 0 |

| tool_intent.resolved_by | Count |
|---|---:|
| rule:pending | 38 |
| rule:file_task_type | 4 |
| llm_slot_filler | 2 |

Fast path vs LLM path:

| Path | Count |
|---|---:|
| fast_rule | 42 |
| llm_slot_filler | 2 |

Stage 2 intent parsing:

| Stage 2 called | llm_intent_parse_success=true | Parse success rate |
|---:|---:|---:|
| 20 | 20 | 100% |

The LLM intent fallback fired on two tasks:

| task_id | success | resolved_tool | note |
|---|---:|---|---|
| e2e_clarification_103 | true | query_emission_factors | fast miss recovered by llm_slot_filler |
| e2e_clarification_113 | false | query_emission_factors | intent recovered, later failed from duplicate tool chain |

## Failed Task Breakdown

| task_id | infra_status | error | tool_chain | last resolved_by |
|---|---|---|---|---|
| e2e_clarification_102 | unknown | `invalid literal for int() with base 10: 'missing'` | [] | none |
| e2e_clarification_106 | ok | - | calculate_micro_emission x3 | rule:pending |
| e2e_clarification_107 | unknown | `invalid literal for int() with base 10: 'missing'` | [] | none |
| e2e_clarification_108 | unknown | `invalid literal for int() with base 10: 'missing'` | [] | none |
| e2e_clarification_109 | unknown | `invalid literal for int() with base 10: 'missing'` | [] | none |
| e2e_clarification_110 | unknown | `invalid literal for int() with base 10: 'missing'` | [] | none |
| e2e_clarification_111 | ok | - | calculate_macro_emission x3 | rule:pending |
| e2e_clarification_112 | ok | - | calculate_micro_emission | rule:file_task_type |
| e2e_clarification_113 | ok | - | query_emission_factors x2 | rule:pending |
| e2e_clarification_115 | ok | - | calculate_macro_emission x2 | rule:pending |
| e2e_clarification_117 | unknown | `invalid literal for int() with base 10: 'missing'` | [] | none |
| e2e_clarification_120 | ok | - | calculate_macro_emission x2 | rule:pending |

Observations:

- 6/12 failures have no classifier or clarification telemetry because the task aborted with `invalid literal for int() with base 10: 'missing'`.
- Among failures with telemetry, intent is already `high`; the remaining failures are not primarily intent-resolution misses.
- `rule:pending` dominates failed telemetry, indicating the AO carried a resolved tool forward but still produced duplicate or incomplete tool chains.

## Latency Note

Current Stage 2 average latency is `6889.11 ms`.

The commit 13 sanity run printed `stage2_avg_latency_ms=5289.13`; this Gate 1 run is therefore about `+1599.98 ms`. That exceeds the design-review stop threshold of `>1s`, so this is recorded as a Gate 1 issue.

## Sanity Observation From Commit 13

| Run | multi_turn_clarification |
|---|---:|
| Phase 2.3 baseline `phase2_pcm_clarification_E` | 40% (8/20) |
| Commit 13 first-class PCM smoke | 50% (10/20) |

- `e2e_clarification_106` improved because the Phase 2.3 probe max-turn fix only formed a closed loop after collection state became first-class.
- `e2e_clarification_116` was excluded as neutral because the baseline failed with `invalid literal for int() with base 10: 'missing'`, leaving no classifier or clarification telemetry.

## Stop Point

Per protocol, Stage 3 ambiguous_colloquial, all-category smoke, full A+E, and ablations were not run.
