# Phase 1C Entry Points and Evaluation Report

**Date:** 2026-03-14  
**Scope:** Conservative Phase 1C / Phase 2-prep cleanup for run entry points and evaluation/reproducibility paths  
**Method:** Verify on-disk state first, then clarify and standardize only the smallest safe surfaces

## 1. Executive Summary

This round clarified two operational stories that were still too fragmented after Phase 0/1/1B:

- how to **run the project today**
- how to **perform a minimal meaningful evaluation/reproducibility pass**

What was improved:

- identified and documented the canonical run paths
- repaired specialized helper scripts that still mattered but were failing because of repo-path drift or stale imports
- added a single low-friction evaluation smoke wrapper as the recommended minimal reproducibility path
- added focused docs so a future contributor can find supported run/eval commands without digging through historical reports

What was intentionally left unchanged:

- no router or API redesign
- no broad docs cleanup across the entire `docs/` tree
- no evaluation methodology redesign
- no command system/Makefile overhaul
- no mass deletion of historical scripts

## 2. Current Run Entry Point Audit

### Files, scripts, and docs inspected

- `README.md`
- `run_api.py`
- `main.py`
- `api/main.py`
- `scripts/query_emission_factors_cli.py`
- `scripts/start_server.ps1`
- `scripts/restart_server.ps1`
- `scripts/migrate_from_mcp.py`
- `scripts/migrate_knowledge.py`
- `scripts/utils/test_new_architecture.py`
- `scripts/utils/test_api_integration.py`
- `scripts/utils/test_rag_integration.py`
- `scripts/utils/switch_standardizer.bat`
- `docs/guides/QUICKSTART.md`
- `docs/guides/WEB_STARTUP_GUIDE.md`
- `.github/workflows/deploy.yml`

### Classification of run paths

#### Canonical primary

| Entry point | Why |
|---|---|
| `python run_api.py` | primary supported local launcher for the integrated API + web UI surface |

#### Canonical secondary

| Entry point | Why |
|---|---|
| `python main.py chat` | supported interactive CLI path for debugging/development, but secondary to the API + web UI |

#### Active but specialized

| Entry point | Why |
|---|---|
| `python main.py health` | smallest local runtime validation |
| `python main.py tools-list` | tool inventory / debugging helper |
| `uvicorn api.main:app --host 0.0.0.0 --port 8000` | valid underlying app path, but `run_api.py` is preferred |
| `python scripts/query_emission_factors_cli.py` | one-tool CLI example; now repaired to use the active executor path |
| `python scripts/utils/test_rag_integration.py` | specialized knowledge-index / tool-registration smoke |
| `python scripts/utils/test_new_architecture.py` | specialized full architecture integration script; may require live LLM access |
| `python scripts/utils/test_api_integration.py` | specialized `api.session.Session` integration script; may require live LLM access |
| `scripts/start_server.ps1` / `scripts/restart_server.ps1` | Windows convenience wrappers around `python run_api.py` |
| `scripts/utils/switch_standardizer.bat` | Windows-only helper for toggling local standardizer modes |

#### Transitional / legacy

| Entry point | Why |
|---|---|
| `scripts/deprecated/` | historical diagnostics and one-off helpers |
| `scripts/migrate_from_mcp.py` | one-off migration helper from older sibling project |
| `scripts/migrate_knowledge.py` | one-off migration helper from older sibling project |
| `docs/guides/QUICKSTART.md` | historical Phase 7 startup guide; contains outdated assumptions |
| `docs/guides/WEB_STARTUP_GUIDE.md` | historical Phase 7 startup guide; contains outdated assumptions |

#### Unclear / manual confirmation needed

| Entry point or concern | Why |
|---|---|
| external service/unit-file launch commands behind the `emission-agent` systemd service referenced in deployment | the runtime service definition is not in this repository |
| any external/local-team wrappers around the current Python entry points | cannot be proven from repository-local code alone |

### Identified minimum runnable path

For a new developer:

1. `pip install -r requirements.txt`
2. `cp .env.example .env`
3. set at least one API key in `.env` for normal chat usage
4. `python run_api.py`
5. open `http://localhost:8000`

For the smallest pre-flight validation:

- `python main.py health`
- `pytest`

## 3. Evaluation / Reproducibility Audit

### Files, directories, and docs inspected

- `evaluation/__init__.py`
- `evaluation/utils.py`
- `evaluation/eval_normalization.py`
- `evaluation/eval_file_grounding.py`
- `evaluation/eval_end2end.py`
- `evaluation/eval_ablation.py`
- `evaluation/normalization/samples.jsonl`
- `evaluation/file_tasks/samples.jsonl`
- `evaluation/file_tasks/data/`
- `evaluation/end2end/samples.jsonl`
- `evaluation/human_compare/samples.csv`
- `evaluation/logs/_smoke_*`
- `README.md`

