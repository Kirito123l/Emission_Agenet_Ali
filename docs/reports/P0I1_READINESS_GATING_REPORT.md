# P0I1 Readiness Gating Report

## 1. Summary
本轮实现了一个统一的 readiness layer，用同一套 bounded assessment 同时服务：

- tool selection 之后、execution 之前的 pre-execution gating
- synthesis 阶段的 follow-up suggestion 约束
- already-provided artifact 去重

核心结果是：

- 系统现在会在真正执行工具前，把动作判成 `ready / blocked / repairable / already_provided`
- 缺 geometry 的空间动作、缺关键字段的宏观排放动作，会在 router pre-exec 路径被拦下，不再先执行再失败
- synthesis 和 deterministic single-tool rendering 不再依赖“系统里有哪些工具”，而是依赖同一套 readiness assessment
- 已交付 artifact 会进入统一 dedup 逻辑，不再在 follow-up 建议里重复出现

本轮目标已达到，但仍然保持 bounded：没有引入 structured data-completion flow，没有新增 scheduler / auto-completion / persistence。

## 2. Files Changed
- [config.py](/home/kirito/Agent1/emission_agent/config.py)
  - 新增 `ENABLE_READINESS_GATING`、`READINESS_REPAIRABLE_ENABLED`、`READINESS_ALREADY_PROVIDED_DEDUP_ENABLED`
  - 默认都为 `true`，因为这轮目标就是让 readiness assessment 成为默认主路径；如果要做 ablation，可直接关掉

- [core/readiness.py](/home/kirito/Agent1/emission_agent/core/readiness.py)
  - 新增正式 readiness IR：`ReadinessStatus`、`BlockedReason`、`AlreadyProvidedArtifact`、`ActionCatalogEntry`、`ActionAffordance`、`ReadinessAssessment`
  - 实现 bounded action catalog、统一 readiness assessment、tool-call 到 action 的映射，以及 blocked / repairable / already_provided 的结构化 response builder

- [core/capability_summary.py](/home/kirito/Agent1/emission_agent/core/capability_summary.py)
  - 改成 readiness layer 的 adapter
  - synthesis prompt 和 deterministic follow-up 继续走旧 surface，但底层已经统一改为 readiness assessment

- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py)
  - 新增 `_build_readiness_assessment()`、`_assess_selected_action_readiness()`、`_record_action_readiness_trace()`
  - 在 `_state_handle_executing()` 里把 readiness gate 接到 `_prepare_tool_arguments()` 之后、`executor.execute()` 之前
  - blocked / repairable / already_provided 会在这里直接停下并返回结构化说明
  - synthesis 构建也改为复用同一套 readiness assessment
  - 原本 response build 里的额外可视化建议旁路，现在在 readiness/capability summary 存在时不会再绕过约束

- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py)
  - 修复从 memory 初始化 state 时没有把完整 `file_analysis` 缓存挂回 state 的问题
  - 这样 readiness assessment 在 continuation / memory-restore 场景下能继续看到 `missing_field_diagnostics`、`spatial_metadata` 等 grounded signals

- [core/trace.py](/home/kirito/Agent1/emission_agent/core/trace.py)
  - 新增 readiness trace taxonomy，并接入 formatter

- [tests/test_readiness_gating.py](/home/kirito/Agent1/emission_agent/tests/test_readiness_gating.py)
  - 新增 readiness unit tests

- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py)
  - 新增 pre-exec readiness gating 和 synthesis regression tests

- [tests/test_trace.py](/home/kirito/Agent1/emission_agent/tests/test_trace.py)
  - 新增 readiness trace formatting tests

- [tests/test_config.py](/home/kirito/Agent1/emission_agent/tests/test_config.py)
  - 覆盖新 flag 默认值

## 3. Readiness Layer Design
### readiness IR
readiness layer 定义在 [core/readiness.py](/home/kirito/Agent1/emission_agent/core/readiness.py)：

- `ReadinessStatus`
  - `ready`
  - `blocked`
  - `repairable`
  - `already_provided`

- `BlockedReason`
  - `reason_code`
  - `message`
  - `missing_requirements`
  - `repair_hint`
  - `severity`

- `ActionCatalogEntry`
  - bounded action catalog 元数据

- `ActionAffordance`
  - 单个 action 的当前 readiness 判定

