# EmissionAgent Phase 1-2 全量工作总结

> 说明：按要求搜索 `EmissionAgent_Project_Status_v2.md`，在项目根目录、上级目录和 `docs/` 范围内均未找到。本文的系统架构与阶段总结主要依据各 Sprint 报告、当前代码与实际运行结果整理，缺失处明确标注。

## 一、项目概述

EmissionAgent 是一个面向机动车排放分析场景的 LLM-native 智能体系统，目标是把“自然语言需求 + 上传文件 + 领域计算 + 结果可视化”收敛成统一闭环。当前主链以 `UnifiedRouter` 为中枢，将文件理解、参数标准化、工具调度、排放/扩散计算、空间渲染、前端展示和会话记忆串联起来。系统的两条核心方法论主线是：一条是“文件感知任务锚定”，即上传文件后主动识别任务类型与字段语义；另一条是“执行侧参数标准化”，即把自然语言参数收束到受控的领域参数空间后再进入 calculator。  

- 项目名称：`EmissionAgent`
- 论文标题：❌ 未发现正式定稿标题；当前最推荐的论文主线题目为 `文件感知的自然语言排放分析智能体`，扩展表述可用 `面向机动车排放分析的文件感知、多工具自然语言智能体系统`（来源：`PROJECT_DEEP_ANALYSIS.md`、`docs/reports/CODEBASE_PAPER_DEEP_AUDIT_ROUND2.md`）
- 技术栈概要：Python 3.13、FastAPI、pandas、GeoPandas、Shapely、pyproj、XGBoost、SciPy、YAML、Leaflet、pytest

来源：`PROJECT_DEEP_ANALYSIS.md`、`SPRINT5_FINAL_REPORT.md`、`SPRINT10_FINAL_REPORT.md`、当前代码与运行结果。

## 二、系统架构

### 2.1 架构概览

`EmissionAgent_Project_Status_v2.md` ❌ 未找到。以下架构图根据当前代码与 Sprint 1-10 报告整理。

```text
User / Web UI / CLI
        |
        v
api/routes.py + api/session.py
        |
        v
core/router.py (UnifiedRouter)
  |-- core/task_state.py      -> 5状态状态机 + 参数/文件/执行上下文
  |-- core/trace.py           -> 审计式 Trace / trace_friendly
  |-- core/memory.py          -> fact memory / last_spatial_data / snapshots
  |-- core/executor.py        -> 参数标准化 + 工具执行
  |     |
  |     v
  |   services/standardizer.py
  |
  |-- tools/registry.py + tools/definitions.py
        |
        +--> tools/emission_factors.py      -> emission factor 查询
        +--> tools/micro_emission.py        -> 微观轨迹排放
        +--> tools/macro_emission.py        -> 宏观路段排放
        +--> tools/file_analyzer.py         -> 文件分析/grounding
        +--> tools/knowledge.py             -> 知识检索
        +--> tools/dispersion.py            -> 扩散浓度计算
        +--> tools/spatial_renderer.py      -> 空间渲染
                    |
                    v
              calculators/* + services/*
                    |
                    v
                map_data / tables / charts
                    |
                    v
                 web/app.js
```

### 2.2 5 状态状态机

当前 `TaskStage` 来自 `core/task_state.py`，共 5 个状态：

```text
INPUT_RECEIVED -> GROUNDED -> EXECUTING -> DONE
       |               |            |
       +-------------> NEEDS_CLARIFICATION
                       ^
                       |
                EXECUTING 也可回退到 NEEDS_CLARIFICATION
```

- `INPUT_RECEIVED`：接收用户输入、文件路径、记忆上下文。
- `GROUNDED`：完成文件 grounding、参数补全、工具选择前准备。
- `NEEDS_CLARIFICATION`：文件类型未知、参数歧义或关键参数缺失。
- `EXECUTING`：执行标准化、工具调用、依赖检查、空间数据注入。
- `DONE`：响应组装完成。

来源：`core/task_state.py` 当前实现，及 `SPRINT1_TASKSTATE_REPORT.md`、`SPRINT5_FINAL_REPORT.md`。

### 2.3 当前 7 个注册工具

根据 `python main.py tools-list` 与 `tools/definitions.py`、`tools/registry.py`，当前注册工具如下：

| 工具名 | 功能 |
|---|---|
| `query_emission_factors` | 查询车辆排放因子曲线，返回图表与表格 |
| `calculate_micro_emission` | 基于轨迹数据做秒级微观排放计算 |
| `calculate_macro_emission` | 基于路段长度/流量/速度做宏观排放计算 |
| `analyze_file` | 分析上传文件结构、字段和任务类型 |
| `query_knowledge` | 检索排放知识库、法规和概念 |
| `calculate_dispersion` | 基于宏观排放结果做 PS-XGB-RLINE surrogate 扩散浓度推理 |
| `render_spatial_map` | 将 emission / concentration 等空间结果渲染为地图数据 |

### 2.4 核心模块关系

- `core/router.py`：统一编排入口，负责状态流转、依赖检查、跨轮数据注入、结果 synthesis。
- `core/executor.py` + `services/standardizer.py`：对自然语言参数做透明标准化，并执行工具。
- `tools/*`：面向 LLM 的工具层封装，输出统一 `ToolResult`。
- `calculators/*`：纯计算层，承载 VSP、微观、宏观与扩散计算核心逻辑。
- `tools/spatial_renderer.py` + `web/app.js`：构成后端空间 payload 到前端 Leaflet 多图层渲染契约。
- `core/memory.py`：保存 `last_tool_snapshot`、`last_spatial_data` 等跨轮上下文。

## 三、Phase 1 详细工作记录（Sprint 1-5）

### Sprint 1: TaskState 状态机与 Router State-Driven Loop

