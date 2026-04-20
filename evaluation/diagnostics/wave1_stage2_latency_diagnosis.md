# Wave 1 Stage 2 Latency Diagnosis

## 1. Scope

This is a diagnostic pass for the Phase 2R Wave 1 `clarification_contract` Stage 2 latency increase. It reads existing logs and source only. No production code was changed and no benchmark was run.

Input logs:

- `evaluation/results/phase2_step4_clarification_focus_E/end2end_logs.jsonl`
- `evaluation/results/phase2r_wave1_smoke_E/end2end_logs.jsonl`
- `evaluation/results/post_oom_guard_smoke_E/end2end_logs.jsonl`
- `evaluation/results/heldout_full_phase2r_wave1_E/end2end_logs.jsonl`

Source inspected:

- `core/contracts/clarification_contract.py`
- `core/intent_resolver.py`
- `core/stance_resolver.py`
- `config.py`
- `services/llm_client.py`

Phase 2.4 prompt reference was taken from commit `ba533e0`, the pre-Wave 1 reference used by the earlier `56790b7` diagnostic.

## 2. Latency Distribution (Task A)

Stage 2 latency was extracted from every `clarification_telemetry[*].stage2_latency_ms` entry.

| Metric | Phase 2.4 ref | Wave 1 smoke | Delta |
|---|---:|---:|---:|
| count | 40 | 57 | +17 |
| mean | 6817.1 ms | 11127.1 ms | +4310.0 ms |
| p50 | 6718.0 ms | 10622.1 ms | +3904.1 ms |
| p90 | 8238.0 ms | 13986.8 ms | +5748.8 ms |
| p99 | 11011.6 ms | 14776.8 ms | +3765.2 ms |
| max | 11593.2 ms | 14950.7 ms | +3357.5 ms |

Conclusion: this is an overall right shift, not a few 20-30s outliers pulling up the mean. Wave 1 max is under 15s, while p50 moved by about 3.9s.

Top Wave 1 outliers:

| Task ID | Category | Latency | Prompt chars | Persisted hint chars | Parse success | `stage2_missing_required` |
|---|---|---:|---:|---:|---|---|
| `e2e_colloquial_146` | `ambiguous_colloquial` | 14950.7 ms | 2370 | 382 | intent=true, stance=true | `[]` |
| `e2e_clarification_117` | `multi_turn_clarification` | 14640.2 ms | 2366 | 395 | intent=true, stance=true | `[]` |
| `e2e_clarification_108` | `multi_turn_clarification` | 14585.0 ms | 2364 | 485 | intent=true, stance=true | `[]` |
| `e2e_colloquial_144` | `ambiguous_colloquial` | 14424.9 ms | 2370 | 331 | intent=true, stance=true | `[]` |
| `e2e_clarification_103` | `multi_turn_clarification` | 14158.7 ms | 2366 | 428 | intent=true, stance=true | `[]` |

No JSON parse retry signal is visible in telemetry for these outliers. They are not longer prompts; their prompt lengths sit in the same 2364-2370 char band as ordinary Stage 2 calls.

Same-task comparison across runs:

- Common Stage 2 task IDs between Phase 2.4 and Wave 1: 21
- Mean per-task latency delta: +2341.4 ms
- Median per-task latency delta: +1948.8 ms
- Positive deltas: 20/21 tasks

This confirms the right shift is not only caused by Wave 1 adding different tasks; shared tasks also got slower.

## 3. Prompt Length Measurement (Task B)

Raw prompts are not persisted in logs, so I used a fake LLM client to call the current `ClarificationContract._run_stage2_llm()` path and capture the exact generated `system` and user YAML message. For the Phase 2.4 prompt, I extracted `_stage2_system_prompt()` from `ba533e0`. The Stage 2 payload builder is unchanged in shape between the two versions; the prompt delta is the system prompt stance addition.

Source facts:

- Current payload builder at `core/contracts/clarification_contract.py:663` includes only `user_message`, `tool_name`, `available_tools`, `file_context`, `current_ao_id`, `classification`, `existing_parameter_snapshot`, `tool_slots`, and `legal_values`.
- No AO history or stance history is injected into the Stage 2 prompt payload.
- Phase 2.4 system prompt chars: 1003
- Wave 1 system prompt chars: 1230
- System prompt delta: +227 chars

Measured prompt samples:

