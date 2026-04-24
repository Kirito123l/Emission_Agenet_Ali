from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class InputCompletionReasonCode(str, Enum):
    MISSING_REQUIRED_FIELD = "missing_required_field"
    MISSING_GEOMETRY = "missing_geometry"
    MISSING_METEOROLOGY = "missing_meteorology"


class InputCompletionOptionType(str, Enum):
    PROVIDE_UNIFORM_VALUE = "provide_uniform_value"
    USE_DERIVATION = "use_derivation"
    UPLOAD_SUPPORTING_FILE = "upload_supporting_file"
    PAUSE = "pause"
    CHOOSE_PRESET = "choose_preset"
    APPLY_DEFAULT_TYPICAL_PROFILE = "apply_default_typical_profile"


class InputCompletionDecisionType(str, Enum):
    SELECTED_OPTION = "selected_option"
    PAUSE = "pause"
    AMBIGUOUS_REPLY = "ambiguous_reply"


@dataclass
class InputCompletionOption:
    option_id: str
    option_type: InputCompletionOptionType
    label: str
    description: str
    requirements: Dict[str, Any] = field(default_factory=dict)
    applicable: bool = True
    default_hint: Optional[str] = None
    aliases: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "option_id": self.option_id,
            "option_type": self.option_type.value,
            "label": self.label,
            "description": self.description,
            "requirements": dict(self.requirements),
            "applicable": self.applicable,
            "default_hint": self.default_hint,
            "aliases": list(self.aliases),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "InputCompletionOption":
        payload = data if isinstance(data, dict) else {}
        option_type = payload.get("option_type") or InputCompletionOptionType.PAUSE.value
        return cls(
            option_id=str(payload.get("option_id") or "").strip(),
            option_type=InputCompletionOptionType(option_type),
            label=str(payload.get("label") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            requirements=dict(payload.get("requirements") or {}),
            applicable=bool(payload.get("applicable", True)),
            default_hint=str(payload.get("default_hint")).strip() if payload.get("default_hint") is not None else None,
            aliases=[
                str(item).strip()
                for item in (payload.get("aliases") or [])
                if str(item).strip()
            ],
        )


@dataclass
class InputCompletionRequest:
    request_id: str
    action_id: str
    reason_code: InputCompletionReasonCode
    reason_summary: str
    missing_requirements: List[str] = field(default_factory=list)
    options: List[InputCompletionOption] = field(default_factory=list)
    target_field: Optional[str] = None
    current_task_type: Optional[str] = None
    related_file_context_summary: Optional[str] = None
    repair_hint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "action_id": self.action_id,
            "reason_code": self.reason_code.value,
            "reason_summary": self.reason_summary,
            "missing_requirements": list(self.missing_requirements),
            "options": [option.to_dict() for option in self.options],
            "target_field": self.target_field,
            "current_task_type": self.current_task_type,
            "related_file_context_summary": self.related_file_context_summary,
            "repair_hint": self.repair_hint,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "InputCompletionRequest":
        payload = data if isinstance(data, dict) else {}
        reason_code = payload.get("reason_code") or InputCompletionReasonCode.MISSING_REQUIRED_FIELD.value
        return cls(
            request_id=str(payload.get("request_id") or "").strip(),
            action_id=str(payload.get("action_id") or "").strip(),
            reason_code=InputCompletionReasonCode(reason_code),
            reason_summary=str(payload.get("reason_summary") or "").strip(),
            missing_requirements=[
                str(item).strip()
                for item in (payload.get("missing_requirements") or [])
                if str(item).strip()
            ],
            options=[
                InputCompletionOption.from_dict(item)
                for item in (payload.get("options") or [])
                if isinstance(item, dict)
            ],
            target_field=str(payload.get("target_field")).strip() if payload.get("target_field") is not None else None,
            current_task_type=(
                str(payload.get("current_task_type")).strip()
                if payload.get("current_task_type") is not None
                else None
            ),
            related_file_context_summary=(
                str(payload.get("related_file_context_summary")).strip()
                if payload.get("related_file_context_summary") is not None
                else None
            ),
            repair_hint=str(payload.get("repair_hint")).strip() if payload.get("repair_hint") is not None else None,
        )

    @classmethod
    def create(
        cls,
        *,
        action_id: str,
        reason_code: InputCompletionReasonCode,
        reason_summary: str,
        missing_requirements: Optional[List[str]] = None,
        options: Optional[List[InputCompletionOption]] = None,
        target_field: Optional[str] = None,
        current_task_type: Optional[str] = None,
        related_file_context_summary: Optional[str] = None,
        repair_hint: Optional[str] = None,
    ) -> "InputCompletionRequest":
        suffix = target_field or action_id or reason_code.value
        return cls(
            request_id=f"completion-{suffix}-{uuid.uuid4().hex[:8]}",
            action_id=action_id,
            reason_code=reason_code,
            reason_summary=reason_summary,
            missing_requirements=list(missing_requirements or []),
            options=list(options or []),
            target_field=target_field,
            current_task_type=current_task_type,
            related_file_context_summary=related_file_context_summary,
            repair_hint=repair_hint,
        )

    def get_option(self, option_id: Optional[str]) -> Optional[InputCompletionOption]:
        if not option_id:
            return None
        for option in self.options:
            if option.option_id == option_id:
                return option
        return None

    def get_first_option_by_type(
        self,
        option_type: InputCompletionOptionType,
    ) -> Optional[InputCompletionOption]:
        for option in self.options:
            if option.option_type == option_type and option.applicable:
                return option
        return None


@dataclass
class InputCompletionDecision:
    request_id: str
    decision_type: InputCompletionDecisionType
    user_reply: str
    selected_option_id: Optional[str] = None
    structured_payload: Dict[str, Any] = field(default_factory=dict)
    source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "decision_type": self.decision_type.value,
            "user_reply": self.user_reply,
            "selected_option_id": self.selected_option_id,
            "structured_payload": dict(self.structured_payload),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "InputCompletionDecision":
        payload = data if isinstance(data, dict) else {}
        decision_type = payload.get("decision_type") or InputCompletionDecisionType.AMBIGUOUS_REPLY.value
        return cls(
            request_id=str(payload.get("request_id") or "").strip(),
            decision_type=InputCompletionDecisionType(decision_type),
            user_reply=str(payload.get("user_reply") or "").strip(),
            selected_option_id=(
                str(payload.get("selected_option_id")).strip()
                if payload.get("selected_option_id") is not None
                else None
            ),
            structured_payload=dict(payload.get("structured_payload") or {}),
            source=str(payload.get("source")).strip() if payload.get("source") is not None else None,
        )


@dataclass
class InputCompletionParseResult:
    is_resolved: bool
    decision: Optional[InputCompletionDecision] = None
    needs_retry: bool = False
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_resolved": self.is_resolved,
            "decision": self.decision.to_dict() if self.decision else None,
            "needs_retry": self.needs_retry,
            "error_message": self.error_message,
        }


