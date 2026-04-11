# EmissionAgent Conversation Upgrade Execution Plan

> Scope: 将 `EMISSIONAGENT_CONVERSATION_UPGRADE_PLAN.md` 中的多轮对话升级方案落地为可执行工作包。  
> Planning source: 当前 ralplan 会话已批准的 **Option A — staged minimal overlay**。  
> Execution rule: 先基线、后实现；每个工作包必须独立验证；不得覆盖当前工作树中与本升级无关的既有修改。

---

## 0. 执行总原则

1. **正确性优先于对话速度**：任何 conversational fast path 都不得绕过参数确认、输入补全、文件关系解析、残余任务恢复、readiness gating、summary delivery 或工具依赖检查。
2. **最小侵入**：优先复用 `UnifiedRouter`、`MemoryManager`、`SessionContextStore`、`ToolExecutor`、现有 readiness/recovery/intent-resolution 机制；避免首轮重写 router 或强制切换到 `memory_v2.py`。
3. **强边界与可回滚**：所有行为改变应有 feature flag 或清晰回滚点。
4. **上下文严格限额**：注入 LLM 的文件列名、工具结果、记忆摘要、解释上下文都必须有硬上限。
5. **测试先行或同步补齐**：每个 WP 至少包含目标单元测试和 router/session 集成测试；阶段完成前必须跑对应验证命令。
6. **保护脏工作树**：执行前记录 `git status --short`，只修改本计划列出的文件；发现同文件已有无关改动时先拆分 diff 或暂停交由执行负责人处理。

---

## 1. 推荐执行顺序与并行策略

| 顺序 | 工作包 | 是否允许并行 | 说明 |
|---|---|---:|---|
| 0 | Phase 0 Baseline | 否 | 所有实现前必须完成，记录当前脏工作树与测试基线。 |
| 1 | WP-CONV-1 | 部分允许 | 基础修复可拆小 lane，但同一文件修改需串行合并。 |
| 2 | WP-CONV-2 | 条件允许 | 依赖 WP-CONV-1 的上下文限额与 telemetry；可与 WP-CONV-3 设计并行，但 router 集成需串行。 |
| 3 | WP-CONV-3 | 条件允许 | 可与 WP-CONV-2 的分类器单测并行；与 assembler/router 注入点需协调。 |
| 4 | WP-CONV-4 | 部分允许 | retry、session cleanup、observability 可拆；最终验证必须串行。 |

---

## 2. Phase 0 — Baseline / Worktree Protection

### 目标

在任何生产代码改动前建立安全基线，避免覆盖仓库中已存在的无关修改。

### 涉及文件

不要求修改生产代码。可能新增或更新临时记录/执行日志，由执行负责人决定是否提交。

### 依赖关系

- 必须先于 WP-CONV-1/2/3/4。
- 后续所有 WP 都依赖此阶段记录的 dirty tree 和测试基线。

### 风险点

- 当前仓库已有无关 modified/untracked 文件；直接 `git checkout` 或大范围格式化可能破坏用户工作。
- 基线测试可能已有失败，若未记录会误判为升级引入回归。

### 验证方式

建议记录：

```bash
git status --short
python main.py health
python main.py tools-list
pytest -q tests/test_router_state_loop.py tests/test_assembler_skill_injection.py tests/test_router_contracts.py tests/test_session_persistence.py
```

若基线失败，需记录失败测试、失败原因、是否与升级范围相关。

### 回滚点

- 此阶段不应产生生产代码 diff。
- 如误改文件，立即按文件级 diff 回滚，且不得回滚无关既有修改。

### 是否允许并行

不允许。必须由单一负责人完成并确认后才能进入实现阶段。

---

## 3. WP-CONV-1 — Foundation Fixes & Telemetry

### 目标

修复当前多轮对话升级的 P0/P1 基础问题：实际模型配置未生效、synthesis 大对象注入、FileContext 列名膨胀、token usage 不可观测，并提前补齐 live state persistence 的关键连续性缺口。

