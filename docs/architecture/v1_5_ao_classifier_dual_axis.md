# v1.5 AO Classifier — 双轴语义 — Component #3 Design

**Document path**: `docs/architecture/v1_5_ao_classifier_dual_axis.md`
**Version**: **frozen v2** (拍板完成 2026-05-06, kirito approved)
**Last updated**: 2026-05-06
**Branch**: `phase9.1-v1.5-upgrade`

---

## §0. Document Status & Conventions

### Status

| Field | Value |
|---|---|
| Status | **frozen v2** (kirito approved 2026-05-06) |
| Frozen tag (target) | `v1.5-design-frozen` (跟 facade + IntentResolver + 集中文档一起打) |
| References | Part 1 frozen + ConversationState facade frozen v2 + IntentResolver frozen v2 + Anchors |
| Referenced by | Component 4-13 集中文档 |
| Frozen 后修改流程 | 仅 §10 open question 实施期解决时回头更新对应章节. 其他章节 frozen 不可改动, 改动须回到设计阶段 review. |

### 命名约定

- **AOClassType**: 用户消息分类的 enum 命名, 全大写下划线
- **AOStatus**: AO 生命周期状态的 enum 命名, 全大写下划线
- 双轴: 两个独立 enum, 不组合成一个新 enum, 不强制 cross-product 完整性

### file:line 引用规范

跟 facade + IntentResolver 一致: 基于 `phase9.1-v1.5-upgrade` HEAD 当时代码状态. AO classifier 代码已存在, 实施期 cc 验证不应触发 file:line 偏移 (因为 v1.5 不动 classifier 算法).

### 阅读建议

- 第一次读: §1 - §2 (背景 + 核心决策, 看清"代码不动"性质)
- 实施 cc 主要参考: §4 (双轴状态空间) + §5 (facade context 注入) + §6 (hand-off) + §11 (Codex validation hooks)
- 设计 review: 全文

---

## §1. Background & Scope

### 1.1 v1.0 AO Classifier 现状 — 3 状态全部已实现

Phase 9.1.0 codebase audit Finding A 确认:

- v1.0 `core/ao_classifier.py` 现有 3 个 AOClassType 状态: NEW_AO, CONTINUATION, REVISION
- 3 个状态**全部完整实现**, 不是 enum 占位也不是 partial
- 没有 REFINEMENT 跟 TERMINATION (整个 codebase 0 命中)

之前 handoff 文档凭印象写"5 状态机当前部分实现 (NEW_AO + CONTINUATION 2 状态)" 是错的. Phase 9.1.0 Finding A 拍板 (Part 1 §1.7 已固化): 不强加 REFINEMENT/TERMINATION 伪状态, AOClassType 保持 3 状态.

### 1.2 双轴语义来源 — 不是新设计, 是现有代码语义层确认

v1.0 codebase 已经有两个独立 enum:

- **AOClassType** (`core/ao_classifier.py`): NEW_AO / CONTINUATION / REVISION — 用户消息相对于当前 AO 的关系
- **AOStatus** (`core/analytical_objective.py:10-16`): CREATED / ACTIVE / REVISING / COMPLETED / FAILED / ABANDONED — AO 自身 lifecycle

两个 enum 在 v1.0 各自工作, 没有显式"双轴" framing. v1.5 的工作是:
- **语义层确认双轴正交** (用户消息分类 × AO lifecycle 是两个独立维度, 不是 5 状态机一个维度)
- **跨 component 协同 hand-off** (AO classifier 读 facade context 改善分类, REVISION 触发 IntentResolver re-plan)
- **论文 §4 narrative 表述精度** (用 "AOClassType + AOStatus 双轴 9 状态空间" 替代 "5 状态机", 反映代码现实)

### 1.3 v1.5 改动 — 零算法改动

v1.5 component #3 不改 AO classifier 分类算法. 改的是:

| 改动 | 性质 |
|---|---|
| `classify()` 接口签名加 `facade` 参数 | 接口扩展, 接收的 context 多了几个字段 |
| classifier 内部读 facade 字段帮助决策 | input context 扩展, 不是算法变化 |
| REVISION 输出后调 IntentResolver.replan_after_revision | 跨 component hand-off 新加, classifier 自己输出不变 |

跟 IntentResolver §7.5 "扩展不替换" 同等性质 — v1.0 代码保留可工作, v1.5 接口扩展提供更多 context.

### 1.4 不解决的问题 (留 v2)

- AOClassType 加新状态 (REFINEMENT / TERMINATION 等). v1.5 锁死 3 状态, 不引入伪状态
- AO classifier 算法本身改动 (rule-based → LLM-only / fine-tune / etc.)
- 多 AO 并行 (v1.5 假设串行, 单 active AO)
- 跨 session AO 关系
- AO classifier 决策可解释性增强 (例如 SHAP / attention 可视化)

详见 §9 Non-Goals.

### 1.5 跟 facade + IntentResolver 的协同范围

