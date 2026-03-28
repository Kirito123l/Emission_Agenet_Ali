# P0I2 Input Completion Flow Report

## 1. Summary

本轮在现有 unified readiness gating 之上，实现了一个 bounded structured data-completion flow。

完成的核心链路是：

- `repairable` action 不再只返回 repair hint
- router 会把支持的 repairable case 转成正式 `InputCompletionRequest`
- state 进入 `TaskStage.NEEDS_INPUT_COMPLETION`
- 下一轮用户通过 bounded reply 形成 `InputCompletionDecision`
- decision 被写入 execution-side `input_completion_overrides`
- router 在同一个 live session/router 生命周期内恢复当前任务上下文继续决策

这轮达到目标，但仍然保持 bounded：

- 没有 durable persistence
- 没有 scheduler / auto-completion
- 没有 general conversational slot-filling
- 只优先支持高价值 repairable reason code：`missing_required_field`、`missing_geometry`

## 2. Files Changed

- [core/input_completion.py](/home/kirito/Agent1/emission_agent/core/input_completion.py)
  - 新增正式 completion IR、option schema、decision schema、parser、prompt formatter。
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py)
  - 把 repairable pre-exec gating 接成 `NEEDS_INPUT_COMPLETION`。
  - 新增 live input completion bundle、reply parsing、override apply、resume guidance。
- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py)
  - 新增 `TaskStage.NEEDS_INPUT_COMPLETION`。
  - 新增 active request / latest decision / overrides observability。
- [core/readiness.py](/home/kirito/Agent1/emission_agent/core/readiness.py)
  - readiness assessment 现在能看到 `input_completion_overrides`，补齐后会重新用同一套 readiness 逻辑评估 action。
- [skills/macro_emission/excel_handler.py](/home/kirito/Agent1/emission_agent/skills/macro_emission/excel_handler.py)
  - Excel/CSV 读入路径新增对 bounded completion override 的最小消费：
    - `uniform_scalar`
    - `source_column_derivation`
- [tools/macro_emission.py](/home/kirito/Agent1/emission_agent/tools/macro_emission.py)
  - 把 `_input_completion_overrides` 传进 file input path，并在 `links_data` 层应用统一值 / 受控 derivation。
- [core/trace.py](/home/kirito/Agent1/emission_agent/core/trace.py)
  - 新增 input completion trace taxonomy 和 formatter。
- [config.py](/home/kirito/Agent1/emission_agent/config.py)
  - 新增 input completion feature flag 和 bounded option config。
- [tests/test_input_completion.py](/home/kirito/Agent1/emission_agent/tests/test_input_completion.py)
  - 新增 completion IR / parser / Excel override 消费测试。
- [tests/test_input_completion_transcripts.py](/home/kirito/Agent1/emission_agent/tests/test_input_completion_transcripts.py)
  - 新增 transcript-style regression。
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py)
  - 新增 / 更新 state-loop integration tests。
- [tests/test_task_state.py](/home/kirito/Agent1/emission_agent/tests/test_task_state.py)
  - 新增 completion observability tests。
- [tests/test_trace.py](/home/kirito/Agent1/emission_agent/tests/test_trace.py)
  - 新增 completion trace formatting tests。
- [tests/test_config.py](/home/kirito/Agent1/emission_agent/tests/test_config.py)
  - 新增 config default assertions。

## 3. Completion Flow Design

### Completion IR

`[core/input_completion.py](/home/kirito/Agent1/emission_agent/core/input_completion.py)` 定义了：

- `InputCompletionReasonCode`
- `InputCompletionOptionType`
- `InputCompletionDecisionType`
- `InputCompletionOption`
- `InputCompletionRequest`
- `InputCompletionDecision`
- `InputCompletionParseResult`

这些对象都支持稳定 `to_dict()` / `from_dict()`，不再靠 router 里的散乱 dict 传递。

### Supported reason codes

这一轮正式接通的 reason code 是：

