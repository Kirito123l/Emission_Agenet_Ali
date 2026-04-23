# EmissionAgent Codebase Audit for Phase 2 Planning

**审计日期**：2026-04-23
**审计人**：Claude (independent audit — 不依赖历史交接文档作为真相源)
**目标**：给 Phase 2 规划提供代码实情基线
**约束**：不修改代码、不跑 benchmark、每条陈述附 `file:line` 证据

---

## Section 0. Critical Findings

本节 ≤10 条，按严重程度降序，每条附 severity / file:line / 对 Task Pack 的影响。

| # | Finding | Severity | Evidence | Task Pack 影响 |
|---|---|---|---|---|
| **0.1** | **生产代码中 `fact_memory.append_constraint_violation` 无任何 writer**——约束违反只进入 trace，不进入 memory；`constraint_violations_seen` / `cumulative_constraint_violations` / AO 的 `constraint_violations` 字段在两条路径下**恒为空** | 🔴 Critical | `core/memory.py:195` 定义；`grep` 生产代码无调用点；UnifiedRouter `_evaluate_cross_constraint_preflight` (`core/router.py:2165`) 只写 trace/state；`services/standardization_engine.py:643-666` 只抛异常 | **B 从零**：Task Pack B 是"从零搭建 writer pipeline + 读出到 prompt"，而非"激活已有机制" |
| **0.2** | **UnifiedRouter 路径下 AO 系统完全不运行**——`grep "AOManager\|ao_manager\|analytical_objective\|AnalyticalObjective" core/router.py` 返回 **0 命中**；A 路径下 assembler 渲染的 AO block 因 `fact_memory.ao_history` 为空而是空架子 | 🔴 Critical | `core/router.py` 无 AO import；`core/governed_router.py:39` 是 AOManager 唯一构造处；`core/assembler.py:385 _build_ao_session_state_block` 读空列表 | **F 必要性**：Migration Task Pack 的首要动因——AO 必须随生产路径统一才能真正生效 |
| **0.3** | **GovernedRouter restart 硬编码丢失 split contract**——`restore_persisted_state` 无条件重建 `[oasc, clarification, dependency]` 三契约，忽略 `enable_contract_split` | 🔴 Critical | `core/governed_router.py:552-556` | **F 阻塞**：Migration Task Pack 必须修此 bug，否则"跨进程 restart 后 contract 链收缩"会持续发生 |
| **0.4** | **`DependencyContract` 是 13 行空壳**，且其 flag `ENABLE_DEPENDENCY_CONTRACT` 无 reader；`BaseContract.before_turn/after_turn` 默认 no-op，等于每轮无效调用两次 | 🟡 High | `core/contracts/dependency_contract.py:1-13`；`config.py:153-155`；`grep "enable_dependency_contract"` 除 config.py 外无命中 | **E 观察**：扩展性重构时应决定激活或删除；非阻塞 |
| **0.5** | **前端 `governed_v2` 不可选**——`web/index.html:786-787` 的 `<select>` 只有 `full` 和 `naive`，`web/app.js:5, 162` 三元表达式把一切非 `naive` 强制为 `full` | 🟢 Medium | `web/index.html:786-787`；`web/app.js:5, 162` | **F 简化**：Migration 只需让 `full` 内部走 GovernedRouter；不必改前端下拉选单即可收敛 |
| **0.6** | **两份 YAML 对 tool 属性的分工混乱**——`config/tool_contracts.yaml` 负责 parameters/dependencies/readiness；`config/unified_mappings.yaml` 负责 required_slots/optional_slots/defaults/clarification_followup_slots/confirm_first_slots；同一 tool 的 schema 在两处声明 | 🟡 High | `core/contracts/stance_resolution_contract.py:12, 177-186` 读 `unified_mappings.yaml`；`tools/contract_loader.py:*` 读 `tool_contracts.yaml` | **E 重构**：Task Pack E 的核心工作是两份 YAML 的 tool 段合并，非纯声明式调整 |
| **0.7** | **`analyze_file` 已有 `data_quality_warnings` 字段但维度单一**——只检查 road_type 下的 speed 异常；Task Pack C 是"扩维度"而非"从零加字段" | 🟢 Medium | `tools/file_analyzer.py:262 _build_data_quality_warnings`、`:303, 322, 344` 现有检测只围绕 road_type vs avg_speed_kph 一致性 | **C 工作性质**：扩字段 + 复用测试基础设施（`tests/test_file_analyzer_targeted_enhancements.py` 已在） |
| **0.8** | **Task Pack A 的实际重心是 reply 解析而非 question 生成**——`_build_probe_question` 已经 LLM-first (`core/contracts/clarification_contract.py:1027-1046`)，但 `parse_parameter_negotiation_reply` 和 `parse_input_completion_reply` 是完整的 regex-state-machine | 🟢 Medium | `core/parameter_negotiation.py:293`；`core/input_completion.py:402`；`_run_probe_question_llm:1047` | **A 范围纠偏**：Task Pack A 的"规则→LLM"主要是 reply parser，question generation 已大部分 LLM-first |
| **0.9** | **`_snapshot_to_tool_args` 逐工具硬编码分支**——6 个工具（6 个 `if tool_name == "..."` 分支）硬编码 snapshot → tool arguments 的 mapping | 🟡 High | `core/governed_router.py:427-533` | **E 影响**：新增工具时必须改此 switch；Section 8 需给出解耦方案 |
| **0.10** | **NaiveRouter 只暴露 7 个工具**（剔除 `analyze_file` 和 `compare_scenarios`），且状态存储独立于 full/governed；naive 基线结果不代表完整工具面 | 🟢 Medium | `core/naive_router.py:28-36 NAIVE_TOOL_NAMES`；`api/session.py:34, 37` | **Eval 解读**：benchmark 对比 naive vs full 时不可声称"工具等价"；非 Phase 2 新增工作 |

**冲突标注**：本次审计与 `docs/codebase_audit_part1_oa_reality.md:9` "full 通常会落到 GovernedRouter" 的说法冲突。以代码为准（Finding 0.2 的反面证据确凿）。

---

## Section 1. 仓库结构与入口

### 1.1 主要入口

- **CLI 主入口**：`main.py:19`，暴露 `chat` / `health` / `tools-list`。`chat` 直接构造 `UnifiedRouter(session_id="cli_session")` (`main.py:22`)——**绕过 API/session 包装层**，因此 CLI 对 `router_mode` flag 无感知。
- **API 主入口**：`run_api.py:26` 启动 uvicorn；FastAPI app 在 `api/main.py:29` 构造，挂 `/api` 路由、把 `web/` 静态目录挂到根路径 (`api/main.py:51`)。
- **API 请求主链**：
  ```
  POST /api/chat (api/routes.py:210)
    → ChatSessionService.process_turn (services/chat_session_service.py:148)
      → Session.chat (api/session.py:83)
        → build_router (core/governed_router.py:559)
          → UnifiedRouter (router.py:*) 或 GovernedRouter (governed_router.py:29)
  ```
- **模式参数**：`full` / `naive` / `governed_v2` 定义于 `services/chat_session_service.py:18 ROUTER_MODES`，在 `api/routes.py:224` 暴露。默认 `"full"`（`api/session.py:83`）。

### 1.2 顶层目录结构（真实主干）

```
core/           — Router、Contract、State、Memory、Assembler 核心
  contracts/    — 7 个 contract 子类
tools/          — 9 个工具 + registry + contract_loader
services/       — 标准化、约束、chat 会话、LLM 客户端、模型后端
api/            — FastAPI routes、session、auth、database
config/         — 5 份 YAML（tool_contracts / cross_constraints / unified_mappings / dispersion_pollutants / meteorology_presets / stance_signals）
evaluation/     — benchmark 入口、标准化/continuation/file-grounding ablation、pipeline_v2
web/            — 前端（index.html + app.js + login.html + diagnostic.html）
tests/          — pytest 测试（含状态契约、契约、cross_constraints 等）
data/           — session 持久化、benchmarks 数据
LOCAL_STANDARDIZER_MODEL/  — 本地标准化模型
ps-xgb-aermod-rline-surrogate/  — AERMOD/RLINE 代理模型（活跃使用，见 Section 9）
GIS文件/        — 上海市底图和路网 shapefile（活跃使用）
static_gis/     — 预处理后的 GeoJSON
```

**仓库根目录**还堆了大量历史报告和诊断（`PHASE*_REPORT.md` × 14、`DEEP_DIVE_*.md` × 3、`EXPLORATION_*.md` × 3 等）——见 Section 9。

### 1.3 Benchmark / Eval 入口

- `evaluation/eval_end2end.py:1713`（显式传 `router_mode="router"`，见 `:1273`）
- `evaluation/run_oasc_matrix.py:305`（每 cell 显式设 `ENABLE_GOVERNED_ROUTER`，见 `:29,43,63,83,106,126,146`）
- `evaluation/eval_ablation.py:160`

**路径不对称**：eval 默认走 `router_mode="router"` → GovernedRouter（配合 `ENABLE_GOVERNED_ROUTER=true` 默认），而 API 默认 `full` → UnifiedRouter。这是 Migration Task Pack（§7.F）必须收敛的差异。

---

## Section 2. Feature Flag 清单

### 2.1 总体统计

- **布尔 flag 总数**：81 个（`config.py:44-368` 区间的 `os.getenv(...).lower() == "true"` 模式）
- **`.env.example` 覆盖**：59 个（`.env.example:40-279`）
- **缺口**：**22 个 live flag 在 `.env.example` 中缺席**，主要是 AO / OASC / contract-split / governed-router 一组：
  - `ENABLE_AO_*`（含 `ENABLE_AO_AWARE_MEMORY`, `ENABLE_AO_CLASSIFIER_RULE_LAYER`, `ENABLE_AO_CLASSIFIER_LLM_LAYER`, `ENABLE_AO_BLOCK_INJECTION`, `ENABLE_AO_PERSISTENT_FACTS`, `ENABLE_AO_FIRST_CLASS_STATE`）
  - `ENABLE_CLARIFICATION_CONTRACT`, `ENABLE_CONTRACT_SPLIT`, `ENABLE_SPLIT_INTENT_CONTRACT`, `ENABLE_SPLIT_STANCE_CONTRACT`, `ENABLE_SPLIT_READINESS_CONTRACT`, `ENABLE_SPLIT_CONTINUATION_STATE`
  - `ENABLE_GOVERNED_ROUTER`
  - 等

### 2.2 分类（ALIVE 69 / DORMANT 10 / MISLEADING 2 / DEAD 0）

**MISLEADING（有定义，无 runtime reader）**：

| Flag | 位置 | 说明 |
|---|---|---|
| `ENABLE_STANDARDIZATION_CACHE` | `config.py:45` | 仅在 `tests/test_config.py:30` 断言存在；无 runtime 代码读它 |
| `ENABLE_DEPENDENCY_CONTRACT` | `config.py:153-155` | `DependencyContract` 类本身就是 13 行空壳（`core/contracts/dependency_contract.py`），无论这个 flag 状态如何都不影响行为 |

