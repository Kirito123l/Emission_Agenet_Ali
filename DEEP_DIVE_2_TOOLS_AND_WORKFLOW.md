# DEEP_DIVE_2_TOOLS_AND_WORKFLOW

本文仅描述当前代码现状，不包含建议。所有结论均附文件路径、函数名或对象名、行号；代码片段均为完整摘录。

## 1. BaseTool 完整定义

- `tools/base.py` 当前总行数为 `127`。

- 文件内定义的对象为 `ToolResult`（`tools/base.py:14-28`）、`PreflightCheckResult`（`tools/base.py:31-37`）、`BaseTool`（`tools/base.py:40-127`）。

- 文件：`tools/base.py`
- 对象：`tools/base.py 全文件`
- 行号：`1-127`

```python
"""
Tool Base Classes
Defines the base interface for all tools
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
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
    map_data: Optional[Dict[str, Any]] = None  # Map data for geographic visualization


@dataclass
class PreflightCheckResult:
    """Result of tool preflight check (asset availability)."""
    is_ready: bool
    reason_code: Optional[str] = None
    message: Optional[str] = None
    missing_requirements: Optional[List[str]] = field(default_factory=list)
    details: Optional[Dict[str, Any]] = field(default_factory=dict)


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

    def preflight_check(self, parameters: Dict[str, Any]) -> PreflightCheckResult:
        """
        Preflight check for tool execution (asset availability).
        Override in subclass to check tool-specific dependencies.

        Args:
            parameters: Tool parameters that will be used

        Returns:
            PreflightCheckResult indicating readiness
        """
        return PreflightCheckResult(is_ready=True)

    def _success(
        self,
        data: Dict[str, Any],
        summary: str,
        chart_data: Optional[Dict] = None,
        table_data: Optional[Dict] = None,
        download_file: Optional[str] = None,
        map_data: Optional[Dict[str, Any]] = None
    ) -> ToolResult:
        """Helper to create success result"""
        return ToolResult(
            success=True,
            data=data,
            summary=summary,
            chart_data=chart_data,
            table_data=table_data,
            download_file=download_file,
            map_data=map_data
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
```

## 2. 每个工具的精确接口

### 2.0 StandardizationEngine 可识别参数名

- 文件：`services/standardization_engine.py`
- 对象：`PARAM_TYPE_REGISTRY`
- 行号：`35-43`

```python
PARAM_TYPE_REGISTRY: Dict[str, str] = {
    "vehicle_type": "vehicle_type",
    "pollutant": "pollutant",
    "pollutants": "pollutant_list",
    "season": "season",
    "road_type": "road_type",
    "meteorology": "meteorology",
    "stability_class": "stability_class",
}
```

### 2.1 `tools/file_analyzer.py`

- 工具类：`FileAnalyzerTool`，定义于 `tools/file_analyzer.py:28-1462`。

- 文件：`tools/file_analyzer.py`
- 对象：`FileAnalyzerTool.execute 签名`
- 行号：`39-39`

```python
    async def execute(self, file_path: str, **kwargs) -> ToolResult:
```

- `preflight_check()` 未在 `tools/file_analyzer.py` 中覆盖；当前使用 `BaseTool.preflight_check()` 默认实现（`tools/base.py:68-79`）。

- 文件：`tools/base.py`
- 对象：`BaseTool.preflight_check 默认实现`
- 行号：`68-79`

```python
    def preflight_check(self, parameters: Dict[str, Any]) -> PreflightCheckResult:
        """
        Preflight check for tool execution (asset availability).
        Override in subclass to check tool-specific dependencies.

        Args:
            parameters: Tool parameters that will be used

        Returns:
            PreflightCheckResult indicating readiness
        """
        return PreflightCheckResult(is_ready=True)
```

- 在 `tools/file_analyzer.py:39-102` 的 `execute()` 中未发现对 `calculators/*` 或独立计算器对象的直接调用语句。

- 按 `StandardizationEngine` 当前参数注册表（`services/standardization_engine.py:35-43`），该工具当前没有会被识别并处理的参数名。

### 2.2 `tools/emission_factors.py`

- 工具类：`EmissionFactorsTool`，定义于 `tools/emission_factors.py:20-228`。

- 文件：`tools/emission_factors.py`
- 对象：`EmissionFactorsTool.execute 签名`
- 行号：`91-91`

```python
    async def execute(self, **kwargs) -> ToolResult:
```

- `preflight_check()` 未在 `tools/emission_factors.py` 中覆盖；当前使用 `BaseTool.preflight_check()` 默认实现（`tools/base.py:68-79`）。

- 文件：`tools/base.py`
- 对象：`BaseTool.preflight_check 默认实现`
- 行号：`68-79`

```python
    def preflight_check(self, parameters: Dict[str, Any]) -> PreflightCheckResult:
        """
        Preflight check for tool execution (asset availability).
        Override in subclass to check tool-specific dependencies.

        Args:
            parameters: Tool parameters that will be used

        Returns:
            PreflightCheckResult indicating readiness
        """
        return PreflightCheckResult(is_ready=True)
```

- `execute()` 内部的计算/底层调用语句位于 `tools/emission_factors.py` 的行号：`141-148`。

- 文件：`tools/emission_factors.py`
- 对象：`EmissionFactorsTool.execute 调用语句 1`
- 行号：`141-148`

```python
                result = self._calculator.query(
                    vehicle_type=vehicle_type,
                    pollutant=pollutant,
                    model_year=model_year,
                    season=season,
                    road_type=road_type,
                    return_curve=return_curve
                )
```

- 按 `StandardizationEngine` 当前参数注册表（`services/standardization_engine.py:35-43`），该工具会被识别并处理的参数名为：`vehicle_type, season, road_type, pollutants, pollutant`。

### 2.3 `tools/micro_emission.py`

- 工具类：`MicroEmissionTool`，定义于 `tools/micro_emission.py:23-251`。

- 文件：`tools/micro_emission.py`
- 对象：`MicroEmissionTool.execute 签名`
- 行号：`46-46`

```python
    async def execute(self, **kwargs) -> ToolResult:
```

- `preflight_check()` 未在 `tools/micro_emission.py` 中覆盖；当前使用 `BaseTool.preflight_check()` 默认实现（`tools/base.py:68-79`）。

- 文件：`tools/base.py`
- 对象：`BaseTool.preflight_check 默认实现`
- 行号：`68-79`

```python
    def preflight_check(self, parameters: Dict[str, Any]) -> PreflightCheckResult:
        """
        Preflight check for tool execution (asset availability).
        Override in subclass to check tool-specific dependencies.

        Args:
            parameters: Tool parameters that will be used

        Returns:
            PreflightCheckResult indicating readiness
        """
        return PreflightCheckResult(is_ready=True)
```

- `execute()` 内部的计算/底层调用语句位于 `tools/micro_emission.py` 的行号：`115-121`。

- 文件：`tools/micro_emission.py`
- 对象：`MicroEmissionTool.execute 调用语句 1`
- 行号：`115-121`

```python
            result = self._calculator.calculate(
                trajectory_data=trajectory_data,
                vehicle_type=vehicle_type,
                pollutants=pollutants,
                model_year=model_year,
                season=season
            )
```

- 按 `StandardizationEngine` 当前参数注册表（`services/standardization_engine.py:35-43`），该工具会被识别并处理的参数名为：`vehicle_type, pollutants, season`。

### 2.4 `tools/macro_emission.py`

- 工具类：`MacroEmissionTool`，定义于 `tools/macro_emission.py:34-950`。

- 文件：`tools/macro_emission.py`
- 对象：`MacroEmissionTool.execute 签名`
- 行号：`614-614`

```python
    async def execute(self, **kwargs) -> ToolResult:
```

- `preflight_check()` 未在 `tools/macro_emission.py` 中覆盖；当前使用 `BaseTool.preflight_check()` 默认实现（`tools/base.py:68-79`）。

- 文件：`tools/base.py`
- 对象：`BaseTool.preflight_check 默认实现`
- 行号：`68-79`

```python
    def preflight_check(self, parameters: Dict[str, Any]) -> PreflightCheckResult:
        """
        Preflight check for tool execution (asset availability).
        Override in subclass to check tool-specific dependencies.

        Args:
            parameters: Tool parameters that will be used

        Returns:
            PreflightCheckResult indicating readiness
        """
        return PreflightCheckResult(is_ready=True)
```

- `execute()` 内部的计算/底层调用语句位于 `tools/macro_emission.py` 的行号：`713-713`, `721-721`, `745-751`。

- 文件：`tools/macro_emission.py`
- 对象：`MacroEmissionTool.execute 调用语句 1`
- 行号：`713-713`

```python
                validation_errors = validate_overrides(overrides)
```

- 文件：`tools/macro_emission.py`
- 对象：`MacroEmissionTool.execute 调用语句 2`
- 行号：`721-721`

```python
                    links_data, override_summaries = apply_overrides(links_data, overrides)
```

- 文件：`tools/macro_emission.py`
- 对象：`MacroEmissionTool.execute 调用语句 3`
- 行号：`745-751`

```python
            result = self._calculator.calculate(
                links_data=links_data,
                pollutants=pollutants,
                model_year=model_year,
                season=season,
                default_fleet_mix=effective_default_fleet_mix
            )
```

- 按 `StandardizationEngine` 当前参数注册表（`services/standardization_engine.py:35-43`），该工具会被识别并处理的参数名为：`pollutants, season`。

### 2.5 `tools/dispersion.py`

- 工具类：`DispersionTool`，定义于 `tools/dispersion.py:57-564`。

- 文件：`tools/dispersion.py`
- 对象：`DispersionTool.execute 签名`
- 行号：`77-77`

```python
    async def execute(self, **kwargs) -> ToolResult:
```

- `preflight_check()` 已在 `tools/dispersion.py:383-441` 覆盖。

- 文件：`tools/dispersion.py`
- 对象：`DispersionTool.preflight_check`
- 行号：`383-441`

```python
    def preflight_check(self, parameters: Dict[str, Any]) -> PreflightCheckResult:
        """Check that dispersion model files exist for the requested parameters."""
        from calculators.dispersion import get_model_paths, STABILITY_ABBREV

        try:
            meteorology = str(parameters.get("meteorology", "urban_summer_day"))
            # .sfc inputs: stability class is unknown until the file is parsed at runtime
            if Path(meteorology).suffix.lower() == ".sfc":
                return PreflightCheckResult(is_ready=True)

            try:
                roughness_height = float(parameters.get("roughness_height", 0.5))
            except (TypeError, ValueError):
                roughness_height = 0.5

            stability_abbrev = self._resolve_stability_class(meteorology, parameters)
            if stability_abbrev is None:
                # Cannot determine stability ahead of time; let execute() handle it
                return PreflightCheckResult(is_ready=True)

            try:
                x0_path, xneg_path = get_model_paths(stability_abbrev, roughness_height)
            except ValueError:
                # Invalid roughness or stability value; let execute() handle with proper error
                return PreflightCheckResult(is_ready=True)

            missing = [p for p in (x0_path, xneg_path) if not p.exists()]
            if not missing:
                return PreflightCheckResult(is_ready=True)

            # Build availability map across all stability classes for the LLM
            available: list = []
            for abbrev in STABILITY_ABBREV:
                try:
                    p0, pn = get_model_paths(abbrev, roughness_height)
                    if p0.exists() and pn.exists():
                        available.append(abbrev)
                except Exception:
                    pass

            return PreflightCheckResult(
                is_ready=False,
                reason_code="model_asset_missing",
                message=(
                    f"Dispersion model files missing for stability class '{stability_abbrev}': "
                    + ", ".join(p.name for p in missing)
                ),
                missing_requirements=[f"model:{stability_abbrev}"],
                details={
                    "stability_class": stability_abbrev,
                    "roughness_height": roughness_height,
                    "missing_files": [p.name for p in missing],
                    "available_stability_classes": available,
                },
            )

        except Exception:
            logger.warning("Dispersion preflight check error, skipping", exc_info=True)
            return PreflightCheckResult(is_ready=True)
```

- `execute()` 内部的计算/底层调用语句位于 `tools/dispersion.py` 的行号：`118-118`, `137-143`。

- 文件：`tools/dispersion.py`
- 对象：`DispersionTool.execute 调用语句 1`
- 行号：`118-118`

```python
            roads_gdf, emissions_df = self._adapter.adapt(emission_data)
```

- 文件：`tools/dispersion.py`
- 对象：`DispersionTool.execute 调用语句 2`
- 行号：`137-143`

```python
            result = calculator.calculate(
                roads_gdf=roads_gdf,
                emissions_df=emissions_df,
                met_input=met_input,
                pollutant=pollutant,
                coverage_assessment=coverage,
            )
```

- 按 `StandardizationEngine` 当前参数注册表（`services/standardization_engine.py:35-43`），该工具会被识别并处理的参数名为：`meteorology, pollutant, stability_class`。

### 2.6 `tools/hotspot.py`

- 工具类：`HotspotTool`，定义于 `tools/hotspot.py:27-181`。

- 文件：`tools/hotspot.py`
- 对象：`HotspotTool.execute 签名`
- 行号：`38-38`

```python
    async def execute(self, **kwargs) -> ToolResult:
```

- `preflight_check()` 未在 `tools/hotspot.py` 中覆盖；当前使用 `BaseTool.preflight_check()` 默认实现（`tools/base.py:68-79`）。

- 文件：`tools/base.py`
- 对象：`BaseTool.preflight_check 默认实现`
- 行号：`68-79`

```python
    def preflight_check(self, parameters: Dict[str, Any]) -> PreflightCheckResult:
        """
        Preflight check for tool execution (asset availability).
        Override in subclass to check tool-specific dependencies.

        Args:
            parameters: Tool parameters that will be used

        Returns:
            PreflightCheckResult indicating readiness
        """
        return PreflightCheckResult(is_ready=True)
```

- `execute()` 内部的计算/底层调用语句位于 `tools/hotspot.py` 的行号：`71-81`。

- 文件：`tools/hotspot.py`
- 对象：`HotspotTool.execute 调用语句 1`
- 行号：`71-81`

```python
            result = self._analyzer.analyze(
                raster_grid=raster_grid,
                road_contributions=road_contributions,
                coverage_assessment=coverage_assessment,
                method=method,
                threshold_value=threshold_value,
                percentile=percentile,
                min_hotspot_area_m2=min_hotspot_area_m2,
                max_hotspots=max_hotspots,
                source_attribution=source_attribution,
            )
```

- 按 `StandardizationEngine` 当前参数注册表（`services/standardization_engine.py:35-43`），该工具当前没有会被识别并处理的参数名。

### 2.7 `tools/spatial_renderer.py`

- 工具类：`SpatialRendererTool`，定义于 `tools/spatial_renderer.py:80-788`。

- 文件：`tools/spatial_renderer.py`
- 对象：`SpatialRendererTool.execute 签名`
- 行号：`84-84`

```python
    async def execute(self, **kwargs) -> ToolResult:
```

- `preflight_check()` 未在 `tools/spatial_renderer.py` 中覆盖；当前使用 `BaseTool.preflight_check()` 默认实现（`tools/base.py:68-79`）。

- 文件：`tools/base.py`
- 对象：`BaseTool.preflight_check 默认实现`
- 行号：`68-79`

```python
    def preflight_check(self, parameters: Dict[str, Any]) -> PreflightCheckResult:
        """
        Preflight check for tool execution (asset availability).
        Override in subclass to check tool-specific dependencies.

        Args:
            parameters: Tool parameters that will be used

        Returns:
            PreflightCheckResult indicating readiness
        """
        return PreflightCheckResult(is_ready=True)
```

- 在 `tools/spatial_renderer.py:84-181` 的 `execute()` 中未发现对 `calculators/*` 或独立计算器对象的直接调用语句。

- 按 `StandardizationEngine` 当前参数注册表（`services/standardization_engine.py:35-43`），该工具会被识别并处理的参数名为：`pollutant`。

### 2.8 `tools/scenario_compare.py`

- 工具类：`ScenarioCompareTool`，定义于 `tools/scenario_compare.py:17-225`。

- 文件：`tools/scenario_compare.py`
- 对象：`ScenarioCompareTool.execute 签名`
- 行号：`28-37`

```python
    async def execute(
        self,
        result_types: List[str],
        baseline: str = "baseline",
        scenarios: Optional[List[str]] = None,
        scenario: Optional[str] = None,
        metrics: Optional[List[str]] = None,
        _context_store: Any = None,
        **kwargs: Any,
    ) -> ToolResult:
```

- `preflight_check()` 未在 `tools/scenario_compare.py` 中覆盖；当前使用 `BaseTool.preflight_check()` 默认实现（`tools/base.py:68-79`）。

- 文件：`tools/base.py`
- 对象：`BaseTool.preflight_check 默认实现`
- 行号：`68-79`

```python
    def preflight_check(self, parameters: Dict[str, Any]) -> PreflightCheckResult:
        """
        Preflight check for tool execution (asset availability).
        Override in subclass to check tool-specific dependencies.

        Args:
            parameters: Tool parameters that will be used

        Returns:
            PreflightCheckResult indicating readiness
        """
        return PreflightCheckResult(is_ready=True)
```

- `execute()` 内部的计算/底层调用语句位于 `tools/scenario_compare.py` 的行号：`75-80`, `100-105`。

- 文件：`tools/scenario_compare.py`
- 对象：`ScenarioCompareTool.execute 调用语句 1`
- 行号：`75-80`

```python
                all_comparisons[result_type] = self._comparator.compare(
                    result_type,
                    baseline_data,
                    scenario_data,
                    metrics,
                )
```

- 文件：`tools/scenario_compare.py`
- 对象：`ScenarioCompareTool.execute 调用语句 2`
- 行号：`100-105`

```python
            all_comparisons[result_type] = self._comparator.multi_compare(
                result_type,
                results_dict,
                baseline_label=baseline,
                metrics=metrics,
            )
```

- 按 `StandardizationEngine` 当前参数注册表（`services/standardization_engine.py:35-43`），该工具当前没有会被识别并处理的参数名。

### 2.9 `tools/knowledge.py`

- 工具类：`KnowledgeTool`，定义于 `tools/knowledge.py:16-73`。

- 文件：`tools/knowledge.py`
- 对象：`KnowledgeTool.execute 签名`
- 行号：`30-30`

```python
    async def execute(self, **kwargs) -> ToolResult:
```

- `preflight_check()` 未在 `tools/knowledge.py` 中覆盖；当前使用 `BaseTool.preflight_check()` 默认实现（`tools/base.py:68-79`）。

- 文件：`tools/base.py`
- 对象：`BaseTool.preflight_check 默认实现`
- 行号：`68-79`

```python
    def preflight_check(self, parameters: Dict[str, Any]) -> PreflightCheckResult:
        """
        Preflight check for tool execution (asset availability).
        Override in subclass to check tool-specific dependencies.

        Args:
            parameters: Tool parameters that will be used

        Returns:
            PreflightCheckResult indicating readiness
        """
        return PreflightCheckResult(is_ready=True)
```

- `execute()` 内部的计算/底层调用语句位于 `tools/knowledge.py` 的行号：`46-46`。

- 文件：`tools/knowledge.py`
- 对象：`KnowledgeTool.execute 调用语句 1`
- 行号：`46-46`

```python
            skill_result = self._skill.execute(**kwargs)
```

- 按 `StandardizationEngine` 当前参数注册表（`services/standardization_engine.py:35-43`），该工具当前没有会被识别并处理的参数名。

### 2.10 `tools/override_engine.py`

- `tools/override_engine.py` 当前不是 `BaseTool` 子类文件；它定义的是参数覆盖辅助函数和异常，而不是独立工具类。

- 文件范围：`tools/override_engine.py:1-316`；对象包括 `OverrideValidationError`（`21-22`）、`validate_overrides()`（`76-169`）、`apply_overrides()`（`172-237`）、`describe_overrides()`（`240-270`）。

- 因此该文件中不存在 `execute()` 和 `preflight_check()`。

- `calculate_macro_emission` 在 `tools/macro_emission.py:711-723` 导入并调用了 `validate_overrides` / `apply_overrides`。

- `overrides` 参数名不在 `StandardizationEngine` 的 `PARAM_TYPE_REGISTRY`（`services/standardization_engine.py:35-42`）中。

- 文件：`tools/override_engine.py`
- 对象：`validate_overrides`
- 行号：`76-169`

```python
def validate_overrides(overrides: List[Dict[str, Any]]) -> List[str]:
    """Validate override specifications and return a flat error list."""
    errors: List[str] = []
    if not isinstance(overrides, list):
        return ["overrides must be a list"]

    for index, override in enumerate(overrides):
        prefix = f"override[{index}]"
        if not isinstance(override, dict):
            errors.append(f"{prefix}: must be an object")
            continue

        column = override.get("column")
        if column not in OVERRIDABLE_COLUMNS:
            errors.append(
                f"{prefix}: column '{column}' is not overridable; "
                f"allowed={list(OVERRIDABLE_COLUMNS.keys())}"
            )
            continue

        column_spec = OVERRIDABLE_COLUMNS[column]
        where = override.get("where")
        if where is not None:
            if not isinstance(where, dict):
                errors.append(f"{prefix}: where must be an object")
            else:
                if not where.get("column"):
                    errors.append(f"{prefix}: where.column is required")
                op = where.get("op")
                if op not in ALLOWED_OPERATORS:
                    errors.append(
                        f"{prefix}: where.op '{op}' not in {list(ALLOWED_OPERATORS.keys())}"
                    )
                if "value" not in where:
                    errors.append(f"{prefix}: where.value is required")

        if column_spec["type"] == "fleet_mix":
            value = override.get("value")
            if not isinstance(value, dict):
                errors.append(f"{prefix}: fleet_mix value must be an object")
                continue

            unknown = sorted(set(value.keys()) - KNOWN_FLEET_CATEGORIES)
            if unknown:
                errors.append(f"{prefix}: unknown fleet categories: {unknown}")

            total = 0.0
            for category, pct in value.items():
                if not isinstance(pct, (int, float)) or pct < 0:
                    errors.append(
                        f"{prefix}: fleet_mix['{category}'] must be a non-negative number"
                    )
                    continue
                total += float(pct)
            if total < 90 or total > 110:
                errors.append(
                    f"{prefix}: fleet_mix percentages sum to {total:.1f}%, expected about 100%"
                )
            continue

        transform = override.get("transform", "set")
        if transform not in ALLOWED_TRANSFORMS:
            errors.append(
                f"{prefix}: unknown transform '{transform}'; allowed={list(ALLOWED_TRANSFORMS.keys())}"
            )
            continue

        if transform == "set":
            value = override.get("value")
            if not isinstance(value, (int, float)):
                errors.append(f"{prefix}: value must be numeric")
            else:
                numeric = float(value)
                if numeric < column_spec["min"] or numeric > column_spec["max"]:
                    errors.append(
                        f"{prefix}: value {numeric} out of range "
                        f"[{column_spec['min']}, {column_spec['max']}]"
                    )
        elif transform == "multiply":
            factor = override.get("factor")
            if factor is None:
                errors.append(f"{prefix}: multiply requires factor")
            elif not isinstance(factor, (int, float)):
                errors.append(f"{prefix}: factor must be numeric")
            elif float(factor) <= 0:
                errors.append(f"{prefix}: factor must be positive")
        elif transform == "add":
            offset = override.get("offset")
            if offset is None:
                errors.append(f"{prefix}: add requires offset")
            elif not isinstance(offset, (int, float)):
                errors.append(f"{prefix}: offset must be numeric")

    return errors
```

- 文件：`tools/override_engine.py`
- 对象：`apply_overrides`
- 行号：`172-237`

```python
def apply_overrides(
    links_data: List[Dict[str, Any]],
    overrides: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Apply validated overrides to links_data and return a copied result plus summaries."""
    modified = copy.deepcopy(links_data)
    if not modified or not overrides:
        return modified, []

    df = pd.DataFrame(modified)
    summaries: List[str] = []

    for index, override in enumerate(overrides):
        column = override["column"]
        if column not in OVERRIDABLE_COLUMNS:
            raise OverrideValidationError(f"override[{index}]: unsupported column {column}")

        where = override.get("where")
        mask = _build_mask(df, where, index)
        affected_count = int(mask.sum())

        if OVERRIDABLE_COLUMNS[column]["type"] == "fleet_mix":
            fleet_mix = _normalize_fleet_mix(override["value"])
            target_indices = list(df.index[mask])
            for row_index in target_indices:
                modified[row_index]["fleet_mix"] = dict(fleet_mix)
            desc = f"车队组成: {fleet_mix}（{affected_count}/{len(modified)} 行）"
            summaries.append(desc)
            continue

        if column not in df.columns:
            raise OverrideValidationError(
                f"override[{index}]: target column '{column}' not found in links_data"
            )

        transform = override.get("transform", "set")
        if transform == "set":
            value = float(override["value"])
            df.loc[mask, column] = value
            summaries.append(f"{column}: 设为 {value:g}（{affected_count}/{len(df)} 行）")
        elif transform == "multiply":
            factor = float(override["factor"])
            df.loc[mask, column] = pd.to_numeric(df.loc[mask, column], errors="coerce") * factor
            summaries.append(f"{column}: × {factor:g}（{affected_count}/{len(df)} 行）")
        elif transform == "add":
            offset = float(override["offset"])
            df.loc[mask, column] = pd.to_numeric(df.loc[mask, column], errors="coerce") + offset
            summaries.append(f"{column}: + {offset:g}（{affected_count}/{len(df)} 行）")
        else:
            raise OverrideValidationError(f"override[{index}]: unsupported transform '{transform}'")

        spec = OVERRIDABLE_COLUMNS[column]
        numeric_series = pd.to_numeric(df[column], errors="coerce")
        clamped = numeric_series.clip(lower=spec["min"], upper=spec["max"])
        clamped_count = int((clamped != numeric_series).fillna(False).sum())
        df[column] = clamped
        if clamped_count:
            summaries.append(
                f"  ⚠️ {clamped_count} 行被裁剪到 [{spec['min']}, {spec['max']}] 范围内"
            )

    result = df.to_dict(orient="records")
    for index, row in enumerate(modified):
        if "fleet_mix" in row:
            result[index]["fleet_mix"] = row["fleet_mix"]
    return result, summaries
```

- 文件：`tools/override_engine.py`
- 对象：`describe_overrides`
- 行号：`240-270`

```python
def describe_overrides(overrides: List[Dict[str, Any]]) -> str:
    """Return a short human-readable description of overrides."""
    if not overrides:
        return "无参数覆盖"

    parts: List[str] = []
    for override in overrides:
        if not isinstance(override, dict):
            continue

        column = str(override.get("column", "unknown"))
        if OVERRIDABLE_COLUMNS.get(column, {}).get("type") == "fleet_mix":
            parts.append(f"车队组成: {override.get('value', {})}")
            continue

        transform = override.get("transform", "set")
        if transform == "set":
            desc = f"{column}: 设为 {override.get('value')}"
        elif transform == "multiply":
            desc = f"{column}: × {override.get('factor')}"
        else:
            desc = f"{column}: + {override.get('offset')}"

        where = override.get("where")
        if isinstance(where, dict):
            desc += (
                f"（仅 {where.get('column')} {where.get('op')} {where.get('value')} 的行）"
            )
        parts.append(desc)

    return "；".join(parts) if parts else "无参数覆盖"
```

- 文件：`tools/macro_emission.py`
- 对象：`MacroEmissionTool.execute 中 override_engine 调用片段`
- 行号：`711-723`

```python
                from tools.override_engine import apply_overrides, validate_overrides, OverrideValidationError

                validation_errors = validate_overrides(overrides)
                if validation_errors:
                    return ToolResult(
                        success=False,
                        error=f"Override validation failed: {'; '.join(validation_errors)}",
                        data={"scenario_label": scenario_label, "overrides": overrides},
                    )
                try:
                    links_data, override_summaries = apply_overrides(links_data, overrides)
                except OverrideValidationError as exc:
                    return ToolResult(
```

## 3. TOOL_DEFINITIONS 完整内容

- `TOOL_DEFINITIONS` 定义于 `tools/definitions.py:6-403`。

- 当前文件总行数为 `403`。

- 文件：`tools/definitions.py`
- 对象：`tools/definitions.py 全文件`
- 行号：`1-403`

