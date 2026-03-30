# EmissionAgent Codebase Status Report

**Generated:** 2026-03-29
**Auditor:** Architecture audit (code-based, no speculation)
**Basis:** Direct code reading of all major modules

---

## 第一部分：代码库全景扫描

### 1.1 目录结构

```
emission_agent/
├── api/                        # FastAPI HTTP层（路由、认证、数据库、session管理）
│   ├── auth.py                 # JWT认证中间件
│   ├── database.py             # SQLite数据库（用户、session持久化）
│   ├── main.py                 # FastAPI app启动、CORS、静态文件挂载
│   ├── models.py               # Pydantic请求/响应模型
│   ├── routes.py               # /api/* 路由定义（chat、upload、session等）
│   ├── response_utils.py       # 响应格式化工具
│   ├── chart_utils.py          # 图表数据格式化
│   ├── logging_config.py       # 访问日志中间件
│   └── session.py              # Session状态管理（per-request router实例化）
├── calculators/                # 物理计算核心（不依赖LLM）
│   ├── dispersion.py           # 大气扩散计算（Gaussian/AERMOD代理）
│   ├── dispersion_adapter.py   # 扩散计算适配层
│   ├── emission_factors.py     # 排放因子查询（按速度曲线）
│   ├── hotspot_analyzer.py     # 热点识别算法
│   ├── macro_emission.py       # 宏观排放计算（路段级）
│   ├── micro_emission.py       # 微观排放计算（逐秒轨迹）
│   ├── scenario_comparator.py  # 情景对比计算
│   └── vsp.py                  # VSP（车辆比功率）计算
├── config/                     # 配置文件目录
│   ├── unified_mappings.yaml   # 所有参数映射表（598行）—— 核心配置
│   ├── meteorology_presets.yaml# 气象预设参数
│   ├── prompts/                # LLM提示词模板（系统提示词）
│   └── skills/                 # 技能配置（已被tools替代）
├── config.py                   # Python配置类（AppConfig dataclass），读取.env
├── core/                       # 主编排层（路由、状态机、治理逻辑）
│   ├── router.py               # UnifiedRouter主类（9999行）—— 系统核心
│   ├── task_state.py           # TaskState复合数据类 + TaskStage状态枚举
│   ├── trace.py                # Trace审计记录（1031行，~104个TraceStepType）
│   ├── readiness.py            # 预执行门控（1489行，ReadinessAssessment）
│   ├── tool_dependencies.py    # TOOL_GRAPH依赖声明 + 验证函数
│   ├── plan.py                 # ExecutionPlan + PlanStep + PlanStepStatus
│   ├── plan_repair.py          # PlanRepairDecision，8种RepairActionType
│   ├── workflow_templates.py   # 5个硬编码工作流模板
│   ├── parameter_negotiation.py# 参数协商（确定性解析，非LLM）
│   ├── remediation_policy.py   # 修复策略（HCM引用，查找表）
│   ├── capability_summary.py   # 能力摘要（注入synthesis提示词）
│   ├── assembler.py            # ContextAssembler（拼接LLM上下文）
│   ├── executor.py             # ToolExecutor（调用tools，带标准化）
│   ├── context_store.py        # SessionContextStore（跨轮工具结果存储）
│   ├── memory.py               # MemoryManager（working/fact memory）
│   ├── artifact_memory.py      # ArtifactMemoryState（已交付制品追踪）
│   ├── file_analysis_fallback.py # LLM fallback（低置信度文件分析）
│   ├── file_relationship_resolution.py # 多文件关系解析
│   ├── geometry_recovery.py    # 几何信息恢复（补充空间文件）
│   ├── input_completion.py     # 缺失字段补全协商
│   ├── intent_resolution.py    # 用户意图解析
│   ├── residual_reentry.py     # 残留工作流重入
│   ├── supplemental_merge.py   # 补充文件列合并
│   ├── summary_delivery.py     # 结构化摘要交付
│   ├── coverage_assessment.py  # 空间覆盖评估
│   ├── skill_injector.py       # 技能注入
│   ├── spatial_types.py        # 空间类型定义
│   ├── output_safety.py        # 输出安全过滤（sanitize_response）
│   ├── router_memory_utils.py  # 路由器内存工具函数（从router.py提取）
│   ├── router_payload_utils.py # 路由器载荷工具函数
│   ├── router_render_utils.py  # 路由器渲染工具函数
│   └── router_synthesis_utils.py # 路由器合成工具函数
├── data/                       # 运行时数据
│   ├── collection/             # 数据收集缓存
│   ├── learning/               # 学习案例存储
│   ├── logs/                   # 运行日志
│   ├── sessions/               # Session JSON文件
│   └── users.db                # SQLite用户数据库
├── evaluation/                 # 评估脚本（非生产路径）
│   ├── eval_end2end.py         # 端到端评估
│   ├── eval_file_grounding.py  # 文件识别评估
│   ├── eval_normalization.py   # 标准化准确率评估
│   └── run_smoke_suite.py      # 冒烟测试套件
├── llm/                        # LLM客户端封装
│   ├── client.py               # LLM客户端（chat/chat_with_tools）
│   └── data_collector.py       # 训练数据收集
├── services/                   # 服务层
│   ├── config_loader.py        # 配置加载器（读取YAML）
│   ├── llm_client.py           # LLM客户端工厂（get_llm_client）
│   ├── standardizer.py         # UnifiedStandardizer（758行）
│   └── standardization_engine.py # StandardizationEngine（批量标准化，1029行）
├── shared/standardizer/        # 共享标准化工具（历史遗留）
│   ├── constants.py            # 内联映射表（与YAML有重叠）
│   ├── cache.py                # 标准化缓存
│   ├── local_client.py         # 本地LoRA模型客户端
│   ├── vehicle.py              # 车辆标准化器
│   └── pollutant.py            # 污染物标准化器
├── skills/                     # 遗留技能层（部分仍被使用）
│   ├── macro_emission/skill.py # 宏观排放技能（有excel_handler）
│   ├── micro_emission/skill.py # 微观排放技能
│   └── knowledge/skill.py      # 知识检索技能
├── tools/                      # 工具层（9个工具）
│   ├── base.py                 # BaseTool ABC, ToolResult, PreflightCheckResult
│   ├── registry.py             # ToolRegistry单例 + init_tools()
│   ├── definitions.py          # 工具JSON schema（OpenAI格式）
│   ├── file_analyzer.py        # FileAnalyzerTool（1462行）
│   ├── emission_factors.py     # EmissionFactorsTool
│   ├── micro_emission.py       # MicroEmissionTool
│   ├── macro_emission.py       # MacroEmissionTool
│   ├── dispersion.py           # DispersionTool（含preflight_check）
│   ├── hotspot.py              # HotspotTool
│   ├── spatial_renderer.py     # SpatialRendererTool
│   ├── scenario_compare.py     # ScenarioCompareTool
│   ├── knowledge.py            # KnowledgeTool
│   ├── formatter.py            # 格式化工具函数
│   └── override_engine.py      # 参数覆盖引擎
├── tests/                      # 测试目录（50+文件）
├── web/                        # 前端HTML/JS/CSS
├── main.py                     # 开发模式入口（uvicorn启动）
├── run_api.py                  # 生产模式API入口
└── config.py                   # 全局配置（AppConfig）
```

