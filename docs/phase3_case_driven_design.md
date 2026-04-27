# Phase 3.1 Case-Driven Design Verification

> Read-only design document. Validates the `decision` field architecture against four
> concrete mechanism cases before any code is written.
> Branch: `phase3-governance-reset`. Date: 2026-04-27.

---

## Section 1: Case A — Constraint Conflict Graceful Handling

### 1.1 Dialogue Script

**Scenario**: User requests a physically invalid parameter combination. Governance
detects the violation, blocks execution, and the reply LLM negotiates a correction —
all without hardcoded governance-authored text.

```
Turn 1:
  User:   "查一下 Motorcycle 在高速公路上的 PM2.5 和 NOx 排放因子"
  Agent:  "摩托车不允许在高速公路上行驶。如果您需要查询摩托车排放因子，请选择地面道路
           或快速路。另外，摩托车 PM2.5 排放数据在 MOVES 中覆盖有限，建议优先查询
           CO、NOx 或 THC。需要调整查询条件吗？"

Turn 2:
  User:   "那换成地面道路，查 NOx 和 CO 吧"
  Agent:  [执行 query_emission_factors(vehicle_type=Motorcycle, road_type=地面道路,
           pollutants=[NOx, CO])，返回因子曲线和数据]
```

### 1.2 Step-by-Step LLM Stage 2 Expected Outputs

**Turn 1 Stage 2 output**:

```json
{
  "slots": {
    "vehicle_type": {"value": "Motorcycle", "source": "user", "confidence": 1.0, "raw_text": "Motorcycle"},
    "pollutants": {"value": ["PM2.5", "NOx"], "source": "user", "confidence": 1.0, "raw_text": "PM2.5 和 NOx"},
    "road_type": {"value": "高速公路", "source": "user", "confidence": 1.0, "raw_text": "高速公路"}
  },
  "intent": {"resolved_tool": "query_emission_factors", "intent_confidence": "high"},
  "stance": {"value": "directive", "confidence": "high"},
  "missing_required": [],
  "needs_clarification": false,
  "clarification_question": null,
  "decision": {
    "value": "proceed",
    "confidence": 0.92,
    "reasoning": "车型、污染物和道路类型均已由用户指定，可直接执行排放因子查询。",
    "clarification_question": null
  }
}
```

**Turn 2 Stage 2 output** (after violation feedback from Turn 1):

```json
{
  "slots": {
    "vehicle_type": {"value": "Motorcycle", "source": "prior_context", "confidence": 0.95, "raw_text": "Motorcycle"},
    "pollutants": {"value": ["NOx", "CO"], "source": "user", "confidence": 1.0, "raw_text": "NOx 和 CO"},
    "road_type": {"value": "地面道路", "source": "user", "confidence": 1.0, "raw_text": "地面道路"}
  },
  "intent": {"resolved_tool": "query_emission_factors", "intent_confidence": "high"},
  "stance": {"value": "directive", "confidence": "high"},
  "missing_required": [],
  "needs_clarification": false,
  "clarification_question": null,
  "decision": {
    "value": "proceed",
    "confidence": 0.90,
    "reasoning": "用户已根据上一轮的约束提示调整了道路类型和污染物，所有参数合法。",
    "clarification_question": null
  }
}
```

### 1.3 What Governance Does at Each Step

**Turn 1**:

1. Stage 2 LLM returns `decision=proceed`
2. `validate_decision()` passes (confidence 0.92 ≥ 0.5, no missing_required)
3. GovernedRouter invokes cross-constraint preflight before execution:
   - `CrossConstraintValidator.validate()` checks standardized params against
     `config/cross_constraints.yaml`
   - Detects two issues:
     - `vehicle_road_compatibility`: Motorcycle + 高速公路 → **reject** (blocked)
     - `vehicle_pollutant_relevance`: Motorcycle + PM2.5 → **warn** (conditional_warning)
4. Governance **blocks execution** for the `reject`-severity violation.
   Constructs a `ViolationRecord`:
   ```python
   ViolationRecord(
       violation_type="vehicle_road_compatibility",
       severity="reject",
       involved_params={"vehicle_type": "Motorcycle", "road_type": "高速公路"},
       suggested_resolution="摩托车不允许上高速公路。可选道路类型: 快速路, 地面道路, 主干路。",
       source_turn=1,
   )
   ```
   And a second record for the warning:
   ```python
   ViolationRecord(
       violation_type="vehicle_pollutant_relevance",
       severity="warn",
       involved_params={"vehicle_type": "Motorcycle", "pollutants": "PM2.5"},
       suggested_resolution="摩托车PM2.5排放数据覆盖有限，可优先选择CO、NOx、THC。",
       source_turn=1,
   )
   ```
5. `ConstraintViolationWriter.record()` persists each to:
   - `current_ao.constraint_violations` (AO-scoped history)
   - `context_store._latest_constraint_violations` (reply context source)
6. GovernedRouter constructs `RouterResponse` with `proceed=False`-equivalent
   semantics and `violations` in trace. **No hardcoded Chinese text** — the
   reply pipeline handles user-facing text generation.
7. `ReplyContextBuilder.build()` reads violations from `violation_writer.get_latest()`
   and populates `ReplyContext.violations`.
8. Reply LLM receives:
   ```json
   {
     "violations": [
       {
         "violation_type": "vehicle_road_compatibility",
         "severity": "reject",
         "involved_params": {"vehicle_type": "Motorcycle", "road_type": "高速公路"},
         "suggested_resolution": "摩托车不允许上高速公路。可选道路类型: 快速路, 地面道路, 主干路。"
       },
       {
         "violation_type": "vehicle_pollutant_relevance",
         "severity": "warn",
         "involved_params": {"vehicle_type": "Motorcycle", "pollutants": "PM2.5"},
         "suggested_resolution": "摩托车PM2.5排放数据覆盖有限，可优先选择CO、NOx、THC。"
       }
     ]
   }
   ```
   And generates: *"摩托车不允许在高速公路上行驶。如果您需要查询摩托车排放因子，请选择地面道路或快速路。另外，摩托车 PM2.5 排放数据在 MOVES 中覆盖有限，建议优先查询 CO、NOx 或 THC。需要调整查询条件吗？"*

**Turn 2**:

1. Stage 2 LLM receives `prior_violations` in its user payload (see §1.4), sees the
   previous violations, understands user has corrected both road_type and pollutants.
2. Outputs `decision=proceed`.
3. Cross-constraint preflight re-runs: Motorcycle + 地面道路 → OK (no block rule for
   地面道路). Motorcycle + [NOx, CO] → OK (no warning for NOx or CO).
4. No violations detected → tool executes normally.

### 1.4 ConstraintViolation Injection Flow — Concrete Design

The key question from my previous design document was: *"ConstraintViolation 具体怎么
注入下一轮 LLM context?"* Here is the answer.

**Step A — Violation production** (already exists in code, no change needed):

```
inner_router._evaluate_cross_constraint_preflight()
  → CrossConstraintValidator.validate()
  → returns CrossConstraintResult(violations=[...], warnings=[...])
  → router emits trace step with type "cross_constraint_violation"
  → router transitions state to DONE with blocked_info
```

**Step B — Violation persistence** (already exists, used by GovernedRouter):

```
GovernedRouter._record_constraint_violations_from_trace()    # governed_router.py:262
  → normalize_cross_constraint_violation()                    # constraint_violation_writer.py:51
  → ConstraintViolationWriter.record()                        # constraint_violation_writer.py:90
    → appends to current_ao.constraint_violations (AO-scoped)
    → replaces context_store._latest_constraint_violations
```

**Step C — Violation → Stage 2 LLM injection** (NEW, the gap to close):

Currently, `context_store._latest_constraint_violations` is read ONLY by
`ReplyContextBuilder` (for the reply parser), NOT by the Stage 2 prompt builder.

To close this gap, the Stage 2 user payload (`prompt_payload` in
`clarification_contract.py:662-681` and `split_contract_utils.py:40-59`) gains
one new key:

```yaml
prior_violations:
  - violation_type: "vehicle_road_compatibility"
    severity: "reject"
    involved_params:
      vehicle_type: "Motorcycle"
      road_type: "高速公路"
    suggested_resolution: "摩托车不允许上高速公路。"
    source_turn: 1
  - violation_type: "vehicle_pollutant_relevance"
    severity: "warn"
    involved_params:
      vehicle_type: "Motorcycle"
      pollutants: "PM2.5"
    suggested_resolution: "摩托车PM2.5排放数据覆盖有限，可优先选择CO、NOx、THC。"
    source_turn: 1
```

Implementation: The Stage 2 prompt builder reads from
`self.constraint_violation_writer.get_latest()` (which returns current AO's
violations from `ao_manager.get_current_ao().constraint_violations`) and
serializes them into the YAML payload.

**Step D — Violation → Reply LLM** (already works, no change needed):

`ReplyContextBuilder.build()` lines 44-56 already reads violations from
`violation_writer.get_latest()` and includes them in `ReplyContext.violations`.
The reply parser LLM prompt receives the full `ReplyContext.to_dict()` JSON.

### 1.5 Code Change Points

