# Context Snapshot: EmissionAgent Conversation Upgrade Ralplan

## Task statement
Read `EMISSIONAGENT_CONVERSATION_UPGRADE_PLAN.md`, inspect the current repository, map the four upgrade phases to the real codebase, identify dependencies and risks, and produce a staged execution plan plus validation strategy before making any code changes.

## Desired outcome
A deliberate, consensus-reviewed staged implementation plan that maps each phase to concrete modules/tests in this repository and defines validation evidence needed before execution.

## Known facts / evidence
- `omx explore` was attempted first for read-only lookup but failed because cargo/prebuilt explore harness was unavailable; normal shell inspection was used as fallback.
- Upgrade document has four phases: foundation fixes, conversation intent router, layered memory, and polishing/reliability.
- Main router is `core/router.py`; constructor currently initializes `self.llm = get_llm_client("agent", model="qwen-plus")` and `_run_state_loop()` starts at line ~1362.
- Context assembly is `core/assembler.py`; `_format_file_context()` joins all columns and does not use `max_tokens` to bound column payload.
- Synthesis payload filtering is `core/router_render_utils.py::filter_results_for_synthesis()` and currently passes full `data` for non emission/query/analyze_file tools.
- Memory is `core/memory.py::MemoryManager`; it keeps working memory, fact memory, and a string `compressed_memory`, but `get_working_memory()` returns only user/assistant and compressed memory is not injected by assembler.
- Session-scoped result memory is `core/context_store.py::SessionContextStore`, with compact `get_context_summary()` capped at 500 chars.
- Async LLM client is `services/llm_client.py`; `chat()` and `chat_with_tools()` return `LLMResponse` without usage telemetry fields.
- Session persistence is `api/session.py`; router state currently persists only `context_store`.
- Tests exist under `tests/`, especially `tests/test_router_state_loop.py`, `tests/test_assembler_skill_injection.py`, `tests/test_context_store*.py`, and `tests/test_session_persistence.py`.
- Git working tree already has unrelated modified/untracked files; planning must avoid changing production code.

## Constraints
- Planning-only workflow: no code changes until execution plan is approved in a later mode.
- Preserve existing behavior and minimize invasive changes.
- No new dependencies without explicit request.
- Must validate both CLI/API paths for tool-related changes where applicable.
- Follow repository style: Python 3, type hints on changed/new functions, small async tool methods, minimal web changes.

## Unknowns / open questions
- Whether `qwen3-max` should be enforced by config default, environment variable, or both; current `config.py` default still shows `qwen-plus`.
- Exact production latency and token telemetry baselines require runtime API calls with valid QWEN credentials.
- Whether the plan should evolve current `MemoryManager` in place or introduce a new `LayeredMemory` class behind the same API to limit router churn.
- Whether conversational fast-path should be enabled by default or guarded by a feature flag for rollback.

## Likely codebase touchpoints
- `core/router.py`
- `core/assembler.py`
- `core/memory.py` (or a new `core/conversation_memory.py`/`core/memory_v2.py`)
- `core/router_render_utils.py`
- `core/router_synthesis_utils.py`
- `services/llm_client.py`
- `config.py`, `.env.example`
- `api/session.py`
- Tests: `tests/test_router_state_loop.py`, `tests/test_assembler_skill_injection.py`, `tests/test_session_persistence.py`, new tests for conversation intent and payload stripping.
