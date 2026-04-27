# Phase 2 Task Pack A - LLM Reply Parser Analysis

## 0. Repository State

- Branch at analysis time: `main`
- HEAD at analysis time: `c3761ef Phase 2 C+D: add clean_dataframe data-quality tool via governed registry`
- Worktree before A.1: clean
- A.1 scope: read existing code, run a 5-task current-reply sample, attempt prototype LLM reply generation, and produce this analysis document. No reply parser, router, config, or test code was changed.

## 1. Existing Reply Parser / Reply Surface Inventory

### 1.1 Important Naming Drift

The current repository does not have a single module explicitly named "final reply parser". User-visible final replies are assembled across:

- `core/router.py:11206` - `UnifiedRouter._state_build_response(...)`, the main final `RouterResponse` assembly point.
- `core/router.py:11747` - `UnifiedRouter._synthesize_results(...)`, the current synthesis boundary.
- `core/router_synthesis_utils.py:26` - deterministic short-circuit policy before synthesis.
- `core/router_render_utils.py:337` - deterministic per-tool markdown rendering.
- `core/router_render_utils.py:821` - deterministic failure fallback renderer.

There are also two regex/deterministic "reply parsers", but they parse **user replies to pending flows**, not final assistant replies:

- `core/parameter_negotiation.py` - 435 lines. Handles parameter-confirmation replies with regex/index/alias matching.
  - Key parse surface: `parse_parameter_negotiation_reply(...)` at `core/parameter_negotiation.py:293`.
  - Regex/index matching: `core/parameter_negotiation.py:229-259`.
  - Prompt renderer: `core/parameter_negotiation.py:395-423`.
- `core/input_completion.py` - 607 lines. Handles input-completion replies with regex/index/numeric/option matching.
  - Key parse surface: `parse_input_completion_reply(...)` at `core/input_completion.py:402`.
  - Regex/index/numeric matching: `core/input_completion.py:296-323`.
  - Option/retry prompt renderer: `core/input_completion.py:570-607`.

The prompt's "426+470 line regex state machine" appears to be stale against current `main`. The closest live artifacts are the two deterministic user-reply parsers above plus the final response rendering/synthesis cluster. Task Pack A should not delete or replace the user-reply parsers; it should add an LLM-based **assistant final reply writer** over a structured `ReplyContext`, with existing response assembly as fallback.

### 1.2 Current Final Reply Data Sources

Current final assistant text is assembled from these sources:

- `TaskState.control` prompts:
  - `input_completion_prompt`, `parameter_confirmation_prompt`, `clarification_question` in `core/task_state.py:207-224`.
  - Returned directly by `UnifiedRouter._state_build_response(...)` for `NEEDS_INPUT_COMPLETION`, `NEEDS_PARAMETER_CONFIRMATION`, and `NEEDS_CLARIFICATION` at `core/router.py:11212-11254`.
- `TaskState.execution.blocked_info`:
  - Used as the blocked response at `core/router.py:11265-11283`.
- `_final_response_text` ad hoc state attribute:
  - Used by several early-return branches at `core/router.py:11285-11301`.
- `TaskState.execution.tool_results`:
  - Declared at `core/task_state.py:186-203`.
  - Used in response assembly and payload extraction at `core/router.py:11312-11355`.
- Synthesis helpers:
  - `core/router_synthesis_utils.py:26-58`: short-circuits `query_knowledge`, failures, and single-tool successes.
  - `core/router_synthesis_utils.py:61-84`: builds filtered synthesis prompt.
  - `core/router_render_utils.py:337-681`: deterministic single-tool success markdown.
  - `core/router_render_utils.py:731-791`: filters tool result payloads for synthesis.
  - `core/router_render_utils.py:821-864`: deterministic fallback markdown for failure/mixed results.
- Optional LLM synthesis:
  - `core/router.py:11785-11810` builds prompt and calls `self.llm.chat(...)` only if deterministic short-circuit does not return text.

### 1.3 Current Output Format

The router returns `RouterResponse`:

- `core/router.py:319-328`
- Fields: `text`, `chart_data`, `table_data`, `map_data`, `download_file`, `executed_tool_calls`, `trace`, `trace_friendly`.

API session preserves the same shape:

- `api/session.py:80-105` returns `text`, frontend payloads, executed tool calls, and trace fields.
- `/chat` wraps this into `ChatResponse` at `api/routes.py:215-275`.

Task Pack A should preserve all non-text payload fields and only replace `RouterResponse.text` plus attach reply metadata into trace.

## 2. GovernedRouter Chat Flow

Current `GovernedRouter.chat(...)` flow:

1. Build `ContractContext` at `core/governed_router.py:102-106`.
2. Run `before_turn(...)` contracts at `core/governed_router.py:109-125`.
3. If no contract intercepts, run `_maybe_execute_from_snapshot(...)` or `inner_router.chat(...)` at `core/governed_router.py:127-143`.
4. Consume constraint-violation trace events through Task Pack B's writer at `core/governed_router.py:145-149`.
5. Run `after_turn(...)` contracts at `core/governed_router.py:151-152`.
6. Return the `RouterResponse` at `core/governed_router.py:154`.

Recommended A integration point:

- Build `ReplyContext` in `GovernedRouter.chat(...)` after Task Pack B's `_record_constraint_violations_from_trace(...)`.
- Prefer running it after `contract.after_turn(...)` and immediately before `return result`, so the builder sees final AO metadata and trace enrichment.
- Keep `UnifiedRouter` unaware of reply parsing. It should continue producing `TraceStep` and `RouterResponse` as the execution kernel.

This preserves the Phase 2 architecture narrative:

> Governance-layer cross-layer data flow uses TraceStep. GovernedRouter hosts independent consumers: ConstraintViolationWriter persists violations, and ReplyContextBuilder constructs the user-reply context. UnifiedRouter remains governance-agnostic.

## 3. ReplyContext Data Source Inventory

### 3.1 TraceStep Types

`core/trace.py:17-109` currently defines these `TraceStepType` values:

`file_grounding`, `file_analysis_multi_table_roles`, `file_analysis_missing_fields`, `file_analysis_spatial_metadata`, `file_analysis_fallback_triggered`, `file_analysis_fallback_applied`, `file_analysis_fallback_skipped`, `file_analysis_fallback_failed`, `file_relationship_resolution_triggered`, `file_relationship_resolution_decided`, `file_relationship_transition_applied`, `file_relationship_resolution_skipped`, `file_relationship_resolution_failed`, `supplemental_merge_triggered`, `supplemental_merge_planned`, `supplemental_merge_applied`, `supplemental_merge_failed`, `supplemental_merge_readiness_refreshed`, `supplemental_merge_resumed`, `intent_resolution_triggered`, `intent_resolution_decided`, `intent_resolution_applied`, `intent_resolution_skipped`, `intent_resolution_failed`, `artifact_recorded`, `artifact_memory_updated`, `artifact_already_provided_detected`, `artifact_suggestion_bias_applied`, `artifact_memory_skipped`, `summary_delivery_triggered`, `summary_delivery_decided`, `summary_delivery_applied`, `summary_delivery_recorded`, `summary_delivery_skipped`, `summary_delivery_failed`, `readiness_assessment_built`, `action_readiness_ready`, `action_readiness_blocked`, `action_readiness_repairable`, `action_readiness_already_provided`, `workflow_template_recommended`, `workflow_template_selected`, `workflow_template_injected`, `workflow_template_skipped`, `plan_created`, `plan_validated`, `plan_deviation`, `plan_step_matched`, `plan_step_completed`, `dependency_validated`, `dependency_blocked`, `plan_repair_triggered`, `plan_repair_proposed`, `plan_repair_applied`, `plan_repair_failed`, `plan_repair_skipped`, `plan_continuation_decided`, `plan_continuation_skipped`, `plan_continuation_injected`, `parameter_negotiation_required`, `parameter_negotiation_confirmed`, `parameter_negotiation_rejected`, `parameter_negotiation_failed`, `input_completion_required`, `input_completion_confirmed`, `input_completion_rejected`, `input_completion_failed`, `input_completion_applied`, `input_completion_paused`, `geometry_completion_attached`, `geometry_re_grounding_triggered`, `geometry_re_grounding_applied`, `geometry_re_grounding_failed`, `geometry_readiness_refreshed`, `geometry_recovery_resumed`, `residual_reentry_target_set`, `residual_reentry_decided`, `residual_reentry_injected`, `residual_reentry_skipped`, `remediation_policy_option_offered`, `remediation_policy_confirmed`, `remediation_policy_applied`, `remediation_policy_failed`, `parameter_standardization`, `cross_constraint_validated`, `cross_constraint_violation`, `cross_constraint_warning`, `tool_selection`, `tool_execution`, `state_transition`, `clarification`, `synthesis`, `error`.

