# EmissionAgent Phase 2 开发升级计划

**文档性质**：Phase 2 工程实现的完整开发计划
**目标读者**：Kirito（项目所有者）+ Codex（执行侧）
**制定日期**：2026-04-23
**依据**：Round 1-2 论文讨论结论 + `docs/codebase_audit_phase2_prep.md`（commit `90905c3`）

---

## 0. 开发计划总纲

### 0.1 本文档的范围与边界

**本文档覆盖**：

- ✅ Phase 2 的六个 Task Pack 的完整开发方案（Migration / YAML 合并 / 约束违反 writer / data quality 管道 / reply parser LLMification / 硬编码解耦）
- ✅ 每个 Task Pack 的子任务拆分、交付物定义、验收标准、风险点
- ✅ 每个 Task Pack 对应的 Codex prompt 草稿（用于你按工作流派发）
- ✅ Task Pack 之间的依赖关系与执行顺序
- ✅ Phase 2 完成后到论文投稿期间的延续工作预览

**本文档不覆盖**：

- ❌ 论文写作任务（Chapter 1-7 写作将在 Phase 2 完成后单独规划）
- ❌ User study 准备工作（protocol 设计、问卷、招募、伦理审批等，Phase 2 完成后单独规划）
- ❌ Phase 3 及以后的方向（skill-style prompt injection / multi-agent / cross-domain replication 等，属于论文 Future Work，不属于本 Phase 2）
- ❌ 对现有 Phase 1.6 / Wave 2-5 成果的进一步优化（本计划只做"架构定型"所需工作）

### 0.2 对齐的目标状态

**Phase 2 的定义**：做完这份计划里的所有工作之后，EmissionAgent 达到"**论文投稿版本的 agent 定型**"状态。具体是：

- **架构层**：生产路径和 benchmark 路径统一，都走 GovernedRouter；Chapter 4 描述的三类机制（Grounding / Governance / Interaction）在代码里真实生效
- **能力层**：Case A/B/C/D 与端到端 Case（Chapter 5）在生产路径下可复现；benchmark 数据在统一路径下可信
- **扩展层**：加新工具只需改 YAML + 新工具文件 + `tools/registry.py` 一行 register（Task Pack E 的验收标准）
- **一致性层**：前端用户体验到的 agent 行为 ≡ benchmark 跑出来的 agent 行为

**Phase 2 不是什么**：

- Phase 2 ≠ 生产级产品的 agent（SLA 级别的稳定性属于 user study 前的加固期工作）
- Phase 2 ≠ feature 完备（某些 LLM 提示词细调、UI 打磨留给论文写作期）
- Phase 2 ≠ benchmark 数字最优（benchmark 会跑，但论文用的最终数据将在 Phase 2 完成 + 一轮 prompt 打磨之后重跑）

### 0.3 六个 Task Pack 总览

Phase 2 含六个 Task Pack，按推荐执行顺序列出：

| 编号 | 名称 | 工作性质 | 关键产出 | 依赖 |
|---|---|---|---|---|
| **F-bugfix** | `restore_persisted_state` 硬编码修复 | Bug fix | 跨进程 restart 不丢 split contract | 无 |
| **F-main** | Migration · 统一生产路径到 GovernedRouter | 架构迁移 | `full` mode 在 API/CLI 都走 GovernedRouter | F-bugfix |
| **E-8.1** | 双 YAML 合并 | 配置层重构 | `tool_contracts.yaml` 成为唯一 tool 声明源 | F-main |
| **B** | 约束违反 writer pipeline | 能力补完 | `constraint_violations_seen` 有生产侧 writer，AO block 承载约束历史 | F-main |
| **C+D** | Data Quality Pipeline（合并） | 能力扩展 + 新增工具 | `analyze_file` 扩维度 + `clean_dataframe` 新工具 | E-8.1（避免双份 YAML 返工） |
| **A** | Reply parser LLMification | 能力升级 | `parameter_negotiation` / `input_completion` 主解析走 LLM，regex 降级为 fast path | B（为 LLM 解析器提供约束上下文） |
| **E-剩余** | `_snapshot_to_tool_args` 等硬编码解耦 | 代码重构 | 新增工具不再改 `governed_router.py` switch | E-8.1、C+D |

### 0.4 Critical Path

```
F-bugfix → F-main → E-8.1 → B → C+D → A → E-剩余
```

**三条强依赖链**：

1. **F-main 是 B/A/C+D 能在生产路径生效的前提**（A 路径下 AO 为空，Task Pack B 写了也不注入 prompt）
2. **E-8.1 是 C+D 避免双份 YAML 返工的前提**（D 新增工具要同时写 `tool_contracts.yaml` + `unified_mappings.yaml`）
3. **B 是 A 的上下文来源**（LLM reply parser 看到约束历史才能做 informed parsing）

**可并行点**：E-剩余（`_snapshot_to_tool_args` / `ao_manager` keywords / NaiveRouter 白名单）不阻塞任何其他 Pack，可以在 C+D / A 进行时穿插完成。

### 0.5 工作流约定

继续沿用此前的协作模式：

1. **Claude 设计**：每个 Task Pack 内部给出子任务清单、验收标准、关键决策点、Codex prompt 草稿
2. **用户派发**：Kirito 将 Codex prompt 发给 Codex 执行
3. **Codex 执行**：按 prompt 要求完成代码改动，产出 commit + 执行报告
4. **Claude 复盘**：Kirito 把 Codex 的执行报告发回 Claude，Claude 审阅 + 决定下一步

每个 Task Pack 独立一个 git 分支，合入 main 前 Claude review。不估算时间，只按任务分点推进。

### 0.6 命名与引用约定

- **Task Pack 编号**：F（Migration）、F-bugfix（前置修复）、E（Extensibility）、A（Reply）、B（Constraint Writer）、C+D（Data Quality）
- **子任务编号**：F.1 / F.2 / ... 或 B.1 / B.2 / ... 依此类推
- **引用审计文档**：本文中"§7.F.2" 指审计文档 `codebase_audit_phase2_prep.md` 的对应 section
- **file:line 引用**：直接写 `core/governed_router.py:538-556`

---

## 1. Task Pack F-bugfix · `restore_persisted_state` 硬编码修复

### 1.1 背景与动机

**审计发现**（§7.F.1）：`core/governed_router.py:538-556` 的 `restore_persisted_state` 方法硬编码重建 `self.contracts = [oasc, clarification, dependency]`，**忽略 `enable_contract_split` 配置**。

**症状**：

- 当 session 在 `enable_contract_split=true` 环境下创建并保存（含 `IntentResolution` / `StanceResolution` / `ExecutionReadiness` 三分裂 contract）
- 跨进程 restart（API 重启、容器重建）后 restore 时 contract 链收缩回 `[oasc, clarification, dependency]`
- AO 元数据中的 `metadata["execution_readiness"]`、`metadata["execution_continuation"]` 等 split-only 字段在磁盘上仍在，但运行时**不再有对应 contract 去读写它们**

**对 Phase 2 的影响**：

- 这个 bug 必须在 Task Pack F-main 之前修，否则 Migration 后任何 split contract 能力都会在 restart 后丢失
- Bug 修复独立于 Migration 本身，单独一个 PR，降低 Migration PR 的复杂度

### 1.2 子任务拆分

#### F-bugfix.1 修复 `restore_persisted_state` 的 contract 列表重建逻辑

**目标**：`restore_persisted_state` 的 contract 重建逻辑与 `__init__` 完全一致，含 `enable_contract_split` 分支判断。

**改动**：

`core/governed_router.py:538-556` 当前逻辑：

```python
def restore_persisted_state(self, payload):
    self.inner_router.restore_persisted_state(payload)
    self.ao_manager = AOManager(self.inner_router.memory.fact_memory)
    self.stance_resolver = StanceResolver(...)
    self.oasc_contract = OASCContract(...)
    self.clarification_contract = ClarificationContract(...)
    self.contracts = [self.oasc_contract, self.clarification_contract, self.dependency_contract]
    # ⚠️ 硬编码 3-contract 列表，忽略 enable_contract_split
```

重构后：

```python
def restore_persisted_state(self, payload):
    self.inner_router.restore_persisted_state(payload)
    self.ao_manager = AOManager(self.inner_router.memory.fact_memory)
    self.stance_resolver = StanceResolver(...)
    self.oasc_contract = OASCContract(...)
    self._build_contracts()  # 抽取 __init__ 里的 contract 装配逻辑到此方法
```

**`_build_contracts` 方法**（新增或从 `__init__` 抽取）：

```python
def _build_contracts(self):
    """Single source of truth for contract list assembly.
    Used by both __init__ and restore_persisted_state.
    """
    contracts = [self.oasc_contract]

    if self.config.enable_contract_split:
        if self.config.enable_split_intent_contract:
            self.intent_contract = IntentResolutionContract(...)
            contracts.append(self.intent_contract)
        if self.config.enable_split_stance_contract:
            self.stance_contract = StanceResolutionContract(...)
            contracts.append(self.stance_contract)
        if self.config.enable_split_readiness_contract:
            self.readiness_contract = ExecutionReadinessContract(...)
            contracts.append(self.readiness_contract)
    else:
        self.clarification_contract = ClarificationContract(...)
        contracts.append(self.clarification_contract)

    contracts.append(self.dependency_contract)
    self.contracts = contracts
```

#### F-bugfix.2 回归测试

**目标**：确保 bug 修复不破坏现有行为。

**改动**：

- 新增 `tests/test_governed_router_restore_persisted_state.py`
- 测试用例：
  1. `enable_contract_split=false`：save → restore，contract 列表长度 = 3，顺序 = `[oasc, clarification, dependency]`
  2. `enable_contract_split=true` + 三 split contract 全开：save → restore，contract 列表长度 = 5，顺序 = `[oasc, intent, stance, readiness, dependency]`
  3. `enable_contract_split=true` + 只开 intent：save → restore，contract 列表长度 = 3，顺序 = `[oasc, intent, dependency]`
  4. 跨配置重启场景：contract_split=true 下创建 session，改成 `enable_contract_split=false` 后 restore——应该按**当前**配置重建（不追求恢复到保存时的配置）

### 1.3 验收标准

- ✅ `_build_contracts` 方法被 `__init__` 和 `restore_persisted_state` 共用，无重复逻辑
- ✅ 四个测试用例全部通过
- ✅ 原 `governed_router` 相关 test 无 regression（本地跑 `tests/test_governed_router*.py`）
- ✅ commit message: `fix(governed_router): restore_persisted_state respects enable_contract_split`

### 1.4 风险点

1. **`__init__` 里的 contract 装配逻辑可能复杂**：如果 `__init__` 混合了 contract 装配与其他初始化逻辑（memory 绑定、stance_resolver 注入等），抽取时需要小心只移动 contract 部分
2. **测试依赖 session persistence**：测试要实际 save + restore，可能需要 fixture 模拟文件系统

### 1.5 Codex Prompt 草稿

````markdown
# 任务：修复 GovernedRouter.restore_persisted_state 的 contract 列表硬编码 bug

## 背景

`core/governed_router.py:538-556` 的 `restore_persisted_state` 方法硬编码重建 contract 列表为 `[oasc, clarification, dependency]`，忽略 `enable_contract_split` 配置。这导致跨进程 restart 后，split contract（IntentResolution / StanceResolution / ExecutionReadiness）被丢失，即使保存时是开启的。

## 目标

让 `restore_persisted_state` 的 contract 装配逻辑与 `__init__` 完全一致，支持 `enable_contract_split` 的所有情况。

## 具体改动

### 改动 1：在 `GovernedRouter` 类中新增 `_build_contracts` 方法

抽取 `__init__` 当前的 contract 装配逻辑到这个方法。装配逻辑应覆盖：

- 始终包含 `oasc_contract`（首位）
- 始终包含 `dependency_contract`（末位）
- 当 `enable_contract_split=false`：中间放 `clarification_contract`
- 当 `enable_contract_split=true`：中间按 flag 依次放 `intent_contract` / `stance_contract` / `readiness_contract`（三个子 flag 独立控制是否加入）

### 改动 2：重构 `__init__`

让 `__init__` 在创建完 `self.oasc_contract` / `self.dependency_contract` 等对象后调用 `self._build_contracts()` 装配 `self.contracts`。

### 改动 3：重构 `restore_persisted_state`

删除硬编码的 `self.contracts = [...]` 列表，改为：

```python
self.inner_router.restore_persisted_state(payload)
self.ao_manager = AOManager(self.inner_router.memory.fact_memory)
self.stance_resolver = StanceResolver(...)
self.oasc_contract = OASCContract(...)
self._build_contracts()  # 复用同一套装配逻辑
```

### 改动 4：新增回归测试

新建 `tests/test_governed_router_restore_persisted_state.py`，包含以下测试用例：

1. `enable_contract_split=false` 默认场景：contract 列表 = `[oasc, clarification, dependency]`
2. `enable_contract_split=true` + 三 split flag 全开：contract 列表 = `[oasc, intent, stance, readiness, dependency]`
3. `enable_contract_split=true` + 只开 `enable_split_intent_contract`：contract 列表 = `[oasc, intent, dependency]`
4. 跨配置重启：保存时 `enable_contract_split=true`，restore 时配置改为 `enable_contract_split=false`——应按 restore 时的当前配置重建

## 验收标准

- `_build_contracts` 方法被两处共用，无重复逻辑
- 4 个新测试用例全部通过
- 原有 `tests/test_governed_router*.py` 无 regression
- commit message: `fix(governed_router): restore_persisted_state respects enable_contract_split`

## 约束

- 只动 `core/governed_router.py` 和 `tests/test_governed_router_restore_persisted_state.py`
- 不动 contract 子类、不动 memory、不动 session
- 单独 PR，不混入其他 Task Pack 的改动

## 首轮回复

动手前请 ACK 并列出你看到的 `__init__` 中 contract 装配逻辑的具体位置（file:line），并说明是否需要在抽取时带走相邻的哪些初始化代码。等我确认后开始。
````

---


## 2. Task Pack F-main · Migration 统一生产路径到 GovernedRouter

### 2.1 背景与动机

**审计关键发现**（§7.F、Finding 0.2）：

- API 默认 `router_mode="full"` 走 **UnifiedRouter**，benchmark 路径 `router_mode="router"+ENABLE_GOVERNED_ROUTER=true` 走 **GovernedRouter**
- UnifiedRouter 路径下 **AO 系统完全不运行**（`grep "AOManager\|ao_manager" core/router.py` 返回 0 命中）
- A 路径下 assembler 渲染的 AO block 因 `fact_memory.ao_history` 为空而是**空架子**

**影响**：前端用户看到的 agent 能力 ≠ benchmark 测出来的能力。Phase 1.6 的 +6.11pp 成果只在 benchmark 路径可见。论文 Chapter 5 的 case study 在生产路径无法复现。

**Migration 的本质**：让 `full` mode 在 API 和 CLI 中都走 GovernedRouter，让前端用户真正体验到 AO / 约束反馈 / LLM-first clarification 等能力。

### 2.2 设计决策

#### 2.2.1 Mode 枚举如何演化

审计文档 §7.F.2 提到两种方案：

- **方案 a**：保留三值枚举（`full` / `naive` / `governed_v2`），但 `full` 内部走 GovernedRouter，`governed_v2` 作为别名保留
- **方案 b**：简化为二值枚举（`agent` / `naive`），需 API 兼容层