- **目标**：把 Router 从隐式 flag/线性流程改造成显式的状态驱动执行循环。
- **核心改动**：
  - 新增/重构 `core/task_state.py`：建立 `TaskStage`、`ParamEntry`、`FileContext`、`ExecutionContext` 等状态数据结构。
  - 修改 `core/router.py`：引入 `_run_state_loop()`，同时保留 `_run_legacy_loop()` 兼容旧路径。
  - 修改 `config.py`：增加 `enable_state_orchestration`、`enable_trace`、`max_orchestration_steps`。
  - 修改 `api/session.py`、`api/models.py`、`api/routes.py`：让 API 返回 Router 新响应形态。
  - 新增 `tests/test_task_state.py`、扩展 `tests/test_router_state_loop.py`。
- **关键设计决策**：
  - 采用显式 `TaskState` 数据模型替代隐式布尔标记，便于序列化、回放与多轮恢复。
  - 新旧双轨并存：新状态循环接入 `Router`，但保留 `_run_legacy_loop()` 作为回退路径。
  - 通过 `to_dict()`/初始化恢复逻辑把会话状态做成可持久化对象，而不是一次性内存变量。
- **测试**：`未记录 -> 92`（`pytest` 总数 92；Sprint 前基线未在已读报告中记录）。
- **论文对应章节**：未明确提及。

来源：`SPRINT1_TASKSTATE_REPORT.md`。

### Sprint 2: Trace 审计链路

- **目标**：为 Router 的每个关键决策建立结构化、可审计的 trace。
- **核心改动**：
  - 新建 `core/trace.py`：实现 `Trace`、`TraceStep`、`TraceStepType`。
  - 修改 `core/router.py`：在状态循环中记录 `FILE_GROUNDING`、`TOOL_SELECTION`、`TOOL_EXECUTION`、`SYNTHESIS` 等步骤。
  - 修改 `api/session.py`、`api/models.py`、`api/routes.py`：把 `trace_friendly` 透传到前端。
  - 新建 `tests/test_trace.py`，扩展 `tests/test_router_state_loop.py`。
- **关键设计决策**：
  - Trace 数据分为结构化 `trace` 与前端可展示的 `trace_friendly` 两层。
  - 状态转移本身会记录，但前端友好视图默认跳过纯噪声型 state transition。
  - 旧架构下的 trace dict 不删除，通过最小兼容适配保留 legacy 行为。
- **测试**：`92 -> 106`，新增 14 个测试。
- **论文对应章节**：未明确提及。

来源：`SPRINT2_TRACE_REPORT.md`。

### Sprint 3: 多信号文件 Grounding

- **目标**：把文件识别从“仅看列名”升级为“列名 + 数值特征 + 完备性”的多信号 grounding。
- **核心改动**：
  - 修改 `tools/file_analyzer.py`：新增 `_analyze_value_features()`，重写 `_identify_task_type()`。
  - 新增 `tests/test_file_grounding_enhanced.py`。
  - 验证 `core/task_state.py` 与 `core/router.py` 已能承接 `evidence` 到 trace。
- **关键设计决策**：
  - 引入三信号判断：字段名、数值分布、所需字段完备性共同参与任务识别。
  - 把 grounding 证据显式写入 `FileContext.evidence`，使 file understanding 可解释。
  - 使用紧凑的 value-feature summary，而不是把整份样本直接塞给 trace 或 memory。
- **测试**：`106 -> 124`，新增 18 个测试。
- **论文对应章节**：未明确提及。

来源：`SPRINT3_FILE_GROUNDING_REPORT.md`。

### Sprint 4: 参数标准化增强

- **目标**：把参数标准化从“返回一个字符串”升级为“带策略、置信度和建议项的结构化结果”。
- **核心改动**：
  - 修改 `services/standardizer.py`：引入 `StandardizationResult`，扩展 vehicle/pollutant/season/road_type 标准化。
  - 修改 `config/unified_mappings.yaml`：补充 `road_types` alias 配置。
  - 修改 `core/executor.py`：让 `_standardize_arguments()` 返回 `(args, records)`。
  - 修改 `core/router.py`：把 `PARAMETER_STANDARDIZATION` 写进 trace。
  - 新增 `tests/test_standardizer_enhanced.py`。
- **关键设计决策**：
  - 保留 `exact / alias / fuzzy / abstain / default` 策略标签，使标准化路径可解释。
  - 对无法识别的值采用 abstain-with-suggestions，而不是静默猜测。
  - 将标准化记录随执行结果回传，形成后续 trace 与 clarification 的基础。
- **测试**：`124 -> 141`，新增 17 个测试。
- **论文对应章节**：未明确提及。

来源：`SPRINT4_STANDARDIZATION_REPORT.md`。

### Sprint 5: Clarification 路由与前端 Trace 面板

- **目标**：在 GROUNDED/EXECUTING 阶段对歧义输入进行澄清，同时把 trace 真正展示到前端。
- **核心改动**：
  - 修改 `core/router.py`：新增 `_identify_critical_missing()`，在文件未知、参数歧义、关键参数缺失时转入 `NEEDS_CLARIFICATION`。
  - 修改 `api/session.py`、`api/routes.py`、`api/models.py`：让 `trace_friendly` 进入历史消息与流式完成事件。
  - 修改 `web/index.html`、`web/app.js`：新增 trace panel UI。
  - 扩展 `tests/test_router_state_loop.py`。
- **关键设计决策**：
  - Clarification 优先级固定为：文件类型未知 > 标准化失败 > 缺失关键参数。
  - Trace panel 放在 assistant card 内部且默认折叠，避免破坏“一个回复一张卡片”的界面结构。
  - 复用现有 Tailwind-heavy 组件风格，只添加少量 CSS 以降低前端侵入性。
- **测试**：`141 -> 143`，新增 2 个测试。
- **论文对应章节**：未明确提及。

来源：`SPRINT5_FINAL_REPORT.md`。

