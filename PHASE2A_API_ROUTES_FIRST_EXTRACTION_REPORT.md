# Phase 2A API Routes First Extraction Report

## 1. Executive Summary

This round completed one conservative extraction from `api/routes.py`: the response-normalization helper block was moved into a new module, `api/response_utils.py`.

Why this target was chosen:

- it was the smallest clearly bounded helper cluster in `api/routes.py`
- it is pure or near-pure logic with no route-registration behavior
- it is reused across multiple endpoints, so extracting it reduces `api/routes.py` size without touching request orchestration
- it is easy to protect with focused tests

What was intentionally left untouched:

- all route handlers
- route registration and `router = APIRouter()`
- request/session/user resolution helpers
- chart/table formatting helpers
- file/GIS/download endpoints
- session/history endpoints
- auth endpoints

## 2. `api/routes.py` Inspection Summary

Current major responsibility clusters identified in the live module:

- request/session helper logic
  - `get_user_id`
- response-normalization helpers
  - `friendly_error_message`
  - `clean_reply_text`
  - `normalize_download_file`
  - `attach_download_to_table_data`
- chart/table formatting helpers
  - `build_emission_chart_data`
  - `extract_key_points`
  - `_pick_key_points`
- chat endpoints
  - `/chat`
  - `/chat/stream`
- file/GIS/download/template endpoints
- session/history endpoints
- health/test endpoints
- auth endpoints

Candidate extraction seams considered:

1. response-normalization helpers
2. chart/table formatting helpers
3. file/download/GIS helper area
4. a route subset such as session endpoints

Why the chosen seam was the safest first move:

- the response-normalization helpers are the most self-contained block
- they do not depend on `Request`, `APIRouter`, `SessionRegistry`, `db`, or streaming behavior
- they already have stable call sites in multiple endpoints, so compatibility can be preserved by importing them back into `api.routes`
- route-subset extraction would require moving decorators or router wiring, which is a larger first step than necessary

## 3. Concrete Extraction Performed

Files created/changed:

- `api/response_utils.py`
- `api/routes.py`
- `tests/test_api_response_utils.py`

What moved out of `api/routes.py`:

- `friendly_error_message`
- `clean_reply_text`
- `normalize_download_file`
- `attach_download_to_table_data`

What remained in place:

- `get_user_id`
- all chart/table formatting helpers
- all route handlers and decorators
- all route-path definitions
- all session/auth/database interactions

How compatibility was preserved:

- `api/routes.py` now imports the extracted helpers at module scope
- existing internal calls in `api/routes.py` still use the same names
- `api.routes.clean_reply_text`, `api.routes.friendly_error_message`, `api.routes.normalize_download_file`, and `api.routes.attach_download_to_table_data` remain available
- `api.main` continues to import and register the same `router`

## 4. Regression Protection / Verification

Tests added:

- `tests/test_api_response_utils.py`

What was tested:

- `clean_reply_text` cleanup behavior
- `friendly_error_message` connection-error mapping
- `normalize_download_file` and `attach_download_to_table_data` output shape
- compatibility re-export through `api.routes`
- app import/route-registration smoke via `/api/health` path presence

Commands run:

- `pytest tests/test_api_response_utils.py`
- `python main.py health`
- `pytest`

What passed:

- targeted extraction tests passed
- health check passed
- full regression suite passed with `49 passed`

Current verification limitations:

- this round did not add live HTTP endpoint tests with `TestClient`
- route behavior was validated through helper tests, app import/registration smoke, and the existing regression suite rather than full request/response contract tests

## 5. What Was Intentionally NOT Refactored

Deferred areas inside `api/routes.py`:

- `get_user_id`
  - still tied to auth-service behavior and request headers
- `build_emission_chart_data`, `extract_key_points`, `_pick_key_points`
  - also pure enough to extract later, but left for the next pass to keep this round to one seam only
- chat endpoints
  - coupled to session state and router orchestration
- file preview, GIS, download, and template endpoints
  - rely on shared globals and file-system behavior
- session/history endpoints
  - contain compatibility-sensitive history/download normalization
- auth endpoints
  - tied to database and token flows

These were deferred because this round was intentionally limited to a single small extraction target.

## 6. Risks / Follow-up Work

Remaining route-related structural debt:

- `api/routes.py` still contains multiple unrelated responsibility clusters
- chart/table formatting helpers remain mixed with route handlers
- file/download/session/history behavior is still packed into one module
- route-level logging remains uneven and should stay separate from structural extraction work

What should be extracted next if this pattern is accepted:

- the chart/table formatting helper block:
  - `build_emission_chart_data`
  - `extract_key_points`
  - `_pick_key_points`

That would follow the same low-risk pattern: pure helper extraction first, router wiring untouched.

## 7. Recommended Next Safe Step

The recommended next safe step is a second helper-only extraction from `api/routes.py`, limited to the chart/table formatting helpers, with compatibility preserved the same way as this round.

## Suggested Next Safe Actions

- [ ] Add one or two focused tests for the chart/table formatting helpers before moving them
- [ ] Extract only `build_emission_chart_data`, `extract_key_points`, and `_pick_key_points` next
- [ ] Keep route decorators and route registration in `api/routes.py` for now
- [ ] Defer any session-route or auth-route split until helper extractions have proven stable
