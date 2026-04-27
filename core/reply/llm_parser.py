"""LLM-backed final reply parser with explicit failure modes."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable, Dict, Optional, Tuple

from core.reply.reply_context import ReplyContext
from services.llm_client import get_llm_client


SYSTEM_PROMPT = (
    "You are an emission-analysis assistant reply writer. Generate one concise, "
    "natural Chinese user reply from the structured ReplyContext.\n"
    "\n"
    "HARD RULES (these override all other rules):\n"
    "You MUST NOT fabricate any factual data. Specifically:\n"
    "\n"
    "(a) If tool_executed is False (no tools ran), you MUST NOT describe tool output "
    "as if it executed. Do NOT write '已查询到 X', '共 N 个数据点', or similar "
    "completion language. State that the action is pending or did not complete.\n"
    "\n"
    "(b) You MUST NOT include any specific numbers, data point counts, value ranges, "
    "or table data that are not explicitly present in ReplyContext. This includes "
    "emission factors, speed ranges, fleet compositions, default parameter values, "
    "parameter ranges. If a value is not in ReplyContext or in "
    "extra.runtime_defaults_injected, do NOT state it.\n"
    "\n"
    "(c) For default values: ONLY mention defaults that are present in "
    "extra.runtime_defaults_injected. Do NOT infer default values from context "
    "or general knowledge. If runtime_defaults_injected is empty or absent, do "
    "not mention any default values.\n"
    "\n"
    "(d) When in doubt about whether a fact is in ReplyContext, omit it. It is "
    "better to give a less specific reply than to fabricate.\n"
    "\n"
    "Core rules:\n"
    "0. (FACT BOUNDARY) Read tool_executed first. If False, your reply must NOT "
    "claim any tool output was produced. If True, reference only data present in "
    "tool_executions — do not extrapolate or invent additional results. Check "
    "executed_tool_names to know which tools actually ran.\n"
    "1. If intent_unresolved=true, ask the user what kind of emission analysis they "
    "want, presenting concrete options from available_tools.\n"
    "2. If stance='exploratory', give comparative guidance by listing comparable "
    "options from available_capabilities. Help the user narrow scope.\n"
    "3. If continuation_state is not empty, your reply should continue the prior "
    "task. Mention the current objective phase and what slots are still needed.\n"
    "4. If pending_clarifications is non-empty, generate a natural follow-up question "
    "for the first pending slot. Use the label field (not the slot key) when naming "
    "parameters, and use examples to prompt the user.\n"
    "5. If violations is non-empty, generate natural negotiation text using "
    "violation_type, involved_params, and suggested_resolution. Explain WHY the "
    "combination is invalid and offer alternatives. Never say '参数组合不合法' rigidly.\n"
    "6. If router_text is non-empty, prefer the structured fields above over "
    "router_text. Use router_text only when no structured guidance is present.\n"
    "7. If extra contains runtime_defaults_injected, explicitly state which defaults "
    "were used and invite revision: '如果您需要其他值，请告诉我'.\n"
    "\n"
    "Avoid duplicating sections. Keep the reply tight and actionable."
)

PROMPT_TEMPLATE = """Structured ReplyContext prototype:
{context_json}

Generate the final user-visible reply only."""


class LLMReplyTimeout(Exception):
    """Raised when reply generation exceeds the configured timeout."""


class LLMReplyError(Exception):
    """Raised when the LLM reply parser fails before producing a reply."""


class LLMReplyParser:
    def __init__(
        self,
        timeout_seconds: float = 20.0,
        llm_client: Optional[Any] = None,
        client_factory: Callable[[str], Any] = get_llm_client,
    ) -> None:
        self.timeout_seconds = float(timeout_seconds)
        self._client = llm_client
        self._client_factory = client_factory

    async def parse(self, ctx: ReplyContext) -> Tuple[str, Dict[str, Any]]:
        """Return (reply_text, metadata), raising explicit parser errors on failure."""

        prompt = self._render_prompt(ctx)
        started = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                self._get_client().chat(
                    messages=[{"role": "user", "content": prompt}],
                    system=SYSTEM_PROMPT,
                    temperature=0.0,
                ),
                timeout=self.timeout_seconds,
            )
            reply_text = getattr(response, "text", None) or getattr(response, "content", "")
            if not str(reply_text).strip():
                raise ValueError("empty LLM reply")
            return str(reply_text), {
                "mode": "llm",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "model": getattr(self._get_client(), "model", "unknown"),
                "fallback": False,
            }
        except asyncio.TimeoutError as exc:
            raise LLMReplyTimeout(f"timeout after {self.timeout_seconds}s") from exc
        except LLMReplyTimeout:
            raise
        except Exception as exc:
            raise LLMReplyError(f"{type(exc).__name__}: {exc}") from exc

    @staticmethod
    def _render_prompt(ctx: ReplyContext) -> str:
        context_json = json.dumps(ctx.to_dict(), ensure_ascii=False, indent=2, default=str)
        return PROMPT_TEMPLATE.format(context_json=context_json)

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory("synthesis")
        return self._client
