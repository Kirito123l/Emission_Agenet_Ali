# Wave 3 Stage 2 Multi-turn Gate Failure Diagnosis

## 1. Scope

Stage 2 failed on the first required smoke gate, so rollout stopped here.

- Code changes were already implemented and committed before the gate run.
- No held-out `multi_step` smoke, no Stage 3 main smoke, and no Stage 4 full runs were started after the failure.
- This diagnosis is read-only. It uses:
  - `evaluation/results/wave3_main_multiturn_smoke_E/end2end_metrics.json`
  - `evaluation/results/wave3_main_multiturn_smoke_E/end2end_logs.jsonl`
  - `evaluation/results/wave2_main_full_E/end2end_logs.jsonl`
  - `evaluation/diagnostics/wave2_multiturn_regression_deep_diagnosis.md`

## 2. Gate Result

Wave 3 Stage 2 command:

```bash
python evaluation/run_oasc_matrix.py --groups E \
  --samples evaluation/benchmarks/end2end_tasks.jsonl \
  --filter-categories multi_turn_clarification \
  --parallel 8 --qps-limit 15 --cache \
  --output-prefix wave3_main_multiturn_smoke
```

Result:

| Metric | Value |
|---|---:|
| tasks | 20 |
| completion | 5.00% (1/20) |
| tool accuracy | 5.00% |
| infra unknown | 0 |
| data integrity | clean |
| Stage 2 mean latency | 5135.8 ms |

Required gate: `multi_turn_clarification >= 40%`  
Actual: `5%`

Wave 2 reference:

| Run | multi_turn completion |
|---|---:|
| `wave2_main_full_E` | 10.00% (2/20) |
| `wave3_main_multiturn_smoke_E` | 5.00% (1/20) |

So Wave 3 regressed the target slice instead of recovering it.

## 3. Aggregate Failure Shape

### 3.1 Outcome distribution

| Shape | Count |
|---|---:|
| pass | 1 |
| extra execution | 15 |
| partial chain | 2 |
| tool chain empty | 1 |
| wrong tool same length | 1 |

This is not a latency or infra issue. It is still a continuation / clarify-first control problem, now dominated by repeated execution.

### 3.2 Continuation telemetry never engaged the intended path

Across all 79 split-contract triggers in this smoke run:

| Signal | Count |
|---|---:|
| `transition_reason=initial_write` | 29 |
| `transition_reason=advance` | 15 |
| `transition_reason=no_change` | 35 |
| `transition_reason=advance_queue` | 0 |
| `transition_reason=replace_queue_override` | 0 |
| `short_circuit_intent=true` | 0 |
| `execution_continuation_active` completion blocks | 0 |

Interpretation:

- `parameter_collection` state was written.
- It was then cleared before execution on many tasks.
- `chain_continuation` never became active on this slice.
- AO lifecycle never blocked completion on active continuation state because there was no active continuation left by completion time.

### 3.3 Projected-chain assumption did not hold on this category

Stage 2 raw payload `chain` values:

| `chain` payload | Count |
|---|---:|
| `[]` | 52 |
| `["calculate_macro_emission"]` | 1 |
| length > 1 | 0 |

The Wave 3 design assumed `pending_tool_queue` would come from `ToolIntent.projected_chain`. On `multi_turn_clarification`, that almost never happens. The downstream obligation usually appears only after a clarification turn or after the first tool result, not in the initial user request.

### 3.4 The split path still ignores the old clarify-first signals

Additional smoke-level counts:

| Signal | Count |
|---|---:|
| tasks with at least one Stage 2 `needs_clarification=true` payload | 14 |
| tasks clearing `parameter_collection` via `transition_reason=advance` before proceed | 15 |
| tasks with cross-turn tool drift in clarification telemetry | 9 |

The failures are concentrated on tools whose config already encodes follow-up / confirm-first behavior:

| Expected top tool | Failed tasks |
|---|---:|
| `query_emission_factors` | 11 |
| `calculate_macro_emission` | 5 |
| `calculate_micro_emission` | 3 |

Relevant config:

- `config/unified_mappings.yaml:556-570`
  - `query_emission_factors.clarification_followup_slots = [model_year]`
  - `query_emission_factors.confirm_first_slots = [road_type]`
- `config/unified_mappings.yaml:572-583`
  - `calculate_micro_emission.confirm_first_slots = [season]`
- `config/unified_mappings.yaml:584-593`
  - `calculate_macro_emission.confirm_first_slots = [season]`

The split path does not consume those follow-up / confirm-first semantics.

## 4. Representative Traces

### 4.1 `e2e_clarification_101`: parameter collection is written, then lost

Expected: one `query_emission_factors` execution  
Actual: two `query_emission_factors` executions

Observed path:

1. Turn 1: `clarify`, pending slot `vehicle_type`
2. Turn 2: `clarify`, pending slot switches to `pollutants`
3. Turn 3: `proceed`, `transition_reason=advance`, continuation cleared
4. Turn 4: user supplies year, classifier emits `REVISION`, second execution runs

Why this matters:

- The split path did write `pending_objective=parameter_collection`.
- But on proceed it cleared that state before AO completion.
- `query_emission_factors` has `clarification_followup_slots=[model_year]`, but split readiness does not preserve that obligation.
- The later year input becomes a revision of a completed AO, so the tool executes twice.

Relevant code:

- [execution_readiness_contract.py](/home/kirito/Agent1/emission_agent/core/contracts/execution_readiness_contract.py#L294): clears `parameter_collection` on proceed.
- [ao_manager.py](/home/kirito/Agent1/emission_agent/core/ao_manager.py#L386): can only block completion if continuation is still active.
- [governed_router.py](/home/kirito/Agent1/emission_agent/core/governed_router.py#L298): legacy follow-up retention still writes only `clarification_contract` metadata, not split continuation state.

### 4.2 `e2e_clarification_116`: parameter collection does not pin intent

Expected: `calculate_micro_emission`  
Actual: `query_emission_factors`

Clarification telemetry tool drift:

- `calculate_micro_emission`
- `query_emission_factors`
- `query_knowledge`
- `query_emission_factors`

This is the clearest implementation-level miss. While `parameter_collection` is active, short clarification answers should stay bound to the current AO tool. They do not.

Why:

- `IntentResolutionContract` only short-circuits when `pending_objective == chain_continuation`.
- `IntentResolver._pending_tool_name()` only reads `pending_next_tool` or legacy clarification metadata.
- `parameter_collection` carries `pending_slot`, but not the tool binding that later turns should reuse.

Relevant code:

- [intent_resolution_contract.py](/home/kirito/Agent1/emission_agent/core/contracts/intent_resolution_contract.py#L39): short-circuit is limited to `CHAIN_CONTINUATION`.
- [intent_resolver.py](/home/kirito/Agent1/emission_agent/core/intent_resolver.py#L150): pending tool lookup ignores `PARAMETER_COLLECTION`.

Net effect: once the user replies with a short slot value, the system can drift to a different tool family.

### 4.3 `e2e_clarification_119`: Stage 2 asked to clarify, split readiness still proceeded

Expected: `calculate_macro_emission -> render_spatial_map`  
Actual: `calculate_macro_emission -> calculate_macro_emission -> render_spatial_map`

Key telemetry:

- First turn Stage 2 raw payload had `needs_clarification=true`
- First turn `chain=["calculate_macro_emission"]`
- First turn decision still became `proceed`
- No `chain_continuation` state was created

This reproduces the Wave 2 regression mechanism:

- Stage 2 clarification intent is advisory only.
- If the merged snapshot appears executable, split readiness proceeds.
- Because `chain` was only the current tool, not the later map step, no queue was installed.
- The later map request is handled as a fresh/reference turn after macro already executed, producing extra work.

Relevant code:

- [execution_readiness_contract.py](/home/kirito/Agent1/emission_agent/core/contracts/execution_readiness_contract.py#L76): Stage 2 payload is merged.
- [execution_readiness_contract.py](/home/kirito/Agent1/emission_agent/core/contracts/execution_readiness_contract.py#L133): decision only keys off `missing_required` / `rejected_slots`, not `needs_clarification`.
- [execution_readiness_contract.py](/home/kirito/Agent1/emission_agent/core/contracts/execution_readiness_contract.py#L327): direct execution is emitted whenever projected chain length is `<= 1`.

### 4.4 `e2e_clarification_110`: exploratory scope framing still masks collection

Expected: `query_emission_factors`  
Actual: no tool execution

Observed path:

- All four turns ended in `clarify`
- `readiness_branch=exploratory`
- Pending slot remained trapped in scope/clarification instead of converging to execution

This was already a Wave 2 failure family. Wave 3 continuation state did not address it because:

- the branch decision still depends on stance,
- `needs_clarification` is not a hard readiness gate,
- and there is no split-native collection objective that says "stay on this AO until required/follow-up clarification converges".

## 5. Root Cause Conclusion

One-sentence conclusion:

> Wave 3 added split-native continuation state, but on `multi_turn_clarification` it remained mostly write-only: parameter collection does not bind intent, follow-up / confirm-first obligations were not migrated from PCM, Stage 2 `needs_clarification` is still not a readiness gate, and projected-chain queueing never engages because this category rarely expresses the downstream chain upfront.

In concrete terms there are four separate gaps:

1. **Parameter collection does not short-circuit intent**
   - State is written in readiness.
   - It is not consumed by intent resolution.
   - Result: short replies can drift tools (`calculate_micro_emission -> query_emission_factors -> query_knowledge`).

2. **Follow-up and confirm-first invariants were not migrated**
   - Legacy config encodes them.
   - Split readiness ignores them.
   - Result: AO completes after the first executable snapshot, even when the benchmark expects another clarification turn before execution or before finalization.

3. **Stage 2 `needs_clarification` remains observational only**
   - 14 tasks had at least one `needs_clarification=true` Stage 2 payload.
   - Split readiness still proceeded once the snapshot looked filled enough.
   - Result: premature execution and later revision/extra execution.

4. **`projected_chain` is the wrong source for this category’s continuation**
   - No multi-turn task in this smoke produced a Stage 2 `chain` longer than one tool.
   - Therefore `chain_continuation` never activated and `short_circuit_intent` never fired.
   - Result: the new Wave 3 mechanism targeted the wrong representation for this benchmark slice.

This is a real design defect, not just a missing edge-case test.

## 6. Stop Point

Per protocol, rollout stops here.

Not run after this failure:

- held-out `multi_step` Stage 2 smoke
- Stage 3 main smoke
- Stage 4 main 7-group ablation
- Stage 4 held-out A/E full

The next iteration should start with diagnosis-backed redesign, not more benchmark spend. The minimum design corrections are:

1. make `parameter_collection` bind intent/tool across continuation turns,
2. migrate `clarification_followup_slots` and `confirm_first_slots` into split-native continuation/readiness state,
3. treat Stage 2 `needs_clarification` as a first-class readiness input,
4. derive continuation from post-execution conversational obligations, not only upfront `projected_chain`.
