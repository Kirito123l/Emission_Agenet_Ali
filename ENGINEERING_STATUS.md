# Engineering Status

This file is the shortest current-state summary for the repository. Use it before reading older phase reports.

## Current Position

Emission Agent is currently a research/engineering prototype with:

- a working FastAPI + web UI surface
- a supported CLI path for debugging
- a usable engineering evaluation harness
- a growing regression baseline around config, calculators, API routes, and router contracts

The repository is now in a consolidation stage:

- active development is still expected
- future open-source release is plausible with more surface polish
- deeper `core/router.py` extraction is intentionally paused for now
- the evaluation harness is usable, but it is still an engineering benchmark package rather than a finalized paper artifact

## Completed Cleanup Stages

### Phase 0 / Minimal Phase 1

- security and secret-handling basics tightened
- missing `LICENSE` added
- initial `pytest` baseline created

### Phase 1B to 1D

- canonical LLM client boundaries clarified
- `skills/` vs `tools/` usage clarified conservatively
- canonical run paths and evaluation paths documented
- maintainer navigation and refactor-prep docs added

### Phase 2A to 2D

- two safe helper seams extracted from `api/routes.py`
- route-level contract tests added
- further `api/routes.py` extraction intentionally paused

### Phase 3A to 3J

- router payload/result contract protection added
- safe helper seams extracted from `core/router.py` into:
  - `core/router_memory_utils.py`
  - `core/router_payload_utils.py`
  - `core/router_render_utils.py`
  - `core/router_synthesis_utils.py`
- deeper synthesis extraction paused after adding mocked async boundary tests

## Canonical Docs

Read these first:

1. [README.md](README.md)
   External-facing overview, quickstart, and docs map
2. [CURRENT_BASELINE.md](CURRENT_BASELINE.md)
   Frozen milestone summary and recommended next workstreams
3. [RELEASE_READINESS.md](RELEASE_READINESS.md)
   Current shareability/open-source sanity checklist
4. [RUNNING.md](RUNNING.md)
   Canonical run paths and minimum validation commands
5. [evaluation/README.md](evaluation/README.md)
   Minimal evaluation and reproducibility entry points
6. [examples/README.md](examples/README.md)
   Minimal realistic workflows for first-time usage
7. [CONTRIBUTING.md](CONTRIBUTING.md)
   Practical contributor and maintainer guidance
8. [DEVELOPMENT.md](DEVELOPMENT.md)
   Maintainer navigation, active/transitional areas, and safe checks

Supporting technical background:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [ROUTER_REFACTOR_PREP.md](ROUTER_REFACTOR_PREP.md)

## Canonical Commands

### Try the app

```bash
pip install -r requirements.txt
cp .env.example .env
python run_api.py
```

Expected result:

- web UI at `http://localhost:8000`
- OpenAPI docs at `http://localhost:8000/docs`

### Validate the app locally

```bash
python main.py health
pytest
```

### Run the smallest meaningful evaluation

```bash
python evaluation/run_smoke_suite.py
```

Expected artifact:

- `evaluation/logs/<run_name>/smoke_summary.json`

## Active, Transitional, And Deferred Areas

### Active runtime surface

- `core/`
- `tools/`
- `services/`
- `api/`
- `web/`
- `evaluation/`

### Active but transitional

- `skills/`
  - some Excel/data handlers are still used through `tools/`
- `llm/client.py`
  - compatibility-oriented synchronous LLM path still used by standardizers and some legacy sync call sites

### Deferred for now

- deeper `core/router.py` extraction beyond the current helper seams
- further `api/routes.py` decomposition beyond the current helper modules
- broad historical report pruning or archive reorganization
- evaluation methodology redesign or paper-package cleanup

## How To Read The Report Trail

- Root-level `PHASE*.md` files are historical engineering records.
- `docs/reports/` and `docs/archive/` are background context, not the current source of truth.
- Use historical reports only when you need the rationale for a specific cleanup decision.
- For current daily work or external sharing prep, prefer the canonical docs above plus the live codebase.

## Recommended Next Safe Focus

The most useful next project-level move is a small release-surface polish pass:

- expand examples only where the workflows are already stable and low-maintenance
- add a small release-artifact or packaging checklist only if external distribution work actually starts
- keep deeper router decomposition paused unless there is a narrowly protected seam again
