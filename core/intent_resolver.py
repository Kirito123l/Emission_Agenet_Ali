from __future__ import annotations

from typing import Any, Dict, List, Optional

from config import get_config
from core.analytical_objective import (
    AORelationship,
    IntentConfidence,
    ToolIntent,
)
from core.execution_continuation import PendingObjective
from core.execution_continuation_utils import load_execution_continuation


class IntentResolver:
    """Resolve the AO tool intent without owning any LLM calls."""

    def __init__(self, inner_router: Any, tool_registry: Any = None):
        self.inner_router = inner_router
        self.tool_registry = tool_registry
        self.runtime_config = get_config()

    # ── Phase 8.1.4b Sub-step 1: downstream chain builder ─────────────────

    @staticmethod
    def _downstream_chain(resolved_tool: str, hints: Dict[str, Any]) -> List[str]:
        """Build multi-step chain from *resolved_tool* using tool_graph.

        Consults TOOL_GRAPH to find tools whose *requires* match what
        *resolved_tool* provides, extending the chain when user-intent hints
        (wants_dispersion, wants_hotspot, wants_map) indicate downstream needs.

        Returns at minimum ``[resolved_tool]`` — never returns an empty chain
        when *resolved_tool* is non-empty.
        """
        from core.tool_dependencies import TOOL_GRAPH, normalize_tokens

        chain = [resolved_tool]
        provides = normalize_tokens(TOOL_GRAPH.get(resolved_tool, {}).get("provides", []))
        if not provides:
            return chain

        # First-level downstream: tools that consume what resolved_tool provides
        downstream_candidates: List[str] = []
        for tool_name, info in TOOL_GRAPH.items():
            if tool_name == resolved_tool:
                continue
            tool_requires = normalize_tokens(info.get("requires", []))
            if any(r in provides for r in tool_requires):
                downstream_candidates.append(tool_name)

        # Append based on user-intent hints (subset of router.py:1694-1699)
        appended: set = set()
        for candidate in downstream_candidates:
            if candidate == "calculate_dispersion" and hints.get("wants_dispersion"):
                chain.append(candidate)
                appended.add(candidate)

        # Second-level: after dispersion, check for hotspot
        if "calculate_dispersion" in appended:
            disp_provides = normalize_tokens(
                TOOL_GRAPH.get("calculate_dispersion", {}).get("provides", [])
            )
            for tool_name, info in TOOL_GRAPH.items():
                tool_requires = normalize_tokens(info.get("requires", []))
                if any(r in disp_provides for r in tool_requires):
                    if tool_name == "analyze_hotspots" and hints.get("wants_hotspot"):
                        chain.append(tool_name)

        # render_spatial_map is a leaf consumer — append when wanted
        if hints.get("wants_map") and "render_spatial_map" not in chain:
            chain.append("render_spatial_map")

        return chain

    # ── End Phase 8.1.4b Sub-step 1 ──────────────────────────────────────

    # ── Phase 8.1.4b Sub-step 2: chain-cursor advancement ────────────────

    @staticmethod
    def _advance_chain_cursor(chain: List[str], ao: Any) -> tuple:
        """Return (resolved_tool, chain) advancing past already-completed tools.

        Checks the current AO's tool_call_log to determine whether earlier
        chain steps have already been executed (either by this AO or recorded
        via continuation state).  Advances *resolved_tool* to the first
        non-completed tool in *chain*.

        Returns ``(chain[0], chain)`` when no advancement is needed.
        """
        if not chain:
            return (None, chain)
        completed: set = set()
        for record in list(getattr(ao, "tool_call_log", []) or []):
            tool = str(getattr(record, "tool", "") or "").strip()
            if tool and getattr(record, "success", False):
                completed.add(tool)
        # Also check continuation: if pending_next_tool points further in
        # the chain, treat earlier steps as completed.
        continuation = load_execution_continuation(ao)
        cont_next = str(getattr(continuation, "pending_next_tool", "") or "").strip()
        if cont_next and cont_next in chain:
            cont_idx = chain.index(cont_next)
            for t in chain[:cont_idx]:
                completed.add(t)

        cursor = 0
        for i, tool in enumerate(chain):
            if tool in completed:
                cursor = i + 1
            else:
                break
        if cursor >= len(chain):
            return (chain[-1], chain)
        return (chain[cursor], chain)

    # ── End Phase 8.1.4b Sub-step 2 ───────────────────────────────────────

    def resolve_fast(self, state: Any, ao: Any) -> ToolIntent:
        """Rules-only fast path. Returns HIGH when a legacy resolver rule hits."""
        hints = self._extract_hints(state)
        desired_chain = [str(item) for item in hints.get("desired_tool_chain") or [] if item]
        if desired_chain:
            resolved_tool, chain = self._advance_chain_cursor(desired_chain, ao)
            evidence = [f"desired_chain:{';'.join(desired_chain)}"]
            if resolved_tool != desired_chain[0]:
                evidence.append(f"chain:advanced_from:{desired_chain[0]}")
            return self._intent(
                resolved_tool,
                IntentConfidence.HIGH,
                resolved_by="rule:desired_chain",
                evidence=evidence,
                state=state,
                projected_chain=chain,
            )

        pending_tool = self._pending_tool_name(ao)
        if pending_tool:
            projected_chain = self._projected_chain_from_ao(ao) or [pending_tool]
            return self._intent(
                pending_tool,
                IntentConfidence.HIGH,
                resolved_by="rule:pending",
                evidence=["pending_tool_name"],
                state=state,
                projected_chain=projected_chain,
            )

        task_type = str(getattr(getattr(state, "file_context", None), "task_type", "") or "").strip()
        if task_type == "macro_emission":
            chain = self._downstream_chain("calculate_macro_emission", hints)
            resolved_tool, chain = self._advance_chain_cursor(chain, ao)
            evidence = ["file_task_type:macro_emission"]
            if resolved_tool != "calculate_macro_emission":
                evidence.append(f"chain:advanced_to:{resolved_tool}")
            elif len(chain) > 1:
                evidence.append("chain:downstream")
            return self._intent(
                resolved_tool,
                IntentConfidence.HIGH,
                resolved_by="rule:file_task_type",
                evidence=evidence,
                state=state,
                projected_chain=chain,
            )
        if task_type == "micro_emission":
            chain = self._downstream_chain("calculate_micro_emission", hints)
            resolved_tool, chain = self._advance_chain_cursor(chain, ao)
            evidence = ["file_task_type:micro_emission"]
            if resolved_tool != "calculate_micro_emission":
                evidence.append(f"chain:advanced_to:{resolved_tool}")
            elif len(chain) > 1:
                evidence.append("chain:downstream")
            return self._intent(
                resolved_tool,
                IntentConfidence.HIGH,
                resolved_by="rule:file_task_type",
                evidence=evidence,
                state=state,
                projected_chain=chain,
            )

        if hints.get("wants_factor"):
            chain = self._downstream_chain("query_emission_factors", hints)
            resolved_tool, chain = self._advance_chain_cursor(chain, ao)
            evidence = ["wants_factor:true"]
            if resolved_tool != "query_emission_factors":
                evidence.append(f"chain:advanced_to:{resolved_tool}")
            elif len(chain) > 1:
                evidence.append("chain:downstream")
            return self._intent(
                resolved_tool,
                IntentConfidence.HIGH,
                resolved_by="rule:wants_factor_strict",
                evidence=evidence,
                state=state,
                projected_chain=chain,
            )

        parent_tool = self._revision_parent_tool(ao)
        if parent_tool:
            return self._intent(
                parent_tool,
                IntentConfidence.HIGH,
                resolved_by="rule:revision_parent",
                evidence=[f"revision_parent_tool:{parent_tool}"],
                state=state,
                projected_chain=[parent_tool],
            )

        return self._intent(
            None,
            IntentConfidence.NONE,
            resolved_by=None,
            evidence=[],
            state=state,
            projected_chain=[],
        )

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
                parsed_chain = list(parsed_hint.get("projected_chain") or [])
                if (
                    parsed_chain
                    and fast.resolved_tool == parsed_chain[0]
                    and (
                        not fast.projected_chain
                        or len(parsed_chain) > len(fast.projected_chain)
                    )
                ):
                    fast.projected_chain = parsed_chain
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
            projected_chain=list(parsed_hint.get("projected_chain") or []),
        )

    def _extract_hints(self, state: Any) -> Dict[str, Any]:
        extractor = getattr(self.inner_router, "_extract_message_execution_hints", None)
        if extractor is None:
            return {}
        hints = extractor(state)
        return dict(hints) if isinstance(hints, dict) else {}

    @staticmethod
    def _pending_tool_name(ao: Any) -> Optional[str]:
        continuation = load_execution_continuation(ao)
        if continuation.pending_objective == PendingObjective.PARAMETER_COLLECTION:
            tool_intent = getattr(ao, "tool_intent", None)
            resolved_tool = str(getattr(tool_intent, "resolved_tool", "") or "").strip()
            if resolved_tool:
                return resolved_tool
            metadata = getattr(ao, "metadata", None)
            if isinstance(metadata, dict):
                readiness_state = metadata.get("execution_readiness")
                if isinstance(readiness_state, dict):
                    pending_tool = str(readiness_state.get("tool_name") or "").strip()
                    if pending_tool:
                        return pending_tool
        if continuation.pending_next_tool:
            return str(continuation.pending_next_tool).strip() or None
        metadata = getattr(ao, "metadata", None)
        if not isinstance(metadata, dict):
            return None
        contract_state = metadata.get("clarification_contract")
        if not isinstance(contract_state, dict):
            return None
        pending_tool = str(contract_state.get("tool_name") or "").strip()
        return pending_tool or None

    @staticmethod
    def _projected_chain_from_ao(ao: Any) -> List[str]:
        continuation = load_execution_continuation(ao)
        if continuation.pending_tool_queue:
            return [str(item) for item in continuation.pending_tool_queue if str(item).strip()]
        tool_intent = getattr(ao, "tool_intent", None)
        return [
            str(item)
            for item in list(getattr(tool_intent, "projected_chain", []) or [])
            if str(item).strip()
        ]

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
            "projected_chain": [
                str(item)
                for item in list(
                    llm_hint.get("projected_chain")
                    or llm_hint.get("chain")
                    or []
                )
                if str(item).strip()
            ],
        }

    @staticmethod
    def _intent(
        resolved_tool: Optional[str],
        confidence: IntentConfidence,
        *,
        resolved_by: Optional[str],
        evidence: list[str],
        state: Any,
        projected_chain: Optional[List[str]] = None,
    ) -> ToolIntent:
        return ToolIntent(
            resolved_tool=resolved_tool,
            confidence=confidence,
            evidence=list(evidence),
            resolved_at_turn=int(getattr(state, "turn_index", 0) or 0) or None,
            resolved_by=resolved_by,
            projected_chain=[
                str(item) for item in list(projected_chain or []) if str(item).strip()
            ],
        )
