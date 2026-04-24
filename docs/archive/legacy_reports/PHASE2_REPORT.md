# Phase 2 Report

## 1. Architecture Refactor Summary

Completed:

- `core/governed_router.py` reduced to a thin contract orchestrator.
- Added `core/contracts/` package:
  - `base.py`
  - `oasc_contract.py`
  - `clarification_contract.py`
  - `dependency_contract.py`
- `dependency_contract.py` placeholder docstring includes the Phase 3 note requested in prompt.

Compatibility checks:

- `pytest -q tests/test_ao_classifier.py tests/test_ao_manager.py tests/test_oasc_telemetry.py`
- `26 passed`

## 2. Implementation Summary

Implemented:

- Clarification Contract flags in `config.py`
- `config/unified_mappings.yaml` `tools:` slot declarations using the approved slot proposal
- Clarification telemetry:
  - `confirm_first_detected`
  - `proceed_mode`
- evaluator support:
  - `clarification_telemetry` in task logs
  - `clarification_contract_metrics` in metrics
  - `--filter-categories`
- matrix runner support:
  - group `G`
  - `--filter-categories`
- AO block visibility for `parameter_snapshot` and pending clarification text
- Fix 1:
  - snapshot-direct execution path in `governed_router.py`
  - direct-path fallback back to original UnifiedRouter path on execution failure
- Fix 2:
  - confirm-first detector
  - pending-slot persistence across continuation turns

Validation:

- `pytest -q tests/test_clarification_contract.py tests/test_oasc_telemetry.py tests/test_benchmark_acceleration.py tests/test_ao_classifier.py tests/test_ao_manager.py`
- `43 passed`

## 3. Smoke Verification

### 3.1 Step 4.1: OASC no-regression smoke

Artifact:

- `evaluation/results/phase2_step4_refactor_smoke_E/end2end_metrics.json`

Result:

| Metric | E |
|---|---:|
| completion_rate | 90.00% |
| tool_accuracy | 93.33% |
| parameter_legal | 76.67% |
| result_data | 86.67% |

Status: passed.

### 3.2 Fix 1 only: `ambiguous_colloquial`

Before:

- `evaluation/results/phase2_fix1_colloquial_E/end2end_metrics.json`
- `ambiguous_colloquial = 20.00%`
- `proceed_mode = fallback x10`

After:

- `evaluation/results/phase2_fix1b_colloquial_E/end2end_metrics.json`
- `ambiguous_colloquial = 50.00%`
- `proceed_mode = snapshot_direct x10`

Status: passed the local gate (`>= 50%`).

### 3.3 Fix 2 only: `multi_turn_clarification`

Before:

- `evaluation/results/phase2_fix2_clarification_E/end2end_metrics.json`
- `multi_turn_clarification = 25.00%`

After pending-slot + completion guard iteration:

- `evaluation/results/phase2_fix2d_clarification_E/end2end_metrics.json`
- `multi_turn_clarification = 20.00%`

Status: failed the local gate (`>= 50%`).

Per prompt rule, execution stopped here. Step 4.3 / Step 5 / Step 6 were not run.

### 3.4 Phase 2.2 PCM retry

After PCM trigger widening and probe-turn limits:

- artifact: `evaluation/results/phase2_pcm_clarification_E/end2end_metrics.json`
- `multi_turn_clarification = 40.00%`
- gate: failed (`< 50%`)

Per prompt rule, execution stopped here. Gate 2 / Gate 3 / Gate 4 / full / ablation were not run.

## 4. Fix Verification Evidence

### 4.1 Fix 1: proceed-path deterministic execution

Representative pair 1:

- task: `e2e_colloquial_143`
- before (`phase2_fix1_colloquial_E`):
  - `proceed_mode=fallback`
  - `tool_chain=[]`
  - clarification telemetry still ended with `final_decision=proceed`
- after (`phase2_fix1b_colloquial_E`):
  - `proceed_mode=snapshot_direct`
  - tool call is emitted directly from snapshot

Representative pair 2:

- task: `e2e_colloquial_141`
- before:
  - `vehicle_type` normalized to `Passenger Car` in telemetry
  - executor fallback path still produced text-only clarification
- after:
  - direct path injects compatibility `model_year=2020`
  - direct tool execution proceeds without re-entering UnifiedRouter routing

Observed fact:

- Fix 1 moved all direct-path colloquial proceed cases from `fallback` to `snapshot_direct`.

### 4.2 Fix 2: confirm-first + pending-slot persistence

Representative pair 1:

- task: `e2e_clarification_102`
- latest run (`phase2_fix2d_clarification_E`):
  - turn 1: `NEW_AO`
  - turn 2: `CONTINUATION`
  - turn 3: `CONTINUATION`
  - turn 4: `REVISION`
  - actual chain still becomes `query_emission_factors x3`

Representative pair 2:

- task: `e2e_clarification_106`
- latest run:
  - turn 1: clarify
  - turn 2: clarify
  - turn 3: `snapshot_direct` execute
  - turn 4: `REVISION`
  - actual chain still becomes `calculate_micro_emission x2`

Observed fact:

- confirm-first detection exists in telemetry, but the category still collapses because many follow-up turns are still reclassified as `REVISION` or `NEW_AO` after the first successful execution.
- pending-slot persistence alone did not prevent this category-level failure.

### 4.3 PCM Gate 1 retry: `e2e_clarification_102`

Artifact:

- `evaluation/results/phase2_pcm_clarification_E/end2end_logs.jsonl`

Outcome:

- success: `false`
- actual tool chain: `query_emission_factors x3`

Classifier trace:

```json
[
  {"turn": 1, "eval_router_turn": 1, "classification": "NEW_AO", "reasoning": "first_message_in_session"},
  {"turn": 2, "eval_router_turn": 2, "classification": "CONTINUATION", "reasoning": "short_clarification"},
  {"turn": 3, "eval_router_turn": 3, "classification": "REVISION", "reasoning": "用户当前消息'主干道'是对AO#1已完成查询中默认道路类型（快速路）的修正意图..."},
  {"turn": 4, "eval_router_turn": 4, "classification": "REVISION", "reasoning": "用户当前消息'2021年'明确修改已完成的AO#2..."}
]
```

Clarification telemetry:

```json
[
  {
    "eval_router_turn": 3,
    "classification_at_trigger": "REVISION",
    "stage1_filled_slots": ["road_type"],
    "final_decision": "proceed",
    "confirm_first_detected": false,
    "confirm_first_trigger": null,
    "collection_mode": false,
    "pcm_trigger_reason": null,
    "probe_optional_slot": null,
    "probe_turn_count": 0,
    "probe_abandoned": false,
    "proceed_mode": "snapshot_direct"
  },
  {
    "eval_router_turn": 4,
    "classification_at_trigger": "REVISION",
    "stage1_filled_slots": ["model_year"],
    "final_decision": "proceed",
    "confirm_first_detected": false,
    "confirm_first_trigger": null,
    "collection_mode": false,
    "pcm_trigger_reason": null,
    "probe_optional_slot": null,
    "probe_turn_count": 0,
    "probe_abandoned": false,
    "proceed_mode": "snapshot_direct"
  }
]
```

Important debug finding:

- There is **no turn-1 ClarificationContract telemetry** for `e2e_clarification_102`.
- Therefore turn 1 is not `confirm_first=false`; the contract did not trigger on turn 1 at all.
- The likely local cause is tool-resolution before confirmation detection: `"我需要公交车CO2那类因子，先帮我确认参数"` was classified as `NEW_AO`, but ClarificationContract did not resolve a `tool_name` for it, so PCM never got a chance to record `confirm_first_trigger`.

## 5. Per-Category Breakdown

Only partial verification is available because Step 4.2 failed before all-category smoke/full.

| Category | A clean baseline | E (Phase 1.7 v8) | E (Phase 2 current best) | △ vs A | △ vs E_v8 |
|---|---:|---:|---:|---:|---:|
| ambiguous_colloquial | 45.00% | 35.00% | 50.00% | +5.00 pp | +15.00 pp |
| multi_turn_clarification | 5.00% | 10.00% | 40.00% | +35.00 pp | +30.00 pp |

Note:

- `ambiguous_colloquial` best Phase 2 point comes from `phase2_fix1b_colloquial_E`
- `multi_turn_clarification` latest PCM retry improved to `40.00%`, still below the `50%` gate

## 6. Hard Floor Verdict

Not evaluated.

Reason:

- Step 4.2 / fix-local gate failed before all-category smoke.

## 7. Pass/Fail Analysis

Not produced for full benchmark.

Reason:

- Step 4.3 / Step 5 were not run.

## 8. Clarification Contract Telemetry

Focused telemetry snapshots:

### `ambiguous_colloquial` best run

- artifact: `evaluation/results/phase2_fix1b_colloquial_E/end2end_metrics.json`
- trigger_count: `10`
- stage2_hit_rate: `1.00`
- short_circuit_rate: `0.00`
- proceed_rate: `1.00`
- outcome: `50.00%`

### `multi_turn_clarification` latest run

- artifact: `evaluation/results/phase2_pcm_clarification_E/end2end_metrics.json`
- trigger_count: `45`
- stage2_hit_rate: `0.3778`
- short_circuit_rate: `0.5111`
- proceed_rate: `0.4889`
- outcome: `40.00%`

## 9. Remaining Failure Shape

Current blocking pattern for `multi_turn_clarification`:

1. First successful execution happens before all user-provided follow-up details arrive.
2. Later replies are reclassified as `REVISION` / `NEW_AO`.
3. This creates repeated tool execution (`query_emission_factors xN`, `calculate_macro_emission xN`, `calculate_micro_emission xN`).
4. Evaluator marks the case failed on tool-chain mismatch even when final payload is otherwise complete.

## 10. Final Verdict

READY FOR PHASE 3: NO

Stop point:

- Fix 1 local gate passed
- Fix 2 local gate failed
- Step 4.3 / Step 5 / Step 6 not run

## 11. Phase 2.4 Progress

### 11.1 First-Class State Sanity Observation

