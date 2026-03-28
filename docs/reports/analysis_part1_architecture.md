# Emission Agent 技术分析（Part 1：系统架构与核心数据流）

本文基于以下文件的顺序阅读与交叉核对完成：`README.md`、`ENGINEERING_STATUS.md`、`CURRENT_BASELINE.md`、`docs/ARCHITECTURE.md`、`config.py`、`config/prompts/core.yaml`、`config/unified_mappings.yaml`、`run_api.py`、`main.py`、`api/main.py`、`api/routes.py`、`core/router.py`、`core/assembler.py`，并补充核对了请求主链路直接依赖的 `api/session.py`、`core/executor.py`、`core/memory.py`、`services/llm_client.py`、`services/config_loader.py`、`tools/definitions.py`、`tools/registry.py` 与核心 tool/calculator 类。

结论先行：该项目当前采用一种典型的 **AI-first + Tool Use** 架构。系统并没有独立的 planning layer，而是由 `UnifiedRouter` 直接驱动一次 `LLM function calling -> tool execution -> result synthesis` 的闭环；同时通过 `MemoryManager` 和 `ContextAssembler` 为多轮对话提供上下文连续性。

## 1. 系统架构总览

### 1.1 分层架构

从运行时角度，当前系统可以抽象为 5 个主层级和 2 个横切支撑层：

```text
入口层
  -> API/CLI 接入层
  -> 核心路由层
  -> 工具执行层
  -> 计算引擎层

横切支撑层
  -> 配置与 Prompt 层
  -> Memory / Session / LLM Service 层
```

如果按代码目录展开，可以表示为：

```text
run_api.py / main.py
  -> api/main.py + api/routes.py + api/session.py
    -> core/router.py (UnifiedRouter)
      -> core/assembler.py + core/memory.py
      -> core/executor.py
        -> tools/registry.py + tools/definitions.py + tools/*.py
          -> calculators/*.py
      -> services/llm_client.py
```

### 1.2 各层职责与关键类/函数

| 层级 | 关键文件 | 关键类/函数 | 职责 |
|---|---|---|---|
| 入口层 | `run_api.py`、`main.py` | `uvicorn.run(...)`、`chat()`、`health()`、`tools_list()` | 提供本地 FastAPI/Web 启动入口和 CLI 调试入口 |
| API 层 | `api/main.py`、`api/routes.py` | `app = FastAPI(...)`、`chat()`、`chat_stream()`、`preview_file()` | 接收 HTTP 请求、保存上传文件、维护 session、组装 API 响应 |
| 会话层 | `api/session.py` | `Session`、`SessionManager`、`SessionRegistry`、`Session.chat()` | 在 API 层和 `UnifiedRouter` 之间做会话隔离、Router 懒加载和历史持久化 |
| 核心路由层 | `core/router.py` | `UnifiedRouter.chat()`、`_process_response()`、`_analyze_file()`、`_synthesize_results()` | 协调 file analysis、context assembly、LLM tool calling、tool execution、synthesis、memory update |
| 上下文组装层 | `core/assembler.py` | `ContextAssembler.assemble()`、`_format_fact_memory()`、`_format_working_memory()`、`_format_file_context()` | 为 LLM 构建最终 `system + tools + messages` 输入 |
| 工具执行层 | `core/executor.py`、`tools/registry.py`、`tools/definitions.py` | `ToolExecutor.execute()`、`_standardize_arguments()`、`init_tools()`、`TOOL_DEFINITIONS` | 根据 LLM 产生的 tool call 执行对应工具，并做透明参数标准化 |
| 工具实现层 | `tools/emission_factors.py`、`tools/micro_emission.py`、`tools/macro_emission.py`、`tools/file_analyzer.py`、`tools/knowledge.py` | `EmissionFactorsTool.execute()`、`MicroEmissionTool.execute()`、`MacroEmissionTool.execute()`、`FileAnalyzerTool.execute()`、`KnowledgeTool.execute()` | 面向 Router 的业务工具封装，负责参数校验、文件读写、结果格式化 |
| 计算引擎层 | `calculators/emission_factors.py`、`calculators/micro_emission.py`、`calculators/macro_emission.py`、`calculators/vsp.py` | `EmissionFactorCalculator.query()`、`MicroEmissionCalculator.calculate()`、`MacroEmissionCalculator.calculate()`、`VSPCalculator.calculate_trajectory_vsp()` | 进行 MOVES/VSP 相关的核心排放计算 |
| 配置与 Prompt 层 | `config.py`、`config/prompts/core.yaml`、`config/unified_mappings.yaml`、`services/config_loader.py` | `Config`、`LLMAssignment`、`get_config()`、`ConfigLoader.load_prompts()`、`ConfigLoader.load_tool_definitions()` | 管理模型分配、运行开关、Prompt、车辆/污染物统一映射 |
| LLM / Memory 支撑层 | `services/llm_client.py`、`core/memory.py` | `LLMClientService.chat_with_tools()`、`LLMClientService.chat()`、`MemoryManager.update()` | 处理 function calling、普通 synthesis 调用、多轮记忆与事实抽取 |

