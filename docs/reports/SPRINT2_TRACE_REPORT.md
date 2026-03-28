# Sprint 2 Trace Report

## 1. Files Created or Modified
- `core/trace.py`: created the structured `Trace`, `TraceStep`, and `TraceStepType` system with serialization and user-friendly rendering.
- `core/router.py`: integrated `Trace` into the state loop, added state-transition recording, user-friendly trace output, and minimal legacy trace passthrough.
- `api/session.py`: passed through `trace_friendly` together with `trace`.
- `api/models.py`: added `trace_friendly` to `ChatResponse`.
- `api/routes.py`: forwarded `trace_friendly` in `/chat` responses.
- `tests/test_trace.py`: added full unit coverage for the new trace module.
- `tests/test_router_state_loop.py`: updated state-loop assertions for structured trace output and added explicit trace-production coverage.

## 2. Full Content of `core/trace.py`
```python
"""
EmissionAgent - Auditable Decision Trace

Records structured decision steps across the agent workflow.
Each state transition in the Router's state loop generates a TraceStep,
creating a complete auditable record of how the system processed a request.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class TraceStepType(str, Enum):
    """Types of trace steps."""

    FILE_GROUNDING = "file_grounding"
    PARAMETER_STANDARDIZATION = "parameter_standardization"
    TOOL_SELECTION = "tool_selection"
    TOOL_EXECUTION = "tool_execution"
    STATE_TRANSITION = "state_transition"
    CLARIFICATION = "clarification"
    SYNTHESIS = "synthesis"
    ERROR = "error"


@dataclass
class TraceStep:
    """A single decision step in the agent workflow."""

    step_index: int
    step_type: TraceStepType
    timestamp: str  # ISO format
    stage_before: str  # TaskStage value at start of this step
    stage_after: Optional[str] = None  # TaskStage value after this step
    action: Optional[str] = None  # what was done (e.g. "analyze_file", "calculate_macro_emission")
    input_summary: Optional[Dict[str, Any]] = None  # key inputs (NOT full data, keep it compact)
    output_summary: Optional[Dict[str, Any]] = None  # key outputs (compact)
    confidence: Optional[float] = None
    reasoning: Optional[str] = None  # why this decision was made
    duration_ms: Optional[float] = None  # step duration in milliseconds
    standardization_records: Optional[List[Dict[str, Any]]] = None  # param standardization details
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict, excluding None fields for cleaner output."""
        result = {}
        for key in ["step_index", "step_type", "timestamp", "stage_before"]:
            val = getattr(self, key)
            result[key] = val.value if isinstance(val, Enum) else val
        for key in [
            "stage_after",
            "action",
            "input_summary",
            "output_summary",
            "confidence",
            "reasoning",
            "duration_ms",
            "standardization_records",
            "error",
        ]:
            val = getattr(self, key)
            if val is not None:
                result[key] = val
        return result


@dataclass
class Trace:
    """Complete auditable decision trace for one agent turn."""

    session_id: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    total_duration_ms: Optional[float] = None
    steps: List[TraceStep] = field(default_factory=list)
    final_stage: Optional[str] = None  # the TaskStage the system ended in

    @classmethod
    def start(cls, session_id: Optional[str] = None) -> "Trace":
        """Initialize a new trace at the beginning of a turn."""
        return cls(
            session_id=session_id,
            start_time=datetime.now().isoformat(),
        )

    def record(
        self,
        step_type: TraceStepType,
        stage_before: str,
        stage_after: Optional[str] = None,
        action: Optional[str] = None,
        input_summary: Optional[Dict] = None,
        output_summary: Optional[Dict] = None,
        confidence: Optional[float] = None,
        reasoning: str = "",
        duration_ms: Optional[float] = None,
        standardization_records: Optional[List[Dict]] = None,
        error: Optional[str] = None,
    ) -> TraceStep:
        """Record a single trace step. Returns the created step."""
        step = TraceStep(
            step_index=len(self.steps),
            step_type=step_type,
            timestamp=datetime.now().isoformat(),
            stage_before=stage_before,
            stage_after=stage_after,
            action=action,
            input_summary=input_summary,
            output_summary=output_summary,
            confidence=confidence,
            reasoning=reasoning,
            duration_ms=duration_ms,
            standardization_records=standardization_records,
            error=error,
        )
        self.steps.append(step)
        return step

    def finish(self, final_stage: str) -> None:
        """Mark the trace as complete."""
        self.end_time = datetime.now().isoformat()
        self.final_stage = final_stage
        if self.start_time:
            try:
                start = datetime.fromisoformat(self.start_time)
                end = datetime.fromisoformat(self.end_time)
                self.total_duration_ms = round((end - start).total_seconds() * 1000, 1)
            except (ValueError, TypeError):
                pass

    def to_dict(self) -> Dict[str, Any]:
        """Full serialization for API response and logging."""
        return {
            "session_id": self.session_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_duration_ms": self.total_duration_ms,
            "final_stage": self.final_stage,
            "step_count": len(self.steps),
            "steps": [s.to_dict() for s in self.steps],
        }

    def to_user_friendly(self) -> List[Dict[str, str]]:
        """Convert to user-friendly display format for frontend trace panel.

        Returns a list of {title, description, status, step_type} dicts.
        Title and description are bilingual (Chinese / English).
        """
        friendly = []
        for step in self.steps:
            entry = self._format_step_friendly(step)
            if entry:
                friendly.append(entry)
        return friendly

    def _format_step_friendly(self, step: TraceStep) -> Optional[Dict[str, str]]:
        """Format a single step for user display."""
        if step.step_type == TraceStepType.FILE_GROUNDING:
            task_type = step.output_summary.get("task_type", "unknown") if step.output_summary else "unknown"
            conf = step.confidence
            conf_str = f"{conf:.0%}" if conf is not None else "N/A"
            return {
                "title": "📄 文件识别 / File Analysis",
                "description": f"识别为 {task_type} 任务，置信度 {conf_str} / Identified as {task_type} task, confidence {conf_str}",
                "status": "success" if conf and conf > 0.6 else "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.TOOL_SELECTION:
            tool = step.action or "unknown"
            return {
                "title": "🔧 工具选择 / Tool Selection",
                "description": f"选择 {tool} / Selected {tool}",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.PARAMETER_STANDARDIZATION:
            desc = step.reasoning or "参数已标准化 / Parameters standardized"
            return {
                "title": "🔄 参数标准化 / Parameter Standardization",
                "description": desc,
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.TOOL_EXECUTION:
            tool = step.action or "unknown"
            success = step.error is None
            duration = f" ({step.duration_ms:.0f}ms)" if step.duration_ms else ""
            if success:
                return {
                    "title": f"⚡ 计算执行 / Execute {tool}",
                    "description": f"{tool} 执行成功{duration} / {tool} completed{duration}",
                    "status": "success",
                    "step_type": step.step_type.value,
                }
            else:
                return {
                    "title": f"❌ 执行失败 / {tool} Failed",
                    "description": step.error or "执行出错 / Execution error",
                    "status": "error",
                    "step_type": step.step_type.value,
                }

        elif step.step_type == TraceStepType.SYNTHESIS:
            return {
                "title": "📝 结果合成 / Result Synthesis",
                "description": step.reasoning or "生成分析报告 / Generating analysis report",
                "status": "success",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.CLARIFICATION:
            return {
                "title": "❓ 需要确认 / Clarification Needed",
                "description": step.reasoning or "需要更多信息 / More information needed",
                "status": "warning",
                "step_type": step.step_type.value,
            }

        elif step.step_type == TraceStepType.ERROR:
            return {
                "title": "⚠️ 错误 / Error",
                "description": step.error or "发生错误 / An error occurred",
                "status": "error",
                "step_type": step.step_type.value,
            }

        return None
```

