# Phase 3H Synthesize Body Execution Report

## 1. Executive Summary

Result: **GO + extraction performed**

This round re-evaluated the remaining body of `_synthesize_results(...)` after the rendering extraction and concluded that one bounded deterministic seam still remained:

- short-circuit synthesis policy
- synthesis-request preparation
- hallucination-keyword detection

Extraction performed:

- `_maybe_short_circuit_synthesis(...)`
- `_build_synthesis_request(...)`
- `_detect_synthesis_hallucination_keywords(...)`

What changed:

- the deterministic synthesis-preparation subset moved into `core/router_synthesis_utils.py`
- `core/router.py` kept thin compatibility wrappers
- focused tests were added for wrapper parity, short-circuit behavior, synthesis-request building, and hallucination-keyword detection

What was deferred:

- the actual async `self.llm.chat(...)` call
- `_synthesize_results(...)` as a whole
- `_process_response(...)`
- `chat(...)`

## 2. Seam Re-evaluation Summary

### Current assessment of the remaining `_synthesize_results` body

After the rendering subset moved out in Phase 3G, `_synthesize_results(...)` still mixed two different concerns:

- deterministic synthesis policy/preparation
- live async LLM invocation and logging

The live async LLM part was still not a good extraction target in this round because it remains coupled to:

- `self.llm.chat(...)`
- runtime logging policy
- the surrounding router orchestration

However, one smaller deterministic seam was still coherent and worthwhile:

- knowledge short-circuit handling
- failure short-circuit handling
- single-tool-success short-circuit handling
- filtered synthesis payload / prompt / message preparation
- hallucination-keyword scanning

### Why it was ready

- the extracted logic does not depend on router instance state
- it operates on plain `tool_results`, prompt text, and user-message strings
- it meaningfully reduces the remaining density inside `_synthesize_results(...)`
- it stays outside `_process_response(...)` and `chat(...)`
- it fits the already-proven compatibility-wrapper extraction pattern used in earlier router rounds

### Protections/tests relied on

Existing protection:

- rendering helper coverage from `tests/test_router_contracts.py`
- fallback-format coverage

New protection added in this round:

- wrapper/module compatibility coverage for the synthesis helpers
- one focused test for short-circuit synthesis behavior
- one focused test for synthesis-request building and hallucination-keyword detection

This was enough to support extracting the deterministic subset without pretending the async LLM call itself is now fully protected.

## 3. Concrete Work Performed

### Files created

- `core/router_synthesis_utils.py`
- `PHASE3H_SYNTHESIZE_BODY_EXECUTION_REPORT.md`

### Files changed

- `core/router.py`
- `tests/test_router_contracts.py`
- `DEVELOPMENT.md`

### What moved out of `core/router.py`

Moved into `core/router_synthesis_utils.py`:

- `maybe_short_circuit_synthesis(...)`
- `build_synthesis_request(...)`
- `detect_hallucination_keywords(...)`

### What remained in place

Left in `core/router.py`:

- thin compatibility wrappers named:
  - `_maybe_short_circuit_synthesis(...)`
  - `_build_synthesis_request(...)`
  - `_detect_synthesis_hallucination_keywords(...)`
- `_synthesize_results(...)`
- the actual async `self.llm.chat(...)` synthesis call
- `_process_response(...)`
- `chat(...)`

### How compatibility was preserved

- `core/router.py` now imports the extracted synthesis helpers and delegates through wrapper methods
- `_synthesize_results(...)` still keeps the same overall structure and return behavior
- the actual LLM invocation remains in the router, so no async behavior or client wiring changed
- new parity tests check that the extracted synthesis helpers and the router wrappers return the same results

## 4. Tests / Verification

### Commands run

```bash
pytest tests/test_router_contracts.py
python main.py health
pytest
```

### What passed

- `pytest tests/test_router_contracts.py`: passed (`16 passed`)
- `python main.py health`: passed
- full `pytest`: passed (`72 passed`)

### Warnings / limitations

- existing FastAPI `@app.on_event(...)` deprecation warnings remain
- existing `datetime.utcnow()` deprecation warning from `api/logging_config.py` remains
- the optional `FlagEmbedding` warning during `python main.py health` remains

These were already present and were intentionally left unchanged.

## 5. What Was Intentionally Left Untouched

Deferred router areas:

- `chat(...)`
- `_process_response(...)`
- `_analyze_file(...)`
- the async `self.llm.chat(...)` portion of `_synthesize_results(...)`
- synthesis-response logging policy beyond keyword detection

These were left untouched because they remain closer to live orchestration and async behavior than the deterministic synthesis-preparation subset extracted in this round.

## 6. Recommended Next Step

The next safe move is a dedicated decision on whether the remaining async LLM-call shell of `_synthesize_results(...)` is worth extracting at all. It may be better left in `core/router.py` unless one or two focused async/mock tests are added first. Do not jump directly into `_process_response(...)` or `chat(...)`.

## Suggested Next Safe Actions

- [x] Re-evaluate the remaining `_synthesize_results(...)` body.
- [x] Extract only the deterministic synthesis-preparation subset.
- [x] Preserve `core/router.py` compatibility through thin wrappers.
- [x] Add focused contract coverage for the new synthesis helper module.
- [ ] Decide separately whether the remaining async LLM-call shell should stay in `core/router.py`.
- [ ] Keep `_process_response(...)` and `chat(...)` out of scope until a later dedicated decision round.
