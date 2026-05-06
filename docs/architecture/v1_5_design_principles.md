# v1.5 Design Phase 2 — Part 1: 设计原则 + Anchors Compliance

**Document path**: `docs/architecture/v1_5_design_principles.md`
**Version**: **frozen** (拍板完成 2026-05-05, kirito approved)
**Last updated**: 2026-05-06
**Branch**: `phase9.1-v1.5-upgrade`

---

## §0. Document Status

| Field | Value |
|---|---|
| Status | **frozen** (kirito approved 2026-05-05) |
| Frozen tag (target) | `v1.5-design-frozen` (跟 Component #1, #2, #3, #4-13 集中文档一起打) |
| References | `EmissionAgent_Core_Anchors.md` (项目锚点, 优先级最高) |
| Referenced by | All Component design documents (#1 facade, #2 IntentResolver, #3 AO classifier, #4-13 集中文档) 引用本章作 ground truth |
| Frozen 后修改流程 | 不可改动. 任何改动须回到设计阶段 review |

---

## §1.1 项目定位 (不变, 来自 Anchors)

EmissionAgent 是首个针对**交通排放领域的领域治理 conversational agent**. 核心论点: framework deterministic + LLM semantic — 治理执行合法性而非治理 LLM 决策.

目标期刊: Transportation Research Part D (TRD) Q1, IF ~7.0.

v1.5 升级目标: 修复 v1.0 在 multi-step chain projection / ConversationState 协同 / shortcut path 治理覆盖等具体瓶颈, 强化领域治理在生产环境下的实际表现, **不改核心论点**.

---

## §1.2 Narrative — v1.0 vs v1.5 量化对比

论文 §4 + §6 narrative:

- **§4 描述 v1.5 完整架构** (含 ConversationState + IntentResolver multi-step planning + 11 核心组件 + 2 infrastructure)
- **§6 evaluation 主体是 concurrent v1.0 rerun vs v1.5 delta**. 历史 Phase 8.2.2.C-2 +65.9pp 数字降级为**附录或脚注**, 标注 "Apr 2026 LLM backend 数据, NaiveRouter behavior 受 LLM iteration depth 影响"
- 历史数字**不**作为核心 claim. 论文 §6 主体只引用 concurrent rerun delta, 避免 reviewer 质疑 "如何排除 LLM 进步本身解释 baseline 差异"
- **§5 Shanghai e2e 案例研究用 v1.5 数据** (Run 7 完整跑通, mode_A 修复后)
- **§7 future work** 改为 "extends v1.5 to v2 (skill mode + deeper localization)", 不是 "fixes v1.5 bugs"

数据策略来源: Phase 9.1.0 阶段 1a Step 2 reproducibility report 推荐 "v1.5 vs concurrent v1.0 rerun".

---

## §1.3 Anchors 4 个不可动摇要素 (绝对不动)

### 1.3.1 核心论点 — framework deterministic + LLM semantic

v1.5 强化方向:
- ConversationState facade 让 deterministic enforcement 在跨 turn / 跨 contract 层面有 single source of truth
- IntentResolver multi-step planning 让 LLM 主导 chain semantics, framework 强制 chain validity

核心论点不变.

### 1.3.2 选题与定位 — 架构 / 工程 / 系统贡献

v1.5 新增的 IntentResolver multi-step planning 看起来像 LLM 算法工作, 但实际是**架构层面**:
- chain projection 是新的架构组件
- chain validation 是 framework 工作
- LLM 只被 prompt 出 chain plan, 不改 LLM 本身, 不 fine-tune, 不 RL training

具体反驳论证见 Component #2 §3.2 防御性 framing 章节.

### 1.3.3 工作流分类 — 5 用户场景 + 6R 任务类型 + 3 类失败模式

| 维度 | v1.5 状态 |
|---|---|
| 5 用户场景 | 不动 |
| 6R 任务类型 (R1-R5 + R6 情景对比) | 不动 |
| 3 类失败模式 (multi-turn drift / 跳步执行 / 参数组合非法) | 不动 |

阶段 1 audit 暴露的具体瓶颈 (Run 7 mode_A / shortcut path bypass graph / PCM 文件上下文 bug) 都映射到现有 3 类失败模式之一, 不需要新增第 4 类.

### 1.3.4 评估架构 — 4 个评估层次

| 层次 | v1.5 影响 |
|---|---|
| Layer 1 标准化准确率 (96.97% 历史 baseline) | 不动 |
| Layer 2 端到端 | concurrent v1.0 rerun + v1.5 ablation, 7 个 run |
| Layer 3 真实案例 (Shanghai e2e) | v1.5 完整跑通 (mode_A 修复) |
| Layer 4 用户研究 | 升级完成后启动, 不在 v1.5 阶段 2 设计范围 |

---

## §1.4 ConversationState Facade — Governed-Only 严格隔离

ConversationState facade **必须是 governed_router 专属**, NaiveRouter 不读不写.

理由: 如果 NaiveRouter 也享受 facade 协调能力, baseline (Run 2 Naive) 会跟着享受 v1.5 改进, ablation delta 不再是干净 governance 贡献信号.

**隔离机制 (反映现状, 不引入新约束)**:

- NaiveRouter 代码不导入任何 facade 模块 (Step 2.5 §1.5 已验证, 天然隔离)
- facade 写入由 governed pipeline 触发 (OASCContract / IntentResolver / ClarificationContract / Reconciler / ExecutionContinuation 等)
- 共享 ToolRegistry 继续 read-only
- **持久化路径不强制分离**, 通过 session_id 命名区分 (governed_router 跟 NaiveRouter 已经 session_id 命名空间不同)

实施期 cc 验证: `grep -r "conversation_state_facade" core/naive_router.py` 必须**零命中**, 否则 STOP & report.

---

## §1.5 v1.0 数据保留 + 数据策略 + Trial 1 隔离原则

### 数据保留

- v1.0 frozen tag `edca378` + Phase 8.2.2.C-2 历史数据 `evaluation/results/phase8_2_2_c2/` 完整保留
- v1.5 数据写到 `evaluation/results/phase9_3_v1_5_ablation/`
- concurrent v1.0 rerun 数据写到 `evaluation/results/phase9_3_v1_0_concurrent_rerun/`

### 数据策略

- Phase 9.3 同时跑 v1.0 baseline (current LLM) + v1.5 (current LLM)
- 论文 §6 主表用 concurrent rerun delta
- 论文 §6 附录或脚注引用历史 +65.9pp delta, **不**作为核心 claim
- 论文 §4 baseline 描述明确 "frozen at edca378, current LLM"

### Trial Count Protocol (hybrid)

- Default 1 trial / task
- 自适应 3 trial / task: 跟历史 outcome 不一致的任何 task
- 抽样 5 task × 3 trial 作为 variance cross-check

### Trial 1 隔离原则 (关键)

每个 task 跑前**必须做 process-level reset**: 新 Python process / 清理 module-level 状态 / 清理 evaluation 副作用文件. 不是 task 跑完做 reset, 是 **task 跑前做 reset**.

理由: Step 2.5 trial 1 vs 2-5 trace 路径分歧暴露 module-level / filesystem-level state 污染. 必须 enforce 每 task 第 1 trial 是干净 governance path. 跟 component #13 (Filesystem hygiene) 直接关联, 不依赖人工记得.

---

## §1.6 工作流纪律

1. **设计阶段不开 audit 轮次** — 设计阶段主体是文档化 + 拍板, cc 主要做语法检查 + 代码 file:line 对齐 + mismatch 发现, 不开新 audit 任务

2. **实施阶段按 Wave 顺序推进** — 每 Wave 单独 commit, checkpoint 在架构层面验收 (不为 0.1pp 数据反复 audit). Wave 划分见集中文档 §11

3. **STOP & report 优先于 cc 自我解读** — 任何阶段 cc 触发 STOP 必须立即停, 等用户拍板. 不允许基于 cc 自己对发现的解释决定继续. 阶段 1a Step 1 cc 违反过 STOP 纪律 (e2e_ambiguous_002 outcome jump 没停继续写报告), 后续不允许

4. **设计偏离 Anchors 立即 stop** — 任何阶段 cc / 用户 / claude 发现潜在 Anchors 突破, 立即报告

5. **scope creep 监控** — 11 核心 + 2 infrastructure 是阶段 1 audit 数据沉淀的最终 scope, 设计 + 实施期间不允许加新组件除非有数据驱动的强支持

6. **架构决策跟工程决策分离**:
   - **架构决策** (用户拍板): ConversationState facade schema, IntentResolver multi-step planning prompt, AO state semantic 双轴定义, 任何跨 component 接口改动, 任何新 contract 引入
   - **工程决策** (cc 决定 + STOP & report): file:line 改动, 单元测试覆盖, commit 拆分, error handling 风格, 命名细节
   - 边界模糊时 cc 默认按架构决策处理, 让用户拍板, 不替用户决定

---

## §1.7 ChatGPT / Claude 级别 Multi-turn 流畅体验目标

v1.5 达到能力 1+2+3, 不强求能力 4:

| 能力 | v1.5 实施目标 | v1.5 不做 |
|---|---|---|
| 能力 1: 自动多步推进 | IntentResolver multi-step planning (#3) + ConversationState chain tracking (#1) + ExecutionContinuation 读 facade (#4) | 完全成熟的 chain repair 算法 (留 v2) |
| 能力 2: 隐式上下文 | ConversationState facade 协调 SessionContextStore + FactMemory + ao.metadata, 让 "再算一次" 能复用 last_referenced_params | 跨 session 的 long-term memory (留 v2) |
| 能力 3: 对话修正 | AO classifier REVISION 状态 (已实现) + ConversationState facade 标记 invalidated step + IntentResolver re-plan + Clarification + Reconciler 改读 facade (#5, #11) | 复杂的 conversational repair (留 v2) |
| 能力 4: 自然语言反馈节奏 | 不强求 | 留 v2 |

---

## §1.8 论文表述精度调整 List

阶段 5 论文写作 checklist (不是实施 target, 是写作期注意事项):

| # | 调整项 | 出处 |
|---|---|---|
| 1 | Anchors §3a "工具依赖图前向校验" 实际是 router-internal, 不是 contract-pipeline-level. v1.5 component #9 改这件事, 但论文 §4 表述要诚实反映 v1.0 / v1.5 各自状态 | 阶段 1b pre-audit §1.4 |
| 2 | DependencyContract 在 v1.0 是空壳, v1.5 才实施化. 论文 §4 描述 "contract pipeline" 时, v1.0 阶段实际只 OASC + Clarification 两个活 contract | 阶段 1b pre-audit §1.4 |
| 3 | "形式化交通排放工作流" (卖点 #1): templates 在 Python dataclass, 不是 YAML config. 论文表述要避免暗示 config-externalized | Phase 9.1.0 codebase audit Task 11 |
| 4 | §26 "10 工具 production-ready": 9/10 工具的 `preflight_check` 是 BaseTool 默认 no-op. 真前向校验是 `validate_tool_prerequisites`. 论文不要混淆 | Phase 9.1.0 codebase audit Task 11 |
| 5 | NaiveRouter `max_iterations=4` 在原 LLM 下 56% task 提前停, 在 deepseek-v4-pro 下 100% 跑到上限. NaiveRouter 行为 LLM-dependent, 论文 §4 baseline 描述要包含这个 nuance | Step 2.5 §4.3 |

---

## §1.9 v1.5 阶段 2 - 5 不做的事 (平行轨道纪律)

- 前端 (v4 + Claude Design 在另一个对话)
- 阿里云部署 (kirito 在做)
- 用户研究协议设计 (升级完成后启动)
- IRB 提交 (升级完成后启动)
- lhb 同步 (kirito 已完成)

---

## §1.10 Phase 9.3 数据可信度前置条件

Phase 9.3 ablation 跑之前必须 commit 的 fix list, **单独 commit 进 baseline, 不等 v1.5 完整设计**:

| # | Fix | 已完成? | 备注 |
|---|---|---|---|
| 1 | Trace race fix (`Trace.to_dict` vs `_attach_oasc_trace`) | ✓ 已完成 (commit `91f51a7` + `34c2758`, tag `v1.5-trace-fix-verified`) | 阶段 1 + 1b Option A |
| 2 | Filesystem hygiene + state cleanup protocol (Trial 1 隔离原则配套实施) | ✗ 未完成 | component #13, Phase 9.1.1 启动前实施 |
| 3 | llm_telemetry trace key (cache/token/wall_time observability) | 部分完成 (cache telemetry 在阶段 1a Step 2 加过, commit `3565500`) | component #12, Phase 9.1.1 启动前完整实施 |

### 实施时机

Phase 9.1.1 启动前完成 #2 + #3 (#1 已经完成). 完成后打 tag `v1.5-eval-infra-ready`. 这是 Phase 9.3 ablation 的 "evaluation infrastructure 就绪" 锚点.

### 为什么前置

这 3 件事是 **evaluation infrastructure 升级**, 不是 v1.5 核心架构. 但 Phase 9.3 数据可信度依赖. 如果等 v1.5 完整设计 (架构) 完成后才搞 evaluation infrastructure, 跑 Phase 9.3 时才发现数据不可分析, 整轮 ablation 重做. 不绕过.

### 跟 v1.5 阶段 3 实施顺序关系

```
现在 (v1.5-design-frozen 之后)
  │
  ├─ 阶段 2.5: Eval infrastructure 升级 (Wave 1)
  │   ├─ Component #13 Filesystem hygiene
  │   ├─ Component #12 llm_telemetry 完整实施
  │   └─ tag v1.5-eval-infra-ready    ◀ Phase 9.3 前置
  │
  ├─ 阶段 3: v1.5 架构实施
  │   ├─ Wave 2: Phase 9.1.1 (Component #1, #9, #2)
  │   ├─ Wave 3: Phase 9.1.2 (Component #3, #4, #5)
  │   ├─ Wave 4: Phase 9.1.3 (Component #6, #7, #8, #10, #11)
  │   └─ tag v1.5-architecture-frozen
  │
  └─ 阶段 4: Phase 9.3 完整 ablation
      ├─ concurrent v1.0 rerun (current LLM)
      ├─ v1.5 ablation (Run 1-7)
      └─ tag v1.5-data-frozen
```

阶段 2.5 工作量小 (~半天-1天), 但是 Phase 9.3 数据可信度的硬前置.

---

## Part 1 拍板状态

**拍板完成**: §1.1 - §1.10 全部 frozen.

后续 Part 2 (Component #1, #2, #3, #4-13 集中文档) + Part 3-5 (实施 / 数据 / 论文阶段) 引用本章作 ground truth. 任何偏离立即 stop & report.

---

## 4 Frozen 文档清单 (设计阶段终点)

`v1.5-design-frozen` tag 包含的完整文档:

1. `docs/architecture/v1_5_design_principles.md` (Part 1, **本文档** FROZEN)
2. `docs/architecture/v1_5_conversation_state_facade.md` (Component #1, FROZEN v2)
3. `docs/architecture/v1_5_intent_resolver_multi_step.md` (Component #2, FROZEN v2)
4. `docs/architecture/v1_5_ao_classifier_dual_axis.md` (Component #3, FROZEN v2)
5. `docs/architecture/v1_5_components_4_13_consolidated.md` (Component #4-13, FROZEN v2)

---

**End of v1.5 Design Phase 2 Part 1 — Design Principles + Anchors Compliance — frozen**

下一步: tag `v1.5-design-frozen` → Wave 1 实施 (Phase 2.5 evaluation infrastructure: Component #12 llm_telemetry + Component #13 Filesystem hygiene).
