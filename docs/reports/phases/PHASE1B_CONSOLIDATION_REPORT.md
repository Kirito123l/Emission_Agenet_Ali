# Phase 1B Consolidation Report

**Date:** 2026-03-14  
**Scope:** Conservative Phase 1B cleanup of LLM client boundaries and `skills/` vs `tools/` usage  
**Method:** Repository-first verification, then low-risk clarifications and compatibility fixes

## Executive Summary

This round clarified the repository's two real LLM client paths without forcing a risky merge:

- `llm/client.py` remains the canonical **synchronous** client path for standardizers, column-mapping helpers, and knowledge-answer refinement.
- `services/llm_client.py` remains the canonical **async/tool-calling** client path for `core/router.py`.

The main consolidation change was making the async client's `purpose` argument real instead of documentary only. `get_llm_client("synthesis")` and similar calls now resolve the correct configured assignment, while the current router behavior for `purpose="agent"` stays unchanged.

This round also clarified the current `skills/` boundary:

- `tools/` is the active runtime surface.
- `skills/knowledge/skill.py` and the micro/macro `excel_handler.py` files are still active through tool wrappers.
- direct legacy skill entry points remain on disk for compatibility, but are not part of the active router/executor path.

Intentionally unchanged:

- no broad router/executor refactor
- no mass deletion of legacy `skills/`
- no migration of Excel handlers out of `skills/`
- no attempt to merge the two LLM clients into one implementation

## Phase 1B Status Verification

### What had already been changed before takeover

Verified from the real on-disk diff:

- `llm/client.py` already had a new module docstring clarifying it as the canonical synchronous LLM path.
- `services/llm_client.py` already had a new module docstring clarifying it as the canonical async/tool-calling path.
- `llm/__init__.py` already had a new package docstring clarifying the intended boundary.

No saved Phase 1B cleanup edits were present yet in:

- `skills/`
- `tools/`
- legacy registry compatibility paths

### What was verified against the actual codebase

Confirmed:

- `llm/client.py` is a synchronous client used by:
  - `shared/standardizer/vehicle.py`
  - `shared/standardizer/pollutant.py`
  - `tools/micro_emission.py`
  - `tools/macro_emission.py`
  - `skills/knowledge/skill.py`
  - legacy direct skill modules
- `services/llm_client.py` is the async/tool-calling client used by `core/router.py`.
- `skills/micro_emission/excel_handler.py` is actively imported by `tools/micro_emission.py` and `evaluation/eval_file_grounding.py`.
- `skills/macro_emission/excel_handler.py` is actively imported by `tools/macro_emission.py` and `evaluation/eval_file_grounding.py`.
- `skills/knowledge/skill.py` is actively wrapped by `tools/knowledge.py`.
- `skills/registry.py` is only imported inside `scripts/deprecated/diagnose_agent.py`.

Additional on-disk finding not captured in the prior notes:

- `skills/micro_emission/skill.py` had a stale import from a non-existent `.calculator` module and was not actually import-stable until this round fixed it.

### Whether prior partial edits were valid or incomplete

The prior partial edits were **valid but incomplete**.

Valid:

- the LLM boundary docstrings were already saved
- the reported `skills -> tools` transitional imports were real

Incomplete:

- the async LLM client's `purpose` parameter was still not wired to purpose-specific assignments
- `skills/registry.py` still hard-imported stale or missing legacy modules
- the direct micro skill import path was stale on disk

## LLM Client Audit

### Files inspected

- `llm/client.py`
- `llm/__init__.py`
- `services/llm_client.py`
- `core/router.py`
- `shared/standardizer/vehicle.py`
- `shared/standardizer/pollutant.py`
- `tools/micro_emission.py`
- `tools/macro_emission.py`
- `skills/knowledge/skill.py`

### Overlap found

Both LLM client implementations currently include:

- OpenAI-compatible client setup
- proxy/direct failover handling
- sync chat-style methods

`llm/client.py` uniquely provides:

- purpose-based assignment routing
- tolerant JSON parsing helpers
- sync-oriented usage patterns

`services/llm_client.py` uniquely provides:

- async chat APIs
- tool-calling support
- `ToolCall` and `LLMResponse` dataclasses

### Canonical path selected

- Canonical synchronous LLM path: `llm.get_llm(...)` / `llm/client.py`
- Canonical async/tool-calling LLM path: `services.llm_client.get_llm_client(...)` / `services/llm_client.py`

### Compatibility strategy

- Kept both client modules in place.
- Re-exported the sync client API from `llm/__init__.py`.
- Added cache reset helpers for tests/runtime overrides.
- Made async `purpose` routing real while preserving explicit model overrides.

### What changed vs what was deferred

Changed:

- `services/llm_client.py` now resolves config assignments by `purpose`
- `llm/__init__.py` now exposes the canonical sync compatibility surface
- small cache-reset helpers were added to both LLM client modules

Deferred:

- extracting shared failover logic into a common base/helper
- merging the two clients
- changing `core/router.py` synthesis to instantiate a separate `purpose="synthesis"` async client
- changing tool-side column mapping to use a different sync `purpose`

## Skills vs Tools Audit

### Files and modules reviewed

- `tools/registry.py`
- `tools/micro_emission.py`
- `tools/macro_emission.py`
- `tools/knowledge.py`
- `skills/__init__.py`
- `skills/base.py`
- `skills/registry.py`
- `skills/knowledge/skill.py`
- `skills/knowledge/retriever.py`
- `skills/knowledge/reranker.py`
- `skills/micro_emission/__init__.py`
- `skills/micro_emission/skill.py`
- `skills/micro_emission/excel_handler.py`
- `skills/macro_emission/__init__.py`
- `skills/macro_emission/skill.py`
- `skills/macro_emission/excel_handler.py`
- `evaluation/eval_file_grounding.py`
- `scripts/deprecated/diagnose_agent.py`

### Classification

#### Active

| Module | Why |
|---|---|
| `tools/registry.py` | active runtime registration path |
| `tools/micro_emission.py` | active tool invoked through executor |
| `tools/macro_emission.py` | active tool invoked through executor |
| `tools/knowledge.py` | active tool invoked through executor |
| `skills/knowledge/skill.py` | directly wrapped by `tools/knowledge.py` |
| `skills/knowledge/retriever.py` | used by active knowledge skill |
| `skills/knowledge/reranker.py` | used by active knowledge skill |

#### Active but transitional

| Module | Why |
|---|---|
| `skills/micro_emission/excel_handler.py` | still imported by active tool and evaluation code |
| `skills/macro_emission/excel_handler.py` | still imported by active tool and evaluation code |
| `skills/__init__.py` | package still represents surviving compatibility surfaces |
| `skills/base.py` | shared base types still used by the remaining direct skill modules |

#### Likely deprecated

| Module | Why |
|---|---|
| `skills/registry.py` | only referenced by `scripts/deprecated/diagnose_agent.py` |
| `skills/micro_emission/skill.py` | not used by active router/tool path; retained only for compatibility |
| `skills/macro_emission/skill.py` | not used by active router/tool path; retained only for compatibility |
| `skills/micro_emission/__init__.py` | compatibility import surface only |
| `skills/macro_emission/__init__.py` | compatibility import surface only |

#### Unclear / manual confirmation needed

| Module or concern | Why |
|---|---|
| Any out-of-repo callers of direct `skills.*.skill` imports | cannot be proven from this repository alone |
| Any external dependency on the missing `skills.emission_factors.skill` path | repository-local code no longer hard-fails, but the historical path is absent on disk |

## Concrete Changes Made

### `services/llm_client.py`

- Implemented real purpose-based assignment resolution.
- Preserved explicit model overrides.
- Added `self.purpose`, `self.assignment`, and `reset_llm_client_cache()`.
- Updated module docs to reflect the actual remaining boundary.

Why low-risk:

- current router already requests `purpose="agent"`, so existing behavior for the active path stays the same
- the public factory name stayed unchanged

### `llm/client.py`

- Stored the resolved `purpose` on each sync client.
- Added `reset_llm_manager()` for tests/runtime overrides.

Why low-risk:

- additive only
- no change to call signatures or request behavior

