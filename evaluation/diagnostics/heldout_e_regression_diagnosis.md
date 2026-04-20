# Held-out E-Group Regression Diagnosis

## 1. Scope

This diagnosis is read-only over the Wave 1 held-out result logs:

- `evaluation/results/heldout_full_phase2r_wave1_A/end2end_logs.jsonl`
- `evaluation/results/heldout_full_phase2r_wave1_E/end2end_logs.jsonl`

No production code, benchmark data, or benchmark execution was changed. The only source files inspected for root-cause localization were:

- `core/contracts/clarification_contract.py`
- `core/governed_router.py`
- `config/unified_mappings.yaml`
- `config/tool_contracts.yaml`
- `evaluation/eval_end2end.py`

Sampling note: the preferred priority categories were inspected first (`simple`, `parameter_ambiguous`, `code_switch_typo`). The three selected tasks are not all the same failure shape: two show over-clarification caused by optional `model_year` probing after all expected params were already resolved, while the code-switch sample shows a separate Stage 3 pollutant rejection path. I also inspected `e2e_heldout_revision_004` as a coverage sanity check; it exposes a follow-up/fallback failure but is not one of the three main representative tasks.

## 2. Three Representative Failure Tasks

### 2.1 Task `e2e_heldout_simple_003` (`simple`)

#### 2.1.1 Task info

- `task_id`: `e2e_heldout_simple_003`
- `category`: `simple`
- `user_message_type`: `factor_query_short_zh_vehicle_pollutant_season`
- `expected_tool_chain`: `["query_emission_factors"]`
- `expected_params`: `vehicle_type=Passenger Car`, `pollutants=["PM2.5"]`, `season=夏季`

#### 2.1.2 A group behavior

- Classifier turn-by-turn sequence: none emitted in A log.
- Actual tool chain: `["query_emission_factors"]`
- Actual params, merged across calls: `vehicle_type=小型汽油轿车`, `pollutants=["PM2.5"]`, `model_year=2020`, `season=夏季`
- Evaluator params comparison: pass. `vehicle_type` was accepted as an alias/fuzzy match for `Passenger Car`.
- Response summary: returned PM2.5 emission-factor data for passenger car with chart/table payload and 73 speed points.
- Success criteria met from `actual.criteria`: `tool_executed=true`, `params_legal=true`, `result_has_data=true`.

#### 2.1.3 E group behavior

- Classifier turn-by-turn sequence:
  - eval turn 1: `NEW_AO`, `rule_layer1`, signal `first_message_in_session`, confidence `1.0`
- Clarification telemetry:
  - eval turn 1:
    - `resolution_confidence`: not emitted in this Wave 1 E log
    - `resolution_evidence`: not emitted
    - `resolved_by`: not emitted
    - `tool_intent_resolved_by`: `llm_slot_filler`
    - `tool_intent_confidence`: `high`
    - `stance_value`: `directive`
    - `stance_confidence`: `low`
    - `stance_resolved_by`: `llm_slot_filler`
    - `final_decision`: `clarify`
    - `proceed_mode`: null
    - `collection_mode`: `true`
    - `stage1_filled_slots`: `vehicle_type`, `pollutants`, `season`
    - `stage2_missing_required`: `[]`
    - `stage3_rejected_slots`: `[]`
    - `probe_optional_slot`: `model_year`
    - `probe_turn_count`: `1`
- Actual tool chain: `[]`
- Actual params vs expected field-level diff:
  - `vehicle_type`: expected `Passenger Car`; actual missing
  - `pollutants`: expected `["PM2.5"]`; actual missing
  - `season`: expected `夏季`; actual missing
- Failed success criteria: `tool_executed`, `params_legal`, `result_has_data`
- `execution_error`: none

#### 2.1.4 Attribution

**错误 clarify**. E resolved the expected slots and stance as directive, but because `model_year` is configured as an optional slot without a clarification default, first-turn `collection_mode` stayed true and the contract probed `model_year` instead of proceeding with the runtime default.

Relevant code locations:

- `config/unified_mappings.yaml:556`: `query_emission_factors` has required `vehicle_type,pollutants`, optional `model_year,season,road_type`, and no `model_year` default.
- `core/contracts/clarification_contract.py:1235`: first AO turn enters collection mode when an optional slot without default is unfilled.
- `core/contracts/clarification_contract.py:365`: when collection mode is true, the contract probes the optional slot instead of proceeding.
- `core/governed_router.py:117`: direct execution could default factor `model_year` only after the contract has allowed execution.

### 2.2 Task `e2e_heldout_param_002` (`parameter_ambiguous`)

#### 2.2.1 Task info

- `task_id`: `e2e_heldout_param_002`
- `category`: `parameter_ambiguous`
- `user_message_type`: `alias_resolution_vehicle_road_pollutant_season`
- `expected_tool_chain`: `["query_emission_factors"]`
- `expected_params`: `vehicle_type=Light Commercial Truck`, `pollutants=["PM2.5"]`, `season=秋季`, `road_type=次干道`

#### 2.2.2 A group behavior

- Classifier turn-by-turn sequence: none emitted in A log.
- Actual tool chain: `["query_emission_factors"]`
- Actual params, merged across calls: `vehicle_type=轻型商用车`, `pollutants=["PM2.5"]`, `model_year=2020`, `season=秋季`, `road_type=地面道路`, `return_curve=true`
- Evaluator params comparison: pass. `vehicle_type` alias was accepted, and `road_type` was accepted through evaluator result-text fallback as `matched_in_tool_result`.
- Response summary: returned PM2.5 emission-factor data for light commercial truck with data payload.
- Success criteria met from `actual.criteria`: `tool_executed=true`, `params_legal=true`, `result_has_data=true`.

#### 2.2.3 E group behavior

- Classifier turn-by-turn sequence:
  - eval turn 1: `NEW_AO`, `rule_layer1`, signal `first_message_in_session`, confidence `1.0`
- Clarification telemetry:
  - eval turn 1:
    - `resolution_confidence`: not emitted in this Wave 1 E log
    - `resolution_evidence`: not emitted
    - `resolved_by`: not emitted
    - `tool_intent_resolved_by`: `llm_slot_filler`
    - `tool_intent_confidence`: `high`
    - `stance_value`: `directive`
    - `stance_confidence`: `low`
    - `stance_resolved_by`: `llm_slot_filler`
    - `final_decision`: `clarify`
    - `proceed_mode`: null
    - `collection_mode`: `true`
    - `stage1_filled_slots`: `vehicle_type`, `pollutants`, `season`, `road_type`
    - `stage2_missing_required`: `[]`
    - `stage3_rejected_slots`: `[]`
    - `stage3_normalizations`: included alias normalization for `vehicle_type`, exact pollutant/season, and road alias to `次干道`
    - `probe_optional_slot`: `model_year`
    - `probe_turn_count`: `1`
- Actual tool chain: `[]`
- Actual params vs expected field-level diff:
  - `vehicle_type`: expected `Light Commercial Truck`; actual missing
  - `pollutants`: expected `["PM2.5"]`; actual missing
  - `season`: expected `秋季`; actual missing
  - `road_type`: expected `次干道`; actual missing
- Failed success criteria: `tool_executed`, `params_legal`, `result_has_data`
- `execution_error`: none

#### 2.2.4 Attribution

**错误 clarify**. Alias/slot resolution succeeded for all expected fields, but the contract still short-circuited to a `model_year` optional probe. This is not an evaluator strictness problem: A passed under the evaluator's actual `criteria` and alias/result-text tolerance.

Relevant code locations:

- `core/contracts/clarification_contract.py:335`: required slots are recomputed after Stage 3 and were empty here.
- `core/contracts/clarification_contract.py:336`: optional slots without defaults are computed separately.
- `core/contracts/clarification_contract.py:368`: optional slot probing runs under collection mode even when required slots are complete.
- `evaluation/eval_end2end.py:734`: evaluator can accept expected params from tool result text, explaining A's `road_type=matched_in_tool_result` pass.

### 2.3 Task `e2e_heldout_codeswitch_005` (`code_switch_typo`)

#### 2.3.1 Task info