### 1.2 核心模块识别

| 职责 | 文件 | 位置说明 |
|------|------|----------|
| 主入口/路由分发 | `core/router.py` | `UnifiedRouter.chat()` L700；分发到 `_run_state_loop()` 或 `_run_legacy_loop()` |
| 文件分析/解析 | `tools/file_analyzer.py` | `FileAnalyzerTool.execute()` L39，规则+LLM fallback |
| 参数标准化/映射 | `services/standardizer.py` | `UnifiedStandardizer`，`services/standardization_engine.py` 批量版 |
| 参数校验/约束 | `core/readiness.py` | `build_readiness_assessment()`，字段完整性+工具依赖检查 |
| 任务状态管理 | `core/task_state.py` | `TaskState` dataclass + `TaskStage` enum |
| 工作流编排/工具调度 | `core/router.py` | `_state_handle_input/grounded/executing()`，L8169/L8750/L8807 |
| 工具定义与注册 | `tools/definitions.py`（JSON schema），`tools/registry.py`（注册），`core/tool_dependencies.py`（依赖图） | 三处分散 |
| 结果合成/响应生成 | `core/router.py` `_synthesize_results()` L9777；`core/router_synthesis_utils.py`；`core/router_render_utils.py` | LLM synthesis + deterministic render |
| 记忆/上下文管理 | `core/memory.py`（MemoryManager），`core/context_store.py`（SessionContextStore） | |
| Trace/审计记录 | `core/trace.py` | `Trace.record()` 在所有决策点被调用 |
| 配置文件 | `config/unified_mappings.yaml`，`config/meteorology_presets.yaml`，`.env` | |
| 测试文件 | `tests/` 目录下50+文件 | |

---

## 第二部分：数据流追踪

### 数据流 A：用户上传CSV文件 → 系统识别任务类型 → 参数标准化 → 执行排放计算 → 返回结果

#### 步骤1：入口

**文件：** `api/routes.py`（HTTP层）→ `api/session.py`（获取或创建 `UnifiedRouter`）→ `core/router.py` `UnifiedRouter.chat(user_message, file_path)`

- **输入：** `user_message: str`，`file_path: str`（已上传到服务器临时路径），`trace: Optional[Dict]`
- **处理：** L706-711，检查 `config.enable_state_orchestration`，分发到 `_run_state_loop()` 或 `_run_legacy_loop()`
- **输出：** 进入其中一个执行路径

---

#### 步骤2：文件分析（state loop路径）

**文件：** `core/router.py` `_state_handle_input()` L8169，`core/router.py` `_analyze_file()` L9765，`tools/file_analyzer.py`

**调用链：**
```
_state_handle_input(state)
  → state.file_context.has_file=True，state.file_context.grounded=False
  → 检查缓存：memory.get_fact_memory().get("file_analysis")
  → 若无缓存：_analyze_file(file_path_str)
      → executor.execute("analyze_file", {"file_path": file_path})
          → FileAnalyzerTool.execute(file_path)
              → pd.read_csv(file_path)  [CSV]
              → _analyze_structure(df, filename)
                  → _analyze_value_features(df)  [数值特征分析]
                  → _identify_task_type(columns, value_features)  [任务类型识别]
                  → standardizer.map_columns(columns, "micro_emission")
                  → standardizer.map_columns(columns, "macro_emission")
                  → _build_missing_field_diagnostics(...)
```

**文件分析方法（`_identify_task_type()`，L706-864）：**

三个信号按加权评分：

- **Signal 1（列名关键词）：** 遍历所有列名，micro关键词（speed/velocity/time/acceleration/速度/加速）每命中+1分，macro关键词（length/flow/volume/traffic/link/长度/流量）每命中+1分
- **Signal 2（值域特征）：** `_analyze_value_features()` 对每列数值进行分析，生成feature_hints列表（如 `possible_vehicle_speed_ms`、`possible_traffic_flow`、`possible_link_length`），对应微观/宏观信号再加分
- **Signal 3（必填字段完整性）：** 调用标准化器检查 micro/macro required columns 是否都通过了映射，若完整则各加1.5分

最终判断：
```python
if micro_score > macro_score:
    task_type = "micro_emission"
    confidence = min(0.4 + micro_score * 0.10, 0.95)
elif macro_score > micro_score:
    task_type = "macro_emission"
    confidence = min(0.4 + macro_score * 0.10, 0.95)
else:
    task_type = "unknown"
    confidence = 0.3
```

**文件分析输出格式（Python dict，非自然语言）：**
```python
{
    "filename": "data.csv",
    "format": "tabular",
    "row_count": 1500,
    "columns": ["link_id", "length_km", "flow_vph", "speed"],
    "task_type": "macro_emission",        # "micro_emission" | "macro_emission" | "unknown"
    "confidence": 0.75,
    "micro_mapping": {"speed": "speed_kph"},
    "macro_mapping": {"link_id": "link_id", "length_km": "link_length_km", "flow_vph": "traffic_flow_vph"},
    "column_mapping": {"link_id": "link_id", ...},   # 根据task_type选择
    "micro_has_required": False,
    "macro_has_required": True,
    "sample_rows": [{...}, {...}],
    "unresolved_columns": ["other_col"],
    "evidence": ["Column 'flow_vph' matches macro keyword 'flow'", ...],
    "analysis_strategy": "rule",
    "fallback_used": False,
    "selected_primary_table": "data.csv",
    "dataset_roles": [...],
    "missing_field_diagnostics": {...},
    "value_features_summary": {...},
}
```

**LLM fallback条件（`core/file_analysis_fallback.py`，`should_use_llm_fallback()`）：**
- 当 task_type == "unknown" 且 confidence < 0.5，或 micro/macro得分均低时触发
- 使用 `FILE_ANALYSIS_FALLBACK_PROMPT`（硬编码在 router.py L222）调用LLM
- LLM返回JSON，`merge_rule_and_fallback_analysis()` 将LLM结果与规则结果合并
- 合并结果存入 `analysis_dict`，`fallback_used=True`

---

#### 步骤3：文件上下文注入状态

**文件：** `core/router.py` L8368-8400，`core/task_state.py` `update_file_context()` L926

```
analysis_dict → state.update_file_context(analysis_dict)
```

- `state.file_context.task_type = "macro_emission"`
- `state.file_context.columns = [...]`
- `state.file_context.macro_mapping = {...}`
- `state.file_context.grounded = True`
- `state.file_context.evidence = [...]`
- 调用 `_transition_state(state, TaskStage.GROUNDED)`

---

#### 步骤4：任务类型判断

任务类型判断发生在 `FileAnalyzerTool._identify_task_type()` 内部（确定性逻辑，非LLM），结果存储在 `state.file_context.task_type`。下游模块直接读取该字段，**不再重新推断**。

证据：`state.update_file_context()` L933: `self.file_context.task_type = analysis_dict.get("task_type")`

---

#### 步骤5：参数标准化

**文件：** `services/standardizer.py`，`services/standardization_engine.py`，`core/executor.py`

