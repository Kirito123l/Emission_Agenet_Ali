# Sprint 12A Report

## 完成的改动列表

| 文件 | 类型 | 行数 | 说明 |
|------|------|------|------|
| `calculators/hotspot_analyzer.py` | 新建 | 501 | 纯计算热点分析器：阈值/百分位识别、4 邻域聚类、热点级源归因、语义降级。 |
| `tools/hotspot.py` | 新建 | 178 | 第 8 个工具 `analyze_hotspots`，负责从上一轮扩散结果执行热点分析并构造 `ToolResult`。 |
| `tools/definitions.py` | 修改 | 372 | 添加 `analyze_hotspots` schema。 |
| `tools/registry.py` | 修改 | 131 | 注册第 8 个工具，失败时仅 warning，不阻断其它工具。 |
| `core/tool_dependencies.py` | 修改 | 79 | 增加 `analyze_hotspots -> requires dispersion_result / provides hotspot_analysis`。 |
| `core/router.py` | 修改 | 1451 | 支持 `analyze_hotspots` 的 `_last_result` 注入，并将热点结果保存为最新空间结果。 |
| `calculators/__init__.py` | 修改 | 15 | 导出 `HotspotAnalyzer`。 |
| `tests/test_hotspot_analyzer.py` | 新建 | 351 | 算法测试：识别、聚类、归因、解释、排序。 |
| `tests/test_hotspot_tool.py` | 新建 | 319 | 工具测试：execute、注册、依赖、router 注入/保存。 |
| `tests/test_dispersion_tool.py` | 修改 | 386 | 将工具总数断言从 7 更新为 8。 |

## HotspotAnalyzer.analyze() 的完整流程

1. 从 `raster_grid["matrix_mean"]` 读取二维浓度矩阵，并校验 `resolution_m`、方法参数和边界条件。
2. 根据 `method` 计算热点 cutoff：
   - `threshold`：直接使用 `threshold_value`
   - `percentile`：对非零浓度格子取 `100 - percentile` 百分位
3. 生成 `hotspot_mask = matrix >= cutoff`。
4. 用 4 邻域 BFS 做连通分量分析，把相邻热点格子合并成 cluster。
5. 根据 `min_hotspot_area_m2` 过滤过小 cluster。
6. 按 cluster 最大浓度、平均浓度和面积排序，只保留 `max_hotspots` 个。
7. 为每个 cluster 构建 `HotspotArea`：
   - 统计 `max_conc / mean_conc / area_m2 / grid_cells`
   - 汇总 `cell_keys`
   - 从 `cell_centers_wgs84` 估算中心点和 bbox
   - 若启用归因，则聚合该 cluster 内所有 receptor 的 top-road 贡献
8. 根据 `coverage_assessment.level` 生成解释性文本，自动做区域分析 vs 局部热点分析的语义降级。
9. 输出 `HotspotAnalysisResult`，包含识别方法、coverage level、interpretation、热点列表和整体 summary。

## 源归因的实现方式

- 输入来自 Sprint 11 的两个结构：
  - `raster_grid["cell_receptor_map"]`
  - `road_contributions["receptor_top_roads"]`
- 归因过程：
  1. hotspot cluster 的格子集合 -> 对应 receptor index 集合
  2. receptor index -> 每个 receptor 的 top roads 贡献列表
  3. 按 road 聚合贡献值
  4. 排序后计算 `contribution_pct`
  5. 输出 top-10 `contributing_roads`
- 实现兼容两种 receptor 贡献格式：
  - `(road_idx, contribution)` tuple/list
  - `{"road_idx", "road_id", "contribution"}` dict
- 输出字段为：
  - `link_id`
  - `contribution_pct`
  - `contribution_value`

## 语义降级规则

- `complete_regional`
  - 解释为“区域污染热点识别”
- `partial_regional`
  - 解释为“区域污染热点识别（路网部分缺失，热点分布可能不完整）”
- `sparse_local` 或未知
  - 解释为“已上传道路范围内的局部热点贡献识别（非完整区域分析）”

这保证了在路网覆盖不完整时，热点工具不会把局部结果误包装成完整区域结论。

## 测试结果

- 新测试：
  - `pytest tests/test_hotspot_analyzer.py -v` -> `18 passed`
  - `pytest tests/test_hotspot_tool.py -v` -> `15 passed`
- 现有扩散链路：
  - `pytest tests/test_dispersion_calculator.py -q` -> `41 passed`
  - `pytest tests/test_dispersion_tool.py -q` -> `20 passed`
  - `pytest tests/test_dispersion_integration.py -q` -> `58 passed`
- 全量回归：
  - `pytest -q` -> `394 passed, 19 warnings in 49.00s`
- Sprint 11 结束时：`361 tests`
- Sprint 12A 完成后：`394 tests`

## 健康检查

- `python main.py health` -> 8 个工具全部 `OK`
- 当前工具列表：
  - `query_emission_factors`
  - `calculate_micro_emission`
  - `calculate_macro_emission`
  - `analyze_file`
  - `query_knowledge`
  - `calculate_dispersion`
  - `analyze_hotspots`
  - `render_spatial_map`
- `python -c "from calculators.hotspot_analyzer import HotspotAnalyzer; from tools.hotspot import HotspotTool; print('Hotspot imports OK')"` -> `Hotspot imports OK`

## 已知限制

- 当前 bbox 使用热点格子中心点范围近似表示，不是严格的格子边界 polygon。
- 聚类使用 4 邻域，不把对角接触视作同一热点。
- 如果原始扩散结果不包含 `road_contributions`，热点仍可识别，但 `contributing_roads` 会为空。
- `render_spatial_map` 和前端还没有热点图层渲染逻辑；本次只把热点数据结构和 routing 准备好。

## 下一步：Sub-task B 需要做什么

1. 在 `tools/spatial_renderer.py` 中识别 `type="hotspot"` 的 map_data。
2. 基于 hotspot 的 `bbox / center / contributing_roads` 渲染热点图层。
3. 用 `raster_grid` 做浓度背景层，而不是继续只画散点 receptor。
4. 为热点图层增加图例、rank 标注和点击详情。
5. 支持高亮 `contributing_roads`，实现“热点区 <- 主要来源路段”联动。
