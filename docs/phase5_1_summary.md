# Phase 5.1 完成总结 — Task Pack A 基础设施轮

Date: 2026-04-29
Branch: `phase3-governance-reset`
Status: 主体收尾, 不进 Phase 5.2 实现动作

---

## §1 完成清单

| Sub-task | 状态 | Commit | 改动 | 关键交付 |
|---|---|---|---|---|
| A.1 LLMReplyParser 模块 | ✅ | `cf4fa71` | +666 lines (3 files new) | `core/reply_parser_llm.py` (274 lines), `config/prompts/reply_parser.yaml` (58 lines) |
| A.2 parameter_negotiation 三层 | ✅ | `e6c0ab5` | +727/-11 (6 files) | 三层解析 (fast path → LLM → legacy regex), `source` 字段枚举, sync→async 桥接, 9 integration tests |
| A.3 input_completion 三层 | ✅ | `55b00de` | +667/-82 (6 files) | 三层解析接入, 限定参数值场景, 6 integration tests |
| A.5 reply_parser.yaml | ✅ | `cf4fa71` | (与 A.1 同 commit) | F1 (confidence 标记), F2 (constraint_violations 仅供参考), F3 (candidate_values 唯一合法集) |
| Stage 2.5 instrumentation | ✅ | `b95c199` | +71/-1 (2 files) | LLMReplyParser process-level call counters, `trace_steps` 导出, aggregation 函数 |
| Stage 2.6 LLM Layer coverage | ✅ | `8d1691c` | +232 lines (1 file new) | 5 个 unit test, 边角输入 + F2/F3 prompt 措辞验证 |
| Round 4b β-recon | ✅ | 未 commit (tmp) | 180-task 全量 Cell A 单 cell | A.2/A.3 触发频率表, 决定 β 跳过 |

注: A.4 (`_build_question` 硬编码清理) 在 Phase 4 已完成, 与 Phase 5.1 无关。

---

## §2 测试规模演化

| 阶段 | tests | delta |
|---|---|---|
| Round 1 之前 baseline | 1258 | — |
| Round 1 (A.1 + A.5) | 1280 | +22 |
| Round 2 (A.2) | 1297 | +17 |
| Round 3 (A.3) | 1311 | +14 |
| Round 4a-merged | 1311 | 0 |
| Stage 2.5 instrumentation | 1311 | 0 |
| Stage 2.6 LLM Layer coverage | 1316 | +5 |

总增量 **+58 tests**, **0 regression 全程** (每轮 full suite pass 验证)。

Test 文件分布:

| 文件 | tests | 性质 |
|---|---|---|
| `tests/test_reply_parser_llm.py` | 22 | LLMReplyParser 单元 (5 decision + failure modes + F1+F2+F3 prompt + enum/dataclass smoke) |
| `tests/test_parameter_negotiation_fast_path.py` | 8 | A.2 Layer 1 fast path (regex) |
| `tests/test_parameter_negotiation_llm_integration.py` | 9 | A.2 caller 集成 (三层调度 + _detect_3layer_protocol_degreeA) |
| `tests/test_input_completion_fast_path.py` | 8 | A.3 Layer 1 fast path (regex) |
| `tests/test_input_completion_llm_integration.py` | 6 | A.3 caller 集成 (三层调度 + source 追踪) |
| `tests/test_reply_parser_llm_layer_coverage.py` | 5 | Stage 2.6: colloquial / multi-slot / ambiguous / F2 / F3 边角覆盖 |

---

## §3 Round 4b β-recon 关键发现

### 数据采集

- **范围**: 180 task 全量 benchmark (9 categories × 20 tasks), Cell A only (flag=OFF)
- **采集字段**: `trace_steps` (A.2/A.3 step_type 过滤), `llm_reply_parser_stats_snapshot`
- **Wall clock**: 1290s (21.5min)
- **位置**: `/tmp/round4b_beta_recon/cell_a/` (未 commit)

### 发现

**A.2 (parameter_negotiation 三层) — 0/180 触发**

