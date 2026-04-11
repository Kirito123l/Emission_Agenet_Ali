# SYSTEM_FOR_PAPER_REFACTOR.md
# 面向论文重构的系统实现审计报告

> 生成日期：2026-04-08
> 审计范围：core/, services/, tools/, calculators/, config/, evaluation/
> 目的：为论文重构提供准确的实现依据，区分论文核心贡献与工程支持细节

---

## 1. Executive Summary

EmissionAgent 是一个**面向道路交通尾气分析的专用智能工作流框架**，不是通用 agent。其核心贡献在于：将自然语言请求自动映射到一条由多个分析工具串联而成的计算链（排放估算 → 扩散模拟 → 热点识别 → 空间渲染），并在这个过程中施加多层领域感知的治理机制——参数标准化、跨约束验证、就绪门控、参数协商、计划修复。

**对论文最有价值的核心事实（摘要级别）：**

| 层次 | 实现现状 | 论文价值 |
|------|---------|---------|
| MOVES-Matrix 宏观排放计算 | 完整实现 | 方法章节核心 |
| 逐秒微观排放 (VSP) | 完整实现 | 方法章节核心 |
| 高斯-代理扩散模型 (PS-XGB-RLINE) | 完整实现 | 方法章节核心 |
| 热点识别与空间渲染 | 完整实现 | 方法章节 |
| 五级参数标准化流水线 | 完整实现 | 方法章节/系统设计 |
| 跨约束验证 | 完整实现 | 系统设计 |
| 任务状态机 (7态) | 完整实现 | 系统设计 |
| 就绪评估 + 能力门控 | 完整实现 | 系统设计 |
| 参数协商 (negotiation) | 完整实现 | 系统设计 |
| 工作流模板 (5个) | 实现完整，默认关闭 | 实现细节 |
| 轻量级规划 + 计划修复 | 实现完整，默认关闭 | 可选提及 |
| 审计追踪 (113种 TraceStepType) | 完整实现 | 附录/系统描述 |
| 补充列合并 / 文件关系解析 | 完整实现 | 工程支持 |
| 意图解析 / 工件记忆 | 完整实现 | 工程支持 |

**最重要的警示：** 轻量级规划（`ENABLE_LIGHTWEIGHT_PLANNING`）、工作流模板（`ENABLE_WORKFLOW_TEMPLATES`）、有界计划修复（`ENABLE_BOUNDED_PLAN_REPAIR`）**默认均为关闭**。如果论文声称"系统使用模板+修复实现工作流编排"，需要明确说明这些机制是系统能力的一部分，但默认运行路径依赖的是 LLM 工具调用 + 状态机门控。

---

## 2. End-to-End System Flow

### 2.1 主入口与两条执行路径

```
用户请求 (user_message, file_path?)
        ↓
UnifiedRouter.chat()
        ↓
config.enable_state_orchestration?
    ├─ True (默认) → _run_state_loop()      ← 当前主路径
    └─ False       → _run_legacy_loop()     ← 遗留路径（保留中）
```

**`_run_state_loop()` 是当前正式执行路径**，以下仅描述此路径。

### 2.2 状态循环主流程

```
TaskState.initialize()          ← 创建全量状态对象
Trace.start()                   ← 开始审计追踪
while not state.is_terminal() and loop_guard < max_iterations:
    INPUT_RECEIVED  → _state_handle_input()
    GROUNDED        → _state_handle_grounded()
    EXECUTING       → _state_handle_executing()
state → DONE (或超限强制 DONE)
_state_build_response()         ← 合成最终回答
memory.update()                 ← 持久化记忆
Trace.finish() / persist()      ← 审计追踪结束
```

最大迭代次数：`max(6, max_orchestration_steps * 3)`，默认约 18 次。

### 2.3 `_state_handle_input()` 阶段（详细）

INPUT_RECEIVED 阶段是**所有前置治理的集中地**，实际执行顺序：

1. 加载活跃的参数协商状态、输入补全状态、文件关系状态、意图解析状态
2. **文件关系解析**（如有新文件上传）：判断是替换主文件、附加支持文件、合并补充列还是继续当前文件
3. **补充列合并**（如关系类型为 merge_supplemental_columns）
4. **参数协商回复检测**（如用户正在回复候选选项）
5. **输入补全回复检测**（如用户正在提供缺失字段）
6. **文件分析**（调用 `analyze_file` 工具）：提取 FileContext
7. **LLM 文件分析回退**（低置信度时 + 配置允许时）
8. **意图解析**：DeliverableIntentType + ProgressIntentType
9. **工作流模板推荐**（如启用）
10. **状态转换** → GROUNDED（文件已接地）或直接进入执行

### 2.4 `_state_handle_grounded()` 阶段

文件已接地后：
1. 检查是否有活跃的参数协商或输入补全（如有，直接进入相应终态）
2. 构建就绪评估（ReadinessAssessment）
3. 决定是否继续（continuation decision）
4. 调用 LLM 进行工具选择（Tool Use 模式，提供全部工具定义）
5. 转换到 EXECUTING

### 2.5 `_state_handle_executing()` 阶段

1. 执行 LLM 选择的工具（通过 ToolExecutor）
2. **执行侧参数标准化**（如启用）
3. **跨约束验证**（如启用）
4. 将结果写入 SessionContextStore
5. 记录 ArtifactMemory
6. 检查是否有残余计划需要继续（continuation bundle）
7. 检查依赖门控（prerequisite tokens）
8. 转换 → DONE 或触发计划修复

### 2.6 关键状态对象

