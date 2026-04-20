# Phase 2R Wave 2 Report

## 1. Summary

Wave 2 replaced the Wave 1 monolithic clarification contract with split intent, stance, and execution-readiness contracts. It repaired the Wave 1 held-out collapse on the targeted `parameter_ambiguous` slice and repaired Stage 2 latency, but it also exposed a serious multi-turn clarification trade-off.

Stage 4 main full completed for both A and E. Stage 4 held-out full did not complete because the provider returned an `Arrearage` billing failure during the A run. The partial held-out A output is contaminated and is not used as a full-run conclusion.

| Area | Result |
|---|---:|
| Stage 1 unit tests after runtime-default readiness | `1162 passed` |
| Stage 2 latency gate E completion | 76.67% |
| Stage 2 latency mean / p50 | 6015 ms / 6467 ms |
| Stage 3 main smoke E completion after postfix2 | 86.67% |
| Stage 3 held-out smoke E completion | 50.00% |
| Stage 3 targeted held-out `parameter_ambiguous` E completion | 57.14% |
| Stage 4 main full A completion | 70.00% |
| Stage 4 main full E completion | 71.67% |
| Stage 4 held-out full | blocked by provider billing failure |

Main full E improves overall completion over A by +1.67 pp and improves tool accuracy by +6.67 pp, but `multi_turn_clarification` regresses sharply. The accepted Wave 2 trade-off is to carry this as known work for Wave 3 rather than repairing it before Stage 4.

## 2. Implementation Changes

### 2.1 Contract Split (Intent / Stance / ExecutionReadiness)

Wave 2 introduced the split path behind `ENABLE_CONTRACT_SPLIT`:

- `IntentResolutionContract`: resolves tool intent before execution readiness.
- `StanceResolutionContract`: resolves directive / deliberative / exploratory stance.
- `ExecutionReadinessContract`: applies stance-dependent readiness decisions and emits `execution_readiness` telemetry.

The old `ClarificationContract` remains available when the split flag is disabled.

### 2.2 PCM Removal

The split path stops depending on Wave 1 PCM fields such as `collection_mode`, `probe_turn_count`, `probe_abandoned`, and `probe_optional_slot`. Split telemetry uses `execution_readiness` metadata instead:

- `readiness_branch`
- `readiness_decision`
- `pending_slot`
- `runtime_defaults_applied`
- `runtime_defaults_resolved`
- `no_default_optionals_probed`

This made Wave 2 logs cleaner but removed one legitimate multi-turn invariant. Section 7.1 records that trade-off explicitly.

### 2.3 Runtime-Default-Aware Readiness Invariant

The deliberative branch no longer probes optional slots that have operational runtime defaults. For example, missing `query_emission_factors.model_year` is classified as resolved by runtime default rather than as an unknowable optional that must be probed.

Effect:

- `wave2_heldout_param_gate_retry2_E` passed the targeted gate at 57.14%.
- The fix did not remove deliberative probing entirely; no-default optionals still probe in deliberative branches.

### 2.4 Stage 3 Canonical Fast-Path + Pollutant Suffix Handling

Split Stage 3 now accepts canonical legal values before alias lookup for:

- `vehicle_type`
- `pollutants`
- `pollutant`
- `road_type`
- `season`

Pollutant normalization also strips common suffix tokens such as Chinese emission nouns and English `emission` / `emissions` / `factor` forms before alias lookup.

Effect:

- The targeted retry eliminated Stage 3 rejection as the residual blocker for held-out `parameter_ambiguous`.
- `wave2_heldout_param_gate_retry_E` moved Stage 3 rejection rate from 42.86% to 0.00%.

### 2.5 Stage 2 Compact Schema + Telemetry

Stage 2 compacted the slot-filler output and added response telemetry. The latency objective was to bring Stage 2 back under the Wave 2 gate after Wave 1's schema expansion caused inflated output and slower calls.

Telemetry now records Stage 2 response size and token-related fields when available, plus a truncated raw response for diagnosis.

