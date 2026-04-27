# Phase 3.1 Decision Field Design

> Read-only design document. No code changes. Awaiting review before implementation.
> Branch: `phase3-governance-reset` (based on `task-pack-a-llm-reply-parser`).
> Date: 2026-04-27.

## Section 1: Current State Inventory

### 1.1 Stage 2 LLM — Three Prompt Variants, One Call Shape

All three variants share the same contract: the user message is a YAML dump of
structured data, not natural language. The LLM is expected to parse the YAML
and return JSON.

#### Variant A: Legacy ClarificationContract (Chinese, verbose, 12 rules)

- **File**: `core/contracts/clarification_contract.py:692-713`
- **Method**: `_stage2_system_prompt()` (static)
- **Language**: Chinese throughout
- **Output schema** (rule 10):
  ```
  {slots: {...}, intent: {...}, stance: {...}, missing_required,
   needs_clarification, clarification_question, ambiguous_slots}
  ```
- **Rules summary**:
  1. Only use `source=inferred` when explicitly expressed / file-context-strong / common-sense-mapping-strong
  2. Don't invent `model_year`; unknown → `{value: null, source: "missing", confidence: 0.0}`
  3. Colloquial vehicle/road/season/pollutant → standard name + raw_text
  4. Missing required → `needs_clarification=true` + natural question
  5. Also output `intent: {resolved_tool, intent_confidence, reasoning}`
  6. Available tools enumeration (4 tools with Chinese descriptions)
  7. Intent confidence rules: "confirm-first without tool" → `none`; "tool keywords" → `high`
  8. Also output `stance: {value, confidence, reasoning}`; values: directive/deliberative/exploratory
  9. Stance rules: "先/确认/看看参数" → deliberative; short+tool → directive; exploratory → exploratory; uncertain → directive
  10. Prefer slots/intent/stance output; fallback compatible with parameter_snapshot
  11. Each slot: `{value, source, confidence, raw_text}`; source ∈ {user, default, inferred, missing}
  12. Forbidden sentinel values in value field
- **Few-shot examples**: None
- **Temperature**: 0.0
- **Timeout**: `clarification_llm_timeout_sec` (default 5.0s)

#### Variant B: Split contracts (Chinese, compact, 9 rules condensed)

- **File**: `core/contracts/split_contract_utils.py:17-27`
- **Method**: `_stage2_system_prompt()` (static, overrides legacy)
- **Language**: Chinese
- **Key differences from Variant A**:
  - No `intent.reasoning` or `stance.reasoning` fields (saves tokens)
  - No rule numbering — a single paragraph
  - Explicit output format string with field list
  - Confidence values: intent.conf ∈ {high, low, none}; stance.conf ∈ {high, medium, low}
  - Same forbidden-sentinel rule
- **Few-shot examples**: None
- **Same user-payload shape as Variant A** (file_context, tool_slots, legal_values, etc.)

#### Variant C: AO Classifier Layer 2 (Chinese, separate concern)

- **File**: `core/ao_classifier.py:72-94`
- **Constant**: `AO_CLASSIFIER_SYSTEM_PROMPT`
- **Language**: Chinese
- **Output**: `{classification, target_ao_id, reference_ao_id, new_objective_text, confidence, reasoning}`
- **Note**: NOT a Stage 2 variant — it's a separate LLM call for turn classification.
  Listed here for completeness; it is addressed in TASK-3, not in this document.

### 1.2 User Payload (YAML) — Same Shape in All Variants

Built at `clarification_contract.py:662-681` and identically at
`split_contract_utils.py:40-59`:

```yaml
user_message: "<raw user text>"
tool_name: "query_emission_factors"  # or null
available_tools:
  query_emission_factors: "查询排放因子；关键词包括 factor, emission factor, 排放因子, 因子"
  calculate_micro_emission: "VSP 逐秒微观排放计算；通常需要轨迹文件"
  calculate_macro_emission: "路段级宏观排放计算；通常需要路网/流量文件"
  query_knowledge: "知识库检索和政策/方法问答"
file_context:
  has_file: true/false
  task_type: "trajectory" or null
  file_path: "/path/to/file" or null
current_ao_id: "AO#3" or null
classification: "NEW_AO" or "CONTINUATION" or "REVISION"
existing_parameter_snapshot:
  vehicle_type: {value: null, source: missing, confidence: 0.0}
  pollutants: {value: null, source: missing, confidence: 0.0}
  ...
tool_slots:
  required_slots: [vehicle_type, pollutants]
  optional_slots: [model_year, season, road_type]
  defaults: {}
  clarification_followup_slots: []
legal_values:
  vehicle_type: [Passenger Car, Transit Bus, Motorcycle, ...]
  pollutants: [CO2, NOx, PM2.5, PM10, CO, THC]
  ...
```

