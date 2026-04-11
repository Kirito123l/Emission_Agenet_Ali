# WP-CONV-2 Execution Report

> Scope executed: WP-CONV-2 only (conservative conversation intent router).  
> Scope intentionally not executed: WP-CONV-3 layered memory, WP-CONV-4 retry/cleanup/polish.  
> Dirty-tree rule: existing unrelated modifications from earlier work and the pre-existing worktree were preserved.

---

## 1. Boundary Review Before WP-CONV-2

Before implementation, the WP-CONV-1 report and current dirty tree were reviewed to avoid overwriting unrelated changes.

### Confirmed WP-CONV-1 boundary

WP-CONV-1 had already modified:

- `.env.example`
- `api/session.py`
- `config.py`
- `core/assembler.py`
- `core/router.py`
- `core/router_render_utils.py`
- `services/llm_client.py`
- targeted WP-CONV-1 tests and docs

### WP-CONV-2 scope selected

WP-CONV-2 was limited to:

- `core/conversation_intent.py` (new classifier)
- `core/router.py` (fast-path integration only)
- `config.py` / `.env.example` (feature flag only)
- WP-CONV-2 tests
- WP-CONV-2 report

### Explicitly not touched for WP-CONV-2

- `core/memory.py`
- `api/session.py`
- `services/llm_client.py`
- `core/router_render_utils.py`
- `core/assembler.py`
- any WP-CONV-3/WP-CONV-4 implementation files

---

## 2. Implemented WP-CONV-2 Scope

### 2.1 Feature flag

Added conservative fast-path gate:

- `config.py` → `enable_conversation_fast_path`
- `.env.example` → `ENABLE_CONVERSATION_FAST_PATH=true`
- `tests/test_config.py` updated accordingly

This flag is the rollback switch for all WP-CONV-2 behavior.

---

### 2.2 Conservative classifier

Added new module:

- `core/conversation_intent.py`

Implemented:

- `ConversationIntent` enum
- `IntentResult` dataclass
- `ConversationIntentClassifier`

Supported classifications:

- `CHITCHAT`
- `EXPLAIN_RESULT`
- `KNOWLEDGE_QA`
- `NEW_TASK`
- `CONTINUE_TASK`
- `MODIFY_PARAMS`
- `RETRY`
- `UNDO`
- `CONFIRM`
- `UNKNOWN`

Design constraints actually enforced:

- rule-first classification only
- fast path only for high-confidence:
  - chitchat
  - explain-result
  - knowledge-QA
- output-mode / task-like requests are routed back to state loop
- confirmation-like replies are never fast-pathed
- active blockers disable fast path

Blocking signals enforced in classifier inputs:

- active parameter negotiation
- active input completion
- file relationship clarification
- residual workflow
- new file upload

---

### 2.3 Router integration

Integrated **only** in `UnifiedRouter.chat()` and **before** `_run_state_loop()`.

This matches the approved execution plan choice:

- fast-path decision happens immediately after `clear_current_turn()`
- if eligible, return fast-path response directly
- otherwise continue into existing `_run_state_loop()` unchanged

Reason for this integration point:

- avoid making pure chitchat / simple explanation / knowledge turns pay the cost of state-loop live state apply/restore, file relationship checks, and other task-routing prework
- keep all task-state machinery authoritative when fast path is not allowed

Implemented router helpers:

- lazy classifier initialization
- active residual-workflow detection
- bounded conversational history message builder
- conversational system prompt builder
- `_maybe_handle_conversation_fast_path()`

Fast-path handlers implemented conservatively:

- **Chitchat** → `llm.chat()` with bounded conversational history
- **Explain-result** → `llm.chat()` with bounded last-tool/context summary
- **Knowledge-QA** → existing `ToolExecutor.execute("query_knowledge", {"query": ...})`

The knowledge path does **not** bypass tool execution boundaries.

---

## 3. Guardrails Verified

WP-CONV-2 explicitly preserves the following paths by refusing fast-path routing when relevant:

1. active negotiation
2. active input completion
3. file relationship clarification
4. residual workflow / continuation
5. summary-delivery-like output-mode requests

### Summary delivery protection

A request such as “帮我可视化一下” is classified back to task/state-loop routing instead of explain/chitchat/knowledge fast path, so the existing summary-delivery and output-shift handling remains authoritative.

---

## 4. Tests Added / Updated

### New tests

- `tests/test_conversation_intent.py`

Coverage includes:

- chitchat fast path allowed
- explain-result fast path allowed when prior result exists
- knowledge-QA fast path allowed without task cues
- blockers disable fast path
- output-mode requests are routed back to state loop
- confirmation-like replies are not fast-pathed

### Updated tests

- `tests/test_router_state_loop.py`
  - chitchat fast path bypasses state loop
  - knowledge fast path uses tool executor
  - active negotiation blocks fast path
  - active input completion blocks fast path
  - file relationship clarification blocks fast path
  - residual workflow blocks fast path
  - summary-delivery-like request does not fast path
- `tests/test_config.py`
  - feature-flag default assertion updated

---

## 5. Verification Results

### Classifier-first verification

```bash
pytest -q tests/test_conversation_intent.py tests/test_config.py
```

Result: **17 passed**, 4 warnings

### Router integration verification

```bash
pytest -q tests/test_router_state_loop.py
```

Result: **65 passed**

### Final targeted verification

```bash
pytest -q tests/test_conversation_intent.py tests/test_router_state_loop.py tests/test_config.py tests/test_router_llm_config.py tests/test_phase1b_consolidation.py
python -m py_compile core/conversation_intent.py core/router.py config.py
```

Result:

- pytest: **88 passed**, 8 warnings
- py_compile: **passed**

Warnings were existing deprecation/import warnings, not WP-CONV-2 assertion failures.

---

## 6. Modified Files

### WP-CONV-2 implementation

- `.env.example`
- `config.py`
- `core/router.py`
- `core/conversation_intent.py`

### WP-CONV-2 tests

- `tests/test_config.py`
- `tests/test_router_state_loop.py`
- `tests/test_conversation_intent.py`

### WP-CONV-2 documentation

- `docs/upgrade/WP-CONV-2_REPORT.md`

---

## 7. What Was Intentionally Not Done

To keep WP-CONV-2 conservative and within scope, the following were intentionally deferred:

- no layered memory / `build_context_for_prompt()` work
- no `core/memory.py` expansion
- no retry/backoff logic
- no conversational prompt persistence enhancements
- no idle session cleanup
- no changes to `api/session.py`
- no changes to `services/llm_client.py`

---

## 8. Remaining Risks

1. **Fast path is intentionally narrow**: many borderline follow-up turns will still route to the state loop. This is expected for safety.
2. **Knowledge-QA currently returns the tool summary directly**: acceptable for conservative rollout, but conversational naturalization can be revisited later if needed.
3. **Result explanation uses bounded last-tool/context summaries only**: this avoids payload explosion but is not yet a full layered-memory experience.
4. **Dirty tree remains broad**: WP-CONV-3 should begin only after reviewing current scoped diffs.

---

## 9. Recommendation for WP-CONV-3

**Conditionally recommended.**

WP-CONV-2 targeted verification passed and all required blockers remained protected. It is reasonable to proceed to WP-CONV-3 **after** reviewing/staging the current scoped diff so the upcoming memory work does not mix with unrelated dirty-tree changes.

WP-CONV-3 should remain limited to in-place layered memory and must not absorb WP-CONV-4 retry/cleanup work.
