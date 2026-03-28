# Sprint 11 Final Report

## Sprint 11 完成总结

- 目标：栅格聚合 + 输入校验 + 贡献追踪 + 气象优化
- 完成状态：✅

Sprint 11 已完成从宏观排放到扩散结果展示的数据增强闭环。11A 解决了输入覆盖度评估、规则栅格聚合和逐路段贡献记录；11B 在不修改 calculator 数值核心的前提下，补齐了气象预设微调、结果中的气象追踪信息，以及更强的 schema 提示。

## 交付物清单

| 文件 | 状态 | 行数 | 说明 |
|------|------|------|------|
| `core/coverage_assessment.py` | 新建 | 240 | 路网覆盖度评估，输出 `complete_regional / partial_regional / sparse_local` 三级语义分级和 warning。 |
| `calculators/dispersion.py` | 修改 | 1586 | 新增 `aggregate_to_raster()`、逐路段贡献追踪、结果栅格聚合与 `display_grid_resolution_m`。 |
| `tools/dispersion.py` | 修改 | 446 | 接入 coverage assessment、`grid_resolution`、`meteorology_used`，支持纯预设/预设+覆盖/纯自定义/SFC 四种气象模式。 |
| `tools/definitions.py` | 修改 | 306 | 补充 `grid_resolution`，强化气象与 coverage 的 schema description，引导 LLM 主动确认默认气象。 |
| `tests/test_coverage_assessment.py` | 新建 | 133 | 覆盖三级分级、连通性、稀疏路网和序列化。 |
| `tests/test_raster_aggregation.py` | 新建 | 178 | 覆盖 50/100/200m 栅格聚合、映射关系、bbox、空输入。 |
| `tests/test_road_contributions.py` | 新建 | 174 | 覆盖逐路段贡献追踪开关、求和一致性和 segment-road 映射。 |
| `tests/test_dispersion_integration.py` | 修改 | 918 | 新增 raster/coverage 集成验证，以及气象预设微调、`meteorology_used` 和 schema 回归测试。 |
| `tests/test_dispersion_calculator.py` | 修改 | 589 | 补充 `display_grid_resolution_m` 和 `raster_grid` 相关断言。 |
| `SPRINT11A_REPORT.md` | 新建 | 225 | Sprint 11A 阶段报告。 |
| `SPRINT11_FINAL_REPORT.md` | 新建 | 126 | Sprint 11 最终结题报告。 |

## 测试结果

- Sprint 11 前：319 tests
- Sprint 11 后：361 tests
- 结果：全部通过

本次 Sprint 11B 额外验证结果：

- `pytest tests/test_dispersion_integration.py -v -k "Meteorology or Schema"` → `36 passed, 22 deselected`
- `pytest -q` → `361 passed, 19 warnings in 46.04s`
- `python main.py health` → 7 个注册工具全部 `OK`
- `python -c "...DispersionTool._build_met_input..."` → 4 种模式全部通过，输出符合预期
- `pytest tests/test_real_model_integration.py::test_real_macro_to_dispersion_20links -v -s 2>&1 | tail -10` → `PASSED`，真实 20 links 链路 smoke 正常

## 新增能力摘要

### 1. 输入校验与语义分级

- 基于凸包面积、总路长、路网密度、连通性和 road count，对输入路网做三级 coverage assessment。
- 对稀疏或断裂路网不阻止计算，但会在结果中附加语义标签和 warning，避免把局部热点结果误读为区域浓度场。
- tool summary 和 `data.coverage_assessment` 会同时保留这类解释信息。

### 2. 栅格聚合

- 计算层仍使用密集 receptor points，不牺牲精度。
- 结果层新增 `raster_grid`，支持 50/100/200m 三档显示分辨率。
- 输出同时包含：
  - 二维浓度矩阵 `matrix_mean / matrix_max`
  - `cell_receptor_map`
  - `cell_centers_wgs84`
  - `bbox_local / bbox_wgs84`
  - 栅格统计信息
- 这些结构已经为 Sprint 12 的前端栅格渲染和热点分析准备好基础数据。

### 3. 逐路段贡献追踪

- `predict_time_series_xgb` 已支持逐受体逐道路贡献记录。
- 根据问题规模自动切换：
  - `dense_exact`：小规模时保存精确稠密贡献矩阵
  - `sparse_topk`：大规模时仅保留每个受体 top-K 贡献道路，控制内存占用
- 结果中的 `road_contributions` 已可直接作为后续 `analyze_hotspots` 的数据底座。

### 4. 气象预设 + 微调

- `DispersionTool._build_met_input()` 现在支持四种模式：
  - 纯预设：返回预设名字符串，保持与既有 calculator 行为完全兼容
  - 预设 + 覆盖：加载 YAML 预设并只覆盖用户指定字段
  - 纯自定义：从参数构造气象 dict，并补齐稳定度派生参数
  - `.sfc` 文件：路径原样透传
- 结果中新增 `meteorology_used`，明确记录：
  - 基础预设名
  - 覆盖前后值
  - 实际用于展示/解释的风速、风向、稳定度、混合层高度
- summary 现在会显示完整气象详情、覆盖记录、coverage warning 和最终栅格分辨率。

## LLM 可用的调用示例

```json
{
  "name": "calculate_dispersion",
  "arguments": {
    "meteorology": "urban_summer_day",
    "wind_direction": 315,
    "grid_resolution": 100
  }
}
```

```json
{
  "name": "calculate_dispersion",
  "arguments": {
    "meteorology": "custom",
    "wind_speed": 1.0,
    "wind_direction": 0,
    "stability_class": "VS",
    "mixing_height": 100,
    "roughness_height": 1.0,
    "grid_resolution": 50
  }
}
```

## 已知限制

- 前端当前仍主要消费 `concentration_grid` 的点状渲染逻辑，`raster_grid` 已就绪，但正式栅格渲染切换留到 Sprint 12。
- `road_contributions` 在大路网下采用 `sparse_topk` 近似存储模式，不是全量稠密矩阵。
- schema 对 LLM 的“先告知默认气象再确认”属于提示增强，最终是否执行仍依赖 agent 在调 tool 前遵循该描述。

## Sprint 12 准备就绪度

| Sprint 12 任务 | 依赖 | 就绪 |
|------|------|------|
| `analyze_hotspots` 工具 | `raster_grid` + `cell_receptor_map` + `road_contributions` | ✅ |
| 前端栅格渲染 | `raster_grid.cell_centers_wgs84` | ✅ |
| 热点标注图层 | `analyze_hotspots` 结果 | ⚠️ 等 `analyze_hotspots` 完成 |
| 贡献路段高亮 | `hotspot.contributing_roads` | ⚠️ 等 `analyze_hotspots` 完成 |

## 结论

Sprint 11 的目标已经全部完成。系统当前从工具接口、结果语义、后处理结构和测试覆盖率上，都已经具备进入 Sprint 12 热点分析与前端栅格渲染阶段的条件。
