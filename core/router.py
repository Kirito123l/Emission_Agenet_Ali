"""
Unified Router - Main entry point for new architecture
Uses Tool Use mode, no planning layer
"""
import logging
import json
import re
import time
from typing import Dict, Optional, List, Any
from dataclasses import dataclass
from config import get_config
from core.assembler import ContextAssembler
from core.executor import ToolExecutor
from core.memory import MemoryManager
from core.router_memory_utils import (
    build_memory_tool_calls as build_memory_tool_calls_helper,
    compact_tool_data as compact_tool_data_helper,
)
from core.router_payload_utils import (
    extract_chart_data as extract_chart_data_helper,
    extract_download_file as extract_download_file_helper,
    extract_map_data as extract_map_data_helper,
    extract_table_data as extract_table_data_helper,
    format_emission_factors_chart as format_emission_factors_chart_helper,
)
from core.router_render_utils import (
    filter_results_for_synthesis as filter_results_for_synthesis_helper,
    format_results_as_fallback as format_results_as_fallback_helper,
    format_tool_errors as format_tool_errors_helper,
    format_tool_results as format_tool_results_helper,
    render_single_tool_success as render_single_tool_success_helper,
)
from core.router_synthesis_utils import (
    build_synthesis_request as build_synthesis_request_helper,
    detect_hallucination_keywords as detect_hallucination_keywords_helper,
    maybe_short_circuit_synthesis as maybe_short_circuit_synthesis_helper,
)
from services.llm_client import get_llm_client

logger = logging.getLogger(__name__)


# Synthesis-only prompt (no tool calling)
SYNTHESIS_PROMPT = """你是机动车排放计算助手。基于工具执行结果生成专业回答。

## 要求
1. 只使用工具返回的实际数据，不要编造或推算数值
2. 总结关键结果（总排放量、计算参数、统计信息）
3. query_knowledge 工具：完整保留返回的答案和参考文档
4. 其他工具：不要添加"参考文档"字样
5. 失败时说明问题并给出建议

## 工具执行结果
{results}

请生成简洁专业的回答。"""


@dataclass
class RouterResponse:
    """Router response to user"""
    text: str
    chart_data: Optional[Dict] = None
    table_data: Optional[Dict] = None
    map_data: Optional[Dict] = None
    download_file: Optional[Dict[str, Any]] = None
    executed_tool_calls: Optional[List[Dict[str, Any]]] = None