### `llm/__init__.py`

- Re-exported `LLMClient`, `LLMManager`, `get_llm`, and `reset_llm_manager`.

Why low-risk:

- additive compatibility surface
- no existing import path was removed

### `skills/__init__.py`

- Replaced the placeholder comment with a package docstring that explicitly marks `skills/` as transitional.

Why low-risk:

- documentation only

### `skills/registry.py`

- Converted direct hard imports into best-effort loading with warnings.
- Preserved `init_skills()` and `get_registry()` names.

Why low-risk:

- only deprecated scripts import this module in-repo
- old callers now get partial registration instead of immediate failure

### `skills/micro_emission/skill.py`

- Fixed the stale calculator import by pointing it at `calculators.micro_emission`.
- Added a compatibility docstring.

Why low-risk:

- this restores a broken legacy import path rather than changing the active runtime
- it matches the calculator module already used by the active tool

### `skills/micro_emission/__init__.py`

- Added an explicit compatibility docstring.
- Re-exported `MicroEmissionSkill` to make the package surface consistent with other skill packages.

Why low-risk:

- compatibility-only surface

### `tools/micro_emission.py`
### `tools/macro_emission.py`
### `tools/knowledge.py`

- Added compatibility notes explaining why `skills/` imports still exist.
- Added short comments on the transitional `skills.*` dependencies.

Why low-risk:

- documentation/comment changes only
- no runtime logic changed

## Tests Added or Updated

### Added

- `tests/test_phase1b_consolidation.py`

Coverage:

- sync canonical import path uses purpose-based assignment
- async service resolves assignment by purpose
- async factory defaults to the configured model for each purpose
- explicit async model override still works
- legacy `skills.micro_emission` import path remains available

### Verification run

- `pytest tests/test_phase1b_consolidation.py` -> 5 passed
- `pytest` -> 43 passed, 4 pre-existing FastAPI deprecation warnings
- manual smoke check:
  - `python -c "from skills.registry import init_skills, get_registry; init_skills(); print(sorted(get_registry()._skills.keys()))"`
  - observed warning for missing `skills.emission_factors.skill`
  - registry still loaded `calculate_macro_emission`, `calculate_micro_emission`, and `query_knowledge`

## What Was Intentionally NOT Changed

- `core/router.py` was not refactored
- router synthesis was not switched to a separate async `purpose="synthesis"` client
- duplicate failover code between the two LLM clients was not deduplicated
- `skills/*/excel_handler.py` files were not moved or renamed
- direct legacy skill modules were not deleted
- no compatibility wrapper was added for the missing `skills.emission_factors.skill` path
- `tools/*` still use `llm.client.get_llm("agent")` for column-mapping helper construction

## Remaining Risks / Follow-up Work

- The two LLM clients still duplicate failover logic and some client setup logic.
- `core/router.py` still uses a single async agent-scoped client for both routing and synthesis.
- `skills.emission_factors.skill` is still absent on disk; the registry now warns instead of crashing, but the legacy path is not restored.
- The micro and macro Excel handlers still live under `skills/`, so the directory boundary remains partially blurred.
- `skills/micro_emission/excel_handler.py` still contains debug stdout logging that should be cleaned later.
- Out-of-repo consumers of direct legacy skill imports are still unknown.

## Recommended Next Safe Step

Extract the still-active `skills/micro_emission/excel_handler.py` and `skills/macro_emission/excel_handler.py` logic into a shared or tool-local file-I/O module, then leave thin import-compatible shims in `skills/` until external callers are confirmed gone.

## Suggested Next Safe Actions

- [ ] Move the active Excel I/O helpers behind a `tools/` or shared compatibility module, keeping `skills/*/excel_handler.py` as shims first.
- [ ] Decide whether router synthesis should instantiate `get_llm_client("synthesis")` separately.
- [ ] Deduplicate shared failover/client bootstrap logic between `llm/client.py` and `services/llm_client.py`.
- [ ] Audit remaining consumers of `skills.registry` and remove the registry once no active callers remain.
- [ ] Decide whether to restore or formally retire the missing `skills.emission_factors.skill` import path.
