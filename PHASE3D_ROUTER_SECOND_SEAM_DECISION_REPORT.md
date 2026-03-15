# Phase 3D Router Second Seam Decision Report

## 1. Executive Summary

I reconstructed the current project/refactor state from the required local reports and verified the live router code before making this decision.

Current assessment of `core/router.py`:

- the first approved router seam was extracted successfully in Phase 3C
- compatibility was preserved through wrappers in `core/router.py`
- the remaining router code is now dominated by:
  - frontend payload shaping
  - synthesis/rendering policy
  - orchestration/control-flow logic
- the only plausible second seam is some portion of the payload-extraction helper area

Recommendation: **NO-GO**

Recommended next focus:

- pause further `core/router.py` extraction
- first add the missing router contract protection for:
  - `query_emission_factors` table shaping
  - `calculate_micro_emission` table shaping
- then re-evaluate whether a coherent payload-extraction seam is ready

## 2. Context Reconstruction

### Prior local docs read

I read the following local documents:

- `REPOSITORY_ENGINEERING_AUDIT.md`
- `PHASE0_MINIMAL_PHASE1_EXECUTION_REPORT.md`
- `PHASE1B_CONSOLIDATION_REPORT.md`
- `PHASE1C_ENTRYPOINTS_AND_EVAL_REPORT.md`
- `PHASE1D_DEV_GUIDE_AND_REFACTOR_PREP_REPORT.md`
- `PHASE2A_API_ROUTES_FIRST_EXTRACTION_REPORT.md`
- `PHASE2B_API_ROUTES_SECOND_EXTRACTION_REPORT.md`
- `PHASE2C_API_CONTRACT_TESTS_REPORT.md`
- `PHASE2D_API_SEAM_REEVALUATION_REPORT.md`
- `PHASE3A_ROUTER_CONTRACT_PROTECTION_REPORT.md`
- `PHASE3B_ROUTER_SEAM_REEVALUATION_REPORT.md`
- `PHASE3C_ROUTER_FIRST_EXTRACTION_REPORT.md`
- `ROUTER_REFACTOR_PREP.md`
- `DEVELOPMENT.md`
- `RUNNING.md`

### Phases already completed

- repository audit and Phase 0/minimal Phase 1 established the initial safety, licensing, and test baseline
- Phase 1B clarified LLM client boundaries and the active `tools/` vs transitional `skills/` boundary
- Phase 1C clarified canonical run entry points and evaluation/reproducibility paths
- Phase 1D added maintainer-facing navigation and refactor-prep documentation
- Phase 2A and Phase 2B completed two successful helper-only extractions from `api/routes.py`
- Phase 2C added thin API route-level contract tests
- Phase 2D explicitly concluded that further `api/routes.py` extraction should pause
- Phase 3A added thin router-level contract protection around payload/result behavior
- Phase 3B concluded that only one tiny first seam in `core/router.py` was justified
- Phase 3C extracted only that approved seam into `core/router_memory_utils.py`

### Guardrails and protections already in place

- root-level maintainer navigation in `DEVELOPMENT.md`
- canonical run instructions in `RUNNING.md`
- router payload/result contract tests in `tests/test_router_contracts.py`
- API route contract tests in `tests/test_api_route_contracts.py`
- a conservative extraction pattern already proven on `api/routes.py`
- a first compatibility-preserving extraction now proven on `core/router.py`

### Current structural position of the project

- `api/routes.py` helper-only seams are exhausted for now and route-flow extraction is paused
- `core/router.py` has begun decomposition, but only at the smallest deterministic seam
- larger router seams remain under debate because they mix user-facing payload shaping with partially protected branches

## 3. Verified Current `core/router.py` State

### What Phase 3C actually changed

Verified in the live code:

- `core/router_memory_utils.py` now contains:
  - `compact_tool_data(...)`
  - `build_memory_tool_calls(...)`
- `core/router.py` imports those helpers and retains wrapper methods:
  - `_build_memory_tool_calls(...)`
  - `_compact_tool_data(...)`
- `_process_response(...)` still calls `self._build_memory_tool_calls(tool_results)` exactly as before

