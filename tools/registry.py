"""
Tool Registry
Manages tool registration and retrieval
"""
import logging
from typing import Dict, Optional
from tools.base import BaseTool

logger = logging.getLogger(__name__)


class ToolName(str):
    """String-compatible tool name wrapper with a `.name` attribute for compatibility."""

    @property
    def name(self) -> str:
        return str(self)


class ToolRegistry:
    """
    Tool registry for managing available tools

    Singleton pattern to ensure single registry instance
    """

    _instance = None
    _tools: Dict[str, BaseTool] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def register(self, name: str, tool: BaseTool):
        """
        Register a tool

        Args:
            name: Tool name (should match function name in definitions)
            tool: Tool instance
        """
        self._tools[name] = tool
        logger.info(f"Registered tool: {name}")

    def get(self, name: str) -> Optional[BaseTool]:
        """
        Get a tool by name

        Args:
            name: Tool name

        Returns:
            Tool instance or None if not found
        """
        return self._tools.get(name)

    def list_tools(self) -> list:
        """Get list of registered tool names as string-compatible wrappers."""
        return [ToolName(name) for name in self._tools.keys()]

    def clear(self):
        """Clear all registered tools (useful for testing)"""
        self._tools.clear()
        logger.info("Cleared tool registry")


# Singleton instance
_registry = ToolRegistry()


def get_registry() -> ToolRegistry:
    """Get the global tool registry"""
    return _registry


def register_tool(name: str, tool: BaseTool):
    """Convenience function to register a tool"""
    _registry.register(name, tool)


class ToolRegistrationError(Exception):
    """Raised when one or more tools fail to register during startup."""


def init_tools():
    """
    Initialize and register all tools

    This should be called at application startup.  If any tool fails to
    register the error is logged but registration continues for the
    remaining tools; all failures are collected and raised as a single
    :class:`ToolRegistrationError` at the end.
    """
    logger.info("Initializing tools...")

    errors: list[tuple[str, str]] = []

    def _register(name, factory):
        try:
            register_tool(name, factory())
        except Exception as e:
            msg = f"Failed to register {name}: {e}"
            logger.error(msg)
            errors.append((name, str(e)))

    # Import and register tools
    from tools.emission_factors import EmissionFactorsTool
    _register("query_emission_factors", EmissionFactorsTool)

    from tools.micro_emission import MicroEmissionTool
    _register("calculate_micro_emission", MicroEmissionTool)

    from tools.macro_emission import MacroEmissionTool
    _register("calculate_macro_emission", MacroEmissionTool)

    from tools.file_analyzer import FileAnalyzerTool
    _register("analyze_file", FileAnalyzerTool)

    from tools.clean_dataframe import CleanDataFrameTool
    _register("clean_dataframe", CleanDataFrameTool)

    from tools.knowledge import KnowledgeTool
    _register("query_knowledge", KnowledgeTool)

    from tools.dispersion import DispersionTool
    _register("calculate_dispersion", DispersionTool)

    from tools.hotspot import HotspotTool
    _register("analyze_hotspots", HotspotTool)

    from tools.spatial_renderer import SpatialRendererTool
    _register("render_spatial_map", SpatialRendererTool)

    from tools.scenario_compare import ScenarioCompareTool
    _register("compare_scenarios", ScenarioCompareTool)

    logger.info(f"Initialized {len(_registry.list_tools())} tools: {_registry.list_tools()}")

    if errors:
        raise ToolRegistrationError(
            f"{len(errors)} tool(s) failed to register: "
            + "; ".join(f"{name}: {msg}" for name, msg in errors)
        )
