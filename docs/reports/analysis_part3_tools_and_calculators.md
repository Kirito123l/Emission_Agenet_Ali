# Emission Agent 深度技术分析（第 3 部分）

本文档聚焦 `tools/` 与 `calculators/` 两层，分析 Emission Agent 如何把 LLM 的 `tool_call` 转换为可执行的排放计算，并进一步拆解 `MOVES` 风格数据查询、`VSP` 微观计算和路段级宏观计算的实现细节。

---

## 1. 工具注册与分发机制

### 1.1 工具如何注册到系统中

系统的工具注册中心是 [`tools/registry.py`](tools/registry.py) 中的 `ToolRegistry` 单例。其核心机制如下：

1. `ToolRegistry` 维护 `_tools: Dict[str, BaseTool]`。
2. `init_tools()` 在启动时实例化并注册各工具：
   - `EmissionFactorsTool` -> `query_emission_factors`
   - `MicroEmissionTool` -> `calculate_micro_emission`
   - `MacroEmissionTool` -> `calculate_macro_emission`
   - `FileAnalyzerTool` -> `analyze_file`
   - `KnowledgeTool` -> `query_knowledge`
3. CLI 路径中，[`main.py`](main.py) 会显式调用 `init_tools()`。
4. API/Router 路径中，[`core/executor.py`](core/executor.py) 的 `ToolExecutor.__init__()` 会在 registry 为空时懒加载调用 `init_tools()`。

因此，系统既支持显式启动注册，也支持执行时 lazy initialization。

### 1.2 LLM function calling 的工具定义格式

所有工具的 schema 都定义在 [`tools/definitions.py`](tools/definitions.py) 的 `TOOL_DEFINITIONS` 中，采用 OpenAI function calling 兼容格式：

```json
{
  "type": "function",
  "function": {
    "name": "calculate_macro_emission",
    "description": "...",
    "parameters": {
      "type": "object",
      "properties": { ... },
      "required": [ ... ]
    }
  }
}
```

这些定义并不直接绑定 Python 函数签名，而是作为 LLM 的可调用工具目录。运行时的绑定关系由 `ToolRegistry` 完成。

相关装配链路如下：

1. [`services/config_loader.py`](services/config_loader.py) 的 `ConfigLoader.load_tool_definitions()` 返回 `TOOL_DEFINITIONS`。
2. [`core/assembler.py`](core/assembler.py) 的 `ContextAssembler.__init__()` 读取这些工具定义。
3. [`core/router.py`](core/router.py) 的 `UnifiedRouter.chat()` 调用 `self.llm.chat_with_tools(messages, tools, system)`。
4. [`services/llm_client.py`](services/llm_client.py) 的 `LLMClientService.chat_with_tools()` 把 `tools=` 传给 OpenAI-compatible SDK，并固定 `tool_choice="auto"`，即由模型决定是否调用工具。

### 1.3 从 LLM 输出的 `tool_call` 到实际执行的决策流

核心调用链如下：

```text
ContextAssembler.assemble()
  -> UnifiedRouter.chat()
  -> LLMClientService.chat_with_tools()
  -> LLMResponse(tool_calls=[ToolCall(...)])
  -> UnifiedRouter._process_response()
  -> ToolExecutor.execute(tool_name, arguments, file_path)
  -> ToolRegistry.get(tool_name)
  -> ToolExecutor._standardize_arguments()
  -> tool.execute(**standardized_args)
  -> Router synthesis / payload extraction
```

更精确地说：

1. `UnifiedRouter.chat()` 先组织 prompt、历史上下文和工具列表。
2. `LLMClientService.chat_with_tools()` 返回 `LLMResponse`，其中 `tool_calls` 被解析为 `ToolCall(id, name, arguments)`。
3. `UnifiedRouter._process_response()` 遍历 `response.tool_calls`。
4. 每个 `tool_call` 都交给 `ToolExecutor.execute()`：
   - 从 registry 按名字取到具体工具实例。
   - 对 `vehicle_type`、`pollutant`、`pollutants` 做执行侧标准化。
   - 如有上传文件且参数中未显式带 `file_path`，自动注入 `file_path`。
   - `await tool.execute(**standardized_args)`。
5. 工具统一返回 `ToolResult`，随后被 `ToolExecutor` 转换成 dict。
6. `UnifiedRouter` 再做两件事：
   - `self._synthesize_results(...)` 生成自然语言回答。
   - `core/router_payload_utils.py` 从工具结果中抽取 `chart_data`、`table_data`、`map_data`、`download_file`。

### 1.4 工具结果的统一数据结构

所有工具都继承 [`tools/base.py`](tools/base.py) 的 `BaseTool`，并返回 `ToolResult`：

