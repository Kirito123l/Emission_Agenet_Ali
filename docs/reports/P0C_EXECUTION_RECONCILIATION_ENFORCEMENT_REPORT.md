# P0-C Execution Reconciliation + Deterministic Dependency Enforcement Report

## 1. Summary

本轮把 P0-B 的 planning MVP 从“planning-stage soft guidance”推进到了 execution-stage 可持续对齐与 deterministic dependency gate。

完成的核心点有两条：

- `plan` 不再只在首次 tool selection 生效。`core/router.py` 现在会在每次真正执行工具前做 plan reconciliation，在成功执行后更新对应 `PlanStep`，并把 matched / deviation / completed 写入 trace 和 plan state。
- dependency graph 不再只用于 planning-time validation。`core/tool_dependencies.py` 新增结构化 pre-exec validator，`core/router.py::_state_handle_executing()` 在 executor 调用前强制执行依赖检查；若缺依赖或只有 stale result，则直接 block，不再 silently continue。

本轮目标已达到，但仍然保持了本项目的论文导向边界：

- 没有引入 dependency auto-completion
- 没有把 router 改成 rigid scheduler
- 没有做 plan approval / editing flow
- 没有做 TaskState resume persistence

## 2. Files Changed

### `core/plan.py`

- 扩展 `PlanStepStatus`，增加 `SKIPPED`
- `PlanStep` 增加 `reconciliation_notes` 和 `blocked_reason`
- `ExecutionPlan` 增加 `reconciliation_notes`
- `ExecutionPlan.to_dict()` 现在显式暴露 `next_pending_step`
- 增加 `get_next_pending_step()` / `get_step()`，让 router 可以按 step_id 或 tool_name 做正式状态更新

原因：
execution-stage reconciliation 需要正式的 step-level 状态和注释承载体，不能只靠 trace 临时日志。

### `core/task_state.py`

- `ExecutionContext` 增加 `blocked_info`
- `TaskState.to_dict()` 增加 `next_planned_step`
- `update_plan_step_status()` 现在支持 `reconciliation_note` 和 `blocked_reason`
- 新增 `append_plan_note()`，避免 router 中散落 step note 写法

原因：
blocked 原因、next planned step、execution reconciliation notes 现在都能进入 `TaskState.to_dict()`，满足 execution observability。

### `core/tool_dependencies.py`

- 新增 `DependencyValidationIssue`
- 新增 `DependencyValidationResult`
- 新增 `validate_tool_prerequisites(...)`
- `validate_plan_steps(...)` 改为复用同一套 prerequisite validator

原因：
planning-stage validation 和 runtime pre-exec enforcement 现在走同一套 canonical dependency semantics，避免再次分叉。

### `core/context_store.py`

- `get_available_types(include_stale=False)` 支持过滤 stale
- 新增 `get_result_availability(...)`
- 新增 `_find_current_turn_entry(...)`
- current-turn availability 现在会和 store 的 stale metadata 对齐

原因：
runtime gate 需要明确区分 current / stale / unavailable，且不能被 current-turn 缓存绕过 stale 判断。

### `core/router.py`

- 新增 `_refresh_execution_plan_state()`
- 新增 `_update_plan_status_from_steps()`
- 新增 `_find_planned_step_for_tool()`
- 新增 `_reconcile_plan_before_execution()`
- 新增 `_validate_execution_dependencies()`
- 新增 `_mark_blocked_plan_step()`
- 新增 `_build_dependency_blocked_response_text()`
- `_state_handle_executing()` 现在在每次 executor 调用前做：
  1. plan reconciliation
  2. `_prepare_tool_arguments()`
  3. deterministic dependency validation
  4. block or execute
  5. post-exec plan update
- `_state_build_response()` 现在支持 dependency-blocked 响应路径

原因：
这一轮的控制流主变更全部收束在 state loop 的执行节点，没有引入新的 orchestration stage，也没有改 legacy loop。

### `core/trace.py`