This confirms that Phase 3C was a real extraction, not just a comment-only change, and that compatibility glue remains in place.

### What remains in `core/router.py`

The live router still contains these major responsibility clusters:

- `chat`:
  - file-analysis/cache handling
  - context assembly
  - LLM tool-call routing
  - memory update
- `_process_response`:
  - direct-response branch
  - tool execution loop
  - retry/error handling
  - synthesis handoff
  - payload extraction
  - final `RouterResponse` assembly
- synthesis/rendering helpers:
  - `_synthesize_results`
  - `_render_single_tool_success`
  - `_filter_results_for_synthesis`
  - `_format_tool_errors`
  - `_format_tool_results`
  - `_format_results_as_fallback`
- payload helpers:
  - `_extract_chart_data`
  - `_format_emission_factors_chart`
  - `_extract_table_data`
  - `_extract_download_file`
  - `_extract_map_data`

### What compatibility wrappers or helper modules exist

- helper module:
  - `core/router_memory_utils.py`
- wrapper methods remaining in `core/router.py`:
  - `_build_memory_tool_calls`
  - `_compact_tool_data`

### What current router protections already cover

Verified in `tests/test_router_contracts.py`:

- memory compaction behavior
- compatibility between `core.router_memory_utils` and `core.router` wrappers
- chart payload precedence and formatting
- macro table preview shaping
- download and map extraction
- deterministic fallback formatting

I also re-ran:

```bash
pytest tests/test_router_contracts.py
```

Result:

- passed (`7 passed`)

### What current router protections do not yet cover

- `query_emission_factors` table shaping
- `calculate_micro_emission` table shaping
- `_render_single_tool_success`
- `_filter_results_for_synthesis`
- `_format_tool_errors`
- `_format_tool_results`
- `chat`
- `_process_response`
- retry behavior
- direct-response behavior

## 4. Candidate Seam Analysis

### Candidate 1: Narrow payload-extraction sub-seam

Description:

- `_extract_chart_data`
- `_format_emission_factors_chart`
- `_extract_download_file`
- `_extract_map_data`

Coupling level:

- Low to medium
- These are deterministic helper-style methods and do not depend on router instance state.
- They are still coupled to tool result schemas and frontend/API payload expectations.

Expected maintainability value if extracted:

- Moderate
- Would remove a meaningful pure-helper slice from `core/router.py`.
- Would continue the helper-extraction pattern without touching orchestration.

Current protection level:

- Medium to high
- Chart behavior is covered.
- Download and map extraction are covered.
- This sub-seam avoids the currently under-protected table branches.

Estimated regression risk:

- Low to medium
- Technically feasible, but it would split the payload helper area in an awkward partial way and leave the more complex table logic behind.

Assessment:

- plausible, but not clearly better than waiting

### Candidate 2: Full payload-extraction helper cluster

Description:

- `_extract_chart_data`
- `_format_emission_factors_chart`
- `_extract_table_data`
- `_extract_download_file`
- `_extract_map_data`

Coupling level:

- Low to medium
- Helper-like, but tightly coupled to multiple tool-result shapes and frontend expectations.
- `_extract_table_data` is the most complex and branch-heavy part.

Expected maintainability value if extracted:

- High
- This is still the largest remaining helper-style block in the router.

Current protection level:

- Mixed
- chart, macro-table, download, and map paths are protected
- `query_emission_factors` table shaping is not directly protected
- `calculate_micro_emission` table shaping is not directly protected

Estimated regression risk:

- Medium
- The under-protected table branches are exactly the parts most likely to drift during extraction.

Assessment:

- not justified yet

### Candidate 3: Synthesis/rendering helper cluster

Description:

- `_synthesize_results`
- `_render_single_tool_success`
- `_filter_results_for_synthesis`
- `_format_tool_errors`
- `_format_tool_results`
- `_format_results_as_fallback`

Coupling level:

- Medium to high
- Close to LLM behavior, retry behavior, and text-format expectations.
- `fallback` is deterministic, but the rest of the cluster is semantically tied to synthesis policy.