**DORMANT（默认关闭但有 reader）**：

| Flag | 默认 | Reader |
|---|---|---|
| `PERSIST_TRACE` | false | `core/router.py:2593` |
| `ENABLE_SESSION_STATE_BLOCK` | false | `core/assembler.py:273` |
| `ENABLE_CONTRACT_SPLIT` | false | `core/contracts/oasc_contract.py:114`（及 governed_router.py / split contracts） |
| `ENABLE_LIGHTWEIGHT_PLANNING` | false | `core/router.py:5649` |
| `ENABLE_BOUNDED_PLAN_REPAIR` | false | `core/router.py:8939` |
| `ENABLE_REPAIR_AWARE_CONTINUATION` | false | `core/router.py:8124` |
| `ENABLE_FILE_ANALYSIS_LLM_FALLBACK` | false | `core/router.py:5313` |
| `ENABLE_WORKFLOW_TEMPLATES` | false | `core/router.py:10434` |
| `ENABLE_BUILTIN_MAP_DATA` | false | `tools/macro_emission.py:926` |
| `USE_LOCAL_STANDARDIZER` | false | `services/model_backend.py:247` |

**关键默认值**（`config.py`）：

- `ENABLE_GOVERNED_ROUTER=true`（:157）——但对 `router_mode="full"` 不生效（`build_router` 的分支只检查 `governed_v2` 或 `router+flag`）
- `enable_contract_split=false`（:80-82）——默认 B 路径 contract 链 = `[OASC, Clarification, Dependency(noop)]`
- `enable_ao_block_injection=true`（:71-73）——assembler 默认渲染 AO block（但 A 路径下是空）
- `enable_ao_aware_memory=true`（:57）——OASCContract `before_turn` 默认启用分类
- `enable_clarification_contract=true`（:77-79）——`ClarificationContract.before_turn` 默认启用内部逻辑

---

## Section 3. Contract Chain / Router Architecture

### 3.1 路径 A · UnifiedRouter (`router_mode="full"`)

- **装载点**：`api/session.py:49-58` → `build_router(..., router_mode="full")` → `core/governed_router.py:563-570` 命中"既非 `governed_v2` 也非 `router`"分支，直接 `return UnifiedRouter(...)`
- **触发条件**：API 默认 mode（`api/session.py:55`；`services/chat_session_service.py:18`）；CLI 的 `main.py:22` 也直接构造 UnifiedRouter
- **Contract 外壳**：⚠️ **完全没有**
  - `UnifiedRouter.chat()` 定义在 `core/router.py:2372`
  - `grep "from core.contracts\|import.*Contract" core/router.py` = 0 命中
  - 无 before_turn/after_turn 生命周期；治理逻辑直接内嵌在 `router.py` 的 11964 行中
- **AO 集成**：⚠️ **零接入**
  - `grep "AOManager\|ao_manager\|analytical_objective\|AnalyticalObjective" core/router.py` = 0 命中
- **Cross-constraint pre-exec gate**：`core/router.py:10782` 调用 `_evaluate_cross_constraint_preflight` (`:2165`)，使用 `services.cross_constraints.get_cross_constraint_validator()` (`:185, 2241`)
- **Tool dependency 校验**：✅ 有，通过 `tool_dependencies.py:181 validate_tool_prerequisites`
- **其他 governance（均在 router.py 内，非 contract 化）**：
  - Workflow templates (`:10434`, flag `ENABLE_WORKFLOW_TEMPLATES` 默认 false)
  - Bounded plan repair (`:8939`)
  - Input completion flow
  - Parameter negotiation
  - Capability-aware synthesis
  - Artifact memory / Readiness gating / Residual re-entry

### 3.2 路径 B · GovernedRouter (`router_mode="governed_v2"` 或 `"router"+ENABLE_GOVERNED_ROUTER=true`)

- **装载点**：`core/governed_router.py:29` 定义，`:32-92` 构造函数
- **触发条件**：`build_router(router_mode="governed_v2")` 或 `router_mode="router"+ENABLE_GOVERNED_ROUTER=true`（flag 默认 true，`config.py:157`）
- **内嵌 UnifiedRouter**：`self.inner_router = UnifiedRouter(...)` (`:35-38`)，通过 `__getattr__` 透传 (`:94-95`)
- **主流程**：`GovernedRouter.chat()` (`:97-149`) 顺序调 `contract.before_turn(context)`，再决定 snapshot direct-exec vs 回退到 `inner_router.chat()`，最后每个 contract `after_turn`

### 3.3 Contract 装载链（构造 vs 仅 import vs 装载但未用）

| Contract | 文件:行 | name | 构造条件 | 进入 `self.contracts` | 被调用 |
|---|---|---|---|---|---|
| `OASCContract` | `core/contracts/oasc_contract.py:25` | `oasc` | 总是 (`governed_router.py:41`) | 总是首位 (`:77`) | ✅ before+after |
| `ClarificationContract` | `core/contracts/clarification_contract.py:112` | `clarification` | `enable_contract_split=false` (`:71-75`) | 是 (`:91`) | ✅ before+after |
| `IntentResolutionContract` | `core/contracts/intent_resolution_contract.py:15` | `intent_resolution` | `contract_split=true && enable_split_intent_contract=true` (`:52-57`) | 是 (`:83`) | ✅ before |
| `StanceResolutionContract` | `core/contracts/stance_resolution_contract.py:15` | `stance_resolution` | `contract_split=true && enable_split_stance_contract=true` (`:58-63`) | 是 (`:84`) | ✅ before |
| `ExecutionReadinessContract` | `core/contracts/execution_readiness_contract.py:23` | `execution_readiness` | `contract_split=true && enable_split_readiness_contract=true` (`:64-69`) | 是 (`:85`) | ✅ before+after |
| `DependencyContract` | `core/contracts/dependency_contract.py:12` | `dependency` | 总是 (`:76`) | 总是末尾 (`:92`) | ⚠️ **装载但无实质动作**——13 行空壳，继承 `BaseContract` 默认 no-op |
| `BaseContract` | `core/contracts/base.py:32` | — | 抽象 | — | — |

**默认 B 路径 contract 链**（`contract_split=false`）：`[OASC, Clarification, Dependency-noop]`
**契约拆分模式**（`contract_split=true`）：`[OASC, IntentResolution, StanceResolution, ExecutionReadiness, Dependency-noop]`

⚠️ `DependencyContract` 每轮都进入 `for contract in self.contracts` 循环（`governed_router.py:110, 146`），每次都被调用 `before_turn` 和 `after_turn`——但这两个方法都是 `BaseContract` 的空实现。这是明显的"装载但未用"。

### 3.4 路径 C · NaiveRouter (`router_mode="naive"`)

- `core/naive_router.py:53`，仅 348 行
- 触发：`mode="naive"` → `session.naive_router` (`api/session.py:73-81`)
- **无 contract / 无 AO / 无 cross-constraint engine / 无 dependency validator**
- 仅 7 个工具（`NAIVE_TOOL_NAMES`，`core/naive_router.py:28-36`），排除 `analyze_file` 和 `compare_scenarios`
- 独立状态存储目录 `naive_router_state/`（`api/session.py:34, 37`）

### 3.5 路径差异矩阵

| 能力 | A (UnifiedRouter / full) | B (GovernedRouter / governed_v2) | C (NaiveRouter / naive) |
|---|---|---|---|
| Contract 外壳 | ❌ | ✅ (OASC+clar/[split]+dep-noop) | ❌ |
| AOClassifier / AO 生命周期 | ❌ | ✅ OASCContract 驱动 | ❌ |
| OASC Stage-2 LLM（意图/stance/slots） | ❌ | ✅（split=true 时） | ❌ |
| ClarificationContract（单流 probe） | ❌ | ✅（split=false 时） | ❌ |
| Cross-constraint pre-exec gate | ✅ (`router.py:10782`) | ✅（同一方法，inner） | ❌ |
| Cross-constraint in StandardizationEngine | ✅ (`services/standardization_engine.py:643`) | ✅ | ✅（若 tool 内走过 engine） |
| Tool dependency 图（YAML 驱动） | ✅ | ✅ | ❌（纯 function calling） |
| Session State Block 注入 LLM prompt | ✅（assembler 共享）——但 AO 数据为空 | ✅（AO 数据真实） | ❌（naive 不走 assembler） |
| 持久化路径 | `router_state/{sid}.json` | **同一文件** | `naive_router_state/{sid}.json` |
| artifact memory / readiness / plan repair / workflow templates | ✅ | ✅（透传） | ❌ |

### 3.6 Session Resume / Legacy Fallback（三种形态）

**(a) 同进程跨 turn 的 router 缓存分裂**

- `api/session.py:41-43` 三个独立字段：`_router` / `_governed_router` / `_naive_router`
- `session.chat(mode=...)` 按 mode 分发到不同字段（`:83-99`）
- **后果**：同一 session 在同一进程中跨 turn 切 mode（例如 turn1=`full`，turn2=`governed_v2`）时，turn2 构造全新 GovernedRouter，其 inner_router 的 memory 从 disk 重读（`_restore_router_state` 会读同一个 `{sid}.json`）
- A 路径下 AO 字段从未填过，所以从 A 切到 B 后，B 看到的是空 AO history

**(b) 跨进程 restart 的反序列化（有 bug）**

- `core/memory.py:744, 871` 定义完整持久化，包含 `ao_history` / `current_ao_id` / `constraint_violations_seen` / `cumulative_constraint_violations` / `session_confirmed_parameters` 等
- `core/governed_router.py:535-556 restore_persisted_state` 的问题：
  ```python
  self.contracts = [
      self.oasc_contract,
      self.clarification_contract,
      self.dependency_contract,
  ]
  ```
  ⚠️ **硬编码老 3-contract shape，忽略 `enable_contract_split`**。如果 session 在 split=true 下保存，restart 后 `intent/stance/readiness` 三 contract 丢失；AO 元数据（`execution_readiness` 等 split-only 字段）仍在磁盘，但运行时不再有 contract 去读写它们。

**(c) 格式迁移异常**

- `core/analytical_objective.py:44 IncompatibleSessionError` + `:260-266`：磁盘 AO 缺 `stance` 字段抛异常，强制跑 `scripts/migrate_phase_2_4_to_2r.py`
- `core/memory.py:826-849`：`ao_history` 为空但有 working_memory 时合成"legacy AO"占位

---

## Section 4. 工具清单与 Tool Contract

### 4.1 注册工具（9 个）

`tools/registry.py:82-145 init_tools()` 显式 import + register 9 个工具：