| Change | File:Line | Description |
|--------|-----------|-------------|
| Inject `prior_violations` into Stage 2 payload | `clarification_contract.py:662-681` | Add key to `prompt_payload` dict; read from `self.constraint_violation_writer.get_latest()` |
| Same for split contracts | `split_contract_utils.py:40-59` | Same change to `prompt_payload` |
| Remove hardcoded Chinese text from cross-constraint blocker | `router.py:2268-2276` | Replace `message = f"参数组合不合法: {violation.reason}..."` with structured violation event in trace; let reply LLM generate text |
| GovernedRouter: handle `blocked` result | `governed_router.py:130-143` | When inner router returns blocked state, construct RouterResponse with structured violation data, NOT hardcoded text |
| System prompt: add `prior_violations` awareness | `clarification_contract.py:692-713` | Add rule in Stage 2 prompt: "如果 prior_violations 非空，说明上一轮存在参数违规，你应在决策时考虑这些违规是否已被用户修正" |
| System prompt: add `prior_violations` awareness (compact) | `split_contract_utils.py:17-27` | Same rule in compact variant |

### 1.6 Uncertainties / Needs Human Review

- **Q-A1**: The current `_evaluate_cross_constraint_preflight` is called from
  `router.py` inner router, not from GovernedRouter. Should we move the preflight
  call to GovernedRouter so it gates `decision=proceed` before inner router
  invocation? Or keep it in the inner router and have GovernedRouter inspect
  the trace afterward? *Recommendation*: Move to GovernedRouter for cleaner
  separation, but this is a medium refactor. Alternative: GovernedRouter runs a
  "preflight check" that calls `CrossConstraintValidator.validate()` directly
  with the snapshot parameters, before calling inner_router.chat().

- **Q-A2**: The `warn`-severity violations (conditional_warning) — should they
  block execution or only warn? Current behavior: they emit trace warnings but
  don't block. The decision field doesn't change this — `warn` violations
  flow to the reply LLM as context but don't prevent `decision=proceed`.

---

## Section 2: Case B — Reverse Dependency Inference

### 2.1 Dialogue Script

**Scenario**: User asks for a downstream analysis result without providing
upstream data. Governance computes the missing dependency chain; the reply LLM
negotiates the prerequisites.

```
Turn 1:
  User:   "我想看 NOx 浓度热点分布"
  Agent:  "要分析 NOx 热点，需要先有路段排放数据和扩散浓度场。
           目前缺少以下上游结果：
           1. 宏观排放计算（需要路网文件，含路段长度、流量、速度）
           2. 扩散模拟（基于排放结果）
           请问您有路网数据文件吗？或者您想先查询 NOx 的排放因子了解基本情况？"

Turn 2:
  User:   "我上传了一个路网文件，帮我分析"
  Agent:  [analyze_file → calculate_macro_emission → calculate_dispersion →
           analyze_hotspots，链式执行后展示热点地图]
```

### 2.2 Step-by-Step LLM Stage 2 Expected Outputs

**Turn 1 Stage 2 output**:

```json
{
  "slots": {
    "pollutants": {"value": ["NOx"], "source": "user", "confidence": 1.0}
  },
  "intent": {"resolved_tool": "analyze_hotspots", "intent_confidence": "high"},
  "chain": ["calculate_macro_emission", "calculate_dispersion", "analyze_hotspots"],
  "stance": {"value": "directive", "confidence": "medium"},
  "missing_required": [],
  "needs_clarification": true,
  "clarification_question": null,
  "decision": {
    "value": "clarify",
    "confidence": 0.80,
    "reasoning": "analyze_hotspots 依赖 dispersion，dispersion 依赖 emission。当前 session 无可用结果，需确认用户是否有路网数据。",
    "clarification_question": "要分析NOx热点，需要先进行排放计算和扩散模拟。请问您有路网数据文件吗？"
  }
}
```

**Key question**: How does the LLM know the dependency chain?

Answer: The user payload includes `tool_graph` — a simplified view of
`TOOL_GRAPH` injected into every Stage 2 call:

```yaml
tool_graph:
  analyze_hotspots:
    requires: [dispersion]
    provides: [hotspot]
    upstream_tools:
      dispersion: calculate_dispersion
      emission: calculate_macro_emission
  calculate_dispersion:
    requires: [emission]
    provides: [dispersion]
  calculate_macro_emission:
    requires: []
    provides: [emission]
    needs_input: "路网文件 (link_length_km, traffic_flow_vph, avg_speed_kph)"
```

This is a **domain context injection**, not a conversational rule. The LLM uses
it to understand that `analyze_hotspots` can't execute without upstream results
and to generate a context-aware clarification question.

**Turn 2 Stage 2 output** (file uploaded, tool chain clear):

```json
{
  "slots": {},
  "intent": {"resolved_tool": "analyze_hotspots", "intent_confidence": "high"},
  "chain": ["calculate_macro_emission", "calculate_dispersion", "analyze_hotspots"],
  "stance": {"value": "directive", "confidence": "high"},
  "missing_required": [],
  "needs_clarification": false,
  "decision": {
    "value": "proceed",
    "confidence": 0.90,
    "reasoning": "用户已上传路网文件，执行链：宏观排放→扩散→热点分析。",
    "clarification_question": null
  }
}
```

### 2.3 What Governance Does at Each Step

**Turn 1**:

1. Stage 2 LLM outputs `decision=clarify` with `chain=[calculate_macro_emission,
   calculate_dispersion, analyze_hotspots]`.
2. `validate_decision()` passes (confidence 0.80 ≥ 0.5, clarify has question).
3. GovernedRouter sees `decision=clarify` — skips inner router entirely.
   Constructs `RouterResponse` with `text=LLM's clarification_question`.
4. Reply parser rewrites for fluency (minimal change — the LLM's question is
   already natural).
5. Execution chain is saved to AO metadata via `ExecutionContinuation` for
   Turn 2 continuation.

**Turn 2**:

1. Stage 2 runs with file_context showing has_file=true.
2. LLM outputs `decision=proceed`.
3. GovernedRouter runs readiness check: `analyze_hotspots` requires
   `dispersion` which requires `emission` which is not yet available.
4. BUT `decision=proceed` with a valid chain means: "execute the chain."
   The chain `[calculate_macro_emission, calculate_dispersion, analyze_hotspots]`
   is passed to the inner router's plan executor.
5. Inner router executes the chain step by step:
   - Step 1: `calculate_macro_emission(pollutants=[NOx], file_path=...)` →
     produces `emission` result token
   - Step 2: `calculate_dispersion(pollutant=NOx)` → reads `emission` from
     context_store → produces `dispersion` result token
   - Step 3: `analyze_hotspots()` → reads `dispersion` from context_store →
     produces `hotspot` result token
6. Governance readiness check runs before EACH step (chain-level gating).

### 2.4 Dependency Graph Injection Design

The `tool_graph` injection is built from existing data in
`core/tool_dependencies.py` and `config/tool_contracts.yaml`:

```python
def _build_tool_graph_for_prompt(tool_name: str | None) -> dict:
    """Build a simplified tool graph for LLM context."""
    from core.tool_dependencies import TOOL_GRAPH, suggest_prerequisite_tool
    graph = {}
    for tname, info in TOOL_GRAPH.items():
        entry = {
            "requires": info.get("requires", []),
            "provides": info.get("provides", []),
        }
        # Add upstream resolution: for each required token, which tool produces it
        entry["upstream_tools"] = {}
        for req in info.get("requires", []):
            upstream = suggest_prerequisite_tool(req)
            if upstream:
                entry["upstream_tools"][req] = upstream
        graph[tname] = entry
    return graph
```

This is injected as a new key `tool_graph` in the Stage 2 user payload. The
system prompt gets a new rule: "如果 intent 指向的工具需要上游结果，检查
tool_graph 判断上游是否已可用，若不可用则在 chain 中包含上游工具。"

### 2.5 Code Change Points

| Change | File:Line | Description |
|--------|-----------|-------------|
| Build `tool_graph` for prompt | `clarification_contract.py:662-681` | Add `tool_graph` key from `_build_tool_graph_for_prompt()` |
| Same for split contracts | `split_contract_utils.py:40-59` | Same |
| Inject `tool_graph` awareness into system prompt | `clarification_contract.py:692-713` | New rule: tool dependency awareness |
| Same for compact prompt | `split_contract_utils.py:17-27` | Same rule in compact form |
| GovernedRouter: chain execution | `governed_router.py:130-143` | When `decision=proceed` and chain is present, pass chain to inner router plan executor |

### 2.6 Uncertainties / Needs Human Review

- **Q-B1**: The tool graph injection adds ~1-2KB to the Stage 2 prompt. For
  simple factor queries that don't need it, this is wasted tokens. Should we
  make it conditional (only inject when tool is downstream of a chain) or
  always include? *Recommendation*: Always include — the cost is small relative
  to the benefit of the LLM understanding the tool ecosystem.

- **Q-B2**: When the LLM outputs `decision=proceed` with a multi-step chain,
  should governance always execute the full chain, or execute step 1 and
  re-evaluate? *Recommendation*: Execute step 1, then re-run LLM (or contract)
  for step 2. This is the existing plan-executor behavior and is safer.

---

## Section 3: Case C — Natural Language Multi-Turn Clarification

### 3.1 Task: e2e_codeswitch_161

**Task definition** (from `evaluation/benchmarks/end2end_tasks.jsonl:161`):
```json
{
  "id": "e2e_codeswitch_161",
  "user_message": "查 passenger car 的 NOx 排放银子",
  "expected_tool": "query_emission_factors",
  "expected_params": {"vehicle_type": "Passenger Car", "pollutants": ["NOx"]}
}
```

**Today's failure**: L3 optional probe over-triggering. Required slots
(vehicle_type, pollutants) are filled but governance probes `model_year` because
it has no declarative YAML default. In single-turn eval, this blocks execution.

**New architecture trace**:

```
Turn 1: "查 passenger car 的 NOx 排放银子"

  Stage 1 (regex):
    - vehicle_type: not extracted (regex may not catch "passenger car" in mixed script)
    - pollutants: "NOx" → ["NOx"] (regex catches "NOx")
    → filled: [pollutants], missing required: [vehicle_type]

  Stage 2 (LLM):
    Input payload includes:
      - user_message: "查 passenger car 的 NOx 排放银子"
      - tool_slots.required_slots: [vehicle_type, pollutants]
      - tool_slots.defaults: {season: "夏季", road_type: "快速路"}  ← YAML defaults
      - runtime_defaults: {model_year: 2020}                         ← NEW: runtime defaults
      - legal_values.vehicle_type: [Passenger Car, Transit Bus, ...]
      - prior_violations: []                                         ← NEW

    LLM output:
    {
      "slots": {
        "vehicle_type": {"value": "Passenger Car", "source": "inferred", "confidence": 0.88, "raw_text": "passenger car"},
        "pollutants": {"value": ["NOx"], "source": "user", "confidence": 1.0, "raw_text": "NOx"},
        "model_year": {"value": null, "source": "missing", "confidence": 0.0}
      },
      "intent": {"resolved_tool": "query_emission_factors", "intent_confidence": "high"},
      "stance": {"value": "directive", "confidence": "high"},
      "missing_required": [],
      "needs_clarification": false,
      "decision": {
        "value": "proceed",
        "confidence": 0.90,
        "reasoning": "Passenger Car→标准车型，NOx→标准污染物，排放因子查询可执行。model_year有默认值2020。",
        "clarification_question": null
      }
    }

  Governance:
    - validate_decision() → passes (value=proceed, confidence=0.90≥0.5, no missing_required)
    - cross_constraint preflight → no violations (Passenger Car + NOx OK)
    - readiness → query_emission_factors has no prerequisites → READY
    - runtime defaults: model_year=2020 injected
    → Execution proceeds ✓
    → Tool runs: query_emission_factors(vehicle_type="Passenger Car", pollutants=["NOx"], model_year=2020, season="夏季", road_type="快速路")
    → e2e_codeswitch_161 PASSES ✓
```

**Critical enabler**: `runtime_defaults` injection into Stage 2 payload. Without
it, the LLM doesn't know model_year has a default and will output
`decision=clarify` to ask for the year. With TASK-1 already providing this
default at runtime, the Stage 2 prompt must be informed of it.

### 3.2 Task: e2e_colloquial_141

**Task definition** (from `evaluation/benchmarks/end2end_tasks.jsonl:141`):
```json
{
  "id": "e2e_colloquial_141",
  "user_message": "家里那种四门小车NOx排放因子",
  "expected_tool": "query_emission_factors",
  "expected_params": {"vehicle_type": "Passenger Car", "pollutants": ["NOx"]}
}
```

**Today's failure**: L4 stage pipeline data flow loss. "家里那种四门小车" is
normalized to "Passenger Car" in Stage 3, but the normalized value doesn't flow
back into the filled-slot snapshot that downstream readiness reads.

**New architecture trace**:

```
Turn 1: "家里那种四门小车NOx排放因子"

  Stage 1 (regex):
    - vehicle_type: "四门小车" extracted (regex partial match?)
    - pollutants: "NOx" → ["NOx"]
    → vehicle_type source=user, confidence=1.0 ← this is the §3.3.2 issue

  Stage 2 (LLM):
    LLM sees existing_parameter_snapshot with vehicle_type="四门小车" (regex-extracted).
    LLM outputs:
    {
      "slots": {
        "vehicle_type": {"value": "Passenger Car", "source": "inferred", "confidence": 0.82, "raw_text": "家里那种四门小车"},
        "pollutants": {"value": ["NOx"], "source": "user", "confidence": 1.0, "raw_text": "NOx"}
      },
      "intent": {"resolved_tool": "query_emission_factors", "intent_confidence": "high"},
      "stance": {"value": "directive", "confidence": "high"},
      "missing_required": [],
      "needs_clarification": false,
      "decision": {
        "value": "proceed",
        "confidence": 0.82,
        "reasoning": "'四门小车'在中文语境下映射为Passenger Car，所有必需参数已补齐。",
        "clarification_question": null
      }
    }

  Stage 3 (standardization):
    - vehicle_type: "Passenger Car" → already canon (passes legal-value check)
    - pollutants: ["NOx"] → already canon
    → normalizations: [vehicle_type: "四门小车" → "Passenger Car" via LLM inference]
    → no rejections

  Governance:
    - decision=proceed → validate → pass → execute
    → e2e_colloquial_141 PASSES ✓
```

**Key enabler**: The LLM does the colloquial→standard mapping in Stage 2 itself
(per existing rule 3: "口语化车型可标准化"). Stage 3 confirms it's a legal value.
The critical TASK-5 fix ensures that the LLM-normalized value in the snapshot
is the one read by readiness and direct-execution argument construction —
not the Stage 1 regex value.

### 3.3 Task: e2e_clarification_101

**Task definition** (from `evaluation/benchmarks/end2end_tasks.jsonl:101`):
```json
{
  "id": "e2e_clarification_101",
  "user_message": "帮我查一下排放因子",
  "follow_up_messages": ["乘用车", "NOx", "2022年"],
  "expected_tool": "query_emission_factors",
  "expected_params": {"vehicle_type": "Passenger Car", "pollutants": ["NOx"], "model_year": "2022"}
}
```

**Today's failure**: L2 turn classification misjudgment. All 4 turns classified
as REVISION, `query_emission_factors` called 4 times with identical (empty) params.

**New architecture trace (4 turns)**:

```
--- Turn 1: "帮我查一下排放因子" ---

  AOClassifier (LLM Layer 2 only, rule layer deleted per TASK-3):
    → NEW_AO (confidence 0.85) ← first message, no active AO

  Stage 2 LLM:
    {
      "slots": {
        "vehicle_type": {"value": null, "source": "missing", "confidence": 0.0},
        "pollutants": {"value": null, "source": "missing", "confidence": 0.0}
      },
      "intent": {"resolved_tool": "query_emission_factors", "intent_confidence": "high"},
      "stance": {"value": "directive", "confidence": "medium"},
      "missing_required": ["vehicle_type", "pollutants"],
      "needs_clarification": true,
      "clarification_question": "请问您需要查询哪种车型和哪些污染物的排放因子？",
      "decision": {
        "value": "clarify",
        "confidence": 0.95,
        "reasoning": "排放因子查询需要车型和污染物，用户尚未指定。",
        "clarification_question": "请问您需要查询哪种车型和哪些污染物的排放因子？"
      }
    }
  Governance: decision=clarify → reply LLM generates question (or uses LLM's own)
  Agent: "请问您需要查询哪种车型和哪些污染物的排放因子？"
  → Contract marks pending with missing_slots=[vehicle_type, pollutants]

--- Turn 2: "乘用车" ---

  AOClassifier (LLM Layer 2):
    → CONTINUATION (confidence 0.88) ← recognizes short reply to pending clarification
    The LLM sees: turn 1 agent asked about vehicle+pollutant, user replied with vehicle type

  Stage 2 LLM:
    {
      "slots": {
        "vehicle_type": {"value": "Passenger Car", "source": "user", "confidence": 0.90, "raw_text": "乘用车"},
        "pollutants": {"value": null, "source": "missing", "confidence": 0.0}
      },
      "intent": {"resolved_tool": "query_emission_factors", "intent_confidence": "high"},
      "stance": {"value": "directive", "confidence": "high"},
      "missing_required": ["pollutants"],
      "needs_clarification": true,
      "clarification_question": "请问您需要查询哪些污染物？例如 CO2、NOx、PM2.5。",
      "decision": {
        "value": "clarify",
        "confidence": 0.92,
        "reasoning": "车型已确认为Passenger Car，污染物仍缺失。",
        "clarification_question": "请问您需要查询哪些污染物？例如 CO2、NOx、PM2.5。"
      }
    }
  Agent: "请问您需要查询哪些污染物？例如 CO2、NOx、PM2.5。"

--- Turn 3: "NOx" ---

  AOClassifier (LLM Layer 2):
    → CONTINUATION (confidence 0.85) ← pollutant reply to clarification

  Stage 2 LLM:
    {
      "slots": {
        "vehicle_type": {"value": "Passenger Car", "source": "prior_context", "confidence": 0.90},
        "pollutants": {"value": ["NOx"], "source": "user", "confidence": 1.0, "raw_text": "NOx"},
        "model_year": {"value": null, "source": "missing", "confidence": 0.0}
      },
      "intent": {"resolved_tool": "query_emission_factors", "intent_confidence": "high"},
      "stance": {"value": "directive", "confidence": "high"},
      "missing_required": [],
      "needs_clarification": false,
      "decision": {
        "value": "proceed",
        "confidence": 0.78,
        "reasoning": "所有必需参数已齐，model_year可使用默认值2020。",
        "clarification_question": null
      }
    }
  Governance: decision=proceed → execute with model_year=2020
  → But wait: the benchmark expects model_year=2022!

  *** DESIGN TENSION DETECTED ***
  TASK-1 says "fresh factor queries with runtime default should proceed."
  But the benchmark follow-ups include "2022年" on Turn 4.
  If we proceed on Turn 3 with model_year=2020, Turn 4 would be a REVISION
  ("改成2022年再算一次") — a different execution path.

  Resolution: This depends on TASK-1's scope. If TASK-1 makes model_year
  unconditional for fresh factor queries, then Turn 3 proceeds with 2020
  and Turn 4 is a revision. If TASK-1's scope is narrower (e.g., only when
  no confirm-first signal), then the LLM's decision=proceed at confidence
  0.78 might trigger the F1 fallback (threshold 0.5 passes, but the LLM
  is uncertain). This is a benchmark expectation question — see §3.4.

--- Turn 4 (if Turn 3 didn't proceed): "2022年" ---

  AOClassifier (LLM Layer 2):
    → CONTINUATION (confidence 0.80)

  Stage 2 LLM:
    {
      "slots": {
        "vehicle_type": {"value": "Passenger Car", "source": "prior_context", "confidence": 0.90},
        "pollutants": {"value": ["NOx"], "source": "prior_context", "confidence": 0.95},
        "model_year": {"value": 2022, "source": "user", "confidence": 1.0, "raw_text": "2022年"}
      },
      "intent": {"resolved_tool": "query_emission_factors", "intent_confidence": "high"},
      "stance": {"value": "directive", "confidence": "high"},
      "missing_required": [],
      "needs_clarification": false,
      "decision": {
        "value": "proceed",
        "confidence": 0.95,
        "reasoning": "所有参数明确，车型+污染物+年份已完整。",
        "clarification_question": null
      }
    }
  → Execute: query_emission_factors(Passenger Car, [NOx], model_year=2022)
  → e2e_clarification_101 PASSES ✓
```

