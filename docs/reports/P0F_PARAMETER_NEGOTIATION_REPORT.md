# P0F Parameter Negotiation Report

## 1. Summary

本轮实现了一个正式的、bounded 的参数协商机制，把此前“标准化失败后统一进入 clarification”的路径拆成了独立的方法组件：

- executor-side standardization 现在不仅会在 `abstain + suggestions` 时失败，也能在 `fuzzy/llm/default` 低置信度但仍有候选集时显式抛出 negotiation-eligible error
- state loop 新增 `TaskStage.NEEDS_PARAMETER_CONFIRMATION`
- 新增正式 negotiation IR：`NegotiationCandidate`、`ParameterNegotiationRequest`、`ParameterNegotiationDecision`、`ParameterNegotiationParseResult`
- router 在 execution-stage standardization error 后会分流到 parameter negotiation，而不是一律进入 generic clarification
- 下一轮用户确认会被 deterministic parser 解析，并转成 execution-side parameter lock
- confirmed lock 会在后续执行中覆盖同名工具参数，避免再次 fuzzy/LLM 猜测
- negotiation 与已有 residual continuation 兼容：若协商发生在 residual workflow 上，确认后的下一轮会恢复 repaired residual plan guidance，而不是把确认 turn 当成全新任务

目标达成情况：已达到。本轮实现的是 bounded parameter negotiation mechanism，不是 general clarification chatbot，也没有引入 persistence、scheduler 或 auto-execution。

## 2. Files Changed

- [core/parameter_negotiation.py](/home/kirito/Agent1/emission_agent/core/parameter_negotiation.py)
  - 新增 negotiation IR 和 deterministic parser。
  - 负责候选项表示、confirmation decision 表示、`index / label / canonical value / none-of-above` 解析，以及结构化 prompt 文本格式化。

- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py)
  - 新增 `TaskStage.NEEDS_PARAMETER_CONFIRMATION`。
  - `ParamEntry` 增加 `locked`、`lock_source`、`confirmation_request_id`。
  - `TaskState` 增加 `active_parameter_negotiation`、`latest_parameter_negotiation_decision`、`apply_parameter_lock()`、`get_parameter_locks_summary()`。
  - `to_dict()` 现在暴露 active negotiation、parameter locks、latest confirmed parameter。

- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py)
  - 新增 live in-memory negotiation bundle。
  - 在 `_state_handle_executing()` 中把 standardization error 分流为 negotiation vs clarification。
  - 在 `_state_handle_input()` 早期加入 active confirmation reply handling。
  - 新增 parameter confirmation guidance / lock guidance 注入。
  - `_prepare_tool_arguments()` 现在会对 locked parameters 做 execution-side override。
  - confirmation 成功后可恢复 residual plan continuation。

- [core/trace.py](/home/kirito/Agent1/emission_agent/core/trace.py)
  - 新增 negotiation trace taxonomy 和 user-friendly formatting。

- [core/executor.py](/home/kirito/Agent1/emission_agent/core/executor.py)
  - `StandardizationError` 现在携带 `param_name`、`original_value`、`negotiation_eligible`、`trigger_reason`。
  - executor result surface 把这些字段传给 router。

- [services/standardization_engine.py](/home/kirito/Agent1/emission_agent/services/standardization_engine.py)
  - 新增 low-confidence negotiation trigger policy。
  - `BatchStandardizationError` 现在支持 `negotiation_eligible` / `trigger_reason`。
  - 新增 `get_param_type()`、`get_candidate_aliases()`、`resolve_candidate_value()` 供 router 构建 negotiation candidates。
  - `standardize_batch()` 现在能在低置信度 fuzzy/llm/default 命中时主动要求 parameter confirmation。

- [config.py](/home/kirito/Agent1/emission_agent/config.py)
  - 新增 `ENABLE_PARAMETER_NEGOTIATION`
  - 新增 `PARAMETER_NEGOTIATION_CONFIDENCE_THRESHOLD`
  - 新增 `PARAMETER_NEGOTIATION_MAX_CANDIDATES`
  - 并将这些配置透传给 `standardization_config`

