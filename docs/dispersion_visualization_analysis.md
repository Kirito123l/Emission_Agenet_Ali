# 路网排放 → 扩散计算 → 栅格化 → 前端可视化链路分析

本文基于当前代码实现梳理 EmissionAgent 中“宏观排放结果 → 扩散 surrogate 推理 → 栅格化 → Leaflet 前端渲染”的完整链路。重点放在每一步的数据结构、单位换算、调用关系和可改造切入点。

## 一、数据流总览

### 1.1 主链路

- 宏观排放工具 [tools/macro_emission.py#L832](/home/kirito/Agent1/emission_agent/tools/macro_emission.py#L832) 会把原始输入里的 `geometry` 合并回 `result["data"]["results"]`，这样下游扩散可以直接从 `_last_result.data.results[*].geometry` 取到道路几何。
- Router 在 [core/router.py#L535](/home/kirito/Agent1/emission_agent/core/router.py#L535) 的 `_prepare_tool_arguments()` 中，为 `calculate_dispersion` / `analyze_hotspots` / `render_spatial_map` 自动注入 `_last_result`。
- 扩散工具 [tools/dispersion.py#L77](/home/kirito/Agent1/emission_agent/tools/dispersion.py#L77) 调用 `EmissionToDispersionAdapter.adapt()`，把宏观排放结果转换为：
  - `roads_gdf`: `GeoDataFrame(NAME_1, geometry)`
  - `emissions_df`: `DataFrame(NAME_1, data_time, nox, length)`
- 扩散计算器 [calculators/dispersion.py#L1040](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1040) 完成：
  - 几何投影与本地化
  - 每 10m 分段
  - 受体生成
  - 气象处理
  - surrogate 推理
  - 结果组装为 `results + concentration_grid + raster_grid + road_contributions`
- 扩散工具的 `ToolResult.map_data` 在 [tools/dispersion.py#L551](/home/kirito/Agent1/emission_agent/tools/dispersion.py#L551) 中只是一层轻封装，核心内容仍是 `concentration_grid` 和 `raster_grid`。
- 空间渲染工具 [tools/spatial_renderer.py#L124](/home/kirito/Agent1/emission_agent/tools/spatial_renderer.py#L124) 根据 `layer_type` 把扩散结果转换成前端可消费的 `map_data.layers[*].data`（GeoJSON）。
- 前端 `web/app.js` 在 [web/app.js#L1845](/home/kirito/Agent1/emission_agent/web/app.js#L1845) 开始分发地图类型，最终用 Leaflet 渲染：
  - 栅格：`L.geoJSON(Polygon cells)`，见 [web/app.js#L2623](/home/kirito/Agent1/emission_agent/web/app.js#L2623)
  - 受体点：`L.circleMarker`，见 [web/app.js#L3092](/home/kirito/Agent1/emission_agent/web/app.js#L3092)
  - 热点：栅格背景 + hotspot polygon + label + 贡献路段高亮，见 [web/app.js#L2684](/home/kirito/Agent1/emission_agent/web/app.js#L2684)

### 1.2 Mermaid 数据流图

```mermaid
flowchart TD
    A[calculate_macro_emission\nToolResult.data.results[*]\nlink_id + geometry + total_emissions_kg_per_hr + link_length_km] --> B[Router _prepare_tool_arguments\n注入 _last_result]
    B --> C[DispersionTool.execute]
    C --> D[EmissionToDispersionAdapter.adapt]
    D --> D1[roads_gdf\nNAME_1 + geometry]
    D --> D2[emissions_df\nNAME_1 + data_time + nox + length]
    D1 --> E[DispersionCalculator.calculate]
    D2 --> E
    E --> E1[_merge_roads_and_emissions\nkg/h -> g/s/m²]
    E1 --> E2[_transform_to_local\nWGS84 -> UTM -> local]
    E2 --> E3[_segment_roads\n每10m一个source segment]
    E3 --> E4[_generate_receptors\n近路受体 + 背景受体]
    E4 --> E5[predict_time_series_xgb\n风向旋转 + 稳定度选模 + 分方向推理]
    E5 --> F[result_data]
    F --> F1[results\n每个受体的 time-series / mean / max]
    F --> F2[concentration_grid\nreceptors + bounds]
    F --> F3[raster_grid\nmatrix_mean/max + cell_centers + cell_receptor_map]
    F --> F4[road_contributions\nper receptor top roads]
    F --> G[SpatialRendererTool]
    G --> G1[raster GeoJSON polygons]
    G --> G2[concentration GeoJSON points]
    G --> G3[hotspot overlay GeoJSON]
    G1 --> H[web/app.js]
    G2 --> H
    G3 --> H
    H --> I[Leaflet + Carto basemap\nL.geoJSON / L.circleMarker]
```

### 1.3 关键数据结构总览

#### 宏观排放结果的下游关键字段

代码来源：[tools/macro_emission.py#L832](/home/kirito/Agent1/emission_agent/tools/macro_emission.py#L832)、[tools/macro_emission.py#L937](/home/kirito/Agent1/emission_agent/tools/macro_emission.py#L937)

```python
{
    "results": [
        {
            "link_id": "R001",
            "link_length_km": 0.82,
            "traffic_flow_vph": 1800,
            "avg_speed_kph": 42.0,
            "total_emissions_kg_per_hr": {
                "CO2": 123.45,
                "NOx": 1.87,
                "PM2.5": 0.09,
            },
            "emission_rates_g_per_veh_km": {
                "CO2": 165.2,
                "NOx": 2.5,
                "PM2.5": 0.12,
            },
            "geometry": "LINESTRING (...)"  # 或 GeoJSON / 坐标数组
        }
    ],
    "summary": {...},
    "scenario_label": "baseline"
}
```

#### 扩散结果核心结构

代码来源：[calculators/dispersion.py#L1580](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1580)

```python
{
    "query_info": {
        "pollutant": "NOx",
        "n_roads": 128,
        "n_receptors": 5342,
        "n_time_steps": 1,
        "roughness_height": 0.5,
        "met_source": "preset",
        "local_origin": {"x": 351223.8, "y": 3456781.2},
        "display_grid_resolution_m": 50.0,
    },
    "results": [...],               # 每个受体的详细结果
    "summary": {...},               # 受体数、平均/最大浓度
    "concentration_grid": {...},    # 点级结果
    "raster_grid": {...},           # 显示用栅格
    "road_contributions": {...},    # 每个受体 top road 贡献
}
```

## 二、排放到扩散的数据转换

### 2.1 `_last_result` 如何从上游进入扩散工具

- Router 只对 `render_spatial_map`、`calculate_dispersion`、`analyze_hotspots` 自动注入 `_last_result`，见 [core/router.py#L555](/home/kirito/Agent1/emission_agent/core/router.py#L555)。
- 对 `calculate_dispersion`，如果 fact memory 里的 `last_spatial_data.results[*]` 看起来像宏观排放结果，就包装成 `{"success": True, "data": spatial}` 注入，见 [core/router.py#L592](/home/kirito/Agent1/emission_agent/core/router.py#L592)。
- `DispersionTool._resolve_emission_source()` 要求 `_last_result.data.results` 是非空列表，并且样本项至少包含 `total_emissions_kg_per_hr` 或 `link_length_km`，见 [tools/dispersion.py#L176](/home/kirito/Agent1/emission_agent/tools/dispersion.py#L176)。

这意味着扩散模块当前并不是“通用排放输入”，而是“带几何的宏观排放输出”的后续步骤。

### 2.2 `EmissionToDispersionAdapter` 做了什么

核心实现见 [calculators/dispersion_adapter.py#L25](/home/kirito/Agent1/emission_agent/calculators/dispersion_adapter.py#L25)。

它做了两件事：

1. 从 `macro_result.data.results[*]` 提取道路几何，构造 `roads_gdf`
2. 从 `macro_result.data.results[*].total_emissions_kg_per_hr["NOx"]` 和 `link_length_km` 构造 `emissions_df`

#### 输出一：`roads_gdf`

由 `_extract_geometry()` 生成，见 [calculators/dispersion_adapter.py#L49](/home/kirito/Agent1/emission_agent/calculators/dispersion_adapter.py#L49)。

```python
GeoDataFrame(
    columns=["NAME_1", "geometry"],
    crs="EPSG:4326"
)
```

- `NAME_1` 来自 `link_id`
- `geometry` 支持：
  - shapely geometry
  - WKT string
  - GeoJSON dict
  - `{"geometry": ...}` / `{"wkt": ...}` 嵌套结构
  - `[[lon, lat], ...]` 坐标数组  
  解析逻辑见 [calculators/dispersion_adapter.py#L95](/home/kirito/Agent1/emission_agent/calculators/dispersion_adapter.py#L95)。

#### 输出二：`emissions_df`

由 `_build_emissions_df()` 生成，见 [calculators/dispersion_adapter.py#L126](/home/kirito/Agent1/emission_agent/calculators/dispersion_adapter.py#L126)。

```python
DataFrame(
    columns=["NAME_1", "data_time", "nox", "length"]
)
```

- `NAME_1` = `link_id`
- `data_time` = 原结果里的 `data_time`，缺失时用 `2024-01-01 00:00:00`
- `nox` = `total_emissions_kg_per_hr["NOx"]`
- `length` = `link_length_km`

当前实现把污染物写死为 `NOx`，见 [calculators/dispersion_adapter.py#L45](/home/kirito/Agent1/emission_agent/calculators/dispersion_adapter.py#L45)、[calculators/dispersion.py#L1136](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1136)。`calculate_dispersion` 的 `pollutant` 参数虽然存在，但计算器会拒绝除 `NOx` 外的污染物。

### 2.3 必需字段与可选字段

#### 必需字段

- `macro_result.status == "success"`，见 [calculators/dispersion_adapter.py#L38](/home/kirito/Agent1/emission_agent/calculators/dispersion_adapter.py#L38)
- `macro_result.data.results` 为非空列表，见 [calculators/dispersion_adapter.py#L41](/home/kirito/Agent1/emission_agent/calculators/dispersion_adapter.py#L41)
- 每条有效路段至少要有：
  - `link_id`
  - `geometry`
  - `total_emissions_kg_per_hr["NOx"]`
  - `link_length_km`

#### 可选字段

- `data_time`：缺失时补默认时间
- `width`：没有时在扩散计算器中补成默认 `7.0m`，见 [calculators/dispersion.py#L1189](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1189)
- `scenario_label`：用于结果存取，不参与计算，见 [tools/dispersion.py#L115](/home/kirito/Agent1/emission_agent/tools/dispersion.py#L115)

### 2.4 线源强度换算公式与单位链

实现见 [calculators/dispersion.py#L949](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L949)。

公式：

```text
line_source_strength = nox_kg_h * 1000 / 3600 / (length_km * 1000 * road_width_m)
```

单位链：

```text
kg/h per link
→ ×1000
g/h per link
→ ÷3600
g/s per link
→ ÷(length_km × 1000)
g/s/m per link length
→ ÷road_width_m
g/s/m²
```

这里的物理含义是：把整条路段在一小时内的 `NOx kg/h` 排放均匀摊成一个“道路面源强度”，供 surrogate 作为 source strength 使用。

## 三、扩散计算核心流程

### 3.1 `DispersionTool.execute()` 的控制流

代码见 [tools/dispersion.py#L77](/home/kirito/Agent1/emission_agent/tools/dispersion.py#L77)。

完整执行步骤：

1. 解析参数：`meteorology`、`roughness_height`、`grid_resolution`、`pollutant`
2. 从 `_last_result` 解析上游排放结果
3. `EmissionToDispersionAdapter.adapt()` 转成 `roads_gdf + emissions_df`
4. `assess_coverage(roads_gdf)` 生成覆盖度说明
5. `_build_met_input()` 处理气象输入
6. 获取 `DispersionCalculator`
7. 把 `grid_resolution` 写到 `calculator.config.display_grid_resolution_m`
8. 调用 `calculator.calculate(...)`
9. 把 `coverage_assessment`、`meteorology_used`、`scenario_label` 填回结果
10. 把 `concentration_grid`/`raster_grid` 封装为 `map_data`

一个关键事实是：`grid_resolution` 只影响第 7 步传入的 `display_grid_resolution_m`，最终只在 `aggregate_to_raster()` 里使用；它不会改变受体生成密度，也不会改变 surrogate 推理分辨率，见 [tools/dispersion.py#L134](/home/kirito/Agent1/emission_agent/tools/dispersion.py#L134)、[calculators/dispersion.py#L1604](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1604)。

### 3.2 气象参数如何处理

实现见 [tools/dispersion.py#L223](/home/kirito/Agent1/emission_agent/tools/dispersion.py#L223) 与 [calculators/dispersion.py#L1341](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1341)。

支持四类输入：

1. 预设名：如 `urban_summer_day`
2. 预设 + 覆盖：如预设基础上覆盖 `wind_speed`
3. `custom`
4. `.sfc` 文件路径

处理规则：

- 预设加载来自 [config/meteorology_presets.yaml](/home/kirito/Agent1/emission_agent/config/meteorology_presets.yaml)，由 [tools/dispersion.py#L302](/home/kirito/Agent1/emission_agent/tools/dispersion.py#L302) 读取。
- `custom` 时会补出 `monin_obukhov_length` 和 `H`，见 [tools/dispersion.py#L257](/home/kirito/Agent1/emission_agent/tools/dispersion.py#L257)。
- `.sfc` 文件会在 [calculators/dispersion.py#L1371](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1371) 读取并重新分类稳定度。

计算器最终只消费一个规范化后的 `DataFrame`，列为：

```python
["Date", "WSPD", "WDIR", "MixHGT_C", "L", "H", "Stab_Class"]
```

### 3.3 道路投影到 UTM 与本地化

实现见 [calculators/dispersion.py#L1210](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1210)。

处理流程：

1. 从 `geometry` 中抽出所有线坐标，见 [calculators/dispersion.py#L1221](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1221)
2. 用 `pyproj.Transformer` 从 `source_crs` 转到配置的 UTM CRS，见 [calculators/dispersion.py#L167](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L167)
3. 收集所有 UTM 点，取全局 `min_x/min_y` 作为 local origin，见 [calculators/dispersion.py#L677](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L677)
4. 每条线的 `new_coords = (utm_x-origin_x, utm_y-origin_y)`，见 [calculators/dispersion.py#L1241](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1241)

这样做的结果是：

- 推理全部在米制局部坐标系里完成
- 输出时再反变换回 WGS84，见 [calculators/dispersion.py#L685](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L685)

### 3.4 每 10m 分段逻辑

实现见 [calculators/dispersion.py#L319](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L319) 与 [calculators/dispersion.py#L1255](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1255)。

规则：

- `segment_interval_m` 默认 `10.0m`
- 对每条 polyline 按累计长度切分
- 每一段只保留一个中点 `(xm, ym)` 和道路局部朝向 `angle_deg`

结果 `segments_df` 结构：

```python
{
    "road_id": 12,
    "road_idx": 12,
    "NAME_1": "R001",
    "segment_id": "12_34",
    "xm": 428.7,
    "ym": 193.5,
    "angle_deg": 71.3,
    "interval": 10.0,
}
```

随后 `_build_source_arrays()` 把这些 segment 按时间复制，与每个时间片上的道路排放强度拼接成 `sources_re.shape == (T, N_segments, 4)`，见 [calculators/dispersion.py#L1304](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1304)。

每个 source 的 4 列分别是：

```python
[xm, ym, emission_strength_g_s_m2, road_angle_deg]
```

### 3.5 受体生成算法

实现见 [calculators/dispersion.py#L210](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L210) 与 [calculators/dispersion.py#L1287](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1287)。

当前“受体网格”并不是规则方格，而是两类点的混合：

1. **近路受体**
2. **背景受体**

#### 近路受体

对每条 road：

- 先构造一个矩形道路缓冲区，半宽 = `0.5 * width + buffer_extra`，见 [calculators/dispersion.py#L183](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L183)
- 默认 `width=7m`，`buffer_extra=3m`，所以默认缓冲半宽是 `6.5m`
- 然后在缓冲区外两侧再偏移 `offset_rule` 指定的距离，默认来自 [calculators/dispersion.py#L42](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L42)：

```python
{3.5: 40, 8.5: 40}
```

这表示：

- 第一圈受体在距道路中心线约 `6.5 + 3.5 = 10m`
- 第二圈受体在距道路中心线约 `6.5 + 8.5 = 15m`
- 沿路每 `40m` 采一个点
- 左右两侧都布点

“缓冲外偏移”的具体含义就是：点不是放在 road polygon 内，而是放在该矩形缓冲区之外若干米的位置，见 [calculators/dispersion.py#L246](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L246)。

#### 背景受体

- 在整个路网范围 bbox 上按 `background_spacing_m=50m` 生成规则背景点，见 [calculators/dispersion.py#L289](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L289)
- 生成后统一删除所有落在道路缓冲区内的点，见 [calculators/dispersion.py#L312](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L312)

因此最终受体集合是：

```text
近路条带受体（10m / 15m 两圈） + 全域50m背景网格 - 道路缓冲内点
```

### 3.6 surrogate 模型推理流程

实现主函数是 [calculators/dispersion.py#L375](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L375)。

完整步骤如下：

1. 对每个时间步读取该时刻气象：
   - `WSPD`
   - `WDIR`
   - `L`
   - `H`
   - `MixHGT_C`
   - `Stab_Class`
2. 对所有受体坐标和所有 source segment 坐标，按风向做坐标旋转，见 [calculators/dispersion.py#L477](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L477)
3. 构造 source-relative 坐标：
   - `x_hat = receptor_x_rot - source_x_rot`
   - `y_hat = receptor_y_rot - source_y_rot`
4. 按 `x_hat` 符号分成：
   - `x0` 模型：下风向，范围 `[0, 1000]`
   - `x-1` 模型：上风向，范围 `[-100, 0]`
5. 限制 `y_hat` 在横风范围 `[-100, 100]`
6. 计算道路相对风向，取 `sin/cos`
7. 根据稳定度选择特征模板：
   - `VS / S / N1` 不带 `MixHGT_C`
   - `N2 / U / VU` 带 `MixHGT_C`
8. 分 batch 调用 XGBoost 模型预测
9. 把 surrogate 输出乘上 source strength，累加到每个 receptor 的浓度

正向/反向模型的贡献计算都使用：

```python
contrib = preds * strength[s_idx] / 1e-6
```

见 [calculators/dispersion.py#L531](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L531)、[calculators/dispersion.py#L593](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L593)。

### 3.7 36 个 XGBoost JSON 系数文件如何组织与加载

路径解析见 [calculators/dispersion.py#L966](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L966)。

维度：

- 稳定度 6 类：`VS / S / N1 / N2 / U / VU`
- 粗糙度 3 档：`0.05 -> L`, `0.5 -> M`, `1.0 -> H`
- 方向 2 个：`x0` / `x-1`

总数：

```text
6 × 3 × 2 = 36
```

命名规则：

```text
model_RLINE_remet_multidir_{stability}[_2000]_x0_{L|M|H}.json
model_RLINE_remet_multidir_{stability}[_2000]_x-1_{L|M|H}.json
```

说明：

- `neutral1` 和 `neutral2` 文件名没有 `_2000`
- 其他稳定度有 `_2000`

默认模型目录优先级见 [calculators/dispersion.py#L118](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L118)：

1. `calculators/data/dispersion_models/`
2. `ps-xgb-aermod-rline-surrogate/models/`

加载策略：

- `DispersionCalculator._ensure_models_loaded()` 只初始化缓存，不一次性把 36 个模型全读进来，见 [calculators/dispersion.py#L1477](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1477)
- 真正按稳定度懒加载发生在 `_get_or_load_model()`，见 [calculators/dispersion.py#L1489](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1489)
- 每个稳定度一次加载 2 个方向模型

### 3.8 贡献路段追踪

主实现见 [calculators/dispersion.py#L430](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L430)、[calculators/dispersion.py#L872](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L872)。

做法：

1. 在推理阶段不只算总浓度，同时把每个 receptor 上每个 source segment 的贡献按 `road_idx` 归并
2. 如果 `n_receptors × n_roads` 不大，就走 `dense_exact`
3. 否则走 `sparse_topk`
4. 最终每个 receptor 只保留 top-k 路段
5. 结果通过 `_serialize_road_contributions()` 加上 `road_id_map`，见 [calculators/dispersion.py#L919](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L919)

输出结构示例：

```python
{
    "receptor_top_roads": {
        "17": [
            {"road_idx": 2, "road_id": "R003", "contribution": 3.12},
            {"road_idx": 8, "road_id": "R014", "contribution": 1.07},
        ]
    },
    "road_id_map": ["R001", "R002", "R003", "..."],
    "top_k": 10,
    "effective_timesteps": 1,
    "tracking_mode": "dense_exact",
}
```

这些信息后续不是给前端直接画，而是给热点分析做“热点源归因”。

### 3.9 当前实现里可以直接看出的性能瓶颈

#### 1. 推理阶段的成对矩阵

`x_hat` / `y_hat` 是 `n_receptors × n_sources` 级别的矩阵，见 [calculators/dispersion.py#L486](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L486)。当路段很多、分段很细、受体很多时，这是主要的 CPU/内存压力源。

#### 2. 贡献追踪的 Python 循环

稀疏模式下逐 receptor/road 做 Python dict 累加，见 [calculators/dispersion.py#L542](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L542)、[calculators/dispersion.py#L604](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L604)。

#### 3. 前端栅格绘制是“每格一个 Polygon”

Leaflet 侧没有 Canvas heatmap 或 WebGL raster，栅格图层是 `L.geoJSON(features)`，每个非零 cell 都是一个 polygon，见 [web/app.js#L2641](/home/kirito/Agent1/emission_agent/web/app.js#L2641)。当非零单元很多时，前端也会变慢。

#### 4. `grid_resolution` 只降显示复杂度，不降推理复杂度

因为受体生成还是固定近路圈 + 50m 背景点，见 [calculators/dispersion.py#L1292](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1292)。所以把 `grid_resolution` 从 50 改到 200，只会减少栅格展示单元数量，不会减少 surrogate 计算量。

## 四、栅格化实现细节

### 4.1 代码位置与方法

栅格化实现在 [calculators/dispersion.py#L709](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L709) 的 `aggregate_to_raster()`。

它不是插值，也不是重新求解浓度场，而是一个**显示层聚合**：

1. 把每个受体点 `(local_x, local_y)` 按 `resolution_m` 分箱到 `(row, col)`
2. 同一格里计算：
   - `matrix_sum`
   - `matrix_count`
   - `matrix_max`
   - `matrix_mean = sum / count`
3. 只对 `matrix_mean > 0` 的格子生成 `cell_centers_wgs84`

所以当前方法是：

```text
规则网格对齐 + 格内聚合（mean/max） + 无插值
```

### 4.2 `raster_grid` 的完整数据结构

来源：[calculators/dispersion.py#L830](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L830)

一个实际形态大致如下：

```python
{
    "matrix_mean": [
        [0.0, 0.0, 1.234, 2.118],
        [0.0, 0.842, 3.551, 1.905],
    ],
    "matrix_max": [
        [0.0, 0.0, 1.876, 2.900],
        [0.0, 1.220, 4.018, 2.333],
    ],
    "bbox_local": [0.0, 0.0, 1450.0, 900.0],
    "bbox_wgs84": [121.4123, 31.2011, 121.4278, 31.2104],
    "resolution_m": 50.0,
    "rows": 19,
    "cols": 30,
    "nodata": 0.0,
    "cell_receptor_map": {
        "3_8": [17, 18],
        "3_9": [19],
        "4_9": [20, 21, 22],
    },
    "cell_centers_wgs84": [
        {
            "row": 3,
            "col": 8,
            "lon": 121.4182,
            "lat": 31.2056,
            "mean_conc": 1.234,
            "max_conc": 1.876,
        }
    ],
    "stats": {
        "total_cells": 570,
        "nonzero_cells": 116,
        "coverage_pct": 20.35,
        "occupied_cells": 143,
    },
}
```

### 4.3 栅格与受体点的关系

不是 1 对 1。

- 一个 cell 可以聚合多个 receptor，证据是 `cell_receptor_map["row_col"] -> [receptor_idx, ...]`，见 [calculators/dispersion.py#L780](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L780)
- 聚合值默认用 `matrix_mean`
- 同时保留 `matrix_max`

因此关系是：

```text
many receptors → one raster cell
```

没有任何空间插值、平滑、IDW、Kriging 或 bicubic 操作。

### 4.4 `grid_resolution` 参数如何控制栅格密度

`grid_resolution` 进入 [tools/dispersion.py#L94](/home/kirito/Agent1/emission_agent/tools/dispersion.py#L94)，被写入 `calculator.config.display_grid_resolution_m`，见 [tools/dispersion.py#L134](/home/kirito/Agent1/emission_agent/tools/dispersion.py#L134)。

后续只在 [calculators/dispersion.py#L1604](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1604) 调用 `aggregate_to_raster(..., resolution_m=self.config.display_grid_resolution_m)`。

所以它控制的是：

- `row/col` 分箱大小
- 栅格 polygon 的边长
- 前端显示单元数量

它不控制：

- 近路受体圈数
- 背景受体 spacing
- surrogate 计算精度

### 4.5 当前方法的优缺点

#### 优点

- 实现简单，完全可追溯
- 保留 `cell_receptor_map`，方便热点分析反查贡献路段
- 不会引入额外插值误差
- `matrix_mean` / `matrix_max` 并存，适合不同后处理

#### 缺点

- 图面呈现是块状离散格，不连续
- 受体布局本身非规则，所以直接分箱会把“近路高密条带受体”和“背景网格受体”混在一起
- `resolution` 变粗只是聚合更粗，并不是真正意义上的连续浓度场重建
- 若后续想做等值面，现有 `cell_centers_wgs84` 是有用的，但还需要插值或直接基于 `matrix_mean` 做 contour

### 4.6 对热点分析的影响

热点分析直接依赖：

- `raster_grid.matrix_mean`，见 [calculators/hotspot_analyzer.py#L114](/home/kirito/Agent1/emission_agent/calculators/hotspot_analyzer.py#L114)
- `raster_grid.cell_receptor_map`，见 [calculators/hotspot_analyzer.py#L446](/home/kirito/Agent1/emission_agent/calculators/hotspot_analyzer.py#L446)
- `road_contributions.receptor_top_roads`

所以如果改掉 `raster_grid` 的结构，需要同时考虑 hotspot 路径是否还能拿到：

1. 2D 聚类基底
2. cell → receptor 的映射

## 五、前端可视化实现

### 5.1 地图库与整体渲染方式

- 地图库是 **Leaflet 1.9.4**，由 [web/index.html#L26](/home/kirito/Agent1/emission_agent/web/index.html#L26) 引入
- 底图是 **Carto light_nolabels**，标签图层是 `light_only_labels`
- 所有地图都通过 `web/app.js` 动态生成容器并初始化 Leaflet

扩散相关的三个主分支：

- `renderRasterMap()`，见 [web/app.js#L2806](/home/kirito/Agent1/emission_agent/web/app.js#L2806)
- `renderConcentrationMap()`，见 [web/app.js#L3016](/home/kirito/Agent1/emission_agent/web/app.js#L3016)
- `renderHotspotMap()`，见 [web/app.js#L2860](/home/kirito/Agent1/emission_agent/web/app.js#L2860)

### 5.2 `map_data` 到前端后的分发逻辑

主入口见 [web/app.js#L1868](/home/kirito/Agent1/emission_agent/web/app.js#L1868)。

逻辑：

1. `renderMapData(map_data, msgContainer)`
2. `getMapPayloadItems()` 处理单 map 或 map collection
3. `hasRenderableSingleMapData()` 判断类型
4. `renderSingleMapData()` 根据类型进入：
   - hotspot
   - raster
   - concentration
   - emission

一个关键分支是 [web/app.js#L1856](/home/kirito/Agent1/emission_agent/web/app.js#L1856)：

- 如果 `type=concentration` 但同时带 `raster_grid`
- 前端会优先走 `renderRasterMap()`

这意味着扩散工具虽然默认 `map_data.type = "concentration"`，但只要结果里带 `raster_grid`，前端默认展示的是栅格版而不是受体点版。

### 5.3 浓度点如何封装成 GeoJSON

后端版本见 [tools/spatial_renderer.py#L362](/home/kirito/Agent1/emission_agent/tools/spatial_renderer.py#L362)，前端兜底版本见 [web/app.js#L2915](/home/kirito/Agent1/emission_agent/web/app.js#L2915)。

结构：

```python
{
    "type": "concentration",
    "layers": [
        {
            "id": "concentration_points",
            "type": "circle",
            "data": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [lon, lat]},
                        "properties": {
                            "receptor_id": 17,
                            "mean_conc": 1.234,
                            "max_conc": 2.118,
                            "value": 1.234,
                        },
                    }
                ],
            },
            "style": {
                "radius": 6,
                "color_field": "value",
                "color_scale": "YlOrRd",
                "value_range": [min, max],
                "opacity": 0.85,
                "legend_title": "NOx Concentration",
                "legend_unit": "μg/m³",
            },
        }
    ],
}
```

Leaflet 侧通过 `L.circleMarker` 逐点绘制，见 [web/app.js#L3174](/home/kirito/Agent1/emission_agent/web/app.js#L3174)。

### 5.4 栅格如何从 `cell_centers + resolution` 合成 polygon

后端版本见 [tools/spatial_renderer.py#L546](/home/kirito/Agent1/emission_agent/tools/spatial_renderer.py#L546)，前端兜底版本见 [web/app.js#L2108](/home/kirito/Agent1/emission_agent/web/app.js#L2108)。

做法：

1. 读 `raster_grid.cell_centers_wgs84`
2. 对每个 cell center，用 `resolution / 2` 按经纬度近似换算：
   - `dlat = (resolution/2) / 111320`
   - `dlon = (resolution/2) / (111320 * cos(lat))`
3. 生成一个 5 点闭合 polygon

这意味着前端真正画的是：

```text
GeoJSON Polygon cell polygons
```

而不是图片瓦片、Canvas raster、WebGL texture。

### 5.5 `map_data` 的完整结构

#### 栅格图层

来源：[tools/spatial_renderer.py#L632](/home/kirito/Agent1/emission_agent/tools/spatial_renderer.py#L632)

```python
{
    "type": "raster",
    "title": "NOx Concentration Field (50m grid)",
    "pollutant": "NOx",
    "center": [31.205, 121.418],
    "zoom": 13,
    "layers": [
        {
            "id": "concentration_raster",
            "type": "polygon",
            "data": {"type": "FeatureCollection", "features": [...]},
            "style": {
                "color_field": "value",
                "color_scale": "YlOrRd",
                "value_range": [0.0123, 8.4412],
                "opacity": 0.7,
                "stroke": False,
                "legend_title": "NOx Concentration",
                "legend_unit": "μg/m³",
                "resolution_m": 50.0,
            },
        }
    ],
    "coverage_assessment": {...},
    "summary": {
        "total_cells": 570,
        "nonzero_cells": 116,
        "resolution_m": 50.0,
        "mean_concentration": 0.8421,
        "max_concentration": 8.4412,
        "unit": "μg/m³",
    },
}
```

#### hotspot 图层

来源：[tools/spatial_renderer.py#L771](/home/kirito/Agent1/emission_agent/tools/spatial_renderer.py#L771)

它会把 `concentration_raster` 当作背景图层叠加，再加一层 `hotspot_areas` polygon。

### 5.6 栅格层的具体绘制方法

实现见 [web/app.js#L2623](/home/kirito/Agent1/emission_agent/web/app.js#L2623)。

Leaflet 侧：

```javascript
const rasterLayer = L.geoJSON(layer.data, {
    style: (feature) => ({
        fillColor: getRasterColor(value, minVal, maxVal),
        fillOpacity: style.opacity || 0.7,
        stroke: false,
        fill: true,
    }),
    onEachFeature: (feature, rasterCell) => {
        rasterCell.bindPopup(... mean/max ...)
    }
});
```

特点：

- 每个 cell 是一个独立 polygon feature
- popup 显示 `mean_conc` 和 `max_conc`
- 通过 `fitBounds(rasterLayer.getBounds())` 自动缩放到栅格范围

### 5.7 颜色映射实现

#### 栅格

实现见 [web/app.js#L2373](/home/kirito/Agent1/emission_agent/web/app.js#L2373)。

- 调色板是离散 `YlOrRd`
- 如果 `value <= 0` 或 `min <= 0`，走线性比例
- 否则走 `log10` 比例

也就是说栅格颜色映射是：

```text
低值/含零：linear
全正值：log-scaled
```

#### 受体点

实现见 [web/app.js#L3081](/home/kirito/Agent1/emission_agent/web/app.js#L3081)。

- 受体点颜色用固定 5 色梯度
- 纯线性分段，不做 log

所以当前“栅格图”和“受体点图”并不是同一套映射策略。

### 5.8 交互功能

当前已有交互：

- 地图平移/缩放：Leaflet 默认
- 图层控制：labels / 行政边界 / 路网底图 / 热点编号 / 贡献路段
- 点击 popup：
  - emission: 路段排放明细，见 [web/app.js#L3436](/home/kirito/Agent1/emission_agent/web/app.js#L3436)
  - concentration: 受体平均/最大浓度，见 [web/app.js#L3198](/home/kirito/Agent1/emission_agent/web/app.js#L3198)
  - raster: cell mean/max，见 [web/app.js#L2651](/home/kirito/Agent1/emission_agent/web/app.js#L2651)
  - hotspot: 区域统计 + top contributing roads，见 [web/app.js#L2721](/home/kirito/Agent1/emission_agent/web/app.js#L2721)

当前没有看到：

- 框选
- 时序播放
- 鼠标 hover 查询
- 地图截图/导出

### 5.9 当前是否支持导出/下载图片

当前没有地图导出实现。

证据：

- 前端检索 `html2canvas` / `leaflet-image` / `dom-to-image` / `jsPDF` / `toDataURL` 均无命中
- 现有 `downloadFile()` 只用于后端生成的表格文件下载，见 [web/app.js#L3603](/home/kirito/Agent1/emission_agent/web/app.js#L3603)

因此当前“下载”能力只覆盖 Excel/结果文件，不覆盖地图图片或地图矢量导出。

## 六、改造建议：用 Contourf 替代栅格化

### 6.1 从哪里切入

这里有两个层级的切入点。

#### 方案 A：先在 `spatial_renderer` 层做低风险原型

切入点：

- [tools/spatial_renderer.py#L546](/home/kirito/Agent1/emission_agent/tools/spatial_renderer.py#L546) `_build_raster_map()`

做法：

- 不改 surrogate 主计算和 `raster_grid` 结构
- 新增 `_build_contour_map()`，输入仍然是现有 `raster_grid`
- 从 `matrix_mean + bbox_local/bbox_wgs84 + resolution_m` 生成等值面 GeoJSON

优点：

- 对下游热点分析零侵入
- 不影响 `DispersionCalculator`
- 可以作为 `layer_type="contour"` 的新增显示分支

缺点：

- contour 只能基于现有的栅格聚合结果做，等值面质量受 `matrix_mean` 离散性约束

#### 方案 B：在 `calculators` 层增加“规范化 contour product”

切入点：

- [calculators/dispersion.py#L1502](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1502) `_assemble_result()`

做法：

- 在生成 `raster_grid` 后，同时生成 `contour_grid` 或 `isobands`
- 把 contour 作为标准输出的一部分
- `tools/spatial_renderer.py` 只做格式转换，不负责数值插值

优点：

- contour 可以变成扩散结果的一等公民
- hotspot、renderer、导出都能共享同一份 contour 数据

缺点：

- 要重新定义扩散结果 schema
- 若以后要保留 `cell_receptor_map` 给 hotspot，`raster_grid` 仍不能删除

如果目标是“尽快替换可视化风格”，建议先做方案 A；如果目标是“把 contour 变成正式分析产物”，建议做方案 B。

### 6.2 现有受体点是否足够做 contour

现有受体点足够做 contour，但要分两种情况看：

#### 用 `raster_grid.matrix_mean` 做 contour

- 已经是规则矩阵
- 可以直接 contour
- 不需要额外插值

这是最容易落地的路径。

#### 直接用 `concentration_grid.receptors` 做散点插值 contour

- 也可行
- 但当前受体布局是“近路条带 + 背景网格”的混合采样，不是均匀散点
- 直接对散点插值会把近路高密区域权重放大，可能形成沿道路的尖锐波纹

所以如果追求稳定可视化，建议优先：

```text
raster_grid.matrix_mean -> contour
```

而不是：

```text
raw receptors -> scattered interpolation -> contour
```

### 6.3 是否需要调整受体生成策略

如果 contour 只作为前端可视化层，不一定需要改受体生成策略。

如果希望 contour 兼具更平滑的“连续场”表达，可以考虑：

- 保留现有近路受体圈，用于近源精度
- 额外在 [calculators/dispersion.py#L1287](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1287) `_generate_receptors()` 中增加一套更规则的 background grid 作为 visualization mesh
- 或在 `aggregate_to_raster()` 之后单独对 `matrix_mean` 做轻度平滑

也就是说，改造 contourf 未必需要改 receptor generation；但如果要让 contour 更“像连续场”，增加更规则的背景采样会更稳。

### 6.4 建议用什么库

#### 服务端生成

建议优先：

- `contourpy` 或 `matplotlib.contourf`

理由：

- 已经有规则 `matrix_mean`
- 服务端可以直接从二维矩阵生成 isobands
- 输出 GeoJSON 最适合当前 Leaflet 架构

推荐产物格式：

1. **GeoJSON isobands**  
   最适合当前前端；可以继续走 `L.geoJSON`
2. **PNG overlay**  
   可做快速出图，但交互性差
3. **GeoTIFF**  
   更偏 GIS 数据交换，不适合当前前端直连

如果要保持现有前端改动最小，优先选：

```text
服务端 contour -> GeoJSON MultiPolygon
```

#### 前端生成

建议：

- `d3-contour`

前提：

- 前端必须拿到完整规则矩阵，而不只是 nonzero cell polygons
- 也就是直接消费 `raster_grid.matrix_mean + rows + cols + bbox_wgs84`

前端生成的优点是灵活；缺点是：

- 计算压力从后端转到浏览器
- 需要自己处理 matrix row/col 到地理坐标的映射
- hotspot 场景还要叠加多个图层，复杂度更高

结合当前 Leaflet 架构，我更推荐**服务端生成 contour GeoJSON**。

### 6.5 如果服务端生成，建议输出什么格式

推荐新增：

```python
"contour_bands": {
    "levels": [0.1, 0.5, 1.0, 2.0, 5.0],
    "geojson": {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "MultiPolygon", "coordinates": ...},
                "properties": {
                    "level_min": 0.5,
                    "level_max": 1.0,
                    "value": 0.5,
                },
            }
        ],
    },
}
```

这样 `tools/spatial_renderer.py` 可以直接新增 `_build_contour_map()` 输出：

```python
{
    "type": "contour",
    "layers": [
        {
            "id": "concentration_contours",
            "type": "polygon",
            "data": contour_bands["geojson"],
            "style": {...}
        }
    ]
}
```

### 6.6 如果前端生成，需要传什么数据结构

如果改成前端 contour，最少要把这些字段传给前端：

```python
{
    "matrix_mean": [[...], [...]],
    "rows": 19,
    "cols": 30,
    "bbox_wgs84": [min_lon, min_lat, max_lon, max_lat],
    "resolution_m": 50.0,
    "unit": "μg/m³",
    "pollutant": "NOx",
}
```

当前 `raster_grid` 已经基本具备这些字段，所以前端 contour 的数据输入并不缺。

### 6.7 对 `spatial_renderer.py` 需要做什么改动

如果采用低风险路径，建议改这些位置：

1. 在 [tools/spatial_renderer.py#L124](/home/kirito/Agent1/emission_agent/tools/spatial_renderer.py#L124) 的分发逻辑新增 `layer_type == "contour"`
2. 新增 `_build_contour_map()`，位置可以跟 `_build_raster_map()` 并列
3. 保留 `_build_raster_map()` 不动，因为 hotspot 仍依赖 raster 背景
4. 若要前端自动优先显示 contour，可调整 `map_data.type`

如果采用服务端 contour 规范化路径，还需要：

5. 在 [calculators/dispersion.py#L1502](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1502) `_assemble_result()` 中增加 `contour_bands`
6. 在 [tools/dispersion.py#L551](/home/kirito/Agent1/emission_agent/tools/dispersion.py#L551) `_build_map_data()` 中把 `contour_bands` 一并塞进 `map_data`

## 七、改造建议：添加地图导出/下载功能

### 7.1 当前地图库是否原生支持导出

Leaflet 本身不提供稳定的“整图导出 PNG/PDF”原生能力。

当前项目也没有引入：

- `leaflet-image`
- `html2canvas`
- `dom-to-image`
- `jsPDF`

所以答案是：**当前前端没有地图导出能力，也没有预置导出库。**

### 7.2 建议的实现方案

#### 方案 A：前端截图导出

候选：

- `html2canvas`
- `dom-to-image`

优点：

- 上手快
- 只需要改前端

风险：

- 当前底图是外部 Carto tile，截图时可能遇到跨域 / tainted canvas 问题
- 导出的结果受浏览器分辨率、缩放级别、异步瓦片加载状态影响

这个方案适合“先有一个能用的 PNG 导出按钮”，不适合高可靠论文图产出。

#### 方案 B：Leaflet 专用导出库

候选：

- `leaflet-image`

优点：

- 比通用 DOM 截图更贴近地图对象

风险：

- 仍然受第三方瓦片 CORS 影响
- 对复杂 overlay 组合稳定性一般

#### 方案 C：服务端静态出图

候选：

- `matplotlib + geopandas`
- 可选叠加 `contextily` 或直接使用本仓库 `static_gis` 数据

优点：

- 最可控，最适合论文/报告
- 能输出高分辨率 PNG / SVG / PDF
- 不依赖前端当前视图状态

代价：

- 需要新增后端导出接口和绘图逻辑

结合当前项目目标，我更推荐：

```text
前端快速按钮：html2canvas（低成本）
正式学术导出：服务端 matplotlib 静态制图（高可靠）
```

### 7.3 需要改哪些文件

#### 如果做前端截图导出

- [web/index.html](/home/kirito/Agent1/emission_agent/web/index.html)
  - 引入导出库
- [web/app.js](/home/kirito/Agent1/emission_agent/web/app.js)
  - 在 `renderRasterMap()` / `renderConcentrationMap()` / `renderHotspotMap()` 的 HTML 模板里加“导出地图”按钮
  - 新增 `exportMap(mapId)` 或 `downloadMapImage(mapId)` 函数

#### 如果做服务端静态导出

- 新增如 `api/map_export.py`
- 新增如 `services/map_exporter.py`
- 可能复用：
  - [tools/spatial_renderer.py](/home/kirito/Agent1/emission_agent/tools/spatial_renderer.py)
  - [calculators/dispersion.py](/home/kirito/Agent1/emission_agent/calculators/dispersion.py)
- 前端 `web/app.js` 只需要调用导出 API 并下载文件

### 7.4 导出格式建议

建议分层：

- **PNG**：默认格式，面向普通用户和汇报截图
- **SVG**：适合矢量图层（emission / contour / hotspot），适合论文后期编辑
- **PDF**：适合报告归档，但通常应由服务端生成

如果只选一个最实用的起点，建议先做：

```text
服务端 PNG 导出
```

因为它兼顾可控性和用户可用性。

## 结论

当前链路的本质是：

1. 宏观排放工具把 `geometry + total_emissions_kg_per_hr` 放进 `results[*]`
2. Router 通过 `_last_result` 把它传给扩散工具
3. Adapter 把结果改造成 `roads_gdf + emissions_df`
4. 扩散计算器在本地米制坐标中做分段 source + 受体点 surrogate 推理
5. `raster_grid` 只是显示层聚合，不是插值重建
6. 前端最终用 Leaflet 把 raster 画成一格一格的 polygon

如果后续要把“块状栅格图”改成“contourf 风格的连续等值填色图”，最稳的技术路径是：

- 短期：在 `tools/spatial_renderer.py` 基于 `raster_grid.matrix_mean` 增加 contour GeoJSON 生成
- 中期：在 `calculators/dispersion.py::_assemble_result()` 中把 contour 变成标准输出
- 并保留现有 `raster_grid`，因为热点分析仍然依赖 `matrix_mean + cell_receptor_map`