| 工具名 | 实现类 | 文件 | consumes (`requires`) | produces | YAML action_variants | Naive 可见 |
|---|---|---|---|---|---|---|
| `query_emission_factors` | `EmissionFactorsTool` | `tools/emission_factors.py` | `[]` | `[emission_factors]` | — | ✅ |
| `calculate_micro_emission` | `MicroEmissionTool` | `tools/micro_emission.py` | `[]` | `[emission]` | — | ✅ |
| `calculate_macro_emission` | `MacroEmissionTool` | `tools/macro_emission.py` | `[]` | `[emission]` | `run_macro_emission` | ✅ |
| `analyze_file` | `FileAnalyzerTool` | `tools/file_analyzer.py` (1629 行) | `[]` | `[file_analysis]` | — | ❌ |
| `query_knowledge` | `KnowledgeTool` | `tools/knowledge.py` | `[]` | `[knowledge]` | — | ✅ |
| `calculate_dispersion` | `DispersionTool` | `tools/dispersion.py` | `[emission]` | `[dispersion]` | `run_dispersion` | ✅ |
| `analyze_hotspots` | `HotspotTool` | `tools/hotspot.py` | `[dispersion]` | `[hotspot]` | `run_hotspot_analysis` | ✅ |
| `render_spatial_map` | `SpatialRendererTool` | `tools/spatial_renderer.py` | 按 `layer_type` 动态（`tool_dependencies.py:120-124`） | `[visualization]` | `render_emission_map` / `render_dispersion_map` / `render_hotspot_map` | ✅ |
| `compare_scenarios` | `ScenarioCompareTool` | `tools/scenario_compare.py` | — | — | `compare_scenario` | ❌ |

### 4.2 Tool Contract 声明式程度

- `TOOL_GRAPH`（`core/tool_dependencies.py:32-34`）：**完全 YAML 驱动**，一行 `= get_tool_contract_registry().get_tool_graph()`，无硬编码 fallback
- `TOOL_DEFINITIONS`（`tools/definitions.py:6`）：**完全 YAML 驱动**，`= get_tool_contract_registry().get_tool_definitions()`
- `config/tool_contracts.yaml`（821 行）声明 `tools.<name>.{parameters,dependencies,readiness,continuation_keywords,action_variants}` + 顶层 `tool_definition_order` + `readiness_action_order` + `artifact_actions`

### 4.3 硬编码散布（五处）

1. **`core/contracts/runtime_defaults.py:10-14`** — `_RUNTIME_DEFAULTS = {"query_emission_factors": {"model_year": 2020}}`；runtime 优先于 YAML defaults（`:41-45` 显式注释"runtime-only wins"）
2. **`core/governed_router.py:427-533`** `_snapshot_to_tool_args` — **逐工具硬编码** 6 个 `if tool_name == "..."` 分支（query_emission_factors / calculate_micro_emission / calculate_macro_emission / calculate_dispersion / analyze_hotspots / render_spatial_map）；新增工具必须扩此 switch
3. **`core/ao_manager.py:73-87 MULTI_STEP_SIGNAL_PATTERNS` + `:566-586 _extract_implied_tools`** — 完成判定的"中英文关键词 → 工具组"硬编码映射
4. **`core/naive_router.py:28-36 NAIVE_TOOL_NAMES`** — 7 工具白名单
5. **双份 YAML 并存** — `config/tool_contracts.yaml` 管 `parameters/dependencies/readiness/continuation_keywords/action_variants`；`config/unified_mappings.yaml` 管 `tools.<name>.required_slots/optional_slots/defaults/clarification_followup_slots/confirm_first_slots`。两份 YAML 各自有一套 tool-level 定义（被 `core/contracts/stance_resolution_contract.py:177-186` 和 `tools/contract_loader.py` 分别读取）

### 4.4 工具在 A/B 路径的行为差异

所有 9 个工具的 `execute()` 在 `tools/*.py` 中**不感知 router mode**——它们是纯执行层。差异来自工具被调用前的 contract/router 处理：

- `BaseTool.preflight_check()` 默认 `is_ready=True`（`tools/base.py:68-79`）；只有 `DispersionTool` 覆写
- `MacroEmissionTool._fix_common_errors()`（`tools/macro_emission.py`）补字段别名（link_length ← length / road_length 等）
- ⚠️ `FileAnalyzerTool` 在 `core/contracts/clarification_contract.py:23` 被直接 import 并用作 contract 层 helper——这意味着 B 路径的 contract 层可以**先于 LLM 选 `analyze_file`** 就跑文件分析；A 路径必须等 LLM 走 tool-calling 才能触发

---

## Section 5. Analytical Objective 数据结构与生命周期

### 5.1 数据结构

- **定义**：`core/analytical_objective.py:198 @dataclass class AnalyticalObjective`
- **19 个字段**：

| 字段 | 类型 | 作用 |
|---|---|---|
| `ao_id` | str (`AO#1`, …) | 会话内自增 ID |
| `session_id` | str | 所属 session |
| `objective_text` | str | 用户目标摘要（取 user_message 前 200 字符） |
| `status` | `AOStatus` enum (CREATED/ACTIVE/REVISING/COMPLETED/FAILED/ABANDONED) | 生命周期状态 |
| `start_turn`, `end_turn` | int | 起止 turn index |
| `relationship` | `AORelationship` (INDEPENDENT/REVISION/REFERENCE) | 与父 AO 关系 |
| `parent_ao_id` | `Optional[str]` | 父 AO |
| `tool_call_log` | `List[ToolCallRecord]` | 本 AO 工具调用（capped 20） |
| `artifacts_produced` | `Dict[str, str]` | `artifact_type → label` |
| `parameters_used` | `Dict[str, Any]` | 本 AO 已确认参数 |
| `failure_reason` | `Optional[str]` | 失败原因 |
| **`constraint_violations`** | `List[Dict[str, Any]]` | ⚠️ **字段存在但恒空**（见 §6.3） |
| `tool_intent` | `ToolIntent` | 已解析意图（resolved_tool/confidence/evidence/projected_chain） |
| `parameter_state` | `ParameterState` | 参数补全状态（required_filled/optional_filled/awaiting_slot/collection_mode/probe_turn_count/probe_abandoned） |
| `stance`, `stance_confidence`, `stance_resolved_by`, `stance_history` | — | 会话 stance |
| `metadata` | `Dict[str, Any]` | 自由字段（`clarification_contract`/`execution_readiness`/`execution_continuation`） |

- `to_dict`/`from_dict`（`:226-332`）；缺 `stance` 抛 `IncompatibleSessionError`（`:260-266`）
- `_migrate_deprecated_metadata`（`:356-400`）把老字段吸收进 `tool_intent`/`parameter_state`

### 5.2 生命周期

- **AOManager** 定义：`core/ao_manager.py:67`
- **AOManager 构造处**（仅 2 处，均 GovernedRouter 内）：
  1. `GovernedRouter.__init__`（`governed_router.py:39`）
  2. `GovernedRouter.restore_persisted_state`（`:540`）
- ⚠️ `grep "ao_manager|AOManager" core/router.py` = 0 命中 — UnifiedRouter 不参与 AO 生命周期
- **生命周期方法**（ao_manager.py）：`create_ao`/`activate_ao`/`append_tool_call`/`register_artifact`/`complete_ao`/`revise_ao`/`fail_ao`/`abandon_ao`
- **调用者**：`OASCContract._apply_classification`（`oasc_contract.py:244-271`）创建 AO；`._sync_ao_from_turn_result`（`:273-313`）追加工具调用 + 同步参数；`.after_turn`（`:94-98`）调用 `complete_ao`

### 5.3 AO 注入 LLM prompt

- **Assembler 入口**：`core/assembler.py:266 _append_session_state_block`——**A/B 共享的 prompt 组装路径**
- Flag：
  - `enable_ao_block_injection=true`（默认，`config.py:71-73`）→ `_build_ao_session_state_block`（`assembler.py:385`）
  - `enable_session_state_block=false`（默认，`config.py:56`）→ legacy block
- Token 预算：`ao_block_token_budget=1200`（`config.py:156`）
- ⚠️ **A 路径悖论**：assembler 尝试渲染 AO block，但 `fact_memory.ao_history` 恒空 → **A 路径下 AO block 是空架子**

### 5.4 三个关键追查点的明确回答

1. **"AO 是否在 UnifiedRouter 路径完全不被使用？"** → **是**。`core/router.py` 中 0 个 AO 相关 import；UnifiedRouter 从不 create/read/update AO。唯一交集是 `fact_memory.ao_history` 作为字段被序列化，但 UnifiedRouter 不写入。

2. **"AO 是否有 constraint_violation_history 或类似字段？"** → **字段存在但 write pipeline 断裂**：
   - `AnalyticalObjective.constraint_violations`（`analytical_objective.py:214`）
   - `fact_memory.constraint_violations_seen`（`memory.py:84`, capped 10）
   - `fact_memory.cumulative_constraint_violations`（`memory.py:89`）
   - **读方**：`assembler.py:363 _format_constraint_violations`（legacy block）、`oasc_contract.py:362` 的循环、`ao_manager.py:345` summary
   - **写方**：`fact_memory.append_constraint_violation`（`memory.py:195`）仅被 tests 调用；`append_cumulative_constraint_violation`（`memory.py:262`）仅被 `oasc_contract.py:373` 调用（但源头 `constraint_violations_seen` 是空）
   - **UnifiedRouter 的 `_evaluate_cross_constraint_preflight`（`router.py:2165`）只写 trace/`blocked_info`/`_final_response_text`，不写 memory**
   - **`services/standardization_engine.py:643-666` 只抛异常，不写 memory**
   - → **现象：两条路径下 `constraint_violations` 全家恒空**

3. **"Session resume 会不会导致 AO 被丢弃或重置？"** → 视 mode 与 flag：
   - 跨 mode 切换（A↔B）：fact_memory 持久化到同一 `router_state/{sid}.json`，AO 历史能复活；A 下不更新，回到 B 停在上次状态
   - 跨进程 restart 且 `contract_split=true`：`governed_router.py:552-556` 硬编码 3-contract shape，丢失 split 运行时能力
   - 磁盘缺 stance 字段：`IncompatibleSessionError`，要求跑迁移脚本
   - `ao_history` 空 + `working_memory` 非空：合成 legacy AO 占位

---

## Section 6. 约束规则与依赖图

### 6.1 Cross-constraint 引擎

- **YAML**：`config/cross_constraints.yaml`（68 行，version 1.1）
- **规则数**：**4 条**
  - `vehicle_road_compatibility`（blocked_combinations）：Motorcycle × 高速公路
  - `vehicle_pollutant_relevance`（conditional_warning）：Motorcycle × PM2.5/PM10
  - `pollutant_task_applicability`（conditional_warning）：CO2 或 THC × `calculate_dispersion`
  - `season_meteorology_consistency`（consistency_warning）：冬季 ↔ 夏季 preset 不匹配
- **规则类型**（`services/cross_constraints.py:123-158`）：
  - `blocked_combinations` → 阻塞
  - `conditional_warning` → 仅警告
  - `consistency_warning` → 仅警告
- **引擎**：`CrossConstraintValidator`（`services/cross_constraints.py:68-229`），singleton `get_cross_constraint_validator()`（`:232-240`）

### 6.2 触发时机（两条独立路径）

