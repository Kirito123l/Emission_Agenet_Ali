# Running Emission Agent

This file is the current source of truth for supported local run paths.

For the broader repo status and docs map, read [ENGINEERING_STATUS.md](ENGINEERING_STATUS.md) first. For current shareability/open-source sanity, read [RELEASE_READINESS.md](RELEASE_READINESS.md). For maintainer-oriented navigation, read [DEVELOPMENT.md](DEVELOPMENT.md).

## Choose Your Goal

| Goal | Command | Expected result |
|---|---|---|
| Try the integrated app | `python run_api.py` | Web UI at `http://localhost:8000` and OpenAPI docs at `http://localhost:8000/docs` |
| Validate the local runtime | `python main.py health` then `pytest` | Basic runtime sanity plus the current regression baseline |
| Run a benchmark-style smoke pass | `python evaluation/run_smoke_suite.py` | Fresh logs under `evaluation/logs/` with `smoke_summary.json` |

If you only want to prove the app starts, stop after the validation path above. If you want benchmark/reproducibility signals, continue with [evaluation/README.md](evaluation/README.md).

## Canonical Entry Points

### Primary

`python run_api.py`

- Starts the FastAPI server from `api.main`
- Serves the web UI from `web/`
- Exposes API docs at `http://localhost:8000/docs`
- This is the main supported local development and demo path

### Secondary

`python main.py chat`

- Starts the interactive CLI chat loop
- Useful when debugging the router/tool pipeline without the browser
- Secondary because the main product surface today is the API + web UI

## Active but Specialized Paths

### Local validation / introspection

- `python main.py health`
  - Lowest-friction runtime validation
  - Checks that tools register successfully
- `python main.py tools-list`
  - Lists registered tools for quick inspection

### Specialized smoke/integration scripts

- `python scripts/utils/test_rag_integration.py`
  - Knowledge-tool import and knowledge-index smoke check
  - Does not exercise the full chat runtime
- `python scripts/utils/test_new_architecture.py`
  - Full architecture integration script
  - May exercise live LLM-backed flows
- `python scripts/utils/test_api_integration.py`
  - `api.session.Session` integration script
  - May exercise live LLM-backed flows
- `python scripts/query_emission_factors_cli.py`
  - One-tool CLI example using the active executor/standardization path
  - Not a general application launcher

### Underlying server path

- `uvicorn api.main:app --host 0.0.0.0 --port 8000`
  - Works because `api.main` is a real FastAPI app entrypoint
  - Prefer `python run_api.py` unless you need custom `uvicorn` flags

### Windows convenience wrappers

- `scripts/start_server.ps1`
- `scripts/restart_server.ps1`

These are convenience wrappers around `python run_api.py`, not separate server implementations.

## Transitional / Legacy / Historical Paths

- `scripts/deprecated/`
  - Historical helpers and old diagnostics; not part of the supported day-to-day workflow
- `scripts/migrate_from_mcp.py`
- `scripts/migrate_knowledge.py`
  - One-off migration helpers from older sibling projects
- `docs/guides/QUICKSTART.md`
- `docs/guides/WEB_STARTUP_GUIDE.md`
  - Historical guides retained on disk; use this file instead for current commands

## Minimum Runnable Path

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Create local config:

```bash
cp .env.example .env
```

3. Set at least one API key in `.env` for normal chat usage:

```bash
QWEN_API_KEY=...
```

4. Start the canonical local app path:

```bash
python run_api.py
```

5. Open:

- `http://localhost:8000` for the web UI
- `http://localhost:8000/docs` for the OpenAPI docs

## Minimum Local Validation Path

If you want the smallest useful validation before using the app:

```bash
python main.py health
pytest
```

If you want a browser-facing validation after startup:

1. Run `python run_api.py`
2. Open `http://localhost:8000`
3. Open `http://localhost:8000/api/health`

Expected result:

- the health command reports the runtime as healthy
- `pytest` completes without failures
- `/api/health` returns a JSON health payload from the running server

## Notes

- `run_api.py` is the canonical launcher because it matches the integrated API + web deployment shape.
- `main.py chat` remains supported, but it is a secondary debugging/developer path.
- The specialized integration scripts may require live LLM configuration and should not be treated as the smallest smoke checks.
- Evaluation and reproducibility commands live in [evaluation/README.md](evaluation/README.md).