## 四、Phase 2 详细工作记录（Sprint 6-10 + Bug Fix Sprints）

### Sprint 6: SpatialLayer 类型系统 + `render_spatial_map` 工具

- **目标**：建立统一的空间数据契约，并把地图渲染抽出为独立工具。
- **核心改动**：
  - 新建 `core/spatial_types.py`：定义 `SpatialLayer`、`SpatialDataPackage`。
  - 新建 `core/tool_dependencies.py`：引入 `TOOL_GRAPH`。
  - 新建 `tools/spatial_renderer.py`：实现 `render_spatial_map`。
  - 修改 `core/task_state.py`：增加 `available_results`。
  - 修改 `tools/definitions.py`、`tools/registry.py`、`core/router.py`、`config/prompts/core.yaml`。
  - 新建 `tests/test_spatial_types.py`、`tests/test_spatial_renderer.py`、`tests/test_tool_dependencies.py`。
- **关键设计决策**：
  - 后端显式输出渲染合同，前端不再“猜怎么画”。
  - `render_spatial_map` 输出仍保持 legacy-compatible `map_data` 形态，避免一次性打破旧前端。
  - `TOOL_GRAPH` 提前把 `calculate_dispersion` 依赖位保留下来，为 Sprint 9 铺路。
- **测试**：`143 -> 172`，新增 29 个测试。
- **论文对应章节**：未明确提及。

来源：`SPRINT6_SPATIAL_TOOL_REPORT.md`。

### Sprint 7 / 7B: 去上海绑定 + available_results + 自动可视化

- **目标**：让地图展示去除上海默认绑定，同时建立工具依赖与自动可视化基础设施。
- **核心改动**：
  - 修改 `core/router.py`：记录 `available_results`、检查依赖、自动触发 `render_spatial_map`。
  - 修改 `web/app.js`：底图从上海中心切换到 location-agnostic 逻辑。
  - 修改 `web/index.html`：更新缓存版本。
  - 新建 `tests/test_available_results_tracking.py`。
- **关键设计决策**：
  - 先把 dependency check 做成“观察与记录”，而不是立刻自动插入工具链，降低变更风险。
  - `render_spatial_map` 自动触发建立在“已有空间数据但尚未渲染”的检测上，避免重复地图。
  - 前端从固定城市中心切换为通用底图 + 可选叠加层，解除上海场景绑定。
- **测试**：`172 -> 181`，新增 9 个测试。
- **论文对应章节**：未明确提及。

来源：`SPRINT7_DESHANGH_REPORT.md`。

### Bug Fix Sprint: 空间数据流 / WKT / Trace 修复汇总

- **目标**：修复 `render_spatial_map` 在同轮/跨轮场景下拿不到完整几何的问题，并修正若干 trace / synthesis 细节。
- **核心改动**：
  - 在 Router 中建立三层注入：当前轮 `tool_results`、`memory.last_spatial_data`、`last_tool_snapshot` fallback。
  - 在 `FactMemory` 中新增 `last_spatial_data`，保存未压缩的完整空间结果。
  - 引入 5MB guard，避免 session JSON 因大几何 payload 膨胀。
  - 后续又把同一批修复汇总为 `Fix-WKT/DataFlow/Trace` 里程碑。
- **关键设计决策**：
  - 优先保留“完整结果供渲染使用”，再通过 snapshot 维持 memory 紧凑性。
  - Tier 1 / Tier 2 注入都要求显式验证几何存在，避免“data 有值但 geometry 缺失”的伪成功。
  - 同轮和跨轮统一使用相同的结果解包模式，减少嵌套结构差异带来的 bug。
- **测试**：
  - `FIX_SPATIAL_DATA_FLOW_REPORT.md` 记录为 `181 -> 190`。
  - `SPRINT10_FINAL_REPORT.md` 后续把 WKT/DataFlow/Trace 汇总记为 `181 -> 192 (+11)`。
  - 由于本次要求阅读的独立报告中只有 `FIX_SPATIAL_DATA_FLOW_REPORT.md`，WKT/Trace 两项未找到单独报告，故这里并列标注来源差异。
- **论文对应章节**：未明确提及。

来源：`FIX_SPATIAL_DATA_FLOW_REPORT.md`、`SPRINT10_FINAL_REPORT.md`。

### Sprint 8: 扩散计算引擎重构

- **总体目标**：把 `ps-xgb-aermod-rline-surrogate/mode_inference.py` 从 708 行 import 即执行脚本重构为可导入、可测试的 `DispersionCalculator` 计算模块。
- **总体测试变化**：`192 -> 240 (+48)`。

#### Sprint 8 Sub-task A：环境准备 + 纯函数提取

- **目标**：先把脚本中的硬编码依赖、纯函数和配置参数抽离，为类化改造打底。
- **核心改动**：
  - 安装依赖：`xgboost==3.2.0`、`scipy==1.17.1`；并在 `requirements.txt` 中加入 `xgboost>=1.7.0`、`scipy>=1.10.0`。
  - 新建 `calculators/dispersion.py` 骨架、`config/meteorology_presets.yaml`、`tests/test_dispersion_calculator.py`。
  - 预留 `calculators/__init__.py` 中的 `DispersionCalculator` 导出位。
- **提取函数与原始对应关系**：