```python
"""
Tool Definitions for Tool Use Mode
Defines all tools in OpenAI function calling format
"""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "query_emission_factors",
            "description": "Query vehicle emission factor curves by speed. Returns chart and data table.",
            "parameters": {
                "type": "object",
                "properties": {
                    "vehicle_type": {
                        "type": "string",
                        "description": "Vehicle type. Pass user's original expression (e.g., '小汽车', '公交车', 'SUV'). System will automatically recognize it."
                    },
                    "pollutants": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of pollutants to query (e.g., ['CO2', 'NOx', 'PM2.5']). Single pollutant also uses this array."
                    },
                    "model_year": {
                        "type": "integer",
                        "description": "Vehicle model year (e.g., 2020). Range: 1995-2025."
                    },
                    "season": {
                        "type": "string",
                        "description": "Season (春季/夏季/秋季/冬季). Optional, defaults to summer if not provided."
                    },
                    "road_type": {
                        "type": "string",
                        "description": "Road type (快速路/地面道路). Optional, defaults to expressway if not provided."
                    },
                    "return_curve": {
                        "type": "boolean",
                        "description": "Whether to return full curve data. Default false."
                    }
                },
                "required": ["vehicle_type", "model_year"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_micro_emission",
            "description": "Calculate second-by-second emissions from vehicle trajectory data (time + speed). Use file_path for uploaded files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to trajectory data file. REQUIRED when user uploaded a file. You will see this path in the file context."
                    },
                    "trajectory_data": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Trajectory data array. Each point should have 't' (time in seconds) and 'speed_kph' (speed in km/h). Use this if user provides data directly."
                    },
                    "vehicle_type": {
                        "type": "string",
                        "description": "Vehicle type. Pass user's original expression. REQUIRED."
                    },
                    "pollutants": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of pollutants to calculate. Defaults to [CO2, NOx, PM2.5] if not provided."
                    },
                    "model_year": {
                        "type": "integer",
                        "description": "Vehicle model year. Defaults to 2020 if not provided."
                    },
                    "season": {
                        "type": "string",
                        "description": "Season. Optional."
                    }
                },
                "required": ["vehicle_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_macro_emission",
            "description": "Calculate road link emissions from traffic data (length + flow + speed). Use file_path for uploaded files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to road link data file."
                    },
                    "links_data": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Road link data array. Each link should have 'link_length_km', 'traffic_flow_vph', 'avg_speed_kph'. Use this if user provides data directly."
                    },
                    "pollutants": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of pollutants to calculate."
                    },
                    "fleet_mix": {
                        "type": "object",
                        "description": "Fleet composition (vehicle type percentages). Optional, uses default if not provided."
                    },
                    "model_year": {
                        "type": "integer",
                        "description": "Vehicle model year."
                    },
                    "season": {
                        "type": "string",
                        "description": "Season. Optional."
                    },
                    "overrides": {
                        "type": "array",
                        "description": "Parameter overrides for scenario simulation. Each override modifies one input column.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {
                                    "type": "string",
                                    "enum": ["avg_speed_kph", "traffic_flow_vph", "link_length_km", "fleet_mix"],
                                    "description": "Column to override"
                                },
                                "value": {
                                    "description": "Fixed value to set, or a fleet_mix object when column=fleet_mix"
                                },
                                "transform": {
                                    "type": "string",
                                    "enum": ["set", "multiply", "add"],
                                    "description": "Transform type. Default: set"
                                },
                                "factor": {
                                    "type": "number",
                                    "description": "Multiplication factor for transform=multiply"
                                },
                                "offset": {
                                    "type": "number",
                                    "description": "Additive offset for transform=add"
                                },
                                "where": {
                                    "type": "object",
                                    "description": "Condition to filter affected rows",
                                    "properties": {
                                        "column": {"type": "string"},
                                        "op": {
                                            "type": "string",
                                            "enum": [">", ">=", "<", "<=", "==", "!=", "in", "not_in"]
                                        },
                                        "value": {}
                                    }
                                }
                            },
                            "required": ["column"]
                        }
                    },
                    "scenario_label": {
                        "type": "string",
                        "description": "Short scenario label such as 'speed_30kmh' or 'bus_15pct'."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_file",
            "description": "Analyze uploaded file structure. Returns columns, data type, and preview.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file to analyze"
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_knowledge",
            "description": "Search emission knowledge base for standards, regulations, and technical concepts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The question or topic to search for in the knowledge base"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of knowledge entries to retrieve. Optional, defaults to 5."
                    },
                    "expectation": {
                        "type": "string",
                        "description": "Expected type of information (e.g., 'standard definition', 'regulation details'). Optional."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_dispersion",
            "description": (
                "Calculate pollutant dispersion/concentration distribution from vehicle emissions "
                "using the PS-XGB-RLINE surrogate model. Requires emission results (typically from "
                "calculate_macro_emission). Produces a spatial concentration raster field. "
                "Supports meteorology presets, custom parameters, or .sfc files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "emission_source": {
                        "type": "string",
                        "description": "Source of emission data. 'last_result' or a file path.",
                        "default": "last_result"
                    },
                    "meteorology": {
                        "type": "string",
                        "description": "Meteorology preset name, 'custom', or .sfc file path. Default: urban_summer_day.",
                        "default": "urban_summer_day"
                    },
                    "wind_speed": {
                        "type": "number",
                        "description": "Wind speed in m/s. Use with 'custom' or to override a preset."
                    },
                    "wind_direction": {
                        "type": "number",
                        "description": "Wind direction in degrees (0=N, 90=E, 180=S, 270=W). Use with 'custom' or to override a preset."
                    },
                    "stability_class": {
                        "type": "string",
                        "description": "Atmospheric stability: VS, S, N1, N2, U, VU.",
                        "enum": ["VS", "S", "N1", "N2", "U", "VU"]
                    },
                    "mixing_height": {
                        "type": "number",
                        "description": "Mixing layer height in meters. Default: 800."
                    },
                    "roughness_height": {
                        "type": "number",
                        "description": "Surface roughness: 0.05 (open), 0.5 (suburban), 1.0 (urban). Default: 0.5.",
                        "enum": [0.05, 0.5, 1.0]
                    },
                    "grid_resolution": {
                        "type": "number",
                        "description": "Display grid resolution in meters: 50, 100, or 200. Default: 50.",
                        "enum": [50, 100, 200],
                        "default": 50
                    },
                    "pollutant": {
                        "type": "string",
                        "description": "Pollutant name. Currently only NOx.",
                        "default": "NOx"
                    },
                    "scenario_label": {
                        "type": "string",
                        "description": "Scenario label used to resolve/store scenario-specific emission and dispersion results."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_hotspots",
            "description": (
                "Identify pollution hotspot areas and trace contributing road sources from "
                "dispersion results. Supports percentile or threshold methods. "
                "Does not re-run dispersion - analyzes stored results instantly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "description": "Identification method: 'percentile' (top N%) or 'threshold' (above value).",
                        "enum": ["percentile", "threshold"],
                        "default": "percentile"
                    },
                    "threshold_value": {
                        "type": "number",
                        "description": "Concentration threshold in ug/m3. Required when method='threshold'."
                    },
                    "percentile": {
                        "type": "number",
                        "description": "Top N percent to identify as hotspots. Default: 5.",
                        "default": 5
                    },
                    "min_hotspot_area_m2": {
                        "type": "number",
                        "description": "Minimum cluster area in m2. Default: 2500.",
                        "default": 2500
                    },
                    "max_hotspots": {
                        "type": "integer",
                        "description": "Max hotspot areas to return. Default: 10.",
                        "default": 10
                    },
                    "source_attribution": {
                        "type": "boolean",
                        "description": "Compute road contribution per hotspot. Default: true.",
                        "default": True
                    },
                    "scenario_label": {
                        "type": "string",
                        "description": "Scenario label used to resolve/store scenario-specific hotspot results."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "render_spatial_map",
            "description": "Render spatial data as an interactive map. Use this to visualize emission results, dispersion results, or any geo-referenced data on a map. Can use data from the previous calculation step.",
            "parameters": {
                "type": "object",
                "properties": {
                    "data_source": {
                        "type": "string",
                        "description": "Data to render. Use 'last_result' to visualize the previous calculation output.",
                        "default": "last_result"
                    },
                    "pollutant": {
                        "type": "string",
                        "description": "Which pollutant to visualize (e.g., CO2, NOx, PM2.5). If not specified, uses the first available."
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional map title"
                    },
                    "layer_type": {
                        "type": "string",
                        "enum": ["emission", "raster", "hotspot", "concentration", "points"],
                        "description": "Type of spatial layer. Auto-detected if not specified."
                    },
                    "scenario_label": {
                        "type": "string",
                        "description": "Optional scenario label to render a stored scenario-specific result instead of baseline."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_scenarios",
            "description": (
                "Compare baseline analysis results with one or more scenario variants. "
                "Shows metric deltas, percentage changes, and per-link differences using data already stored in the session."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "result_types": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["emission", "dispersion", "hotspot"]},
                        "description": "Which result types to compare"
                    },
                    "baseline": {
                        "type": "string",
                        "default": "baseline",
                        "description": "Label of baseline results"
                    },
                    "scenario": {
                        "type": "string",
                        "description": "Single scenario label to compare against baseline"
                    },
                    "scenarios": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Multiple scenario labels to compare against baseline"
                    },
                    "metrics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional metric names to focus on"
                    }
                },
                "required": ["result_types"]
            }
        }
    }
]
```

## 4. TOOL_GRAPH 完整内容

- `core/tool_dependencies.py` 当前总行数为 `361`；`TOOL_GRAPH` 定义于 `30-67`，其余辅助函数也在同文件中。

- 文件：`core/tool_dependencies.py`
- 对象：`core/tool_dependencies.py 全文件`
- 行号：`1-361`

```python
"""
EmissionAgent - Canonical Tool Dependency Graph

Defines lightweight prerequisite relationships between tools.
This layer is intentionally validation-focused; execution still relies on
router argument preparation plus the session context store.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Sequence, Set

from core.plan import PlanStatus, PlanStep, PlanStepStatus

if TYPE_CHECKING:
    from core.context_store import SessionContextStore


CANONICAL_RESULT_ALIASES: Dict[str, str] = {
    "emission_result": "emission",
    "dispersion_result": "dispersion",
    "hotspot_analysis": "hotspot",
    "concentration": "dispersion",
    "raster": "dispersion",
}


# Each tool declares what results it requires and what it provides.
# Canonical result tokens are used throughout this graph.
TOOL_GRAPH: Dict[str, Dict[str, List[str]]] = {
    "query_emission_factors": {
        "requires": [],
        "provides": ["emission_factors"],
    },
    "calculate_micro_emission": {
        "requires": [],
        "provides": ["emission"],
    },
    "calculate_macro_emission": {
        "requires": [],
        "provides": ["emission"],
    },
    "calculate_dispersion": {
        "requires": ["emission"],
        "provides": ["dispersion"],
    },
    "analyze_hotspots": {
        "requires": ["dispersion"],
        "provides": ["hotspot"],
    },
    "render_spatial_map": {
        "requires": [],
        "provides": ["visualization"],
    },
    "compare_scenarios": {
        "requires": [],
        "provides": ["scenario_comparison"],
    },
    "analyze_file": {
        "requires": [],
        "provides": ["file_analysis"],
    },
    "query_knowledge": {
        "requires": [],
        "provides": ["knowledge"],
    },
}


def normalize_result_token(token: Optional[str]) -> Optional[str]:
    """Map legacy result tokens and render-layer aliases to canonical tokens."""
    if token is None:
        return None
    text = str(token).strip().lower()
    if not text:
        return None
    return CANONICAL_RESULT_ALIASES.get(text, text)


def normalize_tokens(tokens: Optional[Iterable[str]]) -> List[str]:
    """Normalize tokens with stable ordering and de-duplication."""
    seen: Set[str] = set()
    normalized: List[str] = []
    for token in tokens or []:
        mapped = normalize_result_token(token)
        if not mapped or mapped in seen:
            continue
        seen.add(mapped)
        normalized.append(mapped)
    return normalized


def get_required_result_tokens(
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Return canonical prerequisite result tokens for a tool call."""
    if tool_name == "render_spatial_map":
        layer_type = normalize_result_token((arguments or {}).get("layer_type"))
        if layer_type in {"emission", "dispersion", "hotspot"}:
            return [layer_type]
        return []
    return normalize_tokens(TOOL_GRAPH.get(tool_name, {}).get("requires", []))


def get_missing_prerequisites(
    tool_name: str,
    available_results: Set[str],
    arguments: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Check whether a tool's prerequisites are met using canonical tokens."""
    available = set(normalize_tokens(available_results))
    requires = get_required_result_tokens(tool_name, arguments)
    return [req for req in requires if req not in available]


@dataclass
class DependencyValidationIssue:
    token: str
    issue_type: str
    message: str
    source: Optional[str] = None
    label: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token": self.token,
            "issue_type": self.issue_type,
            "message": self.message,
            "source": self.source,
            "label": self.label,
        }


@dataclass
class DependencyValidationResult:
    tool_name: str
    required_tokens: List[str]
    available_tokens: List[str]
    missing_tokens: List[str] = field(default_factory=list)
    stale_tokens: List[str] = field(default_factory=list)
    is_valid: bool = True
    message: str = ""
    issues: List[DependencyValidationIssue] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "required_tokens": list(self.required_tokens),
            "available_tokens": list(self.available_tokens),
            "missing_tokens": list(self.missing_tokens),
            "stale_tokens": list(self.stale_tokens),
            "is_valid": self.is_valid,
            "message": self.message,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def validate_tool_prerequisites(
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
    available_tokens: Optional[Iterable[str]] = None,
    context_store: Optional["SessionContextStore"] = None,
    include_stale: bool = False,
) -> DependencyValidationResult:
    """Deterministically validate runtime prerequisites for one tool call."""
    required_tokens = get_required_result_tokens(tool_name, arguments)
    normalized_available = set(normalize_tokens(available_tokens))
    resolved_available = set(normalized_available)
    missing_tokens: List[str] = []
    stale_tokens: List[str] = []
    issues: List[DependencyValidationIssue] = []
    label = None
    if isinstance(arguments, dict) and arguments.get("scenario_label"):
        label = str(arguments["scenario_label"]).strip() or None

    for token in required_tokens:
        if token in resolved_available:
            continue

        availability = None
        if context_store is not None and hasattr(context_store, "get_result_availability"):
            availability = context_store.get_result_availability(
                token,
                label=label,
                include_stale=include_stale,
            )

        if isinstance(availability, dict):
            if availability.get("available"):
                resolved_available.add(token)
                continue
            if availability.get("stale"):
                stale_tokens.append(token)
                issues.append(
                    DependencyValidationIssue(
                        token=token,
                        issue_type="stale",
                        message=(
                            f"Prerequisite '{token}' is only available as stale context and "
                            "include_stale=False."
                        ),
                        source=availability.get("source"),
                        label=availability.get("label"),
                    )
                )
                continue

        missing_tokens.append(token)
        issues.append(
            DependencyValidationIssue(
                token=token,
                issue_type="missing",
                message=f"Missing prerequisite result '{token}'.",
                source=availability.get("source") if isinstance(availability, dict) else None,
                label=availability.get("label") if isinstance(availability, dict) else label,
            )
        )

    is_valid = not missing_tokens and not stale_tokens
    if required_tokens and is_valid:
        message = f"All prerequisite result tokens available for {tool_name}: {required_tokens}."
    elif not required_tokens:
        message = f"No canonical prerequisite result tokens required for {tool_name}."
    else:
        message_parts: List[str] = []
        if missing_tokens:
            message_parts.append(f"missing={missing_tokens}")
        if stale_tokens:
            message_parts.append(f"stale={stale_tokens}")
        message = f"Cannot execute {tool_name}; prerequisite validation failed ({', '.join(message_parts)})."

    return DependencyValidationResult(
        tool_name=tool_name,
        required_tokens=required_tokens,
        available_tokens=sorted(resolved_available),
        missing_tokens=missing_tokens,
        stale_tokens=stale_tokens,
        is_valid=is_valid,
        message=message,
        issues=issues,
    )


def suggest_prerequisite_tool(missing_result: str) -> Optional[str]:
    """Suggest which tool can produce a missing canonical result token."""
    normalized = normalize_result_token(missing_result)
    if not normalized:
        return None
    for tool_name, info in TOOL_GRAPH.items():
        if normalized in normalize_tokens(info.get("provides", [])):
            return tool_name
    return None


def get_tool_provides(tool_name: str) -> List[str]:
    """Get the canonical result types a tool provides."""
    return normalize_tokens(TOOL_GRAPH.get(tool_name, {}).get("provides", []))


def _extract_step_field(step: Any, field_name: str, default: Any) -> Any:
    if isinstance(step, dict):
        return step.get(field_name, default)
    return getattr(step, field_name, default)


def validate_plan_steps(
    plan_steps: Sequence[PlanStep | Dict[str, Any]],
    available_tokens: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Deterministically validate plan-step dependencies in order."""
    if not plan_steps:
        return {
            "status": PlanStatus.INVALID,
            "initial_available_tokens": sorted(normalize_tokens(available_tokens)),
            "final_available_tokens": sorted(normalize_tokens(available_tokens)),
            "validation_notes": ["Plan has no executable analysis steps."],
            "step_results": [],
        }

    available = set(normalize_tokens(available_tokens))
    step_results: List[Dict[str, Any]] = []
    validation_notes: List[str] = []
    invalid_count = 0
    blocked_count = 0

    for index, step in enumerate(plan_steps):
        tool_name = str(_extract_step_field(step, "tool_name", "") or "").strip()
        step_id = str(_extract_step_field(step, "step_id", "") or f"s{index + 1}").strip()
        argument_hints = _extract_step_field(step, "argument_hints", {}) or {}
        declared_depends = normalize_tokens(_extract_step_field(step, "depends_on", []))
        declared_produces = normalize_tokens(_extract_step_field(step, "produces", []))
        inferred_requires = get_required_result_tokens(tool_name, argument_hints)
        canonical_provides = get_tool_provides(tool_name)

        status = PlanStepStatus.READY
        notes: List[str] = []

        if tool_name not in TOOL_GRAPH:
            status = PlanStepStatus.FAILED
            invalid_count += 1
            notes.append(f"Unknown tool '{tool_name}' in plan.")
        else:
            if declared_depends and declared_depends != inferred_requires:
                notes.append(
                    "Declared depends_on normalized to %s, tool semantics imply %s."
                    % (declared_depends, inferred_requires)
                )
            elif not declared_depends and inferred_requires:
                notes.append(f"depends_on inferred from tool semantics: {inferred_requires}.")

            if declared_produces and canonical_provides and declared_produces != canonical_provides:
                notes.append(
                    "Declared produces normalized to %s, canonical tool output is %s."
                    % (declared_produces, canonical_provides)
                )

            validation = validate_tool_prerequisites(
                tool_name,
                arguments=argument_hints,
                available_tokens=available,
                include_stale=False,
            )
            effective_requires = validation.required_tokens or declared_depends
            effective_produces = canonical_provides or declared_produces
            if validation.missing_tokens or validation.stale_tokens:
                status = PlanStepStatus.BLOCKED
                blocked_count += 1
                notes.append(validation.message)
            else:
                available.update(effective_produces)
        step_results.append(
            {
                "step_id": step_id,
                "tool_name": tool_name,
                "required_tokens": inferred_requires or declared_depends,
                "produced_tokens": canonical_provides or declared_produces,
                "status": status,
                "validation_notes": notes,
                "missing_tokens": validation.missing_tokens if tool_name in TOOL_GRAPH else [],
                "stale_tokens": validation.stale_tokens if tool_name in TOOL_GRAPH else [],
            }
        )

    if invalid_count:
        overall_status = PlanStatus.INVALID
        validation_notes.append("Plan contains unknown or invalid tools.")
    elif blocked_count:
        overall_status = PlanStatus.PARTIAL
        validation_notes.append("Plan is only partially executable with current available results.")
    else:
        overall_status = PlanStatus.VALID
        validation_notes.append("Plan dependency chain is executable in order.")

    return {
        "status": overall_status,
        "initial_available_tokens": sorted(normalize_tokens(available_tokens)),
        "final_available_tokens": sorted(available),
        "validation_notes": validation_notes,
        "step_results": step_results,
    }
```

## 5. ToolRegistry 完整内容

- `ToolRegistry` 定义于 `tools/registry.py:20-57`，`init_tools()` 定义于 `82-145`。

- 文件：`tools/registry.py`
- 对象：`tools/registry.py 全文件`
- 行号：`1-145`

```python
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

    try:
        from tools.dispersion import DispersionTool
        register_tool("calculate_dispersion", DispersionTool())
    except Exception as e:
        logger.warning(f"Failed to register calculate_dispersion: {e}")

    try:
        from tools.hotspot import HotspotTool
        register_tool("analyze_hotspots", HotspotTool())
    except Exception as e:
        logger.warning(f"Failed to register analyze_hotspots: {e}")

    try:
        from tools.spatial_renderer import SpatialRendererTool
        register_tool("render_spatial_map", SpatialRendererTool())
    except Exception as e:
        logger.warning(f"Failed to register render_spatial_map: {e}")

    try:
        from tools.scenario_compare import ScenarioCompareTool
        register_tool("compare_scenarios", ScenarioCompareTool())
    except Exception as e:
        logger.warning(f"Failed to register compare_scenarios: {e}")

    logger.info(f"Initialized {len(_registry.list_tools())} tools: {_registry.list_tools()}")
```

## 6. ACTION_CATALOG 完整内容

- 当前工具能力目录不是模块级 `_ACTION_CATALOG` 变量，而是 `get_action_catalog()` 函数返回的 `ActionCatalogEntry` 列表。

- `ActionCatalogEntry` 字段定义位于 `core/readiness.py:124-160`，字段名为：`action_id, display_name, description, tool_name, arguments, guidance_utterance, required_task_types, required_result_tokens, requires_geometry_support, requires_spatial_result_token, provided_conflicts, artifact_key, alternative_action_ids, guidance_enabled, pre_execution_enabled, category`。

- `build_readiness_assessment()` 定义于 `core/readiness.py:1346-1425`。

- 文件：`core/readiness.py`
- 对象：`ActionCatalogEntry`
- 行号：`124-160`

```python
class ActionCatalogEntry:
    action_id: str
    display_name: str
    description: str
    tool_name: Optional[str] = None
    arguments: Dict[str, Any] = field(default_factory=dict)
    guidance_utterance: Optional[str] = None
    required_task_types: List[str] = field(default_factory=list)
    required_result_tokens: List[str] = field(default_factory=list)
    requires_geometry_support: bool = False
    requires_spatial_result_token: Optional[str] = None
    provided_conflicts: List[str] = field(default_factory=list)
    artifact_key: Optional[str] = None
    alternative_action_ids: List[str] = field(default_factory=list)
    guidance_enabled: bool = True
    pre_execution_enabled: bool = True
    category: str = "analysis"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "display_name": self.display_name,
            "description": self.description,
            "tool_name": self.tool_name,
            "arguments": dict(self.arguments),
            "guidance_utterance": self.guidance_utterance,
            "required_task_types": list(self.required_task_types),
            "required_result_tokens": list(self.required_result_tokens),
            "requires_geometry_support": self.requires_geometry_support,
            "requires_spatial_result_token": self.requires_spatial_result_token,
            "provided_conflicts": list(self.provided_conflicts),
            "artifact_key": self.artifact_key,
            "alternative_action_ids": list(self.alternative_action_ids),
            "guidance_enabled": self.guidance_enabled,
            "pre_execution_enabled": self.pre_execution_enabled,
            "category": self.category,
        }
```

- 文件：`core/readiness.py`
- 对象：`ReadinessAssessment`
- 行号：`202-292`

```python
class ReadinessAssessment:
    available_actions: List[ActionAffordance] = field(default_factory=list)
    blocked_actions: List[ActionAffordance] = field(default_factory=list)
    repairable_actions: List[ActionAffordance] = field(default_factory=list)
    already_provided_actions: List[ActionAffordance] = field(default_factory=list)
    summary_notes: List[str] = field(default_factory=list)
    key_signals: Dict[str, Any] = field(default_factory=dict)
    catalog: List[ActionCatalogEntry] = field(default_factory=list)

    def get_action(self, action_id: Optional[str]) -> Optional[ActionAffordance]:
        if not action_id:
            return None
        for item in (
            self.available_actions
            + self.blocked_actions
            + self.repairable_actions
            + self.already_provided_actions
        ):
            if item.action_id == action_id:
                return item
        return None

    def counts(self) -> Dict[str, int]:
        return {
            "ready": len(self.available_actions),
            "blocked": len(self.blocked_actions),
            "repairable": len(self.repairable_actions),
            "already_provided": len(self.already_provided_actions),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available_actions": [item.to_dict() for item in self.available_actions],
            "blocked_actions": [item.to_dict() for item in self.blocked_actions],
            "repairable_actions": [item.to_dict() for item in self.repairable_actions],
            "already_provided_actions": [item.to_dict() for item in self.already_provided_actions],
            "summary_notes": list(self.summary_notes),
            "key_signals": dict(self.key_signals),
            "catalog": [item.to_dict() for item in self.catalog],
            "counts": self.counts(),
        }

    def to_capability_summary(self) -> Dict[str, Any]:
        def _serialize(items: List[ActionAffordance]) -> List[Dict[str, Any]]:
            return [
                {
                    "action_id": item.action_id,
                    "tool_name": item.tool_name,
                    "arguments": dict(item.arguments),
                    "label": item.display_name,
                    "description": item.description,
                    "utterance": item.guidance_utterance,
                    "reason": item.reason.message if item.reason else item.description,
                    "reason_codes": (
                        [item.reason.reason_code]
                        if item.reason is not None and item.reason.reason_code
                        else []
                    ),
                    "missing_requirements": (
                        list(item.reason.missing_requirements)
                        if item.reason is not None
                        else []
                    ),
                    "repair_hint": item.reason.repair_hint if item.reason else None,
                }
                for item in items
                if item.guidance_enabled
            ]

        already_provided = [
            item.provided_artifact.to_dict()
            for item in self.already_provided_actions
            if item.provided_artifact is not None
        ]
        unavailable = _serialize(self.repairable_actions) + _serialize(self.blocked_actions)

        guidance_hints: List[str] = []
        for note in self.summary_notes:
            text = str(note).strip()
            if text and text not in guidance_hints:
                guidance_hints.append(text)

        return {
            "available_next_actions": _serialize(self.available_actions),
            "repairable_actions": _serialize(self.repairable_actions),
            "unavailable_actions_with_reasons": unavailable,
            "already_provided": already_provided,
            "guidance_hints": guidance_hints,
            "metadata": dict(self.key_signals),
            "readiness": self.to_dict(),
        }
```

- 文件：`core/readiness.py`
- 对象：`get_action_catalog`
- 行号：`758-888`

