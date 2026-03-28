# Emission Agent 技术分析（Part 2：文件驱动任务锚定与参数标准化机制）

本文基于以下文件与目录的顺序阅读完成：`tools/file_analyzer.py`、`tools/definitions.py`、`core/executor.py`、`services/standardizer.py`、`services/llm_client.py`，并补充核对了相关主链路文件 `core/router.py`、`core/assembler.py`、`config/prompts/core.yaml`、`config/unified_mappings.yaml`、`shared/standardizer/local_client.py`、`shared/standardizer/vehicle.py`、`shared/standardizer/pollutant.py`、`llm/client.py` 以及 `LOCAL_STANDARDIZER_MODEL/` 中的训练与部署文件。

本部分的核心结论有两点：

1. Emission Agent 并不是“用户上传一个文件，LLM 自己猜怎么处理”的松散流程，而是通过 `FileAnalyzerTool` 把文件显式转化为 `task_type + columns + sample_rows + mapping hints` 的结构化任务锚点，再由 `ContextAssembler` 注入到 LLM 上下文中，形成 **File-Driven Task Grounding**。
2. 当前主链路中的参数标准化并不是让 LLM 直接输出严格的 MOVES 参数，而是在 `core/executor.py` 中，于 **LLM 完成 tool call 之后、tool 实际执行之前** 介入。这种做法构成了一个典型的 **Execution-Side Parameter Standardization** 机制。

同时，仓库中还存在一条本地标准化模型路线：`LOCAL_STANDARDIZER_MODEL/ + shared/standardizer/local_client.py`。这条路线已经有训练脚本、LoRA 配置、推理客户端和 vLLM 启动脚本，但在当前 `services/standardizer.py` 主路径中，仅 vehicle/pollutant 的本地 fallback 被真实接入，column model 尚未接入 `map_columns()` 的主逻辑。

## 1. 文件驱动的任务锚定（File-Driven Task Grounding）

### 1.1 `tools/file_analyzer.py` 的完整处理流程

`tools/file_analyzer.py::FileAnalyzerTool.execute()` 是系统中对上传文件做“前分析”的核心入口。其整体流程如下：

```python
async def execute(file_path):
    validate_file_exists()
    if suffix == ".zip":
        return await _analyze_zip_file(...)
    elif suffix in [".csv", ".xlsx", ".xls"]:
        df = read_tabular_file(...)
        df.columns = df.columns.str.strip()
        analysis = _analyze_structure(df, filename)
        summary = _format_summary(analysis)
        return ToolResult(success=True, data=analysis, summary=summary)
    else:
        return error("Unsupported file format")
```

从实现细节看，它做了 5 件事：

1. **校验文件是否存在**
   使用 `Path(file_path).exists()`，若路径不存在则立即报错。

2. **按文件类型分流**
   - `.csv` -> `pandas.read_csv`
   - `.xlsx/.xls` -> `pandas.read_excel`
   - `.zip` -> `_analyze_zip_file()`
   - 其他后缀 -> 返回“不支持的格式”

3. **清洗列名**
   对 tabular file 执行 `df.columns = df.columns.str.strip()`，避免列名前后空格影响后续识别。

4. **结构分析**
   调用 `_analyze_structure(df, filename)`，输出结构化结果。

5. **为 LLM 生成摘要**
   调用 `_format_summary(analysis)`，把文件名、行数、列名、检测到的 `task_type` 和 sample rows 变成工具摘要文本。

### 1.2 ZIP / Shapefile 的特殊处理

`FileAnalyzerTool` 并不仅支持普通表格，还支持 ZIP 文件：

#### 情况 A：ZIP 中包含 `.shp`

调用 `_analyze_shapefile_zip()`：

1. 使用 `zip_ref.extractall(tmp_dir)` 解压全部文件
2. 递归查找 `.shp`
3. 用 `geopandas.read_file(shp_path)` 读取 GeoDataFrame
4. 调用 `_analyze_shapefile_structure(gdf, zip_path.name)`

Shapefile 分析结果会返回：

- `format = "shapefile"`
- `row_count`
- `geometry_types`
- `columns`（排除 geometry）
- `bounds`
- `sample_data`
- `task_type = "macro_emission"`

这里最重要的一点是：**Shapefile 被直接锚定为 `macro_emission`**。这说明系统把 GIS/road network 类型文件当作天然的宏观排放输入。

#### 情况 B：ZIP 中包含 CSV / Excel

调用 `_analyze_tabular_zip()`：

1. 先从压缩包中抽出一个表格文件到临时目录
2. 读入为 DataFrame
3. 清理列名
4. 重用 `_analyze_structure(df, filename)`

因此，ZIP 只是文件包装形式；真正的任务锚定仍然回到 DataFrame 结构分析。

### 1.3 如何从文件推断任务类型

