"""
Standardization Engine - declarative, pluggable parameter standardization.

Architecture:
    Tool schema / registry
        -> StandardizationEngine
        -> RuleBackend / LLMBackend
        -> StandardizationResult

Cascade:
    exact -> alias -> fuzzy -> LLM -> default -> abstain

Compatibility notes:
    - The legacy rule implementation in services.standardizer remains the source
      of truth for default behavior.
    - Default configuration preserves current executor behavior.
    - LLM fallback is only attempted when rules fail or when a non-empty value
      would otherwise fall back to a default.
"""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from copy import deepcopy
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config import get_config
from services.config_loader import ConfigLoader
from services.standardizer import StandardizationResult, UnifiedStandardizer, get_standardizer

logger = logging.getLogger(__name__)


PARAM_TYPE_REGISTRY: Dict[str, str] = {
    "vehicle_type": "vehicle_type",
    "pollutant": "pollutant",
    "pollutants": "pollutant_list",
    "season": "season",
    "road_type": "road_type",
    "meteorology": "meteorology",
    "stability_class": "stability_class",
}

LEGACY_FUZZY_THRESHOLDS: Dict[str, float] = {
    "vehicle_type": 0.70,
    "pollutant": 0.80,
    "season": 0.60,
    "road_type": 0.60,
    "meteorology": 0.75,
    "stability_class": 0.75,
}

PARAM_TYPE_CONFIG: Dict[str, Dict[str, Any]] = {
    "vehicle_type": {
        "has_default": False,
        "fuzzy_enabled": True,
        "llm_enabled": True,
        "description": "MOVES vehicle source type",
    },
    "pollutant": {
        "has_default": False,
        "fuzzy_enabled": True,
        "llm_enabled": True,
        "description": "Emission pollutant species",
    },
    "pollutant_list": {
        "is_list": True,
        "element_type": "pollutant",
        "description": "List of pollutants",
    },
    "season": {
        "has_default": True,
        "default_value": "夏季",
        "fuzzy_enabled": True,
        "llm_enabled": True,
        "description": "Season for emission factor selection",
    },
    "road_type": {
        "has_default": True,
        "default_value": "快速路",
        "fuzzy_enabled": True,
        "llm_enabled": True,
        "description": "Road functional classification",
    },
    "meteorology": {
        "has_default": False,
        "fuzzy_enabled": True,
        "llm_enabled": True,
        "passthrough_patterns": [r"\.sfc$", r"^custom$"],
        "description": "Meteorological condition preset or mode",
    },
    "stability_class": {
        "has_default": False,
        "fuzzy_enabled": True,
        "llm_enabled": True,
        "description": "Atmospheric stability class (Pasquill-Gifford)",
    },
}

_FAILURE_MESSAGES: Dict[str, Tuple[str, int]] = {
    "vehicle_type": ("Cannot standardize vehicle type '{value}'. Suggestions: {suggestions}", 5),
    "pollutant": ("Cannot standardize pollutant '{value}'. Suggestions: {suggestions}", 5),
    "meteorology": ("Cannot standardize meteorology '{value}'. Suggestions: {suggestions}", 6),
    "stability_class": ("Cannot standardize stability class '{value}'. Suggestions: {suggestions}", 6),
}