```python
ToolResult(
    success: bool,
    data: Optional[Dict[str, Any]],
    error: Optional[str],
    summary: Optional[str],
    chart_data: Optional[Dict],
    table_data: Optional[Dict],
    download_file: Optional[str],
    map_data: Optional[Dict[str, Any]]
)
```

这里有一个实现细节值得写入论文说明：

- 类型注解里 `download_file` 是 `Optional[str]`。
- 但实际运行中多个工具返回的是 `{"path": ..., "filename": ...}` 形式的 dict。
- [`core/router_payload_utils.py`](core/router_payload_utils.py) 已经兼容了这两种格式。

也就是说，系统的“规范接口”和“实际前端协议”之间存在一个轻微的 runtime 扩展层。

### 1.5 多工具协作的真实执行语义

当前系统支持一个 LLM 响应中包含多个 `tool_calls`，并在 [`core/router.py`](core/router.py) 中按顺序执行它们。但实现上有一个很关键的边界：

- 系统会执行同一轮响应里已经给出的全部 `tool_calls`。
- 成功执行后，不会基于第一个工具结果继续再次询问 LLM 规划下一个工具。
- 只有在工具失败时，`UnifiedRouter._process_response()` 才会把错误结果塞回对话上下文，再次调用 `chat_with_tools()` 进行 retry。

因此，当前架构是“单轮一次性 tool selection + 顺序执行 + 结果综合”，而不是严格意义上的 success-driven multi-step planner。

这一点对于后面分析 `query_knowledge -> calculate_*` 的协作模式非常关键。

---

## 2. 各工具详解

### 2.1 工具总览

| 工具名 | Python 类 | 主要职责 | 主要依赖 |
|---|---|---|---|
| `analyze_file` | `tools.file_analyzer.FileAnalyzerTool` | 文件结构识别、任务类型判断 | `services.standardizer` |
| `query_emission_factors` | `tools.emission_factors.EmissionFactorsTool` | 查询速度-排放因子曲线 | `calculators.emission_factors.EmissionFactorCalculator` |
| `calculate_micro_emission` | `tools.micro_emission.MicroEmissionTool` | 秒级轨迹排放计算 | `calculators.micro_emission.MicroEmissionCalculator` + `skills.micro_emission.excel_handler.ExcelHandler` |
| `calculate_macro_emission` | `tools.macro_emission.MacroEmissionTool` | 路段级宏观排放计算 | `calculators.macro_emission.MacroEmissionCalculator` + `skills.macro_emission.excel_handler.ExcelHandler` |
| `query_knowledge` | `tools.knowledge.KnowledgeTool` | 知识库 / RAG 检索 | `skills.knowledge.skill.KnowledgeSkill` |

下面逐个展开。

### 2.2 `analyze_file`

**定义位置**

- schema: [`tools/definitions.py`](tools/definitions.py)
- 实现: [`tools/file_analyzer.py`](tools/file_analyzer.py)

**输入参数**

- 必选：
  - `file_path: str`
- 可选：
  - 无显式业务参数，`**kwargs` 不参与主逻辑

**核心处理逻辑**

`FileAnalyzerTool.execute(file_path, **kwargs)` 的处理分三类：

1. 普通表格文件：`.csv` / `.xlsx` / `.xls`
   - 读取为 `DataFrame`
   - 清洗列名
   - 调用 `_analyze_structure(df, filename)`
2. `.zip`
   - 调用 `_analyze_zip_file()`
   - 若 ZIP 中含 `.shp`，走 `_analyze_shapefile_zip()`
   - 若 ZIP 中含表格，走 `_analyze_tabular_zip()`
3. 不支持的后缀直接报错

`_analyze_structure()` 会输出：

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

其中任务类型识别由 `_identify_task_type(columns)` 完成，采用启发式关键词计分：

- `micro_emission` 指示词：`speed`、`velocity`、`速度`、`time`、`acceleration`、`加速`
- `macro_emission` 指示词：`length`、`flow`、`volume`、`traffic`、`长度`、`流量`、`link`

Shapefile 特殊路径会输出：

- `geometry_types`
- `bounds`
- `sample_data`
- 并强制给出 `task_type = "macro_emission"`

**输出格式**

返回 `ToolResult(success=True, data=analysis, summary=summary)`，其中 `data` 是结构化文件分析结果。

**与其他工具的协作关系**

- 它既可以被 LLM 显式调用，也会被 [`core/router.py`](core/router.py) 的 `UnifiedRouter._analyze_file()` 在有上传文件时隐式调用。
- 其输出会被写入 `MemoryManager`，并由 `ContextAssembler` 注入 prompt。
- 它本身不做计算，但决定后续更可能进入 `calculate_micro_emission` 或 `calculate_macro_emission`。

### 2.3 `query_emission_factors`

**定义位置**

