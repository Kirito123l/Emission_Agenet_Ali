# P0-B Lightweight Planning Implementation Report

## 1. Summary

This round implements the requested P0-B MVP on the state loop only:

- a formal lightweight execution plan IR
- canonical dependency/result tokens
- deterministic plan validation
- planning-stage traceability
- soft plan participation in actual tool selection

The main insertion point is `core/router.py::_state_handle_input()`, between `assemble()` and the first `chat_with_tools()` call. Legacy loop behavior was not reworked.

Overall status: completed for the requested MVP scope.

## 2. Files Changed

- `core/plan.py`
  - Added `PlanStatus`, `PlanStepStatus`, `PlanStep`, `ExecutionPlan`
  - Added `to_dict()` / `from_dict()` and minimal step-status helpers
- `core/task_state.py`
  - Added `TaskState.plan`
  - Extended `to_dict()` to serialize plan
  - Added `set_plan()`, `get_next_planned_step()`, `update_plan_step_status()`
- `core/tool_dependencies.py`
  - Switched dependency semantics to canonical tokens: `emission`, `dispersion`, `hotspot`
  - Added `normalize_result_token()`, `normalize_tokens()`, `get_required_result_tokens()`, `validate_plan_steps()`
  - Kept legacy alias compatibility for `emission_result`, `dispersion_result`, `hotspot_analysis`
- `core/context_store.py`
  - Normalized incoming result/layer lookups
  - Added direct `dispersion` layer handling for `render_spatial_map`
- `core/router.py`
  - Added planning-stage helpers:
    - `_should_generate_plan()`
    - `_generate_execution_plan()`
    - `_validate_execution_plan()`
    - `_collect_available_result_tokens()`
    - `_inject_plan_guidance()`
    - `_validate_tool_selection_against_plan()`
  - Inserted planning into `_state_handle_input()`
  - Added soft plan alignment check in `_state_handle_grounded()`
  - Reflected tool execution outcome back into plan state
- `core/trace.py`
  - Added `PLAN_CREATED`, `PLAN_VALIDATED`, `PLAN_DEVIATION`
  - Added user-friendly formatting for these step types
- `services/llm_client.py`
  - Added async structured JSON call: `chat_json()`
- `config.py`
  - Added feature flag: `enable_lightweight_planning` backed by `ENABLE_LIGHTWEIGHT_PLANNING`
- `core/skill_injector.py`
  - Minimal compatibility update so dependency expansion uses canonicalized tokens
- Tests
  - Updated dependency/token assertions to canonical form where needed
  - Added new planning and validation coverage

## 3. Planning Architecture

Plan IR:

- `ExecutionPlan` carries `goal`, `mode`, `planner_notes`, `status`, `validation_notes`, ordered `steps`
- `PlanStep` carries `step_id`, `tool_name`, `purpose`, `depends_on`, `produces`, `argument_hints`, `status`, `validation_notes`

Generation path:

- `core/router.py::_state_handle_input()`
  - file grounding
  - `assemble()`
  - `_should_generate_plan()`
  - `_generate_execution_plan()` via `llm.chat_json()`
  - `_validate_execution_plan()`
  - `_inject_plan_guidance()`
  - first `chat_with_tools()`

Validation path:

- `core/tool_dependencies.py::validate_plan_steps()`
  - normalizes tokens
  - infers true tool requirements
  - validates steps sequentially against currently available result tokens
  - propagates earlier produced tokens forward only when the step is executable
  - returns structured per-step status plus overall `PlanStatus`

Execution participation:

- first tool-selection context receives a compact plan summary as soft guidance
- `core/router.py::_state_handle_grounded()` calls `_validate_tool_selection_against_plan()`
- if first selected tool mismatches the next planned step, router records `PLAN_DEVIATION`
- execution is not hard-blocked

## 4. Token Canonicalization

Canonical tokens in this round:

- `emission`
- `dispersion`
- `hotspot`

Legacy alias compatibility:

- `emission_result -> emission`
- `dispersion_result -> dispersion`
- `hotspot_analysis -> hotspot`

Render dependency handling:

- `render_spatial_map` remains statically open in `TOOL_GRAPH`
- actual prerequisite inference now happens through `get_required_result_tokens()`
  - `layer_type=emission -> emission`
  - `layer_type=dispersion/raster/concentration -> dispersion`
  - `layer_type=hotspot -> hotspot`

This keeps runtime compatibility while making validation semantics explicit and canonical.

## 5. Trace Changes

Added trace step types:

- `PLAN_CREATED`
- `PLAN_VALIDATED`
- `PLAN_DEVIATION`

Router trace write points:

- after JSON planner output is hydrated
- after deterministic validation finishes
- when the first selected tool deviates from the next planned step

Trace payloads include goal, step count, step statuses, available tokens, and deviation reason so the trace is useful for both debugging and paper-oriented audit artifacts.

## 6. Tests

Executed and passing:

- `pytest -q tests/test_router_state_loop.py tests/test_tool_dependencies.py tests/test_context_store_integration.py tests/test_task_state.py tests/test_trace.py tests/test_available_results_tracking.py`
  - Result: `66 passed`

Additional targeted compatibility checks:

- `pytest -q tests/test_context_store.py tests/test_skill_injector.py tests/test_dispersion_integration.py -k "dependency or plan or render_spatial_map or tool_dependency_chain_completeness or hotspot_requires_dispersion or hotspot_provides_analysis"`
  - Result: `14 passed, 110 deselected`

Key new coverage:

- legacy token alias normalization
- canonical provides/requirements
- render layer-type dependency inference
- ordered plan validation
- planning trigger before first tool selection
- `PLAN_CREATED` / `PLAN_VALIDATED` trace emission
- `PLAN_DEVIATION` soft handling
- planner failure fallback
- context-store-backed validation without false missing-dependency reports

## 7. Known Limitations

Explicitly not implemented in this round:

- no user confirmation or editing of the generated plan
- no dependency auto-completion
- no TaskState resume persistence / hydration workflow
- no rigid plan executor

Current behavior is intentionally:

- soft guidance + validation
- strong trace audit
- minimal intrusion into the existing state loop

Also note:

- planning is feature-gated and defaults to off via `ENABLE_LIGHTWEIGHT_PLANNING=false`
- this was chosen for regression safety and ablation control

## 8. Suggested Next Step

The most paper-aligned next step is to make the plan IR observable across multi-step execution, not by hard-controlling execution, but by adding post-step plan reconciliation metrics:

- planned step matched vs deviated
- validation status transition over time
- dependency failure categories

That would strengthen the empirical story without pushing the system into product-style approval flows or a full orchestrator rewrite.