- `task_id`: `e2e_heldout_codeswitch_005`
- `category`: `code_switch_typo`
- `user_message_type`: `code_switch_typo_vehicle_pollutant_year`
- `expected_tool_chain`: `["query_emission_factors"]`
- `expected_params`: `vehicle_type=Transit Bus`, `pollutants=["THC"]`, `model_year=2020`

#### 2.3.2 A group behavior

- Classifier turn-by-turn sequence: none emitted in A log.
- Actual tool chain: `["query_emission_factors"]`
- Actual params, merged across calls: `vehicle_type=Transit Bus`, `pollutants=["THC"]`, `model_year=2020`
- Evaluator params comparison: pass, exact for all expected fields.
- Response summary: returned THC emission-factor data for transit bus with 73 speed points.
- Success criteria met from `actual.criteria`: `tool_executed=true`, `params_legal=true`, `result_has_data=true`.

#### 2.3.3 E group behavior

- Classifier turn-by-turn sequence:
  - eval turn 1: `NEW_AO`, `rule_layer1`, signal `first_message_in_session`, confidence `1.0`
- Clarification telemetry:
  - eval turn 1:
    - `resolution_confidence`: not emitted in this Wave 1 E log
    - `resolution_evidence`: not emitted
    - `resolved_by`: not emitted
    - `tool_intent_resolved_by`: `llm_slot_filler`
    - `tool_intent_confidence`: `high`
    - `stance_value`: `directive`
    - `stance_confidence`: `low`
    - `stance_resolved_by`: `llm_slot_filler`
    - `final_decision`: `clarify`
    - `proceed_mode`: null
    - `collection_mode`: `true`
    - `stage1_filled_slots`: `vehicle_type`, `pollutants`, `model_year`
    - `stage2_missing_required`: `[]`
    - `stage3_rejected_slots`: `pollutants`, `pollutant`
    - `stage3_normalizations`: typo/fuzzy vehicle normalized to `Transit Bus`; `model_year` normalized to `2020`; pollutant was not retained
    - `probe_optional_slot`: null
    - `probe_turn_count`: `0`
- Actual tool chain: `[]`
- Actual params vs expected field-level diff:
  - `vehicle_type`: expected `Transit Bus`; actual missing
  - `pollutants`: expected `["THC"]`; evaluator marked `matched_in_tool_result`, but no tool call exists, so this is response-text tolerance rather than actual execution
  - `model_year`: expected `2020`; actual missing
- Failed success criteria: `tool_executed`, `params_legal`, `result_has_data`
- `execution_error`: none

#### 2.3.4 Attribution

**错误 clarify via Stage 3 normalization rejection**. The LLM slot filler identified the required slots, including `pollutants`, but Stage 3 rejected both `pollutants` and singular `pollutant`; the contract treats any `rejected_slots` as clarification-blocking.

Relevant code locations:

- `core/contracts/clarification_contract.py:326`: Stage 3 standardization runs after slot filling.
- `core/contracts/clarification_contract.py:355`: any missing or rejected slot forces `clarify`.
- `core/contracts/clarification_contract.py:941`: failed slot standardization marks the slot as `rejected` and clears its value.
- `core/contracts/clarification_contract.py:957`: `pollutants` maps to `pollutant_list`, while singular `pollutant` maps to `pollutant`; this makes code-switch pollutant normalization sensitive to list/scalar handling.

## 3. Failure Shape Summary (all 75 E tasks)

Task-level metrics below use the last telemetry turn when the metric is naturally final-state (`final_decision`, `stance_value`) and any telemetry turn for event-like metrics (`proceed_mode=fallback`, `stance_reversal_detected`). `resolution_confidence`, `resolution_evidence`, and literal `resolved_by` are not emitted by these Wave 1 E logs; the available resolver field is `tool_intent_resolved_by`.

