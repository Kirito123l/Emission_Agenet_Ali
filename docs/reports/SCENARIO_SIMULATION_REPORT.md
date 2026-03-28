# Scenario Simulation Report

## 1. 架构总览

```text
User natural language
    ↓
LLM (skill-guided)
    ↓
calculate_macro_emission(overrides=..., scenario_label=...)
    ↓
SessionContextStore
  - emission:baseline
  - emission:speed_30kmh
  - dispersion:baseline
  - dispersion:speed_30kmh
  - hotspot:...
    ↓
Optional downstream tools
  - calculate_dispersion(scenario_label=...)
  - analyze_hotspots(scenario_label=...)
  - render_spatial_map(scenario_label=...)
    ↓
compare_scenarios(result_types=[...], scenario="...")
    ↓
LLM summary + chart_data
```

核心原则保持不变：
- LLM 负责把自然语言翻译成 `overrides`、`scenario_label` 和工具编排。
- 工具只执行确定性逻辑。
- Context Store 管理完整结果，多版本共存。
- compare 工具只读 Context Store，不重新计算。

## 2. Override 引擎

文件：`tools/override_engine.py`

### 数据结构

每个 override 都是一个对象，支持：
- `column`: `avg_speed_kph` / `traffic_flow_vph` / `link_length_km` / `fleet_mix`
- `transform`: `set` / `multiply` / `add`
- `value` / `factor` / `offset`
- `where`: 条件过滤，支持 `> >= < <= == != in not_in`

### 验证规则

- 只允许白名单列
- 数值列做类型检查和范围检查
- `multiply` 必须提供正数 `factor`
- `fleet_mix` 必须是车型占比字典
- `fleet_mix` 车型类别必须属于：
  - `Passenger Car`
  - `Passenger Truck`
  - `Light Commercial Truck`
  - `Transit Bus`
  - `Combination Long-haul Truck`
- `fleet_mix` 总和必须接近 100%
- `where` 条件必须完整且操作符合法

### 应用规则

- 对输入 `links_data` 做深拷贝，不污染原始数据
- 顺序执行多个 override
- 数值变换后自动裁剪到合法范围
- `fleet_mix` 自动归一化到 100%
- 返回 `overrides_applied` 文本摘要，供结果透明展示和后续对比引用

## 3. Context Store 多版本存储

文件：`core/context_store.py`

### 存储 schema

旧方案：
- 单一 `result_type -> last result`
- 新情景结果会覆盖旧结果

新方案：
- `result_type:label -> StoredResult`
- 例如：
  - `emission:baseline`
  - `emission:speed_30kmh`
  - `dispersion:baseline`
  - `dispersion:speed_30kmh`

`StoredResult` 字段：
- `result_type`
- `tool_name`
- `label`
- `timestamp`
- `summary`
- `data`
- `metadata`

### 依赖解析决策树

- `calculate_dispersion`
  - 优先取 `emission:<scenario_label>`
  - 若未指定标签，优先取本轮最新 emission
  - 否则回退到 `emission:baseline`
- `analyze_hotspots`
  - 同理取 `dispersion`
- `render_spatial_map`
  - `layer_type=emission` → emission
  - `layer_type=raster/concentration` → dispersion
  - `layer_type=hotspot` → hotspot
  - 未指定时按 `hotspot > dispersion > emission`
- `compare_scenarios`
  - 不依赖 `_last_result`
  - 直接读取 Context Store

### 依赖失效机制

- 写入新的 `emission:<label>` 时：
  - 将 `dispersion:<label>` 标记为 `stale`
  - 将 `hotspot:<label>` 标记为 `stale`
- 写入新的 `dispersion:<label>` 时：
  - 将 `hotspot:<label>` 标记为 `stale`

### 场景数量限制

- 每种 `result_type` 最多保留 5 个非 `baseline` 场景
- 超出后移除最旧的非 baseline 场景，避免会话内存无限增长

## 4. compare_scenarios 工具

文件：
- `calculators/scenario_comparator.py`
- `tools/scenario_compare.py`

### 输入

- `result_types`: `["emission"]` / `["dispersion"]` / `["hotspot"]` / 组合
- `baseline`: 默认 `baseline`
- `scenario`: 单场景对比
- `scenarios`: 多场景对比
- `metrics`: 可选指标过滤

### 输出

- `data`: 结构化对比结果
- `summary`: 人类可读摘要
- `chart_data`: 前端可用的 grouped bar 数据

### emission 对比内容

- 总量差值和百分比变化
- Top 10 路段变化
- `overrides_applied`

### dispersion 对比内容

- `mean_concentration`
- `max_concentration`
- 气象参数变化

### hotspot 对比内容

- 热点数量变化
- 最大浓度变化
- 热点总面积变化

## 5. Router 与工具层接入

