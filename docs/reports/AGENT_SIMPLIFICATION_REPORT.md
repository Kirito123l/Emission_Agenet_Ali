# Agent Simplification Report

## Summary

本次改动把 Agent 从“router 规则主导”收回到“LLM 决策，系统执行”：

- 删除 router 内部的气象硬拦截和关键词式 follow-up 编排
- SkillInjector 停止过滤工具 schema，始终注入全部 8 个工具
- 单轮多步执行改为标准 function-calling 循环：工具结果回喂 LLM，再由 LLM 决定下一步
- 气象确认改回 skill prompt 引导，不再由 router 猜测 “OK / 可以 / 开始吧”

## Removed Overdesign

以下过度设计逻辑已从 `core/router.py` 删除。括号中的行号是删除前的大致位置，来自修复前的代码检索记录：

- 顶部多步/气象关键词常量块，旧位置约 `49-116`
- `_determine_follow_up_tools()`，旧位置约 `570`
- `_should_continue_execution()`，旧位置约 `607`
- `_build_runtime_fact_memory()`，旧位置约 `611`
- `_build_follow_up_instruction()`，旧位置约 `632`
- `_build_dispersion_meteorology_clarification()`，旧位置约 `669`
- `_has_recent_meteorology_confirmation()`，旧位置约 `712`
- `_user_mentioned_meteorology()`，旧位置约 `728`
- `_should_pause_for_dispersion_meteorology()`，旧位置约 `742`
- `_request_dispersion_meteorology_clarification()`，旧位置约 `765`
- `_request_follow_up_tool_selection()`，旧位置约 `791`
- `_state_handle_executing()` 里 “Pausing calculate_dispersion...” 的硬拦截分支，旧位置约 `1153-1168`
- `_state_handle_executing()` 里基于 `candidate_tools` 的 follow-up 选择分支，旧位置约 `1352-1372`

## Kept Mechanisms

以下机制保留，因为它们仍然属于“系统做执行”的范围：

- `TaskState` 状态机：`INPUT_RECEIVED -> GROUNDED -> EXECUTING -> DONE/NEEDS_CLARIFICATION`
- 文件分析与 file grounding
- 工具依赖注入：`_last_result` 仍会为 `calculate_dispersion` / `analyze_hotspots` / `render_spatial_map` 自动补齐
- 标准化失败澄清：例如车型、污染物、参数标准化失败仍会转 `NEEDS_CLARIFICATION`
- 单工具友好渲染与 synthesis fallback
- `max_orchestration_steps=4`，但现在只由工具编排循环消费，不再被状态切换误消耗

## New LLM-Native Loop

当前关键实现位置：

- 状态循环入口：[core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L265)
- 工具参数记录 helper：[core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L469)
- tool result 回喂 helper：[core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L541)
- 执行主循环：[core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L741)

执行流程现在是：

1. LLM 首次返回 `tool_calls`
2. router 执行工具
3. router 将 assistant tool-call message + 压缩后的 tool result message 追加回消息历史
4. 再次调用 `chat_with_tools`
5. 如果 LLM 继续返回 `tool_calls`，继续执行
6. 如果 LLM 返回纯文本，直接作为本轮最终回复
7. 如果连续工具轮次达到 `max_orchestration_steps`，停止继续追问，直接用当前结果渲染/synthesis

简化后的状态图：

```text
INPUT_RECEIVED
  -> GROUNDED
  -> EXECUTING
      -> execute tool(s)
      -> append tool messages
      -> ask LLM again
         -> more tool_calls: stay inside EXECUTING loop
         -> plain text: DONE
         -> max steps: DONE via synthesis/render
```

外层 `_run_state_loop()` 现在只看终态，并增加了一个独立的 `loop_guard` 防止状态机异常卡住；它不再错误地把状态切换次数当成 orchestration 步数。

## Skill Injection Simplification

关键改动：

- `core/skill_injector.py:get_tools_for_intents()` 现在始终返回全部工具
- `core/assembler.py` 在 skill mode 下也始终注入全部 `all_tool_definitions`
- `detect_intents()` 仍保留，但只决定 skill 内容，不决定工具可见性
- 当消息没有显式意图但存在 `last_tool_name` 时，会补回对应领域 intent，并继续附加 post-tool guide

相关位置：

- SkillInjector intent 检测：[core/skill_injector.py](/home/kirito/Agent1/emission_agent/core/skill_injector.py#L69)
- SkillInjector 全工具返回：[core/skill_injector.py](/home/kirito/Agent1/emission_agent/core/skill_injector.py#L168)
- Assembler 全工具注入：[core/assembler.py](/home/kirito/Agent1/emission_agent/core/assembler.py#L125)

这解决了 “用户只说 `OK` 时工具被过滤掉” 的根因。

## Meteorology Confirmation

气象确认现在完全交回 prompt 引导：

- 更新文件：[config/skills/dispersion_skill.yaml](/home/kirito/Agent1/emission_agent/config/skills/dispersion_skill.yaml)
- 新 skill 明确要求：
  - 调 `calculate_dispersion` 之前先告诉用户默认预设
  - 给出风速、风向、稳定度
  - 提供调整选项
  - 等用户确认后再调用工具
  - 用户已指定气象，或当前消息是在回应上一轮确认时，可以直接调工具

预期交互流程：

```text
用户: 帮我做扩散分析
LLM: 我将使用城市夏季白天预设（西南风 2.5 m/s，强不稳定条件）...
用户: OK
LLM: 调用 calculate_dispersion(...)
router: 执行工具，不再硬拦截
LLM: 如有需要继续调 analyze_hotspots / render_spatial_map，或直接回复用户
```

## Files Changed

- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py)
- [core/skill_injector.py](/home/kirito/Agent1/emission_agent/core/skill_injector.py)
- [core/assembler.py](/home/kirito/Agent1/emission_agent/core/assembler.py)
- [config/skills/dispersion_skill.yaml](/home/kirito/Agent1/emission_agent/config/skills/dispersion_skill.yaml)
- [tests/test_multi_step_execution.py](/home/kirito/Agent1/emission_agent/tests/test_multi_step_execution.py)
- [tests/test_skill_injector.py](/home/kirito/Agent1/emission_agent/tests/test_skill_injector.py)
- [tests/test_assembler_skill_injection.py](/home/kirito/Agent1/emission_agent/tests/test_assembler_skill_injection.py)
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py)
- [tests/test_hotspot_tool.py](/home/kirito/Agent1/emission_agent/tests/test_hotspot_tool.py)

## Test Results

定向测试：

- `pytest tests/test_multi_step_execution.py -v` -> 9 passed
- `pytest tests/test_skill_injector.py -v` -> 42 passed
- `pytest tests/test_assembler_skill_injection.py -v` -> 11 passed
- `pytest tests/test_router_contracts.py -q` -> 18 passed
- `pytest tests/test_router_state_loop.py -q` -> 8 passed
- `pytest tests/test_dispersion_tool.py -q` -> 20 passed
- `pytest tests/test_hotspot_tool.py -q` -> 15 passed

辅助验证：

- Tool injection check:
  - `'帮我做扩散'` -> `tools=8`
  - `'OK'` -> `tools=8`
  - `'你好'` -> `tools=8`
  - `'帮我算排放然后做扩散'` -> `tools=8`
- `python main.py health` -> 8 tools OK

全量回归：

- `pytest -q` -> **500 passed, 19 warnings in 48.82s**

## Final Regression Count

本轮全量回归测试数：**500**
