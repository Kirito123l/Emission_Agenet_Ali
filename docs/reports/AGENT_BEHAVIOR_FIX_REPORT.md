# Agent Behavior Fix Report

## 概览

本次修复覆盖三个架构层问题：

1. 单轮多步请求只执行第一步。
2. `calculate_dispersion` 在用户未指定气象条件时直接吃默认值，不先确认。
3. `render_spatial_map` 未走友好渲染，回复退化为 `Map rendered: N features`。

## 根因分析

### 1. 单轮多步执行

- 状态循环入口在 [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L320) 附近。
- `max_orchestration_steps` 仍是 4，来自 [config.py](/home/kirito/Agent1/emission_agent/config.py#L54)。
- 一次 LLM 调用可以返回多个 `tool_calls`，但原实现的关键问题不在“单步只能一个 tool”，而在于：
  - `_state_handle_executing()` 执行完成后无条件转 `DONE`。
  - 没有“执行完一个工具后，再让 LLM 基于当前结果决定下一个工具”的分支。
- 结果：像“先扩散，再识别热点”这种依赖式请求，即使 `dispersion_result` 已经产出，也不会在同轮继续触发 `analyze_hotspots`。

### 2. 气象条件询问

- 仅靠 skill prompt 不可靠，LLM 会直接补 `urban_summer_day`。
- 原 router 没有任何硬拦截逻辑，导致默认预设会直接进入 executor。
- 这个问题在链式执行里更明显：即使第一步是自动衔接出来的 `calculate_dispersion`，也会静默使用默认气象。

### 3. `render_spatial_map` 友好渲染缺失

- `render_spatial_map` 不在 `TOOLS_NEEDING_RENDERING` 中。
- 单工具成功时，短路 synthesis 看不到它是“需要 deterministic renderer 的工具”，因此直接回退到 tool summary。
- 于是用户只看到 `Map rendered: 20 features` 这种摘要，而不是结构化渲染说明。

## 实现方案

### 1. 单轮多步执行

核心改动在 [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L548) 和 [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L1011)：

- 新增 `_determine_follow_up_tools()` / `_should_continue_execution()`：
  - 用 `TOOL_GRAPH` 检查最新工具产出的 `provides` 是否解锁了下游工具。
  - 结合当前消息和最近用户消息里的链式意图关键词判断是否继续。
  - 同时过滤掉本轮已执行过的工具，避免重复调用。
- 新增 `_request_follow_up_tool_selection()`：
  - 不改 `TaskStage` 定义，继续留在 `EXECUTING` 阶段。
  - 在工具成功后，重新组装一个带“当前轮已完成结果摘要”的上下文，再让 LLM 只在候选下游工具中选下一步。
  - 若选到新工具，则 `steps_taken += 1`，继续同轮执行；若无新工具，则自然结束。

状态转换现在是：

```text
INPUT_RECEIVED -> GROUNDED -> EXECUTING
EXECUTING --工具成功且存在匹配的下游候选--> EXECUTING
EXECUTING --无后续候选/用户意图已完成--> DONE
EXECUTING --需要气象确认/参数澄清--> NEEDS_CLARIFICATION
```

### 2. 气象硬拦截

核心改动在 [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L669) 到 [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L779)，以及执行前拦截点 [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L1153)。

触发条件：

- 当前将执行的工具是 `calculate_dispersion`
- 用户当前和最近几轮用户消息都没有明确提到气象条件
- 没有 `wind_speed` / `wind_direction` / `stability_class` / `mixing_height` 覆盖参数
- `meteorology` 缺失，或显式等于默认值 `urban_summer_day`
- 用户也没有在上一轮气象澄清后回复“开始吧 / 就用默认”这类确认语

恢复流程：

1. router 在执行前进入 `NEEDS_CLARIFICATION`
2. 回复里动态读取 `config/meteorology_presets.yaml`，告诉用户默认预设和关键参数
3. 用户回复“开始吧”后，router 通过 working memory 识别这是对上一轮气象澄清的确认
4. `calculate_dispersion` 不再被拦截
5. 若上一轮原始诉求里还包含“进一步识别热点”，同轮会继续自动执行 `analyze_hotspots`

### 3. `render_spatial_map` 友好渲染

核心改动：

- [core/router_synthesis_utils.py](/home/kirito/Agent1/emission_agent/core/router_synthesis_utils.py#L14)：
  - 把 `render_spatial_map` 加入 `TOOLS_NEEDING_RENDERING`
- [core/router_render_utils.py](/home/kirito/Agent1/emission_agent/core/router_render_utils.py#L217)：
  - 新增 `_render_spatial_map_result()`
  - 按 `map_data.type` 分别渲染：
    - `macro_emission_map` / `emission`
    - `raster`
    - `hotspot`
    - `concentration`
  - 保留 `map_data` 给前端，不影响地图卡片

## 输出示例

### render_spatial_map

修复前：

```text
Map rendered: 20 features
```

修复后：

```text
## 空间渲染结果

**路段排放地图**
已渲染 20 条路段的排放分布。
排放强度范围: 0.12 - 4.6 kg/(h·km)
```

### dispersion 气象澄清

```text
我将为您进行大气扩散分析。扩散结果对气象条件非常敏感，需要先确认一下气象设置：

当前将使用 urban_summer_day 预设（城市夏季白天 - 强不稳定，西南风 2.5 m/s，稳定度 VU，混合层 1500 m）。

您可以：
- 直接说"开始吧"使用默认设置
- "改用静风稳定条件" - 模拟最不利扩散
- "风向改成西北" - 在当前预设基础上调整
- "用冬季夜间条件" - 切换到其他预设
```

## 修改文件

主改动：

- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py)
- [core/router_synthesis_utils.py](/home/kirito/Agent1/emission_agent/core/router_synthesis_utils.py)
- [core/router_render_utils.py](/home/kirito/Agent1/emission_agent/core/router_render_utils.py)
- [tests/test_multi_step_execution.py](/home/kirito/Agent1/emission_agent/tests/test_multi_step_execution.py)

回归测试适配：

- [tests/test_dispersion_tool.py](/home/kirito/Agent1/emission_agent/tests/test_dispersion_tool.py)

## 测试结果

已执行：

- `pytest tests/test_multi_step_execution.py -v`
  - 16 passed
- `pytest tests/test_router_contracts.py -q`
  - 18 passed
- `pytest tests/test_router_state_loop.py -q`
  - 8 passed
- `pytest tests/test_dispersion_tool.py -q`
  - 20 passed
- `pytest -q`
  - 506 passed, 19 warnings
- `python main.py health`
  - 8 个工具全部 OK

## 结论

三个问题现在都在 router/render 层被稳定处理：

- 多步请求可以在单轮内继续执行下游工具。
- 扩散默认气象不再静默生效，必须先确认。
- `render_spatial_map` 进入 deterministic friendly render，不再退化为简陋 summary。