| 触发点 | 文件:行 | 时机 | 失败后行为 | 写 fact_memory |
|---|---|---|---|---|
| **UnifiedRouter preflight** | `core/router.py:10782`→`:2165 _evaluate_cross_constraint_preflight` | 工具执行前 | `state.execution.blocked_info` + `_final_response_text` → DONE | ❌ 只写 trace |
| **StandardizationEngine 内置** | `services/standardization_engine.py:643-666` | 参数标准化批处理阶段 | 抛 `StandardizationError`（trigger_reason=`cross_constraint_violation:<name>`） | ❌ |

**关键观察**：
- 两个触发点都不是 contract 层（B 路径的 `DependencyContract` 不做约束检查）
- Cross-constraint engine 在两条路径下都生效——因为它是 inner_router 的一部分，不绑定 contract

### 6.3 约束违反的传播

- ✅ **Trace**：`TraceStepType.CROSS_CONSTRAINT_WARNING/VIOLATION`（`router.py:2244, 2281`）
- ✅ **当前轮回复**：`_final_response_text = f"参数组合不合法: {violation.reason}..."`（`router.py:2270`）
- ❌ **跨轮累积到 LLM prompt**：**无**。`constraint_violations_seen` 和 `cumulative_constraint_violations` 在生产代码中无 writer（见 §5.4 第 2 点）

### 6.4 工具依赖图

- **构建方式**：`core/tool_dependencies.py:32-34 TOOL_GRAPH = get_tool_contract_registry().get_tool_graph()`——**纯 YAML 驱动**，无硬编码 fallback
- **硬编码微调**：
  - `CANONICAL_RESULT_ALIASES`（`:20-27`）把 `emission_result/dispersion_result/...` 映射到 `emission/dispersion/...`
  - `get_required_result_tokens` 对 `render_spatial_map` 按 `layer_type` 动态推断（`:120-124`）
- **反向推理**：`suggest_prerequisite_tool(missing_result)`（`:268-276`）可用，返回首个能 provide 的工具
- **Plan 校验**：`validate_plan_steps`（`:290-384`）按序模拟 token 流，返回 BLOCKED/READY/FAILED/INVALID
- **运行时单步校验**：`validate_tool_prerequisites`（`:181-265`）

### 6.5 `ENABLE_DEPENDENCY_CONTRACT` 的影响

- 定义：`config.py:153-155`，默认 false
- 生产 reader：**零**（`grep "enable_dependency_contract" --include="*.py"` 仅命中 config.py 自身）
- `DependencyContract`（`core/contracts/dependency_contract.py:12`）无条件装载 `self.contracts`，**根本不检查此 flag**
- 对 Phase 2 的影响：**非阻塞**。Migration 时建议清理（删除 flag 或激活 contract）

### 6.6 Cross-constraint 引擎在两路径下是否都生效

✅ 是。A 路径直接调；B 路径通过 `inner_router` 间接调。差异只在 B 有 contract 层额外的 stance/intent/readiness 判断，对 cross-constraint 本身无影响。

---

## Section 7. Task Pack 级别的现状评估

本节对 Phase 2 规划的 5 个 Task Pack（A/B/C/D/E）+ Migration Task Pack（F）逐一评估：相关代码 / gap / 风险 / 前置动作。

### 7.A Task Pack A · 追问生成与解析从规则迁移到 LLM 主导 + 标准化 fallback

#### 7.A.1 当前相关代码

**问题生成侧**：
- `core/contracts/clarification_contract.py:996 _build_question`（**rule-based 模板 fallback + LLM 覆盖**）：
  - 接受 `llm_question` 参数——若来自 Stage 2 LLM 的 `stage2_clarification_question` 非空，直接返回
  - 若 LLM 未给问题：走 rule-based 分支（tool_name × slot_name 的硬编码 `if`，共 ~6 个分支，覆盖 `query_emission_factors` 的 `vehicle_type/pollutants/model_year`、`calculate_macro_emission`/`calculate_micro_emission` 的 `pollutants`、`calculate_micro_emission` 的 `vehicle_type`）
  - 兜底文案："我还需要补充一个关键参数后才能继续..."
- `core/contracts/clarification_contract.py:1027 _build_probe_question`（**已 LLM-first**）：
  - 先调 `_run_probe_question_llm:1047`（LLM JSON 输出一句问题）
  - LLM 超时/失败走 `_slot_display_name` + `_valid_values_description` 的 rule-based 模板
- `core/contracts/execution_readiness_contract.py:247, 391`（split 契约）复用上面两个方法

**回复解析侧**（Task Pack A 的实际重心）：
- `core/parameter_negotiation.py:293 parse_parameter_negotiation_reply` —— **426 行完整的 regex 状态机**
  - `_extract_indices:229`、`_extract_index:262`、`_normalize_text:209`、`_extract_parenthetical_parts:213`
  - Decision types: `CONFIRMED` / `NONE_OF_ABOVE` / `AMBIGUOUS_REPLY`
- `core/input_completion.py:402 parse_input_completion_reply` —— **~470 行，同样的 regex 模式**
  - `_extract_index:296`、`_extract_numeric_value:310`、`_match_option_by_reply:339`、`_matches_default_typical_profile_intent:362`
  - Decision types: `SELECTED_OPTION` / `PAUSE` / `AMBIGUOUS_REPLY`

**标准化 fallback**：
- `services/standardization_engine.py` 已有 multi-tier（exact → alias → fuzzy → LLM fallback，见阶段 1 memory）
- `clarification_contract.py` 用 `StandardizationEngine(config={"llm_enabled": False, "fuzzy_enabled": True})` 做 stage3 标准化（`:137-144`）

#### 7.A.2 与目标状态的 gap

| 维度 | 目标 | 当前现状 | Gap 性质 |
|---|---|---|---|
| 问题生成 | LLM-first，标准化 fallback 作为备份 | `_build_probe_question` 已是；`_build_question` 部分是（split 路径由 stage2 LLM 提供，legacy 路径仍有 rule 模板） | **小幅调整**：移除 `_build_question` 的 hardcoded 模板，统一走 LLM；保留超时 fallback |
| 回复解析 | LLM 主导，regex 作为简单 confirmation 的 fast path | 全部 regex 驱动，两套独立状态机（426 + 470 行） | **大范围重写**：两个文件需要引入 LLM 解析层，现有 regex 可降级为"明确数字索引/简短确认"的 fast path |
| 解析异常恢复 | LLM 解析低置信时回到 regex + 标准化 fallback | 目前 regex 低置信直接 `AMBIGUOUS_REPLY` → 再发问题 | **中等重构**：需定义 LLM 置信阈值 + fallback 链路 |

**涉及文件范围**：
- 必改：`core/parameter_negotiation.py`、`core/input_completion.py`、`core/contracts/clarification_contract.py`、`core/contracts/execution_readiness_contract.py`
- 可能改：`core/router.py`（若 UnifiedRouter 直接调 `parse_*_reply`——需 grep 确认）
- 测试必改：`tests/test_parameter_negotiation*.py`、`tests/test_input_completion*.py`（如存在）

**新增/修改的接口**：
- 新增 `core/reply_parser_llm.py` 或 `services/reply_parser.py` 作为 LLM 解析器
- `parse_parameter_negotiation_reply` 和 `parse_input_completion_reply` 签名增加 `llm_client` 注入参数，或在模块级别获取

#### 7.A.3 风险点

1. **LLM 延迟敏感**：回复解析是用户对话的关键路径，每轮可能多一次 LLM 往返（~500ms-2s）。需要超时设置 + 严格的回退链。
2. **ambiguous_reply 的语义变化**：现有 regex 会严格判定 "ambiguous"，LLM 可能过于"宽容"接受模糊回复，导致错误的参数被填入。
3. **Coupling 到 Task Pack B**：若 constraint violation 作为 structured fact 进 prompt（Pack B），LLM 解析时能看到更多上下文；先做 A 再做 B 可能需要二次调整 prompt。
4. **NaiveRouter 不受影响**：NaiveRouter 不走 parameter_negotiation / input_completion，A 只影响 full/governed_v2 路径。

#### 7.A.4 推荐前置动作

1. 在 `core/parameter_negotiation.py` / `core/input_completion.py` 顶部加 LLM 客户端依赖注入点（现在它们是纯函数模块），避免重构时需要到处传 `llm_client`
2. 梳理 `services/llm_client.py` 是否已有适合的低延迟 client 配置（类似 OASC 用的 qwen-plus with timeout=5s）

### 7.B Task Pack B · 约束违反跨轮累积，作为 structured fact 注入 LLM context

#### 7.B.1 当前相关代码

**Data structures**（已存在）：
- `AnalyticalObjective.constraint_violations: List[Dict]`（`core/analytical_objective.py:214`）
- `FactMemory.constraint_violations_seen: List[Dict]`（`core/memory.py:84`, capped 10）
- `FactMemory.cumulative_constraint_violations: List[Dict]`（`core/memory.py:89`, capped N）

**Write API**（已定义但无 producer）：
- `FactMemory.append_constraint_violation(turn, constraint, values, blocked)`（`core/memory.py:195-213`）
- `FactMemory.append_cumulative_constraint_violation(turn, constraint, values, blocked, *, ao_id)`（`core/memory.py:262-280`）

**Read/Render**（已接通）：
- `core/assembler.py:363` legacy block 渲染 `constraint_violations_seen`
- `core/assembler.py:438` AO block 渲染 `cumulative_constraint_violations`
- `core/contracts/oasc_contract.py:353-379 _sync_persistent_session_facts` 每轮从 `fact_memory.constraint_violations_seen` 复制到 `current_ao.constraint_violations` 和 `fact_memory.cumulative_constraint_violations`

**Cross-constraint 产生点**（**无 memory write**）：
- UnifiedRouter `_evaluate_cross_constraint_preflight`（`core/router.py:2165`）—— 只写 `state.execution.blocked_info` + trace
- StandardizationEngine（`services/standardization_engine.py:643-666`）—— 只抛异常 + records

#### 7.B.2 与目标状态的 gap

⚠️ **Task Pack B 的工作量被低估**：这不是"激活已有机制"，而是"从零接通 writer pipeline"。完整闭环需要三段：

| 段 | 当前 | 目标 | 改动 |
|---|---|---|---|
| **Write (capture)** | ❌ 无 producer | Writer 在每个违反点调用 `append_constraint_violation` | 新增 writer hook：router.py 的两个 violation 记录函数（`:2244, 2281` 附近）、StandardizationEngine 的 violation 分支（`:657`） |
| **Aggregate (carry)** | ⚠️ OASC 层有复制逻辑，但源头空 | 从 `constraint_violations_seen` 聚合到 `cumulative_constraint_violations` + AO 层 | OASC 的 `_sync_persistent_session_facts` 已经做了这层；一旦 write 接通就自动生效 |
| **Inject (propagate)** | ⚠️ Assembler 读取了但为空 | Block rendering 已有；只需确保 token 预算足够 | 可能需要调 `ao_block_token_budget` |