### 1.3 Current Output Fields (what Stage 2 Returns Today)

```
slots: Dict[str, {value, source, confidence, raw_text}]  — parameter snapshot
intent: {resolved_tool, intent_confidence, reasoning}     — tool intent (legacy)
       or {tool, conf}                                     — tool intent (split compact)
stance: {value, confidence, reasoning}                    — conversational stance (legacy)
       or {value, conf}                                    — stance (split compact)
chain: [str]                                               — projected tool chain
missing_required: [str]                                    — slot names
needs_clarification: bool
clarification_question: str | null
ambiguous_slots: [str]
```

### 1.4 Current Consumption Paths (where Stage 2 output flows)

| Step | File:Line | What Happens |
|------|-----------|--------------|
| Stage 2 call (legacy) | `clarification_contract.py:219,291` | LLM returns JSON, telemetry extracted |
| Stage 2 call (split intent) | `intent_resolution_contract.py:91` | `_run_stage2_llm_with_telemetry`, only intent consumed here |
| Stage 2 call (split readiness) | `execution_readiness_contract.py:106` | `_run_stage2_llm_with_telemetry`, slots + stance consumed |
| Snapshot merge | `clarification_contract.py:279,317` | `_merge_stage2_snapshot()` — LLM slots merged into contract snapshot |
| Intent extraction | `clarification_contract.py:722-744` | `_extract_llm_intent_hint()` — parses intent from payload |
| Stance extraction | `clarification_contract.py:746-779` | `_extract_llm_stance_hint()` — parses stance; missing_required → deliberative fallback |
| Question-vs-proceed | `clarification_contract.py:354-439` | **§3.3.9** — governance decision tree: missing_required? reject? collection_mode? probe? |
| Split clarify candidates | `execution_readiness_contract.py:177-225` | **§3.4.5** — 9-source aggregation into one list |
| Split stance branches | `execution_readiness_contract.py:313,348` | **§3.4.7, §3.4.8** — EXPLORATORY/DELIBERATIVE hardcoded responses |
| Intent hardcoded clarify | `intent_resolution_contract.py:116-131` | **§3.4.2** — intent=NONE → hardcoded Chinese text |
| Snapshot direct execution | `governed_router.py:355-408` | **§3.1.2** — reads direct_execution block, calls executor, bypasses LLM |

### 1.5 The 9 Governance Decision Points That decision Replaces

Per the user's specification, the `decision` field replaces these hard rules:

1. **§3.2.2** — AOClassifier rule layer substring short-circuit (`_is_short_clarification_reply`, `_detect_revision_target`)
2. **§3.3.5** — Collection-mode resolution (`_resolve_collection_mode` PCM trigger)
3. **§3.3.6** — Optional-slot probe abandon at `>= 2`
4. **§3.3.8** — `_detect_confirm_first` regex detection
5. **§3.3.9** — Question-vs-proceed decision tree (the core governance short-circuit)
6. **§3.4.1** — Continuation-state intent short-circuit
7. **§3.4.3** — Stance reversal substring matching
8. **§3.4.4** — Saturated-slot stance fallback (DELIBERATIVE → DIRECTIVE)
9. **§3.4.7 / §3.4.8** — EXPLORATORY/DELIBERATIVE hardcoded short-circuits

## Section 2: Prompt Redesign — Adding the `decision` Field

### 2.1 Design Principle

The LLM is asked a single new question at the end of its analysis:
**"Based on everything you've extracted (slots, intent, stance), should we
proceed to execute, ask the user a clarification question, or help them
deliberate?"**

Governance still validates the answer against domain constraints (cross-constraint
preflight, readiness), but no longer overrides the conversational judgment.

### 2.2 New Output Schema (additive, not breaking)

The existing output fields remain unchanged. One new top-level field is added:

