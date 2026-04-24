# EmissionAgent Codebase Post-Cleanup Status

**Generated date**: 2026-04-24  
**Current branch**: `main`  
**Current HEAD**: `22c6518`  
**Cleanup scope**: Phase 2 preparation cleanup only; no Phase 2 feature development.

## 1. Executive Summary

- Phase 2 preparation cleanup completed in 5 bounded rounds.
- Root-level accidental files `=0.8.1` and `=1.6.0` were deleted.
- Root-level runtime logs `tmux-client-5419.log`, `tmux-out-5421.log`, and `tmux-server-5421.log` were removed.
- Root-level one-off scripts and the code review snapshot were archived into `scripts/` and `docs/archive/code_review_snapshots/`.
- Root-level held-out benchmark snapshot files were archived into `docs/archive/benchmark_snapshots/`; the benchmark source of truth remains `evaluation/benchmarks/held_out_tasks.jsonl`.
- 25 legacy root Markdown reports were moved into `docs/archive/legacy_reports/`.
- The tracked local-tool backup directory `.omx_backup_20260412_112249/` was deleted.
- The main code/runtime directories were not modified by cleanup.
- `docs/codebase_audit_phase2_prep.md` remains the factual baseline for Phase 2 planning.
- Misleading flags, the dependency contract stub, and Phase 2 migration work were intentionally not handled during cleanup and remain Phase 2 tasks.

## 2. Cleanup Commits

| Round | Commit | Scope | Action |
|---|---|---|---|
| Round 1 | `473e91c` | root accidental files and tmux logs | delete |
| Round 2 | `cb90aaf` | root dev scripts and review snapshot | archive/move |
| Round 3 | `e4095c8` | root held-out benchmark snapshots | archive/move |
| Round 4 | `a7bfa17` | legacy root Markdown reports | archive/move |
| Round 5 | `22c6518` | tracked omx backup logs | delete |

## 3. Repository Structure After Cleanup

Current top-level command outputs at generation time:

- Root-level files: `33`
- Root-level directories: `31` using the requested `find` command
- Tracked files: `1084`

### Active code / runtime directories

- `core/`
- `tools/`
- `services/`
- `api/`
- `config/`
- `evaluation/`
- `web/`
- `tests/`
- `data/`
- `GIS文件/`
- `LOCAL_STANDARDIZER_MODEL/`
- `ps-xgb-aermod-rline-surrogate/`
- `static_gis/`

### Documentation

- `docs/`
- Root-level retained planning/research docs:
  - `EMISSIONAGENT_CONVERSATION_UPGRADE_PLAN.md`
  - `MULTI_TURN_DIAGNOSTIC.md`
  - `PHASE1_5_REPORT.md`
  - `PHASE2_4_GATE1_DIAGNOSIS.md`
  - `PHASE2_SLOT_ANALYSIS.md`
  - `paper_notes.md`

### Archived materials

- `docs/archive/legacy_reports/`
  - Contains `25` archived root-level legacy Markdown reports.
- `docs/archive/benchmark_snapshots/`
  - Contains `held_out_batch1.jsonl`
  - Contains `held_out_batch1_v2.jsonl`
- `docs/archive/code_review_snapshots/`
  - Contains archived `tmp_for_chatgpt_code_review/` snapshot.

### Dev / utility scripts

- `scripts/diagnostics/`
- `scripts/dev/`
- `scripts/verify/`

### Other top-level support directories still present

- `.claude/`
- `.github/`
- `.omx/`
- `.pytest_cache/`
- `__pycache__/`
- `calculators/`
- `deploy/`
- `examples/`
- `llm/`
- `logs/`
- `outputs/`
- `scripts/`
- `shared/`
- `skills/`
- `test/`
- `test_data/`

## 4. Deleted Items

### 4.1 Root accidental files

- `=0.8.1`
- `=1.6.0`

Deletion rationale: clearly accidental root-level abnormal files with no active reference.

### 4.2 Runtime logs

- `tmux-client-5419.log`
- `tmux-out-5421.log`
- `tmux-server-5421.log`

Deletion rationale: untracked/ignored runtime logs.

### 4.3 OMX backup directory

- `.omx_backup_20260412_112249/`

Deletion rationale: tracked local-tool backup/log directory, approximately `16M`, containing `35` tracked files and no active `core/`, `tools/`, `services/`, `api/`, `config/`, `tests/`, `evaluation/`, `.github/`, or `scripts/` reference.

## 5. Archived / Moved Items

### 5.1 Code review snapshot

- `tmp_for_chatgpt_code_review/`
  - -> `docs/archive/code_review_snapshots/tmp_for_chatgpt_code_review/`

This was a committed review snapshot, not an active code path.

### 5.2 Root dev / diagnostic scripts

- `diagnose_hotspot_perf.py`
  - -> `scripts/diagnostics/diagnose_hotspot_perf.py`
- `simulate_e2e.py`
  - -> `scripts/dev/simulate_e2e.py`
- `verify_dispersion_fix.py`
  - -> `scripts/verify/verify_dispersion_fix.py`
- `verify_map_data_collection.py`
  - -> `scripts/verify/verify_map_data_collection.py`

These were one-off diagnostic or verification scripts moved out of the repository root into `scripts/` subdirectories.

### 5.3 Held-out benchmark snapshots

- `held_out_batch1.jsonl`
  - -> `docs/archive/benchmark_snapshots/held_out_batch1.jsonl`
