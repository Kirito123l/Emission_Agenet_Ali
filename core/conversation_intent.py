"""Conservative conversation-intent classifier for fast-path routing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class ConversationIntent(str, Enum):
    CHITCHAT = "chitchat"
    EXPLAIN_RESULT = "explain_result"
    KNOWLEDGE_QA = "knowledge_qa"
    NEW_TASK = "new_task"
    CONTINUE_TASK = "continue_task"
    MODIFY_PARAMS = "modify_params"
    RETRY = "retry"
    UNDO = "undo"
    CONFIRM = "confirm"
    UNKNOWN = "unknown"


@dataclass
class IntentResult:
    intent: ConversationIntent
    confidence: float
    rationale: str
    fast_path_allowed: bool = False
    blocking_signals: List[str] = field(default_factory=list)
    extracted_entities: Optional[dict] = None


class ConversationIntentClassifier:
    """Rule-first classifier biased toward *not* fast-pathing risky turns."""

    CHITCHAT_PATTERNS = (
        r"^(你好|您好|hi|hello|hey|嗨|在吗)[!！。,. ]*$",
        r"^(谢谢|多谢|thanks|thank you)[!！。,. ]*$",
        r"^(好的|收到|明白了|了解了|ok|okay)[!！。,. ]*$",
    )
    EXPLAIN_PATTERNS = (
        r"(解释|说明|什么意思|怎么理解|为什么|请解释)",
        r"(what does|explain|why|how do i interpret)",
    )
    RESULT_REFERENCE_PATTERNS = (
        r"(刚才|上面|之前|这个|那个).*(结果|数据|图|表|值|排放|浓度)",
        r"(结果|数据|图|表|值|排放|浓度).*(是什么意思|怎么理解|为什么)",
    )
    KNOWLEDGE_PATTERNS = (
        r"(是什么|什么是|定义|标准|规范|限值|含义)$",
        r"^(什么是|what is|what are)\b",
        r"(NOx|PM2\.5|PM10|CO2|CO|THC|VSP|MOVES).*(是什么|标准|定义|含义)",
    )
    OUTPUT_MODE_PATTERNS = (
        r"(可视化|图表|地图|渲染|下载|导出|摘要表|柱状图|chart|table|map|render)",
    )
    TASK_PATTERNS = (
        r"(计算|分析|做扩散|扩散|热点|渲染|可视化|对比|scenario|上传|文件)",
        r"(calculate|analyze|run|execute|render|visualize|compare|upload)",
    )
    CONTINUE_PATTERNS = (
        r"^(继续|接着|下一步|然后|continue|next)",
    )
    MODIFY_PATTERNS = (
        r"(换成|改成|改为|修改|调整|更换|切换)",
    )
    RETRY_PATTERNS = (
        r"(再试|重试|重新|retry|again)",
    )
    UNDO_PATTERNS = (
        r"(撤销|回到上一步|undo|revert)",
    )
    CONFIRM_PATTERNS = (
        r"^[1-9一二三四五六七八九]$",
        r"^(确认|就这个|选这个|第[1-9]个|option\s*[1-9])$",
    )

    @staticmethod
    def _match_any(text: str, patterns: tuple[str, ...]) -> bool:
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)

    def classify(
        self,
        user_message: str,
        *,
        has_new_file: bool = False,
        has_last_tool_name: bool = False,
        has_active_file: bool = False,
        has_active_negotiation: bool = False,
        has_active_completion: bool = False,
        has_file_relationship_clarification: bool = False,
        has_residual_workflow: bool = False,
    ) -> IntentResult:
        raw_text = user_message or ""
        text = raw_text.strip()
        normalized = text.lower()

        blocking_signals: List[str] = []
        if has_new_file:
            blocking_signals.append("new_file_upload")
        if has_active_negotiation:
            blocking_signals.append("active_parameter_negotiation")
        if has_active_completion:
            blocking_signals.append("active_input_completion")
        if has_file_relationship_clarification:
            blocking_signals.append("file_relationship_clarification")
        if has_residual_workflow:
            blocking_signals.append("residual_workflow")

        if self._match_any(normalized, self.CONFIRM_PATTERNS):
            return IntentResult(
                intent=ConversationIntent.CONFIRM,
                confidence=0.95,
                rationale="confirmation-like reply detected",
                fast_path_allowed=False,
                blocking_signals=blocking_signals,
            )

        if self._match_any(normalized, self.MODIFY_PATTERNS):
            return IntentResult(
                intent=ConversationIntent.MODIFY_PARAMS,
                confidence=0.85,
                rationale="parameter-modification cue detected",
                fast_path_allowed=False,
                blocking_signals=blocking_signals,
            )

        if self._match_any(normalized, self.CONTINUE_PATTERNS):
            return IntentResult(
                intent=ConversationIntent.CONTINUE_TASK,
                confidence=0.85,
                rationale="continuation cue detected",
                fast_path_allowed=False,
                blocking_signals=blocking_signals,
            )

        if self._match_any(normalized, self.RETRY_PATTERNS):
            return IntentResult(
                intent=ConversationIntent.RETRY,
                confidence=0.85,
                rationale="retry cue detected",
                fast_path_allowed=False,
                blocking_signals=blocking_signals,
            )

        if self._match_any(normalized, self.UNDO_PATTERNS):
            return IntentResult(
                intent=ConversationIntent.UNDO,
                confidence=0.85,
                rationale="undo cue detected",
                fast_path_allowed=False,
                blocking_signals=blocking_signals,
            )

        explain_match = self._match_any(normalized, self.EXPLAIN_PATTERNS)
        result_reference = self._match_any(normalized, self.RESULT_REFERENCE_PATTERNS)
        if explain_match and (result_reference or has_last_tool_name):
            return IntentResult(
                intent=ConversationIntent.EXPLAIN_RESULT,
                confidence=0.9,
                rationale="explanation cue matched prior-result context",
                fast_path_allowed=not blocking_signals,
                blocking_signals=blocking_signals,
            )

        has_output_mode_cue = self._match_any(normalized, self.OUTPUT_MODE_PATTERNS)
        has_task_cue = self._match_any(normalized, self.TASK_PATTERNS)

        if self._match_any(normalized, self.KNOWLEDGE_PATTERNS) and not has_output_mode_cue and not has_task_cue:
            return IntentResult(
                intent=ConversationIntent.KNOWLEDGE_QA,
                confidence=0.85,
                rationale="knowledge-definition cue detected without task keywords",
                fast_path_allowed=not blocking_signals,
                blocking_signals=blocking_signals,
            )

        if (
            self._match_any(normalized, self.CHITCHAT_PATTERNS)
            and len(text) <= 40
            and not has_task_cue
            and not has_output_mode_cue
        ):
            return IntentResult(
                intent=ConversationIntent.CHITCHAT,
                confidence=0.92,
                rationale="short chitchat cue detected",
                fast_path_allowed=not blocking_signals,
                blocking_signals=blocking_signals,
            )

        if has_task_cue or has_output_mode_cue:
            return IntentResult(
                intent=ConversationIntent.CONTINUE_TASK if (has_active_file or has_last_tool_name) else ConversationIntent.NEW_TASK,
                confidence=0.7,
                rationale="task/output-mode cue detected",
                fast_path_allowed=False,
                blocking_signals=blocking_signals + (["output_mode_request"] if has_output_mode_cue else []),
            )

        return IntentResult(
            intent=ConversationIntent.CONTINUE_TASK if (has_active_file or has_last_tool_name) else ConversationIntent.NEW_TASK,
            confidence=0.55,
            rationale="defaulted to task/state-loop routing",
            fast_path_allowed=False,
            blocking_signals=blocking_signals,
        )