### 1.3 当前系统中的核心对象

1. `UnifiedRouter`
当前运行时真正的中心协调器。所有自然语言请求最终都会流向这里。

2. `ContextAssembler`
只负责“组装信息”，不负责“做决策”。它把 system prompt、tool definitions、历史对话、fact memory、file context 组合成 LLM 输入。

3. `ToolExecutor`
执行 Router 选中的工具，并在执行前透明完成 `vehicle_type`、`pollutant(s)` 的标准化。

4. `MemoryManager`
保存最近多轮对话和结构化事实，使 follow-up query 能引用“刚才那个文件”“改成公交车”“沿用上一轮污染物”等上下文。

5. `LLMClientService`
封装 OpenAI-compatible chat completion；`chat_with_tools()` 用于 function calling，`chat()` 用于 synthesis。

### 1.4 配置如何作用于架构

`config.py` 中的 `Config` 会在系统启动或首次访问时初始化以下关键运行开关：

- `enable_file_analyzer`
- `enable_file_context_injection`
- `enable_executor_standardization`
- `macro_column_mapping_modes`
- `agent_llm` / `standardizer_llm` / `synthesis_llm` / `rag_refiner_llm`

其中：

- `config/prompts/core.yaml` 决定 Router 主 system prompt 的行为边界。
- `config/unified_mappings.yaml` 提供车辆类型、污染物、VSP 参数等统一映射基础。
- `services/config_loader.py` 负责将 Prompt 和 `TOOL_DEFINITIONS` 注入 `ContextAssembler`。

## 2. 请求完整生命周期

这里以典型请求“上传文件后发送：`计算这个文件的CO2排放`”为例，按代码调用顺序说明完整链路。

### 2.1 总调用链

```text
HTTP POST /api/chat
  -> api/routes.py::chat()
    -> api/session.py::SessionRegistry.get()
    -> api/session.py::SessionManager.get_or_create_session()
    -> api/session.py::Session.chat()
      -> core/router.py::UnifiedRouter.chat()
        -> core/router.py::_analyze_file() [optional]
          -> core/executor.py::ToolExecutor.execute("analyze_file")
          -> tools/file_analyzer.py::FileAnalyzerTool.execute()
        -> core/assembler.py::ContextAssembler.assemble()
        -> services/llm_client.py::LLMClientService.chat_with_tools()
        -> core/router.py::_process_response()
          -> core/executor.py::ToolExecutor.execute(...)
            -> tools/*.py::execute()
              -> calculators/*.py::{query|calculate}()
          -> core/router.py::_synthesize_results()
            -> services/llm_client.py::LLMClientService.chat() [conditional]
        -> core/memory.py::MemoryManager.update()
    -> api/routes.py::ChatResponse(...)
    -> api/session.py::Session.save_turn()
```

### 2.2 分步说明

#### Step 1. 入口层接收请求