```json
{
  "slots": { ... },
  "intent": { ... },
  "stance": { ... },
  "chain": [ ... ],
  "missing_required": [ ... ],
  "needs_clarification": true,
  "clarification_question": "请问您需要查询哪个车型的排放因子？",
  "ambiguous_slots": [ ... ],

  "decision": {
    "value": "proceed",
    "confidence": 0.85,
    "reasoning": "所有必需槽位已填充，污染物和车型已标准化，可以直接查询排放因子。",
    "clarification_question": null
  }
}
```

#### Field specification

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `decision.value` | `"proceed" \| "clarify" \| "deliberate"` | Yes | The LLM's conversational judgment |
| `decision.confidence` | float 0–1 | Yes | LLM's confidence in this decision |
| `decision.reasoning` | string | Yes | One-sentence rationale (Chinese, for trace/debug) |
| `decision.clarification_question` | string \| null | Yes (non-null when value=clarify) | The exact question to ask the user |

#### Semantics of each value

**`proceed`** — The LLM believes sufficient information exists to execute a tool.
Required slots are filled (or have runtime defaults), intent is resolved, and
the user's stance is directive. The LLM writes no `clarification_question`.

**`clarify`** — The LLM has identified a specific information gap and wants to
ask the user a concrete question. The `clarification_question` field must contain
a natural, one-sentence question in Chinese. Examples: "请问您需要查询哪种污染物的排放因子？"
or "您上传的轨迹文件包含多辆车，请指定要分析哪一辆。"

**`deliberate`** — The user is exploring or comparing options, not ready to execute.
The LLM provides its `reasoning` as advice. No tool execution should happen.
The `clarification_question` may be null or contain a framing question.

### 2.3 New System Prompt Paragraph (Chinese, to be appended to existing)

#### For Variant A (Legacy, appended after rule 12 in `_stage2_system_prompt`):

```
13. 在完成上述所有字段后，额外输出一个 decision 字段，表达你对当前对话走向的判断：
    decision.value 取值：
    - "proceed": 信息已充分，可以直接调用工具执行。clarification_question 填 null。
    - "clarify": 缺少关键信息，需要向用户追问一个具体问题。clarification_question 必须是一句自然的中文问题。
    - "deliberate": 用户在探索或比较选项，应给出建议而非直接执行。clarification_question 可为 null 或一个引导性问题。
    decision.confidence 是对这个判断的置信度 (0-1)。
    decision.reasoning 是一句简短的中文解释。
    判断原则：
    - 所有 required_slots 已填充 + intent_confidence=high + 用户表达明确执行意图 → proceed
    - 存在 missing_required 或 needs_clarification=true → clarify
    - 用户使用"比较/看看/有哪些/能不能/怎么算"等探索性语言 → deliberate
    - 用户说"先确认/先看看参数/帮我检查" → deliberate
    - 不确定时宁可 clarify 也不要盲目 proceed
```

#### For Variant B (Split Compact, appended to `SplitContractSupport._stage2_system_prompt`):

```
额外输出 decision:{value,confidence,reasoning,clarification_question}。
value: proceed(信息充分可执行)/clarify(需追问)/deliberate(用户在探索)。
proceed 时 clarification_question=null；clarify 时必须给出自然中文问题。
判断: 缺必需槽位或 needs_clarification→clarify；探索/比较/确认参数→deliberate；
信息充分+意图明确→proceed；不确定时优先 clarify。
```

### 2.4 Few-Shot Examples (5–7, to be added to the user payload or system prompt)

These examples are designed to be injected as a `few_shot_examples` key in the
YAML user payload (not hardcoded in the system prompt), so they can be iterated
without touching Python code. This is consistent with the existing pattern where
all structured data flows through the YAML payload.

#### Example 1: proceed (factor query, all slots filled)

