# EmissionAgent Multi-Turn Conversation Upgrade Report

> 本报告总结 EmissionAgent 多轮对话升级的**最终实际完成情况**。  
> 依据文件：  
> - `EMISSIONAGENT_CONVERSATION_UPGRADE_PLAN.md`  
> - `docs/upgrade/UPGRADE_EXECUTION_PLAN.md`  
> - `docs/upgrade/WP-CONV-1_REPORT.md`  
> - `docs/upgrade/WP-CONV-2_REPORT.md`  
> - `docs/upgrade/WP-CONV-3_REPORT.md`  
> - `docs/upgrade/WP-CONV-4_REPORT.md`

---

## 1. Executive Summary

本次升级按 `WP-CONV-1` 至 `WP-CONV-4` 四个阶段完成，采用执行计划中批准的 **Option A — staged minimal overlay** 路线：不重写 `UnifiedRouter`，不引入大规模新架构，而是在现有 router、memory、context store、executor、readiness/recovery 机制上做最小侵入增强。

最终实际完成的核心变化包括：

1. 修复基础上下文与稳定性问题：模型配置生效、synthesis 大 payload 裁剪、FileContext 列名限额、token telemetry、live state persistence。
2. 增加保守版 conversation intent router：闲聊、结果解释、知识问答可在安全条件下走轻量 fast path；任务型请求仍走原 state loop。
3. 实现 in-place layered memory：short-term recent turns、mid-term summaries、long-term facts，并通过统一 API 同时服务 fast path 与 state loop。
4. 完成收尾可靠性：LLM transient retry/backoff、流程态持久化补齐、idle session cleanup、安全可观测性日志。

所有阶段均保留 feature flag / rollback 点，并避免将 fast path 置于现有任务恢复、参数确认、输入补全、文件关系解析、summary delivery 等关键流程之上。

---

## 2. Upgrade Objectives vs Actual Delivery

| 原始目标 | 实际完成情况 |
|---|---|
| 修复 Router 模型未使用配置的问题 | 已完成。Router 不再 hardcode `qwen-plus`，改为使用配置的 agent LLM。 |
| 修复 synthesis 大对象注入 | 已完成。对 raster/grid/GeoJSON/map/features 等重 payload 做 copy-only stripping。 |
| 修复 FileContext 列名膨胀 | 已完成。宽表列名被 bounded preview + omitted count 替代。 |
| 增加 token telemetry | 已完成。`chat` / `chat_with_tools` / `chat_json` 支持 usage 提取和日志。 |
| 增加意图路由器 | 已完成保守版。支持 chitchat/explain/knowledge fast path，并严格阻断活跃任务态。 |
| 增加分层记忆 | 已完成 in-place 版本。复用 `MemoryManager`，未引入首轮 `memory_v2.py`。 |
| 增加流程态持久化 | 已完成并补齐。支持 context store、parameter negotiation、input completion、continuation、file relationship、intent resolution。 |
| 增加 LLM retry/backoff | 已完成。仅对 transient connection failures 重试，非连接错误 fail fast。 |
| 增加 idle cleanup | 已完成安全版本。只移除内存 session，不删除持久化文件。 |
| 增强 observability | 已完成基础版本。模型、token、fast-path decision、prompt/context length、retry attempt 均有日志。 |

---

## 3. WP-CONV-1 — Foundation Fixes & Telemetry

### 3.1 实际改动

WP-CONV-1 完成了基础修复和观测能力，解决多轮对话升级前的 P0/P1 问题。

完成项：

1. **Router model config fix**
   - `UnifiedRouter` 不再使用 `get_llm_client("agent", model="qwen-plus")`。
   - 改为 `get_llm_client("agent")`，让 `AGENT_LLM_MODEL` / config 默认值真正生效。
   - 初始化时记录 resolved model。

2. **Synthesis payload stripping**
   - 在 `filter_results_for_synthesis()` 中增加 copy-only heavy payload stripping。
   - 裁剪对象包括 raster grid、concentration grid、contour、GeoJSON、features、map_data 等。
   - 保证原始 tool result 不被 mutation，避免破坏 frontend/context-store/downstream `_last_result`。

3. **FileContext column cap**
   - `ContextAssembler._format_file_context()` 对宽表 columns 做上限控制。
   - 保留 filename、file path、task_type、row_count。
   - 用 bounded preview + omitted count 替代无界列名拼接。