### Router

文件：`core/router.py`

改动：
- 对 `calculate_dispersion` / `analyze_hotspots` / `render_spatial_map`
  - 注入带 `scenario_label` 解析能力的 `_last_result`
- 对 `compare_scenarios`
  - 注入 `_context_store`

### Tool schema

文件：`tools/definitions.py`

新增/扩展：
- `calculate_macro_emission`
  - `overrides`
  - `scenario_label`
- `calculate_dispersion`
  - `scenario_label`
- `analyze_hotspots`
  - `scenario_label`
- `render_spatial_map`
  - `scenario_label`
- 新工具 `compare_scenarios`

### Tool registry

文件：`tools/registry.py`

- 新注册 `compare_scenarios`
- 当前总工具数从 8 变为 9

## 6. Skill 与能力边界

文件：
- `config/skills/scenario_skill.yaml`
- `config/skills/post_emission_guide.yaml`
- `config/skills/post_dispersion_guide.yaml`
- `config/skills/post_hotspot_guide.yaml`
- `core/skill_injector.py`

### 新增能力

- 自然语言触发情景分析
- 用 `scenario_label` 管理多版本结果
- 建议用户做情景对比和重算

### 能力边界声明清单

系统支持：
- 调整速度
- 调整流量
- 调整车队组成
- 调整气象条件
- 调整栅格分辨率
- 调整热点阈值
- 对比不同情景的排放/浓度/热点
- 可视化任意已有结果

系统明确不支持：
- 新能源车/电动车专属排放模拟
- 建筑物/绿化带/屏障扩散遮蔽
- 信号配时优化或微观交通仿真
- 道路新建/拓宽几何变更
- 人口暴露和健康风险评估
- 任何依赖外部新数据源或外部模型的分析

## 7. 典型交互流程

### 单情景排放对比

用户：
- “把速度降到 30 看看效果”

LLM 编排：
1. `calculate_macro_emission(overrides=[...], scenario_label="speed_30kmh")`
2. `compare_scenarios(result_types=["emission"], scenario="speed_30kmh")`

### 排放 + 扩散级联情景

用户：
- “如果所有路段速度降低 20%，扩散会有什么变化？”

LLM 编排：
1. `calculate_macro_emission(overrides=[...], scenario_label="speed_80pct")`
2. `calculate_dispersion(scenario_label="speed_80pct")`
3. `compare_scenarios(result_types=["emission", "dispersion"], scenario="speed_80pct")`

### 多场景对比

用户：
- “30 和 45 都试试，对比一下排放”

LLM 编排：
1. `calculate_macro_emission(..., scenario_label="speed_30")`
2. `calculate_macro_emission(..., scenario_label="speed_45")`
3. `compare_scenarios(result_types=["emission"], scenarios=["speed_30", "speed_45"])`

## 8. 修改文件

新增：
- `tools/override_engine.py`
- `calculators/scenario_comparator.py`
- `tools/scenario_compare.py`
- `config/skills/scenario_skill.yaml`
- `tests/test_override_engine.py`
- `tests/test_scenario_comparator.py`
- `tests/test_compare_tool.py`
- `tests/test_context_store_scenarios.py`

修改：
- `tools/macro_emission.py`
- `tools/dispersion.py`
- `tools/hotspot.py`
- `tools/definitions.py`
- `tools/registry.py`
- `core/context_store.py`
- `core/router.py`
- `core/tool_dependencies.py`
- `core/skill_injector.py`
- `core/router_render_utils.py`
- `config/skills/post_emission_guide.yaml`
- `config/skills/post_dispersion_guide.yaml`
- `config/skills/post_hotspot_guide.yaml`
- `tests/test_context_store.py`
- `tests/test_context_store_integration.py`
- `tests/test_skill_injector.py`
- `tests/test_assembler_skill_injection.py`
- `tests/test_dispersion_tool.py`
- `tests/test_hotspot_tool.py`

## 9. 测试结果

按验收项：
- `pytest tests/test_override_engine.py -v` → 25 passed
- `pytest tests/test_scenario_comparator.py -v` → 8 passed
- `pytest tests/test_compare_tool.py -v` → 8 passed
- `pytest tests/test_context_store_scenarios.py -v` → 9 passed
- `pytest tests/test_context_store.py -q` → 22 passed
- `pytest tests/test_context_store_integration.py -q` → 6 passed
- `pytest tests/test_router_contracts.py -q` → 18 passed
- `pytest tests/test_router_state_loop.py -q` → 8 passed
- `pytest -q` → 590 passed
- `python main.py health` → 9 tools OK
- 工具注册验证脚本 → 9 tools registered

备注：
- `python main.py health` 期间会打印 `FlagEmbedding` 未安装告警，但不影响 9 个工具注册和健康检查通过。