| 提取项 | 新位置 | 原始对应 | 说明 |
|---|---|---|---|
| `convert_coords` | `dispersion.py:113-126` | `mode_inference.py:79-82` | 用 `pyproj.Transformer` 替换已弃用的 `transform` |
| `make_rectangular_buffer` | `dispersion.py:129-150` | `mode_inference.py:131-161` | 保留矩形 buffer 逻辑并补类型注解 |
| `generate_receptors_custom_offset` | `dispersion.py:153-261` | `mode_inference.py:164-309` | 删除 matplotlib 副作用，保留受体生成逻辑 |
| `split_polyline_by_interval_with_angle` | `dispersion.py:264-299` | `mode_inference.py:330-374` | 保留 10m 分段和角度计算 |
| `read_sfc` | `dispersion.py:302-310` | `mode_inference.py:431-434` | 保留 `.sfc` 读取 |
| `load_model` | `dispersion.py:313-317` | `mode_inference.py:465-468` | 保留单模型加载 |
| `predict_time_series_xgb` | `dispersion.py:320-337` | `mode_inference.py:490-668` | A 阶段仅保留签名与 docstring |
| `classify_stability` | `dispersion.py:340-365` | `mode_inference.py:448-457` | 抽成纯函数 |
| `compute_local_origin` | `dispersion.py:368-373` | `mode_inference.py:99-105` | 抽出 local origin 计算 |
| `inverse_transform_coords` | `dispersion.py:376-397` | 无直接对应 | 新增 local/UTM -> WGS84 逆变换 |
| `emission_to_line_source_strength` | `dispersion.py:400-414` | `mode_inference.py:120` | 抽出单位换算公式 |
| `load_all_models` | `dispersion.py:417-450` | `mode_inference.py:470-482` | 将 12 个模型加载程序化 |

- **关键设计决策**：
  - 先抽纯函数，再补类，降低一次性迁移复杂度。
  - 明确禁止在 calculator 层引入 `matplotlib` 等副作用代码。
  - 统一把 CRS、粗糙度、受体参数放进 `DispersionConfig`，避免脚本硬编码散落。
- **测试**：`192 -> 216`，新增 24 个测试。

来源：`SPRINT8A_REPORT.md`。

#### Sprint 8 Sub-task B：`predict_time_series_xgb` + `DispersionCalculator` 类 + Adapter

- **目标**：迁移 surrogate 推理主逻辑，并封装完整的 calculator 类与 emission-to-dispersion adapter。
- **核心改动**：
  - 实现 `predict_time_series_xgb()`。
  - 在 `calculators/dispersion.py` 中新增 `DispersionCalculator` 类。
  - 新建 `calculators/dispersion_adapter.py`。
  - 正式导出 `DispersionCalculator`。
- **`DispersionCalculator.calculate()` 内部流程**：
  1. `_validate_inputs()`
  2. `_merge_roads_and_emissions()`
  3. `_transform_to_local()`
  4. `_segment_roads()`
  5. `_generate_receptors()`
  6. `_build_source_arrays()`
  7. `_process_meteorology()`
  8. `_align_sources_and_met()`
  9. `_ensure_models_loaded()`
  10. `predict_time_series_xgb()`
  11. `inverse_transform_coords()`
  12. `_assemble_result()`
- **与原始 `mode_inference.py` 的数值等价性说明**：
  - 保持按时间步循环、`theta = deg2rad(270 - wind_deg)` 的旋转公式。
  - 保持 downwind / upwind 分支与 `preds * strength / 1e-6` 累积公式。
  - 保持 legacy feature layout 与 receptor 聚合方式。
  - 用 logging 代替 print，并兼容 `xgb.Booster` / `xgb.XGBRegressor` 两类模型对象。
- **Adapter 设计**：
  - `link_id -> NAME_1`
  - `total_emissions_kg_per_hr.NOx -> nox`
  - `link_length_km -> length`
  - 支持从宏观排放结果或外部 geometry source 解析 WKT / GeoJSON / 坐标数组 / Shapely geometry
- **关键设计决策**：
  - Adapter 单独拆层，避免把宏观排放结构知识写死到 calculator 内部。
  - `.sfc` 读取改用 `sep=r"\\s+"` 以适配新 pandas。
  - 需求里提到的 HC 处理以“保留 legacy 7/8 维特征分支”为准，优先保证数值等价。
- **测试**：`216 -> 233`，新增 17 个测试。

来源：`SPRINT8B_REPORT.md`。

#### Sprint 8 Sub-task C：数值等价性验证 + 代码清理 + 结题

- **目标**：验证重构代码与 legacy 脚本数值一致，并完成质量审计。
- **核心改动**：
  - 新建 `tests/test_dispersion_numerical_equivalence.py`。
  - 清理 `print()`、`matplotlib` 残留、未使用 import，补齐 docstring 和类型注解。
  - 修正 `classify_stability()` 以严格贴合 legacy 逻辑。
- **数值等价性测试覆盖**：
  - `convert_to_utm` vs `convert_coords`：坐标差异 `< 0.01m`
  - `classify_stability`：边界值 `100%` 一致
  - `split_polyline_by_interval_with_angle`：段数一致、误差 `< 1e-6`
  - `emission_to_line_source_strength`：公式完全一致
  - `predict_time_series_xgb`：特征向量与浓度累积公式一致
  - `DispersionCalculator` 与 `EmissionToDispersionAdapter` 端到端 smoke 通过
- **代码质量审计结果**：
  - `calculators/dispersion.py`、`calculators/dispersion_adapter.py` 无 `print` / `matplotlib`
  - 导出链路与 import 验证通过
  - 当前接口稳定为 `{"status": "success", "data": {...}}`
- **测试**：`233 -> 240`；Sprint 8 全部完成后 `240 passed`。

来源：`SPRINT8_FINAL_REPORT.md`、`SPRINT10_FINAL_REPORT.md`。

### Sprint 9: `calculate_dispersion` 工具接入

- **总体目标**：把 `DispersionCalculator` 接到 function-calling 工具层，让 LLM 可直接调用扩散计算。
- **总体测试变化**：`240 -> 290 (+50)`。

#### Sprint 9 Sub-task A：Schema + `DispersionTool` + 工具注册