4. **Token telemetry**
   - `LLMResponse` 增加 optional `usage` 字段。
   - `services/llm_client.py` 支持从 OpenAI-compatible response 中提取 usage。
   - 对 `chat`、`chat_with_tools`、`chat_json` 记录 `[TOKEN_TELEMETRY]`。

5. **Live router state persistence**
   - 增加 versioned persistence envelope。
   - 支持恢复 context store、parameter negotiation、input completion、continuation bundle。
   - 保留 legacy context-store-only payload 恢复能力。

### 3.2 核心文件

实现文件：

- `.env.example`
- `api/session.py`
- `config.py`
- `core/assembler.py`
- `core/router.py`
- `core/router_render_utils.py`
- `services/llm_client.py`

测试文件：

- `tests/test_assembler_skill_injection.py`
- `tests/test_config.py`
- `tests/test_router_contracts.py`
- `tests/test_session_persistence.py`
- `tests/test_llm_client_telemetry.py`
- `tests/test_router_llm_config.py`

文档 / 基线：

- `docs/upgrade/WP-CONV-1_BASELINE.md`
- `docs/upgrade/WP-CONV-1_REPORT.md`

### 3.3 验证结果

WP-CONV-1 报告记录的最终验证：

| 验证命令 | 结果 |
|---|---|
| `pytest -q tests/test_router_llm_config.py tests/test_llm_client_telemetry.py tests/test_router_state_loop.py tests/test_assembler_skill_injection.py tests/test_router_contracts.py tests/test_session_persistence.py tests/test_config.py` | **104 passed**, 8 warnings |
| `pytest -q tests/test_phase1b_consolidation.py` | **5 passed**, 1 warning |
| `python -m py_compile core/router.py core/assembler.py core/router_render_utils.py services/llm_client.py api/session.py config.py` | passed |
| `python main.py health` | passed, 9 tools OK |
| `python main.py tools-list` | passed, 9 tools listed |

---

## 4. WP-CONV-2 — Conservative Conversation Intent Router

### 4.1 实际改动

WP-CONV-2 实现了保守版 conversation fast path。该阶段没有重构 router 主结构，而是在 `UnifiedRouter.chat()` 中、进入 `_run_state_loop()` 前增加 fast-path 判断。

完成项：

1. **Feature flag**
   - 新增 `ENABLE_CONVERSATION_FAST_PATH`。
   - 作为 WP-CONV-2 行为的主 rollback gate。

2. **Conversation intent classifier**
   - 新增 `core/conversation_intent.py`。
   - 支持意图：
     - `CHITCHAT`
     - `EXPLAIN_RESULT`
     - `KNOWLEDGE_QA`
     - `NEW_TASK`
     - `CONTINUE_TASK`
     - `MODIFY_PARAMS`
     - `RETRY`
     - `UNDO`
     - `CONFIRM`
     - `UNKNOWN`
   - 规则优先，且默认保守：宁可进入 state loop，也不把任务误判为闲聊。

3. **Fast path integration**
   - 集成点固定在 `UnifiedRouter.chat()`，位于 `_run_state_loop()` 前。
   - 这样 chitchat / simple explain / knowledge QA 不需要白跑 state-loop live state apply/restore、文件关系检查和恢复上下文逻辑。

4. **Fast path handlers**
   - chitchat：使用 `llm.chat()`。
   - explain-result：使用 bounded last tool / context summary。
   - knowledge-QA：复用 `ToolExecutor.execute("query_knowledge", ...)`，不绕过工具边界。

5. **Hard blockers**
   - active parameter negotiation
   - active input completion
   - file relationship clarification
   - residual workflow / continuation
   - incoming file upload
   - summary-delivery-like output-mode requests
   - confirmation-like replies

### 4.2 核心文件

实现文件：

- `.env.example`
- `config.py`
- `core/router.py`
- `core/conversation_intent.py`

测试文件：

- `tests/test_config.py`
- `tests/test_router_state_loop.py`
- `tests/test_conversation_intent.py`

文档：

- `docs/upgrade/WP-CONV-2_REPORT.md`

### 4.3 验证结果

WP-CONV-2 报告记录的验证：