- 本地服务通常由 `run_api.py` 启动，它通过 `uvicorn.run("api.main:app", ...)` 启动 FastAPI。
- `api/main.py` 创建 `FastAPI` 实例，注册 middleware，并通过 `app.include_router(router, prefix="/api")` 挂载 `api/routes.py`。

#### Step 2. API 层解析表单与文件

在 `api/routes.py::chat()` 中：

1. 从 multipart form 中读取：
   - `message`
   - `session_id`
   - `file`
2. 调用 `get_user_id(request)`：
   - 优先读 JWT `Authorization: Bearer ...`
   - 否则读 `X-User-ID`
   - 再否则生成 guest UUID
3. 通过 `SessionRegistry.get(user_id)` 获取用户级 `SessionManager`
4. 通过 `SessionManager.get_or_create_session(session_id)` 获取或新建对话 `Session`

如果上传了文件，`chat()` 会先把文件保存到：

```text
/tmp/emission_agent/{session_id}_input{suffix}
```

然后在用户消息末尾追加一段明确提示：

```text
文件已上传，路径: <input_file_path>
请使用 input_file 参数处理此文件。
```

这一步很重要，因为它把前端上传的 binary file 转换成了 Router/LLM 能感知的 `file_path` 语义。

#### Step 3. Session 层转发到 Router

`api/session.py::Session.chat()` 做的事情很少，但作用关键：

- 通过 `Session.router` 懒加载 `UnifiedRouter(session_id=self.session_id)`
- 调用 `await self.router.chat(user_message=message, file_path=file_path)`
- 把 `RouterResponse` 转成 API 层更容易消费的 dict

这意味着 API 层并不直接操作 Router，而是通过 `Session` 做了一层会话封装。

#### Step 4. Router 先处理文件上下文

`core/router.py::UnifiedRouter.chat()` 的第一阶段是 file analysis：

```python
cached = self.memory.get_fact_memory().get("file_analysis")
current_mtime = os.path.getmtime(file_path)
cache_valid = (
    cached
    and cached["file_path"] == file_path
    and cached["file_mtime"] == current_mtime
)
```

逻辑分支如下：

1. `enable_file_analyzer=False`
直接构造一个最小 file context，仅保留文件名、路径和空 task 信息。

2. 有缓存且 `file_path + file_mtime` 一致
复用上一次 `file_analysis`。

3. 无缓存或文件内容已变
调用 `UnifiedRouter._analyze_file()`。

而 `_analyze_file()` 又会转发到：

```text
ToolExecutor.execute("analyze_file", {"file_path": file_path})
  -> FileAnalyzerTool.execute(file_path)
```

`FileAnalyzerTool` 会读取 CSV / Excel / ZIP，输出：

- `filename`
- `row_count`
- `columns`
- `task_type`
- `confidence`
- `micro_mapping`
- `macro_mapping`
- `sample_rows`

其中 `task_type` 是后续 Router 决策的关键。

#### Step 5. Assembler 构造 LLM 输入

`core/assembler.py::ContextAssembler.assemble()` 会把以下内容组合成一个 `AssembledContext`：

1. `system_prompt`
来自 `config/prompts/core.yaml`，强调：
- 不要伪造数据
- 参数不足时先澄清
- 若 `task_type` 已明确，则不要再问“宏观还是微观”
- 微观计算不能猜测 `vehicle_type`

2. `tools`
来自 `tools/definitions.py::TOOL_DEFINITIONS`，采用 OpenAI function calling schema。

3. `messages`
按下面顺序生成：
- fact memory 的 system message
- recent working memory 的 user/assistant 对
- 当前 user message

如果存在文件且启用了 `enable_file_context_injection`，Assembler 并不会把文件信息单独放成一个 message，而是把 `file_summary` 直接 prepend 到当前 `user_message` 前面。

#### Step 6. LLM 决定是否调用工具

`UnifiedRouter.chat()` 随后调用：

```python
response = await self.llm.chat_with_tools(
    messages=context.messages,
    tools=context.tools,
    system=context.system_prompt
)
```

而 `services/llm_client.py::LLMClientService.chat_with_tools()` 最终执行的是 OpenAI-compatible 请求：

