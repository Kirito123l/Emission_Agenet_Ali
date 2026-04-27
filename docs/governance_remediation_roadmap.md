# Governance Remediation Roadmap

## 1. Method

This roadmap merges the 14 MISALIGNED decision points, 4 cross-cutting
patterns, and 4 L-level failure modes from `docs/phase2_governance_audit.md`
and the Phase 2 failure-mode task evidence. The merge rule is: when one
cross-cutting pattern explains several decision points, treat it as one
engineering task unless the fixes require different owners or risk profiles.

All uncertain conclusions are marked needs human review.

## 2. Task Inventory

### TASK-1 Runtime-Default Optionals Must Not Block Fresh Factor Execution

- **Scope**:
  - Audit decision points: §3.3.5, §3.3.6, §3.1.3.
  - Failure modes: L3, P3.
- **Current State**:
  - Legacy `ClarificationContract` treats `model_year` as an unfilled optional
    without a declarative default and enters collection mode on fresh first
    turns.
  - This blocks `query_emission_factors` even though runtime execution can
    default `model_year=2020`.
- **Target State**:
  - Fresh, non-confirm-first factor queries with all required slots filled
    should proceed and allow runtime default injection.
  - Explicit confirm-first or resumed pending parameter collection should keep
    asking when the user requested confirmation.
- **Fix Type**: reclassify / delete-rule.
- **Files to Modify**:
  - `core/contracts/clarification_contract.py:13-23`, `:335-338`,
    `:1271-1288`.
  - `tests/test_clarification_contract.py:519-558`, `:675-713`, `:620-629`
    for expectation updates/additions.
- **Engineering Effort**: S (< 30 lines, 1-2 files).
- **Expected Impact**:
  - Expected to improve L3-shaped failures such as `e2e_codeswitch_161` and
    held-out shapes like `e2e_heldout_simple_003` / `e2e_heldout_param_002`.
  - Best-guess baseline impact: +5 to +10 pp.
- **Risk**:
  - Low if limited to fresh, non-confirm-first turns and runtime-defaultable
    optionals only.
  - Main risk is suppressing a user-desired confirmation question if the
    confirm-first guard is implemented incorrectly.
- **Dependencies**: None.
- **Verification**:
  - Unit: `tests/test_clarification_contract.py`, `tests/test_contract_split.py`.
  - Smoke: pre/post Qwen smoke over single-turn factor categories and the
    specific `e2e_codeswitch_161`, `e2e_colloquial_141`, `e2e_ambiguous_001`
    slices.

### TASK-2 Harden Evaluation Session Isolation

- **Scope**:
  - Audit decision points: §3.2.1, §3.6.1.
  - Failure modes: L1.
- **Current State**:
  - `evaluation/eval_end2end.py:1279` creates a task session ID from
    `eval_{task_id}`.
  - `evaluation/run_oasc_matrix.py:174-181` clears only `eval_*.json` and
    `eval_naive_*.json`; whether all AO/context stores and non-history files
    are cleared is needs human review.
- **Target State**:
  - Each benchmark task starts with empty AO history, turn counter, context
    store, and router memory.
  - Single-turn tasks should assert `turn=1` and fail fast if polluted.
- **Fix Type**: refactor / merge-duplicates.
- **Files to Modify**:
  - `evaluation/run_oasc_matrix.py:174-181`.
  - `evaluation/eval_end2end.py:1273-1300`.
  - Additional state paths under `data/sessions/` need human review.
- **Engineering Effort**: M (30-100 lines, 2-4 files).
- **Expected Impact**:
  - Expected to stabilize L1 tasks such as `e2e_ambiguous_001`.
  - Best-guess baseline impact: +2 to +6 pp; confidence is lower because the
    exact contamination source needs human review.
- **Risk**:
  - Low for evaluation-only changes; medium if production session cleanup is
    accidentally reused.
- **Dependencies**: None.
- **Verification**:
  - Unit: add an eval-harness isolation test that seeds stale history and
    verifies the next run starts at turn 1.
  - Smoke: run the same single-turn smoke twice and compare turn telemetry.

### TASK-3 Make AO Turn Classification LLM-First for Ambiguous Short Replies

- **Scope**:
  - Audit decision points: §3.2.1, §3.2.2, §3.2.3, §3.2.4.
  - Failure modes: L2, P2.
- **Current State**:
  - Rule layer returns high-confidence CONTINUATION/REVISION for short replies
    and substring revision markers before Layer 2 can arbitrate.
  - Layer 2 verdicts below `ao_classifier_confidence_threshold=0.7` are
    discarded in favor of NEW_AO fallback.
