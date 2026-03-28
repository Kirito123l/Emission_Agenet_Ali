# P1A: Continuation Prompt Calibration + Bounded Continuation Evaluation Harness

## 1. Summary

本轮实现没有继续扩展新的 workflow 控制机制，而是把现有 repair-aware continuation 做成了可比较、可评测、可复现的实验设施。核心结果有两部分：

- 在 [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py) 中，把 continuation guidance 变成了有限 prompt variant 集合：`goal_heavy`、`next_step_heavy`、`balanced_repair_aware`
- 新增 repo 内 continuation evaluation harness：
  - case schema: [evaluation/continuation/samples.jsonl](/home/kirito/Agent1/emission_agent/evaluation/continuation/samples.jsonl)
  - runner: [evaluation/eval_continuation.py](/home/kirito/Agent1/emission_agent/evaluation/eval_continuation.py)
  - wrapper: [scripts/eval/run_continuation_eval.py](/home/kirito/Agent1/emission_agent/scripts/eval/run_continuation_eval.py)

这轮的目标是把 “repaired residual plan influences the next turn” 从功能描述推进到论文可实验验证的状态。实现结果达到了这个目标，但评测默认仍然是 deterministic mock selector，不是 live-model benchmark。

## 2. Files Changed

- [config.py](/home/kirito/Agent1/emission_agent/config.py)
  - 新增 `continuation_prompt_variant` 配置项，对 continuation prompt calibration 做 feature-level 切换。
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py)
  - 新增有限 variant 集合和 `_resolve_continuation_prompt_variant()`
  - 将 `_build_residual_plan_summary_for_prompt()` 改为 variant-aware
  - 在 continuation decision / injection trace 中暴露 `prompt_variant`
- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py)
  - `ContinuationDecision` 新增 `prompt_variant`，让 prompt calibration 能进入 `TaskState.to_dict()` 可观察面。
- [evaluation/continuation/samples.jsonl](/home/kirito/Agent1/emission_agent/evaluation/continuation/samples.jsonl)
  - 新增 continuation evaluation case schema 实例集，覆盖 repaired、blocked、override、ambiguous、completed residual、goal mismatch 等场景。
- [evaluation/eval_continuation.py](/home/kirito/Agent1/emission_agent/evaluation/eval_continuation.py)
  - 新增 continuation evaluation harness、聚合指标、结果写盘与 Markdown summary 生成。
- [scripts/eval/run_continuation_eval.py](/home/kirito/Agent1/emission_agent/scripts/eval/run_continuation_eval.py)
  - 提供与现有仓库脚本风格一致的命令行入口。
- [evaluation/README.md](/home/kirito/Agent1/emission_agent/evaluation/README.md)
  - 补充 continuation evaluation 的入口与输出说明。
- [tests/test_continuation_eval.py](/home/kirito/Agent1/emission_agent/tests/test_continuation_eval.py)
  - 新增 calibration / harness 回归测试。

## 3. Continuation Prompt Calibration

prompt calibration 没有开放成任意模板系统，而是限制成 3 个论文可消融的 variant：

- `goal_heavy`
  - 更强调 original goal 和 residual workflow summary
  - 只弱提示 next pending step
- `next_step_heavy`
  - 明确把 next pending step 写成 highest priority
  - 强调 “prefer the immediate next legal residual step”
- `balanced_repair_aware`
  - 同时保留 goal、residual steps、latest repair summary、latest blocked reason、next pending step

真实落点在 [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py)：

- `_resolve_continuation_prompt_variant()`
- `_build_residual_plan_summary_for_prompt(...)`
- `_inject_continuation_guidance(...)`

这样做的目的是把 prompt 变化空间约束在有限、可解释、可比较的范围内，避免把论文消融做成无限 prompt engineering。

## 4. Evaluation Harness Design

continuation harness 没有重写 router，也没有构造 persistence/resume 系统，而是直接复用现有 continuation 控制面：

- live residual bundle
- `_should_continue_residual_plan(...)`
- `_activate_live_continuation_state(...)`
- `_inject_continuation_guidance(...)`

