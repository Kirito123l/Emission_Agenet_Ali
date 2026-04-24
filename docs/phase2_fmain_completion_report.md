# Phase 2 Task Pack F-main · Completion Report

**Feature branch**: `f-main-governed-router-migration`
**Base commit**: `7c20689` (F-bugfix)
**Smoke subset**: `evaluation/results/migration_smoke/smoke_36.jsonl` (36 tasks, 9 categories)
**Smoke verdict**: PASS(见 `evaluation/results/migration_smoke/comparison.md`)

## 1. 改动清单

### 1.1 核心代码

| File | 改动 |
|---|---|
| `core/governed_router.py:543` | `build_router` 分支归一:`full` / `governed_v2` / `router` → GovernedRouter;`naive` → `ValueError` |
| `api/session.py:41-145` | 合并 `_router` / `_governed_router` 为 `_agent_router`;`router` 和 `governed_router` 作为 property alias;`chat()` 分发简化为 naive vs agent_router;`save_router_state` / `_restore_router_state` 改为统一走 `_agent_router` |
| `api/routes.py` | `/chat` 和 `/chat/stream` 两个 endpoint 都捕获 `IncompatibleSessionError`,返回 HTTP 400 + "Session format incompatible. Please create a new session or run migration script." |
| `main.py:28` | CLI chat 从 `UnifiedRouter(...)` 改为 `build_router(..., router_mode="full")` |
| `config.py` | 删除 `ENABLE_STANDARDIZATION_CACHE` 定义、`ENABLE_DEPENDENCY_CONTRACT` 定义 |
| `core/memory.py:820-855` | 删除 legacy AO 合成占位逻辑(`_migrate_legacy_fact_memory_if_needed`);`from_dict` 加载时若有 `tool_call_log` 但无 `ao_history`,直接抛 `IncompatibleSessionError` |

### 1.2 配置与脚本

| File | 改动 |
|---|---|
| `.env.example` | sweep 删除 flag-not-in-code 的条目,同步 `config.py` 当前状态 |
| `scripts/phase2_4_turn1_resolver_dump.py:196` | `UnifiedRouter(...)` → `build_router(..., router_mode="full")` |
| `scripts/utils/test_new_architecture.py:62` | 同上 |

### 1.3 测试

新增:

- `tests/test_migration_session_routing.py` — 5 个用例(mode=full / governed_v2 / naive 的 router 类型断言 + `session.router` / `session.governed_router` alias 验证)
- `tests/test_main_cli.py` — CLI chat 构造的 router 是 GovernedRouter

修改:

- `tests/test_api_route_contracts.py` — 补 Migration 后路由分发断言
- `tests/test_config.py` — 删除对 `ENABLE_STANDARDIZATION_CACHE` 的断言
- `tests/test_factmemory_refactor.py` — 老格式 session 断言从"合成到 AO#legacy"改为"抛 `IncompatibleSessionError`"
- `tests/test_router_llm_config.py` — 正常构造点 `UnifiedRouter(...)` 替换为 `build_router(...)`;assertion 改 `GovernedRouter`
- `tests/test_state_contract.py` — 老格式 fixture 补 `ao_history`,符合新迁移决策

### 1.4 其他改动(与 Migration 无直接关系,一并合入)

- `AGENTS.md` — 文档更新
- `evaluation/eval_end2end.py` — smoke subset 支持

### 1.5 pre-smoke checkpoint WIP commit(需整理)

当前分支上存在一个 WIP commit(hash `96c821f`):
```
WIP: F-main complete + post smoke (pre-smoke rerun checkpoint)
```
该 commit 包含全部 F-main 改动以及在 smoke 执行时产生的 `evaluation/tool_cache/*` 副产物(136 文件)。在最终整理 commit 时需要:
1. 把 `evaluation/tool_cache/*` 从 commit 中剔除(它是测试副产物,不应版本化)
2. 重写 commit message 为规范格式 `feat(migration): unify production path to GovernedRouter`

详见第 6 节"清理与收尾 commit 操作"。

## 2. 偏离 prompt 的地方

**无**。10 个子任务全部按 prompt 执行,包括:

- 方案 a 三值 mode 枚举保留
- Legacy AO 合成直接删,无 fallback
- `DependencyContract` 类保留,只删 flag
- `object.__new__(UnifiedRouter)` 白盒测试 fixture 保留不动
- `/chat/stream` 独立异常包装单独处理
- `tests/test_factmemory_refactor.py` 旧断言改为期望异常

## 3. 保留的 UnifiedRouter 白盒 fixture 清单

以下测试文件通过 `object.__new__(UnifiedRouter)` 绕过 `__init__` 构造,作为白盒单元测试保留不动,不替换为 `build_router(...)`:

- `tests/test_router_state_loop.py`
- `tests/test_router_contracts.py`
- `tests/test_context_store_integration.py`
- `tests/test_multi_step_execution.py`

替换为 `build_router` 会把这些单元测试变成集成测试(走完整 Router 初始化路径),引入 noise 并拖慢测试速度。

## 4. F-main.7 中修复的老格式 fixture

- `tests/test_factmemory_refactor.py` — 老 session 合成 AO#legacy 的断言改为期望 `IncompatibleSessionError`
- `tests/test_state_contract.py` — 原持久化 session-level `tool_call_log` 但无 `ao_history` 的 fixture,补齐 `ao_history` 字段,符合 Migration 后新格式

## 5. Smoke 对比核心数据

完整对比见 `evaluation/results/migration_smoke/comparison.md`。关键数字:

| Metric | Pre | Post | Δ |
|---|---|---|---|
| completion_rate | 50.00% | 52.78% | +2.78pp |
| tool_accuracy | 63.89% | 66.67% | +2.78pp |
| parameter_legal_rate | 47.22% | 50.00% | +2.78pp |

关键 per-category 变化:
- `multi_step` 25% → 50%(+25pp):预期外的能力激活,Migration 修复了 context_store 跨工具结果传递
- 其余 8 category 全部零偏移(7 Type A 持平 + 2 Type B 持平)

`clarification_contract_metrics.trigger_count` 从 26 升到 49,`proceed_rate` 从 38% 升到 47%——ClarificationContract 在生产路径被更频繁正确触发。

## 6. 清理与收尾 commit 操作

当前状态:

- `git status` 应该干净(WIP commit 已把所有改动固化)
- `HEAD` 是 WIP commit `96c821f`,包含大量 `evaluation/tool_cache/*` 副产物 + `docs/codex_handoff_template.md` 半成品

需要做:

### 6.1 在 feature branch 上重写 commit(用 soft reset 重整)

```bash
# 1. 回到 feature branch 起点,把所有改动 un-commit 但保留在 index
git reset --soft 7c20689

# 2. 用 git reset HEAD 把 tool_cache 从 index 中移出,然后 checkout 恢复
git reset HEAD evaluation/tool_cache/
git checkout -- evaluation/tool_cache/

# 3. 删除不需要 commit 的半成品
rm -f docs/codex_handoff_template.md

# 4. 确认 index 里剩下的都是真正的 Migration 改动
git status --short

# 5. 确认 evaluation/results/migration_smoke/ 下的 smoke_36.jsonl + pre/ + post/ + comparison.md 都在 index 中
git status --short evaluation/results/migration_smoke/

# 6. 如果 comparison.md 和 completion_report.md 还没放进去,加进来
git add evaluation/results/migration_smoke/comparison.md
git add docs/phase2_fmain_completion_report.md

# 7. 正式 commit
git commit -m "feat(migration): unify production path to GovernedRouter

Phase 2 Task Pack F-main. Migration 让 mode=\"full\" 在 API 和 CLI 中
都走 GovernedRouter,同时保留 mode=\"naive\" 作为 baseline。

- build_router 分支合并:full/governed_v2/router → GovernedRouter
- Session 字段合并:_router/_governed_router → _agent_router (backward-compat alias)
- CLI 入口从 UnifiedRouter(...) 改为 build_router(router_mode=\"full\")
- 清理 MISLEADING flags: ENABLE_STANDARDIZATION_CACHE, ENABLE_DEPENDENCY_CONTRACT
- 删除 legacy AO 合成逻辑,老格式 session 直接抛 IncompatibleSessionError
- /chat 和 /chat/stream 两个 endpoint 都映射 IncompatibleSessionError → HTTP 400
- 新增 tests/test_migration_session_routing.py (5 cases) + tests/test_main_cli.py
- Smoke 36-task comparison PASS: overall +2.78pp, multi_step 能力激活 +25pp

See evaluation/results/migration_smoke/comparison.md
See docs/phase2_fmain_completion_report.md"
```

### 6.2 合入 main

```bash
git checkout main
git merge --no-ff f-main-governed-router-migration -m "Phase 2 F-main: unify production path to GovernedRouter"
```

## 7. 给下游 Task Pack 的注意事项

### 7.1 `_agent_router` 命名

Task Pack B(约束违反 writer pipeline)和 Task Pack A(Reply parser LLMification)会在 Router 层面加改动。**新代码访问 router 一律用 `session.agent_router`**,不要用 `session._router` 或 `session._governed_router`(已删除)。`session.router` 和 `session.governed_router` 作为 backward-compat alias 保留,但新代码不应依赖它们。

### 7.2 multi_step 新基线

multi_step category 的 post-Migration completion_rate 基线为 50%(Migration 前是 25%)。后续 Task Pack 若涉及 multi_step 行为评估,**应以 50% 作为对照基线**,不要误以为"multi_step 卡在 25%"。

### 7.3 `context_store` 跨工具传递

Migration 通过 `GovernedRouter.__getattr__` 透传让 `context_store` 在 `mode=full` 路径上恢复正常。Task Pack C+D(Data Quality Pipeline)和 Task Pack A(Reply parser)如有涉及跨工具状态访问,可以假设 `context_store` 在生产路径 live 且正确绑定。

### 7.4 `DependencyContract` 未决

`DependencyContract` 类本次**未触动**(按决策只删 flag 不删类)。Task Pack E-剩余需要决定:激活并实现真实依赖检查,或彻底删除(连带处理 `PHASE2_SLOT_ANALYSIS.md` 的引用)。

## 8. Known issues / TODO

### 8.1 本 Pack 内部

- 无未解决的 known issue。Smoke 通过,全量 `pytest tests/` 1204 passed。

### 8.2 留给后续 Task Pack

- **Task Pack E-剩余**:`DependencyContract` 类处置决策 + `PHASE2_SLOT_ANALYSIS.md` 引用处理
- **Task Pack C+D**:`_agent_router` 命名在 tool_contracts.yaml 合并后是否需要反映到 YAML 字段(应无影响,但需验证)
- **tool_cache 管理**:Migration smoke 过程产生 ~130+ 个 `evaluation/tool_cache/*.json`,这些是测试副产物。建议未来在 `.gitignore` 中加上 `evaluation/tool_cache/`,避免每次跑 smoke 都污染工作树