| Run | multi_turn_clarification |
|---|---:|
| Phase 2.3 baseline `phase2_pcm_clarification_E` | 40.00% (8/20) |
| Commit 13 first-class PCM smoke | 50.00% (10/20) |

Interpretation used for design iteration:

- `e2e_clarification_106` changed from fail to pass because the Phase 2.3 probe max-turn repair formed a closed loop only after PCM state moved from scattered metadata into first-class `ParameterState`.
- `e2e_clarification_116` was excluded from the sanity comparison because the baseline failed with `invalid literal for int() with base 10: 'missing'` and recorded no classifier or clarification telemetry.
- This is a positive side effect of first-class state, not treated as a regression.

### 11.2 Gate 1 After LLM-Assisted Intent Resolution

Command:

```bash
python evaluation/run_oasc_matrix.py --groups E \
  --filter-categories multi_turn_clarification \
  --parallel 8 --qps-limit 15 --cache
```

Artifact:

- `evaluation/results/end2end_full_v5_oasc_E/end2end_metrics.json`
- `PHASE2_4_GATE1_DIAGNOSIS.md`

| Metric | Gate | Actual |
|---|---:|---:|
| multi_turn_clarification success | >= 50% | 40.00% (8/20) |
| tool_accuracy | - | 45.00% |
| parameter_legal_rate | - | 55.00% |
| result_data_rate | - | 70.00% |

Intent telemetry:

| Distribution | Count |
|---|---:|
| tool_intent.confidence=high | 44 |
| resolved_by rule:* | 42 |
| resolved_by llm_slot_filler | 2 |
| Stage 2 calls with parsed intent | 20/20 |

Stop reason:

- Gate 1 failed; Stage 3 ambiguous_colloquial, all-category smoke, full A+E, and ablations were not run.
- Stage 2 average latency was `6889.11 ms`, about `+1599.98 ms` versus the commit 13 sanity run printed value (`5289.13 ms`), exceeding the >1s stop threshold.

### 11.3 Post-Gate1 Sentinel Fix Rerun

Changes verified:

- Stage 2 prompt now requires missing slots to use JSON `null`.
- LLM sentinel strings (`"missing"`, `"unknown"`, `"none"`, `"n/a"`, `"null"`, case-insensitive) are normalized before entering snapshots.
- Snapshot-direct execution ignores missing/sentinel `model_year` instead of calling `int()` on it.
- Evaluator records local production exceptions as `execution_error*` with traceback instead of treating them as infrastructure failures.

Stage 1 tests:

```bash
pytest -q tests/test_eval_failsafe.py tests/test_clarification_contract.py \
  tests/test_intent_resolver.py tests/test_ao_manager.py tests/test_oasc_telemetry.py
```

Result: `54 passed`.

Stage 2 rerun:

```bash
python evaluation/run_oasc_matrix.py --groups E \
  --filter-categories multi_turn_clarification \
  --parallel 8 --qps-limit 15 --cache
```

| Metric | Gate | Actual |
|---|---:|---:|
| multi_turn_clarification success | >= 50% | 65.00% (13/20) |
| tool_accuracy | - | 70.00% |
| parameter_legal_rate | - | 85.00% |
| result_data_rate | - | 80.00% |
| infrastructure unknown | target 0 | 0 |

Original six `'missing'` exception tasks no longer produce infrastructure-unknown failures in the aggregate run (`infrastructure_health.unknown=0`). The required subtarget "at least 5/6 recover `infrastructure_status=ok`" passed.

Stage 3 non-regression run:

```bash
python evaluation/run_oasc_matrix.py --groups E \
  --filter-categories ambiguous_colloquial \
  --parallel 8 --qps-limit 15 --cache
```

| Metric | Gate | Actual |
|---|---:|---:|
| ambiguous_colloquial success | >= 45% | 10.00% (2/20) |
| tool_accuracy | - | 10.00% |
| parameter_legal_rate | - | 10.00% |
| result_data_rate | - | 10.00% |

Stop reason:

- Stage 3 failed; all-category smoke, full A+E, and ablations were not run.
- The immediate failure shape is that sentinel normalization makes missing no-default optional `model_year` visible again, so 18/20 colloquial tasks short-circuit with a year clarification instead of executing. This is a non-regression failure relative to the approved Stage 3 gate, not an infrastructure issue.

### 11.4 Duplicate Execution Diagnosis

Artifact:

- `evaluation/diagnostics/phase2_4_duplicate_execution.md`

Summary:

- In the six telemetry-bearing Gate 1 failures (`106`, `111`, `112`, `113`, `115`, `120`), first AO completion events all had `completion_path=should_complete_explicit`, `block_reason=None`, `tool_intent=high`, and `parameter_state_collection_mode=False`.
- PCM was active before `snapshot_direct`, but commit 13 correctly cleared `collection_mode` after direct execution. Lifecycle then completed the AO, and later follow-up turns were interpreted as REVISION/NEW_AO or post-completion continuation.
- Root-cause label for next repair prompt: **D1/D2/D3 combined**: clear-too-early for benchmark dialogue shape, complete-too-early after direct execution, and classifier completed-AO bias.