Every serialized step uses the same envelope from `TraceStep.to_dict()`:

- Required: `step_index`, `step_type`, `timestamp`, `stage_before`.
- Optional: `stage_after`, `action`, `input_summary`, `output_summary`, `confidence`, `reasoning`, `duration_ms`, `standardization_records`, `error`.

Relevant payload shapes for ReplyContext:

- Tool selection: `core/router.py:10594-10602`
  - `action`: comma-joined tool names.
  - `reasoning`: selected tool summary.
- Tool execution: `core/router.py:11074-11104`
  - `action`: tool name.
  - `input_summary.arguments`: compact tool args.
  - `output_summary`: `success`, `message` or `error`, and selected summary fields.
  - `standardization_records`: parameter standardization details.
- Clarification: `core/router.py:10644-10650` and `core/router.py:11238-11254`
  - `reasoning`: user-facing clarification question.
- Parameter negotiation: `core/router.py:8407-8424`
  - `input_summary`: parameter/raw value/strategy/confidence.
  - `output_summary`: request id and candidates.
- Input completion: `core/router.py:6463-6479`
  - `input_summary`: reason code, target field, missing requirements.
  - `output_summary`: request id and options.
- Cross-constraint warning / violation: `core/router.py:2246-2263` and `core/router.py:2289-2305`
  - `input_summary.standardized_params`.
  - `input_summary.cross_constraint_violations`.
  - `standardization_records`: normalized persistent constraint records.
- Synthesis: `core/router.py:11325-11351`
  - `reasoning`: current synthesis description.

### 3.2 AnalyticalObjective

Current AO schema is `core/analytical_objective.py:199-244`. Fields relevant to reply writing:

- `ao_id`
- `objective_text`
- `status`
- `relationship`
- `parent_ao_id`
- `tool_call_log`
- `artifacts_produced`
- `parameters_used`
- `failure_reason`
- `constraint_violations`
- `tool_intent`
- `parameter_state`
- `stance`, `stance_confidence`, `stance_resolved_by`, `stance_history`
- `metadata`

Task Pack B reused `AnalyticalObjective.constraint_violations`; Task Pack A should consume this through the writer/builder layer, not by re-normalizing engine records.

### 3.3 ConstraintViolationWriter

`core/constraint_violation_writer.py` provides:

- `ViolationRecord`: `violation_type`, `severity`, `involved_params`, `suggested_resolution`, `timestamp`, `source_turn`.
- `ConstraintViolationWriter.get_latest() -> List[ViolationRecord]` at `core/constraint_violation_writer.py:107-117`.

This is the canonical source for current-AO violations in ReplyContext.

### 3.4 Context Store Data Quality Report

Task Pack C+D added:

- `core/context_store.py:228-253`: `get_by_type(result_type, label=None, pollutant=None)`.
- `core/context_store.py:85`: `clean_dataframe -> data_quality_report`.
- `core/data_quality.py:57-103`: strict `CleanDataFrameReport`.
- `tools/clean_dataframe.py:58-64`: tool output stores `{"report": ..., "result_type": "data_quality_report"}`.

ReplyContextBuilder should call `context_store.get_by_type("data_quality_report")`, if available, and include a compact report summary under `extra["data_quality_report"]` or a dedicated optional field if A.2 promotes it to core schema.

### 3.5 Clarification State

Current clarification state sources:

- `core/contracts/clarification_contract.py:1120-1165` persists `ao.metadata["clarification_contract"]`.
- `core/contracts/clarification_contract.py:443-463` appends `clarification_telemetry` into result trace.
- `core/contracts/clarification_contract.py:476-505` rebuilds pending state from AO metadata and first-class parameter state.
- `TaskState.control.clarification_question`, `parameter_confirmation_prompt`, and `input_completion_prompt` are returned directly for pending states.

