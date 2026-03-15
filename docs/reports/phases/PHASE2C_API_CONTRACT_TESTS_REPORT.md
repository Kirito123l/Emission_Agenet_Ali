# Phase 2C API Contract Tests Report

## 1. Executive Summary

This round added a thin route-level contract layer for the FastAPI surface.

What was added:

- status/test route checks for `/api/health` and `/api/test`
- a file-preview contract check for `/api/file/preview`
- a session/history contract check covering:
  - `/api/sessions/new`
  - `/api/sessions`
  - `/api/sessions/{session_id}/history`
  - legacy download metadata backfill in history responses

Why these routes were chosen:

- they cover multiple route categories without requiring live LLM/network calls
- they are stable and important to future `api/routes.py` refactoring
- they exercise compatibility-sensitive behavior, especially around session/history normalization

What was intentionally left uncovered:

- chat endpoints
- streaming chat
- auth/database-backed endpoints
- GIS and download-file serving endpoints

## 2. API Testability Inspection Summary

App/bootstrap/test files inspected:

- `api/main.py`
- `api/routes.py`
- `api/session.py`
- `api/database.py`
- `api/models.py`
- `tests/conftest.py`
- `RUNNING.md`
- `PHASE2B_API_ROUTES_SECOND_EXTRACTION_REPORT.md`

How the API app was instantiated for tests:

- tests use the real `api.main.app`
- requests are sent through `httpx.AsyncClient` with `ASGITransport`
- this avoids the hanging behavior observed with `TestClient`/lifespan in the current app stack while still exercising FastAPI routing and middleware

Test isolation used:

- `db.init_db` was patched to a no-op async function to avoid DB startup IO
- `SessionRegistry.get(...)` was patched to use a temporary per-test session storage directory
- no live LLM/router chat calls were invoked

Route categories considered:

- status/test routes
- file-preview route
- session/history routes
- download routes
- GIS routes
- auth routes
- chat/stream routes

Constraints affecting route selection:

- avoid unstable external model/network dependencies
- avoid broad fixture complexity
- avoid routes that require real database/auth state unless cheaply mockable
- avoid brittle assertions on generated content

## 3. Tests Added

Test files created/changed:

- `tests/test_api_route_contracts.py`
- `DEVELOPMENT.md` (small note on how to run the new contract file)

Routes/endpoints now protected:

- `GET /api/health`
- `GET /api/test`
- `POST /api/file/preview`
- `POST /api/sessions/new`
- `GET /api/sessions`
- `GET /api/sessions/{session_id}/history`

What each test checks:

### Status/test route contract

- route responds with HTTP 200
- response is JSON
- top-level `status` and `timestamp` fields exist

Why this is high-value:

- protects the simplest API availability surface
- catches broken registration/import issues early

### File preview contract

- CSV upload is accepted
- route returns HTTP 200
- response shape includes filename, detected type, columns, preview rows, and warnings
- a minimal trajectory-like CSV is recognized as `trajectory`

Why this is high-value:

- covers multipart/form-data handling plus one important file-analysis surface
- avoids chat/router dependencies

### Session/history contract

- creating a session succeeds
- listing sessions exposes the created session
- history endpoint returns the expected envelope
- legacy assistant history with `table_data.download` is backfilled into `download_file`, `file_id`, and `message_id`

Why this is high-value:

- this is one of the most compatibility-sensitive route flows remaining in `api/routes.py`
- it protects behavior likely to matter in future route extraction work

## 4. Verification

Commands run:

- `pytest tests/test_api_route_contracts.py`
- `python main.py health`
- `pytest`

What passed:

- new route-contract tests passed
- runtime health check passed
- full regression suite passed with `56 passed`

Remaining warnings/limitations:

- existing FastAPI `on_event` deprecation warnings remain
- the new contract tests also surface existing `datetime.utcnow()` deprecation warnings from `api/logging_config.py`
- these warnings were not changed in this round

## 5. What Was Intentionally NOT Tested

Deferred route areas:

- `POST /api/chat`
  - depends on session chat flow and router/LLM behavior
- `POST /api/chat/stream`
  - streaming semantics are more complex and more brittle to test cheaply
- auth endpoints (`/api/register`, `/api/login`, `/api/me`)
  - require more deliberate database-state setup for useful contract coverage
- GIS endpoints
  - rely on optional local asset availability and caching behavior
- file-download endpoints
  - require more fixture setup around real files and persisted history/download state

Why they were deferred:

- they are either more setup-heavy, more externally coupled, or more brittle than the routes chosen for this thin contract layer

## 6. Risks / Follow-up Work

What remains unprotected:

- chat and streaming route contracts
- auth request/response contract behavior
- actual download-file serving behavior
- GIS asset fallback behavior

What additional coverage would be useful before deeper refactoring:

- one small auth-header test around `get_user_id` behavior
- one focused download-route test using a temporary output file
- one light streaming-route smoke test that only checks event framing, not generated content

## 7. Recommended Next Safe Step

With this thin route-level contract layer in place, the next safe move is to re-evaluate the smallest remaining `api/routes.py` seam, starting with request/session helper behavior such as `get_user_id`, and only proceed if the new route contracts stay green.

## Suggested Next Safe Actions

- [ ] Add one focused contract test for `get_user_id` header behavior before extracting it
- [ ] Add one temporary-file contract test for the download route if that behavior will be refactored soon
- [ ] Keep the new route-contract file in the default pre-refactor verification set
- [ ] Continue avoiding chat/stream structural work until a similarly thin contract layer exists there
