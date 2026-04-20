from __future__ import annotations

from typing import Any

from core.analytical_objective import ConversationalStance, StanceConfidence
from core.contracts.base import BaseContract, ContractContext, ContractInterception
from core.stance_resolver import StanceResolution, StanceResolver


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
        self._write_stance(current_ao, resolution, turn)
        context.metadata["stance"] = {
            "reversal_detected": reversal_detected,
            "stance": resolution.stance.value,
            "confidence": resolution.confidence.value,
            "resolved_by": resolution.resolved_by,
            "evidence": list(resolution.evidence),
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