标准化有两个发生时机：

**时机A：文件分析结果中的列名映射**（`UnifiedStandardizer.map_columns()`）
- 输入：用户文件的列名列表（如 `["link_id", "length_km", "flow_vph"]`）
- 处理：先精确匹配 `column_patterns`（YAML中定义的patterns列表），再做子串匹配
- 输出：`{source_col: canonical_field}` 如 `{"flow_vph": "traffic_flow_vph", "length_km": "link_length_km"}`

**时机B：工具参数标准化**（StandardizationEngine在executor中调用）
- 输入：LLM传入的工具参数值（如 `vehicle_type="小汽车"`，`pollutants=["CO2", "氮氧"]`）
- 处理（`UnifiedStandardizer.standardize_vehicle_detailed()` L231）：
  1. 精确匹配 `vehicle_lookup` dict → strategy="exact/alias"，confidence=1.0/0.95
  2. 若无精确/别名匹配，遍历所有alias做fuzzy match（fuzzywuzzy），分数>=70 → strategy="fuzzy"
  3. 若fuzzy失败，尝试本地LoRA模型（可选，需config.use_local_standardizer=True）→ strategy="local_model"
  4. 全部失败 → strategy="abstain"，返回候选建议列表，success=False
- 输出：`StandardizationResult(success, original, normalized, strategy, confidence, suggestions)`

**触发参数协商的条件：**
- strategy="abstain" 时，在 `core/executor.py` 中检测到标准化失败，向router报告
- router在 `_handle_standardization_result()` 中创建 `ParameterNegotiationRequest`

---

#### 步骤6：参数标准化后的格式

标准化后参数以 `ParamEntry` 存储在 `state.parameters` dict：

```python
state.parameters["vehicle_type"] = ParamEntry(
    raw="小汽车",
    normalized="Passenger Car",
    status=ParamStatus.OK,
    confidence=0.95,
    strategy="alias",
    locked=False,
    lock_source=None,
    confirmation_request_id=None,
)
```

---

#### 步骤7：参数校验

校验分两层：

**层1（字段完整性）：** `FileAnalyzerTool._has_required_columns()` 检查必填字段是否都通过了mapping。若缺失，`missing_field_diagnostics` 记录哪些字段missing/derivable/ambiguous。

**层2（工具依赖）：** `core/tool_dependencies.py` `validate_tool_prerequisites()`，检查 `TOOL_GRAPH` 中该工具的 `requires` token是否已在 `state.execution.available_results` 中。

**无交叉约束校验：** 系统**不检查**参数组合合法性（如vehicle_type + fuel_type是否构成MOVES合法组合）。参数组合有效性由LLM推理或由工具执行时的计算逻辑隐式保证。

---

#### 步骤8：工具执行

**文件：** `core/router.py` `_state_handle_executing()` L8807，`core/executor.py` `execute()`

调用链：
```
_state_handle_executing(state)
  → for tool_call in current_response.tool_calls:
      → _prepare_tool_arguments(tool_name, arguments, state)
          → 注入locked参数，注入_input_completion_overrides
          → 若render_spatial_map/calculate_dispersion/analyze_hotspots：注入_last_result
      → _assess_selected_action_readiness(tool_name, arguments, state)
      → executor.execute(tool_name, effective_arguments)
          → StandardizationEngine.standardize(tool_name, arguments)  [可选]
          → tool.execute(**standardized_arguments)
              → MacroEmissionTool.execute(file_path=..., pollutants=..., ...)
                  → calculators/macro_emission.py
          → return {name, arguments, result: ToolResult.as_dict()}
      → _save_result_to_session_context(tool_name, result)
```

**工具执行的参数传递方式：** `**kwargs`，key为参数名，value为标准化后的值。

**工具执行结果格式（ToolResult）：**
```python
ToolResult(
    success=True,
    data={                          # 结构化数据
        "results": [...],           # 路段级结果列表
        "summary": {...},           # 统计摘要
        "query_info": {...},
        "defaults_used": {...},
    },
    summary="计算完成，共1500条路段，总NOx排放量...",  # 人类可读摘要
    chart_data={...},               # 可选图表数据
    table_data={...},               # 可选表格数据
    download_file="path/to/file",   # 可选下载文件路径
    map_data={...},                 # 可选地图数据
)
```

---

#### 步骤9：结果合成

**文件：** `core/router.py` `_state_build_response()` L9268，`_synthesize_results()` L9777，`core/router_synthesis_utils.py`，`core/router_render_utils.py`

两条路径：

**路径A（短路合成）：** `maybe_short_circuit_synthesis()` 检查——
- 单工具成功 → `render_single_tool_success_helper()`，使用确定性模板格式化，不再调LLM
- 有工具失败 → `format_tool_errors_helper()`
- knowledge工具直接返回summary

**路径B（LLM合成）：** 多工具结果时，调用 `build_synthesis_request()` 构建含工具结果+capability_summary的prompt，再次调用 Qwen-plus 生成自然语言回复。

**capability_summary注入：** `build_capability_summary()` → `format_capability_summary_for_prompt()` 将ReadinessAssessment转为中文约束段落，作为 `## 后续建议硬约束` 注入synthesis系统提示词。这限制了LLM能推荐哪些后续步骤。

**最终返回给用户的格式（RouterResponse）：**
```python
RouterResponse(
    text="已完成宏观排放计算...",  # 自然语言文本
    chart_data={...},              # 图表数据（若有）
    table_data={...},              # 表格数据（若有）
    map_data={...},                # 地图数据（若有）
    download_file={...},           # 下载文件信息（若有）
    executed_tool_calls=[...],     # 执行的工具调用记录
    trace={...},                   # Trace审计记录（若enable_trace=True）
    trace_friendly=[...],          # 用户友好Trace（双语）
)
```

---

### 数据流 B：模糊请求（如"帮我分析一下北京的交通排放"）→ 系统处理参数不完整

#### 步骤B1：发现参数不完整

**在 `_state_handle_grounded()` 中（L8750）：**
```python
clarification = self._identify_critical_missing(state)
```

`_identify_critical_missing()` L1095检查优先级：
1. 文件已上传但 task_type == "unknown" → 询问任务类型
2. `state.parameters` 中有 status==AMBIGUOUS 的参数 → 询问具体参数
3. task_type=="micro_emission" 且无 vehicle_type → 询问车型

对于"帮我分析一下北京的交通排放"这种无文件的请求：
- 没有文件上下文，`state.file_context.has_file=False`
- LLM接收用户消息后会尝试调用某个工具（如 `calculate_macro_emission`）但缺少必要参数
- StandardizationEngine尝试标准化，若vehicle_type等缺失且模糊，返回strategy="abstain"

#### 步骤B2：系统处理方式

**三种处理路径：**

**路径1（工具参数缺失/模糊 → 参数协商）：**
- 触发条件：standardizer返回 `strategy="abstain"`，即无法确定性映射
- 在 `core/executor.py` 或 `_handle_standardization_result()` 中创建 `ParameterNegotiationRequest`
- 状态转移：`NEEDS_PARAMETER_CONFIRMATION`
- 系统生成**结构化选项列表**（确定性，非LLM自由生成）：
  ```
  我需要确认以下参数：
  **vehicle_type** (原始值: "公交车")
  请选择：
  1. Transit Bus (公交车) [置信度: 0.95]
  2. Intercity Bus (城际客车) [置信度: 0.72]
  3. School Bus (校车) [置信度: 0.65]
  或者输入具体车型名称
  ```
  格式化函数：`format_parameter_negotiation_prompt()` in `core/parameter_negotiation.py`