| 验证命令 | 结果 |
|---|---|
| `pytest -q tests/test_conversation_intent.py tests/test_config.py` | **17 passed**, 4 warnings |
| `pytest -q tests/test_router_state_loop.py` | **65 passed** |
| `pytest -q tests/test_conversation_intent.py tests/test_router_state_loop.py tests/test_config.py tests/test_router_llm_config.py tests/test_phase1b_consolidation.py` | **88 passed**, 8 warnings |
| `python -m py_compile core/conversation_intent.py core/router.py config.py` | passed |

---

## 5. WP-CONV-3 — In-place Layered Memory

### 5.1 实际改动

WP-CONV-3 实现了分层记忆，但没有引入首轮 `memory_v2.py`，而是对现有 `MemoryManager` 做 backward-compatible 增强。

完成项：

1. **Short-term memory**
   - 保留 recent turns 机制。
   - `Turn` 增加 `turn_index`。
   - 增加共享 API：`build_conversational_messages(...)`。
   - fast path 使用该 API 作为短期历史来源。

2. **Mid-term memory**
   - 新增 `SummarySegment`。
   - 新增 `MemoryManager.mid_term_memory`。
   - 每 3 轮生成一次规则摘要。
   - 最多保留 5 段。
   - 每段最多 200 chars。
   - 同步到 legacy `compressed_memory`，保持兼容。

3. **Long-term memory**
   - 扩展 `FactMemory`：
     - `session_topic`
     - `user_language_preference`
     - `cumulative_tools_used`
     - `key_findings`
     - `user_corrections`
   - 旧字段保持不变，并支持旧 JSON 加载。

4. **Shared memory context**
   - 新增 `MemoryManager.build_context_for_prompt(max_chars=...)`。
   - fast path 与 state loop 共用该 memory context。
   - `ContextAssembler.assemble(..., memory_context=...)` 支持在 legacy / skill mode 下统一注入。

5. **Token / context bounds**
   - fast-path history 最多 5 轮。
   - fast-path assistant 每轮最多 1200 chars。
   - mid-term 5 段 × 200 chars。
   - memory prompt context 默认最多 1800 chars。
   - 禁止注入 raw `last_spatial_data`、raster、concentration matrix、GeoJSON/features、map payload、无界历史。

### 5.2 核心文件

实现文件：

- `.env.example`
- `config.py`
- `core/memory.py`
- `core/assembler.py`
- `core/router.py`

测试文件：

- `tests/test_layered_memory_context.py`
- `tests/test_assembler_skill_injection.py`
- `tests/test_router_state_loop.py`
- `tests/test_config.py`

文档：

- `docs/upgrade/WP-CONV-3_REPORT.md`

### 5.3 验证结果

WP-CONV-3 报告记录的验证：

| 验证命令 | 结果 |
|---|---|
| `pytest -q tests/test_layered_memory_context.py` | **4 passed** |
| `pytest -q tests/test_layered_memory_context.py tests/test_assembler_skill_injection.py tests/test_router_state_loop.py tests/test_config.py` | **94 passed**, 4 warnings |
| `pytest -q tests/test_layered_memory_context.py tests/test_conversation_intent.py tests/test_assembler_skill_injection.py tests/test_router_state_loop.py tests/test_session_persistence.py tests/test_config.py` | **104 passed**, 8 warnings |
| `python -m py_compile core/memory.py core/assembler.py core/router.py config.py` | passed |

---

## 6. WP-CONV-4 — Final Reliability / UX Polish

### 6.1 实际改动

WP-CONV-4 完成最后阶段收尾优化，保持 surgical changes，没有重构 WP-CONV-2 router 主结构，也没有重新设计 WP-CONV-3 memory schema。

完成项：

1. **LLM retry/backoff**
   - 新增 `ENABLE_LLM_RETRY_BACKOFF`。
   - `_request_with_failover()` 支持 transient connection failures 的 bounded retry。
   - 保持 proxy → direct failover。
   - 非连接错误 fail fast。
   - 测试中通过 injectable `_retry_sleep` 避免真实 sleep。

2. **Conversational system prompt 优化**
   - 明确要求不能假装工具已执行。
   - 支持根据 `user_language_preference` 加入语言偏好提示。
   - 增加 prompt length / context length 安全日志，不记录 raw prompt 或 secrets。

3. **Session flow-state persistence completion**
   - WP-CONV-1 已覆盖 parameter negotiation、input completion、continuation bundle。
   - WP-CONV-4 补齐：
     - file relationship bundle
     - intent resolution bundle