### 3.4 Turn Classification Migration Path

The critical question for Case C turn 2–4 is: *"删了 §3.2.2 AOClassifier rule
layer 之后，turn 类型分类怎么迁移？"*

**Current path** (broken):
```
AOClassifier._rule_layer1()              # §3.2.2: substring matching
  → _is_short_clarification_reply()       # "NOx", "乘用车" → CONTINUATION? REVISION?
  → _detect_revision_target()             # "改成" etc.
  → returns CONTINUATION or REVISION at confidence 0.9-1.0
  → LLM Layer 2 NEVER consulted
```

**New path** (TASK-3):
```
AOClassifier._rule_layer1()              # Retained for STRUCTURALLY CERTAIN cases only:
  → first_message_in_session → NEW_AO     # Keep: structural certainty (no AO exists)
  → pure_file_upload → CONTINUATION       # Keep: structural certainty
  → For ALL other cases: return None      # Fall through to LLM Layer 2

AOClassifier._llm_layer2()               # §3.2.3: LLM always consulted
  → Receives: user_message + last 6 conversation messages + AO summary
  → System prompt (§3.2.2 AO_CLASSIFIER_SYSTEM_PROMPT at ao_classifier.py:72-94):
    "当用户发送新消息时，你需要判断这条消息是 CONTINUATION / REVISION / NEW_AO"
    Already includes guidance:
    - '"NOx"（单独一个词）在有 active AO 等待参数时是 CONTINUATION'
    - '"改成冬季再算"是 REVISION，指向之前的计算 AO'
  → Returns classification + confidence
  → If confidence < 0.7: fallback to NEW_AO (existing fallback, unchanged)
```

For e2e_clarification_101's short replies, the LLM classifier should correctly
identify:
- "乘用车" → CONTINUATION (short reply, active AO, pending clarification)
- "NOx" → CONTINUATION (same reasoning)
- "2022年" → CONTINUATION (same reasoning)

The existing classifier prompt already encodes this logic (ao_classifier.py:73-93).
The fix is purely to stop the rule layer from short-circuiting before the LLM
gets to see the input.

**Transition risk**: More LLM calls per turn (one for classification + one for
Stage 2). Mitigation: the AO classifier call is cheap (~200 tokens prompt,
~50 tokens output) and can potentially be merged with Stage 2 in TASK-6.

### 3.5 Domain Knowledge Injection Required for Case C

For e2e_codeswitch_161 to pass, the Stage 2 LLM needs:

| Knowledge | Source | Injection Method |
|-----------|--------|-----------------|
| model_year has runtime default 2020 | `runtime_defaults.py` + TASK-1 | `runtime_defaults` key in Stage 2 user payload |
| season defaults to 夏季 | `tool_contracts.yaml` → `defaults` | Already in `tool_slots.defaults` |
| road_type defaults to 快速路 | `tool_contracts.yaml` → `defaults` | Already in `tool_slots.defaults` |
| Legal values for vehicle_type | `tool_contracts.yaml` + `unified_mappings.yaml` | Already in `legal_values` |
| Standardization aliases (乘用车→Passenger Car) | `services/standardization_engine.py` | LLM does this via rule 3; Stage 3 confirms |

### 3.6 Code Change Points for Case C

| Change | File:Line | Description |
|--------|-----------|-------------|
| Add `runtime_defaults` to Stage 2 payload | `clarification_contract.py:662-681` | New key: `runtime_defaults: {model_year: 2020}` for factor queries |
| Same for split contracts | `split_contract_utils.py:40-59` | Same |
| Delete short-circuit rules from AOClassifier | `ao_classifier.py:202-269` | Remove `_is_short_clarification_reply` and `_detect_revision_target` branches; keep only first-message and file-upload structural rules |
| Lower AO classifier confidence threshold (optional) | `ao_classifier.py:154-158` | Consider lowering from 0.7 → 0.5 for multi-turn clarification, matching decision field threshold |
| TASK-5 snapshot fix | `clarification_contract.py:879-948, :1307-1342` | Ensure LLM-normalized values (not regex Stage 1 values) flow to downstream readiness and execution |

### 3.7 Uncertainties / Needs Human Review

- **Q-C1 (RESOLVED)**: The benchmark expects Turn 4 to provide model_year=2022, but TASK-1
  says proceed with default 2020 on Turn 3. This was initially described as a "design tension"
  but is actually a false tension. The benchmark measures whether the agent eventually calls
  the tool with correct parameters — not which turn it proceeds on. Two valid paths exist:

  **Path (i) — Proceed with default, then revise** (recommended, LLM-deferential):
  Turn 3: LLM outputs `decision=proceed` with model_year=2020 → tool executes →
  reply LLM transparently shows "已查询 Passenger Car NOx 2020 年排放因子。如果您需要其他年份，请告诉我。"
  Turn 4: User says "2022年" → AOClassifier → REVISION → Stage 2 re-runs with model_year=2022 →
  tool executes with correct params → benchmark passes ✓

  **Path (ii) — Clarify, then proceed**:
  Turn 3: LLM outputs `decision=clarify` asking for model_year →
  Turn 4: User provides "2022年" → `decision=proceed` with model_year=2022 →
  tool executes → benchmark passes ✓

  Both paths achieve model_year=2022 in the final tool call. Path (i) is the better product
  behavior: the agent is proactive (executes immediately with a reasonable default) and
  revisable (user can correct with a short follow-up). Path (ii) adds an unnecessary
  round-trip for a parameter that has a valid default.

  **No additional confidence threshold is needed.** The LLM's `decision.confidence ≥ 0.5`
  is sufficient. Adding a 0.85 threshold for optional-defaults would be the same anti-pattern
  identified in audit §3.2.3 (governance overriding LLM judgment with a magic number).
  If the LLM outputs `proceed` at confidence 0.78, governance respects it.
  The F1 safety net (confidence < 0.5) already handles genuinely uncertain cases.

  **Reply LLM default-transparency rule**: When a tool executes with a runtime default value,
  the reply LLM prompt must include a rule: "If any parameter used a default value (listed in
  runtime_defaults_injected), explicitly state what default was used and invite the user to
  revise. Example: '已查询 Passenger Car NOx 2020 年排放因子。如果您需要其他年份，请告诉我。'"
  This transparency belongs to the reply LLM's prompt design, not to governance.

- **Q-C2**: The AOClassifier LLM call adds latency. Can we batch the
  classification and Stage 2 LLM calls? *Recommendation*: Not in Step 2A.
  Defer batching to TASK-6 (Step 2B).

---

## Section 4: Case D — Cross-Turn Constraint Feedback

### 4.1 Dialogue Script

**Scenario**: A violation from Turn 2 should still be visible in Turn 4, so the
LLM can reference it when the user finally addresses it.

```
Turn 1:
  User:   "查 Motorcycle 高速上的 CO2 排放因子"
  Agent:  "摩托车不允许在高速公路上行驶。请选择地面道路或快速路。"

Turn 2:
  User:   "那先不查了，帮我看看排放标准里 CO2 的限值"
  Agent:  [query_knowledge(query="CO2 emission standards")] → 返回标准信息

Turn 3:
  User:   "基于刚才的查询结果…" [继续讨论标准]

Turn 4:
  User:   "现在帮我用地面道路重新查 Motorcycle 的 CO2 排放因子"
  Agent:  "好的，为您查询 Motorcycle 在地面道路上的 CO2 排放因子。"
          [执行 query_emission_factors(Motorcycle, [CO2], road_type=地面道路)]
```

**Key requirement**: In Turn 4, the LLM should remember the Turn 1 violation
(Motorcycle + 高速公路 blocked) and understand that the user has corrected it
(地面道路 instead of 高速). The violation from Turn 1 must still be accessible.

### 4.2 Violation Lifecycle — Current State vs. Needed

**Current state** (partially works):

```
Turn 1:
  ConstraintViolationWriter.record(violation)
    → current_ao.constraint_violations = [violation_record]
    → context_store._latest_constraint_violations = [violation_record]
  
Turn 2 (NEW_AO or REVISION):
  If turn 2 creates a NEW_AO: the previous AO is completed/abandoned.
    → get_latest() returns NEW AO's violations → EMPTY (violation lost!)
  If turn 2 is CONTINUATION: the same AO is active.
    → get_latest() returns the same AO's violations → OK (violation persists)
```

