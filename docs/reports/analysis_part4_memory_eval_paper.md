# Emission Agent 深度技术分析（第 4 部分）

本文档聚焦三部分内容：

1. `Memory / Synthesis / Payload` 的实际实现；
2. `evaluation/` 与 `tests/` 所反映的现有评估体系；
3. 面向 SCI 论文写作时仍缺失的实验、局限性与可发表化改进路径。

---

## 1. 三层记忆管理

### 1.1 总体结构

三层记忆架构由 [`core/memory.py`](core/memory.py) 的 `MemoryManager` 实现，代码注释中定义为：

1. `Working Memory`
2. `Fact Memory`
3. `Compressed Memory`

核心类与数据结构：

- `FactMemory`：结构化事实缓存
- `Turn`：一轮对话
- `MemoryManager`：统一调度、持久化、裁剪、压缩

### 1.2 Working Memory 的具体实现

#### 1.2.1 数据结构

`Working Memory` 以 `List[Turn]` 存在于 `self.working_memory` 中。`Turn` 定义为：

```python
@dataclass
class Turn:
    user: str
    assistant: str
    tool_calls: Optional[List[Dict]] = None
    timestamp: datetime = field(default_factory=datetime.now)
```

也就是说，单轮记忆中理论上保留：

- 用户原始消息
- 助手文本回复
- 该轮工具调用列表
- 时间戳

#### 1.2.2 容量限制与淘汰策略

`MemoryManager.MAX_WORKING_MEMORY_TURNS = 5`。

但要注意这里有三层不同的“窗口”：

1. **内存中保留窗口**
   - `get_working_memory()` 只返回最近 `5` 轮
2. **Assembler 注入窗口**
   - [`core/assembler.py`](core/assembler.py) 的 `ContextAssembler._format_working_memory()` 默认只取最近 `3` 轮
3. **持久化窗口**
   - `_save()` 时最多写盘最近 `10` 轮 `working_memory`

因此，Working Memory 的真实行为不是简单“保留 5 轮”，而是：

- 内存内部可能暂时超过 5 轮；
- prompt 注入只看最近 3 轮；
- 超过 10 轮时触发压缩。

#### 1.2.3 注入 prompt 时的裁剪逻辑

`ContextAssembler._format_working_memory()` 会进一步做两层裁剪：

1. 只保留最近 `max_turns=3`
2. 若超 token budget，则再退化为只保留最近 `1` 轮

同时，对 assistant 回复做字符级截断：

- `MAX_ASSISTANT_RESPONSE_CHARS = 300`

所以 Working Memory 对 LLM 的影响是“最近 1-3 轮对话摘要”，不是完整会话历史。

### 1.3 Fact Memory 的具体实现

#### 1.3.1 数据结构

`FactMemory` 是结构化 key-value 状态，字段如下：

```python
recent_vehicle: Optional[str]
recent_pollutants: List[str]
recent_year: Optional[int]
active_file: Optional[str]
file_analysis: Optional[Dict]
last_tool_name: Optional[str]
last_tool_summary: Optional[str]
last_tool_snapshot: Optional[Dict]
user_preferences: Dict
```

其中真正进入主链路、被 `get_fact_memory()` 返回的字段是：

- `recent_vehicle`
- `recent_pollutants`
- `recent_year`
- `active_file`
- `file_analysis`
- `last_tool_name`
- `last_tool_summary`
- `last_tool_snapshot`

`user_preferences` 虽然在 dataclass 中存在，但当前：

- 不会被 `get_fact_memory()` 返回
- 不会被 `_save()` 持久化
- 也不会被 `ContextAssembler` 注入 prompt

也就是说，`user_preferences` 目前是未接通的预留字段。

#### 1.3.2 更新机制

`MemoryManager.update()` 的流程：

```text
1. append Turn 到 working_memory
2. 如果本轮有 tool_calls:
     _extract_facts_from_tool_calls()
3. 如果有 file_path:
     active_file = file_path
     file_analysis = analysis
4. _detect_correction(user_message)
5. 若 working_memory 过长:
     _compress_old_memory()
6. _save()
```

`_extract_facts_from_tool_calls()` 只从 **成功** 的工具调用中提取事实，主要抽取：

- 车型：优先从 `arguments["vehicle_type"]`，否则从 `data.query_info.vehicle_type`
- 污染物：优先从 `arguments["pollutant(s)"]`
- 年份：优先从 `arguments["model_year"]`
- 最近工具名：`last_tool_name`
- 最近工具 summary：`last_tool_summary`
- 最近工具 snapshot：`last_tool_snapshot`

`last_tool_snapshot` 是一个压缩版结构化快照，只保存以下高价值字段：

- `query_info`
- `summary`
- `fleet_mix_fill`
- `download_file`
- `row_count`
- `columns`
- `task_type`
- `detected_type`

其设计目的是让 follow-up turn 能围绕“刚刚的结果”继续提问，而不必重新注入完整结果数组。

#### 1.3.3 recent pollutants 的容量限制

`_merge_recent_pollutants()` 使用“去重 + 头插 + 截断”的策略：

- 新 pollutant 插入列表头部
- 去重保留
- 最多保留最近 `5` 个

这是一个小而有效的 recency cache。

#### 1.3.4 用户纠错检测

`_detect_correction(user_message)` 是一个轻量 heuristic：

