# Repository Engineering Audit

**Repository:** emission_agent
**Audit Date:** 2026-03-13
**Auditor:** Claude Opus 4.6 (automated, evidence-based)
**Scope:** Full repository structure, code, configuration, documentation, data, experiments, deployment

---

## Executive Summary

### What kind of repository this currently is

This is an **advanced research/engineering prototype** for an LLM-powered vehicle emission calculation assistant. It combines a FastAPI backend, a chat-based web frontend, LLM tool-calling orchestration, EPA MOVES emission calculation engines, RAG knowledge retrieval, GIS map visualization, and user authentication into a single repository. The project has gone through multiple architectural iterations and is actively deployed to an Alibaba Cloud server via GitHub Actions CI/CD.

It sits between "research prototype" and "semi-production system" -- it runs in production and serves real users, but its codebase carries significant accumulated technical debt from rapid iterative development.

### Strongest aspects

1. **Well-designed core architecture:** The Router -> Assembler -> LLM -> Executor -> Tool pipeline is clean and well-separated. The "transparent standardization" pattern (LLM sees raw user input, executor standardizes behind the scenes) is a genuinely good design decision.
2. **Comprehensive domain coverage:** Three emission calculation tools (emission factors, micro/macro), file handling, knowledge RAG, GIS map visualization, and a working web UI. This is a substantial, non-trivial system.
3. **Emerging evaluation infrastructure:** The `evaluation/` directory contains structured benchmarks (end-to-end, file grounding, normalization, ablation) with sample datasets, proper metrics, and configurable runtime overrides. This is ahead of most research prototypes.
4. **Configuration externalization:** Unified mappings YAML, prompt YAML, `.env`-driven model assignments, and feature flags show good configuration hygiene.

### Most dangerous weaknesses

1. **Hardcoded JWT secret key** in `api/auth.py` line 13: `SECRET_KEY = "emission-agent-secret-key-change-in-production"` -- this is a live security vulnerability in production.
2. **Real API keys in `.env`** (Qwen and DeepSeek keys are committed to the working tree; `.env` is gitignored but `.env` itself contains real secrets that could leak if copied).
3. **Dual architecture coexistence:** Both `tools/` and `skills/` implement the same four capabilities with near-identical code. The old `skills/` layer and `llm/client.py` (old LLM client) coexist with the new `tools/` + `services/llm_client.py`, creating confusion about which path is active.
4. **Massive documentation debt:** 72+ report files in `docs/reports/`, 8 root-level markdown files, many duplicated/outdated. The documentation volume actually hurts discoverability.

### Top 3 priorities

1. **Security hardening:** Fix JWT secret, audit for leaked credentials, ensure `.env` cannot be accidentally committed.
2. **Remove dead code:** Eliminate the `skills/` -> `tools/` duplication, and consolidate the two LLM client implementations (`llm/client.py` vs `services/llm_client.py`).
3. **Documentation consolidation:** Reduce 72+ report files to a handful of living documents; create a single authoritative ARCHITECTURE.md.

---

## A. Overall Project Identity and Maturity

### Problem Statement

The repository implements an AI-powered assistant that helps users calculate vehicle exhaust emissions using EPA MOVES methodology. It supports three primary tasks:

1. **Emission factor queries** -- look up speed-dependent emission curves for specific vehicle types and pollutants
2. **Micro-scale emission calculation** -- compute second-by-second emissions from vehicle trajectory data (VSP-based)
3. **Macro-scale emission calculation** -- compute link-level emissions from road network traffic data

The assistant uses LLM (Qwen/DeepSeek) with OpenAI-compatible tool calling to understand natural language queries, map them to appropriate tools, handle file uploads, and present results with charts, tables, maps, and downloadable Excel files.

### Maturity Assessment

| Dimension | Rating | Notes |
|-----------|--------|-------|
| Core calculation logic | Mature | MOVES methodology correctly implemented |
| LLM orchestration | Mature | Clean tool-use architecture, proxy failover, retry |
| Web UI | Functional | Working but monolithic (single 2021-line JS file) |
| API layer | Functional | Streaming + non-streaming endpoints, but routes.py is 1195 lines |
| Authentication | Basic | Works but has hardcoded JWT secret |
| Evaluation | Emerging | Good framework, needs more samples |
| Testing | Missing | No unit tests, no integration tests, no CI test step |
| Documentation | Chaotic | Volume is high, signal-to-noise ratio is low |

### Central Storyline Risk

There is a "many features but weak central storyline" problem. The repository spans:
- LLM agent orchestration
- Emission calculation engines
- RAG knowledge retrieval
- GIS map visualization
- User authentication
- Local model fine-tuning (LoRA)
- Deployment scripts
- Multiple evaluation frameworks

For a research paper or open-source release, the core story should be clarified: Is this primarily about the **LLM agent architecture for domain-specific scientific computation**, or about the **emission calculation methodology**, or about the **evaluation framework**?

---

## B. Repository Structure and File Organization

### Root Directory Clutter

