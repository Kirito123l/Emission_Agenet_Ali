# Wave 2 Stage 3 Held-out Gate Failure

## 1. Scope

Stage 1 and Stage 2 passed:

- `pytest -q`: 1146 passed.
- `wave2_latency_gate_smoke_E`: Stage 2 mean 6015.17 ms, p50 6466.81 ms, p90 8466.06 ms, max 8850.64 ms.

Stage 3 main smoke passed the E completion gate:

- `wave2_main_smoke_E`: completion 76.67%, infra unknown 0.

Stage 3 held-out smoke partially passed but did not cover `parameter_ambiguous`:

- `wave2_heldout_smoke_E`: completion 50.00%, simple 50.00%, code_switch_typo 100.00%, infra unknown 0.
- The smoke sample contained no `parameter_ambiguous` tasks, so the category gate could not be evaluated from that run.

To evaluate the missing hard gate without reading the held-out benchmark source file, I ran a category-filtered E-only held-out gate:

```bash
/home/kirito/miniconda3/bin/python evaluation/run_oasc_matrix.py \
  --groups E \
  --samples evaluation/benchmarks/held_out_tasks.jsonl \
  --filter-categories parameter_ambiguous \
  --parallel 8 --qps-limit 15 --cache \
  --output-prefix wave2_heldout_parameter_ambiguous_gate
```

Result: `parameter_ambiguous` failed at 14.29% (1/7), below the required 40%.

## 2. Failure Summary

| Metric | Value |
|---|---:|
| tasks | 7 |
| completion | 14.29% |
| tool_accuracy | 14.29% |
| parameter_legal_rate | 14.29% |
| result_data_rate | 14.29% |
| infra unknown | 0 |
| Stage 2 avg latency | 5993.70 ms |
| Stage 3 rejection rate | 42.86% |
| proceed_rate | 14.29% |

Failure shape:

| Shape | Count |
|---|---:|
| `final_decision=clarify`, no tool executed | 6 |
| Deliberative branch probed optional `model_year` | 2 |
| Stage 3 rejected already identified slot | 3 |
| Exploratory branch scope clarification | 1 |
| Directive branch failed because Stage 3 rejected pollutant | 1 |

## 3. Task-Level Findings

No held-out user message text is quoted here. Task IDs, expected params, and evaluator actuals are from existing result logs.

| task_id | result | branch | decision | pending/rejected | primary failure |
|---|---:|---|---|---|---|
| `e2e_heldout_param_001` | pass | directive | proceed | runtime default `model_year` | none |
| `e2e_heldout_param_002` | fail | deliberative | clarify | pending `model_year` | over-clarified optional slot despite required slots present |
| `e2e_heldout_param_003` | fail | deliberative | clarify | rejected `vehicle_type` | Stage 3 rejected high-confidence LLM normalized vehicle |
| `e2e_heldout_param_004` | fail | deliberative | clarify | rejected `pollutants` | Stage 3 rejected high-confidence LLM normalized pollutant |
| `e2e_heldout_param_005` | fail | deliberative | clarify | pending `model_year` | over-clarified optional slot despite required slots present |
| `e2e_heldout_param_006` | fail | directive | clarify | rejected `pollutants` | Stage 3 rejected high-confidence LLM normalized pollutant |
| `e2e_heldout_param_007` | fail | exploratory | clarify | pending `scope` | stance overrode a fully specified factor query into scope framing |

## 4. Root Cause

One-sentence root cause: the split path still trusts Stage 2 stance and Stage 3 rejection too aggressively for `parameter_ambiguous` factor queries, so fully specified high-confidence slot fills are converted into clarify/probe turns instead of `snapshot_direct` execution.

Code locations:

- [execution_readiness_contract.py](/home/kirito/Agent1/emission_agent/core/contracts/execution_readiness_contract.py):95 clarifies whenever `rejected_slots` is non-empty, even when the rejected value was a high-confidence LLM canonical value.
- [execution_readiness_contract.py](/home/kirito/Agent1/emission_agent/core/contracts/execution_readiness_contract.py):125 probes no-default optionals for `deliberative`, which made optional `model_year` block two held-out factor queries.
- [execution_readiness_contract.py](/home/kirito/Agent1/emission_agent/core/contracts/execution_readiness_contract.py):74 sends `exploratory` directly to scope framing, which blocked one fully specified factor query.
- [split_contract_utils.py](/home/kirito/Agent1/emission_agent/core/contracts/split_contract_utils.py):108 uses pollutant fallback but only exact aliases; it misses common suffix forms like pollutant names followed by an emission noun.
- [stance_resolution_contract.py](/home/kirito/Agent1/emission_agent/core/contracts/stance_resolution_contract.py):51 accepts fast/LLM stance resolution before execution readiness validates whether all required slots are already filled.

## 5. Recommended Minimal Fix

Stop here before Stage 4. The next implementation pass should be narrow:

1. In split Stage 3, accept canonical high-confidence LLM values for `vehicle_type`, `pollutants`, `pollutant`, `road_type`, and `season` when they already match tool legal values or known aliases.
2. Extend pollutant normalization to strip common emission suffix tokens before alias lookup.
3. In `ExecutionReadinessContract`, add a directive override for factor-query tasks: if `tool_name == query_emission_factors`, all required slots are filled after Stage 3, and stance is not backed by explicit user hedging, proceed with runtime defaults instead of probing optional `model_year`.
4. Treat `exploratory` as scope-framing only when required slots are not fully resolved or explicit exploratory wording is present.

Expected effect: the failed `parameter_ambiguous` category should move from 1/7 to at least 5/7, enough to clear the 40% Stage 3 gate and the 50% held-out full floor for this category.

## 6. Stop Point

Per the Wave 2 verification protocol, Stage 4 full runs were not started because a Stage 3 held-out hard gate failed.