- [tests/test_parameter_negotiation.py](/home/kirito/Agent1/emission_agent/tests/test_parameter_negotiation.py)
  - 新增 negotiation parser / trigger policy / candidate resolution 测试。

- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py)
  - 新增 state-loop negotiation trigger、confirmation、none-of-above、ambiguous retry、continuation compatibility 测试。

- [tests/test_task_state.py](/home/kirito/Agent1/emission_agent/tests/test_task_state.py)
  - 新增 parameter lock / active negotiation observability 测试。

- [tests/test_trace.py](/home/kirito/Agent1/emission_agent/tests/test_trace.py)
  - 新增 negotiation trace formatting 测试。

- [tests/test_config.py](/home/kirito/Agent1/emission_agent/tests/test_config.py)
  - 新增 parameter negotiation config default coverage。

## 3. Negotiation Design

### trigger policy

触发策略不是“所有 standardization failure 都进入 negotiation”，而是明确三分：

- auto accept
  - `exact` / `alias` / `passthrough` / `local_model` 等高确定性结果直接接受。
  - 不进入 negotiation。

- negotiate
  - `services/standardization_engine.py::standardize_batch()` 在以下情况抛出 `BatchStandardizationError(... negotiation_eligible=True ...)`
  - `result.success == False` 且有 candidate/suggestions
  - `result.success == True` 但 `strategy in {fuzzy, llm, default}` 且 `confidence < PARAMETER_NEGOTIATION_CONFIDENCE_THRESHOLD`
  - 这使 negotiation 不再只覆盖“完全失败”，也覆盖“有 top1，但不足以安全自动采纳”的情况。

- clarification
  - 无 candidate 集，或 negotiation 被 `none_of_above` 否决后仍没有合法值。
  - 此时仍走 `NEEDS_CLARIFICATION`，而不是继续留在 parameter confirmation。

### negotiation IR

Negotiation IR 定义在 [core/parameter_negotiation.py](/home/kirito/Agent1/emission_agent/core/parameter_negotiation.py)：

- `NegotiationCandidate`
  - 表示一个 bounded candidate，包含 `index`、`normalized_value`、`display_label`、`confidence`、`strategy`、`reason`、`aliases`

- `ParameterNegotiationRequest`
  - 表示一次正式 parameter confirmation request，包含：
  - `request_id`
  - `parameter_name`
  - `raw_value`
  - `confidence`
  - `trigger_reason`
  - `tool_name`
  - `arg_name`
  - `strategy`
  - `candidates`

- `ParameterNegotiationDecision`
  - 表示用户确认结果：
  - `decision_type in {confirmed, none_of_above, ambiguous_reply}`
  - `selected_index`
  - `selected_value`
  - `user_reply`

- `ParameterNegotiationParseResult`
  - 表示 parser 输出：
  - `is_resolved`
  - `decision`
  - `needs_retry`
  - `error_message`

这些对象都支持 `to_dict()` / `from_dict()`，不是 trace 中的临时 dict。

### confirmation parsing

parser 走 deterministic bounded path，不使用 LLM：

- index parse
  - `1`
  - `选第2个`
  - `第二个`

- candidate match
  - canonical normalized value
  - display label
  - suggestion label 中解析出的 alias，例如 `乘用车 (Passenger Car)` 的 `乘用车` / `Passenger Car`

- none-of-above
  - `都不对`
  - `none`
  - `none of the above`

特殊处理：

- 多索引/多候选同时出现，例如 `第一个还是第二个`
  - 不会误锁定为第一个
  - 会被解析为 ambiguous reply，并保持在 `NEEDS_PARAMETER_CONFIRMATION`

### parameter lock 机制

lock 落在 `TaskState.parameters[param_name] -> ParamEntry` 上：

