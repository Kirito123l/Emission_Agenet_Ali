# Phase 3B Router Seam Re-evaluation Report

## 1. Executive Summary

Current assessment: `core/router.py` still mixes several responsibilities, but it now contains one clearly justifiable first extraction seam.

Recommendation: **GO**, but only for the small memory-compaction helper cluster:

- `_build_memory_tool_calls`
- `_compact_tool_data`

This seam is the smallest, least coupled, and most directly protected by the current router contract tests. It is also used at a single call site in `_process_response`, which keeps the compatibility surface narrow.

The recommended next focus is **not** a broad router split. It is a future single-seam extraction of the memory-compaction helpers only, while leaving:

- `chat`
- `_process_response`
- `_synthesize_results`
- the full table/chart payload shaping block

untouched for now.

## 2. Current `core/router.py` State

`core/router.py` is currently 1161 lines and still combines several distinct responsibilities.

### Major responsibility clusters

- Router entry and orchestration:
  - `UnifiedRouter.chat`
  - file-analysis cache lookup
  - context assembly
  - LLM tool-call routing
  - memory update
- Tool-loop and control flow:
  - `_process_response`
  - retry handling
  - tool execution loop
  - synthesis dispatch
  - final `RouterResponse` assembly
- Synthesis and rendering:
  - `_synthesize_results`
  - `_render_single_tool_success`
  - `_filter_results_for_synthesis`
  - `_format_tool_errors`
  - `_format_tool_results`
  - `_format_results_as_fallback`
- Result/payload shaping:
  - `_extract_chart_data`
  - `_format_emission_factors_chart`
  - `_extract_table_data`
  - `_extract_download_file`
  - `_extract_map_data`
- Memory compaction:
  - `_build_memory_tool_calls`
  - `_compact_tool_data`

### More helper/result-shaping oriented areas

- `_build_memory_tool_calls`
- `_compact_tool_data`
- `_extract_chart_data`
- `_format_emission_factors_chart`
- `_extract_table_data`
- `_extract_download_file`
- `_extract_map_data`
- `_format_results_as_fallback`

These are deterministic helper-style surfaces operating on tool result dictionaries rather than live router state.

### More orchestration/state/LLM/tool-loop specific areas

- `chat`
- `_process_response`
- `_analyze_file`
- `_synthesize_results`

These methods are coupled to runtime config, memory state, executor behavior, LLM calls, retry behavior, and trace capture.

### Current protections already in place

- `tests/test_router_contracts.py` protects:
  - memory tool-call compaction
  - chart payload extraction/formatting
  - macro table preview formatting
  - download/map extraction
  - fallback formatting
- `api/session.py` and `api/routes.py` provide downstream evidence that these router payload shapes matter:
  - `text`
  - `chart_data`
  - `table_data`
  - `map_data`
  - `download_file`
- No comparable protection yet exists for:
  - `chat`
  - `_process_response`
  - retry behavior
  - synthesis branches other than fallback formatting
  - `query_emission_factors` table shaping
  - `calculate_micro_emission` table shaping

## 3. Candidate Seam Analysis

### Candidate 1: Memory compaction helpers

Description:

- `_build_memory_tool_calls`
- `_compact_tool_data`

Coupling level:

- Low
- They do not depend on router instance state beyond method dispatch.
- They operate only on `tool_results`/`data` dictionaries.
- They are used from a single call site in `_process_response`.

Expected maintainability value if extracted:

- Moderate
- Separates memory-grounding preparation from the orchestration loop.
- Reduces responsibility overlap inside `_process_response`.
- Creates a small, reviewable first router extraction without pulling on LLM or tool-loop behavior.

Current protection level:

- Good for a first-pass helper extraction
- Directly covered by `tests/test_router_contracts.py::test_build_memory_tool_calls_compacts_large_payloads_for_follow_up_turns`

Estimated regression risk:

- Low
- The main observable risk is the shape of `executed_tool_calls`, which is already covered by the current contract test.

Assessment:

- Strongest first seam

### Candidate 2: Frontend payload extraction helpers as a cluster

Description:

- `_extract_chart_data`
- `_format_emission_factors_chart`
- `_extract_table_data`
- `_extract_download_file`
- `_extract_map_data`

Coupling level:

- Low to medium
- They do not rely on router instance state, but they are tightly coupled to tool result schemas and frontend/API expectations.
- `_extract_table_data` is the most complex branch-heavy method in the cluster.

Expected maintainability value if extracted:

- High
- This is a large block and conceptually separate from orchestration.
- It would remove a substantial amount of presentation/payload logic from `core/router.py`.

Current protection level:

- Mixed
- Chart, macro-table, download, and map paths are protected.
- `query_emission_factors` table paths are not yet directly protected.
- `calculate_micro_emission` table shaping is not yet directly protected.

Estimated regression risk:

- Medium
- The cluster is attractive, but `_extract_table_data` contains several tool-specific branches and more behavioral surface than the current tests cover.

Assessment:

- Plausible later seam, but still too broad for the first router extraction

### Candidate 3: Synthesis/rendering helpers