**本计划采用方案 a**。理由：

1. 对前端、对 API 消费者零 breaking change
2. `governed_v2` 作为别名保留，eval 脚本和老测试无需改动
3. 前端 HTML `<select>` 选单无需改（Finding 0.5：前端本就只暴露 `full` / `naive`）

#### 2.2.2 Legacy Session 的处置

你之前已拍板：**选项 b，老的代码改删的就删**。

这意味着：

- `core/memory.py:826-849` 的 "legacy AO 合成占位" 逻辑——**删除**
- `core/analytical_objective.py:44 IncompatibleSessionError` 在遇到老 session（无 stance 字段）时——**继续抛出**，要求用户跑迁移脚本
- `scripts/migrate_phase_2_4_to_2r.py`——**保留**作为迁移工具

用户侧影响：如果你本地有 A-path 跑过的老 session 文件，Migration 后 restore 时会报错。需要要么删掉老 session 文件，要么跑一次迁移脚本。本地 dev 环境建议直接清空 `data/sessions/`。

#### 2.2.3 `main.py` CLI 入口的处置

**审计发现**（§1.1）：`main.py:22` 的 `chat` 命令直接构造 `UnifiedRouter(session_id="cli_session")`，绕过 API/session 包装层，对 `router_mode` flag 无感知。

**处置方案**：改为 `build_router(session_id="cli_session", router_mode="full")`，让 CLI 也走 GovernedRouter。

### 2.3 子任务拆分

#### F-main.1 `build_router` 分支合并

**目标**：`router_mode in {"full", "governed_v2", "router"}` 统一走 GovernedRouter 分支。

**改动**：`core/governed_router.py:559-570`

当前：

```python
def build_router(session_id, router_mode, ...):
    if router_mode == "governed_v2":
        return GovernedRouter(...)
    if router_mode == "router" and config.enable_governed_router:
        return GovernedRouter(...)
    # 默认 fallback
    return UnifiedRouter(...)
```

改为：

```python
def build_router(session_id, router_mode, ...):
    if router_mode == "naive":
        # naive 保留独立路径
        raise ValueError("naive mode should use NaiveRouter, not build_router")

    # full / governed_v2 / router 全部走 GovernedRouter
    # （UnifiedRouter 仍然作为 GovernedRouter 内部的 inner_router，不作为独立 router 对外暴露）
    return GovernedRouter(session_id=session_id, ...)
```

#### F-main.2 Session Router 缓存合并

**目标**：合并 `api/session.py:41-70` 的 `_router` 和 `_governed_router` 字段。

**改动**：`api/session.py:41-99`

当前有三个独立 router 缓存字段：

```python
class Session:
    def __init__(self):
        self._router = None
        self._governed_router = None
        self._naive_router = None
```

合并为：

```python
class Session:
    def __init__(self):
        self._agent_router = None  # 统一为单一 agent router（内部是 GovernedRouter）
        self._naive_router = None

    @property
    def agent_router(self):
        if self._agent_router is None:
            self._agent_router = build_router(self.session_id, router_mode="full")
            self._restore_router_state(self._agent_router)
        return self._agent_router

    # 向后兼容的 alias
    @property
    def router(self):
        return self.agent_router

    @property
    def governed_router(self):
        return self.agent_router
```

#### F-main.3 Session.chat 分发逻辑简化

**改动**：`api/session.py:83-99`

当前：

```python
def chat(self, mode: str = "full", ...):
    if mode == "naive":
        return self.naive_router.chat(...)
    elif mode == "governed_v2":
        return self.governed_router.chat(...)
    else:
        return self.router.chat(...)
```

改为：

```python
def chat(self, mode: str = "full", ...):
    if mode == "naive":
        return self.naive_router.chat(...)
    # full / governed_v2 都走 agent_router
    return self.agent_router.chat(...)
```

#### F-main.4 CLI 入口修复

**改动**：`main.py:22`

当前：

```python
chat_router = UnifiedRouter(session_id="cli_session")
```

改为：

```python
from core.governed_router import build_router
chat_router = build_router(session_id="cli_session", router_mode="full")
```

#### F-main.5 前端兼容性验证

**改动**：无需改前端代码（Finding 0.5）。验证：

- `web/index.html:786-787` 的 `<select>` 仍然只有 `full` / `naive`——保留现状
- `web/app.js:5, 162` 的三元表达式无需改——`full` 内部走 GovernedRouter 对前端透明
- 手动测试：前端发送 `mode=full` 请求，确认后端实际走了 GovernedRouter（通过 log 或 trace 验证）

#### F-main.6 清理 MISLEADING flags

**目标**：借 Migration PR 一起清理（§9.1）。

**改动**：

- 删除 `config.py:45` 的 `ENABLE_STANDARDIZATION_CACHE` 定义
- 删除 `tests/test_config.py:30` 对该 flag 的断言
- 删除 `config.py:153-155` 的 `ENABLE_DEPENDENCY_CONTRACT` 定义
- 保留 `DependencyContract` 类暂不动（留到 Task Pack E 决定激活或删除）
- 对 `.env.example` 做一次 sweep，删除 flag-not-in-code 的条目，同步 config.py 当前内容

#### F-main.7 Legacy AO 合成删除

**目标**：按你的"选项 b 删老代码"原则，删除 `core/memory.py:826-849` 的 legacy AO 合成占位逻辑。

**改动**：

- 删除 `memory.py:826-849` 的 `synthesize_legacy_ao` 相关代码
- 修改 `from_dict` 路径：如果 `ao_history` 为空但 `working_memory` 非空，**直接抛 `IncompatibleSessionError`**，要求用户跑迁移脚本

**验证**：

- 对 `scripts/migrate_phase_2_4_to_2r.py` 跑一次，确认它能把老格式升级为新格式
- 清空 `data/sessions/`，确认新 session 能正常创建

#### F-main.8 Session Resume Legacy 处置统一

**目标**：让所有"restart 后处理老数据"的路径都走同一个决策——或迁移或报错。

**改动**：

- `_restore_router_state`（`api/session.py:147`）：遇到 `IncompatibleSessionError` 不捕获，让错误冒到 API 层，由 HTTP 500 + 明确错误信息提示用户
- 在 API 层（`api/routes.py:210`）捕获此异常，返回 HTTP 400 + 友好提示："Session format incompatible. Please create a new session or run migration script."

#### F-main.9 回归测试

**目标**：覆盖 Migration 后的所有核心路径。

**新增测试**：

- `tests/test_migration_session_routing.py`
  - Test 1：`mode="full"` 请求走 GovernedRouter（断言 `session.agent_router.__class__.__name__ == "GovernedRouter"`）
  - Test 2：`mode="governed_v2"` 请求走 GovernedRouter（别名验证）
  - Test 3：`mode="naive"` 请求走 NaiveRouter（不受影响）
  - Test 4：`session.router` alias 返回 agent_router
  - Test 5：`session.governed_router` alias 返回 agent_router
- `tests/test_main_cli.py`
  - CLI `chat` 命令构造的 router 是 GovernedRouter

**修改测试**：

- 全仓 grep `UnifiedRouter(` 的直接构造点（测试 fixture 里），替换为 `build_router(..., router_mode="full")`
- 对应的 assertion 从 `UnifiedRouter` 改为 `GovernedRouter`

#### F-main.10 Benchmark 基线快照

**目标**：Migration 前后行为一致性验证。

**流程**：

1. 在 Migration 分支合入前，跑一次完整 `eval_end2end` benchmark（主 180 任务 + held-out 75 任务），保存为 `data/benchmarks/baseline_pre_migration_<date>.json`
2. Migration 合入后再跑一次相同 benchmark，保存为 `data/benchmarks/baseline_post_migration_<date>.json`
3. 对比两份结果，确认：
   - 整体完成率浮动 ≤ 2 个百分点
   - 无新增的系统性 failure mode
   - 若有个别任务的 pass/fail 翻转，逐个 trace 分析

**注意**：Migration 的 target 是"生产路径 = eval 路径"，所以理论上 eval 的结果**不应该变化**（因为 eval 本来就走 GovernedRouter）。如果有显著变化，说明 Migration 改动有副作用，需要定位。

### 2.4 验收标准

- ✅ F-main.1 ~ F-main.9 所有改动完成
- ✅ `tests/test_migration_session_routing.py` 5 个测试通过
- ✅ 原有 `tests/` 全部 pass（无 regression）
- ✅ `eval_end2end` benchmark 对比浮动 ≤ 2 个百分点
- ✅ 手动在前端跑一次完整 case study（比如 Case A 摩托车场景），确认 AO block 在 prompt 中非空（通过 trace 查看）
- ✅ CLI `python main.py chat` 能正常多轮对话
- ✅ 所有 MISLEADING flag 清理完成
- ✅ commit message: `feat(migration): unify production path to GovernedRouter`

### 2.5 风险点

1. **Benchmark regression**：Migration 理论上不应改变 eval 行为（eval 本就走 GovernedRouter），但若发现有 regression，说明新 session 路由路径或 restore 路径引入了副作用，需 trace 定位
2. **前端 mode 参数兼容**：前端代码用 `mode=full` 发请求，Migration 后需确保请求能正常路由到 GovernedRouter——这是设计重点
3. **老 session 文件的影响**：你本地如果有 `data/sessions/` 下的老 session，重启后尝试 restore 会报错。需在 Migration 合入前先清空（或保留作为迁移脚本测试用例）
4. **CLI `_restore_router_state` 兼容性**：`_restore_router_state` 方法之前接受 UnifiedRouter 或 GovernedRouter 两种对象（通过 `hasattr(router_obj, "to_persisted_state")`），Migration 后只有 GovernedRouter，方法行为应该不变但需确认
5. **`governed_v2` mode 的历史调用点**：全仓 grep `governed_v2` 确认所有调用点（测试、docs、前端）Migration 后行为正确

### 2.6 Codex Prompt 草稿

````markdown
# 任务：Migration · 统一生产路径到 GovernedRouter（Task Pack F-main）

## 背景

当前 `router_mode="full"`（API 默认）走 UnifiedRouter，而 benchmark 用的 `router_mode="router"` + `ENABLE_GOVERNED_ROUTER=true` 走 GovernedRouter。两条路径不对称，导致前端用户看不到 AO / governance / OASC 等 Phase 1.6 成果。

本次 Migration 让 `mode="full"` 在 API 和 CLI 中都走 GovernedRouter，同时保留 `mode="naive"` 作为 baseline。

**前置条件**：Task Pack F-bugfix 已合入（`restore_persisted_state` 的硬编码 contract 列表已修复）。

## 具体改动（10 个子任务）

### F-main.1 `build_router` 分支合并
改 `core/governed_router.py:559-570`：`router_mode in {"full","governed_v2","router"}` 全部 return GovernedRouter。`router_mode="naive"` 抛 ValueError（naive 应由 NaiveRouter 直接构造，不走 build_router）。

### F-main.2 Session router 缓存合并
改 `api/session.py:41-70`：合并 `_router` 和 `_governed_router` 为 `_agent_router`。保留 `_naive_router`。`router` 和 `governed_router` 作为 property alias 返回 `agent_router`。

### F-main.3 Session.chat 分发简化
改 `api/session.py:83-99`：`mode="naive"` 走 `naive_router`，其他一切走 `agent_router`。

### F-main.4 CLI 入口修复
改 `main.py:22`：`UnifiedRouter(...)` 改为 `build_router(..., router_mode="full")`。

### F-main.5 前端兼容性验证（无代码改动）
手动测试：前端发 `mode=full` 请求，确认后端 log/trace 显示走了 GovernedRouter。

### F-main.6 清理 MISLEADING flags
- 删除 `config.py:45` 的 `ENABLE_STANDARDIZATION_CACHE` 定义
- 删除 `tests/test_config.py:30` 对该 flag 的断言
- 删除 `config.py:153-155` 的 `ENABLE_DEPENDENCY_CONTRACT` 定义
- `DependencyContract` 类保留（由 Task Pack E 决定激活或删）
- 对 `.env.example` 做一次 sweep，删除 flag-not-in-code 的条目

### F-main.7 Legacy AO 合成删除
删除 `core/memory.py:826-849` 的 legacy AO 合成占位逻辑。修改 `from_dict`：遇到老格式 session 时直接抛 `IncompatibleSessionError`，不再 fallback。

### F-main.8 Session Resume Legacy 处置
- `api/session.py:147` 的 `_restore_router_state`：不捕获 `IncompatibleSessionError`，让它冒到 API 层
- `api/routes.py:210`：捕获该异常，返回 HTTP 400 + 友好提示文案

### F-main.9 回归测试
新建 `tests/test_migration_session_routing.py`，5 个测试用例（见本任务完整描述）。对全仓 `UnifiedRouter(` 直接构造点做 grep，替换为 `build_router(..., router_mode="full")`。

### F-main.10 Benchmark 基线快照
- Migration 合入前：跑 `eval_end2end` 全量，保存为 `data/benchmarks/baseline_pre_migration_<date>.json`
- Migration 合入后：再跑一次，保存为 `baseline_post_migration_<date>.json`
- 对比两份，报告整体完成率变化和任何 pass/fail 翻转的任务

## 验收标准

- 所有 10 个子任务完成
- 新测试全部通过
- 原有 `tests/` 全部 pass，无 regression
- benchmark 整体完成率浮动 ≤ 2 个百分点
- 手动跑一次前端 case：用 `mode=full` 发问"算摩托车在快速路早高峰的 NOx 排放"，trace 中应显示 OASC / contract chain 装载完整
- CLI `python main.py chat` 能正常运行多轮对话
- commit message: `feat(migration): unify production path to GovernedRouter`

## 约束

- 单独一个 feature 分支
- 不做 Task Pack E（YAML 合并）、Task Pack B（约束 writer）等其他工作
- 老 session 文件：**不做兼容 fallback**，遇到老格式直接报错要求迁移

## 首轮回复

动手前请 ACK 并列出：
1. 你对 `build_router` 当前分支逻辑的理解（贴相关代码行）
2. 你发现的 `_router` / `_governed_router` 所有使用点（包括 test fixture）
3. `governed_v2` mode 在代码中的调用点清单
4. Benchmark 基线快照的命令行示例（`eval_end2end.py` 的完整 invocation）
5. 你认为本 Migration 最容易踩的 2-3 个坑

等我确认后再开工。
````

---

## 3. Task Pack E-8.1 · 双 YAML 合并

### 3.1 背景与动机

**审计发现**（§4.3 / §8.1 / Finding 0.6）：同一 tool 的属性分散在两份 YAML 里：

- `config/tool_contracts.yaml` 管：`parameters` / `dependencies` / `readiness` / `continuation_keywords` / `action_variants`
- `config/unified_mappings.yaml` 管：`required_slots` / `optional_slots` / `defaults` / `clarification_followup_slots` / `confirm_first_slots`

**后果**：

- 加新工具要改两个 YAML
- 同一 tool 在两处的字段分工混乱，容易漂移
- Task Pack D（新增 `clean_dataframe` 工具）如果先发，E 后追，返工成本高

**本 Task Pack 的作用**：在 Task Pack C+D 之前把两份 YAML 合并，让后续的新增工具只需改一处。

### 3.2 设计决策

#### 3.2.1 合并方向