### 2.6 Low-Confidence Non-Directive Stance Fallback

Low-confidence non-directive stance can fall back to directive when required slots are present by raw slot existence and no explicit hedging signal is present. This is deliberately conservative:

- It does not canonical-validate slots at stance time.
- It does not override high-confidence deliberative stance.
- It skips fallback when no resolved tool is available.

## 3. Stage 1 Unit Test Results

Latest post-runtime-default readiness verification:

| Check | Result |
|---|---:|
| `tests/test_contract_split.py` | 25 passed |
| Full `pytest -q` | 1162 passed |

Earlier Wave 2 checkpoints:

| Checkpoint | Result |
|---|---:|
| Initial split / Stage 3 held-out gate diagnosis | 1146 passed |
| Canonical fast-path / suffix / stance fallback retry | 1158 passed |

No new tests were run during this final report pass; this pass only ran Stage 4 benchmarks and wrote the report.

## 4. Stage 2 Latency Gate

Wave 1 Stage 2 latency regression was repaired by the compact schema path.

| Run | Stage 2 calls | Mean | p50 | p90 | Max |
|---|---:|---:|---:|---:|---:|
| Wave 1 smoke E (`phase2r_wave1_smoke_E`) | 57 | 11127 ms | 10622 ms | 13949 ms | 14951 ms |
| Wave 2 latency gate E (`wave2_latency_gate_smoke_E`) | 19 | 6015 ms | 6467 ms | 8465 ms | 8851 ms |
| Wave 2 main full E (`wave2_main_full_E`) | 138 | 5484 ms | 5407 ms | 7134 ms | 10397 ms |

Delta from Wave 1 smoke to Wave 2 latency gate:

- Mean improved by 5112 ms.
- p50 improved by 4155 ms.
- The Wave 2 latency gate passed the mean <= 9000 ms and p50 <= 9000 ms objectives.

## 5. Stage 3 Smoke Gates

### 5.1 Main Smoke Result

| Run | Tasks | Completion | Tool accuracy | Infra unknown | Stage 2 mean |
|---|---:|---:|---:|---:|---:|
| `wave2_main_smoke_E` | 30 | 76.67% | 76.67% | 0 | 5983 ms |
| `wave2_main_smoke_postfix2_E` | 30 | 86.67% | 86.67% | 0 | 5644 ms |

`wave2_main_smoke_postfix2_E` passed overall main smoke but failed the multi-turn smoke sub-gate:

| Category | Completion |
|---|---:|
| `ambiguous_colloquial` | 100.00% |
| `code_switch_typo` | 100.00% |
| `constraint_violation` | 100.00% |
| `incomplete` | 100.00% |
| `multi_step` | 100.00% |
| `multi_turn_clarification` | 0.00% |
| `parameter_ambiguous` | 100.00% |
| `simple` | 100.00% |
| `user_revision` | 100.00% |

### 5.2 Held-out Smoke Result (All Categories)

| Run | Tasks | Completion | Tool accuracy | Infra unknown | Stage 2 mean |
|---|---:|---:|---:|---:|---:|
| `wave2_heldout_smoke_E` | 10 | 50.00% | 70.00% | 0 | 6140 ms |

Per-category smoke sample:

| Category | Tasks | Completion |
|---|---:|---:|
| `ambiguous_colloquial` | 1 | 100.00% |
| `code_switch_typo` | 1 | 100.00% |
| `constraint_violation` | 1 | 100.00% |
| `incomplete` | 1 | 0.00% |
| `multi_step` | 1 | 0.00% |
| `multi_turn_clarification` | 2 | 0.00% |
| `simple` | 2 | 50.00% |
| `user_revision` | 1 | 100.00% |

The smoke sample did not include `parameter_ambiguous`, so a targeted gate was run.

### 5.3 Parameter_ambiguous Targeted Gate

