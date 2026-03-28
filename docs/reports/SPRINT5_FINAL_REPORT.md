# Sprint 5 Final Report

## 1. Files Created or Modified

- `core/router.py`: added clarification detection, GROUNDED-stage clarification gating, and execution-time standardization error clarification handling.
- `api/session.py`: persisted `trace_friendly` into session history.
- `api/routes.py`: stored `trace_friendly` in history and emitted it in streaming `done` events.
- `api/models.py`: added `trace_friendly` to history message schema.
- `web/index.html`: added trace panel CSS and bumped `app.js` cache-busting version to `v=22`.
- `web/app.js`: added trace panel rendering/attachment helpers and integrated them into non-stream, history, and streaming completion paths.
- `tests/test_router_state_loop.py`: added clarification-path tests for unknown file type and standardization failure.
- `SPRINT5_FINAL_REPORT.md`: this report.

## 2. `_identify_critical_missing()` Method

```python
def _identify_critical_missing(self, state: TaskState) -> Optional[str]:
    """Identify the single most critical missing piece of information.

    Returns a clarification question string, or None if nothing is missing.
    Priority order:
    1. File type ambiguity (file uploaded but task_type is unknown)
    2. Standardization failure (a parameter couldn't be standardized)
    3. Missing required parameter (vehicle_type for micro, etc.)
    """
    if (
        state.file_context.has_file
        and state.file_context.grounded
        and state.file_context.task_type == "unknown"
    ):
        return (
            "I analyzed your uploaded file but couldn't determine the analysis type. "
            "Could you tell me: is this **trajectory data** (second-by-second vehicle records) "
            "for micro-scale emission calculation, or **road link data** (link-level traffic statistics) "
            "for macro-scale emission calculation?"
        )

    for param_name, entry in state.parameters.items():
        if entry.status.value == "AMBIGUOUS":
            return (
                f"I need clarification on the {param_name}: '{entry.raw}'. "
                f"Could you be more specific? For example, for vehicle types you can say: "
                f"Passenger Car, Transit Bus, Combination Long-haul Truck, etc."
            )

    if (
        state.file_context.task_type == "micro_emission"
        and "vehicle_type" not in state.parameters
    ):
        return (
            "To calculate micro-scale emissions, I need to know the **vehicle type**. "
            "What type of vehicle is this trajectory from? "
            "For example: Passenger Car, Transit Bus, Light Commercial Truck, etc."
        )

    return None
```

## 3. Updated `_state_handle_grounded()` and Standardization Error Handling in `_state_handle_executing()`

### `_state_handle_grounded()`

```python
async def _state_handle_grounded(
    self,
    state: TaskState,
    trace_obj: Optional[Trace] = None,
) -> None:
    """Handle GROUNDED state: check if we can proceed to execution."""
    clarification = self._identify_critical_missing(state)
    if clarification:
        state.control.needs_user_input = True
        state.control.clarification_question = clarification
        self._transition_state(
            state,
            TaskStage.NEEDS_CLARIFICATION,
            reason="Missing critical information",
            trace_obj=trace_obj,
        )
        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.CLARIFICATION,
                stage_before=TaskStage.GROUNDED.value,
                stage_after=TaskStage.NEEDS_CLARIFICATION.value,
                reasoning=clarification,
            )
        return

    self._transition_state(
        state,
        TaskStage.EXECUTING,
        reason="All parameters ready",
        trace_obj=trace_obj,
    )
```

### Standardization Error Handling in `_state_handle_executing()`

```python
if result.get("error") and result.get("error_type") == "standardization":
    error_msg = result.get("message", "Parameter standardization failed")
    suggestions = result.get("suggestions", [])
    clarification = (
        f"{error_msg}\n\nDid you mean one of these? {', '.join(suggestions[:5])}"
        if suggestions else error_msg
    )

    state.control.needs_user_input = True
    state.control.clarification_question = clarification
    state.execution.last_error = error_msg
    self._transition_state(
        state,
        TaskStage.NEEDS_CLARIFICATION,
        reason="Standardization failed",
        trace_obj=trace_obj,
    )

    if trace_obj:
        trace_obj.record(
            step_type=TraceStepType.ERROR,
            stage_before=TaskStage.EXECUTING.value,
            stage_after=TaskStage.NEEDS_CLARIFICATION.value,
            action=tool_call.name,
            error=error_msg,
        )
    return
```

## 4. Frontend Study Findings

### Layout and Design