- **目标**：新增 `calculate_dispersion` 的 tool schema、工具类和注册流程。
- **核心改动**：
  - 修改 `tools/definitions.py`：新增 `calculate_dispersion` schema。
  - 新建 `tools/dispersion.py`：实现 `DispersionTool`。
  - 修改 `tools/registry.py`：注册第 7 个工具。
  - 修改 `core/router.py`：支持 `calculate_dispersion` 的 `_last_result` 注入与 `concentration_grid` 空间数据保存。
  - 新建 `tests/test_dispersion_tool.py`。
- **关键设计决策**：
  - 工具注册失败使用 `warning` 而非 `error`，避免 `xgboost/scipy` 缺失时拖垮其他工具。
  - `DispersionTool` 按 `roughness_height` 缓存 calculator 实例，而不是每次重建。
  - `map_data` 显式透传 `concentration_grid`，为 Sprint 10 的渲染分支留好接口。
- **测试**：`240 -> 260`，新增 20 个测试。

来源：`SPRINT9A_REPORT.md`。

#### Sprint 9 Sub-task B：气象标准化 + 端到端集成测试

- **目标**：把 meteorology / stability class 接入执行层标准化，并打通 macro->dispersion 主链的端到端测试。
- **核心改动**：
  - 修改 `services/standardizer.py`：新增 `standardize_meteorology()`、`standardize_stability_class()`。
  - 修改 `config/unified_mappings.yaml`：加入气象预设和稳定度 alias。
  - 修改 `core/executor.py`：让 `calculate_dispersion` 支持 `meteorology` 与 `stability_class` 标准化。
  - 新建 `tests/test_dispersion_integration.py`。
- **完整调用链路图**：

```text
LLM function call
  -> executor._standardize_arguments()
  -> DispersionTool.execute()
    -> _resolve_emission_source()
    -> EmissionToDispersionAdapter.adapt()
    -> _build_met_input()
    -> DispersionCalculator.calculate()
    -> _build_summary() + _build_map_data()
  -> ToolResult
  -> router 保存 last_spatial_data [concentration_grid]
  -> synthesis
  -> 前端
```

- **关键设计决策**：
  - 仅标准化离散语义参数，数值型 `wind_speed` / `mixing_height` 等参数原样透传。
  - `meteorology` 同时支持精确名、中文/英文 alias、`custom` 与 `.sfc` 路径。
  - 集成测试只 mock surrogate 模型加载，不 mock calculator 主流程，保证数据流真实经过 adapter 与 calculator。
- **测试**：Sprint 9 完成后 `290 passed`。

来源：`SPRINT9_FINAL_REPORT.md`。

### Sprint 10: concentration 渲染 + 端到端联调

- **总体目标**：把扩散结果真正渲染到前端地图，并补齐 macro -> dispersion -> renderer 的链路测试。
- **总体测试变化**：`290 -> 305 (+15)`。

#### Sprint 10 Sub-task A：concentration 图层渲染（后端 + 前端）

- **目标**：实现 `render_spatial_map` 的 concentration 分支，并在前端支持浓度点图层。
- **核心改动**：
  - 修改 `tools/spatial_renderer.py`：实现 `_build_concentration_map()`。
  - 修改 `web/app.js`：新增 `renderConcentrationMap()`、`initConcentrationLeafletMap()`、`getConcentrationColor()` 等逻辑。
  - 修改 `tests/test_spatial_renderer.py`：补 concentration 渲染测试。
- **关键设计决策**：
  - 保持 `_build_emission_map()` 完全不动，浓度渲染独立扩展。
  - MVP 采用 `CircleMarker + YlOrRd`，先保障结构正确与交互可用，不急于上热力图。
  - 后端同时支持 `concentration_grid` 与 receptor `results` 两种输入路径。
- **测试**：`290 -> 297`，新增 7 个测试；`-k "concentration"` 跑出 8 个通过是因为匹配到 1 个既有测试。

来源：`SPRINT10A_REPORT.md`。

#### Sprint 10 Sub-task B：端到端联调验证 + Phase 2 结题

- **目标**：验证 `macro_emission -> dispersion -> spatial_renderer` 的完整链路，并完成 Phase 2 收口。
- **核心改动**：
  - 修改 `tests/test_dispersion_integration.py`：新增 8 个链路级测试。
  - 新建 `SPRINT10_FINAL_REPORT.md`：汇总 Phase 2 里程碑与当前能力。
- **关键设计决策**：
  - 本子任务只加测试和报告，不再改非测试代码，避免 Phase 2 收尾阶段引入新回归。
  - Router 层的 `last_spatial_data` 保存/注入逻辑被当作链路测试对象，保证跨轮 concentration 可视化有证据支撑。
  - `TOOL_GRAPH` 的 `macro -> dispersion -> render` 链在测试中显式验证，而不是只依赖人工推断。
- **测试**：`297 -> 305`；当前全量 `305 passed, 19 warnings`。

来源：`SPRINT10_FINAL_REPORT.md`。

## 五、关键文件清单

以下表格汇总 Phase 1-2 中新建或重要修改的关键文件。行数均通过当前仓库 `wc -l` 实测。