当前实现中，任务类型推断由 `FileAnalyzerTool._identify_task_type(columns)` 完成。注意，这一逻辑主要基于 **列名特征**，而不是数值统计特征。

其代码逻辑可以概括为：

```python
columns_lower = [c.lower() for c in columns]

micro_indicators = ["speed", "velocity", "速度", "time", "acceleration", "加速"]
macro_indicators = ["length", "flow", "volume", "traffic", "长度", "流量", "link"]

micro_score = count(indicator appears in any column)
macro_score = count(indicator appears in any column)

if micro_score > macro_score:
    return "micro_emission", confidence
elif macro_score > micro_score:
    return "macro_emission", confidence
else:
    return "unknown", 0.3
```

#### micro_emission 的识别依据

偏向轨迹级数据的列名信号包括：

- `speed`
- `velocity`
- `速度`
- `time`
- `acceleration`
- `加速`

这些信号对应逐秒轨迹数据的典型字段：时间、速度、加速度。

#### macro_emission 的识别依据

偏向路段/链路级数据的列名信号包括：

- `length`
- `flow`
- `volume`
- `traffic`
- `长度`
- `流量`
- `link`

这些信号对应 link-level emission 计算所需的长度、流量、平均速度、路段 ID 等字段。

#### confidence 的生成方式

置信度并非来自模型概率，而是启发式公式：

```python
confidence = min(0.5 + score * 0.15, 0.95)
```

因此它本质上是 **heuristic confidence**，不是统计学习意义上的 calibrated confidence。

### 1.4 文件分析不仅做任务分类，还做列名映射预分析

在 `_analyze_structure(df, filename)` 中，除了 `task_type` 推断之外，还做了两项重要工作：

#### 1. 调用 `services.standardizer.map_columns(...)`

```python
micro_mapping = self.standardizer.map_columns(columns, "micro_emission")
macro_mapping = self.standardizer.map_columns(columns, "macro_emission")
```

这一步的意义在于：

- 即使当前还没决定最终是 micro 还是 macro
- 系统也会分别尝试把上传文件列名映射到两套标准 schema 上

因此，文件分析结果中不仅有 `task_type`，还有：

- `micro_mapping`
- `macro_mapping`

这为后续工具选择和列可用性判断提供了支持。

#### 2. 判断 required columns 是否具备

```python
micro_required = self.standardizer.get_required_columns("micro_emission")
macro_required = self.standardizer.get_required_columns("macro_emission")
```

然后分别计算：

- `micro_has_required`
- `macro_has_required`

这两个字段并不直接决定 `task_type`，但它们表达了一个更细的语义：

> “文件看起来像是某类任务，且已具备/未具备该类任务的最小必需字段”

这对后续参数澄清特别重要。

### 1.5 `FileAnalyzerTool` 输出了哪些元信息

对 tabular file，当前 `analysis` dict 包含：

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

对 Shapefile，还额外包含：

- `format`
- `geometry_types`
- `bounds`
- `sample_data`

### 1.6 “列名、行数、数据范围”如何传递到后续阶段

这里需要严格按 live code 说明。

#### Step 1. API 保存文件路径

`api/routes.py::chat()` 在收到上传文件后，会保存到：

```text
/tmp/emission_agent/{session_id}_input{suffix}
```

并把路径提示追加到用户消息中：

```text
文件已上传，路径: ...
请使用 input_file 参数处理此文件。
```

#### Step 2. Router 触发预分析

`core/router.py::UnifiedRouter.chat()` 在发现 `file_path` 存在时，会执行：

```python
file_context = await self._analyze_file(file_path)
```

其中 `_analyze_file()` 会调用：

```python
self.executor.execute(
    tool_name="analyze_file",
    arguments={"file_path": file_path},
    file_path=file_path
)
```

#### Step 3. 文件分析结果被缓存到 Memory

同一轮结束后，`core/memory.py::MemoryManager.update()` 会把：

- `active_file`
- `file_analysis`

写入 fact memory。

因此，文件信息不仅服务当前轮，也会服务后续多轮对话。

#### Step 4. Assembler 把文件信息变成 prompt

`core/assembler.py::ContextAssembler.assemble()` 有两条文件信息注入通道：

##### 通道 A：当前轮 file context 注入

调用 `_format_file_context(file_context)`，把以下字段拼成一段文本：

- `Filename`
- `File path`
- `task_type`
- `Rows`
- `Columns`
- `Sample (first 2 rows)`

然后直接 prepend 到当前 `user_message` 前面。

##### 通道 B：历史 fact memory 注入

`_format_fact_memory()` 会把缓存的 `file_analysis` 中的以下字段以 system message 的形式注入：

- `Cached file task_type`
- `Cached file rows`
- `Cached file columns`

因此，同一个文件在后续多轮中不需要重复上传，也能保持任务锚定。

### 1.7 当前实现中“数据范围”信息的真实边界