**路径2（文件缺少必填字段 → 输入补全）：**
- 触发条件：readiness_assessment 返回 REPAIRABLE，reason_code 指向缺失字段
- 创建 `InputCompletionRequest`，状态转移：`NEEDS_INPUT_COMPLETION`
- 生成结构化输入补全提示（含修复策略选项：uniform scalar fill / upload supporting file / apply default typical profile / pause）

**路径3（完全无上下文 → LLM自由对话）：**
- 若连工具都没有被选择（LLM直接回复文本），进入DONE状态，返回LLM自由文本

#### 步骤B3：追问内容的生成方式

**参数协商的追问**：`format_parameter_negotiation_prompt()` **确定性生成**，基于NegotiationCandidate列表格式化。**不调用LLM生成追问文本**。

**普通澄清问题**：由 `_identify_critical_missing()` 返回的**硬编码中文/英文字符串**（L1109-1134）。**不调用LLM生成追问文本**。

**输入补全提示**：`format_input_completion_prompt()` in `core/input_completion.py`，基于 InputCompletionRequest 结构化生成。

#### 步骤B4：用户补充参数后的接续

**状态保持机制（多轮对话）：**
- `UnifiedRouter` 实例对应一个session_id，存储在 `api/session.py` 的session字典中
- Live state bundles（`_live_parameter_negotiation`，`_live_input_completion`，`_live_continuation_bundle`，`_live_file_relationship`）作为**router实例的字段**持久化在内存中
- 下一轮 `chat()` 调用时，`_state_handle_input()` 首先调用：
  ```python
  self._apply_live_input_completion_state(state)
  self._apply_live_parameter_state(state)
  ```
  将上轮的 active_parameter_negotiation/active_input_completion 恢复到新的 TaskState 中
- 用户回复被 `parse_parameter_negotiation_reply()` 或 `parse_input_completion_reply()` 解析（**确定性正则解析，非LLM**）
- 确认后调用 `state.apply_parameter_lock()` 锁定参数，清除 active_negotiation

---

## 第三部分：逐层架构审查

### 3.1 意图理解与任务建模

#### 是否有结构化任务表示

**有**。`TaskState` 是核心任务表示结构（`core/task_state.py`），包含：
- `file_context: FileContext` — 文件分析结果
- `parameters: Dict[str, ParamEntry]` — 参数状态字典
- `execution: ExecutionContext` — 执行状态（completed_tools, tool_results, available_results）
- `control: ControlState` — 控制状态（steps_taken, max_steps）
- `plan: Optional[ExecutionPlan]` — 执行计划

**无独立的 TaskSpec/TaskRequest 类**。模块间通过 `TaskState` 和 `RouterResponse` 传递任务信息。

#### 文件分析结果格式

**结构化对象（Python dict）**，不是自然语言。通过 `state.update_file_context(analysis_dict)` 写入 `FileContext` dataclass。下游模块通过读取字段获取结果（如 `state.file_context.task_type`，`state.file_context.macro_mapping`），**不需要解析文本**。

文件分析结果同时作为文本摘要注入LLM上下文（通过 `ContextAssembler.assemble()` 中的文件上下文注入）。

#### 文件分析方法（按优先级）

1. **规则（优先）：** 列名关键词匹配 + 数值特征分析 + 必填字段完整性检查（`_identify_task_type()`）
2. **LLM fallback（次之）：** 当规则分析 confidence 低时，调用 LLM 并与规则结果合并（`core/file_analysis_fallback.py`，`should_use_llm_fallback()`）

规则具体形式：关键词字符串列表（L729-745），在列名字符串上做 `if keyword in col_lower`。不使用正则表达式。

#### 任务类型判断是否确定性

**确定性（规则评分）**，非LLM推断。判断结果存入 `state.file_context.task_type`，下游模块直接使用字段值，**不再重新推断**。

---

### 3.2 参数治理

#### 映射资源

**主要存储位置：** `config/unified_mappings.yaml`（598行，Version 2.0）

**覆盖的参数维度及条目数：**

| 维度 | 标准名数量 | 别名条目总计 | 中英文 |
|------|-----------|-------------|-------|
| 车辆类型 (MOVES 13类) | 13 | ~90+ | 两者 |
| 污染物 | 6 (CO2, CO, NOx, PM2.5, PM10, THC) | ~20 | 两者 |
| 季节 | 4 (春/夏/秋/冬) | ~12 | 两者 |
| 道路类型 | 7 (快速路/高速公路/主干道等) | ~30+ | 两者 |
| 气象预设 | 6 (urban_summer_day等) | ~30+ | 两者 |
| 大气稳定度 | 5 (VS/S/N1/N2/U) | ~30+ | 两者 |
| 列名映射 (micro/macro必填字段) | 约15字段 | 每字段3-8个pattern | 两者 |

**还有一处重复定义：** `shared/standardizer/constants.py` 包含 `VEHICLE_TYPE_MAPPING`、`POLLUTANT_MAPPING` 等内联字典，与 YAML 内容有重叠但**不完全一致**（VSP参数仅在YAML中，alias列表在两处略有差异）。`services/standardizer.py` 使用 YAML，`shared/standardizer/constants.py` 被部分遗留代码使用。

**映射表示例（车辆类型，来自 unified_mappings.yaml）：**
```yaml
- id: 21
  standard_name: "Passenger Car"
  display_name_zh: "乘用车"
  aliases:
    - "小汽车"
    - "轿车"
    - "私家车"
    - "SUV"
    - "网约车"
    - "出租车"
    - "滴滴"
    - "passenger car"
    - "car"
    - "轻型汽油车"
    - "汽油车"
    - "乘用车"
    - "轻型车"
  vsp_params:
    A: 0.156461
    B: 0.002001
    C: 0.000492
    M: 1.4788
    m: 1.4788
```

#### 标准化完整流程

**入口函数：** `UnifiedStandardizer.standardize_vehicle_detailed(raw_input)` L231，`standardize_pollutant_detailed()` L300，`standardize_season()` L369，`standardize_road_type()` L418，`standardize_meteorology()` L467，`standardize_stability_class()` L527

**优先级顺序（以车辆为例）：**
```
1. 精确/别名匹配 (vehicle_lookup dict)
   cleaned_lower in self.vehicle_lookup → strategy="exact" (conf=1.0) 或 strategy="alias" (conf=0.95)

2. 若精确失败 → fuzzy match (fuzzywuzzy.fuzz.ratio, 阈值70)
   → strategy="fuzzy", confidence=score/100

3. 若fuzzy失败 → _try_local_standardization() (可选LoRA本地模型)
   → strategy="local_model", confidence>=0.9

4. 全部失败 → strategy="abstain", success=False
   返回 suggestions = 排名前5的候选标准名
```

