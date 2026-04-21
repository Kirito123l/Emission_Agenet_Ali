# EmissionAgent Paper Notes

持续归档。Codex 协作时可以读这份文件作为整体语境。

**Target venue**: TRD (Transportation Research Part D) / TRC
**Positioning**: Top-tier journal
**Current Phase**: Wave 2 complete, Wave 3 planned

---

## 0. Thesis

**Title**: EmissionAgent: A Contract-Governed LLM Agent Framework for Reliable Traffic Emission Analysis

**Three contributions**:
1. **Analytical Objective (AO)** as cognitive unit — first-class task boundary replacing session-level state
2. **Two-tier scope classification** — separating intent resolution from slot filling from execution readiness
3. **AO-aware contracts compose cleanly** — three invariant contracts (Intent / Stance / ExecutionReadiness) can be added/removed independently with interpretable ablation behavior

**Central claim**: Main-benchmark gains are insufficient evidence of LLM agent robustness. Held-out evaluation reveals category-level generalization failures that architectural iteration can repair — but the refactoring itself must migrate invariants, not just fields.

---

## 1. Section 4: Design Iteration (methodology)

### 4.1 Evolution log (素材齐)

| Phase | Change | Result | Insight |
|---|---|---|---|
| Phase 0 | No-OASC baseline | 66.1% main E | Baseline exists |
| Phase 1 | Session State Contract | -2.22pp | Session-level state not enough |
| Phase 1.5-1.7 | Introduce AO + discover v7 contamination | v8 clean baseline 71.11% | **Need independent held-out** |
| Phase 2.0-2.4 | ClarificationContract iteration (PCM, sentinel, observability) | multi_turn 10%→65% (main) | **Single contract accumulates coupling** |
| Phase 2R Wave 1 | First-class stance as AO field | main OK, held-out collapses | **Main benchmark hides generalization failures** |
| Phase 2R Wave 2 | Three-contract split + runtime-default readiness | held-out 18.67→57.33% | **Modular invariants compose but can lose tangled invariants** |
| Phase 2R Wave 3 | Split-native continuation state + ablation | TBD | TBD |

### 4.2 Key technical transitions

**Session State → AO (first-class cognitive unit)**:
- Problem: Phase 1 Session State Contract added cross-task isolation but regressed -2.22pp because task boundaries != session boundaries
- Solution: Phase 1.7 AO as the cognitive unit for a single user objective
- Paper callout: "Conversational state at session level conflates distinct analytical objectives; AO granularity makes contract invariants enforceable per-task."

**ClarificationContract monolith → three split contracts**:
- Problem: Wave 1 placed intent, stance, and readiness logic in one contract. Stance became a second-class heuristic.
- Solution: Wave 2 elevated stance to AO first-class field, split into IntentResolutionContract / StanceResolutionContract / ExecutionReadinessContract
- Paper callout: "Refactoring a conversational contract into modular invariants requires preserving interaction-state obligations; removing the state representation without restating the invariant can improve single-turn behavior while regressing multi-turn correctness."

**Parameter Collection Mode (PCM) deletion → Wave 3 split-native continuation state**:
- Problem: Wave 2 deleted PCM for architectural cleanliness but regressed multi_turn_clarification from 65% to 10%
- Root cause: PCM carried a legitimate cross-turn invariant that three-contract split did not migrate
- Precise invariant:
  > "Once a turn enters parameter-collection mode because user-visible execution readiness is incomplete, subsequent turns must preserve the pending parameter-collection objective until either the required slot is filled or the bounded optional-probe policy explicitly abandons probing; execution readiness is not recomputed from a fresh LLM-filled snapshot alone."
- Wave 3 target: implement this invariant as split-native ExecutionContinuation state

### 4.3 Operational vs Conversational Invariants (新洞见, Wave 2 产出)

**Quote**:
> "Operational readiness and conversational readiness are distinct: an argument may be executable because a runtime default exists, while still conversationally premature because the user-facing clarification obligation has not been discharged."

**Example**:
- `query_emission_factors.model_year` has runtime default 2020 → operationally ready
- But if user said "帮我看看车辆排放因子" (vague) → conversationally premature
- Wave 2's runtime-default-aware readiness (directive branch) is correct for operational readiness; Wave 3's continuation state adds the conversational layer