- `held_out_batch1_v2.jsonl`
  - -> `docs/archive/benchmark_snapshots/held_out_batch1_v2.jsonl`

These are archived benchmark snapshots, not the current benchmark source of truth. The active benchmark file remains `evaluation/benchmarks/held_out_tasks.jsonl`.

### 5.4 Legacy root reports

The following `25` root-level Markdown reports were moved into `docs/archive/legacy_reports/`:

- `ARCHITECTURE_AUDIT_EMISSION_AGENT.md`
- `BENCHMARK_PIPELINE_DIAGNOSTIC.md`
- `BENCHMARK_PIPELINE_EXPLORATION.md`
- `BENCHMARK_PIPELINE_WORK_SUMMARY.md`
- `CALCULATE_DISPERSION_IMPLEMENTATION_ANALYSIS.md`
- `CODEBASE_AUDIT_FOR_PAPER.md`
- `DEEP_DIVE_1_STANDARDIZATION.md`
- `DEEP_DIVE_2_TOOLS_AND_WORKFLOW.md`
- `DEEP_DIVE_3_STATE_TRACE_CONFIG.md`
- `EVAL_MULTISTEP_DIAGNOSTIC.md`
- `EXPLORATION_FOR_UPGRADE_DECISION.md`
- `EXPLORATION_ROUND2.md`
- `EXPLORATION_ROUND3_COGNITIVE_FLOW.md`
- `PHASE0_REPORT.md`
- `PHASE1_55_REPORT.md`
- `PHASE1_5_DIAGNOSIS.md`
- `PHASE1_6_REPORT.md`
- `PHASE1_7_DIAGNOSIS.md`
- `PHASE1_7_REPORT.md`
- `PHASE1_DIAGNOSIS.md`
- `PHASE1_REPORT.md`
- `PHASE2R_WAVE1_REPORT.md`
- `PHASE2_BASELINE.md`
- `PHASE2_REPORT.md`
- `目录文件详细说明.md`

## 6. Root-Level Files Intentionally Retained

- `EMISSIONAGENT_CONVERSATION_UPGRADE_PLAN.md`
  - Retained because it is the closest in-repo local Phase 2 upgrade plan document.
- `MULTI_TURN_DIAGNOSTIC.md`
  - Retained because it still has direct Phase 2 diagnostic reference value.
- `PHASE1_5_REPORT.md`
  - Retained because `evaluation/run_phase1_5_benchmark.py` still hardcodes this file.
- `PHASE2_4_GATE1_DIAGNOSIS.md`
  - Retained because it still directly supports the Phase 2 gate context.
- `PHASE2_SLOT_ANALYSIS.md`
  - Retained because `core/contracts/dependency_contract.py` still points to it.
- `paper_notes.md`
  - Retained because it is an author research note and should not be archived without explicit review.

## 7. Items Deliberately Not Changed

- `core/` untouched by cleanup.
- `tools/` untouched by cleanup.
- `services/` untouched by cleanup.
- `api/` untouched by cleanup.
- `config/` untouched by cleanup.
- `tests/` untouched by cleanup.
- `evaluation/benchmarks/held_out_tasks.jsonl` untouched by cleanup.
- `docs/codebase_audit_phase2_prep.md` untouched and still the factual baseline for Phase 2.
- `.env.example` untouched by cleanup.
- `config.py` untouched by cleanup.
- `core/contracts/dependency_contract.py` untouched by cleanup.

## 8. Known Issues Left for Phase 2

- `ENABLE_STANDARDIZATION_CACHE` remains a misleading flag with no runtime reader.
- `ENABLE_DEPENDENCY_CONTRACT` remains a misleading flag tied to a no-op/stub contract.
- `core/contracts/dependency_contract.py` remains a stub and should be handled by the planned Phase 2 Task Pack E/F-main work.
- `.env.example` and `config.py` flag drift was not normalized during cleanup.
- Production-path migration to `GovernedRouter` was not performed during cleanup.
- YAML merge, constraint writer, data quality, reply parser, and hardcoding cleanup were not performed during cleanup.

## 9. Validation Performed

- Start-of-round `git status --short` was clean before each cleanup/documentation step.
- Root paths removed or archived in Cleanup Rounds 1-5 were explicitly verified.
- Retained root-level docs were explicitly verified after report cleanup.
- JSONL archive files parsed successfully in Cleanup Round 3.
- `python3 -m compileall scripts/diagnostics scripts/dev scripts/verify` passed in Cleanup Round 2.
- Active reference checks were performed before each move or delete.
- No tests were run in document/archive-only rounds unless explicitly stated.

## 10. Current Workspace State

- Branch: `main`
- Current HEAD at document generation time: `22c6518`
- `git status --short`: clean at generation time
- Final cleanup commit chain:
  - `473e91c` -> `cb90aaf` -> `e4095c8` -> `a7bfa17` -> `22c6518`
- Next recommended step: proceed to Phase 2 using this document together with `docs/codebase_audit_phase2_prep.md`.

## 11. Notes for the Next Claude Conversation

- Cleanup is complete.
- Do not re-run cleanup unless new junk appears.
- Use this post-cleanup status document together with `docs/codebase_audit_phase2_prep.md` as the handoff baseline.
- Phase 2 should begin with the planned precondition: F-bugfix for `restore_persisted_state`, then F-main migration.
- No Phase 2 code changes were made during cleanup.