- `missing_required_field`
- `missing_geometry`

代码结构允许以后扩展 `missing_meteorology`，但这轮没有把它接成完整 flow。

### Option generation logic

在 `[core/router.py](/home/kirito/Agent1/emission_agent/core/router.py)` 的 `_build_input_completion_request()` 中：

- `missing_required_field`
  - `provide_uniform_value`
  - `use_derivation`，仅当 `missing_field_diagnostics.required_field_statuses[*].derivation_candidates` 只有一个受控候选时才出现
  - `upload_supporting_file`
  - `pause`
- `missing_geometry`
  - `upload_supporting_file`
  - `pause`

option generation 是 rule-driven 的，不让 LLM 自由发明补救方式。

### Parser strategy

parser 在 `[core/input_completion.py](/home/kirito/Agent1/emission_agent/core/input_completion.py)` 中，默认只做 deterministic parsing：

- 选项序号
- 选项 label / alias
- 数值 reply，例如 `1500`、`全部设为1500`
- upload + `file_path`
- `暂停`

没有引入 LLM-based completion parser。

### Why this is bounded remediation

这轮不是 general dialogue manager，因为：

- 只对 `repairable` action 触发
- 只支持有限 reason code
- option set 是有限枚举
- parser 只接受 bounded reply surface
- completion 结果只落到有限 override schema

## 4. Router Integration

### repairable action 如何进入 NEEDS_INPUT_COMPLETION

主接入点仍在 `[core/router.py](/home/kirito/Agent1/emission_agent/core/router.py)` 的 `_state_handle_executing()`。

控制流现在是：

1. tool selection 完成
2. `_prepare_tool_arguments()`
3. `_assess_selected_action_readiness()`
4. 如果 action 是 `repairable`
5. `_build_input_completion_request(...)`
6. `_activate_input_completion_state(...)`
7. 当前 turn 结束，不执行原工具

注意：

- 只有支持的 repairable reason code 才会进 completion flow
- 其他 repairable 仍然保持解释型短路
- result-token prerequisite 缺失仍然优先走原有 dependency gate / bounded repair 逻辑

### 下一轮如何解析 completion reply

在 `_state_handle_input()` 早期：

- 先 `_apply_live_input_completion_state(state)`
- 如果存在 active request，走 `_handle_active_input_completion(...)`

`_handle_active_input_completion(...)` 会处理：

- explicit new-task override
- bounded completion reply parsing
- pause
- ambiguous reply retry
- completion decision apply
- residual workflow resume

### completion 如何恢复当前任务上下文

恢复不是通过 persistence，而是通过 live router bundle：

- `_save_active_input_completion_bundle(...)`
- `_build_input_completion_resume_decision(...)`
- `_inject_input_completion_guidance(...)`

如果请求发生在 residual workflow 中：

- plan snapshot / repair history / blocked info 会保留
- completion 成功后会构造 `ContinuationDecision(signal="input_completion_resume")`

如果没有 residual plan：

- system guidance 会把 original task summary + applied overrides 注入下一轮 tool-selection context
- 这样 reply `1500` 不会被当成独立新任务

### 为什么这一轮没有做 persistence / scheduler

因为这一轮目标是 bounded remediation，不是 workflow engine：

- 没有 save/load
- 没有跨重启恢复
- 没有 auto-execution
- 没有 dependency auto-completion

## 5. Execution-Side Overrides

### Override 写入位置

`[core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py)` 新增：

- `active_input_completion`
- `latest_input_completion_decision`
- `input_completion_overrides`

### 当前支持的 override 类型

这一轮最小接通了：

- uniform field override
  - 例如 `traffic_flow_vph = 1500`
- source-column derivation override
  - 例如 `traffic_flow_vph <- daily_traffic`
- supporting spatial file reference
  - 例如 `geometry_support.file_ref = /tmp/roads.geojson`

### 后续 execution 如何消费

