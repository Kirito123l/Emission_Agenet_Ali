# P0I4 Residual Re-entry Controller Report

## 1. Summary

本轮实现了 geometry-recovered workflow 的 bounded residual-step re-entry controller。

已完成的核心闭环是：

- geometry recovery 成功后，正式生成 `ResidualReentryTarget`
- 该 target 被写入 `RecoveredWorkflowReentryContext`，而不是只停留在自然语言 hint
- 下一轮若用户继续当前任务，router 会先做正常 continuation 判定，再通过一个 deterministic controller 决定是否注入 re-entry bias
- bias 只影响 assembled context / tool selection guidance
- 不自动执行 target action
- 不 replay residual workflow
- 不引入 scheduler / persistence

这一轮达到目标。当前 recovered workflow 不只是 “resumable”，而是 “resumable with an auditable preferred re-entry target”。

## 2. Files Changed

### Core runtime

- `core/residual_reentry.py`
  - 新增 formal re-entry IR：
    - `ResidualReentryTarget`
    - `RecoveredWorkflowReentryContext`
    - `ReentryDecision`
    - `ReentryStatus`
  - 新增 target / guidance builders：
    - `build_residual_reentry_target(...)`
    - `build_recovered_workflow_reentry_context(...)`
    - `build_reentry_guidance_summary(...)`

- `core/router.py`
  - geometry recovery success 路径现在会写入 formal re-entry target
  - 新增 re-entry controller helpers：
    - `_set_residual_reentry_context(...)`
    - `_message_matches_reentry_target(...)`
    - `_evaluate_reentry_target_readiness(...)`
    - `_build_residual_reentry_decision(...)`
    - `_record_residual_reentry_decision(...)`
    - `_inject_residual_reentry_guidance(...)`
  - 修改 `_handle_geometry_completion_upload(...)`
    - geometry recovery 成功后构造 `RecoveredWorkflowReentryContext`
    - 写 `RESIDUAL_REENTRY_TARGET_SET`
    - geometry recovery success message 现在会明确指出下一轮优先回到哪个动作
  - 修改 `_should_continue_geometry_recovery(...)`
    - continuation 判定不再只依赖 residual-plan heuristic
    - 当存在 recovered re-entry target 时，可以在下一轮显式继续它
    - 支持 “有 residual plan” 和 “只有 recovered target、没有 residual plan” 两种 bounded 情况
  - 修改 `_state_handle_input(...)`
    - explicit new task 时显式跳过 re-entry
    - continuation 决策后注入 re-entry bias
    - 仍然走正常 state loop，不绕过 tool selection
  - 扩展 live input-completion bundle
    - 新增 `residual_reentry_context`

- `core/task_state.py`
  - 新增 state observability：
    - `residual_reentry_context`
    - `reentry_bias_applied`
  - `TaskState.to_dict()` 新暴露：
    - `reentry_target_summary`
    - `reentry_status`
    - `reentry_source`
    - `reentry_guidance_summary`
    - `reentry_bias_applied`
    - `residual_reentry_context_summary`

- `core/trace.py`
  - 新增 trace types：
    - `RESIDUAL_REENTRY_TARGET_SET`
    - `RESIDUAL_REENTRY_DECIDED`
    - `RESIDUAL_REENTRY_INJECTED`
    - `RESIDUAL_REENTRY_SKIPPED`
  - 扩展 friendly formatter，便于 case study / appendix / debugging

- `config.py`
  - 新增 feature flags：
    - `ENABLE_RESIDUAL_REENTRY_CONTROLLER`
    - `RESIDUAL_REENTRY_REQUIRE_READY_TARGET`
    - `RESIDUAL_REENTRY_PRIORITIZE_RECOVERY_TARGET`

### Tests

- `tests/test_residual_reentry.py`
  - 新增 pure controller tests

- `tests/test_residual_reentry_transcripts.py`
  - 新增 transcript-style recovered continuation regression tests