- **Target State**:
  - Keep cheap rules only for structurally certain cases such as first message
    in a truly empty session or pure file supplement.
  - Route short clarification replies and revision-like substrings through the
    LLM classifier, with rule hits treated as evidence, not final decisions.
- **Fix Type**: defer-to-llm / delete-rule.
- **Files to Modify**:
  - `core/ao_classifier.py:202-269`, `:334-358`, `:283-289`.
  - `core/contracts/oasc_contract.py:44-72`.
  - `tests/test_ao_classifier.py` and continuation/e2e tests.
- **Engineering Effort**: M.
- **Expected Impact**:
  - Expected to improve `e2e_clarification_101` and duplicate-execution
    multi-turn failures.
  - Best-guess baseline impact: +5 to +12 pp.
- **Risk**:
  - Medium: more LLM calls increase latency and may change production
    continuation behavior.
- **Dependencies**: TASK-2 should land first if evaluation contamination is
  still present.
- **Verification**:
  - Unit: classifier cases for short pollutant replies, `重新查询`, `改成冬季`,
    and file-only supplement.
  - Smoke: multi-turn clarification three-run comparison.

### TASK-4 Reconcile Confirm/Reversal/Abandon Substring Signals with LLM Outputs

- **Scope**:
  - Audit decision points: §3.3.8, §3.4.1, §3.4.3, §3.4.8.
  - Failure modes: L2, L3, P2.
- **Current State**:
  - `_detect_confirm_first`, `has_reversal_marker`,
    `has_probe_abandon_marker`, and stance reversal matching can override or
    bypass LLM semantic output.
- **Target State**:
  - Substring matches become advisory evidence inside an arbitration function.
  - If LLM stance/intent disagrees with a substring rule, the disagreement is
    logged and the LLM leads unless a domain-hard constraint applies.
- **Fix Type**: defer-to-llm / merge-duplicates.
- **Files to Modify**:
  - `core/contracts/clarification_contract.py:1447-1508`.
  - `core/continuation_signals.py:4-37`.
  - `core/contracts/stance_resolution_contract.py:32-52`.
  - `core/contracts/intent_resolution_contract.py:39-83`.
- **Engineering Effort**: M.
- **Expected Impact**:
  - Expected to reduce wrong continuation/revision and over-abandon behavior.
  - Best-guess baseline impact: +3 to +8 pp.
- **Risk**:
  - Medium: cheap deterministic gates currently provide latency control.
- **Dependencies**: TASK-3 preferred first.
- **Verification**:
  - Unit: overlapping marker strings including `重新查询`, `重新计算`, `等等`,
    and `直接继续`.
  - Smoke: multi-turn clarification and user_revision categories.

### TASK-5 Repair Snapshot and Stage Data-Flow Invariants

- **Scope**:
  - Audit decision points: §3.1.2, §3.3.2, §3.3.4, §3.3.10, §3.4.5, §3.6.2.
  - Failure modes: L4, P1.
- **Current State**:
  - Stage 1, Stage 2, Stage 3, snapshot injection, and reply context all read
    different views of "filled" state.
  - Stage 3 normalization can be visible in telemetry while downstream
    parameter legality still sees missing values.
- **Target State**:
  - One canonical post-Stage-3 snapshot is the only source for readiness,
    direct execution, telemetry, and reply context.
  - Trace highlights expose dropped or rejected snapshot transitions.
- **Fix Type**: refactor.
- **Files to Modify**:
  - `core/contracts/clarification_contract.py:615-649`, `:879-948`,
    `:1307-1342`.
  - `core/contracts/execution_readiness_contract.py:177-225`.
  - `core/reply/reply_context_builder.py:19-30`, `:148-167`.
- **Engineering Effort**: M.
- **Expected Impact**:
  - Expected to improve `e2e_colloquial_141` and other normalized-slot
    fail-to-pass candidates.
  - Best-guess baseline impact: +4 to +9 pp.
- **Risk**:
  - Medium: snapshot semantics are shared by legacy and split paths.
- **Dependencies**: TASK-1 should land first to avoid conflating optional
  probes with true data-flow loss.
- **Verification**:
  - Unit: Stage 3 normalization must appear in direct-execution args.
  - Smoke: ambiguous_colloquial and code_switch_typo.

### TASK-6 Separate Stage 2 Slots, Intent, and Stance Contracts

- **Scope**:
  - Audit decision points: §3.3.3, §3.4.1, §3.4.4, §3.4.5.
  - Failure modes: L1, L2, L4, P1.
- **Current State**:
  - One Stage 2 prompt returns slots, intent, stance, and chain, creating
    correlated failures.