| 文件路径 | 状态 | 行数 | 创建/修改于 | 职责描述 |
|---|---|---:|---|---|
| `config.py` | 修改 | 114 | Sprint 1 | 新增状态机/trace 相关 feature flags |
| `core/task_state.py` | 修改 | 283 | Sprint 1, 6 | 5 状态状态机与任务上下文数据模型 |
| `core/trace.py` | 新建 | 283 | Sprint 2 | 结构化 Trace 与友好渲染 |
| `tools/file_analyzer.py` | 修改 | 601 | Sprint 3 | 多信号文件 grounding |
| `services/standardizer.py` | 修改 | 758 | Sprint 4, 9 | 参数与气象标准化 |
| `core/executor.py` | 修改 | 304 | Sprint 4, 9 | 参数标准化接入与工具执行 |
| `core/router.py` | 修改 | 1410 | Sprint 1/2/4/5/6/7/Fix/9 | 统一编排、依赖检查、空间注入、synthesis |
| `api/session.py` | 修改 | 266 | Sprint 1, 2, 5 | 会话 history 与 trace 透传 |
| `api/models.py` | 修改 | 110 | Sprint 1, 2, 5 | API 响应模型扩展 |
| `api/routes.py` | 修改 | 951 | Sprint 1, 2, 5 | `/api/chat` 与历史/流式结果返回 |
| `web/index.html` | 修改 | 806 | Sprint 5, 7 | trace panel 与地图页面结构 |
| `web/app.js` | 修改 | 2509 | Sprint 5, 7, 10 | trace UI、去上海、concentration 图层前端渲染 |
| `core/spatial_types.py` | 新建 | 149 | Sprint 6 | 空间图层与数据包类型系统 |
| `core/tool_dependencies.py` | 新建 | 75 | Sprint 6 | 工具依赖图与 prerequisite 查询 |
| `tools/spatial_renderer.py` | 新建/修改 | 497 | Sprint 6, 10 | emission/concentration 空间渲染工具 |
| `tools/definitions.py` | 修改 | 269 | Sprint 6, 9 | 工具 function-calling schema |
| `tools/registry.py` | 修改 | 125 | Sprint 6, 9 | 工具注册与初始化 |
| `tests/test_spatial_types.py` | 新建 | 142 | Sprint 6 | SpatialLayer/SpatialDataPackage 测试 |
| `tests/test_spatial_renderer.py` | 新建/修改 | 328 | Sprint 6, 10 | emission 与 concentration 渲染测试 |
| `tests/test_tool_dependencies.py` | 新建 | 55 | Sprint 6 | TOOL_GRAPH 测试 |
| `tests/test_available_results_tracking.py` | 新建 | 58 | Sprint 7 | available_results 与依赖集成测试 |
| `calculators/dispersion.py` | 新建 | 1213 | Sprint 8 | surrogate 扩散核心引擎与 `DispersionCalculator` |
| `calculators/dispersion_adapter.py` | 新建 | 150 | Sprint 8B | 宏观排放结果到扩散输入的桥接层 |
| `config/meteorology_presets.yaml` | 新建 | 54 | Sprint 8A | 6 个气象预设场景 |
| `tests/test_dispersion_calculator.py` | 新建/扩展 | 585 | Sprint 8A/B | dispersion 纯函数、calculator、adapter 测试 |
| `tests/test_dispersion_numerical_equivalence.py` | 新建 | 344 | Sprint 8C | legacy script 与新 calculator 数值等价性测试 |
| `tools/dispersion.py` | 新建 | 257 | Sprint 9A | `calculate_dispersion` 工具封装 |
| `config/unified_mappings.yaml` | 修改 | 574 | Sprint 4, 9 | 参数与气象 alias 配置 |
| `tests/test_dispersion_tool.py` | 新建 | 386 | Sprint 9A | DispersionTool 工具层测试 |
| `tests/test_dispersion_integration.py` | 新建/修改 | 635 | Sprint 9B, 10B | macro->dispersion->renderer 链路测试 |
| `tests/test_task_state.py` | 新建 | 165 | Sprint 1 | TaskState 单元测试 |
| `tests/test_trace.py` | 新建 | 191 | Sprint 2 | Trace 单元测试 |
| `tests/test_file_grounding_enhanced.py` | 新建 | 179 | Sprint 3 | 多信号 file grounding 测试 |
| `tests/test_standardizer_enhanced.py` | 新建 | 166 | Sprint 4 | 结构化标准化与 executor records 测试 |
| `tests/test_router_state_loop.py` | 修改 | 342 | Sprint 1-10 持续扩展 | Router 状态循环与空间注入回归测试 |

## 六、测试体系

### 6.1 测试增长曲线

| 时间点 | 测试总数 | 增量 | 说明 |
|---|---:|---:|---|
| Phase 1 前 | 未记录 | - | 已读报告未给出 Sprint 1 前基线 |
| Sprint 1 后 | 92 | 未记录 | TaskState + Router state loop |
| Sprint 2 后 | 106 | +14 | Trace |
| Sprint 3 后 | 124 | +18 | File grounding |
| Sprint 4 后 | 141 | +17 | Standardization |
| Sprint 5 后 | 143 | +2 | Clarification + 前端 trace panel |
| Sprint 6 后 | 172 | +29 | Spatial types + renderer + dependencies |
| Sprint 7 后 | 181 | +9 | available_results + de-Shanghai |
| Fix: Spatial Data Flow 后 | 190 | +9 | 仅 `FIX_SPATIAL_DATA_FLOW_REPORT.md` 明确记录的数据流修复批次 |
| Fix-WKT/DataFlow/Trace 汇总值 | 192 | +11 | 来源于 `SPRINT10_FINAL_REPORT.md` 汇总；缺单独 WKT/Trace 报告 |
| Sprint 8A 后 | 216 | +24 | 纯函数提取与环境准备 |
| Sprint 8B 后 | 233 | +17 | `predict_time_series_xgb` + calculator + adapter |
| Sprint 8 后 | 240 | +48 | 数值等价性与代码清理完成 |
| Sprint 9A 后 | 260 | +20 | tool schema + registration |
| Sprint 9 后 | 290 | +50 | 气象标准化 + 集成测试 |
| Sprint 10A 后 | 297 | +7 | concentration 渲染测试 |
| Sprint 10 后 | 305 | +15 | 端到端联调与 Phase 2 收尾 |

### 6.2 当前测试分布

当前 `pytest --co -q` 收集到 `305` 个测试；`find tests/ -name "*.py" -exec wc -l {} +` 统计测试代码总行数为 `5332`。下表按测试文件统计分布：