| Metric | Count | Share |
|---|---:|---:|
| No `clarification_telemetry` task (contract not triggered) | 5 | 6.7% |
| `resolution_confidence=none` task | 0 exact; field absent on 70 telemetry-bearing tasks | 0.0% exact |
| `resolution_confidence=low` task | 0 exact; field absent on 70 telemetry-bearing tasks | 0.0% exact |
| `proceed_mode=fallback` | 9 | 12.0% |
| Last `final_decision=clarify` but expected tool chain non-empty | 40 | 53.3% |
| Literal `resolved_by=llm_slot_filler` | 0 exact; field absent on 70 telemetry-bearing tasks | 0.0% exact |
| Available proxy: `tool_intent_resolved_by=llm_slot_filler` | 34 | 45.3% |
| Last `stance_value=deliberative` | 9 | 12.0% |
| Last `stance_value=directive` | 61 | 81.3% |
| `stance_reversal_detected=true` | 3 | 4.0% |

Additional failure rates:

- `tool_intent_resolved_by=llm_slot_filler`: 34 tasks; 30 failed; failure rate 88.2%.
- Last `final_decision=clarify` with expected non-empty tool chain: 40 tasks; 40 failed; failure rate 100.0%.
- `proceed_mode=fallback`: 9 tasks; 5 failed; failure rate 55.6%.

Category shape:

| Category | N | E success | Last clarify | Failed with empty tool chain | Any `tool_intent_resolved_by=llm_slot_filler` | Last deliberative | Last directive |
|---|---:|---:|---:|---:|---:|---:|---:|
| `simple` | 12 | 0 | 11 | 11 | 4 | 0 | 12 |
| `parameter_ambiguous` | 7 | 0 | 7 | 7 | 6 | 0 | 7 |
| `code_switch_typo` | 8 | 0 | 8 | 8 | 5 | 1 | 7 |
| `multi_step` | 8 | 0 | 0 | 0 | 0 | 0 | 8 |
| `constraint_violation` | 7 | 1 | 3 | 3 | 1 | 0 | 7 |
| `multi_turn_clarification` | 10 | 4 | 1 | 3 | 6 | 4 | 6 |
| `user_revision` | 8 | 4 | 2 | 4 | 3 | 3 | 4 |
| `ambiguous_colloquial` | 10 | 0 | 10 | 10 | 9 | 0 | 10 |
| `incomplete` | 5 | 5 | 1 | 0 | 0 | 1 | 0 |

E failed-task primary `failure_shape` distribution, denominator 61 failed tasks:

| Failure shape | Count | Share of failed | Share of all 75 |
|---|---:|---:|---:|
| Tool chain empty | 46 | 75.4% | 61.3% |
| Tool chain mismatch | 7 | 11.5% | 9.3% |
| Other | 5 | 8.2% | 6.7% |
| `params_legal=false` | 2 | 3.3% | 2.7% |
| `result_has_data=false` | 1 | 1.6% | 1.3% |

Interpretation: the dominant E regression is not wrong argument execution. It is pre-execution short-circuiting into clarification, especially for tasks where A executes directly and the evaluator confirms data was returned.

## 4. Held-out Self-Check

The self-check used evaluator actuals from A logs, not a manual strict comparison. Literal expected-vs-actual differences that the evaluator accepted through alias, case normalization, or result-text fallback are not counted as held-out defects.

| A success task | Category | Tool-chain evaluator result | Params evaluator result | Fallback / special pass? | Finding |
|---|---|---|---|---|---|
| `e2e_heldout_simple_003` | `simple` | pass | pass | no geometry gate; alias/fuzzy vehicle accepted | Held-out expectation is plausible. |
| `e2e_heldout_param_002` | `parameter_ambiguous` | pass | pass | result-text fallback accepted `road_type` | Evaluator tolerance worked as designed. |
| `e2e_heldout_codeswitch_005` | `code_switch_typo` | pass | pass | none | Held-out expectation is plausible. |
| `e2e_heldout_clarification_005` | `multi_turn_clarification` | pass | pass | no geometry gate | A can satisfy multi-turn fill with expected params. |
| `e2e_heldout_constraint_001` | `constraint_violation` | pass for empty expected chain | expected param comparison false, but success criteria require `tool_executed=false`, `constraint_blocked=true`, `result_has_data=false` | constraint-block path, not fallback | This is a valid negative/blocked expectation, not a parameter-label bug. |

