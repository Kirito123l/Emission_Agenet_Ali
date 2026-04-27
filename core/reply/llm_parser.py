"""LLM-backed final reply parser with explicit failure modes."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable, Dict, Optional, Tuple

from core.reply.reply_context import ReplyContext
from services.llm_client import get_llm_client


SYSTEM_PROMPT = (
    "You are an emission-analysis assistant reply writer. Rewrite the provided "
    "structured context into one concise, natural Chinese user reply. Use only "
    "provided facts. Do not invent values. If execution was blocked or needs "
    "clarification, ask exactly the needed next question. Avoid duplicating sections."
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
