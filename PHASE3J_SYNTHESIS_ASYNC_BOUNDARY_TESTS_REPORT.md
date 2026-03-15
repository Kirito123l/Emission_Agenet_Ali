# Phase 3J Synthesis Async Boundary Tests Report

## 1. Executive Summary

This round added a small mocked-async protection layer around `UnifiedRouter._synthesize_results(...)` in `core/router.py`.

New protections added:

- one happy-path async synthesis test that verifies `_synthesize_results(...)` awaits `self.llm.chat(...)`, passes a stable high-level request shape, and returns the mocked content
- one no-call fallback-path test that verifies `_synthesize_results(...)` does **not** await `self.llm.chat(...)` when tool failure should short-circuit to deterministic fallback formatting

These scenarios were chosen because they protect the highest-value current boundary:

- the remaining async LLM-call shell inside `_synthesize_results(...)`
- the current call-vs-no-call decision at that method boundary

What was intentionally left untested:

- exact synthesis prose beyond the mocked returned content
- logging side effects
- hallucination-warning logging behavior as a direct assertion target
- broader `_process_response(...)` or `chat(...)` control flow

## 2. Boundary Inspection Summary

### How `_synthesize_results(...)` currently behaves at the async boundary

In the live code, `_synthesize_results(...)` now does three main things:

1. checks deterministic short-circuit conditions through extracted helper wrappers
2. if no short-circuit applies, builds a synthesis request and awaits `self.llm.chat(...)`
3. logs response metadata, scans for hallucination-warning keywords, and returns `synthesis_response.content`

That means the current high-risk boundary is no longer helper formatting. It is the method-level decision between:

- returning a deterministic short-circuit result without touching the LLM
- or calling the async LLM with the current request shape

### Scenarios considered

Considered:

- multi-tool success path that should reach the LLM
- single-tool knowledge short-circuit path
- failed-tool fallback path
- mocked empty or malformed synthesis response handling

Selected for this round:

- multi-tool success path
- failed-tool fallback short-circuit path

### Why these were the best fit

- together they cover the most important branch boundary: **call vs no-call**
- they avoid unstable external dependencies
- they assert stable request/result properties without snapshotting long prose
- they keep the async mocking very small and reviewable

## 3. Tests Added or Updated

### Files changed

- `tests/test_router_contracts.py`
- `DEVELOPMENT.md`

### New tests added

#### `test_synthesize_results_calls_llm_with_built_request_and_returns_content`

What it checks:

- `_synthesize_results(...)` awaits `self.llm.chat(...)` for a representative multi-tool success case
- the `messages` argument preserves the current last-user-message contract
- the `system` prompt still contains the synthesized tool payload at a stable high level
- the returned mocked `content` is passed through unchanged

Why this is thin-but-high-value:

- it protects the real async boundary without asserting the full prompt body
- it verifies the current LLM request contract at the method edge
- it locks in the current return behavior for the happy path

#### `test_synthesize_results_short_circuits_failures_without_calling_llm`

What it checks:

- `_synthesize_results(...)` does **not** await `self.llm.chat(...)` when a failed tool result should trigger deterministic fallback formatting
- the returned text is the current fallback-shaped result rather than an LLM synthesis response

Why this is thin-but-high-value:

- it protects the no-call branch most likely to matter during future synthesis refactoring
- it verifies the current boundary decision without over-specifying the entire fallback text

### Tiny maintainer-facing note

Updated `DEVELOPMENT.md` so the existing router-contract test command explicitly covers `core/router.py` synthesis changes as well as payload/fallback/memory changes.

## 4. Verification

### Commands run

```bash
pytest tests/test_router_contracts.py
python main.py health
pytest
```

### What passed

- `pytest tests/test_router_contracts.py`: passed (`18 passed`)
- `python main.py health`: passed
- full `pytest`: passed (`74 passed`)

### Warnings / limitations

- existing FastAPI `@app.on_event(...)` deprecation warnings remain
- existing `datetime.utcnow()` deprecation warning from `api/logging_config.py` remains
- the optional `FlagEmbedding` warning during `python main.py health` remains

These were already present and were intentionally left unchanged.

## 5. What Was Intentionally NOT Changed

- no structural extraction was performed
- no changes were made to `core/router.py`
- no `_process_response(...)` work was done
- no `chat(...)` work was done
- no broad async router test framework was introduced
- no synthesis prompt or payload contract was redesigned

Deeper router areas still deferred:

- the remaining async shell inside `_synthesize_results(...)`
- `_process_response(...)`
- `chat(...)`
- orchestration/retry behavior
- direct assertions on synthesis logging policy

## 6. Recommended Next Step

Keep deeper synthesis extraction paused for now and use the new async boundary tests as the current guardrail.

The next concrete move should be one of these, but not both at once:

- re-evaluate whether the remaining `_synthesize_results(...)` shell is worth extracting now that call/no-call behavior is protected
- or explicitly decide that the async synthesis shell should remain in `core/router.py` and shift attention to higher-level router control-flow protection instead

## Suggested Next Safe Actions

- [x] Add one mocked async happy-path boundary test for `_synthesize_results(...)`.
- [x] Add one mocked async no-call fallback-path boundary test for `_synthesize_results(...)`.
- [x] Keep router structure unchanged while improving protection.
- [x] Re-run focused router tests, health check, and the full test suite.
- [ ] Re-evaluate whether deeper `_synthesize_results(...)` extraction is still worth pursuing.
- [ ] Avoid jumping directly into `_process_response(...)` or `chat(...)` refactoring without a separate protection plan.