I found no systematic held-out labeling issue in these A-success checks. The held-out set uses fields such as `season`, `road_type`, and `model_year`, but A succeeds under the evaluator's actual criteria on representative tasks containing those fields. The one visible tension is not in held-out labels: source config disagrees on `model_year`. `config/tool_contracts.yaml:44` marks `model_year` required for `query_emission_factors`, while `config/unified_mappings.yaml:560` treats it as optional and no-default. The E contract follows the latter shape and over-probes.

## 5. Root Cause Hypotheses

1. **Highest likelihood: optional `model_year` probing blocks directive first-turn factor queries.**
   - Evidence: `simple_003` and `param_002` had all expected slots filled, `stage2_missing_required=[]`, `stance_value=directive`, but E returned `final_decision=clarify`, `collection_mode=true`, `probe_optional_slot=model_year`.
   - Code evidence: `core/contracts/clarification_contract.py:1235` returns collection mode for first AO turns with unfilled optionals; `core/contracts/clarification_contract.py:365` probes instead of proceeding; `core/governed_router.py:117` can only default `model_year` if execution is reached.
   - Validation/false test: count all failed factor-query tasks with last `final_decision=clarify`, empty `stage2_missing_required`, no rejected slots, `probe_optional_slot=model_year`, and expected tool chain non-empty. This should explain much of `simple`, `parameter_ambiguous`, `ambiguous_colloquial`, and part of `code_switch_typo`.
   - Minimal fix path: for directive `query_emission_factors` first-turn tasks, either treat `model_year` as runtime-defaultable in the clarification contract or allow immediate `snapshot_direct`/context injection when required slots are complete and only `model_year` is missing.

2. **High likelihood: Stage 3 pollutant standardization rejects valid code-switch or typo pollutant slots.**
   - Evidence: `codeswitch_005` had `stage1_filled_slots` including `pollutants`, but `stage3_rejected_slots=["pollutants","pollutant"]`, forcing `final_decision=clarify` and empty tool chain.
   - Code evidence: `core/contracts/clarification_contract.py:941` clears rejected slots; `core/contracts/clarification_contract.py:355` makes rejected slots clarification-blocking.
   - Validation/false test: enumerate E failed code-switch tasks with `stage3_rejected_slots` containing `pollutants` or `pollutant`. If these align with A-pass/E-fail code-switch cases, this is a specific normalizer regression.
   - Minimal fix path: normalize pollutant list/scalar candidates consistently before Stage 3 rejection, especially for code-switch spellings and aliases already identified by the LLM slot filler.

3. **Medium likelihood: stance resolver is not the primary cause of the 0% categories, but it is under-detecting deliberative multi-turn tasks.**
   - Evidence: all 12 `simple` tasks end with directive stance, so simple collapse is not deliberative-over-clarification. However, `multi_turn_clarification` ends deliberative in only 4/10 tasks, below the expected >=70%, and several revision tasks show `user_reversal`/fallback behavior.
   - Code evidence: stance is recorded in `core/contracts/clarification_contract.py` telemetry, but final proceed/clarify is dominated by missing/rejected/collection-mode logic at `core/contracts/clarification_contract.py:355-386`.
   - Validation/false test: compare success of multi-turn tasks by final stance. If directive-final multi-turn tasks fail more often or proceed too early, stance contributes there, but it does not explain `simple`/`parameter_ambiguous` 0%.
   - Minimal fix path: keep stance fixes separate from factor-query collection-mode fixes; do not tune stance first as the primary E-collapse repair.

## 6. Next Step Recommendation

Do not continue Wave 2 for E as-is. The dominant held-out E failure is in the Wave 1 clarification contract path, and it affects broad categories before tool execution. Running Wave 2 before fixing this would mostly measure the same contract regression.

Recommended sequence:

1. Fix the `query_emission_factors` directive path so complete required slots plus only missing `model_year` can proceed with the configured runtime default.
2. Add a focused regression check for code-switch pollutant normalization where `stage1_filled_slots` contains `pollutants` but Stage 3 would reject `pollutants`/`pollutant`.
3. Re-run only the existing Wave 1 held-out E evaluation after the fix, then decide whether Wave 2 should proceed.
4. Investigate stance separately for `multi_turn_clarification`; it is a real anomaly, but it is not the main cause of the `simple`, `parameter_ambiguous`, and `code_switch_typo` collapses.
