# Sprint 12 Final Report

## Sprint 12 完成总结

- 目标：`analyze_hotspots` 工具 + 前端栅格渲染 + 热点标注
- 完成状态：✅

Sprint 12 完成了从扩散结果到热点解释再到地图展示的完整闭环：

```text
calculate_macro_emission (排放计算)
    -> calculate_dispersion (扩散浓度场 + 栅格 + 贡献追踪)
        -> analyze_hotspots (热点识别 + 源归因)
            -> render_spatial_map (栅格渲染 + 热点标注)
```

## 交付物清单

| 文件 | 状态 | 行数 | 说明 |
|------|------|------|------|
| `calculators/hotspot_analyzer.py` | 新增 | 501 | 热点识别、4 邻域聚类、cluster 级源归因 |
| `tools/hotspot.py` | 新增 | 178 | 第 8 个工具，封装热点分析结果与地图数据 |
| `tools/definitions.py` | 修改 | 372 | 新增 `analyze_hotspots` schema |
| `tools/registry.py` | 修改 | 131 | 注册第 8 个工具 |
| `core/tool_dependencies.py` | 修改 | 79 | 添加 `dispersion_result -> hotspot_analysis` 依赖 |
| `core/router.py` | 修改 | 1451 | 注入/保存热点相关 `_last_result` 与空间结果 |
| `calculators/__init__.py` | 修改 | 15 | 导出 `HotspotAnalyzer` |
| `tools/spatial_renderer.py` | 修改 | 769 | 新增 raster / hotspot 后端 map builder |
| `web/app.js` | 修改 | 3370 | 新增栅格渲染、热点图层、warning/legend/标签 |
| `tests/test_hotspot_analyzer.py` | 新增 | 351 | 热点计算逻辑测试 |
| `tests/test_hotspot_tool.py` | 新增 | 319 | 工具注册、执行、router 集成测试 |
| `tests/test_spatial_renderer.py` | 修改 | 542 | raster / hotspot 渲染测试 |
| `tests/test_real_model_integration.py` | 修改 | 374 | 真实扩散渲染断言同步到 raster 新语义 |
| `SPRINT12A_REPORT.md` | 新增 | 107 | Sprint 12A 结题报告 |

## 测试结果

- Sprint 12 前：361 tests
- Sprint 12 后：412 tests
- 全部通过：✅

本次实际执行的验证：

- `pytest tests/test_spatial_renderer.py -v -k "raster or hotspot or Raster or Hotspot"` -> `17 passed, 30 deselected`
- `pytest tests/test_hotspot_analyzer.py -q` -> `18 passed`
- `pytest tests/test_hotspot_tool.py -q` -> `15 passed, 3 warnings`
- `pytest tests/test_real_model_integration.py::test_real_dispersion_result_to_spatial_renderer -q` -> `1 passed`
- `pytest -q` -> `412 passed, 19 warnings in 46.20s`
- `python main.py health` -> `8` 个工具全部 `OK`
- `node -c web/app.js` -> `OK`
- `python -m py_compile tools/spatial_renderer.py` -> `OK`

## 新增能力

### analyze_hotspots 工具

- 支持两种热点识别方法：百分位法和绝对阈值法。
- 使用 4 邻域连通分量把相邻热点栅格合并为一个热点区域。
- 基于 `cell_receptor_map + road_contributions` 做逐热点源归因。
- 根据 `coverage_assessment.level` 自动降级语义，避免把稀疏路网结果误表述为完整区域分析。

### 前端栅格渲染

- `render_spatial_map` 现在优先输出 `raster` 图层，而不是受体 CircleMarker 散点。
- 前端支持把 `raster_grid.cell_centers_wgs84` 渲染为无缝矩形色块。
- 色阶采用对数归一化；当 `min <= 0` 时自动回退到线性色阶。
- 保留旧的 receptor CircleMarker 逻辑作为 fallback，兼容旧扩散结果。

### 前端热点展示

