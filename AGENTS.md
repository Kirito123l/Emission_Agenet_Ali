# Repository Guidelines

## Project Structure & Module Organization
Core application logic lives in `core/` (routing, context assembly, execution, memory). Domain tools are in `tools/`, with numeric engines in `calculators/` and model/service integrations in `services/`. API endpoints and session handling are in `api/`, and the browser UI is in `web/` (`index.html`, `app.js`). Runtime configuration is centralized in `config.py` and `config/`. Persistent and generated data appear in `data/`, `logs/`, and `outputs/`. Utility scripts and ad hoc integration tests are in `scripts/utils/`.

## Build, Test, and Development Commands
- `pip install -r requirements.txt`: install Python dependencies.
- `python run_api.py`: start FastAPI + web UI locally (default `http://localhost:8000`).
- `python main.py chat`: run CLI chat mode.
- `python main.py health`: quick runtime health check.
- `python main.py tools-list`: list registered tools.
- `python scripts/utils/test_new_architecture.py`: architecture integration check.
- `python scripts/utils/test_api_integration.py`: API integration smoke test.

## Coding Style & Naming Conventions
Use Python 3 with 4-space indentation, type hints for new/changed functions, and module-level `snake_case` names (`file_analyzer.py`, `llm_client.py`). Keep classes in `PascalCase`, constants in `UPPER_SNAKE_CASE`, and prefer small, focused async tool methods returning `ToolResult`. Follow existing folder naming and keep web changes minimal and framework-free unless a broader refactor is approved.

## Testing Guidelines
There is no formal `pytest` suite at repo root yet; treat `scripts/utils/test_*.py` as required regression checks for behavior changes. Name new test scripts `test_<feature>.py` and place them in `scripts/utils/` unless they are model-specific (then colocate under that module, e.g., `LOCAL_STANDARDIZER_MODEL/tests/`). Validate both CLI and API paths for tool-related changes.

## Commit & Pull Request Guidelines
Current history is minimal, so use clear imperative commit subjects (for example, `feat: add macro emission input validation`). Keep commits scoped to one logical change. PRs should include: purpose, impacted modules, test commands run, and sample request/response payloads or screenshots for `web/` updates.

## Security & Configuration Tips
Never commit secrets from `.env`. Keep API keys local and rotate if exposed. Avoid committing large generated artifacts from `outputs/` or runtime logs unless needed for debugging and explicitly noted in the PR.