**决策**：`unified_mappings.yaml` 的 `tools.<n>` 段合并进 `tool_contracts.yaml`。

理由（审计 §8.1）：

- `tool_contracts.yaml` 已是 tool-level 的"source of truth"，语义最完整
- `unified_mappings.yaml` 同时管 tool 之外的全局枚举（`vehicle_types` / `pollutants` / `seasons` / `road_types` 等），不能整份废掉
- 合并后：
  - `tool_contracts.yaml` 升级为"唯一的 tool 声明文件"
  - `unified_mappings.yaml` 降级为"标准化枚举字典"（保留 tool 以外的内容）

#### 3.2.2 新的 schema 结构

`tool_contracts.yaml` 中每个 tool 的段扩展为：

```yaml
tools:
  query_emission_factors:
    # 原有字段保留
    parameters:
      vehicle_type:
        required: true
        schema: { type: string }
        standardization: { ... }
      pollutants:
        required: false
        schema: { type: array, items: { type: string } }
    dependencies:
      requires: []
      provides: [emission_factors]
    readiness:
      required_task_types: []
      requires_geometry_support: false
    continuation_keywords: [因子, factor, ...]
    action_variants:
      - run_emission_factors_query

    # 新增字段（从 unified_mappings.yaml 迁入）
    required_slots: [vehicle_type, model_year]
    optional_slots: [pollutants, season, road_type]
    defaults:
      model_year: 2020
    clarification_followup_slots: [season]
    confirm_first_slots: []
```

### 3.3 子任务拆分

#### E-8.1.1 盘点 `unified_mappings.yaml` 当前内容

**目标**：明确哪些字段迁移、哪些保留。

**产出**：一份 markdown 文档 `docs/yaml_merge_analysis.md`，列出：

- `unified_mappings.yaml` 当前所有 top-level keys
- 每个 key 的性质（tool-level / 全局枚举 / 其他）
- 迁移决策（迁到 `tool_contracts.yaml` / 保留在 `unified_mappings.yaml` / 删除）

这一步是为了在动手前发现隐藏的字段，避免漏迁。

#### E-8.1.2 扩展 `tool_contracts.yaml` schema

**目标**：把 `unified_mappings.yaml` 的 `tools.<n>` 段内容迁入 `tool_contracts.yaml`。

**改动**：

- 对 9 个工具逐一操作，把 `unified_mappings.yaml:tools.<n>.{required_slots, optional_slots, defaults, clarification_followup_slots, confirm_first_slots}` 迁入 `tool_contracts.yaml:tools.<n>`
- 保留 `unified_mappings.yaml:tools` 段作为过渡（不立即删除，便于回滚）

#### E-8.1.3 更新 `tools/contract_loader.py`

**目标**：`ToolContractRegistry` 支持新增的 5 个字段。

**改动**：

- `tools/contract_loader.py::ToolContractRegistry` 的 schema 定义新增 5 个字段的加载逻辑
- 新增 getter 方法：`get_required_slots(tool_name)` / `get_optional_slots(tool_name)` / `get_defaults(tool_name)` / `get_clarification_followup_slots(tool_name)` / `get_confirm_first_slots(tool_name)`

#### E-8.1.4 修改 reader 1：`stance_resolution_contract.py`

**改动**：`core/contracts/stance_resolution_contract.py:12, 177-186`

当前：

```python
UNIFIED_MAPPINGS_PATH = "config/unified_mappings.yaml"
# ...
def _get_required_slots(tool_name):
    mappings = yaml.safe_load(open(UNIFIED_MAPPINGS_PATH))
    return mappings["tools"][tool_name]["required_slots"]
```

改为：

```python
from tools.contract_loader import get_tool_contract_registry

def _get_required_slots(tool_name):
    return get_tool_contract_registry().get_required_slots(tool_name)
```

#### E-8.1.5 修改 reader 2：`runtime_defaults.py`

**改动**：`core/contracts/runtime_defaults.py:8, 49-53`

同上：把 `unified_mappings.yaml` 的读取改为 `tool_contracts.yaml` 的读取。保留 `_RUNTIME_DEFAULTS` 的硬编码覆盖机制（§8.5 设计上保留）。

#### E-8.1.6 扫描其他 reader

**目标**：确认没有漏改的 reader。

**操作**：

- `grep -rn "unified_mappings" --include="*.py"` 全仓扫描
- 每个命中确认是在读 `tools.<n>` 段（需要改为读 `tool_contracts.yaml`）还是在读其他段（保持不动）

可能的 reader 候选（审计 §8.1 提到）：`services/config_loader.py`、`shared/standardizer/constants.py`。

#### E-8.1.7 删除 `unified_mappings.yaml:tools` 段

**目标**：E-8.1.4/5/6 完成后，删除 `unified_mappings.yaml:tools` 段。

**验证**：

- 删除前：全仓 grep 确认不再有读取 `unified_mappings.yaml:tools.<n>` 的地方
- 删除后：跑全量 test + 跑一次 `eval_end2end` smoke test（10-20 个任务，而不是全量）

#### E-8.1.8 回归测试

**新增测试**：`tests/test_yaml_merge.py`

- Test 1：`get_tool_contract_registry().get_required_slots("query_emission_factors")` 返回值与旧 `unified_mappings.yaml` 一致
- Test 2：遍历 9 个工具，验证每个工具的 5 个新字段都能正确加载
- Test 3：`stance_resolution_contract._get_required_slots(...)` 的输出与旧行为一致

**修改测试**：

- 全仓 grep `unified_mappings.yaml` 在测试文件中的引用，按需要修改

### 3.4 验收标准

- ✅ `docs/yaml_merge_analysis.md` 完成，覆盖 `unified_mappings.yaml` 所有字段的迁移决策
- ✅ 9 个工具的 5 个新字段全部迁入 `tool_contracts.yaml`
- ✅ `tools/contract_loader.py` 提供 5 个新 getter
- ✅ `stance_resolution_contract` 和 `runtime_defaults` 改为读 `tool_contracts.yaml`
- ✅ `unified_mappings.yaml:tools` 段删除
- ✅ `tests/test_yaml_merge.py` 通过
- ✅ 全量 tests pass
- ✅ `eval_end2end` smoke test（10-20 任务）pass
- ✅ commit message: `refactor(yaml): merge tool-level fields from unified_mappings into tool_contracts`

### 3.5 风险点

1. **漏改 reader**：`unified_mappings.yaml` 的 reader 可能散落在非预期位置；必须做完整的 grep 覆盖
2. **字段语义漂移**：`required_slots` 和 `parameters.<p>.required` 看起来冗余，其实语义不同——前者是"对话层澄清对象"，后者是"schema 层必填性"。合并时保留两个字段，不合并
3. **`unified_mappings.yaml:tools` 段的删除时机**：建议 E-8.1.4/5/6 合入后观察一周再删（灰度），不是 same PR 立即删
4. **Runtime defaults 机制保留**：§8.5 的结论是保留 `_RUNTIME_DEFAULTS`——这次重构不动它

### 3.6 Codex Prompt 草稿

````markdown
# 任务：Task Pack E-8.1 · 双 YAML 合并

## 背景

目前同一 tool 的属性分散在两份 YAML 里：
- `config/tool_contracts.yaml` 管 parameters / dependencies / readiness / continuation_keywords / action_variants
- `config/unified_mappings.yaml` 管 required_slots / optional_slots / defaults / clarification_followup_slots / confirm_first_slots

本任务把 `unified_mappings.yaml:tools.<name>` 段合并进 `tool_contracts.yaml`。

**前置条件**：Task Pack F-main 已合入（Migration 完成）。

## 具体改动（8 个子任务）

### E-8.1.1 盘点分析
产出 `docs/yaml_merge_analysis.md`，列出 `unified_mappings.yaml` 所有 top-level keys 的性质（tool-level / 全局枚举 / 其他）和迁移决策。

### E-8.1.2 扩展 tool_contracts.yaml
对 9 个工具逐一操作，把 `unified_mappings.yaml:tools.<name>.{required_slots, optional_slots, defaults, clarification_followup_slots, confirm_first_slots}` 迁入 `tool_contracts.yaml:tools.<name>`。

### E-8.1.3 更新 contract_loader
扩展 `tools/contract_loader.py` 的 `ToolContractRegistry`：新增 5 个字段的加载逻辑 + 5 个 getter 方法（`get_required_slots` 等）。

### E-8.1.4 修改 stance_resolution_contract reader
改 `core/contracts/stance_resolution_contract.py:12, 177-186`：读取 `unified_mappings.yaml` 的逻辑改为读 `tool_contracts.yaml`（通过 contract_loader 的新 getter）。

### E-8.1.5 修改 runtime_defaults reader
改 `core/contracts/runtime_defaults.py:8, 49-53`：同上，改为读 `tool_contracts.yaml`。保留 `_RUNTIME_DEFAULTS` 硬编码覆盖机制（设计上故意保留）。

### E-8.1.6 全仓扫描其他 reader
`grep -rn "unified_mappings" --include="*.py"` 全仓扫描，每个命中判断是否需要改。可能候选：`services/config_loader.py`、`shared/standardizer/constants.py`。

### E-8.1.7 删除 unified_mappings.yaml:tools 段
E-8.1.4/5/6 完成并通过测试后删除。**注意**：本子任务可以独立一个 PR，与前面的子任务分离，降低风险。

### E-8.1.8 回归测试
新建 `tests/test_yaml_merge.py`，3 个测试用例（见本任务完整描述）。

## 验收标准

- 9 个工具的 5 个新字段在 `tool_contracts.yaml` 中完整
- `unified_mappings.yaml:tools` 段删除
- `unified_mappings.yaml` 其他段（全局枚举）保留不变
- `tests/test_yaml_merge.py` 通过
- 全量 tests pass
- `eval_end2end` 10-20 任务 smoke test pass
- commit message: `refactor(yaml): merge tool-level fields from unified_mappings into tool_contracts`

## 约束

- 保留 `required_slots` 和 `parameters.<p>.required` 两个字段（语义不同，不合并）
- 保留 `runtime_defaults.py:_RUNTIME_DEFAULTS` 机制（§8.5 设计决策）
- E-8.1.7 可以分独立 PR

## 首轮回复

动手前请先完成 E-8.1.1 的分析产出（`docs/yaml_merge_analysis.md`），并在 ACK 里粘贴该文档的核心内容：
1. `unified_mappings.yaml` 当前 top-level keys 清单
2. 每个 key 的迁移决策
3. 全仓 grep `unified_mappings` 的结果清单

等我确认分析后再进入代码改动。
````

---


## 4. Task Pack B · 约束违反 Writer Pipeline

### 4.1 背景与动机

**审计关键发现**（§7.B、Finding 0.1）：

- `AnalyticalObjective.constraint_violations` 字段已定义（`core/analytical_objective.py:214`）
- `FactMemory.constraint_violations_seen` / `cumulative_constraint_violations` 字段已定义（`core/memory.py:84, 89`）
- `FactMemory.append_constraint_violation` 方法已实现（`core/memory.py:195-213`）
- **但生产代码中无任何 producer 调用这些方法** —— 只有 `tests/test_state_contract.py:65,113,191` 用
- UnifiedRouter 的 `_evaluate_cross_constraint_preflight`（`core/router.py:2165`）检测到违反只写 trace + blocked_info + response，**不写 fact_memory**
- StandardizationEngine 的违反检查（`services/standardization_engine.py:643-666`）只抛异常 + records，**不写 fact_memory**
- Assembler 虽然渲染 constraint_violations 到 AO block，但源头永远是空

**影响**：

- 论文 Chapter 5 Case D（跨轮约束反馈）无法在代码中复现——因为约束历史从来没被写入
- Chapter 4.3.2 "规则检测 + LLM 响应" pattern 只完成了"检测"，没完成"注入 LLM context"的闭环

**Task Pack B 的本质**：**从零搭建约束违反的 writer pipeline**，不是"激活已有机制"。

### 4.2 设计决策

#### 4.2.1 Writer 的设计模式

两种候选：

**模式 A：Engine 直接持有 memory 引用**

- `StandardizationEngine.__init__` 新增 `fact_memory` 参数
- Engine 在检测到违反时直接调 `fact_memory.append_constraint_violation(...)`
- 问题：破坏 engine 的"纯函数"特性，测试时需要 mock memory

**模式 B：Engine 产出 events，Router 层消费后写 memory**（**推荐**）

- Engine 保持纯函数特性，只记录 `ViolationRecord` 对象
- Router 层（UnifiedRouter 的 `_evaluate_cross_constraint_preflight` + 类似 hook）捕获这些 records，统一写 memory
- 好处：engine 可测试性不变，memory 写入点集中在 Router

**选用模式 B**。具体方案：

- 在 UnifiedRouter 里新增 `_record_cross_constraint_violation(violations, turn, ao_id)` 方法，作为所有 violation 写 memory 的单一入口
- 两个 violation 源（preflight + standardization_engine）都通过这个方法写
- OASC 的 `_sync_persistent_session_facts` 里的聚合逻辑保持不动（审计 §7.B.2 表明一旦 write 接通，OASC 的聚合自动生效）

#### 4.2.2 Violation 的字段规格

`append_constraint_violation(turn, constraint, values, blocked)` 当前签名。扩展为携带更多结构化信息：

```python
{
    "turn": int,              # 发生在第几轮
    "constraint_name": str,   # 例如 "vehicle_road_compatibility"
    "constraint_type": str,   # "blocked_combinations" / "conditional_warning" / "consistency_warning"
    "values": Dict,           # 触发违反的参数组合，例如 {"vehicle_type": "摩托车", "road_type": "高速公路"}
    "blocked": bool,          # 是否阻塞执行
    "reason": str,            # 人类可读的原因，例如 "摩托车不允许在高速公路上行驶"
    "source": str,            # "preflight" / "standardization_engine" / ...
    "ao_id": Optional[str],   # 当前 AO 的 id
}
```

#### 4.2.3 Token 预算

当前 `ao_block_token_budget=1200`（`config.py:156`）。`cumulative_constraint_violations` 有上限（`core/memory.py:*` 的 `MAX_CUMULATIVE_CONSTRAINTS`，需确认实际值）。

决策：

- 本 Task Pack 不调整 token 预算
- 若 Migration 后实测发现约束块把 AO block 撑爆，再另开 PR 调整（事后优化）

#### 4.2.4 False positive 处理

**审计风险点 3 提到**：StandardizationEngine 在 dry-run 标准化时也可能触发违反（比如 LLM 试探性把 `"小汽车+高速公路"` 标准化为 `"摩托车+高速公路"`，触发 vehicle_road_compatibility 违反）。

**决策**：Writer 点区分"actual violation"和"speculative violation"：

- Actual：用户当前 turn 明确提供的参数组合触发 → 写 memory
- Speculative：standardization 内部尝试的组合触发 → 不写 memory（只记录到 trace）

实现方式：`_record_cross_constraint_violation` 方法新增 `is_speculative: bool` 参数，speculative 只写 trace 不写 memory。

### 4.3 子任务拆分

#### B.1 统一 Violation Record 数据结构

**目标**：定义一个 canonical `ConstraintViolationRecord` 数据类，让 engine 和 router 共享。

**改动**：

新增 `core/constraint_violation_record.py`：

