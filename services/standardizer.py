"""
Unified Standardization Service
Handles all standardization transparently (vehicle types, pollutants, seasons,
road types, column names)
Configuration-first approach with optional local model fallback
"""
from dataclasses import dataclass, field
import logging
from typing import Optional, Dict, List, Any

from config import get_config
from services.config_loader import ConfigLoader
from services.model_backend import NoModelBackend, ParameterModelBackend, create_local_model_backend

# Try to import fuzzywuzzy, fallback to difflib
try:
    from fuzzywuzzy import fuzz
    FUZZY_AVAILABLE = True
except ImportError:
    import difflib
    FUZZY_AVAILABLE = False

    # Fallback fuzzy matching using difflib
    class fuzz:
        @staticmethod
        def ratio(s1: str, s2: str) -> int:
            """Simple ratio using difflib."""
            return int(difflib.SequenceMatcher(None, s1, s2).ratio() * 100)


logger = logging.getLogger(__name__)


@dataclass
class StandardizationResult:
    """Structured result of a parameter standardization operation."""

    success: bool
    original: str
    normalized: Optional[str] = None
    strategy: str = "none"  # exact / alias / fuzzy / abstain / default
    confidence: float = 0.0
    suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "success": self.success,
            "original": self.original,
            "normalized": self.normalized,
            "strategy": self.strategy,
            "confidence": self.confidence,
        }
        if self.suggestions:
            result["suggestions"] = self.suggestions
        return result


