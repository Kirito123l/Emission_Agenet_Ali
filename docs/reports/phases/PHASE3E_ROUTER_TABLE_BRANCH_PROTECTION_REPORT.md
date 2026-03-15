# Phase 3E Router Table Branch Protection Report

## 1. Executive Summary

I reconstructed the current cleanup and refactor-preparation state from the required local reports, then verified the live router code before making changes.

This round added the two exact router contract protections that Phase 3D identified as missing:

- `query_emission_factors` table shaping in `UnifiedRouter._extract_table_data(...)`
- `calculate_micro_emission` table shaping in `UnifiedRouter._extract_table_data(...)`

What was intentionally left unchanged:

- no structural extraction from `core/router.py`
- no payload-format redesign
- no broader router test expansion beyond the two missing table branches
- no changes to router orchestration, synthesis, or API behavior

## 2. Context Reconstruction

### Local docs read

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
- `PHASE3D_ROUTER_SECOND_SEAM_DECISION_REPORT.md`
- `ROUTER_REFACTOR_PREP.md`
- `DEVELOPMENT.md`
- `RUNNING.md`

### What prior phases already established

- early phases improved baseline safety, repo hygiene, and testability
- Phase 2A and Phase 2B completed two safe helper extractions from `api/routes.py`
- Phase 2C added thin API route-level contract tests
- Phase 2D concluded that further `api/routes.py` extraction should pause
- Phase 3A added thin router payload/result contract tests
- Phase 3B approved only one tiny first seam in `core/router.py`
- Phase 3C extracted only the memory-compaction helper pair into `core/router_memory_utils.py`
- Phase 3D re-evaluated the second router seam and concluded that payload-helper extraction should pause until two table-shaping branches were protected

### Why this round was the correct next step

Phase 3D identified a specific blocker to re-evaluating the payload-helper seam:

- `query_emission_factors` table shaping was still unprotected
- `calculate_micro_emission` table shaping was still unprotected

Closing those exact gaps was the smallest useful move before any further router seam decision.

## 3. Verified Current Router Protection State

### What `tests/test_router_contracts.py` already covered before this round

Verified in the live test file:

- memory compaction behavior
- compatibility between `core.router_memory_utils` and `core.router` wrappers
- chart payload precedence and emission-factor chart formatting
- macro table preview shaping
- download extraction
- map extraction
- deterministic fallback formatting

### Where the two missing branches were located in live code

Verified in `core/router.py` inside `UnifiedRouter._extract_table_data(...)`:

- `query_emission_factors`
  - multi-pollutant branch under `if "pollutants" in data`
  - single-pollutant branch under `elif "speed_curve" in data or "curve" in data`
- `calculate_micro_emission`
  - branch under `if r["name"] == "calculate_micro_emission"` inside the shared calculation-tools section

### Why they were previously under-protected

- there was already one macro-table preview test, but no matching test for the other two table-producing tool branches
- Phase 3A and Phase 3D both treated `_extract_table_data(...)` as only partially protected because of these missing cases
- without these tests, a later payload-helper extraction would still risk drifting table columns, preview formatting, or summary/total fields for two important frontend-facing branches

## 4. Tests Added or Updated

### Files changed

- `tests/test_router_contracts.py`

### New tests added

#### `test_extract_table_data_formats_emission_factor_preview_for_frontend`

What it covers:

- the `query_emission_factors` multi-pollutant table branch

What it checks:

- top-level `type` stays `query_emission_factors`
- column names keep the current speed-plus-pollutant format
- preview rows preserve the current formatted string values and row shape
- `total_rows` and `total_columns` match the emitted preview metadata
- summary keeps the current `vehicle_type`, `model_year`, `season`, and `road_type` fields

Why this is thin but high-value:

- it protects the frontend-facing table envelope and field names without asserting unrelated prose or live model behavior
- it exercises the branch that was explicitly called out as missing in Phase 3D

#### `test_extract_table_data_formats_micro_results_preview_for_frontend`

What it covers:

- the `calculate_micro_emission` table branch

What it checks:

- top-level `type` stays `calculate_micro_emission`
- columns preserve the current `t`, `speed_kph`, optional dynamics fields, and pollutant ordering
- preview rows preserve the current string-formatting behavior for speed, acceleration, VSP, and emissions
- `total_rows` and `total_columns` match the emitted preview metadata
- `summary` and `total_emissions` remain aligned with the live `summary.total_emissions_g` contract

Why this is thin but high-value:

- it locks in the stable table shape that downstream API/session consumers rely on
- it avoids external services and tests the live helper logic directly

## 5. Verification

### Commands run

```bash
pytest tests/test_router_contracts.py
python main.py health
pytest
```

### What passed

- `pytest tests/test_router_contracts.py`: passed (`9 passed`)
- `python main.py health`: passed
- full `pytest`: passed (`65 passed`)

### Remaining warnings / limitations

- existing FastAPI `@app.on_event(...)` deprecation warnings remain
- existing `datetime.utcnow()` deprecation warnings from `api/logging_config.py` remain
- `python main.py health` still emits the pre-existing optional `FlagEmbedding` warning from `skills.knowledge.retriever`

These were already present and were intentionally left unchanged in this round.

## 6. What Was Intentionally NOT Changed

Deferred structural work:

- no second `core/router.py` extraction
- no movement of payload helpers into a new module
- no changes to `chat`
- no changes to `_process_response`
- no changes to synthesis/rendering helpers
- no changes to API/session consumers

Why these remain deferred:

- this round existed to satisfy the exact Phase 3D prerequisite, not to reopen seam extraction
- structural movement should only be reconsidered after the added tests are in place and verified

## 7. Follow-up Guidance

### What should happen in the next round

- re-evaluate the payload-helper area in `core/router.py` using the now-expanded `tests/test_router_contracts.py` coverage
- decide whether the coherent payload-extraction seam is now sufficiently protected for a conservative GO recommendation

### Whether the repo is now ready for payload-helper seam re-evaluation

- yes
- the two explicit table-branch blockers named in Phase 3D have now been addressed
- that does not automatically authorize extraction, but it does remove the specific protection gap that previously justified a NO-GO

### What still should not be done prematurely

- do not jump directly into `chat` or `_process_response` refactoring
- do not broaden the next round into a full router cleanup
- do not redesign payload formats just because the helper area may now be extractable

## Suggested Next Safe Actions

- [x] Add focused router contract coverage for `query_emission_factors` table shaping.
- [x] Add focused router contract coverage for `calculate_micro_emission` table shaping.
- [x] Re-run targeted router contracts and the full regression suite.
- [ ] Re-evaluate whether the full payload-helper seam in `core/router.py` is now ready for a conservative GO/NO-GO decision.
- [ ] Keep `chat`, `_process_response`, and synthesis/control-flow work out of scope until a later dedicated decision round.
