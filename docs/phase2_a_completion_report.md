# Phase 2 A Completion Report

## Implementation Status

A.2 through A.6 completed. Full pytest passed: `1249 passed, 40 warnings`.

A.7 smoke scaffolding is in place. The user must run local pre/post smoke because Codex sandbox LLM/network behavior is not stable enough for acceptance evidence. Smoke verdict fields remain TODO until `evaluation/results/a_smoke/{pre,post}/` are produced locally.

## Change List

### A.2 ReplyContext Schema and Builder

- `core/reply/__init__.py`: exports the reply parser boundary surface.
- `core/reply/reply_context.py:14`: `ToolExecutionSummary` strict dataclass.
- `core/reply/reply_context.py:43`: `ClarificationRequest` strict dataclass.
- `core/reply/reply_context.py:66`: `AOStatusSummary` strict dataclass.
- `core/reply/reply_context.py:89`: `ReplyContext` strict dataclass with first-class `router_text`.
- `core/reply/reply_context.py:147`: strict `from_dict` helper rejects unknown fields.
- `core/reply/reply_context_builder.py:33`: pure `ReplyContextBuilder`.
- `core/reply/reply_context_builder.py:36`: `build(...)` assembles context from trace, AO, violations, and context store.

### A.3 LLM Reply Parser

- `core/reply/llm_parser.py:14`: prototype-derived system prompt.
- `core/reply/llm_parser.py:21`: prototype-derived prompt template.
- `core/reply/llm_parser.py:27`: `LLMReplyTimeout`.
- `core/reply/llm_parser.py:31`: `LLMReplyError`.
- `core/reply/llm_parser.py:35`: `LLMReplyParser`.
- `core/reply/llm_parser.py:46`: async `parse(...)` with 20s default timeout and explicit failure modes.

### A.4 Feature Flag and Fallback

- `config.py:154`: `ENABLE_LLM_REPLY_PARSER`, default `true`.
- `tests/test_config.py`: default feature flag assertion.
- `core/governed_router.py:178`: `_generate_final_reply(...)` feature-flag switch and fallback.
- `core/governed_router.py:196`: LLM parser timeout/error fallback keeps `ctx.router_text`.

### A.5 GovernedRouter Integration

- `core/governed_router.py:25`: imports reply boundary only in governance layer.
- `core/governed_router.py:157`: builds `ReplyContext` after constraint violation trace consumption and contract `after_turn`.
- `core/governed_router.py:167`: overwrites `result.text` with LLM reply or router-text fallback.
- `core/governed_router.py:202`: records `reply_generation` trace metadata.
- `core/trace.py:112`: `TraceStepType.REPLY_GENERATION`.
- `core/trace.py`: friendly trace rendering for reply generation.

### A.6 Tests

- `tests/test_reply_context.py`: 8 tests for strict schema, builder behavior, purity, and data-quality report routing.
- `tests/test_llm_reply_parser.py`: 4 tests for parser success, timeout, API error, and prompt coverage.
- `tests/test_governed_router_reply_integration.py`: 4 tests for LLM success, timeout fallback, feature flag disabled, and NaiveRouter isolation.

### A.7 Smoke Scaffolding

- `evaluation/results/a_smoke/build_smoke_10.py`: deterministic local smoke subset builder.
- `docs/phase2_a_smoke_comparison.md`: pre/post command template and three-layer verdict skeleton.

## Deviations From Prompt

- The smoke subset file keeps the historical name `smoke_10.jsonl`, but the current benchmark resolves to 11 tasks: 9 category-first tasks plus 2 sensitivity duplicates. This follows the prompt's instruction to adjust for actual category availability while keeping the target close to 10.
- Smoke sampling prefers each category's native task-ID prefix before sorting by task ID, so reclassified tasks in another ID family do not displace canonical category smoke cases.
- `fallback` does not call a separate regex parser module. It keeps `router_text`, the existing governed-router rendered output, which is the actual legacy rendering surface identified in A.1.
- Smoke execution was not run in Codex. This follows the updated sandbox rule: user-local LLM smoke, Codex reads and fills results afterward.

## ReplyContext Schema Final Version

| Field | Type | Meaning |
|---|---|---|
| `user_message` | `str` | Current user input after governed-router message overrides. |
| `router_text` | `str` | Existing router-rendered reply, used as safe fallback and fact-checking draft. |
| `tool_executions` | `List[ToolExecutionSummary]` | Tool calls and compact execution outcomes from current trace. |
| `violations` | `List[ViolationRecord]` | Current AO constraint violations from Task Pack B writer. |
| `pending_clarifications` | `List[ClarificationRequest]` | Clarification-like trace events requiring user follow-up. |
| `ao_status` | `Optional[AOStatusSummary]` | Current analytical objective state, objective text, and completed tool steps. |
| `trace_highlights` | `List[Dict[str, Any]]` | LLM-safe summaries of important trace steps. |
| `extra` | `Dict[str, Any]` | Explicit extension outlet, currently includes `data_quality_report` when present. |