**LLM参与：** **不通过API调用LLM做标准化**。仅可选本地LoRA模型（`shared/standardizer/local_client.py`，由 `config.use_local_standardizer` 控制）。

**标准化输出（"一个确定值"而非候选列表+置信度）：**
```python
StandardizationResult(
    success=True,
    original="小汽车",
    normalized="Passenger Car",
    strategy="alias",
    confidence=0.95,
    suggestions=[]  # 成功时为空
)
```
失败时：
```python
StandardizationResult(
    success=False,
    original="奇怪的车型",
    normalized=None,
    strategy="abstain",
    confidence=0.0,
    suggestions=["Passenger Car (乘用车)", "Transit Bus (公交车)", ...]
)
```

**标准化失败处理：** 触发参数协商（`ParameterNegotiationRequest`），状态转为 NEEDS_PARAMETER_CONFIRMATION

#### 交叉约束校验

**不存在**车辆类型+燃料类型等参数组合的交叉合法性校验。

证据：检索 `core/readiness.py`，`core/tool_dependencies.py`，`services/standardization_engine.py` 均无此类逻辑。参数组合有效性依赖：
1. YAML中的标准名与 calculators 代码中期望的值一致（隐式约定）
2. calculator内部如遇到无效组合会抛出异常，由工具error处理

#### 协商机制

**触发条件：** 标准化 strategy="abstain" 时，或参数 confidence 低于阈值时

**位置：** `core/executor.py` + `core/router.py` `_handle_standardization_result()`（在 state loop 中）

**格式：** 结构化选项列表，由 `format_parameter_negotiation_prompt()` 生成：
- 参数名 + 原始值
- 编号候选项：`1. Transit Bus (公交车) [策略: alias, 置信度: 0.95]`
- 提示用户选择编号或输入新值

**是否LLM生成：** 否，确定性函数格式化。

**解析方式：** `parse_parameter_negotiation_reply()` 使用正则匹配数字选择（`re.search(r'\b(\d+)\b', reply)`），或识别 "none_of_above" 关键词，或标记为 AMBIGUOUS_REPLY。

#### 参数锁定

**有显式锁定机制。**

- `state.apply_parameter_lock()` L869 设置 `entry.locked=True`，`entry.lock_source="user_confirmation"`，`entry.strategy="user_confirmed"`，`entry.confidence=1.0`
- 在 `_prepare_tool_arguments()` L554-558：
  ```python
  for param_name, entry in state.parameters.items():
      if entry.locked and entry.normalized and param_name in effective_arguments:
          effective_arguments[param_name] = entry.normalized
  ```
  锁定参数在工具执行前**强制覆盖**LLM传入的同名参数值。
- 锁定状态跨轮持久化在 `_live_parameter_negotiation["locked_parameters"]` dict 中，每轮通过 `_apply_live_parameter_state()` 恢复到新 TaskState。

**LLM意外覆盖风险：** 锁定的参数在 `_prepare_tool_arguments()` 中会覆盖 LLM 的 argument值。但如果 LLM 使用了不同的参数名（如 `vehicle_types` vs `vehicle_type`），覆盖可能失效。在LLM完全不调用对应参数名的情况下，锁定不产生效果。

---

### 3.3 工作流编排与工具管理

#### Router核心分发逻辑

**不是 if/elif 链**，也不是策略模式或注册机制。

`chat()` L700 → 判断 `config.enable_state_orchestration` → 调用 `_run_state_loop()` 或 `_run_legacy_loop()`

**State loop 主干（`_run_state_loop()` L872）：**
```python
while not state.is_terminal() and loop_guard < max_state_iterations:
    if state.stage == TaskStage.INPUT_RECEIVED:
        await self._state_handle_input(state)
    elif state.stage == TaskStage.GROUNDED:
        await self._state_handle_grounded(state)
    elif state.stage == TaskStage.EXECUTING:
        await self._state_handle_executing(state)
```

**每个 stage handler 内部**通过大量 if/elif 链处理各种子情况（文件关系解析、参数协商、输入补全、几何恢复等），本质上是复杂的控制流，**不是声明式调度**。

#### 新增一个工具需要修改的位置

1. **创建工具类文件**（如 `tools/noise.py`）：继承 BaseTool，实现 `execute()`
2. **`tools/registry.py` `init_tools()` L82**：添加 `register_tool("analyze_noise", NoiseTool())`
3. **`tools/definitions.py`**：添加 OpenAI格式的 JSON schema
4. **`core/tool_dependencies.py` `TOOL_GRAPH` L30**：添加 `"analyze_noise": {"requires": [], "provides": ["noise"]}`
5. **`core/router.py` `CONTINUATION_TOOL_KEYWORDS` L296**：添加 `"analyze_noise": ["噪声", "noise", ...]`

不需要修改核心控制流，但工具的能力摘要（readiness assessment）中的 ActionCatalogEntry 定义在 `core/readiness.py` 中，若要让系统主动推荐该工具，需在 `_ACTION_CATALOG` 中增加对应 entry（`core/readiness.py` L400+）。

#### 工具定义方式

工具定义分三层，**相互独立，需手动同步**：

**层1（运行时实现）：** `tools/*.py` 中的 BaseTool 子类，实现 `execute(**kwargs) -> ToolResult`。无声明式 schema，输入靠函数签名，无自动验证。

**层2（LLM可见 schema）：** `tools/definitions.py` 中的 `TOOL_DEFINITIONS` 列表，OpenAI function calling 格式，描述参数名、类型、是否required。由 ContextAssembler 注入LLM请求。

**层3（依赖图）：** `core/tool_dependencies.py` `TOOL_GRAPH`，声明 requires/provides，用于依赖验证。

**工具的 preflight_check：** BaseTool 默认返回 `PreflightCheckResult(is_ready=True)`。**只有 DispersionTool 真正覆盖了 preflight_check**，检查文件路径等。其余工具均使用默认（始终 ready）。

一个工具完整声明示例（三层合并后）：
```
calculate_dispersion:
  [layer1] tools/dispersion.py DispersionTool.execute(emission_result, meteorology, ...)
  [layer2] definitions.py: JSON schema with params emission_source, meteorology_preset, ...
  [layer3] TOOL_GRAPH: requires=["emission"], provides=["dispersion"]
  [layer1 preflight] checks for emission file path availability
```

#### 工具间依赖

**在 `core/tool_dependencies.py` `TOOL_GRAPH` 声明**（声明式），**不在 router 中硬编码**。

`render_spatial_map` 的依赖是动态的（根据 `layer_type` 参数动态返回）：
```python
def get_required_result_tokens(tool_name, arguments=None):
    if tool_name == "render_spatial_map":
        layer_type = normalize_result_token(arguments.get("layer_type"))
        if layer_type in {"emission", "dispersion", "hotspot"}:
            return [layer_type]
        return []
    return normalize_tokens(TOOL_GRAPH.get(tool_name, {}).get("requires", []))
```

**上游结果传递方式：** 通过 `_prepare_tool_arguments()` L545 注入 `_last_result` key：
```python
stored_result = context_store.get_result_for_tool(tool_name, label=scenario_label, layer_type=layer_type)
effective_arguments["_last_result"] = stored_result
```
下游工具（如 DispersionTool）从 `kwargs.get("_last_result")` 取上游结果，不是通过参数字段传递。