```python
def get_action_catalog() -> List[ActionCatalogEntry]:
    return [
        ActionCatalogEntry(
            action_id="run_macro_emission",
            display_name="计算宏观排放",
            description="基于路段级交通字段生成宏观排放结果。",
            tool_name="calculate_macro_emission",
            guidance_utterance='“帮我计算路段排放” - 生成路段级排放结果',
            required_task_types=["macro_emission"],
            alternative_action_ids=["render_emission_map", "run_dispersion"],
            guidance_enabled=False,
            category="compute",
        ),
        ActionCatalogEntry(
            action_id="run_micro_emission",
            display_name="计算微观排放",
            description="基于轨迹级逐点字段生成微观排放结果。",
            tool_name="calculate_micro_emission",
            guidance_utterance='“帮我计算轨迹排放” - 生成逐点或逐段排放结果',
            required_task_types=["micro_emission"],
            alternative_action_ids=["render_emission_map"],
            guidance_enabled=False,
            category="compute",
        ),
        ActionCatalogEntry(
            action_id="run_dispersion",
            display_name="模拟污染物扩散浓度",
            description="基于当前排放结果继续进行扩散分析。",
            tool_name="calculate_dispersion",
            guidance_utterance='“帮我做扩散分析” - 了解污染物如何在大气中扩散',
            requires_geometry_support=True,
            alternative_action_ids=["render_emission_map", "compare_scenario"],
            category="analysis",
        ),
        ActionCatalogEntry(
            action_id="run_hotspot_analysis",
            display_name="识别污染热点",
            description="基于扩散结果识别高浓度区域和贡献路段。",
            tool_name="analyze_hotspots",
            guidance_utterance='“帮我识别污染热点” - 找出高浓度区域和主要贡献路段',
            alternative_action_ids=["render_dispersion_map", "compare_scenario"],
            category="analysis",
        ),
        ActionCatalogEntry(
            action_id="render_emission_map",
            display_name="可视化排放空间分布",
            description="在地图上查看各路段排放强度。",
            tool_name="render_spatial_map",
            arguments={"layer_type": "emission"},
            guidance_utterance='“帮我可视化排放分布” - 在地图上查看各路段排放强度',
            requires_geometry_support=True,
            provided_conflicts=["map:emission", "map:any"],
            alternative_action_ids=["run_dispersion", "compare_scenario"],
            category="render",
        ),
        ActionCatalogEntry(
            action_id="render_dispersion_map",
            display_name="可视化扩散浓度分布",
            description="在地图上查看浓度栅格或受体点分布。",
            tool_name="render_spatial_map",
            arguments={"layer_type": "dispersion"},
            guidance_utterance='“在地图上展示浓度分布” - 查看栅格浓度场',
            requires_spatial_result_token="dispersion",
            provided_conflicts=["map:dispersion", "map:any"],
            alternative_action_ids=["run_hotspot_analysis", "compare_scenario"],
            category="render",
        ),
        ActionCatalogEntry(
            action_id="render_hotspot_map",
            display_name="可视化热点区域",
            description="在地图上查看热点区域和贡献路段。",
            tool_name="render_spatial_map",
            arguments={"layer_type": "hotspot"},
            guidance_utterance='“在地图上展示热点” - 查看热点区域和贡献路段',
            requires_spatial_result_token="hotspot",
            provided_conflicts=["map:hotspot", "map:any"],
            alternative_action_ids=["compare_scenario"],
            category="render",
        ),
        ActionCatalogEntry(
            action_id="download_detailed_csv",
            display_name="下载详细结果文件",
            description="获取当前结果的详细表格导出文件。",
            artifact_key="download_detailed_csv",
            guidance_enabled=False,
            pre_execution_enabled=False,
            category="delivery",
        ),
        ActionCatalogEntry(
            action_id="download_topk_summary",
            display_name="下载摘要结果文件",
            description="获取当前摘要或 Top-K 结果导出文件。",
            artifact_key="download_topk_summary",
            guidance_utterance='“给我前5高排放路段摘要表” - 查看当前结果的 Top-K 排名摘要',
            required_task_types=["macro_emission"],
            required_result_tokens=["emission"],
            pre_execution_enabled=False,
            category="delivery",
        ),
        ActionCatalogEntry(
            action_id="render_rank_chart",
            display_name="查看结果图表",
            description="查看或导出当前结果图表。",
            artifact_key="render_rank_chart",
            guidance_utterance='“给我画个前5高排放路段条形图” - 用排序图查看当前结果的高值对象',
            required_task_types=["macro_emission"],
            required_result_tokens=["emission"],
            pre_execution_enabled=False,
            category="delivery",
        ),
        ActionCatalogEntry(
            action_id="deliver_quick_structured_summary",
            display_name="查看结构化摘要",
            description="用简洁结构化摘要概览当前结果。",
            artifact_key="quick_summary_text",
            guidance_utterance='“先给我一个摘要” - 用结构化摘要快速查看当前结果',
            required_task_types=["macro_emission"],
            required_result_tokens=["emission"],
            pre_execution_enabled=False,
            category="delivery",
        ),
        ActionCatalogEntry(
            action_id="compare_scenario",
            display_name="对比情景结果",
            description="比较不同情景下的排放、扩散或热点结果。",
            tool_name="compare_scenarios",
            guidance_utterance='“把速度降到 30 再比较一下” - 对比不同情景下的分析结果',
            alternative_action_ids=["run_dispersion", "render_emission_map"],
            category="analysis",
        ),
    ]
```

- 文件：`core/readiness.py`
- 对象：`build_readiness_assessment`
- 行号：`1346-1425`

```python
def build_readiness_assessment(
    file_context: Optional[Dict[str, Any]],
    context_store: Optional["SessionContextStore"],
    current_tool_results: Sequence[Dict[str, Any]],
    current_response_payloads: Optional[Dict[str, Any]] = None,
    parameter_locks: Optional[Dict[str, Any]] = None,
    input_completion_overrides: Optional[Dict[str, Any]] = None,
    already_provided_dedup_enabled: bool = True,
    artifact_memory_state: Optional[ArtifactMemoryState] = None,
) -> ReadinessAssessment:
    normalized_file_context = _coerce_file_context(file_context)
    catalog = get_action_catalog()
    result_payloads = _collect_result_payloads(current_tool_results, context_store)
    available_tokens = set(_collect_available_tokens(current_tool_results, context_store))
    if already_provided_dedup_enabled:
        already_provided, provided_ids = _collect_already_provided_artifacts(
            current_response_payloads,
            current_tool_results,
            artifact_memory_state=artifact_memory_state,
        )
    else:
        already_provided, provided_ids = [], set()
    has_geometry_support, geometry_source = _determine_geometry_support(
        normalized_file_context,
        result_payloads,
    )

    assessment = ReadinessAssessment(
        summary_notes=[],
        key_signals={
            "task_type": normalized_file_context.get("task_type"),
            "has_geometry_support": has_geometry_support,
            "geometry_support_source": geometry_source,
            "available_result_tokens": sorted(available_tokens),
            "provided_artifact_ids": sorted(provided_ids),
            "missing_field_status": (
                (normalized_file_context.get("missing_field_diagnostics") or {}).get("status")
                if isinstance(normalized_file_context.get("missing_field_diagnostics"), dict)
                else None
            ),
            "selected_primary_table": normalized_file_context.get("selected_primary_table"),
            "dataset_role_count": len(normalized_file_context.get("dataset_roles") or []),
            "parameter_locks": sorted((parameter_locks or {}).keys()),
            "input_completion_overrides": sorted((input_completion_overrides or {}).keys()),
        },
        catalog=catalog,
    )

    for entry in catalog:
        affordance = assess_action_readiness(
            entry,
            file_context=normalized_file_context,
            context_store=context_store,
            current_tool_results=current_tool_results,
            current_response_payloads=current_response_payloads,
            parameter_locks=parameter_locks,
            input_completion_overrides=input_completion_overrides,
            already_provided_dedup_enabled=already_provided_dedup_enabled,
            artifact_memory_state=artifact_memory_state,
        )
        if affordance.status == ReadinessStatus.READY:
            assessment.available_actions.append(affordance)
        elif affordance.status == ReadinessStatus.BLOCKED:
            assessment.blocked_actions.append(affordance)
        elif affordance.status == ReadinessStatus.REPAIRABLE:
            assessment.repairable_actions.append(affordance)
        else:
            assessment.already_provided_actions.append(affordance)

    if any(
        item.reason is not None and item.reason.reason_code == "missing_geometry"
        for item in assessment.repairable_actions + assessment.blocked_actions
    ):
        assessment.summary_notes.append(_REASON_HINTS["missing_geometry"])

    diagnostics = normalized_file_context.get("missing_field_diagnostics") or {}
    if isinstance(diagnostics, dict) and diagnostics.get("status") in {"partial", "insufficient"}:
        assessment.summary_notes.append("当前文件关键字段仍不完整，部分分析动作只能视为 repairable，不能直接执行。")

    return assessment
```

## 7. 工作流模板

- `core/workflow_templates.py` 当前总行数为 `623`。

- 模板结构由 `WorkflowTemplateStep`（`31-62`）、`WorkflowTemplate`（`66-104`）、`TemplateRecommendation`（`108-139`）、`TemplateSelectionResult`（`143-185`）定义。

- 模板集合由 `_build_template_catalog()`（`188-328`）构造，当前模板 ID 为：`macro_emission_baseline`、`macro_spatial_chain`、`micro_emission_baseline`、`macro_render_focus`、`micro_render_focus`。

- 模板选择逻辑位于 `recommend_workflow_templates()`（`508-543`）和 `select_primary_template()`（`546-590`）；router 入口为 `UnifiedRouter._recommend_workflow_template_prior()`（`core/router.py:3758-3774`），实际注入与记录在 `core/router.py:8579-8645`、`3776-3850`。

- 文件：`core/workflow_templates.py`
- 对象：`core/workflow_templates.py 全文件`
- 行号：`1-623`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _coerce_string_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    result: List[str] = []
    for value in values:
        text = str(value).strip() if value is not None else ""
        if text:
            result.append(text)
    return result


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _message_contains_any(message: str, phrases: tuple[str, ...]) -> bool:
    lowered = message.lower()
    return any(phrase in lowered for phrase in phrases)


@dataclass
class WorkflowTemplateStep:
    step_id: str
    tool_name: str
    purpose: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    produces: List[str] = field(default_factory=list)
    argument_hints: Dict[str, Any] = field(default_factory=dict)
    optional: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "purpose": self.purpose,
            "depends_on": list(self.depends_on),
            "produces": list(self.produces),
            "argument_hints": dict(self.argument_hints),
            "optional": self.optional,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "WorkflowTemplateStep":
        payload = data if isinstance(data, dict) else {}
        return cls(
            step_id=str(payload.get("step_id") or "").strip() or "t1",
            tool_name=str(payload.get("tool_name") or "").strip(),
            purpose=str(payload.get("purpose")).strip() if payload.get("purpose") is not None else None,
            depends_on=_coerce_string_list(payload.get("depends_on")),
            produces=_coerce_string_list(payload.get("produces")),
            argument_hints=dict(payload.get("argument_hints") or {}),
            optional=bool(payload.get("optional", False)),
        )


@dataclass
class WorkflowTemplate:
    template_id: str
    name: str
    description: str
    supported_task_types: List[str] = field(default_factory=list)
    required_result_types: List[str] = field(default_factory=list)
    required_file_signals: List[str] = field(default_factory=list)
    step_skeleton: List[WorkflowTemplateStep] = field(default_factory=list)
    applicability_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "supported_task_types": list(self.supported_task_types),
            "required_result_types": list(self.required_result_types),
            "required_file_signals": list(self.required_file_signals),
            "step_skeleton": [step.to_dict() for step in self.step_skeleton],
            "applicability_notes": list(self.applicability_notes),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "WorkflowTemplate":
        payload = data if isinstance(data, dict) else {}
        return cls(
            template_id=str(payload.get("template_id") or "").strip(),
            name=str(payload.get("name") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            supported_task_types=_coerce_string_list(payload.get("supported_task_types")),
            required_result_types=_coerce_string_list(payload.get("required_result_types")),
            required_file_signals=_coerce_string_list(payload.get("required_file_signals")),
            step_skeleton=[
                WorkflowTemplateStep.from_dict(item)
                for item in payload.get("step_skeleton", [])
                if isinstance(item, dict)
            ],
            applicability_notes=_coerce_string_list(payload.get("applicability_notes")),
        )


@dataclass
class TemplateRecommendation:
    template_id: str
    confidence: float
    reason: str
    matched_signals: List[str] = field(default_factory=list)
    unmet_requirements: List[str] = field(default_factory=list)
    is_applicable: bool = False
    priority_rank: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_id": self.template_id,
            "confidence": round(float(self.confidence), 3),
            "reason": self.reason,
            "matched_signals": list(self.matched_signals),
            "unmet_requirements": list(self.unmet_requirements),
            "is_applicable": self.is_applicable,
            "priority_rank": self.priority_rank,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "TemplateRecommendation":
        payload = data if isinstance(data, dict) else {}
        return cls(
            template_id=str(payload.get("template_id") or "").strip(),
            confidence=_coerce_float(payload.get("confidence"), 0.0),
            reason=str(payload.get("reason") or "").strip(),
            matched_signals=_coerce_string_list(payload.get("matched_signals")),
            unmet_requirements=_coerce_string_list(payload.get("unmet_requirements")),
            is_applicable=bool(payload.get("is_applicable", False)),
            priority_rank=int(payload.get("priority_rank", 0) or 0),
        )


@dataclass
class TemplateSelectionResult:
    recommended_template_id: Optional[str] = None
    recommendations: List[TemplateRecommendation] = field(default_factory=list)
    selection_reason: Optional[str] = None
    template_prior_used: bool = False
    selected_template: Optional[WorkflowTemplate] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommended_template_id": self.recommended_template_id,
            "recommendations": [item.to_dict() for item in self.recommendations],
            "selection_reason": self.selection_reason,
            "template_prior_used": self.template_prior_used,
            "selected_template": self.selected_template.to_dict() if self.selected_template else None,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "TemplateSelectionResult":
        payload = data if isinstance(data, dict) else {}
        selected_payload = payload.get("selected_template")
        return cls(
            recommended_template_id=(
                str(payload.get("recommended_template_id")).strip()
                if payload.get("recommended_template_id") is not None
                else None
            ),
            recommendations=[
                TemplateRecommendation.from_dict(item)
                for item in payload.get("recommendations", [])
                if isinstance(item, dict)
            ],
            selection_reason=(
                str(payload.get("selection_reason")).strip()
                if payload.get("selection_reason") is not None
                else None
            ),
            template_prior_used=bool(payload.get("template_prior_used", False)),
            selected_template=(
                WorkflowTemplate.from_dict(selected_payload)
                if isinstance(selected_payload, dict)
                else None
            ),
        )


def _build_template_catalog() -> Dict[str, WorkflowTemplate]:
    templates = [
        WorkflowTemplate(
            template_id="macro_emission_baseline",
            name="Macro Emission Baseline",
            description="Baseline macro-scale emission analysis from grounded road-link data.",
            supported_task_types=["macro_emission"],
            required_file_signals=["macro_task"],
            step_skeleton=[
                WorkflowTemplateStep(
                    step_id="t1",
                    tool_name="calculate_macro_emission",
                    purpose="Compute link-level macro emissions from the grounded road-link dataset.",
                    produces=["emission"],
                ),
                WorkflowTemplateStep(
                    step_id="t2",
                    tool_name="render_spatial_map",
                    purpose="Optionally render the computed emission layer on a map.",
                    depends_on=["emission"],
                    argument_hints={"layer_type": "emission"},
                    optional=True,
                ),
            ],
            applicability_notes=[
                "Use when the file grounding is macro-oriented and required traffic fields are mostly available.",
                "This template stays close to the minimal compute-first workflow.",
            ],
        ),
        WorkflowTemplate(
            template_id="macro_spatial_chain",
            name="Macro Spatial Chain",
            description="Macro emission followed by dispersion, hotspot analysis, and spatial rendering.",
            supported_task_types=["macro_emission"],
            required_file_signals=["macro_task", "spatial_ready"],
            required_result_types=["emission", "dispersion", "hotspot"],
            step_skeleton=[
                WorkflowTemplateStep(
                    step_id="t1",
                    tool_name="calculate_macro_emission",
                    purpose="Compute link-level macro emissions.",
                    produces=["emission"],
                ),
                WorkflowTemplateStep(
                    step_id="t2",
                    tool_name="calculate_dispersion",
                    purpose="Propagate emissions into a dispersion result.",
                    depends_on=["emission"],
                    produces=["dispersion"],
                ),
                WorkflowTemplateStep(
                    step_id="t3",
                    tool_name="analyze_hotspots",
                    purpose="Identify concentration hotspots from the dispersion output.",
                    depends_on=["dispersion"],
                    produces=["hotspot"],
                ),
                WorkflowTemplateStep(
                    step_id="t4",
                    tool_name="render_spatial_map",
                    purpose="Render the hotspot layer on a spatial map.",
                    depends_on=["hotspot"],
                    argument_hints={"layer_type": "hotspot"},
                ),
            ],
            applicability_notes=[
                "Use when file grounding indicates a spatially actionable macro dataset.",
                "This template is only a prior; the planner may shorten it if the user asked for a narrower workflow.",
            ],
        ),
        WorkflowTemplate(
            template_id="micro_emission_baseline",
            name="Micro Emission Baseline",
            description="Micro-scale second-by-second emission analysis from grounded trajectory data.",
            supported_task_types=["micro_emission"],
            required_file_signals=["micro_task"],
            step_skeleton=[
                WorkflowTemplateStep(
                    step_id="t1",
                    tool_name="calculate_micro_emission",
                    purpose="Compute second-by-second micro emissions from the grounded trajectory dataset.",
                    produces=["emission"],
                )
            ],
            applicability_notes=[
                "Use when the file grounding clearly points to micro-scale trajectory analysis.",
                "This template stays compute-only unless the user explicitly asks for map rendering.",
            ],
        ),
        WorkflowTemplate(
            template_id="macro_render_focus",
            name="Macro Render Focus",
            description="Macro emission computation followed by immediate emission-layer rendering.",
            supported_task_types=["macro_emission"],
            required_file_signals=["macro_task", "spatial_ready", "render_intent"],
            step_skeleton=[
                WorkflowTemplateStep(
                    step_id="t1",
                    tool_name="calculate_macro_emission",
                    purpose="Compute macro emissions for the grounded road-link file.",
                    produces=["emission"],
                ),
                WorkflowTemplateStep(
                    step_id="t2",
                    tool_name="render_spatial_map",
                    purpose="Render the emission result on a spatial map.",
                    depends_on=["emission"],
                    argument_hints={"layer_type": "emission"},
                ),
            ],
            applicability_notes=[
                "Use when the user emphasizes map rendering rather than dispersion or hotspot derivation.",
            ],
        ),
        WorkflowTemplate(
            template_id="micro_render_focus",
            name="Micro Render Focus",
            description="Micro emission computation followed by bounded emission-layer rendering.",
            supported_task_types=["micro_emission"],
            required_file_signals=["micro_task", "spatial_ready", "render_intent"],
            step_skeleton=[
                WorkflowTemplateStep(
                    step_id="t1",
                    tool_name="calculate_micro_emission",
                    purpose="Compute micro emissions from trajectory data.",
                    produces=["emission"],
                ),
                WorkflowTemplateStep(
                    step_id="t2",
                    tool_name="render_spatial_map",
                    purpose="Render the micro emission result as an emission layer when spatial context is available.",
                    depends_on=["emission"],
                    argument_hints={"layer_type": "emission"},
                ),
            ],
            applicability_notes=[
                "Use only when the grounded micro dataset exposes actionable spatial context and the user explicitly asks for a map.",
            ],
        ),
    ]
    return {template.template_id: template for template in templates}


_TEMPLATE_CATALOG = _build_template_catalog()


def list_workflow_templates() -> List[WorkflowTemplate]:
    return [WorkflowTemplate.from_dict(item.to_dict()) for item in _TEMPLATE_CATALOG.values()]


def get_workflow_template(template_id: str) -> Optional[WorkflowTemplate]:
    template = _TEMPLATE_CATALOG.get(str(template_id or "").strip())
    return WorkflowTemplate.from_dict(template.to_dict()) if template else None


def _normalize_readiness_status(file_analysis: Dict[str, Any], task_type: str) -> str:
    diagnostics = file_analysis.get("missing_field_diagnostics") or {}
    status = str(diagnostics.get("status") or "").strip().lower()
    if status:
        return status
    if task_type == "macro_emission":
        return "complete" if file_analysis.get("macro_has_required") else "insufficient"
    if task_type == "micro_emission":
        return "complete" if file_analysis.get("micro_has_required") else "insufficient"
    return "unknown_task"


def _extract_grounding_signals(file_analysis: Dict[str, Any], user_message: str) -> Dict[str, Any]:
    task_type = str(file_analysis.get("task_type") or "unknown").strip()
    confidence = _coerce_float(file_analysis.get("confidence"), 0.0)
    readiness_status = _normalize_readiness_status(file_analysis, task_type)
    spatial_metadata = file_analysis.get("spatial_metadata") or {}
    dataset_roles = [
        dict(item)
        for item in (file_analysis.get("dataset_roles") or [])
        if isinstance(item, dict)
    ]
    selected_role = next((item for item in dataset_roles if item.get("selected")), None)
    geometry_types = [str(item) for item in (spatial_metadata.get("geometry_types") or []) if item]
    selected_format = str((selected_role or {}).get("format") or file_analysis.get("format") or "").lower()

    render_intent = _message_contains_any(
        user_message,
        ("地图", "渲染", "可视化", "render", "map", "visual", "visualize"),
    )
    dispersion_intent = _message_contains_any(
        user_message,
        ("扩散", "dispersion", "浓度", "concentration", "raster"),
    )
    hotspot_intent = _message_contains_any(
        user_message,
        ("热点", "hotspot"),
    )

    spatial_ready = bool(spatial_metadata) or selected_format in {"shapefile", "zip_shapefile"}
    if not spatial_ready:
        spatial_ready = any(role.get("role") == "spatial_context" for role in dataset_roles)

    has_line_geometry = any("line" in item.lower() for item in geometry_types)
    role_summary = file_analysis.get("dataset_role_summary") or {}

    return {
        "task_type": task_type,
        "grounding_confidence": confidence,
        "readiness_status": readiness_status,
        "spatial_ready": spatial_ready,
        "has_line_geometry": has_line_geometry,
        "render_intent": render_intent,
        "dispersion_intent": dispersion_intent,
        "hotspot_intent": hotspot_intent,
        "dataset_roles_present": bool(dataset_roles),
        "ambiguous_dataset_roles": bool(role_summary.get("ambiguous")),
        "selected_primary_table": str(file_analysis.get("selected_primary_table") or "").strip() or None,
    }


def _evaluate_template(
    template: WorkflowTemplate,
    signals: Dict[str, Any],
) -> Optional[TemplateRecommendation]:
    task_type = signals["task_type"]
    if task_type not in template.supported_task_types:
        return None

    matched: List[str] = []
    unmet: List[str] = []
    score = 0.0
    applicable = True

    if task_type == "macro_emission":
        matched.append("macro_task")
        score += 0.42
    elif task_type == "micro_emission":
        matched.append("micro_task")
        score += 0.42

    if signals["grounding_confidence"] >= 0.75:
        matched.append("grounding_confident")
        score += 0.1
    elif signals["grounding_confidence"] < 0.5:
        unmet.append("grounding_confidence_low")
        score -= 0.08

    readiness_status = signals["readiness_status"]
    if readiness_status == "complete":
        matched.append("file_readiness_complete")
        score += 0.2
    elif readiness_status == "partial":
        matched.append("file_readiness_partial")
        unmet.append("missing_required_fields_partial")
        score += 0.08
    elif readiness_status == "insufficient":
        unmet.append("file_readiness_insufficient")
        score -= 0.22
        applicable = False
    else:
        unmet.append("file_readiness_unknown")
        score -= 0.12
        applicable = False

    if "spatial_ready" in template.required_file_signals:
        if signals["spatial_ready"]:
            matched.append("spatial_ready")
            score += 0.16
            if signals["has_line_geometry"]:
                matched.append("line_geometry")
                score += 0.05
        else:
            unmet.append("spatial_ready_missing")
            score -= 0.18
            applicable = False

    if "render_intent" in template.required_file_signals and not signals["render_intent"]:
        return None
    if "render_intent" in template.required_file_signals and signals["render_intent"]:
        matched.append("render_intent")
        score += 0.12

    if template.template_id == "macro_spatial_chain":
        if signals["dispersion_intent"]:
            matched.append("dispersion_intent")
            score += 0.17
        if signals["hotspot_intent"]:
            matched.append("hotspot_intent")
            score += 0.17
        if not signals["dispersion_intent"] and not signals["hotspot_intent"]:
            score -= 0.22
    if template.template_id.endswith("render_focus") and signals["hotspot_intent"]:
        score -= 0.12
        unmet.append("hotspot_intent_prefers_spatial_chain")

    if template.template_id == "macro_emission_baseline" and signals["render_intent"]:
        score -= 0.02
    if template.template_id == "micro_emission_baseline" and signals["render_intent"] and signals["spatial_ready"]:
        score -= 0.01

    confidence = max(0.05, min(0.95, round(score, 3)))
    reason_parts = [
        f"task_type={task_type}",
        f"readiness={readiness_status}",
    ]
    if signals["spatial_ready"]:
        reason_parts.append("spatial context available")
    if signals["render_intent"]:
        reason_parts.append("render intent detected")
    if signals["dispersion_intent"] or signals["hotspot_intent"]:
        reason_parts.append("downstream spatial-analysis intent detected")
    if unmet:
        reason_parts.append(f"unmet={', '.join(unmet)}")

    return TemplateRecommendation(
        template_id=template.template_id,
        confidence=confidence,
        reason="; ".join(reason_parts),
        matched_signals=matched,
        unmet_requirements=unmet,
        is_applicable=applicable,
    )


def recommend_workflow_templates(
    file_analysis: Optional[Dict[str, Any]],
    *,
    user_message: Optional[str] = None,
    max_recommendations: int = 3,
    min_confidence: float = 0.3,
) -> List[TemplateRecommendation]:
    if not isinstance(file_analysis, dict):
        return []

    signals = _extract_grounding_signals(file_analysis, user_message or "")
    if signals["task_type"] not in {"macro_emission", "micro_emission"}:
        return []
    if signals["grounding_confidence"] < max(0.0, min_confidence - 0.1):
        return []

    recommendations: List[TemplateRecommendation] = []
    for template in _TEMPLATE_CATALOG.values():
        recommendation = _evaluate_template(template, signals)
        if recommendation is None:
            continue
        if recommendation.confidence < max(0.05, min_confidence - 0.2):
            continue
        recommendations.append(recommendation)

    recommendations.sort(
        key=lambda item: (
            not item.is_applicable,
            -item.confidence,
            item.template_id,
        )
    )
    trimmed = recommendations[: max(1, int(max_recommendations or 1))]
    for index, recommendation in enumerate(trimmed, start=1):
        recommendation.priority_rank = index
    return trimmed


def select_primary_template(
    recommendations: List[TemplateRecommendation],
    *,
    min_confidence: float = 0.55,
) -> TemplateSelectionResult:
    if not recommendations:
        return TemplateSelectionResult(
            recommended_template_id=None,
            recommendations=[],
            selection_reason="No workflow template recommendation was applicable.",
            template_prior_used=False,
            selected_template=None,
        )

    selected_recommendation = next(
        (
            item
            for item in recommendations
            if item.is_applicable and item.confidence >= min_confidence
        ),
        None,
    )
    if selected_recommendation is None:
        top = recommendations[0]
        return TemplateSelectionResult(
            recommended_template_id=None,
            recommendations=recommendations,
            selection_reason=(
                f"No workflow template prior was selected because the best recommendation "
                f"({top.template_id}) stayed below the planner-use threshold or was not applicable."
            ),
            template_prior_used=False,
            selected_template=None,
        )

    selected_template = get_workflow_template(selected_recommendation.template_id)
    return TemplateSelectionResult(
        recommended_template_id=selected_recommendation.template_id,
        recommendations=recommendations,
        selection_reason=(
            f"Selected {selected_recommendation.template_id} as the highest-ranked applicable template prior."
        ),
        template_prior_used=selected_template is not None,
        selected_template=selected_template,
    )


def summarize_template_prior(
    template: WorkflowTemplate,
    recommendation: TemplateRecommendation,
) -> str:
    lines = [
        "[Workflow template prior]",
        f"Template: {template.template_id} ({template.name})",
        f"Confidence: {recommendation.confidence:.2f}",
        f"Reason: {recommendation.reason}",
    ]
    if recommendation.matched_signals:
        lines.append(f"Matched signals: {', '.join(recommendation.matched_signals)}")
    if recommendation.unmet_requirements:
        lines.append(f"Unmet requirements: {', '.join(recommendation.unmet_requirements)}")
    lines.append("Step skeleton:")
    for step in template.step_skeleton:
        step_line = f"- {step.step_id}: {step.tool_name}"
        if step.depends_on:
            step_line += f" | depends_on={', '.join(step.depends_on)}"
        if step.produces:
            step_line += f" | produces={', '.join(step.produces)}"
        if step.argument_hints:
            step_line += f" | argument_hints={step.argument_hints}"
        if step.optional:
            step_line += " | optional=true"
        lines.append(step_line)
    lines.append(
        "Use this template as a bounded prior only. The planner should stay close to it when grounded signals agree, "
        "but may shorten or adapt the workflow when the current request is narrower."
    )
    return "\n".join(lines)
```

- 文件：`core/router.py`
- 对象：`UnifiedRouter._recommend_workflow_template_prior`
- 行号：`3758-3774`

```python
    def _recommend_workflow_template_prior(self, state: TaskState) -> TemplateSelectionResult:
        file_signals = self._get_workflow_template_signals(state)
        recommendations = recommend_workflow_templates(
            file_signals,
            user_message=state.user_message or "",
            max_recommendations=getattr(self.runtime_config, "workflow_template_max_recommendations", 3),
            min_confidence=max(
                0.25,
                float(getattr(self.runtime_config, "workflow_template_min_confidence", 0.55)) - 0.1,
            ),
        )
        selection = select_primary_template(
            recommendations,
            min_confidence=float(getattr(self.runtime_config, "workflow_template_min_confidence", 0.55)),
        )
        state.set_workflow_template_selection(selection)
        return selection
```

- 文件：`core/router.py`
- 对象：`UnifiedRouter._state_handle_input 中工作流模板选择片段`
- 行号：`8579-8645`

```python
        if getattr(self.runtime_config, "enable_workflow_templates", False) and (
            continuation_decision.should_continue or state.file_context.grounded
        ):
            if continuation_decision.should_continue:
                self._record_workflow_template_selection(
                    state,
                    TemplateSelectionResult(
                        recommended_template_id=None,
                        recommendations=[],
                        selection_reason="Residual continuation remained authoritative, so fresh template recommendation was skipped.",
                        template_prior_used=False,
                    ),
                    trace_obj=trace_obj,
                )
            elif forced_continuation_decision is not None and forced_continuation_decision.signal == "parameter_confirmation_resume":
                self._record_workflow_template_selection(
                    state,
                    TemplateSelectionResult(
                        recommended_template_id=None,
                        recommendations=[],
                        selection_reason="Parameter confirmation resumed the current task, so fresh template recommendation was skipped.",
                        template_prior_used=False,
                    ),
                    trace_obj=trace_obj,
                )
            elif (
                forced_continuation_decision is not None
                and forced_continuation_decision.signal in {"geometry_recovery_resume", "geometry_recovery_waiting"}
            ):
                self._record_workflow_template_selection(
                    state,
                    TemplateSelectionResult(
                        recommended_template_id=None,
                        recommendations=[],
                        selection_reason="Geometry recovery kept the residual workflow authoritative, so fresh template recommendation was skipped.",
                        template_prior_used=False,
                    ),
                    trace_obj=trace_obj,
                )
            else:
                file_signals = self._get_workflow_template_signals(state)
                if not isinstance(file_signals, dict) or not state.file_context.grounded:
                    self._record_workflow_template_selection(
                        state,
                        TemplateSelectionResult(
                            recommended_template_id=None,
                            recommendations=[],
                            selection_reason="No grounded file context was available for workflow template recommendation.",
                            template_prior_used=False,
                        ),
                        trace_obj=trace_obj,
                    )
                elif state.file_context.task_type not in {"macro_emission", "micro_emission"}:
                    self._record_workflow_template_selection(
                        state,
                        TemplateSelectionResult(
                            recommended_template_id=None,
                            recommendations=[],
                            selection_reason=(
                                f"Workflow templates were skipped because task_type={state.file_context.task_type or 'unknown'} "
                                "did not support a bounded domain prior."
                            ),
                            template_prior_used=False,
                        ),
                        trace_obj=trace_obj,
                    )
                else:
```

- 文件：`core/router.py`
- 对象：`UnifiedRouter._record_workflow_template_selection`
- 行号：`3776-3850`

```python
    def _record_workflow_template_selection(
        self,
        state: TaskState,
        selection: TemplateSelectionResult,
        *,
        reason_override: Optional[str] = None,
        trace_obj: Optional[Trace] = None,
    ) -> None:
        state.set_workflow_template_selection(selection)
        if trace_obj is None:
            return

        if selection.recommendations:
            trace_obj.record(
                step_type=TraceStepType.WORKFLOW_TEMPLATE_RECOMMENDED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action=selection.recommended_template_id,
                input_summary={
                    "task_type": state.file_context.task_type,
                    "confidence": state.file_context.confidence,
                },
                output_summary={
                    "recommendations": [item.to_dict() for item in selection.recommendations],
                },
                reasoning=(
                    reason_override
                    or "Rule-based workflow template recommendations were derived from the grounded file signals."
                ),
            )

        if selection.template_prior_used and selection.selected_template is not None:
            trace_obj.record(
                step_type=TraceStepType.WORKFLOW_TEMPLATE_SELECTED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action=selection.selected_template.template_id,
                output_summary={
                    "selected_template": selection.selected_template.to_dict(),
                    "selection_reason": selection.selection_reason,
                },
                reasoning=selection.selection_reason or "Selected the highest-ranked applicable template prior.",
            )
            top_recommendation = next(
                (
                    item
                    for item in selection.recommendations
                    if item.template_id == selection.selected_template.template_id
                ),
                None,
            )
            if top_recommendation is not None:
                guidance_text = self._format_workflow_template_injection(
                    selection.selected_template,
                    top_recommendation,
                )
                trace_obj.record(
                    step_type=TraceStepType.WORKFLOW_TEMPLATE_INJECTED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action=selection.selected_template.template_id,
                    output_summary={"guidance_preview": guidance_text[:400]},
                    reasoning=(
                        f"Prepared workflow template prior {selection.selected_template.template_id} "
                        "for the lightweight planning payload."
                    ),
                )
            return

        trace_obj.record(
            step_type=TraceStepType.WORKFLOW_TEMPLATE_SKIPPED,
            stage_before=TaskStage.INPUT_RECEIVED.value,
            reasoning=reason_override or selection.selection_reason or "Workflow template prior was not selected.",
            output_summary={
                "recommendation_count": len(selection.recommendations),
                "template_prior_used": selection.template_prior_used,
            },
        )
```

## 8. ExecutionPlan 相关

- `core/plan.py` 中 `PlanStepStatus` 定义于 `15-22`，`PlanStep` 定义于 `48-99`，`ExecutionPlan` 定义于 `103-231`。

- `core/plan_repair.py` 中 `RepairActionType` 定义于 `26-33`，`PlanRepairDecision` 定义于 `195-250`。

- 当前 `RepairActionType` 枚举实际成员数为 `7`，成员为 `KEEP_REMAINING`、`DROP_BLOCKED_STEP`、`REORDER_REMAINING_STEPS`、`REPLACE_STEP`、`TRUNCATE_AFTER_CURRENT`、`APPEND_RECOVERY_STEP`、`NO_REPAIR`（`core/plan_repair.py:26-33`）。

- 文件：`core/plan.py`
- 对象：`core/plan.py 全文件`
- 行号：`1-231`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class PlanStatus(str, Enum):
    DRAFT = "draft"
    VALID = "valid"
    PARTIAL = "partial"
    INVALID = "invalid"


class PlanStepStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


def _coerce_string_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    result: List[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            result.append(text)
    return result


def _coerce_status(value: Any, enum_cls: type[Enum], default: Enum) -> Enum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except Exception:
        return default


@dataclass
class PlanStep:
    step_id: str
    tool_name: str
    purpose: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    produces: List[str] = field(default_factory=list)
    argument_hints: Dict[str, Any] = field(default_factory=dict)
    status: PlanStepStatus = PlanStepStatus.PENDING
    validation_notes: List[str] = field(default_factory=list)
    reconciliation_notes: List[str] = field(default_factory=list)
    blocked_reason: Optional[str] = None
    repair_action: Optional[str] = None
    repair_source_step_id: Optional[str] = None
    repair_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "purpose": self.purpose,
            "depends_on": list(self.depends_on),
            "produces": list(self.produces),
            "argument_hints": dict(self.argument_hints),
            "status": self.status.value,
            "validation_notes": list(self.validation_notes),
            "reconciliation_notes": list(self.reconciliation_notes),
            "blocked_reason": self.blocked_reason,
            "repair_action": self.repair_action,
            "repair_source_step_id": self.repair_source_step_id,
            "repair_notes": list(self.repair_notes),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "PlanStep":
        payload = data if isinstance(data, dict) else {}
        return cls(
            step_id=str(payload.get("step_id") or "").strip() or "step",
            tool_name=str(payload.get("tool_name") or "").strip(),
            purpose=str(payload.get("purpose")).strip() if payload.get("purpose") is not None else None,
            depends_on=_coerce_string_list(payload.get("depends_on")),
            produces=_coerce_string_list(payload.get("produces")),
            argument_hints=dict(payload.get("argument_hints") or {}),
            status=_coerce_status(payload.get("status"), PlanStepStatus, PlanStepStatus.PENDING),
            validation_notes=_coerce_string_list(payload.get("validation_notes")),
            reconciliation_notes=_coerce_string_list(payload.get("reconciliation_notes")),
            blocked_reason=str(payload.get("blocked_reason")).strip() if payload.get("blocked_reason") is not None else None,
            repair_action=str(payload.get("repair_action")).strip() if payload.get("repair_action") is not None else None,
            repair_source_step_id=str(payload.get("repair_source_step_id")).strip()
            if payload.get("repair_source_step_id") is not None
            else None,
            repair_notes=_coerce_string_list(payload.get("repair_notes")),
        )


@dataclass
class ExecutionPlan:
    goal: str
    steps: List[PlanStep] = field(default_factory=list)
    mode: str = "tool_workflow"
    planner_notes: Optional[str] = None
    status: PlanStatus = PlanStatus.DRAFT
    validation_notes: List[str] = field(default_factory=list)
    reconciliation_notes: List[str] = field(default_factory=list)
    repair_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        next_step = self.get_next_pending_step()
        return {
            "goal": self.goal,
            "mode": self.mode,
            "planner_notes": self.planner_notes,
            "status": self.status.value,
            "validation_notes": list(self.validation_notes),
            "reconciliation_notes": list(self.reconciliation_notes),
            "repair_notes": list(self.repair_notes),
            "next_pending_step": next_step.to_dict() if next_step else None,
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ExecutionPlan":
        payload = data if isinstance(data, dict) else {}
        steps = [
            PlanStep.from_dict(item)
            for item in payload.get("steps", [])
            if isinstance(item, dict)
        ]
        return cls(
            goal=str(payload.get("goal") or "").strip(),
            steps=steps,
            mode=str(payload.get("mode") or "tool_workflow").strip() or "tool_workflow",
            planner_notes=str(payload.get("planner_notes")).strip() if payload.get("planner_notes") is not None else None,
            status=_coerce_status(payload.get("status"), PlanStatus, PlanStatus.DRAFT),
            validation_notes=_coerce_string_list(payload.get("validation_notes")),
            reconciliation_notes=_coerce_string_list(payload.get("reconciliation_notes")),
            repair_notes=_coerce_string_list(payload.get("repair_notes")),
        )

    def get_next_pending_step(self) -> Optional[PlanStep]:
        for step in self.steps:
            if step.status not in {
                PlanStepStatus.COMPLETED,
                PlanStepStatus.FAILED,
                PlanStepStatus.SKIPPED,
            }:
                return step
        return None

    def get_pending_steps(self) -> List[PlanStep]:
        return [
            step
            for step in self.steps
            if step.status not in {
                PlanStepStatus.COMPLETED,
                PlanStepStatus.FAILED,
                PlanStepStatus.SKIPPED,
            }
        ]

    def has_pending_steps(self) -> bool:
        return self.get_next_pending_step() is not None

    def get_next_step(self) -> Optional[PlanStep]:
        return self.get_next_pending_step()

    def get_step(
        self,
        *,
        step_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        allowed_statuses: Optional[set[PlanStepStatus]] = None,
    ) -> Optional[PlanStep]:
        for step in self.steps:
            if step_id and step.step_id != step_id:
                continue
            if tool_name and step.tool_name != tool_name:
                continue
            if allowed_statuses is not None and step.status not in allowed_statuses:
                continue
            if not step_id and not tool_name:
                continue
            return step
        return None

    def mark_step_status(
        self,
        *,
        step_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        status: PlanStepStatus,
        note: Optional[str] = None,
        reconciliation_note: Optional[str] = None,
        blocked_reason: Optional[str] = None,
    ) -> Optional[PlanStep]:
        step = self.get_step(step_id=step_id, tool_name=tool_name)
        if step is None:
            return None
        step.status = status
        if note and note not in step.validation_notes:
            step.validation_notes.append(note)
        if reconciliation_note and reconciliation_note not in step.reconciliation_notes:
            step.reconciliation_notes.append(reconciliation_note)
        if blocked_reason is not None:
            text = str(blocked_reason).strip()
            step.blocked_reason = text or None
        return step

    def append_validation_note(self, note: Optional[str]) -> None:
        if note:
            text = str(note).strip()
            if text and text not in self.validation_notes:
                self.validation_notes.append(text)

    def append_reconciliation_note(self, note: Optional[str]) -> None:
        if note:
            text = str(note).strip()
            if text and text not in self.reconciliation_notes:
                self.reconciliation_notes.append(text)

    def append_repair_note(self, note: Optional[str]) -> None:
        if note:
            text = str(note).strip()
            if text and text not in self.repair_notes:
                self.repair_notes.append(text)
```

- 文件：`core/plan_repair.py`
- 对象：`core/plan_repair.py 全文件`
- 行号：`1-761`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Sequence

from core.plan import ExecutionPlan, PlanStatus, PlanStep, PlanStepStatus
from core.tool_dependencies import (
    TOOL_GRAPH,
    get_required_result_tokens,
    get_tool_provides,
    normalize_result_token,
    normalize_tokens,
    validate_plan_steps,
)

if TYPE_CHECKING:
    from core.context_store import SessionContextStore


class RepairTriggerType(str, Enum):
    PLAN_DEVIATION = "plan_deviation"
    DEPENDENCY_BLOCKED = "dependency_blocked"


class RepairActionType(str, Enum):
    KEEP_REMAINING = "KEEP_REMAINING"
    DROP_BLOCKED_STEP = "DROP_BLOCKED_STEP"
    REORDER_REMAINING_STEPS = "REORDER_REMAINING_STEPS"
    REPLACE_STEP = "REPLACE_STEP"
    TRUNCATE_AFTER_CURRENT = "TRUNCATE_AFTER_CURRENT"
    APPEND_RECOVERY_STEP = "APPEND_RECOVERY_STEP"
    NO_REPAIR = "NO_REPAIR"


def _coerce_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_string_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    result: List[str] = []
    for item in values:
        text = _coerce_string(item)
        if text:
            result.append(text)
    return result


def _coerce_enum(value: Any, enum_cls: type[Enum], default: Enum) -> Enum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except Exception:
        return default


def _clone_step(step: PlanStep) -> PlanStep:
    return PlanStep.from_dict(step.to_dict())


def clone_plan(plan: ExecutionPlan) -> ExecutionPlan:
    return ExecutionPlan.from_dict(plan.to_dict())


def _allowed_result_tokens() -> List[str]:
    tokens: List[str] = ["emission", "dispersion", "hotspot"]
    for spec in TOOL_GRAPH.values():
        tokens.extend(spec.get("requires", []))
        tokens.extend(spec.get("provides", []))
    return normalize_tokens(tokens)


def _allocate_repair_step_id(plan: ExecutionPlan, preferred: Optional[str] = None) -> str:
    existing = {step.step_id for step in plan.steps}
    candidate = _coerce_string(preferred)
    if candidate and candidate not in existing:
        return candidate

    index = 1
    while True:
        candidate = f"repair_s{index}"
        if candidate not in existing:
            return candidate
        index += 1


def _is_mutable_step(step: PlanStep) -> bool:
    return step.status not in {
        PlanStepStatus.COMPLETED,
        PlanStepStatus.SKIPPED,
        PlanStepStatus.FAILED,
    }


def _active_residual_step(step: PlanStep) -> bool:
    return step.status not in {
        PlanStepStatus.COMPLETED,
        PlanStepStatus.SKIPPED,
        PlanStepStatus.FAILED,
    }


def _append_unique(target: List[str], note: Optional[str]) -> None:
    text = _coerce_string(note)
    if text and text not in target:
        target.append(text)


@dataclass
class RepairTriggerContext:
    trigger_type: RepairTriggerType
    trigger_reason: str
    target_step_id: Optional[str] = None
    affected_step_ids: List[str] = field(default_factory=list)
    actual_tool_name: Optional[str] = None
    deviation_type: Optional[str] = None
    available_tokens: List[str] = field(default_factory=list)
    missing_tokens: List[str] = field(default_factory=list)
    stale_tokens: List[str] = field(default_factory=list)
    next_pending_step_id: Optional[str] = None
    next_pending_tool_name: Optional[str] = None
    matched_step_id: Optional[str] = None
    blocked_tool_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger_type": self.trigger_type.value,
            "trigger_reason": self.trigger_reason,
            "target_step_id": self.target_step_id,
            "affected_step_ids": list(self.affected_step_ids),
            "actual_tool_name": self.actual_tool_name,
            "deviation_type": self.deviation_type,
            "available_tokens": list(self.available_tokens),
            "missing_tokens": list(self.missing_tokens),
            "stale_tokens": list(self.stale_tokens),
            "next_pending_step_id": self.next_pending_step_id,
            "next_pending_tool_name": self.next_pending_tool_name,
            "matched_step_id": self.matched_step_id,
            "blocked_tool_name": self.blocked_tool_name,
        }


