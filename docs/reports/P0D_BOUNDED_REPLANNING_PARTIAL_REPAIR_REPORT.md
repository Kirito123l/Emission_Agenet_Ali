# P0D Bounded Replanning + Partial Plan Repair

## 1. Summary

本轮实现了一个受限的 residual plan repair 层，建立在已有的 lightweight planning、execution-stage reconciliation、以及 deterministic dependency enforcement 之上。

完成结果：

- `plan` 在 execution 偏离或 dependency block 后，不再只能停留在“记录失败”。
- 系统现在可以在严格受控的触发条件下生成 bounded repair decision，并对 residual workflow 做局部修复。
- repair 不是开放式 replanning，也不是 full scheduler。
- repair proposal 会经过 deterministic validation；不合法 proposal 不会静默改写计划。
- repair 全程进入正式数据结构、`TaskState.to_dict()`、以及 trace。

整体上达到了本轮目标，但刻意保持了边界：没有 dependency auto-completion，没有 full replanning，没有 auto-execution of repair steps。

## 2. Files Changed

- `core/plan.py`
  - 为 `PlanStep` 增加 `repair_action`、`repair_source_step_id`、`repair_notes`。
  - 为 `ExecutionPlan` 增加 `repair_notes`。
  - 扩展 `to_dict()` / `from_dict()`，让 repair 结果进入正式 plan serialization。
  - 修正 `mark_step_status()`，允许显式清空旧 `blocked_reason`。

- `core/plan_repair.py`
  - 新增正式 repair IR：
    - `RepairTriggerType`
    - `RepairActionType`
    - `RepairTriggerContext`
    - `PlanRepairPatch`
    - `PlanRepairDecision`
    - `RepairValidationIssue`
    - `RepairValidationResult`
  - 新增 deterministic validator：`validate_plan_repair(...)`
  - 在 validator 内部实现 bounded patch apply，并验证 repaired residual workflow 的合法性。

- `core/task_state.py`
  - 新增 `repair_history: List[PlanRepairDecision]`
  - `TaskState.to_dict()` 现在暴露 `repair_history`
  - 新增 `record_plan_repair(...)`

- `core/router.py`
  - 新增 bounded repair prompt 和完整 repair helper：
    - `_validate_residual_plan_legality(...)`
    - `_build_repair_trigger_context(...)`
    - `_should_attempt_plan_repair(...)`
    - `_generate_plan_repair(...)`
    - `_attempt_plan_repair(...)`
    - `_apply_plan_repair(...)`
    - `_build_plan_repair_response_text(...)`
    - `_build_plan_repair_failure_text(...)`
  - 在 `_state_handle_executing()` 中接入：
    - deviation-based selective repair
    - blocked-based repair after dependency gate
  - repair 一旦触发并进入 apply/fail path，本轮停止继续执行，不会自动执行 repair step。

- `core/trace.py`
  - 新增 trace step types：
    - `PLAN_REPAIR_TRIGGERED`
    - `PLAN_REPAIR_PROPOSED`
    - `PLAN_REPAIR_APPLIED`
    - `PLAN_REPAIR_FAILED`
    - `PLAN_REPAIR_SKIPPED`
  - 扩展 user-friendly formatter。

- `config.py`
  - 新增 feature flag：`ENABLE_BOUNDED_PLAN_REPAIR`
  - 默认值保持 `false`，优先回归安全和后续 ablation 可控性。

- `tests/test_router_state_loop.py`
  - 新增 blocked -> repair、severe deviation -> repair、invalid repair fallback、mild deviation -> repair skipped 覆盖。

- `tests/test_tool_dependencies.py`
  - 新增 repair validator 的合法/非法路径测试。

- `tests/test_task_state.py`
  - 新增 repaired plan serialization 和 residual observability 测试。

- `tests/test_trace.py`
  - 新增 repair trace formatting 测试。

## 3. Repair Trigger Policy

repair trigger policy 被明确限制在 execution-stage 事件之后：

- 必触发 repair
  - `DEPENDENCY_BLOCKED`
  - `PLAN_DEVIATION` 且 `deviation_type in {"plan_exhausted", "unplanned_tool"}`

