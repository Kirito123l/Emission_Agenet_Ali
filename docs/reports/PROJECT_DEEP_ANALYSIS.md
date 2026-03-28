# Emission Agent 项目深度技术分析

## 项目概述

Emission Agent 是一个面向机动车排放分析场景的 LLM-native agent 系统。它以 `UnifiedRouter` 为中心，将 Web/API 入口、文件预分析、上下文组装、LLM function calling、工具执行、排放计算引擎、结果可视化与会话记忆串联为统一闭环。与通用对话式工具代理不同，该系统的两个核心方法论特征是：一方面，上传文件会被主动解析为 `task_type + column semantics + file context`，从而驱动工具选择而非仅作为被动附件；另一方面，LLM 输出的自然语言参数不会直接进入计算器，而是先经过执行侧标准化，再映射到受控的 MOVES-compatible 参数空间。系统同时支持排放因子查询、微观轨迹排放、宏观路段排放、知识检索与 GIS 地图交付，并已具备初步的 benchmark、ablation 与 smoke 验证框架，但距离 SCI 论文级证据仍需进一步补充系统实验。

## 目录

- [1. 系统架构与核心数据流](#1-系统架构与核心数据流)
- [2. 文件驱动任务锚定与执行侧参数标准化](#2-文件驱动任务锚定与执行侧参数标准化)
- [3. 工具链实现与计算引擎](#3-工具链实现与计算引擎)
- [4. 记忆管理、结果合成与交付](#4-记忆管理结果合成与交付)
- [5. 现有评估体系与回归覆盖](#5-现有评估体系与回归覆盖)
- [6. 面向论文的实验设计与差距分析](#6-面向论文的实验设计与差距分析)
- [7. 系统局限性与未来工作](#7-系统局限性与未来工作)
- [8. 论文写作行动清单](#8-论文写作行动清单)

---

## 1. 系统架构与核心数据流

### 1.1 分层架构

从 live code 看，系统可以抽象为 5 层：

1. **入口层**
   - `run_api.py`
   - `main.py`
   - 负责启动 FastAPI、CLI、工具注册与运行时配置加载

2. **API / Session 层**
   - `api/main.py`
   - `api/routes.py`
   - `api/session.py`
   - 负责 HTTP 请求、文件上传、流式输出、会话历史和下载接口

3. **核心路由层**
   - `core/router.py`
   - `core/assembler.py`
   - `core/executor.py`
   - `core/memory.py`
   - 负责文件预分析、prompt 组装、tool calling、执行、结果综合和记忆更新

4. **工具执行层**
   - `tools/registry.py`
   - `tools/definitions.py`
   - `tools/*.py`
   - 负责工具 schema 暴露、运行时分发、文件 I/O、结果包装

5. **计算与服务层**
   - `calculators/*.py`
   - `services/standardizer.py`
   - `services/llm_client.py`
   - `llm/client.py`
   - 负责排放计算、参数标准化、RAG、云端或本地模型访问

可用一条统一链路概括：

```text
User / Web / CLI
  -> API + Session
  -> UnifiedRouter
  -> ContextAssembler + MemoryManager
  -> LLM function calling
  -> ToolExecutor + ToolRegistry
  -> tools/*
  -> calculators/* / services/*
  -> synthesis + payload extraction
  -> API response / stream / session history / web rendering
```

### 1.2 核心对象与职责

#### 1.2.1 `UnifiedRouter`

位置：`core/router.py`

职责：

- 接收一轮用户输入
- 处理上传文件的预分析
- 调用 `ContextAssembler` 组装 prompt
- 触发 `chat_with_tools`
- 执行工具调用并处理错误重试
- 合成自然语言回答
- 抽取图表、表格、地图、下载文件
- 更新 `MemoryManager`

它是整个系统最重要的 orchestration 核心。

#### 1.2.2 `ContextAssembler`

位置：`core/assembler.py`

职责：

- 加载 `system_prompt`
- 加载 `TOOL_DEFINITIONS`
- 把 `fact_memory`、`working_memory`、`file_context` 组装成 LLM 输入
- 控制 token 预算与消息裁剪

#### 1.2.3 `ToolExecutor`

位置：`core/executor.py`

职责：

- 按 tool name 获取工具实例
- 在执行前做参数标准化
- 自动注入 `file_path`
- 执行具体工具
- 把 `ToolResult` 转成 router 可消费的统一字典结构

#### 1.2.4 `MemoryManager`

位置：`core/memory.py`

职责：

- 维护 `working_memory`
- 维护 `fact_memory`
- 维护 `compressed_memory`
- 跨轮持久化与恢复
- 从成功的 tool result 中抽取后续轮次可复用的事实

#### 1.2.5 `ToolRegistry`

位置：`tools/registry.py`

职责：

- 单例化管理工具实例
- 在应用启动或 executor 首次执行时注册全部工具
- 完成 tool schema 名称和 Python 对象之间的绑定

### 1.3 配置如何作用于架构

关键运行时开关在 `config.py`：

- `enable_file_analyzer`
- `enable_file_context_injection`
- `enable_executor_standardization`
- `macro_column_mapping_modes`
- `use_local_standardizer`
- `embedding_mode`
- `rerank_mode`

这些开关直接影响：

1. 文件是否先被 `analyze_file`
2. 文件摘要是否注入 prompt
3. executor 是否接管参数标准化
4. macro 列映射是否启用 `direct / ai / fuzzy`
5. 标准化是否尝试本地模型
6. RAG 的 embedding 与 rerank 路径

### 1.4 请求完整生命周期

以用户发送“计算这个文件的 CO2 排放”为例，完整链路如下。

#### 1.4.1 Step-by-step 调用链

1. **API 接收请求**
   - `api/routes.py::chat()` 或 `api/routes.py::chat_stream()`
   - 保存上传文件到 `/tmp/emission_agent/{session_id}_input{suffix}`
   - 把文件路径提示拼进当前消息

2. **Session 层转发**
   - `api/session.py::Session.chat()`
   - 调用 `UnifiedRouter.chat(user_message, file_path)`

3. **Router 预分析文件**
   - `core/router.py::UnifiedRouter.chat()`
   - 如果 `enable_file_analyzer=True`，调用 `_analyze_file(file_path)`
   - 本质上是 `ToolExecutor.execute("analyze_file", ...)`

4. **Assembler 组装上下文**
   - `core/assembler.py::ContextAssembler.assemble()`
   - 拼接：
     - `system_prompt`
     - 工具 schema
     - `fact_memory`
     - `working_memory`
     - `file_context`
     - 当前 user message

5. **LLM 决定是否调用工具**
   - `services/llm_client.py::LLMClientService.chat_with_tools()`
   - `tool_choice="auto"`
   - 返回 `LLMResponse(content, tool_calls)`

6. **Router 处理 tool calls**
   - `core/router.py::UnifiedRouter._process_response()`
   - 遍历 `response.tool_calls`
   - 逐个调用 `ToolExecutor.execute()`

7. **Executor 做透明标准化**
   - `core/executor.py::ToolExecutor._standardize_arguments()`
   - 标准化 `vehicle_type`、`pollutant`、`pollutants`
   - 需要时自动注入 `file_path`

8. **Tool 层执行**
   - `tools/*.py::execute()`
   - 完成文件读取、参数检查、调用 calculator、生成导出文件或地图载荷

9. **Calculator / Service 执行数值逻辑**
   - `calculators/*.py`
   - `services/standardizer.py`
   - `skills/knowledge/*`

10. **错误回填与重试**
    - 如果工具失败且未超过最大重试次数
    - `_process_response()` 会把错误作为 tool message 塞回上下文，再次调用 `chat_with_tools()`

11. **结果综合与 payload 提取**
    - `UnifiedRouter._synthesize_results()`
    - `core/router_payload_utils.py`
    - 提取 `chart_data / table_data / map_data / download_file`

12. **记忆更新**
    - `MemoryManager.update()`
    - 保存 `working_memory`、更新 `fact_memory`、缓存 `file_analysis`

13. **API 返回响应并保存 UI 历史**
    - `api/routes.py`
    - 规范化下载元数据
    - `Session.save_turn()`
    - Web 端渲染文本、图表、表格、地图

#### 1.4.2 生命周期伪代码

```python
async def handle_user_message(message, file):
    file_path = save_upload(file) if file else None
    router_result = await session.router.chat(message, file_path)
    normalized_download = normalize_download_file(router_result.download_file)
    session.save_turn(
        user_input=message,
        assistant_response=router_result.text,
        chart_data=router_result.chart_data,
        table_data=attach_download_to_table_data(router_result.table_data, normalized_download),
        map_data=router_result.map_data,
        download_file=normalized_download,
    )
    return router_result
```

### 1.5 `UnifiedRouter` 的决策逻辑

`UnifiedRouter.chat()` 的主逻辑可以概括为：

```text
chat()
  -> analyze file if needed
  -> assemble context
  -> chat_with_tools()
  -> _process_response()
  -> memory.update()
```

`_process_response()` 有三类分支：

1. **无 tool_calls**
   - 直接返回 `response.content`

2. **有 tool_calls 且执行出错**
   - 把错误整理成 tool feedback
   - 再次调用 `chat_with_tools()`

3. **有 tool_calls 且执行成功**
   - `_synthesize_results()`
   - 提取结构化 payload
   - 返回 `RouterResponse`

### 1.6 LLM function calling 的集成方式

function calling 的 schema 来源于 `tools/definitions.py::TOOL_DEFINITIONS`，经由：

- `services/config_loader.py::ConfigLoader.load_tool_definitions()`
- `core/assembler.py::ContextAssembler.__init__()`

最终进入：

- `services/llm_client.py::LLMClientService.chat_with_tools()`

返回结构：

```python
LLMResponse(
    content: str,
    tool_calls: Optional[List[ToolCall]],
    finish_reason: Optional[str]
)
```

其中 `ToolCall` 结构为：

```python
ToolCall(id: str, name: str, arguments: Dict[str, Any])
```

### 1.7 当前系统中需要统一的架构事实

为了后续论文表述一致，应以 live code 为准，统一以下几点：

1. **主入口是 `UnifiedRouter.chat()`**
   - 不是文档中常用的描述性 `process()`

2. **三层记忆都存在，但 prompt 主链路目前主要使用**
   - `working_memory`
   - `fact_memory`
   - 以及单独注入的 `file_context`
   - `compressed_memory` 当前未进入 assembler

3. **synthesis client 在配置中独立存在，但 router 目前复用了 agent client**
   - `UnifiedRouter.__init__()` 中 `self.llm = get_llm_client("agent", model="qwen-plus")`
   - `_synthesize_results()` 也通过 `self.llm.chat(...)` 完成

4. **tools 层仍保留过渡性的 `skills/` 依赖**
   - `tools/micro_emission.py` 仍调用 `skills.micro_emission.excel_handler.ExcelHandler`
   - `tools/macro_emission.py` 仍调用 `skills.macro_emission.excel_handler.ExcelHandler`

---

## 2. 文件驱动任务锚定与执行侧参数标准化

### 2.1 File-Driven Task Grounding 的核心思想

系统对上传文件的处理并非“文件路径直接交给模型”，而是先经过结构化文件分析，再把分析结果显式注入后续 routing context。这一机制的主入口是：

- `tools/file_analyzer.py::FileAnalyzerTool`
- `core/router.py::UnifiedRouter._analyze_file()`
- `core/assembler.py::ContextAssembler._format_file_context()`

它的作用链如下：

```text
uploaded file
  -> analyze_file
  -> task_type / columns / row_count / sample_rows / column mapping
  -> memory cache
  -> file context injection
  -> LLM tool routing / parameter inference
```

### 2.2 `FileAnalyzerTool` 的完整处理流程

`tools/file_analyzer.py::FileAnalyzerTool.execute(file_path, **kwargs)` 的流程分为三类：

1. **普通表格**
   - `.csv`
   - `.xlsx`
   - `.xls`

2. **ZIP 文件**
   - 若包含 `.shp`，进入 `Shapefile` 分支
   - 若包含表格，进入 `tabular zip` 分支

3. **不支持格式**
   - 直接返回错误

表格分析的核心函数是 `_analyze_structure(df, filename)`，输出：

- `filename`
- `row_count`
- `columns`
- `task_type`
- `confidence`
- `micro_mapping`
- `macro_mapping`
- `micro_has_required`
- `macro_has_required`
- `sample_rows`

### 2.3 如何从文件推断任务类型

`_identify_task_type(columns)` 采用启发式关键词计分：

#### 2.3.1 micro_emission 指示词

- `speed`
- `velocity`
- `速度`
- `time`
- `acceleration`
- `加速`

#### 2.3.2 macro_emission 指示词

- `length`
- `flow`
- `volume`
- `traffic`
- `长度`
- `流量`
- `link`

#### 2.3.3 confidence 生成

若某一类得分更高，则：

```text
confidence = min(0.5 + score * 0.15, 0.95)
```

若两类打平，则返回：

- `task_type = "unknown"`
- `confidence = 0.3`

Shapefile 特殊路径下，系统直接把任务类型视为 `macro_emission`。

### 2.4 文件分析不仅做分类，还做预映射

`FileAnalyzerTool` 不只输出任务类型，还会预先调用：

- `services.standardizer.map_columns(columns, "micro_emission")`
- `services.standardizer.map_columns(columns, "macro_emission")`

并进一步用：

- `get_required_columns("micro_emission")`
- `get_required_columns("macro_emission")`

判断：

- `micro_has_required`
- `macro_has_required`

这使文件预分析具备双重功能：

1. **任务锚定**
2. **列语义预检查**

### 2.5 文件元信息如何传递到后续阶段

文件信息的流转路径如下。

#### 2.5.1 API 保存文件路径

- `api/routes.py` 把上传文件保存到临时路径
- 并将文件路径拼入当前 user message

#### 2.5.2 Router 触发预分析

- `UnifiedRouter.chat()` 调用 `_analyze_file(file_path)`
- 内部通过 executor 执行 `analyze_file`

#### 2.5.3 结果缓存到 Memory

- `MemoryManager.update(... file_analysis=file_context)`
- `fact_memory.active_file`
- `fact_memory.file_analysis`

#### 2.5.4 Assembler 注入到 prompt

有两条通道：

1. **当前轮 file context 注入**
   - `_format_file_context(file_context)`
   - 直接 prepend 到当前 user message 前

2. **历史 fact memory 注入**
   - `_format_fact_memory(fact_memory)`
   - 形成一段系统上下文摘要

### 2.6 当前实现中“文件数据范围”的边界

这点在论文中需要统一。

#### 2.6.1 已实现

- 文件名
- 行数
- 列名
- 任务类型
- 置信度
- 列映射
- 是否具备 required columns
- 前两行 sample rows
- 若是 Shapefile，还包括 `geometry_types` 和 `bounds`

#### 2.6.2 尚未实现

当前 tabular file 分析并没有系统性输出：

- 数值列的 min/max/range
- 分布统计
- 缺失值率
- 单位检测

因此如果论文要写“列名、行数、数据范围共同参与任务锚定”，必须改成更准确的表述：

- 当前 live code 中，主作用信号是 **列名、样例行、行数与几何元信息**，而不是系统性数值范围特征。

### 2.7 文件信息如何影响工具选择

文件信息影响 routing 的方式主要有三种。

#### 2.7.1 system prompt 约束

`config/prompts/core.yaml` 会告诉模型：

- 结合 `task_type` 选择 `calculate_micro_emission` 或 `calculate_macro_emission`

#### 2.7.2 当前 user message 显式携带 file summary

Assembler 会把如下内容放到当前消息前：

```text
Filename: ...
File path: ...
task_type: ...
Rows: ...
Columns: ...
Sample (first 2 rows): ...
```

#### 2.7.3 tool schema 对 `file_path` 的要求

工具定义中明确说明：

- 当用户上传文件时应使用 `file_path`

这让模型更容易把 file-grounded intent 变成具体 tool_call。

### 2.8 论文视角：为什么这不是“被动附件”

从方法论上，这套机制的创新点在于：

1. 文件被先转换成结构化锚点，而不是盲目附加到 prompt
2. 文件分析结果直接影响 tool routing
3. 文件上下文可以跨轮保留
4. 文件结构与自然语言意图在 router 之前就被对齐

因此，“文件驱动任务锚定”是一个比传统“附件上传”更主动的任务 grounding 机制。

### 2.9 执行侧参数标准化的核心定义

执行侧参数标准化的本质是：

- **LLM 负责理解用户自然语言**
- **Executor 在工具执行前把参数转换到后端受控空间**

关键路径：

```text
LLM tool_call arguments
  -> ToolExecutor._standardize_arguments()
  -> tool.execute()
```

不是：

```text
LLM must directly emit fully standardized backend-safe parameters
```

### 2.10 标准化发生的精确时机

精确时机在：

- `core/router.py::_process_response()`
  -> `core/executor.py::ToolExecutor.execute()`
  -> `_standardize_arguments()`
  -> `tool.execute(**standardized_args)`

也就是说，它发生在：

1. LLM 已经决定调用哪个工具之后
2. 实际执行工具之前

### 2.11 `services/standardizer.py` 的工作流程

标准化器 `services/standardizer.py::UnifiedStandardizer` 会：

1. 加载 `config/unified_mappings.yaml`
2. 构建：
   - `vehicle_lookup`
   - `pollutant_lookup`
   - `column_patterns`
3. 提供：
   - `standardize_vehicle()`
   - `standardize_pollutant()`
   - `map_columns()`

#### 2.11.1 `standardize_vehicle()`

流程是：

1. exact lookup
2. fuzzy match
3. 如启用本地模型且置信度足够高，尝试 local fallback
4. 否则返回 `None`

#### 2.11.2 `standardize_pollutant()`

流程是：

1. exact lookup
2. fuzzy match
3. optional local model fallback
4. 否则返回 `None`

#### 2.11.3 `map_columns()`

当前主链路中主要采用：

1. exact match
2. substring match

列映射的本地模型能力虽然已有训练与部署准备，但尚未在新主链路里完全打通。

### 2.12 当前执行侧明确覆盖的参数类型

在 live code 中，`ToolExecutor._standardize_arguments()` 明确处理：

1. `vehicle_type`
2. `pollutant`
3. `pollutants`

具体表现为：

- `vehicle_type` 无法识别会抛出 `StandardizationError`
- `pollutant` 无法识别也会失败
- `pollutants` 列表中单项无法标准化时会保留原值并记录 warning

### 2.13 当前未统一覆盖的参数类型

这部分是论文中必须如实保留的边界：

1. 模糊 `model_year` 表述
2. 模糊 `season` 表述
3. 模糊 `road_type` 表述

虽然工具层和 calculator 层对这些参数有默认值或内部映射，但并不是通过 `executor -> standardizer` 完成统一自然语言标准化。

### 2.14 为什么要把标准化放在执行侧

这一设计比“让 LLM 直接输出标准参数”更合理，原因有五点：

1. 把意图理解与后端约束解耦
2. tool schema 可以保持自然语言友好
3. 标准化规则能独立迭代
4. 错误可以被显式建模为 `standardization` failure
5. 底层可替换规则、fuzzy、本地模型或云端模型

### 2.15 本地标准化模型路线

仓库中存在完整的本地标准化模型路线：

- `LOCAL_STANDARDIZER_MODEL/scripts/01_create_seed_data.py`
- `02_augment_data.py`
- `03_prepare_training_data.py`
- `04_train_lora.py`
- `06_evaluate.py`
- `configs/*.yaml`
- `shared/standardizer/local_client.py`
- `LOCAL_STANDARDIZER_MODEL/start_vllm.sh`

其特点：

1. 训练数据分为：
   - unified（vehicle + pollutant）
   - column mapping
2. 采用 LoRA 微调
3. 支持：
   - `direct`
   - `vllm`

但需要统一一个重要事实：

- 文档和配置中同时存在 4B 与 3B 路线
- 当前运行时默认值仍更多偏向 3B

### 2.16 当前标准化与 grounding 的统一边界

为避免全文互相矛盾，应统一以下说法：

1. `FileAnalyzerTool` 的任务锚定主要依赖列名启发式与样例行，而非 learned classifier
2. executor-side standardization 当前直接覆盖 vehicle / pollutant，不覆盖完整时态/季节/道路类型自然语言标准化
3. 本地标准化模型路线完整存在，但在 live main path 中是部分接入状态
4. macro file grounding 明显强于 micro file grounding 的语义映射能力

---

## 3. 工具链实现与计算引擎

### 3.1 工具注册与分发机制

工具注册中心在 `tools/registry.py::ToolRegistry`，使用单例模式管理 `_tools: Dict[str, BaseTool]`。

`init_tools()` 会注册：

- `query_emission_factors`
- `calculate_micro_emission`
- `calculate_macro_emission`
- `analyze_file`
- `query_knowledge`

工具 schema 则来自 `tools/definitions.py::TOOL_DEFINITIONS`，采用 OpenAI function calling 兼容格式。

运行时分发链路如下：

```text
TOOL_DEFINITIONS
  -> ContextAssembler
  -> LLMClientService.chat_with_tools()
  -> ToolCall(name, arguments)
  -> ToolExecutor.execute()
  -> ToolRegistry.get(name)
  -> tool.execute()
```

### 3.2 `ToolResult` 统一接口

所有工具都继承 `tools/base.py::BaseTool`，返回：

```python
ToolResult(
    success: bool,
    data: Optional[Dict[str, Any]],
    error: Optional[str],
    summary: Optional[str],
    chart_data: Optional[Dict],
    table_data: Optional[Dict],
    download_file: Optional[str],
    map_data: Optional[Dict[str, Any]],
)
```

运行时还存在一个实际扩展：

- `download_file` 常常是 dict 而不是单纯字符串

但 `router_payload_utils` 与 API 层已兼容这一点。

### 3.3 逐个工具分析

#### 3.3.1 `analyze_file`

实现：`tools/file_analyzer.py`

输入：

- 必选：`file_path`

逻辑：

1. 读取表格或 ZIP
2. 识别 `task_type`
3. 做列映射预分析
4. 检查 required fields
5. 返回 `row_count / columns / task_type / mapping / sample_rows`

协作关系：

- 既可被 LLM 显式调用
- 更重要的是会被 router 在有文件时隐式预调用

#### 3.3.2 `query_emission_factors`

实现：`tools/emission_factors.py`

输入：

- 必选：
  - `vehicle_type`
  - `model_year`
- 可选：
  - `pollutant` 或 `pollutants`
  - `season`
  - `road_type`
  - `return_curve`

逻辑：

1. 提取参数
2. 将单/多污染物统一成列表
3. 调用 `EmissionFactorCalculator.query(...)`
4. 组织单污染物或多污染物结果
5. 可选生成 Excel 下载文件

输出：

- `speed_curve` 或 `curve`
- `typical_values`
- `speed_range`
- `unit`
- `download_file`（若生成）

#### 3.3.3 `calculate_micro_emission`

实现：`tools/micro_emission.py`

输入：

- 必选：
  - `vehicle_type`
- 可选：
  - `file_path` / `input_file`
  - `trajectory_data`
  - `pollutants`
  - `model_year`
  - `season`
  - `output_file`

逻辑：

1. `file_path -> input_file`
2. 从文件或数组读取 trajectory
3. 调用 `MicroEmissionCalculator.calculate(...)`
4. 需要时写出结果文件
5. 若来自 input file，则生成增强版下载 Excel

输出：

- `query_info`
- `summary`
- `results`
- `download_file`

#### 3.3.4 `calculate_macro_emission`

实现：`tools/macro_emission.py`

输入：

- 运行时实际至少需要：
  - `links_data` 或 `file_path`
- 其他可选：
  - `pollutants`
  - `fleet_mix`
  - `default_fleet_mix`
  - `model_year`
  - `season`
  - `output_file`

逻辑：

1. 读取路段数据（表格或 ZIP/Shapefile）
2. 自动修正常见字段名
3. 标准化顶层或 link-level `fleet_mix`
4. 对缺失车队组成的 link 用默认值填补
5. 调用 `MacroEmissionCalculator.calculate(...)`
6. 生成下载文件
7. 若 geometry 可用，构建 `map_data`

输出：

- `query_info`
- `results`
- `summary`
- `fleet_mix_fill`
- `download_file`
- `map_data`

#### 3.3.5 `query_knowledge`

实现：`tools/knowledge.py`

底层 skill：

- `skills/knowledge/skill.py`
- `retriever.py`
- `reranker.py`

输入：

- 必选：`query`
- 可选：`top_k`、`expectation`

逻辑：

1. 检索
2. 重排序
3. LLM refine
4. 拼接 reference list

输出：

- `query`
- `results`
- `answer`
- `sources`

### 3.4 计算引擎技术细节

#### 3.4.1 排放因子查询引擎

位置：`calculators/emission_factors.py`

数据组织：

- 季节切分的 CSV
- 字段：
  - `Speed`
  - `pollutantID`
  - `SourceType`
  - `ModelYear`
  - `EmissionQuant`

实现特点：

1. `vehicle_type -> SourceType ID`
2. `pollutant -> pollutantID`
3. `season -> csv`
4. `Speed` 编码中嵌入了道路类型
5. `return_curve=False` 时保留传统 `g/mile`
6. `return_curve=True` 时转换为 `g/km`

#### 3.4.2 微观排放计算引擎

位置：`calculators/micro_emission.py`

数据组织：

- 季节切分 CSV
- 字段：
  - `opModeID`
  - `pollutantID`
  - `SourceType`
  - `ModelYear`
  - `CalendarYear`
  - `EmissionQuant`

核心流程：

1. 实际年份映射到 MOVES 年龄组
2. `VSPCalculator.calculate_trajectory_vsp(...)`
3. 轨迹点转换成 `vsp / opmode`
4. 查 emission matrix
5. `g/hr -> g/s`
6. 逐秒积分并求总量与单位排放

#### 3.4.3 `VSP` 方法

位置：`calculators/vsp.py`

公式：

```text
VSP = (A*v + B*v^2 + C*v^3 + M*v*a + M*v*g*grade/100) / m
```

实现要点：

- 车型参数来自 `shared/standardizer/constants.py::VSP_PARAMETERS`
- 同时生成：
  - `vsp`
  - `vsp_bin`
  - `opmode`

`opMode` 采用速度段 + VSP 阈值分段：

- idle：`0`
- 低速：`11-16`
- 中速：`21-30`
- 高速：`33-40`

#### 3.4.4 宏观排放计算引擎

位置：`calculators/macro_emission.py`

数据组织：

- 季节切分 CSV
- 无 header，代码中指定列名：
  - `opModeID`
  - `pollutantID`
  - `sourceTypeID`
  - `modelYearID`
  - `em`
  - `extra`

核心假设：

- 固定使用 `LOOKUP_OPMODE = 300`
- 即基于平均工况的 MOVES-Matrix 查询

路段排放核心公式：

```text
emission_rate_g_per_sec = emission_rate / 3600
travel_time_sec = (link_length_km / avg_speed_kph) * 3600
emission_g_per_veh = emission_rate_g_per_sec * travel_time_sec
emission_kg_per_hr = emission_g_per_veh * vehicles_per_hour / 1000
```

并进一步求：

- `total_emissions_kg_per_hr`
- `emission_rates_g_per_veh_km`

#### 3.4.5 车队组成处理

宏观工具中的 `fleet_mix` 会经历三层处理：

1. 名称标准化
2. 顶层 `fleet_mix` 下发到各 link
3. 缺失时用默认车队组成填补

默认组成：

- `Passenger Car`: 70%
- `Passenger Truck`: 20%
- `Light Commercial Truck`: 5%
- `Transit Bus`: 3%
- `Combination Long-haul Truck`: 2%

### 3.5 输入文件格式要求

#### 3.5.1 微观文件

支持：

- `.csv`
- `.xlsx`
- `.xls`

最小要求：

- 至少有一列速度

可选：

- 时间
- 加速度
- 坡度

缺失策略：

- 无时间：自动生成序列
- 无加速度：由速度差估算
- 无坡度：默认 `0`

#### 3.5.2 宏观文件

支持：

- `.csv`
- `.xlsx`
- `.xls`
- `.zip`

ZIP 可包含：

- Shapefile
- Excel / CSV

语义上至少要能识别：

- 路段长度
- 流量
- 平均速度

可选增强字段：

- `link_id`
- `geometry`
- 车型占比列

### 3.6 多工具协作模式的真实语义

这部分在全文中必须统一：

1. 系统可以在同一轮响应里执行多个 `tool_calls`
2. 执行顺序由 router 顺序遍历决定
3. 成功后不会继续自动 re-plan
4. 只有工具失败时，才会把错误回注到上下文后再次调用 LLM

因此当前系统更准确的定义是：

- **router orchestration**

而不是：

- 完整 success-driven planner

### 3.7 工具层与计算层的统一结论

1. `tools/` 是薄封装，`calculators/` 才承载核心数值逻辑
2. Router 与 calculators 通过统一 `ToolResult` 解耦
3. macro 工具比 micro 工具更依赖文件语义映射
4. `query_knowledge` 适合做参数解释与法规 grounding
5. 系统形成了 `EmissionFactors / Micro / Macro / GIS` 四类交付能力

---

## 4. 记忆管理、结果合成与交付

### 4.1 三层记忆管理

三层记忆由 `core/memory.py::MemoryManager` 实现：

1. `Working Memory`
2. `Fact Memory`
3. `Compressed Memory`

#### 4.1.1 Working Memory

数据结构：

- `List[Turn]`
- `Turn` 包含：
  - `user`
  - `assistant`
  - `tool_calls`
  - `timestamp`

容量相关事实：

- `MAX_WORKING_MEMORY_TURNS = 5`
- assembler 注入时默认只取最近 `3` 轮
- 若超预算，则退化为最近 `1` 轮
- assistant 文本会截断到 `300` 字符

#### 4.1.2 Fact Memory

当前主链路有效字段：

- `recent_vehicle`
- `recent_pollutants`
- `recent_year`
- `active_file`
- `file_analysis`
- `last_tool_name`
- `last_tool_summary`
- `last_tool_snapshot`

这些字段主要来自成功的工具调用结果与文件缓存。

#### 4.1.3 Compressed Memory

当前实现只是一个字符串：

- 超过 `10` 轮时触发压缩
- 把旧轮中的 tool_calls 变成：

```text
- Called <tool_name> with <arguments>
```

但必须强调：

- `compressed_memory` 当前不进入 `ContextAssembler` 的 prompt 主链路

因此从 live behavior 看，真正影响后续轮次的是：

- `working_memory`
- `fact_memory`
- `file_context`

而不是完整意义上的三层全参与。

### 4.2 记忆如何影响后续轮次

`ContextAssembler.assemble()` 会通过两种方式注入记忆：

1. **Fact Memory**
   - 作为 system context summary

2. **Working Memory**
   - 作为最近几轮 user/assistant messages

此外，若有上传文件，还会单独注入：

3. **File Context**
   - 文件名、路径、`task_type`、行数、列名、样例行

因此，后续轮次里诸如：

- “换成 NOx”
- “还是刚才那个文件”
- “把年份改成 2020”
- “导出上一轮结果”

能够成立，核心依赖的就是这套轻量记忆结构。

### 4.3 记忆持久化与会话管理

这里需要区分两套持久化机制。

#### 4.3.1 Router memory 持久化

`MemoryManager._save()` 写到：

```text
data/sessions/history/{session_id}.json
```

保存：

- `fact_memory`
- `compressed_memory`
- 最近 `10` 轮 `working_memory`

但不会完整保存历史 `tool_calls`。

#### 4.3.2 UI Session 持久化

`api/session.py::SessionManager` 维护另一套前端会话存储：

- 根目录：`data/sessions/{user_id}/`
- 元数据：`sessions_meta.json`
- 历史消息：`history/{session_id}.json`

`Session.save_turn()` 会保存：

- user message
- assistant response
- `chart_data`
- `table_data`
- `map_data`
- `data_type`
- `file_id`
- `download_file`

这意味着当前系统存在“双轨存储”：

1. router memory
2. UI session history

它们有关联，但不是统一数据源。

### 4.4 `_synthesize_results` 的逻辑

结果合成核心在：

- `core/router.py::_synthesize_results()`
- `core/router_synthesis_utils.py`
- `core/router_render_utils.py`

主流程：

```text
tool_results
  -> maybe_short_circuit_synthesis()
  -> if not short-circuit:
       filter_results_for_synthesis()
       build_synthesis_request()
       llm.chat(...)
       detect_hallucination_keywords()
```

### 4.5 短路合成与确定性渲染

为了降低 latency 与 hallucination，系统会尽量 short-circuit：

1. **单 `query_knowledge` 成功**
   - 直接返回工具 summary

2. **任一工具失败**
   - `format_results_as_fallback()`

3. **单工具成功且属于特定工具**
   - `render_single_tool_success()`
   - 支持：
     - `query_emission_factors`
     - `calculate_micro_emission`
     - `calculate_macro_emission`
     - `analyze_file`

因此，当前系统的大量单工具成功回答是 deterministic rendering，不依赖额外 synthesis LLM。

### 4.6 结构化 payload 如何呈现给用户

`core/router_payload_utils.py` 负责抽取：

- `chart_data`
- `table_data`
- `download_file`
- `map_data`

#### 4.6.1 图表

主要用于 `query_emission_factors`：

- 若工具未直接返回 `chart_data`
- router 会根据 `speed_curve / curve` 动态格式化成前端图表 payload

#### 4.6.2 表格

`extract_table_data()` 会把：

- 排放因子结果
- 微观计算结果
- 宏观计算结果

统一转成：

```python
{
  "type": ...,
  "columns": [...],
  "preview_rows": [...],
  "total_rows": ...,
  "total_columns": ...,
  "summary": {...}
}
```

#### 4.6.3 下载文件

API 层会做：

- `normalize_download_file()`
- `attach_download_to_table_data()`

把下载按钮元数据绑定进表格载荷和历史消息。

#### 4.6.4 GIS 地图

后端来源：

- `tools/macro_emission.py::_build_map_data()`

载荷结构包含：

- `center`
- `color_scale`
- `links`
- `pollutant`
- `unit`

前端通过 `Leaflet` 渲染，并支持：

- GIS basemap
- road network overlay
- pollutant 切换
- emission intensity 颜色更新

### 4.7 API 流式交付与 Web 渲染

`api/routes.py::chat_stream()` 会把结果拆成事件流：

- `status`
- `heartbeat`
- `text`
- `chart`
- `table`
- `map`
- `done`
- `error`

`web/app.js` 对应的核心渲染函数：

- `addAssistantMessage()`
- `renderChart()`
- `renderTable()`
- `renderEmissionMap()`
- `initEmissionChart()`
- `initLeafletMap()`

因此系统交付不是单一文本回答，而是：

- markdown 文本
- ECharts 曲线
- 表格预览 + 下载
- Leaflet GIS 地图

的多模态结果组合。

### 4.8 当前结果交付层的实现边界

需要统一保留以下边界：

1. `extract_*` payload helper 通常返回 first match，不支持复杂多工具多载荷并列展示
2. hallucination keyword 检测只做日志警告，不阻断输出
3. session history 与 router memory 存储分离
4. Web 前端没有自动化 UI 测试

---

## 5. 现有评估体系与回归覆盖

### 5.1 evaluation 框架的整体结构

`evaluation/` 目录目前主要包含：

- `eval_normalization.py`
- `eval_file_grounding.py`
- `eval_end2end.py`
- `eval_ablation.py`
- `run_smoke_suite.py`
- `utils.py`
- benchmark sample sets
- checked-in smoke logs

README 已明确说明：

- 这是当前的本地 benchmark 与 reproducibility harness
- 不是最终 paper package

### 5.2 当前已有的评估维度

从代码结构看，现有评估维度已经包含：

1. **参数标准化**
2. **文件任务锚定 / 列映射**
3. **端到端 grounded execution**
4. **模块消融**

此外还有：

- `evaluation/human_compare/samples.csv`
  - 作为人工流程对比 scaffold

### 5.3 smoke suite 测了什么

最小入口：

- `python evaluation/run_smoke_suite.py`

默认顺序运行：

1. normalization
2. file_grounding
3. end2end（`mode="tool"`）

默认 macro mapping 模式：

- `direct,fuzzy`

意图是避免最小 smoke path 依赖 AI-only macro mapping。

### 5.4 normalization benchmark 的真实含义

`evaluation/eval_normalization.py` 直接测：

- `ToolExecutor._standardize_arguments()`

不是完整工具执行。

当前样本集：

- `evaluation/normalization/samples.jsonl`
- 样本数：`10`

指标：

- `sample_accuracy`
- `field_accuracy`
- `parameter_legal_rate`

checked-in smoke 指标为：

- `sample_accuracy = 0.10`
- `field_accuracy = 0.6786`
- `parameter_legal_rate = 0.20`

这个结果说明：

- 当前标准化系统在 field-level 有一定覆盖
- 但 sample-level exact match 仍明显偏弱

### 5.5 file_grounding benchmark 的真实含义

`evaluation/eval_file_grounding.py` 测的是 subsystem，而不是完整 router LLM routing。

它实际做的事：

1. 调用 `FileAnalyzerTool`
2. 调用 macro / micro ExcelHandler 提取映射
3. 调用 `ContextAssembler.assemble()`
4. 验证 task_type、column mapping、required fields、context injection

当前样本集：

- `evaluation/file_tasks/samples.jsonl`
- 样本数：`10`

指标：

- `routing_accuracy`
- `column_mapping_accuracy`
- `required_field_accuracy`
- `file_context_injection_consistency`

checked-in smoke 指标为：

- `routing_accuracy = 0.90`
- `column_mapping_accuracy = 1.00`
- `required_field_accuracy = 0.80`
- `file_context_injection_consistency = 1.00`

这说明：

1. file-grounding 子系统总体有效
2. 宏观和微观的列映射在当前样本集上较强
3. 但 `required_field` 判断与 `task_type` 仍存在失败样本

一个典型边界是：

- `macro_cn_fleet.csv` 在 checked-in logs 中会出现 `task_type = unknown`
- 但其 macro 列映射仍能成功

### 5.6 end-to-end benchmark 的真实含义

`evaluation/eval_end2end.py` 支持：

1. `mode="tool"`
2. `mode="router"`

当前 smoke suite 默认使用 `tool` 模式。

当前样本集：

- `evaluation/end2end/samples.jsonl`
- 样本数：`10`

指标：

- `tool_call_success_rate`
- `route_accuracy`
- `end2end_completion_rate`
- `average_interaction_turns`
- `skipped_samples`

#### 5.6.1 `tool` 模式的边界

`tool` 模式实际上是：

```python
executor.execute(
    tool_name=sample["expected_tool_name"],
    arguments=sample["tool_arguments"],
    file_path=...
)
```

因此它绕过了：

- LLM 选路
- live router 规划

它更准确地说是在测：

- grounded execution

而不是完整 agent routing。

#### 5.6.2 checked-in smoke 指标

`evaluation/logs/_smoke_end2end/end2end_metrics.json` 显示：

- `tool_call_success_rate = 1.00`
- `route_accuracy = 1.00`
- `end2end_completion_rate = 1.00`
- `average_interaction_turns = 1.00`

这些结果说明当前工具执行链路相对稳定，但不能直接据此宣称 router 选路能力达到 100%。

### 5.7 ablation 框架

`evaluation/eval_ablation.py` 当前定义了 4 组 baseline：

1. `full_system`
2. `no_file_awareness`
3. `no_executor_standardization`
4. `macro_rule_only`

对应可控维度包括：

- `enable_file_analyzer`
- `enable_file_context_injection`
- `enable_executor_standardization`
- `macro_column_mapping_modes`
- `mode`
- `only_task`

checked-in ablation 最有价值的两个信号是：

1. `no_file_awareness`
   - `file_grounding.routing_accuracy = 0.0`
   - `required_field_accuracy = 0.0`

2. `no_executor_standardization`
   - `normalization.sample_accuracy = 0.0`
   - `end2end_completion_rate = 0.4`

但也必须同时说明：

- `no_file_awareness` 下 `tool` 模式的 end2end completion 仍可很高
- 这主要是因为 tool mode 已经把工具名指定死了

### 5.8 tests/ 回归测试覆盖了什么

当前 `tests/` 更偏工程回归，主要覆盖：

1. **Calculators**
   - `tests/test_calculators.py`

2. **Standardizer**
   - `tests/test_standardizer.py`

3. **Router helper contracts**
   - `tests/test_router_contracts.py`

4. **API contracts 与 utilities**
   - `tests/test_api_route_contracts.py`
   - `tests/test_api_chart_utils.py`
   - `tests/test_api_response_utils.py`

5. **Config / Auth**
   - `tests/test_config.py`

6. **Micro Excel reader**
   - `tests/test_micro_excel_handler.py`

7. **Smoke wrapper**
   - `tests/test_smoke_suite.py`

### 5.9 当前回归测试的空白

仍明显缺少：

1. `MemoryManager` 本体的系统性测试
2. `SessionManager` 的一致性与并发测试
3. `query_knowledge` 检索质量测试
4. `router` live LLM loop 的系统测试
5. Web UI 自动化测试
6. GIS 地图链路的集成回归

### 5.10 对现有评估体系的统一判断

当前项目已经具备：

- 工程可复现的 smoke 路径
- 模块级 benchmark
- 初步 ablation 骨架

但它仍然是：

- **engineering benchmark harness**

而不是：

- **paper-ready evaluation package**

---

## 6. 面向论文的实验设计与差距分析

### 6.1 端到端任务完成评估

#### 6.1.1 当前缺口

现有 end2end 默认是 `tool` 模式，不能充分反映：

- router 选路能力
- 多轮澄清能力
- memory 驱动的 follow-up 能力

#### 6.1.2 建议 benchmark 构建

建议构建真正的 task-oriented benchmark，覆盖至少：

1. 排放因子查询
2. 微观轨迹文件计算
3. 宏观路段文件计算
4. 知识检索 + 计算联动
5. 多轮 follow-up 参数修改

每条样本建议标注：

- `user_query`
- `optional_file`
- `gold_tool_sequence`
- `gold_final_parameters`
- `gold_expected_outputs`
- `gold_success_criteria`

#### 6.1.3 推荐指标

- `Task Success Rate`
- `Tool Selection Accuracy`
- `Parameter Match Rate`
- `Output Completeness`
- `Average Turns`
- `Clarification Rate`
- `Latency`

### 6.2 文件驱动任务锚定准确率

#### 6.2.1 当前缺口

当前样本数太小，且数据较干净。

#### 6.2.2 推荐数据集维度

建议按以下维度构建：

1. `micro / macro / ambiguous / unsupported`
2. `Chinese / English / mixed`
3. `exact / fuzzy / semantic paraphrase / noisy`
4. `CSV / XLSX / ZIP / Shapefile`
5. `complete / partial / misleading`

每个文件应人工标注：

- `gold_task_type`
- `gold_required_present`
- `gold_column_mapping`

#### 6.2.3 推荐指标

- `Task Type Accuracy`
- `Macro/Micro F1`
- `Required Field Detection Accuracy`
- `Column Mapping Exact Match`
- `Confidence Calibration`

### 6.3 参数标准化准确率

#### 6.3.1 当前缺口

当前标准化 benchmark：

- 规模小
- 字段覆盖有限
- 与 live code 覆盖面并不完全一致

#### 6.3.2 ground truth 应如何构造

建议构造四类数据：

1. vehicle aliases
2. pollutant aliases
3. season / road type expressions
4. difficult negatives

每条样本应包含：

- `raw_expression`
- `gold_standard`
- `legal/illegal`
- `should_abstain`

#### 6.3.3 推荐指标

- `Exact Match Accuracy`
- `Top-k Suggestion Recall`
- `Legality Rate`
- `Abstention Accuracy`
- `Latency`
- `Cost`

### 6.4 消融实验建议

建议扩展为如下完整矩阵：

1. `Full System`
2. `- FileAnalyzer`
3. `- FileContextInjection`
4. `- ExecutorStandardization`
5. `- FactMemory`
6. `- WorkingMemory`
7. `- KnowledgeTool`
8. `- Deterministic short-circuit synthesis`

必须在：

- `router` 模式
- 端到端 benchmark

下执行，否则对 routing / memory 的消融不敏感。

### 6.5 Baseline 对比建议

至少建议对比 4 类 baseline。

#### 6.5.1 Direct LLM

- 无专门 router
- 无执行侧标准化
- 无文件预分析

#### 6.5.2 Manual pipeline

- 人工看文件
- 人工判断 micro / macro
- 人工补齐标准参数
- 再调用工具

#### 6.5.3 Tool-only system

- 保留 calculators 与 tools
- 去掉 file grounding、standardization、memory

#### 6.5.4 Generic tool-calling agent

- 使用通用 tool-calling 策略
- 不引入专门的 file grounding 和 execution-side standardization 设计

### 6.6 交互负担评估

这是非常适合本文系统的实验亮点。

推荐指标：

- `Average Interaction Turns`
- `Clarification Turns`
- `Manual Parameter Mentions`
- `Time to First Valid Result`
- `Time to Final Downloadable Result`

推荐 paired study：

- 条件 A：Emission Agent
- 条件 B：Direct LLM / manual pipeline

### 6.7 4B vs 云端模型对比

建议比较：

1. 本地轻量标准化模型
2. 云端标准化模型
3. 规则 / fuzzy baseline

指标：

- `Exact Match Accuracy`
- `Legality Rate`
- `Abstention Quality`
- `Latency (p50 / p95)`
- `成本`
- `离线可用性`

### 6.8 Case Study 选择建议

最推荐的 4 个案例：

1. **中文路段 + 车型构成文件**
   - `evaluation/file_tasks/data/macro_cn_fleet.csv`
   - 展示 file grounding 边界与价值

2. **非标准英文列名宏观文件**
   - `evaluation/file_tasks/data/macro_fuzzy.csv`
   - 展示 `direct + ai + fuzzy` 语义映射

3. **几何路网文件 + GIS map**
   - `test_data/test_6links.xlsx`
   - 展示排放计算与 GIS 交付一体化

4. **多轮 follow-up 修改参数**
   - 展示 memory 与 cross-turn grounding

### 6.9 对论文实验准备的统一判断

如果要形成 SCI 论文的实验部分，当前最缺的不是代码功能，而是：

1. 更大规模 benchmark
2. 真正 router-mode 的端到端实验
3. 人工或半人工交互负担评估
4. 本地模型 vs 云端模型对比
5. 更系统的 failure analysis

---

## 7. 系统局限性与未来工作

### 7.1 记忆系统局限

1. `compressed_memory` 尚未进入 prompt 主链路
2. working memory 恢复时不保留完整 `tool_calls`
3. correction detection 仅是轻量 heuristic
4. `user_preferences` 尚未接通

### 7.2 会话与持久化局限

1. router memory 与 UI session history 双轨存储
2. `SessionManager` 按 `user_id`，`MemoryManager` 仅按 `session_id`
3. 两套存储模型未完全统一

### 7.3 多工具协作局限

1. 系统支持一次性多工具执行
2. 但 success 后不会继续 re-plan
3. 因此不是完整 planner

### 7.4 标准化与 grounding 局限

1. 执行侧标准化直接覆盖范围有限
2. file analyzer 任务识别以列名 heuristic 为主
3. micro file mapping 仍以 alias matching 为主
4. 本地标准化模型仍是部分接入

### 7.5 合成与交付局限

1. payload helper 多为 first-match 策略
2. hallucination check 只是警告
3. synthesis 看到的是压缩结果，不是完整上下文

### 7.6 评估体系局限

1. benchmark 样本规模太小
2. end2end 默认 `tool` 模式，对 routing 不敏感
3. 缺少真实用户研究
4. 缺少系统性的 latency / cost / robustness 报告
5. `human_compare` 仍只是 scaffold

### 7.7 Web 与部署局限

1. 前端依赖 CDN：
   - Tailwind
   - ECharts
   - Leaflet
2. 没有自动化前端测试
3. GIS basemap / roadnetwork 提升了复现复杂度
4. guest mode 的“非持久化”更接近前端语义，不是严格服务端无状态

### 7.8 未来工作方向

1. 把 `compressed_memory` 真正接入 assembler
2. 统一 session history 与 router memory 存储
3. 引入 success-driven multi-tool replanning
4. 扩展标准化对象到 `season / road_type / year expression`
5. 为 micro file 引入真正 semantic column grounding
6. 扩大 benchmark 与 human study
7. 系统评估本地与云端标准化 trade-off
8. 增强 uncertainty handling 与 failure recovery

---

## 8. 论文写作行动清单

### 8.1 Introduction 需要润色的要点

1. **明确问题缺口**
   - 通用 LLM agent 虽然能调用工具，但在排放分析场景下面临文件理解、参数标准化、计算可执行性和多轮任务连续性不足的问题。

2. **突出场景特殊性**
   - 机动车排放分析不是纯问答，而是“文件 + 参数 + 计算模型 + 可视化交付”的复合工作流。

3. **凸显方法贡献**
   - 文件驱动任务锚定
   - 执行侧参数标准化
   - 双尺度排放计算与 GIS 交付
   - 轻量记忆驱动多轮跟进

4. **强调用户价值**
   - 降低用户解释文件列名和手工整理参数的负担
   - 缩短从上传文件到可下载/可视化结果的路径

5. **把系统定位清楚**
   - 不是通用工作流引擎
   - 而是面向排放分析的 LLM-native domain agent

### 8.2 论文各章节需要准备的素材

#### 8.2.1 Abstract / Introduction

需要素材：

- 应用场景图
- 真实用户任务示例
- 通用 LLM / 手工流程痛点
- 系统贡献点摘要

#### 8.2.2 Related Work

需要素材：

- tool-using LLM agents
- file-grounded agents / structured grounding
- schema grounding / parameter normalization
- traffic emission modeling / MOVES-based systems
- lightweight local model / LoRA standardization

#### 8.2.3 Method

需要素材：

- 总体架构图
- 请求生命周期时序图
- `UnifiedRouter` 决策流程图
- file grounding 流程图
- execution-side standardization 流程图
- memory 结构图
- tool -> calculator 映射表

#### 8.2.4 System Implementation

需要素材：

- `TOOL_DEFINITIONS` 示例
- `ToolExecutor` 标准化代码路径
- `FileAnalyzerTool` 输出字段表
- calculators 的数据格式与核心公式
- Web 端 chart/table/map 截图

#### 8.2.5 Experiments

需要素材：

- benchmark 数据集统计表
- baseline 对比表
- ablation 表
- latency / cost 表
- router-mode 与 tool-mode 对比
- 4B vs cloud 对比表

#### 8.2.6 Case Study

需要素材：

- `macro_cn_fleet.csv`
- `macro_fuzzy.csv`
- `test_6links.xlsx`
- 多轮 follow-up 会话截图与日志

#### 8.2.7 Limitations

需要素材：

- compressed memory 未接通
- partial local-model integration
- tool-mode benchmark 边界
- 双轨存储
- 非完整 planner

### 8.3 必须完成的实验列表（按优先级排序）

#### P0：必须先完成

1. **构建更大规模的端到端 benchmark**
   - 至少覆盖 query / micro / macro / knowledge-assisted / multi-turn 5 类任务
   - 必须包含 `router` 模式

2. **扩展 file grounding benchmark**
   - 增加中文、模糊列名、噪声列、ZIP/Shapefile、unsupported files
   - 输出 confusion matrix

3. **扩展 normalization benchmark**
   - vehicle / pollutant / season / road_type / difficult negatives
   - 明确 ground truth 和 abstention 标注

4. **完成核心 ablation**
   - `full`
   - `- file analyzer`
   - `- file context injection`
   - `- executor standardization`
   - `- memory`

#### P1：强烈建议完成

5. **做 direct LLM / manual pipeline baseline 对比**
   - 对比 task success、turns、time、error rate

6. **做交互负担评估**
   - 平均轮次
   - 澄清轮次
   - 到首次有效结果时间
   - 到最终可下载结果时间

7. **做 4B/3B 本地模型 vs 云端标准化对比**
   - 准确率
   - 合法率
   - 延迟
   - 成本

8. **补 latency / cost / robustness 统计**
   - p50 / p95 latency
   - 大文件 / noisy file / missing field 稳健性

#### P2：用于增强论文说服力

9. **做 case study 与 failure analysis**
   - 成功案例
   - 失败案例
   - 恢复型失败与不可恢复失败分类

10. **补用户研究或半人工比较**
   - 至少形成 human-in-the-loop 对照表

### 8.4 建议的论文投稿目标

建议按论文定位分两条路线选择。

#### 8.4.1 若强调交通与环境应用

优先考虑：

1. `Transportation Research Part D: Transport and Environment`
2. `Atmospheric Environment`
3. `Sustainable Cities and Society`
4. `Journal of Cleaner Production`

适合强调：

- 排放建模应用价值
- 实际交通文件处理
- GIS 排放空间交付
- 环境决策支持

#### 8.4.2 若强调智能系统与交通 AI

优先考虑：

1. `IEEE Transactions on Intelligent Transportation Systems`
2. `Expert Systems with Applications`
3. `Knowledge-Based Systems`

适合强调：

- LLM-native agent architecture
- file grounding
- execution-side standardization
- memory-aware multi-turn interaction

#### 8.4.3 综合建议

如果你的论文最终更偏：

- **排放分析与交通环境应用**：优先投 `TR Part D`
- **智能系统方法论与 agent 设计**：优先投 `IEEE TITS` 或 `Expert Systems with Applications`

从当前代码基础看，最自然的投稿叙事是：

- **“面向机动车排放分析的文件驱动、参数标准化增强型 LLM Agent 系统”**

这样既能保留环境与交通场景特色，也能突出方法创新。