你在提纲中要求分析“列名、行数、数据范围”的传递路径，这里必须如实说明当前代码边界：

#### 已实现

- 表格文件：
  - 列名 `columns`
  - 行数 `row_count`
  - 前两行样本 `sample_rows`
- Shapefile：
  - 空间范围 `bounds`（经纬度 bounding box）

#### 尚未实现

当前 `tools/file_analyzer.py` **没有** 对普通 CSV/Excel 计算通用的数值范围统计，例如：

- 每列最小值/最大值
- 速度范围
- 流量范围
- 缺失值比例

因此，如果论文中要写“data range”，建议准确表述为：

> 对 tabular file，系统当前传递的是 columns、row_count、sample_rows；对 GIS/Shapefile，系统还传递 spatial bounds。一般数值列的 min/max range 尚未在主链路中实现。

### 1.8 文件信息如何影响工具选择与参数推断

文件信息对后续 LLM 决策的影响主要通过 3 个机制实现：

#### 机制 A：system prompt 显式约束

`config/prompts/core.yaml` 明确规定：

- `task_type == "micro_emission"` -> 直接使用 `calculate_micro_emission`
- `task_type == "macro_emission"` -> 直接使用 `calculate_macro_emission`
- `task_type == "unknown"` -> 需要询问用户

这相当于把 file analysis 的结果提升为 tool routing signal。

#### 机制 B：当前 user message 中显式包含 file summary

由于 `ContextAssembler` 会把 file summary 直接 prepend 到当前 user message，LLM 在做 function calling 决策时，会同时看到：

- 文件路径
- 任务类型
- 行数
- 列名
- 样本数据
- 用户自然语言请求

这使得“文件结构”和“用户意图”被统一到同一条 user message 中。

#### 机制 C：tool schema 要求使用 `file_path`

`tools/definitions.py` 中：

- `calculate_micro_emission.file_path`
- `calculate_macro_emission.file_path`
- `analyze_file.file_path`

都把 `file_path` 显式定义为函数参数，且说明该参数应在用户上传文件时使用。

因此，文件不是被前端“悄悄上传”的被动附件，而是 LLM 工具调用 schema 中的第一类参数。

### 1.9 论文视角：为什么这是 File-Driven Task Grounding

从论文角度，这一机制的创新点不在于“系统会读取 Excel”，而在于：

#### 1. 文件被结构化地前分析，而不是盲传给 LLM

系统先用 `FileAnalyzerTool` 把文件转成结构化中间表示：

```text
file -> analysis dict -> prompt grounding
```

而不是简单把“用户上传了文件”这一事实告诉 LLM。

#### 2. 文件直接参与 tool routing

`task_type` 并不是附加说明，而是决定 `calculate_micro_emission` 还是 `calculate_macro_emission` 的锚点。

#### 3. 文件上下文跨轮保留

通过 `MemoryManager.fact_memory.file_analysis`，文件信息在后续多轮对话中仍可作为推理依据。

#### 4. 文件结构与自然语言意图被统一对齐

Assembler 不是把文件信息放在一个“附件列表”里，而是直接把 file summary 融入当前 user message，使 LLM 能在一份上下文中同时看到：

- “文件长什么样”
- “用户想做什么”

这就是一种典型的 **task grounding by file semantics**。

### 1.10 这一机制的现实局限

当前文件驱动锚定机制也有明确边界：

1. `task_type` 推断主要基于列名关键词，尚未结合列值统计或 sample value semantics。
2. `micro_mapping` / `macro_mapping` / `*_has_required` 虽然已在 `file_analyzer.py` 中计算，但当前 `ContextAssembler._format_file_context()` 并未把这些字段直接注入 prompt。
3. 通用 numeric range 尚未纳入 tabular file pre-analysis。

因此，它已经是“主动参与决策的文件”，但仍是一个 **heuristic grounding layer**，不是完全数据语义理解层。

## 2. 执行侧参数标准化（Execution-Side Parameter Standardization）

### 2.1 这一机制的核心定义

所谓 **Execution-Side Parameter Standardization**，在本项目中指的是：

> 让 LLM 负责理解用户意图并给出自然语言风格的 tool call 参数；随后由 `core/executor.py` 在工具真正执行之前，透明地把这些参数转换成后端可执行的标准值。

这个设计在代码上有明确证据：

#### `tools/definitions.py` 的工具描述

多个工具都明确写着：

- `vehicle_type`: “Pass user's original expression”
- `pollutants`: “System will automatically recognize it”

#### `config/prompts/core.yaml`

system prompt 中写明：

```text
参数标准化（如车型、污染物）由系统自动处理
你只需传递用户的原始表述即可
```

这说明标准化不是 LLM 的显式职责，而是执行层职责。

### 2.2 标准化发生的精确时机

精确时序如下：

