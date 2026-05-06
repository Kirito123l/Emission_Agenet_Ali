# v1.5 IntentResolver Multi-Step Planning — Component #2 Design

**Document path**: `docs/architecture/v1_5_intent_resolver_multi_step.md`
**Version**: **frozen v2** (拍板完成 2026-05-06, kirito approved)
**Last updated**: 2026-05-06
**Branch**: `phase9.1-v1.5-upgrade`

---

## §0. Document Status & Conventions

### Status

| Field | Value |
|---|---|
| Status | **frozen v2** (kirito approved 2026-05-06) |
| Frozen tag (target) | `v1.5-design-frozen` (跟 facade + 其他 component 文档一起打) |
| References | Part 1 frozen + ConversationState facade frozen v2 + Anchors |
| Referenced by | Component #4 ExecutionContinuation, Component #5 Clarification + Reconciler 文档 |
| Frozen 后修改流程 | 仅 §12 open question 实施期解决时回头更新对应章节. 其他章节 frozen 不可改动, 改动须回到设计阶段 review. |

### 命名约定

- **chain output 字段命名**: 全小写下划线, 业务语义命名 (`tool_name` / `data_dependencies`), 不带技术前缀
- **ToolPlan / ChainPlan**: dataclass 命名 PascalCase, Python 标准
- **跟 facade schema 字段对齐保证**: facade `pending_chain` 是 `List[ToolPlan]` 容器, ToolPlan 字段在本文档 §4 单一定义, facade §4.2 引用本文档. 双重定义触发 STOP & report.

### file:line 引用规范

跟 facade 文档一致: 基于 `phase9.1-v1.5-upgrade` HEAD `34c2758` (`v1.5-trace-fix-verified` tag) 当时代码状态. 实施期 cc 验证若 file:line 偏移, 按 spec 意图对齐.

### 阅读建议

- 第一次读: §1 - §3 (背景 + 设计决策 + Anchors compliance, **§3.2 是关键章节**)
- 实施 cc 主要参考: §4 (chain output schema) + §5 (LLM prompt design) + §6 (chain validation rules) + §13 (Codex validation hooks) + Appendix B (prompt 完整模板)
- 设计 review: 全文

---

## §1. Background & Scope

### 1.1 v1.0 IntentResolver 现状

v1.0 IntentResolver (现有 `core/contracts/intent_resolution_contract.py`) **只规划单工具**, 不做 chain projection. 阶段 1 audit 数据 (Step 1 variance characterization, 见 Appendix D.1) 暴露这件事是 mode_A 5/5 reproduced 的 root cause 之一:

- Run 7 三 turn 任务 15/15 turn-trial 中, `projected_chain` key 完全 absent
- AO classifier 在 Turn 2 把 "对刚才的排放结果做扩散模拟" 5/5 分类为 NEW_AO, 因为 IntentResolver 没产生 multi-step chain, ExecutionContinuation 的 `pending_tool_queue` 永远空, AO classifier 看不到 "上一步规划好的 chain 还没跑完" 这个信号
- 用户必须每 turn 重新描述任务, 不能依赖系统自动推进 chain

修这件事不是单点修复 IntentResolver, 是把 chain projection 这个**架构组件**加进 v1.5 governance pipeline.

### 1.2 multi-step planning 需求来源

需求不是凭空加, 是修两件具体事:

- **mode_A root cause** (跳步执行): IntentResolver 不规划 chain → 跨 turn chain 推进无法发生
- **能力 1 (自动多步推进)**: 跟 Part 1 §1.7 ChatGPT 级别 multi-turn 流畅体验目标对齐

不是为了"让 LLM 更聪明", 是为了**让 framework 知道用户意图涉及哪些工具步骤**, framework 才能跨 turn 协调 chain 推进.

### 1.3 设计目标

| 目标 | IntentResolver 的具体职责 |
|---|---|
| LLM 主导 chain semantic | 用户意图需要哪些工具 / 工具顺序 / 工具间数据依赖语义 — 全部由 LLM prompt 输出 |
| Framework 强制 chain 字段写入 | LLM 输出 ChainPlan → IntentResolver 验证 → 写入 facade pending_chain — 强制单一写入路径 |
| Framework 强制 chain validity | 工具名合法 / chain 长度合法 / data_dependencies 合法 / 工具依赖图合法 — 全部 framework 检查, 不让 LLM 自评 |
| 提供 chain repair 最小可行实现 | 单步失败时 fallback 单步 chain, 让 framework 不被 LLM 错误卡死 |

### 1.4 不解决的问题 (留 v2)

明确 v1.5 IntentResolver 不做:

- 完全成熟的 chain repair 算法 (v1.5 是 minimal: 单步失败 → fallback 单步)
- chain 跨 AO 共享 (跨 AO chain 关系靠 AO classifier REVISION 而非 chain 自身链接)
- multi-LLM ensemble chain planning
- chain 性能优化 (合并相邻步骤 / cache 中间结果)
- chain branching / DAG (v1.5 只支持 sequential)
- chain 跨 session 持久化

详见 §11 Non-Goals.

### 1.5 跟 facade 的协同范围

facade frozen v2 已定义:
- `pending_chain` (List[ToolPlan]): IntentResolver 主要写入字段
- `chain_origin_turn`: IntentResolver 写入
- `last_chain_advance_reason`: IntentResolver / ExecutionContinuation 都写
- `chain_owner_ao_id`: derived
- `completed_steps`: ExecutionContinuation 写, IntentResolver 读 (re-plan 时)
- `revision_invalidated_steps`: IntentResolver 写 (REVISION 触发)

本文档 §4 定义 ToolPlan / ChainPlan dataclass, facade §4.2 + §5 routing table 引用. **不双重定义**.

---

## §2. Core Design Decisions

### 2.1 LLM 主导 chain semantic, framework 强制 chain validity 边界

这是 component #2 最核心的边界. 严格分工:

| 谁做 | 内容 |
|---|---|
| **LLM 决定** | (a) 用户意图需要哪些工具 (语义判断) |
| | (b) 工具的合理顺序 (语义判断) |
| | (c) 工具间数据依赖关系 (语义判断, 例如 dispersion 需要 emission 输出) |
| | (d) 每步的语义参数 (例如 pollutants=[NOx], 不做标准化) |
| | (e) 每步的用户可见 reasoning (向用户解释这一步为什么) |
| **Framework 决定** | (a) chain 是否合法 (依赖图 / 参数完整性 — 见 §6) |
| | (b) chain 写入哪里 (facade pending_chain, 单一路径) |
| | (c) chain 中间步失败时怎么办 (fallback 单步 — 见 §2.5) |
| | (d) chain 长度限制 (MAX_CHAIN_LENGTH 防御 LLM 输出过长) |
| | (e) chain 跟 AO classifier 状态协同 (REVISION → re-plan, NEW_AO → fresh plan) |

**不交给 LLM 的事**: chain validation 评分 / chain optimization / chain repair 决策 (除非 minimal fallback).

### 2.2 chain output schema 单一定义

ToolPlan / ChainPlan dataclass 在本文档 §4 单一定义. facade §4.2 + §5 routing table 引用本文档.

实施期 cc 验证: facade 的 pending_chain type hint 必须引用本文档定义的 ToolPlan, 不能在 facade 内重复定义.

### 2.3 chain planning vs chain repair 两条独立路径

| 路径 | 触发条件 | 接口 |
|---|---|---|
| **planning** (主路径) | NEW_AO / fresh chain / CONTINUATION 但 pending_chain 已空 | `plan_multi_step(context, facade) -> ChainPlan` |
| **revision re-plan** | AO classifier 输出 REVISION | `replan_after_revision(context, facade, invalidated_step_ids) -> ChainPlan` |
| **repair** | chain 中间步执行失败 | `repair_chain(context, facade, failed_step_id, failure_reason) -> ChainPlan` |

3 个接口共享 LLM prompt 主体, 不同 prompt context 注入 (见 §5).

### 2.4 chain validation 时机

LLM 输出 ChainPlan → 立即 validation (§6) → validation pass → 写入 facade. 顺序严格:

```
LLM call → ChainPlan (raw) → validation → ChainPlan (validated) → facade.set('pending_chain', ...)
```

不存在"先写 facade 后 validate" 的路径. 如果 validation 失败, ChainPlan 不写入 facade, 走 fallback 单步 chain (§2.5).

### 2.5 Chain Validation 失败行为 — Fallback 单步 Chain (拍板已完成)

**拍板**: chain validation 失败时, IntentResolver fallback 到 v1.0 单步规划路径, 同时 log warning. 不 fail-fast, 不 LLM re-prompt.

| 选项 | 含义 | 决议 |
|---|---|---|
| Fail-fast | validation 失败抛异常, 中止 turn | 不选 — 把 LLM 语义错误当 framework 错误, 不对. v1.0 单步行为可用就用 |
| LLM re-prompt | 让 LLM 重新输出 chain | 不选 — 实质是 LLM 算法工作, 跟 §3.2 选题定位冲突 |
| **Fallback 单步 + warning** | 退化到 v1.0 单步规划, log warning | **选** |

理由:
- fallback 是 framework 决策 (LLM 输出错就退化, 不让 LLM 重做), 最符合 framework deterministic + LLM semantic
- v1.0 单步规划逻辑已经 production-tested, 是稳定 fallback path
- warning 让我们能观测 LLM 输出 chain validation 失败率, Phase 9.3 ablation 量化
- 用户体验上单步比 fail 好, 不是 silent failure