标准器 LLM cascade 对全部 ambiguous 输入的 confidence ≥ 0.85, 直接 resolve 不抛 `BatchStandardizationError(negotiation_eligible=True)`。A.2 入口条件未满足 → parameter_negotiation 路径从未激活 → LLMReplyParser 从未在 A.2 caller 中被调用。

**A.3 (input_completion 三层) — 15/180 = 8.3% 触发, 但 LLM Layer 未真正介入**

| category | A.3 触发 task 数 | 占比 |
|---|---|---|
| multi_step | 10/20 | 50% |
| multi_turn_clarification | 2/20 | 10% |
| constraint_violation | 3/25 | 12% |
| 其余 6 类 | 0/115 | 0% |

31 个 trace_steps 分布:
- 15 × `input_completion_required` (source 空)
- 8 × `input_completion_confirmed` (source=option_selection)
- 8 × `input_completion_failed` (source 空)

**关键: `source=llm_parsed` 出现 0 次** — 即使 A.3 路径激活, 用户回复仍由 Layer 1 fast path 或 Layer 4 legacy regex 截胡, LLM Layer 从未被实际调度。

**LLMReplyParser call_count = 0 全域** (Stage 2.5 计数器确认)。

### 含义

handoff §4.2 假设 ("A.2/A.3 修完 multi_turn_clarification fail 转 PASS") 因果链错位:

- `multi_turn_clarification` 16 条 fail 走的是 **ClarificationContract** (governance 层 Stage 2 LLM bundle), 不是 A.2/A.3 reply parser
- ClarificationContract 在 180 task 中触发 248 次, `stage2_hit_rate` 34.7% — 它跟 A.2/A.3 是两条独立路径
- A.2/A.3 修复无法影响 multi_turn_clarification PASS/FAIL, 因为修复的代码路径根本不在那条 task 的执行轨迹上

### 论文叙事影响

Phase 5.1 不能 claim "LLM reply parser 修了 benchmark multi-turn clarification fail"。准确叙事见 §5。

---

## §4 Phase 5.1 收尾标准 (重定后)

原计划 Phase 5.1 验收 = benchmark 增益验证 (β multi_turn_clarification × n=5 × 双 cell 200 runs + γ regression × n=3 × 60 runs)。

β-recon 数据公布后, 收尾标准重定为 **"基础设施轮 + 0 regression"**:

| 完成项 | 证据 |
|---|---|
| ✅ 三层 reply parser 架构 (fast path → LLM → legacy regex) 落实 | A.2 + A.3 wiring commits (`e6c0ab5`, `55b00de`) |
| ✅ LLM Layer 单元测试覆盖 | Stage 2.6 5 个 test, mock LLM 验证边角输入 |
| ✅ Layer 命中分布 instrumentation 通路打通 | Stage 2.5 counters + trace_steps export |
| ✅ 全程 0 production regression | 1316 tests pass |
| ✅ F1/F2/F3 锁定原则在 prompt YAML + LLMReplyParser + 测试中落实 | `reply_parser.yaml` + `test_reply_parser_llm_layer_coverage.py` Test 4/5 |

跳过 (有数据支撑的跳过):

| 跳过项 | 理由 |
|---|---|
| ❌ β multi_turn_clarification × n=5 × 200 runs | β-recon 证明 A.2/A.3 不在 multi_turn_clarification 路径上, 跑了等于基于错误前提 |
| ❌ γ regression × n=3 × 60 runs | A.2/A.3 在 benchmark 上几乎不触发 → regression 风险面极小, 守门不必要 |
| ❌ β multi_step × n=5 × 100 runs | A.3 虽然在此类 50% 触发, 但 LLM Layer 从未被实际调度 (source=llm_parsed 0 次); 跑 multi_step β 验证的是 fast path / legacy regex, 不是 LLM Layer |

---

## §5 论文 §5.2 Case C 叙事校准

### 原叙事 → 新叙事