具体实现位于 [evaluation/eval_continuation.py](/home/kirito/Agent1/emission_agent/evaluation/eval_continuation.py)。

case schema 以 JSONL 表达，每个 case 至少包含：

- `case_id`
- `category`
- `description`
- `prior_state`
- `current_user_input`
- `expected_continuation_decision`
- `expected_new_task_override`
- `expected_next_tool`
- `expected_trace_markers`
- `notes`

`prior_state` 不是完整 snapshot restore，而是 continuation 决策所需的最小 live-state surface：

- residual `plan`
- `repair_history`
- `blocked_info`
- `available_tokens`
- `stale_tokens`
- `file_path`

harness 默认采用 deterministic mock tool selector，但它不是脱离 router 的纯外部规则器。runner 会调用真实 `_state_handle_input()`，让 variant-aware continuation guidance 真实注入到 assemble 后的 tool-selection context，然后由 mock selector 对 prompt 结果做受控评估。

## 5. Metrics

本轮把 continuation evaluation 指标正式落成 aggregation，而不是散落打印。当前输出包括：

- `continuation_decision_accuracy`
- `new_task_override_precision`
- `safe_continuation_recall`
- `next_step_alignment_rate`
- `blocked_after_continuation_rate`
- `trace_completeness`
- `repair_aware_continuation_success_rate`

按 variant 输出：

- `continuation_case_results.jsonl`
- `continuation_metrics.json`
- `continuation_summary.md`

variant-set 对比还会生成：

- `continuation_variant_comparison.json`
- `continuation_variant_comparison.md`

这些输出都写在 `evaluation/logs/...` 下，格式适合直接进入论文实验草稿或 case-study 截图。

## 6. Router Integration

router 主逻辑没有被重写。改动点只在 continuation guidance 构造和 observability：

- `_build_residual_plan_summary_for_prompt()` 现在根据 variant 生成不同的 residual summary
- `_should_continue_residual_plan()` 把 `prompt_variant` 放进 `ContinuationDecision`
- `_record_continuation_decision()` 和 `_inject_continuation_guidance()` 会把 variant 一并写入 trace summary

因此主路径仍然是：

1. `_state_handle_input()`
2. 读取 live residual bundle
3. continuation decision
4. continuation guidance injection
5. 正常 `chat_with_tools()`

没有新增 scheduler 路径，也没有自动执行 residual steps。

## 7. Tests

本轮新增和运行的重点测试：

- [tests/test_continuation_eval.py](/home/kirito/Agent1/emission_agent/tests/test_continuation_eval.py)
  - 验证 prompt variant 输出差异
  - 验证 evaluation runner 写出 JSONL / JSON / Markdown
  - 验证不同 variant 的 next-step alignment 可比较
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py)
  - 复用既有 continuation regression，确认新配置化没有破坏 live continuation 控制流
- [tests/test_task_state.py](/home/kirito/Agent1/emission_agent/tests/test_task_state.py)
  - 继续覆盖 continuation observability surface
- [tests/test_trace.py](/home/kirito/Agent1/emission_agent/tests/test_trace.py)
  - 回归 continuation trace formatting
- [tests/test_config.py](/home/kirito/Agent1/emission_agent/tests/test_config.py)
  - 回归 config surface

## 8. Known Limitations

- no durable persistence / resume
- no auto-execution of residual steps
- no dependency auto-completion
- no user approval/editing flow
- still not a full scheduler or rigid executor
- evaluation harness is deterministic/mock-friendly by default, not a live-model benchmark harness
- current next-step alignment numbers measure bounded continuation behavior under a controlled selector, not final paper-grade model performance

这一点对论文叙事有影响：当前 harness 已经能支持消融和 case-study，但如果要写成最终主实验，后续还需要补一个可批量跑真实模型的同构 runner。

## 9. Suggested Next Step

最自然的下一步是：在不改变当前 case schema 和 aggregation surface 的前提下，给 continuation harness 增加一个可选的 live-model execution mode，用同一套 cases / metrics 对比 deterministic selector 与真实 LLM tool selection 的差异。