#### 状态管理

**显式状态枚举（TaskStage）：**
```python
class TaskStage(str, Enum):
    INPUT_RECEIVED = "INPUT_RECEIVED"
    GROUNDED = "GROUNDED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    NEEDS_PARAMETER_CONFIRMATION = "NEEDS_PARAMETER_CONFIRMATION"
    NEEDS_INPUT_COMPLETION = "NEEDS_INPUT_COMPLETION"
    EXECUTING = "EXECUTING"
    DONE = "DONE"
```

**状态转移显式定义** 在 `_valid_transitions()` L409，通过 `state.transition(new_stage)` 调用，违法转移抛 `ValueError`。

**系统能区分的情况：**
| 情况 | 对应阶段/标志 |
|------|-------------|
| 参数待确认 | NEEDS_PARAMETER_CONFIRMATION + active_parameter_negotiation |
| 文件缺失字段（需补全） | NEEDS_INPUT_COMPLETION + active_input_completion |
| 执行中 | EXECUTING |
| 执行成功 | DONE + execution.tool_results 有成功结果 |
| 可恢复失败 | EXECUTING → readiness=REPAIRABLE，有 repair_hint |
| 等待更多信息 | NEEDS_CLARIFICATION |

**无显式 FAILED 状态**。失败转至 DONE，由 execution.last_error 和 tool_results 中的 success=False 标记。

**状态转移图（文本）：**
```
INPUT_RECEIVED
  ├──→ GROUNDED (文件分析完成，或无文件直接由LLM响应)
  ├──→ NEEDS_CLARIFICATION (文件类型不明，或参数歧义)
  ├──→ NEEDS_PARAMETER_CONFIRMATION (参数标准化失败，需用户选择)
  ├──→ NEEDS_INPUT_COMPLETION (文件缺必填字段，需用户补充)
  └──→ DONE (跳过执行，直接完成)

GROUNDED
  ├──→ EXECUTING (所有参数就绪)
  ├──→ NEEDS_CLARIFICATION (发现关键缺失)
  └──→ DONE (无工具调用)

EXECUTING
  ├──→ DONE (工具执行完成，含成功和失败)
  ├──→ NEEDS_CLARIFICATION
  ├──→ NEEDS_PARAMETER_CONFIRMATION
  └──→ NEEDS_INPUT_COMPLETION

NEEDS_CLARIFICATION → [终态，等待下轮用户输入]
NEEDS_PARAMETER_CONFIRMATION → [终态，等待下轮用户选择]
NEEDS_INPUT_COMPLETION → [终态，等待下轮用户补充]
DONE → [终态]
```

---

### 3.4 结果合成

**工具执行结果的处理路径：**

1. 工具返回 `ToolResult`，被序列化为 `{name, arguments, result}` 存入 `state.execution.tool_results`
2. `_save_result_to_session_context()` 将结果存入 `SessionContextStore`（按 type + label 键）和 fact_memory `last_spatial_data`
3. 进入 `_state_build_response()` L9268，先收集 chart_data/table_data/map_data/download_file
4. 调用 `_synthesize_results()` L9777 生成文本

**合成方式：**

- **短路路径（确定性）：** 单工具成功时，`render_single_tool_success()` 基于工具名和结果使用模板/格式化代码生成Markdown文本
- **LLM合成路径：** 多工具时，传入 `SYNTHESIS_PROMPT` + 工具结果摘要 + capability_summary，调用 Qwen-plus 生成文本

**会推荐后续分析步骤：** 是。`build_capability_summary()` → `format_capability_summary_for_prompt()` 生成 `## 后续建议硬约束` 段落，包含 `available_next_actions` 列表。

**推荐是否受当前状态约束：** 是，且这是显式的硬约束机制。

`ReadinessAssessment` 根据当前 state 判断每个 action 的可用性：
- `required_result_tokens` 不满足 → blocked
- `requires_geometry_support` 但文件无几何列 → blocked
- `required_task_types` 不匹配 → blocked
- artifact 已被提供过（`ArtifactDeliveryStatus.PROVIDED`）→ already_provided

若数据无经纬度，`render_spatial_map` 的 `requires_geometry_support=True` 检查失败 → 该action 被标记为 BLOCKED，**不会出现在 `available_next_actions` 中**，synthesis prompt 中也明确说明"不要建议这些操作"。

---

### 3.5 Trace 与可审计性

**有结构化决策记录机制。**

**文件：** `core/trace.py`，1031行

**TraceStepType（约104个值）涵盖：**
- 文件分析层：FILE_GROUNDING, FILE_ANALYSIS_FALLBACK_TRIGGERED/APPLIED/FAILED, FILE_RELATIONSHIP_RESOLUTION_*
- 补充文件层：SUPPLEMENTAL_MERGE_TRIGGERED/PLANNED/APPLIED
- 意图解析层：INTENT_RESOLUTION_TRIGGERED/DECIDED/APPLIED
- 制品记录层：ARTIFACT_RECORDED/MEMORY_UPDATED
- 工作流层：READINESS_ASSESSMENT_BUILT, ACTION_READINESS_READY/BLOCKED/REPAIRABLE, WORKFLOW_TEMPLATE_RECOMMENDED/SELECTED
- 计划层：PLAN_CREATED/VALIDATED/DEVIATION/STEP_MATCHED/STEP_COMPLETED, DEPENDENCY_VALIDATED/BLOCKED
- 修复层：PLAN_REPAIR_TRIGGERED/PROPOSED/APPLIED/FAILED
- 参数层：PARAMETER_NEGOTIATION_REQUIRED/CONFIRMED/REJECTED, PARAMETER_STANDARDIZATION
- 执行层：TOOL_SELECTION, TOOL_EXECUTION, STATE_TRANSITION, CLARIFICATION, SYNTHESIS, ERROR

**TraceStep 结构：**
```python
@dataclass
class TraceStep:
    step_index: int
    step_type: TraceStepType
    timestamp: str              # ISO格式
    stage_before: str           # 决策前的TaskStage
    stage_after: Optional[str]  # 决策后的TaskStage
    action: Optional[str]       # 执行了什么（如工具名）
    input_summary: Optional[Dict]  # 关键输入（紧凑格式，非完整数据）
    output_summary: Optional[Dict] # 关键输出（紧凑格式）
    confidence: Optional[float]
    reasoning: Optional[str]    # 决策原因
    duration_ms: Optional[float]
    standardization_records: Optional[List[Dict]]
    error: Optional[str]
```

**完整回溯能力：**
- 任务类型：在 FILE_GROUNDING 步骤的 output_summary 中记录 task_type, confidence
- 参数标准化：在 PARAMETER_STANDARDIZATION 步骤的 standardization_records 中记录每个参数的 original/normalized/strategy/confidence
- 工具使用：TOOL_EXECUTION 步骤
- 最终参数：通过 PARAMETER_NEGOTIATION_CONFIRMED 和 STATE_TRANSITION 步骤可追溯