The root directory contains **8 markdown files** beyond README.md:
- `AGENTS.md` -- Claude Code agent instructions
- `CLEANUP_PLAN.md` -- ignored by gitignore but present
- `CODEBASE_PAPER_DEEP_AUDIT_ROUND2.md` -- untracked
- `CODEBASE_SYSTEM_AUDIT_FOR_PAPER.md` -- untracked
- `DEPLOYMENT_INCIDENT_AND_SOP.md` -- untracked
- `EXPERIMENT_DESIGN_AND_EVAL_PLAN.md` -- untracked
- `prompt.md` -- unclear purpose (seems to be a design prompt, not used by code)

Additionally:
- `stitch_emissionagent_desktop_dashboard (7)/` -- a screenshot+HTML folder with spaces in name, clearly a one-off artifact
- `GIS文件/` -- 31MB of raw Shapefiles (gitignored but still on disk)
- `static_gis.tar.gz` -- 900KB compressed archive in repo (should not be versioned)
- `preprocess_gis.py` -- one-off script at root level

### Directory Organization Assessment

| Directory | Status | Notes |
|-----------|--------|-------|
| `core/` | Good | 4 files, clear responsibilities |
| `tools/` | Good | New architecture, well-structured |
| `skills/` | **Deprecated** | Old architecture, still imported by tools |
| `calculators/` | Good | Pure calculation logic, no LLM dependency |
| `services/` | Good | Service layer, clean |
| `api/` | Needs refactoring | `routes.py` is 1195 lines |
| `web/` | Needs cleanup | `app.js.backup`, `app_origin.js`, `diagnostic.html` |
| `config/` | Good | Externalized configuration |
| `data/` | OK | Runtime data, properly gitignored |
| `deploy/` | OK | Deployment scripts |
| `docs/` | **Chaotic** | 72+ report files, massive redundancy |
| `evaluation/` | Good foundation | Needs more samples and documentation |
| `llm/` | **Legacy** | Overlaps with `services/llm_client.py` |
| `shared/` | OK | Local standardizer integration |
| `scripts/` | OK | Has `deprecated/` subfolder (good) |
| `test_data/` | OK | Test data with documentation |
| `LOCAL_STANDARDIZER_MODEL/` | Isolated | 9.6MB, self-contained sub-project |
| `logs/`, `outputs/` | Gitignored | Runtime directories |

### Files That Should Not Be in the Repository

| File/Directory | Issue | Recommendation |
|----------------|-------|----------------|
| `static_gis.tar.gz` | 900KB binary archive | Remove, distribute separately |
| `GIS文件/` | 31MB raw Shapefiles | Already gitignored, delete from disk |
| `stitch_emissionagent_desktop_dashboard (7)/` | One-off screenshot artifact | Delete |
| `web/app.js.backup` | Backup file | Delete |
| `web/app_origin.js` | Old version | Delete |
| `web/diagnostic.html` | Debug page | Move to `scripts/` or delete |
| `prompt.md` | Unused design prompt at root | Move to `docs/` or delete |
| `*.Zone.Identifier` files | Windows WSL artifacts | Already in gitignore pattern |
| `data/users.db` | Runtime SQLite database | Already gitignored |

---

## C. Core Module Architecture

### Architecture Diagram (Actual)

```
User Request
    |
    v
[api/routes.py] -- FastAPI endpoints (chat, stream, file, session, auth)
    |
    v
[api/session.py] -- SessionRegistry -> SessionManager -> Session
    |
    v
[core/router.py] -- UnifiedRouter (1161 lines, the brain)
    |
    +---> [core/assembler.py] -- Context assembly (system prompt + tools + memory + file context)
    +---> [core/memory.py] -- Three-layer memory (working + fact + compressed)
    +---> [services/llm_client.py] -- LLM API calls with tool use (NEW)
    +---> [core/executor.py] -- Tool execution with standardization
              |
              +---> [services/standardizer.py] -- Vehicle/pollutant/column standardization
              +---> [tools/registry.py] -- Tool registry
                        |
                        +---> [tools/emission_factors.py]
                        +---> [tools/micro_emission.py] ---> [calculators/micro_emission.py]
                        +---> [tools/macro_emission.py] ---> [calculators/macro_emission.py]
                        +---> [tools/file_analyzer.py]
                        +---> [tools/knowledge.py] ---> [skills/knowledge/]
```

### Key Architectural Issues

#### 1. Dual Architecture Coexistence (tools/ vs skills/)

The `tools/` directory is the new architecture. However, `tools/micro_emission.py` imports from `skills/micro_emission/excel_handler.py`, and `tools/macro_emission.py` imports from `skills/macro_emission/excel_handler.py`. Both tool implementations also use `llm/client.py` (old LLM client) for intelligent column mapping.

Meanwhile, `skills/registry.py` still initializes `EmissionFactorsSkill`, `MicroEmissionSkill`, `MacroEmissionSkill`, `KnowledgeSkill` -- but nothing in the active code path calls `skills/registry.py`.

**Status:** `skills/*.skill.py` files are **likely deprecated** but `skills/*.excel_handler.py` files are **actively used** by tools. This needs manual confirmation before any deletion.

#### 2. Dual LLM Client Implementations

- `services/llm_client.py` (`LLMClientService`) -- used by `core/router.py` for agent chat and tool calling
- `llm/client.py` (`LLMClient`) -- used by `tools/micro_emission.py` and `tools/macro_emission.py` for column mapping