### Classification of evaluation paths

#### Canonical evaluation entry point

| Entry point | Why |
|---|---|
| `python evaluation/run_smoke_suite.py` | new canonical minimal reproducibility path that reuses existing evaluation modules with conservative defaults |
| `python evaluation/eval_normalization.py` | canonical task-specific runner for normalization |
| `python evaluation/eval_file_grounding.py` | canonical task-specific runner for file grounding |
| `python evaluation/eval_end2end.py` | canonical task-specific runner for end-to-end evaluation |

#### Smoke validation path

| Entry point | Why |
|---|---|
| `python evaluation/run_smoke_suite.py` | smallest meaningful benchmark pass; uses `tool` mode and `direct,fuzzy` macro mapping by default |

#### Benchmark / sample asset locations

| Location | Role |
|---|---|
| `evaluation/normalization/samples.jsonl` | executor-layer normalization benchmark samples |
| `evaluation/file_tasks/samples.jsonl` | file-grounding benchmark samples |
| `evaluation/end2end/samples.jsonl` | end-to-end benchmark samples |
| `evaluation/file_tasks/data/` | file-task fixtures used by file-grounding and some end-to-end cases |
| `evaluation/human_compare/samples.csv` | manual/future-facing comparison scaffold |
| `evaluation/logs/_smoke_*` | checked-in example smoke outputs, useful as references but not authoritative |

#### Partial / incomplete / future-facing paths

| Path | Why |
|---|---|
| `python evaluation/eval_ablation.py` | useful experiment matrix, but larger than the minimum reproducibility path |
| `evaluation/human_compare/samples.csv` | scaffold only; not a fully automated benchmark |
| `python evaluation/eval_end2end.py --mode router` | valid, but exercises more LLM-dependent behavior and is not the lowest-friction local validation path |

#### Unclear / manual confirmation needed

| Path or concern | Why |
|---|---|
| acceptance thresholds for “good enough” benchmark results | not codified in the current repo |
| which checked-in `evaluation/logs/_smoke_*` artifacts should be treated as the reference baseline | example outputs exist, but no authoritative baseline policy is documented |

### Identified minimum reproducible validation/evaluation path

Recommended minimal reproducibility path:

```bash
python evaluation/run_smoke_suite.py
```

Why this path:

- runs real evaluation code, not just unit tests
- uses current benchmark sample assets already in the repo
- stays in `tool` mode
- defaults to `direct,fuzzy` macro mapping to reduce dependency on the AI-only macro mapping stage
- writes a single `smoke_summary.json` plus per-task metrics/logs under `evaluation/logs/`

Verified during this round:

- `python evaluation/run_smoke_suite.py --output-dir evaluation/logs/_smoke_suite_verification` completed successfully
- the resulting metrics were written under `evaluation/logs/_smoke_suite_verification/`

## 4. Concrete Changes Made

### `RUNNING.md`

- Added a focused root-level run guide.
- Classified primary, secondary, specialized, and historical paths.
- Documented the minimum runnable path and the minimum local validation path.

Why low-risk:

- documentation only
- no runtime behavior changed

### `evaluation/README.md`

- Added a focused evaluation/reproducibility guide.
- Documented canonical evaluation entry points, sample locations, the new smoke path, and current limitations.

Why low-risk:

- documentation only
- no benchmark semantics changed

### `evaluation/run_smoke_suite.py`

- Added a small wrapper that runs normalization, file grounding, and end-to-end evaluation with conservative defaults.
- Made it executable via `python evaluation/run_smoke_suite.py`.

Why low-risk:

- reuses existing benchmark functions without changing their internals
- simply packages the recommended minimal reproducibility sequence

### `README.md`

- Added links to the new canonical run/evaluation docs.
- Updated the testing section to point to actual current commands.
- Added a minimal validation snippet.

Why low-risk:

- documentation only

### `run_api.py`
### `main.py`

- Added module docstrings clarifying each file's intended role in the supported entry-point surface.

Why low-risk:

- documentation only

### `scripts/query_emission_factors_cli.py`

- Repaired the script to use the active executor/standardization path instead of the removed `skills.emission_factors.skill` import.
- Added a docstring marking it as a specialized example, not a canonical launcher.

Why low-risk:

- preserved the script's purpose while aligning it with the current architecture
- avoided changing any core application flow

### `scripts/utils/test_new_architecture.py`
### `scripts/utils/test_api_integration.py`
### `scripts/utils/test_rag_integration.py`

