from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Any, Dict, Optional

from config import get_config
from core.analytical_objective import (
    CanonicalExecutionDecision,
    ConversationalStance,
    StanceConfidence,
)
from core.ao_manager import AOManager
from core.constraint_violation_writer import (
    ConstraintViolationWriter,
    normalize_cross_constraint_violation,
)
from core.context_store import SessionContextStore
from core.contracts import (
    ClarificationContract,
    ContractContext,
    DependencyContract,
    ExecutionReadinessContract,
    IntentResolutionContract,
    OASCContract,
    StanceResolutionContract,
)
from core.contracts.decision_validator import validate_decision
from services.cross_constraints import get_cross_constraint_validator
from core.reply import LLMReplyError, LLMReplyParser, LLMReplyTimeout, ReplyContextBuilder
from core.router import RouterResponse, UnifiedRouter
from core.stance_resolver import StanceResolution, StanceResolver
from core.task_state import TaskStage, TaskState
from core.tool_dependencies import get_tool_provides
from services.config_loader import ConfigLoader

logger = logging.getLogger(__name__)


# ── Phase 6.1: minimal executor wrapper for idempotency ──────────────────

class _IdempotencyAwareExecutor:
    """Wraps ToolExecutor to gate all execute() calls with idempotency check."""

    def __init__(self, delegate: Any, governed_router: Any):
        self._delegate = delegate
        self._gr = governed_router

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    async def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        file_path: Optional[str] = None,
    ) -> Dict:
        gr = self._gr

        # Phase 6.E.2: canonical execution state check (intra-AO duplicate suppression)
        canonical_enabled = bool(getattr(gr.runtime_config, "enable_canonical_execution_state", False))
        if canonical_enabled:
            current_ao = gr.ao_manager.get_current_ao()
            if current_ao is not None:
                canonical = gr.ao_manager.check_canonical_execution_state(
                    current_ao, proposed_tool=tool_name,
                )
                if canonical.decision in (
                    CanonicalExecutionDecision.SKIP_COMPLETED_STEP,
                    CanonicalExecutionDecision.ADVANCE_TO_PENDING,
                ):
                    logger.info(
                        "Canonical state skip: %s (decision=%s reason=%s pending_next=%s)",
                        tool_name, canonical.decision.value, canonical.reason,
                        canonical.pending_next_tool,
                    )
                    # Canonical skip is NOT a tool success — it is a governance
                    # decision to suppress duplicate execution.  The result must
                    # carry canonical_skip=True so OASC can skip recording it,
                    # and must NOT carry success=True (no tool executed).
                    return {
                        "success": False,
                        "message": (
                            f"canonical skip — {tool_name} already {canonical.decision.value}"
                        ),
                        "summary": (
                            f"Canonical execution state skip: {tool_name} "
                            f"(matched step[{canonical.matched_step_index}], "
                            f"pending_next={canonical.pending_next_tool})"
                        ),
                        "canonical_skip": True,
                        "canonical_decision": canonical.decision.value,
                        "pending_next_tool": canonical.pending_next_tool,
                    }

        if not bool(getattr(gr.runtime_config, "enable_execution_idempotency", False)):
            return await self._delegate.execute(tool_name, arguments, file_path=file_path)

        # Phase 6.1: build effective-args fingerprint from the same source the executor uses.
        # Apply executor standardization to arguments (same as ToolExecutor does)
        # so the fingerprint reflects post-standardization effective parameters.
        effective_args = dict(arguments or {})
        try:
            std_engine = getattr(self._delegate, "standardization_engine", None)
            if std_engine is not None:
                effective_args = await std_engine.standardize(tool_name, effective_args)
        except Exception:
            pass  # standardization failed — use raw args
        if file_path:
            effective_args["file_path"] = str(file_path)
        # Also enrich from AO parameters_used for sparse args
        current_ao = gr.ao_manager.get_current_ao()
        if current_ao is not None and hasattr(current_ao, "parameters_used"):
            for k, v in current_ao.parameters_used.items():
                if k not in effective_args or effective_args.get(k) is None:
                    effective_args[k] = v

        # Use the user message from the current turn context
        user_message = getattr(gr, '_last_user_message', '') or ''
        idem = gr.ao_manager.check_execution_idempotency(
            current_ao,
            proposed_tool=tool_name,
            proposed_args=effective_args,
            user_message=user_message,
        )
        if idem.decision.value == "exact_duplicate":
            if idem.matched_result_ref:
                ref = str(idem.matched_result_ref)
                artifact_type, _, label = ref.partition(":")
                store = gr.inner_router._ensure_context_store()
                if store.has_result(artifact_type, label=label or None):
                    logger.info(
                        "Idempotency skip: %s (matched AO=%s turn=%s)",
                        tool_name, idem.matched_ao_id, idem.matched_turn,
                    )
                    return {
                        "success": True,
                        "message": f"idempotent skip — cached result from turn {idem.matched_turn}",
                        "summary": f"Idempotent skip: {tool_name} already executed in {idem.matched_ao_id}",
                        "idempotent_skip": True,
                        "matched_ao_id": idem.matched_ao_id,
                        "matched_turn": idem.matched_turn,
                    }
                logger.warning(
                    "Idempotency cache miss for %s (ref=%s), falling through",
                    tool_name, ref,
                )
            # Cache miss or no result_ref — fall through to normal execution
        elif idem.decision.value != "no_duplicate":
            logger.info(
                "Idempotency decision: %s for %s (reason: %s)",
                idem.decision.value, tool_name, idem.decision_reason,
            )

        return await self._delegate.execute(tool_name, arguments, file_path=file_path)