## 3. Key Changes to `core/router.py`
### Updated `RouterResponse`
```python
@dataclass
class RouterResponse:
    """Router response to user"""
    text: str
    chart_data: Optional[Dict] = None
    table_data: Optional[Dict] = None
    map_data: Optional[Dict] = None
    download_file: Optional[Dict[str, Any]] = None
    executed_tool_calls: Optional[List[Dict[str, Any]]] = None
    trace: Optional[Dict[str, Any]] = None  # NEW: auditable decision trace
    trace_friendly: Optional[List[Dict[str, str]]] = None
```

### Updated `_run_state_loop()`, `_transition_state()`, `_state_handle_*()`, `_state_build_response()`
```python
    async def _run_state_loop(
        self,
        user_message: str,
        file_path: Optional[str] = None,
        trace: Optional[Dict[str, Any]] = None,
    ) -> RouterResponse:
        config = get_config()

        fact_memory = self.memory.get_fact_memory()
        state = TaskState.initialize(
            user_message=user_message,
            file_path=file_path,
            memory_dict=fact_memory,
            session_id=self.session_id,
        )
        state.control.max_steps = config.max_orchestration_steps
        trace_obj = Trace.start(session_id=self.session_id) if config.enable_trace else None

        while not state.should_stop():
            if state.stage == TaskStage.INPUT_RECEIVED:
                await self._state_handle_input(state, trace_obj=trace_obj)
            elif state.stage == TaskStage.GROUNDED:
                await self._state_handle_grounded(state, trace_obj=trace_obj)
            elif state.stage == TaskStage.EXECUTING:
                await self._state_handle_executing(state, trace_obj=trace_obj)

        if not state.is_terminal():
            self._transition_state(
                state,
                TaskStage.DONE,
                reason="max steps reached",
                trace_obj=trace_obj,
            )

        if trace_obj:
            trace_obj.finish(final_stage=state.stage.value)

        response = await self._state_build_response(state, user_message, trace_obj=trace_obj)

        tool_calls_data = None
        if state.execution.tool_results and not state.execution.tool_results[0].get("no_tool"):
            tool_calls_data = self._build_memory_tool_calls(state.execution.tool_results)

        file_context = state.file_context.to_dict() if state.file_context.grounded else None
        cached_file_context = getattr(state, "_file_analysis_cache", None)
        if file_context and isinstance(cached_file_context, dict):
            enriched_file_context = dict(cached_file_context)
            enriched_file_context.update(file_context)
            file_context = enriched_file_context
        self.memory.update(user_message, response.text, tool_calls_data, file_path, file_context)

        if trace is not None and trace_obj:
            trace.update(trace_obj.to_dict())

        return response

    def _transition_state(
        self,
        state: TaskState,
        new_stage: TaskStage,
        reason: str = "",
        trace_obj: Optional[Trace] = None,
    ) -> None:
        stage_before = state.stage.value
        state.transition(new_stage, reason=reason)
        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.STATE_TRANSITION,
                stage_before=stage_before,
                stage_after=state.stage.value,
                reasoning=reason,
            )

    async def _state_handle_input(
        self,
        state: TaskState,
        trace_obj: Optional[Trace] = None,
    ) -> None:
        if state.file_context.has_file and not state.file_context.grounded:
            from pathlib import Path
            import os

            cached = self.memory.get_fact_memory().get("file_analysis")
            file_path_str = str(state.file_context.file_path)

            try:
                current_mtime = os.path.getmtime(file_path_str)
            except Exception:
                current_mtime = None

            cache_valid = (
                cached
                and str(cached.get("file_path")) == file_path_str
                and cached.get("file_mtime") == current_mtime
            )

            if self.runtime_config.enable_file_analyzer and cache_valid:
                analysis_dict = dict(cached)
                logger.info(f"Using cached file analysis for {state.file_context.file_path}")
            elif self.runtime_config.enable_file_analyzer:
                analysis_dict = await self._analyze_file(file_path_str)
                analysis_dict["file_path"] = file_path_str
                analysis_dict["file_mtime"] = current_mtime
                logger.info(f"Analyzed new file: {state.file_context.file_path} (mtime: {current_mtime})")
            else:
                analysis_dict = {
                    "filename": Path(file_path_str).name,
                    "file_path": file_path_str,
                    "task_type": None,
                    "confidence": 0.0,
                }
                logger.info("File analyzer disabled by runtime config")

            state.update_file_context(analysis_dict)
            setattr(state, "_file_analysis_cache", analysis_dict)
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.FILE_GROUNDING,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="analyze_file",
                    output_summary={
                        "task_type": state.file_context.task_type,
                        "confidence": state.file_context.confidence,
                        "columns": state.file_context.columns[:10],
                        "row_count": state.file_context.row_count,
                    },
                    confidence=state.file_context.confidence,
                    reasoning="; ".join(state.file_context.evidence) if state.file_context.evidence else "File structure analyzed",
                )

        file_context = None
        if state.file_context.grounded:
            from pathlib import Path

            file_context = {
                "filename": Path(state.file_context.file_path).name if state.file_context.file_path else "unknown",
                "file_path": state.file_context.file_path,
                "task_type": state.file_context.task_type,
                "confidence": state.file_context.confidence if state.file_context.confidence is not None else 0.0,
                "columns": list(state.file_context.columns),
                "row_count": state.file_context.row_count,
                "sample_rows": state.file_context.sample_rows,
                "micro_mapping": state.file_context.micro_mapping,
                "macro_mapping": state.file_context.macro_mapping,
                "micro_has_required": state.file_context.micro_has_required,
                "macro_has_required": state.file_context.macro_has_required,
                "column_mapping": state.file_context.column_mapping,
                "evidence": list(state.file_context.evidence),
            }
            cached_file_context = getattr(state, "_file_analysis_cache", None)
            if isinstance(cached_file_context, dict):
                cached_copy = dict(cached_file_context)
                cached_copy.update(file_context)
                file_context = cached_copy

        context = self.assembler.assemble(
            user_message=state.user_message or "",
            working_memory=self.memory.get_working_memory(),
            fact_memory=self.memory.get_fact_memory(),
            file_context=file_context,
        )
        setattr(state, "_assembled_context", context)

        response = await self.llm.chat_with_tools(
            messages=context.messages,
            tools=context.tools,
            system=context.system_prompt
        )

        if response.tool_calls:
            state._llm_response = response
            state.execution.selected_tool = response.tool_calls[0].name
            if trace_obj:
                tool_names = [tc.name for tc in response.tool_calls]
                trace_obj.record(
                    step_type=TraceStepType.TOOL_SELECTION,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    stage_after=TaskStage.GROUNDED.value,
                    action=", ".join(tool_names),
                    reasoning=f"LLM selected tool(s): {', '.join(tool_names)}",
                )
            self._transition_state(
                state,
                TaskStage.GROUNDED,
                reason="LLM selected tool(s)",
                trace_obj=trace_obj,
            )
        else:
            state.execution.tool_results = [{"text": response.content, "no_tool": True}]
            self._transition_state(
                state,
                TaskStage.DONE,
                reason="LLM responded without tool calls",
                trace_obj=trace_obj,
            )

    async def _state_handle_grounded(
        self,
        state: TaskState,
        trace_obj: Optional[Trace] = None,
    ) -> None:
        self._transition_state(
            state,
            TaskStage.EXECUTING,
            reason="proceeding to execution",
            trace_obj=trace_obj,
        )

    async def _state_handle_executing(
        self,
        state: TaskState,
        trace_obj: Optional[Trace] = None,
    ) -> None:
        response = state._llm_response
        if not response or not response.tool_calls:
            state.execution.tool_results = [{"text": getattr(response, "content", ""), "no_tool": True}]
            self._transition_state(
                state,
                TaskStage.DONE,
                reason="missing tool calls during execution",
                trace_obj=trace_obj,
            )
            return

        context = getattr(state, "_assembled_context", None)
        if context is None:
            context = self.assembler.assemble(
                user_message=state.user_message or "",
                working_memory=self.memory.get_working_memory(),
                fact_memory=self.memory.get_fact_memory(),
                file_context=None,
            )
            setattr(state, "_assembled_context", context)

        state.execution.tool_results = []
        for tool_call in response.tool_calls:
            logger.info(f"Executing tool: {tool_call.name}")
            logger.debug(f"Tool arguments: {tool_call.arguments}")

            tool_start_time = time.time()
            result = await self.executor.execute(
                tool_name=tool_call.name,
                arguments=tool_call.arguments,
                file_path=state.file_context.file_path
            )
            elapsed_ms = round((time.time() - tool_start_time) * 1000, 1)

            logger.info(f"Tool {tool_call.name} completed. Success: {result.get('success')}, Error: {result.get('error')}")
            if result.get('error'):
                logger.error(f"Tool error message: {result.get('message', 'No message')}")

            tool_result = {
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "result": result
            }
            state.execution.tool_results.append(tool_result)
            state.execution.completed_tools.append(tool_call.name)

            if trace_obj:
                std_records = result.get("_standardization_records") or (
                    result.get("_trace", {}).get("standardized_arguments")
                )
                trace_obj.record(
                    step_type=TraceStepType.TOOL_EXECUTION,
                    stage_before=TaskStage.EXECUTING.value,
                    action=tool_call.name,
                    input_summary={
                        "arguments": {
                            key: str(value)[:100]
                            for key, value in tool_call.arguments.items()
                        }
                    },
                    output_summary={
                        "success": result.get("success", False),
                        "message": str(result.get("message", ""))[:200],
                    },
                    confidence=None,
                    reasoning=result.get("summary", ""),
                    duration_ms=elapsed_ms,
                    standardization_records=[std_records] if isinstance(std_records, dict) else std_records,
                    error=result.get("message") if result.get("error") else None,
                )

        has_error = any(item["result"].get("error") for item in state.execution.tool_results)

        if has_error and state.control.steps_taken < state.control.max_steps - 1:
            error_messages = self._format_tool_errors(state.execution.tool_results)
            state.execution.last_error = error_messages

            context.messages.append({
                "role": "assistant",
                "content": response.content or "Calling tools...",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": str(tc.arguments)
                        }
                    }
                    for tc in response.tool_calls
                ]
            })
            context.messages.append({
                "role": "tool",
                "content": error_messages,
                "tool_call_id": state.execution.tool_results[0]["tool_call_id"]
            })

            retry_response = await self.llm.chat_with_tools(
                messages=context.messages,
                tools=context.tools,
                system=context.system_prompt
            )

            state._llm_response = retry_response
            if retry_response.tool_calls:
                state.execution.selected_tool = retry_response.tool_calls[0].name
                if trace_obj:
                    tool_names = [tc.name for tc in retry_response.tool_calls]
                    trace_obj.record(
                        step_type=TraceStepType.TOOL_SELECTION,
                        stage_before=TaskStage.EXECUTING.value,
                        stage_after=TaskStage.EXECUTING.value,
                        action=", ".join(tool_names),
                        reasoning=f"LLM selected tool(s) after retry: {', '.join(tool_names)}",
                    )
                # Count the additional orchestration turn even though the stage remains EXECUTING.
                state.control.steps_taken += 1
                return

            state.execution.tool_results = [{"text": retry_response.content, "no_tool": True}]
            self._transition_state(
                state,
                TaskStage.DONE,
                reason="retry completed without tool calls",
                trace_obj=trace_obj,
            )
            return

        self._transition_state(
            state,
            TaskStage.DONE,
            reason="execution completed",
            trace_obj=trace_obj,
        )

    async def _state_build_response(
        self,
        state: TaskState,
        user_message: str,
        trace_obj: Optional[Trace] = None,
    ) -> RouterResponse:
        if state.stage == TaskStage.NEEDS_CLARIFICATION:
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.CLARIFICATION,
                    stage_before=state.stage.value,
                    reasoning=state.control.clarification_question or "More information needed",
                )
            response = RouterResponse(text=state.control.clarification_question or "Could you provide more details?")
            if trace_obj:
                response.trace = trace_obj.to_dict()
                response.trace_friendly = trace_obj.to_user_friendly()
            return response

        if state.execution.tool_results and state.execution.tool_results[0].get("no_tool"):
            response = RouterResponse(text=state.execution.tool_results[0].get("text", ""))
            if trace_obj:
                response.trace = trace_obj.to_dict()
                response.trace_friendly = trace_obj.to_user_friendly()
            return response

        if state.execution.tool_results:
            context = getattr(state, "_assembled_context", None)
            if context is None:
                context = type("StateContext", (), {"messages": [{"content": user_message}]})()
            synthesis_text = await self._synthesize_results(
                context,
                state._llm_response,
                state.execution.tool_results
            )
            if trace_obj and synthesis_text:
                trace_obj.record(
                    step_type=TraceStepType.SYNTHESIS,
                    stage_before=TaskStage.DONE.value,
                    reasoning="Results synthesized into natural language response",
                )
            chart_data = self._extract_chart_data(state.execution.tool_results)
            table_data = self._extract_table_data(state.execution.tool_results)
            map_data = self._extract_map_data(state.execution.tool_results)
            download_file = self._extract_download_file(state.execution.tool_results)

            response = RouterResponse(
                text=synthesis_text,
                chart_data=chart_data,
                table_data=table_data,
                map_data=map_data,
                download_file=download_file,
                executed_tool_calls=self._build_memory_tool_calls(state.execution.tool_results),
            )
            if trace_obj:
                response.trace = trace_obj.to_dict()
                response.trace_friendly = trace_obj.to_user_friendly()
            return response

        response = RouterResponse(text="I wasn't able to process your request. Could you try again?")
        if trace_obj:
            response.trace = trace_obj.to_dict()
            response.trace_friendly = trace_obj.to_user_friendly()
        return response
```