ReplyContextBuilder should extract pending clarification requests from:

1. `current_ao.metadata["clarification_contract"]` when `pending == true`.
2. Trace steps with `step_type in {"clarification", "parameter_negotiation_required", "input_completion_required"}`.
3. Existing `result.text` fallback when the router returned a clarification before structured metadata is sufficient.

### 3.6 ExecutionState Tool Results

`ExecutionContext.tool_results` is `List[Dict[str, Any]]` at `core/task_state.py:186-203`.

At API boundaries, tool calls are exposed through `RouterResponse.executed_tool_calls`, generated by `core/router_memory_utils.py` and attached in `core/router.py:11312-11355`. Since `GovernedRouter.chat()` receives only `RouterResponse`, A.2 should use:

- `result.executed_tool_calls` for compact external summaries.
- `result.trace.steps` for execution details.
- `inner_router.context_store.get_current_turn_results()` if the builder needs current-turn result payloads and they are available.

## 4. ReplyContext Schema Draft

Proposed location:

- `core/reply/reply_context.py`
- `core/reply/reply_context_builder.py`

Proposed dataclasses:

```python
@dataclass
class ToolExecutionSummary:
    tool_name: str
    arguments: Dict[str, Any]
    success: bool
    summary: str
    result_type: Optional[str] = None
    error: Optional[str] = None
    output_refs: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ClarificationRequest:
    request_type: str  # clarification | parameter_negotiation | input_completion
    question: str
    missing_slots: List[str] = field(default_factory=list)
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    options: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class AOStatusSummary:
    ao_id: str
    objective_text: str
    status: str
    relationship: str
    tool_intent: Optional[str] = None
    stance: Optional[str] = None
    parameters_used: Dict[str, Any] = field(default_factory=dict)
    artifacts_produced: Dict[str, str] = field(default_factory=dict)

@dataclass
class ReplyContext:
    user_message: str
    router_text: str
    tool_executions: List[ToolExecutionSummary]
    violations: List[ViolationRecord]
    pending_clarifications: List[ClarificationRequest]
    ao_status: Optional[AOStatusSummary]
    trace_highlights: List[Dict[str, Any]] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)
```

Strict schema rule:

- `from_dict` rejects unknown top-level fields with `ValueError`, following Task Pack C+D.
- Non-core extension goes under `extra`.
- Sub-dataclasses should use the same strict top-level field policy.

Builder design:

- `ReplyContextBuilder.build(...)` should be pure: no AO writes, no context-store writes, no trace mutation.
- Inputs should be explicit: `user_message`, `RouterResponse`, `trace_steps`, `current_ao`, `violations`, `context_store`.
- Empty trace / missing AO / no violations must return a legal context with empty lists and `ao_status=None`.

## 5. Evidence-Based Reply Quality Comparison

### 5.1 Sample Selection

Five benchmark tasks were selected:

| task_id | category | purpose |
|---|---|---|
| `e2e_simple_001` | simple | basic emission-factor result text |
| `e2e_multistep_001` | multi_step | multi-step result + blocked spatial continuation |
| `e2e_constraint_001` | constraint_violation | reject/block response quality |
| `e2e_clarification_101` | multi_turn_clarification | follow-up / clarification-sensitive reply quality |
| `e2e_ambiguous_001` | parameter_ambiguous | normalized colloquial parameter result text |

Current-code run:

```bash
/home/kirito/miniconda3/bin/python evaluation/eval_end2end.py \
  --samples evaluation/results/a_analysis/legacy_reply_samples_5.jsonl \
  --output-dir evaluation/results/a_analysis/legacy \
  --mode full
```

Result:

- run_status: `completed`
- data_integrity: `clean`
- network_failed: `0/5`
- completion_rate: `0.80`
- tool_accuracy: `0.80`
- parameter_legal_rate: `0.80`
- result_data_rate: `0.80`

### 5.2 Legacy / Current Reply Samples