**涉及文件范围**：
- **必改**（write 接通）：`core/router.py`（至少在 `_evaluate_cross_constraint_preflight` 的违反记录后调 memory writer）、`services/standardization_engine.py`（在 violation 异常之前写 memory——但 engine 是否有 `fact_memory` 引用需要 check）
- **可能改**：`core/contracts/clarification_contract.py`（stage3 的标准化若触发 violation 是否写 memory）
- **测试必改**：`tests/test_state_contract.py`（已存在 fixture；验证 writer 是否被调用，不只是"append 方法能 append"）

**新增/修改的接口**：
- StandardizationEngine 构造函数可能需要新增 `fact_memory` 参数，或改为事件式（engine emit event，外部监听）——需设计决策
- `Router._record_cross_constraint_violation(...)` 新方法，统一入口

#### 7.B.3 风险点

1. **Prompt bloat**：cumulative_constraint_violations 无限制累积会撑爆 token 预算。当前 `MAX_CUMULATIVE_CONSTRAINTS`（`core/memory.py:*`）已有上限，但需要验证 AO block token 预算足够容纳这一段。
2. **Coupling to Task Pack A**：一旦约束违反作为 structured fact 进 prompt，A 的 LLM reply parser 就能看到"上一轮因为 X 被拒"——可能需要调整 prompt 模板。
3. **False-positive cumulative**：如果 standardization_engine 在 dry-run 标准化时也触发违反，cumulative 列表可能包含"从未被用户确认"的违反。需要 writer 点上区分 "actual 违反" vs "speculative"。
4. **UnifiedRouter 路径下 AO 仍为空**（Finding 0.2）：即使 B 写入 memory，A 路径下 AO 段为空——所以 B 的"跨轮累积进 AO"在 A 路径下无效。**Task Pack B 的完整效果依赖 Migration Task Pack 先完成。**

#### 7.B.4 推荐前置动作

1. **先做 Migration Task Pack F**：否则 B 在生产路径下只有 `constraint_violations_seen`（capped 10）真正起作用，AO 层累积在 A 下不可见
2. 如果无法先做 F，至少先把 `constraint_violations_seen` 的 writer 接通（影响 A/B 两条路径），AO 层的累积留到 F 后
3. 设计决策：StandardizationEngine 是保持"无 memory 依赖"的纯函数引擎，还是注入 memory 依赖；建议前者（保持可测试性），通过 Router 层的 wrapper 捕获 engine 的 violation records 再写 memory

### 7.C Task Pack C · `analyze_file` 工具返回升级，让 LLM 自主识别数据质量问题

#### 7.C.1 当前相关代码

- **Entry**：`tools/file_analyzer.py:*` 的 `FileAnalyzerTool.execute`（1629 行，最大 tool 文件）
- **已有字段 `data_quality_warnings`**：
  - 构造入口：`_build_data_quality_warnings`（`tools/file_analyzer.py:262-346`）
  - 返回 payload 层：`:198, 1309, 1451, 1545`
  - 渲染入口：`:1034-1036, 1573-1574, 1591-1592`
- **现有检测维度**（单一）：road_type 与 avg_speed_kph 的一致性——检测 "同一 road_type 下速度极端偏低/偏高" 的行（`:303` groupby road_type、`:322, 344` 异常条件）
- **Test 基础设施已在**：`tests/test_file_analyzer_targeted_enhancements.py:128, 148`

#### 7.C.2 与目标状态的 gap

✅ **这是 5 个 Task Pack 中 gap 最小的**——字段已存在、渲染路径已通、测试框架已有，只需扩充检测维度。

| 维度 | 当前 | 目标（建议） | 改动 |
|---|---|---|---|
| 字段结构 | 已有 `data_quality_warnings: List[Dict]` | 可能升级为 `{warnings: [...], severity: "...", structured_facts: [...]}` | 字段层扩展，非结构重塑 |
| 检测维度 | road_type × speed 一致性 | 扩到：空值率、异常值（IQR / z-score）、重复行、列名不规范、数据类型不一致、时间戳断续 | 新增检测函数，沿用 `_build_data_quality_warnings` 的返回格式 |
| LLM 可读性 | 已作为 summary 的一部分输出到 LLM | 结构化 facts 进 prompt（可能与 Task Pack B 的 structured fact 注入机制合并） | 与 B 可能共享同一"structured fact to prompt"管道 |

**涉及文件范围**：
- 必改：`tools/file_analyzer.py`
- 测试必改：`tests/test_file_analyzer_targeted_enhancements.py` 或新增 `tests/test_file_analyzer_data_quality.py`
- **不** 必改：contract 层、assembler、router（现有 `summary` 输出路径已通）

**新增/修改的接口**：无（字段扩展）

#### 7.C.3 风险点

1. **`analyze_file` 已是 1629 行巨型文件**，进一步扩张会放大维护难度；建议新增 `tools/file_quality_checks.py` 作为独立模块被 FileAnalyzerTool 组合
2. **质量检测与 Task Pack D（`clean_dataframe`）的边界**：检测应和清洗分离（检测在 `analyze_file`，清洗在 `clean_dataframe`）；若两个 Pack 同时推进需明确分工
3. **Regression 风险**：现有 `_build_data_quality_warnings` 的 road_type 逻辑有特定业务含义（§7.C.1），新增维度不要覆盖
4. **Coupling 到 Task Pack B**：若数据质量问题要累积到 LLM context（而不只是当轮），需要 B 的 structured fact pipeline（→ 两者共享 writer）

#### 7.C.4 推荐前置动作

1. 先从 `tools/file_analyzer.py` 抽出 `_build_data_quality_warnings` 及其 helper 到 `tools/file_quality_checks.py`（纯重构，零行为变更），降低后续扩维度的风险
2. 定义 `data_quality_warning` 的 schema（severity 枚举、类别枚举），避免新增维度时字段结构漂移

### 7.D Task Pack D · 新增 `clean_dataframe` 工具，支持常见清洗操作

#### 7.D.1 当前相关代码

- **`clean_dataframe` 工具**：⚠️ **不存在**
  - `grep "clean_dataframe|DataFrameCleaner|dataframe.*clean"` 全仓库 0 命中
  - `tools/registry.py:82-145` 的 `init_tools` 只注册 9 个工具，无清洗工具
  - `config/tool_contracts.yaml` 无 `clean_dataframe` 条目
- **相关基础设施**：
  - `tools/base.py:40 BaseTool` ABC + `ToolResult`（`:14-27`）——新工具的基类
  - `tools/file_analyzer.py` 已有 DataFrame 读取和质量检测
  - `pandas` 依赖已经在（`requirements.txt`）

#### 7.D.2 与目标状态的 gap

⚠️ **Task Pack D 完全从零**。新增工作包括：

| 层 | 改动 |
|---|---|
| **工具实现** | 新建 `tools/clean_dataframe.py` 实现 `CleanDataFrameTool(BaseTool)`；典型清洗操作：drop_duplicates / fillna / drop_columns / rename_columns / filter_rows / coerce_dtypes |
| **工具契约** | 在 `config/tool_contracts.yaml` 加 `clean_dataframe` 段（parameters schema、dependencies、readiness、continuation_keywords） |
| **注册** | `tools/registry.py::init_tools` 加 register 调用 |
| **Naive 路径可见性** | 若要让 naive baseline 也能用，加入 `NAIVE_TOOL_NAMES`（`core/naive_router.py:28-36`） |
| **硬编码联动** | `_snapshot_to_tool_args`（`governed_router.py:427-533`）要加一个 `if tool_name == "clean_dataframe"` 分支；`ao_manager._extract_implied_tools`（`:566-586`）可能需加清洗类关键词 |

**涉及文件范围**：
- 新增：`tools/clean_dataframe.py`
- 必改：`config/tool_contracts.yaml`、`tools/registry.py`、`core/governed_router.py:427-533`、`core/naive_router.py:28-36`（若 naive 需要）
- 可能改：`config/unified_mappings.yaml`（若要声明 `required_slots` 等）
- 新增测试：`tests/test_clean_dataframe.py`

**新增/修改的接口**：
- `clean_dataframe(file_path, operations: List[Dict])` 或 `(file_path, ops: {drop_duplicates: bool, fillna: {...}, ...})`——接口设计需讨论

#### 7.D.3 风险点

1. **工具设计复杂度**：清洗操作集合可能很大；若接口太灵活（任意 operation list），LLM 参数构造会不稳；若太受限，扩展性差——**这是核心设计决策**
2. **文件引用**：清洗后的 DataFrame 如何存回？新文件 or in-session 内存？涉及 artifact memory 的扩展
3. **Coupling 到 Task Pack C**：如果 C 让 LLM 能识别"需要清洗的 warning"，D 让 LLM 能执行清洗——两者应作为一对设计。`analyze_file` 的 warning 最好包含 `suggested_cleaning_ops` 字段，让 LLM 直接用
4. **Coupling 到 Task Pack E**：每新增一个工具都暴露现有的 5 处硬编码（§4.3），D 的推进同时测试了 E 的声明式改造效果

#### 7.D.4 推荐前置动作

1. 与 Task Pack C 一起设计——至少明确 `analyze_file` 的 `data_quality_warnings` 里是否输出 `suggested_ops`（机器可读的清洗建议）
2. 先做 Task Pack E 的两份 YAML 合并（§8）——否则新工具要改两个 YAML + 一堆硬编码，返工成本高
3. 定义 `clean_dataframe` 的 operation schema 时，对齐 `pandas` 常用 API（`drop_duplicates`/`dropna`/`fillna`/`rename`/`astype`/`query`），避免 LLM 需要学 DSL

### 7.E Task Pack E · Extensibility audit（声明式扩展路径无隐藏硬编码）

#### 7.E.1 当前相关代码

**声明式部分**（已做好）：
- `TOOL_DEFINITIONS = get_tool_contract_registry().get_tool_definitions()`（`tools/definitions.py:6`）——LLM function-calling schema 全来自 YAML
- `TOOL_GRAPH = get_tool_contract_registry().get_tool_graph()`（`core/tool_dependencies.py:32-34`）——依赖图全来自 YAML
- action variants、continuation_keywords、param standardization map 都是 YAML 驱动

**硬编码部分**（§4.3 的五处，这是 E 的工作对象）：
1. `core/contracts/runtime_defaults.py:10-14 _RUNTIME_DEFAULTS`（query_emission_factors.model_year=2020）
2. `core/governed_router.py:427-533 _snapshot_to_tool_args`（6 工具逐工具分支）
3. `core/ao_manager.py:73-87, 566-586`（多步关键词 + 隐含工具映射）
4. `core/naive_router.py:28-36 NAIVE_TOOL_NAMES`（7 工具白名单）
5. **双 YAML 冲突**：`tool_contracts.yaml` vs `unified_mappings.yaml` 的 `tools.<name>` 段各有一套字段

#### 7.E.2 与目标状态的 gap

见 **Section 8** 详细方案。简要：

