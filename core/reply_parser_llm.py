"""LLM-backed user reply parser (user→agent direction).

Task Pack A Layer 2: LLM primary parser for interpreting Chinese/English
natural-language clarification replies ("小汽车", "下午高峰", "嗯好", "改成冬季夜间").

Not to be confused with ``core/reply/llm_parser.py`` (agent→user direction).

TODO(A.2 round): When wiring this parser into parameter_negotiation /
input_completion, add a NEW flag ``enable_llm_user_reply_parser``
(default False). DO NOT reuse ``enable_llm_reply_parser`` — that flag
already governs the agent→user reply parser at core/reply/llm_parser.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ReplyDecision(str, Enum):
    """Outcome of parsing a user clarification reply."""
    CONFIRMED = "confirmed"
    NONE_OF_ABOVE = "none_of_above"
    PARTIAL_REPLY = "partial_reply"
    AMBIGUOUS_REPLY = "ambiguous_reply"
    PAUSE = "pause"


@dataclass
class ParsedReply:
    """Result of parsing a user clarification reply.

    ``confidence`` is a signal for upper layers to set ``needs_confirmation``;
    this class does NOT gate on it (F1).  ``needs_confirmation`` must be set
    by the caller (parameter_negotiation / input_completion) based on their
    own confidence-threshold policy.
    """
    decision: ReplyDecision
    slot_values: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    evidence: str = ""
    needs_confirmation: bool = False


class LLMReplyParser:
    """LLM user-reply parser (user→agent direction).

    Corresponds to Task Pack A Layer 2 of the three-layer parsing
    architecture.  Layer 1 (regex fast path) and Layer 3 (standardization
    fallback) are implemented by the callers (parameter_negotiation /
    input_completion) in their own modules.

    This parser does NOT import ViolationRecord, AOManager, or
    FactMemory — context fields like ``confirmed_params`` and
    ``constraint_violations`` must be assembled by the caller from
    AO + ``memory.session_confirmed_parameters`` + ReplyContext and
    passed in as plain dicts / lists.

    NOT to be confused with ``core/reply/llm_parser.py`` (agent→user
    direction).
    """

    def __init__(
        self,
        llm_client: Optional[Any] = None,
        timeout: float = 5.0,
    ) -> None:
        self._client = llm_client
        self.timeout = float(timeout)

    # ── public API ──────────────────────────────────────────────────

    async def parse(
        self,
        user_reply: str,
        context: Dict[str, Any],
    ) -> Optional[ParsedReply]:
        """Parse a user clarification reply with the LLM.

        Parameters
        ----------
        user_reply:
            Raw user message (e.g. "嗯好", "改成下午高峰", "小汽车").
        context:
            Assembled by the caller.  Expected keys:

            * tool_name (str): current tool.
            * slot_name (str): slot being clarified.
            * candidate_values (List[Any]): legal values from
              ``ReplyContext.legal_values_for_pending_slots`` (F3).
            * confirmed_params (Dict[str, Any]): already-confirmed
              parameters (from AO + memory.session_confirmed_parameters
              + ReplyContext).
            * agent_question (str): the question the agent asked.
            * constraint_violations (List[Dict[str, Any]]): serialized
              ``ViolationRecord`` dicts — previously observed violations,
              NOT prescriptive rules (F2).

        Returns
        -------
        ParsedReply on success, ``None`` on any recoverable failure
        (timeout / connection error / bad JSON / missing fields).
        """
        prompt = self._render_prompt(user_reply, context)
        system_prompt = self._load_system_prompt()
        started = time.perf_counter()

        try:
            result = await asyncio.wait_for(
                self._get_client().chat_json(
                    messages=[{"role": "user", "content": prompt}],
                    system=system_prompt,
                    temperature=0.0,
                ),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("LLMReplyParser timed out after %.1fs", self.timeout)
            return None
        except Exception as exc:
            # Do NOT swallow cancellation or system signals (F6).
            if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
            logger.warning("LLMReplyParser LLM call failed: %s: %s", type(exc).__name__, exc)
            return None

        return self._validate_and_build(result, started)

    # ── internal helpers ────────────────────────────────────────────

    @staticmethod
    def _load_system_prompt() -> str:
        """Load the reply-parser system prompt from its YAML file."""
        from pathlib import Path
        import yaml

        prompt_path = Path(__file__).resolve().parents[1] / "config" / "prompts" / "reply_parser.yaml"
        try:
            with open(prompt_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            return str(data.get("system_prompt") or "")
        except Exception:
            logger.exception("Failed to load reply_parser.yaml, using empty prompt")
            return ""

    @staticmethod
    def _render_prompt(user_reply: str, context: Dict[str, Any]) -> str:
        """Render the user_template from reply_parser.yaml with context values."""
        from pathlib import Path
        import yaml

        prompt_path = Path(__file__).resolve().parents[1] / "config" / "prompts" / "reply_parser.yaml"
        try:
            with open(prompt_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            template = str(data.get("user_template") or "")
        except Exception:
            logger.exception("Failed to load reply_parser.yaml user_template")
            template = ""

        candidate_values = context.get("candidate_values") or []
        confirmed_params = context.get("confirmed_params") or {}
        constraint_violations = context.get("constraint_violations") or []

        rendered = template.replace("{user_reply}", str(user_reply or ""))
        rendered = rendered.replace("{tool_name}", str(context.get("tool_name") or ""))
        rendered = rendered.replace("{slot_name}", str(context.get("slot_name") or ""))
        rendered = rendered.replace("{agent_question}", str(context.get("agent_question") or ""))
        rendered = rendered.replace(
            "{candidate_values_json}",
            json.dumps(candidate_values, ensure_ascii=False, indent=2),
        )
        rendered = rendered.replace(
            "{confirmed_params_json}",
            json.dumps(confirmed_params, ensure_ascii=False, indent=2),
        )
        rendered = rendered.replace(
            "{constraint_violations_json}",
            json.dumps(constraint_violations, ensure_ascii=False, indent=2),
        )
        return rendered

    @staticmethod
    def _validate_and_build(raw: Dict[str, Any], started: float) -> Optional[ParsedReply]:
        """Validate LLM JSON payload and build a ParsedReply."""
        if not isinstance(raw, dict):
            logger.warning("LLMReplyParser: response is not a dict")
            return None

        decision_raw = str(raw.get("decision") or "").strip().lower()
        try:
            decision = ReplyDecision(decision_raw)
        except ValueError:
            logger.warning("LLMReplyParser: unknown decision %r", decision_raw)
            return None

        slot_values = raw.get("slot_values")
        if not isinstance(slot_values, dict):
            slot_values = {}

        confidence_raw = raw.get("confidence")
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        evidence = str(raw.get("evidence") or "")[:500]

        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.debug(
            "LLMReplyParser: decision=%s confidence=%.2f latency_ms=%d",
            decision.value,
            confidence,
            latency_ms,
        )

        return ParsedReply(
            decision=decision,
            slot_values=dict(slot_values),
            confidence=confidence,
            evidence=evidence,
        )

    def _get_client(self) -> Any:
        """Lazily acquire the fast-model LLM client.

        Temporarily reuses the ``standardizer`` purpose bucket so it
        automatically follows ``LLM_FAST_MODEL``.  A dedicated
        ``reply_parser`` bucket can be introduced later.
        """
        if self._client is None:
            from services.llm_client import get_llm_client
            self._client = get_llm_client(purpose="standardizer")
        return self._client
