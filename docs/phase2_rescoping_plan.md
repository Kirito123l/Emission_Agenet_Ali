# Phase 2 Rescoping Plan: LLMify Rule-Based Decision Points

## Section 0: Round 3 Artifact Used

An official `evaluation/reports/round3_report.md` was not present. The closest Round 3 equivalent used for this rescoping is:

- `EXPLORATION_ROUND3_COGNITIVE_FLOW.md`

Why this file qualifies:

- It contains the 10-decision table with `RULE-driven` / `HYBRID` labels, including Decisions 7-10 (`EXPLORATION_ROUND3_COGNITIVE_FLOW.md:108-121`).
- It documents Breakpoint-2-relevant failures such as rule-only clarification parsing and constraint-feedback drift (`EXPLORATION_ROUND3_COGNITIVE_FLOW.md:16-21`, `90-106`).

## Section 1: Decision Point Code Location

### 1.1 Decision 7: 追问文本生成

Current Round 3 baseline location:

- Router/input-completion prompt builder: `core/input_completion.py:565-607`
- Router activation sites: `core/router.py:6428-6444`, `7655-7661`

Legacy OA clarification path:

- Required-slot question builder: `core/contracts/clarification_contract.py:996-1025`
- Optional-slot probe builder: `core/contracts/clarification_contract.py:1027-1045`
- Optional-slot wording LLM hook: `core/contracts/clarification_contract.py:1047-1083`

Split-contract path:

- `ExecutionReadinessContract` reuses the same inherited builders when it decides to clarify: `core/contracts/execution_readiness_contract.py:247-251`, `391-396`
- The shared split support layer does not replace question generation; it only provides Stage 2 slot-filler telemetry: `core/contracts/split_contract_utils.py:29-100`

Input:

- Router path consumes `InputCompletionRequest` fields such as `reason_summary`, `target_field`, `missing_requirements`, `options`, and `repair_hint` (`core/input_completion.py:565-607`).
- OA path consumes `tool_name`, `snapshot`, `missing_slots`, `rejected_slots`, and optional `llm_question` (`core/contracts/clarification_contract.py:996-1025`).

Output:

- Router path emits a bounded multi-line prompt string for the user (`core/input_completion.py:565-607`).
- OA path emits a single clarification question string (`core/contracts/clarification_contract.py:996-1045`).

Rule structure:

- Router path is pure template formatting.
- Legacy/split OA required-slot questions are hardcoded by tool/slot branch plus generic fallback.
- Only optional probe wording has an LLM assist, and it is strictly fallback-shaped around a preselected slot (`core/contracts/clarification_contract.py:1047-1083`).

Failure example:

- `e2e_clarification_101` over-clarifies all the way to `road_type` after the benchmark-required values are already given, exhausting the turn budget before execution (`evaluation/results/wave5a_main_multiturn_smoke_E/end2end_logs.jsonl:1`).
- `e2e_clarification_107` and `e2e_clarification_110` show the same shape: factor-query tasks keep emitting clarification text until `pending_slot=road_type`, `probe_count=2`, and still do not force proceed (`evaluation/results/wave5a_main_multiturn_smoke_E/end2end_logs.jsonl:7`, `10`; `evaluation/diagnostics/wave5a_stage2_gate_failure.md:48-86`).

### 1.2 Decision 8: 解析追问回复

Current Round 3 baseline location:

- Deterministic reply detector: `core/input_completion.py:372-399`
- Deterministic reply parser: `core/input_completion.py:402-562`
- Router parse wrapper: `core/router.py:6505-6525`
- Router consume site: `core/router.py:7620-7680`

Legacy OA clarification path:

- There is no dedicated bounded reply parser. The next turn is reinterpreted through:
  - Stage 1 rule hint extraction: `core/contracts/clarification_contract.py:616-650`
  - Stage 2 generic slot-filler LLM: `core/contracts/clarification_contract.py:652-690`
  - Stage 3 standardization / rejection pass: `core/contracts/clarification_contract.py:880-920`

Split-contract path:

- Split intent/readiness continuation also reuses the same generic Stage 2 slot filler through `SplitContractSupport._run_stage2_llm_with_telemetry(...)` (`core/contracts/split_contract_utils.py:29-100`) and then normalizes the returned slot payload via inherited Stage 3 (`core/contracts/clarification_contract.py:880-920`).

Input:

- Router path consumes the active `InputCompletionRequest`, raw `user_reply`, and optional supporting file (`core/input_completion.py:402-562`).
- OA split path consumes the full turn text, current snapshot, current AO classification, and tool slot schema (`core/contracts/split_contract_utils.py:40-59`).

Output:

- Router path emits `InputCompletionParseResult` / `InputCompletionDecision` (`core/input_completion.py:402-562`).
- OA split path emits a refreshed slot snapshot plus tool/stance hints (`core/contracts/split_contract_utils.py:73-100`).

Rule structure:

- Router path is deterministic: pause phrases, index selection, numeric extraction, option alias matching, uploaded-file handling, and one fixed default-profile phrase detector (`core/input_completion.py:418-562`).
- Split path is already partially LLMified, but it is generic slot refilling, not a dedicated pending-slot reply parser.

Failure example:

- Round 3 already identified the blind spot: a natural reply like “刚才说过冬天啊” does not match the deterministic parser because `parse_input_completion_reply` only handles fixed phrases / numbers / aliases / files (`EXPLORATION_ROUND3_COGNITIVE_FLOW.md:20-21`).
- In current Wave 5a logs, `e2e_clarification_102` and `e2e_clarification_104` show the split path still mishandles continuation semantics after clarification, leading to duplicate execution rather than a single converged turn (`evaluation/results/wave5a_main_multiturn_smoke_E/end2end_logs.jsonl:2`, `4`).

### 1.3 Decision 9: artifact 就绪判断

Current rule location:

- Action/readiness affordance engine: `core/readiness.py:900-1214`
- Dependency token validator: `core/tool_dependencies.py:181-265`
- Router execution gate wrapper: `core/router.py:9190-9246`
- Router pre-execution short-circuit / input-completion handoff: `core/router.py:10798-10908`

Split-contract host:

- `ExecutionReadinessContract` is the Phase 2 integration host for any dependency-aware clarification because it already owns the “clarify vs proceed” decision before fallback execution (`core/contracts/execution_readiness_contract.py:32-512`), even though the canonical dependency check itself still lives in router/readiness.

Input:

- Tool name, arguments, available result tokens, context-store artifact availability, geometry support, and current response payloads (`core/tool_dependencies.py:181-265`, `core/readiness.py:900-1214`).

Output:

- `DependencyValidationResult` with `missing_tokens`, `stale_tokens`, and message (`core/tool_dependencies.py:181-265`).
- `ActionAffordance` / repairable vs blocked decision (`core/readiness.py:975-1177`).

Rule structure:

- Pure config-and-token-driven readiness logic.
- No LLM participates in inferring “the user is really asking for hotspot ranking, but hotspot is not ready because emission exists while dispersion/hotspot does not.”

Failure example:

- `e2e_heldout_multistep_001` should be `calculate_macro_emission -> analyze_hotspots`, but the system goes `calculate_macro_emission -> render_spatial_map -> query_emission_factors`, which is a classic downstream-artifact readiness miss (`evaluation/results/wave5a_heldout_multistep_smoke_E/end2end_logs.jsonl:1`).
- `e2e_heldout_multistep_006` should be `calculate_micro_emission -> analyze_hotspots`, but after micro execution the run falls into `input_completion_required` instead of choosing the downstream artifact step (`evaluation/results/wave5a_heldout_multistep_smoke_E/end2end_logs.jsonl:4`).
- `e2e_clarification_120` should be `calculate_macro_emission -> calculate_dispersion`, but the continuation repeatedly returns to macro emission while meteorology clarification text is emitted (`evaluation/results/wave5a_main_multiturn_smoke_E/end2end_logs.jsonl:13`).

### 1.4 Decision 10: 约束违反检测反馈

Current rule location:

- Cross-constraint engine: `services/cross_constraints.py:84-164`
- Constraint catalog: `config/cross_constraints.yaml:3-68`
- Router preflight block path: `core/router.py:2241-2295`
- Standardization-engine block path: `services/standardization_engine.py:643-668`