- 硬编码 #1（runtime_defaults）：保留（有明确语义差异，见 §8）
- 硬编码 #2（_snapshot_to_tool_args）：可改为"从 tool_contract YAML 推导"，但有特殊处理（`as_list`、`safe_int`、`allow_factor_year_default`）需设计
- 硬编码 #3（ao_manager 关键词）：可迁移到 `unified_mappings.yaml` 或 `tool_contracts.yaml` 的 `completion_keywords` 段
- 硬编码 #4（naive 白名单）：可由 YAML 的 `available_to_naive: true/false` 字段替代
- 硬编码 #5（双 YAML）：核心重构——合并两份

#### 7.E.3 风险点

1. **重构量大于"审计"**：名义是 audit，实质是多文件重构。若时间紧张，可分期：first 合并 YAML（#5），later 处理 #2-4
2. **Contract/router 代码已经"知道"两份 YAML 分工**，合并 YAML 后需同步改读取点——影响面广但 mechanical
3. **对现有 flag 的依赖**：例如 stance_resolution_contract 读 unified_mappings，若合并 YAML 需改 reader
4. **Runtime defaults 的保留 rationale**：runtime 和 YAML 可能故意不同步（runtime_defaults.py:41-45 的注释说"runtime-only wins because runtime reflects actual router execution behavior; YAML defaults are declarative-level hints that may lag behind"）——保留这层意图

#### 7.E.4 推荐前置动作

1. 先完成 §8 的方案讨论，再动手
2. 与 Task Pack D 协同——D 新增工具时直接按"合并后"的 YAML 形态写，避免 D 先发、E 后追的双倍工作量
3. 列一个"新增工具需触碰的文件"清单，作为 E 的验收标准（做完 E 后，新工具理想情况只改 YAML + 新增工具文件 + `tools/registry.py` 的一行 register）

**详见 §8。**

### 7.F Migration Task Pack · 统一生产路径到 GovernedRouter

#### 7.F.1 当前相关代码

**Router 分发逻辑**：
- `core/governed_router.py:559-570 build_router`——当前按 mode 三分
- `api/session.py:41-70` 三个独立 router 缓存字段
- `services/chat_session_service.py:18 ROUTER_MODES={"full","naive","governed_v2"}`

**Session resume bug**：
- `core/governed_router.py:538-556 restore_persisted_state`——硬编码 `[oasc, clarification, dependency]`，忽略 `enable_contract_split`

**前端**：
- `web/index.html:786-787`——`<select>` 只 `full`/`naive`
- `web/app.js:5, 162, 684, 697, 769`——mode 值传递
- 响应字段：`reply/text/chart_data/table_data/map_data/download_file/trace_friendly/executed_tool_calls/message_id/file_id/session_id/data_type`——A/B/C 三路径 shape 一致（通过 `ChatTurnResult.to_api_response` 统一，`services/chat_session_service.py:101-115`）

**Eval**：
- `evaluation/eval_end2end.py:1273` 显式 `router_mode="router"`
- `evaluation/run_oasc_matrix.py:29,43,63,83,106,126,146` 显式 `ENABLE_GOVERNED_ROUTER`

#### 7.F.2 与目标状态的 gap

**收敛目标**：`mode="full"` 在 API 和 CLI 中都走 GovernedRouter；保留 `mode="naive"` 作为 baseline；消除 `mode="governed_v2"` 或将其作为 `full` 的别名。

| 改动点 | 文件:行 | 改动性质 |
|---|---|---|
| `build_router` 分支 | `core/governed_router.py:563-570` | 让 `router_mode in {"full","governed_v2","router"}` 都走 GovernedRouter 分支 |
| Session router 缓存 | `api/session.py:41-70` | 合并 `_router` 和 `_governed_router`；保留 `_naive_router` |
| Session chat dispatch | `api/session.py:83-99` | `else` 分支走 `governed_router.chat` |
| `ROUTER_MODES` | `services/chat_session_service.py:18` | 决定是否保留 `governed_v2` 作为对外别名 |
| **restore_persisted_state** | **`core/governed_router.py:538-556`** | **Block：硬编码 contracts 列表必须按 `__init__` 同逻辑重建，含 `enable_contract_split` 分支** |
| 前端 HTML | `web/index.html:786-787` | 是否暴露 `governed_v2` option；合并后 `full` 内部走 governed 就够，UI 可不改 |
| 前端 JS | `web/app.js:5, 162` | 若保留 `full` 作为默认，现有三元表达式兼容；若引入新 mode 值需扩展 |
| CLI 入口 | `main.py:22` | 从 `UnifiedRouter(...)` 改为 `build_router(..., router_mode="full")` |
| Eval 脚本 | `evaluation/eval_end2end.py:1273` 等 | ⚠️ **无需改动**——eval 传 `router_mode="router"` + `ENABLE_GOVERNED_ROUTER` flag 控制；合并后 `router` 仍然走 GovernedRouter |
| Legacy migration 脚本 | `scripts/migrate_phase_2_4_to_2r.py` | 验证老 session 文件能正常升级 |

**涉及文件范围**：
- 必改：`core/governed_router.py`、`api/session.py`、`services/chat_session_service.py`（若 ROUTER_MODES 调整）、`main.py`
- 可能改：`web/index.html`、`web/app.js`
- 必须验证：`tests/` 下使用 `UnifiedRouter(...)` 直接构造的 test 固件

**新增/修改的接口**：
- 若保留三值 mode 枚举：`full` 作为对外名，内部对应 GovernedRouter
- 若简化为二值：`ROUTER_MODES = {"agent", "naive"}`——breaking change，需 API 兼容层

#### 7.F.3 风险点

1. **Legacy session 不兼容**：老 A-path session 磁盘文件无 stance 字段 → restore 时 `IncompatibleSessionError`。需要强制迁移或兼容 fallback
2. **跨 mode session 迁移**：若某用户有混合 turn（前几轮 full、后几轮 governed_v2），合并后如何处理？建议在 `_restore_router_state` 里加兼容层
3. **Eval 基线漂移**：合并后，eval_end2end 和 production 路径一致，之前建立的 "full 基线" 不再存在；benchmark 数据需要重新打基线
4. **前端展示**：若保留 `full` UI 选项但内部走 governed，用户不会察觉；若决定暴露 `governed_v2` 让用户选，需要文案说明
5. **NaiveRouter 不受影响**——`_naive_router` 保留独立路径，用于 baseline 对比
6. **Coupling 到 Task Pack B**：Migration 是 B 在生产路径下真正生效的前提（A 路径下 AO 空、约束 cumulative 无载体）

#### 7.F.4 推荐前置动作

1. **先修 restore_persisted_state 硬编码 bug**——这个 fix 独立于 Migration 本身，先单独 PR 降低合并风险
2. **定义 legacy session 的兼容策略**：a) 启动时批量迁移；b) lazy migration（restore 时发现旧格式跑迁移）；c) 强制用户新建 session
3. **基线快照**：Migration 前跑一轮完整 benchmark（eval_end2end），作为"迁移前"基线
4. **灰度 flag**：可以加一个 `FORCE_GOVERNED_FOR_FULL` 过渡 flag，默认 false；切换时先 true-default 一段再删 flag
5. **清理 MISLEADING flag**：借 Migration PR 一起删除 `ENABLE_STANDARDIZATION_CACHE` 和 `ENABLE_DEPENDENCY_CONTRACT`（§6.5）

---

## Section 8. Extensibility Audit（Task Pack E 深入）

本节对 §4.3 列出的 5 处硬编码给出处置方案，并评估 Task Pack E 的工作量级。

### 8.1 双 YAML 去重方案（核心重构 #5）

**现状**：

| 字段 | `config/tool_contracts.yaml` | `config/unified_mappings.yaml` |
|---|---|---|
| `parameters.<param>.schema` | ✅ | — |
| `parameters.<param>.required` | ✅ | — |
| `parameters.<param>.standardization` | ✅ | — |
| `dependencies.{requires,provides}` | ✅ | — |
| `readiness.{required_task_types,required_result_tokens,requires_geometry_support}` | ✅ | — |
| `continuation_keywords` | ✅ | — |
| `action_variants[]` | ✅ | — |
| **`tools.<name>.required_slots`** | — | ✅ |
| **`tools.<name>.optional_slots`** | — | ✅ |
| **`tools.<name>.defaults`** | — | ✅ |
| **`tools.<name>.clarification_followup_slots`** | — | ✅ |
| **`tools.<name>.confirm_first_slots`** | — | ✅ |

**读取点**：
- `tool_contracts.yaml` → `tools/contract_loader.py:*`（一个 loader 类）
- `unified_mappings.yaml` → `core/contracts/stance_resolution_contract.py:12, 177-186`、`core/contracts/runtime_defaults.py:8, 49-53`、`services/config_loader.py`（需要进一步 grep 确认）、`shared/standardizer/constants.py`（见阶段 1 memory 提到的内联常量）

**去重方案（推荐）**：

将 `unified_mappings.yaml` 的 `tools.<name>` 段**合并进** `tool_contracts.yaml`，扩展后者 schema：

```yaml
tools:
  query_emission_factors:
    # 现有字段
    parameters: { ... }
    dependencies: { ... }
    readiness: { ... }
    continuation_keywords: [...]
    action_variants: [...]
    # 新增字段（从 unified_mappings.yaml 迁入）
    required_slots: [vehicle_type, model_year]
    optional_slots: [pollutants, season, road_type]
    defaults: { model_year: 2020 }
    clarification_followup_slots: [season]
    confirm_first_slots: []
```

**理由**：
- `tool_contracts.yaml` 已是 tool-level 的 "source of truth"，语义最完整
- `unified_mappings.yaml` 同时管非 tool 字段（vehicle_types、pollutants、seasons、road_types 等全局枚举）——这些**保留**在 `unified_mappings.yaml`
- 合并后 `unified_mappings.yaml` 降级为"标准化枚举字典"，`tool_contracts.yaml` 升级为"唯一的 tool 声明文件"

**改动面**：
- 迁移内容：9 个工具 × 5 个字段 = ~45 个 YAML key-value 对
- 改动 reader：
  - `core/contracts/stance_resolution_contract.py:12, 177-186` 改为读 `tool_contracts.yaml`
  - `core/contracts/runtime_defaults.py:49-53` 改为读 `tool_contracts.yaml`
  - `tools/contract_loader.py` 扩展 `ToolContractRegistry` 支持新字段
- 删除 `unified_mappings.yaml:tools` 段

**风险**：中等。mechanical 改动，但需要全仓 grep `unified_mappings.yaml`、`UNIFIED_MAPPINGS_PATH` 的读取点都要改

### 8.2 `_snapshot_to_tool_args` 逐工具硬编码（#2）

**现状**（`core/governed_router.py:427-533`）：6 个 tool 各一个分支，每个分支逐字段调 `read(slot_name)` + 类型 coercion（`as_list` / `safe_int`）

**选项 A：从 YAML 推导**

在 `tool_contracts.yaml` 中扩展 parameter schema，增加 `type_coercion`：

```yaml
parameters:
  pollutants:
    required: false
    schema: { type: array, items: { type: string } }
    type_coercion: as_list  # 新增
  model_year:
    required: true
    schema: { type: integer }
    type_coercion: safe_int  # 新增
```