@dataclass
class PlanRepairPatch:
    target_step_id: Optional[str] = None
    affected_step_ids: List[str] = field(default_factory=list)
    skip_step_ids: List[str] = field(default_factory=list)
    reordered_step_ids: List[str] = field(default_factory=list)
    replacement_step: Optional[PlanStep] = None
    append_steps: List[PlanStep] = field(default_factory=list)
    truncate_after_step_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_step_id": self.target_step_id,
            "affected_step_ids": list(self.affected_step_ids),
            "skip_step_ids": list(self.skip_step_ids),
            "reordered_step_ids": list(self.reordered_step_ids),
            "replacement_step": self.replacement_step.to_dict() if self.replacement_step else None,
            "append_steps": [step.to_dict() for step in self.append_steps],
            "truncate_after_step_id": self.truncate_after_step_id,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "PlanRepairPatch":
        payload = data if isinstance(data, dict) else {}
        replacement_payload = payload.get("replacement_step")
        append_payloads = payload.get("append_steps") or []
        return cls(
            target_step_id=_coerce_string(payload.get("target_step_id")),
            affected_step_ids=_coerce_string_list(payload.get("affected_step_ids")),
            skip_step_ids=_coerce_string_list(payload.get("skip_step_ids")),
            reordered_step_ids=_coerce_string_list(payload.get("reordered_step_ids")),
            replacement_step=(
                PlanStep.from_dict(replacement_payload)
                if isinstance(replacement_payload, dict)
                else None
            ),
            append_steps=[
                PlanStep.from_dict(item)
                for item in append_payloads
                if isinstance(item, dict)
            ],
            truncate_after_step_id=_coerce_string(payload.get("truncate_after_step_id")),
        )


@dataclass
class PlanRepairDecision:
    trigger_type: RepairTriggerType
    trigger_reason: str
    action_type: RepairActionType
    target_step_id: Optional[str] = None
    affected_step_ids: List[str] = field(default_factory=list)
    planner_notes: Optional[str] = None
    is_applicable: bool = False
    validation_notes: List[str] = field(default_factory=list)
    patch: PlanRepairPatch = field(default_factory=PlanRepairPatch)
    repaired_plan_snapshot: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger_type": self.trigger_type.value,
            "trigger_reason": self.trigger_reason,
            "action_type": self.action_type.value,
            "target_step_id": self.target_step_id,
            "affected_step_ids": list(self.affected_step_ids),
            "planner_notes": self.planner_notes,
            "is_applicable": self.is_applicable,
            "validation_notes": list(self.validation_notes),
            "patch": self.patch.to_dict(),
            "repaired_plan_snapshot": self.repaired_plan_snapshot,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "PlanRepairDecision":
        payload = data if isinstance(data, dict) else {}
        patch = PlanRepairPatch.from_dict(payload.get("patch"))
        target_step_id = _coerce_string(payload.get("target_step_id")) or patch.target_step_id
        affected_step_ids = _coerce_string_list(payload.get("affected_step_ids")) or patch.affected_step_ids
        return cls(
            trigger_type=_coerce_enum(
                payload.get("trigger_type"),
                RepairTriggerType,
                RepairTriggerType.PLAN_DEVIATION,
            ),
            trigger_reason=_coerce_string(payload.get("trigger_reason")) or "",
            action_type=_coerce_enum(
                payload.get("action_type"),
                RepairActionType,
                RepairActionType.NO_REPAIR,
            ),
            target_step_id=target_step_id,
            affected_step_ids=affected_step_ids,
            planner_notes=_coerce_string(payload.get("planner_notes")),
            is_applicable=bool(payload.get("is_applicable", False)),
            validation_notes=_coerce_string_list(payload.get("validation_notes")),
            patch=patch,
            repaired_plan_snapshot=(
                payload.get("repaired_plan_snapshot")
                if isinstance(payload.get("repaired_plan_snapshot"), dict)
                else None
            ),
        )


@dataclass
class RepairValidationIssue:
    issue_type: str
    message: str
    step_id: Optional[str] = None
    tool_name: Optional[str] = None
    token: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_type": self.issue_type,
            "message": self.message,
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "token": self.token,
        }


@dataclass
class RepairValidationResult:
    action_type: RepairActionType
    is_valid: bool
    validation_notes: List[str] = field(default_factory=list)
    issues: List[RepairValidationIssue] = field(default_factory=list)
    repaired_plan: Optional[ExecutionPlan] = None
    resulting_next_pending_step: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type.value,
            "is_valid": self.is_valid,
            "validation_notes": list(self.validation_notes),
            "issues": [issue.to_dict() for issue in self.issues],
            "repaired_plan": self.repaired_plan.to_dict() if self.repaired_plan else None,
            "resulting_next_pending_step": self.resulting_next_pending_step,
        }


def _note_step_repair(
    step: PlanStep,
    *,
    action_type: RepairActionType,
    note: str,
    source_step_id: Optional[str] = None,
) -> None:
    step.repair_action = action_type.value
    if source_step_id:
        step.repair_source_step_id = source_step_id
    _append_unique(step.repair_notes, note)
    _append_unique(step.reconciliation_notes, note)


def _reject(
    *,
    action_type: RepairActionType,
    issues: List[RepairValidationIssue],
    notes: List[str],
) -> RepairValidationResult:
    return RepairValidationResult(
        action_type=action_type,
        is_valid=False,
        validation_notes=notes,
        issues=issues,
        repaired_plan=None,
        resulting_next_pending_step=None,
    )


def _validate_step_semantics(plan: ExecutionPlan) -> List[RepairValidationIssue]:
    issues: List[RepairValidationIssue] = []
    allowed_tokens = set(_allowed_result_tokens())

    for step in plan.steps:
        if step.tool_name not in TOOL_GRAPH:
            issues.append(
                RepairValidationIssue(
                    issue_type="unknown_tool",
                    message=f"Unknown tool '{step.tool_name}' in repaired plan.",
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                )
            )
            continue

        declared_depends = normalize_tokens(step.depends_on)
        declared_produces = normalize_tokens(step.produces)
        for token in declared_depends:
            if token not in allowed_tokens:
                issues.append(
                    RepairValidationIssue(
                        issue_type="unknown_token",
                        message=f"Unknown depends_on token '{token}' in repaired plan.",
                        step_id=step.step_id,
                        tool_name=step.tool_name,
                        token=token,
                    )
                )
        for token in declared_produces:
            if token not in allowed_tokens:
                issues.append(
                    RepairValidationIssue(
                        issue_type="unknown_token",
                        message=f"Unknown produces token '{token}' in repaired plan.",
                        step_id=step.step_id,
                        tool_name=step.tool_name,
                        token=token,
                    )
                )

        inferred_requires = get_required_result_tokens(step.tool_name, step.argument_hints)
        canonical_provides = get_tool_provides(step.tool_name)
        if declared_depends and inferred_requires and declared_depends != inferred_requires:
            issues.append(
                RepairValidationIssue(
                    issue_type="depends_mismatch",
                    message=(
                        f"Step {step.step_id} declares depends_on {declared_depends}, "
                        f"but tool semantics require {inferred_requires}."
                    ),
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                )
            )
        if declared_produces and canonical_provides and declared_produces != canonical_provides:
            issues.append(
                RepairValidationIssue(
                    issue_type="produces_mismatch",
                    message=(
                        f"Step {step.step_id} declares produces {declared_produces}, "
                        f"but tool semantics provide {canonical_provides}."
                    ),
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                )
            )

    return issues


def _apply_no_repair(plan: ExecutionPlan, decision: PlanRepairDecision) -> ExecutionPlan:
    repaired_plan = clone_plan(plan)
    _append_unique(
        repaired_plan.repair_notes,
        decision.planner_notes or f"Repair decision kept the residual plan unchanged ({decision.action_type.value}).",
    )
    return repaired_plan


def _apply_drop_blocked_step(plan: ExecutionPlan, decision: PlanRepairDecision) -> ExecutionPlan:
    repaired_plan = clone_plan(plan)
    target_ids = (
        decision.patch.skip_step_ids
        or decision.affected_step_ids
        or decision.patch.affected_step_ids
        or ([decision.target_step_id] if decision.target_step_id else [])
    )
    for step_id in target_ids:
        step = repaired_plan.get_step(step_id=step_id)
        if step is None:
            continue
        step.status = PlanStepStatus.SKIPPED
        _note_step_repair(
            step,
            action_type=decision.action_type,
            note=decision.planner_notes or f"Skipped by bounded repair after {decision.trigger_type.value}.",
        )
    _append_unique(
        repaired_plan.repair_notes,
        decision.planner_notes or f"Dropped blocked residual step(s): {', '.join(target_ids)}.",
    )
    return repaired_plan


def _apply_reorder_remaining_steps(plan: ExecutionPlan, decision: PlanRepairDecision) -> ExecutionPlan:
    repaired_plan = clone_plan(plan)
    reordered_ids = decision.patch.reordered_step_ids
    mutable_steps = [step for step in repaired_plan.steps if _active_residual_step(step)]
    id_to_step = {step.step_id: step for step in mutable_steps}
    reordered_steps = [id_to_step[step_id] for step_id in reordered_ids]

    cursor = 0
    new_steps: List[PlanStep] = []
    for step in repaired_plan.steps:
        if _active_residual_step(step):
            candidate = reordered_steps[cursor]
            _note_step_repair(
                candidate,
                action_type=decision.action_type,
                note=decision.planner_notes or "Residual step order updated by bounded repair.",
            )
            new_steps.append(candidate)
            cursor += 1
        else:
            new_steps.append(step)
    repaired_plan.steps = new_steps
    _append_unique(
        repaired_plan.repair_notes,
        decision.planner_notes or "Reordered residual plan steps.",
    )
    return repaired_plan


def _apply_replace_step(plan: ExecutionPlan, decision: PlanRepairDecision) -> ExecutionPlan:
    repaired_plan = clone_plan(plan)
    target_id = decision.target_step_id or decision.patch.target_step_id
    target_step = repaired_plan.get_step(step_id=target_id)
    if target_step is None:
        return repaired_plan

    replacement = _clone_step(decision.patch.replacement_step) if decision.patch.replacement_step else None
    if replacement is None:
        return repaired_plan
    replacement.step_id = _allocate_repair_step_id(repaired_plan, replacement.step_id)
    replacement.depends_on = normalize_tokens(replacement.depends_on)
    replacement.produces = normalize_tokens(replacement.produces or get_tool_provides(replacement.tool_name))
    replacement.status = PlanStepStatus.PENDING
    _note_step_repair(
        replacement,
        action_type=decision.action_type,
        note=decision.planner_notes or f"Replacement for step {target_step.step_id}.",
        source_step_id=target_step.step_id,
    )

    target_step.status = PlanStepStatus.SKIPPED
    _note_step_repair(
        target_step,
        action_type=decision.action_type,
        note=decision.planner_notes or f"Replaced by {replacement.step_id}.",
        source_step_id=replacement.step_id,
    )

    index = repaired_plan.steps.index(target_step)
    repaired_plan.steps.insert(index + 1, replacement)
    _append_unique(
        repaired_plan.repair_notes,
        decision.planner_notes or f"Replaced residual step {target_step.step_id} with {replacement.step_id}.",
    )
    return repaired_plan


def _apply_truncate_after_current(plan: ExecutionPlan, decision: PlanRepairDecision) -> ExecutionPlan:
    repaired_plan = clone_plan(plan)
    anchor_id = decision.patch.truncate_after_step_id or decision.target_step_id
    if not anchor_id:
        return repaired_plan

    anchor = repaired_plan.get_step(step_id=anchor_id)
    if anchor is None:
        return repaired_plan

    start = repaired_plan.steps.index(anchor)
    affected: List[str] = []
    for step in repaired_plan.steps[start:]:
        if step.status == PlanStepStatus.COMPLETED:
            continue
        if step.status in {PlanStepStatus.SKIPPED, PlanStepStatus.FAILED}:
            continue
        step.status = PlanStepStatus.SKIPPED
        _note_step_repair(
            step,
            action_type=decision.action_type,
            note=decision.planner_notes or f"Truncated from step {anchor_id}.",
            source_step_id=anchor_id,
        )
        affected.append(step.step_id)

    _append_unique(
        repaired_plan.repair_notes,
        decision.planner_notes or f"Truncated residual workflow from {anchor_id}: {', '.join(affected)}.",
    )
    return repaired_plan


def _apply_append_recovery_step(plan: ExecutionPlan, decision: PlanRepairDecision) -> ExecutionPlan:
    repaired_plan = clone_plan(plan)
    appended_ids: List[str] = []
    for raw_step in decision.patch.append_steps:
        step = _clone_step(raw_step)
        step.step_id = _allocate_repair_step_id(repaired_plan, step.step_id)
        step.depends_on = normalize_tokens(step.depends_on)
        step.produces = normalize_tokens(step.produces or get_tool_provides(step.tool_name))
        step.status = PlanStepStatus.PENDING
        _note_step_repair(
            step,
            action_type=decision.action_type,
            note=decision.planner_notes or "Appended as a bounded recovery step.",
            source_step_id=decision.target_step_id,
        )
        repaired_plan.steps.append(step)
        appended_ids.append(step.step_id)

    _append_unique(
        repaired_plan.repair_notes,
        decision.planner_notes or f"Appended recovery step(s): {', '.join(appended_ids)}.",
    )
    return repaired_plan