_PAUSE_PHRASES = (
    "pause",
    "later",
    "稍后",
    "暂停",
    "先不做",
    "先不继续",
)

_UPLOAD_PHRASES = (
    "upload",
    "上传",
    "补充文件",
    "gis",
    "geojson",
    "shapefile",
    "wkt",
)

# Bounded set of phrases that indicate "use default typical profile" intent.
# These are deterministic pattern matches – no LLM involved.
_DEFAULT_TYPICAL_PROFILE_PHRASES = (
    "默认典型值",
    "默认值模拟",
    "默认值计算",
    "默认典型",
    "用默认值",
    "按默认",
    "默认估算",
    "典型值模拟",
    "典型值估算",
    "道路类型估算",
    "道路类型默认",
    "按道路类型",
    "系统默认模拟",
    "系统默认",
    "默认模拟",
    "default typical",
    "default profile",
    "use defaults",
    "use default",
    "typical profile",
)

_INDEX_PATTERNS = (
    r"^\s*(\d+)\s*$",
    r"选第\s*(\d+)\s*个",
    r"第\s*(\d+)\s*个",
)

_CHINESE_INDEX_MAP = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
}


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _extract_index(reply: str) -> Optional[int]:
    normalized = _normalize_text(reply)
    if not normalized:
        return None
    for pattern in _INDEX_PATTERNS:
        match = re.search(pattern, normalized)
        if match:
            return int(match.group(1))
    for key, value in _CHINESE_INDEX_MAP.items():
        if f"第{key}个" in normalized or f"选第{key}个" in normalized:
            return value
    return None


def _extract_numeric_value(reply: str) -> Optional[float]:
    normalized = str(reply or "").strip()
    if not normalized:
        return None
    match = re.search(r"(-?\d+(?:\.\d+)?)", normalized.replace(",", ""))
    if not match:
        return None
    try:
        value = float(match.group(1))
    except Exception:
        return None
    if value < 0:
        return None
    return value


def _option_aliases(option: InputCompletionOption) -> List[str]:
    aliases = [option.label, option.option_id, option.option_type.value, *(option.aliases or [])]
    seen = set()
    result: List[str] = []
    for item in aliases:
        text = str(item or "").strip()
        normalized = _normalize_text(text)
        if text and normalized and normalized not in seen:
            seen.add(normalized)
            result.append(text)
    return result