然后用通用 loop 替代 6 个分支：

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
    # 特殊 case：allow_factor_year_default
    if allow_factor_year_default and tool_name == "query_emission_factors":
        args.setdefault("model_year", _get_default_model_year())
    return args
```

**选项 B：保留分支，但提取到独立模块**

`core/governed_router.py` 的 `_snapshot_to_tool_args` 移到 `core/snapshot_to_tool_args.py`，保留分支（易读但不声明式）。

**推荐**：选项 A。特殊逻辑（`allow_factor_year_default` / `pollutant_list_fallback` 的单元素解包）作为显式 post-processing hook，不能粗暴声明化。

**风险**：低-中。有 12 个单元测试已覆盖 `governed_router` 的 snapshot 行为（需 grep 验证），重构需保持行为一致

### 8.3 `ao_manager` 关键词映射（#3）

**现状**：

- `core/ao_manager.py:73-87 MULTI_STEP_SIGNAL_PATTERNS`：硬编码中英文 regex（`再`、`然后`、`接着`、`then`、`after that` 等）
- `:566-586 _extract_implied_tools`：硬编码工具关键词映射（`因子` → `query_emission_factors`；`扩散` → `calculate_dispersion` 等）

**处置方案**：

将这些关键词迁移到 `tool_contracts.yaml` 的 `completion_keywords`（与现有 `continuation_keywords` 对称）：

```yaml
tools:
  calculate_dispersion:
    continuation_keywords: [扩散, dispersion, 浓度, concentration, raster]
    # 新增：完成判定关键词
    completion_keywords: [扩散, dispersion, 浓度]
```

`MULTI_STEP_SIGNAL_PATTERNS` 继续硬编码（通用语言模式，非 tool-level），但可以抽到 `core/ao_manager_keywords.py` 独立文件增强可读性。

**风险**：低。纯数据迁移

### 8.4 NaiveRouter 工具白名单（#4）

**现状**：`core/naive_router.py:28-36 NAIVE_TOOL_NAMES` 硬编码 7 个工具名

**处置方案**：

在 `tool_contracts.yaml` 工具级加 `available_in_naive: true/false`（默认 true），naive router 过滤：

```yaml
tools:
  query_emission_factors:
    available_in_naive: true
  analyze_file:
    available_in_naive: false  # 复杂工具不进 naive baseline
  compare_scenarios:
    available_in_naive: false
