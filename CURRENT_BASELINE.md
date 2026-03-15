# Current Baseline

This file marks the current post-cleanup baseline. Use it as the stable reference point for experiments, evaluation, future paper-supporting work, and later open-source preparation.

## What This Baseline Represents

The repository has completed:

- safety/hygiene cleanup and initial regression-test setup
- conservative clarification of active runtime paths and transitional areas
- bounded helper extraction from `api/routes.py`
- bounded helper extraction from `core/router.py`
- API and router contract protection
- project-surface consolidation, examples, contributor guidance, and release-readiness sanity work

The result is a repo that is:

- stable enough to use as a working engineering baseline
- coherent enough to share with collaborators
- intentionally still evolving in some internal areas

## Canonical Docs For This Baseline

Use these first:

1. [README.md](README.md)
2. [ENGINEERING_STATUS.md](ENGINEERING_STATUS.md)
3. [RELEASE_READINESS.md](RELEASE_READINESS.md)
4. [RUNNING.md](RUNNING.md)
5. [evaluation/README.md](evaluation/README.md)
6. [examples/README.md](examples/README.md)
7. [CONTRIBUTING.md](CONTRIBUTING.md)
8. [DEVELOPMENT.md](DEVELOPMENT.md)

Use root-level `PHASE*.md` files only when you need the rationale behind a specific earlier cleanup decision.

## Canonical Commands

### Run the app

```bash
python run_api.py
```

### Validate the baseline

```bash
python main.py health
pytest
```

### Run the smallest meaningful evaluation

```bash
python evaluation/run_smoke_suite.py
```

## Intentionally Paused Areas

- deeper `core/router.py` extraction
- deeper `api/routes.py` extraction
- broad historical-doc pruning
- broader packaging/distribution work

These are paused intentionally so this baseline can remain a stable reference point.

## How To Use This Baseline Going Forward

- For experiments and evaluation:
  - start from the canonical commands and docs above
- For future maintenance:
  - prefer small compatibility-preserving changes
- For future structural cleanup:
  - reopen only with narrow, test-backed seams
- For future open-source preparation:
  - treat this baseline as the stable starting point, not the final public package

## Recommended Next Workstreams

- experiments and evaluation expansion
- paper-supporting analysis or benchmark work
- later open-source packaging polish only when external sharing becomes a real need