### 涉及文件

主要文件：

- `core/router.py`
- `core/router_render_utils.py`
- `core/router_synthesis_utils.py`
- `core/assembler.py`
- `services/llm_client.py`
- `api/session.py`
- `config.py`
- `.env.example`

测试文件：

- `tests/test_router_state_loop.py`
- `tests/test_router_contracts.py`
- `tests/test_assembler_skill_injection.py`
- `tests/test_session_persistence.py`
- `tests/test_config.py`
- 可新增 `tests/test_router_llm_config.py`
- 可新增 `tests/test_llm_client_telemetry.py`

### 具体工作

#### 3.1 Router 模型配置生效

- 将 `UnifiedRouter.__init__` 中硬编码 `get_llm_client("agent", model="qwen-plus")` 改为 `get_llm_client("agent")`。
- 初始化时记录 resolved model，例如 `self.llm.model`。
- `.env.example` 与默认配置应表达清晰：运行模型由 `AGENT_LLM_MODEL` 控制。

#### 3.2 Synthesis payload 裁剪

- 在 `filter_results_for_synthesis()` 中增加 copy-only heavy payload stripping。
- 重点裁剪：`raster_grid`、`matrix_mean`、`concentration_grid`、`cell_centers_wgs84`、`contour_bands`、`contour_geojson`、`receptor_top_roads`、`cell_receptor_map`、`map_data`、`geojson`、`features`。
- 长 list 只保留 preview 和 omitted count。
- 不得修改原始 tool result，以免影响 frontend payload、context store、下游 `_last_result` 注入。

#### 3.3 FileContext 列名限额

- 在 `ContextAssembler._format_file_context()` 中对 `columns` 生成做硬上限。
- 保留 file path、filename、task_type、row_count。
- 宽表显示前若干列，并标注剩余列数。

#### 3.4 Token telemetry

- 在 `services/llm_client.py` 的 `chat()`、`chat_with_tools()`、`chat_json()` 中提取并记录 API `usage`。
- 可在 `LLMResponse` 增加 optional `usage` 字段，保持向后兼容。
- 日志不得包含 API key、raw prompt 或大型 payload。

#### 3.5 Live state persistence

- 在 `api/session.py` / `core/router.py` 中持久化和恢复：
  - `context_store`
  - `_live_parameter_negotiation`
  - `_live_input_completion`
  - `_live_continuation_bundle`
- 使用 versioned envelope。
- 保持旧格式 `context_store` payload 可恢复。
- 建议加 `ENABLE_LIVE_STATE_PERSISTENCE` feature flag。

### 依赖关系

- 依赖 Phase 0 基线。
- WP-CONV-2 依赖本 WP 的模型配置、payload 限额、telemetry 和基础 persistence。
- WP-CONV-3 依赖本 WP 的 context/payload 限额策略。

### 风险点

- 模型配置变更可能改变 LLM 行为与测试 mock 假设。
- payload 裁剪若误作用于原始对象，会破坏地图渲染、下载、context store 或下游工具。
- `LLMResponse` 增加字段应保持所有测试构造兼容。
- live state persistence 中复杂对象可能无法 JSON 序列化。

### 验证方式

Targeted tests：

```bash
pytest -q tests/test_router_contracts.py
pytest -q tests/test_assembler_skill_injection.py
pytest -q tests/test_session_persistence.py
pytest -q tests/test_config.py
```

新增/补充测试应覆盖：

- router 不再 hardcode `qwen-plus`。
- synthesis JSON 对 heavy spatial payload 裁剪后目标 `< 5000 chars`。
- `_format_file_context()` 对宽表列名截断。
- fake OpenAI response 的 `usage` 被记录/返回。
- session reload 后 live negotiation / continuation state 可恢复。

### 回滚点

可按子项独立回滚：