```

`NaiveRouter._load_naive_tool_definitions`（`core/naive_router.py:107-115`）改为过滤 `available_in_naive`。

**风险**：低。如果未来加新工具，默认进 naive（需要决定是否默认 true）

### 8.5 `runtime_defaults.py`（#1）保留理由

**现状**：`core/contracts/runtime_defaults.py:10-14 _RUNTIME_DEFAULTS = {"query_emission_factors": {"model_year": 2020}}`；runtime 优先于 YAML defaults

**保留理由**（源码 `:41-45` 有显式注释）：

> When a slot has both YAML default and runtime-only default, runtime-only wins. Rationale: runtime defaults reflect actual router execution behavior; YAML defaults are declarative-level hints that may lag behind operational reality.

**意图分析**：
- YAML `defaults` 是"声明层的建议"——例如 tool_contracts 声明 `model_year: 2020`
- `_RUNTIME_DEFAULTS` 是"执行层的实际值"——当实际行为偏离声明时（例如 2020 年没数据时 router 实际用 2018），先在代码里覆盖再慢慢同步 YAML

**建议**：保留此机制，但加 CI check——`_RUNTIME_DEFAULTS` 的每个 entry 在 YAML 里如果存在不同值要警告；在代码里加一个注释说明当前 runtime=YAML（如果已同步）或 runtime=X 而 YAML=Y（如果有漂移）

**风险**：低。这是设计上的故意保留

### 8.6 Task Pack E 总体工作量级判断

**结论**：⚠️ **需要局部重构**（不是纯声明式可行，也不是大规模重构）

| 子项 | 工作性质 | 范围 |
|---|---|---|
| 8.1 双 YAML 合并 | 结构重构 | 中（~45 YAML entries + ~5 文件 reader） |
| 8.2 `_snapshot_to_tool_args` | 代码重构 | 小（单文件，12 UT 保护） |
| 8.3 `ao_manager` 关键词 | 数据迁移 | 小（YAML + 2 方法改 reader） |
| 8.4 naive 白名单 | 数据迁移 | 极小（YAML flag + 1 方法改 filter） |
| 8.5 runtime_defaults | 保留 + 加文档 | 极小（加注释 + 可选 CI check） |

**建议顺序**：先做 8.1（基础），再做 8.4/8.5/8.3（轻量），最后 8.2（依赖 8.1 的合并结果）。Task Pack D 推进时优先走"合并后"的 YAML 形态。

---

## Section 9. Dead Code / Legacy / Misleading 清单

### 9.1 Misleading Flags（代码层）

| Flag | 位置 | 现象 | 处置建议 |
|---|---|---|---|
| `ENABLE_STANDARDIZATION_CACHE` | `config.py:45` | 生产代码无 reader；仅 `tests/test_config.py:30` 断言 | **删除**（Migration PR 顺便） |
| `ENABLE_DEPENDENCY_CONTRACT` | `config.py:153-155` | 生产代码无 reader；`DependencyContract` 是 13 行空壳 | **删除 flag + 删除或激活 DependencyContract**（二选一） |

### 9.2 `DependencyContract` Stub 处置

`core/contracts/dependency_contract.py:1-13`：13 行，仅 `class DependencyContract(BaseContract): name = "dependency"`，docstring 写 "Phase 3 placeholder"。`BaseContract.before_turn/after_turn` 默认 no-op。

**处置选项**：

| 选项 | 说明 | 推荐度 |
|---|---|---|
| A. 删除 | 从 `governed_router.py:76, 92` 移除；删除文件；减少每轮两次无效调用 | ⭐⭐⭐ 推荐 |
| B. 激活（实现 Phase 3 slot 校验） | 实际做 meteorology-for-dispersion 等跨工具 slot 依赖检查 | ⭐ 只在 Phase 3 真正推进时 |
| C. 保留占位 | 维持现状 | ⭐⭐ 如果 Phase 3 近在眼前 |

### 9.3 异常文件（pip install 误写产物）

仓库根目录有两个文件：
- `=0.8.1`（4509 bytes）
- `=1.6.0`（0 bytes）

**来源推断**：`pip install package>=0.8.1` 的 `>` 漏掉导致 shell 把 `=0.8.1` 当作文件名创建。

**处置建议**：**直接删除**。无任何代码引用（`grep` 全仓 0 命中）。

### 9.4 运行时日志残留

根目录：
- `tmux-client-5419.log`（20 KB）
- `tmux-out-5421.log`（1 KB）
- `tmux-server-5421.log`（1.25 MB）——⚠️ **大文件**

**处置建议**：**直接删除 + 加入 `.gitignore`**（`tmux-*.log`）。

### 9.5 Temporary code-review 目录

`tmp_for_chatgpt_code_review/`：
- `INDEX.md`
- `README_COPY_USE.md`
- `core/`（含部分 core 代码副本，疑似用于 ChatGPT 外部 review）
- `evaluation/`（同上）

`grep` 代码引用：仅 `目录文件详细说明.md:93` 描述性提及，无活跃代码依赖。

**处置建议**：**归档（移到 `docs/archive/` 或类似）或删除**。当前根目录暴露临时性工作物，降低可读性。

### 9.6 根目录堆积的历史报告（20 个 MD 文件）

**PHASE 系列**（14 个）：`PHASE0_REPORT.md`、`PHASE1_*.md`（7 个）、`PHASE2_*.md`（4 个，含 `PHASE2R_WAVE1_REPORT.md`）、`POST_WP4_SNAPSHOT.md`

**DEEP_DIVE 系列**（3 个）：`DEEP_DIVE_1_STANDARDIZATION.md`（173 KB）、`DEEP_DIVE_2_TOOLS_AND_WORKFLOW.md`（293 KB）、`DEEP_DIVE_3_STATE_TRACE_CONFIG.md`（294 KB）——⚠️ **合计 760 KB**

**EXPLORATION 系列**（3 个）：`EXPLORATION_FOR_UPGRADE_DECISION.md`、`EXPLORATION_ROUND2.md`、`EXPLORATION_ROUND3_COGNITIVE_FLOW.md`

**其他**：`ARCHITECTURE_AUDIT_EMISSION_AGENT.md`（47 KB）、`CODEBASE_AUDIT_FOR_PAPER.md`（60 KB）、`CODEBASE_STATUS_REPORT.md`（55 KB）、`EMISSIONAGENT_CONVERSATION_UPGRADE_PLAN.md`、`MULTI_TURN_DIAGNOSTIC.md`、`BENCHMARK_PIPELINE_*.md`（3 个）、`EVAL_MULTISTEP_DIAGNOSTIC.md`、`CALCULATE_DISPERSION_IMPLEMENTATION_ANALYSIS.md`、`SYSTEM_FOR_PAPER_REFACTOR.md`、`目录文件详细说明.md`、`paper_notes.md`

**处置建议**：
- **归档到 `docs/archive/phase_history/`** —— 保留但从根目录移走
- 本次 audit 的 `docs/codebase_audit_phase2_prep.md` 成为新的"当前真相源"
- 特别注意：归档前确认没有新脚本/文档通过相对路径引用这些文件

### 9.7 Held-out benchmark 文件

根目录：
- `held_out_batch1.jsonl`（15 KB）
- `held_out_batch1_v2.jsonl`（21 KB）

`grep` 代码引用：仅 `目录文件详细说明.md:33` 提及"保留测试批次数据"；未找到脚本引用。

**处置建议**：**移到 `evaluation/held_out/` 或 `data/held_out/`**——benchmark 数据不应在根目录。

### 9.8 其他可疑文件

- `tmp_for_chatgpt_code_review/`：见 9.5
- `diagnose_hotspot_perf.py`（11 KB，根目录脚本）：未集成进测试/evaluation 体系，疑似一次性诊断脚本。**归档到 `scripts/diagnostics/`** 建议
- `verify_dispersion_fix.py`、`verify_map_data_collection.py`、`simulate_e2e.py`：同上，归档到 `scripts/verify/` 或 `scripts/dev/`
- `run_code.py`（16 KB）：根目录 Python 脚本；未见标准入口引用。**需人工确认**是否仍活跃

### 9.9 不是杂物（经过确认）

以下根目录项看似杂物，但扫描确认**仍在活跃使用**，**保留**：

| 项 | 证据 |
|---|---|
| `ps-xgb-aermod-rline-surrogate/` | `tests/test_real_model_integration.py:22` 引用；`PROJECT_SUMMARY.md:249` 描述为核心代理模型；`SYSTEM_FOR_PAPER_REFACTOR.md:488, 841` 引用 |
| `GIS文件/` | `preprocess_gis.py:9, 21` 直接读 shapefile；`static_gis/README.md:35` 描述预处理流程；`CODEBASE_STATUS_REPORT.md:916` 有数据结构说明 |
| `static_gis/` | API 层 `api/routes.py:510-527, 557-575` 加载 basemap/roadnetwork GeoJSON |
| `LOCAL_STANDARDIZER_MODEL/` | `services/model_backend.py:247`（USE_LOCAL_STANDARDIZER reader） |

### 9.10 处置优先级汇总

| 优先级 | 项 |
|---|---|
| 🔴 必须处理（清洁度影响开发） | 9.3（删除 `=X.Y.Z` 异常文件）、9.4（删除 tmux 日志 + `.gitignore`） |
| 🟡 建议处理（文档负担） | 9.2（决定 DependencyContract 存废）、9.5（归档 tmp_for_chatgpt）、9.6（归档历史报告）、9.7（移动 held-out jsonl） |
| 🟢 可选处理 | 9.1（Misleading flag 删除，与 Migration PR 合并）、9.8（归档诊断脚本） |
| ⚪ 不处理（活跃使用） | 9.9 全部 |

---

## Section 10. 近期变动热区快照

基于阶段 1 的 40-commit 扫描（`main` 分支，工作区干净）：

### 10.1 最近 25 个 commit 主题

集中在 Phase 2R / OASC / clarification / continuation / benchmark 诊断方向：

近 5 commit（按时间倒序）：
- `196d84e Phase 2 rescoping: LLMify rule-based decision points`
- `b1565df Audit Part 1: OA architecture reality check`
- `f5ae522 Diagnose dispersion-intent-without-data bug`
- `6eab9a2 Survey: benchmark construction pipeline v2 state`
- `04023d4 Stop Wave 5a after probe-limit calibration missed Stage 2 gates`

### 10.2 最近 40 commit 的文件命中数（热区）

| 目录 | 命中次数 | 说明 |
|---|---|---|
| `evaluation/` | **191** | 最活跃——pipeline_v2、benchmark 构造、ablation 脚本持续迭代 |
| `core/` | 47 | 中等活跃——contracts、router、memory 有持续修改 |
| `tests/` | 40 | 同步 core 的变更 |
| `docs/` | 23 | 文档更新 |

### 10.3 对 Phase 2 规划的含义

- **benchmark pipeline 是近期主战场**——Task Pack 推进时应协调 evaluation 团队的 ongoing work
- **core 仍在流动**——Phase 2 Task Pack 的 core 改动需要和 `core/contracts/` 近期变更协调（特别是 `clarification_contract.py` / `execution_readiness_contract.py` 的 split contract 改造）
- **tests 跟进及时**——基础设施健康
- **docs 跟进相对慢**——本次 audit 产出的文档是一次性补齐

---

## Section 11. Open Notes 给规划者

本节是开放评论，写我在审计中发现但上面各 section 未充分覆盖的事实和观察。

### 11.1 Task Pack 划分与代码现实的 mismatch

**11.1.1** Task Pack B 的名字"约束违反跨轮累积"暗示"激活已有机制"，代码现实是"从零搭建 writer pipeline"。**这个 Pack 的实际工作量接近 Task Pack D 的量级**（见 §7.B.2）。建议：
- 在 Phase 2 规划里重命名为"**建立约束违反数据流**"
- 明确前置 Migration（Task Pack F）——否则 B 的 AO 层累积在生产 A 路径下无效

**11.1.2** Task Pack A 的实际重心偏离规划描述。题面强调"追问生成"，但：
- `_build_probe_question` 已经 LLM-first（只有 `_build_question` 的 legacy 模板还是 rule-based）
- 真正的 rule-based 重灾区是**回复解析**——`parameter_negotiation.py`（426 行）和 `input_completion.py`（~470 行）两套独立 regex 状态机

建议：Task Pack A 重新定义范围为"**Reply parser LLMification + question template 收敛**"，前者工作量远大于后者。

**11.1.3** Task Pack C 的 gap 比预想小。字段、测试框架、渲染路径**都已经在**（`tools/file_analyzer.py:262 _build_data_quality_warnings` + `tests/test_file_analyzer_targeted_enhancements.py`），只需扩维度。Task Pack C 可以**合并进 Task Pack D 一起做**——两者高度耦合（C 检测质量问题，D 执行清洗），共用 data quality schema 最合理。

**11.1.4** Task Pack E（Extensibility audit）的名字暗示是"审计"，代码现实是"**局部重构**"（见 §8 结论）。名字低估了工作量。

### 11.2 架构层面的长期担忧

**11.2.1** `core/router.py` 11964 行这件事是**长期结构债**。Phase 2 Task Pack 多数和 router.py 交互（B 的 writer、Migration 的 `build_router`、E 的 `_snapshot_to_tool_args`）。建议 Phase 2 或 Phase 3 启动一个独立的"router.py 拆分"工作包——例如抽出 `GovernanceEngine`、`WorkflowEngine`、`ContinuationEngine`（阶段 1 memory 已提过）。

**11.2.2** A 路径（UnifiedRouter）和 B 路径（GovernedRouter）在**治理机制上完全不对称**——A 有 11964 行嵌入治理，B 有 6 个 contract 外加同一 11964 行的透传。Migration 不只是"切换哪个 router"，更是"**让生产代码长期跑在 contract 化的治理路径上**"。Phase 3 如果不拆 router.py，这个不对称会永远存在。

**11.2.3** 两份 YAML（`tool_contracts.yaml` + `unified_mappings.yaml`）的分工混乱（§8.1）已经造成**隐性认知负担**：开发者改一个工具时要记得改两份。越早合并越好。

### 11.3 证据留痕的评论

**11.3.1** `ARCHITECTURE_AUDIT_EMISSION_AGENT.md`（46 KB，2026-03-29）和本次审计是**独立完成**的。如果规划者对比两份文档发现不一致，以本次为准（本次更新、约束更严格、每条附证据）。

**11.3.2** `docs/codebase_audit_part1_oa_reality.md:9` 的 "full 通常会落到 GovernedRouter" 描述与代码矛盾（`api/session.py:55` + `governed_router.py:563-570` 证明相反）。建议该文件也做修订或归档。

**11.3.3** 阶段 1 标记的 2 个 MISLEADING flag 和 10 个 DORMANT flag（§2.2）——Phase 2 Task Pack 完成时建议清理 MISLEADING（§9.1），DORMANT 要么激活要么归档。

### 11.4 可能被忽略的细节

**11.4.1** `_RUNTIME_DEFAULTS`（`core/contracts/runtime_defaults.py:10-14`）**只对 `query_emission_factors.model_year=2020` 一个 entry 起作用**。这意味着："runtime 覆盖 YAML" 的机制理论上强大，实际只处理一个场景。Phase 2 不必扩展机制，但可以在 §8.5 的 CI check 里添加"如果 entry 数 > 3，发 warning"。

**11.4.2** `NaiveRouter` 独立状态存储（`naive_router_state/`）和 full/governed 共享存储（`router_state/`）——跨 mode 切换时 naive 的数据永远不会和 full/governed 混淆，这是好事；但意味着**eval 跑 naive 的结果无法和 full 共享 session 上下文**。

**11.4.3** `core/contracts/__init__.py:1-7` 一股脑 import 所有 Contract——如果新增一个 Contract，要同时改 `__init__.py`（这是轻量级硬编码，但有一致性要求）。

### 11.5 建议的 Phase 2 顺序

基于上面所有分析，推荐顺序：

1. **F（Migration）** —— 先修 `restore_persisted_state` bug（§7.F.4#1），独立 PR
2. **F 主体** —— `build_router` + `api/session.py` + legacy session 兼容策略
3. **E（Extensibility）的 §8.1 双 YAML 合并** —— 基础重构，降低后续 Pack 成本
4. **B（约束违反）** —— write pipeline 建立
5. **C+D 合并**（`analyze_file` 扩维度 + `clean_dataframe` 新工具）—— 共用 data quality schema
6. **A（Reply parser LLMification）** —— 独立于其他 Pack，最后做降低风险
7. **E 剩余（§8.2-8.4）** —— 扫尾

**Critical path**：F → E-8.1 → B，其他 Pack 相对并行。

---

## Appendix A. Audit Method

### A.1 审计原则

1. **Evidence first**：每条陈述附 `file:line` 或 `grep` 证据
2. **代码为真相源**：不依赖历史文档（`HANDOVER_*.md`、`codebase_audit_part*.md`、`ARCHITECTURE_AUDIT_*.md` 等）作为 ground truth，仅作"可能过时的参考"
3. **Full enumeration**：对 feature flag、YAML 字段、contract 子类、工具等完整列出，不抽样
4. **不修改代码**：整个审计过程只读
5. **不跑 benchmark**：不依赖 runtime 行为，只通过静态分析得结论

### A.2 审计流程

本次审计分三阶段：

**阶段 1**（前置 Codex 对话完成）：
- 仓库结构扫描
- 顶层入口定位
- Feature flag 完整提取和分类
- 近期 commit 热区统计

**阶段 2**（本文档主体）：
- Contract chain / Router 架构深入
- 工具清单与 Tool Contract
- AO 数据结构与生命周期
- 约束规则与依赖图
- Migration Surface 识别

**阶段 3**（本文档定稿）：
- 6 个 Task Pack 的现状评估
- Extensibility 深入（§8）
- Dead/Legacy 清理清单（§9）
- 整合成一份 audit 文档

### A.3 涉及工具

- `grep -rn <pattern> --include="*.py"` — 代码引用追踪
- `wc -l <file>` — 体量估计
- `ls -la` — 目录清查
- `Read` — 文件详细阅读（优先定向读，而非全文读）

### A.4 已知局限

1. **未读完 `core/router.py` 全文**（11964 行）——只做定向 grep 和分段 read。可能遗漏部分藏在深处的行为
2. **未读完 `tools/file_analyzer.py` 全文**（1629 行）——只读了开头和 `_build_data_quality_warnings` 附近
3. **未实际运行 benchmark 验证** Task Pack 的具体 fail 场景
4. **未深入前端 UI 逻辑**——只扫了 mode 选单和 API 调用点
5. **未穷尽扫 tests/**——对 tests 的引用只做关键词验证

---

## Appendix B. Evidence Conventions

本文档使用以下证据约定：

- **`file:line`** — 单个行号，指向定义或关键调用点
- **`file:line-line`** — 行号区间，指向完整函数或片段
- **`file:line, line, line`** — 多个离散行号，同一文件内
- **`grep "pattern"`** — 表示已用 grep 验证，通常后缀"命中/0 命中/仅命中 XX"
- **⚠️ 标注** — 关键冲突、bug、或与期望不符的发现
- **✅/❌/🟡/🔴/🟢** — 状态或严重度 icons
- **粗体 `code`** — 重要的类名、函数名、flag 名
- **Section 引用** — `§X.Y` 格式（§7.F 即 Section 7 子节 F）
- **数字后的 "X 行"** — 文件体量估计（`wc -l` 结果）
- **不使用 emoji 作装饰**——仅用于信号（severity / status）

---

*End of audit.*