4. **Idle session cleanup**
   - 新增 `SessionManager.cleanup_idle_sessions(ttl_hours=None)`。
   - 默认 TTL：72 小时。
   - 仅从内存移除 session，不删除 persisted history/router_state/memory 文件。

5. **Basic observability**
   - retry attempts 记录 attempt count 和 delay。
   - token telemetry 保持启用。
   - fast-path decision logging 保持启用。
   - conversational prompt length/context length logging 启用。

### 6.2 核心文件

实现文件：

- `.env.example`
- `api/session.py`
- `config.py`
- `core/router.py`
- `services/llm_client.py`

测试文件：

- `tests/test_config.py`
- `tests/test_llm_client_telemetry.py`
- `tests/test_router_state_loop.py`
- `tests/test_session_persistence.py`

文档：

- `docs/upgrade/WP-CONV-4_REPORT.md`

### 6.3 验证结果

WP-CONV-4 报告记录的验证：

| 验证命令 | 结果 |
|---|---|
| `pytest -q tests/test_llm_client_telemetry.py tests/test_session_persistence.py tests/test_router_state_loop.py tests/test_config.py` | **84 passed**, 8 warnings |
| `pytest -q tests/test_llm_client_telemetry.py tests/test_session_persistence.py tests/test_router_state_loop.py tests/test_config.py tests/test_conversation_intent.py tests/test_layered_memory_context.py` | **96 passed**, 8 warnings |
| `python -m py_compile services/llm_client.py api/session.py core/router.py config.py` | passed |
| `python main.py health` | passed, 9 tools OK |
| `python main.py tools-list` | passed, 9 tools listed |

---

## 7. System Capability Improvements

### 7.1 Multi-turn continuity

升级前系统主要依赖 recent working memory、fact slots 和 context-store summary；旧对话细节容易在短窗口外丢失。

升级后：

- short-term recent turns 仍保留，用于局部连续性。
- mid-term summaries 每 3 轮生成一次，最多保留 5 段。
- long-term facts 保存 session topic、language preference、tools used、key findings、corrections 等结构化信息。
- state loop 与 fast path 共用 `MemoryManager` 的 memory context API，避免记忆行为分裂。
- live workflow state 在 session reload 后更完整可恢复。

实际提升：第 8-10 轮后追问早期事实时，系统具备通过 bounded summaries / facts 找回早期上下文的基础能力。

### 7.2 Intent routing

升级前所有用户输入倾向于进入完整状态机，即使是“你好”“解释一下刚才结果”“PM2.5 是什么”这类轻量对话。

升级后：

- chitchat、explain-result、knowledge-QA 可在安全条件下走 fast path。
- 任务型请求、继续任务、参数修改、确认回复、summary-delivery-like 输出请求仍进入 state loop。
- active negotiation、input completion、file relationship clarification、residual workflow、新文件上传等状态会阻断 fast path。

实际提升：降低非任务型消息的状态机开销，同时保持工具任务正确性。

### 7.3 Layered memory

升级后 `MemoryManager` 从简单 working memory + fact memory + compressed string，扩展为：

- short-term：recent turns
- mid-term：bounded `SummarySegment`
- long-term：structured facts

并提供：

- `build_conversational_messages(...)`
- `build_context_for_prompt(...)`

实际提升：fast path 和 state loop 可共享一致的记忆上下文，避免一个路径“记得”、另一个路径“不记得”。

### 7.4 Stability and observability

升级后新增或增强：

- model resolution logging
- token usage telemetry
- synthesis payload stripping
- FileContext column caps
- transient LLM retry/backoff
- live state persistence
- prompt/context length logging
- retry attempt logging
- idle in-memory session cleanup

实际提升：系统更不容易因单轮大 payload、宽表列名、网络瞬断或 session reload 而破坏对话连续性。

---

## 8. Feature Flags and Rollback Points

| Feature flag | Purpose | Rollback behavior |
|---|---|---|
| `ENABLE_CONVERSATION_FAST_PATH` | 控制 WP-CONV-2 fast path | 关闭后回到原 state-loop/legacy routing。 |
| `ENABLE_LAYERED_MEMORY_CONTEXT` | 控制 WP-CONV-3 memory context 注入 | 关闭后保留 memory 数据，但不注入 prompt。 |
| `ENABLE_LIVE_STATE_PERSISTENCE` | 控制 live router state persistence | 关闭后回到 legacy context-store persistence。 |
| `ENABLE_LLM_RETRY_BACKOFF` | 控制 transient LLM retry/backoff | 关闭后仅保留原 failover 行为。 |

