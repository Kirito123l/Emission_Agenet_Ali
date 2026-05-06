"""Evaluate end-to-end routing and execution over structured benchmark tasks.

Notes:
- `router` and `full` modes exercise the production governed router path.
- `naive` mode exercises `NaiveRouter.chat()` as the paper baseline path.
- `tool` mode remains available for offline validation and smoke-style checks.
- Router-mode evaluation may require provider/API access depending on the configured LLM stack.
"""
from __future__ import annotations

import argparse
import asyncio
import contextvars
import copy
import json
import os
import re
import sys
import threading
import time
import traceback
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypeVar


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.executor import ToolExecutor
from core.naive_router import NaiveRouter
from core.governed_router import build_router
from core.reply_parser_llm import reset_call_stats, get_call_stats
from evaluation.tool_cache import ToolResultCache
from evaluation.utils import (
    classify_failure,
    classify_recoverability,
    compare_expected_subset,
    load_jsonl,
    now_ts,
    rebuild_tool_registry,
    resolve_project_path,
    runtime_overrides,
    safe_div,
    write_json,
    write_jsonl,
)
from tools.file_analyzer import FileAnalyzerTool


DEFAULT_SAMPLES = PROJECT_ROOT / "evaluation" / "benchmarks" / "end2end_tasks.jsonl"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "evaluation" / "results" / "end2end"

# A.2/A.3 step_type values whose input_summary.source is exported to trace_steps.
NEGOTIATION_COMPLETION_STEPS = frozenset({
    "parameter_negotiation_required", "parameter_negotiation_confirmed",
    "parameter_negotiation_rejected", "parameter_negotiation_failed",
    "input_completion_required", "input_completion_confirmed",
    "input_completion_rejected", "input_completion_failed",
    "input_completion_applied", "input_completion_paused",
})

# Phase 8.1.4c: governance trace step types included in eval logs.
GOVERNANCE_TRACE_STEPS = frozenset({
    "reconciler_invoked", "reconciler_proceed",
    "b_validator_filter",
    "pcm_advisory_injected",
    "projected_chain_generated",
    "decision_field_clarify",
    # Phase 8.2.2: ablation telemetry trace steps
    "ao_classifier_forced_new_ao",
    "readiness_gating_skipped",
    "cross_constraint_check_skipped",
    "fast_path_skipped",
    "continuation_overridden_to_new_ao",
})

# Combined set for trace_steps serialization.
ALL_SERIALIZED_STEP_TYPES = NEGOTIATION_COMPLETION_STEPS | GOVERNANCE_TRACE_STEPS
LEGACY_NEEDS_USER_STAGE = {
    "NEEDS_INPUT_COMPLETION",
    "NEEDS_PARAMETER_CONFIRMATION",
    "NEEDS_CLARIFICATION",
}
GEOMETRY_REQUIRED_TOOLS = {
    "calculate_dispersion",
    "render_spatial_map",
}
GEOMETRY_TEXT_CUES = (
    "geometry",
    "几何",
    "geojson",
    "wkt",
    "坐标",
    "经纬度",
    "空间信息",
    "空间位置",
    "位置信息",
    "方位",
    "geo",
    "spatial",
    "空间数据",
    "地理信息",
    "空间元数据",
    "没有可用于空间分析的几何信息",
    "缺少空间",
    "无空间",
)
METEOROLOGY_TEXT_CUES = ("气象", "风向", "风速", "稳定度", "混合层", "气象配置", "meteorology")
FOLLOW_UP_TEXT_CUES = (
    "请",
    "补充",
    "提供",
    "上传",
    "确认",
    "告诉",
    "需要",
    "如需",
    "如果您",
    "您可以",
    "你可以",
    "建议",
    "要继续",
    "才能继续",
)
EMISSION_COMPLETION_TEXT_CUES = (
    "排放",
    "emission",
    "计算完成",
    "计算结果",
    "已完成",
    "结果如下",
    "排放量",
    "排放结果",
    "g/h",
    "g/km",
    "kg/h",
    "克",
    "总排放",
    "total emission",
)
COMPLETED_DOWNSTREAM_TEXT_CUES = (
    "扩散分析已完成",
    "扩散计算已完成",
    "浓度场已生成",
    "热点分析已完成",
    "地图已生成",
    "渲染完成",
    "dispersion completed",
    "hotspot completed",
)
ASKING_USER_CUES = (
    "请告诉我",
    "请确认",
    "请选择",
    "请提供",
    "请说明",
    "请输入",
    "请指定",
    "请问",
    "我需要",
    "需要知道",
    "需要确认",
    "需要先确认",
    "需要了解",
    "需要提供",
    "还需要",
    "能告诉我",
    "您能",
    "你能",
    "以下信息",
    "以下关键信息",
    "1.",
    "1、",
    "未指定",
    "未提供",
    "缺少",
    "尚未",
    "没有指定",
    "没有提供",
    "不确定",
    "请任选其一",
    "请选择一个补救方式",
    "如果你选择",
    "如果现在不处理",
    "暂停当前",
    "上传文件",
    "which",
    "please specify",
    "please confirm",
    "please provide",
    "please tell",
    "what is your",
    "直接说",
    "使用以上",
    "以上默认",
    "回复",
    "确认后",
)
RESULT_DELIVERY_CUES = (
    "✅ 计算完成",
    "计算完成",
    "查询结果",
    "排放结果如下",
    "已成功查询",
    "已查询到",
    "已查得",
    "已完成路段文件",
    "已完成宏观排放计算",
    "已完成微观排放计算",
)
CONSTRAINT_WARNING_CUES = ("警告", "warning", "不一致", "不匹配", "冲突", "实际等效")
CONSTRAINT_WARNING_CONTEXT_CUES = ("季节", "气象", "meteorology", "summer", "winter", "urban_summer", "urban_winter")
CONSTRAINT_BLOCK_CUES = (
    "参数组合不合法",
    "参数组合不成立",
    "禁止",
    "不允许",
    "不能",
    "无法",
    "非法",
    "不合法",
    "违规",
    "违反",
    "prohibited",
    "not allowed",
    "illegal",
    "invalid combination",
)
CONSTRAINT_BLOCK_CONTEXT_PATTERNS = (
    r"摩托车.*高速",
    r"高速.*摩托车",
    r"motorcycle.*highway",
    r"highway.*motorcycle",
    r"pm\s*10.*摩托车",
    r"pm\s*2\.?5.*摩托车",
    r"摩托车.*pm\s*10",
    r"摩托车.*pm\s*2\.?5",
)
ROUTER_FOLLOW_UP_BY_TOOL = {
    "calculate_macro_emission": "继续先计算这个文件的宏观排放。",
    "calculate_micro_emission": "继续先计算这个轨迹文件的微观排放。",
    "calculate_dispersion": "继续基于刚才的排放结果做扩散分析。",
    "analyze_hotspots": "继续基于刚才的扩散结果做热点分析。",
    "render_spatial_map": "继续把刚才的结果渲染成地图。",
    "query_knowledge": "继续先查询相关知识。",
    "query_emission_factors": "继续查询对应排放因子。",
}


class InfrastructureErrorType(Enum):
    OK = "ok"
    TRANSIENT_RETRIED = "transient_retried"
    BILLING_FAILED = "billing_failed"
    NETWORK_FAILED = "network_failed"
    PERMANENT_ERROR = "permanent_error"
    UNKNOWN = "unknown"


PRODUCTION_EXCEPTION_TYPES = (
    ValueError,
    KeyError,
    TypeError,
    AttributeError,
    json.JSONDecodeError,
)


class BenchmarkAbort(RuntimeError):
    """Signal that a benchmark run must stop for infrastructure health reasons."""

    def __init__(self, status: str, message: str, task_index: int, task_id: str):
        super().__init__(message)
        self.status = status
        self.task_index = task_index
        self.task_id = task_id


T = TypeVar("T")
CURRENT_EVAL_TASK_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_eval_task_id",
    default=None,
)

BILLING_ERROR_CUES = (
    "arrearage",
    "余额不足",
    "billing",
    "账户欠费",
)
NETWORK_ERROR_CUES = (
    "connection error",
    "timeout",
    "timed out",
    "connectionreseterror",
)
PERMANENT_ERROR_CUES = (
    "model not found",
    "invalid parameter",
)