def validate_plan_repair(
    current_plan: ExecutionPlan,
    repair_decision: PlanRepairDecision,
    *,
    available_tokens: Optional[Iterable[str]] = None,
    context_store: Optional["SessionContextStore"] = None,
) -> RepairValidationResult:
    action_type = repair_decision.action_type
    issues: List[RepairValidationIssue] = []
    validation_notes: List[str] = []

    if action_type not in set(RepairActionType):
        issues.append(
            RepairValidationIssue(
                issue_type="unknown_action",
                message=f"Unknown repair action '{action_type}'.",
            )
        )
        return _reject(action_type=RepairActionType.NO_REPAIR, issues=issues, notes=validation_notes)

    completed_ids = {
        step.step_id
        for step in current_plan.steps
        if step.status == PlanStepStatus.COMPLETED
    }

    touched_ids: set[str] = set()
    if action_type == RepairActionType.DROP_BLOCKED_STEP:
        touched_ids.update(repair_decision.patch.skip_step_ids)
        touched_ids.update(repair_decision.affected_step_ids)
        touched_ids.update(repair_decision.patch.affected_step_ids)
        for candidate_id in [repair_decision.target_step_id, repair_decision.patch.target_step_id]:
            if candidate_id:
                touched_ids.add(candidate_id)
    elif action_type == RepairActionType.REORDER_REMAINING_STEPS:
        touched_ids.update(repair_decision.patch.reordered_step_ids)
    elif action_type == RepairActionType.REPLACE_STEP:
        for candidate_id in [repair_decision.target_step_id, repair_decision.patch.target_step_id]:
            if candidate_id:
                touched_ids.add(candidate_id)
    elif action_type == RepairActionType.TRUNCATE_AFTER_CURRENT:
        touched_ids.update(repair_decision.affected_step_ids)
        touched_ids.update(repair_decision.patch.affected_step_ids)

    immutable_touches = sorted(touched_ids & completed_ids)
    if immutable_touches:
        for step_id in immutable_touches:
            issues.append(
                RepairValidationIssue(
                    issue_type="completed_step_mutation",
                    message=f"Repair cannot mutate completed step '{step_id}'.",
                    step_id=step_id,
                )
            )
        return _reject(action_type=action_type, issues=issues, notes=validation_notes)

    if repair_decision.action_type == RepairActionType.NO_REPAIR:
        repaired_plan = _apply_no_repair(current_plan, repair_decision)
    elif repair_decision.action_type == RepairActionType.KEEP_REMAINING:
        repaired_plan = _apply_no_repair(current_plan, repair_decision)
    elif repair_decision.action_type == RepairActionType.DROP_BLOCKED_STEP:
        step_ids = (
            repair_decision.patch.skip_step_ids
            or repair_decision.affected_step_ids
            or repair_decision.patch.affected_step_ids
            or ([repair_decision.target_step_id] if repair_decision.target_step_id else [])
        )
        if not step_ids:
            issues.append(
                RepairValidationIssue(
                    issue_type="missing_patch_data",
                    message="DROP_BLOCKED_STEP requires at least one target step id.",
                )
            )
            return _reject(action_type=action_type, issues=issues, notes=validation_notes)
        repaired_plan = _apply_drop_blocked_step(current_plan, repair_decision)
    elif repair_decision.action_type == RepairActionType.REORDER_REMAINING_STEPS:
        mutable_steps = [step for step in current_plan.steps if _active_residual_step(step)]
        mutable_ids = [step.step_id for step in mutable_steps]
        if sorted(repair_decision.patch.reordered_step_ids) != sorted(mutable_ids):
            issues.append(
                RepairValidationIssue(
                    issue_type="illegal_reorder",
                    message=(
                        "REORDER_REMAINING_STEPS must provide an exact permutation of the "
                        f"residual step ids: {mutable_ids}."
                    ),
                )
            )
            return _reject(action_type=action_type, issues=issues, notes=validation_notes)
        repaired_plan = _apply_reorder_remaining_steps(current_plan, repair_decision)
    elif repair_decision.action_type == RepairActionType.REPLACE_STEP:
        if repair_decision.patch.replacement_step is None:
            issues.append(
                RepairValidationIssue(
                    issue_type="missing_patch_data",
                    message="REPLACE_STEP requires patch.replacement_step.",
                )
            )
            return _reject(action_type=action_type, issues=issues, notes=validation_notes)
        repaired_plan = _apply_replace_step(current_plan, repair_decision)
    elif repair_decision.action_type == RepairActionType.TRUNCATE_AFTER_CURRENT:
        if not (repair_decision.patch.truncate_after_step_id or repair_decision.target_step_id):
            issues.append(
                RepairValidationIssue(
                    issue_type="missing_patch_data",
                    message="TRUNCATE_AFTER_CURRENT requires truncate_after_step_id or target_step_id.",
                )
            )
            return _reject(action_type=action_type, issues=issues, notes=validation_notes)
        repaired_plan = _apply_truncate_after_current(current_plan, repair_decision)
    elif repair_decision.action_type == RepairActionType.APPEND_RECOVERY_STEP:
        if not repair_decision.patch.append_steps:
            issues.append(
                RepairValidationIssue(
                    issue_type="missing_patch_data",
                    message="APPEND_RECOVERY_STEP requires patch.append_steps.",
                )
            )
            return _reject(action_type=action_type, issues=issues, notes=validation_notes)
        repaired_plan = _apply_append_recovery_step(current_plan, repair_decision)
    else:
        issues.append(
            RepairValidationIssue(
                issue_type="unknown_action",
                message=f"Unsupported repair action '{repair_decision.action_type.value}'.",
            )
        )
        return _reject(action_type=action_type, issues=issues, notes=validation_notes)

    issues.extend(_validate_step_semantics(repaired_plan))
    if issues:
        return _reject(action_type=action_type, issues=issues, notes=validation_notes)

    available = set(normalize_tokens(available_tokens))
    for step in repaired_plan.steps:
        if step.status == PlanStepStatus.COMPLETED:
            available.update(step.produces or get_tool_provides(step.tool_name))

    residual_steps: List[PlanStep] = []
    for step in repaired_plan.steps:
        if not _active_residual_step(step):
            continue
        clone = _clone_step(step)
        clone.status = PlanStepStatus.PENDING
        residual_steps.append(clone)

    if not residual_steps:
        repaired_plan.status = PlanStatus.VALID
        repaired_plan.validation_notes = ["Residual plan has no executable steps after repair."]
        next_step = repaired_plan.get_next_pending_step()
        return RepairValidationResult(
            action_type=repair_decision.action_type,
            is_valid=True,
            validation_notes=list(repaired_plan.validation_notes),
            issues=[],
            repaired_plan=repaired_plan,
            resulting_next_pending_step=next_step.to_dict() if next_step else None,
        )

    residual_validation = validate_plan_steps(residual_steps, available_tokens=available)
    if residual_validation["status"] != PlanStatus.VALID:
        validation_notes.extend(residual_validation["validation_notes"])
        for result in residual_validation["step_results"]:
            issues.append(
                RepairValidationIssue(
                    issue_type="illegal_residual_plan",
                    message="; ".join(result["validation_notes"]) or "Residual step is not executable.",
                    step_id=result.get("step_id"),
                    tool_name=result.get("tool_name"),
                )
            )
        return _reject(action_type=action_type, issues=issues, notes=validation_notes)

    residual_by_id = {item["step_id"]: item for item in residual_validation["step_results"]}
    for step in repaired_plan.steps:
        if step.step_id not in residual_by_id:
            continue
        result = residual_by_id[step.step_id]
        step.depends_on = list(result["required_tokens"])
        step.produces = list(result["produced_tokens"])
        step.status = result["status"]
        for note in result["validation_notes"]:
            _append_unique(step.validation_notes, note)
        step.blocked_reason = None

    repaired_plan.status = PlanStatus.VALID
    repaired_plan.validation_notes = list(residual_validation["validation_notes"])
    _append_unique(
        repaired_plan.repair_notes,
        repair_decision.planner_notes or f"Repair action {repair_decision.action_type.value} validated.",
    )
    next_step = repaired_plan.get_next_pending_step()

    return RepairValidationResult(
        action_type=repair_decision.action_type,
        is_valid=True,
        validation_notes=list(residual_validation["validation_notes"]),
        issues=[],
        repaired_plan=repaired_plan,
        resulting_next_pending_step=next_step.to_dict() if next_step else None,
    )


def summarize_repair_action(decision: PlanRepairDecision) -> str:
    summary = decision.action_type.value
    if decision.target_step_id:
        summary += f" on {decision.target_step_id}"
    if decision.affected_step_ids:
        summary += f" affecting {', '.join(decision.affected_step_ids)}"
    return summary
```

## 9. Router 中的工作流编排代码

- 文件：`core/router.py`
- 对象：`UnifiedRouter._run_state_loop`
- 行号：`872-942`

```python
    async def _run_state_loop(
        self,
        user_message: str,
        file_path: Optional[str] = None,
        trace: Optional[Dict[str, Any]] = None,
    ) -> RouterResponse:
        config = get_config()

        fact_memory = self.memory.get_fact_memory()
        state = TaskState.initialize(
            user_message=user_message,
            file_path=file_path,
            memory_dict=fact_memory,
            session_id=self.session_id,
        )
        state.control.max_steps = config.max_orchestration_steps
        trace_obj = Trace.start(session_id=self.session_id) if config.enable_trace else None

        loop_guard = 0
        max_state_iterations = max(6, state.control.max_steps * 3)
        while not state.is_terminal() and loop_guard < max_state_iterations:
            loop_guard += 1
            if state.stage == TaskStage.INPUT_RECEIVED:
                await self._state_handle_input(state, trace_obj=trace_obj)
            elif state.stage == TaskStage.GROUNDED:
                await self._state_handle_grounded(state, trace_obj=trace_obj)
            elif state.stage == TaskStage.EXECUTING:
                await self._state_handle_executing(state, trace_obj=trace_obj)

        if not state.is_terminal():
            self._transition_state(
                state,
                TaskStage.DONE,
                reason="state loop guard reached",
                trace_obj=trace_obj,
            )

        if trace_obj:
            trace_obj.finish(final_stage=state.stage.value)

        response = await self._state_build_response(state, user_message, trace_obj=trace_obj)
        self._sync_live_continuation_state(state)

        tool_calls_data = None
        if state.execution.tool_results and not state.execution.tool_results[0].get("no_tool"):
            tool_calls_data = self._build_memory_tool_calls(state.execution.tool_results)

        file_context = state.file_context.to_dict() if state.file_context.grounded else None
        cached_file_context = getattr(state, "_file_analysis_cache", None)
        if file_context and isinstance(cached_file_context, dict):
            enriched_file_context = dict(cached_file_context)
            enriched_file_context.update(file_context)
            file_context = enriched_file_context

        memory_file_path, memory_file_analysis = self._resolve_memory_update_payload(
            state,
            raw_file_path=file_path,
            file_context=file_context,
        )
        self.memory.update(
            user_message,
            response.text,
            tool_calls_data,
            memory_file_path,
            memory_file_analysis,
        )

        if trace is not None and trace_obj:
            trace.update(trace_obj.to_dict())

        return response
```

- 文件：`core/router.py`
- 对象：`UnifiedRouter._state_handle_executing`
- 行号：`8807-9266`

```python
    async def _state_handle_executing(
        self,
        state: TaskState,
        trace_obj: Optional[Trace] = None,
    ) -> None:
        response = state._llm_response
        if not response or not response.tool_calls:
            state.execution.tool_results = [{"text": getattr(response, "content", ""), "no_tool": True}]
            self._transition_state(
                state,
                TaskStage.DONE,
                reason="missing tool calls during execution",
                trace_obj=trace_obj,
            )
            return

        context = getattr(state, "_assembled_context", None)
        if context is None:
            context = self.assembler.assemble(
                user_message=state.user_message or "",
                working_memory=self.memory.get_working_memory(),
                fact_memory=self.memory.get_fact_memory(),
                file_context=self._build_state_file_context(state),
                context_summary=self._get_context_summary(),
            )
            setattr(state, "_assembled_context", context)

        conversation_messages = list(context.messages)
        current_response = response
        rounds_used = 1
        dependency_blocked = False
        repair_halted = False

        while current_response and current_response.tool_calls and not dependency_blocked and not repair_halted:
            cycle_results: List[Dict[str, Any]] = []

            for tool_call in current_response.tool_calls:
                logger.info(f"Executing tool: {tool_call.name}")
                logger.debug(f"Tool arguments: {tool_call.arguments}")

                reconciliation = self._reconcile_plan_before_execution(
                    state,
                    tool_call.name,
                    trace_obj=trace_obj,
                )
                planned_step = reconciliation.get("planned_step")
                if reconciliation.get("deviation_type"):
                    trigger_context = self._build_repair_trigger_context(
                        state,
                        trigger_type=RepairTriggerType.PLAN_DEVIATION,
                        trigger_reason=reconciliation.get("note") or "Execution deviated from the current plan.",
                        actual_tool_name=tool_call.name,
                        deviation_type=reconciliation.get("deviation_type"),
                        planned_step=planned_step,
                        next_step=reconciliation.get("next_step"),
                    )
                    should_repair, repair_reason = self._should_attempt_plan_repair(state, trigger_context)
                    if should_repair:
                        repaired, decision, validation, failure_reason = await self._attempt_plan_repair(
                            state,
                            trigger_context,
                            trace_obj=trace_obj,
                        )
                        repair_halted = True
                        setattr(
                            state,
                            "_final_response_text",
                            (
                                self._build_plan_repair_response_text(trigger_context, decision, validation)
                                if repaired
                                else self._build_plan_repair_failure_text(
                                    trigger_context,
                                    failure_reason or "repair validation failed",
                                )
                            ),
                        )
                        break
                    if trace_obj:
                        trace_obj.record(
                            step_type=TraceStepType.PLAN_REPAIR_SKIPPED,
                            stage_before=TaskStage.EXECUTING.value,
                            action=tool_call.name,
                            input_summary=trigger_context.to_dict(),
                            reasoning=repair_reason,
                        )

                effective_arguments = self._prepare_tool_arguments(
                    tool_call.name,
                    tool_call.arguments,
                    state=state,
                )
                readiness_assessment, readiness_affordance = self._assess_selected_action_readiness(
                    tool_name=tool_call.name,
                    arguments=effective_arguments,
                    tool_results=state.execution.tool_results,
                    state=state,
                    trace_obj=trace_obj,
                    stage_before=TaskStage.EXECUTING.value,
                    purpose="pre_execution",
                )
                if readiness_affordance is not None and self._should_short_circuit_readiness(readiness_affordance):
                    state.execution.blocked_info = self._build_action_readiness_block_payload(readiness_affordance)
                    state.execution.last_error = state.execution.blocked_info["message"]
                    completion_request = None
                    if readiness_affordance.status == ReadinessStatus.REPAIRABLE:
                        completion_request = self._build_input_completion_request(
                            state,
                            readiness_affordance,
                        )
                    if completion_request is not None:
                        state.append_plan_note(
                            f"Repairable action '{tool_call.name}' entered structured input completion.",
                            step_id=getattr(planned_step, "step_id", None),
                            tool_name=None if planned_step is not None else tool_call.name,
                            reconciliation=True,
                        )
                        self._activate_input_completion_state(
                            state,
                            completion_request,
                            readiness_affordance,
                            trace_obj=trace_obj,
                        )
                        return
                    self._mark_blocked_plan_step(
                        state,
                        tool_call.name,
                        state.execution.last_error,
                        planned_step=planned_step,
                    )
                    if readiness_affordance.status == ReadinessStatus.ALREADY_PROVIDED:
                        setattr(
                            state,
                            "_final_response_text",
                            build_action_already_provided_response(
                                readiness_affordance,
                                readiness_assessment or ReadinessAssessment(),
                            ),
                        )
                    elif readiness_affordance.status == ReadinessStatus.REPAIRABLE:
                        setattr(
                            state,
                            "_final_response_text",
                            build_action_repairable_response(
                                readiness_affordance,
                                readiness_assessment or ReadinessAssessment(),
                            ),
                        )
                    else:
                        setattr(
                            state,
                            "_final_response_text",
                            build_action_blocked_response(
                                readiness_affordance,
                                readiness_assessment or ReadinessAssessment(),
                            ),
                        )
                    dependency_blocked = True
                    break
                dependency_validation = self._validate_execution_dependencies(
                    state,
                    tool_call.name,
                    effective_arguments,
                    trace_obj=trace_obj,
                )
                if not dependency_validation.is_valid:
                    dependency_blocked = True
                    blocked_payload = dependency_validation.to_dict()
                    if planned_step is not None:
                        blocked_payload["step_id"] = planned_step.step_id
                    state.execution.blocked_info = blocked_payload
                    state.execution.last_error = dependency_validation.message
                    self._mark_blocked_plan_step(
                        state,
                        tool_call.name,
                        dependency_validation.message,
                        planned_step=planned_step,
                    )
                    trigger_context = self._build_repair_trigger_context(
                        state,
                        trigger_type=RepairTriggerType.DEPENDENCY_BLOCKED,
                        trigger_reason=dependency_validation.message,
                        actual_tool_name=tool_call.name,
                        planned_step=planned_step,
                        next_step=reconciliation.get("next_step"),
                        dependency_validation=dependency_validation,
                    )
                    should_repair, repair_reason = self._should_attempt_plan_repair(state, trigger_context)
                    if should_repair:
                        repaired, decision, validation, failure_reason = await self._attempt_plan_repair(
                            state,
                            trigger_context,
                            trace_obj=trace_obj,
                        )
                        setattr(
                            state,
                            "_final_response_text",
                            (
                                self._build_plan_repair_response_text(trigger_context, decision, validation)
                                if repaired
                                else self._build_plan_repair_failure_text(
                                    trigger_context,
                                    failure_reason or "repair validation failed",
                                )
                            ),
                        )
                    else:
                        if trace_obj:
                            trace_obj.record(
                                step_type=TraceStepType.PLAN_REPAIR_SKIPPED,
                                stage_before=TaskStage.EXECUTING.value,
                                action=tool_call.name,
                                input_summary=trigger_context.to_dict(),
                                reasoning=repair_reason,
                            )
                        setattr(
                            state,
                            "_final_response_text",
                            self._build_dependency_blocked_response_text(state, dependency_validation),
                        )
                    break

                tool_start_time = time.time()
                result = await self.executor.execute(
                    tool_name=tool_call.name,
                    arguments=effective_arguments,
                    file_path=state.file_context.file_path
                )
                elapsed_ms = round((time.time() - tool_start_time) * 1000, 1)

                logger.info(
                    "Tool %s completed. Success: %s, Error: %s",
                    tool_call.name,
                    result.get("success"),
                    result.get("error"),
                )
                if result.get("error"):
                    logger.error("Tool error message: %s", result.get("message", "No message"))

                tool_result = {
                    "tool_call_id": tool_call.id,
                    "name": tool_call.name,
                    "arguments": tool_call.arguments,
                    "result": result
                }
                cycle_results.append(tool_result)
                state.execution.tool_results.append(tool_result)
                state.execution.completed_tools.append(tool_call.name)
                self._save_result_to_session_context(tool_call.name, result)

                if result.get("success"):
                    state.execution.available_results.update(get_tool_provides(tool_call.name))
                completed_plan_step = self._update_plan_after_tool_execution(state, tool_call.name, result)
                self._refresh_execution_plan_state(state)
                if trace_obj and result.get("success") and completed_plan_step is not None:
                    trace_obj.record(
                        step_type=TraceStepType.PLAN_STEP_COMPLETED,
                        stage_before=TaskStage.EXECUTING.value,
                        action=tool_call.name,
                        input_summary={
                            "step_id": completed_plan_step.step_id,
                            "tool_name": tool_call.name,
                            "execution_success": True,
                        },
                        output_summary={
                            "produced_tokens": get_tool_provides(tool_call.name),
                            "available_tokens": sorted(state.execution.available_results),
                        },
                        reasoning=(
                            f"Completed planned step {completed_plan_step.step_id} via {tool_call.name}."
                        ),
                    )

                std_records = result.get("_standardization_records", [])
                if trace_obj and std_records:
                    std_summary_parts = []
                    for rec in std_records:
                        param = rec.get("param", "?")
                        original = rec.get("original", "?")
                        normalized = rec.get("normalized", original)
                        strategy = rec.get("strategy", "?")
                        confidence = rec.get("confidence", 0)

                        if original != normalized:
                            std_summary_parts.append(
                                f"{param}: '{original}' → '{normalized}' ({strategy}, conf={confidence:.2f})"
                            )
                        else:
                            std_summary_parts.append(
                                f"{param}: '{original}' ✓ ({strategy}, conf={confidence:.2f})"
                            )

                    if std_summary_parts:
                        trace_obj.record(
                            step_type=TraceStepType.PARAMETER_STANDARDIZATION,
                            stage_before=TaskStage.EXECUTING.value,
                            action="standardize_parameters",
                            reasoning="; ".join(std_summary_parts),
                            standardization_records=std_records,
                        )

                if result.get("error") and result.get("error_type") == "standardization":
                    error_msg = result.get("message", "Parameter standardization failed")
                    negotiation_request = self._build_parameter_negotiation_request(tool_call.name, result)
                    if negotiation_request is not None:
                        state.execution.last_error = error_msg
                        self._activate_parameter_confirmation_state(
                            state,
                            negotiation_request,
                            trace_obj=trace_obj,
                        )
                        return

                    suggestions = result.get("suggestions", [])
                    clarification = (
                        f"{error_msg}\n\nDid you mean one of these? {', '.join(suggestions[:5])}"
                        if suggestions else error_msg
                    )

                    state.control.needs_user_input = True
                    state.control.parameter_confirmation_prompt = None
                    state.control.clarification_question = clarification
                    state.execution.last_error = error_msg
                    self._transition_state(
                        state,
                        TaskStage.NEEDS_CLARIFICATION,
                        reason="Standardization failed",
                        trace_obj=trace_obj,
                    )

                    if trace_obj:
                        trace_obj.record(
                            step_type=TraceStepType.ERROR,
                            stage_before=TaskStage.EXECUTING.value,
                            stage_after=TaskStage.NEEDS_CLARIFICATION.value,
                            action=tool_call.name,
                            error=error_msg,
                        )
                    return

                if trace_obj:
                    output_info = {"success": result.get("success", False)}
                    if result.get("success"):
                        data = result.get("data", {})
                        if isinstance(data, dict):
                            if "total_emissions" in data:
                                output_info["total_links"] = data.get("summary", {}).get("total_links")
                                output_info["pollutants"] = list(data.get("total_emissions", {}).keys())
                            elif "speed_data" in data or "curve" in str(data):
                                output_info["data_points"] = data.get("data_count") or data.get("speed_data", {}).get("count")
                        output_info["message"] = str(result.get("message", ""))[:100]
                    else:
                        output_info["error"] = str(result.get("message", ""))[:200]

                    trace_obj.record(
                        step_type=TraceStepType.TOOL_EXECUTION,
                        stage_before=TaskStage.EXECUTING.value,
                        action=tool_call.name,
                        input_summary={
                            "arguments": {
                                key: str(value)[:80]
                                for key, value in (tool_call.arguments or {}).items()
                            }
                        },
                        output_summary=output_info,
                        confidence=None,
                        reasoning=result.get("summary", ""),
                        duration_ms=elapsed_ms,
                        standardization_records=std_records or None,
                        error=result.get("message") if result.get("error") else None,
                    )

            if dependency_blocked or repair_halted:
                break

            if not cycle_results:
                break

            has_error = any(item["result"].get("error") for item in cycle_results)
            if has_error:
                state.execution.last_error = self._format_tool_errors(cycle_results)

            self._append_tool_messages_for_llm(conversation_messages, current_response, cycle_results)
            context.messages = conversation_messages

            if rounds_used >= state.control.max_steps:
                logger.info(
                    "Reached max orchestration steps (%s); finalizing with current tool results",
                    state.control.max_steps,
                )
                if has_error and state.execution.last_error and not getattr(state, "_final_response_text", None):
                    setattr(state, "_final_response_text", state.execution.last_error)
                break

            follow_up_response = await self.llm.chat_with_tools(
                messages=conversation_messages,
                tools=context.tools,
                system=context.system_prompt,
            )
            state._llm_response = follow_up_response

            if follow_up_response.tool_calls:
                state.execution.selected_tool = follow_up_response.tool_calls[0].name
                self._capture_tool_call_parameters(state, follow_up_response.tool_calls)
                if trace_obj:
                    tool_names = [tc.name for tc in follow_up_response.tool_calls]
                    reason = "LLM selected next tool(s) after tool results"
                    if has_error:
                        reason = "LLM selected tool(s) after tool error feedback"
                    trace_obj.record(
                        step_type=TraceStepType.TOOL_SELECTION,
                        stage_before=TaskStage.EXECUTING.value,
                        stage_after=TaskStage.EXECUTING.value,
                        action=", ".join(tool_names),
                        reasoning=f"{reason}: {', '.join(tool_names)}",
                    )
                current_response = follow_up_response
                rounds_used += 1
                continue

            if follow_up_response.content:
                setattr(state, "_final_response_text", follow_up_response.content)
            elif has_error and state.execution.last_error and not getattr(state, "_final_response_text", None):
                setattr(state, "_final_response_text", state.execution.last_error)
            break

        has_spatial_data = False
        has_map_data_from_tool = False
        available_pollutants: set = set()
        for r in state.execution.tool_results:
            actual = r.get("result", r) if isinstance(r, dict) else r
            if not isinstance(actual, dict):
                continue
            if actual.get("map_data"):
                has_map_data_from_tool = True
            if not actual.get("success"):
                continue
            data = actual.get("data", {})
            if not isinstance(data, dict):
                continue
            for link in data.get("results", [])[:5]:
                if isinstance(link, dict):
                    if link.get("geometry"):
                        has_spatial_data = True
                    available_pollutants.update(
                        link.get("total_emissions_kg_per_hr", {}).keys()
                    )

        already_visualized = "render_spatial_map" in state.execution.completed_tools

        if has_spatial_data and not already_visualized and not has_map_data_from_tool:
            logger.info("Spatial data detected, will suggest visualization to user")
            state.execution._visualization_available = True
            state.execution._available_pollutants = sorted(available_pollutants)

        self._transition_state(
            state,
            TaskStage.DONE,
            reason="execution completed",
            trace_obj=trace_obj,
        )
```

- 文件：`core/router.py`
- 对象：`UnifiedRouter._prepare_tool_arguments`
- 行号：`545-625`

```python
    def _prepare_tool_arguments(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]],
        state: Optional[TaskState] = None,
    ) -> Dict[str, Any]:
        """Inject the right upstream result for downstream tools."""
        effective_arguments = dict(arguments or {})
        if state is not None:
            for param_name, entry in state.parameters.items():
                if entry.locked and entry.normalized and param_name in effective_arguments:
                    effective_arguments[param_name] = entry.normalized
            if state.input_completion_overrides:
                effective_arguments["_input_completion_overrides"] = (
                    state.get_input_completion_overrides_summary()
                )
        if tool_name == "compare_scenarios":
            effective_arguments["_context_store"] = self._ensure_context_store()
            return effective_arguments

        if tool_name not in {"render_spatial_map", "calculate_dispersion", "analyze_hotspots"}:
            return effective_arguments
        if "_last_result" in effective_arguments:
            return effective_arguments

        context_store = self._ensure_context_store()
        layer_type = effective_arguments.get("layer_type")
        scenario_label = effective_arguments.get("scenario_label")
        stored_result = context_store.get_result_for_tool(
            tool_name,
            label=scenario_label,
            layer_type=layer_type,
        )
        if isinstance(stored_result, dict):
            effective_arguments["_last_result"] = stored_result
            logger.info("%s: injected _last_result from context store", tool_name)
            return effective_arguments

        fact_mem = self.memory.get_fact_memory()
        spatial = fact_mem.get("last_spatial_data")

        if tool_name == "render_spatial_map":
            if isinstance(spatial, dict) and spatial.get("results"):
                effective_arguments["_last_result"] = {"success": True, "data": spatial}
                logger.info(
                    "render_spatial_map: injected from memory spatial_data, %s links",
                    len(spatial["results"]),
                )
                return effective_arguments
            snapshot = fact_mem.get("last_tool_snapshot")
            if snapshot:
                effective_arguments["_last_result"] = snapshot
                logger.warning(
                    "render_spatial_map: using last_tool_snapshot (may be compacted, geometry might be missing)"
                )
                return effective_arguments

        if tool_name == "calculate_dispersion":
            if isinstance(spatial, dict) and spatial.get("results"):
                sample = spatial["results"][:3]
                if any(
                    isinstance(item, dict) and item.get("total_emissions_kg_per_hr")
                    for item in sample
                ):
                    effective_arguments["_last_result"] = {"success": True, "data": spatial}
                    logger.info(
                        "calculate_dispersion: injected macro emission result from memory spatial_data, %s links",
                        len(spatial["results"]),
                    )
                    return effective_arguments

        if tool_name == "analyze_hotspots":
            if isinstance(spatial, dict) and "raster_grid" in spatial:
                effective_arguments["_last_result"] = {"success": True, "data": spatial}
                logger.info(
                    "analyze_hotspots: injected raster result from memory spatial_data, hotspots=%s",
                    len(spatial.get("hotspots", [])),
                )
                return effective_arguments

        return effective_arguments