**持久化：** **不持久化到磁盘**。Trace 对象仅在当前请求的生命周期中存在，作为 `RouterResponse.trace` 字段通过 API 返回给前端。若启用了 API 访问日志，响应中的 trace JSON 会出现在日志文件中。

---

### 3.6 记忆与上下文

**多轮上下文维护：**

`MemoryManager`（`core/memory.py`）持有两类记忆：
- `working_memory`：对话历史列表（`[{role, content}]`），控制长度截断
- `fact_memory`：结构化事实字典
  - `active_file`：当前主文件路径
  - `file_analysis`：上次文件分析的完整dict（跨轮复用）
  - `recent_vehicle`，`recent_year`，`recent_pollutants`：最近确认的参数
  - `last_spatial_data`：最近的空间数据（geometry含义的结果）
  - `last_tool_snapshot`：最近工具执行快照

`SessionContextStore`（`core/context_store.py`）：
- 以 `(result_type, scenario_label)` 为键存储 `StoredResult`
- 最多5个scenario
- 跨工具依赖时，`get_result_for_tool()` 按 type + label 检索上游结果
- `clear_current_turn()` 每轮 `chat()` 调用时清空当前轮缓存，但 `_store` 字典（session级）保留

**已计算结果的跨轮复用：**
- SessionContextStore 的 `_store` 在router实例生命周期内持久
- `memory.fact_memory["last_spatial_data"]` 通过 `_update_legacy_last_spatial_data()` 更新
- 空间数据（GeoJSON等）通过 `_last_result` key 在工具参数中传递（L574-623）

**空间数据跨轮持久化：**
- 宏观排放结果（含geometry）→ `memory.fact_memory["last_spatial_data"]`
- 扩散结果（concentration_grid/raster_grid）→ `memory.fact_memory["last_spatial_data"]`
- 热点分析结果 → `memory.fact_memory["last_spatial_data"]`
- SessionContextStore 作为第一查询优先级（`context_store.get_result_for_tool()`），memory作为后备

---

## 第四部分：可扩展性实测

### 场景1：新增噪声分析工具

需要修改/创建的位置：

| 操作 | 文件 | 行数估计 |
|------|------|---------|
| 创建工具实现 | `tools/noise.py`（新建） | 不计（工具核心逻辑） |
| 注册工具 | `tools/registry.py` `init_tools()` | +4行 |
| 添加JSON schema | `tools/definitions.py` | +30-50行 |
| 添加依赖声明 | `core/tool_dependencies.py` `TOOL_GRAPH` | +4行 |
| 添加续接关键词 | `core/router.py` `CONTINUATION_TOOL_KEYWORDS` L296 | +2行 |
| 添加Readiness动作条目 | `core/readiness.py` `_ACTION_CATALOG`（约400行处） | +15-25行 |
| 添加列名映射（若需要） | `config/unified_mappings.yaml` | +10-30行 |

**框架代码总改动约 55-115行**（不含工具计算逻辑本身）。

**不需要修改的位置：** 核心 while 循环控制流，LLM tool-use 接口（TOOL_DEFINITIONS 注入后自动可用），参数标准化框架。

### 场景2：支持欧盟排放标准（Euro 6）

**需要修改：**

1. **`config/unified_mappings.yaml`**：
   - 添加欧盟车辆分类别名（Euro ACEA 分类）
   - 添加欧盟排放标准参数维度（Euro 3/4/5/6 标准年份映射）
   - 约+50-100行

2. **参数标准化逻辑：** `services/standardizer.py` 中的 `standardize_vehicle_detailed()` 使用 lookup table 查找，无代码改动，只需在 YAML 中添加新别名。若需添加新的参数维度（如 `emission_standard`），需在 UnifiedStandardizer 中添加对应的 `_build_lookup_tables()` 逻辑（约+30行）。

3. **计算器层**（`calculators/emission_factors.py`，`calculators/macro_emission.py`）：需要实现欧盟 COPERT/HBEFA 排放因子模型。这是核心业务逻辑改动，与框架代码无关。

4. **`tools/definitions.py`**：若新增 `emission_standard` 参数，需更新工具 schema（约+10行）。

5. **`core/tool_dependencies.py`**：不需要修改（工具接口不变）。

6. **`core/router.py`**：不需要修改（框架层无感知）。

---

## 第五部分：配置与资源文件清单

| 文件路径 | 用途 | 条目数 | 是否被代码直接引用 | 示例内容 |
|---------|------|--------|-------------------|---------|
| `config/unified_mappings.yaml` | 所有参数映射（车辆、污染物、季节、道路、气象、列名pattern） | 13车辆+6污染物+4季节+7道路+6气象+6稳定度+~15列名字段 | 是（`services/config_loader.py`） | 见1.2节 |
| `config/meteorology_presets.yaml` | 大气扩散气象预设参数（风速、稳定度、混合层高度等） | 约6个预设 | 是（`calculators/dispersion.py`） | `urban_summer_day: {wind_speed: 3.0, stability: D, ...}` |
| `.env` | API密钥、模型配置、功能开关 | ~20项 | 是（`config.py` via `python-dotenv`） | `LLM_MODEL=qwen-plus`, `ENABLE_STATE_ORCHESTRATION=true` |
| `.env.example` | .env 模板说明 | ~20项 | 否（文档用途） | 同上 |
| `config/prompts/` | LLM系统提示词模板 | 若干文件 | 是（ContextAssembler） | 系统角色提示词 |
| `data/users.db` | SQLite用户数据库 | 运行时数据 | 是（`api/database.py`） | 用户账户、session记录 |
| `data/learning/` | 学习案例JSON | 运行时累积 | 是（`llm/data_collector.py`） | 标注的对话案例 |
| `GIS文件/test_subnets/*/summary.json` | 测试用GIS子网络摘要 | 12个子网络 | 是（测试/评估脚本） | `{"network_id": "1km_hd_regular_jingan_01", ...}` |
| `LOCAL_STANDARDIZER_MODEL/data/augmented/*.json` | LoRA训练数据 | 数百条 | 是（训练脚本） | 标注的参数标准化案例 |
| `pyproject.toml` | Python项目配置 | — | 是（pytest配置） | — |
| `requirements.txt` | 依赖包列表 | ~20项 | 是（部署） | `fastapi`, `pandas`, `geopandas`, ... |

---

## 第六部分：测试覆盖

### 测试文件清单