Both implement proxy failover, both wrap the OpenAI SDK, both have nearly identical `_is_connection_error()` and `_request_with_failover()` methods. This is clear duplication.

#### 3. Router Complexity (1161 lines)

`core/router.py` is the largest Python file and handles:
- Main chat flow
- Tool call loop with retry
- Synthesis (calling a separate LLM for response generation)
- Chart data extraction and normalization
- Table data construction
- Map data passthrough
- File analysis caching with mtime detection
- Download file metadata management
- Error handling and fallback

Much of the chart/table/download normalization logic in `router.py` is duplicated in `api/routes.py` (which has its own `build_emission_chart_data`, `extract_key_points`, `normalize_download_file` functions).

#### 4. Routes.py Complexity (1195 lines)

`api/routes.py` contains:
- Chat endpoint (non-streaming)
- Chat endpoint (streaming with heartbeat)
- File preview endpoint
- GIS basemap/roadnetwork endpoints (with global caching)
- Multiple download endpoints (by session, by message, by filename)
- Template download
- Session CRUD
- Authentication (register, login, get current user)
- Various helper functions for chart/table normalization

This should be split into at least 3-4 modules (chat, files, sessions, auth).

---

## D. Code Quality and Maintainability

### Naming Consistency

- **Mixed languages in comments/strings:** Chinese and English comments are intermixed throughout. This is understandable for a Chinese research team, but for open-source release, public-facing code should use English comments consistently.
- **Variable naming:** Generally good Python conventions (snake_case). Some inconsistency in parameter names (`file_path` vs `input_file` -- both handled via compatibility mapping).
- **Module naming:** Clear and descriptive.

### Function/Class Responsibility

- `UnifiedRouter.chat()` does too much -- it's essentially a 200+ line function that should be decomposed.
- `routes.py::chat()` and `routes.py::chat_stream()` have massive code duplication (~80% identical logic).
- Tool classes (`MicroEmissionTool`, `MacroEmissionTool`) are well-structured with clear `execute()` methods.

### Duplicated Logic

| Duplication | Location 1 | Location 2 | Severity |
|-------------|-----------|-----------|----------|
| LLM client with failover | `services/llm_client.py` | `llm/client.py` | High |
| Chart data normalization | `core/router.py` | `api/routes.py` | Medium |
| Download file normalization | `core/router.py` | `api/routes.py` | Medium |
| Chat endpoint logic | `routes.py::chat()` | `routes.py::chat_stream()` | Medium |
| Skill implementations | `skills/*.skill.py` | `tools/*.py` | High (dead code) |

### Hardcoded Values

| Location | Value | Risk |
|----------|-------|------|
| `api/auth.py:13` | JWT `SECRET_KEY = "emission-agent-secret-key-change-in-production"` | **CRITICAL security** |
| `core/assembler.py:32` | `MAX_CONTEXT_TOKENS = 6000` | Should be configurable |
| `core/memory.py:58` | `MAX_WORKING_MEMORY_TURNS = 5` | Should be configurable |
| `core/router.py:59` | `MAX_TOOL_CALLS_PER_TURN = 3` | Reasonable default |
| `tools/macro_emission.py:404` | Default center `[116.4074, 39.9042]` (Beijing) | Should match actual data region |

### Debugging Leftovers

- `routes.py` lines 317-324: `sys.stdout.write` debug prints with emoji in production chat endpoint
- `routes.py` lines 373-376: `[DEBUG API]` logger statements
- `routes.py` lines 538-542: `[DEBUG STREAM]` logger statements
- `routes.py` lines 1039-1044: Debug logging of every history message
- `routes.py` lines 1059-1073: Test endpoint with emoji debug output

### Error Handling

- Tool execution has good error handling with structured error responses.
- `routes.py` has a `friendly_error_message()` function for user-facing errors -- good practice.
- However, several bare `except Exception as e` blocks exist without specific error type handling.
- The `_parse_json_response()` in `llm/client.py` has impressive robustness for malformed LLM JSON output.

### Type Annotations

- Present in most function signatures but incomplete. No `mypy` or type checking configured.
- `ToolResult`, `RouterResponse`, `LLMResponse` are well-typed dataclasses.

---

## E. Configuration, Environment, and Dependency Management

### Dependencies (requirements.txt)

The `requirements.txt` is well-structured with comments grouping dependencies:
- Core LLM deps (openai, httpx)
- Web framework (fastapi, uvicorn)
- Data processing (pandas, openpyxl)
- RAG (faiss-cpu, dashscope)
- Auth (passlib, PyJWT, aiosqlite)
- GIS (shapely, geopandas, fiona)

**Issues:**
- `fuzzywuzzy` is imported but not in requirements.txt (code falls back to `difflib`)
- No lock file (`requirements.lock` or `pip freeze` output) for reproducibility
- `geopandas>=0.13.0` and `fiona>=1.9.0` are heavy dependencies (C extensions) that are only needed for Shapefile import -- could be made optional
- `bcrypt<4.1` version pinning seems fragile
- No `pyproject.toml` -- still using legacy `requirements.txt` only

### Environment Configuration

