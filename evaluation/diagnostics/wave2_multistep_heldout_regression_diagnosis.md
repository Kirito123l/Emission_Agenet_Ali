# Wave 2 Multi-step Held-out Regression Diagnosis

## 1. Scope

This is a read-only diagnosis. No code was changed and no benchmark was rerun.

Logs read:

- `evaluation/results/wave2_main_full_E/end2end_logs.jsonl`
- `evaluation/results/wave2_heldout_full_retry_E/end2end_logs.jsonl`
- `evaluation/results/heldout_full_phase2r_wave1_E/end2end_logs.jsonl`

Important correction up front: the Wave 2 main full log contains 20 `multi_step` tasks, not 10. The logged result is 18/20 pass = 90.00%. The held-out retry log contains 8/8 fail = 0.00%.

The extra focus requested by the user, `geometry_gated_halt_acceptable`, turned out to be central. Main pass behavior is dominated by legal geometry halts; held-out failures split into:

1. wrong-chain / repeated-execution failures, and
2. evaluator-style failures where the expected chain was fully executed but `expected.success_criteria.geometry_gated_halt_acceptable=true` while `actual.geometry_gated_halt_acceptable=false`.

## 2. Task A

### 2.1 Main Full Multi-step Pass Features

Wave 2 main full E has 18 passing `multi_step` tasks.

High-level distribution:

| Metric | Count |
|---|---:|
| `has_file=true` | 17 |
| `has_file=false` | 1 |
| `test_file=.csv` | 13 |
| `test_file=.xlsx` | 3 |
| `test_file=none` | 1 |
| other / repo fixture path not in extension bucket | 1 |
| `geometry_gated_halt_acceptable=true` | 12 |
| `geometry_gated_halt_acceptable=false` | 6 |
| first-turn `directive` readiness branch | 17 |
| first-turn `deliberative` readiness branch | 1 |

Expected chain length distribution:

| Chain length | Count |
|---|---:|
| 2 | 10 |
| 3 | 7 |
| 4 | 1 |

Expected tool-chain distribution among passes:

| expected_tool_chain | Count |
|---|---:|
| `macro -> dispersion` | 5 |
| `macro -> dispersion -> hotspot` | 3 |
| `macro -> map` | 2 |
| `macro -> dispersion -> map` | 3 |
| `micro -> dispersion -> hotspot` | 1 |
| `macro -> dispersion -> hotspot -> map` | 1 |
| `micro -> dispersion` | 1 |
| `factors -> factors` | 1 |
| `knowledge -> macro` | 1 |

Actual tool-chain pattern among passes:

| actual_tool_chain | Count |
|---|---:|
| `macro only` | 10 |
| `micro only` | 2 |
| `macro -> map` | 2 |
| `macro -> dispersion -> map` | 1 |
| `macro -> dispersion -> hotspot` | 1 |
| `factors -> factors` | 1 |
| `knowledge -> macro` | 1 |

Main pass takeaway: most main `multi_step` passes are not full-chain executions. They are legal early stops after the upstream emission step because `geometry_gated_halt_acceptable=true`.

Abstract message-type pattern in main passes:

- dominant: `macro_dispersion_file_csv`
- common variants: `macro_map_file`, `macro_dispersion_map_file`, `micro_dispersion_file`
- edge cases: `knowledge_then_macro`, `factor_then_factor`

### 2.2 Held-out Full Retry Multi-step Failure Features

Wave 2 held-out retry E has 8 failing `multi_step` tasks.

High-level distribution:

| Metric | Count |
|---|---:|
| `has_file=true` | 8 |
| `test_file=.xlsx` | 5 |
| `test_file=.zip` | 2 |
| `test_file=.csv` | 1 |
| `geometry_gated_halt_acceptable=true` | 0 |
| `geometry_gated_halt_acceptable=false` | 8 |
| first-turn `directive` readiness branch | 8 |

Expected chain length distribution:

| Chain length | Count |
|---|---:|
| 2 | 6 |
| 3 | 2 |

Expected tool-chain distribution among held-out fails:

| expected_tool_chain | Count |
|---|---:|
| `macro -> hotspot` | 2 |
| `factors -> macro` | 1 |
| `macro -> dispersion` | 1 |
| `macro -> hotspot -> map` | 1 |
| `macro -> map` | 1 |
| `micro -> hotspot` | 1 |
| `macro -> dispersion -> map` | 1 |

Actual tool-chain distribution among held-out fails:

| actual_tool_chain | Count |
|---|---:|
| `macro -> macro` | 1 |
| `factors -> factors` | 1 |
| `macro -> dispersion` | 1 |
| `macro -> map` | 2 |
| `micro only` | 1 |
| `macro -> dispersion -> map` | 1 |
| `macro -> dispersion -> hotspot` | 1 |

Abstract held-out message-type pattern:

- `hotspot_after_macro_zip`
- `factor_then_macro_excel`
- `macro_dispersion_excel`
- `macro_hotspot_map_zip`
- `macro_map_excel`
- `micro_hotspot_csv`
- `macro_dispersion_map_excel`

Held-out fail takeaway: unlike main, none of these tasks pass through the geometry-halt tolerance path. All 8 require real downstream continuation, and every failure is on a chain that either:

1. deviates from the expected chain, or
2. matches the expected chain but still fails because the held-out expected success criteria require `geometry_gated_halt_acceptable=true`.

### 2.3 Failure Shape Analysis

Primary failure-shape classification for held-out 8 fails:

| task_id | primary failure_shape | notes |
|---|---|---|
| `e2e_heldout_multistep_001` | `tool_chain_partial` | expected `macro -> hotspot`, got `macro -> macro`; repeated execution |
| `e2e_heldout_multistep_002` | `params_illegal` | expected `factors -> macro`, got `factors -> factors`; `model_year` expected 2018, actual 2020 |
| `e2e_heldout_multistep_003` | `evaluator_mismatch` | exact expected chain executed; all core criteria true; fail aligns with `exp_geom=true` vs `act_geom=false` |
| `e2e_heldout_multistep_004` | `tool_chain_partial` | expected hotspot before map, got `macro -> map` |
| `e2e_heldout_multistep_005` | `evaluator_mismatch` | exact expected chain executed; fail aligns with `exp_geom=true` vs `act_geom=false` |
| `e2e_heldout_multistep_006` | `tool_chain_partial` | expected `micro -> hotspot`, got `micro only` |
| `e2e_heldout_multistep_007` | `evaluator_mismatch` | exact expected chain executed; fail aligns with `exp_geom=true` vs `act_geom=false` |
| `e2e_heldout_multistep_008` | `tool_chain_partial` | expected `macro -> hotspot`, got extra `dispersion` before hotspot |

Aggregate counts:

| failure_shape | Count |
|---|---:|
| `tool_chain_partial` | 4 |
| `evaluator_mismatch` | 3 |
| `params_illegal` | 1 |
| `tool_chain_empty` | 0 |
| `geometry_gated_halt_incorrect` | 0 |
| `halt_acceptable_but_did_extra_exec` | 0 |

The requested extra category, `halt_acceptable_but_did_extra_exec`, is absent in held-out `multi_step`: none of the 8 failed tasks ever reached `actual.geometry_gated_halt_acceptable=true`. That matters because it means the held-out 0% collapse is not caused by “legal halt + one extra wrong step.” Instead, the split is:

- wrong continuation / repeated execution on some tasks, and
- a likely expected/evaluator mismatch on others.

## 3. Task B - Three Representative Held-out Failures

### 3.1 `e2e_heldout_multistep_003` - `macro -> dispersion`

Abstract message type: `macro_dispersion_excel_calm_stable`.

Expected chain:

- `calculate_macro_emission`
- `calculate_dispersion`

First-turn readiness telemetry:

- `trigger_mode=split`
- `stage2_called=false`
- `stage1_filled_slots=["vehicle_type","pollutants","season","meteorology","stability_class"]`
- `stage3_normalizations`: `vehicle_type -> Combination Long-haul Truck`, `pollutants -> ["NOx"]`, `meteorology -> calm_stable`, `stability_class -> S`
- `final_decision=proceed`
- `proceed_mode=fallback`
- `tool_name=calculate_dispersion`
- `execution_readiness.readiness_branch=directive`
- `execution_readiness.readiness_decision=proceed`

