"""
Tool Base Classes
Defines the base interface for all tools
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """
    Standardized tool execution result

    All tools return this structure for consistency
    """
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    summary: Optional[str] = None  # Human-readable summary for LLM
    chart_data: Optional[Dict] = None  # Chart data for visualization
    table_data: Optional[Dict] = None  # Table data for display
    download_file: Optional[str] = None  # File path for download


class BaseTool(ABC):
    """
    Base class for all tools

    Design principles:
    1. Tools are self-contained and stateless
    2. Standardization happens inside tools (transparent to LLM)
    3. Tools return structured ToolResult
    4. Tools handle their own errors gracefully
    """

    def __init__(self):
        self.name = self.__class__.__name__
        logger.info(f"Initialized tool: {self.name}")

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """
        Execute the tool with given parameters

        Args:
            **kwargs: Tool-specific parameters

        Returns:
            ToolResult with success status and data/error
        """
        pass

    def _success(
        self,
        data: Dict[str, Any],
        summary: str,
        chart_data: Optional[Dict] = None,
        table_data: Optional[Dict] = None,
        download_file: Optional[str] = None
    ) -> ToolResult:
        """Helper to create success result"""
        return ToolResult(
            success=True,
            data=data,
            summary=summary,
            chart_data=chart_data,
            table_data=table_data,
            download_file=download_file
        )

    def _error(self, message: str, suggestions: Optional[list] = None) -> ToolResult:
        """Helper to create error result"""
        error_data = {"message": message}
        if suggestions:
            error_data["suggestions"] = suggestions

        return ToolResult(
            success=False,
            error=message,
            data=error_data
        )

    def _validate_required_params(self, params: Dict, required: list) -> Optional[str]:
        """
        Validate required parameters

        Args:
            params: Parameter dictionary
            required: List of required parameter names

        Returns:
            Error message if validation fails, None if success
        """
        missing = [p for p in required if p not in params or params[p] is None]
        if missing:
            return f"Missing required parameters: {', '.join(missing)}"
        return None
