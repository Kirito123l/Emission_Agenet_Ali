# Sprint 1: TaskState Data Structure + Router State-Driven Loop

## Modified Files

- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py): added the new state-machine data model, serialization helpers, memory restoration, and file-grounding update logic.
- [config.py](/home/kirito/Agent1/emission_agent/config.py): added `enable_state_orchestration`, `enable_trace`, and `max_orchestration_steps`.
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py): added `trace` to `RouterResponse`, moved the old `chat()` body into `_run_legacy_loop()`, added state-loop dispatch and handlers.
- [api/session.py](/home/kirito/Agent1/emission_agent/api/session.py): now creates/passes a trace dict and returns `trace` from router results.
- [api/models.py](/home/kirito/Agent1/emission_agent/api/models.py): added optional `trace` to `ChatResponse`.
- [api/routes.py](/home/kirito/Agent1/emission_agent/api/routes.py): now forwards `trace` in `/api/chat` responses and excludes `None` fields from that route response.
- [tests/test_task_state.py](/home/kirito/Agent1/emission_agent/tests/test_task_state.py): added required TaskState coverage.
- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py): added legacy dispatch and new state-loop coverage.

## `core/task_state.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskStage(str, Enum):
    INPUT_RECEIVED = "INPUT_RECEIVED"
    GROUNDED = "GROUNDED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    EXECUTING = "EXECUTING"
    DONE = "DONE"


class ParamStatus(str, Enum):
    OK = "OK"
    PENDING = "PENDING"
    MISSING = "MISSING"
    AMBIGUOUS = "AMBIGUOUS"


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        if hasattr(value, "to_dict"):
            return value.to_dict()
        return {
            item.name: _serialize_value(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, dict):
        return {key: _serialize_value(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    return value


@dataclass
class ParamEntry:
    raw: Optional[str] = None
    normalized: Optional[str] = None
    status: ParamStatus = ParamStatus.MISSING
    confidence: Optional[float] = None
    strategy: Optional[str] = None  # exact / alias / fuzzy / abstain

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw": self.raw,
            "normalized": self.normalized,
            "status": self.status.value,
            "confidence": self.confidence,
            "strategy": self.strategy,
        }


@dataclass
class FileContext:
    has_file: bool = False
    file_path: Optional[str] = None
    grounded: bool = False
    task_type: Optional[str] = None
    confidence: Optional[float] = None
    column_mapping: Dict[str, Any] = field(default_factory=dict)
    evidence: List[str] = field(default_factory=list)
    row_count: Optional[int] = None
    columns: List[str] = field(default_factory=list)
    sample_rows: Optional[List[Dict]] = None
    micro_mapping: Optional[Dict] = None
    macro_mapping: Optional[Dict] = None
    micro_has_required: Optional[bool] = None
    macro_has_required: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_file": self.has_file,
            "file_path": self.file_path,
            "grounded": self.grounded,
            "task_type": self.task_type,
            "confidence": self.confidence,
            "column_mapping": _serialize_value(self.column_mapping),
            "evidence": list(self.evidence),
            "row_count": self.row_count,
            "columns": list(self.columns),
            "sample_rows": _serialize_value(self.sample_rows),
            "micro_mapping": _serialize_value(self.micro_mapping),
            "macro_mapping": _serialize_value(self.macro_mapping),
            "micro_has_required": self.micro_has_required,
            "macro_has_required": self.macro_has_required,
        }


@dataclass
class ExecutionContext:
    selected_tool: Optional[str] = None
    completed_tools: List[str] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    last_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_tool": self.selected_tool,
            "completed_tools": list(self.completed_tools),
            "tool_results": _serialize_value(self.tool_results),
            "last_error": self.last_error,
        }


@dataclass
class ControlState:
    steps_taken: int = 0
    max_steps: int = 4
    needs_user_input: bool = False
    clarification_question: Optional[str] = None
    stop_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "steps_taken": self.steps_taken,
            "max_steps": self.max_steps,
            "needs_user_input": self.needs_user_input,
            "clarification_question": self.clarification_question,
            "stop_reason": self.stop_reason,
        }


