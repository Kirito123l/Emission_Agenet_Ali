# Sprint 11A Report

生成时间：`2026-03-21`  
项目根目录：`/home/kirito/Agent1/emission_agent`

## 一、完成的改动列表

### 1. 输入校验与语义分级

- 新增 `core/coverage_assessment.py`
  - 实现 `CoverageAssessment` 数据类
  - 实现 `assess_coverage(roads_gdf)`，输出覆盖等级、密度、连通性、最大断裂间距、解释语义和 warning
- 修改 `tools/dispersion.py`
  - 在 adapter 后、calculator 前执行 coverage assessment
  - 将 `coverage_assessment` 注入 calculator 结果
  - 将 warning 追加到 tool summary
  - 将 `coverage_assessment` 透传到 `map_data`

### 2. 栅格聚合层

- 修改 `calculators/dispersion.py`
  - `DispersionConfig` 新增 `display_grid_resolution_m: float = 50.0`
  - 新增 `aggregate_to_raster(...)`
  - 在 `_assemble_result()` 中基于受体均值浓度构建 `raster_grid`
  - 在 `query_info` 中回传 `display_grid_resolution_m`
- 修改 `tools/definitions.py`
  - 为 `calculate_dispersion` schema 新增 `grid_resolution` 参数，支持 `50 | 100 | 200`
- 修改 `tools/dispersion.py`
  - 支持读取 `grid_resolution`
  - 调用 calculator 前动态设置 display grid resolution
  - 将 `raster_grid` 透传到 `map_data`

### 3. 逐路段浓度贡献记录

- 修改 `calculators/dispersion.py`
  - `predict_time_series_xgb()` 新增
    - `track_road_contributions: bool = False`
    - `segment_to_road_map: Optional[np.ndarray] = None`
  - `track_road_contributions=False` 时保持原始返回类型和数值路径不变
  - `track_road_contributions=True` 时返回 `(conc_df, road_contributions)`
  - `_segment_roads()` 为每个线源段记录 `road_idx`
  - `calculate()` 构建 `segment_to_road_map` 并启用贡献追踪
  - `_assemble_result()` 回传
    - `road_contributions.receptor_top_roads`
    - `road_contributions.road_id_map`
    - `road_contributions.top_k`
    - `road_contributions.tracking_mode`

### 4. 测试

- 新增 `tests/test_coverage_assessment.py`
- 新增 `tests/test_raster_aggregation.py`
- 新增 `tests/test_road_contributions.py`
- 修改 `tests/test_dispersion_calculator.py`
- 修改 `tests/test_dispersion_integration.py`

## 二、CoverageAssessment 分级规则与示例

### 规则

- `complete_regional`
  - 条件：`road_density >= 8 km/km²`、路网连通、凸包面积 `>= 0.5 km²`
  - 语义：`区域污染浓度场 / Regional pollution concentration field`
- `partial_regional`
  - 条件：`road_density >= 3 km/km²`，但未达到 complete 条件
  - 语义：`区域浓度场（部分路网可能缺失，浓度可能偏低）`
- `sparse_local`
  - 条件：`road_count < 10`，或密度过低，或凸包退化
  - 语义：`已上传道路范围内的局部热点贡献识别 / Local hotspot contribution analysis within uploaded roads only`

### 计算指标

- 凸包面积：统一投影到 UTM 后基于 `convex_hull.area`
- 路段总长度：统一投影到 UTM 后基于 `geometry.length.sum()`
- 路网密度：`total_road_length_km / convex_hull_area_km2`
- 连通性：对每条道路做 `200m buffer` 后 union，单一 polygon 视为连通
- 最大断裂间距：对多 cluster polygon 的 pairwise distance 取最大值

### 示例

- 1 km x 1 km 范围内 10 条交叉道路，密度约 10 km/km²：`complete_regional`
- 2 km x 2 km 范围内 12 条网格道路，密度约 6 km/km²：`partial_regional`
- 5 条零散道路，或 2 条上传道路：`sparse_local`

## 三、aggregate_to_raster 实现说明

### 设计目标

- 计算层继续使用原有密集受体点，保证 surrogate 精度
- 显示层新增规则栅格，提升浓度场展示和后续热点分析可用性
- 仅做后处理，不改变受体级推理结果

### 聚合流程

1. 根据受体 `x/y` 范围和 `resolution_m` 计算 raster `rows/cols`
2. 将每个受体映射到 `(row, col)`
3. 对每个 cell 聚合
   - `sum`
   - `count`
   - `max`
4. 生成
   - `matrix_mean`
   - `matrix_max`
   - `cell_receptor_map`