1. 恢复 router model override（不推荐，仅用于紧急回滚）。
2. 关闭 payload stripping 或回滚 `router_render_utils.py` 修改。
3. 恢复 `_format_file_context()` 旧逻辑。
4. 移除 telemetry optional field/logging。
5. 关闭 `ENABLE_LIVE_STATE_PERSISTENCE`，保留 legacy `context_store` persistence。

### 是否允许并行

部分允许。

可并行 lane：

- payload stripping + tests
- FileContext column cap + tests
- telemetry + tests
- session persistence + tests

不建议并行修改同一个 `core/router.py` 区域；router model 与 live persistence 应由一个负责人串行合并。

---

## 4. WP-CONV-2 — Conservative Conversation Intent Router

### 目标

实现类 ChatGPT 的轻量对话分流：闲聊、结果解释、知识问答不再默认进入完整状态机；任务类、继续任务、参数修改、确认/补全仍走现有 state loop 和工具机制。

### 涉及文件

主要文件：

- 新增 `core/conversation_intent.py`
- 可新增 `core/conversation_handlers.py`
- `core/router.py`
- `core/assembler.py`
- `tools/knowledge.py`（通常不改，仅复用）
- `tools/registry.py`（通常不改，仅复用）

测试文件：

- 新增 `tests/test_conversation_intent.py`
- `tests/test_router_state_loop.py`
- `tests/test_intent_resolution.py`
- `tests/test_summary_delivery.py`
- 可能补充 `tests/test_context_store_integration.py`

### 具体工作

#### 4.1 ConversationIntentClassifier

实现 rule-first classifier，分类至少包含：

- `CHITCHAT`
- `EXPLAIN_RESULT`
- `KNOWLEDGE_QA`
- `NEW_TASK`
- `CONTINUE_TASK`
- `MODIFY_PARAMS`
- `RETRY`
- `UNDO`
- `CONFIRM`

设计要求：

- 规则优先，LLM 兜底可后置，不作为首轮必需。
- 误判成本不对称：宁可把闲聊送入状态机，也不能把任务误判为闲聊。
- 输出必须包含 intent、confidence、reason/blocking signals、extracted_entities（可选）。

#### 4.2 Fast path gate

Fast path 仅允许高置信度：

- `CHITCHAT`
- `EXPLAIN_RESULT`
- `KNOWLEDGE_QA`

必须阻断 fast path 的情况：

- active parameter negotiation
- active input completion
- active file relationship clarification
- incoming file upload
- residual workflow / continuation bundle
- geometry recovery / residual reentry
- explicit tool/action/compute keywords
- low confidence
- confirm-like reply

#### 4.3 Router 集成

确定集成点：

- 在 `UnifiedRouter.chat()` 中清理 current turn 后、进入 `_run_state_loop()` 之前做 fast-path 判断；但必须读取 live blockers。
- 不在 `_state_handle_input()` 早期集成。理由：闲聊、简单解释、知识问答等 fast-path 场景应尽早短路，避免为非任务型消息白跑 state-loop 内的 live state apply/restore、文件关系、恢复上下文等前置逻辑，从而降低延迟和无谓状态扰动风险。

必须保持：

- `core/intent_resolution.py` 仍负责 active task output-mode/progress bias。
- summary delivery surface 不被 chitchat fast path 抢先。
- readiness gating、file relationship resolution、parameter/input confirmation 不被绕过。

建议 feature flag：

- `ENABLE_CONVERSATION_FAST_PATH`

#### 4.4 Lightweight handlers

- Chitchat：使用 `llm.chat()`，不注入 tool schema。
- Explain result：注入 bounded `last_tool_name`、`last_tool_summary`、`last_tool_snapshot`、`context_store.get_context_summary()`。
- Knowledge QA：通过现有 `ToolExecutor` 或注册工具执行 `query_knowledge`；不要绕过工具边界直接实例化 registry 私有对象。
- 所有 handler 都应更新 `MemoryManager`。

#### 4.5 Conversational message builder