- `.env.example` is comprehensive and well-documented
- Feature flags (`ENABLE_LLM_STANDARDIZATION`, `ENABLE_STANDARDIZATION_CACHE`, etc.) are a good pattern
- `config.py` is clean with a singleton pattern and `reset_config()` for testing
- **Missing from `.env.example`:** `JWT_SECRET_KEY` (currently hardcoded), `ENABLE_FILE_ANALYZER`, `ENABLE_FILE_CONTEXT_INJECTION`, `ENABLE_EXECUTOR_STANDARDIZATION`, `MACRO_COLUMN_MAPPING_MODES`, `PORT`

### Docker Configuration

- Multi-stage Dockerfile is well-structured (builder + runtime)
- `docker-compose.yml` is minimal and correct
- `.dockerignore` exists (not inspected, but present)
- No docker-compose profiles for dev vs production

---

## F. Data, Knowledge Base, Samples, and Assets

### Data Organization

| Path | Contents | Size | Risk |
|------|----------|------|------|
| `calculators/data/emission_factors/` | 3 CSV files (EPA MOVES data) | Small | Core data, must be included |
| `calculators/data/macro_emission/` | 3 CSV files | Small | Core data |
| `calculators/data/micro_emission/` | 3 CSV files | Small | Core data |
| `skills/macro_emission/data/` | 3 CSV files | Small | **Duplicate** of calculators/data |
| `skills/micro_emission/data/` | 3 CSV files | Small | **Duplicate** of calculators/data |
| `config/unified_mappings.yaml` | Vehicle types, pollutants, column patterns | Small | Core config |
| `skills/knowledge/index/` | FAISS index + chunks | ~2MB | RAG knowledge base |
| `data/collection/` | JSONL standardization training data | Small | Collection data |
| `data/learning/cases.jsonl` | Learning cases | Small | Auto-collected |
| `static_gis/` | 2 GeoJSON files | 6MB | GIS basemap data |
| `static_gis.tar.gz` | Compressed version | 900KB | **Should not be in repo** |
| `LOCAL_STANDARDIZER_MODEL/` | Full sub-project | 9.6MB | Should be separate repo |
| `test_data/` | Test Excel/ZIP files | Several MB | OK for repo |

### Duplicate Data Files

The CSV data files in `skills/macro_emission/data/` and `skills/micro_emission/data/` appear to be exact duplicates of files in `calculators/data/`. This was noted in a previous commit message (`d744d16 chore: remove redundant calculator files and update gitignore`) but the skills-side copies were not removed.

### Large Files and Open-Source Risk

- `static_gis/basemap.geojson` and `roadnetwork.geojson` total ~6MB. These are Shanghai-specific GIS data. For open-source release, these should be documented as optional/sample data.
- `LOCAL_STANDARDIZER_MODEL/` contains training data, scripts, configs, and documentation for a LoRA fine-tuning sub-project. This is 9.6MB and could be a separate repository.
- `GIS文件/` (31MB raw Shapefiles) is gitignored but present on disk.

### Absolute Path Dependencies

No hardcoded absolute paths found in Python code. Paths are relative to `PROJECT_ROOT` via `config.py`. Session data uses relative paths (`data/sessions/`). This is good.

---

## G. Experiment and Evaluation Infrastructure

### Evaluation Structure

```
evaluation/
  __init__.py
  utils.py                    # Common utilities (load_jsonl, runtime_overrides, classify_failure, etc.)
  eval_end2end.py            # End-to-end task evaluation
  eval_file_grounding.py     # File task recognition + column mapping evaluation
  eval_normalization.py      # Standardization evaluation
  eval_ablation.py           # Ablation study framework
  end2end/samples.jsonl      # End-to-end benchmark samples
  file_tasks/
    samples.jsonl            # File grounding samples
    data/                    # 8 test CSV files (micro + macro variants)
  normalization/samples.jsonl # Normalization test samples
  human_compare/samples.csv  # Human comparison dataset
```

### Assessment

**Strengths:**
- Well-structured evaluation scripts with proper argument parsing
- `runtime_overrides` context manager enables clean ablation studies
- Metrics are well-defined: tool_call_success_rate, route_accuracy, end2end_completion_rate, column_mapping_accuracy
- Failure classification taxonomy (recoverable vs unrecoverable)
- Sample datasets exist for multiple evaluation dimensions

**Weaknesses:**
- **No unified runner:** Each eval script must be run separately. A `Makefile` or unified `run_eval.py` would help.
- **Sample sizes are small:** The `end2end/samples.jsonl` and `file_tasks/samples.jsonl` likely contain <20 samples each. For paper-quality experiments, this needs significant expansion.
- **No baseline comparisons:** The evaluation framework measures the system's own performance but doesn't compare against baselines (e.g., no-standardization, different LLMs, no RAG).
- **No documentation:** The evaluation framework has no README explaining how to run benchmarks, what metrics mean, or how to add new samples.
- **No CI integration:** Evaluations are not part of the CI/CD pipeline (they require LLM API calls, which is understandable, but at least non-LLM tests could be automated).
- **Logs directory not gitignored consistently:** Evaluation may write to `evaluation/logs/` which could accidentally be committed.

---

## H. Interfaces and Run Entry Points

### Entry Points

