# Wave 2 Parameter-Ambiguous Gate Retry Failure

## 1. Scope

This retry implemented the requested narrow fixes:

- Split Stage 3 accepts already-canonical `vehicle_type`, `pollutants`, `pollutant`, `road_type`, and `season` values before alias normalization.
- Split pollutant normalization strips common emission suffixes before alias lookup.
- Split stance resolution falls back from low-confidence non-directive stance to directive only when required slots are present by raw Stage 2 slot existence and no explicit hedging is present.

Verification before the gate:

- `tests/test_contract_split.py`: 21 passed.
- Full `pytest -q`: 1158 passed.

Gate command:

```bash
/home/kirito/miniconda3/bin/python evaluation/run_oasc_matrix.py \
  --groups E \
  --samples evaluation/benchmarks/held_out_tasks.jsonl \
  --filter-categories parameter_ambiguous \
  --parallel 8 --qps-limit 15 --cache \
  --output-prefix wave2_heldout_param_gate_retry
```

Result: failed the retry gate.

| Metric | Before | Retry | Gate |
|---|---:|---:|---:|
| completion | 14.29% | 28.57% | >= 50% |
| tool_accuracy | 14.29% | 42.86% | n/a |
| parameter_legal_rate | 14.29% | 28.57% | n/a |
| result_data_rate | 14.29% | 42.86% | n/a |
| Stage 3 rejection rate | 42.86% | 0.00% | n/a |
| proceed_rate | 14.29% | 42.86% | n/a |

Per protocol, main smoke and held-out smoke postfix runs were not started.

## 2. Before/After Task-Level Comparison

No held-out user message text is quoted here. Task IDs, criteria, and parameter comparisons are from existing result logs.

| task_id | before | retry | before shape | retry shape |
|---|---:|---:|---|---|
| `e2e_heldout_param_001` | pass | pass | directive proceed | unchanged |
| `e2e_heldout_param_002` | fail | pass | deliberative probed optional `model_year` | directive proceed with runtime `model_year` default |
| `e2e_heldout_param_003` | fail | fail | Stage 3 rejected `vehicle_type` | rejection fixed, but medium-confidence deliberative still probes optional `model_year` |
| `e2e_heldout_param_004` | fail | fail | Stage 3 rejected `pollutants` | rejection fixed, but high-confidence deliberative still probes optional `model_year` |
| `e2e_heldout_param_005` | fail | fail | deliberative probed optional `model_year` | still medium-confidence deliberative probing optional `model_year` |
| `e2e_heldout_param_006` | fail | fail | directive plus Stage 3 rejected `pollutants` | now executes, but evaluator expected explicit `model_year=2012`; runtime default produced 2020 |
| `e2e_heldout_param_007` | fail | fail | exploratory scope clarify | now medium-confidence deliberative probing optional `model_year` |

What improved:

- All Stage 3 rejected-slot failures were removed.
- `e2e_heldout_param_002` moved from fail to pass.
- `e2e_heldout_param_006` moved from no execution to execution, but still failed param legality due model_year.

What did not improve enough:

- Four remaining tasks are blocked by deliberative optional `model_year` probing.
- One task executes but misses an expected non-default model year.

## 3. Root Cause After Retry

One-sentence root cause: the requested low-confidence-only stance fallback was too conservative for this held-out slice because the remaining non-directive Stage 2 stance hints are medium or high confidence, so `ExecutionReadinessContract` still treats no-default optional `model_year` as a deliberative probe blocker even when required factor-query slots are filled.

Evidence from retry logs:

| task_id | retry stance from Stage 2 | retry readiness |
|---|---|---|
| `e2e_heldout_param_003` | deliberative / medium | clarify `model_year` |
| `e2e_heldout_param_004` | deliberative / high | clarify `model_year` |
| `e2e_heldout_param_005` | deliberative / medium | clarify `model_year` |
| `e2e_heldout_param_007` | deliberative / medium | clarify `model_year` |

The first retry fixed the normalizer layer; the residual failure is now readiness policy, not Stage 3 rejection.

Relevant code locations:

- [execution_readiness_contract.py](/home/kirito/Agent1/emission_agent/core/contracts/execution_readiness_contract.py):125 probes no-default optionals for any deliberative branch.
- [stance_resolution_contract.py](/home/kirito/Agent1/emission_agent/core/contracts/stance_resolution_contract.py):81 intentionally falls back only for low-confidence non-directive stance.
- [split_contract_utils.py](/home/kirito/Agent1/emission_agent/core/contracts/split_contract_utils.py):101 now fixes canonical/suffix normalizer rejection, confirmed by retry Stage 3 rejection rate 0%.

## 4. Recommended Next Fix

Do not broaden Fix 1 blindly. The next narrow fix should target `ExecutionReadinessContract`, not Stage 3:

```python
if tool_name == "query_emission_factors":
    if all required slots are filled after Stage 3:
        if no_default_optionals == ["model_year"] and model_year was not explicitly requested:
            proceed with runtime default even when branch == "deliberative"
```

Why this is narrower:

- It preserves deliberative probing for genuinely missing required slots.
- It preserves deliberative probing for tools where optional slots materially change workflow semantics.
- It addresses the actual residual blocker: optional `model_year` blocking saturated factor queries.

Expected effect:

- `e2e_heldout_param_003`, `004`, `005`, and `007` should proceed instead of clarify.
- `e2e_heldout_param_006` may still fail unless raw text or Stage 2 can recover explicit `model_year=2012`; this is a separate year extraction issue.
- Passing 3 of those 4 would move the gate to at least 5/7 = 71.43%.

## 5. Stop Point

Stopped after the failed `parameter_ambiguous` retry gate, as requested. No postfix main smoke or held-out smoke runs were started.