@dataclass
class TaskState:
    stage: TaskStage = TaskStage.INPUT_RECEIVED
    file_context: FileContext = field(default_factory=FileContext)
    parameters: Dict[str, ParamEntry] = field(default_factory=dict)
    execution: ExecutionContext = field(default_factory=ExecutionContext)
    control: ControlState = field(default_factory=ControlState)
    session_id: Optional[str] = None
    user_message: Optional[str] = None
    _llm_response: Optional[Any] = field(default=None, repr=False)

    @classmethod
    def initialize(
        cls,
        user_message: Optional[str],
        file_path: Optional[str],
        memory_dict: Optional[Dict[str, Any]],
        session_id: Optional[str],
    ) -> TaskState:
        state = cls(session_id=session_id, user_message=user_message)

        if file_path:
            state.file_context.has_file = True
            state.file_context.file_path = str(file_path)

        memory_dict = memory_dict or {}

        recent_vehicle = memory_dict.get("recent_vehicle")
        if recent_vehicle:
            vehicle_value = str(recent_vehicle)
            state.parameters["vehicle_type"] = ParamEntry(
                raw=vehicle_value,
                normalized=vehicle_value,
                status=ParamStatus.OK,
                confidence=1.0,
                strategy="exact",
            )

        recent_pollutants = memory_dict.get("recent_pollutants") or []
        if recent_pollutants:
            pollutant_value = ", ".join(str(item) for item in recent_pollutants)
            state.parameters["pollutants"] = ParamEntry(
                raw=pollutant_value,
                normalized=pollutant_value,
                status=ParamStatus.OK,
                confidence=1.0,
                strategy="exact",
            )

        recent_year = memory_dict.get("recent_year")
        if recent_year is not None:
            year_value = str(recent_year)
            state.parameters["model_year"] = ParamEntry(
                raw=year_value,
                normalized=year_value,
                status=ParamStatus.OK,
                confidence=1.0,
                strategy="exact",
            )

        if not file_path:
            active_file = memory_dict.get("active_file")
            file_analysis = memory_dict.get("file_analysis")
            if active_file:
                state.file_context.has_file = True
                state.file_context.file_path = str(active_file)
                if isinstance(file_analysis, dict):
                    state.update_file_context(file_analysis)

        return state

    def transition(self, new_stage: TaskStage, reason: str = "") -> None:
        valid_targets = self._valid_transitions()
        if new_stage not in valid_targets:
            raise ValueError(f"Invalid transition: {self.stage.value} -> {new_stage.value}")
        self.stage = new_stage
        self.control.steps_taken += 1
        if reason:
            self.control.stop_reason = reason

    def _valid_transitions(self) -> List[TaskStage]:
        transition_map = {
            TaskStage.INPUT_RECEIVED: [
                TaskStage.GROUNDED,
                TaskStage.NEEDS_CLARIFICATION,
                TaskStage.DONE,
            ],
            TaskStage.GROUNDED: [
                TaskStage.EXECUTING,
                TaskStage.NEEDS_CLARIFICATION,
                TaskStage.DONE,
            ],
            TaskStage.NEEDS_CLARIFICATION: [],
            TaskStage.EXECUTING: [
                TaskStage.DONE,
                TaskStage.NEEDS_CLARIFICATION,
            ],
            TaskStage.DONE: [],
        }
        return transition_map[self.stage]

    def is_terminal(self) -> bool:
        return self.stage in {TaskStage.DONE, TaskStage.NEEDS_CLARIFICATION}

    def should_stop(self) -> bool:
        return self.is_terminal() or self.control.steps_taken >= self.control.max_steps

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage.value,
            "file_context": self.file_context.to_dict(),
            "parameters": {
                key: value.to_dict()
                for key, value in self.parameters.items()
            },
            "execution": self.execution.to_dict(),
            "control": self.control.to_dict(),
            "session_id": self.session_id,
            "user_message": self.user_message,
        }

    def update_file_context(self, analysis_dict: Dict[str, Any]) -> None:
        if not isinstance(analysis_dict, dict):
            return

        if analysis_dict.get("file_path"):
            self.file_context.file_path = str(analysis_dict["file_path"])
        self.file_context.has_file = bool(self.file_context.file_path)
        self.file_context.task_type = analysis_dict.get("task_type")
        self.file_context.confidence = analysis_dict.get("confidence")
        self.file_context.columns = list(analysis_dict.get("columns") or [])
        self.file_context.row_count = analysis_dict.get("row_count")
        self.file_context.sample_rows = analysis_dict.get("sample_rows")
        self.file_context.micro_mapping = analysis_dict.get("micro_mapping")
        self.file_context.macro_mapping = analysis_dict.get("macro_mapping")
        self.file_context.micro_has_required = analysis_dict.get("micro_has_required")
        self.file_context.macro_has_required = analysis_dict.get("macro_has_required")
        self.file_context.column_mapping = {}
        if self.file_context.task_type == "micro_emission" and self.file_context.micro_mapping:
            self.file_context.column_mapping = dict(self.file_context.micro_mapping)
        elif self.file_context.task_type == "macro_emission" and self.file_context.macro_mapping:
            self.file_context.column_mapping = dict(self.file_context.macro_mapping)

        evidence = analysis_dict.get("evidence")
        if isinstance(evidence, list):
            self.file_context.evidence = [str(item) for item in evidence]
        else:
            derived_evidence: List[str] = []
            if self.file_context.task_type:
                derived_evidence.append(f"task_type={self.file_context.task_type}")
            if self.file_context.confidence is not None:
                derived_evidence.append(f"confidence={self.file_context.confidence}")
            self.file_context.evidence = derived_evidence
        self.file_context.grounded = True