| task_id | current reply quality | excerpt |
|---|---|---|
| `e2e_simple_001` | OK but mechanical. It includes useful values, then appends an English summary line that duplicates the Chinese section. | `## 2020年网约车CO2排放因子查询结果 ... Found emission factors for 1 pollutants...` |
| `e2e_multistep_001` | Weak. It mixes a scenario-label question, macro result delivery, geometry gating, and duplicated meteorology prompt blocks in one reply. | `请问您希望使用哪个情景标签... ## 宏观排放计算结果 ... 🌤 扩散气象条件... 🌤 扩散气象条件...` |
| `e2e_constraint_001` | Good. The block reason is clear and gives legal alternatives. | `摩托车禁止在高速公路行驶... 请将道路类型修改为合法选项...` |
| `e2e_clarification_101` | Poor. The final reply repeats the same emission-factor report multiple times; this is exactly the kind of assembly artifact the LLM writer should clean up. | `## 2022年乘用车NOx排放因子查询结果 ...` repeated three times |
| `e2e_ambiguous_001` | OK but template-like. It captures normalized vehicle/pollutant/year but appends a raw English tool summary. | `## 排放因子查询结果 ... Found CO2 emission factors...` |

### 5.3 Prototype LLM Reply Call

The prototype LLM reply generation was rerun successfully after the environment and sandbox network path were corrected.

Execution notes:

- `.env` was loaded before the call so `QWEN_API_KEY` was available to the process.
- The user-side sandbox/network approval path was corrected before this successful rerun.
- The prototype used `services.llm_client.get_llm_client("synthesis")`.
- Timeout per sample: `20` seconds.
- Input source: `evaluation/results/a_analysis/legacy_rerun/end2end_logs.jsonl`.
- Output JSON: `evaluation/results/a_analysis/llm_reply_samples_5_rerun.json`.
- Summary: `5` total, `5` success, `0` failed.
- Generated at: `2026-04-25T12:58:35.197378+00:00`.

Prototype prompt shape used:

```text
System: You are an emission-analysis assistant reply writer. Rewrite the provided
structured context into one concise, natural Chinese user reply. Use only provided
facts. Do not invent values. If execution was blocked or needs clarification, ask
exactly the needed next question. Avoid duplicating sections.

User: Structured ReplyContext prototype:
{context_json}

Generate the final user-visible reply only.
```

LLM replies and measured latency:

#### `e2e_simple_001` (`simple`) - 7697.13 ms

```markdown
## 2020年网约车CO2排放因子查询结果

**查询参数**  
- 车辆类型: 网约车（系统识别为Passenger Car）  
- 模型年份: 2020年  
- 污染物: CO2  
- 季节: 夏季（默认值）  
- 道路类型: 快速路（默认值）  

**典型排放值 (g/mile)**  
- **低速** (40.2 km/h): 288.26  
- **中速** (80.5 km/h): 228.60  
- **高速** (112.7 km/h): 228.81  

**数据概况**  
- 速度范围: 8.0 - 123.9 km/h  
- 数据点数: 73个  
- 排放趋势: CO2排放随速度先降低后趋于平稳  

> 注意：季节和道路类型参数使用了系统默认值（夏季、快速路）。如需其他季节或道路类型的排放因子，请告知。
```

#### `e2e_multistep_001` (`multi_step`) - 5263.23 ms

```markdown
已为您完成路网文件的CO2排放计算：

- **总排放量**：318.90 kg/h（约7.65吨/天）  
- **计算条件**：2020年、夏季、默认车队组成（以小型客车为主）  
- **路段统计**：共3条路段，单路段排放介于81.25 ~ 142.46 kg/h  

---

但当前数据缺少**空间几何信息**（如坐标、WKT或GeoJSON），无法直接进行扩散分析。

请任选以下一项操作：  
1. **上传补充空间文件**（如GIS/Shapefile/GeoJSON，或含坐标列的表格），并在下一条消息中回复“上传文件”；  
2. 若暂不处理空间分析，请回复“暂停”。
```

#### `e2e_constraint_001` (`constraint_violation`) - 2884.8 ms

```markdown
根据中国现行交通法规，**摩托车禁止驶入高速公路**，因此“摩托车 + 高速公路”这一组合在现实中不成立，系统也无法提供对应的排放因子。

请您将道路类型更改为摩托车允许行驶的合法道路类型，例如：  
- **快速路**  
- **地面道路**

请问您希望查询哪一种？我可以立即为您生成2020年摩托车在该道路类型下的 CO₂ 排放因子曲线。
```

#### `e2e_clarification_101` (`multi_turn_clarification`) - 9160.05 ms

