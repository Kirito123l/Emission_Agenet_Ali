# EmissionAgent 多轮对话持续性诊断报告

> 诊断时间：2026-04-10
>
> 方法：只读代码审计 + 本地脚本化测量（未修改业务代码）
>
> 说明：下文中的 token 为工程估算，不是 API 实测值。JSON 体积优先按 `chars / 4` 粗算；中文富集 prompt 优先按 `chars / 2` 粗算；混合内容以区间表示更可靠。

## 0. 先说结论

当前代码库已经做了两件对“长对话不爆炸”非常有利的事：

1. 原始对话历史不会线性增长到几十轮：真正送进主 `chat_with_tools` 的只有最近 3 轮工作记忆，且 assistant 回复会截断到 300 字符以内。代码见 `core/assembler.py:204-243`、`core/assembler.py:294-333`。
2. `SessionContextStore` 的 LLM 回注只有一个 500 字符上限的 session summary，不会把全量工具结果每轮塞回 prompt。代码见 `core/context_store.py:253-283`。

但当前代码也有几个非常关键的现实问题：

1. **实际 Router 并没有用配置里的 `qwen3-max`，而是硬编码 override 成了 `qwen-plus`。** 代码见 `core/router.py:341`，而配置层默认是 `qwen3-max`，见 `config.py:25-38`。也就是说，“256K 上下文”在当前 Router 运行路径里并不是已被落实的事实。
2. **多工具场景下的 synthesis prompt 可能突然变大。** `filter_results_for_synthesis()` 对 `calculate_dispersion`、`analyze_hotspots`、`render_spatial_map`、`compare_scenarios` 这类结果没有做强约束过滤，直接把 `data` 原样塞进 synthesis JSON。代码见 `core/router_render_utils.py:683-742`。而这些工具的数据里可能包含 `raster_grid`、`concentration_grid`、`hotspots`、地图 payload 等大对象，见 `tools/dispersion.py:604-617`、`tools/hotspot.py:175-190`。
3. **系统没有真实 token telemetry。** `ContextAssembler.estimated_tokens` 只是启发式估算，而且 skill mode 只把“工具名列表”计入估算，不计入真实 9 个工具 schema。代码见 `core/assembler.py:127-140`。本地实测 9 个工具 schema JSON 为 10414 字符，而 skill mode 只估 204 字符的工具名列表。

结论是：

- 如果只看“普通连续追问”，当前实现**不会因为历史消息无限增长而在第 10/20 轮崩掉**。
- 但如果看“类似 Claude/GPT 的持续对话体验”，当前实现**远远不是完整持续记忆**，而是“3 轮工作记忆 + 少量槽位事实 + 500 字符结果摘要”的混合方案。
- 真正的高风险点不是轮数，而是：
  - 实际模型不是预期的 `qwen3-max`
  - 多工具 synthesis 可能吃进大 payload
  - 过程态 continuation / parameter negotiation / input completion 只在内存里活着，进程重启会丢

## 1. Token 预算分析（每轮 LLM 调用的 token 消耗分解）

### 1.1 固定开销（每轮必须发送的）

这里要区分两类 LLM 调用：

1. 主工具选择调用：`chat_with_tools(messages, tools, system)`，见 `core/router.py:9307-9311`、`services/llm_client.py:224-289`
2. 最终 synthesis 调用：`chat(messages, system)`，见 `core/router.py:10449-10463`

#### A. 主工具选择调用的固定开销

- System prompt：
  - 基础 `core_v3.yaml` 仅 483 字符，见 `config/prompts/core_v3.yaml:5-26`
  - 但运行时默认开启 skill injection，见 `config.py:222`
  - `SkillInjector` 会把 post-tool guide、intent skill、file upload guide 拼进 system prompt，见 `core/assembler.py:115-125`、`core/skill_injector.py:190-223`
  - 本地脚本测得：
    - 无上下文、简单“继续”：`system_prompt` 约 463 chars
    - “查排放因子”：约 876 chars
    - 带文件/刚算完排放/要画图的常见 follow-up：situational prompt 约 1472 chars；拼上 core_v3 和 session summary 后，完整 system prompt 约 **2005 chars**
  - 估算：**常见分析轮 ~0.8K-1.0K tokens；最低 ~0.2K-0.4K tokens**