| 对象 | 位置 | 主要字段 |
|------|------|---------|
| `TaskState` | core/task_state.py | stage, file_context, parameters, execution, control, plan, continuation, ... (100+字段) |
| `FileContext` | core/task_state.py | has_file, file_path, grounded, task_type, confidence, column_mapping, micro_mapping, macro_mapping, spatial_metadata, dataset_roles |
| `ExecutionContext` | core/task_state.py | selected_tool, completed_tools, tool_results, last_error, available_results, blocked_info |
| `ControlState` | core/task_state.py | steps_taken, max_steps(默认4), needs_user_input, stop_reason |
| `ContinuationDecision` | core/task_state.py | residual_plan_exists, should_continue, next_tool_name, latest_repair_summary |
| `ExecutionPlan` | core/plan.py | goal, steps, mode, status |
| `PlanStep` | core/plan.py | step_id, tool_name, depends_on, produces, status |
| `RouterResponse` | core/router.py | text, chart_data, table_data, map_data, download_file, trace |

---

## 3. File-Grounded Task Understanding

### 3.1 文件分析流水线

```
用户上传文件
     ↓
FileAnalyzerTool.execute(file_path)
     ↓
_analyze_structure() / _analyze_zip_file() / _analyze_shapefile_structure() / _analyze_geojson_file()
     ↓
列名模式匹配（column_patterns from unified_mappings.yaml）
     ↓
任务类型推断（macro_emission / micro_emission / unknown）
     ↓
DatasetRole 分配（ZIP包含多表时）
     ↓
缺失字段诊断（missing_field_diagnostics）
     ↓
空间元数据提取（geometry_types, has_geometry, crs_info）
     ↓
FileContext 对象（注入 TaskState）
```

缓存策略：`file_path` + `file_mtime` 双重校验，文件未变时复用缓存。

### 3.2 列名映射（unified_mappings.yaml 驱动）

**宏观排放列识别模式：**
- link_id, length/link_length, flow/traffic_flow, speed/avg_speed

**微观排放列识别模式：**
- time/timestamp, speed/v, acceleration/acc/a, grade/slope

这些模式来自 `config/unified_mappings.yaml` 的 `column_patterns` 节，不是硬编码在 Python 中。

### 3.3 FileContext 真实字段

```python
@dataclass
class FileContext:
    has_file: bool
    file_path: Optional[str]
    grounded: bool
    task_type: Optional[str]          # "macro_emission" | "micro_emission" | "unknown"
    confidence: float                  # 0.0~1.0
    column_mapping: Dict[str, str]     # {canonical_field: source_column}
    evidence: List[str]                # 接地证据字符串列表
    row_count: Optional[int]
    columns: List[str]
    sample_rows: List[Dict]
    micro_mapping: Dict[str, str]      # micro 列映射
    macro_mapping: Dict[str, str]      # macro 列映射
    micro_has_required: bool           # 是否有必需字段
    macro_has_required: bool
    selected_primary_table: Optional[str]  # ZIP包多表时选定的主表
    dataset_roles: List[Dict]          # [{role, format, filename, selected}]
    spatial_metadata: Dict             # {geometry_types, has_geometry, crs_info, ...}
    missing_field_diagnostics: Dict    # {status, missing_required, missing_optional, ...}
    spatial_context: Optional[str]     # 空间上下文描述
```

### 3.4 LLM 文件分析回退

当规则分析置信度低时，如果 `ENABLE_FILE_ANALYSIS_LLM_FALLBACK=true`（默认关闭），会调用 LLM 进行语义分析。回退结果通过 `merge_rule_and_fallback_analysis()` 与规则结果合并，以规则结果为主。

**注意：** 此功能默认关闭，论文不应将此作为核心机制描述。

### 3.5 文件关系解析（多轮文件场景）

当用户在会话中上传第二个文件时，系统通过 LLM + 规则推断文件关系：

| 关系类型 | 含义 |
|---------|------|
| `replace_primary_file` | 新文件替换当前分析的主文件 |
| `attach_supporting_file` | 作为支持文件（如空间底图）附加 |
| `merge_supplemental_columns` | 补充合并缺失的列（如为现有数据添加坐标） |
| `continue_with_current_file` | 忽略新文件，继续使用当前主文件 |
| `ask_clarify` | 证据不足，返回询问用户 |

此机制完整实现，在代码中有 5 种分支的 LLM 提示词和转换计划生成逻辑。

---

## 4. Execution-Side Parameter Governance

### 4.1 标准化流水线（五级级联）

```
原始参数值（来自用户自然语言）
        ↓
Level 1: Exact Match    ← 大小写不敏感完全匹配
        ↓ (miss)
Level 2: Alias Match    ← unified_mappings.yaml 中的别名列表
        ↓ (miss)
Level 3: Fuzzy Match    ← fuzzywuzzy.fuzz.ratio() 相似度匹配
        ↓ (miss, 或置信度 < threshold)
Level 4: Model Match    ← 本地 LoRA 模型 或 LLM API (qwen-turbo)
        ↓ (miss)
Level 5: Default/Abstain ← 有默认值则填入，否则返回失败+建议
```

各参数类型的模糊匹配阈值：
- `vehicle_type`: 70%
- `pollutant`: 80%
- `season`, `road_type`: 60%
- `meteorology`: 75%
- `stability_class`: 75%

标准化结果结构（`StandardizationResult`）：
- `success`, `original`, `normalized`, `strategy`（exact/alias/fuzzy/model/default/abstain）, `confidence`, `suggestions`

### 4.2 参数覆盖的维度（unified_mappings.yaml）