```text
LLM chat_with_tools()
  -> 产出 tool_calls (name + arguments)
  -> UnifiedRouter._process_response()
  -> ToolExecutor.execute(tool_name, arguments, file_path)
     -> _standardize_arguments(...)
     -> tool.execute(**standardized_args)
```

即：

1. LLM 已经决定了要调用哪个工具
2. LLM 已经生成了原始参数
3. 但 tool 还没执行
4. 此时 Executor 进行标准化

对应 `core/executor.py::ToolExecutor.execute()` 的关键顺序是：

```python
tool = self.registry.get(tool_name)
standardized_args = self._standardize_arguments(tool_name, arguments)
if file_path and "file_path" not in standardized_args:
    standardized_args["file_path"] = file_path
result = await tool.execute(**standardized_args)
```

因此可以用一句话概括：

> 标准化发生在 **post-tool-call, pre-tool-execution** 阶段。

### 2.3 `services/standardizer.py` 的总体架构

`services/standardizer.py::UnifiedStandardizer` 的设计思路非常清楚：

```text
configuration table first
-> fuzzy match second
-> local model fallback third
-> fail gracefully
```

初始化时它会：

1. 通过 `ConfigLoader.load_mappings()` 读取 `config/unified_mappings.yaml`
2. 调用 `_build_lookup_tables()`
3. 构造：
   - `vehicle_lookup`
   - `pollutant_lookup`
   - `column_patterns`

因此当前主链路中的标准化是 **configuration-first**，不是默认依赖在线 LLM。

### 2.4 `standardize_vehicle()` 的完整流程

`UnifiedStandardizer.standardize_vehicle(raw_input)` 的逻辑如下：

```python
if not raw_input:
    return None

raw_lower = raw_input.lower().strip()

if raw_lower in self.vehicle_lookup:
    return exact_match_standard_name

best_match = fuzzy_match(threshold=70)
if best_match:
    return best_match.standard_name

if self._get_local_model():
    result = self._local_model.standardize_vehicle(raw_input)
    if result and result["confidence"] > 0.9:
        return result["standard_name"]

return None
```

它处理的核心不匹配包括：

- 中文别名 -> 标准英文车型
- 英文别名 -> 标准英文车型
- 大小写差异
- 轻微拼写差异 / 模糊表述

例如：

- `公交车` -> `Transit Bus`
- `SUV` -> `Passenger Car`
- `大货车` -> `Combination Long-haul Truck`

其底层依据来自 `config/unified_mappings.yaml` 中：

- `vehicle_types[*].standard_name`
- `vehicle_types[*].display_name_zh`
- `vehicle_types[*].aliases`

### 2.5 `standardize_pollutant()` 的完整流程

污染物标准化和车型标准化完全平行，但使用更严格的 fuzzy threshold：

- vehicle threshold = 70
- pollutant threshold = 80

其原因也很合理：

- 车型别名更丰富，模糊度更高
- 污染物集合更小、更敏感，误判代价更高

典型映射包括：

- `碳排放` -> `CO2`
- `氮氧` -> `NOx`
- `颗粒物` -> `PM2.5`

### 2.6 `map_columns()` 的完整流程

`services/standardizer.py::map_columns(columns, task_type)` 是文件驱动链中的另一个关键方法。

它的逻辑并不是 LLM-based，而是 **pattern-based rule matching**：

```python
patterns = self.column_patterns.get(task_type, {})

for col in columns:
    # Pass 1: exact match
    if col_lower == pattern.lower():
        mapping[col] = standard_name

    # Pass 2: substring match
    if pattern in col or col in pattern:
        mapping[col] = standard_name
```

它有两个阶段：

#### Pass 1：Exact match

精确命中某个标准字段的别名模式，例如：

- `车速` -> `speed_kph`
- `交通流量` -> `traffic_flow_vph`

#### Pass 2：Substring match

若没有 exact match，则尝试：

- `pattern in col_lower`
- `col_lower in pattern`

并使用最长 pattern 优先。

这使得：

- `link_avg_speed_kmh`
- `速度(km/h)`
- `流量(辆/h)`

等较长变体也能识别出来。

### 2.7 受支持的“不匹配类型”与当前能力边界

你要求分析以下几类不匹配。基于 live code，当前必须区分“已在执行侧实现”与“仅在其他层存在枚举/默认值”。

#### 已在执行侧明确处理

##### 1. 自然语言车型名称 -> MOVES 标准车型

已实现，路径为：

```text
Executor._standardize_arguments()
  -> UnifiedStandardizer.standardize_vehicle()
```

##### 2. 自然语言污染物名称 -> 标准污染物标识

已实现，路径为：

```text
Executor._standardize_arguments()
  -> UnifiedStandardizer.standardize_pollutant()
```

##### 3. 文件列名 -> 标准字段名

已实现，但发生在 file analysis 阶段，而不是 tool 参数阶段：