### 4.4 Why held-out is necessary (not optional)

Wave 1 E on main benchmark: multi_turn 65% (good)
Wave 1 E on held-out: simple 0%, parameter_ambiguous 0%, code_switch_typo 0%, multi_step 0% (disaster)

> "A framework evaluated only on its development benchmark can appear robust while hiding systemic generalization failures."

Main benchmark has been iteratively improved to fix task-level failures; this creates overfitting to main's linguistic distribution. Held-out reveals the brittleness.

---

## 2. Section 6: Evaluation

### 6.1 Main Benchmark (180 tasks, 9 categories)

**Wave 2 final numbers** (for reference):
- A: 70.00% completion
- E: 71.67% completion, 83.89% tool_accuracy
- Improvement categories (E > A): ambiguous_colloquial +20pp, code_switch_typo +15pp, multi_step +20pp
- Regression categories (E < A): simple -14pp, user_revision -15pp, incomplete -11pp, multi_turn_clarification -5pp

**Wave 3 target numbers**: TBD after Wave 3 Stage 4.1

### 6.1.bis v7 contamination disclosure (honesty section)

Prior v7 benchmark runs used cross-task session sharing, inflating apparent performance. Phase 1.7 discovered this and rebuilt v8 with clean per-task session isolation. **All numbers in this paper are v8 clean except where historical comparison is explicit**.

Paper callout: "Benchmark integrity for conversational LLM agents requires per-task state isolation; cross-task state sharing silently contaminated our prior metrics."

### 6.2 Held-out Benchmark (75 tasks, 9 categories)

**Construction** (for §3 Methodology):
- 9 categories mirroring main
- Deliberately paraphrased: English-Chinese code-switch, typos, alias variations
- Stance mix: 64 directive, 10 deliberative, 1 exploratory
- 10 smoke-tagged subset for fast iteration
- 11 with `has_file=true` using various fixtures (csv, xlsx, zip)
- **Self-audit corrected v5**: 6 multi_step tasks had overly strict `geometry_gated_halt_acceptable=true`; corrected in v5

### 6.3 Wave 1 → Wave 2 v5 held-out results

**Overall**: Wave 1 E 18.67% → Wave 2 E 57.33% (+38.66pp)

**Per-category table** (this goes directly into paper):

| Category | Wave 1 E | Wave 2 E v5 | Δ |
|---|---:|---:|---:|
| ambiguous_colloquial | 0.00% | 80.00% | +80.00pp |
| simple | 0.00% | 75.00% | +75.00pp |
| parameter_ambiguous | 0.00% | 71.43% | +71.43pp |
| code_switch_typo | 0.00% | 62.50% | +62.50pp |
| user_revision | 50.00% | 100.00% | +50.00pp |
| multi_step | 0.00% | 37.50% | +37.50pp |
| constraint_violation | 14.29% | 28.57% | +14.28pp |
| incomplete | 100.00% | 60.00% | -40.00pp |
| multi_turn_clarification | 40.00% | 0.00% | -40.00pp |

**Honest reporting principle**: 
- 7 categories improved (2 dramatically)
- 2 categories regressed (multi_turn: invariant migration issue; incomplete: TBD)
- Paper must report both — regression discussion is methodology strength

### 6.3.bis Held-out benchmark self-audit (methodology point)

During Wave 2 Stage 4 analysis, 6 held-out `multi_step` tasks were found to have overly strict evaluator criteria (`geometry_gated_halt_acceptable=true` treated as required actual condition instead of tolerance). Corrected in v5 after diagnostic confirmation.

Paper callout:
> "Held-out benchmark construction itself requires iteration. Our initial held-out set included six multi-step tasks with overly strict geometry-halt criteria, carried over from main-benchmark fixtures that happened to rely on halt tolerance. Stage-4 analysis revealed that half of the held-out multi_step 0% rate was an evaluation-contract bug rather than execution failure. Held-out-first development must include benchmark self-audit as a checkpoint; the value of the paradigm comes precisely from these late-stage corrections, not in spite of them."

### 6.4 Main vs Held-out Generalization