class UnifiedStandardizer:
    """
    Unified standardization service

    Design: Configuration table first, local model second, fail gracefully
    All standardization is transparent to the main LLM
    """

    def __init__(self):
        runtime_config = get_config()
        self.mappings = ConfigLoader.load_mappings()
        self.config = self.mappings
        self._fuzzy_enabled = bool(getattr(runtime_config, "standardization_fuzzy_enabled", True))
        self._model_enabled = bool(getattr(runtime_config, "enable_llm_standardization", True))
        self._build_lookup_tables()
        self._local_model: Optional[ParameterModelBackend] = None  # Lazy load

    def _build_lookup_tables(self):
        """Build fast lookup tables from configuration."""
        self.vehicle_lookup: Dict[str, str] = {}
        self.vehicle_catalog: Dict[str, Dict[str, Any]] = {}
        for vtype in self.config.get("vehicle_types", []):
            std_name = vtype["standard_name"]
            self.vehicle_catalog[std_name] = vtype
            self.vehicle_lookup[std_name.lower().strip()] = std_name

            display_name = vtype.get("display_name_zh")
            if display_name:
                self.vehicle_lookup[display_name.lower().strip()] = std_name

            for alias in vtype.get("aliases", []):
                self.vehicle_lookup[str(alias).lower().strip()] = std_name

        logger.info(f"Built vehicle lookup table with {len(self.vehicle_lookup)} entries")

        self.pollutant_lookup: Dict[str, str] = {}
        self.pollutant_catalog: Dict[str, Dict[str, Any]] = {}
        for pollutant in self.config.get("pollutants", []):
            std_name = pollutant["standard_name"]
            self.pollutant_catalog[std_name] = pollutant
            self.pollutant_lookup[std_name.lower().strip()] = std_name

            display_name = pollutant.get("display_name_zh")
            if display_name:
                self.pollutant_lookup[display_name.lower().strip()] = std_name

            for alias in pollutant.get("aliases", []):
                self.pollutant_lookup[str(alias).lower().strip()] = std_name

        logger.info(f"Built pollutant lookup table with {len(self.pollutant_lookup)} entries")

        self.column_patterns = self.config.get("column_patterns", {})

        self.season_lookup: Dict[str, str] = {}
        seasons_config = self.mappings.get("seasons", {})
        if isinstance(seasons_config, dict):
            for standard_name, aliases in seasons_config.items():
                for alias in aliases if isinstance(aliases, list) else []:
                    self.season_lookup[str(alias).lower().strip()] = standard_name
                self.season_lookup[standard_name.lower().strip()] = standard_name
        elif isinstance(seasons_config, list):
            for entry in seasons_config:
                if not isinstance(entry, dict):
                    continue
                standard_name = entry.get("standard_name")
                if not standard_name:
                    continue
                for alias in entry.get("aliases", []):
                    self.season_lookup[str(alias).lower().strip()] = standard_name
                self.season_lookup[standard_name.lower().strip()] = standard_name
        from core.contracts.emission_schema import get_default as _s_get_default
        self.season_default = self.mappings.get("defaults", {}).get("season") or _s_get_default("season") or "夏季"


        self.road_type_lookup: Dict[str, str] = {}
        road_types_config = self.mappings.get("road_types", {})
        if isinstance(road_types_config, dict):
            for standard_name, info in road_types_config.items():
                if isinstance(info, dict):
                    aliases = info.get("aliases", [])
                elif isinstance(info, list):
                    aliases = info
                else:
                    aliases = []
                for alias in aliases:
                    self.road_type_lookup[str(alias).lower().strip()] = standard_name
                self.road_type_lookup[standard_name.lower().strip()] = standard_name
        from core.contracts.emission_schema import get_default as _s_get_default
        self.road_type_default = self.mappings.get("defaults", {}).get("road_type") or _s_get_default("road_type") or "快速路"

        self.meteorology_lookup: Dict[str, str] = {}
        meteorology_config = self.mappings.get("meteorology", {})
        presets_config = meteorology_config.get("presets", {}) if isinstance(meteorology_config, dict) else {}
        self.meteorology_presets: List[str] = []
        if isinstance(presets_config, dict):
            for standard_name, info in presets_config.items():
                self.meteorology_presets.append(standard_name)
                self.meteorology_lookup[standard_name.lower().strip()] = standard_name
                aliases = info.get("aliases", []) if isinstance(info, dict) else []
                for alias in aliases:
                    self.meteorology_lookup[str(alias).lower().strip()] = standard_name

        self.stability_lookup: Dict[str, str] = {}
        stability_config = self.mappings.get("stability_classes", {})
        self.stability_classes: List[str] = []
        if isinstance(stability_config, dict):
            for standard_name, info in stability_config.items():
                self.stability_classes.append(standard_name)
                self.stability_lookup[standard_name.lower().strip()] = standard_name
                aliases = info.get("aliases", []) if isinstance(info, dict) else []
                for alias in aliases:
                    self.stability_lookup[str(alias).lower().strip()] = standard_name

    def _fuzzy_ratio(self, left: str, right: str) -> int:
        """Compute a normalized fuzzy ratio between two strings."""
        return fuzz.ratio(str(left).strip().lower(), str(right).strip().lower())

    def _try_local_standardization(
        self,
        raw_input: str,
        lookup: Dict[str, str],
        model_method: str,
    ) -> Optional[StandardizationResult]:
        """Use the optional local model backend and normalize its response."""
        if not self._model_enabled:
            return None
        local_model = self._get_local_model()
        if not local_model:
            return None

        param_type = {
            "standardize_vehicle": "vehicle_type",
            "standardize_pollutant": "pollutant",
        }.get(model_method)
        if param_type is None:
            return None

        candidates = (
            list(self.vehicle_catalog.keys())
            if param_type == "vehicle_type"
            else list(self.pollutant_catalog.keys())
        )
        aliases = self._get_model_aliases(param_type)
        result = local_model.infer(param_type, raw_input, candidates, aliases)
        if result is None or not result.success:
            return None
        if result.normalized and result.normalized in set(lookup.values()):
            return result
        return None

    def _get_model_aliases(self, param_type: str) -> Dict[str, List[str]]:
        """Return candidate aliases for model-based standardization."""
        aliases: Dict[str, List[str]] = {}
        if param_type == "vehicle_type":
            for std_name, entry in self.vehicle_catalog.items():
                alias_items = []
                display_name = entry.get("display_name_zh")
                if display_name:
                    alias_items.append(str(display_name))
                alias_items.extend(str(alias) for alias in entry.get("aliases", []) if alias)
                aliases[std_name] = alias_items
        elif param_type == "pollutant":
            for std_name, entry in self.pollutant_catalog.items():
                alias_items = []
                display_name = entry.get("display_name_zh")
                if display_name:
                    alias_items.append(str(display_name))
                alias_items.extend(str(alias) for alias in entry.get("aliases", []) if alias)
                aliases[std_name] = alias_items
        return aliases

    def _rank_standard_names(
        self,
        raw_input: str,
        lookup: Dict[str, str],
        top_k: int = 5,
    ) -> List[str]:
        """Rank canonical names by fuzzy similarity to the raw input."""
        if not raw_input:
            return []

        scored: Dict[str, int] = {}
        for alias, standard_name in lookup.items():
            score = self._fuzzy_ratio(raw_input, alias)
            scored[standard_name] = max(scored.get(standard_name, 0), score)

        ranked = sorted(scored.items(), key=lambda item: (-item[1], item[0]))
        return [name for name, _ in ranked[:top_k]]

    def standardize_vehicle_detailed(self, raw_input: str) -> StandardizationResult:
        """Standardize vehicle type with full result details."""
        if raw_input is None or not str(raw_input).strip():
            return StandardizationResult(success=False, original=raw_input or "", strategy="none")

        cleaned = str(raw_input).strip()
        cleaned_lower = cleaned.lower()

        if cleaned_lower in self.vehicle_lookup:
            normalized = self.vehicle_lookup[cleaned_lower]
            strategy = "exact" if cleaned == normalized else "alias"
            confidence = 1.0 if strategy == "exact" else 0.95
            logger.debug(f"Vehicle {strategy} match: '{cleaned}' -> '{normalized}'")
            return StandardizationResult(
                success=True,
                original=cleaned,
                normalized=normalized,
                strategy=strategy,
                confidence=confidence,
            )

        best_match = None
        best_score = 0
        for alias, standard_name in self.vehicle_lookup.items():
            score = self._fuzzy_ratio(cleaned, alias)
            if score > best_score:
                best_score = score
                best_match = standard_name

        if self._fuzzy_enabled and best_score >= 70 and best_match:
            logger.debug(f"Vehicle fuzzy match: '{cleaned}' -> '{best_match}' (score: {best_score})")
            return StandardizationResult(
                success=True,
                original=cleaned,
                normalized=best_match,
                strategy="fuzzy",
                confidence=round(best_score / 100, 2),
            )

        local_result = self._try_local_standardization(cleaned, self.vehicle_lookup, "standardize_vehicle")
        if local_result:
            logger.info(
                "Vehicle local model: '%s' -> '%s' (confidence: %s)",
                cleaned,
                local_result.normalized,
                local_result.confidence,
            )
            return local_result

        suggestions = self.get_vehicle_suggestions(cleaned, top_k=5)
        logger.warning(f"Cannot standardize vehicle: '{cleaned}'")
        return StandardizationResult(
            success=False,
            original=cleaned,
            strategy="abstain",
            confidence=0.0,
            suggestions=suggestions,
        )

    def standardize_vehicle(self, raw_input: str) -> Optional[str]:
        """
        Standardize vehicle type. Returns standard name or None.

        This is the backward-compatible interface. For detailed results
        including confidence and strategy, use standardize_vehicle_detailed().
        """
        result = self.standardize_vehicle_detailed(raw_input)
        return result.normalized if result.success else None

    def standardize_pollutant_detailed(self, raw_input: str) -> StandardizationResult:
        """Standardize pollutant with full result details."""
        if raw_input is None or not str(raw_input).strip():
            return StandardizationResult(success=False, original=raw_input or "", strategy="none")

        cleaned = str(raw_input).strip()
        cleaned_lower = cleaned.lower()

        if cleaned_lower in self.pollutant_lookup:
            normalized = self.pollutant_lookup[cleaned_lower]
            strategy = "exact" if cleaned == normalized else "alias"
            confidence = 1.0 if strategy == "exact" else 0.95
            logger.debug(f"Pollutant {strategy} match: '{cleaned}' -> '{normalized}'")
            return StandardizationResult(
                success=True,
                original=cleaned,
                normalized=normalized,
                strategy=strategy,
                confidence=confidence,
            )

        best_match = None
        best_score = 0
        for alias, standard_name in self.pollutant_lookup.items():
            score = self._fuzzy_ratio(cleaned, alias)
            if score > best_score:
                best_score = score
                best_match = standard_name

        if self._fuzzy_enabled and best_score >= 80 and best_match:
            logger.debug(f"Pollutant fuzzy match: '{cleaned}' -> '{best_match}' (score: {best_score})")
            return StandardizationResult(
                success=True,
                original=cleaned,
                normalized=best_match,
                strategy="fuzzy",
                confidence=round(best_score / 100, 2),
            )

        local_result = self._try_local_standardization(cleaned, self.pollutant_lookup, "standardize_pollutant")
        if local_result:
            logger.info(
                "Pollutant local model: '%s' -> '%s' (confidence: %s)",
                cleaned,
                local_result.normalized,
                local_result.confidence,
            )
            return local_result

        suggestions = self.get_pollutant_suggestions(cleaned, top_k=5)
        logger.warning(f"Cannot standardize pollutant: '{cleaned}'")
        return StandardizationResult(
            success=False,
            original=cleaned,
            strategy="abstain",
            confidence=0.0,
            suggestions=suggestions,
        )

    def standardize_pollutant(self, raw_input: str) -> Optional[str]:
        """
        Standardize pollutant. Returns standard name or None.

        This is the backward-compatible interface. For detailed results
        including confidence and strategy, use standardize_pollutant_detailed().
        """
        result = self.standardize_pollutant_detailed(raw_input)
        return result.normalized if result.success else None

    def standardize_season(self, raw_input: str) -> StandardizationResult:
        """Standardize season parameter."""
        if raw_input is None or not str(raw_input).strip():
            return StandardizationResult(
                success=True,
                original=raw_input or "",
                normalized=self.season_default,
                strategy="default",
                confidence=1.0,
            )

        cleaned = str(raw_input).strip()
        cleaned_lower = cleaned.lower()

        if cleaned_lower in self.season_lookup:
            return StandardizationResult(
                success=True,
                original=cleaned,
                normalized=self.season_lookup[cleaned_lower],
                strategy="alias",
                confidence=0.95,
            )

        best_match = None
        best_score = 0
        for alias, standard_name in self.season_lookup.items():
            score = self._fuzzy_ratio(cleaned_lower, alias)
            if score > best_score:
                best_score = score
                best_match = standard_name

        if self._fuzzy_enabled and best_score >= 60 and best_match:
            return StandardizationResult(
                success=True,
                original=cleaned,
                normalized=best_match,
                strategy="fuzzy",
                confidence=round(best_score / 100, 2),
            )

        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=self.season_default,
            strategy="default",
            confidence=0.5,
            suggestions=sorted(set(self.season_lookup.values())),
        )

    def standardize_road_type(self, raw_input: str) -> StandardizationResult:
        """Standardize road type parameter."""
        if raw_input is None or not str(raw_input).strip():
            return StandardizationResult(
                success=True,
                original=raw_input or "",
                normalized=self.road_type_default,
                strategy="default",
                confidence=1.0,
            )

        cleaned = str(raw_input).strip()
        cleaned_lower = cleaned.lower()

        if cleaned_lower in self.road_type_lookup:
            return StandardizationResult(
                success=True,
                original=cleaned,
                normalized=self.road_type_lookup[cleaned_lower],
                strategy="alias",
                confidence=0.95,
            )

        best_match = None
        best_score = 0
        for alias, standard_name in self.road_type_lookup.items():
            score = self._fuzzy_ratio(cleaned_lower, alias)
            if score > best_score:
                best_score = score
                best_match = standard_name

        if self._fuzzy_enabled and best_score >= 60 and best_match:
            return StandardizationResult(
                success=True,
                original=cleaned,
                normalized=best_match,
                strategy="fuzzy",
                confidence=round(best_score / 100, 2),
            )

        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=self.road_type_default,
            strategy="default",
            confidence=0.5,
            suggestions=sorted(set(self.road_type_lookup.values())),
        )

    def standardize_meteorology(self, value: str) -> StandardizationResult:
        """Standardize meteorology preset names or pass through custom/path inputs."""
        if value is None or not str(value).strip():
            return StandardizationResult(
                success=False,
                original=value or "",
                strategy="abstain",
                confidence=0.0,
                suggestions=list(self.meteorology_presets),
            )

        cleaned = str(value).strip()
        cleaned_lower = cleaned.lower()

        if cleaned_lower == "custom" or cleaned_lower.endswith(".sfc"):
            return StandardizationResult(
                success=True,
                original=cleaned,
                normalized=cleaned,
                strategy="exact",
                confidence=1.0,
            )

        if cleaned_lower in self.meteorology_lookup:
            normalized = self.meteorology_lookup[cleaned_lower]
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
        for alias, standard_name in self.meteorology_lookup.items():
            score = self._fuzzy_ratio(cleaned, alias)
            if score > best_score:
                best_score = score
                best_match = standard_name

        if self._fuzzy_enabled and best_score >= 75 and best_match:
            return StandardizationResult(
                success=True,
                original=cleaned,
                normalized=best_match,
                strategy="fuzzy",
                confidence=round(best_score / 100, 2),
            )

        return StandardizationResult(
            success=False,
            original=cleaned,
            strategy="abstain",
            confidence=0.0,
            suggestions=list(self.meteorology_presets),
        )

    def standardize_stability_class(self, value: str) -> StandardizationResult:
        """Standardize atmospheric stability class aliases to canonical abbreviations."""
        if value is None or not str(value).strip():
            return StandardizationResult(
                success=False,
                original=value or "",
                strategy="abstain",
                confidence=0.0,
                suggestions=list(self.stability_classes),
            )

        cleaned = str(value).strip()
        cleaned_lower = cleaned.lower()

        if cleaned_lower in self.stability_lookup:
            normalized = self.stability_lookup[cleaned_lower]
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
        for alias, standard_name in self.stability_lookup.items():
            score = self._fuzzy_ratio(cleaned, alias)
            if score > best_score:
                best_score = score
                best_match = standard_name

        if self._fuzzy_enabled and best_score >= 75 and best_match:
            return StandardizationResult(
                success=True,
                original=cleaned,
                normalized=best_match,
                strategy="fuzzy",
                confidence=round(best_score / 100, 2),
            )

        return StandardizationResult(
            success=False,
            original=cleaned,
            strategy="abstain",
            confidence=0.0,
            suggestions=list(self.stability_classes),
        )

    def get_vehicle_suggestions(self, raw_input: str = None, top_k: int = 6) -> List[str]:
        """
        Get vehicle type suggestions for user selection.

        Args:
            raw_input: Optional user input for context
            top_k: Maximum number of suggestions to return

        Returns:
            List of suggested vehicle types with Chinese names
        """
        if raw_input:
            ranked_names = self._rank_standard_names(raw_input, self.vehicle_lookup, top_k=top_k)
            suggestions = []
            for std_name in ranked_names:
                vehicle = self.vehicle_catalog.get(std_name, {})
                display_name = vehicle.get("display_name_zh", std_name)
                suggestions.append(f"{display_name} ({std_name})")
            return suggestions

        suggestions = []
        common_types = [
            "Passenger Car",
            "Transit Bus",
            "Light Commercial Truck",
            "Combination Long-haul Truck",
            "Passenger Truck",
            "Intercity Bus",
        ]

        for std_name in common_types[:top_k]:
            vehicle = self.vehicle_catalog.get(std_name)
            if vehicle:
                suggestions.append(f"{vehicle['display_name_zh']} ({std_name})")

        return suggestions

    def get_pollutant_suggestions(self, raw_input: str = None, top_k: int = 6) -> List[str]:
        """
        Get pollutant suggestions.

        Args:
            raw_input: Optional user input for ranking suggestions
            top_k: Maximum number of suggestions to return

        Returns:
            List of standard pollutant names
        """
        if raw_input:
            return self._rank_standard_names(raw_input, self.pollutant_lookup, top_k=top_k)

        return [p["standard_name"] for p in self.config.get("pollutants", [])[:top_k]]

    def map_columns(self, columns: List[str], task_type: str) -> Dict[str, str]:
        """
        Map column names to standard names

        Strategy:
        1. Exact match against patterns
        2. Substring match (column contains pattern or pattern contains column)

        Args:
            columns: List of column names from user's file
            task_type: "micro_emission" or "macro_emission"

        Returns:
            Dictionary mapping {original_column: standard_column}
        """
        patterns = self.column_patterns.get(task_type, {})
        mapping = {}

        for col in columns:
            col_lower = col.lower().strip()

            matched = False
            for field_name, field_config in patterns.items():
                standard_name = field_config.get("standard")
                pattern_list = field_config.get("patterns", [])

                for pattern in pattern_list:
                    if col_lower == pattern.lower():
                        mapping[col] = standard_name
                        matched = True
                        break
                if matched:
                    break

            if matched:
                continue

            best_field = None
            best_len = 0
            for field_name, field_config in patterns.items():
                standard_name = field_config.get("standard")
                if standard_name in mapping.values():
                    continue
                pattern_list = field_config.get("patterns", [])

                for pattern in pattern_list:
                    p_lower = pattern.lower()
                    if len(p_lower) < 3:
                        continue
                    if p_lower in col_lower or col_lower in p_lower:
                        if len(p_lower) > best_len:
                            best_len = len(p_lower)
                            best_field = (col, standard_name)

            if best_field:
                mapping[best_field[0]] = best_field[1]
                logger.debug(f"Column substring match: '{best_field[0]}' -> '{best_field[1]}'")

        return mapping

    def get_required_columns(self, task_type: str) -> List[str]:
        """
        Get list of required column names for a task type

        Args:
            task_type: "micro_emission" or "macro_emission"

        Returns:
            List of required standard column names
        """
        patterns = self.column_patterns.get(task_type, {})
        required = []

        for field_name, field_config in patterns.items():
            if field_config.get("required", False):
                required.append(field_config.get("standard"))

        return required

    def get_column_patterns_for_display(self, task_type: str, field_name: str) -> List[str]:
        """
        Get supported column name patterns for display to user

        Args:
            task_type: "micro_emission" or "macro_emission"
            field_name: Field name (e.g., "speed", "length")

        Returns:
            List of supported pattern strings
        """
        patterns = self.column_patterns.get(task_type, {})
        field_config = patterns.get(field_name, {})
        return field_config.get("patterns", [])

    def _get_local_model(self):
        """
        Lazy load local model if available

        Returns:
            Local model backend or None
        """
        if self._local_model is None:
            try:
                backend = create_local_model_backend()
                if isinstance(backend, NoModelBackend):
                    logger.info("Local standardizer disabled in config")
                    self._local_model = None
                else:
                    self._local_model = backend
                    logger.info("Local standardizer model backend loaded")
            except Exception as exc:
                logger.info(f"Local standardizer not available: {exc}")

        return self._local_model


_standardizer_instance = None


def get_standardizer() -> UnifiedStandardizer:
    """Get the singleton standardizer instance."""
    global _standardizer_instance
    if _standardizer_instance is None:
        _standardizer_instance = UnifiedStandardizer()
    return _standardizer_instance


def reset_standardizer() -> None:
    """Reset cached standardizer so runtime config overrides take effect."""
    global _standardizer_instance
    _standardizer_instance = None