- 检测词：`不对 / 不是 / 应该是 / 我说的是 / 换成 / 改成`
- 如果命中，再用一个很小的车辆关键词表识别：
  - `小汽车`
  - `公交车`
  - `货车`
  - `轿车`
  - `客车`

这说明当前 correction handling 不是 LLM-based semantic correction，而是基于中文关键字的规则修正。

### 1.4 Compressed Memory 的具体实现

#### 1.4.1 数据结构

`Compressed Memory` 在代码中只是一个字符串：

```python
self.compressed_memory: str = ""
```

#### 1.4.2 触发条件

当 `len(self.working_memory) > MAX_WORKING_MEMORY_TURNS * 2`，即超过 `10` 轮时，触发 `_compress_old_memory()`。

#### 1.4.3 压缩逻辑

当前压缩策略非常简单：

1. 取旧轮次 `old_turns = self.working_memory[:-5]`
2. 遍历其中的 `tool_calls`
3. 生成文本摘要：

```text
- Called <tool_name> with <arguments>
```

4. 把这些摘要拼成 `compressed_memory`
5. `working_memory` 只保留最近 `5` 轮

也就是说，`Compressed Memory` 不是语义摘要，也不是 conversation summarization，而是“历史工具调用日志的文本压缩版”。

### 1.5 记忆如何影响后续 LLM 调用

这部分不在 `memory.py` 本身，而体现在 [`core/assembler.py`](core/assembler.py)。

#### 1.5.1 Fact Memory 的注入方式

`ContextAssembler.assemble()` 会先把 `fact_memory` 转成一段 system message：

```text
[Context from previous conversations]
Recent vehicle type: ...
Recent pollutants: ...
Recent model year: ...
Active file: ...
Cached file task_type: ...
Cached file rows: ...
Cached file columns: ...
Last successful tool: ...
Last tool summary: ...
Last tool snapshot: ...
```

这使得 LLM 在 follow-up turn 中能理解诸如：

- “换成 NOx 再算一次”
- “还是刚才那个文件”
- “把年份改成 2020”
- “导出刚才的结果”

#### 1.5.2 Working Memory 的注入方式

Working Memory 则被转成标准对话消息：

```python
[
  {"role": "user", "content": "..."},
  {"role": "assistant", "content": "..."},
  ...
]
```

因此，它对 LLM 的作用更偏 conversational continuity。

#### 1.5.3 File Memory 的注入方式

如果 `file_context` 存在，且 `enable_file_context_injection=True`，则 `ContextAssembler._format_file_context()` 会把文件摘要直接 prepend 到当前 user message 前面：

```text
Filename: ...
File path: ...
task_type: ...
Rows: ...
Columns: ...
Sample (first 2 rows): ...
```

这一步对文件驱动任务尤其关键，因为它把“文件已上传”从隐式环境状态提升为 prompt 中显式可见的信息。

#### 1.5.4 Compressed Memory 的现实边界

需要特别强调：

- `compressed_memory` 会被生成、保存、加载；
- 但当前 `ContextAssembler.assemble()` 并不会把 `compressed_memory` 注入 prompt。

所以在当前 live code 中，真正影响后续轮次 LLM 调用的是：

- `Fact Memory`
- `Working Memory`
- `File Context`

而不是完整的“三层全量参与”。

### 1.6 持久化机制

`MemoryManager._save()` 会把数据写到：

```text
data/sessions/history/{session_id}.json
```

持久化内容包括：

- `session_id`
- `fact_memory`
- `compressed_memory`
- 最近 `10` 轮 `working_memory`

值得注意的边界：

1. 保存 `working_memory` 时只持久化：
   - `user`
   - `assistant`
   - `timestamp`
2. 不保存 `tool_calls`
3. `_load()` 恢复时也只恢复 user/assistant 文本

因此，重启后：

- Working Memory 的文本延续性仍在；
- 但每轮详细的工具调用轨迹不会被恢复；
- 旧轮压缩时也无法再利用这些历史 turn 的 tool_calls。

### 1.7 【论文视角】这种设计对多轮排放分析对话的意义

对多轮排放分析场景而言，这套设计的价值主要体现在四点：

1. **参数延续**
   - `recent_vehicle / recent_pollutants / recent_year` 使 follow-up turn 可以省略重复参数。

2. **文件持续 grounding**
   - `active_file + file_analysis` 让用户可以自然地说“还是这个文件”“再算一次 PM2.5”。

3. **结果导向 follow-up**
   - `last_tool_summary + last_tool_snapshot` 让系统能围绕“上一轮已计算出的结果”继续解释、导出、修改参数。

4. **上下文成本控制**
   - 不把完整结果数组长期留在 prompt 中，而是用结构化 snapshot 和短窗口工作记忆维持对话连续性。

但从论文表达上必须诚实说明：

- 当前系统真正发挥作用的是 `Working + Fact` 两层；
- `Compressed Memory` 仍是未完全接线的设计雏形。

---

## 2. 结果合成与交付

### 2.1 `_synthesize_results` 的主逻辑

结果合成主入口在 [`core/router.py`](core/router.py) 的 `UnifiedRouter._synthesize_results()`，但大量逻辑已拆分到：

- [`core/router_synthesis_utils.py`](core/router_synthesis_utils.py)
- [`core/router_render_utils.py`](core/router_render_utils.py)

整体流程如下：