| Task ID | Phase 2.4 prompt chars | Wave 1 prompt chars | Delta |
|---|---:|---:|---:|
| `e2e_clarification_101` | 2140 | 2367 | +227 |
| `e2e_clarification_105` | 2143 | 2370 | +227 |
| `e2e_clarification_106` | 2142 | 2369 | +227 |
| `e2e_clarification_111` | 2141 | 2368 | +227 |
| `e2e_clarification_112` | 2140 | 2367 | +227 |
| `e2e_clarification_102` | 2152 | 2379 | +227 |
| `e2e_clarification_103` | 2139 | 2366 | +227 |

Prompt length correlation:

| Run | Corr(latency, user message chars) | Corr(latency, persisted hint chars) | Corr(latency, missing slot count) |
|---|---:|---:|---:|
| Phase 2.4 ref | 0.328 | 0.000 | 0.502 |
| Wave 1 smoke | 0.108 | 0.075 | -0.697 |

Conclusion: hidden prompt injection is not present, and the measured +227 char input increase is too small and too uniform to explain a +3904 ms p50 shift by itself.

## 4. Output Tokens Analysis (Task C)

Full raw Stage 2 responses and provider token usage are not persisted in `end2end_logs.jsonl`. Wave 1 does persist extracted `llm_intent_raw` and `stance_llm_hint_raw`; Phase 2.4 does not persist those fields. Therefore the output analysis below uses persisted raw hint objects as a lower-bound proxy, not a complete raw response size.

| Metric | Phase 2.4 ref | Wave 1 smoke |
|---|---:|---:|
| Stage 2 calls with latency | 40 | 57 |
| Full raw response persisted | 0 | 0 |
| Token usage persisted | 0 | 0 |
| Avg persisted intent raw chars | 0 persisted | 204.8 |
| Avg persisted stance raw chars | 0 persisted | 131.6 |
| Avg persisted intent+stance chars | 0 persisted | 360.4 |
| Estimated persisted hint tokens (`chars / 4`) | 0 persisted | 90.1 |
| Observable Stage 2 call exception rate | 0/40 | 0/57 |
| Intent hint parse failure rate | not instrumented | 0/57 |
| Stance hint parse failure rate | not instrumented | 0/57 |
| JSON parse retry fields present | 0 | 0 |

The comparable lower-bound estimate is:

- Old schema required `intent` but not `stance`. Wave 1 `intent` raw averages 204.8 chars, so Phase 2.4's comparable intent object was likely in that range.
- Wave 1 adds `stance` raw averaging 131.6 chars and raises persisted hint output to 360.4 chars.
- This is an estimated +155.6 chars, or about +38.9 output tokens, before counting the full `slots` object that is not persisted.

The latency shape fits output expansion better than input expansion:

- Input prompt grew only +227 chars.
- Persisted output hints grew by roughly +155 chars and added an extra reasoning-bearing object.
- LLM latency is usually more sensitive to generated tokens than prompt characters at this scale.
- Wave 1 p50 moved right rather than only p99/max, consistent with every Stage 2 completion generating the additional `stance` object.

Observability gap for Wave 2: Stage 2 telemetry should persist either provider usage (`prompt_tokens`, `completion_tokens`) or bounded raw-response length fields. Currently it cannot separate prompt processing time from completion generation time.

## 5. Provider/Network Ruling-out (Task D)

Run artifact mtimes:

| Run | Log mtime |
|---|---|
| Phase 2.4 ref | 2026-04-16 09:26:37 +0800 |
| Wave 1 smoke | 2026-04-19 08:53:18 +0800 |
| post-OOM main smoke | 2026-04-20 10:26:23 +0800 |
| Wave 1 held-out E | 2026-04-20 11:38:14 +0800 |

Provider/network was checked only through local config, per instruction. No provider status page was queried.

Relevant configuration:

- `config.py:83`: `CLARIFICATION_LLM_MODEL` default remains `qwen-plus`.
- `config.py:86`: `CLARIFICATION_LLM_TIMEOUT_SEC` default remains `5.0`.
- `services/llm_client.py:96`: request timeout remains `120.0`.
- `services/llm_client.py:146`: retry attempts remain controlled by `enable_llm_retry_backoff`, max `3` when enabled.
- `services/llm_client.py:380`: `chat_json` still uses the same model field, JSON response format, and `temperature=0.0`.

Effective provider variance is ruled out by unchanged model/timeout/retry config for this diagnosis. The post-OOM and held-out Wave 1 logs also stay slow (`10261.8 ms` and `12463.4 ms` mean Stage 2 latency), so the issue persists beyond a single smoke run.