- **Target State**:
  - Either split the call into independently typed outputs or keep one call
    but validate and arbitrate each axis independently.
- **Fix Type**: refactor / defer-to-llm.
- **Files to Modify**:
  - `core/contracts/clarification_contract.py:651-714`.
  - `core/contracts/split_contract_utils.py:17-100`.
  - `core/contracts/intent_resolution_contract.py:84-108`.
  - `core/contracts/stance_resolution_contract.py:53-68`.
- **Engineering Effort**: L.
- **Expected Impact**:
  - Broad but uncertain: +4 to +10 pp.
- **Risk**:
  - High: likely increases latency and prompt cost.
- **Dependencies**: TASK-3 and TASK-5 should land first.
- **Verification**:
  - Unit: malformed/missing `intent`, `stance`, or `slots` can fail
    independently without corrupting the other axes.
  - Smoke: full category matrix, not just targeted tasks.

### TASK-7 Centralize and Recalibrate Probe Limit

- **Scope**:
  - Audit decision points: §3.3.6, §3.4.6, §3.4.8.
  - Failure modes: L3, P3.
- **Current State**:
  - Probe budget is encoded as `>= 2` or `probe_limit=2` in several paths.
- **Target State**:
  - One runtime-configured probe budget with explicit semantics:
    "maximum number of optional clarification questions before execution".
- **Fix Type**: extract-constant.
- **Files to Modify**:
  - `config.py:122-127` for a runtime setting, if approved.
  - `core/contracts/clarification_contract.py:367-385`.
  - `core/contracts/execution_readiness_contract.py:149-150`,
    `:227-245`, `:348-371`.
- **Engineering Effort**: S.
- **Expected Impact**:
  - Expected to improve over-clarification with bounded turn budgets.
  - Best-guess baseline impact: +2 to +5 pp.
- **Risk**:
  - Medium: changing probe semantics affects real conversations.
- **Dependencies**: TASK-1 preferred first.
- **Verification**:
  - Unit: one-probe and two-probe semantics.
  - Smoke: multi_turn_clarification.

### TASK-8 Replace Hardcoded Governance Text with Reply-Policy Inputs

- **Scope**:
  - Audit decision points: §3.4.2, §3.4.7, §3.3.9, §3.7.1.
  - Failure modes: P4.
- **Current State**:
  - Governance writes fixed Chinese text for intent clarification,
    exploratory framing, generic missing parameter prompts, and cross-
    constraint messages.
- **Target State**:
  - Governance provides structured reason, missing slot, and domain
    constraint data; reply LLM produces user-facing text.
- **Fix Type**: defer-to-llm / refactor.
- **Files to Modify**:
  - `core/contracts/intent_resolution_contract.py:116-131`.
  - `core/contracts/execution_readiness_contract.py:313-346`.
  - `core/contracts/clarification_contract.py:405-422`, `:1018-1044`.
  - `core/router.py:2268-2276`.
- **Engineering Effort**: M.
- **Expected Impact**:
  - Mostly reply quality, not baseline mechanics: +1 to +3 pp.
- **Risk**:
  - Low-to-medium: reply LLM may omit exact domain wording unless the
    structured context is strong.
- **Dependencies**: TASK-5 preferred first.
- **Verification**:
  - Unit: reply context contains enough structured facts.
  - Smoke: no loss in constraint_violation and clarification tasks.

### TASK-9 Add Guardrails Around Snapshot Direct Execution

- **Scope**:
  - Audit decision point: §3.1.2.
  - Failure modes: L4.
- **Current State**:
  - Governance can select tool and parameters, then call the executor without
    inner-router LLM review.
- **Target State**:
  - Snapshot-direct proceeds only when canonical snapshot invariants pass.
  - Low-confidence or conflict-bearing snapshots fall back to the inner router
    with the snapshot attached as context.
- **Fix Type**: refactor.
- **Files to Modify**:
  - `core/governed_router.py:355-408`, `:666-685`.
  - `core/contracts/clarification_contract.py:424-438`.
  - `core/contracts/execution_readiness_contract.py:498-512`.
- **Engineering Effort**: M.
- **Expected Impact**:
  - Best-guess baseline impact: +3 to +6 pp.
- **Risk**:
  - Medium: fallback path may execute different tools or increase latency.
- **Dependencies**: TASK-5 first.
- **Verification**:
  - Unit: invalid snapshot falls back instead of direct executing.
  - Smoke: factor query and multi-step execution.

### TASK-10 Document and Enforce Clarify-Candidate Priority

- **Scope**:
  - Audit decision point: §3.4.5.
  - Failure modes: L3, L4, P1.