- `ReadinessAssessment`
  - 当前 turn / 当前上下文的聚合 assessment

### action catalog
本轮 catalog 是有限、可解释的，不是通用动作图。当前覆盖：

- 计算类
  - `run_macro_emission`
  - `run_micro_emission`
  - `run_dispersion`
  - `run_hotspot_analysis`

- 渲染类
  - `render_emission_map`
  - `render_dispersion_map`
  - `render_hotspot_map`

- 交付类
  - `download_detailed_csv`
  - `download_topk_summary`
  - `render_rank_chart`

- 替代分析类
  - `compare_scenario`

### 四分类逻辑
- `ready`
  - prerequisites、file readiness、geometry readiness、artifact dedup 全都通过

- `blocked`
  - 当前动作和上下文明显不相容
  - 当前主要用在 `task_type` incompatible 这类强阻断

- `repairable`
  - 当前不能做，但缺失条件清晰、结构化、可解释
  - 例如：
    - 缺 `traffic_flow_vph`
    - 缺 geometry
    - 缺 upstream result token
    - 缺 scenario pair

- `already_provided`
  - 当前 turn 已经交付了同类 artifact，不应重复建议或重复执行

### 为什么这是系统级约束，而不是 case-specific patch
这层不是在 router 里补几个 if-else。真正统一的是：

- 同一套 action catalog
- 同一套 file/result/artifact signal 读取
- 同一套 status taxonomy
- 同一套 blocked / repairable response builder
- 同一套 synthesis adapter

因此 geometry 缺失、traffic flow 缺失、重复下载建议只是这套 readiness layer 的不同实例，而不是单独打补丁。

## 4. Router Integration
### pre-execution gating 接点
主接点在 [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py) 的 `_state_handle_executing()`：

1. LLM 已经选出 tool
2. `_prepare_tool_arguments()` 先做 runtime argument injection / parameter lock 覆盖
3. `_assess_selected_action_readiness()` 把 tool call 映射到 action id
4. 读取同一上下文下的 `ReadinessAssessment`
5. 若不是 `ready`，就在 `executor.execute()` 之前停下

### blocked / repairable 时如何响应
- `blocked`
  - 不执行工具
  - 构建 `build_action_blocked_response(...)`
  - 写 `state.execution.blocked_info`
  - 当前 turn 结束

- `repairable`
  - 不执行工具
  - 构建 `build_action_repairable_response(...)`
  - 当前 turn 结束
  - 但本轮不进入新的 interactive completion flow

- `already_provided`
  - 不重复执行
  - 返回 `build_action_already_provided_response(...)`

### 为什么这一轮没有做 structured data-completion flow
这轮只实现 governance，不实现 resolution flow。

也就是说：

- readiness layer 会告诉你“现在不能做”
- 会说明“差什么”
- 会说明“最接近的补救方向”
- 但不会把它推进成 `NEEDS_INPUT_COMPLETION` 或下一轮交互式补数流程

这是刻意 bounded 的边界。

### 与既有 dependency gate 的关系
这轮没有推翻既有 deterministic dependency enforcement。

工程上做了一个现实适配：

- geometry / missing fields / already-provided 这类 readiness 问题，直接在 readiness gate 拦下
- 仅 missing upstream result token / stale token 这类 case，仍允许继续走既有 dependency gate，从而不破坏之前的 bounded repair 语义

这样 readiness layer 统一了 assessment surface，但没有粗暴改写已有 dependency-blocked -> repair 路径。

## 5. Synthesis Integration
### 同一套 assessment 如何继续服务结果综合
[core/capability_summary.py](/home/kirito/Agent1/emission_agent/core/capability_summary.py) 现在只是 readiness 的 adapter：

- `build_capability_summary(...)` 内部直接调用 `build_readiness_assessment(...)`
- synthesis prompt 继续拿 capability summary surface
- deterministic single-tool renderer 继续走 `get_capability_aware_follow_up(...)`

但底层已经是同一套 readiness logic，不再有一套给 synthesis、一套给 pre-exec。

### 抑制 unsupported actions 和重复 artifact
统一 suppression 现在来自同一个 readiness assessment：

- 无 geometry
  - `render_emission_map`
  - `run_dispersion`
  不再进入 ready list

- 已给 download_file
  - `download_detailed_csv`
  进入 `already_provided`