- 热点区域以红色虚线边框显示。
- 热点中心带 rank 数字标签。
- 点击 hotspot popup 可查看最大/平均浓度、面积和 Top contributing roads。
- `coverage_assessment` 在地图卡片上展示 warning 横条。
- 若 GIS 路网中存在可匹配的 ID / name 字段，则前端会 best-effort 高亮贡献路段。

## 后端渲染实现

### `tools/spatial_renderer.py`

- `_detect_layer_type()` 新增 `hotspot` 和 `raster` 识别，并保证 `raster_grid` 优先于 legacy `concentration_grid`。
- `_build_raster_map()`：
  - 读取 `raster_grid.cell_centers_wgs84`
  - 按 `resolution_m` 近似换算经纬度偏移
  - 为每个非零 cell 生成闭合矩形 Polygon
  - 输出 `concentration_raster` 图层、值域、summary 和 coverage 信息
- `_build_hotspot_map()`：
  - 把每个 hotspot 的 `bbox` 转成 Polygon
  - 收集 `contributing_road_ids`
  - 自动叠加 raster 背景层
  - 把完整 `hotspots_detail` 透传给前端 popup

## 前端渲染实现

### `web/app.js`

- `renderMapData()` 现在支持：
  - `type="hotspot"`
  - `type="raster"`
  - `type="concentration" + raster_grid`
  - legacy emission / concentration fallback
- `normalizeRasterMapData()`：
  - 兼容两种输入：
    - 直接来自 `calculate_dispersion` 的原始 `map_data`
    - 来自 `render_spatial_map` 的 backend-normalized raster payload
- `normalizeHotspotMapData()`：
  - 兼容两种输入：
    - 直接来自 `analyze_hotspots` 的原始 `map_data`
    - 来自 `render_spatial_map` 的 backend-normalized hotspot payload
- 新增 `renderRasterMap()` / `initRasterLeafletMap()`：
  - GeoJSON Polygon 栅格色块
  - popup 展示 mean/max concentration
  - 连续渐变图例 + 分辨率说明
- 新增 `renderHotspotMap()` / `initHotspotLeafletMap()`：
  - hotspot bbox 边框图层
  - rank 标签
  - interpretation banner
  - coverage warning banner
  - best-effort 贡献路段高亮图层

## 手动验证步骤

以 `test_data/test_20links.xlsx` 为例，可按下面步骤做端到端人工验收：

1. 启动服务：`python run_api.py`
2. 上传或选用 `test_data/test_20links.xlsx`
3. 运行宏观排放计算：`calculate_macro_emission`
4. 运行扩散：`calculate_dispersion`
   - 例如：`meteorology="urban_summer_day"`, `grid_resolution=50`
5. 运行热点分析：`analyze_hotspots`
   - 例如：`method="percentile"`, `percentile=5`, `source_attribution=true`
6. 运行渲染：`render_spatial_map`
7. 在前端确认：
   - 扩散结果显示为连续栅格色块，而不是离散受体点
   - 热点图显示红色虚线框和 rank 标签
   - popup 中能看到 contributing roads
   - `partial_regional` / `sparse_local` 时出现 coverage warning 横条

## 已知限制

- 栅格矩形是基于局部经纬度近似换算生成的显示层，不改变底层扩散计算精度。
- 贡献路段高亮依赖 GIS 路网属性是否包含可匹配的 `link_id` / `road_id` / `name`；当前 `static_gis/roadnetwork.geojson` 只有 `highway` 和 `name`，因此高亮是 best-effort，不保证所有数据集都命中。
- hotspot 前端渲染当前使用 hotspot `bbox` 作为可视化范围，尚未细化为 cluster cell union polygon。
- legacy CircleMarker fallback 仍保留，因此旧会话与旧结果不会被破坏，但视觉上不如 raster 层连续。

## Sprint 13 准备就绪度

| 任务 | 依赖 | 就绪 |
|------|------|------|
| `calculate_dispersion` 文件直接输入 | `tools/dispersion.py` | ⚠️ 待做 |
| `test_shanghai_full` 完整验证 | 前端栅格渲染 | ✅ |
| Benchmark 构建 | 完整工具链 | ✅ |

