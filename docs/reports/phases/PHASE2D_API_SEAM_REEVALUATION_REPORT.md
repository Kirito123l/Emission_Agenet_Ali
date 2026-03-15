# Phase 2D API Seam Re-evaluation Report

## 1. Executive Summary

Current assessment of `api/routes.py`:

- the two clean pure-helper seams have already been extracted
- the remaining code is now dominated by route-flow behavior, shared state, and compatibility-sensitive request/response handling
- the current route-level contract tests improve confidence, but they do not make the remaining seams low-risk in the same way the earlier helper extractions were

Recommendation:

- **NO-GO**

Recommended next focus:

- pause further structural extraction from `api/routes.py`
- shift attention to `core/router.py` refactor preparation, specifically by adding or planning focused protection around router result/payload formatting seams before any decomposition

## 2. Current `api/routes.py` State

What has already been extracted in previous rounds:

- response normalization helpers now live in `api/response_utils.py`
- chart/table helpers now live in `api/chart_utils.py`
- compatibility is preserved through module-scope imports in `api/routes.py`

What major responsibility clusters still remain in `api/routes.py`:

- request/session identity helper:
  - `get_user_id`
- chat route flow:
  - `/chat`
  - `/chat/stream`
- file preview/GIS/download/template routes
- session/history routes
- small utility routes:
  - `/health`
  - `/test`
- auth routes:
  - `/register`
  - `/login`
  - `/me`

What has become more route-flow-specific:

- `chat` and `chat/stream` combine request parsing, session lookup, file handling, router calls, response shaping, and persistence
- download and history paths combine request identity, storage lookup, compatibility backfill, and file-system behavior
- auth routes combine request validation, database calls, token handling, and response models

Current route-level protection relevant to this decision:

- `/api/health` and `/api/test`
- `/api/file/preview`
- `/api/sessions/new`
- `/api/sessions`
- `/api/sessions/{session_id}/history`
- extracted helper modules continue to have direct unit tests

This protection is useful, but it is still thinner around download, auth, GIS, and chat/stream behavior.

## 3. Candidate Seam Analysis

### Candidate 1: `get_user_id`

Description:

- a single helper function that resolves user identity from JWT, `X-User-ID`, or a generated UUID

Coupling level:

- medium
- depends on `Request`, request headers, and `auth_service.decode_token`

Expected value if extracted:

- low
- it would save little complexity and would not materially simplify the route module structure

Current test protection level:

- low to medium
- current route tests exercise the `X-User-ID` path indirectly through session routes
- JWT and fallback UUID behavior are not protected directly

Estimated risk:

- low to medium technically, but poor payoff
- not a strong enough value target for its own round

### Candidate 2: Session/history route support logic

Description:

- session listing/creation/deletion/title update plus history normalization/backfill logic

Coupling level:

- medium to high
- depends on `SessionRegistry`, request identity, persisted history shape, download metadata compatibility, and `config.outputs_dir`

Expected value if extracted:

- medium
- this area is conceptually cohesive, but most of the complexity is route-flow-specific rather than pure helper logic

Current test protection level:

- medium
- create/list/history are covered
- delete/title and broader download interactions are not

Estimated risk:

- medium
- extracting the history backfill code alone would be a narrow move, but the maintainability payoff is limited compared with the behavioral coupling involved

### Candidate 3: File preview/GIS/download/template route group

Description:

- mixed set of file preview, GIS asset serving, download handling, and template generation routes

Coupling level:

- medium to high
- depends on `TEMP_DIR`, cache globals, filesystem state, config, and route-specific response types

Expected value if extracted:

- medium at best
- the group is not especially uniform, and only `preview_file` is currently guarded by a route contract test

Current test protection level:

- low to medium
- preview is covered
- GIS/download/template paths are not

Estimated risk:

- medium to high
- this would be the first route-group extraction rather than another pure-helper move

### Candidate 4: Auth route group

Description:

- `/register`, `/login`, and `/me`

Coupling level:

- high
- depends on database state, password hashing, token encoding/decoding, and auth models

Expected value if extracted:

- medium
- the group is cohesive, but not currently cheap to split safely

Current test protection level:

- low
- no direct route-level contract tests currently protect these endpoints

Estimated risk:

- high
- not a good next extraction target without additional auth-focused tests first

### Candidate 5: Health/test utility routes

Description:

- `/health` and `/test`

Coupling level:

- low

Expected value if extracted:

- very low
- too small to justify a structural round

Current test protection level:

- high relative to size

Estimated risk:

- low, but not worthwhile

## 4. Decision Analysis

Why continuing `api/routes.py` extraction is not justified right now:

- the best pure-helper seams are already gone
- the remaining seams are either too small to matter (`get_user_id`, health/test) or too tied to live route flow (session/history, downloads, auth, chat/stream)
- the current route contracts improve confidence but still only partially cover the more entangled areas
- extracting one of the remaining route groups now would be a different class of refactor than the safe helper-only moves in Phase 2A and Phase 2B

Comparison with shifting attention to `core/router.py` preparation:

- `api/routes.py` next step:
  - risk: medium to high
  - payoff: low to medium
  - readiness: weaker, because the remaining seams are not clean helper blocks
  - test protection: partial
- `core/router.py` preparation next step:
  - risk: lower if limited to prep/guardrail work rather than extraction
  - payoff: higher, because `core/router.py` still has larger pure-helper seams identified in `ROUTER_REFACTOR_PREP.md`
  - readiness: reasonable, because the prep document already names candidate helper extractions and the code remains the larger structural debt center
  - test protection: still needs targeted strengthening, which is exactly why preparation is the better immediate move

Conclusion:

- further `api/routes.py` extraction now would be driven more by continuity than by quality of seam
- the better engineering choice is to stop here and shift the next round toward `core/router.py` preparation

## 5. Recommendation

**NO-GO**

Exact recommended next action:

- do not schedule a Phase 2D structural extraction from `api/routes.py`
- instead, begin a `core/router.py` preparation round focused on identifying and protecting the first safe router helper seam, likely around result/payload formatting or memory-compaction helpers, before any actual router split

What should not be done next:

- do not extract `get_user_id` merely to keep API refactoring momentum going
- do not move session/history or file/download route groups yet
- do not split auth routes yet
- do not begin moving chat or streaming routes

## 6. Any Tiny Clarifications Made

No tiny code or documentation clarifications were made in this round.

## 7. Follow-up Guidance

What should happen in the next round:

- focus on `core/router.py` preparation rather than API extraction
- identify the first router helper seam with the best combination of purity, value, and testability
- add or improve targeted tests around router output-shaping behavior before attempting any router extraction

Useful prerequisites before the next structural move:

- explicit tests for router payload/result formatting behavior
- confirmation of which router helpers are already indirectly protected by the smoke suite and which are not
- a clear definition of the first router seam that should remain inside `core/router.py` versus the first one that could move out safely

## Suggested Next Safe Actions

- [ ] Treat `api/routes.py` helper extraction as complete for now
- [ ] Start a `core/router.py` preparation pass centered on test/guardrail improvement, not extraction
- [ ] Add focused protection for router chart/table/download/map payload shaping before any router split
- [ ] Revisit `api/routes.py` only if new tests reveal a clearly bounded remaining seam with stronger payoff than current candidates