def classify_infrastructure_error(error: BaseException | str | None) -> InfrastructureErrorType:
    if error is None:
        return InfrastructureErrorType.OK
    message = str(error).lower()
    if any(cue in message for cue in BILLING_ERROR_CUES):
        return InfrastructureErrorType.BILLING_FAILED
    if any(cue in message for cue in NETWORK_ERROR_CUES):
        return InfrastructureErrorType.NETWORK_FAILED
    if any(cue in message for cue in PERMANENT_ERROR_CUES):
        return InfrastructureErrorType.PERMANENT_ERROR
    return InfrastructureErrorType.UNKNOWN


async def _run_with_infrastructure_failsafe(
    operation: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 3,
    retry_delay_sec: float = 1.0,
    timeout_sec: Optional[float] = None,
) -> tuple[Optional[T], InfrastructureErrorType, int, Optional[Dict[str, Any]]]:
    retry_count = 0
    last_error: Optional[Dict[str, Any]] = None
    for attempt in range(max_retries + 1):
        try:
            if timeout_sec and timeout_sec > 0:
                result = await asyncio.wait_for(operation(), timeout=timeout_sec)
            else:
                result = await operation()
            status = (
                InfrastructureErrorType.TRANSIENT_RETRIED
                if retry_count > 0
                else InfrastructureErrorType.OK
            )
            return result, status, retry_count, None
        except Exception as exc:  # noqa: BLE001 - benchmark must classify provider exceptions.
            if isinstance(exc, asyncio.TimeoutError):
                error_type = InfrastructureErrorType.NETWORK_FAILED
                last_error = _execution_error_payload(exc, message=f"Timeout after {timeout_sec} seconds")
            elif isinstance(exc, PRODUCTION_EXCEPTION_TYPES):
                error_type = InfrastructureErrorType.OK
                last_error = _execution_error_payload(exc)
            else:
                error_type = classify_infrastructure_error(exc)
                last_error = _execution_error_payload(exc)
            if error_type == InfrastructureErrorType.BILLING_FAILED:
                return None, error_type, retry_count, last_error
            if error_type == InfrastructureErrorType.NETWORK_FAILED and attempt < max_retries:
                retry_count += 1
                await asyncio.sleep(retry_delay_sec)
                continue
            return None, error_type, retry_count, last_error
    return None, InfrastructureErrorType.UNKNOWN, retry_count, last_error


def _execution_error_payload(exc: BaseException, *, message: Optional[str] = None) -> Dict[str, Any]:
    frames = traceback.format_exception(type(exc), exc, exc.__traceback__, limit=10)
    return {
        "message": message or str(exc),
        "type": exc.__class__.__name__,
        "repr": repr(exc),
        "traceback": "".join(frames),
    }


def _initial_infrastructure_health() -> Dict[str, int]:
    return {item.value: 0 for item in InfrastructureErrorType}


def _compute_data_integrity(health: Dict[str, int], total: int) -> str:
    if total <= 0:
        return "clean"
    transient_ratio = safe_div(health.get(InfrastructureErrorType.TRANSIENT_RETRIED.value, 0), total)
    has_hard_failure = bool(
        health.get(InfrastructureErrorType.BILLING_FAILED.value, 0)
        or health.get(InfrastructureErrorType.NETWORK_FAILED.value, 0)
    )
    return "clean" if transient_ratio < 0.05 and not has_hard_failure else "contaminated"


class TaskTelemetryRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rate_limit_wait_ms: Dict[str, float] = {}
        self._cache_hits: Dict[str, int] = {}

    def add_rate_limit_wait(self, task_id: Optional[str], wait_ms: float) -> None:
        if not task_id or wait_ms <= 0:
            return
        with self._lock:
            self._rate_limit_wait_ms[task_id] = self._rate_limit_wait_ms.get(task_id, 0.0) + wait_ms

    def add_cache_hit(self, task_id: Optional[str]) -> None:
        if not task_id:
            return
        with self._lock:
            self._cache_hits[task_id] = self._cache_hits.get(task_id, 0) + 1

    def snapshot_for_task(self, task_id: str) -> Dict[str, Any]:
        with self._lock:
            return {
                "rate_limit_wait_ms": round(self._rate_limit_wait_ms.get(task_id, 0.0), 2),
                "cache_hits": int(self._cache_hits.get(task_id, 0)),
            }

    def aggregate(self) -> Dict[str, Any]:
        with self._lock:
            total_wait_ms = round(sum(self._rate_limit_wait_ms.values()), 2)
            total_cache_hits = int(sum(self._cache_hits.values()))
        return {
            "rate_limit_wait_ms_total": total_wait_ms,
            "cache_hits_total": total_cache_hits,
        }


class RequestRateLimiter:
    def __init__(self, qps_limit: Optional[float], telemetry: TaskTelemetryRegistry):
        self.qps_limit = float(qps_limit or 0)
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()
        self._telemetry = telemetry

    def acquire(self, task_id: Optional[str]) -> float:
        if self.qps_limit <= 0:
            return 0.0
        waited_ms = 0.0
        while True:
            sleep_for = 0.0
            with self._lock:
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] >= 1.0:
                    self._timestamps.popleft()
                if len(self._timestamps) < int(self.qps_limit):
                    self._timestamps.append(now)
                    break
                sleep_for = max(0.0, 1.0 - (now - self._timestamps[0]))
            if sleep_for > 0:
                time.sleep(sleep_for)
                waited_ms += sleep_for * 1000
        if waited_ms > 0:
            self._telemetry.add_rate_limit_wait(task_id, waited_ms)
        return waited_ms


@contextmanager
def _evaluation_runtime_hooks(
    *,
    rate_limiter: RequestRateLimiter,
    task_telemetry: TaskTelemetryRegistry,
    tool_cache: ToolResultCache,
):
    import llm.client as sync_llm_module
    import services.llm_client as async_llm_module
    from core import executor as executor_module

    original_async_chat = async_llm_module.LLMClientService.chat
    original_async_chat_with_tools = async_llm_module.LLMClientService.chat_with_tools
    original_async_chat_json = async_llm_module.LLMClientService.chat_json
    original_sync_chat = sync_llm_module.LLMClient.chat
    original_sync_chat_json = sync_llm_module.LLMClient.chat_json
    original_sync_chat_json_with_history = sync_llm_module.LLMClient.chat_json_with_history
    original_execute = executor_module.ToolExecutor.execute

    async def wrapped_async_chat(self, *args, **kwargs):
        rate_limiter.acquire(CURRENT_EVAL_TASK_ID.get())
        return await original_async_chat(self, *args, **kwargs)

    async def wrapped_async_chat_with_tools(self, *args, **kwargs):
        rate_limiter.acquire(CURRENT_EVAL_TASK_ID.get())
        return await original_async_chat_with_tools(self, *args, **kwargs)

    async def wrapped_async_chat_json(self, *args, **kwargs):
        rate_limiter.acquire(CURRENT_EVAL_TASK_ID.get())
        return await original_async_chat_json(self, *args, **kwargs)

    def wrapped_sync_chat(self, *args, **kwargs):
        rate_limiter.acquire(CURRENT_EVAL_TASK_ID.get())
        return original_sync_chat(self, *args, **kwargs)

    def wrapped_sync_chat_json(self, *args, **kwargs):
        rate_limiter.acquire(CURRENT_EVAL_TASK_ID.get())
        return original_sync_chat_json(self, *args, **kwargs)

    def wrapped_sync_chat_json_with_history(self, *args, **kwargs):
        rate_limiter.acquire(CURRENT_EVAL_TASK_ID.get())
        return original_sync_chat_json_with_history(self, *args, **kwargs)

    async def wrapped_execute(self, tool_name: str, arguments: Dict[str, Any], file_path: str = None):
        if tool_cache.should_cache(tool_name):
            cached = tool_cache.get(tool_name, file_path, arguments or {})
            if isinstance(cached, dict):
                task_telemetry.add_cache_hit(CURRENT_EVAL_TASK_ID.get())
                result = copy.deepcopy(cached)
                result["_cache_hit"] = True
                return result
        result = await original_execute(self, tool_name, arguments, file_path=file_path)
        if tool_cache.should_cache(tool_name):
            tool_cache.put(tool_name, file_path, arguments or {}, result)
        if isinstance(result, dict):
            result["_cache_hit"] = False
        return result

    async_llm_module.LLMClientService.chat = wrapped_async_chat
    async_llm_module.LLMClientService.chat_with_tools = wrapped_async_chat_with_tools
    async_llm_module.LLMClientService.chat_json = wrapped_async_chat_json
    sync_llm_module.LLMClient.chat = wrapped_sync_chat
    sync_llm_module.LLMClient.chat_json = wrapped_sync_chat_json
    sync_llm_module.LLMClient.chat_json_with_history = wrapped_sync_chat_json_with_history
    executor_module.ToolExecutor.execute = wrapped_execute
    try:
        yield
    finally:
        async_llm_module.LLMClientService.chat = original_async_chat
        async_llm_module.LLMClientService.chat_with_tools = original_async_chat_with_tools
        async_llm_module.LLMClientService.chat_json = original_async_chat_json
        sync_llm_module.LLMClient.chat = original_sync_chat
        sync_llm_module.LLMClient.chat_json = original_sync_chat_json
        sync_llm_module.LLMClient.chat_json_with_history = original_sync_chat_json_with_history
        executor_module.ToolExecutor.execute = original_execute