| 参数类型 | 候选值数量 | 说明 |
|---------|----------|------|
| vehicle_type | 13 | MOVES 标准车型，含 VSP 物理参数 (A,B,C,M,m) |
| pollutant | 6 | CO2, CO, NOx, PM2.5, PM10, THC |
| season | 4 | 春季, 夏季, 秋季, 冬季 |
| road_type | 5 | 快速路, 高速公路, 主干道, 次干道, 支路 |
| meteorology | 6 | 预设气象场（urban_summer_day/night, urban_winter_day/night, windy_neutral, calm_stable） |
| stability_class | 6 | Pasquill-Gifford 稳定度分类 (VS/S/N1/N2/U/VU) 含 L/H 参数 |

**默认值（无用户指定时）：** season=夏季，road_type=快速路，model_year=2020，pollutants=[CO2, NOx, PM2.5]

### 4.3 跨约束验证（CrossConstraintValidator）

实现位置：`services/cross_constraints.py`，规则文件：`config/cross_constraints.yaml`

当前已部署的约束规则（3条）：
1. `vehicle_road_compatibility`：摩托车不允许上高速公路（hard block）
2. `vehicle_pollutant_relevance`：车型与污染物相关性（规则槽位，当前为空）
3. `season_meteorology_consistency`：季节与气象预设的一致性（warning，非 hard block）

约束结果类型：`CrossConstraintViolation`（含 blocked / inconsistent 两种 violation_type）
验证时机：参数标准化完成后，工具执行前。

**评估价值：** 这是"交通领域知识编码"的典型体现——摩托车禁止上高速是 GB 法规的直接编码，season-meteorology 一致性是气象-排放建模的领域知识，值得在论文中作为约束感知（constraint-awareness）的具体实例说明。

### 4.4 参数协商机制（Parameter Negotiation）

当参数标准化得到多个候选（fuzzy 阶段置信度接近）时触发。

**协商请求结构（`ParameterNegotiationRequest`）：**
- `request_id`（UUID）
- `parameter_name`, `raw_value`, `confidence`
- `trigger_reason`, `tool_name`, `arg_name`
- `strategy`（触发时的标准化策略）
- `candidates`（候选列表，含 normalized_value, display_label, confidence, strategy, aliases）

**用户回复解析（`parse_parameter_negotiation_reply()`）：**
- 支持中文序数词（一、二、三、四、五、六）
- 支持数字+序号模式（1、option1、第2个）
- 支持括号别名（如"轿车 (Passenger Car)"）
- 结果类型：`CONFIRMED` | `NONE_OF_ABOVE` | `AMBIGUOUS_REPLY`

**参数锁定（Parameter Lock）：**
- 用户确认后，`ParamEntry.locked=True`, `lock_source="user_confirmed"`
- 锁定后的参数在后续轮次不再触发协商（strategy="user_confirmed"）
- `_live_parameter_negotiation.locked_parameters` 跨轮次持久化

### 4.5 输入补全机制（Input Completion）

当工具需要的字段在文件中缺失时触发：

输入补全选项类型（`InputCompletionOptionType`）：
- `uniform_scalar_fill`：统一标量填充（如"全部路段 flow=1000"）
- `upload_supporting_file`：上传补充文件（如含流量数据的第二张表）
- `apply_default_typical_profile`：应用 HCM 典型值（基于路网类型的默认流量/速度）
- `pause`：暂停并告知用户所需字段

补全后：字段值以 `completion_overrides` 形式注入工具调用参数。

---

## 5. Constraint-Aware Workflow Orchestration

### 5.1 任务状态机

实现位置：`core/task_state.py`

**7个 TaskStage 值：**

```
INPUT_RECEIVED      ← 初始态：用户消息已接收
GROUNDED            ← 文件已分析，参数已标准化
NEEDS_CLARIFICATION ← 需要用户提供更多信息（终态之一）
NEEDS_PARAMETER_CONFIRMATION ← 等待参数选择确认（终态之一）
NEEDS_INPUT_COMPLETION ← 等待缺失字段补全（终态之一）
EXECUTING           ← 工具正在执行
DONE                ← 完成（终态）
```

**合法转换矩阵（`_valid_transitions()`）：**
```
INPUT_RECEIVED  → {GROUNDED, NEEDS_CLARIFICATION, NEEDS_PARAMETER_CONFIRMATION,
                   NEEDS_INPUT_COMPLETION, DONE}
GROUNDED        → {EXECUTING, NEEDS_CLARIFICATION, NEEDS_PARAMETER_CONFIRMATION,
                   NEEDS_INPUT_COMPLETION, DONE}
EXECUTING       → {DONE, NEEDS_CLARIFICATION, NEEDS_PARAMETER_CONFIRMATION,
                   NEEDS_INPUT_COMPLETION}
NEEDS_*         → {} (纯终态，不允许再转换)
DONE            → {} (纯终态)
```

非法转换会抛出 `ValueError`，确保状态机的完整性。

**注意：** 没有显式的 `FAILED` 状态——执行失败会转到 `DONE`（携带错误信息）。

### 5.2 就绪评估（ReadinessAssessment）

实现位置：`core/readiness.py`（1365行）

**就绪状态（ReadinessStatus）：**
- `READY`：可立即执行
- `BLOCKED`：前置条件未满足（如 dispersion 未执行就无法做 hotspot）
- `REPAIRABLE`：阻塞但可通过某种修复动作恢复（如补充缺失列）
- `ALREADY_PROVIDED`：该 artifact 本轮已交付，避免重复执行