```text
tool_results
  -> _maybe_short_circuit_synthesis()
      -> query_knowledge 单工具成功: 直接返回 summary
      -> 任一工具失败: 用 deterministic fallback markdown
      -> 单工具成功且属于可渲染工具: 用 deterministic renderer
  -> 否则 build_synthesis_request()
      -> filter_results_for_synthesis()
      -> JSON 序列化
      -> 调用 synthesis LLM
      -> detect_hallucination_keywords()
```

### 2.2 短路合成策略（short-circuit synthesis）

`maybe_short_circuit_synthesis(tool_results)` 的设计动机是：

- 避免每次都再走一轮 synthesis LLM；
- 降低 latency 和 hallucination 风险；
- 对常见单工具结果使用确定性格式化。

短路规则包括：

1. **单个 `query_knowledge` 成功**
   - 直接返回工具 summary
   - 不再走 synthesis LLM

2. **任一工具失败**
   - 调用 `format_results_as_fallback(tool_results)`
   - 返回确定性 markdown，避免 LLM 在错误上下文下“润色”

3. **单工具成功**
   - 如果属于：
     - `query_emission_factors`
     - `calculate_micro_emission`
     - `calculate_macro_emission`
     - `analyze_file`
   - 则使用 `render_single_tool_success()`

因此，当前系统的大量常见交互实际上并不经过 synthesis LLM，而是 deterministic rendering。

### 2.3 结构化结果过滤

若需要真正调用 synthesis LLM，则先调用 `build_synthesis_request()`。

其内部先用 `filter_results_for_synthesis(tool_results)` 去掉大数组，只保留高价值字段：

- 对 `calculate_micro_emission` / `calculate_macro_emission`
  - `summary`
  - `num_points`
  - `total_emissions`
  - `total_distance_km`
  - `total_time_s`
  - `query_params`
  - `has_download_file`
- 对 `query_emission_factors`
  - `summary`
  - `data`
- 对 `analyze_file`
  - `file_type`
  - `columns`
  - `row_count`
  - `file_path`
- 对失败工具
  - `success=False`
  - `error`

这一步相当于 synthesis 前的 payload compaction。

### 2.4 synthesis LLM 的输入构造

`build_synthesis_request()` 会生成：

- `results_json`
- `system_prompt`
- `messages`

其中：

- `system_prompt = prompt_template.replace("{results}", results_json)`
- `messages = [{"role": "user", "content": last_user_message or "请总结计算结果"}]`

也就是说，synthesis 阶段看到的是：

1. 精简后的结构化 JSON
2. 最后一条用户消息

而不是完整多轮上下文。

这有利于降低 prompt 复杂度，但也限制了 synthesis 对长上下文细节的利用。

### 2.5 幻觉检测机制

在 synthesis LLM 返回文本后，router 会做一个非常轻量的 hallucination check：

- 关键词列表如：
  - `相当于`
  - `棵树`
  - `峰值出现在`
  - `空调导致`
  - `不完全燃烧`

然后调用 `detect_hallucination_keywords(content, keywords)`。

需要强调：

- 这是日志告警机制；
- 不会阻断返回；
- 也不做自动修正。

所以它更接近 engineering safety hint，而不是严格 hallucination guardrail。

### 2.6 结果渲染：如何把结构化数据呈现给用户

结果交付并不只发生在 router，还包括 API 层和 Web 层。

#### 2.6.1 Router 层：抽取结构化 payload

[`core/router_payload_utils.py`](core/router_payload_utils.py) 负责从 `tool_results` 中抽取：

- `chart_data`
- `table_data`
- `download_file`
- `map_data`

主要函数：

- `extract_chart_data()`
- `extract_table_data()`
- `extract_download_file()`
- `extract_map_data()`

其中有一个很重要的实现特点：

- 若工具自己没填 `chart_data/table_data`，router 会根据 `data` 做二次构造；
- 尤其是 `query_emission_factors` 的图表和表格是 payload utils 动态生成的，而不是工具直接返回的。

#### 2.6.2 API 层：JSON 与流式事件封装

[`api/routes.py`](api/routes.py) 提供两种交付路径：

1. `POST /api/chat`
   - 一次性返回 `ChatResponse`
2. `POST /api/chat/stream`
   - 逐步返回事件流

非流式模式下，API 会：

1. 从 `session.chat()` 拿到：
   - `text`
   - `chart_data`
   - `table_data`
   - `map_data`
   - `download_file`
2. 用 `normalize_download_file()` 生成下载元信息
3. 用 `attach_download_to_table_data()` 把下载链接绑定进 `table_data`
4. 推断 `data_type`：
   - `chart`
   - `table`
   - `map`
   - `table_and_map`
5. 保存到 `Session._history`

流式模式则把结果拆成事件类型：

- `status`
- `heartbeat`
- `text`
- `chart`
- `table`
- `map`
- `done`
- `error`

这使前端可以逐块渲染，而不是等完整 JSON。

#### 2.6.3 Web 层：四类结果组件

前端主要在 [`web/app.js`](web/app.js) 中完成渲染，核心函数包括：

- `addAssistantMessage()`
- `renderChart()`
- `renderTable()`
- `renderEmissionMap()`
- `initEmissionChart()`
- `initLeafletMap()`

四类数据对应的呈现方式：

1. **文本**
   - `marked` 渲染 markdown

2. **图表**
   - `ECharts`
   - 主要用于排放因子速度曲线

3. **表格**
   - preview rows + summary
   - 支持下载按钮