- 工具定义 JSON schema（9 个工具）：
  - 运行时由 `get_tool_contract_registry().get_tool_definitions()` 生成，见 `tools/contract_loader.py:76-91`
  - 本地脚本实测：
    - `tool_count = 9`
    - JSON 长度 = **10414 chars**
    - 按 JSON `chars / 4` 粗算 ≈ **2603 tokens**
  - 估算：**~2.6K tokens**

- Readiness / capability 注入：
  - **主工具选择调用默认没有这部分固定开销**
  - readiness/capability 主要出现在 synthesis 阶段，见 `core/router.py:10005-10011`、`core/router.py:10449-10463`
  - 估算：**0 tokens（对主工具选择调用而言）**

- 主工具选择调用固定开销合计：
  - System prompt：**~0.8K-1.0K**
  - 9 工具 schema：**~2.6K**
  - 固定合计：**~3.4K-3.6K tokens**

#### B. synthesis 调用的固定开销

- `SYNTHESIS_PROMPT` 本体很短，见 `core/router.py:191-202`
- 但真正发出的 synthesis system prompt = `SYNTHESIS_PROMPT + results_json + capability_prompt`，见 `core/router_synthesis_utils.py:61-84`
- capability prompt 由 `format_capability_summary_for_prompt()` 生成，见 `core/capability_summary.py:60-182`
- 本地脚本用一个典型 capability summary 测得：
  - capability prompt ≈ **612 chars**
  - 约 **0.3K tokens**

### 1.2 可变开销（随对话增长的）

- 对话历史：
  - `MemoryManager` 持久化最近 5 轮工作记忆，见 `core/memory.py:59-83`
  - 但真正送给 LLM 的只有最近 **3 轮**，见 `core/assembler.py:225-233`、`core/assembler.py:294-333`
  - 每条 assistant 历史消息截断到 **300 chars**，见 `core/assembler.py:61-63`、`core/assembler.py:315-330`
  - 超预算时会进一步退化到只保留最近 1 轮，见 `core/assembler.py:321-333`
  - 结论：**历史不是线性增长，而是 3 轮滑动窗口**

- FileContext 注入：
  - 通过 `ContextAssembler._format_file_context()` 把文件摘要直接拼到当前 user message 前面，见 `core/assembler.py:235-243`、`core/assembler.py:335-355`
  - 设计注释写着 `max_tokens=500`，但实现**没有真正按 token 截断**，尤其 `Columns:` 会把所有列名全量 join 出来，见 `core/assembler.py:335-355`
  - 本地脚本构造 200 列文件时，单这段 file context 就达到 **2420 chars**，约 **1.2K tokens**
  - 结论：**FileContext 理论上应是 ~500 tokens，实际上对宽表是不受控的**

- SessionContextStore 回注：
  - assembler 只拿 `context_store.get_context_summary()`，并把它追加到 system prompt，见 `core/router.py:480-482`、`core/assembler.py:120-125`
  - 该 summary 被硬截断到 **500 chars**，见 `core/context_store.py:14-16`、`core/context_store.py:253-283`
  - 估算：**~0.2K-0.25K tokens**

- ArtifactMemory 回注：
  - 不直接进入 assembler 的主对话 prompt
  - 主要通过 capability summary 和 file_analysis cache 间接影响 synthesis / follow-up bias，见 `core/router.py:1551-1561`、`core/router.py:1696-1700`、`core/router.py:8649-8725`
  - 对 LLM 的直接注入量通常是 bounded summary，而不是全量 artifact 列表
  - 但 `ArtifactMemoryState.artifacts` 本身**没有 pruning**，见 `core/artifact_memory.py:244-249`、`core/artifact_memory.py:619-625`
  - 结论：**对 prompt 影响通常有限；对磁盘/RAM 增长影响更明显**

### 1.3 单轮 LLM 调用次数和用途

按当前默认运行配置（`enable_state_orchestration=true`、`enable_lightweight_planning=false`、`enable_repair_aware_continuation=false`、`enable_workflow_templates=false`、`enable_file_analysis_llm_fallback=false`）：

- 第 1 次调用：
  - `chat_with_tools`
  - 位置：`core/router.py:9307-9311`
  - 用途：主工具选择 / 直接回答