### Minimal Legacy Trace Attachment
```python
        if get_config().enable_trace and trace is not None:
            result.trace = trace
```

## 4. Changes to `api/session.py`, `api/routes.py`, `api/models.py`
### `api/session.py`
```python
    async def chat(self, message: str, file_path: Optional[str] = None) -> Dict:
        """
        异步聊天接口

        Returns:
            Dict with keys: text, chart_data, table_data, map_data, download_file, trace, trace_friendly
        """
        trace = {} if get_config().enable_trace else None
        result = await self.router.chat(user_message=message, file_path=file_path, trace=trace)

        return {
            "text": result.text,
            "chart_data": result.chart_data,
            "table_data": result.table_data,
            "map_data": result.map_data,
            "download_file": result.download_file,
            "trace": result.trace,
            "trace_friendly": result.trace_friendly,
        }
```

### `api/models.py`
```python
class ChatResponse(BaseModel):
    """聊天响应"""
    reply: str
    session_id: str
    data_type: Optional[str] = None  # "text" | "chart" | "table" | "map" | "table_and_map"
    chart_data: Optional[Dict[str, Any]] = None
    table_data: Optional[Dict[str, Any]] = None
    map_data: Optional[Dict[str, Any]] = None
    file_id: Optional[str] = None
    download_file: Optional[Dict[str, Any]] = None
    message_id: Optional[str] = None
    trace: Optional[Dict[str, Any]] = None
    trace_friendly: Optional[List[Dict[str, Any]]] = None
    success: bool = True
    error: Optional[str] = None
```