在 `ContextAssembler` 中增加 bounded no-tool message builder，例如：

- 最近 5 轮对话。
- assistant 回复长度上限高于工具模式但仍需 capped。
- 不注入 tool schema、readiness 或 capability 大段信息。

### 依赖关系

- 依赖 WP-CONV-1 的 payload/file context 限额和 telemetry。
- 与 WP-CONV-3 的 memory context 有接口关系；若并行，需约定 `build_context_for_prompt()` / `build_messages_for_chat()` 的稳定签名。

### 风险点

- 误判闲聊导致真实计算任务不执行。
- 用户回复“好的/确认/1”时被当成闲聊，破坏 negotiation/input completion。
- Knowledge QA 绕过工具执行路径，造成 memory/context store 不一致。
- explain-result 注入过大 snapshot。

### 验证方式

Targeted tests：

```bash
pytest -q tests/test_conversation_intent.py
pytest -q tests/test_router_state_loop.py
pytest -q tests/test_intent_resolution.py tests/test_summary_delivery.py
```

必须覆盖：

- “你好” fast path，`chat_with_tools` 不被调用。
- “计算 Passenger Car 的 CO2 排放因子” 进入 state loop。
- active negotiation 下“好的/1/确认”不走 chitchat。
- active input completion 下补全回复不走 chitchat。
- explain-result 使用 last tool summary/snapshot/context summary。
- knowledge QA 成功时记录 tool memory，失败时友好 fallback。
- trace 中包含 intent、confidence、block reason。

### 回滚点

- 关闭 `ENABLE_CONVERSATION_FAST_PATH` 即可退回原 state loop 行为。
- 可删除/停用 `conversation_intent.py` 与 `conversation_handlers.py` 的 router 接入，不影响 WP-CONV-1。
- 保留 tests 作为未来再启用依据。

### 是否允许并行

条件允许。

可并行：

- classifier + classifier unit tests
- handler unit tests
- assembler conversational message builder

必须串行：

- router 集成
- 与 active negotiation / input completion / summary delivery 的冲突测试修复

---

## 5. WP-CONV-3 — In-place Layered Memory

### 目标

把现有 `MemoryManager` 从“短窗口 + fact slots + 死存储 compressed_memory”升级为可注入、可持久化、有硬上限的分层记忆；支持第 10/20 轮仍保留关键上下文。

### 涉及文件

主要文件：

- `core/memory.py`
- `core/assembler.py`
- `core/router.py`
- `core/context_store.py`（通常不改，只复用 summary）
- `api/session.py`（如需验证持久化）

测试文件：

- 新增 `tests/test_layered_memory_context.py`
- `tests/test_session_persistence.py`
- `tests/test_assembler_skill_injection.py`
- `tests/test_router_state_loop.py`

### 具体工作

#### 5.1 MemoryManager 兼容增强

在现有 `MemoryManager` 中增加：

- `turn_counter`
- bounded mid-term summaries
- `session_topic`
- `user_language_preference`
- `cumulative_tools_used`
- `key_findings`
- `user_corrections`

继续支持旧 JSON：旧字段缺失时使用默认值。

#### 5.2 让 compressed_memory 真正进入 prompt

新增：

```python
build_context_for_prompt(max_chars: int = 3000) -> str
```

输出结构建议：

- `[会话事实]`
- `[历史摘要]`
- `[用户偏好/修正]`
- `[关键发现]`

#### 5.3 Prompt 注入

可选方案：

1. `ContextAssembler.assemble(..., memory_context=None)` 新增 optional 参数。
2. Router 将 memory context append 到现有 `context_summary`。

推荐：若测试 mock 对 assembler 签名敏感，优先采用 router append 或兼容签名检查。

#### 5.4 严格禁止大对象注入

Memory context 不得包含：

- `last_spatial_data` full payload
- `raster_grid`
- concentration matrices
- GeoJSON/map features
- full context-store data
- raw download payload

### 依赖关系