```markdown
已为您查询到2022年乘用车在夏季快速路上的NOx排放因子数据：

**典型排放值（g/mile）**  
- 低速（40.2 km/h）：0.0068  
- 中速（80.5 km/h）：0.0115  
- 高速（112.7 km/h）：0.0209  

**数据概况**  
- 速度范围：8.0 – 123.9 km/h  
- 数据点数：73  
- 数据来源：MOVES（Atlanta）  

如需其他污染物（如CO₂、PM2.5等）、不同季节、道路类型、车型或年份的排放因子，请告诉我。您也可以上传车辆轨迹或路段交通数据，我可协助计算实际排放量。
```

#### `e2e_ambiguous_001` (`parameter_ambiguous`) - 5194.09 ms

```markdown
## 排放因子查询结果

**查询参数**  
- 车型: Passenger Car  
- 年份: 2020  
- 季节: 夏季  
- 道路类型: 快速路  
- 污染物: CO2  

**典型排放值 (g/mile)**  
- 低速 (40.2 km/h): 288.2570  
- 中速 (80.5 km/h): 228.6030  
- 高速 (112.7 km/h): 228.8100  

**数据概况**  
- 速度范围: 8.0 - 123.9 km/h  
- 数据点数: 73  
- 数据来源: MOVES (Atlanta)
```

### 5.4 Side-by-Side Quality Comparison

| task_id | Legacy / current behavior | Prototype LLM behavior | rating | reason |
|---|---|---|---|---|
| `e2e_simple_001` | Gives the correct factor table, but appends a raw English tool summary after the Chinese answer. | Preserves the same facts and removes the raw English summary. | Better | Information is unchanged, but the final answer is cleaner and no longer exposes tool-output residue. |
| `e2e_multistep_001` | Mixes a scenario-label question, macro-emission result, duplicated input-completion blocks, geometry-gating details, and final calculation summary in one long reply. | Separates the completed CO2 calculation from the blocked dispersion step, keeps the key emission numbers, and asks for exactly the geometry recovery decision. | Better | This directly fixes the mixed-intent assembly problem and makes the next user action clear. |
| `e2e_constraint_001` | Clear legal rejection with actionable alternatives. | Nearly identical content with minor formatting normalization. | Equal | The legacy text was already good; LLM did not materially improve or degrade it. |
| `e2e_clarification_101` | Repeats the same 2022 Passenger Car NOx factor report multiple times and appends repeated English summaries. | Produces one consolidated report with the same key values and one concise follow-up sentence. | Better | This solves the motivating repeated-assembly artifact while preserving the important values. |
| `e2e_ambiguous_001` | Correct result table, but ends with a raw English tool summary. | Keeps the table and removes the raw English summary. | Better | The answer remains factual while becoming more user-facing and less template-like. |

Detailed observations for the motivating cases:

- `e2e_clarification_101`: the LLM eliminates the repeated report blocks entirely. It keeps the NOx values, speed range, data count, and source, then compresses follow-up options into a single natural sentence. This is a strong positive signal for using `router_text` as a factual draft plus LLM cleanup.
- `e2e_multistep_001`: the LLM successfully separates "completed macro emission calculation" from "dispersion cannot proceed without geometry". It removes duplicate recovery prompts and asks for one clear next action, which is exactly the intended role of the reply writer layer.

### 5.5 LLM Improvement Verdict

Overall rating: **Better**.

Case-level result:

- Better: `e2e_simple_001`, `e2e_multistep_001`, `e2e_clarification_101`, `e2e_ambiguous_001`.
- Equal: `e2e_constraint_001`.
- Worse: none observed in the five-sample prototype.

The strongest improvements are not cosmetic. The LLM prototype removes repeated assembly artifacts, suppresses raw tool-summary leakage, and separates completed results from blocked follow-up actions. The constraint-violation case was already good, and the LLM correctly preserved the control-flow message instead of over-rewriting it.

Recommendation: **proceed to A.2 directly with the current prompt template as the baseline implementation**.

A.3 can still tune wording after the first integrated tests, but the evidence does not justify another prompt-engineering-only iteration before implementation. The key implementation requirement is to keep `router_text` as a first-class `ReplyContext` field so the LLM has a safe factual draft and the fallback path remains exactly the existing renderer.