### `api/routes.py`
```python
        reply_text = result.get("text", "")
        chart_data = result.get("chart_data")
        table_data = result.get("table_data")
        map_data = result.get("map_data")
        trace = result.get("trace")
        trace_friendly = result.get("trace_friendly")
        assistant_message_id = uuid.uuid4().hex[:12]
        download_file = normalize_download_file(
            result.get("download_file"),
            session.session_id,
            assistant_message_id,
            user_id
        )

        response = ChatResponse(
            reply=clean_reply_text(reply_text),
            session_id=session.session_id,
            success=True,
            data_type=data_type,
            chart_data=chart_data,
            table_data=table_data,
            map_data=map_data,
            file_id=session.session_id if download_file else None,
            download_file=download_file,
            message_id=assistant_message_id,
            trace=trace,
            trace_friendly=trace_friendly,
        )
```

## 5. Full Content of `tests/test_trace.py`
```python
"""Tests for core.trace module."""

import json

import pytest

from core.trace import Trace, TraceStep, TraceStepType


class TestTraceStep:
    def test_to_dict_excludes_none(self):
        step = TraceStep(
            step_index=0,
            step_type=TraceStepType.FILE_GROUNDING,
            timestamp="2025-01-01T00:00:00",
            stage_before="INPUT_RECEIVED",
        )
        d = step.to_dict()
        assert "stage_after" not in d
        assert "error" not in d
        assert d["step_type"] == "file_grounding"

    def test_to_dict_includes_set_fields(self):
        step = TraceStep(
            step_index=1,
            step_type=TraceStepType.TOOL_EXECUTION,
            timestamp="2025-01-01T00:00:00",
            stage_before="EXECUTING",
            stage_after="DONE",
            action="calculate_macro_emission",
            duration_ms=150.5,
            error=None,
        )
        d = step.to_dict()
        assert d["action"] == "calculate_macro_emission"
        assert d["duration_ms"] == 150.5
        assert "error" not in d


class TestTrace:
    def test_start_creates_with_timestamp(self):
        t = Trace.start(session_id="test-123")
        assert t.session_id == "test-123"
        assert t.start_time is not None
        assert t.steps == []

    def test_record_appends_step(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.FILE_GROUNDING,
            stage_before="INPUT_RECEIVED",
            action="analyze_file",
            confidence=0.88,
        )
        assert len(t.steps) == 1
        assert t.steps[0].step_index == 0
        assert t.steps[0].step_type == TraceStepType.FILE_GROUNDING
        assert t.steps[0].confidence == 0.88

    def test_record_auto_increments_index(self):
        t = Trace.start()
        t.record(step_type=TraceStepType.FILE_GROUNDING, stage_before="INPUT_RECEIVED")
        t.record(step_type=TraceStepType.TOOL_SELECTION, stage_before="GROUNDED")
        t.record(step_type=TraceStepType.TOOL_EXECUTION, stage_before="EXECUTING")
        assert [s.step_index for s in t.steps] == [0, 1, 2]

    def test_finish_sets_end_time_and_duration(self):
        t = Trace.start()
        t.record(step_type=TraceStepType.FILE_GROUNDING, stage_before="INPUT_RECEIVED")
        t.finish(final_stage="DONE")
        assert t.end_time is not None
        assert t.final_stage == "DONE"
        assert t.total_duration_ms is not None
        assert t.total_duration_ms >= 0

    def test_to_dict_serializable(self):
        t = Trace.start(session_id="s1")
        t.record(
            step_type=TraceStepType.TOOL_EXECUTION,
            stage_before="EXECUTING",
            action="calculate_macro_emission",
            output_summary={"success": True},
            duration_ms=200.0,
        )
        t.finish("DONE")
        d = t.to_dict()
        json_str = json.dumps(d)
        assert isinstance(json_str, str)
        assert d["step_count"] == 1
        assert d["final_stage"] == "DONE"

    def test_to_user_friendly_file_grounding(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.FILE_GROUNDING,
            stage_before="INPUT_RECEIVED",
            output_summary={"task_type": "macro_emission", "confidence": 0.88},
            confidence=0.88,
        )
        friendly = t.to_user_friendly()
        assert len(friendly) == 1
        assert "macro_emission" in friendly[0]["description"]
        assert friendly[0]["status"] == "success"

    def test_to_user_friendly_tool_execution_success(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.TOOL_EXECUTION,
            stage_before="EXECUTING",
            action="calculate_macro_emission",
            duration_ms=350.0,
        )
        friendly = t.to_user_friendly()
        assert len(friendly) == 1
        assert "350ms" in friendly[0]["description"]
        assert friendly[0]["status"] == "success"

    def test_to_user_friendly_tool_execution_error(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.TOOL_EXECUTION,
            stage_before="EXECUTING",
            action="calculate_micro_emission",
            error="Missing required parameter: vehicle_type",
        )
        friendly = t.to_user_friendly()
        assert len(friendly) == 1
        assert friendly[0]["status"] == "error"

    def test_to_user_friendly_skips_state_transition(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.STATE_TRANSITION,
            stage_before="INPUT_RECEIVED",
            stage_after="GROUNDED",
        )
        friendly = t.to_user_friendly()
        assert len(friendly) == 0

    def test_to_user_friendly_clarification(self):
        t = Trace.start()
        t.record(
            step_type=TraceStepType.CLARIFICATION,
            stage_before="NEEDS_CLARIFICATION",
            reasoning="Missing pollutant specification",
        )
        friendly = t.to_user_friendly()
        assert len(friendly) == 1
        assert friendly[0]["status"] == "warning"

    def test_full_workflow_trace(self):
        """Simulate a complete file→tool→synthesis trace."""
        t = Trace.start(session_id="full-test")
        t.record(
            step_type=TraceStepType.FILE_GROUNDING,
            stage_before="INPUT_RECEIVED",
            action="analyze_file",
            output_summary={"task_type": "macro_emission"},
            confidence=0.9,
            reasoning="Column 'speed' + 'flow' + 'length' detected",
        )
        t.record(
            step_type=TraceStepType.TOOL_SELECTION,
            stage_before="INPUT_RECEIVED",
            stage_after="GROUNDED",
            action="calculate_macro_emission",
        )
        t.record(
            step_type=TraceStepType.TOOL_EXECUTION,
            stage_before="EXECUTING",
            action="calculate_macro_emission",
            output_summary={"success": True},
            duration_ms=500.0,
        )
        t.record(
            step_type=TraceStepType.SYNTHESIS,
            stage_before="DONE",
            reasoning="Results synthesized",
        )
        t.finish("DONE")

        d = t.to_dict()
        assert d["step_count"] == 4
        assert json.dumps(d)

        friendly = t.to_user_friendly()
        assert len(friendly) == 4
        assert friendly[0]["step_type"] == "file_grounding"
        assert friendly[1]["step_type"] == "tool_selection"
        assert friendly[2]["step_type"] == "tool_execution"
        assert friendly[3]["step_type"] == "synthesis"
```