| Entry Point | Type | Status | Notes |
|-------------|------|--------|-------|
| `python run_api.py` | Web API server | **Primary** | Starts FastAPI with uvicorn |
| `python main.py chat` | CLI chat | Secondary | Interactive terminal chat |
| `python main.py health` | CLI health check | Utility | Lists registered tools |
| `python main.py tools-list` | CLI tool list | Utility | Similar to health |
| `python -m evaluation.eval_end2end` | Evaluation | Development | End-to-end benchmark |
| `python -m evaluation.eval_file_grounding` | Evaluation | Development | File grounding benchmark |
| `python -m evaluation.eval_normalization` | Evaluation | Development | Normalization benchmark |
| `python -m evaluation.eval_ablation` | Evaluation | Development | Ablation study |
| `python preprocess_gis.py` | One-off script | Utility | Preprocesses Shapefiles to GeoJSON |
| `scripts/query_emission_factors_cli.py` | CLI tool | Utility | Direct emission factor query |

### Assessment

- The primary entry point (`run_api.py`) is clear and well-documented in README.
- `main.py` CLI is clean but underused (the web UI is the primary interface).
- The `test_api_integration.py` and `test_new_architecture.py` in `scripts/utils/` are referenced in README as test commands but are utility scripts, not proper tests.
- A new developer can identify the runnable path quickly: README -> `pip install` -> `cp .env.example .env` -> `python run_api.py`.

---

## I. Documentation and Readability

### README.md

The README is **comprehensive and well-structured**:
- Clear project description
- Architecture diagram
- Quick start instructions
- Usage examples
- API endpoint documentation
- Configuration guide
- Development guide with "Adding New Tools" instructions

**Issues:**
- Architecture section references `calculators/micro.py` and `calculators/macro.py` but actual files are `micro_emission.py` and `macro_emission.py`
- Testing section references `test_new_architecture.py` and `test_api_integration.py` as if they are test commands, but they are scripts in `scripts/utils/`
- No mention of evaluation framework

### Documentation Volume Problem

The `docs/` directory contains **72+ report files** in `docs/reports/` alone. These are historical development logs, bug fix reports, phase completion reports, and analysis documents. Examples:

- `PHASE1_COMPLETION_REPORT.md` through `PHASE7_COMPLETION_REPORT.md`
- `FIX_ROUND2_REPORT.md`, `FIX_ROUND3_REPORT.md`, `FIX_ROUND4_REPORT.md`
- `BUGFIX_REPORT.md`, `BUGFIX_SUMMARY.md`, `BUG_FIX_REPORT.md` (three separate files)
- `DIAGNOSIS_REPORT.md`, `DIAGNOSIS_SUMMARY.md`, `DIAGNOSTIC_REPORT.md`

This is a **documentation graveyard**. These files are useful as a development journal but they severely reduce the signal-to-noise ratio. A new developer or collaborator will be overwhelmed.

The `docs/Claude_Design/` directory contains prompts that were fed to Claude for development -- these are internal development artifacts, not documentation.

### Key Missing Documentation

| Document | Priority | Notes |
|----------|----------|-------|
| `ARCHITECTURE.md` (authoritative, up-to-date) | High | `docs/ARCHITECTURE.md` exists but may be outdated |
| `CONTRIBUTING.md` | High | Essential for open-source |
| `DEVELOPMENT.md` | High | How to set up dev environment, run tests |
| `evaluation/README.md` | High | How to run benchmarks |
| `DATA_GUIDE.md` | Medium | What data files exist, their format, source |
| `LICENSE` file | **Critical** | README says MIT but no LICENSE file exists |

---

## J. Testing, Quality Assurance, and Engineering Discipline

### Current Testing Status

**There are no tests.** Specifically:
- No `tests/` directory
- No `pytest.ini`, `setup.cfg`, or `pyproject.toml` with test configuration
- No unit tests for calculators, standardizers, or tools
- No integration tests for the API
- The CI/CD pipeline (`deploy.yml`) has **no test step** -- it deploys directly on push to main
- `.gitignore` excludes `test_*.py` files (this is overly aggressive and would prevent test files from being committed)

The files in `scripts/utils/test_*.py` are manual test scripts, not automated tests.

### Lint / Format / Type Check

- No `ruff`, `black`, `isort`, `flake8`, or `pylint` configuration
- No `mypy` configuration
- No `pre-commit` hooks
- No `.editorconfig`
- Code formatting is generally consistent but not enforced

### Recommendations (Realistic for Current Size)

Given the project's size (~16K lines of Python, ~60 Python files), the minimal viable testing setup would be:

1. **Add `pyproject.toml`** with `[tool.pytest]`, `[tool.ruff]` sections
2. **Add `tests/` directory** with:
   - `test_calculators.py` -- pure function tests for emission calculations (no LLM needed)
   - `test_standardizer.py` -- standardization mapping tests (no LLM needed)
   - `test_config.py` -- configuration loading tests
3. **Add `ruff` linting** -- zero-config, catches real bugs
4. **Fix `.gitignore`** -- remove the `test_*.py` exclusion, add explicit `scripts/utils/test_*.py` instead
5. **Add test step to CI** before deploy

---

## K. Open-Source Readiness Assessment

### Distance from Public Release: **Significant work needed**

