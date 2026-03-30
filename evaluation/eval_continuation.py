"""Evaluate bounded residual-plan continuation behavior and prompt variants."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_config
from core.context_store import SessionContextStore
from core.plan import ExecutionPlan
from core.router import CONTINUATION_PROMPT_VARIANTS, CONTINUATION_TOOL_KEYWORDS, UnifiedRouter
from core.task_state import TaskState
from core.tool_dependencies import suggest_prerequisite_tool, validate_tool_prerequisites
from core.trace import Trace
from evaluation.utils import load_jsonl, now_ts, runtime_overrides, safe_div, write_json, write_jsonl
from services.llm_client import LLMResponse, ToolCall, get_llm_client


CANONICAL_TOOL_ORDER = (
    "calculate_macro_emission",
    "calculate_micro_emission",
    "calculate_dispersion",
    "analyze_hotspots",
    "render_spatial_map",
    "compare_scenarios",
    "query_emission_factors",
    "query_knowledge",
)


class ContinuationExecutionMode(str, Enum):
    DETERMINISTIC = "deterministic"
    LIVE_MODEL = "live_model"


@dataclass
class ContinuationEvalCase:
    case_id: str
    category: str
    description: str
    prior_state: Dict[str, Any]
    current_user_input: str
    expected_continuation_decision: bool
    expected_new_task_override: bool
    expected_next_tool: Optional[str]
    expected_trace_markers: List[str]
    notes: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ContinuationEvalCase":
        return cls(
            case_id=str(payload.get("case_id") or "").strip(),
            category=str(payload.get("category") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            prior_state=dict(payload.get("prior_state") or {}),
            current_user_input=str(payload.get("current_user_input") or "").strip(),
            expected_continuation_decision=bool(payload.get("expected_continuation_decision", False)),
            expected_new_task_override=bool(payload.get("expected_new_task_override", False)),
            expected_next_tool=(
                str(payload["expected_next_tool"]).strip()
                if payload.get("expected_next_tool") is not None
                else None
            ),
            expected_trace_markers=[
                str(item).strip()
                for item in (payload.get("expected_trace_markers") or [])
                if str(item).strip()
            ],
            notes=str(payload.get("notes")).strip() if payload.get("notes") is not None else None,
        )


class _EvalMemory:
    def get_fact_memory(self) -> Dict[str, Any]:
        return {}

    def get_working_memory(self) -> List[Dict[str, Any]]:
        return []

    def update(self, *args: Any, **kwargs: Any) -> None:
        return None


class _EvalAssembler:
    def assemble(
        self,
        *,
        user_message: str,
        working_memory: Optional[Sequence[Dict[str, Any]]] = None,
        fact_memory: Optional[Dict[str, Any]] = None,
        file_context: Optional[Dict[str, Any]] = None,
        context_summary: str = "",
    ) -> Any:
        tools = [
            {"type": "function", "function": {"name": name}}
            for name in CANONICAL_TOOL_ORDER
        ]
        return SimpleNamespace(
            system_prompt="continuation evaluation prompt",
            tools=tools,
            messages=[{"role": "user", "content": user_message}],
            estimated_tokens=0,
        )


class DeterministicContinuationLLM:
    """Mock LLM that deterministically maps injected guidance to one tool choice."""

    def __init__(
        self,
        *,
        case: ContinuationEvalCase,
        plan_provider: Callable[[], Optional[ExecutionPlan]],
        prompt_variant: str,
        blocked_info: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.case = case
        self._plan_provider = plan_provider
        self.prompt_variant = prompt_variant
        self.blocked_info = blocked_info or {}
        self.requests: List[Dict[str, Any]] = []

    async def chat_with_tools(
        self,
        *,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        system: str,
    ) -> LLMResponse:
        self.requests.append({"messages": messages, "tools": tools, "system": system})
        tool_name = self._select_tool(messages)
        if tool_name is None:
            return LLMResponse(content="No tool selected for this continuation case.")
        return LLMResponse(
            content=f"deterministically selected {tool_name}",
            tool_calls=[
                ToolCall(
                    id=f"{self.case.case_id}-tool",
                    name=tool_name,
                    arguments=self._tool_arguments_for(tool_name),
                )
            ],
        )

    async def chat_json(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {}

    async def chat(self, *args: Any, **kwargs: Any) -> LLMResponse:
        return LLMResponse(content="unused")

    def _tool_arguments_for(self, tool_name: str) -> Dict[str, Any]:
        plan = self._plan_provider()
        if isinstance(plan, ExecutionPlan):
            for step in plan.steps:
                if step.tool_name == tool_name and isinstance(step.argument_hints, dict):
                    return dict(step.argument_hints)
        return {}

    @staticmethod
    def _extract_guidance(messages: List[Dict[str, Any]]) -> Optional[str]:
        for message in reversed(messages):
            content = str(message.get("content") or "")
            if message.get("role") == "system" and "Residual workflow continuation" in content:
                return content
        return None

    @staticmethod
    def _extract_user_text(messages: List[Dict[str, Any]]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user":
                return str(message.get("content") or "").strip().lower()
        return ""

    def _extract_prompt_variant(self, guidance: Optional[str]) -> str:
        if guidance:
            matched = re.search(r"variant=([a-z_]+)", guidance)
            if matched and matched.group(1) in CONTINUATION_PROMPT_VARIANTS:
                return matched.group(1)
        return self.prompt_variant

    def _explicit_tool_from_user(self, plan: Optional[ExecutionPlan], user_text: str) -> Optional[str]:
        if plan is None:
            return None
        pending_steps = plan.get_pending_steps()
        for step in pending_steps:
            keywords = CONTINUATION_TOOL_KEYWORDS.get(step.tool_name, [])
            if any(keyword.lower() in user_text for keyword in keywords):
                return step.tool_name
        if "扩散" in user_text:
            return "calculate_dispersion"
        if "热点" in user_text and "渲染" in user_text:
            return "render_spatial_map"
        return None

    def _goal_weighted_tool(self, plan: Optional[ExecutionPlan], user_text: str) -> Optional[str]:
        if plan is None:
            return None
        goal_text = " ".join(
            filter(
                None,
                [
                    plan.goal.lower(),
                    plan.planner_notes.lower() if plan.planner_notes else "",
                    user_text,
                ],
            )
        )
        scored: List[tuple[int, int, str]] = []
        pending_steps = plan.get_pending_steps()
        for index, step in enumerate(pending_steps):
            score = 0
            for keyword in CONTINUATION_TOOL_KEYWORDS.get(step.tool_name, []):
                if keyword.lower() in goal_text:
                    score += 1
            scored.append((score, index, step.tool_name))
        if not scored:
            return None
        scored.sort(key=lambda item: (item[0], item[1]))
        return scored[-1][2]

    def _blocked_recovery_tool(self) -> Optional[str]:
        missing_tokens = self.blocked_info.get("missing_tokens") or []
        for token in missing_tokens:
            suggested = suggest_prerequisite_tool(str(token))
            if suggested:
                return suggested
        return None

    def _select_tool(self, messages: List[Dict[str, Any]]) -> Optional[str]:
        guidance = self._extract_guidance(messages)
        if guidance is None:
            return None

        plan = self._plan_provider()
        user_text = self._extract_user_text(messages)
        explicit = self._explicit_tool_from_user(plan, user_text)
        if explicit:
            return explicit

        variant = self._extract_prompt_variant(guidance)
        next_step = plan.get_next_pending_step() if isinstance(plan, ExecutionPlan) else None
        ready_step = None
        if isinstance(plan, ExecutionPlan):
            ready_step = next(
                (step for step in plan.get_pending_steps() if step.status.value == "ready"),
                None,
            )

        if variant == "next_step_heavy":
            if next_step is not None:
                return next_step.tool_name
            if ready_step is not None:
                return ready_step.tool_name
            return self._blocked_recovery_tool() or self._goal_weighted_tool(plan, user_text)

        if variant == "balanced_repair_aware":
            if self.blocked_info and ("blocked reason" in guidance.lower() or "repair summary" in guidance.lower()):
                if next_step is not None and next_step.status.value != "blocked":
                    return next_step.tool_name
                recovery_tool = self._blocked_recovery_tool()
                if recovery_tool:
                    return recovery_tool
            if next_step is not None and next_step.status.value != "blocked":
                return next_step.tool_name
            if ready_step is not None:
                return ready_step.tool_name
            return self._blocked_recovery_tool() or self._goal_weighted_tool(plan, user_text)

        return self._goal_weighted_tool(plan, user_text)


class LiveModelContinuationLLM:
    """Thin wrapper that lets the eval harness call the real LLM client with controlled settings."""

    def __init__(
        self,
        *,
        client: Any,
        temperature: float = 0.0,
        seed: Optional[int] = None,
    ) -> None:
        self.client = client
        self.temperature = temperature
        self.seed = seed
        self.requests: List[Dict[str, Any]] = []

    async def chat_with_tools(
        self,
        *,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        system: str,
    ) -> LLMResponse:
        self.requests.append({"messages": messages, "tools": tools, "system": system})
        return await self.client.chat_with_tools(
            messages=messages,
            tools=tools,
            system=system,
            temperature=self.temperature,
            seed=self.seed,
        )

    async def chat_json(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await self.client.chat_json(
            messages=messages,
            system=system,
            temperature=self.temperature,
            seed=self.seed,
        )

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
    ) -> LLMResponse:
        return await self.client.chat(
            messages=messages,
            system=system,
            temperature=self.temperature,
            seed=self.seed,
        )


def _default_live_llm_factory(*, temperature: float, seed: Optional[int]) -> LiveModelContinuationLLM:
    return LiveModelContinuationLLM(
        client=get_llm_client(purpose="agent"),
        temperature=temperature,
        seed=seed,
    )


def _synthetic_result_for_token(token: str) -> Optional[tuple[str, Dict[str, Any]]]:
    if token == "emission":
        return (
            "calculate_macro_emission",
            {
                "success": True,
                "summary": "Synthetic emission result",
                "data": {
                    "summary": {"total_links": 1},
                    "results": [{"link_id": "L1", "total_emissions_kg_per_hr": 1.0}],
                },
            },
        )
    if token == "dispersion":
        return (
            "calculate_dispersion",
            {
                "success": True,
                "summary": "Synthetic dispersion result",
                "data": {
                    "summary": {"receptor_count": 1},
                    "concentration_grid": {"receptors": [{"id": "R1", "concentration": 3.2}]},
                },
            },
        )
    if token == "hotspot":
        return (
            "analyze_hotspots",
            {
                "success": True,
                "summary": "Synthetic hotspot result",
                "data": {
                    "summary": {"hotspot_count": 1},
                    "hotspots": [{"id": "H1", "score": 9.1}],
                },
            },
        )
    return None


def _seed_context_store(
    context_store: SessionContextStore,
    *,
    available_tokens: Iterable[str],
    stale_tokens: Iterable[str],
) -> None:
    stale_set = {str(token).strip() for token in stale_tokens if str(token).strip()}
    for token in {str(token).strip() for token in available_tokens if str(token).strip()} | stale_set:
        synthetic = _synthetic_result_for_token(token)
        if synthetic is None:
            continue
        tool_name, result = synthetic
        stored = context_store.store_result(tool_name, result)
        if stored is not None and token in stale_set:
            stored.metadata["stale"] = True


def _build_router_for_case(
    case: ContinuationEvalCase,
    *,
    prompt_variant: str,
    state: TaskState,
    execution_mode: str,
    live_llm_factory: Optional[Callable[..., Any]] = None,
    live_model_temperature: float = 0.0,
    live_model_seed: Optional[int] = None,
) -> UnifiedRouter:
    router = object.__new__(UnifiedRouter)
    router.session_id = f"continuation-eval-{case.case_id}-{execution_mode}"
    router.runtime_config = get_config()
    router.memory = _EvalMemory()
    router.assembler = _EvalAssembler()
    router.executor = SimpleNamespace(execute=None)
    router.context_store = SessionContextStore()
    blocked_info = dict(case.prior_state.get("blocked_info") or {})
    _seed_context_store(
        router.context_store,
        available_tokens=case.prior_state.get("available_tokens") or [],
        stale_tokens=case.prior_state.get("stale_tokens") or [],
    )
    if execution_mode == ContinuationExecutionMode.DETERMINISTIC.value:
        router.llm = DeterministicContinuationLLM(
            case=case,
            plan_provider=lambda: state.plan or ExecutionPlan.from_dict(case.prior_state.get("plan")),
            prompt_variant=prompt_variant,
            blocked_info=blocked_info,
        )
    else:
        factory = live_llm_factory or _default_live_llm_factory
        router.llm = factory(
            temperature=live_model_temperature,
            seed=live_model_seed,
        )
    router._live_continuation_bundle = {
        "plan": case.prior_state.get("plan"),
        "repair_history": case.prior_state.get("repair_history") or [],
        "blocked_info": blocked_info or None,
        "file_path": case.prior_state.get("file_path"),
        "latest_repair_summary": case.prior_state.get("latest_repair_summary"),
        "residual_plan_summary": None,
    }
    return router


def _case_trace_markers(trace_obj: Trace) -> List[str]:
    return [step.step_type.value for step in trace_obj.steps]


def _trace_completeness(expected: Sequence[str], observed: Sequence[str]) -> float:
    if not expected:
        return 1.0
    observed_set = set(observed)
    matched = sum(1 for marker in expected if marker in observed_set)
    return round(safe_div(matched, len(expected)), 4)


def _next_tool_alignment(expected_tool: Optional[str], actual_tool: Optional[str]) -> Optional[bool]:
    if expected_tool is None:
        return None
    return actual_tool == expected_tool


def _classify_eval_failure(exc: Exception) -> str:
    message = str(exc).lower()
    if "timeout" in message:
        return "timeout"
    if "api key" in message or "connection" in message or "chat with tools failed" in message:
        return "llm_call_failure"
    if "tool" in message and "parse" in message:
        return "tool_selection_extraction_failure"
    return "runtime_failure"


def _collect_case_result(
    *,
    case: ContinuationEvalCase,
    state: TaskState,
    router: UnifiedRouter,
    trace_obj: Trace,
    prompt_variant: str,
    execution_mode: str,
    failure_type: Optional[str] = None,
    failure_message: Optional[str] = None,
    backend_notes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    decision = state.continuation
    actual_tool = state.execution.selected_tool
    blocked_after_continuation = False
    dependency_message = None
    if decision and decision.should_continue and actual_tool:
        arguments = {}
        if state.plan is not None:
            matched_step = state.plan.get_step(tool_name=actual_tool)
            if matched_step is not None:
                arguments = dict(matched_step.argument_hints or {})
        validation = validate_tool_prerequisites(
            actual_tool,
            arguments=arguments,
            available_tokens=router._collect_available_result_tokens(state, include_stale=False),
            context_store=router.context_store,
            include_stale=False,
        )
        blocked_after_continuation = not validation.is_valid
        dependency_message = validation.message

    observed_markers = _case_trace_markers(trace_obj)
    trace_score = _trace_completeness(case.expected_trace_markers, observed_markers)
    trace_ok = trace_score == 1.0
    actual_continuation = bool(decision and decision.should_continue)
    actual_new_task_override = bool(decision and decision.new_task_override)
    decision_correct = actual_continuation == case.expected_continuation_decision
    new_task_correct = actual_new_task_override == case.expected_new_task_override
    next_tool_aligned = _next_tool_alignment(case.expected_next_tool, actual_tool)

    assistant_direct_response = None
    if state.execution.tool_results:
        assistant_direct_response = state.execution.tool_results[-1].get("text")

    if failure_type is None and actual_continuation and actual_tool is None:
        if assistant_direct_response:
            failure_type = "unexpected_direct_answer"
            failure_message = assistant_direct_response
        else:
            failure_type = "no_tool_selected"
            failure_message = "Continuation was selected but no tool call was returned."
    if failure_type is None and not trace_ok:
        failure_type = "trace_missing"
        failure_message = "Expected continuation trace markers were not all observed."

    case_success = decision_correct and new_task_correct and trace_ok
    if next_tool_aligned is not None:
        case_success = case_success and next_tool_aligned
    if failure_type is not None:
        case_success = False

    mode_notes = list(backend_notes or [])
    if execution_mode == ContinuationExecutionMode.DETERMINISTIC.value:
        mode_notes.append("deterministic selector backend")
    else:
        mode_notes.append(
            f"live model backend; temperature={getattr(router.llm, 'temperature', None)}; seed={getattr(router.llm, 'seed', None)}"
        )

    return {
        "case_id": case.case_id,
        "category": case.category,
        "description": case.description,
        "execution_mode": execution_mode,
        "variant": prompt_variant,
        "prompt_variant": decision.prompt_variant if decision else prompt_variant,
        "current_user_input": case.current_user_input,
        "expected_continuation_decision": case.expected_continuation_decision,
        "actual_continuation_decision": actual_continuation,
        "continuation_decision_correct": decision_correct,
        "expected_new_task_override": case.expected_new_task_override,
        "actual_new_task_override": actual_new_task_override,
        "new_task_override_correct": new_task_correct,
        "expected_next_tool": case.expected_next_tool,
        "actual_next_tool": actual_tool,
        "next_step_alignment": next_tool_aligned,
        "blocked_after_continuation": blocked_after_continuation,
        "dependency_validation_message": dependency_message,
        "expected_trace_markers": list(case.expected_trace_markers),
        "observed_trace_markers": observed_markers,
        "trace_completeness": trace_score,
        "trace_ok": trace_ok,
        "case_success": case_success,
        "pass": case_success,
        "failure_type": failure_type,
        "failure_message": failure_message,
        "continuation_signal": decision.signal if decision else None,
        "continuation_reason": decision.reason if decision else None,
        "latest_repair_summary": decision.latest_repair_summary if decision else None,
        "latest_blocked_reason": decision.latest_blocked_reason if decision else None,
        "next_planned_step": state.get_next_planned_step().to_dict() if state.get_next_planned_step() else None,
        "residual_plan_summary": decision.residual_plan_summary if decision else None,
        "assistant_direct_response": assistant_direct_response,
        "mode_notes": mode_notes,
        "trace": trace_obj.to_dict(),
        "notes": case.notes,
    }


def _init_case_state(case: ContinuationEvalCase) -> TaskState:
    state = TaskState.initialize(
        user_message=case.current_user_input,
        file_path=case.prior_state.get("current_file_path"),
        memory_dict={},
        session_id=f"continuation-eval-{case.case_id}",
    )
    available_tokens = case.prior_state.get("available_tokens") or []
    if available_tokens:
        state.execution.available_results.update(str(token) for token in available_tokens)
    return state


async def _run_case_deterministic(
    case: ContinuationEvalCase,
    *,
    prompt_variant: str,
) -> Dict[str, Any]:
    state = _init_case_state(case)
    router = _build_router_for_case(
        case,
        prompt_variant=prompt_variant,
        state=state,
        execution_mode=ContinuationExecutionMode.DETERMINISTIC.value,
    )
    trace_obj = Trace.start(session_id=router.session_id)
    failure_type = None
    failure_message = None
    try:
        await router._state_handle_input(state, trace_obj=trace_obj)
    except Exception as exc:  # pragma: no cover - deterministic backend should stay stable
        failure_type = _classify_eval_failure(exc)
        failure_message = str(exc)
    return _collect_case_result(
        case=case,
        state=state,
        router=router,
        trace_obj=trace_obj,
        prompt_variant=prompt_variant,
        execution_mode=ContinuationExecutionMode.DETERMINISTIC.value,
        failure_type=failure_type,
        failure_message=failure_message,
    )


async def _run_case_live_model(
    case: ContinuationEvalCase,
    *,
    prompt_variant: str,
    live_llm_factory: Optional[Callable[..., Any]] = None,
    live_model_temperature: float = 0.0,
    live_model_seed: Optional[int] = None,
) -> Dict[str, Any]:
    state = _init_case_state(case)
    trace_obj = Trace.start(session_id=f"continuation-eval-{case.case_id}-live-model")
    backend_notes: List[str] = []
    failure_type = None
    failure_message = None

    try:
        router = _build_router_for_case(
            case,
            prompt_variant=prompt_variant,
            state=state,
            execution_mode=ContinuationExecutionMode.LIVE_MODEL.value,
            live_llm_factory=live_llm_factory,
            live_model_temperature=live_model_temperature,
            live_model_seed=live_model_seed,
        )
    except Exception as exc:
        router = object.__new__(UnifiedRouter)
        router.session_id = f"continuation-eval-{case.case_id}-live-model-failed"
        router.context_store = SessionContextStore()
        failure_type = "llm_backend_init_failure"
        failure_message = str(exc)
        backend_notes.append("live model backend initialization failed before state loop entry")
        return _collect_case_result(
            case=case,
            state=state,
            router=router,
            trace_obj=trace_obj,
            prompt_variant=prompt_variant,
            execution_mode=ContinuationExecutionMode.LIVE_MODEL.value,
            failure_type=failure_type,
            failure_message=failure_message,
            backend_notes=backend_notes,
        )

    try:
        await router._state_handle_input(state, trace_obj=trace_obj)
    except Exception as exc:
        failure_type = _classify_eval_failure(exc)
        failure_message = str(exc)
        backend_notes.append("live model backend raised during first-step continuation evaluation")

    return _collect_case_result(
        case=case,
        state=state,
        router=router,
        trace_obj=trace_obj,
        prompt_variant=prompt_variant,
        execution_mode=ContinuationExecutionMode.LIVE_MODEL.value,
        failure_type=failure_type,
        failure_message=failure_message,
        backend_notes=backend_notes,
    )


async def _run_case(
    case: ContinuationEvalCase,
    *,
    prompt_variant: str,
    execution_mode: str,
    live_llm_factory: Optional[Callable[..., Any]] = None,
    live_model_temperature: float = 0.0,
    live_model_seed: Optional[int] = None,
) -> Dict[str, Any]:
    if execution_mode == ContinuationExecutionMode.LIVE_MODEL.value:
        return await _run_case_live_model(
            case,
            prompt_variant=prompt_variant,
            live_llm_factory=live_llm_factory,
            live_model_temperature=live_model_temperature,
            live_model_seed=live_model_seed,
        )
    return await _run_case_deterministic(
        case,
        prompt_variant=prompt_variant,
    )


def _aggregate_variant_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(records)
    decision_correct = sum(1 for record in records if record["continuation_decision_correct"])
    safe_continue_total = sum(1 for record in records if record["expected_continuation_decision"])
    safe_continue_hits = sum(
        1
        for record in records
        if record["expected_continuation_decision"] and record["actual_continuation_decision"]
    )
    actual_override_positive = sum(1 for record in records if record["actual_new_task_override"])
    true_override_positive = sum(
        1
        for record in records
        if record["actual_new_task_override"] and record["expected_new_task_override"]
    )
    alignment_applicable = [record for record in records if record["expected_next_tool"]]
    alignment_hits = sum(1 for record in alignment_applicable if record["next_step_alignment"] is True)
    blocked_applicable = [
        record
        for record in records
        if record["actual_continuation_decision"] and record["actual_next_tool"]
    ]
    blocked_hits = sum(1 for record in blocked_applicable if record["blocked_after_continuation"])
    trace_avg = round(sum(record["trace_completeness"] for record in records) / total, 4) if total else 0.0
    repair_aware_cases = [
        record
        for record in records
        if record["category"] in {"repair_applied_continue", "dependency_blocked_continue"}
    ]
    repair_aware_successes = sum(
        1
        for record in repair_aware_cases
        if record["actual_continuation_decision"]
        and record["next_step_alignment"] is True
        and not record["blocked_after_continuation"]
    )
    failure_counts: Dict[str, int] = {}
    for record in records:
        failure_type = record.get("failure_type")
        if not failure_type:
            continue
        failure_counts[failure_type] = failure_counts.get(failure_type, 0) + 1

    categories: Dict[str, Dict[str, Any]] = {}
    for record in records:
        bucket = categories.setdefault(
            record["category"],
            {
                "cases": 0,
                "decision_accuracy": 0.0,
                "next_step_alignment_rate": 0.0,
                "blocked_after_continuation_rate": 0.0,
                "_decision_hits": 0,
                "_alignment_hits": 0,
                "_alignment_total": 0,
                "_blocked_hits": 0,
                "_blocked_total": 0,
            },
        )
        bucket["cases"] += 1
        bucket["_decision_hits"] += int(record["continuation_decision_correct"])
        if record["next_step_alignment"] is not None:
            bucket["_alignment_total"] += 1
            bucket["_alignment_hits"] += int(record["next_step_alignment"] is True)
        if record["actual_continuation_decision"] and record["actual_next_tool"]:
            bucket["_blocked_total"] += 1
            bucket["_blocked_hits"] += int(record["blocked_after_continuation"])

    for bucket in categories.values():
        bucket["decision_accuracy"] = round(safe_div(bucket["_decision_hits"], bucket["cases"]), 4)
        bucket["next_step_alignment_rate"] = round(
            safe_div(bucket["_alignment_hits"], bucket["_alignment_total"]), 4
        )
        bucket["blocked_after_continuation_rate"] = round(
            safe_div(bucket["_blocked_hits"], bucket["_blocked_total"]), 4
        )
        for key in list(bucket.keys()):
            if key.startswith("_"):
                bucket.pop(key, None)

    return {
        "task": "continuation",
        "execution_mode": records[0]["execution_mode"] if records else None,
        "prompt_variant": records[0]["prompt_variant"] if records else None,
        "samples": total,
        "continuation_decision_accuracy": round(safe_div(decision_correct, total), 4),
        "new_task_override_precision": round(safe_div(true_override_positive, actual_override_positive), 4),
        "safe_continuation_recall": round(safe_div(safe_continue_hits, safe_continue_total), 4),
        "next_step_alignment_rate": round(safe_div(alignment_hits, len(alignment_applicable)), 4),
        "blocked_after_continuation_rate": round(safe_div(blocked_hits, len(blocked_applicable)), 4),
        "trace_completeness": trace_avg,
        "repair_aware_continuation_success_rate": round(
            safe_div(repair_aware_successes, len(repair_aware_cases)),
            4,
        ),
        "failure_count": sum(failure_counts.values()),
        "failure_counts": failure_counts,
        "categories": categories,
    }


def _variant_markdown(
    execution_mode: str,
    variant: str,
    metrics: Dict[str, Any],
    records: List[Dict[str, Any]],
) -> str:
    lines = [
        f"# Continuation Evaluation Summary: {execution_mode} / {variant}",
        "",
        "## Aggregate Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| continuation_decision_accuracy | {metrics['continuation_decision_accuracy']:.4f} |",
        f"| new_task_override_precision | {metrics['new_task_override_precision']:.4f} |",
        f"| safe_continuation_recall | {metrics['safe_continuation_recall']:.4f} |",
        f"| next_step_alignment_rate | {metrics['next_step_alignment_rate']:.4f} |",
        f"| blocked_after_continuation_rate | {metrics['blocked_after_continuation_rate']:.4f} |",
        f"| trace_completeness | {metrics['trace_completeness']:.4f} |",
        f"| repair_aware_continuation_success_rate | {metrics['repair_aware_continuation_success_rate']:.4f} |",
        f"| failure_count | {metrics['failure_count']} |",
        "",
        "## Category Metrics",
        "",
        "| Category | Cases | Decision Acc. | Next-Step Align | Blocked After Continue |",
        "|---|---:|---:|---:|---:|",
    ]
    for category, payload in sorted(metrics["categories"].items()):
        lines.append(
            "| {category} | {cases} | {decision:.4f} | {align:.4f} | {blocked:.4f} |".format(
                category=category,
                cases=payload["cases"],
                decision=payload["decision_accuracy"],
                align=payload["next_step_alignment_rate"],
                blocked=payload["blocked_after_continuation_rate"],
            )
        )

    if metrics["failure_counts"]:
        lines.extend(
            [
                "",
                "## Failure Counts",
                "",
                "| Failure Type | Count |",
                "|---|---:|",
            ]
        )
        for failure_type, count in sorted(metrics["failure_counts"].items()):
            lines.append(f"| {failure_type} | {count} |")

    notable_failures = [
        record
        for record in records
        if record.get("failure_type") or not record.get("case_success")
    ][:5]
    if notable_failures:
        lines.extend(
            [
                "",
                "## Notable Failure Cases",
                "",
            ]
        )
        for record in notable_failures:
            lines.append(
                "- `{case_id}` ({category}): failure_type={failure_type}, tool={tool}, note={note}".format(
                    case_id=record["case_id"],
                    category=record["category"],
                    failure_type=record.get("failure_type") or "metric_mismatch",
                    tool=record.get("actual_next_tool") or "-",
                    note=record.get("failure_message") or record.get("continuation_reason") or "-",
                )
            )

    lines.extend(
        [
            "",
            "## Per-Case Results",
            "",
            "| Case | Category | Continue | Expected | Tool | Expected Tool | Blocked | Trace | Failure |",
            "|---|---|---:|---:|---|---|---:|---:|---|",
        ]
    )
    for record in records:
        lines.append(
            "| {case_id} | {category} | {actual} | {expected} | {tool} | {expected_tool} | {blocked} | {trace:.2f} | {failure} |".format(
                case_id=record["case_id"],
                category=record["category"],
                actual=str(record["actual_continuation_decision"]).lower(),
                expected=str(record["expected_continuation_decision"]).lower(),
                tool=record["actual_next_tool"] or "-",
                expected_tool=record["expected_next_tool"] or "-",
                blocked=str(bool(record["blocked_after_continuation"])).lower(),
                trace=record["trace_completeness"],
                failure=record.get("failure_type") or "-",
            )
        )
    return "\n".join(lines) + "\n"


def _variant_comparison_markdown(execution_mode: str, mode_summary: Dict[str, Any]) -> str:
    lines = [
        f"# Continuation Prompt Variant Comparison: {execution_mode}",
        "",
        "## Aggregate Metrics",
        "",
        "| Variant | Decision Acc. | Override Prec. | Safe Continue Recall | Next-Step Align | Blocked After Continue | Trace Complete | Repair-Aware Success | Failures |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for variant, payload in mode_summary["variants"].items():
        metrics = payload["metrics"]
        lines.append(
            "| {variant} | {decision:.4f} | {override:.4f} | {recall:.4f} | {align:.4f} | {blocked:.4f} | {trace:.4f} | {repair:.4f} | {failures} |".format(
                variant=variant,
                decision=metrics["continuation_decision_accuracy"],
                override=metrics["new_task_override_precision"],
                recall=metrics["safe_continuation_recall"],
                align=metrics["next_step_alignment_rate"],
                blocked=metrics["blocked_after_continuation_rate"],
                trace=metrics["trace_completeness"],
                repair=metrics["repair_aware_continuation_success_rate"],
                failures=metrics["failure_count"],
            )
        )
    return "\n".join(lines) + "\n"


def _largest_category_gaps(det_metrics: Dict[str, Any], live_metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    categories = set(det_metrics.get("categories", {}).keys()) | set(live_metrics.get("categories", {}).keys())
    gaps: List[Dict[str, Any]] = []
    for category in sorted(categories):
        det = det_metrics.get("categories", {}).get(category, {})
        live = live_metrics.get("categories", {}).get(category, {})
        alignment_gap = round(
            live.get("next_step_alignment_rate", 0.0) - det.get("next_step_alignment_rate", 0.0),
            4,
        )
        decision_gap = round(
            live.get("decision_accuracy", 0.0) - det.get("decision_accuracy", 0.0),
            4,
        )
        blocked_gap = round(
            live.get("blocked_after_continuation_rate", 0.0) - det.get("blocked_after_continuation_rate", 0.0),
            4,
        )
        gaps.append(
            {
                "category": category,
                "next_step_alignment_gap": alignment_gap,
                "decision_accuracy_gap": decision_gap,
                "blocked_after_continuation_gap": blocked_gap,
                "abs_alignment_gap": abs(alignment_gap),
            }
        )
    gaps.sort(key=lambda item: item["abs_alignment_gap"], reverse=True)
    for item in gaps:
        item.pop("abs_alignment_gap", None)
    return gaps[:3]


def _select_recommended_live_variant(mode_summaries: Dict[str, Any]) -> Optional[str]:
    live_summary = mode_summaries.get(ContinuationExecutionMode.LIVE_MODEL.value)
    if not live_summary:
        return None

    ranked: List[tuple[float, float, float, float, str]] = []
    for variant, payload in live_summary["variants"].items():
        metrics = payload["metrics"]
        ranked.append(
            (
                metrics["next_step_alignment_rate"],
                metrics["continuation_decision_accuracy"],
                metrics["trace_completeness"],
                -metrics["blocked_after_continuation_rate"],
                variant,
            )
        )
    if not ranked:
        return None
    ranked.sort()
    return ranked[-1][-1]


def _mode_comparison_payload(summary: Dict[str, Any]) -> Dict[str, Any]:
    execution_modes = summary.get("execution_modes", {})
    comparison: Dict[str, Any] = {
        "task": "continuation",
        "samples": summary.get("samples", 0),
        "modes": {},
        "variants": {},
        "recommended_live_model_variant": _select_recommended_live_variant(execution_modes),
    }

    for mode, payload in execution_modes.items():
        comparison["modes"][mode] = {
            "variants": {
                variant: variant_payload["metrics"]
                for variant, variant_payload in payload.get("variants", {}).items()
            }
        }

    all_variants = set()
    for payload in execution_modes.values():
        all_variants.update(payload.get("variants", {}).keys())

    det_payload = execution_modes.get(ContinuationExecutionMode.DETERMINISTIC.value, {})
    live_payload = execution_modes.get(ContinuationExecutionMode.LIVE_MODEL.value, {})
    for variant in sorted(all_variants):
        det_metrics = det_payload.get("variants", {}).get(variant, {}).get("metrics")
        live_metrics = live_payload.get("variants", {}).get(variant, {}).get("metrics")
        metric_gaps: Dict[str, float] = {}
        if det_metrics and live_metrics:
            for key in (
                "continuation_decision_accuracy",
                "new_task_override_precision",
                "safe_continuation_recall",
                "next_step_alignment_rate",
                "blocked_after_continuation_rate",
                "trace_completeness",
                "repair_aware_continuation_success_rate",
            ):
                metric_gaps[key] = round(live_metrics[key] - det_metrics[key], 4)

        comparison["variants"][variant] = {
            "deterministic": det_metrics,
            "live_model": live_metrics,
            "metric_gaps": metric_gaps,
            "largest_category_gaps": (
                _largest_category_gaps(det_metrics, live_metrics)
                if det_metrics and live_metrics
                else []
            ),
        }

    return comparison


def _mode_comparison_markdown(summary: Dict[str, Any], comparison: Dict[str, Any]) -> str:
    lines = [
        "# Continuation Execution Mode Comparison",
        "",
        "## Variant-by-Mode Metrics",
        "",
        "| Variant | Mode | Decision Acc. | Override Prec. | Safe Continue Recall | Next-Step Align | Blocked After Continue | Trace Complete | Repair-Aware Success | Failures |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for mode, payload in summary.get("execution_modes", {}).items():
        for variant, variant_payload in payload.get("variants", {}).items():
            metrics = variant_payload["metrics"]
            lines.append(
                "| {variant} | {mode} | {decision:.4f} | {override:.4f} | {recall:.4f} | {align:.4f} | {blocked:.4f} | {trace:.4f} | {repair:.4f} | {failures} |".format(
                    variant=variant,
                    mode=mode,
                    decision=metrics["continuation_decision_accuracy"],
                    override=metrics["new_task_override_precision"],
                    recall=metrics["safe_continuation_recall"],
                    align=metrics["next_step_alignment_rate"],
                    blocked=metrics["blocked_after_continuation_rate"],
                    trace=metrics["trace_completeness"],
                    repair=metrics["repair_aware_continuation_success_rate"],
                    failures=metrics["failure_count"],
                )
            )

    lines.extend(
        [
            "",
            "## Deterministic vs Live-Model Gaps",
            "",
        ]
    )
    for variant, payload in comparison.get("variants", {}).items():
        if not payload.get("metric_gaps"):
            continue
        lines.append(f"### {variant}")
        lines.append("")
        lines.append("| Metric | Live - Deterministic |")
        lines.append("|---|---:|")
        for metric_name, gap in payload["metric_gaps"].items():
            lines.append(f"| {metric_name} | {gap:+.4f} |")
        if payload["largest_category_gaps"]:
            lines.append("")
            lines.append("| Category | Alignment Gap | Decision Gap | Blocked Gap |")
            lines.append("|---|---:|---:|---:|")
            for item in payload["largest_category_gaps"]:
                lines.append(
                    "| {category} | {align:+.4f} | {decision:+.4f} | {blocked:+.4f} |".format(
                        category=item["category"],
                        align=item["next_step_alignment_gap"],
                        decision=item["decision_accuracy_gap"],
                        blocked=item["blocked_after_continuation_gap"],
                    )
                )
        lines.append("")

    recommended_variant = comparison.get("recommended_live_model_variant")
    if recommended_variant:
        lines.extend(
            [
                "## Recommended Live-Model Variant",
                "",
                f"- `{recommended_variant}` currently offers the strongest live-model balance across next-step alignment, decision accuracy, and blocked-after-continuation rate under the shared harness.",
                "",
            ]
        )

    live_failures: List[str] = []
    live_summary = summary.get("execution_modes", {}).get(ContinuationExecutionMode.LIVE_MODEL.value, {})
    for variant, payload in live_summary.get("variants", {}).items():
        metrics = payload["metrics"]
        if metrics["failure_count"]:
            live_failures.append(f"- `{variant}`: {metrics['failure_counts']}")
    if live_failures:
        lines.extend(["## Notable Live-Model Failures", ""])
        lines.extend(live_failures)
        lines.append("")

    return "\n".join(lines) + "\n"


def _filter_cases(
    cases: List[ContinuationEvalCase],
    *,
    max_cases: Optional[int] = None,
    categories: Optional[Sequence[str]] = None,
    case_ids: Optional[Sequence[str]] = None,
) -> List[ContinuationEvalCase]:
    category_filter = {str(item).strip() for item in (categories or []) if str(item).strip()}
    case_id_filter = {str(item).strip() for item in (case_ids or []) if str(item).strip()}

    filtered: List[ContinuationEvalCase] = []
    for case in cases:
        if category_filter and case.category not in category_filter:
            continue
        if case_id_filter and case.case_id not in case_id_filter:
            continue
        filtered.append(case)

    if max_cases is not None:
        return filtered[: max(0, int(max_cases))]
    return filtered


def run_continuation_evaluation(
    *,
    samples_path: Path,
    output_dir: Path,
    variants: Sequence[str],
    execution_modes: Sequence[str] = (ContinuationExecutionMode.DETERMINISTIC.value,),
    max_cases: Optional[int] = None,
    categories: Optional[Sequence[str]] = None,
    case_ids: Optional[Sequence[str]] = None,
    live_model_temperature: float = 0.0,
    live_model_seed: Optional[int] = None,
    dry_run: bool = False,
    live_llm_factory: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    cases = [ContinuationEvalCase.from_dict(payload) for payload in load_jsonl(samples_path)]
    cases = _filter_cases(
        cases,
        max_cases=max_cases,
        categories=categories,
        case_ids=case_ids,
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    normalized_modes: List[str] = []
    for mode in execution_modes:
        normalized = str(mode).strip().lower()
        if normalized not in {item.value for item in ContinuationExecutionMode}:
            raise ValueError(f"Unknown continuation execution mode: {mode}")
        normalized_modes.append(normalized)

    summary: Dict[str, Any] = {
        "task": "continuation",
        "samples": len(cases),
        "samples_path": str(samples_path),
        "execution_modes": {},
        "filters": {
            "max_cases": max_cases,
            "categories": list(categories or []),
            "case_ids": list(case_ids or []),
            "dry_run": dry_run,
        },
    }

    if dry_run:
        summary["planned_cases"] = [
            {
                "case_id": case.case_id,
                "category": case.category,
                "variants": list(variants),
                "execution_modes": normalized_modes,
            }
            for case in cases
        ]
        write_json(output_dir / "continuation_dry_run_plan.json", summary)
        return summary

    async def _run_async() -> Dict[str, Any]:
        with runtime_overrides(
            enable_state_orchestration=True,
            enable_trace=True,
            enable_lightweight_planning=False,
            enable_bounded_plan_repair=True,
            enable_repair_aware_continuation=True,
        ):
            for mode in normalized_modes:
                mode_summary: Dict[str, Any] = {
                    "mode": mode,
                    "variants": {},
                }
                mode_dir = output_dir / mode
                mode_dir.mkdir(parents=True, exist_ok=True)
                for variant in variants:
                    normalized_variant = str(variant).strip().lower()
                    if normalized_variant not in CONTINUATION_PROMPT_VARIANTS:
                        raise ValueError(f"Unknown continuation prompt variant: {variant}")
                    get_config().continuation_prompt_variant = normalized_variant
                    variant_records: List[Dict[str, Any]] = []
                    for case in cases:
                        variant_records.append(
                            await _run_case(
                                case,
                                prompt_variant=normalized_variant,
                                execution_mode=mode,
                                live_llm_factory=live_llm_factory,
                                live_model_temperature=live_model_temperature,
                                live_model_seed=live_model_seed,
                            )
                        )
                    metrics = _aggregate_variant_metrics(variant_records)
                    variant_dir = mode_dir / normalized_variant
                    variant_dir.mkdir(parents=True, exist_ok=True)
                    write_jsonl(variant_dir / "continuation_case_results.jsonl", variant_records)
                    write_json(variant_dir / "continuation_metrics.json", metrics)
                    (variant_dir / "continuation_summary.md").write_text(
                        _variant_markdown(mode, normalized_variant, metrics, variant_records),
                        encoding="utf-8",
                    )
                    if len(normalized_modes) == 1:
                        legacy_variant_dir = output_dir / normalized_variant
                        legacy_variant_dir.mkdir(parents=True, exist_ok=True)
                        write_jsonl(legacy_variant_dir / "continuation_case_results.jsonl", variant_records)
                        write_json(legacy_variant_dir / "continuation_metrics.json", metrics)
                        (legacy_variant_dir / "continuation_summary.md").write_text(
                            _variant_markdown(mode, normalized_variant, metrics, variant_records),
                            encoding="utf-8",
                        )
                    mode_summary["variants"][normalized_variant] = {
                        "metrics": metrics,
                        "logs_path": str(variant_dir / "continuation_case_results.jsonl"),
                        "metrics_path": str(variant_dir / "continuation_metrics.json"),
                        "summary_path": str(variant_dir / "continuation_summary.md"),
                    }

                write_json(mode_dir / "continuation_variant_comparison.json", mode_summary)
                (mode_dir / "continuation_variant_comparison.md").write_text(
                    _variant_comparison_markdown(mode, mode_summary),
                    encoding="utf-8",
                )
                mode_summary["variant_comparison_path"] = str(mode_dir / "continuation_variant_comparison.json")
                mode_summary["variant_comparison_markdown_path"] = str(
                    mode_dir / "continuation_variant_comparison.md"
                )
                summary["execution_modes"][mode] = mode_summary
        return summary

    summary = asyncio.run(_run_async())
    comparison = _mode_comparison_payload(summary)
    summary["mode_comparison"] = comparison
    write_json(output_dir / "continuation_mode_comparison.json", comparison)
    (output_dir / "continuation_mode_comparison.md").write_text(
        _mode_comparison_markdown(summary, comparison),
        encoding="utf-8",
    )
    summary["mode_comparison_path"] = str(output_dir / "continuation_mode_comparison.json")
    summary["mode_comparison_markdown_path"] = str(output_dir / "continuation_mode_comparison.md")

    if len(normalized_modes) == 1:
        single_mode = normalized_modes[0]
        summary["variants"] = summary["execution_modes"][single_mode]["variants"]
        write_json(
            output_dir / "continuation_variant_comparison.json",
            summary["execution_modes"][single_mode],
        )
        (output_dir / "continuation_variant_comparison.md").write_text(
            _variant_comparison_markdown(single_mode, summary["execution_modes"][single_mode]),
            encoding="utf-8",
        )

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate repair-aware continuation prompt variants.")
    parser.add_argument(
        "--samples",
        type=Path,
        default=PROJECT_ROOT / "evaluation/continuation/samples.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / f"evaluation/results/continuation/continuation_{now_ts()}",
    )
    parser.add_argument("--variant", choices=list(CONTINUATION_PROMPT_VARIANTS))
    parser.add_argument("--variant-set")
    parser.add_argument("--mode", choices=[item.value for item in ContinuationExecutionMode])
    parser.add_argument("--mode-set")
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--categories")
    parser.add_argument("--case-ids")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.variant and args.variant_set:
        raise SystemExit("Use either --variant or --variant-set, not both.")
    if args.mode and args.mode_set:
        raise SystemExit("Use either --mode or --mode-set, not both.")

    if args.variant_set:
        variants = [item.strip() for item in args.variant_set.split(",") if item.strip()]
    elif args.variant:
        variants = [args.variant]
    else:
        variants = ["balanced_repair_aware"]

    if args.mode_set:
        execution_modes = [item.strip() for item in args.mode_set.split(",") if item.strip()]
    elif args.mode:
        execution_modes = [args.mode]
    else:
        execution_modes = [ContinuationExecutionMode.DETERMINISTIC.value]

    categories = [item.strip() for item in (args.categories or "").split(",") if item.strip()]
    case_ids = [item.strip() for item in (args.case_ids or "").split(",") if item.strip()]

    summary = run_continuation_evaluation(
        samples_path=args.samples,
        output_dir=args.output_dir,
        variants=variants,
        execution_modes=execution_modes,
        max_cases=args.max_cases,
        categories=categories,
        case_ids=case_ids,
        live_model_temperature=args.temperature,
        live_model_seed=args.seed,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