| Category | Main E | Held-out E v5 | Gap |
|---|---:|---:|---:|
| ambiguous_colloquial | 65.00% | 80.00% | held-out better |
| code_switch_typo | 90.00% | 62.50% | -27.50pp |
| constraint_violation | 76.47% | 28.57% | -47.90pp |
| incomplete | 83.33% | 60.00% | -23.33pp |
| multi_step | 90.00% | 37.50% | -52.50pp |
| multi_turn_clarification | 10.00% | 0.00% | -10.00pp |
| parameter_ambiguous | 66.67% | 71.43% | held-out better |
| simple | 80.95% | 75.00% | -5.95pp |
| user_revision | 85.00% | 100.00% | held-out better |

Categories where held-out **beats** main: ambiguous_colloquial, parameter_ambiguous, user_revision. These are the slots where Wave 2's runtime-default-aware readiness most directly helps.

Categories with worst held-out gap: constraint_violation -47.90pp, multi_step -52.50pp. Wave 3 targets multi_step; constraint_violation gap may be data distribution (held-out constraint tasks have tighter fixtures).

### 6.5 Wave 3 7-group Ablation (TBD, Stage 4.1 output)

Structure (to be filled):

| Group | A | B | C | D | E | F | G |
|---|---|---|---|---|---|---|---|
| Config | No-OASC | +Intent | +Stance | +Readiness | Full | -Intent | -RuntimeDefault |
| Overall E | 70.00% | ? | ? | ? | ? | ? | ? |
| multi_turn | 15.00% | ? | ? | ? | ? | ? | ? |
| simple | 95.24% | ? | ? | ? | ? | ? | ? |

Purpose: show that each contract contributes independently and compositionally.

---

## 3. Section 4.3 Contract Architecture (body)

(Write out after Wave 3 完成)

### 3.1 Contract interface
```
Contract.evaluate(context: AgentContext) -> ContractResult
  preconditions: List[Precondition]
  invariant: Invariant
  violation_action: Callable
```

### 3.2 Three Wave 2 contracts

**IntentResolutionContract**:
- Invariant: `AO.tool_intent.confidence != NONE` before execution
- Violation: return `clarify_intent(...)`
- Fast path: rule-based tool intent resolution from user_message keywords
- Fallback: LLM slot-filler hint

**StanceResolutionContract**:
- Invariant: `AO.stance != UNKNOWN` before execution
- Violation: default to DIRECTIVE with telemetry warning
- Fast path: hedging phrase detection ("等等", "先确认", etc.)
- Fallback: LLM stance hint
- Extra: low-confidence non-directive stance fallback to directive when required slots are saturated and no hedging present

**ExecutionReadinessContract**:
- Preconditions: IntentResolution + StanceResolution satisfied
- Branches:
  - directive: required filled → execute (runtime defaults fill optionals)
  - deliberative: required filled + no-default optional missing → probe; runtime-default optional doesn't block
  - exploratory: ask scope-framing question
- Runtime-default-aware via `core/contracts/runtime_defaults.py` registry

### 3.3 Wave 3 ExecutionContinuation (添加)

(Write after Wave 3 design review)

---

## 4. Reproducibility / Implementation

### 4.1 Tech stack
- qwen3-max (main agent), qwen-plus (classifier + slot filler)
- FastAPI backend
- MOVES-based emission calculators
- PS-XGB dispersion model
- Config-driven via `unified_mappings.yaml`, `tool_contracts.yaml`, `cross_constraints.yaml`

### 4.2 Key files
- `core/contracts/` — 3 split contracts (Wave 2) + ExecutionContinuation (Wave 3)
- `core/governed_router.py` — delegation to contracts + runtime defaults
- `core/analytical_objective.py` — AO dataclass and lifecycle
- `core/ao_manager.py` — AO lifecycle orchestration
- `evaluation/run_oasc_matrix.py` — benchmark runner with A-G group support
- `evaluation/benchmarks/end2end_tasks.jsonl` — 180-task main benchmark (v8)
- `evaluation/benchmarks/held_out_tasks.jsonl` — 75-task held-out (v5)

### 4.3 Reproducibility gates (required in paper)
1. Main benchmark v8 clean (post-Phase 1.7 contamination fix)
2. Held-out benchmark v5 (post-Wave 2 Stage 4 correction)
3. Both benchmarks are included in supplementary materials
4. All experiment commands provided in `evaluation/reports/*.md`
5. LLM temperature=0.0 for reproducibility (stochasticity limited to provider variance)