- 第 2~4 次调用（条件触发）：
  - `chat_with_tools`
  - 位置：`core/router.py:9824-9828`
  - 用途：工具执行后继续选下一个工具
  - 上限：由 `max_orchestration_steps=4` 控制，见 `config.py:223`、`core/task_state.py:207-215`

- synthesis 调用（条件触发）：
  - `chat`
  - 位置：`core/router.py:10449-10463`
  - 用途：把工具结果合成为自然语言
  - 但很多场景会被 `_maybe_short_circuit_synthesis()` 直接绕过，见 `core/router.py:10421-10447`、`core/router_synthesis_utils.py:26-58`
  - 单工具成功时，经常 **0 次 synthesis LLM 调用**

- 可选 JSON 调用（只在特定分支触发）：
  - 文件关系解析：`core/router.py:2315-2319`
  - 意图解析：`core/router.py:3771-3775`
  - 文件分析 fallback：`core/router.py:4113-4118`，但默认关闭
  - 轻量 planning：`core/router.py:8111-8119`，但默认关闭
  - plan repair：`core/router.py:7734-7743`，但默认关闭

### 1.4 预估：第 N 轮时的总 token 消耗

这里采用“当前默认配置 + 常见分析型 follow-up + 有文件上下文 + session summary”的近似测量。使用实际 assembler 路径和真实 9 工具 schema 做本地脚本组装。

- 第 1 轮：
  - 测得总长度约 `10931 chars`
  - 粗算约 **2.7K-3.2K tokens**
  - 特征：无历史、无 session summary、无 file context

- 第 5 轮：
  - 测得总长度约 `14741 chars`
  - 粗算约 **3.7K-5.0K tokens**
  - 特征：最近 3 轮历史 + fact memory + file context + session summary 已全部介入

- 第 10 轮：
  - 近似与第 5 轮持平
  - 粗算约 **3.7K-5.0K tokens**
  - 原因：历史窗口已封顶在最近 3 轮

- 第 20 轮：
  - 近似与第 10 轮持平
  - 粗算约 **3.7K-5.0K tokens**
  - 原因同上

- 256K 上限预计在第多少轮触及：
  - **如果真的是 256K 模型，并且只看历史增长，那么不会因为“轮数增加”线性触顶**
  - **真正的触顶路径是“单轮 payload 爆炸”而不是“轮数爆炸”**
  - 典型爆炸源：
    - 多工具 synthesis 把 `dispersion` / `hotspot` / `map` 的全量 `data` 直接 JSON 化，见 `core/router_render_utils.py:736-740`
    - 宽表文件把全部列名注入 user message，见 `core/assembler.py:346-349`
  - 另外，当前 Router 实际模型是 `qwen-plus`，不是 `qwen3-max`，见 `core/router.py:341`；所以“256K 何时触顶”在当前运行路径下本身就是一个未落实前提

## 2. 对话历史管理现状

### 2.1 历史存储结构

- `MemoryManager` 分三层：
  - `working_memory`
  - `fact_memory`
  - `compressed_memory`
  - 代码见 `core/memory.py:51-68`

- 但真正参与主 LLM prompt 的只有：
  - `fact_memory` 的格式化摘要，见 `core/assembler.py:215-223`、`core/assembler.py:245-292`
  - 最近 3 轮 `working_memory`，见 `core/assembler.py:225-233`、`core/assembler.py:294-333`
  - `compressed_memory` **会被写入磁盘，但不会被 assembler 或 router 再读回 prompt**
  - 代码证据：`compressed_memory` 只有 `core/memory.py` 自己在读写；全仓库无其他引用

- `fact_memory` 里真正保留的只是少量槽位：
  - `recent_vehicle`
  - `recent_pollutants`
  - `recent_year`
  - `active_file`
  - `file_analysis`
  - `last_tool_name`
  - `last_tool_summary`
  - `last_tool_snapshot`
  - `last_spatial_data`
  - 见 `core/memory.py:27-40`、`core/memory.py:91-101`

### 2.2 历史截断策略