```yaml
few_shot_examples:
  - input:
      user_message: "查一下 Passenger Car 的 CO2 排放因子"
      tool_name: "query_emission_factors"
      existing_parameter_snapshot:
        vehicle_type: {value: "Passenger Car", source: user, confidence: 1.0}
        pollutants: {value: ["CO2"], source: user, confidence: 1.0}
        model_year: {value: null, source: missing, confidence: 0.0}
      tool_slots:
        required_slots: [vehicle_type, pollutants]
        optional_slots: [model_year, season, road_type]
        defaults: {model_year: 2020}
    output:
      slots:
        vehicle_type: {value: "Passenger Car", source: user, confidence: 1.0}
        pollutants: {value: ["CO2"], source: user, confidence: 1.0}
        model_year: {value: null, source: missing, confidence: 0.0}
      intent: {resolved_tool: "query_emission_factors", intent_confidence: high}
      stance: {value: directive, confidence: high}
      missing_required: []
      needs_clarification: false
      clarification_question: null
      decision:
        value: proceed
        confidence: 0.92
        reasoning: "所有必需参数已明确，model_year 可由默认值填充，可以直接执行因子查询。"
        clarification_question: null
```

#### Example 2: clarify (missing required slot)

```yaml
  - input:
      user_message: "查一下排放因子"
      tool_name: null
      existing_parameter_snapshot: {}
      tool_slots:
        required_slots: [vehicle_type, pollutants]
        optional_slots: [model_year]
        defaults: {}
    output:
      slots:
        vehicle_type: {value: null, source: missing, confidence: 0.0}
        pollutants: {value: null, source: missing, confidence: 0.0}
      intent: {resolved_tool: "query_emission_factors", intent_confidence: high}
      stance: {value: directive, confidence: medium}
      missing_required: [vehicle_type, pollutants]
      needs_clarification: true
      clarification_question: "请问您需要查询哪种车型和哪些污染物的排放因子？"
      decision:
        value: clarify
        confidence: 0.95
        reasoning: "factor 关键词明确指向排放因子查询，但车型和污染物均缺失，必须追问。"
        clarification_question: "请问您需要查询哪种车型和哪些污染物的排放因子？"
```

#### Example 3: deliberate (user wants to confirm first)

```yaml
  - input:
      user_message: "先帮我看看需要哪些参数才能算微观排放"
      tool_name: null
      existing_parameter_snapshot: {}
      tool_slots:
        required_slots: [vehicle_type, pollutants]
        optional_slots: [model_year, season, road_type]
        defaults: {}
    output:
      slots:
        vehicle_type: {value: null, source: missing, confidence: 0.0}
        pollutants: {value: null, source: missing, confidence: 0.0}
      intent: {resolved_tool: "calculate_micro_emission", intent_confidence: medium}
      stance: {value: deliberative, confidence: high}
      missing_required: [vehicle_type, pollutants]
      needs_clarification: false
      clarification_question: null
      decision:
        value: deliberate
        confidence: 0.88
        reasoning: "用户明确说'先看看'，处于参数确认阶段，应列出所需参数而非直接追问。"
        clarification_question: null
```

#### Example 4: clarify (rejected slot — colloquial value not mappable)

```yaml
  - input:
      user_message: "查一下国五车的 NOx"
      tool_name: "query_emission_factors"
      existing_parameter_snapshot:
        vehicle_type: {value: "国五车", source: user, confidence: 0.5}
        pollutants: {value: ["NOx"], source: user, confidence: 1.0}
      tool_slots:
        required_slots: [vehicle_type, pollutants]
        optional_slots: []
        defaults: {}
      legal_values:
        vehicle_type: [Passenger Car, Transit Bus, Motorcycle, Light Commercial Truck, ...]
    output:
      slots:
        vehicle_type: {value: null, source: rejected, confidence: 0.3, raw_text: "国五车"}
        pollutants: {value: ["NOx"], source: user, confidence: 1.0}
      intent: {resolved_tool: "query_emission_factors", intent_confidence: high}
      stance: {value: directive, confidence: medium}
      missing_required: []
      needs_clarification: true
      clarification_question: "国五车对应哪种 MOVES 车型？可选：Passenger Car、Light Commercial Truck 或 Heavy-Duty Truck。"
      decision:
        value: clarify
        confidence: 0.82
        reasoning: "国五是排放标准不是车型，需用户映射到 MOVES 车型类别。"
        clarification_question: "国五车对应哪种 MOVES 车型？可选：Passenger Car、Light Commercial Truck 或 Heavy-Duty Truck。"
```

#### Example 5: proceed (macro emission, all required + file provided)

