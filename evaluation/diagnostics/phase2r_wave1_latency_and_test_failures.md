# Phase 2R Wave 1 Diagnostic: Test Failures And Stage 2 Latency

## Scope

This diagnostic is read-only with respect to production/evaluator code. It checks:

1. Whether the 8 full-suite failures reported during Wave 1 were introduced by Wave 1 commits.
2. Whether the Stage 2 latency increase is explained by the Wave 1 prompt/schema changes or by Stage 2 trigger volume/outliers.

## Task A: 8 Test Failure Clarification

### Current failing nodeids

The 8 failures observed in the dirty working tree were:

| Test | Failure shape |
|---|---|
| `tests/test_compare_tool.py::TestCompareScenariosTool::test_multi_result_type_comparison` | `NameError: unit is not defined` |
| `tests/test_compare_tool.py::TestCompareScenariosTool::test_summary_readable` | `NameError: unit is not defined` |
| `tests/test_hotspot_analyzer.py::TestInterpretation::test_complete_regional_interpretation` | `_build_interpretation()` missing `unit` |
| `tests/test_hotspot_analyzer.py::TestInterpretation::test_sparse_local_interpretation` | `_build_interpretation()` missing `unit` |
| `tests/test_hotspot_analyzer.py::TestInterpretation::test_partial_regional_interpretation` | `_build_interpretation()` missing `unit` |
| `tests/test_residual_reentry_transcripts.py::test_transcript_explicit_new_task_skips_recovered_reentry_target` | invalid `NEEDS_CLARIFICATION -> EXECUTING` transition |
| `tests/test_scenario_comparator.py::TestDispersionComparison::test_concentration_deltas` | `NameError: unit is not defined` |
| `tests/test_scenario_comparator.py::TestDispersionComparison::test_meteorology_changes_detected` | `NameError: unit is not defined` |

### Before Wave 1 exact-nodeid run

Command run in a temporary worktree at `ba533e0` (parent of first Wave 1 commit `b7106a8`):

```bash
pytest -q \
  tests/test_compare_tool.py::TestCompareScenariosTool::test_multi_result_type_comparison \
  tests/test_compare_tool.py::TestCompareScenariosTool::test_summary_readable \
  tests/test_hotspot_analyzer.py::TestInterpretation::test_complete_regional_interpretation \
  tests/test_hotspot_analyzer.py::TestInterpretation::test_sparse_local_interpretation \
  tests/test_hotspot_analyzer.py::TestInterpretation::test_partial_regional_interpretation \
  tests/test_residual_reentry_transcripts.py::test_transcript_explicit_new_task_skips_recovered_reentry_target \
  tests/test_scenario_comparator.py::TestDispersionComparison::test_concentration_deltas \
  tests/test_scenario_comparator.py::TestDispersionComparison::test_meteorology_changes_detected
```

Result:

```text
8 passed in 1.48s
```

### Clean Wave 1 HEAD exact-nodeid run

Command run in a clean temporary worktree at `efd8730`:

```bash
pytest -q <same 8 nodeids>
```

Result:

```text
8 passed in 1.82s
```

### Full-suite caveat

Running full `pytest -q` directly at `ba533e0` is not a valid apples-to-apples comparison because several Phase files were untracked in this repository state. A clean `ba533e0` worktree fails collection on missing `core.ao_classifier` and `core.naive_router`. Overlaying current untracked files makes collection proceed, but then current tests expect newer `FactMemory(session_id=...)` API not present in tracked `ba533e0`, producing unrelated AO test failures.

The exact 8 nodeids above are the relevant check for the reported failures.

### Earliest introduction

There is no git commit that introduces these 8 failures in the tested history:

- exact 8 pass at pre-Wave1 `ba533e0`
- exact 8 pass at clean Wave1 HEAD `efd8730`
- exact 8 fail only in the dirty current working tree

The current dirty files touching those failure areas are:

```text
calculators/hotspot_analyzer.py
calculators/scenario_comparator.py
core/router.py
```

`git diff --stat` for those files:

```text
calculators/hotspot_analyzer.py    |   17 +-
calculators/scenario_comparator.py |   14 +-
core/router.py                     | 1052 +++++++++++++++++++++++++++++++++++-
```

Conclusion for Task A: the previous report phrase "outside Wave 1 files" was directionally correct, but incomplete. The precise statement is: **the 8 failures are not introduced by Wave 1 commits; they are caused by uncommitted dirty working-tree changes outside the Wave 1 file set.**

## Task B: Stage 2 Latency Root Cause

### Stage 2 trigger count

Source logs:

- Phase 2.4 focus rerun: `evaluation/results/phase2_step4_clarification_focus_E/end2end_logs.jsonl`
- Wave 1 smoke: `evaluation/results/phase2r_wave1_smoke_E/end2end_logs.jsonl`

