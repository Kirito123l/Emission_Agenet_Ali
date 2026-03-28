# Emission Agent - 代码库技术深度分析

> 分析日期：2026-03-24
> 代码总量：~39,630 行 Python（含测试），~150+ 文件
> 架构版本：v2.0 (AI-First / Tool Use)

---

## 1. 架构设计

### 1.1 整体架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│                    用户交互层 (User Interface)                     │
│  Web UI (index.html/app.js)  │  CLI (main.py)  │  REST API       │
└──────────────────────┬───────────────────────────────────────────┘
                       │  HTTP / WebSocket
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                    API 网关层 (api/)                               │
│  routes.py (1078L)  │  session.py  │  auth.py  │  models.py      │
│  负责：HTTP 端点、文件上传、会话管理、认证、流式响应               │
└──────────────────────┬───────────────────────────────────────────┘
                       │  await router.chat(msg, file)
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│              核心路由层 (core/router.py, 1650L)                    │
│  UnifiedRouter: 系统的"大脑"                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │
│  │ 状态循环  │  │ 上下文    │  │ 工具执行  │  │ 结果综合         │ │
│  │ _run_    │  │ 组装      │  │ & 重试   │  │ _synthesize_    │ │
│  │ state_   │  │ assembler │  │ executor │  │ results()       │ │
│  │ loop()   │  │ .assemble │  │ .execute │  │                  │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘ │
│  辅助模块（已从 router.py 抽出）：                                │
│  router_payload_utils / router_render_utils /                    │
│  router_synthesis_utils / router_memory_utils                    │
└──────────────────────┬───────────────────────────────────────────┘
                       │
          ┌────────────┼────────────────┐
          ▼            ▼                ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  Assembler   │ │  Executor    │ │  Memory      │
