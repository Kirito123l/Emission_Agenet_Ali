from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from config import get_config
from core.analytical_objective import AOStatus
from core.ao_manager import AOManager

logger = logging.getLogger(__name__)

_UPLOAD_SUFFIX_RE = re.compile(
    r"(?:\n+文件已上传，路径:\s*.+?)(?:\n请使用 input_file 参数处理此文件。)?\s*$",
    re.S,
)


class AOClassType(Enum):
    CONTINUATION = "continuation"
    REVISION = "revision"
    NEW_AO = "new_ao"


@dataclass
class AOClassification:
    classification: AOClassType
    target_ao_id: Optional[str]
    reference_ao_id: Optional[str]
    new_objective_text: Optional[str]
    confidence: float
    reasoning: str
    layer: str


@dataclass
class ClassifierTelemetry:
    turn: int
    user_message_preview: str
    layer_hit: str
    rule_signal: Optional[str]
    classification: str
    confidence: float
    layer2_latency_ms: Optional[float]
    target_ao_id: Optional[str]
    reference_ao_id: Optional[str]
    reasoning: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn": self.turn,
            "user_message_preview": self.user_message_preview,
            "layer_hit": self.layer_hit,
            "rule_signal": self.rule_signal,
            "classification": self.classification,
            "confidence": self.confidence,
            "layer2_latency_ms": self.layer2_latency_ms,
            "target_ao_id": self.target_ao_id,
            "reference_ao_id": self.reference_ao_id,
            "reasoning": self.reasoning,
        }


AO_CLASSIFIER_SYSTEM_PROMPT = """你是交通排放分析会话的意图分类器。

当用户发送新消息时，你需要判断这条消息是：
- CONTINUATION: 延续当前 active 分析目标（补全参数、确认选项、继续工具链）
- REVISION: 修改已完成分析目标的参数，要求重新计算
- NEW_AO: 开始一个独立的新分析目标（可能引用之前的 AO 结果）

注意：
- "把刚才结果画图"是 NEW_AO，但它可能引用之前的 AO
- "改成冬季再算"是 REVISION，指向之前的计算 AO
- "NOx"（单独一个词）在有 active AO 等待参数时是 CONTINUATION
- "再查一个 CO2"在无 active AO 时是 NEW_AO

输出 JSON：
{
  "classification": "CONTINUATION" | "REVISION" | "NEW_AO",
  "target_ao_id": "AO#2" or null,
  "reference_ao_id": "AO#2" or null,
  "new_objective_text": "...",
  "confidence": 0.0,
  "reasoning": "简短解释"
}
"""