| 测试文件 | 测试模块 | 测试类型 | 覆盖层 |
|---------|---------|---------|-------|
| `test_task_state.py` | `core/task_state.py` | 单元 | 状态管理 |
| `test_trace.py` | `core/trace.py` | 单元 | Trace结构 |
| `test_tool_dependencies.py` | `core/tool_dependencies.py` | 单元 | 依赖验证 |
| `test_readiness_gating.py` | `core/readiness.py` | 单元 | 工具可用性判断 |
| `test_parameter_negotiation.py` | `core/parameter_negotiation.py` | 单元 | 协商解析 |
| `test_input_completion.py` | `core/input_completion.py` | 单元 | 输入补全 |
| `test_input_completion_transcripts.py` | `core/input_completion.py` | 集成 | 多轮对话补全 |
| `test_remediation_policy.py` | `core/remediation_policy.py` | 单元 | 修复策略 |
| `test_workflow_templates.py` | `core/workflow_templates.py` | 单元 | 模板选择 |
| `test_context_store.py` | `core/context_store.py` | 单元 | Session存储 |
| `test_context_store_integration.py` | `core/context_store.py` | 集成 | 跨工具依赖 |
| `test_context_store_scenarios.py` | `core/context_store.py` | 集成 | 多情景 |
| `test_artifact_memory.py` | `core/artifact_memory.py` | 单元 | 制品追踪 |
| `test_capability_aware_synthesis.py` | `core/capability_summary.py` | 单元 | 能力约束 |
| `test_file_analysis_fallback.py` | `core/file_analysis_fallback.py` | 单元 | LLM fallback |
| `test_file_analyzer_targeted_enhancements.py` | `tools/file_analyzer.py` | 单元 | 列名映射增强 |
| `test_file_grounding_enhanced.py` | 文件分析完整流程 | 集成 | 文件分析 |
| `test_file_relationship_resolution.py` | `core/file_relationship_resolution.py` | 单元 | 多文件关系 |
| `test_geometry_recovery.py` | `core/geometry_recovery.py` | 单元 | 几何恢复 |
| `test_geometry_recovery_transcripts.py` | 几何恢复多轮 | 集成 | 几何恢复 |
| `test_residual_reentry.py` | `core/residual_reentry.py` | 单元 | 残留重入 |
| `test_residual_reentry_transcripts.py` | 残留重入多轮 | 集成 | 残留重入 |
| `test_intent_resolution.py` | `core/intent_resolution.py` | 单元 | 意图解析 |
| `test_supplemental_merge.py` | `core/supplemental_merge.py` | 单元 | 列合并 |
| `test_summary_delivery.py` | `core/summary_delivery.py` | 单元 | 摘要交付 |
| `test_standardizer.py` | `services/standardizer.py` | 单元 | 标准化准确率 |
| `test_standardizer_enhanced.py` | `services/standardizer.py` | 单元 | 标准化边界 |
| `test_standardization_engine.py` | `services/standardization_engine.py` | 单元 | 批量标准化 |
| `test_calculators.py` | `calculators/*.py` | 单元 | 物理计算 |
| `test_dispersion_calculator.py` | `calculators/dispersion.py` | 单元 | 扩散计算 |
| `test_dispersion_integration.py` | DispersionTool端到端 | 集成 | 扩散工具 |
| `test_dispersion_numerical_equivalence.py` | 扩散数值等价性 | 单元 | 计算精度 |
| `test_dispersion_tool.py` | `tools/dispersion.py` | 单元 | 工具接口 |
| `test_hotspot_tool.py` | `tools/hotspot.py` | 单元 | 热点工具 |
| `test_hotspot_analyzer.py` | `calculators/hotspot_analyzer.py` | 单元 | 热点算法 |
| `test_scenario_comparator.py` | `calculators/scenario_comparator.py` | 单元 | 情景对比 |
| `test_compare_tool.py` | `tools/scenario_compare.py` | 单元 | 情景工具 |
| `test_override_engine.py` | `tools/override_engine.py` | 单元 | 参数覆盖 |
| `test_spatial_renderer.py` | `tools/spatial_renderer.py` | 单元 | 空间渲染 |
| `test_spatial_types.py` | `core/spatial_types.py` | 单元 | 空间类型 |
| `test_router_state_loop.py` | `core/router.py` state loop | 集成 | 主编排逻辑 |
| `test_router_contracts.py` | `core/router.py` API契约 | 集成 | 路由器接口 |
| `test_multi_step_execution.py` | 多工具执行链 | 集成 | 工具调度 |
| `test_multi_tool_map_data.py` | 多工具地图数据 | 集成 | 空间数据流 |
| `test_available_results_tracking.py` | 可用结果追踪 | 单元 | 依赖追踪 |
| `test_api_route_contracts.py` | `api/routes.py` | 集成 | API层 |
| `test_api_chart_utils.py` | `api/chart_utils.py` | 单元 | 图表格式 |
| `test_api_response_utils.py` | `api/response_utils.py` | 单元 | 响应格式 |
| `test_config.py` | `config.py` | 单元 | 配置加载 |
| `test_coverage_assessment.py` | `core/coverage_assessment.py` | 单元 | 覆盖评估 |
| `test_real_model_integration.py` | 真实LLM集成 | 端到端 | 完整流程 |
| `test_continuation_eval.py` | 续接决策评估 | 集成 | 工作流续接 |
| `test_macro_typical_profile_execution.py` | 宏观默认剖面执行 | 集成 | 修复策略+执行 |
| `test_micro_excel_handler.py` | 微观Excel处理 | 单元 | 文件解析 |
| `test_phase1b_consolidation.py` | 架构整合测试 | 集成 | 多层 |
| `test_smoke_suite.py` | 冒烟测试 | 端到端 | 完整流程 |

**专门测试参数标准化准确性的文件：** `test_standardizer.py`，`test_standardizer_enhanced.py`，`evaluation/eval_normalization.py`

**专门测试异常输入处理的文件：** `test_file_analysis_fallback.py`，`test_file_analyzer_targeted_enhancements.py`

---

## 信息完整性自检

- [x] 项目目录结构 — 第一部分 1.1 完整列出至两层深度
- [x] 所有核心模块的位置和职责 — 第一部分 1.2 表格
- [x] 两条端到端数据流的完整追踪 — 第二部分 A/B，每步均写明输入→处理→输出
- [x] TaskSpec/任务表示的数据结构 — 3.1节，TaskState全字段定义，ParamEntry完整定义
- [x] 文件分析的方法和输出格式 — 数据流A步骤2，完整dict格式+LLM fallback条件
- [x] 参数映射表的位置、格式、覆盖范围 — 3.2节，unified_mappings.yaml完整说明+示例
- [x] 参数标准化的完整流程（包括规则/LLM的优先级） — 3.2节，4步优先级+代码行号
- [x] 交叉约束校验的存在与否及实现方式 — 3.2节：**不存在**，已验证代码
- [x] 参数协商机制的存在与否及实现方式 — 3.2节，参数协商完整说明（含解析方式）
- [x] 参数锁定机制的存在与否 — 3.2节，apply_parameter_lock()完整说明
- [x] Router的分发逻辑和控制流 — 3.3节，state loop主干代码
- [x] 工具的定义方式和声明式元信息的有无 — 3.3节，三层分离的工具定义
- [x] 工具间依赖的管理方式 — 3.3节，TOOL_GRAPH声明式+_last_result传递机制
- [x] 状态管理的显式程度 — 3.3节，7状态枚举+转移图+_valid_transitions()
- [x] 结果合成的约束感知程度 — 3.4节，capability_summary硬约束注入机制
- [x] Trace的结构化程度 — 3.5节，104个TraceStepType+TraceStep完整结构
- [x] 新增工具的具体改动清单 — 第四部分场景1，5处改动+行数
- [x] 参数域扩展的具体改动清单 — 第四部分场景2，5处改动
- [x] 所有配置/资源文件的清单 — 第五部分表格
- [x] 测试覆盖情况 — 第六部分，50+测试文件完整列表+类型+覆盖层