实施细节 (§7.5 详述): v1.0 单步规划逻辑保留作为 fallback path, v1.5 multi-step planning 作为 primary path. 不是 v1.0 完全抛弃, 是行为扩展.

---

## §3. Anchors Compliance Checklist

设计前置约束. 任何 IntentResolver 设计变化必须先过这个 checklist.

### 3.1 跟核心论点 (framework deterministic + LLM semantic) 一致性

| Aspect | 跟核心论点关系 |
|---|---|
| LLM 主导 chain semantic (§2.1) | LLM 决定语义内容, 跟核心论点一致 ✓ |
| Framework 强制 chain validity (§6) | framework 决定合法性, 不让 LLM 自评 ✓ |
| chain output schema 单一定义 (§2.2) | framework 强制单一写入路径, deterministic ✓ |
| Validation 失败 fallback 单步 (§2.5) | framework 决定 fallback 行为, 不让 LLM 重做 ✓ |
| chain repair minimal 实现 (§7.3) | framework 决定 repair 路径, LLM 不参与 repair 决策 ✓ |

**Verdict**: IntentResolver 强化核心论点, 不改变它. 所有接口都符合 "framework deterministic enforcement of LLM-driven chain semantics".

### 3.2 跟选题定位 (架构 / 工程 / 系统贡献) 一致性 — 重点章节

