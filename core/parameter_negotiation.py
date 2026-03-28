from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class NegotiationDecisionType(str, Enum):
    CONFIRMED = "confirmed"
    NONE_OF_ABOVE = "none_of_above"
    AMBIGUOUS_REPLY = "ambiguous_reply"


@dataclass
class NegotiationCandidate:
    index: int
    normalized_value: str
    display_label: str
    confidence: Optional[float] = None
    strategy: Optional[str] = None
    reason: Optional[str] = None
    aliases: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "normalized_value": self.normalized_value,
            "display_label": self.display_label,
            "confidence": self.confidence,
            "strategy": self.strategy,
            "reason": self.reason,
            "aliases": list(self.aliases),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "NegotiationCandidate":
        payload = data if isinstance(data, dict) else {}
        return cls(
            index=int(payload.get("index") or 0),
            normalized_value=str(payload.get("normalized_value") or "").strip(),
            display_label=str(payload.get("display_label") or "").strip(),
            confidence=(
                float(payload["confidence"])
                if payload.get("confidence") is not None
                else None
            ),
            strategy=str(payload.get("strategy")).strip() if payload.get("strategy") is not None else None,
            reason=str(payload.get("reason")).strip() if payload.get("reason") is not None else None,
            aliases=[
                str(item).strip()
                for item in (payload.get("aliases") or [])
                if str(item).strip()
            ],
        )


@dataclass
class ParameterNegotiationRequest:
    request_id: str
    parameter_name: str
    raw_value: str
    confidence: Optional[float]
    trigger_reason: str
    tool_name: Optional[str] = None
    arg_name: Optional[str] = None
    strategy: Optional[str] = None
    candidates: List[NegotiationCandidate] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "parameter_name": self.parameter_name,
            "raw_value": self.raw_value,
            "confidence": self.confidence,
            "trigger_reason": self.trigger_reason,
            "tool_name": self.tool_name,
            "arg_name": self.arg_name,
            "strategy": self.strategy,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ParameterNegotiationRequest":
        payload = data if isinstance(data, dict) else {}
        return cls(
            request_id=str(payload.get("request_id") or "").strip(),
            parameter_name=str(payload.get("parameter_name") or "").strip(),
            raw_value=str(payload.get("raw_value") or "").strip(),
            confidence=(
                float(payload["confidence"])
                if payload.get("confidence") is not None
                else None
            ),
            trigger_reason=str(payload.get("trigger_reason") or "").strip(),
            tool_name=str(payload.get("tool_name")).strip() if payload.get("tool_name") is not None else None,
            arg_name=str(payload.get("arg_name")).strip() if payload.get("arg_name") is not None else None,
            strategy=str(payload.get("strategy")).strip() if payload.get("strategy") is not None else None,
            candidates=[
                NegotiationCandidate.from_dict(item)
                for item in (payload.get("candidates") or [])
                if isinstance(item, dict)
            ],
        )

    @classmethod
    def create(
        cls,
        *,
        parameter_name: str,
        raw_value: Any,
        trigger_reason: str,
        tool_name: Optional[str] = None,
        arg_name: Optional[str] = None,
        confidence: Optional[float] = None,
        strategy: Optional[str] = None,
        candidates: Optional[List[NegotiationCandidate]] = None,
    ) -> "ParameterNegotiationRequest":
        return cls(
            request_id=f"neg-{parameter_name}-{uuid.uuid4().hex[:8]}",
            parameter_name=parameter_name,
            raw_value=str(raw_value or "").strip(),
            confidence=confidence,
            trigger_reason=trigger_reason,
            tool_name=tool_name,
            arg_name=arg_name or parameter_name,
            strategy=strategy,
            candidates=list(candidates or []),
        )


