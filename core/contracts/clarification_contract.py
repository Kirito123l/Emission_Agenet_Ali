from __future__ import annotations

import asyncio
import copy
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import yaml

from config import get_config
from core.analytical_objective import IntentConfidence
from core.ao_classifier import AOClassType
from core.contracts.base import BaseContract, ContractContext, ContractInterception
from core.intent_resolver import IntentResolver
from core.router import RouterResponse
from core.contracts.runtime_defaults import _RUNTIME_DEFAULTS as RUNTIME_DEFAULTS
from core.stance_resolver import StanceResolution, StanceResolver
from core.tool_dependencies import _build_tool_graph_for_prompt
from services.llm_client import get_llm_client
from services.standardization_engine import StandardizationEngine
from tools.file_analyzer import FileAnalyzerTool
from tools.contract_loader import get_tool_contract_registry

logger = logging.getLogger(__name__)

YEAR_RANGE_MIN = 1995
YEAR_RANGE_MAX = 2025
_SENTINEL_VALUES = {"missing", "unknown", "none", "n/a", "null", ""}
_DECISION_EXAMPLES: Optional[list] = None


def _load_decision_examples() -> list:
    global _DECISION_EXAMPLES
    if _DECISION_EXAMPLES is not None:
        return _DECISION_EXAMPLES
    import os as _os
    path = _os.path.join(_os.path.dirname(__file__), "..", "..", "config", "decision_few_shot_examples.yaml")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        _DECISION_EXAMPLES = list(data.get("examples") or []) if isinstance(data, dict) else []
    except Exception:
        _DECISION_EXAMPLES = []
    return _DECISION_EXAMPLES


@dataclass
class ClarificationTelemetry:
    turn: int
    triggered: bool
    trigger_mode: str
    classification_at_trigger: Optional[str]
    stage1_filled_slots: List[str]
    stage2_called: bool
    stage2_latency_ms: Optional[float]
    stage2_missing_required: List[str]
    stage2_clarification_question: Optional[str]
    stage3_rejected_slots: List[str]
    stage3_normalizations: List[Dict[str, Any]]
    final_decision: str
    confirm_first_detected: bool
    confirm_first_trigger: Optional[str]
    collection_mode: bool
    pcm_trigger_reason: Optional[str]
    probe_optional_slot: Optional[str]
    probe_turn_count: int
    probe_abandoned: bool
    proceed_mode: Optional[str]
    ao_id: Optional[str]
    tool_name: Optional[str]
    llm_intent_raw: Optional[Dict[str, Any]]
    llm_intent_parse_success: bool
    tool_intent_confidence: Optional[str]
    tool_intent_resolved_by: Optional[str]
    stance_value: Optional[str]
    stance_confidence: Optional[str]
    stance_resolved_by: Optional[str]
    stance_evidence: List[str]
    stance_reversal_detected: bool
    stance_llm_hint_raw: Optional[Dict[str, Any]]
    stance_llm_hint_parse_success: bool
    stage2_decision: Optional[Dict[str, Any]] = None
    pcm_advisory: Optional[Dict[str, Any]] = None
    pcm_advisory_delta: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn": self.turn,
            "triggered": self.triggered,
            "trigger_mode": self.trigger_mode,
            "classification_at_trigger": self.classification_at_trigger,
            "stage1_filled_slots": list(self.stage1_filled_slots),
            "stage2_called": self.stage2_called,
            "stage2_latency_ms": self.stage2_latency_ms,
            "stage2_missing_required": list(self.stage2_missing_required),
            "stage2_clarification_question": self.stage2_clarification_question,
            "stage3_rejected_slots": list(self.stage3_rejected_slots),
            "stage3_normalizations": [dict(item) for item in self.stage3_normalizations],
            "final_decision": self.final_decision,
            "confirm_first_detected": self.confirm_first_detected,
            "confirm_first_trigger": self.confirm_first_trigger,
            "collection_mode": self.collection_mode,
            "pcm_trigger_reason": self.pcm_trigger_reason,
            "probe_optional_slot": self.probe_optional_slot,
            "probe_turn_count": self.probe_turn_count,
            "probe_abandoned": self.probe_abandoned,
            "proceed_mode": self.proceed_mode,
            "ao_id": self.ao_id,
            "tool_name": self.tool_name,
            "llm_intent_raw": dict(self.llm_intent_raw) if isinstance(self.llm_intent_raw, dict) else None,
            "llm_intent_parse_success": self.llm_intent_parse_success,
            "tool_intent_confidence": self.tool_intent_confidence,
            "tool_intent_resolved_by": self.tool_intent_resolved_by,
            "stance_value": self.stance_value,
            "stance_confidence": self.stance_confidence,
            "stance_resolved_by": self.stance_resolved_by,
            "stance_evidence": list(self.stance_evidence),
            "stance_reversal_detected": self.stance_reversal_detected,
            "stance_llm_hint_raw": (
                dict(self.stance_llm_hint_raw)
                if isinstance(self.stance_llm_hint_raw, dict)
                else None
            ),
            "stance_llm_hint_parse_success": self.stance_llm_hint_parse_success,
            "stage2_decision": dict(self.stage2_decision) if isinstance(self.stage2_decision, dict) else None,
            "pcm_advisory": dict(self.pcm_advisory) if isinstance(self.pcm_advisory, dict) else None,
            "pcm_advisory_delta": list(self.pcm_advisory_delta) if self.pcm_advisory_delta else None,
        }