## 6. Test Results
### `pytest tests/test_trace.py -v`
```text
============================= test session starts ==============================
platform linux -- Python 3.13.9, pytest-9.0.2, pluggy-1.5.0 -- /home/kirito/miniconda3/bin/python3.13
cachedir: .pytest_cache
rootdir: /home/kirito/Agent1/emission_agent
configfile: pyproject.toml
plugins: anyio-4.12.1
collecting ... collected 13 items

tests/test_trace.py::TestTraceStep::test_to_dict_excludes_none PASSED    [  7%]
tests/test_trace.py::TestTraceStep::test_to_dict_includes_set_fields PASSED [ 15%]
tests/test_trace.py::TestTrace::test_start_creates_with_timestamp PASSED [ 23%]
tests/test_trace.py::TestTrace::test_record_appends_step PASSED          [ 30%]
tests/test_trace.py::TestTrace::test_record_auto_increments_index PASSED [ 38%]
tests/test_trace.py::TestTrace::test_finish_sets_end_time_and_duration PASSED [ 46%]
tests/test_trace.py::TestTrace::test_to_dict_serializable PASSED         [ 53%]
tests/test_trace.py::TestTrace::test_to_user_friendly_file_grounding PASSED [ 61%]
tests/test_trace.py::TestTrace::test_to_user_friendly_tool_execution_success PASSED [ 69%]
tests/test_trace.py::TestTrace::test_to_user_friendly_tool_execution_error PASSED [ 76%]
tests/test_trace.py::TestTrace::test_to_user_friendly_skips_state_transition PASSED [ 84%]
tests/test_trace.py::TestTrace::test_to_user_friendly_clarification PASSED [ 92%]
tests/test_trace.py::TestTrace::test_full_workflow_trace PASSED          [100%]

============================== 13 passed in 0.56s ==============================
```