4. **地图**
   - `Leaflet`
   - 支持 GIS basemap 与 pollutant 切换

### 2.7 表格与下载文件交付

`extract_table_data()` 会把结构化计算结果转成前端统一表格格式：

```python
{
  "type": "...",
  "columns": [...],
  "preview_rows": [...],
  "total_rows": ...,
  "total_columns": ...,
  "summary": {...},
  "total_emissions": {...}
}
```

前端 `renderResultTable()` 会进一步：

1. 渲染 summary table
2. 渲染 detail preview table
3. 挂载 download button
4. 如果总行数超过预览上限，提示用户下载完整文件

下载文件 metadata 由 API 层统一标准化后注入：

```python
{
  "path": ...,
  "filename": ...,
  "file_id": ...,
  "message_id": ...,
  "url": ...
}
```

### 2.8 GIS 地图载荷的生成

GIS map 的生成分成后端和前端两段。

#### 2.8.1 后端 map payload 生成

地图载荷真正的来源是 [`tools/macro_emission.py`](tools/macro_emission.py) 的 `_build_map_data()`，但 router 通过 `extract_map_data()` 把它送出。

map payload 结构大致为：

```python
{
  "type": "macro_emission_map",
  "center": [...],
  "zoom": 12,
  "pollutant": "CO2",
  "unit": "kg/(h·km)",
  "color_scale": {
    "min": ...,
    "max": ...,
    "colors": [...]
  },
  "links": [
    {
      "link_id": ...,
      "geometry": [[lon, lat], ...],
      "emissions": {...},          # intensity
      "emission_rate": {...},      # g/(veh·km)
      "link_length_km": ...,
      "avg_speed_kph": ...,
      "traffic_flow_vph": ...
    }
  ]
}
```

后端会解析多种 geometry 表达：

- WKT `LINESTRING`
- GeoJSON 字符串
- 坐标数组
- 坐标串
- Shapefile 提取结果

#### 2.8.2 前端 GIS 渲染

前端 `renderEmissionMap(mapData, msgContainer)` 会：

1. 生成 pollutant selector
2. 生成 color legend
3. 创建 `Leaflet` 容器
4. 调用 `initLeafletMap(mapData, mapId, pollutant)`

`initLeafletMap()` 的实现特点：

- 优先请求 `/api/gis/basemap`
- 再请求 `/api/gis/roadnetwork`
- 若 basemap 失败则 fallback 到 `CartoDB Positron`
- emission layer 用 polyline 绘制
- line weight 根据 link 数量自适应
- 支持动态切换 pollutant，不重建整张地图，只更新 polyline 颜色与 popup

因此，GIS 结果不是简单的图片输出，而是带交互层的 payload-driven map view。

### 2.9 结果交付链路总结

整个交付链可以概括为：

```text
ToolResult
  -> Router synthesis / payload extraction
  -> API normalize_download_file + attach_download_to_table_data
  -> Session.save_turn()
  -> Web render text/chart/table/map
```

这是一个典型的“structured result first, natural language second”的 agent 交付模式。

---

## 3. 现有评估体系

### 3.1 evaluation 目录的整体结构

当前评估体系主要位于 [`evaluation/`](evaluation)：

- `eval_normalization.py`
- `eval_file_grounding.py`
- `eval_end2end.py`
- `eval_ablation.py`
- `run_smoke_suite.py`
- `utils.py`
- benchmark samples 与 example logs

README 已明确说明：

- 这是“engineering benchmark harness”
- 不是最终 paper package

这个定位非常重要。

### 3.2 目前有哪些评估维度

从现有 runner 看，项目已经具备 4 个维度：

1. **参数标准化**
   - `evaluation/eval_normalization.py`

2. **文件任务锚定 / 列映射**
   - `evaluation/eval_file_grounding.py`

3. **端到端执行**
   - `evaluation/eval_end2end.py`

4. **组件消融**
   - `evaluation/eval_ablation.py`

此外还有：

- `evaluation/human_compare/samples.csv`
  - 作为人工流程对比 scaffold
  - 尚未形成全自动实验

### 3.3 smoke suite 测试了什么

最小可复现入口是 [`evaluation/run_smoke_suite.py`](evaluation/run_smoke_suite.py)。

它顺序运行：

1. `run_normalization_evaluation(...)`
2. `run_file_grounding_evaluation(...)`
3. `run_end2end_evaluation(..., mode="tool")`

并输出：

```text
evaluation/logs/<run_name>/
  normalization/
  file_grounding/
  end2end/
  smoke_summary.json
```

默认配置：

- `enable_file_analyzer = True`
- `enable_file_context_injection = True`
- `enable_executor_standardization = True`
- `macro_column_mapping_modes = ("direct", "fuzzy")`
- `mode = "tool"`

特别注意 smoke suite 默认用 `direct,fuzzy`，故意绕开 AI-only macro mapping，使本地验证更稳。

### 3.4 normalization 评估实际测了什么

`eval_normalization.py` 直接评估 `ToolExecutor._standardize_arguments()`，并不是完整工具执行。

样本源：

- `evaluation/normalization/samples.jsonl`
- 当前样本数：`10`

每条样本包含：

- `tool_name`
- `raw_arguments`
- `expected_standardized`
- `focus_params`
- `expected_success`

输出指标：

- `sample_accuracy`
- `field_accuracy`
- `parameter_legal_rate`