- `tests/test_router_state_loop.py`
  - 扩展 geometry recovery continuation tests
  - 验证 target set / next-turn bias / stale skip / new-task skip

- `tests/test_trace.py`
  - 新增 residual re-entry trace formatting coverage

- `tests/test_task_state.py`
  - 新增 re-entry observability serialization coverage

- `tests/test_config.py`
  - 新增 residual re-entry feature-flag defaults coverage

- `tests/test_geometry_recovery_transcripts.py`
  - 扩展 geometry recovery transcript assertions，覆盖 re-entry target creation 和更具体的 success message

## 3. Re-entry Design

### Re-entry target IR

本轮没有把 “恢复后优先回到哪个动作” 放在 prompt 文本里，而是新增了正式对象：

- `ResidualReentryTarget`
  - `target_action_id`
  - `target_tool_name`
  - `target_step_id`
  - `source`
  - `reason`
  - `priority`
  - 另外补充了：
    - `target_tool_arguments`
    - `display_name`
    - `residual_plan_relationship`
    - `matches_next_pending_step`

- `RecoveredWorkflowReentryContext`
  - `reentry_target`
  - `residual_plan_summary`
  - `geometry_recovery_context`
  - `readiness_refresh_result`
  - `reentry_status`
  - `reentry_guidance_summary`
  - 另外补充了：
    - `last_decision_reason`
    - `bias_applied_on_turn`
    - `target_ready`
    - `last_target_readiness_status`

### How target generation works

geometry recovery 成功后，`build_recovered_workflow_reentry_context(...)` 会：

1. 读取 geometry recovery 的原始 `target_action_id`
2. 读取 residual plan 的 next pending step
3. 生成唯一 primary target

规则是 bounded 的：

- 若 geometry recovery target 与 next pending step 一致：
  - 直接绑定该 step，`residual_plan_relationship=aligned_with_next_pending_step`

- 若 residual plan 中仍有该 repaired action，但不是 next pending step：
  - 仍优先使用 repaired action 作为 re-entry target
  - residual plan summary 保留

- 若没有 residual plan：
  - 直接使用 geometry recovery target 作为唯一 re-entry target

### Why this is bounded re-entry, not a scheduler

本轮只决定：

- 下一轮 continuation 时，哪个 recovered action 应该被优先 bias

本轮不做：

- 执行 target
- 执行多个 residual steps
- replan / reorder / auto-chain
- persistence-backed resume

因此它是一个 bounded controller，不是 scheduler graph，也不是 replay engine。

## 4. Router Integration

### How geometry recovery success now sets re-entry target

`core/router.py` 中的 `_handle_geometry_completion_upload(...)` 在 geometry recovery success 后增加了：

1. readiness refresh 成功确认 target action `ready`
2. 调用 `build_recovered_workflow_reentry_context(...)`
3. 把结果写入 `TaskState.residual_reentry_context`
4. 写入 live input-completion bundle 的 `residual_reentry_context`
5. 记录 `RESIDUAL_REENTRY_TARGET_SET`

这一步发生在 geometry recovery success turn 内，但仍然不执行目标工具。

### How next-turn continuation applies re-entry bias

下一轮在 `_state_handle_input(...)` 中：

1. 先按现有 continuation policy 判定是否继续当前任务
2. 再调用 `_build_residual_reentry_decision(...)`
3. controller 会检查：
   - feature flag 是否开启
   - 是否存在 recovered workflow re-entry context
   - 当前 turn 是否 continuation 而不是 new task
   - 若要求 ready target，则 target 是否仍然 ready
4. 若满足条件，调用 `_inject_residual_reentry_guidance(...)`

注入的是一个额外 system guidance block，明确写出：

- recovered workflow re-entry target
- residual-plan relationship
- 本轮应优先考虑该 target
- 不自动执行
- 不 replay whole workflow

### Why this still does not auto replay

本轮没有在 controller 中直接触发：

- `executor.execute(...)`
- residual workflow replay
- chained tool calls

re-entry bias 只影响后续 `chat_with_tools()` 的上下文，因此仍属于正常 state-loop decision making。