**ActionAffordance（动作能力评估）：**
```python
@dataclass
class ActionAffordance:
    action_id: str
    status: ReadinessStatus        # READY/BLOCKED/REPAIRABLE/ALREADY_PROVIDED
    display_name: str
    description: str
    tool_name: str
    arguments: Dict
    reason: Optional[BlockedReason]
    required_conditions: List[str] # 前置条件描述
    available_conditions: List[str]
    alternative_actions: List[str]
    guidance_utterance: str        # 给用户的引导话术
    provided_artifact: Optional[Dict]  # 已提供的 artifact 信息
```

**空间就绪检测：** 通过 14 个几何列关键词（geometry, geom, wkt, geojson, lon, lat, x_coord, y_coord 等）识别数据集是否具备空间能力。

**已提供检测：** ArtifactMemory 中记录已交付的 {download_file, table_data, map_data, chart_data}，在新轮次中避免重复交付同一 artifact。

### 5.3 工具依赖图（TOOL_GRAPH）

实现位置：`core/tool_dependencies.py`

**三个规范结果 token：**
- `emission`（宏/微观排放计算结果）
- `dispersion`（扩散模拟结果，含 raster_grid/contour）
- `hotspot`（热点分析结果）

**依赖关系（requires/provides）：**
```
calculate_micro_emission:  requires=[], provides=[emission]
calculate_macro_emission:  requires=[], provides=[emission]
calculate_dispersion:      requires=[emission], provides=[dispersion]
analyze_hotspots:          requires=[dispersion], provides=[hotspot]
render_spatial_map:        requires=[emission|dispersion|hotspot]*
compare_scenarios:         requires=[]
query_emission_factors:    requires=[]
query_knowledge:           requires=[]
analyze_file:              requires=[]
```

*render_spatial_map 的 requires 取决于 `layer_type` 参数（动态依赖）。

**别名规范化：** emission_result→emission, dispersion_result→dispersion, hotspot_analysis→hotspot, concentration/raster/contour→dispersion

### 5.4 工作流模板（5个，默认关闭）

实现位置：`core/workflow_templates.py`（编译为 Python 常量，非 YAML 配置）

| Template ID | 适用场景 | 步骤链 |
|------------|---------|-------|
| `macro_emission_baseline` | 宏观排放基础分析 | calc_macro → (render?) |
| `macro_spatial_chain` | 宏观完整空间链 | calc_macro → dispersion → hotspot → render |
| `micro_emission_baseline` | 微观轨迹基础分析 | calc_micro |
| `macro_render_focus` | 宏观+地图渲染 | calc_macro → render |
| `micro_render_focus` | 微观+地图渲染（需空间支持） | calc_micro → render |

**模板推荐评分机制：** 基于信号评分（task_type=0.42, file_readiness_complete=0.2, spatial_ready=0.16, render_intent=0.12 等），选择 confidence ≥ 0.55 的模板作为规划器先验。

**重要：** `ENABLE_WORKFLOW_TEMPLATES=false`（默认）。启用后，模板作为"bounded prior"注入 LLM 规划提示，LLM 可适当收窄但不能扩展。

### 5.5 轻量级规划与计划修复

**轻量级规划（`ENABLE_LIGHTWEIGHT_PLANNING=false` 默认关闭）：**
- 启用后在每轮执行前调用 LLM 生成 `ExecutionPlan`（compact JSON）
- 规划提示词（`PLANNING_PROMPT`）严格限制工具名、token 名、步骤格式

**计划修复（`ENABLE_BOUNDED_PLAN_REPAIR=false` 默认关闭）：**

修复触发类型（`RepairTriggerType`）：
- `PLAN_DEVIATION`：LLM 调用了不在计划中的工具
- `DEPENDENCY_BLOCKED`：工具依赖的前置 token 未满足

修复动作类型（`RepairActionType`，7种）：
- `KEEP_REMAINING`：保持剩余步骤不变
- `DROP_BLOCKED_STEP`：删除被阻塞的步骤
- `REORDER_REMAINING_STEPS`：重排剩余步骤顺序
- `REPLACE_STEP`：用另一工具替换步骤
- `TRUNCATE_AFTER_CURRENT`：截断当前步骤之后的所有步骤
- `APPEND_RECOVERY_STEP`：追加恢复步骤
- `NO_REPAIR`：无需修复（残余工作流仍合法）

修复由专用 LLM 调用执行（`REPAIR_PROMPT`），输出受严格约束（bounded JSON）。

### 5.6 HCM 默认典型值（Remediation Policy）

实现位置：`core/remediation_policy.py`

显式引用 **Highway Capacity Manual 6th Edition (HCM 6th ed.)** 作为 traffic_flow 默认值来源。按路网分类（motorway/trunk/primary/secondary/tertiary/residential 等）和车道数提供每方向每小时的默认流量：
- motorway + 3lanes: 2000 veh/h
- primary + 2lanes: 900 veh/h
- residential: 150 veh/h
- ...（完整查找表，14个路网类型 × 多车道数）

策略类型（`RemediationPolicyType`）：
- `UNIFORM_SCALAR_FILL`：统一标量填充
- `UPLOAD_SUPPORTING_FILE`：上传补充文件
- `APPLY_DEFAULT_TYPICAL_PROFILE`：应用 HCM 典型值
- `PAUSE`：暂停

**论文价值：** 这是框架中最直接的"交通专业知识编码"，直接引用可信来源，可以作为"domain-grounded default inference"的典型实例写进论文。

---

## 6. Tooling Layer and Analysis Chains