**The gap**: If Turn 2 starts a new AO (e.g., knowledge query after a failed
factor query), the violation from Turn 1 is scoped to the old AO and lost.

Moreover, when an AO is completed, violations go into the AO's history but are
not queryable by `get_latest()` which only returns the *current* AO's violations.

**Needed behavior**: Violations should persist across AO boundaries within the
same session, at least as context for the LLM. The LLM should see "the user tried
Motorcycle + 高速公路 earlier and it was rejected" even if the current AO is
different.

### 4.3 Cross-Turn Violation Visibility Design

**Option A** (minimal, Step 2A): Keep AO-scoped violations but add a
`session_violation_log` that accumulates ALL violations across all AOs in the
session. The Stage 2 payload reads from this log, not from `get_latest()`.

**Option B** (full, Step 2B+): Add a `violation_memory` to the working-memory
system that LLM can reference across turns.

I recommend **Option A** for Step 2A because it's a small change to the existing
persistence layer.

**Implementation**:

1. `SessionContextStore` gains a new list: `_session_violation_log: List[Dict]`
   that accumulates ALL violations across ALL AOs (never cleared until session end).

2. `ConstraintViolationWriter.record()` appends to BOTH:
   - `current_ao.constraint_violations` (AO-scoped, existing)
   - `context_store._session_violation_log` (session-scoped, NEW)

3. `SessionContextStore.get_session_violations()` returns the full session log.

4. Stage 2 payload builder reads from `get_session_violations()` (session-scoped)
   instead of `get_latest()` (AO-scoped) for `prior_violations`.

5. `ReplyContextBuilder` continues to use `get_latest()` (AO-scoped) for the
   reply LLM, since the reply is about the current turn/AO.

**Distinction**:
- `prior_violations` in Stage 2 prompt → session-scoped (LLM has full context)
- `violations` in ReplyContext → AO-scoped (reply is about current turn)

### 4.4 Step-by-Step for Case D

```
Turn 4: "现在帮我用地面道路重新查 Motorcycle 的 CO2 排放因子"

  Stage 2 LLM user payload:
    prior_violations:                              ← session-scoped, from get_session_violations()
      - violation_type: "vehicle_road_compatibility"
        severity: "reject"
        involved_params: {vehicle_type: "Motorcycle", road_type: "高速公路"}
        suggested_resolution: "摩托车不允许上高速公路。"
        source_turn: 1
      - violation_type: "vehicle_pollutant_relevance"
        severity: "warn"
        involved_params: {vehicle_type: "Motorcycle", pollutants: "PM2.5"}
        suggested_resolution: "摩托车PM2.5排放数据覆盖有限。"
        source_turn: 3                          ← from a separate attempt

  LLM output:
  {
    "slots": {
      "vehicle_type": {"value": "Motorcycle", "source": "prior_context", "confidence": 0.95},
      "pollutants": {"value": ["CO2"], "source": "user", "confidence": 1.0},
      "road_type": {"value": "地面道路", "source": "user", "confidence": 1.0}
    },
    "intent": {"resolved_tool": "query_emission_factors", "intent_confidence": "high"},
    "stance": {"value": "directive", "confidence": "high"},
    "missing_required": [],
    "needs_clarification": false,
    "decision": {
      "value": "proceed",
      "confidence": 0.92,
      "reasoning": "用户已将道路类型从之前违规的高速公路改为地面道路，Motorcycle+地面道路+CO2组合合法。",
      "clarification_question": null
    }
  }
```

### 4.5 Code Change Points for Case D

| Change | File:Line | Description |
|--------|-----------|-------------|
| Add `_session_violation_log` to SessionContextStore | `core/context_store.py:110` | New list attribute, never cleared until session reset |
| `record()` appends to session log | `core/constraint_violation_writer.py:90-105` | Also write to `context_store._session_violation_log` |
| `get_session_violations()` method | `core/context_store.py` | New method returning full session log |
| Stage 2 reads from session log | `clarification_contract.py:662-681` | `prior_violations` key reads from `get_session_violations()` not `get_latest()` |
| Eval harness: clear session log between tasks | `evaluation/run_oasc_matrix.py` (TASK-2) | Ensure session reset clears `_session_violation_log` |

### 4.6 Uncertainties / Needs Human Review

- **Q-D1**: Should we also inject `prior_violations` into the AO classifier LLM
  prompt? A violation from Turn 1 might help the classifier understand that
  Turn 4's message is related to the Turn 1 AO. *Recommendation*: Not in Step 2A.
  The classifier works from conversation history, which already contains the
  violation context via the agent's own replies.

- **Q-D2**: How many turns back should violations persist? Session-scoped means
  they persist for the entire session, which could grow large. *Recommendation*:
  Truncate to the last N violations or last M turns (`max_violation_history_turns=10`).

---

## Section 5: Cross-Case Common Requirements

### 5.1 Domain Knowledge Injection Matrix

This table summarizes EVERY piece of domain knowledge the LLM Stage 2 needs,
across all 4 cases:

| # | Knowledge | Source | Needed For | Injection Point | Exists Today? |
|---|-----------|--------|------------|-----------------|---------------|
| K1 | Tool legal values (vehicle types, pollutants, etc.) | `tool_contracts.yaml` + `unified_mappings.yaml` | Case C: colloquial→canonical mapping | Stage 2 payload + ReplyContext.legal_values_for_pending_slots | YES |
| K2 | Tool required/optional slots | `tool_contracts.yaml` | All cases: what's missing | `tool_slots` in payload | YES |
| K3 | Declarative YAML defaults (season=夏季, road_type=快速路) | `tool_contracts.yaml` → `defaults` | Case C: know what's filled | `tool_slots.defaults` in payload | YES |
| K4 | **Runtime defaults** (model_year=2020) | `runtime_defaults.py` / Router | Case C: e2e_codeswitch_161 proceed without asking model_year | `runtime_defaults` in payload | **NO** — must add |
| K5 | **Cross-constraint rules** | `config/cross_constraints.yaml` | Case A: LLM detects conflict proactively? Or governance catches it? | Not in LLM prompt (governance-owned) | N/A — governance check |
| K6 | **Tool dependency graph** (requires/provides) | `core/tool_dependencies.py` → `TOOL_GRAPH` | Case B: reverse dependency inference | `tool_graph` in payload | **NO** — must add |
| K7 | **Prior violations** (session-scoped) | `SessionContextStore._session_violation_log` | Case A Turn 2, Case D: correction context | `prior_violations` in payload | **NO** — must add |
| K8 | Available session results (emission/dispersion/hotspot) | `SessionContextStore` / context | Case B: check if prerequisites already available | `available_results` in payload | PARTIAL — file_context only |
| K9 | AO history summary (previous objectives + outcomes) | `AOManager.get_all_aos()` | Case D: cross-AO context | `ao_history` in payload | PARTIAL — only current_ao_id |

**Three new injections** (K4, K6, K7) and one expanded injection (K8) are needed
to make all four cases work. K5 (cross-constraint rules) remains governance-owned
and is NOT injected into the LLM prompt — this is the key separation.

**K1 Dual Injection Note**: K1 has dual injection: Stage 2 needs legal values for slot
validation; reply LLM needs them to reference enum values legitimately. Without
ReplyContext injection, reply LLM falls back to training knowledge (e.g. listing
model_year 1995–2025 from MOVES general knowledge), which violates HARD RULE (b)
(no facts outside ReplyContext). The ReplyContext field
`legal_values_for_pending_slots` carries the same legal-value definitions that
Stage 2 sees, keyed by slot name, so the reply LLM can cite authorized enum ranges
without fabricating or inferring them.

#### 5.1.1 Why K5 Is Governance-Owned, Not LLM-Injected

This is a locked design principle for Phase 3:

> Domain rules (cross-constraint, readiness) are NOT injected into the LLM prompt
> because they are governance's territory. Governance checks for violations and
> feeds back to the LLM via the ConstraintViolation closed loop — the LLM sees
> *which specific rule was violated*, not *that the rules exist in advance*.
> This division implements the "rule detection + LLM response" design philosophy
> from the architecture outline (§4.3.2): the LLM does not need to memorize all
> domain rules, and governance is not overridden by the LLM.

**Rationale**:

1. **Separation of concerns**: Cross-constraint rules are domain physics
   (vehicle/road compatibility, vehicle/pollutant relevance, pollutant/task
   applicability, season/meteorology consistency). Governance owns domain physics.
   The LLM owns conversational pragmatics.

2. **Single source of truth**: Constraint rules live in `config/cross_constraints.yaml`.
   If injected into the LLM prompt, the rules would exist in two places (YAML config
   and prompt text) and could diverge.

3. **Closed-loop feedback is sufficient**: When a violation occurs, governance
   constructs a `ViolationRecord` with the violation type, severity, involved
   parameters, and suggested resolution. This record is injected into the NEXT
   turn's Stage 2 payload via `prior_violations` (K7). The LLM sees exactly what
   went wrong and can respond accordingly — it doesn't need to know the rules
   proactively.

4. **Prevents hallucinated constraint enforcement**: If the LLM knew all constraint
   rules, it might hallucinate violations that don't exist or misinterpret rule
   scope. Governance's deterministic check is the authoritative source.

**What the LLM sees (correct)**:
```yaml
prior_violations:
  - violation_type: "vehicle_road_compatibility"
    severity: "reject"
    involved_params: {vehicle_type: "Motorcycle", road_type: "高速公路"}
    suggested_resolution: "摩托车不允许上高速公路。可选道路类型: 快速路, 地面道路, 主干路。"
```

