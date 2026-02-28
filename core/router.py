"""
Unified Router - Main entry point for new architecture
Uses Tool Use mode, no planning layer
"""
import logging
import json
import re
from typing import Dict, Optional, List, Any
from dataclasses import dataclass
from core.assembler import ContextAssembler
from core.executor import ToolExecutor
from core.memory import MemoryManager
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
    download_file: Optional[str] = None
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
        self.assembler = ContextAssembler()
        self.executor = ToolExecutor()
        self.memory = MemoryManager(session_id)
        self.llm = get_llm_client("agent", model="qwen-plus")

    async def chat(
        self,
        user_message: str,
        file_path: Optional[str] = None
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

            if cache_valid:
                file_context = cached
                logger.info(f"Using cached file analysis for {file_path}")
            else:
                file_context = await self._analyze_file(file_path)
                # Store path and mtime to detect file changes
                file_context["file_path"] = file_path_str
                file_context["file_mtime"] = current_mtime
                logger.info(f"Analyzed new file: {file_path} (mtime: {current_mtime})")
            # Diagnostic: log memory state when file is uploaded
            wm = self.memory.get_working_memory()
            fm = self.memory.get_fact_memory()
            logger.info(
                f"[FILE UPLOAD] working_memory_turns={len(wm)}, "
                f"fact_memory={fm}, "
                f"file_task_type={file_context.get('task_type') or file_context.get('detected_type')}"
            )

        # 2. Assemble context
        context = self.assembler.assemble(
            user_message=user_message,
            working_memory=self.memory.get_working_memory(),
            fact_memory=self.memory.get_fact_memory(),
            file_context=file_context
        )

        # 3. Call LLM with Tool Use
        response = await self.llm.chat_with_tools(
            messages=context.messages,
            tools=context.tools,
            system=context.system_prompt
        )

        # 4. Process response
        result = await self._process_response(
            response,
            context,
            file_path,
            tool_call_count=0
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

        return result

    async def _process_response(
        self,
        response,
        context,
        file_path: Optional[str],
        tool_call_count: int = 0
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
                tool_call_count=tool_call_count + 1
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
        download_file = self._extract_download_file(tool_results)

        logger.info(f"[DEBUG EXTRACT] chart_data: {bool(chart_data)}")
        logger.info(f"[DEBUG EXTRACT] table_data: {bool(table_data)}")
        if table_data:
            logger.info(f"[DEBUG EXTRACT] table_data type: {table_data.get('type')}, rows: {len(table_data.get('preview_rows', []))}")

        return RouterResponse(
            text=synthesis_text,
            chart_data=chart_data,
            table_data=table_data,
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
        # 特殊处理：知识检索直接返回
        if len(tool_results) == 1 and tool_results[0].get("name") == "query_knowledge":
            knowledge_result = tool_results[0].get("result", {})
            if knowledge_result.get("success") and knowledge_result.get("summary"):
                logger.info("[知识检索] 直接返回答案，跳过 synthesis")
                return knowledge_result["summary"]

        # 避免synthesis幻觉：失败场景直接走确定性格式化
        if any(not r.get("result", {}).get("success") for r in tool_results):
            logger.info("[Synthesis] 检测到工具失败，使用确定性格式化结果")
            return self._format_results_as_fallback(tool_results)

        # 单工具成功场景：优先使用工具summary，避免重复模板丢失关键信息
        if len(tool_results) == 1:
            only_result = tool_results[0].get("result", {})
            only_name = tool_results[0].get("name", "unknown")

            # 对于需要友好渲染的工具，使用 _render_single_tool_success
            tools_needing_rendering = [
                "query_emission_factors",
                "calculate_micro_emission",
                "calculate_macro_emission",
                "analyze_file"
            ]

            if only_result.get("success"):
                if only_name in tools_needing_rendering:
                    logger.info(f"[Synthesis] 单工具成功({only_name})，使用友好渲染")
                    return self._render_single_tool_success(only_name, only_result)
                elif only_result.get("summary"):
                    logger.info(f"[Synthesis] 单工具成功({only_name})，直接返回工具summary")
                    return only_result["summary"]
                else:
                    logger.info(f"[Synthesis] 单工具成功({only_name})，工具无summary，使用渲染回退")
                    return self._render_single_tool_success(only_name, only_result)

        # 1. 过滤数据，只保留关键信息
        filtered_results = self._filter_results_for_synthesis(tool_results)

        # 2. 格式化为 JSON
        import json
        results_json = json.dumps(filtered_results, ensure_ascii=False, indent=2)

        logger.info(f"Filtered results for synthesis ({len(results_json)} chars):")
        logger.info(f"{results_json[:500]}...")  # Log first 500 chars

        # 3. 构建 synthesis prompt
        synthesis_prompt = SYNTHESIS_PROMPT.replace("{results}", results_json)

        # 4. 构建消息
        # 注意：不要传递 tools 参数，只做纯文本生成
        synthesis_messages = [
            {"role": "user", "content": context.messages[-1]["content"] if context.messages else "请总结计算结果"}
        ]

        # 5. 调用 LLM
        synthesis_response = await self.llm.chat(
            messages=synthesis_messages,
            system=synthesis_prompt
        )

        logger.info(f"Synthesis complete. Response length: {len(synthesis_response.content)} chars")

        # 检查是否有幻觉迹象
        hallucination_keywords = ["相当于", "棵树", "峰值出现在", "空调导致", "不完全燃烧"]
        for kw in hallucination_keywords:
            if kw in synthesis_response.content:
                logger.warning(f"⚠️ Possible hallucination detected: '{kw}' found in response")

        return synthesis_response.content

    def _render_single_tool_success(self, tool_name: str, result: Dict) -> str:
        """Render stable and clean markdown for single-tool success cases."""
        if tool_name == "calculate_micro_emission":
            data = result.get("data", {})
            query_info = data.get("query_info", {})
            summary = data.get("summary", {})
            emissions = summary.get("total_emissions_g", {})

            lines = [
                "## 微观排放计算结果",
                "",
                "**计算参数**",
                f"- 车型: {query_info.get('vehicle_type', '未知')}",
                f"- 年份: {query_info.get('model_year', '未知')}",
                f"- 季节: {query_info.get('season', '未知')}",
                f"- 污染物: {', '.join(query_info.get('pollutants', [])) or '未知'}",
                f"- 轨迹点数: {query_info.get('trajectory_points', 0)}",
                "",
                "**汇总结果**",
                f"- 总距离: {summary.get('total_distance_km', 0):.3f} km",
                f"- 总时间: {summary.get('total_time_s', 0)} s",
                "- 总排放量:",
            ]

            for pol, val in emissions.items():
                lines.append(f"  - {pol}: {val:.4f} g")

            rates = summary.get("emission_rates_g_per_km", {})
            if rates:
                lines.append("- 单位排放:")
                for pol, val in rates.items():
                    lines.append(f"  - {pol}: {val:.4f} g/km")

            return "\n".join(lines)

        if tool_name == "calculate_macro_emission":
            data = result.get("data", {})
            query_info = data.get("query_info", {})
            summary = data.get("summary", {})
            totals = summary.get("total_emissions_kg_per_hr", {})

            lines = [
                "## 宏观排放计算结果",
                "",
                "**计算参数**",
                f"- 路段数: {query_info.get('links_count', 0)}",
                f"- 年份: {query_info.get('model_year', '未知')}",
                f"- 季节: {query_info.get('season', '未知')}",
                f"- 污染物: {', '.join(query_info.get('pollutants', [])) or '未知'}",
                "",
                "**汇总结果**",
                "- 总排放量 (kg/h):",
            ]

            for pol, val in totals.items():
                lines.append(f"  - {pol}: {val:.4f}")

            return "\n".join(lines)

        if tool_name == "query_emission_factors":
            data = result.get("data", {})

            # 判断单污染物 vs 多污染物
            if "query_summary" in data:
                # 单污染物格式
                qs = data.get("query_summary", {})
                pollutant_names = qs.get("pollutant", "未知")
                vehicle_type = qs.get("vehicle_type", "未知")
                model_year = qs.get("model_year", "未知")
                season = qs.get("season", "未知")
                road_type = qs.get("road_type", "未知")
                pollutants_data = {pollutant_names: data}
            else:
                # 多污染物格式
                vehicle_type = data.get("vehicle_type", "未知")
                model_year = data.get("model_year", "未知")
                meta = data.get("metadata", {})
                season = meta.get("season", "未知")
                road_type = meta.get("road_type", "未知")
                pollutants_data = data.get("pollutants", {})
                pollutant_names = ", ".join(pollutants_data.keys())

            lines = [
                "## 排放因子查询结果",
                "",
                "**查询参数**",
                f"- 车型: {vehicle_type}",
                f"- 年份: {model_year}",
                f"- 季节: {season}",
                f"- 道路类型: {road_type}",
                f"- 污染物: {pollutant_names}",
            ]

            # 每个污染物的典型排放值
            speed_labels = {25: "低速", 50: "中速", 70: "高速"}
            for pol_name, pol_data in pollutants_data.items():
                unit = pol_data.get("unit", "g/mile")
                typical = pol_data.get("typical_values", [])

                if len(pollutants_data) > 1:
                    lines.append("")
                    lines.append(f"**{pol_name} 典型排放值 ({unit})**")
                else:
                    lines.append("")
                    lines.append(f"**典型排放值 ({unit})**")

                if typical:
                    for tv in typical:
                        speed_kph = tv.get("speed_kph", 0)
                        rate = tv.get("emission_rate", 0)
                        label = speed_labels.get(tv.get("speed_mph"), f"{speed_kph} km/h")
                        lines.append(f"- {label} ({speed_kph} km/h): {rate:.4f}")
                else:
                    lines.append("- 暂无典型值数据")

            # 数据概况（取第一个污染物的信息）
            first_pol = next(iter(pollutants_data.values()), {})
            speed_range = first_pol.get("speed_range", {})
            data_points = first_pol.get("data_points", 0)
            data_source = first_pol.get("data_source", "")

            lines.append("")
            lines.append("**数据概况**")
            if speed_range:
                lines.append(f"- 速度范围: {speed_range.get('min_kph', 0)} - {speed_range.get('max_kph', 0)} km/h")
            lines.append(f"- 数据点数: {data_points}")
            if data_source:
                lines.append(f"- 数据来源: {data_source}")

            return "\n".join(lines)

        if tool_name == "analyze_file":
            data = result.get("data", {})
            filename = data.get("filename", "未知文件")
            row_count = data.get("row_count", 0)
            columns = data.get("columns", [])
            task_type = data.get("task_type", "未知")
            confidence = data.get("confidence", 0)

            lines = [
                "## 文件分析结果",
                "",
                "**文件信息**",
                f"- 文件名: {filename}",
                f"- 数据行数: {row_count}",
                f"- 识别类型: {task_type}",
                f"- 置信度: {confidence:.0%}",
                "",
                "**数据列**",
                f"- 列数: {len(columns)}",
                f"- 列名: {', '.join(columns[:10])}",
            ]
            if len(columns) > 10:
                lines.append(f"  (还有 {len(columns) - 10} 列...)")

            # 检测到的任务类型提示
            if task_type == "micro_emission":
                lines.append("")
                lines.append("**💡 建议**: 该文件适合用于微观排放计算（基于轨迹数据）")
            elif task_type == "macro_emission":
                lines.append("")
                lines.append("**💡 建议**: 该文件适合用于宏观排放计算（基于路段流量）")

            return "\n".join(lines)

        # For non-calculation tools, keep original summary
        return result.get("summary") or "执行完成。"

    def _filter_results_for_synthesis(self, tool_results: list) -> Dict:
        """
        过滤工具结果，只保留关键信息供 Synthesis 使用

        设计原则：
        - 保留足够信息让 LLM 生成准确回答
        - 移除大量详细数据（避免 token 浪费）
        - 保留汇总和关键参数
        """
        filtered = {}

        for r in tool_results:
            tool_name = r["name"]
            result = r["result"]

            # 处理失败的情况
            if not result.get("success"):
                filtered[tool_name] = {
                    "success": False,
                    "error": result.get("message") or result.get("error") or "未知错误"
                }
                continue

            data = result.get("data", {})

            # 对于排放计算工具，只保留汇总信息
            if tool_name in ["calculate_micro_emission", "calculate_macro_emission"]:
                summary = data.get("summary", {})
                results_list = data.get("results", [])

                # 提取查询参数（如果有）
                query_params = {}
                if data.get("vehicle_type"):
                    query_params["vehicle_type"] = data["vehicle_type"]
                if data.get("pollutants"):
                    query_params["pollutants"] = data["pollutants"]
                if data.get("model_year"):
                    query_params["model_year"] = data["model_year"]
                if data.get("season"):
                    query_params["season"] = data["season"]

                filtered[tool_name] = {
                    "success": True,
                    "summary": result.get("summary", "计算完成"),
                    "num_points": len(results_list),
                    "total_emissions": summary.get("total_emissions_g", {}) or summary.get("total_emissions", {}),
                    "total_distance_km": summary.get("total_distance_km"),
                    "total_time_s": summary.get("total_time_s"),
                    "query_params": query_params,
                    "has_download_file": bool(data.get("download_file"))
                }

            # 对于排放因子查询
            elif tool_name == "query_emission_factors":
                filtered[tool_name] = {
                    "success": True,
                    "summary": result.get("summary", "查询完成"),
                    "data": data  # 排放因子数据量不大，可以保留
                }

            # 对于文件分析
            elif tool_name == "analyze_file":
                filtered[tool_name] = {
                    "success": True,
                    "file_type": data.get("detected_type") or data.get("task_type"),
                    "columns": data.get("columns"),
                    "row_count": data.get("row_count"),
                    "file_path": data.get("file_path"),
                }

            # 其他工具
            else:
                filtered[tool_name] = {
                    "success": True,
                    "data": data
                }

        return filtered

    def _format_tool_errors(self, tool_results: list) -> str:
        """Format tool errors for LLM"""
        errors = []
        for r in tool_results:
            if r["result"].get("error"):
                msg = r["result"].get("message") or r["result"].get("error") or "Unknown error"
                suggestions = r["result"].get("suggestions")
                error_text = f"[{r['name']}] Error: {msg}"
                if suggestions:
                    error_text += f"\nSuggestions: {', '.join(suggestions)}"
                errors.append(error_text)
        return "\n".join(errors)

    def _format_tool_results(self, tool_results: list) -> str:
        """Format tool results for LLM"""
        summaries = []
        for r in tool_results:
            if r["result"].get("success"):
                summary = r["result"].get("summary", "Execution successful")
                summaries.append(f"[{r['name']}] {summary}")
            else:
                error = r["result"].get("message") or r["result"].get("error") or "Unknown error"
                summaries.append(f"[{r['name']}] Error: {error}")
        return "\n".join(summaries)

    def _build_memory_tool_calls(self, tool_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Build compact tool-call records for memory extraction.
        Keep tool success and compact data snapshot so follow-up turns stay grounded.
        """
        records: List[Dict[str, Any]] = []
        for item in tool_results:
            result = item.get("result", {})
            records.append({
                "name": item.get("name"),
                "arguments": item.get("arguments", {}),
                "result": {
                    "success": bool(result.get("success")),
                    "summary": result.get("summary"),
                    "data": self._compact_tool_data(result.get("data")),
                },
            })
        return records

    def _compact_tool_data(self, data: Any) -> Optional[Dict[str, Any]]:
        """Compact tool data to avoid storing large arrays in memory context."""
        if not isinstance(data, dict):
            return None

        compact: Dict[str, Any] = {}
        for key, value in data.items():
            if key in {"results", "speed_curve", "pollutants"}:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                compact[key] = value
                continue
            if key in {"query_info", "summary", "fleet_mix_fill", "download_file"} and isinstance(value, dict):
                compact[key] = value
                continue
            if key == "columns" and isinstance(value, list):
                compact[key] = value[:20]

        return compact

    def _format_results_as_fallback(self, tool_results: list) -> str:
        """
        Fallback method to format tool results directly when synthesis fails

        This provides a structured, user-friendly response without relying on LLM synthesis
        """
        lines = []
        lines.append("## 工具执行结果\n")

        success_count = sum(1 for r in tool_results if r["result"].get("success"))
        error_count = len(tool_results) - success_count

        if error_count > 0:
            lines.append(f"⚠️ {error_count} 个工具执行失败，{success_count} 个成功\n")
        else:
            lines.append(f"✅ 所有工具执行成功\n")

        for i, r in enumerate(tool_results, 1):
            tool_name = r["name"]
            result = r["result"]

            lines.append(f"### {i}. {tool_name}\n")

            if result.get("success"):
                lines.append("**状态**: ✅ 成功\n")

                # Add summary if available
                if result.get("summary"):
                    lines.append(f"**结果**: {result['summary']}\n")

                # Add data if available
                if result.get("data"):
                    data = result["data"]
                    if isinstance(data, dict):
                        for key, value in list(data.items())[:5]:  # Show first 5 items
                            lines.append(f"- {key}: {value}\n")
                        if len(data) > 5:
                            lines.append(f"  ... (共 {len(data)} 项数据)\n")
            else:
                lines.append("**状态**: ❌ 失败\n")

                # Add error message
                error_text = result.get("message") or result.get("error")
                if error_text:
                    lines.append(f"**错误**: {error_text}\n")

                # Add suggestions if available
                if result.get("suggestions"):
                    lines.append("**建议**:\n")
                    for suggestion in result["suggestions"]:
                        lines.append(f"- {suggestion}\n")

            lines.append("\n")

        return "".join(lines)

    def _extract_chart_data(self, tool_results: list) -> Optional[Dict]:
        """Extract chart data from tool results"""
        for r in tool_results:
            # Check if tool explicitly provides chart_data
            if r["result"].get("chart_data"):
                return r["result"]["chart_data"]

            # For emission_factors tool, format data as chart_data
            if r["name"] == "query_emission_factors" and r["result"].get("success"):
                data = r["result"].get("data", {})
                if data:
                    # Format for frontend chart rendering
                    return self._format_emission_factors_chart(data)

        return None

    def _format_emission_factors_chart(self, data: Dict) -> Dict:
        """Format emission factors data for chart display"""
        # Check if it's multi-pollutant format
        if "pollutants" in data:
            # 转换多污染物数据格式：speed_curve -> curve
            formatted_pollutants = {}
            for pollutant, pol_data in data["pollutants"].items():
                formatted_pollutants[pollutant] = {
                    "curve": pol_data.get("speed_curve", []),  # 重命名 speed_curve 为 curve
                    "unit": pol_data.get("unit", "g/mile")
                }

            return {
                "type": "emission_factors",
                "vehicle_type": data.get("vehicle_type", "Unknown"),
                "model_year": data.get("model_year", 2020),
                "pollutants": formatted_pollutants,
                "metadata": data.get("metadata", {})
            }

        # Single pollutant format
        if "speed_curve" in data:
            # Extract pollutant name from query_summary if available
            pollutant = data.get("query_summary", {}).get("pollutant", "Unknown")
            vehicle_type = data.get("query_summary", {}).get("vehicle_type", "Unknown")
            model_year = data.get("query_summary", {}).get("model_year", 2020)

            return {
                "type": "emission_factors",
                "vehicle_type": vehicle_type,
                "model_year": model_year,
                "pollutants": {
                    pollutant: {
                        "curve": data["speed_curve"],
                        "unit": data.get("unit", "g/mile")
                    }
                },
                "metadata": {
                    "data_source": data.get("data_source", ""),
                    "speed_range": data.get("speed_range", {}),
                    "data_points": data.get("data_points", 0)
                }
            }

        return None

    def _extract_table_data(self, tool_results: list) -> Optional[Dict]:
        """从工具结果提取表格数据，格式与前端 renderResultTable 兼容"""
        MAX_PREVIEW_ROWS = 4  # 只返回前4行作为预览（优化用户体验）

        for r in tool_results:
            # 优先使用工具直接返回的 table_data
            if r["result"].get("table_data"):
                return r["result"]["table_data"]

            # 处理排放因子查询工具 - 生成关键点表格
            if r["name"] == "query_emission_factors" and r["result"].get("success"):
                logger.info(f"[DEBUG TABLE] Processing query_emission_factors")
                data = r["result"].get("data", {})
                logger.info(f"[DEBUG TABLE] Data keys: {list(data.keys())}")

                # 多污染物格式
                if "pollutants" in data:
                    logger.info(f"[DEBUG TABLE] Multi-pollutant format detected")
                    pollutants_data = data["pollutants"]
                    # 获取第一个污染物的曲线数据作为速度基准
                    first_pollutant = list(pollutants_data.keys())[0]
                    logger.info(f"[DEBUG TABLE] First pollutant: {first_pollutant}")
                    logger.info(f"[DEBUG TABLE] First pollutant data keys: {list(pollutants_data[first_pollutant].keys())}")
                    # 注意：原始数据使用 speed_curve，不是 curve
                    curve = pollutants_data[first_pollutant].get("speed_curve", [])
                    logger.info(f"[DEBUG TABLE] Curve length: {len(curve)}")
                    # 如果 speed_curve 为空，尝试 curve
                    if not curve:
                        curve = pollutants_data[first_pollutant].get("curve", [])
                        logger.info(f"[DEBUG TABLE] Trying 'curve' field, length: {len(curve)}")

                    if curve:
                        # 提取关键点（每10个点取1个）
                        step = max(1, len(curve) // MAX_PREVIEW_ROWS)
                        key_points = curve[::step][:MAX_PREVIEW_ROWS]

                        # 构建列名：速度 + 各污染物
                        columns = ["速度 (km/h)"] + [f"{p} (g/km)" for p in pollutants_data.keys()]

                        # 构建数据行
                        preview_rows = []
                        for i, point in enumerate(key_points):
                            row_data = {"速度 (km/h)": f"{point['speed_kph']:.1f}"}
                            # 添加每个污染物在该速度下的排放率
                            for pollutant, pol_data in pollutants_data.items():
                                # 注意：原始数据使用 speed_curve，不是 curve
                                pol_curve = pol_data.get("speed_curve", [])
                                # 找到对应速度的排放率
                                idx = i * step
                                if idx < len(pol_curve):
                                    emission_rate = pol_curve[idx].get("emission_rate", 0)
                                    row_data[f"{pollutant} (g/km)"] = f"{emission_rate:.4f}"
                            preview_rows.append(row_data)

                        logger.info(f"[DEBUG TABLE] Generated {len(preview_rows)} preview rows")
                        table_result = {
                            "type": "query_emission_factors",
                            "columns": columns,
                            "preview_rows": preview_rows,
                            "total_rows": len(curve),
                            "total_columns": len(columns),
                            "summary": {
                                "vehicle_type": data.get("vehicle_type", "Unknown"),
                                "model_year": data.get("model_year", 2020),
                                "season": data.get("metadata", {}).get("season", ""),
                                "road_type": data.get("metadata", {}).get("road_type", "")
                            }
                        }
                        logger.info(f"[DEBUG TABLE] Returning table data")
                        return table_result

                # 单污染物格式
                elif "speed_curve" in data:
                    logger.info(f"[DEBUG TABLE] Single-pollutant format detected")
                    curve = data["speed_curve"]
                    pollutant = data.get("query_summary", {}).get("pollutant", "Unknown")

                    # 提取关键点
                    step = max(1, len(curve) // MAX_PREVIEW_ROWS)
                    key_points = curve[::step][:MAX_PREVIEW_ROWS]

                    columns = ["速度 (km/h)", f"{pollutant} (g/km)"]
                    preview_rows = [
                        {
                            "速度 (km/h)": f"{p['speed_kph']:.1f}",
                            f"{pollutant} (g/km)": f"{p['emission_rate']:.4f}"
                        }
                        for p in key_points
                    ]

                    return {
                        "type": "query_emission_factors",
                        "columns": columns,
                        "preview_rows": preview_rows,
                        "total_rows": len(curve),
                        "total_columns": 2,
                        "summary": data.get("query_summary", {})
                    }

            # 从计算工具的 data.results 构建表格数据
            if r["name"] in ["calculate_micro_emission", "calculate_macro_emission"]:
                data = r["result"].get("data", {})
                results = data.get("results", [])
                summary = data.get("summary", {})

                if not results:
                    # 如果没有详细结果，至少返回汇总
                    if summary:
                        total_emissions = summary.get("total_emissions_g", {}) or summary.get("total_emissions", {})
                        return {
                            "type": r["name"],
                            "columns": ["指标", "数值"],
                            "preview_rows": [
                                {"指标": k, "数值": f"{v:.2f} g"}
                                for k, v in total_emissions.items()
                            ],
                            "total_rows": len(total_emissions),
                            "total_columns": 2,
                            "summary": summary
                        }
                    continue

                # 从第一条结果提取列名
                first_result = results[0]

                # 微观排放的列名
                if r["name"] == "calculate_micro_emission":
                    # 基础列
                    columns = ["t", "speed_kph"]
                    # 如果有加速度
                    if "acceleration_mps2" in first_result:
                        columns.append("acceleration_mps2")
                    # VSP
                    if "vsp" in first_result or "VSP" in first_result:
                        columns.append("VSP")
                    # 排放物列
                    emissions = first_result.get("emissions", {})
                    columns.extend(list(emissions.keys()))

                    # 构建数据行
                    preview_rows = []
                    for row in results[:MAX_PREVIEW_ROWS]:  # 限制前10行
                        row_data = {
                            "t": row.get("t", row.get("time", "")),
                            "speed_kph": f"{row.get('speed_kph', row.get('speed', 0)):.1f}"
                        }
                        if "acceleration_mps2" in row:
                            row_data["acceleration_mps2"] = f"{row['acceleration_mps2']:.2f}"
                        if "vsp" in row:
                            row_data["VSP"] = f"{row['vsp']:.2f}"
                        elif "VSP" in row:
                            row_data["VSP"] = f"{row['VSP']:.2f}"
                        # 排放数据
                        for pol, val in row.get("emissions", {}).items():
                            row_data[pol] = f"{val:.4f}"
                        preview_rows.append(row_data)

                # 宏观排放的列名 - 优先显示计算结果
                else:  # calculate_macro_emission
                    # 从 data 获取污染物列表
                    query_info = data.get("query_info", {})
                    result_pollutants = query_info.get("pollutants", ["CO2"])
                    main_pollutant = result_pollutants[0] if result_pollutants else "CO2"

                    # 优先显示计算结果列，而非输入列
                    columns = ["link_id", f"{main_pollutant}_kg_h", f"{main_pollutant}_g_veh_km"]
                    # 如果有多个污染物，添加第二污染物列
                    if len(result_pollutants) > 1:
                        second_pollutant = result_pollutants[1]
                        columns.append(f"{second_pollutant}_kg_h")

                    # 构建数据行 - 显示计算结果而非输入
                    preview_rows = []
                    for row in results[:MAX_PREVIEW_ROWS]:
                        # 获取总排放量（单位：kg/h）
                        total_emiss = row.get("total_emissions_kg_per_hr", {}).get(main_pollutant, 0)
                        # 获取单位排放率（单位：g/(veh·km)）
                        emission_rate = row.get("emission_rates_g_per_veh_km", {}).get(main_pollutant, 0)

                        row_data = {
                            "link_id": row.get("link_id", ""),
                            f"{main_pollutant}_kg_h": f"{total_emiss:.2f}",
                            f"{main_pollutant}_g_veh_km": f"{emission_rate:.2f}"
                        }

                        # 添加第二污染物（如果有）
                        if len(result_pollutants) > 1:
                            second_pollutant = result_pollutants[1]
                            second_emiss = row.get("total_emissions_kg_per_hr", {}).get(second_pollutant, 0)
                            row_data[f"{second_pollutant}_kg_h"] = f"{second_emiss:.2f}"

                        preview_rows.append(row_data)

                return {
                    "type": r["name"],
                    "columns": columns,
                    "preview_rows": preview_rows,
                    "total_rows": len(results),
                    "total_columns": len(columns),
                    "summary": summary,
                    "total_emissions": summary.get("total_emissions_g", {}) or summary.get("total_emissions", {})
                }

        return None

    def _extract_download_file(self, tool_results: list) -> Optional[Dict]:
        """
        从工具结果提取下载文件信息

        返回格式：{"path": "...", "filename": "..."}
        """
        logger.info(f"[DEBUG] Extracting download_file from {len(tool_results)} tool results")

        for r in tool_results:
            result = r["result"]
            logger.info(f"[DEBUG] Checking tool: {r['name']}")
            logger.info(f"[DEBUG] Result keys: {result.keys()}")

            # 位置1：顶层 download_file（必须非空）
            if result.get("download_file"):
                df = result["download_file"]
                logger.info(f"[DEBUG] Found download_file at top level: {df}")
                if isinstance(df, str):
                    return {"path": df, "filename": df.split("/")[-1].split("\\")[-1]}
                elif isinstance(df, dict):
                    return df

            # 位置2：data.download_file（必须非空）
            data = result.get("data", {})
            if data and data.get("download_file"):
                df = data["download_file"]
                logger.info(f"[DEBUG] Found download_file in data: {df}")
                if isinstance(df, str):
                    return {"path": df, "filename": df.split("/")[-1].split("\\")[-1]}
                elif isinstance(df, dict):
                    return df

            # 位置3：metadata.download_file（兼容旧格式）
            metadata = result.get("metadata", {})
            if metadata and metadata.get("download_file"):
                logger.info(f"[DEBUG] Found download_file in metadata: {metadata['download_file']}")
                return metadata["download_file"]

        logger.warning("[DEBUG] No download_file found in any tool result")
        return None

    def clear_history(self):
        """Clear conversation history"""
        self.memory.working_memory.clear()
        self.memory.fact_memory = MemoryManager.FactMemory()
        logger.info(f"Cleared history for session {self.session_id}")