- **跟 facade (component #1)**: classifier 读 `current_objective` / `pending_chain` / `last_user_intent` 等字段
- **跟 IntentResolver (component #2)**: REVISION 触发 `replan_after_revision` 接口

本文档不重复 facade schema 跟 IntentResolver 接口定义, 引用 + 描述协同点.

---

## §2. Core Design Decisions

### 2.1 AO Classifier 代码不动 — v1.5 是接口扩展不是算法变化

(本节是 component #3 最核心的 framing, 跟 IntentResolver §7.5 "扩展不替换" 同等性质.)

**Framing**: AO classifier 在 v1.5 通过 ConversationState facade 获得 cross-turn context, 分类决策的 input 更丰富, 但**分类算法本身不变**. 论文 §4 描述时说 "v1.5 AO classifier 接收 facade context, 分类准确性在 multi-turn 场景提升", 不是 "v1.5 修改了 AO classifier 算法".

具体 v1.5 改动表 (跟 §1.3 一致):

| v1.0 vs v1.5 | v1.0 | v1.5 |
|---|---|---|
| 分类算法 | rule-based + LLM fallback (现有) | **不变** |
| 输出 enum | NEW_AO / CONTINUATION / REVISION | **不变** (3 状态) |
| `classify()` 接口签名 | `classify(message, context) -> AOClassType` | `classify(message, context, facade) -> AOClassType` (加 facade 参数) |
| classifier 读的 input | message + 现有 context | message + context + **facade 字段 (新增)** |
| REVISION 输出后行为 | (无显式 hand-off) | **触发 IntentResolver.replan_after_revision** |

### 2.2 双轴语义正交, 不是 cross-product 状态机

AOClassType (3) × AOStatus (6) = 18 cross-product 组合, 但**不是所有 18 组合都合法** — 有些组合现实中不出现 (例如 user 发新消息时 AO 处于 ABANDONED 状态), 有些组合是无意义的 (例如 NEW_AO + COMPLETED).

设计原则: **两轴独立定义, 不强制 cross-product 完整性**. 实际有效组合见 §4.3.

这跟"5 状态机"或"9 状态机"语义不同:
- 5 状态机: 一个状态空间, 5 个互斥状态, 状态转移图
- 双轴语义: 两个**独立的状态空间**, 每个状态空间内部有自己的转移图, 跨轴组合不需要完整覆盖

论文 §4 描述精度上避免 "9 状态机" 这种把双轴误读为单轴的表述.

### 2.3 REFINEMENT / TERMINATION 不引入

(锁死, 跟 Part 1 §1.7 拍板一致.)

理由:
- REFINEMENT (LLM 澄清后用户补充信息) 已经是 CONTINUATION 的子模式 — 现有 ClarificationContract 走 `is_resume` 路径已经处理这个场景
- TERMINATION 是**结果**不是**消息分类**, 不属于 AOClassType (用户消息相对于 AO 的关系) 语义层. AOStatus 已经有 COMPLETED / FAILED / ABANDONED 3 个 lifecycle 终态, 覆盖 termination 的所有形态
- 加伪状态会污染 AOClassType 语义, 误导论文 §4 reviewer

如果实施期发现需要新分类, 必须回到设计阶段 review, 不在 v1.5 阶段直接加.

### 2.4 facade context 注入只读, 不写

AO classifier 在 v1.5 **只读 facade**, 不写 facade. classifier 输出 AOClassType 给 OASCContract, OASCContract 根据分类结果触发 facade 写入 (例如 NEW_AO → 创建 AO + facade.set('current_objective', ...)).

这件事跟 facade §7.3 一致. classifier 不直接 facade.set, 因为 classifier 是 read-only decision component, 不是 state writer.

---

## §3. Anchors Compliance Checklist

设计前置约束.

### 3.1 跟核心论点 (framework deterministic + LLM semantic) 一致性

| Aspect | 跟核心论点关系 |
|---|---|
| AO classifier 代码不动 | 现有 framework deterministic 行为保留 ✓ |
| facade context 注入只读 | classifier 是 framework decision component, 不引入 LLM 决策路径变化 ✓ |
| REVISION 触发 IntentResolver re-plan | framework 强制 hand-off, LLM 在 IntentResolver 内做语义重规划 ✓ |
| 双轴正交语义 | 反映代码现实, framework 状态结构清晰 ✓ |

**Verdict**: AO classifier v1.5 改动 (接口扩展 + 协同 hand-off) 不改变核心论点定位, 跟 framework deterministic + LLM semantic 一致.

### 3.2 跟选题定位 (架构 / 工程 / 系统贡献) 一致性

AO classifier v1.5 改动是**架构层面**:

- 接口扩展 (`classify` 加 facade 参数) 是接口契约变化
- 跨 component 协同 (REVISION → IntentResolver re-plan) 是新协调点
- 双轴语义确认是论文 §4 表述精度提升

**不是 LLM 算法工作**:

- v1.5 不调整 classifier 内的 LLM prompt (classifier 内部 LLM 调用是现有 v1.0 行为, 不动)
- 不 fine-tune classifier
- 不引入新 LLM 分类模型

**Verdict**: AO classifier 改动跟 IntentResolver 同样是接口 + 协调点扩展, 是架构贡献.

### 3.3 跟 3 类失败模式分类一致性

| 失败模式 | AO classifier 修复方式 |
|---|---|
| **多轮状态漂移** | 主修 — facade context 让 classifier 看到 `current_objective` + `pending_chain` 状态, 减少 Turn 2 误分类 NEW_AO (mode_A 5/5 reproduced 的关键修复路径) |
| 跳步执行 | 间接修 — classifier 正确分 CONTINUATION 后, IntentResolver 不重新 plan, ExecutionContinuation 自动推进 chain |
| 参数组合非法 | 不直接修 |

**Verdict**: AO classifier 主修 multi-turn drift, 不引入第 4 类失败模式.

### 3.4 跟 4 评估层次一致性

| 层次 | AO classifier 影响 |
|---|---|
| Layer 1 标准化准确率 | 不影响 — classifier 不做参数标准化 |
| Layer 2 端到端 | 间接影响 — classifier 准确分类是 mode_A 修复的前置, Phase 9.3 ablation 中 facade-disabled run 跟 IntentResolver-disabled run 都依赖 classifier 跟 facade context 协同 |
| Layer 3 Shanghai e2e | 直接影响 — Run 7 Turn 2 必须正确分 CONTINUATION 才能闭环 |
| Layer 4 用户研究 | 不在范围 |

**Verdict**: AO classifier 间接 + 直接影响 Layer 2 + Layer 3, 不影响 Layer 1 + Layer 4.

### 3.5 NaiveRouter 隔离 compliance

AO classifier v1.5 接口扩展加 `facade` 参数后, **NaiveRouter 不调** v1.5 接口 — NaiveRouter 自己是 vanilla function calling, 不做 AO 分类.

实施期 cc 验证: `grep -rn "ao_classifier\|AOClassifier\|AOClassType" core/naive_router.py` 必须 0 命中. 跟 §11 验证清单闭环.

**Verdict**: NaiveRouter 隔离守住.

---

## §4. 双轴状态空间定义

本章是 component #3 的核心, 不能压缩.

### 4.1 AOClassType (用户消息分类)

`core/ao_classifier.py` 现有 enum, v1.5 不变:

```python
class AOClassType(Enum):
    NEW_AO = "new_ao"
    CONTINUATION = "continuation"
    REVISION = "revision"
```

业务语义:

| 状态 | 业务语义 |
|---|---|
| **NEW_AO** | 用户发起新分析任务, 跟当前 AO (如果存在) 不相关 |
| **CONTINUATION** | 用户消息延续当前 AO — 例如确认/继续/澄清回答/对当前 chain 的下一步进行 |
| **REVISION** | 用户改变之前的决定 — 例如改参数, 改污染物, 改情景 |

### 4.2 AOStatus (AO 生命周期)

`core/analytical_objective.py:10-16` 现有 enum, v1.5 不变:

```python
class AOStatus(Enum):
    CREATED = "created"
    ACTIVE = "active"
    REVISING = "revising"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"
```

业务语义:

| 状态 | 业务语义 |
|---|---|
| **CREATED** | AO 已创建, chain 未开始 |
| **ACTIVE** | AO chain 在执行中 (pending_chain 非空 或 chain 部分完成但未结束) |
| **REVISING** | 用户触发 REVISION, 旧 AO 进 REVISING 状态, 新 AO 创建 |
| **COMPLETED** | AO chain 全部成功, objective 达成 |
| **FAILED** | AO chain 失败 (错误超出 fallback 能修复的范围) |
| **ABANDONED** | 用户主动放弃 / 长时间不活跃超时 / 等 |

### 4.3 双轴有效组合

3 × 6 = 18 cross-product, 实际有效组合见下表 (Y = 现实中会出现, N = 不会出现):

| AOClassType \ AOStatus | CREATED | ACTIVE | REVISING | COMPLETED | FAILED | ABANDONED |
|---|---|---|---|---|---|---|
| **NEW_AO** | (新 AO 立即从 CREATED 转 ACTIVE) Y | Y (正常 NEW_AO 触发流程) | N (REVISING 中不该新建 AO) | Y (上 AO 完成后用户发新任务) | Y (上 AO 失败后用户改新任务) | Y (上 AO 被弃后新任务) |
| **CONTINUATION** | N (CONTINUATION 必须有 active AO) | Y (主路径 — Run 7 Turn 2 修复目标) | Y (REVISING 期用户回答澄清) | N (COMPLETED 后不该 CONTINUATION) | N (FAILED 后不该 CONTINUATION) | N (ABANDONED 后不该 CONTINUATION) |
| **REVISION** | N (REVISION 必须有可修订 AO) | Y (主路径) | Y (REVISING 中再次 REVISION, 多次改主意) | Y (用户后悔, COMPLETED 之后改主意) | N (FAILED AO 不再 REVISION) | N (ABANDONED 不 REVISION) |

**有效组合数**: 9 个 Y. 这是双轴**实际有效状态空间**大小, 不是简单 18.

注意:
- "9" 跟之前 handoff 文档 "9 状态空间" 这个数字相同, 但语义不同. handoff 误读成 "9 状态机", 实际是 "双轴 9 个有效组合"
- 论文 §4 表述: 用 "双轴 9 个有效组合" 而非 "9 状态机"

### 4.4 状态转移图

每个轴自己的转移图 (跨轴不强制约束):

**AOClassType 转移**: 无约束. 每个 turn 用户消息独立分类, 跟前一 turn 分类无逻辑依赖.

**AOStatus 转移图**:

```
CREATED ─────► ACTIVE ─────► COMPLETED
   │              │
   │              ├─► FAILED
   │              │
   │              ├─► ABANDONED
   │              │
   │              └─► REVISING ──┐
   │                              │
   │                              ▼
   └─────────────────────► CREATED (REVISION 创建新 AO)
                                  │
                                  ▼
                                 ACTIVE
                                  │
                                  ▼
                                COMPLETED (or FAILED / ABANDONED / 再次 REVISING)
```

转移触发器:

| 转移 | 触发 |
|---|---|
| CREATED → ACTIVE | AO 第一次执行 chain step |
| ACTIVE → COMPLETED | pending_chain 空 + completed_steps 满足 objective |
| ACTIVE → FAILED | chain 失败超出 repair 能力 |
| ACTIVE → ABANDONED | session 超时 / 用户主动放弃 |
| ACTIVE → REVISING | AO classifier 输出 REVISION |
| REVISING → (新 AO CREATED) | IntentResolver.replan_after_revision 创建新 AO |

### 4.5 跟 facade `objective_status` 字段映射

facade frozen v2 §4.1 定义:

```python
objective_status: Enum (active / completed / blocked / revising)
```

facade 的 4 状态是 AOStatus 6 状态的**子集映射**:

| facade objective_status | 对应 AOStatus |
|---|---|
| `active` | ACTIVE 或 CREATED (尚未执行第一步) |
| `revising` | REVISING |
| `completed` | COMPLETED |
| `blocked` | FAILED 或 ABANDONED (用户视角下都是"卡住/弃" 状态) |

facade 用 4 状态简化业务语义, AOStatus 保留 6 状态完整 lifecycle. 两者不冲突, facade 是 view.

---

## §5. facade Context 注入

AO classifier v1.5 在 `classify()` 内读 facade 字段帮助分类决策. 本节列具体读哪些字段 + 怎么影响分类.

### 5.1 注入字段表

| facade 字段 | classifier 用途 |
|---|---|
| `current_objective` | 判断是否有 active AO. None → 倾向 NEW_AO. 非 None → 看消息内容判断 CONTINUATION 或 REVISION |
| `pending_chain` | 判断当前 AO 是否还有未完成的 chain. 非空 → 用户消息可能是 CONTINUATION (确认/继续 chain). 空 → 当前 AO 可能 ready to extend, NEW_AO 或 CONTINUATION 都可能 |
| `last_user_intent` | 上一 turn 用户消息. 比对当前消息是否语义延续 (例如"再加一步" / "刚才那个" 类引用) |
| `completed_steps` | summarized list — 当前 AO 已完成的步骤. classifier 判断 REVISION 时 (用户改主意) 看哪些步骤可能被废弃 |
| `objective_status` | AO 当前 lifecycle. ACTIVE / REVISING → 多数 CONTINUATION 或 REVISION. COMPLETED / FAILED / ABANDONED → 多数 NEW_AO |

### 5.2 注入对分类的影响 — Run 7 Turn 2 mode_A 修复关键

mode_A 5/5 reproduced 的核心: v1.0 没有 facade context, classifier 在 Turn 2 把 "对刚才的排放结果做扩散模拟" 5/5 分类为 NEW_AO.

v1.5 加 facade context 后:

```
classifier input (Turn 2):
  message: "对刚才的排放结果做扩散模拟"
  facade.current_objective: AO#1 (still active)
  facade.pending_chain: [calculate_dispersion]  # IntentResolver Turn 1 已规划
  facade.last_user_intent: "用 macro_direct.csv 算上海 3 路段排放, 计算 CO2 和 NOx, 夏季"
  facade.completed_steps: [step_1: macro_emission(CO2:318.90, NOx:67.40)]
  facade.objective_status: active

classifier 分类逻辑 (现有算法 + facade context):
  - current_objective 非 None → 不是 NEW_AO 默认路径
  - pending_chain 非空 (有 dispersion 待执行) → 倾向 CONTINUATION (用户消息匹配 chain head)
  - 消息内容含 "刚才" — 引用前文, 强 CONTINUATION 信号
  - completed_steps 含 emission, message 提 dispersion (chain 下一步) → 强 CONTINUATION 信号

classifier 输出: CONTINUATION ✓ (mode_A 修复)
```

v1.5 不改 classifier 算法, 但 facade context 让算法 input 更丰富, 现有算法 (rule-based + LLM fallback) 自然给出正确分类.

### 5.3 注入数据流

```
ClarificationContract.before_turn 之前
  ↓
OASCContract.before_turn(context, facade) 内
  ↓
ao_classifier.classify(
    message=context.user_message,
    context=context,
    facade=facade,  # v1.5 新增参数
) -> AOClassType
  ↓
OASCContract 根据分类结果决定:
  NEW_AO → AOManager.create_ao(...) → facade.set('current_objective', new_ao_id)
  CONTINUATION → 不创建新 AO, 不动 current_objective
  REVISION → AOManager.revise_ao(current_ao_id) → 触发 IntentResolver.replan_after_revision
```

注意:
- classifier 自己**不写 facade** (按 §2.4)
- OASCContract 根据 classifier 输出决定 facade 写入

### 5.4 注入对 LLM call 数量的影响

v1.0 classifier 内部已有 LLM fallback (rule-based 不能确定时调 LLM). v1.5 加 facade context 后:
- LLM fallback 输入 context 增加 (新加几个 facade 字段)
- LLM call 频率不变 (rule-based 命中时不调 LLM, 跟 v1.0 一致)
- prompt token 略增 (新增字段 ~200 tokens), 不影响 latency

实施期通过 component #12 llm_telemetry 监控 classifier LLM call 实际行为变化, 异常立即 surface.

---

## §6. Hand-off Contracts

本章描述 AO classifier 跟其他 component 的具体接口.

### §6.1 跟 OASCContract — classifier 调用入口

OASCContract.before_turn 是 AO classifier 的唯一调用入口. v1.5 OASCContract.before_turn 接收 facade 参数后传给 classifier.

| 项 | 内容 |
|---|---|
| OASCContract 调用 classifier 接口 | `ao_classifier.classify(message, context, facade) -> AOClassType` |
| classifier 输入 | message + context + **facade (v1.5 新增)** |
| classifier 输出 | AOClassType (NEW_AO / CONTINUATION / REVISION) |
| OASCContract 后续行为 | 根据 AOClassType 触发 facade 写入 / AOManager 操作 / IntentResolver 调用 |
| 触发时机 | OASCContract.before_turn 主流程, 在 ClarificationContract 之前 |

### §6.2 跟 facade (component #1) — 读取 cross-turn context

| 项 | 内容 |
|---|---|
| 读 facade 字段 | `current_objective`, `pending_chain`, `last_user_intent`, `completed_steps`, `objective_status` (5 字段, 见 §5.1) |
| 写 facade 字段 | 无 (classifier 只读, 写由 OASCContract 触发) |
| 触发时机 | classifier.classify() 内 |
| 关键决策 | classifier 是 read-only decision component, 不直接动 facade state |

### §6.3 跟 IntentResolver (component #2) — REVISION 触发 re-plan

REVISION 输出后的 hand-off:

| 项 | 内容 |
|---|---|
| 触发条件 | classifier.classify 输出 AOClassType.REVISION |
| 触发组件 | OASCContract (classifier 输出后) |
| 调用接口 | `intent_resolver.replan_after_revision(context, facade, invalidated_step_ids)` |
| invalidated_step_ids 来源 | OASCContract 根据 user 消息推断哪些 step 被改 (例如用户改 pollutant → emission step 被 invalidate) |
| 数据流 | classifier → REVISION → OASCContract.revise_ao → AOManager.revise_ao → IntentResolver.replan_after_revision → 新 AO 的 pending_chain 写入 facade |
| 关键决策 | classifier 自己不调 IntentResolver, OASCContract 是协调中介 |

实施期注意: invalidated_step_ids 推断逻辑在 OASCContract 内, 不在 classifier 内. classifier 只负责分类, 不负责 invalidation 推断. 这件事跟"classifier 是 read-only decision component"一致.

### §6.4 跟 AOManager — 不直接 hand-off, 通过 OASCContract 间接

classifier 不直接调 AOManager.create_ao / revise_ao. 这些 AO lifecycle 操作由 OASCContract 根据 classifier 输出触发.

理由: classifier 单一职责 (分类), 不承担 lifecycle 写入. 这件事跟现有 v1.0 OASC 结构一致, 不动.

### §6.5 跟 ClarificationContract — 间接, 通过 facade

ClarificationContract 在 OASCContract 之后调用. ClarificationContract 不直接调 classifier, 但读 facade `objective_status` 时间接受到 classifier 输出影响 (因为 OASCContract 已根据分类更新了 facade).

间接 hand-off, 不直接接口调用.

---

## §7. Lifecycle & Persistence

### 7.1 AO Classifier 实例化

跟现有 v1.0 行为一致 — `ao_classifier` 是 GovernedRouter / OASCContract 持有的 dependency. 实例化时机不变.

v1.5 加 `facade` 参数到 classify() 接口, 不影响 classifier 实例化模式.

### 7.2 持久化

AO classifier 自己**无状态**, 不持久化. 每次 classify 是 stateless decision based on input.

state 全部由 facade + 底层 store 持有 (跟 facade frozen v2 §8.2 一致).

### 7.3 进程重启

进程重启 → GovernedRouter 重建 → ao_classifier 重新实例化 → 没有需要恢复的 classifier 内部 state.

---

## §8. Trace Observability

### 8.1 现有 classifier_telemetry 不动

v1.0 现有 trace key `classifier_telemetry` (Phase 9.1.0 codebase audit Task 5 确认存在), 记录 classifier 内部决策 (rule layer / LLM layer / confidence / fallback). v1.5 不加新 trace key, 也不重新设计 classifier_telemetry 结构.

### 8.2 facade context 注入要不要增加 trace 字段

设计期决定: **在 classifier_telemetry 增加 1 个字段 `facade_context_summary`** 记录 classifier 实际读到的 facade 字段值.

理由:
- 实施期诊断需要 — 出问题时知道 classifier 看到什么 facade 状态
- Phase 9.3 ablation 数据需要 — facade-disabled run 跟正常 run 比对要求看到 facade context 对分类的影响
- 跟 facade `conversation_state_update` trace 互补 (facade trace 记 write, classifier trace 记 read)

字段 schema:

```json
{
  "facade_context_summary": {
    "current_objective": "AO#1" | null,
    "pending_chain_length": 1,
    "last_user_intent_brief": "用 macro_direct.csv...",
    "completed_steps_count": 1,
    "objective_status": "active"
  }
}
```

不 dump 完整字段值 (避免 trace 膨胀), dump summary.

### 8.3 跟 facade trace 协同

classifier_telemetry 跟 facade `conversation_state_update` trace 时间线:

```
classifier.classify() 调用
  → trace classifier_telemetry (含 facade_context_summary)
  → 输出 AOClassType
OASCContract 根据输出
  → 触发 facade.set(...)
    → trace conversation_state_update
```

两个 trace 在时间上紧邻, 但记录不同事件. classifier 记 read, facade 记 write.

---

## §9. Non-Goals

明确不做:

1. **AOClassType 加新状态** (REFINEMENT / TERMINATION 等). v1.5 锁死 3 状态. 跟 §2.3 闭环
2. **AO classifier 算法改动** — rule-based + LLM fallback 现有结构不动
3. **classifier 内 LLM 改动** — 不 fine-tune, 不换模型, 不调 prompt
4. **多 AO 并行** — v1.5 假设串行, 单 active AO. 多 AO 留 v2
5. **跨 session AO 关系** — 单 session 内独立, 跨 session 留 v2
6. **classifier 决策可解释性增强** (SHAP / attention 可视化等) — 留 v2 或永远不做
7. **AOStatus 加新状态** — 6 lifecycle 已覆盖完整 lifecycle
8. **LLM 算法工作** — 跟 IntentResolver §11 一致, v1.5 component #3 也不做 LLM 算法贡献

---

## §10. Open Questions

预期 3 个 open question, 比 facade / IntentResolver 少 (因为 component #3 改动小).

### Open Q1: facade_context_summary 字段精度

§8.2 加的 trace 字段 dump summary 还是完整值?
- summary (倾向): trace 不膨胀, 但实施期诊断信息可能不够
- 完整值: 诊断信息完整, 但 trace size 增加 (尤其 completed_steps 长 chain 时)

倾向: **summary**. 实施期监控 trace size, 如果 summary 不够诊断再升级.

### Open Q2: REVISION invalidated_step_ids 推断逻辑

§6.3 提到 invalidated_step_ids 由 OASCContract 推断. 推断逻辑选项:
- (a) Rule-based: 匹配关键词 (例如 "改 pollutant" → emission step invalidate)
- (b) LLM-based: 让 LLM 看用户消息推断哪些 step 该 invalidate
- (c) Hybrid: rule-based 先尝试, 不能确定时 LLM fallback

倾向: **(c) hybrid**. 跟现有 classifier 架构 (rule + LLM fallback) 一致. 实施期最终拍板, 取决于 100-task benchmark 中 REVISION case 的实际多样性.

### Open Q3: Multi-turn 场景 AOStatus 自动转移

`ABANDONED` 在 v1.0 是否有自动触发逻辑 (例如 session 超时 N turn 没活动)? 还是只在用户主动放弃时手动触发?

实施期 audit `core/analytical_objective.py` 跟 AOManager 现有 ABANDONED 触发路径, 决定 v1.5 是否需要保留 / 加强自动转移. 不在 component #3 范围, 但 surface 一下让 cc 实施期注意.

---

## §11. Validation Hooks for Codex

schema frozen 后, 第一个 cc 任务按本章验证.

### 11.1 cc 验证任务清单

按顺序跑, 任一失败立即 STOP & report:

1. **NaiveRouter 隔离验证**
   ```bash
   grep -rn "ao_classifier\|AOClassifier\|AOClassType" core/naive_router.py
   ```
   必须 0 命中.

2. **AOClassType enum 不动验证**
   - file: `core/ao_classifier.py`
   - 验证: `AOClassType` enum 含且仅含 NEW_AO / CONTINUATION / REVISION 3 个成员
   - 任一成员被新增 (例如 REFINEMENT / TERMINATION) → STOP, 跟 §2.3 拍板冲突

3. **AOStatus enum 不动验证**
   - file: `core/analytical_objective.py:10-16`
   - 验证: `AOStatus` enum 含 CREATED / ACTIVE / REVISING / COMPLETED / FAILED / ABANDONED 6 成员
   - 任一变化 → STOP

4. **classifier 算法不动验证**
   - file: `core/ao_classifier.py`
   - 验证: classifier 内部 rule-based + LLM fallback 结构跟 v1.0 一致 (具体函数 / class 结构对比 v1.0-data-frozen)
   - 检查 v1.5 改动只在 `classify()` 接口签名 (新增 facade 参数) + 内部读 facade 字段, 不改算法逻辑
   - 算法逻辑改动 → STOP

5. **`facade_context_summary` trace 字段不跟现有 classifier_telemetry 字段冲突**
   - 验证: 现有 classifier_telemetry 中没有 `facade_context_summary` 字段
   - 命名冲突 → STOP

### 11.2 STOP & report 触发条件

- NaiveRouter 隔离 grep 命中
- AOClassType / AOStatus enum 被改动
- classifier 算法逻辑改动
- trace 字段命名冲突

任一 STOP → 不继续验证, 直接报告 user, 等用户拍板修订.

5 项验证全 pass → component #3 准备进 Phase 9.1.1 实施.

---

## Appendix A: Worked Examples

3 个简短场景, 重点 classifier 的 input/output. detailed turn-by-turn facade state 已在 facade Appendix A.1 + IntentResolver Appendix A.1 覆盖, 本附录只补充 classifier 视角.

### A.1 Run 7 Turn 2 mode_A 修复 — CONTINUATION 分类

```
Input:
  message: "对刚才的排放结果做扩散模拟"
  facade.current_objective: AO#1
  facade.pending_chain: [calculate_dispersion]
  facade.last_user_intent: "用 macro_direct.csv 算上海 3 路段排放..."
  facade.completed_steps: [step_1: macro_emission(CO2:318.90, NOx:67.40)]
  facade.objective_status: active

classifier internal:
  rule layer: 检测 "刚才" 引用前文 + AO#1 active + pending_chain 非空 → 强 CONTINUATION 信号
  LLM fallback: 不需要 (rule 已确定)
  
Output: AOClassType.CONTINUATION

OASCContract 后续:
  - 不创建新 AO
  - facade.current_objective 保持 AO#1
  - 不调 IntentResolver re-plan (CONTINUATION 不重规划)
  - 走主流程, ExecutionContinuation 推进 pending_chain

trace:
  classifier_telemetry:
    rule_layer: matched (continuation)
    facade_context_summary:
      current_objective: AO#1
      pending_chain_length: 1
      objective_status: active
```

跟 v1.0 对比: v1.0 没有 facade context, classifier 5/5 分 NEW_AO (因为 message 里有 "扩散模拟" 这个新工具名 + LLM 没看到 chain context). v1.5 修复.

### A.2 用户改主意 — REVISION 分类

```
Input:
  message: "啊我说错了, 应该算 NOx 不是 CO2"
  facade.current_objective: AO#1
  facade.pending_chain: []  # AO#1 chain 已完成 step_1 emission(CO2)
  facade.last_user_intent: "算乘用车夏季 CO2 排放"
  facade.completed_steps: [step_1: macro_emission(CO2)]
  facade.objective_status: active

classifier internal:
  rule layer: 检测 "说错了" / "应该算 X 不是 Y" 类 REVISION pattern → REVISION 信号
  LLM fallback: 不需要

Output: AOClassType.REVISION

OASCContract 后续:
  - AOManager.revise_ao(AO#1) → AO#1 进 REVISING, 创建 AO#2
  - 推断 invalidated_step_ids = [step_1] (用户改 pollutant, emission 步骤需重做)
  - 调 IntentResolver.replan_after_revision(context, facade, [step_1])
  - IntentResolver 输出新 chain, 写入 facade.pending_chain
  - facade.set('current_objective', 'AO#2')
  - facade.set('revision_invalidated_steps', [step_1])

trace:
  classifier_telemetry:
    rule_layer: matched (revision)
    facade_context_summary:
      current_objective: AO#1
      objective_status: active
      pending_chain_length: 0
```

### A.3 跨 AO 新任务 — NEW_AO 分类

```
Input:
  message: "再分析一下污染热点"
  facade.current_objective: None  # AO#1 已 COMPLETED
  facade.pending_chain: []
  facade.last_user_intent: "对刚才的排放结果做扩散模拟"
  facade.completed_steps: []  # current_objective 切换后清空 (或保留前 AO 的, 看 facade routing)
  facade.recent_tool_results_index: {emission: ref_xxx, dispersion: ref_yyy}  # 跨 AO 仍可用
  facade.objective_status: completed (AO#1)

classifier internal:
  rule layer: 检测 current_objective None + 消息含新任务关键词 ("热点") → NEW_AO 信号
  LLM fallback: 不需要

Output: AOClassType.NEW_AO

OASCContract 后续:
  - AOManager.create_ao(...) → AO#2 (CREATED → ACTIVE)
  - facade.set('current_objective', 'AO#2')
  - 调 IntentResolver.plan_multi_step
  - IntentResolver 利用 recent_tool_results_index 知道 dispersion 已有, 规划单步 chain [analyze_hotspots(use=dispersion_ref)]

trace:
  classifier_telemetry:
    rule_layer: matched (new_ao)
    facade_context_summary:
      current_objective: null
      objective_status: completed
```

跟 facade Appendix A.1 Turn 3 一致, 验证跨 AO recent_tool_results_index 跨 AO 持久 + classifier 正确识别 NEW_AO.

---

## Appendix B: 双轴状态空间 Visual Aid

### B.1 双轴正交结构

```
                   AOStatus (lifecycle, 6 状态)
                          ▲
                          │
    CREATED  ACTIVE  REVISING  COMPLETED  FAILED  ABANDONED
       │       │       │         │         │        │
NEW_AO ┤   Y    Y      N         Y         Y        Y    │
       │                                                  │
CONTIN ┤   N    Y      Y         N         N        N    │── AOClassType (3 状态)
       │                                                  │
REVIS  ┤   N    Y      Y         Y         N        N    │
       │
       └────────────────────────────────────────────────────────►
                          (有效组合 9 个 Y)
```

### B.2 AOStatus 转移路径

```
   CREATED ────► ACTIVE ──┬──► COMPLETED
                          │         │
                          ├──► FAILED
                          │
                          ├──► ABANDONED
                          │
                          └──► REVISING ──► (新 AO CREATED) ──► ACTIVE ──► ...
```

### B.3 AOClassType 跟触发关系

```
NEW_AO        ───► AOManager.create_ao ───► 新 AO (CREATED → ACTIVE)
CONTINUATION  ───► (no AO lifecycle change, 仅 facade pending_chain 推进)
REVISION      ───► AOManager.revise_ao ───► 旧 AO REVISING + 新 AO CREATED
                ───► IntentResolver.replan_after_revision ───► 新 AO ACTIVE
```

---

## Appendix C: Glossary

| 术语 | 含义 |
|---|---|
| AOClassType | 用户消息相对于当前 AO 的关系分类 (NEW_AO / CONTINUATION / REVISION). 现有 enum, v1.5 不变 |
| AOStatus | AO lifecycle 状态 (CREATED / ACTIVE / REVISING / COMPLETED / FAILED / ABANDONED). 现有 enum, v1.5 不变 |
| 双轴语义 | AOClassType × AOStatus 两个独立 enum 的正交组合, 共 18 cross-product 中 9 个有效组合 |
| 9 个有效组合 | §4.3 定义的实际现实中会出现的双轴组合 (9 个 Y), 不是"9 状态机" |
| facade_context_summary | classifier 在 v1.5 加到 classifier_telemetry 的 trace 字段, 记录 classifier 读到的 facade 字段 summary |
| invalidated_step_ids | REVISION 时 OASCContract 推断哪些 completed_steps 被废弃 |
| read-only decision component | classifier 是 framework 决策组件, 只读 facade, 不写 facade |

---

## Appendix D: References

### D.1 Audit references

| Audit | 报告 | 本文档对应章节 |
|---|---|---|
| Phase 9.1.0 codebase audit Finding A | `docs/architecture/phase9_1_0_codebase_audit.md` | §1.1 (3 状态全部已实现, 不强加 REFINEMENT/TERMINATION) |
| Run 7 variance | `docs/architecture/phase9_1_0_run7_variance.md` | §5.2 (mode_A 5/5 reproduced, classifier 5/5 误分类 NEW_AO) |
| 阶段 1a observability | `docs/architecture/phase9_1_0_step3_followup_observability_variance.md` | §8.2 (classifier_telemetry 字段加 facade_context_summary 的设计依据) |

### D.2 Component cross-reference

| 引用方 | 引用本文档章节 |
|---|---|
| facade frozen v2 §7.3 | §6.1 OASCContract 调用 classifier 的 hand-off |
| facade frozen v2 §4.1 (objective_status) | §4.5 facade objective_status 跟 AOStatus 映射 |
| IntentResolver frozen v2 §7.2 (replan_after_revision) | §6.3 REVISION 触发 IntentResolver re-plan |
| IntentResolver frozen v2 §8.2 (AO classifier hand-off) | §6.1 + §6.3 双向引用 |
| Part 1 §1.7 能力 1 (自动多步推进) | §3.3 + §5.2 (classifier 正确分 CONTINUATION 是能力 1 前置) |
| Part 1 §1.10 (Anchors §3c 双轴 narrative) | §1.2 + §2.2 (双轴语义来源跟 narrative) |

---

**End of v1.5 AO Classifier 双轴语义 Component #3 Design document — frozen v2**

**Frozen 状态**: 2026-05-06 kirito approved. 后续 component 文档引用本文档不可推翻. 仅 §10 open question 实施期解决时回头更新对应章节.

下一步: Component 4-13 集中文档.