- 依赖 WP-CONV-1 的 payload 限额策略。
- 与 WP-CONV-2 的 conversational prompt 共享 memory context；接口需稳定。
- Session persistence 测试可复用 WP-CONV-1 live persistence 基础。

### 风险点

- 新 memory fields 破坏旧 session JSON 加载。
- mid-term summary 过长或重复，导致 prompt bloat。
- stale facts 影响新任务判断。
- 把 spatial payload 错误带入 prompt。

### 验证方式

Targeted tests：

```bash
pytest -q tests/test_layered_memory_context.py
pytest -q tests/test_session_persistence.py
pytest -q tests/test_assembler_skill_injection.py
pytest -q tests/test_router_state_loop.py
```

必须覆盖：

- 旧 memory JSON 可加载。
- 新字段可保存/恢复。
- `build_context_for_prompt()` 输出长度 capped。
- 20-turn simulated conversation 仍能注入早期关键事实摘要。
- memory context 不包含 raw spatial keys/payload。
- assembler/router 注入不会破坏已有 skill injection message 结构。

### 回滚点

- 关闭 `ENABLE_LAYERED_MEMORY_CONTEXT`，保留字段持久化但不注入 prompt。
- 回滚 assembler/router 的 memory_context 注入点。
- 保留旧 `working_memory` + `fact_memory` 行为。

### 是否允许并行

条件允许。

可并行：

- memory data model + persistence tests
- prompt formatting/unit tests

必须串行：

- assembler/router 注入点
- 与 WP-CONV-2 conversational prompt 的接口合并

---

## 6. WP-CONV-4 — Reliability, UX Polish & Final Verification

### 目标

补齐 LLM 调用可靠性、会话清理、conversational prompt、trace/observability，并完成全量验证。

### 涉及文件

主要文件：

- `services/llm_client.py`
- `api/session.py`
- `core/router.py`
- `core/conversation_handlers.py`（若 WP-CONV-2 新增）
- `config.py`
- `.env.example`

测试文件：

- `tests/test_llm_client_telemetry.py` 或新增 retry tests
- `tests/test_session_persistence.py`
- `tests/test_router_state_loop.py`
- `tests/test_config.py`

### 具体工作

#### 6.1 LLM retry/backoff

- 对 transient connection errors 做 bounded retry/backoff。
- 保留现有 proxy → direct failover。
- auth、validation、schema、bad request 等非 transient 错误 fail fast。
- 测试中使用 fake client 和 injectable sleeper，避免真实 sleep。

建议 feature flag：

- `ENABLE_LLM_RETRY_BACKOFF`

#### 6.2 Conversational system prompt

- 为 chitchat/explain/knowledge naturalization 提供简洁 system prompt。
- 包含 EmissionAgent 能力边界。
- 跟随用户语言偏好。
- 注入 bounded memory/context summary。

#### 6.3 Idle session cleanup

- 在 `api/session.py` 增加 idle session cleanup。
- 默认只从内存 session registry 移除 idle sessions。
- 不删除 persisted history/router_state/memory，除非显式调用 delete session。

#### 6.4 Observability

补齐日志/trace：

- resolved LLM model
- token usage
- intent classification result
- fast-path block reason
- synthesis JSON length
- memory context length
- retry attempt count

不得记录：

- API keys
- raw secrets
- raw huge prompt/payload

### 依赖关系

- 依赖 WP-CONV-1 telemetry 基础。
- 依赖 WP-CONV-2 conversational handlers。
- 依赖 WP-CONV-3 memory context。
- 是最终 release readiness gate。

### 风险点

- retry 导致非幂等请求重复；需限制在 LLM API 请求层，不重复执行工具。
- cleanup 若删除持久化数据会造成会话丢失。
- observability 过度记录 prompt 或数据，造成日志膨胀/泄露。

### 验证方式

Targeted tests：

```bash
pytest -q tests/test_session_persistence.py
pytest -q tests/test_router_state_loop.py
pytest -q tests/test_config.py
```