class ClarificationContract(BaseContract):
    name = "clarification"
    _tools_cache: Optional[Dict[str, Any]] = None

    def __init__(
        self,
        inner_router: Any = None,
        ao_manager: Any = None,
        runtime_config: Optional[Any] = None,
    ):
        self.inner_router = inner_router
        self.ao_manager = ao_manager
        self.runtime_config = runtime_config or get_config()
        self.file_analyzer = FileAnalyzerTool()
        self.stage3_engine = StandardizationEngine(
            config={
                "llm_enabled": False,
                "parameter_negotiation_enabled": False,
                "enable_cross_constraint_validation": False,
                "fuzzy_enabled": True,
            }
        )
        self.llm_client = None
        if getattr(self.runtime_config, "enable_clarification_stage2_llm", True):
            self.llm_client = get_llm_client(
                "agent",
                model=getattr(self.runtime_config, "clarification_llm_model", None),
            )
        self.intent_resolver = IntentResolver(inner_router, ao_manager)
        self.stance_resolver = StanceResolver(runtime_config=self.runtime_config)

    async def before_turn(self, context: ContractContext) -> ContractInterception:
        if not getattr(self.runtime_config, "enable_clarification_contract", True):
            return ContractInterception()
        if self.inner_router is None or self.ao_manager is None:
            return ContractInterception()

        oasc_state = dict(context.metadata.get("oasc") or {})
        classification = oasc_state.get("classification")
        current_ao = self.ao_manager.get_current_ao()
        pending_state = self._get_pending_state(current_ao)

        is_resume = bool(pending_state and pending_state.get("pending"))
        is_fresh = bool(
            classification is not None
            and classification.classification in {AOClassType.NEW_AO, AOClassType.REVISION}
        )
        if not is_resume and not is_fresh:
            return ContractInterception()

        state = context.state_snapshot
        if state is None:
            return ContractInterception()
        await self._ensure_file_context(state, context.file_path)

        confirm_first_trigger = self._detect_confirm_first(context.effective_user_message) if is_fresh else None
        confirm_first_detected = bool(confirm_first_trigger)

        tool_intent = self.intent_resolver.resolve_fast(state, current_ao)
        stance_fast = self.stance_resolver.resolve_fast(context.effective_user_message, current_ao)
        tool_name = tool_intent.resolved_tool
        telemetry = ClarificationTelemetry(
            turn=self._current_turn_index(),
            triggered=True,
            trigger_mode="resume_pending" if is_resume else "fresh",
            classification_at_trigger=classification.classification.name if classification is not None else None,
            stage1_filled_slots=[],
            stage2_called=False,
            stage2_latency_ms=None,
            stage2_missing_required=[],
            stage2_clarification_question=None,
            stage3_rejected_slots=[],
            stage3_normalizations=[],
            final_decision="proceed",
            confirm_first_detected=confirm_first_detected,
            confirm_first_trigger=confirm_first_trigger,
            collection_mode=False,
            pcm_trigger_reason=None,
            probe_optional_slot=None,
            probe_turn_count=0,
            probe_abandoned=False,
            proceed_mode=None,
            ao_id=current_ao.ao_id if current_ao is not None else None,
            tool_name=tool_name,
            llm_intent_raw=None,
            llm_intent_parse_success=False,
            tool_intent_confidence=tool_intent.confidence.value,
            tool_intent_resolved_by=tool_intent.resolved_by,
            stance_value=getattr(getattr(current_ao, "stance", None), "value", None),
            stance_confidence=getattr(getattr(current_ao, "stance_confidence", None), "value", None),
            stance_resolved_by=getattr(current_ao, "stance_resolved_by", None),
            stance_evidence=[],
            stance_reversal_detected=bool(
                context.metadata.get("stance", {}).get("reversal_detected")
                if isinstance(context.metadata.get("stance"), dict)
                else False
            ),
            stance_llm_hint_raw=None,
            stance_llm_hint_parse_success=False,
        )

        prefetched_stage2_payload: Optional[Dict[str, Any]] = None
        llm_question = None
        if not tool_name:
            if not self._stage2_available():
                return ContractInterception()
            telemetry.stage2_called = True
            try:
                started = time.perf_counter()
                prefetched_stage2_payload = await self._run_stage2_llm(
                    user_message=context.effective_user_message,
                    state=state,
                    current_ao=current_ao,
                    tool_name=None,
                    snapshot={},
                    tool_spec=self._generic_tool_spec(),
                    classification=classification,
                )
                telemetry.stage2_latency_ms = round((time.perf_counter() - started) * 1000, 2)
                telemetry.stage2_missing_required = list(prefetched_stage2_payload.get("missing_required") or [])
                llm_question = str(prefetched_stage2_payload.get("clarification_question") or "").strip() or None
                telemetry.stage2_clarification_question = llm_question
                if isinstance(prefetched_stage2_payload.get("decision"), dict):
                    telemetry.stage2_decision = dict(prefetched_stage2_payload["decision"])
                llm_hint, llm_raw, parse_success = self._extract_llm_intent_hint(prefetched_stage2_payload)
                telemetry.llm_intent_raw = llm_raw
                telemetry.llm_intent_parse_success = parse_success
                stance_hint, stance_raw, stance_parse_success = self._extract_llm_stance_hint(prefetched_stage2_payload)
                telemetry.stance_llm_hint_raw = stance_raw
                telemetry.stance_llm_hint_parse_success = stance_parse_success
                stance_resolution = self.stance_resolver.resolve_with_llm_hint(stance_fast, stance_hint)
                self._persist_stance(current_ao, stance_resolution)
                self._apply_stance_telemetry(telemetry, stance_resolution)
                tool_intent = self.intent_resolver.resolve_with_llm_hint(state, current_ao, llm_hint)
                self._persist_tool_intent(current_ao, tool_intent)
                tool_name = tool_intent.resolved_tool
                telemetry.tool_name = tool_name
                telemetry.tool_intent_confidence = tool_intent.confidence.value
                telemetry.tool_intent_resolved_by = tool_intent.resolved_by
            except Exception as exc:
                logger.warning("ClarificationContract Stage 2 intent resolution failed: %s", exc)
                return ContractInterception()

        self._persist_tool_intent(current_ao, tool_intent)
        tool_spec = self._get_tool_spec(tool_name)
        if not tool_spec or (
            not tool_spec.get("required_slots")
            and not (is_resume and tool_spec.get("clarification_followup_slots"))
        ):
            return ContractInterception()

        active_required_slots = list(tool_spec.get("required_slots") or [])
        pending_decision = str(pending_state.get("pending_decision") or "").strip()
        if is_resume and pending_state.get("pending") and pending_decision == "clarify_required":
            active_required_slots.extend(
                slot_name
                for slot_name in list(pending_state.get("missing_slots") or [])
                if slot_name
            )
        active_required_slots = list(dict.fromkeys(active_required_slots))

        snapshot = self._initial_snapshot(
            tool_name=tool_name,
            current_ao=current_ao,
            pending_state=pending_state,
            classification=classification,
        )
        telemetry.stage1_filled_slots = self._run_stage1(state, snapshot)

        missing_required_stage1 = self._missing_slots(snapshot, active_required_slots)

        # Phase 4: pre-compute PCM advisory for flag=true injection into Stage 2 payload
        flag_on = getattr(get_config(), "enable_llm_decision_field", False)
        pcm_advisory = None
        if flag_on and prefetched_stage2_payload is None:
            prelim_unfilled = self._get_unfilled_optionals_without_default(snapshot, tool_spec)
            prelim_collection_mode, prelim_trigger = self._resolve_collection_mode(
                ao=current_ao,
                missing_required=missing_required_stage1,
                confirm_first_detected=confirm_first_detected,
                unfilled_optionals_without_default=prelim_unfilled,
                is_resume=is_resume,
            )
            if prelim_collection_mode:
                runtime_defaults_available: Dict[str, Any] = {}
                rt = dict(RUNTIME_DEFAULTS.get(tool_name or "", {}))
                for slot_name in prelim_unfilled:
                    if slot_name in rt:
                        runtime_defaults_available[slot_name] = rt[slot_name]
                pcm_advisory = {
                    "unfilled_optionals_without_default": prelim_unfilled,
                    "runtime_defaults_available": runtime_defaults_available,
                    "confirm_first_detected": confirm_first_detected,
                    "suggested_probe_slot": prelim_unfilled[0] if prelim_unfilled else None,
                    "collection_mode_active": True,
                }
                telemetry.pcm_advisory = pcm_advisory

        if prefetched_stage2_payload is not None:
            snapshot = self._merge_stage2_snapshot(
                snapshot,
                self._stage2_snapshot_payload(prefetched_stage2_payload),
        )
        if (
            prefetched_stage2_payload is None
            and (missing_required_stage1 or (flag_on and pcm_advisory is not None))
            and self._stage2_available()
        ):
            telemetry.stage2_called = True
            try:
                started = time.perf_counter()
                llm_payload = await self._run_stage2_llm(
                    user_message=context.effective_user_message,
                    state=state,
                    current_ao=current_ao,
                    tool_name=tool_name,
                    snapshot=snapshot,
                    tool_spec=tool_spec,
                    classification=classification,
                    pcm_advisory=pcm_advisory,
                )
                telemetry.stage2_latency_ms = round((time.perf_counter() - started) * 1000, 2)
                telemetry.stage2_missing_required = list(llm_payload.get("missing_required") or [])
                llm_question = str(llm_payload.get("clarification_question") or "").strip() or None
                telemetry.stage2_clarification_question = llm_question
                if isinstance(llm_payload.get("decision"), dict):
                    telemetry.stage2_decision = dict(llm_payload["decision"])
                llm_hint, llm_raw, parse_success = self._extract_llm_intent_hint(llm_payload)
                telemetry.llm_intent_raw = llm_raw
                telemetry.llm_intent_parse_success = parse_success
                stance_hint, stance_raw, stance_parse_success = self._extract_llm_stance_hint(llm_payload)
                telemetry.stance_llm_hint_raw = stance_raw
                telemetry.stance_llm_hint_parse_success = stance_parse_success
                stance_resolution = self.stance_resolver.resolve_with_llm_hint(stance_fast, stance_hint)
                self._persist_stance(current_ao, stance_resolution)
                self._apply_stance_telemetry(telemetry, stance_resolution)
                tool_intent = self.intent_resolver.resolve_with_llm_hint(state, current_ao, llm_hint)
                self._persist_tool_intent(current_ao, tool_intent)
                telemetry.tool_intent_confidence = tool_intent.confidence.value
                telemetry.tool_intent_resolved_by = tool_intent.resolved_by
                snapshot = self._merge_stage2_snapshot(snapshot, self._stage2_snapshot_payload(llm_payload))
                if tool_intent.resolved_tool and tool_intent.resolved_tool != tool_name:
                    tool_name = str(tool_intent.resolved_tool)
                    telemetry.tool_name = tool_name
                    tool_spec = self._get_tool_spec(tool_name) or tool_spec
            except Exception as exc:
                logger.warning("ClarificationContract Stage 2 failed: %s", exc)

        snapshot, normalizations, rejected_slots = self._run_stage3(
            tool_name=tool_name,
            snapshot=snapshot,
            tool_spec=tool_spec,
            suppress_defaults_for=active_required_slots if (confirm_first_detected or is_resume) else [],
        )
        telemetry.stage3_normalizations = normalizations
        telemetry.stage3_rejected_slots = list(rejected_slots)

        missing_required = self._missing_slots(snapshot, active_required_slots)
        unfilled_optionals_without_default = self._get_unfilled_optionals_without_default(
            snapshot,
            tool_spec,
        )
        collection_mode, pcm_trigger_reason = self._resolve_collection_mode(
            ao=current_ao,
            missing_required=missing_required,
            confirm_first_detected=confirm_first_detected,
            unfilled_optionals_without_default=unfilled_optionals_without_default,
            is_resume=is_resume,
        )
        telemetry.collection_mode = collection_mode
        telemetry.pcm_trigger_reason = pcm_trigger_reason
        probe_optional_slot = None
        pending_decision: Optional[str] = None
        should_proceed = False
        question = None
        pending_slots: List[str] = []

        if missing_required or rejected_slots:
            pending_decision = "clarify_required"
            pending_slots = list(dict.fromkeys([*missing_required, *rejected_slots]))
            question = self._build_question(
                tool_name=tool_name,
                snapshot=snapshot,
                missing_slots=missing_required,
                rejected_slots=rejected_slots,
                llm_question=llm_question,
            )
        elif not collection_mode:
            should_proceed = True
        elif flag_on:
            # Phase 4 advisory mode: don't hard-block; advisory was already stored pre-Stage-2
            if unfilled_optionals_without_default:
                probe_optional_slot = unfilled_optionals_without_default[0]
                telemetry.probe_optional_slot = probe_optional_slot
                # Reconcile: if post-Stage-3 differs from pre-Stage-2, record delta
                pre_stage2 = telemetry.pcm_advisory or {}
                pre_unfilled = set(pre_stage2.get("unfilled_optionals_without_default") or [])
                post_unfilled = set(unfilled_optionals_without_default)
                if pre_unfilled != post_unfilled:
                    telemetry.pcm_advisory_delta = sorted(post_unfilled - pre_unfilled)
            should_proceed = True
        else:
            if unfilled_optionals_without_default:
                probe_optional_slot = unfilled_optionals_without_default[0]
                telemetry.probe_optional_slot = probe_optional_slot
                probe_turn_count = self._next_probe_turn_count(pending_state, probe_optional_slot)
                telemetry.probe_turn_count = probe_turn_count
                if probe_turn_count >= 2:
                    telemetry.probe_abandoned = True
                    should_proceed = True
                else:
                    pending_decision = "probe_optional"
                    pending_slots = [probe_optional_slot]
                    question = await self._build_probe_question(
                        tool_name=tool_name,
                        snapshot=snapshot,
                        slot_name=probe_optional_slot,
                        current_ao=current_ao,
                    )
            else:
                should_proceed = True

        self._persist_snapshot_state(
            ao=current_ao,
            tool_name=tool_name,
            snapshot=snapshot,
            clarification_question=question or "",
            pending=not should_proceed,
            missing_slots=pending_slots,
            rejected_slots=rejected_slots,
            followup_slots=list(tool_spec.get("clarification_followup_slots") or []),
            confirm_first_detected=confirm_first_detected,
            collection_mode=collection_mode,
            pcm_trigger_reason=pcm_trigger_reason,
            pending_decision=pending_decision,
            probe_optional_slot=probe_optional_slot,
            probe_turn_count=telemetry.probe_turn_count,
            probe_abandoned=telemetry.probe_abandoned,
        )

        if not should_proceed:
            # Q3 gate: when decision field is active, store hardcoded recommendation
            # but let GovernedRouter._consume_decision_field control routing.
            if self._decision_field_active(telemetry):
                telemetry.final_decision = "deferred_to_decision_field"
                self._persist_snapshot_state(
                    ao=current_ao,
                    tool_name=tool_name,
                    snapshot=snapshot,
                    clarification_question=question or "",
                    pending=not should_proceed,
                    missing_slots=pending_slots,
                    rejected_slots=rejected_slots,
                    followup_slots=list(tool_spec.get("clarification_followup_slots") or []),
                    confirm_first_detected=confirm_first_detected,
                    collection_mode=collection_mode,
                    pcm_trigger_reason=pcm_trigger_reason,
                    pending_decision=pending_decision,
                    probe_optional_slot=probe_optional_slot,
                    probe_turn_count=telemetry.probe_turn_count,
                    probe_abandoned=telemetry.probe_abandoned,
                )
                return ContractInterception(
                    metadata={
                        "clarification": {
                            "telemetry": telemetry.to_dict(),
                            "hardcoded_recommendation": "clarify",
                            "hardcoded_reason": question or "",
                            "hardcoded_pending_slots": pending_slots,
                        }
                    }
                )
            telemetry.final_decision = "clarify"
            structured_pending: List[Dict[str, Any]] = []
            for slot_name in pending_slots:
                entry: Dict[str, Any] = {
                    "slot": slot_name,
                    "label": self._slot_display_name(slot_name),
                    "tool": tool_name,
                    "examples": self._valid_values_list(slot_name),
                }
                if slot_name in rejected_slots:
                    slot_payload = snapshot.get(slot_name) or {}
                    raw = slot_payload.get("raw_text")
                    suggestions = slot_payload.get("suggestions") if isinstance(slot_payload.get("suggestions"), list) else []
                    entry["reason"] = f"无法识别 '{raw or slot_name}'"
                    entry["options"] = [str(s) for s in suggestions[:5]] if suggestions else ["请换一种更标准的说法"]
                else:
                    entry["reason"] = f"缺少必要参数 {self._slot_display_name(slot_name)}"
                structured_pending.append(entry)
            response = RouterResponse(
                text=question or "我还需要补充一个关键参数后才能继续，请直接告诉我缺失的参数值。",
                executed_tool_calls=[],
                trace=self._build_short_circuit_trace(
                    question=question or "我还需要补充一个关键参数后才能继续，请直接告诉我缺失的参数值。",
                    telemetry=telemetry.to_dict(),
                    tool_name=tool_name,
                    snapshot=snapshot,
                ),
                trace_friendly=[{"step_type": "clarification", "summary": question or ""}],
            )
            legal_map: Dict[str, list] = {}
            for slot_name in pending_slots:
                values = self._valid_values_list(slot_name)
                if values:
                    legal_map[slot_name] = values
            return ContractInterception(
                proceed=False,
                response=response,
                metadata={
                    "clarification": {"telemetry": telemetry.to_dict()},
                    "pending_clarifications": structured_pending,
                    "legal_values_for_pending_slots": legal_map,
                },
            )

        self._inject_snapshot_into_context(snapshot, current_ao)
        telemetry.final_decision = "proceed"
        telemetry.proceed_mode = "context_injection"
        return ContractInterception(
            metadata={
                "clarification": {
                    "telemetry": telemetry.to_dict(),
                    "direct_execution": {
                        "tool_name": tool_name,
                        "parameter_snapshot": copy.deepcopy(snapshot),
                        "confirm_first_detected": confirm_first_detected,
                        "trigger_mode": telemetry.trigger_mode,
                    },
                }
            }
        )

    async def after_turn(
        self,
        context: ContractContext,
        result: RouterResponse,
    ) -> None:
        clarification_state = dict(context.metadata.get("clarification") or {})
        telemetry = clarification_state.get("telemetry")
        if telemetry is None:
            return
        trace_obj = result.trace if isinstance(result.trace, dict) else None
        if trace_obj is None:
            trace_obj = {}
            result.trace = trace_obj
        existing = trace_obj.setdefault("clarification_telemetry", [])
        if not any(
            isinstance(item, dict)
            and item.get("turn") == telemetry.get("turn")
            and item.get("tool_name") == telemetry.get("tool_name")
            and item.get("final_decision") == telemetry.get("final_decision")
            for item in existing
        ):
            existing.append(dict(telemetry))
        trace_obj["clarification_contract"] = {
            "enabled": True,
            "final_decision": telemetry.get("final_decision"),
            "tool_name": telemetry.get("tool_name"),
        }
        if telemetry.get("final_decision") == "proceed":
            current_ao = self.ao_manager.get_current_ao() if self.ao_manager is not None else None
            if current_ao is not None and isinstance(current_ao.metadata, dict):
                contract_state = current_ao.metadata.get("clarification_contract")
                if isinstance(contract_state, dict):
                    contract_state["pending"] = False
                    current_ao.metadata["clarification_contract"] = contract_state

    def _get_pending_state(self, ao: Any) -> Dict[str, Any]:
        if ao is None or not isinstance(getattr(ao, "metadata", None), dict):
            return {}
        payload = ao.metadata.get("clarification_contract")
        pending_state = dict(payload) if isinstance(payload, dict) else {}
        if not self._first_class_state_enabled():
            return pending_state

        parameter_state = getattr(ao, "parameter_state", None)
        tool_intent = getattr(ao, "tool_intent", None)
        resolved_tool = str(getattr(tool_intent, "resolved_tool", "") or "").strip()
        if resolved_tool and not pending_state.get("tool_name"):
            pending_state["tool_name"] = resolved_tool

        awaiting_slot = str(getattr(parameter_state, "awaiting_slot", "") or "").strip()
        if awaiting_slot and "missing_slots" not in pending_state:
            pending_state["missing_slots"] = [awaiting_slot]
        if awaiting_slot and "probe_optional_slot" not in pending_state:
            pending_state["probe_optional_slot"] = awaiting_slot
        if awaiting_slot and "pending" not in pending_state:
            pending_state["pending"] = True
        if parameter_state is not None:
            pending_state.setdefault("probe_turn_count", int(getattr(parameter_state, "probe_turn_count", 0) or 0))
            pending_state.setdefault("probe_abandoned", bool(getattr(parameter_state, "probe_abandoned", False)))
            reason = str(getattr(parameter_state, "collection_mode_reason", "") or "").strip()
            if reason and "pcm_trigger_reason" not in pending_state:
                pending_state["pcm_trigger_reason"] = reason
        return pending_state

    def _initial_snapshot(
        self,
        *,
        tool_name: str,
        current_ao: Any,
        pending_state: Dict[str, Any],
        classification: Any,
    ) -> Dict[str, Dict[str, Any]]:
        if isinstance(pending_state.get("parameter_snapshot"), dict):
            return copy.deepcopy(pending_state.get("parameter_snapshot"))
        if current_ao is not None and isinstance(getattr(current_ao, "metadata", None), dict):
            metadata_snapshot = current_ao.metadata.get("parameter_snapshot")
            if isinstance(metadata_snapshot, dict):
                return copy.deepcopy(metadata_snapshot)
        if (
            classification is not None
            and classification.classification == AOClassType.REVISION
            and current_ao is not None
            and current_ao.parent_ao_id
            and self.ao_manager is not None
        ):
            parent = self.ao_manager.get_ao_by_id(current_ao.parent_ao_id)
            if parent is not None:
                parent_metadata = parent.metadata if isinstance(parent.metadata, dict) else {}
                if isinstance(parent_metadata.get("parameter_snapshot"), dict):
                    return copy.deepcopy(parent_metadata.get("parameter_snapshot"))
                return self._snapshot_from_parameters(parent.parameters_used)
        return self._empty_snapshot(tool_name)

    def _empty_snapshot(self, tool_name: str) -> Dict[str, Dict[str, Any]]:
        tool_spec = self._get_tool_spec(tool_name)
        slots: List[str] = []
        slots.extend(tool_spec.get("required_slots") or [])
        slots.extend(tool_spec.get("optional_slots") or [])
        slots.extend(tool_spec.get("clarification_followup_slots") or [])
        snapshot: Dict[str, Dict[str, Any]] = {}
        for slot_name in dict.fromkeys(str(item) for item in slots if item):
            snapshot[slot_name] = self._slot_record(None, "missing", None, None)
        return snapshot

    @staticmethod
    def _snapshot_from_parameters(parameters: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        snapshot: Dict[str, Dict[str, Any]] = {}
        for key, value in dict(parameters or {}).items():
            snapshot[str(key)] = {
                "value": copy.deepcopy(value),
                "source": "user",
                "confidence": 1.0,
                "raw_text": None,
            }
        return snapshot

    async def _ensure_file_context(self, state: Any, file_path: Optional[str]) -> None:
        resolved_path = str(file_path or "").strip()
        if not resolved_path or getattr(state.file_context, "grounded", False):
            return
        fact_memory = self.inner_router.memory.fact_memory
        analysis = None
        if (
            isinstance(fact_memory.file_analysis, dict)
            and str(fact_memory.file_analysis.get("file_path") or "") == resolved_path
        ):
            analysis = dict(fact_memory.file_analysis)
        else:
            result = await self.file_analyzer.execute(file_path=resolved_path)
            if result.success and isinstance(result.data, dict):
                analysis = dict(result.data)
                analysis["file_path"] = resolved_path
        if not isinstance(analysis, dict):
            return
        state.update_file_context(analysis)
        fact_memory.active_file = resolved_path
        fact_memory.file_analysis = dict(analysis)

    def _resolve_tool_name(
        self,
        *,
        state: Any,
        current_ao: Any,
        pending_state: Dict[str, Any],
        classification: Any,
    ) -> Optional[str]:
        pending_tool = str(pending_state.get("tool_name") or "").strip()
        if pending_tool:
            return pending_tool
        hints = self.inner_router._extract_message_execution_hints(state)
        desired_chain = [str(item) for item in hints.get("desired_tool_chain") or [] if item]
        if desired_chain:
            return desired_chain[0]
        task_type = str(getattr(state.file_context, "task_type", "") or "").strip()
        if task_type == "macro_emission":
            return "calculate_macro_emission"
        if task_type == "micro_emission":
            return "calculate_micro_emission"
        if hints.get("wants_factor"):
            return "query_emission_factors"
        if (
            classification is not None
            and classification.classification == AOClassType.REVISION
            and current_ao is not None
            and current_ao.parent_ao_id
            and self.ao_manager is not None
        ):
            parent = self.ao_manager.get_ao_by_id(current_ao.parent_ao_id)
            if parent is not None:
                for record in reversed(parent.tool_call_log):
                    if record.success:
                        return record.tool
        return None

    def _run_stage1(
        self,
        state: Any,
        snapshot: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        hints = self.inner_router._extract_message_execution_hints(state)
        filled: List[str] = []

        def apply(slot_name: str, value: Any, raw_text: Any) -> None:
            if value in (None, "", []):
                return
            snapshot[slot_name] = self._slot_record(
                value=value,
                source="user",
                confidence=1.0,
                raw_text=raw_text,
            )
            filled.append(slot_name)

        apply("vehicle_type", hints.get("vehicle_type"), hints.get("vehicle_type_raw") or hints.get("vehicle_type"))
        if hints.get("pollutants"):
            pollutants = list(hints.get("pollutants") or [])
            apply("pollutants", pollutants, pollutants)
        apply("season", hints.get("season"), hints.get("season_raw") or hints.get("season"))
        apply("road_type", hints.get("road_type"), hints.get("road_type_raw") or hints.get("road_type"))
        apply("meteorology", hints.get("meteorology"), hints.get("meteorology_raw") or hints.get("meteorology"))
        apply(
            "stability_class",
            hints.get("stability_class"),
            hints.get("stability_class_raw") or hints.get("stability_class"),
        )
        if hints.get("model_year") is not None:
            year_text = str(hints.get("model_year"))
            apply("model_year", year_text, year_text)
        return list(dict.fromkeys(filled))

    async def _run_stage2_llm(
        self,
        *,
        user_message: str,
        state: Any,
        current_ao: Any,
        tool_name: Optional[str],
        snapshot: Dict[str, Dict[str, Any]],
        tool_spec: Dict[str, Any],
        classification: Any,
        pcm_advisory: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        prompt_payload: Dict[str, Any] = {
            "user_message": user_message,
            "tool_name": tool_name,
            "available_tools": self._available_tool_intent_descriptions(),
            "file_context": {
                "has_file": bool(getattr(state.file_context, "has_file", False)),
                "task_type": getattr(state.file_context, "task_type", None),
                "file_path": getattr(state.file_context, "file_path", None),
            },
            "current_ao_id": getattr(current_ao, "ao_id", None) if current_ao is not None else None,
            "classification": classification.classification.name if classification is not None else None,
            "existing_parameter_snapshot": snapshot,
            "tool_slots": {
                "required_slots": list(tool_spec.get("required_slots") or []),
                "optional_slots": list(tool_spec.get("optional_slots") or []),
                "defaults": dict(tool_spec.get("defaults") or {}),
                "clarification_followup_slots": list(tool_spec.get("clarification_followup_slots") or []),
            },
            "legal_values": self._build_legal_values(tool_spec),
            "runtime_defaults": dict(RUNTIME_DEFAULTS.get(tool_name or "", {})),
            "tool_graph": _build_tool_graph_for_prompt(),
            "prior_violations": self._get_prior_violations(),
            "available_results": self._build_available_results(),
            "decision_examples": _load_decision_examples(),
        }
        if pcm_advisory is not None:
            prompt_payload["pcm_advisory"] = pcm_advisory
        return await asyncio.wait_for(
            self.llm_client.chat_json(
                messages=[{"role": "user", "content": yaml.safe_dump(prompt_payload, allow_unicode=True, sort_keys=False)}],
                system=self._stage2_system_prompt(),
                temperature=0.0,
            ),
            timeout=float(getattr(self.runtime_config, "clarification_llm_timeout_sec", 5.0)),
        )

    @staticmethod
    def _stage2_system_prompt() -> str:
        return (
            "你是交通排放分析的意图与参数补全器。根据用户消息、当前工具、已有参数快照、可用工具和合法值列表，"
            "输出完整 slots/parameter_snapshot，而不是增量 patch。\n"
            "规则：\n"
            "1. 只在用户明确表达、文件上下文强支持、或常识映射极强时使用 source=inferred。\n"
            "2. 不要编造 model_year；用户没说就输出 {value: null, source: \"missing\", confidence: 0.0}。\n"
            "3. 对口语化车型/道路/季节/污染物，可以把 value 填成你判断的合法标准名，同时 raw_text 保留用户原词。\n"
            "4. 如果缺少必需槽位，needs_clarification=true，并生成一个简洁自然的问题。\n"
            "5. 同时判断工具意图，输出 intent: {resolved_tool, intent_confidence, reasoning}。\n"
            "6. 可用工具: query_emission_factors=查询排放因子(factor/emission factor/排放因子/因子); "
            "calculate_micro_emission=VSP逐秒微观排放; calculate_macro_emission=路段级宏观排放; query_knowledge=知识库检索。\n"
            "7. 如果用户明确说先确认参数但未指定工具类别，intent_confidence=none；如果说“那类因子”等工具关键词，intent_confidence=high。\n"
            "8. 同时判断用户的对话姿态 stance: {value, confidence, reasoning}。value 只能是 directive/deliberative/exploratory。\n"
            "9. stance 判断原则: 含“先/确认/看看参数”等先讨论信号=deliberative；短消息+明确工具指向=directive；"
            "询问可能性或宽泛探索=exploratory；不确定时输出 directive。\n"
            "10. 输出 JSON，优先使用 {slots: {...}, intent: {...}, stance: {...}, missing_required, needs_clarification, clarification_question, ambiguous_slots}；"
            "兼容时也可输出 parameter_snapshot。\n"
            "11. 每个槽位都输出 {value, source, confidence, raw_text}；source 仅允许 user/default/inferred/missing。\n"
            "12. 严禁将 value 设置为字符串 \"missing\"、\"unknown\"、\"none\"、\"n/a\"、\"null\" 或任何文本 placeholder；"
            "value 必须是 null 或合法类型值。\n"
            "13. (K4) runtime_defaults 字段列出了当前工具可用的运行时默认值（如 model_year=2020）。"
            "当用户未提供对应槽位值时，你可以用默认值填充（source=default, confidence=0.5），但必须在 needs_clarification 为 false 时注明。\n"
            "14. (K6) tool_graph 字段列出了工具间的依赖关系（requires/provides/upstream_tools）。"
            "如果用户请求的工具需要上游结果（如 calculate_dispersion 需要 emission），"
            "且 available_results 中不包含对应结果类型，请在 intent.chain 里按依赖顺序规划执行序列。\n"
            "15. (K7) prior_violations 字段列出了本轮对话中之前的参数约束冲突记录。"
            "如果当前用户消息与之前的违规相关（相同的参数组合被再次尝试），"
            "你应该在 stance 或 clarification_question 中反映这些约束。\n"
            "16. (K8) available_results 字段列出了当前会话中已完成的工具结果类型。"
            "在规划工具链时避免重复已存在的结果；如果用户请求的结果已存在，告知用户可复用。\n"
            "17. (DECISION FIELD) 额外输出 decision 字段表达你对当前对话的执行判断。"
            "格式: {value: \"proceed\"|\"clarify\"|\"deliberate\", confidence: 0-1, reasoning: string, clarification_question: string|null}。"
            "proceed=信息足够可执行工具（missing_required=[]且参数完整）；"
            "clarify=需要询问用户具体问题（填 clarification_question）；"
            "deliberate=用户在探索/比较，不直接执行而给出建议（填 reasoning）。"
            "confidence≥0.5；当 value=clarify 时 clarification_question 非空；当 value=deliberate 时 reasoning 非空。\n"
            "18. (K9) pcm_advisory: governance 主动检测到的对话提示信号 "
            "(含 unfilled_optionals, runtime_defaults_available, confirm_first 等)。"
            "这是非约束性建议。你应该考虑 advisory 中的信息，但是否 proceed/clarify "
            "由你的 decision 字段最终决定。当 advisory 显示 unfilled_optional 但 "
            "runtime_defaults_available 中有对应默认值时，通常应 decision=proceed "
            "(因为信息已充分)。"
        )

    @staticmethod
    def _stage2_snapshot_payload(llm_payload: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(llm_payload.get("slots"), dict):
            return dict(llm_payload.get("slots") or {})
        return dict(llm_payload.get("parameter_snapshot") or {})

    @staticmethod
    def _extract_llm_intent_hint(
        llm_payload: Dict[str, Any],
    ) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], bool]:
        if not isinstance(llm_payload, dict):
            return None, None, False
        raw = llm_payload.get("intent")
        if isinstance(raw, dict):
            hint = {
                "resolved_tool": raw.get("resolved_tool") or raw.get("tool"),
                "intent_confidence": raw.get("intent_confidence") or raw.get("confidence") or raw.get("conf"),
                "reasoning": raw.get("reasoning"),
                "projected_chain": raw.get("projected_chain") or raw.get("chain") or llm_payload.get("chain") or [],
            }
            return hint, dict(raw), True
        if llm_payload.get("tool_name"):
            raw_hint = {
                "resolved_tool": llm_payload.get("tool_name"),
                "intent_confidence": "high",
                "reasoning": "legacy tool_name field",
                "projected_chain": llm_payload.get("chain") or [],
            }
            return raw_hint, dict(raw_hint), True
        return None, None, False

    @staticmethod
    def _extract_llm_stance_hint(
        llm_payload: Dict[str, Any],
    ) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], bool]:
        if not isinstance(llm_payload, dict):
            return (
                {"value": "directive", "confidence": "low", "reasoning": "missing stance fallback"},
                None,
                False,
            )
        if list(llm_payload.get("missing_required") or []):
            raw = llm_payload.get("stance")
            return (
                {
                    "value": "deliberative",
                    "confidence": "high",
                    "reasoning": "missing required slots",
                },
                dict(raw) if isinstance(raw, dict) else None,
                isinstance(raw, dict),
            )
        raw = llm_payload.get("stance")
        if isinstance(raw, dict):
            hint = {
                "value": raw.get("value") or raw.get("stance"),
                "confidence": raw.get("confidence") or raw.get("conf"),
                "reasoning": raw.get("reasoning"),
            }
            return hint, dict(raw), True
        return (
            {"value": "directive", "confidence": "low", "reasoning": "missing stance fallback"},
            None,
            False,
        )

    def _merge_stage2_snapshot(
        self,
        base_snapshot: Dict[str, Dict[str, Any]],
        llm_snapshot: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        merged = copy.deepcopy(base_snapshot)
        for slot_name, slot_payload in dict(llm_snapshot or {}).items():
            if not isinstance(slot_payload, dict):
                continue
            normalized_payload = self._normalize_missing_value(dict(slot_payload))
            merged[str(slot_name)] = {
                "value": copy.deepcopy(normalized_payload.get("value")),
                "source": str(normalized_payload.get("source") or "missing"),
                "confidence": normalized_payload.get("confidence"),
                "raw_text": copy.deepcopy(normalized_payload.get("raw_text")),
            }
        return merged

    @staticmethod
    def _normalize_missing_value(payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return payload
        normalized = dict(payload)
        value = normalized.get("value")
        source = str(normalized.get("source") or "").strip().lower()
        if source == "missing":
            normalized["value"] = None
            normalized["source"] = "missing"
            return normalized
        if isinstance(value, str) and value.strip().lower() in _SENTINEL_VALUES:
            normalized["value"] = None
            if source != "rejected":
                normalized["source"] = "missing"
        return normalized

    def _stage2_available(self) -> bool:
        return (
            bool(getattr(self.runtime_config, "enable_clarification_stage2_llm", True))
            and self.llm_client is not None
        )

    def _generic_tool_spec(self) -> Dict[str, Any]:
        slots: List[str] = []
        for spec in self._load_tools_config().values():
            if not isinstance(spec, dict):
                continue
            slots.extend(spec.get("required_slots") or [])
            slots.extend(spec.get("optional_slots") or [])
            slots.extend(spec.get("clarification_followup_slots") or [])
        return {
            "required_slots": [],
            "optional_slots": list(dict.fromkeys(str(slot) for slot in slots if str(slot).strip())),
            "defaults": {},
            "clarification_followup_slots": [],
        }

    @staticmethod
    def _available_tool_intent_descriptions() -> Dict[str, str]:
        return {
            "query_emission_factors": "查询排放因子；关键词包括 factor, emission factor, 排放因子, 因子",
            "calculate_micro_emission": "VSP 逐秒微观排放计算；通常需要轨迹文件",
            "calculate_macro_emission": "路段级宏观排放计算；通常需要路网/流量文件",
            "query_knowledge": "知识库检索和政策/方法问答",
        }

    def _persist_tool_intent(self, ao: Any, tool_intent: Any) -> None:
        if ao is None or not self._first_class_state_enabled():
            return
        target = getattr(ao, "tool_intent", None)
        if target is None or tool_intent is None:
            return
        target.resolved_tool = getattr(tool_intent, "resolved_tool", None)
        target.confidence = getattr(tool_intent, "confidence", IntentConfidence.NONE)
        target.evidence = list(getattr(tool_intent, "evidence", []) or [])
        target.resolved_at_turn = getattr(tool_intent, "resolved_at_turn", None)
        target.resolved_by = getattr(tool_intent, "resolved_by", None)
        target.projected_chain = list(getattr(tool_intent, "projected_chain", []) or [])

    def _persist_stance(self, ao: Any, resolution: StanceResolution) -> None:
        if ao is None or not getattr(self.runtime_config, "enable_conversational_stance", True):
            return
        ao.stance = resolution.stance
        ao.stance_confidence = resolution.confidence
        ao.stance_resolved_by = resolution.resolved_by
        turn = self._current_turn_index()
        if not ao.stance_history or ao.stance_history[-1][1] != resolution.stance:
            ao.stance_history.append((turn, resolution.stance))

    @staticmethod
    def _apply_stance_telemetry(
        telemetry: ClarificationTelemetry,
        resolution: StanceResolution,
    ) -> None:
        telemetry.stance_value = resolution.stance.value
        telemetry.stance_confidence = resolution.confidence.value
        telemetry.stance_resolved_by = resolution.resolved_by
        telemetry.stance_evidence = list(resolution.evidence)

    def _run_stage3(
        self,
        *,
        tool_name: str,
        snapshot: Dict[str, Dict[str, Any]],
        tool_spec: Dict[str, Any],
        suppress_defaults_for: List[str],
    ) -> tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        updated = copy.deepcopy(snapshot)
        defaults = dict(tool_spec.get("defaults") or {})
        normalizations: List[Dict[str, Any]] = []
        rejected_slots: List[str] = []
        confidence_threshold = float(
            getattr(self.runtime_config, "clarification_llm_confidence_threshold", 0.7)
        )

        suppressed = {str(item) for item in suppress_defaults_for if str(item).strip()}
        for slot_name, default_value in defaults.items():
            if slot_name in suppressed:
                continue
            slot_payload = updated.setdefault(slot_name, self._slot_record(None, "missing", None, None))
            if slot_payload.get("source") == "missing" and slot_payload.get("value") in (None, "", []):
                slot_payload.update(self._slot_record(default_value, "default", 1.0, None))

        for slot_name, slot_payload in list(updated.items()):
            if not isinstance(slot_payload, dict):
                continue
            source = str(slot_payload.get("source") or "missing")
            value = slot_payload.get("value")
            raw_text = slot_payload.get("raw_text")
            confidence = slot_payload.get("confidence")
            if source in {"missing", "default"}:
                continue
            if source == "inferred" and confidence is not None and float(confidence) < confidence_threshold:
                updated[slot_name] = self._slot_record(None, "missing", None, raw_text)
                continue

            normalized, success, strategy, suggestions = self._standardize_slot(
                slot_name,
                value=value,
                raw_text=raw_text,
            )
            if success:
                updated[slot_name]["value"] = normalized
                normalizations.append(
                    {
                        "slot": slot_name,
                        "raw": raw_text if raw_text not in (None, "", []) else value,
                        "standardized": normalized,
                        "strategy": strategy,
                    }
                )
                continue
            if source == "inferred" and self._is_legal_candidate(slot_name, value):
                updated[slot_name]["value"] = value
                normalizations.append(
                    {
                        "slot": slot_name,
                        "raw": raw_text if raw_text not in (None, "", []) else value,
                        "standardized": value,
                        "strategy": "llm_candidate_validated",
                    }
                )
                continue
            updated[slot_name]["source"] = "rejected"
            updated[slot_name]["value"] = None
            updated[slot_name]["suggestions"] = list(suggestions or [])
            rejected_slots.append(slot_name)

        return updated, normalizations, list(dict.fromkeys(rejected_slots))

    def _standardize_slot(
        self,
        slot_name: str,
        *,
        value: Any,
        raw_text: Any,
    ) -> tuple[Any, bool, str, List[str]]:
        param_type = {
            "vehicle_type": "vehicle_type",
            "pollutants": "pollutant_list",
            "pollutant": "pollutant",
            "season": "season",
            "road_type": "road_type",
            "meteorology": "meteorology",
            "stability_class": "stability_class",
        }.get(slot_name)
        if param_type is None:
            return value, True, "passthrough", []
        raw_value = raw_text if raw_text not in (None, "", []) else value
        result = self.stage3_engine.standardize(
            param_type,
            raw_value,
            context={"tool": "clarification_contract", "param_name": slot_name},
        )
        return result.normalized, bool(result.success), str(result.strategy or "unknown"), list(result.suggestions or [])

    @staticmethod
    def _missing_slots(
        snapshot: Dict[str, Dict[str, Any]],
        slots: List[str],
    ) -> List[str]:
        missing: List[str] = []
        for slot_name in slots:
            slot_payload = snapshot.get(slot_name) or {}
            if not isinstance(slot_payload, dict):
                missing.append(slot_name)
                continue
            slot_payload = ClarificationContract._normalize_missing_value(slot_payload)
            if slot_payload.get("source") == "rejected":
                missing.append(slot_name)
                continue
            if slot_payload.get("value") in (None, "", []):
                missing.append(slot_name)
        return missing

    def _build_question(
        self,
        *,
        tool_name: str,
        snapshot: Dict[str, Dict[str, Any]],
        missing_slots: List[str],
        rejected_slots: List[str],
        llm_question: Optional[str],
    ) -> str:
        if rejected_slots:
            slot_name = rejected_slots[0]
            slot_payload = snapshot.get(slot_name) or {}
            raw = slot_payload.get("raw_text")
            suggestions = slot_payload.get("suggestions") if isinstance(slot_payload.get("suggestions"), list) else []
            choices = "、".join(str(item) for item in suggestions[:5]) or "请换一种更标准的说法"
            return f"我不太确定您说的“{raw or slot_name}”对应哪一项。可选有：{choices}。"
        if llm_question:
            return llm_question
        slot_name = missing_slots[0] if missing_slots else ""
        if not slot_name:
            return "我还需要补充一个关键参数后才能继续，请直接告诉我缺失的参数值。"
        label = self._slot_display_name(slot_name)
        desc = self._valid_values_description(slot_name)
        return f"请提供{label}（{desc}）。"

    async def _build_probe_question(
        self,
        *,
        tool_name: str,
        snapshot: Dict[str, Dict[str, Any]],
        slot_name: str,
        current_ao: Any,
    ) -> str:
        llm_question = await self._run_probe_question_llm(
            tool_name=tool_name,
            snapshot=snapshot,
            slot_name=slot_name,
            current_ao=current_ao,
        )
        if llm_question:
            return llm_question
        return ""

    async def _run_probe_question_llm(
        self,
        *,
        tool_name: str,
        snapshot: Dict[str, Dict[str, Any]],
        slot_name: str,
        current_ao: Any,
    ) -> Optional[str]:
        if self.llm_client is None or not getattr(self.runtime_config, "enable_clarification_stage2_llm", True):
            return None
        prompt_payload = {
            "tool_name": tool_name,
            "slot_name": slot_name,
            "slot_display_name": self._slot_display_name(slot_name),
            "valid_values_description": self._valid_values_description(slot_name),
            "current_snapshot": snapshot,
            "current_ao_id": getattr(current_ao, "ao_id", None) if current_ao is not None else None,
            "objective_text": getattr(current_ao, "objective_text", None) if current_ao is not None else None,
        }
        try:
            response = await asyncio.wait_for(
                self.llm_client.chat_json(
                    messages=[{"role": "user", "content": yaml.safe_dump(prompt_payload, allow_unicode=True, sort_keys=False)}],
                    system=(
                        "你是交通排放分析的澄清问题生成器。"
                        "请针对指定参数生成一句简洁自然的追问，不能引入额外参数，不能提供解释段落。"
                        '输出 JSON: {"clarification_question": "..."}'
                    ),
                    temperature=0.0,
                ),
                timeout=float(getattr(self.runtime_config, "clarification_llm_timeout_sec", 5.0)),
            )
        except Exception as exc:
            logger.warning("ClarificationContract probe-question LLM failed: %s", exc)
            return None
        question = str((response or {}).get("clarification_question") or "").strip()
        return question or None

    @staticmethod
    def _slot_display_name(slot_name: str) -> str:
        mapping = {
            "vehicle_type": "车辆类型",
            "pollutants": "污染物",
            "pollutant": "污染物",
            "model_year": "车型年份",
            "season": "季节",
            "road_type": "道路类型",
            "meteorology": "气象条件",
            "stability_class": "稳定度等级",
        }
        return mapping.get(slot_name, slot_name)

    def _valid_values_description(self, slot_name: str) -> str:
        values = self._valid_values_list(slot_name)
        if not values:
            return "请提供合法值"
        return " / ".join(str(item) for item in values[:6])

    def _valid_values_list(self, slot_name: str) -> List[str]:
        if slot_name == "model_year":
            return [str(y) for y in range(YEAR_RANGE_MIN, YEAR_RANGE_MAX + 1, 5)]
        if slot_name == "pollutants" or slot_name == "pollutant":
            values = self.stage3_engine.get_candidates("pollutant")
        else:
            param_type = {
                "vehicle_type": "vehicle_type",
                "season": "season",
                "road_type": "road_type",
                "meteorology": "meteorology",
                "stability_class": "stability_class",
            }.get(slot_name)
            values = self.stage3_engine.get_candidates(param_type) if param_type else []
        if not values:
            return []
        return [str(item) for item in values[:6]]

    def _persist_snapshot_state(
        self,
        *,
        ao: Any,
        tool_name: str,
        snapshot: Dict[str, Dict[str, Any]],
        clarification_question: str,
        pending: bool,
        missing_slots: List[str],
        rejected_slots: List[str],
        followup_slots: List[str],
        confirm_first_detected: bool,
        collection_mode: bool,
        pcm_trigger_reason: Optional[str],
        pending_decision: Optional[str],
        probe_optional_slot: Optional[str],
        probe_turn_count: int,
        probe_abandoned: bool,
    ) -> None:
        if ao is None:
            return
        if self._first_class_state_enabled():
            self._update_first_class_state(
                ao=ao,
                tool_name=tool_name,
                snapshot=snapshot,
                pending=pending,
                missing_slots=missing_slots,
                collection_mode=collection_mode,
                pcm_trigger_reason=pcm_trigger_reason,
                probe_optional_slot=probe_optional_slot,
                probe_turn_count=probe_turn_count,
                probe_abandoned=probe_abandoned,
            )
        if not isinstance(ao.metadata, dict):
            ao.metadata = {}
        ao.metadata["parameter_snapshot"] = copy.deepcopy(snapshot)
        ao.metadata["collection_mode"] = bool(collection_mode)
        ao.metadata["pcm_trigger_reason"] = pcm_trigger_reason
        ao.metadata["clarification_contract"] = {
            "tool_name": tool_name,
            "parameter_snapshot": copy.deepcopy(snapshot),
            "clarification_question": clarification_question,
            "pending": bool(pending),
            "missing_slots": list(missing_slots),
            "rejected_slots": list(rejected_slots),
            "followup_slots": list(followup_slots),
            "confirm_first_detected": bool(confirm_first_detected),
            "pcm_trigger_reason": pcm_trigger_reason,
            "pending_decision": pending_decision,
            "probe_optional_slot": probe_optional_slot,
            "probe_turn_count": int(probe_turn_count or 0),
            "probe_abandoned": bool(probe_abandoned),
        }

    def _update_first_class_state(
        self,
        *,
        ao: Any,
        tool_name: str,
        snapshot: Dict[str, Dict[str, Any]],
        pending: bool,
        missing_slots: List[str],
        collection_mode: bool,
        pcm_trigger_reason: Optional[str],
        probe_optional_slot: Optional[str],
        probe_turn_count: int,
        probe_abandoned: bool,
    ) -> None:
        tool_intent = getattr(ao, "tool_intent", None)
        if tool_intent is not None:
            tool_intent.resolved_tool = tool_name
            if getattr(tool_intent, "confidence", IntentConfidence.NONE) == IntentConfidence.NONE:
                tool_intent.confidence = IntentConfidence.HIGH
            if not getattr(tool_intent, "resolved_by", None):
                tool_intent.resolved_by = "clarification_contract:legacy_resolver"
            if not getattr(tool_intent, "evidence", None):
                tool_intent.evidence = ["clarification_contract.tool_name"]
            if getattr(tool_intent, "resolved_at_turn", None) is None:
                tool_intent.resolved_at_turn = self._current_turn_index()

        parameter_state = getattr(ao, "parameter_state", None)
        if parameter_state is None:
            return
        parameter_state.collection_mode = bool(collection_mode)
        parameter_state.collection_mode_reason = pcm_trigger_reason
        awaiting_slot = str(probe_optional_slot or "").strip()
        if not awaiting_slot and pending and missing_slots:
            awaiting_slot = str(missing_slots[0] or "").strip()
        parameter_state.awaiting_slot = awaiting_slot or None
        parameter_state.probe_turn_count = int(probe_turn_count or 0)
        parameter_state.probe_abandoned = bool(probe_abandoned)

        required_slots = set()
        optional_slots = set()
        tool_spec = self._get_tool_spec(tool_name)
        required_names = set(str(item) for item in list(tool_spec.get("required_slots") or []))
        optional_names = set(str(item) for item in list(tool_spec.get("optional_slots") or []))
        for slot_name, slot_payload in dict(snapshot or {}).items():
            if not isinstance(slot_payload, dict):
                continue
            if slot_payload.get("source") in {"missing", "rejected"}:
                continue
            if slot_payload.get("value") in (None, "", []):
                continue
            if slot_name in required_names:
                required_slots.add(str(slot_name))
            if slot_name in optional_names:
                optional_slots.add(str(slot_name))
        parameter_state.required_filled = required_slots
        parameter_state.optional_filled = optional_slots

    @staticmethod
    def _is_first_ao_turn(ao: Any) -> bool:
        if ao is None:
            return False
        tool_log = getattr(ao, "tool_call_log", None)
        if not isinstance(tool_log, list):
            return True
        return len(tool_log) == 0

    def _resolve_collection_mode(
        self,
        *,
        ao: Any,
        missing_required: List[str],
        confirm_first_detected: bool,
        unfilled_optionals_without_default: List[str],
        is_resume: bool,
    ) -> tuple[bool, Optional[str]]:
        if is_resume:
            return self._current_collection_mode(ao)
        if confirm_first_detected:
            return True, "confirm_first_signal"
        if self._is_first_ao_turn(ao):
            if missing_required:
                return True, "missing_required_at_first_turn"
            if unfilled_optionals_without_default:
                return True, "unfilled_optional_no_default_at_first_turn"
            return False, None
        return self._current_collection_mode(ao)

    def _current_collection_mode(self, ao: Any) -> tuple[bool, Optional[str]]:
        if ao is not None and self._first_class_state_enabled():
            parameter_state = getattr(ao, "parameter_state", None)
            if parameter_state is not None:
                reason = str(getattr(parameter_state, "collection_mode_reason", "") or "").strip()
                if getattr(parameter_state, "collection_mode", False) or reason:
                    return bool(getattr(parameter_state, "collection_mode", False)), reason or None
        if ao is None or not isinstance(getattr(ao, "metadata", None), dict):
            return False, None
        return bool(ao.metadata.get("collection_mode")), (
            str(ao.metadata.get("pcm_trigger_reason") or "") or None
        )

    @staticmethod
    def _get_unfilled_optionals_without_default(
        snapshot: Dict[str, Dict[str, Any]],
        tool_spec: Dict[str, Any],
    ) -> List[str]:
        optional_slots = [str(item) for item in list(tool_spec.get("optional_slots") or []) if str(item).strip()]
        default_slots = {
            str(key)
            for key in dict(tool_spec.get("defaults") or {}).keys()
            if str(key).strip()
        }
        no_default_slots = [slot_name for slot_name in optional_slots if slot_name not in default_slots]
        unfilled: List[str] = []
        for slot_name in no_default_slots:
            slot_payload = snapshot.get(slot_name) or {}
            if not isinstance(slot_payload, dict) or slot_payload.get("value") is None:
                unfilled.append(slot_name)
        return unfilled

    @staticmethod
    def _next_probe_turn_count(
        pending_state: Dict[str, Any],
        slot_name: str,
    ) -> int:
        previous_slot = str(pending_state.get("probe_optional_slot") or "").strip()
        if not previous_slot and list(pending_state.get("missing_slots") or []):
            previous_slot = str(list(pending_state.get("missing_slots") or [None])[0] or "").strip()
        previous_decision = str(pending_state.get("pending_decision") or "").strip()
        previous_count = int(pending_state.get("probe_turn_count") or 0)
        if previous_decision == "probe_optional" and previous_slot == slot_name:
            return previous_count + 1
        return 1

    @staticmethod
    def _decision_field_active(telemetry: ClarificationTelemetry) -> bool:
        """Return True when the LLM decision field should gate hardcoded routing."""
        if not getattr(get_config(), "enable_llm_decision_field", False):
            return False
        if telemetry is None:
            return False
        decision = telemetry.stage2_decision
        if not isinstance(decision, dict):
            return False
        value = str(decision.get("value") or "").strip().lower()
        return value in {"proceed", "clarify", "deliberate"}

    def _first_class_state_enabled(self) -> bool:
        return bool(getattr(self.runtime_config, "enable_ao_first_class_state", True))

    def _inject_snapshot_into_context(
        self,
        snapshot: Dict[str, Dict[str, Any]],
        current_ao: Any,
    ) -> None:
        fact_memory = self.inner_router.memory.fact_memory
        confirmed: Dict[str, Any] = {}
        for slot_name, slot_payload in snapshot.items():
            if not isinstance(slot_payload, dict):
                continue
            if slot_payload.get("source") in {"missing", "rejected"}:
                continue
            value = slot_payload.get("value")
            if value in (None, "", []):
                continue
            confirmed[slot_name] = value

        if "vehicle_type" in confirmed:
            fact_memory.recent_vehicle = str(confirmed["vehicle_type"])
        if "pollutants" in confirmed and isinstance(confirmed["pollutants"], list):
            fact_memory.recent_pollutants = [str(item) for item in confirmed["pollutants"]]
        if "model_year" in confirmed:
            try:
                fact_memory.recent_year = int(confirmed["model_year"])
            except Exception:
                fact_memory.recent_year = None

        fact_memory.update_session_confirmed_parameters(confirmed)
        fact_memory.locked_parameters_display = dict(confirmed)
        if current_ao is not None:
            if not isinstance(current_ao.metadata, dict):
                current_ao.metadata = {}
            current_ao.metadata["parameter_snapshot"] = copy.deepcopy(snapshot)
            for key, value in confirmed.items():
                current_ao.parameters_used[key] = value

    @staticmethod
    def _build_short_circuit_trace(
        *,
        question: str,
        telemetry: Dict[str, Any],
        tool_name: str,
        snapshot: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "steps": [
                {
                    "step_type": "clarification",
                    "action": "clarification_contract",
                    "reasoning": question,
                    "output_summary": {
                        "tool_name": tool_name,
                        "parameter_snapshot": snapshot,
                        "telemetry": telemetry,
                    },
                }
            ],
            "final_stage": "NEEDS_CLARIFICATION",
            "clarification_telemetry": [dict(telemetry)],
        }

    @classmethod
    def _load_tools_config(cls) -> Dict[str, Any]:
        if cls._tools_cache is not None:
            return cls._tools_cache
        registry = get_tool_contract_registry()
        tools: Dict[str, Any] = {}
        for definition in registry.get_tool_definitions():
            function = definition.get("function") if isinstance(definition, dict) else None
            tool_name = str((function or {}).get("name") or "").strip()
            if not tool_name:
                continue
            tools[tool_name] = {
                "required_slots": registry.get_required_slots(tool_name),
                "optional_slots": registry.get_optional_slots(tool_name),
                "defaults": registry.get_defaults(tool_name),
                "clarification_followup_slots": registry.get_clarification_followup_slots(tool_name),
                "confirm_first_slots": registry.get_confirm_first_slots(tool_name),
            }
        cls._tools_cache = tools
        return cls._tools_cache

    def _get_tool_spec(self, tool_name: Optional[str]) -> Dict[str, Any]:
        if not tool_name:
            return {}
        return dict(self._load_tools_config().get(tool_name) or {})

    def _build_legal_values(self, tool_spec: Dict[str, Any]) -> Dict[str, Any]:
        values: Dict[str, Any] = {}
        slots = list(tool_spec.get("required_slots") or []) + list(tool_spec.get("optional_slots") or [])
        for slot_name in slots:
            if slot_name == "model_year":
                values[slot_name] = f"{YEAR_RANGE_MIN}-{YEAR_RANGE_MAX}"
                continue
            param_type = {
                "vehicle_type": "vehicle_type",
                "pollutants": "pollutant",
                "pollutant": "pollutant",
                "season": "season",
                "road_type": "road_type",
                "meteorology": "meteorology",
                "stability_class": "stability_class",
            }.get(slot_name)
            if not param_type:
                continue
            values[slot_name] = self.stage3_engine.get_candidates(param_type)
        return values

    def _is_legal_candidate(self, slot_name: str, value: Any) -> bool:
        if slot_name == "model_year":
            try:
                year = int(value)
            except Exception:
                return False
            return YEAR_RANGE_MIN <= year <= YEAR_RANGE_MAX
        legal_values = self._build_legal_values({"required_slots": [slot_name], "optional_slots": []}).get(slot_name)
        if not legal_values:
            return False
        if isinstance(value, list):
            return all(item in legal_values for item in value)
        return value in legal_values

    @staticmethod
    def _slot_record(
        value: Any,
        source: str,
        confidence: Optional[float],
        raw_text: Any,
    ) -> Dict[str, Any]:
        return {
            "value": copy.deepcopy(value),
            "source": source,
            "confidence": confidence,
            "raw_text": copy.deepcopy(raw_text),
        }

    def _get_prior_violations(self) -> list:
        context_store = getattr(self.inner_router, "context_store", None)
        if context_store is None and hasattr(self.inner_router, "_ensure_context_store"):
            context_store = self.inner_router._ensure_context_store()
        if context_store is not None:
            return context_store.get_session_violations()
        return []

    def _build_available_results(self) -> dict:
        context_store = getattr(self.inner_router, "context_store", None)
        if context_store is None and hasattr(self.inner_router, "_ensure_context_store"):
            context_store = self.inner_router._ensure_context_store()
        if context_store is None:
            return {}
        known_tokens = ["emission", "dispersion", "hotspot", "visualization",
                        "scenario_comparison", "file_analysis", "data_quality_report",
                        "emission_factors", "knowledge"]
        result: dict = {}
        for token in known_tokens:
            result[token] = context_store.has_result(token)
        return result

    def _current_turn_index(self) -> int:
        turn_counter = int(getattr(self.inner_router.memory, "turn_counter", 0) or 0)
        return turn_counter + 1

    def _detect_confirm_first(self, user_message: str) -> Optional[str]:
        text = str(user_message or "").strip().lower()
        if not text:
            return None
        signals = tuple(getattr(self.runtime_config, "clarification_confirm_first_signals", ()) or ())
        for signal in signals:
            if signal and signal in text:
                return f"signal:{signal}"

        patterns = set(getattr(self.runtime_config, "clarification_confirm_first_patterns", ()) or ())
        if "need_parameters_fuzzy" in patterns and re.search(r"需要.{0,12}参数", text):
            return "pattern:need_parameters_fuzzy"
        if "leading_sequence_marker" in patterns and self._matches_leading_sequence_marker(text):
            return "pattern:leading_sequence_marker"
        if "parameter_request" in patterns and self._matches_parameter_request(text):
            return "pattern:parameter_request"
        return None

    @staticmethod
    def _matches_leading_sequence_marker(text: str) -> bool:
        if not re.match(r"^\s*(先|再|然后|接着|之后|先把|先用)", text):
            return False
        request_terms = (
            "帮",
            "查",
            "算",
            "计算",
            "处理",
            "看看",
            "看",
            "确认",
            "做",
            "用",
            "跑",
            "分析",
            "query",
            "calculate",
            "check",
            "confirm",
            "run",
            "analyze",
            "process",
        )
        return any(term in text for term in request_terms)

    @staticmethod
    def _matches_parameter_request(text: str) -> bool:
        if "参数" not in text:
            return False
        request_terms = (
            "需要",
            "确认",
            "怎么",
            "哪些",
            "什么",
            "列",
            "设置",
            "填",
            "帮",
            "看",
        )
        return any(term in text for term in request_terms)
