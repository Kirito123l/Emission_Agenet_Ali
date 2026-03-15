# Development Guide

This file is the maintainer-facing navigation layer for the current repository state. Use it as the first stop before changing code.

## Start Here

Read these in order:

1. [README.md](README.md) for the external-facing overview and quickstart
2. [ENGINEERING_STATUS.md](ENGINEERING_STATUS.md) for the current engineering state, completed phases, and deferred areas
3. [CURRENT_BASELINE.md](CURRENT_BASELINE.md) for the current frozen milestone summary and recommended next workstreams
4. [RELEASE_READINESS.md](RELEASE_READINESS.md) for the current shareability/open-source sanity checklist
5. [RUNNING.md](RUNNING.md) for the current canonical run and smoke paths
6. [evaluation/README.md](evaluation/README.md) for the current evaluation and reproducibility entry points
7. [examples/README.md](examples/README.md) for the smallest realistic workflows
8. [CONTRIBUTING.md](CONTRIBUTING.md) for practical contribution guardrails
9. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the current high-level architecture
10. Relevant reports under `docs/reports/phases/` or `docs/reports/gis/` only when you need historical cleanup rationale for a specific area

Trust the live codebase first, then use the phase reports as supporting context.

## Doc Roles

- `README.md`, `ENGINEERING_STATUS.md`, `CURRENT_BASELINE.md`, `RELEASE_READINESS.md`, `RUNNING.md`, `evaluation/README.md`, `examples/README.md`, and `CONTRIBUTING.md`
  - current source-of-truth docs for daily work
- `docs/reports/phases/` and `docs/reports/gis/`
  - historical cleanup and optimization decision records
- `docs/reports/` and `docs/archive/`
  - older background material; do not treat them as the default starting point

## Canonical Daily Paths

### Main run paths

- `python run_api.py`
  - Canonical integrated app path
- `python main.py chat`
  - Secondary CLI/debugging path

### Main validation paths

- `python main.py health`
  - Lowest-friction runtime check
- `pytest`
  - Current regression baseline
- `python scripts/utils/test_rag_integration.py`
  - Specialized knowledge-path smoke check

### Main evaluation path

- `python evaluation/run_smoke_suite.py`
  - Canonical minimal reproducibility run

## Where To Look

### Active application layers

- `core/`
  - Router, context assembly, tool execution, memory
- `tools/`
  - Active tool surface used by the router/executor
- `services/`
  - LLM and parameter-standardization services
- `api/`
  - FastAPI app, routes, session/auth integration
- `evaluation/`
  - Current benchmark and smoke-evaluation harness

### Active but transitional

- `skills/`
  - Transitional support layer
  - Some `excel_handler.py` modules are still active through `tools/`
  - Some `skill.py` modules remain compatibility or legacy paths
- `llm/client.py`
  - Canonical synchronous compatibility path for standardizers and legacy sync call sites

### Historical or secondary

- `docs/guides/QUICKSTART.md`
- `docs/guides/WEB_STARTUP_GUIDE.md`
- `docs/archive/`
- `scripts/deprecated/`

These remain on disk for context, not as the source of truth for current development.

## Before Making Changes

- Verify on-disk behavior before trusting older reports or comments.
- Prefer small compatibility-preserving edits over broad cleanup.
- Keep smoke and evaluation output clean; use logging instead of raw `print(...)` or `sys.stdout.write(...)` for debug traces.
- If you need to touch `core/router.py` or `api/routes.py`, read [ROUTER_REFACTOR_PREP.md](ROUTER_REFACTOR_PREP.md) first and avoid ad hoc decomposition.
- The extracted router helper seams now live in `core/router_memory_utils.py`, `core/router_payload_utils.py`, `core/router_render_utils.py`, and `core/router_synthesis_utils.py`; keep later router cleanup scoped to one contract-backed seam at a time.

## Safe First Checks

If you changed runtime behavior:

```bash
python main.py health
pytest
```

If you changed `calculators/macro_emission.py` or GIS macro-calculation performance assumptions:

```bash
pytest tests/test_calculators.py
python scripts/utils/benchmark_macro_lookup.py
```

The macro calculator now keeps a process-local season cache keyed by `winter/spring/summer`.
Use `MacroEmissionCalculator.clear_matrix_cache()` in tests or local benchmarks when you need a cold-load measurement or when you change the bundled CSV files in-process.

If you changed evaluation-adjacent behavior:

```bash
python evaluation/run_smoke_suite.py
```

If you changed API routes, session/history handling, or download metadata behavior:

```bash
pytest tests/test_api_route_contracts.py
```

If you changed `core/router.py` payload shaping, synthesis behavior, fallback formatting, or memory tool-call compaction:

```bash
pytest tests/test_router_contracts.py
```

## Areas To Avoid Starting In

- `core/router.py`
  - Large orchestration module with mixed routing, synthesis, and frontend-payload shaping
- `api/routes.py`
  - Large route surface with helper logic, download/session flows, and auth endpoints

Do not start cleanup by splitting these files unless you have a focused extraction plan and regression coverage in place.