- **Current State**:
  - Split readiness merges missing required, rejected slots, confirm-first,
    followup, carried pending, and Stage 2 needs-clarification sources by
    append order.
- **Target State**:
  - Explicit priority: rejected required > missing required > carried pending
    required > user-requested confirm-first > followup optional > runtime-
    defaultable optional.
- **Fix Type**: refactor.
- **Files to Modify**:
  - `core/contracts/execution_readiness_contract.py:177-225`.
  - `tests/test_contract_split.py`.
- **Engineering Effort**: M.
- **Expected Impact**:
  - Best-guess baseline impact: +4 to +8 pp.
- **Risk**:
  - Medium: changes which question is asked first.
- **Dependencies**: TASK-1 and TASK-5 preferred first.
- **Verification**:
  - Unit: candidate priority table test.
  - Smoke: multi_turn_clarification and parameter_ambiguous.

### TASK-11 Reclassify Stage 3 Inferred-Confidence Threshold as Advisory

- **Scope**:
  - Audit decision point: §3.3.4.
  - Failure modes: L4.
- **Current State**:
  - Inferred slots below `clarification_llm_confidence_threshold=0.7` are
    demoted to missing before downstream logic.
- **Target State**:
  - Low-confidence inferred values should become candidates with explicit
    uncertainty, not silent missing, unless they violate domain legal values.
- **Fix Type**: defer-to-llm / reclassify.
- **Files to Modify**:
  - `core/contracts/clarification_contract.py:891-914`.
  - `tests/test_clarification_contract.py:633-658`.
- **Engineering Effort**: S to M.
- **Expected Impact**:
  - Best-guess baseline impact: +2 to +5 pp.
- **Risk**:
  - Medium: may pass uncertain values into execution.
- **Dependencies**: TASK-5 preferred first.
- **Verification**:
  - Unit: low-confidence legal candidate remains candidate and is surfaced.
  - Smoke: ambiguous_colloquial.

## 3. Priority Ranking

| Priority | Task | Effort | Expected Impact | Risk |
|---|---|---:|---:|---|
| P0 | TASK-1 Runtime-default optionals must not block fresh factor execution | S | +5 to +10 pp | Low |
| P1 | TASK-3 AO turn classification LLM-first for ambiguous short replies | M | +5 to +12 pp | Medium |
| P1 | TASK-5 Snapshot and Stage data-flow invariants | M | +4 to +9 pp | Medium |
| P1 | TASK-10 Clarify-candidate priority | M | +4 to +8 pp | Medium |
| P1 | TASK-2 Evaluation session isolation | M | +2 to +6 pp | Low/Medium |
| P2 | TASK-4 Substring/LLM reconciliation | M | +3 to +8 pp | Medium |
| P2 | TASK-9 Snapshot direct execution guardrails | M | +3 to +6 pp | Medium |
| P2 | TASK-7 Centralize and recalibrate probe limit | S | +2 to +5 pp | Medium |
| P2 | TASK-11 Stage 3 confidence threshold advisory | S/M | +2 to +5 pp | Medium |
| P2 | TASK-6 Separate Stage 2 axes | L | +4 to +10 pp | High |
| P3 | TASK-8 Replace hardcoded governance text | M | +1 to +3 pp | Low/Medium |

P0 selection rationale: TASK-1 is the only task that satisfies Effort=S,
Expected Impact >= 5 pp, and Risk=Low. It is also directly tied to the
documented L3 single-turn failure shape.

## 4. Sequencing Considerations

- Run TASK-1 first because it is small, bounded, and removes a known
  benchmark blocker without changing LLM routing.
- Run TASK-2 before interpreting any future smoke regression in L1/L2 areas;
  polluted evaluation state can invalidate comparisons.
- Run TASK-3 before TASK-4 because substring reconciliation depends on a clear
  classifier ownership boundary.
- Run TASK-5 before TASK-9 because snapshot-direct guardrails need a canonical
  snapshot invariant.
- Delay TASK-6 until smaller L2/L4 fixes land; it is high blast-radius.

## 5. What This Roadmap Does NOT Cover

- §3.7.3 capability summary "hard constraint" language strength. This needs
  separate prompt-compliance evidence before changing.
- §3.6.2 trace highlight gating. It may hide useful events, but the audit does
  not prove it affects baseline; needs human review.
- Full production UX design for clarification wording. TASK-8 only scopes the
  governance/reply boundary.
- Domain-hard constraints such as §3.7.1 cross-constraint preflight and
  §3.7.2 readiness affordance. These are positive governance examples and are
  not remediation targets except for structured reply handoff.
- The audit count mismatch: visible §3 inventory has 37 decision points, while
  summary says 40. This document does not infer the missing three.