```python
from dataclasses import dataclass, field
from typing import Dict, Optional, Any

@dataclass
class ConstraintViolationRecord:
    turn: int
    constraint_name: str
    constraint_type: str  # "blocked_combinations" / "conditional_warning" / "consistency_warning"
    values: Dict[str, Any]
    blocked: bool
    reason: str
    source: str  # "preflight" / "standardization_engine" / ...
    ao_id: Optional[str] = None
    is_speculative: bool = False  # True = dry-run 产生，不写 memory

    def to_dict(self) -> Dict:
        return { ... }

    @classmethod
    def from_dict(cls, d: Dict) -> "ConstraintViolationRecord":
        return cls(**d)
```

更新 `FactMemory.append_constraint_violation` 签名接受 `ConstraintViolationRecord` 对象（向后兼容老签名通过 overload / 字典拆解）。

#### B.2 Router 层统一 Writer 入口

**改动**：`core/router.py`

在 UnifiedRouter 上新增方法：

```python
def _record_cross_constraint_violation(
    self,
    violation: ConstraintViolationRecord,
) -> None:
    """Single source of truth for writing constraint violations to memory.

    Called from multiple violation source points (preflight, standardization_engine).
    Speculative violations only write trace, not memory.
    """
    # 1. 永远写 trace（可解释性）
    self.trace.add_step(
        TraceStepType.CROSS_CONSTRAINT_VIOLATION if violation.blocked
        else TraceStepType.CROSS_CONSTRAINT_WARNING,
        data=violation.to_dict(),
    )

    # 2. Speculative 违反不写 memory
    if violation.is_speculative:
        return

    # 3. 写 fact_memory
    self.memory.fact_memory.append_constraint_violation(
        turn=violation.turn,
        constraint=violation.constraint_name,
        values=violation.values,
        blocked=violation.blocked,
        # 扩展的可选字段
        constraint_type=violation.constraint_type,
        reason=violation.reason,
        source=violation.source,
    )
```

#### B.3 改造 `_evaluate_cross_constraint_preflight`

**改动**：`core/router.py:2165` 附近

当前逻辑只写 trace + blocked_info：

```python
def _evaluate_cross_constraint_preflight(self, ...):
    violations = validator.validate(...)
    for v in violations:
        self.trace.add_step(...)
        if v.blocks_execution:
            state.execution.blocked_info[...] = ...
    # ⚠️ 没有写 memory
```

改为：

```python
def _evaluate_cross_constraint_preflight(self, ...):
    violations = validator.validate(...)
    for v in violations:
        record = ConstraintViolationRecord(
            turn=self.current_turn_index,
            constraint_name=v.constraint_name,
            constraint_type=v.constraint_type,
            values=v.values,
            blocked=v.blocks_execution,
            reason=v.reason,
            source="preflight",
            ao_id=self._get_current_ao_id_if_available(),
            is_speculative=False,  # preflight 是 actual 用户参数
        )
        self._record_cross_constraint_violation(record)
        # 保留原有的 blocked_info 写入（不改）
        if v.blocks_execution:
            state.execution.blocked_info[...] = ...
```

#### B.4 改造 StandardizationEngine 的违反处理

**改动**：`services/standardization_engine.py:643-666`

Engine 保持纯函数特性。现有的违反检测代码会抛 `StandardizationError`——**保持不变**。

但 engine 内部同时记录 `ViolationRecord` 列表供外部查询：

```python
class StandardizationEngine:
    def __init__(self, ...):
        self._violation_records: List[ViolationRecord] = []

    def get_violations(self) -> List[ViolationRecord]:
        return list(self._violation_records)

    def clear_violations(self):
        self._violation_records.clear()

    def _record_violation(self, ...):
        self._violation_records.append(ViolationRecord(...))
```

Router 在调用 engine 之后读取 violations 并写 memory：

```python
# 在 router.py 某处调用 engine 的地方
engine.clear_violations()
try:
    result = engine.standardize(...)
except StandardizationError:
    raise
finally:
    for v in engine.get_violations():
        record = ConstraintViolationRecord(
            ...,
            source="standardization_engine",
            is_speculative=<根据上下文判断>,
        )
        self._record_cross_constraint_violation(record)
```

**Speculative 判定规则**：在 Router 调用 engine 的上下文中，若 engine 调用是来自 "LLM 探索性标准化"（例如 clarification_contract 的 stage3），记为 speculative；若来自"用户确认参数后的最终标准化"，记为 actual。

#### B.5 AO Writer 接入

**改动**：确保当 AO 存在时，violation 同时写入 AO.constraint_violations。

审计 §7.B.2 表明 OASC 的 `_sync_persistent_session_facts`（`core/contracts/oasc_contract.py:353-379`）已经有从 `fact_memory.constraint_violations_seen` 复制到 `current_ao.constraint_violations` 的逻辑。B.3/B.4 接通 writer 后，这层聚合自动生效——**本子任务主要是验证**，不是写新代码。

**验证**：

- 写测试：`tests/test_constraint_violation_ao_sync.py`
- 模拟一个触发违反的 session turn
- 断言：`fact_memory.constraint_violations_seen` 非空
- 断言：OASC after_turn 之后，`current_ao.constraint_violations` 包含该违反

#### B.6 Prompt Injection 验证

**改动**：确保 assembler 渲染的 AO block 包含 constraint_violations。

审计 §5.3 表明 assembler 的 `_build_ao_session_state_block`（`core/assembler.py:385, 438`）已经读 `cumulative_constraint_violations`——**本子任务主要是验证**。

**验证**：

- 手动场景：跑一个违反约束的 case（例如 Case A 摩托车+快速路），查看下一轮的 LLM prompt
- 断言：prompt 里包含 "previous constraint violations" 相关字段，列出上一轮的违反
- 方式：打开 `PERSIST_TRACE=true`，从 trace 里读 assembled prompt；或直接在 assembler 加 debug log

#### B.7 回归测试与端到端测试

**新增测试**：

`tests/test_constraint_violation_writer.py`：

- Test 1：模拟 preflight 检测到 violation，验证 `fact_memory.constraint_violations_seen` 被写入
- Test 2：模拟 standardization_engine 触发 violation，验证 writer 被调用
- Test 3：Speculative violation 只写 trace 不写 memory
- Test 4：Violation record 的字段完整性（turn / constraint_name / reason / source 等全部正确）

`tests/test_constraint_violation_prompt_injection.py`：

- 端到端测试：创建 session → 触发违反 → 下一轮对话，验证 LLM prompt 中包含违反历史

**修改测试**：

- `tests/test_state_contract.py:65,113,191` 的已有测试可能需要调整，因为 `append_constraint_violation` 签名扩展

### 4.4 验收标准

- ✅ `core/constraint_violation_record.py` 新增
- ✅ `UnifiedRouter._record_cross_constraint_violation` 作为唯一 writer 入口
- ✅ `_evaluate_cross_constraint_preflight` 通过 writer 入口写 memory
- ✅ `StandardizationEngine` 提供 `get_violations()` / `clear_violations()` API，Router 读取后写 memory
- ✅ Speculative vs actual 的区分实现
- ✅ `tests/test_constraint_violation_writer.py` 4 个测试通过
- ✅ `tests/test_constraint_violation_prompt_injection.py` 端到端测试通过
- ✅ 手动跑一次 Case D 场景（跨轮违反），trace 和 prompt 显示违反历史保留
- ✅ 原有 tests 无 regression
- ✅ commit message: `feat(constraints): implement constraint violation writer pipeline`

### 4.5 风险点

1. **Prompt bloat**：cumulative violations 累积可能撑爆 AO block token budget。本次不调整预算，但需要观察实际 token 占用
2. **Speculative 判定的边界模糊**：Router 调用 engine 的上下文有多种（stage3 标准化 / tool 参数最终校验 / ...），判定哪些是 speculative 需要仔细设计
3. **与 Task Pack A 的 coupling**：Pack A 的 LLM reply parser 会看到 violation 历史——先做 B 再做 A 是对的，但 A 动工时可能需要调整 prompt 模板
4. **Trace 体积增加**：所有 violation 都写 trace（含 speculative），trace 体积可能显著增加。需要确认 trace 的 serialization 性能不受影响
5. **OASC 聚合可能有 dedup 问题**：同一 violation 在同一 turn 被重复写入的情况下，OASC 聚合是否 dedup？需要测试

### 4.6 Codex Prompt 草稿

````markdown
# 任务：Task Pack B · 约束违反 Writer Pipeline

## 背景

当前 `fact_memory.constraint_violations_seen` / `cumulative_constraint_violations` 字段已定义，但**生产代码中无 writer**——约束违反只写 trace，不写 memory。后果：论文 Chapter 5 Case D（跨轮约束反馈）无法在代码中复现。

本任务从零搭建约束违反的 writer pipeline，让违反能被 AO 和 assembler 看到。

**前置条件**：Task Pack F-main 已合入（Migration 完成，AO 在生产路径生效）。

## 设计模式

采用"Engine 纯函数 + Router 层 Writer"模式：
- Engine（StandardizationEngine）保持纯函数特性，只记录 ViolationRecord
- UnifiedRouter 统一通过 `_record_cross_constraint_violation` 写 memory
- 区分 actual violation（写 memory）和 speculative violation（只写 trace）

## 具体改动（7 个子任务）

### B.1 定义 ConstraintViolationRecord 数据结构
新增 `core/constraint_violation_record.py`，定义 dataclass 含字段：turn / constraint_name / constraint_type / values / blocked / reason / source / ao_id / is_speculative。扩展 `FactMemory.append_constraint_violation` 签名，兼容老调用。

### B.2 Router 层 Writer 入口
在 `UnifiedRouter` 新增 `_record_cross_constraint_violation(violation: ConstraintViolationRecord)` 方法。逻辑：永远写 trace；若非 speculative，写 fact_memory。

### B.3 改造 preflight
`core/router.py:2165 _evaluate_cross_constraint_preflight`：每次检测到 violation，构造 ConstraintViolationRecord（source="preflight", is_speculative=False）并调 `_record_cross_constraint_violation`。保留原有的 blocked_info 写入逻辑不变。

### B.4 改造 StandardizationEngine
`services/standardization_engine.py:643-666` 当前直接抛 StandardizationError——保留这个行为。同时给 engine 加 `get_violations()` / `clear_violations()` API，记录所有检测到的 violation 到内部 list。Router 在调用 engine 的地方捕获这些 records 并通过 writer 入口写 memory。Speculative 判定规则：clarification stage3 标准化 = speculative；用户确认后最终标准化 = actual。

### B.5 AO 聚合验证
OASC 的 `_sync_persistent_session_facts` 已有从 `fact_memory.constraint_violations_seen` 复制到 AO 的逻辑，本子任务主要是测试验证，不写新代码。新建 `tests/test_constraint_violation_ao_sync.py` 验证聚合生效。

### B.6 Prompt Injection 验证
Assembler 的 `_build_ao_session_state_block` 已读 cumulative_constraint_violations，本子任务主要验证 prompt 实际包含违反历史。手动跑触发违反的场景（比如 Case A 摩托车+快速路），从 trace 中读 assembled prompt 确认。

### B.7 回归测试
新增：
- `tests/test_constraint_violation_writer.py`（4 个用例）
- `tests/test_constraint_violation_prompt_injection.py`（端到端）
调整：`tests/test_state_contract.py:65,113,191` 按扩展后的签名适配

## 验收标准

- 7 个子任务全部完成
- 新测试全部通过
- 手动验证：触发违反 → 下一轮 LLM prompt 包含违反历史
- 原有 tests 无 regression
- commit message: `feat(constraints): implement constraint violation writer pipeline`

## 约束

- Engine 保持纯函数特性，不持有 memory 引用
- Writer 只有一个入口（Router 的 `_record_cross_constraint_violation`）
- 不调整 `ao_block_token_budget`（事后观察再定）
- 本 Pack 不动 LLM reply parser（Task Pack A 做）

## 首轮回复

动手前请 ACK 并列出：
1. `StandardizationEngine.__init__` 当前的 dependency（哪些参数传入）
2. `core/router.py` 里调用 `StandardizationEngine` 的所有位置（含 context 描述）
3. 你对 speculative 判定规则的理解：哪些上下文应标为 speculative
4. `FactMemory.append_constraint_violation` 当前签名 vs 扩展后签名的兼容策略
5. `TraceStepType.CROSS_CONSTRAINT_VIOLATION` 的现有使用点（确认不会破坏现有的 trace 结构）

等我确认后再动工。
````

---


## 5. Task Pack C+D · Data Quality Pipeline

### 5.1 背景与动机

**审计发现**：

- **Task Pack C**（§7.C、Finding 0.7）：`analyze_file` 已有 `data_quality_warnings` 字段（`tools/file_analyzer.py:262`），但检测维度**单一**——只检查 road_type 下的 speed 异常。需要扩维度
- **Task Pack D**（§7.D）：`clean_dataframe` 工具**完全不存在**。`grep "clean_dataframe|DataFrameCleaner|dataframe.*clean"` 全仓 0 命中

**合并 C 和 D 的理由**：

1. C 的"扩维度"与 D 的"新增工具"共享同一个 **data quality schema**——谁先做都要定义这个 schema，合并推进只定义一次
2. 工作流闭环：`analyze_file` 识别数据质量问题 → LLM 基于 warnings 决定是否清洗 → `clean_dataframe` 执行清洗 → 产物作为新 artifact 进入 AO
3. 论文 Chapter 5 的端到端 case 阶段 2（schema 推断与数据质量感知）需要这一对工具协同

**本 Task Pack 的本质**：定义完整的 data quality pipeline——从检测（C）到清洗（D）再到 artifact 流转（集成到现有 AO / tool graph）。

### 5.2 设计决策

#### 5.2.1 Data Quality Schema

Warnings 的 schema 升级为含 severity + 可能的 suggested ops：

```python
# tools/file_analyzer.py 返回的 data_quality_warnings 新 schema
{
    "warnings": [
        {
            "warning_id": str,              # 稳定 ID 供后续引用，例如 "placeholder_in_site_name"
            "category": str,                # "missing_value" / "outlier" / "schema_inconsistency" / "encoding" / "type_mismatch" / ...
            "severity": str,                # "info" / "warning" / "error"
            "field": Optional[str],         # 涉及的字段名，例如 "site_name"
            "row_indices": Optional[List[int]],  # 涉及的行（如果适用，截断到前 N 个）
            "description": str,             # 人类可读描述
            "suggested_ops": List[Dict],    # 清洗建议（供 clean_dataframe 消费）
        },
        ...
    ],
    "overall_quality_summary": str,         # 一句话总结，供 LLM 直接引用
}
```

**`suggested_ops` 的格式与 `clean_dataframe` 的 operation schema 对齐**：

```python
# clean_dataframe 的 operation schema
{
    "op": str,  # "fillna" / "drop_columns" / "rename_columns" / "coerce_dtypes" / "drop_duplicates" / "filter_rows"
    "args": Dict,  # op 特定的参数，例如 fillna 的 {"column": "site_name", "value": 0, "fillna_strategy": "zero_to_na"}
}
```

设计上让 `analyze_file` 返回的 `suggested_ops` 能被 LLM 直接拼接后传给 `clean_dataframe`，降低 LLM 构造参数的成本。

#### 5.2.2 检测维度清单（Task Pack C）

扩展到以下 6 个维度（基于审计 §7.C.2 + 实用经验）：