- 条件触发 repair
  - `ahead_of_plan`
  - `behind_plan`
  - 只有当 `router._validate_residual_plan_legality(...)` 判断 residual workflow 已不再合法时才触发

- 不触发 repair
  - 普通 direct answer
  - planning-stage validation failure
  - 无 plan 的普通单步回答
  - 轻微 ahead/behind 且 residual plan 仍合法

实现位置在 `core/router.py::_state_handle_executing()`：

- 先由 `_reconcile_plan_before_execution()` 识别 deviation
- 再由 `_should_attempt_plan_repair()` 做 selective policy 决策
- 被跳过的 repair 不会悄悄消失，而是写入 `PLAN_REPAIR_SKIPPED`

这样设计的原因是：repair 必须是 trigger-bounded，而不是执行期任意时刻都能被 LLM 自由发起。

## 4. Repair Representation

repair 使用正式 IR，而不是 trace 里的临时 dict。

核心结构在 `core/plan_repair.py`：

- `RepairTriggerContext`
  - 表示 repair 触发原因和上下文
  - 包含 trigger type、target step、available tokens、missing/stale tokens、deviation type 等

- `PlanRepairDecision`
  - 表示 planner 返回的 bounded repair decision
  - 包含：
    - `trigger_type`
    - `trigger_reason`
    - `action_type`
    - `target_step_id`
    - `affected_step_ids`
    - `planner_notes`
    - `is_applicable`
    - `validation_notes`
    - `patch`
    - `repaired_plan_snapshot`

- `PlanRepairPatch`
  - 不是任意 JSON patch，而是有限字段集合

action space 被限制为：

- `KEEP_REMAINING`
- `DROP_BLOCKED_STEP`
- `REORDER_REMAINING_STEPS`
- `REPLACE_STEP`
- `TRUNCATE_AFTER_CURRENT`
- `APPEND_RECOVERY_STEP`
- `NO_REPAIR`

这个有限 action space 是有意设计的。它避免 repair 滑向“planner 想怎么改就怎么改”，更适合论文中表述为 bounded repair space。

## 5. Repair Validation

repair validator 位于 `core/plan_repair.py::validate_plan_repair(...)`。

它做了以下 deterministic checks：

1. repair action 是否在允许集合中
2. 是否试图修改已经 `COMPLETED` 的 step
3. repaired residual plan 是否依然只使用已知工具
4. 是否引入未知 token
5. step 声明的 `depends_on` / `produces` 是否与 canonical tool semantics 冲突
6. repaired residual workflow 是否真正可执行
   - validator 会重新构造 residual steps
   - 使用当前 available tokens + completed steps already produced tokens
   - 调用 `validate_plan_steps(...)`
   - 若 residual workflow 仍是 `PARTIAL` / `INVALID`，repair 直接拒绝

这部分保证了几个关键论文主张：

- repair 不是 prompt improvisation
- repair 不能“假装解决” blocked 根因
- completed execution history 不会被重写

例如：

- `APPEND_RECOVERY_STEP` 允许把恢复步骤追加到 residual workflow
- 但如果追加后的 residual 仍然不合法，validator 会拒绝它

## 6. Router Integration

真实控制流仍然收敛在 `core/router.py::_state_handle_executing()`。

### A. deviation path

每次工具执行前：

1. `_reconcile_plan_before_execution(...)`
2. 若出现 `PLAN_DEVIATION`
3. `_should_attempt_plan_repair(...)`
4. 若 policy 允许：
   - `_attempt_plan_repair(...)`
   - 其中包含：
     - `_generate_plan_repair(...)` -> `llm.chat_json(...)`
     - `validate_plan_repair(...)`
     - `_apply_plan_repair(...)`
5. 当前 turn 停在 repair 结果说明，不继续执行该 deviated tool

### B. dependency blocked path

每次工具执行前依赖检查：

1. `_validate_execution_dependencies(...)`
2. 若 fail：
   - 先记录 `DEPENDENCY_BLOCKED`
   - 先把 step 标为 `BLOCKED`
   - 再进入 `_should_attempt_plan_repair(...)`
   - 如果 repair 合法，就更新 residual plan
   - 如果 repair 失败，就保留原 plan
