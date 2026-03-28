# P0E: Repair-Aware Next-Turn Continuation

## 1. Summary

本轮实现了 live session / live router 生命周期内的 repair-aware next-turn continuation。

结果不是 durable resume，也不是 scheduler。当前实现做的是：

- 上一轮留下的 residual plan / repair history / blocked context 会被保存到 `UnifiedRouter` 的 live in-memory continuation bundle。
- 下一轮 `core/router.py::_state_handle_input()` 会显式判断是否继续 residual workflow。
- 若 continuation 成立，router 会把 residual plan 恢复到新的 `TaskState`，并把 residual summary / next pending step / latest repair or blocked reason 注入首轮 tool-selection context。
- 若用户显式开启新任务，continuation 会被跳过，并记录 trace，不会把新请求硬套进旧 residual workflow。

目标已达到：repaired residual plan 现在会影响下一轮决策，而且这个过程是 selective、traceable、testable 的。

## 2. Files Changed

`core/router.py`

- 新增 live continuation bundle。
- 新增 continuation policy / summary / injection helpers：
  - `_sync_live_continuation_state()`
  - `_should_continue_residual_plan()`
  - `_is_new_task_request()`
  - `_build_residual_plan_summary_for_prompt()`
  - `_inject_continuation_guidance()`
  - `_record_continuation_decision()`
  - `_should_replan_on_continuation()`
- 在 `_run_state_loop()` 结束时同步 residual state。
- 在 `_state_handle_input()` 中插入 continuation decision 和 prompt injection。

`core/task_state.py`

- 新增正式 continuation IR：`ContinuationDecision`。
- `TaskState` 新增 `continuation` 字段。
- `TaskState.to_dict()` 现在暴露：
  - `continuation`
  - `continuation_ready`
  - `continuation_reason`
  - `latest_repair_summary`
  - `residual_plan_summary`
- 新增最小 helper：
  - `set_continuation_decision()`
  - `get_latest_repair_summary()`
  - `get_residual_plan_summary()`

`core/plan.py`

- 为 residual workflow continuation 增加最小 plan helper：
  - `get_pending_steps()`
  - `has_pending_steps()`

`core/trace.py`

- 新增 continuation trace types：
  - `PLAN_CONTINUATION_DECIDED`
  - `PLAN_CONTINUATION_SKIPPED`
  - `PLAN_CONTINUATION_INJECTED`
- 更新 user-friendly formatter。

`config.py`

- 新增 feature flag：
  - `ENABLE_REPAIR_AWARE_CONTINUATION`
- 默认值为 `false`，原因是这轮会改变跨连续 turn 的 tool-selection context，默认关闭更利于回归安全和 ablation。

`tests/test_router_state_loop.py`

- 新增跨 turn continuation 测试：
  - repair applied -> next turn continuation
  - dependency blocked residual -> next turn continuation
  - explicit new task override
  - ambiguous input without safe continuation

`tests/test_task_state.py`

- 新增 continuation observability 测试。

`tests/test_trace.py`

- 新增 continuation trace formatting 测试。

## 3. Continuation Policy

continuation 触发前提不是“state 里有个 plan 就继续”，而是更保守的 live residual policy。

`core/router.py::_should_continue_residual_plan()` 的判定顺序是：

1. `ENABLE_REPAIR_AWARE_CONTINUATION` 必须开启。
2. router 的 live continuation bundle 中必须存在 residual `ExecutionPlan`。
3. 该 residual plan 必须仍有 pending step。
4. 然后区分三类用户输入：

- 明确 continuation：
  - 例如 `继续`、`接着做`、`next step`。
  - 直接判为 continuation。
- 明确 new task：
  - 例如 `换个任务`、`重新分析`、`直接回答这个新问题`。
  - 或上传文件相对 residual workflow 明显切换。
  - 明确跳过 continuation。
- 模糊输入：
  - 只在用户输入仍与 residual goal / pending tools / blocked tokens 语义相关时才继续。
  - 否则跳过，不把所有后续消息黏到旧计划上。

这样设计的原因是：论文叙事需要的是 bounded workflow adaptation，而不是“只要有 residual plan 就强行续跑”。

## 4. Continuation Context Injection

residual summary 由 `core/router.py::_build_residual_plan_summary_for_prompt()` 构造，不是全文 dump。

摘要内容包括：

- original goal
- residual plan status
- available result tokens
- latest repair summary
- latest blocked reason
- next pending step
- first ready residual step（如果和 next pending step 不同）
- 最多 4 个 residual steps 的紧凑列表

注入点在 `core/router.py::_state_handle_input()`，位置是：

- `assemble()` 之后
- lightweight planning / first `chat_with_tools()` 之前

真正执行注入的是 `core/router.py::_inject_continuation_guidance()`，它把一条 system guidance message 插入当前 assembled context。该 guidance 明确告诉 LLM：