```python
cli.chat.completions.create(
    model=self.model,
    messages=full_messages,
    tools=tools,
    tool_choice="auto",
    ...
)
```

这意味着：

- 工具选择不是由 Python rule hard-code 决定
- 而是由 LLM 在 `tool_choice="auto"` 模式下，基于 prompt、history、file context、tool schema 自主选择

对示例请求而言，可能出现两种典型分支：

1. 若 `task_type == "macro_emission"`
LLM 很可能直接调用 `calculate_macro_emission`，参数中包含 `pollutants=["CO2"]` 和 `file_path`。

2. 若 `task_type == "micro_emission"`
LLM 会知道应该走 `calculate_micro_emission`，但该工具需要 `vehicle_type`。若用户未提供车型，系统 prompt 会约束 LLM 先发起 clarification，而不是盲算。

#### Step 7. Router 处理 tool calls

`core/router.py::_process_response()` 是真正的 tool loop：

```python
if not response.tool_calls:
    return RouterResponse(text=response.content)

for tool_call in response.tool_calls:
    result = await self.executor.execute(
        tool_name=tool_call.name,
        arguments=tool_call.arguments,
        file_path=file_path
    )
```

这里有三个要点：

1. `UnifiedRouter` 一轮最多允许 `MAX_TOOL_CALLS_PER_TURN = 3`
防止无限循环。

2. `ToolExecutor` 会自动把 API 层传来的 `file_path` 注入 tool arguments
即使 LLM 漏传，也可补齐。

3. 若工具执行失败，Router 不会立即报错退出，而是把错误回填给 LLM 进行一次自然重试。

#### Step 8. Executor 完成透明参数标准化

`core/executor.py::ToolExecutor.execute()` 的执行顺序是：

```text
get tool from registry
-> standardize arguments
-> auto inject file_path
-> await tool.execute(**standardized_args)
-> convert ToolResult to dict
```

其中 `_standardize_arguments()` 会透明标准化：

- `vehicle_type`
- `pollutant`
- `pollutants`

也就是说，LLM 可以把用户原始表达如“公交车”“小汽车”“碳排放”直接传下去，Executor 再通过 `services.standardizer` 做统一映射。这是项目“transparent standardization”的关键实现点。

#### Step 9. Tool 层调用对应 Calculator

当前注册到 `ToolRegistry` 的工具包括：

- `query_emission_factors` -> `EmissionFactorsTool.execute()` -> `EmissionFactorCalculator.query()`
- `calculate_micro_emission` -> `MicroEmissionTool.execute()` -> `MicroEmissionCalculator.calculate()`
- `calculate_macro_emission` -> `MacroEmissionTool.execute()` -> `MacroEmissionCalculator.calculate()`
- `analyze_file` -> `FileAnalyzerTool.execute()`
- `query_knowledge` -> `KnowledgeTool.execute()`

其中三个主要计算链分别是：

1. 排放因子查询

```text
EmissionFactorsTool.execute()
  -> EmissionFactorCalculator.query(vehicle_type, pollutant, model_year, season, road_type)
```

2. 微观排放计算

```text
MicroEmissionTool.execute()
  -> 读取 trajectory_data / Excel
  -> MicroEmissionCalculator.calculate(...)
  -> VSPCalculator.calculate_trajectory_vsp(...)
```

3. 宏观排放计算

```text
MacroEmissionTool.execute()
  -> 读取 links_data / Excel / ZIP-Shapefile
  -> fleet_mix 填补与标准化
  -> MacroEmissionCalculator.calculate(...)
```

#### Step 10. 错误回填与自然重试

如果某个 tool result 带有 `error=True`，`_process_response()` 会：

1. 用 `_format_tool_errors()` 把错误整理为文本
2. 把原 assistant 的 tool call 记录追加进 `context.messages`
3. 再追加一条 `role="tool"` 的错误消息
4. 再次调用 `chat_with_tools()`

伪代码如下：

```python
if has_error and tool_call_count < MAX_TOOL_CALLS_PER_TURN - 1:
    context.messages += [
        assistant_message_with_tool_calls,
        tool_error_message,
    ]
    retry_response = await llm.chat_with_tools(...)
    return await _process_response(retry_response, ..., tool_call_count + 1)
```