## 5. Residual Workflow Interaction

本轮没有改变 residual workflow 的 authoritative ownership。

实现上的协调方式是：

- residual workflow 仍由 live continuation bundle 持有
- `_activate_live_continuation_state(...)` 仍负责恢复 residual plan
- re-entry target 只是一个更强的 next-turn bias

因此：

- residual plan 仍保留
- next pending step summary 仍保留
- workflow template fresh recommendation 仍会在 recovered continuation 时被跳过
- re-entry target 只是在 continuation guidance 之上，再额外明确 “当前最优先回到哪个 repaired action”

这保证了 continuity 提升，但没有把 residual workflow ownership 从现有 continuation policy 手里拿走。

## 6. Trace Extensions

### New trace types

- `RESIDUAL_REENTRY_TARGET_SET`
  - geometry recovery success 后写入
  - 记录 recovered target action、source、residual relationship

- `RESIDUAL_REENTRY_DECIDED`
  - 下一轮 continuation 判定后写入
  - 记录本轮是否应用 re-entry bias，以及 why

- `RESIDUAL_REENTRY_INJECTED`
  - 真正把 re-entry guidance 注入 assembled context 时写入
  - 记录 guidance preview

- `RESIDUAL_REENTRY_SKIPPED`
  - 明确未应用时写入
  - 例如 explicit new task、target stale/not-ready、unsafe continuation

### Why these traces matter for the paper

这些 traces 让论文可以明确展示：

- remediation 后不仅 readiness 被刷新
- 还显式生成了一个 auditable re-entry target
- 下一轮不是靠 unconstrained LLM 自己“猜回去”
- controller 做了 bounded、可解释、可审计的偏置

这比只在 prompt 里加一句 “继续做上一个任务” 更适合作为 formal workflow-recovery artifact。

## 7. Tests

### Commands run

1. `python -m py_compile core/router.py core/task_state.py core/trace.py core/residual_reentry.py tests/test_residual_reentry.py tests/test_residual_reentry_transcripts.py tests/test_router_state_loop.py tests/test_trace.py tests/test_task_state.py tests/test_config.py`
   - 结果：通过

2. `pytest -q tests/test_residual_reentry.py tests/test_residual_reentry_transcripts.py tests/test_geometry_recovery.py tests/test_geometry_recovery_transcripts.py tests/test_router_state_loop.py tests/test_trace.py tests/test_task_state.py tests/test_config.py tests/test_input_completion.py tests/test_input_completion_transcripts.py tests/test_readiness_gating.py`
   - 结果：`122 passed`

### Key behaviors now covered

- geometry recovery success formally sets a `ResidualReentryTarget`
- next-turn continuation applies bounded re-entry bias
- injected guidance explicitly prioritizes recovered target action
- explicit new task skips re-entry
- stale / no-longer-ready target skips re-entry
- residual workflow ownership is preserved
- no scheduler semantics were introduced
- trace formatting covers all new re-entry step types
- `TaskState.to_dict()` exposes re-entry observability fields

## 8. Known Limitations

- no automatic replay
- no durable persistence / resume
- re-entry bias only applies to bounded recovered workflows
- no scheduler semantics were introduced
- recovered target preference still depends on bounded readiness / continuation conditions

另外还有一个工程上刻意保留的边界：

- re-entry target 仍主要依赖 action-id / tool-name / residual-step mapping，而不是新的 global action graph
- 这是为了保持 bounded，但意味着 target binding 仍受现有 residual plan annotations 的质量影响

## 9. Suggested Next Step

最推荐的下一步是：

- 给 lightweight plan steps 增加稳定的 `action_id` annotation，并在 repair / continuation / re-entry 全链路复用

原因是当前 re-entry target 仍需要在 `action_id <-> tool_name <-> argument_hints.layer_type` 之间做 bounded mapping。若 residual step 自身携带 canonical `action_id`，后续可以进一步降低 re-entry binding 的启发式成分，同时不必引入 scheduler。