- schema: [`tools/definitions.py`](tools/definitions.py)
- 实现: [`tools/emission_factors.py`](tools/emission_factors.py)
- 引擎: [`calculators/emission_factors.py`](calculators/emission_factors.py)

**输入参数**

schema 定义中：

- 必选：
  - `vehicle_type: str`
  - `model_year: int`
- 可选：
  - `pollutants: List[str]`
  - `season: str`
  - `road_type: str`
  - `return_curve: bool`

运行时 `execute()` 还兼容单个 `pollutant` 参数：

- `pollutant: str`
- `pollutants: List[str]`

如果两者都没有，则报错。

**核心处理逻辑**

`EmissionFactorsTool.execute()` 的主流程：

1. 读取 `vehicle_type`、`model_year`、`season`、`road_type`、`return_curve`
2. 规范化污染物输入为 `pollutants_list`
3. 对每个 pollutant 调用 `EmissionFactorCalculator.query(...)`
4. 若任一 pollutant 查询失败，直接返回失败结果
5. 按“单污染物/多污染物”两种模式组织输出
6. 单污染物且存在 `speed_curve` 时，会额外生成 Excel 下载文件

**输出格式**

单污染物时，`data` 典型形态为：

```python
{
  "query_summary": {...},
  "speed_curve": [...],
  "typical_values": [...],
  "speed_range": {...},
  "data_points": int,
  "unit": "g/mile",
  "data_source": "MOVES (Atlanta)"
}
```

多污染物时，`data` 形态为：

```python
{
  "vehicle_type": ...,
  "model_year": ...,
  "pollutants": {
    "CO2": {...},
    "NOx": {...}
  },
  "metadata": {
    "season": ...,
    "road_type": ...
  }
}
```

**与其他工具的协作关系**

- 参数中的 `vehicle_type`、`pollutant(s)` 通常先经过 `ToolExecutor._standardize_arguments()`。
- 工具本身通常不直接填 `chart_data` / `table_data`，而是由 [`core/router_payload_utils.py`](core/router_payload_utils.py) 从 `data` 中二次抽取成前端图表和表格。
- 可与 `query_knowledge` 协作，用于先确认污染物定义、法规要求，再查询排放因子。

### 2.4 `calculate_micro_emission`

**定义位置**

- schema: [`tools/definitions.py`](tools/definitions.py)
- 实现: [`tools/micro_emission.py`](tools/micro_emission.py)
- 引擎: [`calculators/micro_emission.py`](calculators/micro_emission.py)
- 文件 I/O: [`skills/micro_emission/excel_handler.py`](skills/micro_emission/excel_handler.py)

**输入参数**

schema 定义中：

- 必选：
  - `vehicle_type: str`
- 可选：
  - `file_path: str`
  - `trajectory_data: List[Dict]`
  - `pollutants: List[str]`
  - `model_year: int`
  - `season: str`

运行时还兼容：

- `input_file`
- `output_file`

并且 `file_path` 会被自动映射成 `input_file`。

**核心处理逻辑**

`MicroEmissionTool.execute()` 的主流程如下：

```text
1. file_path -> input_file
2. 校验 vehicle_type
3. 如果有 input_file:
     ExcelHandler.read_trajectory_from_excel()
   否则使用 trajectory_data
4. 校验 trajectory_data 非空
5. 调用 MicroEmissionCalculator.calculate(...)
6. 如指定 output_file，写出结果文件
7. 如来自 input_file，再生成增强版下载 Excel
8. 组织 summary 并返回 ToolResult
```

有两个实现细节值得注意：

1. `MicroEmissionTool` 会尝试给 `ExcelHandler` 注入 `llm_client`，日志中称“Intelligent column mapping enabled”。
2. 但当前 [`skills/micro_emission/excel_handler.py`](skills/micro_emission/excel_handler.py) 实际读取逻辑仍主要依赖固定 alias 列表匹配，并没有真正调用 LLM 做列语义映射。

因此，微观文件输入目前是“规则别名驱动”，而不是宏观工具那种 `direct + ai + fuzzy` 混合列映射。

**输出格式**

`data` 结构为：

```python
{
  "query_info": {
    "vehicle_type": ...,
    "pollutants": [...],
    "model_year": ...,
    "season": ...,
    "trajectory_points": ...
  },
  "summary": {
    "total_distance_km": ...,
    "total_time_s": ...,
    "total_emissions_g": {...},
    "emission_rates_g_per_km": {...}
  },
  "results": [
    {
      "t": ...,
      "speed_kph": ...,
      "speed_mph": ...,
      "vsp": ...,
      "opmode": ...,
      "emissions": {...}
    }
  ],
  "download_file": {...}   # 若生成
}
```

**与其他工具的协作关系**