class GovernedRouter:

    def __init__(self, session_id: str, memory_storage_dir: Optional[str | Path] = None):
        self.session_id = session_id
        self.runtime_config = get_config()
        self.inner_router = UnifiedRouter(
            session_id=session_id,
            memory_storage_dir=memory_storage_dir,
        )
        # Phase 6.1: wrap executor for idempotency gating
        self.inner_router.executor = _IdempotencyAwareExecutor(
            self.inner_router.executor, self,
        )
        self._last_user_message = ""
        self.ao_manager = AOManager(self.inner_router.memory.fact_memory)
        self.constraint_violation_writer = self._build_constraint_violation_writer()
        self.reply_context_builder = ReplyContextBuilder()
        self._reply_parser = LLMReplyParser(timeout_seconds=20.0)
        self.stance_resolver = StanceResolver(runtime_config=self.runtime_config)
        self.oasc_contract = OASCContract(
            inner_router=self.inner_router,
            ao_manager=self.ao_manager,
            runtime_config=self.runtime_config,
        )
        self.dependency_contract = DependencyContract()
        self._build_contracts()

    def _build_contracts(self) -> None:
        self.contract_split_enabled = bool(getattr(self.runtime_config, "enable_contract_split", False))
        self.clarification_contract = None
        self.intent_resolution_contract = None
        self.stance_resolution_contract = None
        self.execution_readiness_contract = None
        self.contracts = [self.oasc_contract]
        if self.contract_split_enabled:
            if bool(getattr(self.runtime_config, "enable_split_intent_contract", True)):
                self.intent_resolution_contract = IntentResolutionContract(
                    inner_router=self.inner_router,
                    ao_manager=self.ao_manager,
                    runtime_config=self.runtime_config,
                )
                self.contracts.append(self.intent_resolution_contract)
            if bool(getattr(self.runtime_config, "enable_split_stance_contract", True)):
                self.stance_resolution_contract = StanceResolutionContract(
                    inner_router=self.inner_router,
                    ao_manager=self.ao_manager,
                    runtime_config=self.runtime_config,
                )
                self.contracts.append(self.stance_resolution_contract)
            if bool(getattr(self.runtime_config, "enable_split_readiness_contract", True)):
                self.execution_readiness_contract = ExecutionReadinessContract(
                    inner_router=self.inner_router,
                    ao_manager=self.ao_manager,
                    runtime_config=self.runtime_config,
                )
                self.contracts.append(self.execution_readiness_contract)
        else:
            self.clarification_contract = ClarificationContract(
                inner_router=self.inner_router,
                ao_manager=self.ao_manager,
                runtime_config=self.runtime_config,
            )
            self.contracts.append(self.clarification_contract)
        self.contracts.append(self.dependency_contract)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner_router, name)

    async def chat(
        self,
        user_message: str,
        file_path: Optional[str] = None,
        trace: Optional[Dict[str, Any]] = None,
    ) -> RouterResponse:
        self._last_user_message = str(user_message or "")
        context = ContractContext(
            user_message=user_message,
            file_path=str(file_path) if file_path else None,
            trace=trace,
        )

        result: Optional[RouterResponse] = None
        for contract in self.contracts:
            interception = await contract.before_turn(context)
            if interception.user_message_override is not None:
                context.user_message_override = interception.user_message_override
            if interception.metadata:
                context.metadata.update(interception.metadata)
            if (
                getattr(contract, "name", None) == "oasc"
                and self.contract_split_enabled
                and not bool(getattr(self.runtime_config, "enable_split_stance_contract", True))
            ):
                stance_metadata = self._apply_stance_resolution(context)
                if stance_metadata:
                    context.metadata["stance"] = stance_metadata
            if not interception.proceed:
                result = interception.response or RouterResponse(text="")
                break

        # ── Phase 8.1.4c: record PCM advisory and projected chain traces ──
        if trace is not None:
            # PCM advisory injected (from clarification contract)
            clarification_state = dict(context.metadata.get("clarification") or {})
            pcm_telemetry = clarification_state.get("telemetry")
            if isinstance(pcm_telemetry, dict):
                pcm_advisory = pcm_telemetry.get("pcm_advisory")
                if isinstance(pcm_advisory, dict):
                    trace.setdefault("steps", []).append({
                        "step_type": "pcm_advisory_injected",
                        "action": "pcm_advisory_stage2_injection",
                        "input_summary": {
                            "source": "clarification_contract",
                            "collection_mode_active": pcm_advisory.get("collection_mode_active"),
                        },
                        "output_summary": {
                            "unfilled_optionals": pcm_advisory.get("unfilled_optionals_without_default", []),
                            "runtime_defaults_available": list(
                                (pcm_advisory.get("runtime_defaults_available") or {}).keys()
                            ),
                            "suggested_probe_slot": pcm_advisory.get("suggested_probe_slot"),
                        },
                    })

            # Projected chain generated (from intent resolution contract)
            tool_intent = context.metadata.get("tool_intent")
            if isinstance(tool_intent, dict) or hasattr(tool_intent, "projected_chain"):
                chain = (
                    list(tool_intent.get("projected_chain") or [])
                    if isinstance(tool_intent, dict)
                    else list(getattr(tool_intent, "projected_chain", []) or [])
                )
                resolved_tool = (
                    tool_intent.get("resolved_tool")
                    if isinstance(tool_intent, dict)
                    else getattr(tool_intent, "resolved_tool", None)
                )
                resolved_by = (
                    tool_intent.get("resolved_by")
                    if isinstance(tool_intent, dict)
                    else getattr(tool_intent, "resolved_by", None)
                )
                if chain:
                    trace.setdefault("steps", []).append({
                        "step_type": "projected_chain_generated",
                        "action": "chain_resolution",
                        "output_summary": {
                            "chain": chain,
                            "chain_length": len(chain),
                            "resolved_tool": resolved_tool,
                            "source": resolved_by or "unknown",
                        },
                    })
                    context.metadata["projected_chain"] = {
                        "chain": chain,
                        "chain_length": len(chain),
                        "source": resolved_by or "unknown",
                    }
        # ── End Phase 8.1.4c contract traces ────────────────────────────

        # Phase 6.1: idempotency pre-check before any tool dispatch
        if result is None and bool(getattr(self.runtime_config, "enable_execution_idempotency", False)):
            idem_block = self._check_pre_dispatch_idempotency(context)
            if idem_block is not None:
                result = idem_block
                context.router_executed = True

        if result is None:
            if bool(getattr(get_config(), "enable_llm_decision_field", False)):
                decision_result = self._consume_decision_field(context, trace)
                if decision_result is not None:
                    result = decision_result
                    context.router_executed = True
            if result is None:
                result = await self._maybe_execute_from_snapshot(context)
                if result is None:
                    clarification_state = dict(context.metadata.get("clarification") or {})
                    telemetry = clarification_state.get("telemetry")
                    if isinstance(telemetry, dict) and telemetry.get("final_decision") == "proceed":
                        telemetry["proceed_mode"] = "fallback"
                        clarification_state["telemetry"] = telemetry
                        context.metadata["clarification"] = clarification_state
                    result = await self.inner_router.chat(
                        user_message=context.effective_user_message,
                        file_path=file_path,
                        trace=trace,
                    )
                    context.router_executed = True
                else:
                    context.router_executed = True

        self._record_constraint_violations_from_trace(
            result,
            trace,
            source_turn=self._current_turn_index() or self._current_turn_index(pre_call=True),
        )

        for contract in self.contracts:
            await contract.after_turn(context, result)

        if bool(getattr(get_config(), "enable_reply_pipeline", True)):
            reply_context_builder = self.__dict__.get("reply_context_builder") or ReplyContextBuilder()
            reply_context = reply_context_builder.build(
                user_message=context.effective_user_message,
                router_text=result.text,
                trace_steps=self._trace_steps(result, trace),
                ao_manager=self.__dict__.get("ao_manager"),
                violation_writer=self.__dict__.get("constraint_violation_writer"),
                context_store=self._context_store_for_writer(),
                governance_metadata=context.metadata,
            )
            original_text = result.text
            result.text, reply_metadata = await self._generate_final_reply(reply_context)
            self._record_reply_generation_trace(
                result,
                trace,
                metadata=reply_metadata,
                router_text=original_text,
                final_text=result.text,
            )

        return result

    async def _generate_final_reply(self, ctx: Any) -> tuple[str, Dict[str, Any]]:
        runtime_config = self.__dict__.get("runtime_config") or get_config()
        if not bool(getattr(runtime_config, "enable_llm_reply_parser", True)):
            return ctx.router_text, {"mode": "legacy_render"}
        parser = self.__dict__.get("_reply_parser")
        if parser is None:
            return ctx.router_text, {
                "mode": "legacy_render",
                "reason": "reply_parser_uninitialized",
            }
        try:
            return await parser.parse(ctx)
        except (LLMReplyTimeout, LLMReplyError) as exc:
            logger.warning(
                "LLM reply parser failed (%s: %s), keeping router_text",
                type(exc).__name__,
                exc,
            )
            return ctx.router_text, {
                "mode": "fallback",
                "fallback": True,
                "reason": f"{type(exc).__name__}: {exc}",
            }

    @staticmethod
    def _record_reply_generation_trace(
        result: RouterResponse,
        trace: Optional[Dict[str, Any]],
        *,
        metadata: Dict[str, Any],
        router_text: str,
        final_text: str,
    ) -> None:
        trace_target = result.trace if isinstance(result.trace, dict) else trace
        if not isinstance(trace_target, dict):
            return
        trace_target.setdefault("steps", []).append(
            {
                "step_type": "reply_generation",
                "action": "llm_reply_parser",
                "input_summary": {
                    "router_text_chars": len(router_text or ""),
                },
                "output_summary": {
                    **dict(metadata or {}),
                    "reply_chars": len(final_text or ""),
                },
                "reasoning": "LLM reply parser generated final reply"
                if (metadata or {}).get("mode") == "llm"
                else "Router-rendered reply kept as legacy/fallback output",
            }
        )
        if result.trace is None:
            result.trace = trace_target
        if isinstance(result.trace_friendly, list):
            entry = {
                "title": "回复生成 / Reply Generation",
                "description": (
                    "LLM reply parser generated final reply"
                    if (metadata or {}).get("mode") == "llm"
                    else "Router-rendered reply kept as legacy/fallback output"
                ),
                "status": "warning" if (metadata or {}).get("fallback") else "success",
                "type": "reply_generation",
                "step_type": "reply_generation",
            }
            reply_latency = (metadata or {}).get("latency_ms")
            if reply_latency is not None:
                entry["latency_ms"] = int(reply_latency)
            result.trace_friendly.append(entry)

    def _build_constraint_violation_writer(self) -> ConstraintViolationWriter:
        return ConstraintViolationWriter(
            self.ao_manager,
            self._context_store_for_writer(),
        )

    def _context_store_for_writer(self) -> SessionContextStore:
        if hasattr(self.inner_router, "_ensure_context_store"):
            return self.inner_router._ensure_context_store()
        context_store = getattr(self.inner_router, "context_store", None)
        if context_store is None:
            context_store = SessionContextStore()
            setattr(self.inner_router, "context_store", context_store)
        return context_store

    def _record_constraint_violations_from_trace(
        self,
        result: RouterResponse,
        trace: Optional[Dict[str, Any]],
        *,
        source_turn: int,
    ) -> None:
        steps = self._trace_steps(result, trace)
        if not steps:
            return

        seen = set()
        for severity, payload, timestamp in self._iter_constraint_violation_events(steps):
            try:
                record = normalize_cross_constraint_violation(
                    payload,
                    severity=severity,
                    source_turn=source_turn,
                    timestamp=timestamp,
                )
            except (TypeError, ValueError):
                logger.debug("Skipped malformed constraint violation payload: %s", payload)
                continue

            signature = (
                record.violation_type,
                record.severity,
                tuple(sorted((key, repr(value)) for key, value in record.involved_params.items())),
                record.source_turn,
            )
            if signature in seen:
                continue
            seen.add(signature)
            self.constraint_violation_writer.record(record)

    @staticmethod
    def _trace_steps(
        result: RouterResponse,
        trace: Optional[Dict[str, Any]],
    ) -> list[Dict[str, Any]]:
        result_trace = getattr(result, "trace", None)
        if isinstance(result_trace, dict) and isinstance(result_trace.get("steps"), list):
            return [item for item in result_trace.get("steps", []) if isinstance(item, dict)]
        if isinstance(trace, dict) and isinstance(trace.get("steps"), list):
            return [item for item in trace.get("steps", []) if isinstance(item, dict)]
        return []

    def _iter_constraint_violation_events(
        self,
        steps: list[Dict[str, Any]],
    ) -> list[tuple[str, Dict[str, Any], Optional[str]]]:
        events: list[tuple[str, Dict[str, Any], Optional[str]]] = []
        for step in steps:
            step_type = str(step.get("step_type") or "")
            timestamp = str(step.get("timestamp")) if step.get("timestamp") is not None else None
            if step_type == "cross_constraint_violation":
                for payload in self._extract_step_constraint_payloads(step):
                    events.append(("reject", payload, timestamp))
                continue
            if step_type == "cross_constraint_warning":
                for payload in self._extract_step_constraint_payloads(step):
                    events.append(("warn", payload, timestamp))
                continue

            for record in list(step.get("standardization_records") or []):
                if not isinstance(record, dict):
                    continue
                record_type = str(record.get("record_type") or record.get("strategy") or "")
                if record_type == "cross_constraint_violation":
                    events.append(("negotiate", record, timestamp))
                elif record_type == "cross_constraint_warning":
                    events.append(("warn", record, timestamp))
        return events

    @staticmethod
    def _extract_step_constraint_payloads(step: Dict[str, Any]) -> list[Dict[str, Any]]:
        payloads: list[Dict[str, Any]] = []
        for container_name in ("input_summary", "output_summary"):
            container = step.get(container_name)
            if not isinstance(container, dict):
                continue
            for key in ("cross_constraint_violations", "violations", "warnings"):
                values = container.get(key)
                if isinstance(values, list):
                    payloads.extend(item for item in values if isinstance(item, dict))

        for record in list(step.get("standardization_records") or []):
            if not isinstance(record, dict):
                continue
            nested = record.get("constraint_violation")
            payloads.append(nested if isinstance(nested, dict) else record)
        return payloads

    # ── Phase 6.1: pre-dispatch idempotency check ─────────────────────────

    def _check_pre_dispatch_idempotency(
        self, context: ContractContext
    ) -> Optional[RouterResponse]:
        """Check idempotency BEFORE any tool dispatch.

        When a short parameter-like message arrives after an AO just completed
        with the same tool, and the effective args haven't changed, block
        re-execution and return a cached/synthesized response.
        """
        current_ao = self.ao_manager.get_current_ao()
        if current_ao is None:
            return None
        # Only fire when current AO is empty/new (no prior tool calls in this AO)
        if list(getattr(current_ao, "tool_call_log", []) or []):
            return None

        user_message = context.effective_user_message or ""
        if not self.ao_manager._is_short_parameter_like(user_message):
            return None

        completed = self.ao_manager.get_completed_aos()
        if not completed:
            return None
        most_recent = completed[-1]

        # Extract proposed tool from tool_intent metadata
        tool_intent = context.metadata.get("tool_intent")
        if tool_intent is None:
            tool_intent = getattr(current_ao, "tool_intent", None)
        proposed_tool = getattr(tool_intent, "resolved_tool", None) if tool_intent else None
        if not proposed_tool:
            return None

        # Check if completed AO executed the same tool
        prior_tools = {r.tool for r in getattr(most_recent, "tool_call_log", []) or [] if r.success}
        if proposed_tool not in prior_tools:
            return None

        # Build proposed effective args from AO state + context
        proposed_args: Dict[str, Any] = {}
        if context.file_path:
            proposed_args["file_path"] = str(context.file_path)
        for k, v in getattr(current_ao, "parameters_used", {}).items():
            if k not in proposed_args:
                proposed_args[k] = v
        # Also pull from completed AO's parameters_used for keys missing in current
        for k, v in getattr(most_recent, "parameters_used", {}).items():
            if k not in proposed_args:
                proposed_args[k] = v

        # Run idempotency check
        idem = self.ao_manager.check_execution_idempotency(
            current_ao,
            proposed_tool=proposed_tool,
            proposed_args=proposed_args,
            user_message=user_message,
        )
        if idem.decision.value != "exact_duplicate":
            return None

        # Build a blocking response — avoid re-execution
        logger.info(
            "Pre-dispatch idempotency block: %s for AO=%s (matched AO=%s turn=%s)",
            proposed_tool, getattr(current_ao, "ao_id", "?"),
            idem.matched_ao_id, idem.matched_turn,
        )
        return RouterResponse(
            text="",
            executed_tool_calls=[],
        )

    async def _maybe_execute_from_snapshot(self, context: ContractContext) -> Optional[RouterResponse]:
        clarification_state = dict(context.metadata.get("clarification") or {})
        direct_execution = clarification_state.get("direct_execution")
        telemetry = clarification_state.get("telemetry")
        if not isinstance(direct_execution, dict):
            return None

        tool_name = str(direct_execution.get("tool_name") or "").strip()
        snapshot = direct_execution.get("parameter_snapshot")
        allow_factor_year_default = bool(
            tool_name == "query_emission_factors"
            and str(direct_execution.get("trigger_mode") or "") == "fresh"
            and not bool(direct_execution.get("confirm_first_detected"))
        )
        runtime_defaults_allowed = [
            str(item)
            for item in list(direct_execution.get("runtime_defaults_allowed") or [])
            if str(item).strip()
        ]
        if "model_year" in runtime_defaults_allowed and tool_name == "query_emission_factors":
            allow_factor_year_default = True
        if not tool_name or not isinstance(snapshot, dict):
            return None

        response = await self._execute_from_snapshot(
            tool_name=tool_name,
            snapshot=snapshot,
            allow_factor_year_default=allow_factor_year_default,
            user_message=context.user_message,
            file_path=context.file_path,
            state_snapshot=context.state_snapshot,
            trace=context.trace,
        )
        if response is None:
            if isinstance(telemetry, dict):
                telemetry["proceed_mode"] = "fallback"
                clarification_state["telemetry"] = telemetry
                context.metadata["clarification"] = clarification_state
            return None

        self._retain_pending_followups_after_direct_execution(
            snapshot=snapshot,
            used_runtime_defaults=(
                ["model_year"]
                if allow_factor_year_default and self._snapshot_missing_value(snapshot, "model_year")
                else []
            ),
        )
        self._mark_parameter_collection_complete()
        if isinstance(telemetry, dict):
            telemetry["proceed_mode"] = "snapshot_direct"
            clarification_state["telemetry"] = telemetry
            context.metadata["clarification"] = clarification_state
        return response

    async def _execute_from_snapshot(
        self,
        *,
        tool_name: str,
        snapshot: Dict[str, Any],
        allow_factor_year_default: bool,
        user_message: str,
        file_path: Optional[str],
        state_snapshot: Optional[Any],
        trace: Optional[Dict[str, Any]],
    ) -> Optional[RouterResponse]:
        arguments = self._snapshot_to_tool_args(
            tool_name,
            snapshot,
            allow_factor_year_default=allow_factor_year_default,
        )
        if not isinstance(arguments, dict):
            return None

        # Phase 6.1: execution idempotency gate
        if bool(getattr(self.runtime_config, "enable_execution_idempotency", False)):
            current_ao = self.ao_manager.get_current_ao()
            effective_args = dict(arguments)
            if file_path:
                effective_args["file_path"] = str(file_path)
            if current_ao is not None and hasattr(current_ao, "parameters_used"):
                for k, v in current_ao.parameters_used.items():
                    if k not in effective_args or effective_args.get(k) is None:
                        effective_args[k] = v
            idem = self.ao_manager.check_execution_idempotency(
                current_ao,
                proposed_tool=tool_name,
                proposed_args=effective_args,
                user_message=user_message,
            )
            if idem.decision.value == "exact_duplicate":
                cached_response = self._build_idempotent_response(
                    idem, tool_name, user_message, file_path, trace
                )
                if cached_response is not None:
                    return cached_response
                logger.warning(
                    "Idempotency cache miss for %s (matched_result_ref=%s), falling through to execution",
                    tool_name, idem.matched_result_ref,
                )
            if idem.decision.value != "no_duplicate":
                if trace is not None:
                    trace.setdefault("steps", []).append({
                        "step_type": "idempotent_skip",
                        "decision": idem.decision.value,
                        "matched_ao_id": idem.matched_ao_id,
                        "matched_tool": idem.matched_tool,
                        "matched_turn": idem.matched_turn,
                        "proposed_fingerprint": idem.proposed_fingerprint,
                        "previous_fingerprint": idem.previous_fingerprint,
                        "decision_reason": idem.decision_reason,
                        "explicit_rerun_absent": idem.explicit_rerun_absent,
                    })

        self.inner_router._ensure_context_store().clear_current_turn()
        result = await self.inner_router.executor.execute(
            tool_name=tool_name,
            arguments=arguments,
            file_path=file_path,
        )
        if not bool(result.get("success")):
            return None

        self.inner_router._save_result_to_session_context(tool_name, result)

        tool_result = {
            "tool_call_id": f"clarification_contract_{tool_name}_{time.time_ns()}",
            "name": tool_name,
            "arguments": dict(
                arguments,
                **({"file_path": str(file_path)} if file_path and bool(getattr(self.runtime_config, "enable_execution_idempotency", False)) else {})
            ),
            "result": result,
        }

        state = state_snapshot or TaskState.initialize(
            user_message=user_message,
            file_path=file_path,
            memory_dict=self.inner_router.memory.get_fact_memory(),
            session_id=self.session_id,
        )
        state.stage = TaskStage.DONE
        state.user_message = user_message
        state.execution.selected_tool = tool_name
        state.execution.tool_results = [tool_result]
        state.execution.completed_tools = [tool_name]
        state.execution.available_results.update(get_tool_provides(tool_name))
        state.execution.last_error = None
        state._llm_response = None
        state._assembled_context = type("StateContext", (), {"messages": [{"content": user_message}]})()
        setattr(state, "_final_response_text", None)

        response = await self.inner_router._state_build_response(
            state,
            user_message,
            trace_obj=None,
        )
        if not result.get("success"):
            return None

        self.inner_router.memory.update(
            user_message=user_message,
            assistant_response=response.text,
            tool_calls=response.executed_tool_calls,
            file_path=file_path,
            file_analysis=(
                self.inner_router.memory.fact_memory.file_analysis
                if isinstance(self.inner_router.memory.fact_memory.file_analysis, dict)
                else None
            ),
        )

        if trace is not None:
            trace.setdefault("steps", []).append(
                {
                    "step_type": "tool_execution",
                    "action": "clarification_contract_snapshot_direct",
                    "output_summary": {
                        "tool_name": tool_name,
                        "arguments": dict(arguments),
                        "success": True,
                    },
                }
            )
            if response.trace is None:
                response.trace = trace
            elif isinstance(response.trace, dict):
                response.trace.setdefault("steps", []).extend(trace.get("steps") or [])
        return response

    def _build_idempotent_response(
        self,
        idem: Any,
        tool_name: str,
        user_message: str,
        file_path: Optional[str],
        trace: Optional[Dict[str, Any]],
    ) -> Optional[RouterResponse]:
        """Build a RouterResponse from a cached tool result for idempotent skip."""
        if not idem.matched_result_ref:
            return None
        ref = str(idem.matched_result_ref)
        artifact_type, _, label = ref.partition(":")
        store = self.inner_router._ensure_context_store()
        if not store.has_result(artifact_type, label=label or None):
            return None
        cached = store.get_by_type(artifact_type, label=label or None)
        if cached is None or not cached.data:
            return None

        tool_result = {
            "tool_call_id": f"idempotent_skip_{tool_name}_{time.time_ns()}",
            "name": tool_name,
            "arguments": {},
            "result": {
                "success": True,
                "message": "idempotent skip — cached result reused",
                "idempotent_skip": True,
            },
        }
        response = RouterResponse(
            text="",
            executed_tool_calls=[tool_result],
        )
        if trace is not None:
            trace.setdefault("steps", []).append({
                "step_type": "idempotent_skip",
                "action": tool_name,
                "output_summary": {
                    "tool_name": tool_name,
                    "cached_result_ref": idem.matched_result_ref,
                    "matched_turn": idem.matched_turn,
                },
            })
            response.trace = trace
        return response

    def _retain_pending_followups_after_direct_execution(
        self,
        *,
        snapshot: Dict[str, Any],
        used_runtime_defaults: list[str],
    ) -> None:
        if not used_runtime_defaults:
            return
        current_ao = self.ao_manager.get_current_ao()
        if current_ao is None or not isinstance(current_ao.metadata, dict):
            return
        clarification_state = current_ao.metadata.get("clarification_contract")
        if not isinstance(clarification_state, dict):
            return
        followup_slots = [
            str(item)
            for item in list(clarification_state.get("followup_slots") or [])
            if str(item).strip()
        ]
        pending_slots = [
            slot_name
            for slot_name in followup_slots
            if slot_name in used_runtime_defaults and self._snapshot_missing_value(snapshot, slot_name)
        ]
        if not pending_slots:
            return
        clarification_state["pending"] = True
        clarification_state["missing_slots"] = pending_slots
        current_ao.metadata["clarification_contract"] = clarification_state

    def _mark_parameter_collection_complete(self) -> None:
        if bool(getattr(self.runtime_config, "enable_contract_split", False)):
            return
        if not getattr(self.runtime_config, "enable_ao_first_class_state", True):
            return
        current_ao = self.ao_manager.get_current_ao()
        if current_ao is None:
            return
        parameter_state = getattr(current_ao, "parameter_state", None)
        if parameter_state is None:
            return
        parameter_state.collection_mode = False
        parameter_state.awaiting_slot = None
        parameter_state.probe_turn_count = 0
        parameter_state.probe_abandoned = False

    def _consume_decision_field(
        self,
        context: ContractContext,
        trace: Optional[Dict[str, Any]] = None,
    ) -> Optional[RouterResponse]:
        """Three-way decision field consumption (Step 1.11).

        Returns a RouterResponse for clarify/deliberate decisions, or None for
        proceed (which falls through to existing execution path).

        Phase 5.3 Round 3.2: A reconciler arbitrates across P1 (Stage 2 LLM),
        P2 (YAML stage 3), and P3 (readiness gate) before consumption.
        """
        stage2_payload = context.metadata.get("stage2_payload")
        decision = None
        if isinstance(stage2_payload, dict):
            decision = stage2_payload.get("decision")
        if not isinstance(decision, dict):
            clarification_state = dict(context.metadata.get("clarification") or {})
            telemetry = clarification_state.get("telemetry")
            if isinstance(telemetry, dict):
                decision = telemetry.get("stage2_decision")
        if not isinstance(decision, dict):
            return None

        # Build a minimal payload for validate_decision (it checks decision + missing_required)
        validation_payload = {"decision": decision}
        if isinstance(stage2_payload, dict):
            validation_payload["missing_required"] = stage2_payload.get("missing_required", [])
        is_valid, fallback_reason = validate_decision(validation_payload)
        if not is_valid:
            logger.debug("Decision field validation failed: %s — falling back", fallback_reason)
            return None

        # ── Phase 5.3 Round 3.2: A reconciler ──────────────────────────
        from core.contracts.reconciler import (
            build_p1_from_stage2_payload,
            build_p2_from_stage3_yaml,
            build_p3_from_readiness_gate,
            filter_stage2_missing_required,
            reconcile,
        )

        p1 = build_p1_from_stage2_payload(stage2_payload, is_valid=True)
        stage3_yaml = context.metadata.get("stage3_yaml")
        p2 = build_p2_from_stage3_yaml(stage3_yaml)
        # P3 may be at top-level (Q3 gate paths) or inside clarification (proceed path)
        readiness_gate = context.metadata.get("readiness_gate")
        if not isinstance(readiness_gate, dict):
            clarification_state = dict(context.metadata.get("clarification") or {})
            readiness_gate = clarification_state.get("readiness_gate")
        p3 = build_p3_from_readiness_gate(readiness_gate)

        tool_name = self._extract_tool_name_from_context(context) or p1.resolved_tool
        b_result = None
        if tool_name and p1.missing_required:
            b_result = filter_stage2_missing_required(tool_name, p1.missing_required)

        # ── Phase 8.1.4c: B validator filter trace ──────────────────────
        if b_result is not None and trace is not None:
            filter_payload = {
                "tool_name": tool_name,
                "original_missing_required": b_result.original_slots,
                "grounded_slots": b_result.grounded_slots,
                "dropped_slots": b_result.dropped_slots,
                "dropped_reasons": b_result.dropped_reasons,
                "is_contract_found": b_result.is_contract_found,
                "source": "stage2_missing_required",
            }
            trace.setdefault("steps", []).append({
                "step_type": "b_validator_filter",
                "action": "contract_grounding",
                "input_summary": {"source": "filter_stage2_missing_required", "tool_name": tool_name},
                "output_summary": filter_payload,
            })
            context.metadata["b_validator_filter"] = filter_payload
        # ── End B validator filter trace ────────────────────────────────

        # ── Phase 8.1.4c: reconciler invoked trace ──────────────────────
        if trace is not None:
            trace.setdefault("steps", []).append({
                "step_type": "reconciler_invoked",
                "action": "reconciler_enter",
                "input_summary": {
                    "p1_decision": p1.decision_value,
                    "p1_confidence": p1.decision_confidence,
                    "p1_f1_valid": p1.f1_valid,
                    "p1_missing_required": list(p1.missing_required),
                    "p2_missing_required": list(p2.get("missing_required") or []),
                    "p3_disposition": p3.disposition,
                    "b_result_present": b_result is not None,
                },
            })
        # ── End reconciler invoked trace ─────────────────────────────────

        reconciled = reconcile(p1, p2, p3, b_result=b_result, tool_name=tool_name)

        # Store reconciled decision in metadata for trace/debug
        context.metadata["reconciled_decision"] = {
            "decision_value": reconciled.decision_value,
            "reconciled_missing_required": reconciled.reconciled_missing_required,
            "clarification_question": reconciled.clarification_question,
            "deliberative_reasoning": reconciled.deliberative_reasoning,
            "reasoning": reconciled.reasoning,
            "source_trace": reconciled.source_trace,
            "applied_rule_id": reconciled.applied_rule_id,
        }

        value = reconciled.decision_value
        if not value:
            value = str(decision.get("value") or "").strip().lower()
        # ── End A reconciler block ─────────────────────────────────────

        # ── Phase 8.1.4c: reconciler proceed trace ──────────────────────
        if value == "proceed" and trace is not None:
            trace.setdefault("steps", []).append({
                "step_type": "reconciler_proceed",
                "action": "reconciler_decision",
                "output_summary": {
                    "decision_value": value,
                    "applied_rule_id": reconciled.applied_rule_id,
                    "reasoning": reconciled.reasoning,
                },
                "confidence": 1.0,
            })
        # ── End reconciler proceed trace ─────────────────────────────────

        if value == "proceed":
            # Cross-constraint preflight (design §5.2):
            # validate parameter combination before allowing execution.
            # On violation → inject ConstraintViolation into prior_violations
            # and return a RouterResponse describing the violation (no fall through).
            snapshot = self._extract_snapshot_from_context(context)
            if snapshot and not getattr(
                self.runtime_config, "enable_cross_constraint_validation", True
            ):
                if trace is not None:
                    trace.setdefault("steps", []).append({
                        "step_type": "cross_constraint_check_skipped",
                        "action": "cross_constraint_disabled",
                        "output_summary": {"reason": "ENABLE_CROSS_CONSTRAINT_VALIDATION=false"},
                        "reasoning": "Cross-constraint validation disabled — skipping violation check in reconciler proceed path",
                    })
            elif snapshot:
                tool_name = self._extract_tool_name_from_context(context) or ""
                validator = get_cross_constraint_validator()
                cc_result = validator.validate(
                    snapshot,
                    tool_name=tool_name or None,
                    context={"user_message": context.effective_user_message},
                )
                if cc_result.violations:
                    # Record violation for next turn's Stage 2 LLM feedback
                    for v in cc_result.violations:
                        try:
                            record = normalize_cross_constraint_violation(
                                v,
                                severity="reject",
                                source_turn=self._current_turn_index(),
                            )
                            self.constraint_violation_writer.record(record)
                        except (TypeError, ValueError):
                            logger.debug("Skipped malformed cross-constraint in proceed: %s", v)
                    # Build a user-facing violation description
                    violation_msgs = []
                    for v in cc_result.violations[:3]:
                        reason = getattr(v, "reason", None) or str(v)
                        violation_msgs.append(f"- {reason}")
                    violation_text = (
                        "参数组合存在冲突：\n" + "\n".join(violation_msgs)
                        + "\n\n请调整参数后重试。"
                    )
                    trace_friendly = [{"type": "cross_constraint_violation", "step_type": "cross_constraint_violation", "summary": violation_text[:200]}]
                    if trace is not None:
                        trace.setdefault("steps", []).append({
                            "step_type": "cross_constraint_violation",
                            "action": "decision_field_proceed_gate",
                            "output_summary": {"decision": "proceed", "violations": violation_msgs},
                        })
                    return RouterResponse(
                        text=violation_text,
                        executed_tool_calls=[],
                        trace_friendly=trace_friendly,
                        trace=trace,
                    )
                # Cross-constraint clean, fall through to execution
            return None  # Falls through to snapshot / inner router

        if value == "clarify":
            question = str(
                reconciled.clarification_question
                or decision.get("clarification_question")
                or ""
            ).strip()
            # Build a minimal question from reconciled missing_required if LLM gave none
            if not question and reconciled.reconciled_missing_required:
                missing_names = "、".join(reconciled.reconciled_missing_required)
                question = f"请提供以下必需参数：{missing_names}"
            if not question:
                return None
            trace_friendly = [{"type": "clarification", "step_type": "clarification", "summary": question}]
            if trace is not None:
                trace.setdefault("steps", []).append({
                    "step_type": "decision_field_clarify",
                    "action": "llm_decision_field",
                    "output_summary": {
                        "decision": value,
                        "question": question,
                        "applied_rule_id": reconciled.applied_rule_id,
                    },
                })
            return RouterResponse(
                text=question,
                executed_tool_calls=[],
                trace_friendly=trace_friendly,
                trace=trace,
            )

        if value == "deliberate":
            reasoning = str(
                reconciled.deliberative_reasoning
                or decision.get("reasoning")
                or ""
            ).strip()
            if not reasoning:
                return None
            trace_friendly = [{"type": "clarification", "step_type": "clarification", "summary": reasoning}]
            if trace is not None:
                trace.setdefault("steps", []).append({
                    "step_type": "decision_field_deliberate",
                    "action": "llm_decision_field",
                    "output_summary": {"decision": value, "reasoning": reasoning[:200]},
                })
            return RouterResponse(
                text=reasoning,
                executed_tool_calls=[],
                trace_friendly=trace_friendly,
                trace=trace,
            )

        return None

    @staticmethod
    def _extract_snapshot_from_context(context: ContractContext) -> Dict[str, Any]:
        """Extract flattened parameter snapshot from contract metadata for cross-constraint validation."""
        # Try clarification contract metadata first
        clarification_state = dict(context.metadata.get("clarification") or {})
        direct = clarification_state.get("direct_execution")
        if isinstance(direct, dict) and isinstance(direct.get("parameter_snapshot"), dict):
            snapshot = direct["parameter_snapshot"]
            # Flatten: snapshot is {slot: {value, source, ...}} → {slot: value}
            return {
                str(k): v.get("value")
                for k, v in snapshot.items()
                if isinstance(v, dict) and v.get("value") is not None
            }
        return {}

    @staticmethod
    def _extract_tool_name_from_context(context: ContractContext) -> Optional[str]:
        clarification_state = dict(context.metadata.get("clarification") or {})
        direct = clarification_state.get("direct_execution")
        if isinstance(direct, dict):
            return str(direct.get("tool_name") or "")
        telemetry = clarification_state.get("telemetry")
        if isinstance(telemetry, dict):
            return str(telemetry.get("tool_name") or "")
        return None

    def _apply_stance_resolution(self, context: ContractContext) -> Dict[str, Any]:
        if not getattr(self.runtime_config, "enable_conversational_stance", True):
            return {}
        oasc_state = context.metadata.get("oasc") if isinstance(context.metadata.get("oasc"), dict) else {}
        classification = oasc_state.get("classification")
        if classification is None:
            return {}
        current_ao = self.ao_manager.get_current_ao()
        if current_ao is None:
            return {}
        if self.contract_split_enabled and not bool(
            getattr(self.runtime_config, "enable_split_stance_contract", True)
        ):
            turn = self._current_turn_index(pre_call=True)
            resolution = StanceResolution(
                stance=ConversationalStance.DIRECTIVE,
                confidence=StanceConfidence.LOW,
                evidence=["minimal_prior_directive"],
                resolved_by="minimal_prior_directive",
            )
            self._write_stance(current_ao, resolution, turn)
            return {
                "reversal_detected": False,
                "stance": resolution.stance.value,
                "resolved_by": resolution.resolved_by,
                "evidence": list(resolution.evidence),
            }
        classification_value = str(getattr(getattr(classification, "classification", None), "value", "") or "")
        turn = self._current_turn_index(pre_call=True)
        if classification_value in {"new_ao", "revision"}:
            fast = self.stance_resolver.resolve_fast(context.effective_user_message, current_ao)
            resolution = self.stance_resolver.resolve_with_llm_hint(fast, None)
            self._write_stance(current_ao, resolution, turn)
            return {
                "reversal_detected": False,
                "stance": resolution.stance.value,
                "resolved_by": resolution.resolved_by,
                "evidence": list(resolution.evidence),
            }
        if classification_value == "continuation":
            reversal = self.stance_resolver.detect_reversal(
                context.effective_user_message,
                current_ao.stance,
            )
            if reversal is None:
                return {"reversal_detected": False}
            evidence = self.stance_resolver.reversal_evidence(context.effective_user_message)
            resolution = StanceResolution(
                stance=reversal,
                confidence=current_ao.stance_confidence,
                evidence=[evidence or "user_reversal"],
                resolved_by="user_reversal",
            )
            self._write_stance(current_ao, resolution, turn)
            return {
                "reversal_detected": True,
                "stance": resolution.stance.value,
                "resolved_by": resolution.resolved_by,
                "evidence": list(resolution.evidence),
            }
        return {}

    @staticmethod
    def _write_stance(ao: Any, resolution: StanceResolution, turn: int) -> None:
        ao.stance = resolution.stance
        ao.stance_confidence = resolution.confidence
        ao.stance_resolved_by = resolution.resolved_by
        if not ao.stance_history or ao.stance_history[-1][1] != resolution.stance:
            ao.stance_history.append((turn, resolution.stance))

    def _current_turn_index(self, *, pre_call: bool = False) -> int:
        turn_counter = int(getattr(self.inner_router.memory, "turn_counter", 0) or 0)
        return turn_counter + 1 if pre_call else turn_counter

    @staticmethod
    def _snapshot_missing_value(snapshot: Dict[str, Any], slot_name: str) -> bool:
        payload = snapshot.get(slot_name)
        if not isinstance(payload, dict):
            return True
        if payload.get("source") == "rejected":
            return True
        return payload.get("value") in (None, "", [])

    @staticmethod
    def _snapshot_to_tool_args(
        tool_name: str,
        snapshot: Dict[str, Any],
        *,
        allow_factor_year_default: bool = False,
    ) -> Dict[str, Any]:
        from core.snapshot_coercion import apply_coercion
        from tools.contract_loader import get_tool_contract_registry

        def read(slot_name: str):
            payload = snapshot.get(slot_name)
            if not isinstance(payload, dict):
                return None
            source = str(payload.get("source") or "").strip().lower()
            value = payload.get("value")
            if source in {"missing", "rejected"}:
                return None
            if isinstance(value, str) and value.strip().lower() in {"missing", "unknown", "none", "n/a", "null", ""}:
                return None
            return value

        registry = get_tool_contract_registry()
        param_coercions = registry.get_type_coercion(tool_name)

        # Pre-processing: cross-parameter fallback — pollutant ← pollutants[0]
        # for dispersion / render_spatial_map (retained special hook).
        if tool_name in ("calculate_dispersion", "render_spatial_map"):
            if read("pollutant") is None and read("pollutants") is not None:
                pollutants_raw = read("pollutants")
                if isinstance(pollutants_raw, list) and pollutants_raw:
                    snapshot = dict(snapshot)
                    snapshot["pollutant"] = {"value": pollutants_raw[0], "source": "inferred"}

        args: Dict[str, Any] = {}
        for slot_name in sorted(snapshot):
            raw = read(slot_name)
            if raw is None:
                continue
            coercion = param_coercions.get(slot_name)
            if coercion is None:
                continue
            coerced = apply_coercion(coercion, raw, slot_name)
            if coerced is not None:
                args[slot_name] = coerced

        # Post-processing hook: model_year default injection (retained from pre-declarative era)
        if allow_factor_year_default and tool_name == "query_emission_factors" and "model_year" not in args:
            defaults = dict((ConfigLoader.load_mappings() or {}).get("defaults") or {})
            try:
                default_my = int(defaults.get("model_year"))
                args["model_year"] = default_my
            except (TypeError, ValueError):
                pass

        return args

    def to_persisted_state(self) -> Dict[str, Any]:
        return self.inner_router.to_persisted_state()

    def restore_persisted_state(self, payload: Dict[str, Any]) -> None:
        self.inner_router.restore_persisted_state(payload)
        self.ao_manager = AOManager(self.inner_router.memory.fact_memory)
        self.constraint_violation_writer = self._build_constraint_violation_writer()
        self.stance_resolver = StanceResolver(runtime_config=self.runtime_config)
        self.oasc_contract = OASCContract(
            inner_router=self.inner_router,
            ao_manager=self.ao_manager,
            runtime_config=self.runtime_config,
        )
        self._build_contracts()


def build_router(
    session_id: str,
    *,
    memory_storage_dir: Optional[str | Path] = None,
    router_mode: str = "router",
) -> Any:
    normalized_mode = str(router_mode or "router").strip().lower()
    if normalized_mode in {"full", "governed_v2", "router"}:
        return GovernedRouter(session_id=session_id, memory_storage_dir=memory_storage_dir)
    if normalized_mode == "naive":
        raise ValueError("router_mode='naive' must construct NaiveRouter directly")
    raise ValueError(f"Unsupported router_mode: {router_mode}")