Existing but weak feedback/memory hooks:

- FactMemory has both transient and cumulative constraint slots (`core/memory.py:84-89`).
- AO block rendering already knows how to display cumulative constraint violations (`core/assembler.py:420-451`).
- OASC can copy seen violations from session memory into AO history (`core/contracts/oasc_contract.py:353-379`).
- But `append_constraint_violation(...)` currently has no live caller in router/executor paths (`rg -n "append_constraint_violation\\(" core/ services/` only finds the definition in `core/memory.py:195-212`).

Input:

- Standardized params plus optional `tool_name` (`services/cross_constraints.py:84-164`).

Output:

- `CrossConstraintResult` with `violations` and `warnings` (`services/cross_constraints.py:53-65`, `84-164`).
- Router preflight block text or standardization error (`core/router.py:2261-2295`, `services/standardization_engine.py:651-666`).

Rule structure:

- Pure YAML rule matching.
- Feedback to next-turn LLM is infrastructurally possible, but current write-path wiring is incomplete.

Failure example:

- Round 3 documented constraint tasks where the evaluator looked for either the fixed string `参数组合不合法` or a `cross_constraint_violation` record, but LLM no-tool replies produced neither, so the constraint state did not survive structurally (`EXPLORATION_ROUND3_COGNITIVE_FLOW.md:103-106`).

## Section 2: LLMification Design Per Decision Point

### 2.1 Decision Point 7: 追问文本生成

Current rule behavior:

- Router input completion always renders the same structured template from `InputCompletionRequest` (`core/input_completion.py:565-607`).
- OA contracts still choose required-slot questions via hardcoded tool/slot branches (`core/contracts/clarification_contract.py:996-1025`).
- Only optional probe wording has a narrow LLM hook (`core/contracts/clarification_contract.py:1047-1083`).

Proposed LLM behavior:

- Keep the rule layer responsible for deciding which slot is missing.
- Let an LLM generate the natural-language surface form for that already-determined slot, using:
  - resolved tool
  - pending slot
  - already-filled snapshot
  - last user turn
  - whether this is required-slot clarification vs optional probe

Prompt sketch:

> You are rewriting a bounded clarification question for a traffic-emission agent. The system has already decided which single slot must be asked about. Ask only about that slot, in one short sentence, using the user’s prior wording when helpful. Do not introduce new slots, do not broaden scope, and do not explain the whole workflow. Return JSON with `clarification_question`.

Where it injects:

- Primary Phase 2 host: `core/contracts/execution_readiness_contract.py:247-251` and `391-396`
- Reuse/extend existing helper: `core/contracts/clarification_contract.py:996-1083`

Fallback:

- If the LLM fails or times out, keep `_build_question(...)` / `format_input_completion_prompt(...)` exactly as today.

Risk:

- Over-generation: asks for more than one slot.
- Under-generation: fails to ask a legally necessary slot.

Mitigation:

- The rule layer still chooses the slot set.
- The LLM only verbalizes a preselected single-slot ask.
- Reject outputs mentioning slots outside `missing_slots[:1]` or `pending_slot`.

Assessment:

- This improves product UX and some turn-budget failures, but it is not the best first investment if ordered strictly by current failure share.

### 2.2 Decision Point 8: 解析追问回复

Current rule behavior:

- Router `parse_input_completion_reply(...)` only handles fixed patterns, numeric replies, aliases, and upload markers (`core/input_completion.py:402-562`).
- Split contracts already have a generic Stage 2 LLM slot filler (`core/contracts/split_contract_utils.py:29-100`), but it is not specialized to “one active pending slot on a clarification turn.”

Current failure mode:

- Natural-language clarification replies can miss the deterministic router parser entirely (`EXPLORATION_ROUND3_COGNITIVE_FLOW.md:20-21`).
- Split continuation can still interpret a follow-up as a fresh execution opportunity and duplicate the tool, as in `e2e_clarification_102` and `e2e_clarification_104` (`evaluation/results/wave5a_main_multiturn_smoke_E/end2end_logs.jsonl:2`, `4`).

