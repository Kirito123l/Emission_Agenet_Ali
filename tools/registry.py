"""
Tool Registry
Manages tool registration and retrieval
"""
import logging
from typing import Dict, Optional
from tools.base import BaseTool

logger = logging.getLogger(__name__)


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
        """Get list of registered tool names"""
        return list(self._tools.keys())

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


def init_tools():
    """
    Initialize and register all tools

    This should be called at application startup
    """
    logger.info("Initializing tools...")

    # Import and register tools
    try:
        from tools.emission_factors import EmissionFactorsTool
        register_tool("query_emission_factors", EmissionFactorsTool())
    except Exception as e:
        logger.error(f"Failed to register emission_factors tool: {e}")

    try:
        from tools.micro_emission import MicroEmissionTool
        register_tool("calculate_micro_emission", MicroEmissionTool())
    except Exception as e:
        logger.error(f"Failed to register micro_emission tool: {e}")

    try:
        from tools.macro_emission import MacroEmissionTool
        register_tool("calculate_macro_emission", MacroEmissionTool())
    except Exception as e:
        logger.error(f"Failed to register macro_emission tool: {e}")

    try:
        from tools.file_analyzer import FileAnalyzerTool
        register_tool("analyze_file", FileAnalyzerTool())
    except Exception as e:
        logger.error(f"Failed to register file_analyzer tool: {e}")

    try:
        from tools.knowledge import KnowledgeTool
        register_tool("query_knowledge", KnowledgeTool())
    except Exception as e:
        logger.error(f"Failed to register knowledge tool: {e}")

    logger.info(f"Initialized {len(_registry.list_tools())} tools: {_registry.list_tools()}")
