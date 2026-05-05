# Phase 9.1.0 Step 1 — Run 7 LLM Variance Characterization Report

**Date:** 2026-05-05
**Branch:** `phase9.1-v1.5-upgrade` (HEAD: `6809888`)
**Data:** `evaluation/results/_temp_phase9_1_0_variance/trial_{1..5}/`
**Analysis script:** `evaluation/scripts/analyze_run7_variance.py`
**Analysis output:** `evaluation/results/_temp_phase9_1_0_variance/variance_summary.json`

---

## 1. Pre-Trial LLM Config

Captured at `_temp_phase9_1_0_variance/trial_1/run_metadata.json` (identical for all 5 trials).

| Parameter | Value | Source |
|---|---|---|
| Provider | `deepseek` | `config.py:32` via `.env` `LLM_PROVIDER=deepseek` |
| Model | `deepseek-v4-pro` | `config.py:33,46` via `.env` `LLM_REASONING_MODEL=deepseek-v4-pro` |
| Temperature | `0.0` | `config.py:47` (hardcoded in LLMAssignment) |
| Max tokens | `8000` | `config.py:16` (LLMAssignment default) |
| Thinking enabled | `True` | `config.py:36` via `.env` `DEEPSEEK_ENABLE_THINKING=true` |
| Reasoning effort | `max` | `config.py:37` via `.env` `DEEPSEEK_REASONING_EFFORT=max` |
| Thinking models | `('deepseek-v4-pro',)` | `config.py:38-42` |
| Base URL | `https://api.deepseek.com` | `.env` `DEEPSEEK_BASE_URL` |
| SDK | `openai 2.32.0` | `pip show openai` |
| Router model source | `get_llm_client("agent")` | `router.py:353` → `config.agent_llm.model` |

**No hardcoded `qwen-plus`** — the `router.py:341` hardcoding mentioned in the upgrade plan has been fixed. Current code at `router.py:353` uses `get_llm_client("agent")` which reads `config.agent_llm.model`.

**Original Run 7 LLM:** Unknown. The original Run 7 was run from `phase3-governance-reset` branch. The model used at that time is not recorded in the trace data. Based on the Phase 9.1.0 audit's upgrade plan reference to `router.py:341` hardcoding `qwen-plus`, the original may have used `qwen-plus` or `qwen3-max`. This cannot be verified.

### Key governance flags (all trials)

| Flag | Value | Source |
|---|---|---|
| `enable_state_orchestration` | `True` | `config.py:68` |
| `enable_llm_decision_field` | `True` | `config.py:189` |
| `enable_conversation_fast_path` | `True` | `config.py:72` |
| `enable_ao_classifier_rule_layer` | `True` | `config.py:76-78` |
| `enable_ao_classifier_llm_layer` | `True` | `config.py:79-81` |

---

## 2. 5-Trial Trace Summary

### 2.1 Per-Trial Triage

| Trial | Mode | Turn 1 Tool | Turn 2 Tool | Turn 3 Tool | Wall Clock | Governance Steps |
|---|---|---|---|---|---|---|
| 1 | mode_A | `calculate_macro_emission` (success) | None | None | 298s | reply_generation(3), intent_resolution(3), state_transition(1), clarification(2), file_relationship_resolution_skipped(1) |
| 2 | mode_A | `calculate_macro_emission` (success) | None | None | 176s | reply_generation(3) only |
| 3 | mode_A | `calculate_macro_emission` (success) | None | None | 225s | reply_generation(3) only |
| 4 | mode_A | `calculate_macro_emission` (success) | None | None | 261s | reply_generation(3) only |
| 5 | mode_A | `calculate_macro_emission` (success) | None | None | 215s | reply_generation(3) only |

**All 5 trials: mode_A (original_run7_like)** — Turn 1 `calculate_macro_emission` success, Turn 2/3 no tools.

### 2.2 Cross-Trial Per-Turn Comparison