- 常见前置工具是 `analyze_file`，用于识别上传文件是否更适合微观计算。
- 计算结果会被 `router_payload_utils.extract_table_data()` 转成前端预览表。
- 如果用户不确定 `vehicle_type` 或污染物名称，可先通过 `query_knowledge` 或执行侧标准化辅助完成参数确认。

### 2.5 `calculate_macro_emission`

**定义位置**

- schema: [`tools/definitions.py`](tools/definitions.py)
- 实现: [`tools/macro_emission.py`](tools/macro_emission.py)
- 引擎: [`calculators/macro_emission.py`](calculators/macro_emission.py)
- 文件 I/O: [`skills/macro_emission/excel_handler.py`](skills/macro_emission/excel_handler.py)

**输入参数**

schema 定义中没有强制 required 字段，但运行时实际上需要：

- `links_data` 或 `file_path`

其他可选参数：

- `pollutants: List[str]`
- `fleet_mix: Dict`
- `model_year: int`
- `season: str`

运行时还兼容：

- `default_fleet_mix`
- `input_file`
- `output_file`

**核心处理逻辑**

`MacroEmissionTool.execute()` 是所有工具中最复杂的一个，流程如下：

```text
1. file_path -> input_file
2. 从 input_file 或 links_data 获取路段数据
   - .zip: 可能是 Shapefile，也可能是 Excel/CSV
   - 表格: ExcelHandler.read_links_from_excel()
3. _fix_common_errors():
   - 自动修正常见字段名
   - 把 fleet_mix 的 array 形式改写为 object
   - 自动生成缺失 link_id
   - 保留 geometry
4. _apply_global_fleet_mix():
   - 将顶层 fleet_mix 下发到每个 link
   - 并对车队名称做标准化
5. _fill_missing_link_fleet_mix():
   - 对缺失车队组成的路段用 default_fleet_mix 回填
6. 调用 MacroEmissionCalculator.calculate(...)
7. 若有 input_file，则生成带排放列的下载 Excel
8. _build_map_data():
   - 从 geometry 解析 LineString / GeoJSON / 坐标数组 / 坐标串
   - 构造 map_data
9. 返回 ToolResult
```

**输出格式**

`data` 典型结构为：

```python
{
  "query_info": {
    "model_year": ...,
    "pollutants": [...],
    "season": ...,
    "links_count": ...
  },
  "results": [
    {
      "link_id": ...,
      "link_length_km": ...,
      "traffic_flow_vph": ...,
      "avg_speed_kph": ...,
      "fleet_composition": {...},
      "emissions_by_vehicle": {...},
      "total_emissions_kg_per_hr": {...},
      "emission_rates_g_per_veh_km": {...}
    }
  ],
  "summary": {
    "total_links": ...,
    "total_emissions_kg_per_hr": {...}
  },
  "fleet_mix_fill": {
    "strategy": "default_fleet_mix",
    "filled_count": ...,
    "filled_link_ids": [...],
    "filled_row_indices": [...],
    "default_fleet_mix_used": {...}
  },
  "download_file": {...}   # 若生成
}
```

此外 `ToolResult.map_data` 可能携带地图可视化对象：

```python
{
  "type": "macro_emission_map",
  "center": [lon, lat],
  "pollutant": "...",
  "unit": "kg/(h·km)",
  "links": [...]
}
```

**与其他工具的协作关系**

- 最常见的前置工具是 `analyze_file`。
- `fleet_mix` 里的车型名会继续借助 `services.standardizer` 标准化。
- 结果可以被 router 自动抽取为 `table_data`、`map_data`、`download_file`。
- 与 `query_knowledge` 的典型协作场景是：先确认某种宏观排放方法、污染物口径或法规含义，再执行计算。

### 2.6 `query_knowledge`

**定义位置**

- schema: [`tools/definitions.py`](tools/definitions.py)
- 工具包装: [`tools/knowledge.py`](tools/knowledge.py)
- 实际 skill: [`skills/knowledge/skill.py`](skills/knowledge/skill.py)
- 检索器: [`skills/knowledge/retriever.py`](skills/knowledge/retriever.py)
- 重排序: [`skills/knowledge/reranker.py`](skills/knowledge/reranker.py)

**输入参数**

- 必选：
  - `query: str`
- 可选：
  - `top_k: int`
  - `expectation: str`

**核心处理逻辑**

`KnowledgeTool.execute()` 本身只是一个薄包装，真正流程在 `KnowledgeSkill.execute()` 中：

```text
1. KnowledgeRetriever.search(query, top_k)
2. KnowledgeReranker.rerank(query, results, top_n=top_k)
3. _refine_answer(query, reranked_results, expectation)
4. 提取、去重来源
5. 用 Python 代码把 “参考文档” 附加到答案末尾
```

其中：

- `KnowledgeRetriever`
  - 支持 `local` 的 `BGE-M3` embedding
  - 也支持 `api` embedding
  - 底层使用 `FAISS`
