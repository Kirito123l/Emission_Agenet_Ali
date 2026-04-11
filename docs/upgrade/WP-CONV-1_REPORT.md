# WP-CONV-1 Execution Report

> Scope executed: Phase 0 baseline + WP-CONV-1 only.  
> Scope intentionally not executed: WP-CONV-2 conversational fast path, WP-CONV-3 layered memory, WP-CONV-4 retry/cleanup/polish.  
> Dirty-tree rule: existing unrelated modifications were preserved; no broad checkout/formatting was used.

---

## 1. Phase 0 Baseline

### Baseline artifact

- `docs/upgrade/WP-CONV-1_BASELINE.md`

### Baseline commands

| Command | Result |
|---|---|
| `python main.py health` | Passed; 9 tools OK |
| `python main.py tools-list` | Passed; 9 tools listed |
| `pytest -q tests/test_router_state_loop.py tests/test_assembler_skill_injection.py tests/test_router_contracts.py tests/test_session_persistence.py tests/test_config.py` | Passed: 98 passed, 8 warnings |

### Dirty working tree handling

Current worktree already contained unrelated modified/untracked files before WP-CONV-1. The baseline snapshot records status and diffs for WP-CONV-1 touch files. During implementation, changes were limited to the WP-CONV-1 files listed below plus new targeted tests/report files.

---

## 2. Completed WP-CONV-1 Subitems

### 2.1 Router model config fix

#### Goal

Remove the router-level hardcoded `qwen-plus` override so the agent model is resolved from configured `AGENT_LLM_MODEL` / config defaults.

#### Implementation

- `core/router.py`
  - Changed `get_llm_client("agent", model="qwen-plus")` to `get_llm_client("agent")`.
  - Added init-time model logging.
- `config.py`
  - Updated agent and synthesis fallback model defaults to `qwen3-max`.
  - Preserved existing unrelated parameter-negotiation default change already present in the dirty tree.
- `.env.example`
  - Updated `AGENT_LLM_MODEL=qwen3-max`.
  - Updated `SYNTHESIS_LLM_MODEL=qwen3-max`.
  - Preserved existing unrelated parameter-negotiation example change already present in the dirty tree.
- `tests/test_router_llm_config.py`
  - Added regression test proving router calls `get_llm_client("agent")` without a model override.

#### Targeted verification

```bash
pytest -q tests/test_router_llm_config.py tests/test_config.py
```

Result: Passed, 10 passed, 8 warnings.

#### Rollback point

Revert the router constructor call and associated model-default/example changes. This rollback is narrow but not recommended unless runtime model compatibility requires it.

---

### 2.2 Synthesis payload stripping

#### Goal

Prevent large spatial/tool payloads from being JSON-injected into synthesis prompts while preserving original tool results for frontend, context store, downloads, and downstream tool reuse.

#### Implementation

- `core/router_render_utils.py`
  - Added recursive copy-only synthesis stripper.
  - Heavy keys stripped include raster grids, concentration grids, contours, GeoJSON/features, map data, receptor maps, and similar large spatial payloads.
  - Long lists are previewed with omitted count.
  - Non-mutating behavior is covered by test.
- `tests/test_router_contracts.py`
  - Added regression test for heavy payload stripping without mutating original payload.

#### Targeted verification

```bash
pytest -q tests/test_router_contracts.py
```

Result: Passed, 19 passed.

#### Rollback point

Revert the helper functions and the `else` branch in `filter_results_for_synthesis()` to pass through full `data` again. Frontend behavior should not need rollback because original payloads are not mutated.

---

### 2.3 FileContext column cap

#### Goal

Bound file-column prompt expansion for wide tables while preserving essential file context.

#### Implementation

- `core/assembler.py`
  - Added `MAX_FILE_CONTEXT_COLUMNS_CHARS` and `MAX_FILE_CONTEXT_COLUMNS` caps.
  - `_format_file_context()` now renders a bounded column preview plus omitted-count marker.
- `tests/test_assembler_skill_injection.py`
  - Added wide-table regression test.

#### Targeted verification

```bash
pytest -q tests/test_assembler_skill_injection.py
```

Result: Passed, 13 passed.

#### Rollback point

Revert `_format_file_context()` to full column join if a downstream consumer unexpectedly depends on full column list in prompt. Prefer adjusting cap over full rollback.

---

### 2.4 Token telemetry

#### Goal

Record API token usage from async LLM calls for future context/cost decisions.

#### Implementation

- `services/llm_client.py`
  - Added optional `usage` field to `LLMResponse`.
  - Added usage extraction for dict-like and attribute-like OpenAI-compatible responses.
  - Logs `[TOKEN_TELEMETRY]` for `chat`, `chat_with_tools`, and `chat_json` when provider usage is present.
