"""Naive function-calling router for baseline experiments.

This router is intentionally a minimal configured-model tool-calling loop over
the seven experiment tools, with no extra orchestration layers.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.llm_client import LLMClientService, LLMResponse, ToolCall
from tools.base import ToolResult
from tools.contract_loader import get_tool_contract_registry
from tools.registry import ToolRegistry, get_registry, init_tools

logger = logging.getLogger(__name__)


NAIVE_SYSTEM_PROMPT = """你是一个交通排放分析助手。你可以使用以下工具帮助用户完成分析任务。
请根据用户的需求选择合适的工具并填写参数。
如果用户上传了文件，文件路径会在消息中提供。"""


@dataclass
class NaiveRouterResponse:
    """Router response shape compatible with API/evaluation consumers."""

    text: str
    chart_data: Optional[Dict[str, Any]] = None
    table_data: Optional[Dict[str, Any]] = None
    map_data: Optional[Dict[str, Any]] = None
    download_file: Optional[Any] = None
    executed_tool_calls: Optional[List[Dict[str, Any]]] = None
    trace: Optional[Dict[str, Any]] = None
    trace_friendly: Optional[List[Dict[str, str]]] = None


class NaiveRouter:
    """Minimal configured-model function-calling baseline."""

    MAX_HISTORY_TURNS = 5
    MAX_TOOL_ITERATIONS = 4

    def __init__(
        self,
        session_id: str = "naive",
        *,
        llm: Optional[LLMClientService] = None,
        registry: Optional[ToolRegistry] = None,
        tool_definitions: Optional[List[Dict[str, Any]]] = None,
        tool_call_log_path: Optional[str | Path] = None,
        max_history_turns: int = MAX_HISTORY_TURNS,
        max_tool_iterations: int = MAX_TOOL_ITERATIONS,
    ):
        self.session_id = session_id
        self.llm = llm or LLMClientService(temperature=0.0, purpose="agent")
        self.registry = registry or get_registry()
        if not self.registry.list_tools():
            init_tools()
        self.tool_definitions = tool_definitions or self._load_naive_tool_definitions()
        self.history: List[Dict[str, str]] = []
        self.max_history_turns = int(max_history_turns)
        self.max_tool_iterations = int(max_tool_iterations)
        self.tool_call_log_path = Path(tool_call_log_path) if tool_call_log_path else Path(
            "logs/naive_router_tool_calls.jsonl"
        )

    def to_persisted_state(self) -> Dict[str, Any]:
        """Persist only the simple role/content history list."""
        return {
            "version": 1,
            "history": self._json_safe(self.history),
        }

    def restore_persisted_state(self, payload: Dict[str, Any]) -> None:
        """Restore simple history from a persisted payload."""
        if not isinstance(payload, dict):
            return
        history = payload.get("history")
        if not isinstance(history, list):
            return
        restored: List[Dict[str, str]] = []
        for item in history:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            content = str(item.get("content") or "")
            if role in {"user", "assistant"}:
                restored.append({"role": role, "content": content})
        self.history = restored

    @classmethod
    def _load_naive_tool_definitions(cls) -> List[Dict[str, Any]]:
        allowed = set(get_tool_contract_registry().get_naive_available_tools())
        definitions = get_tool_contract_registry().get_tool_definitions()
        return [
            item
            for item in definitions
            if item.get("function", {}).get("name") in allowed
        ]

    async def chat(
        self,
        user_message: str,
        file_path: Optional[str] = None,
        trace: Optional[Dict[str, Any]] = None,
    ) -> NaiveRouterResponse:
        """Run the naive tool-calling loop and return API/eval-compatible output."""
        current_user_message = self._build_user_message(user_message, file_path)
        messages = self._build_messages(current_user_message)
        executed_tool_calls: List[Dict[str, Any]] = []
        trace_steps: List[Dict[str, Any]] = []
        final_response: Optional[LLMResponse] = None

        for iteration in range(self.max_tool_iterations + 1):
            response = await self.llm.chat_with_tools(
                messages=messages,
                tools=self.tool_definitions,
                system=NAIVE_SYSTEM_PROMPT,
                temperature=0.0,
            )
            final_response = response

            if not response.tool_calls:
                break
            if iteration >= self.max_tool_iterations:
                logger.warning("NaiveRouter reached max tool iterations for session %s", self.session_id)
                break

            messages.append(self._assistant_tool_call_message(response))
            for tool_call in response.tool_calls:
                call_record = await self._execute_tool_call(tool_call, iteration=iteration + 1)
                executed_tool_calls.append(call_record)
                trace_steps.append(self._trace_step(call_record, iteration=iteration + 1))
                messages.append(self._tool_result_message(tool_call, call_record))

        text = (final_response.content if final_response else "") or self._fallback_text(executed_tool_calls)
        artifacts = self._collect_latest_artifacts(executed_tool_calls)
        self._append_history(current_user_message, text)

        trace_payload = trace if trace is not None else {}
        trace_payload.update(
            {
                "router_mode": "naive",
                "session_id": self.session_id,
                "steps": trace_steps,
                "final": {
                    "text": text,
                    "tool_calls": executed_tool_calls,
                },
            }
        )

        return NaiveRouterResponse(
            text=text,
            chart_data=artifacts.get("chart_data"),
            table_data=artifacts.get("table_data"),
            map_data=artifacts.get("map_data"),
            download_file=artifacts.get("download_file"),
            executed_tool_calls=executed_tool_calls,
            trace=trace_payload,
            trace_friendly=[
                {
                    "step_type": "tool_execution",
                    "description": f"{call.get('name')}: {'success' if call.get('result', {}).get('success') else 'failed'}",
                }
                for call in executed_tool_calls
            ],
        )

    def _build_user_message(self, user_message: str, file_path: Optional[str]) -> str:
        text = str(user_message or "").strip()
        if file_path and str(file_path) not in text:
            file_note = f"文件已上传，路径: {file_path}"
            return f"{text}\n\n{file_note}" if text else file_note
        return text

    def _build_messages(self, current_user_message: str) -> List[Dict[str, Any]]:
        history_limit = max(self.max_history_turns, 0) * 2
        history = self.history[-history_limit:] if history_limit else []
        return [dict(message) for message in history] + [
            {"role": "user", "content": current_user_message}
        ]

    def _append_history(self, user_message: str, assistant_response: str) -> None:
        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": assistant_response})

    def _assistant_tool_call_message(self, response: LLMResponse) -> Dict[str, Any]:
        return {
            "role": "assistant",
            "content": response.content or "",
            "tool_calls": [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": json.dumps(tool_call.arguments or {}, ensure_ascii=False),
                    },
                }
                for tool_call in (response.tool_calls or [])
            ],
        }

    def _tool_result_message(self, tool_call: ToolCall, call_record: Dict[str, Any]) -> Dict[str, Any]:
        result_payload = call_record.get("result") or {}
        return {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "name": tool_call.name,
            "content": json.dumps(result_payload, ensure_ascii=False, default=str),
        }

    async def _execute_tool_call(self, tool_call: ToolCall, *, iteration: int) -> Dict[str, Any]:
        raw_parameters = dict(tool_call.arguments or {})
        started_at = datetime.now().isoformat()
        result_payload: Dict[str, Any]
        success = False
        error_message: Optional[str] = None

        naive_tool_names = get_tool_contract_registry().get_naive_available_tools()
        if tool_call.name not in naive_tool_names:
            error_message = f"Tool not available in NaiveRouter baseline: {tool_call.name}"
            result_payload = {
                "success": False,
                "error": error_message,
                "summary": error_message,
                "data": None,
            }
        else:
            tool = self.registry.get(tool_call.name)
            if tool is None:
                error_message = f"Unknown tool: {tool_call.name}"
                result_payload = {
                    "success": False,
                    "error": error_message,
                    "summary": error_message,
                    "data": None,
                }
            else:
                try:
                    tool_result = await tool.execute(**raw_parameters)
                    result_payload = self._tool_result_to_dict(tool_result)
                    success = bool(tool_result.success)
                    error_message = None if success else (tool_result.error or result_payload.get("summary"))
                except Exception as exc:
                    error_message = str(exc)
                    result_payload = {
                        "success": False,
                        "error": error_message,
                        "summary": f"Tool execution error: {error_message}",
                        "data": None,
                    }

        call_record = {
            "id": tool_call.id,
            "name": tool_call.name,
            "arguments": self._json_safe(raw_parameters),
            "raw_parameters": self._json_safe(raw_parameters),
            "result": self._json_safe(result_payload),
            "iteration": iteration,
        }
        self._log_tool_call(
            {
                "timestamp": started_at,
                "session_id": self.session_id,
                "iteration": iteration,
                "tool_call_id": tool_call.id,
                "tool_name": tool_call.name,
                "raw_parameters": self._json_safe(raw_parameters),
                "execution_success": success,
                "error_message": error_message,
            }
        )
        return call_record

    @staticmethod
    def _tool_result_to_dict(result: ToolResult) -> Dict[str, Any]:
        return {
            "success": bool(result.success),
            "data": result.data,
            "error": result.error,
            "summary": result.summary,
            "chart_data": result.chart_data,
            "table_data": result.table_data,
            "map_data": result.map_data,
            "download_file": result.download_file,
        }

    @staticmethod
    def _trace_step(call_record: Dict[str, Any], *, iteration: int) -> Dict[str, Any]:
        result = call_record.get("result") or {}
        return {
            "step_type": "tool_execution",
            "router_mode": "naive",
            "iteration": iteration,
            "tool_name": call_record.get("name"),
            "arguments": call_record.get("arguments") or {},
            "success": bool(result.get("success")),
            "error": result.get("error"),
        }

    @staticmethod
    def _fallback_text(executed_tool_calls: List[Dict[str, Any]]) -> str:
        for call in reversed(executed_tool_calls):
            result = call.get("result") or {}
            if result.get("summary"):
                return str(result["summary"])
            if result.get("error"):
                return str(result["error"])
        return ""

    @staticmethod
    def _collect_latest_artifacts(executed_tool_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
        artifacts: Dict[str, Any] = {}
        for call in executed_tool_calls:
            result = call.get("result") or {}
            for key in ("chart_data", "table_data", "map_data", "download_file"):
                if result.get(key):
                    artifacts[key] = result[key]
        return artifacts

    def _log_tool_call(self, payload: Dict[str, Any]) -> None:
        self.tool_call_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.tool_call_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(self._json_safe(payload), ensure_ascii=False) + "\n")

    @staticmethod
    def _json_safe(payload: Any) -> Any:
        try:
            return json.loads(json.dumps(payload, ensure_ascii=False, default=str))
        except Exception:
            return str(payload)