```

- 文件：`core/router.py`
- 对象：`UnifiedRouter._assess_selected_action_readiness`
- 行号：`8023-8058`

```python
    def _assess_selected_action_readiness(
        self,
        *,
        tool_name: str,
        arguments: Optional[Dict[str, Any]],
        tool_results: List[Dict[str, Any]],
        state: Optional[TaskState] = None,
        trace_obj: Optional[Trace] = None,
        stage_before: str,
        purpose: str = "pre_execution",
    ) -> tuple[Optional[ReadinessAssessment], Optional[ActionAffordance]]:
        frontend_payloads = self._extract_frontend_payloads(tool_results)
        assessment = self._build_readiness_assessment(
            tool_results,
            state=state,
            frontend_payloads=frontend_payloads,
            trace_obj=trace_obj,
            stage_before=stage_before,
            purpose=purpose,
        )
        if assessment is None:
            return None, None

        action_id = map_tool_call_to_action_id(tool_name, arguments)
        if action_id is None:
            return assessment, None

        affordance = assessment.get_action(action_id)
        if affordance is not None:
            self._record_action_readiness_trace(
                affordance,
                trace_obj=trace_obj,
                stage_before=stage_before,
                purpose=purpose,
            )
        return assessment, affordance
```

- 文件：`core/router.py`
- 对象：`UnifiedRouter._save_result_to_session_context`
- 行号：`495-498`

```python
    def _save_result_to_session_context(self, tool_name: str, result: Dict[str, Any]) -> None:
        """Store full results for downstream tools and keep legacy spatial memory updated."""
        self._ensure_context_store().add_current_turn_result(tool_name, result)
        self._update_legacy_last_spatial_data(tool_name, result)
```

## 10. 结果合成与能力约束

- `core/capability_summary.py` 当前总行数为 `285`；`build_capability_summary()` 定义于 `33-57`，`format_capability_summary_for_prompt()` 定义于 `60-182`。

- router 的 `_build_capability_summary_for_synthesis()` 位于 `core/router.py:8060-8167`，`_synthesize_results()` 位于 `core/router.py:9777-9840`。

- capability summary 注入 synthesis prompt 的直接代码位于 `core/router_synthesis_utils.py:58-81` 的 `build_synthesis_request()`。

- 文件：`core/capability_summary.py`
- 对象：`core/capability_summary.py 全文件`
- 行号：`1-285`

```python
"""Capability-aware follow-up guidance built on the unified readiness layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from core.artifact_memory import (
    ArtifactMemoryState,
    apply_artifact_memory_to_capability_summary,
)
from core.intent_resolution import IntentResolutionApplicationPlan
from core.readiness import build_readiness_assessment

if TYPE_CHECKING:
    from core.context_store import SessionContextStore


_FOLLOW_UP_ACTIONS_BY_TOOL: Dict[str, Sequence[str]] = {
    "calculate_macro_emission": (
        "render_rank_chart",
        "download_topk_summary",
        "deliver_quick_structured_summary",
        "render_emission_map",
        "run_dispersion",
        "compare_scenario",
    ),
    "calculate_micro_emission": ("render_emission_map", "run_dispersion"),
    "calculate_dispersion": ("run_hotspot_analysis", "render_dispersion_map", "compare_scenario"),
    "analyze_hotspots": ("render_hotspot_map", "compare_scenario"),
}


def build_capability_summary(
    file_context: Optional[Dict[str, Any]],
    context_store: Optional["SessionContextStore"],
    current_tool_results: Sequence[Dict[str, Any]],
    current_response_payloads: Optional[Dict[str, Any]] = None,
    parameter_locks: Optional[Dict[str, Any]] = None,
    artifact_memory_state: Optional[ArtifactMemoryState] = None,
    intent_plan: Optional[IntentResolutionApplicationPlan] = None,
) -> Dict[str, Any]:
    """Return the legacy capability-summary surface backed by readiness assessment."""
    assessment = build_readiness_assessment(
        file_context,
        context_store,
        current_tool_results,
        current_response_payloads,
        parameter_locks=parameter_locks,
        artifact_memory_state=artifact_memory_state,
    )
    summary = assessment.to_capability_summary()
    return apply_artifact_memory_to_capability_summary(
        summary,
        artifact_memory_state,
        intent_plan=intent_plan,
        dedup_by_family=True,
    ) or summary


def format_capability_summary_for_prompt(summary: Optional[Dict[str, Any]]) -> str:
    """Render one bounded prompt section for synthesis."""
    if not isinstance(summary, dict):
        return ""

    available_actions = summary.get("available_next_actions") or []
    repairable_actions = summary.get("repairable_actions") or []
    unavailable_actions = summary.get("unavailable_actions_with_reasons") or []
    already_provided = summary.get("already_provided") or []
    guidance_hints = summary.get("guidance_hints") or []
    intent_bias = summary.get("intent_bias") or {}
    artifact_bias = summary.get("artifact_bias") or {}

    blocked_only = [
        item for item in unavailable_actions
        if item not in repairable_actions
    ]

    lines = [
        "## 后续建议硬约束",
        "",
        "以下是当前数据的 readiness 边界。下面的约束优先级高于一般总结要求，你必须严格遵守：",
        "",
        "### 当前可直接执行的操作",
    ]

    if available_actions:
        for item in available_actions:
            lines.append(f"- {item.get('label')}: {item.get('description')}")
    else:
        lines.append("- 当前没有额外的可执行后续操作可以安全推荐。")

    lines.extend(["", "### 当前可修复但尚未就绪的操作（不要直接建议这些）"])
    if repairable_actions:
        for item in repairable_actions:
            repair_hint = str(item.get("repair_hint") or "").strip()
            reason = str(item.get("reason") or "").strip()
            if repair_hint:
                lines.append(f"- {item.get('label')}: {reason} 补救方向：{repair_hint}")
            else:
                lines.append(f"- {item.get('label')}: {reason}")
    else:
        lines.append("- 无。")

    lines.extend(["", "### 当前被阻断的操作（严禁将这些列为推荐选项）"])
    if blocked_only:
        for item in blocked_only:
            lines.append(f"- {item.get('label')}: {item.get('reason')}")
    else:
        lines.append("- 无。")

    lines.extend(["", "### 本次已提供的交付物（不要重复建议这些）"])
    if already_provided:
        for item in already_provided:
            lines.append(f"- {item.get('display_name') or item.get('label')}: {item.get('message') or item.get('reason')}")
    else:
        lines.append("- 无。")

    if guidance_hints:
        lines.extend(["", "### 能力边界提示"])
        for hint in guidance_hints:
            lines.append(f"- {hint}")

    if isinstance(intent_bias, dict) and intent_bias:
        deliverable = str(intent_bias.get("deliverable_intent") or "").strip()
        progress = str(intent_bias.get("progress_intent") or "").strip()
        preferred_actions = [
            str(item).strip()
            for item in (intent_bias.get("preferred_action_ids") or [])
            if str(item).strip()
        ]
        preferred_artifacts = [
            str(item).strip()
            for item in (intent_bias.get("preferred_artifact_kinds") or [])
            if str(item).strip()
        ]
        lines.extend(["", "### 当前高层意图偏置"])
        if deliverable or progress:
            lines.append(
                f"- deliverable_intent={deliverable or 'unknown'}; progress_intent={progress or 'unknown'}"
            )
        if preferred_actions:
            lines.append(f"- 优先动作: {', '.join(preferred_actions)}")
        if preferred_artifacts:
            lines.append(f"- 优先交付形态: {', '.join(preferred_artifacts)}")

    if isinstance(artifact_bias, dict) and artifact_bias:
        suppressed = [
            str(item).strip()
            for item in (artifact_bias.get("suppressed_action_ids") or [])
            if str(item).strip()
        ]
        promoted = [
            str(item).strip()
            for item in (artifact_bias.get("promoted_families") or [])
            if str(item).strip()
        ]
        repeated_types = [
            str(item).strip()
            for item in (artifact_bias.get("repeated_artifact_types") or [])
            if str(item).strip()
        ]
        lines.extend(["", "### 已交付 artifact 记忆"])
        if repeated_types:
            lines.append(f"- 已完整提供的类型: {', '.join(repeated_types)}")
        if suppressed:
            lines.append(f"- 需抑制重复动作: {', '.join(suppressed)}")
        if promoted:
            lines.append(f"- 更适合补充的输出族: {', '.join(promoted)}")

    lines.extend(
        [
            "",
            "### 最终硬性要求",
            "- 你只能建议“当前可直接执行的操作”中的项目。",
            "- 严禁把 repairable 或 blocked 的动作写成建议列表项、下一步选项或可点击动作。",
            "- repairable 动作如需提及，只能用一句前置条件说明，不能写成推荐。",
            "- 严禁重复建议已提供的下载文件、地图、图表或表格。",
            "- 严禁发明未列出的导出、可视化或分析步骤。",
            "- 如果当前没有安全的后续操作，就明确说“当前没有额外的安全后续操作建议”。",
        ]
    )
    return "\n".join(lines)


def get_capability_aware_follow_up(
    tool_name: str,
    capability_summary: Optional[Dict[str, Any]],
) -> Dict[str, List[str]]:
    """Return filtered follow-up suggestions and hints for deterministic rendering."""
    if not isinstance(capability_summary, dict):
        return {"suggestions": [], "hints": []}

    desired_action_ids = _FOLLOW_UP_ACTIONS_BY_TOOL.get(tool_name, ())
    intent_bias = capability_summary.get("intent_bias") or {}
    available_by_id = {
        item.get("action_id"): item
        for item in capability_summary.get("available_next_actions") or []
        if isinstance(item, dict) and item.get("action_id")
    }
    unavailable_by_id = {
        item.get("action_id"): item
        for item in capability_summary.get("unavailable_actions_with_reasons") or []
        if isinstance(item, dict) and item.get("action_id")
    }

    suggestions: List[str] = []
    hints: List[str] = []
    deliverable_intent = str(intent_bias.get("deliverable_intent") or "").strip()
    preferred_action_ids = [
        str(item).strip()
        for item in (intent_bias.get("preferred_action_ids") or [])
        if str(item).strip()
    ]
    deprioritized_action_ids = {
        str(item).strip()
        for item in (intent_bias.get("deprioritized_action_ids") or [])
        if str(item).strip()
    }
    artifact_bias = capability_summary.get("artifact_bias") or {}
    suppressed_by_artifact = {
        str(item).strip()
        for item in (artifact_bias.get("suppressed_action_ids") or [])
        if str(item).strip()
    }

    ordered_action_ids: List[str] = []
    for action_id in preferred_action_ids:
        if action_id in desired_action_ids and action_id not in ordered_action_ids:
            ordered_action_ids.append(action_id)
    for action_id in desired_action_ids:
        if action_id in ordered_action_ids:
            continue
        ordered_action_ids.append(action_id)

    if deliverable_intent in {
        "chart_or_ranked_summary",
        "downloadable_table",
        "quick_summary",
        "rough_estimate",
    } and not any(action_id in preferred_action_ids for action_id in desired_action_ids):
        ordered_action_ids = []

    for action_id in ordered_action_ids:
        if action_id in suppressed_by_artifact:
            continue
        if action_id in deprioritized_action_ids and action_id not in preferred_action_ids:
            continue
        item = available_by_id.get(action_id)
        if item and item.get("utterance"):
            suggestions.append(str(item["utterance"]))

    for action_id in ordered_action_ids or desired_action_ids:
        item = unavailable_by_id.get(action_id)
        if not item:
            continue
        reason_codes = item.get("reason_codes") or []
        if "missing_geometry" in reason_codes:
            hint = "如需空间分析，请补充路段坐标、WKT、GeoJSON 或其他几何信息。"
            if hint not in hints:
                hints.append(hint)
                continue
        repair_hint = str(item.get("repair_hint") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if repair_hint and repair_hint not in hints:
            hints.append(repair_hint)
        elif reason and reason not in hints:
            hints.append(reason)

    for hint in capability_summary.get("guidance_hints") or []:
        text = str(hint).strip()
        if text and text not in hints:
            hints.append(text)

    bias_summary = str(intent_bias.get("user_visible_summary") or "").strip()
    if bias_summary and bias_summary not in hints:
        hints.insert(0, bias_summary)

    artifact_summary = str(artifact_bias.get("user_visible_summary") or "").strip()
    if artifact_summary and artifact_summary not in hints:
        hints.insert(0, artifact_summary)

    return {
        "suggestions": suggestions,
        "hints": hints,
    }
```

- 文件：`core/router.py`
- 对象：`UnifiedRouter._build_capability_summary_for_synthesis`
- 行号：`8060-8167`

```python
    def _build_capability_summary_for_synthesis(
        self,
        tool_results: List[Dict[str, Any]],
        *,
        state: Optional[TaskState] = None,
        frontend_payloads: Optional[Dict[str, Any]] = None,
        trace_obj: Optional[Trace] = None,
        stage_before: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Summarize current data capabilities so synthesis stays within supported actions."""
        if not getattr(self.runtime_config, "enable_capability_aware_synthesis", True):
            logger.info("[CapabilityAwareSynthesis] disabled by feature flag")
            return None

        assessment = self._build_readiness_assessment(
            tool_results,
            state=state,
            frontend_payloads=frontend_payloads,
            trace_obj=trace_obj,
            stage_before=stage_before,
            purpose="synthesis_guidance",
        )
        if assessment is None:
            return None
        summary = assessment.to_capability_summary()
        if (
            state is not None
            and state.latest_intent_resolution_plan is not None
            and getattr(self.runtime_config, "intent_resolution_bias_followup_suggestions", True)
        ):
            summary = apply_intent_bias_to_capability_summary(
                summary,
                state.latest_intent_resolution_plan,
            )
        if (
            state is not None
            and getattr(self.runtime_config, "enable_artifact_memory", True)
        ):
            artifact_plan = build_artifact_suggestion_plan(
                state.artifact_memory_state,
                capability_summary=summary,
                intent_plan=state.latest_intent_resolution_plan,
                dedup_by_family=getattr(
                    self.runtime_config,
                    "artifact_memory_dedup_by_family",
                    True,
                ),
            )
            if (
                trace_obj is not None
                and stage_before is not None
                and (
                    artifact_plan.repeated_artifact_types
                    or artifact_plan.repeated_artifact_families
                )
            ):
                trace_obj.record(
                    step_type=TraceStepType.ARTIFACT_ALREADY_PROVIDED_DETECTED,
                    stage_before=stage_before,
                    action="artifact_memory_repeat_detection",
                    input_summary=state.get_artifact_memory_summary(),
                    output_summary=artifact_plan.to_dict(),
                    reasoning=(
                        "Detected previously delivered artifact types/families and suppressed repeated follow-up guidance."
                    ),
                )
            if getattr(self.runtime_config, "artifact_memory_bias_followup", True):
                summary = apply_artifact_memory_to_capability_summary(
                    summary,
                    state.artifact_memory_state,
                    state.latest_intent_resolution_plan,
                    dedup_by_family=getattr(
                        self.runtime_config,
                        "artifact_memory_dedup_by_family",
                        True,
                    ),
                )
                if (
                    trace_obj is not None
                    and stage_before is not None
                    and (
                        artifact_plan.suppressed_action_ids
                        or artifact_plan.promoted_families
                        or artifact_plan.user_visible_summary
                    )
                ):
                    trace_obj.record(
                        step_type=TraceStepType.ARTIFACT_SUGGESTION_BIAS_APPLIED,
                        stage_before=stage_before,
                        action="artifact_memory_followup_bias",
                        input_summary=state.get_artifact_memory_summary(),
                        output_summary=artifact_plan.to_dict(),
                        reasoning=(
                            "Applied bounded artifact-memory bias so follow-up suggestions prefer new output forms over repeated deliverables."
                        ),
                    )
        try:
            logger.info(
                "[CapabilityAwareSynthesis] file_context_present=%s summary=%s",
                bool(self._get_file_context_for_synthesis(state)),
                json.dumps(summary, ensure_ascii=False, indent=2),
            )
        except Exception:
            logger.info(
                "[CapabilityAwareSynthesis] file_context_present=%s summary_unserializable",
                bool(self._get_file_context_for_synthesis(state)),
            )
        return summary