| Requirement | Status | Blocker? |
|-------------|--------|----------|
| LICENSE file | **Missing** | YES |
| No hardcoded secrets | **FAIL** (JWT secret in code) | YES |
| No real API keys accessible | **RISK** (.env with real keys on disk) | YES |
| `.gitignore` hygiene | Mostly good | No |
| `.env.example` | Good | No |
| CONTRIBUTING.md | Missing | YES (for community) |
| Minimal runnable example | README covers this | No |
| Documentation accuracy | Mixed | Partial |
| No internal references | Deployment references private server | Minor |
| Sample data for outsiders | `test_data/` exists with examples | No |
| Dependencies installable | Yes | No |
| Can outsider clone + run? | **Partially** -- needs API key, GIS data optional | Minor |

### Key Blockers for Open-Source Release

1. **No LICENSE file** -- despite README claiming MIT
2. **Hardcoded JWT secret** in `api/auth.py`
3. **72+ internal development reports** in `docs/reports/` would confuse external contributors
4. **`LOCAL_STANDARDIZER_MODEL/`** contains training data and scripts that may have distribution concerns
5. **Shanghai-specific GIS data** in `static_gis/` -- acceptable as sample data but should be documented
6. **Chinese-only comments and UI strings** in much of the codebase -- fine for a Chinese-facing tool, but limits international adoption
7. **No test suite** means contributors cannot verify their changes don't break anything

---

## L. Technical Debt and Risk List

### High Priority

| # | Issue | Location | Affects | Difficulty |
|---|-------|----------|---------|------------|
| H1 | Hardcoded JWT secret key | `api/auth.py:13` | Security, open-source | Easy |
| H2 | No LICENSE file | Root | Open-source release | Easy |
| H3 | `.gitignore` excludes `test_*.py` | `.gitignore` | Testing | Easy |
| H4 | Dual LLM client implementations | `services/llm_client.py` + `llm/client.py` | Maintainability | Medium |
| H5 | Dead `skills/*.skill.py` code path | `skills/` | Code clarity | Medium |
| H6 | No automated tests | Entire project | Refactoring safety | Medium |
| H7 | `routes.py` is 1195 lines | `api/routes.py` | Maintainability | Medium |
| H8 | `router.py` is 1161 lines | `core/router.py` | Maintainability | Medium |
| H9 | Debug print statements in production code | `api/routes.py` | Log quality | Easy |
| H10 | No test step in CI/CD | `.github/workflows/deploy.yml` | Deploy safety | Easy |

### Medium Priority

| # | Issue | Location | Affects | Difficulty |
|---|-------|----------|---------|------------|
| M1 | Duplicate CSV data files | `skills/*/data/` vs `calculators/data/` | Confusion | Easy |
| M2 | `static_gis.tar.gz` in repository | Root | Repo size | Easy |
| M3 | 72+ report files in `docs/reports/` | `docs/reports/` | Documentation quality | Medium |
| M4 | Chart/table normalization duplicated | `router.py` + `routes.py` | Code duplication | Medium |
| M5 | `chat()` and `chat_stream()` duplication | `api/routes.py` | Maintainability | Medium |
| M6 | No `pyproject.toml` | Root | Modern Python packaging | Easy |
| M7 | Missing `.env.example` entries | `.env.example` | Reproducibility | Easy |
| M8 | README architecture diagram inaccuracies | `README.md` | Developer confusion | Easy |
| M9 | `stitch_emissionagent_desktop_dashboard (7)/` in repo | Root | Repo clutter | Easy |
| M10 | No evaluation README | `evaluation/` | Experiment reproducibility | Easy |

### Low Priority

| # | Issue | Location | Affects | Difficulty |
|---|-------|----------|---------|------------|
| L1 | `web/app.js` is 2021 lines (monolithic) | `web/app.js` | Frontend maintainability | Hard |
| L2 | `web/app.js.backup` and `app_origin.js` | `web/` | Clutter | Easy |
| L3 | `prompt.md` at root level | Root | Clutter | Easy |
| L4 | `preprocess_gis.py` at root level | Root | Should be in scripts/ | Easy |
| L5 | `LOCAL_STANDARDIZER_MODEL/` could be separate repo | Root | Repo size/clarity | Medium |
| L6 | Token estimation is rough heuristic | `core/assembler.py:236-244` | Accuracy | Medium |
| L7 | No rate limiting on auth endpoints | `api/routes.py` | Security | Medium |
| L8 | `datetime.utcnow()` deprecated in Python 3.12+ | `api/auth.py`, `api/database.py` | Future compat | Easy |
| L9 | Mixed Chinese/English code comments | Throughout | Open-source readability | Hard |
| L10 | `CORS allow_origins=["*"]` in production | `api/main.py:43` | Security | Easy |

---

## M. Phased Remediation Roadmap

### Phase 0: Immediate Blockers and Repository Risks (Start Immediately)

**Objective:** Fix security issues and critical blockers that could cause immediate harm.

