"""
Context Assembler - Assembles context for LLM
No decision-making, just information assembly

Supports two modes:
  - Legacy: loads core.yaml + all TOOL_DEFINITIONS (enable_skill_injection=False)
  - Skill injection: loads core_v3.yaml + SkillInjector (enable_skill_injection=True)
"""
import logging
import json
import yaml
import inspect
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from config import get_config
from services.config_loader import ConfigLoader

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).parent.parent / "config"


@dataclass
class AssembledContext:
    """Assembled context ready for LLM"""
    system_prompt: str
    tools: List[Dict]
    messages: List[Dict]
    estimated_tokens: int
    telemetry: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BlockTelemetry:
    turn: int
    persistent_facts_tokens: int
    completed_aos_tokens: int
    current_ao_tokens: int
    total_block_tokens: int
    num_completed_aos_in_block: int
    num_tool_calls_in_current_ao: int
    persistent_facts_present: bool
    files_in_session_present: bool
    session_confirmed_parameters_present: bool
    cumulative_constraint_violations_present: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn": self.turn,
            "persistent_facts_tokens": self.persistent_facts_tokens,
            "completed_aos_tokens": self.completed_aos_tokens,
            "current_ao_tokens": self.current_ao_tokens,
            "total_block_tokens": self.total_block_tokens,
            "num_completed_aos_in_block": self.num_completed_aos_in_block,
            "num_tool_calls_in_current_ao": self.num_tool_calls_in_current_ao,
            "persistent_facts_present": self.persistent_facts_present,
            "files_in_session_present": self.files_in_session_present,
            "session_confirmed_parameters_present": self.session_confirmed_parameters_present,
            "cumulative_constraint_violations_present": self.cumulative_constraint_violations_present,
        }