- The page is a three-part flex layout: top navbar, left sidebar, and a main chat column.
- The main canvas uses a light gray `#f7f7f8` background; assistant content sits inside white cards with soft borders and light shadow.
- The primary accent is emerald/green: `#10b77f` / `#059669`.
- Typography uses `Manrope`, with generous spacing and rounded corners (`12px`, `16px`, `2xl`-style radii).
- Assistant messages are not flat chat bubbles; they are white cards inside a `flex justify-start gap-4` wrapper, with an avatar column on the left.
- User messages are green gradient bubbles aligned right.
- Styling is a hybrid:
  - Tailwind utility classes are the dominant component styling mechanism.
  - `index.html` contains substantial custom CSS for global layout tuning, markdown rendering, scrollbars, and card refinement.
- I did not find an existing reusable collapsible panel pattern inside messages. The closest existing interactive patterns are chart pollutant tabs, session inline rename, and hover-revealed action buttons.

### Assistant Message Rendering Path

- Non-streaming path:
  - `sendMessage()` calls `/api/chat`
  - response object is passed directly into `addAssistantMessage(data)`
- History path:
  - `loadSession()` -> `renderHistory(messages)`
  - assistant history messages are re-rendered by `addAssistantMessage(...)`
- Streaming path:
  - `sendMessageStream()` creates a container with `createAssistantMessageContainer()`
  - text is updated by `updateMessageContent()`
  - charts/tables/maps are appended incrementally by `renderChart()`, `renderTable()`, and `renderEmissionMap()`
  - final stream completion is handled in the `done` event branch

### Assistant Message DOM Structure

- The exact assistant wrapper is:
  - outer container: `div.flex.justify-start.gap-4`
  - avatar column
  - content column: `div.flex.flex-col.gap-4.flex-1.min-w-0`
  - message card: `div.bg-white.dark:bg-slate-800.p-4.rounded-xl.shadow-sm.border...`
  - content root inside card: `div.message-content`
- All charts, tables, maps, and the final trace panel belong inside the message card, after `.message-content`.

### Existing Response Data Flow

- API non-stream response already exposes `trace` and `trace_friendly`.
- History messages previously did not persist `trace_friendly`; I added that to session history persistence.
- Streaming `done` events previously did not emit `trace_friendly`; I added it there because streaming is the default UI path.

## 5. Design Decisions

- I placed the trace panel inside the existing assistant message card rather than outside the card. That preserves the current “one assistant reply = one card” visual model.
- The toggle button uses the existing muted slate palette instead of the emerald primary action color. That keeps it secondary to the actual answer.
- The panel background is slightly darker/lighter slate than the message body:
  - light mode: `slate-50/slate-100` gradient
  - dark mode: semi-transparent `slate-900/slate-800`
- Each step uses a subtle card with:
  - left border for status color
  - small status dot
  - existing typography scale and spacing
- I kept the trace collapsed by default to avoid distracting from the main answer.
- I used the existing Tailwind-heavy component approach for markup and added only a small amount of custom CSS in `index.html` for the toggle/panel/step states and transition.

## 6. Complete `renderTracePanel()` Function and CSS

### `renderTracePanel()`

```javascript
function renderTracePanel(traceFriendly) {
    if (!Array.isArray(traceFriendly) || traceFriendly.length === 0) {
        return null;
    }

    const panelId = `trace-panel-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const wrapper = document.createElement('div');
    wrapper.className = 'trace-panel-container';

    const stepsHtml = traceFriendly.map((step) => {
        const status = step?.status || 'success';
        const statusClass = status === 'error'
            ? 'trace-step-error'
            : status === 'warning'
                ? 'trace-step-warning'
                : 'trace-step-success';

        return `
            <div class="trace-step ${statusClass}">
                <span class="trace-step-status" aria-hidden="true"></span>
                <div class="min-w-0">
                    <div class="trace-step-title">${escapeHtml(step?.title || 'Analysis Step')}</div>
                    <div class="trace-step-description">${escapeHtml(step?.description || '')}</div>
                </div>
            </div>
        `;
    }).join('');

    wrapper.innerHTML = `
        <button type="button" class="trace-toggle" aria-expanded="false" aria-controls="${panelId}">
            <span class="material-symbols-outlined text-[18px]" style="font-size: 18px;">schema</span>
            <span>查看分析步骤 / View Analysis Steps</span>
            <span class="material-symbols-outlined trace-chevron ml-1" style="font-size: 18px;">expand_more</span>
        </button>
        <div id="${panelId}" class="trace-panel-shell" hidden>
            ${stepsHtml}
        </div>
    `;

    const toggle = wrapper.querySelector('.trace-toggle');
    const panel = wrapper.querySelector('.trace-panel-shell');
    toggle?.addEventListener('click', () => {
        const expanded = toggle.getAttribute('aria-expanded') === 'true';
        toggle.setAttribute('aria-expanded', String(!expanded));
        toggle.classList.toggle('is-open', !expanded);
        panel.hidden = expanded;
    });

    return wrapper;
}
```

### CSS

```css
.trace-toggle {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    margin-top: 1rem;
    padding: 0.625rem 0.875rem;
    border-radius: 0.875rem;
    border: 1px solid #e2e8f0;
    background: #f8fafc;
    color: #475569;
    font-size: 0.875rem;
    font-weight: 600;
    transition: background-color 0.2s ease, border-color 0.2s ease, color 0.2s ease;
}