router 在 `_prepare_tool_arguments()` 中把 `state.input_completion_overrides` 注入 `_input_completion_overrides`。

消费点目前接到了宏观排放文件输入链：

- `[skills/macro_emission/excel_handler.py](/home/kirito/Agent1/emission_agent/skills/macro_emission/excel_handler.py)`
  - `read_links_from_excel(..., completion_overrides=...)`
  - 缺失 required field 时允许：
    - `uniform_scalar`
    - `source_column_derivation`
- `[tools/macro_emission.py](/home/kirito/Agent1/emission_agent/tools/macro_emission.py)`
  - `_read_from_zip(...)`
  - `_read_excel_from_zip(...)`
  - `_apply_input_completion_overrides_to_links(...)`

几何 supporting file 这一轮只做到：

- 正式进入 state / router context
- 进入下一轮 file grounding / readiness / routing context

没有在这轮自动触发“重算上游结果 + 再渲染地图”。

## 6. Trace Extensions

`[core/trace.py](/home/kirito/Agent1/emission_agent/core/trace.py)` 新增：

- `INPUT_COMPLETION_REQUIRED`
- `INPUT_COMPLETION_CONFIRMED`
- `INPUT_COMPLETION_REJECTED`
- `INPUT_COMPLETION_FAILED`
- `INPUT_COMPLETION_APPLIED`
- `INPUT_COMPLETION_PAUSED`

写入路径：

- repairable action 进入 completion flow
- 用户回复被成功解析
- override 被写入 state
- reply 解析失败
- 用户明确暂停
- active completion 被新任务 override

这些 trace 对论文有价值，因为它们把：

- repairable detection
- structured remediation request
- user decision parsing
- execution-side override apply
- residual workflow resume

变成了正式可审计 artifact，而不是 prompt 层的隐式行为。

## 7. Tests

运行了：

```bash
python -m py_compile core/input_completion.py core/task_state.py core/readiness.py core/router.py core/trace.py skills/macro_emission/excel_handler.py tools/macro_emission.py tests/test_input_completion.py tests/test_input_completion_transcripts.py tests/test_router_state_loop.py tests/test_task_state.py tests/test_trace.py tests/test_config.py
pytest -q tests/test_input_completion.py tests/test_input_completion_transcripts.py tests/test_router_state_loop.py tests/test_task_state.py tests/test_trace.py tests/test_config.py
pytest -q tests/test_readiness_gating.py tests/test_capability_aware_synthesis.py tests/test_input_completion.py tests/test_input_completion_transcripts.py tests/test_router_state_loop.py tests/test_task_state.py tests/test_trace.py tests/test_config.py
```

结果：

- `99 passed, 4 warnings`
- `111 passed, 4 warnings`

关键新增覆盖：

- repairable action 正式进入 `NEEDS_INPUT_COMPLETION`
- uniform scalar completion parse / apply
- pause path
- geometry missing request path
- active completion 被显式新任务覆盖
- residual plan 在 completion success 后恢复
- execution-side macro file input 消费 uniform override
- input completion trace formatting
- TaskState observability

## 8. Known Limitations

- no durable persistence / resume
- no general conversational slot-filling
- only bounded high-value repairable reason codes supported
- no scheduler / auto-completion was introduced
- completion only works within live router/session lifecycle

另外，本轮几何补救仍然是保守的：

- supporting file 可以进入 file grounding / readiness context
- 但不会自动重算上游结果或自动继续地图渲染

这是有意保守，避免这轮从 bounded remediation 漂移成 scheduler。

## 9. Suggested Next Step

最自然的下一步是：

**把 `missing_geometry` completion 接到一个受控的 “supporting-file-aware re-grounding → upstream recompute recommendation” 层。**

原因：

- 这轮已经把 geometry upload 变成正式 completion request 和 live override
- 但它还没有进入一个明确的、受控的 “上传后如何恢复空间链” 机制
- 下一轮最值得做的是把这个恢复路径 formalize，而不是继续扩 reason code 数量