| | 原 handoff 叙事 | β-recon 后校准 |
|---|---|---|
| 提案 | A.2/A.3 修了 multi_turn_clarification 4 条 fail | **撤回** — 因果链不成立 (ClarificationContract vs reply parser 是两条独立路径) |
| 新提案 | — | 三层 reply parser 兜底架构 + 标准器 cascade 联合处理 colloquial 输入 |
| 不 claim | — | "LLM parser 修了具体 task PASS/FAIL" |
| 改 claim | — | "三层架构覆盖不同失败模式: 标准器 cascade 处理高频 colloquial, fast path 处理结构化回复, LLM Layer 是边角 case 兜底" |
| LLM Layer 存在性证据 | — | Stage 2.6 5 个 unit test (`test_reply_parser_llm_layer_coverage.py`), 不是 benchmark 数字 |

### 跟 lhb 讨论项

论文大纲 §5.2 lhb 批注高密度对齐:

> "如果没有这个机制, 交通排放分析中会出现什么具体的、领域特有的错误?"

当前回答: 在标准器无法可靠 resolve 用户回复的边角 case (多义 colloquial 表达 / code-switch / 高度模糊回复) 下, 没有 LLM Layer 兜底会导致 turn 超过 `max_clarification_attempts` 直接 fail。

待 lhb 评估:
- 这个回答是否够支撑 §5.2 Case C
- 是否需要构造针对 LLM Layer 的真实用户场景作为实证补充

备选方案: 后续 user study 阶段 (Phase 5 之后) 可构造专门触发 LLM Layer 的 benchmark task (标准器 confidence < 阈值 + fast path 不命中), 作为 §5.2 Case C 的实证补充。这是 handoff §4.4 "§9 评估" 范围的事。

---

## §6 Phase 5.2 启动条件

- ✅ Phase 5.1 主体收尾 (本文档就位)
- ✅ 当前分支 `phase3-governance-reset` 工作树干净 (已验证: `git status` 只有 2 个 untracked `.docx` 文件, 无 staged/unstaged 改动)
- ✅ `governed_router.py` 116 行 WIP 已 stash (`stash@{0}: On main: WIP: Step 1.B decision field Q3 defer + trace`)
- ✅ Phase 5.2 范围明确 (handoff §4.2 §5.2 + 升级计划 §7.3 6 个 sub-task)

Phase 5.2 estimated 1-1.5 周, 完成后进 Phase 5.3 Final Benchmark。

---

## §7 Phase 5 完成后 followup 清单

以下事项在 Phase 5.1 期间发现但明确划在范围外, 列清避免遗漏:

| # | 事项 | 发现阶段 | 处理时机 |
|---|---|---|---|
| 1 | `e2e_constraint_002` / `e2e_constraint_046` 在当前分支 Cell A FAIL — Phase 3-4 引入的 regression (相对 v8_fix_A baseline), 与 Phase 5.1 无关 | Round 4b Stage 1 | Phase 5.3 Final Benchmark 之后 audit |
| 2 | `router.py` 直访 `_memory.session_confirmed_parameters` (private attr) — 封装为 `ao_manager.get_confirmed_parameters()` public getter | Round 2/3 | Phase 5.2 完成后或 Phase 5.3 后评估 |
| 3 | LLMReplyParser 在 A.2/A.3 caller 路径中每 turn 新建实例 — 不影响正确性, GC 浪费 | Stage 2.5 recon | Phase 5.3 之后或论文写作期间 |
| 4 | `smoke_10.jsonl` "smoke=true 单轮 + smoke=false 多轮" 混编设计 — 是设计非 bug, 但文件名易误导 | Round 4a-merged | Phase 5.3 后 rename 或加 README 说明 |
| 5 | A.2/A.3 在 benchmark 上几乎不触发 — 需扩 benchmark 设计针对 LLM Layer 的 task (标准器 confidence < 阈值 + fast path 不命中) 才可拿到 LLM Layer 真实 trace 证据 | Round 4b β-recon | Phase 5 之后 (handoff §4.4 "§9 评估" 范围) |