### `pytest tests/test_router_state_loop.py -v`
```text
============================= test session starts ==============================
platform linux -- Python 3.13.9, pytest-9.0.2, pluggy-1.5.0 -- /home/kirito/miniconda3/bin/python3.13
cachedir: .pytest_cache
rootdir: /home/kirito/Agent1/emission_agent
configfile: pyproject.toml
plugins: anyio-4.12.1
collecting ... collected 4 items

tests/test_router_state_loop.py::test_legacy_loop_unchanged[asyncio] PASSED [ 25%]
tests/test_router_state_loop.py::test_state_loop_no_tool_call[asyncio] PASSED [ 50%]
tests/test_router_state_loop.py::test_state_loop_with_tool_call[asyncio] PASSED [ 75%]
tests/test_router_state_loop.py::test_state_loop_produces_trace[asyncio] PASSED [100%]

============================== 4 passed in 0.56s ===============================
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
collected 106 items

tests/test_api_chart_utils.py::test_build_emission_chart_data_single_pollutant_preserves_curve_shape PASSED [  0%]
tests/test_api_chart_utils.py::test_build_emission_chart_data_multi_pollutant_converts_speed_curve_to_curve PASSED [  1%]
tests/test_api_chart_utils.py::test_extract_key_points_supports_direct_and_legacy_formats PASSED [  2%]
tests/test_api_chart_utils.py::test_routes_module_keeps_chart_helper_names PASSED [  3%]
tests/test_api_response_utils.py::test_clean_reply_text_removes_json_blocks_and_extra_blank_lines PASSED [  4%]
tests/test_api_response_utils.py::test_friendly_error_message_handles_connection_failures PASSED [  5%]
tests/test_api_response_utils.py::test_normalize_and_attach_download_metadata_preserve_existing_shape PASSED [  6%]
tests/test_api_response_utils.py::test_routes_module_keeps_helper_names_and_health_route_registration PASSED [  7%]
tests/test_api_route_contracts.py::test_api_status_routes_return_expected_top_level_shape[asyncio] PASSED [  8%]
tests/test_api_route_contracts.py::test_file_preview_route_detects_trajectory_csv_with_expected_warnings[asyncio] PASSED [  9%]
tests/test_api_route_contracts.py::test_session_routes_create_list_and_history_backfill_legacy_download_metadata[asyncio] PASSED [ 10%]
tests/test_calculators.py::TestVSPCalculator::test_idle_opmode PASSED    [ 11%]
tests/test_calculators.py::TestVSPCalculator::test_low_speed_opmode PASSED [ 12%]
tests/test_calculators.py::TestVSPCalculator::test_medium_speed_opmode PASSED [ 13%]
tests/test_calculators.py::TestVSPCalculator::test_high_speed_opmode PASSED [ 14%]
tests/test_calculators.py::TestVSPCalculator::test_vsp_calculation_passenger_car PASSED [ 15%]
tests/test_calculators.py::TestVSPCalculator::test_vsp_with_acceleration PASSED [ 16%]
tests/test_calculators.py::TestVSPCalculator::test_vsp_bin_range PASSED  [ 16%]
tests/test_calculators.py::TestVSPCalculator::test_trajectory_vsp_batch PASSED [ 17%]
tests/test_calculators.py::TestVSPCalculator::test_invalid_vehicle_type_raises PASSED [ 18%]
tests/test_calculators.py::TestMicroEmissionCalculator::test_simple_trajectory_calculation PASSED [ 19%]
tests/test_calculators.py::TestMicroEmissionCalculator::test_summary_statistics PASSED [ 20%]
tests/test_calculators.py::TestMicroEmissionCalculator::test_unknown_vehicle_type_error PASSED [ 21%]
tests/test_calculators.py::TestMicroEmissionCalculator::test_empty_trajectory_error PASSED [ 22%]
tests/test_calculators.py::TestMicroEmissionCalculator::test_year_to_age_group PASSED [ 23%]
tests/test_calculators.py::TestMacroEmissionCalculator::test_load_emission_matrix_reuses_cached_dataframe PASSED [ 24%]
tests/test_calculators.py::TestMacroEmissionCalculator::test_query_emission_rate_matches_legacy_scan PASSED [ 25%]
tests/test_calculators.py::TestMacroEmissionCalculator::test_query_emission_rate_rebuilds_lookup_for_external_matrix PASSED [ 26%]
tests/test_calculators.py::TestMacroEmissionCalculator::test_calculate_matches_legacy_lookup_path PASSED [ 27%]
tests/test_calculators.py::TestEmissionFactorCalculator::test_vehicle_type_mapping_complete PASSED [ 28%]
tests/test_calculators.py::TestEmissionFactorCalculator::test_pollutant_mapping_complete PASSED [ 29%]
tests/test_config.py::TestConfigLoading::test_config_creates_successfully PASSED [ 30%]
tests/test_config.py::TestConfigLoading::test_config_singleton PASSED    [ 31%]
tests/test_config.py::TestConfigLoading::test_config_reset PASSED        [ 32%]
tests/test_config.py::TestConfigLoading::test_feature_flags_default_true PASSED [ 33%]
tests/test_config.py::TestConfigLoading::test_feature_flag_override PASSED [ 33%]
tests/test_config.py::TestConfigLoading::test_directories_created PASSED [ 34%]
tests/test_config.py::TestJWTSecretLoading::test_jwt_secret_from_env PASSED [ 35%]
tests/test_config.py::TestJWTSecretLoading::test_auth_module_loads_dotenv_before_reading_secret PASSED [ 36%]
tests/test_config.py::TestJWTSecretLoading::test_jwt_default_is_not_production_safe PASSED [ 37%]
tests/test_micro_excel_handler.py::test_read_trajectory_from_excel_strips_columns_without_stdout_noise PASSED [ 38%]
tests/test_phase1b_consolidation.py::test_sync_llm_package_export_uses_purpose_assignment PASSED [ 39%]
tests/test_phase1b_consolidation.py::test_async_llm_service_uses_purpose_assignment PASSED [ 40%]
tests/test_phase1b_consolidation.py::test_async_llm_factory_uses_purpose_default_model PASSED [ 41%]
tests/test_phase1b_consolidation.py::test_async_llm_factory_preserves_explicit_model_override PASSED [ 42%]
tests/test_phase1b_consolidation.py::test_legacy_micro_skill_import_path_remains_available PASSED [ 43%]
tests/test_router_contracts.py::test_build_memory_tool_calls_compacts_large_payloads_for_follow_up_turns PASSED [ 44%]
tests/test_router_contracts.py::test_router_memory_utils_match_core_router_compatibility_wrappers PASSED [ 45%]
tests/test_router_contracts.py::test_router_payload_utils_match_core_router_compatibility_wrappers PASSED [ 46%]
tests/test_router_contracts.py::test_router_render_utils_match_core_router_compatibility_wrappers PASSED [ 47%]
tests/test_router_contracts.py::test_router_synthesis_utils_match_core_router_compatibility_wrappers PASSED [ 48%]
tests/test_router_contracts.py::test_maybe_short_circuit_synthesis_covers_knowledge_failure_and_single_tool_paths PASSED [ 49%]
tests/test_router_contracts.py::test_build_synthesis_request_and_keyword_detection_preserve_llm_input_contract PASSED [ 50%]
tests/test_router_contracts.py::test_render_single_tool_success_formats_micro_results_with_key_sections PASSED [ 50%]
tests/test_router_contracts.py::test_filter_results_and_error_formatting_keep_retry_and_synthesis_signal PASSED [ 51%]
tests/test_router_contracts.py::test_extract_chart_data_prefers_explicit_chart_payload PASSED [ 52%]
tests/test_router_contracts.py::test_extract_chart_data_formats_emission_factor_curves_for_frontend PASSED [ 53%]
tests/test_router_contracts.py::test_extract_table_data_formats_macro_results_preview_for_frontend PASSED [ 54%]
tests/test_router_contracts.py::test_extract_table_data_formats_emission_factor_preview_for_frontend PASSED [ 55%]
tests/test_router_contracts.py::test_extract_table_data_formats_micro_results_preview_for_frontend PASSED [ 56%]
tests/test_router_contracts.py::test_extract_download_and_map_payloads_support_current_and_legacy_locations PASSED [ 57%]
tests/test_router_contracts.py::test_format_results_as_fallback_preserves_success_and_error_sections PASSED [ 58%]
tests/test_router_contracts.py::test_synthesize_results_calls_llm_with_built_request_and_returns_content[asyncio] PASSED [ 59%]
tests/test_router_contracts.py::test_synthesize_results_short_circuits_failures_without_calling_llm[asyncio] PASSED [ 60%]
tests/test_router_state_loop.py::test_legacy_loop_unchanged[asyncio] PASSED [ 61%]
tests/test_router_state_loop.py::test_state_loop_no_tool_call[asyncio] PASSED [ 62%]
tests/test_router_state_loop.py::test_state_loop_with_tool_call[asyncio] PASSED [ 63%]
tests/test_router_state_loop.py::test_state_loop_produces_trace[asyncio] PASSED [ 64%]
tests/test_smoke_suite.py::test_run_smoke_suite_writes_summary_with_expected_defaults PASSED [ 65%]
tests/test_standardizer.py::TestVehicleStandardization::test_exact_english PASSED [ 66%]
tests/test_standardizer.py::TestVehicleStandardization::test_exact_chinese PASSED [ 66%]
tests/test_standardizer.py::TestVehicleStandardization::test_alias_chinese PASSED [ 67%]
tests/test_standardizer.py::TestVehicleStandardization::test_case_insensitive PASSED [ 68%]
tests/test_standardizer.py::TestVehicleStandardization::test_unknown_returns_none PASSED [ 69%]
tests/test_standardizer.py::TestVehicleStandardization::test_empty_returns_none PASSED [ 70%]
tests/test_standardizer.py::TestVehicleStandardization::test_suggestions_non_empty PASSED [ 71%]
tests/test_standardizer.py::TestPollutantStandardization::test_exact_english PASSED [ 72%]
tests/test_standardizer.py::TestPollutantStandardization::test_case_insensitive PASSED [ 73%]
tests/test_standardizer.py::TestPollutantStandardization::test_chinese_name PASSED [ 74%]
tests/test_standardizer.py::TestPollutantStandardization::test_unknown_returns_none PASSED [ 75%]
tests/test_standardizer.py::TestPollutantStandardization::test_suggestions_non_empty PASSED [ 76%]
tests/test_standardizer.py::TestColumnMapping::test_micro_speed_column PASSED [ 77%]
tests/test_standardizer.py::TestColumnMapping::test_empty_columns PASSED [ 78%]
tests/test_task_state.py::test_initialize_without_file PASSED            [ 79%]
tests/test_task_state.py::test_initialize_with_file PASSED               [ 80%]
tests/test_task_state.py::test_initialize_with_memory PASSED             [ 81%]
tests/test_task_state.py::test_valid_transitions PASSED                  [ 82%]
tests/test_task_state.py::test_invalid_transition_raises PASSED          [ 83%]
tests/test_task_state.py::test_should_stop_at_terminal[DONE] PASSED      [ 83%]
tests/test_task_state.py::test_should_stop_at_terminal[NEEDS_CLARIFICATION] PASSED [ 84%]
tests/test_task_state.py::test_should_stop_at_max_steps PASSED           [ 85%]
tests/test_task_state.py::test_to_dict_serializable PASSED               [ 86%]
tests/test_task_state.py::test_update_file_context PASSED                [ 87%]
tests/test_trace.py::TestTraceStep::test_to_dict_excludes_none PASSED    [ 88%]
tests/test_trace.py::TestTraceStep::test_to_dict_includes_set_fields PASSED [ 89%]
tests/test_trace.py::TestTrace::test_start_creates_with_timestamp PASSED [ 90%]
tests/test_trace.py::TestTrace::test_record_appends_step PASSED          [ 91%]
tests/test_trace.py::TestTrace::test_record_auto_increments_index PASSED [ 92%]
tests/test_trace.py::TestTrace::test_finish_sets_end_time_and_duration PASSED [ 93%]
tests/test_trace.py::TestTrace::test_to_dict_serializable PASSED         [ 94%]
tests/test_trace.py::TestTrace::test_to_user_friendly_file_grounding PASSED [ 95%]
tests/test_trace.py::TestTrace::test_to_user_friendly_tool_execution_success PASSED [ 96%]
tests/test_trace.py::TestTrace::test_to_user_friendly_tool_execution_error PASSED [ 97%]
tests/test_trace.py::TestTrace::test_to_user_friendly_skips_state_transition PASSED [ 98%]
tests/test_trace.py::TestTrace::test_to_user_friendly_clarification PASSED [ 99%]
tests/test_trace.py::TestTrace::test_full_workflow_trace PASSED          [100%]

=============================== warnings summary ===============================
api/main.py:73
  /home/kirito/Agent1/emission_agent/api/main.py:73: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.

          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).

    @app.on_event("startup")

../../miniconda3/lib/python3.13/site-packages/fastapi/applications.py:4573
../../miniconda3/lib/python3.13/site-packages/fastapi/applications.py:4573
  /home/kirito/miniconda3/lib/python3.13/site-packages/fastapi/applications.py:4573: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.

          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).

    return self.router.on_event(event_type)

api/main.py:88
  /home/kirito/Agent1/emission_agent/api/main.py:88: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.

          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).

    @app.on_event("shutdown")

tests/test_api_route_contracts.py: 12 warnings
  /home/kirito/Agent1/emission_agent/api/logging_config.py:28: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    "timestamp": datetime.utcnow().isoformat() + "Z",

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================= 106 passed, 16 warnings in 4.75s =======================
```

## 7. Output of `python main.py health`
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

## 8. Issues Encountered and Resolutions
- The `EXECUTING` stage has a retry path that re-enters the same stage without a formal `TaskState.transition()`. If left unchanged, `steps_taken` would stop advancing and the retry loop could run indefinitely. I preserved the Sprint 1 safeguard by keeping `state.control.steps_taken += 1` when a retry returns new tool calls.
- Sprint 2 required structured trace output in state mode while still keeping legacy mode compatible. I resolved that by leaving the legacy ad-hoc trace dict intact and only attaching it back onto `RouterResponse.trace` at the end of `_run_legacy_loop()` when `enable_trace` is on.