│ (366L)       │ │ (362L)       │ │ (337L)       │
│ 上下文组装    │ │ 参数标准化    │ │ 三层记忆      │
│ + Skill注入  │ │ + 工具调用    │ │ Working/Fact │
│              │ │              │ │ /Compressed  │
└──────────────┘ └──────┬───────┘ └──────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────────────┐
│                    工具层 (tools/)                                 │
│  file_analyzer(601L) │ macro_emission(877L) │ micro_emission     │
│  emission_factors    │ dispersion(486L)     │ spatial_renderer   │
│  hotspot(184L)       │ scenario_compare     │ knowledge(73L)     │
│  override_engine(316L) │ formatter(138L)    │ definitions(403L)  │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                    计算引擎层 (calculators/)                       │
│  dispersion(1586L!)│ macro_emission(341L) │ micro_emission(242L)│
│  emission_factors(245L) │ hotspot_analyzer(567L) │ vsp(148L)    │
│  scenario_comparator(200L)│ dispersion_adapter(150L)            │
└──────────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                    服务层 (services/)                              │
│  standardizer(758L) │ standardization_engine(911L) │            │
│  llm_client(398L)   │ config_loader(152L)           │            │
│  负责：参数标准化级联、LLM API 调用、配置加载                      │
└──────────────────────────────────────────────────────────────────┘
```

**架构模式判定：单 Agent + Tool Calling + 状态机混合**

系统本质上是一个 **单 Agent 架构**，采用 OpenAI Function Calling 标准实现工具调用。核心决策由一个 LLM 完成（Qwen-Plus），没有多 Agent 协作。系统提供两条执行路径：
1. **Legacy Loop**（`_run_legacy_loop`）：经典的 LLM → Tool Call → Synthesize 单轮/重试循环
2. **State Loop**（`_run_state_loop`）：基于显式状态机（`TaskState`）的多步编排，状态流为 `INPUT_RECEIVED → GROUNDED → EXECUTING → DONE`

**没有使用任何已知框架**（LangChain、AutoGen 等），是完全自研的。这是一个有意的设计决策——避免框架依赖，保持对 LLM 调用流的完全控制。

### 1.2 模块划分与职责

| 模块 | 行数 | 职责 | 厚/薄 |
|------|------|------|-------|
| `core/router.py` | 1650 | 系统核心：状态循环、LLM 调用、工具编排、结果综合 | **最厚** — 系统的"上帝对象" |
| `services/standardization_engine.py` | 911 | 参数标准化级联引擎 | **厚** — 有实质设计 |
| `services/standardizer.py` | 758 | 规则标准化实现（精确/别名/模糊匹配） | **厚** — 领域映射 |
| `tools/macro_emission.py` | 877 | 宏观排放工具（文件读取+列映射+调用计算器） | **厚** — 数据处理密集 |
| `tools/spatial_renderer.py` | 788 | 空间渲染工具（GeoJSON 生成） | **厚** |
| `core/router_render_utils.py` | 770 | 从 router 抽出的渲染辅助 | 中等 |
| `tools/file_analyzer.py` | 601 | 文件分析（列语义识别、任务类型推断） | **厚** — 领域逻辑 |
| `calculators/dispersion.py` | 1586 | 高斯扩散模型计算 | **最厚计算逻辑** |
| `calculators/hotspot_analyzer.py` | 567 | 热点分析 | 厚 |
| `core/assembler.py` | 366 | 上下文组装 | 中等 |
| `core/executor.py` | 362 | 工具执行器 | 中等 |
| `core/memory.py` | 337 | 三层记忆管理 | 中等 |
| `core/task_state.py` | 283 | 状态机数据结构 | 薄 — 主要是数据类 |
| `core/trace.py` | 283 | 决策追踪 | 薄 — 数据记录 |
| `core/context_store.py` | 421 | 会话内工具结果存储 | 中等 |
| `core/skill_injector.py` | 238 | 技能注入（动态工具选择） | 中等 |
| `tools/knowledge.py` | 73 | 知识检索 | **薄** — 主要是 RAG 转发 |
| `tools/base.py` | 104 | 工具基类 | 薄 — 接口定义 |
| `core/tool_dependencies.py` | 83 | 工具依赖图 | **薄** — 静态配置 |

**职责模糊区域**：
- `router.py` 承担了过多职责（1650 行），既做状态管理、又做 payload 提取、又做 LLM 调用编排。虽然已抽出 4 个辅助模块，但主文件仍然是"上帝对象"。
- `tools/macro_emission.py`（877L）和 `calculators/macro_emission.py`（341L）之间的边界模糊：工具层做了大量数据转换工作（列名自动修正 `_fix_common_errors`、车队组成三级处理管线 global→link-level→fallback、4 种几何格式解析 WKT/GeoJSON/坐标列表/分隔符），计算层反而较薄（主要是 MOVES 矩阵查询和排放量乘法）。

### 1.3 分层设计

系统有 **5 层明确分层**：

1. **用户交互层**：Web UI（HTML/JS）+ API 端点（FastAPI routes）
2. **核心路由层**：`UnifiedRouter` — 意图理解 + 任务编排（由 LLM 驱动）
3. **工具层**：`tools/*` — 领域工具的参数处理和数据转换
4. **计算引擎层**：`calculators/*` — 纯计算逻辑（无 LLM 依赖）
5. **服务层**：`services/*` — 横切关注点（标准化、LLM 客户端、配置）

**分层边界评估**：
- 交互层 → 路由层：**清晰**。`api/routes.py` 只调用 `router.chat()`，接口干净。API 层还实现了 SSE 流式输出（分阶段状态更新 + 打字机效果 + 15 秒心跳保活），以及三级用户隔离（JWT → X-User-ID → UUID fallback）。
- 路由层 → 工具层：**清晰**。通过 `executor.execute(tool_name, args)` 统一调用。
- 工具层 → 计算层：**较清晰**。工具负责数据适配，计算器负责纯计算。
- 路由层 → 服务层：**隐式耦合**。标准化在 executor 中自动触发，对 router 透明，这是有意设计。

### 1.4 关键架构决策与设计理由

**有深度的设计决策**：

1. **"AI-First"哲学——信任 LLM，最小化规则**
   - 系统有意地将 guardrail 代码从 ~130 行削减到接近零，让 LLM 自然地处理模糊输入。这不是偷懒，而是经过 A/B 对比后的有意决策。
   - 理由：规则越多，prompt 越膨胀，LLM 理解越差。让 LLM 自己决定何时澄清、何时推断，效果反而更好。

2. **透明标准化——Executor 层自动处理，LLM 不可见**
   - 用户说"柴油大车"，LLM 直接传递原始文本给工具，Executor 在调用前自动将其标准化为"Combination Long-haul Truck"。LLM 永远不知道标准化的存在。
   - 级联策略：`exact → alias → fuzzy → LLM → default → abstain`（`standardization_engine.py:12`）
   - 这是一个深思熟虑的设计：如果让 LLM 做标准化，它可能会猜错；如果在 prompt 中列举所有合法值，会浪费大量 token。

3. **双执行路径（Legacy + State Loop）**
   - Legacy loop 简单直接：LLM 一次调用，出错重试最多 3 次。
   - State loop 更结构化：`INPUT_RECEIVED → GROUNDED → EXECUTING → DONE`，支持澄清中断和工具依赖检查。
   - 两条路径通过 `config.enable_state_orchestration` 开关切换。

4. **文件 mtime 缓存**
   - 同一会话中上传文件路径相同（`{session_id}_input.csv`），但内容可能变化。用 `os.path.getmtime` 检测变化，避免使用过期分析结果。

5. **Context Store 的语义版本化存储**
   - `context_store.py` 不是简单的"保存上次结果"。它按**语义类型+场景标签**存储结果（如 `emission:baseline`, `emission:scenario_speed30`），支持多场景对比而不覆盖。
   - 内置依赖失效机制：如果 emission 结果被更新，依赖它的 dispersion 和 hotspot 结果会被标记为 stale。
   - 检索时按依赖图查找：`render_spatial_map` 请求 `emission_map` 类型时，系统自动查找最近的 emission 结果。

**缺少明确设计决策的地方**：
- 工具依赖图（`tool_dependencies.py`）目前只有声明式定义，没有在执行时自动注入前置工具——只是记录了依赖关系，实际 auto-injection 代码虽然有 log 但不执行。
- `context_store.py` 和 `memory.py` 的职责有重叠：context_store 管理单轮内的工具结果传递，memory.fact_memory.last_spatial_data 管理跨轮的空间数据。两者有时存储同一份数据，边界不够清晰。

### 1.5 与通用 Agent 框架的区别

**和标准 "LLM + function calling" 的区别**：

| 特性 | 标准方案 | 当前系统 |
|------|----------|----------|
| 参数标准化 | 无 | 有完整的 6 级级联标准化 |
| 文件语义理解 | 无 | 有专门的文件分析工具 + 列映射逻辑 |
| 工具依赖管理 | 无 | 有工具依赖图 + 上下文注入 |
| 决策追踪 | 无 | 有结构化的 Trace 机制 |
| 多步编排 | 无（单轮） | 有状态循环支持多步 |
| 短路综合 | 无（全部走 LLM） | 有确定性渲染，跳过不必要的 LLM 调用 |
| 记忆系统 | 无/简单历史 | 三层：Working + Fact + Compressed |

**排放分析领域特定设计**：
1. **车辆/污染物/季节的多语言标准化映射**（`unified_mappings.yaml`，13 种 MOVES 车型 + 中英别名）
2. **微观/宏观排放双路径自动识别**（文件分析器根据列名判断数据类型）
3. **VSP（Vehicle Specific Power）计算模型**嵌入计算层
4. **EPA MOVES 排放因子数据库**直接查询
5. **高斯扩散模型**（1586 行，支持 Gaussian plume + AERMOD-RLINE surrogate）
6. **GIS 空间渲染**（GeoJSON 生成 + Leaflet 前端渲染）
7. **排放热点分析**（基于扩散浓度栅格的空间聚类）

### 1.6 架构的可扩展性

**新增分析工具**：
1. 在 `tools/` 创建工具类，继承 `BaseTool`
2. 在 `tools/definitions.py` 添加 OpenAI function schema
3. 在 `tools/registry.py` 注册
4. （可选）在 `calculators/` 添加计算引擎
5. （可选）在 `config/skills/` 添加技能描述 YAML

需要改动 3-4 个文件，核心逻辑（router/executor）**无需修改**。这是良好的扩展性设计。

**新增文件格式**：只需修改 `tools/file_analyzer.py`（已支持 CSV、Excel、ZIP/Shapefile）。

**工具热插拔**：通过 `tools/registry.py` 的注册表模式，支持运行时注册。但实际上工具在启动时一次性初始化，不支持真正的热插拔。

---

## 2. Agent 核心逻辑分析

### 2.1 决策与推理

**LLM 角色**：LLM（Qwen-Plus）负责以下决策：
- 理解用户意图
- 选择调用哪个工具（或直接回复）
- 决定工具参数（使用用户原始表述）
- 在工具出错后决定是重试、换工具还是向用户澄清
- 综合工具结果生成自然语言回复

**规则/代码负责**：
- 参数标准化（将中文表述映射为 MOVES 标准名）
- 文件分析和任务类型推断（基于列名模式匹配）
- 工具依赖检查
- 幻觉关键词检测（`["相当于", "棵树", "峰值出现在"]`）
- 输出安全过滤（`output_safety.py`）

**约束注入**：系统在 LLM 决策**之后**施加约束——标准化在工具执行前自动发生，LLM 不知道也无法绕过。这是一个关键的设计选择：领域约束由代码保证，不依赖 prompt。

### 2.2 任务规划

系统没有显式的"先生成计划再执行"机制。

**State Loop 模式**：通过状态机驱动的隐式规划。状态转换是即时的——当前步骤完成后立即决定下一步。没有"预先生成 N 步计划"的环节。

**多步编排实现**：在 `_state_handle_executing` 中，工具执行后，LLM 的响应会被检查：如果 LLM 返回新的 tool_call，则继续执行（最多 `max_orchestration_steps`）；如果返回纯文本，则终止。这是一个 **LLM 驱动的逐步展开** 模式。

### 2.3 状态管理

**TaskState 数据结构**（`core/task_state.py`）：
```python
class TaskStage(Enum):
    INPUT_RECEIVED = "INPUT_RECEIVED"
    GROUNDED = "GROUNDED"          # 文件已分析，参数已解析
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    EXECUTING = "EXECUTING"
    DONE = "DONE"

@dataclass
class TaskState:
    stage: TaskStage
    user_message: str
    parameters: Dict[str, ParamEntry]  # 参数及其标准化状态
    file_context: FileContext           # 文件分析结果
    execution: ExecutionContext          # 工具执行上下文
    control: ControlFlags               # 最大步数、是否需要澄清等
```

状态追踪是显式的、结构化的，存在内存变量中。状态信息直接影响后续决策（如 `NEEDS_CLARIFICATION` 会终止执行循环并返回澄清问题）。

**三层记忆**：
1. **Working Memory**：最近 5 轮对话（user + assistant + tool_calls）
2. **Fact Memory**：结构化事实（`recent_vehicle`, `recent_pollutants`, `recent_year`, `file_analysis`, `last_spatial_data`）
3. **Compressed Memory**：旧对话的压缩摘要（实际上这部分实现较简单，主要是截断旧轮次）

### 2.4 工具调用

**实现方式**：标准 OpenAI Function Calling 格式。工具定义在 `tools/definitions.py` 中以 JSON Schema 声明，通过 `llm.chat_with_tools(messages, tools, system)` 传递给 LLM。

**当前工具清单**：

| 工具 | 输入 | 输出 | 依赖 |
|------|------|------|------|
| `analyze_file` | file_path | task_type, columns, mapping | 无 |
| `query_emission_factors` | vehicle_type, pollutants, model_year | 速度-排放曲线 + 图表 | 无 |
| `calculate_micro_emission` | file_path, vehicle_type, pollutants | 逐秒排放结果 + Excel | 无 |
| `calculate_macro_emission` | file_path, pollutants, model_year | 路段排放结果 + Excel + GeoJSON | 无 |
| `calculate_dispersion` | _last_result (排放结果) | 浓度场栅格 | emission_result |
| `analyze_hotspots` | _last_result (扩散结果) | 热点位置 | dispersion_result |
| `render_spatial_map` | _last_result | GeoJSON 地图载荷 | 无（但需要空间数据） |
| `compare_scenarios` | _context_store | 场景对比报告 | 无 |
| `query_knowledge` | query, top_k | 知识库检索结果 | 无 |

**工具依赖**：`calculate_dispersion` 需要先有 `emission_result`，`analyze_hotspots` 需要先有 `dispersion_result`。Router 在 GROUNDED 阶段检查依赖。上游结果通过 `context_store` 或 `memory.fact_memory.last_spatial_data` 自动注入。

**注册方式**：
```python
# tools/registry.py
registry = ToolRegistry()
registry.register("analyze_file", FileAnalyzerTool())
registry.register("calculate_macro_emission", MacroEmissionTool())
# ...
```

### 2.5 错误处理

- **工具执行失败**：错误结果反馈给 LLM，LLM 可以选择重试、换参数或向用户解释。最多重试 `MAX_TOOL_CALLS_PER_TURN=3` 次。
- **标准化失败**：特殊处理——返回具体的建议值列表（如"您是否指的是：Passenger Car, Transit Bus..."），让用户澄清。
- **LLM 幻觉**：`_detect_synthesis_hallucination_keywords` 检测特定关键词（如"相当于 N 棵树"），发出警告日志（但不拦截）。
- **输出安全**：`output_safety.py` 对所有返回文本做 sanitize。
- **缺少正式的回退机制**：没有"如果所有重试都失败就用缓存结果"或"降级到简单回复"的策略。

---

## 3. 文件处理与任务理解

文件上传后的处理步骤：

1. **API 层接收**（`api/routes.py`）：保存为 `temp/{session_id}_input.{ext}`
2. **Router 检查缓存**：比对 `file_path + mtime`，命中则跳过分析
3. **FileAnalyzerTool 分析**（`tools/file_analyzer.py`, 601 行）：
   - 读取文件（Pandas DataFrame）
   - 清洗列名（strip、小写化）
   - **列语义匹配**：用关键词/模式匹配将列名映射到标准语义
   - **任务类型推断**：检查是否包含微观必需列（time, speed）或宏观必需列（link_length, traffic_flow, avg_speed）
   - 返回 `task_type`、`confidence`、`column_mapping`、`sample_rows`
4. **结果缓存到 Memory**：存入 `fact_memory.file_analysis`
5. **后续使用**：文件上下文注入 Assembler，LLM 在 system prompt 中看到文件结构信息

**列语义识别实现**：**纯规则**，基于关键词匹配和列名模式。不使用 LLM 进行列名推理。这是一个合理的设计——列名匹配是确定性问题，LLM 不比规则更好但更慢更贵。

```python
# file_analyzer.py 中的列映射逻辑（简化）
MICRO_COLUMN_PATTERNS = {
    "time": ["time", "t", "时间", "timestamp"],
    "speed": ["speed", "velocity", "速度", "v"],
    "acceleration": ["accel", "加速度", "a"],
}
MACRO_COLUMN_PATTERNS = {
    "link_length_km": ["length", "长度", "link_length"],
    "traffic_flow_vph": ["flow", "流量", "volume", "traffic"],
    "avg_speed_kph": ["speed", "平均速度", "avg_speed"],
}
```

文件分析模块是一个**有实质深度的模块**（601 行），包含了对 CSV、Excel、ZIP/Shapefile 的支持，以及对中英文列名的双语匹配逻辑。

---

## 4. 参数处理与约束机制

### 标准化级联

用户自然语言 → LLM 传递原始文本 → Executor 触发标准化：

```
"柴油大车" → exact match? NO
           → alias match? YES → "Combination Long-haul Truck"
           → confidence: 1.0, strategy: "alias"

"PM2.5颗粒物" → exact? NO → alias? YES → "PM2.5"

"晚高峰"     → exact? NO → alias? NO → fuzzy? NO → LLM fallback? → abstain
```

**参数空间定义**位于 `config/unified_mappings.yaml`：
- 13 种 MOVES 车型，每种有中英文别名列表 + VSP 参数
- 10+ 种污染物（CO2, CO, NOx, PM2.5, PM10, VOC, NH3, SO2, EC, OC）
- 4 季节、2 道路类型
- 每种参数有独立的模糊匹配阈值（`standardization_engine.py:46`）

**参数不合法时的处理**：
1. 标准化引擎返回 `StandardizationError`，带有 `suggestions` 列表
2. Executor 将其包装为特殊错误类型 `error_type: "standardization"`
3. Router（State Loop）识别此错误，转入 `NEEDS_CLARIFICATION` 状态
4. 向用户展示建议值列表，等待用户选择

标准化代码量：`standardizer.py`(758L) + `standardization_engine.py`(911L) = **1669 行**，是系统中最重的非 UI 模块之一。这是系统最核心的领域特定设计之一。

---

## 5. 多步工作流编排

### 典型工作流

**工作流 A：宏观排放计算**
```
用户上传文件 + "计算这些路段的CO2排放"
  → analyze_file → task_type="macro_emission"
  → calculate_macro_emission → 路段排放结果 + Excel + GeoJSON
  → _synthesize_results → 自然语言摘要
```

**工作流 B：排放→扩散→热点→可视化**（最复杂，4步）
```
用户上传文件 + "分析这个区域的污染扩散情况"
  → analyze_file → task_type="macro_emission"
  → calculate_macro_emission → emission_result
  → calculate_dispersion → concentration_grid (需要上一步结果)
  → analyze_hotspots → hotspot_locations (需要扩散结果)
  → render_spatial_map → GeoJSON 地图
```

### 步骤间依赖

依赖关系通过两种机制实现：
1. **声明式**：`core/tool_dependencies.py` 中的 `TOOL_GRAPH` 定义 requires/provides
2. **运行时注入**：`router._prepare_tool_arguments()` 自动从 `context_store` 或 `memory.last_spatial_data` 注入 `_last_result`

**自动编排能力**：系统可以在一个 turn 中自动执行多步——LLM 执行完一个工具后，如果 LLM 返回下一个 tool_call，Router 会继续执行（最多 `max_orchestration_steps`）。这不是预先规划的，而是 LLM 逐步决定的。

**工作流中断后恢复**：通过 `NEEDS_CLARIFICATION` 状态实现。当缺少关键参数时，系统暂停并向用户提问。用户回答后在下一个 turn 继续，但**当前状态不会跨 turn 持久化**——新的 turn 会重新初始化 TaskState。恢复能力依赖 Memory（fact_memory 保留了文件分析和上次工具结果）。

---

## 6. 结果交付与可视化

**结果呈现方式**：
- **自然语言**：LLM 综合工具结果生成解释性文本
- **表格**：排放结果预览（前 N 行），通过 `table_data` payload 传递前端
- **图表**：排放因子速度曲线图（ECharts 配置），通过 `chart_data` payload
- **下载文件**：详细计算结果 Excel 文件
- **GIS 地图**：GeoJSON 路网排放分布，前端用 Leaflet 渲染

**GIS 空间可视化**：
- `tools/spatial_renderer.py`（788L）生成 GeoJSON，包含路段排放着色、浓度栅格、热点标注
- 前端 `web/app.js` 用 Leaflet.js 渲染地图
- 支持多图层：排放强度、浓度等值线、热点位置

**扩散分析**：
- `calculators/dispersion.py`（1586L）实现了**完整的大气扩散计算引擎**，包括：
  - WGS84↔UTM 坐标变换
  - 道路几何分段（10m 间隔）+ 缓冲区创建（7m 默认宽度）
  - 受体点生成（基于道路偏移规则：3.5m→40m）
  - PS-XGB-AERMOD-RLINE surrogate 模式（XGBoost 代理模型替代完整 AERMOD-RLINE 计算）
  - Pasquill-Gifford 稳定度分类（6 级：VS/S/N1/N2/U/VU）
  - 逐受体道路贡献追溯（Top-N roads per receptor）
  - 栅格化浓度场输出 + 覆盖率评估
  - 气象预设系统（`meteorology_presets.yaml`：城市夏日/冬日/夜间等场景）
- `tools/dispersion.py`（486L）在工具层增加了气象参数处理（预设名/自定义dict/.sfc文件三种模式）
- 这是系统中最重的计算模块，有实质性的物理建模和工程实现深度

**结果解释**：混合模式。单工具成功时使用确定性渲染模板（`router_render_utils.py`中的 `render_single_tool_success`），跳过 LLM 调用节省 token；多工具或复杂场景才调用 LLM 综合。

---

## 7. 透明性与可审计性

**Decision Trace 机制**（`core/trace.py`）：

```python
class TraceStepType(Enum):
    FILE_GROUNDING = "file_grounding"
    PARAMETER_STANDARDIZATION = "parameter_standardization"
    TOOL_SELECTION = "tool_selection"
    TOOL_EXECUTION = "tool_execution"
    STATE_TRANSITION = "state_transition"
    CLARIFICATION = "clarification"
    SYNTHESIS = "synthesis"
    ERROR = "error"
```

每个决策步骤记录：
- 步骤类型、时间戳
- 状态转换（before → after）
- 执行动作、输入/输出摘要
- 置信度、推理原因
- 标准化记录（原始值 → 标准化值 + 策略 + 置信度）
- 耗时

**用户可见性**：Trace 通过 API 返回（`RouterResponse.trace` 和 `trace_friendly`），前端可以展示决策过程。但前端目前对 trace 的展示能力有限。

**实现深度**：Trace 机制在 State Loop 中已完整实现，每个关键步骤都有记录。Legacy Loop 中的 trace 较简单（只是嵌套 dict）。总体来说，这是一个**已实现且有实质深度**的特性。

---

## 8. Prompt 工程

### System Prompt（`config/prompts/core.yaml`，~73 行）

核心设计意图：**极简主义**。

```yaml
你是一个智能机动车排放计算助手。

## 交互原则
1. 理解用户的真实意图，即使表达不完整或不规范
2. 信息不足时，友好地询问，并给出选项或建议
3. 使用工具获取数据，不要编造数据
4. 回复简洁清晰，突出关键结果

## 特别重要：车辆类型确认
- 绝不假设或猜测车辆类型
- 如果用户没有明确说明车型，必须先询问

## 关于文件
- task_type 已明确时，不要再询问用户是宏观还是微观
```

**显式行为约束**：
- "绝不假设或猜测车辆类型"
- "不要编造数据"
- "task_type 已明确时，不要再询问"

### Synthesis Prompt（router.py 内联，~10 行）

```python
SYNTHESIS_PROMPT = """你是机动车排放计算助手。基于工具执行结果生成专业回答。
## 要求
1. 只使用工具返回的实际数据，不要编造或推算数值
2. 总结关键结果（总排放量、计算参数、统计信息）
3. query_knowledge 工具：完整保留返回的答案和参考文档
4. 其他工具：不要添加"参考文档"字样
5. 失败时说明问题并给出建议
"""
```

### 技能描述文件（`config/skills/*.yaml`）

当启用 Skill Injection 模式时，`core/skill_injector.py` 通过**关键词意图检测 + 依赖扩展 + 后置引导**动态选择相关技能注入 system prompt：

```python
# 意图规则示例（skill_injector.py）
INTENT_RULES = {
    "dispersion": {
        "keywords": ["扩散", "浓度", "dispersion", "大气"],
        "skills": ["dispersion_skill", "meteorology_guide"]
    },
    "scenario": {
        "keywords": ["情景", "对比", "如果", "假设", "降低", "提高"],
        "skills": ["scenario_skill"]
    },
}
```

技能文件包含领域特定的操作指导，例如 `dispersion_skill.yaml` 要求 LLM 在调用扩散工具前先向用户确认气象参数。还支持自动依赖扩展（用户说"热点分析"但无扩散结果时，自动加载 dispersion 技能）和后置引导（执行完排放计算后注入 `post_emission_guide` 建议可视化或扩散分析）。

**Prompt 结构化程度**：中等。使用 Markdown 格式的条目化规则，但没有 JSON Schema 或 XML 标签的严格结构。工具定义使用标准 OpenAI Function Calling JSON Schema，结构化程度高。

---

## 9. 端到端流程走查

### 场景 A：用户上传路网文件，计算路段排放

```
用户: [上传 road_links.xlsx] "帮我计算这些路段的CO2和NOx排放"

1. API层 (routes.py:chat_with_file)
   → 保存文件到 temp/fcfd..._input.xlsx
   → 创建/获取 UnifiedRouter(session_id)

2. Router.chat()
   → _run_state_loop()
   → TaskState.initialize(user_msg, file_path)
   → stage = INPUT_RECEIVED

3. _state_handle_input()
   → 文件未缓存 → _analyze_file()
   → FileAnalyzerTool.execute(file_path)
   → 读取 Excel → 检测列名 → 发现 link_length, traffic_flow, avg_speed
   → task_type = "macro_emission", confidence = 0.95
   → state.update_file_context(analysis)
   → Trace: FILE_GROUNDING

4. Assembler.assemble()
   → 加载 core.yaml system prompt
   → 注入文件上下文（"用户上传了 road_links.xlsx, 包含 120 行, 列: ..."）
   → 注入 working memory（最近 5 轮）
   → 注入 fact memory
   → 返回 AssembledContext(messages, tools, system_prompt)

5. LLM.chat_with_tools(messages, tools, system)
   → LLM 理解用户意图
   → 返回 tool_call: calculate_macro_emission(
       file_path="temp/fcfd..._input.xlsx",
       pollutants=["CO2", "NOx"],
       model_year=2020
     )
   → Trace: TOOL_SELECTION
   → stage → GROUNDED

6. _state_handle_grounded()
   → _identify_critical_missing() → None (参数齐全)
   → stage → EXECUTING

7. _state_handle_executing()
   → executor.execute("calculate_macro_emission", args)
     → _standardize_arguments():
       "CO2" → exact match → "CO2" ✓
       "NOx" → exact match → "NOx" ✓
     → MacroEmissionTool.execute():
       → 读取 Excel → 列名映射 → 调用 MacroEmissionCalculator
       → 查询 MOVES 排放因子 → 逐路段计算排放
       → 生成 Excel 结果文件
       → 返回 ToolResult(data={results, summary, download_file, map_data})
   → Trace: TOOL_EXECUTION (duration: ~2000ms)
   → _save_result_to_session_context()
   → stage → DONE

8. _state_build_response()
   → _synthesize_results() or 短路渲染
   → _extract_frontend_payloads() → chart_data, table_data, map_data, download_file
   → RouterResponse(text="计算完成。120个路段的排放结果：CO2总排放量 245.6 kg/h...")

9. Memory.update()
   → 添加到 working_memory
   → 更新 fact_memory (recent_pollutants=["CO2","NOx"])
   → 持久化到 JSON 文件
```

### 场景 B：模糊输入 "帮我看看这个区域的污染情况"

```
用户: "帮我看看这个区域的污染情况"（无文件上传）

1. Router._run_state_loop()
   → state.file_context.has_file = False
   → Assembler.assemble() → 注入 memory（可能有之前的文件）

2. LLM 决策:
   → 情况A: 如果 memory 中有活跃文件
     → LLM 可能调用 calculate_macro_emission 或 render_spatial_map
   → 情况B: 如果 memory 为空
     → LLM 返回澄清文本: "请问您想分析哪个区域？您可以上传路网数据文件..."

3. 如果 LLM 直接回复（无 tool_call）:
   → stage → DONE
   → RouterResponse(text="请上传数据文件或提供更多信息...")
```

系统**不会自动追问**（没有硬编码的追问逻辑），而是**依赖 LLM 的自然判断**。如果 LLM 认为信息不足，它会自然地要求更多信息。这符合"AI-First"哲学。

### 场景 C：排放→扩散→可视化

```
用户: [上传文件] "计算排放，然后做扩散分析，画在地图上"

1. analyze_file → macro_emission
2. LLM 第一轮: tool_call = calculate_macro_emission
   → 执行成功 → 结果存入 context_store
3. LLM 第二轮（看到 tool result 后）: tool_call = calculate_dispersion
   → _prepare_tool_arguments() 自动注入 _last_result (排放数据)
   → 执行高斯扩散计算 → 浓度栅格
4. LLM 第三轮: tool_call = render_spatial_map
   → 自动注入扩散结果 → 生成 GeoJSON
5. LLM 第四轮: 返回文本回复
   → _synthesize_results() → 综合所有工具结果
   → RouterResponse(text=..., map_data=..., download_file=...)
```

多步衔接通过 **LLM 自然续接 + Router 自动数据注入** 实现。LLM 看到工具结果后决定下一步调什么，Router 负责在底层把上游结果注入下游工具。

---

## 10. 当前系统的优势与不足

### 设计良好的部分

1. **参数标准化级联**（1669 行）：6 级策略、中英文别名、模糊匹配、LLM fallback——这是一个经过深思熟虑的、有论文深度的机制。
2. **透明标准化的架构决策**：将标准化放在 Executor 层，对 LLM 不可见。这避免了 prompt 膨胀和 LLM 误解问题。
3. **文件语义理解**（601 行）：列名模式匹配 + 任务类型推断，是领域特定的有价值设计。
4. **高斯扩散计算引擎**（1586 行）：完整的物理模型实现，不是玩具。
5. **Trace 机制**：结构化决策记录，支持审计和调试。
6. **短路综合**：单工具成功时跳过 LLM 综合，节省 token 和延迟。

### 实现较浅的部分

1. **知识检索（RAG）**：`tools/knowledge.py` 只有 73 行，主要是对 `skills/knowledge/` 的薄包装。检索器和重排序器有基本实现，但整体 RAG 深度有限。
2. **Compressed Memory**：名义上有三层记忆，但压缩层实际上只是简单截断旧轮次，没有真正的摘要生成或知识蒸馏。
3. **工具依赖图**：`tool_dependencies.py`（83 行）只是声明式定义，虽然 Router 在 GROUNDED 阶段会检查依赖，但不会自动注入前置工具——只记录了依赖关系和日志，实际执行还是依赖 LLM 自己决定。
4. **Skill Injection**：有机制但较基础，主要是根据文件类型/用户意图选择加载哪些技能描述。
5. **前端可视化**：单页 HTML + vanilla JS，功能可用但工程化程度低，没有组件化框架。

### "打开盖子"实际内容有限的模块

- `core/output_safety.py`（47 行）：目前只做了基本的文本清理，不是真正的安全过滤。
- `core/coverage_assessment.py`（240 行）：评估排放计算的覆盖率，但逻辑主要是阈值检查。
- `core/router_memory_utils.py`（48 行）：很薄的辅助函数。
- `skills/` 目录：旧的 skill 架构，大部分逻辑已迁移到 `tools/`，保留用于兼容。

### 和"纯用 ChatGPT + 手动操作"的核心优势

1. **自动参数标准化**：用户可以用任何中文表述，系统自动映射到 MOVES 标准名。手动操作需要用户自己查表。
2. **文件驱动的自动工作流**：上传文件后系统自动识别数据类型并选择正确的计算路径。
3. **集成计算引擎**：VSP 排放计算（14 bin 模态推断 + 逐秒积分）、MOVES 矩阵查询（速度编码 `{speed_mph}{0}{road_type_id}`）、高斯扩散代理模型、热点空间聚类——这些不是 ChatGPT 能做的。
4. **GIS 可视化**：计算结果直接在地图上展示。
5. **跨步骤数据流**：工具结果自动传递给下游工具，用户不需要手动复制粘贴。

### 三个最大技术短板

1. **Router.py 过度膨胀**（1650 行）：虽然已抽出 4 个辅助模块，但主文件仍然是上帝对象。Legacy Loop 和 State Loop 两套执行路径共存增加了复杂度。
2. **缺少持久化的工作流状态**：TaskState 不跨 turn 持久化。如果用户在多步工作流中断开连接再回来，只能依赖 Memory 中的残余信息恢复，不能精确恢复到中断点。
3. **评估体系覆盖有限**：有 evaluation 框架和 smoke suite，但端到端评估只覆盖了少量固定场景（标准化准确率、文件 grounding、基本流程）。没有覆盖多步工作流、扩散分析、热点分析等复杂路径。

---

## 11. 代码质量与工程成熟度

### 代码组织
- **结构清晰**：`core/`, `tools/`, `calculators/`, `services/`, `api/`, `web/` 分层明确
- **命名一致**：模块、类、函数命名规范
- **文档**：有 README、ARCHITECTURE.md、多份阶段性报告

### 测试
- **40+ 测试文件**，覆盖了核心路由、工具、计算器、标准化引擎、状态管理、trace、API 路由等
- 有 `conftest.py` 和 mock 基础设施
- 有 evaluation 框架（标准化评估、文件 grounding 评估、端到端评估、消融实验）
- 测试代码量约占总代码的 25-30%

### 配置管理
- 支持多 LLM 提供商：Qwen、DeepSeek、本地/OpenAI 兼容
- `config.py` 集中管理运行时配置（feature flags、模型选择、标准化配置）
- `.env` 管理 API key
- 标准化映射在 YAML 配置文件中

### 日志和监控
- 使用 Python logging，配有 `api/logging_config.py`
- access log 持久化到文件
- 工具执行有详细的 trace 和 duration 记录
- 无 metrics 收集或外部监控集成

### 代码量统计
- Python 源文件：~100+ 个（不含测试）
- 测试文件：~40 个
- 总行数：~39,630 行
- 最大文件：`core/router.py`（1650L）、`calculators/dispersion.py`（1586L）
- 配置文件：~10 个 YAML

---

## 总结评估

### 架构设计深度

当前系统**不是一个简单的 LLM + 工具调用包装**。它在以下方面有论文级别的设计深度：

1. **透明参数标准化架构**：将 NL→标准参数 的映射从 LLM prompt 中剥离，放到 Executor 层自动处理的 6 级级联策略。这是一个可量化、可评估、可消融的架构创新。
2. **文件驱动的任务推断**：通过列语义匹配自动识别数据类型和分析路径，是领域特定的有价值设计。
3. **多步工具编排的数据流管理**：context_store + 自动注入 `_last_result` 的机制，解决了多步工作流中的数据传递问题。

### 需要加深的方向

1. **状态管理的持久化和恢复**：当前 TaskState 是单 turn 的。如果能持久化并支持跨 turn 恢复，会显著增加系统的鲁棒性和论文深度。
2. **规划机制**：当前系统是"逐步展开"的，没有预先规划。引入一个轻量的 Plan 阶段（LLM 先输出执行计划，再逐步执行）会增加可解释性。
3. **评估体系**：需要覆盖更多场景的端到端评估，特别是多步工作流、参数标准化的边界情况、扩散计算的数值正确性。
4. **Router 重构**：将 1650 行的 router 拆分为更小的、职责单一的组件（如 Orchestrator、Synthesizer、PayloadExtractor），提高可维护性和可测试性。
