# Phase 2 C+D Smoke Comparison

## Overview

Task Pack C+D adds the governed-only `clean_dataframe` tool. This smoke verifies that adding a new LLM-visible governed tool does not disturb existing task routing, parameter legality, tool execution, or result-data production.

Result: pre and post are perfectly aligned across all four top-level metrics and all 5 tested categories. Adding `clean_dataframe` produced zero behavior drift on the 10-task smoke subset.

## Subset

`evaluation/results/cd_smoke/smoke_10.jsonl` contains 10 tasks:

| Category | Task IDs |
|---|---|
| simple | `e2e_simple_001`, `e2e_simple_002` |
| parameter_ambiguous | `e2e_ambiguous_001`, `e2e_ambiguous_002` |
| multi_step | `e2e_multistep_001`, `e2e_multistep_002` |
| incomplete | `e2e_incomplete_001`, `e2e_incomplete_002` |
| constraint_violation | `e2e_constraint_001`, `e2e_constraint_002` |

## Infrastructure

| Field | Pre | Post |
|---|---:|---:|
| run_status | completed | completed |
| data_integrity | clean | clean |
| network_failed | 0/10 | 0/10 |
| wall_clock_sec | 65.19 | 40.09 |
| cache_hit_rate | 0.60 | 0.00 |

## Overall Metrics

| Metric | Pre | Post | Delta |
|---|---:|---:|---:|
| completion_rate | 0.80 | 0.80 | 0pp |
| tool_accuracy | 0.90 | 0.90 | 0pp |
| parameter_legal_rate | 0.50 | 0.50 | 0pp |
| result_data_rate | 0.50 | 0.50 | 0pp |

## Per-category Metrics

| Category | Pre completion | Post completion | Delta | Pre tool_accuracy | Post tool_accuracy |
|---|---:|---:|---:|---:|---:|
| simple | 2/2 | 2/2 | 0 | 1.00 | 1.00 |
| parameter_ambiguous | 1/2 | 1/2 | 0 | 0.50 | 0.50 |
| multi_step | 2/2 | 2/2 | 0 | 1.00 | 1.00 |
| incomplete | 2/2 | 2/2 | 0 | 1.00 | 1.00 |
| constraint_violation | 1/2 | 1/2 | 0 | 1.00 | 1.00 |

## Clarification Metrics

| Metric | Pre | Post |
|---|---:|---:|
| trigger_count | 8 | 8 |
| proceed_rate | 0.375 | 0.375 |
| stage2_hit_rate | not recorded in user pre summary | 0.25 |
| short_circuit_rate | not recorded in user pre summary | 0.625 |

## Architecture Extensibility Evidence

The smoke target was not to prove new `clean_dataframe` capability quality; it was to verify the architectural claim that a new governed tool can be added through the Phase 2 registry/executor/context-store path without disrupting existing tasks.

Evidence:

- Four top-level metrics are unchanged: `0pp` drift on completion, tool accuracy, parameter legality, and result-data rate.
- All 5 categories have identical pass counts pre and post.
- Infrastructure was clean in both runs: `data_integrity=clean`, `network_failed=0/10`.

This is usable Chapter 4 E2E evidence for the architecture extensibility claim: adding a new tool did not perturb LLM tool selection on the existing smoke workload.

## Acceptance Rule

Because C+D only adds a tool and should not alter existing task behavior:

- Overall `completion_rate` pre vs post delta should be <= 3pp.
- No category should have pass-to-fail flips.

Observed:

- Overall `completion_rate` delta: `0pp`.
- Category drift: `0` in all 5 categories.

## Verdict

PASS. The C+D smoke shows zero behavior drift across 10 tasks and 5 categories.