- `KnowledgeReranker`
  - 支持 `api` rerank
  - 或 `local` 关键词重排序
  - local 模式下采用 `0.6 * original_score + 0.4 * keyword_score`

因此，`query_knowledge` 并不是简单 FAQ，而是完整的 `retrieval -> rerank -> LLM refinement` 管线。

**输出格式**

`KnowledgeTool` 返回：

```python
{
  "query": ...,
  "results": [...],
  "answer": "...",
  "sources": [...]
}
```

并且 `summary = answer`，即 synthesis 阶段会直接使用完整答案而不是摘要。

**与其他工具的协作关系**

- 适合用来确认排放标准、术语、法规背景和参数含义。
- 当前架构下，它更适合作为“前置澄清工具”或“跨轮对话辅助工具”，而不是严格的单轮链式前置步骤。
- 也就是说，推荐模式通常是：
  - 第 1 轮：`query_knowledge`
  - 第 2 轮：用户确认后再 `calculate_*`

---

## 3. 计算引擎技术细节

### 3.1 排放因子查询引擎：`calculators/emission_factors.py`

#### 3.1.1 MOVES 数据组织方式

排放因子数据库放在 [`calculators/data/emission_factors/`](calculators/data/emission_factors) 下，按季节切成 3 个 CSV：

- `atlanta_2025_1_55_65.csv`
- `atlanta_2025_4_75_65.csv`
- `atlanta_2025_7_90_70.csv`

字段结构为：

```text
Speed, pollutantID, SourceType, ModelYear, EmissionQuant
```

其组织逻辑是：

- `SourceType` 表示 MOVES 车型 ID
- `pollutantID` 表示污染物 ID
- `ModelYear` 是实际车型年份
- `EmissionQuant` 为速度对应的排放因子
- `Speed` 不是单纯速度，而是嵌入了道路类型编码的复合字段

#### 3.1.2 查询逻辑

`EmissionFactorCalculator.query()` 的逻辑：

1. `vehicle_type -> SourceType ID`
2. `pollutant -> pollutantID`
3. `season -> csv_file`
4. 读取季节文件
5. 先按 `SourceType + pollutantID + ModelYear` 过滤
6. 再解析 `Speed` 编码拆出：
   - `speed_value`（mph）
   - `road_type_in_data`
7. 仅保留道路类型匹配的数据
8. 按速度排序后返回

关键编码约定：

- 例如 `504` 表示 `5 mph + road type 4`
- 例如 `1005` 表示 `10 mph + road type 5`

道路类型映射由 `ROAD_TYPE_MAPPING` 控制，当前主要归并到两类：

- `4`: `快速路`
- `5`: `地面道路`

#### 3.1.3 返回形式与单位

引擎有两种输出：

1. `return_curve=False`
   - 返回 `speed_curve`
   - 单位保留为 `g/mile`
   - 附带 `typical_values`
2. `return_curve=True`
   - 返回 `curve`
   - 单位转换为 `g/km`

这说明该引擎兼顾了：

- 面向用户展示的传统曲线查询
- 面向前端图表的标准化数值输出

#### 3.1.4 论文视角下的技术特点

- 数据查询不是 SQL/数据库服务，而是本地 CSV slicing + ID lookup。
- 车型与污染物暴露给上层的是“受控映射子集”，并非底层 CSV 中出现的全部 pollutantID。
- 道路类型不是一个独立列，而是编码在 `Speed` 中，这一点对论文描述很重要。

### 3.2 微观排放计算引擎：`calculators/micro_emission.py`

#### 3.2.1 数据组织方式

微观计算数据位于 [`calculators/data/micro_emission/`](calculators/data/micro_emission) 下，也按季节分 3 个 CSV。字段结构为：

```text
opModeID, pollutantID, SourceType, ModelYear, CalendarYear, EmissionQuant
```

这里的 `ModelYear` 不是实际年份，而是 MOVES 年龄组编码。

#### 3.2.2 年份到年龄组的转换

`MicroEmissionCalculator._year_to_age_group(model_year)` 把真实年份转换为 MOVES 年龄组：

- `1`: 0-1 年
- `2`: 2-9 年
- `5`: 10-19 年
- `9`: 20+ 年

代码注释明确指出：

- 数据中没有年龄组 `3`
- 因此直接跳过该组

也就是说，微观引擎的年份处理逻辑与宏观引擎不同：微观先压缩到年龄组，再检索矩阵。

#### 3.2.3 VSP 方法实现

`VSP` 实现位于 [`calculators/vsp.py`](calculators/vsp.py)，参数来自 [`shared/standardizer/constants.py`](shared/standardizer/constants.py) 的 `VSP_PARAMETERS`。

公式为：