- 本轮应被解释为 residual workflow continuation
- 优先考虑 next ready residual step
- 不要 auto-execute
- 不要 auto-complete dependencies

这让 continuation 成为正式 prompt context，而不只是上轮 repair 响应文本里的说明。

## 5. Router Integration

真实控制流现在是：

1. `UnifiedRouter.chat()` 仍然清空 current-turn context store，仅保持 session-scoped stored results。
2. `_run_state_loop()` 新建新的 `TaskState`，但不会从 disk/history 重建 plan。
3. `_state_handle_input()` 中：
   - 先做文件 grounding 和 assemble。
   - 然后调用 `_should_continue_residual_plan()`。
   - 若 continuation 成立：
     - `_activate_live_continuation_state()` 将 live residual `ExecutionPlan` 和 `repair_history` 恢复进当前 turn 的 `TaskState`。
     - `_record_continuation_decision()` 写 `PLAN_CONTINUATION_DECIDED`。
     - `_inject_continuation_guidance()` 注入 residual summary，并写 `PLAN_CONTINUATION_INJECTED`。
     - 默认不 full replan。
   - 若 continuation 被跳过：
     - 写 `PLAN_CONTINUATION_SKIPPED`。
     - 正常走本轮新任务逻辑。
4. `_state_handle_executing()` 继续复用上一轮已有的 plan reconciliation / dependency enforcement / bounded repair 路径。
5. turn 结束后，`_run_state_loop()` 调用 `_sync_live_continuation_state()`：
   - 若当前 `state.plan` 仍有 pending residual steps，则把它快照到 router 的 live continuation bundle。
   - 若 plan 已完成或不存在，则清空 active continuation bundle。

没有做 auto-completion，因为这轮目标是“下一轮在 residual workflow 约束下继续决策”，不是“系统自动把剩余步骤跑完”。

## 6. Trace Extensions

新增 trace step types：

- `PLAN_CONTINUATION_DECIDED`
- `PLAN_CONTINUATION_SKIPPED`
- `PLAN_CONTINUATION_INJECTED`

写入路径：

- `_record_continuation_decision()` 负责 `DECIDED` / `SKIPPED`
- `_inject_continuation_guidance()` 负责 `INJECTED`

每个 trace 都包含 continuation 相关关键信息，例如：

- residual plan 是否存在
- next pending step
- continuation signal
- latest repair summary
- latest blocked reason
- guidance preview

这些 trace 对论文有价值，因为它们能展示：

- residual workflow 何时被继续
- 何时被显式跳过
- continuation context 到底向 LLM 注入了什么

## 7. Tests

本轮实际运行了：

```bash
python -m py_compile core/plan.py core/task_state.py core/trace.py core/router.py config.py tests/test_router_state_loop.py tests/test_task_state.py tests/test_trace.py
pytest -q tests/test_task_state.py tests/test_trace.py
pytest -q tests/test_router_state_loop.py
pytest -q tests/test_context_store_integration.py
pytest -q tests/test_router_state_loop.py tests/test_task_state.py tests/test_trace.py tests/test_context_store_integration.py
```

结果：

- `tests/test_task_state.py tests/test_trace.py`: `33 passed`
- `tests/test_router_state_loop.py`: `21 passed`
- `tests/test_context_store_integration.py`: `11 passed`
- combined suite: `65 passed`

关键新增覆盖：

- repair applied 后，下一轮 `继续` 会恢复 residual plan，并沿 next pending step 注入 tool-selection context
- dependency blocked residual state 会影响下一轮 continuation guidance
- 明确 new task 会跳过 continuation
- 模糊但不安全的输入不会被错误续接到 residual workflow
- `TaskState.to_dict()` 可观察 continuation state
- continuation trace formatter 可读

## 8. Known Limitations

- no durable persistence / resume
- no auto-execution of residual steps
- no dependency auto-completion
- no user approval/editing flow
- still not a full scheduler or rigid executor
- continuation only works within the live session/router lifecycle

额外说明：

- 当前 continuation 依赖 `Session.router` 复用同一个 `UnifiedRouter` 实例。
- 如果 router 进程/实例被销毁，live continuation bundle 不会从 disk 历史中重建。
- 这符合本轮边界，也更利于论文里明确区分 continuation vs durable resume。

## 9. Suggested Next Step

最自然的下一步是：**repair-aware continuation prompt calibration + bounded continuation evaluation harness**。

原因是代码层 continuation 已经接通，下一轮最值得做的不是 persistence，而是围绕现有 `PLAN_CONTINUATION_*` trace 和 residual guidance，系统性评估：

- continuation 是否真的提高 next-step alignment
- 哪些 blocked / repaired residual patterns 最容易被继续正确执行
- 哪些 prompt 注入形式最稳定

这比直接跳到 persistence 或 scheduler 更符合当前代码现实，也更服务论文叙事。