### 6.1 工具体系总览（9个注册工具）

```
tools/registry.py → init_tools() 注册以下工具：
  1. query_emission_factors    ← EmissionFactorsTool
  2. calculate_micro_emission  ← MicroEmissionTool
  3. calculate_macro_emission  ← MacroEmissionTool
  4. analyze_file              ← FileAnalyzerTool
  5. query_knowledge           ← KnowledgeTool
  6. calculate_dispersion      ← DispersionTool
  7. analyze_hotspots          ← HotspotTool
  8. render_spatial_map        ← SpatialRendererTool
  9. compare_scenarios         ← ScenarioCompareTool
```

工具基类（`BaseTool`）：有 `execute(**kwargs) → ToolResult` 抽象方法，`ToolResult` 携带 `{success, data, error, summary, chart_data, table_data, download_file, map_data}`。

**注意：** 除 DispersionTool 外，其余工具的 `preflight_check()` 均返回 `is_ready=True`，即 preflight 机制目前只有 Dispersion 工具真正实现了就绪检查。

### 6.2 核心分析工具详情

#### A. 微观排放工具（`calculate_micro_emission`）
- **位置：** `tools/micro_emission.py` + `calculators/micro_emission.py`
- **核心算法：** VSP（Vehicle Specific Power）+ MOVES 排放因子矩阵
- **VSP 公式：** `VSP = (A·v + B·v² + C·v³ + M·v·a + M·v·g·grade/100) / m`（单位 kW/ton）
- **VSP 参数来源：** `config/unified_mappings.yaml` 中各车型的 {A, B, C, M, m}（13车型均有参数）
- **输入：** vehicle_type, pollutants, model_year, season, trajectory_data（逐秒速度/加速度/坡度）或 input_file
- **输出：** 逐秒排放量，summary 统计
- **论文地位：** 方法章节核心（微观尾气建模）

#### B. 宏观排放工具（`calculate_macro_emission`）
- **位置：** `tools/macro_emission.py` + `calculators/macro_emission.py`
- **核心算法：** MOVES-Matrix 方法（交通流 × 排放因子 × 路段长度）
- **输入：** vehicle_type, pollutants, season, road_type, fleet_mix, links_data（路段OD + 流量 + 速度）
- **自动修复：** `_fix_common_errors()` 处理常见字段名错误（length→link_length_km 等）
- **输出：** 路段级排放量（含 geometry 字段支持空间渲染）
- **论文地位：** 方法章节核心（宏观网络级尾气建模）

#### C. 扩散工具（`calculate_dispersion`）
- **位置：** `tools/dispersion.py` + `calculators/dispersion.py`
- **核心模型：** PS-XGB-AERMOD-RLINE 代理模型（`ps-xgb-aermod-rline-surrogate/`）
- **气象输入：** 6种预设 + custom + .sfc 文件
- **Pasquill-Gifford 稳定度映射：** 6级（VS→F, S→E, N1→D, N2→C, U→B, VU→A），含 Monin-Obukhov 长度 L 和混合层高度 H
- **地面粗糙度：** 0.05/0.5/1.0（m）
- **输出：** raster_grid（浓度栅格），contour_bands（等值线，如启用），coverage_assessment
- **前置依赖：** `emission`（通过 `_last_result` 注入）
- **论文地位：** 方法章节核心（污染物扩散建模）

#### D. 热点分析工具（`analyze_hotspots`）
- **位置：** `tools/hotspot.py` + `calculators/hotspot_analyzer.py`
- **方法：** 基于百分位数（percentile 方法，默认95th percentile）
- **参数：** threshold_value=5.0, min_hotspot_area_m2=2500, max_hotspots=10
- **输入：** dispersion 结果（含 raster_grid）
- **输出：** 热点多边形列表（含 peak_concentration, centroid, source_attribution）
- **论文地位：** 方法章节（热点识别）

#### E. 空间渲染工具（`render_spatial_map`）
- **位置：** `tools/spatial_renderer.py`
- **功能：** 将 emission/dispersion/hotspot 结果转为前端交互地图数据（Leaflet 格式）
- **输入：** layer_type 参数决定渲染哪类数据
- **输出：** map_data（前端渲染负载）
- **论文地位：** 实现细节/系统描述（可视化层）

#### F. 场景比较工具（`compare_scenarios`）
- **位置：** `tools/scenario_compare.py`
- **功能：** 从 SessionContextStore 提取多个场景结果并做对比计算
- **支持：** 单场景pairwise/多场景multi-compare，按 result_type（emission/dispersion/hotspot）分别对比
- **论文地位：** 系统能力描述（场景分析）

#### G. 文件分析工具（`analyze_file`）
- **位置：** `tools/file_analyzer.py`
- **功能：** 见第3节
- **注意：** 在 LLM 规划提示词中明确要求"不在 plan steps 中包含 analyze_file"——它不是用户可见分析链的一部分，而是系统内部的接地工具。

### 6.3 典型完整分析链

```
用户：分析这个路网文件的 NOx 排放并显示热点地图
     ↓
[file grounding]  analyze_file → task_type=macro_emission, macro_has_required=True
     ↓
[standardization] vehicle_type="客车" → "Transit Bus"; pollutant="氮氧化物" → "NOx"
     ↓
[readiness]       calculate_macro_emission: READY
                  calculate_dispersion:     READY (emission 将由上步提供)
                  analyze_hotspots:         BLOCKED (dispersion 未就绪)
     ↓
[LLM tool call]   calculate_macro_emission(links_data=..., ...)
     ↓
[ArtifactMemory]  token: emission
     ↓
[LLM tool call]   calculate_dispersion(emission_source="last_result", meteorology="urban_summer_day")
     ↓
[ArtifactMemory]  token: dispersion
     ↓
[LLM tool call]   analyze_hotspots(dispersion_data=..., method="percentile")
     ↓
[ArtifactMemory]  token: hotspot
     ↓
[LLM tool call]   render_spatial_map(layer_type="hotspot")
     ↓
RouterResponse: text + map_data
```

