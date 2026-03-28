"""
Tool Executor - Executes tool calls with transparent standardization
"""
import logging
import time
from typing import Dict, Any, List, Optional
from config import get_config
from tools.registry import get_registry
from services.standardization_engine import BatchStandardizationError, StandardizationEngine

logger = logging.getLogger(__name__)


def _compact_scalar_dict(data: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    """Extract a small scalar-only summary from a dictionary."""
    compact: Dict[str, Any] = {}
    for key in keys:
        value = data.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            compact[key] = value
    return compact


def _summarize_spatial_payload(data: Any) -> Dict[str, Any]:
    """Summarize large spatial payloads so traces/logs stay compact."""
    if not isinstance(data, dict):
        return {"type": type(data).__name__}

    summary: Dict[str, Any] = {"keys": list(data.keys())[:12]}

    query_info = data.get("query_info")
    if isinstance(query_info, dict):
        query_summary = _compact_scalar_dict(
            query_info,
            ["pollutant", "model_year", "season", "method", "link_count", "road_count"],
        )
        pollutants = query_info.get("pollutants")
        if isinstance(pollutants, list):
            query_summary["pollutants"] = list(pollutants[:8])
        if query_summary:
            summary["query_info"] = query_summary

    results = data.get("results")
    if isinstance(results, list):
        summary["results_count"] = len(results)

    summary_block = data.get("summary")
    if isinstance(summary_block, dict):
        compact_summary = {
            key: value
            for key, value in summary_block.items()
            if isinstance(value, (str, int, float, bool)) or value is None
        }
        if compact_summary:
            summary["summary"] = compact_summary

    raster_grid = data.get("raster_grid")
    if isinstance(raster_grid, dict):
        raster_summary = _compact_scalar_dict(
            raster_grid,
            ["rows", "cols", "resolution_m", "nodata"],
        )
        cell_centers = raster_grid.get("cell_centers_wgs84")
        if isinstance(cell_centers, list):
            raster_summary["cell_centers"] = len(cell_centers)
        cell_receptor_map = raster_grid.get("cell_receptor_map")
        if isinstance(cell_receptor_map, dict):
            raster_summary["cell_receptor_map"] = len(cell_receptor_map)
        stats = raster_grid.get("stats")
        if isinstance(stats, dict):
            raster_summary["nonzero_cells"] = stats.get("nonzero_cells")
        if raster_summary:
            summary["raster_grid"] = raster_summary

    concentration_grid = data.get("concentration_grid")
    if isinstance(concentration_grid, dict):
        concentration_summary = {}
        receptors = concentration_grid.get("receptors")
        if isinstance(receptors, list):
            concentration_summary["receptors"] = len(receptors)
        time_keys = concentration_grid.get("time_keys")
        if isinstance(time_keys, list):
            concentration_summary["time_keys"] = len(time_keys)
        if concentration_summary:
            summary["concentration_grid"] = concentration_summary

    road_contributions = data.get("road_contributions")
    if isinstance(road_contributions, dict):
        road_summary = _compact_scalar_dict(road_contributions, ["tracking_mode", "description"])
        receptor_top_roads = road_contributions.get("receptor_top_roads")
        if isinstance(receptor_top_roads, dict):
            road_summary["receptor_top_roads"] = len(receptor_top_roads)
        road_id_map = road_contributions.get("road_id_map")
        if isinstance(road_id_map, list):
            road_summary["road_id_map"] = len(road_id_map)
        if road_summary:
            summary["road_contributions"] = road_summary

    hotspots = data.get("hotspots")
    if isinstance(hotspots, list):
        summary["hotspots_count"] = len(hotspots)

    coverage = data.get("coverage_assessment")
    if isinstance(coverage, dict):
        summary["coverage_assessment"] = {
            "level": coverage.get("level"),
            "warnings": len(coverage.get("warnings", [])) if isinstance(coverage.get("warnings"), list) else 0,
        }

    meteorology = data.get("meteorology_used")
    if isinstance(meteorology, dict):
        summary["meteorology_used"] = _compact_scalar_dict(
            meteorology,
            ["_source_mode", "_preset_name", "wind_speed", "wind_direction", "stability_class", "mixing_height"],
        )

    return summary


def _summarize_argument_value(key: str, value: Any) -> Any:
    """Summarize large argument payloads for logs and traces."""
    if key == "_last_result":
        if not isinstance(value, dict):
            return {"type": type(value).__name__}
        return {
            "type": "injected_last_result",
            "success": bool(value.get("success") or value.get("status") == "success"),
            "data": _summarize_spatial_payload(value.get("data", value)),
        }

    if isinstance(value, dict):
        if len(value) <= 8 and all(isinstance(item, (str, int, float, bool)) or item is None for item in value.values()):
            return dict(value)
        return {"type": "dict", "keys": list(value.keys())[:12], "size": len(value)}

    if isinstance(value, list):
        if len(value) <= 10 and all(isinstance(item, (str, int, float, bool)) or item is None for item in value):
            return list(value)
        return {"type": "list", "size": len(value)}

    return value


def summarize_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Create a log-safe trace-safe argument summary."""
    return {
        key: _summarize_argument_value(key, value)
        for key, value in dict(arguments or {}).items()
    }


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
        self.runtime_config = get_config()
        self._std_engine = StandardizationEngine(self.runtime_config.standardization_config)
        self.standardizer = self._std_engine.rule_standardizer
        self._last_standardization_records: List[Dict[str, Any]] = []

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
        start_time = time.perf_counter()
        summarized_original_args = summarize_arguments(arguments or {})
        exec_trace = {
            "tool_name": tool_name,
            "original_arguments": summarized_original_args,
            "standardization_enabled": self.runtime_config.enable_executor_standardization,
            "file_path_context": file_path,
        }

        # 1. Get tool
        tool = self.registry.get(tool_name)
        if not tool:
            return {
                "success": False,
                "error": True,
                "message": f"Unknown tool: {tool_name}",
                "_trace": exec_trace,
            }

        # 2. Standardize parameters (transparent to LLM)
        std_records: List[Dict[str, Any]] = []
        try:
            if logger.isEnabledFor(logging.INFO):
                logger.info("[Executor] Original arguments for %s: %s", tool_name, summarized_original_args)
            standardized_args, std_records = self._standardize_arguments(tool_name, arguments or {})
            summarized_standardized_args = summarize_arguments(standardized_args)
            if logger.isEnabledFor(logging.INFO):
                logger.info("[Executor] Standardized arguments for %s: %s", tool_name, summarized_standardized_args)
            exec_trace["standardized_arguments"] = summarized_standardized_args
            exec_trace["standardization_records"] = std_records
        except StandardizationError as e:
            logger.error(f"Standardization failed for {tool_name}: {e}")
            return {
                "success": False,
                "error": True,
                "error_type": "standardization",
                "message": str(e),
                "suggestions": e.suggestions if hasattr(e, "suggestions") else None,
                "param_name": e.param_name if hasattr(e, "param_name") else None,
                "original_value": e.original_value if hasattr(e, "original_value") else None,
                "negotiation_eligible": bool(getattr(e, "negotiation_eligible", False)),
                "trigger_reason": getattr(e, "trigger_reason", None),
                "_standardization_records": e.records if hasattr(e, "records") else std_records,
                "_trace": {
                    **exec_trace,
                    "standardization_records": e.records if hasattr(e, "records") else std_records,
                    "error": str(e),
                    "duration_ms": round((time.perf_counter() - start_time) * 1000, 2),
                },
            }

        # 3. Add file path if needed
        if file_path and "file_path" not in standardized_args:
            standardized_args["file_path"] = file_path
            logger.info(f"[Executor] Auto-injected file_path: {file_path}")
            exec_trace["auto_injected_file_path"] = True
        else:
            exec_trace["auto_injected_file_path"] = False

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
                "map_data": result.map_data,
                "download_file": result.download_file,
                "message": result.error if result.error else result.summary,
                "_standardization_records": std_records,
                "_trace": {
                    **exec_trace,
                    "standardization_records": std_records,
                    "duration_ms": round((time.perf_counter() - start_time) * 1000, 2),
                },
            }

        except MissingParameterError as e:
            return {
                "success": False,
                "error": True,
                "error_type": "missing_parameter",
                "message": str(e),
                "missing_params": e.params if hasattr(e, 'params') else [],
                "_standardization_records": std_records,
                "_trace": {
                    **exec_trace,
                    "standardization_records": std_records,
                    "duration_ms": round((time.perf_counter() - start_time) * 1000, 2),
                },
            }

        except Exception as e:
            logger.exception(f"Tool execution failed: {tool_name}")
            return {
                "success": False,
                "error": True,
                "error_type": "execution",
                "message": f"Execution failed: {str(e)}",
                "_standardization_records": std_records,
                "_trace": {
                    **exec_trace,
                    "standardization_records": std_records,
                    "duration_ms": round((time.perf_counter() - start_time) * 1000, 2),
                },
            }

    def _standardize_arguments(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Standardize tool arguments using domain-specific rules.

        Args:
            tool_name: Tool name (for context)
            arguments: Raw arguments from LLM

        Returns:
            Tuple of (standardized_arguments, standardization_records).

        Raises:
            StandardizationError: If standardization fails
        """
        if not self.runtime_config.enable_executor_standardization:
            return dict(arguments or {}), []
        try:
            standardized, records = self._std_engine.standardize_batch(
                params=arguments,
                tool_name=tool_name,
            )
            self._last_standardization_records = list(records)
            return standardized, records
        except BatchStandardizationError as exc:
            self._last_standardization_records = list(exc.records)
            raise StandardizationError(
                str(exc),
                suggestions=exc.suggestions,
                records=exc.records,
                param_name=exc.param_name,
                original_value=exc.original_value,
                negotiation_eligible=exc.negotiation_eligible,
                trigger_reason=exc.trigger_reason,
            ) from exc


class StandardizationError(Exception):
    """Raised when standardization fails"""

    def __init__(
        self,
        message: str,
        suggestions: list = None,
        records: List[Dict[str, Any]] = None,
        param_name: Optional[str] = None,
        original_value: Any = None,
        negotiation_eligible: bool = False,
        trigger_reason: Optional[str] = None,
    ):
        super().__init__(message)
        self.suggestions = suggestions or []
        self.records = records or []
        self.param_name = param_name
        self.original_value = original_value
        self.negotiation_eligible = negotiation_eligible
        self.trigger_reason = trigger_reason


class MissingParameterError(Exception):
    """Raised when required parameters are missing"""
    def __init__(self, message: str, params: list = None):
        super().__init__(message)
        self.params = params or []