```yaml
  - input:
      user_message: "用这个路网文件算一下宏观排放，车型按 Transit Bus，污染物 CO2 和 PM2.5"
      tool_name: "calculate_macro_emission"
      file_context: {has_file: true, task_type: "road_network"}
      existing_parameter_snapshot:
        vehicle_type: {value: "Transit Bus", source: user, confidence: 1.0}
        pollutants: {value: ["CO2", "PM2.5"], source: user, confidence: 1.0}
      tool_slots:
        required_slots: [vehicle_type, pollutants]
        optional_slots: [model_year, season, road_type]
        defaults: {model_year: 2020}
    output:
      slots:
        vehicle_type: {value: "Transit Bus", source: user, confidence: 1.0}
        pollutants: {value: ["CO2", "PM2.5"], source: user, confidence: 1.0}
        model_year: {value: null, source: missing, confidence: 0.0}
      intent: {resolved_tool: "calculate_macro_emission", intent_confidence: high}
      stance: {value: directive, confidence: high}
      missing_required: []
      needs_clarification: false
      clarification_question: null
      decision:
        value: proceed
        confidence: 0.90
        reasoning: "所有必需参数已由用户提供，文件已上传，可直接执行宏观排放计算。"
        clarification_question: null
```

#### Example 6: deliberate (exploratory comparison)

```yaml
  - input:
      user_message: "Passenger Car 和 Transit Bus 哪个 PM2.5 排放高？市区道路和高速分别算一下"
      tool_name: null
      existing_parameter_snapshot:
        vehicle_type: {value: null, source: missing, confidence: 0.0}
        pollutants: {value: ["PM2.5"], source: user, confidence: 1.0}
      tool_slots:
        required_slots: [vehicle_type, pollutants]
        optional_slots: [road_type]
        defaults: {}
    output:
      slots:
        vehicle_type: {value: null, source: missing, confidence: 0.0}
        pollutants: {value: ["PM2.5"], source: user, confidence: 1.0}
        road_type: {value: null, source: missing, confidence: 0.0}
      intent: {resolved_tool: "query_emission_factors", intent_confidence: medium}
      stance: {value: exploratory, confidence: high}
      missing_required: [vehicle_type]
      needs_clarification: false
      clarification_question: null
      decision:
        value: deliberate
        confidence: 0.85
        reasoning: "用户在比较两种车型和两种道路类型，属于探索性分析，应给出查询建议而非直接执行。"
        clarification_question: "您想先分别查询两种车型在市区和高速的 PM2.5 因子，然后做对比，需要我开始查询吗？"
```

#### Example 7: clarify (continuation — short reply to a probe)

```yaml
  - input:
      user_message: "CO2"
      tool_name: "query_emission_factors"
      classification: "CONTINUATION"
      existing_parameter_snapshot:
        vehicle_type: {value: "Passenger Car", source: user, confidence: 1.0}
        pollutants: {value: null, source: missing, confidence: 0.0}
      tool_slots:
        required_slots: [vehicle_type, pollutants]
        optional_slots: []
        defaults: {}
    output:
      slots:
        vehicle_type: {value: "Passenger Car", source: user, confidence: 1.0}
        pollutants: {value: ["CO2"], source: user, confidence: 1.0}
      intent: {resolved_tool: "query_emission_factors", intent_confidence: high}
      stance: {value: directive, confidence: high}
      missing_required: []
      needs_clarification: false
      clarification_question: null
      decision:
        value: proceed
        confidence: 0.93
        reasoning: "用户回复 CO2 补全了污染物参数，所有必需槽位已齐，应继续执行排放因子查询。"
        clarification_question: null
```

## Section 3: Schema Validation and Fallback Design

### 3.1 Validation Rules (applied post-Stage 2, pre-consumption)

```python
# Pseudocode — not for implementation yet
def validate_decision(decision: dict, payload: dict) -> tuple[bool, str, str | None]:
    """Returns (is_valid, fallback_reason, fallback_decision_value)."""

    # Rule 1: decision field must exist and be a dict
    if not isinstance(decision, dict):
        return False, "decision_missing_or_wrong_type", None

    value = str(decision.get("value") or "").strip().lower()

    # Rule 2: value must be in the allowed set
    if value not in {"proceed", "clarify", "deliberate"}:
        return False, f"invalid_decision_value_{value}", None

    # Rule 3: confidence must be >= 0.5
    confidence = float(decision.get("confidence") or 0)
    if confidence < 0.5:
        return False, f"low_confidence_{confidence}", None

    # Rule 4: clarify requires a non-empty clarification_question
    if value == "clarify":
        question = str(decision.get("clarification_question") or "").strip()
        if not question:
            return False, "clarify_missing_question", None

    # Rule 5 (cross-check): decision==proceed but payload has missing_required
    missing = list(payload.get("missing_required") or [])
    if value == "proceed" and missing:
        return False, "proceed_with_missing_required", None

    return True, "valid", value
```