---

## 7. What Is Truly Novel in the Current Implementation

以下内容是代码中**真实实现且有论文价值**的创新点，按强度排序：

### 7.1 高价值：真正的领域特异性机制

**（1）MOVES-VSP 微观排放计算链**
- 完整实现逐秒速度→VSP→排放因子查表→排放量的全链路
- VSP 参数（A/B/C/M/m）按13个 MOVES 车型配置，可从 YAML 驱动
- 论文中应作为核心方法描述

**（2）MOVES-Matrix 宏观路段排放**
- 按路段（link）的流量×速度×排放因子矩阵方法
- 输出带几何信息的路段级排放，支持后续扩散
- 论文中应作为核心方法描述

**（3）PS-XGB-RLINE 代理扩散模型**
- 使用 XGBoost 代理替代 AERMOD/RLINE 数值模型
- 6种预设气象场对应 Pasquill-Gifford 6级稳定度
- 支持自定义气象参数（风速/风向/混合层/粗糙度）
- 论文中应描述代理模型的设计选择

**（4）HCM 引用的默认流量查找表**
- `core/remediation_policy.py` 中明确标注 "HCM 6th ed." 来源
- 按路网等级×车道数提供 per-direction 默认流量
- 这是"领域知识编码为可审计决策"的最好例子

**（5）交通参数的五级标准化流水线**
- exact→alias→fuzzy→model→default 的完整实现
- 为交通领域参数设计（13车型/6污染物/4季节/5路型/6气象/6稳定度）
- 模糊匹配阈值按参数重要性差异化设置（vehicle 70% vs pollutant 80%）

**（6）跨约束验证（domain-encoded constraints）**
- 摩托车禁止上高速（GB法规直接编码）
- 季节-气象预设一致性检验（气象建模领域知识）
- YAML 配置驱动，易于扩展

### 7.2 中等价值：工作流治理机制

**（7）依赖令牌依赖图（TOOL_GRAPH）**
- emission → dispersion → hotspot 的显式依赖链
- 阻断未满足依赖的工具调用
- 使多步分析链在框架层面有形式保证

**（8）就绪评估门控（ReadinessAssessment）**
- READY/BLOCKED/REPAIRABLE/ALREADY_PROVIDED 四态
- ArtifactMemory 跟踪避免重复交付
- 能力摘要（capability summary）注入 LLM 上下文防止幻觉推荐

**（9）参数协商机制**
- 当参数模糊时向用户展示候选列表并解析回复
- 支持中文序数词解析
- 用户确认后参数锁定，跨轮次保持

**（10）任务状态机（7态）**
- 合法转换的形式验证（ValueError 异常）
- NEEDS_PARAMETER_CONFIRMATION 等等待态是工作流暂停的正式表达
- 不同等待类型（参数/输入补全/澄清）有独立的状态

### 7.3 较低价值：工程支持层（论文中可一笔带过）

- 文件关系解析（多文件上传场景）
- 补充列合并（SupplementalMerge）
- 工件记忆（ArtifactMemory）去重
- 意图解析（IntentResolution）
- 几何恢复（GeometryRecovery）
- 审计追踪（Trace，113种 TraceStepType）——审计设施好，但不是论文核心方法
- LLM 文件分析回退（默认关闭）

---

## 8. What Should Be Emphasized / De-emphasized in the Paper

### 8.1 应该在论文中强调的

| 内容 | 建议章节 | 理由 |
|------|---------|------|
| MOVES-VSP 微观计算方法 | 方法（3.x） | 这是交通排放建模的核心贡献 |
| MOVES-Matrix 宏观方法 | 方法（3.x） | 同上 |
| PS-XGB 代理扩散模型 | 方法（3.x） | 模型设计选择值得说明 |
| 分析链的形式依赖（emission→dispersion→hotspot） | 系统设计 | 这是"工作流框架"区别于"通用agent"的关键 |
| 五级标准化流水线 | 系统设计 | 专为交通参数设计，有领域意义 |
| 跨约束验证（交通法规/气象知识编码） | 系统设计 | 领域特异性的最好体现 |
| HCM 引用的默认值 | 系统设计 | 可信来源的领域知识，直接可引用 |
| 文件接地机制（从上传文件推断任务类型） | 系统设计 | 交通数据驱动分析的具体落地 |
| 端到端评估 + 消融实验 | 实验（5.x） | 4指标×5消融配置有论文价值 |

### 8.2 应该降低篇幅或移入附录的

| 内容 | 建议处理 |
|------|---------|
| 轻量级规划（默认关闭） | 附录或一句话提及 |
| 工作流模板（默认关闭） | 附录或一句话提及 |
| 有界计划修复（默认关闭） | 附录或一句话提及 |
| 参数协商机制 | 系统描述（1-2段）而非完整方法节 |
| 审计追踪（113 TraceStepType） | 实现细节，附录 |
| 文件关系解析 | 一句话提及 |
| ArtifactMemory / 去重 | 一句话提及 |

### 8.3 应该在论文叙事上纠正的