- 新增 trace step types:
  - `PLAN_STEP_MATCHED`
  - `PLAN_STEP_COMPLETED`
  - `DEPENDENCY_VALIDATED`
  - `DEPENDENCY_BLOCKED`
- user-friendly formatter 已接入上述类型

原因：
trace 现在不仅记录“做了什么”，还记录“计划如何被执行 / 偏离 / 阻断”。

### `tests/test_tool_dependencies.py`

- 新增 runtime prerequisite validator 覆盖
- 新增 stale result fail 默认策略覆盖
- 新增 planning/runtime dependency mapping 一致性覆盖

### `tests/test_context_store_integration.py`

- 新增 current vs stale dependency validation 覆盖
- 新增 canonical token path 覆盖
- 新增 `render_spatial_map(layer_type=hotspot)` 无 hotspot 时 deterministic block 覆盖

### `tests/test_router_state_loop.py`

- 新增 multi-step execution reconciliation 覆盖
- 新增 execution-stage deviation 覆盖
- 新增 dependency blocked before execution 覆盖

### `tests/test_trace.py`

- 新增 execution-stage trace formatting 覆盖

### `tests/test_task_state.py`

- 新增 execution-observable plan serialization 覆盖

## 3. Execution Reconciliation Design

reconciliation 的正式落点是 `core/router.py::_state_handle_executing()`。

当前 pre-exec 控制流变为：

1. `_reconcile_plan_before_execution()`
2. `_prepare_tool_arguments()`
3. `_validate_execution_dependencies()`
4. 若通过，调用 executor
5. `_update_plan_after_tool_execution()`
6. `_refresh_execution_plan_state()`

### matched / deviated 的判断

`_reconcile_plan_before_execution()` 每次都会读取 `state.get_next_planned_step()`。

- 如果 `actual_tool_name == next_pending_step.tool_name`
  - 记录 `PLAN_STEP_MATCHED`
  - 将 step 标记为 `IN_PROGRESS`
- 如果 tool 在 plan 中，但不是当前 next pending step
  - 记录 `PLAN_DEVIATION`
  - 将 deviation 分类为 `ahead_of_plan` 或 `behind_plan`
  - 对实际执行的 planned step 标记 `IN_PROGRESS`
- 如果 tool 不在 plan 中
  - 记录 `PLAN_DEVIATION`
  - deviation 类型为 `unplanned_tool`
- 如果 plan 已没有 pending step 但仍继续 tool-calling
  - 记录 `PLAN_DEVIATION`
  - deviation 类型为 `plan_exhausted`

### post-exec plan state 更新

`_update_plan_after_tool_execution()` 会把对应的 planned step 更新为：

- `COMPLETED`：tool success
- `FAILED`：tool returned error

`_refresh_execution_plan_state()` 会再根据“当前真实可用结果”重算尚未完成步骤的 runtime readiness：

- prerequisites 满足 -> `READY`
- prerequisites 不满足 -> `BLOCKED`

这一步的作用是让 plan 在 execution-stage 保持“活着”的状态，而不是 planning 结束后冻结。

## 4. Deterministic Dependency Enforcement

validator 实现在 `core/tool_dependencies.py::validate_tool_prerequisites(...)`。

### validator 输入

- `tool_name`
- `arguments`
- `available_tokens`
- `context_store`
- `include_stale=False`

### available / missing / stale 判定

判定顺序是：

1. 先按 canonical token 解析该工具的 `required_tokens`
2. 再看 `available_tokens`
3. 再看 `context_store.get_result_availability(...)`
4. 若只有 stale result 且 `include_stale=False`
   - 记为 `stale_tokens`
   - validation fail
5. 若结果不存在
   - 记为 `missing_tokens`
   - validation fail

`core/context_store.py` 的 `get_result_availability(...)` 会区分：

- current turn fresh result
- stored fresh result
- stale exact-label result
- stale baseline fallback result
- unavailable

### blocked 时的处理

`core/router.py::_state_handle_executing()` 在 executor 调用前强制执行 `_validate_execution_dependencies()`。

若 validation fail：

