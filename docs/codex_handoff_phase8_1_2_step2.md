# Codex Handoff: Phase 8.1.2 Step 2

## Completed Changes

- Step 2A OFF preflight verified direct environment control:
  - `ENABLE_LLM_DECISION_FIELD=false`
  - `ENABLE_CONTRACT_SPLIT=true`
  - `ENABLE_GOVERNED_ROUTER=true`
  - `clarification_llm_model=qwen3-max`
  - `ao_classifier_model=qwen3-max`
- Confirmed archived `evaluation/archive/phase5_3/run_phase5_3_ablation.py` is not safe to use directly:
  - its `PROJECT_ROOT = Path(__file__).resolve().parents[1]` now resolves under `evaluation/archive`, not repo root;
  - its `_run_one()` does `env.update(mode_env)`, so parent `ENABLE_LLM_DECISION_FIELD=false` would not override `governance_full`'s `true`.
- Used direct `evaluation/eval_end2end.py` path for Step 2A, matching governance-full env surface with decision field forced off.

## Files Changed

- Added this handoff file only: `docs/codex_handoff_phase8_1_2_step2.md`
- No production code changed.
- `docs/architecture/v1_freeze_reality_audit.md` was not updated for Step 2 because the run is invalid/incomplete.

## Tests Already Passed

- No tests passed in this checkpoint.
- `git diff --check` passed after this handoff file.

## Current Blocker

Step 2A OFF n=3 cannot produce valid data because the configured qwen3-max / Model Studio account returns:

```text
Access denied, please make sure your account is in good standing
type: Arrearage
code: Arrearage
```

All three OFF reps aborted almost immediately with `run_status=aborted_billing` and `data_integrity=contaminated`.

Partial invalid artifacts:

- `evaluation/results/phase8_1_2/step2_off/governance_full/rep_1/end2end_metrics.json`
- `evaluation/results/phase8_1_2/step2_off/governance_full/rep_2/end2end_metrics.json`
- `evaluation/results/phase8_1_2/step2_off/governance_full/rep_3/end2end_metrics.json`

Each file reports only 1 completed/recorded task before abort, so none can be used for OFF mean/std.

## Exact Next Commands

After fixing the provider/account billing issue, rerun Step 2A from scratch. Do not reuse the contaminated partial results.

```bash
rm -rf evaluation/results/phase8_1_2/step2_off
```

Use direct eval path, not the archived ablation runner:

```bash
set -euo pipefail
export ENABLE_AO_AWARE_MEMORY=true
export ENABLE_AO_CLASSIFIER_RULE_LAYER=true
export ENABLE_AO_CLASSIFIER_LLM_LAYER=true
export ENABLE_AO_BLOCK_INJECTION=true
export ENABLE_AO_PERSISTENT_FACTS=true
export ENABLE_AO_FIRST_CLASS_STATE=true
export ENABLE_SESSION_STATE_BLOCK=false
export ENABLE_GOVERNED_ROUTER=true
export ENABLE_CLARIFICATION_CONTRACT=true
export ENABLE_CONTRACT_SPLIT=true
export ENABLE_SPLIT_INTENT_CONTRACT=true
export ENABLE_SPLIT_STANCE_CONTRACT=true
export ENABLE_SPLIT_READINESS_CONTRACT=true
export ENABLE_SPLIT_CONTINUATION_STATE=true
export ENABLE_RUNTIME_DEFAULT_AWARE_READINESS=true
export ENABLE_LLM_DECISION_FIELD=false
export ENABLE_CROSS_CONSTRAINT_VALIDATION=true
export ENABLE_READINESS_GATING=true
export ENABLE_LLM_USER_REPLY_PARSER=false
for rep in 1 2 3; do
  ~/miniconda3/bin/python evaluation/eval_end2end.py --clear-cache >/dev/null
  ~/miniconda3/bin/python evaluation/eval_end2end.py \
    --samples evaluation/benchmarks/end2end_tasks.jsonl \
    --output-dir "evaluation/results/phase8_1_2/step2_off/governance_full/rep_${rep}" \
    --mode router \
    --parallel 4 \
    --qps-limit 15 \
    --smoke \
    --cache
done
```

Then run Step 2B with the same env surface except:

```bash
export ENABLE_LLM_DECISION_FIELD=true
```

## Benchmark / Smoke / Evaluation Status

- OFF Step 2A: blocked, invalid, contaminated.
- ON Step 2B: not started.
- §7 Reconciler Activation Sanity: not written.
- Requested Step 2 commit: not created.

## Risks

- The archived ablation runner is misleading after archive relocation and should not be used without fixing path/env precedence.
- The invalid partial result directories exist under ignored `evaluation/results/`; remove them before rerun to avoid mixing contaminated and valid data.
- The benchmark abort happened inside Stage 2 LLM calls, before useful reconciler/B validator telemetry could be collected.

## Things Not To Repeat

- Do not cite the current Step 2A partial metrics.
- Do not commit §7 until both OFF and ON n=3 complete with `run_status=completed` and `data_integrity=clean`.
- Do not proceed to Step 2B or Step 3 until the provider/account blocker is cleared.