```

- 文件：`core/router.py`
- 对象：`UnifiedRouter._synthesize_results`
- 行号：`9777-9840`

```python
    async def _synthesize_results(
        self,
        context,
        original_response,
        tool_results: list,
        capability_summary: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        综合工具执行结果，生成自然语言回复
        """
        short_circuit_text = self._maybe_short_circuit_synthesis(
            tool_results,
            capability_summary=capability_summary,
        )
        if short_circuit_text is not None:
            if len(tool_results) == 1 and tool_results[0].get("name") == "query_knowledge":
                logger.info("[知识检索] 直接返回答案，跳过 synthesis")
            elif any(not item.get("result", {}).get("success") for item in tool_results):
                logger.info("[Synthesis] 检测到工具失败，使用确定性格式化结果")
            elif len(tool_results) == 1:
                only_name = tool_results[0].get("name", "unknown")
                only_result = tool_results[0].get("result", {})
                if only_name in {
                    "query_emission_factors",
                    "calculate_micro_emission",
                    "calculate_macro_emission",
                    "calculate_dispersion",
                    "analyze_hotspots",
                    "render_spatial_map",
                    "analyze_file",
                }:
                    logger.info(f"[Synthesis] 单工具成功({only_name})，使用友好渲染")
                elif only_result.get("summary"):
                    logger.info(f"[Synthesis] 单工具成功({only_name})，直接返回工具summary")
                else:
                    logger.info(f"[Synthesis] 单工具成功({only_name})，工具无summary，使用渲染回退")
            return short_circuit_text

        request = self._build_synthesis_request(
            context.messages[-1]["content"] if context.messages else None,
            tool_results,
            capability_summary=capability_summary,
        )
        results_json = request["results_json"]

        logger.info(f"Filtered results for synthesis ({len(results_json)} chars):")
        logger.info(f"{results_json[:500]}...")  # Log first 500 chars
        logger.info("[CapabilityAwareSynthesis] full_synthesis_prompt:\n%s", request["system_prompt"])

        synthesis_response = await self.llm.chat(
            messages=request["messages"],
            system=request["system_prompt"],
        )

        logger.info(f"Synthesis complete. Response length: {len(synthesis_response.content)} chars")

        hallucination_keywords = ["相当于", "棵树", "峰值出现在", "空调导致", "不完全燃烧"]
        for keyword in self._detect_synthesis_hallucination_keywords(
            synthesis_response.content,
            hallucination_keywords,
        ):
            logger.warning(f"⚠️ Possible hallucination detected: '{keyword}' found in response")

        return synthesis_response.content
```

- 文件：`core/router_synthesis_utils.py`
- 对象：`build_synthesis_request 中 capability_summary 注入代码`
- 行号：`58-81`

```python
    return None


def build_synthesis_request(
    last_user_message: Optional[str],
    tool_results: list[Dict[str, Any]],
    prompt_template: str,
    capability_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the filtered synthesis payload, prompt, and message list."""
    filtered_results = filter_results_for_synthesis(tool_results)
    results_json = json.dumps(filtered_results, ensure_ascii=False, indent=2)
    synthesis_prompt = prompt_template.replace("{results}", results_json)
    capability_prompt = format_capability_summary_for_prompt(capability_summary)
    if capability_prompt:
        synthesis_prompt = f"{synthesis_prompt}\n\n{capability_prompt}"
    else:
        synthesis_prompt = f"{synthesis_prompt}\n\n请生成简洁专业的回答。"
    synthesis_messages = [{"role": "user", "content": last_user_message or "请总结计算结果"}]

    return {
        "filtered_results": filtered_results,
        "results_json": results_json,
        "capability_summary": capability_summary,
```

- 文件：`core/router.py`
- 对象：`UnifiedRouter._state_build_response 中 capability_summary 传入 synthesis 片段`
- 行号：`9367-9396`

```python
            if context is None:
                context = type("StateContext", (), {"messages": [{"content": user_message}]})()
            response_text = getattr(state, "_final_response_text", None)
            frontend_payloads = self._extract_frontend_payloads(state.execution.tool_results)
            capability_summary = self._build_capability_summary_for_synthesis(
                state.execution.tool_results,
                state=state,
                frontend_payloads=frontend_payloads,
                trace_obj=trace_obj,
                stage_before=TaskStage.DONE.value,
            )
            if response_text:
                if trace_obj:
                    synthesis_reason = "LLM produced final response after receiving tool results"
                    if state.latest_summary_delivery_result is not None:
                        synthesis_reason = (
                            "Bounded summary delivery surface produced the final response and payloads."
                        )
                    trace_obj.record(
                        step_type=TraceStepType.SYNTHESIS,
                        stage_before=TaskStage.DONE.value,
                        reasoning=synthesis_reason,
                    )
            else:
                synthesis_context = type("StateContext", (), {"messages": [{"content": user_message}]})()
                response_text = await self._synthesize_results(
                    synthesis_context,
                    state._llm_response,
                    state.execution.tool_results,
                    capability_summary=capability_summary,
```

- 文件：`core/router.py`
- 对象：`UnifiedRouter._process_response 中 capability_summary 传入片段`
- 行号：`9728-9736`

```python
        capability_summary = self._build_capability_summary_for_synthesis(
            tool_results,
            frontend_payloads=frontend_payloads,
        )
        synthesis_text = await self._synthesize_results(
            context,
            response,
            tool_results,
            capability_summary=capability_summary,
```

## 11. 恢复机制概览

### 11.1 `core/input_completion.py`

- `InputCompletionReasonCode` 定义于 `core/input_completion.py:10-13`。

- `InputCompletionOptionType` 定义于 `core/input_completion.py:16-22`，当前策略类型为 `PROVIDE_VALUE`、`USE_DERIVATION`、`UPLOAD_SUPPORTING_FILE`、`DEFAULT_TYPICAL_PROFILE`、`PAUSE`。

- `InputCompletionDecisionType` 定义于 `core/input_completion.py:25-28`，当前决策类型为 `SELECT_OPTION`、`PROVIDE_FREEFORM`、`CANCEL`。

- `InputCompletionRequest` 定义于 `core/input_completion.py:75-177`。

- 触发条件在 `UnifiedRouter._build_input_completion_request()`（`core/router.py:4376-4631`）中：单字段缺失时在 `4535-4545` 返回 `InputCompletionRequest.create(...)`，多字段缺失且 remediation policy 可覆盖时在 `4582-4592` 返回 `InputCompletionRequest.create(...)`，`reason_code == "missing_geometry"` 时在 `4619-4629` 返回 `InputCompletionRequest.create(...)`。

- 文件：`core/input_completion.py`
- 对象：`InputCompletionReasonCode`
- 行号：`10-13`

```python
class InputCompletionReasonCode(str, Enum):
    MISSING_REQUIRED_FIELD = "missing_required_field"
    MISSING_GEOMETRY = "missing_geometry"
    MISSING_METEOROLOGY = "missing_meteorology"
```

- 文件：`core/input_completion.py`
- 对象：`InputCompletionOptionType`
- 行号：`16-22`

```python
class InputCompletionOptionType(str, Enum):
    PROVIDE_UNIFORM_VALUE = "provide_uniform_value"
    USE_DERIVATION = "use_derivation"
    UPLOAD_SUPPORTING_FILE = "upload_supporting_file"
    PAUSE = "pause"
    CHOOSE_PRESET = "choose_preset"
    APPLY_DEFAULT_TYPICAL_PROFILE = "apply_default_typical_profile"
```

- 文件：`core/input_completion.py`
- 对象：`InputCompletionDecisionType`
- 行号：`25-28`

```python
class InputCompletionDecisionType(str, Enum):
    SELECTED_OPTION = "selected_option"
    PAUSE = "pause"
    AMBIGUOUS_REPLY = "ambiguous_reply"
```

- 文件：`core/input_completion.py`
- 对象：`InputCompletionRequest`
- 行号：`75-177`

```python
class InputCompletionRequest:
    request_id: str
    action_id: str
    reason_code: InputCompletionReasonCode
    reason_summary: str
    missing_requirements: List[str] = field(default_factory=list)
    options: List[InputCompletionOption] = field(default_factory=list)
    target_field: Optional[str] = None
    current_task_type: Optional[str] = None
    related_file_context_summary: Optional[str] = None
    repair_hint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "action_id": self.action_id,
            "reason_code": self.reason_code.value,
            "reason_summary": self.reason_summary,
            "missing_requirements": list(self.missing_requirements),
            "options": [option.to_dict() for option in self.options],
            "target_field": self.target_field,
            "current_task_type": self.current_task_type,
            "related_file_context_summary": self.related_file_context_summary,
            "repair_hint": self.repair_hint,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "InputCompletionRequest":
        payload = data if isinstance(data, dict) else {}
        reason_code = payload.get("reason_code") or InputCompletionReasonCode.MISSING_REQUIRED_FIELD.value
        return cls(
            request_id=str(payload.get("request_id") or "").strip(),
            action_id=str(payload.get("action_id") or "").strip(),
            reason_code=InputCompletionReasonCode(reason_code),
            reason_summary=str(payload.get("reason_summary") or "").strip(),
            missing_requirements=[
                str(item).strip()
                for item in (payload.get("missing_requirements") or [])
                if str(item).strip()
            ],
            options=[
                InputCompletionOption.from_dict(item)
                for item in (payload.get("options") or [])
                if isinstance(item, dict)
            ],
            target_field=str(payload.get("target_field")).strip() if payload.get("target_field") is not None else None,
            current_task_type=(
                str(payload.get("current_task_type")).strip()
                if payload.get("current_task_type") is not None
                else None
            ),
            related_file_context_summary=(
                str(payload.get("related_file_context_summary")).strip()
                if payload.get("related_file_context_summary") is not None
                else None
            ),
            repair_hint=str(payload.get("repair_hint")).strip() if payload.get("repair_hint") is not None else None,
        )

    @classmethod
    def create(
        cls,
        *,
        action_id: str,
        reason_code: InputCompletionReasonCode,
        reason_summary: str,
        missing_requirements: Optional[List[str]] = None,
        options: Optional[List[InputCompletionOption]] = None,
        target_field: Optional[str] = None,
        current_task_type: Optional[str] = None,
        related_file_context_summary: Optional[str] = None,
        repair_hint: Optional[str] = None,
    ) -> "InputCompletionRequest":
        suffix = target_field or action_id or reason_code.value
        return cls(
            request_id=f"completion-{suffix}-{uuid.uuid4().hex[:8]}",
            action_id=action_id,
            reason_code=reason_code,
            reason_summary=reason_summary,
            missing_requirements=list(missing_requirements or []),
            options=list(options or []),
            target_field=target_field,
            current_task_type=current_task_type,
            related_file_context_summary=related_file_context_summary,
            repair_hint=repair_hint,
        )

    def get_option(self, option_id: Optional[str]) -> Optional[InputCompletionOption]:
        if not option_id:
            return None
        for option in self.options:
            if option.option_id == option_id:
                return option
        return None

    def get_first_option_by_type(
        self,
        option_type: InputCompletionOptionType,
    ) -> Optional[InputCompletionOption]:
        for option in self.options:
            if option.option_type == option_type and option.applicable:
                return option
        return None
```

- 文件：`core/router.py`
- 对象：`UnifiedRouter._build_input_completion_request 触发片段`
- 行号：`4480-4629`

```python
                    if isinstance(candidate, dict) and candidate.get("source_column"):
                        options.append(
                            InputCompletionOption(
                                option_id=f"{target_field}_use_derivation",
                                option_type=InputCompletionOptionType.USE_DERIVATION,
                                label=f"使用现有列推导 {target_field}",
                                description=(
                                    f"使用列 `{candidate['source_column']}` 作为 `{target_field}` 的受控补全来源。"
                                ),
                                requirements={
                                    "field": target_field,
                                    "source_column": candidate["source_column"],
                                    "derivation": candidate.get("derivation"),
                                },
                                default_hint=candidate["source_column"],
                                aliases=["推导", "用现有列", str(candidate["source_column"])],
                            )
                        )

                if getattr(self.runtime_config, "input_completion_allow_upload_support_file", True):
                    options.append(
                        InputCompletionOption(
                            option_id=f"{target_field}_upload_file",
                            option_type=InputCompletionOptionType.UPLOAD_SUPPORTING_FILE,
                            label="上传更完整的补充文件",
                            description="上传一个包含缺失字段的新文件，系统将用它替换当前缺失输入。",
                            requirements={"field": target_field},
                            aliases=["上传文件", "补充文件", "新文件"],
                        )
                    )

                options.append(
                    InputCompletionOption(
                        option_id=f"{target_field}_pause",
                        option_type=InputCompletionOptionType.PAUSE,
                        label="暂停当前补救",
                        description="暂时不补这个字段，先结束当前动作。",
                        aliases=["暂停", "稍后", "先不做"],
                    )
                )
                if not options:
                    return None
                max_options = max(int(getattr(self.runtime_config, "input_completion_max_options", 4)), 1)
                options = options[:max_options]

                # Build reason summary that aligns diagnostics with completion options
                reason_summary = reason.message
                if policy_option is not None and remediation_policy is not None:
                    all_target = remediation_policy.target_fields
                    if len(all_target) > 1:
                        reason_summary = (
                            f"{reason.message} "
                            f"其中 {'、'.join(all_target)} 可通过默认典型值策略一并补齐。"
                        )

                return InputCompletionRequest.create(
                    action_id=affordance.action_id,
                    reason_code=InputCompletionReasonCode.MISSING_REQUIRED_FIELD,
                    reason_summary=reason_summary,
                    missing_requirements=list(reason.missing_requirements),
                    options=options,
                    target_field=target_field,
                    current_task_type=str(file_context.get("task_type") or "").strip() or None,
                    related_file_context_summary=related_summary,
                    repair_hint=reason.repair_hint,
                )

            # Multi-field missing: only offer policy option if it covers all fields
            if policy_option is not None and remediation_policy is not None:
                covered = set(remediation_policy.target_fields)
                missing_set = set(missing_field_names)
                if missing_set <= covered or (missing_set & covered):
                    options = [policy_option]
                    if getattr(self.runtime_config, "input_completion_allow_upload_support_file", True):
                        options.append(
                            InputCompletionOption(
                                option_id="multi_field_upload_file",
                                option_type=InputCompletionOptionType.UPLOAD_SUPPORTING_FILE,
                                label="上传更完整的补充文件",
                                description="上传包含所有缺失字段的新文件。",
                                requirements={"fields": missing_field_names},
                                aliases=["上传文件", "补充文件", "新文件"],
                            )
                        )
                    options.append(
                        InputCompletionOption(
                            option_id="multi_field_pause",
                            option_type=InputCompletionOptionType.PAUSE,
                            label="暂停当前补救",
                            description="暂时不补这些字段，先结束当前动作。",
                            aliases=["暂停", "稍后", "先不做"],
                        )
                    )
                    max_options = max(int(getattr(self.runtime_config, "input_completion_max_options", 4)), 1)
                    options = options[:max_options]

                    target_fields_list = "、".join(missing_field_names)
                    reason_summary = (
                        f"{reason.message} "
                        f"{target_fields_list} 可通过默认典型值策略一并补齐。"
                    )

                    return InputCompletionRequest.create(
                        action_id=affordance.action_id,
                        reason_code=InputCompletionReasonCode.MISSING_REQUIRED_FIELD,
                        reason_summary=reason_summary,
                        missing_requirements=list(reason.missing_requirements),
                        options=options,
                        target_field=missing_field_names[0],
                        current_task_type=str(file_context.get("task_type") or "").strip() or None,
                        related_file_context_summary=related_summary,
                        repair_hint=reason.repair_hint,
                    )

            return None

        if reason_code == "missing_geometry":
            options = []
            if getattr(self.runtime_config, "input_completion_allow_upload_support_file", True):
                options.append(
                    InputCompletionOption(
                        option_id="geometry_upload_file",
                        option_type=InputCompletionOptionType.UPLOAD_SUPPORTING_FILE,
                        label="上传补充空间文件",
                        description="上传 GIS / GeoJSON / Shapefile，或包含 WKT / 坐标列的新文件。",
                        requirements={"geometry_support": True},
                        aliases=["上传文件", "上传空间文件", "gis", "geojson", "shapefile"],
                    )
                )
            options.append(
                InputCompletionOption(
                    option_id="geometry_pause",
                    option_type=InputCompletionOptionType.PAUSE,
                    label="暂停当前空间动作",
                    description="暂时不补空间数据，先结束当前动作。",
                    aliases=["暂停", "稍后", "先不做"],
                )
            )
            max_options = max(int(getattr(self.runtime_config, "input_completion_max_options", 4)), 1)
            return InputCompletionRequest.create(
                action_id=affordance.action_id,
                reason_code=InputCompletionReasonCode.MISSING_GEOMETRY,
                reason_summary=reason.message,
                missing_requirements=list(reason.missing_requirements),
                options=options[:max_options],
                target_field="geometry",
                current_task_type=str(file_context.get("task_type") or "").strip() or None,
                related_file_context_summary=related_summary,
                repair_hint=reason.repair_hint,
            )
```

### 11.2 `core/geometry_recovery.py`

- 主要公开接口为 `infer_geometry_capability_summary()`（`88-165`）、`build_geometry_recovery_context()`（`363-390`）、`re_ground_with_supporting_spatial_input()`（`408-516`）。

- 触发条件在 `UnifiedRouter._handle_geometry_completion_upload()`（`core/router.py:5106-5558`）中：运行时配置 `enable_geometry_recovery_path` 为真（`5114-5115`），用户通过 input completion 上传支持空间文件后，router 调用 `build_geometry_recovery_context()`（`5204-5211`）和 `re_ground_with_supporting_spatial_input()`（`5274-5280`）。

- 文件：`core/geometry_recovery.py`
- 对象：`infer_geometry_capability_summary`
- 行号：`88-165`

```python
def infer_geometry_capability_summary(
    analysis_dict: Optional[Dict[str, Any]],
    *,
    file_ref: Optional[str] = None,
) -> Dict[str, Any]:
    analysis = dict(analysis_dict or {})
    spatial_metadata = analysis.get("spatial_metadata") or {}
    dataset_roles = [
        dict(item)
        for item in (analysis.get("dataset_roles") or [])
        if isinstance(item, dict)
    ]
    columns = _iter_candidate_columns(analysis)
    geometry_columns = _detect_geometry_columns(columns)
    coordinate_pairs = _detect_coordinate_pairs(columns)
    support_modes: List[str] = []
    notes: List[str] = []

    if isinstance(spatial_metadata, dict) and spatial_metadata:
        support_modes.append("spatial_metadata")
        notes.append("Supporting file exposes bounded spatial metadata.")

    if geometry_columns:
        support_modes.append("geometry_column_signal")
        notes.append(
            "Supporting file exposes geometry-like columns: "
            + ", ".join(geometry_columns[:6])
            + (" ..." if len(geometry_columns) > 6 else "")
        )

    if coordinate_pairs:
        support_modes.append("coordinate_column_pair")
        notes.append(
            "Supporting file exposes bounded coordinate pairs: "
            + ", ".join("/".join(pair) for pair in coordinate_pairs[:4])
        )

    for role in dataset_roles:
        role_name = _safe_lower_text(role.get("role"))
        format_name = _safe_lower_text(role.get("format"))
        if role_name in {"spatial_context", "supporting_spatial_dataset"}:
            support_modes.append("supporting_spatial_role")
            notes.append("Supporting file was recognized as a supporting spatial dataset.")
            break
        if format_name in {"shapefile", "zip_shapefile", "geojson"}:
            support_modes.append("geospatial_format_role")
            notes.append("Supporting file contains a bounded geospatial dataset role.")
            break

    support_modes = sorted({item for item in support_modes if item})
    geometry_types = []
    if isinstance(spatial_metadata, dict):
        geometry_types = [
            str(item)
            for item in (spatial_metadata.get("geometry_types") or [])
            if str(item).strip()
        ]

    has_geometry_support = bool(support_modes)
    if not has_geometry_support:
        notes.append(
            "Bounded analysis did not find spatial metadata, geometry-like columns, or coordinate pairs "
            "that could safely serve as geometry support."
        )

    return {
        "has_geometry_support": has_geometry_support,
        "support_modes": support_modes,
        "recognized_geometry_columns": geometry_columns,
        "coordinate_column_pairs": coordinate_pairs,
        "geometry_types": geometry_types,
        "analysis_confidence": analysis.get("confidence"),
        "analysis_task_type": analysis.get("task_type"),
        "selected_primary_table": analysis.get("selected_primary_table"),
        "dataset_role_count": len(dataset_roles),
        "file_type": _normalize_file_type(file_ref, analysis.get("format")),
        "notes": notes,
    }
```

- 文件：`core/geometry_recovery.py`
- 对象：`build_geometry_recovery_context`
- 行号：`363-390`

```python
def build_geometry_recovery_context(
    *,
    primary_file_ref: Optional[str],
    supporting_spatial_input: SupportingSpatialInput,
    target_action_id: Optional[str],
    target_task_type: Optional[str],
    residual_plan_summary: Optional[str],
    readiness_before: Optional[Dict[str, Any]] = None,
) -> GeometryRecoveryContext:
    notes = [
        "Bounded geometry recovery paired the primary file with one supporting spatial input."
    ]
    if supporting_spatial_input.geometry_capability_summary.get("notes"):
        notes.extend(
            str(item)
            for item in supporting_spatial_input.geometry_capability_summary.get("notes", [])
            if str(item).strip()
        )
    return GeometryRecoveryContext(
        primary_file_ref=primary_file_ref,
        supporting_spatial_input=supporting_spatial_input,
        target_action_id=target_action_id,
        target_task_type=target_task_type,
        residual_plan_summary=residual_plan_summary,
        recovery_status=GeometryRecoveryStatus.ATTACHED.value,
        re_grounding_notes=notes,
        readiness_before=dict(readiness_before or {}) or None,
    )
```

- 文件：`core/geometry_recovery.py`
- 对象：`re_ground_with_supporting_spatial_input`
- 行号：`408-516`

```python
def re_ground_with_supporting_spatial_input(
    *,
    primary_file_context: Optional[Dict[str, Any]],
    supporting_spatial_input: SupportingSpatialInput,
    target_action_id: Optional[str],
    target_task_type: Optional[str],
    residual_plan_summary: Optional[str],
) -> GeometryReGroundingResult:
    primary = dict(primary_file_context or {})
    support_summary = dict(supporting_spatial_input.geometry_capability_summary or {})
    if not support_summary.get("has_geometry_support"):
        failure_reason = (
            "The uploaded supporting file was analyzed, but it did not expose usable geometry support "
            "signals for bounded recovery."
        )
        return GeometryReGroundingResult(
            success=False,
            updated_file_context=primary,
            geometry_support_established=False,
            canonical_signals={"has_geometry_support": False, "geometry_support_source": None},
            re_grounding_notes=[failure_reason],
            geometry_support_facts=[],
            upstream_recompute_recommendation=None,
            failure_reason=failure_reason,
        )

    updated = dict(primary)
    geometry_support_facts = [
        f"supporting_file={supporting_spatial_input.file_name}",
        "geometry_support=available",
        "geometry_support_source=supporting_spatial_input",
    ]
    support_modes = list(support_summary.get("support_modes") or [])
    if support_modes:
        geometry_support_facts.append("support_modes=" + ",".join(support_modes))

    notes = [
        "Re-grounded the current task against the primary file plus one supporting spatial input.",
        (
            f"Primary file remained {primary.get('file_path') or 'unknown'}, while "
            f"{supporting_spatial_input.file_name} was attached as bounded geometry support."
        ),
    ]
    notes.extend(
        str(item)
        for item in support_summary.get("notes", [])
        if str(item).strip()
    )

    merged_roles = [
        dict(item)
        for item in (updated.get("dataset_roles") or [])
        if isinstance(item, dict)
    ]
    merged_roles.append(
        {
            "dataset_name": supporting_spatial_input.file_name,
            "role": "supporting_spatial_dataset",
            "format": supporting_spatial_input.file_type,
            "task_type": target_task_type,
            "confidence": support_summary.get("analysis_confidence"),
            "selected": False,
            "reason": "Attached through structured geometry completion as bounded spatial support.",
        }
    )

    updated["dataset_roles"] = merged_roles
    updated["spatial_context"] = {
        "mode": "supporting_spatial_input",
        "primary_file_ref": updated.get("file_path"),
        "supporting_file_ref": supporting_spatial_input.file_ref,
        "supporting_file_name": supporting_spatial_input.file_name,
        "supporting_file_type": supporting_spatial_input.file_type,
        "source": supporting_spatial_input.source,
        "geometry_capability_summary": support_summary,
        "spatial_metadata": dict(supporting_spatial_input.spatial_metadata or {}),
        "dataset_roles": [dict(item) for item in supporting_spatial_input.dataset_roles],
        "target_action_id": target_action_id,
        "target_task_type": target_task_type,
        "residual_plan_summary": residual_plan_summary,
    }
    updated["supporting_spatial_input"] = supporting_spatial_input.to_dict()
    updated["geometry_recovery_pairing"] = {
        "mode": "bounded_primary_plus_supporting_spatial_input",
        "primary_file_ref": updated.get("file_path"),
        "supporting_file_ref": supporting_spatial_input.file_ref,
    }

    canonical_signals = {
        "has_geometry_support": True,
        "geometry_support_source": "supporting_spatial_input",
        "support_modes": support_modes,
        "supporting_file_type": supporting_spatial_input.file_type,
        "target_action_id": target_action_id,
    }

    return GeometryReGroundingResult(
        success=True,
        updated_file_context=updated,
        geometry_support_established=True,
        canonical_signals=canonical_signals,
        re_grounding_notes=notes,
        geometry_support_facts=geometry_support_facts,
        upstream_recompute_recommendation=_build_upstream_recompute_recommendation(
            target_action_id,
            target_task_type,
        ),
        failure_reason=None,
    )
```

- 文件：`core/router.py`
- 对象：`UnifiedRouter._handle_geometry_completion_upload 触发片段`
- 行号：`5106-5406`

```python
    async def _handle_geometry_completion_upload(
        self,
        state: TaskState,
        request: InputCompletionRequest,
        decision: InputCompletionDecision,
        *,
        trace_obj: Optional[Trace] = None,
    ) -> bool:
        if not getattr(self.runtime_config, "enable_geometry_recovery_path", True):
            return False

        bundle = self._ensure_live_input_completion_bundle()
        self._set_residual_reentry_context(state, None)
        file_ref = str((decision.structured_payload or {}).get("file_ref") or "").strip()
        primary_file_ref = (
            str(bundle.get("file_path") or "").strip()
            or str(state.file_context.file_path or "").strip()
            or None
        )
        readiness_before = {
            "status": ReadinessStatus.REPAIRABLE.value,
            "reason_code": InputCompletionReasonCode.MISSING_GEOMETRY.value,
        }

        if not primary_file_ref:
            error_message = "Geometry recovery requires an existing primary file before a supporting spatial file can be attached."
            prompt_text = format_input_completion_prompt(
                request,
                retry_message=error_message,
            )
            state.control.needs_user_input = True
            state.control.input_completion_prompt = prompt_text
            self._transition_state(
                state,
                TaskStage.NEEDS_INPUT_COMPLETION,
                reason="Geometry recovery had no primary file context to repair",
                trace_obj=trace_obj,
            )
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.GEOMETRY_RE_GROUNDING_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action=request.action_id,
                    reasoning=error_message,
                )
                trace_obj.record(
                    step_type=TraceStepType.INPUT_COMPLETION_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    stage_after=TaskStage.NEEDS_INPUT_COMPLETION.value,
                    action=request.action_id,
                    input_summary={"request_id": request.request_id, "user_reply": decision.user_reply},
                    reasoning=error_message,
                )
            return True

        supported, detected_type, support_error = self._is_supported_geometry_recovery_file(file_ref)
        if supported:
            supporting_analysis = await self._analyze_supporting_spatial_file(file_ref)
            supporting_spatial_input = SupportingSpatialInput.from_analysis(
                file_ref=file_ref,
                source="input_completion_upload",
                analysis_dict=supporting_analysis,
            )
        else:
            supporting_spatial_input = SupportingSpatialInput(
                file_ref=file_ref,
                file_name=Path(file_ref).name if file_ref else "",
                file_type=detected_type,
                source="input_completion_upload",
                geometry_capability_summary={
                    "has_geometry_support": False,
                    "support_modes": [],
                    "notes": [support_error] if support_error else [],
                    "file_type": detected_type,
                },
                dataset_roles=[],
                spatial_metadata={},
            )
            supporting_analysis = {}

        state.set_supporting_spatial_input(supporting_spatial_input)
        bundle["supporting_spatial_input"] = supporting_spatial_input.to_dict()
        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.GEOMETRY_COMPLETION_ATTACHED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action=request.action_id,
                input_summary={
                    "source": supporting_spatial_input.source,
                    "target_action_id": request.action_id,
                },
                output_summary=supporting_spatial_input.to_summary(),
                reasoning=(
                    f"Attached supporting spatial file {supporting_spatial_input.file_name or file_ref} "
                    f"for repairable geometry recovery."
                ),
            )

        recovery_context = build_geometry_recovery_context(
            primary_file_ref=primary_file_ref,
            supporting_spatial_input=supporting_spatial_input,
            target_action_id=request.action_id,
            target_task_type=request.current_task_type,
            residual_plan_summary=str(bundle.get("residual_plan_summary") or "").strip() or None,
            readiness_before=readiness_before,
        )
        state.set_geometry_recovery_context(recovery_context)
        bundle["geometry_recovery_context"] = recovery_context.to_dict()

        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.GEOMETRY_RE_GROUNDING_TRIGGERED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action=request.action_id,
                input_summary={
                    "primary_file_ref": primary_file_ref,
                    "supporting_file_ref": supporting_spatial_input.file_ref,
                    "target_task_type": request.current_task_type,
                },
                output_summary={
                    "supporting_file_type": supporting_spatial_input.file_type,
                    "support_modes": supporting_spatial_input.geometry_capability_summary.get("support_modes"),
                },
                reasoning=(
                    "Triggered bounded geometry re-grounding with the current primary file plus one supporting spatial file."
                ),
            )

        if support_error:
            recovery_context.recovery_status = GeometryRecoveryStatus.FAILED.value
            recovery_context.failure_reason = support_error
            state.set_geometry_recovery_context(recovery_context)
            bundle["geometry_recovery_context"] = recovery_context.to_dict()
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.GEOMETRY_RE_GROUNDING_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action=request.action_id,
                    input_summary={"supporting_file_ref": file_ref},
                    reasoning=support_error,
                )
            prompt_text = format_input_completion_prompt(
                request,
                retry_message=support_error,
            )
            state.control.needs_user_input = True
            state.control.input_completion_prompt = prompt_text
            self._transition_state(
                state,
                TaskStage.NEEDS_INPUT_COMPLETION,
                reason="Supporting spatial file type was not eligible for bounded geometry recovery",
                trace_obj=trace_obj,
            )
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.INPUT_COMPLETION_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    stage_after=TaskStage.NEEDS_INPUT_COMPLETION.value,
                    action=request.action_id,
                    input_summary={"request_id": request.request_id, "user_reply": decision.user_reply},
                    reasoning=support_error,
                )
            return True

        primary_file_context = self._get_file_context_for_synthesis(state) or {}
        if primary_file_ref:
            primary_file_context["file_path"] = primary_file_ref

        re_grounding_result = re_ground_with_supporting_spatial_input(
            primary_file_context=primary_file_context,
            supporting_spatial_input=supporting_spatial_input,
            target_action_id=request.action_id,
            target_task_type=request.current_task_type,
            residual_plan_summary=str(bundle.get("residual_plan_summary") or "").strip() or None,
        )

        if not re_grounding_result.success:
            recovery_context.recovery_status = GeometryRecoveryStatus.FAILED.value
            recovery_context.failure_reason = re_grounding_result.failure_reason
            recovery_context.re_grounding_notes = list(re_grounding_result.re_grounding_notes)
            state.set_geometry_recovery_context(recovery_context)
            bundle["geometry_recovery_context"] = recovery_context.to_dict()
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.GEOMETRY_RE_GROUNDING_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action=request.action_id,
                    input_summary={
                        "primary_file_ref": primary_file_ref,
                        "supporting_file_ref": supporting_spatial_input.file_ref,
                    },
                    output_summary={
                        "supporting_file_summary": supporting_spatial_input.to_summary(),
                    },
                    reasoning=re_grounding_result.failure_reason
                    or "Supporting file did not establish bounded geometry support.",
                )
            prompt_text = format_input_completion_prompt(
                request,
                retry_message=re_grounding_result.failure_reason,
            )
            state.control.needs_user_input = True
            state.control.input_completion_prompt = prompt_text
            self._transition_state(
                state,
                TaskStage.NEEDS_INPUT_COMPLETION,
                reason="Geometry re-grounding did not restore bounded geometry support",
                trace_obj=trace_obj,
            )
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.INPUT_COMPLETION_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    stage_after=TaskStage.NEEDS_INPUT_COMPLETION.value,
                    action=request.action_id,
                    input_summary={"request_id": request.request_id, "user_reply": decision.user_reply},
                    reasoning=re_grounding_result.failure_reason or "Geometry re-grounding failed.",
                )
            return True

        updated_file_context = dict(re_grounding_result.updated_file_context)
        updated_file_context["file_path"] = primary_file_ref
        state.update_file_context(updated_file_context)
        setattr(state, "_file_analysis_cache", updated_file_context)
        bundle["recovered_file_context"] = updated_file_context

        recovery_context.recovery_status = GeometryRecoveryStatus.RE_GROUNDED.value
        recovery_context.re_grounding_notes = list(re_grounding_result.re_grounding_notes)
        state.set_geometry_recovery_context(recovery_context)
        bundle["geometry_recovery_context"] = recovery_context.to_dict()

        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.GEOMETRY_RE_GROUNDING_APPLIED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action=request.action_id,
                input_summary={
                    "primary_file_ref": primary_file_ref,
                    "supporting_file_ref": supporting_spatial_input.file_ref,
                },
                output_summary={
                    "geometry_support_facts": list(re_grounding_result.geometry_support_facts),
                    "canonical_signals": dict(re_grounding_result.canonical_signals),
                },
                reasoning="Applied bounded file-aware re-grounding and refreshed geometry-support facts in the current task context.",
            )

        assessment = None
        if getattr(self.runtime_config, "geometry_recovery_require_readiness_refresh", True):
            assessment = self._build_readiness_assessment(
                state.execution.tool_results,
                state=state,
                frontend_payloads=self._extract_frontend_payloads(state.execution.tool_results),
                trace_obj=None,
                stage_before=None,
                purpose="input_completion_recheck",
            )
        affordance = assessment.get_action(request.action_id) if assessment is not None else None
        readiness_refresh_result = self._build_geometry_readiness_refresh_result(
            request=request,
            affordance=affordance,
            assessment=assessment,
        )
        state.set_geometry_readiness_refresh_result(readiness_refresh_result)
        bundle["readiness_refresh_result"] = readiness_refresh_result

        recovery_context.readiness_after = dict(readiness_refresh_result)
        reentry_context: Optional[RecoveredWorkflowReentryContext] = None
        if affordance is not None and affordance.status == ReadinessStatus.READY:
            recovery_context.recovery_status = GeometryRecoveryStatus.RESUMABLE.value
            recovery_context.resume_hint = (
                f"Geometry support is now available; the repaired workflow can resume with `{request.action_id}` on the next turn."
            )
            recovery_context.upstream_recompute_recommendation = (
                re_grounding_result.upstream_recompute_recommendation
            )
            if getattr(self.runtime_config, "enable_residual_reentry_controller", True):
                reentry_plan = ExecutionPlan.from_dict(bundle.get("plan")) if isinstance(bundle.get("plan"), dict) else None
                reentry_context = build_recovered_workflow_reentry_context(
                    geometry_recovery_context=recovery_context,
                    readiness_refresh_result=readiness_refresh_result,
                    residual_plan=reentry_plan,
                    residual_plan_summary=str(bundle.get("residual_plan_summary") or "").strip() or None,
                    prioritize_recovery_target=getattr(
                        self.runtime_config,
                        "residual_reentry_prioritize_recovery_target",
                        True,
                    ),
                )
                self._set_residual_reentry_context(state, reentry_context)
        else:
            reason_message = (
                affordance.reason.message
                if affordance is not None and affordance.reason is not None
                else "Readiness refresh did not turn the target action into ready."
            )
            recovery_context.recovery_status = GeometryRecoveryStatus.FAILED.value
            recovery_context.failure_reason = reason_message
            self._set_residual_reentry_context(state, None)
        state.set_geometry_recovery_context(recovery_context)
        bundle["geometry_recovery_context"] = recovery_context.to_dict()
```

### 11.3 `core/residual_reentry.py`

- 主要公开接口为 `build_residual_reentry_target()`（`247-319`）、`build_reentry_guidance_summary()`（`322-350`）、`build_recovered_workflow_reentry_context()`（`353-379`）。

- 触发条件分两段：在 geometry recovery 完成且 readiness refresh 后，如果目标动作已变为 `READY` 且 `enable_residual_reentry_controller` 为真，router 在 `core/router.py:5382-5395` 调用 `build_recovered_workflow_reentry_context(...)` 建立 residual re-entry 上下文；后续 turn 中 `UnifiedRouter._build_residual_reentry_decision()`（`core/router.py:4941-5021`）要求已有 `state.residual_reentry_context`、`continuation_decision.should_continue` 为真，且在 `4999-5014` 可选地要求目标动作再次通过 readiness 校验。

- 文件：`core/residual_reentry.py`
- 对象：`build_residual_reentry_target`
- 行号：`247-319`

```python
def build_residual_reentry_target(
    *,
    geometry_recovery_context: GeometryRecoveryContext,
    residual_plan: Optional[ExecutionPlan] = None,
    prioritize_recovery_target: bool = True,
) -> ResidualReentryTarget:
    action_id = geometry_recovery_context.target_action_id
    catalog_entry = _catalog_entry_by_action_id(action_id)
    target_tool_name = catalog_entry.tool_name if catalog_entry is not None else None
    target_tool_arguments = dict(getattr(catalog_entry, "arguments", {}) or {})
    display_name = getattr(catalog_entry, "display_name", None) if catalog_entry is not None else None
    source = "geometry_recovery"
    priority = 100 if prioritize_recovery_target else 80

    next_step = residual_plan.get_next_pending_step() if residual_plan is not None else None
    matched_step = _find_matching_pending_step(
        residual_plan,
        target_action_id=action_id,
        target_tool_name=target_tool_name,
    )

    target_step_id = None
    residual_plan_relationship = "no_residual_plan"
    matches_next_pending_step = False

    if next_step is not None and matched_step is not None and matched_step.step_id == next_step.step_id:
        target_step_id = next_step.step_id
        target_tool_name = next_step.tool_name
        target_tool_arguments = dict(next_step.argument_hints or {}) or target_tool_arguments
        residual_plan_relationship = "aligned_with_next_pending_step"
        matches_next_pending_step = True
    elif matched_step is not None:
        target_step_id = matched_step.step_id
        target_tool_name = matched_step.tool_name
        target_tool_arguments = dict(matched_step.argument_hints or {}) or target_tool_arguments
        residual_plan_relationship = "recovered_target_within_residual_plan"
    elif next_step is not None:
        residual_plan_relationship = "recovery_target_prioritized_over_next_pending_step"
        if not prioritize_recovery_target:
            target_step_id = next_step.step_id
            target_tool_name = next_step.tool_name
            target_tool_arguments = dict(next_step.argument_hints or {})
            action_id = map_tool_call_to_action_id(next_step.tool_name, next_step.argument_hints) or action_id
            fallback_entry = _catalog_entry_by_action_id(action_id)
            if fallback_entry is not None:
                display_name = fallback_entry.display_name
            source = "continuation"
            priority = 80
            residual_plan_relationship = "fallback_next_pending_step"

    if residual_plan_relationship == "aligned_with_next_pending_step":
        reason = "The repaired geometry target matched the next pending residual step, so it was bound as the primary re-entry target."
    elif residual_plan_relationship == "recovered_target_within_residual_plan":
        reason = "The repaired geometry target remained within the residual workflow and was promoted as the primary re-entry target."
    elif residual_plan_relationship == "recovery_target_prioritized_over_next_pending_step":
        reason = "The repaired geometry target remained the preferred re-entry target even though the residual next pending step summary was retained."
    elif residual_plan_relationship == "fallback_next_pending_step":
        reason = "The re-entry controller fell back to the next pending residual step because recovery-target prioritization was disabled."
    else:
        reason = "The repaired action became the sole bounded re-entry target because no residual plan was available."

    return ResidualReentryTarget(
        target_action_id=action_id,
        target_tool_name=target_tool_name,
        target_step_id=target_step_id,
        source=source,
        reason=reason,
        priority=priority,
        target_tool_arguments=target_tool_arguments,
        display_name=display_name,
        residual_plan_relationship=residual_plan_relationship,
        matches_next_pending_step=matches_next_pending_step,
    )
