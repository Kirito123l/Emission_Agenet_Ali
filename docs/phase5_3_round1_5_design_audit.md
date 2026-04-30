# Phase 5.3 Round 1.5 Design Audit

Date: 2026-04-30

Scope: design-level audit only. No code fixes, no data runs, no commit.

Evidence baseline:

- Round 1.4 `governance_full` 30-task n=3: `multi_turn_clarification` = 0/4 in all 3 reps.
- Round 1.4 `ao_only` 30-task n=3: `multi_turn_clarification` = 2/4 in all 3 reps.
- Trace source for detailed task audit:
  - `evaluation/results/phase5_3/round1_4_sanity/governance_full/rep_1/end2end_logs.jsonl`
  - `evaluation/results/phase5_3/round1_4_sanity/ao_only/rep_1/end2end_logs.jsonl`

## 1. Required Reading Summary

1. `docs/phase3_case_driven_design.md` §7 intended ClarificationContract/decision-field governance to let the LLM own conversational pragmatics while deterministic governance owns domain facts, with only the F1 0.5 safety net and no extra confidence threshold.
2. `docs/phase4_pcm_redesign.md` intended PCM to become advisory context for Stage 2 instead of a hard blocker, so missing optional/default/probe signals inform the LLM but do not decide execution.
3. `core/contracts/clarification_contract.py` intends to build a YAML-backed parameter snapshot, enrich it through Stage 2 LLM, standardize/default slots, persist multi-turn state, and either inject executable snapshot metadata or return a structured clarification.
4. `core/ao_classifier.py` plus `core/contracts/oasc_contract.py` intend to classify each user turn as continuation/revision/new AO, maintain AO state, and refresh chain continuation state after successful tool execution.
5. `core/contracts/execution_readiness_contract.py` intends the split-contract path to gate or proceed based on stance, required slots, optional-slot advisory, and execution continuation state, while preserving chain/parameter continuation across turns.

## 2. Four-Task Design Audit

### 2.1 Task 105: Governance-Only Fail, `ao_only` Pass

Task: `e2e_clarification_105`

Expected chain: `calculate_macro_emission`

Expected params: `pollutants=["CO2"]`, `season="夏季"`

Observed behavior:

- `governance_full`: fail in final turn 3; observed chain becomes repeated `calculate_macro_emission` calls instead of one expected call.
- `ao_only`: passes in all 3 reps; it executes `calculate_macro_emission` once and does not count follow-up replies as additional tool calls.
- Governance trace:
  - turn 1 Stage 2 asks for vehicle type, pollutant, model year.
  - turn 2 Stage 2 raw response says missing `vehicle_type` and `road_type`, and `decision=clarify`.
  - turn 3 Stage 2 finally says `decision=proceed` for `pollutants=CO2`, `season=夏季`.

Design questions:

1. Stage 2 raw `required_slots` comes from the LLM prompt payload, not from an independent hardcoded list inside Stage 2. The payload is assembled in `core/contracts/clarification_contract.py` and includes `tool_slots.required_slots`, `tool_slots.optional_slots`, `defaults`, `runtime_defaults`, `legal_values`, and the existing snapshot.
2. The authoritative source for tool required slots is `config/tool_contracts.yaml` through the tool contract registry. `calculate_macro_emission` has `required_slots: [pollutants]`, `optional_slots: [season, scenario_label]`, and `defaults: {season: "夏季"}`. It does not contain `vehicle_type` or `road_type`.
3. Multi-turn slot persistence is designed, not absent: `_initial_snapshot()` reads pending AO metadata / parent parameters, `_merge_stage2_snapshot()` merges Stage 2 slots into the snapshot, and `_persist_snapshot_state()` writes the snapshot back to AO metadata and first-class parameter state.

Design intent vs actual behavior:

- Design intent: Stage 2 should use the YAML-backed `tool_slots` and existing snapshot; governance should persist slots across turns; PCM/advisory should not invent hard requirements.
- Actual behavior: Stage 2 hallucinated `vehicle_type` and `road_type` as required for a macro file task, even though the YAML contract does not require them. The raw LLM decision was then still available to the decision-field consumer, while the post-Stage-3 authoritative YAML check saw no such required slots.

Classification:

- Primary: Class A, ClarificationContract implementation bug.
- Secondary: Class B, ClarificationContract design gap.

Reasoning:

- The implementation already has the correct design inputs: `tool_slots.required_slots` from YAML and persisted `existing_parameter_snapshot`.
- The bug is that `decision=clarify` is consumed from raw Stage 2 output without validating whether the requested missing slots are legal required slots for the active tool. `validate_decision()` only checks schema/confidence/proceed-with-missing/clarify-question/deliberate-reason; it does not reject invented clarification slots.
- The design gap is narrower: Phase 3 did not explicitly define a validator rule for `decision=clarify` such as "clarify pending slots must be in the active tool's required/follow-up slots or in a governance-produced pending list." That omitted guard lets LLM prompt drift become user-visible.

Repair estimate:

- Low/medium risk, 40-80 LOC.
- Add a decision reconciliation layer after Stage 2/Stage 3:
  - reject or downgrade Stage 2 `clarify` if `missing_required` is not a subset of active required/follow-up slots;
  - when YAML/post-Stage-3 says no required slots are missing, prefer reconciled `proceed` over raw LLM `clarify`;
  - record telemetry as `stage2_decision_raw` plus `reconciled_decision`.

### 2.2 Task 120: Governance-Only Fail, `ao_only` Pass

Task: `e2e_clarification_120`

Expected chain: `calculate_macro_emission -> calculate_dispersion`

Expected params: `pollutants=["NOx"]`, `meteorology="windy_neutral"`

Observed behavior:

- `governance_full`: fails in final turn 3; it repeatedly executes `calculate_macro_emission` and never returns to `calculate_dispersion`.
- `ao_only`: passes in all 3 reps with chain `calculate_macro_emission -> calculate_dispersion`.
- Governance trace:
  - turn 1 Stage 2 correctly identifies `tool=calculate_dispersion`, `chain=["calculate_macro_emission", "calculate_dispersion"]`, and `decision=clarify` because `available_results.emission=false`.
  - telemetry `final_decision` still shows `proceed`, because the contract-level `should_proceed` path is based on required slots / collection mode, not on the consumed decision-field result.
  - turn 2 and turn 3 resolve only `calculate_macro_emission`; the dependency chain from turn 1 is not persisted as "after macro, run dispersion."

Design questions:

1. Stage 2 raw to final decision is split across two places:
   - `ClarificationContract.before_turn()` records `telemetry.stage2_decision`, then independently computes `should_proceed` from YAML required slots, Stage 3, and PCM collection state.
   - `GovernedRouter._consume_decision_field()` later consumes raw `stage2_decision` and returns clarify/deliberate responses or falls through on proceed.
2. Raw `clarify` can appear with contract `final_decision=proceed` because `final_decision` records ClarificationContract's hardcoded route, not the router's actual decision-field consumption. This is a telemetry/state-machine mismatch.
3. Cross-tool dependency handoff is intended to be expressed through Stage 2 `intent.chain`, `tool_graph`, `available_results`, and split execution continuation. In practice, `OASCContract._refresh_split_execution_continuation()` refreshes chain continuation only after successful tool execution, based on `tool_intent.projected_chain`.
4. "Need emission before dispersion" is represented in `config/tool_contracts.yaml` under `calculate_dispersion.dependencies.requires: [emission]`, and is injected into Stage 2 as `tool_graph` plus `available_results`.

Design intent vs actual behavior:

- Design intent: Stage 2 can plan dependency chains using `tool_graph`; continuation state should carry remaining chain steps; readiness should avoid asking for unnecessary information when a dependency can be satisfied by a prior tool.
- Actual behavior: a dependency chain discovered in a clarifying turn is not persisted as an execution plan. After the user agrees to run macro first, the active tool intent collapses to `calculate_macro_emission`, and no component restores the pending `calculate_dispersion` step.

Classification:

- Primary: Class E, cross-component Contract + AO + ReadinessGating coordination problem.
- Secondary: Class A, implementation bug in decision/final telemetry reconciliation.

Reasoning:

- The chain exists in Stage 2 raw output, so the design knows the desired plan.
- No single component owns "persist dependency plan from a clarify turn and resume it after upstream tool success." ClarificationContract sees the chain, GovernedRouter can execute one snapshot tool, OASC can advance an existing chain after success, and Readiness can hold continuation state; none of them bridges the clarify-to-upstream-to-downstream transition.

Repair estimate:

- Medium/high risk, 120-220 LOC if fixed properly.
- Persist Stage 2 `intent.chain` into AO `tool_intent.projected_chain` even when the current turn returns a clarification response.
- When a later turn executes the first tool in that chain, initialize/advance `ExecutionContinuation` to the next tool.
- Ensure snapshot direct execution either honors `projected_chain` or explicitly delegates multi-tool chains to the inner router's normal planner.
- Add regression tests for `dispersion requires emission` multi-turn handoff.

### 2.3 Task 110: Governance and AO Both Fail, Different Failure Shapes

Task: `e2e_clarification_110`

Expected chain: `query_emission_factors`

Expected params: `vehicle_type="Refuse Truck"`, `pollutants=["PM10"]`, `model_year="2020"`

Observed behavior:

- `governance_full`: fails in final turn 4 with zero tool calls.
- `ao_only`: fails in all 3 reps, but it does execute `query_emission_factors` repeatedly; failure is chain mismatch from duplicate tool calls.
- Governance trace:
  - turn 1 generic clarify is reasonable because "需要一个排放查询" is underspecified.
  - turn 2 asks for pollutant after "垃圾车", also reasonable.
  - turn 3 Stage 2 raw has complete slots and `decision=proceed`, but final state remains clarify/readiness pending.
  - turn 4 "2020年" is treated as a revision/new vague turn; accumulated `vehicle_type` and `pollutants` are no longer available, so the system asks the generic analysis question again.
- `ao_only` trace:
  - no ClarificationContract telemetry.
  - each follow-up is classified around the completed AO and can trigger another `query_emission_factors` call.

Design questions:

Governance side:

1. Stage 2 raw vs final mismatch is in the split contract/readiness path: telemetry can show `stage2_decision=proceed`, while `execution_readiness.readiness_decision=clarify` and `final_decision=clarify`.
2. Cross-turn slot persistence exists in both ClarificationContract metadata and ExecutionReadiness split pending state, but it is scoped to the current AO. Once the AO classifier creates/revises a different AO, the new turn can lose the collected slot snapshot unless parent metadata is correctly inherited and interpreted.
3. Query factor contracts are asymmetric: `query_emission_factors.required_slots` are `vehicle_type` and `pollutants`; `model_year` is optional at `required_slots` level but appears as `required: true` under parameters and as `clarification_followup_slots: [model_year]`. This dual representation makes "ready to execute with default 2020" vs "still collecting model_year" ambiguous for readiness.

AO side:

1. AO classifier design says short slot-like replies are continuation only when there is an active/revising AO waiting for parameters.
2. After a tool execution completes the AO, later short replies like "垃圾车", "PM10", or "2020年" can be classified as revision rather than harmless confirmation.
3. There is no tool-call de-duplication layer that says "same tool + same canonical args already succeeded in this multi-turn exchange; do not append another tool call unless user requested recalculation."

Design intent vs actual behavior:

- Design intent: governance should collect missing slots, then proceed once required slots are filled or runtime defaults are acceptable; AO should distinguish continuation from revision; duplicate follow-ups should not corrupt the tool chain.
- Actual behavior: readiness can override or contradict a Stage 2 proceed in a way that keeps the user in clarification; AO classification then changes scope and loses accumulated slots; without governance, duplicate execution still fails the evaluator.

Classification:

- Governance side: Class A implementation bug plus Class E cross-component coordination issue.
- AO side: Class D AO classifier design gap.

Reasoning:

- The Stage 2 raw proceed is clear evidence that the LLM decision path had enough information at turn 3. The final clarify points to a state-machine implementation bug or unresolved conflict between readiness and decision-field consumption.
- The `ao_only` duplicate calls are not a governance bug. They expose an AO design gap: completed-AO short follow-ups are over-eagerly treated as revisions, and the system lacks semantic idempotency for already satisfied objectives.

Repair estimate:

- Governance: medium risk, 80-160 LOC.
  - Normalize `query_emission_factors` readiness around required slots vs follow-up slots vs runtime defaults.
  - Reconcile Stage 2 proceed with readiness advisory before returning clarify.
  - Preserve slot snapshot when transitioning from parameter collection to execution.
- AO: medium/high risk, 100-200 LOC.
  - Add duplicate/intended-confirmation detection for short slot-like messages after a just-completed AO.
  - Add idempotency guard for repeated identical canonical tool calls inside the same multi-turn task.

### 2.4 Task 119: Governance and AO Both Fail, Similar Repetition Pattern

Task: `e2e_clarification_119`

