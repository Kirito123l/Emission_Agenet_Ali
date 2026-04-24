from __future__ import annotations

from typing import Any, Dict

from core.analytical_objective import ConversationalStance, StanceConfidence
from core.contracts.base import BaseContract, ContractContext, ContractInterception
from core.stance_resolver import StanceResolution, StanceResolver
from tools.contract_loader import get_tool_contract_registry


class StanceResolutionContract(BaseContract):
    """Wave 2 split contract for conversational stance resolution."""

    name = "stance_resolution"

    def __init__(self, inner_router: Any = None, ao_manager: Any = None, runtime_config: Any = None):
        self.inner_router = inner_router
        self.ao_manager = ao_manager
        self.runtime_config = runtime_config
        self.stance_resolver = StanceResolver(runtime_config=runtime_config)

    async def before_turn(self, context: ContractContext) -> ContractInterception:
        if not getattr(self.runtime_config, "enable_contract_split", False):
            return ContractInterception()
        if not getattr(self.runtime_config, "enable_split_stance_contract", True):
            return ContractInterception()
        oasc_state = dict(context.metadata.get("oasc") or {})
        classification = oasc_state.get("classification")
        current_ao = self.ao_manager.get_current_ao() if self.ao_manager is not None else None
        if classification is None or current_ao is None:
            return ContractInterception()
        classification_value = str(getattr(getattr(classification, "classification", None), "value", "") or "")
        turn = self._current_turn_index(pre_call=True)
        reversal_detected = False
        if classification_value == "continuation":
            reversal = self.stance_resolver.detect_reversal(context.effective_user_message, current_ao.stance)
            if reversal is not None:
                evidence = self.stance_resolver.reversal_evidence(context.effective_user_message)
                resolution = StanceResolution(
                    stance=reversal,
                    confidence=current_ao.stance_confidence,
                    evidence=[evidence or "user_reversal"],
                    resolved_by="user_reversal",
                )
                reversal_detected = True
            else:
                resolution = StanceResolution(
                    stance=current_ao.stance if current_ao.stance != ConversationalStance.UNKNOWN else ConversationalStance.DIRECTIVE,
                    confidence=current_ao.stance_confidence if current_ao.stance != ConversationalStance.UNKNOWN else StanceConfidence.LOW,
                    evidence=["current_stance"] if current_ao.stance != ConversationalStance.UNKNOWN else ["default"],
                    resolved_by=current_ao.stance_resolved_by or "default_directive",
                )
        else:
            fast = self.stance_resolver.resolve_fast(context.effective_user_message, current_ao)
            payload = context.metadata.get("stage2_payload") if isinstance(context.metadata.get("stage2_payload"), dict) else {}
            stance_hint, stance_raw, parse_success = self._extract_llm_stance_hint(payload)
            resolution = self.stance_resolver.resolve_with_llm_hint(fast, stance_hint)
            context.metadata["stance_resolution"] = {
                "stance_llm_hint_raw": stance_raw,
                "stance_llm_hint_parse_success": parse_success,
            }
            resolution = self._fallback_low_confidence_saturated_slots(
                resolution=resolution,
                context=context,
                current_ao=current_ao,
                payload=payload,
            )
        self._write_stance(current_ao, resolution, turn)
        stance_resolution_metadata = dict(context.metadata.get("stance_resolution") or {})
        context.metadata["stance"] = {
            "reversal_detected": reversal_detected,
            "stance": resolution.stance.value,
            "confidence": resolution.confidence.value,
            "resolved_by": resolution.resolved_by,
            "evidence": list(resolution.evidence),
            **{
                key: stance_resolution_metadata[key]
                for key in ("fallback_reason", "stance_fallback_skipped_reason")
                if key in stance_resolution_metadata
            },
        }
        return ContractInterception()

    @staticmethod
    def _extract_llm_stance_hint(llm_payload: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bool]:
        raw = llm_payload.get("stance") if isinstance(llm_payload, dict) else None
        if isinstance(raw, dict):
            return (
                {
                    "value": raw.get("value") or raw.get("stance"),
                    "confidence": raw.get("confidence") or raw.get("conf"),
                    "reasoning": raw.get("reasoning"),
                },
                dict(raw),
                True,
            )
        return None, None, False

    def _fallback_low_confidence_saturated_slots(
        self,
        *,
        resolution: StanceResolution,
        context: ContractContext,
        current_ao: Any,
        payload: Dict[str, Any],
    ) -> StanceResolution:
        metadata = context.metadata.setdefault("stance_resolution", {})
        if (
            resolution.stance not in {ConversationalStance.DELIBERATIVE, ConversationalStance.EXPLORATORY}
            or resolution.confidence != StanceConfidence.LOW
        ):
            return resolution
        tool_intent = context.metadata.get("tool_intent") or getattr(current_ao, "tool_intent", None)
        tool_name = str(getattr(tool_intent, "resolved_tool", "") or "").strip()
        if not tool_name:
            metadata["stance_fallback_skipped_reason"] = "no_resolved_tool"
            return resolution
        slots = self._extract_payload_slots(payload)
        if not self._check_required_filled_presence(tool_name, slots):
            metadata["stance_fallback_skipped_reason"] = "required_missing"
            return resolution
        if self._has_explicit_hedging(context.effective_user_message):
            metadata["stance_fallback_skipped_reason"] = "explicit_hedging"
            return resolution
        metadata["fallback_reason"] = "low_conf_nondirective_with_filled_required"
        return StanceResolution(
            stance=ConversationalStance.DIRECTIVE,
            confidence=StanceConfidence.LOW,
            evidence=list(resolution.evidence) + ["fallback_saturated_slots"],
            resolved_by="fallback_saturated_slots",
        )

    @classmethod
    def _check_required_filled_presence(cls, tool_name: str, payload_slots: Dict[str, Any]) -> bool:
        required_slots = cls._required_slots_for_tool(tool_name)
        if not required_slots:
            return False
        return all(cls._slot_present(payload_slots.get(slot)) for slot in required_slots)

    @staticmethod
    def _extract_payload_slots(payload: Dict[str, Any]) -> Dict[str, Any]:
        slots = payload.get("slots") if isinstance(payload, dict) else None
        if isinstance(slots, dict):
            return dict(slots)
        snapshot = payload.get("parameter_snapshot") if isinstance(payload, dict) else None
        return dict(snapshot) if isinstance(snapshot, dict) else {}

    @staticmethod
    def _slot_present(slot_payload: Any) -> bool:
        value = slot_payload.get("value") if isinstance(slot_payload, dict) else slot_payload
        return value not in (None, "", [])

    @staticmethod
    def _has_explicit_hedging(user_message: str) -> bool:
        text = str(user_message or "").strip().lower()
        if not text:
            return False
        hedging_terms = (
            "等等",
            "先确认",
            "先看看",
            "先看",
            "如果",
            "或者",
            "还是",
            "要不要",
            "scope",
            "能否",
        )
        return any(term in text for term in hedging_terms)

    @classmethod
    def _required_slots_for_tool(cls, tool_name: str) -> list[str]:
        return get_tool_contract_registry().get_required_slots(tool_name)

    def _current_turn_index(self, *, pre_call: bool = False) -> int:
        turn_counter = int(getattr(getattr(self.inner_router, "memory", None), "turn_counter", 0) or 0)
        return turn_counter + 1 if pre_call else turn_counter

    @staticmethod
    def _write_stance(ao: Any, resolution: StanceResolution, turn: int) -> None:
        ao.stance = resolution.stance
        ao.stance_confidence = resolution.confidence
        ao.stance_resolved_by = resolution.resolved_by
        if not ao.stance_history or ao.stance_history[-1][1] != resolution.stance:
            ao.stance_history.append((turn, resolution.stance))