class ContextAssembler:
    """
    Context assembler - Assembles all information for LLM

    Design: No decisions, just assembly
    Priority: Core prompt > Tools > Facts > Working memory > File context
    """

    MAX_CONTEXT_TOKENS = 6000  # Conservative limit
    SESSION_STATE_TOKEN_BUDGET = 800

    def __init__(self):
        self.config = ConfigLoader.load_prompts()
        self.all_tool_definitions = ConfigLoader.load_tool_definitions()
        self.runtime_config = get_config()
        self.last_telemetry: Dict[str, Any] = {}

        # Skill injection setup
        if self.runtime_config.enable_skill_injection:
            from core.skill_injector import SkillInjector
            self.skill_injector = SkillInjector()
            self._core_v3_prompt = self._load_prompt_file(
                CONFIG_DIR / "prompts" / "core_v3.yaml"
            )
        else:
            self.skill_injector = None
            self._core_v3_prompt = None

        # Legacy alias
        self.tools = self.all_tool_definitions

    # Max chars to keep per assistant response in working memory
    MAX_ASSISTANT_RESPONSE_CHARS = 300
    MAX_FILE_CONTEXT_COLUMNS_CHARS = 500
    MAX_FILE_CONTEXT_COLUMNS = 20

    @staticmethod
    def _load_prompt_file(path: Path) -> str:
        """Load system_prompt text from a YAML file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return data.get("system_prompt", "")
        except Exception as e:
            logger.error(f"Failed to load prompt file {path}: {e}")
            return ""

    def assemble(
        self,
        user_message: str,
        working_memory: List[Dict],
        fact_memory: Dict,
        file_context: Optional[Dict] = None,
        context_summary: Optional[str] = None,
        memory_context: Optional[str] = None,
        state: Optional[Any] = None,
    ) -> AssembledContext:
        """
        Assemble complete context for LLM.

        Routes to skill-injection or legacy mode based on config.
        """
        if self.runtime_config.enable_skill_injection and self.skill_injector:
            return self._assemble_with_skills(
                user_message, working_memory, fact_memory, file_context, context_summary, memory_context, state
            )
        return self._assemble_legacy(user_message, working_memory, fact_memory, file_context, context_summary, memory_context, state)

    def _assemble_with_skills(
        self,
        user_message: str,
        working_memory: List[Dict],
        fact_memory: Dict,
        file_context: Optional[Dict] = None,
        context_summary: Optional[str] = None,
        memory_context: Optional[str] = None,
        state: Optional[Any] = None,
    ) -> AssembledContext:
        """Assemble context using skill-based prompt injection."""
        has_file = file_context is not None
        used_tokens = 0

        # 1. Detect intents
        intents = self.skill_injector.detect_intents(
            user_message=user_message,
            last_tool_name=fact_memory.get("last_tool_name"),
            file_context=file_context,
            available_results=fact_memory.get("available_results"),
        )
        logger.info(f"Detected intents: {intents}")

        # 2. Layer 1 + Layer 2/3: Core prompt with situational injection
        situational = self.skill_injector.get_situational_prompt(
            intents=intents,
            last_tool_name=fact_memory.get("last_tool_name"),
        )
        system_prompt = self._core_v3_prompt.replace(
            "{situational_prompt}", situational
        )
        if context_summary:
            system_prompt = f"{system_prompt}\n\n{context_summary}"
        if memory_context:
            system_prompt = f"{system_prompt}\n\n{memory_context}"
        system_prompt, session_state_telemetry = self._append_session_state_block(
            system_prompt,
            fact_memory,
            state,
        )
        used_tokens += self._estimate_tokens(system_prompt)

        # 3. Always expose the full tool surface and let the LLM decide.
        tools = list(self.all_tool_definitions)
        tool_names = [t["function"]["name"] for t in tools]
        logger.info(
            f"Injecting {len(tools)} tools (of {len(self.all_tool_definitions)} total): "
            f"{tool_names}"
        )
        used_tokens += self._estimate_tokens(json.dumps(tool_names))

        # 4. Build messages (same logic as legacy)
        messages = self._build_messages(
            user_message, working_memory, fact_memory, file_context, used_tokens
        )
        used_tokens += self._estimate_tokens(str(messages))

        logger.info(
            f"Assembled context (skill mode): ~{used_tokens} tokens, "
            f"{len(messages)} messages, has_file={has_file}, "
            f"intents={intents}, tools={len(tools)}"
        )

        telemetry_payload = {"session_state_block": session_state_telemetry}
        self.last_telemetry = telemetry_payload
        return AssembledContext(
            system_prompt=system_prompt,
            tools=tools,
            messages=messages,
            estimated_tokens=used_tokens,
            telemetry=telemetry_payload,
        )

    def _assemble_legacy(
        self,
        user_message: str,
        working_memory: List[Dict],
        fact_memory: Dict,
        file_context: Optional[Dict] = None,
        context_summary: Optional[str] = None,
        memory_context: Optional[str] = None,
        state: Optional[Any] = None,
    ) -> AssembledContext:
        """
        Assemble complete context for LLM (legacy mode, unchanged behavior).

        Token budget priority:
        1. Core prompt (~200 tokens) - MUST
        2. Tool definitions (~400 tokens) - MUST
        3. Fact memory (~100 tokens) - Important
        4. Working memory (~3000 tokens) - Important
        5. File context (~500 tokens) - When file uploaded, ELEVATED priority
        """
        has_file = file_context is not None
        used_tokens = 0

        # 1. Core prompt (MUST)
        system_prompt = self.config["system_prompt"]
        if context_summary:
            system_prompt = f"{system_prompt}\n\n{context_summary}"
        if memory_context:
            system_prompt = f"{system_prompt}\n\n{memory_context}"
        system_prompt, session_state_telemetry = self._append_session_state_block(
            system_prompt,
            fact_memory,
            state,
        )
        used_tokens += self._estimate_tokens(system_prompt)

        # 2. Tool definitions (MUST)
        tools = self.all_tool_definitions
        used_tokens += 400  # Estimated

        # 3. Build messages
        messages = self._build_messages(
            user_message, working_memory, fact_memory, file_context, used_tokens
        )
        used_tokens += self._estimate_tokens(str(messages))

        logger.info(
            f"Assembled context: ~{used_tokens} tokens, {len(messages)} messages, "
            f"has_file={has_file}, working_memory_turns={len(working_memory)}"
        )

        telemetry_payload = {"session_state_block": session_state_telemetry}
        self.last_telemetry = telemetry_payload
        return AssembledContext(
            system_prompt=system_prompt,
            tools=tools,
            messages=messages,
            estimated_tokens=used_tokens,
            telemetry=telemetry_payload,
        )

    def _append_session_state_block(
        self,
        system_prompt: str,
        fact_memory: Dict,
        state: Optional[Any],
    ) -> tuple[str, Dict[str, Any]]:
        use_ao_block = bool(getattr(self.runtime_config, "enable_ao_block_injection", False))
        use_legacy_block = bool(getattr(self.runtime_config, "enable_session_state_block", False))
        if not use_ao_block and not use_legacy_block:
            return system_prompt, {"enabled": False, "estimated_tokens": 0, "truncated": False, "kind": "none"}

        resolved_state = state or self._infer_task_state_from_call_stack()
        block_kind = "ao" if use_ao_block else "legacy"
        block = self._build_session_state_block(fact_memory, resolved_state)
        budget = (
            int(getattr(self.runtime_config, "ao_block_token_budget", 1200))
            if use_ao_block
            else self.SESSION_STATE_TOKEN_BUDGET
        )
        estimated_tokens = self._estimate_tokens(block)
        truncated = False
        if block_kind == "legacy" and estimated_tokens > budget:
            block = self._build_legacy_session_state_block(
                fact_memory,
                resolved_state,
                max_tool_calls=5,
            )
            estimated_tokens = self._estimate_tokens(block)
            truncated = True
        if estimated_tokens > budget:
            block = self._truncate_session_state_block(block, budget)
            estimated_tokens = self._estimate_tokens(block)
            truncated = True

        block_telemetry = None
        try:
            block_telemetry = self._build_block_telemetry(
                fact_memory,
                resolved_state,
                block_kind=block_kind,
                rendered_block=block,
            )
        except Exception as exc:
            logger.warning("Failed to attach block telemetry: %s", exc)

        return (
            f"{system_prompt}\n\n{block}",
            {
                "enabled": True,
                "estimated_tokens": estimated_tokens,
                "truncated": truncated,
                "state_visible": resolved_state is not None,
                "kind": block_kind,
                "block_telemetry": block_telemetry,
            },
        )

    def _build_session_state_block(
        self,
        fact_memory: Any,
        state: Optional[Any],
        *,
        max_tool_calls: Optional[int] = None,
    ) -> str:
        if getattr(self.runtime_config, "enable_ao_block_injection", False):
            return self._build_ao_session_state_block(fact_memory, state, max_tool_calls=max_tool_calls)
        return self._build_legacy_session_state_block(fact_memory, state, max_tool_calls=max_tool_calls)

    def _build_legacy_session_state_block(
        self,
        fact_memory: Any,
        state: Optional[Any],
        *,
        max_tool_calls: Optional[int] = None,
    ) -> str:
        """Build the Phase 1 legacy State Contract block."""
        memory = self._fact_memory_to_dict(fact_memory)
        locked_parameters = self._locked_parameters_from_state(state)
        if not locked_parameters:
            locked_parameters = dict(memory.get("locked_parameters_display") or {})

        lines: List[str] = ["[Session State]"]
        lines.append("Tools called this session:")
        tool_log = list(memory.get("tool_call_log") or [])
        if max_tool_calls is not None:
            tool_log = tool_log[-max_tool_calls:]
        if tool_log:
            for record in tool_log:
                lines.append(self._format_tool_log_record(record))
        else:
            lines.append("none")

        lines.append("")
        lines.append("Active artifacts: " + self._format_active_artifacts(memory.get("active_artifact_refs") or {}))
        lines.append("Confirmed parameters (locked): " + self._format_locked_parameters(locked_parameters))
        lines.append(
            "Constraint violations seen: "
            + self._format_constraint_violations(memory.get("constraint_violations_seen") or [])
        )
        lines.append("Current turn action required:")
        lines.append(self._derive_current_action_required(state))
        return "\n".join(lines)

    def _build_ao_session_state_block(
        self,
        fact_memory: Any,
        state: Optional[Any],
        *,
        max_tool_calls: Optional[int] = None,
    ) -> str:
        memory = self._fact_memory_to_dict(fact_memory)
        sections = self._build_ao_block_sections(
            memory,
            state,
            max_tool_calls=max_tool_calls or 10,
        )
        block = self._render_ao_block_from_sections(sections)
        budget = int(getattr(self.runtime_config, "ao_block_token_budget", 1200))
        if self._estimate_tokens(block) <= budget:
            return block

        sections["current_lines"] = self._build_current_ao_lines(
            sections.get("current_ao"),
            state,
            max_tool_calls=5,
        )
        block = self._render_ao_block_from_sections(sections)
        if self._estimate_tokens(block) <= budget:
            return block

        sections["completed_lines"] = self._build_completed_ao_lines(
            list(sections.get("completed_aos") or [])[-3:]
        )
        return self._render_ao_block_from_sections(sections)

    @staticmethod
    def _fact_memory_to_dict(fact_memory: Any) -> Dict[str, Any]:
        if isinstance(fact_memory, dict):
            return fact_memory
        if hasattr(fact_memory, "__dict__"):
            payload = dict(getattr(fact_memory, "__dict__", {}))
            if isinstance(payload.get("files_in_session"), list):
                payload["files_in_session"] = [
                    item.to_dict() if hasattr(item, "to_dict") else item
                    for item in payload.get("files_in_session") or []
                ]
            if isinstance(payload.get("ao_history"), list):
                payload["ao_history"] = [
                    item.to_dict() if hasattr(item, "to_dict") else item
                    for item in payload.get("ao_history") or []
                ]
            return payload
        return {}

    def _build_ao_persistent_fact_lines(self, memory: Dict[str, Any]) -> List[str]:
        if not getattr(self.runtime_config, "enable_ao_persistent_facts", True):
            return [
                "Files available: none",
                "Session-confirmed parameters: none",
                "Constraint violations observed: none",
            ]

        files = [
            item for item in memory.get("files_in_session") or []
            if isinstance(item, dict)
        ]
        filenames = [str(item.get("filename") or Path(str(item.get("path") or "")).name).strip() for item in files]
        filenames = [item for item in filenames if item]

        confirmed_parameters = dict(memory.get("session_confirmed_parameters") or {})
        constraints = [
            item
            for item in memory.get("cumulative_constraint_violations") or []
            if isinstance(item, dict)
        ]

        return [
            "Files available: " + (", ".join(filenames[-5:]) if filenames else "none"),
            "Session-confirmed parameters: "
            + (
                ", ".join(f"{key}={value}" for key, value in list(confirmed_parameters.items())[-6:])
                if confirmed_parameters
                else "none"
            ),
            "Constraint violations observed: " + self._format_cumulative_constraints(constraints),
        ]

    def _build_ao_block_sections(
        self,
        memory: Dict[str, Any],
        state: Optional[Any],
        *,
        max_tool_calls: int,
    ) -> Dict[str, Any]:
        ao_history = [
            item for item in memory.get("ao_history") or []
            if isinstance(item, dict)
        ]
        current_ao_id = str(memory.get("current_ao_id") or "").strip() or None
        current_ao = None
        if current_ao_id:
            current_ao = next((item for item in ao_history if item.get("ao_id") == current_ao_id), None)
        if current_ao is None:
            current_ao = next(
                (
                    item for item in reversed(ao_history)
                    if str(item.get("status") or "").lower() in {"active", "revising", "created"}
                ),
                None,
            )
        completed_aos = [
            item
            for item in ao_history
            if str(item.get("status") or "").lower() == "completed"
        ][-5:]
        return {
            "persistent_lines": self._build_ao_persistent_fact_lines(memory),
            "completed_lines": self._build_completed_ao_lines(completed_aos),
            "current_lines": self._build_current_ao_lines(
                current_ao,
                state,
                max_tool_calls=max_tool_calls,
            ),
            "current_ao": current_ao,
            "completed_aos": completed_aos,
        }

    @staticmethod
    def _render_ao_block_from_sections(sections: Dict[str, Any]) -> str:
        return "\n".join(
            [
                "[Session State]",
                "Persistent facts (across all analytical objectives):",
                *(sections.get("persistent_lines") or []),
                "",
                "Completed analytical objectives:",
                *(sections.get("completed_lines") or []),
                "",
                *(sections.get("current_lines") or []),
            ]
        )

    def _build_block_telemetry(
        self,
        fact_memory: Any,
        state: Optional[Any],
        *,
        block_kind: str,
        rendered_block: str,
    ) -> Optional[Dict[str, Any]]:
        if block_kind != "ao":
            return None
        try:
            memory = self._fact_memory_to_dict(fact_memory)
            sections = self._build_ao_block_sections(memory, state, max_tool_calls=10)
            persistent_section = "\n".join(
                [
                    "Persistent facts (across all analytical objectives):",
                    *(sections.get("persistent_lines") or []),
                ]
            )
            completed_section = "\n".join(
                ["Completed analytical objectives:", *(sections.get("completed_lines") or [])]
            )
            current_section = "\n".join(sections.get("current_lines") or [])
            persistent_items = {
                "files": bool(memory.get("files_in_session")),
                "session_confirmed_parameters": bool(memory.get("session_confirmed_parameters")),
                "cumulative_constraint_violations": bool(memory.get("cumulative_constraint_violations")),
            }
            current_ao = sections.get("current_ao") if isinstance(sections.get("current_ao"), dict) else {}
            tool_log = current_ao.get("tool_call_log") if isinstance(current_ao, dict) else []
            telemetry = BlockTelemetry(
                turn=int(memory.get("last_turn_index") or 0) + 1,
                persistent_facts_tokens=self._estimate_tokens(persistent_section),
                completed_aos_tokens=self._estimate_tokens(completed_section),
                current_ao_tokens=self._estimate_tokens(current_section),
                total_block_tokens=self._estimate_tokens(rendered_block),
                num_completed_aos_in_block=len(sections.get("completed_aos") or []),
                num_tool_calls_in_current_ao=min(len(tool_log or []), 10),
                persistent_facts_present=bool(
                    getattr(self.runtime_config, "enable_ao_persistent_facts", True)
                    and any(persistent_items.values())
                ),
                files_in_session_present=persistent_items["files"],
                session_confirmed_parameters_present=persistent_items["session_confirmed_parameters"],
                cumulative_constraint_violations_present=persistent_items["cumulative_constraint_violations"],
            )
            return telemetry.to_dict()
        except Exception as exc:
            logger.warning("Failed to build AO block telemetry: %s", exc)
            return None

    def _build_completed_ao_lines(self, completed_aos: List[Dict[str, Any]]) -> List[str]:
        if not completed_aos:
            return ["none"]
        lines: List[str] = []
        for item in completed_aos[-5:]:
            ao_id = str(item.get("ao_id") or "AO#?")
            objective = self._trim_text(str(item.get("objective_text") or ""), 100)
            artifacts = item.get("artifacts_produced") if isinstance(item.get("artifacts_produced"), dict) else {}
            artifact_text = self._format_artifact_summary(artifacts)
            lines.append(f'[{ao_id}] "{objective}" -> produced {artifact_text}')
        return lines

    def _build_current_ao_lines(
        self,
        current_ao: Optional[Dict[str, Any]],
        state: Optional[Any],
        *,
        max_tool_calls: int,
    ) -> List[str]:
        if not isinstance(current_ao, dict):
            return [
                "Current analytical objective:",
                "[none]",
                "",
                "Current turn action: " + self._derive_current_action_required(state),
            ]

        ao_id = str(current_ao.get("ao_id") or "AO#?")
        status = str(current_ao.get("status") or "unknown").upper()
        objective = self._trim_text(str(current_ao.get("objective_text") or ""), 160)
        relationship = str(current_ao.get("relationship") or "independent").upper()
        parent_ao_id = str(current_ao.get("parent_ao_id") or "").strip() or None
        relationship_text = relationship
        if parent_ao_id:
            relationship_text = f"{relationship} of {parent_ao_id}"

        tool_log = [
            item
            for item in current_ao.get("tool_call_log") or []
            if isinstance(item, dict)
        ][-max_tool_calls:]

        tool_lines = [self._format_tool_log_record(item) for item in tool_log] if tool_log else ["none"]
        metadata = current_ao.get("metadata") if isinstance(current_ao.get("metadata"), dict) else {}
        parameter_snapshot = (
            metadata.get("parameter_snapshot")
            if isinstance(metadata.get("parameter_snapshot"), dict)
            else {}
        )
        clarification_state = (
            metadata.get("clarification_contract")
            if isinstance(metadata.get("clarification_contract"), dict)
            else {}
        )
        return [
            "Current analytical objective:",
            f"[{ao_id} - {status}]",
            f'Objective: "{objective}"',
            f"Relationship: {relationship_text}",
            f"Parameter snapshot: {self._format_parameter_snapshot(parameter_snapshot)}",
            "Tools executed this objective: " + (" | ".join(tool_lines) if tool_lines else "none"),
            (
                "Pending clarification: "
                + str(clarification_state.get("clarification_question") or "").strip()
                if clarification_state.get("pending") and clarification_state.get("clarification_question")
                else "Pending clarification: none"
            ),
            "Current turn action: " + self._derive_current_action_required(state),
        ]

    @staticmethod
    def _trim_text(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    @staticmethod
    def _format_artifact_summary(artifacts: Dict[str, Any]) -> str:
        if not artifacts:
            return "none"
        parts: List[str] = []
        for key, value in list(artifacts.items())[:5]:
            ref_text = str(value or key)
            label = ref_text.split(":", 1)[-1] if ":" in ref_text else ref_text
            parts.append(f"{key}({label})")
        return ", ".join(parts) if parts else "none"

    @staticmethod
    def _format_cumulative_constraints(records: List[Dict[str, Any]]) -> str:
        if not records:
            return "none"
        parts: List[str] = []
        for item in records[-5:]:
            values = item.get("values") if isinstance(item.get("values"), dict) else {}
            value_text = "+".join(str(value) for value in values.values() if value is not None)
            if not value_text:
                value_text = str(item.get("constraint") or "constraint")
            blocked_text = "blocked" if item.get("blocked") else "warned"
            ao_id = str(item.get("ao_id") or "").strip()
            during = f"during {ao_id}, " if ao_id else ""
            parts.append(f"{value_text} ({during}{blocked_text})")
        return "; ".join(parts) if parts else "none"

    @staticmethod
    def _format_parameter_snapshot(snapshot: Dict[str, Any]) -> str:
        if not isinstance(snapshot, dict) or not snapshot:
            return "none"
        parts: List[str] = []
        for slot_name, slot_payload in snapshot.items():
            if not isinstance(slot_payload, dict):
                continue
            source = str(slot_payload.get("source") or "missing")
            value = slot_payload.get("value")
            if value in (None, "", []):
                rendered = "missing"
            elif isinstance(value, list):
                rendered = "[" + ", ".join(str(item) for item in value[:5]) + "]"
            else:
                rendered = str(value)
            parts.append(f"{slot_name}={rendered} [{source}]")
        return ", ".join(parts) if parts else "none"

    def _infer_task_state_from_call_stack(self) -> Optional[Any]:
        frame = inspect.currentframe()
        if frame is None:
            return None
        current = frame.f_back
        for _ in range(8):
            if current is None:
                return None
            candidate = current.f_locals.get("state")
            if candidate is not None and hasattr(candidate, "parameters") and hasattr(candidate, "execution"):
                return candidate
            current = current.f_back
        return None

    @staticmethod
    def _locked_parameters_from_state(state: Optional[Any]) -> Dict[str, Any]:
        if state is None:
            return {}
        parameters = getattr(state, "parameters", None)
        if not isinstance(parameters, dict):
            return {}
        locked: Dict[str, Any] = {}
        for name, entry in parameters.items():
            is_locked = bool(getattr(entry, "locked", False))
            value = getattr(entry, "normalized", None) or getattr(entry, "raw", None)
            if isinstance(entry, dict):
                is_locked = bool(entry.get("locked", is_locked))
                value = entry.get("normalized") or entry.get("raw") or value
            if is_locked and value is not None:
                locked[str(name)] = value
        return locked

    def _format_tool_log_record(self, record: Any) -> str:
        if not isinstance(record, dict):
            return "- malformed tool log record"
        tool = str(record.get("tool") or "unknown")
        args = record.get("args_compact") if isinstance(record.get("args_compact"), dict) else {}
        arg_text = self._format_args_compact(args)
        if len(arg_text) > 220:
            arg_text = arg_text[:217].rstrip() + "..."
        status = "success" if record.get("success") else "failed"
        result_ref = str(record.get("result_ref") or "").strip()
        summary = str(record.get("summary") or "").strip()
        suffix_parts = [status]
        if result_ref:
            suffix_parts.append(f"produced {result_ref.replace(':', '_')}")
        if summary:
            suffix_parts.append(summary[:80])
        return f"{tool}({arg_text}) -> " + ", ".join(suffix_parts)

    @staticmethod
    def _format_args_compact(args: Dict[str, Any]) -> str:
        parts: List[str] = []
        for key, value in args.items():
            if key.startswith("_"):
                continue
            if isinstance(value, list):
                rendered = "[" + ", ".join(str(item) for item in value[:5]) + "]"
            elif isinstance(value, dict):
                rendered = json.dumps(value, ensure_ascii=False)
                if len(rendered) > 80:
                    rendered = rendered[:77] + "..."
            else:
                rendered = str(value)
            if key in {"file_path", "input_file"}:
                key = "file"
                rendered = Path(rendered).name
            parts.append(f"{key}={rendered}")
        return ", ".join(parts)

    @staticmethod
    def _format_active_artifacts(active_artifact_refs: Dict[str, Any]) -> str:
        if not active_artifact_refs:
            return "none [geometry: unknown]"
        artifact_parts: List[str] = []
        geometry = active_artifact_refs.get("geometry")
        for result_type, ref in active_artifact_refs.items():
            if result_type == "geometry":
                continue
            ref_text = str(ref)
            label = ref_text.split(":", 1)[-1] if ":" in ref_text else ref_text
            artifact_parts.append(f"{result_type}({label})")
        geometry_present = "unknown"
        if isinstance(geometry, dict):
            geometry_present = "present" if geometry.get("geometry_present") else "missing"
        elif isinstance(geometry, bool):
            geometry_present = "present" if geometry else "missing"
        prefix = ", ".join(artifact_parts) if artifact_parts else "none"
        return f"{prefix} [geometry: {geometry_present}]"

    @staticmethod
    def _format_locked_parameters(locked_parameters: Dict[str, Any]) -> str:
        if not locked_parameters:
            return "none"
        return ", ".join(f"{key}={value}" for key, value in locked_parameters.items())

    @staticmethod
    def _format_constraint_violations(records: List[Any]) -> str:
        if not records:
            return "none"
        parts: List[str] = []
        for record in records[-5:]:
            if not isinstance(record, dict):
                continue
            values = record.get("values") if isinstance(record.get("values"), dict) else {}
            value_text = "+".join(str(value) for value in values.values() if value is not None)
            if not value_text:
                value_text = str(record.get("constraint") or "constraint")
            status = "blocked" if record.get("blocked") else "warned"
            turn = record.get("turn")
            parts.append(f"{value_text} ({status} on turn {turn})")
        return "; ".join(parts) if parts else "none"

    @staticmethod
    def _derive_current_action_required(state: Optional[Any]) -> str:
        if state is None:
            return "New task starts; handle the user's current message."
        if getattr(state, "active_input_completion", None) is not None:
            return "The user is replying to an input-completion request. Use their answer to fill the missing parameter or file input."
        if getattr(state, "active_parameter_negotiation", None) is not None:
            return "The user is confirming a parameter candidate. Apply that confirmation before selecting tools."
        continuation = getattr(state, "continuation", None)
        if continuation is not None:
            next_tool = getattr(continuation, "next_tool_name", None)
            summary = getattr(continuation, "residual_plan_summary", None)
            if next_tool:
                return f"The user's multi-step intent still has pending work. Continue with {next_tool} rather than starting over."
            if summary:
                return f"The user's multi-step intent still has pending work: {summary}"
        plan = getattr(state, "plan", None)
        steps = getattr(plan, "steps", None)
        if isinstance(steps, list):
            pending = [
                getattr(step, "tool_name", None)
                for step in steps
                if str(getattr(step, "status", "")).split(".")[-1] not in {"DONE", "COMPLETED"}
            ]
            pending = [item for item in pending if item]
            if pending:
                return "The user's multi-step intent has pending steps: " + " -> ".join(pending[:3])
        return "New task starts; handle the user's current message."

    def _truncate_session_state_block(self, block: str, max_tokens: int) -> str:
        max_chars = max_tokens * 2
        if len(block) <= max_chars:
            return block
        return block[: max_chars - 32].rstrip() + "\n...(session state truncated)"

    def _build_messages(
        self,
        user_message: str,
        working_memory: List[Dict],
        fact_memory: Dict,
        file_context: Optional[Dict],
        used_tokens: int,
    ) -> List[Dict]:
        """Build the messages list (shared by both modes)."""
        messages = []

        # Fact memory
        if fact_memory and any(fact_memory.values()):
            fact_summary = self._format_fact_memory(fact_memory)
            if fact_summary:
                messages.append({
                    "role": "system",
                    "content": f"[Context from previous conversations]\n{fact_summary}"
                })
                used_tokens += self._estimate_tokens(fact_summary)

        # Working memory
        remaining_budget = self.MAX_CONTEXT_TOKENS - used_tokens - 500
        working_memory_messages = self._format_working_memory(
            working_memory,
            max_tokens=remaining_budget,
            max_turns=3
        )
        messages.extend(working_memory_messages)
        used_tokens += self._estimate_tokens(str(working_memory_messages))

        # File context
        if file_context and self.runtime_config.enable_file_context_injection:
            file_summary = self._format_file_context(file_context, max_tokens=500)
            user_message = f"{file_summary}\n\n{user_message}"

        # Current user message
        messages.append({"role": "user", "content": user_message})

        return messages

    def _format_fact_memory(self, fact_memory: Dict) -> str:
        """Format fact memory for LLM"""
        lines = []

        if fact_memory.get("recent_vehicle"):
            lines.append(f"Recent vehicle type: {fact_memory['recent_vehicle']}")

        if fact_memory.get("recent_pollutants"):
            pols = ", ".join(fact_memory["recent_pollutants"])
            lines.append(f"Recent pollutants: {pols}")

        if fact_memory.get("recent_year"):
            lines.append(f"Recent model year: {fact_memory['recent_year']}")

        if fact_memory.get("active_file"):
            lines.append(f"Active file: {fact_memory['active_file']}")

        file_analysis = fact_memory.get("file_analysis")
        if isinstance(file_analysis, dict):
            task_type = file_analysis.get("task_type") or file_analysis.get("detected_type")
            if task_type:
                lines.append(f"Cached file task_type: {task_type}")
            if file_analysis.get("row_count") is not None:
                lines.append(f"Cached file rows: {file_analysis.get('row_count')}")
            cols = file_analysis.get("columns") or []
            if isinstance(cols, list) and cols:
                preview_cols = ", ".join([str(c) for c in cols[:12]])
                if len(cols) > 12:
                    preview_cols += f" ... (共{len(cols)}列)"
                lines.append(f"Cached file columns: {preview_cols}")

        if fact_memory.get("last_tool_name"):
            lines.append(f"Last successful tool: {fact_memory['last_tool_name']}")
        if fact_memory.get("last_tool_summary"):
            summary = str(fact_memory["last_tool_summary"])
            if len(summary) > 260:
                summary = summary[:260] + "...(truncated)"
            lines.append(f"Last tool summary: {summary}")
        if fact_memory.get("last_tool_snapshot"):
            try:
                snap = json.dumps(fact_memory["last_tool_snapshot"], ensure_ascii=False)
                if len(snap) > 360:
                    snap = snap[:360] + "...(truncated)"
                lines.append(f"Last tool snapshot: {snap}")
            except Exception:
                pass

        return "\n".join(lines) if lines else ""

    def _format_working_memory(
        self,
        working_memory: List[Dict],
        max_tokens: int,
        max_turns: int = 3
    ) -> List[Dict]:
        """
        Format working memory for LLM

        Strategy: Keep last N complete turns (default 3, reduced when file uploaded)
        Truncate long assistant responses to prevent pattern bias
        If over budget, drop oldest turns
        """
        if not working_memory:
            return []

        recent = working_memory[-max_turns:]

        result = []
        for turn in recent:
            result.append({"role": "user", "content": turn["user"]})
            # Truncate long assistant responses to prevent context pollution
            assistant_text = turn["assistant"]
            if len(assistant_text) > self.MAX_ASSISTANT_RESPONSE_CHARS:
                assistant_text = assistant_text[:self.MAX_ASSISTANT_RESPONSE_CHARS] + "...(truncated)"
            result.append({"role": "assistant", "content": assistant_text})

        # Token budget check — drop oldest if over budget
        estimated = self._estimate_tokens(str(result))
        if estimated > max_tokens and len(recent) > 1:
            recent = recent[-1:]
            result = []
            for turn in recent:
                result.append({"role": "user", "content": turn["user"]})
                assistant_text = turn["assistant"]
                if len(assistant_text) > self.MAX_ASSISTANT_RESPONSE_CHARS:
                    assistant_text = assistant_text[:self.MAX_ASSISTANT_RESPONSE_CHARS] + "...(truncated)"
                result.append({"role": "assistant", "content": assistant_text})

        return result

    def _format_file_context(self, file_context: Dict, max_tokens: int) -> str:
        """Format file context for LLM"""
        columns = [str(col) for col in file_context.get("columns", [])]
        columns_str = ", ".join(columns)
        if len(columns_str) > self.MAX_FILE_CONTEXT_COLUMNS_CHARS:
            shown = columns[: self.MAX_FILE_CONTEXT_COLUMNS]
            while shown and len(", ".join(shown)) > self.MAX_FILE_CONTEXT_COLUMNS_CHARS:
                shown.pop()
            omitted = max(0, len(columns) - len(shown))
            columns_str = ", ".join(shown)
            if omitted:
                columns_str = f"{columns_str} ... ({omitted} more columns)"

        lines = [
            f"Filename: {file_context.get('filename', 'unknown')}",
            f"File path: {file_context.get('file_path', 'unknown')}",
        ]

        # Highlight task_type prominently — system prompt tells LLM to use this
        task_type = file_context.get("task_type") or file_context.get("detected_type", "unknown")
        lines.append(f"task_type: {task_type}")

        lines.extend([
            f"Rows: {file_context.get('row_count', 'unknown')}",
            f"Columns: {columns_str}",
        ])

        # Add sample data if space available
        if max_tokens > 300 and file_context.get("sample_rows"):
            lines.append(f"Sample (first 2 rows): {file_context['sample_rows'][:2]}")

        return "\n".join(lines)

    def _estimate_tokens(self, text: str) -> int:
        """
        Estimate token count

        Simple heuristic: 1 Chinese char ≈ 1 token, 1 English word ≈ 1 token
        In production, use tiktoken for accurate counting
        """
        if not text:
            return 0
        return len(text) // 2