### 3.2 Fallback Path (the F1 safety net)

When validation fails, the system falls back to the **existing hard rules** as a
safety net — not to the LLM's raw unvalidated output. This is the "LLM 不可全信"
principle.

Fallback routing table:

| Validation Failure | Fallback Behavior |
|---|---|
| `decision_missing_or_wrong_type` | Run existing governance question-vs-proceed logic (§3.3.9 / §3.4.5–§3.4.9) |
| `invalid_decision_value_*` | Run existing governance logic |
| `low_confidence_*` | Treat as `decision=clarify` with fallback question from `_build_question()` |
| `clarify_missing_question` | Use LLM's `clarification_question` from the top-level payload (legacy field), or fallback to `_build_question()` |
| `proceed_with_missing_required` | Override to `decision=clarify`, use LLM's `clarification_question` from payload or `_build_question()` |

Fallback telemetry: every fallback event records `decision_fallback_reason` and
`decision_fallback_source` (which rule triggered) in the trace. This lets us
measure how often the F1 net activates and tune the prompt or thresholds.

### 3.3 Confidence Threshold Rationale

The threshold of 0.5 is intentionally lower than the existing
`clarification_llm_confidence_threshold=0.7` and
`ao_classifier_confidence_threshold=0.7`. Rationale:

- The `decision` field is a conversational judgment, not a domain-legal-value
  enforcement. A lower bar respects the design principle that "conversational
  pragmatics is LLM-deferential."
- Domain safety is enforced downstream by cross-constraint preflight (§3.7.1)
  and readiness (§3.7.2), which are NOT gated on `decision.confidence`.
- If the LLM says `proceed` at 0.55 but cross-constraint detects
  vehicle/road incompatibility, the ConstraintViolation still blocks execution
  regardless of confidence.

The 0.5 threshold can be adjusted via `runtime_config` after baseline measurement.

## Section 4: GovernedRouter Consumption Layer — Modification Points

This section lists every file:line that must change, without writing the code.

### 4.1 Prompt Changes (2 files, additive)

| File | Line(s) | Change |
|------|---------|--------|
| `core/contracts/clarification_contract.py` | 692–713 | Append decision rule (rule 13) to `_stage2_system_prompt()` |
| `core/contracts/split_contract_utils.py` | 17–27 | Append compact decision rule to `_stage2_system_prompt()` |
| `core/contracts/clarification_contract.py` | 662–681 | Add `few_shot_examples` key to `prompt_payload` (read from a constant or config — see §5.2) |
| `core/contracts/split_contract_utils.py` | 40–59 | Same — add `few_shot_examples` to `prompt_payload` |

### 4.2 Validation Layer (1 new function, 1 file)

| File | Change |
|------|--------|
| `core/contracts/clarification_contract.py` (or new `core/contracts/decision_validator.py`) | New static function `validate_decision(decision, payload) -> (bool, str, str\|None)` implementing §3.1 rules |

### 4.3 Consumption in Legacy ClarificationContract (1 file, ~15 lines changed)

| File | Line(s) | Current Behavior | New Behavior |
|------|---------|------------------|--------------|
| `clarification_contract.py` | 219–249 | After prefetched Stage 2: extracts intent + stance, then falls through to question-vs-proceed | After Stage 2: extract `decision` field, validate it. If `decision=proceed`, skip to snapshot injection. If `decision=clarify`, use LLM's question directly. If `decision=deliberate`, use LLM's reasoning as response text. |
| `clarification_contract.py` | 291–319 | Same pattern for standard Stage 2 call | Same changes |
| `clarification_contract.py` | 354–439 | **§3.3.9** question-vs-proceed decision tree | Retain as the F1 fallback path ONLY (when decision validation fails). Normal path reads `decision.value` instead. |