```text
FileAnalyzerTool._analyze_structure()
  -> UnifiedStandardizer.map_columns()
```

#### 当前未在执行侧明确实现

##### 4. 模糊年份表述 -> 标准 `model_year`

**未在 `services/standardizer.py` 中实现。**

当前代码中：

- `core/executor.py::_standardize_arguments()` 不处理 `model_year`
- `services/standardizer.py` 没有 `standardize_year()`
- `tools/micro_emission.py` / `tools/macro_emission.py` 只是默认 `model_year = 2020`
- `tools/emission_factors.py` 要求 `model_year` 必填

因此，像“20年的车”“近几年车型”这类自然语言年份，目前 **不是 execution-side standardization 已支持能力**。

##### 5. 模糊季节表述 -> 受控季节枚举

**主链路中未在 Executor/Standardizer 层实现。**

需要注意三个事实：

1. `config/unified_mappings.yaml` 中存在 `seasons.aliases`
2. 旧路径 `shared/standardizer/constants.py` 中存在 `SEASON_MAPPING`
3. calculators 中存在 `SEASON_CODES`

但是：

- `services/standardizer.py` 当前不调用这些 seasons aliases
- `core/executor.py` 也不标准化 `season`

因此，季节在当前主链路更多依赖：

- tool 层默认值（通常为 `"夏季"`）
- downstream calculator 的内部枚举

##### 6. 模糊道路类型表述 -> 受控 `road_type`

同样，**未在 execution-side standardization 层实现**。

当前只有：

- `calculators/emission_factors.py::ROAD_TYPE_MAPPING`

会把：

- `高速公路`
- `城市道路`
- `地面道路`
- `居民区道路`

映射到内部道路类型 ID。

这属于 **calculator-level normalization**，而不是 `services/standardizer.py` 层的显式标准化。

### 2.8 `executor.py` 中调用 standardizer 的代码路径

在 `core/executor.py::_standardize_arguments()` 中，当前只拦截三个参数键：

- `vehicle_type`
- `pollutant`
- `pollutants`

具体逻辑是：

```python
for key, value in arguments.items():
    if key == "vehicle_type":
        standardized[key] = standardizer.standardize_vehicle(value)
    elif key == "pollutant":
        standardized[key] = standardizer.standardize_pollutant(value)
    elif key == "pollutants":
        standardized[key] = [
            standardizer.standardize_pollutant(pol) or pol
            for pol in value
        ]
    else:
        standardized[key] = value
```

这说明标准化当前是一个 **targeted argument interceptor**，而不是对所有参数做统一 normalization。

### 2.9 标准化失败时如何处理

如果 `standardize_vehicle()` 或 `standardize_pollutant()` 返回 `None`，Executor 会抛出 `StandardizationError`，并返回结构化错误结果：

```python
{
    "success": False,
    "error": True,
    "error_type": "standardization",
    "message": "...",
    "suggestions": [...]
}
```

这有两个重要效果：

1. 对 tool 来说，输入已经被过滤成“可执行”或“显式失败”两类。
2. 对 Router 来说，标准化失败并不是静默错误，而是可以回填给 LLM，触发 clarification 或重试。

### 2.10 当前标准化是规则、LLM 还是混合？

如果只看当前主链路 `services/standardizer.py`，答案是：

> **混合式，但以 configuration/rule 为主，本地模型为可选 fallback。**

具体拆分如下：

#### 第 1 层：配置映射

来源：

- `config/unified_mappings.yaml`

机制：

- exact alias lookup

特点：

- 透明
- 可维护
- 不依赖在线模型

#### 第 2 层：fuzzy matching

来源：

- `fuzzywuzzy.fuzz.ratio`
- 若库不可用，则 fallback 到 `difflib.SequenceMatcher`

机制：

- vehicle threshold = 70
- pollutant threshold = 80

特点：

- 处理轻微拼写差异
- 仍是 deterministic heuristic

#### 第 3 层：本地标准化模型 fallback

来源：

- `shared/standardizer/local_client.py`

触发条件：

- `config.use_local_standardizer == True`

机制：

- lazy load
- `confidence > 0.9` 才接受

特点：

- 可学习更复杂表述
- 但当前只对 vehicle / pollutant fallback 生效

#### 没有接入的部分

当前 `services/standardizer.py` **没有** 调用在线 API/云端 LLM 标准化。云端 API 标准化主要存在于旧路径：

- `shared/standardizer/vehicle.py`
- `shared/standardizer/pollutant.py`

### 2.11 为什么要在执行侧做标准化，而不是让 LLM 直接输出标准参数

这是本项目很有论文价值的设计点。

#### 原因 1：把“理解意图”和“满足后端约束”解耦

LLM 更适合做：

- 理解“这是一辆网约车”
- 理解“碳排放”指 `CO2`
- 理解“刚才那个文件应该算宏观排放”

而标准化层更适合做：

