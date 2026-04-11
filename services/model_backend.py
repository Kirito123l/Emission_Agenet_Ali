"""
Abstracted model backends for parameter standardization.

Backends supported:
- Remote LLM API
- Local fine-tuned/distilled model
- No-op rule-only mode
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from config import get_config

if TYPE_CHECKING:
    from services.standardizer import StandardizationResult


logger = logging.getLogger(__name__)


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _config_value(config: Any, key: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


def _candidate_lookup(candidates: List[str], aliases: Dict[str, List[str]]) -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    for candidate in candidates:
        lookup[str(candidate).strip().lower()] = candidate
        for alias in aliases.get(candidate, []):
            lookup[str(alias).strip().lower()] = candidate
    return lookup


class ParameterModelBackend(ABC):
    """Abstract interface for model-based parameter standardization."""

    def standardize(
        self,
        param_type: str,
        raw_value: str,
        candidates: List[str],
        aliases: Dict[str, List[str]],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional["StandardizationResult"]:
        """Backward-compatible alias for older callers."""
        return self.infer(param_type, raw_value, candidates, aliases, context)

    @abstractmethod
    def infer(
        self,
        param_type: str,
        raw_value: str,
        candidates: List[str],
        aliases: Dict[str, List[str]],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional["StandardizationResult"]:
        """Attempt to standardize a parameter value using model inference."""


class APIModelBackend(ParameterModelBackend):
    """Backend that uses the remote OpenAI-compatible API."""

    def __init__(self, config: Optional[Any] = None):
        self._config = config or {}
        self._backend = str(_config_value(self._config, "llm_backend", "api") or "api").lower()
        self._model = _config_value(self._config, "llm_model")
        self._timeout = float(_config_value(self._config, "llm_timeout", 5.0))
        self._max_retries = int(_config_value(self._config, "llm_max_retries", 1))
        self._enabled = bool(_config_value(self._config, "llm_enabled", True))
        self._consecutive_failures = 0
        self._disable_after_failures = max(int(_config_value(self._config, "llm_disable_after_failures", 3)), 1)
        self._disabled_reason: Optional[str] = None
        self._client = None

    def infer(
        self,
        param_type: str,
        raw_value: str,
        candidates: List[str],
        aliases: Dict[str, List[str]],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional["StandardizationResult"]:
        if not self._enabled or self._backend != "api":
            return None

        if self._consecutive_failures >= self._disable_after_failures:
            logger.warning(
                "LLM standardization temporarily disabled for this backend after %d consecutive failures: %s",
                self._consecutive_failures,
                self._disabled_reason or "unknown error",
            )
            return None

        try:
            payload = self._call_llm(param_type, raw_value, candidates, aliases, context)
        except Exception as exc:
            self._disabled_reason = str(exc)
            self._consecutive_failures += 1
            logger.warning(
                "LLM standardization failed for %s=%r (consecutive_failures=%d/%d): %s",
                param_type,
                raw_value,
                self._consecutive_failures,
                self._disable_after_failures,
                exc,
            )
            return None

        if not isinstance(payload, dict):
            return None

        self._consecutive_failures = 0
        self._disabled_reason = None

        raw_choice = payload.get("value")
        if raw_choice is None:
            return None

        normalized = _candidate_lookup(candidates, aliases).get(str(raw_choice).strip().lower())
        if not normalized:
            logger.warning(
                "LLM returned invalid candidate for %s=%r: %r",
                param_type,
                raw_value,
                raw_choice,
            )
            return None

        try:
            confidence = float(payload.get("confidence", 0.8) or 0.8)
        except (TypeError, ValueError):
            confidence = 0.8

        from services.standardizer import StandardizationResult

        return StandardizationResult(
            success=True,
            original=_clean_string(raw_value),
            normalized=normalized,
            strategy="llm",
            confidence=min(max(confidence, 0.0), 0.95),
        )

    def _get_client(self):
        if self._client is not None:
            return self._client

        from services.llm_client import LLMClientService

        client = LLMClientService(model=self._model, purpose="standardizer")
        if abs(getattr(client, "_request_timeout", 120.0) - self._timeout) > 1e-9:
            client._request_timeout = self._timeout
            client._client_proxy = client._create_openai_client(use_proxy=True) if client._proxy else None
            client._client_direct = client._create_openai_client(use_proxy=False)
            client.client = (
                client._client_proxy
                if client._use_proxy_primary and client._client_proxy
                else client._client_direct
            )
        self._client = client
        return self._client

    def _call_llm(
        self,
        param_type: str,
        raw_value: str,
        candidates: List[str],
        aliases: Dict[str, List[str]],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        prompt = self._build_prompt(param_type, raw_value, candidates, aliases)
        system = "你是一个参数标准化助手。只能从给定候选中选择，不要解释，不要输出 Markdown。"
        last_error = None

        for _ in range(max(self._max_retries, 0) + 1):
            try:
                client = self._get_client()
                response = client.chat_json_sync(prompt=prompt, system=system)
                return response if isinstance(response, dict) else None
            except Exception as exc:
                last_error = exc
                continue

        if last_error is not None:
            raise last_error
        return None

    def _build_prompt(
        self,
        param_type: str,
        raw_value: str,
        candidates: List[str],
        aliases: Dict[str, List[str]],
    ) -> str:
        descriptions = {
            "vehicle_type": "车辆类型（MOVES 机动车分类）",
            "pollutant": "大气污染物种类",
            "season": "季节",
            "road_type": "道路功能分类",
            "meteorology": "气象条件预设",
            "stability_class": "大气稳定度等级（Pasquill-Gifford 分类）",
        }
        desc = descriptions.get(param_type, param_type)

        candidate_lines = []
        for candidate in candidates:
            alias_items = aliases.get(candidate, [])[:3]
            if alias_items:
                candidate_lines.append(f"- {candidate}（{', '.join(alias_items)}）")
            else:
                candidate_lines.append(f"- {candidate}")

        return (
            f"将以下{desc}参数值映射到标准值。\n"
            f"输入：\"{_clean_string(raw_value)}\"\n"
            f"标准值列表：\n{chr(10).join(candidate_lines)}\n\n"
            "只返回 JSON："
            '{"value": "匹配的标准值或null", "confidence": 0.0到1.0}'
        )


class LocalModelBackend(ParameterModelBackend):
    """Backend that uses the local standardizer client."""

    def __init__(self, config: Optional[Any] = None):
        runtime_config = get_config()
        local_config = _config_value(config, "local_standardizer_config", None)
        if local_config is None:
            local_config = getattr(runtime_config, "local_standardizer_config", {})

        self._config = dict(local_config or {})
        self._enabled = bool(
            self._config.get("enabled", False)
            or _config_value(config, "use_local_standardizer", False)
            or getattr(runtime_config, "use_local_standardizer", False)
        )
        self._config["enabled"] = self._enabled
        self._client = None

    def infer(
        self,
        param_type: str,
        raw_value: str,
        candidates: List[str],
        aliases: Dict[str, List[str]],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional["StandardizationResult"]:
        if not self._enabled:
            return None

        method_name = {
            "vehicle_type": "standardize_vehicle",
            "pollutant": "standardize_pollutant",
        }.get(param_type)
        if method_name is None:
            return None

        client = self._get_client()
        if client is None:
            return None

        try:
            raw_result = getattr(client, method_name)(_clean_string(raw_value))
        except Exception as exc:
            logger.warning("Local model failed for %s=%r: %s", param_type, raw_value, exc)
            return None

        confidence = 0.9
        normalized_candidate = None
        if isinstance(raw_result, dict):
            normalized_candidate = (
                raw_result.get("standard_name")
                or raw_result.get("normalized")
                or raw_result.get("result")
            )
            try:
                confidence = float(raw_result.get("confidence", 0.9) or 0.9)
            except (TypeError, ValueError):
                confidence = 0.9
        elif isinstance(raw_result, str):
            normalized_candidate = raw_result.strip()

        if not normalized_candidate or confidence < 0.9:
            return None

        normalized = _candidate_lookup(candidates, aliases).get(str(normalized_candidate).strip().lower())
        if not normalized:
            return None

        from services.standardizer import StandardizationResult

        return StandardizationResult(
            success=True,
            original=_clean_string(raw_value),
            normalized=normalized,
            strategy="local_model",
            confidence=round(confidence, 2),
        )

    def _get_client(self):
        if self._client is not None:
            return self._client

        from shared.standardizer.local_client import get_local_standardizer_client

        self._client = get_local_standardizer_client(self._config)
        return self._client


class NoModelBackend(ParameterModelBackend):
    """Rule-only backend that never attempts model inference."""

    def infer(
        self,
        param_type: str,
        raw_value: str,
        candidates: List[str],
        aliases: Dict[str, List[str]],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional["StandardizationResult"]:
        return None


def create_local_model_backend(config: Optional[Any] = None) -> ParameterModelBackend:
    """Create a local-only model backend."""
    backend = LocalModelBackend(config)
    if _config_value(backend._config, "enabled", False):
        return backend
    return NoModelBackend()


def create_model_backend(config: Optional[Any] = None) -> ParameterModelBackend:
    """Create the configured parameter standardization backend."""
    resolved_config = config if config is not None else get_config()
    model_enabled = bool(
        _config_value(
            resolved_config,
            "llm_enabled",
            _config_value(resolved_config, "enable_llm_standardization", True),
        )
    )
    if not model_enabled:
        return NoModelBackend()
    if _config_value(resolved_config, "use_local_standardizer", False):
        return LocalModelBackend(resolved_config)
    if model_enabled:
        return APIModelBackend(resolved_config)
    return NoModelBackend()