这体现了项目在 README 和 `docs/ARCHITECTURE.md` 中强调的“自然重试机制”，而不是单独的 rigid rule engine。

#### Step 11. 结果综合与前端 payload 提取

工具执行完成后，Router 调用 `UnifiedRouter._synthesize_results()`。

其逻辑并不是“必定再调一次 LLM”，而是：

1. 先执行 `_maybe_short_circuit_synthesis()`
2. 若满足单工具成功、知识检索直返、工具失败回退等条件，则直接用 deterministic renderer 返回文本
3. 否则才用 synthesis prompt 调 `LLMClientService.chat()`

随后，Router 使用以下 helper 提取前端可视化数据：

- `_extract_chart_data()`
- `_extract_table_data()`
- `_extract_map_data()`
- `_extract_download_file()`

最终形成 `RouterResponse`：

```python
RouterResponse(
    text=synthesis_text,
    chart_data=...,
    table_data=...,
    map_data=...,
    download_file=...,
    executed_tool_calls=...
)
```

#### Step 12. Memory 更新

`core/memory.py::MemoryManager.update()` 在每一轮结束后会：

1. 把当前 turn 写入 `working_memory`
2. 从成功的 `tool_calls` 中抽取结构化事实
3. 更新 `active_file` 和 `file_analysis`
4. 检测用户纠正表达，如“换成公交车”“改成货车”
5. 必要时压缩旧记忆
6. 写盘持久化

它抽取的关键信息包括：

- `recent_vehicle`
- `recent_pollutants`
- `recent_year`
- `active_file`
- `file_analysis`
- `last_tool_name`
- `last_tool_summary`
- `last_tool_snapshot`

#### Step 13. API 层返回响应并保存 UI 历史

返回 API 层后，`api/routes.py::chat()` 会继续做几件 UI/接口相关工作：

1. `normalize_download_file(...)`
2. 判断 `data_type` 属于 `chart/table/map/table_and_map`
3. `attach_download_to_table_data(...)`
4. 构造 `ChatResponse`
5. 调用 `session.save_turn(...)` 保存 UI 历史
6. `mgr.save_session()` 持久化 Session 元数据

因此，系统实际上维护了两类“历史”：

1. Router 级 memory
服务于后续 reasoning 和 prompt grounding。

2. API Session 级 `_history`
服务于 Web 前端历史渲染、下载按钮恢复、消息级回放。

### 2.3 生命周期伪代码

```python
async def api_chat(message, file):
    user_id = get_user_id(request)
    session = SessionRegistry.get(user_id).get_or_create_session(session_id)
    file_path = save_upload_if_needed(file)
    message = inject_file_hint(message, file_path)

    result = await session.chat(message, file_path)

    response = build_chat_response(result)
    session.save_turn(...)
    save_session_meta(...)
    return response


async def router_chat(user_message, file_path):
    file_context = cached_or_analyze_file(file_path)
    context = assembler.assemble(
        user_message=user_message,
        working_memory=memory.get_working_memory(),
        fact_memory=memory.get_fact_memory(),
        file_context=file_context
    )

    response = await llm.chat_with_tools(
        messages=context.messages,
        tools=context.tools,
        system=context.system_prompt
    )

    result = await process_response(response, context, file_path)
    memory.update(user_message, result.text, result.executed_tool_calls, file_path, file_context)
    return result
```

## 3. UnifiedRouter 核心逻辑

### 3.1 `UnifiedRouter` 的组成

`core/router.py::UnifiedRouter.__init__()` 在实例化时会绑定：

- `self.assembler = ContextAssembler()`
- `self.executor = ToolExecutor()`
- `self.memory = MemoryManager(session_id)`
- `self.llm = get_llm_client("agent", model="qwen-plus")`

从架构上看，它是一个 **Orchestrator**，而不是单纯 Router。

### 3.2 主方法 `chat()` 的决策流程

`UnifiedRouter.chat()` 可以概括为下面 5 步：