### 4.4 Consumption in Split Contracts (3 files, ~30 lines changed)

| File | Line(s) | Current Behavior | New Behavior |
|------|---------|------------------|--------------|
| `intent_resolution_contract.py` | 116–131 | **§3.4.2** intent=NONE → hardcoded Chinese text | If Stage 2 returned `decision=clarify` with question, use that question. Fallback to existing hardcoded text only when decision is missing/invalid. |
| `execution_readiness_contract.py` | 313–346 | **§3.4.7** EXPLORATORY → hardcoded Chinese text | If `decision=deliberate`, use LLM's reasoning/clarification_question. Hardcoded text becomes fallback only. |
| `execution_readiness_contract.py` | 348–429 | **§3.4.8** DELIBERATIVE probe logic | If `decision=deliberate`, skip probe logic — LLM has already decided this is exploratory. If `decision=clarify`, use LLM's question instead of `_build_probe_question()`. If `decision=proceed`, skip to execution readiness. |
| `execution_readiness_contract.py` | 177–225 | **§3.4.5** 9-source clarify-candidates aggregation | When `decision=clarify` is present and valid, bypass the aggregation — use the LLM's specified question and missing slot. Aggregation retained as F1 fallback. |
| `execution_readiness_contract.py` | 227–244 | **§3.4.6** probe-limit force-proceed | When `decision=proceed`, skip probe-limit gate. When `decision=clarify`, probe-limit still applies but uses LLM's question. |
| `execution_readiness_contract.py` | 498–512 | Direct execution block construction | Add `decision` to telemetry. Only construct `direct_execution` when `decision=proceed` AND cross-constraint/readiness pass. |

### 4.5 Consumption in GovernedRouter Shell (1 file, ~10 lines changed)

| File | Line(s) | Current Behavior | New Behavior |
|------|---------|------------------|--------------|
| `governed_router.py` | 355–408 | **§3.1.2** `_maybe_execute_from_snapshot` — reads `direct_execution` block, bypasses LLM | Add guard: only execute from snapshot if `decision=proceed` is present in telemetry AND validated. If `decision=clarify` or `decision=deliberate`, skip direct execution and fall through to reply pipeline. |
| `governed_router.py` | 130–143 | After contracts, falls through to inner router | Before calling inner router: if `decision=deliberate`, construct RouterResponse from LLM's reasoning (no tool execution). If `decision=clarify`, construct RouterResponse from LLM's question (no tool execution). |

### 4.6 Telemetry Extension (2 files, additive)

| File | Change |
|------|--------|
| `core/contracts/clarification_contract.py` (ClarificationTelemetry dataclass, lines 32–66) | Add fields: `decision_value: Optional[str]`, `decision_confidence: Optional[float]`, `decision_fallback_reason: Optional[str]`, `decision_fallback_source: Optional[str]` |
| `core/contracts/execution_readiness_contract.py` (`_telemetry` method) | Add same fields to split telemetry dict |

### 4.7 Substring Matcher Decommissioning (NOT in Step 2A — deferred to Step 2B + Step 3)

These are listed here for completeness but are NOT modified in Step 2A:

| File | Line(s) | Function | Step |
|------|---------|----------|------|
| `core/ao_classifier.py` | 202–269 | `_rule_layer1` short-circuits | Step 2A (TASK-3) |
| `core/continuation_signals.py` | 4–37 | `has_reversal_marker`, `has_probe_abandon_marker` | Step 2A (TASK-4) |
| `core/contracts/stance_resolution_contract.py` | 32–52 | `detect_reversal` substring | Step 2A (TASK-4) |
| `core/contracts/clarification_contract.py` | 1447–1508 | `_detect_confirm_first` | Step 2A (TASK-4) |
| `core/ao_classifier.py` | 99–114 | `_reference_signal_patterns` substring list | Step 3 (TASK-4 cleanup) |

## Section 5: Risks and Open Questions

### 5.1 Identified Risks

**R1 — LLM decision inconsistency across turns.** The same user state might get
`proceed` on turn 1 and `clarify` on turn 2 due to LLM non-determinism (even at
temperature=0.0, different models or provider updates can shift behavior).
*Mitigation*: The F1 fallback path is deterministic and always available.
Telemetry records every decision + fallback event for monitoring.