def _merge_config(base: Dict[str, Any], override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = deepcopy(base)
    for key, value in dict(override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _dedupe(items: Sequence[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


class BatchStandardizationError(Exception):
    """Raised when batch standardization should surface a user-facing clarification."""

    def __init__(
        self,
        message: str,
        param_name: str,
        original_value: Any,
        suggestions: Optional[List[str]] = None,
        records: Optional[List[Dict[str, Any]]] = None,
        negotiation_eligible: bool = False,
        trigger_reason: Optional[str] = None,
    ):
        super().__init__(message)
        self.param_name = param_name
        self.original_value = original_value
        self.suggestions = suggestions or []
        self.records = records or []
        self.negotiation_eligible = negotiation_eligible
        self.trigger_reason = trigger_reason


class StandardizationBackend(ABC):
    """Abstract backend interface."""

    @abstractmethod
    def standardize(
        self,
        param_type: str,
        raw_value: str,
        candidates: List[str],
        aliases: Dict[str, List[str]],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[StandardizationResult]:
        """Attempt to standardize a value."""


class RuleBackend(StandardizationBackend):
    """
    Compatibility-first rule backend.

    By default it delegates to the legacy standardizer to preserve exact output.
    When a custom fuzzy threshold is configured, it replays the rule matching for
    that parameter type with the overridden threshold.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None, standardizer: Optional[UnifiedStandardizer] = None):
        self._config = config or {}
        self._standardizer = standardizer or get_standardizer()
        self._mappings = ConfigLoader.load_mappings()

    @property
    def rule_standardizer(self) -> UnifiedStandardizer:
        return self._standardizer

    def standardize(
        self,
        param_type: str,
        raw_value: str,
        candidates: List[str],
        aliases: Dict[str, List[str]],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[StandardizationResult]:
        method_map = {
            "vehicle_type": self._standardizer.standardize_vehicle_detailed,
            "pollutant": self._standardizer.standardize_pollutant_detailed,
            "season": self._standardizer.standardize_season,
            "road_type": self._standardizer.standardize_road_type,
            "meteorology": self._standardizer.standardize_meteorology,
            "stability_class": self._standardizer.standardize_stability_class,
        }
        method = method_map.get(param_type)
        if method is None:
            return None

        legacy_result = method(raw_value)
        if not self._needs_custom_threshold(param_type):
            return legacy_result

        return self._standardize_with_custom_threshold(param_type, raw_value)

    def _needs_custom_threshold(self, param_type: str) -> bool:
        legacy = LEGACY_FUZZY_THRESHOLDS.get(param_type)
        if legacy is None:
            return False
        threshold = self._threshold_for(param_type)
        return abs(threshold - legacy) > 1e-9

    def _threshold_for(self, param_type: str) -> float:
        thresholds = self._config.get("fuzzy_thresholds", {}) or {}
        if param_type in thresholds:
            return float(thresholds[param_type])
        if param_type in LEGACY_FUZZY_THRESHOLDS:
            return float(self._config.get("fuzzy_threshold", LEGACY_FUZZY_THRESHOLDS[param_type]))
        return 1.0

    def _lookup_for(self, param_type: str) -> Dict[str, str]:
        lookup_map = {
            "vehicle_type": self._standardizer.vehicle_lookup,
            "pollutant": self._standardizer.pollutant_lookup,
            "season": self._standardizer.season_lookup,
            "road_type": self._standardizer.road_type_lookup,
            "meteorology": self._standardizer.meteorology_lookup,
            "stability_class": self._standardizer.stability_lookup,
        }
        return lookup_map.get(param_type, {})

    def _standardize_with_custom_threshold(self, param_type: str, raw_value: str) -> StandardizationResult:
        cleaned = _clean_string(raw_value)
        if not cleaned:
            return self._legacy_blank_result(param_type, raw_value)

        lookup = self._lookup_for(param_type)
        cleaned_lower = cleaned.lower()
        normalized = lookup.get(cleaned_lower)
        if normalized:
            strategy = "exact" if cleaned == normalized else "alias"
            confidence = 1.0 if strategy == "exact" else 0.95
            return StandardizationResult(
                success=True,
                original=cleaned,
                normalized=normalized,
                strategy=strategy,
                confidence=confidence,
            )

        best_match = None
        best_score = 0
        for alias, standard_name in lookup.items():
            score = self._standardizer._fuzzy_ratio(cleaned, alias)
            if score > best_score:
                best_score = score
                best_match = standard_name

        threshold = int(round(self._threshold_for(param_type) * 100))
        if best_match and best_score >= threshold:
            return StandardizationResult(
                success=True,
                original=cleaned,
                normalized=best_match,
                strategy="fuzzy",
                confidence=round(best_score / 100, 2),
            )

        if param_type == "vehicle_type":
            local_result = self._standardizer._try_local_standardization(
                cleaned,
                self._standardizer.vehicle_lookup,
                "standardize_vehicle",
            )
            if local_result:
                return local_result
            return StandardizationResult(
                success=False,
                original=cleaned,
                strategy="abstain",
                confidence=0.0,
                suggestions=self._standardizer.get_vehicle_suggestions(cleaned, top_k=5),
            )

        if param_type == "pollutant":
            local_result = self._standardizer._try_local_standardization(
                cleaned,
                self._standardizer.pollutant_lookup,
                "standardize_pollutant",
            )
            if local_result:
                return local_result
            return StandardizationResult(
                success=False,
                original=cleaned,
                strategy="abstain",
                confidence=0.0,
                suggestions=self._standardizer.get_pollutant_suggestions(cleaned, top_k=5),
            )

        if param_type == "season":
            return StandardizationResult(
                success=True,
                original=cleaned,
                normalized=self._standardizer.season_default,
                strategy="default",
                confidence=0.5,
                suggestions=sorted(set(self._standardizer.season_lookup.values())),
            )

        if param_type == "road_type":
            return StandardizationResult(
                success=True,
                original=cleaned,
                normalized=self._standardizer.road_type_default,
                strategy="default",
                confidence=0.5,
                suggestions=sorted(set(self._standardizer.road_type_lookup.values())),
            )

        if param_type == "meteorology":
            return StandardizationResult(
                success=False,
                original=cleaned,
                strategy="abstain",
                confidence=0.0,
                suggestions=list(self._standardizer.meteorology_presets),
            )

        if param_type == "stability_class":
            return StandardizationResult(
                success=False,
                original=cleaned,
                strategy="abstain",
                confidence=0.0,
                suggestions=list(self._standardizer.stability_classes),
            )

        return StandardizationResult(success=False, original=cleaned, strategy="abstain")

    def _legacy_blank_result(self, param_type: str, raw_value: Any) -> StandardizationResult:
        method_map = {
            "vehicle_type": self._standardizer.standardize_vehicle_detailed,
            "pollutant": self._standardizer.standardize_pollutant_detailed,
            "season": self._standardizer.standardize_season,
            "road_type": self._standardizer.standardize_road_type,
            "meteorology": self._standardizer.standardize_meteorology,
            "stability_class": self._standardizer.standardize_stability_class,
        }
        return method_map[param_type](raw_value)


class LLMBackend(StandardizationBackend):
    """
    LLM-based standardization for unresolved rule cases.

    The current implementation uses the project's OpenAI-compatible client.
    A future local backend can be introduced behind the same interface.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}
        self._backend = str(self._config.get("llm_backend", "api") or "api").lower()
        self._model = self._config.get("llm_model")
        self._timeout = float(self._config.get("llm_timeout", 5.0))
        self._max_retries = int(self._config.get("llm_max_retries", 1))
        self._enabled = bool(self._config.get("llm_enabled", True))
        self._client = None

    def standardize(
        self,
        param_type: str,
        raw_value: str,
        candidates: List[str],
        aliases: Dict[str, List[str]],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[StandardizationResult]:
        if not self._enabled or self._backend != "api":
            return None

        try:
            payload = self._call_llm(param_type, raw_value, candidates, aliases, context)
        except Exception as exc:
            logger.warning("LLM standardization failed for %s=%r: %s", param_type, raw_value, exc)
            return None

        if not isinstance(payload, dict):
            return None

        raw_choice = payload.get("value")
        if raw_choice is None:
            return None

        candidate_lookup = {candidate.lower(): candidate for candidate in candidates}
        normalized = candidate_lookup.get(str(raw_choice).strip().lower())
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
            client.client = client._client_proxy if client._use_proxy_primary and client._client_proxy else client._client_direct
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


class StandardizationEngine:
    """Central standardization coordinator."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        runtime_config = get_config()
        base_config = getattr(runtime_config, "standardization_config", {})
        self._config = _merge_config(base_config, config)
        self._rule_backend = RuleBackend(config=self._config)
        self._llm_backend = self._init_llm_backend()
        self._param_registry = self._load_param_registry()
        self._catalog = self._load_catalog()

    @property
    def rule_backend(self) -> RuleBackend:
        return self._rule_backend

    @property
    def rule_standardizer(self) -> UnifiedStandardizer:
        return self._rule_backend.rule_standardizer

    def _init_llm_backend(self) -> Optional[LLMBackend]:
        return LLMBackend(self._config)

    def _load_param_registry(self) -> Dict[str, str]:
        return dict(PARAM_TYPE_REGISTRY)

    def _load_catalog(self) -> Dict[str, Dict[str, Any]]:
        mappings = ConfigLoader.load_mappings()
        catalog: Dict[str, Dict[str, Any]] = {}

        vehicle_aliases: Dict[str, List[str]] = {}
        vehicle_candidates: List[str] = []
        for entry in mappings.get("vehicle_types", []):
            standard_name = entry.get("standard_name")
            if not standard_name:
                continue
            vehicle_candidates.append(standard_name)
            aliases = []
            if entry.get("display_name_zh"):
                aliases.append(str(entry["display_name_zh"]))
            aliases.extend(str(alias) for alias in entry.get("aliases", []) if alias)
            vehicle_aliases[standard_name] = _dedupe(aliases)
        catalog["vehicle_type"] = {"candidates": vehicle_candidates, "aliases": vehicle_aliases}

        pollutant_aliases: Dict[str, List[str]] = {}
        pollutant_candidates: List[str] = []
        for entry in mappings.get("pollutants", []):
            standard_name = entry.get("standard_name")
            if not standard_name:
                continue
            pollutant_candidates.append(standard_name)
            aliases = []
            if entry.get("display_name_zh"):
                aliases.append(str(entry["display_name_zh"]))
            aliases.extend(str(alias) for alias in entry.get("aliases", []) if alias)
            pollutant_aliases[standard_name] = _dedupe(aliases)
        catalog["pollutant"] = {"candidates": pollutant_candidates, "aliases": pollutant_aliases}

        season_aliases: Dict[str, List[str]] = {}
        season_candidates: List[str] = []
        seasons = mappings.get("seasons", {})
        if isinstance(seasons, list):
            for entry in seasons:
                standard_name = entry.get("standard_name")
                if not standard_name:
                    continue
                season_candidates.append(standard_name)
                season_aliases[standard_name] = _dedupe(
                    [str(alias) for alias in entry.get("aliases", []) if alias]
                )
        elif isinstance(seasons, dict):
            for standard_name, aliases in seasons.items():
                season_candidates.append(standard_name)
                season_aliases[standard_name] = _dedupe(
                    [str(alias) for alias in aliases if alias]
                )
        catalog["season"] = {"candidates": season_candidates, "aliases": season_aliases}

        road_aliases: Dict[str, List[str]] = {}
        road_candidates: List[str] = []
        for standard_name, info in (mappings.get("road_types", {}) or {}).items():
            road_candidates.append(standard_name)
            if isinstance(info, dict):
                aliases = info.get("aliases", [])
            elif isinstance(info, list):
                aliases = info
            else:
                aliases = []
            road_aliases[standard_name] = _dedupe([str(alias) for alias in aliases if alias])
        catalog["road_type"] = {"candidates": road_candidates, "aliases": road_aliases}

        meteorology_aliases: Dict[str, List[str]] = {}
        meteorology_candidates: List[str] = []
        presets = ((mappings.get("meteorology", {}) or {}).get("presets", {}) or {})
        for standard_name, info in presets.items():
            meteorology_candidates.append(standard_name)
            aliases = info.get("aliases", []) if isinstance(info, dict) else []
            meteorology_aliases[standard_name] = _dedupe([str(alias) for alias in aliases if alias])
        catalog["meteorology"] = {"candidates": meteorology_candidates, "aliases": meteorology_aliases}

        stability_aliases: Dict[str, List[str]] = {}
        stability_candidates: List[str] = []
        for standard_name, info in (mappings.get("stability_classes", {}) or {}).items():
            stability_candidates.append(standard_name)
            aliases = info.get("aliases", []) if isinstance(info, dict) else []
            stability_aliases[standard_name] = _dedupe([str(alias) for alias in aliases if alias])
        catalog["stability_class"] = {"candidates": stability_candidates, "aliases": stability_aliases}

        return catalog

    def standardize(
        self,
        param_type: str,
        raw_value: Any,
        context: Optional[Dict[str, Any]] = None,
    ) -> StandardizationResult:
        type_config = PARAM_TYPE_CONFIG.get(param_type)
        original = raw_value if raw_value is not None else ""

        if type_config is None:
            return StandardizationResult(
                success=True,
                original=original,
                normalized=raw_value,
                strategy="passthrough",
                confidence=1.0,
            )

        if self._should_passthrough(param_type, raw_value, type_config):
            normalized = self._passthrough_value(param_type, raw_value)
            return StandardizationResult(
                success=True,
                original=original,
                normalized=normalized,
                strategy="passthrough",
                confidence=1.0,
            )

        if type_config.get("is_list"):
            return self._standardize_list(param_type, raw_value, type_config, context)

        candidates = self.get_candidates(param_type)
        aliases = self._get_aliases(param_type)
        rule_result = self._rule_backend.standardize(param_type, raw_value, candidates, aliases, context)

        if rule_result is None:
            return StandardizationResult(
                success=True,
                original=original,
                normalized=raw_value,
                strategy="passthrough",
                confidence=1.0,
            )

        if self._should_accept_rule_result(param_type, raw_value, rule_result):
            return rule_result

        if self._can_try_llm(param_type, raw_value, type_config):
            llm_result = self._llm_backend.standardize(param_type, raw_value, candidates, aliases, context) if self._llm_backend else None
            if llm_result is not None and llm_result.success:
                logger.info(
                    "LLM resolved %s=%r -> %r (confidence=%.2f)",
                    param_type,
                    raw_value,
                    llm_result.normalized,
                    llm_result.confidence,
                )
                return llm_result

        if rule_result.success:
            return rule_result

        suggestions = rule_result.suggestions or self._get_suggestions(param_type, raw_value)
        return StandardizationResult(
            success=False,
            original=rule_result.original,
            normalized=None,
            strategy="abstain",
            confidence=0.0,
            suggestions=suggestions,
        )

    def standardize_batch(
        self,
        params: Dict[str, Any],
        tool_name: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        standardized: Dict[str, Any] = {}
        records: List[Dict[str, Any]] = []

        for key, value in dict(params or {}).items():
            param_type = self._param_registry.get(key)
            if param_type is None or value is None:
                standardized[key] = value
                continue

            type_config = PARAM_TYPE_CONFIG.get(param_type, {})
            if type_config.get("is_list"):
                if not isinstance(value, list):
                    standardized[key] = value
                    continue
                standardized[key] = self._standardize_list_param(key, value, tool_name, records)
                continue

            if not isinstance(value, str):
                standardized[key] = value
                continue

            context = {"tool": tool_name, "param_name": key}
            result = self.standardize(param_type, value, context)

            if not self._should_record_passthrough(key, param_type, value, result):
                standardized[key] = result.normalized if result.success else value
                continue

            record = {"param": key, **result.to_dict()}
            records.append(record)

            if self._should_trigger_parameter_negotiation(param_type, value, result):
                suggestions = self._build_negotiation_suggestions(param_type, value, result)
                record["suggestions"] = suggestions
                raise BatchStandardizationError(
                    message=self._build_negotiation_message(key, value, suggestions),
                    param_name=key,
                    original_value=value,
                    suggestions=suggestions,
                    records=records,
                    negotiation_eligible=True,
                    trigger_reason=self._build_negotiation_trigger_reason(result),
                )

            if result.success:
                standardized[key] = result.normalized
                continue

            suggestions = result.suggestions
            negotiation_eligible = self._should_trigger_parameter_negotiation(param_type, value, result)
            raise BatchStandardizationError(
                message=self._build_failure_message(key, value, suggestions),
                param_name=key,
                original_value=value,
                suggestions=suggestions,
                records=records,
                negotiation_eligible=negotiation_eligible,
                trigger_reason=(
                    self._build_negotiation_trigger_reason(result)
                    if negotiation_eligible
                    else "standardization_abstain_no_safe_candidates"
                ),
            )

        return standardized, records

    def get_candidates(self, param_type: str) -> List[str]:
        if PARAM_TYPE_CONFIG.get(param_type, {}).get("is_list"):
            element_type = PARAM_TYPE_CONFIG[param_type]["element_type"]
            return self.get_candidates(element_type)
        return list((self._catalog.get(param_type) or {}).get("candidates", []))

    def register_param_type(self, param_name: str, param_type: str):
        self._param_registry[param_name] = param_type

    def get_param_type(self, param_name: str) -> Optional[str]:
        return self._param_registry.get(param_name)

    def _get_aliases(self, param_type: str) -> Dict[str, List[str]]:
        if PARAM_TYPE_CONFIG.get(param_type, {}).get("is_list"):
            element_type = PARAM_TYPE_CONFIG[param_type]["element_type"]
            return self._get_aliases(element_type)
        return dict((self._catalog.get(param_type) or {}).get("aliases", {}))

    def get_candidate_aliases(self, param_name: str) -> Dict[str, List[str]]:
        param_type = self.get_param_type(param_name)
        if param_type is None:
            return {}
        return self._get_aliases(param_type)

    def resolve_candidate_value(self, param_name: str, raw_value: Any) -> Optional[str]:
        param_type = self.get_param_type(param_name)
        if param_type is None:
            return None

        candidates = self.get_candidates(param_type)
        aliases = self._get_aliases(param_type)
        variants = [str(raw_value or "").strip()]
        if not variants[0]:
            return None

        match = re.match(r"^(.*?)\s*\((.*?)\)\s*$", variants[0])
        if match:
            variants.extend([match.group(1).strip(), match.group(2).strip()])

        for variant in variants:
            lowered = variant.lower()
            if not lowered:
                continue
            for candidate in candidates:
                if lowered == candidate.lower():
                    return candidate
                for alias in aliases.get(candidate, []):
                    if lowered == str(alias).strip().lower():
                        return candidate
        return None

    def _should_passthrough(self, param_type: str, raw_value: Any, type_config: Dict[str, Any]) -> bool:
        if not isinstance(raw_value, str):
            return False
        patterns = type_config.get("passthrough_patterns", []) or []
        cleaned = raw_value.strip()
        return any(re.search(pattern, cleaned, flags=re.IGNORECASE) for pattern in patterns)

    def _passthrough_value(self, param_type: str, raw_value: Any) -> Any:
        if not isinstance(raw_value, str):
            return raw_value
        cleaned = raw_value.strip()
        if param_type == "meteorology" and cleaned.lower() == "custom":
            return "custom"
        if param_type == "meteorology" and cleaned.lower().endswith(".sfc"):
            return raw_value
        return raw_value

    def _standardize_list(
        self,
        param_type: str,
        raw_value: Any,
        type_config: Dict[str, Any],
        context: Optional[Dict[str, Any]],
    ) -> StandardizationResult:
        if raw_value is None:
            return StandardizationResult(
                success=True,
                original="",
                normalized=raw_value,
                strategy="passthrough",
                confidence=1.0,
            )

        items = list(raw_value) if isinstance(raw_value, list) else [raw_value]
        element_type = type_config["element_type"]
        normalized_items: List[Any] = []
        suggestions: List[str] = []
        element_results: List[StandardizationResult] = []

        for item in items:
            if item is None or not isinstance(item, str):
                normalized_items.append(item)
                continue
            result = self.standardize(element_type, item, context)
            element_results.append(result)
            if result.success:
                normalized_items.append(result.normalized)
            else:
                normalized_items.append(item)
                suggestions.extend(result.suggestions)

        success = all(result.success for result in element_results)
        if not element_results:
            strategy = "passthrough"
            confidence = 1.0
        elif all(result.strategy == "exact" for result in element_results):
            strategy = "exact"
            confidence = 1.0
        elif success:
            strategy = "alias"
            confidence = min(result.confidence for result in element_results)
        else:
            strategy = "abstain"
            confidence = 0.0

        return StandardizationResult(
            success=success,
            original=str(raw_value),
            normalized=normalized_items,
            strategy=strategy,
            confidence=confidence,
            suggestions=_dedupe(suggestions),
        )

    def _standardize_list_param(
        self,
        key: str,
        values: List[Any],
        tool_name: Optional[str],
        records: List[Dict[str, Any]],
    ) -> List[Any]:
        normalized_values: List[Any] = []
        for item in values:
            if item is None or not isinstance(item, str):
                normalized_values.append(item)
                continue

            result = self.standardize(
                "pollutant",
                item,
                {"tool": tool_name, "param_name": key},
            )
            records.append({"param": f"{key}[{item}]", **result.to_dict()})
            if result.success:
                normalized_values.append(result.normalized)
            else:
                normalized_values.append(item)
                logger.warning("Could not standardize pollutant list item: %r", item)
        return normalized_values

    def _should_accept_rule_result(
        self,
        param_type: str,
        raw_value: Any,
        result: StandardizationResult,
    ) -> bool:
        cleaned = _clean_string(raw_value)
        if result.success and result.strategy != "default":
            return True
        if result.success and result.strategy == "default":
            return not cleaned or not self._is_llm_enabled_for(param_type)
        if result.strategy == "none":
            return not cleaned
        return False

    def _can_try_llm(self, param_type: str, raw_value: Any, type_config: Dict[str, Any]) -> bool:
        return bool(
            self._llm_backend
            and self._is_llm_enabled_for(param_type)
            and isinstance(raw_value, str)
            and raw_value.strip()
            and type_config.get("llm_enabled", True)
        )

    def _is_llm_enabled_for(self, param_type: str) -> bool:
        if not self._config.get("llm_enabled", True):
            return False
        return PARAM_TYPE_CONFIG.get(param_type, {}).get("llm_enabled", True)

    def _get_suggestions(self, param_type: str, raw_value: Any) -> List[str]:
        cleaned = _clean_string(raw_value)
        standardizer = self.rule_standardizer
        if param_type == "vehicle_type":
            return standardizer.get_vehicle_suggestions(cleaned, top_k=5)
        if param_type == "pollutant":
            return standardizer.get_pollutant_suggestions(cleaned, top_k=5)
        if param_type == "season":
            return sorted(set(standardizer.season_lookup.values()))
        if param_type == "road_type":
            return sorted(set(standardizer.road_type_lookup.values()))
        if param_type == "meteorology":
            return list(standardizer.meteorology_presets)
        if param_type == "stability_class":
            return list(standardizer.stability_classes)
        return self.get_candidates(param_type)

    def _build_failure_message(self, param_name: str, raw_value: Any, suggestions: List[str]) -> str:
        template, limit = _FAILURE_MESSAGES.get(
            param_name,
            ("Cannot standardize parameter '{value}'. Suggestions: {suggestions}", 5),
        )
        suggestion_text = ", ".join((suggestions or [])[:limit])
        return template.format(value=raw_value, suggestions=suggestion_text)

    def _build_negotiation_message(self, param_name: str, raw_value: Any, suggestions: List[str]) -> str:
        suggestion_text = ", ".join((suggestions or [])[: self._parameter_negotiation_max_candidates()])
        return (
            f"Parameter '{param_name}' for value '{raw_value}' requires confirmation before execution. "
            f"Candidates: {suggestion_text}"
        )

    def _parameter_negotiation_enabled(self) -> bool:
        return bool(self._config.get("parameter_negotiation_enabled", False))

    def _parameter_negotiation_threshold(self) -> float:
        return float(self._config.get("parameter_negotiation_confidence_threshold", 0.85))

    def _parameter_negotiation_max_candidates(self) -> int:
        return max(int(self._config.get("parameter_negotiation_max_candidates", 5)), 1)

    def _build_negotiation_suggestions(
        self,
        param_type: str,
        raw_value: Any,
        result: StandardizationResult,
    ) -> List[str]:
        suggestions: List[str] = []
        if result.normalized:
            suggestions.append(str(result.normalized))
        suggestions.extend(result.suggestions or [])
        suggestions.extend(self._get_suggestions(param_type, raw_value))
        return _dedupe(suggestions)[: self._parameter_negotiation_max_candidates()]

    def _should_trigger_parameter_negotiation(
        self,
        param_type: str,
        raw_value: Any,
        result: StandardizationResult,
    ) -> bool:
        if not self._parameter_negotiation_enabled():
            return False

        suggestions = self._build_negotiation_suggestions(param_type, raw_value, result)
        if not suggestions:
            return False

        if not result.success:
            return True

        if result.strategy in {"exact", "alias", "passthrough", "local_model"}:
            return False

        return float(result.confidence or 0.0) < self._parameter_negotiation_threshold()

    @staticmethod
    def _build_negotiation_trigger_reason(result: StandardizationResult) -> str:
        confidence = float(result.confidence or 0.0)
        if result.success:
            return f"low_confidence_{result.strategy}_match(confidence={confidence:.2f})"
        return f"standardization_{result.strategy}_with_candidates(confidence={confidence:.2f})"

    def _should_record_passthrough(
        self,
        key: str,
        param_type: str,
        raw_value: Any,
        result: StandardizationResult,
    ) -> bool:
        if key == "meteorology" and result.strategy == "passthrough" and isinstance(raw_value, str):
            return False
        return True
