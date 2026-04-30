# Phase 5.3 Round 2 — A + B + E narrow 修复设计文档

Date: 2026-04-30
Status: Round 2 design complete; user decisions closed; ready for Round 3 implementation planning.

---

## §1 必读文档总结

1. **phase5_3_round1_5_design_audit.md** — 4 个 multi_turn_clarification fail task 的设计层 audit，揭示 5 个 Class 缺陷 (A=ClarificationContract 实现 bug, B=clarify-grounding 设计缺口, C=无证据, D=AO 设计缺口, E=跨组件协调)，推荐 Round 2 修 A+B reconciliation + Round 3 修 E narrow chain handoff。

2. **phase5_2_summary.md** — 两条核心架构论点落地：agent 不知道数据库内容 (6 处硬编码消除) + 加新工具不需改 agent 代码 (3 处工具注册硬编码消除，YAML 声明式驱动)，全程 0 regression (+46 tests)。

3. **phase5_1_summary.md** — β-recon 关键发现：multi_turn_clarification 16/20 fail 走 ClarificationContract 而非 A.2/A.3 reply parser，LLM reply parser 0 次被实际调度，Phase 5.1 不能 claim "LLM reply parser 修了 benchmark fail"。

4. **phase3_case_driven_design.md §7** — F1(置信度不覆盖 LLM decision)、F2(领域规则 governance-owned, 不注入 LLM prompt)、F3(reply LLM 枚举值来自 ReplyContext) 三个锁定原则，是 A+B 修复设计的 ground truth。

5. **phase4_pcm_redesign.md** — PCM 在 flag=false 时 83% short-circuit Stage 2，推荐 Option B (flag=true 时 PCM → advisory + LLM decision field 主导)，Phase 4 实现已落地 Option B + Option C fallback。

---

## §2 修复方法论

### §2.1 PCM 在决策链中的真实位置

#### §2.1.1 当前分支 PCM 默认 mode

`config.py:178`:
```python
self.enable_llm_decision_field = os.getenv("ENABLE_LLM_DECISION_FIELD", "false").lower() == "true"
```

默认值 `false`。无 `.env` override。**生产默认 mode = PCM hard-block (Option C fallback)**。

#### §2.1.2 Round 1.4 governance_full 跑分时 PCM mode

完整路径:
```
evaluation/results/phase5_3/round1_4_sanity/governance_full/rep_1/config_snapshot.json
```

关键字段:
- `ablation.mode`: `"governance_full"`
- `ablation.mode_env.ENABLE_LLM_DECISION_FIELD`: `"true"`
- `ablation.mode_env.ENABLE_CONTRACT_SPLIT`: `"true"`
- `ablation.mode_env.ENABLE_GOVERNED_ROUTER`: `"true"`
- `ablation.mode_env.ENABLE_CLARIFICATION_CONTRACT`: `"true"`

**governance_full mode 下 decision field 是开启的，PCM 处于 Option B advisory mode**。

config.py 默认 `enable_llm_decision_field = False`，无 `.env` override。governance_full mode 通过 ablation framework 的 `mode_env` 覆盖为 `true`。

这意味着 Round 1.4 的 0/4 multi_turn_clarification FAIL 是在 **PCM advisory + decision field enabled** 的状态下产生的 — 不是 PCM short-circuit 导致的。

#### §2.1.3 实际决策链 (flag=true, 即 governance_full 路径)

**Round 1.4 governance_full 跑的是 Wave 2 only**。

证据 (`governed_router.py:60-96`, `_build_contracts`):
```python
if self.contract_split_enabled:       # True in governance_full
    # Wave 2: split contracts
    self.contracts.append(self.intent_resolution_contract)
    self.contracts.append(self.stance_resolution_contract)
    self.contracts.append(self.execution_readiness_contract)
else:
    # Wave 1: legacy unified contract (NOT instantiated when split enabled)
    self.clarification_contract = ClarificationContract(...)
```

`config_snapshot.json` 中 `ENABLE_CONTRACT_SPLIT=true`、`ENABLE_SPLIT_INTENT_CONTRACT=true`、`ENABLE_SPLIT_READINESS_CONTRACT=true`、`ENABLE_SPLIT_STANCE_CONTRACT=true`。Wave 1 (`ClarificationContract`) **不在 contract list 中**。

实际执行顺序:
```
Turn entry
  │
  ├─ [1] OASC contract (AO classification)
  │     governed_router.py:66 — always present
  │
  ├─ [2] IntentResolutionContract.before_turn (Wave 2)
  │     intent_resolution_contract.py:36-131
  │     - Fast resolver determines intent from continuation state
  │     - If intent unresolved: calls Stage 2 LLM via split_contract_utils.py:55-132
  │       → sets context.metadata["stage2_payload"] (intent_resolution_contract.py:104)
  │     - Persists tool_intent to AO (line 123)
  │
  ├─ [3] StanceResolutionContract.before_turn (Wave 2)
  │     stance_resolution_contract.py:32-131
  │     - Resolves stance from continuation/reversal markers or LLM
  │
  ├─ [4] ExecutionReadinessContract.before_turn (Wave 2)
  │     execution_readiness_contract.py:74-372
  │     1. Stage 1: regex hint extraction (line 91)
  │     2. PCM advisory pre-computation (lines 96-119, only when flag=true):
  │        - _classify_missing_optionals → no_default / resolved_by_default
  │        - Does NOT set should_proceed=False (advisory only)
  │     3. Stage 2 LLM (lines 121-145):
  │        - Reuses context.metadata["stage2_payload"] if already set by IntentResolution
  │          AND none of the trigger conditions (missing_required, continuation, etc.) are met
  │        - Otherwise overwrites with own Stage 2 call
  │        - Prompt includes: K4 runtime_defaults, K6 tool_graph, K7 prior_violations,
  │          K8 available_results, K9 pcm_advisory, decision examples
  │        - Returns: slots, intent, stance, chain, decision
  │     4. Stage 3: standardization + legal-value enforcement (lines 149-154)
  │     5. clarify_candidates aggregation (lines 204-254)
  │     6. Decision routing (lines 256-372):
  │        - If clarify_candidates exist + optional_only_probe + flag=true:
  │          → advisory mode, force_proceed (line 269-285)
  │        - If clarify_candidates exist + flag=false:
  │          → hard-block probing with probe_limit
  │        - Q3 gate: if _split_decision_field_active → defer to decision_field
  │
  ├─ [5] DependencyContract.before_turn (always last)
  │
  ├─ GovernedRouter (lines 109-154):
  │   1. Run all contracts. If any returns proceed=False → short-circuit
  │   2. If result is None (all contracts passed):
  │      a. If enable_llm_decision_field: _consume_decision_field()
  │         - Reads decision from context.metadata["stage2_payload"]
  │           (set by IntentResolution or ExecutionReadiness, whichever ran Stage 2 last)
  │         - validate_decision() → F1 safety check
  │         - proceed → cross-constraint preflight → blocked or fall-through
  │         - clarify → returns LLM question directly
  │         - deliberate → returns LLM reasoning directly
  │      b. If decision field returns None → _maybe_execute_from_snapshot()
  │      c. If snapshot returns None → inner_router.chat() (fallback)
  │
  └─ Reply: LLM reply parser rewrites final text
       (注: Phase 5.1 β-recon 已验证 benchmark 全域 0 触发, 此路径为框架兜底)
```

**关键结论**: Round 1.4 governance_full 跑的是 Wave 2 split contract 路径 (IntentResolution → StanceResolution → ExecutionReadiness)。Wave 1 的 `ClarificationContract` (clarification_contract.py:316-517) **不在执行路径上**。这意味着:

- A reconciliation 和 B validator 的**主要实施面在 Wave 2** (execution_readiness_contract.py + intent_resolution_contract.py)
- Wave 1 (`clarification_contract.py`) 中的等价代码需要**同步修改以保持双路径一致**（当 flag=false 时 Wave 1 是活跃路径），但 A+B 的核心逻辑验证和 smoke test 必须以 Wave 2 为 primary target
- 当前澄清 E narrow 链持久化需要在 Wave 2 的 IntentResolutionContract 路径上验证

**关键发现**：PCM 在当前 governance_full 模式下**不是 short-circuit gate**。PCM 计算 advisory → 注入 Stage 2 payload → Stage 2 LLM 做最终 decision → GovernedRouter 消费 decision。这恰好是 Phase 4 Option B 设计的完整实现。

**决策链是 5 步，但 PCM 是 advisory input 而非 gate**：
1. PCM advisory (K9 input to Stage 2)
2. Stage 2 raw (LLM output)
3. Stage 3 YAML snapshot (standardization + legal-value check)
4. ExecutionReadiness final (split path) / ClarificationContract final (legacy path)
5. Router consumed (GovernedRouter._consume_decision_field)

#### §2.1.4 105/110/120 trace 中 PCM 触发情况

**Trace 数据源**:
```
evaluation/results/phase5_3/round1_4_sanity/governance_full/rep_1/end2end_logs.jsonl
```
每 task 一条 JSONL record。以下字段来自每条 record 的 top-level keys。

**Stage 2 / PCM / decision 关键字段来源**:

| 信息 | JSONL 字段路径 | 示例值 |
|------|---------------|--------|
| Stage 2 是否被调用 | `clarification_telemetry.stage2_called` | `true` |
| Stage 2 decision | `clarification_telemetry.stage2_decision` | `{"value": "clarify", "confidence": 0.85, "reasoning": "..."}` |
| Stage 2 missing_required | `clarification_telemetry.stage2_missing_required` | `["vehicle_type", "road_type"]` |
| PCM advisory 是否注入 | `clarification_telemetry.pcm_advisory` | `{"unfilled_optionals_without_default": [...], "runtime_defaults_available": {...}}` |
| PCM trigger reason | `clarification_telemetry.pcm_trigger_reason` | `null` (flag=true advisory mode 下不触发) |
| Collection mode | `clarification_telemetry.collection_mode` | `false` (flag=true 下 advisory 不设 collection_mode block) |
| Final decision | `clarification_telemetry.final_decision` | `"deferred_to_decision_field"` or `"proceed"` |
| 实际 tool calls | `actual.tool_calls[].name` + `actual.tool_calls[].arguments` | 见下表 |
| 期望 tool chain | `expected.tool_chain` | `["calculate_macro_emission"]` 等 |
| AO lifecycle | `ao_lifecycle_events[]` | 13 events for 105 |
| Contract path | 推导自 `config_snapshot.json` `ENABLE_CONTRACT_SPLIT=true` | Wave 2 only |

**Task 105 trace evidence** (来源: `end2end_logs.jsonl` record for `e2e_clarification_105`):

- `actual.tool_calls`: 3 个 `calculate_macro_emission({model_year: 2020, pollutants: ["CO2"], season: "夏季"})` — 重复执行同一工具 3 次
- `expected.tool_chain`: `["calculate_macro_emission"]` — 期望 1 次 macro
- Round 1.5 audit §2.1 从 per-turn trace 确认: turn 2 Stage 2 raw `decision=clarify`, `missing_required=["vehicle_type", "road_type"]` — 但 `config/tool_contracts.yaml` 中 `calculate_macro_emission.required_slots=["pollutants"]`, 不含 `vehicle_type` 或 `road_type`。这构成 Class B 的直接证据: Stage 2 hallucinated required slots 未被 validator 过滤。

**Task 110 trace evidence** (来源: `end2end_logs.jsonl` record for `e2e_clarification_110`):

- `actual.tool_calls`: **0 个** — governance 路径未产生任何工具调用
- `expected.tool_chain`: `["query_emission_factors"]`
- Round 1.5 audit §2.3 确认: turn 3 Stage 2 raw `decision=proceed` (complete slots: vehicle_type="Refuse Truck", pollutants=["PM10"], model_year="2020"), 但 final state 仍为 clarify, 导致 0 tool calls。这构成 Class A 的直接证据: Stage 2 proceed 与 readiness final clarify 不一致。

**Task 120 trace evidence** (来源: `end2end_logs.jsonl` record for `e2e_clarification_120`):

- `actual.tool_calls`: 3 个 `calculate_macro_emission({pollutants: ["NOx"], season: "夏季"})` — 只执行了 macro, 没有 dispersion
- `expected.tool_chain`: `["calculate_macro_emission", "calculate_dispersion"]`
- Round 1.5 audit §2.2 确认: turn 1 Stage 2 raw `decision=clarify`, `chain=["calculate_macro_emission", "calculate_dispersion"]`, `available_results.emission=false`。clarify 返回后 chain 丢失, 后续 turn 只跑 macro。这构成 Class E 的直接证据。

**汇总**:

| Task | Stage 2 called? | Trace evidence field | Stage 2 decision | PCM advisory in log? | PCM short-circuit? | Actual failure |
|------|----------------|---------------------|-----------------|----------------------|---------------------|----------------|
| 105 | Yes (inferred from `stage2_decision` present in ctel) | `clarification_telemetry.stage2_decision` = `{"value": "clarify", ...}`, `clarification_telemetry.stage2_missing_required` = `["vehicle_type", "road_type"]` (hallucinated per audit §2.1) | turn 2: clarify with hallucinated required slots | `clarification_telemetry.pcm_advisory` populated (advisory mode) | **No** — `pcm_trigger_reason` is null, `collection_mode` false | Stage 2 raw clarify with hallucinated slots reaches user → 3 repeated macro calls |
| 110 | Yes (`stage2_decision` present in ctel) | `clarification_telemetry.stage2_decision` = `{"value": "proceed", ...}` (per audit §2.3 turn 3), `actual.tool_calls` = `[]` | turn 3: proceed (complete slots) but not consumed | `clarification_telemetry.pcm_advisory` populated (advisory mode) | **No** | proceed consumed but readiness blocks → 0 tool calls |
| 120 | Yes (`stage2_decision` present in ctel) | `actual.tool_calls[].name` = `["calculate_macro_emission"]` × 3 (no dispersion), `expected.tool_chain` = `["calculate_macro_emission", "calculate_dispersion"]` | turn 1: clarify with chain=[macro, dispersion] | `clarification_telemetry.pcm_advisory` populated (advisory mode) | **No** | clarify returned, chain not persisted → only macro runs, no dispersion |

**结论**: 三个 task 的 PCM 均处于 advisory mode (`flag=true`), Stage 2 正常被调用。失败根源不是 PCM short-circuit:
- 105: Class B — Stage 2 hallucinated required slots 未被 validator 过滤
- 110: Class A — Stage 2 proceed 与 readiness final clarify 不一致, 未被 reconcile
- 120: Class E — Stage 2 chain 未被持久化, clarify 返回后 chain 丢失

**验证方法**: 独立审视者可运行以下 Python 脚本从同一 JSONL 文件提取字段值重现本表 — 读取 `end2end_logs.jsonl`, 按 `task_id` 过滤 105/110/120, 提取上表列出的 `clarification_telemetry.*`、`actual.tool_calls`、`expected.tool_chain` 字段。

### §2.2 "补全设计"边界重新审视

基于 §2.1 PCM 真实位置 (advisory, 非 short-circuit gate)，重新审视 A/B/E narrow：

#### A reconciliation — 仍是补全设计 ✓

**PCM 不影响 A**。当前决策链中，PCM advisory 是 Stage 2 的输入 (K9)，不是 Stage 2 之后的 gate。A 要 reconcile 的 4 个 decision 都在 Stage 2 输出之后：