**R2 — `clarification_question` quality.** The LLM may generate vague or
hallucinated questions (e.g., asking about a parameter that doesn't exist).
*Mitigation*: Schema validation cross-checks that `decision=clarify` has a
non-empty question. The reply parser (§3.6.1) acts as a second LLM pass that
can improve question quality. If the question references a non-existent slot,
downstream readiness will catch it.

**R3 — Increased prompt length.** Few-shot examples add ~2KB to the prompt.
*Mitigation*: Examples can be truncated or moved to a separate config file.
The split-compact variant will use shorter examples. Token budget impact should
be measured in Step 2A smoke tests.

**R4 — Interaction with existing stance reversal logic.** The `decision` field
may say `proceed` while `stance_resolver.detect_reversal()` simultaneously
detects a reversal from substring matching. *Resolution*: In Step 2A, when both
exist, `decision` wins and the substring match is logged as overridden. In
Step 2B (TASK-6), the stance reversal logic is fully reconciled.

**R5 — Baseline regression.** The current 64% completion rate may drop if the
LLM makes worse conversational judgments than the hard rules. *Mitigation*:
Step 2A is behind a feature flag (`enable_llm_decision_field`, default False).
A/B comparison against baseline is mandatory before making it the default.

### 5.2 Open Questions for Review

**Q1 — Where should few-shot examples live?** Option A: inline in the system
prompt (simpler, one file). Option B: in the YAML user payload (consistent
with existing pattern, easier to iterate). Option C: in a separate YAML config
file (`config/decision_few_shot_examples.yaml`). I recommend Option C for
maintainability — domain experts can add examples without touching Python.

**Q2 — Should the decision field reuse or replace `needs_clarification`?**
Currently `needs_clarification` is a boolean, and `clarification_question` is a
top-level string. The new `decision` field duplicates some of this information
(`decision=clarify` ≈ `needs_clarification=true`). I recommend keeping both in
Step 2A for backward compatibility, then removing `needs_clarification` in
Step 2B once the decision field is proven.

**Q3 — What about multi-tool chains?** Currently `chain` and `projected_chain`
are separate concerns. If the LLM returns `decision=proceed` but the chain
requires intermediate steps, should governance auto-execute the chain or ask
for confirmation? My initial view: `decision=proceed` means "proceed with the
first tool in the chain"; governance handles chain continuation via the existing
ExecutionContinuation mechanism. Needs confirmation.

**Q4 — Is the 0.5 confidence threshold right?** This is an empirical question.
I chose 0.5 because it's lower than the existing 0.7 thresholds (consistent
with "LLM leads conversational judgment") but high enough to filter out
nonsense. This should be tuned based on Step 2A smoke test data.

**Q5 — Does `decision=deliberate` need a separate reply path, or can it reuse
the existing exploratory branch?** The existing EXPLORATORY branch (§3.4.7)
returns a hardcoded Chinese question. With `decision=deliberate`, the LLM's
`reasoning` becomes the response text (potentially rewritten by the reply parser).
This is a new code path that doesn't exist today — needs a small new branch in
GovernedRouter.chat().

**Q6 — How does `decision` interact with TASK-1 (runtime-default optionals)?**
TASK-1 makes model_year=2020 a runtime default for factor queries. When the LLM
sees model_year is missing but knows it has a runtime default, should it return
`decision=proceed` or `decision=clarify`? The few-shot Example 1 shows
`decision=proceed` in this case, but this assumes the LLM knows about the
default. *Recommendation*: The user payload should include a `runtime_defaults`
key listing which optional slots have defaults, so the LLM can factor this
into its decision. This should be added to TASK-1's scope.

### 5.3 Feature Flag Plan

All changes in Step 2A are gated behind a single runtime_config flag:

```
enable_llm_decision_field: bool = False  # default OFF
```

When `False`, the system runs the existing hard-rule path unchanged.
When `True`:
- The decision rule is appended to the Stage 2 system prompt
- Few-shot examples are injected into the user payload
- `validate_decision()` runs on Stage 2 output
- GovernedRouter reads `decision.value` instead of the legacy question-vs-proceed tree
- F1 fallback activates on validation failure

This allows clean A/B comparison: run the same smoke suite with the flag
on and off, compare completion rates.

---

*End of design document. Awaiting human review before any code changes.*