def _match_option_by_reply(
    request: InputCompletionRequest,
    reply: str,
) -> Optional[InputCompletionOption]:
    selected_index = _extract_index(reply)
    applicable_options = [option for option in request.options if option.applicable]
    if selected_index is not None:
        if 1 <= selected_index <= len(applicable_options):
            return applicable_options[selected_index - 1]
        return None

    normalized_reply = _normalize_text(reply)
    if not normalized_reply:
        return None

    for option in applicable_options:
        for alias in _option_aliases(option):
            normalized_alias = _normalize_text(alias)
            if normalized_reply == normalized_alias or normalized_alias in normalized_reply:
                return option
    return None


def _matches_default_typical_profile_intent(normalized_reply: str) -> bool:
    """Deterministic check: does the reply express 'use default typical profile' intent?"""
    if not normalized_reply:
        return False
    for phrase in _DEFAULT_TYPICAL_PROFILE_PHRASES:
        if phrase in normalized_reply:
            return True
    return False


def reply_looks_like_input_completion_attempt(
    request: InputCompletionRequest,
    user_reply: str,
    *,
    supporting_file_path: Optional[str] = None,
) -> bool:
    reply = _normalize_text(user_reply)
    if not reply and not supporting_file_path:
        return False
    if any(phrase in reply for phrase in _PAUSE_PHRASES):
        return True
    if supporting_file_path and request.get_first_option_by_type(InputCompletionOptionType.UPLOAD_SUPPORTING_FILE):
        return True
    if _extract_index(user_reply) is not None:
        return True
    if (
        _extract_numeric_value(user_reply) is not None
        and request.get_first_option_by_type(InputCompletionOptionType.PROVIDE_UNIFORM_VALUE)
    ):
        return True
    if _match_option_by_reply(request, user_reply) is not None:
        return True
    if (
        request.get_first_option_by_type(InputCompletionOptionType.APPLY_DEFAULT_TYPICAL_PROFILE)
        and _matches_default_typical_profile_intent(reply)
    ):
        return True
    return False


def parse_input_completion_reply(
    request: InputCompletionRequest,
    user_reply: str,
    *,
    supporting_file_path: Optional[str] = None,
) -> InputCompletionParseResult:
    reply = str(user_reply or "").strip()
    normalized_reply = _normalize_text(reply)

    if not normalized_reply and not supporting_file_path:
        return InputCompletionParseResult(
            is_resolved=False,
            needs_retry=True,
            error_message="Empty completion reply.",
        )

    if any(phrase in normalized_reply for phrase in _PAUSE_PHRASES):
        pause_option = request.get_first_option_by_type(InputCompletionOptionType.PAUSE)
        return InputCompletionParseResult(
            is_resolved=True,
            decision=InputCompletionDecision(
                request_id=request.request_id,
                decision_type=InputCompletionDecisionType.PAUSE,
                user_reply=reply,
                selected_option_id=pause_option.option_id if pause_option else None,
                source="pause_phrase",
            ),
        )

    # Deterministic detection of "use default typical profile" intent
    profile_option = request.get_first_option_by_type(InputCompletionOptionType.APPLY_DEFAULT_TYPICAL_PROFILE)
    if profile_option is not None and _matches_default_typical_profile_intent(normalized_reply):
        return InputCompletionParseResult(
            is_resolved=True,
            decision=InputCompletionDecision(
                request_id=request.request_id,
                decision_type=InputCompletionDecisionType.SELECTED_OPTION,
                user_reply=reply,
                selected_option_id=profile_option.option_id,
                structured_payload={
                    "mode": "remediation_policy",
                    "policy_type": "apply_default_typical_profile",
                    "target_fields": list(profile_option.requirements.get("target_fields") or []),
                    "context_signals": list(profile_option.requirements.get("context_signals_present") or []),
                },
                source="default_typical_profile_phrase",
            ),
        )

    uniform_option = request.get_first_option_by_type(InputCompletionOptionType.PROVIDE_UNIFORM_VALUE)
    numeric_value = _extract_numeric_value(reply)
    if uniform_option is not None and numeric_value is not None:
        return InputCompletionParseResult(
            is_resolved=True,
            decision=InputCompletionDecision(
                request_id=request.request_id,
                decision_type=InputCompletionDecisionType.SELECTED_OPTION,
                user_reply=reply,
                selected_option_id=uniform_option.option_id,
                structured_payload={
                    "mode": "uniform_scalar",
                    "field": request.target_field,
                    "value": numeric_value,
                },
                source="numeric_reply",
            ),
        )

    selected_option = _match_option_by_reply(request, reply)
    if selected_option is None and supporting_file_path:
        selected_option = request.get_first_option_by_type(InputCompletionOptionType.UPLOAD_SUPPORTING_FILE)

    if selected_option is None:
        return InputCompletionParseResult(
            is_resolved=False,
            needs_retry=True,
            error_message=(
                "Reply with an option index/label, a numeric value like `1500`, upload the supporting file, or say `暂停`."
            ),
        )

    if selected_option.option_type == InputCompletionOptionType.PAUSE:
        return InputCompletionParseResult(
            is_resolved=True,
            decision=InputCompletionDecision(
                request_id=request.request_id,
                decision_type=InputCompletionDecisionType.PAUSE,
                user_reply=reply,
                selected_option_id=selected_option.option_id,
                source="option_selection",
            ),
        )

    if selected_option.option_type == InputCompletionOptionType.UPLOAD_SUPPORTING_FILE:
        if not supporting_file_path:
            return InputCompletionParseResult(
                is_resolved=False,
                needs_retry=True,
                error_message="This option requires uploading a supporting file in the same turn.",
            )
        return InputCompletionParseResult(
            is_resolved=True,
            decision=InputCompletionDecision(
                request_id=request.request_id,
                decision_type=InputCompletionDecisionType.SELECTED_OPTION,
                user_reply=reply,
                selected_option_id=selected_option.option_id,
                structured_payload={
                    "mode": "uploaded_supporting_file",
                    "file_ref": supporting_file_path,
                },
                source="uploaded_file",
            ),
        )

    if selected_option.option_type == InputCompletionOptionType.PROVIDE_UNIFORM_VALUE:
        return InputCompletionParseResult(
            is_resolved=False,
            needs_retry=True,
            error_message="Please give the concrete uniform value directly, for example `1500` or `全部设为1500`.",
        )

    if selected_option.option_type == InputCompletionOptionType.USE_DERIVATION:
        payload = dict(selected_option.requirements or {})
        payload.setdefault("mode", "source_column_derivation")
        payload.setdefault("field", request.target_field)
        return InputCompletionParseResult(
            is_resolved=True,
            decision=InputCompletionDecision(
                request_id=request.request_id,
                decision_type=InputCompletionDecisionType.SELECTED_OPTION,
                user_reply=reply,
                selected_option_id=selected_option.option_id,
                structured_payload=payload,
                source="option_selection",
            ),
        )

    if selected_option.option_type == InputCompletionOptionType.APPLY_DEFAULT_TYPICAL_PROFILE:
        return InputCompletionParseResult(
            is_resolved=True,
            decision=InputCompletionDecision(
                request_id=request.request_id,
                decision_type=InputCompletionDecisionType.SELECTED_OPTION,
                user_reply=reply,
                selected_option_id=selected_option.option_id,
                structured_payload={
                    "mode": "remediation_policy",
                    "policy_type": "apply_default_typical_profile",
                    "target_fields": list(selected_option.requirements.get("target_fields") or []),
                    "context_signals": list(selected_option.requirements.get("context_signals_present") or []),
                },
                source="option_selection",
            ),
        )

    return InputCompletionParseResult(
        is_resolved=False,
        needs_retry=True,
        error_message="The selected completion option is not supported in this round.",
    )