| Run | Tasks | Completion | Tool accuracy | Parameter legal | Result data | Infra unknown |
|---|---:|---:|---:|---:|---:|---:|
| `wave2_heldout_parameter_ambiguous_gate_E` | 7 | 14.29% | 14.29% | 14.29% | 14.29% | 0 |
| `wave2_heldout_param_gate_retry_E` | 7 | 28.57% | 42.86% | 28.57% | 42.86% | 0 |
| `wave2_heldout_param_gate_retry2_E` | 7 | 57.14% | 85.71% | 57.14% | 85.71% | 0 |

The final targeted gate passed the >= 50% objective. The known residual issue is `param_006`, where the LLM did not extract an explicit year and runtime default `model_year=2020` was used instead.

## 6. Stage 4 Full Results

### 6.1 Main Benchmark A vs E

Main full completed for both groups.

| Group | Tasks | Completion | Tool accuracy | Parameter legal | Result data | Infra unknown |
|---|---:|---:|---:|---:|---:|---:|
| A | 180 | 70.00% | 77.22% | 71.11% | 76.11% | 0 |
| E | 180 | 71.67% | 83.89% | 68.33% | 78.33% | 0 |

Per-category main full:

| Category | A completion | E completion | Delta |
|---|---:|---:|---:|
| `ambiguous_colloquial` | 45.00% | 65.00% | +20.00 pp |
| `code_switch_typo` | 75.00% | 90.00% | +15.00 pp |
| `constraint_violation` | 76.47% | 76.47% | +0.00 pp |
| `incomplete` | 94.44% | 83.33% | -11.11 pp |
| `multi_step` | 70.00% | 90.00% | +20.00 pp |
| `multi_turn_clarification` | 15.00% | 10.00% | -5.00 pp |
| `parameter_ambiguous` | 62.50% | 66.67% | +4.17 pp |
| `simple` | 95.24% | 80.95% | -14.29 pp |
| `user_revision` | 100.00% | 85.00% | -15.00 pp |

Pass/fail task analysis:

| Shape | Count |
|---|---:|
| both pass | 104 |
| A fail, E pass | 25 |
| A pass, E fail | 22 |
| both fail | 29 |

Category distribution of A pass -> E fail:

| Category | Count |
|---|---:|
| `ambiguous_colloquial` | 3 |
| `constraint_violation` | 4 |
| `incomplete` | 3 |
| `multi_turn_clarification` | 2 |
| `parameter_ambiguous` | 4 |
| `simple` | 3 |
| `user_revision` | 3 |

E failure shapes in main full:

| Shape | Count |
|---|---:|
| tool not executed | 16 |
| params illegal | 17 |
| result/output evaluator mismatch | 18 |

The largest E failure concentration is still `multi_turn_clarification`: 18/20 failed, mostly with repeated executions or missing required user-response behavior rather than infra errors.

### 6.2 Held-out Benchmark A vs E

Held-out full was attempted with:

```bash
/home/kirito/miniconda3/bin/python evaluation/run_oasc_matrix.py --groups A,E \
  --samples evaluation/benchmarks/held_out_tasks.jsonl \
  --parallel 8 --qps-limit 15 --cache \
  --output-prefix wave2_heldout_full
```

The run aborted during group A with provider billing failure:

| Field | Value |
|---|---|
| provider error type | `Arrearage` |
| run status | `aborted_billing` |
| data integrity | `contaminated` |
| completed partial tasks | 51 |
| billing failures | 1 |
| output dir | `evaluation/results/wave2_heldout_full_A` |
| E full result | not produced |

The partial A metrics are not a valid held-out full conclusion:

| Partial group | Tasks scored before abort | Completion | Tool accuracy |
|---|---:|---:|---:|
| A | 51 | 47.06% | 56.86% |

Wave 1 held-out full baseline remains the latest clean full held-out A/E run:

| Group | Tasks | Completion | Tool accuracy |
|---|---:|---:|---:|
| Wave 1 A | 75 | 54.67% | 66.67% |
| Wave 1 E | 75 | 18.67% | 32.00% |

Clean Wave 2 held-out evidence available before the billing abort:

| Run | Scope | Completion |
|---|---|---:|
| `wave2_heldout_smoke_E` | 10-task smoke | 50.00% |
| `wave2_heldout_param_gate_retry2_E` | `parameter_ambiguous`, 7 tasks | 57.14% |

Wave 1 vs Wave 2 full held-out delta per category cannot be computed until `wave2_heldout_full_E` completes cleanly.

### 6.3 Main vs Held-out Comparison (Generalization Check)

Current clean comparison is necessarily partial because Stage 4 held-out full did not complete.

| Evidence | Main | Held-out |
|---|---:|---:|
| Wave 2 E smoke/full overall | main smoke 86.67%; main full 71.67% | held-out smoke 50.00%; targeted `parameter_ambiguous` 57.14% |
| `parameter_ambiguous` | main full E 66.67% | targeted held-out E 57.14% |
| `multi_turn_clarification` | main full E 10.00% | held-out smoke E 0.00% |

Interpretation:

- Wave 2 repairs the catastrophic Wave 1 held-out `parameter_ambiguous` failure enough to pass the targeted gate.
- Full held-out generalization remains unmeasured for Wave 2 because of billing abort.
- Multi-turn clarification remains weak on both main and held-out smoke evidence.

## 7. Known Issues and Trade-offs

### 7.1 Multi-turn Clarification Regression

This is the main accepted Wave 2 trade-off.

| Run | `multi_turn_clarification` completion |
|---|---:|
| Wave 1 smoke E (`phase2r_wave1_smoke_E`) | 65.00% |
| Wave 2 main smoke E before postfix2 | 25.00% |
| Wave 2 main smoke E after postfix2 | 0.00% |
| Wave 2 main full E | 10.00% |

Root cause from `evaluation/diagnostics/wave2_multiturn_regression_deep_diagnosis.md`: Wave 1 PCM carried a legitimate invariant that was not migrated into split contracts.

Precise invariant:

> Once a turn enters parameter-collection mode because user-visible execution readiness is incomplete, subsequent turns must preserve the pending parameter-collection objective until either the required slot is filled or the bounded optional-probe policy explicitly abandons probing; execution readiness is not recomputed from a fresh LLM-filled snapshot alone.

Three observed violation points:

1. Exploratory branch ordering: Wave 2 can run exploratory scope framing before required-slot clarification, causing required slots to be masked by repeated scope questions.
2. No persisted split-native collection state: after execution or clarification, Wave 2 recomputes readiness from a fresh snapshot and can re-enter the same clarification or execute repeatedly.
3. Stage 2 `needs_clarification` ignored: if Stage 2 fills a plausible/default required slot, ExecutionReadiness can proceed even when Stage 2 also produced a clarification question.

This regression is not hidden by the overall main full score. It is a real behavioral loss and should be handled as Wave 3 work if multi-turn clarification remains in scope.

### 7.2 `param_006` Explicit Year Extraction Gap

The targeted held-out `parameter_ambiguous` gate still has a known residual failure: one task contains an explicit model year, but Stage 2 does not extract it. The router then applies runtime default `model_year=2020`, so the task executes but fails expected parameter legality.

This is an LLM explicit-year extraction gap, not the readiness invariant itself.

### 7.3 Other Stage 4 Full Run Issues

Main full E also shows:

- `simple` regression vs A: 80.95% E vs 95.24% A.
- `user_revision` regression vs A: 85.00% E vs 100.00% A.
- `incomplete` regression vs A: 83.33% E vs 94.44% A.
- Standardization confirmation failures for ambiguous vehicle or road-type values.
- Multi-step/render failures where `render_spatial_map` lacked a dispersion result in context.
- Provider billing failure blocked held-out full completion; this must be resolved before any clean Stage 4 held-out claim.

## 8. Wave 3 Recommendations

These are next steps based on observed invariant gaps, not commitments.

### 8.1 Restore Split-native Collection State