| 测试文件 | 测试数 | 覆盖范围 |
|---|---:|---|
| `tests/test_api_chart_utils.py` | 4 | 图表辅助函数与 API chart payload |
| `tests/test_api_response_utils.py` | 4 | API response 清洗、download metadata、友好错误 |
| `tests/test_api_route_contracts.py` | 3 | API route 顶层契约 |
| `tests/test_available_results_tracking.py` | 9 | available_results 与 dependency integration |
| `tests/test_calculators.py` | 20 | VSP、微观、宏观、排放因子 calculator |
| `tests/test_config.py` | 9 | 配置加载与 JWT secret |
| `tests/test_dispersion_calculator.py` | 41 | dispersion 纯函数、calculator、adapter、气象预设 |
| `tests/test_dispersion_integration.py` | 38 | macro->dispersion->renderer 集成链、标准化、router concentration 注入 |
| `tests/test_dispersion_numerical_equivalence.py` | 7 | dispersion 与 legacy script 数值等价性 |
| `tests/test_dispersion_tool.py` | 20 | DispersionTool schema/execute/registry/router |
| `tests/test_file_grounding_enhanced.py` | 18 | 多信号 file grounding |
| `tests/test_micro_excel_handler.py` | 1 | 轨迹 Excel 读取 |
| `tests/test_phase1b_consolidation.py` | 5 | 兼容导出与 phase1b consolidation |
| `tests/test_router_contracts.py` | 18 | router helper contract、payload/render/synthesis utils |
| `tests/test_router_state_loop.py` | 8 | Router 状态循环、clarification、空间数据保存/注入 |
| `tests/test_smoke_suite.py` | 1 | smoke suite 输出 |
| `tests/test_spatial_renderer.py` | 29 | emission/concentration 渲染、WKT 解析 |
| `tests/test_spatial_types.py` | 7 | 空间类型序列化与 bounds 计算 |
| `tests/test_standardizer.py` | 14 | vehicle/pollutant/column mapping 标准化 |
| `tests/test_standardizer_enhanced.py` | 17 | 结构化标准化、season/road_type、executor records |
| `tests/test_task_state.py` | 10 | TaskState 初始化、转换、序列化 |
| `tests/test_tool_dependencies.py` | 9 | TOOL_GRAPH 与 prerequisite 查询 |
| `tests/test_trace.py` | 13 | Trace/TraceStep 与友好输出 |

说明：

- `tests/conftest.py` 与 `tests/__init__.py` 不计入测试数。
- `pytest --co -q` 的完整测试名清单已实际收集；正文采用按文件聚合的方式呈现，避免 305 条用例名使总结文档失控膨胀。

## 七、技术演进

按时间线梳理，Phase 1-2 的关键技术演进如下：

1. **Sprint 1**：引入 `TaskState` 显式状态机，替代隐式 flag 驱动流程。
2. **Sprint 1**：在 Router 内保留 legacy loop 与新 state loop 双轨运行，降低架构切换风险。
3. **Sprint 2**：建立 `Trace` / `TraceStep` 审计链路，使工具选择与执行决策可回放、可前端展示。
4. **Sprint 3**：文件理解从“列名匹配”升级为“三信号 grounding”，把文件从被动附件变成主动任务入口。
5. **Sprint 4**：参数标准化引入结构化 `StandardizationResult` 和 abstain 机制，避免模糊值直接进入 calculator。
6. **Sprint 5**：状态机新增 clarification 分支，系统能够在缺关键信息时主动追问。
7. **Sprint 6**：建立 `SpatialLayer`/`SpatialDataPackage` 空间类型系统，并把 `render_spatial_map` 抽成独立工具。
8. **Sprint 7**：引入 `available_results` 和 `TOOL_GRAPH` 驱动的结果依赖跟踪，同时解除前端“上海默认中心”绑定。
9. **Fix Sprint**：空间数据流改成“三层注入 + last_spatial_data 持久化”，修复跨轮地图渲染数据缺失。
10. **Sprint 8A**：`pyproj.transform` 被 `pyproj.Transformer` 替换，legacy 脚本纯函数化。
11. **Sprint 8B/C**：`mode_inference.py` 从 708 行顶层脚本扩展为 1213 行可导入 `DispersionCalculator`，同时通过数值等价性测试锁定核心数学路径。
12. **Sprint 9**：扩散能力接入工具层，新增 `calculate_dispersion` schema、工具类、气象预设/稳定度标准化。
13. **Sprint 10**：浓度结果从“后端可算”推进到“后端可渲染 + 前端可展示”，形成 emission 线图层 + concentration 点图层双空间表达。

来源：`SPRINT1_TASKSTATE_REPORT.md` 至 `SPRINT10_FINAL_REPORT.md`，以及当前代码。

## 八、当前系统状态快照

### 8.1 `python main.py health`

```text
WARNING:skills.knowledge.retriever:FlagEmbedding 未安装，本地embedding功能不可用
╭───────────────────╮
│ Tool Health Check │
╰───────────────────╯
OK query_emission_factors
OK calculate_micro_emission
OK calculate_macro_emission
OK analyze_file
OK query_knowledge
OK calculate_dispersion
OK render_spatial_map

Total tools: 7
```

### 8.2 `pytest -q`

```text
======================= 305 passed, 19 warnings in 6.51s =======================
```

### 8.3 关键文件行数汇总

```text
1213 calculators/dispersion.py
 150 calculators/dispersion_adapter.py
 257 tools/dispersion.py
 497 tools/spatial_renderer.py
 269 tools/definitions.py
1410 core/router.py
 283 core/task_state.py
 283 core/trace.py
 149 core/spatial_types.py
  75 core/tool_dependencies.py
 758 services/standardizer.py
  54 config/meteorology_presets.yaml
 574 config/unified_mappings.yaml
2509 web/app.js
```

### 8.4 关键 import 验证