- `tests/test_llm_client_telemetry.py`
  - Added fake-response tests for `chat()` usage return/logging and `chat_json()` logging without changing return value.

#### Targeted verification

```bash
pytest -q tests/test_llm_client_telemetry.py
```

Result: Passed, 2 passed.

#### Rollback point

Remove optional usage field and telemetry helpers/log calls. Existing code constructing `LLMResponse` remains compatible because the field is optional.

---

### 2.5 Live router state persistence

#### Goal

Persist restart-sensitive live workflow state so parameter negotiation, input completion, and residual continuation can survive session reloads.

#### Implementation

- `config.py`
  - Added `enable_live_state_persistence` flag from `ENABLE_LIVE_STATE_PERSISTENCE`, default true.
- `.env.example`
  - Added `ENABLE_LIVE_STATE_PERSISTENCE=true`.
- `core/router.py`
  - Added versioned `to_persisted_state()` envelope.
  - Added tolerant `restore_persisted_state()` accepting legacy context-store-only payloads.
  - Added JSON-safe serialization helper for live bundles.
- `api/session.py`
  - `save_router_state()` now writes versioned state when flag is enabled.
  - `_restore_router_state()` now delegates to router tolerant restore when enabled.
  - Legacy context-store restore remains as fallback.
- `tests/test_session_persistence.py`
  - Added live state reload regression test for parameter negotiation, input completion overrides, and continuation summary.
- `tests/test_config.py`
  - Added default flag assertion.

#### Targeted verification

```bash
pytest -q tests/test_session_persistence.py tests/test_config.py
```

Result: Passed, 11 passed, 8 warnings.

#### Rollback point

Set `ENABLE_LIVE_STATE_PERSISTENCE=false` to fall back to legacy context-store-only persistence, or revert the `api/session.py` delegation and router persistence methods.

---

## 3. Final WP-CONV-1 Verification

| Command | Result |
|---|---|
| `pytest -q tests/test_router_llm_config.py tests/test_llm_client_telemetry.py tests/test_router_state_loop.py tests/test_assembler_skill_injection.py tests/test_router_contracts.py tests/test_session_persistence.py tests/test_config.py` | Passed: 104 passed, 8 warnings |
| `pytest -q tests/test_phase1b_consolidation.py` | Passed: 5 passed, 1 warning |
| `python -m py_compile core/router.py core/assembler.py core/router_render_utils.py services/llm_client.py api/session.py config.py` | Passed |
| `python main.py health` | Passed; 9 tools OK |
| `python main.py tools-list` | Passed; 9 tools listed |

Warnings observed were existing deprecation/import warnings, not WP-CONV-1 assertion failures.

---

## 4. Modified Files

### WP-CONV-1 implementation files

- `.env.example`
- `api/session.py`
- `config.py`
- `core/assembler.py`
- `core/router.py`
- `core/router_render_utils.py`
- `services/llm_client.py`

### WP-CONV-1 tests

- `tests/test_assembler_skill_injection.py`
- `tests/test_config.py`
- `tests/test_router_contracts.py`
- `tests/test_session_persistence.py`
- `tests/test_llm_client_telemetry.py`
- `tests/test_router_llm_config.py`

### WP-CONV-1 documentation / baseline artifacts

- `docs/upgrade/WP-CONV-1_BASELINE.md`
- `docs/upgrade/WP-CONV-1_REPORT.md`

### Pre-existing unrelated dirty files preserved

The worktree still contains unrelated modified/untracked files outside the WP-CONV-1 scope, including evaluation files, cross-constraint/standardization files, file analyzer tests/tools, audit documents, and other repository artifacts. They were not intentionally changed for WP-CONV-1.

---

## 5. Remaining Risks

1. **Dirty tree remains broad**: before WP-CONV-2, isolate or review WP-CONV-1 diffs to avoid mixing with unrelated work.
2. **Model behavior changes**: router now honors configured `AGENT_LLM_MODEL`; runtime LLM behavior may differ from previous hardcoded `qwen-plus`.
3. **Live state JSON safety**: current persistence is tolerant and JSON-safe, but future non-dict live-state objects may need typed restoration.
4. **Synthesis stripping thresholds**: current stripping is conservative for heavy keys and long lists; real macro→dispersion→hotspot telemetry should be reviewed after live runs.

---

## 6. Recommendation for WP-CONV-2

WP-CONV-1 targeted verification passed. It is reasonable to proceed to WP-CONV-2 **after** reviewing/staging the WP-CONV-1 diff separately from unrelated dirty-tree changes. WP-CONV-2 should start with classifier tests and keep `ENABLE_CONVERSATION_FAST_PATH` as the rollback gate.