def format_input_completion_prompt(
    request: InputCompletionRequest,
    *,
    retry_message: Optional[str] = None,
) -> str:
    lines = [
        "输入补全 / Input Completion",
        f"当前动作 `{request.action_id}` 还不能直接执行。",
        f"原因: {request.reason_summary}",
    ]
    if request.target_field:
        lines.append(f"目标字段: `{request.target_field}`")
    if request.current_task_type:
        lines.append(f"任务类型: `{request.current_task_type}`")
    if request.related_file_context_summary:
        lines.append(f"文件上下文: {request.related_file_context_summary}")
    if request.missing_requirements:
        lines.append(f"缺失条件: {', '.join(request.missing_requirements)}")
    if request.repair_hint:
        lines.append(f"补救提示: {request.repair_hint}")

    lines.append("请选择一个补救方式：")
    for index, option in enumerate([item for item in request.options if item.applicable], start=1):
        line = f"{index}. {option.label} - {option.description}"
        if option.default_hint:
            line += f" ({option.default_hint})"
        lines.append(line)

    if retry_message:
        lines.append(f"上次回复未能形成合法补救决策: {retry_message}")

    if request.get_first_option_by_type(InputCompletionOptionType.PROVIDE_UNIFORM_VALUE):
        lines.append(
            "如果你选择统一值，请直接回复数值，例如 `1500`、`全部设为1500` 或 `统一按 2000 vph`。"
        )
    if request.get_first_option_by_type(InputCompletionOptionType.UPLOAD_SUPPORTING_FILE):
        lines.append("如果你选择补充文件，请在下一条消息中上传文件并回复 '上传文件'。")
    if request.get_first_option_by_type(InputCompletionOptionType.APPLY_DEFAULT_TYPICAL_PROFILE):
        lines.append(
            "如果你希望使用默认典型值策略，回复 '用默认典型值模拟' 或 '按道路类型估算' 即可。"
        )
    lines.append("如果现在不处理，回复 '暂停'。")
    return "\n".join(lines)
