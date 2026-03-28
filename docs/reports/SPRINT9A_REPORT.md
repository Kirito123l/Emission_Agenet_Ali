# Sprint 9 Sub-task A Report

## 完成的改动列表

- 在 `tools/definitions.py` 新增 `calculate_dispersion` function-calling schema。
- 新建 `tools/dispersion.py`，实现 `DispersionTool`：
  - 支持 `last_result` 作为排放输入源。
  - 支持 6 个气象预设、`custom` 气象字典、`.sfc` 文件路径。
  - 按 `roughness_height` 缓存 `DispersionCalculator` 实例。
  - 返回标准 `ToolResult`，并附带 `concentration_grid` 形式的 `map_data`。
- 在 `tools/registry.py` 注册 `calculate_dispersion`，并使用 `warning` 级别处理注册失败。
- 在 `core/router.py` 扩展空间数据保存逻辑：
  - `calculate_dispersion` 结果现在会写入 `last_spatial_data`。
  - 当结果包含 `concentration_grid` 时也会保存。
- 在 `core/router.py` 增加 `calculate_dispersion` 的 `_last_result` 注入：
  - 可从当前轮已完成的 `calculate_macro_emission` 结果注入。
  - 可从 memory 中仍保留的宏观排放空间结果注入。
- 新建 `tests/test_dispersion_tool.py`，覆盖工具初始化、参数解析、calculator 缓存、execute 集成、工具注册、router 注入与空间数据保存。

## calculate_dispersion Schema

```python
{
    "type": "function",
    "function": {
        "name": "calculate_dispersion",
        "description": (
            "Calculate pollutant dispersion/concentration distribution from vehicle emissions "
            "using the PS-XGB-RLINE surrogate model. "
            "This tool requires emission results as input - typically from calculate_macro_emission. "
            "It computes how pollutants disperse in the atmosphere around roads, "
            "producing a spatial concentration field that can be visualized on a map."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "emission_source": {
                    "type": "string",
                    "description": (
                        "Source of emission data. Options: "
                        "'last_result' to use the most recent macro emission calculation result, "
                        "or a file path to emission data file."
                    ),
                    "default": "last_result"
                },
                "meteorology": {
                    "type": "string",
                    "description": (
                        "Meteorological conditions. Options: "
                        "A preset name (urban_summer_day, urban_summer_night, urban_winter_day, "
                        "urban_winter_night, windy_neutral, calm_stable), "
                        "or 'custom' to specify wind_speed/wind_direction/stability_class separately, "
                        "or a file path to an AERMOD .sfc meteorology file."
                    ),
                    "default": "urban_summer_day"
                },
                "wind_speed": {
                    "type": "number",
                    "description": "Wind speed in m/s. Only used when meteorology='custom'."
                },
                "wind_direction": {
                    "type": "number",
                    "description": "Wind direction in degrees (0=N, 90=E, 180=S, 270=W). Only used when meteorology='custom'."
                },
                "stability_class": {
                    "type": "string",
                    "description": (
                        "Atmospheric stability class. Only used when meteorology='custom'. "
                        "Options: VS (very stable), S (stable), N1 (neutral), N2 (neutral), "
                        "U (unstable), VU (very unstable)."
                    ),
                    "enum": ["VS", "S", "N1", "N2", "U", "VU"]
                },
                "mixing_height": {
                    "type": "number",
                    "description": "Mixing layer height in meters. Only used when meteorology='custom'. Default: 800."
                },
                "roughness_height": {
                    "type": "number",
                    "description": (
                        "Surface roughness height in meters. Determines which surrogate model set to use. "
                        "Options: 0.05 (open terrain), 0.5 (suburban), 1.0 (urban). Default: 0.5."
                    ),
                    "enum": [0.05, 0.5, 1.0]
                },
                "pollutant": {
                    "type": "string",
                    "description": "Pollutant to calculate dispersion for. Currently only NOx is supported.",
                    "default": "NOx"
                }
            },
            "required": []
        }
    }
}
```

## DispersionTool.execute() 流程说明

1. 读取 LLM/executor 传入参数：`emission_source`、`meteorology`、`roughness_height`、`pollutant`。
2. 通过 `_resolve_emission_source()` 解析排放输入：
   - `last_result` 时接收 router 注入的上一份宏观排放结果。
   - 文件路径暂不支持，记录 warning 并返回失败。
3. 用 `EmissionToDispersionAdapter.adapt()` 将宏观排放结果转成：
   - `roads_gdf`
   - `emissions_df`
4. 如果没有 geometry，直接返回失败，避免进入 calculator。
5. 通过 `_build_met_input()` 构造气象输入：
   - 预设名直接透传给 `DispersionCalculator`
   - `custom` 组装成 dict，并补代表性的 `monin_obukhov_length`
   - `.sfc` 路径直接透传
6. 通过 `_get_calculator()` 按 roughness 缓存/复用 `DispersionCalculator` 实例。
7. 调用 `DispersionCalculator.calculate()` 执行扩散推理。
8. 如果 calculator 返回 `status=error`，转换为 `ToolResult(success=False, ...)`。
9. 成功时构建：
   - `summary`
   - `map_data`，其中显式包含 `concentration_grid`
10. 返回标准 `ToolResult(success=True, data=..., summary=..., map_data=...)`。

## 工具注册验证

`python main.py health` 输出：

```text
OK query_emission_factors
OK calculate_micro_emission
OK calculate_macro_emission
OK analyze_file
OK query_knowledge
OK calculate_dispersion
OK render_spatial_map

Total tools: 7
```

额外验证：

```text
python -c "from tools.dispersion import DispersionTool; print('Tool OK')"
Tool OK
```

## 测试结果

- `pytest tests/test_dispersion_tool.py -v` -> `20 passed`
- `pytest -q` -> `260 passed, 19 warnings in 6.04s`
- 原有测试无回归
- 新增覆盖点：
  - `DispersionTool` 初始化
  - `_resolve_emission_source`
  - `_build_met_input`
  - `_get_calculator`
  - `execute()` 成功/失败路径
  - registry 注册后工具总数为 7
  - router 对 `calculate_dispersion` 的 `_last_result` 注入
  - router 对 `concentration_grid` 的 `last_spatial_data` 保存

## 额外说明

- `calculate_dispersion` 现在已经能被工具层注册，并且默认 `emission_source="last_result"` 时，router 会在可用时自动注入上一份宏观排放结果。
- `map_data` 中包含 `concentration_grid`，这样后续 `spatial_renderer` 的图层识别逻辑可以把它识别为 `concentration` 类型。
- 未加载真实 surrogate 模型文件；所有测试均通过 mock calculator 完成，符合当前 CI/本地测试约束。
- 快速质量检查已确认 `tools/dispersion.py` 和 `calculators/dispersion_adapter.py` 中没有 `print` / `matplotlib` / `plt` 残留。

## 下一步（Sub-task B）

- 让 router/executor 的依赖编排更稳定地触发 `calculate_macro_emission -> calculate_dispersion` 链式调用，而不是仅依赖 `_last_result` 注入。
- 继续补 `tools/definitions.py` 相关提示与 synthesis 文案，让 LLM 更稳定地在有排放结果时选择 `calculate_dispersion`。
- 开始定义扩散工具的前端展示/trace 体验，但不进入 Sprint 10 的浓度渲染实现细节。