Proposed LLM behavior:

- Introduce a dedicated pending-slot filler prompt, not a generic full-snapshot refill.
- Inputs:
  - active AO / `PendingObjective.PARAMETER_COLLECTION`
  - pending slot name
  - allowed canonical values for that slot
  - already-confirmed snapshot
  - latest user turn plus previous clarification question
- Output:
  - `{slot_name, value, confidence, evidence_span, should_retry}`

Where it injects:

- Preferred host: `SplitContractSupport._run_stage2_llm_with_telemetry(...)` (`core/contracts/split_contract_utils.py:29-100`)
- Consume in `ExecutionReadinessContract.before_turn(...)` while parameter collection is active (`core/contracts/execution_readiness_contract.py:32-512`)
- Router fallback path can continue to use `parse_input_completion_reply(...)` unchanged (`core/router.py:6505-6525`, `7620-7680`)

Fallback:

- If the dedicated slot filler is uncertain or times out, fall back to:
  - deterministic parser on the router path
  - current Stage 1/Stage 3 normalization on the split path

Risk:

- Hallucinated slot values.
- Latency added to every clarification turn.

Mitigation:

- Only trust the LLM when `pending_slot` is known and the extracted value stays inside that slot’s legal value space after standardization.
- Require confidence above threshold and reject answers that fill unrelated slots.
- Reuse the existing split Stage 2 call rather than adding a second extra call where possible.

Assessment:

- This is the most thesis-pure Breakpoint-2 fix, but it is only the third-largest current failure family in the latest Wave 5a target corpus.

### 2.3 Decision Point 9: artifact 就绪判断

Current rule behavior:

- The router blocks or reroutes purely from tokenized prerequisites and readiness affordances (`core/tool_dependencies.py:181-265`, `core/readiness.py:975-1177`, `core/router.py:10798-10908`).
- The system does not semantically reinterpret a user ask like “找出最严重的前5段路” as “the user wants hotspot analysis, and the missing prerequisite is hotspot-ready upstream state.”

Stage options:

- Option A, Phase 2 partial: add an LLM dependency-awareness layer inside split readiness.
- Option B, Phase 3 complete: separate Dependency Contract / richer planner-driven remediation.

Recommended Phase 2 scope:

- Do Option A only.
- Given:
  - requested deliverable from user text
  - currently available artifacts / result tokens
  - current tool already executed
  - file context
- Ask the LLM to choose one of:
  - `proceed_current_step`
  - `ask_for_missing_dependency`
  - `redirect_to_prerequisite_tool`

Where it injects:

- Phase 2 host: `core/contracts/execution_readiness_contract.py:32-512`
- The existing rule validator remains the hard safety rail: `core/tool_dependencies.py:181-265`

Fallback:

- If the LLM is uncertain, keep current rule behavior: block or short-circuit via readiness/input-completion.

Risk:

- The LLM may invent a chain that the system cannot support.

Mitigation:

- Constrain outputs to tools already present in the tool graph and action catalog.
- Require that any redirected prerequisite tool matches `suggest_prerequisite_tool(...)` or current action-catalog affordances (`core/tool_dependencies.py:268-276`, `core/readiness.py:1217-1296`).

Assessment:

- This is the highest-share current failure family.
- It is not the original Round 3 “natural language reply parser” case, but it is still a rule-to-LLM decision-point upgrade and now the biggest blocker in the current Wave 5a target corpus.

### 2.4 Decision Point 10: 约束违反反馈

Current behavior:

- The validator is already rule-based and correct enough at detection time (`services/cross_constraints.py:84-164`).
- The real gap is that violation state is not reliably written into the session/AO memory that the next-turn LLM sees, even though the AO block can already render it (`core/assembler.py:420-451`; no live caller for `FactMemory.append_constraint_violation(...)`, `core/memory.py:195-212`).

Proposed behavior:

- Do not add a new LLM call.
- When preflight or standardization emits a violation/warning, write it into:
  - `current_ao.constraint_violations`
  - `FactMemory.constraint_violations_seen`
  - `FactMemory.cumulative_constraint_violations`