- Added robust repo-root path setup so the scripts work from any current working directory.
- Clarified their intent in module docstrings.
- Fixed the RAG smoke script's knowledge-index path to the real repo location.

Why low-risk:

- import/bootstrap fixes only
- no architectural logic changed

### `docs/guides/QUICKSTART.md`
### `docs/guides/WEB_STARTUP_GUIDE.md`

- Added a short status banner marking them as historical and redirecting readers to `RUNNING.md`.

Why low-risk:

- documentation-only redirect
- avoids trying to fully modernize large historical guides in this round

### `evaluation/__init__.py`

- Updated the package docstring to describe the evaluation package as a current reproducibility/benchmark surface, not only a paper-oriented one.

Why low-risk:

- documentation only

## 5. Documentation Improvements

Added or updated:

- `RUNNING.md`
- `evaluation/README.md`
- `README.md`
- `docs/guides/QUICKSTART.md`
- `docs/guides/WEB_STARTUP_GUIDE.md`

Why this approach was chosen:

- the repo already has a very large docs surface, so adding one clear root-level run guide and one evaluation-specific guide was the smallest way to create real source-of-truth documents
- updating every historical report/guide would have been noisy and risky
- adding status banners to the two most obvious stale startup guides reduces confusion without a broad docs rewrite

## 6. Tests Added or Updated

### Added

- `tests/test_smoke_suite.py`

What it tests:

- the new smoke-suite wrapper writes a summary file
- the wrapper uses the intended defaults (`tool` mode and `direct,fuzzy` macro mapping)
- the wrapper calls the three benchmark runners with the expected parameters

Why this test was appropriate:

- it protects the only new logic introduced in this round
- it avoids running the full benchmark in unit tests by monkeypatching the underlying runners

### Verification performed

- `pytest` -> **44 passed**, 4 pre-existing FastAPI deprecation warnings
- `python main.py health` -> succeeded
- `python main.py tools-list` -> succeeded
- `python scripts/query_emission_factors_cli.py` -> succeeded after repair
- `python scripts/utils/test_rag_integration.py` -> succeeded after path fix
- `python -c "import runpy; runpy.run_path('scripts/utils/test_api_integration.py', run_name='__not_main__')"` -> import/bootstrap check succeeded
- `python -c "import runpy; runpy.run_path('scripts/utils/test_new_architecture.py', run_name='__not_main__')"` -> import/bootstrap check succeeded
- `python evaluation/run_smoke_suite.py --output-dir evaluation/logs/_smoke_suite_verification` -> succeeded

## 7. What Was Intentionally NOT Changed

- did not redesign `core/router.py`
- did not redesign `api/routes.py`
- did not change API behavior
- did not add a Makefile or new command system
- did not refactor the evaluation methodology or metrics
- did not delete historical scripts beyond classifying them
- did not attempt a broad cleanup of the entire `docs/` tree
- did not modify CI/CD in `.github/workflows/deploy.yml`

## 8. Remaining Risks / Follow-up Work

- The repository still has many historical docs/reports, so discoverability is improved but not fully solved.
- Some specialized integration scripts still require live LLM access and should not be mistaken for the smallest smoke checks.
- `evaluation/run_smoke_suite.py` works as a minimal benchmark wrapper, but benchmark quality thresholds are still undocumented.
- `evaluation/human_compare/samples.csv` is present but not yet integrated into an automated workflow.
- `scripts/utils/test_new_architecture.py` and `scripts/utils/test_api_integration.py` are still broad integration scripts rather than tightly controlled automated tests.
- `skills/micro_emission/excel_handler.py` still emits debug stdout during file reads, which showed up during smoke evaluation.

## 9. Recommended Next Safe Step

Create one small `CONTRIBUTING.md` or `DEVELOPMENT.md` that links only to the canonical living docs (`RUNNING.md`, `evaluation/README.md`, `docs/ARCHITECTURE.md`) and explicitly demotes the older report-style docs to historical/reference status.

## Suggested Next Safe Actions

- [ ] Add one small contributor-facing doc that links only to the canonical living run/eval/architecture guides.
- [ ] Decide whether to codify benchmark acceptance thresholds for normalization, file grounding, and end-to-end completion.
- [ ] Decide whether `evaluation/logs/_smoke_*` should remain checked-in examples or move to external/reference artifacts.
- [ ] Trim or suppress debug stdout in the micro Excel handler before relying on smoke-eval logs as cleaner reference artifacts.
- [ ] Review whether the specialized integration scripts should eventually move under `tests/` or remain manual smoke scripts.
