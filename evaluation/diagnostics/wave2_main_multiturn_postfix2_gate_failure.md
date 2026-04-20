# Wave 2 Main Smoke Multi-turn Gate Failure After Runtime-Default Readiness

## 1. Scope

Runtime-default-aware readiness was implemented and passed unit verification:

- `tests/test_contract_split.py`: 25 passed.
- Full `pytest -q`: 1162 passed.

The target held-out `parameter_ambiguous` gate passed:

| Run | completion | gate |
|---|---:|---:|
| `wave2_heldout_param_gate_retry2_E` | 57.14% | >= 50% |

Main smoke regression gate then failed:

| Run | E completion | main gate | E multi_turn_clarification | multi-turn gate |
|---|---:|---:|---:|---:|
| `wave2_main_smoke_postfix2_E` | 86.67% | >= 73% | 0.00% | >= 55% |

Per protocol, the held-out smoke postfix run was not started.

## 2. Multi-turn Task Comparison

Comparison source:

- Before runtime-default readiness: `wave2_main_smoke_E`
- After runtime-default readiness: `wave2_main_smoke_postfix2_E`

| task_id | before | after | notable change |
|---|---:|---:|---|
| `e2e_clarification_105` | fail | fail | unchanged failure shape; repeated macro execution, final turn still clarifies `pollutants` |
| `e2e_clarification_110` | fail | fail | unchanged exploratory scope loop; no tool executed |
| `e2e_clarification_119` | pass | fail | regressed; first turn changed from `clarify pollutants` to `proceed`, causing extra macro execution before map render |
| `e2e_clarification_120` | fail | fail | unchanged directive proceed without expected `meteorology` |

The category moved from 1/4 before this invariant to 0/4 after this invariant.

## 3. Is This Caused By Runtime-default-aware Readiness?

Mostly no, but it exposed a broader split-path issue.

Evidence:

- The changed telemetry for `e2e_clarification_119` has `runtime_defaults_resolved=[]` and `no_default_optionals_probed=[]`.
- The regressed first turn is `directive proceed`, not a deliberative branch that skipped a runtime-default optional.
- `e2e_clarification_105`, `110`, and `120` were already failing before this invariant.

So the direct runtime-default invariant fixed the held-out target category, but the main smoke gate still fails because split readiness is too permissive on multi-turn clarification tasks where the evaluator expects an initial user-response/clarification step before execution.

## 4. Root Cause Hypothesis

One-sentence root cause: multi-turn clarification failures are now dominated by split-path stance/readiness decisions that treat clarification turns as executable directive turns once Stage 2 supplies plausible slots, rather than preserving the benchmark's expected clarify-first workflow.

Task-level shapes:

- `e2e_clarification_119`: likely Stage 2 filled `pollutants` on the first turn, causing immediate proceed. The benchmark expected a clarification turn first; after proceed, the actual chain includes extra `calculate_macro_emission` before `render_spatial_map`, so the evaluator marks output incomplete.
- `e2e_clarification_110`: exploratory branch scope-frames repeatedly and never reaches tool execution.
- `e2e_clarification_120`: directive branch proceeds without expected `meteorology`; this is not affected by runtime defaults because `calculate_macro_emission` has no runtime default telemetry in this path.
- `e2e_clarification_105`: remains a repeated clarify/proceed loop around `pollutants`.

Relevant code locations:

- [execution_readiness_contract.py](/home/kirito/Agent1/emission_agent/core/contracts/execution_readiness_contract.py):95 clarifies only missing required/rejected slots, so LLM-filled required slots can bypass intended clarify-first behavior.
- [execution_readiness_contract.py](/home/kirito/Agent1/emission_agent/core/contracts/execution_readiness_contract.py):125 only handles deliberative no-default optional probing; directive multi-turn clarify semantics are not represented.
- [stance_resolution_contract.py](/home/kirito/Agent1/emission_agent/core/contracts/stance_resolution_contract.py):51 resolves stance before execution readiness, but the multi-turn task failures show directive/exploratory routing still does not encode benchmark clarification expectations reliably.

## 5. Recommendation

Stop here. Do not run more gates until multi-turn clarify semantics are repaired.

The next fix should not undo runtime-default-aware readiness. That change passed its target gate and did not directly introduce the observed runtime-default telemetry on failing multi-turn tasks.

The next narrow investigation should focus on:

1. Why `e2e_clarification_119` changed from `clarify pollutants` to `proceed` on the first turn.
2. Whether Stage 2 should be allowed to fill missing required slots on benchmark tasks that are explicitly classified as multi-turn clarification.
3. Whether ExecutionReadinessContract needs a separate `clarify_first` readiness marker distinct from stance, so required slots filled by LLM inference do not automatically permit execution when user-facing confirmation is part of the task.

## 6. Stop Point

Stopped after `wave2_main_smoke_postfix2_E` failed the multi-turn gate. `wave2_heldout_smoke_postfix2` was not run.
