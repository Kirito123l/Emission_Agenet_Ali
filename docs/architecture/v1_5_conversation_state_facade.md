# v1.5 ConversationState Facade — Schema & Hand-off Specification

**Document path**: `docs/architecture/v1_5_conversation_state_facade.md`
**Version**: **frozen v2** (拍板完成 2026-05-05, kirito approved)
**Last updated**: 2026-05-05
**Branch**: `phase9.1-v1.5-upgrade`

---

## §0. Document Status & Conventions

### Status

| Field | Value |
|---|---|
| Status | **frozen v2** (kirito approved 2026-05-05) |
| Frozen tag (target) | `v1.5-design-frozen` (跟其他 component 文档一起打) |
| Supersedes | None (this is the first ConversationState design) |
| References Part 1 frozen | Yes — 引用 `docs/architecture/v1_5_design_principles.md` 作 ground truth |
| Referenced by | Part 2 后续 10 个 component 文档 (component #2 - #11), Part 4 实施工作分解 |
| Frozen 后修改流程 | 仅 §11 open question 实施期解决时回头更新对应章节. 其他章节 frozen 不可改动, 改动须回到设计阶段 review. |

### 命名约定

- **facade field**: 业务语义命名, 全小写下划线, 不带 store 前缀 (例如 `pending_chain` 不是 `ao_pending_chain`)
- **underlying store key/path**: 反映 store 实际命名 (例如 `ao.metadata["execution_continuation"]`)
- **routing**: facade field → underlying store 的映射, 见 §5 完整路由表
- **read-through / write-through**: facade 不存数据, 读写都路由到底层 store

### file:line 引用规范

- 文档内 file:line 引用基于 `phase9.1-v1.5-upgrade` 分支 HEAD `34c2758` (`v1.5-trace-fix-verified` tag) 当时代码状态
- 实施期 cc 验证时若 file:line 偏移, 按 spec 意图对齐当前代码, 偏离在 commit message 显式记录

### 阅读建议

- 第一次读: §1 - §3 (背景 + 设计决策 + Anchors compliance)
- 实施 cc 主要参考: §4 (字段 schema) + §5 (路由表) + §7 (hand-off contracts) + §12 (Codex validation hooks)
- 设计 review: 全文

---

## §1. Background & Scope

### 1.1 为什么需要 facade

阶段 1 audit 数据 (6 轮 audit, 见 Appendix C 引用) 收敛出 v1.0 架构在跨 contract 协同上的具体瓶颈:

**mode_A 5/5 reproduced (Step 1 variance characterization)**: Run 7 三 turn 任务在 v1.0 frozen 代码 + current LLM 下稳定失败 — Turn 1 calculate_macro_emission 成功, Turn 2 chain projection 完全不发生 (`projected_chain` 在 15/15 turn-trial 全部 absent), Turn 3 stuck. 失败 root cause 不是单一 contract 的 bug, 是**跨 contract 没有 single source of truth**:

- AO classifier 在 Turn 2 把 "对刚才的排放结果做扩散模拟" 5/5 分类为 NEW_AO, 不是 CONTINUATION
- IntentResolver 不规划 multi-step chain, 每个 AO 只单工具
- ExecutionContinuation 的 `pending_tool_queue` 永远空
- ClarificationContract / Reconciler 各自读各自的 `ao.metadata` namespace, 互相不知道对方写了什么

4 个 state machine 各自工作但**没有跨 machine 的共享状态对象**. 加新 contract / 改某个 contract 都不能解决 mode_A — 必须有协调层.

### 1.2 Facade vs 新独立 store 的 trade-off

设计阶段拍板路线: **facade**, 不引入第 4 个 store.

| 选项 | 含义 | 选择理由 |
|---|---|---|
| 新独立 store | 标准 ConversationState class + 自己的持久化 | **不选** — 跟现有 3 个 cross-turn store (SessionContextStore / FactMemory / ao.metadata) 形成 split-brain 风险 |
| **Facade (read-through + write-through)** | 业务语义层包装现有 3 个 store, 不复制数据 | **选** — 不引入数据冗余, NaiveRouter 隔离自然继承, 但需要清晰的 routing table |

facade 是 v1.5 唯一的"新对象", 但它本身**不持久化数据**. 所有跨 turn 状态仍由现有 store 提供 (SessionContextStore + FactMemory + ao.metadata + AOExecutionState).

### 1.3 设计目标

facade 直接服务 Part 1 §1.7 的能力 1+2+3:

| 能力 | facade 的具体职责 |
|---|---|
| 能力 1: 自动多步推进 | 提供 chain state 字段 (§4.2), 让 IntentResolver 写 `pending_chain`, ExecutionContinuation 读 `pending_chain` 自动推进, 跨 turn 持久化 |
| 能力 2: 隐式上下文 | 提供 parameter state 字段 (§4.3), 让 "再算一次" 类指令复用 `last_referenced_params` |
| 能力 3: 对话修正 | 提供 clarification state 字段 (§4.4), AO classifier REVISION 触发 `revision_invalidated_steps` 写入, IntentResolver re-plan |

### 1.4 不解决的问题

明确不在 v1.5 facade scope (留 v2 或永远不做):

- 跨 session memory (long-term user history)
- 多 user 共享 state
- ConversationState 自身持久化机制 (facade 不存数据)
- LLM 直接读写 facade (LLM 通过 contract pipeline 间接交互)
- Reactive subscription / observer pattern (v1.5 不引入)
- 物理 store 重构 (SessionContextStore / FactMemory / ao.metadata 内部实现不动)

---

## §2. Core Design Decisions

### 2.1 Facade 是 read-through + write-through 协调层

facade 不是 cache, 不是新 store, 不是中间状态. 是一个**业务语义包装**:

- **Read**: facade.get('field') → 路由到底层 store 的对应 key, 实时取值
- **Write**: facade.set('field', value) → 路由到底层 store 写入, 立即生效

facade 自身不维护任何数据副本. 这意味着:
- facade.get() 总是返回底层 store 当前值, 不存在 facade-vs-store 不一致
- facade write 立即 visible 给所有读底层 store 的代码 (包括不通过 facade 读的代码)
- 进程重启后 facade 重新实例化, 状态完全从底层 store 重建

### 2.2 底层 store 不变

| 底层 store | 文件位置 | facade 用途 |
|---|---|---|
| `SessionContextStore` | `core/context_store.py` | 工具结果 / 文件 grounding 结果 / cross-turn artifacts |
| `FactMemory` | `core/memory.py` | recent_vehicle / recent_pollutants / session_confirmed_parameters / ao_history |
| `ao.metadata` | `core/analytical_objective.py:523` (per-AO dict) | clarification_contract / execution_continuation / parameter_snapshot |
| `AOExecutionState` | `core/analytical_objective.py:262-271` | planned_chain / chain_cursor / chain_status |

v1.5 不动这 4 个 store 的内部实现. facade 只是新增的读写入口.

### 2.3 Governed-only 严格隔离

按 Part 1 §1.4 拍板, 落地到 facade 实现:

- facade 模块 (`core/conversation_state_facade.py`) **不被 NaiveRouter 导入**
- facade write 由 governed pipeline 触发 (具体写入点见 §7 hand-off contracts)
- 共享 ToolRegistry 单例继续 read-only
- 持久化路径通过 session_id 命名区分, 不强制目录分离

实施期 cc 必须验证: `grep -r "conversation_state_facade" core/naive_router.py` 必须**零命中**, 否则 STOP & report.

### 2.4 Atomicity — Fail-Fast (拍板已完成)

**拍板**: facade write 任一失败 → 立即抛异常停止当前 turn 处理. 已成功的 write 保留 (不 rollback), 失败处由 caller (governed pipeline 主流程) 处理.

| 选项 | 含义 | 决议 |
|---|---|---|
| Fail-fast (write-and-stop) | 失败立即抛异常, 已写入保留 | **选** |
| Best-effort (continue on error) | 部分失败, 继续后续 write | 不选 — silent failure 风险 |
| Transactional (all-or-nothing) | 要么全成功要么全 rollback | 不选 — 底层 store 大概率不支持 transaction |

理由:
- 跟现有 governance pipeline fail-fast 模式一致 (Phase 8.2.5 `STANDARDIZATION_FAILED_BLOCKED_EXECUTION` enforce 同样模式)
- 实现简单, 不需要 transaction 支持
- 保证 state 一致性, 不出现 "半写" 状态
- 错误对用户可见, 不是 silent degradation

注意: "已写入保留" 跟 "rollback" 之间的实施细节留 §11 Open Q5 决定.

### 2.5 Read consistency — Read-Your-Writes Within Turn

facade read 的 consistency 保证:

- **同 turn 内**: read-your-writes — 当前 turn 写入立即可见 (因为 write-through, 底层 store 已经更新)
- **跨 turn**: 依赖底层 store 持久化 — 读到的是上 turn 持久化后的值
- **进程重启后**: 完全从底层 store 重建, 无 facade 自身持久化

不保证:
- 跨 process 实时一致 (单 session 串行假设, 见 §6.5)
- 跨 session 状态共享 (按 §1.4)

### 2.6 跟 Part 1 §1.4 隔离机制的具体落地点

| Part 1 约束 | facade 实施细节 |
|---|---|
| NaiveRouter 不导入 facade 模块 | `core/conversation_state_facade.py` 不出现在 `naive_router.py` import 中 |
| facade 写入由 governed pipeline 触发 | §7 11 个 hand-off contract 列出所有合法写入点 |
| 共享 ToolRegistry read-only | facade 不引入对 ToolRegistry 的 mutation API |
| session_id 命名区分 | facade 实例从 `session_id` 派生, NaiveRouter session_id 跟 governed_router session_id 命名空间不重叠 |

---

## §3. Anchors Compliance Checklist

设计前置约束, 不是事后检查. 任何 facade 设计变化必须先过这个 checklist.

### 3.1 跟核心论点 (framework deterministic + LLM semantic) 一致性

| Aspect | 跟核心论点关系 |
|---|---|
| facade write-through | framework 强制单一写入路径, deterministic ✓ |
| facade read-through | LLM 不直接读 facade, 通过 contract pipeline ✓ |
| atomicity fail-fast | framework 强制状态一致性 ✓ |
| `pending_chain` 字段 | LLM (IntentResolver prompt) 主导 chain 内容, framework 保证 chain 跨 turn 持久 ✓ |
| `revision_invalidated_steps` | LLM 决定 REVISION 语义, framework 强制 invalidation 实际发生 ✓ |

**Verdict**: facade 强化核心论点, 不改变它. 所有 facade 字段都符合 "framework deterministic enforcement of LLM-driven semantic decisions".

### 3.2 跟选题定位 (架构 / 工程 / 系统贡献) 一致性

facade 是**架构层组件** — 跨 4 个 state machine 的协调层, 不是 LLM 算法改进, 不是 prompt engineering, 不是模型微调.

新增的 IntentResolver multi-step planning (component #3) prompt 设计是 LLM-side, 但本 facade 文档不涉及 prompt — 那是 component #3 文档的职责.

**Verdict**: facade 是架构贡献, 跟定位一致.

### 3.3 跟 3 类失败模式分类一致性

| 失败模式 | facade 对应字段 |
|---|---|
| 多轮状态漂移 | `current_objective`, `objective_owner_ao_id`, `last_user_intent` (§4.1) |
| 跳步执行 | `pending_chain`, `completed_steps`, `chain_owner_ao_id` (§4.2) |
| 参数组合非法 | `last_referenced_params`, `parameter_validity_window` (§4.3) — 协助 cross-constraint check 的跨 turn 上下文 |

**Verdict**: facade 字段映射到 3 类失败模式, 不引入第 4 类.

### 3.4 跟 4 评估层次一致性

| 层次 | facade 影响 |
|---|---|
| Layer 1 标准化准确率 | 不影响 — facade 不改变 standardization 逻辑 |
| Layer 2 端到端 | facade 是 v1.5 vs v1.0 delta 的核心来源, Phase 9.3 ablation 重点 |
| Layer 3 Shanghai e2e | facade 修复 mode_A, Run 7 跑通 |
| Layer 4 用户研究 | 升级完成后启动, 不在 v1.5 设计范围 |

**Layer 2 facade 贡献验证**: Phase 9.3 ablation 设 facade-disabled run (具体 run 编号待 Phase 9.3 protocol 定), 跟 governance_full 比较得出 facade 单独贡献.

**Verdict**: facade 直接影响 Layer 2 + Layer 3, 不影响 Layer 1 + Layer 4.

### 3.5 NaiveRouter 隔离 compliance

facade write 由以下组件触发, 全部在 governed pipeline 内:
- OASCContract (§7.1)
- IntentResolver (§7.2)
- AO classifier (§7.3)
- ExecutionContinuation (§7.4)
- ClarificationContract (§7.5)
- Reconciler (§7.6)
- Conversation_fast_path (§7.7)
- Standardizer fallback (§7.8)
- PCM 文件上下文 (§7.9)
- DependencyContract (§7.10)
- Reconciler fall-through (§7.11)

NaiveRouter 不在列表中. NaiveRouter 不读不写 facade.

**NaiveRouter 隔离 grep 验证**: 见 §5 "新增字段隔离约束" 段, 实施期 cc 必须验证 0 命中. 任一命中触发 STOP & report, 不得绕过.

**Verdict**: 隔离守住, ablation delta 干净.

---

## §4. Field Schema

### Schema 性质 — Maximum, Not Minimum

本章列 19 个 field. **这是 maximum** — 设计期罗列充分, 实施期 (Phase 9.1.1+) 如果发现某些字段不真需要 (例如某 contract 实际不需要某字段就能满足职责), 可以删. 不能在实施期加新字段, 加字段需要回到设计阶段 review.

实施期删字段触发 STOP & report, 让用户知道 schema 收敛情况, 不是 cc 单方面决定.

### 字段分组

5 组按业务语义命名:
- §4.1 Objective state — AO 跨 turn 身份跟当前用户意图
- §4.2 Chain state — multi-step planning 跟自动推进
- §4.3 Parameter state — 跨 turn 隐式上下文
- §4.4 Clarification state — 对话修正 + PCM
- §4.5 Reconciler / fallback state — borderline 决策跟 fast path 协同

### §4.1 Objective state

| Field | Type | 业务语义 |
|---|---|---|
| `current_objective` | `Optional[AO_id]` (str or None) | 当前 active AO 的 id. 跨 turn 持久, AO 完成后 None. |
| `objective_owner_ao_id` | `Optional[AO_id]` | objective 创建/最新 revise 时的 AO id. 跟 `current_objective` 多数时间相同, 在 REVISION 链中追溯到根 AO 时不同. |
| `objective_status` | `Enum` (`active` / `completed` / `blocked` / `revising`) | objective 当前 lifecycle 状态. 跟 AOStatus 6 lifecycle 双轴对齐. |
| `last_user_intent` | `Optional[str]` | 最近一 turn 用户消息 (raw text), 用于 IntentResolver / AO classifier 判断 CONTINUATION/REVISION. |

### §4.2 Chain state

| Field | Type | 业务语义 |
|---|---|---|
| `pending_chain` | `List[ToolPlan]` | IntentResolver multi-step planning 输出的待执行工具序列. 空列表表示无 pending. |
| `completed_steps` | `List[CompletedStep]` | 当前 objective 下已完成的步骤, 含工具名 / 参数 / 输出 reference / wall_time. |
| `chain_owner_ao_id` | `Optional[AO_id]` | pending_chain 跟 completed_steps 归属的 AO. 跟 `objective_owner_ao_id` 一致 (REVISION 也保持一致, REVISION 重置 chain). |
| `chain_origin_turn` | `Optional[int]` | pending_chain 第一次写入的 turn 号. 用于诊断 chain stall (例如 chain 跨 5 turn 没推进则警告). |
| `last_chain_advance_reason` | `Optional[str]` | 最近一次 chain 推进的触发原因 (例如 `tool_completed_advance` / `revision_replan` / `user_skip`). 主要用于 trace observability. |

### §4.3 Parameter state

| Field | Type | 业务语义 |
|---|---|---|
| `last_referenced_params` | `Dict[str, Any]` | 最近一次成功执行工具时的标准化参数. "再算一次" 类指令复用源. 包含 vehicle / pollutants / season / road_type / file_id 等. |
| `recent_tool_results_index` | `Dict[str, ResultRef]` | 跨 turn 工具结果索引 (canonical_token → result_ref). 路由到 SessionContextStore.get_result_availability. |
| `parameter_validity_window` | `int` (turn count) | last_referenced_params 的 staleness 边界. 默认 5 turn 后失效, 强迫重新询问. |

### §4.4 Clarification state

| Field | Type | 业务语义 |
|---|---|---|
| `pending_clarification_slot` | `Optional[ClarificationSlot]` | 当前等用户回答的参数 slot (slot_name / probe_count / probe_abandoned). |
| `clarification_origin` | `Optional[str]` | clarification 触发源 (`standardizer_fallback` / `pcm_optional` / `revision_param_change` 等). |
| `revision_invalidated_steps` | `List[step_id]` | REVISION 触发后被 invalidate 的 completed_steps id 列表. IntentResolver re-plan 时跳过这些 step. |
| `pcm_active` | `bool` | PCM (parameter collection mode) 是否激活. 跟 `ao.parameter_state.collection_mode` 一致. |

### §4.5 Reconciler / fallback state

| Field | Type | 业务语义 |
|---|---|---|
| `last_reconciler_decision` | `Optional[ReconciledDecisionRef]` | 最近一次 reconciler 输出 (decision_value / source_trace 摘要). 调试 + 跨 turn 诊断用. |
| `borderline_decision_marker` | `Optional[str]` | reconciler "clarify but empty question" fall-through 触发标记. component #11 写, ClarificationContract / IntentResolver 读. |
| `fast_path_blocking_signal` | `bool` | 当前是否有 pending_chain 阻止 conversation_fast_path 激活. component #6 读, derived from `pending_chain` non-empty. |

### Schema 字段总数

5 组 × 字段数 = 4 + 5 + 3 + 4 + 3 = **19 fields**.

---

## §5. Routing Table

下表是 schema → 底层 store 映射的 single source of truth. cc 实施期按本表对 file:line, 用户阶段 2 review 按本表 sanity-check 是否合理.

**表头说明**:
- `facade field` — §4 的字段名
- `underlying store` — 路由的底层 store 名
- `underlying key/path` — 在底层 store 内的具体 key 或属性
- `write-through 写法` — facade.set 时实际怎么写
- `read-through 读法` — facade.get 时实际怎么读
- `persistence` — 跨 turn 持久化机制
- `NaiveRouter visibility` — NaiveRouter 是否能从底层读到 (govern-only 隔离验证)

| facade field | underlying store | underlying key/path | write-through | read-through | persistence | NaiveRouter visibility |
|---|---|---|---|---|---|---|
| `current_objective` | `FactMemory` | `current_ao_id` (`memory.py:93`) | `fact_memory.current_ao_id = ao_id` + `_save()` | `fact_memory.current_ao_id` | JSON dump on `_save()` | YES (NaiveRouter doesn't import FactMemory anyway) |
| `objective_owner_ao_id` | `FactMemory` | `ao_history[-1].owner_ao_id` (扩展 AnalyticalObjective) | 通过 AOManager.create_ao / revise_ao | `fact_memory.ao_history[].owner_ao_id` 查 | JSON dump | NO (path through governance) |
| `objective_status` | `ao.metadata` | derived from `ao.status` (AOStatus enum) | facade.set 写 `ao.status` 通过 AOManager | `ao.status` 直接读 | ao_history 持久化 | NO |
| `last_user_intent` | `FactMemory` | new field `last_user_message` (FactMemory 加字段) | `fact_memory.last_user_message = msg` | `fact_memory.last_user_message` | JSON dump | NO |
| `pending_chain` | `ao.metadata` + `AOExecutionState` | `ao.metadata["execution_continuation"]["pending_tool_queue"]` + `ao.execution_state.planned_chain` (mirror) | facade.set 写两处, 失败任一即 fail-fast | 优先读 `ao.execution_state.planned_chain` | ao_history 持久化 | NO |
| `completed_steps` | `ao.metadata` | `ao.tool_call_log` 已存在 + 新加 `ao.metadata["completed_steps_index"]` | append 到 `tool_call_log`, 索引到 metadata | 读 `tool_call_log` 过滤成功 step | ao_history 持久化 | NO |
| `chain_owner_ao_id` | `ao.metadata` | derived — 等于当前 AO id | 不直接 set, derived | `current_ao.ao_id` | derived | NO |
| `chain_origin_turn` | `ao.metadata` | `ao.metadata["chain_origin_turn"]` (新加) | `ao.metadata["chain_origin_turn"] = turn_no` | `ao.metadata.get("chain_origin_turn")` | ao_history 持久化 | NO |
| `last_chain_advance_reason` | `ao.metadata` | `ao.metadata["last_chain_advance_reason"]` (新加) | 写 ao.metadata | 读 ao.metadata | ao_history 持久化 | NO |
| `last_referenced_params` | `FactMemory` | `session_confirmed_parameters` (`memory.py:88`) + `recent_vehicle/pollutants/year` 聚合 | facade.set 写聚合到 session_confirmed_parameters | 聚合读 | JSON dump | NO |
| `recent_tool_results_index` | `SessionContextStore` | `_store` (`context_store.py:66`) | facade write-through 通过 `context_store.put()` | `context_store.get_result_availability()` | context_store 持久化 (`router_state/`) | NO |
| `parameter_validity_window` | facade-internal config | const 默认 5 (不持久化) | 不写 (config 不可变) | hardcoded const 或 `runtime_config.parameter_validity_window` | N/A | N/A |
| `pending_clarification_slot` | `ao.metadata` | `ao.metadata["clarification_contract"]` (`oasc_contract.py:1365`) | facade.set 路由到 ClarificationContract.set_pending | 读 `ao.metadata["clarification_contract"]` | ao_history 持久化 | NO |
| `clarification_origin` | `ao.metadata` | `ao.metadata["clarification_origin"]` (新加) | 写 ao.metadata | 读 ao.metadata | ao_history 持久化 | NO |
| `revision_invalidated_steps` | `ao.metadata` | `ao.metadata["revision_invalidated_steps"]` (新加) | 写 ao.metadata (REVISION 触发) | 读 ao.metadata | ao_history 持久化 | NO |
| `pcm_active` | `ao.parameter_state` | `ao.parameter_state.collection_mode` (`oasc_contract.py:1407`) | derived — 不直接 set | 直接读 | ao_history 持久化 | NO |
| `last_reconciler_decision` | `context.metadata` (per-turn, 不跨 turn) | `context.metadata["reconciled_decision"]` (`governed_router.py:1016`) | reconciler 写 | 同 turn 读 | NOT persisted (per-turn only) | NO |
| `borderline_decision_marker` | `ao.metadata` | `ao.metadata["borderline_decision_marker"]` (新加) | component #11 写 | 多 contract 读 | ao_history 持久化 | NO |
| `fast_path_blocking_signal` | derived | derived from `pending_chain` non-empty | 不直接 set | derived: `len(facade.get('pending_chain')) > 0` | derived | N/A |

**新增字段总结** (对 underlying store 的实际改动):
- `FactMemory.last_user_message` — new attr
- `ao.metadata["chain_origin_turn"]` — new key
- `ao.metadata["last_chain_advance_reason"]` — new key
- `ao.metadata["clarification_origin"]` — new key
- `ao.metadata["revision_invalidated_steps"]` — new key
- `ao.metadata["borderline_decision_marker"]` — new key
- `ao.metadata["completed_steps_index"]` — new key (索引到 tool_call_log)

总计: FactMemory 1 字段 + ao.metadata 6 keys 新增. 不动 SessionContextStore / AOExecutionState / TaskState.

**新增字段隔离约束**: 这 7 个新字段是 facade 专属, NaiveRouter 不读不写. 实施期改 `core/memory.py` + `core/analytical_objective.py` 时, 新字段必须只在 governed pipeline 触发的代码路径下写入, 不在 NaiveRouter 共享代码路径下写入. 跟 Part 1 §1.4 governed-only 隔离一致.

**实施期 cc 验证 (强制)**:

```bash
grep -rn "last_user_message\|chain_origin_turn\|last_chain_advance_reason\|clarification_origin\|revision_invalidated_steps\|borderline_decision_marker\|completed_steps_index" core/naive_router.py
```

必须 **0 命中**. 任一命中立即 STOP & report, 不得绕过. 跟 §12.1 验证清单第 1 项闭环.

---

## §6. Operation Semantics

### 6.1 Write operations

facade 提供 4 类 write API:

```python
# Single field write
facade.set(field: str, value: Any) -> None

# Multi-field atomic update (按 §6.3 fail-fast)
facade.update(partial: Dict[str, Any]) -> None

# List append (chain advance, completed_steps, revision_invalidated_steps)
facade.append_to(list_field: str, item: Any) -> None

# Clear field (REVISION 时 invalidate chain)
facade.invalidate(field_or_pattern: str) -> None
```

`update(partial)` 不是 transaction — 跑 fail-fast: 第 1 个失败前的写入保留, 失败处停止后续 partial.

### 6.2 Read operations

facade 提供 2 类 read API. **不引入 subscribe / observer pattern** (v1.5 假设串行):

```python
# Single field read
facade.get(field: str) -> Optional[Any]

# Read-only snapshot of all fields
facade.snapshot() -> Dict[str, Any]
```

`subscribe(field, callback)` — **明确不做**. 写在这里是为了避免后续误加. 如果实施期发现需要跨 contract 通知, 走 trace event 不是 reactive callback.

### 6.3 Atomicity — Fail-Fast

按 §2.4 拍板, 实施细节:

```python
def update(self, partial: Dict[str, Any]) -> None:
    for field, value in partial.items():
        try:
            self._route_write(field, value)  # 路由到底层 store
        except Exception as e:
            # 已写入字段保留, 不 rollback
            raise FacadeWriteError(field=field, partial_completed=...)
```

caller 收到 `FacadeWriteError` 处理: 通常停止当前 turn 处理, 让 governed_router fail this turn.

### 6.4 错误处理

| 错误情况 | facade 行为 |
|---|---|
| 底层 store 写失败 (例如 disk full) | 抛 `FacadeWriteError`, 已写部分保留 |
| field 名不在 schema | 抛 `FacadeUnknownFieldError`, 不写底层 store |
| read 时底层 store 没该 key | 返回 `None` (不 raise) |
| read 时 underlying store 实例还没初始化 | 抛 `FacadeNotReadyError` (governed_router 实例化 bug) |

### 6.5 Concurrency

**v1.5 假设单 session 串行**. 不引入 lock / mutex / async coordination.

具体:
- 同 session 同 turn 内 facade write 顺序由 governed pipeline 顺序决定
- 跨 session 不共享 facade 实例
- governed pipeline 假设 `await` 链严格序, 不并发跑多个 contract before_turn

如果 v2 引入并发 (例如多个 contract 并发跑), 必须重新设计 facade concurrency model. v1.5 不解决.

---

## §7. Hand-off Contracts

本章涵盖 **11 个 v1.5 component 中的 10 个** (component #1 facade 自己不在本章, 其余 #2 - #11 跟 facade 的具体读写接口).

每节限制半页内, 只描述接口 + 触发时机 + 字段读写 list, **不描述 contract 内部实现**. 内部实现细节在各 component 文档.

### §7.1 OASCContract — Hand-off

| 项 | 内容 |
|---|---|
| Component # | 现有, 不是新增 |
| 读 facade 字段 | `current_objective`, `objective_status`, `last_user_intent` |
| 写 facade 字段 | `current_objective` (after_turn AO lifecycle sync), `objective_status` |
| 触发时机 | OASCContract.before_turn (读) + after_turn (写) |
| 接口签名 | `before_turn(context, facade)` / `after_turn(context, result, facade)` (新增 facade 参数) |
| Anchors compliance | 跟现有 OASC 行为一致, 只是数据流统一通过 facade |

### §7.2 IntentResolver multi-step planning (component #3) — Hand-off

| 项 | 内容 |
|---|---|
| Component # | 3 (新增, 核心) |
| 读 facade 字段 | `current_objective`, `completed_steps`, `last_referenced_params`, `recent_tool_results_index`, `revision_invalidated_steps` |
| 写 facade 字段 | `pending_chain`, `chain_origin_turn`, `last_chain_advance_reason` |
| 触发时机 | IntentResolver.resolve_fast() 之后, 替代当前的单工具 chain 推断 |
| 接口签名 | `plan_multi_step(context, facade) -> List[ToolPlan]` |
| 关键决策 | LLM prompt 主导 chain 内容; framework 强制 chain 字段写入 facade; chain validation (依赖图 / 参数完整性) 由本 component 在写入前做 |

### §7.3 AO classifier (component #2 双轴语义层) — Hand-off

| 项 | 内容 |
|---|---|
| Component # | 2 (代码不动, 语义层确认) |
| 读 facade 字段 | `current_objective`, `last_user_intent`, `pending_chain` |
| 写 facade 字段 | 触发但不直接写 — REVISION 通过 OASCContract / Reconciler 间接触发 facade.invalidate('completed_steps') |
| 触发时机 | OASCContract before_turn 内调 ao_classifier.classify |
| 接口签名 | classify 接口不变, 但 OASCContract 需要把 facade 传给 classifier 作 read-only 上下文 |
| 关键决策 | 3 状态 (NEW_AO/CONTINUATION/REVISION) + AOStatus 6 lifecycle 双轴, 不强加 REFINEMENT/TERMINATION |

### §7.4 ExecutionContinuation (component #4) — Hand-off

| 项 | 内容 |
|---|---|
| Component # | 4 (重构改读 facade) |
| 读 facade 字段 | `pending_chain`, `chain_owner_ao_id`, `current_objective` |
| 写 facade 字段 | `last_chain_advance_reason` (chain 推进时), `pending_chain` (pop 头部已执行 step) |
| 触发时机 | governed_router 主流程 + ExecutionReadinessContract.before_turn |
| 接口签名 | `advance(facade) -> Optional[ToolPlan]` (取 pending_chain 头部) |
| 关键决策 | v1.0 的 `pending_tool_queue` 字段语义不变, 只是写入入口换成 facade |

### §7.5 ClarificationContract + Reconciler (component #5) — Hand-off

ClarificationContract:

| 项 | 内容 |
|---|---|
| 读 facade 字段 | `last_referenced_params`, `pending_chain`, `pending_clarification_slot`, `pcm_active`, `borderline_decision_marker` |
| 写 facade 字段 | `pending_clarification_slot`, `clarification_origin`, `pcm_active` |
| 触发时机 | ClarificationContract.before_turn 主流程 |
| 关键决策 | "好的"/"对"/"继续" 类用户反馈通过 facade.get('pending_chain') 判断是否触发 chain 推进 |

Reconciler:

| 项 | 内容 |
|---|---|
| 读 facade 字段 | `pending_chain`, `pending_clarification_slot`, `objective_status` |
| 写 facade 字段 | `last_reconciler_decision` (per-turn, 不跨 turn 持久) |
| 触发时机 | governed_router._consume_decision_field |
| 接口签名 | `reconcile(p1, p2, p3, b_result, facade) -> ReconciledDecision` |

### §7.6 Conversation_fast_path (component #6) — Hand-off

| 项 | 内容 |
|---|---|
| Component # | 6 (新增 blocking signal) |
| 读 facade 字段 | `fast_path_blocking_signal` (derived from `pending_chain`) |
| 写 facade 字段 | 无 |
| 触发时机 | ConversationIntentClassifier.classify 内, 检查 fast_path_allowed 时 |
| 接口签名 | 现有 `classify` 接口加一步: `if facade.get('fast_path_blocking_signal'): fast_path_allowed = False` |
| 关键决策 | pending_chain 非空时禁用 fast path, 强制走 governed pipeline |

### §7.7 Standardizer fallback (component #7) — Hand-off

| 项 | 内容 |
|---|---|
| Component # | 7 (新增 clarification 触发) |
| 读 facade 字段 | `last_referenced_params` (fallback tier 命中 default 时复用) |
| 写 facade 字段 | `pending_clarification_slot`, `clarification_origin = 'standardizer_fallback'` |
| 触发时机 | StandardizationEngine fallback tier 命中时 |
| 关键决策 | fallback tier 命中 default → 触发 clarification 通过 facade, 不再 silent default |

### §7.8 PCM 文件上下文 bug fix (component #8) — Hand-off

| 项 | 内容 |
|---|---|
| Component # | 8 (bug fix) |
| 读 facade 字段 | `recent_tool_results_index` (检查 file_analysis 是否已 grounded) |
| 写 facade 字段 | 无 |
| 触发时机 | ClarificationContract `_detect_confirm_first` 之前, 检查文件 grounding 状态 |
| 关键决策 | PCM 不该激活 if file_relationship_resolution 已经 grounded; facade 提供统一 grounding state 查询入口 |

### §7.9 DependencyContract 实施化 (component #9) — Hand-off

| 项 | 内容 |
|---|---|
| Component # | 9 (新增, v1.0 是空壳) |
| 读 facade 字段 | `pending_chain`, `recent_tool_results_index`, `current_objective` |
| 写 facade 字段 | 触发 trace block_telemetry 写入 (不直接动 facade 字段) |
| 触发时机 | DependencyContract.before_turn (新实现) + shortcut path 调用入口 |
| 接口签名 | `before_turn(context, facade) -> ContractDecision` |
| 关键决策 | shortcut path 是否启用 dependency check 留 component #10 决定 (软 / 硬 / record-only) |

### §7.10 Shortcut path dependency check (component #10) — Hand-off

**本节范围**: facade 只提供 `block_telemetry` 数据查询, 不决定 block 行为. block 决策 (硬 block / 软 record / 跳过) 在 component #10 (DependencyContract) 文档拍板, 不在 facade schema. 如果 component #10 拍板影响 facade schema 字段, 本文档相应章节回头更新.

| 项 | 内容 |
|---|---|
| Component # | 10 (设计选择项) |
| 读 facade 字段 | `pending_chain`, `recent_tool_results_index` |
| 写 facade 字段 | 无 (只 record block_telemetry) |
| 触发时机 | `_execute_from_snapshot` 入口 |
| 关键决策 | 3 选项 (硬 block / 软 record-only / 跳过) 留各 component 文档拍板. facade 只提供数据查询接口, 不决定 block 行为 |

### §7.11 Reconciler "clarify but empty question" fall-through (component #11) — Hand-off

| 项 | 内容 |
|---|---|
| Component # | 11 (新增 facade 写入点) |
| 读 facade 字段 | `pending_clarification_slot`, `pending_chain` |
| 写 facade 字段 | `borderline_decision_marker` |
| 触发时机 | `_consume_decision_field` 内, reconciler 返回 `decision_value="clarify"` 但 question empty 时 |
| 接口签名 | `mark_borderline(facade, source_trace) -> None` |
| 关键决策 | 标记 borderline 决策, 让下一 turn ClarificationContract / IntentResolver 知道当前在 borderline 路径, 调整决策策略 |

---

## §8. Lifecycle & Persistence

### 8.1 facade 实例化时机

**Per session (跟 GovernedRouter 绑定)**, 不是 per turn.

```python
class GovernedRouter:
    def __init__(self, session_id, ...):
        self.facade = ConversationStateFacade(
            session_id=session_id,
            fact_memory=self.memory.fact_memory,
            context_store=self.inner_router.context_store,
            ao_manager=self.ao_manager,
        )
```

facade 的所有 read/write 通过持有的 store 引用走, 不复制数据.

### 8.2 跨 turn 状态 carry-over 机制

facade **不持久化自己**. 跨 turn 状态由底层 store 持久化提供:
- `FactMemory` → `data/sessions/history/{session_id}.json`
- `SessionContextStore` → `router_state/{session_id}.json`
- `ao.metadata` → 通过 `FactMemory.ao_history` 持久化

facade 实例化时只取底层 store 引用, 不读 / 写底层 store. 第一次 `facade.get('field')` 才触发 read-through.

### 8.3 进程重启后的 facade 重建

进程重启 → GovernedRouter 重新实例化 → MemoryManager 加载 `data/sessions/history/{session_id}.json` → fact_memory 恢复 → facade 重新构造 → 所有跨 turn 状态完全可读.

facade 自身**没有任何独立持久化**, 不存 facade dump.

### 8.4 session 结束时 facade 销毁

facade 跟 GovernedRouter 同 session 生命周期. session 结束 → GovernedRouter 销毁 → facade 销毁. 底层 store 持久化完整保留 (按 v1.0 行为, 不动).

---

## §9. Trace Observability

### 9.1 facade write 触发 trace event

每次 facade.set / update / append_to / invalidate **触发一个 trace event**, 新 step type:

```
TraceStepType.CONVERSATION_STATE_UPDATE = "conversation_state_update"
```

放在 `core/trace.py` enum, 跟其他 step type 同级.

### 9.2 trace event 字段

```json
{
  "type": "conversation_state_update",
  "operation": "set" | "update" | "append_to" | "invalidate",
  "fields": ["pending_chain", "last_chain_advance_reason"],
  "triggered_by": "intent_resolver_multi_step_plan",
  "wall_time_ms": 1.2,
  "previous_summary": "{pending_chain: empty}",
  "new_summary": "{pending_chain: [tool1, tool2]}"
}
```

不 dump 完整 value (避免 trace 膨胀), dump summary (字段名 + 长度 / hash / 关键标识).

### 9.3 跟现有 governance metadata 的关系

| 现有 trace key | 含义 | 跟 facade trace 的关系 |
|---|---|---|
| `oasc` | OASC 内部分类 telemetry | 不重复, facade trace 只记自己写入 |
| `classifier_telemetry` | AO classifier 详细输出 | 不重复 |
| `block_telemetry` | dependency / constraint check 结果 | 不重复, component #9/#10 通过 facade 触发 block_telemetry, 但 trace event 分两类 |
| `ao_lifecycle_events` | AO lifecycle (create/activate/complete) | 不重复, facade 写 `current_objective` 跟 ao_lifecycle_events 互补 |
| `reconciled_decision` | reconciler 输出 | 不重复, facade 写 `last_reconciler_decision` 是 ref 不是完整 decision |

facade trace 是**业务语义层**的 observability, 现有 governance metadata 是**实现层** observability. 两者并存, 不冲突.

### 9.4 跟 component #12 llm_telemetry 的关系

llm_telemetry 记 LLM call (cache / tokens / wall_time). facade trace 记 ConversationState writes. 两者完全独立, 不重叠.

---

## §10. Non-Goals

明确不做:

- 跨 session memory (long-term user history)
- 多 user 共享 state
- ConversationState 自身持久化 (facade 是 view, 不是 store)
- LLM 直接读写 facade (LLM 通过 contract pipeline 间接交互)
- Reactive subscription / observer pattern (§6.2 已说)
- 物理 store 重构 (SessionContextStore / FactMemory / ao.metadata 内部实现不动)
- 跨 process 一致性 (单 session 串行假设, §6.5)
- facade 自动 schema migration (v1.5 → v2 schema 改动手动处理)

---

## §11. Open Questions

5 个 open question 留实施期 (Phase 9.1.1+) 决定. 不阻塞 schema frozen.

### Open Q1: facade 实例 vs 静态全局 module

facade 是 `ConversationStateFacade` class instance (per session) 还是 `core/conversation_state_facade.py` module-level functions (with implicit session context)?

**倾向: per-session class instance** (实施期 default 这个, 除非有 strong counter-evidence).

理由:
- 单元测试隔离: per-session 实例化让 test fixture 干净, 跨 test 不污染全局状态
- NaiveRouter 隔离稳健: 静态全局让 NaiveRouter 容易意外触及 facade state, per-session 强制依赖注入
- Modern engineering default: instance-based 是 Python 项目主流, 跟 GovernedRouter / MemoryManager 等现有 class 一致
- 复杂度代价低: instance 化只多一次 `self.facade = ConversationStateFacade(...)` 实例化代码

实施期最终拍板. 偏离 per-session 须 STOP & report.

### Open Q2: 类型系统 (TypedDict vs dataclass vs Pydantic)

facade 内部字段类型用什么:
- TypedDict — 轻量, 但运行时无验证
- @dataclass — Python 标准, 适度验证
- Pydantic BaseModel — 强验证 + serialize, 但加依赖

倾向: **@dataclass**, 项目已用. 实施期最终拍板.

### Open Q3: read-through fallback 行为

`facade.get('field')` 时若底层 store 缺该 key, 行为:
- 返回 None (默认设计)
- 抛 `FacadeMissingFieldError`
- 返回 schema-defined default (例如 `pending_chain` default 是 `[]`)

倾向: **schema-defined default for collections, None for scalars**. §6.4 当前写 "返回 None", 实施期收敛细节.

### Open Q4: facade 字段命名跟 underlying store key 的命名映射策略

§5 routing table 暴露: 一些 facade 字段是 1:1 映射 (例如 `current_objective` → `fact_memory.current_ao_id`), 一些是聚合 (例如 `last_referenced_params` 聚合 `session_confirmed_parameters` + `recent_vehicle/pollutants/year`).

聚合字段的 write semantics 复杂 — `facade.set('last_referenced_params', {...})` 时, 是 overwrite 整个聚合还是 merge?

实施期决定. 倾向: overwrite 简单, merge 风险大.

### Open Q5: facade write 失败的回滚粒度

跟 §2.4 fail-fast 拍板呼应. fail-fast 决定 "失败立即停止", 但**真实施时**失败前已经写到 underlying store 的部分要不要 manual undo, 取决于 underlying store API.

实施期决定. 倾向: **不 undo** (fail-fast 已写入保留, 让 caller 处理). 但若某 underlying store 写入产生 disk 副作用 (例如 `_save()` 已经 flush), 可能需要 manual cleanup.

---

## §12. Validation Hooks for Codex

schema frozen 后, 第一个 cc 任务按本章验证 schema 跟现有代码对齐.

### 12.1 cc 验证任务清单

按顺序跑, 任一失败立即 STOP & report:

1. **NaiveRouter 隔离验证**
   - `grep -rn "conversation_state_facade" core/naive_router.py` → 必须 0 命中
   - `grep -rn "ConversationStateFacade" core/naive_router.py` → 必须 0 命中

2. **Schema 字段跟现有代码 namespace 冲突检查**
   按 §5 routing table 列的 "underlying key/path", grep 现有代码:
   - `ao.metadata["chain_origin_turn"]` — 应该 0 命中 (新加)
   - `ao.metadata["last_chain_advance_reason"]` — 应该 0 命中
   - `ao.metadata["clarification_origin"]` — 应该 0 命中
   - `ao.metadata["revision_invalidated_steps"]` — 应该 0 命中
   - `ao.metadata["borderline_decision_marker"]` — 应该 0 命中
   - `ao.metadata["completed_steps_index"]` — 应该 0 命中
   - `fact_memory.last_user_message` — 应该 0 命中
   
   任一 > 0 命中 → STOP, 报告 namespace 冲突.

3. **底层 store 真实结构跟 §5 routing 假设对齐**
   按 §5 列每条:
   - `core/memory.py:88` 是 `session_confirmed_parameters` 还是已经改名? 命名一致 → pass
   - `core/memory.py:93` 是 `current_ao_id` 还是已经改名? 命名一致 → pass
   - `core/context_store.py:66` 是 `_store: Dict[str, StoredResult]` 还是已经改名? 一致 → pass
   - `core/analytical_objective.py:262-271` 是 `AOExecutionState` 跟 `planned_chain` / `chain_cursor` 字段 → 一致 → pass
   - `core/analytical_objective.py:523` 是 `metadata: Dict[str, Any]` → 一致 → pass

   任一 mismatch → STOP, 报告底层 store 已 drift, schema 需要修订.

4. **Hand-off contract 接口签名假设验证**
   §7 列每个 component 的接口签名, 跟现有 contract 类签名对照:
   - OASCContract.before_turn / after_turn (`oasc_contract.py:44-72` / `:704-760`) → 当前签名不接受 `facade` 参数, 实施期需要加. flag 这件事不是 STOP, 是已知改动.
   - 其他 contract 类似.

   接口签名跟 §7 假设**不可调和**冲突 (例如 contract 类被删 / 文件不存在) → STOP.

5. **Trace step type 添加位置**
   `core/trace.py:17-128` enum 当前 108 个成员. 检查:
   - `CONVERSATION_STATE_UPDATE` 不存在 → 验证通过 (新加)
   - 名字冲突 (例如已有同名) → STOP

### 12.2 STOP & report 触发条件

cc 验证期间:

1. NaiveRouter 隔离 grep 命中 → STOP
2. Schema 新加字段 namespace 已被占用 → STOP
3. 底层 store 字段命名已 drift (跟 §5 假设不一致) → STOP
4. Hand-off contract 类被删 / 文件不存在 → STOP
5. Trace step type 名字冲突 → STOP

任一 STOP → 不继续验证, 直接报告 user, 等用户拍板 schema 修订.

5 项验证全 pass → schema 准备进 Phase 9.1.1 实施.

---

## Appendix A: Worked Examples

### A.1 mode_A 修复后 — Run 7 完整三 turn (DETAILED)

本例是论文 §5 Shanghai e2e 案例研究的核心 trace. turn-by-turn facade state + contract pipeline + facade read/write.

**初始状态** (新 session):

```
facade state: {} (全部 None / 空)
underlying stores: 全部空
```

---

**Turn 1** (用户输入: "用 macro_direct.csv 算上海 3 路段排放, 计算 CO2 和 NOx, 夏季"):

```
facade state before:
  current_objective: None
  pending_chain: []
  completed_steps: []
  last_referenced_params: {}
  last_user_intent: None

contract pipeline:
  1. ContractContext 建立, file_path = macro_direct.csv
  
  2. OASCContract.before_turn(context, facade):
     - facade.set('last_user_intent', "用 macro_direct.csv ...")
     - AO classifier → NEW_AO (没有 current_objective)
     - AOManager.create_ao(...) → AO#1 created, status=ACTIVE
     - facade.set('current_objective', 'AO#1')
     - facade.set('objective_owner_ao_id', 'AO#1')
     - facade.set('objective_status', 'active')
  
  3. ClarificationContract.before_turn(context, facade):
     - facade.get('last_referenced_params') → {} (无前序 turn)
     - 文件已通过 file_relationship_resolution grounded
     - PCM 不激活 (because component #8 fix: file 已 grounded)
     - facade.set('pcm_active', False)
     - Stage 2 LLM 解析 → 标准化参数 {pollutants: [CO2, NOx], season: summer, road_segments: [...]}
  
  4. IntentResolver.plan_multi_step(context, facade):
     - facade.get('completed_steps') → []
     - facade.get('last_referenced_params') → {}
     - LLM prompt: "user wants emission calculation + dispersion is reasonable next step"
     - LLM output: chain = [calculate_macro_emission, calculate_dispersion]
     - dependency check: calculate_dispersion requires emission (not yet available → enqueue, not block)
     - facade.set('pending_chain', [calculate_macro_emission, calculate_dispersion])
     - facade.set('chain_origin_turn', 1)
     - facade.set('last_chain_advance_reason', 'multi_step_initial_plan')
  
  5. ExecutionReadinessContract.before_turn:
     - facade.get('pending_chain') → [...]
     - 取头部 calculate_macro_emission, 检查 readiness → ready
  
  6. Reconciler:
     - 决议 proceed
     - facade.set('last_reconciler_decision', {value: 'proceed', source_trace: ...})
  
  7. Tool execution: calculate_macro_emission(pollutants=[CO2,NOx], season=summer, ...)
     - Result: {CO2: 318.90 kg/h, NOx: 67.40 g/h, output_file: outputs/macro_xxx.xlsx}
  
  8. ExecutionContinuation.advance(facade):
     - facade.append_to('completed_steps', {step_id: 1, tool: macro_emission, result_ref: ..., wall_time_ms: 5230})
     - facade.set('pending_chain', [calculate_dispersion])  (pop 头部)
     - facade.set('last_chain_advance_reason', 'tool_completed_advance')
  
  9. OASCContract.after_turn(context, result, facade):
     - AO#1 still active (chain 未完, pending_chain 非空)
     - facade.set('objective_status', 'active')
  
  10. facade.set('last_referenced_params', {pollutants: [CO2, NOx], season: summer, road_segments: [...]})

facade state after Turn 1:
  current_objective: AO#1
  objective_owner_ao_id: AO#1
  objective_status: active
  last_user_intent: "用 macro_direct.csv 算上海..."
  pending_chain: [calculate_dispersion]
  completed_steps: [{step_id: 1, tool: macro_emission, ...}]
  chain_owner_ao_id: AO#1
  chain_origin_turn: 1
  last_chain_advance_reason: tool_completed_advance
  last_referenced_params: {pollutants: [CO2, NOx], season: summer, road_segments: [...]}
  recent_tool_results_index: {emission: ref_to_macro_xxx.xlsx}
  pcm_active: False
  fast_path_blocking_signal: True (pending_chain 非空)
```

Response to user: "已计算: CO2 318.90 kg/h, NOx 67.40 g/h. 接下来准备进行扩散模拟."

---

**Turn 2** (用户输入: "对刚才的排放结果做扩散模拟"):

```
facade state before: <Turn 1 after 状态>

contract pipeline:
  1. ConversationIntentClassifier:
     - facade.get('fast_path_blocking_signal') → True (pending_chain 非空)
     - fast_path_allowed = False
     - 走 governed pipeline (component #6 阻止 fast path)
  
  2. OASCContract.before_turn(context, facade):
     - facade.set('last_user_intent', "对刚才的排放结果做扩散模拟")
     - AO classifier (读 facade):
       - facade.get('current_objective') → AO#1 (still active)
       - facade.get('pending_chain') → [calculate_dispersion]
       - 用户消息跟 pending_chain 头部语义一致 (dispersion)
       - 分类 → CONTINUATION (不是 NEW_AO, 这是 mode_A 修复关键)
     - 不创建新 AO, current_objective 保持 AO#1
  
  3. ClarificationContract.before_turn(context, facade):
     - facade.get('last_referenced_params') → {pollutants: [CO2, NOx], ...}
     - 用户没说 dispersion 用哪个 pollutant → 检查 last_referenced_params
     - 默认用 NOx (pollutants 列表第一个 dispersion-relevant)
     - PCM 不激活 (足够参数)
  
  4. IntentResolver.plan_multi_step(context, facade):
     - facade.get('pending_chain') → [calculate_dispersion]
     - 已有 chain, 不需要 re-plan
     - 验证 chain 头部 dispersion 仍可执行 → ready
     - chain 不变
  
  5. ExecutionReadinessContract.before_turn:
     - facade.get('recent_tool_results_index') → {emission: ref_to_macro_xxx}
     - dispersion requires emission → satisfied
     - readiness 通过
  
  6. Tool execution: calculate_dispersion(pollutant=NOx, source=emission_ref, ...)
     - Result: {dispersion_grid: ..., output_file: outputs/dispersion_xxx.geojson}
  
  7. ExecutionContinuation.advance(facade):
     - facade.append_to('completed_steps', {step_id: 2, tool: dispersion, ...})
     - facade.set('pending_chain', [])  (chain 完成)
     - facade.set('last_chain_advance_reason', 'tool_completed_advance')
     - facade.set('fast_path_blocking_signal', False) — derived
  
  8. OASCContract.after_turn(context, result, facade):
     - facade.get('pending_chain') → []
     - 检查 objective satisfied: completed_steps 已含 emission + dispersion
     - AO#1 → COMPLETED
     - facade.set('objective_status', 'completed')
     - facade.set('current_objective', None)

facade state after Turn 2:
  current_objective: None  (AO#1 completed)
  objective_status: completed
  pending_chain: []
  completed_steps: [step_1: macro_emission, step_2: dispersion]
  last_referenced_params: {pollutants: [CO2, NOx], season: summer, road_segments: [...]}
  recent_tool_results_index: {emission: ref_macro, dispersion: ref_dispersion}
  fast_path_blocking_signal: False
```

Response to user: "扩散模拟完成. NOx 在 ... 区域..."

**关键修复点**: AO classifier Turn 2 把 "对刚才的排放结果做扩散模拟" 分为 CONTINUATION 而非 NEW_AO, 因为 facade 让 classifier 看到 `current_objective=AO#1` + `pending_chain=[dispersion]`, classifier 推断这是延续不是新任务. v1.0 没这个 facade, 5/5 trial 全分为 NEW_AO.

---

**Turn 3** (假设用户输入: "再分析一下污染热点"):

```
facade state before: <Turn 2 after 状态>

facade.get('current_objective') → None (AO#1 completed)
→ AO classifier → NEW_AO (创建 AO#2)
→ IntentResolver.plan_multi_step 利用 facade.get('completed_steps') 的 emission/dispersion 结果
→ 规划 [analyze_hotspots] 单步 chain
→ 自动执行
```

Turn 3 关键: 即使 AO#1 completed, facade.completed_steps 跟 recent_tool_results_index 跨 AO 持久, IntentResolver 复用上 AO 工具结果.

---

### A.2 Conversation repair (REVISION) — 简短

```
Turn 1: 用户算 CO2 排放 → AO#1 → completed_steps=[macro_emission(CO2)]
Turn 2: 用户说 "啊我说错了, 应该算 NOx 不是 CO2"
  - AO classifier → REVISION (current_objective=AO#1 still recent, intent matches REVISION pattern)
  - AOManager.revise_ao(AO#1) → 创建 AO#2 (REVISION 关系)
  - facade.set('current_objective', 'AO#2')
  - facade.set('objective_owner_ao_id', 'AO#1') — 保留 root AO 追溯
  - facade.invalidate('completed_steps') — 旧 step 不再算
  - facade.set('revision_invalidated_steps', [step_1])
  - IntentResolver re-plan: pending_chain = [calculate_macro_emission(NOx)]
  - 执行
```

### A.3 隐式上下文 — 简短

```
Turn 1: 用户算 macro_emission(乘用车, 夏季) → completed
  - facade.last_referenced_params = {vehicle: 乘用车, season: summer, ...}

Turn 2: 用户说 "再算一次, 改成冬季"
  - AO classifier → CONTINUATION 或 NEW_AO (取决于具体语义)
  - IntentResolver.plan: facade.get('last_referenced_params') 取 {vehicle: 乘用车, ...}
  - 用户只改 season, 其他参数复用
  - chain = [calculate_macro_emission(乘用车, winter)]
  - 不需要再问 vehicle, road, pollutants
```

---

## Appendix B: Glossary

| 术语 | 含义 |
|---|---|
| AO | Analytical Objective. 单个用户分析目标的封装单元. v1.0 已有概念. |
| AO classifier | 把用户消息分类为 NEW_AO / CONTINUATION / REVISION 的组件. `core/ao_classifier.py`. |
| AOStatus | AO lifecycle 状态 (CREATED / ACTIVE / REVISING / COMPLETED / FAILED / ABANDONED). `core/analytical_objective.py:10-16`. v1.0 已有 6 状态. |
| AOExecutionState | AO 内 chain 进度 ledger (`planned_chain` / `chain_cursor` / etc.). `core/analytical_objective.py:262-271`. |
| facade | 本文档的 ConversationStateFacade — 业务语义层包装现有 store 的协调层. |
| underlying store | facade 路由到的实际数据存储 (FactMemory / SessionContextStore / ao.metadata / AOExecutionState). |
| read-through | facade.get 直接读底层 store, 不缓存. |
| write-through | facade.set 立即写底层 store, 不延迟. |
| mode_A | Step 1 variance characterization 命名的 Run 7 失败模式 (Turn 1 macro 成功, Turn 2/3 stuck). |
| shortcut path | governed_router 的 `_consume_decision_field` + `_maybe_execute_from_snapshot` 路径, 跳过 inner_router 完整 state loop. |
| fail-fast | facade write 任一失败立即抛异常, 不 rollback (§2.4). |
| governed-only | facade 严格只在 governed_router pipeline 内使用, NaiveRouter 不导入 (§2.3 + §3.5). |
| component #N | v1.5 阶段 2 设计的 11 个核心组件之一. 完整列表见 Part 1 §1.10 + 各 component 文档. |

---

## Appendix C: Related Audit References

本 schema 设计的所有决策追溯到 6 轮 audit 报告.

| Audit | 报告 | 本文档对应章节 |
|---|---|---|
| Phase 9.1.0 codebase audit | `docs/architecture/phase9_1_0_codebase_audit.md` | §1.1 (mode_A root cause), §3 (现有 store 结构), §5 (routing 基础) |
| Run 7 trace recheck | `docs/architecture/phase9_1_0_run7_trace_recheck.md` | §1.1 (Run 7 break point) |
| Run 7 variance | `docs/architecture/phase9_1_0_run7_variance.md` | §1.1 (mode_A 5/5 evidence), Appendix A.1 |
| Session/cache verification | `docs/architecture/phase9_1_0_isolation_cache_verify.md` | §2.3 (NaiveRouter 隔离已 verified) |
| Step 2 reproducibility | `docs/architecture/phase9_1_0_step2_reproducibility.md` | §1.2 (facade vs new store trade-off), §11 Open Q4 |
| Step 2.5 NaiveRouter drift | `docs/architecture/phase9_1_0_step2_5_naive_drift_trace_race.md` | §3.5 (NaiveRouter LLM-driven behavior, baseline 不 contaminated) |
| 阶段 1 trace fix | `docs/architecture/phase9_1_0_step3_trace_fix_verification.md` | §9 (trace observability foundation) |
| 阶段 1a observability | `docs/architecture/phase9_1_0_step3_followup_observability_variance.md` | §11 Open Q3 (read-through fallback) |
| 阶段 1b pre-audit | `docs/architecture/phase9_1_0_step3c_1b_pre_audit.md` | §7.10 (shortcut path component #10), §7.9 (DependencyContract 实施化) |
| 阶段 1b Option A | `docs/architecture/phase9_1_0_step3d_optionA_verification.md` | §9 (trace 完整性已 verified, facade trace 加在此基础上) |

---

**End of v1.5 ConversationState Facade Schema document — frozen v2**

**Frozen 状态**: 2026-05-05 kirito approved. 后续 component 文档引用本文档不可推翻. 仅 §11 open question 实施期解决时回头更新对应章节.

下一步: 进 Part 2 component #2 (IntentResolver multi-step planning) 文档.