```

## New Router Methods

```python
    async def chat(
        self,
        user_message: str,
        file_path: Optional[str] = None,
        trace: Optional[Dict[str, Any]] = None,
    ) -> RouterResponse:
        config = get_config()
        if config.enable_state_orchestration:
            return await self._run_state_loop(user_message, file_path, trace)
        else:
            return await self._run_legacy_loop(user_message, file_path, trace)

    async def _run_state_loop(
        self,
        user_message: str,
        file_path: Optional[str] = None,
        trace: Optional[Dict[str, Any]] = None,
    ) -> RouterResponse:
        start_time = time.time()
        config = get_config()

        fact_memory = self.memory.get_fact_memory()
        state = TaskState.initialize(
            user_message=user_message,
            file_path=file_path,
            memory_dict=fact_memory,
            session_id=self.session_id,
        )
        state.control.max_steps = config.max_orchestration_steps

        while not state.should_stop():
            if state.stage == TaskStage.INPUT_RECEIVED:
                await self._state_handle_input(state)
            elif state.stage == TaskStage.GROUNDED:
                await self._state_handle_grounded(state)
            elif state.stage == TaskStage.EXECUTING:
                await self._state_handle_executing(state)

        if not state.is_terminal():
            state.transition(TaskStage.DONE, reason="max steps reached")

        response = await self._state_build_response(state, user_message)

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

        if trace is not None:
            trace["task_state"] = state.to_dict()
            trace["duration"] = round(time.time() - start_time, 2)
            response.trace = trace

        return response

    async def _state_handle_input(self, state: TaskState) -> None:
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
            state.transition(TaskStage.GROUNDED, reason="LLM selected tool(s)")
        else:
            state.execution.tool_results = [{"text": response.content, "no_tool": True}]
            state.transition(TaskStage.DONE, reason="LLM responded without tool calls")

    async def _state_handle_grounded(self, state: TaskState) -> None:
        state.transition(TaskStage.EXECUTING, reason="proceeding to execution")

    async def _state_handle_executing(self, state: TaskState) -> None:
        response = state._llm_response
        if not response or not response.tool_calls:
            state.execution.tool_results = [{"text": getattr(response, "content", ""), "no_tool": True}]
            state.transition(TaskStage.DONE, reason="missing tool calls during execution")
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

        tool_results = []
        completed_tools: List[str] = []
        for tool_call in response.tool_calls:
            logger.info(f"Executing tool: {tool_call.name}")
            logger.debug(f"Tool arguments: {tool_call.arguments}")

            result = await self.executor.execute(
                tool_name=tool_call.name,
                arguments=tool_call.arguments,
                file_path=state.file_context.file_path
            )

            logger.info(f"Tool {tool_call.name} completed. Success: {result.get('success')}, Error: {result.get('error')}")
            if result.get('error'):
                logger.error(f"Tool error message: {result.get('message', 'No message')}")

            tool_results.append({
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "result": result
            })
            completed_tools.append(tool_call.name)

        state.execution.tool_results = tool_results
        state.execution.completed_tools.extend(completed_tools)

        has_error = any(item["result"].get("error") for item in tool_results)

        if has_error and state.control.steps_taken < state.control.max_steps - 1:
            error_messages = self._format_tool_errors(tool_results)
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
                "tool_call_id": tool_results[0]["tool_call_id"]
            })

            retry_response = await self.llm.chat_with_tools(
                messages=context.messages,
                tools=context.tools,
                system=context.system_prompt
            )

            state._llm_response = retry_response
            if retry_response.tool_calls:
                state.execution.selected_tool = retry_response.tool_calls[0].name
                # Count the additional orchestration turn even though the stage remains EXECUTING.
                state.control.steps_taken += 1
                return

            state.execution.tool_results = [{"text": retry_response.content, "no_tool": True}]
            state.transition(TaskStage.DONE, reason="retry completed without tool calls")
            return

        state.transition(TaskStage.DONE, reason="execution completed")

    async def _state_build_response(self, state: TaskState, user_message: str) -> RouterResponse:
        if state.stage == TaskStage.NEEDS_CLARIFICATION:
            return RouterResponse(text=state.control.clarification_question or "Could you provide more details?")

        if state.execution.tool_results and state.execution.tool_results[0].get("no_tool"):
            return RouterResponse(text=state.execution.tool_results[0].get("text", ""))

        if state.execution.tool_results:
            context = getattr(state, "_assembled_context", None)
            if context is None:
                context = type("StateContext", (), {"messages": [{"content": user_message}]})()
            synthesis_text = await self._synthesize_results(
                context,
                state._llm_response,
                state.execution.tool_results
            )
            chart_data = self._extract_chart_data(state.execution.tool_results)
            table_data = self._extract_table_data(state.execution.tool_results)
            map_data = self._extract_map_data(state.execution.tool_results)
            download_file = self._extract_download_file(state.execution.tool_results)

            return RouterResponse(
                text=synthesis_text,
                chart_data=chart_data,
                table_data=table_data,
                map_data=map_data,
                download_file=download_file,
                executed_tool_calls=self._build_memory_tool_calls(state.execution.tool_results),
            )

        return RouterResponse(text="I wasn't able to process your request. Could you try again?")