- `working_memory` 持久化最多 5 轮，见 `core/memory.py:59-83`
- 超过 10 轮时会压缩旧轮次，见 `core/memory.py:143-145`、`core/memory.py:240-254`
- 但 LLM 注入层只取最近 3 轮，见 `core/assembler.py:303-333`
- assistant 历史消息截到 300 chars，见 `core/assembler.py:315-330`
- 超预算时直接退到只保留最近 1 轮，见 `core/assembler.py:321-333`

结论：

- **当前不是“长上下文持续对话”**
- 而是“3 轮工作记忆 + 若干事实槽位 + 500 字符 session summary”

### 2.3 跨轮次状态传递

跨轮次真正会传的东西：

- 事实槽位：通过 `MemoryManager` 落盘并在新 turn 初始化 `TaskState`，见 `core/router.py:1370-1375`、`core/task_state.py:304-398`
- 文件主上下文：`active_file + file_analysis`，见 `core/memory.py:133-139`、`core/task_state.py:356-397`
- 工具语义结果：通过 `SessionContextStore` 存储并回注 500-char summary 或给下游工具 `_last_result` 注入，见 `core/router.py:488-491`、`core/router.py:544-620`、`core/context_store.py:107-140`
- artifact 交付记忆：挂在 `file_analysis` cache / memory update payload 中，见 `core/router.py:1551-1561`、`core/router.py:1696-1700`

不会稳定跨轮保留的东西：

- 第 4 轮以前的自然语言对话细节
- 完整工具调用链 reasoning
- API 层 `_history` 对话全文

原因：这些内容虽然会存盘，但 router 不会把它们重新装进 prompt。`api/session.py` 的 `_history` 主要用于前端历史回显，见 `api/session.py:39-40`、`api/session.py:108-153`、`api/session.py:278-307`。

## 3. 会话管理架构

### 3.1 Router 实例生命周期

- Web/API 路径下，每个 `session_id` 对应一个懒加载 `UnifiedRouter`，见 `api/session.py:42-51`
- `SessionManager` 在内存里持有 `Session` 对象字典，见 `api/session.py:167-200`
- 因此在**同一进程存活期间**，每个会话确实会复用同一个 Router 实例

### 3.2 会话状态存储位置

- `MemoryManager`：
  - 路径：`data/sessions/<user_id>/memory/<session_id>.json`
  - 初始化见 `api/session.py:30-34`、`api/session.py:46-49`
  - Router 侧使用 `MemoryManager(session_id, storage_dir=...)`，见 `core/router.py:334-340`

- `SessionContextStore`：
  - 被保存到 `data/sessions/<user_id>/router_state/<session_id>.json`
  - 保存/恢复代码见 `api/session.py:74-104`

- API 历史消息：
  - 保存在 `data/sessions/<user_id>/history/<session_id>.json`
  - 代码见 `api/session.py:291-308`

### 3.3 并发会话处理

- `SessionRegistry` 按 `user_id` 隔离 `SessionManager`，见 `api/session.py:315-329`
- 每个 user 下多个 `session_id` 分别维护自己的 Router/Memory/History
- 没有 Redis、数据库级共享会话态；主要是**进程内对象 + JSON 落盘**

### 3.4 超时与清理

- 没看到自动 session TTL / idle cleanup
- 删除只发生在显式 `/sessions/{id}` 删除接口，见 `api/session.py:231-245`、`api/routes.py:900-903`
- streaming 连接只有 15 秒 heartbeat 保活，见 `api/routes.py:431-438`

结论：

- 会话状态持久化是有的
- 但**没有自动清理机制**
- 长期运行后，session 文件、router_state、memory、history 都会持续累积

## 4. 错误恢复能力

### 4.1 LLM 调用失败时的行为

- Router 主 LLM 客户端只有：
  - 120s request timeout
  - proxy -> direct failover
  - **没有 retry / backoff**
  - 代码见 `services/llm_client.py:94-121`、`services/llm_client.py:138-174`

- `chat()` / `chat_with_tools()` / `chat_json()` 都是失败即抛异常，见 `services/llm_client.py:200-223`、`services/llm_client.py:250-293`、`services/llm_client.py:318-339`
- API 层把异常包装成友好错误消息，见 `api/routes.py:352-359`、`api/routes.py:541-546`

补充：

- 标准化子系统有独立 5s timeout + 1 次重试，见 `config.py:237-238`、`services/model_backend.py:80-81`、`services/model_backend.py:188-198`
- 但这不等于 Router 主对话 LLM 有重试