- 把 `网约车` 统一成 `Passenger Car`
- 把 `碳排放` 统一成 `CO2`
- 把列名统一成 `link_length_km`

#### 原因 2：tool schema 可以保持自然语言友好

因为标准化在执行侧完成，所以 `tools/definitions.py` 可以明确告诉 LLM：

```text
Pass user's original expression
System will automatically recognize it
```

这让 tool definitions 更贴近用户语义，而不是迫使 LLM 始终输出严格英文枚举。

#### 原因 3：标准化规则可以独立演化

新增一个车型别名时，不需要重新训主 Agent，也不需要修改 Router，只需：

- 更新 `config/unified_mappings.yaml`
- 或改进 `services/standardizer.py`

#### 原因 4：错误可以被显式建模

执行侧标准化失败时，可以：

- 返回 suggestions
- 触发 Router retry
- 让 LLM 向用户发 clarification

如果把所有标准化都压给 LLM，失败往往只会表现为“错误 tool arguments”，而不是结构化的 standardization failure。

#### 原因 5：便于替换底层标准化引擎

当前 `services/standardizer.py` 的 fallback 已经预留了：

- 规则映射
- fuzzy
- 本地模型

未来即使要切换：

- 本地 LoRA
- 云端 API
- 小模型分类器

对 Router 和 tool schema 都是透明的。

### 2.12 从论文角度概括这一机制

可以把这一机制表述为：

> Emission Agent 采用了一种 execution-side parameter standardization 设计：LLM 仅需输出贴近用户原表达的 tool arguments，严格的 domain-specific normalization 由执行层在工具调用和工具执行之间透明完成。该设计降低了主 LLM 的 schema 负担，同时保证了后端计算引擎与 MOVES 标准参数空间的一致性。

## 3. 4B 轻量标准化模型（本地标准化模型路线）

### 3.1 仓库中是否存在相关代码/数据

存在，而且内容相当完整：

- 数据构造脚本：`LOCAL_STANDARDIZER_MODEL/scripts/01_create_seed_data.py`
- 数据增强脚本：`LOCAL_STANDARDIZER_MODEL/scripts/02_augment_data.py`
- 数据格式转换与切分：`LOCAL_STANDARDIZER_MODEL/scripts/03_prepare_training_data.py`
- LoRA 训练：`LOCAL_STANDARDIZER_MODEL/scripts/04_train_lora.py`
- 评估：`LOCAL_STANDARDIZER_MODEL/scripts/06_evaluate.py`
- 配置：`LOCAL_STANDARDIZER_MODEL/configs/*.yaml`
- 本地客户端：`shared/standardizer/local_client.py`
- 部署脚本：`LOCAL_STANDARDIZER_MODEL/start_vllm.sh`

因此，这不是一个空概念，而是一条真实存在的工程扩展路径。

### 3.2 训练数据是如何构造的

本地标准化模型的数据链是：

```text
rule seed extraction
  -> data augmentation
  -> chat-format conversion
  -> train/eval/test split
```

#### Step 1. 生成种子数据

`01_create_seed_data.py` 生成三类 seed：

##### 1. vehicle seed

由 13 类 MOVES 标准车型及其别名生成：

- `input = alias`
- `output = standard_type`
- `category = "vehicle"`

真实数据量：

- `vehicle_type_seed.json` = 236 条

##### 2. pollutant seed

由标准污染物及其别名生成：

- `input = alias`
- `output = standard_pollutant`
- `category = "pollutant"`

真实数据量：

- `pollutant_seed.json` = 66 条

##### 3. column mapping seed

由三套字段生成：

- `MICRO_EMISSION_COLUMNS`
- `MACRO_EMISSION_COLUMNS`
- `FLEET_MIX_COLUMNS`

其中车队组成列也被建模为可映射输出，例如：

- `私家车%` -> `Passenger Car`
- `公交车%` -> `Transit Bus`

真实数据量：

- `column_mapping_seed.json` = 158 条

#### Step 2. 数据增强

`02_augment_data.py::DataAugmenter` 采用了比较系统的增强策略。

##### 对 vehicle / pollutant 文本增强

增强方式包括：

- 去空格 / 加空格
- 大小写变化
- 标点变化
- 上下文模板包裹
- 车型专用修饰词添加

上下文模板例如：

- `查询{}`
- `我想查{}`
- `{}类型`
- `帮我查{}的数据`
- `{}的排放`

车型专用修饰词包括：

- `新能源`
- `电动`
- `燃油`
- `混动`
- `柴油`
- `国六`

##### 对 column mapping 的增强

其思路不是对单列做变体，而是生成“模拟真实 Excel 表头组合”：

1. 随机选 2-4 个标准字段
2. 每个字段随机选一个 alias
3. 组合成一组列名
4. 随机加入 30% 的噪声列，例如：
   - `备注`
   - `说明`
   - `序号`
   - `Unnamed: 0`