```

## `tests/test_task_state.py`

```python
"""Tests for the state orchestration data structures."""

from __future__ import annotations

import json

import pytest

from core.task_state import FileContext, ParamStatus, TaskStage, TaskState


def test_initialize_without_file():
    state = TaskState.initialize(
        user_message="hello",
        file_path=None,
        memory_dict={},
        session_id="session-1",
    )

    assert state.stage == TaskStage.INPUT_RECEIVED
    assert state.file_context.has_file is False
    assert state.file_context.file_path is None


def test_initialize_with_file(tmp_path):
    file_path = tmp_path / "input.csv"
    state = TaskState.initialize(
        user_message="analyze this file",
        file_path=str(file_path),
        memory_dict={},
        session_id="session-1",
    )

    assert state.stage == TaskStage.INPUT_RECEIVED
    assert state.file_context.has_file is True
    assert state.file_context.file_path == str(file_path)


def test_initialize_with_memory(tmp_path):
    active_file = tmp_path / "cached.csv"
    memory_dict = {
        "recent_vehicle": "Passenger Car",
        "recent_pollutants": ["CO2", "NOx"],
        "recent_year": 2022,
        "active_file": str(active_file),
        "file_analysis": {
            "file_path": str(active_file),
            "task_type": "micro_emission",
            "confidence": 0.92,
            "columns": ["time", "speed"],
            "row_count": 12,
            "sample_rows": [{"time": 0, "speed": 10}],
            "micro_mapping": {"speed": "speed_kph"},
            "macro_mapping": {},
            "micro_has_required": True,
            "macro_has_required": False,
        },
    }

    state = TaskState.initialize(
        user_message="continue",
        file_path=None,
        memory_dict=memory_dict,
        session_id="session-1",
    )

    assert state.parameters["vehicle_type"].status == ParamStatus.OK
    assert state.parameters["vehicle_type"].normalized == "Passenger Car"
    assert state.parameters["pollutants"].normalized == "CO2, NOx"
    assert state.parameters["model_year"].normalized == "2022"
    assert state.file_context.has_file is True
    assert state.file_context.file_path == str(active_file)
    assert state.file_context.grounded is True
    assert state.file_context.task_type == "micro_emission"


def test_valid_transitions():
    state = TaskState()

    state.transition(TaskStage.GROUNDED)
    assert state.stage == TaskStage.GROUNDED

    state.transition(TaskStage.EXECUTING)
    assert state.stage == TaskStage.EXECUTING

    state.transition(TaskStage.DONE)
    assert state.stage == TaskStage.DONE


def test_invalid_transition_raises():
    state = TaskState()

    with pytest.raises(ValueError, match="Invalid transition"):
        state.transition(TaskStage.EXECUTING)


@pytest.mark.parametrize("terminal_stage", [TaskStage.DONE, TaskStage.NEEDS_CLARIFICATION])
def test_should_stop_at_terminal(terminal_stage):
    state = TaskState(stage=terminal_stage)

    assert state.is_terminal() is True
    assert state.should_stop() is True


def test_should_stop_at_max_steps():
    state = TaskState()
    state.control.max_steps = 2
    state.control.steps_taken = 2

    assert state.should_stop() is True


def test_to_dict_serializable():
    state = TaskState(
        file_context=FileContext(has_file=True, file_path="/tmp/input.csv"),
    )
    state.parameters["vehicle_type"] = state.parameters.get(
        "vehicle_type",
        None,
    ) or TaskState.initialize(
        user_message="hello",
        file_path=None,
        memory_dict={"recent_vehicle": "Passenger Car"},
        session_id="session-1",
    ).parameters["vehicle_type"]

    payload = state.to_dict()

    json.dumps(payload)
    assert payload["stage"] == "INPUT_RECEIVED"
    assert payload["file_context"]["file_path"] == "/tmp/input.csv"