Nested schemas:

- `ToolExecutionSummary`: `tool_name`, `arguments`, `success`, `summary`, optional `error`.
- `ClarificationRequest`: `target_field`, `reason`, `options`.
- `AOStatusSummary`: `state`, `objective`, `completed_steps`.

Strict deserialization:

- `ReplyContext.from_dict` rejects unknown top-level fields with `ValueError`.
- All child dataclasses also reject unknown fields.
- Non-core extensions must use `extra`.

## Dual-Path Architecture Description

The production path is:

1. `UnifiedRouter` executes the existing planning/tool/synthesis flow and returns `RouterResponse`.
2. `GovernedRouter` consumes trace events for constraint violation persistence.
3. `GovernedRouter` runs contract `after_turn` hooks.
4. `ReplyContextBuilder` constructs a strict `ReplyContext` from trace, AO state, constraint writer, context store, and `router_text`.
5. If `ENABLE_LLM_REPLY_PARSER=true`, `LLMReplyParser` rewrites the final reply from `ReplyContext`.
6. If the flag is false, parser is unavailable, timeout occurs, or provider error occurs, `GovernedRouter` keeps `ctx.router_text`.
7. `reply_generation` trace records mode, fallback, reason, latency, and model metadata where available.

`UnifiedRouter` remains unaware of the reply parser. `NaiveRouter` remains on its own reply path.

## Architecture Boundary Verification

- `UnifiedRouter` does not import `core.reply`: `grep -n "from core.reply\|import core.reply" core/router.py` returns no matches.
- `ReplyContextBuilder.build()` is pure: it returns a new `ReplyContext` and does not assign to `self`.
- `router_text` is a top-level `ReplyContext` field at `core/reply/reply_context.py:92`.
- Fallback returns `ctx.router_text` at `core/governed_router.py:196`.
- `reply_generation` trace output includes `mode`, `fallback`, and `reason` via metadata expansion at `core/governed_router.py:221`.
- `LLMReplyParser.parse()` converts `asyncio.TimeoutError` to `LLMReplyTimeout` and other exceptions to `LLMReplyError` at `core/reply/llm_parser.py:69`.
- `NaiveRouter` does not import `core.reply`: `grep -rn "from core.reply\|import core.reply" core/naive_router.py` returns no matches.

## Test Results

Full regression:

```text
/home/kirito/miniconda3/bin/python -m pytest tests/ -q --tb=line
1249 passed, 40 warnings in 86.00s
```

New A.6 test distribution:

| File | Count |
|---|---:|
| `tests/test_reply_context.py` | 8 |
| `tests/test_llm_reply_parser.py` | 4 |
| `tests/test_governed_router_reply_integration.py` | 4 |
| Total | 16 |

## Smoke Three-Layer Verdict

TODO after user-local pre/post smoke.

Required local commands are documented in `docs/phase2_a_smoke_comparison.md`.

Expected data sources after local run:

- `evaluation/results/a_smoke/pre/end2end_metrics.json`
- `evaluation/results/a_smoke/post/end2end_metrics.json`
- `evaluation/results/a_smoke/pre/end2end_logs.jsonl`
- `evaluation/results/a_smoke/post/end2end_logs.jsonl`

## Downstream Notes for E-Remaining

- The legacy rendering layer (`_state_build_response`, `router_synthesis_utils`, `router_render_utils`) remains the main path when `ENABLE_LLM_REPLY_PARSER=false`. Task Pack A did not delete it.
- `router_text` is the fact-checking baseline and fallback output in `ReplyContext`. Do not remove it from fallback paths before Phase 3 production latency and quality evidence are collected.
- `parameter_negotiation.py:435` and `input_completion.py:607` are user-input parsers, not final reply renderers. They are out of scope for Task Pack A and should not be treated as removable legacy reply parsers.
- `data_quality_report` is intentionally routed through `ReplyContext.extra["data_quality_report"]`, not promoted into core schema fields.

## Known Issues / TODO

- Smoke three-layer verdict remains TODO until user-local pre/post smoke is complete.
- Prototype evidence showed smaller marginal gains on simple/ambiguous cases where legacy output was already acceptable. Phase 3 may consider skip heuristics, but this Task Pack keeps one uniform path.
- LLM reply generation is latency-sensitive. `timeout=20s` was selected from prototype evidence; Phase 3 should revisit after collecting production latency distribution.
- Regex/legacy rendering deletion criteria are not met. Keep router-text fallback until E-remaining or Phase 3 explicitly defines removal gates.