其含义分别是：

- **sample_accuracy**
  - 整条样本的标准化结果是否与期望一致
- **field_accuracy**
  - 关注字段逐项 exact match 的比例
- **parameter_legal_rate**
  - 标准化后参数是否合法

额外日志中还会记录：

- `failure_type`
- `recoverability`

### 3.5 file_grounding 评估实际测了什么

`eval_file_grounding.py` 用于评估：

1. 文件任务类型识别
2. 列映射正确性
3. required field 检测
4. file context 注入一致性

样本源：

- `evaluation/file_tasks/samples.jsonl`
- 当前样本数：`10`

每条样本包含：

- `user_query`
- `file_path`
- `expected_task_type`
- `expected_tool_name`
- `expected_mapping`
- `expected_required_present`

输出指标：

- `routing_accuracy`
- `column_mapping_accuracy`
- `required_field_accuracy`
- `file_context_injection_consistency`

但这里需要指出一个关键事实：

- 这个 runner 并没有真正跑 router 里的 LLM tool selection；
- 它是直接调用 `FileAnalyzerTool`、`MacroExcelHandler`、`MicroExcelHandler` 和 `ContextAssembler`。

因此这里测的是 **file grounding subsystem**，不是完整 agent routing。

### 3.6 end-to-end 评估实际测了什么

`eval_end2end.py` 支持两种模式：

1. `mode="tool"`
2. `mode="router"`

默认 smoke suite 使用 `tool` 模式。

样本源：

- `evaluation/end2end/samples.jsonl`
- 当前样本数：`10`

每条样本包含：

- `user_query`
- `file_path`
- `expected_tool_name`
- `tool_arguments`
- `expected_success`
- `expected_outputs`

输出指标：

- `tool_call_success_rate`
- `route_accuracy`
- `end2end_completion_rate`
- `average_interaction_turns`
- `skipped_samples`

#### 3.6.1 `tool` 模式的真实含义

`tool` 模式下，runner 直接调用：

```python
executor.execute(
    tool_name=sample["expected_tool_name"],
    arguments=sample["tool_arguments"],
    file_path=...
)
```

所以它绕过了 LLM routing 本身。

这意味着：

- `tool_call_success_rate` 是工具执行成功率；
- `route_accuracy` 在 tool 模式下基本是“按 expected_tool_name 直接执行”的结果，不是模型选路能力。

换言之，`tool` 模式更准确的名称应该是：

- **grounded execution benchmark**

而不是完整的 agent routing benchmark。

#### 3.6.2 `router` 模式

`router` 模式才会真正调用 `UnifiedRouter.chat(...)`。

但 README 也明确建议：

- router mode 用于故意测试完整 chat routing loop；
- 本地 benchmarking 更推荐 tool mode。

这表明当前项目默认把 router mode 视为“更接近线上、更依赖 LLM、更不稳定”的路径。

### 3.7 ablation 测了什么

`eval_ablation.py` 定义了 4 个 baseline / ablation：

1. `full_system`
2. `no_file_awareness`
3. `no_executor_standardization`
4. `macro_rule_only`

对应配置维度包括：

- `enable_file_analyzer`
- `enable_file_context_injection`
- `enable_executor_standardization`
- `macro_column_mapping_modes`
- `mode`
- `only_task`

这说明项目已经具备较初步的模块消融实验骨架。

### 3.8 已有 smoke artifact 反映了什么

仓库中附带了示例产物：

- `evaluation/logs/_smoke_normalization/normalization_metrics.json`
- `evaluation/logs/_smoke_file_grounding/file_grounding_metrics.json`
- `evaluation/logs/_smoke_end2end/end2end_metrics.json`
- `evaluation/logs/_smoke_ablation/ablation_summary.json`

README 已强调这些只是 **reference outputs**，不是当前代码事实的唯一来源。但它们仍能说明评估框架目前关注的方向和暴露出的薄弱点。

示例 smoke 指标如下：

| 任务 | 样本数 | 关键指标 |
|---|---:|---|
| normalization | 10 | `sample_accuracy = 0.10`, `field_accuracy = 0.6786`, `parameter_legal_rate = 0.20` |
| file_grounding | 10 | `routing_accuracy = 0.90`, `column_mapping_accuracy = 1.00`, `required_field_accuracy = 0.80` |
| end2end(tool) | 10 | `tool_call_success_rate = 1.00`, `route_accuracy = 1.00`, `end2end_completion_rate = 1.00`, `average_interaction_turns = 1.00` |

这些结果非常有启发性：

1. **标准化层明显是短板**
   - sample-level 精确命中率很低
2. **文件 grounding 的列映射能力相对强**
   - column mapping accuracy 达到 1.0
3. **tool-mode end2end 几乎全通**
   - 说明 execution pipeline 本身较稳定
   - 但也说明该 benchmark 对 routing 的考察有限

示例 ablation 中最有价值的两个观察：

1. `no_file_awareness`
   - `file_grounding.routing_accuracy = 0.0`
   - `required_field_accuracy = 0.0`
2. `no_executor_standardization`
   - `normalization.sample_accuracy = 0.0`
   - `end2end_completion_rate = 0.4`

这已经为论文中的 component importance 提供了定性证据，但还不足以形成严谨实验结论。

### 3.9 tests/ 目录下的回归测试覆盖了什么

`tests/` 目录目前更像工程回归套件，而不是 paper benchmark。