其他可回滚点：

- synthesis payload stripping 可单独回滚 `core/router_render_utils.py` 对 synthesis payload 的裁剪逻辑。
- FileContext column cap 可通过调整 cap 或回滚 `_format_file_context()` 的列名 preview 逻辑处理。
- idle cleanup 不会自动删除持久化文件；如不使用，不调用 `cleanup_idle_sessions()` 即可。

---

## 9. Current Remaining Limitations

1. **Fast path intentionally conservative**  
   部分边界消息仍会进入 state loop。这是为了避免误判任务输入，属于有意设计。

2. **Knowledge-QA naturalization 仍较轻量**  
   当前 knowledge fast path 主要返回工具 summary；如需要更自然的解释风格，后续可在安全范围内增加 LLM naturalization，但需控制 token 和失败路径。

3. **Layered memory 是规则摘要，不是语义检索系统**  
   mid-term summary 当前是 deterministic/rule-based，不是 embedding retrieval；能覆盖早期事实和工具摘要，但不等于完整长期语义记忆。

4. **Memory schema 扩展带来迁移风险**  
   当前支持旧 JSON 加载，但未来若 live-state 或 memory payload 引入复杂对象，仍需版本化迁移策略。

5. **Prompt observability 只记录长度级信息**  
   为避免泄露和日志膨胀，目前不记录 raw prompt。若未来需要更深诊断，应增加 redaction / sampling 机制。

6. **尚未记录完整真实 LLM API 压测数据**  
   已具备 telemetry，但实际 token、延迟、成本分布仍需在真实会话中持续采集。

7. **当前工作树仍较宽**  
   执行过程中多次保留了既有 unrelated dirty tree。合并前应按 WP scoped diff 分组 review/stage，避免混入无关修改。

---

## 10. Follow-up Recommendations

### 10.1 合并前建议

1. 按工作包分组 review：
   - WP-CONV-1 foundation
   - WP-CONV-2 intent router
   - WP-CONV-3 layered memory
   - WP-CONV-4 polish
2. 确认 unrelated dirty-tree 修改不混入本次升级提交。
3. 对 `core/router.py` 和 `core/memory.py` 做重点 code review，因为它们是最大风险文件。
4. 保留 feature flags 默认值，但在生产启用前准备快速回滚说明。

### 10.2 上线前建议

运行完整验证：

```bash
pytest -q
python scripts/utils/test_new_architecture.py
python scripts/utils/test_api_integration.py
python main.py health
python main.py tools-list
```

并建议手动 smoke：

1. “你好”
2. 上传宏观排放文件并计算
3. “解释一下刚才结果里最高的路段是什么意思”
4. “继续做扩散”
5. 触发参数确认并回复选项
6. “PM2.5 是什么”
7. 连续对话 8-10 轮后追问第 1 轮内容，例如“我最开始上传的文件有几行数据”
8. 重启 session/process 后确认上下文恢复

### 10.3 后续增强建议

1. 基于 telemetry 分析 fast path 与 state loop 的 token/latency 差异。
2. 对 memory summaries 做真实多轮对话评估，必要时优化摘要模板。
3. 为 knowledge-QA 增加可选 naturalization，但需保留工具失败 fallback。
4. 若长期对话需求继续增长，再评估 embedding-based retrieval 或独立 memory subsystem；当前阶段不建议立即重写。
5. 将 prompt/context length observability 与 trace UI 或诊断报告对接，方便后续排查。

---

## 11. Final Status

本次 EmissionAgent 多轮对话升级已经按四阶段完成：

- `WP-CONV-1`: foundation fixes and telemetry — **complete**
- `WP-CONV-2`: conservative conversation intent router — **complete**
- `WP-CONV-3`: in-place layered memory — **complete**
- `WP-CONV-4`: final reliability / observability polish — **complete**

整体结果：系统从“主要依赖短窗口和少量 fact slots 的任务型 agent”，升级为“具备安全 fast path、分层记忆、可恢复流程态、上下文限额和基础可观测性”的多轮对话垂域智能体。