```text
VSP = (A*v + B*v^2 + C*v^3 + M*v*a + M*v*g*grade/100) / m
```

其中：

- `v`: 速度，单位 `m/s`
- `a`: 加速度，单位 `m/s^2`
- `grade`: 坡度百分比
- `A/B/C/M/m`: 车型参数

`VSPCalculator.calculate_trajectory_vsp()` 的实现要点：

1. 把 `speed_kph` 转换成 `speed_mps` 与 `speed_mph`
2. 若输入缺少加速度，则由相邻时刻速度差自动计算
3. 若缺少坡度，默认 `0`
4. 计算 `vsp`
5. 同时计算：
   - `vsp_bin`
   - `opmode`

需要注意：

- 最终排放率查询实际使用的是 `opmode`
- `vsp_bin` 会被保存在结果里，但不直接参与 emission lookup

#### 3.2.4 `opMode` 分类逻辑

`VSPCalculator.vsp_to_opmode(speed_mph, vsp)` 采用分段规则：

- `speed < 1 mph` -> `opMode 0`（idle）
- `1-25 mph` -> `11-16`
- `25-50 mph` -> `21-30`
- `>50 mph` -> `33-40`

不同速度段再按 `vsp` 阈值切分。

这体现了典型的 MOVES “速度段 + VSP 区间” 双维离散化思路。

#### 3.2.5 微观排放率查询与总量计算

核心逻辑在 `MicroEmissionCalculator.calculate()` 中：

```text
for point in trajectory_with_vsp:
    for pollutant in pollutants:
        emission_rate = _query_emission_rate(matrix, opmode, pollutant_id, source_type_id, model_year)
        emissions[pollutant] = emission_rate / 3600
```

也就是：

- 底层矩阵 `EmissionQuant` 单位是 `g/hr`
- 计算结果换算为逐秒累积使用的 `g/s`

`_query_emission_rate()` 的查询策略：

1. 先按 `opmode + pollutantID + sourceType + age_group` 精确查询
2. 若没有匹配项，回退到 `opModeID = 300`
3. 仍无数据则返回 `0.0`

总结统计 `_calculate_summary()` 包括：

- 总距离：`speed_kph * dt / 3600`
- 总时间：结果条数
- 总排放：对每秒排放求和
- 单位排放：`total_emission / total_distance_km`

### 3.3 宏观排放计算引擎：`calculators/macro_emission.py`

#### 3.3.1 数据组织方式

宏观引擎使用 [`calculators/data/macro_emission/`](calculators/data/macro_emission) 下的季节矩阵文件：

- `atlanta_2025_1_35_60 .csv`
- `atlanta_2025_4_75_65.csv`
- `atlanta_2025_7_80_60.csv`

与前两个引擎不同，这里的 CSV 是无 header 的，读取时由代码指定列名：

```text
opModeID, pollutantID, sourceTypeID, modelYearID, em, extra
```

实现里固定采用：

- `LOOKUP_OPMODE = 300`

即宏观模型并不显式按瞬时工况分类，而是直接取平均工况的 emission rate。

#### 3.3.2 查询缓存机制

`MacroEmissionCalculator` 有一个进程内缓存：

- `_SEASON_MATRIX_CACHE: Dict[str, pd.DataFrame]`

流程是：

1. 第一次按季节读取 CSV
2. 为 `opModeID = 300` 构建 `(pollutant_id, source_type, model_year) -> rate` 的 lookup dict
3. 把 lookup 存进 `matrix.attrs["macro_emission_rate_lookup"]`
4. 后续相同季节复用 DataFrame 与 lookup

这说明宏观计算器已经做了针对高频重复查询的本地索引优化。

#### 3.3.3 路段级排放公式

单个路段的主逻辑在 `_calculate_link()`：

1. 读取：
   - `link_length_km`
   - `traffic_flow_vph`
   - `avg_speed_kph`
   - `fleet_mix`
2. 对 `fleet_mix` 百分比归一化到 100%
3. 对每个 vehicle class 计算 `vehicles_per_hour`
4. 对每个 pollutant 查询平均 emission rate
5. 计算路段排放

代码中的物理计算过程写得非常明确：

```text
emission_rate_g_per_sec = emission_rate / 3600
travel_time_sec = (link_length_km / avg_speed_kph) * 3600
emission_g_per_veh = emission_rate_g_per_sec * travel_time_sec
emission_kg_per_hr = emission_g_per_veh * vehicles_per_hour / 1000
```

也可以整理成等价形式：

```text
Emission_link,pollutant =
SUM_vehicle(
    EF_vehicle,pollutant(g/h)
    * link_length_km / avg_speed_kph(h)
    * vehicles_per_hour
) / 1000
```

最终得到：

- `total_emissions_kg_per_hr`
- `emission_rates_g_per_veh_km`

