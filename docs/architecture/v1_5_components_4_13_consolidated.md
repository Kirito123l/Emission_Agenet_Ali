# v1.5 Components 4-13 Consolidated — 集中设计文档

**Document path**: `docs/architecture/v1_5_components_4_13_consolidated.md`
**Version**: **frozen v2** (拍板完成 2026-05-06, kirito approved)
**Last updated**: 2026-05-06
**Branch**: `phase9.1-v1.5-upgrade`

---

## §0. Document Status & Scope

### Status

| Field | Value |
|---|---|
| Status | **frozen v2** (kirito approved 2026-05-06) |
| Frozen tag (target) | `v1.5-design-frozen` (跟 Component #1, #2, #3 一起打, 设计阶段终点) |
| References | Part 1 frozen + Component #1 facade frozen v2 + Component #2 IntentResolver frozen v2 + Component #3 AO classifier frozen v2 |
| Frozen 后修改流程 | 仅 §12 global open questions 实施期解决时回头更新对应组件章节. 其他章节 frozen 不可改动, 改动须回到设计阶段 review. |

### 文档定位

本文档涵盖 v1.5 components #4 - #13 (10 个), 性质上每个组件都是 **小改动 / bug fix / 接口扩展 / 重构**, 不需要像 component #1 #2 那样独立长文档. 集中文档让 cc 实施期 cross-reference 容易.

每个组件章节包含 5 个 section:
- **现状** (1 段, v1.0 真实情况)
- **v1.5 改动** (具体 file:line + 接口签名)
- **跟 facade / IntentResolver / AO classifier 协同** (引用对应 frozen 文档章节)
- **Open questions** (如有, 实施期决定的细节)
- **cc validation hooks** (具体 grep / verification)

不重复 Anchors compliance / Lifecycle / Trace observability 整套结构 — 那些在 #1 #2 #3 已覆盖. 本文档每个组件 §3.5 (NaiveRouter 隔离) 跟 §3.1-3.4 (Anchors 4 项) 用一句话或表格回应, 不展开.

### 阅读顺序建议

cc 实施期按 §1 → §10 顺序读, 每个组件独立工作单位, 不需要前后依赖.

实施期工作量估计 (粗略, 不是承诺):
- §1 (#4) ExecutionContinuation: 1-2 天
- §2 (#5) Clarification + Reconciler: 1-2 天
- §3 (#6) Fast path blocking: 0.5 天
- §4 (#7) Standardizer fallback: 1 天
- §5 (#8) PCM file context bug: 0.5 天
- §6 (#9) DependencyContract 实施化: 1-2 天
- §7 (#10) Shortcut path dependency check: 0.5-1 天
- §8 (#11) Reconciler fall-through: 0.5 天
- §9 (#12) llm_telemetry trace key: 0.5 天
- §10 (#13) Filesystem hygiene: 1 天

总实施估计: 8-12 天 (实际取决于 cc 速度跟 unforeseen issues).

---

## §1. Component #4 — ExecutionContinuation 改读 facade

### 1.1 现状

v1.0 `ExecutionContinuation` (`core/contracts/execution_readiness_contract.py:275-283` 区域) 通过 `ao.metadata["execution_continuation"]["pending_tool_queue"]` 跨 turn 持有 chain 推进状态. 这个机制已经工作, 但跟 `AOExecutionState.planned_chain` 并存, 没有统一读写入口.

### 1.2 v1.5 改动

ExecutionContinuation 改读 facade 字段:

| 改动 | file:line 候选 |
|---|---|
| 取下一步执行: 改读 `facade.get("pending_chain")` | `core/contracts/execution_readiness_contract.py` ExecutionContinuation 主路径 |
| chain 推进: 改写 `facade.set("pending_chain", remainder)` + `facade.append_to("completed_steps", step_result)` | 同上 |
| chain 推进原因: `facade.set("last_chain_advance_reason", "tool_completed_advance")` | 同上 |
| chain 中间步失败: 调 `IntentResolver.repair_chain` (Component #2 §7.3) | 失败处理路径 |

不动:
- ExecutionContinuation 主算法 (advance / readiness check)
- ao.metadata 底层结构 (facade 通过 routing 写两处, 见 facade §5)

### 1.3 跟 facade / IntentResolver 协同

引用:
- facade frozen v2 §4.2 (chain state 字段)
- facade frozen v2 §5 routing table (pending_chain 路由到 ao.metadata + AOExecutionState mirror)
- facade frozen v2 §7.4 (ExecutionContinuation hand-off)
- IntentResolver frozen v2 §7.3 (repair_chain 接口)
- IntentResolver frozen v2 §8.3 (跟 ExecutionContinuation hand-off)

### 1.4 Open Questions

**Q1**: chain repair 触发时机 — execution 失败立刻 repair 还是 reconciler 决策后再 repair?
- 倾向: **reconciler 决策后再 repair** (跟 IntentResolver §8.5 reconciler gating 一致)
- 实施期最终拍板

### 1.5 cc Validation Hooks

```bash
# 1. NaiveRouter 隔离
grep -rn "facade\.get\|facade\.set\|facade\.append_to" core/naive_router.py
# 必须 0 命中

# 2. ExecutionContinuation 不直接读 ao.metadata pending_tool_queue (改读 facade)
grep -rn 'ao\.metadata\["execution_continuation"\]\["pending_tool_queue"\]' core/contracts/execution_readiness_contract.py
# 应该只在 facade routing 内, ExecutionContinuation 主流程不直接访问
```

任一异常 → STOP & report.

### 1.6 Anchors compliance (1 段)

ExecutionContinuation 改读 facade 是接口扩展不是算法变化, 跟 IntentResolver §3.2 同等性质 — 架构层面改动, 不是 LLM 算法. 跟 3 类失败模式: 主修跳步执行 (chain 自动推进). NaiveRouter 不调 ExecutionContinuation, 隔离守住.

---

## §2. Component #5 — Clarification + Reconciler 改读 facade

### 2.1 现状

`ClarificationContract` 跟 `Reconciler` (在 `core/governed_router.py` 内) v1.0 各自读各自的 `ao.metadata` namespace, 没有跨 contract shared state.

### 2.2 v1.5 改动

ClarificationContract 改读 facade:

| 字段 | 用途 |
|---|---|
| `facade.get("last_referenced_params")` | 判断是否真缺参数, 避免重复问已知参数 |
| `facade.get("pending_chain")` | 处理 "好的"/"对"/"继续" 用户回答 — 触发 chain 推进而不是再问参数 |
| `facade.get("pending_clarification_slot")` | 当前等用户回答的参数 slot |
| `facade.get("pcm_active")` | PCM 状态查询 |
| `facade.get("borderline_decision_marker")` | 检测上一 turn 是否走 reconciler fall-through (component #11 设置) |
| `facade.set("pending_clarification_slot", ...)` | 写入新 clarification 需求 |
| `facade.set("clarification_origin", ...)` | 标识 clarification 触发源 |

Reconciler 改读 facade:

| 字段 | 用途 |
|---|---|
| `facade.get("pending_chain")` | reconciler 决策时需要知道当前 chain 状态 |
| `facade.get("pending_clarification_slot")` | reconciler 决策时需要知道是否在 clarification 路径 |
| `facade.get("objective_status")` | reconciler 决策考虑 AO lifecycle |
| `facade.set("last_reconciler_decision", ...)` | per-turn (不跨 turn 持久) |

不动:
- ClarificationContract 主算法 (probe / fallback / direct execute)
- Reconciler 决策逻辑 (P1 / P2 / P3 / B 4 路汇总)

### 2.3 跟 facade 协同

引用:
- facade frozen v2 §4.4 (Clarification state 字段)
- facade frozen v2 §4.5 (Reconciler / fallback state 字段)
- facade frozen v2 §7.5 (Clarification + Reconciler hand-off)

### 2.4 Open Questions

**Q1**: "好的"/"对"/"继续" 类用户回答的识别 — rule-based 还是 LLM?
- 倾向: **rule-based 优先**, LLM fallback (跟现有 ClarificationContract `_detect_confirm_first` 类似)
- 实施期 audit `_detect_confirm_first` 现有逻辑后拍板

**Q2**: Reconciler 跟 borderline_decision_marker (component #11) 协同时机
- reconciler 在调用 component #11 mark_borderline 之前还是之后读 marker?
- 倾向: **当前 turn reconciler 不读, 下一 turn ClarificationContract 读** (避免同 turn 自己读自己刚写的 marker)
- 实施期最终拍板

### 2.5 cc Validation Hooks

```bash
# 1. NaiveRouter 隔离
grep -rn "ConversationStateFacade\|conversation_state_facade" core/naive_router.py
# 必须 0 命中

# 2. ClarificationContract 改读 facade 后, 不直接读 ao.metadata clarification namespace 多处
grep -rn 'ao\.metadata\["clarification' core/contracts/clarification_contract.py | wc -l
# 实施前 baseline 计数 → 实施后应该减少 (统一通过 facade 访问)
```

### 2.6 Anchors compliance

Clarification + Reconciler 改读 facade 是协调层升级, 不动决策算法. 修复多轮状态漂移 (主) + 对话修正 (能力 3 协同). NaiveRouter 隔离守住.

---

## §3. Component #6 — Conversation Fast Path Blocking Signal

### 3.1 现状

`ConversationIntentClassifier` 在 `core/governed_router.py:623-734` 区域分类用户消息为 `CHITCHAT` / `EXPLAIN_RESULT` / `KNOWLEDGE_QA` / `TOOL_REQUEST` 等. 命中 fast-path 类别且 `fast_path_allowed=True` 时, 整个 governed pipeline 被跳过.

阶段 1a Step 2 数据显示 fast path 命中频率会让 multi-step chain 推进失败 (因为 chain 中途进 fast path → governance 不工作).

### 3.2 v1.5 改动

加 1 个 blocking signal:

| 改动 | file:line 候选 |
|---|---|
| `ConversationIntentClassifier.classify` 内, 在确定 `fast_path_allowed=True` 之前, 检查 `facade.get("fast_path_blocking_signal")` | `core/governed_router.py:623-734` 区域 |
| 如果 `fast_path_blocking_signal == True` (即 `pending_chain` 非空), 强制 `fast_path_allowed = False`, 走 governed pipeline | 同上 |

`fast_path_blocking_signal` 是 facade derived field — `facade.get("fast_path_blocking_signal")` 返回 `len(facade.get("pending_chain")) > 0` 的结果.

总改动量: ~5-10 LOC.

### 3.3 跟 facade 协同

引用:
- facade frozen v2 §4.5 (Reconciler / fallback state, 含 `fast_path_blocking_signal`)
- facade frozen v2 §5 routing table (`fast_path_blocking_signal` derived from `pending_chain` non-empty)
- facade frozen v2 §7.7 (Conversation_fast_path hand-off)

### 3.4 Open Questions

**Q1**: borderline 决策时是否也禁用 fast path? 例如 `borderline_decision_marker` 非空时
- 倾向: **是**, blocking signal 扩展为 `pending_chain non-empty OR borderline_decision_marker non-empty`
- 实施期看 100-task benchmark 数据决定

### 3.5 cc Validation Hooks

```bash
# 1. NaiveRouter 隔离 — fast path 是 NaiveRouter 不涉及的 governed pipeline 内部
# 不需要 NaiveRouter grep

# 2. facade.fast_path_blocking_signal 检查在 classify 之前
grep -rn "fast_path_blocking_signal\|pending_chain" core/governed_router.py
# 应该在 ConversationIntentClassifier classify 路径上有命中
```

### 3.6 Anchors compliance

Fast path blocking 是 1 个 governance signal 扩展, 主修跳步执行 (chain 中途不被 fast path 短路). NaiveRouter 不涉及 fast path.

---

## §4. Component #7 — Standardizer Fallback 触发 Clarification

### 4.1 现状

`services/standardization_engine.py` 有 6-level cascade. fallback tier (default + abstain) 命中时**直接 silent default**, 不主动 clarify. Layer 1 整体 89.3% 但 fallback tier 准确率 21.7% — 这是 Phase 9.1.0 Step 2.5 之前的瓶颈 #2.

### 4.2 v1.5 改动

fallback tier 命中时改为触发 clarification 通过 facade:

| 改动 | file:line 候选 |
|---|---|
| Standardizer fallback tier (default tier) 命中时, 不再直接 return default value, 而是写 facade `pending_clarification_slot` + `clarification_origin = 'standardizer_fallback'` | `services/standardization_engine.py` fallback tier 实施处 |
| abstain tier 命中时同样行为 | 同上 |
| 扩 alias / fuzzy 规则 (减少落到 fallback) | YAML 配置 |
| LLM tier 增强 (更积极介入) | `services/standardization_engine.py` LLM tier 实施处 |

不动:
- 6-level cascade 整体结构
- standardize 接口签名

### 4.3 跟 facade 协同

引用:
- facade frozen v2 §4.4 (Clarification state, 含 `pending_clarification_slot` + `clarification_origin`)
- facade frozen v2 §7.8 (Standardizer fallback hand-off)

### 4.4 Open Questions

**Q1**: alias / fuzzy 规则扩展具体做哪些
- 实施期根据 100-task benchmark fallback tier 命中分布决定
- 不阻塞设计

**Q2**: LLM tier 增强的判断阈值 (什么 confidence 下让 LLM tier 介入)
- 实施期最终拍板

### 4.5 cc Validation Hooks

```bash
# 1. NaiveRouter 隔离 — Standardizer 可能被 NaiveRouter 共享, 但 facade 写入只在 governed 路径
grep -rn "facade\.set" services/standardization_engine.py
# 应该只在 governed-pipeline-triggered 代码路径下

# 2. fallback tier 不再 silent default
grep -rn "default_value\|silent_default" services/standardization_engine.py
# 实施前 baseline → 实施后应该减少
```

### 4.6 Anchors compliance

Standardizer fallback 改为主动 clarify, 修复多轮状态漂移 (主) + 参数组合非法 (间接, fallback default 可能导致非法组合). 不动 standardize 算法. NaiveRouter 共享 standardize, 但 facade 写入隔离守住.

---

## §5. Component #8 — PCM File Context Bug Fix

### 5.1 现状

阶段 1a Step 1 (Run 7 trace recheck) 暴露: 用户上传文件后, `file_relationship_resolution` step 已经触发 + grounding 进 SessionContextStore + fact_memory, 但 `ClarificationContract` 仍然激活 PCM 要求"请上传文件". 这是 ClarificationContract 不读 file grounding 状态的 bug.

### 5.2 v1.5 改动

ClarificationContract `_detect_confirm_first` 之前加 file grounding 状态检查:

| 改动 | file:line 候选 |
|---|---|
| ClarificationContract 在 PCM 激活判断前, 检查 `facade.get("recent_tool_results_index")` 是否含 file_analysis 类 entry | `core/contracts/clarification_contract.py` PCM 激活路径 |
| 如果 file 已 grounded, 不激活 PCM (跳过"请上传文件" 提示) | 同上 |

总改动量: ~10-15 LOC.

### 5.3 跟 facade 协同

引用:
- facade frozen v2 §4.3 (Parameter state, 含 `recent_tool_results_index`)
- facade frozen v2 §7.9 (PCM 文件上下文 hand-off)

### 5.4 Open Questions

无.

### 5.5 cc Validation Hooks

```bash
# PCM 激活前检查 file grounding
grep -B5 -A5 "collection_mode_active\|pcm_active" core/contracts/clarification_contract.py | grep "recent_tool_results_index"
# 应该有命中 (验证 PCM 激活前真的有 grounding 检查)
```

### 5.6 Anchors compliance

PCM bug fix 修复多轮状态漂移 (用户已上传文件被误判为没上传). 不动 ClarificationContract 主算法. NaiveRouter 不涉及 PCM.

---

## §6. Component #9 — DependencyContract 实施化

### 6.1 现状

阶段 1b pre-audit Finding A: `core/contracts/dependency_contract.py:12` 是空壳 — 只有 class 声明, 没有 `before_turn()` 实现. v1.0 工具依赖图前向校验在 `core/router.py` inner_router state loop 内 (`router.py:8811/9305/10763`), 不在 contract pipeline 里.

阶段 1b 还发现 shortcut path (`_consume_decision_field` / `_maybe_execute_from_snapshot`) 完全绕过 graph check.

### 6.2 v1.5 改动

把 `validate_tool_prerequisites` 包装成 contract:

| 改动 | file:line 候选 |
|---|---|
| `DependencyContract.before_turn(context, facade) -> ContractDecision` 实施 | `core/contracts/dependency_contract.py` |
| `DependencyContract.validate_chain(chain_plan, completed_steps, facade) -> DependencyValidationResult` 实施 (IntentResolver §6.4 调用入口) | 同上 |
| 内部包装现有 `validate_tool_prerequisites` (不重写依赖图算法) | 引用 `core/router.py:8811/9305/10763` 现有逻辑 |
| 注册到 GovernedRouter contract pipeline | `core/governed_router.py` contract list |

注意: shortcut path 上的 graph check 决策由 component #10 拍板.

### 6.3 跟 IntentResolver / Component #10 协同

引用:
- IntentResolver frozen v2 §6.4 (调 `DependencyContract.validate_chain`, 不复制依赖图逻辑)
- IntentResolver frozen v2 §8.4 (chain validation 期间调用)
- 本文档 §7 (Component #10 shortcut path dependency check)

### 6.4 Open Questions

**Q1**: `validate_chain` 的内部行为 — 跟 `before_turn` 共享代码 vs 独立
- 倾向: **共享** — 都包装 `validate_tool_prerequisites`, 接口不同 (单工具 vs chain) 但底层算法同一
- 实施期最终拍板

**Q2**: DependencyContract before_turn 在 contract pipeline 顺序
- 倾向: **OASCContract → IntentResolver → DependencyContract → ClarificationContract → ExecutionReadinessContract → ExecutionContinuation**
- 实施期 audit 现有 contract pipeline 顺序后最终拍板

### 6.5 cc Validation Hooks

```bash
# 1. NaiveRouter 隔离
grep -rn "DependencyContract\|dependency_contract" core/naive_router.py
# 必须 0 命中

# 2. DependencyContract 不复制依赖图算法
grep -rn "build_dependency_graph\|tool_prerequisites_logic" core/contracts/dependency_contract.py
# 应该是调用 router.py 现有 validate_tool_prerequisites, 不复制逻辑

# 3. 现有 router.py validate_tool_prerequisites 不被删除 (DependencyContract 复用)
grep -rn "def validate_tool_prerequisites" core/router.py
# 必须 ≥ 1 命中
```

### 6.6 Anchors compliance

DependencyContract 实施化把现有 router-internal 逻辑上升为 contract pipeline 一员, **强化卖点 #3a** (工具依赖图前向校验). 不引入新依赖图算法, 是组件接口扩展. NaiveRouter 隔离守住. 注意论文 §4 表述精度调整 list (Part 1 §1.8 项 1+2): v1.0 是 router-internal, v1.5 才 contract-pipeline-level.

---

## §7. Component #10 — Shortcut Path Dependency Check

### 7.1 现状

阶段 1b pre-audit + Option A 落地后, shortcut path (`_consume_decision_field` / `_maybe_execute_from_snapshot`) 上 cross-constraint 已经有 trace dump. 但 tool dependency graph check 在 shortcut path 上**完全不触发** — 这是 Hard 部分推迟到 v1.5 设计阶段的项.

### 7.2 v1.5 改动 — 设计期拍板"软记录, 不硬 block"

(本节是阶段 1b pre-audit §5 Option C 的设计期拍板.)

| 改动 | file:line 候选 |
|---|---|
| `_execute_from_snapshot()` 入口加 `DependencyContract.validate_chain_step(tool_plan, facade)` 调用 | `core/governed_router.py:_execute_from_snapshot()` |
| validation 失败 (即 dependency 缺失) **不 block 执行**, 只 record 到 `block_telemetry` | 同上 |
| `block_telemetry` entry 标 `decision: "shortcut_path_dependency_check"` + `passed: false` + `missing_prerequisites: [...]` | 同上 |

总改动量: ~25 LOC.

**为什么软记录 (record only) 不硬 block**:
- 阶段 1b pre-audit §5 已 surface: shortcut path 上 `available_results` 在 line 755 被 clear, 硬 block 的 dependency check 会**永远报告 "all prerequisites missing"** — 这恰好是 Run 4 (no_graph) ablation 想证明的. 用 record only 让 Run 1 能正常执行 (现有行为), Run 4 ablation 通过 trace 数据看 graph check 影响
- 硬 block 引入 governance 行为变化, 违反 "trace recording only" 范围约束
- 跳过完全不做, 失去 ablation 数据来源

### 7.3 跟 IntentResolver / Component #9 协同

引用:
- IntentResolver frozen v2 §6.4 (chain validation 规则 4 调 DependencyContract)
- 本文档 §6 (Component #9 DependencyContract 实施化)

注意: shortcut path 触发的是单步 dependency check (`validate_chain_step`), IntentResolver 触发的是 chain-level dependency check (`validate_chain`). 两个接口都在 DependencyContract.

### 7.4 Open Questions

**Q1**: shortcut path 是否未来升级为硬 block (v2 决定)
- v1.5 不做硬 block. 留 v2 评估 — 取决于 Phase 9.3 Run 4 ablation 数据是否足够说明软记录的诊断价值

### 7.5 cc Validation Hooks

```bash
# 1. shortcut path 加了 dependency check 调用
grep -rn "DependencyContract\|validate_chain_step" core/governed_router.py
# 应该在 _execute_from_snapshot 区域有命中

# 2. 不引入硬 block 行为
grep -rn "raise.*DependencyError\|return.*BLOCKED" core/governed_router.py
# _execute_from_snapshot 区域应该 0 命中 (软记录不抛异常)
```

### 7.6 Anchors compliance

Shortcut path dependency check 软记录是 trace observability 升级, 不动 governance 决策. 修复 Run 4 ablation 证据缺口. NaiveRouter 不涉及 shortcut path.

---

## §8. Component #11 — Reconciler "Clarify but Empty Question" Fall-through

### 8.1 现状

阶段 1b pre-audit 暴露: shortcut path 真实触发原因之一是 reconciler 给出 `decision_value="clarify"` 但 `clarification_question` 为空时的 fall-through 路径. 这种 borderline 决策没有显式标记, ClarificationContract / IntentResolver 下一 turn 不知道当前在 borderline 路径.

### 8.2 v1.5 改动

加 1 个 facade write 标记 borderline 决策:

| 改动 | file:line 候选 |
|---|---|
| `_consume_decision_field` 内, reconciler 返回 `decision_value="clarify"` 但 question empty 时, 调 `mark_borderline(facade, source_trace)` | `core/governed_router.py:_consume_decision_field` |
| `mark_borderline` 实现: `facade.set("borderline_decision_marker", source_trace_summary)` | 新加 helper function |

总改动量: ~10 LOC.

### 8.3 跟 facade / Clarification 协同

引用:
- facade frozen v2 §4.5 (`borderline_decision_marker` 字段)
- facade frozen v2 §7.11 (Reconciler fall-through hand-off)
- 本文档 §2 (Component #5 ClarificationContract 读 borderline_decision_marker)

### 8.4 Open Questions

**Q1**: borderline_decision_marker 跨 turn 持久化策略
- 写入后什么时候清除 — 下一 turn 处理完就清, 还是保留多 turn?
- 倾向: **下一 turn ClarificationContract 处理后立即清** (避免老 marker 影响后续判断)
- 实施期最终拍板

### 8.5 cc Validation Hooks

```bash
# mark_borderline 调用点
grep -rn "mark_borderline\|borderline_decision_marker" core/governed_router.py
# 应该在 _consume_decision_field 区域有命中
```

### 8.6 Anchors compliance

Borderline marker 是 governance signal 扩展, 修复多轮状态漂移 (borderline 路径不被 invisibly 走). NaiveRouter 不涉及 reconciler.

---

## §9. Component #12 — llm_telemetry Trace Key

### 9.1 现状

阶段 1a Step 2 期间已经实施 `llm_telemetry` 部分 (cache telemetry 已加, commit `3565500`). 但完整 LLM call observability (cache / tokens / wall_time / model) 跨所有 LLM call point 没统一. 不同 LLM call 散在多处, telemetry 跨点不一致.

### 9.2 v1.5 改动

完整 llm_telemetry trace key 统一:

| 改动 | file:line 候选 |
|---|---|
| `services/llm_client.py` LLM call 主入口加完整 telemetry 写入 (cache_hit_tokens / cache_miss_tokens / prompt_tokens / completion_tokens / model / wall_time_ms / call_id) | `services/llm_client.py` |
| `core/trace.py` 加新 trace key `llm_telemetry: List[LLMCallTelemetry]` | `core/trace.py` |
| 所有现有 LLM call 点 (AO classifier LLM fallback, IntentResolver, Standardizer LLM tier, etc.) 自动通过 LLM client 走 telemetry | 引用现有调用点 |

总改动量: 已部分完成 (cache telemetry), 完整实施 ~30 LOC + trace key 注册.

### 9.3 跟其他 component 协同

无显式 hand-off. 所有 LLM call 通过统一 LLM client 自动获得 telemetry. IntentResolver / Component #3 AO classifier 等不需要单独写 telemetry 代码.

### 9.4 Open Questions

无.

### 9.5 cc Validation Hooks

```bash
# 1. 所有 LLM call 通过 llm_client 主入口 (不有人绕过 telemetry)
grep -rn "openai\|deepseek_client\.chat" core/ services/ | grep -v llm_client.py
# 应该 0 命中 (所有 LLM call 走 llm_client)

# 2. trace key llm_telemetry 已加
grep -rn "llm_telemetry" core/trace.py
# 必须 ≥ 1 命中
```

### 9.6 Anchors compliance

llm_telemetry 是 evaluation infrastructure 升级 (Part 1 §1.10 Phase 9.3 数据可信度前置项 #3). 不动 governance 决策. 不影响 ablation delta. NaiveRouter 也通过 llm_client 走 telemetry, 不影响隔离 (telemetry read-only, 不影响 NaiveRouter 决策).

---

## §10. Component #13 — Filesystem Hygiene + State Cleanup Protocol

### 10.1 现状

阶段 1.5 + Step 2 暴露: GovernedRouter 实例化时 `MemoryManager._load()` 无条件加载 `data/sessions/history/{session_id}.json`, 没有 fresh-session 检查. 跨 task 跨 trial 复用 session_id 会导致 state 污染 (Step 1.5 验证).

阶段 1a Step 2 跑前 state cleanup 已经在 `evaluation/run_phase9_1_0_step2.py` 实施. 但**这是 evaluation runner 层面**, 不是 GovernedRouter 自身. v1.5 应该把 hygiene 内化.

### 10.2 v1.5 改动

| 改动 | file:line 候选 |
|---|---|
| GovernedRouter `__init__` 加 `fresh_session=True` 选项 (default False 保持兼容) | `core/governed_router.py.__init__` |
| `fresh_session=True` 时, 实例化前清理 `data/sessions/history/{session_id}.json` 跟相关 state file | 同上 |
| Phase 9.3 ablation runner 默认用 `fresh_session=True` | `evaluation/eval_ablation.py` |
| 文档化 session_id 命名规范 (`<purpose>_<task_id>_<timestamp>`) | 集中文档本节 |

不动:
- MemoryManager._load 内部逻辑 (兼容 v1.0 行为)
- 普通生产环境 session 持久化 (default 行为不变)

### 10.3 跟其他 component 协同

无显式 hand-off. 是 evaluation infrastructure / GovernedRouter lifecycle 改动.

### 10.4 Open Questions

**Q1**: fresh_session 是 GovernedRouter init 选项 vs MemoryManager 选项
- 倾向: **GovernedRouter 选项**, MemoryManager 不动
- 实施期最终拍板

**Q2**: state cleanup 范围 — 只清 `data/sessions/history/<session_id>.json` 还是清全部 state file?
- 全部包括: `data/sessions/history/{session_id}.json` + `router_state/{session_id}.json` + 任何 `data/sessions/router_state/{session_id}.json`
- 倾向: **全部清** — fresh_session 语义就是干净起步
- 实施期最终拍板

### 10.5 cc Validation Hooks

```bash
# 1. GovernedRouter __init__ 加 fresh_session 参数
grep -rn "fresh_session" core/governed_router.py
# 必须 ≥ 1 命中

# 2. ablation runner 默认 fresh_session=True
grep -rn "fresh_session.*True\|fresh_session=True" evaluation/eval_ablation.py evaluation/eval_end2end.py
# 必须 ≥ 1 命中

# 3. 普通生产环境兼容 (default 不动)
grep -rn "fresh_session.*False\|fresh_session=False" core/governed_router.py
# default 应该是 False
```

### 10.6 Anchors compliance

Filesystem hygiene 是 evaluation infrastructure 升级 (Part 1 §1.10 Phase 9.3 数据可信度前置项 #2). 不动 governance 决策. 修复 Trial 1 隔离原则 (Part 1 §1.5). NaiveRouter 也走 fresh_session 选项, 不影响隔离.

---

## §11. 实施顺序建议

按依赖关系建议实施顺序 (cc 实施期可调整):

```
Wave 1 (基础设施, Phase 2.5 evaluation infra):
  - Component #12 llm_telemetry (cache telemetry 已部分完成)
  - Component #13 Filesystem hygiene + state cleanup
  → tag v1.5-eval-infra-ready (Part 1 §1.10 锚点)

Wave 2 (核心架构, Phase 9.1.1):
  - Component #1 facade (已 frozen, 实施开始)
  - Component #9 DependencyContract 实施化 (facade 不依赖, 但 IntentResolver 依赖)
  - Component #2 IntentResolver multi-step (依赖 facade + DependencyContract)
  → 验收: mode_A 5/5 task 重跑能 chain 推进

Wave 3 (协同改读 facade, Phase 9.1.2):
  - Component #3 AO classifier (代码不动, 加 facade 参数 + classify 内部读 facade)
  - Component #4 ExecutionContinuation (改读 facade)
  - Component #5 Clarification + Reconciler (改读 facade)
  → 验收: 主路径无 silent regression

Wave 4 (其他改动, Phase 9.1.3):
  - Component #6 Fast path blocking
  - Component #7 Standardizer fallback
  - Component #8 PCM file context bug
  - Component #10 Shortcut path dependency check
  - Component #11 Reconciler fall-through
  → tag v1.5-architecture-frozen
```

每 Wave 一个 commit batch, checkpoint 验收完整 wave 完成. 不每组件单独 stop & report.

---

## §12. 全局 Open Questions

跨 component 共享的 open questions, 实施期统一决定:

**Global Q1**: Wave 之间 cc 是否需要 stop & report 让用户拍板, 还是 cc 自主推进
- 倾向: **每 Wave 完成后 cc stop & report 一次**, 用户 review 验收数据再启动下一 Wave
- 跟 Part 1 §1.6.6 架构-工程决策分离一致

**Global Q2**: 实施过程中如果发现某 component 设计文档跟实际代码 mismatch, 处理流程
- 倾向: **小 mismatch (file:line 偏移) cc 自主调整 + commit message 记录**
- **大 mismatch (接口签名 / 算法假设错误) cc STOP & report**, 用户回到设计文档修订
- 实施期严格执行

**Global Q3**: 实施期发现需要 v1.5 scope 之外的改动 (例如 fix 一个跟 mode_A 无关的 bug)
- 倾向: **不在 v1.5 scope 内. 任何 scope 外改动 STOP & report, 用户决定是否纳入**
- 跟 Part 1 §1.6.5 scope creep 监控一致

---

## §13. 全局 Validation Hooks Summary

集中文档全部 component 的 cc validation hook 汇总, 实施期 cc 可一次性跑全部:

```bash
# === NaiveRouter 隔离全局检查 ===
grep -rn "ConversationStateFacade\|conversation_state_facade\|plan_multi_step\|ChainPlan\|ToolPlan\|replan_after_revision\|repair_chain\|IntentResolverMultiStep\|AOClassifier\|AOClassType\|DependencyContract\|dependency_contract\|mark_borderline\|borderline_decision_marker" core/naive_router.py
# 必须 0 命中 — NaiveRouter 完全不导入 v1.5 governance 模块

# === facade 字段命名冲突全局检查 ===
grep -rn 'last_user_message\|chain_origin_turn\|last_chain_advance_reason\|clarification_origin\|revision_invalidated_steps\|borderline_decision_marker\|completed_steps_index' core/ services/ | grep -v conversation_state_facade.py
# 应该只在 facade routing 内, 其他代码通过 facade 访问

# === Trace step type 不冲突 ===
grep -rn "intent_resolution_multi_step_plan\|intent_resolution_revision_replan\|intent_resolution_chain_repair\|intent_resolution_validation_failed\|conversation_state_update\|llm_telemetry" core/trace.py
# 必须有命中 (新加) 但不重复定义

# === IntentResolver 不复制依赖图逻辑 ===
grep -rn "validate_tool_prerequisites\|tool_dependency_graph" core/contracts/intent_resolver*.py
# 必须 0 命中 — IntentResolver 调 DependencyContract.validate_chain

# === DependencyContract 不重写依赖图算法 ===
grep -rn "build_dependency_graph\|tool_prerequisites_logic" core/contracts/dependency_contract.py
# 必须 0 命中 — DependencyContract 调 router.py 现有 validate_tool_prerequisites
```

任一异常 → STOP & report.

---

## §14. Cross-Reference 跟 Frozen 文档关系

集中文档的所有设计决策在 frozen 文档中已经引用确立. 本节列具体 cross-reference:

| Component | 主要引用 frozen 文档 |
|---|---|
| #4 ExecutionContinuation | facade §4.2, §5, §7.4; IntentResolver §7.3, §8.3 |
| #5 Clarification + Reconciler | facade §4.4, §4.5, §7.5 |
| #6 Fast path blocking | facade §4.5 (`fast_path_blocking_signal`), §7.7 |
| #7 Standardizer fallback | facade §4.4, §7.8 |
| #8 PCM file context bug | facade §4.3 (`recent_tool_results_index`), §7.9 |
| #9 DependencyContract 实施化 | IntentResolver §6.4, §8.4; 本文档 §7 |
| #10 Shortcut path dependency check | IntentResolver §6.4; 本文档 §6 |
| #11 Reconciler fall-through | facade §4.5 (`borderline_decision_marker`), §7.11 |
| #12 llm_telemetry | Part 1 §1.10 (Phase 9.3 数据可信度前置项 #3) |
| #13 Filesystem hygiene | Part 1 §1.5 (Trial 1 隔离原则), §1.10 前置项 #2 |

frozen 文档是设计 ground truth. 本集中文档是各 component 的实施 spec, 引用 frozen 文档不重复设计决策.

---

**End of v1.5 Components 4-13 Consolidated Design document — frozen v2**

**Frozen 状态**: 2026-05-06 kirito approved. 仅 §12 global open questions 实施期解决时回头更新对应组件章节.

---

## 🎯 设计阶段终点 (Design Phase End)

本文档 frozen 之后, **v1.5 阶段 2 设计阶段全部完成**. 4 份 frozen 文档构成 `v1.5-design-frozen` tag 的完整内容:

1. `docs/architecture/v1_5_design_principles.md` (Part 1, FROZEN)
2. `docs/architecture/v1_5_conversation_state_facade.md` (Component #1, FROZEN v2)
3. `docs/architecture/v1_5_intent_resolver_multi_step.md` (Component #2, FROZEN v2)
4. `docs/architecture/v1_5_ao_classifier_dual_axis.md` (Component #3, FROZEN v2)
5. `docs/architecture/v1_5_components_4_13_consolidated.md` (Component #4-13, **FROZEN v2 ← 本文档**)

下一步: 实施阶段 Wave 1 — Phase 2.5 evaluation infrastructure (Component #12 llm_telemetry + Component #13 Filesystem hygiene), tag `v1.5-eval-infra-ready` 后进 Phase 9.1.1 (Component #1 + #9 + #2 实施).