**Key Tasks:**
1. Move JWT `SECRET_KEY` to environment variable, update `.env.example`
2. Add `LICENSE` file (MIT as stated in README)
3. Verify `.env` is not committed to git history (check `git log --all -- .env`)
4. Remove `test_*.py` exclusion from `.gitignore` (replace with specific `scripts/utils/test_*.py`)
5. Delete `stitch_emissionagent_desktop_dashboard (7)/` directory
6. Delete `web/app.js.backup` and `web/app_origin.js`
7. Remove `static_gis.tar.gz` from repository
8. Remove debug `sys.stdout.write` and `[DEBUG]` logger statements from `routes.py`

**Expected Benefits:** Secure production deployment, unblocked open-source preparation.
**Risks:** JWT secret change requires re-authentication of existing users.
**Start:** Immediately.

### Phase 1: Repository Cleanup and Engineering Standardization (1-2 weeks)

**Objective:** Eliminate dead code, reduce duplication, establish engineering foundations.

**Key Tasks:**
1. **Consolidate LLM clients:** Merge `llm/client.py` functionality into `services/llm_client.py`, update all imports
2. **Clean up skills/ directory:**
   - Move `skills/*/excel_handler.py` to `tools/` or a shared location
   - Confirm `skills/*.skill.py` files are unused, then delete them
   - Remove duplicate CSV data from `skills/*/data/`
3. **Split `api/routes.py`** into: `routes/chat.py`, `routes/files.py`, `routes/sessions.py`, `routes/auth.py`
4. **Add `pyproject.toml`** with project metadata, pytest config, ruff config
5. **Add basic tests:** `tests/test_calculators.py`, `tests/test_standardizer.py`, `tests/test_config.py`
6. **Add CI test step** in GitHub Actions before deploy
7. **Update `.env.example`** with all configurable values
8. **Move `preprocess_gis.py`** to `scripts/`
9. **Fix README** architecture diagram inaccuracies

**Expected Benefits:** Cleaner codebase, safer refactoring, CI-protected deployments.
**Risks:** Import path changes may break things -- test manually before deploying.
**Start:** After Phase 0.

### Phase 2: Documentation and Evaluation Consolidation (1-2 weeks)

**Objective:** Make documentation useful and evaluation framework paper-ready.

**Key Tasks:**
1. **Archive `docs/reports/`:** Move all 72+ files to `docs/archive/reports/` or a separate branch
2. **Create authoritative documents:**
   - `docs/ARCHITECTURE.md` -- rewrite from scratch based on actual code
   - `CONTRIBUTING.md` -- contribution guide
   - `DEVELOPMENT.md` -- development setup and workflow
   - `evaluation/README.md` -- evaluation framework documentation
   - `DATA_GUIDE.md` -- data files, formats, sources
3. **Expand evaluation samples:** Add more test cases to each benchmark category
4. **Create unified evaluation runner:** `Makefile` or `scripts/run_eval.sh` that runs all benchmarks
5. **Add evaluation baseline:** At minimum, measure performance with standardization disabled as a baseline
6. **Document metrics definitions** in evaluation README

**Expected Benefits:** Outsiders can understand the project; evaluation is paper-ready.
**Risks:** Low risk.
**Start:** Can overlap with Phase 1.

### Phase 3: Open-Source Release Preparation (1 week)

**Objective:** Make the repository suitable for public GitHub release.

**Key Tasks:**
1. **Audit git history** for accidentally committed secrets
2. **Review `LOCAL_STANDARDIZER_MODEL/`** -- either document it clearly or extract to separate repo
3. **Document GIS data** as optional with instructions for how to provide your own
4. **Add `examples/` directory** with minimal runnable examples (e.g., single emission factor query, single micro calculation)
5. **Translate key documentation** to English (or clearly mark as bilingual project)
6. **Add `.env.example` completeness check** in CI
7. **Create GitHub issue templates** and PR template
8. **Final security audit** -- run `trufflehog` or similar on repository

**Expected Benefits:** Clean public release.
**Risks:** Git history rewrite may be needed if secrets are found in history.
**Start:** After Phases 1 and 2.

### Phase 4: Longer-Term Architecture Improvements

**Objective:** Address deeper structural issues for long-term maintainability.

**Key Tasks:**
1. **Decompose `core/router.py`:** Extract chart normalization, file caching, and download management into separate modules
2. **Extract `routes.py` response builders:** Create a shared response normalization layer used by both chat and stream endpoints
3. **Consider frontend modernization:** If the web UI will continue to be developed, consider migrating `app.js` to a framework (React/Vue/Svelte) or at least splitting into modules
4. **Make GIS dependencies optional:** Guard `geopandas`/`fiona` imports so the system runs without them
5. **Add structured logging:** Replace `sys.stdout.write` debug patterns with proper structured JSON logging
6. **Add request validation middleware:** Rate limiting, input size limits
7. **Consider database migration tool:** If the user schema evolves, add Alembic or similar

**Expected Benefits:** Maintainable long-term architecture.
**Risks:** Significant refactoring effort.
**Start:** After open-source release, based on community feedback.

---

## N. Recommended Files to Add or Restructure

### Files to Add