Expected maintainability value if extracted:

- Moderate
- Could shrink the synthesis area, but not without more text-oriented contract protection.

Current protection level:

- Weak to mixed
- Only `_format_results_as_fallback` has meaningful protection now.

Estimated regression risk:

- Medium to high
- User-facing text behavior would be more brittle than the already-extracted seam.

Assessment:

- not a good second seam

### Candidate 4: File-analysis/cache or control-flow seams

Description:

- file-analysis/cache block in `chat`
- `_process_response`
- parts of the tool-loop/retry flow

Coupling level:

- High
- These are the most stateful and behavior-sensitive parts of the router.

Expected maintainability value if extracted:

- Potentially high later, but not through a safe second extraction now.

Current protection level:

- Low
- current tests do not meaningfully protect these branches

Estimated regression risk:

- High

Assessment:

- explicitly not ready

## 5. Decision Analysis

### Option A: GO

The only plausible GO option is the narrow payload-extraction sub-seam:

- chart formatting
- chart extraction
- download extraction
- map extraction

Why GO is tempting:

- helper-like and deterministic
- current tests already protect most of that behavior
- no direct dependency on router instance state

Why GO is still not the better decision:

- it would fragment the payload helper area before the table branches are protected
- the maintainability gain is only moderate
- the more coherent payload-extraction seam remains blocked on missing table-path protection
- there is no urgency created by the current live repository state that outweighs waiting for better protection

### Option B: NO-GO

Pause second extraction and first add more protection.

Why NO-GO is stronger:

- Phase 3C already identified the missing table-path protection as the next safe prerequisite
- that gap still exists in the live tests
- the larger remaining seams are still either under-protected or too awkward to split cleanly
- a second extraction now would be driven more by momentum than by improved readiness

### Explicit comparison

Risk:

- GO on a narrow payload sub-seam: low to medium
- NO-GO: lower

Payoff:

- GO: moderate
- NO-GO: no structural change now, but keeps the next extraction cleaner and more coherent

Readiness:

- narrow payload sub-seam: arguable
- coherent full payload seam: not ready
- synthesis/control-flow seams: not ready

Protection adequacy:

- enough for a narrow sub-seam
- not enough for the cleaner full payload seam

Expected maintainability improvement:

- narrow sub-seam: modest
- waiting for missing table tests first: improves the chance of a more coherent next extraction

Whether the seam is truly better than waiting:

- no

## 6. Recommendation

Recommendation: **NO-GO**

Exact recommended next action:

- add focused router contract tests for:
  - `query_emission_factors` table shaping
  - `calculate_micro_emission` table shaping
- then re-evaluate whether a coherent payload-extraction seam is justified

What should not be done next:

- do not extract another helper cluster from `core/router.py` yet
- do not split the payload helper area into an awkward partial subcluster just because it is technically possible
- do not touch `chat`, `_process_response`, or synthesis/control-flow logic
- do not redesign the router/executor interface

## 7. Any Tiny Clarifications Made

None.

## 8. Follow-up Guidance

What should happen in the next round:

- treat it as a protection/clarity round, not an extraction round
- add the two missing table-path contract tests
- optionally add one very small mocked `_process_response()` happy-path smoke test only if it can be done without large fixture complexity

Prerequisites before the next structural move:

- direct protection for:
  - `query_emission_factors` table branch
  - `calculate_micro_emission` table branch
- confirmation that the payload helper area can be extracted as a coherent unit or a clearly justified subset

## Suggested Next Safe Actions

- [x] Reconstruct the current project state from the required local reports.
- [x] Verify that Phase 3C actually extracted only the memory-compaction helper pair.
- [x] Reassess the remaining major responsibility clusters in `core/router.py`.
- [x] Compare GO vs NO-GO for a second router extraction seam.
- [x] Record that the current recommendation is NO-GO.
- [ ] Add contract coverage for `query_emission_factors` table shaping.
- [ ] Add contract coverage for `calculate_micro_emission` table shaping.
- [ ] Re-evaluate the payload-extraction helper area only after those guards exist.