- `locked=True`
- `lock_source="user_confirmation"`
- `confirmation_request_id=<request_id>`
- `normalized=<confirmed canonical value>`

执行约束落点在 [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py)：

- `_prepare_tool_arguments(..., state=state)`
  - 如果 `state.parameters[param_name].locked == True`
  - 且工具调用里已经带了同名参数
  - 则用 locked canonical value 覆盖 LLM 提供的值

因此 confirmed value 不再只是文本历史，而是 execution-side binding constraint。

这条闭环支持论文里的“参数强约束”叙事，因为：

- ambiguity 先被结构化暴露
- user confirmation 被正式解析
- confirmed canonical value 会进入可观测状态
- 并在后续执行参数中被强制复用

## 4. Router Integration

### standardization error 如何分流到 negotiation

执行链路是：

1. `services/standardization_engine.py::standardize_batch()`
2. `core/executor.py::_standardize_arguments()`
3. `core/executor.py::execute()`
4. `core/router.py::_state_handle_executing()`

router 的关键分流逻辑现在是：

- 若 `result.error_type == "standardization"` 且 `_build_parameter_negotiation_request(...)` 成功
  - 调用 `_activate_parameter_confirmation_state(...)`
  - 进入 `TaskStage.NEEDS_PARAMETER_CONFIRMATION`
  - 保存 active live negotiation bundle
  - 写 `PARAMETER_NEGOTIATION_REQUIRED`
  - 当前 turn 停止

- 否则
  - 仍走现有 `NEEDS_CLARIFICATION`

### next turn confirmation 如何进入 state loop

在 [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py) 的 `_state_handle_input()` 早期，新增：

- `_apply_live_parameter_state(state)`
  - 把 live bundle 中的 locked params / active request / latest confirmed decision 读回当前 turn `TaskState`

- `_handle_active_parameter_confirmation(state, trace_obj)`
  - 只在 active request 存在时运行
  - 若输入像 confirmation attempt，则调用 `_parse_parameter_confirmation_reply()`

confirmation outcome:

- confirmed
  - `state.apply_parameter_lock(...)`
  - live bundle 写入 `locked_parameters`
  - 写 `PARAMETER_NEGOTIATION_CONFIRMED`
  - 若 negotiation snapshot 中带 residual plan，则恢复 residual continuation decision
  - 本轮继续正常 tool-selection / execution

- none_of_above
  - 清掉 active request
  - 转 `NEEDS_CLARIFICATION`
  - 写 `PARAMETER_NEGOTIATION_REJECTED`

- ambiguous reply
  - 保持 `NEEDS_PARAMETER_CONFIRMATION`
  - 写 `PARAMETER_NEGOTIATION_FAILED`
  - 重新给结构化候选 prompt

### 如何与 continuation / residual plan 兼容

compatibility 的关键不是 persistence，而是 live bundle。

router 新增了 `_live_parameter_negotiation`，其中保存：

- `active_request`
- `parameter_snapshot`
- `locked_parameters`
- `latest_confirmed_parameter`
- `file_path`
- `plan`
- `repair_history`
- `blocked_info`
- `latest_repair_summary`
- `residual_plan_summary`
- `original_goal`
- `original_user_message`

因此 negotiation 如果发生在 residual workflow 上：

- trigger turn 结束时，parameter negotiation bundle 会保留 residual plan snapshot
- confirm turn 中 `_build_parameter_confirmation_resume_decision(...)` 会把 residual plan 恢复进当前 `TaskState`
- 然后继续走已有 continuation injection 逻辑

这使参数协商不会把 repaired residual workflow 冲掉，也没有把 router 改成 scheduler。

## 5. Trace Extensions

新增 trace step types 在 [core/trace.py](/home/kirito/Agent1/emission_agent/core/trace.py)：

- `PARAMETER_NEGOTIATION_REQUIRED`
- `PARAMETER_NEGOTIATION_CONFIRMED`
- `PARAMETER_NEGOTIATION_REJECTED`
- `PARAMETER_NEGOTIATION_FAILED`