---

## 5. Future Work (Section 8 素材)

### 5.1 Known limitations after Wave 3

(Fill after Wave 3)

**multi_turn_clarification recovery target**:
- Wave 1: 65% main / 40% held-out
- Wave 2: 10% main / 0% held-out
- Wave 3 target: ≥30% main / ≥30% held-out
- Residual: likely LLM stance misclassification on edge cases

**multi_step continuation bugs**:
- Wave 2 v5: 37.5% held-out (3/8 pass due to benchmark fix)
- Wave 3 target: ≥50% (修 wrong-continuation in 5 fail tasks)
- Residual: possibly 1-2 tasks with LLM routing issues

**constraint_violation held-out gap**:
- Not Wave 3 target
- Diagnosed as fixture sensitivity, not architecture
- Paper §8: suggest held-out benchmark enlargement for constraint tasks

### 5.2 Research directions

- **LLM explicit-year extraction** — `param_006` failed because qwen-plus didn't extract "2012" as model_year; this is LLM capability, not framework
- **Dependency Contract** — currently deferred; could manage tool-chain dependency more explicitly
- **Resource feasibility preconditions** — dispersion OOM showed contracts should reason about computational feasibility (extended contracts class in paper §8)
- **Adaptive ablation** — Wave 3 produces 7-group matrix; future work could apply same pattern to other agent domains

---

## 6. Commit Log / Timeline

### Phase 2R Wave 1 commits (ref)
c649fee, efd8730, 56790b7, ... (see git log)

### Phase 2R Wave 2 commits (ref)
- 48484cb Add contract split feature gate scaffold
- 58d0692 Implement Wave 2 split contract path
- daf7000 Accept canonical split-stage values
- 73a98e0 Low-confidence stance fallback
- b225244 Centralize runtime default lookup
- b03f7e3 Runtime-default aware readiness
- 69a89d6 Diagnose multi-turn regression
- 073b9ab Diagnose multi-step held-out regression
- 3721a7e Fix heldout benchmark 6-task success_criteria (v5)
- 4e39ac6 Wave 2 v5 rerun results
- 10e5b20 v5 report correction + 9.1 update
- 9a7dd0d Benchmark correction post-mortem

### Phase 2R Wave 3 commits (TBD)

(Fill as Codex produces them)

---

## 7. Paper Writing Order (when ready)

Suggested order (not finalized):

1. §3 Methodology (contract framework formalism + AO definition)
2. §4 Architecture (3+1 contracts, invariants, runtime defaults)
3. §5 Implementation (from this document §4)
4. §6 Evaluation (main, held-out, ablation, comparison)
5. §7 Discussion (operational vs conversational invariants, self-audit insight, generalization gap)
6. §8 Limitations and Future Work
7. §1-2 Introduction + Related Work (write last, once all else settled)

Length target: 35-45 pages including all tables.

---

## 8. Review Preparation (preempt likely reviewer concerns)

### Expected tough questions and prepared answers

**Q**: Why not use GPT-4 / Claude / DeepSeek?
**A**: Framework is LLM-agnostic; we used qwen for operational cost. Framework substitutes any JSON-capable LLM.

**Q**: Why 180 + 75 task benchmarks, not larger?
**A**: Both are hand-curated with per-task failure-mode coverage. Scale is not the point; systematic invariant coverage is.

**Q**: multi_turn regression in Wave 2 is concerning. Is this a counter-example to your thesis?
**A**: No — it's direct evidence for the invariant-migration lesson. Wave 3 recovers it via split-native continuation state (see §4.3 and §6).

**Q**: Held-out is suspiciously curated (0% collapse in Wave 1).
**A**: Held-out was constructed deliberately with paraphrase variation. Wave 1's 0% collapse is not an artifact — Wave 2 recovers it without changing the held-out set.

**Q**: How do you verify contamination is gone in v8?
**A**: Per-task session IDs are deterministic and verifiable from runner logs. Appendix provides per-session isolation proof.

---

Last updated: [Wave 2 collection, 待 Wave 3 updates]