**What the LLM does NOT see (correct)**:
```yaml
# NOT injected — governance-owned
cross_constraint_rules:
  - name: vehicle_road_compatibility
    rule: "Motorcycle + 高速公路 → blocked"
```

Any future proposal to inject K5 into the LLM prompt must explicitly challenge this
principle and demonstrate why the closed-loop violation feedback is insufficient.

### 5.2 Unified GovernedRouter Consumption Architecture

Across all 4 cases, the GovernedRouter flow converges to a single pattern:

```
                  ┌──────────────────────────────┐
                  │   Stage 2 LLM (enriched)     │
                  │   payload includes:           │
                  │   - runtime_defaults (K4)     │
                  │   - tool_graph (K6)           │
                  │   - prior_violations (K7)     │
                  │   - available_results (K8)    │
                  │   outputs: decision field     │
                  └──────────────┬───────────────┘
                                 │
                    validate_decision()
                     (3.1 rules + F1 fallback)
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
        decision=proceed   decision=clarify   decision=deliberate
              │                  │                  │
    ┌─────────┴─────────┐       │           ┌──────┴──────┐
    │ cross_constraint  │    Use LLM's      │ Use LLM's   │
    │ preflight         │    question as    │ reasoning   │
    │ (K5, gov-owned)   │    response       │ as advice   │
    │  ↓                │    (skips inner   │ (skips tool │
    │ readiness check   │     router)       │  execution) │
    │ (K6, gov-owned)   │                   │             │
    │  ↓                │                   │             │
    │ PASS → execute    │                   │             │
    │ FAIL → inject     │                   │             │
    │  ViolationRecord  │                   │             │
    │  → reply LLM      │                   │             │
    └───────────────────┘                   └─────────────┘
```

This is the same architecture for all cases. Case A exercises the "FAIL → inject
ViolationRecord" path. Case B exercises the "readiness check" path (dependency
gating). Case C exercises the "decision=clarify" path. Case D exercises the
"prior_violations" injection that feeds the next turn's Stage 2.

### 5.3 Gaps in phase3_decision_field_design.md Identified by Case Analysis

These are the things my previous code-first design document missed:

**Gap 1 — No `runtime_defaults` injection.** The decision field design assumed
the LLM would know about model_year=2020. It doesn't. K4 must be added to the
Stage 2 payload for e2e_codeswitch_161 to pass. This should be part of TASK-1's
scope.

**Gap 2 — No `tool_graph` injection.** The decision field design focused on
conversational judgment (proceed/clarify/deliberate) but didn't address
dependency awareness. For Case B, the LLM needs K6 to understand that
analyze_hotspots can't run without upstream emission/dispersion.

**Gap 3 — No `prior_violations` injection.** The decision field design only
considered the current turn's Stage 2 output. For Case A Turn 2 and Case D,
the LLM needs to see violations from prior turns (K7) to generate coherent
responses and understand parameter corrections.

**Gap 4 — Violation scope was AO-only, not session-scoped.** The previous
design relied on `get_latest()` which returns current-AO violations. Case D
shows this is insufficient when users switch AOs. A session-scoped log is
needed.

**Gap 5 — No `available_results` injection.** For Case B, the LLM needs to
know what results already exist in the session (K8) to decide whether
upstream tools need to run.

**Gap 6 — Turn classification migration not addressed.** The previous design
deferred TASK-3 to Step 2A but didn't specify how the AOClassifier rule layer
deletion interacts with the decision field. Case C shows that turn
classification and the decision field are independent concerns: the classifier
determines AO lifecycle (CONTINUATION/REVISION/NEW_AO), the decision field
determines conversational action (proceed/clarify/deliberate). Both need the
LLM, but they serve different purposes.

**Gap 7 — `decision=proceed` with optional-defaults clarity (RESOLVED).** Case C Turn 3
shows `decision=proceed` at confidence 0.78 when an optional slot has a runtime default.
This is NOT ambiguous under the LLM-deferential principle: if the LLM says proceed,
governance proceeds. The F1 safety net (confidence < 0.5) is the only threshold.
The reply LLM handles transparency by stating what default was used and inviting revision
(see §3.7 Q-C1 resolution).

---

## Section 6: Phase 3.1 Implementation Order (Revised per F3)

The implementation is organized into 5 steps. Each step is independently smoke-tested
to verify baseline changes before proceeding. High-risk large atomic changes are avoided.

---

### Step 0: TASK-8 — Replace Hardcoded Governance Text with LLM Generation

- **Type**: Independent (can run and ship alone).
- **Entry prerequisite**: None (works on current `phase3-governance-reset` branch).
- **Exit verification**: Run full smoke matrix. No baseline regression expected
  (text quality change only). Verify reply text is fluent Chinese and contains all
  structured facts from `ReplyContext`.
- **Effort**: M.
- **Risk**: Low/Medium — reply LLM may occasionally omit domain-precise wording.

**Scope**: Governance stops writing user-facing Chinese text directly. Instead,
governance provides structured reason, missing slot, and domain constraint data;
the reply LLM produces the user-facing text.

#### 6.0.1 Hardcoded Text Inventory → LLM Generation Blueprint

Each row is a concrete implementation target for Step 0.

| # | Site | File:Line | Current Hardcoded Text | Target: Structured Context for Reply LLM |
|---|------|-----------|----------------------|------------------------------------------|
| H1 | Intent unresolved fallback | `intent_resolution_contract.py:116-131` | `"请先说明您想执行哪类交通排放分析：排放因子查询、微观排放、宏观排放或知识库问答。"` | Inject `intent_unresolved: true` + `available_tools: [query_emission_factors, calculate_micro_emission, calculate_macro_emission, query_knowledge]` into ReplyContext. Reply LLM generates context-appropriate guidance. |
| H2 | Exploratory hardcoded clarify | `execution_readiness_contract.py:313-346` | `"您想先比较哪类交通排放分析目标？可以指定排放因子、微观排放、宏观排放或扩散影响。"` | Inject `stance: "exploratory"` + `missing_context: "用户未指定具体分析目标"` + `available_capabilities: [...]` into ReplyContext. Reply LLM generates exploratory framing. |
| H3 | Generic missing-parameter prompt | `clarification_contract.py:405-422` (inside question-vs-proceed tree) | Constructed from `_build_question()` template: `f"请提供{slot_label}…"` | Replace `_build_question()` hardcoded templates with structured `pending_clarifications: [{slot, label, tool, examples}]` in ReplyContext. Reply LLM generates natural question. |
| H4 | Probe question fallback | `clarification_contract.py:1026-1044` (`_build_probe_question()` fallback) | Template-based probe fallback when LLM probe generation fails | Already has LLM-backed path (`_run_probe_question_llm()` at :1046-1082). Remove the hardcoded fallback template; on LLM failure, use `pending_clarifications` via ReplyContext. |
| H5 | Cross-constraint violation message | `router.py:2268-2276` | `f"参数组合不合法: {violation.reason}。建议: {violation.suggestion}"` | Already covered by Case A design: governance emits `ViolationRecord` to trace; `ReplyContextBuilder` already reads violations; the hardcoded f-string is replaced by letting the reply LLM generate text from `ReplyContext.violations`. |
| H6 | Intent short-circuit text (continuation-state) | `intent_resolution_contract.py:36-58` | Implicit: continuation-state hardcodes intent without LLM | Inject `continuation_state: {objective, pending_slots, prior_tool}` into ReplyContext instead of hardcoding intent. Reply LLM generates continuation-aware text. |

**Design rule for all H1-H6**: Governance writes to `ReplyContext` (structured facts).
Reply LLM writes user-facing text. Governance NEVER constructs a user-visible string directly.

---

### Step 1: Knowledge Injection + Decision Field (Atomic)

- **Type**: **Atomic** — must be implemented as one unit. Individual sub-steps cannot
  be validated independently because knowledge injection without the decision field
  gives the LLM information it cannot act on, and the decision field without knowledge
  injection starves the LLM of the facts needed to make correct decisions.
- **Entry prerequisite**: Step 0 complete (ReplyContext structure must be in place
  for the reply LLM to handle `decision=clarify` and violation text generation).
- **Exit verification**: All 4 cases (A/B/C/D) pass in manual trace mode with
  `enable_llm_decision_field=True`. Run full smoke matrix with feature flag ON and
  OFF; compare baseline deltas. Expected impact: +5 to +12 pp across L2/L3/L4
  failure categories.
- **Effort**: L (combined scope of old Step 1 + Step 2A).
- **Risk**: High if not atomic; Medium if atomic with feature flag gating.

#### 6.2.1 Knowledge Injection Sub-steps (from old Step 1)

| # | Description | K# | Files | Effort |
|---|-------------|----|-------|--------|
| 1.1 | Add `runtime_defaults` to Stage 2 user payload | K4 | `clarification_contract.py:662-681`, `split_contract_utils.py:40-59` | S |
| 1.2 | Build `_build_tool_graph_for_prompt()` helper; add `tool_graph` to Stage 2 payload | K6 | Same files + new helper function | S |
| 1.3 | Add `_session_violation_log: List[Dict]` to `SessionContextStore` | K7 | `core/context_store.py:110` | S |
| 1.4 | `ConstraintViolationWriter.record()` appends to `_session_violation_log` | K7 | `core/constraint_violation_writer.py:90-105` | S |
| 1.5 | Add `get_session_violations()` method; inject `prior_violations` into Stage 2 payload | K7 | `core/context_store.py`, `clarification_contract.py:662-681`, `split_contract_utils.py:40-59` | S |
| 1.6 | Add `available_results` (emission/dispersion/hotspot tokens from context_store) to Stage 2 payload | K8 | Same Stage 2 payload files | S |
| 1.7 | Update both Stage 2 system prompts to reference new payload keys (`runtime_defaults`, `tool_graph`, `prior_violations`, `available_results`) | — | `clarification_contract.py:692-713`, `split_contract_utils.py:17-27` | S |
| 1.7a | Inject K1 (`legal_values`) into ReplyContext.legal_values_for_pending_slots (dual-injection: Stage 2 + reply LLM) | K1 | `core/reply/reply_context.py`, `core/reply/reply_context_builder.py` | S |

