# Phase 2.4 Duplicate Execution Diagnosis

## Source

- Log: `evaluation/results/end2end_full_v5_oasc_E/end2end_logs.jsonl`
- Scope: failed tasks with telemetry after Gate 1:
  `e2e_clarification_106`, `111`, `112`, `113`, `115`, `120`
- This is read-only diagnosis. No production logic was changed for this artifact.

## Per-Task Trace

### e2e_clarification_106

- failure mode: `calculate_micro_emission x3`
- first AO complete: turn 2, AO#1
- complete event state: `collection_mode=False`, `tool_intent=high`, `completion_path=should_complete_explicit`, `block_reason=None`
- block_reason non-null: none

| eval_turn | classifier | clarification | AO lifecycle |
|---:|---|---|---|
| 1 | NEW_AO / `first_message_in_session` | clarify, tool=`calculate_micro_emission`, resolved_by=`rule:pending`, collection_mode=True, probe=`model_year` | create AO#1; activate AO#1 |
| 2 | CONTINUATION / `short_clarification` | proceed, `snapshot_direct`, collection_mode=True, probe_turn_count=2, probe_abandoned=True | append_tool_call AO#1; complete AO#1 |
| 3 | REVISION / reasoning says user modifies completed AO#1 vehicle_type | clarify, tool=`calculate_micro_emission`, resolved_by=`rule:file_task_type`, collection_mode=True | create AO#2; activate AO#2; revise AO#2 |
| 4 | CONTINUATION / `short_clarification` | proceed, `snapshot_direct`, collection_mode=True, probe_abandoned=True | append_tool_call AO#2; complete AO#2 |

### e2e_clarification_111

- failure mode: `calculate_macro_emission x3`
- first AO complete: turn 1, AO#1
- complete event state: `collection_mode=False`, `tool_intent=high`, `completion_path=should_complete_explicit`, `block_reason=None`
- block_reason non-null: none

| eval_turn | classifier | clarification | AO lifecycle |
|---:|---|---|---|
| 1 | NEW_AO / `first_message_in_session` | proceed, `snapshot_direct`, collection_mode=False | create AO#1; activate AO#1; append_tool_call AO#1; complete AO#1 |
| 2 | CONTINUATION / reasoning says AO#1 already completed but message likely clarifies original intent | no clarification telemetry | append_tool_call AO#1; complete AO#1 again |
| 3 | NEW_AO / reasoning says `再做扩散` is new referenced goal | clarify, tool=`calculate_macro_emission`, collection_mode=True, probe=`scenario_label` | create AO#2; activate AO#2 |

### e2e_clarification_112

- failure mode: `calculate_micro_emission x1`, then later clarification/revision did not complete expected final params
- first AO complete: turn 2, AO#1
- complete event state: `collection_mode=False`, `tool_intent=high`, `completion_path=should_complete_explicit`, `block_reason=None`
- block_reason non-null: turn 3 has `basic_checks_failed`, after AO#1 was already complete

| eval_turn | classifier | clarification | AO lifecycle |
|---:|---|---|---|
| 1 | NEW_AO / `first_message_in_session` | clarify, tool=`calculate_micro_emission`, collection_mode=True, probe=`model_year` | create AO#1; activate AO#1 |
| 2 | CONTINUATION / `short_clarification` | proceed, `snapshot_direct`, collection_mode=True, probe_abandoned=True | append_tool_call AO#1; complete AO#1 |
| 3 | CONTINUATION / reasoning says current AO is completed but NOx is result-focused continuation | no clarification telemetry | complete_blocked AO#1, `block_reason=basic_checks_failed` |
| 4 | REVISION / reasoning says `冬天` modifies completed AO#1 season | clarify, tool=`calculate_micro_emission`, collection_mode=True | create AO#2; activate AO#2; revise AO#2 |

### e2e_clarification_113

- failure mode: `query_emission_factors x2`
- first AO complete: turn 3, AO#1
- complete event state: `collection_mode=False`, `tool_intent=high`, `completion_path=should_complete_explicit`, `block_reason=None`
- block_reason non-null: none

| eval_turn | classifier | clarification | AO lifecycle |
|---:|---|---|---|
| 1 | NEW_AO / `first_message_in_session` | clarify, tool=`query_emission_factors`, resolved_by=`llm_slot_filler`, collection_mode=True | create AO#1; activate AO#1 |
| 2 | CONTINUATION / `short_clarification` | clarify, resolved_by=`rule:pending`, collection_mode=True | no complete |
| 3 | CONTINUATION / `short_clarification` | proceed, `snapshot_direct`, collection_mode=True | append_tool_call AO#1; complete AO#1 |
| 4 | CONTINUATION / reasoning says no active AO but `次干道` is supplemental road_type for AO#1 | no clarification telemetry | append_tool_call AO#1; complete AO#1 again |

### e2e_clarification_115