(本节是 component #2 防御性 framing 的关键章节. 论文 §4 reviewer 第一反应可能是 "IntentResolver multi-step + LLM prompt design 看起来是 LLM 算法工作", 必须充分反驳.)

**反驳论点**: IntentResolver multi-step planning 看似 LLM 算法工作, 实际是**架构层贡献**.

**论证 1: chain projection 是新的架构组件**

v1.0 governance pipeline 只有单工具规划, 跨 turn chain 推进**没有架构组件支持**. v1.5 IntentResolver multi-step planning 引入:

- 新的接口 (`plan_multi_step` / `replan_after_revision` / `repair_chain`)
- 新的数据结构 (ChainPlan / ToolPlan, §4)
- 新的协调点 (跟 facade pending_chain 写入耦合, 跟 ExecutionContinuation 跨 turn 推进协同, 跟 AO classifier REVISION 触发协同)

这 3 个新增不是 LLM 算法, 是**架构 surface area** — 跨 contract 协调点, 跨 turn 状态承载.

**论证 2: chain validation 是 framework 工作**

§6 validation 5 条规则:
- 工具名在 ToolRegistry 列表内
- chain 长度 ≤ MAX_CHAIN_LENGTH
- data_dependencies 引用合法
- 工具依赖图前向校验 (component #9 协同)
- parameter 跟 ToolContract YAML 大类对齐

这 5 条全部是 framework 检查, **不是 LLM 评分**, 不是 LLM 自我评估. 验证逻辑是 deterministic Python 代码, 不调 LLM, 不做 ML scoring.

**论证 3: LLM 只被 prompt 出 chain plan, 不改 LLM 本身**

明确 v1.5 不做:

- LLM 模型选择 / 替换
- LLM fine-tune
- RL training (DPO / PPO / 任何强化学习)
- multi-LLM ensemble
- prompt 自动 search / 优化算法

LLM 模型固定为 deepseek-v4-pro, prompt 是**工程实现** (跟 ToolContract YAML 同步, §5.5), 不是 LLM 算法贡献.

**论证 4: 跟 v1.0 单工具 IntentResolver 接口对比**

v1.0:
- IntentResolver.before_turn → 推断单工具
- 输出: 单工具 + 参数
- 责任范围: 当前 turn 决策

v1.5 扩展:
- IntentResolver.plan_multi_step → 推断 ChainPlan (多工具)
- 输出: ChainPlan (跨 turn 持久, 通过 facade)
- 责任范围: 跨 turn chain 协调
- 接口扩展: replan_after_revision / repair_chain (新增 lifecycle 路径)

**接口 + 责任边界变化是架构变化**, 不是 LLM 算法变化. v1.0 → v1.5 IntentResolver 是**接口扩展 + 数据结构新增 + 跨组件协调点新增**.

**论证 5: 跟 §11 Non-Goals 闭环**

§11 显式列 v1.5 不做的 LLM 算法工作 (LLM 模型选择 / fine-tune / RL / ensemble / prompt 自动优化). 论文 §4 reviewer 看 §11 立刻知道 v1.5 边界. §11 跟本节 §3.2 锁死论点.

**Verdict**: IntentResolver multi-step planning 是架构贡献, 满足卖点 #3a (工具依赖图扩展为多步 chain planning) 跟核心论点 (framework deterministic + LLM semantic). 不是 LLM 算法工作.

### 3.3 跟 3 类失败模式分类一致性

| 失败模式 | IntentResolver 修复方式 |
|---|---|
| 多轮状态漂移 | 部分修 — chain projection 让 AO classifier 看到 "上一步规划好的 chain 还没跑完" 信号, 减少误分类 NEW_AO |
| **跳步执行** | 主修 — multi-step planning 是跳步执行的直接 fix |
| 参数组合非法 | 不直接修 — 这件事 component #5 + #9 处理. IntentResolver 只在 §6 规则 5 防御 "LLM 给出不存在的 parameter key" |

**Verdict**: IntentResolver 修复主要针对跳步执行, 不引入第 4 类失败模式.

### 3.4 跟 4 评估层次一致性

| 层次 | IntentResolver 影响 |
|---|---|
| Layer 1 标准化准确率 | 不影响 — IntentResolver 不做参数标准化 |
| Layer 2 端到端 | IntentResolver 是 v1.5 vs v1.0 delta 的核心来源之一 |
| Layer 3 Shanghai e2e | IntentResolver multi-step planning 修复 mode_A, Run 7 跑通 |
| Layer 4 用户研究 | 升级完成后启动, 不在 v1.5 设计范围 |

**Layer 2 IntentResolver 贡献验证**: Phase 9.3 ablation 设 IntentResolver-disabled run (具体 run 编号待 Phase 9.3 protocol 定, 跟 facade-disabled run 协同设计), 跟 governance_full 比较得出 IntentResolver 单独贡献.

**Verdict**: IntentResolver 直接影响 Layer 2 + Layer 3, 不影响 Layer 1 + Layer 4.

### 3.5 NaiveRouter 隔离 compliance

IntentResolver multi-step planning **只在 governed pipeline 内**:
- `plan_multi_step` / `replan_after_revision` / `repair_chain` 接口由 GovernedRouter 调用
- LLM prompt 模板 (Appendix B) 不被 NaiveRouter 使用
- ChainPlan / ToolPlan dataclass 不被 NaiveRouter 导入

NaiveRouter 仍是 vanilla function calling agent, 单步规划, 单工具调用循环 (max_iterations=4).

**实施期 cc 验证**: `grep -rn "plan_multi_step\|ChainPlan\|ToolPlan\|replan_after_revision\|repair_chain" core/naive_router.py` 必须 0 命中. 任一命中触发 STOP & report. 跟 §13.1 验证清单闭环.

**Verdict**: NaiveRouter 隔离守住, ablation delta 干净.

---

## §4. Chain Output Schema

本章定义 ToolPlan / ChainPlan dataclass 字段. 这是 component #2 跟 facade 协同的核心数据结构, **本章是单一定义**, facade §4.2 引用本章不重复.

### 4.1 ToolPlan dataclass

```python
@dataclass
class ToolPlan:
    tool_name: str
    parameters: Dict[str, Any]
    data_dependencies: List[str]
    optional: bool = False
    reasoning: str = ""
    plan_origin: PlanOrigin = PlanOrigin.FRESH_PLAN
```

字段说明:

| 字段 | Type | 业务语义 |
|---|---|---|
| `tool_name` | `str` | 工具名, 必须在 ToolRegistry 列表内 (§6 规则 1 验证) |
| `parameters` | `Dict[str, Any]` | LLM 输出的语义参数, **非标准化**. 标准化由 standardization_engine 在执行前做 |
| `data_dependencies` | `List[str]` | 此步依赖的前序步骤, 例如 `["needs_emission_result_from_step_1"]` 或 `["uses_completed_step_1"]`. 空列表表示无依赖 |
| `optional` | `bool` | 用户可选跳过 (default False). Reconciler 在 chain 推进时可询问用户是否跳过. 主要用于"扩展分析" 类可选步骤 |
| `reasoning` | `str` | LLM 输出的步骤理由, 用户可见. 例如 "为了分析污染热点, 在扩散结果上做 hotspot analysis" |
| `plan_origin` | `PlanOrigin` enum | `FRESH_PLAN` / `REVISION_REPLAN` / `REPAIR_REPLAN`. 用于 trace 区分 |

`PlanOrigin` enum:

```python
class PlanOrigin(Enum):
    FRESH_PLAN = "fresh_plan"
    REVISION_REPLAN = "revision_replan"
    REPAIR_REPLAN = "repair_replan"
```

### 4.2 ChainPlan dataclass

```python
@dataclass
class ChainPlan:
    chain_id: UUID
    chain_owner_ao_id: AO_id
    planned_at_turn: int
    total_steps: int
    chain_strategy: ChainStrategy = ChainStrategy.SEQUENTIAL
    tool_plans: List[ToolPlan] = field(default_factory=list)
```

字段说明:

| 字段 | Type | 业务语义 |
|---|---|---|
| `chain_id` | `UUID` | 唯一 chain 标识符. 用于 trace 跟 facade 关联 |
| `chain_owner_ao_id` | `AO_id` | chain 归属的 AO. 跟 facade `chain_owner_ao_id` 一致 |
| `planned_at_turn` | `int` | chain 第一次写入的 turn 号. 跟 facade `chain_origin_turn` 一致 |
| `total_steps` | `int` | chain 长度. 必须 ≤ MAX_CHAIN_LENGTH (§6 规则 2) |
| `chain_strategy` | `ChainStrategy` enum | `SEQUENTIAL` / `PARALLEL_ELIGIBLE`. **v1.5 只支持 SEQUENTIAL**, parallel 留 v2 |
| `tool_plans` | `List[ToolPlan]` | chain 步骤序列, 顺序执行 |

`ChainStrategy` enum:

```python
class ChainStrategy(Enum):
    SEQUENTIAL = "sequential"
    PARALLEL_ELIGIBLE = "parallel_eligible"  # v1.5 not implemented
```

### 4.3 跟 facade pending_chain 字段映射

facade frozen v2 §4.2 定义:

```
pending_chain: List[ToolPlan]
```

(facade routing table §5 注: "facade.set 写两处 — `ao.metadata["execution_continuation"]["pending_tool_queue"]` + `ao.execution_state.planned_chain` (mirror)".)

IntentResolver 主要 hand-off 接口:

```python
chain_plan = intent_resolver.plan_multi_step(context, facade)
facade.set("pending_chain", chain_plan.tool_plans)
facade.set("chain_origin_turn", chain_plan.planned_at_turn)
facade.set("last_chain_advance_reason", "multi_step_initial_plan")
```

ChainPlan 容器 (chain_id / chain_strategy 等元信息) **不**直接写 facade, 写入 trace event (§10) + 实施期可能存到 `ao.metadata["chain_plan_metadata"]` (留 §12 Open Q5 决定).

### 4.4 序列化 / 反序列化规范

ChainPlan / ToolPlan 必须支持 JSON 序列化 (跟 ao.metadata 持久化兼容):

- `dataclasses.asdict(chain_plan)` 转 dict
- enum 字段转 str (PlanOrigin / ChainStrategy `.value`)
- UUID 字段转 str

反序列化:
- 从 ao.metadata 加载 ChainPlan 用 `ChainPlan(**data)` 配合 enum 字段重建

实施期不引入 Pydantic / msgpack, 用 Python 标准库 json.

---

## §5. LLM Prompt Design

本章是 component #2 第二个核心新内容. v1.5 引入 multi-step chain planning 必须有具体 prompt 模板, 不能只说"让 LLM 输出 chain". prompt 设计是工程实现, 不是 LLM 算法.

### 5.1 Prompt 总体结构

```
[System Prompt - 英文]
  - 角色定位: chain planner
  - 输出格式 JSON schema
  - 单步 vs 多步选择规则
  - 数据依赖表达规则

[Few-Shot Examples - 中文]
  - 5+1 个示例 (Appendix B)

[Current Context - 中文]
  - current_objective (从 facade)
  - last_user_intent (从 facade)
  - completed_steps summarized (从 facade)
  - last_referenced_params (从 facade)
  - recent_tool_results_index summarized (从 facade)

[User Message]
  - 当前 turn 用户输入

[Output Instruction - 英文]
  - "Respond with JSON ChainPlan only. No markdown wrapping."
```

System prompt 跟 output instruction 用英文 (DeepSeek-v4-pro 长 instruction 英文更稳, 当前 LLM 工程最佳实践). few-shot examples + context + user message 中文为主 (用户 input 中文, LLM reasoning 中文, 跟领域术语一致). JSON 字段名英文规范, 字段值中英混合按用户实际.

### 5.2 System Prompt 模板

完整模板见 Appendix B.1. 核心元素:

- **角色定位**: "You are a chain planner for a traffic emission analysis system. Your job is to decompose user intent into a sequence of tool calls (a 'chain'). You decide which tools to call, in what order, and what semantic parameters to use."
- **输出格式约束**: JSON schema 跟 §4 ToolPlan / ChainPlan 严格对齐. 不用 markdown 包装. 不输出额外解释.
- **单步 vs 多步选择规则**:
  - 用户意图明确单一工作 → 单步 chain (例如纯查询排放因子)
  - 用户意图涉及顺序工具组合 → 多步 chain (例如计算排放 + 扩散模拟)
  - 用户意图涉及可选扩展分析 → 多步 chain 含 `optional=True` 步骤
- **数据依赖表达规则**:
  - 当前 chain 内步骤间依赖: `"needs_<artifact>_from_step_<N>"` (例如 `needs_emission_result_from_step_1`)
  - 跨 turn 依赖 (用 completed_steps 已有结果): `"uses_completed_step_<N>"`
  - 无依赖: 空列表

### 5.3 Few-Shot Examples

5+1 个示例 (Appendix B.2 - B.6):

| # | 场景 | 重点 |
|---|---|---|
| B.2 NEW_AO 单步 | 纯查询排放因子 | 单步 chain, 无 data_dependencies |
| B.3 NEW_AO 多步 (mode_A 修复目标) | 计算排放 + 扩散模拟 | 2 步 chain, step 2 依赖 step 1 输出 |
| B.4 CONTINUATION (隐式上下文) | 复用 last_referenced_params | 演示 context 注入怎么用 |
| B.5 REVISION (重规划) | 用户改主意 | 演示 invalidated_steps 注入 |
| B.6 (新增, Q5 拍板) Validation 失败 fallback | LLM 输出非法 chain | 演示 fallback 单步行为, system 怎么处理 |
| B.7 Chain repair (中间步失败) | step_2 fail, repair 单步 | 演示 minimal repair |

3-5 个 examples 的工程权衡: 太少 LLM 不学到模式, 太多 prompt token 爆炸. 5+1 是合理点.

### 5.4 Context 注入 (从 facade 读 + 注入 prompt)

每次 LLM call, IntentResolver 从 facade 读以下字段并注入 prompt:

| facade 字段 | 注入形式 |
|---|---|
| `current_objective` | "Current AO: <ao_id>" 或 "(no active objective, this is a new task)" |
| `last_user_intent` | "Previous user message: <text>" (如果存在) |
| `completed_steps` | summarized list — 每 step 一行 "(step_N) tool_name: brief_outcome", 不注入完整 result |
| `last_referenced_params` | dict 直接注入 (典型 < 200 字符) |
| `recent_tool_results_index` | key list — `["emission", "dispersion"]`, 不注入完整 result |
| `revision_invalidated_steps` (REVISION 时) | invalidated step ids list |

完整 result 不注入 prompt (避免 token 膨胀). LLM 通过 step 名跟 data_dependencies 引用, framework 在执行时从 SessionContextStore 取实际 result.

### 5.5 Prompt 工程纪律

5 条纪律:

**纪律 1**: 不在 prompt 内嵌入工具实现细节. 工具语义 (输入 / 输出 / 限制) 来自 ToolContract YAML, prompt 内只引用工具名 + 简短描述. 避免 prompt 跟 tool registry drift.

**纪律 2**: 不在 prompt 内做参数标准化. LLM 输出的 `parameters` 是**语义参数** (`vehicle: 乘用车` / `season: 夏季`), 标准化由 standardization_engine 在执行前做.

**纪律 3 (拍板已完成)**: prompt 跟 ToolContract YAML 通过**运行时 inject** 同步 — LLM call 前从 ToolRegistry 读当前工具列表 + 参数 schema, inject 到 system prompt 的 `{{tool_registry_section}}` placeholder. 不用代码生成 (build process 复杂, 引入新 build step), 不用模板引擎 (引入 Jinja2 等新依赖).

理由 (跟 Part 1 §1.6 架构决策跟工程决策分离一致):
- 架构方向 (运行时 inject) 设计期定, 避免实施期 cc 反复 deliberate 三个选项
- 简单 — 不需要额外 build step 跟 toolchain 改动
- 跟现有 LLMClient pipeline 一致 — DeepSeek 调用本来就是运行时构造 messages
- 单一逻辑源 — ToolRegistry 是唯一 source, prompt 跑前从单一源读

具体 inject 实现细节 (f-string / 自定义 template / 别的) 实施期决定, 见 §12 Q2.

**纪律 4**: prompt 长度预算控制 (§5.6). prompt 模板 + few-shot + context 不能超过 LLM context window 1/3 (留 2/3 给 LLM 推理 + 输出).

**纪律 5**: prompt 修订纳入 git. 每次 prompt 改动单独 commit, message 标 `prompt: <change>`, 让 cc 跟用户都能 trace prompt 演化.

### 5.6 Prompt 长度预算

DeepSeek-v4-pro context window 32k tokens. v1.5 IntentResolver prompt 预算:

| 段落 | 估算 tokens |
|---|---|
| System prompt | ~800 |
| Few-shot (6 examples × 平均 200 token) | ~1200 |
| Current context (注入 facade 字段) | ~500 |
| User message | ~200 |
| Output instruction | ~100 |
| **小计** | **~2800 tokens** |

留给 LLM reasoning + output: ~29k tokens, 充足. 实际 chain output 极少超过 500 tokens.

实施期监控 prompt 实际 token 数 (component #12 llm_telemetry 记录), 超过 4000 tokens 触发 prompt slim audit.

---

## §6. Chain Validation Rules

本章是 component #2 第三个核心新内容. validation 是 framework 工作, 不是 LLM 评分.

### 6.1 Validation 触发时机

LLM 输出 ChainPlan (raw) → 立即 validation → validation pass → 写入 facade. 顺序严格:

```python
chain_plan_raw = llm_call(prompt)
chain_plan_parsed = parse_json(chain_plan_raw)  # JSON 解析失败也是 validation 失败
validation_result = validate_chain(chain_plan_parsed, context, facade)
if validation_result.passed:
    facade.set("pending_chain", chain_plan_parsed.tool_plans)
else:
    log.warning(f"Chain validation failed: {validation_result.reasons}")
    fallback_to_single_step_plan(context, facade)  # §2.5 fallback
```

不存在"先写 facade 后 validate" 路径.

### 6.2 Validation 5 条规则

**规则 1**: 工具名在 ToolRegistry 列表内

每个 ToolPlan.tool_name 必须能在 `tools.registry.ToolRegistry.list()` 找到. LLM 给出不存在的工具名 (例如 `calculate_co2_emission` 而非 `calculate_macro_emission`) 直接 reject.

**规则 2**: chain 长度 ≤ MAX_CHAIN_LENGTH

`MAX_CHAIN_LENGTH` 默认 5 (实施期可调, 见 §12 Open Q4). 防御 LLM 输出过长 chain (例如 hallucinate 出 10 步分析). 100-task benchmark 实际最长 chain ≤ 4 步, 5 是安全边界.

**规则 3**: data_dependencies 引用合法

每个 ToolPlan.data_dependencies 中:
- `"needs_<artifact>_from_step_<N>"` 中 N 必须 ≤ 当前 ToolPlan 在 chain 中的位置
- `"uses_completed_step_<N>"` 中 N 必须存在于 facade.completed_steps 中

引用未来 step 或不存在 completed_step 直接 reject.

**规则 4**: 工具依赖图前向校验 (component #9 协同)

每个 ToolPlan 调用 component #9 DependencyContract 前向校验:
- 工具 prerequisites 是否在 chain 内前序步骤 / completed_steps / SessionContextStore 中可满足
- 不可满足 → 此 ToolPlan reject

具体调用接口见 component #9 文档.

**规则 5**: parameter 跟 ToolContract YAML 大类对齐

每个 ToolPlan.parameters 的 key 必须出现在该工具的 ToolContract YAML inputs 列表内. 防御 LLM 给出工具不接受的 parameter key (例如对 `query_emission_factors` 给 `dispersion_grid` 参数).

不做完整参数标准化 (那是 standardization_engine 工作), 只做大类对齐.

### 6.3 Validation 失败行为

按 §2.5 拍板, **fallback 到 v1.0 单步规划路径 + log warning**.

具体实施:

```python
def fallback_to_single_step_plan(context, facade) -> None:
    log.warning(
        "IntentResolver multi-step validation failed. "
        f"Reasons: {validation_result.reasons}. "
        "Falling back to v1.0 single-step planning."
    )
    # 调用 v1.0 IntentResolver.before_turn (保留作 fallback path)
    single_tool_plan = legacy_intent_resolver.before_turn(context)
    if single_tool_plan:
        chain_plan = ChainPlan(
            chain_id=uuid4(),
            chain_owner_ao_id=facade.get("current_objective"),
            planned_at_turn=context.turn_no,
            total_steps=1,
            chain_strategy=ChainStrategy.SEQUENTIAL,
            tool_plans=[ToolPlan(
                tool_name=single_tool_plan.tool_name,
                parameters=single_tool_plan.parameters,
                data_dependencies=[],
                plan_origin=PlanOrigin.FRESH_PLAN,
                reasoning="(fallback) v1.0 single-step plan due to multi-step validation failure"
            )]
        )
        facade.set("pending_chain", chain_plan.tool_plans)
        facade.set("last_chain_advance_reason", "multi_step_validation_fallback")
```

trace 记录 `intent_resolution_validation_failed` step (§10).

### 6.4 Validation 跟 component #9 DependencyContract 协同

**拍板 (设计期, 不留实施期)**: IntentResolver chain validation 规则 4 **调用 component #9 DependencyContract.validate_chain(), 不重新实现依赖图检查**.

理由 (跟 Part 1 §1.6 架构决策跟工程决策分离一致):
- **单一逻辑源**: 工具依赖图检查的 source of truth 是 DependencyContract. IntentResolver 复制依赖图逻辑会导致两份代码 drift, 实施期 / 维护期都是 bug 来源
- **v1.5 latency 不是 hard constraint**: chain planning 本来就是 LLM call (~2-3 秒), 加 dependency check (~10ms 量级) 时间相对极小
- **同 process 调用成本低**: DependencyContract 跟 IntentResolver 在同一 GovernedRouter 实例内, 调用是普通 Python 方法调用
- **Anchors §3.2 一致**: framework 强制 chain validity, 单一组件做依赖检查跟"framework 强制"语义一致

数据流 (不模糊带过):

```
LLM 输出 ChainPlan (raw)
  ↓
IntentResolver 内部检查: 规则 1 (工具名) + 规则 2 (chain 长度) + 规则 3 (data_dependencies)
  ↓
IntentResolver 调用 DependencyContract.validate_chain(chain_plan, completed_steps, facade) → ValidationResult
  ↓ (规则 4 委托给 DependencyContract)
IntentResolver 内部检查: 规则 5 (parameter key 跟 ToolContract YAML 大类对齐)
  ↓
全部规则 PASS → 写入 facade.pending_chain
任一规则 FAIL → fallback 单步 (§6.3) + log warning
```

**接口签名** (IntentResolver 调用方视角):

```python
from core.contracts.dependency_contract import DependencyContract

dep_result: DependencyValidationResult = self.dependency_contract.validate_chain(
    chain_plan=chain_plan_raw,
    completed_steps=facade.get("completed_steps") or [],
    facade=facade,
)

if not dep_result.passed:
    log.warning(f"Chain validation rule 4 failed (DependencyContract): {dep_result.reasons}")
    return self._fallback_to_single_step_plan(context, facade)
```

DependencyContract.validate_chain 的内部实现 (是 hard block / soft record / skip 哪种行为) 由 component #10 拍板, IntentResolver 不关心内部细节, 只读 ValidationResult.passed.

**实施期 cc 验证**: IntentResolver 实现里 `grep -rn "validate_tool_prerequisites\|tool_dependency_graph" core/contracts/intent_resolver*.py` 必须 0 命中 — 这些是 DependencyContract 内部实现细节, 不应该出现在 IntentResolver 代码里. 跟 §13.1 验证清单闭环.

### 6.5 Validation 跟 cross-parameter constraint 协同

不在本章范围. cross-parameter constraint 在 component #5 (Standardizer fallback + Clarification) 边界. IntentResolver 只在规则 5 做 parameter key 大类对齐, 不做 cross-parameter constraint 检查.

---

## §7. Operation Semantics

### 7.1 主接口 — `plan_multi_step`

```python
def plan_multi_step(
    self,
    context: ContractContext,
    facade: ConversationStateFacade,
) -> ChainPlan:
    """主路径 — NEW_AO / fresh chain / CONTINUATION 但 pending_chain 已空 时调用.

    1. 从 facade 读 context (§5.4)
    2. 构造 prompt (§5.1-5.5)
    3. LLM call
    4. parse + validate (§6)
    5. validation pass → 返回 ChainPlan; fail → fallback 单步 (§6.3)
    """
```

调用时机: GovernedRouter 主流程在 OASCContract.before_turn 之后, ExecutionReadinessContract.before_turn 之前.

### 7.2 REVISION re-plan 接口 — `replan_after_revision`

```python
def replan_after_revision(
    self,
    context: ContractContext,
    facade: ConversationStateFacade,
    invalidated_step_ids: List[step_id],
) -> ChainPlan:
    """AO classifier 输出 REVISION 时调用.

    1. invalidated_step_ids 注入 prompt (告诉 LLM 这些 step 被废弃)
    2. 已成功未 invalidate 的 completed_steps 是否复用 — 见 §12 Open Q5
    3. 其他逻辑跟 plan_multi_step 一致
    4. 返回 ChainPlan, plan_origin = REVISION_REPLAN
    """
```

调用时机: AO classifier 在 OASCContract.before_turn 内输出 REVISION → IntentResolver 触发 replan_after_revision.

### 7.3 Chain repair 接口 — `repair_chain`

```python
def repair_chain(
    self,
    context: ContractContext,
    facade: ConversationStateFacade,
    failed_step_id: step_id,
    failure_reason: str,
) -> ChainPlan:
    """chain 中间步执行失败时调用.

    v1.5 minimal 实现:
    1. 把 failed_step 之前的 completed_steps 保留
    2. 重新 plan 失败步及之后 (LLM 看到 failure_reason 决定怎么改)
    3. 如果 LLM 仍输出非法 chain, fallback 单步 plan (§6.3)
    4. 返回 ChainPlan, plan_origin = REPAIR_REPLAN

    完整 chain repair 算法 (智能跳过 / 替换工具 / 重试参数等) 留 v2.
    """
```

调用时机: ExecutionContinuation 检测到 chain 中间步失败时调用 (具体 hand-off 见 component #4 文档).

### 7.4 错误处理

| 错误情况 | IntentResolver 行为 |
|---|---|
| LLM API timeout | 抛 IntentResolverLLMError, GovernedRouter 主流程处理 (typically retry 1 次后 fail turn) |
| LLM output 不可解析 (非合法 JSON) | validation 失败, fallback 单步 (§6.3) + log warning |
| validation 失败 (§6 规则任一) | fallback 单步 + log warning |
| facade write 失败 | 透传 FacadeWriteError 给 caller (跟 facade §6.4 一致) |
| context 缺关键字段 (例如 user message 空) | 抛 IntentResolverContextError, 不调 LLM |

### 7.5 跟现有 `intent_resolution_contract.py` 的关系 — 扩展, 不替换

(本节是 §2.5 fallback 单步路径的具体实施基础, 拍板已完成: **扩展, 不替换**.)

**v1.0 单步规划 = fallback path, v1.5 multi-step planning = primary path**.

实施细节:

- v1.0 `intent_resolution_contract.py` 的 `before_turn` 接口保留, 不删除
- v1.5 `IntentResolverMultiStep` 新类, 跟 v1.0 `IntentResolutionContract` 共存
- GovernedRouter 主流程默认调 IntentResolverMultiStep.plan_multi_step
- multi-step validation 失败时 fallback 调 IntentResolutionContract.before_turn (v1.0 单步)
- 不删 v1.0 代码, 实施风险显著降低

注意: v1.0 单步规划逻辑 production-tested, 是稳定 fallback. 完全替换风险高 (跟 5 个 contract 协同破坏), 扩展 incremental 风险小.

---

## §8. Hand-off Contracts

本章描述 IntentResolver 跟其他 component 的具体接口. **只接口 + 触发时机 + 字段读写 list, 不描述其他 component 内部实现** (那在各 component 文档).

### §8.1 跟 facade (component #1) — 写 pending_chain

| 项 | 内容 |
|---|---|
| 读 facade 字段 | `current_objective`, `last_user_intent`, `completed_steps`, `last_referenced_params`, `recent_tool_results_index`, `revision_invalidated_steps` |
| 写 facade 字段 | `pending_chain`, `chain_origin_turn`, `last_chain_advance_reason` |
| 触发时机 | plan_multi_step / replan_after_revision / repair_chain 任一接口 |
| 接口签名 | `facade.set("pending_chain", chain_plan.tool_plans)` 等 |
| 关键决策 | facade 写入是 fail-fast (按 facade §2.4), validation 失败时不写 facade |

### §8.2 跟 AO classifier (component #3) — 读 AO classification

| 项 | 内容 |
|---|---|
| 读 AO classifier 字段 | classification 结果 (NEW_AO / CONTINUATION / REVISION) |
| 写 AO classifier 字段 | 无 |
| 触发时机 | AO classifier 在 OASCContract.before_turn 内分类后, IntentResolver 根据分类决定调哪个接口 |
| 协同逻辑 | NEW_AO → plan_multi_step; CONTINUATION 且 pending_chain 空 → plan_multi_step; CONTINUATION 且 pending_chain 非空 → 不 re-plan; REVISION → replan_after_revision |
| 关键决策 | AO classifier 3 状态 + AOStatus 6 lifecycle 双轴, IntentResolver 只读 classifier 结果决定路径 |

### §8.3 跟 ExecutionContinuation (component #4) — pending_chain 写入后 ExecutionContinuation 推进

| 项 | 内容 |
|---|---|
| 读 facade 字段 | (跟本文档无关, ExecutionContinuation 自己读 pending_chain 推进) |
| 写 facade 字段 | (ExecutionContinuation 写 pending_chain 头部 pop / completed_steps append) |
| 触发时机 | IntentResolver 写完 pending_chain → ExecutionReadinessContract 检查 readiness → ExecutionContinuation 推进 |
| 协同逻辑 | IntentResolver 不直接调用 ExecutionContinuation, 通过 facade pending_chain 数据流间接协同 |
| 关键决策 | chain 中间步失败 → ExecutionContinuation 调用 IntentResolver.repair_chain (§7.3) |

### §8.4 跟 DependencyContract (component #9) — chain validation 期间调用

| 项 | 内容 |
|---|---|
| 读 DependencyContract 输出 | validation 结果 (passed / reasons / blocked_step_ids) |
| 写 DependencyContract 输入 | tool_plan + chain_so_far + facade |
| 触发时机 | §6.2 规则 4 验证时调用 |
| 接口签名 | `dependency_contract.validate_chain_step(tool_plan, chain_so_far, facade) -> DependencyValidationResult` |
| 关键决策 | DependencyContract 决定 block / record / skip, IntentResolver 只读结果 |

### §8.5 跟 Reconciler (component #5) — chain repair 时协同

| 项 | 内容 |
|---|---|
| 读 Reconciler 输出 | reconciler 是否决定继续 chain repair 还是中止 turn |
| 写 Reconciler 输入 | repair_chain 调用前提 + chain 状态 |
| 触发时机 | repair_chain 调用前 reconciler 决策, repair_chain 输出后 reconciler 再次决策 (是否接受 repair plan) |
| 关键决策 | reconciler 在 repair 路径上是 gating, 不让 IntentResolver 单独决定 repair 是否进行 |

---

## §9. Lifecycle & Persistence

### 9.1 IntentResolver 实例化

**Per-session class instance** (跟 facade §11 Q1 一致):

```python
class GovernedRouter:
    def __init__(self, session_id, ...):
        self.intent_resolver = IntentResolverMultiStep(
            llm_client=self.llm_client,
            tool_registry=self.tool_registry,
            tool_contract_loader=self.tool_contract_loader,
            facade=self.facade,
        )
```

不引入静态全局 module-level functions.

### 9.2 chain plan 持久化

ChainPlan 通过 facade.pending_chain 写入持久化, IntentResolver 自己**不持久化**. 跨 turn 状态完全从 facade + 底层 store 读出.

### 9.3 LLM call 缓存

**v1.5 不缓存**. 每次 plan_multi_step / replan_after_revision / repair_chain 都 LLM call.

理由: chain plan 应该响应 facade state 变化. facade state 跨 turn 变化, 同 prompt 的 chain plan 可能不一样. 缓存导致 stale chain plan, 跟 mode_A 相反方向修复.

实施期可监控 LLM call 次数 (component #12 llm_telemetry), 如果发现热点重复调用再考虑短期缓存. 默认不缓存.

### 9.4 进程重启后的 IntentResolver 重建

进程重启 → GovernedRouter 重新实例化 → IntentResolver 重新构造 → 从 facade 读 pending_chain (跨 turn 持久化的) → 不重新 plan, 直接继续推进.

只有 pending_chain 空且当前 turn 需要 plan 时才 LLM call.

---

## §10. Trace Observability

### 10.1 IntentResolver 触发新 trace step types

新加到 `core/trace.py` `TraceStepType` enum:

```python
TraceStepType.INTENT_RESOLUTION_MULTI_STEP_PLAN = "intent_resolution_multi_step_plan"
TraceStepType.INTENT_RESOLUTION_REVISION_REPLAN = "intent_resolution_revision_replan"
TraceStepType.INTENT_RESOLUTION_CHAIN_REPAIR = "intent_resolution_chain_repair"
TraceStepType.INTENT_RESOLUTION_VALIDATION_FAILED = "intent_resolution_validation_failed"
```

替代 v1.0 单步 `intent_resolution` step type? **不**. v1.0 step type 保留, v1.5 新 step types 跟 v1.0 共存. fallback 单步路径走 v1.0 step type.

### 10.2 Trace event 字段

每个新 step type 的字段:

```json
{
  "type": "intent_resolution_multi_step_plan",
  "chain_id": "uuid-xxx",
  "chain_owner_ao_id": "AO#1",
  "total_steps": 2,
  "chain_strategy": "sequential",
  "plan_origin": "fresh_plan",
  "tool_chain_summary": ["calculate_macro_emission", "calculate_dispersion"],
  "validation_result": {
    "passed": true,
    "rules_checked": [1, 2, 3, 4, 5]
  },
  "wall_time_ms": 2300,
  "llm_call_count": 1
}
```

不 dump 完整 ChainPlan (避免 trace 膨胀), dump summary.

`intent_resolution_validation_failed` step type 额外字段:

```json
{
  "type": "intent_resolution_validation_failed",
  "raw_chain_summary": [...],
  "validation_failures": [
    {"rule_id": 4, "reason": "tool calculate_dispersion missing prerequisite"}
  ],
  "fallback_action": "single_step_plan"
}
```

### 10.3 跟 component #12 llm_telemetry 协同

LLM call telemetry (cache / tokens / wall_time / model) 走 component #12 llm_telemetry trace key, **不**重复在 IntentResolver trace event. IntentResolver trace 只记 chain semantic 跟 validation 结果.

### 10.4 跟 facade `conversation_state_update` trace 的关系

顺序:
- IntentResolver 输出 ChainPlan → 触发 `intent_resolution_multi_step_plan` trace
- 然后 facade.set("pending_chain", ...) → 触发 `conversation_state_update` trace

两个 trace event 在时间上紧邻, 但分开记录. IntentResolver trace 描述 "为什么这个 chain", facade trace 描述 "facade 哪些字段被改".

---

## §11. Non-Goals

明确不做 (7 个):

1. **LLM 算法工作**: v1.5 IntentResolver 不做 LLM 模型选择 / prompt fine-tune / RL training / multi-LLM ensemble / prompt 自动 search / 优化算法. 当前 LLM 是 deepseek-v4-pro, prompt 设计是工程实现 (跟 ToolContract YAML 同步), 不是 LLM 算法贡献. **跟 §3.2 防御性 framing 直接闭环.**
2. **chain 跨 AO 共享** — 跨 AO chain 关系靠 AO classifier REVISION 而非 chain 自身链接
3. **chain branching / DAG** — v1.5 只支持 sequential chain
4. **chain optimization** — 例如合并相邻步骤 / cache 中间结果
5. **完整 chain repair 算法** — v1.5 minimal: 单步失败 → fallback 单步 plan; complete repair 留 v2
6. **chain 跨 session 持久化**
7. **chain 跨 process 协调** — v1.5 假设单 session 串行 (跟 facade §6.5 一致)

---

## §12. Open Questions

5 个 open question 留实施期 (Phase 9.1.1+) 决定. 不阻塞 schema frozen.

### Open Q1: chain validation 失败时 fallback 单步 chain 还是 LLM re-prompt

跟 §2.5 + §6.3 拍板呼应. 当前拍板 fallback 单步 chain. 实施期可能反转 — 例如发现 LLM 输出 chain validation 失败率高 (>10%) 时, 可能加 1 次 LLM re-prompt (限定 1 次, 避免无限循环).

倾向: **fallback 单步 chain** (按 §2.5 拍板).

### Open Q2: 运行时 inject 的具体实现细节

**架构方向已设计期拍板** (§5.5 纪律 3): prompt 跟 ToolContract YAML 通过运行时 inject 同步, 不用代码生成 / 模板引擎.

实施期 open: 运行时 inject 的具体实现选项:
- f-string format
- 自定义 lightweight template (例如 `{{tool_registry_section}}` placeholder + `str.replace`)
- 现有 LLMClient pipeline 已有的 templating 能力 (如有)

倾向: **自定义 lightweight template** (`str.replace` 处理 placeholder). 简单, 无新依赖. 实施期最终拍板, 取决于现有 LLMClient pipeline 模式. 偏离运行时 inject 方向须 STOP & report.

### Open Q3: chain repair 的最小可行实现范围

§7.3 minimal repair: 失败 step 之前保留 + 重新 plan 失败步及之后. v1.5 应该到什么程度:
- (i) 真正调 LLM 重新 plan (当前设计)
- (ii) 直接 fallback 单步 (相当于 v1.0 行为)
- (iii) 退回到 turn 开始, 重新 plan_multi_step

倾向: **(i) 真正调 LLM 重新 plan**, 因为 v1.5 引入 IntentResolver 就是为了让 framework 利用 LLM chain semantic, repair 是合理 use case.

### Open Q4: MAX_CHAIN_LENGTH 默认值

§6.2 规则 2 当前默认 5. 需要看 100-task benchmark 实际 chain 长度分布:
- 如果实际 chain 几乎都 ≤ 3 步, MAX_CHAIN_LENGTH=3 更严格 (防御 LLM hallucinate 长 chain)
- 如果实际 chain 偶尔到 4 步, MAX_CHAIN_LENGTH=5 安全
- 如果偶尔到 6 步, MAX_CHAIN_LENGTH=7

倾向: **5**. 实施期 Phase 9.1.1 跑前 audit 100-task benchmark chain 长度分布最终拍板.

### Open Q5: REVISION re-plan 时是否复用未 invalidate 的 completed_steps

§7.2 替换 invalidated_steps 后:
- (a) 完全重新 plan, 不复用 completed_steps
- (b) 保留所有 completed_steps, 只 plan invalidated_steps + 之后

倾向: **(b) 保留 completed_steps**. 避免重做已成功的工具 (用户体验更好, 资源节省). 但需要 LLM prompt 显式告诉 "已 completed_steps 不要重新规划".

---

## §13. Validation Hooks for Codex

schema frozen 后, 第一个 cc 任务按本章验证.

### 13.1 cc 验证任务清单

按顺序跑, 任一失败立即 STOP & report:

1. **NaiveRouter 隔离验证**
   ```bash
   grep -rn "plan_multi_step\|ChainPlan\|ToolPlan\|replan_after_revision\|repair_chain\|IntentResolverMultiStep" core/naive_router.py
   ```
   必须 0 命中.

2. **现有 `intent_resolution_contract.py` 接口跟 §7.5 假设是否匹配**
   - file: `core/contracts/intent_resolution_contract.py`
   - 验证: `before_turn(context)` 接口存在 + 返回单工具规划 (而非 None)
   - 不匹配 → STOP, 报告接口已 drift, §7.5 fallback 路径需要修订

3. **现有 ToolRegistry / ToolContract YAML 跟 §6.2 规则 5 兼容**
   - 验证: `tools.registry.ToolRegistry.list()` 返回工具列表
   - 验证: 每个工具 ToolContract YAML 含 `inputs` section
   - 不兼容 → STOP

4. **`ChainPlan` / `ToolPlan` dataclass 不跟现有代码 namespace 冲突**
   ```bash
   grep -rn "class ChainPlan\|class ToolPlan" core/
   ```
   必须 0 命中. 任一命中 → STOP

5. **新 trace step types 不跟现有 `TraceStepType` enum 冲突**
   - 验证: `intent_resolution_multi_step_plan` / `intent_resolution_revision_replan` / `intent_resolution_chain_repair` / `intent_resolution_validation_failed` 不在 `core/trace.py` 现有 enum 内
   - 任一存在 → STOP

6. **IntentResolver 不复制依赖图逻辑 (跟 §6.4 拍板闭环)**
   ```bash
   grep -rn "validate_tool_prerequisites\|tool_dependency_graph\|build_dependency_graph" core/contracts/intent_resolver*.py
   ```
   必须 0 命中. 任一命中表示 IntentResolver 复制了 DependencyContract 内部逻辑, 违反单一逻辑源原则 → STOP.

### 13.2 STOP & report 触发条件

- NaiveRouter 隔离 grep 命中
- 现有 IntentResolutionContract 接口跟 §7.5 假设不可调和
- ToolRegistry / ToolContract YAML 结构跟 §6.2 假设根本不一致
- ChainPlan / ToolPlan 命名冲突
- Trace step type 命名冲突
- IntentResolver 复制依赖图逻辑 (跟 §6.4 拍板冲突)
- LLM prompt 模板 token 预算 (§5.6) 实际超过 4000 tokens → 重新评估 prompt slim

任一 STOP → 不继续验证, 直接报告 user, 等用户拍板修订.

6 项验证全 pass → component #2 准备进 Phase 9.1.1 实施.

---

## Appendix A: Worked Examples

5 个完整场景, A.1 详细 turn-by-turn (跟 facade Appendix A.1 互补, 重点 IntentResolver 视角), A.2 - A.5 简洁.

### A.1 mode_A 完整修复 — Run 7 三 turn turn-by-turn (DETAILED, IntentResolver 视角)

(facade Appendix A.1 已经写完整 facade state, 本附录 IntentResolver 视角补充 LLM prompt 跟 chain output 细节.)

**Turn 1** 用户输入: "用 macro_direct.csv 算上海 3 路段排放, 计算 CO2 和 NOx, 夏季"

```
context (从 facade 读):
  current_objective: None (新 session)
  last_user_intent: None
  completed_steps: []
  last_referenced_params: {}
  recent_tool_results_index: {}

AO classifier 输出: NEW_AO (no current_objective)

IntentResolver.plan_multi_step(context, facade):
  prompt context (注入):
    "Current AO: (no active objective, this is a new task)"
    "User message: 用 macro_direct.csv 算上海 3 路段排放, 计算 CO2 和 NOx, 夏季"
    "File available: macro_direct.csv (already grounded)"
  
  LLM call (deepseek-v4-pro):
    output JSON:
    {
      "chain_id": "...",
      "total_steps": 2,
      "chain_strategy": "sequential",
      "tool_plans": [
        {
          "tool_name": "calculate_macro_emission",
          "parameters": {
            "vehicle": "乘用车",
            "pollutants": ["CO2", "NOx"],
            "season": "夏季",
            "road_segments_file": "macro_direct.csv"
          },
          "data_dependencies": [],
          "optional": false,
          "reasoning": "计算 3 路段在夏季的 CO2 跟 NOx 排放",
          "plan_origin": "fresh_plan"
        },
        {
          "tool_name": "calculate_dispersion",
          "parameters": {
            "pollutant": "NOx",
            "season": "夏季"
          },
          "data_dependencies": ["needs_emission_result_from_step_1"],
          "optional": false,
          "reasoning": "扩散模拟基于 step 1 排放结果 (NOx 是 dispersion 主要关注污染物)",
          "plan_origin": "fresh_plan"
        }
      ]
    }
  
  validation:
    规则 1: calculate_macro_emission ∈ ToolRegistry ✓; calculate_dispersion ∈ ToolRegistry ✓
    规则 2: total_steps=2 ≤ MAX_CHAIN_LENGTH=5 ✓
    规则 3: data_dependencies "needs_emission_result_from_step_1" 引用 step 1 (chain 内合法) ✓
    规则 4: DependencyContract.validate_chain_step:
      - step 1 calculate_macro_emission prerequisites: file 已 grounded ✓
      - step 2 calculate_dispersion prerequisites: emission_result (在 chain step 1) ✓ — chain 内可满足
    规则 5: parameters keys 跟 ToolContract YAML inputs 对齐 ✓
    validation_result: passed
  
  facade write:
    facade.set("pending_chain", [step_1, step_2])
    facade.set("chain_origin_turn", 1)
    facade.set("last_chain_advance_reason", "multi_step_initial_plan")
  
  trace event:
    intent_resolution_multi_step_plan (chain_id=..., total_steps=2, plan_origin=fresh_plan, validation passed)

ExecutionContinuation 推进:
  pending_chain[0] = calculate_macro_emission → execute → success
  facade.append_to("completed_steps", step_1_result)
  facade.set("pending_chain", [step_2])  # pop 头部

Response: "已计算: CO2 318.90 kg/h, NOx 67.40 g/h. 接下来准备进行扩散模拟."
```

**Turn 2** 用户输入: "对刚才的排放结果做扩散模拟"

```
context (从 facade 读):
  current_objective: AO#1 (still active)
  pending_chain: [step_2 calculate_dispersion]
  completed_steps: [step_1: emission(CO2:318.90, NOx:67.40)]
  last_referenced_params: {pollutants: [CO2, NOx], season: summer, ...}
  recent_tool_results_index: {emission: ref_macro_xxx}

AO classifier 输出: CONTINUATION (current_objective 存在 + pending_chain 非空 + 用户消息跟 pending head 语义一致)

IntentResolver:
  pending_chain 非空, 不 re-plan, 直接用现有 step_2
  (CONTINUATION 路径不调 plan_multi_step)
  
  trace event: 无 (没新 chain plan 产生)

ExecutionContinuation 推进:
  pending_chain[0] = calculate_dispersion → execute → success
  facade.append_to("completed_steps", step_2_result)
  facade.set("pending_chain", [])  # chain 完成

Response: "扩散模拟完成. NOx 在 ... 区域..."
```

**Turn 3** 假设用户输入: "再分析一下污染热点"

```
context:
  current_objective: None (AO#1 completed)
  completed_steps: [step_1, step_2]
  last_referenced_params: {pollutants: [CO2, NOx], season: summer, ...}
  recent_tool_results_index: {emission: ..., dispersion: ...}

AO classifier 输出: NEW_AO (current_objective 空)

IntentResolver.plan_multi_step:
  prompt context 注入:
    "Current AO: (no active objective, new task)"
    "Recent completed steps: step_1 emission, step_2 dispersion"
    "Recent tool results available: emission, dispersion"
    "User message: 再分析一下污染热点"
  
  LLM 利用 recent_tool_results_index 知道 dispersion 已有, 规划:
    chain = [analyze_hotspots(input=dispersion_result)]
    1 步 chain, data_dependencies=["uses_completed_step_2"]
  
  validation pass
  facade write
  执行
```

关键修复点 (跟 v1.0 对比):
- v1.0: AO classifier Turn 2 把 "对刚才的..." 5/5 分为 NEW_AO (因为 IntentResolver 不规划 chain, AO classifier 看不到 chain context)
- v1.5: AO classifier Turn 2 看到 facade.pending_chain 非空, 分为 CONTINUATION
- v1.5: Turn 3 跨 AO 仍能复用 recent_tool_results_index, IntentResolver 知道 dispersion 已有

### A.2 REVISION re-plan — 简短

```
Turn 1: 用户算 CO2 排放 → AO#1, completed_steps=[macro_emission(CO2)]
Turn 2: 用户说 "啊我说错了, 应该算 NOx 不是 CO2"

AO classifier → REVISION
IntentResolver.replan_after_revision(invalidated_step_ids=[step_1]):
  prompt context 注入:
    "REVISION: 用户改主意, 以下 step 被废弃:"
    "  step_1: calculate_macro_emission(CO2)"
    "Replan based on new user intent."
  
  LLM 输出:
    chain = [calculate_macro_emission(NOx)]
    plan_origin = revision_replan
  
  validation pass
  facade.set("revision_invalidated_steps", [step_1])
  facade.set("pending_chain", [new_step_1])
  
  trace event: intent_resolution_revision_replan
```

(Q5 拍板倾向: 保留未 invalidate 的 completed_steps, 本例只有 1 个 step 被 invalidate 所以全部 invalidate.)

### A.3 Chain repair (中间步失败) — 简短

```
Turn 1: chain = [calculate_macro_emission, calculate_dispersion, analyze_hotspots]
        step_1 success, step_2 (dispersion) FAILED with "missing meteorology data"

ExecutionContinuation 检测到 step_2 失败, 调 IntentResolver.repair_chain(failed_step_id=step_2, failure_reason="missing meteorology data"):
  prompt context:
    "Chain repair: step_2 (calculate_dispersion) failed with reason: missing meteorology data"
    "Completed: step_1 calculate_macro_emission (success)"
    "Failed: step_2 calculate_dispersion"
    "Pending: step_3 analyze_hotspots"
    "Replan from step_2 onwards."
  
  LLM 输出 (尝试给 step_2 加 meteorology fallback):
    chain = [calculate_dispersion(use_default_meteorology=true), analyze_hotspots]
    plan_origin = repair_replan
  
  validation:
    规则 5: parameters key "use_default_meteorology" 不在 ToolContract YAML inputs 内 → reject
  
  fallback 单步 (§6.3):
    log warning "repair validation failed, fallback to single-step"
    单步 plan = [analyze_hotspots(use_completed_step_1)]  # 跳过 dispersion, 用 emission 直接 hotspot
    facade.set("pending_chain", [single_step])
  
  trace event:
    intent_resolution_chain_repair (validation_failed=true)
    intent_resolution_validation_failed
```

### A.4 跨 turn chain 推进 + 隐式上下文 — 简短

```
Turn 1: 用户 "算乘用车夏季排放" → emission(乘用车, 夏季) success
        facade.last_referenced_params = {vehicle: 乘用车, season: summer, ...}

Turn 2: 用户 "再算一次, 改成冬季"

AO classifier → 取决于具体语义, 假设 NEW_AO (新 task)
IntentResolver.plan_multi_step:
  prompt context 注入:
    "Recent params (last referenced): {vehicle: 乘用车, season: 夏季, pollutants: [CO2, NOx]}"
    "User message: 再算一次, 改成冬季"
  
  LLM 输出 (复用 vehicle/pollutants, 改 season):
    chain = [calculate_macro_emission(乘用车, 冬季, pollutants=[CO2, NOx])]
    1 步 chain
    reasoning: "用户保持 vehicle 跟 pollutants, 只改 season 为冬季"
  
  validation pass
  facade write + 执行
```

### A.5 Validation 失败 fallback 单步 (Q5 拍板补充) — 简短

```
Turn 1: 用户 "算排放"  (模糊 input)

AO classifier → NEW_AO

IntentResolver.plan_multi_step:
  LLM 输出 (hallucinate 长 chain):
    chain = [
      calculate_macro_emission,
      calculate_dispersion,  
      analyze_hotspots,
      render_spatial_map,
      compare_scenarios,
      query_knowledge,  # 6 步, 超 MAX_CHAIN_LENGTH=5
    ]
  
  validation:
    规则 2: total_steps=6 > MAX_CHAIN_LENGTH=5 → reject
  
  fallback 单步 (§6.3):
    调 v1.0 IntentResolutionContract.before_turn(context):
      v1.0 单步规划 → calculate_macro_emission (推断默认参数)
    facade.set("pending_chain", [single_step])
    facade.set("last_chain_advance_reason", "multi_step_validation_fallback")
  
  trace event:
    intent_resolution_validation_failed (rule_id=2, reason="chain too long")
    intent_resolution_multi_step_plan (跳过, 走了 fallback path)
  
  log.warning("IntentResolver multi-step validation failed: chain too long. Falling back to v1.0 single-step.")
```

实施期监控这种 warning 频率, 如果 >5% turn 出现说明 prompt 没引导好 LLM, 需要调整 prompt few-shot.

---

## Appendix B: Prompt Template Examples

完整可拷贝示例. 实施期 cc 直接用本附录作为 prompt 实施起点.

### B.1 System Prompt Template (英文)

```
You are a chain planner for a traffic emission analysis system. Your job is to decompose user intent into a sequence of tool calls — a "chain" — that achieves the user's goal.

## Available Tools

{{tool_registry_section}}  
(Auto-injected from ToolContract YAML. Each tool has: name, brief_description, inputs, outputs.)

## Output Format

Respond with a JSON ChainPlan only. No markdown wrapping. No additional explanation outside the JSON.

```json
{
  "chain_id": "<uuid>",
  "total_steps": <int>,
  "chain_strategy": "sequential",
  "tool_plans": [
    {
      "tool_name": "<tool_name from Available Tools>",
      "parameters": {<semantic params, not standardized>},
      "data_dependencies": ["needs_<artifact>_from_step_<N>" or "uses_completed_step_<N>" or omit if none],
      "optional": false,
      "reasoning": "<user-visible Chinese explanation>",
      "plan_origin": "fresh_plan" | "revision_replan" | "repair_replan"
    }
  ]
}
```

## Single-step vs Multi-step Decision Rules

- User intent is a single task → single-step chain (e.g. "查询乘用车 NOx 排放因子")
- User intent involves a sequence of related tools → multi-step chain (e.g. "计算排放并模拟扩散")
- User intent has optional extension → multi-step with `optional=true` for extension steps

## Data Dependency Expression Rules

- Within current chain: "needs_<artifact>_from_step_<N>" (e.g. "needs_emission_result_from_step_1")
- Across turns (using `completed_steps`): "uses_completed_step_<N>"
- No dependencies: omit `data_dependencies` or empty list

## Constraints (Hard)

- Tool names MUST come from Available Tools. Do not invent tools.
- Maximum chain length: 5 steps.
- Parameters use semantic Chinese values (e.g. `"vehicle": "乘用车"`), not standardized codes.

Respond ONLY with the JSON ChainPlan.
```

### B.2 NEW_AO 单步示例

```
[Current Context]
Current AO: (no active objective, new task)
User message: 查询一下乘用车在夏季的 NOx 排放因子

[Expected LLM output]
{
  "chain_id": "uuid-1",
  "total_steps": 1,
  "chain_strategy": "sequential",
  "tool_plans": [
    {
      "tool_name": "query_emission_factors",
      "parameters": {
        "vehicle": "乘用车",
        "pollutant": "NOx",
        "season": "夏季"
      },
      "data_dependencies": [],
      "optional": false,
      "reasoning": "查询乘用车在夏季的 NOx 排放因子",
      "plan_origin": "fresh_plan"
    }
  ]
}
```

### B.3 NEW_AO 多步 (mode_A 修复目标)

```
[Current Context]
Current AO: (no active objective, new task)
User message: 用 macro_direct.csv 算上海 3 路段排放, 计算 CO2 和 NOx, 夏季
File available: macro_direct.csv (already grounded)

[Expected LLM output]
{
  "chain_id": "uuid-2",
  "total_steps": 2,
  "chain_strategy": "sequential",
  "tool_plans": [
    {
      "tool_name": "calculate_macro_emission",
      "parameters": {
        "vehicle": "乘用车",
        "pollutants": ["CO2", "NOx"],
        "season": "夏季",
        "road_segments_file": "macro_direct.csv"
      },
      "data_dependencies": [],
      "optional": false,
      "reasoning": "计算 3 路段在夏季的 CO2 跟 NOx 排放",
      "plan_origin": "fresh_plan"
    },
    {
      "tool_name": "calculate_dispersion",
      "parameters": {
        "pollutant": "NOx",
        "season": "夏季"
      },
      "data_dependencies": ["needs_emission_result_from_step_1"],
      "optional": false,
      "reasoning": "扩散模拟基于 step 1 排放结果, NOx 是 dispersion 主要关注污染物",
      "plan_origin": "fresh_plan"
    }
  ]
}
```

### B.4 CONTINUATION (隐式上下文)

```
[Current Context]
Current AO: AO#1 (active)
Recent params (last referenced): {vehicle: 乘用车, season: 夏季, pollutants: [CO2, NOx]}
Recent completed steps: step_1 calculate_macro_emission (CO2: 318.90, NOx: 67.40)
Pending chain: (empty, AO#1 might be ready to extend)
User message: 再算一次, 改成冬季

[Expected LLM output]
{
  "chain_id": "uuid-3",
  "total_steps": 1,
  "chain_strategy": "sequential",
  "tool_plans": [
    {
      "tool_name": "calculate_macro_emission",
      "parameters": {
        "vehicle": "乘用车",
        "pollutants": ["CO2", "NOx"],
        "season": "冬季"
      },
      "data_dependencies": [],
      "optional": false,
      "reasoning": "用户保持 vehicle 跟 pollutants, 只改 season 为冬季, 重新计算排放",
      "plan_origin": "fresh_plan"
    }
  ]
}
```

### B.5 REVISION 重规划

```
[Current Context]
Current AO: AO#2 (REVISION of AO#1)
REVISION: 用户改主意, 以下 step 被废弃:
  step_1 (in AO#1): calculate_macro_emission(pollutants=[CO2])
User message: 啊我说错了, 应该算 NOx 不是 CO2

[Expected LLM output]
{
  "chain_id": "uuid-4",
  "total_steps": 1,
  "chain_strategy": "sequential",
  "tool_plans": [
    {
      "tool_name": "calculate_macro_emission",
      "parameters": {
        "vehicle": "乘用车",
        "pollutants": ["NOx"],
        "season": "夏季"
      },
      "data_dependencies": [],
      "optional": false,
      "reasoning": "用户更正污染物为 NOx, 重新计算排放",
      "plan_origin": "revision_replan"
    }
  ]
}
```

### B.6 Validation 失败 fallback 单步 (Q5 拍板)

```
[Current Context]
Current AO: (no active objective)
User message: 算排放 (模糊 input)

[LLM Hypothetical Output - validation FAILS]
{
  "chain_id": "uuid-5",
  "total_steps": 6,  // 超过 MAX_CHAIN_LENGTH=5
  "chain_strategy": "sequential",
  "tool_plans": [
    {"tool_name": "calculate_macro_emission", ...},
    {"tool_name": "calculate_dispersion", ...},
    {"tool_name": "analyze_hotspots", ...},
    {"tool_name": "render_spatial_map", ...},
    {"tool_name": "compare_scenarios", ...},
    {"tool_name": "query_knowledge", ...}
  ]
}

[Validation Failure]
Rule 2 violated: total_steps=6 > MAX_CHAIN_LENGTH=5

[Fallback Action]
- log.warning("IntentResolver multi-step validation failed: chain too long. Falling back to v1.0 single-step.")
- 调 v1.0 IntentResolutionContract.before_turn(context) → 推断单工具 calculate_macro_emission 默认参数
- facade.set("pending_chain", [single_step])
- trace event: intent_resolution_validation_failed (rule_id=2, fallback_action="single_step_plan")

[User-visible Behavior]
系统继续执行 calculate_macro_emission (默认参数), 不让 turn fail.
```

### B.7 Chain repair (中间步失败)

```
[Current Context]
Chain repair: step_2 (calculate_dispersion) failed with reason: "missing meteorology data"
Completed: step_1 calculate_macro_emission (success)
Failed: step_2 calculate_dispersion
Pending: step_3 analyze_hotspots

User message: (no new user input — automatic repair)

[Expected LLM output]
{
  "chain_id": "uuid-6",
  "total_steps": 1,  // 跳过 dispersion, 直接用 emission 做 hotspot
  "chain_strategy": "sequential",
  "tool_plans": [
    {
      "tool_name": "analyze_hotspots",
      "parameters": {
        "input_source": "emission_result"  // 用 step_1 emission 替代 dispersion 作 hotspot 输入
      },
      "data_dependencies": ["uses_completed_step_1"],
      "optional": false,
      "reasoning": "由于 step_2 dispersion 缺少气象数据失败, 退而用 step_1 emission 直接做 hotspot 分析",
      "plan_origin": "repair_replan"
    }
  ]
}
```

(注: 真实 LLM 输出未必 ideal, 可能仍尝试调 dispersion 加默认气象, validation 可能仍失败 → 走 fallback 单步. 本例展示 ideal repair 行为.)

---

## Appendix C: Glossary

| 术语 | 含义 |
|---|---|
| ChainPlan | LLM 输出的多步 chain 完整数据结构, 含 chain_id / total_steps / tool_plans (§4.2) |
| ToolPlan | chain 内单步规划数据结构, 含 tool_name / parameters / data_dependencies (§4.1) |
| chain projection | IntentResolver 把用户意图投射成 chain 的过程 (LLM call → ChainPlan) |
| chain validation | framework 检查 ChainPlan 合法性 (§6) |
| chain repair | chain 中间步失败时重新规划 (§7.3) |
| MAX_CHAIN_LENGTH | chain 长度上限, 默认 5 (§6.2 规则 2) |
| fallback 单步 | validation 失败时退化到 v1.0 单步规划路径 (§2.5, §6.3) |
| plan_origin | ToolPlan 来源标识 (FRESH_PLAN / REVISION_REPLAN / REPAIR_REPLAN, §4.1) |
| chain_strategy | chain 执行策略 (SEQUENTIAL / PARALLEL_ELIGIBLE), v1.5 只支持 SEQUENTIAL (§4.2) |
| primary path / fallback path | v1.5 multi-step planning = primary, v1.0 single-step planning = fallback (§7.5) |

---

## Appendix D: Related Audit References + Component Cross-Reference

### D.1 Audit references

| Audit | 报告 | 本文档对应章节 |
|---|---|---|
| Phase 9.1.0 codebase audit Task 7 | `docs/architecture/phase9_1_0_codebase_audit.md` | §1.1 (现有 IntentResolver 单步规划) |
| Run 7 trace recheck | `docs/architecture/phase9_1_0_run7_trace_recheck.md` | §1.1 (mode_A 5/5, projected_chain absent) |
| Run 7 variance | `docs/architecture/phase9_1_0_run7_variance.md` | §1.1 (15/15 turn-trial chain absent) |
| Step 2 reproducibility | `docs/architecture/phase9_1_0_step2_reproducibility.md` | §6.2 规则 2 MAX_CHAIN_LENGTH 100-task benchmark 参考 |
| 阶段 1b pre-audit | `docs/architecture/phase9_1_0_step3c_1b_pre_audit.md` | §6.4 DependencyContract 协同 (component #9 空壳 → v1.5 实施化) |

### D.2 Component cross-reference

| 引用方 | 引用本文档章节 |
|---|---|
| facade frozen v2 §4.2 | §4 ToolPlan / ChainPlan dataclass 单一定义 |
| facade frozen v2 §7.2 | §8.1 facade hand-off 接口 |
| Component #3 (AO classifier 双轴语义) | §8.2 AO classifier hand-off |
| Component #4 (ExecutionContinuation) | §8.3 chain 推进 hand-off |
| Component #5 (Clarification + Reconciler) | §8.5 chain repair gating |
| Component #9 (DependencyContract 实施化) | §6.4 + §8.4 chain validation 协同 |
| Part 1 §1.7 能力 1 | §1.2 multi-step planning 需求来源 |
| Part 1 §1.3.2 选题定位 | §3.2 防御性 framing |
| Part 1 §1.10 Phase 9.3 数据可信度前置 | §10.3 component #12 llm_telemetry 协同 |

---

**End of v1.5 IntentResolver Multi-Step Planning Component #2 Design document — frozen v2**

**Frozen 状态**: 2026-05-06 kirito approved. 后续 component 文档引用本文档不可推翻. 仅 §12 open question 实施期解决时回头更新对应章节.

下一步: 进 Component #3 (AO classifier 双轴语义) 文档.