LLM retry tests 应覆盖：

- transient connection error retry 成功。
- auth/validation error 不 retry。
- proxy/direct failover 顺序保持。

Final full verification：

```bash
python -m py_compile core/router.py core/assembler.py core/memory.py core/router_render_utils.py services/llm_client.py api/session.py config.py
pytest -q
python scripts/utils/test_new_architecture.py
python scripts/utils/test_api_integration.py
python main.py health
python main.py tools-list
```

推荐手动 smoke：

1. “你好”
2. 上传宏观排放文件并计算。
3. “解释一下刚才结果里最高的路段是什么意思”
4. “继续做扩散”
5. 触发参数确认并回复选项。
6. “PM2.5 是什么”
7. 连续对话 8-10 轮后，追问第 1 轮的内容（例如“我最开始上传的文件有几行数据”），验证分层记忆可检索早期事实。
8. 重启 session/process 后确认上下文可恢复。

### 回滚点

- 关闭 `ENABLE_LLM_RETRY_BACKOFF`。
- 关闭 `ENABLE_CONVERSATION_FAST_PATH`。
- 关闭 `ENABLE_LAYERED_MEMORY_CONTEXT`。
- 关闭 `ENABLE_LIVE_STATE_PERSISTENCE`。
- 回滚 idle cleanup 调度入口，保留手动 cleanup 方法。

### 是否允许并行

部分允许。

可并行：

- retry/backoff tests
- session cleanup tests
- conversational prompt polish
- observability logging

必须串行：

- final integration
- full `pytest -q`
- final smoke verification

---

## 7. 跨工作包验收标准

升级完成前必须满足：

1. 现有核心工具链仍可运行。
2. 任务型输入仍进入 state loop 和工具选择。
3. 闲聊/解释/知识问答在安全条件下可走轻量路径。
4. 参数确认、输入补全、文件关系解析、残余任务恢复不被 fast path 绕过。
5. synthesis payload、file context、memory context 均有明确上限。
6. session restart 后关键上下文可恢复。
7. 日志包含可观测信息但不泄露 secrets 或大型 payload。
8. 全量验证命令通过，或所有失败均有明确非本升级原因说明。

---

## 8. 建议交付方式

### 顺序执行（推荐）

适合当前 dirty working tree：

```bash
$ralph "Implement approved EMISSIONAGENT conversation upgrade plan sequentially. Preserve unrelated working tree changes. Start with Phase 0 baseline, then WP-CONV-1. Do not advance work packages without targeted tests passing."
```

### Team 并行执行

仅在 Phase 0 完成且文件 ownership 明确后使用：

```bash
$team "Implement approved EMISSIONAGENT conversation upgrade plan in staged work packages. Preserve unrelated working tree changes. Split lanes by files/modules and require targeted tests before merge."
```

建议 team lanes：

1. Foundation lane：`core/router.py`、`core/router_render_utils.py`、`core/assembler.py`、`services/llm_client.py`
2. Conversation lane：`core/conversation_intent.py`、`core/conversation_handlers.py`、router fast-path tests
3. Memory/persistence lane：`core/memory.py`、`api/session.py`、session tests
4. Verification lane：targeted pytest、integration scripts、full pytest、manual smoke checklist

---

## 9. Final Verification Checklist

```bash
git status --short
pytest -q tests/test_router_state_loop.py tests/test_assembler_skill_injection.py tests/test_router_contracts.py tests/test_session_persistence.py
pytest -q tests/test_context_store.py tests/test_context_store_integration.py tests/test_context_store_scenarios.py
pytest -q tests/test_intent_resolution.py tests/test_summary_delivery.py
python scripts/utils/test_new_architecture.py
python scripts/utils/test_api_integration.py
python main.py health
python main.py tools-list
pytest -q
```

Final report must include：

- changed files
- simplifications made
- verification evidence
- remaining risks
- feature flags and rollback instructions