#### 6.2.2 Decision Field Sub-steps (from old Step 2A, minus deleted 2a-9)

| # | Description | TASK | Files | Effort |
|---|-------------|------|-------|--------|
| 1.8 | Add `decision` field rule to both Stage 2 system prompts (output schema: `{value, confidence, reasoning, clarification_question}`) | — | `clarification_contract.py:692-713`, `split_contract_utils.py:17-27` | S |
| 1.9 | Create `config/decision_few_shot_examples.yaml` with 7 few-shot examples (proceed/clarify/deliberate); inject into Stage 2 user payload | — | New YAML file + Stage 2 payload builders | S |
| 1.10 | Implement `validate_decision()` with 5 F1 safety-net rules (schema check, confidence ≥ 0.5, missing_required → clarify, clarify requires question, deliberative requires reasoning); on validation failure, fall back to existing hard-rule path | — | New function in `clarification_contract.py` or `core/contracts/decision_validator.py` | S |
| 1.11 | GovernedRouter: read `decision` from Stage 2 output; route to three branches (proceed → inner router, clarify → skip execution + reply, deliberate → skip execution + reply) | — | `governed_router.py:130-143`, `:355-408` (snapshot guard bypassed when decision≠proceed) | M |
| 1.12 | Contract consumption: replace 9 hard-rule governance decision sites with `decision` reads | — | `intent_resolution_contract.py:116-131`, `execution_readiness_contract.py:313-346, :348-429, :177-225`, `clarification_contract.py:354-439` | M |
| 1.13 | Add feature flag `enable_llm_decision_field` (default `False`) to `config.py` | — | `config.py` | S |
| 1.14 | Eval harness: clear `_session_violation_log` between tasks, reset AO state fully (TASK-2) | — | `evaluation/run_oasc_matrix.py:174-181`, `evaluation/eval_end2end.py:1273-1300` | M |

#### 6.2.3 Why This Step Must Be Atomic

Splitting Step 1 into "knowledge injection first, decision field later" (or vice
versa) produces an unverifiable intermediate state:

- **Knowledge without decision field**: The LLM sees `tool_graph`, `runtime_defaults`,
  and `prior_violations` but cannot express "proceed because model_year has a default"
  or "clarify because dependencies are missing." The information is present but inert.
  No case passes; smoke shows no delta.
- **Decision field without knowledge**: The LLM can express proceed/clarify/deliberate
  but lacks the facts to make correct decisions. It doesn't know model_year defaults
  to 2020, doesn't know analyze_hotspots requires dispersion, doesn't see prior
  violations. Cases fail with wrong decisions; smoke may regress.
- **Together**: The LLM has both the facts (knowledge injection) and the mechanism
  (decision field) to act on them. All 4 cases can pass.

The feature flag (`enable_llm_decision_field=False` by default) gates the entire
atomic unit. When OFF, the system falls through to existing hard-rule paths unchanged.

---

### Step 2: Decision Field Recalibration + LLM-First Classification (EXPANDED SCOPE)

**Step 2 scope expanded based on Step 1 dual smoke evidence (2026-04-27).** Decision field
implementation is complete (Step 1.B) but disabled by default due to fast-model
calibration insufficiency: qwen-turbo-latest over-clarifies on simple directive
tasks, causing -6.67pp regression on 30-task smoke when enabled
(ON=80.00% vs OFF=86.67%).

Step 2 must address this jointly with TASK-3 (AOClassifier LLM-first):
- Both AOClassifier and Stage 2 decision field require reasoning model capacity
  (qwen3-max), not fast model
- Consolidate into single per-turn LLM call producing both turn classification
  AND execution decision (slots/intent/stance/decision in one output)
- This is a step toward TASK-6 (Stage 2 axis separation) but motivated by
  calibration evidence rather than pure refactor

- **Type**: Independent (can run and ship after Step 1.B baseline is understood).
- **Entry prerequisite**: Step 1.A committed (knowledge injection proven +10pp);
  Step 1.B committed but disabled.
- **Exit verification**: Dual smoke (30-task + 11-task); ON >= OFF. Multi-turn
  clarification smoke passes. No regression in single-turn directive tasks.
- **Effort**: L (expanded from original M+M).
- **Risk**: Medium-High — model switch increases latency; consolidated LLM call
  changes prompt architecture.

#### 6.3.1 Model Switch + Prompt Consolidation (NEW)

| # | Description | Files | Effort |
|---|-------------|-------|--------|
| 2.1 | Switch AOClassifier LLM layer and Stage 2 LLM from fast model (qwen-turbo-latest) to reasoning model (qwen3-max) | `core/ao_classifier.py`, `core/contracts/clarification_contract.py`, `core/contracts/split_contract_utils.py` | M |
| 2.2 | Consolidate AOClassifier + Stage 2 into single LLM call: one prompt producing turn classification (AO action, classification, confidence) + execution decision (slots, intent, stance, decision) in unified output | `core/ao_classifier.py`, `core/contracts/clarification_contract.py` | L |
| 2.3 | Re-enable decision field: set `enable_llm_decision_field` default to `true` | `config.py` | S |

#### 6.3.2 TASK-3 Remnant: Rule Layer Simplification

| # | Description | Files | Effort |
|---|-------------|-------|--------|
| 2.4 | Delete `_is_short_clarification_reply` and `_detect_revision_target` branches from `_rule_layer1()`; keep only structural rules (`first_message_in_session → NEW_AO`, `pure_file_upload → CONTINUATION`) | `core/ao_classifier.py:202-269` | M |
| 2.5 | For all other cases, `_rule_layer1()` returns `None` → falls through to LLM (now unified call from 2.2) | `core/ao_classifier.py:283-289` | S |
| 2.6 | Lower AO classifier confidence fallback threshold from 0.7 → 0.5 | `core/ao_classifier.py:154-158` | S |

#### 6.3.3 TASK-4 Partial: Substring Matchers → Advisory

| # | Description | Files | Effort |
|---|-------------|-------|--------|
| 2.7 | `_detect_confirm_first()`: log match result as trace evidence; LLM stance/intent leads | `core/contracts/clarification_contract.py:1447-1508` | M |
| 2.8 | `has_reversal_marker()`: log match result; LLM classification leads | `core/continuation_signals.py:4-37` | S |
| 2.9 | `has_probe_abandon_marker()`: log match result; LLM decision leads | `core/contracts/stance_resolution_contract.py:32-52` | S |
| 2.10 | Add arbitration function: when substring and LLM disagree, log the disagreement + LLM wins (unless domain-hard constraint applies) | New helper in `clarification_contract.py` | S |

#### 6.3.4 Verification

| # | Description | Effort |
|---|-------------|--------|
| 2.11 | Repeat dual smoke (30-task + 11-task); expect ON >= OFF on 30-task completion | S |
| 2.12 | Add unit tests: short pollutant reply, `重新查询`, `改成冬季`, file-only supplement classified correctly by unified LLM call | `tests/test_ao_classifier.py` | S |

---

### Step 3: TASK-6 — Separate Stage 2 Axes (High Risk, Deferred)

- **Type**: Independent (can run and ship after Step 2 baseline is proven).
- **Entry prerequisite**: Step 2 baseline stable for 7+ days AND all 4 cases
  (A/B/C/D) passing consistently in smoke. This precondition is non-negotiable
  because TASK-6 is the highest blast-radius change in Phase 3.
- **Exit verification**: Full smoke matrix. Malformed/missing `intent`, `stance`,
  or `slots` must fail independently without corrupting other axes. No correlated
  multi-axis failures (P1 pattern eliminated).
- **Effort**: L.
- **Risk**: High — increases latency and prompt cost; changes production
  clarification behavior.

| # | Description | Effort |
|---|-------------|--------|
| 3.1 | Option A (preferred): Keep one Stage 2 call but add independent per-axis validation with separate confidence thresholds | L |
| 3.2 | Option B: Split into 3 separate LLM calls (slots, intent, stance) with independent prompts | L |
| 3.3 | Remove `needs_clarification` top-level field from Stage 2 output (superseded by `decision.value = clarify`) | S |

---

### Step 4: Cleanup + Magic Constant Extraction

- **Type**: Independent (can run after Step 2 or Step 3).
- **Entry prerequisite**: Step 2 complete (decision field proven stable).
- **Exit verification**: No behavioral change — pure refactor. Smoke unchanged.
- **Effort**: S to M.
- **Risk**: Low (pure refactor, no behavior change).

