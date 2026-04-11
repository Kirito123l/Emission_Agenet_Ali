"""
Unified Router - Main entry point for new architecture
Uses Tool Use mode with optional lightweight planning in the state loop
"""
import logging
import json
import re
import time
from pathlib import Path
from typing import Dict, Optional, List, Any, Tuple
from dataclasses import dataclass
from config import get_config
from core.assembler import ContextAssembler
from core.context_store import SessionContextStore
from core.executor import ToolExecutor
from core.artifact_memory import (
    ArtifactMemoryState,
    apply_artifact_memory_to_capability_summary,
    build_artifact_suggestion_plan,
    classify_artifacts_from_delivery,
    update_artifact_memory,
)
from core.file_relationship_resolution import (
    FileRelationshipDecision,
    FileRelationshipFileSummary,
    FileRelationshipParseResult,
    FileRelationshipResolutionContext,
    FileRelationshipTransitionPlan,
    FileRelationshipType,
    build_file_relationship_transition_plan,
    infer_file_relationship_fallback,
    parse_file_relationship_result,
)
from core.file_analysis_fallback import (
    FileAnalysisFallbackDecision,
    build_file_analysis_fallback_payload,
    merge_rule_and_fallback_analysis,
    parse_llm_file_analysis_result,
    should_use_llm_fallback,
)
from core.geometry_recovery import (
    GeometryRecoveryContext,
    GeometryRecoveryStatus,
    SupportingSpatialInput,
    build_geometry_recovery_context,
    re_ground_with_supporting_spatial_input,
)
from core.input_completion import (
    InputCompletionDecision,
    InputCompletionDecisionType,
    InputCompletionOption,
    InputCompletionOptionType,
    InputCompletionParseResult,
    InputCompletionReasonCode,
    InputCompletionRequest,
    format_input_completion_prompt,
    parse_input_completion_reply,
    reply_looks_like_input_completion_attempt,
)
from core.intent_resolution import (
    INTENT_RESOLUTION_PROMPT,
    DeliverableIntentType,
    IntentResolutionApplicationPlan,
    IntentResolutionContext,
    IntentResolutionDecision,
    IntentResolutionParseResult,
    ProgressIntentType,
    apply_intent_bias_to_capability_summary,
    build_intent_resolution_application_plan,
    infer_intent_resolution_fallback,
    parse_intent_resolution_result,
)
from core.conversation_intent import ConversationIntent, ConversationIntentClassifier
from core.memory import MemoryManager
from core.output_safety import sanitize_response
from core.remediation_policy import (
    RemediationPolicy,
    RemediationPolicyType,
    apply_default_typical_profile,
    check_default_typical_profile_eligibility,
)
from core.parameter_negotiation import (
    NegotiationCandidate,
    NegotiationDecisionType,
    ParameterNegotiationDecision,
    ParameterNegotiationParseResult,
    ParameterNegotiationRequest,
    build_candidate_aliases,
    format_parameter_negotiation_prompt,
    parse_parameter_negotiation_reply,
    reply_looks_like_confirmation_attempt,
)
from core.plan import ExecutionPlan, PlanStatus, PlanStep, PlanStepStatus
from core.plan_repair import (
    PlanRepairDecision,
    RepairActionType,
    RepairTriggerContext,
    RepairTriggerType,
    RepairValidationResult,
    summarize_repair_action,
    validate_plan_repair,
)
from core.readiness import (
    ActionAffordance,
    ReadinessAssessment,
    ReadinessStatus,
    build_action_already_provided_response,
    build_action_blocked_response,
    build_action_repairable_response,
    build_readiness_assessment,
    map_tool_call_to_action_id,
)
from core.residual_reentry import (
    RecoveredWorkflowReentryContext,
    ReentryDecision,
    build_recovered_workflow_reentry_context,
    build_reentry_guidance_summary,
)
from core.supplemental_merge import (
    SupplementalMergeContext,
    SupplementalMergePlan,
    SupplementalMergeResult,
    _extract_missing_fields,
    apply_supplemental_merge_analysis_refresh,
    build_supplemental_merge_plan,
    execute_supplemental_merge,
)
from core.summary_delivery import (
    SummaryDeliveryContext,
    SummaryDeliveryPlan,
    SummaryDeliveryResult,
    build_summary_delivery_plan,
    execute_summary_delivery_plan,
)
from core.task_state import (
    ContinuationDecision,
    ParamEntry,
    ParamStatus,
    TaskStage,
    TaskState,
)
from core.tool_dependencies import (
    DependencyValidationResult,
    TOOL_GRAPH,
    get_missing_prerequisites,
    get_tool_provides,
    normalize_tokens,
    validate_tool_prerequisites,
    validate_plan_steps,
)
from core.trace import Trace, TraceStepType
from core.workflow_templates import (
    TemplateRecommendation,
    TemplateSelectionResult,
    WorkflowTemplate,
    recommend_workflow_templates,
    select_primary_template,
    summarize_template_prior,
)
from tools.contract_loader import get_tool_contract_registry
from core.router_memory_utils import (
    build_memory_tool_calls as build_memory_tool_calls_helper,
    compact_tool_data as compact_tool_data_helper,
)
from core.router_payload_utils import (
    extract_chart_data as extract_chart_data_helper,
    extract_download_file as extract_download_file_helper,
    extract_map_data as extract_map_data_helper,
    extract_table_data as extract_table_data_helper,
    format_emission_factors_chart as format_emission_factors_chart_helper,
)
from core.router_render_utils import (
    filter_results_for_synthesis as filter_results_for_synthesis_helper,
    format_results_as_fallback as format_results_as_fallback_helper,
    format_tool_errors as format_tool_errors_helper,
    format_tool_results as format_tool_results_helper,
    render_single_tool_success as render_single_tool_success_helper,
)
from core.router_synthesis_utils import (
    build_synthesis_request as build_synthesis_request_helper,
    detect_hallucination_keywords as detect_hallucination_keywords_helper,
    maybe_short_circuit_synthesis as maybe_short_circuit_synthesis_helper,
)
from services.cross_constraints import get_cross_constraint_validator
from services.llm_client import LLMResponse, ToolCall, get_llm_client
from services.standardizer import UnifiedStandardizer

logger = logging.getLogger(__name__)


# Synthesis-only prompt (no tool calling)
SYNTHESIS_PROMPT = """你是机动车排放计算助手。基于工具执行结果生成专业回答。

## 要求
1. 只使用工具返回的实际数据，不要编造或推算数值
2. 总结关键结果（总排放量、计算参数、统计信息）
3. query_knowledge 工具：完整保留返回的答案和参考文档
4. 其他工具：不要添加"参考文档"字样
5. 失败时说明问题并给出建议

## 工具执行结果
{results}
"""


PLANNING_PROMPT = """You are a lightweight workflow planner for an academic emission-analysis agent.

Return one compact JSON object only.
Requirements:
- Build a grounded execution plan, not a product UX flow.
- If workflow_template_prior is provided, use it as the structured starting point unless grounded user intent clearly requires a narrower adaptation.
- Do not include analyze_file in plan steps.
- Use only tool names that exist in the runtime tool surface.
- Use canonical result tokens only: emission, dispersion, hotspot.
- Keep the plan ordered, minimal, and auditable.
- Each step should include: step_id, tool_name, purpose, depends_on, produces, argument_hints.
- For render_spatial_map, set argument_hints.layer_type when it is inferable.
- If the request is not a workflow, return an empty steps list instead of free text.
"""


FILE_ANALYSIS_FALLBACK_PROMPT = """You are a bounded semantic fallback for file grounding in an academic emission-analysis agent.

Return one compact JSON object only.
Requirements:
- This is a fallback layer for low-confidence file analysis, not a free-form file understanding agent.
- Allowed task_type values only: macro_emission, micro_emission, unknown.
- Use only the provided canonical semantic fields.
- column_mapping must use the format {canonical_field: source_column}.
- Use only source columns that appear in the provided metadata.
- If the ZIP package has multiple candidate tables, you may set selected_primary_table to one candidate filename.
- If the ZIP package has multiple datasets and roles are still ambiguous, you may return dataset_roles with bounded role labels only.
- Do not invent new task types, tools, or execution steps.
- If evidence is insufficient, keep task_type as unknown and leave unresolved fields unmapped.
"""


REPAIR_PROMPT = """You are a bounded residual-workflow repair controller for an academic emission-analysis agent.

Return one compact JSON object only.
Requirements:
- Repair only the residual workflow. Never rewrite or mutate completed steps.
- Allowed action_type values only:
  KEEP_REMAINING
  DROP_BLOCKED_STEP
  REORDER_REMAINING_STEPS
  REPLACE_STEP
  TRUNCATE_AFTER_CURRENT
  APPEND_RECOVERY_STEP
  NO_REPAIR
- Prefer the smallest local repair that restores a legal residual workflow.
- Do not auto-execute anything.
- Do not invent new tools.
- Do not use analyze_file as a repair step.
- Use canonical dependency tokens only: emission, dispersion, hotspot.
- If the trigger is mild and the residual workflow is still legal, return action_type=NO_REPAIR and is_applicable=false.
- patch fields may contain:
  target_step_id
  affected_step_ids
  skip_step_ids
  reordered_step_ids
  replacement_step
  append_steps
  truncate_after_step_id
"""


FILE_RELATIONSHIP_RESOLUTION_PROMPT = """You are a bounded file-relationship resolver for an academic emission-analysis agent.

Return one compact JSON object only.
Requirements:
- Classify the relationship between the latest referenced/uploaded file and the current workflow state.
- Allowed relationship_type values only:
  replace_primary_file
  attach_supporting_file
  merge_supplemental_columns
  continue_with_current_file
  ask_clarify
- This resolver does not choose tools, rewrite plans, or mutate backend state directly.
- Use affected_contexts only from:
  primary_file
  pending_completion
  completion_overrides
  geometry_recovery
  residual_workflow
  residual_reentry
  supporting_file_context
  supplemental_merge
- Set should_supersede_pending_completion=true only when the new file should override the active completion flow.
- Set should_reset_recovery_context=true only when recovery state bound to the previous primary file should be invalidated.
- Set should_preserve_residual_workflow=true only when the residual workflow remains semantically valid after this file decision.
- If evidence is insufficient, return relationship_type=ask_clarify instead of guessing.
"""


CONTINUATION_TOOL_KEYWORDS = (
    get_tool_contract_registry().get_continuation_keywords()
)

CONTINUATION_PROMPT_VARIANTS = (
    "goal_heavy",
    "next_step_heavy",
    "balanced_repair_aware",
)


@dataclass
class RouterResponse:
    """Router response to user"""
    text: str
    chart_data: Optional[Dict] = None
    table_data: Optional[Dict] = None
    map_data: Optional[Dict] = None
    download_file: Optional[Dict[str, Any]] = None
    executed_tool_calls: Optional[List[Dict[str, Any]]] = None
    trace: Optional[Dict[str, Any]] = None  # NEW: auditable decision trace
    trace_friendly: Optional[List[Dict[str, str]]] = None


class UnifiedRouter:
    """
    Unified router - New architecture main entry point

    Design philosophy:
    - Trust LLM to make decisions
    - Use Tool Use mode with an optional lightweight JSON planning pass
    - Standardization happens in executor (transparent)
    - Natural dialogue for clarification
    - Errors handled through conversation
    - Lightweight planning is soft guidance plus validation, not rigid control
    """

    MAX_TOOL_CALLS_PER_TURN = 3  # Prevent infinite loops

    def __init__(self, session_id: str, memory_storage_dir: Optional[str | Path] = None):
        self.session_id = session_id
        self.runtime_config = get_config()
        self.assembler = ContextAssembler()
        self.executor = ToolExecutor()
        self.memory = MemoryManager(session_id, storage_dir=memory_storage_dir)
        self.context_store = SessionContextStore()
        self.llm = get_llm_client("agent")
        logger.info("Router LLM model for session %s: %s", self.session_id, self.llm.model)
        self.conversation_intent_classifier = ConversationIntentClassifier()
        self._message_standardizer: Optional[UnifiedStandardizer] = None
        self._live_continuation_bundle: Dict[str, Any] = {
            "plan": None,
            "repair_history": [],
            "blocked_info": None,
            "file_path": None,
            "latest_repair_summary": None,
            "residual_plan_summary": None,
        }
        self._live_parameter_negotiation: Dict[str, Any] = {
            "active_request": None,
            "parameter_snapshot": {},
            "locked_parameters": {},
            "latest_confirmed_parameter": None,
            "file_path": None,
            "plan": None,
            "repair_history": [],
            "blocked_info": None,
            "latest_repair_summary": None,
            "residual_plan_summary": None,
            "original_goal": None,
            "original_user_message": None,
        }
        self._live_input_completion: Dict[str, Any] = {
            "active_request": None,
            "overrides": {},
            "latest_decision": None,
            "file_path": None,
            "plan": None,
            "repair_history": [],
            "blocked_info": None,
            "latest_repair_summary": None,
            "residual_plan_summary": None,
            "original_goal": None,
            "original_user_message": None,
            "action_id": None,
            "recovered_file_context": None,
            "supporting_spatial_input": None,
            "geometry_recovery_context": None,
            "readiness_refresh_result": None,
            "residual_reentry_context": None,
        }
        self._live_file_relationship: Dict[str, Any] = {
            "latest_decision": None,
            "latest_transition_plan": None,
            "pending_upload_summary": None,
            "pending_upload_analysis": None,
            "pending_primary_summary": None,
            "pending_primary_analysis": None,
            "attached_supporting_file": None,
            "awaiting_clarification": False,
        }
        self._live_intent_resolution: Dict[str, Any] = {
            "latest_decision": None,
            "latest_application_plan": None,
        }

    def _ensure_context_store(self) -> SessionContextStore:
        """Lazily initialize the session context store for test helpers and old instances."""
        if not hasattr(self, "context_store") or self.context_store is None:
            self.context_store = SessionContextStore()
        return self.context_store

    def _ensure_live_continuation_bundle(self) -> Dict[str, Any]:
        if not hasattr(self, "_live_continuation_bundle") or not isinstance(self._live_continuation_bundle, dict):
            self._live_continuation_bundle = {
                "plan": None,
                "repair_history": [],
                "blocked_info": None,
                "file_path": None,
                "latest_repair_summary": None,
                "residual_plan_summary": None,
            }
        return self._live_continuation_bundle

    def _ensure_live_parameter_negotiation_bundle(self) -> Dict[str, Any]:
        if not hasattr(self, "_live_parameter_negotiation") or not isinstance(self._live_parameter_negotiation, dict):
            self._live_parameter_negotiation = {
                "active_request": None,
                "parameter_snapshot": {},
                "locked_parameters": {},
                "latest_confirmed_parameter": None,
                "file_path": None,
                "plan": None,
                "repair_history": [],
                "blocked_info": None,
                "latest_repair_summary": None,
                "residual_plan_summary": None,
                "original_goal": None,
                "original_user_message": None,
            }
        return self._live_parameter_negotiation

    def _ensure_live_input_completion_bundle(self) -> Dict[str, Any]:
        if not hasattr(self, "_live_input_completion") or not isinstance(self._live_input_completion, dict):
            self._live_input_completion = {
                "active_request": None,
                "overrides": {},
                "latest_decision": None,
                "file_path": None,
                "plan": None,
                "repair_history": [],
                "blocked_info": None,
                "latest_repair_summary": None,
                "residual_plan_summary": None,
                "original_goal": None,
                "original_user_message": None,
                "action_id": None,
                "recovered_file_context": None,
                "supporting_spatial_input": None,
                "geometry_recovery_context": None,
                "readiness_refresh_result": None,
                "residual_reentry_context": None,
            }
        return self._live_input_completion

    def _ensure_live_file_relationship_bundle(self) -> Dict[str, Any]:
        if not hasattr(self, "_live_file_relationship") or not isinstance(self._live_file_relationship, dict):
            self._live_file_relationship = {
                "latest_decision": None,
                "latest_transition_plan": None,
                "pending_upload_summary": None,
                "pending_upload_analysis": None,
                "pending_primary_summary": None,
                "pending_primary_analysis": None,
                "attached_supporting_file": None,
                "awaiting_clarification": False,
            }
        return self._live_file_relationship

    def _ensure_live_intent_resolution_bundle(self) -> Dict[str, Any]:
        if not hasattr(self, "_live_intent_resolution") or not isinstance(self._live_intent_resolution, dict):
            self._live_intent_resolution = {
                "latest_decision": None,
                "latest_application_plan": None,
            }
        return self._live_intent_resolution

    def _get_context_summary(self) -> str:
        """Return the current compact session summary for LLM context."""
        return self._ensure_context_store().get_context_summary()

    def _ensure_conversation_intent_classifier(self) -> ConversationIntentClassifier:
        if (
            not hasattr(self, "conversation_intent_classifier")
            or self.conversation_intent_classifier is None
        ):
            self.conversation_intent_classifier = ConversationIntentClassifier()
        return self.conversation_intent_classifier

    def _has_active_residual_workflow(self) -> bool:
        bundle = self._ensure_live_continuation_bundle()
        return bool(
            bundle.get("plan")
            or bundle.get("blocked_info")
            or bundle.get("residual_plan_summary")
        )

    def _get_memory_context_for_prompt(self) -> Optional[str]:
        if not getattr(self.runtime_config, "enable_layered_memory_context", True):
            return None
        if hasattr(self.memory, "build_context_for_prompt"):
            return self.memory.build_context_for_prompt()
        return None

    def _build_conversational_messages(
        self,
        user_message: str,
        *,
        max_turns: int = 5,
        assistant_char_limit: int = 1200,
    ) -> List[Dict[str, str]]:
        if hasattr(self.memory, "build_conversational_messages"):
            return self.memory.build_conversational_messages(
                user_message,
                max_turns=max_turns,
                assistant_char_limit=assistant_char_limit,
            )

        messages: List[Dict[str, str]] = []
        history = []
        if hasattr(self, "memory") and hasattr(self.memory, "get_working_memory"):
            history = self.memory.get_working_memory() or []

        for turn in history[-max_turns:]:
            user_text = str(turn.get("user", "")).strip()
            assistant_text = str(turn.get("assistant", "")).strip()
            if user_text:
                messages.append({"role": "user", "content": user_text})
            if assistant_text:
                if len(assistant_text) > assistant_char_limit:
                    assistant_text = assistant_text[:assistant_char_limit].rstrip() + "...(truncated)"
                messages.append({"role": "assistant", "content": assistant_text})

        messages.append({"role": "user", "content": user_message})
        return messages

    def _build_conversational_system_prompt(
        self,
        *,
        explain_result: bool = False,
    ) -> str:
        fact_memory = self.memory.get_fact_memory() if hasattr(self.memory, "get_fact_memory") else {}
        sections = [
            "你是 EmissionAgent，一个专注于交通排放分析的智能助手。",
            "你的能力范围包括道路交通排放估算、扩散模拟、热点识别、情景对比，以及相关知识解释。",
            "回答要求：简洁、自然、忠于当前会话上下文；如果请求明显需要执行工具或继续任务，不要假装已执行。",
        ]

        context_summary = self._get_context_summary()
        if context_summary:
            sections.append(f"当前会话摘要：\n{context_summary}")
        memory_context = self._get_memory_context_for_prompt()
        if memory_context:
            sections.append(f"分层记忆上下文：\n{memory_context}")

        if explain_result:
            last_tool_name = str(fact_memory.get("last_tool_name") or "未知")
            last_tool_summary = str(fact_memory.get("last_tool_summary") or "")
            snapshot = fact_memory.get("last_tool_snapshot")
            snapshot_text = ""
            if snapshot:
                try:
                    snapshot_text = json.dumps(snapshot, ensure_ascii=False)
                except Exception:
                    snapshot_text = str(snapshot)
                if len(snapshot_text) > 1000:
                    snapshot_text = snapshot_text[:1000].rstrip() + "...(truncated)"
            sections.append(f"上一次成功工具：{last_tool_name}")
            if last_tool_summary:
                sections.append(f"上一次结果摘要：{last_tool_summary[:500]}")
            if snapshot_text:
                sections.append(f"结果快照：{snapshot_text}")
            sections.append("当前模式：用户在追问或要求解释既有结果，请解释而不是重新规划任务。")

        return "\n\n".join(sections)

    async def _maybe_handle_conversation_fast_path(
        self,
        user_message: str,
        file_path: Optional[str],
        trace: Optional[Dict[str, Any]],
    ) -> Optional[RouterResponse]:
        if not getattr(self.runtime_config, "enable_conversation_fast_path", True):
            return None

        fact_memory = self.memory.get_fact_memory() if hasattr(self.memory, "get_fact_memory") else {}
        classifier = self._ensure_conversation_intent_classifier()
        intent_result = classifier.classify(
            user_message=user_message,
            has_new_file=bool(file_path),
            has_last_tool_name=bool(fact_memory.get("last_tool_name")),
            has_active_file=bool(fact_memory.get("active_file")),
            has_active_negotiation=bool(self._ensure_live_parameter_negotiation_bundle().get("active_request")),
            has_active_completion=bool(self._ensure_live_input_completion_bundle().get("active_request")),
            has_file_relationship_clarification=bool(
                self._ensure_live_file_relationship_bundle().get("awaiting_clarification")
            ),
            has_residual_workflow=self._has_active_residual_workflow(),
        )

        if trace is not None:
            trace.clear()
            trace["input"] = {
                "user_message": user_message,
                "file_path": file_path,
            }
            trace["intent_classification"] = {
                "intent": intent_result.intent.value,
                "confidence": intent_result.confidence,
                "rationale": intent_result.rationale,
                "fast_path_allowed": intent_result.fast_path_allowed,
                "blocking_signals": list(intent_result.blocking_signals),
            }

        if not intent_result.fast_path_allowed:
            return None

        tool_calls_data = None
        if intent_result.intent == ConversationIntent.CHITCHAT:
            llm_response = await self.llm.chat(
                messages=self._build_conversational_messages(user_message),
                system=self._build_conversational_system_prompt(),
            )
            text = self._sanitize_response_text(llm_response.content)
        elif intent_result.intent == ConversationIntent.EXPLAIN_RESULT:
            llm_response = await self.llm.chat(
                messages=self._build_conversational_messages(user_message),
                system=self._build_conversational_system_prompt(explain_result=True),
            )
            text = self._sanitize_response_text(llm_response.content)
        elif intent_result.intent == ConversationIntent.KNOWLEDGE_QA:
            result = await self.executor.execute(
                tool_name="query_knowledge",
                arguments={"query": user_message},
                file_path=file_path,
            )
            tool_calls_data = [
                {
                    "name": "query_knowledge",
                    "arguments": {"query": user_message},
                    "result": result,
                }
            ]
            if result.get("success"):
                self._save_result_to_session_context("query_knowledge", result)
                text = self._sanitize_response_text(
                    str(result.get("summary") or result.get("message") or "知识查询完成。")
                )
            else:
                text = self._sanitize_response_text(
                    str(result.get("message") or result.get("error") or "知识查询未成功完成。")
                )
        else:
            return None

        self.memory.update(
            user_message=user_message,
            assistant_response=text,
            tool_calls=tool_calls_data,
            file_path=None,
            file_analysis=None,
        )

        response = RouterResponse(
            text=text,
            executed_tool_calls=tool_calls_data,
        )
        if trace is not None:
            trace["conversation_fast_path"] = {
                "intent": intent_result.intent.value,
                "used_tool": tool_calls_data[0]["name"] if tool_calls_data else None,
            }
            trace["final"] = {
                "text": text,
                "fast_path": True,
                "tool_calls": tool_calls_data,
            }
            if getattr(self.runtime_config, "enable_trace", False):
                response.trace = trace
                response.trace_friendly = []
        return response

    @staticmethod
    def _json_safe_payload(value: Any) -> Any:
        """Convert live router state to a JSON-safe payload."""
        try:
            return json.loads(json.dumps(value, ensure_ascii=False, default=str))
        except Exception:
            return None

    def to_persisted_state(self) -> Dict[str, Any]:
        """Serialize restart-sensitive router state with a versioned envelope."""
        return {
            "version": 2,
            "context_store": self._ensure_context_store().to_persisted_dict(),
            "live_state": {
                "parameter_negotiation": self._json_safe_payload(
                    self._ensure_live_parameter_negotiation_bundle()
                ),
                "input_completion": self._json_safe_payload(
                    self._ensure_live_input_completion_bundle()
                ),
                "continuation_bundle": self._json_safe_payload(
                    self._ensure_live_continuation_bundle()
                ),
            },
        }

    def restore_persisted_state(self, payload: Dict[str, Any]) -> None:
        """Restore versioned router state while accepting legacy context-store payloads."""
        if not isinstance(payload, dict):
            return

        context_payload = payload.get("context_store")
        if isinstance(context_payload, dict):
            self.context_store = SessionContextStore.from_persisted_dict(context_payload)

        live_state = payload.get("live_state")
        if not isinstance(live_state, dict):
            return

        parameter_negotiation = live_state.get("parameter_negotiation")
        if isinstance(parameter_negotiation, dict):
            self._ensure_live_parameter_negotiation_bundle().update(parameter_negotiation)

        input_completion = live_state.get("input_completion")
        if isinstance(input_completion, dict):
            self._ensure_live_input_completion_bundle().update(input_completion)

        continuation_bundle = live_state.get("continuation_bundle")
        if isinstance(continuation_bundle, dict):
            self._ensure_live_continuation_bundle().update(continuation_bundle)

    def _sanitize_response_text(self, text: Optional[str]) -> str:
        """Apply the user-facing output safety rail on every response path."""
        return sanitize_response(text or "")

    def _save_result_to_session_context(self, tool_name: str, result: Dict[str, Any]) -> None:
        """Store full results for downstream tools and keep legacy spatial memory updated."""
        self._ensure_context_store().add_current_turn_result(tool_name, result)
        self._update_legacy_last_spatial_data(tool_name, result)

    def _update_legacy_last_spatial_data(self, tool_name: str, result: Dict[str, Any]) -> None:
        """Maintain the old last_spatial_data compatibility slot during migration."""
        if not isinstance(result, dict) or not result.get("success"):
            return

        data = result.get("data", {})
        if not isinstance(data, dict):
            return

        if tool_name in {"calculate_macro_emission", "calculate_micro_emission"}:
            results_list = data.get("results", [])
            if isinstance(results_list, list) and results_list:
                has_geom = any(
                    isinstance(item, dict) and item.get("geometry")
                    for item in results_list[:5]
                )
                if has_geom:
                    self.memory.fact_memory.last_spatial_data = data
                    logger.info("Saved last_spatial_data: %s links with geometry", len(results_list))
                    return

        if tool_name == "analyze_hotspots" and "hotspots" in data:
            self.memory.fact_memory.last_spatial_data = data
            logger.info(
                "Saved last_spatial_data: hotspot analysis with %s hotspots",
                len(data.get("hotspots", [])),
            )
            return

        if tool_name == "calculate_dispersion" and ("concentration_grid" in data or "raster_grid" in data):
            self.memory.fact_memory.last_spatial_data = data
            receptor_count = len(data.get("concentration_grid", {}).get("receptors", []))
            if receptor_count:
                logger.info(
                    "Saved last_spatial_data: concentration_grid with %s receptors",
                    receptor_count,
                )
            else:
                raster = data.get("raster_grid", {})
                logger.info(
                    "Saved last_spatial_data: raster_grid with %sx%s cells",
                    raster.get("rows", 0),
                    raster.get("cols", 0),
                )

    def _prepare_tool_arguments(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]],
        state: Optional[TaskState] = None,
    ) -> Dict[str, Any]:
        """Inject the right upstream result for downstream tools."""
        effective_arguments = dict(arguments or {})
        if state is not None:
            for param_name, entry in state.parameters.items():
                if not entry.locked or not entry.normalized:
                    continue
                if param_name in {"vehicle_type", "road_type", "season", "meteorology", "stability_class"}:
                    effective_arguments[param_name] = entry.normalized
            if state.input_completion_overrides:
                effective_arguments["_input_completion_overrides"] = (
                    state.get_input_completion_overrides_summary()
                )
        if tool_name == "compare_scenarios":
            effective_arguments["_context_store"] = self._ensure_context_store()
            return effective_arguments

        if tool_name not in {"render_spatial_map", "calculate_dispersion", "analyze_hotspots"}:
            return effective_arguments
        if "_last_result" in effective_arguments:
            return effective_arguments

        context_store = self._ensure_context_store()
        layer_type = effective_arguments.get("layer_type")
        scenario_label = effective_arguments.get("scenario_label")
        stored_result = context_store.get_result_for_tool(
            tool_name,
            label=scenario_label,
            layer_type=layer_type,
        )
        if isinstance(stored_result, dict):
            effective_arguments["_last_result"] = stored_result
            logger.info("%s: injected _last_result from context store", tool_name)
            return effective_arguments

        fact_mem = self.memory.get_fact_memory()
        spatial = fact_mem.get("last_spatial_data")

        if tool_name == "render_spatial_map":
            if isinstance(spatial, dict) and spatial.get("results"):
                effective_arguments["_last_result"] = {"success": True, "data": spatial}
                logger.info(
                    "render_spatial_map: injected from memory spatial_data, %s links",
                    len(spatial["results"]),
                )
                return effective_arguments
            snapshot = fact_mem.get("last_tool_snapshot")
            if snapshot:
                effective_arguments["_last_result"] = snapshot
                logger.warning(
                    "render_spatial_map: using last_tool_snapshot (may be compacted, geometry might be missing)"
                )
                return effective_arguments

        if tool_name == "calculate_dispersion":
            if isinstance(spatial, dict) and spatial.get("results"):
                sample = spatial["results"][:3]
                if any(
                    isinstance(item, dict) and item.get("total_emissions_kg_per_hr")
                    for item in sample
                ):
                    effective_arguments["_last_result"] = {"success": True, "data": spatial}
                    logger.info(
                        "calculate_dispersion: injected macro emission result from memory spatial_data, %s links",
                        len(spatial["results"]),
                    )
                    return effective_arguments

        if tool_name == "analyze_hotspots":
            if isinstance(spatial, dict) and "raster_grid" in spatial:
                effective_arguments["_last_result"] = {"success": True, "data": spatial}
                logger.info(
                    "analyze_hotspots: injected raster result from memory spatial_data, hotspots=%s",
                    len(spatial.get("hotspots", [])),
                )
                return effective_arguments

        return effective_arguments

    def _get_message_standardizer(self) -> UnifiedStandardizer:
        if not hasattr(self, "_message_standardizer") or self._message_standardizer is None:
            self._message_standardizer = UnifiedStandardizer()
        return self._message_standardizer

    @staticmethod
    def _find_alias_position(message_lower: str, alias_lower: str) -> Optional[int]:
        if not alias_lower:
            return None
        if re.search(r"[A-Za-z0-9]", alias_lower):
            pattern = rf"(?<![A-Za-z0-9]){re.escape(alias_lower)}(?![A-Za-z0-9])"
            match = re.search(pattern, message_lower)
            return match.start() if match else None
        position = message_lower.find(alias_lower)
        return position if position >= 0 else None

    def _find_best_alias_match(
        self,
        message: str,
        lookup: Dict[str, str],
    ) -> Optional[Tuple[str, str]]:
        message_lower = message.lower()
        best_match: Optional[Tuple[str, str, int]] = None
        for alias, normalized in sorted(lookup.items(), key=lambda item: (-len(str(item[0])), str(item[0]))):
            alias_text = str(alias).strip()
            if not alias_text:
                continue
            position = self._find_alias_position(message_lower, alias_text.lower())
            if position is None:
                continue
            candidate = (alias_text, normalized, position)
            if best_match is None or len(candidate[0]) > len(best_match[0]) or (
                len(candidate[0]) == len(best_match[0]) and candidate[2] < best_match[2]
            ):
                best_match = candidate
        if best_match is None:
            return None
        return best_match[0], best_match[1]

    def _extract_pollutants_from_message(self, message: str) -> List[str]:
        standardizer = self._get_message_standardizer()
        message_lower = message.lower()
        matches: List[Tuple[int, str]] = []
        seen: set[str] = set()
        for alias, normalized in sorted(
            standardizer.pollutant_lookup.items(),
            key=lambda item: (-len(str(item[0])), str(item[0])),
        ):
            alias_text = str(alias).strip()
            if not alias_text or normalized in seen:
                continue
            position = self._find_alias_position(message_lower, alias_text.lower())
            if position is None:
                continue
            seen.add(normalized)
            matches.append((position, normalized))
        matches.sort(key=lambda item: item[0])
        return [normalized for _, normalized in matches]

    def _extract_message_execution_hints(self, state: TaskState) -> Dict[str, Any]:
        cached = getattr(state, "_message_execution_hints", None)
        if isinstance(cached, dict):
            return cached

        message = str(state.user_message or "").strip()
        message_lower = message.lower()
        standardizer = self._get_message_standardizer()

        road_lookup = dict(standardizer.road_type_lookup)
        # End2end benchmark treats `expressway` as the blocked high-speed-road family.
        road_lookup["expressway"] = "高速公路"

        vehicle_match = self._find_best_alias_match(message, standardizer.vehicle_lookup)
        road_match = self._find_best_alias_match(message, road_lookup)
        season_match = self._find_best_alias_match(message, standardizer.season_lookup)
        meteorology_match = self._find_best_alias_match(message, standardizer.meteorology_lookup)
        stability_match = self._find_best_alias_match(message, standardizer.stability_lookup)
        pollutants = self._extract_pollutants_from_message(message)
        year_match = re.search(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", message)

        wants_factor = any(token in message_lower for token in ("排放因子", "emission factor"))
        wants_dispersion = any(token in message_lower for token in ("扩散", "dispersion", "浓度场"))
        wants_hotspot = any(token in message_lower for token in ("热点", "hotspot"))
        wants_map = any(token in message_lower for token in ("地图", "渲染", "展示", "可视化", "map", "render"))
        wants_emission = any(token in message_lower for token in ("排放", "emission"))

        desired_tool_chain: List[str] = []
        if wants_factor:
            desired_tool_chain.append("query_emission_factors")
        else:
            grounded_task_type = str(state.file_context.task_type or "").strip()
            if grounded_task_type == "micro_emission" and wants_emission:
                desired_tool_chain.append("calculate_micro_emission")
            elif grounded_task_type == "macro_emission" and (wants_emission or wants_dispersion or wants_hotspot or wants_map):
                desired_tool_chain.append("calculate_macro_emission")

        if wants_dispersion:
            desired_tool_chain.append("calculate_dispersion")
        if wants_hotspot:
            desired_tool_chain.append("analyze_hotspots")
        if wants_map:
            desired_tool_chain.append("render_spatial_map")

        hints = {
            "message": message,
            "vehicle_type": vehicle_match[1] if vehicle_match else None,
            "vehicle_type_raw": vehicle_match[0] if vehicle_match else None,
            "road_type": road_match[1] if road_match else None,
            "road_type_raw": road_match[0] if road_match else None,
            "season": season_match[1] if season_match else None,
            "season_raw": season_match[0] if season_match else None,
            "meteorology": meteorology_match[1] if meteorology_match else None,
            "meteorology_raw": meteorology_match[0] if meteorology_match else None,
            "stability_class": stability_match[1] if stability_match else None,
            "stability_class_raw": stability_match[0] if stability_match else None,
            "pollutants": pollutants,
            "model_year": int(year_match.group(1)) if year_match else None,
            "wants_factor": wants_factor,
            "wants_emission": wants_emission,
            "wants_dispersion": wants_dispersion,
            "wants_hotspot": wants_hotspot,
            "wants_map": wants_map,
            "desired_tool_chain": list(dict.fromkeys(desired_tool_chain)),
        }
        setattr(state, "_message_execution_hints", hints)
        return hints

    def _seed_explicit_message_parameter_locks(self, state: TaskState) -> None:
        hints = self._extract_message_execution_hints(state)
        lockable_fields = {
            "vehicle_type": ("vehicle_type", "vehicle_type_raw"),
            "road_type": ("road_type", "road_type_raw"),
            "season": ("season", "season_raw"),
            "meteorology": ("meteorology", "meteorology_raw"),
            "stability_class": ("stability_class", "stability_class_raw"),
        }
        for param_name, (normalized_key, raw_key) in lockable_fields.items():
            normalized_value = hints.get(normalized_key)
            if not normalized_value:
                continue
            state.apply_parameter_lock(
                parameter_name=param_name,
                normalized_value=str(normalized_value),
                raw_value=str(hints.get(raw_key) or normalized_value),
                lock_source="explicit_user_message",
            )

    def _set_direct_user_response_state(
        self,
        state: TaskState,
        text: str,
        *,
        stage: TaskStage,
        stage_before: TaskStage,
        reason: str,
        trace_obj: Optional[Trace] = None,
        trace_step_type: Optional[TraceStepType] = None,
    ) -> None:
        state.control.needs_user_input = stage in {
            TaskStage.NEEDS_CLARIFICATION,
            TaskStage.NEEDS_INPUT_COMPLETION,
            TaskStage.NEEDS_PARAMETER_CONFIRMATION,
        }
        state.control.clarification_question = text if stage == TaskStage.NEEDS_CLARIFICATION else None
        state.control.input_completion_prompt = text if stage == TaskStage.NEEDS_INPUT_COMPLETION else None
        state.control.parameter_confirmation_prompt = (
            text if stage == TaskStage.NEEDS_PARAMETER_CONFIRMATION else None
        )
        setattr(state, "_final_response_text", text)
        self._transition_state(
            state,
            stage,
            reason=reason,
            trace_obj=trace_obj,
        )
        if trace_obj and trace_step_type is not None:
            trace_obj.record(
                step_type=trace_step_type,
                stage_before=stage_before.value,
                stage_after=stage.value,
                reasoning=text,
            )

    def _build_missing_input_clarification(self, state: TaskState) -> Optional[str]:
        hints = self._extract_message_execution_hints(state)
        desired_chain = list(hints.get("desired_tool_chain") or [])
        if not desired_chain:
            return None

        next_tool = desired_chain[0]
        if next_tool == "query_emission_factors":
            if not hints.get("vehicle_type"):
                return "要查询排放因子，我还需要车型。请告诉我是 Passenger Car、Transit Bus、Motorcycle 等哪一类车辆。"
            if not hints.get("pollutants"):
                return "要查询排放因子，我还需要污染物类型。请说明是 CO2、NOx、PM2.5，还是其它污染物。"
            if hints.get("model_year") is None:
                return "要查询排放因子，我还需要车型年份。请告诉我例如 2020、2021 这样的年份。"
            return None

        completed_tools = list(state.execution.completed_tools or [])
        if next_tool == "calculate_dispersion" and "calculate_macro_emission" not in completed_tools:
            if state.file_context.has_file and str(state.file_context.task_type or "").strip() == "macro_emission":
                return None
            return "做扩散分析前，我需要路网排放结果。你可以上传路网文件让我先算排放，或直接说明要基于哪一份排放结果继续。"
        if next_tool == "analyze_hotspots" and "calculate_dispersion" not in completed_tools:
            return "做热点分析前，我需要一份扩散结果。你可以先让我运行扩散分析，或告诉我你要使用的已有浓度场结果。"
        if next_tool == "render_spatial_map" and not completed_tools and not state.file_context.has_file:
            return "画地图前，我需要一份可视化对象。请告诉我要渲染排放结果、扩散结果还是热点结果，或者先上传对应数据文件。"
        return None

    def _build_deterministic_fallback_tool_call(self, state: TaskState) -> Optional[LLMResponse]:
        hints = self._extract_message_execution_hints(state)
        desired_chain = list(hints.get("desired_tool_chain") or [])
        if not desired_chain:
            return None

        completed_tools = list(state.execution.completed_tools or [])
        next_tool = next((tool for tool in desired_chain if tool not in completed_tools), None)
        if not next_tool:
            return None

        arguments: Dict[str, Any] = {}
        if next_tool == "query_emission_factors":
            if not hints.get("vehicle_type") or not hints.get("pollutants") or hints.get("model_year") is None:
                return None
            arguments = {
                "vehicle_type": hints["vehicle_type_raw"] or hints["vehicle_type"],
                "model_year": hints["model_year"],
                "pollutants": list(hints["pollutants"]),
            }
            if hints.get("season"):
                arguments["season"] = hints["season_raw"] or hints["season"]
            if hints.get("road_type"):
                arguments["road_type"] = hints["road_type_raw"] or hints["road_type"]

        elif next_tool in {"calculate_macro_emission", "calculate_micro_emission"}:
            if not state.file_context.has_file or not state.file_context.grounded:
                return None
            if hints.get("pollutants"):
                arguments["pollutants"] = list(hints["pollutants"])
            if hints.get("model_year") is not None:
                arguments["model_year"] = hints["model_year"]
            if hints.get("season"):
                arguments["season"] = hints["season_raw"] or hints["season"]
            if hints.get("vehicle_type"):
                arguments["vehicle_type"] = hints["vehicle_type_raw"] or hints["vehicle_type"]
            if hints.get("road_type"):
                arguments["road_type"] = hints["road_type_raw"] or hints["road_type"]

        elif next_tool == "calculate_dispersion":
            arguments = {}
            if hints.get("meteorology"):
                arguments["meteorology"] = hints["meteorology_raw"] or hints["meteorology"]
            if hints.get("stability_class"):
                arguments["stability_class"] = hints["stability_class_raw"] or hints["stability_class"]
            if hints.get("pollutants"):
                arguments["pollutant"] = hints["pollutants"][0]

        elif next_tool == "analyze_hotspots":
            arguments = {}

        elif next_tool == "render_spatial_map":
            if "analyze_hotspots" in completed_tools:
                arguments["layer_type"] = "hotspot"
            elif "calculate_dispersion" in completed_tools:
                arguments["layer_type"] = "dispersion"
            else:
                arguments["layer_type"] = "emission"
            if hints.get("pollutants"):
                arguments["pollutant"] = hints["pollutants"][0]
        else:
            return None

        return LLMResponse(
            content="",
            tool_calls=[
                ToolCall(
                    id=f"deterministic_{next_tool}",
                    name=next_tool,
                    arguments=arguments,
                )
            ],
            finish_reason="tool_calls",
        )

    def _maybe_recover_missing_tool_call(
        self,
        state: TaskState,
        *,
        stage_before: TaskStage,
        trace_obj: Optional[Trace] = None,
    ) -> bool:
        clarification = self._build_missing_input_clarification(state)
        if clarification:
            self._set_direct_user_response_state(
                state,
                clarification,
                stage=TaskStage.NEEDS_CLARIFICATION,
                stage_before=stage_before,
                reason="Deterministic clarification applied after a no-tool LLM reply",
                trace_obj=trace_obj,
                trace_step_type=TraceStepType.CLARIFICATION,
            )
            return True

        fallback_response = self._build_deterministic_fallback_tool_call(state)
        if fallback_response is None or not fallback_response.tool_calls:
            return False

        state._llm_response = fallback_response
        state.execution.selected_tool = fallback_response.tool_calls[0].name
        self._capture_tool_call_parameters(state, fallback_response.tool_calls)
        if trace_obj:
            tool_names = [tool_call.name for tool_call in fallback_response.tool_calls]
            trace_obj.record(
                step_type=TraceStepType.TOOL_SELECTION,
                stage_before=stage_before.value,
                stage_after=TaskStage.GROUNDED.value if stage_before == TaskStage.INPUT_RECEIVED else TaskStage.EXECUTING.value,
                action=", ".join(tool_names),
                reasoning=(
                    "Deterministic fallback selected tool(s) after the LLM replied without tool calls: "
                    + ", ".join(tool_names)
                ),
            )
        if stage_before == TaskStage.INPUT_RECEIVED:
            self._transition_state(
                state,
                TaskStage.GROUNDED,
                reason="Recovered execution path after no-tool LLM reply",
                trace_obj=trace_obj,
            )
        return True

    def _should_force_explicit_tool_execution(
        self,
        state: TaskState,
        tool_name: str,
    ) -> bool:
        hints = self._extract_message_execution_hints(state)
        desired_chain = list(hints.get("desired_tool_chain") or [])
        if tool_name not in desired_chain or tool_name in set(state.execution.completed_tools or []):
            return False
        if tool_name == "render_spatial_map" and hints.get("wants_map"):
            return True
        return False

    @staticmethod
    def _build_cross_constraint_record(violation: Any, *, success: bool) -> Dict[str, Any]:
        strategy = "cross_constraint_warning" if success else "cross_constraint_violation"
        return {
            "param": f"{violation.param_a_name}+{violation.param_b_name}",
            "success": success,
            "original": f"{violation.param_a_value} | {violation.param_b_value}",
            "normalized": f"{violation.param_a_value} | {violation.param_b_value}",
            "strategy": strategy,
            "confidence": 1.0,
            "record_type": strategy,
            "constraint_name": violation.constraint_name,
            "violation_type": violation.violation_type,
            "reason": violation.reason,
            "suggestions": list(violation.suggestions),
        }

    def _evaluate_cross_constraint_preflight(
        self,
        state: TaskState,
        tool_name: str,
        effective_arguments: Dict[str, Any],
        *,
        trace_obj: Optional[Trace] = None,
    ) -> bool:
        standardizer = self._get_message_standardizer()
        hints = self._extract_message_execution_hints(state)

        standardized_params: Dict[str, Any] = {}
        if effective_arguments.get("vehicle_type") or hints.get("vehicle_type"):
            vehicle_raw = str(
                effective_arguments.get("vehicle_type")
                or hints.get("vehicle_type_raw")
                or hints.get("vehicle_type")
            )
            vehicle_result = standardizer.standardize_vehicle_detailed(vehicle_raw)
            if vehicle_result.success and vehicle_result.normalized:
                standardized_params["vehicle_type"] = vehicle_result.normalized

        if effective_arguments.get("road_type") or hints.get("road_type"):
            road_raw = str(
                effective_arguments.get("road_type")
                or hints.get("road_type_raw")
                or hints.get("road_type")
            )
            road_result = standardizer.standardize_road_type(road_raw)
            if road_result.success and road_result.normalized:
                standardized_params["road_type"] = road_result.normalized

        if effective_arguments.get("season") or hints.get("season"):
            season_raw = str(
                effective_arguments.get("season")
                or hints.get("season_raw")
                or hints.get("season")
            )
            season_result = standardizer.standardize_season(season_raw)
            if season_result.success and season_result.normalized:
                standardized_params["season"] = season_result.normalized

        if effective_arguments.get("meteorology") or hints.get("meteorology"):
            meteorology_raw = str(
                effective_arguments.get("meteorology")
                or hints.get("meteorology_raw")
                or hints.get("meteorology")
            )
            meteorology_result = standardizer.standardize_meteorology(meteorology_raw)
            if meteorology_result.success and meteorology_result.normalized:
                standardized_params["meteorology"] = meteorology_result.normalized

        if effective_arguments.get("pollutant"):
            pollutant_raw = str(effective_arguments.get("pollutant"))
            pollutant_result = standardizer.standardize_pollutant_detailed(pollutant_raw)
            if pollutant_result.success and pollutant_result.normalized:
                standardized_params["pollutant"] = pollutant_result.normalized

        if isinstance(effective_arguments.get("pollutants"), list):
            normalized_pollutants: List[Any] = []
            for item in effective_arguments.get("pollutants", []):
                if item is None or not isinstance(item, str):
                    normalized_pollutants.append(item)
                    continue
                pollutant_result = standardizer.standardize_pollutant_detailed(item)
                normalized_pollutants.append(
                    pollutant_result.normalized
                    if pollutant_result.success and pollutant_result.normalized
                    else item
                )
            if normalized_pollutants:
                standardized_params["pollutants"] = normalized_pollutants

        if not standardized_params:
            return False

        constraint_result = get_cross_constraint_validator().validate(
            standardized_params,
            tool_name=tool_name,
        )
        if constraint_result.warnings and trace_obj:
            trace_obj.record(
                step_type=TraceStepType.CROSS_CONSTRAINT_WARNING,
                stage_before=TaskStage.EXECUTING.value,
                action=tool_name,
                input_summary={"standardized_params": dict(standardized_params)},
                standardization_records=[
                    self._build_cross_constraint_record(warning, success=True)
                    for warning in constraint_result.warnings
                ],
                reasoning="Cross-parameter warning detected during router preflight.",
            )

        if not constraint_result.violations:
            return False

        violation = constraint_result.violations[0]
        suggestions = list(violation.suggestions or [])
        suggestion_text = (
            "\n\nDid you mean one of these? " + ", ".join(suggestions[:5])
            if suggestions
            else ""
        )
        message = f"参数组合不合法: {violation.reason}{suggestion_text}"
        state.execution.blocked_info = {
            "message": message,
            "constraint_name": violation.constraint_name,
            "suggestions": suggestions,
        }
        state.execution.last_error = violation.reason
        setattr(state, "_final_response_text", message)
        self._transition_state(
            state,
            TaskStage.DONE,
            reason=f"Cross constraint blocked execution before {tool_name}",
            trace_obj=trace_obj,
        )
        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.CROSS_CONSTRAINT_VIOLATION,
                stage_before=TaskStage.EXECUTING.value,
                stage_after=TaskStage.DONE.value,
                action=tool_name,
                input_summary={"standardized_params": dict(standardized_params)},
                standardization_records=[
                    self._build_cross_constraint_record(violation, success=False)
                ],
                reasoning=violation.reason,
                error=violation.reason,
            )
        return True

    def _extract_key_stats(self, tool_name: str, data: Dict[str, Any]) -> str:
        """Extract only the numbers the LLM needs for a final natural-language reply."""
        if not isinstance(data, dict):
            return ""

        stats: List[str] = []
        summary = data.get("summary", {})
        if isinstance(summary, dict):
            if "total_links" in summary:
                stats.append(f"{summary['total_links']} links")
            total_emissions = summary.get("total_emissions_kg_per_hr")
            if isinstance(total_emissions, dict):
                for pollutant, value in list(total_emissions.items())[:6]:
                    if isinstance(value, (int, float)):
                        stats.append(f"{pollutant}: {value:.2f} kg/h")
            if "receptor_count" in summary:
                stats.append(f"{summary['receptor_count']} receptors")
            if "mean_concentration" in summary and isinstance(summary["mean_concentration"], (int, float)):
                stats.append(f"mean={summary['mean_concentration']:.4f} μg/m³")
            if "max_concentration" in summary and isinstance(summary["max_concentration"], (int, float)):
                stats.append(f"max={summary['max_concentration']:.4f} μg/m³")
            if "hotspot_count" in summary:
                stats.append(f"{summary['hotspot_count']} hotspots")

        coverage = data.get("coverage_assessment")
        if isinstance(coverage, dict) and coverage.get("warnings"):
            stats.append(f"{len(coverage['warnings'])} coverage warnings")

        defaults = data.get("defaults_used")
        if isinstance(defaults, dict) and defaults:
            stats.append(f"defaults: {', '.join(str(key) for key in list(defaults.keys())[:6])}")
        elif isinstance(defaults, list) and defaults:
            names = [
                str(item.get("parameter"))
                for item in defaults[:6]
                if isinstance(item, dict) and item.get("parameter")
            ]
            if names:
                stats.append(f"defaults: {', '.join(names)}")

        scenario_label = data.get("scenario_label")
        if isinstance(scenario_label, str) and scenario_label and scenario_label != "baseline":
            stats.append(f"scenario={scenario_label}")

        return "; ".join(stats)

    def _build_tool_result_message(self, tool_name: str, result: Dict[str, Any], tool_call_id: str) -> Dict[str, Any]:
        """Build a compact tool-role message for LLM follow-up decisions."""
        success = bool(result.get("success"))
        summary = str(result.get("summary") or result.get("message") or f"{tool_name} completed").strip()
        if len(summary) > 600:
            summary = summary[:597].rstrip() + "..."

        key_stats = self._extract_key_stats(tool_name, result.get("data", {}))
        parts = [
            f"Tool: {tool_name}",
            f"Status: {'success' if success else 'error'}",
            f"Result: {summary}",
        ]
        if key_stats:
            parts.append(f"Key stats: {key_stats}")
        if result.get("error") and str(result.get("error")) not in summary:
            parts.append(f"Error: {str(result.get('error'))[:180]}")

        content = "\n".join(parts)
        if len(content) > 1000:
            content = content[:997].rstrip() + "..."
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        }

    async def chat(
        self,
        user_message: str,
        file_path: Optional[str] = None,
        trace: Optional[Dict[str, Any]] = None,
    ) -> RouterResponse:
        self._ensure_context_store().clear_current_turn()
        config = get_config()
        if config.enable_state_orchestration:
            fast_path_response = await self._maybe_handle_conversation_fast_path(
                user_message,
                file_path,
                trace,
            )
            if fast_path_response is not None:
                return fast_path_response
            return await self._run_state_loop(user_message, file_path, trace)
        else:
            return await self._run_legacy_loop(user_message, file_path, trace)

    async def _run_legacy_loop(
        self,
        user_message: str,
        file_path: Optional[str] = None,
        trace: Optional[Dict[str, Any]] = None,
    ) -> RouterResponse:
        """
        Process user message

        Flow:
        1. Assemble context (prompt + tools + memory + file)
        2. Call LLM with Tool Use
        3. If tool calls → execute → synthesize
        4. If direct response → return
        5. Update memory

        Args:
            user_message: User's message
            file_path: Optional uploaded file path

        Returns:
            RouterResponse with text and optional data
        """
        logger.info(f"Processing message: {user_message[:50]}...")
        start_time = time.perf_counter()
        if trace is not None:
            trace.clear()
            trace["input"] = {
                "user_message": user_message,
                "file_path": file_path,
            }

        # 1. Analyze file if provided (use cache when available)
        file_context = None
        if file_path:
            from pathlib import Path
            import os

            cached = self.memory.get_fact_memory().get("file_analysis")
            file_path_str = str(file_path)

            # Check if file exists and get its modification time
            try:
                current_mtime = os.path.getmtime(file_path_str)
            except Exception:
                current_mtime = None

            # Use cache only if path and mtime match
            cache_valid = (
                cached
                and str(cached.get("file_path")) == file_path_str
                and cached.get("file_mtime") == current_mtime
            )

            if self.runtime_config.enable_file_analyzer and cache_valid:
                file_context = cached
                logger.info(f"Using cached file analysis for {file_path}")
            elif self.runtime_config.enable_file_analyzer:
                file_context = await self._analyze_file(file_path)
                # Store path and mtime to detect file changes
                file_context["file_path"] = file_path_str
                file_context["file_mtime"] = current_mtime
                logger.info(f"Analyzed new file: {file_path} (mtime: {current_mtime})")
            else:
                file_context = {
                    "filename": Path(file_path_str).name,
                    "file_path": file_path_str,
                    "task_type": None,
                    "confidence": 0.0,
                }
                logger.info("File analyzer disabled by runtime config")
            # Diagnostic: log memory state when file is uploaded
            wm = self.memory.get_working_memory()
            fm = self.memory.get_fact_memory()
            logger.info(
                f"[FILE UPLOAD] working_memory_turns={len(wm)}, "
                f"fact_memory={fm}, "
                f"file_task_type={file_context.get('task_type') or file_context.get('detected_type')}"
            )
        if trace is not None:
            trace["file_analysis"] = file_context
            trace["runtime_flags"] = {
                "enable_file_analyzer": self.runtime_config.enable_file_analyzer,
                "enable_file_context_injection": self.runtime_config.enable_file_context_injection,
                "enable_executor_standardization": self.runtime_config.enable_executor_standardization,
                "macro_column_mapping_modes": list(self.runtime_config.macro_column_mapping_modes),
            }

        # 2. Assemble context
        context = self.assembler.assemble(
            user_message=user_message,
            working_memory=self.memory.get_working_memory(),
            fact_memory=self.memory.get_fact_memory(),
            file_context=file_context,
            context_summary=self._get_context_summary(),
            memory_context=self._get_memory_context_for_prompt(),
        )
        if trace is not None:
            trace["assembled_context"] = {
                "message_count": len(context.messages),
                "estimated_tokens": context.estimated_tokens,
                "file_context_injected": bool(file_context and self.runtime_config.enable_file_context_injection),
                "last_user_message": context.messages[-1]["content"] if context.messages else None,
            }

        # 3. Call LLM with Tool Use
        response = await self.llm.chat_with_tools(
            messages=context.messages,
            tools=context.tools,
            system=context.system_prompt
        )
        if trace is not None:
            trace["routing"] = {
                "raw_response_content": response.content,
                "tool_calls": [
                    {"name": tc.name, "arguments": tc.arguments}
                    for tc in (response.tool_calls or [])
                ],
            }

        # 4. Process response
        result = await self._process_response(
            response,
            context,
            file_path,
            tool_call_count=0,
            trace=trace,
        )

        # 5. Update memory
        tool_calls_data = result.executed_tool_calls
        if tool_calls_data is None and response.tool_calls:
            # Fallback: keep raw tool calls even if no execution result captured.
            tool_calls_data = [{"name": tc.name, "arguments": tc.arguments} for tc in response.tool_calls]

        self.memory.update(
            user_message=user_message,
            assistant_response=result.text,
            tool_calls=tool_calls_data,
            file_path=file_path,
            file_analysis=file_context
        )
        if trace is not None:
            trace["final"] = {
                "text": result.text,
                "has_chart_data": bool(result.chart_data),
                "has_table_data": bool(result.table_data),
                "has_map_data": bool(result.map_data),
                "has_download_file": bool(result.download_file),
                "tool_calls": tool_calls_data,
                "duration_ms": round((time.perf_counter() - start_time) * 1000, 2),
            }

        result.text = self._sanitize_response_text(result.text)

        if get_config().enable_trace and trace is not None:
            result.trace = trace

        return result

    async def _run_state_loop(
        self,
        user_message: str,
        file_path: Optional[str] = None,
        trace: Optional[Dict[str, Any]] = None,
    ) -> RouterResponse:
        config = get_config()

        fact_memory = self.memory.get_fact_memory()
        state = TaskState.initialize(
            user_message=user_message,
            file_path=file_path,
            memory_dict=fact_memory,
            session_id=self.session_id,
        )
        state.control.max_steps = config.max_orchestration_steps
        trace_obj = Trace.start(session_id=self.session_id) if config.enable_trace else None

        loop_guard = 0
        max_state_iterations = max(6, state.control.max_steps * 3)
        while not state.is_terminal() and loop_guard < max_state_iterations:
            loop_guard += 1
            if state.stage == TaskStage.INPUT_RECEIVED:
                await self._state_handle_input(state, trace_obj=trace_obj)
            elif state.stage == TaskStage.GROUNDED:
                await self._state_handle_grounded(state, trace_obj=trace_obj)
            elif state.stage == TaskStage.EXECUTING:
                await self._state_handle_executing(state, trace_obj=trace_obj)

        if not state.is_terminal():
            self._transition_state(
                state,
                TaskStage.DONE,
                reason="state loop guard reached",
                trace_obj=trace_obj,
            )

        if trace_obj:
            trace_obj.finish(final_stage=state.stage.value)

        response = await self._state_build_response(state, user_message, trace_obj=trace_obj)
        if trace_obj and getattr(config, "persist_trace", False):
            try:
                trace_obj.persist(session_id=self.session_id)
            except Exception as exc:
                logger.warning("Failed to persist trace: %s", exc)
        self._sync_live_continuation_state(state)

        tool_calls_data = None
        if state.execution.tool_results and not state.execution.tool_results[0].get("no_tool"):
            tool_calls_data = self._build_memory_tool_calls(state.execution.tool_results)

        file_context = state.file_context.to_dict() if state.file_context.grounded else None
        cached_file_context = getattr(state, "_file_analysis_cache", None)
        if file_context and isinstance(cached_file_context, dict):
            enriched_file_context = dict(cached_file_context)
            enriched_file_context.update(file_context)
            file_context = enriched_file_context

        memory_file_path, memory_file_analysis = self._resolve_memory_update_payload(
            state,
            raw_file_path=file_path,
            file_context=file_context,
        )
        self.memory.update(
            user_message,
            response.text,
            tool_calls_data,
            memory_file_path,
            memory_file_analysis,
        )

        if trace is not None and trace_obj:
            trace.update(trace_obj.to_dict())

        return response

    def _resolve_memory_update_payload(
        self,
        state: TaskState,
        *,
        raw_file_path: Optional[str],
        file_context: Optional[Dict[str, Any]],
    ) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
        if hasattr(state, "_memory_update_file_path"):
            resolved_file_path = getattr(state, "_memory_update_file_path")
        else:
            resolved_file_path = raw_file_path or state.file_context.file_path

        if hasattr(state, "_memory_update_file_analysis"):
            resolved_analysis = getattr(state, "_memory_update_file_analysis")
        else:
            resolved_analysis = file_context

        if not resolved_file_path and isinstance(file_context, dict):
            resolved_file_path = file_context.get("file_path")

        normalized_file_path = str(resolved_file_path).strip() if resolved_file_path else None
        if normalized_file_path is None:
            return None, None

        if isinstance(resolved_analysis, dict):
            analysis_payload = dict(resolved_analysis)
            analysis_payload["file_path"] = normalized_file_path
            return normalized_file_path, analysis_payload

        if isinstance(file_context, dict):
            analysis_payload = dict(file_context)
            analysis_payload["file_path"] = normalized_file_path
            return normalized_file_path, analysis_payload

        return normalized_file_path, None

    def _infer_delivery_turn_index(self) -> int:
        if hasattr(self, "memory") and hasattr(self.memory, "get_working_memory"):
            try:
                return len(self.memory.get_working_memory()) + 1
            except Exception:
                return 1
        return 1

    def _build_response_frontend_payloads(self, response: RouterResponse) -> Dict[str, Any]:
        return {
            "chart_data": response.chart_data,
            "table_data": response.table_data,
            "map_data": response.map_data,
            "download_file": response.download_file,
        }

    def _record_delivered_artifacts(
        self,
        state: TaskState,
        response: RouterResponse,
        *,
        trace_obj: Optional[Trace] = None,
        stage_before: str = TaskStage.DONE.value,
    ) -> None:
        if not getattr(self.runtime_config, "enable_artifact_memory", True):
            if trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.ARTIFACT_MEMORY_SKIPPED,
                    stage_before=stage_before,
                    action="artifact_memory_recording",
                    reasoning="Artifact memory recording is disabled by feature flag.",
                )
            return
        if not state.execution.tool_results:
            if trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.ARTIFACT_MEMORY_SKIPPED,
                    stage_before=stage_before,
                    action="artifact_memory_recording",
                    reasoning="No tool-backed delivery occurred in this turn, so artifact memory recording was skipped.",
                )
            return

        records = classify_artifacts_from_delivery(
            tool_results=state.execution.tool_results,
            frontend_payloads=self._build_response_frontend_payloads(response),
            response_text=response.text,
            delivery_turn_index=self._infer_delivery_turn_index(),
            related_task_type=state.file_context.task_type,
            track_textual_summary=getattr(
                self.runtime_config,
                "artifact_memory_track_textual_summary",
                True,
            ),
        )
        if not records:
            if trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.ARTIFACT_MEMORY_SKIPPED,
                    stage_before=stage_before,
                    action="artifact_memory_recording",
                    reasoning="The response did not contain a bounded artifact shape worth tracking.",
                )
            return

        previous_summary = state.get_artifact_memory_summary()
        for record in records:
            if trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.ARTIFACT_RECORDED,
                    stage_before=stage_before,
                    action=record.artifact_type.value,
                    output_summary=record.to_dict(),
                    reasoning=record.summary or "Recorded delivered artifact into bounded artifact memory.",
                )

        updated_memory = update_artifact_memory(state.artifact_memory_state, records)
        state.set_artifact_memory_state(updated_memory)

        cached_file_context = getattr(state, "_file_analysis_cache", None)
        if isinstance(cached_file_context, dict):
            cached_file_context["artifact_memory"] = updated_memory.to_dict()
            cached_file_context["artifact_memory_summary"] = updated_memory.to_summary()
            cached_file_context["latest_artifact_by_family"] = state.get_latest_artifact_by_family()
            cached_file_context["latest_artifact_by_type"] = state.get_latest_artifact_by_type()
            cached_file_context["recent_delivery_summary"] = state.get_recent_delivery_summary()
            setattr(state, "_file_analysis_cache", cached_file_context)

        if trace_obj is not None:
            trace_obj.record(
                step_type=TraceStepType.ARTIFACT_MEMORY_UPDATED,
                stage_before=stage_before,
                action="artifact_memory_recording",
                input_summary=previous_summary,
                output_summary=updated_memory.to_summary(),
                reasoning="Updated bounded artifact memory after actual result delivery.",
            )

    def _transition_state(
        self,
        state: TaskState,
        new_stage: TaskStage,
        reason: str = "",
        trace_obj: Optional[Trace] = None,
    ) -> None:
        stage_before = state.stage.value
        state.transition(new_stage, reason=reason)
        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.STATE_TRANSITION,
                stage_before=stage_before,
                stage_after=state.stage.value,
                reasoning=reason,
            )

    def _identify_critical_missing(self, state: TaskState) -> Optional[str]:
        """Identify the single most critical missing piece of information.

        Returns a clarification question string, or None if nothing is missing.
        Priority order:
        1. File type ambiguity (file uploaded but task_type is unknown)
        2. Standardization failure (a parameter couldn't be standardized)
        3. Missing required parameter (vehicle_type for micro, etc.)
        """
        if (
            state.file_context.has_file
            and state.file_context.grounded
            and state.file_context.task_type == "unknown"
        ):
            return (
                "I analyzed your uploaded file but couldn't determine the analysis type. "
                "Could you tell me: is this **trajectory data** (second-by-second vehicle records) "
                "for micro-scale emission calculation, or **road link data** (link-level traffic statistics) "
                "for macro-scale emission calculation?"
            )

        for param_name, entry in state.parameters.items():
            if entry.status.value == "AMBIGUOUS":
                return (
                    f"I need clarification on the {param_name}: '{entry.raw}'. "
                    f"Could you be more specific? For example, for vehicle types you can say: "
                    f"Passenger Car, Transit Bus, Combination Long-haul Truck, etc."
                )

        if (
            state.file_context.task_type == "micro_emission"
            and "vehicle_type" not in state.parameters
        ):
            return (
                "To calculate micro-scale emissions, I need to know the **vehicle type**. "
                "What type of vehicle is this trajectory from? "
                "For example: Passenger Car, Transit Bus, Light Commercial Truck, etc."
            )

        return None

    def _build_state_file_context(self, state: TaskState) -> Optional[Dict[str, Any]]:
        """Build the file-context payload for assembler calls within the state loop."""
        if not state.file_context.grounded:
            return None

        file_context = {
            "filename": Path(state.file_context.file_path).name if state.file_context.file_path else "unknown",
            "file_path": state.file_context.file_path,
            "task_type": state.file_context.task_type,
            "confidence": state.file_context.confidence if state.file_context.confidence is not None else 0.0,
            "columns": list(state.file_context.columns),
            "row_count": state.file_context.row_count,
            "sample_rows": state.file_context.sample_rows,
            "micro_mapping": state.file_context.micro_mapping,
            "macro_mapping": state.file_context.macro_mapping,
            "micro_has_required": state.file_context.micro_has_required,
            "macro_has_required": state.file_context.macro_has_required,
            "column_mapping": state.file_context.column_mapping,
            "evidence": list(state.file_context.evidence),
            "selected_primary_table": state.file_context.selected_primary_table,
            "dataset_roles": list(state.file_context.dataset_roles),
            "spatial_metadata": dict(state.file_context.spatial_metadata),
            "missing_field_diagnostics": dict(state.file_context.missing_field_diagnostics),
            "spatial_context": dict(state.file_context.spatial_context),
            "input_completion_overrides": state.get_input_completion_overrides_summary(),
            "attached_supporting_file": (
                state.attached_supporting_file.to_dict()
                if state.attached_supporting_file is not None
                else None
            ),
            "latest_file_relationship_decision": (
                state.latest_file_relationship_decision.to_dict()
                if state.latest_file_relationship_decision is not None
                else None
            ),
            "latest_supplemental_merge_plan": (
                state.latest_supplemental_merge_plan.to_dict()
                if state.latest_supplemental_merge_plan is not None
                else None
            ),
            "latest_supplemental_merge_result": (
                state.latest_supplemental_merge_result.to_dict()
                if state.latest_supplemental_merge_result is not None
                else None
            ),
            "latest_intent_resolution_decision": (
                state.latest_intent_resolution_decision.to_dict()
                if state.latest_intent_resolution_decision is not None
                else None
            ),
            "latest_intent_resolution_plan": (
                state.latest_intent_resolution_plan.to_dict()
                if state.latest_intent_resolution_plan is not None
                else None
            ),
            "latest_summary_delivery_plan": (
                state.latest_summary_delivery_plan.to_dict()
                if state.latest_summary_delivery_plan is not None
                else None
            ),
            "latest_summary_delivery_result": (
                state.latest_summary_delivery_result.to_dict()
                if state.latest_summary_delivery_result is not None
                else None
            ),
            "artifact_memory": state.artifact_memory_state.to_dict(),
            "artifact_memory_summary": state.get_artifact_memory_summary(),
            "latest_artifact_by_family": state.get_latest_artifact_by_family(),
            "latest_artifact_by_type": state.get_latest_artifact_by_type(),
            "recent_delivery_summary": state.get_recent_delivery_summary(),
        }
        cached_file_context = getattr(state, "_file_analysis_cache", None)
        if isinstance(cached_file_context, dict):
            cached_copy = dict(cached_file_context)
            cached_copy.update(file_context)
            file_context = cached_copy
        return file_context

    def _restore_state_file_context_from_analysis(
        self,
        state: TaskState,
        analysis_dict: Optional[Dict[str, Any]],
        *,
        file_path_override: Optional[str] = None,
    ) -> None:
        payload = dict(analysis_dict or {})
        override = str(file_path_override).strip() if file_path_override else None
        if override:
            payload["file_path"] = override

        if payload:
            state.update_file_context(payload)
            if isinstance(payload.get("artifact_memory"), dict):
                state.set_artifact_memory_state(ArtifactMemoryState.from_dict(payload.get("artifact_memory")))
            if isinstance(payload.get("latest_summary_delivery_plan"), dict):
                state.set_latest_summary_delivery_plan(
                    SummaryDeliveryPlan.from_dict(payload.get("latest_summary_delivery_plan"))
                )
            if isinstance(payload.get("latest_summary_delivery_result"), dict):
                state.set_latest_summary_delivery_result(
                    SummaryDeliveryResult.from_dict(payload.get("latest_summary_delivery_result"))
                )
            setattr(state, "_file_analysis_cache", dict(payload))
            return

        state.file_context.file_path = override
        state.file_context.has_file = bool(override)
        state.file_context.grounded = False

    def _set_state_file_context_to_ungrounded_file(
        self,
        state: TaskState,
        file_path: Optional[str],
    ) -> None:
        normalized_path = str(file_path).strip() if file_path else None
        state.file_context.file_path = normalized_path
        state.file_context.has_file = bool(normalized_path)
        state.file_context.grounded = False
        state.file_context.task_type = None
        state.file_context.confidence = None
        state.file_context.column_mapping = {}
        state.file_context.evidence = []
        state.file_context.row_count = None
        state.file_context.columns = []
        state.file_context.sample_rows = None
        state.file_context.micro_mapping = None
        state.file_context.macro_mapping = None
        state.file_context.micro_has_required = None
        state.file_context.macro_has_required = None
        state.file_context.selected_primary_table = None
        state.file_context.dataset_roles = []
        state.file_context.spatial_metadata = {}
        state.file_context.missing_field_diagnostics = {}
        state.file_context.spatial_context = {}

    def _clear_primary_field_completion_overrides(
        self,
        state: TaskState,
    ) -> Dict[str, Dict[str, Any]]:
        preserved: Dict[str, Dict[str, Any]] = {}
        for key, payload in state.get_input_completion_overrides_summary().items():
            mode = str(payload.get("mode") or "").strip().lower()
            if key == "geometry_support" or (mode == "uploaded_supporting_file" and key == "geometry_support"):
                preserved[key] = dict(payload)
        state.input_completion_overrides.clear()
        for key, payload in preserved.items():
            state.apply_input_completion_override(key=key, override=payload)
        return preserved

    def _capture_supplemental_merge_resume_snapshot(
        self,
        state: TaskState,
    ) -> Dict[str, Any]:
        bundle = self._ensure_live_input_completion_bundle()
        active_request = state.active_input_completion or self._load_active_input_completion_request()
        snapshot = {
            "plan": dict(bundle.get("plan")) if isinstance(bundle.get("plan"), dict) else None,
            "repair_history": [
                dict(item)
                for item in (bundle.get("repair_history") or [])
                if isinstance(item, dict)
            ],
            "blocked_info": dict(bundle.get("blocked_info") or {}) if isinstance(bundle.get("blocked_info"), dict) else None,
            "file_path": str(bundle.get("file_path") or "").strip() or None,
            "latest_repair_summary": str(bundle.get("latest_repair_summary") or "").strip() or None,
            "residual_plan_summary": str(bundle.get("residual_plan_summary") or "").strip() or None,
            "request": active_request.to_dict() if active_request is not None else None,
        }
        return snapshot

    def _restore_residual_plan_from_snapshot(
        self,
        state: TaskState,
        *,
        resume_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        snapshot = resume_snapshot if isinstance(resume_snapshot, dict) else {}
        plan_snapshot = snapshot.get("plan")

        if isinstance(plan_snapshot, dict):
            plan = ExecutionPlan.from_dict(plan_snapshot)
            repair_history = [
                PlanRepairDecision.from_dict(item)
                for item in (snapshot.get("repair_history") or [])
                if isinstance(item, dict)
            ]
            blocked_info = (
                dict(snapshot.get("blocked_info") or {})
                if isinstance(snapshot.get("blocked_info"), dict)
                else None
            )
            latest_repair_summary = (
                str(snapshot.get("latest_repair_summary") or "").strip() or None
            )
            residual_plan_summary = (
                str(snapshot.get("residual_plan_summary") or "").strip() or None
            )
        else:
            plan, repair_history, blocked_info, _previous_file_path = self._load_live_residual_plan()
            if plan is None:
                return None
            latest_repair_summary = self._ensure_live_continuation_bundle().get("latest_repair_summary")
            residual_plan_summary = self._ensure_live_continuation_bundle().get("residual_plan_summary")

        if plan is None or not plan.has_pending_steps():
            return None

        state.set_plan(plan)
        state.repair_history = repair_history
        state.execution.blocked_info = blocked_info
        self._refresh_execution_plan_state(state)

        continuation_bundle = self._ensure_live_continuation_bundle()
        continuation_bundle.update(
            {
                "plan": plan.to_dict(),
                "repair_history": [item.to_dict() for item in repair_history],
                "blocked_info": blocked_info,
                "file_path": state.file_context.file_path or snapshot.get("file_path"),
                "latest_repair_summary": latest_repair_summary,
                "residual_plan_summary": residual_plan_summary,
            }
        )
        return {
            "latest_repair_summary": latest_repair_summary,
            "residual_plan_summary": residual_plan_summary,
            "blocked_info": blocked_info,
        }

    def _build_supplemental_merge_resume_decision(
        self,
        state: TaskState,
        *,
        restored_context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ContinuationDecision]:
        if state.plan is None or not state.plan.has_pending_steps():
            return None

        next_step = state.get_next_planned_step()
        context_payload = restored_context if isinstance(restored_context, dict) else {}
        return ContinuationDecision(
            residual_plan_exists=True,
            continuation_ready=True,
            should_continue=True,
            should_replan=False,
            prompt_variant=self._resolve_continuation_prompt_variant(),
            signal="supplemental_merge_resume",
            reason="supplemental merge refreshed the current file context and restored the residual workflow",
            next_step_id=next_step.step_id if next_step is not None else None,
            next_tool_name=next_step.tool_name if next_step is not None else None,
            latest_repair_summary=(
                str(context_payload.get("latest_repair_summary") or "").strip() or None
            ),
            residual_plan_summary=(
                str(context_payload.get("residual_plan_summary") or "").strip() or None
            ),
            latest_blocked_reason=(
                str((context_payload.get("blocked_info") or {}).get("message")).strip()
                if isinstance(context_payload.get("blocked_info"), dict)
                and (context_payload.get("blocked_info") or {}).get("message")
                else None
            ),
        )

    def _build_supplemental_merge_context(
        self,
        state: TaskState,
        relationship_context: FileRelationshipResolutionContext,
        decision: FileRelationshipDecision,
    ) -> SupplementalMergeContext:
        current_primary_analysis = getattr(state, "_file_relationship_current_primary_analysis", None)
        upload_analysis = getattr(state, "_file_relationship_upload_analysis", None)
        primary_summary = (
            relationship_context.current_primary_file.to_dict()
            if relationship_context.current_primary_file is not None
            else {}
        )
        supplemental_summary = (
            relationship_context.latest_uploaded_file.to_dict()
            if relationship_context.latest_uploaded_file is not None
            else {}
        )
        primary_diagnostics = (
            dict((current_primary_analysis or {}).get("missing_field_diagnostics") or {})
            if isinstance(current_primary_analysis, dict)
            else {}
        )
        target_missing_fields = _extract_missing_fields(primary_diagnostics)
        residual_summary = (
            state.get_residual_plan_summary()
            or str(self._ensure_live_input_completion_bundle().get("residual_plan_summary") or "").strip()
            or str(self._ensure_live_continuation_bundle().get("residual_plan_summary") or "").strip()
            or None
        )
        return SupplementalMergeContext(
            primary_file_summary=primary_summary,
            supplemental_file_summary=supplemental_summary,
            primary_file_analysis=dict(current_primary_analysis or {}),
            supplemental_file_analysis=dict(upload_analysis or {}),
            current_task_type=relationship_context.current_task_type,
            target_missing_canonical_fields=target_missing_fields,
            current_residual_workflow_summary=residual_summary,
            relationship_decision_summary=decision.to_dict(),
        )

    def _build_supplemental_merge_readiness_refresh_result(
        self,
        *,
        request: Optional[InputCompletionRequest],
        affordance: Optional[ActionAffordance],
        assessment: Optional[ReadinessAssessment],
        diagnostics: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        after_status = affordance.status.value if affordance is not None else "unknown"
        after_reason_code = affordance.reason.reason_code if affordance and affordance.reason else None
        remaining_missing_fields = [
            str(item.get("field") or "").strip()
            for item in (diagnostics or {}).get("missing_fields", [])
            if isinstance(item, dict) and str(item.get("field") or "").strip()
        ]
        return {
            "action_id": request.action_id if request is not None else None,
            "action_display_name": affordance.display_name if affordance is not None else None,
            "before_status": (
                ReadinessStatus.REPAIRABLE.value
                if request is not None
                else "unknown"
            ),
            "before_reason_code": (
                request.reason_code.value
                if request is not None and request.reason_code is not None
                else None
            ),
            "after_status": after_status,
            "after_reason_code": after_reason_code,
            "status_delta": (
                f"{ReadinessStatus.REPAIRABLE.value}->{after_status}"
                if request is not None
                else f"unknown->{after_status}"
            ),
            "remaining_missing_fields": remaining_missing_fields,
            "workflow_actionable": after_status == ReadinessStatus.READY.value,
            "available_action_count": len(assessment.available_actions) if assessment is not None else None,
            "repairable_action_count": len(assessment.repairable_actions) if assessment is not None else None,
        }

    def _build_supplemental_merge_user_text(
        self,
        *,
        plan: SupplementalMergePlan,
        result: SupplementalMergeResult,
        readiness_refresh_result: Dict[str, Any],
    ) -> str:
        merge_key = plan.merge_keys[0] if plan.merge_keys else None
        merge_key_label = (
            merge_key.primary_column
            if merge_key is not None and merge_key.primary_column
            else "主键"
        )
        merged_fields = [
            f"`{field}`"
            for field in result.merged_columns[:4]
        ]
        merged_fragment = "、".join(merged_fields) if merged_fields else "目标字段"
        after_status = str(readiness_refresh_result.get("after_status") or "").strip().lower()
        action_name = (
            str(readiness_refresh_result.get("action_display_name") or "").strip()
            or str(readiness_refresh_result.get("action_id") or "").strip()
            or "当前工作流"
        )
        if after_status == ReadinessStatus.READY.value:
            return (
                f"已将补充文件按 `{merge_key_label}` 合并到当前主数据中，并补齐 {merged_fragment}。"
                f" 当前工作流已可继续进行{action_name}。"
            )

        remaining_missing = [
            str(item).strip()
            for item in (readiness_refresh_result.get("remaining_missing_fields") or [])
            if str(item).strip()
        ]
        if remaining_missing:
            return (
                f"已按 `{merge_key_label}` 合并补充文件，并导入 {merged_fragment}，"
                f" 但当前工作流仍未完全就绪：仍缺少 {', '.join(remaining_missing)}。"
            )

        return (
            f"已按 `{merge_key_label}` 合并补充文件，并导入 {merged_fragment}，"
            f" 但当前工作流尚未恢复到可直接执行状态。"
        )

    def _message_has_file_relationship_cue(self, message: Optional[str]) -> bool:
        normalized = str(message or "").strip().lower()
        if not normalized:
            return False
        cues = (
            "发错",
            "重新上传",
            "用这个新的",
            "换成这个",
            "替换",
            "补充文件",
            "配套",
            "gis",
            "shapefile",
            "geojson",
            "补一列",
            "补充列",
            "补充表",
            "合并",
            "merge",
            "use this new",
            "replace",
            "supporting file",
            "use this",
            "this one",
        )
        return any(cue in normalized for cue in cues)

    def _get_file_relationship_current_primary_path(
        self,
        state: TaskState,
    ) -> Optional[str]:
        relationship_bundle = self._ensure_live_file_relationship_bundle()
        pending_primary_summary = relationship_bundle.get("pending_primary_summary")
        if relationship_bundle.get("awaiting_clarification") and isinstance(pending_primary_summary, dict):
            pending_path = str(pending_primary_summary.get("file_path") or "").strip()
            if pending_path:
                return pending_path

        candidates = [
            self._ensure_live_input_completion_bundle().get("file_path"),
            self._ensure_live_continuation_bundle().get("file_path"),
            self.memory.get_fact_memory().get("active_file"),
        ]
        for item in candidates:
            normalized = str(item or "").strip()
            if normalized:
                return normalized

        current_file_path = str(state.file_context.file_path or "").strip() or None
        incoming_file_path = str(state.incoming_file_path or "").strip() or None
        if current_file_path and incoming_file_path and current_file_path == incoming_file_path:
            return None
        return current_file_path

    def _get_file_relationship_current_primary_analysis(
        self,
        state: TaskState,
    ) -> Optional[Dict[str, Any]]:
        current_primary_path = self._get_file_relationship_current_primary_path(state)
        relationship_bundle = self._ensure_live_file_relationship_bundle()
        if relationship_bundle.get("awaiting_clarification") and isinstance(
            relationship_bundle.get("pending_primary_analysis"),
            dict,
        ):
            pending_primary_analysis = dict(relationship_bundle["pending_primary_analysis"])
            analysis_path = str(pending_primary_analysis.get("file_path") or "").strip() or None
            if not current_primary_path or analysis_path == current_primary_path:
                return pending_primary_analysis

        candidates = [
            self._ensure_live_input_completion_bundle().get("recovered_file_context"),
            self.memory.get_fact_memory().get("file_analysis"),
            getattr(state, "_file_analysis_cache", None),
        ]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            candidate_path = str(candidate.get("file_path") or "").strip() or None
            if current_primary_path is None or candidate_path == current_primary_path:
                return dict(candidate)
        return None

    async def _get_file_relationship_upload_analysis(
        self,
        state: TaskState,
    ) -> Optional[Dict[str, Any]]:
        relationship_bundle = self._ensure_live_file_relationship_bundle()
        incoming_file_path = str(state.incoming_file_path or "").strip() or None

        if not incoming_file_path:
            pending_analysis = relationship_bundle.get("pending_upload_analysis")
            if isinstance(pending_analysis, dict):
                return dict(pending_analysis)
            return None

        cached_analysis = getattr(state, "_pending_file_relationship_upload_analysis", None)
        if isinstance(cached_analysis, dict):
            cached_path = str(cached_analysis.get("file_path") or "").strip() or None
            if cached_path == incoming_file_path:
                return dict(cached_analysis)

        bundle_analysis = relationship_bundle.get("pending_upload_analysis")
        if isinstance(bundle_analysis, dict):
            bundle_path = str(bundle_analysis.get("file_path") or "").strip() or None
            if bundle_path == incoming_file_path:
                setattr(state, "_pending_file_relationship_upload_analysis", dict(bundle_analysis))
                return dict(bundle_analysis)

        if getattr(self.runtime_config, "enable_file_analyzer", True):
            analysis_dict = await self._analyze_file(incoming_file_path)
        else:
            analysis_dict = {
                "filename": Path(incoming_file_path).name,
                "file_path": incoming_file_path,
                "format": Path(incoming_file_path).suffix.lower().lstrip("."),
                "task_type": None,
                "confidence": 0.0,
            }

        analysis_dict["file_path"] = incoming_file_path
        setattr(state, "_pending_file_relationship_upload_analysis", dict(analysis_dict))
        return analysis_dict

    async def _build_file_relationship_resolution_context(
        self,
        state: TaskState,
    ) -> FileRelationshipResolutionContext:
        current_primary_analysis = self._get_file_relationship_current_primary_analysis(state)
        upload_analysis = await self._get_file_relationship_upload_analysis(state)
        relationship_bundle = self._ensure_live_file_relationship_bundle()

        current_primary_summary = None
        current_primary_path = self._get_file_relationship_current_primary_path(state)
        if current_primary_analysis is not None:
            current_primary_summary = FileRelationshipFileSummary.from_analysis(
                current_primary_analysis,
                role_candidate="current_primary",
                source="live_primary",
            )
        elif current_primary_path:
            current_primary_summary = FileRelationshipFileSummary.from_path(
                current_primary_path,
                role_candidate="current_primary",
                source="live_primary",
            )

        latest_uploaded_summary = None
        if upload_analysis is not None:
            latest_uploaded_summary = FileRelationshipFileSummary.from_analysis(
                upload_analysis,
                role_candidate="new_upload",
                source="incoming_turn",
            )
        elif isinstance(relationship_bundle.get("pending_upload_summary"), dict):
            latest_uploaded_summary = FileRelationshipFileSummary.from_dict(
                relationship_bundle["pending_upload_summary"]
            )

        attached_supporting_file = None
        if state.attached_supporting_file is not None:
            attached_supporting_file = state.attached_supporting_file
        elif isinstance(relationship_bundle.get("attached_supporting_file"), dict):
            attached_supporting_file = FileRelationshipFileSummary.from_dict(
                relationship_bundle["attached_supporting_file"]
            )

        request = state.active_input_completion or self._load_active_input_completion_request()
        current_task_type = (
            state.file_context.task_type
            or (request.current_task_type if request is not None else None)
            or (current_primary_summary.task_type if current_primary_summary is not None else None)
        )

        recent_candidates: List[FileRelationshipFileSummary] = []
        seen_paths = set()
        for item in [current_primary_summary, latest_uploaded_summary, attached_supporting_file]:
            if item is None:
                continue
            marker = item.file_path or item.file_name or id(item)
            if marker in seen_paths:
                continue
            seen_paths.add(marker)
            recent_candidates.append(item)

        setattr(state, "_file_relationship_current_primary_analysis", current_primary_analysis)
        setattr(state, "_file_relationship_upload_analysis", upload_analysis)

        return FileRelationshipResolutionContext(
            current_primary_file=current_primary_summary,
            latest_uploaded_file=latest_uploaded_summary,
            attached_supporting_file=attached_supporting_file,
            current_task_type=current_task_type,
            has_pending_completion=request is not None,
            pending_completion_reason_code=(
                request.reason_code.value
                if request is not None and request.reason_code is not None
                else None
            ),
            has_geometry_recovery=state.geometry_recovery_context is not None,
            has_residual_reentry=state.residual_reentry_context is not None,
            has_residual_workflow=(
                state.plan is not None
                or isinstance(self._ensure_live_continuation_bundle().get("plan"), dict)
            ),
            has_completion_overrides=bool(
                state.get_input_completion_overrides_summary()
                or self._ensure_live_input_completion_bundle().get("overrides")
            ),
            has_active_parameter_negotiation=(
                state.active_parameter_negotiation is not None
                or self._load_active_parameter_negotiation_request() is not None
            ),
            awaiting_relationship_clarification=bool(
                relationship_bundle.get("awaiting_clarification", False)
            ),
            user_message=state.user_message,
            recent_file_candidates=recent_candidates,
        )

    def _should_resolve_file_relationship(
        self,
        state: TaskState,
    ) -> tuple[bool, str]:
        if not getattr(self.runtime_config, "enable_file_relationship_resolution", True):
            return False, "file relationship resolution feature flag disabled"

        relationship_bundle = self._ensure_live_file_relationship_bundle()
        has_pending_relationship_clarification = bool(
            relationship_bundle.get("awaiting_clarification")
            and relationship_bundle.get("pending_upload_summary")
        )
        incoming_file_path = str(state.incoming_file_path or "").strip() or None
        active_negotiation_request = (
            state.active_parameter_negotiation
            or self._load_active_parameter_negotiation_request()
        )
        has_relation_cue = self._message_has_file_relationship_cue(state.user_message)
        has_active_file_bound_context = any(
            [
                self._get_file_relationship_current_primary_path(state),
                state.active_input_completion is not None,
                self._load_active_input_completion_request() is not None,
                state.geometry_recovery_context is not None,
                state.residual_reentry_context is not None,
                state.plan is not None,
                isinstance(self._ensure_live_continuation_bundle().get("plan"), dict),
                bool(state.get_input_completion_overrides_summary()),
            ]
        )

        if has_pending_relationship_clarification:
            return True, "an unresolved file-relationship clarification was waiting on this turn"

        if not has_active_file_bound_context:
            return False, "no active file-bound workflow or primary-file context was present"

        if (
            incoming_file_path
            and active_negotiation_request is not None
            and reply_looks_like_confirmation_attempt(active_negotiation_request, state.user_message or "")
        ):
            return False, "an explicit parameter-confirmation reply took precedence over file relationship resolution"

        if incoming_file_path:
            return True, "a new uploaded file entered an active file-bound workflow"

        if not getattr(self.runtime_config, "file_relationship_resolution_require_new_upload", True) and has_relation_cue:
            return True, "the user explicitly referenced a file-relationship change"

        return False, "no new upload or unresolved file-relationship cue was present"

    def _build_file_relationship_resolution_messages(
        self,
        context: FileRelationshipResolutionContext,
    ) -> List[Dict[str, str]]:
        return [
            {
                "role": "user",
                "content": json.dumps(context.to_llm_payload(), ensure_ascii=False, indent=2),
            }
        ]

    async def _resolve_file_relationship(
        self,
        context: FileRelationshipResolutionContext,
    ) -> FileRelationshipParseResult:
        raw_payload: Optional[Dict[str, Any]] = None
        try:
            if not hasattr(self.llm, "chat_json"):
                raise ValueError("structured JSON file-relationship resolution is unavailable")

            raw_payload = await self.llm.chat_json(
                messages=self._build_file_relationship_resolution_messages(context),
                system=FILE_RELATIONSHIP_RESOLUTION_PROMPT,
                temperature=0.0,
            )
            parse_result = parse_file_relationship_result(raw_payload, context)
            if parse_result.is_resolved and parse_result.decision is not None:
                return parse_result
            raise ValueError(parse_result.error or "file relationship resolution returned an unresolved payload")
        except Exception as exc:
            if getattr(self.runtime_config, "file_relationship_resolution_allow_llm_fallback", True):
                fallback_decision = infer_file_relationship_fallback(context)
                return FileRelationshipParseResult(
                    is_resolved=True,
                    decision=fallback_decision,
                    raw_payload=raw_payload,
                    error=str(exc),
                    used_fallback=True,
                )

            ask_clarify = FileRelationshipDecision(
                relationship_type=FileRelationshipType.ASK_CLARIFY,
                confidence=0.0,
                reason=str(exc),
                primary_file_candidate=(
                    context.current_primary_file.file_path
                    if context.current_primary_file is not None
                    else None
                ),
                supporting_file_candidate=(
                    context.latest_uploaded_file.file_path
                    if context.latest_uploaded_file is not None
                    else None
                ),
                affected_contexts=["primary_file", "pending_completion"],
                should_supersede_pending_completion=False,
                should_reset_recovery_context=False,
                should_preserve_residual_workflow=False,
                user_utterance_summary=str(context.user_message or "").strip() or None,
                resolution_source="guardrail",
            )
            return FileRelationshipParseResult(
                is_resolved=True,
                decision=ask_clarify,
                raw_payload=raw_payload,
                error=str(exc),
                used_fallback=False,
            )

    def _apply_file_relationship_transition(
        self,
        state: TaskState,
        context: FileRelationshipResolutionContext,
        decision: FileRelationshipDecision,
        transition_plan: FileRelationshipTransitionPlan,
        *,
        trace_obj: Optional[Trace] = None,
    ) -> None:
        relationship_bundle = self._ensure_live_file_relationship_bundle()
        relationship_bundle["latest_decision"] = decision.to_dict()
        relationship_bundle["latest_transition_plan"] = transition_plan.to_dict()
        state.set_latest_file_relationship_decision(decision)
        state.set_latest_file_relationship_transition(transition_plan)
        state.set_awaiting_file_relationship_clarification(False)
        state.set_pending_file_relationship_upload(None)

        current_primary_analysis = getattr(state, "_file_relationship_current_primary_analysis", None)
        upload_analysis = getattr(state, "_file_relationship_upload_analysis", None)
        upload_summary = context.latest_uploaded_file

        if transition_plan.replace_primary_file:
            if transition_plan.supersede_pending_completion:
                self._clear_live_input_completion_state(clear_overrides=True)
                state.set_active_input_completion(None)
                state.input_completion_overrides.clear()
                state.set_latest_input_completion_decision(None)
            if transition_plan.supersede_parameter_negotiation:
                self._clear_live_parameter_negotiation_state(clear_locks=False)
                state.set_active_parameter_negotiation(None)
                state.set_latest_parameter_negotiation_decision(None)
            if transition_plan.reset_geometry_recovery_context:
                state.set_supporting_spatial_input(None)
                state.set_geometry_recovery_context(None)
            if transition_plan.reset_geometry_readiness_refresh:
                state.set_geometry_readiness_refresh_result(None)
            if transition_plan.clear_residual_reentry_context:
                state.set_residual_reentry_context(None)
                state.set_reentry_bias_applied(False)
            if not transition_plan.preserve_residual_workflow:
                self._clear_live_continuation_state()
                state.set_plan(None)
                state.repair_history = []
                state.set_continuation_decision(None)
                state.execution.blocked_info = None
            state.set_attached_supporting_file(None)
            state.set_latest_summary_delivery_plan(None)
            state.set_latest_summary_delivery_result(None)
            state.set_artifact_memory_state(ArtifactMemoryState())
            cached_file_context = getattr(state, "_file_analysis_cache", None)
            if isinstance(cached_file_context, dict):
                cached_file_context["latest_summary_delivery_plan"] = None
                cached_file_context["latest_summary_delivery_result"] = None
                cached_file_context["artifact_memory"] = state.artifact_memory_state.to_dict()
                cached_file_context["artifact_memory_summary"] = state.get_artifact_memory_summary()
                setattr(state, "_file_analysis_cache", cached_file_context)
            relationship_bundle["attached_supporting_file"] = None
            relationship_bundle["pending_upload_summary"] = None
            relationship_bundle["pending_upload_analysis"] = None
            relationship_bundle["pending_primary_summary"] = None
            relationship_bundle["pending_primary_analysis"] = None
            relationship_bundle["awaiting_clarification"] = False

            new_primary_path = transition_plan.new_primary_file_candidate
            self._set_state_file_context_to_ungrounded_file(state, new_primary_path)
            state.incoming_file_path = new_primary_path
            if isinstance(upload_analysis, dict):
                setattr(state, "_pending_file_relationship_upload_analysis", dict(upload_analysis))
            setattr(state, "_memory_update_file_path", new_primary_path)
            setattr(state, "_memory_update_file_analysis", None)

        elif transition_plan.attach_supporting_file:
            if transition_plan.preserve_primary_file:
                self._restore_state_file_context_from_analysis(
                    state,
                    current_primary_analysis,
                    file_path_override=transition_plan.new_primary_file_candidate,
                )
            state.set_attached_supporting_file(upload_summary)
            relationship_bundle["attached_supporting_file"] = (
                upload_summary.to_dict() if upload_summary is not None else None
            )
            relationship_bundle["pending_upload_summary"] = None
            relationship_bundle["pending_upload_analysis"] = None
            relationship_bundle["pending_primary_summary"] = None
            relationship_bundle["pending_primary_analysis"] = None
            relationship_bundle["awaiting_clarification"] = False
            setattr(
                state,
                "_memory_update_file_path",
                transition_plan.new_primary_file_candidate
                or (
                    context.current_primary_file.file_path
                    if context.current_primary_file is not None
                    else None
                ),
            )
            setattr(
                state,
                "_memory_update_file_analysis",
                self._build_state_file_context(state),
            )

        elif transition_plan.pending_merge_semantics:
            state.set_latest_supplemental_merge_plan(None)
            state.set_latest_supplemental_merge_result(None)
            if transition_plan.preserve_primary_file:
                self._restore_state_file_context_from_analysis(
                    state,
                    current_primary_analysis,
                    file_path_override=transition_plan.new_primary_file_candidate,
                )
            relationship_bundle["pending_upload_summary"] = None
            relationship_bundle["pending_upload_analysis"] = None
            relationship_bundle["pending_primary_summary"] = None
            relationship_bundle["pending_primary_analysis"] = None
            relationship_bundle["awaiting_clarification"] = False
            state.control.needs_user_input = False
            state.control.input_completion_prompt = None
            state.control.parameter_confirmation_prompt = None
            state.control.clarification_question = None

            if getattr(self.runtime_config, "enable_supplemental_column_merge", True):
                resume_snapshot = None
                if transition_plan.supersede_pending_completion:
                    resume_snapshot = self._capture_supplemental_merge_resume_snapshot(state)
                    setattr(state, "_supplemental_merge_resume_snapshot", dict(resume_snapshot))
                    active_request = state.active_input_completion or self._load_active_input_completion_request()
                    if active_request is not None:
                        setattr(state, "_supplemental_merge_active_request", active_request.to_dict())

                    preserved_overrides = state.get_input_completion_overrides_summary()
                    if transition_plan.clear_input_completion_overrides:
                        preserved_overrides = self._clear_primary_field_completion_overrides(state)

                    self._ensure_live_input_completion_bundle()["overrides"] = preserved_overrides
                    self._clear_live_input_completion_state(clear_overrides=False)
                    self._ensure_live_input_completion_bundle()["overrides"] = preserved_overrides
                    self._ensure_live_input_completion_bundle()["latest_decision"] = None
                    state.set_active_input_completion(None)
                    state.set_latest_input_completion_decision(None)
                else:
                    setattr(state, "_supplemental_merge_resume_snapshot", None)

                setattr(state, "_memory_update_file_path", None)
                setattr(state, "_memory_update_file_analysis", None)
            else:
                setattr(state, "_final_response_text", transition_plan.user_visible_summary)
                setattr(
                    state,
                    "_memory_update_file_path",
                    transition_plan.new_primary_file_candidate
                    or (
                        context.current_primary_file.file_path
                        if context.current_primary_file is not None
                        else None
                    ),
                )
                setattr(
                    state,
                    "_memory_update_file_analysis",
                    self._build_state_file_context(state),
                )
                state.incoming_file_path = None
                self._transition_state(
                    state,
                    TaskStage.DONE,
                    reason="supplemental merge semantics were recognized but merge execution was disabled",
                    trace_obj=trace_obj,
                )

        elif transition_plan.require_clarification:
            if context.current_primary_file is not None:
                self._restore_state_file_context_from_analysis(
                    state,
                    current_primary_analysis,
                    file_path_override=context.current_primary_file.file_path,
                )
            relationship_bundle["pending_upload_summary"] = (
                upload_summary.to_dict() if upload_summary is not None else None
            )
            relationship_bundle["pending_upload_analysis"] = (
                dict(upload_analysis) if isinstance(upload_analysis, dict) else None
            )
            relationship_bundle["pending_primary_summary"] = (
                context.current_primary_file.to_dict()
                if context.current_primary_file is not None
                else None
            )
            relationship_bundle["pending_primary_analysis"] = (
                dict(current_primary_analysis) if isinstance(current_primary_analysis, dict) else None
            )
            relationship_bundle["awaiting_clarification"] = True
            state.set_pending_file_relationship_upload(upload_summary)
            state.set_awaiting_file_relationship_clarification(True)
            state.control.needs_user_input = True
            state.control.clarification_question = transition_plan.clarification_question
            state.control.parameter_confirmation_prompt = None
            state.control.input_completion_prompt = None
            setattr(
                state,
                "_memory_update_file_path",
                context.current_primary_file.file_path if context.current_primary_file is not None else None,
            )
            setattr(
                state,
                "_memory_update_file_analysis",
                self._build_state_file_context(state),
            )
            self._transition_state(
                state,
                TaskStage.NEEDS_CLARIFICATION,
                reason="file relationship remained ambiguous and required bounded clarification",
                trace_obj=trace_obj,
            )

        else:
            if transition_plan.preserve_primary_file:
                self._restore_state_file_context_from_analysis(
                    state,
                    current_primary_analysis,
                    file_path_override=transition_plan.new_primary_file_candidate,
                )
            relationship_bundle["pending_upload_summary"] = None
            relationship_bundle["pending_upload_analysis"] = None
            relationship_bundle["pending_primary_summary"] = None
            relationship_bundle["pending_primary_analysis"] = None
            relationship_bundle["awaiting_clarification"] = False
            setattr(
                state,
                "_memory_update_file_path",
                transition_plan.new_primary_file_candidate
                or (
                    context.current_primary_file.file_path
                    if context.current_primary_file is not None
                    else None
                ),
            )
            setattr(
                state,
                "_memory_update_file_analysis",
                self._build_state_file_context(state),
            )
            state.incoming_file_path = None

        if trace_obj is not None:
            trace_obj.record(
                step_type=TraceStepType.FILE_RELATIONSHIP_TRANSITION_APPLIED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                stage_after=state.stage.value if state.stage != TaskStage.INPUT_RECEIVED else None,
                action=decision.relationship_type.value,
                input_summary={
                    "decision": decision.to_dict(),
                },
                output_summary=transition_plan.to_dict(),
                reasoning=transition_plan.user_visible_summary
                or decision.reason
                or "Applied a bounded state transition from the file-relationship decision.",
            )

    async def _handle_supplemental_merge(
        self,
        state: TaskState,
        relationship_context: FileRelationshipResolutionContext,
        decision: FileRelationshipDecision,
        transition_plan: FileRelationshipTransitionPlan,
        *,
        trace_obj: Optional[Trace] = None,
    ) -> bool:
        merge_context = self._build_supplemental_merge_context(
            state,
            relationship_context,
            decision,
        )
        if trace_obj is not None:
            trace_obj.record(
                step_type=TraceStepType.SUPPLEMENTAL_MERGE_TRIGGERED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action="supplemental_merge",
                input_summary={
                    "primary_file_summary": dict(merge_context.primary_file_summary),
                    "supplemental_file_summary": dict(merge_context.supplemental_file_summary),
                    "target_missing_canonical_fields": list(merge_context.target_missing_canonical_fields),
                    "current_task_type": merge_context.current_task_type,
                },
                reasoning=(
                    "The file-relationship resolver classified the upload as merge_supplemental_columns, "
                    "so the router entered the bounded supplemental merge path."
                ),
            )

        plan = build_supplemental_merge_plan(
            merge_context,
            allow_alias_keys=getattr(self.runtime_config, "supplemental_merge_allow_alias_keys", True),
        )
        state.set_latest_supplemental_merge_plan(plan)
        state.set_latest_supplemental_merge_result(None)

        if trace_obj is not None:
            trace_obj.record(
                step_type=TraceStepType.SUPPLEMENTAL_MERGE_PLANNED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action="supplemental_merge_plan",
                input_summary={
                    "relationship_decision": decision.to_dict(),
                },
                output_summary=plan.to_dict(),
                reasoning=(
                    plan.failure_reason
                    or (
                        f"Planned a bounded key-based merge using "
                        f"{plan.merge_keys[0].primary_column}->{plan.merge_keys[0].supplemental_column}."
                        if plan.merge_keys
                        else "Built a bounded supplemental merge plan."
                    )
                ),
            )

        resume_snapshot = getattr(state, "_supplemental_merge_resume_snapshot", None)
        restored_plan_context = self._restore_residual_plan_from_snapshot(
            state,
            resume_snapshot=resume_snapshot if isinstance(resume_snapshot, dict) else None,
        )

        if plan.plan_status != "ready":
            failure_reason = plan.failure_reason or "The supplemental merge plan could not be built safely."
            if trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.SUPPLEMENTAL_MERGE_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="supplemental_merge_plan",
                    input_summary=merge_context.to_dict(),
                    output_summary=plan.to_dict(),
                    reasoning=failure_reason,
                    error=failure_reason,
                )
            state.control.needs_user_input = True
            state.control.clarification_question = failure_reason
            state.control.input_completion_prompt = None
            state.control.parameter_confirmation_prompt = None
            setattr(state, "_final_response_text", failure_reason)
            self._transition_state(
                state,
                TaskStage.NEEDS_CLARIFICATION,
                reason="supplemental merge plan could not be established safely",
                trace_obj=trace_obj,
            )
            return True

        result = execute_supplemental_merge(
            plan,
            outputs_dir=self.runtime_config.outputs_dir,
            session_id=self.session_id,
        )
        state.set_latest_supplemental_merge_result(result)

        if not result.success:
            failure_reason = result.failure_reason or "The bounded supplemental merge execution failed."
            if trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.SUPPLEMENTAL_MERGE_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="supplemental_merge_apply",
                    input_summary=plan.to_dict(),
                    output_summary=result.to_dict(),
                    reasoning=failure_reason,
                    error=failure_reason,
                )
            state.control.needs_user_input = True
            state.control.clarification_question = failure_reason
            state.control.input_completion_prompt = None
            state.control.parameter_confirmation_prompt = None
            setattr(state, "_final_response_text", failure_reason)
            self._transition_state(
                state,
                TaskStage.NEEDS_CLARIFICATION,
                reason="supplemental merge execution failed safely",
                trace_obj=trace_obj,
            )
            return True

        if trace_obj is not None:
            trace_obj.record(
                step_type=TraceStepType.SUPPLEMENTAL_MERGE_APPLIED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action="supplemental_merge_apply",
                input_summary=plan.to_dict(),
                output_summary=result.to_dict(),
                reasoning=(
                    f"Materialized a merged primary dataset at {result.materialized_primary_file_ref} "
                    f"with columns {result.merged_columns}."
                ),
            )

        materialized_ref = result.materialized_primary_file_ref
        if not materialized_ref:
            failure_reason = "Supplemental merge succeeded logically but did not materialize an execution-side file."
            if trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.SUPPLEMENTAL_MERGE_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="supplemental_merge_apply",
                    input_summary=plan.to_dict(),
                    output_summary=result.to_dict(),
                    reasoning=failure_reason,
                    error=failure_reason,
                )
            state.control.needs_user_input = True
            state.control.clarification_question = failure_reason
            self._transition_state(
                state,
                TaskStage.NEEDS_CLARIFICATION,
                reason="supplemental merge did not materialize a file artifact",
                trace_obj=trace_obj,
            )
            return True

        merged_analysis = await self._analyze_file(materialized_ref)
        merged_analysis["file_path"] = materialized_ref
        merged_analysis = await self._maybe_apply_file_analysis_fallback(
            merged_analysis,
            trace_obj=None,
        )
        merged_analysis = apply_supplemental_merge_analysis_refresh(
            merged_analysis,
            plan=plan,
            result=result,
        )
        state.update_file_context(merged_analysis)
        setattr(state, "_file_analysis_cache", dict(merged_analysis))

        result.updated_file_context_summary = {
            "file_path": materialized_ref,
            "task_type": merged_analysis.get("task_type"),
            "columns": list(merged_analysis.get("columns") or [])[:12],
            "row_count": merged_analysis.get("row_count"),
        }
        result.updated_missing_field_diagnostics = dict(
            merged_analysis.get("missing_field_diagnostics") or {}
        )

        request_payload = getattr(state, "_supplemental_merge_active_request", None)
        request = (
            InputCompletionRequest.from_dict(request_payload)
            if isinstance(request_payload, dict)
            else None
        )

        assessment = None
        affordance = None
        if getattr(self.runtime_config, "supplemental_merge_require_readiness_refresh", True):
            assessment = self._build_readiness_assessment(
                state.execution.tool_results,
                state=state,
                frontend_payloads=self._extract_frontend_payloads(state.execution.tool_results),
                trace_obj=None,
                stage_before=None,
                purpose="input_completion_recheck",
            )
            if assessment is not None and request is not None:
                affordance = assessment.get_action(request.action_id)

        readiness_refresh_result = self._build_supplemental_merge_readiness_refresh_result(
            request=request,
            affordance=affordance,
            assessment=assessment,
            diagnostics=result.updated_missing_field_diagnostics,
        )
        result.updated_readiness_summary = dict(readiness_refresh_result)
        state.set_latest_supplemental_merge_result(result)

        if trace_obj is not None:
            trace_obj.record(
                step_type=TraceStepType.SUPPLEMENTAL_MERGE_READINESS_REFRESHED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action=request.action_id if request is not None else None,
                input_summary={
                    "before_status": readiness_refresh_result.get("before_status"),
                    "before_reason_code": readiness_refresh_result.get("before_reason_code"),
                },
                output_summary=dict(readiness_refresh_result),
                reasoning=(
                    f"Readiness refreshed after supplemental merge: "
                    f"{readiness_refresh_result.get('status_delta')}."
                ),
            )

        continuation_decision = None
        if readiness_refresh_result.get("after_status") == ReadinessStatus.READY.value:
            continuation_decision = self._build_supplemental_merge_resume_decision(
                state,
                restored_context=restored_plan_context,
            )
            if continuation_decision is None and request is not None and affordance is not None:
                continuation_decision = ContinuationDecision(
                    residual_plan_exists=False,
                    continuation_ready=True,
                    should_continue=False,
                    should_replan=False,
                    prompt_variant=self._resolve_continuation_prompt_variant(),
                    signal="supplemental_merge_resume",
                    reason=(
                        "supplemental merge restored the current file context and made the original action "
                        "ready for the next explicit turn"
                    ),
                    next_step_id=request.action_id,
                    next_tool_name=affordance.tool_name,
                )
            if continuation_decision is not None:
                state.set_continuation_decision(continuation_decision)
                if trace_obj is not None:
                    trace_obj.record(
                        step_type=TraceStepType.SUPPLEMENTAL_MERGE_RESUMED,
                        stage_before=TaskStage.INPUT_RECEIVED.value,
                        action=continuation_decision.next_tool_name,
                        input_summary={
                            "next_step_id": continuation_decision.next_step_id,
                            "next_tool_name": continuation_decision.next_tool_name,
                            "signal": continuation_decision.signal,
                        },
                        output_summary={
                            "residual_plan_summary": continuation_decision.residual_plan_summary,
                            "latest_repair_summary": continuation_decision.latest_repair_summary,
                        },
                        reasoning=(
                            "The merged file refreshed readiness and restored the current workflow "
                            "to a resumable state without auto replay."
                        ),
                    )

        state.execution.blocked_info = None
        setattr(
            state,
            "_memory_update_file_path",
            materialized_ref,
        )
        setattr(
            state,
            "_memory_update_file_analysis",
            dict(merged_analysis),
        )
        state.incoming_file_path = None
        state.control.needs_user_input = False
        state.control.clarification_question = None
        state.control.input_completion_prompt = None
        state.control.parameter_confirmation_prompt = None
        setattr(
            state,
            "_final_response_text",
            self._build_supplemental_merge_user_text(
                plan=plan,
                result=result,
                readiness_refresh_result=readiness_refresh_result,
            ),
        )

        self._clear_live_input_completion_state(clear_overrides=False)
        self._ensure_live_input_completion_bundle()["overrides"] = state.get_input_completion_overrides_summary()
        self._ensure_live_input_completion_bundle()["latest_decision"] = None
        self._ensure_live_input_completion_bundle()["file_path"] = materialized_ref

        self._transition_state(
            state,
            TaskStage.DONE,
            reason="supplemental merge path completed without auto replay",
            trace_obj=trace_obj,
        )
        return True

    def _evaluate_missing_parameter_preflight(
        self,
        state: TaskState,
        tool_name: str,
        *,
        effective_arguments: Optional[Dict[str, Any]] = None,
        trace_obj: Optional[Trace] = None,
    ) -> bool:
        hints = self._extract_message_execution_hints(state)
        explicit_arguments = effective_arguments if isinstance(effective_arguments, dict) else {}
        if tool_name != "query_emission_factors" or (not hints.get("wants_factor") and not explicit_arguments):
            return False

        resolved_vehicle_type = explicit_arguments.get("vehicle_type") or hints.get("vehicle_type")
        resolved_model_year = (
            explicit_arguments.get("model_year")
            if explicit_arguments.get("model_year") is not None
            else hints.get("model_year")
        )
        resolved_pollutants = (
            explicit_arguments.get("pollutants")
            or explicit_arguments.get("pollutant")
            or hints.get("pollutants")
        )

        clarification: Optional[str] = None
        if not resolved_vehicle_type:
            clarification = "要查询排放因子，我还需要车型。请告诉我是 Passenger Car、Transit Bus、Motorcycle 等哪一类车辆。"
        elif resolved_model_year is None:
            clarification = "要查询排放因子，我还需要车型年份。请告诉我例如 2020、2021 这样的年份。"
        elif not explicit_arguments and not resolved_pollutants:
            clarification = "要查询排放因子，我还需要污染物类型。请说明是 CO2、NOx、PM2.5，还是其它污染物。"

        if clarification is None:
            return False

        self._set_direct_user_response_state(
            state,
            clarification,
            stage=TaskStage.NEEDS_CLARIFICATION,
            stage_before=TaskStage.EXECUTING,
            reason="Missing required factor-query parameter detected before tool execution",
            trace_obj=trace_obj,
            trace_step_type=TraceStepType.CLARIFICATION,
        )
        return True

    def _extract_available_metrics_for_summary_delivery(
        self,
        result_payload: Optional[Dict[str, Any]],
    ) -> List[str]:
        payload = result_payload if isinstance(result_payload, dict) else {}
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        rows = data.get("results") if isinstance(data, dict) else []
        metrics: List[str] = []
        seen = set()
        if isinstance(rows, list):
            for row in rows[:20]:
                if not isinstance(row, dict):
                    continue
                totals = row.get("total_emissions_kg_per_hr")
                if isinstance(totals, dict):
                    for pollutant in totals.keys():
                        metric_name = f"{pollutant}_kg_h"
                        if metric_name not in seen:
                            seen.add(metric_name)
                            metrics.append(metric_name)
        summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
        totals = summary.get("total_emissions_kg_per_hr") if isinstance(summary, dict) else {}
        if isinstance(totals, dict):
            for pollutant in totals.keys():
                metric_name = f"{pollutant}_kg_h"
                if metric_name not in seen:
                    seen.add(metric_name)
                    metrics.append(metric_name)
        return metrics

    def _build_summary_delivery_context(
        self,
        state: TaskState,
    ) -> Optional[SummaryDeliveryContext]:
        source_result: Optional[Dict[str, Any]] = None
        source_result_type: Optional[str] = None
        source_tool_name: Optional[str] = None
        source_label: Optional[str] = None
        source_summary: Dict[str, Any] = {}

        for item in reversed(state.execution.tool_results):
            if not isinstance(item, dict):
                continue
            result = item.get("result")
            if not isinstance(result, dict) or not result.get("success"):
                continue
            if str(item.get("name") or "").strip() in {"calculate_macro_emission", "summary_delivery_surface"}:
                source_result = result
                source_result_type = "emission" if str(item.get("name") or "").strip() == "calculate_macro_emission" else "summary_delivery"
                source_tool_name = str(item.get("name") or "").strip() or None
                source_label = "current_turn"
                break

        store = self._ensure_context_store()
        stored = None
        if source_result is None:
            stored = store.get_by_type("emission")
            if stored is None:
                stored = store.get_latest()
            if stored is not None and isinstance(stored.data, dict):
                source_result = dict(stored.data)
                source_result_type = stored.result_type
                source_tool_name = stored.tool_name
                source_label = stored.label
                source_summary = stored.compact()

        if source_result is None:
            return None

        if not source_summary:
            summary_block = (
                source_result.get("data", {}).get("summary", {})
                if isinstance(source_result.get("data"), dict)
                else {}
            )
            source_summary = {
                "type": source_result_type,
                "tool": source_tool_name,
                "label": source_label,
                "summary": source_result.get("summary"),
                "metadata": {
                    "row_count": len(source_result.get("data", {}).get("results", []) or [])
                    if isinstance(source_result.get("data"), dict)
                    else 0,
                    "total_emissions_kg_per_hr": (
                        summary_block.get("total_emissions_kg_per_hr")
                        if isinstance(summary_block, dict)
                        else None
                    ),
                },
            }

        plan = state.latest_intent_resolution_plan
        decision = state.latest_intent_resolution_decision
        has_geometry_support = bool(state.file_context.spatial_metadata or state.file_context.spatial_context)
        return SummaryDeliveryContext(
            user_message=state.user_message,
            current_task_type=state.file_context.task_type,
            deliverable_intent=(
                plan.deliverable_intent
                if plan is not None
                else DeliverableIntentType.UNKNOWN
            ),
            progress_intent=(
                plan.progress_intent
                if plan is not None
                else (
                    decision.progress_intent
                    if decision is not None
                    else ProgressIntentType.ASK_CLARIFY
                )
            ),
            has_geometry_support=has_geometry_support,
            source_result_type=source_result_type,
            source_tool_name=source_tool_name,
            source_label=source_label,
            source_result_summary=source_summary,
            available_metrics=self._extract_available_metrics_for_summary_delivery(source_result),
            artifact_memory_summary=state.get_artifact_memory_summary(),
            raw_source_result=source_result,
        )

    def _should_trigger_summary_delivery_surface(
        self,
        state: TaskState,
    ) -> tuple[bool, str]:
        if not getattr(self.runtime_config, "enable_summary_delivery_surface", True):
            return False, "summary delivery surface feature flag disabled"

        plan = state.latest_intent_resolution_plan
        if plan is None:
            return False, "no active intent-resolution plan was available for summary delivery"

        if plan.require_clarification:
            return False, "intent resolution required clarification, so summary delivery was skipped"

        if plan.progress_intent in {
            ProgressIntentType.START_NEW_TASK,
            ProgressIntentType.ASK_CLARIFY,
        }:
            return False, "the current progress intent did not support direct bounded summary delivery"

        message = str(state.user_message or "").strip().lower()
        explicit_spatial_cues = (
            "地图",
            "map",
            "空间图",
            "spatial map",
            "geojson",
            "geometry",
            "图层",
            "layer",
        )
        chart_cues = (
            "可视化",
            "图表",
            "条形图",
            "柱状图",
            "chart",
            "plot",
            "画出来",
            "画个图",
        )
        table_cues = (
            "top",
            "前",
            "排行",
            "排名",
            "高排",
            "摘要表",
            "summary table",
            "ranked table",
            "表格",
        )
        summary_cues = (
            "摘要",
            "总结",
            "汇总",
            "概览",
            "summary",
        )
        export_cues = ("导出", "下载", "export", "download")
        has_explicit_spatial_cue = any(token in message for token in explicit_spatial_cues)
        has_chart_cue = any(token in message for token in chart_cues)
        has_ranked_table_cue = any(
            token in message
            for token in table_cues
        )
        has_summary_cue = any(token in message for token in summary_cues)
        has_export_cue = any(token in message for token in export_cues)

        if has_explicit_spatial_cue:
            return False, "the user explicitly asked for a spatial map, so readiness/repair should take precedence"

        if plan.progress_intent != ProgressIntentType.SHIFT_OUTPUT_MODE:
            return False, "direct bounded summary delivery is only allowed on output-mode shift turns"

        if plan.deliverable_intent == DeliverableIntentType.CHART_OR_RANKED_SUMMARY:
            if has_chart_cue or has_ranked_table_cue:
                return True, "the current turn explicitly requested a bounded non-spatial chart/summary output"
            return False, "the turn did not explicitly request a chart/table deliverable"

        if plan.deliverable_intent == DeliverableIntentType.QUICK_SUMMARY:
            if has_summary_cue:
                return True, "the current turn explicitly requested a concise structured summary"
            return False, "the turn did not explicitly request a summary deliverable"

        if plan.deliverable_intent == DeliverableIntentType.DOWNLOADABLE_TABLE:
            if has_ranked_table_cue or has_export_cue:
                return True, "the current turn requested a ranked summary table delivery"
            return False, "the turn did not explicitly request a table/export deliverable"

        return False, "the resolved deliverable intent did not map to the bounded chart/summary surface"

    def _build_summary_delivery_synthetic_tool_result(
        self,
        state: TaskState,
        plan: SummaryDeliveryPlan,
        result: SummaryDeliveryResult,
    ) -> Dict[str, Any]:
        ranking_metric = plan.decision.ranking_metric
        pollutant = ranking_metric[:-5] if ranking_metric and ranking_metric.endswith("_kg_h") else None
        data_payload = {
            "delivery_type": (
                plan.decision.selected_delivery_type.value
                if plan.decision.selected_delivery_type is not None
                else None
            ),
            "source_result_type": plan.source_result_type,
            "summary": {
                "delivery_type": (
                    plan.decision.selected_delivery_type.value
                    if plan.decision.selected_delivery_type is not None
                    else None
                ),
                "ranking_metric": ranking_metric,
                "topk": plan.decision.topk,
                "artifact_count": len(result.artifact_records),
            },
            "query_info": {
                "pollutants": [pollutant] if pollutant else [],
            },
            "download_file": result.download_file,
            "task_type": state.file_context.task_type,
        }
        return {
            "tool_call_id": "summary-delivery",
            "name": "summary_delivery_surface",
            "arguments": {
                "delivery_type": (
                    plan.decision.selected_delivery_type.value
                    if plan.decision.selected_delivery_type is not None
                    else None
                ),
                "source_result_type": plan.source_result_type,
                "ranking_metric": ranking_metric,
                "topk": plan.decision.topk,
            },
            "result": {
                "success": True,
                "summary": result.delivery_summary,
                "data": data_payload,
                "chart_data": result.chart_ref,
                "table_data": result.table_preview,
                "download_file": result.download_file,
            },
        }

    def _apply_summary_delivery_surface(
        self,
        state: TaskState,
        plan: SummaryDeliveryPlan,
        result: SummaryDeliveryResult,
        *,
        trace_obj: Optional[Trace] = None,
    ) -> None:
        state.set_latest_summary_delivery_plan(plan)
        state.set_latest_summary_delivery_result(result)
        cached_file_context = getattr(state, "_file_analysis_cache", None)
        if isinstance(cached_file_context, dict):
            cached_file_context["latest_summary_delivery_plan"] = plan.to_dict()
            cached_file_context["latest_summary_delivery_result"] = result.to_dict()
            setattr(state, "_file_analysis_cache", cached_file_context)

        synthetic_result = self._build_summary_delivery_synthetic_tool_result(
            state,
            plan,
            result,
        )
        state.execution.selected_tool = "summary_delivery_surface"
        state.execution.tool_results = [synthetic_result]
        state.execution.completed_tools.append("summary_delivery_surface")
        setattr(state, "_final_response_text", result.summary_text or result.delivery_summary or "")

        if trace_obj is not None:
            trace_obj.record(
                step_type=TraceStepType.SUMMARY_DELIVERY_APPLIED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action=(
                    plan.decision.selected_delivery_type.value
                    if plan.decision.selected_delivery_type is not None
                    else None
                ),
                input_summary=plan.to_dict(),
                output_summary=result.to_dict(),
                reasoning=(
                    result.delivery_summary
                    or "Applied the bounded chart/summary delivery surface to the existing result context."
                ),
            )
            trace_obj.record(
                step_type=TraceStepType.SUMMARY_DELIVERY_RECORDED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action="summary_delivery_surface",
                output_summary={
                    "artifact_records": [item.to_dict() for item in result.artifact_records],
                    "has_chart": bool(result.chart_ref),
                    "has_table": bool(result.table_preview),
                    "has_download": bool(result.download_file),
                },
                reasoning="Materialized bounded chart/summary artifacts for delivery and downstream artifact-memory recording.",
            )

        self._transition_state(
            state,
            TaskStage.DONE,
            reason="bounded summary delivery surface completed",
            trace_obj=trace_obj,
        )

    def _maybe_apply_summary_delivery_surface(
        self,
        state: TaskState,
        *,
        trace_obj: Optional[Trace] = None,
    ) -> bool:
        should_trigger, trigger_reason = self._should_trigger_summary_delivery_surface(state)
        if not should_trigger:
            return False

        if trace_obj is not None:
            trace_obj.record(
                step_type=TraceStepType.SUMMARY_DELIVERY_TRIGGERED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action="summary_delivery_surface",
                input_summary={
                    "deliverable_intent": (
                        state.latest_intent_resolution_plan.deliverable_intent.value
                        if state.latest_intent_resolution_plan is not None
                        else None
                    ),
                    "progress_intent": (
                        state.latest_intent_resolution_plan.progress_intent.value
                        if state.latest_intent_resolution_plan is not None
                        else None
                    ),
                },
                reasoning=trigger_reason,
            )

        context = self._build_summary_delivery_context(state)
        if context is None:
            if trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.SUMMARY_DELIVERY_SKIPPED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="summary_delivery_surface",
                    reasoning="No eligible upstream result was available for bounded chart/summary delivery, so normal routing continued.",
                )
            return False

        plan = build_summary_delivery_plan(
            context,
            state.artifact_memory_state,
            default_topk=getattr(self.runtime_config, "summary_delivery_default_topk", 5),
            enable_bar_chart=getattr(self.runtime_config, "summary_delivery_enable_bar_chart", True),
            allow_text_fallback=getattr(self.runtime_config, "summary_delivery_allow_text_fallback", True),
        )
        state.set_latest_summary_delivery_plan(plan)

        if trace_obj is not None:
            trace_obj.record(
                step_type=TraceStepType.SUMMARY_DELIVERY_DECIDED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action=(
                    plan.decision.selected_delivery_type.value
                    if plan.decision.selected_delivery_type is not None
                    else None
                ),
                input_summary=context.to_dict(),
                output_summary=plan.to_dict(),
                confidence=plan.decision.confidence,
                reasoning=plan.decision.reason or trigger_reason,
            )

        if plan.plan_status == "not_actionable":
            if trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.SUMMARY_DELIVERY_SKIPPED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="summary_delivery_surface",
                    input_summary=context.to_dict(),
                    output_summary=plan.to_dict(),
                    reasoning=plan.suppression_reason or "Summary delivery was not actionable in the current context.",
                )
            return False

        if plan.plan_status == "suppressed":
            state.set_latest_summary_delivery_result(
                SummaryDeliveryResult(
                    success=False,
                    summary_text=plan.user_visible_summary,
                    delivery_summary=plan.user_visible_summary,
                    failure_reason=plan.suppression_reason,
                )
            )
            setattr(
                state,
                "_final_response_text",
                plan.user_visible_summary
                or "同类型交付物刚才已经给过，当前更适合切换为另一种输出形式。",
            )
            if trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.SUMMARY_DELIVERY_SKIPPED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="summary_delivery_surface",
                    input_summary=context.to_dict(),
                    output_summary=plan.to_dict(),
                    reasoning=plan.suppression_reason or "Artifact memory suppressed an exact repeat summary delivery.",
                )
            self._transition_state(
                state,
                TaskStage.DONE,
                reason="summary delivery suppressed by artifact memory",
                trace_obj=trace_obj,
            )
            return True

        if plan.plan_status == "failed":
            failure_result = SummaryDeliveryResult(
                success=False,
                summary_text=plan.user_visible_summary,
                delivery_summary=plan.user_visible_summary,
                failure_reason=plan.suppression_reason,
            )
            state.set_latest_summary_delivery_result(failure_result)
            setattr(
                state,
                "_final_response_text",
                plan.user_visible_summary or "当前不能安全生成所请求的图表/摘要交付。",
            )
            if trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.SUMMARY_DELIVERY_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="summary_delivery_surface",
                    input_summary=context.to_dict(),
                    output_summary=plan.to_dict(),
                    reasoning=plan.suppression_reason or "The bounded summary delivery plan failed its safety preconditions.",
                    error=plan.suppression_reason,
                )
            self._transition_state(
                state,
                TaskStage.DONE,
                reason="summary delivery surface failed",
                trace_obj=trace_obj,
            )
            return True

        result = execute_summary_delivery_plan(
            plan,
            context,
            outputs_dir=Path(self.runtime_config.outputs_dir),
            delivery_turn_index=self._infer_delivery_turn_index(),
            source_tool_name="summary_delivery_surface",
        )
        if not result.success:
            state.set_latest_summary_delivery_result(result)
            setattr(
                state,
                "_final_response_text",
                result.summary_text or result.delivery_summary or result.failure_reason or "",
            )
            if trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.SUMMARY_DELIVERY_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="summary_delivery_surface",
                    input_summary=plan.to_dict(),
                    output_summary=result.to_dict(),
                    reasoning=result.failure_reason or "The bounded summary delivery execution did not produce a safe output.",
                    error=result.failure_reason,
                )
            self._transition_state(
                state,
                TaskStage.DONE,
                reason="summary delivery execution failed",
                trace_obj=trace_obj,
            )
            return True

        self._apply_summary_delivery_surface(
            state,
            plan,
            result,
            trace_obj=trace_obj,
        )
        return True

    def _message_has_intent_resolution_cue(self, message: Optional[str]) -> bool:
        normalized = str(message or "").strip().lower()
        if not normalized:
            return False
        cues = (
            "可视化",
            "画出来",
            "画个图",
            "地图",
            "图表",
            "排行",
            "排名",
            "摘要",
            "摘要表",
            "导出",
            "下载",
            "汇总",
            "总结",
            "对比",
            "比较",
            "模拟",
            "scenario",
            "visualize",
            "map",
            "chart",
            "export",
            "download",
            "summary",
            "compare",
            "rough",
            "估一下",
            "大概",
            "换个方式展示",
        )
        return any(cue in normalized for cue in cues)

    def _message_looks_like_progress_continuation(self, message: Optional[str]) -> bool:
        normalized = str(message or "").strip().lower()
        if not normalized:
            return False
        cues = (
            "继续",
            "接着",
            "下一步",
            "先这样算",
            "就按这个",
            "按这个",
            "continue",
            "keep going",
            "next step",
        )
        return any(cue in normalized for cue in cues)

    def _summarize_action_candidates_for_intent(
        self,
        assessment: Optional[ReadinessAssessment],
    ) -> List[Dict[str, Any]]:
        if assessment is None:
            return []
        candidates: List[Dict[str, Any]] = []
        for status, items in (
            ("ready", assessment.available_actions),
            ("repairable", assessment.repairable_actions),
            ("blocked", assessment.blocked_actions),
            ("already_provided", assessment.already_provided_actions),
        ):
            for item in items:
                candidates.append(
                    {
                        "action_id": item.action_id,
                        "status": status,
                        "display_name": item.display_name,
                        "tool_name": item.tool_name,
                        "description": item.description,
                        "reason": (
                            item.reason.message
                            if item.reason is not None
                            else item.description
                        ),
                        "reason_code": (
                            item.reason.reason_code
                            if item.reason is not None
                            else None
                        ),
                    }
                )
        return candidates[:16]

    def _summarize_recent_results_for_intent(self) -> List[Dict[str, Any]]:
        summaries: List[Dict[str, Any]] = []
        store = self._ensure_context_store()
        for result_type in ("hotspot", "dispersion", "emission", "scenario_comparison"):
            stored = store.get_by_type(result_type)
            if stored is None:
                continue
            summaries.append(
                {
                    "result_type": stored.result_type,
                    "tool_name": stored.tool_name,
                    "label": stored.label,
                    "summary": stored.summary,
                }
            )

        fact_memory = self.memory.get_fact_memory()
        last_tool_name = str(fact_memory.get("last_tool_name") or "").strip()
        last_tool_summary = str(fact_memory.get("last_tool_summary") or "").strip()
        if last_tool_name and last_tool_summary:
            marker = (last_tool_name, last_tool_summary)
            existing = {
                (str(item.get("tool_name") or "").strip(), str(item.get("summary") or "").strip())
                for item in summaries
            }
            if marker not in existing:
                summaries.append(
                    {
                        "result_type": None,
                        "tool_name": last_tool_name,
                        "label": "latest",
                        "summary": last_tool_summary,
                    }
                )
        return summaries[:8]

    def _build_latest_file_or_recovery_summary_for_intent(
        self,
        state: TaskState,
    ) -> Dict[str, Any]:
        summary: Dict[str, Any] = {}
        if state.latest_supplemental_merge_result is not None:
            summary["supplemental_merge"] = {
                "success": state.latest_supplemental_merge_result.success,
                "merged_columns": list(state.latest_supplemental_merge_result.merged_columns[:4]),
            }
        if state.geometry_recovery_context is not None:
            summary["geometry_recovery"] = state.get_geometry_recovery_context_summary()
        if state.latest_file_relationship_decision is not None:
            summary["file_relationship"] = {
                "relationship_type": state.latest_file_relationship_decision.relationship_type.value,
                "confidence": state.latest_file_relationship_decision.confidence,
            }
        return summary

    def _build_intent_resolution_context(
        self,
        state: TaskState,
        assessment: Optional[ReadinessAssessment],
    ) -> IntentResolutionContext:
        capability_summary = assessment.to_capability_summary() if assessment is not None else {}
        delivered_artifacts = [
            dict(item)
            for item in (capability_summary.get("already_provided") or [])
            if isinstance(item, dict)
        ]
        if (
            getattr(self.runtime_config, "enable_artifact_memory", True)
            and state.artifact_memory_state.recent_artifact_summary
        ):
            delivered_artifacts = [dict(item) for item in state.artifact_memory_state.recent_artifact_summary]
        readiness_summary = {
            "counts": assessment.counts() if assessment is not None else {},
            "available_action_ids": [
                item.action_id for item in (assessment.available_actions if assessment is not None else [])
            ],
            "repairable_action_ids": [
                item.action_id for item in (assessment.repairable_actions if assessment is not None else [])
            ],
            "already_provided": list(capability_summary.get("already_provided") or []),
            "guidance_hints": list(capability_summary.get("guidance_hints") or []),
        }
        residual_summary = (
            state.get_residual_plan_summary()
            or str(self._ensure_live_continuation_bundle().get("residual_plan_summary") or "").strip()
            or str(self._ensure_live_input_completion_bundle().get("residual_plan_summary") or "").strip()
            or None
        )
        recovered_target = state.get_reentry_target_summary() or {}
        key_signals = dict(assessment.key_signals) if assessment is not None else {}
        return IntentResolutionContext(
            user_message=state.user_message,
            current_task_type=state.file_context.task_type,
            residual_workflow_summary=residual_summary,
            recovered_target_summary=recovered_target,
            readiness_summary=readiness_summary,
            delivered_artifacts=delivered_artifacts,
            recent_result_types=self._collect_available_result_tokens(
                state,
                include_stale=False,
                include_memory=True,
            ),
            recent_tool_results_summary=self._summarize_recent_results_for_intent(),
            latest_file_or_recovery_summary=self._build_latest_file_or_recovery_summary_for_intent(state),
            relevant_action_candidates=self._summarize_action_candidates_for_intent(assessment),
            has_geometry_support=bool(key_signals.get("has_geometry_support", False)),
            has_residual_workflow=bool(
                residual_summary
                or state.plan is not None
                or isinstance(self._ensure_live_continuation_bundle().get("plan"), dict)
            ),
            has_recovered_target=bool(recovered_target),
        )

    def _should_resolve_intent(
        self,
        state: TaskState,
    ) -> tuple[bool, str]:
        if not getattr(self.runtime_config, "enable_intent_resolution", True):
            return False, "intent resolution feature flag disabled"

        if (
            state.incoming_file_path
            and self._message_has_file_relationship_cue(state.user_message)
        ):
            return False, "file relationship resolution took precedence for the current upload turn"

        active_completion_request = state.active_input_completion or self._load_active_input_completion_request()
        if (
            active_completion_request is not None
            and reply_looks_like_input_completion_attempt(active_completion_request, state.user_message or "")
        ):
            return False, "an explicit input-completion reply took precedence over intent resolution"

        active_negotiation_request = (
            state.active_parameter_negotiation
            or self._load_active_parameter_negotiation_request()
        )
        if (
            active_negotiation_request is not None
            and reply_looks_like_confirmation_attempt(active_negotiation_request, state.user_message or "")
        ):
            return False, "an explicit parameter-confirmation reply took precedence over intent resolution"

        has_recovery_context = any(
            [
                state.residual_reentry_context is not None,
                state.geometry_recovery_context is not None,
            ]
        )
        has_result_context = bool(
            self._collect_available_result_tokens(
                state,
                include_stale=False,
                include_memory=True,
            )
        )
        has_output_cue = self._message_has_intent_resolution_cue(state.user_message)
        has_continuation_cue = self._message_looks_like_progress_continuation(state.user_message)
        has_follow_up_context = bool(
            has_result_context
            or has_recovery_context
            or state.latest_supplemental_merge_result is not None
        )

        if has_output_cue and has_follow_up_context:
            return True, "the user requested a deliverable form or output-mode shift in an active task context"

        if has_continuation_cue and has_recovery_context:
            return True, "the user sent a continuation-like turn while recovered or geometry-recovery context existed"

        return False, "no strong deliverable/progress intent cue was present for the current context"

    def _build_intent_resolution_messages(
        self,
        context: IntentResolutionContext,
    ) -> List[Dict[str, str]]:
        return [
            {
                "role": "user",
                "content": json.dumps(context.to_llm_payload(), ensure_ascii=False, indent=2),
            }
        ]

    async def _resolve_deliverable_and_progress_intent(
        self,
        context: IntentResolutionContext,
    ) -> IntentResolutionParseResult:
        raw_payload: Optional[Dict[str, Any]] = None
        try:
            if not hasattr(self.llm, "chat_json"):
                raise ValueError("structured JSON intent resolution is unavailable")

            raw_payload = await self.llm.chat_json(
                messages=self._build_intent_resolution_messages(context),
                system=INTENT_RESOLUTION_PROMPT,
                temperature=0.0,
            )
            parse_result = parse_intent_resolution_result(raw_payload, context)
            if parse_result.is_resolved and parse_result.decision is not None:
                return parse_result
            raise ValueError(parse_result.error or "intent resolution returned an unresolved payload")
        except Exception as exc:
            if getattr(self.runtime_config, "intent_resolution_allow_llm_fallback", True):
                fallback_decision = infer_intent_resolution_fallback(context)
                return IntentResolutionParseResult(
                    is_resolved=True,
                    decision=fallback_decision,
                    raw_payload=raw_payload,
                    error=str(exc),
                    used_fallback=True,
                )

            ask_clarify = IntentResolutionDecision(
                deliverable_intent=DeliverableIntentType.UNKNOWN,
                progress_intent=ProgressIntentType.ASK_CLARIFY,
                confidence=0.0,
                reason=str(exc),
                current_task_relevance=0.0,
                should_bias_existing_action=False,
                should_preserve_residual_workflow=False,
                should_trigger_clarification=True,
                user_utterance_summary=str(context.user_message or "").strip() or None,
                resolution_source="guardrail",
            )
            return IntentResolutionParseResult(
                is_resolved=True,
                decision=ask_clarify,
                raw_payload=raw_payload,
                error=str(exc),
                used_fallback=False,
            )

    def _build_intent_guidance_text(
        self,
        plan: IntentResolutionApplicationPlan,
    ) -> Optional[str]:
        return str(plan.guidance_summary or "").strip() or None

    def _apply_intent_resolution_plan(
        self,
        state: TaskState,
        context: IntentResolutionContext,
        decision: IntentResolutionDecision,
        application_plan: IntentResolutionApplicationPlan,
        *,
        trace_obj: Optional[Trace] = None,
    ) -> None:
        bundle = self._ensure_live_intent_resolution_bundle()
        bundle["latest_decision"] = decision.to_dict()
        bundle["latest_application_plan"] = application_plan.to_dict()
        state.set_latest_intent_resolution_decision(decision)
        state.set_latest_intent_resolution_plan(application_plan)

        if application_plan.reset_current_task_context:
            self._reset_state_for_new_task_direction(
                state,
                clear_residual_workflow=not application_plan.preserve_residual_workflow,
            )

        if application_plan.supersede_recovered_target:
            state.set_residual_reentry_context(None)
            state.set_reentry_bias_applied(False)
            self._ensure_live_input_completion_bundle()["residual_reentry_context"] = None

        if application_plan.require_clarification:
            state.control.needs_user_input = True
            state.control.clarification_question = (
                application_plan.clarification_question
                or "Please clarify the intended deliverable or next step."
            )
            state.control.parameter_confirmation_prompt = None
            state.control.input_completion_prompt = None
            if trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.INTENT_RESOLUTION_APPLIED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action=decision.progress_intent.value,
                    input_summary={
                        "deliverable_intent": decision.deliverable_intent.value,
                        "progress_intent": decision.progress_intent.value,
                        "current_task_type": context.current_task_type,
                    },
                    output_summary={
                        "application_plan": application_plan.to_dict(),
                        "entered_clarification": True,
                    },
                    confidence=decision.confidence,
                    reasoning=application_plan.user_visible_summary
                    or decision.reason
                    or "Intent resolution requested bounded clarification.",
                )
            self._transition_state(
                state,
                TaskStage.NEEDS_CLARIFICATION,
                reason="intent resolution required clarification before safe biasing",
                trace_obj=trace_obj,
            )
            return

        if trace_obj is not None:
            trace_obj.record(
                step_type=TraceStepType.INTENT_RESOLUTION_APPLIED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action=decision.progress_intent.value,
                input_summary={
                    "deliverable_intent": decision.deliverable_intent.value,
                    "progress_intent": decision.progress_intent.value,
                    "current_task_type": context.current_task_type,
                },
                output_summary={
                    "application_plan": application_plan.to_dict(),
                    "guidance_preview": (self._build_intent_guidance_text(application_plan) or "")[:400],
                },
                confidence=decision.confidence,
                reasoning=application_plan.user_visible_summary
                or decision.reason
                or "Applied bounded deliverable/progress bias to the current workflow.",
            )

    def _inject_intent_resolution_guidance(
        self,
        context: Any,
        state: TaskState,
    ) -> None:
        plan = state.latest_intent_resolution_plan
        if plan is None:
            return
        guidance_text = self._build_intent_guidance_text(plan)
        if not guidance_text:
            return
        guidance_message = {"role": "system", "content": guidance_text}
        insert_at = len(context.messages)
        if context.messages and context.messages[-1].get("role") == "user":
            insert_at -= 1
        context.messages.insert(insert_at, guidance_message)

    def _apply_intent_bias_to_continuation_decision(
        self,
        state: TaskState,
        decision: ContinuationDecision,
    ) -> ContinuationDecision:
        plan = state.latest_intent_resolution_plan
        if (
            plan is None
            or not getattr(self.runtime_config, "intent_resolution_bias_continuation", True)
        ):
            return decision

        next_step = state.get_next_planned_step()
        next_action_id = None
        if next_step is not None:
            next_action_id = map_tool_call_to_action_id(
                next_step.tool_name,
                next_step.argument_hints,
            )
        preferred_actions = set(plan.preferred_action_ids)

        if plan.progress_intent == ProgressIntentType.START_NEW_TASK:
            decision.should_continue = False
            decision.should_replan = False
            decision.new_task_override = True
            decision.signal = "intent_start_new_task"
            decision.reason = (
                plan.user_visible_summary
                or "Intent resolution identified a new-task direction, so residual continuation was suppressed."
            )
            return decision

        if plan.progress_intent == ProgressIntentType.RESUME_RECOVERED_TARGET and state.residual_reentry_context is not None:
            target = state.residual_reentry_context.reentry_target
            decision.should_continue = True
            decision.continuation_ready = True
            if decision.signal not in {"geometry_recovery_resume", "geometry_recovery_waiting"}:
                decision.signal = "intent_resume_recovered_target"
                decision.reason = (
                    plan.user_visible_summary
                    or "Intent resolution biased the turn toward the recovered target action."
                )
            if target.target_tool_name:
                decision.next_tool_name = target.target_tool_name
            if target.target_action_id and not decision.next_step_id:
                decision.next_step_id = target.target_action_id
            return decision

        if plan.progress_intent == ProgressIntentType.CONTINUE_CURRENT_TASK and decision.residual_plan_exists and not decision.should_continue:
            decision.should_continue = True
            decision.continuation_ready = True
            decision.signal = "intent_continue_current_task"
            decision.reason = (
                plan.user_visible_summary
                or "Intent resolution kept the current residual workflow authoritative."
            )
            return decision

        if plan.progress_intent == ProgressIntentType.SHIFT_OUTPUT_MODE:
            if preferred_actions and next_action_id in preferred_actions:
                decision.should_continue = True
                decision.continuation_ready = True
                decision.signal = "intent_shift_output_mode_continue"
                decision.reason = (
                    "Intent resolution requested a different output mode, and the residual next step already aligned with that bounded preference."
                )
                return decision
            decision.should_continue = False
            decision.continuation_ready = False
            decision.signal = "intent_shift_output_mode"
            decision.reason = (
                plan.user_visible_summary
                or "Intent resolution recognized an output-mode shift, so default residual continuation was de-emphasized."
            )
            return decision

        return decision

    def _reset_state_for_new_task_direction(
        self,
        state: TaskState,
        *,
        clear_residual_workflow: bool,
    ) -> None:
        self._clear_live_parameter_negotiation_state(clear_locks=True)
        self._clear_live_input_completion_state(clear_overrides=True)
        state.input_completion_overrides.clear()
        state.set_active_parameter_negotiation(None)
        state.set_active_input_completion(None)
        state.set_latest_input_completion_decision(None)
        state.set_supporting_spatial_input(None)
        state.set_geometry_recovery_context(None)
        state.set_geometry_readiness_refresh_result(None)
        state.set_residual_reentry_context(None)
        state.set_reentry_bias_applied(False)
        state.set_latest_summary_delivery_plan(None)
        state.set_latest_summary_delivery_result(None)
        state.set_artifact_memory_state(ArtifactMemoryState())
        cached_file_context = getattr(state, "_file_analysis_cache", None)
        if isinstance(cached_file_context, dict):
            cached_file_context["latest_summary_delivery_plan"] = None
            cached_file_context["latest_summary_delivery_result"] = None
            cached_file_context["artifact_memory"] = state.artifact_memory_state.to_dict()
            cached_file_context["artifact_memory_summary"] = state.get_artifact_memory_summary()
            cached_file_context["latest_artifact_by_family"] = state.get_latest_artifact_by_family()
            cached_file_context["latest_artifact_by_type"] = state.get_latest_artifact_by_type()
            cached_file_context["recent_delivery_summary"] = state.get_recent_delivery_summary()
            setattr(state, "_file_analysis_cache", cached_file_context)
        if clear_residual_workflow:
            self._clear_live_continuation_state()
            state.set_plan(None)
            state.repair_history = []
            state.set_continuation_decision(None)
            state.execution.blocked_info = None

    def _build_file_analysis_fallback_messages(
        self,
        analysis_dict: Dict[str, Any],
        decision: FileAnalysisFallbackDecision,
    ) -> List[Dict[str, str]]:
        payload = build_file_analysis_fallback_payload(
            analysis_dict,
            decision,
            max_sample_rows=self.runtime_config.file_analysis_fallback_max_sample_rows,
            max_columns=self.runtime_config.file_analysis_fallback_max_columns,
        )
        return [
            {
                "role": "user",
                "content": (
                    "Infer a bounded fallback file analysis JSON for the following low-confidence grounding case.\n"
                    f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
                ),
            }
        ]

    async def _maybe_apply_file_analysis_fallback(
        self,
        analysis_dict: Dict[str, Any],
        *,
        trace_obj: Optional[Trace] = None,
    ) -> Dict[str, Any]:
        if not isinstance(analysis_dict, dict):
            return analysis_dict

        if not getattr(self.runtime_config, "enable_file_analysis_llm_fallback", False):
            return analysis_dict

        if analysis_dict.get("file_analysis_fallback_evaluated"):
            return analysis_dict

        decision = should_use_llm_fallback(
            analysis_dict,
            confidence_threshold=self.runtime_config.file_analysis_fallback_confidence_threshold,
            allow_zip_table_selection=self.runtime_config.file_analysis_fallback_allow_zip_table_selection,
        )
        analysis_dict["file_analysis_fallback_decision"] = decision.to_dict()
        analysis_dict["file_analysis_fallback_evaluated"] = True

        if not decision.should_use_fallback:
            analysis_dict.setdefault("analysis_strategy", "rule")
            analysis_dict.setdefault("fallback_used", False)
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.FILE_ANALYSIS_FALLBACK_SKIPPED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="file_analysis_llm_fallback",
                    input_summary={
                        "task_type": analysis_dict.get("task_type"),
                        "confidence": analysis_dict.get("confidence"),
                        "unresolved_columns": decision.unresolved_columns[:8],
                    },
                    output_summary={
                        "decision": decision.to_dict(),
                    },
                    reasoning=(
                        "Rule-based file grounding remained the primary path because the analysis stayed above "
                        "the fallback trigger policy."
                    ),
                )
            return analysis_dict

        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.FILE_ANALYSIS_FALLBACK_TRIGGERED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action="file_analysis_llm_fallback",
                input_summary={
                    "task_type": analysis_dict.get("task_type"),
                    "confidence": analysis_dict.get("confidence"),
                    "reasons": [reason.value for reason in decision.reasons],
                    "unresolved_columns": decision.unresolved_columns[:8],
                    "candidate_tables": (analysis_dict.get("candidate_tables") or [])[:8],
                },
                reasoning="; ".join(decision.reason_details) or "Low-confidence file grounding triggered bounded fallback.",
            )

        try:
            raw_payload = await self.llm.chat_json(
                messages=self._build_file_analysis_fallback_messages(analysis_dict, decision),
                system=FILE_ANALYSIS_FALLBACK_PROMPT,
                temperature=0.0,
            )
            llm_result = parse_llm_file_analysis_result(raw_payload, analysis_dict)
            merged = merge_rule_and_fallback_analysis(analysis_dict, llm_result)

            if not merged.used_fallback:
                analysis_dict["file_analysis_fallback_result"] = llm_result.to_dict()
                analysis_dict["file_analysis_fallback_merge_strategy"] = merged.merge_strategy
                analysis_dict["file_analysis_fallback_error"] = merged.reasoning_summary
                if trace_obj:
                    trace_obj.record(
                        step_type=TraceStepType.FILE_ANALYSIS_FALLBACK_FAILED,
                        stage_before=TaskStage.INPUT_RECEIVED.value,
                        action="file_analysis_llm_fallback",
                        input_summary={
                            "decision": decision.to_dict(),
                        },
                        output_summary={
                            "fallback_result": llm_result.to_dict(),
                            "merge_strategy": merged.merge_strategy,
                        },
                        reasoning=merged.reasoning_summary or "Fallback output was valid JSON but not strong enough to override rule analysis.",
                    )
                return analysis_dict

            final_analysis = dict(merged.analysis)
            final_analysis["file_analysis_fallback_decision"] = decision.to_dict()
            final_analysis["file_analysis_fallback_result"] = llm_result.to_dict()
            final_analysis["file_analysis_fallback_merge_strategy"] = merged.merge_strategy
            final_analysis["file_analysis_fallback_evaluated"] = True

            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.FILE_ANALYSIS_FALLBACK_APPLIED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="file_analysis_llm_fallback",
                    input_summary={
                        "decision": decision.to_dict(),
                    },
                    output_summary={
                        "task_type": final_analysis.get("task_type"),
                        "confidence": final_analysis.get("confidence"),
                        "column_mapping": dict(final_analysis.get("column_mapping") or {}),
                        "selected_primary_table": final_analysis.get("selected_primary_table"),
                        "merge_strategy": merged.merge_strategy,
                    },
                    confidence=final_analysis.get("confidence"),
                    reasoning=(
                        llm_result.reasoning_summary
                        or "Merged LLM fallback semantics into the canonical file analysis result."
                    ),
                )
            return final_analysis
        except Exception as exc:
            analysis_dict["file_analysis_fallback_error"] = str(exc)
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.FILE_ANALYSIS_FALLBACK_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="file_analysis_llm_fallback",
                    input_summary={
                        "decision": decision.to_dict(),
                    },
                    error=str(exc),
                    reasoning=(
                        "LLM fallback failed validation or execution, so the router kept the rule-based file analysis."
                    ),
                )
            return analysis_dict

    def _record_file_analysis_enhancement_traces(
        self,
        analysis_dict: Dict[str, Any],
        trace_obj: Optional[Trace],
    ) -> None:
        if not trace_obj or not isinstance(analysis_dict, dict):
            return

        dataset_roles = [
            dict(item)
            for item in (analysis_dict.get("dataset_roles") or [])
            if isinstance(item, dict)
        ]
        if len(dataset_roles) > 1:
            selected_roles = [item.get("dataset_name") for item in dataset_roles if item.get("selected")]
            trace_obj.record(
                step_type=TraceStepType.FILE_ANALYSIS_MULTI_TABLE_ROLES,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action="analyze_file_roles",
                input_summary={
                    "candidate_tables": (analysis_dict.get("candidate_tables") or [])[:10],
                },
                output_summary={
                    "selected_primary_table": analysis_dict.get("selected_primary_table"),
                    "dataset_roles": dataset_roles[:8],
                },
                reasoning=(
                    f"Detected {len(dataset_roles)} dataset role entries; "
                    f"selected primary={analysis_dict.get('selected_primary_table')}, "
                    f"selected roles={selected_roles or ['none']}."
                ),
            )

        diagnostics = analysis_dict.get("missing_field_diagnostics") or {}
        if diagnostics and diagnostics.get("status") not in {None, "complete", "unknown_task"}:
            trace_obj.record(
                step_type=TraceStepType.FILE_ANALYSIS_MISSING_FIELDS,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action="analyze_file_diagnostics",
                input_summary={
                    "task_type": diagnostics.get("task_type"),
                    "required_fields": (diagnostics.get("required_fields") or [])[:8],
                },
                output_summary={
                    "status": diagnostics.get("status"),
                    "missing_fields": (diagnostics.get("missing_fields") or [])[:6],
                    "derivable_opportunities": (diagnostics.get("derivable_opportunities") or [])[:6],
                },
                reasoning=(
                    f"Required-field diagnostics status={diagnostics.get('status')} "
                    f"for task_type={diagnostics.get('task_type')}."
                ),
            )

        spatial_metadata = analysis_dict.get("spatial_metadata") or {}
        if spatial_metadata:
            trace_obj.record(
                step_type=TraceStepType.FILE_ANALYSIS_SPATIAL_METADATA,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action="analyze_file_spatial_metadata",
                output_summary={
                    "geometry_types": (spatial_metadata.get("geometry_types") or [])[:6],
                    "crs": spatial_metadata.get("crs"),
                    "epsg": spatial_metadata.get("epsg"),
                    "bounds": spatial_metadata.get("bounds"),
                },
                reasoning=(
                    f"Extracted spatial metadata for {spatial_metadata.get('feature_count', '?')} features "
                    f"with geometry_types={spatial_metadata.get('geometry_types') or []}."
                ),
            )

    def _get_workflow_template_signals(self, state: TaskState) -> Optional[Dict[str, Any]]:
        cached_file_context = getattr(state, "_file_analysis_cache", None)
        if isinstance(cached_file_context, dict):
            return dict(cached_file_context)
        return self._build_state_file_context(state)

    def _format_workflow_template_injection(
        self,
        template: WorkflowTemplate,
        recommendation: TemplateRecommendation,
    ) -> str:
        return summarize_template_prior(template, recommendation)

    def _summarize_template_prior_alignment(
        self,
        plan: ExecutionPlan,
        template: Optional[WorkflowTemplate],
    ) -> Optional[str]:
        if template is None:
            return None
        template_tools = [step.tool_name for step in template.step_skeleton]
        plan_tools = [step.tool_name for step in plan.steps]
        if not template_tools or not plan_tools:
            return None
        if template_tools == plan_tools[: len(template_tools)]:
            return f"Planner stayed aligned with template prior {template.template_id}."

        matched_prefix = 0
        for expected, actual in zip(template_tools, plan_tools):
            if expected != actual:
                break
            matched_prefix += 1
        if matched_prefix > 0:
            return (
                f"Planner partially adapted template prior {template.template_id} after {matched_prefix} leading step(s); "
                f"template_tools={template_tools}, planned_tools={plan_tools}."
            )
        return (
            f"Planner diverged early from template prior {template.template_id}; "
            f"template_tools={template_tools}, planned_tools={plan_tools}."
        )

    def _recommend_workflow_template_prior(self, state: TaskState) -> TemplateSelectionResult:
        file_signals = self._get_workflow_template_signals(state)
        recommendations = recommend_workflow_templates(
            file_signals,
            user_message=state.user_message or "",
            max_recommendations=getattr(self.runtime_config, "workflow_template_max_recommendations", 3),
            min_confidence=max(
                0.25,
                float(getattr(self.runtime_config, "workflow_template_min_confidence", 0.55)) - 0.1,
            ),
        )
        selection = select_primary_template(
            recommendations,
            min_confidence=float(getattr(self.runtime_config, "workflow_template_min_confidence", 0.55)),
        )
        state.set_workflow_template_selection(selection)
        return selection

    def _record_workflow_template_selection(
        self,
        state: TaskState,
        selection: TemplateSelectionResult,
        *,
        reason_override: Optional[str] = None,
        trace_obj: Optional[Trace] = None,
    ) -> None:
        state.set_workflow_template_selection(selection)
        if trace_obj is None:
            return

        if selection.recommendations:
            trace_obj.record(
                step_type=TraceStepType.WORKFLOW_TEMPLATE_RECOMMENDED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action=selection.recommended_template_id,
                input_summary={
                    "task_type": state.file_context.task_type,
                    "confidence": state.file_context.confidence,
                },
                output_summary={
                    "recommendations": [item.to_dict() for item in selection.recommendations],
                },
                reasoning=(
                    reason_override
                    or "Rule-based workflow template recommendations were derived from the grounded file signals."
                ),
            )

        if selection.template_prior_used and selection.selected_template is not None:
            trace_obj.record(
                step_type=TraceStepType.WORKFLOW_TEMPLATE_SELECTED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action=selection.selected_template.template_id,
                output_summary={
                    "selected_template": selection.selected_template.to_dict(),
                    "selection_reason": selection.selection_reason,
                },
                reasoning=selection.selection_reason or "Selected the highest-ranked applicable template prior.",
            )
            top_recommendation = next(
                (
                    item
                    for item in selection.recommendations
                    if item.template_id == selection.selected_template.template_id
                ),
                None,
            )
            if top_recommendation is not None:
                guidance_text = self._format_workflow_template_injection(
                    selection.selected_template,
                    top_recommendation,
                )
                trace_obj.record(
                    step_type=TraceStepType.WORKFLOW_TEMPLATE_INJECTED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action=selection.selected_template.template_id,
                    output_summary={"guidance_preview": guidance_text[:400]},
                    reasoning=(
                        f"Prepared workflow template prior {selection.selected_template.template_id} "
                        "for the lightweight planning payload."
                    ),
                )
            return

        trace_obj.record(
            step_type=TraceStepType.WORKFLOW_TEMPLATE_SKIPPED,
            stage_before=TaskStage.INPUT_RECEIVED.value,
            reasoning=reason_override or selection.selection_reason or "Workflow template prior was not selected.",
            output_summary={
                "recommendation_count": len(selection.recommendations),
                "template_prior_used": selection.template_prior_used,
            },
        )

    def _should_generate_plan(self, state: TaskState) -> bool:
        """Decide whether to invoke the lightweight planner for this turn."""
        if not getattr(self.runtime_config, "enable_lightweight_planning", False):
            return False
        if state.plan is not None:
            return False

        message = (state.user_message or "").strip().lower()
        if (
            state.file_context.has_file
            and state.file_context.grounded
            and state.file_context.task_type in {"macro_emission", "micro_emission"}
        ):
            return True

        workflow_keywords = (
            "扩散",
            "dispersion",
            "热点",
            "hotspot",
            "地图",
            "可视化",
            "visualization",
            "render",
            "map",
            "compare",
            "comparison",
            "scenario",
            "对比",
            "然后",
            "接着",
            "下一步",
            "继续",
            "进一步",
            "follow up",
            "then",
            "next",
        )
        if any(keyword in message for keyword in workflow_keywords):
            return True

        return False

    def _infer_available_tokens_from_memory(self) -> List[str]:
        """Best-effort compatibility bridge from legacy memory slots."""
        fact_memory = self.memory.get_fact_memory()
        inferred: List[str] = []

        last_tool_name = fact_memory.get("last_tool_name")
        if isinstance(last_tool_name, str) and last_tool_name:
            inferred.extend(get_tool_provides(last_tool_name))

        spatial = fact_memory.get("last_spatial_data")
        if not isinstance(spatial, dict):
            return normalize_tokens(inferred)

        if spatial.get("hotspots") or spatial.get("hotspot_count"):
            inferred.append("hotspot")
        elif "raster_grid" in spatial or "concentration_grid" in spatial:
            inferred.append("dispersion")
        elif isinstance(spatial.get("results"), list):
            sample = spatial["results"][:3]
            if any(
                isinstance(item, dict) and item.get("total_emissions_kg_per_hr")
                for item in sample
            ):
                inferred.append("emission")

        return normalize_tokens(inferred)

    def _collect_available_result_tokens(
        self,
        state: TaskState,
        *,
        include_stale: bool = False,
        include_memory: bool = False,
    ) -> List[str]:
        """Collect canonical result tokens visible to the current state loop turn."""
        tokens: List[str] = []
        tokens.extend(state.execution.available_results)
        tokens.extend(self._ensure_context_store().get_available_types(include_stale=include_stale))
        if include_memory:
            tokens.extend(self._infer_available_tokens_from_memory())
        return normalize_tokens(tokens)

    def _load_live_residual_plan(self) -> tuple[Optional[ExecutionPlan], List[PlanRepairDecision], Optional[Dict[str, Any]], Optional[str]]:
        bundle = self._ensure_live_continuation_bundle()
        plan_snapshot = bundle.get("plan")
        plan = ExecutionPlan.from_dict(plan_snapshot) if isinstance(plan_snapshot, dict) else None
        repair_history = [
            PlanRepairDecision.from_dict(item)
            for item in bundle.get("repair_history", [])
            if isinstance(item, dict)
        ]
        blocked_info = dict(bundle["blocked_info"]) if isinstance(bundle.get("blocked_info"), dict) else None
        file_path = str(bundle["file_path"]) if bundle.get("file_path") else None
        return plan, repair_history, blocked_info, file_path

    def _load_active_parameter_negotiation_request(self) -> Optional[ParameterNegotiationRequest]:
        bundle = self._ensure_live_parameter_negotiation_bundle()
        payload = bundle.get("active_request")
        if isinstance(payload, dict):
            return ParameterNegotiationRequest.from_dict(payload)
        return None

    def _load_active_input_completion_request(self) -> Optional[InputCompletionRequest]:
        bundle = self._ensure_live_input_completion_bundle()
        payload = bundle.get("active_request")
        if isinstance(payload, dict):
            return InputCompletionRequest.from_dict(payload)
        return None

    def _clear_live_parameter_negotiation_state(self, *, clear_locks: bool = False) -> None:
        bundle = self._ensure_live_parameter_negotiation_bundle()
        bundle["active_request"] = None
        bundle["parameter_snapshot"] = {}
        bundle["file_path"] = None
        bundle["plan"] = None
        bundle["repair_history"] = []
        bundle["blocked_info"] = None
        bundle["latest_repair_summary"] = None
        bundle["residual_plan_summary"] = None
        bundle["original_goal"] = None
        bundle["original_user_message"] = None
        if clear_locks:
            bundle["locked_parameters"] = {}
            bundle["latest_confirmed_parameter"] = None

    def _clear_live_continuation_state(self) -> None:
        bundle = self._ensure_live_continuation_bundle()
        bundle["plan"] = None
        bundle["repair_history"] = []
        bundle["blocked_info"] = None
        bundle["file_path"] = None
        bundle["latest_repair_summary"] = None
        bundle["residual_plan_summary"] = None

    def _clear_live_input_completion_state(self, *, clear_overrides: bool = False) -> None:
        bundle = self._ensure_live_input_completion_bundle()
        bundle["active_request"] = None
        bundle["file_path"] = None
        bundle["plan"] = None
        bundle["repair_history"] = []
        bundle["blocked_info"] = None
        bundle["latest_repair_summary"] = None
        bundle["residual_plan_summary"] = None
        bundle["original_goal"] = None
        bundle["original_user_message"] = None
        bundle["action_id"] = None
        bundle["recovered_file_context"] = None
        bundle["supporting_spatial_input"] = None
        bundle["geometry_recovery_context"] = None
        bundle["readiness_refresh_result"] = None
        bundle["residual_reentry_context"] = None
        if clear_overrides:
            bundle["overrides"] = {}
            bundle["latest_decision"] = None

    def _clear_live_file_relationship_state(self, *, clear_pending: bool = True) -> None:
        bundle = self._ensure_live_file_relationship_bundle()
        bundle["latest_decision"] = None
        bundle["latest_transition_plan"] = None
        if clear_pending:
            bundle["pending_upload_summary"] = None
            bundle["pending_upload_analysis"] = None
            bundle["pending_primary_summary"] = None
            bundle["pending_primary_analysis"] = None
            bundle["awaiting_clarification"] = False
        bundle["attached_supporting_file"] = None

    def _clear_live_intent_resolution_state(self) -> None:
        bundle = self._ensure_live_intent_resolution_bundle()
        bundle["latest_decision"] = None
        bundle["latest_application_plan"] = None

    def _apply_live_parameter_state(self, state: TaskState) -> None:
        bundle = self._ensure_live_parameter_negotiation_bundle()
        locked_parameters = bundle.get("locked_parameters") or {}
        for name, payload in locked_parameters.items():
            if not isinstance(payload, dict):
                continue
            state.parameters[name] = ParamEntry.from_dict(payload)

        latest_confirmed = bundle.get("latest_confirmed_parameter")
        if isinstance(latest_confirmed, dict):
            state.set_latest_parameter_negotiation_decision(
                ParameterNegotiationDecision.from_dict(latest_confirmed)
            )

        active_request = bundle.get("active_request")
        if isinstance(active_request, dict):
            state.set_active_parameter_negotiation(ParameterNegotiationRequest.from_dict(active_request))

    def _apply_live_input_completion_state(self, state: TaskState) -> None:
        bundle = self._ensure_live_input_completion_bundle()
        recovered_file_context = bundle.get("recovered_file_context")
        current_file_path = str(state.file_context.file_path or "").strip() or None
        bundle_file_path = str(bundle.get("file_path") or "").strip() or None
        if isinstance(recovered_file_context, dict) and (
            current_file_path is None or current_file_path == bundle_file_path
        ):
            state.update_file_context(recovered_file_context)
            setattr(state, "_file_analysis_cache", dict(recovered_file_context))

        for key, payload in (bundle.get("overrides") or {}).items():
            if isinstance(payload, dict):
                state.apply_input_completion_override(key=str(key), override=payload)

        latest_decision = bundle.get("latest_decision")
        if isinstance(latest_decision, dict):
            state.set_latest_input_completion_decision(
                InputCompletionDecision.from_dict(latest_decision)
            )

        active_request = bundle.get("active_request")
        if isinstance(active_request, dict):
            state.set_active_input_completion(InputCompletionRequest.from_dict(active_request))

        supporting_spatial_input = bundle.get("supporting_spatial_input")
        if isinstance(supporting_spatial_input, dict):
            state.set_supporting_spatial_input(
                SupportingSpatialInput.from_dict(supporting_spatial_input)
            )

        geometry_recovery_context = bundle.get("geometry_recovery_context")
        if isinstance(geometry_recovery_context, dict):
            state.set_geometry_recovery_context(
                GeometryRecoveryContext.from_dict(geometry_recovery_context)
            )

        readiness_refresh_result = bundle.get("readiness_refresh_result")
        if isinstance(readiness_refresh_result, dict):
            state.set_geometry_readiness_refresh_result(readiness_refresh_result)

        residual_reentry_context = bundle.get("residual_reentry_context")
        if isinstance(residual_reentry_context, dict):
            state.set_residual_reentry_context(
                RecoveredWorkflowReentryContext.from_dict(residual_reentry_context)
            )

    def _apply_live_file_relationship_state(self, state: TaskState) -> None:
        bundle = self._ensure_live_file_relationship_bundle()

        latest_decision = bundle.get("latest_decision")
        if isinstance(latest_decision, dict):
            state.set_latest_file_relationship_decision(
                FileRelationshipDecision.from_dict(latest_decision)
            )

        latest_transition = bundle.get("latest_transition_plan")
        if isinstance(latest_transition, dict):
            state.set_latest_file_relationship_transition(
                FileRelationshipTransitionPlan.from_dict(latest_transition)
            )

        pending_upload_summary = bundle.get("pending_upload_summary")
        if isinstance(pending_upload_summary, dict):
            state.set_pending_file_relationship_upload(
                FileRelationshipFileSummary.from_dict(pending_upload_summary)
            )
        else:
            state.set_pending_file_relationship_upload(None)

        attached_supporting_file = bundle.get("attached_supporting_file")
        if isinstance(attached_supporting_file, dict):
            state.set_attached_supporting_file(
                FileRelationshipFileSummary.from_dict(attached_supporting_file)
            )
        else:
            state.set_attached_supporting_file(None)

        state.set_awaiting_file_relationship_clarification(
            bool(bundle.get("awaiting_clarification", False))
        )

    def _apply_live_intent_resolution_state(self, state: TaskState) -> None:
        bundle = self._ensure_live_intent_resolution_bundle()

        latest_decision = bundle.get("latest_decision")
        if isinstance(latest_decision, dict):
            state.set_latest_intent_resolution_decision(
                IntentResolutionDecision.from_dict(latest_decision)
            )

        latest_application_plan = bundle.get("latest_application_plan")
        if isinstance(latest_application_plan, dict):
            state.set_latest_intent_resolution_plan(
                IntentResolutionApplicationPlan.from_dict(latest_application_plan)
            )

    def _build_parameter_negotiation_request(
        self,
        tool_name: str,
        result: Dict[str, Any],
    ) -> Optional[ParameterNegotiationRequest]:
        if not getattr(self.runtime_config, "enable_parameter_negotiation", False):
            return None
        if not result.get("negotiation_eligible"):
            return None

        param_name = str(result.get("param_name") or "").strip()
        raw_value = result.get("original_value")
        records = list(result.get("_standardization_records") or [])
        target_record = None
        if param_name:
            for record in reversed(records):
                if record.get("param") == param_name:
                    target_record = record
                    break
        if target_record is None and records:
            target_record = records[-1]
            param_name = str(target_record.get("param") or param_name).strip()
            raw_value = target_record.get("original", raw_value)

        if not param_name:
            return None

        record_suggestions = target_record.get("suggestions") if isinstance(target_record, dict) else []
        suggestions = list(result.get("suggestions") or record_suggestions or [])
        max_candidates = max(int(getattr(self.runtime_config, "parameter_negotiation_max_candidates", 5)), 1)
        suggestions = suggestions[:max_candidates]
        if not suggestions:
            return None

        std_engine = getattr(self.executor, "_std_engine", None)
        alias_map = std_engine.get_candidate_aliases(param_name) if std_engine is not None else {}
        trigger_reason = str(result.get("trigger_reason") or "standardization requires confirmation").strip()
        confidence = target_record.get("confidence") if isinstance(target_record, dict) else None
        strategy = target_record.get("strategy") if isinstance(target_record, dict) else None

        candidates: List[NegotiationCandidate] = []
        seen = set()
        for index, suggestion in enumerate(suggestions, start=1):
            display_label = str(suggestion).strip()
            if not display_label:
                continue
            normalized_value = (
                std_engine.resolve_candidate_value(param_name, display_label)
                if std_engine is not None
                else None
            )
            if not normalized_value:
                label_match = re.match(r"^(.*?)\s*\((.*?)\)\s*$", display_label)
                normalized_value = (
                    label_match.group(2).strip()
                    if label_match and label_match.group(2).strip()
                    else display_label
                )
            dedupe_key = (display_label.lower(), normalized_value.lower())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            candidates.append(
                NegotiationCandidate(
                    index=index,
                    normalized_value=normalized_value,
                    display_label=display_label,
                    confidence=confidence,
                    strategy=strategy,
                    reason=trigger_reason,
                    aliases=build_candidate_aliases(
                        display_label,
                        normalized_value,
                        extra_aliases=list(alias_map.get(normalized_value, [])),
                    ),
                )
            )

        if not candidates:
            return None

        return ParameterNegotiationRequest.create(
            parameter_name=param_name,
            raw_value=raw_value,
            confidence=confidence,
            trigger_reason=trigger_reason,
            tool_name=tool_name,
            arg_name=param_name,
            strategy=strategy,
            candidates=candidates,
        )

    def _save_active_parameter_negotiation_bundle(
        self,
        state: TaskState,
        request: ParameterNegotiationRequest,
    ) -> None:
        bundle = self._ensure_live_parameter_negotiation_bundle()
        continuation_bundle = self._ensure_live_continuation_bundle()
        bundle.update(
            {
                "active_request": request.to_dict(),
                "parameter_snapshot": {
                    key: value.to_dict()
                    for key, value in state.parameters.items()
                },
                "file_path": state.file_context.file_path or continuation_bundle.get("file_path"),
                "plan": (
                    state.plan.to_dict()
                    if state.plan is not None
                    else continuation_bundle.get("plan")
                ),
                "repair_history": (
                    [decision.to_dict() for decision in state.repair_history]
                    if state.repair_history
                    else list(continuation_bundle.get("repair_history") or [])
                ),
                "blocked_info": (
                    dict(state.execution.blocked_info)
                    if isinstance(state.execution.blocked_info, dict)
                    else continuation_bundle.get("blocked_info")
                ),
                "latest_repair_summary": (
                    state.get_latest_repair_summary()
                    or continuation_bundle.get("latest_repair_summary")
                ),
                "residual_plan_summary": (
                    state.get_residual_plan_summary()
                    or continuation_bundle.get("residual_plan_summary")
                ),
                "original_goal": state.plan.goal if state.plan is not None else state.user_message,
                "original_user_message": state.user_message,
            }
        )

    def _save_active_input_completion_bundle(
        self,
        state: TaskState,
        request: InputCompletionRequest,
        affordance: ActionAffordance,
    ) -> None:
        bundle = self._ensure_live_input_completion_bundle()
        continuation_bundle = self._ensure_live_continuation_bundle()
        bundle.update(
            {
                "active_request": request.to_dict(),
                "overrides": state.get_input_completion_overrides_summary(),
                "latest_decision": (
                    state.latest_input_completion_decision.to_dict()
                    if state.latest_input_completion_decision is not None
                    else None
                ),
                "file_path": state.file_context.file_path or continuation_bundle.get("file_path"),
                "plan": (
                    state.plan.to_dict()
                    if state.plan is not None
                    else continuation_bundle.get("plan")
                ),
                "repair_history": (
                    [decision.to_dict() for decision in state.repair_history]
                    if state.repair_history
                    else list(continuation_bundle.get("repair_history") or [])
                ),
                "blocked_info": (
                    dict(state.execution.blocked_info)
                    if isinstance(state.execution.blocked_info, dict)
                    else continuation_bundle.get("blocked_info")
                ),
                "latest_repair_summary": (
                    state.get_latest_repair_summary()
                    or continuation_bundle.get("latest_repair_summary")
                ),
                "residual_plan_summary": (
                    state.get_residual_plan_summary()
                    or continuation_bundle.get("residual_plan_summary")
                ),
                "original_goal": state.plan.goal if state.plan is not None else state.user_message,
                "original_user_message": state.user_message,
                "action_id": affordance.action_id,
                "recovered_file_context": getattr(state, "_file_analysis_cache", None),
                "supporting_spatial_input": (
                    state.supporting_spatial_input.to_dict()
                    if state.supporting_spatial_input is not None
                    else bundle.get("supporting_spatial_input")
                ),
                "geometry_recovery_context": (
                    state.geometry_recovery_context.to_dict()
                    if state.geometry_recovery_context is not None
                    else bundle.get("geometry_recovery_context")
                ),
                "readiness_refresh_result": (
                    dict(state.geometry_readiness_refresh_result)
                    if isinstance(state.geometry_readiness_refresh_result, dict)
                    else bundle.get("readiness_refresh_result")
                ),
                "residual_reentry_context": (
                    state.residual_reentry_context.to_dict()
                    if state.residual_reentry_context is not None
                    else bundle.get("residual_reentry_context")
                ),
            }
        )

    def _build_parameter_confirmation_clarification(
        self,
        request: ParameterNegotiationRequest,
    ) -> str:
        return (
            f"你否定了 `{request.parameter_name}` 的候选集，但系统还没有合法值。"
            f" 请直接提供一个明确的 `{request.parameter_name}` 值，原始输入是 `{request.raw_value}`。"
        )

    def _build_input_completion_file_context_summary(
        self,
        state: TaskState,
    ) -> Optional[str]:
        file_context = self._build_state_file_context(state) or {}
        fragments: List[str] = []
        task_type = file_context.get("task_type")
        if task_type:
            fragments.append(f"task_type={task_type}")
        selected_primary_table = file_context.get("selected_primary_table")
        if selected_primary_table:
            fragments.append(f"primary_table={selected_primary_table}")
        columns = file_context.get("columns") or []
        if isinstance(columns, list) and columns:
            fragments.append(f"columns={len(columns)}")
        if file_context.get("spatial_metadata"):
            fragments.append("spatial_metadata=yes")
        diagnostics = file_context.get("missing_field_diagnostics") or {}
        if isinstance(diagnostics, dict) and diagnostics.get("status"):
            fragments.append(f"missing_field_status={diagnostics.get('status')}")
        return ", ".join(fragments) if fragments else None

    def _build_input_completion_request(
        self,
        state: TaskState,
        affordance: ActionAffordance,
    ) -> Optional[InputCompletionRequest]:
        if not getattr(self.runtime_config, "enable_input_completion_flow", False):
            return None
        reason = affordance.reason
        if reason is None:
            return None

        file_context = self._build_state_file_context(state) or {}
        related_summary = self._build_input_completion_file_context_summary(state)
        reason_code = str(reason.reason_code or "").strip()

        if reason_code == "missing_required_fields":
            diagnostics = file_context.get("missing_field_diagnostics") or {}
            field_statuses = [
                item
                for item in (diagnostics.get("required_field_statuses") or [])
                if isinstance(item, dict) and str(item.get("status") or "").strip().lower() != "present"
            ]
            if not field_statuses:
                return None
            missing_field_names = [
                str(item.get("field") or "").strip()
                for item in field_statuses
                if str(item.get("field") or "").strip()
            ]

            # --- Policy-based remediation: check if default typical profile applies ---
            policy_option: Optional[InputCompletionOption] = None
            remediation_policy: Optional[RemediationPolicy] = None
            if (
                getattr(self.runtime_config, "enable_policy_based_remediation", False)
                and getattr(self.runtime_config, "enable_default_typical_profile_policy", False)
            ):
                available_columns = list(file_context.get("columns") or [])
                task_type = str(file_context.get("task_type") or "").strip()
                allowed_task_types_tuple = getattr(
                    self.runtime_config, "default_typical_profile_allowed_task_types", ("macro_emission",)
                )
                allowed_set = set(allowed_task_types_tuple) if allowed_task_types_tuple else {"macro_emission"}
                remediation_policy = check_default_typical_profile_eligibility(
                    task_type=task_type,
                    missing_fields=missing_field_names,
                    available_columns=available_columns,
                    allowed_task_types=allowed_set,
                )
                if remediation_policy is not None:
                    target_fields_desc = "、".join(remediation_policy.target_fields)
                    signals_desc = "、".join(remediation_policy.context_signals_present)
                    policy_option = InputCompletionOption(
                        option_id="apply_default_typical_profile",
                        option_type=InputCompletionOptionType.APPLY_DEFAULT_TYPICAL_PROFILE,
                        label=f"使用默认典型值策略补齐 {target_fields_desc}",
                        description=(
                            f"根据已有道路属性（{signals_desc}）"
                            f"按保守典型值查找表自动为 {target_fields_desc} 填充估算值。"
                            f"这是一个有界的默认典型值策略，不是真实交通模型。"
                        ),
                        requirements={
                            "target_fields": list(remediation_policy.target_fields),
                            "context_signals_present": list(remediation_policy.context_signals_present),
                            "estimation_basis": remediation_policy.estimation_basis,
                            "policy_type": "apply_default_typical_profile",
                        },
                        default_hint=f"基于 {remediation_policy.estimation_basis}",
                        aliases=[
                            "默认典型值", "默认值模拟", "道路类型估算",
                            "用默认值", "典型值", "apply_default_typical_profile",
                        ],
                    )

            # For single-field missing: full option set
            # For multi-field missing: only offer policy option (if applicable) or return None
            if len(field_statuses) == 1:
                target = field_statuses[0]
                target_field = str(target.get("field") or "").strip()
                if not target_field:
                    return None

                options: List[InputCompletionOption] = []

                # Policy option first (if eligible) – it's the recommended path
                if policy_option is not None:
                    options.append(policy_option)

                if getattr(self.runtime_config, "input_completion_allow_uniform_scalar", True):
                    options.append(
                        InputCompletionOption(
                            option_id=f"{target_field}_uniform_value",
                            option_type=InputCompletionOptionType.PROVIDE_UNIFORM_VALUE,
                            label=f"为所有记录指定统一的 {target_field} 值",
                            description=f"直接为缺失字段 `{target_field}` 提供一个统一数值。",
                            requirements={"field": target_field},
                            default_hint="例如 1500",
                            aliases=["统一值", "统一", "全部设为"],
                        )
                    )

                derivation_candidates = target.get("derivation_candidates") or []
                if len(derivation_candidates) == 1:
                    candidate = derivation_candidates[0]
                    if isinstance(candidate, dict) and candidate.get("source_column"):
                        options.append(
                            InputCompletionOption(
                                option_id=f"{target_field}_use_derivation",
                                option_type=InputCompletionOptionType.USE_DERIVATION,
                                label=f"使用现有列推导 {target_field}",
                                description=(
                                    f"使用列 `{candidate['source_column']}` 作为 `{target_field}` 的受控补全来源。"
                                ),
                                requirements={
                                    "field": target_field,
                                    "source_column": candidate["source_column"],
                                    "derivation": candidate.get("derivation"),
                                },
                                default_hint=candidate["source_column"],
                                aliases=["推导", "用现有列", str(candidate["source_column"])],
                            )
                        )

                if getattr(self.runtime_config, "input_completion_allow_upload_support_file", True):
                    options.append(
                        InputCompletionOption(
                            option_id=f"{target_field}_upload_file",
                            option_type=InputCompletionOptionType.UPLOAD_SUPPORTING_FILE,
                            label="上传更完整的补充文件",
                            description="上传一个包含缺失字段的新文件，系统将用它替换当前缺失输入。",
                            requirements={"field": target_field},
                            aliases=["上传文件", "补充文件", "新文件"],
                        )
                    )

                options.append(
                    InputCompletionOption(
                        option_id=f"{target_field}_pause",
                        option_type=InputCompletionOptionType.PAUSE,
                        label="暂停当前补救",
                        description="暂时不补这个字段，先结束当前动作。",
                        aliases=["暂停", "稍后", "先不做"],
                    )
                )
                if not options:
                    return None
                max_options = max(int(getattr(self.runtime_config, "input_completion_max_options", 4)), 1)
                options = options[:max_options]

                # Build reason summary that aligns diagnostics with completion options
                reason_summary = reason.message
                if policy_option is not None and remediation_policy is not None:
                    all_target = remediation_policy.target_fields
                    if len(all_target) > 1:
                        reason_summary = (
                            f"{reason.message} "
                            f"其中 {'、'.join(all_target)} 可通过默认典型值策略一并补齐。"
                        )

                return InputCompletionRequest.create(
                    action_id=affordance.action_id,
                    reason_code=InputCompletionReasonCode.MISSING_REQUIRED_FIELD,
                    reason_summary=reason_summary,
                    missing_requirements=list(reason.missing_requirements),
                    options=options,
                    target_field=target_field,
                    current_task_type=str(file_context.get("task_type") or "").strip() or None,
                    related_file_context_summary=related_summary,
                    repair_hint=reason.repair_hint,
                )

            # Multi-field missing: only offer policy option if it covers all fields
            if policy_option is not None and remediation_policy is not None:
                covered = set(remediation_policy.target_fields)
                missing_set = set(missing_field_names)
                if missing_set <= covered or (missing_set & covered):
                    options = [policy_option]
                    if getattr(self.runtime_config, "input_completion_allow_upload_support_file", True):
                        options.append(
                            InputCompletionOption(
                                option_id="multi_field_upload_file",
                                option_type=InputCompletionOptionType.UPLOAD_SUPPORTING_FILE,
                                label="上传更完整的补充文件",
                                description="上传包含所有缺失字段的新文件。",
                                requirements={"fields": missing_field_names},
                                aliases=["上传文件", "补充文件", "新文件"],
                            )
                        )
                    options.append(
                        InputCompletionOption(
                            option_id="multi_field_pause",
                            option_type=InputCompletionOptionType.PAUSE,
                            label="暂停当前补救",
                            description="暂时不补这些字段，先结束当前动作。",
                            aliases=["暂停", "稍后", "先不做"],
                        )
                    )
                    max_options = max(int(getattr(self.runtime_config, "input_completion_max_options", 4)), 1)
                    options = options[:max_options]

                    target_fields_list = "、".join(missing_field_names)
                    reason_summary = (
                        f"{reason.message} "
                        f"{target_fields_list} 可通过默认典型值策略一并补齐。"
                    )

                    return InputCompletionRequest.create(
                        action_id=affordance.action_id,
                        reason_code=InputCompletionReasonCode.MISSING_REQUIRED_FIELD,
                        reason_summary=reason_summary,
                        missing_requirements=list(reason.missing_requirements),
                        options=options,
                        target_field=missing_field_names[0],
                        current_task_type=str(file_context.get("task_type") or "").strip() or None,
                        related_file_context_summary=related_summary,
                        repair_hint=reason.repair_hint,
                    )

            return None

        if reason_code == "missing_geometry":
            options = []
            if getattr(self.runtime_config, "input_completion_allow_upload_support_file", True):
                options.append(
                    InputCompletionOption(
                        option_id="geometry_upload_file",
                        option_type=InputCompletionOptionType.UPLOAD_SUPPORTING_FILE,
                        label="上传补充空间文件",
                        description="上传 GIS / GeoJSON / Shapefile，或包含 WKT / 坐标列的新文件。",
                        requirements={"geometry_support": True},
                        aliases=["上传文件", "上传空间文件", "gis", "geojson", "shapefile"],
                    )
                )
            options.append(
                InputCompletionOption(
                    option_id="geometry_pause",
                    option_type=InputCompletionOptionType.PAUSE,
                    label="暂停当前空间动作",
                    description="暂时不补空间数据，先结束当前动作。",
                    aliases=["暂停", "稍后", "先不做"],
                )
            )
            max_options = max(int(getattr(self.runtime_config, "input_completion_max_options", 4)), 1)
            return InputCompletionRequest.create(
                action_id=affordance.action_id,
                reason_code=InputCompletionReasonCode.MISSING_GEOMETRY,
                reason_summary=reason.message,
                missing_requirements=list(reason.missing_requirements),
                options=options[:max_options],
                target_field="geometry",
                current_task_type=str(file_context.get("task_type") or "").strip() or None,
                related_file_context_summary=related_summary,
                repair_hint=reason.repair_hint,
            )

        return None

    def _activate_input_completion_state(
        self,
        state: TaskState,
        request: InputCompletionRequest,
        affordance: ActionAffordance,
        *,
        prompt_text: Optional[str] = None,
        trace_obj: Optional[Trace] = None,
        record_required: bool = True,
    ) -> None:
        state.set_active_input_completion(request)
        state.control.needs_user_input = True
        state.control.input_completion_prompt = prompt_text or format_input_completion_prompt(request)
        state.control.parameter_confirmation_prompt = None
        state.control.clarification_question = None
        self._save_active_input_completion_bundle(state, request, affordance)
        self._transition_state(
            state,
            TaskStage.NEEDS_INPUT_COMPLETION,
            reason="Structured input completion required",
            trace_obj=trace_obj,
        )
        if trace_obj and record_required:
            trace_obj.record(
                step_type=TraceStepType.INPUT_COMPLETION_REQUIRED,
                stage_before=TaskStage.EXECUTING.value,
                stage_after=TaskStage.NEEDS_INPUT_COMPLETION.value,
                action=request.action_id,
                input_summary={
                    "reason_code": request.reason_code.value,
                    "target_field": request.target_field,
                    "missing_requirements": list(request.missing_requirements),
                },
                output_summary={
                    "request_id": request.request_id,
                    "options": [option.to_dict() for option in request.options],
                },
                reasoning=request.reason_summary,
            )
            # Trace REMEDIATION_POLICY_OPTION_OFFERED if a policy option is present
            policy_opt = request.get_first_option_by_type(InputCompletionOptionType.APPLY_DEFAULT_TYPICAL_PROFILE)
            if policy_opt is not None:
                trace_obj.record(
                    step_type=TraceStepType.REMEDIATION_POLICY_OPTION_OFFERED,
                    stage_before=TaskStage.NEEDS_INPUT_COMPLETION.value,
                    action=request.action_id,
                    input_summary={
                        "policy_type": "apply_default_typical_profile",
                        "target_fields": list(policy_opt.requirements.get("target_fields") or []),
                        "context_signals_present": list(policy_opt.requirements.get("context_signals_present") or []),
                    },
                    output_summary={
                        "option_id": policy_opt.option_id,
                        "estimation_basis": policy_opt.requirements.get("estimation_basis"),
                    },
                    reasoning=(
                        f"Default typical profile option offered for "
                        f"{', '.join(policy_opt.requirements.get('target_fields') or [])} "
                        f"based on {policy_opt.requirements.get('estimation_basis', 'road attributes')}."
                    ),
                )

    def _should_handle_input_completion(self, state: TaskState) -> bool:
        request = state.active_input_completion or self._load_active_input_completion_request()
        if request is None or not getattr(self.runtime_config, "enable_input_completion_flow", False):
            return False
        supporting_file_path = (
            str(state.incoming_file_path or "").strip()
            or str(state.file_context.file_path or "").strip()
            or None
        )
        return reply_looks_like_input_completion_attempt(
            request,
            state.user_message or "",
            supporting_file_path=supporting_file_path,
        )

    def _parse_input_completion_reply(
        self,
        state: TaskState,
    ) -> InputCompletionParseResult:
        request = state.active_input_completion or self._load_active_input_completion_request()
        if request is None:
            return InputCompletionParseResult(
                is_resolved=False,
                needs_retry=False,
                error_message="No active input completion request.",
            )
        supporting_file_path = (
            str(state.incoming_file_path or "").strip()
            or str(state.file_context.file_path or "").strip()
            or None
        )
        return parse_input_completion_reply(
            request,
            state.user_message or "",
            supporting_file_path=supporting_file_path,
        )

    def _build_input_completion_resume_decision(
        self,
        state: TaskState,
    ) -> Optional[ContinuationDecision]:
        bundle = self._ensure_live_input_completion_bundle()
        plan_snapshot = bundle.get("plan")
        if not isinstance(plan_snapshot, dict):
            return None

        plan = ExecutionPlan.from_dict(plan_snapshot)
        if not plan.has_pending_steps():
            return None

        repair_history = [
            PlanRepairDecision.from_dict(item)
            for item in (bundle.get("repair_history") or [])
            if isinstance(item, dict)
        ]
        state.set_plan(plan)
        state.repair_history = repair_history
        if not state.file_context.file_path and bundle.get("file_path"):
            state.file_context.file_path = str(bundle["file_path"])
            state.file_context.has_file = True
        self._refresh_execution_plan_state(state)

        next_step = state.get_next_planned_step()
        decision = ContinuationDecision(
            residual_plan_exists=True,
            continuation_ready=True,
            should_continue=True,
            should_replan=False,
            prompt_variant=self._resolve_continuation_prompt_variant(),
            signal="input_completion_resume",
            reason="input completion resolved a repairable action and resumed the residual workflow",
            next_step_id=next_step.step_id if next_step is not None else None,
            next_tool_name=next_step.tool_name if next_step is not None else None,
            latest_repair_summary=str(bundle.get("latest_repair_summary") or "").strip() or None,
            residual_plan_summary=str(bundle.get("residual_plan_summary") or "").strip() or None,
            latest_blocked_reason=(
                str((bundle.get("blocked_info") or {}).get("message")).strip()
                if isinstance(bundle.get("blocked_info"), dict) and (bundle.get("blocked_info") or {}).get("message")
                else None
            ),
        )
        self._ensure_live_continuation_bundle().update(
            {
                "plan": plan.to_dict(),
                "repair_history": [decision_item.to_dict() for decision_item in repair_history],
                "blocked_info": bundle.get("blocked_info"),
                "file_path": state.file_context.file_path or bundle.get("file_path"),
                "latest_repair_summary": bundle.get("latest_repair_summary"),
                "residual_plan_summary": bundle.get("residual_plan_summary"),
            }
        )
        return decision

    def _is_supported_geometry_recovery_file(
        self,
        file_path: Optional[str],
    ) -> tuple[bool, Optional[str], Optional[str]]:
        normalized_path = str(file_path or "").strip()
        if not normalized_path:
            return False, None, "Supporting-file geometry recovery requires an uploaded file in the same turn."

        suffix = Path(normalized_path).suffix.lower().lstrip(".")
        if not suffix:
            return False, None, "The uploaded supporting file did not have a recognizable extension."

        supported_types = {
            str(item).strip().lower()
            for item in getattr(self.runtime_config, "geometry_recovery_supported_file_types", ())
            if str(item).strip()
        }
        if suffix not in supported_types:
            supported_text = ", ".join(sorted(supported_types)) or "geojson, shp, zip, csv, xlsx, xls"
            return (
                False,
                suffix,
                f"Unsupported supporting spatial file type '.{suffix}'. Supported types: {supported_text}.",
            )
        return True, suffix, None

    async def _analyze_supporting_spatial_file(
        self,
        file_path: str,
    ) -> Dict[str, Any]:
        analysis_dict = await self._analyze_file(file_path)
        analysis_dict["file_path"] = file_path
        return await self._maybe_apply_file_analysis_fallback(
            analysis_dict,
            trace_obj=None,
        )

    def _build_geometry_readiness_refresh_result(
        self,
        *,
        request: InputCompletionRequest,
        affordance: Optional[ActionAffordance],
        assessment: Optional[ReadinessAssessment],
    ) -> Dict[str, Any]:
        after_status = affordance.status.value if affordance is not None else "unknown"
        after_reason_code = affordance.reason.reason_code if affordance and affordance.reason else None
        return {
            "action_id": request.action_id,
            "before_status": ReadinessStatus.REPAIRABLE.value,
            "before_reason_code": InputCompletionReasonCode.MISSING_GEOMETRY.value,
            "after_status": after_status,
            "after_reason_code": after_reason_code,
            "status_delta": f"{ReadinessStatus.REPAIRABLE.value}->{after_status}",
            "has_geometry_support": (
                assessment.key_signals.get("has_geometry_support")
                if assessment is not None
                else None
            ),
            "geometry_support_source": (
                assessment.key_signals.get("geometry_support_source")
                if assessment is not None
                else None
            ),
        }

    def _build_geometry_recovery_success_text(
        self,
        context: GeometryRecoveryContext,
        readiness_refresh_result: Dict[str, Any],
        reentry_context: Optional[RecoveredWorkflowReentryContext] = None,
    ) -> str:
        supporting = context.supporting_spatial_input
        action_id = context.target_action_id or "current_spatial_action"
        lines = [
            f"已接入补充空间文件 `{supporting.file_name}`，并完成一次受控 geometry re-grounding。",
            (
                f"当前主文件 `{Path(context.primary_file_ref).name if context.primary_file_ref else 'unknown'}` "
                f"已获得 bounded geometry support，目标动作 `{action_id}` 的就绪状态已从 "
                f"`{readiness_refresh_result.get('before_status')}` 刷新为 "
                f"`{readiness_refresh_result.get('after_status')}`。"
            ),
            "当前 workflow 已恢复到可继续决策状态，但本轮不会自动执行后续工具。",
        ]
        if reentry_context is not None:
            target = reentry_context.reentry_target
            target_label = target.display_name or target.target_action_id or action_id
            lines.append(
                f"下一轮若继续当前任务，优先回到 `{target_label}`"
                f"{f'（{target.target_tool_name}）' if target.target_tool_name else ''}。"
            )
        if context.resume_hint:
            lines.append(f"继续提示：{context.resume_hint}")
        if context.upstream_recompute_recommendation:
            lines.append(f"有界建议：{context.upstream_recompute_recommendation}")
        return "\n".join(lines)

    def _set_residual_reentry_context(
        self,
        state: TaskState,
        reentry_context: Optional[RecoveredWorkflowReentryContext],
    ) -> None:
        state.set_residual_reentry_context(reentry_context)
        state.set_reentry_bias_applied(False)
        self._ensure_live_input_completion_bundle()["residual_reentry_context"] = (
            reentry_context.to_dict() if reentry_context is not None else None
        )

    def _message_matches_reentry_target(
        self,
        message: str,
        reentry_context: RecoveredWorkflowReentryContext,
    ) -> bool:
        lowered = str(message or "").strip().lower()
        if not lowered:
            return False

        target = reentry_context.reentry_target
        candidates = []
        if target.target_action_id:
            candidates.append(target.target_action_id)
        if target.target_tool_name:
            candidates.append(target.target_tool_name)
            candidates.extend(CONTINUATION_TOOL_KEYWORDS.get(target.target_tool_name, []))
        if target.display_name:
            candidates.append(target.display_name)

        for candidate in candidates:
            normalized = str(candidate or "").strip().lower()
            if normalized and normalized in lowered:
                return True
        return False

    def _evaluate_reentry_target_readiness(
        self,
        state: TaskState,
        reentry_context: RecoveredWorkflowReentryContext,
    ) -> tuple[Optional[ReadinessAssessment], Optional[ActionAffordance], Optional[bool]]:
        target_action_id = reentry_context.reentry_target.target_action_id
        if not target_action_id:
            return None, None, None
        assessment = self._build_readiness_assessment(
            state.execution.tool_results,
            state=state,
            frontend_payloads=self._extract_frontend_payloads(state.execution.tool_results),
            trace_obj=None,
            stage_before=None,
            purpose="input_completion_recheck",
        )
        affordance = assessment.get_action(target_action_id) if assessment is not None else None
        if affordance is None:
            return assessment, None, None
        return assessment, affordance, affordance.status == ReadinessStatus.READY

    def _build_residual_reentry_decision(
        self,
        state: TaskState,
        continuation_decision: Optional[ContinuationDecision],
    ) -> Optional[ReentryDecision]:
        if not getattr(self.runtime_config, "enable_residual_reentry_controller", True):
            return None

        reentry_context = state.residual_reentry_context
        if reentry_context is None:
            return None

        target = reentry_context.reentry_target
        if target is None:
            return ReentryDecision(
                should_apply=False,
                decision_status="skipped",
                reason="Recovered workflow had no formal re-entry target.",
                source="geometry_recovery",
                residual_plan_exists=bool(continuation_decision and continuation_decision.residual_plan_exists),
            )

        guidance_summary = build_reentry_guidance_summary(
            reentry_target=target,
            residual_plan_summary=(
                continuation_decision.residual_plan_summary
                if continuation_decision and continuation_decision.residual_plan_summary
                else reentry_context.residual_plan_summary
            ),
            geometry_recovery_context=reentry_context.geometry_recovery_context,
        )

        decision = ReentryDecision(
            should_apply=False,
            decision_status="skipped",
            target=target,
            source=target.source,
            guidance_summary=guidance_summary,
            continuation_signal=continuation_decision.signal if continuation_decision else None,
            new_task_override=bool(continuation_decision and continuation_decision.new_task_override),
            residual_plan_exists=bool(continuation_decision and continuation_decision.residual_plan_exists),
        )

        if continuation_decision is None:
            decision.reason = "No continuation decision was available for the recovered workflow."
            return decision

        if continuation_decision.new_task_override:
            decision.reason = "The user explicitly started a new task, so recovered-workflow re-entry bias was skipped."
            return decision

        if not continuation_decision.should_continue:
            decision.reason = (
                continuation_decision.reason
                or "The new turn did not safely continue the recovered workflow."
            )
            return decision

        if (
            getattr(self.runtime_config, "residual_reentry_require_ready_target", True)
            and target.target_action_id
        ):
            _assessment, affordance, target_ready = self._evaluate_reentry_target_readiness(
                state,
                reentry_context,
            )
            decision.target_ready = target_ready
            decision.readiness_status = affordance.status.value if affordance is not None else None
            if target_ready is not True:
                decision.decision_status = "stale"
                decision.reason = (
                    "Recovered re-entry target was not re-validated as ready on the new turn, so the bias was skipped."
                )
                return decision

        decision.should_apply = True
        decision.decision_status = "applied"
        decision.reason = (
            "Recovered workflow continuation stayed on-task, so the next turn was deterministically biased toward the repaired target action."
        )
        return decision

    def _record_residual_reentry_decision(
        self,
        state: TaskState,
        decision: ReentryDecision,
        trace_obj: Optional[Trace] = None,
    ) -> None:
        reentry_context = state.residual_reentry_context
        if reentry_context is not None:
            reentry_context.apply_decision(decision)
            state.set_residual_reentry_context(reentry_context)
            self._ensure_live_input_completion_bundle()["residual_reentry_context"] = reentry_context.to_dict()
        state.set_reentry_bias_applied(decision.should_apply)

        if trace_obj is None:
            return

        target_summary = decision.target.to_summary() if decision.target is not None else None
        trace_obj.record(
            step_type=TraceStepType.RESIDUAL_REENTRY_DECIDED,
            stage_before=TaskStage.INPUT_RECEIVED.value,
            action=decision.target.target_tool_name if decision.target is not None else None,
            input_summary={
                "continuation_signal": decision.continuation_signal,
                "new_task_override": decision.new_task_override,
                "residual_plan_exists": decision.residual_plan_exists,
                "target": target_summary,
            },
            output_summary={
                "should_apply": decision.should_apply,
                "decision_status": decision.decision_status,
                "target_ready": decision.target_ready,
                "readiness_status": decision.readiness_status,
            },
            reasoning=decision.reason or "Recovered-workflow re-entry decision evaluated.",
        )
        if not decision.should_apply:
            trace_obj.record(
                step_type=TraceStepType.RESIDUAL_REENTRY_SKIPPED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action=decision.target.target_tool_name if decision.target is not None else None,
                input_summary={"target": target_summary},
                output_summary={
                    "decision_status": decision.decision_status,
                    "target_ready": decision.target_ready,
                    "readiness_status": decision.readiness_status,
                },
                reasoning=decision.reason or "Recovered-workflow re-entry bias was skipped.",
            )

    def _inject_residual_reentry_guidance(
        self,
        context: Any,
        state: TaskState,
        decision: ReentryDecision,
        trace_obj: Optional[Trace] = None,
    ) -> None:
        if not decision.should_apply or not decision.guidance_summary:
            return

        guidance_message = {"role": "system", "content": decision.guidance_summary}
        insert_at = len(context.messages)
        if context.messages and context.messages[-1].get("role") == "user":
            insert_at -= 1
        context.messages.insert(insert_at, guidance_message)

        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.RESIDUAL_REENTRY_INJECTED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action=decision.target.target_tool_name if decision.target is not None else None,
                input_summary={
                    "target": (
                        decision.target.to_summary()
                        if decision.target is not None
                        else None
                    ),
                },
                output_summary={"guidance_preview": decision.guidance_summary[:400]},
                reasoning=(
                    "Injected bounded recovered-workflow re-entry guidance without introducing auto-replay or scheduler semantics."
                ),
            )

    async def _handle_geometry_completion_upload(
        self,
        state: TaskState,
        request: InputCompletionRequest,
        decision: InputCompletionDecision,
        *,
        trace_obj: Optional[Trace] = None,
    ) -> bool:
        if not getattr(self.runtime_config, "enable_geometry_recovery_path", True):
            return False

        bundle = self._ensure_live_input_completion_bundle()
        self._set_residual_reentry_context(state, None)
        file_ref = str((decision.structured_payload or {}).get("file_ref") or "").strip()
        primary_file_ref = (
            str(bundle.get("file_path") or "").strip()
            or str(state.file_context.file_path or "").strip()
            or None
        )
        readiness_before = {
            "status": ReadinessStatus.REPAIRABLE.value,
            "reason_code": InputCompletionReasonCode.MISSING_GEOMETRY.value,
        }

        if not primary_file_ref:
            error_message = "Geometry recovery requires an existing primary file before a supporting spatial file can be attached."
            prompt_text = format_input_completion_prompt(
                request,
                retry_message=error_message,
            )
            state.control.needs_user_input = True
            state.control.input_completion_prompt = prompt_text
            self._transition_state(
                state,
                TaskStage.NEEDS_INPUT_COMPLETION,
                reason="Geometry recovery had no primary file context to repair",
                trace_obj=trace_obj,
            )
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.GEOMETRY_RE_GROUNDING_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action=request.action_id,
                    reasoning=error_message,
                )
                trace_obj.record(
                    step_type=TraceStepType.INPUT_COMPLETION_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    stage_after=TaskStage.NEEDS_INPUT_COMPLETION.value,
                    action=request.action_id,
                    input_summary={"request_id": request.request_id, "user_reply": decision.user_reply},
                    reasoning=error_message,
                )
            return True

        supported, detected_type, support_error = self._is_supported_geometry_recovery_file(file_ref)
        if supported:
            supporting_analysis = await self._analyze_supporting_spatial_file(file_ref)
            supporting_spatial_input = SupportingSpatialInput.from_analysis(
                file_ref=file_ref,
                source="input_completion_upload",
                analysis_dict=supporting_analysis,
            )
        else:
            supporting_spatial_input = SupportingSpatialInput(
                file_ref=file_ref,
                file_name=Path(file_ref).name if file_ref else "",
                file_type=detected_type,
                source="input_completion_upload",
                geometry_capability_summary={
                    "has_geometry_support": False,
                    "support_modes": [],
                    "notes": [support_error] if support_error else [],
                    "file_type": detected_type,
                },
                dataset_roles=[],
                spatial_metadata={},
            )
            supporting_analysis = {}

        state.set_supporting_spatial_input(supporting_spatial_input)
        bundle["supporting_spatial_input"] = supporting_spatial_input.to_dict()
        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.GEOMETRY_COMPLETION_ATTACHED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action=request.action_id,
                input_summary={
                    "source": supporting_spatial_input.source,
                    "target_action_id": request.action_id,
                },
                output_summary=supporting_spatial_input.to_summary(),
                reasoning=(
                    f"Attached supporting spatial file {supporting_spatial_input.file_name or file_ref} "
                    f"for repairable geometry recovery."
                ),
            )

        recovery_context = build_geometry_recovery_context(
            primary_file_ref=primary_file_ref,
            supporting_spatial_input=supporting_spatial_input,
            target_action_id=request.action_id,
            target_task_type=request.current_task_type,
            residual_plan_summary=str(bundle.get("residual_plan_summary") or "").strip() or None,
            readiness_before=readiness_before,
        )
        state.set_geometry_recovery_context(recovery_context)
        bundle["geometry_recovery_context"] = recovery_context.to_dict()

        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.GEOMETRY_RE_GROUNDING_TRIGGERED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action=request.action_id,
                input_summary={
                    "primary_file_ref": primary_file_ref,
                    "supporting_file_ref": supporting_spatial_input.file_ref,
                    "target_task_type": request.current_task_type,
                },
                output_summary={
                    "supporting_file_type": supporting_spatial_input.file_type,
                    "support_modes": supporting_spatial_input.geometry_capability_summary.get("support_modes"),
                },
                reasoning=(
                    "Triggered bounded geometry re-grounding with the current primary file plus one supporting spatial file."
                ),
            )

        if support_error:
            recovery_context.recovery_status = GeometryRecoveryStatus.FAILED.value
            recovery_context.failure_reason = support_error
            state.set_geometry_recovery_context(recovery_context)
            bundle["geometry_recovery_context"] = recovery_context.to_dict()
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.GEOMETRY_RE_GROUNDING_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action=request.action_id,
                    input_summary={"supporting_file_ref": file_ref},
                    reasoning=support_error,
                )
            prompt_text = format_input_completion_prompt(
                request,
                retry_message=support_error,
            )
            state.control.needs_user_input = True
            state.control.input_completion_prompt = prompt_text
            self._transition_state(
                state,
                TaskStage.NEEDS_INPUT_COMPLETION,
                reason="Supporting spatial file type was not eligible for bounded geometry recovery",
                trace_obj=trace_obj,
            )
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.INPUT_COMPLETION_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    stage_after=TaskStage.NEEDS_INPUT_COMPLETION.value,
                    action=request.action_id,
                    input_summary={"request_id": request.request_id, "user_reply": decision.user_reply},
                    reasoning=support_error,
                )
            return True

        primary_file_context = self._get_file_context_for_synthesis(state) or {}
        if primary_file_ref:
            primary_file_context["file_path"] = primary_file_ref

        re_grounding_result = re_ground_with_supporting_spatial_input(
            primary_file_context=primary_file_context,
            supporting_spatial_input=supporting_spatial_input,
            target_action_id=request.action_id,
            target_task_type=request.current_task_type,
            residual_plan_summary=str(bundle.get("residual_plan_summary") or "").strip() or None,
        )

        if not re_grounding_result.success:
            recovery_context.recovery_status = GeometryRecoveryStatus.FAILED.value
            recovery_context.failure_reason = re_grounding_result.failure_reason
            recovery_context.re_grounding_notes = list(re_grounding_result.re_grounding_notes)
            state.set_geometry_recovery_context(recovery_context)
            bundle["geometry_recovery_context"] = recovery_context.to_dict()
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.GEOMETRY_RE_GROUNDING_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action=request.action_id,
                    input_summary={
                        "primary_file_ref": primary_file_ref,
                        "supporting_file_ref": supporting_spatial_input.file_ref,
                    },
                    output_summary={
                        "supporting_file_summary": supporting_spatial_input.to_summary(),
                    },
                    reasoning=re_grounding_result.failure_reason
                    or "Supporting file did not establish bounded geometry support.",
                )
            prompt_text = format_input_completion_prompt(
                request,
                retry_message=re_grounding_result.failure_reason,
            )
            state.control.needs_user_input = True
            state.control.input_completion_prompt = prompt_text
            self._transition_state(
                state,
                TaskStage.NEEDS_INPUT_COMPLETION,
                reason="Geometry re-grounding did not restore bounded geometry support",
                trace_obj=trace_obj,
            )
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.INPUT_COMPLETION_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    stage_after=TaskStage.NEEDS_INPUT_COMPLETION.value,
                    action=request.action_id,
                    input_summary={"request_id": request.request_id, "user_reply": decision.user_reply},
                    reasoning=re_grounding_result.failure_reason or "Geometry re-grounding failed.",
                )
            return True

        updated_file_context = dict(re_grounding_result.updated_file_context)
        updated_file_context["file_path"] = primary_file_ref
        state.update_file_context(updated_file_context)
        setattr(state, "_file_analysis_cache", updated_file_context)
        bundle["recovered_file_context"] = updated_file_context

        recovery_context.recovery_status = GeometryRecoveryStatus.RE_GROUNDED.value
        recovery_context.re_grounding_notes = list(re_grounding_result.re_grounding_notes)
        state.set_geometry_recovery_context(recovery_context)
        bundle["geometry_recovery_context"] = recovery_context.to_dict()

        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.GEOMETRY_RE_GROUNDING_APPLIED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action=request.action_id,
                input_summary={
                    "primary_file_ref": primary_file_ref,
                    "supporting_file_ref": supporting_spatial_input.file_ref,
                },
                output_summary={
                    "geometry_support_facts": list(re_grounding_result.geometry_support_facts),
                    "canonical_signals": dict(re_grounding_result.canonical_signals),
                },
                reasoning="Applied bounded file-aware re-grounding and refreshed geometry-support facts in the current task context.",
            )

        assessment = None
        if getattr(self.runtime_config, "geometry_recovery_require_readiness_refresh", True):
            assessment = self._build_readiness_assessment(
                state.execution.tool_results,
                state=state,
                frontend_payloads=self._extract_frontend_payloads(state.execution.tool_results),
                trace_obj=None,
                stage_before=None,
                purpose="input_completion_recheck",
            )
        affordance = assessment.get_action(request.action_id) if assessment is not None else None
        readiness_refresh_result = self._build_geometry_readiness_refresh_result(
            request=request,
            affordance=affordance,
            assessment=assessment,
        )
        state.set_geometry_readiness_refresh_result(readiness_refresh_result)
        bundle["readiness_refresh_result"] = readiness_refresh_result

        recovery_context.readiness_after = dict(readiness_refresh_result)
        reentry_context: Optional[RecoveredWorkflowReentryContext] = None
        if affordance is not None and affordance.status == ReadinessStatus.READY:
            recovery_context.recovery_status = GeometryRecoveryStatus.RESUMABLE.value
            recovery_context.resume_hint = (
                f"Geometry support is now available; the repaired workflow can resume with `{request.action_id}` on the next turn."
            )
            recovery_context.upstream_recompute_recommendation = (
                re_grounding_result.upstream_recompute_recommendation
            )
            if getattr(self.runtime_config, "enable_residual_reentry_controller", True):
                reentry_plan = ExecutionPlan.from_dict(bundle.get("plan")) if isinstance(bundle.get("plan"), dict) else None
                reentry_context = build_recovered_workflow_reentry_context(
                    geometry_recovery_context=recovery_context,
                    readiness_refresh_result=readiness_refresh_result,
                    residual_plan=reentry_plan,
                    residual_plan_summary=str(bundle.get("residual_plan_summary") or "").strip() or None,
                    prioritize_recovery_target=getattr(
                        self.runtime_config,
                        "residual_reentry_prioritize_recovery_target",
                        True,
                    ),
                )
                self._set_residual_reentry_context(state, reentry_context)
        else:
            reason_message = (
                affordance.reason.message
                if affordance is not None and affordance.reason is not None
                else "Readiness refresh did not turn the target action into ready."
            )
            recovery_context.recovery_status = GeometryRecoveryStatus.FAILED.value
            recovery_context.failure_reason = reason_message
            self._set_residual_reentry_context(state, None)
        state.set_geometry_recovery_context(recovery_context)
        bundle["geometry_recovery_context"] = recovery_context.to_dict()

        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.GEOMETRY_READINESS_REFRESHED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action=request.action_id,
                input_summary={
                    "before_status": readiness_refresh_result.get("before_status"),
                    "before_reason_code": readiness_refresh_result.get("before_reason_code"),
                },
                output_summary={
                    "after_status": readiness_refresh_result.get("after_status"),
                    "after_reason_code": readiness_refresh_result.get("after_reason_code"),
                    "status_delta": readiness_refresh_result.get("status_delta"),
                },
                reasoning=(
                    f"Readiness refreshed after geometry remediation: "
                    f"{readiness_refresh_result.get('status_delta')}."
                ),
            )
            if reentry_context is not None:
                trace_obj.record(
                    step_type=TraceStepType.RESIDUAL_REENTRY_TARGET_SET,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action=reentry_context.reentry_target.target_tool_name,
                    input_summary={
                        "target_action_id": request.action_id,
                        "source": reentry_context.reentry_target.source,
                    },
                    output_summary={
                        "reentry_target": reentry_context.reentry_target.to_summary(),
                        "reentry_status": reentry_context.reentry_status,
                    },
                    reasoning=(
                        "Geometry recovery succeeded, so a formal recovered-workflow re-entry target was set for the next turn."
                    ),
                )

        if affordance is None or affordance.status != ReadinessStatus.READY:
            failure_reason = (
                recovery_context.failure_reason
                or "The supporting file was attached, but the target action is still not ready."
            )
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.GEOMETRY_RE_GROUNDING_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action=request.action_id,
                    input_summary={
                        "primary_file_ref": primary_file_ref,
                        "supporting_file_ref": supporting_spatial_input.file_ref,
                    },
                    output_summary={
                        "readiness_refresh_result": readiness_refresh_result,
                    },
                    reasoning=failure_reason,
                )
            prompt_text = format_input_completion_prompt(
                request,
                retry_message=failure_reason,
            )
            state.control.needs_user_input = True
            state.control.input_completion_prompt = prompt_text
            self._transition_state(
                state,
                TaskStage.NEEDS_INPUT_COMPLETION,
                reason="Geometry recovery remained insufficient after readiness refresh",
                trace_obj=trace_obj,
            )
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.INPUT_COMPLETION_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    stage_after=TaskStage.NEEDS_INPUT_COMPLETION.value,
                    action=request.action_id,
                    input_summary={"request_id": request.request_id, "user_reply": decision.user_reply},
                    reasoning=failure_reason,
                )
            return True

        override_payload = {
            "mode": "uploaded_supporting_file",
            "file_ref": supporting_spatial_input.file_ref,
            "source": "input_completion",
            "request_id": request.request_id,
            "action_id": request.action_id,
            "supporting_spatial_input": supporting_spatial_input.to_dict(),
            "geometry_recovery_status": recovery_context.recovery_status,
        }
        state.apply_input_completion_override(key="geometry_support", override=override_payload)
        state.set_latest_input_completion_decision(decision)
        state.set_active_input_completion(None)
        state.control.needs_user_input = False
        state.control.input_completion_prompt = None
        state.control.clarification_question = None
        state.control.parameter_confirmation_prompt = None

        bundle["active_request"] = None
        bundle["latest_decision"] = decision.to_dict()
        bundle["overrides"] = state.get_input_completion_overrides_summary()
        bundle["file_path"] = primary_file_ref

        resume_decision = self._build_input_completion_resume_decision(state)
        if resume_decision is not None:
            state.set_continuation_decision(resume_decision)

        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.INPUT_COMPLETION_APPLIED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action=request.action_id,
                input_summary={"request_id": request.request_id},
                output_summary={
                    "overrides": state.get_input_completion_overrides_summary(),
                    "readiness_recheck": readiness_refresh_result,
                },
                reasoning="Applied geometry supporting-file completion and refreshed bounded recovery state.",
            )
            trace_obj.record(
                step_type=TraceStepType.GEOMETRY_RECOVERY_RESUMED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action=request.action_id,
                input_summary={
                    "target_action_id": request.action_id,
                    "residual_plan_summary": bundle.get("residual_plan_summary"),
                },
                output_summary={
                    "resume_hint": recovery_context.resume_hint,
                    "upstream_recompute_recommendation": recovery_context.upstream_recompute_recommendation,
                    "after_status": readiness_refresh_result.get("after_status"),
                },
                reasoning=(
                    "Restored the current task context after bounded geometry remediation without auto-executing downstream tools."
                ),
            )

        setattr(
            state,
            "_final_response_text",
            self._build_geometry_recovery_success_text(
                recovery_context,
                readiness_refresh_result,
                reentry_context=reentry_context,
            ),
        )
        self._transition_state(
            state,
            TaskStage.DONE,
            reason="Geometry recovery succeeded; current workflow became resumable without auto execution",
            trace_obj=trace_obj,
        )
        return True

    def _inject_input_completion_guidance(
        self,
        context: Any,
        state: TaskState,
    ) -> None:
        overrides = state.get_input_completion_overrides_summary()
        if not overrides:
            return

        bundle = self._ensure_live_input_completion_bundle()
        latest_decision = state.latest_input_completion_decision
        original_task = str(bundle.get("original_user_message") or "").strip() or None
        geometry_context = state.geometry_recovery_context
        supporting_spatial_input = state.supporting_spatial_input
        reentry_context = state.residual_reentry_context

        lines = ["[Input completion overrides]"]
        if latest_decision is not None:
            lines.append(
                "The current turn resolved a bounded input-completion request. "
                "Treat the remediation result as binding execution context."
            )
        if original_task:
            lines.append(f"Continue the original task instead of treating this reply as standalone: {original_task}")
        for key, payload in overrides.items():
            mode = str(payload.get("mode") or "unknown")
            if mode == "uniform_scalar":
                lines.append(f"- {key} = {payload.get('value')} (uniform scalar)")
            elif mode == "source_column_derivation":
                lines.append(f"- {key} <- {payload.get('source_column')} (bounded derivation)")
            elif mode == "uploaded_supporting_file":
                lines.append(f"- {key} uses supporting file {payload.get('file_ref')}")
            else:
                lines.append(f"- {key}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")
        if supporting_spatial_input is not None:
            lines.append(
                f"- supporting_spatial_input={supporting_spatial_input.file_name} "
                f"({supporting_spatial_input.file_type or 'unknown'})"
            )
        if geometry_context is not None:
            lines.append(
                f"- geometry_recovery_status={geometry_context.recovery_status} "
                f"for action {geometry_context.target_action_id or 'unknown'}"
            )
            if geometry_context.resume_hint:
                lines.append(f"- resume_hint: {geometry_context.resume_hint}")
            if geometry_context.upstream_recompute_recommendation:
                lines.append(
                    f"- upstream_recompute_recommendation: {geometry_context.upstream_recompute_recommendation}"
                )
        if reentry_context is not None:
            target = reentry_context.reentry_target
            lines.append(
                f"- reentry_target={target.target_action_id or 'unknown'}"
                f" -> {target.target_tool_name or 'unknown_tool'}"
            )
            lines.append(f"- reentry_status={reentry_context.reentry_status}")
        lines.append(
            "Use these overrides exactly. Do not ignore them, and do not reopen the same missing-input issue unless readiness still remains unsatisfied after re-evaluation."
        )
        guidance_message = {"role": "system", "content": "\n".join(lines)}
        insert_at = len(context.messages)
        if context.messages and context.messages[-1].get("role") == "user":
            insert_at -= 1
        context.messages.insert(insert_at, guidance_message)

    def _apply_input_completion_decision(
        self,
        state: TaskState,
        request: InputCompletionRequest,
        decision: InputCompletionDecision,
    ) -> tuple[bool, Optional[ContinuationDecision], Optional[Dict[str, Any]], Optional[str]]:
        selected_option = request.get_option(decision.selected_option_id)
        if selected_option is None:
            return False, None, None, "Selected completion option was not found in the active request."

        payload = dict(decision.structured_payload or {})
        mode = str(payload.get("mode") or "").strip().lower()
        override_key: Optional[str] = None
        override_payload: Optional[Dict[str, Any]] = None

        if mode == "uniform_scalar":
            override_key = request.target_field
            override_payload = {
                "mode": "uniform_scalar",
                "value": payload.get("value"),
                "source": "input_completion",
                "request_id": request.request_id,
                "action_id": request.action_id,
            }
        elif mode in {"source_column_derivation", "use_derivation"}:
            override_key = request.target_field
            override_payload = {
                "mode": "source_column_derivation",
                "source_column": payload.get("source_column"),
                "derivation": payload.get("derivation"),
                "source": "input_completion",
                "request_id": request.request_id,
                "action_id": request.action_id,
            }
        elif mode == "uploaded_supporting_file":
            override_key = "geometry_support" if request.reason_code == InputCompletionReasonCode.MISSING_GEOMETRY else (request.target_field or "supporting_file")
            override_payload = {
                "mode": "uploaded_supporting_file",
                "file_ref": payload.get("file_ref"),
                "source": "input_completion",
                "request_id": request.request_id,
                "action_id": request.action_id,
            }
        elif mode == "remediation_policy":
            return self._apply_remediation_policy_decision(state, request, decision, payload)
        else:
            return False, None, None, "Unsupported completion payload mode."

        if not override_key or not isinstance(override_payload, dict):
            return False, None, None, "Completion override could not be materialized."

        if mode == "uploaded_supporting_file":
            file_ref = str(override_payload.get("file_ref") or "").strip()
            if not file_ref:
                return False, None, None, "Supporting-file completion requires an uploaded file in the same turn."
            state.file_context.file_path = file_ref
            state.file_context.has_file = True
            state.file_context.grounded = False

        state.apply_input_completion_override(key=override_key, override=override_payload)
        state.set_latest_input_completion_decision(decision)
        state.set_active_input_completion(None)
        state.control.needs_user_input = False
        state.control.input_completion_prompt = None
        state.control.clarification_question = None
        state.control.parameter_confirmation_prompt = None

        bundle = self._ensure_live_input_completion_bundle()
        bundle["active_request"] = None
        bundle["latest_decision"] = decision.to_dict()
        bundle["overrides"] = state.get_input_completion_overrides_summary()
        bundle["file_path"] = state.file_context.file_path or bundle.get("file_path")

        readiness_summary: Optional[Dict[str, Any]] = None
        if not state.file_context.has_file or state.file_context.grounded:
            assessment = self._build_readiness_assessment(
                state.execution.tool_results,
                state=state,
                frontend_payloads=self._extract_frontend_payloads(state.execution.tool_results),
                trace_obj=None,
                stage_before=None,
                purpose="input_completion_recheck",
            )
            if assessment is not None:
                rechecked = assessment.get_action(request.action_id)
                readiness_summary = {
                    "action_id": request.action_id,
                    "status": rechecked.status.value if rechecked is not None else "unknown",
                    "reason_code": rechecked.reason.reason_code if rechecked and rechecked.reason else None,
                }
        else:
            readiness_summary = {
                "action_id": request.action_id,
                "status": "deferred_until_grounding",
                "reason_code": None,
            }

        return True, self._build_input_completion_resume_decision(state), readiness_summary, None

    def _apply_remediation_policy_decision(
        self,
        state: TaskState,
        request: InputCompletionRequest,
        decision: InputCompletionDecision,
        payload: Dict[str, Any],
    ) -> tuple[bool, Optional[ContinuationDecision], Optional[Dict[str, Any]], Optional[str]]:
        """Apply a remediation policy decision and write field-level overrides."""
        policy_type_str = str(payload.get("policy_type") or "").strip()
        target_fields = list(payload.get("target_fields") or [])
        context_signals = list(payload.get("context_signals") or [])

        if policy_type_str != "apply_default_typical_profile":
            return False, None, None, f"Unsupported remediation policy type: {policy_type_str}"

        # Reconstruct the policy from the option requirements
        selected_option = request.get_option(decision.selected_option_id)
        reqs = selected_option.requirements if selected_option else {}
        if not target_fields:
            target_fields = list(reqs.get("target_fields") or [])
        if not context_signals:
            context_signals = list(reqs.get("context_signals_present") or [])

        policy = RemediationPolicy(
            policy_type=RemediationPolicyType.APPLY_DEFAULT_TYPICAL_PROFILE,
            applicable_task_types=[str(request.current_task_type or "macro_emission")],
            target_fields=target_fields,
            context_signals=sorted({"highway", "lanes", "maxspeed"}),
            context_signals_present=context_signals,
            estimation_basis=str(reqs.get("estimation_basis") or "road attributes"),
            confidence_label="conservative",
        )

        # Apply the policy to get field-level overrides
        application_result = apply_default_typical_profile(
            policy=policy,
            missing_fields=target_fields,
        )

        if not application_result.success:
            return False, None, None, application_result.error or "Remediation policy application failed."

        # Write each field override into the execution-side state
        for field_override in application_result.field_overrides:
            override_payload = {
                "mode": "default_typical_profile",
                "field": field_override.field_name,
                "strategy_description": field_override.strategy_description,
                "lookup_basis": field_override.lookup_basis,
                "policy_type": "apply_default_typical_profile",
                "source": "input_completion",
                "request_id": request.request_id,
                "action_id": request.action_id,
            }
            state.apply_input_completion_override(
                key=field_override.field_name,
                override=override_payload,
            )

        state.set_latest_input_completion_decision(decision)
        state.set_active_input_completion(None)
        state.control.needs_user_input = False
        state.control.input_completion_prompt = None
        state.control.clarification_question = None
        state.control.parameter_confirmation_prompt = None

        bundle = self._ensure_live_input_completion_bundle()
        bundle["active_request"] = None
        bundle["latest_decision"] = decision.to_dict()
        bundle["overrides"] = state.get_input_completion_overrides_summary()
        bundle["file_path"] = state.file_context.file_path or bundle.get("file_path")
        bundle["remediation_policy_applied"] = application_result.to_dict()

        # Readiness recheck
        readiness_summary: Optional[Dict[str, Any]] = None
        if not state.file_context.has_file or state.file_context.grounded:
            assessment = self._build_readiness_assessment(
                state.execution.tool_results,
                state=state,
                frontend_payloads=self._extract_frontend_payloads(state.execution.tool_results),
                trace_obj=None,
                stage_before=None,
                purpose="input_completion_recheck",
            )
            if assessment is not None:
                rechecked = assessment.get_action(request.action_id)
                readiness_summary = {
                    "action_id": request.action_id,
                    "status": rechecked.status.value if rechecked is not None else "unknown",
                    "reason_code": rechecked.reason.reason_code if rechecked and rechecked.reason else None,
                }
        else:
            readiness_summary = {
                "action_id": request.action_id,
                "status": "deferred_until_grounding",
                "reason_code": None,
            }

        return True, self._build_input_completion_resume_decision(state), readiness_summary, None

    async def _handle_active_input_completion(
        self,
        state: TaskState,
        trace_obj: Optional[Trace] = None,
    ) -> Optional[ContinuationDecision]:
        request = self._load_active_input_completion_request()
        if request is None:
            return None

        state.set_active_input_completion(request)
        upload_supported = request.get_first_option_by_type(InputCompletionOptionType.UPLOAD_SUPPORTING_FILE) is not None
        is_new_task, signal, reason = self._is_new_task_request(state)
        if is_new_task and not (
            signal == "new_file_override"
            and upload_supported
            and state.file_context.file_path
        ):
            self._clear_live_input_completion_state(clear_overrides=True)
            state.set_active_input_completion(None)
            state.input_completion_overrides.clear()
            state.set_latest_input_completion_decision(None)
            state.set_supporting_spatial_input(None)
            state.set_geometry_recovery_context(None)
            state.set_geometry_readiness_refresh_result(None)
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.INPUT_COMPLETION_REJECTED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action=request.action_id,
                    input_summary={"request_id": request.request_id, "reason_code": request.reason_code.value},
                    reasoning=reason or "Active input completion was superseded by an explicit new task.",
                )
            return None

        if not self._should_handle_input_completion(state):
            prompt_text = format_input_completion_prompt(
                request,
                retry_message="当前需要先完成这个补救选择。请回复选项序号、具体数值、上传文件，或说“暂停”。",
            )
            state.control.needs_user_input = True
            state.control.input_completion_prompt = prompt_text
            state.control.clarification_question = None
            state.control.parameter_confirmation_prompt = None
            self._transition_state(
                state,
                TaskStage.NEEDS_INPUT_COMPLETION,
                reason="Input completion reply was missing or not actionable",
                trace_obj=trace_obj,
            )
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.INPUT_COMPLETION_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    stage_after=TaskStage.NEEDS_INPUT_COMPLETION.value,
                    action=request.action_id,
                    input_summary={"request_id": request.request_id, "user_reply": state.user_message},
                    reasoning="The reply did not look like a bounded completion decision.",
                )
            return None

        parse_result = self._parse_input_completion_reply(state)
        if parse_result.is_resolved and parse_result.decision is not None:
            decision = parse_result.decision
            state.set_latest_input_completion_decision(decision)

            if decision.decision_type == InputCompletionDecisionType.PAUSE:
                bundle = self._ensure_live_input_completion_bundle()
                bundle["active_request"] = None
                bundle["latest_decision"] = decision.to_dict()
                state.set_active_input_completion(None)
                state.control.needs_user_input = False
                state.control.input_completion_prompt = None
                setattr(
                    state,
                    "_final_response_text",
                    "已暂停当前补救流程。后续如果你准备好了缺失输入，可以继续当前任务或重新上传补充数据。",
                )
                self._transition_state(
                    state,
                    TaskStage.DONE,
                    reason="User paused bounded input completion",
                    trace_obj=trace_obj,
                )
                if trace_obj:
                    trace_obj.record(
                        step_type=TraceStepType.INPUT_COMPLETION_PAUSED,
                        stage_before=TaskStage.INPUT_RECEIVED.value,
                        stage_after=TaskStage.DONE.value,
                        action=request.action_id,
                        input_summary={"request_id": request.request_id},
                        reasoning=f"User paused the active input completion with reply '{decision.user_reply}'.",
                    )
                return None

            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.INPUT_COMPLETION_CONFIRMED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action=request.action_id,
                    input_summary={
                        "request_id": request.request_id,
                        "selected_option_id": decision.selected_option_id,
                        "source": decision.source,
                    },
                    output_summary={"structured_payload": dict(decision.structured_payload or {})},
                    reasoning=f"Parsed bounded completion reply '{decision.user_reply}'.",
                )
                # Emit REMEDIATION_POLICY_CONFIRMED if this is a policy decision
                if str(dict(decision.structured_payload or {}).get("mode") or "") == "remediation_policy":
                    trace_obj.record(
                        step_type=TraceStepType.REMEDIATION_POLICY_CONFIRMED,
                        stage_before=TaskStage.INPUT_RECEIVED.value,
                        action=request.action_id,
                        input_summary={
                            "policy_type": dict(decision.structured_payload or {}).get("policy_type"),
                            "target_fields": dict(decision.structured_payload or {}).get("target_fields"),
                            "user_reply": decision.user_reply,
                        },
                        reasoning=(
                            f"User confirmed remediation policy "
                            f"'{dict(decision.structured_payload or {}).get('policy_type')}' "
                            f"via reply '{decision.user_reply}'."
                        ),
                    )

            selected_option = request.get_option(decision.selected_option_id)
            if (
                request.reason_code == InputCompletionReasonCode.MISSING_GEOMETRY
                and selected_option is not None
                and selected_option.option_type == InputCompletionOptionType.UPLOAD_SUPPORTING_FILE
            ):
                handled = await self._handle_geometry_completion_upload(
                    state,
                    request,
                    decision,
                    trace_obj=trace_obj,
                )
                if handled:
                    return None

            applied, resume_decision, readiness_summary, error_message = self._apply_input_completion_decision(
                state,
                request,
                decision,
            )
            if not applied:
                prompt_text = format_input_completion_prompt(
                    request,
                    retry_message=error_message or "The completion decision could not be applied.",
                )
                state.control.needs_user_input = True
                state.control.input_completion_prompt = prompt_text
                self._transition_state(
                    state,
                    TaskStage.NEEDS_INPUT_COMPLETION,
                    reason="Input completion decision could not be applied",
                    trace_obj=trace_obj,
                )
                if trace_obj:
                    trace_obj.record(
                        step_type=TraceStepType.INPUT_COMPLETION_FAILED,
                        stage_before=TaskStage.INPUT_RECEIVED.value,
                        stage_after=TaskStage.NEEDS_INPUT_COMPLETION.value,
                        action=request.action_id,
                        input_summary={"request_id": request.request_id, "user_reply": decision.user_reply},
                        reasoning=error_message or "Input completion decision could not be applied.",
                    )
                    # If this was a policy decision that failed, also emit REMEDIATION_POLICY_FAILED
                    if str(dict(decision.structured_payload or {}).get("mode") or "") == "remediation_policy":
                        trace_obj.record(
                            step_type=TraceStepType.REMEDIATION_POLICY_FAILED,
                            stage_before=TaskStage.INPUT_RECEIVED.value,
                            stage_after=TaskStage.NEEDS_INPUT_COMPLETION.value,
                            action=request.action_id,
                            input_summary={
                                "policy_type": dict(decision.structured_payload or {}).get("policy_type"),
                            },
                            error=error_message or "Remediation policy application failed.",
                            reasoning=error_message or "Remediation policy could not be applied.",
                        )
                return None

            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.INPUT_COMPLETION_APPLIED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action=request.action_id,
                    input_summary={"request_id": request.request_id},
                    output_summary={
                        "overrides": state.get_input_completion_overrides_summary(),
                        "readiness_recheck": readiness_summary,
                    },
                    reasoning="Applied bounded input-completion override and resumed the current task context.",
                )
                # Emit REMEDIATION_POLICY_APPLIED if a policy was applied
                bundle = self._ensure_live_input_completion_bundle()
                policy_result = bundle.get("remediation_policy_applied")
                if isinstance(policy_result, dict) and policy_result.get("success"):
                    trace_obj.record(
                        step_type=TraceStepType.REMEDIATION_POLICY_APPLIED,
                        stage_before=TaskStage.INPUT_RECEIVED.value,
                        action=request.action_id,
                        input_summary={
                            "policy_type": policy_result.get("policy_type"),
                        },
                        output_summary={
                            "field_overrides": policy_result.get("field_overrides"),
                            "summary": policy_result.get("summary"),
                        },
                        reasoning=(
                            f"Remediation policy applied: {policy_result.get('summary', 'N/A')}"
                        ),
                    )
            return resume_decision

        prompt_text = format_input_completion_prompt(
            request,
            retry_message=parse_result.error_message,
        )
        state.control.needs_user_input = True
        state.control.input_completion_prompt = prompt_text
        state.control.clarification_question = None
        state.control.parameter_confirmation_prompt = None
        self._transition_state(
            state,
            TaskStage.NEEDS_INPUT_COMPLETION,
            reason="Input completion reply was ambiguous",
            trace_obj=trace_obj,
        )
        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.INPUT_COMPLETION_FAILED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                stage_after=TaskStage.NEEDS_INPUT_COMPLETION.value,
                action=request.action_id,
                input_summary={"request_id": request.request_id, "user_reply": state.user_message},
                reasoning=parse_result.error_message or "Input completion reply could not be parsed.",
            )
        return None

    def _sync_live_continuation_state(self, state: TaskState) -> None:
        bundle = self._ensure_live_continuation_bundle()
        if state.plan is None or state.plan.status == PlanStatus.INVALID or not state.plan.has_pending_steps():
            bundle.update(
                {
                    "plan": None,
                    "repair_history": [],
                    "blocked_info": None,
                    "file_path": None,
                    "latest_repair_summary": None,
                    "residual_plan_summary": None,
                }
            )
            return

        latest_repair_summary = state.get_latest_repair_summary()
        blocked_info = dict(state.execution.blocked_info) if isinstance(state.execution.blocked_info, dict) else None
        bundle.update(
            {
                "plan": state.plan.to_dict(),
                "repair_history": [decision.to_dict() for decision in state.repair_history],
                "blocked_info": blocked_info,
                "file_path": state.file_context.file_path,
                "latest_repair_summary": latest_repair_summary,
                "residual_plan_summary": self._build_residual_plan_summary_for_prompt(
                    state.plan,
                    available_tokens=self._collect_available_result_tokens(state, include_stale=False),
                    latest_repair_summary=latest_repair_summary,
                    blocked_info=blocked_info,
                ),
            }
        )

    @staticmethod
    def _first_matching_phrase(message: str, phrases: tuple[str, ...]) -> Optional[str]:
        lowered = message.lower()
        for phrase in phrases:
            if phrase in lowered:
                return phrase
        return None

    @staticmethod
    def _extract_ascii_keywords(text: Optional[str]) -> List[str]:
        if not text:
            return []
        return [item for item in re.findall(r"[a-z]{4,}", text.lower()) if item]

    def _residual_message_matches_plan(
        self,
        message: str,
        plan: ExecutionPlan,
        blocked_info: Optional[Dict[str, Any]] = None,
    ) -> bool:
        lowered = message.lower()
        terms: List[str] = []

        next_step = plan.get_next_pending_step()
        if next_step is not None:
            terms.extend(CONTINUATION_TOOL_KEYWORDS.get(next_step.tool_name, []))
            terms.extend(next_step.depends_on)
            terms.extend(next_step.produces)
            if next_step.purpose:
                terms.extend(self._extract_ascii_keywords(next_step.purpose))

        for step in plan.get_pending_steps()[:3]:
            terms.extend(CONTINUATION_TOOL_KEYWORDS.get(step.tool_name, []))
            terms.extend(step.depends_on)
            terms.extend(step.produces)

        terms.extend(self._extract_ascii_keywords(plan.goal))
        terms.extend(self._extract_ascii_keywords(plan.planner_notes))

        if blocked_info:
            terms.extend(blocked_info.get("missing_tokens", []))
            terms.extend(blocked_info.get("stale_tokens", []))
            blocked_tool = blocked_info.get("tool_name")
            if blocked_tool:
                terms.extend(CONTINUATION_TOOL_KEYWORDS.get(str(blocked_tool), []))

        for term in normalize_tokens(terms):
            if term and len(term) >= 2 and term in lowered:
                return True

        for term in terms:
            text = str(term).strip().lower()
            if text and len(text) >= 2 and text in lowered:
                return True
        return False

    def _is_new_task_request(
        self,
        state: TaskState,
        previous_file_path: Optional[str] = None,
    ) -> tuple[bool, Optional[str], Optional[str]]:
        message = (state.user_message or "").strip().lower()
        new_task_cues = (
            "换个文件",
            "重新分析",
            "重新来",
            "重来",
            "换个任务",
            "另一个任务",
            "另外一个任务",
            "直接回答这个新问题",
            "直接回答",
            "不要管前面的",
            "不管前面的",
            "重新算",
            "start over",
            "new task",
            "another task",
            "ignore previous",
            "don't use previous",
        )
        matched = self._first_matching_phrase(message, new_task_cues)
        if matched:
            return True, "explicit_new_task", f"explicit new-task cue '{matched}' detected"

        current_file_path = str(state.file_context.file_path) if state.file_context.file_path else None
        if current_file_path and previous_file_path and current_file_path != previous_file_path:
            return True, "new_file_override", "uploaded file changed relative to the residual workflow"

        return False, None, None

    def _build_residual_plan_summary_for_prompt(
        self,
        plan: ExecutionPlan,
        *,
        available_tokens: Optional[List[str]] = None,
        latest_repair_summary: Optional[str] = None,
        blocked_info: Optional[Dict[str, Any]] = None,
        variant: Optional[str] = None,
    ) -> str:
        prompt_variant = self._resolve_continuation_prompt_variant(variant)
        next_step = plan.get_next_pending_step()
        pending_steps = plan.get_pending_steps()
        ready_step = next(
            (step for step in pending_steps if step.status == PlanStepStatus.READY),
            None,
        )

        step_lines: List[str] = []
        for step in pending_steps[:4]:
            step_line = f"- {step.step_id}: {step.tool_name} [{step.status.value}]"
            if step.depends_on:
                step_line += f" | depends_on={', '.join(step.depends_on)}"
            if step.produces:
                step_line += f" | produces={', '.join(step.produces)}"
            if step.argument_hints:
                step_line += (
                    " | argument_hints="
                    + json.dumps(step.argument_hints, ensure_ascii=False, sort_keys=True)
                )
            if step.blocked_reason:
                step_line += f" | blocked_reason={step.blocked_reason}"
            step_lines.append(step_line)

        lines = [f"[Residual workflow continuation | variant={prompt_variant}]"]

        if prompt_variant == "goal_heavy":
            lines.append(f"Original goal: {plan.goal}")
            lines.append(f"Residual workflow status: {plan.status.value}")
            if latest_repair_summary:
                lines.append(f"Repair-aware context: {latest_repair_summary}")
            if blocked_info and blocked_info.get("message"):
                lines.append(f"Blocked context: {blocked_info['message']}")
            if available_tokens:
                lines.append(f"Available result tokens: {', '.join(available_tokens)}")
            if next_step is not None:
                hint_line = f"Residual next-step hint: {next_step.step_id} -> {next_step.tool_name} [{next_step.status.value}]"
                if next_step.blocked_reason:
                    hint_line += f" | blocked_reason={next_step.blocked_reason}"
                lines.append(hint_line)
            lines.append("Residual workflow summary:")
            lines.extend(step_lines)
            lines.append(
                "Continuation policy: preserve the original workflow goal when the conversation is still on-task. "
                "Do not auto-execute steps and do not auto-complete dependencies."
            )
            return "\n".join(lines)

        if prompt_variant == "next_step_heavy":
            lines.append(f"Original goal: {plan.goal}")
            lines.append(f"Residual workflow status: {plan.status.value}")
            if next_step is not None:
                next_line = (
                    f"Immediate next pending step (highest priority): {next_step.step_id} -> "
                    f"{next_step.tool_name} [{next_step.status.value}]"
                )
                if next_step.blocked_reason:
                    next_line += f" | blocked_reason={next_step.blocked_reason}"
                lines.append(next_line)
            if ready_step is not None and (next_step is None or ready_step.step_id != next_step.step_id):
                lines.append(f"First ready residual step: {ready_step.step_id} -> {ready_step.tool_name}")
            if blocked_info and blocked_info.get("message"):
                lines.append(f"Latest blocked reason: {blocked_info['message']}")
            if latest_repair_summary:
                lines.append(f"Latest repair summary: {latest_repair_summary}")
            if available_tokens:
                lines.append(f"Available result tokens: {', '.join(available_tokens)}")
            lines.append("Near-term residual steps:")
            lines.extend(step_lines)
            lines.append(
                "Tool-selection rule: if the user is continuing the same workflow, prefer the immediate next legal residual step "
                "before later residual steps. Do not auto-execute steps and do not auto-complete dependencies."
            )
            return "\n".join(lines)

        lines.append(f"Original goal: {plan.goal}")
        lines.append(f"Residual plan status: {plan.status.value}")
        if available_tokens:
            lines.append(f"Available result tokens: {', '.join(available_tokens)}")
        if latest_repair_summary:
            lines.append(f"Latest repair summary: {latest_repair_summary}")
        if blocked_info and blocked_info.get("message"):
            lines.append(f"Latest blocked reason: {blocked_info['message']}")
        if next_step is not None:
            next_line = f"Next pending step: {next_step.step_id} -> {next_step.tool_name} [{next_step.status.value}]"
            if next_step.blocked_reason:
                next_line += f" | blocked_reason={next_step.blocked_reason}"
            lines.append(next_line)
        if ready_step is not None and (next_step is None or ready_step.step_id != next_step.step_id):
            lines.append(f"First ready residual step: {ready_step.step_id} -> {ready_step.tool_name}")
        lines.append("Residual workflow summary:")
        lines.extend(step_lines)
        lines.append(
            "Continuation policy: treat this turn as a bounded continuation of the residual workflow unless the user clearly starts a new task. "
            "Prefer the next ready residual step when appropriate. Do not auto-execute steps and do not auto-complete dependencies."
        )
        return "\n".join(lines)

    def _resolve_continuation_prompt_variant(self, variant: Optional[str] = None) -> str:
        candidate = str(
            variant
            or getattr(self.runtime_config, "continuation_prompt_variant", "balanced_repair_aware")
            or "balanced_repair_aware"
        ).strip().lower()
        if candidate not in CONTINUATION_PROMPT_VARIANTS:
            return "balanced_repair_aware"
        return candidate

    def _should_replan_on_continuation(
        self,
        state: TaskState,
        decision: ContinuationDecision,
    ) -> tuple[bool, str]:
        if not decision.should_continue:
            return False, "continuation not active"
        if state.plan is None:
            return False, "no residual plan hydrated into state"
        if state.plan.status == PlanStatus.INVALID:
            return True, "residual plan became invalid and requires controlled replanning"
        return False, "residual plan remains actionable; skipping full replan"

    def _should_continue_residual_plan(self, state: TaskState) -> ContinuationDecision:
        decision = ContinuationDecision(
            residual_plan_exists=False,
            continuation_ready=False,
            should_continue=False,
            prompt_variant=self._resolve_continuation_prompt_variant(),
            reason="no live residual workflow available",
            signal="no_residual_plan",
        )

        if not getattr(self.runtime_config, "enable_repair_aware_continuation", False):
            decision.reason = "repair-aware continuation feature flag disabled"
            decision.signal = "feature_disabled"
            return decision

        plan, repair_history, blocked_info, previous_file_path = self._load_live_residual_plan()
        if plan is None:
            return decision

        decision.residual_plan_exists = True
        decision.latest_repair_summary = (
            self._ensure_live_continuation_bundle().get("latest_repair_summary")
            or (
                f"{repair_history[-1].action_type.value}: {repair_history[-1].planner_notes}"
                if repair_history and repair_history[-1].planner_notes
                else (repair_history[-1].action_type.value if repair_history else None)
            )
        )
        decision.latest_blocked_reason = blocked_info.get("message") if blocked_info else None
        decision.residual_plan_summary = (
            self._ensure_live_continuation_bundle().get("residual_plan_summary")
            or self._build_residual_plan_summary_for_prompt(
                plan,
                available_tokens=self._collect_available_result_tokens(state, include_stale=False),
                latest_repair_summary=decision.latest_repair_summary,
                blocked_info=blocked_info,
                variant=decision.prompt_variant,
            )
        )

        next_step = plan.get_next_pending_step()
        if next_step is None:
            decision.reason = "residual plan has no pending steps"
            decision.signal = "no_pending_residual"
            return decision

        decision.continuation_ready = True
        decision.next_step_id = next_step.step_id
        decision.next_tool_name = next_step.tool_name

        is_new_task, signal, reason = self._is_new_task_request(state, previous_file_path=previous_file_path)
        if is_new_task:
            decision.signal = signal
            decision.reason = reason
            decision.new_task_override = True
            return decision

        message = (state.user_message or "").strip().lower()
        continuation_cues = (
            "继续",
            "接着做",
            "接着",
            "下一步",
            "按修复后的计划继续",
            "剩下的步骤",
            "continue",
            "keep going",
            "next step",
            "follow the repaired plan",
        )
        matched_cue = self._first_matching_phrase(message, continuation_cues)
        if matched_cue:
            decision.should_continue = True
            decision.signal = "explicit_continuation"
            decision.reason = f"explicit continuation cue '{matched_cue}' matched the residual workflow"
            return decision

        if self._residual_message_matches_plan(message, plan, blocked_info=blocked_info):
            decision.should_continue = True
            decision.signal = "residual_related_heuristic"
            decision.reason = "user input remained semantically aligned with the residual workflow"
            return decision

        decision.signal = "ambiguous_no_safe_continuation"
        decision.reason = "residual plan existed, but the new user input did not safely align with it"
        return decision

    def _should_continue_geometry_recovery(
        self,
        state: TaskState,
    ) -> Optional[ContinuationDecision]:
        if not getattr(self.runtime_config, "enable_geometry_recovery_path", True):
            return None

        geometry_context = state.geometry_recovery_context
        if geometry_context is None:
            return None
        if geometry_context.recovery_status != GeometryRecoveryStatus.RESUMABLE.value:
            return None

        reentry_context = (
            state.residual_reentry_context
            if getattr(self.runtime_config, "enable_residual_reentry_controller", True)
            else None
        )

        plan, repair_history, blocked_info, previous_file_path = self._load_live_residual_plan()
        next_step = plan.get_next_pending_step() if plan is not None else None
        if plan is None and reentry_context is None:
            return None
        if plan is not None and next_step is None and reentry_context is None:
            return None

        decision = ContinuationDecision(
            residual_plan_exists=plan is not None,
            continuation_ready=True,
            should_continue=False,
            should_replan=False,
            prompt_variant=self._resolve_continuation_prompt_variant(),
            signal="geometry_recovery_waiting",
            reason="geometry recovery remained active, but the new turn did not safely resume the residual workflow",
            next_step_id=(
                next_step.step_id
                if next_step is not None
                else (
                    reentry_context.reentry_target.target_step_id
                    if reentry_context is not None
                    else None
                )
            ),
            next_tool_name=(
                next_step.tool_name
                if next_step is not None
                else (
                    reentry_context.reentry_target.target_tool_name
                    if reentry_context is not None
                    else None
                )
            ),
            latest_repair_summary=(
                self._ensure_live_continuation_bundle().get("latest_repair_summary")
                or (
                    f"{repair_history[-1].action_type.value}: {repair_history[-1].planner_notes}"
                    if repair_history and repair_history[-1].planner_notes
                    else (repair_history[-1].action_type.value if repair_history else None)
                )
            ),
            residual_plan_summary=(
                self._ensure_live_continuation_bundle().get("residual_plan_summary")
                or (
                    self._build_residual_plan_summary_for_prompt(
                        plan,
                        available_tokens=self._collect_available_result_tokens(state, include_stale=False),
                        latest_repair_summary=self._ensure_live_continuation_bundle().get("latest_repair_summary"),
                        blocked_info=blocked_info,
                    )
                    if plan is not None
                    else None
                )
                or (
                    reentry_context.residual_plan_summary
                    if reentry_context is not None
                    else None
                )
            ),
            latest_blocked_reason=blocked_info.get("message") if blocked_info else None,
        )

        is_new_task, signal, reason = self._is_new_task_request(state, previous_file_path=previous_file_path)
        if is_new_task:
            decision.signal = signal
            decision.reason = reason
            decision.new_task_override = True
            return decision

        message = (state.user_message or "").strip().lower()
        continuation_cues = (
            "继续",
            "接着做",
            "接着",
            "下一步",
            "继续当前任务",
            "continue",
            "keep going",
            "next step",
        )
        matched_cue = self._first_matching_phrase(message, continuation_cues)
        if matched_cue:
            decision.should_continue = True
            decision.signal = "geometry_recovery_resume"
            decision.reason = (
                f"geometry recovery kept the residual workflow authoritative and the user explicitly resumed it with '{matched_cue}'"
            )
            return decision

        if plan is not None and self._residual_message_matches_plan(message, plan, blocked_info=blocked_info):
            decision.should_continue = True
            decision.signal = "geometry_recovery_resume"
            decision.reason = "geometry recovery restored the residual workflow and the new user input remained aligned with it"
            return decision

        if reentry_context is not None and self._message_matches_reentry_target(message, reentry_context):
            decision.should_continue = True
            decision.signal = "geometry_recovery_resume"
            decision.reason = "geometry recovery restored a formal re-entry target and the new user input aligned with that recovered action"
            return decision

        return decision

    def _activate_live_continuation_state(self, state: TaskState, decision: ContinuationDecision) -> None:
        plan, repair_history, _blocked_info, _previous_file_path = self._load_live_residual_plan()
        if plan is None:
            return
        state.set_plan(plan)
        state.repair_history = repair_history
        self._refresh_execution_plan_state(state)
        if not decision.latest_repair_summary:
            decision.latest_repair_summary = state.get_latest_repair_summary()
        decision.residual_plan_summary = self._build_residual_plan_summary_for_prompt(
            state.plan,
            available_tokens=self._collect_available_result_tokens(state, include_stale=False),
            latest_repair_summary=decision.latest_repair_summary,
            blocked_info=self._ensure_live_continuation_bundle().get("blocked_info"),
            variant=decision.prompt_variant,
        )

    def _record_continuation_decision(
        self,
        state: TaskState,
        decision: ContinuationDecision,
        trace_obj: Optional[Trace] = None,
    ) -> None:
        state.set_continuation_decision(decision)
        if trace_obj is None or not decision.residual_plan_exists:
            return

        summary = {
            "residual_plan_exists": decision.residual_plan_exists,
            "continuation_ready": decision.continuation_ready,
            "next_step_id": decision.next_step_id,
            "next_tool_name": decision.next_tool_name,
            "prompt_variant": decision.prompt_variant,
            "signal": decision.signal,
            "latest_repair_summary": decision.latest_repair_summary,
            "latest_blocked_reason": decision.latest_blocked_reason,
        }
        trace_obj.record(
            step_type=(
                TraceStepType.PLAN_CONTINUATION_DECIDED
                if decision.should_continue
                else TraceStepType.PLAN_CONTINUATION_SKIPPED
            ),
            stage_before=TaskStage.INPUT_RECEIVED.value,
            action=decision.next_tool_name,
            input_summary=summary,
            reasoning=decision.reason or "continuation decision evaluated",
        )

    def _activate_parameter_confirmation_state(
        self,
        state: TaskState,
        request: ParameterNegotiationRequest,
        *,
        prompt_text: Optional[str] = None,
        trace_obj: Optional[Trace] = None,
        record_required: bool = True,
    ) -> None:
        state.set_active_parameter_negotiation(request)
        state.control.needs_user_input = True
        state.control.parameter_confirmation_prompt = (
            prompt_text or format_parameter_negotiation_prompt(request)
        )
        state.control.clarification_question = None
        self._save_active_parameter_negotiation_bundle(state, request)
        self._transition_state(
            state,
            TaskStage.NEEDS_PARAMETER_CONFIRMATION,
            reason="Parameter confirmation required",
            trace_obj=trace_obj,
        )
        if trace_obj and record_required:
            trace_obj.record(
                step_type=TraceStepType.PARAMETER_NEGOTIATION_REQUIRED,
                stage_before=TaskStage.EXECUTING.value,
                stage_after=TaskStage.NEEDS_PARAMETER_CONFIRMATION.value,
                action=request.tool_name,
                input_summary={
                    "parameter_name": request.parameter_name,
                    "raw_value": request.raw_value,
                    "strategy": request.strategy,
                    "confidence": request.confidence,
                },
                output_summary={
                    "request_id": request.request_id,
                    "candidates": [candidate.to_dict() for candidate in request.candidates],
                },
                reasoning=request.trigger_reason,
            )

    def _should_handle_parameter_confirmation(self, state: TaskState) -> bool:
        request = state.active_parameter_negotiation or self._load_active_parameter_negotiation_request()
        if request is None or not getattr(self.runtime_config, "enable_parameter_negotiation", False):
            return False
        return reply_looks_like_confirmation_attempt(request, state.user_message or "")

    def _parse_parameter_confirmation_reply(
        self,
        state: TaskState,
    ) -> ParameterNegotiationParseResult:
        request = state.active_parameter_negotiation or self._load_active_parameter_negotiation_request()
        if request is None:
            return ParameterNegotiationParseResult(
                is_resolved=False,
                needs_retry=False,
                error_message="No active parameter negotiation request.",
            )
        return parse_parameter_negotiation_reply(request, state.user_message or "")

    def _build_parameter_confirmation_resume_decision(
        self,
        state: TaskState,
    ) -> Optional[ContinuationDecision]:
        bundle = self._ensure_live_parameter_negotiation_bundle()
        plan_snapshot = bundle.get("plan")
        if not isinstance(plan_snapshot, dict):
            return None

        plan = ExecutionPlan.from_dict(plan_snapshot)
        if not plan.has_pending_steps():
            return None

        repair_history = [
            PlanRepairDecision.from_dict(item)
            for item in (bundle.get("repair_history") or [])
            if isinstance(item, dict)
        ]
        state.set_plan(plan)
        state.repair_history = repair_history
        if not state.file_context.file_path and bundle.get("file_path"):
            state.file_context.file_path = str(bundle["file_path"])
            state.file_context.has_file = True
        self._refresh_execution_plan_state(state)

        next_step = state.get_next_planned_step()
        decision = ContinuationDecision(
            residual_plan_exists=True,
            continuation_ready=True,
            should_continue=True,
            should_replan=False,
            prompt_variant=self._resolve_continuation_prompt_variant(),
            signal="parameter_confirmation_resume",
            reason="parameter confirmation resolved an active negotiation and resumed the residual workflow",
            next_step_id=next_step.step_id if next_step is not None else None,
            next_tool_name=next_step.tool_name if next_step is not None else None,
            latest_repair_summary=str(bundle.get("latest_repair_summary") or "").strip() or None,
            residual_plan_summary=str(bundle.get("residual_plan_summary") or "").strip() or None,
            latest_blocked_reason=(
                str((bundle.get("blocked_info") or {}).get("message")).strip()
                if isinstance(bundle.get("blocked_info"), dict) and (bundle.get("blocked_info") or {}).get("message")
                else None
            ),
        )

        self._ensure_live_continuation_bundle().update(
            {
                "plan": plan.to_dict(),
                "repair_history": [decision_item.to_dict() for decision_item in repair_history],
                "blocked_info": bundle.get("blocked_info"),
                "file_path": bundle.get("file_path"),
                "latest_repair_summary": bundle.get("latest_repair_summary"),
                "residual_plan_summary": bundle.get("residual_plan_summary"),
            }
        )
        return decision

    def _inject_parameter_confirmation_guidance(
        self,
        context: Any,
        state: TaskState,
    ) -> None:
        locked_parameters = state.get_parameter_locks_summary()
        if not locked_parameters:
            return

        latest_decision = state.latest_parameter_negotiation_decision
        lines = ["[Confirmed parameter locks]"]
        if latest_decision and latest_decision.decision_type == NegotiationDecisionType.CONFIRMED:
            lines.append(
                "The current turn resolved a bounded parameter negotiation. "
                "Treat the confirmed value as binding for later execution."
            )
        for name, payload in locked_parameters.items():
            lines.append(
                f"- {name} = {payload.get('normalized')} "
                f"(lock_source={payload.get('lock_source') or 'unknown'})"
            )
        lines.append(
            "Use the locked canonical values exactly. Do not reinterpret or fuzzy-guess them again."
        )

        guidance_message = {"role": "system", "content": "\n".join(lines)}
        insert_at = len(context.messages)
        if context.messages and context.messages[-1].get("role") == "user":
            insert_at -= 1
        context.messages.insert(insert_at, guidance_message)

    def _handle_active_parameter_confirmation(
        self,
        state: TaskState,
        trace_obj: Optional[Trace] = None,
    ) -> Optional[ContinuationDecision]:
        request = self._load_active_parameter_negotiation_request()
        if request is None:
            return None

        state.set_active_parameter_negotiation(request)
        message = (state.user_message or "").strip()
        is_new_task, _signal, _reason = self._is_new_task_request(state)
        if is_new_task:
            self._clear_live_parameter_negotiation_state(clear_locks=True)
            state.set_active_parameter_negotiation(None)
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.PARAMETER_NEGOTIATION_REJECTED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    reasoning="Active parameter negotiation was superseded because the user explicitly started a new task.",
                    input_summary={"request_id": request.request_id, "parameter_name": request.parameter_name},
                )
            return None

        if not self._should_handle_parameter_confirmation(state):
            return None

        parse_result = self._parse_parameter_confirmation_reply(state)
        if parse_result.is_resolved and parse_result.decision is not None:
            decision = parse_result.decision
            state.set_latest_parameter_negotiation_decision(decision)
            if decision.decision_type == NegotiationDecisionType.CONFIRMED and decision.selected_value:
                locked_entry = state.apply_parameter_lock(
                    parameter_name=request.parameter_name,
                    normalized_value=decision.selected_value,
                    raw_value=request.raw_value,
                    request_id=request.request_id,
                )
                bundle = self._ensure_live_parameter_negotiation_bundle()
                locked_parameters = dict(bundle.get("locked_parameters") or {})
                locked_parameters[request.parameter_name] = locked_entry.to_dict()
                bundle["locked_parameters"] = locked_parameters
                bundle["latest_confirmed_parameter"] = decision.to_dict()
                bundle["active_request"] = None
                state.set_active_parameter_negotiation(None)
                state.control.needs_user_input = False
                state.control.parameter_confirmation_prompt = None
                if trace_obj:
                    trace_obj.record(
                        step_type=TraceStepType.PARAMETER_NEGOTIATION_CONFIRMED,
                        stage_before=TaskStage.INPUT_RECEIVED.value,
                        action=request.tool_name,
                        input_summary={
                            "request_id": request.request_id,
                            "parameter_name": request.parameter_name,
                            "selected_index": decision.selected_index,
                        },
                        output_summary={
                            "selected_value": decision.selected_value,
                            "lock_applied": True,
                        },
                        reasoning=(
                            f"Confirmed {request.parameter_name}={decision.selected_value} "
                            f"from reply '{decision.user_reply}'."
                        ),
                    )
                return self._build_parameter_confirmation_resume_decision(state)

            self._clear_live_parameter_negotiation_state(clear_locks=False)
            state.set_active_parameter_negotiation(None)
            state.control.needs_user_input = True
            state.control.parameter_confirmation_prompt = None
            state.control.clarification_question = self._build_parameter_confirmation_clarification(request)
            self._transition_state(
                state,
                TaskStage.NEEDS_CLARIFICATION,
                reason="User rejected all parameter candidates",
                trace_obj=trace_obj,
            )
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.PARAMETER_NEGOTIATION_REJECTED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    stage_after=TaskStage.NEEDS_CLARIFICATION.value,
                    action=request.tool_name,
                    input_summary={"request_id": request.request_id, "parameter_name": request.parameter_name},
                    reasoning=(
                        f"User rejected all candidates for {request.parameter_name} "
                        f"with reply '{decision.user_reply}'."
                    ),
                )
            return None

        state.control.needs_user_input = True
        prompt_text = format_parameter_negotiation_prompt(
            request,
            retry_message=parse_result.error_message,
        )
        state.control.parameter_confirmation_prompt = prompt_text
        self._transition_state(
            state,
            TaskStage.NEEDS_PARAMETER_CONFIRMATION,
            reason="Parameter confirmation reply was ambiguous",
            trace_obj=trace_obj,
        )
        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.PARAMETER_NEGOTIATION_FAILED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                stage_after=TaskStage.NEEDS_PARAMETER_CONFIRMATION.value,
                action=request.tool_name,
                input_summary={
                    "request_id": request.request_id,
                    "parameter_name": request.parameter_name,
                    "user_reply": state.user_message,
                },
                reasoning=parse_result.error_message or "Parameter confirmation reply could not be parsed.",
            )
        return None

    def _inject_continuation_guidance(
        self,
        context: Any,
        state: TaskState,
        decision: ContinuationDecision,
        trace_obj: Optional[Trace] = None,
    ) -> None:
        if not decision.should_continue:
            return

        guidance_text = decision.residual_plan_summary
        if not guidance_text and state.plan is not None:
            guidance_text = self._build_residual_plan_summary_for_prompt(
                state.plan,
                available_tokens=self._collect_available_result_tokens(state, include_stale=False),
                latest_repair_summary=decision.latest_repair_summary,
                blocked_info=self._ensure_live_continuation_bundle().get("blocked_info"),
                variant=decision.prompt_variant,
            )
        if not guidance_text:
            return
        guidance_message = {"role": "system", "content": guidance_text}
        insert_at = len(context.messages)
        if context.messages and context.messages[-1].get("role") == "user":
            insert_at -= 1
        context.messages.insert(insert_at, guidance_message)

        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.PLAN_CONTINUATION_INJECTED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action=decision.next_tool_name,
                input_summary={
                    "next_step_id": decision.next_step_id,
                    "next_tool_name": decision.next_tool_name,
                    "should_replan": decision.should_replan,
                    "prompt_variant": decision.prompt_variant,
                },
                output_summary={
                    "guidance_preview": guidance_text[:400],
                },
                reasoning=(
                    f"Injected residual continuation guidance for {decision.next_step_id} -> {decision.next_tool_name}. "
                    f"variant={decision.prompt_variant}; should_replan={decision.should_replan}."
                ),
            )

    def _refresh_execution_plan_state(self, state: TaskState) -> None:
        """Refresh execution-time step readiness from actual currently available results."""
        if state.plan is None:
            return

        available = set(self._collect_available_result_tokens(state, include_stale=False))
        context_store = self._ensure_context_store()
        for step in state.plan.steps:
            if step.status == PlanStepStatus.COMPLETED:
                available.update(step.produces or get_tool_provides(step.tool_name))
                step.blocked_reason = None
                continue
            if step.status in {PlanStepStatus.FAILED, PlanStepStatus.SKIPPED}:
                continue
            if step.status == PlanStepStatus.IN_PROGRESS:
                step.blocked_reason = None
                continue

            validation = validate_tool_prerequisites(
                step.tool_name,
                arguments=step.argument_hints,
                available_tokens=available,
                context_store=context_store,
                include_stale=False,
            )
            if validation.is_valid:
                step.status = PlanStepStatus.READY
                step.blocked_reason = None
            else:
                step.status = PlanStepStatus.BLOCKED
                step.blocked_reason = validation.message
                if validation.message not in step.validation_notes:
                    step.validation_notes.append(validation.message)

        self._update_plan_status_from_steps(state)

    def _update_plan_status_from_steps(self, state: TaskState) -> None:
        if state.plan is None:
            return
        if state.plan.status == PlanStatus.INVALID:
            return

        statuses = [step.status for step in state.plan.steps]
        if statuses and all(status in {PlanStepStatus.COMPLETED, PlanStepStatus.SKIPPED} for status in statuses):
            state.plan.status = PlanStatus.VALID
            return
        if any(status in {PlanStepStatus.BLOCKED, PlanStepStatus.FAILED} for status in statuses):
            state.plan.status = PlanStatus.PARTIAL
            return
        state.plan.status = PlanStatus.VALID

    def _validate_residual_plan_legality(self, state: TaskState) -> Optional[Dict[str, Any]]:
        if state.plan is None:
            return None

        available = set(self._collect_available_result_tokens(state, include_stale=False))
        residual_steps: List[PlanStep] = []
        for step in state.plan.steps:
            if step.status == PlanStepStatus.COMPLETED:
                available.update(step.produces or get_tool_provides(step.tool_name))
                continue
            if step.status in {PlanStepStatus.SKIPPED, PlanStepStatus.FAILED}:
                continue
            residual_steps.append(PlanStep.from_dict(step.to_dict()))

        if not residual_steps:
            return {
                "status": PlanStatus.VALID,
                "validation_notes": ["Residual plan has no executable steps."],
                "step_results": [],
                "initial_available_tokens": sorted(available),
                "final_available_tokens": sorted(available),
            }
        return validate_plan_steps(residual_steps, available_tokens=available)

    def _find_planned_step_for_tool(
        self,
        state: TaskState,
        tool_name: str,
    ) -> Optional[Any]:
        if state.plan is None:
            return None
        return state.plan.get_step(
            tool_name=tool_name,
            allowed_statuses={
                PlanStepStatus.PENDING,
                PlanStepStatus.READY,
                PlanStepStatus.BLOCKED,
                PlanStepStatus.IN_PROGRESS,
            },
        )

    def _reconcile_plan_before_execution(
        self,
        state: TaskState,
        tool_name: str,
        trace_obj: Optional[Trace] = None,
    ) -> Dict[str, Any]:
        """Reconcile the next actual tool execution against the current plan state."""
        result: Dict[str, Any] = {
            "planned_step": None,
            "next_step": None,
            "matched": False,
            "deviation_type": None,
            "note": None,
        }
        if state.plan is None:
            return result

        self._refresh_execution_plan_state(state)
        next_step = state.get_next_planned_step()
        planned_step = self._find_planned_step_for_tool(state, tool_name)
        result["planned_step"] = planned_step
        result["next_step"] = next_step

        if next_step is None:
            note = f"Plan has no pending step, but execution attempted '{tool_name}'."
            state.append_plan_note(note, reconciliation=True)
            result["deviation_type"] = "plan_exhausted"
            result["note"] = note
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.PLAN_DEVIATION,
                    stage_before=TaskStage.EXECUTING.value,
                    action=tool_name,
                    input_summary={"deviation_type": "plan_exhausted"},
                    output_summary={"actual_tool": tool_name},
                    reasoning=note,
                )
            return result

        if tool_name == next_step.tool_name:
            note = f"Actual tool '{tool_name}' matched next planned step {next_step.step_id}."
            state.update_plan_step_status(
                step_id=next_step.step_id,
                status=PlanStepStatus.IN_PROGRESS,
                reconciliation_note=note,
            )
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.PLAN_STEP_MATCHED,
                    stage_before=TaskStage.EXECUTING.value,
                    action=tool_name,
                    input_summary={
                        "step_id": next_step.step_id,
                        "expected_tool": next_step.tool_name,
                        "actual_tool": tool_name,
                        "exact_match": True,
                    },
                    output_summary={"step_status": PlanStepStatus.IN_PROGRESS.value},
                    reasoning=note,
                )
            result["planned_step"] = next_step
            result["matched"] = True
            result["note"] = note
            return result

        if planned_step is not None:
            next_index = state.plan.steps.index(next_step)
            actual_index = state.plan.steps.index(planned_step)
            deviation_type = "ahead_of_plan" if actual_index > next_index else "behind_plan"
            note = (
                f"Actual tool '{tool_name}' maps to planned step {planned_step.step_id}, "
                f"but current next step is {next_step.step_id} ({next_step.tool_name}). "
                f"deviation_type={deviation_type}."
            )
            state.append_plan_note(note, step_id=next_step.step_id, reconciliation=True)
            state.append_plan_note(note, step_id=planned_step.step_id, reconciliation=True)
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.PLAN_DEVIATION,
                    stage_before=TaskStage.EXECUTING.value,
                    action=tool_name,
                    input_summary={
                        "deviation_type": deviation_type,
                        "expected_step_id": next_step.step_id,
                        "expected_tool": next_step.tool_name,
                        "matched_step_id": planned_step.step_id,
                    },
                    output_summary={"actual_tool": tool_name},
                    reasoning=note,
                )
            result["deviation_type"] = deviation_type
            result["note"] = note
            return result

        note = (
            f"Actual tool '{tool_name}' is not present in the current plan; "
            f"next planned step is {next_step.step_id} ({next_step.tool_name})."
        )
        state.append_plan_note(note, reconciliation=True)
        state.append_plan_note(note, step_id=next_step.step_id, reconciliation=True)
        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.PLAN_DEVIATION,
                stage_before=TaskStage.EXECUTING.value,
                action=tool_name,
                input_summary={
                    "deviation_type": "unplanned_tool",
                    "expected_step_id": next_step.step_id,
                    "expected_tool": next_step.tool_name,
                },
                output_summary={"actual_tool": tool_name},
                reasoning=note,
            )
        result["deviation_type"] = "unplanned_tool"
        result["note"] = note
        return result

    def _build_repair_trigger_context(
        self,
        state: TaskState,
        *,
        trigger_type: RepairTriggerType,
        trigger_reason: str,
        actual_tool_name: Optional[str] = None,
        deviation_type: Optional[str] = None,
        planned_step: Optional[Any] = None,
        next_step: Optional[Any] = None,
        dependency_validation: Optional[DependencyValidationResult] = None,
    ) -> RepairTriggerContext:
        affected_step_ids: List[str] = []
        if planned_step is not None and getattr(planned_step, "step_id", None):
            affected_step_ids.append(planned_step.step_id)
        if next_step is not None and getattr(next_step, "step_id", None) and next_step.step_id not in affected_step_ids:
            affected_step_ids.append(next_step.step_id)

        return RepairTriggerContext(
            trigger_type=trigger_type,
            trigger_reason=trigger_reason,
            target_step_id=getattr(planned_step, "step_id", None) or getattr(next_step, "step_id", None),
            affected_step_ids=affected_step_ids,
            actual_tool_name=actual_tool_name,
            deviation_type=deviation_type,
            available_tokens=self._collect_available_result_tokens(state, include_stale=False),
            missing_tokens=list(dependency_validation.missing_tokens) if dependency_validation else [],
            stale_tokens=list(dependency_validation.stale_tokens) if dependency_validation else [],
            next_pending_step_id=getattr(next_step, "step_id", None),
            next_pending_tool_name=getattr(next_step, "tool_name", None),
            matched_step_id=getattr(planned_step, "step_id", None),
            blocked_tool_name=dependency_validation.tool_name if dependency_validation else None,
        )

    def _should_attempt_plan_repair(
        self,
        state: TaskState,
        trigger_context: RepairTriggerContext,
    ) -> tuple[bool, str]:
        if not getattr(self.runtime_config, "enable_bounded_plan_repair", False):
            return False, "bounded plan repair feature flag disabled"
        if state.plan is None:
            return False, "no execution plan available"
        if not hasattr(self.llm, "chat_json"):
            return False, "structured JSON repair generation unavailable"

        if trigger_context.trigger_type == RepairTriggerType.DEPENDENCY_BLOCKED:
            return True, "dependency-blocked repair is always eligible"

        if trigger_context.trigger_type != RepairTriggerType.PLAN_DEVIATION:
            return False, "unsupported repair trigger type"

        deviation_type = trigger_context.deviation_type or "unknown"
        if deviation_type in {"plan_exhausted", "unplanned_tool"}:
            return True, f"deviation_type={deviation_type} requires bounded repair"

        if deviation_type in {"ahead_of_plan", "behind_plan"}:
            residual_validation = self._validate_residual_plan_legality(state)
            if residual_validation and residual_validation.get("status") == PlanStatus.VALID:
                return False, f"deviation_type={deviation_type} kept residual workflow legal"
            return True, f"deviation_type={deviation_type} left residual workflow invalid"

        return False, f"deviation_type={deviation_type} not selected for repair"

    async def _generate_plan_repair(
        self,
        state: TaskState,
        trigger_context: RepairTriggerContext,
    ) -> Optional[PlanRepairDecision]:
        if state.plan is None:
            return None

        residual_steps = [
            step.to_dict()
            for step in state.plan.steps
            if step.status not in {PlanStepStatus.COMPLETED, PlanStepStatus.SKIPPED, PlanStepStatus.FAILED}
        ]
        planner_payload = {
            "trigger": trigger_context.to_dict(),
            "current_plan": state.plan.to_dict(),
            "completed_steps": [
                step.to_dict()
                for step in state.plan.steps
                if step.status == PlanStepStatus.COMPLETED
            ],
            "residual_steps": residual_steps,
            "available_result_tokens": self._collect_available_result_tokens(state, include_stale=False),
            "allowed_tools": sorted(tool for tool in TOOL_GRAPH.keys() if tool != "analyze_file"),
            "canonical_dependency_tokens": ["emission", "dispersion", "hotspot"],
        }

        repair_payload = await self.llm.chat_json(
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(planner_payload, ensure_ascii=False, indent=2),
                }
            ],
            system=REPAIR_PROMPT,
            temperature=0.0,
        )
        decision = PlanRepairDecision.from_dict(repair_payload)
        decision.trigger_type = trigger_context.trigger_type
        decision.trigger_reason = trigger_context.trigger_reason
        if not decision.target_step_id:
            decision.target_step_id = trigger_context.target_step_id
        if not decision.affected_step_ids:
            decision.affected_step_ids = list(trigger_context.affected_step_ids)
        return decision

    def _apply_plan_repair(
        self,
        state: TaskState,
        decision: PlanRepairDecision,
        validation: RepairValidationResult,
    ) -> Optional[ExecutionPlan]:
        if not validation.is_valid or validation.repaired_plan is None:
            return None
        state.set_plan(validation.repaired_plan)
        decision.validation_notes = list(validation.validation_notes)
        decision.repaired_plan_snapshot = validation.repaired_plan.to_dict()
        state.record_plan_repair(decision)
        self._refresh_execution_plan_state(state)
        return validation.repaired_plan

    def _build_plan_repair_response_text(
        self,
        trigger_context: RepairTriggerContext,
        decision: Optional[PlanRepairDecision],
        validation: Optional[RepairValidationResult],
    ) -> str:
        if decision is None or validation is None or not validation.is_valid:
            return (
                f"Execution stopped after {trigger_context.trigger_type.value}: "
                f"{trigger_context.trigger_reason}. The current plan was left unchanged."
            )

        next_step = validation.resulting_next_pending_step
        next_desc = "No further pending step remains."
        if isinstance(next_step, dict) and next_step.get("step_id") and next_step.get("tool_name"):
            next_desc = (
                f"Next pending step is {next_step['step_id']} -> {next_step['tool_name']}."
            )

        if decision.action_type == RepairActionType.NO_REPAIR or not decision.is_applicable:
            return (
                f"Execution stopped after {trigger_context.trigger_type.value}: {trigger_context.trigger_reason}. "
                f"Repair evaluation kept the residual plan unchanged. {next_desc} "
                "No repair step was auto-executed in this turn."
            )

        return (
            f"Execution stopped after {trigger_context.trigger_type.value}: {trigger_context.trigger_reason}. "
            f"Applied bounded repair {summarize_repair_action(decision)}. "
            f"{next_desc} No repair step was auto-executed in this turn."
        )

    def _build_plan_repair_failure_text(
        self,
        trigger_context: RepairTriggerContext,
        failure_reason: str,
    ) -> str:
        return (
            f"Execution stopped after {trigger_context.trigger_type.value}: {trigger_context.trigger_reason}. "
            f"Plan repair failed ({failure_reason}), so the original residual plan was preserved."
        )

    async def _attempt_plan_repair(
        self,
        state: TaskState,
        trigger_context: RepairTriggerContext,
        trace_obj: Optional[Trace] = None,
    ) -> tuple[bool, Optional[PlanRepairDecision], Optional[RepairValidationResult], Optional[str]]:
        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.PLAN_REPAIR_TRIGGERED,
                stage_before=TaskStage.EXECUTING.value,
                action=trigger_context.actual_tool_name or trigger_context.blocked_tool_name,
                input_summary=trigger_context.to_dict(),
                reasoning=trigger_context.trigger_reason,
            )

        try:
            decision = await self._generate_plan_repair(state, trigger_context)
        except Exception as exc:
            failure_reason = f"repair generation error: {exc}"
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.PLAN_REPAIR_FAILED,
                    stage_before=TaskStage.EXECUTING.value,
                    action=trigger_context.actual_tool_name or trigger_context.blocked_tool_name,
                    input_summary=trigger_context.to_dict(),
                    error=str(exc),
                    reasoning=failure_reason,
                )
            return False, None, None, failure_reason

        if decision is None:
            failure_reason = "repair generation returned no decision"
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.PLAN_REPAIR_FAILED,
                    stage_before=TaskStage.EXECUTING.value,
                    action=trigger_context.actual_tool_name or trigger_context.blocked_tool_name,
                    input_summary=trigger_context.to_dict(),
                    reasoning=failure_reason,
                )
            return False, None, None, failure_reason

        validation = validate_plan_repair(
            state.plan,
            decision,
            available_tokens=self._collect_available_result_tokens(state, include_stale=False),
            context_store=self._ensure_context_store(),
        )

        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.PLAN_REPAIR_PROPOSED,
                stage_before=TaskStage.EXECUTING.value,
                action=decision.action_type.value,
                input_summary={
                    "trigger_type": decision.trigger_type.value,
                    "target_step_id": decision.target_step_id,
                    "affected_step_ids": decision.affected_step_ids,
                },
                output_summary={
                    "validation_passed": validation.is_valid,
                    "action_type": decision.action_type.value,
                    "resulting_next_pending_step": validation.resulting_next_pending_step,
                },
                reasoning=decision.planner_notes or summarize_repair_action(decision),
            )

        if decision.action_type == RepairActionType.NO_REPAIR or not decision.is_applicable:
            if not validation.is_valid:
                failure_reason = "; ".join(issue.message for issue in validation.issues) or "repair validation failed"
                if trace_obj:
                    trace_obj.record(
                        step_type=TraceStepType.PLAN_REPAIR_FAILED,
                        stage_before=TaskStage.EXECUTING.value,
                        action=decision.action_type.value,
                        input_summary=trigger_context.to_dict(),
                        output_summary=validation.to_dict(),
                        reasoning=failure_reason,
                    )
                return False, decision, validation, failure_reason
            reason = decision.planner_notes or "Repair decision elected to keep the residual plan unchanged."
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.PLAN_REPAIR_SKIPPED,
                    stage_before=TaskStage.EXECUTING.value,
                    action=decision.action_type.value,
                    input_summary=trigger_context.to_dict(),
                    output_summary={"action_type": decision.action_type.value},
                    reasoning=reason,
                )
            return True, decision, validation, None

        if not validation.is_valid:
            failure_reason = "; ".join(issue.message for issue in validation.issues) or "repair validation failed"
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.PLAN_REPAIR_FAILED,
                    stage_before=TaskStage.EXECUTING.value,
                    action=decision.action_type.value,
                    input_summary=trigger_context.to_dict(),
                    output_summary=validation.to_dict(),
                    reasoning=failure_reason,
                )
            return False, decision, validation, failure_reason

        repaired_plan = self._apply_plan_repair(state, decision, validation)
        if trace_obj and repaired_plan is not None:
            trace_obj.record(
                step_type=TraceStepType.PLAN_REPAIR_APPLIED,
                stage_before=TaskStage.EXECUTING.value,
                action=decision.action_type.value,
                input_summary={
                    "target_step_id": decision.target_step_id,
                    "affected_step_ids": decision.affected_step_ids,
                },
                output_summary={
                    "next_pending_step": validation.resulting_next_pending_step,
                    "plan_status": repaired_plan.status.value,
                },
                reasoning=self._build_plan_repair_response_text(trigger_context, decision, validation),
            )
        return True, decision, validation, None

    def _validate_execution_dependencies(
        self,
        state: TaskState,
        tool_name: str,
        arguments: Optional[Dict[str, Any]],
        trace_obj: Optional[Trace] = None,
    ) -> DependencyValidationResult:
        available_tokens = self._collect_available_result_tokens(state, include_stale=False)
        state.execution.available_results.update(available_tokens)
        validation = validate_tool_prerequisites(
            tool_name,
            arguments=arguments,
            available_tokens=state.execution.available_results,
            context_store=self._ensure_context_store(),
            include_stale=False,
        )
        if (
            not validation.is_valid
            and self._should_allow_tool_level_dependency_resolution(
                state=state,
                tool_name=tool_name,
                arguments=arguments,
                validation=validation,
            )
        ):
            validation = DependencyValidationResult(
                tool_name=tool_name,
                required_tokens=validation.required_tokens,
                available_tokens=validation.available_tokens,
                missing_tokens=[],
                stale_tokens=[],
                is_valid=True,
                message=(
                    f"Allowing {tool_name} to attempt direct input resolution without "
                    "stored prerequisite context."
                ),
                issues=[],
            )
        if trace_obj:
            trace_obj.record(
                step_type=(
                    TraceStepType.DEPENDENCY_VALIDATED
                    if validation.is_valid
                    else TraceStepType.DEPENDENCY_BLOCKED
                ),
                stage_before=TaskStage.EXECUTING.value,
                action=tool_name,
                input_summary={
                    "required_tokens": validation.required_tokens,
                    "available_tokens": validation.available_tokens,
                    "missing_tokens": validation.missing_tokens,
                    "stale_tokens": validation.stale_tokens,
                },
                output_summary={"validation_passed": validation.is_valid},
                reasoning=validation.message,
            )
        return validation

    def _should_allow_tool_level_dependency_resolution(
        self,
        *,
        state: TaskState,
        tool_name: str,
        arguments: Optional[Dict[str, Any]],
        validation: DependencyValidationResult,
    ) -> bool:
        if state.plan is not None:
            return False
        if validation.stale_tokens:
            return False
        hints = self._extract_message_execution_hints(state)
        desired_chain = list(hints.get("desired_tool_chain") or [])
        if tool_name in desired_chain:
            current_index = desired_chain.index(tool_name)
            for required_prior_tool in desired_chain[:current_index]:
                if required_prior_tool not in set(state.execution.completed_tools or []):
                    return False
        allowed_missing = {
            "calculate_dispersion": ["emission"],
            "analyze_hotspots": ["dispersion"],
        }
        return validation.missing_tokens == allowed_missing.get(tool_name)

    def _mark_blocked_plan_step(
        self,
        state: TaskState,
        tool_name: str,
        reason: str,
        planned_step: Optional[Any] = None,
    ) -> None:
        if state.plan is None:
            return
        target_step = planned_step or self._find_planned_step_for_tool(state, tool_name)
        if target_step is None:
            state.plan.append_validation_note(reason)
            return
        state.update_plan_step_status(
            step_id=target_step.step_id,
            status=PlanStepStatus.BLOCKED,
            note=reason,
            reconciliation_note=f"Execution blocked before {tool_name}.",
            blocked_reason=reason,
        )
        state.plan.append_validation_note(reason)
        self._update_plan_status_from_steps(state)

    def _build_dependency_blocked_response_text(
        self,
        state: TaskState,
        validation: DependencyValidationResult,
    ) -> str:
        token_parts: List[str] = []
        if validation.missing_tokens:
            token_parts.append(f"missing prerequisite results: {', '.join(validation.missing_tokens)}")
        if validation.stale_tokens:
            token_parts.append(f"only stale results are available for: {', '.join(validation.stale_tokens)}")

        blocker = validation.tool_name
        explanation = "; ".join(token_parts) if token_parts else validation.message
        if state.execution.completed_tools:
            completed = ", ".join(state.execution.completed_tools)
            return (
                f"Completed {completed}, but cannot continue with {blocker} because {explanation}. "
                "This turn stops at the deterministic dependency gate."
            )
        return (
            f"Cannot execute {blocker} because {explanation}. "
            "This turn stops before tool execution."
        )

    async def _generate_execution_plan(self, state: TaskState) -> Optional[ExecutionPlan]:
        """Ask the LLM for a lightweight structured workflow plan."""
        if not hasattr(self.llm, "chat_json"):
            return None

        template_prior_payload = None
        if state.template_prior_used and state.selected_workflow_template is not None:
            matching_recommendation = next(
                (
                    item
                    for item in state.recommended_workflow_templates
                    if item.template_id == state.selected_workflow_template.template_id
                ),
                None,
            )
            if matching_recommendation is not None:
                template_prior_payload = {
                    "selected_template": state.selected_workflow_template.to_dict(),
                    "recommendation": matching_recommendation.to_dict(),
                    "summary": self._format_workflow_template_injection(
                        state.selected_workflow_template,
                        matching_recommendation,
                    ),
                }

        planner_payload = {
            "user_message": state.user_message or "",
            "file_context": self._build_state_file_context(state),
            "available_result_tokens": self._collect_available_result_tokens(state),
            "context_summary": self._get_context_summary(),
            "workflow_template_prior": template_prior_payload,
            "workflow_template_recommendations": [
                recommendation.to_dict()
                for recommendation in state.recommended_workflow_templates
            ],
            "allowed_tools": [
                "calculate_macro_emission",
                "calculate_micro_emission",
                "calculate_dispersion",
                "analyze_hotspots",
                "render_spatial_map",
                "compare_scenarios",
                "query_emission_factors",
                "query_knowledge",
            ],
        }

        try:
            plan_payload = await self.llm.chat_json(
                messages=[
                    {
                        "role": "user",
                        "content": json.dumps(planner_payload, ensure_ascii=False, indent=2),
                    }
                ],
                system=PLANNING_PROMPT,
                temperature=0.0,
            )
        except Exception as exc:
            logger.warning("Lightweight planning failed; continuing without plan: %s", exc)
            return None

        try:
            plan = ExecutionPlan.from_dict(plan_payload)
        except Exception as exc:
            logger.warning("Failed to hydrate execution plan; continuing without plan: %s", exc)
            return None

        if not plan.goal:
            plan.goal = state.user_message or "Execute the grounded analysis workflow"

        normalized_steps = []
        for step in plan.steps:
            if step.tool_name == "analyze_file":
                continue
            if not step.step_id or step.step_id == "step":
                step.step_id = f"s{len(normalized_steps) + 1}"
            step.depends_on = normalize_tokens(step.depends_on)
            step.produces = normalize_tokens(step.produces or get_tool_provides(step.tool_name))
            step.status = PlanStepStatus.PENDING
            step.validation_notes = []
            normalized_steps.append(step)
        plan.steps = normalized_steps
        plan.status = PlanStatus.DRAFT
        plan.validation_notes = []
        return plan

    def _validate_execution_plan(self, state: TaskState) -> Optional[Dict[str, Any]]:
        """Run deterministic validation and write the result back into state.plan."""
        if state.plan is None:
            return None

        available_tokens = self._collect_available_result_tokens(state)
        validation = validate_plan_steps(state.plan.steps, available_tokens=available_tokens)
        state.plan.status = validation["status"]
        state.plan.validation_notes = list(validation["validation_notes"])

        step_by_id = {step.step_id: step for step in state.plan.steps}
        for step_result in validation["step_results"]:
            step = step_by_id.get(step_result["step_id"])
            if step is None:
                continue
            step.depends_on = list(step_result["required_tokens"])
            step.produces = list(step_result["produced_tokens"])
            step.status = step_result["status"]
            step.validation_notes = list(step_result["validation_notes"])
        return validation

    def _format_plan_guidance(self, plan: ExecutionPlan, available_tokens: List[str]) -> str:
        lines = [
            "[Execution plan guidance]",
            f"Goal: {plan.goal}",
            f"Plan status: {plan.status.value}",
        ]
        if available_tokens:
            lines.append(f"Available result tokens: {', '.join(available_tokens)}")
        if plan.planner_notes:
            lines.append(f"Planner notes: {plan.planner_notes}")

        next_step = plan.get_next_step()
        if next_step is not None:
            lines.append(f"Next planned step: {next_step.step_id} -> {next_step.tool_name}")

        for step in plan.steps[:4]:
            step_line = f"- {step.step_id}: {step.tool_name}"
            if step.depends_on:
                step_line += f" | depends_on={', '.join(step.depends_on)}"
            if step.produces:
                step_line += f" | produces={', '.join(step.produces)}"
            if step.argument_hints:
                step_line += (
                    " | argument_hints="
                    + json.dumps(step.argument_hints, ensure_ascii=False, sort_keys=True)
                )
            lines.append(step_line)

        lines.append(
            "Use this plan as soft guidance only. Prefer the next ready planned step when appropriate, "
            "and only deviate when grounded context or available results justify it."
        )
        return "\n".join(lines)

    def _inject_plan_guidance(
        self,
        context: Any,
        plan: Optional[ExecutionPlan],
        available_tokens: Optional[List[str]] = None,
    ) -> None:
        """Inject a compact plan summary into the first tool-selection context."""
        if plan is None or not plan.steps or plan.status == PlanStatus.INVALID:
            return

        guidance_message = {
            "role": "system",
            "content": self._format_plan_guidance(plan, available_tokens or []),
        }

        insert_at = len(context.messages)
        if context.messages and context.messages[-1].get("role") == "user":
            insert_at -= 1
        context.messages.insert(insert_at, guidance_message)

    def _validate_tool_selection_against_plan(
        self,
        state: TaskState,
        trace_obj: Optional[Trace] = None,
    ) -> None:
        """Soft-check the first selected tool against the next planned step."""
        if state.plan is None or state._llm_response is None or not state._llm_response.tool_calls:
            return

        next_step = state.get_next_planned_step()
        if next_step is None:
            return

        actual_tool = state._llm_response.tool_calls[0].name
        if actual_tool == next_step.tool_name:
            state.update_plan_step_status(
                step_id=next_step.step_id,
                status=PlanStepStatus.IN_PROGRESS,
                reconciliation_note="LLM selected the next planned tool.",
            )
            return

        deviation_note = (
            f"Expected next planned tool '{next_step.tool_name}' ({next_step.step_id}) "
            f"but LLM selected '{actual_tool}'."
        )
        state.plan.append_validation_note(deviation_note)
        state.append_plan_note(deviation_note, step_id=next_step.step_id, reconciliation=True)
        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.PLAN_DEVIATION,
                stage_before=TaskStage.GROUNDED.value,
                action=actual_tool,
                input_summary={"expected_tool": next_step.tool_name, "step_id": next_step.step_id},
                output_summary={"actual_tool": actual_tool},
                reasoning=deviation_note,
            )

    def _update_plan_after_tool_execution(
        self,
        state: TaskState,
        tool_name: str,
        result: Dict[str, Any],
    ) -> Optional[Any]:
        """Reflect actual execution outcomes back into the plan state."""
        if state.plan is None:
            return None

        target_step = self._find_planned_step_for_tool(state, tool_name)
        if target_step is None:
            return None

        if result.get("success"):
            note = "Tool executed successfully."
            state.update_plan_step_status(
                step_id=target_step.step_id,
                status=PlanStepStatus.COMPLETED,
                note=note,
                reconciliation_note=f"Execution completed for {tool_name}.",
                blocked_reason="",
            )
        else:
            note = str(result.get("message") or result.get("error") or "Tool execution failed.")
            state.update_plan_step_status(
                step_id=target_step.step_id,
                status=PlanStepStatus.FAILED,
                note=note,
                reconciliation_note=f"Execution failed for {tool_name}.",
            )
        self._update_plan_status_from_steps(state)
        return target_step

    def _capture_tool_call_parameters(self, state: TaskState, tool_calls: Optional[List[Any]]) -> None:
        """Persist tool-call arguments into state parameters for grounding and tracing."""
        for tool_call in tool_calls or []:
            for key, value in (tool_call.arguments or {}).items():
                if value is None:
                    continue
                existing = state.parameters.get(key)
                if existing is not None and existing.locked:
                    continue
                if isinstance(value, list):
                    raw_value = ", ".join(str(item) for item in value)
                else:
                    raw_value = str(value)
                state.parameters[key] = ParamEntry(
                    raw=raw_value,
                    normalized=raw_value,
                    status=ParamStatus.OK,
                    confidence=1.0,
                    strategy="exact",
                )

    def _summarize_map_data_for_llm(self, map_data: Dict[str, Any]) -> Dict[str, Any]:
        """Keep only compact map metadata when re-feeding tool results to the LLM."""
        summary: Dict[str, Any] = {}
        for key in ("type", "title", "pollutant", "unit"):
            if key in map_data:
                summary[key] = map_data[key]

        map_summary = map_data.get("summary")
        if isinstance(map_summary, dict) and map_summary:
            summary["summary"] = map_summary

        coverage = map_data.get("coverage_assessment")
        if isinstance(coverage, dict) and coverage.get("warnings"):
            summary["coverage_assessment"] = {
                "warnings": coverage.get("warnings", [])[:3],
            }

        if isinstance(map_data.get("links"), list):
            summary["feature_count"] = len(map_data["links"])

        if isinstance(map_data.get("hotspots_detail"), list):
            summary["hotspot_count"] = len(map_data["hotspots_detail"])

        return summary

    def _append_tool_messages_for_llm(
        self,
        messages: List[Dict[str, Any]],
        response: Any,
        tool_results: List[Dict[str, Any]],
    ) -> None:
        """Append assistant/tool messages so the LLM can choose the next step naturally."""
        assistant_tool_calls = []
        tool_results_by_id = {}

        for item in tool_results:
            tool_call_id = item.get("tool_call_id")
            if tool_call_id:
                tool_results_by_id[tool_call_id] = item

        for tool_call in response.tool_calls or []:
            assistant_tool_calls.append(
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": json.dumps(tool_call.arguments or {}, ensure_ascii=False),
                    },
                }
            )

        messages.append(
            {
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": assistant_tool_calls,
            }
        )

        for tool_call in response.tool_calls or []:
            tool_result = tool_results_by_id.get(tool_call.id)
            if not tool_result:
                continue
            messages.append(
                self._build_tool_result_message(
                    tool_name=tool_result.get("name", tool_call.name),
                    result=tool_result.get("result", {}),
                    tool_call_id=tool_call.id,
                )
            )

    def _extract_frontend_payloads(self, tool_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Collect frontend payloads from all tool results in execution order."""
        chart_data = self._extract_chart_data(tool_results)
        table_data = self._extract_table_data(tool_results)
        map_data = self._extract_map_data(tool_results)
        download_file = self._extract_download_file(tool_results)

        map_payload_count = 0
        if isinstance(map_data, dict):
            if map_data.get("type") == "map_collection" and isinstance(map_data.get("items"), list):
                map_payload_count = len(map_data["items"])
            else:
                map_payload_count = 1

        logger.info(
            "[frontend payloads] chart=%s table=%s map=%s download=%s",
            bool(chart_data),
            bool(table_data),
            map_payload_count,
            bool(download_file),
        )
        return {
            "chart_data": chart_data,
            "table_data": table_data,
            "map_data": map_data,
            "download_file": download_file,
        }

    def _get_file_context_for_synthesis(
        self,
        state: Optional[TaskState] = None,
    ) -> Optional[Dict[str, Any]]:
        """Resolve the best grounded file context available for synthesis guidance."""
        if state is not None:
            state_file_context = self._build_state_file_context(state)
            if isinstance(state_file_context, dict):
                return state_file_context

        fact_memory: Dict[str, Any] = {}
        if hasattr(self, "memory") and hasattr(self.memory, "get_fact_memory"):
            maybe_memory = self.memory.get_fact_memory()
            if isinstance(maybe_memory, dict):
                fact_memory = maybe_memory

        file_analysis = fact_memory.get("file_analysis")
        if isinstance(file_analysis, dict):
            return dict(file_analysis)
        return None

    def _build_readiness_assessment(
        self,
        tool_results: List[Dict[str, Any]],
        *,
        state: Optional[TaskState] = None,
        frontend_payloads: Optional[Dict[str, Any]] = None,
        trace_obj: Optional[Trace] = None,
        stage_before: Optional[str] = None,
        purpose: str = "synthesis_guidance",
    ) -> Optional[ReadinessAssessment]:
        if purpose in {"pre_execution", "input_completion_recheck"} and not getattr(
            self.runtime_config,
            "enable_readiness_gating",
            True,
        ):
            return None
        if purpose == "intent_resolution" and not getattr(
            self.runtime_config,
            "enable_intent_resolution",
            True,
        ):
            return None
        if purpose not in {"pre_execution", "input_completion_recheck", "intent_resolution"} and not getattr(
            self.runtime_config,
            "enable_capability_aware_synthesis",
            True,
        ):
            return None

        file_context = self._get_file_context_for_synthesis(state)
        parameter_locks = state.get_parameter_locks_summary() if state is not None else None
        input_completion_overrides = (
            state.get_input_completion_overrides_summary()
            if state is not None
            else None
        )
        assessment = build_readiness_assessment(
            file_context,
            self._ensure_context_store(),
            tool_results,
            frontend_payloads,
            parameter_locks=parameter_locks,
            input_completion_overrides=input_completion_overrides,
            already_provided_dedup_enabled=getattr(
                self.runtime_config,
                "readiness_already_provided_dedup_enabled",
                True,
            ),
            artifact_memory_state=(
                state.artifact_memory_state
                if state is not None and getattr(self.runtime_config, "enable_artifact_memory", True)
                else None
            ),
        )
        if trace_obj and stage_before:
            counts = assessment.counts()
            trace_obj.record(
                step_type=TraceStepType.READINESS_ASSESSMENT_BUILT,
                stage_before=stage_before,
                action=purpose,
                input_summary={
                    "purpose": purpose,
                    "task_type": assessment.key_signals.get("task_type"),
                    "has_geometry_support": assessment.key_signals.get("has_geometry_support"),
                    "available_result_tokens": assessment.key_signals.get("available_result_tokens"),
                    "provided_artifact_ids": assessment.key_signals.get("provided_artifact_ids"),
                    "missing_field_status": assessment.key_signals.get("missing_field_status"),
                },
                output_summary=counts,
                reasoning=(
                    f"Built readiness assessment for {purpose}: "
                    f"ready={counts['ready']}, repairable={counts['repairable']}, "
                    f"blocked={counts['blocked']}, already_provided={counts['already_provided']}."
                ),
            )
        return assessment

    def _record_action_readiness_trace(
        self,
        affordance: ActionAffordance,
        *,
        trace_obj: Optional[Trace],
        stage_before: str,
        purpose: str,
    ) -> None:
        if trace_obj is None:
            return
        step_type_map = {
            ReadinessStatus.READY: TraceStepType.ACTION_READINESS_READY,
            ReadinessStatus.BLOCKED: TraceStepType.ACTION_READINESS_BLOCKED,
            ReadinessStatus.REPAIRABLE: TraceStepType.ACTION_READINESS_REPAIRABLE,
            ReadinessStatus.ALREADY_PROVIDED: TraceStepType.ACTION_READINESS_ALREADY_PROVIDED,
        }
        reason = affordance.reason.message if affordance.reason is not None else affordance.description
        trace_obj.record(
            step_type=step_type_map[affordance.status],
            stage_before=stage_before,
            action=affordance.action_id,
            input_summary={
                "purpose": purpose,
                "action_id": affordance.action_id,
                "display_name": affordance.display_name,
                "tool_name": affordance.tool_name,
                "arguments": affordance.arguments,
            },
            output_summary={
                "status": affordance.status.value,
                "reason_code": affordance.reason.reason_code if affordance.reason is not None else None,
                "missing_requirements": (
                    affordance.reason.missing_requirements
                    if affordance.reason is not None
                    else []
                ),
                "repair_hint": affordance.reason.repair_hint if affordance.reason is not None else None,
            },
            reasoning=reason,
        )
        if affordance.status == ReadinessStatus.ALREADY_PROVIDED and affordance.provided_artifact is not None:
            trace_obj.record(
                step_type=TraceStepType.ARTIFACT_ALREADY_PROVIDED_DETECTED,
                stage_before=stage_before,
                action=affordance.action_id,
                output_summary={
                    "provided_artifact": affordance.provided_artifact.to_dict(),
                    "purpose": purpose,
                },
                reasoning=(
                    affordance.provided_artifact.message
                    or "Artifact memory detected that the requested deliverable was already provided."
                ),
            )

    def _build_action_readiness_block_payload(
        self,
        affordance: ActionAffordance,
    ) -> Dict[str, Any]:
        return {
            "action_id": affordance.action_id,
            "display_name": affordance.display_name,
            "tool_name": affordance.tool_name,
            "status": affordance.status.value,
            "message": affordance.reason.message if affordance.reason is not None else affordance.description,
            "reason_code": affordance.reason.reason_code if affordance.reason is not None else None,
            "missing_requirements": (
                list(affordance.reason.missing_requirements)
                if affordance.reason is not None
                else []
            ),
            "repair_hint": affordance.reason.repair_hint if affordance.reason is not None else None,
            "alternative_actions": list(affordance.alternative_actions),
            "provided_artifact": (
                affordance.provided_artifact.to_dict()
                if affordance.provided_artifact is not None
                else None
            ),
        }

    def _should_short_circuit_readiness(
        self,
        affordance: ActionAffordance,
    ) -> bool:
        if affordance.status in {
            ReadinessStatus.BLOCKED,
            ReadinessStatus.ALREADY_PROVIDED,
        }:
            return True
        if affordance.status != ReadinessStatus.REPAIRABLE:
            return False
        if not getattr(self.runtime_config, "readiness_repairable_enabled", True):
            return False
        reason_code = affordance.reason.reason_code if affordance.reason is not None else None
        return reason_code not in {"missing_prerequisite_result", "stale_prerequisite_result"}

    def _assess_selected_action_readiness(
        self,
        *,
        tool_name: str,
        arguments: Optional[Dict[str, Any]],
        tool_results: List[Dict[str, Any]],
        state: Optional[TaskState] = None,
        trace_obj: Optional[Trace] = None,
        stage_before: str,
        purpose: str = "pre_execution",
    ) -> tuple[Optional[ReadinessAssessment], Optional[ActionAffordance]]:
        frontend_payloads = self._extract_frontend_payloads(tool_results)
        assessment = self._build_readiness_assessment(
            tool_results,
            state=state,
            frontend_payloads=frontend_payloads,
            trace_obj=trace_obj,
            stage_before=stage_before,
            purpose=purpose,
        )
        if assessment is None:
            return None, None

        action_id = map_tool_call_to_action_id(tool_name, arguments)
        if action_id is None:
            return assessment, None

        affordance = assessment.get_action(action_id)
        if affordance is not None:
            self._record_action_readiness_trace(
                affordance,
                trace_obj=trace_obj,
                stage_before=stage_before,
                purpose=purpose,
            )
        return assessment, affordance

    def _build_capability_summary_for_synthesis(
        self,
        tool_results: List[Dict[str, Any]],
        *,
        state: Optional[TaskState] = None,
        frontend_payloads: Optional[Dict[str, Any]] = None,
        trace_obj: Optional[Trace] = None,
        stage_before: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Summarize current data capabilities so synthesis stays within supported actions."""
        if not getattr(self.runtime_config, "enable_capability_aware_synthesis", True):
            logger.info("[CapabilityAwareSynthesis] disabled by feature flag")
            return None

        assessment = self._build_readiness_assessment(
            tool_results,
            state=state,
            frontend_payloads=frontend_payloads,
            trace_obj=trace_obj,
            stage_before=stage_before,
            purpose="synthesis_guidance",
        )
        if assessment is None:
            return None
        summary = assessment.to_capability_summary()
        if (
            state is not None
            and state.latest_intent_resolution_plan is not None
            and getattr(self.runtime_config, "intent_resolution_bias_followup_suggestions", True)
        ):
            summary = apply_intent_bias_to_capability_summary(
                summary,
                state.latest_intent_resolution_plan,
            )
        if (
            state is not None
            and getattr(self.runtime_config, "enable_artifact_memory", True)
        ):
            artifact_plan = build_artifact_suggestion_plan(
                state.artifact_memory_state,
                capability_summary=summary,
                intent_plan=state.latest_intent_resolution_plan,
                dedup_by_family=getattr(
                    self.runtime_config,
                    "artifact_memory_dedup_by_family",
                    True,
                ),
            )
            if (
                trace_obj is not None
                and stage_before is not None
                and (
                    artifact_plan.repeated_artifact_types
                    or artifact_plan.repeated_artifact_families
                )
            ):
                trace_obj.record(
                    step_type=TraceStepType.ARTIFACT_ALREADY_PROVIDED_DETECTED,
                    stage_before=stage_before,
                    action="artifact_memory_repeat_detection",
                    input_summary=state.get_artifact_memory_summary(),
                    output_summary=artifact_plan.to_dict(),
                    reasoning=(
                        "Detected previously delivered artifact types/families and suppressed repeated follow-up guidance."
                    ),
                )
            if getattr(self.runtime_config, "artifact_memory_bias_followup", True):
                summary = apply_artifact_memory_to_capability_summary(
                    summary,
                    state.artifact_memory_state,
                    state.latest_intent_resolution_plan,
                    dedup_by_family=getattr(
                        self.runtime_config,
                        "artifact_memory_dedup_by_family",
                        True,
                    ),
                )
                if (
                    trace_obj is not None
                    and stage_before is not None
                    and (
                        artifact_plan.suppressed_action_ids
                        or artifact_plan.promoted_families
                        or artifact_plan.user_visible_summary
                    )
                ):
                    trace_obj.record(
                        step_type=TraceStepType.ARTIFACT_SUGGESTION_BIAS_APPLIED,
                        stage_before=stage_before,
                        action="artifact_memory_followup_bias",
                        input_summary=state.get_artifact_memory_summary(),
                        output_summary=artifact_plan.to_dict(),
                        reasoning=(
                            "Applied bounded artifact-memory bias so follow-up suggestions prefer new output forms over repeated deliverables."
                        ),
                    )
        try:
            logger.info(
                "[CapabilityAwareSynthesis] file_context_present=%s summary=%s",
                bool(self._get_file_context_for_synthesis(state)),
                json.dumps(summary, ensure_ascii=False, indent=2),
            )
        except Exception:
            logger.info(
                "[CapabilityAwareSynthesis] file_context_present=%s summary_unserializable",
                bool(self._get_file_context_for_synthesis(state)),
            )
        return summary

    async def _state_handle_input(
        self,
        state: TaskState,
        trace_obj: Optional[Trace] = None,
    ) -> None:
        self._apply_live_input_completion_state(state)
        self._apply_live_parameter_state(state)
        self._apply_live_file_relationship_state(state)
        self._apply_live_intent_resolution_state(state)
        state.set_latest_summary_delivery_plan(None)
        state.set_latest_summary_delivery_result(None)
        cached_file_context = getattr(state, "_file_analysis_cache", None)
        if isinstance(cached_file_context, dict):
            cached_file_context["latest_summary_delivery_plan"] = None
            cached_file_context["latest_summary_delivery_result"] = None
            setattr(state, "_file_analysis_cache", cached_file_context)

        forced_continuation_decision: Optional[ContinuationDecision] = None
        skip_generic_new_task_reset = False

        should_resolve_relationship, resolution_reason = self._should_resolve_file_relationship(state)
        if should_resolve_relationship:
            relationship_context = await self._build_file_relationship_resolution_context(state)
            if trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.FILE_RELATIONSHIP_RESOLUTION_TRIGGERED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="file_relationship_resolution",
                    input_summary={
                        "trigger_reason": resolution_reason,
                        "current_primary_file": (
                            relationship_context.current_primary_file.to_dict()
                            if relationship_context.current_primary_file is not None
                            else None
                        ),
                        "latest_uploaded_file": (
                            relationship_context.latest_uploaded_file.to_dict()
                            if relationship_context.latest_uploaded_file is not None
                            else None
                        ),
                        "current_task_type": relationship_context.current_task_type,
                        "has_pending_completion": relationship_context.has_pending_completion,
                        "has_geometry_recovery": relationship_context.has_geometry_recovery,
                        "has_residual_workflow": relationship_context.has_residual_workflow,
                    },
                    reasoning=resolution_reason,
                )

            parse_result = await self._resolve_file_relationship(relationship_context)
            if parse_result.error and trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.FILE_RELATIONSHIP_RESOLUTION_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="file_relationship_resolution",
                    input_summary=relationship_context.to_dict(),
                    output_summary=parse_result.to_dict(),
                    reasoning=parse_result.error,
                    error=parse_result.error,
                )

            decision = parse_result.decision or infer_file_relationship_fallback(relationship_context)
            transition_plan = build_file_relationship_transition_plan(decision, relationship_context)
            if trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.FILE_RELATIONSHIP_RESOLUTION_DECIDED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action=decision.relationship_type.value,
                    input_summary={
                        "current_primary_file": (
                            relationship_context.current_primary_file.to_dict()
                            if relationship_context.current_primary_file is not None
                            else None
                        ),
                        "latest_uploaded_file": (
                            relationship_context.latest_uploaded_file.to_dict()
                            if relationship_context.latest_uploaded_file is not None
                            else None
                        ),
                        "user_message": state.user_message,
                    },
                    output_summary={
                        "relationship_type": decision.relationship_type.value,
                        "confidence": decision.confidence,
                        "decision": decision.to_dict(),
                        "transition_plan": transition_plan.to_dict(),
                    },
                    confidence=decision.confidence,
                    reasoning=decision.reason or "Resolved the new file against the current workflow state.",
                )

            self._apply_file_relationship_transition(
                state,
                relationship_context,
                decision,
                transition_plan,
                trace_obj=trace_obj,
            )
            skip_generic_new_task_reset = transition_plan.suppress_generic_new_task_reset

            if (
                transition_plan.pending_merge_semantics
                and getattr(self.runtime_config, "enable_supplemental_column_merge", True)
                and state.stage == TaskStage.INPUT_RECEIVED
            ):
                handled = await self._handle_supplemental_merge(
                    state,
                    relationship_context,
                    decision,
                    transition_plan,
                    trace_obj=trace_obj,
                )
                if handled and state.stage in {
                    TaskStage.NEEDS_CLARIFICATION,
                    TaskStage.DONE,
                }:
                    return

            if state.stage in {
                TaskStage.NEEDS_CLARIFICATION,
                TaskStage.DONE,
            }:
                return
        elif trace_obj is not None:
            trace_obj.record(
                step_type=TraceStepType.FILE_RELATIONSHIP_RESOLUTION_SKIPPED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action="file_relationship_resolution",
                input_summary={
                    "incoming_file_path": state.incoming_file_path,
                    "user_message": state.user_message,
                },
                reasoning=resolution_reason,
            )

        if state.active_input_completion is not None:
            forced_continuation_decision = await self._handle_active_input_completion(
                state,
                trace_obj=trace_obj,
            )
            if state.stage in {
                TaskStage.NEEDS_INPUT_COMPLETION,
                TaskStage.DONE,
            }:
                return

        if state.active_parameter_negotiation is not None:
            forced_continuation_decision = self._handle_active_parameter_confirmation(
                state,
                trace_obj=trace_obj,
            )
            if state.stage in {
                TaskStage.NEEDS_CLARIFICATION,
                TaskStage.NEEDS_PARAMETER_CONFIRMATION,
            }:
                return

        if forced_continuation_decision is None:
            forced_continuation_decision = self._should_continue_geometry_recovery(state)

        if state.file_context.has_file and not state.file_context.grounded:
            from pathlib import Path
            import os

            cached = self.memory.get_fact_memory().get("file_analysis")
            file_path_str = str(state.file_context.file_path)
            pending_relationship_analysis = getattr(state, "_pending_file_relationship_upload_analysis", None)

            try:
                current_mtime = os.path.getmtime(file_path_str)
            except Exception:
                current_mtime = None

            cache_valid = (
                cached
                and str(cached.get("file_path")) == file_path_str
                and cached.get("file_mtime") == current_mtime
            )

            if (
                self.runtime_config.enable_file_analyzer
                and isinstance(pending_relationship_analysis, dict)
                and str(pending_relationship_analysis.get("file_path") or "").strip() == file_path_str
            ):
                analysis_dict = dict(pending_relationship_analysis)
                analysis_dict["file_mtime"] = current_mtime
                analysis_dict = await self._maybe_apply_file_analysis_fallback(
                    analysis_dict,
                    trace_obj=trace_obj,
                )
                logger.info("Using cached relationship-resolution upload analysis for %s", file_path_str)
            elif self.runtime_config.enable_file_analyzer and cache_valid:
                analysis_dict = dict(cached)
                analysis_dict = await self._maybe_apply_file_analysis_fallback(
                    analysis_dict,
                    trace_obj=trace_obj,
                )
                logger.info(f"Using cached file analysis for {state.file_context.file_path}")
            elif self.runtime_config.enable_file_analyzer:
                analysis_dict = await self._analyze_file(file_path_str)
                analysis_dict["file_path"] = file_path_str
                analysis_dict["file_mtime"] = current_mtime
                analysis_dict = await self._maybe_apply_file_analysis_fallback(
                    analysis_dict,
                    trace_obj=trace_obj,
                )
                logger.info(f"Analyzed new file: {state.file_context.file_path} (mtime: {current_mtime})")
            else:
                analysis_dict = {
                    "filename": Path(file_path_str).name,
                    "file_path": file_path_str,
                    "task_type": None,
                    "confidence": 0.0,
                }
                logger.info("File analyzer disabled by runtime config")

            state.update_file_context(analysis_dict)
            setattr(state, "_file_analysis_cache", analysis_dict)
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.FILE_GROUNDING,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="analyze_file",
                    output_summary={
                        "task_type": state.file_context.task_type,
                        "confidence": state.file_context.confidence,
                        "columns": state.file_context.columns[:10],
                        "row_count": state.file_context.row_count,
                    },
                    confidence=state.file_context.confidence,
                    reasoning="; ".join(state.file_context.evidence) if state.file_context.evidence else "File structure analyzed",
                )
                self._record_file_analysis_enhancement_traces(analysis_dict, trace_obj)

        should_resolve_intent, intent_resolution_reason = self._should_resolve_intent(state)
        if should_resolve_intent:
            intent_assessment = self._build_readiness_assessment(
                state.execution.tool_results,
                state=state,
                frontend_payloads=self._extract_frontend_payloads(state.execution.tool_results),
                trace_obj=None,
                stage_before=None,
                purpose="intent_resolution",
            )
            intent_context = self._build_intent_resolution_context(state, intent_assessment)
            if trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.INTENT_RESOLUTION_TRIGGERED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="intent_resolution",
                    input_summary={
                        "trigger_reason": intent_resolution_reason,
                        "current_task_type": intent_context.current_task_type,
                        "recent_result_types": list(intent_context.recent_result_types),
                        "has_residual_workflow": intent_context.has_residual_workflow,
                        "has_recovered_target": intent_context.has_recovered_target,
                    },
                    reasoning=intent_resolution_reason,
                )

            intent_parse_result = await self._resolve_deliverable_and_progress_intent(intent_context)
            if intent_parse_result.error and trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.INTENT_RESOLUTION_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="intent_resolution",
                    input_summary=intent_context.to_dict(),
                    output_summary=intent_parse_result.to_dict(),
                    reasoning=intent_parse_result.error,
                    error=intent_parse_result.error,
                )

            intent_decision = intent_parse_result.decision or infer_intent_resolution_fallback(intent_context)
            intent_application_plan = build_intent_resolution_application_plan(
                intent_decision,
                intent_context,
            )
            if trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.INTENT_RESOLUTION_DECIDED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action=intent_decision.progress_intent.value,
                    input_summary={
                        "user_message": state.user_message,
                        "current_task_type": intent_context.current_task_type,
                        "recovered_target_summary": dict(intent_context.recovered_target_summary),
                    },
                    output_summary={
                        "deliverable_intent": intent_decision.deliverable_intent.value,
                        "progress_intent": intent_decision.progress_intent.value,
                        "confidence": intent_decision.confidence,
                        "decision": intent_decision.to_dict(),
                        "application_plan": intent_application_plan.to_dict(),
                    },
                    confidence=intent_decision.confidence,
                    reasoning=intent_decision.reason or "Resolved the bounded deliverable/progress intent.",
                )

            self._apply_intent_resolution_plan(
                state,
                intent_context,
                intent_decision,
                intent_application_plan,
                trace_obj=trace_obj,
            )
            if intent_application_plan.reset_current_task_context:
                forced_continuation_decision = None
            skip_generic_new_task_reset = True
            if state.stage == TaskStage.NEEDS_CLARIFICATION:
                return
        else:
            state.set_latest_intent_resolution_decision(None)
            state.set_latest_intent_resolution_plan(None)
            self._clear_live_intent_resolution_state()
            if trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.INTENT_RESOLUTION_SKIPPED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="intent_resolution",
                    input_summary={
                        "user_message": state.user_message,
                        "incoming_file_path": state.incoming_file_path,
                    },
                    reasoning=intent_resolution_reason,
                )

        is_new_task, _signal, _reason = (
            (False, None, None)
            if skip_generic_new_task_reset
            else self._is_new_task_request(state)
        )
        if is_new_task:
            if state.residual_reentry_context is not None and trace_obj is not None:
                skip_decision = ReentryDecision(
                    should_apply=False,
                    decision_status="skipped",
                    reason="The user explicitly started a new task, so recovered-workflow re-entry bias was skipped.",
                    target=state.residual_reentry_context.reentry_target,
                    source=state.residual_reentry_context.reentry_target.source,
                    new_task_override=True,
                    residual_plan_exists=isinstance(self._ensure_live_continuation_bundle().get("plan"), dict),
                )
                self._record_residual_reentry_decision(state, skip_decision, trace_obj=trace_obj)
            self._reset_state_for_new_task_direction(
                state,
                clear_residual_workflow=False,
            )
            forced_continuation_decision = None

        self._seed_explicit_message_parameter_locks(state)

        if self._maybe_apply_summary_delivery_surface(state, trace_obj=trace_obj):
            return

        file_context = self._build_state_file_context(state)

        context = self.assembler.assemble(
            user_message=state.user_message or "",
            working_memory=self.memory.get_working_memory(),
            fact_memory=self.memory.get_fact_memory(),
            file_context=file_context,
            context_summary=self._get_context_summary(),
            memory_context=self._get_memory_context_for_prompt(),
        )
        setattr(state, "_assembled_context", context)

        available_tokens = self._collect_available_result_tokens(state)
        state.execution.available_results.update(available_tokens)

        continuation_decision = forced_continuation_decision or self._should_continue_residual_plan(state)
        continuation_decision = self._apply_intent_bias_to_continuation_decision(
            state,
            continuation_decision,
        )
        geometry_recovery_authoritative = (
            forced_continuation_decision is not None
            and forced_continuation_decision.signal in {"geometry_recovery_resume", "geometry_recovery_waiting"}
            and continuation_decision.residual_plan_exists
        )
        if continuation_decision.should_continue or geometry_recovery_authoritative:
            self._activate_live_continuation_state(state, continuation_decision)
        if continuation_decision.should_continue:
            should_replan, replan_reason = self._should_replan_on_continuation(state, continuation_decision)
            continuation_decision.should_replan = should_replan
            if should_replan:
                continuation_decision.reason = (
                    f"{continuation_decision.reason}. Controlled replan allowed: {replan_reason}"
                )
                state.set_plan(None)
            else:
                continuation_decision.reason = (
                    f"{continuation_decision.reason}. {replan_reason}"
                )
        self._record_continuation_decision(state, continuation_decision, trace_obj=trace_obj)
        if continuation_decision.should_continue:
            self._inject_continuation_guidance(
                context,
                state,
                continuation_decision,
                trace_obj=trace_obj,
            )
        self._inject_parameter_confirmation_guidance(context, state)
        self._inject_input_completion_guidance(context, state)
        self._inject_intent_resolution_guidance(context, state)
        reentry_decision = self._build_residual_reentry_decision(state, continuation_decision)
        if reentry_decision is not None:
            self._record_residual_reentry_decision(state, reentry_decision, trace_obj=trace_obj)
            self._inject_residual_reentry_guidance(
                context,
                state,
                reentry_decision,
                trace_obj=trace_obj,
            )

        if getattr(self.runtime_config, "enable_workflow_templates", False) and (
            continuation_decision.should_continue or state.file_context.grounded
        ):
            if continuation_decision.should_continue:
                self._record_workflow_template_selection(
                    state,
                    TemplateSelectionResult(
                        recommended_template_id=None,
                        recommendations=[],
                        selection_reason="Residual continuation remained authoritative, so fresh template recommendation was skipped.",
                        template_prior_used=False,
                    ),
                    trace_obj=trace_obj,
                )
            elif forced_continuation_decision is not None and forced_continuation_decision.signal == "parameter_confirmation_resume":
                self._record_workflow_template_selection(
                    state,
                    TemplateSelectionResult(
                        recommended_template_id=None,
                        recommendations=[],
                        selection_reason="Parameter confirmation resumed the current task, so fresh template recommendation was skipped.",
                        template_prior_used=False,
                    ),
                    trace_obj=trace_obj,
                )
            elif (
                forced_continuation_decision is not None
                and forced_continuation_decision.signal in {"geometry_recovery_resume", "geometry_recovery_waiting"}
            ):
                self._record_workflow_template_selection(
                    state,
                    TemplateSelectionResult(
                        recommended_template_id=None,
                        recommendations=[],
                        selection_reason="Geometry recovery kept the residual workflow authoritative, so fresh template recommendation was skipped.",
                        template_prior_used=False,
                    ),
                    trace_obj=trace_obj,
                )
            else:
                file_signals = self._get_workflow_template_signals(state)
                if not isinstance(file_signals, dict) or not state.file_context.grounded:
                    self._record_workflow_template_selection(
                        state,
                        TemplateSelectionResult(
                            recommended_template_id=None,
                            recommendations=[],
                            selection_reason="No grounded file context was available for workflow template recommendation.",
                            template_prior_used=False,
                        ),
                        trace_obj=trace_obj,
                    )
                elif state.file_context.task_type not in {"macro_emission", "micro_emission"}:
                    self._record_workflow_template_selection(
                        state,
                        TemplateSelectionResult(
                            recommended_template_id=None,
                            recommendations=[],
                            selection_reason=(
                                f"Workflow templates were skipped because task_type={state.file_context.task_type or 'unknown'} "
                                "did not support a bounded domain prior."
                            ),
                            template_prior_used=False,
                        ),
                        trace_obj=trace_obj,
                    )
                else:
                    selection = self._recommend_workflow_template_prior(state)
                    self._record_workflow_template_selection(state, selection, trace_obj=trace_obj)

        if self._should_generate_plan(state):
            plan = await self._generate_execution_plan(state)
            if plan is not None:
                state.set_plan(plan)
                template_alignment = self._summarize_template_prior_alignment(
                    plan,
                    state.selected_workflow_template,
                )
                if trace_obj:
                    trace_obj.record(
                        step_type=TraceStepType.PLAN_CREATED,
                        stage_before=TaskStage.INPUT_RECEIVED.value,
                        action="generate_execution_plan",
                        output_summary={
                            "goal": plan.goal,
                            "step_count": len(plan.steps),
                            "selected_template_id": (
                                state.selected_workflow_template.template_id
                                if state.selected_workflow_template
                                else None
                            ),
                            "steps": [
                                {
                                    "step_id": step.step_id,
                                    "tool_name": step.tool_name,
                                    "depends_on": list(step.depends_on),
                                    "produces": list(step.produces),
                                }
                                for step in plan.steps
                            ],
                        },
                        reasoning=" ".join(
                            item
                            for item in [
                                plan.planner_notes or "Structured plan generated from grounded request.",
                                template_alignment,
                            ]
                            if item
                        ),
                    )
                validation = self._validate_execution_plan(state)
                if validation is not None and trace_obj:
                    trace_obj.record(
                        step_type=TraceStepType.PLAN_VALIDATED,
                        stage_before=TaskStage.INPUT_RECEIVED.value,
                        action="validate_execution_plan",
                        output_summary={
                            "plan_status": validation["status"].value,
                            "initial_available_tokens": validation["initial_available_tokens"],
                            "final_available_tokens": validation["final_available_tokens"],
                            "step_statuses": [
                                {
                                    "step_id": item["step_id"],
                                    "tool_name": item["tool_name"],
                                    "status": item["status"].value,
                                }
                                for item in validation["step_results"]
                            ],
                        },
                        reasoning="; ".join(validation["validation_notes"]),
                    )
                self._inject_plan_guidance(
                    context,
                    state.plan,
                    available_tokens=self._collect_available_result_tokens(state),
                )

        response = await self.llm.chat_with_tools(
            messages=context.messages,
            tools=context.tools,
            system=context.system_prompt
        )

        if response.tool_calls:
            state._llm_response = response
            state.execution.selected_tool = response.tool_calls[0].name
            self._capture_tool_call_parameters(state, response.tool_calls)
            if trace_obj:
                tool_names = [tc.name for tc in response.tool_calls]
                trace_obj.record(
                    step_type=TraceStepType.TOOL_SELECTION,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    stage_after=TaskStage.GROUNDED.value,
                    action=", ".join(tool_names),
                    reasoning=f"LLM selected tool(s): {', '.join(tool_names)}",
                )
            self._transition_state(
                state,
                TaskStage.GROUNDED,
                reason="LLM selected tool(s)",
                trace_obj=trace_obj,
            )
        else:
            if not str(response.content or "").strip():
                if self._maybe_recover_missing_tool_call(
                    state,
                    stage_before=TaskStage.INPUT_RECEIVED,
                    trace_obj=trace_obj,
                ):
                    return
            state.execution.tool_results = [{"text": response.content, "no_tool": True}]
            self._transition_state(
                state,
                TaskStage.DONE,
                reason="LLM responded without tool calls",
                trace_obj=trace_obj,
            )

    async def _state_handle_grounded(
        self,
        state: TaskState,
        trace_obj: Optional[Trace] = None,
    ) -> None:
        """Handle GROUNDED state: check if we can proceed to execution."""
        state.execution.available_results.update(self._collect_available_result_tokens(state))
        self._refresh_execution_plan_state(state)

        clarification = self._identify_critical_missing(state)
        if clarification:
            state.control.needs_user_input = True
            state.control.clarification_question = clarification
            self._transition_state(
                state,
                TaskStage.NEEDS_CLARIFICATION,
                reason="Missing critical information",
                trace_obj=trace_obj,
            )
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.CLARIFICATION,
                    stage_before=TaskStage.GROUNDED.value,
                    stage_after=TaskStage.NEEDS_CLARIFICATION.value,
                    reasoning=clarification,
                )
            return

        self._validate_tool_selection_against_plan(state, trace_obj=trace_obj)

        # Check tool dependencies before proceeding to execution
        if state._llm_response and hasattr(state._llm_response, 'tool_calls') and state._llm_response.tool_calls:
            for tc in state._llm_response.tool_calls:
                missing = get_missing_prerequisites(
                    tc.name,
                    state.execution.available_results,
                    tc.arguments,
                )
                if missing:
                    logger.info(
                        "Tool %s selected with unmet prerequisites %s; "
                        "lightweight planning will trace but not auto-complete dependencies in this round.",
                        tc.name,
                        missing,
                    )
                    if state.plan is not None:
                        state.plan.append_validation_note(
                            f"Selected tool '{tc.name}' is missing prerequisites {missing} at grounded check."
                        )

        self._transition_state(
            state,
            TaskStage.EXECUTING,
            reason="All parameters ready",
            trace_obj=trace_obj,
        )

    async def _state_handle_executing(
        self,
        state: TaskState,
        trace_obj: Optional[Trace] = None,
    ) -> None:
        response = state._llm_response
        if not response or not response.tool_calls:
            state.execution.tool_results = [{"text": getattr(response, "content", ""), "no_tool": True}]
            self._transition_state(
                state,
                TaskStage.DONE,
                reason="missing tool calls during execution",
                trace_obj=trace_obj,
            )
            return

        context = getattr(state, "_assembled_context", None)
        if context is None:
            context = self.assembler.assemble(
                user_message=state.user_message or "",
                working_memory=self.memory.get_working_memory(),
                fact_memory=self.memory.get_fact_memory(),
                file_context=self._build_state_file_context(state),
                context_summary=self._get_context_summary(),
                memory_context=self._get_memory_context_for_prompt(),
            )
            setattr(state, "_assembled_context", context)

        conversation_messages = list(context.messages)
        current_response = response
        rounds_used = 1
        dependency_blocked = False
        repair_halted = False

        while current_response and current_response.tool_calls and not dependency_blocked and not repair_halted:
            cycle_results: List[Dict[str, Any]] = []

            for tool_call in current_response.tool_calls:
                logger.info(f"Executing tool: {tool_call.name}")
                logger.debug(f"Tool arguments: {tool_call.arguments}")

                reconciliation = self._reconcile_plan_before_execution(
                    state,
                    tool_call.name,
                    trace_obj=trace_obj,
                )
                planned_step = reconciliation.get("planned_step")
                if reconciliation.get("deviation_type"):
                    trigger_context = self._build_repair_trigger_context(
                        state,
                        trigger_type=RepairTriggerType.PLAN_DEVIATION,
                        trigger_reason=reconciliation.get("note") or "Execution deviated from the current plan.",
                        actual_tool_name=tool_call.name,
                        deviation_type=reconciliation.get("deviation_type"),
                        planned_step=planned_step,
                        next_step=reconciliation.get("next_step"),
                    )
                    should_repair, repair_reason = self._should_attempt_plan_repair(state, trigger_context)
                    if should_repair:
                        repaired, decision, validation, failure_reason = await self._attempt_plan_repair(
                            state,
                            trigger_context,
                            trace_obj=trace_obj,
                        )
                        repair_halted = True
                        setattr(
                            state,
                            "_final_response_text",
                            (
                                self._build_plan_repair_response_text(trigger_context, decision, validation)
                                if repaired
                                else self._build_plan_repair_failure_text(
                                    trigger_context,
                                    failure_reason or "repair validation failed",
                                )
                            ),
                        )
                        break
                    if trace_obj:
                        trace_obj.record(
                            step_type=TraceStepType.PLAN_REPAIR_SKIPPED,
                            stage_before=TaskStage.EXECUTING.value,
                            action=tool_call.name,
                            input_summary=trigger_context.to_dict(),
                            reasoning=repair_reason,
                        )

                effective_arguments = self._prepare_tool_arguments(
                    tool_call.name,
                    tool_call.arguments,
                    state=state,
                )
                if self._evaluate_missing_parameter_preflight(
                    state,
                    tool_call.name,
                    effective_arguments=effective_arguments,
                    trace_obj=trace_obj,
                ):
                    return
                if self._evaluate_cross_constraint_preflight(
                    state,
                    tool_call.name,
                    effective_arguments,
                    trace_obj=trace_obj,
                ):
                    return
                readiness_assessment, readiness_affordance = self._assess_selected_action_readiness(
                    tool_name=tool_call.name,
                    arguments=effective_arguments,
                    tool_results=state.execution.tool_results,
                    state=state,
                    trace_obj=trace_obj,
                    stage_before=TaskStage.EXECUTING.value,
                    purpose="pre_execution",
                )
                force_explicit_execution = (
                    readiness_affordance is not None
                    and readiness_affordance.status == ReadinessStatus.ALREADY_PROVIDED
                    and self._should_force_explicit_tool_execution(
                        state,
                        tool_call.name,
                    )
                )
                if (
                    readiness_affordance is not None
                    and self._should_short_circuit_readiness(readiness_affordance)
                    and not force_explicit_execution
                ):
                    state.execution.blocked_info = self._build_action_readiness_block_payload(readiness_affordance)
                    state.execution.last_error = state.execution.blocked_info["message"]
                    completion_request = None
                    if readiness_affordance.status == ReadinessStatus.REPAIRABLE:
                        completion_request = self._build_input_completion_request(
                            state,
                            readiness_affordance,
                        )
                    if completion_request is not None:
                        state.append_plan_note(
                            f"Repairable action '{tool_call.name}' entered structured input completion.",
                            step_id=getattr(planned_step, "step_id", None),
                            tool_name=None if planned_step is not None else tool_call.name,
                            reconciliation=True,
                        )
                        self._activate_input_completion_state(
                            state,
                            completion_request,
                            readiness_affordance,
                            trace_obj=trace_obj,
                        )
                        return
                    self._mark_blocked_plan_step(
                        state,
                        tool_call.name,
                        state.execution.last_error,
                        planned_step=planned_step,
                    )
                    if readiness_affordance.status == ReadinessStatus.ALREADY_PROVIDED:
                        setattr(
                            state,
                            "_final_response_text",
                            build_action_already_provided_response(
                                readiness_affordance,
                                readiness_assessment or ReadinessAssessment(),
                            ),
                        )
                    elif readiness_affordance.status == ReadinessStatus.REPAIRABLE:
                        setattr(
                            state,
                            "_final_response_text",
                            build_action_repairable_response(
                                readiness_affordance,
                                readiness_assessment or ReadinessAssessment(),
                            ),
                        )
                    else:
                        setattr(
                            state,
                            "_final_response_text",
                            build_action_blocked_response(
                                readiness_affordance,
                                readiness_assessment or ReadinessAssessment(),
                            ),
                        )
                    dependency_blocked = True
                    break
                dependency_validation = self._validate_execution_dependencies(
                    state,
                    tool_call.name,
                    effective_arguments,
                    trace_obj=trace_obj,
                )
                if not dependency_validation.is_valid:
                    dependency_blocked = True
                    blocked_payload = dependency_validation.to_dict()
                    if planned_step is not None:
                        blocked_payload["step_id"] = planned_step.step_id
                    state.execution.blocked_info = blocked_payload
                    state.execution.last_error = dependency_validation.message
                    self._mark_blocked_plan_step(
                        state,
                        tool_call.name,
                        dependency_validation.message,
                        planned_step=planned_step,
                    )
                    trigger_context = self._build_repair_trigger_context(
                        state,
                        trigger_type=RepairTriggerType.DEPENDENCY_BLOCKED,
                        trigger_reason=dependency_validation.message,
                        actual_tool_name=tool_call.name,
                        planned_step=planned_step,
                        next_step=reconciliation.get("next_step"),
                        dependency_validation=dependency_validation,
                    )
                    should_repair, repair_reason = self._should_attempt_plan_repair(state, trigger_context)
                    if should_repair:
                        repaired, decision, validation, failure_reason = await self._attempt_plan_repair(
                            state,
                            trigger_context,
                            trace_obj=trace_obj,
                        )
                        setattr(
                            state,
                            "_final_response_text",
                            (
                                self._build_plan_repair_response_text(trigger_context, decision, validation)
                                if repaired
                                else self._build_plan_repair_failure_text(
                                    trigger_context,
                                    failure_reason or "repair validation failed",
                                )
                            ),
                        )
                    else:
                        if trace_obj:
                            trace_obj.record(
                                step_type=TraceStepType.PLAN_REPAIR_SKIPPED,
                                stage_before=TaskStage.EXECUTING.value,
                                action=tool_call.name,
                                input_summary=trigger_context.to_dict(),
                                reasoning=repair_reason,
                            )
                        setattr(
                            state,
                            "_final_response_text",
                            self._build_dependency_blocked_response_text(state, dependency_validation),
                        )
                    break

                tool_start_time = time.time()
                result = await self.executor.execute(
                    tool_name=tool_call.name,
                    arguments=effective_arguments,
                    file_path=state.file_context.file_path
                )
                elapsed_ms = round((time.time() - tool_start_time) * 1000, 1)

                logger.info(
                    "Tool %s completed. Success: %s, Error: %s",
                    tool_call.name,
                    result.get("success"),
                    result.get("error"),
                )
                if result.get("error"):
                    logger.error("Tool error message: %s", result.get("message", "No message"))

                tool_result = {
                    "tool_call_id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                    "result": result
                }
                cycle_results.append(tool_result)
                state.execution.tool_results.append(tool_result)
                state.execution.completed_tools.append(tool_call.name)
                self._save_result_to_session_context(tool_call.name, result)

                if result.get("success"):
                    state.execution.available_results.update(get_tool_provides(tool_call.name))
                completed_plan_step = self._update_plan_after_tool_execution(state, tool_call.name, result)
                self._refresh_execution_plan_state(state)
                if trace_obj and result.get("success") and completed_plan_step is not None:
                    trace_obj.record(
                        step_type=TraceStepType.PLAN_STEP_COMPLETED,
                        stage_before=TaskStage.EXECUTING.value,
                        action=tool_call.name,
                        input_summary={
                            "step_id": completed_plan_step.step_id,
                            "tool_name": tool_call.name,
                            "execution_success": True,
                        },
                        output_summary={
                            "produced_tokens": get_tool_provides(tool_call.name),
                            "available_tokens": sorted(state.execution.available_results),
                        },
                        reasoning=(
                            f"Completed planned step {completed_plan_step.step_id} via {tool_call.name}."
                        ),
                    )

                std_records = result.get("_standardization_records", [])
                if trace_obj and std_records:
                    std_summary_parts = []
                    for rec in std_records:
                        param = rec.get("param", "?")
                        original = rec.get("original", "?")
                        normalized = rec.get("normalized", original)
                        strategy = rec.get("strategy", "?")
                        confidence = rec.get("confidence", 0)

                        if original != normalized:
                            std_summary_parts.append(
                                f"{param}: '{original}' → '{normalized}' ({strategy}, conf={confidence:.2f})"
                            )
                        else:
                            std_summary_parts.append(
                                f"{param}: '{original}' ✓ ({strategy}, conf={confidence:.2f})"
                            )

                    if std_summary_parts:
                        trace_obj.record(
                            step_type=TraceStepType.PARAMETER_STANDARDIZATION,
                            stage_before=TaskStage.EXECUTING.value,
                            action="standardize_parameters",
                            reasoning="; ".join(std_summary_parts),
                            standardization_records=std_records,
                        )

                if result.get("error") and result.get("error_type") == "standardization":
                    error_msg = result.get("message", "Parameter standardization failed")
                    negotiation_request = self._build_parameter_negotiation_request(tool_call.name, result)
                    if negotiation_request is not None:
                        state.execution.last_error = error_msg
                        self._activate_parameter_confirmation_state(
                            state,
                            negotiation_request,
                            trace_obj=trace_obj,
                        )
                        return

                    suggestions = result.get("suggestions", [])
                    clarification = (
                        f"{error_msg}\n\nDid you mean one of these? {', '.join(suggestions[:5])}"
                        if suggestions else error_msg
                    )

                    state.control.needs_user_input = True
                    state.control.parameter_confirmation_prompt = None
                    state.control.clarification_question = clarification
                    state.execution.last_error = error_msg
                    self._transition_state(
                        state,
                        TaskStage.NEEDS_CLARIFICATION,
                        reason="Standardization failed",
                        trace_obj=trace_obj,
                    )

                    if trace_obj:
                        trace_obj.record(
                            step_type=TraceStepType.ERROR,
                            stage_before=TaskStage.EXECUTING.value,
                            stage_after=TaskStage.NEEDS_CLARIFICATION.value,
                            action=tool_call.name,
                            error=error_msg,
                        )
                    return

                if trace_obj:
                    output_info = {"success": result.get("success", False)}
                    if result.get("success"):
                        data = result.get("data", {})
                        if isinstance(data, dict):
                            if "total_emissions" in data:
                                output_info["total_links"] = data.get("summary", {}).get("total_links")
                                output_info["pollutants"] = list(data.get("total_emissions", {}).keys())
                            elif "speed_data" in data or "curve" in str(data):
                                output_info["data_points"] = data.get("data_count") or data.get("speed_data", {}).get("count")
                        output_info["message"] = str(result.get("message", ""))[:100]
                    else:
                        output_info["error"] = str(result.get("message", ""))[:200]

                    trace_obj.record(
                        step_type=TraceStepType.TOOL_EXECUTION,
                        stage_before=TaskStage.EXECUTING.value,
                        action=tool_call.name,
                        input_summary={
                            "arguments": {
                                key: str(value)[:80]
                                for key, value in (tool_call.arguments or {}).items()
                            }
                        },
                        output_summary=output_info,
                        confidence=None,
                        reasoning=result.get("summary", ""),
                        duration_ms=elapsed_ms,
                        standardization_records=std_records or None,
                        error=result.get("message") if result.get("error") else None,
                    )

            if dependency_blocked or repair_halted:
                break

            if not cycle_results:
                break

            has_error = any(item["result"].get("error") for item in cycle_results)
            if has_error:
                state.execution.last_error = self._format_tool_errors(cycle_results)

            self._append_tool_messages_for_llm(conversation_messages, current_response, cycle_results)
            context.messages = conversation_messages

            if rounds_used >= state.control.max_steps:
                logger.info(
                    "Reached max orchestration steps (%s); finalizing with current tool results",
                    state.control.max_steps,
                )
                if has_error and state.execution.last_error and not getattr(state, "_final_response_text", None):
                    setattr(state, "_final_response_text", state.execution.last_error)
                break

            follow_up_response = await self.llm.chat_with_tools(
                messages=conversation_messages,
                tools=context.tools,
                system=context.system_prompt,
            )
            state._llm_response = follow_up_response

            if follow_up_response.tool_calls:
                state.execution.selected_tool = follow_up_response.tool_calls[0].name
                self._capture_tool_call_parameters(state, follow_up_response.tool_calls)
                if trace_obj:
                    tool_names = [tc.name for tc in follow_up_response.tool_calls]
                    reason = "LLM selected next tool(s) after tool results"
                    if has_error:
                        reason = "LLM selected tool(s) after tool error feedback"
                    trace_obj.record(
                        step_type=TraceStepType.TOOL_SELECTION,
                        stage_before=TaskStage.EXECUTING.value,
                        stage_after=TaskStage.EXECUTING.value,
                        action=", ".join(tool_names),
                        reasoning=f"{reason}: {', '.join(tool_names)}",
                    )
                current_response = follow_up_response
                rounds_used += 1
                continue

            if follow_up_response.content:
                setattr(state, "_final_response_text", follow_up_response.content)
            elif self._maybe_recover_missing_tool_call(
                state,
                stage_before=TaskStage.EXECUTING,
                trace_obj=trace_obj,
            ):
                if state.stage == TaskStage.EXECUTING and state._llm_response and state._llm_response.tool_calls:
                    current_response = state._llm_response
                    rounds_used += 1
                    continue
                return
            elif has_error and state.execution.last_error and not getattr(state, "_final_response_text", None):
                setattr(state, "_final_response_text", state.execution.last_error)
            break

        has_spatial_data = False
        has_map_data_from_tool = False
        available_pollutants: set = set()
        for r in state.execution.tool_results:
            actual = r.get("result", r) if isinstance(r, dict) else r
            if not isinstance(actual, dict):
                continue
            if actual.get("map_data"):
                has_map_data_from_tool = True
            if not actual.get("success"):
                continue
            data = actual.get("data", {})
            if not isinstance(data, dict):
                continue
            for link in data.get("results", [])[:5]:
                if isinstance(link, dict):
                    if link.get("geometry"):
                        has_spatial_data = True
                    available_pollutants.update(
                        link.get("total_emissions_kg_per_hr", {}).keys()
                    )

        already_visualized = "render_spatial_map" in state.execution.completed_tools

        if has_spatial_data and not already_visualized and not has_map_data_from_tool:
            logger.info("Spatial data detected, will suggest visualization to user")
            state.execution._visualization_available = True
            state.execution._available_pollutants = sorted(available_pollutants)

        self._transition_state(
            state,
            TaskStage.DONE,
            reason="execution completed",
            trace_obj=trace_obj,
        )

    async def _state_build_response(
        self,
        state: TaskState,
        user_message: str,
        trace_obj: Optional[Trace] = None,
    ) -> RouterResponse:
        if state.stage == TaskStage.NEEDS_INPUT_COMPLETION:
            response = RouterResponse(
                text=self._sanitize_response_text(
                    state.control.input_completion_prompt
                    or "Please resolve the structured input completion request before execution."
                ),
            )
            if trace_obj:
                trace_obj.finish(final_stage=state.stage.value)
                response.trace = trace_obj.to_dict()
                response.trace_friendly = trace_obj.to_user_friendly()
            return response

        if state.stage == TaskStage.NEEDS_PARAMETER_CONFIRMATION:
            response = RouterResponse(
                text=self._sanitize_response_text(
                    state.control.parameter_confirmation_prompt
                    or "Please confirm the parameter candidate before execution."
                ),
            )
            if trace_obj:
                trace_obj.finish(final_stage=state.stage.value)
                response.trace = trace_obj.to_dict()
                response.trace_friendly = trace_obj.to_user_friendly()
            return response

        if state.stage == TaskStage.NEEDS_CLARIFICATION:
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.CLARIFICATION,
                    stage_before=TaskStage.NEEDS_CLARIFICATION.value,
                    reasoning=state.control.clarification_question or "More information needed",
                )
            response = RouterResponse(
                text=self._sanitize_response_text(
                    state.control.clarification_question or "Could you provide more details?"
                ),
            )
            if trace_obj:
                trace_obj.finish(final_stage=state.stage.value)
                response.trace = trace_obj.to_dict()
                response.trace_friendly = trace_obj.to_user_friendly()
            return response

        if state.execution.blocked_info:
            frontend_payloads = self._extract_frontend_payloads(state.execution.tool_results)
            response = RouterResponse(
                text=self._sanitize_response_text(
                    getattr(state, "_final_response_text", None)
                    or state.execution.blocked_info.get("message", "Execution blocked by unmet dependencies.")
                ),
                chart_data=frontend_payloads["chart_data"],
                table_data=frontend_payloads["table_data"],
                map_data=frontend_payloads["map_data"],
                download_file=frontend_payloads["download_file"],
                executed_tool_calls=self._build_memory_tool_calls(state.execution.tool_results)
                if state.execution.tool_results
                else None,
            )
            if trace_obj:
                response.trace = trace_obj.to_dict()
                response.trace_friendly = trace_obj.to_user_friendly()
            return response

        if state.repair_history and getattr(state, "_final_response_text", None) and not state.execution.tool_results:
            response = RouterResponse(
                text=self._sanitize_response_text(getattr(state, "_final_response_text", "")),
            )
            if trace_obj:
                response.trace = trace_obj.to_dict()
                response.trace_friendly = trace_obj.to_user_friendly()
            return response

        if getattr(state, "_final_response_text", None) and not state.execution.tool_results:
            response = RouterResponse(
                text=self._sanitize_response_text(getattr(state, "_final_response_text", "")),
            )
            if trace_obj:
                response.trace = trace_obj.to_dict()
                response.trace_friendly = trace_obj.to_user_friendly()
            return response

        if state.execution.tool_results and state.execution.tool_results[0].get("no_tool"):
            response = RouterResponse(
                text=self._sanitize_response_text(state.execution.tool_results[0].get("text", ""))
            )
            if trace_obj:
                response.trace = trace_obj.to_dict()
                response.trace_friendly = trace_obj.to_user_friendly()
            return response

        if state.execution.tool_results:
            context = getattr(state, "_assembled_context", None)
            if context is None:
                context = type("StateContext", (), {"messages": [{"content": user_message}]})()
            response_text = getattr(state, "_final_response_text", None)
            frontend_payloads = self._extract_frontend_payloads(state.execution.tool_results)
            capability_summary = self._build_capability_summary_for_synthesis(
                state.execution.tool_results,
                state=state,
                frontend_payloads=frontend_payloads,
                trace_obj=trace_obj,
                stage_before=TaskStage.DONE.value,
            )
            if response_text:
                if trace_obj:
                    synthesis_reason = "LLM produced final response after receiving tool results"
                    if state.latest_summary_delivery_result is not None:
                        synthesis_reason = (
                            "Bounded summary delivery surface produced the final response and payloads."
                        )
                    trace_obj.record(
                        step_type=TraceStepType.SYNTHESIS,
                        stage_before=TaskStage.DONE.value,
                        reasoning=synthesis_reason,
                    )
            else:
                synthesis_context = type("StateContext", (), {"messages": [{"content": user_message}]})()
                response_text = await self._synthesize_results(
                    synthesis_context,
                    state._llm_response,
                    state.execution.tool_results,
                    capability_summary=capability_summary,
                )
                if trace_obj and response_text:
                    synthesis_desc = self._build_synthesis_trace_description(state)
                    trace_obj.record(
                        step_type=TraceStepType.SYNTHESIS,
                        stage_before=TaskStage.DONE.value,
                        reasoning=synthesis_desc,
                    )
            chart_data = frontend_payloads["chart_data"]
            table_data = frontend_payloads["table_data"]
            map_data = frontend_payloads["map_data"]
            download_file = frontend_payloads["download_file"]

            response = RouterResponse(
                text=self._sanitize_response_text(response_text),
                chart_data=chart_data,
                table_data=table_data,
                map_data=map_data,
                download_file=download_file,
                executed_tool_calls=self._build_memory_tool_calls(state.execution.tool_results),
            )

            # Append visualization suggestion if spatial data was detected
            # and the single-tool renderer did not already provide follow-up guidance.
            single_tool_name = None
            if len(state.execution.tool_results) == 1:
                single_tool_name = state.execution.tool_results[0].get("name")

            if (
                getattr(state.execution, '_visualization_available', False)
                and not map_data
                and single_tool_name != "calculate_macro_emission"
                and capability_summary is None
            ):
                pollutants = getattr(state.execution, '_available_pollutants', [])
                pollutant_options = "、".join(pollutants) if pollutants else "CO2, NOx"
                first_pol = pollutants[0] if pollutants else "CO2"
                viz_suggestion = (
                    "\n\n---\n"
                    f"📍 **检测到空间数据，可以进行地图可视化**\n\n"
                    f"可用污染物：{pollutant_options}\n\n"
                    f"您可以说：\n"
                    f'- "帮我可视化 {first_pol} 的排放分布"\n'
                    f'- "在地图上展示所有污染物"\n'
                    f'- "不需要可视化"'
                )
                response.text = self._sanitize_response_text(response.text + viz_suggestion)

            self._record_delivered_artifacts(
                state,
                response,
                trace_obj=trace_obj,
                stage_before=TaskStage.DONE.value,
            )

            if trace_obj:
                response.trace = trace_obj.to_dict()
                response.trace_friendly = trace_obj.to_user_friendly()
            return response

        response = RouterResponse(
            text=self._sanitize_response_text("I wasn't able to process your request. Could you try again?")
        )
        if trace_obj:
            response.trace = trace_obj.to_dict()
            response.trace_friendly = trace_obj.to_user_friendly()
        return response

    def _build_synthesis_trace_description(self, state: TaskState) -> str:
        """Build a user-friendly synthesis trace description from executed tools."""
        result_summary_parts: List[str] = []

        for tool_result in state.execution.tool_results:
            if not isinstance(tool_result, dict):
                continue
            tool_name = str(tool_result.get("name", ""))
            result = tool_result.get("result", {})
            if not isinstance(result, dict) or not result.get("success"):
                continue
            description = self._describe_successful_tool_for_trace(
                tool_name=tool_name,
                result=result,
                arguments=tool_result.get("arguments", {}),
            )
            if description:
                result_summary_parts.append(description)

        if result_summary_parts:
            return "; ".join(result_summary_parts)

        completed_tools = state.execution.completed_tools
        if "calculate_macro_emission" in completed_tools:
            return "Macro emission calculation completed"
        if "calculate_micro_emission" in completed_tools:
            return "Micro emission calculation completed"
        if "render_spatial_map" in completed_tools:
            return "Spatial map rendered"
        if "query_emission_factors" in completed_tools:
            return "Emission factor query completed"

        tool_names = ", ".join(completed_tools) if completed_tools else "Analysis"
        return f"{tool_names} completed"

    def _describe_successful_tool_for_trace(
        self,
        tool_name: str,
        result: Dict[str, Any],
        arguments: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Describe one successful tool execution for the synthesis trace."""
        arguments = arguments if isinstance(arguments, dict) else {}
        data = result.get("data", {})
        data = data if isinstance(data, dict) else {}

        if tool_name == "calculate_macro_emission":
            summary = data.get("summary", {})
            summary = summary if isinstance(summary, dict) else {}
            n_links = summary.get("total_links")
            if n_links is None and isinstance(data.get("results"), list):
                n_links = len(data["results"])

            pollutants = data.get("query_info", {}).get("pollutants", [])
            if not isinstance(pollutants, list) or not pollutants:
                total_emissions = summary.get("total_emissions_kg_per_hr", {})
                if isinstance(total_emissions, dict):
                    pollutants = list(total_emissions.keys())

            details: List[str] = []
            if n_links is not None:
                details.append(f"{n_links} road links")
            if pollutants:
                details.append(f"pollutants: {', '.join(str(pol) for pol in pollutants)}")
            return "Macro emission calculation completed" + (f": {', '.join(details)}" if details else "")

        if tool_name == "calculate_micro_emission":
            result_rows = data.get("results", [])
            if isinstance(result_rows, list) and result_rows:
                return f"Micro emission calculation completed: {len(result_rows)} trajectory records"
            return "Micro emission calculation completed"

        if tool_name == "render_spatial_map":
            map_data = result.get("map_data")
            if not isinstance(map_data, dict):
                map_data = data.get("map_config")
            map_data = map_data if isinstance(map_data, dict) else {}

            summary = map_data.get("summary", {})
            summary = summary if isinstance(summary, dict) else {}
            n_features = summary.get("total_links")
            if n_features is None and isinstance(map_data.get("links"), list):
                n_features = len(map_data["links"])

            pollutant = map_data.get("pollutant") or arguments.get("pollutant")
            details: List[str] = []
            if n_features is not None:
                details.append(f"{n_features} features")
            if pollutant:
                details.append(str(pollutant))
            return "Map rendered" + (f": {', '.join(details)}" if details else "")

        if tool_name == "query_emission_factors":
            vehicle = data.get("vehicle_type")
            year = data.get("model_year")
            if vehicle and year is not None:
                return f"Emission factor query completed: {vehicle} ({year})"
            return "Emission factor query completed"

        if tool_name == "analyze_file":
            task_type = data.get("task_type") or data.get("detected_type")
            if task_type:
                return f"File analysis completed: {task_type}"
            return "File analysis completed"

        if tool_name == "query_knowledge":
            return "Knowledge query completed"

        return f"{tool_name or 'Tool'} completed"

    async def _process_response(
        self,
        response,
        context,
        file_path: Optional[str],
        tool_call_count: int = 0,
        trace: Optional[Dict[str, Any]] = None,
    ) -> RouterResponse:
        """
        Process LLM response

        Handles:
        - Direct responses (no tools)
        - Tool calls (execute and synthesize)
        - Errors (retry or friendly message)
        """
        # Case 1: Direct response (no tool calls)
        if not response.tool_calls:
            return RouterResponse(
                text=self._sanitize_response_text(response.content),
                executed_tool_calls=None,
            )

        # Case 2: Too many retries
        if tool_call_count >= self.MAX_TOOL_CALLS_PER_TURN:
            return RouterResponse(
                text=self._sanitize_response_text(
                    "I tried several approaches but encountered some issues. "
                    "Could you please provide more details about what you need?"
                )
            )

        # Case 3: Execute tool calls
        tool_results = []
        for tool_call in response.tool_calls:
            logger.info(f"Executing tool: {tool_call.name}")
            logger.debug(f"Tool arguments: {tool_call.arguments}")

            effective_arguments = self._prepare_tool_arguments(tool_call.name, tool_call.arguments)
            readiness_assessment, readiness_affordance = self._assess_selected_action_readiness(
                tool_name=tool_call.name,
                arguments=effective_arguments,
                tool_results=tool_results,
                state=None,
                trace_obj=None,
                stage_before=TaskStage.EXECUTING.value,
                purpose="pre_execution",
            )
            if readiness_affordance is not None and self._should_short_circuit_readiness(readiness_affordance):
                if readiness_affordance.status == ReadinessStatus.ALREADY_PROVIDED:
                    response_text = build_action_already_provided_response(
                        readiness_affordance,
                        readiness_assessment or ReadinessAssessment(),
                    )
                elif readiness_affordance.status == ReadinessStatus.REPAIRABLE:
                    response_text = build_action_repairable_response(
                        readiness_affordance,
                        readiness_assessment or ReadinessAssessment(),
                    )
                else:
                    response_text = build_action_blocked_response(
                        readiness_affordance,
                        readiness_assessment or ReadinessAssessment(),
                    )
                frontend_payloads = self._extract_frontend_payloads(tool_results)
                return RouterResponse(
                    text=self._sanitize_response_text(response_text),
                    chart_data=frontend_payloads["chart_data"],
                    table_data=frontend_payloads["table_data"],
                    map_data=frontend_payloads["map_data"],
                    download_file=frontend_payloads["download_file"],
                    executed_tool_calls=self._build_memory_tool_calls(tool_results) if tool_results else None,
                )
            result = await self.executor.execute(
                tool_name=tool_call.name,
                arguments=effective_arguments,
                file_path=file_path
            )

            logger.info(f"Tool {tool_call.name} completed. Success: {result.get('success')}, Error: {result.get('error')}")
            if result.get('error'):
                logger.error(f"Tool error message: {result.get('message', 'No message')}")

            tool_results.append({
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
                "result": result
            })
            self._save_result_to_session_context(tool_call.name, result)
        if trace is not None:
            trace.setdefault("tool_execution", []).append({
                "turn": tool_call_count,
                "tool_results": [
                    {
                        "name": item["name"],
                        "arguments": item["arguments"],
                        "success": item["result"].get("success"),
                        "message": item["result"].get("message"),
                        "trace": item["result"].get("_trace"),
                    }
                    for item in tool_results
                ],
            })

        logger.info(f"Collected {len(tool_results)} tool results from {len(response.tool_calls)} tool calls")

        # Check for errors
        has_error = any(r["result"].get("error") for r in tool_results)

        if has_error and tool_call_count < self.MAX_TOOL_CALLS_PER_TURN - 1:
            # Let LLM handle the error (might ask for clarification)
            error_messages = self._format_tool_errors(tool_results)

            # Add tool results to context
            context.messages.append({
                "role": "assistant",
                "content": response.content or "Calling tools...",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": str(tc.arguments)
                        }
                    }
                    for tc in response.tool_calls
                ]
            })
            context.messages.append({
                "role": "tool",
                "content": error_messages,
                "tool_call_id": tool_results[0]["tool_call_id"]
            })

            # Retry with error context
            retry_response = await self.llm.chat_with_tools(
                messages=context.messages,
                tools=context.tools,
                system=context.system_prompt
            )

            return await self._process_response(
                retry_response,
                context,
                file_path,
                tool_call_count=tool_call_count + 1,
                trace=trace,
            )

        # Synthesize results
        frontend_payloads = self._extract_frontend_payloads(tool_results)
        capability_summary = self._build_capability_summary_for_synthesis(
            tool_results,
            frontend_payloads=frontend_payloads,
        )
        synthesis_text = await self._synthesize_results(
            context,
            response,
            tool_results,
            capability_summary=capability_summary,
        )

        # Extract data for frontend
        chart_data = frontend_payloads["chart_data"]
        table_data = frontend_payloads["table_data"]
        map_data = frontend_payloads["map_data"]
        download_file = frontend_payloads["download_file"]

        logger.info(f"[DEBUG EXTRACT] chart_data: {bool(chart_data)}")
        logger.info(f"[DEBUG EXTRACT] table_data: {bool(table_data)}")
        logger.info(f"[DEBUG EXTRACT] map_data: {bool(map_data)}")
        if table_data:
            logger.info(f"[DEBUG EXTRACT] table_data type: {table_data.get('type')}, rows: {len(table_data.get('preview_rows', []))}")
        if map_data:
            if map_data.get("type") == "map_collection":
                logger.info(f"[DEBUG EXTRACT] map_data collection size: {len(map_data.get('items', []))}")
            else:
                logger.info(f"[DEBUG EXTRACT] map_data links: {len(map_data.get('links', []))}")

        return RouterResponse(
            text=self._sanitize_response_text(synthesis_text),
            chart_data=chart_data,
            table_data=table_data,
            map_data=map_data,
            download_file=download_file,
            executed_tool_calls=self._build_memory_tool_calls(tool_results),
        )

    async def _analyze_file(self, file_path: str) -> Dict:
        """Analyze file using file analyzer tool"""
        result = await self.executor.execute(
            tool_name="analyze_file",
            arguments={"file_path": file_path},
            file_path=file_path
        )
        data = result.get("data", {})
        # Add file_path to the data so LLM knows where the file is
        data["file_path"] = file_path
        return data

    async def _synthesize_results(
        self,
        context,
        original_response,
        tool_results: list,
        capability_summary: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        综合工具执行结果，生成自然语言回复
        """
        short_circuit_text = self._maybe_short_circuit_synthesis(
            tool_results,
            capability_summary=capability_summary,
        )
        if short_circuit_text is not None:
            if len(tool_results) == 1 and tool_results[0].get("name") == "query_knowledge":
                logger.info("[知识检索] 直接返回答案，跳过 synthesis")
            elif any(not item.get("result", {}).get("success") for item in tool_results):
                logger.info("[Synthesis] 检测到工具失败，使用确定性格式化结果")
            elif len(tool_results) == 1:
                only_name = tool_results[0].get("name", "unknown")
                only_result = tool_results[0].get("result", {})
                if only_name in {
                    "query_emission_factors",
                    "calculate_micro_emission",
                    "calculate_macro_emission",
                    "calculate_dispersion",
                    "analyze_hotspots",
                    "render_spatial_map",
                    "analyze_file",
                }:
                    logger.info(f"[Synthesis] 单工具成功({only_name})，使用友好渲染")
                elif only_result.get("summary"):
                    logger.info(f"[Synthesis] 单工具成功({only_name})，直接返回工具summary")
                else:
                    logger.info(f"[Synthesis] 单工具成功({only_name})，工具无summary，使用渲染回退")
            return short_circuit_text

        request = self._build_synthesis_request(
            context.messages[-1]["content"] if context.messages else None,
            tool_results,
            capability_summary=capability_summary,
        )
        results_json = request["results_json"]

        logger.info(f"Filtered results for synthesis ({len(results_json)} chars):")
        logger.info(f"{results_json[:500]}...")  # Log first 500 chars
        logger.info("[CapabilityAwareSynthesis] full_synthesis_prompt:\n%s", request["system_prompt"])

        synthesis_response = await self.llm.chat(
            messages=request["messages"],
            system=request["system_prompt"],
        )

        logger.info(f"Synthesis complete. Response length: {len(synthesis_response.content)} chars")

        hallucination_keywords = ["相当于", "棵树", "峰值出现在", "空调导致", "不完全燃烧"]
        for keyword in self._detect_synthesis_hallucination_keywords(
            synthesis_response.content,
            hallucination_keywords,
        ):
            logger.warning(f"⚠️ Possible hallucination detected: '{keyword}' found in response")

        return synthesis_response.content

    def _render_single_tool_success(
        self,
        tool_name: str,
        result: Dict,
        capability_summary: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Compatibility wrapper around extracted rendering helper."""
        return render_single_tool_success_helper(
            tool_name,
            result,
            capability_summary=capability_summary,
        )

    def _filter_results_for_synthesis(self, tool_results: list) -> Dict:
        """Compatibility wrapper around extracted rendering helper."""
        return filter_results_for_synthesis_helper(tool_results)

    def _format_tool_errors(self, tool_results: list) -> str:
        """Compatibility wrapper around extracted rendering helper."""
        return format_tool_errors_helper(tool_results)

    def _format_tool_results(self, tool_results: list) -> str:
        """Compatibility wrapper around extracted rendering helper."""
        return format_tool_results_helper(tool_results)

    def _maybe_short_circuit_synthesis(
        self,
        tool_results: list,
        capability_summary: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Compatibility wrapper around extracted synthesis helper."""
        return maybe_short_circuit_synthesis_helper(
            tool_results,
            capability_summary=capability_summary,
        )

    def _build_synthesis_request(
        self,
        last_user_message: Optional[str],
        tool_results: list,
        capability_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Compatibility wrapper around extracted synthesis helper."""
        return build_synthesis_request_helper(
            last_user_message,
            tool_results,
            SYNTHESIS_PROMPT,
            capability_summary=capability_summary,
        )

    def _detect_synthesis_hallucination_keywords(self, content: str, keywords: list[str]) -> list[str]:
        """Compatibility wrapper around extracted synthesis helper."""
        return detect_hallucination_keywords_helper(content, keywords)

    def _build_memory_tool_calls(self, tool_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Compatibility wrapper around the extracted memory-compaction helper."""
        return build_memory_tool_calls_helper(tool_results)

    def _compact_tool_data(self, data: Any) -> Optional[Dict[str, Any]]:
        """Compatibility wrapper around the extracted memory-compaction helper."""
        return compact_tool_data_helper(data)

    def _format_results_as_fallback(self, tool_results: list) -> str:
        """Compatibility wrapper around extracted rendering helper."""
        return format_results_as_fallback_helper(tool_results)

    def _extract_chart_data(self, tool_results: list) -> Optional[Dict]:
        """Compatibility wrapper around extracted payload helper."""
        return extract_chart_data_helper(tool_results)

    def _format_emission_factors_chart(self, data: Dict) -> Optional[Dict]:
        """Compatibility wrapper around extracted payload helper."""
        return format_emission_factors_chart_helper(data)

    def _extract_table_data(self, tool_results: list) -> Optional[Dict]:
        """Compatibility wrapper around extracted payload helper."""
        return extract_table_data_helper(tool_results)

    def _extract_download_file(self, tool_results: list) -> Optional[Dict]:
        """Compatibility wrapper around extracted payload helper."""
        return extract_download_file_helper(tool_results)

    def _extract_map_data(self, tool_results: list) -> Optional[Dict]:
        """Compatibility wrapper around extracted payload helper."""
        return extract_map_data_helper(tool_results)

    def clear_history(self):
        """Clear conversation history"""
        self.memory.working_memory.clear()
        self.memory.fact_memory = MemoryManager.FactMemory()
        self._ensure_context_store().clear_current_turn()
        self.context_store = SessionContextStore()
        self._ensure_live_continuation_bundle().update(
            {
                "plan": None,
                "repair_history": [],
                "blocked_info": None,
                "file_path": None,
                "latest_repair_summary": None,
                "residual_plan_summary": None,
            }
        )
        self._ensure_live_parameter_negotiation_bundle().update(
            {
                "active_request": None,
                "parameter_snapshot": {},
                "locked_parameters": {},
                "latest_confirmed_parameter": None,
                "file_path": None,
                "plan": None,
                "repair_history": [],
                "blocked_info": None,
                "latest_repair_summary": None,
                "residual_plan_summary": None,
                "original_goal": None,
                "original_user_message": None,
            }
        )
        self._ensure_live_input_completion_bundle().update(
            {
                "active_request": None,
                "overrides": {},
                "latest_decision": None,
                "file_path": None,
                "plan": None,
                "repair_history": [],
                "blocked_info": None,
                "latest_repair_summary": None,
                "residual_plan_summary": None,
                "original_goal": None,
                "original_user_message": None,
                "action_id": None,
                "recovered_file_context": None,
                "supporting_spatial_input": None,
                "geometry_recovery_context": None,
                "readiness_refresh_result": None,
                "residual_reentry_context": None,
            }
        )
        self._ensure_live_file_relationship_bundle().update(
            {
                "latest_decision": None,
                "latest_transition_plan": None,
                "pending_upload_summary": None,
                "pending_upload_analysis": None,
                "pending_primary_summary": None,
                "pending_primary_analysis": None,
                "attached_supporting_file": None,
                "awaiting_clarification": False,
            }
        )
        self._ensure_live_intent_resolution_bundle().update(
            {
                "latest_decision": None,
                "latest_application_plan": None,
            }
        )
        logger.info(f"Cleared history for session {self.session_id}")