5. 打乱顺序

这使 column model 学到的不是单点 alias classification，而是 **multi-column contextual mapping**。

增强后真实数据量：

- `unified_augmented.json` = 5,121 条
- `column_augmented.json` = 3,000 条

#### Step 3. 转换成聊天格式

`03_prepare_training_data.py` 将数据转成 Qwen chat format。

##### unified model 的输入格式

system prompt + task tag：

- `[vehicle] 大货车`
- `[pollutant] 碳排放`

assistant 只输出标准值，例如：

- `Combination Long-haul Truck`
- `CO2`

##### column model 的输入格式

system prompt 指定 `task_type`

user 输入是列名数组的 JSON 字符串，例如：

```json
["车流量", "私家车%"]
```

assistant 输出是 mapping 的 JSON 字符串，例如：

```json
{"私家车%": "Passenger Car", "车流量": "traffic_flow_vph"}
```

#### Step 4. 划分训练/验证/测试集

`split_dataset()` 使用：

- `train_ratio = 0.85`
- `eval_ratio = 0.10`
- 剩余 0.05 为 test
- `random.seed(42)`

真实切分结果为：

##### unified model

- `unified_train.json` = 4,352
- `unified_eval.json` = 512
- `unified_test.json` = 257

##### column model

- `column_train.json` = 2,550
- `column_eval.json` = 300
- `column_test.json` = 150

### 3.3 模型选型与微调方式

#### 训练脚本层面的模型与任务形式

`04_train_lora.py` 使用：

- `AutoModelForCausalLM`
- `AutoTokenizer`
- `PEFT / LoRA`
- `TaskType.CAUSAL_LM`

数据预处理通过 `tokenizer.apply_chat_template(...)` 将三轮对话转成训练文本。

这说明本地标准化模型不是 classification head，而是 **instruction-tuned causal LM + LoRA adapter**。

#### LoRA 配置

##### unified model

`configs/unified_lora_config.yaml`：

- `r = 16`
- `lora_alpha = 32`
- `target_modules = [q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj]`
- `num_train_epochs = 5`
- `learning_rate = 2e-4`
- `batch_size = 4`
- `gradient_accumulation_steps = 4`
- `max_length = 256`

##### column model

`configs/column_lora_config.yaml`：

- `r = 32`
- `lora_alpha = 64`
- 同样覆盖 attention + MLP 投影层
- `num_train_epochs = 8`
- `learning_rate = 1e-4`
- `max_length = 512`

column model 使用更大的 rank 和更长上下文，反映出列名映射任务比单个 label standardization 更复杂。

### 3.4 “4B 轻量模型”在代码中的真实状态

这里需要非常谨慎地区分“训练配置”和“当前集成默认值”。

#### 文档/配置中的 4B 路线

以下文件明确写的是：

- `Qwen/Qwen3-4B-Instruct-2507`

例如：

- `LOCAL_STANDARDIZER_MODEL/configs/unified_lora_config.yaml`
- `LOCAL_STANDARDIZER_MODEL/configs/column_lora_config.yaml`
- `LOCAL_STANDARDIZER_MODEL/README.md`

因此，从训练设计文档角度，它确实是一条 **Qwen3-4B + LoRA** 路线。

#### 当前运行时默认值仍偏向 3B

但以下 live integration/default files 使用的是：

- `Qwen/Qwen2.5-3B-Instruct`

例如：

- `config.py::local_standardizer_config["base_model"]`
- `LOCAL_STANDARDIZER_MODEL/start_vllm.sh`
- `LOCAL_STANDARDIZER_MODEL/QUICKSTART.md`
- `TRAINING_GUIDE.md`
- `INTEGRATION_GUIDE.md`

因此，当前仓库实际上存在一个明显分裂：

```text
训练配置/部分 README: Qwen3-4B
运行时默认配置/部署脚本: Qwen2.5-3B
```

如果论文要写“4B 轻量标准化模型”，建议明确表述为：

> 代码仓库包含面向 Qwen3-4B-Instruct-2507 的训练配置，但当前默认部署脚本与运行时配置仍以 Qwen2.5-3B-Instruct 为主，说明该本地标准化模型路线仍处于从实验配置向主线部署收敛的过渡阶段。

### 3.5 本地模型如何部署

`shared/standardizer/local_client.py` 提供两种推理模式：

#### 模式 A：direct

直接加载：

- tokenizer
- base model
- unified LoRA
- column LoRA

然后通过 `_switch_adapter("unified" | "column")` 动态切换适配器。

#### 模式 B：vllm

通过 HTTP 请求调用 vLLM 服务。

`LOCAL_STANDARDIZER_MODEL/start_vllm.sh` 的核心命令是：