1. **Placeholder 检测**（最关键）：0 / -1 / "" / "NA" / "未知" 等伪缺失值——对应论文 Chapter 5 阶段 2 的 `site_name` 字段 0 占位符场景
2. **Missing value rate**：空值率超过阈值（例如 >50%）的列
3. **Outlier detection**：数值列的 IQR 或 z-score 异常（保留现有 road_type × speed 逻辑作为特定子检测）
4. **Schema inconsistency**：列名不规范（含空格、特殊字符）、类型不一致（同一列混合 str/int）
5. **Encoding issue**：非 UTF-8 文件编码、乱码（对应论文 case 的 `roads.cpg` 编码异常场景）
6. **Duplicate rows**：完全重复的行

每个维度对应一个独立的 `_detect_<category>()` 方法。

#### 5.2.3 `clean_dataframe` 工具接口设计

**关键决策**：参数形式用 **"显式 operation list"** 而非"DSL"。

理由：

- LLM 构造参数更稳定（照着 analyze_file 返回的 suggested_ops 填）
- 每个 operation 的 args 是扁平的 dict，schema 明确
- 避免 LLM 需要学习新的 DSL 语法

**接口签名**：

```python
def clean_dataframe(
    file_path: str,           # 输入文件路径（CSV / Excel / JSON）
    operations: List[Dict],   # 清洗操作列表，顺序执行
    output_path: Optional[str] = None,  # 输出文件路径；None 时自动生成
) -> ToolResult:
    """
    operations 示例:
    [
        {"op": "fillna", "args": {"column": "site_name", "strategy": "zero_to_na"}},
        {"op": "drop_columns", "args": {"columns": ["useless_col"]}},
        {"op": "coerce_dtypes", "args": {"column": "avg_speed", "dtype": "float"}}
    ]
    """
```

**返回值**（ToolResult）：

- `status`: success / partial_success / failed
- `output_path`: 清洗后的文件路径
- `summary`: 每个 operation 的执行摘要（成功/失败、影响行数、警告）
- `data_quality_after`: 清洗后的 data_quality_warnings（可选，用于前后对比）

#### 5.2.4 支持的 operation 列表

**初版支持 6 个 operation**（覆盖常见场景）：

| operation | args | 说明 |
|---|---|---|
| `fillna` | `column` / `strategy` (`zero_to_na` / `median` / `mean` / `forward_fill` / `backfill` / `constant`) / `value` | 空值填充或占位符处理 |
| `drop_columns` | `columns: List[str]` | 删除列 |
| `drop_rows` | `condition: str`（pandas query 字符串）| 按条件删除行 |
| `rename_columns` | `mapping: Dict[str, str]` | 列重命名 |
| `coerce_dtypes` | `column: str` / `dtype: str` | 类型转换 |
| `drop_duplicates` | `subset: Optional[List[str]]` | 删除重复行 |

Future operations（留 placeholder 注释，本 Pack 不实现）：

- `join` / `merge`：需要二次调用（当前工具只处理单文件）
- `groupby_agg`：聚合操作，复杂度高
- `apply_formula`：自定义公式，LLM 构造风险大

#### 5.2.5 Artifact 流转

- `clean_dataframe` 产生的 `output_path` 作为新 artifact 注册进 AO（artifact_type = `cleaned_dataframe`）
- 后续工具（比如 `calculate_macro_emission`）可以引用这个 artifact 的 `output_path`
- `tool_contracts.yaml` 中声明 `clean_dataframe.produces: [cleaned_dataframe]`

#### 5.2.6 检测代码的抽取

**审计 §7.C.4 推荐**：先从 `tools/file_analyzer.py`（1629 行巨型文件）抽出 `_build_data_quality_warnings` 及 helper 到独立模块，再扩维度。

**本 Pack 遵循此建议**：

- 新建 `tools/file_quality_checks.py` 作为独立模块
- FileAnalyzerTool 通过组合关系使用这些检测函数
- 每个检测维度一个独立 `_detect_<category>()` 函数，便于单元测试

### 5.3 子任务拆分

#### C+D.1 抽取现有 data quality 逻辑到独立模块

**目标**：先重构不变行为，为后续扩维度做准备。

**改动**：

- 新建 `tools/file_quality_checks.py`
- 把 `tools/file_analyzer.py:262-346` 的 `_build_data_quality_warnings` 及其 helper 抽出来
- `FileAnalyzerTool` 改为 `from tools.file_quality_checks import build_data_quality_warnings`
- 确保原有 test（`tests/test_file_analyzer_targeted_enhancements.py:128,148`）仍通过

#### C+D.2 定义 Data Quality Schema

**目标**：在 `tools/file_quality_checks.py` 定义新 schema 的数据类。

**改动**：

```python
# tools/file_quality_checks.py
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum

class WarningCategory(str, Enum):
    PLACEHOLDER = "placeholder"
    MISSING_VALUE = "missing_value"
    OUTLIER = "outlier"
    SCHEMA_INCONSISTENCY = "schema_inconsistency"
    ENCODING = "encoding"
    TYPE_MISMATCH = "type_mismatch"
    DUPLICATE_ROWS = "duplicate_rows"

class WarningSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

@dataclass
class DataQualityWarning:
    warning_id: str
    category: WarningCategory
    severity: WarningSeverity
    description: str
    field: Optional[str] = None
    row_indices: Optional[List[int]] = None
    suggested_ops: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        ...
```

#### C+D.3 实现 6 个检测维度

**目标**：在 `tools/file_quality_checks.py` 实现 6 个独立检测函数。

**改动**：

每个维度一个独立函数：

```python
def detect_placeholders(df: pd.DataFrame) -> List[DataQualityWarning]:
    """检测 0 / -1 / "" / "NA" 等伪缺失值。
    对数值列检查 0/-1；对字符串列检查 ""/"NA"/"未知" 等关键词。
    若 >20% 的行是占位符，生成 warning，severity=warning。
    """
    ...

def detect_missing_values(df: pd.DataFrame) -> List[DataQualityWarning]:
    """检测空值率 >50% 的列。"""
    ...

def detect_outliers(df: pd.DataFrame) -> List[DataQualityWarning]:
    """数值列的 IQR 异常检测。保留现有的 road_type × speed 逻辑作为特定子检测。"""
    ...

def detect_schema_inconsistency(df: pd.DataFrame) -> List[DataQualityWarning]:
    """列名不规范（空格、特殊字符）；类型不一致。"""
    ...

def detect_encoding_issues(file_path: str, df: pd.DataFrame) -> List[DataQualityWarning]:
    """非 UTF-8 编码（通过 .cpg / chardet 检测）；乱码字符。"""
    ...

def detect_duplicate_rows(df: pd.DataFrame) -> List[DataQualityWarning]:
    """完全重复的行。"""
    ...
```

每个函数返回 `List[DataQualityWarning]`。主入口 `build_data_quality_warnings` 依次调用这 6 个函数并合并结果。

**关键：`suggested_ops` 的填充**

每个 warning 应带上具体的清洗建议，例如：

- 空值率 >50% 的列 → `suggested_ops = [{"op": "drop_columns", "args": {"columns": ["该列名"]}}]`
- 占位符 → `suggested_ops = [{"op": "fillna", "args": {"column": "该列", "strategy": "zero_to_na"}}]`
- 重复行 → `suggested_ops = [{"op": "drop_duplicates", "args": {}}]`

#### C+D.4 更新 `FileAnalyzerTool` 的返回格式

**改动**：`tools/file_analyzer.py:262-346` 附近

当前返回的 `data_quality_warnings` 是 list of dict，但字段不完整。

更新为：

```python
def _build_data_quality_warnings(self, df, file_path):
    from tools.file_quality_checks import build_data_quality_warnings
    warnings = build_data_quality_warnings(df, file_path)
    return {
        "warnings": [w.to_dict() for w in warnings],
        "overall_quality_summary": self._summarize_warnings(warnings),
    }
```

**保留向后兼容**：如果老的调用方只读 `data_quality_warnings` 是 list 格式，改为 dict 后需要 grep 所有消费者。审计文档 §7.C.1 提到消费者在 `:198, 1309, 1451, 1545, :1034-1036, 1573-1574, 1591-1592`。这些全部需要更新为新格式。

#### C+D.5 实现 `clean_dataframe` 工具（Task Pack D 主体）

**改动**：新建 `tools/clean_dataframe.py`

```python
from tools.base import BaseTool, ToolResult
import pandas as pd
from typing import List, Dict, Optional

class CleanDataFrameTool(BaseTool):
    name = "clean_dataframe"

    def execute(self, file_path: str, operations: List[Dict], output_path: Optional[str] = None) -> ToolResult:
        df = self._load_file(file_path)
        summary_entries = []

        for op_def in operations:
            op_name = op_def["op"]
            op_args = op_def.get("args", {})
            try:
                df, entry = self._apply_operation(df, op_name, op_args)
                summary_entries.append(entry)
            except Exception as e:
                summary_entries.append({"op": op_name, "status": "failed", "error": str(e)})
                # 决策：一个 op 失败继续下一个（partial success 模式）

        output_path = output_path or self._generate_output_path(file_path)
        self._save_file(df, output_path)

        # 清洗后重新检测（可选）
        from tools.file_quality_checks import build_data_quality_warnings
        post_warnings = build_data_quality_warnings(df, output_path)

        return ToolResult(
            status="success" if all(e["status"] == "success" for e in summary_entries) else "partial_success",
            output_path=output_path,
            summary=summary_entries,
            data_quality_after={"warnings": [w.to_dict() for w in post_warnings]},
        )

    def _apply_operation(self, df, op_name, op_args):
        op_handlers = {
            "fillna": self._op_fillna,
            "drop_columns": self._op_drop_columns,
            "drop_rows": self._op_drop_rows,
            "rename_columns": self._op_rename_columns,
            "coerce_dtypes": self._op_coerce_dtypes,
            "drop_duplicates": self._op_drop_duplicates,
        }
        handler = op_handlers.get(op_name)
        if not handler:
            raise ValueError(f"Unsupported operation: {op_name}")
        return handler(df, op_args)

    # 6 个 op handler 各自实现
```

#### C+D.6 注册 `clean_dataframe` 到 `tool_contracts.yaml`

**改动**：`config/tool_contracts.yaml`

```yaml
tools:
  clean_dataframe:
    parameters:
      file_path:
        required: true
        schema: { type: string }
      operations:
        required: true
        schema:
          type: array
          items:
            type: object
            properties:
              op: { type: string, enum: [fillna, drop_columns, drop_rows, rename_columns, coerce_dtypes, drop_duplicates] }
              args: { type: object }
      output_path:
        required: false
        schema: { type: string }
    dependencies:
      requires: []
      provides: [cleaned_dataframe]
    readiness:
      required_task_types: []
      requires_geometry_support: false
    continuation_keywords: [清洗, clean, 处理数据]
    action_variants:
      - run_clean_dataframe
    # 合并后的新字段
    required_slots: [file_path, operations]
    optional_slots: [output_path]
    defaults: {}
    clarification_followup_slots: []
    confirm_first_slots: [operations]   # 让 LLM 先确认 ops 再执行
```

#### C+D.7 注册 `clean_dataframe` 到 `tools/registry.py`

**改动**：`tools/registry.py:82-145 init_tools`

```python
from tools.clean_dataframe import CleanDataFrameTool

def init_tools():
    # ... 原有 9 个注册
    registry.register(CleanDataFrameTool())
```

#### C+D.8 处理 `_snapshot_to_tool_args` 的硬编码

**改动**：`core/governed_router.py:427-533`

加一个 `if tool_name == "clean_dataframe"` 分支（临时方案，留给 Task Pack E-剩余 统一重构）。

```python
if tool_name == "clean_dataframe":
    args["file_path"] = snapshot.get("file_path")
    args["operations"] = snapshot.get("operations", [])
    if snapshot.get("output_path"):
        args["output_path"] = snapshot["output_path"]
```

**TODO 注释**：在 `_snapshot_to_tool_args` 函数体开头加：

```python
# TODO(Task Pack E-剩余): 该方法的逐工具分支在 E-剩余 中通过 YAML type_coercion 解耦
```

#### C+D.9 NaiveRouter 暴露性决策

**决策**：`clean_dataframe` 不进 NaiveRouter 白名单。

理由：

- NaiveRouter 是 baseline，不需要工具链协同能力
- 清洗是 agent 工作流的中间步骤，naive 不展示这层能力

#### C+D.10 回归测试

**新增测试**：

`tests/test_file_quality_checks.py`：

- 6 个检测函数各有 3-5 个 fixture 用例
- 占位符检测：合成 `site_name = [0, 0, 0, "北京路", 0]` 的 DataFrame，验证 warning + suggested_ops
- 空值率：>50% 空列 → warning
- Outlier：合成异常值 DataFrame
- Schema：列名含空格 → warning
- Encoding：非 UTF-8 CSV → warning
- Duplicate：重复行 → warning

`tests/test_clean_dataframe.py`：

- 6 个 operation 各一个用例
- partial success 场景：某 op 失败其他继续
- output_path 自动生成逻辑
- `data_quality_after` 字段完整性

`tests/test_data_quality_pipeline_end_to_end.py`：

- 端到端：analyze_file → LLM 模拟构造 ops → clean_dataframe → 验证 cleaned artifact
- 这是论文 Chapter 5 阶段 2 的核心 case 的简化版

### 5.4 验收标准

- ✅ `tools/file_quality_checks.py` 独立模块就位，6 个检测函数
- ✅ `DataQualityWarning` schema 定义清晰，含 `suggested_ops`
- ✅ `FileAnalyzerTool` 返回新 schema，所有消费者适配
- ✅ `tools/clean_dataframe.py` 实现，6 个 operation handler
- ✅ `tool_contracts.yaml` 含 `clean_dataframe` 条目（合并后的新 schema）
- ✅ `tools/registry.py` 注册
- ✅ `tests/test_file_quality_checks.py` 6 维度各 3-5 用例通过
- ✅ `tests/test_clean_dataframe.py` 6 operation 各一用例 + partial success 通过
- ✅ `tests/test_data_quality_pipeline_end_to_end.py` 端到端通过
- ✅ 原有 tests 无 regression
- ✅ 手动跑论文 Chapter 5 阶段 2 的 case（上海 CSV 有 site_name 的 0 占位符 + roads.cpg 编码异常），verify analyze_file 正确识别并给 suggested_ops
- ✅ commit message: `feat(data-quality): add data quality pipeline (analyze_file expansion + clean_dataframe tool)`

### 5.5 风险点

1. **检测阈值的领域适配**：空值率 >50%、占位符 >20% 等阈值需要针对 emission 数据的实际分布调参，本 Pack 给合理默认值，投稿前再基于实际数据微调
2. **`suggested_ops` 的 LLM 消费**：LLM 能否正确消费 `suggested_ops` 拼成 `clean_dataframe` 的 operations 参数，取决于 prompt 设计。这一层留给写论文 case study 时再微调
3. **文件类型覆盖**：`clean_dataframe` 初版只支持 CSV。Excel / JSON / Shapefile 留给未来。需要在工具描述里明确
4. **大文件性能**：真实 CSV 可能有 100 万行（论文 case 的逐小时排放 139 万行），本 Pack 用 pandas 直接处理，超过一定行数的优化留给未来
5. **与 Task Pack E-剩余 的 coupling**：C+D 引入 `clean_dataframe` 时加了 `_snapshot_to_tool_args` 硬编码分支——这是临时方案，E-剩余会统一重构。需要在代码里留 TODO