```text
All imports OK
Meteorology: urban_summer_day
Stability: U
DispersionCalculator: DispersionCalculator
Adapter: EmissionToDispersionAdapter
DispersionTool: DispersionTool
SpatialRendererTool: SpatialRendererTool
```

### 8.5 当前工具列表

```text
WARNING:skills.knowledge.retriever:FlagEmbedding 未安装，本地embedding功能不可用
╭─────────────────╮
│ Available Tools │
╰─────────────────╯
- query_emission_factors
- calculate_micro_emission
- calculate_macro_emission
- analyze_file
- query_knowledge
- calculate_dispersion
- render_spatial_map
```

## 九、已知限制与后续规划

### 9.1 已知限制

- 扩散 surrogate 目前仅支持 `NOx`。
- 所有扩散相关测试仍使用 mock 模型，142MB 真实模型未进入 CI。
- emission 与 meteorology 的时间对齐仍主要覆盖“等长”与“单步复制”场景。
- concentration 前端当前采用 `CircleMarker`，高密度受体场景可能需要热力图或聚合。
- 前端多图层共存与浏览器交互尚未建立自动化 UI 测试。
- 本次任务要求读取的项目状态文档 `EmissionAgent_Project_Status_v2.md` 缺失，说明状态文档体系仍有缺口。

### 9.2 技术债

- Router、memory、spatial renderer 在 Phase 2 期间经历了多轮 hotfix，接口已稳定，但相关设计文档分散在多个 Sprint 报告中，尚未收敛为统一开发文档。
- 旧架构/旧脚本文档仍散落在仓库中，论文与工程口径需要进一步统一。
- 本地知识检索依赖 `FlagEmbedding`，当前环境缺失时会在 `health`/`tools-list` 输出 warning。
- 真实 surrogate 模型集成验证、benchmark 数据集和 paper-ready 评测资产尚未沉淀。

### 9.3 后续路线图

1. **真实模型集成测试**：用实际 surrogate 模型跑一套可复现实例。
2. **Benchmark 构建**：沉淀 40-50 个排放/扩散/混合场景基准用例。
3. **实验设计**：覆盖端到端准确性、组件级消融、交互负担和失败模式分析。
4. **文档收敛**：补齐缺失的项目状态文档，统一主链 architecture / Sprint / benchmark 文档。
5. **论文写作**：围绕“文件感知 + 执行侧标准化 + 多工具计算与空间展示”主线组织系统论文材料。

---

## 附录：生成时间与验证命令实际输出

### A. 生成时间

```text
2026-03-21T17:35:34+08:00
```

### B. Python 版本

```text
Python 3.13.9
```

### C. `pytest --co -q` 摘要输出

```text
============================= test session starts ==============================
platform linux -- Python 3.13.9, pytest-9.0.2, pluggy-1.5.0
rootdir: /home/kirito/Agent1/emission_agent
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.12.1
collected 305 items
...
========================= 305 tests collected in 1.64s =========================
```

### D. `find tests/ -name "*.py" -exec wc -l {} +`

```text
     0 tests/__init__.py
    24 tests/conftest.py
    30 tests/test_micro_excel_handler.py
    55 tests/test_tool_dependencies.py
    58 tests/test_available_results_tracking.py
    63 tests/test_phase1b_consolidation.py
    68 tests/test_api_response_utils.py
    70 tests/test_smoke_suite.py
    79 tests/test_config.py
    82 tests/test_api_chart_utils.py
    94 tests/test_standardizer.py
   128 tests/test_api_route_contracts.py
   142 tests/test_spatial_types.py
   165 tests/test_task_state.py
   166 tests/test_standardizer_enhanced.py
   179 tests/test_file_grounding_enhanced.py
   191 tests/test_trace.py
   319 tests/test_calculators.py
   328 tests/test_spatial_renderer.py
   342 tests/test_router_state_loop.py
   344 tests/test_dispersion_numerical_equivalence.py
   386 tests/test_dispersion_tool.py
   585 tests/test_dispersion_calculator.py
   635 tests/test_dispersion_integration.py
  5332 total
```

### E. `wc -l` 关键代码文件

```text
  1213 calculators/dispersion.py
   150 calculators/dispersion_adapter.py
   257 tools/dispersion.py
   497 tools/spatial_renderer.py
   269 tools/definitions.py
  1410 core/router.py
   283 core/task_state.py
   283 core/trace.py
   149 core/spatial_types.py
    75 core/tool_dependencies.py
   758 services/standardizer.py
    54 config/meteorology_presets.yaml
   574 config/unified_mappings.yaml
  2509 web/app.js
```

### F. `python main.py health`

```text
WARNING:skills.knowledge.retriever:FlagEmbedding 未安装，本地embedding功能不可用
╭───────────────────╮
│ Tool Health Check │
╰───────────────────╯
OK query_emission_factors
OK calculate_micro_emission
OK calculate_macro_emission
OK analyze_file
OK query_knowledge
OK calculate_dispersion
OK render_spatial_map

Total tools: 7
```

### G. `python main.py tools-list`

```text
WARNING:skills.knowledge.retriever:FlagEmbedding 未安装，本地embedding功能不可用
╭─────────────────╮
│ Available Tools │
╰─────────────────╯
- query_emission_factors
- calculate_micro_emission
- calculate_macro_emission
- analyze_file
- query_knowledge
- calculate_dispersion
- render_spatial_map
```

### H. import 验证

```text
All imports OK
Meteorology: urban_summer_day
Stability: U
DispersionCalculator: DispersionCalculator
Adapter: EmissionToDispersionAdapter
DispersionTool: DispersionTool
SpatialRendererTool: SpatialRendererTool
```

### I. `pytest -q`

```text
======================= 305 passed, 19 warnings in 6.51s =======================
```

### J. `node -c web/app.js`

```text
[no output; syntax check passed]
```
