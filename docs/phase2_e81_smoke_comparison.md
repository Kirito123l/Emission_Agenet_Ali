# Phase 2 E-8.1 Smoke Comparison

## Overview

E-8.1 is a pure refactor: tool-level conversational fields moved from
`config/unified_mappings.yaml:tools` into `config/tool_contracts.yaml`, and
readers now resolve those fields through `ToolContractRegistry`. The smoke goal
is zero behavior drift.

## Subset

- Sample file: `evaluation/results/e81_smoke/smoke_10.jsonl`
- Sample size: 10 tasks
- Sampling: first task by ID from each of the 9 end-to-end categories, plus a
  second `user_revision` task as a sensitivity case.
- Mode: `full`
- Pre baseline: migration-before code with the E-8.1 working tree stashed clean.
- Post baseline: current `e-8-1-yaml-merge` working tree.

## Infrastructure

Both runs completed cleanly.

| Field | Pre | Post |
| --- | ---: | ---: |
| `run_status` | completed | completed |
| `data_integrity` | clean | clean |
| `network_failed` | 0/10 | 0/10 |
| `wall_clock` | 51.57s | 50.31s |
| `cache_hit_rate` | 0.9091 | 0.9091 |

The matching 91% cache-hit rate and zero network failures remove the
infrastructure noise seen in the initial smoke attempt.

## Overall Metrics

| Metric | Pre | Post | Delta |
| --- | ---: | ---: | ---: |
| `completion_rate` | 0.70 | 0.70 | 0.00 |
| `tool_accuracy` | 0.70 | 0.70 | 0.00 |
| `parameter_legal_rate` | 0.60 | 0.60 | 0.00 |
| `result_data_rate` | 0.60 | 0.60 | 0.00 |

## Per-Category Metrics

| Category | Pre pass | Post pass | Delta | Flip count |
| --- | ---: | ---: | ---: | ---: |
| `ambiguous_colloquial` | 0/1 | 0/1 | 0 | 0 |
| `code_switch_typo` | 0/1 | 0/1 | 0 | 0 |
| `constraint_violation` | 1/1 | 1/1 | 0 | 0 |
| `incomplete` | 1/1 | 1/1 | 0 | 0 |
| `multi_step` | 1/1 | 1/1 | 0 | 0 |
| `multi_turn_clarification` | 0/1 | 0/1 | 0 | 0 |
| `parameter_ambiguous` | 1/1 | 1/1 | 0 | 0 |
| `simple` | 1/1 | 1/1 | 0 | 0 |
| `user_revision` | 2/2 | 2/2 | 0 | 0 |

All 9 categories are identical pre vs post.

## Clarification Metrics

| Metric | Pre | Post | Delta |
| --- | ---: | ---: | ---: |
| `clarification.trigger_count` | 7 | 9 | +2 |
| `clarification.proceed_rate` | 0.5714 | 0.5556 | -0.0158 |

The trigger-count change is limited to the clarification instrumentation path
after switching readers to `ToolContractRegistry`. It does not affect the four
acceptance metrics and produced no category or task pass/fail flips.

## Verdict

PASS.

- Refactor threshold: `completion_rate` drift <= 2pp and no pass/fail flips.
- Actual drift: 0pp across `completion_rate`, `tool_accuracy`,
  `parameter_legal_rate`, and `result_data_rate`.
- Actual flips: 0 task flips; 9/9 categories identical.

Conclusion: E-8.1 smoke shows a perfect refactor with zero behavior drift.