### 5.6 Codex Prompt 草稿

````markdown
# 任务：Task Pack C+D · Data Quality Pipeline（合并推进）

## 背景

- Task Pack C：`analyze_file` 当前只检测 road_type × speed 异常，需扩维度
- Task Pack D：`clean_dataframe` 工具完全不存在，需从零实现
- 合并推进的理由：两者共享 data quality schema（analyze_file 的 warnings 带 suggested_ops 直接喂给 clean_dataframe）

**前置条件**：Task Pack E-8.1 已合入（双 YAML 合并完成）。

## 设计决策

- **Data Quality Schema**：warnings 带 warning_id / category / severity / suggested_ops 等字段
- **Clean operation 接口**：显式 operation list（非 DSL），初版 6 个 op（fillna / drop_columns / drop_rows / rename_columns / coerce_dtypes / drop_duplicates）
- **检测维度**：6 个（placeholder / missing_value / outlier / schema_inconsistency / encoding / duplicate_rows）
- **NaiveRouter 不暴露 clean_dataframe**

## 具体改动（10 个子任务）

### C+D.1 抽取现有逻辑到独立模块
新建 `tools/file_quality_checks.py`，把 `tools/file_analyzer.py:262-346` 的 `_build_data_quality_warnings` 抽出来，`FileAnalyzerTool` 改为组合使用。零行为变更。

### C+D.2 定义 Data Quality Schema
在 `tools/file_quality_checks.py` 定义 `DataQualityWarning` dataclass、`WarningCategory` / `WarningSeverity` 枚举。warnings 字段含 warning_id / category / severity / description / field / row_indices / suggested_ops。

### C+D.3 实现 6 个检测维度
6 个独立函数（`detect_placeholders` / `detect_missing_values` / `detect_outliers` / `detect_schema_inconsistency` / `detect_encoding_issues` / `detect_duplicate_rows`）。主入口 `build_data_quality_warnings` 依次调用并合并。每个 warning 带具体的 `suggested_ops`。

### C+D.4 更新 FileAnalyzerTool 返回格式
返回 `{"warnings": [...], "overall_quality_summary": "..."}`。更新消费者（`tools/file_analyzer.py:198, 1309, 1451, 1545, 1034-1036, 1573-1574, 1591-1592` 全部命中）。

### C+D.5 实现 clean_dataframe 工具
新建 `tools/clean_dataframe.py`，实现 `CleanDataFrameTool(BaseTool)`，含 6 个 operation handler。Partial success 模式（单个 op 失败继续其他）。返回 `ToolResult` 含 output_path / summary / data_quality_after。

### C+D.6 注册到 tool_contracts.yaml
新增 `clean_dataframe` 条目。parameters / dependencies / readiness / continuation_keywords / action_variants / required_slots / optional_slots / confirm_first_slots 全部声明（合并后的新 schema 形态）。

### C+D.7 注册到 tools/registry.py
`tools/registry.py::init_tools` 加一行 register。

### C+D.8 处理 _snapshot_to_tool_args 硬编码
在 `core/governed_router.py:427-533` 加 `if tool_name == "clean_dataframe"` 分支（临时方案）。在方法体顶部加 TODO 注释标注本分支会被 Task Pack E-剩余 重构。

### C+D.9 NaiveRouter 不暴露
`NAIVE_TOOL_NAMES`（`core/naive_router.py:28-36`）不加入 `clean_dataframe`。

### C+D.10 回归测试
新建 3 个测试文件：
- `tests/test_file_quality_checks.py`（6 维度各 3-5 用例）
- `tests/test_clean_dataframe.py`（6 operation + partial success）
- `tests/test_data_quality_pipeline_end_to_end.py`（analyze_file → clean_dataframe 端到端）

## 验收标准

- 10 个子任务全部完成
- 3 个新测试文件全部通过
- 原有 tests 无 regression
- 手动测试：用论文 case 的上海 CSV（含 site_name 的 0 占位符），analyze_file 返回的 warnings 正确识别并给 suggested_ops；把 suggested_ops 传给 clean_dataframe 能正确清洗
- commit message: `feat(data-quality): add data quality pipeline (analyze_file expansion + clean_dataframe tool)`

## 约束

- `clean_dataframe` 初版只支持 CSV（Excel / JSON 未来扩展）
- 检测阈值使用合理默认值，先不针对特定数据调参
- 保持 FileAnalyzerTool 原有的 road_type × speed 检测逻辑作为 outlier 维度的特定子检测
- LLM prompt 的适配（让 LLM 正确读 warnings 并构造 operations）不在本 Pack 范围，留给写论文 case 时微调

## 首轮回复

动手前请 ACK 并列出：
1. `tools/file_analyzer.py` 中所有消费 `data_quality_warnings` 的位置及当前读取字段方式
2. pandas / openpyxl / chardet 等依赖是否已在 `requirements.txt`（若 encoding 检测需要 chardet）
3. 你对 `suggested_ops` 的 schema 的具体提议（一个 placeholder warning 应该给什么 suggested_ops）
4. `confirm_first_slots: [operations]` 的语义你理解是什么——是指 LLM 在执行前让用户确认 operations 列表吗？
5. 端到端测试中如何模拟 LLM 消费 warnings 生成 operations（是否需要真实调 LLM，还是用 fixture 模拟）

等我确认后再动工。
````

---

## 6. Task Pack A · Reply Parser LLMification

### 6.1 背景与动机

**审计关键发现**（§7.A、Finding 0.8）：

- **Question generation 端**：`_build_probe_question`（`core/contracts/clarification_contract.py:1027-1046`）已 **LLM-first**——LLM 超时或失败才走 rule-based 模板。`_build_question`（`:996`）部分也是 LLM 驱动（split 路径接受 stage2 LLM 的 `stage2_clarification_question`）
- **Reply parsing 端（Task Pack A 的真正重心）**：
  - `core/parameter_negotiation.py:293 parse_parameter_negotiation_reply` —— **426 行完整的 regex 状态机**
  - `core/input_completion.py:402 parse_input_completion_reply` —— **~470 行，同样的 regex 模式**
- **五级标准化 fallback** 已在 `services/standardization_engine.py`，可复用

**影响**：论文 Chapter 5 Case C（自然语言多轮澄清）要求处理「小汽车」「下午高峰」「嗯好」「改成冬季夜间」等自然表达——**当前 regex 状态机处理不了**。

**Task Pack A 的本质**：把 reply parser 从 regex 驱动改为 LLM 主导 + regex fast path + 标准化 fallback。

### 6.2 设计决策

#### 6.2.1 解析层次（三层）

**Layer 1: Fast Path（Regex）**

对明显的简单回复（数字索引、"是/否"、"好的"、"第二个"等）用 regex 直接匹配——这类回复 LLM 多跑一次没必要且慢。

Fast path 判定规则：

- 单字或极短回复（≤3 字符）
- 纯数字（"1" / "2" / "第一个"）
- 明确的 confirm 词（"好" / "是" / "对" / "yes" / "ok"）
- 明确的 decline 词（"不" / "都不是" / "no"）

命中 fast path 直接返回结果，不调 LLM。

**Layer 2: LLM 主解析器（新）**

Fast path 不命中时调 LLM。Prompt 包含：

- 当前问题上下文（槽位名、槽位可选值、上一轮 agent 问的问题）
- 当前 AO 状态（已确认的参数、正在澄清的槽位）
- 约束违反历史（来自 Task Pack B 的 cumulative_constraint_violations）
- 用户的回复原文

LLM 返回 JSON：

```json
{
    "decision": "CONFIRMED | NONE_OF_ABOVE | PARTIAL_REPLY | AMBIGUOUS_REPLY",
    "slot_values": {"vehicle_type": "小汽车", "time_period": "下午高峰"},
    "confidence": 0.92,
    "evidence": "用户提到'小汽车'明确映射到 passenger_car；'下午高峰'对应 pm_peak"
}
```

**Layer 3: Standardization Fallback**

LLM 解析出的 slot_values 再经过 `StandardizationEngine` 的五级 cascade（exact → alias → fuzzy → LLM → default → abstain）做最终标准化。

这一层是**safety net**——即使 LLM 解析器"理解得差不多"，最终落到代码的值一定是通过标准化引擎的合法值。

#### 6.2.2 Confidence 阈值

- LLM confidence ≥ 0.85：直接采用
- 0.60 ≤ confidence < 0.85：采用但标记 `needs_confirmation=True`（下一轮让 agent 做一次轻量确认）
- confidence < 0.60：退化为 `AMBIGUOUS_REPLY`，agent 重发问题

阈值初始值参考 OASC 其他 LLM 节点的经验值，投稿前再基于实际表现调整。

#### 6.2.3 LLM 延迟控制

**审计风险点 1 提到**：reply 解析在用户对话关键路径，每轮多一次 LLM 往返（~500ms-2s）会影响体验。

**对策**：

- 用 qwen-plus（响应最快）而非 qwen-max
- Timeout = 5 秒（同 OASC 的 Stage 2 LLM）
- LLM 超时 → 回退到 regex 解析（原有逻辑保留）
- LLM 异常 → 回退到 regex 解析 + 告警 trace

#### 6.2.4 解析器模块化

**审计建议**（§7.A.4）：在 `parameter_negotiation.py` / `input_completion.py` 顶部加 LLM client 注入点。

本计划的具体做法：新建 `core/reply_parser_llm.py` 作为 LLM 解析器的独立模块，两个文件共享这一个 LLM 解析器。

#### 6.2.5 Fast path 决策逻辑的位置

Fast path 判定放在 `parameter_negotiation.py` / `input_completion.py` 各自的入口函数（`parse_parameter_negotiation_reply` / `parse_input_completion_reply`）里。不抽公共模块——因为两者的 fast path 判定规则略有差异（input_completion 的数字索引映射到选项，parameter_negotiation 的数字索引映射到 slot 序列）。

### 6.3 子任务拆分

#### A.1 新建 LLM Reply Parser 模块

**目标**：独立模块供两个解析器复用。

**改动**：新建 `core/reply_parser_llm.py`

```python
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, List

class ReplyDecision(str, Enum):
    CONFIRMED = "confirmed"
    NONE_OF_ABOVE = "none_of_above"
    PARTIAL_REPLY = "partial_reply"
    AMBIGUOUS_REPLY = "ambiguous_reply"
    PAUSE = "pause"  # 用户想暂停澄清

@dataclass
class ParsedReply:
    decision: ReplyDecision
    slot_values: Dict[str, str]
    confidence: float
    evidence: str
    needs_confirmation: bool = False

class LLMReplyParser:
    def __init__(self, llm_client=None):
        self.llm_client = llm_client or self._default_client()

    def parse(
        self,
        user_reply: str,
        context: Dict,  # 当前问题、槽位、AO 状态、约束历史
    ) -> Optional[ParsedReply]:
        """返回 None 表示 LLM 失败/超时，上层 fallback 到 regex。"""
        prompt = self._build_prompt(user_reply, context)
        try:
            resp = self.llm_client.call(prompt, timeout=5.0)
            return self._parse_response(resp)
        except (TimeoutError, Exception) as e:
            # 记录 trace 但不抛
            return None

    def _build_prompt(self, user_reply, context):
        # 构造含槽位、选项、AO 状态、约束历史的 prompt
        ...

    def _parse_response(self, resp) -> ParsedReply:
        # JSON 解析 + confidence 判定 + needs_confirmation 设置
        ...
```

#### A.2 改造 `parameter_negotiation.py`

**改动**：`core/parameter_negotiation.py:293 parse_parameter_negotiation_reply`

```python
def parse_parameter_negotiation_reply(user_reply, context, llm_parser=None):
    # Layer 1: Fast path（regex）
    fast_result = _try_fast_path(user_reply, context)
    if fast_result is not None:
        return fast_result

    # Layer 2: LLM 主解析
    if llm_parser is None:
        llm_parser = _get_default_llm_parser()

    llm_result = llm_parser.parse(user_reply, context)
    if llm_result is not None and llm_result.confidence >= 0.60:
        # Layer 3: Standardization fallback
        standardized = _standardize_slot_values(llm_result.slot_values)
        return _wrap_as_negotiation_decision(standardized, llm_result)

    # LLM 失败或低置信：回退到原有 regex 解析器
    return _legacy_regex_parse(user_reply, context)

def _try_fast_path(user_reply, context):
    """极短回复的 regex 快速路径。命中返回 decision，未命中返回 None。"""
    # 判定 1：纯数字 → 索引
    # 判定 2：confirm 词
    # 判定 3：decline 词
    ...

def _legacy_regex_parse(user_reply, context):
    """原有的 426 行 regex 状态机，保留作为最终 fallback。"""
    # 现有的 parse 逻辑原封不动
    ...
```

**关键**：原有 regex 状态机 **保留不删**，作为最终 fallback。只是主路径改为 LLM 优先。

#### A.3 改造 `input_completion.py`

**改动**：`core/input_completion.py:402 parse_input_completion_reply`

同 A.2 的模式，不赘述。

#### A.4 清理 `_build_question` 的硬编码模板

**改动**：`core/contracts/clarification_contract.py:996 _build_question`

当前逻辑：

```python
def _build_question(self, tool_name, slot_name, llm_question=None):
    if llm_question:
        return llm_question
    # Rule-based fallback（~6 个 if 分支）
    if tool_name == "query_emission_factors" and slot_name == "vehicle_type":
        return "请问您想查询哪种车型的排放因子？"
    # ... 更多分支
    # 兜底
    return "我还需要补充一个关键参数后才能继续..."
```

改为：

```python
def _build_question(self, tool_name, slot_name, llm_question=None):
    if llm_question:
        return llm_question
    # LLM-first：尝试让 LLM 生成问题
    llm_result = self._run_question_llm(tool_name, slot_name)
    if llm_result:
        return llm_result
    # 最终 fallback（兜底文案）
    return "我还需要补充一个关键参数后才能继续..."
```

删除 6 个硬编码 `if tool_name == "..." and slot_name == "..."` 分支。`_run_question_llm` 复用 `_run_probe_question_llm` 的实现模式。

#### A.5 Prompt 模板设计

**目标**：为 A.1 的 LLM Reply Parser 设计稳定的 prompt 模板。

**新增文件**：`config/prompts/reply_parser.yaml`（或加到现有 prompt 配置）

Prompt 模板示例（中文）：

```
你是一个对话理解助手。上一轮 agent 问了用户一个澄清问题，现在需要解析用户的回复。

## 上下文
- 当前工具：{tool_name}
- 正在澄清的槽位：{slot_name}
- 槽位的候选值（如有）：{candidate_values}
- 已确认的参数：{confirmed_params}
- 历史约束违反（如果有）：{constraint_violations}

## Agent 上一轮问的问题
{agent_question}

## 用户的回复
{user_reply}

## 任务
解析用户回复，返回以下 JSON：
{
    "decision": "CONFIRMED | NONE_OF_ABOVE | PARTIAL_REPLY | AMBIGUOUS_REPLY | PAUSE",
    "slot_values": {{"<槽位名>": "<识别的值>"}},
    "confidence": <0.0-1.0>,
    "evidence": "<你识别的理由>"
}

## 规则
- CONFIRMED：用户明确给出了需要的槽位值
- NONE_OF_ABOVE：用户表达"都不是"或"都不要"
- PARTIAL_REPLY：用户只回答了部分槽位
- AMBIGUOUS_REPLY：用户回复不清楚或与上下文无关
- PAUSE：用户想停止澄清（"算了"、"不用了"、"先不要"）
```