.trace-toggle:hover {
    background: #f1f5f9;
    color: #0f172a;
    border-color: #cbd5e1;
}

.dark .trace-toggle {
    background: rgba(15, 23, 42, 0.68);
    color: #cbd5e1;
    border-color: rgba(148, 163, 184, 0.2);
}

.dark .trace-toggle:hover {
    background: rgba(30, 41, 59, 0.9);
    color: #f8fafc;
    border-color: rgba(148, 163, 184, 0.3);
}

.trace-chevron {
    transition: transform 0.2s ease;
}

.trace-toggle.is-open .trace-chevron {
    transform: rotate(180deg);
}

.trace-panel-shell {
    margin-top: 0.875rem;
    padding: 1rem;
    border-radius: 1rem;
    border: 1px solid #e2e8f0;
    background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
}

.dark .trace-panel-shell {
    border-color: rgba(148, 163, 184, 0.18);
    background: linear-gradient(180deg, rgba(15, 23, 42, 0.82) 0%, rgba(30, 41, 59, 0.72) 100%);
}

.trace-panel-shell[hidden] {
    display: none !important;
}

.trace-step {
    display: flex;
    gap: 0.75rem;
    align-items: flex-start;
    padding: 0.875rem 1rem;
    border-radius: 0.875rem;
    border: 1px solid rgba(226, 232, 240, 0.95);
    background: rgba(255, 255, 255, 0.9);
}

.dark .trace-step {
    border-color: rgba(148, 163, 184, 0.14);
    background: rgba(15, 23, 42, 0.55);
}

.trace-step + .trace-step {
    margin-top: 0.75rem;
}

.trace-step-status {
    width: 0.625rem;
    height: 0.625rem;
    margin-top: 0.425rem;
    border-radius: 9999px;
    flex-shrink: 0;
}

.trace-step-success {
    border-left: 3px solid #10b981;
}

.trace-step-success .trace-step-status {
    background: #10b981;
}

.trace-step-warning {
    border-left: 3px solid #f59e0b;
}

.trace-step-warning .trace-step-status {
    background: #f59e0b;
}

.trace-step-error {
    border-left: 3px solid #ef4444;
}

.trace-step-error .trace-step-status {
    background: #ef4444;
}

.trace-step-title {
    color: #0f172a;
    font-size: 0.875rem;
    font-weight: 700;
    line-height: 1.4;
}

.trace-step-description {
    margin-top: 0.2rem;
    color: #475569;
    font-size: 0.8125rem;
    line-height: 1.6;
    white-space: pre-wrap;
}

.dark .trace-step-title {
    color: #f8fafc;
}

.dark .trace-step-description {
    color: #cbd5e1;
}
```

## 7. Exact Integration Points in `app.js`

- Non-streaming assistant rendering:
  - function: `addAssistantMessage(data)`
  - location: after map rendering, before `scrollToBottom()`
  - logic: `attachTracePanelToMessage(msgContainer, data.trace_friendly)`

- History re-rendering:
  - function: `renderHistory(messages)`
  - location: assistant branch when calling `addAssistantMessage(...)`
  - logic: pass `trace_friendly: msg.trace_friendly`

- Streaming completion path:
  - function: `sendMessageStream(message, file)`
  - code path: `case 'done'`
  - logic: if `data.trace_friendly` is present, call `attachTracePanelToMessage(assistantMsgId, data.trace_friendly)`

- Supporting DOM helpers added:
  - `getAssistantMessageContainer(target)`
  - `getAssistantMessageCard(target)`
  - `attachTracePanelToMessage(target, traceFriendly)`

## 8. Streaming Case Handling: Decision and Reasoning

- Decision: I implemented option `a`, not `b`.
- I added `trace_friendly` to the final SSE `done` event in `api/routes.py`.
- Reasoning:
  - The frontend defaults to `USE_STREAMING = true`.
  - If the trace panel existed only in the non-stream path, the primary UI path would never show it.
  - Adding `trace_friendly` only once, at stream completion, keeps the stream lightweight and avoids partial/meta events during generation.
- Graceful behavior:
  - If `trace_friendly` is absent in `done`, the frontend simply skips the panel.

## 9. Test Results

### `pytest tests/test_router_state_loop.py -v`

```text
============================= test session starts ==============================
platform linux -- Python 3.13.9, pytest-9.0.2, pluggy-1.5.0 -- /home/kirito/miniconda3/bin/python3.13
cachedir: .pytest_cache
rootdir: /home/kirito/Agent1/emission_agent
configfile: pyproject.toml
plugins: anyio-4.12.1
collecting ... collected 6 items

