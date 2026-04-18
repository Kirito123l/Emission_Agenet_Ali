from __future__ import annotations

from typing import Any, Dict, Optional

from config import get_config
from core.analytical_objective import (
    AORelationship,
    IntentConfidence,
    ToolIntent,
)


class IntentResolver:
    """Resolve the AO tool intent without owning any LLM calls."""

    def __init__(self, inner_router: Any, tool_registry: Any = None):
        self.inner_router = inner_router
        self.tool_registry = tool_registry
        self.runtime_config = get_config()

    def resolve_fast(self, state: Any, ao: Any) -> ToolIntent:
        """Rules-only fast path. Returns HIGH when a legacy resolver rule hits."""
        pending_tool = self._pending_tool_name(ao)
        if pending_tool:
            return self._intent(
                pending_tool,
                IntentConfidence.HIGH,
                resolved_by="rule:pending",
                evidence=["pending_tool_name"],
                state=state,
            )

        hints = self._extract_hints(state)
        desired_chain = [str(item) for item in hints.get("desired_tool_chain") or [] if item]
        if desired_chain:
            return self._intent(
                desired_chain[0],
                IntentConfidence.HIGH,
                resolved_by="rule:desired_chain",
                evidence=[f"desired_chain:{';'.join(desired_chain)}"],
                state=state,
            )

        task_type = str(getattr(getattr(state, "file_context", None), "task_type", "") or "").strip()
        if task_type == "macro_emission":
            return self._intent(
                "calculate_macro_emission",
                IntentConfidence.HIGH,
                resolved_by="rule:file_task_type",
                evidence=["file_task_type:macro_emission"],
                state=state,
            )
        if task_type == "micro_emission":
            return self._intent(
                "calculate_micro_emission",
                IntentConfidence.HIGH,
                resolved_by="rule:file_task_type",
                evidence=["file_task_type:micro_emission"],
                state=state,
            )

        if hints.get("wants_factor"):
            return self._intent(
                "query_emission_factors",
                IntentConfidence.HIGH,
                resolved_by="rule:wants_factor_strict",
                evidence=["wants_factor:true"],
                state=state,
            )

        parent_tool = self._revision_parent_tool(ao)
        if parent_tool:
            return self._intent(
                parent_tool,
                IntentConfidence.HIGH,
                resolved_by="rule:revision_parent",
                evidence=[f"revision_parent_tool:{parent_tool}"],
                state=state,
            )

        return self._intent(None, IntentConfidence.NONE, resolved_by=None, evidence=[], state=state)

    def resolve_with_llm_hint(self, state: Any, ao: Any, llm_hint: Optional[Dict[str, Any]]) -> ToolIntent:
        """Merge fast rules with an intent hint produced by the slot filler."""
        fast = self.resolve_fast(state, ao)
        parsed_hint = self._parse_llm_hint(llm_hint)
        if fast.confidence == IntentConfidence.HIGH:
            if parsed_hint:
                fast.evidence.append(
                    "llm_hint:"
                    + str(parsed_hint.get("resolved_tool") or "none")
                    + ":"
                    + str(parsed_hint.get("intent_confidence") or "none")
                )
            return fast

        if not getattr(self.runtime_config, "enable_llm_intent_resolution", True):
            return fast

        if not parsed_hint:
            return fast

        confidence = parsed_hint["confidence"]
        resolved_tool = parsed_hint.get("resolved_tool")
        reasoning = str(parsed_hint.get("reasoning") or "").strip()
        evidence = ["llm_slot_filler"]
        if reasoning:
            evidence.append(f"reasoning:{reasoning}")
        return self._intent(
            resolved_tool if confidence != IntentConfidence.NONE else None,
            confidence,
            resolved_by="llm_slot_filler" if confidence != IntentConfidence.NONE else None,
            evidence=evidence,
            state=state,
        )

    def _extract_hints(self, state: Any) -> Dict[str, Any]:
        extractor = getattr(self.inner_router, "_extract_message_execution_hints", None)
        if extractor is None:
            return {}
        hints = extractor(state)
        return dict(hints) if isinstance(hints, dict) else {}

    @staticmethod
    def _pending_tool_name(ao: Any) -> Optional[str]:
        tool_intent = getattr(ao, "tool_intent", None)
        resolved_tool = str(getattr(tool_intent, "resolved_tool", "") or "").strip()
        confidence = getattr(tool_intent, "confidence", IntentConfidence.NONE)
        if resolved_tool and confidence == IntentConfidence.HIGH:
            return resolved_tool
        metadata = getattr(ao, "metadata", None)
        if not isinstance(metadata, dict):
            return None
        contract_state = metadata.get("clarification_contract")
        if not isinstance(contract_state, dict):
            return None
        pending_tool = str(contract_state.get("tool_name") or "").strip()
        return pending_tool or None

    def _revision_parent_tool(self, ao: Any) -> Optional[str]:
        if ao is None or getattr(ao, "relationship", None) != AORelationship.REVISION:
            return None
        parent_ao_id = str(getattr(ao, "parent_ao_id", "") or "").strip()
        if not parent_ao_id:
            return None
        parent = self._get_ao_by_id(parent_ao_id)
        if parent is None:
            return None
        for record in reversed(list(getattr(parent, "tool_call_log", []) or [])):
            if getattr(record, "success", False):
                tool = str(getattr(record, "tool", "") or "").strip()
                if tool:
                    return tool
        return None

    def _get_ao_by_id(self, ao_id: str) -> Any:
        getter = getattr(self.tool_registry, "get_ao_by_id", None)
        if getter is not None:
            return getter(ao_id)
        memory = getattr(getattr(self.inner_router, "memory", None), "fact_memory", None)
        for ao in list(getattr(memory, "ao_history", []) or []):
            if getattr(ao, "ao_id", None) == ao_id:
                return ao
        return None

    @staticmethod
    def _parse_llm_hint(llm_hint: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(llm_hint, dict):
            return None
        confidence_raw = str(
            llm_hint.get("intent_confidence")
            or llm_hint.get("confidence")
            or "none"
        ).strip().lower()
        try:
            confidence = IntentConfidence(confidence_raw)
        except ValueError:
            confidence = IntentConfidence.NONE
        resolved_tool = (
            str(llm_hint.get("resolved_tool")).strip()
            if llm_hint.get("resolved_tool") is not None
            else None
        )
        if confidence == IntentConfidence.NONE and not resolved_tool:
            return None
        return {
            "resolved_tool": resolved_tool,
            "confidence": confidence,
            "intent_confidence": confidence.value,
            "reasoning": llm_hint.get("reasoning"),
        }

    @staticmethod
    def _intent(
        resolved_tool: Optional[str],
        confidence: IntentConfidence,
        *,
        resolved_by: Optional[str],
        evidence: list[str],
        state: Any,
    ) -> ToolIntent:
        return ToolIntent(
            resolved_tool=resolved_tool,
            confidence=confidence,
            evidence=list(evidence),
            resolved_at_turn=int(getattr(state, "turn_index", 0) or 0) or None,
            resolved_by=resolved_by,
        )