def test_update_file_context():
    state = TaskState()
    analysis_dict = {
        "file_path": "/tmp/sample.csv",
        "task_type": "micro_emission",
        "confidence": 0.95,
        "columns": ["time", "speed", "acceleration"],
        "row_count": 24,
        "sample_rows": [{"time": 0, "speed": 12.3}],
        "micro_mapping": {"speed": "speed_kph", "time": "time"},
        "macro_mapping": {"flow": "traffic_flow_vph"},
        "micro_has_required": True,
        "macro_has_required": False,
        "evidence": ["speed column matched", "time column matched"],
    }

    state.update_file_context(analysis_dict)

    assert state.file_context.has_file is True
    assert state.file_context.file_path == "/tmp/sample.csv"
    assert state.file_context.grounded is True
    assert state.file_context.task_type == "micro_emission"
    assert state.file_context.confidence == 0.95
    assert state.file_context.columns == ["time", "speed", "acceleration"]
    assert state.file_context.row_count == 24
    assert state.file_context.sample_rows == [{"time": 0, "speed": 12.3}]
    assert state.file_context.micro_mapping == {"speed": "speed_kph", "time": "time"}
    assert state.file_context.macro_mapping == {"flow": "traffic_flow_vph"}
    assert state.file_context.micro_has_required is True
    assert state.file_context.macro_has_required is False
    assert state.file_context.column_mapping == {"speed": "speed_kph", "time": "time"}
    assert state.file_context.evidence == ["speed column matched", "time column matched"]
