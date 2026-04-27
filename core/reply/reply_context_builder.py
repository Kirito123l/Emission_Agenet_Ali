"""Build strict ReplyContext objects from governance-layer state."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.ao_manager import AOManager
from core.constraint_violation_writer import ConstraintViolationWriter
from core.context_store import SessionContextStore
from core.reply.reply_context import (
    AOStatusSummary,
    ClarificationRequest,
    ContinuationState,
    ReplyContext,
    ToolExecutionSummary,
)
from core.trace import TraceStep


IMPORTANT_TRACE_TYPES = {
    "cross_constraint_violation",
    "cross_constraint_warning",
    "clarification",
    "parameter_standardization",
    "tool_execution",
    "synthesis",
    "parameter_negotiation_required",
    "input_completion_required",
    "action_readiness_blocked",
    "action_readiness_repairable",
}


class ReplyContextBuilder:
    """Pure context assembler for the LLM reply parser."""

    def build(
        self,
        *,
        user_message: str,
        router_text: str,
        trace_steps: List[TraceStep],
        ao_manager: Optional[AOManager],
        violation_writer: Optional[ConstraintViolationWriter],
        context_store: Optional[SessionContextStore],
        governance_metadata: Optional[Dict[str, Any]] = None,
    ) -> ReplyContext:
        step_dicts = [self._step_to_dict(step) for step in list(trace_steps or [])]
        meta = dict(governance_metadata or {})
        tool_execs = self._tool_executions(step_dicts)
        return ReplyContext(
            user_message=str(user_message or ""),
            router_text=str(router_text or ""),
            tool_executions=tool_execs,
            violations=violation_writer.get_latest() if violation_writer is not None else [],
            pending_clarifications=self._pending_clarifications(step_dicts, meta),
            ao_status=self._ao_status(ao_manager),
            trace_highlights=self._trace_highlights(step_dicts),
            extra=self._extra(context_store),
            intent_unresolved=bool(meta.get("intent_unresolved", False)),
            stance=str(meta.get("stance") or ""),
            continuation_state=self._continuation_state(meta),
            available_tools=self._str_list(meta.get("available_tools")),
            available_capabilities=self._str_list(meta.get("available_capabilities")),
            tool_executed=bool(tool_execs),
            executed_tool_names=[t.tool_name for t in tool_execs if t.success],
            legal_values_for_pending_slots=self._legal_values_from_meta(meta, step_dicts),
        )

    @staticmethod
    def _step_to_dict(step: Any) -> Dict[str, Any]:
        if isinstance(step, dict):
            return dict(step)
        if hasattr(step, "to_dict"):
            payload = step.to_dict()
            return dict(payload) if isinstance(payload, dict) else {}
        return {}

    def _tool_executions(self, steps: List[Dict[str, Any]]) -> List[ToolExecutionSummary]:
        executions: List[ToolExecutionSummary] = []
        for step in steps:
            if str(step.get("step_type") or "") != "tool_execution":
                continue
            output = step.get("output_summary") if isinstance(step.get("output_summary"), dict) else {}
            input_summary = step.get("input_summary") if isinstance(step.get("input_summary"), dict) else {}
            arguments = input_summary.get("arguments") if isinstance(input_summary.get("arguments"), dict) else {}
            success = bool(output.get("success"))
            error = step.get("error") or output.get("error")
            summary = (
                step.get("reasoning")
                or output.get("message")
                or output.get("summary")
                or ("success" if success else "failed")
            )
            executions.append(
                ToolExecutionSummary(
                    tool_name=str(step.get("action") or output.get("tool_name") or ""),
                    arguments=dict(arguments),
                    success=success,
                    summary=str(summary or ""),
                    error=str(error) if error is not None else None,
                )
            )
        return executions

    def _pending_clarifications(self, steps: List[Dict[str, Any]], meta: Dict[str, Any]) -> List[ClarificationRequest]:
        pending: List[ClarificationRequest] = []
        seen_targets: set[str] = set()
        # First, collect structured pending_clarifications from governance metadata.
        gov_pending = meta.get("pending_clarifications")
        if isinstance(gov_pending, list):
            for item in gov_pending:
                if not isinstance(item, dict):
                    continue
                cr = ClarificationRequest(
                    target_field=str(item.get("target_field") or item.get("slot") or ""),
                    reason=str(item.get("reason") or ""),
                    options=[str(o) for o in list(item.get("options") or item.get("examples") or [])],
                    label=str(item.get("label") or ""),
                    tool=str(item.get("tool") or ""),
                )
                if cr.target_field and cr.target_field not in seen_targets:
                    pending.append(cr)
                    seen_targets.add(cr.target_field)
        # Then collect from trace steps as before.
        for step in steps:
            step_type = str(step.get("step_type") or "")
            if step_type not in {
                "clarification",
                "parameter_negotiation_required",
                "input_completion_required",
                "action_readiness_blocked",
                "action_readiness_repairable",
            }:
                continue
            output = step.get("output_summary") if isinstance(step.get("output_summary"), dict) else {}
            input_summary = step.get("input_summary") if isinstance(step.get("input_summary"), dict) else {}
            target = (
                output.get("target_field")
                or output.get("awaiting_slot")
                or output.get("missing_slot")
                or input_summary.get("target_field")
                or input_summary.get("awaiting_slot")
                or step.get("action")
                or "unknown"
            )
            options_raw = output.get("options") or input_summary.get("options") or []
            options = [str(item) for item in options_raw] if isinstance(options_raw, list) else []
            reason = step.get("reasoning") or output.get("question") or output.get("message") or step.get("error") or ""
            pending.append(
                ClarificationRequest(
                    target_field=str(target),
                    reason=str(reason or ""),
                    options=options,
                )
            )
        return pending

    @staticmethod
    def _ao_status(ao_manager: Optional[AOManager]) -> Optional[AOStatusSummary]:
        current = ao_manager.get_current_ao() if ao_manager is not None else None
        if current is None:
            return None
        status = getattr(getattr(current, "status", None), "value", None) or getattr(current, "status", "")
        completed_steps: List[str] = []
        for record in list(getattr(current, "tool_call_log", []) or []):
            if not bool(getattr(record, "success", False)):
                continue
            tool_name = str(getattr(record, "tool_name", None) or getattr(record, "tool", "") or "")
            if tool_name:
                completed_steps.append(tool_name)
        return AOStatusSummary(
            state=str(status or ""),
            objective=str(getattr(current, "objective_text", "") or ""),
            completed_steps=completed_steps,
        )

    def _trace_highlights(self, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        highlights: List[Dict[str, Any]] = []
        for step in steps:
            step_type = str(step.get("step_type") or "")
            if step_type not in IMPORTANT_TRACE_TYPES:
                continue
            summary = (
                step.get("reasoning")
                or step.get("error")
                or self._compact_mapping(step.get("output_summary"))
                or self._compact_mapping(step.get("input_summary"))
            )
            highlights.append(
                {
                    "step_type": step_type,
                    "action": step.get("action"),
                    "summary": self._truncate(summary),
                }
            )
        return highlights

    @staticmethod
    def _extra(context_store: Optional[SessionContextStore]) -> Dict[str, Any]:
        if context_store is None:
            return {}
        stored = context_store.get_by_type("data_quality_report")
        if stored is None:
            return {}
        return {
            "data_quality_report": stored.to_persisted_dict()
            if hasattr(stored, "to_persisted_dict")
            else stored
        }

    @staticmethod
    def _compact_mapping(value: Any) -> str:
        if not isinstance(value, dict):
            return ""
        parts = []
        for key, item in list(value.items())[:4]:
            parts.append(f"{key}={item}")
        return ", ".join(parts)

    @staticmethod
    def _continuation_state(meta: Dict[str, Any]) -> Optional[ContinuationState]:
        cs = meta.get("continuation_state")
        if isinstance(cs, dict):
            return ContinuationState(
                objective=str(cs.get("objective") or ""),
                pending_slots=[str(item) for item in list(cs.get("pending_slots") or [])],
                prior_tool=str(cs.get("prior_tool") or ""),
                pending_objective=str(cs.get("pending_objective") or ""),
            )
        return None

    @staticmethod
    def _legal_values_from_meta(meta: Dict[str, Any], step_dicts: list) -> Dict[str, List[Any]]:
        # Priority 1: explicit legal_values_for_pending_slots from governance metadata
        explicit = meta.get("legal_values_for_pending_slots")
        if isinstance(explicit, dict):
            return {
                str(k): list(v) if isinstance(v, list) else [v]
                for k, v in explicit.items()
            }
        # Priority 2: extract from trace steps (e.g. clarification steps carry options)
        result: Dict[str, List[Any]] = {}
        for step in step_dicts:
            if step.get("step_type") not in ("clarification", "parameter_negotiation_required",
                                              "input_completion_required", "action_readiness_blocked"):
                continue
            output = step.get("output_summary") if isinstance(step.get("output_summary"), dict) else {}
            target = output.get("target_field") or output.get("awaiting_slot") or output.get("missing_slot") or ""
            options = output.get("options") or output.get("legal_values") or []
            if target and options:
                result[str(target)] = list(options) if isinstance(options, list) else [options]
        return result

    @staticmethod
    def _str_list(value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(item) for item in value]
        return []

    @staticmethod
    def _truncate(value: Any, limit: int = 200) -> str:
        text = str(value or "")
        return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."