5. 将 cell center 和 bbox 从 local/UTM 坐标逆变换回 WGS-84

### 输出结构

`raster_grid` 包含：

- `matrix_mean`
- `matrix_max`
- `bbox_local`
- `bbox_wgs84`
- `resolution_m`
- `rows`
- `cols`
- `nodata`
- `cell_receptor_map`
- `cell_centers_wgs84`
- `stats`

其中 `cell_receptor_map` 是后续 `analyze_hotspots` 的关键桥接数据，用于从栅格热点反查其包含的受体集合。

## 四、predict_time_series_xgb 贡献追踪实现与内存考量

### 追踪方式

- 由 `_segment_roads()` 记录每个线源段的 `road_idx`
- `calculate()` 构造 `segment_to_road_map`
- `predict_time_series_xgb()` 在每次 segment contribution 累加总浓度时，同时累加到所属原始道路

### 两种追踪模式

- `dense_exact`
  - 当 `n_receptors * n_roads <= 10,000,000` 时使用
  - 分配 `n_receptors x n_roads` 的 `float32` 矩阵
  - 精确累计后提取每个受体 top-k 道路
- `sparse_topk`
  - 当估算 dense 矩阵过大时启用
  - 使用 `list[defaultdict(float)]` 存储受体级稀疏贡献
  - 当单受体记录过多时裁剪到较大的候选集合，再在最终阶段保留 top 10

### 当前输出

- `receptor_top_roads`
  - 每个受体的 top-10 道路贡献
- `road_id_map`
  - `road_idx -> road_id` 映射
- `effective_timesteps`
  - 用于说明贡献值已按有效时间步平均
- `tracking_mode`
  - `dense_exact` 或 `sparse_topk`

### 内存说明

- 小中型网络：使用 dense exact，速度和可解释性更好
- 大型网络：自动退化到 sparse top-k，避免构建不可接受的稠密矩阵

## 五、测试结果

### 新增测试

- `pytest tests/test_coverage_assessment.py -v` -> `8 passed`
- `pytest tests/test_raster_aggregation.py -v` -> `9 passed`
- `pytest tests/test_road_contributions.py -v` -> `5 passed`

### 现有扩散回归

- `pytest tests/test_dispersion_calculator.py -q` -> `41 passed`
- `pytest tests/test_dispersion_tool.py -q` -> `20 passed`
- `pytest tests/test_dispersion_integration.py -q` -> `41 passed`
- `pytest tests/test_dispersion_numerical_equivalence.py -q` -> `7 passed`

### 全量回归

- `pytest -q` -> `344 passed, 19 warnings in 48.08s`

### 健康检查

- `python main.py health`
  - `OK query_emission_factors`
  - `OK calculate_micro_emission`
  - `OK calculate_macro_emission`
  - `OK analyze_file`
  - `OK query_knowledge`
  - `OK calculate_dispersion`
  - `OK render_spatial_map`
  - `Total tools: 7`

### 真实模型 smoke

执行：

```bash
pytest tests/test_real_model_integration.py -v -s 2>&1 | head -50
```

已确认输出前 50 行中包含：

- 36 个真实 surrogate 模型成功加载
- 特征维度检查通过
- `test_real_macro_to_dispersion_20links` 通过
- 六个气象预设场景通过
- roughness 0.05 / 0.5 / 1.0 场景通过
- `spatial_renderer` 集成通过

## 六、已知限制

- `sparse_topk` 模式下的道路贡献记录是面向 top-k 归因的近似存储，不是全量稠密矩阵
- `coverage_assessment` 当前使用凸包面积和 200m buffer 连通性做快速评估，适合语义分级，不等同于严格的路网图论分析
- `raster_grid` 当前输出仍是后端数据结构，前端渲染仍沿用旧的 receptor circle layer；真正的 raster/heatmap 呈现留到后续任务
- 热点源归因工具本身尚未实现，本次只提供数据基础

## 七、下一步（Sub-task B）

Sprint 11 / 12 后续工作建议：

1. 修改 `tools/spatial_renderer.py`，优先渲染 `raster_grid.cell_centers_wgs84`，替代当前 CircleMarker 离散散点效果
2. 在前端加入 coverage badge / warning 文案，使 `complete_regional` / `partial_regional` / `sparse_local` 的语义直接可见
3. 新建 `analyze_hotspots` 工具
   - 基于 `raster_grid.cell_receptor_map`
   - 结合 `road_contributions.receptor_top_roads`
   - 输出热点 cell 的主要来源道路排序
4. 进一步评估大路网场景下 `sparse_topk` 贡献追踪的性能与精度边界