```bash
vllm serve "$BASE_MODEL" \
    --enable-lora \
    --lora-modules unified="$UNIFIED_LORA" \
    --lora-modules column="$COLUMN_LORA" \
    --port 8001
```

这说明部署策略不是起两个模型服务，而是：

> 一个 base model + 两个可切换 LoRA adapter

### 3.6 本地模型与云端 API 标准化的对比

这里必须区分当前主链路和旧路径。

#### 云端 API 标准化：旧路径 `shared/standardizer/*`

`shared/standardizer/vehicle.py` 与 `pollutant.py` 的流程是：

```text
rule match
-> if not enough confidence:
   call llm.client.get_llm("standardizer")
-> prompt LLM to return JSON {"standard": ..., "confidence": ...}
-> parse JSON
-> wrap as StandardizationResult
```

特点：

- 依赖云端/API LLM
- 有显式 confidence
- 返回对象更丰富
- 每次标准化可能产生一次外部模型调用

#### 本地模型标准化：`shared/standardizer/local_client.py`

流程是：

```text
load base model + LoRA
-> [vehicle]/[pollutant] prompt
-> generate string
-> validate against standard set
```

特点：

- 本地推理，无 API 成本
- direct / vLLM 两种部署
- dynamic LoRA adapter switching
- 更适合高频调用

#### 当前新主链路：`services/standardizer.py`

当前新主链路则更轻量：

```text
config lookup
-> fuzzy
-> optional local model fallback
```

特点：

- 无需每次都调 LLM
- 更适合 Executor 内同步、低成本地做标准化
- 对 Router 完全透明

### 3.7 本地模型当前接入程度

这是论文中必须准确说明的部分。

#### 已接入

`services/standardizer.py::_get_local_model()` 会在：

- `use_local_standardizer = True`

时懒加载：

- `shared.standardizer.local_client.get_local_standardizer_client()`

随后：

- `standardize_vehicle()`
- `standardize_pollutant()`

会把本地模型作为 fallback 使用。

#### 未完全接入

虽然 `shared/standardizer/local_client.py` 已经实现了：

- `map_columns(columns, task_type)`

但当前 `services/standardizer.py::map_columns()` 仍然只使用配置规则与 substring matching，**没有调用 local model**。

因此，column LoRA 虽然已经训练和部署就绪，但尚未进入当前主链路的 `FileAnalyzerTool -> UnifiedStandardizer.map_columns()` 路径。

### 3.8 从论文角度如何定义这条本地模型路线

如果要从论文角度提炼，可以这样定义：

> Emission Agent 在规则化执行侧标准化机制之上，进一步设计了一条轻量本地标准化模型路线：通过 Qwen-based causal LM 与 LoRA adapter，将 alias normalization 与 column mapping 转化为低成本、可替换、可本地部署的专用子模型任务。这使系统在保持主 Agent 结构稳定的前提下，获得了从静态规则向可学习标准化器扩展的能力。

但同时必须补上一句：

> 就当前 live code 而言，该本地模型路线已在 vehicle/pollutant fallback 中部分接入，而 column mapping adapter 仍处于“代码已具备、主链尚未调用”的阶段。

## 4. 综合评价与论文写作建议

### 4.1 你可以如何概括 Part 2 的核心贡献

这一部分最适合提炼成两个创新点：

#### 创新点 A：File-Driven Task Grounding

上传文件后，系统不是把文件当作被动附件，而是先将其转换成结构化任务锚点，再注入 LLM 上下文，显式驱动工具选择与参数澄清。

#### 创新点 B：Execution-Side Parameter Standardization

系统把“自然语言理解”与“严格参数约束”分成两层：LLM 负责理解与生成原始 tool arguments，Executor 负责透明标准化。这降低了主模型的 schema 负担，并提升了后端可执行性。

### 4.2 论文里建议如实保留的边界条件

以下几点不建议回避，反而适合写成“当前实现边界”：

1. `file_analyzer.py` 对 tabular file 的任务锚定主要依赖列名启发式，而不是数值统计或 end-to-end learned classifier。
2. 当前 execution-side standardization 直接覆盖的是 vehicle/pollutant，不包括 model year、season、road type 的自然语言标准化。
3. 本地标准化模型路线已经具备完整训练与部署支撑，但在新主链路中是部分接入状态。
4. `LOCAL_STANDARDIZER_MODEL/` 内部存在 3B/4B 文档与配置的不一致，需要在论文中统一术语。

### 4.3 一句话总括

从系统方法论看，Emission Agent 在“文件理解”和“参数标准化”两个传统上容易被混入 prompt 的问题上，都采取了更工程化的中间层设计：前者用 `FileAnalyzerTool` 把文件转成任务锚点，后者用 `ToolExecutor + UnifiedStandardizer` 把自然语言参数转成后端可执行的标准参数空间。这种设计使系统既保留了 LLM 的语义灵活性，又保证了 emission calculation pipeline 的结构化可执行性。
