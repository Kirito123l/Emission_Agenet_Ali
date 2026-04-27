# Governance Failure Modes in EmissionAgent

## 1. Background and Method

These failure modes emerged during Phase 2 diagnosis by repeatedly comparing
traces, auditing governance decision points, and checking smoke/evaluation
telemetry. They were not predefined categories. The taxonomy below treats the
Phase 2 audit as the source inventory and uses observed task failures as the
calibration target.

Audit count note: `docs/phase2_governance_audit.md` summary says 40 decision
points, but the numbered `#### 3.*` inventory contains 37 headings. The matrix
in section 6 covers the 37 visible decision points. The count mismatch itself
is marked needs human review.

## 2. Failure Mode Taxonomy

### L1 - Evaluation Isolation Leakage

- **Definition**: The evaluation harness does not fully clear router/AO state
  between tasks, so later tasks see AO or turn state from earlier tasks and are
  misclassified as CONTINUATION or REVISION.
- **Symptoms**: Turn number greater than 1 in a single-turn task;
  `classification=CONTINUATION` in a NEW task; final response references query
  results that never occurred in the current task.
- **Reference task**: `e2e_ambiguous_001` (Round 3 Qwen Run A: `turn=22`,
  target `AO#9`).
- **Mechanism class**: Harness-level state contamination.
- **Audit decision points implicated**: §3.2.1 (`state_snapshot`
  construction), §3.6.1 (reply parser rewrites on polluted context and makes
  the error fluent).

### L2 - Turn Classification Misjudgment

- **Definition**: `AOClassifier` classifies a NEW_AO as CONTINUATION/REVISION,
  or treats clarification answers as REVISION.
- **Symptoms**: Multi-turn clarification answers are treated as edits to a
  previous AO; clarification stage 2 never triggers; the same tool is called
  repeatedly with the same parameters.
- **Reference task**: `e2e_clarification_101` (4 turns all REVISION,
  `query_emission_factors` called 4 times with identical parameters).
- **Mechanism class**: `AOClassifier` rule layer substring matching on short
  replies.
- **Audit decision points implicated**: §3.2.1, §3.2.2, §3.2.3, §3.3.8.

### L3 - Optional Probe Over-Triggering

- **Definition**: Required slots are complete, but governance still triggers a
  first-turn optional-slot probe because an optional slot has no declarative
  default. In single-turn evaluation, this locks the task in
  NEEDS_CLARIFICATION and prevents tool execution.
- **Symptoms**: `stage1_filled_slots` contains all required fields;
  `stage2_missing_required=[]`; `final_decision=clarify`;
  `pcm_trigger_reason=unfilled_optional_no_default_at_first_turn`.
- **Reference task**: `e2e_codeswitch_161` (vehicle and pollutants are filled,
  but the contract probes `model_year`).
- **Mechanism class**: Collection-mode resolution treats first-turn optional
  absence as a strong execution blocker.
- **Audit decision points implicated**: §3.3.5, §3.3.6, §3.4.6, §3.4.8.

### L4 - Stage Pipeline Data Flow Loss

- **Definition**: Clarification-stage data is not transmitted consistently
  across Stage 1 -> Stage 2 -> Stage 3. Stage 3 normalizations do not reliably
  flow back into the filled-slot snapshot that downstream decisions read.
- **Symptoms**: `stage3_normalizations` shows success, such as `家里那种四门小车`
  -> `Passenger Car`, but final `params_legal=false` and `expected_params`
  still reports missing values.
- **Reference task**: `e2e_colloquial_141`.
- **Mechanism class**: Snapshot write/read path asymmetry.
- **Audit decision points implicated**: §3.3.2, §3.3.4, §3.3.10, §3.6.2.

## 3. Cross-cutting Failure Patterns

### P1 - Coupled Multi-axis LLM Decision

Corresponds to audit §4.1. A single Stage 2 LLM call decides slots, intent,
stance, and sometimes chain shape. A single model error therefore becomes a
correlated failure across several governance axes. This pattern contributes to
L1, L2, and L4.

### P2 - Parallel Substring + LLM Detection Without Reconciliation

Corresponds to audit §4.2 and §4.5. Substring matchers and LLM outputs decide
overlapping conversational meanings, but there is no explicit arbitration step.
Examples include confirm-first, reversal, abandon, and revision detection.

### P3 - Hardcoded Magic Constants for Probe Behavior

Corresponds to audit §4.6. `probe_limit=2` or equivalent `>= 2` logic appears
in multiple paths. The constant is behavioral policy but is not centralized or
explained by a domain rationale.

### P4 - Hardcoded Governance-Authored User-Facing Text

Corresponds to audit §4.4. Several governance short-circuits construct
user-visible text directly and only later allow the reply parser to rewrite
style. This makes content selection governance-authored even when wording is
LLM-rewritten.

## 4. Domain-Aligned Governance (Counter-examples)

These are positive examples from audit §2.3 and should be preserved or
strengthened:

- §3.7.1 cross-constraint preflight: vehicle, road, pollutant, season, and
  meteorology compatibility is a domain rule.