覆盖点包括：

1. **计算引擎**
   - [`tests/test_calculators.py`](tests/test_calculators.py)
   - 覆盖 `VSP`、micro、macro、emission factors

2. **标准化层**
   - [`tests/test_standardizer.py`](tests/test_standardizer.py)
   - vehicle / pollutant / column mapping 的规则层验证

3. **Router helper contracts**
   - [`tests/test_router_contracts.py`](tests/test_router_contracts.py)
   - memory compaction、render、payload、synthesis helper 的兼容性测试

4. **API contract**
   - [`tests/test_api_route_contracts.py`](tests/test_api_route_contracts.py)
   - health/test route、file preview、session history backfill

5. **API utility**
   - [`tests/test_api_chart_utils.py`](tests/test_api_chart_utils.py)
   - [`tests/test_api_response_utils.py`](tests/test_api_response_utils.py)

6. **配置与鉴权**
   - [`tests/test_config.py`](tests/test_config.py)

7. **文件读取**
   - [`tests/test_micro_excel_handler.py`](tests/test_micro_excel_handler.py)

8. **Smoke suite wrapper**
   - [`tests/test_smoke_suite.py`](tests/test_smoke_suite.py)

9. **Phase 1B 整理兼容性**
   - [`tests/test_phase1b_consolidation.py`](tests/test_phase1b_consolidation.py)

### 3.10 回归测试尚未覆盖的部分

从当前测试分布看，仍然存在明显空白：

1. `MemoryManager` 本体几乎没有直接测试
2. `SessionManager` 的并发、持久化一致性没有专门测试
3. `query_knowledge` 的检索效果没有自动化质量测试
4. `router` live LLM mode 没有系统性的 contract test
5. Web 前端 JS 没有自动化 UI 测试
6. GIS basemap / roadnetwork / map switching 没有集成回归

---

## 4. 面向论文的实验差距分析

这一部分是最关键的。当前代码已经具备工程验证框架，但距离 SCI 论文级实验还差至少 8 类补充设计。

### 4.1 a) 端到端任务完成评估

#### 4.1.1 现状问题

现有 `end2end` 默认是 `tool` 模式，直接指定 `expected_tool_name`，所以：

- 它主要测“工具执行正确性”
- 不能充分测“agent 是否会选对工具、问对澄清问题、正确使用记忆”

#### 4.1.2 论文需要的 benchmark 设计

建议构建一个真正的 **task-oriented benchmark**，覆盖至少 5 类任务：

1. 排放因子查询
2. 微观轨迹文件计算
3. 宏观路段文件计算
4. 知识检索 + 计算联动
5. 多轮 follow-up 修改参数任务

每个样本建议包含：

- `user_query`
- `optional_file`
- `gold_tool_sequence`
- `gold_final_parameters`
- `gold_expected_outputs`
- `gold_success_criteria`

其中 `gold_tool_sequence` 不一定要求完全匹配，但可用于 route-level analysis。

#### 4.1.3 推荐指标

至少报告：

- `Task Success Rate`
- `Tool Selection Accuracy`
- `Parameter Match Rate`
- `Output Completeness`
- `Average Turns`
- `Latency`
- `Need-for-Clarification Rate`

对于 end-to-end 成功，建议定义成多条件：

```text
成功 = 选对任务 + 参数可执行 + 输出完整 + 与 gold 误差在容忍范围内
```

### 4.2 b) 文件驱动任务锚定的准确率

#### 4.2.1 现状问题

当前 `file_grounding` benchmark 只有 10 个样本，且 mostly clean。

#### 4.2.2 benchmark 应如何构建

建议构建文件级 benchmark，至少按以下维度分层：

1. **任务类型**
   - micro
   - macro
   - ambiguous
   - unsupported

2. **语言**
   - English
   - Chinese
   - mixed-language headers

3. **列规范程度**
   - exact match
   - fuzzy alias
   - semantic paraphrase
   - noisy columns

4. **文件格式**
   - CSV
   - XLSX
   - ZIP+Shapefile

5. **信息完整度**
   - required complete
   - partially missing
   - misleading columns

每个文件需要人工标注：

- `gold_task_type`
- `gold_required_present`
- `gold_column_mapping`

#### 4.2.3 推荐指标

- `Task Type Accuracy`
- `Macro/Micro F1`
- `Required Field Detection Accuracy`
- `Column Mapping Exact Match`
- `Confidence Calibration`
  - 例如按 `confidence` 分桶看正确率

还建议给出 confusion matrix，因为：

- `micro -> macro`
- `macro -> unknown`
- `macro_cn_fleet -> unknown`

这类错误具有不同工程含义。

### 4.3 c) 参数标准化准确率

#### 4.3.1 现状问题

当前标准化 benchmark 已经存在，但规模过小，而且 ground truth 只覆盖少量 alias。

同时，live code 里标准化主要覆盖：

- `vehicle_type`
- `pollutant`
- `pollutants`

而不是完整覆盖：

- `season`
- `road_type`
- `model_year` 的自然语言表达

#### 4.3.2 ground truth 应如何构造

建议构建标准化数据集时分四层：

1. **Vehicle aliases**
   - 中文别名
   - 英文别名
   - 缩写
   - 错拼
   - 口语化名称

2. **Pollutant aliases**
   - 中文全称
   - 英文大小写变化
   - PM 细分写法