```

- 文件：`core/residual_reentry.py`
- 对象：`build_reentry_guidance_summary`
- 行号：`322-350`

```python
def build_reentry_guidance_summary(
    *,
    reentry_target: ResidualReentryTarget,
    residual_plan_summary: Optional[str],
    geometry_recovery_context: GeometryRecoveryContext,
) -> str:
    target_name = reentry_target.display_name or reentry_target.target_action_id or "recovered_action"
    lines = ["[Recovered workflow re-entry target]"]
    lines.append(
        "This workflow was previously repaired through bounded geometry recovery. Treat the recovered target below as the highest-priority continuation hint for this turn."
    )
    lines.append(
        f"Primary re-entry target: {target_name} -> {reentry_target.target_tool_name or 'unknown_tool'}"
    )
    if reentry_target.target_step_id:
        lines.append(f"Recovered target step: {reentry_target.target_step_id}")
    lines.append(f"Target source: {reentry_target.source}")
    if reentry_target.residual_plan_relationship:
        lines.append(
            f"Residual-plan relationship: {reentry_target.residual_plan_relationship}"
        )
    if residual_plan_summary:
        lines.append(f"Residual workflow summary: {residual_plan_summary}")
    if geometry_recovery_context.resume_hint:
        lines.append(f"Recovery resume hint: {geometry_recovery_context.resume_hint}")
    lines.append(
        "Tool-selection rule: prefer this recovered target before other residual steps when the user is continuing the same workflow. Do not auto-execute and do not replay the whole workflow."
    )
    return "\n".join(lines)
```

- 文件：`core/residual_reentry.py`
- 对象：`build_recovered_workflow_reentry_context`
- 行号：`353-379`

```python
def build_recovered_workflow_reentry_context(
    *,
    geometry_recovery_context: GeometryRecoveryContext,
    readiness_refresh_result: Optional[Dict[str, Any]],
    residual_plan: Optional[ExecutionPlan] = None,
    residual_plan_summary: Optional[str] = None,
    prioritize_recovery_target: bool = True,
) -> RecoveredWorkflowReentryContext:
    target = build_residual_reentry_target(
        geometry_recovery_context=geometry_recovery_context,
        residual_plan=residual_plan,
        prioritize_recovery_target=prioritize_recovery_target,
    )
    summary = residual_plan_summary or geometry_recovery_context.residual_plan_summary
    return RecoveredWorkflowReentryContext(
        reentry_target=target,
        residual_plan_summary=summary,
        geometry_recovery_context=geometry_recovery_context,
        readiness_refresh_result=dict(readiness_refresh_result or {}) or None,
        reentry_status=ReentryStatus.TARGET_SET.value,
        reentry_guidance_summary=build_reentry_guidance_summary(
            reentry_target=target,
            residual_plan_summary=summary,
            geometry_recovery_context=geometry_recovery_context,
        ),
        last_decision_reason=target.reason,
    )
```

- 文件：`core/router.py`
- 对象：`UnifiedRouter._build_residual_reentry_decision`
- 行号：`4941-5021`

```python
    def _build_residual_reentry_decision(
        self,
        state: TaskState,
        continuation_decision: Optional[ContinuationDecision],
    ) -> Optional[ReentryDecision]:
        if not getattr(self.runtime_config, "enable_residual_reentry_controller", True):
            return None

        reentry_context = state.residual_reentry_context
        if reentry_context is None:
            return None

        target = reentry_context.reentry_target
        if target is None:
            return ReentryDecision(
                should_apply=False,
                decision_status="skipped",
                reason="Recovered workflow had no formal re-entry target.",
                source="geometry_recovery",
                residual_plan_exists=bool(continuation_decision and continuation_decision.residual_plan_exists),
            )

        guidance_summary = build_reentry_guidance_summary(
            reentry_target=target,
            residual_plan_summary=(
                continuation_decision.residual_plan_summary
                if continuation_decision and continuation_decision.residual_plan_summary
                else reentry_context.residual_plan_summary
            ),
            geometry_recovery_context=reentry_context.geometry_recovery_context,
        )

        decision = ReentryDecision(
            should_apply=False,
            decision_status="skipped",
            target=target,
            source=target.source,
            guidance_summary=guidance_summary,
            continuation_signal=continuation_decision.signal if continuation_decision else None,
            new_task_override=bool(continuation_decision and continuation_decision.new_task_override),
            residual_plan_exists=bool(continuation_decision and continuation_decision.residual_plan_exists),
        )

        if continuation_decision is None:
            decision.reason = "No continuation decision was available for the recovered workflow."
            return decision

        if continuation_decision.new_task_override:
            decision.reason = "The user explicitly started a new task, so recovered-workflow re-entry bias was skipped."
            return decision

        if not continuation_decision.should_continue:
            decision.reason = (
                continuation_decision.reason
                or "The new turn did not safely continue the recovered workflow."
            )
            return decision

        if (
            getattr(self.runtime_config, "residual_reentry_require_ready_target", True)
            and target.target_action_id
        ):
            _assessment, affordance, target_ready = self._evaluate_reentry_target_readiness(
                state,
                reentry_context,
            )
            decision.target_ready = target_ready
            decision.readiness_status = affordance.status.value if affordance is not None else None
            if target_ready is not True:
                decision.decision_status = "stale"
                decision.reason = (
                    "Recovered re-entry target was not re-validated as ready on the new turn, so the bias was skipped."
                )
                return decision

        decision.should_apply = True
        decision.decision_status = "applied"
        decision.reason = (
            "Recovered workflow continuation stayed on-task, so the next turn was deterministically biased toward the repaired target action."
        )
        return decision
```

- 文件：`core/router.py`
- 对象：`UnifiedRouter._handle_geometry_completion_upload 中 residual reentry 建立片段`
- 行号：`5372-5395`

```python
        recovery_context.readiness_after = dict(readiness_refresh_result)
        reentry_context: Optional[RecoveredWorkflowReentryContext] = None
        if affordance is not None and affordance.status == ReadinessStatus.READY:
            recovery_context.recovery_status = GeometryRecoveryStatus.RESUMABLE.value
            recovery_context.resume_hint = (
                f"Geometry support is now available; the repaired workflow can resume with `{request.action_id}` on the next turn."
            )
            recovery_context.upstream_recompute_recommendation = (
                re_grounding_result.upstream_recompute_recommendation
            )
            if getattr(self.runtime_config, "enable_residual_reentry_controller", True):
                reentry_plan = ExecutionPlan.from_dict(bundle.get("plan")) if isinstance(bundle.get("plan"), dict) else None
                reentry_context = build_recovered_workflow_reentry_context(
                    geometry_recovery_context=recovery_context,
                    readiness_refresh_result=readiness_refresh_result,
                    residual_plan=reentry_plan,
                    residual_plan_summary=str(bundle.get("residual_plan_summary") or "").strip() or None,
                    prioritize_recovery_target=getattr(
                        self.runtime_config,
                        "residual_reentry_prioritize_recovery_target",
                        True,
                    ),
                )
                self._set_residual_reentry_context(state, reentry_context)
```

### 11.4 `core/supplemental_merge.py`

- 主要公开接口为 `build_supplemental_merge_plan()`（`680-763`）、`execute_supplemental_merge()`（`783-966`）、`apply_supplemental_merge_analysis_refresh()`（`982-1081`）。

- 触发条件位于 `UnifiedRouter._handle_supplemental_merge()`（`core/router.py:2129-2436`）：trace 中明确写明 file-relationship resolver 将上传分类为 `merge_supplemental_columns` 后进入该路径（`2145-2157`），随后依次调用 `build_supplemental_merge_plan()`（`2160-2163`）、`execute_supplemental_merge()`（`2218-2222`）、`apply_supplemental_merge_analysis_refresh()`（`2292-2296`）。

- 文件：`core/supplemental_merge.py`
- 对象：`build_supplemental_merge_plan`
- 行号：`680-763`

```python
def build_supplemental_merge_plan(
    context: SupplementalMergeContext,
    *,
    allow_alias_keys: bool = True,
) -> SupplementalMergePlan:
    primary_file_ref = (
        _clean_text(context.primary_file_analysis.get("file_path"))
        or _clean_text(context.primary_file_summary.get("file_path"))
    )
    supplemental_file_ref = (
        _clean_text(context.supplemental_file_analysis.get("file_path"))
        or _clean_text(context.supplemental_file_summary.get("file_path"))
    )
    target_missing_fields = (
        list(context.target_missing_canonical_fields)
        or _extract_missing_fields(_clean_dict(context.primary_file_analysis.get("missing_field_diagnostics")))
    )

    plan = SupplementalMergePlan(
        primary_file_ref=primary_file_ref,
        supplemental_file_ref=supplemental_file_ref,
        merge_mode="left_join_by_key",
        preconditions=[],
        plan_status="unavailable",
    )

    if not primary_file_ref or not supplemental_file_ref:
        plan.failure_reason = "Supplemental merge requires both a primary file and a supplemental file reference."
        plan.preconditions.append(plan.failure_reason)
        return plan

    if not target_missing_fields:
        plan.failure_reason = (
            "The current primary file did not expose unresolved canonical fields, "
            "so there was no bounded merge target."
        )
        plan.preconditions.append(plan.failure_reason)
        return plan

    merge_key = _choose_merge_key(context, allow_alias_keys=allow_alias_keys)
    if merge_key is None:
        plan.failure_reason = (
            "The supplemental file did not expose a reliable key that could be aligned "
            "to the current primary file."
        )
        plan.preconditions.append(plan.failure_reason)
        return plan

    attachments = _resolve_attachment_candidates(context, allow_alias_keys=allow_alias_keys)
    if not attachments:
        plan.failure_reason = (
            "The supplemental file did not contain columns that matched the current missing canonical fields."
        )
        plan.preconditions.append(plan.failure_reason)
        plan.merge_keys = [merge_key]
        return plan

    plan.merge_keys = [merge_key]
    plan.attachments = attachments
    plan.candidate_columns_to_import = _dedupe_strings(
        attachment.supplemental_column for attachment in attachments if attachment.supplemental_column
    )
    plan.canonical_targets = {
        attachment.canonical_field: attachment.target_column
        for attachment in attachments
        if attachment.canonical_field and attachment.target_column
    }
    plan.plan_status = "ready"
    plan.preconditions.extend(
        [
            f"bounded_key_alignment:{merge_key.primary_column}->{merge_key.supplemental_column}",
            "bounded_target_import_only",
        ]
    )
    unresolved_fields = [
        field_name
        for field_name in target_missing_fields
        if field_name not in plan.canonical_targets
    ]
    if unresolved_fields:
        plan.preconditions.append(
            "remaining_missing_targets:" + ",".join(sorted(unresolved_fields))
        )
    return plan
```

- 文件：`core/supplemental_merge.py`
- 对象：`execute_supplemental_merge`
- 行号：`783-966`

```python
def execute_supplemental_merge(
    plan: SupplementalMergePlan,
    *,
    outputs_dir: Path,
    session_id: Optional[str] = None,
) -> SupplementalMergeResult:
    if plan.plan_status != "ready":
        return SupplementalMergeResult(
            success=False,
            failure_reason=plan.failure_reason or "Supplemental merge plan was not executable.",
        )

    if not plan.merge_keys:
        return SupplementalMergeResult(
            success=False,
            failure_reason="Supplemental merge plan was missing a bounded merge key.",
        )

    merge_key = plan.merge_keys[0]
    primary_df, primary_error = _read_tabular_file(plan.primary_file_ref)
    if primary_error:
        return SupplementalMergeResult(success=False, failure_reason=primary_error)

    supplemental_df, supplemental_error = _read_tabular_file(plan.supplemental_file_ref)
    if supplemental_error:
        return SupplementalMergeResult(success=False, failure_reason=supplemental_error)

    assert primary_df is not None
    assert supplemental_df is not None

    if merge_key.primary_column not in primary_df.columns:
        return SupplementalMergeResult(
            success=False,
            failure_reason=(
                f"Primary merge key '{merge_key.primary_column}' was not present in the primary file."
            ),
        )
    if merge_key.supplemental_column not in supplemental_df.columns:
        return SupplementalMergeResult(
            success=False,
            failure_reason=(
                f"Supplemental merge key '{merge_key.supplemental_column}' was not present in the supplemental file."
            ),
        )

    import_columns = [
        attachment.supplemental_column
        for attachment in plan.attachments
        if attachment.supplemental_column
    ]
    unique_import_columns = _dedupe_strings(import_columns)
    if not unique_import_columns:
        return SupplementalMergeResult(
            success=False,
            failure_reason="No bounded supplemental columns were selected for import.",
        )

    for column in unique_import_columns:
        if column not in supplemental_df.columns:
            return SupplementalMergeResult(
                success=False,
                failure_reason=f"Supplemental import column '{column}' was not present in the supplemental file.",
            )

    primary_work = primary_df.copy()
    supplemental_work = supplemental_df.copy()
    primary_work["__merge_key__"] = primary_work[merge_key.primary_column].apply(_normalize_merge_key_value)
    supplemental_work["__merge_key__"] = supplemental_work[merge_key.supplemental_column].apply(_normalize_merge_key_value)

    primary_non_null_key_count = int(primary_work["__merge_key__"].notna().sum())
    supplemental_non_null_key_count = int(supplemental_work["__merge_key__"].notna().sum())
    if primary_non_null_key_count == 0:
        return SupplementalMergeResult(
            success=False,
            failure_reason="Primary merge key values were empty, so a bounded row alignment could not be established.",
        )
    if supplemental_non_null_key_count == 0:
        return SupplementalMergeResult(
            success=False,
            failure_reason="Supplemental merge key values were empty, so a bounded row alignment could not be established.",
        )

    duplicates = supplemental_work.loc[
        supplemental_work["__merge_key__"].notna(),
        "__merge_key__",
    ].duplicated(keep=False)
    if bool(duplicates.any()):
        return SupplementalMergeResult(
            success=False,
            failure_reason=(
                "Supplemental merge key values were not unique, so the bounded merge path could not "
                "safely align rows."
            ),
        )

    rename_map: Dict[str, str] = {}
    for attachment in plan.attachments:
        if not attachment.supplemental_column or not attachment.canonical_field:
            continue
        rename_map[attachment.supplemental_column] = f"__supp_{attachment.canonical_field}"

    supplemental_subset = supplemental_work[["__merge_key__", *unique_import_columns]].copy()
    supplemental_subset = supplemental_subset.rename(columns=rename_map)

    merged_df = primary_work.merge(
        supplemental_subset,
        on="__merge_key__",
        how="left",
    )

    attachments: List[SupplementalColumnAttachment] = []
    merged_columns: List[str] = []
    matched_rows = 0
    for attachment in plan.attachments:
        imported_column = rename_map.get(attachment.supplemental_column or "")
        target_column = attachment.target_column
        if not imported_column or not target_column:
            continue

        imported_series = merged_df[imported_column]
        if target_column in merged_df.columns:
            merged_df[target_column] = merged_df[target_column].where(
                merged_df[target_column].notna(),
                imported_series,
            )
        else:
            merged_df[target_column] = imported_series

        non_null_count = int(merged_df[target_column].notna().sum())
        coverage_ratio = (
            round(non_null_count / max(len(primary_df), 1), 4)
            if len(primary_df) > 0
            else 0.0
        )
        matched_rows = max(matched_rows, int(imported_series.notna().sum()))
        cloned = SupplementalColumnAttachment.from_dict(attachment.to_dict())
        cloned.status = "imported" if non_null_count > 0 else "unmatched"
        cloned.coverage_ratio = coverage_ratio
        cloned.non_null_value_count = non_null_count
        attachments.append(cloned)
        if non_null_count > 0 and target_column not in merged_columns:
            merged_columns.append(target_column)

    if matched_rows == 0 or not merged_columns:
        return SupplementalMergeResult(
            success=False,
            failure_reason=(
                "The supplemental file was aligned by key, but none of the targeted canonical fields "
                "received matched values."
            ),
            attachments=attachments,
            merge_stats={
                "primary_row_count": int(len(primary_df)),
                "supplemental_row_count": int(len(supplemental_df)),
                "matched_primary_rows": matched_rows,
            },
        )

    merged_df = merged_df.drop(columns=["__merge_key__", *rename_map.values()], errors="ignore")
    output_path = _build_materialized_output_path(
        outputs_dir=outputs_dir,
        primary_file_ref=plan.primary_file_ref or "primary.csv",
        supplemental_file_ref=plan.supplemental_file_ref or "supplemental.csv",
        session_id=session_id,
    )
    merged_df.to_csv(output_path, index=False)

    return SupplementalMergeResult(
        success=True,
        merged_columns=merged_columns,
        materialized_primary_file_ref=str(output_path),
        attachments=attachments,
        merge_stats={
            "primary_row_count": int(len(primary_df)),
            "supplemental_row_count": int(len(supplemental_df)),
            "matched_primary_rows": matched_rows,
            "merge_key": merge_key.to_dict(),
            "coverage_by_target": {
                attachment.canonical_field: attachment.coverage_ratio
                for attachment in attachments
                if attachment.canonical_field
            },
        },
    )
```

- 文件：`core/supplemental_merge.py`
- 对象：`apply_supplemental_merge_analysis_refresh`
- 行号：`982-1081`

```python
def apply_supplemental_merge_analysis_refresh(
    analysis_dict: Dict[str, Any],
    *,
    plan: SupplementalMergePlan,
    result: SupplementalMergeResult,
) -> Dict[str, Any]:
    analysis = dict(analysis_dict or {})
    task_type = _clean_text(analysis.get("task_type"))
    mapping_key = None
    if task_type == "macro_emission":
        mapping_key = "macro_mapping"
    elif task_type == "micro_emission":
        mapping_key = "micro_mapping"

    if mapping_key is not None:
        updated_mapping = _clean_dict(analysis.get(mapping_key))
    else:
        updated_mapping = _clean_dict(analysis.get("column_mapping"))
    for attachment in result.attachments:
        if attachment.target_column and attachment.canonical_field:
            updated_mapping.setdefault(attachment.target_column, attachment.canonical_field)

    analysis["column_mapping"] = dict(updated_mapping)
    if mapping_key is not None:
        analysis[mapping_key] = dict(updated_mapping)

    diagnostics = _clean_dict(analysis.get("missing_field_diagnostics"))
    field_statuses = _clean_dict_list(diagnostics.get("required_field_statuses"))
    if field_statuses:
        attachment_by_field = {
            attachment.canonical_field: attachment
            for attachment in result.attachments
            if attachment.canonical_field
        }
        refreshed_statuses: List[Dict[str, Any]] = []
        for item in field_statuses:
            field_name = _clean_text(item.get("field"))
            attachment = attachment_by_field.get(field_name or "")
            if attachment is None:
                refreshed_statuses.append(dict(item))
                continue

            patched = dict(item)
            patched["mapped_from"] = attachment.target_column or attachment.supplemental_column
            coverage_ratio = attachment.coverage_ratio or 0.0
            if coverage_ratio >= 0.999:
                patched["status"] = "present"
                patched["reason"] = (
                    f"Resolved by bounded supplemental merge via key "
                    f"'{plan.merge_keys[0].primary_column}' -> '{plan.merge_keys[0].supplemental_column}'."
                )
                patched["candidate_columns"] = []
            elif coverage_ratio > 0.0:
                patched["status"] = "partial_merge"
                patched["reason"] = (
                    f"Supplemental merge imported '{attachment.supplemental_column}', "
                    f"but only covered {coverage_ratio:.0%} of primary rows."
                )
            else:
                patched["status"] = "missing"
                patched["reason"] = (
                    f"Supplemental merge targeted '{attachment.supplemental_column}', "
                    "but no aligned values were materialized."
                )
            refreshed_statuses.append(patched)

        diagnostics["required_field_statuses"] = refreshed_statuses
        diagnostics["missing_fields"] = [
            item
            for item in refreshed_statuses
            if str(item.get("status") or "").strip().lower() != "present"
        ]
        diagnostics["status"] = _recompute_diagnostics_status(refreshed_statuses)
        diagnostics["supplemental_merge_summary"] = {
            "merge_key": plan.merge_keys[0].to_dict() if plan.merge_keys else None,
            "merged_columns": list(result.merged_columns),
            "coverage_by_target": {
                attachment.canonical_field: attachment.coverage_ratio
                for attachment in result.attachments
                if attachment.canonical_field
            },
        }
        analysis["missing_field_diagnostics"] = diagnostics

    evidence = [str(item) for item in (analysis.get("evidence") or []) if item is not None]
    evidence.append(
        "supplemental_merge="
        + ",".join(
            f"{attachment.canonical_field}:{attachment.coverage_ratio}"
            for attachment in result.attachments
            if attachment.canonical_field
        )
    )
    analysis["evidence"] = evidence
    analysis["supplemental_merge_plan"] = plan.to_dict()
    analysis["supplemental_merge_result"] = result.to_dict()
    analysis["supplemental_column_attachments"] = [
        attachment.to_dict() for attachment in result.attachments
    ]
    return analysis
```

- 文件：`core/router.py`
- 对象：`UnifiedRouter._handle_supplemental_merge 触发与调用片段`
- 行号：`2129-2338`

```python
    async def _handle_supplemental_merge(
        self,
        state: TaskState,
        relationship_context: FileRelationshipResolutionContext,
        decision: FileRelationshipDecision,
        transition_plan: FileRelationshipTransitionPlan,
        *,
        trace_obj: Optional[Trace] = None,
    ) -> bool:
        merge_context = self._build_supplemental_merge_context(
            state,
            relationship_context,
            decision,
        )
        if trace_obj is not None:
            trace_obj.record(
                step_type=TraceStepType.SUPPLEMENTAL_MERGE_TRIGGERED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action="supplemental_merge",
                input_summary={
                    "primary_file_summary": dict(merge_context.primary_file_summary),
                    "supplemental_file_summary": dict(merge_context.supplemental_file_summary),
                    "target_missing_canonical_fields": list(merge_context.target_missing_canonical_fields),
                    "current_task_type": merge_context.current_task_type,
                },
                reasoning=(
                    "The file-relationship resolver classified the upload as merge_supplemental_columns, "
                    "so the router entered the bounded supplemental merge path."
                ),
            )

        plan = build_supplemental_merge_plan(
            merge_context,
            allow_alias_keys=getattr(self.runtime_config, "supplemental_merge_allow_alias_keys", True),
        )
        state.set_latest_supplemental_merge_plan(plan)
        state.set_latest_supplemental_merge_result(None)

        if trace_obj is not None:
            trace_obj.record(
                step_type=TraceStepType.SUPPLEMENTAL_MERGE_PLANNED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action="supplemental_merge_plan",
                input_summary={
                    "relationship_decision": decision.to_dict(),
                },
                output_summary=plan.to_dict(),
                reasoning=(
                    plan.failure_reason
                    or (
                        f"Planned a bounded key-based merge using "
                        f"{plan.merge_keys[0].primary_column}->{plan.merge_keys[0].supplemental_column}."
                        if plan.merge_keys
                        else "Built a bounded supplemental merge plan."
                    )
                ),
            )

        resume_snapshot = getattr(state, "_supplemental_merge_resume_snapshot", None)
        restored_plan_context = self._restore_residual_plan_from_snapshot(
            state,
            resume_snapshot=resume_snapshot if isinstance(resume_snapshot, dict) else None,
        )

        if plan.plan_status != "ready":
            failure_reason = plan.failure_reason or "The supplemental merge plan could not be built safely."
            if trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.SUPPLEMENTAL_MERGE_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="supplemental_merge_plan",
                    input_summary=merge_context.to_dict(),
                    output_summary=plan.to_dict(),
                    reasoning=failure_reason,
                    error=failure_reason,
                )
            state.control.needs_user_input = True
            state.control.clarification_question = failure_reason
            state.control.input_completion_prompt = None
            state.control.parameter_confirmation_prompt = None
            setattr(state, "_final_response_text", failure_reason)
            self._transition_state(
                state,
                TaskStage.NEEDS_CLARIFICATION,
                reason="supplemental merge plan could not be established safely",
                trace_obj=trace_obj,
            )
            return True

        result = execute_supplemental_merge(
            plan,
            outputs_dir=self.runtime_config.outputs_dir,
            session_id=self.session_id,
        )
        state.set_latest_supplemental_merge_result(result)

        if not result.success:
            failure_reason = result.failure_reason or "The bounded supplemental merge execution failed."
            if trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.SUPPLEMENTAL_MERGE_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="supplemental_merge_apply",
                    input_summary=plan.to_dict(),
                    output_summary=result.to_dict(),
                    reasoning=failure_reason,
                    error=failure_reason,
                )
            state.control.needs_user_input = True
            state.control.clarification_question = failure_reason
            state.control.input_completion_prompt = None
            state.control.parameter_confirmation_prompt = None
            setattr(state, "_final_response_text", failure_reason)
            self._transition_state(
                state,
                TaskStage.NEEDS_CLARIFICATION,
                reason="supplemental merge execution failed safely",
                trace_obj=trace_obj,
            )
            return True

        if trace_obj is not None:
            trace_obj.record(
                step_type=TraceStepType.SUPPLEMENTAL_MERGE_APPLIED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                action="supplemental_merge_apply",
                input_summary=plan.to_dict(),
                output_summary=result.to_dict(),
                reasoning=(
                    f"Materialized a merged primary dataset at {result.materialized_primary_file_ref} "
                    f"with columns {result.merged_columns}."
                ),
            )

        materialized_ref = result.materialized_primary_file_ref
        if not materialized_ref:
            failure_reason = "Supplemental merge succeeded logically but did not materialize an execution-side file."
            if trace_obj is not None:
                trace_obj.record(
                    step_type=TraceStepType.SUPPLEMENTAL_MERGE_FAILED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action="supplemental_merge_apply",
                    input_summary=plan.to_dict(),
                    output_summary=result.to_dict(),
                    reasoning=failure_reason,
                    error=failure_reason,
                )
            state.control.needs_user_input = True
            state.control.clarification_question = failure_reason
            self._transition_state(
                state,
                TaskStage.NEEDS_CLARIFICATION,
                reason="supplemental merge did not materialize a file artifact",
                trace_obj=trace_obj,
            )
            return True

        merged_analysis = await self._analyze_file(materialized_ref)
        merged_analysis["file_path"] = materialized_ref
        merged_analysis = await self._maybe_apply_file_analysis_fallback(
            merged_analysis,
            trace_obj=None,
        )
        merged_analysis = apply_supplemental_merge_analysis_refresh(
            merged_analysis,
            plan=plan,
            result=result,
        )
        state.update_file_context(merged_analysis)
        setattr(state, "_file_analysis_cache", dict(merged_analysis))

        result.updated_file_context_summary = {
            "file_path": materialized_ref,
            "task_type": merged_analysis.get("task_type"),
            "columns": list(merged_analysis.get("columns") or [])[:12],
            "row_count": merged_analysis.get("row_count"),
        }
        result.updated_missing_field_diagnostics = dict(
            merged_analysis.get("missing_field_diagnostics") or {}
        )

        request_payload = getattr(state, "_supplemental_merge_active_request", None)
        request = (
            InputCompletionRequest.from_dict(request_payload)
            if isinstance(request_payload, dict)
            else None
        )

        assessment = None
        affordance = None
        if getattr(self.runtime_config, "supplemental_merge_require_readiness_refresh", True):
            assessment = self._build_readiness_assessment(
                state.execution.tool_results,
                state=state,
                frontend_payloads=self._extract_frontend_payloads(state.execution.tool_results),
                trace_obj=None,
                stage_before=None,
                purpose="input_completion_recheck",
            )
            if assessment is not None and request is not None:
                affordance = assessment.get_action(request.action_id)

        readiness_refresh_result = self._build_supplemental_merge_readiness_refresh_result(
            request=request,
            affordance=affordance,
            assessment=assessment,
            diagnostics=result.updated_missing_field_diagnostics,
        )
        result.updated_readiness_summary = dict(readiness_refresh_result)
        state.set_latest_supplemental_merge_result(result)
```

## 自检

- [x] BaseTool 完整定义已贴出

- [x] 每个工具的 execute() 签名已贴出

- [x] TOOL_DEFINITIONS 完整内容已贴出

- [x] TOOL_GRAPH 完整内容已贴出

- [x] ToolRegistry 和 init_tools 已贴出

- [x] ACTION_CATALOG 完整内容已贴出

- [x] workflow_templates 已贴出

- [x] ExecutionPlan / PlanRepairDecision 已贴出

- [x] Router 关键编排代码已贴出

- [x] 能力约束机制已贴出

- [x] 恢复机制概览已提供