**问题 1：** 如果论文中描述"系统使用工作流模板+修复编排分析流"，这在默认配置下不成立。
**建议：** 改为"系统维护显式的工具依赖图，并在运行时通过就绪评估门控强制依赖顺序；工作流模板作为可选先验，可通过配置启用"。

**问题 2：** 如果论文中说"agent 自动生成执行计划"，需要说明在默认配置下规划是隐式的（LLM tool use），显式规划需要启用 `ENABLE_LIGHTWEIGHT_PLANNING`。

**问题 3：** 如果论文声称"通用 agent 框架"，代码实现的是高度专用的框架——工具集固定为9个，分析链固定为3-4步，参数空间有限且被显式枚举。这种专用性应该是论文强调的优势，不是局限。

---

## 9. Chapter-by-Chapter Paper Refactor Suggestions

假设论文结构为通用的系统论文格式（Introduction / Related Work / Method / System / Evaluation / Conclusion）：

### 9.1 Introduction（引言）

**当前实现支持的论文定位：**
- "面向道路交通尾气分析的专用智能工作流系统"
- 强调：从自然语言到多步科学计算链的全自动化；参数标准化降低专业门槛；领域约束防止错误分析

**避免的定位：**
- "通用 LLM agent 框架"（代码实现太专用）
- "零样本工具编排"（参数标准化、约束验证、依赖图都是 domain-specific 的硬编码知识）

### 9.2 Related Work

可以参考的方向（代码中有实现支撑）：
- MOVES 排放模型 / AERMOD/RLINE 扩散模型（代码中有实现）
- LLM 工具使用（Tool Use 模式）
- 领域特定 agent（domain-specific agent）
- 参数标准化 / 模糊匹配

### 9.3 方法章节（重要）

**3.1 系统概述 / 架构**
- 5层架构：接地层 → 参数治理层 → 依赖门控层 → 计算层 → 空间分析层
- 数据流：自然语言 + 文件 → FileContext → 标准化参数 → 工具链 → 多媒体结果

**3.2 文件接地（File Grounding）**
- task_type 推断机制（宏观/微观/未知）
- 列名模式匹配（YAML 配置驱动）
- 与高精度有直接关系：接地是否正确影响下游全部工具

**3.3 参数治理（Parameter Governance）**
- 五级标准化流水线（应该是方法章节一个完整小节）
- 跨约束验证（domain-encoded rules）
- 参数协商（可简短描述）

**3.4 微观排放计算（Micro-scale Emission Estimation）**
- VSP 公式和 MOVES 参数化
- 输入数据要求（second-by-second trajectory）
- 14个 VSP bins

**3.5 宏观排放计算（Macro-scale Emission Estimation）**
- MOVES-Matrix 方法
- 路段级输出（link-level）
- Fleet mix 和 road type 的参数化

**3.6 扩散与热点分析**
- PS-XGB 代理模型选择理由（计算效率）
- Pasquill-Gifford 气象参数化
- 热点识别的百分位方法

**3.7 工作流编排（Workflow Orchestration）**
- 任务状态机（7态）
- 依赖图门控（emission→dispersion→hotspot）
- 就绪评估（READY/BLOCKED/REPAIRABLE）

### 9.4 实验章节

**5.1 评测设置**
- 基准任务集（`evaluation/benchmarks/end2end_tasks.jsonl`）
- Router 模式端到端评测

**5.2 主要指标（4个，均有代码支撑）**
- `completion_rate`：任务完成率
- `tool_accuracy`：工具选择准确率
- `parameter_legal_rate`：参数合法率
- `result_data_rate`：结果数据返回率

**5.3 消融实验（5个配置，均有代码支撑）**
- baseline（全功能）
- no_standardization（关闭执行侧标准化）
- no_cross_constraint（关闭跨约束验证）
- no_negotiation（关闭参数协商）
- no_readiness（关闭就绪门控）

每个消融配置运行3次取均值/标准差，这是合理的实验设计。

---

## 10. Open Gaps / Unclear Areas / Claims That Need Caution

### 10.1 功能实现但默认关闭的机制（需要在论文中谨慎声明）

| 机制 | 默认状态 | 风险 |
|------|---------|------|
| 轻量级规划 | OFF | 若论文声称"系统使用显式规划"，需加 "when enabled" |
| 工作流模板 | OFF | 若论文声称"系统使用模板先验"，需加 "when enabled" |
| 有界计划修复 | OFF | 同上 |
| 文件分析 LLM 回退 | OFF | 论文中的"文件接地"如包含此机制需说明 |
| 修复感知继续 | OFF | 消融实验默认配置需检查 |

### 10.2 实现部分完成的机制

**vehicle_pollutant_relevance 约束：** `config/cross_constraints.yaml` 中有槽位但 `rules: {}` 为空，未实际生效。若论文描述"车型-污染物约束验证"，当前代码不支持。

**preflight_check：** 除 DispersionTool 外，所有工具返回 `is_ready=True`，即预检机制仅在 Dispersion 层真正实现。

**legacy loop：** `_run_legacy_loop()` 仍存在（约1000+行），是技术债，但不影响论文描述（论文只需描述 `_run_state_loop` 路径）。

**LOCAL_STANDARDIZER_MODEL：** 本地 LoRA 标准化模型有训练脚本，但是否部署于生产/评测环境需确认。消融实验中 `no_standardization` 关闭的是 `ENABLE_EXECUTOR_STANDARDIZATION`，使用的标准化后端需澄清。

### 10.3 代码中存在但论文可能忽视的细节

