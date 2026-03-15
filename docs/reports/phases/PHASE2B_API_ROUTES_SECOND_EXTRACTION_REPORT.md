# Phase 2B API Routes Second Extraction Report

## 1. Executive Summary

This round completed one additional conservative extraction from `api/routes.py`: the chart/table helper cluster was moved into `api/chart_utils.py`.

Why this extraction target was chosen:

- after Phase 2A, it remained the clearest pure-helper block in `api/routes.py`
- it depends only on local data structures plus module-local logging
- it does not depend on FastAPI request objects, session state, route decorators, database access, or router orchestration
- it fit the same low-risk extraction pattern already validated by `api/response_utils.py`

What was intentionally left untouched:

- all route handlers and route decorators
- `get_user_id`
- file/GIS/download flows
- session/history flows
- auth flows
- route registration in `api.main`

## 2. `api/routes.py` Re-inspection Summary

What remained in `api/routes.py` after Phase 2A:

- `get_user_id`
- chart/table helper functions:
  - `build_emission_chart_data`
  - `extract_key_points`
  - `_pick_key_points`
- all chat/file/download/session/history/health/auth endpoints

Whether the chart/table helper block was confirmed as the next safest seam:

- yes
- the block was still well-bounded and pure enough for extraction
- its only live dependency inside the helper block was logging, which could move cleanly into the new module

Alternatives considered:

- `get_user_id`
  - smaller, but still tied to `Request` and `auth_service`
- file/GIS/download helper extraction
  - more coupled to shared globals, filesystem behavior, and compatibility-sensitive route flows
- route-subset extraction
  - riskier because it moves decorators and router wiring instead of pure helper logic

## 3. Concrete Extraction Performed

Files created/changed:

- `api/chart_utils.py`
- `api/routes.py`
- `tests/test_api_chart_utils.py`

What moved out of `api/routes.py`:

- `build_emission_chart_data`
- `extract_key_points`
- `_pick_key_points`

What remained in place:

- `get_user_id`
- all route handlers and decorators
- all route-path definitions
- all file/session/auth/download/history logic
- previously extracted response helpers still imported from `api/response_utils.py`

How compatibility was preserved:

- `api/routes.py` imports the extracted chart helpers at module scope
- existing internal calls still use the same names
- `api.routes.build_emission_chart_data`, `api.routes.extract_key_points`, and `api.routes._pick_key_points` remain available
- `api.main` continues to import and register the same `router`

## 4. Regression Protection / Verification

Tests added:

- `tests/test_api_chart_utils.py`

What was tested:

- single-pollutant chart normalization behavior
- multi-pollutant `speed_curve` to `curve` conversion behavior
- direct and legacy key-point extraction behavior
- compatibility re-export through `api.routes`

Commands run:

- `pytest tests/test_api_chart_utils.py tests/test_api_response_utils.py`
- `python main.py health`
- `pytest`

What passed:

- targeted API helper tests passed
- health check passed
- full regression suite passed with `53 passed`

Current verification limitations:

- this round still did not add live HTTP endpoint tests with `TestClient`
- route behavior was validated through helper tests, app import/registration smoke already present from Phase 2A, and the broader regression suite rather than endpoint contract tests

## 5. What Was Intentionally NOT Refactored

Deferred areas still remaining in `api/routes.py`:

- `get_user_id`
  - tied to `Request` headers plus `auth_service`
- chat endpoints
  - coupled to session state and router execution
- file preview/GIS/download/template endpoints
  - rely on shared globals, filesystem behavior, and response compatibility
- session/history endpoints
  - contain compatibility-sensitive message normalization and download reconstruction
- auth endpoints
  - tied to database and token flows

Why they were deferred:

- this round was intentionally limited to one pure helper extraction only
- the remaining areas are less helper-like and more route-flow-specific, so the next safe move should be more test-driven

## 6. Risks / Follow-up Work

Remaining route-related structural debt:

- `api/routes.py` is smaller than before but still mixes multiple route-flow responsibilities
- the remaining code is now more behavior-sensitive than the already-extracted helper clusters
- route-level logging and compatibility logic are still interleaved with handler bodies

What this second extraction teaches us:

- the phased helper-extraction pattern is repeatable when the target is pure and well-bounded
- module-scope re-imports in `api/routes.py` are enough to preserve compatibility for these helper-only moves
- future extractions will need stronger route-level tests because the easiest pure-helper seams are mostly gone

## 7. Recommended Next Safe Step

The recommended next safe step is to add thin route-level smoke/contract tests around session/history/download behavior before attempting any further structural extraction from `api/routes.py`.

## Suggested Next Safe Actions

- [ ] Add small route-contract tests for `/api/sessions`, `/api/sessions/{session_id}/history`, and download metadata behavior
- [ ] Keep `api/routes.py` as the router-registration home for now
- [ ] Defer any route-subset split until those route-level guards exist
- [ ] Reassess whether `get_user_id` is worth extracting only after the new route-contract tests are in place