## 6. Root Cause Conclusion

One-sentence root cause: **Wave 1 made every Stage 2 call generate an additional reasoning-bearing `stance` object and increased Stage 2 call volume, causing an across-the-distribution completion-time shift; the +227 char prompt increase, outliers, and config/provider changes do not explain the +4.3s mean / +3.9s p50 regression.**

Supporting facts:

- Stage 2 call count increased from 40 to 57.
- p50 shifted from 6718.0 ms to 10622.1 ms, so this is not a tail-only outlier issue.
- Measured prompt delta is only +227 chars with no AO-history injection.
- Wave 1 persisted `intent+stance` hints average 360.4 chars; the new `stance` hint alone averages 131.6 chars.
- Parse failure/retry does not explain the shift: Wave 1 intent and stance hint parse success are both 57/57.

## 7. Three-tier Optimization Options (Task E)

### E.1 Zero-cost option: compact Stage 2 output and add minimal observability

Change only the Stage 2 prompt:

- Require `intent.reasoning` and `stance.reasoning` to be omitted or capped to a very short phrase.
- Require `stance` to output only `{value, confidence}` unless confidence is low.
- Ask for compact JSON, no prose, no explanatory reasoning unless needed.
- Add telemetry for `stage2_response_chars`, `stage2_intent_chars`, `stage2_stance_chars`, and provider usage if already available from `services.llm_client` without changing routing behavior.

Expected effect:

- Output lower-bound reduction: about 100-180 chars per call, roughly 25-45 generated tokens.
- Latency estimate: 1500-3000 ms per Stage 2 call if qwen-plus latency is dominated by JSON completion tokens in this band.
- Wave 1 p50 target after E.1: approximately 7.5-9.0s.

Implementation effort: 1 commit.

### E.2 Small-cost option: compact response schema plus parser update

Replace verbose fields with compact schema:

- `slots` unchanged or lightly compacted.
- `intent: {tool, conf}` instead of `{resolved_tool, intent_confidence, reasoning}`.
- `stance: {v, c}` instead of `{value, confidence, reasoning}`.
- Use enum values (`d`, `delib`, `explore`) only internally if parser maps them back.

Expected effect:

- Output lower-bound reduction: about 180-280 chars per call, plus less schema-following burden.
- Latency estimate: 2500-4000 ms per Stage 2 call.
- Wave 1 p50 target after E.2: approximately 6.5-8.0s.

Implementation effort: 2-3 commits: prompt/schema change, parser compatibility update, regression tests for legacy and compact payloads.

### E.3 Architecture option: split or restructure Stage 2 decisions

Two viable directions:

- Split stance resolution from slot filling: run fast rule stance first; call LLM stance only for ambiguous deliberative/exploratory cases. Most directive factor queries would avoid stance generation.
- Or keep one call but make it a compact unified classifier with streaming/early parse fields, so intent/stance can be consumed without waiting for verbose slot reasoning.

Expected effect:

- If stance LLM is skipped for common directive tasks, Stage 2 output can approach Phase 2.4 size and call volume can be reduced.
- Latency estimate: 3000-5000 ms reduction on affected calls; possible return to 6-7s p50 for Stage 2-heavy smoke.

Implementation effort: larger, about 1-2 days, because it changes resolver boundaries and requires broader regression coverage.

## 8. Recommendation for Wave 2

Do a small E.1 optimization before Wave 2 if Wave 2 depends on E-group latency staying under control. It is low-risk, does not require architecture changes, and should plausibly bring Stage 2 p50 back near or below 8-9s.

Do not start the full 7-group Wave 2 held-out matrix with current Stage 2 behavior unless a latency budget alarm is added. Current observed means are:

- Wave 1 smoke E: 11127.1 ms
- post-OOM smoke E: 10261.8 ms
- Wave 1 held-out E: 12463.4 ms

Recommended Wave 2 gate:

1. Apply E.1 prompt compacting and telemetry-only observability.
2. Re-run the existing 40-task Wave 1 smoke E only, not the full benchmark matrix.
3. Proceed to Wave 2 if Stage 2 p50 is <= 9000 ms and mean is <= 9000 ms.
4. If E.1 does not clear that gate, defer E.3 until after Wave 2 planning and add a hard latency alarm to the Wave 2 prompt/runbook.