**几何恢复（GeometryRecovery）：** 当扩散工具需要路段几何但当前文件无几何时，系统支持通过附加空间文件重新接地。这是一个有实际意义的能力，但可能被论文遗漏。

**会话上下文持久化（SessionContextStore）：** 工具结果在多轮会话中持久保存，支持 `compare_scenarios` 跨轮比较。这是多轮对话的基础，在论文中如涉及场景对比分析应提及。

**输出安全（output_safety）：** `sanitize_response()` 对每个回答应用内容过滤，但具体规则不透明。

**合成提示词（SYNTHESIS_PROMPT）：** 明确要求"不编造数值"、"只使用工具返回的实际数据"——这个 hallucination 防范机制值得在系统描述中提及。

### 10.4 评测设计的潜在问题

- **任务集规模：** `end2end_tasks.jsonl` 的任务数量未知（需检查），评测代表性需说明。
- **评测指标的自动化程度：** completion_rate 依赖 "completion signal" 关键词检测（40+模式词），存在假阳性/假阴性风险，论文中应说明。
- **几何依赖任务：** eval_end2end.py 中对 calculate_dispersion 和 render_spatial_map 等需要几何数据的工具有特殊处理（"geometry-gated"），消融实验中这类任务是否被正确处理需确认。

---

## Appendix A: Feature Flag 完整列表

| 环境变量 | 默认值 | 影响机制 |
|---------|-------|---------|
| ENABLE_STATE_ORCHESTRATION | true | 状态机 vs 遗留循环 |
| ENABLE_TRACE | true | 审计追踪 |
| PERSIST_TRACE | false | 追踪持久化到磁盘 |
| ENABLE_FILE_ANALYZER | true | 文件接地分析 |
| ENABLE_FILE_CONTEXT_INJECTION | true | 文件上下文注入 LLM |
| ENABLE_EXECUTOR_STANDARDIZATION | true | 执行侧参数标准化 |
| ENABLE_CROSS_CONSTRAINT_VALIDATION | true | 跨约束验证 |
| ENABLE_PARAMETER_NEGOTIATION | true | 参数协商 |
| ENABLE_READINESS_GATING | true | 就绪门控 |
| ENABLE_LIGHTWEIGHT_PLANNING | **false** | 显式 LLM 规划 |
| ENABLE_BOUNDED_PLAN_REPAIR | **false** | 有界计划修复 |
| ENABLE_REPAIR_AWARE_CONTINUATION | **false** | 修复感知继续 |
| ENABLE_WORKFLOW_TEMPLATES | **false** | 工作流模板先验 |
| ENABLE_FILE_ANALYSIS_LLM_FALLBACK | **false** | 文件分析 LLM 回退 |
| ENABLE_CAPABILITY_AWARE_SYNTHESIS | true | 能力感知合成 |
| ENABLE_LLM_STANDARDIZATION | true | LLM 标准化回退 |
| ENABLE_CONTOUR_OUTPUT | true | 扩散等值线输出 |
| ENABLE_INPUT_COMPLETION_FLOW | true | 输入补全流程 |
| READINESS_REPAIRABLE_ENABLED | true | 可修复状态检测 |
| READINESS_ALREADY_PROVIDED_DEDUP_ENABLED | true | 已提供去重 |

---

## Appendix B: 模块依赖拓扑（简化）

```
UnifiedRouter (core/router.py)
  ├── TaskState (core/task_state.py)
  ├── Trace (core/trace.py)
  ├── ReadinessAssessment (core/readiness.py)
  │     └── ArtifactMemory (core/artifact_memory.py)
  ├── ParameterNegotiation (core/parameter_negotiation.py)
  ├── InputCompletion (core/input_completion.py)
  │     └── RemediationPolicy (core/remediation_policy.py) [HCM tables]
  ├── FileRelationshipResolution (core/file_relationship_resolution.py)
  ├── SupplementalMerge (core/supplemental_merge.py)
  ├── IntentResolution (core/intent_resolution.py)
  ├── GeometryRecovery (core/geometry_recovery.py)
  ├── WorkflowTemplates (core/workflow_templates.py) [optional]
  ├── ExecutionPlan + PlanRepair (core/plan.py, core/plan_repair.py) [optional]
  ├── TOOL_GRAPH (core/tool_dependencies.py)
  ├── ToolExecutor (core/executor.py)
  │     ├── StandardizationEngine (services/standardization_engine.py)
  │     │     └── UnifiedStandardizer (services/standardizer.py)
  │     │           └── unified_mappings.yaml (config/)
  │     └── CrossConstraintValidator (services/cross_constraints.py)
  │           └── cross_constraints.yaml (config/)
  └── ToolRegistry (tools/registry.py)
        ├── FileAnalyzerTool (tools/file_analyzer.py)
        ├── MicroEmissionTool → VSPCalculator (calculators/vsp.py)
        ├── MacroEmissionTool → MacroEmissionCalculator (calculators/macro_emission.py)
        ├── DispersionTool → DispersionAdapter (calculators/dispersion_adapter.py)
        │     └── PS-XGB-RLINE surrogate (ps-xgb-aermod-rline-surrogate/)
        ├── HotspotTool → HotspotAnalyzer (calculators/hotspot_analyzer.py)
        ├── SpatialRendererTool (tools/spatial_renderer.py)
        ├── ScenarioCompareTool (tools/scenario_compare.py)
        ├── EmissionFactorsTool (tools/emission_factors.py)
        └── KnowledgeTool (tools/knowledge.py)
```

---

*文档结束。本文档基于 2026-04-08 代码状态生成，反映真实实现，不包含推断或期望能力。*