Expected chain: `calculate_macro_emission -> render_spatial_map`

Expected params: `pollutants=["CO2"]`

Observed behavior:

- `governance_full`: fails in all 3 reps with extra `render_spatial_map` / repeated chain calls.
- `ao_only`: fails in all 3 reps with the same core problem: repeated macro/map or repeated map after the expected chain is already satisfied.
- Governance trace:
  - turn 1 may over-clarify for vehicle/pollutant despite a file task.
  - turn 2 proceeds and runs analysis/map.
  - turn 3 "出地图" is classified as revision/re-render and adds another map call.
- `ao_only` trace:
  - first turn can execute `calculate_macro_emission -> render_spatial_map`.
  - follow-up "CO2" repeats macro/map.
  - follow-up "出地图" repeats map.

Design questions:

1. AO classifier distinguishes follow-up vs revision primarily through active AO state, short clarification replies, explicit revision phrases, and an LLM prompt. Its prompt explicitly says "把刚才结果画图" is `NEW_AO` that may reference the previous AO, not continuation.
2. `continuation_state` is designed to track a projected chain and advance it after successful tool execution. Once the chain is complete, it clears. It does not represent "expected benchmark follow-up already satisfied; treat the next short message as confirmation or no-op unless it asks for a new artifact."
3. Tool-call history is stored in AO memory, but execution selection does not use it as an idempotency guard before appending another identical tool call.

Design intent vs actual behavior:

- Design intent: if a chain has remaining tools, continuation state should carry the next tool; after completion, a new message may be a new AO or revision.
- Actual behavior: benchmark-style multi-turn clarification uses follow-up messages as slot fills for one task, but the AO design often treats post-completion follow-ups as new revision/re-render requests. The evaluator then accumulates duplicate tool calls and marks the chain mismatched.

Classification:

- Primary: Class D AO classifier design gap.
- Secondary: Class E cross-component coordination issue.
- Tertiary: Class A/B for governance over-clarification on turn 1, but not the dominant failure because `ao_only` also fails.

Reasoning:

- This failure exists without ClarificationContract. The common failure surface is AO multi-turn semantics plus lack of duplicate-call suppression.
- The current design assumes "after completion, a follow-up is likely a revision/new AO" more often than "the follow-up belongs to the same benchmark clarification exchange."

Repair estimate:

- Medium/high risk, 120-240 LOC.
- Add a completed-AO follow-up policy:
  - if the last AO completed in the current bounded exchange and the new message only restates an already used slot/artifact request, do not re-run the same chain;
  - if the message requests a missing downstream artifact, run only the missing downstream tool;
  - if it changes a canonical parameter, classify as revision.
- Add tests for 119-like "CO2" then "出地图" after macro/map completion.

## 3. Defect Classification

### Class A: ClarificationContract / Readiness Implementation Bugs

Evidence:

- Task 105: Stage 2 raw invented required slots (`vehicle_type`, `road_type`) for `calculate_macro_emission`, but the YAML contract only requires `pollutants`.
- Task 110: Stage 2 raw `decision=proceed` with complete query-factor slots, but final readiness state remains clarify and no tool executes.
- Task 120: Stage 2 raw `decision=clarify` but telemetry final says proceed; actual router response follows decision-field clarify. This is not behaviorally fatal alone, but it makes state/trace interpretation inconsistent.

Root issue:

- The raw Stage 2 decision, post-Stage-3 YAML snapshot, readiness decision, and router-consumed decision are not reconciled into a single authoritative decision object.

### Class B: ClarificationContract Design Gaps

Evidence:

- The design did not explicitly require validation that `decision=clarify` pending slots must be valid for the active tool contract.
- Stage 2 is prompted with `tool_slots`, but there is no design-level invariant that prevents LLM hallucinated required slots from reaching the decision consumer.

Root issue:

- Phase 3 decision validation focused on F1 safety and schema validity, not contract-grounding of clarify decisions.

### Class C: AO Classifier Implementation Bugs

Evidence:

- No clear single-line implementation defect was proven in Round 1.5.
- The AO classifier mostly behaves according to its current prompt and rules: short replies are continuation only when an active/revising AO is waiting; completed-AO follow-ups can become revisions.

Root issue:

- None assigned as primary. Current evidence supports design gap more than implementation bug.

### Class D: AO Classifier Design Gaps

Evidence:

- Task 119 fails in both `governance_full` and `ao_only` through repeated macro/map or map-only calls.
- Task 110 in `ao_only` executes `query_emission_factors` repeatedly after short follow-ups.

Root issue:

- The AO design lacks a "same clarification exchange / already satisfied objective" state. It distinguishes continuation/revision/new AO, but not idempotent confirmation vs duplicate replay after completion.

### Class E: Cross-Component Coordination Problems

Evidence:

- Task 120: Stage 2 discovers dependency chain `macro -> dispersion`, but no component persists that chain through a clarification response and resumes it after macro succeeds.
- Task 110: slot persistence, readiness, AO scope transitions, and runtime defaults disagree on whether the query is ready.
- Task 119: continuation state can advance chain execution, but after completion it does not prevent benchmark follow-ups from re-triggering satisfied tools.

Root issue:

- The system has separate state machines for ClarificationContract, ExecutionReadiness, AO scope, execution continuation, and evaluator follow-ups. They do not share one canonical "multi-turn task state."

## 4. Repair Scope Estimate

| Class | Estimated LOC | Risk | Phase 5.3 fixable? | If not fixed |
|---|---:|---|---|---|
| A: Contract/readiness implementation bugs | 80-180 | Medium | Yes, recommended before 180-task main run | Governance ablation underreports value; multi-turn failures look worse than intended design |
| B: Contract clarify-grounding design gap | 40-100 | Low/Medium | Yes, if limited to validator/reconciliation | LLM can continue inventing non-contract required slots; paper must mark contract-grounding gap |
| C: AO implementation bug | 0 currently proven | N/A | No action until new evidence | No honest claim that there is a concrete AO bug yet |
| D: AO classifier design gap | 120-240 | Medium/High | Maybe, but only with narrow idempotency policy | Multi-turn production UX repeats expensive tools; benchmark chain mismatch persists in AO-only |
| E: Cross-component coordination | 150-300 | High | Partial only in Phase 5.3; full fix belongs in Phase 6 | Dependency-chain workflows like dispersion remain brittle; paper should mark multi-turn orchestration as residual limitation |

Production impact if not fixed:

- Contract bugs produce unnecessary clarification, missed execution, or misleading telemetry.
- AO design gaps can re-run expensive tools on short follow-ups, increasing cost and user confusion.
- Cross-component gaps matter most for chained analyses such as emission-to-dispersion and map rendering.

Paper impact if not fixed:

- The final benchmark can still be reported honestly, but `multi_turn_clarification` must be called out as a residual failure mode.
- The 3-way ablation should not claim governance improves multi-turn clarification unless Class A/B/E fixes are verified.
- Failure analysis should distinguish "domain tool capability" from "multi-turn orchestration state."

## 5. Recommended Repair Sequence

Recommended next rounds:

1. Round 2: Fix Class A/B narrow contract reconciliation.
   - Add decision reconciliation between Stage 2 raw output, YAML required slots, Stage 3 snapshot, and readiness final state.
   - Add validator coverage for hallucinated clarify slots and raw-proceed/final-clarify mismatch.
   - Verify with 30-task n=3 on `governance_full` and `ao_only`, focusing on tasks 105 and 110.

2. Round 3: Fix a narrow slice of Class E for dependency handoff.
   - Persist Stage 2 `intent.chain` from clarification turns.
   - Resume pending downstream tool after upstream tool success for `macro -> dispersion`.
   - Verify task 120 specifically plus 30-task n=3.

3. Round 4: Decide whether to address Class D in Phase 5.3 or defer to Phase 6.
   - If Phase 5.3: implement a narrow idempotency/no-op guard for duplicate same-tool same-args follow-ups after completed AO.
   - If deferred: document 119/110 AO-only duplicate execution as an honest residual limitation.

4. Round 5: Re-run ablation sanity before main benchmark.
   - `naive`, `ao_only`, `governance_full` on 30-task n=3 or n=5.
   - Only proceed if the three modes are behaviorally separated and multi-turn changes do not regress other categories.

5. Round 6: Run 180-task x 3 cells x n=5 main benchmark.

6. Round 7: Run held-out and write Final.2 / Final.3.

Recommendation:

- Do not start the 180-task main run before at least Class A/B and the Task 120 Class E dependency handoff are either fixed or explicitly waived.
- Defer broad AO classifier redesign to Phase 6 unless Phase 5.3 has enough time for a narrow idempotency-only patch plus multi-rep regression validation.
