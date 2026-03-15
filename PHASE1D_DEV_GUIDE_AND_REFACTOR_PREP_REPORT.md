# Phase 1D Developer Guide And Refactor Prep Report

## 1. Executive Summary

This round added a small maintainer-facing navigation layer, cleaned the known low-value stdout noise from the smoke/evaluation path, and prepared a concrete future decomposition plan for the two oversized active modules.

What was clarified:

- the current maintainer source-of-truth docs and where to start reading
- the current canonical run, validation, and evaluation paths
- the high-level active vs transitional areas of the repository
- the most practical future extraction seams in `core/router.py` and `api/routes.py`

What was cleaned up:

- direct debug stdout in `skills/micro_emission/excel_handler.py` was replaced with debug-level logging

What was intentionally deferred:

- broad logging normalization in other modules
- any real decomposition of `core/router.py` or `api/routes.py`
- broad historical-doc cleanup or major structure changes

## 2. Developer Navigation Work

Files/docs inspected during this round:

- `README.md`
- `RUNNING.md`
- `evaluation/README.md`
- `docs/ARCHITECTURE.md`
- `docs/README.md`
- `REPOSITORY_ENGINEERING_AUDIT.md`
- `PHASE0_MINIMAL_PHASE1_EXECUTION_REPORT.md`
- `PHASE1B_CONSOLIDATION_REPORT.md`
- `PHASE1C_ENTRYPOINTS_AND_EVAL_REPORT.md`

New developer-facing source of truth created:

- `DEVELOPMENT.md`

Why this structure was chosen:

- a root-level developer navigation file is the lowest-friction place for future maintainers to start
- the repository already had multiple reports and historical guides, so the main problem was orientation, not missing prose
- the new file points readers to the already-established canonical run and evaluation docs instead of duplicating them

The new guide is intentionally concise and focuses on:

- which docs are live and should be trusted first
- which commands are canonical for daily development
- which directories are active vs transitional
- where not to start risky cleanup

## 3. Smoke/Evaluation Noise Cleanup

Noisy output found:

- direct `sys.stdout.write(...)` debug lines in `skills/micro_emission/excel_handler.py`

Where it came from:

- `ExcelHandler.read_trajectory_from_excel(...)` emitted column-name debug traces before and after column cleanup
- this leaked into `python evaluation/run_smoke_suite.py` output because file-grounding and end-to-end smoke samples exercise the micro Excel reader

What changed:

- replaced the raw stdout writes with `logger.debug(...)` calls

Why the change was low-risk:

- no business logic changed
- the same file-reading and column-cleanup behavior was preserved
- the debug information still exists for developers who enable debug logging
- default smoke/evaluation output is now cleaner and more reproducible

Observed result after verification:

- the previous `[DEBUG] 文件列名 ...` stdout lines no longer appear during `python evaluation/run_smoke_suite.py --output-dir evaluation/logs/_phase1d_smoke_check`

## 4. Refactor Preparation Work

Oversized modules analyzed:

- `core/router.py`
- `api/routes.py`

Future extraction seams identified:

For `core/router.py`:

- result rendering helpers
- frontend payload extraction helpers
- memory compaction helpers
- later, the file-context/cache preparation block inside `UnifiedRouter.chat`

For `api/routes.py`:

- response normalization helpers
- chart/table formatting helpers
- later, file/download/GIS support helpers
- only after those steps, possible route-group splits

Recommended future sequence:

1. strengthen helper/payload regression coverage
2. extract pure helpers from `api/routes.py`
3. extract pure helpers from `core/router.py`
4. extract the file-context/cache preparation block from `UnifiedRouter.chat`
5. only then consider route grouping into smaller modules

What was intentionally not refactored now:

- `UnifiedRouter.chat`
- `UnifiedRouter._process_response`
- FastAPI route registration and path structure
- streaming behavior in `/chat/stream`
- session/auth/database flow

## 5. Concrete Changes Made

### `skills/micro_emission/excel_handler.py`

- replaced direct stdout debug writes with debug-level logging
- safe because it preserves behavior and only changes how diagnostic output is emitted

### `tests/test_micro_excel_handler.py`

- added a focused regression test covering:
  - whitespace-stripped column handling
  - absence of accidental stdout noise
- safe because it only exercises existing behavior

### `DEVELOPMENT.md`

- added a concise maintainer navigation document at the repository root
- safe because it is documentation only and references already-verified canonical paths

### `ROUTER_REFACTOR_PREP.md`

- added a concrete future decomposition-prep document for `core/router.py` and `api/routes.py`
- safe because it is planning-only and explicitly defers risky work

### `README.md`

- updated the canonical docs section to include the new maintainer navigation and refactor-prep documents
- safe because it only improves discoverability

### `RUNNING.md`

- added a pointer to `DEVELOPMENT.md` for maintainers
- safe because it does not alter run instructions

### `evaluation/README.md`

- added pointers back to `DEVELOPMENT.md` and `RUNNING.md`
- safe because it keeps evaluation guidance connected to the broader developer workflow

## 6. Tests Added or Updated

Added:

- `tests/test_micro_excel_handler.py`

What was tested:

- the micro Excel reader still parses trimmed CSV column names correctly
- the read path no longer emits debug stdout

Why this was sufficient for this round:

- the only code-path behavior change was the debug-output normalization in the micro Excel handler
- broader regression risk was covered by rerunning the existing suite and the smoke evaluation wrapper

Verification run:

- `pytest`
- `python main.py health`
- `python evaluation/run_smoke_suite.py --output-dir evaluation/logs/_phase1d_smoke_check`

Results:

- `45 passed`
- health check succeeded
- smoke suite completed successfully and no longer showed the old micro Excel debug stdout lines

## 7. Documentation Added or Updated

Created:

- `DEVELOPMENT.md`
- `ROUTER_REFACTOR_PREP.md`

Updated:

- `README.md`
- `RUNNING.md`
- `evaluation/README.md`

Why this approach was chosen:

- root-level focused docs are easier to discover than another large report buried in `docs/`
- the repository already had canonical run/evaluation docs, so the best improvement was connecting them with a maintainer-oriented navigation layer and a concrete refactor-prep note

## 8. Remaining Risks / Follow-up Work

Still messy or incomplete:

- `core/router.py` and `api/routes.py` remain large and mix orchestration with formatting/helper logic
- some debug-style `logger.info(...)` lines still exist in large active modules, especially `core/router.py`
- `docs/README.md` and various historical docs remain outdated relative to the new root-level canonical docs
- smoke runs still surface meaningful warnings such as missing optional local embedding dependencies; these were left unchanged because they are not accidental debug stdout

What should happen later:

- add helper-contract tests around router payload extraction and route normalization utilities
- do a first-pass pure-helper extraction from `api/routes.py`
- then do a matching pure-helper extraction from `core/router.py`
- separately decide which warnings should remain visible vs be downgraded

## 9. Recommended Next Safe Step

The next safe cleanup focus is a helper-only extraction pass on `api/routes.py`, starting with pure response-normalization and chart/table formatting helpers while keeping all route signatures and payload schemas unchanged.

## Suggested Next Safe Actions

- [ ] Add focused tests for `normalize_download_file`, `attach_download_to_table_data`, and `clean_reply_text`
- [ ] Extract pure helper functions from `api/routes.py` without moving route handlers yet
- [ ] Add focused tests for router payload extraction helpers before touching `core/router.py`
- [ ] Keep `python evaluation/run_smoke_suite.py` as the minimum reproducibility guard for future cleanup rounds
