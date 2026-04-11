# WP-CONV-3 Execution Report

> Scope executed: WP-CONV-3 only (layered memory).  
> Scope intentionally not executed: WP-CONV-4 retry/backoff, cleanup, idle-session management, and other polish work.  
> Dirty-tree rule: unrelated modified/untracked files were preserved.

---

## 1. Scope Discipline

WP-CONV-3 was implemented under the following constraints:

1. **Only layered memory** was implemented.
2. **No retry/backoff logic** was added.
3. **No cleanup / idle session cleanup** was added.
4. Memory data structure was implemented **before** prompt/router injection points.
5. Fast path and state loop now consume the **same MemoryManager-backed layered memory APIs**, avoiding separate memory behavior stacks.

---

## 2. Layered Memory Design

### 2.1 Short-term memory

Short-term memory remains the recent-turn conversation buffer, persisted in `working_memory`.

Implemented details:

- storage: `MemoryManager.working_memory`
- per-turn model: `Turn`
- added `turn_index` to track sequencing across summaries and persistence
- bounded retention for storage trimming remains based on recent turns
- shared API added:
  - `build_conversational_messages(...)`

This API is now the fast-path source of truth for recent-turn conversational history.

### 2.2 Mid-term memory

New bounded summary layer added:

- dataclass: `SummarySegment`
- storage: `MemoryManager.mid_term_memory`
- generation cadence: every **3 turns**
- retention: max **5 segments**
- summary length: max **200 chars** per segment

Generation is rule-based and deterministic:

- tool turns summarize tool name + bounded tool summary
- non-tool turns summarize user utterance snippets

Legacy compatibility is maintained by mirroring mid-term summaries into `compressed_memory`.

### 2.3 Long-term memory

`FactMemory` was expanded with bounded structured fields:

- `session_topic`
- `user_language_preference`
- `cumulative_tools_used`
- `key_findings`
- `user_corrections`

Existing fields remain unchanged:

- `recent_vehicle`
- `recent_pollutants`
- `recent_year`
- `active_file`
- `file_analysis`
- `last_tool_name`
- `last_tool_summary`
- `last_tool_snapshot`
- `last_spatial_data`

These long-term facts are persisted and restored with backward-compatible defaults.

---

## 3. Shared Injection Strategy

After the memory structure was implemented, minimal injection points were added.

### 3.1 Shared memory context API

New shared API in `MemoryManager`:

- `build_context_for_prompt(max_chars=...)`

This is now used by:

- **state-loop / tool-mode assembly** via `ContextAssembler.assemble(..., memory_context=...)`
- **fast path** via `UnifiedRouter._build_conversational_system_prompt()`

This ensures mid-term and long-term memory are not duplicated in separate router codepaths.

### 3.2 Shared short-term history API

New shared API in `MemoryManager`:

- `build_conversational_messages(user_message, max_turns=..., assistant_char_limit=...)`

This is used by the fast path instead of maintaining a separate ad hoc history implementation.

### 3.3 Minimal router/assembler changes only

Injection-point changes were intentionally narrow:

- `core/assembler.py`
  - added optional `memory_context` parameter
  - appends memory context to system prompt in both legacy and skill modes
- `core/router.py`
  - added `_get_memory_context_for_prompt()`
  - fast path uses `build_conversational_messages()` and `build_context_for_prompt()` when available
  - state loop / legacy loop pass `memory_context=` into assembler

No WP-CONV-4 logic was touched.

---

## 4. Token Strategy

Layered memory is bounded at every layer.

### 4.1 Short-term

- storage retention: recent turns only
- fast-path history builder: **max 5 turns**
- fast-path assistant message cap: **1200 chars per assistant turn**
- state-loop tool mode continues to use bounded assembler working-memory formatting (existing 3-turn tool-mode budget remains in place)

### 4.2 Mid-term

- summary interval: **3 turns**
- max summary segments retained: **5**
- max chars per segment: **200**

### 4.3 Long-term

- recent pollutants: max **5**
- cumulative tools used: max **20**
- key findings: max **8**
- user corrections: max **8**

### 4.4 Prompt context cap

- `build_context_for_prompt(max_chars=1800)` default cap
- if exceeded, hard truncation with explicit `...(truncated)` marker

### 4.5 Explicit prohibitions

The memory context builder does **not** inject:

- raw `last_spatial_data`
- `raster_grid`
- concentration matrices
- raw GeoJSON/features
- full map payloads
- unbounded historical concatenation

---

## 5. Implemented Files

### WP-CONV-3 implementation

- `.env.example`
- `config.py`
- `core/memory.py`
- `core/assembler.py`
- `core/router.py`

### WP-CONV-3 tests

- `tests/test_layered_memory_context.py`
- `tests/test_assembler_skill_injection.py`
- `tests/test_router_state_loop.py`
- `tests/test_config.py`

### WP-CONV-3 documentation

- `docs/upgrade/WP-CONV-3_REPORT.md`

---

## 6. Verification Results

### Memory-structure-first targeted verification

```bash
pytest -q tests/test_layered_memory_context.py
```

Result: **4 passed**

### Injection-point targeted verification

```bash
pytest -q tests/test_layered_memory_context.py tests/test_assembler_skill_injection.py tests/test_router_state_loop.py tests/test_config.py
```

Result: **94 passed**, 4 warnings

### Final WP-CONV-3 targeted verification

```bash
pytest -q tests/test_layered_memory_context.py tests/test_conversation_intent.py tests/test_assembler_skill_injection.py tests/test_router_state_loop.py tests/test_session_persistence.py tests/test_config.py
python -m py_compile core/memory.py core/assembler.py core/router.py config.py
```

Result:

- pytest: **104 passed**, 8 warnings
- py_compile: **passed**

Warnings were existing deprecation/import warnings, not WP-CONV-3 assertion failures.

---

## 7. Risk Assessment

### 7.1 Main risks

1. **`core/memory.py` diff is large**  
   The memory model was expanded substantially to support layered memory and persistence. This increases schema and maintenance surface.

2. **Persistence migration risk**  
   Old session files are supported, but any future non-dict persisted structures will require careful migration discipline.

3. **Shared memory, different short-term budgets**  
   Fast path and tool mode now share the same MemoryManager-backed layered memory source of truth, but they still intentionally use different short-term history budgets for latency/token reasons. This is bounded and deliberate, but should be monitored in UX review.

4. **Dirty tree remains broad**  
   WP-CONV-3 changes should be reviewed/staged separately before any WP-CONV-4 work.

### 7.2 Risk level

Overall WP-CONV-3 risk: **moderate**

Reason:

- behavior remains bounded and well-tested
- no retry/cleanup changes were mixed in
- persistence remained backward-compatible
- largest risk is schema growth and broad memory-module diff, not immediate routing correctness

---

## 8. Recommendation

WP-CONV-3 completed successfully within scope.

If proceeding next, WP-CONV-4 should stay strictly limited to:

- retry/backoff
- conversational prompt polish
- cleanup / idle session handling
- observability additions

and should **not** reopen layered-memory design unless a concrete regression is found.