| File | Priority | Purpose |
|------|----------|---------|
| `LICENSE` | **Critical** | MIT license text |
| `pyproject.toml` | High | Project metadata, tool configs (pytest, ruff) |
| `CONTRIBUTING.md` | High | Contribution guidelines |
| `DEVELOPMENT.md` | High | Development setup, running tests, deployment |
| `evaluation/README.md` | High | Evaluation framework guide |
| `Makefile` | Medium | Common commands (test, lint, eval, serve) |
| `tests/__init__.py` | High | Test package |
| `tests/test_calculators.py` | High | Calculator unit tests |
| `tests/test_standardizer.py` | High | Standardization tests |
| `tests/test_config.py` | Medium | Config loading tests |
| `tests/conftest.py` | Medium | Shared test fixtures |
| `examples/README.md` | Medium | Example scripts guide |
| `examples/query_emission_factors.py` | Medium | Minimal runnable example |
| `DATA_GUIDE.md` | Medium | Data file documentation |

### Files to Restructure

| Current | Proposed | Notes |
|---------|----------|-------|
| `api/routes.py` (1195 lines) | Split into `api/routes/chat.py`, `api/routes/files.py`, `api/routes/sessions.py`, `api/routes/auth.py` | Reduce per-file complexity |
| `llm/client.py` | Merge into `services/llm_client.py`, then delete `llm/` | Eliminate duplication |
| `skills/*/excel_handler.py` | Move to `tools/excel_handlers/` or `shared/excel_handlers/` | Make dependency clear |
| `docs/reports/` (72+ files) | Move to `docs/archive/reports/` | Reduce noise |
| `docs/Claude_Design/` | Move to `docs/archive/design_prompts/` | Internal artifacts |
| `.gitignore` | Remove `test_*.py` pattern, add specific exclusions | Allow test files |
| `.env.example` | Add missing keys (JWT_SECRET_KEY, PORT, feature flags) | Completeness |

### Files to Delete

| File | Reason |
|------|--------|
| `static_gis.tar.gz` | Binary in repo, redundant with `static_gis/` |
| `web/app.js.backup` | Backup file |
| `web/app_origin.js` | Old version |
| `stitch_emissionagent_desktop_dashboard (7)/` | One-off artifact |
| `prompt.md` | Unused root-level design prompt |
| `CLEANUP_PLAN.md` | Already gitignored, should not be tracked |
| `skills/macro_emission/data/*.csv` | Duplicates of `calculators/data/macro_emission/` |
| `skills/micro_emission/data/*.csv` | Duplicates of `calculators/data/micro_emission/` |

### Files Needing Manual Confirmation Before Action

| File/Directory | Status | Action Needed |
|----------------|--------|---------------|
| `skills/macro_emission/skill.py` | Likely deprecated | Confirm no active code path calls it |
| `skills/micro_emission/skill.py` | Likely deprecated | Confirm no active code path calls it |
| `skills/knowledge/skill.py` | Likely deprecated | Confirm `tools/knowledge.py` replaces it |
| `skills/registry.py` | Likely deprecated | Confirm nothing imports `skills.registry.init_skills()` |
| `llm/data_collector.py` | Status unclear | Check if actively used |
| `web/diagnostic.html` | Debug page | Decide if needed in production |
| `shared/standardizer/` | Active but underused | Check if local standardizer path is tested |

---

## Appendix: Suggested Immediate Actions

The following is a prioritized checklist of the 10 most important immediate actions:

- [ ] **1. Fix JWT secret key** -- Move `SECRET_KEY` in `api/auth.py` to an environment variable (`JWT_SECRET_KEY`), update `.env.example`, and set a strong random key in production `.env`.

- [ ] **2. Add LICENSE file** -- Create `LICENSE` at repository root with MIT license text (as stated in README).

- [ ] **3. Remove `.gitignore` test exclusion** -- Delete the `test_*.py` and `*_test.py` lines from `.gitignore`. Add `scripts/utils/test_*.py` as a specific exclusion if those shouldn't be tracked.

- [ ] **4. Delete repository artifacts** -- Remove `static_gis.tar.gz`, `stitch_emissionagent_desktop_dashboard (7)/`, `web/app.js.backup`, `web/app_origin.js`, and `prompt.md` (or move to docs/).

- [ ] **5. Remove debug statements from production code** -- Clean up `sys.stdout.write` debug prints and `[DEBUG]` logger statements in `api/routes.py`.

- [ ] **6. Add `pyproject.toml`** -- Create a minimal `pyproject.toml` with `[project]` metadata, `[tool.pytest.ini_options]`, and `[tool.ruff]` configuration.

- [ ] **7. Write 3 basic test files** -- Create `tests/test_calculators.py` (test emission calculations with known inputs/outputs), `tests/test_standardizer.py` (test vehicle/pollutant mapping), `tests/test_config.py` (test config loading). These require zero LLM API calls.

- [ ] **8. Add CI test step** -- Add a `test` job in `.github/workflows/deploy.yml` that runs `pytest tests/` before the deploy step, or gate deploy on test success.

- [ ] **9. Consolidate LLM clients** -- Merge `llm/client.py` into `services/llm_client.py` (or have `llm/client.py` re-export from services). Update `tools/micro_emission.py` and `tools/macro_emission.py` imports.

- [ ] **10. Archive old documentation** -- Move `docs/reports/` (72+ files) and `docs/Claude_Design/` to `docs/archive/`, then create a fresh, authoritative `docs/ARCHITECTURE.md` based on the actual current code.