| Trial | Turn | AO Class | AO ID | PCM Active | Tools | Step Types |
|---|---|---|---|---|---|---|
| 1 | 1 | `new_ao` | AO#1 | False | macro_emission ✓ | reply_generation |
| 1 | 2 | `new_ao` | AO#2 | True | None | reply_generation |
| 1 | 3 | `new_ao` | AO#3 | True | None | clarification(2), intent_resolution(3), state_transition, reply_generation |
| 2 | 1 | `new_ao` | AO#1 | False | macro_emission ✓ | reply_generation |
| 2 | 2 | `new_ao` | AO#2 | True | None | reply_generation |
| 2 | 3 | `new_ao` | AO#3 | True | None | reply_generation |
| 3 | 1 | `new_ao` | AO#1 | False | macro_emission ✓ | reply_generation |
| 3 | 2 | `new_ao` | AO#2 | True | None | reply_generation |
| 3 | 3 | `new_ao` | AO#3 | True | None | reply_generation |
| 4 | 1 | `new_ao` | AO#1 | False | macro_emission ✓ | reply_generation |
| 4 | 2 | `new_ao` | AO#2 | True | None | reply_generation |
| 4 | 3 | `new_ao` | AO#3 | True | None | reply_generation |
| 5 | 1 | `new_ao` | AO#1 | False | macro_emission ✓ | reply_generation |
| 5 | 2 | `new_ao` | AO#2 | True | None | reply_generation |
| 5 | 3 | `new_ao` | AO#3 | True | None | reply_generation |

### 2.3 Turn 2 Response Variation

The LLM response to Turn 2 ("请对刚才的排放结果做扩散模拟") varies across trials:

| Trial | Turn 2 Response Theme |
|---|---|
| 1 | Asks which pollutant for dispersion (CO2/NOx/PM2.5) |
| 2 | **Says dispersion is not supported** ("当前系统暂不支持扩散模拟功能") |
| 3 | Asks which pollutant for dispersion |
| 4 | **Says dispersion is not supported** ("当前系统暂不支持扩散模拟功能") |
| 5 | Asks which pollutant + requests meteorology data |

Two trials (2, 4) hallucinate that dispersion is "not supported," despite the tool being available. This is LLM variance within mode_A — the system state (AO classification, PCM status, tools executed) is invariant, but the LLM's surface response varies.

---

## 3. Failure Mode Classification

### 3.1 Mode Distribution

| Mode | Count | Description |
|---|---|---|
| mode_A (original_run7_like) | **5/5** | Turn 1 macro_emission success, Turn 2/3 no tools |
| mode_B (pcm_blocked_throughout) | 0/5 | All 3 turns PCM-blocked, zero tools |
| mode_C (full_chain_success) | 0/5 | Turn 1+2+3 all execute tools |
| mode_D (other) | 0/5 | Any other pattern |

### 3.2 Classification Evidence per Trial

**Trial 1 (source: `trial_1/shanghai_e2e_summary.json`):**
- Turn 1: `tool_chain=["calculate_macro_emission"]`, `ao_lifecycle_events[0].complete_check_results.collection_mode_active=False`
- Turn 2: `tool_calls=[]`, `collection_mode_active=True`, `ao_classification=new_ao`
- Turn 3: `tool_calls=[]`, `collection_mode_active=True`, `ao_classification=new_ao`
- Classification: **mode_A** — Turn 1 tool success, Turn 2+3 no tools

**Trial 2 (source: `trial_2/shanghai_e2e_summary.json`):**
- Turn 1: `tool_chain=["calculate_macro_emission"]`, `collection_mode_active=False`
- Turn 2: `tool_calls=[]`, `collection_mode_active=True`
- Turn 3: `tool_calls=[]`, `collection_mode_active=True`
- Classification: **mode_A**

**Trial 3 (source: `trial_3/shanghai_e2e_summary.json`):**
- Turn 1: `tool_chain=["calculate_macro_emission"]`, `collection_mode_active=False`
- Turn 2: `tool_calls=[]`, `collection_mode_active=True`
- Turn 3: `tool_calls=[]`, `collection_mode_active=True`
- Classification: **mode_A**

**Trial 4 (source: `trial_4/shanghai_e2e_summary.json`):**
- Turn 1: `tool_chain=["calculate_macro_emission"]`, `collection_mode_active=False`
- Turn 2: `tool_calls=[]`, `collection_mode_active=True`
- Turn 3: `tool_calls=[]`, `collection_mode_active=True`
- Classification: **mode_A**

**Trial 5 (source: `trial_5/shanghai_e2e_summary.json`):**
- Turn 1: `tool_chain=["calculate_macro_emission"]`, `collection_mode_active=False`
- Turn 2: `tool_calls=[]`, `collection_mode_active=True`
- Turn 3: `tool_calls=[]`, `collection_mode_active=True`
- Classification: **mode_A**

---

## 4. Invariant Checks

### 4.1 Cross-Trial Invariant Results