其中单位排放率计算为：

```text
rate = total_emissions_kg_per_hr * 1000 / link_length_km / traffic_flow_vph
```

#### 3.3.4 车队组成处理

宏观计算最重要的附加逻辑是 `fleet_mix` 处理。它分三层：

1. `MacroEmissionTool._standardize_fleet_mix()`
   - 把自然语言车型名标准化到受控 vehicle class
2. `MacroEmissionTool._apply_global_fleet_mix()`
   - 如果用户把 `fleet_mix` 写在顶层，则向每个 link 下发
3. `MacroEmissionTool._fill_missing_link_fleet_mix()`
   - 对仍缺失组成的 link 用默认车队组成填补

默认车队组成来自 `MacroEmissionCalculator.DEFAULT_FLEET_MIX`：

- `Passenger Car`: 70%
- `Passenger Truck`: 20%
- `Light Commercial Truck`: 5%
- `Transit Bus`: 3%
- `Combination Long-haul Truck`: 2%

这使得系统在文件缺失部分 fleet composition 时仍可计算，而不是直接失败。

#### 3.3.5 宏观输入文件的语义映射

宏观文件处理器 [`skills/macro_emission/excel_handler.py`](skills/macro_emission/excel_handler.py) 是一个独立值得强调的模块。它要求的标准字段是：

- 必需：
  - `link_length_km`
  - `traffic_flow_vph`
  - `avg_speed_kph`
- 可选：
  - `link_id`
  - `geometry`

列映射策略是三阶段融合：

1. `direct match`
2. `AI semantic mapping`
3. `fuzzy mapping`

是否启用三阶段由 [`config.py`](config.py) 的 `MACRO_COLUMN_MAPPING_MODES` 控制，默认是：

```text
direct,ai,fuzzy
```

此外，它还支持：

- 把 `daily_traffic` / `AADT` / `日交通量` 自动除以 `24` 转成 `veh/h`
- 自动解析车型占比列
- 把聚合的 `Truck%` 拆分到多个可计算的 truck class
- 保留 `geometry` 以供地图渲染

### 3.4 用户输入文件格式要求

这一部分建议在论文中单独写成“输入数据约束”小节。

#### 3.4.1 微观排放输入文件

来源：[`skills/micro_emission/excel_handler.py`](skills/micro_emission/excel_handler.py)

支持格式：

- `.csv`
- `.xlsx`
- `.xls`

列要求：

- 必需：
  - 速度列，支持别名：
    - `speed_kph`
    - `speed_kmh`
    - `speed`
    - `车速`
    - `速度`
- 可选：
  - 时间列：`t` / `time` / `time_sec` / `时间`
  - 加速度列：`acceleration` / `acc` / `acceleration_mps2` / `加速度`
  - 坡度列：`grade_pct` / `grade` / `坡度`

默认策略：

- 无时间列：按 `0,1,2,...` 自动生成
- 无加速度列：由速度差自动估算
- 无坡度列：默认 `0`

也就是说，微观工具对轨迹输入非常宽容，最低要求几乎只有“一列速度”。

#### 3.4.2 宏观排放输入文件

来源：[`skills/macro_emission/excel_handler.py`](skills/macro_emission/excel_handler.py)、[`tools/macro_emission.py`](tools/macro_emission.py)

支持格式：

- `.csv`
- `.xlsx`
- `.xls`
- `.zip`

其中 `.zip` 可以包含：

- Shapefile
- Excel/CSV

表格最低要求语义上要能映射出：

- 路段长度
- 流量
- 平均速度

可选增强字段：

- `link_id`
- `geometry`
- 各车型占比列

地图可视化支持的几何表达形式包括：

- WKT `LINESTRING(...)`
- GeoJSON 字符串
- 坐标数组
- `121.4,31.2;121.5,31.3` 这种坐标串

---

## 4. 工具协作模式

### 4.1 典型链路一：用户上传文件 -> `analyze_file` -> `calculate_macro_emission`

这是当前系统最典型的“文件驱动宏观排放”路径。

#### 4.1.1 实际调用链

```text
api/routes.py::chat()
  -> 保存上传文件到临时路径
  -> UnifiedRouter.chat(user_message, file_path)
     -> UnifiedRouter._analyze_file(file_path)
        -> ToolExecutor.execute("analyze_file", {"file_path": ...})
           -> FileAnalyzerTool.execute()
     -> MemoryManager.update(... file_analysis ...)
     -> ContextAssembler.assemble(... file_context ...)
     -> LLMClientService.chat_with_tools(... tools=TOOL_DEFINITIONS ...)
     -> 返回 calculate_macro_emission(...) 的 tool_call
     -> UnifiedRouter._process_response()
        -> ToolExecutor.execute("calculate_macro_emission", arguments, file_path)
           -> MacroEmissionTool.execute()
              -> ExcelHandler.read_links_from_excel() / _read_from_zip()
              -> MacroEmissionCalculator.calculate()
              -> _build_map_data()
     -> _synthesize_results()
     -> extract_table_data() / extract_map_data() / extract_download_file()
```