| # | Description | TASK | Files | Effort |
|---|-------------|------|-------|--------|
| 4.1 | TASK-7: Extract `probe_limit` to single runtime config (`config.py:122-127`); replace all `>= 2` and `probe_limit=2` sites | TASK-7 | `clarification_contract.py:367-385`, `execution_readiness_contract.py:149-150, :227-245, :348-371` | S |
| 4.2 | Remove remaining substring matchers entirely (TASK-4 final) | TASK-4 | `continuation_signals.py`, `clarification_contract.py` | S |
| 4.3 | TASK-9: Add invariant checks before snapshot direct execution; low-confidence snapshots fall back to inner router | TASK-9 | `governed_router.py:355-408, :666-685`, `execution_readiness_contract.py:498-512` | M |
| 4.4 | TASK-11: Reclassify Stage 3 confidence threshold as advisory (low-confidence values become candidates with uncertainty, not silent missing) | TASK-11 | `clarification_contract.py:891-914` | S/M |
| 4.5 | Remove `_run_legacy_loop()` if state loop is proven stable (out of scope — needs separate decision) | — | `core/router.py` | L |

---

### Dependency Graph

```
Step 0 (TASK-8: Hardcoded Text → LLM)
  │  Independent. No dependencies.
  │  Exit: smoke unchanged, text fluent.
  ↓
Step 1.A (Knowledge Injection: K1/K4/K6/K7/K8)
  │  Depends on: Step 0 (ReplyContext structure)
  │  Exit: +10pp over Step 0 (86.67% vs 76.67% on 30-task smoke).
  │  Commit: knowledge injection code, flag default false, harness fixes.
  ↓
Step 1.B (Decision Field: disabled by default)
  │  Depends on: Step 1.A (flag entry, knowledge injection)
  │  Exit: code complete; flag OFF = no regression, flag ON = -6.67pp (known issue).
  │  Commit: decision field code (3-way branch, Q3 gates, F1 validator, few-shot YAML).
  ↓
Step 2 (Decision Recalibration + LLM-First Classification) ← EXPANDED SCOPE
  ├── 2.1-2.3: Model switch (reasoning model), consolidate AO + Stage 2, re-enable decision field
  ├── 2.4-2.6: TASK-3 remnant (rule layer simplification)
  ├── 2.7-2.10: TASK-4 partial (substring → advisory)
  ├── 2.11-2.12: Verification (dual smoke, unit tests)
  │  Depends on: Step 1.A + 1.B
  │  Exit: ON >= OFF; no regression on directive tasks.
  ↓
Step 2 (Decision Recalibration + LLM-First Classification) ← EXPANDED SCOPE
  ├── 2.1-2.3: Model switch + consolidate AO + Stage 2 + re-enable decision field
  ├── 2.4-2.6: TASK-3 remnant (rule layer simplification)
  ├── 2.7-2.10: TASK-4 partial (substring matchers → advisory)
  ├── 2.11-2.12: Verification (dual smoke, unit tests)
  │  Depends on: Step 1.A + 1.B
  │  Exit: ON >= OFF on 30-task; no regression on single-turn directives.
  ↓
Step 3 (TASK-6: Separate Stage 2 Axes)
  │  Depends on: Step 2 baseline stable 7+ days + 4 cases passing
  │  Exit: no correlated multi-axis failures.
  ↓
Step 4 (Cleanup)
  │  Depends on: Step 2 (or Step 3) complete
  │  Exit: smoke unchanged, code cleaner.
```

---

### What Each Case Gets at Each Step

| Case | After Step 0 | After Step 1 | After Step 2 | After Step 3 | After Step 4 |
|------|-------------|-------------|-------------|-------------|-------------|
| A — Constraint conflict | Reply LLM generates violation text from structured ReplyContext (no hardcoded Chinese). | **FULL** — Stage 2 sees prior_violations; decision=proceed → governance blocks → ViolationRecord → reply LLM | Same | Same | Cleaner code |
| B — Reverse dependency | Reply text quality improved. | **FULL** — Stage 2 sees tool_graph + available_results → decision=clarify with chain awareness | Same | Same | Cleaner code |
| C — Multi-turn clarification | Reply text quality improved. | **FULL** — Stage 2 sees runtime_defaults → decision=proceed (or clarify when needed) → e2e_codeswitch_161, e2e_colloquial_141, e2e_clarification_101 pass | LLM classifier correctly identifies CONTINUATION for short replies | Same | Cleaner code |
| D — Cross-turn feedback | Reply text quality improved. | **FULL** — Session-scoped prior_violations injected into Stage 2; LLM references past violations | Same | Same | Cleaner code |

---

## Section 7: Design Principles Locked in Phase 3

The following principles were debated during case-driven design review and are now
**locked**. Any future proposal that contradicts them must explicitly challenge the
principle and provide evidence that the original rationale no longer holds.

### 7.1 F1: No Confidence-Based Governance Override of LLM Decisions

**Principle**: Governance SHALL NOT use a confidence threshold to override the
LLM's `decision` field. If the LLM outputs `decision.value = proceed` at
`decision.confidence ≥ 0.5`, governance proceeds.

**Rationale**:
- A secondary confidence threshold (e.g., "proceed only if confidence ≥ 0.85 when
  optional slots are missing") is the same anti-pattern identified in audit §3.2.3,
  where `ao_classifier_confidence_threshold = 0.7` was marked MISALIGNED.
- The F1 safety net already covers genuinely uncertain cases: `confidence < 0.5`
  triggers fallback to existing hard-rule paths.
- The 0.5–0.85 interval is where the LLM is exercising legitimate conversational
  judgment. Overriding it replaces LLM judgment with a magic number — precisely
  the governance overreach Phase 3 exists to eliminate.

**What this means in practice**:
- `validate_decision()` has ONE confidence gate: `confidence < 0.5 → fallback to
  hard-rule path`.
- There is NO `decision_proceed_confidence_threshold_for_optionals` config key.
- If the LLM decides to proceed with optional slots defaulted, the reply LLM
  handles transparency (states what default was used, invites revision).
- If the LLM is genuinely uncertain about a default, it should output
  `decision = clarify` at its own discretion.

**Challenge required to revisit**: Demonstrate that the LLM systematically outputs
`proceed` at confidence 0.5–0.85 when it should clarify, with evidence from 50+
real user turns (not benchmark tasks), and show that the reply LLM transparency
mechanism is insufficient to correct the resulting user confusion.

### 7.2 F2: Domain Rules Are Governance-Owned, Not LLM-Injected

**Principle**: Cross-constraint rules (K5), readiness rules, and other domain
physics constraints SHALL NOT be injected into the LLM prompt. Governance
detects violations deterministically and feeds them back to the LLM via the
`ConstraintViolation` closed loop.

**Rationale**:
- Domain rules (vehicle/road compatibility, vehicle/pollutant relevance, etc.) are
  governance's territory. The LLM owns conversational pragmatics.
- Rules injected into the prompt would exist in two places (YAML config + prompt
  text) and could diverge — a single-source-of-truth violation.
- The closed-loop feedback (`prior_violations` in the next turn's Stage 2 payload)
  is sufficient: the LLM sees *which rule was violated*, not *that the rules exist
  in advance*.
- This implements the "rule detection + LLM response" design philosophy (§4.3.2):
  the LLM does not need to memorize all domain rules, and governance is not
  overridden by the LLM.

**What this means in practice**:
- `config/cross_constraints.yaml` is the single source of truth for constraints.
- The Stage 2 LLM user payload does NOT contain a `cross_constraint_rules` key.
- When governance detects a violation, it constructs a `ViolationRecord` and
  persists it to `_session_violation_log`. The NEXT turn's Stage 2 payload
  includes this violation in `prior_violations`.
- The LLM sees the violation as *historical context* (something that happened),
  not as *proactive rules* (something that might happen).

**Challenge required to revisit**: Demonstrate a concrete case where the closed-loop
feedback is insufficient — the LLM makes the same mistake repeatedly across 3+
turns because it lacks proactive rule knowledge, AND show that injecting the rules
into the prompt would fix this without introducing hallucinated constraint
enforcement.

---

### 7.3 F3: Reply LLM Enum Value Sourcing

**Principle**: When reply LLM lists domain enum values (model_year ranges, vehicle
types, pollutant codes), the values MUST come from
`ReplyContext.legal_values_for_pending_slots`, not from training knowledge.

**Rationale**:
- Domain enum values may diverge from training data (e.g., project YAML may restrict
  to 1995–2025 while training knowledge knows 1985–2030). Single source of truth
  required.
- Listing values from training knowledge violates HARD RULE (b): "no specific
  numbers or ranges not explicitly present in ReplyContext."
- The `legal_values_for_pending_slots` field provides the same legal-value
  definitions that Stage 2 uses for slot validation, ensuring consistency between
  what governance validates and what the reply LLM presents to the user.
- This closes the design gap identified in Step 0 smoke v2 where model_year
  1995–2025 was listed from LLM domain knowledge rather than from an injected
  legal_values source.

**What this means in practice**:
- `ReplyContext` gains a new field: `legal_values_for_pending_slots: Dict[str, List[Any]]`,
  defaulting to `{}`.
- `ReplyContextBuilder` populates this field from governance metadata during
  `build()`, keyed by slot name (e.g., `{"model_year": [1995, ..., 2025], "vehicle_type": ["Passenger Car", ...]}`).
- The reply LLM prompt (Step 0 HARD RULES) includes guidance: "When listing
  valid values for a parameter, use the range in legal_values_for_pending_slots
  — do not generate ranges from training knowledge."
- K1 injection (Step 1 sub-step 1.7a) simultaneously feeds legal values to both
  Stage 2 and ReplyContext, maintaining a single injection source.

**Challenge required to revisit**: Demonstrate that `legal_values_for_pending_slots`
cannot be reliably injected without bloating Stage 2 / reply LLM payload beyond
practical limits (>5KB), OR show that the legal values change frequently enough
that injection lag causes the reply LLM to present stale enum ranges to users.

---

*End of design document. Awaiting human review before any code changes.*