写入路径：

- `PARAMETER_NEGOTIATION_REQUIRED`
  - `_state_handle_executing()` 中 standardization error 分流到 negotiation 时

- `PARAMETER_NEGOTIATION_CONFIRMED`
  - `_handle_active_parameter_confirmation()` 中用户确认成功并应用 lock 时

- `PARAMETER_NEGOTIATION_REJECTED`
  - `none_of_above` 转 clarification
  - 或 active negotiation 被 explicit new task supersede 时

- `PARAMETER_NEGOTIATION_FAILED`
  - confirmation reply 无法唯一解析，需要 retry 时

为什么这些 trace 对论文有用：

- 能区分“标准化失败”和“进入 bounded negotiation”
- 能区分“候选被确认”与“候选被拒绝”
- 能明确看到 lock 是否 applied
- 能对 ambiguity case 做 case-study 和 failure analysis，而不是只看最终自然语言回复

## 6. Tests

本轮实际运行了以下测试：

- `pytest -q tests/test_router_state_loop.py tests/test_parameter_negotiation.py tests/test_task_state.py tests/test_trace.py tests/test_standardization_engine.py tests/test_context_store_integration.py tests/test_config.py`
  - 结果：`121 passed, 4 warnings`

另外分阶段单独跑过：

- `pytest -q tests/test_parameter_negotiation.py tests/test_task_state.py tests/test_trace.py tests/test_config.py`
  - `51 passed, 4 warnings`

- `pytest -q tests/test_standardization_engine.py`
  - `33 passed`

- `pytest -q tests/test_context_store_integration.py`
  - `11 passed`

关键新增覆盖：

- `tests/test_router_state_loop.py`
  - low-confidence candidate -> `NEEDS_PARAMETER_CONFIRMATION`
  - next turn confirmation by index
  - none-of-above -> clarification
  - ambiguous reply retry
  - residual continuation + negotiation coexistence

- `tests/test_parameter_negotiation.py`
  - index / label / none-of-above parser
  - bounded confirmation-attempt detection
  - low-confidence LLM result -> negotiation-eligible batch error
  - high-confidence alias auto accept
  - display label -> canonical resolution

- `tests/test_task_state.py`
  - parameter lock observability
  - active negotiation request observability
  - `NEEDS_PARAMETER_CONFIRMATION` terminal semantics

- `tests/test_trace.py`
  - negotiation trace formatting

## 7. Known Limitations

- no durable persistence / resume
  - negotiation bundle 和 parameter locks 只存在于 live router/session 生命周期内

- no open-ended conversational negotiation
  - parser 只支持 bounded reply formats，不是 general dialogue negotiation agent

- no auto-execution after confirmation
  - confirmation 成功后只恢复正常 state loop 决策，不会自动执行整条 workflow

- no dependency auto-completion
  - 参数确认不会触发 dependency auto-completion，也不会补跑前置工具

- still not a scheduler or full dialogue manager
  - router 仍然是 bounded workflow controller，不是 general orchestration scheduler

另外有一个有意识的工程选择：

- parameter lock 当前通过 router `_prepare_tool_arguments()` 对“同名参数”做 execution-side override
  - 没有进一步扩成“自动为所有可能缺失参数补注入”
  - 这是刻意保持 bounded 的结果，避免本轮漂移成 implicit slot-filling scheduler

## 8. Suggested Next Step

最自然的下一步是做 **parameter-lock-aware continuation / evaluation slices**：

- 在现有 continuation evaluation harness 上加入 parameter ambiguity cases
- 衡量“confirmation lock 是否提高下一步 tool argument correctness / 降低重复 negotiation rate”

原因是本轮已经把 negotiation IR、state、trace、execution lock 全部落地，下一步最有论文价值的不是继续加机制，而是把“lock 对 continuation / execution 的收益”做成可比较实验面。