```text
1. 处理 file context
2. 组装 LLM context
3. 调用 LLM function calling
4. 执行 tool loop / synthesis
5. 更新 memory
```

更接近代码的伪代码如下：

```python
async def chat(user_message, file_path):
    if file_path:
        file_context = use_cache_or_analyze(file_path)

    context = assembler.assemble(
        user_message,
        working_memory=memory.get_working_memory(),
        fact_memory=memory.get_fact_memory(),
        file_context=file_context
    )

    response = await llm.chat_with_tools(
        messages=context.messages,
        tools=context.tools,
        system=context.system_prompt
    )

    result = await _process_response(response, context, file_path)

    memory.update(
        user_message=user_message,
        assistant_response=result.text,
        tool_calls=result.executed_tool_calls,
        file_path=file_path,
        file_analysis=file_context
    )

    return result
```

### 3.3 Router 如何决定调用哪个工具

严格来说，Python 代码本身并不直接做语义路由；真正的“选哪个工具”是 LLM 决策。

Router 提供给 LLM 的决策依据主要有四类：

1. `system_prompt`
来自 `config/prompts/core.yaml`，给出高层规则，例如：
- 不伪造数据
- 微观计算不可猜车型
- 已有 `task_type` 时不要重复问宏观/微观

2. `TOOL_DEFINITIONS`
来自 `tools/definitions.py`，定义每个 function 的：
- `name`
- `description`
- `parameters`
- `required`

3. `file_context`
来自 `analyze_file` 结果，尤其是：
- `task_type`
- `columns`
- `row_count`
- `sample_rows`
- `file_path`

4. `fact_memory + working_memory`
帮助 LLM 理解 follow-up request 中的省略表达。

因此 Router 的“决策机制”不是：

```text
if contains("CO2"): call tool A
if contains("file"): call tool B
```

而是：

```text
把结构化上下文喂给 LLM
-> 由 LLM 在 function calling 模式下选 tool
-> Router 负责执行与回路控制
```

### 3.4 LLM function calling 的集成方式

当前 function calling 集成可拆成 4 个环节：

#### 1. 工具 schema 的来源

`ContextAssembler` 通过 `ConfigLoader.load_tool_definitions()` 加载 `tools/definitions.py::TOOL_DEFINITIONS`。

#### 2. 请求发起

`LLMClientService.chat_with_tools()` 调用 OpenAI-compatible `chat.completions.create(...)`，并显式传入：

- `messages`
- `tools`
- `tool_choice="auto"`

#### 3. 响应解析

若返回 `message.tool_calls`，则逐个解析：

```python
arguments = json.loads(tc.function.arguments)
tool_calls.append(
    ToolCall(id=tc.id, name=tc.function.name, arguments=arguments)
)
```

#### 4. 执行与再注入

Router 执行完工具后，如遇错误，会把 tool error 作为 `role="tool"` 消息再注入上下文，形成下一轮 function calling 输入。

这是一种标准的 OpenAI-style tool loop，而不是自定义 JSON planner。

### 3.5 `_process_response()` 的三种分支

`_process_response()` 是 Router 中最关键的方法，核心分支如下：

#### 分支 A：LLM 直接回答

若 `response.tool_calls` 为空，则直接返回：

```python
RouterResponse(text=response.content)
```

这通常发生在：

- 需要澄清参数
- 用户只是追问解释性问题
- LLM 认为无需再调工具

#### 分支 B：执行工具后重试

若调用工具后有错误，且尚未达到重试上限，则：

- 格式化 tool errors
- 回填上下文
- 再次调用 `chat_with_tools()`

这让 LLM 可以：

- 改写错误参数
- 主动向用户发 clarification
- 选择别的工具

#### 分支 C：执行工具后综合结果

若工具成功，Router 会：

1. `_synthesize_results()`
2. `_extract_chart_data()`
3. `_extract_table_data()`
4. `_extract_map_data()`
5. `_extract_download_file()`

最终返回一个富结果的 `RouterResponse`。

### 3.6 多轮对话处理逻辑