```

## `tests/test_router_state_loop.py`

```python
"""Contract tests for the new router state loop and legacy dispatch path."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from config import get_config
from core.router import UnifiedRouter
from services.llm_client import LLMResponse, ToolCall


class FakeMemory:
    def __init__(self, fact_memory=None, working_memory=None):
        self._fact_memory = fact_memory or {}
        self._working_memory = working_memory or []
        self.update_calls = []

    def get_fact_memory(self):
        return dict(self._fact_memory)

    def get_working_memory(self):
        return list(self._working_memory)

    def update(self, user_message, assistant_response, tool_calls=None, file_path=None, file_analysis=None):
        self.update_calls.append(
            {
                "user_message": user_message,
                "assistant_response": assistant_response,
                "tool_calls": tool_calls,
                "file_path": file_path,
                "file_analysis": file_analysis,
            }
        )


def make_router(
    *,
    llm_response: LLMResponse,
    executor_result=None,
    fact_memory=None,
    working_memory=None,
) -> UnifiedRouter:
    router = object.__new__(UnifiedRouter)
    router.session_id = "test-session"
    router.runtime_config = get_config()
    router.memory = FakeMemory(fact_memory=fact_memory, working_memory=working_memory)
    router.assembler = SimpleNamespace(
        assemble=Mock(
            return_value=SimpleNamespace(
                system_prompt="system prompt",
                tools=[{"type": "function", "function": {"name": "query_emission_factors"}}],
                messages=[{"role": "user", "content": "test user message"}],
                estimated_tokens=12,
            )
        )
    )
    router.executor = SimpleNamespace(execute=AsyncMock(return_value=executor_result or {}))
    router.llm = SimpleNamespace(
        chat_with_tools=AsyncMock(return_value=llm_response),
        chat=AsyncMock(return_value=LLMResponse(content="unused synthesis")),
    )
    return router


@pytest.mark.anyio
async def test_legacy_loop_unchanged():
    config = get_config()
    config.enable_state_orchestration = False

    router = make_router(llm_response=LLMResponse(content="legacy direct response"))
    router._run_state_loop = AsyncMock(side_effect=AssertionError("state loop should not run"))

    result = await router.chat("legacy request")

    assert result.text == "legacy direct response"
    assert result.executed_tool_calls is None
    assert router._run_state_loop.await_count == 0
    assert len(router.memory.update_calls) == 1
    assert router.memory.update_calls[0]["assistant_response"] == "legacy direct response"
    assert router.assembler.assemble.call_count == 1
    assert router.llm.chat_with_tools.await_count == 1


@pytest.mark.anyio
async def test_state_loop_no_tool_call():
    config = get_config()
    config.enable_state_orchestration = True

    router = make_router(llm_response=LLMResponse(content="state direct response"))
    trace = {}

    result = await router.chat("state request", trace=trace)

    assert result.text == "state direct response"
    assert result.trace is trace
    assert result.trace["task_state"]["stage"] == "DONE"
    assert result.trace["task_state"]["execution"]["tool_results"] == [
        {"text": "state direct response", "no_tool": True}
    ]
    assert len(router.memory.update_calls) == 1
    assert router.memory.update_calls[0]["tool_calls"] is None
    assert router.llm.chat_with_tools.await_count == 1


@pytest.mark.anyio
async def test_state_loop_with_tool_call():
    config = get_config()
    config.enable_state_orchestration = True

    tool_call = ToolCall(
        id="call-1",
        name="query_emission_factors",
        arguments={"vehicle_type": "Passenger Car", "model_year": 2020},
    )
    llm_response = LLMResponse(content="calling query tool", tool_calls=[tool_call])
    executor_result = {
        "success": True,
        "summary": "查询成功",
        "data": {
            "vehicle_type": "Passenger Car",
            "model_year": 2020,
            "metadata": {"season": "夏季", "road_type": "快速路"},
            "pollutants": {
                "CO2": {
                    "speed_curve": [
                        {"speed_kph": 20.0, "emission_rate": 1.1},
                        {"speed_kph": 40.0, "emission_rate": 1.4},
                    ],
                    "unit": "g/km",
                    "typical_values": [
                        {"speed_kph": 20.0, "speed_mph": 12, "emission_rate": 1.1},
                    ],
                    "speed_range": {"min_kph": 20.0, "max_kph": 40.0},
                    "data_points": 2,
                    "data_source": "test-source",
                }
            },
        },
    }
    router = make_router(llm_response=llm_response, executor_result=executor_result)
    trace = {}

    result = await router.chat("query emission factors", trace=trace)

    assert result.text.startswith("## 排放因子查询结果")
    assert result.chart_data["type"] == "emission_factors"
    assert result.chart_data["vehicle_type"] == "Passenger Car"
    assert result.executed_tool_calls[0]["name"] == "query_emission_factors"
    assert trace["task_state"]["stage"] == "DONE"
    assert trace["task_state"]["execution"]["completed_tools"] == ["query_emission_factors"]
    assert len(router.memory.update_calls) == 1
    assert router.memory.update_calls[0]["tool_calls"][0]["name"] == "query_emission_factors"
    router.llm.chat.assert_not_awaited()
```

## Test Results

### `pytest tests/test_task_state.py -v`

```text
============================= test session starts ==============================
platform linux -- Python 3.13.9, pytest-9.0.2, pluggy-1.5.0 -- /home/kirito/miniconda3/bin/python3.13
cachedir: .pytest_cache
rootdir: /home/kirito/Agent1/emission_agent
configfile: pyproject.toml
plugins: anyio-4.12.1
collecting ... collected 10 items

tests/test_task_state.py::test_initialize_without_file PASSED            [ 10%]
tests/test_task_state.py::test_initialize_with_file PASSED               [ 20%]
tests/test_task_state.py::test_initialize_with_memory PASSED             [ 30%]
tests/test_task_state.py::test_valid_transitions PASSED                  [ 40%]
tests/test_task_state.py::test_invalid_transition_raises PASSED          [ 50%]
tests/test_task_state.py::test_should_stop_at_terminal[DONE] PASSED      [ 60%]
tests/test_task_state.py::test_should_stop_at_terminal[NEEDS_CLARIFICATION] PASSED [ 70%]
tests/test_task_state.py::test_should_stop_at_max_steps PASSED           [ 80%]
tests/test_task_state.py::test_to_dict_serializable PASSED               [ 90%]
tests/test_task_state.py::test_update_file_context PASSED                [100%]

============================== 10 passed in 0.77s ==============================
```

### `pytest tests/test_router_state_loop.py -v`

```text
============================= test session starts ==============================
platform linux -- Python 3.13.9, pytest-9.0.2, pluggy-1.5.0 -- /home/kirito/miniconda3/bin/python3.13
cachedir: .pytest_cache
rootdir: /home/kirito/Agent1/emission_agent
configfile: pyproject.toml
plugins: anyio-4.12.1
collecting ... collected 3 items

tests/test_router_state_loop.py::test_legacy_loop_unchanged[asyncio] PASSED [ 33%]
tests/test_router_state_loop.py::test_state_loop_no_tool_call[asyncio] PASSED [ 66%]
tests/test_router_state_loop.py::test_state_loop_with_tool_call[asyncio] PASSED [100%]

============================== 3 passed in 0.77s ===============================
```

### `python main.py health`

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
collected 92 items

tests/test_api_chart_utils.py::test_build_emission_chart_data_single_pollutant_preserves_curve_shape PASSED [  1%]
tests/test_api_chart_utils.py::test_build_emission_chart_data_multi_pollutant_converts_speed_curve_to_curve PASSED [  2%]
tests/test_api_chart_utils.py::test_extract_key_points_supports_direct_and_legacy_formats PASSED [  3%]
tests/test_api_chart_utils.py::test_routes_module_keeps_chart_helper_names PASSED [  4%]
tests/test_api_response_utils.py::test_clean_reply_text_removes_json_blocks_and_extra_blank_lines PASSED [  5%]
tests/test_api_response_utils.py::test_friendly_error_message_handles_connection_failures PASSED [  6%]
tests/test_api_response_utils.py::test_normalize_and_attach_download_metadata_preserve_existing_shape PASSED [  7%]
tests/test_api_response_utils.py::test_routes_module_keeps_helper_names_and_health_route_registration PASSED [  8%]
tests/test_api_route_contracts.py::test_api_status_routes_return_expected_top_level_shape[asyncio] PASSED [  9%]
tests/test_api_route_contracts.py::test_file_preview_route_detects_trajectory_csv_with_expected_warnings[asyncio] PASSED [ 10%]
tests/test_api_route_contracts.py::test_session_routes_create_list_and_history_backfill_legacy_download_metadata[asyncio] PASSED [ 11%]
tests/test_calculators.py::TestVSPCalculator::test_idle_opmode PASSED    [ 13%]
tests/test_calculators.py::TestVSPCalculator::test_low_speed_opmode PASSED [ 14%]
tests/test_calculators.py::TestVSPCalculator::test_medium_speed_opmode PASSED [ 15%]
tests/test_calculators.py::TestVSPCalculator::test_high_speed_opmode PASSED [ 16%]
tests/test_calculators.py::TestVSPCalculator::test_vsp_calculation_passenger_car PASSED [ 17%]
tests/test_calculators.py::TestVSPCalculator::test_vsp_with_acceleration PASSED [ 18%]
tests/test_calculators.py::TestVSPCalculator::test_vsp_bin_range PASSED  [ 19%]
tests/test_calculators.py::TestVSPCalculator::test_trajectory_vsp_batch PASSED [ 20%]
tests/test_calculators.py::TestVSPCalculator::test_invalid_vehicle_type_raises PASSED [ 21%]
tests/test_calculators.py::TestMicroEmissionCalculator::test_simple_trajectory_calculation PASSED [ 22%]
tests/test_calculators.py::TestMicroEmissionCalculator::test_summary_statistics PASSED [ 23%]
tests/test_calculators.py::TestMicroEmissionCalculator::test_unknown_vehicle_type_error PASSED [ 25%]
tests/test_calculators.py::TestMicroEmissionCalculator::test_empty_trajectory_error PASSED [ 26%]
tests/test_calculators.py::TestMicroEmissionCalculator::test_year_to_age_group PASSED [ 27%]
tests/test_calculators.py::TestMacroEmissionCalculator::test_load_emission_matrix_reuses_cached_dataframe PASSED [ 28%]
tests/test_calculators.py::TestMacroEmissionCalculator::test_query_emission_rate_matches_legacy_scan PASSED [ 29%]
tests/test_calculators.py::TestMacroEmissionCalculator::test_query_emission_rate_rebuilds_lookup_for_external_matrix PASSED [ 30%]
tests/test_calculators.py::TestMacroEmissionCalculator::test_calculate_matches_legacy_lookup_path PASSED [ 31%]
tests/test_calculators.py::TestEmissionFactorCalculator::test_vehicle_type_mapping_complete PASSED [ 32%]
tests/test_calculators.py::TestEmissionFactorCalculator::test_pollutant_mapping_complete PASSED [ 33%]
tests/test_config.py::TestConfigLoading::test_config_creates_successfully PASSED [ 34%]
tests/test_config.py::TestConfigLoading::test_config_singleton PASSED    [ 35%]
tests/test_config.py::TestConfigLoading::test_config_reset PASSED        [ 36%]
tests/test_config.py::TestConfigLoading::test_feature_flags_default_true PASSED [ 38%]
tests/test_config.py::TestConfigLoading::test_feature_flag_override PASSED [ 39%]
tests/test_config.py::TestConfigLoading::test_directories_created PASSED [ 40%]
tests/test_config.py::TestJWTSecretLoading::test_jwt_secret_from_env PASSED [ 41%]
tests/test_config.py::TestJWTSecretLoading::test_auth_module_loads_dotenv_before_reading_secret PASSED [ 42%]
tests/test_config.py::TestJWTSecretLoading::test_jwt_default_is_not_production_safe PASSED [ 43%]
tests/test_micro_excel_handler.py::test_read_trajectory_from_excel_strips_columns_without_stdout_noise PASSED [ 44%]
tests/test_phase1b_consolidation.py::test_sync_llm_package_export_uses_purpose_assignment PASSED [ 45%]
tests/test_phase1b_consolidation.py::test_async_llm_service_uses_purpose_assignment PASSED [ 46%]
tests/test_phase1b_consolidation.py::test_async_llm_factory_uses_purpose_default_model PASSED [ 47%]
tests/test_phase1b_consolidation.py::test_async_llm_factory_preserves_explicit_model_override PASSED [ 48%]
tests/test_phase1b_consolidation.py::test_legacy_micro_skill_import_path_remains_available PASSED [ 50%]
tests/test_router_contracts.py::test_build_memory_tool_calls_compacts_large_payloads_for_follow_up_turns PASSED [ 51%]
tests/test_router_contracts.py::test_router_memory_utils_match_core_router_compatibility_wrappers PASSED [ 52%]
tests/test_router_contracts.py::test_router_payload_utils_match_core_router_compatibility_wrappers PASSED [ 53%]
tests/test_router_contracts.py::test_router_render_utils_match_core_router_compatibility_wrappers PASSED [ 54%]
tests/test_router_contracts.py::test_router_synthesis_utils_match_core_router_compatibility_wrappers PASSED [ 55%]
tests/test_router_contracts.py::test_maybe_short_circuit_synthesis_covers_knowledge_failure_and_single_tool_paths PASSED [ 56%]
tests/test_router_contracts.py::test_build_synthesis_request_and_keyword_detection_preserve_llm_input_contract PASSED [ 57%]
tests/test_router_contracts.py::test_render_single_tool_success_formats_micro_results_with_key_sections PASSED [ 58%]
tests/test_router_contracts.py::test_filter_results_and_error_formatting_keep_retry_and_synthesis_signal PASSED [ 59%]
tests/test_router_contracts.py::test_extract_chart_data_prefers_explicit_chart_payload PASSED [ 60%]
tests/test_router_contracts.py::test_extract_chart_data_formats_emission_factor_curves_for_frontend PASSED [ 61%]
tests/test_router_contracts.py::test_extract_table_data_formats_macro_results_preview_for_frontend PASSED [ 63%]
tests/test_router_contracts.py::test_extract_table_data_formats_emission_factor_preview_for_frontend PASSED [ 64%]
tests/test_router_contracts.py::test_extract_table_data_formats_micro_results_preview_for_frontend PASSED [ 65%]
tests/test_router_contracts.py::test_extract_download_and_map_payloads_support_current_and_legacy_locations PASSED [ 66%]
tests/test_router_contracts.py::test_format_results_as_fallback_preserves_success_and_error_sections PASSED [ 67%]
tests/test_router_contracts.py::test_synthesize_results_calls_llm_with_built_request_and_returns_content[asyncio] PASSED [ 68%]
tests/test_router_contracts.py::test_synthesize_results_short_circuits_failures_without_calling_llm[asyncio] PASSED [ 69%]
tests/test_router_state_loop.py::test_legacy_loop_unchanged[asyncio] PASSED [ 70%]
tests/test_router_state_loop.py::test_state_loop_no_tool_call[asyncio] PASSED [ 71%]
tests/test_router_state_loop.py::test_state_loop_with_tool_call[asyncio] PASSED [ 72%]
tests/test_smoke_suite.py::test_run_smoke_suite_writes_summary_with_expected_defaults PASSED [ 73%]
tests/test_standardizer.py::TestVehicleStandardization::test_exact_english PASSED [ 75%]
tests/test_standardizer.py::TestVehicleStandardization::test_exact_chinese PASSED [ 76%]
tests/test_standardizer.py::TestVehicleStandardization::test_alias_chinese PASSED [ 77%]
tests/test_standardizer.py::TestVehicleStandardization::test_case_insensitive PASSED [ 78%]
tests/test_standardizer.py::TestVehicleStandardization::test_unknown_returns_none PASSED [ 79%]
tests/test_standardizer.py::TestVehicleStandardization::test_empty_returns_none PASSED [ 80%]
tests/test_standardizer.py::TestVehicleStandardization::test_suggestions_non_empty PASSED [ 81%]
tests/test_standardizer.py::TestPollutantStandardization::test_exact_english PASSED [ 82%]
tests/test_standardizer.py::TestPollutantStandardization::test_case_insensitive PASSED [ 83%]
tests/test_standardizer.py::TestPollutantStandardization::test_chinese_name PASSED [ 84%]
tests/test_standardizer.py::TestPollutantStandardization::test_unknown_returns_none PASSED [ 85%]
tests/test_standardizer.py::TestPollutantStandardization::test_suggestions_non_empty PASSED [ 86%]
tests/test_standardizer.py::TestColumnMapping::test_micro_speed_column PASSED [ 88%]
tests/test_standardizer.py::TestColumnMapping::test_empty_columns PASSED [ 89%]
tests/test_task_state.py::test_initialize_without_file PASSED            [ 90%]
tests/test_task_state.py::test_initialize_with_file PASSED               [ 91%]
tests/test_task_state.py::test_initialize_with_memory PASSED             [ 92%]
tests/test_task_state.py::test_valid_transitions PASSED                  [ 93%]
tests/test_task_state.py::test_invalid_transition_raises PASSED          [ 94%]
tests/test_task_state.py::test_should_stop_at_terminal[DONE] PASSED      [ 95%]
tests/test_task_state.py::test_should_stop_at_terminal[NEEDS_CLARIFICATION] PASSED [ 96%]
tests/test_task_state.py::test_should_stop_at_max_steps PASSED           [ 97%]
tests/test_task_state.py::test_to_dict_serializable PASSED               [ 98%]
tests/test_task_state.py::test_update_file_context PASSED                [100%]

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
======================= 92 passed, 16 warnings in 5.05s ========================
```

## Issues Encountered

- The new state loop initially risked dropping cached file-analysis metadata like `file_mtime` when persisting memory, which would have broken exact cache reuse on later turns. I resolved that by keeping the raw analyzer payload on the state object and merging it back into the serialized `file_context` before `memory.update()`.
- `RouterResponse.trace` is only populated when a trace dict is supplied to the router, so the API layer would still have returned `None` unless it actively created one. I resolved that by making [api/session.py](/home/kirito/Agent1/emission_agent/api/session.py) pass `{}` when `enable_trace` is enabled, then returning `result.trace` through the session and `/api/chat`.

92 tests now pass total: the prior 79 plus 13 new Sprint 1 tests.