@dataclass
class ParameterNegotiationDecision:
    parameter_name: str
    decision_type: NegotiationDecisionType
    user_reply: str
    selected_index: Optional[int] = None
    selected_value: Optional[str] = None
    request_id: Optional[str] = None
    selected_display_label: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameter_name": self.parameter_name,
            "decision_type": self.decision_type.value,
            "user_reply": self.user_reply,
            "selected_index": self.selected_index,
            "selected_value": self.selected_value,
            "request_id": self.request_id,
            "selected_display_label": self.selected_display_label,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ParameterNegotiationDecision":
        payload = data if isinstance(data, dict) else {}
        decision_type = payload.get("decision_type") or NegotiationDecisionType.AMBIGUOUS_REPLY.value
        return cls(
            parameter_name=str(payload.get("parameter_name") or "").strip(),
            decision_type=NegotiationDecisionType(decision_type),
            user_reply=str(payload.get("user_reply") or "").strip(),
            selected_index=int(payload["selected_index"]) if payload.get("selected_index") is not None else None,
            selected_value=str(payload.get("selected_value")).strip() if payload.get("selected_value") is not None else None,
            request_id=str(payload.get("request_id")).strip() if payload.get("request_id") is not None else None,
            selected_display_label=(
                str(payload.get("selected_display_label")).strip()
                if payload.get("selected_display_label") is not None
                else None
            ),
        )


@dataclass
class ParameterNegotiationParseResult:
    is_resolved: bool
    decision: Optional[ParameterNegotiationDecision] = None
    needs_retry: bool = False
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_resolved": self.is_resolved,
            "decision": self.decision.to_dict() if self.decision else None,
            "needs_retry": self.needs_retry,
            "error_message": self.error_message,
        }


_NONE_OF_ABOVE_PHRASES = (
    "none of the above",
    "none",
    "都不对",
    "都不是",
    "都不行",
    "none-of-above",
)

_CHINESE_INDEX_MAP = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
}


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _extract_parenthetical_parts(text: str) -> List[str]:
    cleaned = str(text or "").strip()
    if not cleaned:
        return []
    parts = [cleaned]
    match = re.match(r"^(.*?)\s*\((.*?)\)\s*$", cleaned)
    if match:
        left = match.group(1).strip()
        right = match.group(2).strip()
        if left:
            parts.append(left)
        if right:
            parts.append(right)
    return parts