3. **Season / road type**
   - `冬天 / winter / cold season`
   - `高速 / expressway / freeway`

4. **Difficult negatives**
   - 模糊输入
   - 非法输入
   - 多义输入

每条样本应有：

- `raw_expression`
- `gold_standard`
- `legal/illegal`
- `confidence_needed`

#### 4.3.3 推荐指标

- `Exact Match Accuracy`
- `Top-k Suggestion Recall`
- `Legality Rate`
- `Abstention Accuracy`
  - 遇到未知输入时能否正确拒识
- `Latency`
- `Cost`

论文里尤其建议把标准化错误分成：

- `wrong normalization`
- `abstain when should match`
- `accept illegal`

### 4.4 d) 消融实验建议

现有 ablation 已经有雏形，但论文建议扩展为更完整的矩阵：

1. `Full System`
2. `- FileAnalyzer`
3. `- FileContextInjection`
4. `- ExecutorStandardization`
5. `- FactMemory`
6. `- WorkingMemory`
7. `- KnowledgeTool`
8. `- Deterministic short-circuit synthesis`

#### 4.4.1 需要观测的指标

对每种 ablation，至少测：

- end-to-end task success
- route accuracy
- average interaction turns
- clarification count
- latency
- user burden

#### 4.4.2 当前现有 ablation 的局限

当前 `eval_ablation.py` 的局限在于：

- end2end 默认仍是 `tool` 模式
- 因此对 routing / memory 的 ablation 不够敏感

例如 checked-in artifacts 中：

- `no_file_awareness` 的 `end2end_completion_rate` 仍然是 `1.0`

这并不能说明 file analyzer 对真实端到端无用，只能说明 **当前 tool-mode benchmark 已经把 tool 选定了**。

### 4.5 e) Baseline 对比建议

论文建议至少对比 4 类 baseline：

#### 4.5.1 Direct LLM baseline

即不使用 agent orchestration，只给模型自然语言问题和文件描述，让它直接回答。

可测：

- 是否能正确判断任务类型
- 是否能输出可执行参数
- 是否会 hallucinate

#### 4.5.2 No-agent manual pipeline baseline

即人工流程：

1. 用户自己看文件列名
2. 手工决定 micro / macro
3. 手工补车型、污染物、年份参数
4. 再调用计算器

这类 baseline 非常适合展示：

- 交互负担
- 准备时间
- 参数出错率

`evaluation/human_compare/samples.csv` 已经为此提供了 scaffold。

#### 4.5.3 Tool-only baseline

即保留计算工具，但去掉：

- file analyzer
- standardizer
- memory

让用户必须输入标准参数。

这是最适合展示 agent 增益的 engineering baseline。

#### 4.5.4 Generic agent framework baseline

可以用统一 prompt 和统一工具集，在通用 agent orchestration 模式下对比，例如：

- 只有 ReAct-style prompting
- 没有 execution-side standardization
- 没有 file grounding

这里不必执着于某个外部框架品牌，重点是对比 **设计思想**：

- “有 specialized grounding/standardization/memory 的 agent”
vs
- “通用 tool-calling LLM”

### 4.6 f) 交互负担评估

这是 Emission Agent 很适合做的论文亮点。

#### 4.6.1 可量化指标

建议统计：

- `Average Interaction Turns`
- `Clarification Turns`
- `Manual Parameter Mentions`
- `Manual File Explanation Tokens`
- `Time to First Valid Result`
- `Time to Final Downloadable Result`

#### 4.6.2 构造方法

可以设计 paired study：

- 条件 A：使用 Emission Agent
- 条件 B：使用 direct LLM / manual pipeline

对同一任务记录：

- 用户需要额外补充多少次车型/污染物/年份
- 是否需要打开文件自行解释列含义
- 完成任务所需总轮次

这类指标能很好支撑“系统减少用户交互负担”的论文主张。

### 4.7 g) 4B vs 云端模型对比

这是标准化部分非常适合做的实验。

#### 4.7.1 推荐对比对象

1. 本地轻量标准化模型
2. 云端 API 标准化模型
3. 纯规则 / fuzzy baseline

#### 4.7.2 推荐对比指标

- `Exact Match Accuracy`
- `Legality Rate`
- `Abstention Quality`
- `Latency (p50 / p95)`
- `GPU / CPU cost`
- `API cost`
- `Offline availability`

#### 4.7.3 论文可讨论的 trade-off

- 本地 4B / 3B 路线：
  - 隐私好
  - 可离线
  - 延迟可控
  - 但精度可能低于云端
- 云端模型：
  - 泛化好
  - 对长尾 alias 更强
  - 但有网络与成本依赖

建议把对比做成两个维度的 Pareto 图：

- `accuracy`
- `latency/cost`

### 4.8 h) 可能的案例分析（Case Study）

建议至少准备 4 个 case study。

#### Case 1: 中文路段 + 车型构成文件

文件示例：

- `evaluation/file_tasks/data/macro_cn_fleet.csv`

价值：

- 展示中文列名、车队组成列、文件锚定与列映射的难点
- 当前代码里它还能暴露 `task_type = unknown` 但后续 macro mapping 仍成功的边界情况

#### Case 2: 非标准英文列名的宏观路段文件

文件示例：

- `evaluation/file_tasks/data/macro_fuzzy.csv`

价值：

- 展示 `direct + ai + fuzzy` 列语义映射能力
- 很适合突出 file-driven task grounding