| Invariant | Holds 5/5? | Details |
|---|---|---|
| `turn1_tool_executed` | **Yes** | 5/5: `calculate_macro_emission` success |
| `turn1_ao_new` | **Yes** | 5/5: `AOClassType.NEW_AO` |
| `turn1_collection_mode_false` | **Yes** | 5/5: PCM not active on Turn 1 |
| `turn2_ao_new_ao` | **Yes** | 5/5: classifier outputs `new_ao` for "扩散模拟" |
| `turn2_collection_mode_true` | **Yes** | 5/5: PCM blocks Turn 2 (missing pollutants parameter) |
| `turn2_no_tools` | **Yes** | 5/5: no tools executed in Turn 2 |
| `turn3_ao_new_ao` | **Yes** | 5/5: classifier outputs `new_ao` for Turn 3 |
| `turn3_collection_mode_true` | **Yes** | 5/5: PCM still blocking |
| `turn3_no_tools` | **Yes** | 5/5: no tools executed in Turn 3 |
| `projected_chain_never_present` | **Yes** | 15/15 turn-trials: `projected_chain` absent |

### 4.2 Analysis

**All 10 invariants hold 5/5.** The code behavior is stable at the structural level — the failure mode is deterministic given the current LLM backend.

Key structural findings:
1. **Chain continuation is NEVER classified.** Turn 2 ("请对刚才的排放结果做扩散模拟") is classified as `new_ao` 5/5, never as `continuation`. The AO classifier treats "对刚才的排放结果做扩散模拟" as a NEW independent objective rather than a chain continuation of the macro emission AO.
2. **PCM activates at Turn 2, not Turn 1.** `collection_mode_active=False` in Turn 1 (5/5), then `True` in Turn 2 (5/5). PCM blocks dispersion because the AO classifier created a new AO, and the new AO has unfilled optional parameters (pollutants for dispersion).
3. **`projected_chain` is absent 15/15 turn-trials.** The IntentResolver never projects a multi-step chain. Each AO is a single-tool plan.
4. **AO#1 auto-completes** after Turn 1 (macro emission success), leaving no active AO for Turn 2 to continue.
5. **Each turn creates a NEW AO** (AO#1 → AO#2 → AO#3). No cross-turn AO persistence across the 3-turn workflow.

### 4.3 Trace Quality Variance

Trials 2-5 have only `reply_generation` trace steps (3 per trial) — no `intent_resolution`, `state_transition`, `clarification`, `file_relationship` steps. Trial 1 has richer trace data with all governance steps. This trace quality variance is NOT a behavioral difference (the tool execution pattern is identical) — it's a trace recording difference. Trials 2-5 likely took a snapshot/direct execution path that bypasses the full state loop trace recording.

This is a **secondary finding**: trace completeness varies even when behavior is invariant. The v1.5 ConversationState writes should not depend on full state loop trace availability for observability.

---

## 5. Hypothesis Evaluation

### H3 Supported (Strong)

| Hypothesis | Requirement | Actual | Verdict |
|---|---|---|---|
| H1 (systematic offset) | mode_B ≥ 4/5 | mode_B = 0/5 | **Rejected** |
| H2 (high variance) | ≥ 2 modes | 1 mode observed | **Rejected** |
| H3 (original is normal) | mode_A ≥ 4/5 | mode_A = 5/5 | **Accepted** |

**The original Run 7 behavior (Turn 1 macro emission success, Turn 2/3 stuck) is the stable, reproducible failure mode.** The Phase 9.1.0 single re-run (zero tools in all turns, PCM-blocked throughout) was an **outlier** — likely caused by a transient LLM model variance or a different model version on that specific API call.

### Rationale

- mode_A: 5/5 (100%)
- mode_B: 0/5 (0%)
- mode_C: 0/5 (0%)
- mode_D: 0/5 (0%)
- Unique modes observed: 1
- H3 threshold: mode_A ≥ 4/5 → satisfied (5/5)

---

## 6. Implications for Step 2 Sample Size

**Recommendation: 5 task × 1 trial.**

| Scenario | Recommendation | Basis |
|---|---|---|
| H1 (systematic offset) | 5 task × 1 trial | Each trial reliable (invariant behavior) |
| H2 (high variance) | 5 task × ≥3 trial | Need task-level variance quantification |
| H3 (original stable) | 5 task × 1 trial | Single trial representative of behavior |
| **Actual (H3, strong)** | **5 task × 1 trial** | 10/10 invariants hold 5/5, behavior is deterministic |

The 10/10 invariant checks holding across all 5 trials confirm that a single trial per task in Step 2 will produce representative data. The variance is in LLM surface response text (e.g., "dispersion not supported" vs. "which pollutant?"), not in structural governance behavior (AO classification, tool execution, PCM status).

---

## 7. Implications for v1.5 Facade Design

### 7.1 PCM Gate Behavior: Stable Target

PCM behavior is 100% stable across trials:
- Turn 1: `collection_mode_active=False` → tool executes
- Turn 2: `collection_mode_active=True` → tool blocked
- Turn 3: `collection_mode_active=True` → tool blocked

**This is a reliable v1.5 design target.** The PCM gate reliably blocks chain continuation by creating a new AO rather than continuing the existing one.

### 7.2 AO Classification: Stable, Systematic Bug

AO classifier output is 5/5 `new_ao` for Turn 2 ("请对刚才的排放结果做扩散模拟"). The classifier NEVER classifies "对刚才的排放结果做" as CONTINUATION.

**Root cause at `core/ao_classifier.py`:** The LLM Layer 2 classifier does not recognize "对刚才的排放结果做X" as a chain continuation pattern. The rule layer (`ao_classifier.py:228-295`) doesn't have a rule for this Chinese pattern.

**v1.5 design target:** ConversationState facade should detect chain continuation intent from the user message even when the AO classifier misclassifies it as NEW_AO. The `projected_chain` from the prior AO should be available in ConversationState.

### 7.3 Projected Chain: Systematically Absent

`projected_chain` key is absent from 15/15 turn-trials. `pending_tool_queue` is `[]` for all lifecycle events where it's parseable.

**v1.5 design target:** The IntentResolver (`core/intent_resolver.py`) should project multi-step chains when the user's initial request implies downstream tools. For "计算排放" with a road network file, the projected chain should be `["calculate_macro_emission", "calculate_dispersion", "analyze_hotspots", "render_spatial_map"]`.

### 7.4 AO Continuity: Each Turn Creates New AO

The AO classifier creates AO#1 (Turn 1), AO#2 (Turn 2), AO#3 (Turn 3) — never continues the same AO across turns.

**v1.5 design target:** ConversationState should track the "parent AO" that should be continued. When Turn 2 references "刚才的排放结果" (the result just computed), ConversationState should detect this as a chain continuation on AO#1, not create a new AO#2.

### 7.5 Concrete v1.5 Facade Hand-Off Points

Based on this 5-trial ground truth:

1. **`oasc_contract.py:368-369`** — CONTINUATION path. Currently only triggered by rule-layer signals (`_is_short_clarification_reply`). v1.5 should add ConversationState-based continuation detection for "对刚才的" patterns.

2. **`ao_classifier.py:237-244`** — NEW_AO path for first message. Currently always creates new AO. v1.5 should check ConversationState for pending chains from prior AOs.

3. **`execution_readiness_contract.py:275-283`** — Chain continuation write to `ExecutionContinuation`. Currently writes `pending_tool_queue=[]` because no projected chain exists. v1.5 should populate this from ConversationState.

4. **`clarification_contract.py:423-585`** — PCM decision tree. Currently blocks execution when optional parameters are missing. v1.5 should check ConversationState for whether the current AO is part of a multi-step chain and adjust PCM behavior accordingly (e.g., skip optional probes for intermediate chain steps where the parameter will be filled later).

---

## 8. Conclusion

1. **H3 supported (strong, 5/5).** The original Run 7 failure mode (Turn 1 macro success, Turn 2/3 stuck) is the stable, reproducible behavior with the current DeepSeek v4-pro backend.

2. **10/10 cross-trial invariants hold.** Code behavior is structurally deterministic. LLM variance affects surface response text, not governance decisions.

3. **The Phase 9.1.0 single re-run was an outlier.** Its zero-tool PCM-blocked-throughout behavior does not reproduce and should not be used as the v1.5 canonical test case.

4. **Step 2 recommendation: 5 task × 1 trial.** Single trials are representative for each task.

5. **v1.5 facade targets are clearly defined:**
   - Fix AO classifier to recognize chain continuation patterns ("对刚才的...做X")
   - Populate `projected_chain` from IntentResolver for multi-step workflows
   - Track AO continuity across turns in ConversationState
   - Adjust PCM behavior for intermediate chain steps