## 6. Timeout Threshold Decision

Recommended timeout: **20 seconds**.

Reasoning:

- Current regex/deterministic rendering is not merely "less fluent"; at least two sampled cases show information-assembly defects that can confuse users.
- A too-short timeout would frequently fall back to the same noisy reply surface during the most valuable cases: multi-step, clarification, constraint-follow-up, and data-quality summaries.
- Existing clarification LLM thresholds are 5 seconds because they classify bounded JSON. Final reply writing is longer-form and can tolerate more latency.
- Fallback remains available, so a 20-second timeout does not create a hard failure path.

Caveat:

- Because the prototype LLM call failed during A.1 with `APIConnectionError`, this threshold is based on observed legacy/current reply weakness plus existing architecture latency expectations. Re-run the five prototype calls after network stability if the team wants direct side-by-side prose samples before A.2.

## 7. A.6 Test Strategy Draft

### Unit Tests

1. `ReplyContext.from_dict` rejects unknown top-level field and error message includes the field name.
2. `ReplyContext.from_dict` accepts arbitrary content inside `extra`.
3. `ReplyContextBuilder.build` converts fixture trace + AO + violations into expected summaries.
4. `ReplyContextBuilder.build` handles empty trace / missing AO / no violations with empty lists and `ao_status=None`.
5. `ReplyContextBuilder.build` includes `data_quality_report` from `context_store.get_by_type("data_quality_report")` when present.

### Parser Tests

6. LLM parser returns `(reply, metadata)` when mock LLM succeeds.
7. LLM parser raises `LLMReplyTimeout` on timeout.
8. LLM parser raises `LLMReplyError` on provider/API error.
9. Prompt rendering includes tool summaries, violations, pending clarifications, AO status, and data-quality report summary when present.

### GovernedRouter Integration Tests

10. `ENABLE_LLM_REPLY_PARSER=true` + LLM success returns LLM text and records non-fallback metadata.
11. `ENABLE_LLM_REPLY_PARSER=true` + timeout falls back to current legacy response text and records `fallback=True`.
12. `ENABLE_LLM_REPLY_PARSER=false` uses legacy response text and does not call LLM parser.
13. ConstraintViolationWriter consumer still runs before reply context construction.
14. `restore_persisted_state` does not need to rebuild builder state because builder is pure.

### Regression Tests

15. NaiveRouter does not import or invoke LLM reply parser.
16. Existing synthesis/rendering helper tests continue to pass because legacy path remains fallback.
17. Existing router state-loop tests continue to pass with feature flag disabled or mocked parser.

## 8. Proposed A.2-A.5 Implementation Plan

1. Add `core/reply/` package:
   - `reply_context.py`
   - `reply_context_builder.py`
   - `llm_parser.py`
   - optional `legacy_adapter.py` if fallback needs a named wrapper around current `RouterResponse.text`.
2. Add `ENABLE_LLM_REPLY_PARSER=true` and `LLM_REPLY_PARSER_TIMEOUT_SEC=20` to `config.py` and `.env.example`.
3. In `GovernedRouter.__init__`, construct parser objects only at governance layer. Do not change `UnifiedRouter`.
4. In `GovernedRouter.chat(...)`, after B's violation consumer and after contract `after_turn(...)`, build `ReplyContext`.
5. If flag enabled, call LLM parser with timeout. On `LLMReplyTimeout` / `LLMReplyError`, log and preserve legacy `result.text`.
6. Record reply metadata into `result.trace`, e.g. `trace["reply_parser"] = {"mode": "llm"|"legacy", "fallback": bool, "reason": ...}`.
7. Keep all frontend payload fields untouched.

## 9. Open Questions For User Confirmation

1. A.1 prototype LLM generation failed due connectivity. Proceed with the 20-second threshold based on observed legacy/current reply defects, or rerun prototype samples after network is fixed?
2. Should `ReplyContext` include `router_text` as a first-class field? I recommend yes: it gives the LLM a safe fallback draft while the structured fields constrain factual content.
3. Should `data_quality_report` be a core optional field or live under `extra` for A? I recommend `extra["data_quality_report"]` for this pack to avoid over-expanding the core schema before Task Pack A's reply prompt is proven.