#### Case 3: 几何路网文件 + GIS map 输出

文件示例：

- `test_data/test_6links.xlsx`

价值：

- 展示结构化排放结果如何直接转成 GIS 地图
- 体现“分析 + 可视化交付”一体化

#### Case 4: 多轮跟进修改参数

对话示例：

1. “计算这个文件的 CO2 排放”
2. “换成 NOx”
3. “年份改成 2020”
4. “把结果导出”

价值：

- 最能展示 `Fact Memory + Working Memory` 的作用
- 也是 direct LLM 最容易退化的场景

---

## 5. 系统局限性（Limitations）

这一节建议在论文里诚实呈现，因为当前代码已经暴露出若干非常具体的工程边界。

### 5.1 记忆系统的局限

1. **Compressed Memory 尚未真正参与 prompt**
   - `compressed_memory` 会生成和持久化，但 `ContextAssembler` 不使用它。

2. **Working Memory 恢复不完整**
   - 重载后只恢复 user/assistant 文本，不恢复 tool_calls。

3. **Correction handling 很弱**
   - `_detect_correction()` 是中文关键字 heuristic，不是通用语义纠错。

4. **user_preferences 未接通**
   - 数据结构里有，但主链路未使用。

### 5.2 会话与记忆持久化的局限

当前系统实际上有两套存储：

1. `SessionManager`
   - 用于前端会话历史
   - 路径：`data/sessions/{user_id}/...`
2. `MemoryManager`
   - 用于 router 记忆
   - 路径：`data/sessions/history/{session_id}.json`

这带来两个问题：

1. **双轨存储**
   - UI history 与 router memory 不是同一个对象源
2. **用户隔离不一致**
   - `SessionManager` 按 user_id 分目录
   - `MemoryManager` 只按 session_id 全局存储

从论文角度，这意味着当前系统在 memory/session consistency 上仍偏 engineering prototype。

### 5.3 多工具协作的局限

当前 router 支持多工具顺序执行，但：

- success 后不会继续 re-plan
- 只有出错时才回灌上下文再问 LLM

因此，它不是完整的 multi-step planner。

这意味着：

- `query_knowledge -> calculate_*` 更适合跨轮
- 同轮强依赖工具链条的能力仍有限

### 5.4 标准化与 grounding 的局限

1. **执行侧标准化覆盖面有限**
   - 主要覆盖 `vehicle_type`、`pollutant(s)`
   - `season / road_type / model_year` 的自然语言标准化并未完整统一接入

2. **文件任务识别 heuristic 较脆弱**
   - 对中文宏观文件 `macro_cn_fleet.csv` 会出现 `task_type = unknown`

3. **微观列映射仍偏规则化**
   - `skills/micro_emission/excel_handler.py` 没有真正使用 LLM 映射

### 5.5 合成与交付层的局限

1. **payload extraction 只取第一个匹配结果**
   - `extract_chart_data()` / `extract_table_data()` / `extract_map_data()` 返回 first match
   - 多工具多 payload 的展示能力有限

2. **hallucination detection 只是告警**
   - 不做拦截，也不自动修正

3. **synthesis LLM 看到的是压缩结果**
   - 对复杂多轮上下文的理解有限

### 5.6 评估体系的局限

1. benchmark 样本数很小
   - 目前三个主 benchmark 都只有 `10` 个样本

2. `tool` 模式 end2end 对 routing 不敏感

3. 缺少真实用户研究

4. 缺少 latency / cost / robustness 的系统性报告

5. `human_compare` 仍只是 scaffold，不是自动实验

### 5.7 Web 与部署层的局限

1. 前端依赖 CDN：
   - Tailwind
   - ECharts
   - Leaflet

2. 没有自动化前端测试

3. GIS basemap / roadnetwork 依赖额外 API 端点，复现门槛高于纯文本工具链

4. guest mode 的“非持久化”主要是前端 `sessionStorage` 级别语义，不是严格服务端无状态

### 5.8 未来工作方向

结合以上局限，论文中可以自然引出未来工作：

1. 把 `Compressed Memory` 真正接入 assembler
2. 统一 session history 与 router memory 的存储模型
3. 把 success-driven multi-tool replanning 接入 router
4. 扩展标准化对象到 `season / road_type / year expression`
5. 为微观文件引入真正的 semantic column grounding
6. 扩大 benchmark 规模并引入 human study
7. 系统评估本地模型 vs 云端模型的 accuracy-latency-cost trade-off
8. 增加不确定性与失败恢复机制研究

---

## 总结：面向论文写作的核心判断

从整个项目代码看，Emission Agent 已经具备一篇论文的雏形，尤其有三项可以被明确包装为研究贡献：

1. **文件驱动任务锚定**
   - 文件不再是被动附件，而是主动参与任务识别和工具路由

2. **执行侧参数标准化**
   - 把 LLM 的自然语言输出与受控计算参数空间解耦

3. **双尺度排放计算 + 可视化交付**
   - 同时支持 `Emission Factors / Micro / Macro / GIS`

但如果要写成 SCI 论文，当前最大的短板不是系统功能，而是：

- benchmark 太小；
- end-to-end 评估仍偏 engineering；
- 多轮记忆与多工具协作的实验论证不足；
- 4B 本地模型与云端模型的系统性对比尚未形成。

换句话说，系统本体已经能支撑论文，但实验部分还需要从“可运行验证”提升到“可发表证据”。