Description:

- `_render_single_tool_success`
- `_filter_results_for_synthesis`
- `_format_tool_errors`
- `_format_tool_results`
- `_format_results_as_fallback`

Coupling level:

- Medium
- These methods are deterministic, but they are semantically tied to synthesis policy and human-readable output expectations.
- They sit closer to the LLM and retry flows than the other helper candidates.

Expected maintainability value if extracted:

- Moderate
- Would reduce density inside `_synthesize_results`.
- Could clarify deterministic-vs-LLM formatting boundaries later.

Current protection level:

- Weak to mixed
- `_format_results_as_fallback` is protected.
- The rest of the cluster is not meaningfully covered.
- `_render_single_tool_success` in particular would need more text-oriented assertions.

Estimated regression risk:

- Medium to high
- Output-format churn risk is higher here than for memory compaction.

Assessment:

- Not ready for first extraction

### Candidate 4: File-analysis/cache preparation block in `chat`

Description:

- file upload analysis
- cache validation
- runtime-flag branching
- file context persistence

Coupling level:

- High
- Depends on runtime config, memory contents, filesystem state, and file analyzer behavior.

Expected maintainability value if extracted:

- Moderate in the long run
- But it would still leave most of `chat` highly stateful.

Current protection level:

- Low
- No direct contract layer around this branch yet.

Estimated regression risk:

- High

Assessment:

- Explicitly not a first seam

## 4. Decision Analysis

### Option A: GO

There is one justified first extraction seam now:

- the memory compaction helper cluster

Why GO is justified:

- It is the smallest serious seam in the file.
- It is deterministic and state-light.
- It is used in only one place.
- It already has direct contract coverage.
- It is easy to keep compatibility-preserving by importing the extracted helpers back into `core/router.py`.

Payoff:

- Smaller than the payload-extraction cluster, but still real.
- It proves router extraction mechanics without touching orchestration or frontend payload assembly.
- It reduces responsibility mixing in `_process_response`.

Risk:

- Lower than any other serious candidate seam in the file.

### Option B: NO-GO

A full NO-GO would mean deferring all router extraction until more protection exists.

Why full NO-GO is not the best call:

- The current contract layer is already sufficient for one narrow deterministic seam.
- Waiting longer would not materially improve safety for the memory-compaction seam.
- Deferring all extraction would overstate the current coupling level of those two helper methods.

### Explicit comparison

Risk:

- GO on memory compaction: low
- NO-GO on everything: lowest possible, but more conservative than necessary

Payoff:

- GO on memory compaction: modest but concrete
- NO-GO on everything: no structural progress despite a viable seam already existing

Readiness:

- Memory compaction seam: ready now
- Payload extraction cluster: partially ready, but not ready as a first router extraction
- Synthesis/rendering cluster: not ready

Protection adequacy:

- Memory compaction seam: adequate
- Larger payload cluster: partial
- Orchestration seams: inadequate

Expected refactor safety:

- Highest for the memory compaction seam

Engineering value:

- Best risk-adjusted value comes from a very small first extraction, not from the largest removable block

## 5. Recommendation

Recommendation: **GO**

Exact recommended next action:

- In the next structural round, extract only:
  - `_build_memory_tool_calls`
  - `_compact_tool_data`
- Place them in one small dedicated helper module.
- Keep `core/router.py` import-compatible during the transition.
- Do not change the shape of `executed_tool_calls`.

What should remain untouched in that first extraction round:

- `chat`
- `_process_response`
- `_synthesize_results`
- `_render_single_tool_success`
- `_filter_results_for_synthesis`
- `_format_tool_errors`
- `_format_tool_results`
- `_extract_table_data`
- file-analysis/cache logic

What should not be done next:

- Do not jump directly to extracting the full payload-extraction block.
- Do not start with `_process_response` or `chat`.
- Do not try to merge router compaction logic with `core/memory` snapshot logic in the same round.
- Do not redesign the router/executor contract.

## 6. Any Tiny Clarifications Made

None in this round beyond this report.

## 7. Follow-up Guidance

Next round guidance:

- Treat the memory-compaction helper pair as the only approved first seam.
- Preserve the current `tests/test_router_contracts.py` guardrail.
- Keep the extraction compatibility-first:
  - same input shape
  - same returned structure
  - same call site behavior

Useful prerequisites before the later payload-extraction round:

- Add one focused contract test for `query_emission_factors` table shaping.
- Add one focused contract test for `calculate_micro_emission` table shaping.
- Consider one mocked `_process_response()` test before touching any control-flow seam.

## Suggested Next Safe Actions

- [x] Re-evaluate current `core/router.py` seams against the new router contract layer.
- [x] Identify one first seam with the best risk-adjusted extraction value.
- [x] Record that the memory-compaction helper pair is the current recommended first extraction target.
- [ ] In the next round, extract only `_build_memory_tool_calls` and `_compact_tool_data`.
- [ ] Add table-path protection before attempting the larger payload-extraction cluster.
- [ ] Keep `chat` and `_process_response` out of scope until helper extractions are stable.
