from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from config import get_config
from core.analytical_objective import (
    AnalyticalObjective,
    ConversationalStance,
    StanceConfidence,
)


@dataclass
class StanceResolution:
    stance: ConversationalStance
    confidence: StanceConfidence
    evidence: List[str]
    resolved_by: str


class StanceResolver:
    """Resolve conversational stance without owning any LLM calls."""

    _DEFAULT_SIGNALS = {
        "deliberative_signals": [
            "先确认",
            "先帮我确认",
            "先看一下",
            "列一下参数",
            "参数是什么",
            "怎么设置",
            "需要什么",
            "confirm first",
            "check first",
        ],
        "directive_verbs": ["查", "算", "计算", "给我", "帮我查", "要", "calculate", "query"],
        "directive_patterns": ["算一下", "帮我查", "给我", "calculate", "query"],
        "exploratory_signals": ["看看能做什么", "都有哪些", "可以分析什么", "能分析什么"],
        "reversal_signals": ["等等", "再想想", "换成", "不对", "改成", "算了还是", "重新"],
    }

    def __init__(self, signal_config: Optional[Dict[str, Any] | str | Path] = None, runtime_config: Any = None):
        self.runtime_config = runtime_config or get_config()
        self.signals = self._load_signals(signal_config)

    def resolve_fast(
        self,
        user_message: str,
        ao: Optional[AnalyticalObjective],
    ) -> Optional[StanceResolution]:
        """Rules-only path. Returns None when no clear stance signal hits."""
        if not getattr(self.runtime_config, "enable_conversational_stance", True):
            return None
        message = self._normalize(user_message)
        if not message:
            return None

        deliberative = self._first_signal(message, "deliberative_signals")
        if deliberative:
            return StanceResolution(
                stance=ConversationalStance.DELIBERATIVE,
                confidence=StanceConfidence.HIGH,
                evidence=[f"signal:{deliberative}"],
                resolved_by="rule:deliberative_signal",
            )

        exploratory = self._first_signal(message, "exploratory_signals")
        if exploratory and not self._has_directive_signal(message):
            return StanceResolution(
                stance=ConversationalStance.EXPLORATORY,
                confidence=StanceConfidence.HIGH,
                evidence=[f"signal:{exploratory}"],
                resolved_by="rule:exploratory_signal",
            )

        directive = self._first_signal(message, "directive_patterns")
        if directive:
            return StanceResolution(
                stance=ConversationalStance.DIRECTIVE,
                confidence=StanceConfidence.MEDIUM,
                evidence=[f"signal:{directive}"],
                resolved_by="rule:directive_signal",
            )

        if len(message) < 25 and self._has_directive_signal(message):
            return StanceResolution(
                stance=ConversationalStance.DIRECTIVE,
                confidence=StanceConfidence.MEDIUM,
                evidence=["short_directive_message"],
                resolved_by="rule:directive_signal",
            )

        return None

    def resolve_with_llm_hint(
        self,
        fast_result: Optional[StanceResolution],
        llm_hint: Optional[Dict[str, Any]],
    ) -> StanceResolution:
        """Merge fast rules and slot-filler stance hint."""
        if not getattr(self.runtime_config, "enable_conversational_stance", True):
            return StanceResolution(
                stance=ConversationalStance.UNKNOWN,
                confidence=StanceConfidence.LOW,
                evidence=["feature_disabled"],
                resolved_by="feature_disabled",
            )
        parsed = (
            self._parse_llm_hint(llm_hint)
            if getattr(self.runtime_config, "enable_stance_llm_resolution", True)
            else None
        )

        if fast_result is not None and fast_result.confidence == StanceConfidence.HIGH:
            return fast_result
        if parsed is not None and parsed.confidence == StanceConfidence.HIGH:
            return parsed
        if fast_result is not None and fast_result.confidence == StanceConfidence.MEDIUM:
            return fast_result
        if parsed is not None and parsed.confidence == StanceConfidence.MEDIUM:
            return parsed
        if fast_result is not None:
            return fast_result
        if parsed is not None:
            return parsed
        return StanceResolution(
            stance=ConversationalStance.DIRECTIVE,
            confidence=StanceConfidence.LOW,
            evidence=["default"],
            resolved_by="default_directive",
        )

    def detect_reversal(
        self,
        user_message: str,
        current_stance: ConversationalStance,
    ) -> Optional[ConversationalStance]:
        if not getattr(self.runtime_config, "enable_conversational_stance", True):
            return None
        if not getattr(self.runtime_config, "enable_stance_reversal_detection", True):
            return None
        message = self._normalize(user_message)
        if not message:
            return None
        signal = self._first_signal(message, "reversal_signals")
        if not signal:
            return None
        if current_stance == ConversationalStance.DELIBERATIVE:
            return None
        return ConversationalStance.DELIBERATIVE

    def reversal_evidence(self, user_message: str) -> Optional[str]:
        signal = self._first_signal(self._normalize(user_message), "reversal_signals")
        return f"signal:{signal}" if signal else None

    def _first_signal(self, message: str, key: str) -> Optional[str]:
        for signal in self.signals.get(key, []):
            candidate = str(signal or "").strip().lower()
            if candidate and candidate in message:
                return candidate
        return None

    def _has_directive_signal(self, message: str) -> bool:
        return bool(
            self._first_signal(message, "directive_verbs")
            or self._first_signal(message, "directive_patterns")
        )

    def _parse_llm_hint(self, llm_hint: Optional[Dict[str, Any]]) -> Optional[StanceResolution]:
        if not isinstance(llm_hint, dict):
            return None
        stance_raw = str(llm_hint.get("value") or llm_hint.get("stance") or "").strip().lower()
        if not stance_raw:
            return None
        try:
            stance = ConversationalStance(stance_raw)
        except ValueError:
            return None
        confidence_raw = str(llm_hint.get("confidence") or "low").strip().lower()
        try:
            confidence = StanceConfidence(confidence_raw)
        except ValueError:
            confidence = StanceConfidence.LOW
        reasoning = str(llm_hint.get("reasoning") or "").strip()
        evidence = ["llm_slot_filler"]
        if reasoning:
            evidence.append(f"reasoning:{reasoning[:30]}")
        return StanceResolution(
            stance=stance,
            confidence=confidence,
            evidence=evidence,
            resolved_by="llm_slot_filler",
        )

    def _load_signals(self, signal_config: Optional[Dict[str, Any] | str | Path]) -> Dict[str, List[str]]:
        if isinstance(signal_config, dict):
            raw = signal_config
        else:
            path = Path(signal_config or getattr(self.runtime_config, "stance_signals_path", ""))
            raw = {}
            if path.exists():
                loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if isinstance(loaded, dict):
                    raw = loaded
        merged: Dict[str, List[str]] = {}
        for key, defaults in self._DEFAULT_SIGNALS.items():
            values = raw.get(key, defaults) if isinstance(raw, dict) else defaults
            merged[key] = [
                str(item).strip().lower()
                for item in list(values or [])
                if str(item).strip()
            ]
        return merged

    @staticmethod
    def _normalize(user_message: str) -> str:
        return str(user_message or "").strip().lower()
