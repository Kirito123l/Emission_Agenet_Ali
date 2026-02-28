"""
Configuration Loader Service
Loads and caches configuration from YAML files
"""
import yaml
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from functools import lru_cache

logger = logging.getLogger(__name__)

# Configuration file paths
CONFIG_DIR = Path(__file__).parent.parent / "config"
MAPPINGS_FILE = CONFIG_DIR / "unified_mappings.yaml"
PROMPTS_FILE = CONFIG_DIR / "prompts" / "core.yaml"


class ConfigLoader:
    """Configuration loader with caching"""

    _mappings_cache: Optional[Dict] = None
    _prompts_cache: Optional[Dict] = None

    @classmethod
    def load_mappings(cls) -> Dict[str, Any]:
        """
        Load unified mappings configuration

        Returns:
            Dictionary containing all mappings (vehicles, pollutants, columns, etc.)
        """
        if cls._mappings_cache is None:
            try:
                with open(MAPPINGS_FILE, 'r', encoding='utf-8') as f:
                    cls._mappings_cache = yaml.safe_load(f)
                logger.info(f"Loaded mappings configuration from {MAPPINGS_FILE}")
            except Exception as e:
                logger.error(f"Failed to load mappings configuration: {e}")
                raise RuntimeError(f"Cannot load mappings configuration: {e}")

        return cls._mappings_cache

    @classmethod
    def load_prompts(cls) -> Dict[str, str]:
        """
        Load prompt templates

        Returns:
            Dictionary containing prompt templates
        """
        if cls._prompts_cache is None:
            try:
                with open(PROMPTS_FILE, 'r', encoding='utf-8') as f:
                    cls._prompts_cache = yaml.safe_load(f)
                logger.info(f"Loaded prompts from {PROMPTS_FILE}")
            except Exception as e:
                logger.error(f"Failed to load prompts: {e}")
                raise RuntimeError(f"Cannot load prompts: {e}")

        return cls._prompts_cache

    @classmethod
    def load_tool_definitions(cls) -> List[Dict]:
        """
        Load tool definitions for Tool Use mode

        Returns:
            List of tool definitions in OpenAI function calling format
        """
        # Import here to avoid circular dependency
        from tools.definitions import TOOL_DEFINITIONS
        return TOOL_DEFINITIONS

    @classmethod
    def get_vehicle_types(cls) -> List[Dict]:
        """Get all vehicle type definitions"""
        mappings = cls.load_mappings()
        return mappings.get("vehicle_types", [])

    @classmethod
    def get_pollutants(cls) -> List[Dict]:
        """Get all pollutant definitions"""
        mappings = cls.load_mappings()
        return mappings.get("pollutants", [])

    @classmethod
    def get_column_patterns(cls, task_type: str) -> Dict[str, Dict]:
        """
        Get column patterns for a specific task type

        Args:
            task_type: "micro_emission" or "macro_emission"

        Returns:
            Dictionary of column patterns
        """
        mappings = cls.load_mappings()
        patterns = mappings.get("column_patterns", {})
        return patterns.get(task_type, {})

    @classmethod
    def get_defaults(cls) -> Dict[str, Any]:
        """Get default values"""
        mappings = cls.load_mappings()
        return mappings.get("defaults", {})

    @classmethod
    def get_vsp_params(cls, vehicle_id: int) -> Optional[Dict]:
        """
        Get VSP parameters for a vehicle type

        Args:
            vehicle_id: MOVES vehicle type ID

        Returns:
            VSP parameters or None if not found
        """
        vehicle_types = cls.get_vehicle_types()
        for vtype in vehicle_types:
            if vtype.get("id") == vehicle_id:
                return vtype.get("vsp_params")
        return None

    @classmethod
    def get_vsp_bins(cls) -> Dict[int, Dict]:
        """Get VSP bin definitions"""
        mappings = cls.load_mappings()
        return mappings.get("vsp_bins", {})

    @classmethod
    def reload(cls):
        """Force reload all configurations (useful for testing)"""
        cls._mappings_cache = None
        cls._prompts_cache = None
        logger.info("Configuration cache cleared")


# Convenience functions
def get_config_loader() -> ConfigLoader:
    """Get the configuration loader instance"""
    return ConfigLoader


def load_mappings() -> Dict[str, Any]:
    """Convenience function to load mappings"""
    return ConfigLoader.load_mappings()


def load_prompts() -> Dict[str, str]:
    """Convenience function to load prompts"""
    return ConfigLoader.load_prompts()
