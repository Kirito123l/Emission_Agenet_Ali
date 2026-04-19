# Phase 2R Wave 1 Report

## 1. Implementation Summary

Wave 1 adds Conversational Stance as first-class AO state and telemetry only. Existing PCM/proceed/clarify decisions are unchanged.

Changed files:

| Area | Files |
|---|---|
| AO schema | `core/analytical_objective.py` |
| Migration | `scripts/migrate_phase_2_4_to_2r.py` |
| Resolver | `core/stance_resolver.py`, `config/stance_signals.yaml` |
| LLM schema | `core/contracts/clarification_contract.py` |
| Orchestration | `core/governed_router.py` |
| Config | `config.py` |
| Tests | `tests/test_analytical_objective.py`, `tests/test_stance_resolver.py`, `tests/test_clarification_contract.py` |

Commits:

| Commit | Purpose |
|---|---|
| `b7106a8` | AO stance schema + incompatible old-session guard + migration script |
| `c649fee` | StanceResolver + signal config + feature flags |
| `f698d9b` | Slot filler schema adds top-level `stance` |
| `94f8169` | GovernedRouter/Clarification telemetry writes stance |
| `8f504c0` | Missing-required Stage 2 turns are labeled deliberative for telemetry |
| `0f16d70` | Independent feature-flag unit coverage |

## 2. Schema And Compatibility

`AnalyticalObjective` now persists:

- `stance`
- `stance_confidence`
- `stance_resolved_by`
- `stance_history`

Old Phase 2.4 AO payloads without `stance` raise `IncompatibleSessionError` with a migration hint. Production AO loading happens through `core/memory.py::MemoryManager._load`. Eval matrix runs clear `eval_*.json` and `eval_naive_*.json` before each group, so the benchmark path should not hit stale AO sessions. Tool cache stores only tool results and does not load AO history.

Migration script: `scripts/migrate_phase_2_4_to_2r.py`.

## 3. LLM Schema

Stage 2 slot filler now asks for:

```json
{
  "slots": {},
  "intent": {},
  "stance": {
    "value": "directive | deliberative | exploratory",
    "confidence": "high | medium | low",
    "reasoning": "..."
  }
}
```

Parser behavior:

- Missing `stance` field falls back to `directive/low`.
- `missing_required` non-empty produces a deterministic `deliberative/high` stance hint.
- No extra LLM call was added; stance reuses the existing qwen-plus slot filler call.

## 4. Tests

| Command | Result |
|---|---:|
| `pytest -q tests/test_analytical_objective.py tests/test_factmemory_refactor.py` | 11 passed |
| `pytest -q tests/test_stance_resolver.py` | 8 passed |
| `pytest -q tests/test_clarification_contract.py tests/test_stance_resolver.py` | 35 passed |
| `pytest -q tests/test_clarification_contract.py tests/test_stance_resolver.py tests/test_analytical_objective.py tests/test_oasc_telemetry.py` | 50 passed |
| Final focused set after flag tests | 52 passed |
| `pytest -q` | 1122 passed, 8 failed |

Full-suite failures are outside the Wave 1 files:

- `calculators/scenario_comparator.py`: `unit` NameError
- `HotspotAnalyzer._build_interpretation`: missing `unit` argument in tests
- `core/router.py` residual reentry transition: `NEEDS_CLARIFICATION -> EXECUTING`

## 5. Stage 2 Smoke

Command:

```bash
python evaluation/run_oasc_matrix.py --groups E \
  --filter-categories multi_turn_clarification,ambiguous_colloquial \
  --parallel 8 --qps-limit 15 --cache \
  --output-prefix phase2r_wave1_smoke
```

Result path: `evaluation/results/phase2r_wave1_smoke_E/`.

| Metric | Result | Gate |
|---|---:|---:|
| data_integrity | clean | clean |
| infrastructure ok | 40/40 | 40/40 |
| overall completion | 37.5% | informational |
| multi_turn_clarification | 65.0% | >=55.0% |
| ambiguous_colloquial | 10.0% | >=8.0% |

Compared with `evaluation/results/phase2_step4_clarification_focus_E/`:

| Category | Phase 2.4 focus | Wave 1 |
|---|---:|---:|
| multi_turn_clarification | 30.0% | 65.0% |
| ambiguous_colloquial | 20.0% | 10.0% |

Wave 1 does not claim stance caused the completion change; stance is not read by decisions yet.

## 6. Telemetry Sanity

Source: `evaluation/results/phase2r_wave1_smoke_E/end2end_logs.jsonl`.

| Check | Result | Gate |
|---|---:|---:|
| clarification telemetry entries | 94 | informational |
| non-empty `stance_value` | 100.0% | >=80.0% |
| Stage 2 stance parse success | 100.0% | >90.0% |
| multi_turn task-level deliberative | 85.0% | >=40.0% |
| ambiguous_colloquial task-level directive | 50.0% | >=50.0% |

Entry-level stance distribution:

| Category | directive | deliberative | exploratory |
|---|---:|---:|---:|
| multi_turn_clarification | 14 | 60 | 0 |
| ambiguous_colloquial | 10 | 10 | 0 |

## 7. Feature Flags

Flags added:

- `ENABLE_CONVERSATIONAL_STANCE`
- `ENABLE_STANCE_LLM_RESOLUTION`
- `ENABLE_STANCE_REVERSAL_DETECTION`

Verification: `tests/test_stance_resolver.py` covers all three independently.

## 8. Latency Note

The Stage 2 average latency in the Wave 1 smoke was `11127.09 ms`.

Reference focus run `evaluation/results/phase2_step4_clarification_focus_E/end2end_metrics.json` recorded `6817.08 ms`.

Observed delta: `+4310.01 ms`.

This exceeds the prompt-level expectation that schema expansion should add less than 500 ms. No runtime profiling was performed in this wave; the observed run includes provider variance and different post-Phase-2.4 code paths, but the latency budget is not cleared.

## 9. Verdict

Wave 1 functional scope is complete:

- AO stance schema exists and persists.
- StanceResolver exists and is unit-tested.
- Stage 2 slot filler returns/accepts stance.
- GovernedRouter writes stance to AO state.
- Clarification telemetry contains stance fields.
- Smoke success-rate gates passed.
- Telemetry distribution gates passed.

Known blocker before relying on this in Wave 2: Stage 2 latency needs profiling or mitigation.