#### 4.1.2 协作机制解读

这里的 `analyze_file` 并不是可有可无的辅助功能，而是 upstream grounding 步骤：

1. 它先把文件识别为更可能属于 `macro_emission`
2. `ContextAssembler` 把文件摘要和路径写进当前 prompt
3. LLM 因此更倾向于直接选择 `calculate_macro_emission`
4. 真正执行时，`file_path` 又会被 `ToolExecutor` 自动注入目标工具

所以这条链是一个“隐式工具预调用 + 显式计算工具调用”的双阶段协作模式。

### 4.2 典型链路二：`query_knowledge` -> 参数确认 -> `calculate_*`

这是另一类更适合论文讨论的“知识辅助计算”路径。

#### 4.2.1 推荐的真实使用方式

在当前实现中，最稳妥的工作流是跨轮完成：

**第 1 轮**

```text
用户：NOx 是什么？宏观排放里怎么理解？
LLM -> query_knowledge(query="NOx 宏观排放含义", ...)
系统返回知识答案和参考文档
```

**第 2 轮**

```text
用户：那就按 NOx 计算这个文件
LLM -> calculate_macro_emission(...)
```

原因是：

- 当前 router 成功执行工具后不会再次让 LLM 基于前一个工具结果继续规划下一步；
- 多工具协作虽然支持同轮顺序执行，但不是 success-driven replanning。

#### 4.2.2 当前系统支持的多工具协作方式

当前系统的多工具协作机制可以概括为：

1. LLM 一次返回多个 `tool_calls`
2. Router 顺序执行
3. 收集所有结果
4. 做统一 synthesis

伪代码如下：

```python
response = llm.chat_with_tools(...)
for tc in response.tool_calls:
    result = executor.execute(tc.name, tc.arguments)
tool_results.append(result)
final_answer = synthesize(tool_results)
```

这意味着：

- 如果 LLM 在一开始就能确定多个工具都要调用，可以同轮执行。
- 如果第二个工具的参数必须依赖第一个工具的输出，则当前系统更适合通过“错误重试”或“下一轮对话”完成，而不是同轮 success chaining。

### 4.3 多工具协作中的结果传递机制

工具之间并不是通过共享 Python 对象直接串联，而是通过三种渠道协作：

1. **Router 级即时传递**
   - `tool_results` 在 `UnifiedRouter._process_response()` 中集中保存
2. **Memory 级跨轮传递**
   - `MemoryManager.update()` 会保存 compact tool call records
   - `last_tool_name`、`last_tool_summary`、`last_tool_snapshot` 可被后续轮次引用
3. **Prompt 级语义传递**
   - `ContextAssembler` 会把 fact memory 和 file context 注入新的 prompt

因此，系统的 tool collaboration 不是 workflow engine 风格的 DAG 编排，而是：

- 单轮内：router 顺序执行 + 统一综合
- 跨轮间：memory grounding + 重新路由

---

## 结论：工具层与计算层的架构特征

从代码实现看，Emission Agent 的工具链具备以下特征：

1. **工具层是薄封装，计算层是核心数值引擎**
   - `tools/` 主要负责参数适配、文件 I/O、结果包装
   - `calculators/` 才承载真正的 MOVES 查询和排放公式

2. **路由层与计算层通过统一 `ToolResult` 解耦**
   - Router 不关心具体公式，只关心 `success/data/summary`
   - 前端 payload 也通过统一抽取器从工具结果生成

3. **宏观工具比微观工具更“智能文件驱动”**
   - 宏观输入支持 `direct + ai + fuzzy` 语义列映射
   - 微观输入当前仍主要依赖 alias 匹配

4. **多工具协作是“router orchestration”，不是完整 planner**
   - 系统支持 multi-tool selection
   - 但成功后不会自动继续 re-plan
   - 更适合文件 grounding、知识辅助澄清和跨轮计算

5. **计算引擎呈现了三种不同的数据抽象层级**
   - `EmissionFactors`: 速度曲线查询
   - `MicroEmission`: 秒级 `VSP/opMode` 轨迹积分
   - `MacroEmission`: 路段级车队组合聚合

如果写成论文，本部分可以作为“Tool-Orchestrated Computational Architecture”章节的核心技术材料，其中最值得突出的是：

- 工具定义与执行分离
- 文件语义映射与宏观输入鲁棒性
- `VSP` 微观排放与 `MOVES-Matrix` 宏观排放并存的双尺度计算框架
- `query_knowledge` 对参数解释与法规 grounding 的辅助作用