- Then let the existing AO block surface it on the next turn.

Where it injects:

- `core/router.py:2241-2295`
- `services/standardization_engine.py:643-668`
- existing memory plumbing in `core/memory.py:195-212`, `262-282`

Assessment:

- Small, infrastructural, worth doing.
- But current Wave 5a benchmark blockers are elsewhere, so it should not be Phase 2’s first sub-phase.

## Section 3: Implementation Roadmap

The order below is driven by current failure share, not engineering convenience.

Current corpus used for ordering:

- `evaluation/results/wave5a_main_multiturn_smoke_E/end2end_metrics.json`: `13/20` failures on current `multi_turn_clarification`
- `evaluation/results/wave5a_heldout_multistep_smoke_E/end2end_metrics.json`: `5/8` failures on current held-out `multi_step`

Mapped-failure classification:

- `17/18` current failures were mappable to Decisions 7/8/9/10 by log inspection.
- `1/18` (`e2e_clarification_119`) is an out-of-scope implementation bug: split Stage 2 emitted string confidence `"high"` and Stage 3 crashed on `float(confidence)` (`evaluation/results/wave5a_main_multiturn_smoke_E/end2end_logs.jsonl:12`; `core/contracts/clarification_contract.py:913-915`).

Decision-share breakdown of the 17 mappable failures:

| Decision point | Count | Share | Representative tasks |
|---|---:|---:|---|
| Decision 9: artifact/dependency readiness | 8 | 47.1% | `e2e_clarification_111`, `115`, `120`; `e2e_heldout_multistep_001`, `002`, `004`, `006`, `008` |
| Decision 7: clarification text / over-clarification policy | 7 | 41.2% | `e2e_clarification_101`, `103`, `105`, `107`, `110`, `114`, `118` |
| Decision 8: clarification-reply interpretation / continuation consumption | 2 | 11.8% | `e2e_clarification_102`, `104` |
| Decision 10: constraint feedback carry-over | 0 | 0.0% | no current Wave 5a target-slice failures; gap remains architectural |

### 3.1 Phase 2α: Decision 9 Partial Dependency Awareness

Why first:

- Highest current failure share: `8/17 = 47.1%`
- Directly targets the held-out `multi_step` plateau at `37.5%` (`evaluation/results/wave5a_heldout_multistep_smoke_E/end2end_metrics.json`)

Scope:

- LLMify the semantic interpretation of downstream deliverable intent while keeping the hard dependency graph rule-enforced.

Expected benchmark impact:

- Held-out `multi_step`: `37.5% -> 60%+`
- Main `multi_turn_clarification`: modest lift on macro→dispersion style tasks (`111`, `115`, `120`)

Estimated effort:

- `5-7` Codex days

### 3.2 Phase 2β: Decision 7 Clarification Text Generation

Why second:

- Second-largest current failure share: `7/17 = 41.2%`
- These are mostly turn-budget losses caused by over-asking on factor tasks (`evaluation/diagnostics/wave5a_stage2_gate_failure.md:48-86`)

Scope:

- Keep slot selection rule-based.
- LLMify only the surface wording and budget-aware narrowing of the question.

Expected benchmark impact:

- Main `multi_turn_clarification`: `35% -> 45-50%`
- Product UX: significant improvement

Estimated effort:

- `3-5` Codex days

### 3.3 Phase 2γ: Decision 8 Clarification-Reply Slot Filling

Why third:

- Smallest non-zero current share: `2/17 = 11.8%`
- Still the most direct embodiment of Breakpoint 2’s original statement: rules cannot absorb natural-language clarification replies.

Scope:

- Replace generic “full snapshot refill” continuation handling with a dedicated pending-slot extractor on split clarification turns.

Expected benchmark impact:

- Main `multi_turn_clarification`: targeted lift on duplicate-execution / wrong-consumption tasks like `102`, `104`
- Overall: smaller benchmark delta than 2α or 2β unless paired later with them

Estimated effort:

- `4-6` Codex days

### 3.4 Phase 2δ: Decision 10 Constraint Feedback Infrastructure

Why fourth:

- `0/17` share in the current Wave 5a target corpus
- Still necessary infrastructure, but not the main benchmark blocker right now

Scope:

- Wire live constraint violations into AO/session memory and AO block injection.

Expected benchmark impact:

- Small direct benchmark movement
- Better next-turn coherence on constraint-violation tasks

Estimated effort:

- `1-2` Codex days

## Section 4: Relationship to Wave 2-5a

### 4.1 Did Wave 2-5a actually close Breakpoint 2?

No, not in the sense defined by Round 3.

Evidence:

- The split OA path is still off by default in HEAD: `ENABLE_CONTRACT_SPLIT=false` (`config.py:80-82`), so the split contracts are not the default production path (`core/governed_router.py:46-92`).
- Decision 7 remains rule-first even inside OA:
  - router prompt builder is pure template code (`core/input_completion.py:565-607`)
  - required-slot OA question builder is hardcoded (`core/contracts/clarification_contract.py:996-1025`)
  - only one narrow prompt-generation LLM hook exists for optional probes (`core/contracts/clarification_contract.py:1047-1083`)
- Decision 8 remains rule-only on the router input-completion path:
  - `parse_input_completion_reply(...)` has zero LLM calls (`core/input_completion.py:402-562`)
  - the router consumes that rule parser directly (`core/router.py:6505-6525`, `7620-7680`)
- Wave 2-5a did add one real LLMified continuation mechanism in split mode:
  - generic Stage 2 slot filling (`core/contracts/split_contract_utils.py:29-100`)
  - legacy equivalent `ClarificationContract._run_stage2_llm(...)` (`core/contracts/clarification_contract.py:652-690`)

Conclusion:

- Wave 2-5a partially LLMified split clarification handling.
- It did not replace the Round 3 decision points on the default production clarification path.
- So it was architectural restructuring plus partial substrate work, not closure of Breakpoint 2.

### 4.2 What from Wave 2-5a is genuinely worth keeping

- `ExecutionReadinessContract` is the right host for Decisions 7 and 9 because it already owns the pre-execution `clarify/proceed` boundary (`core/contracts/execution_readiness_contract.py:32-512`).
- `IntentResolutionContract` and `SplitContractSupport` are the right host for Decision 8 because they already centralize turn-level slot-filling context and Stage 2 telemetry (`core/contracts/intent_resolution_contract.py:24-132`, `core/contracts/split_contract_utils.py:29-100`).
- `ExecutionContinuation` is still valuable as the pending-state carrier (`core/execution_continuation.py:8-87`).
- AO block / persistent-fact scaffolding is valuable for Decision 10 because the render path already exists (`core/assembler.py:420-451`).
- Wave 2-5a telemetry is valuable because it makes per-decision ablation possible (`evaluation/diagnostics/wave3_stage2_multiturn_gate_failure.md:64-83`, `core/contracts/execution_readiness_contract.py:564-624`).

### 4.3 What Wave 2-5a code is mainly side-product, not Breakpoint-2 closure

- `probe_limit` calibration is real behavior, but it is benchmark-budget tuning, not natural-language cognition closure (`evaluation/diagnostics/wave5a_stage2_gate_failure.md:66-86`; `core/contracts/execution_readiness_contract.py:227-240`, `350-367`).
- `clarification_followup_slots` / `confirm_first_slots` migration is useful architecture work, but it mainly moved rule policy into split state rather than making the system better at understanding natural-language replies (`evaluation/diagnostics/wave4_stage2_gate_failure.md:60-67`; `core/contracts/execution_readiness_contract.py:129-140`, `711-727`).
- Stance splits and exploratory/directive branching are structurally cleaner, but they are not the core fix for “rules cannot absorb natural language.”

### 4.4 What can be simplified after rescoping

- The repo currently has two clarification stacks:
  - router input-completion (`core/input_completion.py`, `core/router.py`)
  - OA split clarification/readiness (`core/contracts/*`)
- Phase 2 should not add a third stack.
- The simplest direction is to treat the split contracts as the long-term host and keep the router parser as fallback compatibility until split is actually promoted.

## Section 5: Testing and Evaluation Plan

