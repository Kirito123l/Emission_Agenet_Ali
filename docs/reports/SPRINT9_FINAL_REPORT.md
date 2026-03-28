# Sprint 9 Final Report

## Sprint 9 完成总结

- Sprint 9 目标：将 `DispersionCalculator` 接入工具层，让 LLM 能通过 function calling 调用扩散计算
- 完成状态：✅

## 交付物清单

| 文件 | 状态 | 行数 | 说明 |
|------|------|------|------|
| `tools/dispersion.py` | 新建 | 257 | `DispersionTool` 工具类，封装 emission source 解析、adapter 调用、气象输入构建、calculator 执行与 `ToolResult` 输出 |
| `tools/definitions.py` | 修改 | 269 | 新增 `calculate_dispersion` function-calling schema |
| `tools/registry.py` | 修改 | 125 | 注册第 7 个工具 `calculate_dispersion` |
| `core/router.py` | 修改 | 1410 | `_last_result` 注入扩展到扩散链路，`concentration_grid` 保存到 `last_spatial_data` |
| `core/executor.py` | 修改 | 304 | 新增 `meteorology` 与 `stability_class` 参数标准化接入 |
| `services/standardizer.py` | 修改 | 758 | 新增 `standardize_meteorology()` 与 `standardize_stability_class()` |
| `config/unified_mappings.yaml` | 修改 | 574 | 新增 6 个气象预设别名映射与稳定度等级别名映射 |
| `tests/test_dispersion_tool.py` | 新建 | 386 | 工具层测试，覆盖 schema/execute/registry/router 注入与空间数据保存 |
| `tests/test_dispersion_integration.py` | 新建 | 282 | 端到端集成测试，覆盖 adapter、calculator、meteorology standardization、executor standardization、依赖链验证 |

## 测试结果

- Sprint 9 前：240 tests
- Sprint 9 后：290 tests
- 全部通过
- 原有测试无回归

关键验证结果：

- `pytest tests/test_dispersion_integration.py -q` → `30 passed`
- `pytest -q` → `290 passed, 19 warnings in 6.33s`
- `python main.py health` → `Total tools: 7`
- `python -c "from services.standardizer import get_standardizer; s = get_standardizer(); print(s.standardize_meteorology('城市夏季白天'))"` → `StandardizationResult(... normalized='urban_summer_day', strategy='alias' ...)`

## calculate_dispersion 完整调用链路

```text
LLM function call
  -> executor._standardize_arguments() [meteorology/stability_class/pollutant 标准化]
  -> DispersionTool.execute()
    -> _resolve_emission_source() [从 _last_result 获取排放数据]
    -> EmissionToDispersionAdapter.adapt() [字段映射 + 单位转换 + geometry 解析]
    -> _build_met_input() [预设/custom/.sfc 气象输入构建]
    -> DispersionCalculator.calculate() [道路合并 -> 坐标转换 -> 分段 -> 受体生成 -> 气象处理 -> surrogate 推理]
    -> _build_summary() + _build_map_data()
  -> ToolResult
  -> router: save to last_spatial_data [concentration_grid]
  -> synthesis
  -> 前端
```

## LLM 可用的调用示例

```json
{
  "name": "calculate_dispersion",
  "arguments": {
    "emission_source": "last_result",
    "meteorology": "urban_summer_day",
    "roughness_height": 0.5,
    "pollutant": "NOx"
  }
}
```

```json
{
  "name": "calculate_dispersion",
  "arguments": {
    "meteorology": "custom",
    "wind_speed": 3.0,
    "wind_direction": 270,
    "stability_class": "U",
    "mixing_height": 800,
    "roughness_height": 1.0
  }
}
```

## 气象标准化实现摘要

- `meteorology` 现在支持精确预设名、中文别名、英文别名、`custom` 和 `.sfc` 路径。
- 无法识别的 `meteorology` 输入会返回 `abstain`，并给出 6 个预设名建议。
- `stability_class` 现在支持 `VS/S/N1/N2/U/VU` 以及英文/中文别名的统一归一化。
- `executor` 只标准化离散语义参数；`wind_speed`、`wind_direction`、`mixing_height`、`roughness_height` 继续原样透传。

## 已知限制

- 文件路径作为 `emission_source` 暂不支持，当前仍依赖 `last_result`
- surrogate 模型当前仅支持 `NOx`
- `render_spatial_map` 的 `concentration` 分支仍是占位实现，完整浓度渲染留到 Sprint 10
- 所有测试使用 mock surrogate 模型，未加载真实 142MB 模型文件做集成验证

## Sprint 10 准备就绪度

| Sprint 10 任务 | 依赖 | 就绪 |
|------|------|------|
| `render_spatial_map` concentration 渲染 | `concentration_grid` 结构已定义并在 `map_data` 中透传 | ✅ |
| 前端浓度图层显示 | Leaflet + 色阶 + 图例 | ⚠️ 待做 |
| 端到端联调（macro → dispersion → map） | 工具链路已通，router memory 已保存 `concentration_grid` | ✅ |
| 真实模型文件集成测试 | 142MB 模型文件与运行环境 | ⚠️ 可选 |

## 运行验证

```bash
pytest tests/test_dispersion_integration.py -q
pytest -q
python main.py health
python -c "from services.standardizer import get_standardizer; s = get_standardizer(); print(s.standardize_meteorology('城市夏季白天'))"
```
