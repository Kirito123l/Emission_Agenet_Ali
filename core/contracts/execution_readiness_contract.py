from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from core.analytical_objective import ConversationalStance
from core.contracts.base import ContractContext, ContractInterception
from core.contracts.split_contract_utils import SplitContractSupport
from core.router import RouterResponse


class ExecutionReadinessContract(SplitContractSupport):
    """Wave 2 split contract for stance-dependent execution readiness."""

    name = "execution_readiness"

    def __init__(self, inner_router: Any = None, ao_manager: Any = None, runtime_config: Any = None):
        super().__init__(inner_router=inner_router, ao_manager=ao_manager, runtime_config=runtime_config)

    async def before_turn(self, context: ContractContext) -> ContractInterception:
        if not getattr(self.runtime_config, "enable_contract_split", False):
            return ContractInterception()
        state = context.state_snapshot
        oasc_state = dict(context.metadata.get("oasc") or {})
        classification = oasc_state.get("classification")
        current_ao = self.ao_manager.get_current_ao() if self.ao_manager is not None else None
        if state is None or classification is None or current_ao is None:
            return ContractInterception()
        tool_intent = context.metadata.get("tool_intent") or getattr(current_ao, "tool_intent", None)
        tool_name = str(getattr(tool_intent, "resolved_tool", "") or "").strip()
        if not tool_name:
            return ContractInterception()
        tool_spec = self._get_tool_spec(tool_name)
        if not tool_spec:
            return ContractInterception()

        snapshot = self._initial_snapshot(
            tool_name=tool_name,
            current_ao=current_ao,
            pending_state=self._get_split_pending_state(current_ao),
            classification=classification,
        )
        stage1_filled = self._run_stage1(state, snapshot)
        active_required_slots = list(dict.fromkeys(tool_spec.get("required_slots") or []))
        missing_required_stage1 = self._missing_slots(snapshot, active_required_slots)
        stage2_meta = dict(context.metadata.get("stage2_telemetry") or {})
        llm_payload = context.metadata.get("stage2_payload") if isinstance(context.metadata.get("stage2_payload"), dict) else None
        if llm_payload is None and missing_required_stage1 and self._stage2_available():
            llm_payload, stage2_meta = await self._run_stage2_llm_with_telemetry(
                user_message=context.effective_user_message,
                state=state,
                current_ao=current_ao,
                tool_name=tool_name,
                snapshot=snapshot,
                tool_spec=tool_spec,
                classification=classification,
            )
            context.metadata["stage2_payload"] = llm_payload
            context.metadata["stage2_telemetry"] = stage2_meta
        if llm_payload is not None:
            snapshot = self._merge_stage2_snapshot(snapshot, self._stage2_snapshot_payload(llm_payload))

        snapshot, normalizations, rejected_slots = self._run_stage3(
            tool_name=tool_name,
            snapshot=snapshot,
            tool_spec=tool_spec,
            suppress_defaults_for=[],
        )
        missing_required = self._missing_slots(snapshot, active_required_slots)
        no_default_optionals = self._get_unfilled_optionals_without_default(snapshot, tool_spec)
        stance_value = getattr(getattr(current_ao, "stance", None), "value", None) or "directive"
        branch = stance_value if stance_value in {"directive", "deliberative", "exploratory"} else "directive"

        if branch == ConversationalStance.EXPLORATORY.value:
            telemetry = self._telemetry(
                tool_name=tool_name,
                decision="clarify",
                branch=branch,
                pending_slot="scope",
                stage1_filled=stage1_filled,
                stage2_meta=stage2_meta,
                normalizations=normalizations,
                rejected_slots=rejected_slots,
                runtime_defaults=[],
            )
            return ContractInterception(
                proceed=False,
                response=RouterResponse(
                    text="您想先比较哪类交通排放分析目标？可以指定排放因子、微观排放、宏观排放或扩散影响。",
                    trace_friendly=[{"step_type": "clarification", "summary": "scope framing"}],
                ),
                metadata={"clarification": {"telemetry": telemetry}},
            )

        if missing_required or rejected_slots:
            pending_slot = (missing_required or rejected_slots or [None])[0]
            question = self._build_question(
                tool_name=tool_name,
                snapshot=snapshot,
                missing_slots=missing_required,
                rejected_slots=rejected_slots,
                llm_question=stage2_meta.get("stage2_clarification_question"),
            )
            self._persist_split_pending(current_ao, tool_name, pending_slot, snapshot)
            telemetry = self._telemetry(
                tool_name=tool_name,
                decision="clarify",
                branch=branch,
                pending_slot=pending_slot,
                stage1_filled=stage1_filled,
                stage2_meta=stage2_meta,
                normalizations=normalizations,
                rejected_slots=rejected_slots,
                runtime_defaults=[],
            )
            return ContractInterception(
                proceed=False,
                response=RouterResponse(
                    text=question,
                    trace_friendly=[{"step_type": "clarification", "summary": question}],
                ),
                metadata={"clarification": {"telemetry": telemetry}},
            )

        if branch == ConversationalStance.DELIBERATIVE.value and no_default_optionals:
            pending_slot = no_default_optionals[0]
            self._persist_split_pending(current_ao, tool_name, pending_slot, snapshot)
            question = await self._build_probe_question(
                tool_name=tool_name,
                snapshot=snapshot,
                slot_name=pending_slot,
                current_ao=current_ao,
            )
            telemetry = self._telemetry(
                tool_name=tool_name,
                decision="clarify",
                branch=branch,
                pending_slot=pending_slot,
                stage1_filled=stage1_filled,
                stage2_meta=stage2_meta,
                normalizations=normalizations,
                rejected_slots=rejected_slots,
                runtime_defaults=[],
            )
            return ContractInterception(
                proceed=False,
                response=RouterResponse(
                    text=question,
                    trace_friendly=[{"step_type": "clarification", "summary": question}],
                ),
                metadata={"clarification": {"telemetry": telemetry}},
            )

        runtime_defaults = ["model_year"] if tool_name == "query_emission_factors" and self._snapshot_missing_value(snapshot, "model_year") else []
        telemetry = self._telemetry(
            tool_name=tool_name,
            decision="proceed",
            branch=branch,
            pending_slot=None,
            stage1_filled=stage1_filled,
            stage2_meta=stage2_meta,
            normalizations=normalizations,
            rejected_slots=rejected_slots,
            runtime_defaults=runtime_defaults,
        )
        return ContractInterception(
            metadata={
                "clarification": {
                    "telemetry": telemetry,
                    "direct_execution": {
                        "tool_name": tool_name,
                        "parameter_snapshot": copy.deepcopy(snapshot),
                        "confirm_first_detected": False,
                        "trigger_mode": "fresh",
                        "runtime_defaults_allowed": runtime_defaults,
                    },
                }
            }
        )

    async def after_turn(self, context: ContractContext, result: RouterResponse) -> None:
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
            "split": True,
            "final_decision": telemetry.get("final_decision"),
            "tool_name": telemetry.get("tool_name"),
        }
        current_ao = self.ao_manager.get_current_ao() if self.ao_manager is not None else None
        if current_ao is not None and telemetry.get("final_decision") == "proceed":
            pending = dict(getattr(current_ao, "metadata", {}).get("execution_readiness") or {})
            pending["pending"] = False
            current_ao.metadata["execution_readiness"] = pending

    def _telemetry(
        self,
        *,
        tool_name: str,
        decision: str,
        branch: str,
        pending_slot: Optional[str],
        stage1_filled: List[str],
        stage2_meta: Dict[str, Any],
        normalizations: List[Dict[str, Any]],
        rejected_slots: List[str],
        runtime_defaults: List[str],
    ) -> Dict[str, Any]:
        return {
            "turn": self._current_turn_index(),
            "triggered": True,
            "trigger_mode": "split",
            "classification_at_trigger": None,
            "stage1_filled_slots": list(stage1_filled),
            "stage2_called": bool(stage2_meta.get("stage2_called")),
            "stage2_latency_ms": stage2_meta.get("stage2_latency_ms"),
            "stage2_missing_required": list(stage2_meta.get("stage2_missing_required") or []),
            "stage2_clarification_question": stage2_meta.get("stage2_clarification_question"),
            "stage2_response_chars": stage2_meta.get("stage2_response_chars"),
            "stage2_intent_chars": stage2_meta.get("stage2_intent_chars"),
            "stage2_stance_chars": stage2_meta.get("stage2_stance_chars"),
            "stage2_prompt_tokens": stage2_meta.get("stage2_prompt_tokens"),
            "stage2_completion_tokens": stage2_meta.get("stage2_completion_tokens"),
            "stage2_raw_response_truncated": stage2_meta.get("stage2_raw_response_truncated"),
            "stage3_rejected_slots": list(rejected_slots),
            "stage3_normalizations": [dict(item) for item in normalizations],
            "final_decision": decision,
            "proceed_mode": None,
            "ao_id": getattr(self.ao_manager.get_current_ao(), "ao_id", None) if self.ao_manager else None,
            "tool_name": tool_name,
            "execution_readiness": {
                "readiness_branch": branch,
                "readiness_decision": decision,
                "pending_slot": pending_slot,
                "runtime_defaults_applied": list(runtime_defaults),
            },
        }

    @staticmethod
    def _snapshot_missing_value(snapshot: Dict[str, Any], slot_name: str) -> bool:
        payload = snapshot.get(slot_name)
        if not isinstance(payload, dict):
            return True
        if payload.get("source") == "rejected":
            return True
        return payload.get("value") in (None, "", [])

    @staticmethod
    def _get_split_pending_state(ao: Any) -> Dict[str, Any]:
        if ao is None or not isinstance(getattr(ao, "metadata", None), dict):
            return {}
        payload = ao.metadata.get("execution_readiness")
        return dict(payload) if isinstance(payload, dict) else {}

    @staticmethod
    def _persist_split_pending(ao: Any, tool_name: str, pending_slot: Optional[str], snapshot: Dict[str, Any]) -> None:
        if ao is None or not isinstance(getattr(ao, "metadata", None), dict):
            return
        ao.metadata["execution_readiness"] = {
            "pending": bool(pending_slot),
            "tool_name": tool_name,
            "pending_slot": pending_slot,
            "missing_slots": [pending_slot] if pending_slot else [],
            "parameter_snapshot": copy.deepcopy(snapshot),
        }