class OAScopeClassifier:
    _alias_cache: Optional[set[str]] = None
    _reference_signal_patterns = (
        "改成",
        "换成",
        "重新算",
        "重新计算",
        "刚才的结果",
        "基于上次",
        "基于刚才",
        "沿用",
        "参考刚才",
        "instead",
        "change to",
        "revise",
        "based on previous",
        "use previous",
    )

    def __init__(self, ao_manager: AOManager, llm_client: Any = None, config: Any = None):
        self.ao_manager = ao_manager
        self.llm_client = llm_client
        self.config = config or get_config()
        self._telemetry_log: List[ClassifierTelemetry] = []

    async def classify(
        self,
        user_message: str,
        recent_conversation: List[Dict[str, Any]],
        task_state: Any,
    ) -> AOClassification:
        current_turn = self._current_turn_index()
        if getattr(self.config, "enable_ao_classifier_rule_layer", True):
            rule_result = self._rule_layer1(user_message, task_state)
            if rule_result is not None:
                self._record_telemetry(
                    ClassifierTelemetry(
                        turn=current_turn,
                        user_message_preview=self._message_preview(user_message),
                        layer_hit="rule_layer1",
                        rule_signal=self._extract_rule_signal(rule_result),
                        classification=rule_result.classification.name,
                        confidence=rule_result.confidence,
                        layer2_latency_ms=None,
                        target_ao_id=rule_result.target_ao_id,
                        reference_ao_id=rule_result.reference_ao_id,
                        reasoning=rule_result.reasoning,
                    )
                )
                return rule_result

        llm_latency_ms: Optional[float] = None
        if getattr(self.config, "enable_ao_classifier_llm_layer", True):
            try:
                started = time.perf_counter()
                llm_result = await self._llm_layer2(user_message, recent_conversation)
                llm_latency_ms = round((time.perf_counter() - started) * 1000, 2)
                if llm_result.confidence >= getattr(
                    self.config,
                    "ao_classifier_confidence_threshold",
                    0.7,
                ):
                    self._record_telemetry(
                        ClassifierTelemetry(
                            turn=current_turn,
                            user_message_preview=self._message_preview(user_message),
                            layer_hit="llm_layer2",
                            rule_signal=None,
                            classification=llm_result.classification.name,
                            confidence=llm_result.confidence,
                            layer2_latency_ms=llm_latency_ms,
                            target_ao_id=llm_result.target_ao_id,
                            reference_ao_id=llm_result.reference_ao_id,
                            reasoning=llm_result.reasoning,
                        )
                    )
                    return llm_result
            except Exception as exc:
                logger.warning("AO classifier Layer 2 failed: %s", exc)

        fallback = AOClassification(
            classification=AOClassType.NEW_AO,
            target_ao_id=None,
            reference_ao_id=None,
            new_objective_text=(user_message or "")[:100],
            confidence=0.3,
            reasoning="Fallback: Layer 2 unavailable or low confidence",
            layer="fallback",
        )
        self._record_telemetry(
            ClassifierTelemetry(
                turn=current_turn,
                user_message_preview=self._message_preview(user_message),
                layer_hit="fallback",
                rule_signal=None,
                classification=fallback.classification.name,
                confidence=fallback.confidence,
                layer2_latency_ms=llm_latency_ms,
                target_ao_id=fallback.target_ao_id,
                reference_ao_id=fallback.reference_ao_id,
                reasoning=fallback.reasoning,
            )
        )
        return fallback

    def _rule_layer1(
        self,
        user_message: str,
        task_state: Any,
    ) -> Optional[AOClassification]:
        current_ao = self.ao_manager.get_current_ao()
        ao_history = list(getattr(getattr(self.ao_manager, "_memory", None), "ao_history", []) or [])

        if not ao_history:
            return AOClassification(
                classification=AOClassType.NEW_AO,
                target_ao_id=None,
                reference_ao_id=None,
                new_objective_text=(user_message or "")[:100],
                confidence=1.0,
                reasoning="first_message_in_session",
                layer="rule",
            )

        if getattr(task_state, "active_input_completion", None):
            return self._make_continuation("active_input_completion")

        if getattr(task_state, "active_parameter_negotiation", None):
            return self._make_continuation("active_parameter_negotiation")

        continuation = getattr(task_state, "continuation", None)
        if continuation is not None and (
            getattr(continuation, "next_tool_name", None)
            or getattr(continuation, "residual_plan_summary", None)
        ):
            return self._make_continuation("continuation_pending")

        if (
            current_ao is not None
            and current_ao.status in {AOStatus.ACTIVE, AOStatus.REVISING}
            and self._is_short_clarification_reply(user_message)
        ):
            return self._make_continuation("short_clarification")

        if self._is_pure_file_upload(user_message):
            if current_ao is not None and self._ao_waiting_for_file(current_ao, task_state):
                return self._make_continuation("file_supplement")

        revision_target = self._detect_revision_target(user_message)
        if revision_target is not None:
            target_id = revision_target.ao_id
            return AOClassification(
                classification=AOClassType.REVISION,
                target_ao_id=target_id,
                reference_ao_id=None,
                new_objective_text=self._build_revision_objective_text(revision_target, user_message),
                confidence=0.92,
                reasoning="revision phrase matched a completed analytical objective",
                layer="rule",
            )

        if current_ao is None and not self._has_revision_reference_signals(user_message):
            return AOClassification(
                classification=AOClassType.NEW_AO,
                target_ao_id=None,
                reference_ao_id=None,
                new_objective_text=(user_message or "")[:100],
                confidence=0.9,
                reasoning="no_active_ao_no_revision_signal",
                layer="rule",
            )

        return None

    def _make_continuation(self, reason: str) -> AOClassification:
        current = self.ao_manager.get_current_ao()
        return AOClassification(
            classification=AOClassType.CONTINUATION,
            target_ao_id=current.ao_id if current else None,
            reference_ao_id=None,
            new_objective_text=None,
            confidence=0.98,
            reasoning=reason,
            layer="rule",
        )

    def _detect_revision_target(self, user_message: str) -> Optional[Any]:
        message = str(user_message or "").strip().lower()
        revision_cues = ("改成", "换成", "重新算", "重新计算", "instead", "change to", "revise")
        if not any(cue in message for cue in revision_cues):
            return None
        completed = self.ao_manager.get_completed_aos()
        return completed[-1] if completed else None

    def _build_revision_objective_text(self, parent_ao: Any, user_message: str) -> str:
        base = str(getattr(parent_ao, "objective_text", "") or "").strip()
        delta = str(user_message or "").strip()
        if base:
            return f"修订 {parent_ao.ao_id}: {base} | {delta}"[:240]
        return f"修订 {parent_ao.ao_id}: {delta}"[:240]

    def _has_revision_reference_signals(self, msg: str) -> bool:
        text = str(msg or "").strip().lower()
        if not text:
            return False
        return any(pattern in text for pattern in self._reference_signal_patterns)

    @classmethod
    def _mapping_aliases(cls) -> set[str]:
        if cls._alias_cache is not None:
            return cls._alias_cache
        mappings_path = Path(__file__).resolve().parent.parent / "config" / "unified_mappings.yaml"
        aliases: set[str] = set()
        try:
            with mappings_path.open("r", encoding="utf-8") as fh:
                payload = yaml.safe_load(fh) or {}
            for key, value in payload.items():
                if not isinstance(value, list):
                    continue
                for item in value:
                    if not isinstance(item, dict):
                        continue
                    standard_name = str(item.get("standard_name") or "").strip()
                    if standard_name:
                        aliases.add(standard_name.lower())
                    display_name_zh = str(item.get("display_name_zh") or "").strip()
                    if display_name_zh:
                        aliases.add(display_name_zh.lower())
                    for alias in item.get("aliases") or []:
                        alias_text = str(alias or "").strip()
                        if alias_text:
                            aliases.add(alias_text.lower())
        except Exception as exc:
            logger.warning("Failed to load AO classifier aliases: %s", exc)
        cls._alias_cache = aliases
        return aliases

    def _is_short_clarification_reply(self, msg: str) -> bool:
        stripped = _UPLOAD_SUFFIX_RE.sub("", str(msg or "")).strip()
        if not stripped:
            return False
        lowered = stripped.lower()
        if len(stripped) < 20 and lowered in self._mapping_aliases():
            return True
        confirm_words = {
            "是",
            "否",
            "对",
            "不对",
            "好的",
            "嗯",
            "确认",
            "取消",
            "yes",
            "no",
            "ok",
            "okay",
        }
        if lowered in confirm_words:
            return True
        continuation_phrases = ("按刚才的", "就这样", "沿用前面", "same as above", "use previous")
        return any(phrase in stripped for phrase in continuation_phrases)

    def _is_pure_file_upload(self, msg: str) -> bool:
        stripped = _UPLOAD_SUFFIX_RE.sub("", str(msg or "")).strip()
        return not stripped

    def _ao_waiting_for_file(self, ao: Any, task_state: Any) -> bool:
        if getattr(task_state, "active_input_completion", None) is not None:
            return True
        prompt = str(getattr(getattr(task_state, "control", None), "clarification_question", "") or "")
        if "文件" in prompt or "上传" in prompt or "file" in prompt.lower():
            return True
        objective = str(getattr(ao, "objective_text", "") or "").lower()
        return "file" in objective or "文件" in objective

    async def _llm_layer2(
        self,
        user_message: str,
        recent_conversation: List[Dict[str, Any]],
    ) -> AOClassification:
        if self.llm_client is None:
            raise RuntimeError("AO classifier LLM client unavailable")
        prompt = self._build_classifier_prompt(user_message, recent_conversation)
        timeout = float(getattr(self.config, "ao_classifier_timeout_sec", 5.0))
        response = await asyncio.wait_for(
            self.llm_client.chat_json(
                messages=[{"role": "user", "content": prompt}],
                system=AO_CLASSIFIER_SYSTEM_PROMPT,
                temperature=0.0,
            ),
            timeout=timeout,
        )
        return self._parse_classifier_response(response)

    def _build_classifier_prompt(
        self,
        user_message: str,
        recent_conversation: List[Dict[str, Any]],
    ) -> str:
        ao_summary = self.ao_manager.get_summary_for_classifier()
        payload = {
            "ao_summary": ao_summary,
            "recent_conversation": recent_conversation[-6:],
            "current_user_message": user_message,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _parse_classifier_response(self, response: Dict[str, Any]) -> AOClassification:
        payload = response if isinstance(response, dict) else {}
        raw = str(payload.get("classification") or "").strip().upper()
        mapping = {
            "CONTINUATION": AOClassType.CONTINUATION,
            "REVISION": AOClassType.REVISION,
            "NEW_AO": AOClassType.NEW_AO,
        }
        classification = mapping.get(raw, AOClassType.NEW_AO)
        target_ao_id = (
            str(payload.get("target_ao_id")).strip()
            if payload.get("target_ao_id") is not None
            else None
        )
        reference_ao_id = (
            str(payload.get("reference_ao_id")).strip()
            if payload.get("reference_ao_id") is not None
            else None
        )
        return AOClassification(
            classification=classification,
            target_ao_id=target_ao_id,
            reference_ao_id=reference_ao_id,
            new_objective_text=(
                str(payload.get("new_objective_text")).strip()
                if payload.get("new_objective_text") is not None
                else None
            ),
            confidence=float(payload.get("confidence") or 0.0),
            reasoning=str(payload.get("reasoning") or ""),
            layer="llm",
        )

    def telemetry_size(self) -> int:
        return len(self._telemetry_log)

    def telemetry_slice(self, start_index: int = 0) -> List[Dict[str, Any]]:
        if start_index < 0:
            start_index = 0
        return [item.to_dict() for item in self._telemetry_log[start_index:]]

    def _record_telemetry(self, item: ClassifierTelemetry) -> None:
        try:
            self._telemetry_log.append(item)
            self._telemetry_log = self._telemetry_log[-200:]
        except Exception as exc:
            logger.warning("Failed to record classifier telemetry: %s", exc)

    def _current_turn_index(self) -> int:
        return int(getattr(getattr(self.ao_manager, "_memory", None), "last_turn_index", 0) or 0) + 1

    @staticmethod
    def _message_preview(user_message: str) -> str:
        preview = str(user_message or "").strip().replace("\n", " ")
        return preview[:80]

    @staticmethod
    def _extract_rule_signal(result: AOClassification) -> Optional[str]:
        allowed = {
            "active_input_completion",
            "active_parameter_negotiation",
            "continuation_pending",
            "short_clarification",
            "file_supplement",
            "first_message_in_session",
            "no_active_ao_no_revision_signal",
        }
        return result.reasoning if result.layer == "rule" and result.reasoning in allowed else None