| Run | clarification telemetry entries | Stage 2 called | Stage 2 avg latency |
|---|---:|---:|---:|
| Phase 2.4 focus rerun | 67 | 40 | 6817.08 ms |
| Wave 1 smoke | 94 | 57 | 11127.09 ms |
| Delta | +27 | +17 | +4310.01 ms |

By category:

| Run | Category | entries | Stage 2 called | avg | p90 | max |
|---|---|---:|---:|---:|---:|---:|
| Phase 2.4 | multi_turn_clarification | 57 | 30 | 6491.89 | 8141.37 | 10102.00 |
| Phase 2.4 | ambiguous_colloquial | 10 | 10 | 7792.67 | 9107.79 | 11593.21 |
| Wave 1 | multi_turn_clarification | 74 | 37 | 10839.38 | 13583.21 | 14640.18 |
| Wave 1 | ambiguous_colloquial | 20 | 20 | 11659.34 | 14044.02 | 14950.74 |

#### Did commit `8f504c0` make more turns enter Stage 2?

No, not structurally.

`8f504c0` changes `_extract_llm_stance_hint()` after `_run_stage2_llm()` already returned. It does not alter the conditions that decide whether Stage 2 is called.

Observed Stage 2 count in the final Wave 1 smoke is 57. The earlier Wave 1 smoke before `8f504c0` printed `stage2_hit_rate=0.625` and `trigger_count=96`, equivalent to about 60 Stage 2 calls. The final count is lower, not higher. The increase versus Phase 2.4 focus rerun is therefore not attributable to `8f504c0`.

### Prompt character count

Measured by `len(ClarificationContract._stage2_system_prompt())`.

| Version | System prompt chars |
|---|---:|
| Phase 2.4 (`ba533e0` worktree) | 1003 |
| Wave 1 HEAD | 1230 |
| Delta | +227 |

The prompt delta is about 22.6% of the system prompt, but the latency average rose about 63.2% (`6817.08 -> 11127.09 ms`). Static evidence does not support prompt length as the sole or primary cause.

### Wave 1 latency distribution

Wave 1 Stage 2 latency across 57 calls:

| Metric | ms |
|---|---:|
| p50 | 10622.11 |
| p90 | 13948.69 |
| p99 | 14640.18 |
| max | 14950.74 |

Phase 2.4 Stage 2 latency across 40 calls:

| Metric | ms |
|---|---:|
| p50 | 6693.94 |
| p90 | 8141.37 |
| p99 | 10102.00 |
| max | 11593.21 |

This is not a "few outliers pulled up the average" pattern. The median and p90 both shifted upward.

### Static root-cause assessment

Static evidence points to a combination of:

1. More Stage 2 calls: 40 -> 57.
2. Per-call latency distribution shift: p50 6693.94 -> 10622.11 ms.

Prompt length alone is unlikely to explain the +4310 ms average increase:

- only +227 system-prompt characters
- no additional LLM call was added
- p50 shifted, so it is not only a tail/outlier issue

The likely causes need runtime profiling or provider/request telemetry, especially:

- whether qwen-plus response token count increased due to `stance.reasoning`
- whether JSON schema complexity causes slower decoding/generation
- whether provider variance/rate state differed between the two smoke runs
- whether Wave 1 changed the set of Stage 2 turns toward harder prompts

### Wave 2 prompt-size implication

Because static analysis does not identify prompt length as the main cause, no strong length-only projection is justified.

If Wave 2 adds an ExecutionReadinessContract description of roughly 300-600 characters to the same Stage 2 system prompt, the system prompt would grow from 1230 to about 1530-1830 chars. Based on this diagnostic, that increase should not be treated as the dominant risk by itself; the larger risk is more Stage 2 calls or longer model completions.

## Conclusion

### Test failures

The 8 failures are **not Wave 1 commit regressions**. They are present only in the dirty working tree, caused by uncommitted changes outside the Wave 1 files.

### Latency

The Stage 2 latency budget is **not cleared**:

- Stage 2 calls increased by 17 on the same 40-task category set.
- p50 latency increased by 3928.17 ms.
- system prompt length increased by only 227 chars.

### Wave 2 decision

Do **not** push Wave 2 directly if Wave 2 will add more Stage 2 calls or more required LLM-generated fields.

Recommended gate before Wave 2 implementation:

1. Insert a short latency optimization/measurement round.
2. Measure Stage 2 output token counts and per-call prompt payload size.
3. Add a per-turn latency breakdown to clarification telemetry if not already present.
4. Keep stance-dependent Wave 2 logic from increasing Stage 2 call count.

Verdict: **insert latency optimization/measurement before Wave 2 behavioral changes.**