项目的多轮对话不是只靠前端历史，而是靠 Router 自己的 memory 子系统：

#### 1. Working memory

`MemoryManager.working_memory` 保存完整 turn；`get_working_memory()` 默认返回最近 5 轮。

但注意，真正送进 prompt 时，`ContextAssembler._format_working_memory()` 只取最近 3 轮，并且对 assistant 长回复截断到 300 字符。

#### 2. Fact memory

这是 follow-up grounding 的核心，保存：

- 最近车型
- 最近污染物
- 最近 model year
- 当前 active file
- 缓存的 file analysis
- 上一个成功工具及摘要
- 上一个工具的 compact snapshot

例如用户说：

```text
把刚才那个改成公交车
```

系统就会依赖：

- `recent_vehicle`
- `active_file`
- `last_tool_snapshot`
- recent working memory

来恢复语义。

#### 3. Correction detection

`MemoryManager._detect_correction()` 会检查“换成”“改成”“我说的是”等中文修正词，并尝试更新 `recent_vehicle`。

#### 4. Compressed memory

文档中强调了“三层记忆”，代码里也确实有 `compressed_memory` 字段和 `_compress_old_memory()` 逻辑；但在当前主链路中，`ContextAssembler.assemble()` 并没有把 `compressed_memory` 注入 prompt。

因此，当前 live code 实际使用的是：

```text
Fact memory + Recent working memory
```

而不是完整意义上的三层 prompt 注入。

## 4. 上下文组装机制

### 4.1 `assemble()` 的输入与输出

`core/assembler.py::ContextAssembler.assemble()` 的输入是：

- `user_message`
- `working_memory`
- `fact_memory`
- `file_context`

输出是：

```python
AssembledContext(
    system_prompt: str,
    tools: List[Dict],
    messages: List[Dict],
    estimated_tokens: int
)
```

这四个字段会被 Router 直接传入 `LLMClientService.chat_with_tools()`。

### 4.2 Prompt 组装顺序

当前实现中的组装顺序非常清晰：

#### 1. 加载 `system_prompt`

来自 `config/prompts/core.yaml` 的 `system_prompt` 字段。

这是最高层的行为约束，包含：

- 角色设定：机动车排放计算助手
- 工具能力边界
- 澄清策略
- 多轮引用策略
- 文件 `task_type` 使用规则

#### 2. 加载 `tools`

来自 `tools/definitions.py::TOOL_DEFINITIONS`。

这些 definitions 直接定义了 function calling 接口，而不是运行时从 registry 反射生成。

#### 3. 注入 fact memory

若 `fact_memory` 非空，则 `assemble()` 会生成一条额外的 `role="system"` message：

```text
[Context from previous conversations]
Recent vehicle type: ...
Recent pollutants: ...
Recent model year: ...
Active file: ...
Cached file task_type: ...
Last successful tool: ...
Last tool summary: ...
Last tool snapshot: ...
```

这里的一个重要特点是：结构化事实并没有拼进主 `system_prompt`，而是作为第二层 system message 单独注入。

#### 4. 注入 working memory

`_format_working_memory()` 会把最近 3 轮 turn 展平为：

```text
user
assistant
user
assistant
...
```

若 token 预算不足，则进一步只保留最近 1 轮。

#### 5. 注入 file context

若有文件且 `enable_file_context_injection=True`，则 `assemble()` 会先调用 `_format_file_context(file_context)` 生成：

```text
Filename: ...
File path: ...
task_type: ...
Rows: ...
Columns: ...
Sample (first 2 rows): ...
```

然后把这段文本直接 prepend 到当前 `user_message` 前：

```python
user_message = f"{file_summary}\n\n{user_message}"
```

这使得 file context 和用户当前意图在同一条 user message 中出现，对 function calling 的即时决策非常有利。

#### 6. 添加当前 user message

最后才 append：

```python
{"role": "user", "content": user_message}
```

### 4.3 Token 预算控制

`ContextAssembler` 明确实现了一个轻量 token budget 策略：

