# Wave 2 Multi-turn Clarification Regression Deep Diagnosis

## 1. Scope

This is read-only diagnosis. No production code was changed and no new benchmark was run.

Logs read:

- Wave 1 E smoke: `evaluation/results/phase2r_wave1_smoke_E/end2end_logs.jsonl`
- PCM reference for `e2e_clarification_119`: `evaluation/results/phase2_pcm_clarification_E/end2end_logs.jsonl`
- Wave 2 before runtime-default invariant: `evaluation/results/wave2_main_smoke_E/end2end_logs.jsonl`
- Wave 2 after runtime-default invariant: `evaluation/results/wave2_main_smoke_postfix2_E/end2end_logs.jsonl`

The Wave 2 smoke contains four `multi_turn_clarification` tasks: `e2e_clarification_105`, `110`, `119`, and `120`.

- Wave 1 smoke pass -> Wave 2 fail: `105`, `110`.
- Regression exemplar requested by user: `119`; it is pass in the PCM reference and in pre-invariant Wave 2, but fail in postfix2.
- Control fail/fail: `120`.

## 2. Task A - Trace Comparison

### 2.1 `e2e_clarification_105`

Wave 1 smoke: pass.

| turn | decision | PCM / readiness | slot signal |
|---:|---|---|---|
| 1 | clarify | `collection_mode=true`, `probe_turn_count=0` | `stage2_missing_required=["pollutants"]`; stance `deliberative/high` |
| 2 | clarify | `collection_mode=true`, `probe_optional_slot=scenario_label`, `probe_turn_count=1` | `stage1_filled_slots=["pollutants"]` |
| 3 | proceed | `collection_mode=true`, `probe_optional_slot=scenario_label`, `probe_turn_count=2`, `proceed_mode=snapshot_direct` | `stage1_filled_slots=["season"]` |

Final Wave 1 chain: `["calculate_macro_emission"]`; success.

Wave 2 postfix2: fail.

| turn | decision | readiness | slot signal |
|---:|---|---|---|
| 1 | clarify | `branch=directive`, `pending_slot=pollutants` | `stage2_called=true`; Stage 2 asked for missing analysis params |
| 2 | proceed | `branch=directive` | `stage1_filled_slots=["pollutants"]` |
| 3 | clarify | `branch=directive`, `pending_slot=pollutants` | `stage1_filled_slots=["season"]`, `stage2_missing_required=["pollutants"]` |

Final Wave 2 chain: `["calculate_macro_emission", "calculate_macro_emission"]`; fail due incomplete output shape despite valid tool data.

Interpretation: Wave 1's PCM kept the task in a bounded collection state and stopped after probe-count exhaustion with one execution. Wave 2 has no collection state; it can re-enter the same required-slot clarification after already executing.

### 2.2 `e2e_clarification_110`

Wave 1 smoke: pass.

| turn | decision | PCM / readiness | slot signal |
|---:|---|---|---|
| 1 | clarify | `collection_mode=true`, `probe_turn_count=0` | Stage 2 generated broad factor-query clarification; stance `directive/medium` |
| 2 | clarify | `collection_mode=true` | `stage1_filled_slots=["vehicle_type"]`, `stage2_missing_required=["pollutants"]`; stance `deliberative/high` |
| 3 | clarify | `collection_mode=true`, `probe_optional_slot=model_year`, `probe_turn_count=1` | `stage1_filled_slots=["pollutants"]` |
| 4 | proceed | `collection_mode=true`, `proceed_mode=snapshot_direct` | `stage1_filled_slots=["model_year"]` |

Final Wave 1 chain: `["query_emission_factors"]`; success.

Wave 2 postfix2: fail.