Phase 2 should only be considered closed when the moved benchmark number can be tied to the intended decision point, not just to aggregate score drift.

### 5.1 Decision 9 / Phase 2α

Primary evidence:

- `wave5a_heldout_multistep_smoke_E`: `37.5% -> 60%+`

Ablation:

- flag off: current rule-only readiness
- flag on: LLM dependency-awareness layer
- prove that tasks like `e2e_heldout_multistep_001`, `004`, `006`, `008` switch from wrong downstream tool choice / repairable halt to the expected downstream artifact chain

Trace proof:

- logs must show the dependency-aware layer selecting either the prerequisite tool or a dependency clarification before the old hard-stop path

### 5.2 Decision 7 / Phase 2β

Primary evidence:

- main `multi_turn_clarification`: `35% -> 45-50%`

Ablation:

- same slot selection, old rule wording vs LLM wording
- verify that `pending_slot=road_type` factor-task loops shrink rather than merely changing phrasing

Trace proof:

- fewer turn-budget exhaustions like `e2e_clarification_101`, `107`, `110`

### 5.3 Decision 8 / Phase 2γ

Primary evidence:

- targeted clarification-reply slice should be added around pending-slot continuation turns, because the current main benchmark under-samples this family
- existing benchmark tasks `e2e_clarification_102` and `104` should stop duplicate execution

Ablation:

- generic split Stage 2 refill vs dedicated pending-slot filler

Trace proof:

- the continuation turn must bind to the pending slot/tool and not create a second fresh execution

### 5.4 Decision 10 / Phase 2δ

Primary evidence:

- no dedicated score target is necessary for the first pass; the key evidence is next-turn AO block visibility

Ablation:

- with memory wiring off vs on, same constraint-violation task should show cumulative constraint text in AO block injection and session memory

Trace proof:

- `cumulative_constraint_violations_present=true` in AO block telemetry (`core/assembler.py:531-553`)

### 5.5 Anti-drift Rule

To avoid another Wave-style thesis drift:

- each sub-phase gets one decision point, one host file, one flag, one benchmark slice
- do not accept “score up” if traces show the old rule path still doing the real work
- require at least one negative ablation proving the new LLM decision is load-bearing

## Section 6: Risks and Open Questions

- Latency budget risk is real. Current split Stage 2 already averages `6865.95 ms` on the Wave 5a main multi-turn slice (`evaluation/results/wave5a_main_multiturn_smoke_E/end2end_metrics.json`). Phase 2 should prefer reusing this call over adding two more per turn.
- Hallucination risk is highest for Decision 8. The mitigation has to be slot-bounded extraction plus post-standardization legality checks.
- Decision 7 must not break structured UX such as bounded option prompts or the meteorology confirm card. The LLM should generate wording around a fixed option set, not replace the option set itself.
- `UNVERIFIED: whether production will actually run split contracts after Phase 2 lands.` Code still defaults `ENABLE_CONTRACT_SPLIT=false` (`config.py:80-82`).
- `UNVERIFIED: whether the router input-completion path will remain a production fallback long enough that it also needs explicit Decision-8 LLMification.` Current code keeps both stacks alive.

## Section 7: Explicit Recommendation

Recommend **Phase 2α: Decision 9 partial dependency awareness** first.

Why this one:

- It is the largest current mapped failure family: `8/17 = 47.1%` of the current Wave 5a target-slice failures.
- It is independently shippable in `1-2` weeks because it can be added as a bounded layer inside `ExecutionReadinessContract` without waiting for Decisions 7, 8, or 10.
- It has a clean benchmark contract: the held-out `multi_step` slice is already isolated and currently stuck at `37.5%`.
- It is still a genuine Phase 2 instance of “LLMify a rule decision”: today the system hard-stops on tokenized prerequisites; the proposed change lets the model interpret the user’s downstream deliverable ask against current artifacts and choose the right clarify/redirect action while the rule layer remains the safety rail.

This is not the purest Breakpoint-2 example. Decision 8 is purer. But on current evidence, Decision 9 is the best first slice because it removes the biggest remaining rule bottleneck with a standalone measurable win. Decision 7 should follow immediately after if 2α lands cleanly.