class UnifiedRouter:
    """
    Unified router - New architecture main entry point

    Design philosophy:
    - Trust LLM to make decisions
    - Use Tool Use mode (no planning JSON)
    - Standardization happens in executor (transparent)
    - Natural dialogue for clarification
    - Errors handled through conversation
    """

    MAX_TOOL_CALLS_PER_TURN = 3  # Prevent infinite loops

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.runtime_config = get_config()
        self.assembler = ContextAssembler()
        self.executor = ToolExecutor()
        self.memory = MemoryManager(session_id)
        self.llm = get_llm_client("agent", model="qwen-plus")

    async def chat(
        self,
        user_message: str,
        file_path: Optional[str] = None,
        trace: Optional[Dict[str, Any]] = None,
    ) -> RouterResponse:
        """
        Process user message

        Flow:
        1. Assemble context (prompt + tools + memory + file)
        2. Call LLM with Tool Use
        3. If tool calls → execute → synthesize
        4. If direct response → return
        5. Update memory

        Args:
            user_message: User's message
            file_path: Optional uploaded file path

        Returns:
            RouterResponse with text and optional data
        """
        logger.info(f"Processing message: {user_message[:50]}...")
        start_time = time.perf_counter()
        if trace is not None:
            trace.clear()
            trace["input"] = {
                "user_message": user_message,
                "file_path": file_path,
            }

        # 1. Analyze file if provided (use cache when available)
        file_context = None
        if file_path:
            from pathlib import Path
            import os

            cached = self.memory.get_fact_memory().get("file_analysis")
            file_path_str = str(file_path)

            # Check if file exists and get its modification time
            try:
                current_mtime = os.path.getmtime(file_path_str)
            except Exception:
                current_mtime = None

            # Use cache only if path and mtime match
            cache_valid = (
                cached
                and str(cached.get("file_path")) == file_path_str
                and cached.get("file_mtime") == current_mtime
            )

            if self.runtime_config.enable_file_analyzer and cache_valid:
                file_context = cached
                logger.info(f"Using cached file analysis for {file_path}")
            elif self.runtime_config.enable_file_analyzer:
                file_context = await self._analyze_file(file_path)
                # Store path and mtime to detect file changes
                file_context["file_path"] = file_path_str
                file_context["file_mtime"] = current_mtime
                logger.info(f"Analyzed new file: {file_path} (mtime: {current_mtime})")
            else:
                file_context = {
                    "filename": Path(file_path_str).name,
                    "file_path": file_path_str,
                    "task_type": None,
                    "confidence": 0.0,
                }
                logger.info("File analyzer disabled by runtime config")
            # Diagnostic: log memory state when file is uploaded
            wm = self.memory.get_working_memory()
            fm = self.memory.get_fact_memory()
            logger.info(
                f"[FILE UPLOAD] working_memory_turns={len(wm)}, "
                f"fact_memory={fm}, "
                f"file_task_type={file_context.get('task_type') or file_context.get('detected_type')}"
            )
        if trace is not None:
            trace["file_analysis"] = file_context
            trace["runtime_flags"] = {
                "enable_file_analyzer": self.runtime_config.enable_file_analyzer,
                "enable_file_context_injection": self.runtime_config.enable_file_context_injection,
                "enable_executor_standardization": self.runtime_config.enable_executor_standardization,
                "macro_column_mapping_modes": list(self.runtime_config.macro_column_mapping_modes),
            }

        # 2. Assemble context
        context = self.assembler.assemble(
            user_message=user_message,
            working_memory=self.memory.get_working_memory(),
            fact_memory=self.memory.get_fact_memory(),
            file_context=file_context
        )
        if trace is not None:
            trace["assembled_context"] = {
                "message_count": len(context.messages),
                "estimated_tokens": context.estimated_tokens,
                "file_context_injected": bool(file_context and self.runtime_config.enable_file_context_injection),
                "last_user_message": context.messages[-1]["content"] if context.messages else None,
            }

        # 3. Call LLM with Tool Use
        response = await self.llm.chat_with_tools(
            messages=context.messages,
            tools=context.tools,
            system=context.system_prompt
        )
        if trace is not None:
            trace["routing"] = {
                "raw_response_content": response.content,
                "tool_calls": [
                    {"name": tc.name, "arguments": tc.arguments}
                    for tc in (response.tool_calls or [])
                ],
            }

        # 4. Process response
        result = await self._process_response(
            response,
            context,
            file_path,
            tool_call_count=0,
            trace=trace,
        )

        # 5. Update memory
        tool_calls_data = result.executed_tool_calls
        if tool_calls_data is None and response.tool_calls:
            # Fallback: keep raw tool calls even if no execution result captured.
            tool_calls_data = [{"name": tc.name, "arguments": tc.arguments} for tc in response.tool_calls]

        self.memory.update(
            user_message=user_message,
            assistant_response=result.text,
            tool_calls=tool_calls_data,
            file_path=file_path,
            file_analysis=file_context
        )
        if trace is not None:
            trace["final"] = {
                "text": result.text,
                "has_chart_data": bool(result.chart_data),
                "has_table_data": bool(result.table_data),
                "has_map_data": bool(result.map_data),
                "has_download_file": bool(result.download_file),
                "tool_calls": tool_calls_data,
                "duration_ms": round((time.perf_counter() - start_time) * 1000, 2),
            }

        return result

    async def _process_response(
        self,
        response,
        context,
        file_path: Optional[str],
        tool_call_count: int = 0,
        trace: Optional[Dict[str, Any]] = None,
    ) -> RouterResponse:
        """
        Process LLM response

        Handles:
        - Direct responses (no tools)
        - Tool calls (execute and synthesize)
        - Errors (retry or friendly message)
        """
        # Case 1: Direct response (no tool calls)
        if not response.tool_calls:
            return RouterResponse(text=response.content, executed_tool_calls=None)

        # Case 2: Too many retries
        if tool_call_count >= self.MAX_TOOL_CALLS_PER_TURN:
            return RouterResponse(
                text="I tried several approaches but encountered some issues. "
                     "Could you please provide more details about what you need?"
            )

        # Case 3: Execute tool calls
        tool_results = []
        for tool_call in response.tool_calls:
            logger.info(f"Executing tool: {tool_call.name}")
            logger.debug(f"Tool arguments: {tool_call.arguments}")

            result = await self.executor.execute(
                tool_name=tool_call.name,
                arguments=tool_call.arguments,
                file_path=file_path
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
        if trace is not None:
            trace.setdefault("tool_execution", []).append({
                "turn": tool_call_count,
                "tool_results": [
                    {
                        "name": item["name"],
                        "arguments": item["arguments"],
                        "success": item["result"].get("success"),
                        "message": item["result"].get("message"),
                        "trace": item["result"].get("_trace"),
                    }
                    for item in tool_results
                ],
            })

        logger.info(f"Collected {len(tool_results)} tool results from {len(response.tool_calls)} tool calls")

        # Check for errors
        has_error = any(r["result"].get("error") for r in tool_results)

        if has_error and tool_call_count < self.MAX_TOOL_CALLS_PER_TURN - 1:
            # Let LLM handle the error (might ask for clarification)
            error_messages = self._format_tool_errors(tool_results)

            # Add tool results to context
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

            # Retry with error context
            retry_response = await self.llm.chat_with_tools(
                messages=context.messages,
                tools=context.tools,
                system=context.system_prompt
            )

            return await self._process_response(
                retry_response,
                context,
                file_path,
                tool_call_count=tool_call_count + 1,
                trace=trace,
            )

        # Synthesize results
        synthesis_text = await self._synthesize_results(
            context,
            response,
            tool_results
        )

        # Extract data for frontend
        chart_data = self._extract_chart_data(tool_results)
        table_data = self._extract_table_data(tool_results)
        map_data = self._extract_map_data(tool_results)
        download_file = self._extract_download_file(tool_results)

        logger.info(f"[DEBUG EXTRACT] chart_data: {bool(chart_data)}")
        logger.info(f"[DEBUG EXTRACT] table_data: {bool(table_data)}")
        logger.info(f"[DEBUG EXTRACT] map_data: {bool(map_data)}")
        if table_data:
            logger.info(f"[DEBUG EXTRACT] table_data type: {table_data.get('type')}, rows: {len(table_data.get('preview_rows', []))}")
        if map_data:
            logger.info(f"[DEBUG EXTRACT] map_data links: {len(map_data.get('links', []))}")

        return RouterResponse(
            text=synthesis_text,
            chart_data=chart_data,
            table_data=table_data,
            map_data=map_data,
            download_file=download_file,
            executed_tool_calls=self._build_memory_tool_calls(tool_results),
        )

    async def _analyze_file(self, file_path: str) -> Dict:
        """Analyze file using file analyzer tool"""
        result = await self.executor.execute(
            tool_name="analyze_file",
            arguments={"file_path": file_path},
            file_path=file_path
        )
        data = result.get("data", {})
        # Add file_path to the data so LLM knows where the file is
        data["file_path"] = file_path
        return data

    async def _synthesize_results(
        self,
        context,
        original_response,
        tool_results: list
    ) -> str:
        """
        综合工具执行结果，生成自然语言回复
        """
        short_circuit_text = self._maybe_short_circuit_synthesis(tool_results)
        if short_circuit_text is not None:
            if len(tool_results) == 1 and tool_results[0].get("name") == "query_knowledge":
                logger.info("[知识检索] 直接返回答案，跳过 synthesis")
            elif any(not item.get("result", {}).get("success") for item in tool_results):
                logger.info("[Synthesis] 检测到工具失败，使用确定性格式化结果")
            elif len(tool_results) == 1:
                only_name = tool_results[0].get("name", "unknown")
                only_result = tool_results[0].get("result", {})
                if only_name in {
                    "query_emission_factors",
                    "calculate_micro_emission",
                    "calculate_macro_emission",
                    "analyze_file",
                }:
                    logger.info(f"[Synthesis] 单工具成功({only_name})，使用友好渲染")
                elif only_result.get("summary"):
                    logger.info(f"[Synthesis] 单工具成功({only_name})，直接返回工具summary")
                else:
                    logger.info(f"[Synthesis] 单工具成功({only_name})，工具无summary，使用渲染回退")
            return short_circuit_text

        request = self._build_synthesis_request(
            context.messages[-1]["content"] if context.messages else None,
            tool_results,
        )
        results_json = request["results_json"]

        logger.info(f"Filtered results for synthesis ({len(results_json)} chars):")
        logger.info(f"{results_json[:500]}...")  # Log first 500 chars

        synthesis_response = await self.llm.chat(
            messages=request["messages"],
            system=request["system_prompt"],
        )

        logger.info(f"Synthesis complete. Response length: {len(synthesis_response.content)} chars")

        hallucination_keywords = ["相当于", "棵树", "峰值出现在", "空调导致", "不完全燃烧"]
        for keyword in self._detect_synthesis_hallucination_keywords(
            synthesis_response.content,
            hallucination_keywords,
        ):
            logger.warning(f"⚠️ Possible hallucination detected: '{keyword}' found in response")

        return synthesis_response.content

    def _render_single_tool_success(self, tool_name: str, result: Dict) -> str:
        """Compatibility wrapper around extracted rendering helper."""
        return render_single_tool_success_helper(tool_name, result)

    def _filter_results_for_synthesis(self, tool_results: list) -> Dict:
        """Compatibility wrapper around extracted rendering helper."""
        return filter_results_for_synthesis_helper(tool_results)

    def _format_tool_errors(self, tool_results: list) -> str:
        """Compatibility wrapper around extracted rendering helper."""
        return format_tool_errors_helper(tool_results)

    def _format_tool_results(self, tool_results: list) -> str:
        """Compatibility wrapper around extracted rendering helper."""
        return format_tool_results_helper(tool_results)

    def _maybe_short_circuit_synthesis(self, tool_results: list) -> Optional[str]:
        """Compatibility wrapper around extracted synthesis helper."""
        return maybe_short_circuit_synthesis_helper(tool_results)

    def _build_synthesis_request(self, last_user_message: Optional[str], tool_results: list) -> Dict[str, Any]:
        """Compatibility wrapper around extracted synthesis helper."""
        return build_synthesis_request_helper(last_user_message, tool_results, SYNTHESIS_PROMPT)

    def _detect_synthesis_hallucination_keywords(self, content: str, keywords: list[str]) -> list[str]:
        """Compatibility wrapper around extracted synthesis helper."""
        return detect_hallucination_keywords_helper(content, keywords)

    def _build_memory_tool_calls(self, tool_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Compatibility wrapper around the extracted memory-compaction helper."""
        return build_memory_tool_calls_helper(tool_results)

    def _compact_tool_data(self, data: Any) -> Optional[Dict[str, Any]]:
        """Compatibility wrapper around the extracted memory-compaction helper."""
        return compact_tool_data_helper(data)

    def _format_results_as_fallback(self, tool_results: list) -> str:
        """Compatibility wrapper around extracted rendering helper."""
        return format_results_as_fallback_helper(tool_results)

    def _extract_chart_data(self, tool_results: list) -> Optional[Dict]:
        """Compatibility wrapper around extracted payload helper."""
        return extract_chart_data_helper(tool_results)

    def _format_emission_factors_chart(self, data: Dict) -> Optional[Dict]:
        """Compatibility wrapper around extracted payload helper."""
        return format_emission_factors_chart_helper(data)

    def _extract_table_data(self, tool_results: list) -> Optional[Dict]:
        """Compatibility wrapper around extracted payload helper."""
        return extract_table_data_helper(tool_results)

    def _extract_download_file(self, tool_results: list) -> Optional[Dict]:
        """Compatibility wrapper around extracted payload helper."""
        return extract_download_file_helper(tool_results)

    def _extract_map_data(self, tool_results: list) -> Optional[Dict]:
        """Compatibility wrapper around extracted payload helper."""
        return extract_map_data_helper(tool_results)

    def clear_history(self):
        """Clear conversation history"""
        self.memory.working_memory.clear()
        self.memory.fact_memory = MemoryManager.FactMemory()
        logger.info(f"Cleared history for session {self.session_id}")