### 4.2 状态机异常恢复

- 如果 LLM 在需要选工具时返回 no-tool，router 会尝试 deterministic fallback 或直接转澄清，见 `core/router.py:907-953`
- state loop 有 guard，超出迭代上限会强制转 `DONE`，见 `core/router.py:1380-1397`
- 但非法状态转换仍然直接 `raise ValueError`，见 `core/task_state.py:400-404`

### 4.3 前端连接中断恢复

- 流式接口是 `StreamingResponse(text/event-stream)`，见 `api/routes.py:362-550`
- 有 heartbeat，但没有 WebSocket session resume，也没有 mid-turn resume token
- 连接断了以后，用户通常只能重新发起新一轮请求

## 5. 已识别的瓶颈（按严重程度排序）

### 🔴 P0 - 会导致对话崩溃的问题

- **实际 Router 模型不是 `qwen3-max`，而是 `qwen-plus`。**
  - 代码：`core/router.py:341`
  - 背景配置：`config.py:25-38`
  - 影响：当前工程并不能用“qwen3-max 256K”来评估真实可持续轮数；上下文上限、稳定性、成本都可能与预期不一致。

- **多工具 synthesis 对部分工具结果做了“全量 data dump”，有单轮 prompt 爆炸风险。**
  - 代码：`core/router_render_utils.py:736-740`
  - 上游大对象来源：`tools/dispersion.py:604-617`、`tools/hotspot.py:175-190`
  - 影响：不是第 20 轮才危险，而是**任意一轮**只要进入“扩散/热点/地图/对比 + 非短路 synthesis”，就可能把大栅格或大地图 payload 直接塞进 LLM。

### 🟡 P1 - 会导致对话质量下降的问题

- **旧对话的自然语言细节丢失得很快。**
  - 代码：`core/assembler.py:225-233`、`core/assembler.py:294-333`
  - 影响：第 4 轮之前的原始对话几乎不再进入 prompt；只能靠 fact slots 和 500-char session summary 维持弱连续性。

- **`compressed_memory` 实际是死存储。**
  - 写入代码：`core/memory.py:240-254`
  - 全仓库无再利用
  - 影响：看起来做了“压缩长期记忆”，实际上没有被 router 再利用。

- **`estimated_tokens` 明显低估真实输入。**
  - skill mode 只估工具名列表：`core/assembler.py:127-135`
  - legacy mode 直接写死 `400`：`core/assembler.py:182-184`
  - 真实 9 工具 schema JSON：10414 chars
  - 影响：trace 中的 `estimated_tokens` 不能作为真实 prompt budget 的可信依据。

- **`_format_file_context()` 的 `max_tokens` 参数没有被真正执行。**
  - 代码：`core/assembler.py:335-355`
  - 影响：宽表列名可能直接把 user message 前缀推高到 1K+ tokens，本地 200 列实测约 2420 chars。

- **流程态 continuation / parameter negotiation / input completion 只存在 Router 内存 bundle 中。**
  - live bundle：`core/router.py:343-383`
  - 应用恢复：`core/router.py:4569-4615`
  - Session 落盘只保存 `context_store`：`api/session.py:74-104`
  - 影响：服务重启后，正在进行中的“继续执行”“参数确认”“补输入”上下文会丢。

- **`SessionContextStore` 和 `ArtifactMemory` 的持久化体积会持续增长。**
  - `SessionContextStore` 持久化全量 `store + history`：`core/context_store.py:432-483`
  - `_store` 只对非 baseline scenario 做 5 个上限；`_history` 没有上限：`core/context_store.py:535-548`
  - `ArtifactMemoryState` append 无 pruning：`core/artifact_memory.py:244-249`、`core/artifact_memory.py:619-625`
  - 影响：prompt 不一定炸，但磁盘/RAM 和 session state 会越跑越大。

### 🟢 P2 - 优化建议（不影响功能但影响体验）

- **API 全量历史只用于前端展示，不参与真正对话 grounding。**
  - 代码：`api/session.py:108-153`、`api/session.py:278-307`
  - 影响：前端看起来“历史都在”，但模型并没有真的记住同样多的内容。

