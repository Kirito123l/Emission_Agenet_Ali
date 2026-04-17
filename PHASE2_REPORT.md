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