Per-tool execution:

1. `calculate_macro_emission`
   - executed: yes
   - error: none
   - result: macro emission success on 6 links
2. `calculate_dispersion`
   - executed: yes
   - error: none
   - result: dispersion success, 11024 receptors

AO / context-store signal:

- one AO only
- two tool calls appended to the same AO
- AO completed cleanly with `objective_satisfied=true`
- no blocked continuation, no missing dependency signal

Response text prefix:

`已完成重型货车NOx排放计算和冬季静风稳定条件下的扩散模拟...`

Why evaluator marked fail:

- `actual.tool_chain_match=true`
- `tool_executed=true`
- `params_legal=true`
- `result_has_data=true`
- but `expected.success_criteria.geometry_gated_halt_acceptable=true` while `actual.geometry_gated_halt_acceptable=false`

This is the cleanest evaluator-mismatch example: the system did exactly the requested two-step chain and still failed.

### 3.2 `e2e_heldout_multistep_005` - `macro -> render_spatial_map`

Abstract message type: `macro_map_excel`.

Expected chain:

- `calculate_macro_emission`
- `render_spatial_map`

First-turn readiness telemetry:

- `trigger_mode=split`
- `stage2_called=true`
- Stage 2 resolved:
  - `pollutants=["CO"]`
  - `scenario_label="早高峰"`
  - `intent.tool=calculate_macro_emission`
  - `stance.value=directive`
- `final_decision=proceed`
- `proceed_mode=snapshot_direct`
- `execution_readiness.readiness_branch=directive`

Per-tool execution:

1. `calculate_macro_emission`
   - executed: yes
   - error: none
   - result: macro emission success on 6 links
2. `render_spatial_map`
   - executed: yes
   - error: none
   - result: `Map rendered: 6 features`

AO / context-store signal:

- AO#1 completed after macro emission
- AO#2 was created as a reference AO for the map step
- map rendering completed cleanly in AO#2
- block telemetry shows file/session state carried across turns

Response text prefix:

`## 宏观排放计算结果 ... 已成功生成早高峰CO排放强度热力图...`

Why evaluator marked fail:

- exact expected chain executed
- all core success criteria are true
- fail aligns again with `expected.geometry_gated_halt_acceptable=true` vs `actual=false`

This is not a chain-break failure. It is another expected/evaluator-style failure.

### 3.3 `e2e_heldout_multistep_007` - `macro -> dispersion -> render_spatial_map`

Abstract message type: `macro_dispersion_map_excel`.

Expected chain:

- `calculate_macro_emission`
- `calculate_dispersion`
- `render_spatial_map`

First-turn readiness telemetry:

- `trigger_mode=split`
- `stage2_called=false`
- rule-driven chain selection
- `final_decision=proceed`
- `proceed_mode=fallback`
- `execution_readiness.readiness_branch=directive`

Per-tool execution:

1. `calculate_macro_emission`
   - executed: yes
   - error: none
2. `calculate_dispersion`
   - executed: yes
   - error: none
3. `render_spatial_map`
   - executed: yes
   - error: none

AO / context-store signal:

- AO#1 handled macro and reached `complete_blocked` only because the full objective was not yet satisfied
- AO#2 resumed pending work and completed downstream continuation
- trace shows `artifact_already_provided_detected` / `action_readiness_already_provided`, then the final render step
- this is a successful cross-step continuation path, not a broken dependency path

Response text prefix:

`🌤 扩散气象条件 ... ## 扩散计算结果 ...`

Why evaluator marked fail:

- exact expected three-step chain executed
- all core success criteria are true
- fail aligns with `expected.geometry_gated_halt_acceptable=true` vs `actual=false`

This is the strongest evidence that at least part of held-out `multi_step` 0% is not router execution failure at all.

## 4. Task C - Main Full Comparison

### 4.1 `macro -> dispersion`: held-out `003` vs main `e2e_multistep_001`

Main comparison task:

- expected chain: `macro -> dispersion`
- actual chain: `macro only`
- `geometry_gated_halt_acceptable=true`
- pass

Key difference:

- main pass is a legal early halt on a CSV file with no geometry
- held-out `003` fully executes both macro and dispersion on an Excel file and still fails

Implication:

- this pair does not show a held-out execution bug; it shows a different evaluation path
- main relies on halt tolerance, held-out `003` tries to execute through

### 4.2 `macro -> render_spatial_map`: held-out `005` vs main `e2e_multistep_003`

Main comparison task:

- expected chain: `macro -> render_spatial_map`
- actual chain: `macro -> render_spatial_map`
- pass

Key difference:

- both tasks execute the exact same 2-step chain successfully
- both have `geometry_gated_halt_acceptable=false` in actual criteria
- main expected criteria do not require geometry halt
- held-out expected criteria do require geometry halt

Implication:

- this pair points directly at a held-out expected/evaluator issue, not a router chain issue

### 4.3 `macro -> dispersion -> render_spatial_map`: held-out `007` vs main `e2e_multistep_005`

Main comparison task:

- expected chain: `macro -> dispersion -> render_spatial_map`
- actual chain: exact same 3-step chain
- same file family: `test_6links.xlsx`
- pass

Held-out `007`:

- same expected 3-step chain
- exact same actual 3-step chain
- same file family: `test_6links.xlsx`
- fail

Key difference:

- main expected success criteria do not include `geometry_gated_halt_acceptable`
- held-out expected success criteria do include `geometry_gated_halt_acceptable=true`
- actual criteria are otherwise effectively the same

Implication:

- this is very strong evidence of a held-out expected/evaluator mismatch for at least one subset of held-out multi-step tasks

## 5. Task D - Root Cause Hypotheses

### Hypothesis 1 - Held-out Expected / Evaluator Problem

Claim:

Some held-out `multi_step` tasks encode `geometry_gated_halt_acceptable=true` as a required expected criterion even when the full expected chain is successfully executed.

Evidence:

- `e2e_heldout_multistep_003`, `005`, `007` all have:
  - exact expected chain executed
  - `tool_executed=true`
  - `params_legal=true`
  - `result_has_data=true`
  - fail
- all three also have:
  - `expected.success_criteria.geometry_gated_halt_acceptable=true`
  - `actual.geometry_gated_halt_acceptable=false`
- main analogues `e2e_multistep_003` and `e2e_multistep_005` pass with the same exact-chain behavior because their expected criteria do not require geometry halt

How to falsify:

- inspect `evaluation/eval_end2end.py` success comparison on `geometry_gated_halt_acceptable`
- confirm whether expected subset matching treats `true` as a mandatory equality rather than a tolerance flag

Repair path:

- evaluator semantics change: interpret `geometry_gated_halt_acceptable=true` as permissive tolerance, not as a required actual criterion
- or benchmark fix: remove that field from held-out tasks that already expect the full chain to execute

### Hypothesis 2 - Wave 2 Wrong-Continuation / Repeated-Execution Bug

Claim:

A subset of held-out `multi_step` failures are real router/control-flow errors where Wave 2 continues with the wrong downstream step or repeats the upstream step.

Evidence:

- `e2e_heldout_multistep_001`: expected `macro -> hotspot`, got `macro -> macro`
- `e2e_heldout_multistep_002`: expected `factors -> macro`, got `factors -> factors`
- `e2e_heldout_multistep_004`: expected hotspot before map, got `macro -> map`
- `e2e_heldout_multistep_006`: expected `micro -> hotspot`, got `micro only`
- `e2e_heldout_multistep_008`: expected `macro -> hotspot`, got extra `dispersion` before hotspot

How to falsify:

- inspect whether `rule:desired_chain`, `rule:pending`, or AO reference transitions consistently misroute when the next step is `analyze_hotspots`
- compare with main `multi_step` pass traces that use hotspot continuations such as `e2e_multistep_049`

Repair path:

- fix chain continuation logic in the split path, especially pending-step resolution and downstream tool selection after the first artifact is recorded
- this likely lives near the same continuation machinery implicated in the Wave 2 multi-turn regression

### Hypothesis 3 - Shared Continuation-State Family Bug with Multi-turn Regression

Claim:

The wrong-chain held-out `multi_step` failures and the accepted Wave 2 `multi_turn_clarification` regression may share one family root cause: after one tool succeeds, split-path readiness is recomputed from scratch instead of preserving an explicit next-step objective.

Evidence:

- repeated-exec cases in held-out `multi_step`: `macro -> macro`, `factors -> factors`
- wrong-step substitutions: map or dispersion is chosen where hotspot was expected
- these are structurally similar to the multi-turn diagnosis, where Wave 2 loses the pending collection objective and re-enters execution from a fresh snapshot
- the strongest overlap is not `halt_acceptable_but_did_extra_exec` itself, which is absent here, but “post-success readiness recomputation chooses the wrong next action”

How to falsify:

- inspect AO lifecycle for wrong-chain multi-step tasks and check whether the follow-up AO lacks an explicit preserved desired chain
- compare to main hotspot success `e2e_multistep_049` to see whether the pass path depends on a different rule source such as `rule:desired_chain`

Repair path:

- add split-native continuation state for multi-step objectives, analogous to the missing split-native collection state proposed for multi-turn clarification
- do not rely on fresh LLM/rule re-resolution alone after the first artifact is produced

### Hypothesis 4 - Held-out Fixture Sensitivity, But Not a Generic File-Parser Failure

Claim:

Held-out multi-step uses more `.xlsx` and `.zip_shapefile` fixtures than main passes, and that changes the continuation regime, but file parsing itself is not the dominant failure.

Evidence:

- main pass cohort is dominated by CSV fixtures and legal geometry halts
- held-out fail cohort is dominated by Excel/ZIP fixtures that continue further
- however, the three evaluator-mismatch tasks parse and execute successfully, including exact-chain success
- therefore the parser/file analyzer is not failing broadly on held-out files

How to falsify:

- inspect file-analysis confidence and dataset roles across all 8 held-out tasks
- check whether any failed task shows low-confidence or missing file role metadata; current logs do not

Repair path:

- if needed, narrow to downstream continuation logic conditioned on file geometry / artifact type, not to file parsing generally

## 6. Task E - Paper Meaning

Classification: **known limitation with a concrete root-cause split, not just a data artifact**.

Why:

- the 0% held-out result is too severe to dismiss as benign held-out specialness
- but it is also not a single fatal architecture failure, because the 8 fails split into:
  - real continuation bugs, and
  - likely benchmark/evaluator mismatch on `geometry_gated_halt_acceptable`
- that means the paper can honestly report this as a limitation in the held-out continuation setting while also explaining that part of the measured collapse is an evaluation-contract issue rather than pure execution incapacity

One-sentence paper framing:

> Wave 2's held-out multi-step collapse is a mixed limitation: some failures expose real continuation-state defects, while others appear to be caused by the evaluator treating geometry-halt tolerance as a required success condition even when the full downstream chain executed correctly.

## 7. Benchmark Correction Applied

The held-out benchmark was corrected at v5 after this diagnosis.

Applied fix set:

- `e2e_heldout_multistep_001`
- `e2e_heldout_multistep_003`
- `e2e_heldout_multistep_004`
- `e2e_heldout_multistep_005`
- `e2e_heldout_multistep_007`
- `e2e_heldout_multistep_008`

Why 6 tasks rather than only the 3 exact-chain failures:

- `003`, `005`, `007` were already exact-chain passes masked by the bad `geometry_gated_halt_acceptable` criterion.
- `001`, `004`, `008` are still real wrong-continuation failures, but their incorrect halt criterion would also have blocked evaluator pass after a future Wave 3 continuation fix.
- correcting the benchmark first ensures Wave 3 verification can measure the continuation bug family cleanly.

The 3 `constraint_violation` tasks (`constraint_005/006/007`) retain `geometry_gated_halt_acceptable` by design.

E-group rerun on v5:

- result: `3/8` pass on `multi_step` = `37.50%`
- newly passing tasks: `003`, `005`, `007`
- remaining real continuation-bug tasks: `001`, `002`, `004`, `006`, `008`

Updated interpretation:

- Hypothesis 1 was confirmed benchmark-side.
- Hypothesis 2 and Hypothesis 3 remain the explanation for the remaining five failures and should be addressed in Wave 3.