- **SSE 只有 heartbeat，没有 resume。**
  - 代码：`api/routes.py:431-438`
  - 影响：长任务中断后用户体验不如 Claude/GPT 风格的稳态流式体验。

- **单工具成功时大量走 deterministic short-circuit synthesis。**
  - 代码：`core/router.py:10421-10447`
  - 影响：这是预算优化，但也意味着很多回复完全不再参考多轮语境，只参考当前结果对象。

## 6. 与 Claude/GPT 对话体验的差距分析

### 6.1 闲聊 / 追问处理

当前当用户说“解释一下刚才的结果”时，router 主要依赖：

- 最近 3 轮工作记忆，见 `core/assembler.py:294-333`
- `last_tool_name` / `last_tool_summary` / `last_tool_snapshot`，见 `core/memory.py:35-39`、`core/memory.py:160-175`
- `SessionContextStore` 的 500-char summary，见 `core/context_store.py:253-283`

这意味着：

- 对“刚才”的理解只对最近几轮比较稳
- 对更早轮次的细节只能做弱回忆
- 对闲聊型上下文（例如用户偏好、上一次解释风格、前面几轮措辞差异）几乎没有建模

### 6.2 上下文连贯性

问题：第 10 轮时，LLM 还能记住第 1 轮文件分析结果吗？

答案：

- **结构化信息可能还在**
  - `active_file`
  - `file_analysis`
  - `SessionContextStore` 里的语义结果
- **自然语言细节大概率已经不在**
  - 因为第 1 轮原始 user / assistant 对话早就被挤出 3 轮窗口

所以当前更像：

- “记得你算过什么、用的是什么文件、最近成功过什么工具”
- 不像：
- “完整记得你们前 10 轮是怎么一步步聊过来的”

### 6.3 错误恢复

当前如果某轮工具执行失败：

- 同轮内：
  - state loop 允许 LLM 基于 tool result/error 继续选下一个工具，见 `core/router.py:9808-9848`
  - legacy loop 里还会做一次带 error context 的 retry，见 `core/router.py:10320-10358`

- 跨轮：
  - 如果是 parameter negotiation / input completion，且进程没重启，可以靠 live bundle 接续，见 `core/router.py:4569-4615`
  - 如果进程重启，这些流程态会丢
  - repair-aware continuation 默认还是关闭的，见 `config.py:72-73`

因此用户说“再试一次”时：

- 对纯工具失败，系统可以重新走一轮，但不是强语义“恢复上一个中断工作流”
- 对跨轮恢复体验，明显弱于 Claude/GPT 的长期 thread continuation

### 6.4 对话流自然度

当前系统虽然做了状态机编排，但整体仍偏“任务型”而不是“thread-native”：

- 强项：
  - 对分析任务、文件任务、下游工具串接更稳
  - 对结构化 follow-up（继续、画图、做扩散、做热点）有专门机制

- 弱项：
  - 闲聊、解释、追问、改写、跳话题后再回来，仍然依赖非常有限的历史窗口
  - 会话全文存在于前端历史，但不等于模型真的共享了同一个“持续思维空间”

## 7. 关键代码位置索引