| turn | decision | readiness | slot signal |
|---:|---|---|---|
| 1 | clarify | `branch=exploratory`, `pending_slot=scope` | Stage 2 intent says factor query and supplies a useful clarification question |
| 2 | clarify | `branch=exploratory`, `pending_slot=scope` | `stage1_filled_slots=["vehicle_type"]`, `stage2_missing_required=["pollutants"]` |
| 3 | clarify | `branch=exploratory`, `pending_slot=scope` | `stage1_filled_slots=["pollutants"]`, `stage2_missing_required=["vehicle_type"]` |
| 4 | clarify | `branch=exploratory`, `pending_slot=scope` | `stage1_filled_slots=["model_year"]`, `stage2_missing_required=["vehicle_type","pollutants"]` |

Final Wave 2 chain: `[]`; fail.

Interpretation: Wave 2's `exploratory` branch runs before required-slot clarification, so required-slot evidence is masked by repeated scope framing. Wave 1 did not let stance override missing required slots.

### 2.3 `e2e_clarification_119`

PCM reference: pass. Wave 1 smoke: fail. Wave 2 pre-invariant: pass. Wave 2 postfix2: fail.

PCM reference path:

| turn | decision | PCM / readiness | slot signal |
|---:|---|---|---|
| 1 | clarify | `collection_mode=true`, `probe_turn_count=0` | `stage2_missing_required=["pollutants"]` |
| 2 | clarify | `collection_mode=true`, `probe_optional_slot=scenario_label`, `probe_turn_count=1` | `stage1_filled_slots=["pollutants"]` |
| 3 | clarify | `collection_mode=true`, `probe_optional_slot=scenario_label` | `stage2_missing_required=["pollutants"]` on map turn |
| 4 | proceed | `collection_mode=true`, `probe_turn_count=2`, `proceed_mode=snapshot_direct` | no rejection |

Final PCM reference chain: `["calculate_macro_emission", "render_spatial_map"]`; success.

Wave 2 pre-invariant path:

| turn | decision | readiness | slot signal |
|---:|---|---|---|
| 1 | clarify | `branch=directive`, `pending_slot=pollutants` | Stage 2 returned `needs_clarification=true` and all relevant slots missing |
| 2 | proceed | `branch=directive` | `stage1_filled_slots=["pollutants"]` |
| 3 | proceed | `branch=directive`, `proceed_mode=fallback` | map continuation |

Final pre-invariant chain: `["calculate_macro_emission", "render_spatial_map"]`; success.

Wave 2 postfix2 path:

| turn | decision | readiness | slot signal |
|---:|---|---|---|
| 1 | proceed | `branch=directive`, no pending slot | Stage 2 raw response had `needs_clarification=true` and a clarification question, but also filled `pollutants=["CO2","NOx"]` with `source=default` |
| 2 | proceed | `branch=directive` | `stage1_filled_slots=["pollutants"]` |
| 3 | proceed | `branch=directive`, `proceed_mode=fallback` | map continuation |

Final postfix2 chain: `["calculate_macro_emission", "calculate_macro_emission", "render_spatial_map"]`; fail due extra macro execution/output shape.

Interpretation: Wave 2 split readiness ignores Stage 2 `needs_clarification` / `clarification_question` if required slots look filled after merging the LLM slot payload. PCM/pre-invariant success depended on a first-turn clarify gate before any macro execution.

### 2.4 `e2e_clarification_120` - Control Fail/Fail

Wave 1 smoke: fail.

| turn | decision | PCM / readiness | slot signal |
|---:|---|---|---|
| 1 | clarify | `collection_mode=true` | `stage2_missing_required=["pollutants"]` |
| 2 | clarify | `collection_mode=true`, `probe_optional_slot=scenario_label`, `probe_turn_count=1` | `stage1_filled_slots=["pollutants"]` |
| 3 | proceed | `collection_mode=true`, `probe_turn_count=2`, `proceed_mode=snapshot_direct` | `stage1_filled_slots=["meteorology","stability_class"]` |
| 4 | clarify | `collection_mode=true` | `stage2_missing_required=["pollutants"]` |

Final Wave 1 chain: `["calculate_macro_emission", "calculate_macro_emission"]`; fail because expected dispersion was not executed.

Wave 2 postfix2: fail.

