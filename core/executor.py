"""
Tool Executor - Executes tool calls with transparent standardization
"""
import logging
from typing import Dict, Any
from tools.registry import get_registry
from services.standardizer import get_standardizer

logger = logging.getLogger(__name__)


class ToolExecutor:
    """
    Tool executor with transparent standardization

    Design:
    1. Receives tool calls from LLM
    2. Standardizes parameters (transparent to LLM)
    3. Executes tools
    4. Returns structured results
    """

    def __init__(self):
        self.registry = get_registry()
        self.standardizer = get_standardizer()

        # Initialize tools if not already done
        if not self.registry.list_tools():
            from tools import init_tools
            init_tools()
            logger.info(f"Initialized {len(self.registry.list_tools())} tools")

    async def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        file_path: str = None
    ) -> Dict:
        """
        Execute a tool call

        Flow:
        1. Get tool from registry
        2. Standardize parameters (transparent)
        3. Validate parameters
        4. Execute tool
        5. Format result

        Args:
            tool_name: Name of tool to execute
            arguments: Tool arguments from LLM
            file_path: Optional file path context

        Returns:
            Execution result dictionary
        """
        # 1. Get tool
        tool = self.registry.get(tool_name)
        if not tool:
            return {
                "success": False,
                "error": True,
                "message": f"Unknown tool: {tool_name}"
            }

        # 2. Standardize parameters (transparent to LLM)
        try:
            logger.info(f"[Executor] Original arguments from LLM for {tool_name}: {arguments}")
            standardized_args = self._standardize_arguments(tool_name, arguments)
            logger.info(f"[Executor] Standardized arguments: {standardized_args}")
        except StandardizationError as e:
            logger.error(f"Standardization failed for {tool_name}: {e}")
            return {
                "success": False,
                "error": True,
                "error_type": "standardization",
                "message": str(e),
                "suggestions": e.suggestions if hasattr(e, 'suggestions') else None
            }

        # 3. Add file path if needed
        if file_path and "file_path" not in standardized_args:
            standardized_args["file_path"] = file_path
            logger.info(f"[Executor] Auto-injected file_path: {file_path}")

        # 4. Execute tool
        try:
            logger.info(f"Executing {tool_name} with standardized args")
            result = await tool.execute(**standardized_args)

            logger.info(f"{tool_name} execution completed. Success: {result.success}")
            if not result.success:
                logger.error(f"{tool_name} failed: {result.data if result.error else 'Unknown error'}")

            # Convert ToolResult to dict
            return {
                "success": result.success,
                "data": result.data,
                "error": result.error,
                "summary": result.summary,
                "chart_data": result.chart_data,
                "table_data": result.table_data,
                "download_file": result.download_file,
                "message": result.error if result.error else result.summary
            }

        except MissingParameterError as e:
            return {
                "success": False,
                "error": True,
                "error_type": "missing_parameter",
                "message": str(e),
                "missing_params": e.params if hasattr(e, 'params') else []
            }

        except Exception as e:
            logger.exception(f"Tool execution failed: {tool_name}")
            return {
                "success": False,
                "error": True,
                "error_type": "execution",
                "message": f"Execution failed: {str(e)}"
            }

    def _standardize_arguments(self, tool_name: str, arguments: Dict) -> Dict:
        """
        Standardize arguments transparently

        This is where the magic happens - LLM passes user's original input,
        we standardize it here without LLM knowing

        Args:
            tool_name: Tool name (for context)
            arguments: Raw arguments from LLM

        Returns:
            Standardized arguments

        Raises:
            StandardizationError: If standardization fails
        """
        standardized = {}

        for key, value in arguments.items():
            if key == "vehicle_type" and value:
                # Standardize vehicle type
                std_value = self.standardizer.standardize_vehicle(value)
                if std_value is None:
                    raise StandardizationError(
                        f"Cannot recognize vehicle type: '{value}'",
                        suggestions=self.standardizer.get_vehicle_suggestions()
                    )
                standardized[key] = std_value
                logger.debug(f"Standardized vehicle: '{value}' -> '{std_value}'")

            elif key == "pollutant" and value:
                # Standardize single pollutant
                std_value = self.standardizer.standardize_pollutant(value)
                if std_value is None:
                    raise StandardizationError(
                        f"Cannot recognize pollutant: '{value}'",
                        suggestions=self.standardizer.get_pollutant_suggestions()
                    )
                standardized[key] = std_value
                logger.debug(f"Standardized pollutant: '{value}' -> '{std_value}'")

            elif key == "pollutants" and value:
                # Standardize pollutant list
                std_list = []
                for pol in value:
                    std_pol = self.standardizer.standardize_pollutant(pol)
                    if std_pol:
                        std_list.append(std_pol)
                    else:
                        # Keep original if can't standardize
                        std_list.append(pol)
                        logger.warning(f"Could not standardize pollutant: '{pol}'")
                standardized[key] = std_list

            else:
                # Pass through other parameters
                standardized[key] = value

        return standardized


class StandardizationError(Exception):
    """Raised when standardization fails"""
    def __init__(self, message: str, suggestions: list = None):
        super().__init__(message)
        self.suggestions = suggestions


class MissingParameterError(Exception):
    """Raised when required parameters are missing"""
    def __init__(self, message: str, params: list = None):
        super().__init__(message)
        self.params = params or []