| 关注点 | 文件 | 行号 | 说明 |
|--------|------|------|------|
| Router 实际模型 override | `core/router.py` | `L341` | `get_llm_client("agent", model="qwen-plus")` |
| Router 入口 | `core/router.py` | `L1190-L1201` | `chat()` 选择 state loop / legacy loop |
| 主 LLM 工具选择调用 | `core/router.py` | `L9307-L9311` | `chat_with_tools(messages, tools, system)` |
| 多工具 follow-up 调用 | `core/router.py` | `L9824-L9828` | 工具执行后再次 `chat_with_tools` |
| 最终 synthesis 调用 | `core/router.py` | `L10449-L10463` | `chat(messages, system)` |
| Synthesis prompt 常量 | `core/router.py` | `L191-L202` | `SYNTHESIS_PROMPT` |
| System prompt 组装 | `core/assembler.py` | `L115-L125` | skill injection + context summary |
| 历史与文件上下文组装 | `core/assembler.py` | `L204-L243` | fact memory / working memory / file context / current user |
| 工作记忆截断 | `core/assembler.py` | `L294-L333` | 最近 3 轮、assistant 截断 300 chars |
| FileContext 注入格式化 | `core/assembler.py` | `L335-L355` | `max_tokens` 未真正执行 |
| MemoryManager 定义 | `core/memory.py` | `L51-L68` | 三层 memory 结构 |
| Memory 更新与持久化 | `core/memory.py` | `L103-L149` | 每轮更新 memory |
| `compressed_memory` 生成 | `core/memory.py` | `L240-L254` | 生成但未被 prompt 使用 |
| TaskState 初始化 | `core/task_state.py` | `L304-L398` | 每轮从 `memory_dict` 重建状态 |
| 参数锁摘要 | `core/task_state.py` | `L869-L895` | parameter lock 跨轮摘要 |
| SessionContextStore 定义 | `core/context_store.py` | `L65-L106` | 语义结果存储 |
| SessionContext summary 限长 | `core/context_store.py` | `L253-L283` | 500 chars 上限 |
| SessionContext 持久化 | `core/context_store.py` | `L432-L483` | 保存全量 store + history |
| 工具 schema 生成 | `tools/contract_loader.py` | `L76-L91` | 9 个 function-calling tools |
| tool_contracts 体积 | `config/tool_contracts.yaml` | `824 lines / 26996 bytes` | 工具契约源文件大小 |
| skill injection 规则 | `core/skill_injector.py` | `L84-L132` | intent 检测 |
| situational prompt 组装 | `core/skill_injector.py` | `L190-L223` | post-tool + skills + file guide |
| capability summary 组装 | `core/router.py` | `L8649-L8756` | synthesis follow-up guardrails |
| capability prompt 文本化 | `core/capability_summary.py` | `L60-L182` | readiness/capability 注入文本 |
| synthesis request 构造 | `core/router_synthesis_utils.py` | `L61-L84` | `results_json + capability_prompt` |
| synthesis 结果过滤缺口 | `core/router_render_utils.py` | `L683-L742` | dispersion/hotspot/map/compare 仍会塞全量 `data` |
| 文件关系 JSON 调用 | `core/router.py` | `L2306-L2324` | `chat_json` |
| 意图解析 JSON 调用 | `core/router.py` | `L3762-L3780` | `chat_json` |
| 轻量 planning JSON 调用 | `core/router.py` | `L8063-L8129` | 默认关闭 |
| plan repair JSON 调用 | `core/router.py` | `L7707-L7751` | 默认关闭 |
| live continuation bundle 同步 | `core/router.py` | `L6607-L6638` | 仅内存，不落盘 |
| live parameter / input state 回灌 | `core/router.py` | `L4569-L4615` | 仅当前 Router 实例有效 |
| Session 懒加载 Router | `api/session.py` | `L42-L51` | 每会话一个 Router 实例 |
| Router state 持久化 | `api/session.py` | `L74-L104` | 只保存 `context_store` |
| API 非流式聊天入口 | `api/routes.py` | `L220-L350` | 每轮 POST 新请求 |
| API 流式聊天入口 | `api/routes.py` | `L362-L550` | SSE + heartbeat，无 resume |
| LLM 客户端 failover | `services/llm_client.py` | `L138-L174` | proxy -> direct，无 retry/backoff |

## 8. 建议给后续升级的工程抓手

如果目标真的是“像 Claude/GPT 一样连续几十轮不降智”，优先级建议如下：

1. 先修正 Router 的模型来源，让实际运行模型与配置一致；否则 256K 预算分析没有落地意义。位置：`core/router.py:341`
2. 给主 LLM 调用接入真实 token telemetry（至少记录 prompt chars、tool schema chars、OpenAI usage 字段）；否则只能靠启发式盲飞。位置：`services/llm_client.py:176-339`
3. 修 `filter_results_for_synthesis()`，对 `dispersion/hotspot/map/compare` 做严格裁剪；否则单轮爆炸风险一直存在。位置：`core/router_render_utils.py:683-742`
4. 把“长期记忆”从当前的 3 轮窗口 + fact slots，升级为可检索、可摘要、可恢复的 session memory，而不是只给前端看全历史。当前位置：`core/memory.py`、`api/session.py`
5. 把 live continuation / negotiation / input completion bundle 纳入可恢复持久化；否则服务重启会把工作流 continuity 打断。位置：`core/router.py:343-383`、`api/session.py:74-104`