def _extract_indices(reply: str) -> List[int]:
    cleaned = str(reply or "").strip().lower()
    if not cleaned:
        return []

    indices: List[int] = []

    exact_digit = re.fullmatch(r"(\d+)", cleaned)
    if exact_digit:
        indices.append(int(exact_digit.group(1)))
        return indices

    patterns = (
        r"选第\s*(\d+)\s*个",
        r"第\s*(\d+)\s*个",
        r"option\s*(\d+)",
        r"choose\s*(\d+)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, cleaned):
            indices.append(int(match.group(1)))

    for char, index in _CHINESE_INDEX_MAP.items():
        if f"第{char}个" in cleaned or f"选第{char}个" in cleaned:
            indices.append(index)

    deduped: List[int] = []
    for index in indices:
        if index not in deduped:
            deduped.append(index)
    return deduped


def _extract_index(reply: str) -> Optional[int]:
    indices = _extract_indices(reply)
    if len(indices) == 1:
        return indices[0]
    return None


def reply_looks_like_confirmation_attempt(
    request: ParameterNegotiationRequest,
    user_reply: str,
) -> bool:
    normalized_reply = _normalize_text(user_reply)
    if not normalized_reply:
        return False
    if any(phrase in normalized_reply for phrase in _NONE_OF_ABOVE_PHRASES):
        return True
    if _extract_indices(user_reply):
        return True

    for candidate in request.candidates:
        terms = [candidate.display_label, candidate.normalized_value, *candidate.aliases]
        for term in terms:
            normalized_term = _normalize_text(term)
            if normalized_term and (
                normalized_reply == normalized_term
                or normalized_term in normalized_reply
            ):
                return True
    return False


def parse_parameter_negotiation_reply(
    request: ParameterNegotiationRequest,
    user_reply: str,
) -> ParameterNegotiationParseResult:
    reply = str(user_reply or "").strip()
    normalized_reply = _normalize_text(reply)
    if not normalized_reply:
        return ParameterNegotiationParseResult(
            is_resolved=False,
            needs_retry=True,
            error_message="Empty confirmation reply.",
        )

    if any(phrase in normalized_reply for phrase in _NONE_OF_ABOVE_PHRASES):
        return ParameterNegotiationParseResult(
            is_resolved=True,
            decision=ParameterNegotiationDecision(
                parameter_name=request.parameter_name,
                decision_type=NegotiationDecisionType.NONE_OF_ABOVE,
                user_reply=reply,
                request_id=request.request_id,
            ),
        )

    selected_index = _extract_index(reply)
    if selected_index is not None:
        for candidate in request.candidates:
            if candidate.index == selected_index:
                return ParameterNegotiationParseResult(
                    is_resolved=True,
                    decision=ParameterNegotiationDecision(
                        parameter_name=request.parameter_name,
                        decision_type=NegotiationDecisionType.CONFIRMED,
                        user_reply=reply,
                        selected_index=candidate.index,
                        selected_value=candidate.normalized_value,
                        selected_display_label=candidate.display_label,
                        request_id=request.request_id,
                    ),
                )
        return ParameterNegotiationParseResult(
            is_resolved=False,
            needs_retry=True,
            error_message=f"Candidate index {selected_index} is out of range.",
        )

    exact_matches: List[NegotiationCandidate] = []
    partial_matches: List[NegotiationCandidate] = []
    for candidate in request.candidates:
        terms = [candidate.display_label, candidate.normalized_value, *candidate.aliases]
        normalized_terms = {_normalize_text(term) for term in terms if _normalize_text(term)}
        if normalized_reply in normalized_terms:
            exact_matches.append(candidate)
            continue
        if any(term in normalized_reply for term in normalized_terms):
            partial_matches.append(candidate)

    matches = exact_matches or partial_matches
    unique_matches = {candidate.index: candidate for candidate in matches}
    if len(unique_matches) == 1:
        candidate = list(unique_matches.values())[0]
        return ParameterNegotiationParseResult(
            is_resolved=True,
            decision=ParameterNegotiationDecision(
                parameter_name=request.parameter_name,
                decision_type=NegotiationDecisionType.CONFIRMED,
                user_reply=reply,
                selected_index=candidate.index,
                selected_value=candidate.normalized_value,
                selected_display_label=candidate.display_label,
                request_id=request.request_id,
            ),
        )

    return ParameterNegotiationParseResult(
        is_resolved=False,
        needs_retry=True,
        error_message=(
            "The reply did not uniquely identify one candidate. "
            "Reply with the candidate index, canonical value, label, or '都不对'."
        ),
    )


def format_parameter_negotiation_prompt(
    request: ParameterNegotiationRequest,
    *,
    retry_message: Optional[str] = None,
) -> str:
    lines = [
        "参数确认 / Parameter Confirmation",
        (
            f"我不能安全地确定参数 `{request.parameter_name}` 的值。"
            f" 原始输入是 `{request.raw_value}`。"
        ),
    ]
    if request.tool_name:
        lines.append(f"相关工具: `{request.tool_name}`")
    if request.strategy or request.confidence is not None:
        confidence_text = (
            f"{request.confidence:.2f}"
            if request.confidence is not None
            else "n/a"
        )
        lines.append(
            f"触发原因: {request.trigger_reason} "
            f"(strategy={request.strategy or 'unknown'}, confidence={confidence_text})"
        )
    else:
        lines.append(f"触发原因: {request.trigger_reason}")

    lines.append("请在以下候选中确认一个：")
    for candidate in request.candidates:
        confidence_text = (
            f" · conf={candidate.confidence:.2f}"
            if candidate.confidence is not None
            else ""
        )
        strategy_text = f" · {candidate.strategy}" if candidate.strategy else ""
        lines.append(
            f"{candidate.index}. {candidate.display_label}"
            f" -> `{candidate.normalized_value}`{strategy_text}{confidence_text}"
        )

    if retry_message:
        lines.append(f"上次回复未能唯一确认: {retry_message}")

    lines.append(
        "回复方式：输入序号、候选标签、canonical value，或回复“都不对”/`none`。"
    )
    return "\n".join(lines)


def build_candidate_aliases(display_label: str, normalized_value: str, extra_aliases: Optional[List[str]] = None) -> List[str]:
    seen = set()
    aliases: List[str] = []
    for item in [display_label, normalized_value, *_extract_parenthetical_parts(display_label), *(extra_aliases or [])]:
        text = str(item or "").strip()
        lowered = text.lower()
        if text and lowered not in seen:
            seen.add(lowered)
            aliases.append(text)
    return aliases