3. 当前 turn 结束

### C. 为什么没有做 auto-completion

因为本轮目标不是 scheduler。

repair 的职责仅限于：

- 更新 residual plan
- 更新 plan state / repair history
- 生成可解释响应

它不负责：

- 自动补跑缺失依赖
- 自动重入 executor 去执行新 patch
- 自动扩完整子图

因此当前系统仍然是 bounded repair framework，而不是 workflow scheduler。

## 7. Trace Extensions

新增 trace step types：

- `PLAN_REPAIR_TRIGGERED`
- `PLAN_REPAIR_PROPOSED`
- `PLAN_REPAIR_APPLIED`
- `PLAN_REPAIR_FAILED`
- `PLAN_REPAIR_SKIPPED`

写入路径：

- `PLAN_REPAIR_TRIGGERED`
  - `_attempt_plan_repair(...)` 开始时

- `PLAN_REPAIR_PROPOSED`
  - repair JSON parse 成 `PlanRepairDecision` 并完成 deterministic validation 后

- `PLAN_REPAIR_APPLIED`
  - `_apply_plan_repair(...)` 成功把 repaired plan 写回 `state.plan` 后

- `PLAN_REPAIR_FAILED`
  - JSON generation error
  - invalid decision
  - illegal residual patch
  - completed-step mutation attempt

- `PLAN_REPAIR_SKIPPED`
  - selective policy 明确决定不 repair
  - 或 planner 返回 `NO_REPAIR`

这些 trace 对论文有价值，因为它们能明确区分：

- deviation happened but repair was skipped
- repair was triggered and proposed
- proposal was invalid and rejected
- proposal was applied to residual plan

这比只记录“最后执行了什么工具”更接近 framework-level audit artifact。

## 8. Tests

本轮实际运行了以下测试：

```bash
pytest -q tests/test_router_state_loop.py tests/test_tool_dependencies.py tests/test_task_state.py tests/test_trace.py tests/test_context_store_integration.py
```

结果：

- `79 passed`

另外分阶段跑过：

```bash
pytest -q tests/test_tool_dependencies.py tests/test_task_state.py tests/test_trace.py
pytest -q tests/test_router_state_loop.py
pytest -q tests/test_context_store_integration.py
```

关键新增覆盖：

- `tests/test_router_state_loop.py`
  - dependency blocked -> bounded repair applied
  - mild ahead-of-plan deviation -> repair skipped
  - plan exhausted deviation -> repair triggered and stops before unplanned execution
  - invalid repair -> original plan preserved + `PLAN_REPAIR_FAILED`

- `tests/test_tool_dependencies.py`
  - validator accepts legal residual repair
  - validator rejects illegal hotspot residual
  - validator rejects completed-step mutation

- `tests/test_task_state.py`
  - repaired plan serialization
  - residual next pending step observability

- `tests/test_trace.py`
  - repair trace formatting

## 9. Known Limitations

- no dependency auto-completion
- no full replanning of the whole workflow
- no user approval/editing flow
- no resume persistence
- repair does not auto-execute new steps
- still not a rigid plan executor or workflow scheduler

另外还有一个有意保留的边界：

- 当前 repair validator 要求 repaired residual workflow 自身可通过 deterministic validation
- 这会让 repair 倾向于最小、保守、可解释
- 但也意味着它不会接受“先保留一个已知仍不可执行的尾部，等以后再说”的宽松 patch

这个选择更有利于论文叙事中的 legality claim，但会牺牲一部分产品式灵活性。

## 10. Suggested Next Step

最自然的下一步是做 **repair-aware next-turn continuation**：

- 不做 persistence
- 不做 scheduler
- 只让下一轮 state loop 在已有 repaired residual plan 基础上继续决策
- 并把 `repair_history` / `next_pending_step` 更明确地注入下一轮 tool-selection context

这样可以把当前的“单 turn 内 bounded repair”推进成“跨连续 turn 的 bounded workflow adaptation”，同时仍然不走向 full orchestration rewrite。