- 当前 `summary_table / chart_data / map_data` 已交付
  - 对应 artifact action 不再重复建议

### 一个额外修复
在 [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py) 的 response build 里，原本还有一条手工拼接“检测到空间数据，可以进行地图可视化”的旁路。  
这条旁路会绕开 synthesis prompt 约束。

本轮把它改成：

- 当 capability/readiness summary 存在时，不再走这条附加建议旁路

这样 guidance 不会被这个后门重新污染。

## 6. Trace Extensions
### 新增 trace types
在 [core/trace.py](/home/kirito/Agent1/emission_agent/core/trace.py) 新增：

- `READINESS_ASSESSMENT_BUILT`
- `ACTION_READINESS_READY`
- `ACTION_READINESS_BLOCKED`
- `ACTION_READINESS_REPAIRABLE`
- `ACTION_READINESS_ALREADY_PROVIDED`

### 写入路径
- `_build_readiness_assessment(...)`
  - 写 `READINESS_ASSESSMENT_BUILT`

- `_assess_selected_action_readiness(...)`
  - 针对 selected action 写：
    - `ACTION_READINESS_READY`
    - `ACTION_READINESS_BLOCKED`
    - `ACTION_READINESS_REPAIRABLE`
    - `ACTION_READINESS_ALREADY_PROVIDED`

### 为什么这些 trace 对论文有用
这组 trace 能直接回答：

- 当前 turn 到底评估了哪些 affordance
- 某个动作为什么是 blocked / repairable
- pre-exec 是否真的在执行前拦住了不 ready 动作
- synthesis / deterministic guidance 背后用的 readiness surface 是什么

因此这组 trace 可以直接作为 readiness-aware governance 的 case study artifact。

## 7. Tests
### 跑了哪些测试
运行了：

```bash
python -m py_compile core/readiness.py core/capability_summary.py core/router.py core/trace.py config.py tests/test_readiness_gating.py tests/test_router_state_loop.py tests/test_trace.py tests/test_config.py
pytest -q tests/test_readiness_gating.py tests/test_capability_aware_synthesis.py tests/test_router_state_loop.py tests/test_trace.py tests/test_router_contracts.py tests/test_render_defaults.py tests/test_config.py
```

结果：

- `104 passed`
- `4 warnings`

warnings 是现有 FastAPI `on_event` deprecation warning，不是这轮引入的错误。

### 新增覆盖的关键行为
- [tests/test_readiness_gating.py](/home/kirito/Agent1/emission_agent/tests/test_readiness_gating.py)
  - geometry 缺失时空间动作不是 `ready`
  - `traffic_flow_vph` 缺失时宏观动作是 `repairable`
  - download artifact 已提供时进入 `already_provided`
  - 标准宏观输入仍是 `ready`

- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py)
  - render_spatial_map 在缺 geometry 时 pre-exec 就被拦下
  - task_type incompatible 时 pre-exec blocked
  - 缺 `traffic_flow_vph` 时宏观排放不再先执行后失败
  - synthesis 不再建议 unsupported spatial actions，也不再重复建议下载

- [tests/test_trace.py](/home/kirito/Agent1/emission_agent/tests/test_trace.py)
  - 新 readiness trace formatter 全覆盖

## 8. Known Limitations
- no structured data-completion flow yet
- repairable currently explains but does not continue
- readiness catalog is bounded to high-value actions
- no new scheduler / auto-completion / persistence was introduced

另外有一个代码现实层面的限制需要明确：

- 当前 task-type gating 只在确实存在 grounded file context 时才生效

这是刻意的。原因是系统里仍然存在不依赖 grounded file 的工具调用路径；如果把 `task_type` 约束无条件扩张到所有调用，会把原本合法的非文件型调用也误拦掉，反而让论文叙事变差。

## 9. Suggested Next Step
最自然的下一步是：

**在 readiness layer 之上补一个 bounded resolution flow，只处理 repairable actions 的最小化 completion negotiation。**

原因很直接：

- 这轮已经能稳定识别 `repairable`
- 也已经能在 pre-exec 阶段阻断 premature execution
- 但 repairable 还只会“解释”，不会“进入正式补救流程”

所以下一轮最值得做的，不是继续扩 catalog，而是把 `repairable -> bounded completion` 这条链补上。
