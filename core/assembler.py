"""
Context Assembler - Assembles context for LLM
No decision-making, just information assembly
"""
import logging
import json
from typing import Dict, List, Optional
from dataclasses import dataclass
from services.config_loader import ConfigLoader

logger = logging.getLogger(__name__)


@dataclass
class AssembledContext:
    """Assembled context ready for LLM"""
    system_prompt: str
    tools: List[Dict]
    messages: List[Dict]
    estimated_tokens: int


class ContextAssembler:
    """
    Context assembler - Assembles all information for LLM

    Design: No decisions, just assembly
    Priority: Core prompt > Tools > Facts > Working memory > File context
    """

    MAX_CONTEXT_TOKENS = 6000  # Conservative limit

    def __init__(self):
        self.config = ConfigLoader.load_prompts()
        self.tools = ConfigLoader.load_tool_definitions()

    # Max chars to keep per assistant response in working memory
    MAX_ASSISTANT_RESPONSE_CHARS = 300

    def assemble(
        self,
        user_message: str,
        working_memory: List[Dict],
        fact_memory: Dict,
        file_context: Optional[Dict] = None
    ) -> AssembledContext:
        """
        Assemble complete context for LLM

        Token budget priority:
        1. Core prompt (~200 tokens) - MUST
        2. Tool definitions (~400 tokens) - MUST
        3. Fact memory (~100 tokens) - Important
        4. Working memory (~3000 tokens) - Important
        5. File context (~500 tokens) - When file uploaded, ELEVATED priority

        Args:
            user_message: Current user message
            working_memory: Recent conversation turns
            fact_memory: Structured facts
            file_context: Optional file information

        Returns:
            AssembledContext ready for LLM
        """
        has_file = file_context is not None
        used_tokens = 0

        # 1. Core prompt (MUST)
        system_prompt = self.config["system_prompt"]
        used_tokens += self._estimate_tokens(system_prompt)

        # 2. Tool definitions (MUST)
        tools = self.tools
        used_tokens += 400  # Estimated

        # 3. Build messages
        messages = []

        # 3.1 Add fact memory if available
        if fact_memory and any(fact_memory.values()):
            fact_summary = self._format_fact_memory(fact_memory)
            if fact_summary:
                messages.append({
                    "role": "system",
                    "content": f"[Context from previous conversations]\n{fact_summary}"
                })
                used_tokens += self._estimate_tokens(fact_summary)

        # 3.2 Add working memory (recent conversations)
        remaining_budget = self.MAX_CONTEXT_TOKENS - used_tokens - 500
        working_memory_messages = self._format_working_memory(
            working_memory,
            max_tokens=remaining_budget,
            max_turns=3
        )
        messages.extend(working_memory_messages)
        used_tokens += self._estimate_tokens(str(working_memory_messages))

        # 3.3 Add file context if available — make it prominent
        if file_context:
            file_summary = self._format_file_context(file_context, max_tokens=500)
            user_message = f"{file_summary}\n\n{user_message}"

        # 3.4 Add current user message
        messages.append({"role": "user", "content": user_message})
        used_tokens += self._estimate_tokens(user_message)

        logger.info(
            f"Assembled context: ~{used_tokens} tokens, {len(messages)} messages, "
            f"has_file={has_file}, working_memory_turns={len(working_memory)}"
        )

        return AssembledContext(
            system_prompt=system_prompt,
            tools=tools,
            messages=messages,
            estimated_tokens=used_tokens
        )

    def _format_fact_memory(self, fact_memory: Dict) -> str:
        """Format fact memory for LLM"""
        lines = []

        if fact_memory.get("recent_vehicle"):
            lines.append(f"Recent vehicle type: {fact_memory['recent_vehicle']}")

        if fact_memory.get("recent_pollutants"):
            pols = ", ".join(fact_memory["recent_pollutants"])
            lines.append(f"Recent pollutants: {pols}")

        if fact_memory.get("recent_year"):
            lines.append(f"Recent model year: {fact_memory['recent_year']}")

        if fact_memory.get("active_file"):
            lines.append(f"Active file: {fact_memory['active_file']}")

        file_analysis = fact_memory.get("file_analysis")
        if isinstance(file_analysis, dict):
            task_type = file_analysis.get("task_type") or file_analysis.get("detected_type")
            if task_type:
                lines.append(f"Cached file task_type: {task_type}")
            if file_analysis.get("row_count") is not None:
                lines.append(f"Cached file rows: {file_analysis.get('row_count')}")
            cols = file_analysis.get("columns") or []
            if isinstance(cols, list) and cols:
                preview_cols = ", ".join([str(c) for c in cols[:12]])
                if len(cols) > 12:
                    preview_cols += f" ... (共{len(cols)}列)"
                lines.append(f"Cached file columns: {preview_cols}")

        if fact_memory.get("last_tool_name"):
            lines.append(f"Last successful tool: {fact_memory['last_tool_name']}")
        if fact_memory.get("last_tool_summary"):
            summary = str(fact_memory["last_tool_summary"])
            if len(summary) > 260:
                summary = summary[:260] + "...(truncated)"
            lines.append(f"Last tool summary: {summary}")
        if fact_memory.get("last_tool_snapshot"):
            try:
                snap = json.dumps(fact_memory["last_tool_snapshot"], ensure_ascii=False)
                if len(snap) > 360:
                    snap = snap[:360] + "...(truncated)"
                lines.append(f"Last tool snapshot: {snap}")
            except Exception:
                pass

        return "\n".join(lines) if lines else ""

    def _format_working_memory(
        self,
        working_memory: List[Dict],
        max_tokens: int,
        max_turns: int = 3
    ) -> List[Dict]:
        """
        Format working memory for LLM

        Strategy: Keep last N complete turns (default 3, reduced when file uploaded)
        Truncate long assistant responses to prevent pattern bias
        If over budget, drop oldest turns
        """
        if not working_memory:
            return []

        recent = working_memory[-max_turns:]

        result = []
        for turn in recent:
            result.append({"role": "user", "content": turn["user"]})
            # Truncate long assistant responses to prevent context pollution
            assistant_text = turn["assistant"]
            if len(assistant_text) > self.MAX_ASSISTANT_RESPONSE_CHARS:
                assistant_text = assistant_text[:self.MAX_ASSISTANT_RESPONSE_CHARS] + "...(truncated)"
            result.append({"role": "assistant", "content": assistant_text})

        # Token budget check — drop oldest if over budget
        estimated = self._estimate_tokens(str(result))
        if estimated > max_tokens and len(recent) > 1:
            recent = recent[-1:]
            result = []
            for turn in recent:
                result.append({"role": "user", "content": turn["user"]})
                assistant_text = turn["assistant"]
                if len(assistant_text) > self.MAX_ASSISTANT_RESPONSE_CHARS:
                    assistant_text = assistant_text[:self.MAX_ASSISTANT_RESPONSE_CHARS] + "...(truncated)"
                result.append({"role": "assistant", "content": assistant_text})

        return result

    def _format_file_context(self, file_context: Dict, max_tokens: int) -> str:
        """Format file context for LLM"""
        lines = [
            f"Filename: {file_context.get('filename', 'unknown')}",
            f"File path: {file_context.get('file_path', 'unknown')}",
        ]

        # Highlight task_type prominently — system prompt tells LLM to use this
        task_type = file_context.get("task_type") or file_context.get("detected_type", "unknown")
        lines.append(f"task_type: {task_type}")

        lines.extend([
            f"Rows: {file_context.get('row_count', 'unknown')}",
            f"Columns: {', '.join(file_context.get('columns', []))}",
        ])

        # Add sample data if space available
        if max_tokens > 300 and file_context.get("sample_rows"):
            lines.append(f"Sample (first 2 rows): {file_context['sample_rows'][:2]}")

        return "\n".join(lines)

    def _estimate_tokens(self, text: str) -> int:
        """
        Estimate token count

        Simple heuristic: 1 Chinese char ≈ 1 token, 1 English word ≈ 1 token
        In production, use tiktoken for accurate counting
        """
        if not text:
            return 0
        return len(text) // 2