| turn | decision | readiness | slot signal |
|---:|---|---|---|
| 1 | proceed | `branch=directive`, `proceed_mode=fallback` | no Stage 2 |
| 2 | proceed | `branch=directive`, `proceed_mode=fallback` | `stage1_filled_slots=["pollutants"]` |
| 3 | proceed | `branch=directive`, `proceed_mode=fallback` | `stage1_filled_slots=["meteorology","stability_class"]` |

Final Wave 2 chain: `["calculate_macro_emission", "calculate_macro_emission"]`; fail.

Interpretation: This task is not rescued by PCM either; it needs cross-tool continuation from macro emission to dispersion, not only clarification readiness.

## 3. Task B - Difference Localization

### 3.1 Wave 1 first-turn decision

For the successful Wave 1 smoke tasks:

- `105`: first turn `final_decision=clarify`.
- `110`: first turn `final_decision=clarify`.

For the PCM reference success:

- `119`: first turn `final_decision=clarify`.

So the mechanism behind the passing paths is a first-turn clarify gate, usually with `collection_mode=true`.

### 3.2 What caused Wave 1 clarify?

The legacy `ClarificationContract` decision path is:

- Stage 2 fills/asks about missing slots at `core/contracts/clarification_contract.py:284-323`.
- Stage 3 normalizes snapshot at `core/contracts/clarification_contract.py:326-333`.
- Missing required slots are computed at `core/contracts/clarification_contract.py:335`.
- PCM is resolved at `core/contracts/clarification_contract.py:340-346`.
- Required/rejected slots force `pending_decision="clarify_required"` at `core/contracts/clarification_contract.py:355-364`.
- If no missing required but collection mode is active, no-default optionals are probed at `core/contracts/clarification_contract.py:368-384`.
- Probe count exhaustion proceeds at `core/contracts/clarification_contract.py:373-386`.
- The state is persisted, including `collection_mode`, `pending_decision`, `probe_optional_slot`, and `probe_turn_count`, at `core/contracts/clarification_contract.py:388-404`.
- `not should_proceed` returns a clarification response at `core/contracts/clarification_contract.py:406-423`.

The PCM invariant itself is at `core/contracts/clarification_contract.py:1235-1254`:

- Fresh first AO turn + missing required -> collection mode.
- Fresh first AO turn + no-default optional missing -> collection mode.
- Resume turns keep current collection mode.

Important detail: Wave 1 did not rely only on stance. It persisted a parameter-collection state across turns. The telemetry for 105/110/119 shows `collection_mode=true` and then either repeated required-slot clarification or optional-slot probe before execution.

### 3.3 Wave 2 first-turn decision

Wave 2 postfix2:

- `105`: first turn `clarify`, but later re-enters required-slot clarification after executing once.
- `110`: first turn `clarify`, but via `readiness_branch=exploratory`, `pending_slot=scope`, not required-slot clarification.
- `119`: first turn `proceed`, because Stage 2 filled the required slot payload with default pollutants despite also returning `needs_clarification=true`.
- `120`: first turn `proceed`.

### 3.4 Why Wave 2 proceeds or loops differently

The split `ExecutionReadinessContract` logic differs in four ways:

1. It runs exploratory scope framing before required-slot clarification:
   - `core/contracts/execution_readiness_contract.py:75-95` happens before `missing_required` handling at `core/contracts/execution_readiness_contract.py:97-126`.
   - This explains `110`: required slots may be missing, but exploratory branch repeatedly emits scope questions.

2. It has no persisted PCM state:
   - Under split, telemetry has `execution_readiness`, not `collection_mode/probe_turn_count`.
   - There is no equivalent to legacy persistence at `core/contracts/clarification_contract.py:388-404`.
   - This explains why 105 can execute and then later ask for the same required slot again.