**要点**：

- Prompt 中暴露 AO 的已确认参数和约束历史——这是 Task Pack B 的成果能被 A 利用的地方
- 返回固定 JSON schema，便于稳定解析
- 提供明确的 decision 定义

#### A.6 Fast Path 规则实现

**改动**：在 `parameter_negotiation.py` 和 `input_completion.py` 各自实现 `_try_fast_path`。

示例规则（parameter_negotiation）：

```python
FAST_PATH_CONFIRM_WORDS = {"好", "是", "对", "yes", "ok", "嗯", "行"}
FAST_PATH_DECLINE_WORDS = {"不", "都不是", "都不要", "no"}

def _try_fast_path(user_reply, context):
    reply = user_reply.strip().lower()
    if len(reply) <= 3:
        # 数字索引
        if reply.isdigit():
            idx = int(reply) - 1
            return _index_to_decision(idx, context)
        # Confirm
        if reply in FAST_PATH_CONFIRM_WORDS:
            return _build_confirm_decision(context)
        # Decline
        if reply in FAST_PATH_DECLINE_WORDS:
            return _build_none_decision(context)
    return None
```

#### A.7 Coupling to Task Pack B 验证

**目标**：验证 LLM Reply Parser 能正确利用 Task Pack B 的 `cumulative_constraint_violations`。

**测试场景**：

1. 用户触发约束违反（比如摩托车+快速路）→ B 写入 memory
2. 下一轮用户用模糊表达（比如"换成另一个车型"）
3. LLM Reply Parser 的 context 应包含上一轮的违反历史
4. LLM 基于违反历史判断用户是在"避开"之前的组合，给出合理的 slot_values 解析

**测试文件**：`tests/test_reply_parser_with_constraint_context.py`

#### A.8 回归测试

**新增测试**：

`tests/test_llm_reply_parser.py`：

- LLM parser 的基本功能（confirm / none / partial / ambiguous）
- Confidence 阈值行为
- LLM 超时 fallback

`tests/test_reply_parser_fast_path.py`：

- 6 个 fast path 判定规则各有用例
- Fast path 命中不调 LLM

`tests/test_parameter_negotiation_llm_integration.py`：

- 原有 regex 解析器的所有测试用例仍通过（legacy fallback 保留）
- 新 LLM 路径的集成测试

### 6.4 验收标准

- ✅ `core/reply_parser_llm.py` 新模块就位
- ✅ `parameter_negotiation.py` / `input_completion.py` 改造完成，三层解析（fast path → LLM → regex fallback）
- ✅ `_build_question` 硬编码模板删除
- ✅ `config/prompts/reply_parser.yaml`（或等价配置）就位
- ✅ `tests/test_llm_reply_parser.py` / `test_reply_parser_fast_path.py` / `test_parameter_negotiation_llm_integration.py` 通过
- ✅ `tests/test_reply_parser_with_constraint_context.py`（Coupling to B）通过
- ✅ 原有 `tests/test_parameter_negotiation*.py` / `test_input_completion*.py`（如果存在）无 regression
- ✅ 手动跑论文 Chapter 5 Case C 场景（「小汽车」「下午高峰」「嗯好」「改成冬季夜间」），每轮都应被 LLM 正确解析
- ✅ LLM 超时或失败时 regex fallback 正常工作
- ✅ commit message: `feat(reply-parser): LLMify parameter_negotiation and input_completion with regex fallback`

### 6.5 风险点

1. **LLM 延迟影响**：每轮多一次 LLM 往返。实测若体验受损，考虑在 fast path 增加更多判定规则
2. **LLM 的"过度宽容"**：LLM 可能把模糊回复强行解析为 confirm，导致错误参数。confidence 阈值 + `needs_confirmation` 机制是对策，但需要在实测中调阈值
3. **Prompt 稳定性**：LLM 返回非 JSON / 字段缺失的情况。需要 robust JSON 解析 + schema 校验
4. **Fast path 规则偏差**：fast path 规则（尤其数字索引）在 input_completion 和 parameter_negotiation 语义不同。测试覆盖要完整
5. **Legacy regex 的维护成本**：保留 legacy regex 作为 fallback，代码量不减反增。长远可能需要评估是否彻底删掉——但本 Pack 不做
6. **Coupling to B**：Task Pack A 的 prompt 依赖 B 的约束历史。B 的输出格式变化会影响 A。需要在 B 输出时锁定格式

### 6.6 Codex Prompt 草稿

````markdown
# 任务：Task Pack A · Reply Parser LLMification

## 背景

论文 Chapter 5 Case C（自然语言多轮澄清）要求处理「小汽车」「下午高峰」「嗯好」「改成冬季夜间」等自然表达。当前 `parameter_negotiation.py` / `input_completion.py` 是两套 regex 状态机（共 ~900 行），无法处理这些表达。

本任务实现三层解析：Fast Path（regex）→ LLM 主解析 → Legacy regex fallback。同时清理 `_build_question` 的硬编码模板。

**前置条件**：Task Pack B 已合入（LLM parser 的 prompt 需要 cumulative_constraint_violations 字段）。

## 设计

- **Layer 1 Fast Path**：极短回复（≤3 字符）/ 纯数字索引 / confirm-decline 关键词，直接 regex 判定
- **Layer 2 LLM 主解析**：fast path 未命中时调 LLM，返回 JSON { decision / slot_values / confidence / evidence }
- **Layer 3 Standardization Fallback**：LLM 解析的 slot_values 经五级标准化引擎处理
- **Confidence 阈值**：≥0.85 直接采用；0.60-0.85 标记 needs_confirmation；<0.60 AMBIGUOUS_REPLY
- **LLM 延迟**：qwen-plus + timeout=5s；超时 fallback 到 legacy regex
- **Legacy regex 保留**：不删除现有 426 + 470 行的 regex 状态机，作为最终 fallback

## 具体改动（8 个子任务）

### A.1 新建 LLM Reply Parser 模块
新建 `core/reply_parser_llm.py`，含 `LLMReplyParser` 类、`ParsedReply` dataclass、`ReplyDecision` 枚举。

### A.2 改造 parameter_negotiation.py
`core/parameter_negotiation.py:293 parse_parameter_negotiation_reply` 改为三层解析。原有 regex 逻辑保留为 `_legacy_regex_parse`。

### A.3 改造 input_completion.py
`core/input_completion.py:402 parse_input_completion_reply` 同上。

### A.4 清理 _build_question 硬编码模板
`core/contracts/clarification_contract.py:996 _build_question` 删除 6 个硬编码 `if tool_name and slot_name` 分支。改为 LLM-first + 兜底文案。`_run_question_llm` 复用 `_run_probe_question_llm` 的实现模式。

### A.5 Prompt 模板设计
新建 `config/prompts/reply_parser.yaml`（或加到现有 prompt 配置）。Prompt 暴露 AO 已确认参数 + 约束违反历史。返回固定 JSON schema。

### A.6 Fast Path 规则实现
`_try_fast_path` 各自在两个解析器里实现。规则包括数字索引 / confirm 词 / decline 词。

### A.7 Coupling to Task Pack B 验证
新增 `tests/test_reply_parser_with_constraint_context.py`：模拟约束违反触发 → 下一轮用户模糊回复 → 验证 LLM parser 的 context 含违反历史。

### A.8 回归测试
新增：
- `tests/test_llm_reply_parser.py`
- `tests/test_reply_parser_fast_path.py`
- `tests/test_parameter_negotiation_llm_integration.py`

## 验收标准

- 8 个子任务全部完成
- 新测试全部通过
- 原有 regex 测试无 regression
- 手动跑 Case C 对话（「小汽车」「下午高峰」「嗯好」「改成冬季夜间」），trace 显示每轮都经过 LLM parser
- LLM 超时场景（人为 mock 超时）regex fallback 正常工作
- commit message: `feat(reply-parser): LLMify parameter_negotiation and input_completion with regex fallback`

## 约束

- 原有 regex 状态机 **保留**，作为 fallback
- Fast path 规则差异化（parameter_negotiation 和 input_completion 各自规则）
- LLM 客户端用 qwen-plus + timeout=5s
- Confidence 阈值初始值按本任务描述（0.60 / 0.85），未来可调

## 首轮回复

动手前请 ACK 并列出：
1. `core/parameter_negotiation.py` 和 `core/input_completion.py` 当前的公共入口点和私有 helper 列表
2. `_build_probe_question` / `_run_probe_question_llm` 的现有实现模式（作为 `_run_question_llm` 的参考模板）
3. `services/llm_client.py` 中 qwen-plus 的调用接口（是否已有 timeout / JSON mode 支持）
4. Task Pack B 的 `cumulative_constraint_violations` 在 memory 中的字段结构（作为 prompt 的输入）
5. 原有 regex 测试文件是否存在（`tests/test_parameter_negotiation*.py` / `test_input_completion*.py`）

等我确认后再动工。
````

---


## 7. Task Pack E-剩余 · 硬编码解耦与可扩展性收尾

### 7.1 背景与动机

**审计发现**（§4.3、§8）：除了 E-8.1 已处理的双 YAML 合并，还有 4 处硬编码（§8.2-8.5）影响可扩展性：

1. **`_snapshot_to_tool_args`（§8.2）**：`core/governed_router.py:427-533` 对 6 个工具各一个 `if tool_name == "..."` 分支。加新工具必须改此 switch
2. **`ao_manager` 关键词（§8.3）**：`core/ao_manager.py:73-87` 的多步信号模式 + `:566-586` 的工具关键词映射。加新工具可能需要加关键词
3. **NaiveRouter 白名单（§8.4）**：`core/naive_router.py:28-36 NAIVE_TOOL_NAMES` 硬编码 7 个工具
4. **`runtime_defaults`（§8.5）**：`core/contracts/runtime_defaults.py:10-14` 的 `_RUNTIME_DEFAULTS`——**这一项保留**（设计上故意保留的 runtime vs YAML 分离）

**本 Task Pack 的本质**：通过 schema 扩展 + 通用 loop + YAML 字段迁移，把 3 处硬编码解耦，让 Task Pack E 的 "加新工具只需改 YAML" 这一验收目标真正达到。

### 7.2 设计决策

#### 7.2.1 `_snapshot_to_tool_args` 的声明化

**方案**：在 `tool_contracts.yaml` 的 parameter schema 中加 `type_coercion` 字段，用通用 loop 替代 6 个硬编码分支。

YAML 扩展：

```yaml
tools:
  query_emission_factors:
    parameters:
      pollutants:
        required: false
        schema: { type: array, items: { type: string } }
        type_coercion: as_list   # 新增
      model_year:
        required: true
        schema: { type: integer }
        type_coercion: safe_int  # 新增
      vehicle_type:
        required: true
        schema: { type: string }
        # 无 type_coercion = 不做 coerce
```

代码简化：

```python
def _snapshot_to_tool_args(tool_name, snapshot, *, allow_factor_year_default=False):
    tool_spec = get_tool_contract_registry().get_contract(tool_name)
    args = {}
    for param_name, param_info in tool_spec["parameters"].items():
        value = _read_slot(snapshot, param_name)
        if value is None:
            continue
        coerced = _apply_coercion(value, param_info.get("type_coercion"))
        if coerced is not None:
            args[param_name] = coerced

    # 特殊 post-processing hook（保留，必要）
    if allow_factor_year_default and tool_name == "query_emission_factors":
        args.setdefault("model_year", _get_default_model_year())

    return args
```

**特殊处理保留**：`allow_factor_year_default` 和 `pollutant_list_fallback` 的单元素解包不适合粗暴声明化，作为显式 post-processing hook。

**支持的 coercion 函数**（在 `core/governed_router.py` 或独立模块定义）：

- `as_list`：单值包成 list
- `safe_int`：转 int，失败返回 None
- `safe_float`：转 float，失败返回 None
- `as_string`：强制转 str
- `preserve`（默认）：不做 coerce

#### 7.2.2 `ao_manager` 关键词迁移

**方案**：把工具关键词从硬编码迁到 `tool_contracts.yaml`。

YAML 扩展：

```yaml
tools:
  calculate_dispersion:
    continuation_keywords: [扩散, dispersion, 浓度, concentration, raster]  # 已有
    completion_keywords: [扩散, dispersion, 浓度]  # 新增
```

`completion_keywords` 作为 `_extract_implied_tools` 的数据源。

**`MULTI_STEP_SIGNAL_PATTERNS` 保留**（通用语言模式"再"、"然后"、"接着"等），但抽到独立模块 `core/ao_manager_keywords.py` 增强可读性。

#### 7.2.3 NaiveRouter 白名单声明化

**方案**：在 `tool_contracts.yaml` 工具级加 `available_in_naive: true/false`（默认 true）。

```yaml
tools:
  query_emission_factors:
    available_in_naive: true  # 默认可以不写

  analyze_file:
    available_in_naive: false  # 复杂工具不进 naive

  compare_scenarios:
    available_in_naive: false
```

`NaiveRouter._load_naive_tool_definitions`（`core/naive_router.py:107-115`）改为从 YAML 过滤。

### 7.3 子任务拆分

#### E-剩余.1 `_snapshot_to_tool_args` 声明化

**目标**：替换 6 个硬编码 if 分支为通用 loop。

**改动**：

- `config/tool_contracts.yaml`：为 6 个工具的 parameter 加 `type_coercion` 字段
- `tools/contract_loader.py`：`ToolContractRegistry` 支持读取 `type_coercion` 字段
- 新建 `core/snapshot_coercion.py`：定义 5 个 coercion 函数（`as_list` / `safe_int` / `safe_float` / `as_string` / `preserve`）
- `core/governed_router.py:427-533`：`_snapshot_to_tool_args` 改为通用 loop
- `tests/test_snapshot_to_tool_args.py`：原有 UT（审计 §8.2 提到有 12 个）全部保留，新增 coerce 规则单元测试

**验收关键**：原有 12 个 UT 全部 pass（行为 100% 一致）。

#### E-剩余.2 `ao_manager` 关键词迁移

**目标**：工具关键词从硬编码迁到 YAML。

**改动**：

- `config/tool_contracts.yaml`：为每个工具加 `completion_keywords` 字段（值来自 `ao_manager.py:566-586` 当前硬编码）
- `tools/contract_loader.py`：支持读取 `completion_keywords`，提供 getter `get_completion_keywords(tool_name)`
- `core/ao_manager.py:566-586 _extract_implied_tools`：改为从 YAML 读取
- 新建 `core/ao_manager_keywords.py`：把 `MULTI_STEP_SIGNAL_PATTERNS`（通用语言模式）抽到独立模块
- `tests/test_ao_manager_keyword_extraction.py`：更新测试，保持行为一致

#### E-剩余.3 NaiveRouter 白名单声明化

**目标**：`NAIVE_TOOL_NAMES` 硬编码迁到 YAML。

**改动**：

