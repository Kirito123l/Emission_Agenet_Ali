# Contributing

This repository is still in an active cleanup/consolidation stage. Contributions are welcome, but the safest changes are small, explicit, and easy to verify.

## Start Here

Read these first:

1. [README.md](README.md)
2. [ENGINEERING_STATUS.md](ENGINEERING_STATUS.md)
3. [CURRENT_BASELINE.md](CURRENT_BASELINE.md)
4. [RELEASE_READINESS.md](RELEASE_READINESS.md)
5. [RUNNING.md](RUNNING.md)
6. [evaluation/README.md](evaluation/README.md) if your change touches evaluation or reproducibility
7. [DEVELOPMENT.md](DEVELOPMENT.md) for maintainer-oriented navigation

Trust the live codebase first. Use the root-level `PHASE*.md` reports when you need the rationale for a specific earlier cleanup decision.

## Contribution Style That Fits This Repo

- Prefer small, compatibility-preserving changes over broad rewrites.
- Verify on-disk behavior before trusting older comments or reports.
- Keep edits scoped to one logical change.
- Do not casually start refactors in `core/router.py` or `api/routes.py`.
- Treat `skills/` as transitional unless the live code clearly shows a path is still active.
- Keep examples, docs, and run commands aligned with what actually works in the repository today.

## Safe Local Workflow

### Before changing code

```bash
python main.py health
pytest
```

### After changing runtime behavior

```bash
python main.py health
pytest
```

### After changing evaluation-related behavior

```bash
python evaluation/run_smoke_suite.py
```

### After changing API behavior

```bash
pytest tests/test_api_route_contracts.py
```

### After changing router payload/synthesis/fallback behavior

```bash
pytest tests/test_router_contracts.py
```

## Sensitive Areas

Use extra care in:

- `core/router.py`
  - large orchestration module with deferred deeper extraction work
- `api/routes.py`
  - large route surface with helper extractions already completed and further decomposition intentionally paused
- `skills/`
  - some parts are still active through compatibility paths, others are legacy
- root-level historical reports
  - keep them as decision records unless a cleanup round explicitly targets doc archival

If you need to touch `core/router.py` or `api/routes.py`, read [ROUTER_REFACTOR_PREP.md](ROUTER_REFACTOR_PREP.md) first.

## Docs And Examples

Use these as the current source-of-truth set:

- [README.md](README.md)
- [ENGINEERING_STATUS.md](ENGINEERING_STATUS.md)
- [CURRENT_BASELINE.md](CURRENT_BASELINE.md)
- [RELEASE_READINESS.md](RELEASE_READINESS.md)
- [RUNNING.md](RUNNING.md)
- [evaluation/README.md](evaluation/README.md)
- [examples/README.md](examples/README.md)
- [DEVELOPMENT.md](DEVELOPMENT.md)

Historical context:

- root-level `PHASE*.md`
- `docs/reports/`
- `docs/archive/`

## What Good Contributions Look Like Right Now

- clarifying or correcting current docs
- improving examples or reproducibility guidance
- small test-backed bug fixes
- focused contract protection around behavior-sensitive surfaces
- conservative compatibility-preserving cleanup

## What Should Usually Wait

- broad architecture redesign
- deep refactors across multiple subsystems
- large reorganizations of historical docs
- deeper `core/router.py` extraction without a clearly protected seam