1. Stage 2 raw `decision` (LLM says clarify/proceed/deliberate)
2. Stage 2 raw `missing_required` (LLM says which slots are missing)
3. Stage 3 YAML snapshot (post-standardization: which slots are truly required/missing per contract)
4. ExecutionReadiness / ClarificationContract final `should_proceed` (derived from #2 + #3 + collection_mode)

A 的 reconciliation 规则是：当 #1 (Stage 2 decision=proceed) 和 #2 (Stage 2 missing_required=[]) 被 #3 (YAML required slots not missing) 和 #4 (readiness ready) 支持时，reconciled decision 是 proceed。当 #2 声称 missing X 但 #3 说 X 不是 required slot 时，reconcile 应过滤 X。

这只涉及 Stage 2 post-processing 逻辑，不涉及 PCM。PCM advisory 是 Stage 2 的**上游输入**；A 是 Stage 2 **输出之后**的 reconciliation。两者独立。

**F2 对照**：YAML snapshot (domain physics) 赢 LLM raw (conversational pragmatics)。F2 字面支持。

#### B clarify-grounding validator — 仍是补全设计 ✓

**PCM 不影响 B**。B 的 validator 在 Stage 2 输出之后运行，过滤 LLM 声称的 `missing_required` 使其必须是 YAML contract 中声明的 required/follow-up slot。

当前 `validate_decision()` (`decision_validator.py:10-54`) 已经做了 F1 安全网检查 (schema/confidence/missing_required non-empty check)，但**没有做 contract-grounding**：它检查 `decision=proceed → missing_required must be []`，但不检查 `decision=clarify → missing_required must be subset of tool's actual required/follow-up slots`。

B 要加的就是这个 grounding check：如果 LLM 说 "需要 vehicle_type 和 road_type"但 YAML contract 只要求 pollutants，validator 应 downgrade 或过滤非法 slot。

这同样是 Stage 2 post-processing，跟 PCM advisory 输入无关。

**F2 对照**：Validator ground 到 YAML contract (domain physics)。F2 字面支持。

#### E narrow chain handoff — 仍是补全设计 ✓

**PCM 不影响 E**。E narrow 要修的是：

1. ClarificationContract Stage 2 在 `decision=clarify` 时返回 `intent.chain` (已有)
2. 这个 chain 被持久化到 AO `tool_intent.projected_chain` (当前缺失)
3. 当 upstream tool (macro) 跑完后，ExecutionContinuation 检查 projected_chain 是否还有未执行 step (dispersion)，有则激活

这三个步骤都不涉及 PCM。PCM advisory 不影响 chain 的生成 (chain 来自 Stage 2 LLM 的 tool_graph 推理)。PCM 也不影响 chain 的持久化 (那是 ClarificationContract → AO 的数据流)。PCM 更不影响 ExecutionContinuation 的 advance (那是 OASC contract after_turn 的逻辑)。

**F2 对照**：Chain 是 LLM 的计划能力 (conversational pragmatics)，持久化和 handoff 是 governance 的责任 (domain data flow)。F2 字面支持。

### §2.3 PCM 牵连风险评估

**三个 fix 均不牵连 PCM 重设计**。理由：

- A reconciliation 和 B validator 都在 Stage 2 **输出之后**运行，PCM advisory 在 Stage 2 **输入之前**注入。修改 reconciliation/validator 逻辑不需要改 PCM advisory 的计算或注入。
- E narrow 修的是 ClarificationContract → AO projected_chain → ExecutionContinuation 数据流，这条路径不经过 PCM。
- 即使 flag=false (PCM hard-block)，A 和 B 仍然有效：当 flag=false 时 PCM short-circuit 阻止 Stage 2 调用，但 A 和 B 都只在 Stage 2 被调用后才生效。flag=false 时 Stage 2 不运行 → A 和 B 无输入 → 自然 fall through 到现有 hard-rule 路径。这是正确行为。

**唯一需要注意**：flag=false 时 PCM hard-block 阻止 Stage 2 调用，因此 A 和 B 的 reconciliation/validator **只会**在 flag=true 时生效。这是设计意图 — A 和 B 是 LLM-deferential 路径的 guardrail，不是 hard-rule 路径的 patch。

### §2.4 补全设计证据 (逐个 fix, file:line 级别)

#### A reconciliation — 补全 Phase 3 F2 原则

**F2 原则原文** (`phase3_case_driven_design.md:1416-1441`):
> "Cross-constraint rules (K5), readiness rules, and other domain physics constraints SHALL NOT be injected into the LLM prompt. Governance detects violations deterministically and feeds them back to the LLM via the ConstraintViolation closed loop."

**补全证据**：

1. **当前代码已有 4 个独立的 decision source**，但缺少统一的 reconciliation point：
   - Stage 2 raw: `clarification_contract.py:370-371` — `telemetry.stage2_decision = dict(llm_payload["decision"])`
   - Stage 3 YAML: `clarification_contract.py:395-400` — `snapshot, normalizations, rejected_slots = self._run_stage3(...)`
   - ClarificationContract final: `clarification_contract.py:422-445` — `should_proceed` tree
   - Router consumed: `governed_router.py:557-674` — `_consume_decision_field`

2. **设计意图已存在于 Phase 3 架构中** (`phase3_case_driven_design.md:1042-1072`)：Unified GovernedRouter Consumption Architecture 图显示了 `validate_decision()` → 三路分支的统一模式。Reconciliation 是这个架构的 missing piece：当前架构有 validate_decision (F1 安全网) 但没有 reconcile_decision (YAML grounding)。

3. **F2 字面对照**："Domain rules (cross-constraint, readiness) are NOT injected into the LLM prompt" → A reconciliation 正是把 domain rules (YAML contract required slots) 作为 post-hoc check，不是 pre-LLM injection。符合 F2。

#### B validator — 补全 Phase 3 Phase 3 decision field 设计

**补全证据**：

1. **`validate_decision()` 已存在** (`decision_validator.py:10-54`)：做 schema check + confidence check + missing_required consistency check。但 spec (`phase3_case_driven_design.md:1196`) 只说要 "F1 safety-net rules"，没说 contract-grounding。**Grounding 是 Phase 3 设计文档中未明确写出但 F2 原则隐含要求的 missing piece**。

2. **Stage 2 prompt 已包含 tool_slots** (`clarification_contract.py:812-817`)：LLM 能看到哪些是 required、哪些是 optional。但 LLM 仍可能 hallucinate — prompt rule 17 只说 "proceed=信息足够可执行工具"，没说 "clarify 只能针对 contract 声明的 required/follow-up slots"。**Prompt 层防御不充分，需要 post-hoc validator**。

3. **Class B 由 Round 1.5 audit 直接归因** (audit §2.1):
   > "The design gap is narrower: Phase 3 did not explicitly define a validator rule for decision=clarify such as 'clarify pending slots must be in the active tool's required/follow-up slots.'"

   这是典型的 "补全设计"：设计意图已存在 (decision field validation)，实施有一个遗漏的规则 (contract-grounding for clarify)。补这个规则不需要重新设计 decision field。

#### E narrow — 补全 ExecutionContinuation 已有设计

**补全证据**：

1. **Stage 2 已输出 chain**: prompt rule 14 (K6) + tool_graph 注入指示 LLM "在 intent.chain 里按依赖顺序规划执行序列"。Task 120 turn 1 Stage 2 正确输出了 `chain=["calculate_macro_emission", "calculate_dispersion"]` (Round 1.5 audit §2.2 确认)。

2. **AO `tool_intent.projected_chain` 字段已存在** (`analytical_objective.py:55`): `projected_chain: List[str] = field(default_factory=list)`。`OASCContract._refresh_split_execution_continuation()` 在 tool 成功执行后读取 `tool_intent.projected_chain` 来 advance ExecutionContinuation。

3. **ExecutionContinuation 已设计 chain advance 逻辑** (`execution_readiness_contract.py` 多处, `execution_continuation_utils.py:30-48`)。但 advance 只在 chain **已存在且 match** 时工作。

4. **§2.4.E.4-audit — `projected_chain` 全链路 audit（闭环）**:

   **4a. 所有写入点** (`grep -rn "projected_chain" core/`):
   | # | 文件:行 | 操作 | 上下文 |
   |---|---------|------|--------|
   | W1 | `intent_resolver.py:120` | `fast.projected_chain = parsed_chain` | resolve_with_llm_hint fast-path: 仅当 `fast.resolved_tool == parsed_chain[0]` 时写入 |
   | W2 | `intent_resolver.py:141` | `projected_chain=list(parsed_hint.get("projected_chain") or [])` | resolve_with_llm_hint slow-path: 总是写入 LLM hint 的 chain |
   | W3 | `clarification_contract.py:1024` | `target.projected_chain = list(getattr(tool_intent, "projected_chain", []) or [])` | _persist_tool_intent: **无条件覆盖** AO 的 projected_chain |
   | W4 | `analytical_objective.py:372` | `tool_intent.projected_chain = [pending_tool]` | _migrate_deprecated_metadata: 仅当 `not tool_intent.projected_chain` 时写入 (不覆盖已有值) |
   | W5 | `intent_resolver.py:34,46,57,66,76,87,96` | resolve_fast 各分支 | 从 continuation/parent context 构建 ToolIntent，含 projected_chain |

   **4b. 所有读取点**:
   | # | 文件:行 | 读取上下文 |
   |---|---------|-----------|
   | R1 | `intent_resolver.py:185` | `_projected_chain_from_ao`: 从 AO 读取 tool_intent.projected_chain |
   | R2 | `execution_readiness_contract.py:79` | normalize_tool_queue(projected_chain) |
   | R3 | `execution_continuation_utils.py:34` | normalize_tool_queue |
   | R4 | `execution_continuation_utils.py:48` | remove_completed_tool |
   | R5 | `oasc_contract.py:134` | _refresh_split_execution_continuation: 检查每个 tool in projected_chain |
   | R6 | `intent_resolution_contract.py:74,51` | continuation short-circuit |

   **4c. Task 120 链丢失的根因分析**:

   Turn 1 ("帮我看这个路网文件的NOx排放，再做个扩散"):
   - `intent_resolver.resolve_fast()` → fast.resolved_tool = `"calculate_dispersion"` (用户最终目标), fast.confidence = HIGH
   - Stage 2 LLM 返回: `intent.resolved_tool="calculate_dispersion"`, `chain=["calculate_macro_emission", "calculate_dispersion"]`
   - `_extract_llm_intent_hint` → `parsed_hint["projected_chain"] = ["calculate_macro_emission", "calculate_dispersion"]`
   - `resolve_with_llm_hint`: fast.confidence == HIGH → 进入 **W1 路径** (line 103-121)
   - 检查 `fast.resolved_tool == parsed_chain[0]` → `"calculate_dispersion" == "calculate_macro_emission"` → **FALSE**
   - **chain 被丢弃**。`fast.projected_chain` 保持为空 (fast 原始值) 或被设置为其他值。
   - `_persist_tool_intent` (W3) 将空 projected_chain 写入 AO。

   **根因**: `intent_resolver.py:114` 的条件 `fast.resolved_tool == parsed_chain[0]` 假设 chain[0] 等于最终目标工具。但对依赖链 (macro → dispersion), chain[0] 是上游 prerequisite (macro), 不是最终目标 (dispersion)。条件为 false → chain 被静默丢弃。

   Turn 2 (用户提供参数后):
   - 新的 Stage 2 调用可能输出也可能不输出 chain。如果 LLM 输出 chain 且 fast.confidence != HIGH, W2 路径会写入 chain。但此时 AO 已有 turn 1 写入的空 projected_chain — 且 turn 2 的 `_persist_tool_intent` (W3) 会**无条件覆盖**为新值。链的跨 turn 持久化依赖每次 Stage 2 调用都重新输出完整 chain。

   **4d. 判定: E narrow 是 "补全设计" ✓**。

   理由:
   - chain 的生成 (Stage 2 LLM)、解析 (`_extract_llm_intent_hint`)、持久化 (`_persist_tool_intent`)、消费 (OASC chain advance) 四个环节**全部已存在于代码中** — 不是从零设计。
   - Bug 是两个实现细节:
     1. `intent_resolver.py:114` 的条件 `fast.resolved_tool == parsed_chain[0]` 对依赖链 (chain[0] != resolved_tool) 失效 → chain 在 resolve 阶段被丢弃。
     2. `_persist_tool_intent` (W3) 无条件覆盖 `projected_chain` → 即使 chain 在 turn N 被正确持久化, turn N+1 的 Stage 2 调用可能用空 chain 覆盖。
   - 修复在补全设计层面: 改 W1 的条件 (允许 chain[0] != resolved_tool 但 resolved_tool 在 chain 中) + 改 W3 的覆盖为 merge (非空新 chain 覆盖, 空新 chain 保留旧值)。
   - 不涉及新状态机、新数据流、新组件。
   - **不触发 escalation** — E narrow 保持在 Round 2 范围。

5. **E narrow 的 "narrow" 边界** (`phase5_3_round1_5_design_audit.md §5`): 只修 macro → dispersion 一条依赖路径。依赖路径本身已在 `config/tool_contracts.yaml` (`calculate_dispersion.dependencies.requires: [emission]`) 和 `core/tool_dependencies.py` (`TOOL_GRAPH`) 中定义。chain handoff 的骨架已在 ExecutionContinuation 中设计。补的是 W1 条件修复 + W3 merge 策略。

### §2.5 Observations carried to §3 (ack only, not resolved here)

**O1 — "4 decision" 命名未对齐**: §2.2 列了 (Stage 2 raw decision, Stage 2 raw missing_required, Stage 3 YAML, ClarificationContract final), §2.4 A 第 1 点列了 (Stage 2 raw, Stage 3 YAML, ClarificationContract final, Router consumed)。§3 定义 `ReconciledDecision` schema 时必须先统一 source 命名 + 数量 (当前实际是 5 个 source 但 Router consumed 是下游消费者, 不是 decision producer)。建议统一为 4 个 producer + 1 个 consumer。

**O2 — A 跟 B 工作边界重叠**: §2.2 A 第二段 "当 Stage 2 missing_required 声称 missing X 但 YAML 说 X 不是 required slot 时, reconcile 应过滤 X" — 这实际是 B validator 的 contract-grounding 职责。§3 必须明确划清: B validator 负责 per-decision 合法性校验 (slot ∈ contract required/follow-up), A reconciliation 负责跨-decision 冲突裁决 (LLM says proceed vs readiness says clarify 时谁赢)。

**O3 — 流程图 Reply 段**: Phase 5.1 β-recon 已验证 LLM Reply Parser 在 benchmark 全域 0 触发 (source=llm_parsed 0 次, call_count=0)。流程图中 "Reply: LLM reply parser rewrites final text" 实际是 fallback 到 `router_text`。不影响 §2 主结论, 但 §3 设计 reply context 注入点时可校准。

**O4 — 实施面以 Wave 2 为主**: Round 1.4 governance_full 跑的是 Wave 2 split contract 路径 (IntentResolution → StanceResolution → ExecutionReadiness)。Wave 1 (`ClarificationContract`) 不在活跃路径上。但 Wave 1 代码 (clarification_contract.py) 中仍存在等价的 Stage 2 → persist → Q3 gate 逻辑, flag=false 时 Wave 1 是活跃路径。A+B 设计必须覆盖双 Wave, 但 §3 的 schema/rule 设计以 Wave 2 为 primary target, Wave 1 为同步修改目标。

---

## §3 Class A — Reconciliation 修复设计

### §3.1 Source 命名统一表

**前置实证**。Wave 2 (contract-split, governance_full 活跃路径) 中, 影响最终路由决策的 data point 共有 4 个, 但只有 3 个是 producer。当前代码缺少统一的 reconciliation 层, 导致 `_consume_decision_field` 只读取 `stage2_raw` 而忽略其他 producer。

#### 3.1.1 命名模型: 3 producer + 1 consumer

| # | 命名 | 英文标识 | 角色 | 含义 |
|---|------|---------|------|------|
| P1 | Stage 2 原始输出 | `stage2_raw` | **producer** | LLM 对当前 turn 的语义判断 — 该 proceed/clarify/deliberate + 哪些 slot 缺失 |
| P2 | Stage 3 YAML 约束 | `stage3_yaml` | **producer** | governance 领域物理检验 — YAML contract 声明哪些 slot 是 required/optional, 当前哪些 truly missing |
| P3 | Readiness 程序门控 | `readiness_gate` | **producer** | governance 程序 gate — 综合 missing/rejected/confirm_first/followup/continuation, 决定是否阻塞执行 |
| C1 | Router 最终路由 | `router_consume` | **consumer** | GovernedRouter 读取 producer 输出, 产生最终 RouterResponse (工具执行 / clarify / deliberate) |

**Router 最终路由不是 producer** — 它是消费者。当前 bug 是 `router_consume` 只消费了 P1 (`_consume_decision_field` 只读 `context.metadata["stage2_payload"]`), 忽略了 P2 和 P3。

#### 3.1.2 各 source 详细定义

**P1 — `stage2_raw` (LLM 原始语义输出)**

| 属性 | 值 |
|------|-----|
| 存储位置 | `context.metadata["stage2_payload"]` (dict) |
| Wave 2 写入点 1 | `intent_resolution_contract.py:104` — IntentResolution 调 Stage 2 后写入 |
| Wave 2 写入点 2 | `execution_readiness_contract.py:144` — ExecutionReadiness 调 Stage 2 后写入 (覆盖前值, 或复用 IntentResolution 已写入的 payload, 见 line 122) |
| Wave 1 写入点 | `clarification_contract.py:356` — `llm_payload = await self._run_stage2_llm(...)`; 未写入 `context.metadata`, 仅局部使用 |
| 数据结构字段 | `decision.value` (`"proceed"\|"clarify"\|"deliberate"`), `decision.confidence` (float), `decision.reasoning` (str), `decision.clarification_question` (str\|null), `missing_required` (List[str]), `intent.resolved_tool`, `intent.chain` (List[str]), `needs_clarification` (bool), `slots` (Dict) |
| 含义 | LLM 看到 tool_slots + legal_values + runtime_defaults + tool_graph + prior_violations + pcm_advisory 后, 对当前 turn 应该如何路由的完整判断。**这是 conversational pragmatics 的权威来源** (F2: LLM owns pragmatics)。 |
| 可靠性 | 可能 hallucinate missing_required (task 105: 声称 vehicle_type/road_type 缺失但 contract 不要求), 可能误判 proceed/clarify |

**P2 — `stage3_yaml` (governance 领域物理检验)**

| 属性 | 值 |
|------|-----|
| 存储位置 | Wave 2 局部变量 (`execution_readiness_contract.py:149-156`), 不写入 context.metadata |
| 关键数据 | `missing_required` (List[str]) — `self._missing_slots(snapshot, active_required_slots)` 的输出, YAML contract required_slots 中当前为空的 slot; `rejected_slots` (List[str]) — Stage 3 标准化后 legal-value check 失败的 slot; `snapshot` (Dict) — post-standardization 的快照; `optional_classification` (Dict) — `{"no_default": [...], "resolved_by_default": [...]}` |
| 含义 | **这是 domain physics 的权威来源** (F2: governance owns domain physics)。这里的 `missing_required` 是 YAML contract 声明的真正缺失 slot, 不是 LLM 的判断。 |
| 可靠性 | 可靠 — 完全 deterministic, ground 到 `config/tool_contracts.yaml` |

**P3 — `readiness_gate` (governance 程序门控)**

| 属性 | 值 |
|------|-----|
| 存储位置 | Wave 2 局部变量 + `context.metadata["clarification"]` (最终 disposition) |
| 关键数据 | `clarify_candidates` (List[str]) — 综合 aggregation (line 204-254, 9 个 input source); `clarify_required_candidates` (List[str]); `clarify_optional_candidates` (List[str]); `force_proceed_reason` (Optional[str]) — `"probe_limit_reached"`, `"advisory_mode"`, None; `optional_only_probe` (bool); `preserve_followup_slot` (Optional[str]); `ContractInterception.proceed` (bool); `direct_execution` dict (set at line 619-627, consumed by `_maybe_execute_from_snapshot`) |
| 含义 | **这是 governance 的程序 gate** — 综合 stage2_raw 和 stage3_yaml 的信息, governance 对当前 turn 有 3 种 disposition: **(D1) hard-block** — `ContractInterception(proceed=False)` + RouterResponse 含 clarify question, GovernedRouter 直接返回, LLM 不参与 (触发: clarify_candidates 存在 + `_split_decision_field_active=False`, line 365/416/542); **(D2) Q3 defer** — `ContractInterception(proceed=True)` + metadata 含 `hardcoded_recommendation`, GovernedRouter 读到后让 `_consume_decision_field` 做最终决策 (触发: clarify_candidates 存在 + `_split_decision_field_active=True`, line 358; 或 EXPLORATORY/DELIBERATIVE stance + Q3 gate 活跃, line 405/535); **(D3) proceed** — `ContractInterception(proceed=True)` + metadata 可能含 `direct_execution` dict (line 630, 触发: clarify_candidates 为空, 或 flag=true advisory mode 处理了 optional-only probe, 或 probe_limit reached force-proceed) |
| 可靠性 | 混合 — clarify_candidates aggregation (line 204-254) 有 9 个 input source 且无显式优先级 (Phase 2 audit §3.4.5 MISALIGNED), `preserve_followup_slot` 逻辑 (line 551-583) 可能对完全合法的 turn 设置 PARAMETER_COLLECTION continuation |

**C1 — `router_consume` (GoernedRouter 最终路由)**

| 属性 | 值 |
|------|-----|
| 位置 | `governed_router.py:132-154` |
| 当前消费逻辑 | 1. `_consume_decision_field` (line 557-674): 读 `context.metadata["stage2_payload"]["decision"]` → validate_decision → 三路路由; 2. 若返回 None: `_maybe_execute_from_snapshot` (line 364-414): 读 `context.metadata["clarification"]["direct_execution"]` → 直接执行工具; 3. 若仍 None: `inner_router.chat` (fallback) |
| 缺失 | **只消费 P1, 不消费 P2/P3**。`_consume_decision_field` 的 validate_decision 只做 F1 safety check (schema/confidence/missing_required), 不做 P2 (YAML contract ground) 或 P3 (readiness gate conflict check)。 |
| A 修复后 | `router_consume` 消费 `reconciled_decision` (P1+P2+P3 合并输出), 而非直接读 `stage2_raw` |

#### 3.1.3 Source 关系图

```
                    ┌────────────────────┐
                    │    P1: stage2_raw  │  LLM 语义判断
                    │  context.metadata  │  (decision, missing_required,
                    │  ["stage2_payload"]│   intent, chain, needs_clarify)
                    └────────┬───────────┘
                             │
                    ┌────────▼───────────┐
                    │ P2: stage3_yaml    │  governance 领域物理
                    │ (局部变量, 不写     │  (YAML contract required slots,
                    │  context.metadata) │   rejected, optional class)
                    └────────┬───────────┘
                             │
                    ┌────────▼───────────┐
                    │ P3: readiness_gate │  governance 程序 gate
                    │  context.metadata  │  (clarify_candidates,
                    │  ["clarification"] │   force_proceed, direct_execution)
                    └────────┬───────────┘
                             │
                    ┌────────▼───────────┐
                    │  reconcile()       │  ← NEW (Class A 补全)
                    │  合并 P1+P2+P3     │
                    │  → reconciled_decision
                    └────────┬───────────┘
                             │
                    ┌────────▼───────────┐
                    │ C1: router_consume │  GovernedRouter 最终路由
                    │  _consume_decision │  (proceed→execute /
                    │  _field (修改后)   │   clarify→question /
                    │                    │   deliberate→reasoning)
                    └────────────────────┘
```

#### 3.1.4 命名决策点

**§3.1-1 决策已关闭**: 接受 3 producer + 1 consumer source model。

- **最终选择**: 3 producer (P1 `stage2_raw` / P2 `stage3_yaml` / P3 `readiness_gate`) + 1 consumer (C1 `router_consume`)。该模型精确反映 Wave 2 实际数据流。`stage2_raw` 的 `missing_required` 是 LLM 的 view, 不是独立 producer — 它跟 `decision` 来自同一个 LLM 调用的同一个 payload。
- **备选 A**: 4 producer (把 `stage2_raw.decision` 和 `stage2_raw.missing_required` 拆成两个独立 producer)。不推荐 — 两者来自同一 LLM 调用, 拆分不增加 reconciliation 精度, 但增加概念复杂度。
- **备选 B**: 2 producer (把 `stage3_yaml` 和 `readiness_gate` 合并为 `governance_gate`)。不推荐 — 两者角色不同 (领域物理 vs 程序 gate), 合并后 reconciliation 规则无法清楚表达 "YAML required slots 赢 LLM missing_required" vs "readiness gate 可选 probe 不阻塞 LLM proceed" 的区别。

---

## §3.2 ReconciledDecision schema 设计

### §3.2.0 前置任务 close

#### §3.2.0-A 行号冲突 reconcile (close)

**实证**: `grep -n` 确认 `execution_readiness_contract.py` 中 `clarify_candidates` aggregation 的精确行号区间为 **lines 204-254**:
- Line 204: `clarify_candidates = list(missing_required) + list(rejected_slots)` — aggregation 起始
- Line 254: `continue_after = ...` — aggregation 之后第一个非 aggregation 语句 (probe_limit check)

**§2.1.3 vs §3.1 校准结果**:
- §2.1.3 line 105 原写 `(lines 177-225)` — 错误。177-203 是 continuation/reversal setup, 不是 clarify_candidates aggregation。已修复为 `(lines 204-254)`。
- §3.1 lines 406/408 原写 `line 206-254` — 偏移 2 行 (start 实际是 204, 不是 206)。已修复为 `line 204-254`。

**结论**: 真实行号为 204-254。两份文档已同步。

#### §3.2.0-B P3 disposition 校准 (close)

**实证**: `grep -n "ContractInterception\|proceed=False\|Q3\|hardcoded_recommendation\|direct_execution"` 确认 Wave 2 有 3 种 disposition:

| # | Disposition | ContractInterception 形式 | 文件:行 | 触发条件 |
|---|-------------|--------------------------|---------|----------|
| D1 | **hard-block** | `proceed=False` + `response=RouterResponse(text=question)` | line 365-372, 416-432, 542-549 | clarify_candidates 存在 + `_split_decision_field_active()=False`; 或 EXPLORATORY/DELIBERATIVE stance + Q3 gate 不活跃 |
| D2 | **Q3 defer** | `proceed=True` (default) + `metadata={"hardcoded_recommendation": "clarify"|"deliberate"}` | line 358-364, 405-415, 535-541 | clarify_candidates 存在 + `_split_decision_field_active()=True`; 或 EXPLORATORY/DELIBERATIVE stance + Q3 gate 活跃 |
| D3 | **proceed** | `proceed=True` (default) + `metadata={"clarification": {"telemetry": ..., "direct_execution": ...}}` | line 630 | clarify_candidates 为空; 或 flag=true advisory mode 处理了 optional-only probe (line 269-294); 或 probe_limit reached force-proceed (line 258-267) |

**§3.1 P3 "含义" 行已更新**为 3 种 disposition 完整列表 + 触发条件 + file:line。

**验证**: D1 返回时 GovernedRouter 在 line 129 读到 `not interception.proceed → result = interception.response` (hard block)。D2 返回时 `interception.proceed=True` (default), 合约循环继续, GovernedRouter line 132-134 发现 `result is None` + `enable_llm_decision_field=true` → 调 `_consume_decision_field` (Q3 生效)。D3 返回时 `interception.proceed=True` + 循环继续 → `_consume_decision_field` 被调用 (如果 flag on) → `_maybe_execute_from_snapshot` 读取 `direct_execution`。

#### §3.2.0-C 范围红线 (A reconciliation vs P3 内部 aggregation)

**红线声明**:

A reconciliation 处理 P1 (stage2_raw) / P2 (stage3_yaml) / P3 (readiness_gate) **三个 producer 之间的 cross-source arbitration**。Reconciler 把 P3 当作**单一 producer 消费** — 输入 P3 的 disposition (D1/D2/D3) + clarify_candidates list, 不进入 P3 内部如何聚合 clarify_candidates。

**明确不在 Round 2 范围**:
- P3 内部 clarify_candidates 的 9-input-source aggregation 优先级优化 (Phase 2 audit §3.4.5 MISALIGNED)。这是 P3 readiness_gate 内部设计问题, 归 Phase 6 (Class D: AO classifier design gap 或 Phase 2 TASK-10)。
- P3 内部 `preserve_followup_slot` 逻辑 (line 551-583) 是否应对合法 turn 设置 PARAMETER_COLLECTION continuation。这是 P3 readiness_gate 的 followup-slot 策略问题, 归 Phase 6。

**Escalation 条件**: 如果 §3.3 reconciliation 规则设计时发现某个 case (如 task 110) 的根因在 P3 clarify_candidates 聚合逻辑内部, 而非 P1/P2/P3 之间的冲突 → STOP & report, 该 case 转 Phase 6。

#### §3.2.0-D Wave 1/2 helper 接口 (reconciler 显式参数注入)

**问题**: Wave 1 (`clarification_contract.py:356`) P1 数据是局部变量 `llm_payload`, 不写 `context.metadata`。Wave 2 P1 数据在 `context.metadata["stage2_payload"]`。Reconciler 不能假设固定 metadata key 作为 P1 来源。

**设计**: Reconciler 接受显式参数注入。定义 `Stage2RawSource` 等输入 dataclass, 由 Wave-specific helper 从各自数据源提取。

```python
# --- Input dataclasses (new file or contracts/ shared) ---

@dataclass
class Stage2RawSource:
    """P1: LLM 原始语义输出, 从 Wave 1/2 各自的 Stage 2 LLM 返回值提取。"""
    decision_value: Literal["proceed", "clarify", "deliberate", ""]  # "" = invalid/missing
    decision_confidence: float  # 0.0 if missing
    decision_reasoning: str
    decision_clarification_question: Optional[str]
    missing_required: List[str]  # LLM-claimed missing slots
    needs_clarification: bool
    intent_chain: List[str]  # LLM's planned tool chain
    # Full raw payload preserved for trace
    raw_payload: Dict[str, Any]

@dataclass
class Stage3YamlSource:
    """P2: governance 领域物理检验结果。"""
    yaml_missing_required: List[str]  # YAML contract required slots that are truly missing
    rejected_slots: List[str]  # slots that failed legal-value check
    optional_no_default: List[str]  # optional slots without declarative or runtime default
    optional_resolved_by_default: List[str]  # optional slots resolved by runtime default
    active_required_slots: List[str]  # the tool's required slots (from tool_spec)

@dataclass  
class ReadinessGateState:
    """P3: governance 程序门控的完整 disposition, 8 fields 不塌缩。"""
    disposition: Literal["hard_block", "q3_defer", "proceed"]
    clarify_candidates: List[str]
    clarify_required_candidates: List[str]
    clarify_optional_candidates: List[str]
    force_proceed_reason: Optional[str]
    optional_only_probe: bool
    preserve_followup_slot: Optional[str]
    has_direct_execution: bool
    # Raw metadata for trace
    raw_metadata: Dict[str, Any]
```

**Wave 2 helper** (新函数, 放在 `execution_readiness_contract.py` 或 `split_contract_utils.py`):
```python
# execution_readiness_contract.py, near line 256 (after clarify_candidates built)
def _build_stage2_raw_source(context: ContractContext) -> Stage2RawSource:
    payload = context.metadata.get("stage2_payload") or {}
    decision = payload.get("decision") or {}
    return Stage2RawSource(
        decision_value=str(decision.get("value") or "").strip().lower(),
        decision_confidence=float(decision.get("confidence", 0)),
        decision_reasoning=str(decision.get("reasoning") or ""),
        decision_clarification_question=str(decision.get("clarification_question") or "").strip() or None,
        missing_required=list(payload.get("missing_required") or []),
        needs_clarification=bool(payload.get("needs_clarification")),
        intent_chain=list((payload.get("intent") or {}).get("chain") or payload.get("chain") or []),
        raw_payload=dict(payload),
    )

def _build_stage3_yaml_source(
    missing_required: List[str], rejected_slots: List[str],
    optional_classification: Dict, active_required_slots: List[str],
) -> Stage3YamlSource:
    return Stage3YamlSource(
        yaml_missing_required=list(missing_required),
        rejected_slots=list(rejected_slots),
        optional_no_default=list(optional_classification.get("no_default") or []),
        optional_resolved_by_default=list(optional_classification.get("resolved_by_default") or []),
        active_required_slots=list(active_required_slots),
    )

def _build_readiness_gate_state(
    clarify_candidates, clarify_required_candidates, clarify_optional_candidates,
    force_proceed_reason, optional_only_probe, preserve_followup_slot,
    has_direct_execution, raw_metadata,
) -> ReadinessGateState:
    # Determine disposition from existing local state
    ...
```

**Wave 1 helper** (新函数, 放在 `clarification_contract.py`, 在 `_run_stage2_llm` 返回后):
```python
# clarification_contract.py, near line 356 (after Stage 2 LLM returns)
def _build_stage2_raw_source_from_llm(llm_payload: dict) -> Stage2RawSource:
    # Same shape as Wave 2, but source is local variable not context.metadata
    ...
```

**Reconciler 主函数签名** (§3.2.4 展开):
```python
def reconcile(
    stage2_raw: Stage2RawSource,
    stage3_yaml: Stage3YamlSource,
    readiness_gate: ReadinessGateState,
    context: Optional[ReconciliationContext] = None,
) -> ReconciledDecision:
    ...
```

### §3.2.1 ReconciledDecision dataclass 字段定义

```python
@dataclass
class ReconciledDecision:
    """A reconciliation 的输出: P1+P2+P3 三 producer 合并后的单一 decision。"""

    # ── 最终 decision ──
    decision_value: Literal["proceed", "clarify", "deliberate"]
    # 来源: 从 P1/P2/P3 合并 — 默认取 P1.decision_value, 除非 reconciliation rule 覆盖

    # ── B validator 过滤 + A reconcile 后的 missing slots ──
    reconciled_missing_required: List[str]
    # 来源: P1.missing_required → B validator filter (contract-grounding) → A reconcile
    # 含义: 必须是 YAML contract required_slots 的子集。P1 hallucinated slots 已过滤。
    # 预留给 §3.5 A/B 边界: B validator 输出 list → A reconciler 消费

    # ── clarify 时的问题文本 ──
    clarification_question: Optional[str]  # decision=clarify 时非空
    # 来源: 优先 P1.decision_clarification_question (LLM-generated), 
    #       fallback seed 可来自 P3 structured reason，但 final user-facing text
    #       必须经 LLM/reply pipeline regenerated 或 safe fallback

    # ── deliberate 时的推理文本 ──
    deliberative_reasoning: str  # decision=deliberate 时非空
    # 来源: P1.decision_reasoning

    # ── reconciler 内部裁决推理 ──
    reasoning: str
    # 含义: reconciler 为什么选择这个 decision_value (例: "LLM=proceed, YAML=all_required_filled,
    #   readiness=optional_probe_only → reconciled to proceed per rule R2")
    # 供 trace + debug + 论文写作

    # ── 各 source 原始贡献 ──
    source_trace: Dict[str, Any]
    # 结构: {"stage2_raw": {...}, "stage3_yaml": {...}, "readiness_gate": {...}}
    # 含义: 三 producer 的完整 snapshot, 供 subsequent audit + trace

    # ── 触发的规则 ID ──
    applied_rule_id: str
    # 来源: §3.3 规则编号 (例 "R1", "R2_optional_probe", "R4_fallback")
    # 含义: 哪条 reconciliation rule 触发了最终 decision
```

**字段来源 producer 汇总**:

| 字段 | 主要来源 | 备注 |
|------|---------|------|
| `decision_value` | P1 (stage2_raw) → P3 override (if needed) | LLM leads, governance P3 can upgrade clarify→proceed if optional-only probe |
| `reconciled_missing_required` | P1 (stage2_raw) → B filter → P2 (stage3_yaml) ground | LLM says X missing, B filters against contract, only P2 YAML slots remain |
| `clarification_question` | P1 (stage2_raw) preferred, P3 fallback | LLM-generated when possible |
| `deliberative_reasoning` | P1 (stage2_raw) | LLM's reasoning |
| `reasoning` | Reconciler internal | Generated by reconciliation logic |
| `source_trace` | P1+P2+P3 | Raw snapshots from all producers |
| `applied_rule_id` | Reconciler internal | Which §3.3 rule triggered |

**§3.2.1-1 决策已关闭**: 使用最终 7-field `ReconciledDecision` schema:
- `decision_value`
- `reconciled_missing_required`
- `clarification_question`
- `deliberative_reasoning`
- `reasoning`
- `source_trace`
- `applied_rule_id`

不增加 chain field。F1 validation runs before reconcile (§3.4), so F1 status fields do not belong in `ReconciledDecision`。

### §3.2.2 跟现有 Phase 3 结构的关系

**选择: ReconciledDecision 是 wrap/parallel, 不是 extend/replace**。

| 现有结构 | 关系 | 理由 |
|---------|------|------|
| **Phase 3 decision_field** (LLM 输出的 dict `{"value": ..., "confidence": ..., ...}`) | **wrap** — ReconciledDecision 包住 P1 raw decision, 但可能 override `decision_value` | P1 是 LLM 输出, reconciler 可能根据 P2/P3 覆盖 P1。P1 raw 保存在 `source_trace` 中, 不丢失 |
| **ContractInterception** (contract before_turn 返回类型) | **parallel** — ReconciledDecision 是 `_consume_decision_field` 的输入, ContractInterception 是 contract 的输出 | ContractInterception 不变 (P3 readiness_gate 仍然返回它)。ReconciledDecision 是新数据流, 在 contract 循环之后, `_consume_decision_field` 之前注入 |
| **validate_decision()** (F1 safety net, 现在返回 `(bool, str)`) | **pre-step** — validate_decision 在 reconciler 之前运行；F1 fail 时不调用 reconciler | §3.4 已定: validate_decision → reconcile → router_consume 三段式 |

**改动面**:

| 改动点 | 文件:行 | 性质 | 描述 |
|--------|---------|------|------|
| `_consume_decision_field` 改签名或逻辑 | `governed_router.py:557-674` | 修改 | 当前读 P1 raw → 改读 ReconciledDecision |
| 新 reconciler 调用点 | `governed_router.py:133-137` | 新增 | contract 循环后, `_consume_decision_field` 之前, 调 `reconcile(...)` 产生 ReconciledDecision |
| `validate_decision` 不变 | `decision_validator.py:10-54` | 不修改 | F1 check 仍由 reconciler 调用, API 不变 |

**§3.2.2-1 决策已关闭**: `ReconciledDecision` 与 `ContractInterception` 是 parallel, not extend/replace。`ReconciledDecision` 走 `_consume_decision_field` / `_consume_reconciled_decision` 路径, `ContractInterception` 保持 contract 返回路径。D1 disposition (hard-block) 直接在 contract 层由 `ContractInterception(proceed=False)` 处理, 不经过 reconciler。D2 (Q3 defer) 和 D3 (proceed) 经过 reconciler。

### §3.2.3 文件组织

**推荐: yes, 需要新文件 `core/contracts/reconciler.py`**。

理由:
- `decision_validator.py` 做 F1 安全网 (schema/confidence check), `reconciler.py` 做 cross-source arbitration — 不同职责, 不同文件
- Wave 1 + Wave 2 都需要 reconciler — 放在 contracts/ 下两个 wave 都能 import
- 当前 `execution_readiness_contract.py` 已 700+ 行, 放 reconciler 进去会加剧 god-file 问题
- 测试隔离: `test_reconciler.py` 可以 pure unit test, 不对 Wave 1/2 的 LLM 客户端有依赖
- 跟 `decision_validator.py` 的关系: 同目录, reconciler imports validate_decision

**备选**: 放进 `split_contract_utils.py`。不推荐 — split_contract_utils 是 Wave 2 专用 helpers, reconciler 是跨 Wave 的组件。

**`core/contracts/reconciler.py` 大致结构**:
```
# Input dataclasses (§3.2.0-D)
class Stage2RawSource:
class Stage3YamlSource:
class ReadinessGateState:
class ReconciliationContext:

# Output dataclass (§3.2.1)
class ReconciledDecision:

# Main reconciler function (§3.2.4)
def reconcile(s2: Stage2RawSource, s3: Stage3YamlSource,
              gate: ReadinessGateState, ctx: Optional[ReconciliationContext]) -> ReconciledDecision:

# Rule implementations (§3.3 — to be designed)
def _reconcile_all_agree(...) -> Optional[ReconciledDecision]:
def _reconcile_llm_proceed_readiness_optional_probe(...) -> Optional[ReconciledDecision]:
def _reconcile_llm_hallucinated_slots(...) -> Optional[ReconciledDecision]:

# Wave helpers (§3.2.0-D)
def build_stage2_raw_from_metadata(context_metadata: dict) -> Stage2RawSource:
def build_stage2_raw_from_llm_payload(llm_payload: dict) -> Stage2RawSource:
def build_stage3_yaml(...) -> Stage3YamlSource:
def build_readiness_gate_from_metadata(clarification_metadata: dict) -> ReadinessGateState:
```

**§3.2.3-1 决策已关闭**: Round 3 implementation 接受新增 `core/contracts/reconciler.py`。

### §3.2.4 Reconciler 接口签名

```python
# core/contracts/reconciler.py

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


@dataclass
class ReconciliationContext:
    """Optional context for reconciliation."""
    turn_index: int = 0
    wave: Literal["wave1", "wave2"] = "wave2"
    tool_name: str = ""


def reconcile(
    stage2_raw: Stage2RawSource,
    stage3_yaml: Stage3YamlSource,
    readiness_gate: ReadinessGateState,
    context: Optional[ReconciliationContext] = None,
) -> ReconciledDecision:
    """Merge P1 (stage2_raw) + P2 (stage3_yaml) + P3 (readiness_gate) → single decision.

    Reconciliation rules (§3.3) are applied in priority order. The first matching
    rule produces the final ReconciledDecision.
    
    Args:
        stage2_raw: P1 — LLM's raw semantic output (decision, missing_required, etc.)
        stage3_yaml: P2 — governance domain physics check (YAML-grounded missing slots)
        readiness_gate: P3 — governance procedural gate (disposition, clarify_candidates)
        context: Optional turn/mode metadata for trace.
    
    Returns:
        ReconciledDecision with the final reconciled value, reasoning, and source trace.
    """
    ...
```

**Wave 2 call site 伪代码** (`governed_router.py`, near line 133-137):

```python
# In GovernedRouter.chat(), after contract loop, before _consume_decision_field:
if result is None and bool(getattr(get_config(), "enable_llm_decision_field", False)):
    # NEW: build reconciler inputs from contract outputs
    from core.contracts.reconciler import (
        reconcile, build_stage2_raw_from_metadata, build_stage3_yaml,
        build_readiness_gate_from_metadata, Stage2RawSource, Stage3YamlSource,
        ReadinessGateState,
    )
    p1 = build_stage2_raw_from_metadata(context.metadata)
    p2 = build_stage3_yaml(
        missing_required=...,  # extracted from context.metadata or trace
        rejected_slots=...,
        optional_classification=...,
        active_required_slots=...,
    )
    p3 = build_readiness_gate_from_metadata(context.metadata.get("clarification") or {})
    rctx = ReconciliationContext(
        turn_index=self._current_turn_index(),
        wave="wave2",
        tool_name=p1.raw_payload.get("intent", {}).get("resolved_tool", ""),
    )
    reconciled = reconcile(p1, p2, p3, rctx)
    
    decision_result = self._consume_reconciled_decision(reconciled, context, trace)
    if decision_result is not None:
        result = decision_result
        context.router_executed = True
```

**Wave 1 call site 伪代码** (`clarification_contract.py`, near line 485+):

```python
# In ClarificationContract.before_turn(), after should_proceed decision tree:
if not should_proceed and self._decision_field_active(telemetry):
    from core.contracts.reconciler import (
        reconcile, build_stage2_raw_from_llm_payload, Stage3YamlSource,
        build_readiness_gate_from_metadata,
    )
    p1 = build_stage2_raw_from_llm_payload(llm_payload)  # from local variable
    p2 = Stage3YamlSource(
        yaml_missing_required=list(missing_required),
        rejected_slots=list(rejected_slots),
        optional_no_default=unfilled_optionals_without_default,
        optional_resolved_by_default=[],  # Wave 1 doesn't classify this
        active_required_slots=list(active_required_slots),
    )
    p3 = build_readiness_gate_from_metadata({"disposition": "q3_defer", ...})
    reconciled = reconcile(p1, p2, p3, ReconciliationContext(wave="wave1"))
    # Store reconciled in context.metadata for GovernedRouter to consume
    context.metadata["reconciled_decision"] = reconciled.to_dict()
```

**P2 数据在 Wave 2 的可用性 note**: 当前 P2 (`stage3_yaml`) 是 ExecutionReadinessContract 的局部变量 (line 149-156), 不写入 `context.metadata`。Reconciler 调用发生在 GovernedRouter (contract 循环之后), P2 数据需要通过 `context.metadata` 传递。方案: ExecutionReadinessContract 在 `before_turn` 结尾 (near line 632) 将 P2 数据写入 `context.metadata["stage3_yaml"]`。这是 1 行新增的 metadata write。

---

---

### §3.A 前置 Audit

#### §3.A.1 ReconciledDecision 7 字段实证

**Prompt 指定的 6 个最少字段**:
1. `decision_value` — Literal["proceed", "clarify", "deliberate"]
2. `reconciled_missing_required` — B validator filter + A reconcile 后的 missing slots
3. `clarification_question` — Optional[str], clarify 时的问题文本
4. `reasoning` — reconciler 内部裁决推理 (trace/debug)
5. `source_trace` — P1/P2/P3 原始 snapshot
6. `applied_rule_id` — §3.3 规则编号

**Codex 新增字段审查**:

| # | 字段 | 类型 | 新增理由 | 消费者 | Over-engineering? |
|---|------|------|---------|--------|-------------------|
| 7 | `deliberative_reasoning` | `str` | decision=deliberate 时 LLM 的推理文本需要独立于 reconciler 的 `reasoning` (后者是 reconciler 内部 trace 用的)。`_consume_decision_field` 在 deliberate 分支 (governed_router.py:658-672) 需要展示给 user。如果压缩到 `reasoning` 字段, 语义模糊 (reconciler-author vs LLM-author) | `_consume_decision_field` deliberate 分支 | **保留** — 确实需要。`reasoning` 是 reconciler 写给自己 trace 的, `deliberative_reasoning` 是 LLM 写个 user 看的 |

**§3.A.1 判决**: 保留 `deliberative_reasoning` (有明确的 consumer, 语义不跟 `reasoning` 重叠)。F1 validation runs before reconcile (§3.4)，所以 F1 状态不进入 `ReconciledDecision`。**最终 7 字段**: decision_value / reconciled_missing_required / clarification_question / deliberative_reasoning / reasoning / source_trace / applied_rule_id。

#### §3.A.2 D1 hard-block 触发条件实证 + task 105 路径判定 ⭐

**D1 三个出处的精确条件**:

| D1 出处 | 外层条件 | 内层判别 |
|---------|---------|---------|
| `execution_readiness_contract.py:365-372` | `clarify_candidates` 非空 (line 256) + NOT `probe_limit_reached` (line 258) + NOT `flag_on and optional_only_probe` (line 269) → else (line 295) | `if self._split_decision_field_active(context)` (line 357) → **False** → D1 hard-block |
| `execution_readiness_contract.py:416-432` | `branch == EXPLORATORY` (line 377) | `if self._split_decision_field_active(context)` (line 404) → **False** → D1 hard-block |
| `execution_readiness_contract.py:542-549` | `branch == DELIBERATIVE and no_default_optionals` (line 434) + `flag_on=False` (line 435) + NOT probe_limit_reached/abandon → hard-block path | `if self._split_decision_field_active(context)` (line 534) → **False** → D1 hard-block |

**统一判别**: D1 vs D2 的分水岭是 `_split_decision_field_active(context)` 的返回值。True → D2 Q3 defer, False → D1 hard-block。`_split_decision_field_active` (split_contract_utils.py:19-31) 检查:
```python
if not getattr(get_config(), "enable_llm_decision_field", False): return False
stage2 = context.metadata.get("stage2_payload")
if not isinstance(stage2, dict): return False
decision = stage2.get("decision")
if not isinstance(decision, dict): return False
return str(decision.get("value") or "").strip().lower() in {"proceed", "clarify", "deliberate"}
```

**Task 105 turn 2 路径判定**:

1. `enable_llm_decision_field = True` (governance_full mode)
2. Stage 2 raw `decision = {"value": "clarify", ...}` → valid → `_split_decision_field_active` = **True**
3. clarify_candidates = `["vehicle_type", "road_type"]` (hallucinated, 通过 stage2_needs_clarification 路径 line 229-236 注入)
4. `optional_only_probe` = False (clarify_required_candidates 非空)
5. `flag_on and optional_only_probe` = False → **进入 else at line 295**
6. `_split_decision_field_active` = True → **D2 Q3 defer (line 358)**
7. GovernedRouter 读到 Q3 defer metadata → `_consume_decision_field` → 读到 `decision=clarify` → 返回 LLM hallucinated question

**判决**: D1 does NOT intercept task 105. The path is **D2 → _consume_decision_field → reconciler can intervene**.

**Task 105 hallucinated slots 进入 clarify_candidates 的具体机制** (line 229-236):
```python
if stage2_needs_clarification and executed_tool_count == 0:
    stage2_required_candidates = self._missing_named_slots(
        snapshot, stage2_meta.get("stage2_missing_required") or []
    )
    clarify_candidates.extend(stage2_required_candidates)
```
`stage2_meta.get("stage2_missing_required")` 直接引用了 LLM 的 `missing_required` = `["vehicle_type", "road_type"]` (hallucinated)。`_missing_named_slots(snapshot, ["vehicle_type", "road_type"])` 检查 snapshot 中是否这些 slot 的值为空 → 是 (snapshot 没有这两个非 contract slot) → 返回 `["vehicle_type", "road_type"]` → extend 进 clarify_candidates。

**这意味着 B validator 的 contract-grounding filter 不能只 filter `stage2_raw.missing_required`，也必须 filter `readiness_gate.clarify_candidates`，因为 hallucinated slots 通过 line 229-236 进入了 clarify_candidates list。或者 alternatively，B validator 应该在 line 229-236 之前 filter `stage2_meta.get("stage2_missing_required")`，阻止 hallucinated slots 进入 clarify_candidates。这是 §3.5 A/B 边界需要解决的设计选择。**

**§3.A.2 判决**: D1 不包含 task 105 case。Fix 路径经过 D2 → reconciler。Continue §3.3。

---

### §3.3 Reconciliation 规则

每条规则: (前提 / 后果 / 优先级 / source 引用 / F2-F3 对照)。规则按优先级降序排列, reconciler 按顺序匹配第一条命中的规则。

#### 3.3.1 规则优先级总览

| 优先级 | 规则 | 覆盖 case | 一句话 |
|--------|------|----------|--------|
| P0 (最高) | R4 — F1 边界 | Stage 2 decision 不合法 (confidence<0.5, schema invalid) | F1 fail → 不 reconcile, 回 hard-rule 路径 |
| P1 | R3 — 一致性 | 4 source 全一致 | Trivial pass-through |
| P2 | R1 — LLM proceed vs readiness block | Task 110 | LLM 说 proceed, YAML 说 slots complete, readiness 说 optional probe → reconcile 为 proceed |
| P3 | R2 — LLM clarify hallucinated | Task 105 | LLM 说 clarify + missing X, YAML 说 X 不是 required → reconcile 为 proceed |

#### 3.3.2 Rule R4 — F1 边界 (最高优先级)

- **前提**: `stage2_raw.decision_value not in {"proceed", "clarify", "deliberate"}` OR `stage2_raw.decision_confidence < 0.5` OR (decision=proceed AND stage2_raw.missing_required 非空)
- **后果**: Reconciler **不产出** ReconciledDecision。返回 None 或 raise, caller fallback 到现有 hard-rule 路径。
- **优先级**: P0 (最高)。F1 是所有 reconciler 规则的前置 gate。
- **source 引用**: `decision_validator.py:10-54` — `validate_decision(stage2_output)` 返回 `(is_valid, reason)`。Reconciler 第一步调用它。
- **F2 对照**: F1 是 F2 的实现机制 — "LLM confidence < 0.5 时 governance 不信任 LLM 的 pragmatics 判断"。这不是 governance 在 pragmatics 层面覆盖 LLM, 而是 governance 在 LLM 自身承认不确定性时启动安全网。
- **F3 对照**: 不相关 — F1 不涉及 reply text 生成。

#### 3.3.3 Rule R3 — 一致性 case

- **前提**: `stage2_raw.decision_value == readiness_gate.disposition_equivalent` AND `stage3_yaml.yaml_missing_required == B_filter(stage2_raw.missing_required)` (LLM 说的 missing slots 跟 YAML 一致)。定义 `disposition_equivalent`: D2 (Q3 defer with hardcoded_recommendation="clarify") eq "clarify", D3 (proceed) eq "proceed", D1 (hard-block) eq "clarify"。
- **后果**: `reconciled_decision = {decision_value: stage2_raw.decision_value, ...}` — **直接透传**, 不做任何 override。`applied_rule_id = "R3_trivial"`。
- **优先级**: P1。一致性是最常见的 case (估计 70-80% turns)。不需要 reconcile 逻辑, 但要记录该 rule 被命中 (供 trace)。
- **source 引用**: P1+P2+P3 全部一致 → 不需要 arbitration。
- **F2 对照**: LLM pragmatics 和 governance domain physics 一致 → 无冲突 → governance 不介入。F2 字面支持 (只有当 LLM 触碰领域硬边界时 governance 才介入)。
- **F3 对照**: 不相关。

#### 3.3.4 Rule R1 — LLM proceed vs readiness optional block (Task 110)

- **前提**:
  1. `stage2_raw.decision_value == "proceed"`
  2. `B_filter(stage2_raw.missing_required) == []` (LLM 说的 missing slots, 经 B validator contract-grounding 后, 在 YAML required 范围内没有 missing)
  3. `stage3_yaml.yaml_missing_required == []` (YAML contract 确认所有 required slots 已填充)
  4. `readiness_gate.disposition == D2 ("q3_defer")` OR `readiness_gate.clarify_candidates` 非空但全部属于 `optional` 或 `followup` slots (optional-only probe)
  5. `readiness_gate.force_proceed_reason == None` (不是 probe_limit_reached 或 advisory_mode 的 force-proceed — 只说明 readiness 没主动放弃阻塞)

- **后果**: `reconciled_decision.decision_value = "proceed"`。`clarification_question = None`。`reasoning = "LLM=proceed, YAML=all required filled, readiness=optional-only probe → reconciled to proceed per R1. Governance should not block execution for optional slot probing when required slots are complete."` (或类似)。`applied_rule_id = "R1_proceed_override"`。

- **优先级**: P2。LLM 对 proceed 的判断 + YAML 对 required slots complete 的确认 = pragmatics + physics 对齐, readiness 的 optional probe 不应阻塞。

- **source 引用**:
  - P1: `stage2_raw.decision_value`, `stage2_raw.missing_required` (post-B-filter)
  - P2: `stage3_yaml.yaml_missing_required`
  - P3: `readiness_gate.disposition`, `readiness_gate.clarify_candidates`, `readiness_gate.clarify_required_candidates`

- **F2 对照**: readiness gate 的 optional probe 是 conversational pragmatics (判断用户"是否还想填 model_year"), 不是 domain physics (vehicle+road 兼容性)。F2: LLM owns pragmatics → LLM 说 proceed → governance 尊重。YAML required complete = domain physics confirms no blocker。两者一致 → proceed。

- **F3 对照**: 不直接相关。Proceed 后的 reply text 由 reply LLM 生成。

- **Task 110 turn 3 演示** (见 §3.7): 此规则命中, reconciled = proceed, user gets tool execution。

#### 3.3.5 Rule R2 — LLM clarify with hallucinated slots (Task 105, 跟 B validator 协同)

- **前提**:
  1. `stage2_raw.decision_value == "clarify"`
  2. `stage2_raw.missing_required` 含有不在 YAML contract required_slots 也不是 followup_slots 的 slot (hallucinated)
  3. `B_filter(stage2_raw.missing_required) == []` (B validator contract-grounding 后, 无合法 missing required)
  4. `stage3_yaml.yaml_missing_required == []` (YAML 确认所有 required slots 已填充)

- **后果**: `reconciled_decision.decision_value = "proceed"`。`reconciled_missing_required = []` (B 已过滤 hallucinated slots)。`clarification_question = None`。`reasoning = "LLM=clarify with X,Y but contract requires only Z; YAML=all required filled → hallucinated missing_required filtered by B validator → reconciled to proceed per R2"`。`applied_rule_id = "R2_hallucination_filtered"`。

- **优先级**: P3。比 R1 低 — 如果 R1 的条件也满足 (LLM proceed), R1 先命中。R2 处理 LLM clarify 但理由不合法的情况。

- **source 引用**:
  - P1: `stage2_raw.missing_required` → B validator filter → `B_filter(stage2_raw.missing_required)`
  - P2: `stage3_yaml.yaml_missing_required`, `stage3_yaml.active_required_slots`
  - P3: `readiness_gate.clarify_candidates` (可能已包含 hallucinated slots via line 229-236 — 见 §3.A.2)

- **F2 对照**: LLM 说 "需要 vehicle_type" 但 YAML contract 说 macro emission 不需要 vehicle_type → LLM 在领域知识上犯错 (domain physics)。Governance 的 YAML contract 纠正 LLM。F2: governance owns domain physics → governance wins。LLM 的 clarify 判断被 override, 因为 LLM 的 pragmatics 判断基于错误的 domain 前提。

- **F3 对照**: 不直接相关。

- **跟 B validator 协同**: B validator 做 per-decision contract-grounding: `stage2_raw.missing_required → filter against contract required/followup → B_filtered_missing_required`。R2 消费 B validator 的输出。如果 `B_filter(stage2_raw.missing_required)` 为空 + `stage3_yaml.yaml_missing_required` 为空 → R2 命中。

- **关于 hallucinated slots in clarify_candidates (§3.A.2 发现)**: Line 229-236 把 `stage2_meta.get("stage2_missing_required")` (即 LLM 的原始 missing_required) extend 进 clarify_candidates。B validator 需要在 clarify_candidates 被 build 之前 (即 ExecutionReadiness 内部) 或之后 (即 reconciler 内部) filter 掉这些 hallucinated slots。这是 §3.5 决定 A/B 边界 (a/b/c) 时需要解决的关键实施细节。

---

### §3.4 A reconciler 跟 F1 validate_decision 的关系

#### 3.4.1 关系选择: F1 是 reconciler 的前置 gate

**§3.4-1 决策已关闭**: F1 first。`validate_decision()` runs before `reconcile()`。If F1 fails, do not feed invalid Stage 2 decision into the reconciler; fallback to existing safe path / hard-rule behavior。

**代码层调用顺序** (reconcile → validate_decision 还是 validate_decision → reconcile?):
```
F1 validate_decision() 先 → 若 pass → reconcile() → router_consume
                      → 若 fail → fallback hard-rule 路径
```

**推荐理由**:
1. F1 是 safety net — 检查 decision 的 basic validity (schema/confidence/consistency)。如果 decision 本身 broken, reconcile 没有意义。
2. F1 规则简单 deterministic, 不应被 reconciler 的 cross-source arbitration 覆盖。
3. 备选 (reconcile first, F1 annotates) 产出一个 "partially valid" ReconciledDecision, consumer 需要判断是否信任 — 增加 consumer 复杂度。

**冲突裁决**: 不存在直接冲突 — F1 fail 时 reconciler 不运行, 没有 "F1 say fallback 但 reconcile say proceed" 的场景。

#### 3.4.2 governed_router.py 改动方案

**Before** (`governed_router.py:133-137`, current):
```python
if bool(getattr(get_config(), "enable_llm_decision_field", False)):
    decision_result = self._consume_decision_field(context, trace)
    if decision_result is not None:
        result = decision_result
        context.router_executed = True
```

**After** (pseudocode):
```python
if bool(getattr(get_config(), "enable_llm_decision_field", False)):
    # Step 1: F1 safety check
    stage2_payload = context.metadata.get("stage2_payload") or {}
    decision_valid, validation_reason = validate_decision(stage2_payload)
    
    if not decision_valid:
        # F1 fail → fall through to hard-rule path (existing behavior)
        logger.debug("F1 validation failed: %s — falling back", validation_reason)
        # trace step (NEW)
        self._record_trace_step(trace, "decision_field_f1_fallback",
            {"reason": validation_reason, "decision": stage2_payload.get("decision")})
        # fall through → _maybe_execute_from_snapshot → inner_router.chat
    else:
        # Step 2: build reconciler inputs
        from core.contracts.reconciler import reconcile, build_stage2_raw_from_metadata, \
            build_stage3_yaml, build_readiness_gate_from_metadata, ReconciliationContext
        
        p1 = build_stage2_raw_from_metadata(context.metadata)
        p2 = build_stage3_yaml(
            missing_required=context.metadata.get("stage3_yaml", {}).get("missing_required", []),
            rejected_slots=context.metadata.get("stage3_yaml", {}).get("rejected_slots", []),
            optional_classification=context.metadata.get("stage3_yaml", {}).get("optional_classification", {}),
            active_required_slots=context.metadata.get("stage3_yaml", {}).get("active_required_slots", []),
        )
        p3 = build_readiness_gate_from_metadata(context.metadata.get("clarification") or {})
        rctx = ReconciliationContext(
            turn_index=self._current_turn_index(), wave="wave2",
            tool_name=(stage2_payload.get("intent") or {}).get("resolved_tool", ""),
        )
        reconciled = reconcile(p1, p2, p3, rctx)
        
        # Step 3: route based on reconciled decision
        decision_result = self._consume_reconciled_decision(reconciled, context, trace)
        if decision_result is not None:
            result = decision_result
            context.router_executed = True
```

**`_consume_reconciled_decision` 新方法** (`governed_router.py`, 替换/扩展 `_consume_decision_field` 的消费逻辑):
```python
def _consume_reconciled_decision(self, rd: ReconciledDecision, context, trace):
    if rd.decision_value == "proceed":
        # Cross-constraint preflight (existing logic, moved from _consume_decision_field)
        # ... same as current lines 589-638
        return None  # fall through to snapshot/inner_router
    elif rd.decision_value == "clarify":
        question = rd.clarification_question or ""
        # ... return RouterResponse(text=question)
    elif rd.decision_value == "deliberate":
        reasoning = rd.deliberative_reasoning or ""
        # ... return RouterResponse(text=reasoning)
```

---

### §3.5 A reconciler 跟 B validator 的边界

#### 3.5.1 职责划分

| 组件 | 职责 | 输入 | 输出 |
|------|------|------|------|
| **B validator** | Per-decision contract-grounding: 过滤 LLM 声称的 `missing_required`, 只保留属于 YAML contract `required_slots` ∪ `clarification_followup_slots` 的 slot | `stage2_raw.missing_required` (List[str]) + tool contract spec | `b_filtered_missing_required` (List[str]) — 去掉 hallucinated slots |
| **A reconciler** | Cross-source arbitration: P1 (LLM semantics, post-B-filter) vs P2 (YAML physics) vs P3 (readiness gate) 冲突裁决 | Stage2RawSource, Stage3YamlSource, ReadinessGateState | ReconciledDecision |

#### 3.5.2 关系选择: B 是 A-called contract-grounding filter

**§3.5-1 决策已关闭**: B 是 A-called contract-grounding filter, not a linear hard gate。B does not output proceed/clarify/deliberate。B outputs grounded slot subsets + telemetry only。A calls B at the two filter points already described。

**推荐理由**:
1. A reconciler 的规则 (R1, R2) 依赖 "LLM 说的 missing_required 是否合法" 这个判断。如果 B 在 A 内部, A 每一条规则都要自己做 contract-grounding → 重复代码。
2. B 的 filter 是 per-decision (只对 stage2_raw 操作), A 的 reconciliation 是 cross-source (P1 vs P2 vs P3)。前置 filter 让 A 的规则更干净: A 不需要关心 "LLM 是否 hallucinated", 只需要关心 "post-filter 的状态 vs readiness_gate 的状态"。
3. 备选 (b) 平行 在 merge 点需要额外的 "谁先 running" 协调逻辑。备选 (c) B within A 使 reconcier 代码复杂, 不如 (a) 清晰。

#### 3.5.3 §3.A.2 发现: B validator 需要 filter 两个地方

**§3.A.2 关键发现**: Task 105 hallucinated slots (`vehicle_type`, `road_type`) 通过 `execution_readiness_contract.py:229-236` 的 `stage2_needs_clarification` 路径进入了 `clarify_candidates` list。B validator 如果只 filter `stage2_raw.missing_required`, hallucinated slots 仍然存在于 P3 `readiness_gate.clarify_candidates` 中。

**方案**: B validator 有两个 filter 点:
1. **B-filter point 1** — Filter `stage2_raw.missing_required` (P1 input, 在 reconciler 入口)
2. **B-filter point 2** — Filter `readiness_gate.clarify_candidates` 中的 hallucinated entries (P3 input, 在 reconciler 入口或 readiness contract 内部)

推荐: B-filter point 2 放在 reconciler 内部 (在 build_readiness_gate_from_metadata 之后, reconcile 之前), 因为:
- 不修改 ExecutionReadinessContract 内部逻辑 (减少改动面)
- Reconciler 拿到 D2 disposition 的 clarify_candidates, B-filter 后如果 clarify_required_candidates 变空 + clarify_optional_candidates 为空 → readiness_gate 等效 disposition 从 "clarify" 变 "proceed" → R2 命中

**实施**: `reconciler.py` 中的 `build_readiness_gate_from_metadata()` 或 reconciler 入口接受 tool_contract spec 参数, 对 `clarify_candidates` 做 contract-grounding filter。

#### 3.5.4 调用顺序图 (file:line level)

```
governed_router.py:133-137
  │
  ├─ validate_decision(stage2_payload)              # decision_validator.py:10
  │   ↓ F1 pass
  │
  ├─ B validator: filter_stage2_raw(stage2_raw, tool_contract)   # NEW in reconciler.py
  │   Input: stage2_raw.missing_required
  │   Output: b_filtered_missing_required
  │
  ├─ build_readiness_gate_from_metadata(metadata)    # NEW in reconciler.py
  │   B-filter: filter clarify_candidates against contract
  │   Output: ReadinessGateState (with filtered clarify_candidates)
  │
  ├─ reconcile(p1, p2, p3, ctx)                      # NEW in reconciler.py
  │   ├─ R4 check (F1 pre-condition)
  │   ├─ R3 check (consistency, all agree)
  │   ├─ R1 check (LLM proceed vs readiness block)
  │   ├─ R2 check (LLM clarify hallucinated)
  │   └─ Output: ReconciledDecision
  │
  └─ _consume_reconciled_decision(reconciled)         # MODIFIED in governed_router.py
      ├─ proceed → cross-constraint preflight → fall-through or block
      ├─ clarify → RouterResponse(text=question)
      └─ deliberate → RouterResponse(text=reasoning)
```

---

### §3.6 改动面 (Wave 2 primary + Wave 1 同步)

#### 3.6.1 新文件: `core/contracts/reconciler.py`

| # | 内容 | LOC | 性质 |
|---|------|-----|------|
| R1 | Input dataclasses: `Stage2RawSource`, `Stage3YamlSource`, `ReadinessGateState`, `ReconciliationContext` | +40 | 新增 |
| R2 | Output dataclass: `ReconciledDecision` (7 fields) | +30 | 新增 |
| R3 | `reconcile()` main function (规则调度) | +30 | 新增 |
| R4 | Rule implementations: `_rule_r1_llm_proceed_override()`, `_rule_r2_hallucination_filtered()`, `_rule_r3_trivial()`, `_rule_r4_f1_fallback()` | +60 | 新增 |
| R5 | B validator: `filter_stage2_missing_required()` + `filter_clarify_candidates()` | +25 | 新增 |
| R6 | Wave helpers: `build_stage2_raw_from_metadata()`, `build_stage2_raw_from_llm_payload()`, `build_stage3_yaml()`, `build_readiness_gate_from_metadata()` | +50 | 新增 |
| **Total** | | **+235** | |

#### 3.6.2 `core/contracts/decision_validator.py`

| # | 文件:行 | 当前代码 | 改动后 | LOC | 性质 |
|---|---------|---------|--------|-----|------|
| D1 | `decision_validator.py:10-54` | `def validate_decision(stage2_output: dict) -> Tuple[bool, Optional[str]]:` — 5 F1 rules | **不改动函数签名**。可选新增 `validate_decision_from_source(s: Stage2RawSource)` wrapper | +5 | 新增 wrapper |

不修改核心函数 — F1 规则不变。

#### 3.6.3 `core/governed_router.py`

| # | 文件:行 | 当前代码 (grep 实证) | 改动后 | LOC | 性质 |
|---|---------|---------------------|--------|-----|------|
| G1 | `governed_router.py:133-137` | `if bool(getattr(get_config(), "enable_llm_decision_field", False)): decision_result = self._consume_decision_field(context, trace)` | 替换为 F1 check → reconcile → _consume_reconciled_decision 三段式 (见 §3.4.2 after 伪代码) | +30/-8 | 修改 |
| G2 | `governed_router.py:557-674` | `def _consume_decision_field(self, context, trace) -> Optional[RouterResponse]:` — 当前读 stage2_payload 直接路由 | 替换为 `def _consume_reconciled_decision(self, rd: ReconciledDecision, context, trace) -> Optional[RouterResponse]:` — 消费 ReconciledDecision。保留 cross-constraint preflight 逻辑 (line 589-638) | +40/-80 | 修改/删除 |

#### 3.6.4 `core/contracts/execution_readiness_contract.py`

| # | 文件:行 | 当前代码 (grep 实证) | 改动后 | LOC | 性质 |
|---|---------|---------------------|--------|-----|------|
| E1 | `execution_readiness_contract.py:630` (before return) | `return ContractInterception(metadata={"clarification": clarification_metadata})` | 在 return 之前写入 P2 数据到 `context.metadata["stage3_yaml"]` | +5 | 新增 |
| E2 | `execution_readiness_contract.py:630` | — | `context.metadata["stage3_yaml"] = {"missing_required": missing_required, "rejected_slots": rejected_slots, "optional_classification": optional_classification, "active_required_slots": active_required_slots}` | +5 | 新增 |

**G1 改动实证**:
```python
# Current (line 133-137):
            if bool(getattr(get_config(), "enable_llm_decision_field", False)):
                decision_result = self._consume_decision_field(context, trace)
                if decision_result is not None:
                    result = decision_result
                    context.router_executed = True
```

#### 3.6.5 `core/contracts/intent_resolution_contract.py`

| # | 文件:行 | 当前代码 | 改动后 | LOC | 性质 |
|---|---------|---------|--------|-----|------|
| I1 | `intent_resolution_contract.py:123` (after _persist_tool_intent) | — | P2 数据 (active_required_slots 来自 generic tool_spec 或 None) 通过 metadata propagate 到后续 ExecutionReadiness | 0 | 不改动 — ExecutionReadiness 已负责 P2 output |

IntentResolution 不直接参与 reconciliation — 它 writes P1 (stage2_payload) to context.metadata, ExecutionReadiness consumes it and may overwrite. No change needed.

#### 3.6.6 Wave 1 同步: `core/contracts/clarification_contract.py`

| # | 文件:行 | 当前代码 (grep 实证) | 改动后 | LOC | 性质 |
|---|---------|---------------------|--------|-----|------|
| C1 | `clarification_contract.py:485-516` (Q3 gate section) | `if not should_proceed: if self._decision_field_active(telemetry): telemetry.final_decision = "deferred_to_decision_field" ... return ContractInterception(metadata=...)` | 如果不应 proceed + decision_field active → 用 Wave 1 helper 构建 reconciler 输入, 调 reconcile(), 把 ReconciledDecision 写入 `context.metadata["reconciled_decision"]` (供 GovernedRouter 读取) | +20 | 新增/修改 |
| C2 | `clarification_contract.py:381-382` | `tool_intent = self.intent_resolver.resolve_with_llm_hint(...) self._persist_tool_intent(current_ao, tool_intent)` | 不改动 — P1 数据已从局部 llm_payload 提取 | +0 | 不改动 |

**LOC 总估**: +295 (新增) / -88 (删除) ≈ **+207 net**。

---

### §3.7 Task 110 turn-by-turn 演示

基于 `end2end_logs.jsonl` (Round 1.4 governance_full rep_1) 的 trace evidence + Round 1.5 audit §2.3 分析。

Task 110: `e2e_clarification_110` — expected `query_emission_factors` with `vehicle_type="Refuse Truck"`, `pollutants=["PM10"]`, `model_year="2020"`.

#### Turn 1

**Input sources** (from trace + audit):
```
P1 stage2_raw:
  decision_value: "clarify"
  decision_confidence: 0.90 (est.)
  missing_required: ["vehicle_type", "pollutants"] (LLM, correct — tool requires both)
  needs_clarification: true

P2 stage3_yaml:
  yaml_missing_required: ["vehicle_type", "pollutants"]
  rejected_slots: []
  active_required_slots: ["vehicle_type", "pollutants"]  (query_emission_factors)

P3 readiness_gate:
  disposition: D2 ("q3_defer")  (clarify_candidates non-empty, _split_decision_field_active=True)
  clarify_candidates: ["vehicle_type", "pollutants"]
  clarify_required_candidates: ["vehicle_type", "pollutants"]
  clarify_optional_candidates: []
  force_proceed_reason: None
```

**B validator output**:
```
b_filtered_missing_required: ["vehicle_type", "pollutants"]
(all LLM-claimed slots are in contract required_slots → no hallucination)
```

**Reconciler trace**:
```
R4 check: F1 valid (confidence >= 0.5, decision=clarify, clarification_question non-empty) → pass
R3 check: stage2_raw.decision=clarify, readiness_gate.disposition=D2=clarify, 
         B_filter(missing_required)==yaml_missing_required → ALL AGREE
Rule applied: §3.3 R3 (consistency)
```

**Output**:
```
reconciled_decision:
  decision_value: "clarify"
  reconciled_missing_required: ["vehicle_type", "pollutants"]
  clarification_question: (LLM's question about vehicle type and pollutant)
  reasoning: "R3_trivial: all 3 producers agree on clarify"
  applied_rule_id: "R3_trivial"
```

**Effect**: GovernedRouter returns LLM's clarification question. User asked "需要什么车型和污染物？". Correct behavior — underspecified first turn.

#### Turn 3 (关键 — Round 1.5 audit 标注的 fail 点)

**Turn 2 context** (recap): User replied "Refuse Truck" and "PM10" in separate follow-ups. By turn 3, vehicle_type and pollutants are filled.

**Input sources** (from trace + audit §2.3):
```
P1 stage2_raw:
  decision_value: "proceed"
  decision_confidence: 0.85 (est. — "所有必需参数已齐，model_year可使用默认值2020")
  missing_required: [] (LLM: all required slots filled)
  needs_clarification: false

P2 stage3_yaml:
  yaml_missing_required: [] (vehicle_type="Refuse Truck", pollutants=["PM10"] both present)
  rejected_slots: []
  optional_no_default: [] (model_year has runtime_default=2020 → resolved_by_default)
  optional_resolved_by_default: ["model_year"]
  active_required_slots: ["vehicle_type", "pollutants"]

P3 readiness_gate:
  disposition: D2 ("q3_defer")
    (clarify_candidates may be non-empty due to preserve_followup_slot=model_year at line 572,
     OR may be D3 "proceed" if clarify_candidates is empty)
  clarify_candidates: ["model_year"] (followup slot, optional, has runtime default)
  clarify_required_candidates: []
  clarify_optional_candidates: ["model_year"]
  force_proceed_reason: None
```

**Note on P3 disposition for turn 3**: 目前有两种可能性取决于 followup_slots 处理:
- (A) `preserve_followup_slot = "model_year"` → continuation PARAMETER_COLLECTION set → clarify_candidates may include model_year → D2 Q3 defer
- (B) `flag_on=true` + optional_only_probe → advisory mode force_proceed → D3 proceed

但 Round 1.4 trace 显示 **0 tool calls** — 说明当前代码走到了 clarify 而非 proceed。这证实了 (A) 路径 (D2 Q3 defer → _consume_decision_field 读 P1 decision=proceed → fall through → then `_maybe_execute_from_snapshot` 可能因为某些原因没执行, 或者 `_consume_decision_field` 在 proceed 后 fall through 但 `_maybe_execute_from_snapshot` 因为 followup pending 被跳过)。

不管当前 disposition 是 D2 还是 D3, reconciler 都处理:

**B validator output**:
```
b_filtered_missing_required: [] (stage2_raw.missing_required already empty)
```

**Reconciler trace**:
```
R4 check: F1 valid (confidence >= 0.5, decision=proceed, missing_required empty) → pass
R3 check: stage2_raw.decision=proceed BUT readiness_gate.disposition=D2 (clarify)
         → NOT all agree → skip R3
R1 check:
  1. stage2_raw.decision_value == "proceed" ✓
  2. B_filter(stage2_raw.missing_required) == [] ✓
  3. stage3_yaml.yaml_missing_required == [] ✓
  4. readiness_gate.disposition in {D2, D3} ✓
  5. readiness_gate.clarify_required_candidates == [] ✓ (optional-only)
  → R1 MATCHED
Rule applied: §3.3 R1 (proceed override)
```

**Output**:
```
reconciled_decision:
  decision_value: "proceed"
  reconciled_missing_required: []
  clarification_question: None
  deliberative_reasoning: ""
  reasoning: "LLM=proceed, YAML=all required filled, readiness=optional-only probe (model_year followup) → reconciled to proceed per R1. F2: governance should not block execution for optional slot probing when required slots complete."
  applied_rule_id: "R1_proceed_override"
  source_trace: {stage2_raw: {decision: "proceed", ...}, stage3_yaml: {missing_required: [], ...}, readiness_gate: {disposition: "q3_defer", clarify_required: [], ...}}
```

**Effect**:
- `_consume_reconciled_decision` sees `decision_value="proceed"` → cross-constraint preflight (Refuse Truck + PM10 → OK) → passes → returns None
- Falls through to `_maybe_execute_from_snapshot` → `direct_execution` dict present (projected_chain=["query_emission_factors"]) → executes `query_emission_factors(vehicle_type="Refuse Truck", pollutants=["PM10"], model_year=2020, season="夏季")`
- User-visible: tool execution result with CO2 emission factors for Refuse Truck + PM10 + 2020
- Benchmark: tool_chain=["query_emission_factors"] matches expected → **PASS** ✓

**对比修复前/后**:

| | Turn 3 结果 | 最终 tool calls | Benchmark |
|---|------------|----------------|-----------|
| 修复前 (Round 1.4) | Stage 2 proceed 但 readiness blocks → 0 tool calls | 0 | FAIL |
| 修复后 (A reconciler) | R1 reconciled = proceed → tool executes | 1 × query_emission_factors | **PASS** ✓ |

---

*§3 结束。Round 2 source model, schema, integration path, F1 order, and A/B boundary decisions are closed for Round 3 planning。*

---

## §4 Class B — B validator (contract-grounding filter) 设计

### §4.A Preflight Verify

#### Finding A: B/A 边界澄清 (close §4.A.1)

§3.5.2 选了 "(a) B 是 A 的前置 step"。这句话在语义上有 nuance，必须在 §4 中细化：

1. **B 不是 A reconciler 本体**。B 是独立的 contract-grounding validator 函数集合 (`filter_stage2_missing_required` + `filter_clarify_candidates`)，放在 `reconciler.py` 中但与 reconciler 的 cross-source arbitration 逻辑分开。

2. **A 是 orchestrator，A 在两个位置调用 B**：
   - Filter Point 1: reconcile 之前，过滤 `stage2_raw.missing_required`
   - Filter Point 2: reconcile 过程中 / readiness gate 输入进入 A 前，过滤 `readiness_gate.clarify_candidates`

3. **B 的输出是 `ContractGroundingResult`** (grounded_slots + dropped_slots + evidence)，不是 `ReconciledDecision`，也不是 `decision_value`。

4. **B 只判断 slot 是否 contract-grounded** (slot ∈ required_slots ∪ clarification_followup_slots)，不决定 proceed / clarify / deliberate。

5. **B 不替 LLM 做 conversational pragmatics** — B 不判断 "这个 slot 该不该问"，只判断 "这个 slot 是不是 contract 声明的 slot"。不倒退成 PCM hard-block。

6. **"B 前置 step" 的准确含义**: 不是单个线性 pre-step，而是 A orchestrator 在两个输入点调用同一个 B validator 接口。调用顺序图见 §4.4。

#### Finding B: 5-file change surface verify (close §4.A.2.1)

**§3.6 实际列出了 6 个 section (3.6.1-3.6.6)，完整清单如下**：

| # | 文件 | §3.6 section | 改动性质 | 理由 |
|---|------|-------------|---------|------|
| 1 | `core/contracts/reconciler.py` | §3.6.1 | **新增** (+235 LOC) | 所有 input/output dataclass + main reconciler + B validator 函数 + Wave helpers |
| 2 | `core/contracts/decision_validator.py` | §3.6.2 | **极小改动** (+5 LOC) | 可选新增 `validate_decision_from_source(s: Stage2RawSource)` wrapper；核心 F1 规则不变 |
| 3 | `core/governed_router.py` | §3.6.3 | **修改** (+70/-88 LOC) | G1: 替换 line 133-137 为 F1→reconcile→consume 三段式；G2: `_consume_decision_field` → `_consume_reconciled_decision` |
| 4 | `core/contracts/execution_readiness_contract.py` | §3.6.4 | **新增 metadata write** (+5 LOC) | E1/E2: line ~630 写入 `context.metadata["stage3_yaml"]` 暴露 P2 数据 |
| 5 | `core/contracts/clarification_contract.py` | §3.6.6 | **Wave 1 同步** (+20 LOC) | C1: line ~485-516 Q3 gate 接入 reconciler，写 `context.metadata["reconciled_decision"]` |
| — | `core/contracts/intent_resolution_contract.py` | §3.6.5 | **不改动** (0 LOC) | IntentResolution 只写 P1 (`stage2_payload`)，不参与 reconciliation |

**结论**: 5 个实际改动文件是 #1-#5。§3.6.5 intent_resolution_contract.py 明确标了 "0 LOC 不改动"，不应算入改动面。

**关于 Wave 1 `clarification_contract.py` explicit ack**:
- **是，Wave 1 在改动面内** (文件 #5)。
- 改动 call site: `clarification_contract.py` line ~485-516，当前 Q3 gate 段 (`if not should_proceed: if self._decision_field_active(telemetry): ... return ContractInterception(metadata={...})`)。
- 改动内容: 在 `_decision_field_active` 分支中，用 Wave 1 helper (`build_stage2_raw_from_llm_payload`) 构建 reconciler 输入，调用 `reconcile()`，将 `ReconciledDecision` 写入 `context.metadata["reconciled_decision"]`。
- GovernedRouter 的 `_consume_reconciled_decision` 统一消费此 metadata，Wave 1/2 路径在此汇合。
- **不改动** `clarification_contract.py` 的 Stage 2 LLM 调用逻辑 (line 343-391)、`_persist_tool_intent` (line 1024, W3)、`_extract_llm_intent_hint` (line 889-911)。B validator 的 contract-grounding 是 post-hoc filter，不修改 Stage 2 prompt 或 intent 持久化。

#### Finding C: LOC 算术对账 (close §4.A.2.2)

**handoff 数字 vs §3.6 逐段加总 vs 实证**:

| 来源 | 算式 | 结果 |
|------|------|------|
| handoff | "+207 net LOC" | +207 |
| 局部推算 | "+235 + (70-88) + 10 = +227" (仅 reconciler + governed_router + execution_readiness) | +227 |
| §3.6 完整加总 | +235 (reconciler) + 5 (decision_validator) + 70/-88 (governed_router) + 10 (execution_readiness) + 20 (clarification) | **+252 net** |
| 排除 decision_validator wrapper (optional) | +235 + 70/-88 + 10 + 20 | **+247 net** |

**三种结果差异来源**:
- handoff +207: 来源不明，未在 §3.6 中逐段 trace。
- 局部 +227: 只加了 3 个文件的 reconciler(+235) + governed_router(-18) + execution_readiness(+10)，漏了 decision_validator(+5) 和 clarification(+20)。
- §3.6 完整加总 +247 ~ +252: 5 个文件合计。

**结论**:
1. handoff 数字 "+207 net LOC" 是未 verify 的估算，**不能直接引用为事实**。
2. §3.6 各段 LOC 数是设计阶段的 estimate，最终以 implementation diff 为准。
3. **早期 estimate (200-250 net LOC) 已 superseded**。§4 B validator 完整设计 (dataclass + helper + 2 filters + 集成 + trace, ~+110 LOC) 使 reconciler.py 总额调至 ~+320，全量 estimate 约为 **~+350 net LOC**，涵盖 5 个文件 (1 new + 4 modified)。
4. 最终数字必须以 Round 3 实施完成后的 `git diff --stat` 为准。所有本节 LOC 数字均为设计阶段 estimate。

#### Finding D: Wave 1 是否在改动面 — explicit ack

**是，Wave 1 `clarification_contract.py` 在改动面内**。理由见 Finding B 文件 #5。

不改动的内容 (红线):
- `_run_stage2_llm` (line 356) — Stage 2 LLM 调用逻辑不变
- `_extract_llm_intent_hint` (line 889-911) — chain 提取逻辑不变
- `_persist_tool_intent` (line 1024) — W3 写入不变 (归 E narrow §5)
- Stage 2 prompt 构建 (K4-K9) — 不变

只改 Q3 gate 段 (line 485-516): 在现有 `_decision_field_active` 分支中加 reconciler 调用 + metadata write。

**Wave 1 vs Wave 2 区别**:
| 项目 | Wave 1 (clarification_contract) | Wave 2 (execution_readiness) |
|------|------|------|
| P1 数据源 | 局部变量 `llm_payload` | `context.metadata["stage2_payload"]` |
| P2 数据源 | 局部变量 `missing_required`, `rejected_slots` | `context.metadata["stage3_yaml"]` (需新增 write) |
| P3 数据源 | 局部变量 `pending_slots`, `should_proceed` | `context.metadata["clarification"]` |
| 是否活跃 | `ENABLE_CONTRACT_SPLIT=false` + `ENABLE_LLM_DECISION_FIELD=true` | `ENABLE_CONTRACT_SPLIT=true` + `ENABLE_LLM_DECISION_FIELD=true` |
| 改动 LOC 估 | +20 | +5 (P2 write) + 集成点在 governed_router |

---

### §4.1 B validator 函数签名

#### 4.1.1 设计原则

B validator 是 **deterministic governance** 组件：
- 输入: tool_name + slot name list + contract registry
- 输出: grounded vs dropped slot partition
- 不调用 LLM
- 不修改 LLM prompt
- 不使用 confidence threshold (不违反 F1)
- 不注入领域规则到 prompt (不违反 F2)
- 不涉及 reply text generation (不冲突 F3)

#### 4.1.2 函数 1: `filter_stage2_missing_required()`

```python
# core/contracts/reconciler.py

def filter_stage2_missing_required(
    *,
    tool_name: str,
    missing_required: list[str],
    contract_registry: ToolContractRegistry,
    source: str = "stage2_raw.missing_required",
) -> ContractGroundingResult:
    """Filter Stage 2 raw missing_required against active tool contract.

    Only slots that appear in the tool's required_slots or
    clarification_followup_slots are retained as grounded.

    Args:
        tool_name: Active tool name (key in tool_contracts.yaml tools section).
        missing_required: LLM-claimed missing slots (from stage2_raw.missing_required).
        contract_registry: Loaded ToolContractRegistry for reading YAML contracts.
        source: Label for trace — identifies which producer this filter is applied to.

    Returns:
        ContractGroundingResult with grounded_slots = intersection of
        missing_required with allowed_slots, and dropped_slots = the rest.
    """
```

**输入字段**:
| 参数 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `tool_name` | `str` | P1 `stage2_raw.intent.resolved_tool` 或 P3 `clarification_telemetry.tool_name` | 必须非空；空字符串时 B validator 返回 unknown_tool_contract diagnostic |
| `missing_required` | `list[str]` | P1 `stage2_raw.missing_required` | LLM 声称的缺失 slot 列表。可能包含 hallucinated slots (task 105: vehicle_type, road_type 不在 macro 的 contract 中) |
| `contract_registry` | `ToolContractRegistry` | 来自 `tools/contract_loader.py` 的 `get_tool_contract_registry()` | 已实例化的 contract registry；不在此函数内实例化（DI 原则） |
| `source` | `str` | caller 指定 | trace payload 中的 source label，默认 `"stage2_raw.missing_required"` |

**输出**: `ContractGroundingResult` (dataclass, 定义见 §4.2)

**行为**:
- 如果 `tool_name` 为空字符串或不在 contract registry 中 → `grounded_slots = []`, 所有 `missing_required` 进入 `dropped_slots`, `dropped_reason = "unknown_tool_contract"`
- 如果 `tool_name` 合法 → 读取 contract → `allowed_slots = required_slots ∪ clarification_followup_slots` → `grounded_slots = missing_required ∩ allowed_slots` → `dropped_slots = missing_required \ allowed_slots`

#### 4.1.3 函数 2: `filter_clarify_candidates()`

```python
# core/contracts/reconciler.py

def filter_clarify_candidates(
    *,
    tool_name: str,
    clarify_candidates: list[str],
    contract_registry: ToolContractRegistry,
    source: str = "readiness_gate.clarify_candidates",
) -> ContractGroundingResult:
    """Filter readiness_gate clarify_candidates against active tool contract.

    This addresses the §3.A.2 finding: hallucinated slots enter clarify_candidates
    via execution_readiness_contract.py line 229-236 (stage2_needs_clarification
    path injects stage2_missing_required into clarify_candidates).

    Only candidates that appear in the tool's required_slots or
    clarification_followup_slots are retained. Candidates that are not in
    allowed_slots (e.g., non-contract hallucinated slots) are dropped.

    Args:
        tool_name: Active tool name.
        clarify_candidates: Readiness gate aggregated clarification candidates.
            Current structure is list[str] (execution_readiness_contract.py:238
            deduplicates with dict.fromkeys(str(item) for item in ...)).
        contract_registry: Loaded ToolContractRegistry.
        source: Label for trace.

    Returns:
        ContractGroundingResult.
    """
```

**审计 `clarify_candidates` 实际结构**:
- `execution_readiness_contract.py:206`: `clarify_candidates = list(missing_required) + list(rejected_slots)` — list[str] 起源
- Lines 215-236: 各路径 `.extend()` 全部追加 str 元素
- Line 238: `clarify_candidates = list(dict.fromkeys(str(item) for item in clarify_candidates if str(item).strip()))` — **最终类型 = `list[str]`**，已去重去空
- **结论**: 当前 clarify_candidates 在所有消费点 (line 256 onwards) 都是 `list[str]`。不需要处理 dict / object 结构。

**输入字段**:
| 参数 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `tool_name` | `str` | `clarification_telemetry.tool_name` 或 P1 `stage2_raw.intent.resolved_tool` | 同上 |
| `clarify_candidates` | `list[str]` | P3 `readiness_gate.clarify_candidates` (提取自 `context.metadata["clarification"]["telemetry"]` 或 ExecutionReadiness 局部变量) | 已去重的 slot 名称 list |
| `contract_registry` | `ToolContractRegistry` | 同上 | DI 原则，不内部实例化 |
| `source` | `str` | caller 指定 | 默认 `"readiness_gate.clarify_candidates"` |

**行为**: 与 `filter_stage2_missing_required` 共享底层 ground check，区别在于输入来源不同 (用于 trace)。

#### 4.1.4 共享底层: `_contract_allowed_slots()`

```python
# core/contracts/reconciler.py (internal helper)

def _contract_allowed_slots(
    tool_name: str,
    contract_registry: ToolContractRegistry,
) -> tuple[list[str], list[str], list[str]]:
    """Return (required_slots, followup_slots, allowed_slots) for tool_name.

    allowed_slots = required_slots ∪ clarification_followup_slots.

    Returns empty lists if tool_name is unknown (caller handles diagnostic).
    """
```

**关键**: `allowed_slots` 只包含 `required_slots ∪ clarification_followup_slots`，**不包含** `optional_slots` 全量。理由：
- `optional_slots` 如 `query_emission_factors.season` 有 default "夏季"，不应被问询
- `optional_slots` 如 `calculate_macro_emission.scenario_label` 是可选标签，不是参数收集目标
- 把全部 optional_slots 纳入 allowed_set 会让 B validator 失去过滤能力 — LLM 说任何 optional slot 都算 grounded
- `confirm_first_slots` 也不纳入 allowed_set — confirm_first 是 governance 层面的确认策略，不是 contract-grounded slot 定义

**具体 contract 对照**:

| tool | required_slots | clarification_followup_slots | allowed_slots (B validator) |
|------|---------------|------------------------------|---------------------------|
| `query_emission_factors` | `["vehicle_type", "pollutants"]` | `["model_year"]` | `["vehicle_type", "pollutants", "model_year"]` |
| `calculate_micro_emission` | `["vehicle_type", "pollutants"]` | `[]` | `["vehicle_type", "pollutants"]` |
| `calculate_macro_emission` | `["pollutants"]` | `[]` | `["pollutants"]` |
| `calculate_dispersion` | `[]` | `[]` | `[]` |
| `analyze_hotspots` | `[]` | `[]` | `[]` |

---

### §4.2 B validator dataclass

#### 4.2.1 `ContractGroundingResult` (输出)

```python
@dataclass
class ContractGroundingResult:
    """B validator output: grounded vs dropped slot partition for a single filter call."""

    # ── 调用标识 ──
    tool_name: str
    """Active tool name at time of filter call. Empty string if unknown."""

    source: str
    """Which producer this filter was applied to.
    Values: "stage2_raw.missing_required" | "readiness_gate.clarify_candidates"
    """

    # ── contract 信息 ──
    required_slots: list[str]
    """From YAML contract. Empty if unknown tool."""

    clarification_followup_slots: list[str]
    """From YAML contract. Empty if not declared."""

    allowed_slots: list[str]
    """= required_slots ∪ clarification_followup_slots. The contract-grounded set."""

    # ── 输入 ──
    original_slots: list[str]
    """Input candidate slots, before filtering. Preserves original order."""

    # ── 输出 ──
    grounded_slots: list[str]
    """Slots that pass contract-grounding: original_slots ∩ allowed_slots."""

    dropped_slots: list[str]
    """Slots that fail contract-grounding: original_slots \ allowed_slots."""

    dropped_reasons: dict[str, str]
    """Per-slot reason for each dropped slot.
    Key = slot name, Value = reason code (see below).
    """

    # ── 完整度信号 ──
    is_contract_found: bool
    """False if tool_name was unknown or contract registry returned no spec."""

    had_hallucinated_slots: bool
    """True if any input slot was dropped (convenience flag for reconciler)."""

    # ── trace payload ──
    trace_payload: dict
    """Self-contained trace record for telemetry/debug.
    Keys: source, tool_name, original, grounded, dropped, dropped_reasons,
          allowed, required, followup, is_contract_found, timestamp.
    """
```

**`dropped_reasons` 枚举值**:

| 值 | 含义 | 触发条件 |
|----|------|---------|
| `"not_in_required_or_followup_slots"` | Slot 不在 contract 的 required_slots 或 clarification_followup_slots 中 | `slot not in allowed_slots` (最常用) |
| `"unknown_tool_contract"` | tool_name 无法在 tool_contracts.yaml 中找到对应 contract | `tool_name` 不在 contract_registry 中 |
| `"malformed_candidate"` | Candidate slot 名称无效 (空字符串, 纯空格等) | `str(slot).strip() == ""` |
| `"empty_contract_allowed_set"` | Contract 存在但 required_slots 和 clarification_followup_slots 都为空 — 该工具无可问询的 slot | `allowed_slots == []` 且 `is_contract_found == True` |

**`unknown_tool_contract` 策略**: 硬 diagnostic — 不要静默通过。
- B validator 返回 `grounded_slots = []`, `dropped_slots = original_slots`, `is_contract_found = False`
- A reconciler 收到 `is_contract_found=False` → **不应 produce proceed**，应走 fallback 或 escalate
- 具体是否 block 留给 A orchestrator 决定 (§4.7 Case 4)。B validator 只标诊断，不直接 block。

#### 4.2.2 工厂函数 `ContractGroundingResult.empty()`

```python
@staticmethod
def _empty_result(
    tool_name: str,
    source: str,
    original_slots: list[str],
) -> ContractGroundingResult:
    """Factory for unknown/missing contract — all slots dropped."""
    return ContractGroundingResult(
        tool_name=tool_name,
        source=source,
        required_slots=[],
        clarification_followup_slots=[],
        allowed_slots=[],
        original_slots=list(original_slots),
        grounded_slots=[],
        dropped_slots=list(original_slots),
        dropped_reasons={s: "unknown_tool_contract" for s in original_slots},
        is_contract_found=False,
        had_hallucinated_slots=bool(original_slots),
        trace_payload={...},
    )
```

#### 4.2.3 dataclass 关系图

```
filter_stage2_missing_required(...)  ──→  ContractGroundingResult  (for P1 input)
filter_clarify_candidates(...)       ──→  ContractGroundingResult  (for P3 input)
                                                │
                                     A reconciler reads:
                                     - b_p1.grounded_slots → reconciled_missing_required
                                     - b_p1.dropped_slots → source_trace evidence
                                     - b_p3.grounded_slots → filtered clarify_candidates
                                     - b_p3.dropped_slots → source_trace evidence
                                                │
                                                ▼
                                     ReconciledDecision.source_trace["b_validator"]
```

---

### §4.3 Contract-grounding check 算法

#### 4.3.1 主算法

```
Algorithm: contract_grounding_filter

Input: tool_name (str), candidate_slots (list[str]),
       contract_registry (ToolContractRegistry), source (str)

Output: ContractGroundingResult

Step 1 — Load contract:
    tool_spec = contract_registry.get(tool_name)
    if tool_spec is None:
        return _empty_result(tool_name, source, candidate_slots)

Step 2 — Extract allowed set:
    required_slots = list(tool_spec.get("required_slots") or [])
    followup_slots = list(tool_spec.get("clarification_followup_slots") or [])
    allowed_slots = list(dict.fromkeys(required_slots + followup_slots))
    # dict.fromkeys preserves first-occurrence order, deduplicates

Step 3 — Normalize input:
    normalized = []
    seen = set()
    for raw in candidate_slots:
        s = str(raw).strip()
        if s and s not in seen:
            normalized.append(s)
            seen.add(s)
    # Filters empty/whitespace, deduplicates, preserves original order

Step 4 — Partition:
    grounded_slots = [s for s in normalized if s in allowed_slots]
    dropped_slots  = [s for s in normalized if s not in allowed_slots]

Step 5 — Build reasons:
    dropped_reasons = {}
    for s in dropped_slots:
        if not allowed_slots:
            dropped_reasons[s] = "empty_contract_allowed_set"
        else:
            dropped_reasons[s] = "not_in_required_or_followup_slots"

Step 6 — Build trace_payload:
    trace_payload = {
        "source": source,
        "tool_name": tool_name,
        "original": list(normalized),
        "grounded": list(grounded_slots),
        "dropped": list(dropped_slots),
        "dropped_reasons": dict(dropped_reasons),
        "allowed": list(allowed_slots),
        "required": list(required_slots),
        "followup": list(followup_slots),
        "is_contract_found": True,
        "had_hallucinated_slots": bool(dropped_slots),
    }

Step 7 — Return ContractGroundingResult:
    return ContractGroundingResult(
        tool_name=tool_name,
        source=source,
        required_slots=list(required_slots),
        clarification_followup_slots=list(followup_slots),
        allowed_slots=list(allowed_slots),
        original_slots=list(normalized),
        grounded_slots=list(grounded_slots),
        dropped_slots=list(dropped_slots),
        dropped_reasons=dropped_reasons,
        is_contract_found=True,
        had_hallucinated_slots=bool(dropped_slots),
        trace_payload=trace_payload,
    )
```

#### 4.3.2 复杂度

- 所有操作 O(n) where n = len(candidate_slots)
- `allowed_slots` lookup 用 `set` 内部，O(1) per slot
- candidate_slots 规模很小 (典型 0-5 slots, 极端 10-15) — 性能完全不是瓶颈
- No LLM call, no I/O beyond contract_registry (memory lookup)

#### 4.3.3 Trace 建议

- **step_type 建议**: `"contract_grounding_filter"` 或 `"b_validator_filter"`
- **trace payload**: 直接嵌入 `ContractGroundingResult.trace_payload`
- **不写用户可见中文硬编码文本** — B validator 是 governance 内部组件，输出面向 trace 和 debug，不是面向用户
- **trace step 写入点**: 在 A reconciler 的 `source_trace` 中记录两个 B validator 结果：
  ```
  source_trace: {
    ...
    "b_validator": {
      "stage2_raw_filter": {...},   # ContractGroundingResult.trace_payload
      "clarify_candidates_filter": {...},  # ContractGroundingResult.trace_payload
    }
  }
  ```

#### 4.3.4 设计约束

- **B validator 是 deterministic governance** — 相同输入永远产生相同输出
- **B 不改变 LLM 的语义理解** — B 只过滤非 contract slot 进入后续 decision reconciliation，不重新解释 LLM 的语义
- **B 不使用 confidence threshold** — 不违反 F1 (F1 是 `validate_decision` 的职责，B 是 contract grounding，两者正交)
- **B 不把领域规则注入 LLM prompt** — 不违反 F2 (B 是 post-hoc filter，不是 pre-LLM injection)
- **B 与 F3 不冲突** — B 约束的是 clarification slot 名称 (domain term)，不是 reply enum 值 (conversational pragmatics)

---

### §4.4 B validator 与 reconciler.py 的集成

#### 4.4.1 集成架构图

```
contract loop (governed_router.py:114-130)
  │
  ├─ IntentResolutionContract.before_turn()
  │   → writes P1: context.metadata["stage2_payload"]
  │
  ├─ StanceResolutionContract.before_turn()
  │
  ├─ ExecutionReadinessContract.before_turn()
  │   → writes P2: context.metadata["stage3_yaml"]  (NEW, §3.6.4 E1/E2)
  │   → writes P3: context.metadata["clarification"]
  │
  ▼
contract loop ends, result is None
  │
  ▼
governed_router.py:133-137 (MODIFIED, §3.4.2 After)
  │
  ├─ F1 validate_decision(stage2_payload)
  │   ↓ pass
  │
  ├─ build p1 = Stage2RawSource from context.metadata["stage2_payload"]
  ├─ build p2 = Stage3YamlSource from context.metadata["stage3_yaml"]
  │
  ├─ ★ Filter Point 1: B validator on p1.missing_required
  │   b1 = filter_stage2_missing_required(
  │       tool_name=p1_raw.intent.resolved_tool,
  │       missing_required=p1.missing_required,
  │       contract_registry=registry,
  │       source="stage2_raw.missing_required",
  │   )
  │   → p1.missing_required = b1.grounded_slots  (overwrite for reconciler)
  │   → b1.dropped_slots recorded in source_trace
  │
  ├─ build p3 = ReadinessGateState from context.metadata["clarification"]
  │
  ├─ ★ Filter Point 2: B validator on p3.clarify_candidates
  │   b3 = filter_clarify_candidates(
  │       tool_name=p3_raw.tool_name,
  │       clarify_candidates=p3.clarify_candidates,
  │       contract_registry=registry,
  │       source="readiness_gate.clarify_candidates",
  │   )
  │   → p3.clarify_candidates = b3.grounded_slots  (overwrite for reconciler)
  │   → Rebuild p3.clarify_required_candidates from b3.grounded ∩ required_slots
  │   → b3.dropped_slots recorded in source_trace
  │
  ├─ reconcile(p1, p2, p3, ctx)
  │   → ReconciledDecision
  │   → source_trace["b_validator"] = {b1.trace, b3.trace}
  │
  ▼
_consume_reconciled_decision(reconciled)
```

#### 4.4.2 Filter Point 1 细节: stage2_raw.missing_required

**位置**: `governed_router.py` chat() 方法中, `build_stage2_raw_from_metadata` 之后, `reconcile()` 之前。

**输入**:
- `tool_name`: 从 `stage2_payload.intent.resolved_tool` 或 `clarification_telemetry.tool_name` 提取
- `missing_required`: 从 `Stage2RawSource.missing_required` (已由 helper 从 P1 提取为 list[str])
- `contract_registry`: `get_tool_contract_registry()` (已在 `clarification_contract.py:26` 导入, `reconciler.py` 同样导入)

**输出**:
- `b1.grounded_slots`: 取代 `p1.missing_required` 进入 reconciler
- `b1.dropped_slots`: 进入 `source_trace["b_validator"]["stage2_raw_filter"]["dropped"]`

**效果**:
- Task 105 turn 2: P1 `missing_required = ["vehicle_type", "road_type"]` → B filter → `grounded_slots = []` (macro required_slots = ["pollutants"], 无 followup) → R2 命中 → proceed

#### 4.4.3 Filter Point 2 细节: readiness_gate.clarify_candidates

**位置**: `governed_router.py` chat() 方法中, `build_readiness_gate_from_metadata` 之后, `reconcile()` 之前。

**输入**:
- `tool_name`: 从 P3 metadata 的 `clarification_telemetry.tool_name` 提取
- `clarify_candidates`: 从 `ReadinessGateState.clarify_candidates` (list[str])
- `contract_registry`: 同上

**输出**:
- `b3.grounded_slots`: 取代 `p3.clarify_candidates` (读 readiness 的原始 clarify list, 去 hallucinated)
- `b3.dropped_slots`: 进入 `source_trace["b_validator"]["clarify_candidates_filter"]["dropped"]`

**重建 `clarify_required_candidates`**: B filter 后, `p3.clarify_candidates` 只含 grounded slots。Recocniler 或 filter wrapper 重建 `p3.clarify_required_candidates`:
```python
b3_required = [s for s in b3.grounded_slots if s in (required_slots or [])]
b3_optional = [s for s in b3.grounded_slots if s not in (required_slots or [])]
```

**效果**:
- Task 105 turn 2: clarify_candidates 原始含 `["vehicle_type", "road_type"]` (通过 line 229-236 stage2_needs_clarification 路径注入) → B filter → `grounded_slots = []` → `clarify_required_candidates = []`, `clarify_optional_candidates = []` → readiness disposition 从 D2 Q3 defer 等效变为 "nothing to clarify" → reconciler R2 命中 → proceed

#### 4.4.4 B validator 不修改 execution_readiness_contract.py 内部

**设计决策**: B-filter point 2 放在 reconciler 层 (governed_router 调用点), 而不是放在 `execution_readiness_contract.py` 内部。

理由:
1. **不改动 ExecutionReadinessContract 内部逻辑** — clarify_candidates aggregation (line 204-254) 保持原样，P3 仍输出原始 clarify_candidates。B validator 是 reconcile 前的 consumer-side filter。
2. **不改动 Wave 1/2 分发逻辑** — 两个 Wave 的 contract 各自产出自己的 clarify_candidates, reconciler 统一 B-filter。
3. **不修改 `_missing_named_slots` / `_build_question` / `_persist_split_pending`** — 这些是 P3 内部实施的细节，B validator 是 P3 输出之后的消费者。
4. **如果将来要改 P3 clarify_candidates aggregation 九源优先级** (Phase 6 Class D scope), B validator 不受影响 — 它是 aggregation 之后的 filter。

**备选方案 (不在 Round 2 选用)**: 在 `execution_readiness_contract.py:229-236` 的 `stage2_needs_clarification` 分支中直接 filter `stage2_meta.get("stage2_missing_required")`，阻止 hallucinated slots 进入 clarify_candidates。这是从源头上预防 — 更干净，但改动 P3 内部逻辑，超出 reconciliation "补全设计" 范围。记录为 Phase 6 可选优化。

#### 4.4.5 B validator 的两个结果进入 ReconciledDecision

```python
# 在 reconciler 主函数 reconcile() 中:
source_trace["b_validator"] = {
    "stage2_raw_filter": {
        "source": b1.source,
        "original": b1.original_slots,
        "grounded": b1.grounded_slots,
        "dropped": b1.dropped_slots,
        "dropped_reasons": b1.dropped_reasons,
        "is_contract_found": b1.is_contract_found,
    },
    "clarify_candidates_filter": {
        "source": b3.source,
        "original": b3.original_slots,
        "grounded": b3.grounded_slots,
        "dropped": b3.dropped_slots,
        "dropped_reasons": b3.dropped_reasons,
        "is_contract_found": b3.is_contract_found,
    },
}
```

---

### §4.5 Task 105 turn 2 演示

#### 4.5.1 输入事实

**Active tool**: `calculate_macro_emission`

**YAML contract** (`config/tool_contracts.yaml:202-213`, grep 实证):
```yaml
calculate_macro_emission:
    required_slots:
      - pollutants
    optional_slots:
      - season
      - scenario_label
    defaults:
      season: "夏季"
    clarification_followup_slots: []
```

**allowed_slots**: `["pollutants"]` (required_slots ∪ clarification_followup_slots = ["pollutants"] ∪ [])

**Stage 2 raw** (from Round 1.5 audit §2.1, per-trace):
```
missing_required: ["vehicle_type", "road_type"]
decision.value: "clarify"
decision.confidence: 0.85 (est.)
```

**Stage 3 YAML** (post-standardization):
```
yaml_missing_required: []    (pollutants 已由用户提供的，或默认)
rejected_slots: []
optional_no_default: []       (season has default "夏季")
optional_resolved_by_default: ["season"]
active_required_slots: ["pollutants"]
```

**P3 readiness_gate**:
```
clarify_candidates: ["vehicle_type", "road_type"]  (hallucinated, via line 229-236)
clarify_required_candidates: ["vehicle_type", "road_type"]
clarify_optional_candidates: []
disposition: D2 ("q3_defer")   (_split_decision_field_active=True)
```

#### 4.5.2 B-filter 执行

**Filter Point 1** — `filter_stage2_missing_required()`:
```
Input:  tool_name="calculate_macro_emission"
        missing_required=["vehicle_type", "road_type"]

Step 2: required_slots=["pollutants"], followup_slots=[], allowed_slots=["pollutants"]
Step 4: grounded_slots = ["vehicle_type", "road_type"] ∩ ["pollutants"] = []
         dropped_slots  = ["vehicle_type", "road_type"] \ ["pollutants"] = ["vehicle_type", "road_type"]
Step 5: dropped_reasons = {
            "vehicle_type": "not_in_required_or_followup_slots",
            "road_type": "not_in_required_or_followup_slots",
        }

Output: ContractGroundingResult(
    grounded_slots=[],
    dropped_slots=["vehicle_type", "road_type"],
    had_hallucinated_slots=True,
    is_contract_found=True,
)
```

**Filter Point 2** — `filter_clarify_candidates()`:
```
Input:  tool_name="calculate_macro_emission"
        clarify_candidates=["vehicle_type", "road_type"]

Same allowed_slots=["pollutants"]
→ grounded_slots=[]
→ dropped_slots=["vehicle_type", "road_type"]

Output: ContractGroundingResult(
    grounded_slots=[],
    dropped_slots=["vehicle_type", "road_type"],
    had_hallucinated_slots=True,
)
```

#### 4.5.3 Post-B-filter state

```
p1.missing_required (post B-filter): []   ← was ["vehicle_type", "road_type"]
p3.clarify_candidates (post B-filter): [] ← was ["vehicle_type", "road_type"]
p3.clarify_required_candidates (post B-filter): []
p3.clarify_optional_candidates (post B-filter): []

Effective readiness disposition: nothing to clarify
  (clarify_required=[] AND clarify_optional=[])
```

#### 4.5.4 Reconciler evaluation

```
R4 check: F1 valid (confidence >= 0.5, decision=clarify, question non-empty) → pass
R3 check: stage2_raw.decision=clarify BUT effective readiness is "no blockers"
         → NOT all agree → skip R3
R1 check: stage2_raw.decision_value == "proceed" → FALSE (LLM said clarify) → skip R1
R2 check:
  1. stage2_raw.decision_value == "clarify" ✓
  2. B_filter(stage2_raw.missing_required) == [] ✓ (vehicle_type/road_type dropped)
  3. stage3_yaml.yaml_missing_required == [] ✓ (pollutants filled, season has default)
  → R2 MATCHED

applied_rule_id: "R2_hallucination_filtered"
```

#### 4.5.5 ReconciledDecision output

```python
ReconciledDecision(
    decision_value="proceed",
    reconciled_missing_required=[],
    clarification_question=None,
    deliberative_reasoning="",
    reasoning=(
        "LLM=clarify with [vehicle_type, road_type] but contract(calculate_macro_emission) "
        "requires only [pollutants]; YAML=all required filled, season resolved by default; "
        "B validator dropped hallucinated slots [vehicle_type, road_type] "
        "→ reconciled to proceed per R2."
    ),
    source_trace={
        "stage2_raw": {"decision": "clarify", "missing_required": ["vehicle_type", "road_type"], ...},
        "stage3_yaml": {"missing_required": [], "active_required_slots": ["pollutants"], ...},
        "readiness_gate": {"disposition": "q3_defer", "original_clarify_candidates": ["vehicle_type", "road_type"], ...},
        "b_validator": {
            "stage2_raw_filter": {"original": ["vehicle_type", "road_type"], "grounded": [], "dropped": ["vehicle_type", "road_type"], ...},
            "clarify_candidates_filter": {"original": ["vehicle_type", "road_type"], "grounded": [], "dropped": ["vehicle_type", "road_type"], ...},
        },
    },
    applied_rule_id="R2_hallucination_filtered",
)
```

#### 4.5.6 Effect

- `_consume_reconciled_decision` sees `decision_value="proceed"`
- Cross-constraint preflight (pollutants OK) → passes → returns None
- Falls through to `_maybe_execute_from_snapshot` → executes `calculate_macro_emission(pollutants=[...], season="夏季")`
- User gets macro emission result instead of irrelevant "请输入 vehicle_type 和 road_type" clarification

**Before vs After**:

| | Turn 2 result | Actual tool calls | Semantic correctness |
|---|---|---|---|
| 修复前 (Round 1.4) | clarify with hallucinated "vehicle_type, road_type" → user confused → 3 redundant macro calls | 3 × calculate_macro_emission (same params) | Wrong — LLM hallucination reaches user |
| 修复后 (B validator + R2) | proceed → execute macro with correct params | 1 × calculate_macro_emission | Correct — hallucination filtered, contract-grounded execution |

---

### §4.6 改动面: file:line 级别 + LOC 估

**注意**: 本节给出的是 **设计阶段 LOC 区间估计**，不是 implementation fact。最终以 `git diff --stat` 为准。

#### 4.6.1 `core/contracts/reconciler.py` (新文件)

| # | 内容 | 涉及 § | 估 LOC | 
|---|------|-------|--------|
| B1 | `ContractGroundingResult` dataclass (7 fields + dropped_reasons + trace_payload + `_empty_result` factory) | §4.2 | +35 |
| B2 | `_contract_allowed_slots()` internal helper | §4.1.4 | +15 |
| B3 | `filter_stage2_missing_required()` — Filter Point 1 | §4.1.2 | +20 |
| B4 | `filter_clarify_candidates()` — Filter Point 2 | §4.1.3 | +20 |
| B5 | 集成 B validator 进入 `reconcile()` 主函数 | §4.4 | +10 |
| B6 | trace_payload 构建 | §4.3.3 | +10 |
| **subtotal** | | | **~+110** |

**注意**: §3.6.1 R5 原预算 +25 LOC 是针对 B validator 的初始占位 (当时只设想了 2 个简单函数)。当前完整设计 (dataclass + helper + 2 filters + 集成 + trace) 扩展为 ~+110 LOC。reconciler.py 总 LOC 从 +235 调至 **~+320**。

#### 4.6.2 `core/contracts/decision_validator.py`

| # | 现有行 | 改动 | § | 估 LOC |
|---|--------|------|---|--------|
| D1 | `decision_validator.py:10-54` | 不改动 — F1 核心函数签名不变。可选: 新增 `validate_decision_from_source(s: Stage2RawSource)` wrapper (直接构造 dict 调 `validate_decision`) | §3.6.2 | +5 (optional) |

**说明**: B validator 不在 `decision_validator.py` 中 — 职责不同:
- `decision_validator.py`: F1 safety net (schema / confidence / consistency within single decision payload)
- `reconciler.py` B validator: contract-grounding filter (slot ∈ YAML contract allowed set)

两者正交。不放一起。

#### 4.6.3 `core/governed_router.py`

| # | 现有行 | 改动 | § | 估 LOC |
|---|--------|------|---|--------|
| G1 | `governed_router.py:133-137` | 替换为 F1 → B-filter (2 次) → reconcile → _consume_reconciled_decision 流程 | §3.4.2, §4.4 | +40/-8 |
| G2 | `governed_router.py:557-674` | `_consume_decision_field` → `_consume_reconciled_decision` (保留 cross-constraint preflight) | §3.4.2 | +40/-80 |
| G3 | `governed_router.py:25` (imports) | 新增 `from core.contracts.reconciler import ...` | — | +2 |
| **subtotal** | | | | **+82/-88 ≈ -6 net** |

#### 4.6.4 `core/contracts/execution_readiness_contract.py`

| # | 现有行 | 改动 | § | 估 LOC |
|---|--------|------|---|--------|
| E1 | `execution_readiness_contract.py:630` (before return) | 写入 P2: `context.metadata["stage3_yaml"] = {...}` | §3.6.4 | +5 |

**不改动**: clarify_candidates aggregation (line 204-254), stage2_needs_clarification path (line 229-236), `_build_question` / `_persist_split_pending`。

**说明**: E1 是 P2 数据暴露点 — 当前 `missing_required`, `rejected_slots`, `optional_classification`, `active_required_slots` 是 ExecutionReadiness 局部变量。E1 是 1 个 dict assignment 写入 `context.metadata`, 供 governed_router 中的 reconciler 入口读取。

#### 4.6.5 `core/contracts/clarification_contract.py` (Wave 1 同步)

| # | 现有行 | 改动 | § | 估 LOC |
|---|--------|------|---|--------|
| C1 | `clarification_contract.py:485-516` (Q3 gate, `if not should_proceed: if self._decision_field_active(telemetry):`) | 构建 reconciler 输入 (Wave 1 helper: `build_stage2_raw_from_llm_payload`) + 调用 `reconcile()` + 写入 `context.metadata["reconciled_decision"]` | §3.6.6 | +25 |
| C2 | `clarification_contract.py:26` (imports) | 新增 `from core.contracts.reconciler import ...` | — | +1 |
| **subtotal** | | | | **~+26** |

**Wave 1 call site 伪代码**:
```python
# In clarification_contract.py, Q3 gate section (~line 485-516):
if not should_proceed:
    if self._decision_field_active(telemetry):
        from core.contracts.reconciler import (
            reconcile, build_stage2_raw_from_llm_payload,
            build_readiness_gate_from_metadata, ReconciliationContext,
            filter_stage2_missing_required, filter_clarify_candidates,
        )
        registry = get_tool_contract_registry()
        p1 = build_stage2_raw_from_llm_payload(llm_payload)
        
        # B Filter Point 1
        b1 = filter_stage2_missing_required(
            tool_name=tool_name,
            missing_required=list(p1.missing_required),
            contract_registry=registry,
        )
        p1.missing_required = b1.grounded_slots
        
        p2 = Stage3YamlSource(
            yaml_missing_required=list(missing_required),
            rejected_slots=list(rejected_slots),
            optional_no_default=list(unfilled_optionals_without_default),
            optional_resolved_by_default=[],
            active_required_slots=list(active_required_slots),
        )
        p3 = build_readiness_gate_from_metadata({
            "disposition": "q3_defer",
            "clarify_candidates": list(pending_slots),
            ...
        })
        
        # B Filter Point 2
        b3 = filter_clarify_candidates(
            tool_name=tool_name,
            clarify_candidates=list(p3.clarify_candidates),
            contract_registry=registry,
        )
        p3.clarify_candidates = b3.grounded_slots
        
        reconciled = reconcile(p1, p2, p3, ReconciliationContext(
            turn_index=self._current_turn_index(), wave="wave1",
            tool_name=tool_name,
        ))
        context.metadata["reconciled_decision"] = reconciled.to_dict()
        telemetry.final_decision = "deferred_to_decision_field"
        return ContractInterception(metadata={...})  # existing return
```

**注意**: Wave 1 和 Wave 2 在 `governed_router.py` 中汇合 — `_consume_decision_field` / `_consume_reconciled_decision` 检查 `context.metadata["reconciled_decision"]` 优先于 raw `stage2_payload`。如果 Wave 1 写了 `reconciled_decision` (flag=true with contract_split=false), GovernedRouter 统一消费。

#### 4.6.6 `config/tool_contracts.yaml` (只读)

| 改动 | § | 估 LOC |
|------|---|--------|
| **不改动** — B validator 只读取 contract 用于 slot grounding | — | 0 |

**备查**: 如果 audit 发现某些 tool 的 `clarification_followup_slots` 缺失或需要声明，此为 **独立 design debt**，out of Round 3 unless direct Task 105/110/120 evidence proves it is required。

#### 4.6.7 LOC 汇总

| 文件 | 估 LOC | 性质 |
|------|--------|------|
| `core/contracts/reconciler.py` | ~+320 | 新文件 (含 B validator +110, A reconciler +210) |
| `core/contracts/decision_validator.py` | +5 (optional) | 不改 F1 核心 |
| `core/governed_router.py` | +82/-88 ≈ -6 net | 修改 |
| `core/contracts/execution_readiness_contract.py` | +5 | 修改 (P2 暴露) |
| `core/contracts/clarification_contract.py` | +26 | 修改 (Wave 1 同步) |
| `config/tool_contracts.yaml` | 0 | 只读 |
| **Total** | **~+438/-88 ≈ +350 net** | |

**注**: reconciler.py 原 +235 → 现约 +320 (B validator 预算从 +25 调至 +110, 更准确反映 dataclass + helper + 2 filters + 集成 + trace 的完整设计)。最终以 `git diff --stat` 在 Round 3 实施阶段为准。

---

### §4.7 边界 case

#### Case 1: B-filter 后 missing_required 变空 + 无 hard-block

**条件**:
- B-filter 后 `grounded_missing_required = []`
- `stage3_yaml.yaml_missing_required = []` — 无 truly missing required slots
- `readiness_gate` 无 hard-block (D1)，或 disposition 为 D2/D3

**处理**: A reconciler 可 proceed。
- R2 命中 (LLM clarify with hallucinated → filtered all → proceed)
- R1 命中 (LLM already proceed, confirmed by YAML + filtered readiness)

**风险**: 无。Governance 的三种 authoritative source (YAML contract required complete + readiness not hard-blocking + LLM's own missing_required was hallucinated) 全部 agree execution is safe。

#### Case 2: B-filter 后 missing_required 变空 + readiness 仍有真实 hard-block

**条件**:
- B-filter 后 `grounded_missing_required = []` — LLM 的说法已过滤
- 但 `readiness_gate` 仍有真实 hard-block (D1 或 D2 with non-empty clarify_required_candidates caused by non-LLM reasons):
  - 缺文件 (`file_path`)
  - 缺上游 result (dependency `requires: [emission]` 未满足)
  - 缺数据 (trajectory_data / links_data)

**处理**: A 不能 proceed。
- Readiness 的 disposition 来自非 LLM 原因 — 例如 `missing_required` (YAML required) 和 `rejected_slots` (legal-value check fail) 仍非空
- B 只过滤 LLM hallucinated slots，不绕过真实 dependency/readiness hard-block
- Reconciler 的 P3 input 保留了 complete `ReadinessGateState`, 包括 D1/D2 的完整 disposition。B validator 只修改了 `p3.clarify_candidates` (去 hallucinated)，不修改 `p3.disposition`
- 如果 B-filter 后 `p3.clarify_candidates` 为空但 `p3.disposition == D1`, reconciler 需要检查 P3 的 original reason → R3 或 fallback

**实施**: Reconciler 在检查 R1/R2 前，先检查 readiness_gate.disposition:
```python
if readiness_gate.disposition == "hard_block":
    # P3 hard-block is for non-LLM reasons (missing file, dependency, etc.)
    # B validator filtered hallucinated slots but real blockers remain
    # → respect the hard block, don't apply R1/R2
    return _build_fallback_decision(readiness_gate)
```

#### Case 3: B-filter 后 grounded_missing_required 非空

**条件**:
- B-filter 后 `grounded_missing_required` 含 contract-legal slots
- 例如: task 110 turn 1: `missing_required = ["vehicle_type", "pollutants"]` → B filter → `["vehicle_type", "pollutants"]` (both in contract)

**处理**: A 保持 clarify。
- R3 (consistency) 通常命中 — LLM clarify + YAML confirm missing + readiness clarify
- `clarification_question` 应只围绕 grounded slots

**子 case 3a: LLM 的 question 只问了 dropped slots**:
- 如果 LLM 的 `clarification_question` 只针对 hallucinated slots (如 "请输入 vehicle_type 和 road_type" 而 macro 只需要 pollutants)
- B filter 后 grounded_missing_required = [] (R2 命中 → proceed, question 不需要)
- 如果 grounded_missing_required 非空但 question 只覆盖 dropped slots → A reconciler 标记 `clarification_question_invalid = True`
- **策略** (design decision, 不在此轮实现):
  - Option a: regenerate question from `_build_question()` (governance-authored)
  - Option b: P3 structured reason / hardcoded_reason may be used only as **internal fallback seed** for downstream regeneration; final user-facing clarification text must be regenerated via LLM/reply pipeline or marked for safe fallback, not direct governance-authored text
  - Option c: 返回 clarify 但不带 question text，让 downstream 生成
  - **§4.7-1 决策已关闭**: 采用 option b — P3 structured reason / hardcoded_reason 仅作为 internal fallback seed。Final user-facing clarification must be regenerated through LLM/reply pipeline or safe fallback。Do not directly expose governance hardcoded Chinese text。

#### Case 4: Unknown tool contract

**条件**:
- `tool_name` 不在 `tool_contracts.yaml` 中，或 contract_registry 返回 None

**处理**: unknown_tool_contract 是 B validator 的 **hard diagnostic**，不是 B hard gate。
- B 只输出 evidence: `is_contract_found=False`, `grounded_slots=[]`, `dropped_slots=original_slots`, `dropped_reasons` 全部标记为 `"unknown_tool_contract"`。B 不直接阻断执行 — B 是 filter，不是 gate。
- **A reconciler / router 决定 safe fallback**:
  - A 收到 `is_contract_found=False` → 标记 diagnostic + 记录 trace event `"b_validator_unknown_contract"` with tool_name
  - A 不 produce proceed (无法确认 YAML contract grounded) — **risky proceed is forbidden**
  - A 走 safe fallback: defer to hard-rule path (不经过 LLM-deferential decision field routing)，让现有 contract-independent logic 处理
  - 可能 contract 是 legitimate new tool 或 config issue — trace record 供 debug 定位
- **§4.7-2 决策已关闭**: `unknown_tool_contract` 是 B hard diagnostic, not B hard gate。B outputs `is_contract_found=False` + evidence。A/router chooses safe fallback / hard-rule path。Risky proceed is forbidden。

#### Case 5: clarification_followup_slots 与 required_slots 双表示不一致

**条件**:
- 某个 slot 出现在 `clarification_followup_slots` 中但不在 `required_slots` 中，也不在 `optional_slots` 中
- 例如 (假设): `query_emission_factors.clarification_followup_slots = ["model_year"]`, `model_year` 同时也是 `optional_slots` — 这是当前 YAML 实际情况。这是合法设计 (optional slot 被指定为可跟进的 slot)
- 不一致的 case: 将来的 tool contract 中 `clarification_followup_slots` 包含一个不在 required 也不在 optional 中的 slot → B validator 仍会把它纳入 `allowed_slots` (因为只检查 `required_slots ∪ clarification_followup_slots`)

**处理**:
- B 只尊重 contract 明示的 `clarification_followup_slots`，不把所有 `optional_slots` 当成可问 slot
- 如果 `clarification_followup_slots` 中某个 slot 不在 `required_slots ∪ optional_slots` 中 (即 contract 的 parameters list 中不存在), 这是 **contract 设计错误** — B validator 不能检测 (它不验证 `clarification_followup_slots` 的 cross-reference)
- **标记为 implementation audit item** (不在此轮修复): Round 3 实施时可加 contract schema validation: `clarification_followup_slots ⊆ (required_slots ∪ optional_slots)` 作为 contract load-time invariant check

#### Case 6: 空 contract (no required_slots, no followup_slots)

**条件**:
- 例如: `calculate_dispersion` (`required_slots: []`, `clarification_followup_slots: []`, `allowed_slots = []`)
- `analyze_hotspots` (`required_slots: []`, `clarification_followup_slots: []`, `allowed_slots = []`)

**处理**:
- B validator 返回 `allowed_slots=[]`, `grounded_slots=[]`, 所有输入 slots 进 `dropped_slots` with reason `"empty_contract_allowed_set"`
- A reconciler: LLM 不应该对这些工具说 clarify (没有可问询的 slot)。如果 LLM 说了 clarify with missing_required → dropped → R2 命中 → proceed
- **这是正确行为**: 无 required slot 的工具不应对用户做 parameter collection。Stage 2 LLM 已被告知 tool 的 required_slots (K4)，不应 hallucinate

---

#### 【本节已关闭决策项汇总】

| # | 位置 | 问题 | 推荐 | 状态 |
|---|------|------|------|------|
| §4.7-1 | Case 3a | B-filter 后 LLM question 只覆盖 dropped slots：final user-facing text must be regenerated via LLM/reply pipeline, hardcoded_reason only as internal seed | Option b: P3 hardcoded_reason as internal seed → LLM/reply pipeline regenerated | Closed |
| §4.7-2 | Case 4 | unknown tool_contract: B hard diagnostic (not B gate); A/router decides safe fallback; risky proceed forbidden | Fallback to hard-rule path | Closed |

---

*§4 结束。B validator design and §4.7 edge-case decisions are closed for Round 3 planning。*
*下一步: Round 3 implementation planning after this design document is tracked。*

## §5 Class E narrow — Chain handoff repair design

### §5.1 Scope and boundary

E narrow fixes only the Task 120 macro → dispersion chain persistence failure: Stage 2 produces `["calculate_macro_emission", "calculate_dispersion"]`, but after a clarify/follow-up turn the chain can degrade or be overwritten, causing `governance_full` to repeat `calculate_macro_emission` and never reach `calculate_dispersion`.

Strict boundary:
- E narrow does not introduce canonical multi-turn state.
- E narrow does not handle full revision-aware chain replacement.
- E narrow does not fix Class D AO completion state.
- E narrow does not widen AO classification or continuation classification boundary.
- E narrow does not redesign PCM; PCM mode has already been audited as advisory in `governance_full`.
- E narrow does not modify A reconciler or B validator. B validator is unrelated here and must not become a hard gate; A reconciler remains arbitration.
- E narrow does not change `config/tool_contracts.yaml` or expand tool-contract policy.
- Phase 6 E full remains mandatory architecture debt.

The only verification target for this section is Task 120 chain persistence across the macro → dispersion handoff. No unrelated failures or benchmark plans are part of this design.

### §5.2 Evidence table: projected_chain lifecycle

| File:line | Evidence | E narrow implication |
|---|---|---|
| `core/analytical_objective.py:49-55` | `ToolIntent` owns `projected_chain` as first-class AO state. | The repair should preserve this field when it already contains a valid multi-step chain. |
| `core/intent_resolver.py:57` | `resolve_fast()` can produce `projected_chain=["calculate_macro_emission"]` from `file_context.task_type == "macro_emission"`. | A later fast-rule pass can degrade an existing macro → dispersion chain to a single macro tool. |
| `core/intent_resolver.py:90-96` | `resolve_fast()` fallback can produce `projected_chain=[]`. | A later fallback pass can erase an existing chain if persistence is unconditional. |
| `core/intent_resolver.py:111-120` | `resolve_with_llm_hint()` merges `parsed_chain` only when `fast.resolved_tool == parsed_chain[0]` and the parsed chain is longer than the fast chain. | LLM chain recovery is narrow and does not protect against later persistence overwrite. |
| `core/intent_resolver.py:166-167` | `_pending_tool_name()` already returns `continuation.pending_next_tool`; for `CHAIN_CONTINUATION`, this is the next chain tool. | No extra E narrow lookup is needed here by default. |
| `core/intent_resolver.py:178-187` | `_projected_chain_from_ao()` reads `continuation.pending_tool_queue` first, then AO `tool_intent.projected_chain`. | Existing continuation state already has priority over stale AO chain state during fast resolution. |
| `core/contracts/clarification_contract.py:1013-1024` | `_persist_tool_intent()` currently assigns `target.projected_chain = list(...)` unconditionally. | This is chain-destruction mechanism A. It can erase or shrink a previously accepted multi-step chain. |
| `core/contracts/intent_resolution_contract.py:48-61` | `CHAIN_CONTINUATION` short-circuit already returns `continuation.pending_next_tool` with `projected_chain=list(continuation.pending_tool_queue or [])`. | E narrow should not widen this short-circuit. |
| `core/contracts/intent_resolution_contract.py:123` | `_persist_tool_intent()` is called after intent resolution. | The unconditional persistence point can overwrite the accepted chain after every resolution pass. |
| `core/contracts/execution_readiness_contract.py:191-204` | `replace_queue_override` replaces continuation when `projected_chain[0] != continuation_before.pending_next_tool`. | This is chain-destruction mechanism B. It can replace pending dispersion with a macro-only queue. |
| `core/contracts/oasc_contract.py:143-158` | OASC advances an existing chain via `advance_tool_queue(...)`. | Chain advancement logic already exists and should be preserved. |
| `core/contracts/oasc_contract.py:160-167` | OASC builds `CHAIN_CONTINUATION` when `len(projected_chain) > 1`. | The initial macro → dispersion queue is already supported when the full chain survives. |
| `core/execution_continuation_utils.py:42-55` | `build_chain_continuation()` normalizes a projected chain and stores the remaining queue. | No new chain representation is needed for E narrow. |
| `core/execution_continuation_utils.py:66-74` | `advance_tool_queue()` advances sequentially through executed tools. | Sequential chain movement is already implemented. |

### §5.3 Corrected root cause for Task 120

Task 120 has two independent chain-destruction mechanisms:

A. `_persist_tool_intent()` unconditional overwrite:
- Existing `["calculate_macro_emission", "calculate_dispersion"]` can be overwritten by `[]` from `resolve_fast()` fallback.
- Existing `["calculate_macro_emission", "calculate_dispersion"]` can also be overwritten by single-tool `["calculate_macro_emission"]` from the `file_task_type:macro_emission` fast rule.
- Once overwritten, later stages no longer have a durable macro → dispersion plan to hand off.

B. `execution_readiness_contract` `replace_queue_override`:
- Existing `CHAIN_CONTINUATION` with `pending_next_tool="calculate_dispersion"` can be replaced by `projected_chain=["calculate_macro_emission"]` because the current guard only checks `projected_chain[0] != pending_next_tool`.
- That replacement resets the queue to macro and causes repeated `calculate_macro_emission` execution instead of advancing to `calculate_dispersion`.

Fix 2 from the earlier audit is removed. `_pending_tool_name()` and `intent_resolution_contract` already handle `CHAIN_CONTINUATION`; adding redundant lookup logic has no direct evidence for Task 120 and belongs to follow-up only if Task 120 still fails after Fix 1 + Fix 3.

### §5.4 Fix 1 — preserve multi-step projected_chain in _persist_tool_intent

Design only; do not implement in this section.

Accepted pseudo-code:

```python
new_chain = list(getattr(tool_intent, "projected_chain", []) or [])
existing_chain = list(getattr(target, "projected_chain", []) or [])

# Rule 1: never erase a non-empty chain.
if not new_chain and existing_chain:
    return

# Rule 2: preserve multi-step chain against single-step or empty degradation.
if len(existing_chain) > 1 and len(new_chain) <= 1:
    if not new_chain:
        return
    if new_chain[0] in existing_chain and existing_chain.index(new_chain[0]) > 0:
        pass  # legitimate downstream advancement
    else:
        return  # regression to first tool or unrelated single-tool overwrite

target.projected_chain = new_chain
```

Decision table for `existing_chain=["A", "B"]`:

| `new_chain` | Decision | Reason |
|---|---|---|
| `[]` | block | Never erase a non-empty chain. |
| `["A"]` | block | Regression to first tool. |
| `["B"]` | allow | Legitimate downstream advancement. |
| `["X"]` | block | Unrelated single-tool overwrite. |
| `["A", "B"]` | accept | Same chain. |
| `["A", "B", "C"]` | accept | Multi-step expansion. |
| `["B", "C"]` | accept | Downstream multi-step replacement. |

This does not solve revision-aware replacement. A true user revision to `["X"]` needs explicit revision evidence and belongs to Phase 6 E full / Class D boundary work.

### §5.5 Fix 3 — guard replace_queue_override in execution_readiness_contract

Design only; do not implement in this section.

Accepted pseudo-code:

```python
elif (
    continuation_before.pending_objective == PendingObjective.CHAIN_CONTINUATION
    and continuation_before.pending_next_tool
    and projected_chain
    and projected_chain[0] != continuation_before.pending_next_tool
):
    if continuation_before.pending_next_tool in projected_chain:
        idx = projected_chain.index(continuation_before.pending_next_tool)
        continuation_after = ExecutionContinuation(
            pending_objective=PendingObjective.CHAIN_CONTINUATION,
            pending_next_tool=continuation_before.pending_next_tool,
            pending_tool_queue=projected_chain[idx:],
            updated_turn=self._current_turn_index(),
        )
        save_execution_continuation(current_ao, continuation_after)
        transition_reason = "replace_queue_override"
    # else: pending_next_tool not in projected_chain — preserve existing, no-op.
```

If `pending_next_tool` is not in `projected_chain`, implementation must not call `save_execution_continuation()`. It must not change `transition_reason`. This prevents `pending_next_tool="calculate_dispersion"` from being replaced by `["calculate_macro_emission"]`.

### §5.6 Why Fix 2 is removed

`_pending_tool_name()` already handles `CHAIN_CONTINUATION` by returning `continuation.pending_next_tool`.

`intent_resolution_contract` already has a `CHAIN_CONTINUATION` short-circuit that resolves the pending tool from continuation state and carries `continuation.pending_tool_queue`.

A third redundant check would increase maintenance without evidence. If Task 120 still fails after Fix 1 + Fix 3, audit again; do not preemptively widen AO classification or the short-circuit boundary.

### §5.7 Proposed change surface and LOC estimate

| File | Proposed E narrow change | Estimate |
|---|---|---:|
| `core/contracts/clarification_contract.py:1024` | Guard `projected_chain` persistence against empty/single-step degradation. | ~+8 LOC |
| `core/contracts/execution_readiness_contract.py:191-204` | Guard `replace_queue_override` to preserve `pending_next_tool` unless it appears in the new projected chain. | ~+11 LOC |
| Total | E narrow implementation surface. | ~+19 LOC |

No changes to `core/intent_resolver.py` in default E narrow.

No changes to `core/contracts/oasc_contract.py`.

No changes to `core/execution_continuation_utils.py`.

No changes to `config/tool_contracts.yaml`.

### §5.8 Minimal verification target

After implementation, run Task 120 single-task verify before any 30-task sanity.

Expected result: `governance_full` should advance from `calculate_macro_emission` to `calculate_dispersion` across the clarify/follow-up turn.

Do not run 30-task sanity until Task 105/110/120 minimal gates all pass after A/B/E implementation.

### §5.9 Phase 6 E full boundary

Phase 6 E full remains responsible for:
- canonical multi-turn state layer
- revision-aware chain replacement
- classification boundary widening
- stale chain pruning in OASC
- chain state across AO boundaries
- LLM prompt visibility of pending chain state
- continuation recovery after tool failure
- arbitrary multi-step/branching chain management

## §6 修复后预期行为

本节描述 A/B/E narrow 实施后的设计预期行为。这里不是 benchmark 结果，也不声明系统已经通过任何评测。

### §6.1 Task 105 expected behavior — Class B

修复前失败模式:
- Stage 2 为 `calculate_macro_emission` hallucinate `missing_required=["vehicle_type", "road_type"]`。
- YAML contract 中 `calculate_macro_emission` 只要求 `pollutants`，所以 `vehicle_type` / `road_type` 不是该工具的 contract-grounded required slots。

B validator 后:
- `filter_stage2_missing_required()` drops non-contract slots。
- `filter_clarify_candidates()` 也过滤由 hallucinated Stage 2 needs 派生出的 `readiness_gate` candidates。
- B 只输出 grounded slots + telemetry；B validator never makes route decisions and is never a hard gate。
- A reconciler 决定最终 route。

预期结果:
- 如果 `pollutants=["CO2"]` 已填充，且 `season="夏季"` 已 default/resolved，则 reconciled decision 应为 proceed。
- Tool chain 应执行一次 `calculate_macro_emission`，不应重复执行 macro。

Verification gate:
- B implementation 后先跑 Task 105 single-task verify，再进入更大范围 sanity。

### §6.2 Task 110 expected behavior — Class A

修复前失败模式:
- Stage 2 raw decision says proceed with complete slots。
- Readiness/final route remains clarify，导致 0 tool calls。

A reconciler 后:
- P1 `stage2_raw`、P2 `stage3_yaml`、P3 `readiness_gate` 都必须被 representation。
- Trust levels and conflict rules are explicit。
- `ReconciledDecision.source_trace` 记录完整 source breakdown。
- A reconciler is arbitration, not "P2 always wins"。

预期结果:
- 如果 Stage 2 proceed 被 YAML required slots filled 支持，且 readiness 没有 true hard-block，则 final route proceeds to `query_emission_factors`。
- 系统不应继续卡在 clarify loop / 0 tool call。

Verification gate:
- A implementation 后跑 Task 110 single-task verify。

### §6.3 Task 120 expected behavior — Class E narrow

修复前失败模式:
- Stage 2 输出 chain `["calculate_macro_emission", "calculate_dispersion"]`。
- Clarify/follow-up turn 后 chain degraded/overwritten，导致重复 macro 且没有 dispersion。

E narrow 后:
- `_persist_tool_intent` preserves existing multi-step `projected_chain` against empty/single-step degradation。
- `execution_readiness_contract` `replace_queue_override` preserves current `pending_next_tool` and no-ops if `projected_chain` loses it。
- Fix 2 remains removed from the default E narrow fix set。

预期结果:
- Chain 应从 `calculate_macro_emission` advance to `calculate_dispersion`。
- 不应只重复执行 macro。

Verification gate:
- E implementation 后跑 Task 120 single-task verify。

### §6.4 System-level expected behavior

修复后的 decision consumption path:

```text
Stage 2 raw → B grounding filter → Stage 3 YAML / readiness sources → A reconciliation → router consume
```

A/B/E narrow fixes 应先让 105/110/120 通过，再运行 30-task sanity。

这不声明 Phase 6 D/E full 已解决。

这不声明 benchmark-wide success；benchmark 结论必须等待证据。

## §7 Unit test and minimal verification design

本节只设计 tests 和 verification gates。本文档 closeout 不运行 tests、不运行 benchmark。

### §7.1 B validator unit tests

Suggested test file:
- `tests/test_contract_grounding_validator.py`

Proposed tests:
- `filter_stage2_missing_required()` drops hallucinated slots for `calculate_macro_emission`。
- `filter_clarify_candidates()` drops readiness candidates not in required/followup slots。
- Dropped evidence includes original slots, grounded slots, dropped slots, allowed slots, and source。
- `unknown_tool_contract` produces hard diagnostic, not a B decision。
- B does not output proceed/clarify/deliberate。

Design invariant:
- B validator filters legal slot subsets and emits telemetry only。
- B validator is never a hard gate and never owns final route decisions。

### §7.2 A reconciler unit tests

Suggested test file:
- `tests/test_reconciler.py`

Proposed tests:
- Stage 2 proceed + YAML complete + readiness no hard-block => reconciled proceed。
- Stage 2 clarify with hallucinated missing slots + B grounded empty + YAML complete => reconciled proceed。
- True YAML missing required slot => reconciled clarify。
- Readiness true hard-block such as missing dependency/file is not bypassed by B。
- `source_trace` contains P1/P2/P3 and `applied_rule_id`。
- Trust levels/conflict rule evidence present。
- No "P2 always wins" shortcut。

Design invariant:
- A reconciler is arbitration across sources with source breakdown and trust/conflict reasoning。
- A must not collapse into a simplistic precedence rule.

### §7.3 E narrow unit tests

Suggested test files:
- `tests/test_projected_chain_persistence.py`
- or `tests/test_execution_readiness_chain_guard.py`

Proposed tests:
- `_persist_tool_intent` does not let `[]` erase existing `["A", "B"]`。
- `_persist_tool_intent` does not let `["A"]` overwrite existing `["A", "B"]`。
- `_persist_tool_intent` allows `["B"]` as downstream advancement from `["A", "B"]`。
- `_persist_tool_intent` does not let `["X"]` overwrite existing `["A", "B"]` without revision evidence。
- `replace_queue_override` does not replace `pending_next_tool="B"` with `projected_chain=["A"]`。
- `replace_queue_override` rebuilds queue when `projected_chain=["A", "B", "C"]` and `pending_next_tool="B"` => `["B", "C"]`。

Design invariant:
- E narrow protects only macro → dispersion chain persistence.
- Revision-aware replacement and arbitrary branching remain Phase 6 E full debt.

### §7.4 Minimal task verification gates

Mandatory order:
1. After B validator implementation + unit tests: run Task 105 single-task verify.
2. After A reconciler integration + unit tests: run Task 110 single-task verify.
3. After E narrow implementation + unit tests: run Task 120 single-task verify.
4. Only after 105/110/120 all pass: run 30-task sanity.
5. Only after 30-task sanity: consider larger benchmark.

If any single task fails, STOP and audit design vs implementation.

Do not run 30-task sanity to hide single-task failure behind aggregate statistics.

### §7.5 Suggested verification commands

Exact script names/flags must be verified before Round 3 implementation. Do not assume command syntax from this design document.

Command discovery suggestions:

```bash
grep -rn "e2e_clarification_105\|e2e_clarification_110\|e2e_clarification_120" evaluation tests
grep -rn "eval_end2end\|single task\|task_id\|benchmark" evaluation scripts tests
```

Placeholder verification intents:
- `<single-task verification command for Task 105>`
- `<single-task verification command for Task 110>`
- `<single-task verification command for Task 120>`
- `<30-task sanity command, only after 105/110/120 all pass>`
- `<larger benchmark command, only after 30-task sanity evidence>`

## §8 风险评估与后续边界

本节明确 implementation risks 和 non-goals。未解决缺陷不能被转写成 paper narrative。

### §8.1 Implementation risks

- Reconciler integration could accidentally bypass real readiness hard-blocks.
- B validator could accidentally become a hard gate if implemented wrongly.
- E narrow chain guard could preserve stale chain in true user revision cases.
- Wave 1 / Wave 2 dual path consistency risk.
- Untracked document risk: this design doc must be git-added before commit.

### §8.2 Scope risks / expansion control

Out of scope for Phase 5.3 Round 2 A/B/E narrow:
- Class C AO classifier bug unless new direct evidence ties it to 105/110/120。
- Class D AO completion state。
- Phase 6 E full canonical multi-turn state。
- PCM redesign。
- Unrelated benchmark category failures。
- Arbitrary chain branching / revision-aware replacement。

Scope control rule:
- Phase 5.3 scope is A/B/E narrow only.
- Class C/D/E-full/unrelated failures are followups unless directly required by Task 105/110/120 evidence.

### §8.3 Mitigation

- Use unit tests before task verification.
- Use 105/110/120 strict gates.
- Add telemetry/source_trace for B and A.
- Keep E narrow to two files unless implementation audit proves otherwise.
- Stop on any discipline trigger.

Discipline triggers include:
- B validator starts making route decisions or behaving like a hard gate.
- A reconciler loses P1/P2/P3 source breakdown.
- PCM advisory mode is redesigned instead of consumed as already audited.
- Any single-task gate fails.
- Implementation tries to absorb Class C/D/E-full without direct evidence.

### §8.4 Phase 6 mandatory architecture debt

D full:
- AO needs completed/satisfied objective state to avoid contamination.

E full:
- A canonical multi-turn state layer is still required.

These are not future work for paper decoration. They are mandatory architecture debts to be paid before claiming final system maturity.

Phase 5.3 only stabilizes the A/B/E narrow decision path.

### §8.5 Paper-writing boundary

- No claim that Phase 5.3 alone makes the whole architecture final.
- No claim of benchmark success before data.
- No framing of defects as contributions.
- Paper timing follows architecture state and evidence.

## §9 Round 3 implementation status and adjusted gates

This section records Round 3.1 implementation outcomes observed after the Round 2 design was accepted. It is status documentation only; it does not change the §3-§8 design decisions.

### §9.1 Round 3.1B — B validator unit layer

Implementation status:
- Created `core/contracts/reconciler.py`.
- Created `tests/test_contract_grounding_validator.py`.
- B validator unit tests passed 25/25.
- Unsafe `governed_router` R2 integration was reverted.

Gate conclusion:
- Status: B unit accepted; integration pending A/P2/P3 path.
- B remains a contract-grounding filter and telemetry producer only.
- B must not become a hard gate or output `proceed` / `clarify` / `deliberate`.

### §9.2 Round 3.1C — C-narrow intent anchor

Implementation status:
- Added narrow continuation file-task anchor in `core/contracts/intent_resolution_contract.py`.
- Added `tests/test_intent_resolution_contract.py`.
- Tests passed 7/7.

Gate conclusion:
- Status: kept as bounded C-narrow support, but not credited alone for Task 105.
- This does not expand Phase 5.3 into Class C full AO classification repair.

### §9.3 Round 3.1D — OASC stale backfill guard

Implementation status:
- Changed `core/contracts/oasc_contract.py` from:

```python
if not result.executed_tool_calls:
```

to:

```python
if result.executed_tool_calls is None:
```

- Added `tests/test_oasc_backfill_guard.py`.
- Tests passed 6/6.

Gate conclusion:
- Status: accepted.
- This fixes stale tool-call contamination on clarify turns.

### §9.4 Round 3.1E — file_analysis persistence / hydration

Implementation status:
- Added file context hydration call in `core/contracts/intent_resolution_contract.py`.
- Added `tests/test_file_analysis_hydration.py`.
- Tests passed 7/7.
- Regression tests still passed:
  - B validator 25/25.
  - C-narrow 7/7.
  - OASC backfill 6/6.

Latest Task 105 result:
- `query_emission_factors` drift is gone.
- All turns resolve to `calculate_macro_emission`.
- No `vehicle_type` clarification remains.
- Actual chain is `["calculate_macro_emission", "calculate_macro_emission"]`.
- Expected chain is `["calculate_macro_emission"]`.
- `completion_rate` remains `0.0` due to exact `tool_chain` mismatch.

Interpretation:
- Phase 5.3-fixable defects for Task 105 are closed:
  - B slot grounding unit layer.
  - Intent drift.
  - Stale OASC backfill.
  - `file_context` hydration.
- Remaining duplicate execution is same-tool same-effective-params idempotency / AO completed-state debt.
- This is Phase 6 Class D full, not Phase 5.3.
- Do NOT implement idempotency guard in Phase 5.3.

Task 105 adjusted gate status: Phase 5.3-fixable blockers closed; residual exact-chain failure is Phase 6 Class D idempotency / AO completed-state debt. This permits Phase 5.3 to proceed to Task 110/A reconciliation without treating Task 105 as a full benchmark PASS.

Warnings:
- Do not claim Task 105 full PASS.
- Do not claim benchmark success.
- Do not hide `completion_rate=0.0`.
- Do not implement same-tool same-params duplicate suppression in Phase 5.3.

### §9.5 Round 3.2 — A reconciler

Implementation:
- `core/contracts/reconciler.py`: New file (~350 lines).
- `ReconciledDecision` 7-field schema: `decision_value`, `reconciled_missing_required`, `clarification_question`, `deliberative_reasoning`, `reasoning`, `source_trace`, `applied_rule_id`.
- 4 rules in priority order:
  - **A1** (`R_A_STAGE2_PROCEED_SUPPORTED_BY_YAML_AND_READINESS`): P1 proceed + P2/P3 clean → proceed.
  - **A2** (`R_A_YAML_REQUIRED_MISSING`): P2 has missing required → clarify.
  - **A3** (`R_A_B_FILTERED_EMPTY_WITH_P2P3_SUPPORT`): P1/P3 clean, B-filtered empty, P2 clean → proceed.
  - **A4** (`R_A_DEFER_TO_READINESS`): Fallback to P3 disposition.
- Source transport: P1 (`Stage2RawSource`, trust: `llm_semantic`), P2 (`stage3_yaml`, trust: `yaml_deterministic`), P3 (`ReadinessGateState`, trust: `readiness_heuristic`).
- B validator (`ContractGroundingResult`) integrated as pre-filter for A3.
- Integration in `governed_router._consume_decision_field`: builds P1/P2/P3, runs B filter, runs reconcile, stores `reconciled_decision` in context.metadata.
- 19 unit tests pass.

Status:
- A reconciler implementation is accepted.
- Task 110 original expected Class A failure changed after upstream snapshot persistence fixes (Round 3.3/3.4); A implementation itself is correct and remains accepted.
- No A rule change after initial implementation.

### §9.6 Round 3.3 — parameter snapshot persistence

Implementation:
- `core/contracts/execution_readiness_contract.py`: `_persist_split_pending` now mirrors `execution_readiness.parameter_snapshot` to top-level AO-local fields:
  - `ao.metadata["parameter_snapshot"]` = deep copy of snapshot.
  - `ao.parameters_used[slot_name]` = value for each non-missing, non-empty, non-rejected slot.
- `ClarificationContract._initial_snapshot`: reads `pending_state["parameter_snapshot"]` first, then `current_ao.metadata["parameter_snapshot"]`, then parent AO, then empty snapshot.
- 13 unit tests pass.

Status:
- `vehicle_type` persists across turns in Task 110.
- Snapshot accumulation works: Turn 2 fills vehicle_type, Turn 3 adds pollutants → merged snapshot has both.

### §9.7 Round 3.4 — Stage 1 merge protection

Implementation:
- `core/contracts/clarification_contract.py`: `_merge_stage2_snapshot` now guards Stage 1 deterministic fills against Stage 2 LLM downgrade.
  - When `base_slot.value` is non-empty (not None, "", []) AND `llm_value` is empty/missing → skip, preserve Stage 1 fill.
  - Empty list `[]` and empty string `""` are treated as empty.
  - Sentinel values (`Missing`, `UNKNOWN`, `n/a`) are normalized to None via `_normalize_missing_value`.
- 10 unit tests pass.

Status:
- `pollutants=["PM10"]` from Stage 1 preserved when Stage 2 outputs missing.
- Stage 2 non-empty updates still accepted (refinement, not downgrade).

### §9.8 Round 3.5 — stance guard

Implementation:
- `core/contracts/stance_resolution_contract.py`: In continuation/no-reversal branch, check if `PendingObjective.PARAMETER_COLLECTION` is active via `load_execution_continuation()`.
  - If active → resolve stance as `DIRECTIVE` (confidence=HIGH, resolved_by="continuation_state:parameter_collection").
  - If not active → preserve previous stance (existing behavior).
- `is_active()` check ensures: abandoned=false AND pending_slot is set.
- Reversal detection takes priority (checked before PARAMETER_COLLECTION guard).
- 7 unit tests pass.

Status:
- Task 110 Turn 3 "PM10": stance=directive (resolved_by=continuation_state:parameter_collection).
- `query_emission_factors` executes with correct args: vehicle_type="Refuse Truck", pollutants=["PM10"], model_year=2020.
- **Task 110 adjusted gate closed.**
- Residual: duplicate `query_emission_factors` execution on Turn 4. This is Phase 6 Class D idempotency / AO completed-state debt.

### §9.9 Round 3.6 — E narrow chain handoff

Implementation:
- **Fix 1** — `core/contracts/clarification_contract.py`: `_persist_tool_intent` guards `projected_chain` persistence:
  - Rule 1: never erase a non-empty chain with empty.
  - Rule 2: preserve multi-step chain against single-step degradation.
  - Valid downstream advancement allowed (e.g., `["A","B"]` + new `["B"]` → accept).
  - Unrelated single-tool overwrite blocked.
- **Fix 3** — `core/contracts/execution_readiness_contract.py`: `replace_queue_override` now checks `pending_next_tool in projected_chain` before replacing continuation.
  - If `pending_next_tool` in chain → rebuild queue from that index.
  - If NOT in chain → no-op (preserve existing continuation, no `save_execution_continuation()` call).
- 17 unit tests pass (10 for Fix 1, 7 for Fix 3).

Status:
- Task 120 Turn 1: Stage 2 outputs `projected_chain=["calculate_macro_emission", "calculate_dispersion"]`.
- Task 120 Turn 2: chain preserved (Fix 1). Macro executes. OASC advances continuation to `pending_next_tool=calculate_dispersion`.
- Task 120 Turn 3: chain handoff intact (Fix 3). `pending_next_tool=calculate_dispersion` NOT overwritten. Dispersion tool is attempted.
- Dispersion tool fails with "缺少空间几何信息" — tool-level spatial geometry dependency, not E narrow chain persistence.
- **Task 120 adjusted gate closed.**
- Remaining failure: dispersion tool requires WKT/GeoJSON/coordinates not present in macro result from `macro_direct.csv`. This is a tool contract / data-flow issue.

### §9.10 Phase 6 outstanding debts

The following are explicitly deferred to Phase 6:

1. **idempotency / AO completed-state** (Class D):
   - Same-tool same-effective-params duplicate execution (Task 105 duplicate macro, Task 110 duplicate query_emission_factors).
   - AO completed-state detection so the system does not re-execute already-completed tools.

2. **Full canonical multi-turn state** (Class E full):
   - Revision-aware chain replacement.
   - Arbitrary chain branching beyond macro→dispersion.
   - Cross-AO chain memory.

3. **Dispersion data-flow / spatial geometry dependency**:
   - `calculate_dispersion` requires spatial geometry (WKT/GeoJSON/coordinates) not currently provided by `calculate_macro_emission` output from CSV-only inputs.
   - May be treated as tool contract debt (macro should emit spatial data, or dispersion should accept tabular-only input with default geometry).

Warnings:
- Do NOT claim Task 105, Task 110, or Task 120 full benchmark PASS.
- Do NOT hide residual exact metric failures caused by Phase 6 debts.
- Do NOT implement idempotency, dispersion geometry fixes, or canonical multi-turn state in Phase 5.3.
- Phase 5.3 scope is closed as of Round 3.6.