- `MAX_CONTEXT_TOKENS = 6000`
- tools 预估占用约 400 tokens
- file context 为 500 tokens 预留空间
- assistant 历史回答最多保留 300 个字符
- 若 working memory 超预算，则从 3 轮降到 1 轮

token estimation 目前使用简单启发式：

```python
return len(text) // 2
```

因此它更接近 engineering heuristic，而不是精确 tokenizer。

### 4.4 上下文组装的设计特点

当前实现有 4 个非常鲜明的特点：

1. **System prompt 保持简洁**
复杂业务细节不塞进主 prompt，而是分散到 tool descriptions、fact memory、file context。

2. **File context 被提升为当前轮高优先级信息**
不是挂在历史里，而是直接拼到当前 user message 前面。

3. **Memory 采用“结构化事实 + 短历史”**
避免无上限堆叠聊天记录。

4. **Tool schema 是 prompt 的一部分**
这意味着路由行为本质上受 `tools/definitions.py` 影响很大。

### 4.5 组装流程伪代码

```python
def assemble(user_message, working_memory, fact_memory, file_context):
    system_prompt = load_prompts()["system_prompt"]
    tools = load_tool_definitions()
    messages = []

    if fact_memory:
        messages.append({
            "role": "system",
            "content": format_fact_memory(fact_memory)
        })

    messages.extend(format_working_memory(working_memory, max_turns=3))

    if file_context and enable_file_context_injection:
        file_summary = format_file_context(file_context)
        user_message = file_summary + "\n\n" + user_message

    messages.append({"role": "user", "content": user_message})

    return AssembledContext(
        system_prompt=system_prompt,
        tools=tools,
        messages=messages,
        estimated_tokens=estimate_tokens(...)
    )
```

## 5. 当前实现与架构文档的几个关键差异

这部分对论文写作很重要，因为应以 live code 为准。

### 5.1 文档常写 `process()`，实际主入口是 `UnifiedRouter.chat()`

`docs/ARCHITECTURE.md` 使用了 `process()` 作为描述性名称，但当前代码中的真实入口方法是 `core/router.py::UnifiedRouter.chat()`。

### 5.2 “三层记忆”在代码中存在，但 prompt 注入目前主要是两层

代码中有：

- `working_memory`
- `fact_memory`
- `compressed_memory`

但 `compressed_memory` 目前未进入 `ContextAssembler.assemble()` 的 prompt 主链路。

### 5.3 synthesis LLM 在配置中独立存在，但当前 Router 实际复用了 agent client

`config.py` 中定义了 `synthesis_llm`，但 `UnifiedRouter._synthesize_results()` 当前调用的是 `self.llm.chat(...)`，而 `self.llm` 在 `__init__()` 中通过 `get_llm_client("agent", model="qwen-plus")` 创建。

因此当前 live implementation 里，synthesis 并未真正切换到独立的 `purpose="synthesis"` client。

### 5.4 tool execution 层仍有过渡性 `skills/` 依赖

例如：

- `tools/micro_emission.py` 仍依赖 `skills.micro_emission.excel_handler.ExcelHandler`
- `tools/macro_emission.py` 也保留了基于 `skills/` 的文件处理辅助逻辑

这与 README / ENGINEERING_STATUS 中所说的“active but transitional”是一致的。

## 6. 小结

从系统架构角度看，Emission Agent 当前最核心的技术路线可以概括为：

1. **FastAPI/API Session 层** 负责把 Web/HTTP 请求转换成带 `session_id` 和 `file_path` 的结构化输入。
2. **UnifiedRouter** 负责整个智能闭环：file analysis、context assembly、LLM function calling、tool execution、synthesis、memory update。
3. **ContextAssembler + MemoryManager** 负责多轮上下文延续。
4. **ToolExecutor + ToolRegistry** 负责透明标准化和工具分发。
5. **tools + calculators** 负责真正的排放建模和数据处理。

因此，该项目并不是传统的“规则驱动工作流系统”，而是一个以 `UnifiedRouter` 为中心、由 LLM 在 OpenAI function calling 模式下完成工具决策的 **LLM-native emission analysis agent**。