Implement a split-native version of the legitimate PCM invariant using `execution_readiness` metadata rather than resurrecting Wave 1 PCM field names. The state should preserve pending slot / pending decision / bounded probe count across turns while keeping Wave 2 telemetry clean.

Expected impact:

- Directly targets repeated execution and repeated clarify/proceed loops in multi-turn tasks.
- Larger surface area than a single branch reorder because AO lifecycle and readiness persistence must agree.

### 8.2 Stage 2 `needs_clarification` Signal Integration

Treat Stage 2 `needs_clarification=true` and `clarification_question` as first-class readiness inputs when slots were filled by default or weak inference. This prevents inferred/defaulted required slots from acting as user permission to execute in clarify-first workflows.

Expected impact:

- Targets tasks like `e2e_clarification_119`, where Stage 2 both asked a clarification question and filled a default pollutant payload.
- Lower surface area than full collection-state restoration, but it may not solve repeated-turn state loss by itself.

### 8.3 Exploratory Branch Ordering

Move missing-required / rejected-slot handling ahead of exploratory scope framing, or constrain exploratory scope framing to cases without pending required slots.

Expected impact:

- Targets scope-loop failures such as `e2e_clarification_110`.
- Smallest change, but it does not solve default-filled proceed or persistence loss.

## 9. Paper Material Callouts

### 9.1 Held-out Evaluation Necessity

Wave 1 looked promising on main `multi_turn_clarification` smoke at 65%, but held-out E collapsed to 18.67% overall and 0% on `simple`, `parameter_ambiguous`, `multi_step`, and `code_switch_typo`. Wave 2's targeted held-out gate shows why held-out evaluation is necessary: the main benchmark alone did not reveal resolver brittleness, and the held-out target forced fixes to Stage 3 normalization and runtime-default readiness.

Suggested citation anchor:

> Main-benchmark gains were insufficient evidence of robustness; held-out evaluation exposed a category-level collapse that only became visible under paraphrased slot and stance distributions.

### 9.2 Invariant Migration Challenge

Deleting PCM was architecturally clean but removed a behavioral invariant that multi-turn clarification depended on. The lesson is not that PCM should remain, but that architectural decomposition must migrate invariants, not only fields.

Suggested citation anchor:

> Refactoring a conversational contract into modular invariants requires preserving interaction-state obligations; removing the state representation without restating the invariant can improve single-turn behavior while regressing multi-turn correctness.

### 9.3 Operational vs Conversational Invariants

Runtime-default-aware readiness is an operational invariant: if a missing optional has an execution-time default, it should not block execution. Multi-turn clarification is a conversational invariant: if the system owes the user a clarification turn, inferred/default values do not by themselves authorize execution.

Suggested citation anchor:

> Operational readiness and conversational readiness are distinct: an argument may be executable because a runtime default exists, while still conversationally premature because the user-facing clarification obligation has not been discharged.

## 10. Commit History

Relevant Wave 2 commits:

| Commit | Subject |
|---|---|
| `48484cb` | Add contract split feature gate scaffold |
| `58d0692` | Implement Wave 2 split contract path |
| `b664866` | Stabilize Wave 2 regression verification |
| `187282f` | Diagnose Wave 2 held-out gate failure |
| `daf7000` | Accept canonical split-stage values before aliasing |
| `73a98e0` | Fallback low-confidence stance when slots are saturated |
| `3cb2406` | Record failed parameter-ambiguous retry gate |
| `b225244` | Centralize contract runtime default lookup |
| `b03f7e3` | Make split readiness runtime-default aware |
| `d56e4ca` | Record main multi-turn gate failure after readiness fix |
| `69a89d6` | Diagnose Wave 2 multi-turn clarification regression |

Final report pass:

- Ran main full A+E successfully and retained `evaluation/results/wave2_main_full_A` / `evaluation/results/wave2_main_full_E`.
- Attempted held-out full A+E; provider billing failure produced only contaminated partial `evaluation/results/wave2_heldout_full_A`.
- Wrote this report without production code changes.
