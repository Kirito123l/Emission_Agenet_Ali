"""
Unified Standardization Service
Handles all standardization transparently (vehicle types, pollutants, column names)
Configuration-first approach with optional local model fallback
"""
import logging
from typing import Optional, Dict, List, Tuple
from services.config_loader import ConfigLoader

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
            """Simple ratio using difflib"""
            return int(difflib.SequenceMatcher(None, s1, s2).ratio() * 100)

logger = logging.getLogger(__name__)


class UnifiedStandardizer:
    """
    Unified standardization service

    Design: Configuration table first, local model second, fail gracefully
    All standardization is transparent to the main LLM
    """

    def __init__(self):
        self.config = ConfigLoader.load_mappings()
        self._build_lookup_tables()
        self._local_model = None  # Lazy load

    def _build_lookup_tables(self):
        """Build fast lookup tables from configuration"""
        # Vehicle lookup table
        self.vehicle_lookup = {}
        for vtype in self.config["vehicle_types"]:
            std_name = vtype["standard_name"]
            # Add standard name (case-insensitive)
            self.vehicle_lookup[std_name.lower()] = vtype
            # Add Chinese display name
            self.vehicle_lookup[vtype["display_name_zh"]] = vtype
            # Add all aliases
            for alias in vtype.get("aliases", []):
                self.vehicle_lookup[alias.lower()] = vtype

        logger.info(f"Built vehicle lookup table with {len(self.vehicle_lookup)} entries")

        # Pollutant lookup table
        self.pollutant_lookup = {}
        for pol in self.config["pollutants"]:
            std_name = pol["standard_name"]
            # Add standard name (case-insensitive)
            self.pollutant_lookup[std_name.lower()] = pol
            # Add Chinese display name
            self.pollutant_lookup[pol["display_name_zh"]] = pol
            # Add all aliases
            for alias in pol.get("aliases", []):
                self.pollutant_lookup[alias.lower()] = pol

        logger.info(f"Built pollutant lookup table with {len(self.pollutant_lookup)} entries")

        # Column patterns
        self.column_patterns = self.config.get("column_patterns", {})

    def standardize_vehicle(self, raw_input: str) -> Optional[str]:
        """
        Standardize vehicle type

        Flow:
        1. Exact match in configuration
        2. Fuzzy match in configuration
        3. Local model (if available and confident)
        4. Return None (cannot recognize)

        Args:
            raw_input: User's vehicle type input (e.g., "小汽车", "SUV")

        Returns:
            Standard vehicle type name (e.g., "Passenger Car") or None
        """
        if not raw_input:
            return None

        raw_lower = raw_input.lower().strip()

        # 1. Exact match
        if raw_lower in self.vehicle_lookup:
            result = self.vehicle_lookup[raw_lower]["standard_name"]
            logger.debug(f"Vehicle exact match: '{raw_input}' -> '{result}'")
            return result

        # 2. Fuzzy match (threshold: 70)
        best_match = None
        best_score = 0
        for key, value in self.vehicle_lookup.items():
            score = fuzz.ratio(raw_lower, key.lower())
            if score > best_score and score >= 70:
                best_score = score
                best_match = value

        if best_match:
            result = best_match["standard_name"]
            logger.debug(f"Vehicle fuzzy match: '{raw_input}' -> '{result}' (score: {best_score})")
            return result

        # 3. Local model (if available)
        if self._get_local_model():
            try:
                result = self._local_model.standardize_vehicle(raw_input)
                if result and result.get("confidence", 0) > 0.9:
                    std_name = result.get("standard_name")
                    logger.info(f"Vehicle local model: '{raw_input}' -> '{std_name}' (confidence: {result['confidence']})")
                    return std_name
            except Exception as e:
                logger.warning(f"Local model failed for vehicle '{raw_input}': {e}")

        # 4. Cannot recognize
        logger.warning(f"Cannot standardize vehicle: '{raw_input}'")
        return None

    def standardize_pollutant(self, raw_input: str) -> Optional[str]:
        """
        Standardize pollutant

        Args:
            raw_input: User's pollutant input (e.g., "氮氧", "PM2.5")

        Returns:
            Standard pollutant name (e.g., "NOx") or None
        """
        if not raw_input:
            return None

        raw_lower = raw_input.lower().strip()

        # 1. Exact match
        if raw_lower in self.pollutant_lookup:
            result = self.pollutant_lookup[raw_lower]["standard_name"]
            logger.debug(f"Pollutant exact match: '{raw_input}' -> '{result}'")
            return result

        # 2. Fuzzy match (threshold: 80, stricter than vehicle)
        best_match = None
        best_score = 0
        for key, value in self.pollutant_lookup.items():
            score = fuzz.ratio(raw_lower, key.lower())
            if score > best_score and score >= 80:
                best_score = score
                best_match = value

        if best_match:
            result = best_match["standard_name"]
            logger.debug(f"Pollutant fuzzy match: '{raw_input}' -> '{result}' (score: {best_score})")
            return result

        # 3. Local model (if available)
        if self._get_local_model():
            try:
                result = self._local_model.standardize_pollutant(raw_input)
                if result and result.get("confidence", 0) > 0.9:
                    std_name = result.get("standard_name")
                    logger.info(f"Pollutant local model: '{raw_input}' -> '{std_name}'")
                    return std_name
            except Exception as e:
                logger.warning(f"Local model failed for pollutant '{raw_input}': {e}")

        # 4. Cannot recognize
        logger.warning(f"Cannot standardize pollutant: '{raw_input}'")
        return None

    def get_vehicle_suggestions(self, raw_input: str = None) -> List[str]:
        """
        Get vehicle type suggestions for user selection

        Args:
            raw_input: Optional user input for context

        Returns:
            List of suggested vehicle types with Chinese names
        """
        suggestions = []
        # Return top 6 most common vehicle types
        common_types = [
            "Passenger Car",
            "Transit Bus",
            "Light Commercial Truck",
            "Combination Long-haul Truck",
            "Passenger Truck",
            "Intercity Bus"
        ]

        for std_name in common_types:
            for vtype in self.config["vehicle_types"]:
                if vtype["standard_name"] == std_name:
                    suggestions.append(f"{vtype['display_name_zh']} ({std_name})")
                    break

        return suggestions

    def get_pollutant_suggestions(self) -> List[str]:
        """
        Get pollutant suggestions

        Returns:
            List of standard pollutant names
        """
        return [p["standard_name"] for p in self.config["pollutants"]]

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

            # Pass 1: Exact match
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

            # Pass 2: Substring match (col contains pattern or pattern contains col)
            best_field = None
            best_len = 0
            for field_name, field_config in patterns.items():
                standard_name = field_config.get("standard")
                if standard_name in mapping.values():
                    continue  # Already mapped this field
                pattern_list = field_config.get("patterns", [])

                for pattern in pattern_list:
                    p_lower = pattern.lower()
                    if len(p_lower) < 3:
                        continue  # Skip very short patterns for substring match
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
            Local model client or None
        """
        if self._local_model is None:
            try:
                # Check if local model is enabled in config
                from config import get_config
                config = get_config()

                if config.use_local_standardizer:
                    from shared.standardizer.local_client import get_local_standardizer_client
                    self._local_model = get_local_standardizer_client()
                    logger.info("Local standardizer model loaded")
                else:
                    logger.info("Local standardizer disabled in config")
            except Exception as e:
                logger.info(f"Local standardizer not available: {e}")
                # Not an error - local model is optional

        return self._local_model


# Singleton instance
_standardizer_instance = None


def get_standardizer() -> UnifiedStandardizer:
    """Get the singleton standardizer instance"""
    global _standardizer_instance
    if _standardizer_instance is None:
        _standardizer_instance = UnifiedStandardizer()
    return _standardizer_instance