- failure mode: `calculate_macro_emission x2`
- first AO complete: turn 3, AO#1
- complete event state: `collection_mode=False`, `tool_intent=high`, `completion_path=should_complete_explicit`, `block_reason=None`
- block_reason non-null: none

| eval_turn | classifier | clarification | AO lifecycle |
|---:|---|---|---|
| 1 | NEW_AO / `first_message_in_session` | clarify, tool=`calculate_macro_emission`, collection_mode=True | create AO#1; activate AO#1 |
| 2 | CONTINUATION / reasoning cites active AO#1 awaiting pollutants | clarify, collection_mode=True, probe=`scenario_label` | no complete |
| 3 | CONTINUATION / reasoning cites active AO#1 awaiting scenario_label | proceed, `snapshot_direct`, collection_mode=True, probe_abandoned=True | append_tool_call AO#1; complete AO#1 |
| 4 | NEW_AO / reasoning says `继续基于刚才的排放结果做扩散分析` is a new referenced goal | clarify, tool=`calculate_macro_emission`, collection_mode=True | create AO#2; activate AO#2 |

### e2e_clarification_120

- failure mode: `calculate_macro_emission x2`
- first AO complete: turn 2, AO#1
- complete event state: `collection_mode=False`, `tool_intent=high`, `completion_path=should_complete_explicit`, `block_reason=None`
- block_reason non-null: none

| eval_turn | classifier | clarification | AO lifecycle |
|---:|---|---|---|
| 1 | NEW_AO / `first_message_in_session` | clarify, tool=`calculate_macro_emission`, collection_mode=True, probe=`scenario_label` | create AO#1; activate AO#1 |
| 2 | CONTINUATION / reasoning cites active AO#1 awaiting scenario_label | proceed, `snapshot_direct`, collection_mode=True, probe_abandoned=True | append_tool_call AO#1; complete AO#1 |
| 3 | NEW_AO / reasoning says `windy_neutral` is isolated and current AO completed/no pending | clarify, tool=`calculate_macro_emission`, collection_mode=True | create AO#2; activate AO#2 |

## Summary Questions

### 1. Did lifecycle invariant guard trigger?

It triggered structurally on all explicit complete events because complete events include `completion_path=should_complete_explicit` and `complete_check_results`. It did not block the duplicate-producing completes in the 6 tasks.

Observed block reasons:

- `None` on all first AO complete events.
- One later `basic_checks_failed` in `e2e_clarification_112` turn 3, after AO#1 had already completed; it did not prevent the initial close.

Reason: by the time snapshot-direct execution succeeds, `parameter_state.collection_mode` has already been cleared to `False`, and `tool_intent.confidence=high`. The guard therefore sees `collection_mode_active=False`, `intent_resolved=True`, `tool_chain_succeeded=True`, `final_response_delivered=True`, and `objective_satisfied=True`.

### 2. What was `collection_mode` when AO completed?

For every first complete event in these tasks, lifecycle telemetry recorded `parameter_state_collection_mode=False`.

Cause pattern:

- PCM was active in clarification telemetry before proceed (`collection_mode=True`).
- On `snapshot_direct` success, commit 13 clears `parameter_state.collection_mode` and `awaiting_slot`.
- `complete_ao()` then runs after the turn and sees collection mode already cleared.
- This clear is semantically correct for "parameter collection done" but too early for multi-turn benchmark intents where the user still has scheduled follow-up parameters or downstream steps.

### 3. Does classifier reasoning cite completed AO state?

Yes, in multiple cases:

- `e2e_clarification_106` turn 3: reasoning says user modifies already completed AO#1 vehicle_type, so `REVISION`.
- `e2e_clarification_112` turn 4: reasoning says `冬天` modifies successfully completed AO#1 season, so `REVISION`.
- `e2e_clarification_120` turn 3: reasoning says current AO is completed and no pending parameter remains, so `NEW_AO`.
- `e2e_clarification_115` turn 4: reasoning says a downstream diffusion request is a new referenced goal after AO#1 completion.

This matches the Phase 1.5 pattern: once AO is completed, classifier tends to frame later follow-up values as revision/new reference instead of continuing the original multi-turn collection.

### 4. One-sentence root-cause hypothesis

Duplicate execution root cause is **A: premature AO completion after snapshot-direct proceed**: snapshot-direct success clears `collection_mode`, lifecycle guard completes AO, and later benchmark follow-up turns are reinterpreted as REVISION/NEW_AO or post-completion continuation, causing repeated tool execution.

## Candidate Labels for Next Repair Prompt

- **D1_CLEAR_TOO_EARLY**: `collection_mode` is cleared at snapshot-direct success before the evaluator dialogue has delivered all follow-up turns.
- **D2_COMPLETE_TOO_EARLY**: `_can_complete_ao` has no knowledge of pending benchmark/user follow-up intent after parameter collection appears complete.
- **D3_CLASSIFIER_COMPLETED_AO_BIAS**: classifier reasoning explicitly uses completed AO state to choose REVISION/NEW_AO.