- `config/tool_contracts.yaml`：为 `analyze_file` 和 `compare_scenarios` 加 `available_in_naive: false`（其他工具默认 true，可不写）
- `tools/contract_loader.py`：支持读取 `available_in_naive`，提供 getter `get_naive_available_tools()`
- `core/naive_router.py:28-36`：删除 `NAIVE_TOOL_NAMES` 硬编码
- `core/naive_router.py:107-115`：`_load_naive_tool_definitions` 改为过滤 `available_in_naive`
- `tests/test_naive_router_tools.py`：更新测试

#### E-剩余.4 `runtime_defaults.py` 加 CI check

**目标**：§8.5 保留机制，但加漂移检测。

**改动**：

- `core/contracts/runtime_defaults.py`：加一个模块级 `_check_consistency_with_yaml()` 函数，在 import 时如果 `_RUNTIME_DEFAULTS` 与 YAML `defaults` 有差异则打 log
- 新增 `tests/test_runtime_defaults_consistency.py`：CI 里跑，当前 `_RUNTIME_DEFAULTS = {"query_emission_factors": {"model_year": 2020}}`，YAML defaults 里也是 2020——一致则通过；不一致则 log 警告但不 fail test（设计上允许漂移）

**注释**：在 `runtime_defaults.py` 源码里加明确的 rationale 注释（§8.5 审计已引用源码注释）。

#### E-剩余.5 "加新工具"文档化

**目标**：产出一份 dev docs，明确加新工具需要做的事。

**改动**：新建 `docs/dev/adding_a_new_tool.md`

内容：

```markdown
# 加一个新工具的完整流程

完成 Task Pack E-剩余 之后，加新工具只需要做以下事情：

## 必做

1. 实现工具类 `tools/<tool_name>.py`，继承 `BaseTool`
2. 在 `config/tool_contracts.yaml` 声明完整 tool spec（参考 `query_emission_factors` 条目）
3. 在 `tools/registry.py::init_tools` 加一行 register

## 不需要做

- ❌ 不需要改 `core/governed_router.py:_snapshot_to_tool_args`（type_coercion 在 YAML 声明）
- ❌ 不需要改 `core/ao_manager.py:_extract_implied_tools`（completion_keywords 在 YAML 声明）
- ❌ 不需要改 `core/naive_router.py:NAIVE_TOOL_NAMES`（available_in_naive 在 YAML 声明）
- ❌ 不需要改 assembler、contract、session 等上层代码

## 验证

跑 `tests/test_tool_extensibility.py`（本 Pack 提供）验证新工具能被所有层正确识别。
```

#### E-剩余.6 Extensibility 验证测试

**目标**：设计一个"模拟加新工具"的集成测试，验证声明式路径真的够用。

**改动**：新增 `tests/test_tool_extensibility.py`

```python
def test_adding_tool_through_yaml_only():
    """验证加新工具只需改 YAML + 新工具文件 + registry.py。"""
    # 1. 在临时 YAML 中添加一个 dummy 工具声明
    # 2. 创建 DummyTool 类（继承 BaseTool）
    # 3. 动态 register 到 registry
    # 4. 验证以下都能正确识别：
    #    - TOOL_DEFINITIONS 包含 dummy
    #    - TOOL_GRAPH 包含 dummy 的 consumes/produces
    #    - _snapshot_to_tool_args(dummy, ...) 能基于 type_coercion 正确 coerce 参数
    #    - _extract_implied_tools 能识别 dummy 的 completion_keywords
    #    - NaiveRouter 根据 available_in_naive 正确过滤
    # 5. 清理：移除 dummy 注册，还原 YAML
```

这个测试是 **Task Pack E 的验收硬证据**——只要它过，"加新工具只需改 YAML" 这个 claim 就真的成立。

### 7.4 验收标准

- ✅ E-剩余.1 ~ E-剩余.6 全部完成
- ✅ `tests/test_snapshot_to_tool_args.py` 原 12 UT 全部 pass
- ✅ `tests/test_ao_manager_keyword_extraction.py` pass
- ✅ `tests/test_naive_router_tools.py` pass
- ✅ `tests/test_runtime_defaults_consistency.py` pass
- ✅ `tests/test_tool_extensibility.py`（新）pass——这是 E 的最终验收
- ✅ 原有 tests 无 regression
- ✅ `docs/dev/adding_a_new_tool.md` 就位
- ✅ commit message: `refactor(extensibility): declarative tool registration (snapshot coercion + completion keywords + naive whitelist)`

### 7.5 风险点

1. **`_snapshot_to_tool_args` 特殊逻辑**：`allow_factor_year_default` 等 post-processing 不要误声明化
2. **YAML schema 扩展的向后兼容**：新增 `type_coercion` / `completion_keywords` / `available_in_naive` 字段，确保不写这些字段时有合理默认行为
3. **`ao_manager_keywords.py` 抽取**：`MULTI_STEP_SIGNAL_PATTERNS` 不是 tool-level，抽到独立模块时保持原逻辑
4. **`test_tool_extensibility.py` 的 cleanup**：测试结束要还原 YAML 和 registry，否则污染后续 test

### 7.6 Codex Prompt 草稿

````markdown
# 任务：Task Pack E-剩余 · 硬编码解耦与可扩展性收尾

## 背景

Task Pack E-8.1（双 YAML 合并）已完成，但仍有 3 处硬编码影响可扩展性：
- `_snapshot_to_tool_args`（6 if 分支）
- `ao_manager._extract_implied_tools`（工具关键词硬编码）
- `NaiveRouter NAIVE_TOOL_NAMES`（7 工具白名单）

本任务通过 YAML schema 扩展 + 通用 loop 替换完成解耦。目标：加新工具只需改 YAML + 新工具文件 + `tools/registry.py` 一行 register。

**前置条件**：Task Pack E-8.1 + C+D 已合入。

## 具体改动（6 个子任务）

### E-剩余.1 _snapshot_to_tool_args 声明化
- 在 `config/tool_contracts.yaml` 的 parameter schema 加 `type_coercion` 字段（5 种值：as_list / safe_int / safe_float / as_string / preserve）
- `tools/contract_loader.py` 支持读取
- 新建 `core/snapshot_coercion.py` 定义 5 个 coercion 函数
- `core/governed_router.py:427-533 _snapshot_to_tool_args` 改为通用 loop
- **保留** `allow_factor_year_default` 等特殊 post-processing hook

### E-剩余.2 ao_manager 关键词迁移
- 在 `config/tool_contracts.yaml` 每个工具加 `completion_keywords` 字段
- `tools/contract_loader.py` 加 `get_completion_keywords(tool_name)` getter
- `core/ao_manager.py:566-586 _extract_implied_tools` 改为从 YAML 读
- 新建 `core/ao_manager_keywords.py`，把 `MULTI_STEP_SIGNAL_PATTERNS` 抽出去

### E-剩余.3 NaiveRouter 白名单声明化
- 在 `config/tool_contracts.yaml` 为 `analyze_file` / `compare_scenarios` 加 `available_in_naive: false`
- `tools/contract_loader.py` 加 `get_naive_available_tools()` getter
- `core/naive_router.py:28-36` 删除 `NAIVE_TOOL_NAMES`；`:107-115 _load_naive_tool_definitions` 改为 YAML 过滤

### E-剩余.4 runtime_defaults 加 CI check
- `core/contracts/runtime_defaults.py` 加 `_check_consistency_with_yaml()` 函数，log 不一致
- 新建 `tests/test_runtime_defaults_consistency.py`
- 不做强制同步（设计上允许漂移）

### E-剩余.5 加新工具流程文档
新建 `docs/dev/adding_a_new_tool.md`，明确"加新工具只需改三处"。

### E-剩余.6 Extensibility 验证测试
新建 `tests/test_tool_extensibility.py`：动态注册一个 DummyTool，验证所有层都能正确识别。这是 Task Pack E 的最终验收。

## 验收标准

- 6 个子任务全部完成
- 原有相关 tests 全部 pass（无 regression）
- `tests/test_tool_extensibility.py` 通过——这是硬证据
- `docs/dev/adding_a_new_tool.md` 就位
- commit message: `refactor(extensibility): declarative tool registration (snapshot coercion + completion keywords + naive whitelist)`

## 约束

- 保留 `_RUNTIME_DEFAULTS` 机制（§8.5 设计决策）
- 保留 `allow_factor_year_default` 等特殊 post-processing hook
- `MULTI_STEP_SIGNAL_PATTERNS` 保留但抽到独立模块

## 首轮回复

动手前请 ACK 并列出：
1. `core/governed_router.py:427-533` 的 6 个 if 分支各自处理什么工具、什么参数、用什么 coerce 逻辑
2. `core/ao_manager.py:566-586` 的工具关键词映射完整清单（哪些工具映射到哪些中英文关键词）
3. `NAIVE_TOOL_NAMES` 的当前 7 个工具
4. 你对 `test_tool_extensibility.py` 的 cleanup 策略的想法（pytest fixture / monkeypatch / 独立 yaml）
5. `tests/test_snapshot_to_tool_args.py` 是否已存在（审计 §8.2 提到 12 个 UT），以及这些 UT 的具体场景

等我确认后再动工。
````

---

## 8. Final Benchmark Run · Phase 2 收尾基准测试

### 8.1 背景

Phase 2 完成后需要跑一次完整 benchmark，作为：

1. 论文 Chapter 6.2（Benchmark-Based Evaluation）的数据源
2. Phase 2 整体质量的客观验证
3. User study 准备期的 baseline

### 8.2 子任务

#### Final.1 运行完整 Benchmark

**改动**：执行 `evaluation/eval_end2end.py` 全量

- 主 180 任务
- Held-out 75 任务
- Ablation 组（NaiveRouter vs +AO vs +Governance full）

#### Final.2 基线快照对比

**改动**：对比 pre-Migration / post-Migration / post-Phase-2 三份基线

**产出**：`data/benchmarks/phase2_benchmark_report_<date>.md`

- 整体完成率三阶段对比
- 每个 Task Pack 合入后的局部提升
- Held-out 任务表现
- 失败模式分类

#### Final.3 失败模式分析

**目标**：识别 Phase 2 完成后仍然存在的失败模式，为论文 Chapter 6.5（Failure Analysis）提供材料。

**改动**：

- 跑一次 benchmark 后，手动 trace review 所有 failed 任务
- 按失败原因分类（LLM 理解错误 / 约束检测遗漏 / 工具执行错误 / 其他）
- 产出 `docs/phase2_failure_analysis.md`

### 8.3 验收标准

- ✅ Benchmark 全量跑通
- ✅ 三阶段基线对比报告就位
- ✅ Failure mode 分类完成
- ✅ commit message: `docs(benchmark): phase 2 final benchmark report`

### 8.4 风险点

1. **Benchmark 时长**：全量跑一次预计几小时到一天
2. **API 费用**：255 个任务的 LLM 调用开销
3. **结果可信度**：若某些任务 pass/fail 翻转，需要逐个 trace 分析而非纯统计

### 8.5 无独立 Codex prompt

本 task 不是 code change，而是 pipeline 执行 + 报告撰写，由你手动跑 + Claude 协助分析报告。

---

## 9. Phase 2 完成后的延续工作（预览）

**不在本开发计划范围，仅列出让你知道 Phase 2 之后的事情**。

### 9.1 User Study 前的加固期

Phase 2 完成后，user study 启动前需要：

- **Prompt 打磨**：针对 LLM clarification / reply parser 的 prompt 基于实际对话微调
- **错误处理的用户可读性**：user study 被试会碰到 agent 出错，错误消息需要友好
- **Soak testing**：跑 50-100 real-user-like session，修掉随机出现的 edge case
- **响应延迟优化**：观察 Phase 2 完成后的端到端延迟，必要时调 LLM timeout / fast path 规则

### 9.2 论文写作期的代码配合

论文写作过程中可能触发小幅代码调整：

- Chapter 5 Case study 在代码里复现时发现某个 case 不稳定
- Chapter 4 写架构细节时发现代码实现与描述需要对齐
- 新增或修改 trace rendering 让 case study 的 trace 更清晰可读

### 9.3 User Study 准备

独立一个 workstream，预计 2-3 周：

- Protocol 设计（between-subjects 或 within-subjects）
- 任务集设计（5-10 个任务覆盖 S1-S4 场景）
- 问卷设计（trust / interpretability / interaction quality / cognitive load / preference 五维度）
- 招募 24 人（交通 / 环境 / 大气 / 城规相关专业研究生）
- 伦理审批（如果学校要求）

### 9.4 Expert Evaluation 准备

并行进行：

- 专家招募 5-8 人（交通环境方向教授 / 高年级 PhD / 资深工程师）
- 评分维度定义（准确性 / 完整性 / 可解释性 / 合理性）
- Session trace 盲审材料准备

### 9.5 投稿前的最后一轮 benchmark

所有 case study 完成、所有 prompt 打磨完成后，再跑一次完整 benchmark 作为论文最终数据源。

---

## 10. 执行 Checklist 总表

用这张表跟踪整个 Phase 2 进度。

| Task Pack | 状态 | 关键交付 | 依赖 |
|---|---|---|---|
| F-bugfix | ⬜ | `restore_persisted_state` 修复 + 4 测试用例 | 无 |
| F-main | ⬜ | 生产路径统一到 GovernedRouter | F-bugfix |
| E-8.1 | ⬜ | 双 YAML 合并 | F-main |
| B | ⬜ | Constraint violation writer pipeline | F-main |
| C+D | ⬜ | Data quality pipeline（analyze_file 扩维度 + clean_dataframe 新工具） | E-8.1 |
| A | ⬜ | Reply parser LLMification | B |
| E-剩余 | ⬜ | 硬编码解耦（snapshot / ao_keywords / naive 白名单） | E-8.1、C+D |
| Final benchmark | ⬜ | 完整 benchmark + 对比报告 | A + E-剩余 |

---

## 11. 文档修订历史

- **v1.0**（2026-04-23，本版本）：基于 `docs/codebase_audit_phase2_prep.md`（commit `90905c3`）起草

---

## 附录 A · 术语与缩写

- **AO**：Analytical Objective，对话目标对象（`core/analytical_objective.py:198`）
- **OASC**：Objective-Aware Stage Classifier，AO 分类驱动的 contract
- **Task Pack**：Phase 2 的工作组织单元（A/B/C/D/E/F）
- **Migration**：Task Pack F，指"生产路径统一到 GovernedRouter"的架构迁移
- **Legacy AO**：Memory 中 `from_dict` 时为空 `ao_history` 合成的占位 AO（Phase 2 将删除此 fallback）
- **Split contract**：`IntentResolutionContract` / `StanceResolutionContract` / `ExecutionReadinessContract` 三个细分契约（对应 `ClarificationContract`）

---

## 附录 B · Critical Path 图

```
Task Pack F-bugfix ─→ Task Pack F-main ─┬→ Task Pack E-8.1 ─→ Task Pack C+D ─┐
                                         │                                     │
                                         └→ Task Pack B ──────→ Task Pack A ──┤
                                                                               │
                                                                               ▼
                                                              Task Pack E-剩余
                                                                               │
                                                                               ▼
                                                            Final Benchmark Run
```

**最长路径**：F-bugfix → F-main → B → A → E-剩余 → Final（5 级）

**最短并行组合**：F 和 B 的前两步能交织（F-bugfix 先，F-main 和 B 可考虑并行——但 B 的完整效果依赖 F-main，建议仍按 critical path 串行）

---

**—— 开发计划 v1.0 结束 ——**