- §3.7.2 readiness affordance gate: data-shape and artifact prerequisite
  checks prevent impossible downstream actions.
- §3.1.3 `model_year=2020` runtime default: a documented domain default for
  factor queries.
- `core/readiness.py` field labels and repair hints: `link_length_km`,
  `traffic_flow_vph`, `avg_speed_kph`, `timestamp_s`, and related fields are
  emission-domain concepts.
- HCM 6th ed. cited defaults in remediation policy: citable methodological
  defaults are legitimate governance.

These are what governance should encode: domain physics, method constraints,
data-shape requirements, and audit-citable defaults.

## 5. Design Principle

> Governance should encode domain physics, not conversational pragmatics.

Specifically:

- Domain physics (vehicle/road/pollutant/season compatibility, methodological
  defaults, data-shape requirements, audit citations) -> governance-authoritative.
- Conversational pragmatics (turn classification, intent inference,
  information sufficiency judgment, stance reading) -> LLM-deferential.

When governance crosses this boundary into conversational pragmatics, it
produces L1-L4 failure modes.

## 6. Failure Mode -> Decision Point Cross-Reference Matrix

Legend: `X` = directly related; `?` = plausible but needs human review.

| Decision Point | L1 | L2 | L3 | L4 | P1 | P2 | P3 | P4 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| §3.1.1 Contract pipeline gate |  | X |  |  |  |  |  |  |
| §3.1.2 Snapshot direct execution |  |  |  | X |  |  |  |  |
| §3.1.3 `model_year` runtime default |  |  |  | ? |  |  |  |  |
| §3.1.4 Cross-constraint violation persistence |  |  |  |  |  |  |  |  |
| §3.2.1 OASC classification call | X | X |  |  |  |  |  |  |
| §3.2.2 AOClassifier rule layer |  | X |  |  |  | X |  |  |
| §3.2.3 AOClassifier LLM confidence gate |  | X |  |  |  |  |  |  |
| §3.2.4 OASC AO mutation |  | X |  |  |  |  |  |  |
| §3.2.5 OASC AO completion |  |  |  | X |  |  |  |  |
| §3.3.1 Clarification trigger gate |  | X |  |  |  |  |  |  |
| §3.3.2 Stage 1 heuristic extraction |  |  |  | X |  |  |  |  |
| §3.3.3 Stage 2 LLM bundle | X |  |  | X | X |  |  |  |
| §3.3.4 Stage 3 standardization |  |  |  | X |  |  |  |  |
| §3.3.5 Collection-mode resolution |  |  | X |  |  |  |  |  |
| §3.3.6 Optional probe abandon `>= 2` |  |  | X |  |  |  | X |  |
| §3.3.7 Probe question generation |  |  | X |  |  |  |  | X |
| §3.3.8 Confirm-first detection | X | X |  |  |  | X |  |  |
| §3.3.9 Question-vs-proceed decision |  |  | X | X |  |  |  | X |
| §3.3.10 Snapshot injection |  |  |  | X |  |  |  |  |
| §3.4.1 Continuation-state intent short-circuit |  | X |  | X | X | X |  |  |
| §3.4.2 Intent-unresolved hardcoded clarify |  | X |  |  |  |  |  | X |
| §3.4.3 Continuation-side reversal |  | X |  |  |  | X |  |  |
| §3.4.4 Saturated-slot stance fallback | X |  |  |  | X |  |  |  |
| §3.4.5 Clarify candidates aggregation |  |  | X | X | X |  |  |  |
| §3.4.6 Probe-limit force-proceed |  |  | X |  |  |  | X |  |
| §3.4.7 Exploratory hardcoded clarify |  | X |  |  |  |  |  | X |
| §3.4.8 Deliberative probe abandonment |  |  | X |  |  | X | X |  |
| §3.4.9 Followup-slot retention |  |  | X |  |  |  |  |  |
| §3.5.1 AO completion guard |  |  |  | X |  |  |  |  |
| §3.5.2 Intent backfill from tool call |  |  |  |  |  |  |  |  |
| §3.5.3 Implicit predecessor closure |  |  |  | X |  |  |  |  |
| §3.6.1 LLM reply parser rewrite | X |  |  |  |  |  |  |  |
| §3.6.2 Trace highlight gating |  |  |  | X |  |  |  |  |
| §3.6.3 Constraint violation writer scope |  |  |  | X |  |  |  |  |
| §3.7.1 Cross-constraint preflight blocker |  |  |  |  |  |  |  | X |
| §3.7.2 Action readiness affordance gate |  |  |  |  |  |  |  |  |
| §3.7.3 Capability-aware synthesis hard-constraint injection |  |  |  | ? |  |  |  |  |

Matrix counts over visible audit rows:

- L1: 5 decision points.
- L2: 11 decision points.
- L3: 8 decision points.
- L4: 14 decision points, including 2 needs human review marks.
- P1: 4 decision points.
- P2: 5 decision points.
- P3: 3 decision points.
- P4: 5 decision points.

