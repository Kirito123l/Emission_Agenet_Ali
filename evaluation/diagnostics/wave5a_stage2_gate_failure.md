# Wave 5a Stage 2 Gate Failure Diagnosis

## 1. Scope

Wave 5a stopped at Stage 2 per protocol.

This round only implemented one calibration:

- enforce `probe_limit` for split-path optional-slot probing

It did **not** change:

- multi-step continuation
- projected-chain handling
- held-out wrong-continuation behavior

## 2. Gate Results

| Gate | Required | Actual | Result |
|---|---:|---:|---|
| main `multi_turn_clarification` | `>= 50%` | `35.00%` (`7/20`) | fail |
| held-out `multi_step` | `>= 50%` | `37.50%` (`3/8`) | fail |

Integrity stayed clean:

- `infra_unknown = 0`
- `data_integrity = clean`

## 3. What Improved

Main `multi_turn_clarification` improved, but only slightly:

| Run | completion |
|---|---:|
| Wave 4 Stage 2 | `30.00%` |
| Wave 5a Stage 2 | `35.00%` |

Task-level delta:

- new passes:
  - `e2e_clarification_108`
  - `e2e_clarification_109`
- regression:
  - `e2e_clarification_102`

So the probe-limit calibration was not inert. It just was not strong enough.

## 4. Why Main Multi-turn Still Failed

The dominant remaining pattern is still over-clarification on factor tasks.

Representative failures:

- `e2e_clarification_101`
- `e2e_clarification_107`

Observed final telemetry shape:

- last decision = `clarify`
- last pending slot = `road_type`
- `probe_count = 2`
- `force_proceed_reason = null`

This is the key point.

Wave 5a enforces:

```text
if probe_count >= probe_limit: force proceed
else: increment probe_count and clarify
```

With `probe_limit = 2`, the system still allows:

1. first optional probe
2. second optional probe

and only forces proceed on the **next** turn.

For the benchmark slice, that is still too late. The turn budget is exhausted while the agent is still asking the second optional question.

So the implementation is correct relative to the chosen invariant, but the chosen threshold semantics are still too permissive for this benchmark.

In short:

> Wave 5a fixed “optional probing is unbounded”, but not “optional probing fits inside the evaluator’s turn budget”.

## 5. Held-out Multi-step Result

Held-out `multi_step` stayed exactly at the Wave 4 level:

| Run | completion |
|---|---:|
| Wave 4 Stage 2 | `37.50%` |
| Wave 5a Stage 2 | `37.50%` |

This was expected from scope:

- Wave 5a explicitly did not touch multi-step continuation
- the remaining fails are still the Wave 2/Wave 4 wrong-continuation family

Representative unchanged failures:

- `e2e_heldout_multistep_001`
  - `calculate_macro_emission -> render_spatial_map -> query_emission_factors`
- `e2e_heldout_multistep_002`
  - `query_emission_factors -> calculate_macro_emission`
- `e2e_heldout_multistep_006`
  - repeated `calculate_dispersion` continuation behavior

So this Stage 2 gate was effectively blocked by a non-goal category.

## 6. Root Cause Conclusion

There are two separate conclusions:

1. **Within Wave 5a scope**
   - `probe_limit=2` is still too loose for the main multi-turn benchmark
   - the current semantics force proceed one turn later than the evaluator can tolerate

2. **Outside Wave 5a scope**
   - held-out multi-step remained unchanged because the round did not touch the wrong-continuation family
   - using it as a hard Stage 2 gate for this round prevented rollout even though the code change was multi-turn-only

## 7. Stop Point

Per protocol, rollout stops here.

Not run:

- Stage 3 main smoke regression
- Stage 4 main full A/E
- Stage 4 held-out full A/E

## 8. Recommended Next Move

The narrow next iteration is not a redesign. It is one more calibration:

- either lower the effective optional probe budget from `2` to `1`,
- or change the force-proceed condition from “before asking the next optional question” to “when asking the second optional question”.

That is the direct fix for the main multi-turn miss.

Held-out multi-step should be treated separately. This round did not move it.
