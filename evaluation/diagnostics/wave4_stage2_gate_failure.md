# Wave 4 Stage 2 Gate Failure Diagnosis

## 1. Scope

Wave 4 stopped at Stage 2 per protocol. No Stage 3 main smoke and no Stage 4 full runs were started.

This diagnosis uses:

- `evaluation/results/wave4_main_multiturn_smoke_E/`
- `evaluation/results/wave4_heldout_multistep_smoke_E/`
- `evaluation/diagnostics/wave3_stage2_multiturn_gate_failure.md`

## 2. Gate Results

| Gate | Required | Actual | Result |
|---|---:|---:|---|
| main `multi_turn_clarification` | `>= 40%` | `30.00%` (`6/20`) | fail |
| held-out `multi_step` | `>= 50%` | `37.50%` (`3/8`) | fail |

Run integrity stayed clean in both slices:

- `infra_unknown = 0`
- `data_integrity = clean`

## 3. What Improved

Wave 4 did recover part of the Wave 3 split-path regression on `multi_turn_clarification`.

| Run | multi_turn completion |
|---|---:|
| Wave 2 main full E | `10.00%` |
| Wave 3 Stage 2 smoke E | `5.00%` |
| Wave 4 Stage 2 smoke E | `30.00%` |

The telemetry shows the intended split-native binding now engages:

- `short_circuit_rate = 0.8243`
- `stage2_hit_rate = 0.9595`

This is materially different from Wave 3, where `short_circuit_intent=true` never fired. So the Wave 4 fixes were not inert. They were only incomplete.

## 4. Main Multi-turn Failure Shape

### 4.1 Parameter collection now binds, but it over-extends

Representative failures:

- `e2e_clarification_101`
- `e2e_clarification_110`

Observed clarification path:

1. `vehicle_type`
2. `pollutants`
3. `model_year`
4. `road_type`

No tool execution happens before the task times out from the evaluator's perspective.

This means Wave 4 fixed the Wave 3 drift problem, but overshot into a stronger clarify-first regime:

- `clarification_followup_slots` is now preserved
- `confirm_first_slots` is now consumed
- Stage 2 `needs_clarification=true` is now respected

For `query_emission_factors`, that combination creates an over-constrained sequence on some benchmark tasks. The system keeps asking for `model_year` and then `road_type` even when the benchmark expects execution earlier.

### 4.2 Repeated execution still exists on macro tasks

Representative failure:

- `e2e_clarification_104`

Observed path:

1. `calculate_macro_emission` clarifies `season`
2. second turn proceeds
3. later turn executes `calculate_macro_emission` again

So the multi-turn slice is no longer dominated by tool drift, but repeated execution on resumed AO flow still exists.

## 5. Held-out Multi-step Failure Shape

Held-out `multi_step` stayed at `3/8`, exactly the Wave 2 v5 level.

Failed tasks:

- `e2e_heldout_multistep_001`
- `e2e_heldout_multistep_002`
- `e2e_heldout_multistep_004`
- `e2e_heldout_multistep_006`
- `e2e_heldout_multistep_008`

Representative wrong-continuation patterns:

- `001`: `calculate_macro_emission -> render_spatial_map -> query_emission_factors`
- `002`: `query_emission_factors -> calculate_macro_emission`
- `004`: `calculate_macro_emission -> calculate_macro_emission -> render_spatial_map`
- `006`: `calculate_micro_emission` followed by repeated `calculate_dispersion`
- `008`: `calculate_macro_emission -> calculate_macro_emission`

Interpretation:

- The Wave 4 fixes were mostly about parameter collection and clarify-first semantics.
- They did not materially change the multi-step wrong-continuation family diagnosed in Wave 2.
- `projected_chain` preservation remains in place, but the held-out failures still show bad initial tool selection, repeated upstream execution, and broken downstream continuation.

## 6. Root Cause Update

Wave 4 partially fixed the Wave 3 diagnosis, but only half of the intended recovery landed:

1. **Fixed enough to measure**
   - `parameter_collection` now binds intent across short continuation turns
   - Stage 2 `needs_clarification` is no longer observational only

2. **New blocker exposed**
   - migrated `clarification_followup_slots` and `confirm_first_slots` now over-constrain some single-tool multi-turn tasks, especially `query_emission_factors`
   - default-filled `road_type` is treated as still needing confirmation, which is correct structurally, but too strict for the current benchmark slice

3. **Still unsolved**
   - held-out `multi_step` wrong-continuation is still the Wave 2 family, not the Wave 3 family
   - the current Wave 4 changes do not repair that slice

In one sentence:

> Wave 4 repaired split-path intent binding and clarify gating, but it did not calibrate follow-up / confirm-first obligations for evaluator-expected execution timing, and it did not move the held-out multi-step continuation bug.

## 7. Stop Point

Per protocol, rollout stops here.

Not run:

- Stage 3 main smoke
- Stage 4 main A/E full
- Stage 4 held-out A/E full

The next iteration should be narrower than Wave 4:

1. calibrate `clarification_followup_slots` / `confirm_first_slots` so they do not force four-step clarify loops on factor tasks,
2. separately target the held-out multi-step wrong-continuation family rather than assuming the multi-turn fix will also recover it.