- 不执行工具
- 记录 `DEPENDENCY_BLOCKED`
- `state.execution.blocked_info = validation.to_dict()`
- 对应 plan step 标为 `BLOCKED`
- 生成 deterministic blocked response text
- 当前执行链直接结束

### 为什么这一轮没有做 auto-completion

这是刻意保持的边界。当前实现只做 deterministic legality gate，不做：

- 自动补跑前置工具
- 自动扩图
- 自动修正 plan
- 自动 reroute 到别的工具

原因是本轮目标是“workflow constraints are code-level enforced”，不是“把 router 变成 workflow scheduler”。

## 5. Trace Extensions

新增 trace step types：

- `PLAN_STEP_MATCHED`
- `PLAN_STEP_COMPLETED`
- `DEPENDENCY_VALIDATED`
- `DEPENDENCY_BLOCKED`

写入路径如下：

- `PLAN_STEP_MATCHED`
  - `core/router.py::_reconcile_plan_before_execution()`
- `PLAN_STEP_COMPLETED`
  - `core/router.py::_state_handle_executing()` 成功执行后
- `DEPENDENCY_VALIDATED`
  - `core/router.py::_validate_execution_dependencies()` pass 时
- `DEPENDENCY_BLOCKED`
  - `core/router.py::_validate_execution_dependencies()` fail 时

这些 trace 对论文有用的原因很直接：

- 可以明确展示“计划的哪一步被实际执行”
- 可以明确展示“偏离是 unplanned 还是 out-of-order”
- 可以明确展示“执行没有发生，因为 dependency gate 在代码层阻断了它”

换句话说，trace 现在能承载 execution audit，而不只是 decision log。

## 6. Tests

本轮实际运行的测试命令：

```bash
pytest -q tests/test_tool_dependencies.py tests/test_context_store_integration.py tests/test_trace.py tests/test_task_state.py tests/test_router_state_loop.py
```

结果：

- `70 passed`

按任务要求单独补跑：

```bash
pytest -q tests/test_router_state_loop.py tests/test_tool_dependencies.py tests/test_context_store_integration.py
```

结果：

- `43 passed`

额外补跑：

```bash
pytest -q tests/test_context_store.py tests/test_context_store_scenarios.py tests/test_available_results_tracking.py tests/test_skill_injector.py
```

结果：

- `84 passed`

新增覆盖的关键行为：

- multi-step execution 中的 `PLAN_STEP_MATCHED` / `PLAN_STEP_COMPLETED`
- execution-stage out-of-order deviation
- dependency blocked before execution
- current vs stale result validation
- render hotspot 无结果时 deterministic block
- planning/runtime dependency mapping 一致性
- execution-observable plan serialization
- new trace formatter outputs

## 7. Known Limitations

这一轮仍然明确没有做以下内容：

- 仍然没有 dependency auto-completion
- 仍然没有 plan approval / editing
- 仍然没有 TaskState resume persistence
- 仍然不是 rigid plan executor
- 当前 enforcement 是 deterministic pre-exec gate，不是 full workflow controller

另外还有一个工程上刻意保留的限制：

- runtime injection 仍然和 plan reconciliation / dependency enforcement 解耦存在。也就是说，`_prepare_tool_arguments()` 负责喂数据，dependency gate 负责判合法，plan reconciliation 负责审计；这一层没有进一步合并成统一 executor framework。

这对论文叙事是好事，因为三者职责现在更清楚；但从工程完整性看，后续如果要做更强 workflow control，还需要更正式的 runtime step controller。

## 8. Suggested Next Step

下一轮最自然的推进方向是：

- 做 **bounded replanning / partial plan repair**，但只在 execution-stage deviation 或 dependency blocked 之后触发，并且仍然保持“不自动执行补全步骤”的边界。

原因：
当前系统已经具备显式 plan、runtime reconciliation、dependency gate 和 trace。下一步最有研究价值的不是继续堆更多 trace taxonomy，而是在不引入 full scheduler 的前提下，研究“被阻断或偏离后的局部计划修复”。