def _check_outputs(result_like: Dict[str, Any], expected_outputs: Dict[str, bool]) -> Dict[str, Any]:
    data = result_like.get("data") or {}
    actual_outputs = {
        "has_chart_data": bool(result_like.get("chart_data")),
        "has_table_data": bool(result_like.get("table_data")),
        "has_map_data": bool(result_like.get("map_data")),
        "has_download_file": bool(result_like.get("download_file") or data.get("download_file")),
    }
    matched = True
    details = {}
    for key, expected in expected_outputs.items():
        actual = actual_outputs.get(key)
        details[key] = {"expected": expected, "actual": actual, "matched": actual == expected}
        matched = matched and actual == expected
    return {"matched": matched, "details": details, "actual_outputs": actual_outputs}


def _extract_trace_steps(trace_payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(trace_payload, dict):
        return []
    steps = trace_payload.get("steps")
    if isinstance(steps, list):
        return [step for step in steps if isinstance(step, dict)]
    return []


def _collect_standardization_records(trace_steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for step in trace_steps:
        step_records = step.get("standardization_records")
        if isinstance(step_records, list):
            records.extend(record for record in step_records if isinstance(record, dict))
    return records


def _has_result_payload(
    response_payload: Dict[str, Any],
    executed_tool_calls: List[Dict[str, Any]],
) -> bool:
    if response_payload.get("chart_data") or response_payload.get("table_data"):
        return True
    if response_payload.get("map_data") or response_payload.get("download_file"):
        return True

    for tool_call in executed_tool_calls:
        result = tool_call.get("result", {})
        if not isinstance(result, dict):
            continue
        if result.get("summary") or result.get("data"):
            return True
    return False


def _tool_chain_matches(actual: List[str], expected: List[str]) -> bool:
    if not expected:
        return True
    return actual == expected


def _tool_chain_matches_for_task(task: Dict[str, Any], actual: List[str], expected: List[str]) -> bool:
    if _tool_chain_matches(actual, expected):
        return True
    if task.get("category") == "user_revision" and expected and len(actual) >= len(expected):
        return actual[-len(expected) :] == expected
    return False


def _file_has_explicit_geometry(file_analysis: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(file_analysis, dict):
        return False

    columns = file_analysis.get("columns")
    if isinstance(columns, list):
        lowered = {str(column).strip().lower() for column in columns}
        if any(marker in lowered for marker in {"geometry", "geom", "wkt", "geojson"}):
            return True

    spatial_metadata = file_analysis.get("spatial_metadata")
    if isinstance(spatial_metadata, dict) and spatial_metadata:
        return True

    return False


def _geometry_gate_prefix(expected_tool_chain: List[str]) -> Optional[List[str]]:
    if not expected_tool_chain:
        return None

    prefix: List[str] = []
    for tool_name in expected_tool_chain:
        if tool_name in GEOMETRY_REQUIRED_TOOLS:
            return prefix
        prefix.append(tool_name)
    return None


def _normalize_match_text(text: str) -> str:
    return (
        text.lower()
        .replace("₂", "2")
        .replace("₅", "5")
        .replace("ₓ", "x")
        .replace("pm2.₅", "pm2.5")
    )


def _has_emission_completion_signal(response_text: str) -> bool:
    normalized_text = _normalize_match_text(response_text)
    return (
        any(cue in response_text for cue in EMISSION_COMPLETION_TEXT_CUES)
        or ("排放" in response_text and "已完成" in response_text)
        or ("排放" in response_text and "已执行" in response_text)
        or ("排放结果摘要" in response_text)
        or ("总排放" in response_text)
        or ("emission" in normalized_text and "completed" in normalized_text)
    )


def _response_text_is_asking_user(text: str) -> bool:
    if not text:
        return False
    stripped_text = text.strip()
    normalized_text = _normalize_match_text(stripped_text)
    if any(normalized_text.startswith(_normalize_match_text(cue)) for cue in RESULT_DELIVERY_CUES):
        return False
    hit_count = sum(
        1
        for cue in ASKING_USER_CUES
        if _normalize_match_text(cue) in normalized_text or cue in stripped_text
    )
    if hit_count >= 1:
        return True
    return stripped_text.endswith(("?", "？")) and any(
        cue in stripped_text for cue in ("请", "是否", "哪", "什么", "多少", "如何", "需要")
    )


def _response_text_has_constraint_warning(text: str) -> bool:
    if not text:
        return False
    normalized_text = _normalize_match_text(text)
    has_warning_cue = any(cue in normalized_text for cue in CONSTRAINT_WARNING_CUES)
    has_context_cue = any(cue in normalized_text for cue in CONSTRAINT_WARNING_CONTEXT_CUES)
    return has_warning_cue and has_context_cue


def _response_text_has_constraint_block(text: str) -> bool:
    if not text:
        return False
    normalized_text = _normalize_match_text(text)
    has_block_cue = any(_normalize_match_text(cue) in normalized_text for cue in CONSTRAINT_BLOCK_CUES)
    if not has_block_cue:
        return False
    return any(re.search(pattern, normalized_text, re.IGNORECASE) for pattern in CONSTRAINT_BLOCK_CONTEXT_PATTERNS)


def _stringify_for_param_match(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, (str, int, float, bool)):
        return str(payload)
    if isinstance(payload, dict):
        return " ".join(
            f"{key} {_stringify_for_param_match(value)}"
            for key, value in payload.items()
        )
    if isinstance(payload, list):
        return " ".join(_stringify_for_param_match(item) for item in payload)
    return str(payload)


def _expected_value_in_text(expected_value: Any, text: str) -> bool:
    normalized_text = _normalize_match_text(text)
    if isinstance(expected_value, dict):
        return all(_expected_value_in_text(value, text) for value in expected_value.values())
    if isinstance(expected_value, list):
        return all(_expected_value_in_text(value, text) for value in expected_value)
    normalized_expected = _normalize_match_text(str(expected_value))
    if not normalized_expected:
        return False
    return normalized_expected in normalized_text


def _response_text_has_expected_tool_result(text: str, expected_tool_chain: List[str]) -> bool:
    if not text or not expected_tool_chain:
        return False
    normalized_text = _normalize_match_text(text)
    expected = expected_tool_chain[-1]
    if expected in {"calculate_macro_emission", "calculate_micro_emission"}:
        return _has_emission_completion_signal(text)
    if expected == "query_emission_factors":
        return (
            ("排放因子" in text or "emission factor" in normalized_text)
            and any(cue in text for cue in ("已成功查询", "查询结果", "完整的排放因子", "Found emission factors"))
        )
    if expected == "query_knowledge":
        return "知识" in text or "knowledge" in normalized_text
    if expected == "calculate_dispersion":
        return "扩散" in text and any(cue in text for cue in ("完成", "结果", "浓度", "已生成"))
    if expected == "analyze_hotspots":
        return "热点" in text and any(cue in text for cue in ("完成", "结果", "识别", "已生成"))
    if expected == "render_spatial_map":
        return ("地图" in text or "map" in normalized_text) and any(cue in text for cue in ("完成", "生成", "渲染"))
    return False


def _tool_result_text(executed_tool_calls: List[Dict[str, Any]], response_payload: Dict[str, Any]) -> str:
    chunks = [_stringify_for_param_match(response_payload)]
    for tool_call in executed_tool_calls:
        result = tool_call.get("result")
        if isinstance(result, dict):
            chunks.append(_stringify_for_param_match(result.get("summary")))
            chunks.append(_stringify_for_param_match(result.get("data")))
    return " ".join(chunk for chunk in chunks if chunk)


def _merge_tool_arguments(executed_tool_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for tool_call in executed_tool_calls:
        arguments = tool_call.get("arguments")
        if not isinstance(arguments, dict):
            continue
        for key, value in arguments.items():
            if key not in merged:
                merged[key] = value
                continue
            existing = merged[key]
            if existing == value:
                continue
            existing_list = existing if isinstance(existing, list) else [existing]
            incoming_list = value if isinstance(value, list) else [value]
            merged[key] = existing_list + incoming_list
    return merged


def _comparison_with_result_fallback(
    actual_arguments: Dict[str, Any],
    expected_params: Dict[str, Any],
    *,
    executed_tool_calls: List[Dict[str, Any]],
    response_payload: Dict[str, Any],
) -> Dict[str, Any]:
    comparison = compare_expected_subset(actual_arguments, expected_params)
    if comparison["matched"] or not expected_params:
        return comparison

    result_text = _tool_result_text(executed_tool_calls, response_payload)
    details = dict(comparison.get("details") or {})
    matched = True
    for key, detail in list(details.items()):
        if detail.get("matched"):
            continue
        expected_value = detail.get("expected")
        if _expected_value_in_text(expected_value, result_text):
            updated_detail = dict(detail)
            updated_detail["matched"] = True
            updated_detail["actual"] = "__matched_in_tool_result__"
            updated_detail["reason"] = "matched_in_tool_result"
            details[key] = updated_detail
            continue
        matched = False
    return {"matched": matched, "details": details}


def _is_prefix_chain(actual: List[str], expected: List[str]) -> bool:
    if len(actual) > len(expected):
        return False
    return actual == expected[: len(actual)]


def _next_expected_tool(actual: List[str], expected: List[str]) -> Optional[str]:
    if not _is_prefix_chain(actual, expected):
        return None
    if len(actual) >= len(expected):
        return None
    return expected[len(actual)]


def _build_router_follow_up_message(task: Dict[str, Any], actual_chain: List[str]) -> Optional[str]:
    expected_chain = [str(item) for item in task.get("expected_tool_chain", []) if item]
    next_tool = _next_expected_tool(actual_chain, expected_chain)
    if not next_tool:
        return None

    remaining = expected_chain[len(actual_chain) :]
    if not actual_chain:
        return (
            "开始，按默认参数继续执行这个完整流程："
            + " -> ".join(remaining)
            + "。如果前置结果缺失，请先执行链条里的前置工具。"
        )

    template = ROUTER_FOLLOW_UP_BY_TOOL.get(next_tool)
    if template:
        return template
    return "继续执行下一步：" + " -> ".join(remaining)


def _merge_trace_payloads(trace_payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not trace_payloads:
        return {}
    merged_steps: List[Dict[str, Any]] = []
    classifier_telemetry: List[Dict[str, Any]] = []
    ao_lifecycle_events: List[Dict[str, Any]] = []
    block_telemetry: List[Dict[str, Any]] = []
    clarification_telemetry: List[Dict[str, Any]] = []
    for turn_index, payload in enumerate(trace_payloads, start=1):
        for step in payload.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            merged_step = dict(step)
            merged_step.setdefault("eval_router_turn", turn_index)
            merged_steps.append(merged_step)
        for item in payload.get("classifier_telemetry", []) or []:
            if not isinstance(item, dict):
                continue
            merged_item = dict(item)
            merged_item.setdefault("eval_router_turn", turn_index)
            classifier_telemetry.append(merged_item)
        for item in payload.get("ao_lifecycle_events", []) or []:
            if not isinstance(item, dict):
                continue
            merged_item = dict(item)
            merged_item.setdefault("eval_router_turn", turn_index)
            ao_lifecycle_events.append(merged_item)
        for item in payload.get("block_telemetry", []) or []:
            if not isinstance(item, dict):
                continue
            merged_item = dict(item)
            merged_item.setdefault("eval_router_turn", turn_index)
            block_telemetry.append(merged_item)
        for item in payload.get("clarification_telemetry", []) or []:
            if not isinstance(item, dict):
                continue
            merged_item = dict(item)
            merged_item.setdefault("eval_router_turn", turn_index)
            clarification_telemetry.append(merged_item)
    # Phase 8.1.4c: propagate per-turn governance metadata from last turn.
    last_payload = trace_payloads[-1]
    reconciled_decisions: List[Dict[str, Any]] = []
    b_validator_filters: List[Dict[str, Any]] = []
    projected_chains: List[Dict[str, Any]] = []
    for turn_index, payload in enumerate(trace_payloads, start=1):
        rd = payload.get("reconciled_decision")
        if isinstance(rd, dict):
            rd_with_turn = dict(rd)
            rd_with_turn.setdefault("eval_router_turn", turn_index)
            reconciled_decisions.append(rd_with_turn)
        bf = payload.get("b_validator_filter")
        if isinstance(bf, dict):
            bf_with_turn = dict(bf)
            bf_with_turn.setdefault("eval_router_turn", turn_index)
            b_validator_filters.append(bf_with_turn)
        pc = payload.get("projected_chain")
        if isinstance(pc, dict):
            pc_with_turn = dict(pc)
            pc_with_turn.setdefault("eval_router_turn", turn_index)
            projected_chains.append(pc_with_turn)

    return {
        "steps": merged_steps,
        "final_stage": trace_payloads[-1].get("final_stage"),
        "eval_router_turns": len(trace_payloads),
        "classifier_telemetry": classifier_telemetry,
        "ao_lifecycle_events": ao_lifecycle_events,
        "block_telemetry": block_telemetry,
        "clarification_telemetry": clarification_telemetry,
        "reconciled_decision": reconciled_decisions[-1] if reconciled_decisions else last_payload.get("reconciled_decision"),
        "b_validator_filter": b_validator_filters[-1] if b_validator_filters else last_payload.get("b_validator_filter"),
        "projected_chain": projected_chains[-1] if projected_chains else last_payload.get("projected_chain"),
    }


def _merge_response_payloads(payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not payloads:
        return {}
    merged = dict(payloads[-1])
    merged["text"] = "\n\n".join(str(payload.get("text") or "") for payload in payloads if payload.get("text"))
    for key in ("chart_data", "table_data", "map_data", "download_file"):
        if merged.get(key):
            continue
        for payload in reversed(payloads[:-1]):
            if payload.get(key):
                merged[key] = payload.get(key)
                break
    return merged


def _is_geometry_gated_multistep_success(
    task: Dict[str, Any],
    *,
    actual_tool_chain: List[str],
    response_payload: Dict[str, Any],
    file_analysis: Optional[Dict[str, Any]],
    trace_has_error: bool,
) -> bool:
    if not (task.get("success_criteria") or {}).get("geometry_gated_halt_acceptable"):
        return False

    expected_tool_chain = [str(item) for item in task.get("expected_tool_chain", []) if item]
    expected_prefix = _geometry_gate_prefix(expected_tool_chain)
    if not expected_prefix:
        return False
    if actual_tool_chain and actual_tool_chain != expected_prefix:
        return False

    if _file_has_explicit_geometry(file_analysis):
        return False

    missing_field_diagnostics = (file_analysis or {}).get("missing_field_diagnostics")
    if isinstance(missing_field_diagnostics, dict):
        if str(missing_field_diagnostics.get("status") or "").strip().lower() != "complete":
            return False

    if trace_has_error:
        return False

    response_text = str(response_payload.get("text") or "")
    lowered_text = _normalize_match_text(response_text)
    has_geometry_mention = any(_normalize_match_text(cue) in lowered_text for cue in GEOMETRY_TEXT_CUES)
    has_meteorology_gate = any(_normalize_match_text(cue) in lowered_text for cue in METEOROLOGY_TEXT_CUES)
    has_emission_evidence = _has_emission_completion_signal(response_text)
    has_follow_up = (
        any(_normalize_match_text(cue) in lowered_text for cue in FOLLOW_UP_TEXT_CUES)
        or _response_text_is_asking_user(response_text)
    )
    if any(_normalize_match_text(cue) in lowered_text for cue in COMPLETED_DOWNSTREAM_TEXT_CUES):
        return False
    evidence_count = sum([has_geometry_mention or has_meteorology_gate, has_emission_evidence, has_follow_up])
    if evidence_count < 2:
        return False
    if not has_emission_evidence:
        return False

    expected_pollutants = task.get("expected_params", {}).get("pollutants", [])
    if expected_pollutants:
        if not any(_normalize_match_text(str(pollutant)) in lowered_text for pollutant in expected_pollutants):
            return False

    return True


def _normalize_task(sample: Dict[str, Any]) -> Dict[str, Any]:
    if "sample_id" in sample:
        expected_tool = sample.get("expected_tool_name")
        return {
            "id": sample["sample_id"],
            "category": "legacy",
            "description": sample.get("user_query", sample["sample_id"]),
            "user_message": sample.get("user_query", ""),
            "has_file": bool(sample.get("file_path")),
            "test_file": sample.get("file_path"),
            "expected_tool": expected_tool,
            "expected_tool_chain": [expected_tool] if expected_tool else [],
            "expected_params": sample.get("tool_arguments", {}),
            "expected_outputs": sample.get("expected_outputs", {}),
            "success_criteria": {},
            "follow_up_messages": sample.get("follow_up_messages", []),
            "smoke": bool(sample.get("smoke", False)),
            "__legacy_expected_success": bool(sample.get("expected_success", True)),
            "__legacy_tool_arguments": sample.get("tool_arguments", {}),
        }

    expected_tool = sample.get("expected_tool")
    chain = sample.get("expected_tool_chain")
    if not isinstance(chain, list):
        chain = [expected_tool] if expected_tool else []

    return {
        "id": sample.get("id", "unknown_task"),
        "category": sample.get("category", "uncategorized"),
        "description": sample.get("description", sample.get("user_message", "")),
        "user_message": sample.get("user_message", ""),
        "has_file": bool(sample.get("has_file")),
        "test_file": sample.get("test_file"),
        "expected_tool": expected_tool,
        "expected_tool_chain": [item for item in chain if item],
        "expected_params": sample.get("expected_params", {}),
        "expected_outputs": sample.get("expected_outputs", {}),
        "success_criteria": sample.get("success_criteria", {}),
        "follow_up_messages": sample.get("follow_up_messages", []),
        "smoke": bool(sample.get("smoke", False)),
        "__legacy_expected_success": None,
        "__legacy_tool_arguments": sample.get("tool_arguments"),
    }


def _load_benchmark_tasks(
    samples_path: Path,
    *,
    only_task: Optional[str] = None,
    category: Optional[str] = None,
    filter_categories: Optional[List[str]] = None,
    smoke: bool = False,
) -> List[Dict[str, Any]]:
    raw_samples = load_jsonl(samples_path)
    tasks = [_normalize_task(sample) for sample in raw_samples]
    if only_task:
        tasks = [task for task in tasks if only_task in task.get("expected_tool_chain", [])]
    if category:
        tasks = [task for task in tasks if task.get("category") == category]
    if filter_categories:
        allowed = {str(item).strip() for item in filter_categories if str(item).strip()}
        tasks = [task for task in tasks if task.get("category") in allowed]
    if smoke:
        tasks = [task for task in tasks if task.get("smoke")]
    return tasks


def _build_task_result(
    task: Dict[str, Any],
    *,
    executed_tool_calls: List[Dict[str, Any]],
    response_payload: Dict[str, Any],
    trace_payload: Optional[Dict[str, Any]],
    error_message: Optional[str],
    duration_ms: float,
    file_analysis: Optional[Dict[str, Any]],
    task_runtime_telemetry: Optional[Dict[str, Any]] = None,
    execution_error: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    trace_steps = _extract_trace_steps(trace_payload)
    trace_step_types = [str(step.get("step_type", "")).lower() for step in trace_steps]
    standardization_records = _collect_standardization_records(trace_steps)
    actual_tool_chain = [str(call.get("name")) for call in executed_tool_calls if call.get("name")]
    expected_tool_chain = task.get("expected_tool_chain", [])
    if task.get("category") == "user_revision" and executed_tool_calls:
        actual_arguments = executed_tool_calls[-1].get("arguments", {})
    else:
        actual_arguments = _merge_tool_arguments(executed_tool_calls)
    if not isinstance(actual_arguments, dict):
        actual_arguments = {}
    params_comparison = _comparison_with_result_fallback(
        actual_arguments,
        task.get("expected_params", {}),
        executed_tool_calls=executed_tool_calls,
        response_payload=response_payload,
    )
    response_text = str(response_payload.get("text") or "")

    text_result_implies_expected_tool = (
        not actual_tool_chain
        and len(expected_tool_chain) == 1
        and _response_text_has_expected_tool_result(response_text, expected_tool_chain)
    )
    tool_executed = bool(executed_tool_calls) or text_result_implies_expected_tool
    params_legal = params_comparison["matched"] if task.get("expected_params") else tool_executed
    result_has_data = (
        _has_result_payload(response_payload, executed_tool_calls)
        or _response_text_has_expected_tool_result(response_text, expected_tool_chain)
    )
    final_stage = str((trace_payload or {}).get("final_stage") or "")
    requires_user_response = (
        final_stage in LEGACY_NEEDS_USER_STAGE
        or any(step_type in {"clarification", "input_completion_required", "parameter_negotiation_required"} for step_type in trace_step_types)
        or _response_text_is_asking_user(response_text)
    )
    constraint_blocked = (
        "参数组合不合法" in response_text
        or _response_text_has_constraint_block(response_text)
        or any(
            record.get("record_type") == "cross_constraint_violation"
            for record in standardization_records
        )
    )
    constraint_warning = any(
        record.get("record_type") == "cross_constraint_warning"
        for record in standardization_records
    ) or _response_text_has_constraint_warning(response_text)
    trace_has_error = any(step.get("error") for step in trace_steps) or any(
        step_type == "error" for step_type in trace_step_types
    )

    criteria_actuals = {
        "tool_executed": tool_executed,
        "params_legal": params_legal,
        "result_has_data": result_has_data,
        "requires_user_response": requires_user_response,
        "constraint_blocked": constraint_blocked,
        "constraint_warning": constraint_warning,
        "trace_has_error": trace_has_error,
        "geometry_gated_halt_acceptable": False,
    }
    geometry_gated_success = _is_geometry_gated_multistep_success(
        task,
        actual_tool_chain=actual_tool_chain,
        response_payload=response_payload,
        file_analysis=file_analysis,
        trace_has_error=trace_has_error,
    )
    criteria_actuals["geometry_gated_halt_acceptable"] = geometry_gated_success
    tool_match = (
        _tool_chain_matches_for_task(task, actual_tool_chain, expected_tool_chain)
        or text_result_implies_expected_tool
        or geometry_gated_success
    )

    if task["__legacy_expected_success"] is not None:
        output_check = _check_outputs(response_payload, task.get("expected_outputs", {}))
        success = (
            (tool_executed == task["__legacy_expected_success"])
            and output_check["matched"]
            and tool_match
        )
    else:
        output_check = None
        success = geometry_gated_success or tool_match
        if not geometry_gated_success:
            for key, expected_value in (task.get("success_criteria") or {}).items():
                if key not in criteria_actuals:
                    continue
                success = success and (criteria_actuals[key] == expected_value)

    record = {
        "task_id": task["id"],
        "category": task["category"],
        "description": task["description"],
        "input": {
            "user_message": task["user_message"],
            "test_file": task.get("test_file"),
        },
        "file_analysis": file_analysis,
        "expected": {
            "tool_chain": task.get("expected_tool_chain", []),
            "params": task.get("expected_params", {}),
            "success_criteria": task.get("success_criteria", {}),
            "legacy_expected_success": task["__legacy_expected_success"],
            "legacy_expected_outputs": task.get("expected_outputs", {}),
        },
        "actual": {
            "tool_chain": actual_tool_chain,
            "tool_chain_match": tool_match,
            "geometry_gated_success": geometry_gated_success,
            "tool_calls": executed_tool_calls,
            "params_comparison": params_comparison,
            "criteria": criteria_actuals,
            "response_payload": response_payload,
            "trace_step_types": trace_step_types,
            "standardization_records": standardization_records,
            "final_stage": final_stage or None,
            "eval_router_turns": (trace_payload or {}).get("eval_router_turns"),
        },
        "success": success,
        "timing_ms": duration_ms,
        "error": error_message,
        "execution_error": (
            execution_error.get("repr") or execution_error.get("message")
            if isinstance(execution_error, dict)
            else None
        ),
        "execution_error_type": (
            execution_error.get("type")
            if isinstance(execution_error, dict)
            else None
        ),
        "execution_traceback": (
            execution_error.get("traceback")
            if isinstance(execution_error, dict)
            else None
        ),
        "output_check": output_check,
        "classifier_telemetry": list((trace_payload or {}).get("classifier_telemetry") or []),
        "ao_lifecycle_events": list((trace_payload or {}).get("ao_lifecycle_events") or []),
        "block_telemetry": list((trace_payload or {}).get("block_telemetry") or []),
        "clarification_telemetry": list((trace_payload or {}).get("clarification_telemetry") or []),
        "trace_steps": [
            {k: v for k, v in step.items()
             if k in ("step_type", "input_summary", "output_summary", "action", "confidence", "eval_router_turn")}
            for step in (trace_payload or {}).get("steps", [])
            if step.get("step_type") in ALL_SERIALIZED_STEP_TYPES
        ],
        "reconciled_decision": (trace_payload or {}).get("reconciled_decision"),
        "b_validator_filter": (trace_payload or {}).get("b_validator_filter"),
        "projected_chain": (trace_payload or {}).get("projected_chain"),
        "llm_reply_parser_stats_snapshot": get_call_stats(),
        "rate_limit_wait_ms": round(float((task_runtime_telemetry or {}).get("rate_limit_wait_ms") or 0.0), 2),
        "cache_hits": int((task_runtime_telemetry or {}).get("cache_hits") or 0),
    }
    failure_type = classify_failure(record)
    record["failure_type"] = failure_type
    record["recoverability"] = classify_recoverability(failure_type)
    return record


def _aggregate_llm_reply_parser_stats(logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate cumulative per-task LLMReplyParser snapshots into a final summary."""
    max_call = 0
    max_success = 0
    max_none = 0
    for log in logs:
        snap = log.get("llm_reply_parser_stats_snapshot")
        if isinstance(snap, dict):
            max_call = max(max_call, snap.get("call_count", 0))
            max_success = max(max_success, snap.get("success_count", 0))
            max_none = max(max_none, snap.get("none_count", 0))
    return {
        "call_count": max_call,
        "success_count": max_success,
        "none_count": max_none,
        "success_rate": round(max_success / max_call, 4) if max_call > 0 else 0.0,
    }


def _aggregate_metrics(
    logs: List[Dict[str, Any]],
    mode: str,
    skipped: int,
    *,
    run_status: str = "completed",
    subset: str = "full",
    cache_stats: Optional[Dict[str, Any]] = None,
    rate_limit_telemetry: Optional[Dict[str, Any]] = None,
    wall_clock_sec: Optional[float] = None,
) -> Dict[str, Any]:
    categories = sorted({str(log.get("category", "uncategorized")) for log in logs})
    success_count = sum(1 for log in logs if log.get("success"))
    tool_match_count = sum(
        1
        for log in logs
        if log.get("actual", {}).get("tool_chain_match")
        or not log.get("expected", {}).get("tool_chain")
    )
    params_legal_count = sum(
        1 for log in logs if log.get("actual", {}).get("criteria", {}).get("params_legal")
    )
    result_data_count = sum(
        1 for log in logs if log.get("actual", {}).get("criteria", {}).get("result_has_data")
    )

    by_category: Dict[str, Dict[str, Any]] = {}
    for category in categories:
        bucket = [log for log in logs if log.get("category") == category]
        by_category[category] = {
            "tasks": len(bucket),
            "success_rate": round(safe_div(sum(1 for log in bucket if log.get("success")), len(bucket)), 4),
            "tool_accuracy": round(
                safe_div(
                    sum(
                        1
                        for log in bucket
                        if log.get("actual", {}).get("tool_chain_match")
                        or not log.get("expected", {}).get("tool_chain")
                    ),
                    len(bucket),
                ),
                4,
            ),
        }

    infrastructure_health = _initial_infrastructure_health()
    for log in logs:
        status = str(log.get("infrastructure_status") or InfrastructureErrorType.OK.value)
        infrastructure_health.setdefault(status, 0)
        infrastructure_health[status] += 1

    total = len(logs)
    data_integrity = _compute_data_integrity(infrastructure_health, total)
    if run_status != "completed":
        data_integrity = "contaminated"

    classifier_turns = [
        item
        for log in logs
        for item in (log.get("classifier_telemetry") or [])
        if isinstance(item, dict)
    ]
    clarification_entries = [
        item
        for log in logs
        for item in (log.get("clarification_telemetry") or [])
        if isinstance(item, dict)
    ]
    new_or_revision_turns = sum(
        1
        for item in classifier_turns
        if str(item.get("classification") or "").upper() in {"NEW_AO", "REVISION"}
    )
    fresh_entries = [
        item for item in clarification_entries if str(item.get("trigger_mode") or "") == "fresh"
    ]
    stage2_entries = [item for item in clarification_entries if item.get("stage2_called")]
    stage2_latencies = [
        float(item.get("stage2_latency_ms"))
        for item in stage2_entries
        if item.get("stage2_latency_ms") is not None
    ]
    stage3_rejected_count = sum(
        1 for item in clarification_entries if list(item.get("stage3_rejected_slots") or [])
    )
    short_circuit_count = sum(
        1 for item in clarification_entries if str(item.get("final_decision") or "") == "clarify"
    )
    proceed_count = sum(
        1 for item in clarification_entries if str(item.get("final_decision") or "") == "proceed"
    )

    return {
        "task": "end2end",
        "mode": mode,
        "subset": subset,
        "run_status": run_status,
        "infrastructure_health": infrastructure_health,
        "data_integrity": data_integrity,
        "tasks": len(logs),
        "completion_rate": round(safe_div(success_count, len(logs)), 4),
        "tool_accuracy": round(safe_div(tool_match_count, len(logs)), 4),
        "parameter_legal_rate": round(safe_div(params_legal_count, len(logs)), 4),
        "result_data_rate": round(safe_div(result_data_count, len(logs)), 4),
        "skipped_tasks": skipped,
        "by_category": by_category,
        "cache_stats": cache_stats or {"hits": 0, "misses": 0, "hit_rate": 0.0},
        "rate_limit_telemetry": rate_limit_telemetry or {"rate_limit_wait_ms_total": 0.0},
        "clarification_contract_metrics": {
            "trigger_count": len(clarification_entries),
            "trigger_rate_over_new_revision_turns": round(
                safe_div(len(fresh_entries), new_or_revision_turns),
                4,
            ),
            "stage2_hit_rate": round(safe_div(len(stage2_entries), len(clarification_entries)), 4),
            "stage2_avg_latency_ms": round(safe_div(sum(stage2_latencies), len(stage2_latencies)), 2),
            "stage3_rejection_rate": round(safe_div(stage3_rejected_count, len(clarification_entries)), 4),
            "short_circuit_rate": round(safe_div(short_circuit_count, len(clarification_entries)), 4),
            "proceed_rate": round(safe_div(proceed_count, len(clarification_entries)), 4),
        },
        "llm_reply_parser": _aggregate_llm_reply_parser_stats(logs),
        "wall_clock_sec": round(float(wall_clock_sec or 0.0), 2),
    }


async def _run_router_task(
    task: Dict[str, Any],
    *,
    file_path: Optional[Path],
    eval_run_id: str = "",
) -> tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    """Run router mode, using bounded same-session follow-ups for expected multi-step chains."""
    run_ns = f"{eval_run_id}_" if eval_run_id else ""
    router = build_router(session_id=f"eval_{run_ns}{task['id']}", router_mode="router", fresh_session=True)
    expected_chain = [str(item) for item in task.get("expected_tool_chain", []) if item]
    scripted_follow_up_count = len(task.get("follow_up_messages", []) or [])
    max_turns = max(1, min(len(expected_chain) + scripted_follow_up_count + 2, 8))

    response_payloads: List[Dict[str, Any]] = []
    trace_payloads: List[Dict[str, Any]] = []
    executed_tool_calls: List[Dict[str, Any]] = []
    message = task["user_message"]
    scripted_follow_ups = [
        str(item).strip()
        for item in task.get("follow_up_messages", []) or []
        if str(item or "").strip()
    ]

    for turn_index in range(max_turns):
        trace: Dict[str, Any] = {}
        result = await router.chat(
            user_message=message,
            file_path=str(file_path) if file_path else None,
            trace=trace,
        )
        response_payloads.append(
            {
                "text": result.text,
                "chart_data": result.chart_data,
                "table_data": result.table_data,
                "map_data": result.map_data,
                "download_file": result.download_file,
            }
        )
        executed_tool_calls.extend(list(result.executed_tool_calls or []))
        trace_payloads.append(result.trace or trace)

        actual_chain = [str(call.get("name")) for call in executed_tool_calls if call.get("name")]
        if len(expected_chain) <= 1:
            if scripted_follow_ups:
                message = scripted_follow_ups.pop(0)
                continue
            break
        if actual_chain == expected_chain:
            if scripted_follow_ups:
                message = scripted_follow_ups.pop(0)
                continue
            break
        if not _is_prefix_chain(actual_chain, expected_chain):
            if scripted_follow_ups:
                message = scripted_follow_ups.pop(0)
                continue
            break

        follow_up = scripted_follow_ups.pop(0) if scripted_follow_ups else _build_router_follow_up_message(task, actual_chain)
        if not follow_up:
            break
        message = follow_up

        # If the router made no progress and the response is not asking for a continuation,
        # another turn is unlikely to unlock the expected chain.
        response_text = str(response_payloads[-1].get("text") or "")
        if turn_index > 0 and not result.executed_tool_calls and not _response_text_is_asking_user(response_text):
            break

    # Full AO state reset for evaluation isolation (Q4 / L1 isolation)
    context_store = getattr(getattr(router, "inner_router", None), "context_store", None)
    if context_store is not None:
        if hasattr(context_store, "clear_session_violations"):
            context_store.clear_session_violations()
        if hasattr(context_store, "clear_current_turn"):
            context_store.clear_current_turn()
    # Reset AO manager to prevent state leaking between tasks
    ao_manager = getattr(router, "ao_manager", None)
    if ao_manager is not None and hasattr(ao_manager, "reset"):
        ao_manager.reset()

    merged_response = _merge_response_payloads(response_payloads)
    tool_summaries = [
        str((call.get("result") or {}).get("summary") or "")
        for call in executed_tool_calls
        if isinstance(call.get("result"), dict) and (call.get("result") or {}).get("summary")
    ]
    if tool_summaries:
        merged_response["text"] = "\n\n".join(
            item for item in [str(merged_response.get("text") or ""), *tool_summaries] if item
        )
    return merged_response, executed_tool_calls, _merge_trace_payloads(trace_payloads)


async def _run_single_task_async(
    task: Dict[str, Any],
    *,
    mode: str,
    output_dir: Path,
    enable_file_analyzer: bool,
    resolved_task_timeout_sec: float,
    eval_run_id: str = "",
) -> Dict[str, Any]:
    file_path = resolve_project_path(task.get("test_file"))
    file_analysis = None
    if file_path and enable_file_analyzer:
        analyzer = FileAnalyzerTool()
        analysis_result = await analyzer.execute(file_path=str(file_path))
        file_analysis = analysis_result.data if analysis_result.success else None

    start = time.perf_counter()
    error_message: Optional[str] = None
    execution_error: Optional[Dict[str, Any]] = None
    response_payload: Dict[str, Any] = {}
    trace_payload: Optional[Dict[str, Any]] = None
    executed_tool_calls: List[Dict[str, Any]] = []
    infrastructure_status = InfrastructureErrorType.OK
    retry_count = 0
    executor = ToolExecutor() if mode == "tool" else None

    async def _execute_task_payload() -> tuple[Dict[str, Any], List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        if mode in {"router", "full"}:
            response, tool_calls, trace = await _run_router_task(
                task,
                file_path=file_path,
                eval_run_id=eval_run_id,
            )
            return response, tool_calls, trace
        if mode == "naive":
            run_ns = f"{eval_run_id}_" if eval_run_id else ""
            router = NaiveRouter(
                session_id=f"eval_naive_{run_ns}{task['id']}",
                tool_call_log_path=output_dir / "naive_tool_calls.jsonl",
            )
            trace = {}
            result = await router.chat(
                user_message=task["user_message"],
                file_path=str(file_path) if file_path else None,
                trace=trace,
            )
            response = {
                "text": result.text,
                "chart_data": result.chart_data,
                "table_data": result.table_data,
                "map_data": result.map_data,
                "download_file": result.download_file,
            }
            return response, list(result.executed_tool_calls or []), result.trace or trace

        expected_chain = task.get("expected_tool_chain", [])
        if len(expected_chain) != 1:
            raise ValueError("tool mode only supports single-step benchmark tasks")

        tool_name = expected_chain[0]
        tool_arguments = dict(task.get("__legacy_tool_arguments") or task.get("expected_params") or {})
        tool_result = await executor.execute(
            tool_name=tool_name,
            arguments=tool_arguments,
            file_path=str(file_path) if file_path else None,
        )
        response = {
            "text": tool_result.get("message"),
            "chart_data": tool_result.get("chart_data"),
            "table_data": tool_result.get("table_data"),
            "map_data": tool_result.get("map_data"),
            "download_file": tool_result.get("download_file"),
            "data": tool_result.get("data"),
        }
        tool_calls = [
            {
                "name": tool_name,
                "arguments": tool_arguments,
                "result": {
                    "success": bool(tool_result.get("success")),
                    "summary": tool_result.get("summary"),
                    "data": tool_result.get("data"),
                },
            }
        ]
        return response, tool_calls, tool_result.get("_trace")

    task_result, infrastructure_status, retry_count, infra_error = await _run_with_infrastructure_failsafe(
        _execute_task_payload,
        retry_delay_sec=1.0,
        timeout_sec=resolved_task_timeout_sec,
    )
    if task_result is not None:
        response_payload, executed_tool_calls, trace_payload = task_result
    else:
        if isinstance(infra_error, dict):
            error_message = str(infra_error.get("message") or "")
            execution_error = infra_error
        else:
            error_message = str(infra_error or "")
            execution_error = None

    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    return {
        "task": task,
        "executed_tool_calls": executed_tool_calls,
        "response_payload": response_payload,
        "trace_payload": trace_payload,
        "error_message": error_message,
        "execution_error": execution_error,
        "duration_ms": duration_ms,
        "file_analysis": file_analysis,
        "infrastructure_status": infrastructure_status,
        "retry_count": retry_count,
    }


def _run_single_task_sync(
    task: Dict[str, Any],
    *,
    mode: str,
    output_dir: Path,
    enable_file_analyzer: bool,
    resolved_task_timeout_sec: float,
    eval_run_id: str = "",
) -> Dict[str, Any]:
    token = CURRENT_EVAL_TASK_ID.set(task["id"])
    try:
        return asyncio.run(
            _run_single_task_async(
                task,
                mode=mode,
                output_dir=output_dir,
                enable_file_analyzer=enable_file_analyzer,
                resolved_task_timeout_sec=resolved_task_timeout_sec,
                eval_run_id=eval_run_id,
            )
        )
    finally:
        CURRENT_EVAL_TASK_ID.reset(token)


def run_end2end_evaluation(
    samples_path: Path,
    output_dir: Path,
    mode: str = "router",
    enable_file_analyzer: bool = True,
    enable_file_context_injection: bool = True,
    enable_executor_standardization: bool = True,
    macro_column_mapping_modes: tuple[str, ...] = ("direct", "ai", "fuzzy"),
    only_task: Optional[str] = None,
    category: Optional[str] = None,
    filter_categories: Optional[List[str]] = None,
    task_timeout_sec: Optional[float] = None,
    parallel: int = 1,
    qps_limit: float = 15.0,
    smoke: bool = False,
    cache_enabled: bool = True,
) -> Dict[str, Any]:
    tasks = _load_benchmark_tasks(
        samples_path,
        only_task=only_task,
        category=category,
        filter_categories=filter_categories,
        smoke=smoke,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    logs: List[Dict[str, Any]] = []
    run_status = "completed"
    skipped = 0
    resolved_task_timeout_sec = (
        float(task_timeout_sec)
        if task_timeout_sec is not None
        else float(os.getenv("BENCHMARK_TASK_TIMEOUT_SEC", "180"))
    )
    started_at = time.perf_counter()
    eval_run_id = f"{int(started_at * 1000)}"
    parallel = max(1, int(parallel or 1))
    task_telemetry = TaskTelemetryRegistry()
    rate_limiter = RequestRateLimiter(qps_limit, task_telemetry)
    tool_cache = ToolResultCache(
        cache_dir=PROJECT_ROOT / "evaluation" / "tool_cache",
        enabled=cache_enabled,
        project_root=PROJECT_ROOT,
    )

    def _build_record_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        task = payload["task"]
        record = _build_task_result(
            task,
            executed_tool_calls=payload.get("executed_tool_calls") or [],
            response_payload=payload.get("response_payload") or {},
            trace_payload=payload.get("trace_payload"),
            error_message=payload.get("error_message"),
            duration_ms=float(payload.get("duration_ms") or 0.0),
            file_analysis=payload.get("file_analysis"),
            task_runtime_telemetry=task_telemetry.snapshot_for_task(task["id"]),
            execution_error=payload.get("execution_error"),
        )
        infrastructure_status = payload.get("infrastructure_status", InfrastructureErrorType.UNKNOWN)
        record["infrastructure_status"] = infrastructure_status.value
        record["retry_count"] = int(payload.get("retry_count") or 0)
        return record

    consecutive_network_failed = 0
    with runtime_overrides(
        enable_file_analyzer=enable_file_analyzer,
        enable_file_context_injection=enable_file_context_injection,
        enable_executor_standardization=enable_executor_standardization,
        macro_column_mapping_modes=macro_column_mapping_modes,
    ), _evaluation_runtime_hooks(
        rate_limiter=rate_limiter,
        task_telemetry=task_telemetry,
        tool_cache=tool_cache,
    ):
        rebuild_tool_registry()
        if parallel == 1:
            for task_index, task in enumerate(tasks, start=1):
                payload = _run_single_task_sync(
                    task,
                    mode=mode,
                    output_dir=output_dir,
                    enable_file_analyzer=enable_file_analyzer,
                    resolved_task_timeout_sec=resolved_task_timeout_sec,
                    eval_run_id=eval_run_id,
                )
                record = _build_record_from_payload(payload)
                logs.append(record)
                infrastructure_status = payload.get("infrastructure_status", InfrastructureErrorType.UNKNOWN)
                if infrastructure_status == InfrastructureErrorType.TRANSIENT_RETRIED:
                    consecutive_network_failed = 0
                elif infrastructure_status == InfrastructureErrorType.NETWORK_FAILED:
                    consecutive_network_failed += 1
                elif infrastructure_status != InfrastructureErrorType.OK:
                    consecutive_network_failed = 0
                else:
                    consecutive_network_failed = 0

                if infrastructure_status == InfrastructureErrorType.BILLING_FAILED:
                    run_status = "aborted_billing"
                    print(
                        f"BENCHMARK ABORTED at task #{task_index} due to billing failure",
                        file=sys.stderr,
                    )
                    break
                if consecutive_network_failed >= 5:
                    run_status = "aborted_network"
                    print(
                        f"BENCHMARK ABORTED at task #{task_index} due to consecutive network failures",
                        file=sys.stderr,
                    )
                    break
        else:
            import concurrent.futures

            executor = ThreadPoolExecutor(max_workers=parallel)
            in_flight: Dict[concurrent.futures.Future, tuple[int, Dict[str, Any]]] = {}
            next_task_index = 0
            abort_requested = False
            try:
                while next_task_index < min(parallel, len(tasks)):
                    task = tasks[next_task_index]
                    future = executor.submit(
                        _run_single_task_sync,
                        task,
                        mode=mode,
                        output_dir=output_dir,
                        enable_file_analyzer=enable_file_analyzer,
                        resolved_task_timeout_sec=resolved_task_timeout_sec,
                        eval_run_id=eval_run_id,
                    )
                    in_flight[future] = (next_task_index + 1, task)
                    next_task_index += 1

                while in_flight:
                    done, _ = concurrent.futures.wait(
                        in_flight.keys(),
                        return_when=concurrent.futures.FIRST_COMPLETED,
                    )
                    for future in done:
                        task_index, task = in_flight.pop(future)
                        try:
                            payload = future.result()
                        except Exception as exc:  # noqa: BLE001
                            error_payload = _execution_error_payload(exc)
                            payload = {
                                "task": task,
                                "executed_tool_calls": [],
                                "response_payload": {},
                                "trace_payload": None,
                                "error_message": str(error_payload.get("message") or ""),
                                "execution_error": error_payload,
                                "duration_ms": 0.0,
                                "file_analysis": None,
                                "infrastructure_status": (
                                    InfrastructureErrorType.OK
                                    if isinstance(exc, PRODUCTION_EXCEPTION_TYPES)
                                    else classify_infrastructure_error(exc)
                                ),
                                "retry_count": 0,
                            }
                        record = _build_record_from_payload(payload)
                        logs.append(record)
                        infrastructure_status = payload.get("infrastructure_status", InfrastructureErrorType.UNKNOWN)
                        if infrastructure_status == InfrastructureErrorType.TRANSIENT_RETRIED:
                            consecutive_network_failed = 0
                        elif infrastructure_status == InfrastructureErrorType.NETWORK_FAILED:
                            consecutive_network_failed += 1
                        elif infrastructure_status != InfrastructureErrorType.OK:
                            consecutive_network_failed = 0
                        else:
                            consecutive_network_failed = 0

                        if infrastructure_status == InfrastructureErrorType.BILLING_FAILED:
                            run_status = "aborted_billing"
                            abort_requested = True
                            print(
                                f"BENCHMARK ABORTED at task #{task_index} due to billing failure",
                                file=sys.stderr,
                            )
                        elif consecutive_network_failed >= 5:
                            run_status = "aborted_network"
                            abort_requested = True
                            print(
                                f"BENCHMARK ABORTED at task #{task_index} due to consecutive network failures",
                                file=sys.stderr,
                            )

                        if abort_requested:
                            continue
                        if next_task_index < len(tasks):
                            next_task = tasks[next_task_index]
                            new_future = executor.submit(
                                _run_single_task_sync,
                                next_task,
                                mode=mode,
                                output_dir=output_dir,
                                enable_file_analyzer=enable_file_analyzer,
                                resolved_task_timeout_sec=resolved_task_timeout_sec,
                                eval_run_id=eval_run_id,
                            )
                            in_flight[new_future] = (next_task_index + 1, next_task)
                            next_task_index += 1
                    if abort_requested:
                        for future in list(in_flight.keys()):
                            future.cancel()
                        break
            finally:
                executor.shutdown(wait=not abort_requested, cancel_futures=abort_requested)

    logs = sorted(logs, key=lambda row: str(row.get("task_id") or ""))
    metrics = _aggregate_metrics(
        logs,
        mode=mode,
        skipped=skipped,
        run_status=run_status,
        subset="smoke" if smoke else "full",
        cache_stats=tool_cache.stats(),
        rate_limit_telemetry=task_telemetry.aggregate(),
        wall_clock_sec=time.perf_counter() - started_at,
    )
    metrics["logs_path"] = str(output_dir / "end2end_logs.jsonl")
    write_jsonl(output_dir / "end2end_logs.jsonl", logs)
    write_json(output_dir / "end2end_metrics.json", metrics)
    return metrics


def main() -> None:
    reset_call_stats()  # Round 4b: zero LLMReplyParser counters per eval invocation
    parser = argparse.ArgumentParser(description="Evaluate end-to-end benchmark tasks.")
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR / f"end2end_{now_ts()}")
    parser.add_argument("--mode", choices=["router", "full", "naive", "tool"], default="router")
    parser.add_argument("--parallel", type=int, default=8)
    parser.add_argument("--qps-limit", type=float, default=15.0)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--disable-file-analyzer", action="store_true")
    parser.add_argument("--disable-file-context-injection", action="store_true")
    parser.add_argument("--disable-executor-standardization", action="store_true")
    parser.add_argument("--cache", dest="cache_enabled", action="store_true", default=True)
    parser.add_argument("--no-cache", dest="cache_enabled", action="store_false")
    parser.add_argument("--clear-cache", action="store_true")
    parser.add_argument("--macro-modes", default="direct,ai,fuzzy")
    parser.add_argument("--only-task")
    parser.add_argument("--category")
    parser.add_argument("--filter-categories", default="")
    parser.add_argument("--task-timeout-sec", type=float, default=None)
    args = parser.parse_args()

    if args.clear_cache:
        cache = ToolResultCache(
            cache_dir=PROJECT_ROOT / "evaluation" / "tool_cache",
            enabled=True,
            project_root=PROJECT_ROOT,
        )
        cache.invalidate_all()
        print(json.dumps({"cache_cleared": True}, ensure_ascii=False, indent=2))
        return

    metrics = run_end2end_evaluation(
        samples_path=args.samples,
        output_dir=args.output_dir,
        mode=args.mode,
        enable_file_analyzer=not args.disable_file_analyzer,
        enable_file_context_injection=not args.disable_file_context_injection,
        enable_executor_standardization=not args.disable_executor_standardization,
        macro_column_mapping_modes=tuple(mode.strip() for mode in args.macro_modes.split(",") if mode.strip()),
        only_task=args.only_task,
        category=args.category,
        filter_categories=[item.strip() for item in str(args.filter_categories or "").split(",") if item.strip()],
        task_timeout_sec=args.task_timeout_sec,
        parallel=args.parallel,
        qps_limit=args.qps_limit,
        smoke=args.smoke,
        cache_enabled=args.cache_enabled,
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