3. It ignores Stage 2 `needs_clarification` as a decision input:
   - It records `stage2_clarification_question`, but only uses it in `_build_question` when `missing_required or rejected_slots` is true.
   - It does not test the raw Stage 2 `needs_clarification` flag.
   - This explains 119 postfix2: raw Stage 2 asked for clarification, but slot merge made `missing_required=[]`, so execution proceeded.

4. It treats LLM default-filled required slots as filled:
   - For 119 postfix2, Stage 2 gave `pollutants=["CO2","NOx"]` with `source=default`.
   - After Stage 3, `missing_required=[]`, so the contract proceeded.
   - Wave 1/PCM passing paths depended on not executing before user supplied the pollutant.

## 4. Task C - Candidate Fix Paths

### Option 1 - Add a clarify-first readiness marker without restoring PCM

Change scope:

- `core/contracts/execution_readiness_contract.py:61-73`: after Stage 2 merge and Stage 3, inspect Stage 2 `needs_clarification` and slot sources.
- `core/contracts/split_contract_utils.py:88-99`: persist `stage2_needs_clarification` in telemetry metadata if not already present.

Behavior:

- If Stage 2 says `needs_clarification=true` and required slots are only filled by LLM `source=default` or weak inference, return clarify once.
- Do not introduce `collection_mode`, `probe_turn_count`, or PCM fields.

Impact:

- Mostly multi_turn_clarification and possibly ambiguous_colloquial.
- Could reduce premature execution where LLM invents/defaults required slots.
- Lower risk to simple/directive tasks if gated on Stage 2 `needs_clarification=true`.

Work estimate: small to medium, 1-2 commits plus targeted tests.

### Option 2 - Restore a split-native parameter collection state

Change scope:

- `core/contracts/execution_readiness_contract.py:95-180`: add `execution_readiness.pending` state transitions equivalent to required-slot clarify and optional probe.
- `core/ao_manager.py` lifecycle completion path: ensure split reads readiness metadata for pending collection.
- `core/analytical_objective.py` serialization: keep PCM fields excluded but allow `execution_readiness` metadata to persist.

Behavior:

- Recreate legitimate PCM behavior with new field names: `pending`, `pending_decision`, `pending_slot`, `probe_count`.
- Keep logs Wave 2-clean by using `execution_readiness`, not `collection_mode`.

Impact:

- Multi_turn_clarification most directly.
- Could affect incomplete/parameter_ambiguous because they also rely on clarification loops.
- Larger surface area and more lifecycle risk.

Work estimate: medium to large, 3-5 commits plus lifecycle tests.

### Option 3 - Reorder split readiness so required-slot clarification outranks stance branch

Change scope:

- `core/contracts/execution_readiness_contract.py:75-126`: move `missing_required or rejected_slots` handling before exploratory branch.
- `core/contracts/execution_readiness_contract.py:75-95`: only use exploratory scope framing when no required/rejected slot is pending.

Behavior:

- `exploratory` no longer masks required-slot questions.
- Does not solve 119's default-filled required-slot proceed by itself.

Impact:

- Directly targets `110`.
- May help held-out exploratory mistakes where required slots are available/missing.
- Low risk to simple/directive; moderate risk to true exploratory tasks that intentionally need scope framing.

Work estimate: small, 1 commit plus tests.

## 5. Task D - Paper Material

Yes, deleting Wave 1 PCM removed a legitimate invariant.

Precise invariant:

> Once a turn enters parameter-collection mode because user-visible execution readiness is incomplete, subsequent turns must preserve the pending parameter-collection objective until either the required slot is filled or the bounded optional-probe policy explicitly abandons probing; execution readiness is not recomputed from a fresh LLM-filled snapshot alone.

This invariant is legitimate because multi-turn clarification is not only slot completeness; it is a user-facing interaction contract. The system must remember that it owes the user a clarification/probe step before treating inferred/defaulted slots as permission to execute.

## 6. Stop Point

This report stops at diagnosis. No production code was changed and no new benchmark was run. The next decision is whether to restore a split-native version of the PCM invariant, implement a narrower clarify-first marker, or only reorder required-slot handling ahead of stance branching.