tests/test_router_state_loop.py::test_legacy_loop_unchanged[asyncio] PASSED [ 16%]
tests/test_router_state_loop.py::test_state_loop_no_tool_call[asyncio] PASSED [ 33%]
tests/test_router_state_loop.py::test_state_loop_with_tool_call[asyncio] PASSED [ 50%]
tests/test_router_state_loop.py::test_state_loop_produces_trace[asyncio] PASSED [ 66%]
tests/test_router_state_loop.py::test_clarification_on_unknown_file_type[asyncio] PASSED [ 83%]
tests/test_router_state_loop.py::test_clarification_on_standardization_error[asyncio] PASSED [100%]

============================== 6 passed in 0.41s ===============================
```

### `pytest`

```text
============================= test session starts ==============================
platform linux -- Python 3.13.9, pytest-9.0.2, pluggy-1.5.0 -- /home/kirito/miniconda3/bin/python3.13
cachedir: .pytest_cache
rootdir: /home/kirito/Agent1/emission_agent
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.12.1
collecting ... 
collected 143 items

======================= 143 passed, 19 warnings in 4.92s =======================
```

## 10. Output of `python main.py health`

```text
WARNING:skills.knowledge.retriever:FlagEmbedding 未安装，本地embedding功能不可用
╭───────────────────╮
│ Tool Health Check │
╰───────────────────╯
OK query_emission_factors
OK calculate_micro_emission
OK calculate_macro_emission
OK analyze_file
OK query_knowledge

Total tools: 5
```

## 11. Manual UI Verification

- I was able to start `python run_api.py` and observed the startup banner:

```text
============================================================
🌿 Emission Agent API Server
============================================================
服务器启动中...
访问地址: http://localhost:8000
API文档: http://localhost:8000/docs
============================================================
```

- I also verified the HTML now references `app.js?v=22`.
- I verified `node --check web/app.js` with no syntax output, which indicates the updated frontend script parses successfully.
- I could not complete browser-based manual interaction in this environment:
  - loopback HTTP access to `127.0.0.1:8000` was blocked in the sandbox
  - there is no interactive browser available here to click and visually inspect the toggle
- So I could not directly confirm the on-screen toggle expansion by browser, but the backend/API/frontend integration points, HTML/CSS wiring, and JS syntax are all in place.

## 12. Final Upgrade Summary Across All 5 Sprints

### Total Test Count

- Baseline before upgrade: `79`
- Final after Sprint 5: `143`

### All New Files Created

- `core/task_state.py`
- `core/trace.py`
- `tests/test_task_state.py`
- `tests/test_trace.py`
- `tests/test_router_state_loop.py`
- `tests/test_file_grounding_enhanced.py`
- `tests/test_standardizer_enhanced.py`
- `SPRINT1_TASKSTATE_REPORT.md`
- `SPRINT2_TRACE_REPORT.md`
- `SPRINT3_FILE_GROUNDING_REPORT.md`
- `SPRINT4_STANDARDIZATION_REPORT.md`
- `SPRINT5_FINAL_REPORT.md`

### All Files Modified

- `config.py`
- `core/router.py`
- `core/executor.py`
- `services/standardizer.py`
- `tools/file_analyzer.py`
- `config/unified_mappings.yaml`
- `api/session.py`
- `api/routes.py`
- `api/models.py`
- `web/index.html`
- `web/app.js`
- `tests/test_router_state_loop.py`

### New Feature Flags Added to `config.py`

- `enable_state_orchestration`
- `enable_trace`
- `max_orchestration_steps`

### Key Capabilities Added

- Sprint 1: explicit `TaskState` and state-driven router orchestration loop
- Sprint 2: structured `Trace` / `TraceStep` system with friendly trace output
- Sprint 3: multi-signal file grounding with evidence and value-feature analysis
- Sprint 4: structured parameter standardization results, season/road type normalization, abstain-with-suggestions, and traceable standardization records
- Sprint 5: clarification routing for ambiguous file/parameter situations and a frontend trace panel integrated into non-stream, history, and streaming-complete rendering paths
