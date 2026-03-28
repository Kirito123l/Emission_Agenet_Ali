# Sprint 8 Sub-task B Report

## 完成的改动列表

- 实现了 [calculators/dispersion.py](/home/kirito/Agent1/emission_agent/calculators/dispersion.py) 中的 `predict_time_series_xgb()`，替换掉 Sub-task A 的 `NotImplementedError` 占位实现。
- 在 [calculators/dispersion.py](/home/kirito/Agent1/emission_agent/calculators/dispersion.py) 中新增 `DispersionCalculator` 类，封装了 legacy `mode_inference.py` 的顶层执行流程。
- 新建 [calculators/dispersion_adapter.py](/home/kirito/Agent1/emission_agent/calculators/dispersion_adapter.py)，完成宏观排放结果到扩散输入的桥接。
- 修改 [calculators/__init__.py](/home/kirito/Agent1/emission_agent/calculators/__init__.py)，正式导出 `DispersionCalculator`。
- 扩展 [tests/test_dispersion_calculator.py](/home/kirito/Agent1/emission_agent/tests/test_dispersion_calculator.py)，新增推理、calculator、adapter 的单元测试和 smoke coverage。
- 清除了 `calculators/dispersion.py` 中的 `print()` 调用，统一改为 `logging`。
- 为当前 pandas 版本修复了 `.sfc` 读取兼容性，`read_sfc()` 使用 `sep=r"\\s+"` 替代已移除的 `delim_whitespace=True`。

## DispersionCalculator.calculate() 内部流程

入口在 [calculators/dispersion.py:699](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L699)。

执行顺序如下：

1. `_validate_inputs()`  
   位置: [calculators/dispersion.py:756](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L756)  
   校验 `roads_gdf` 必需列、`emissions_df` 必需列，以及当前仅允许 `pollutant="NOx"`。

2. `_merge_roads_and_emissions()`  
   位置: [calculators/dispersion.py:781](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L781)  
   按 `NAME_1` 连接道路几何和排放时序，处理 `NAME -> NAME_1` 兼容、宽度默认值、`data_time` 解析，以及 `nox_g_m_s2` 线源强度换算。

3. `_transform_to_local()`  
   位置: [calculators/dispersion.py:836](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L836)  
   将道路几何从输入 CRS 转 UTM，再平移到 local 坐标系 `(min_x, min_y) = (0, 0)`。

4. `_segment_roads()`  
   位置: [calculators/dispersion.py:881](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L881)  
   调用 `split_polyline_by_interval_with_angle()` 将每条路分成 10m 线源段，并记录段中心点和方向角。

5. `_generate_receptors()`  
   位置: [calculators/dispersion.py:912](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L912)  
   调用 `generate_receptors_custom_offset()` 生成近路受体和背景网格受体，再按 `(x, y)` 去重。

6. `_build_source_arrays()`  
   位置: [calculators/dispersion.py:929](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L929)  
   把 road segment midpoints 和 link-level emission 时序展开成 legacy surrogate 所需的 `sources_re.shape = (T, N_segments, 4)`。

7. `_process_meteorology()`  
   位置: [calculators/dispersion.py:966](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L966)  
   支持 4 类输入：
   - `.sfc` 文件
   - 预设名
   - DataFrame
   - Dict

8. `_align_sources_and_met()`  
   位置: [calculators/dispersion.py:1061](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1061)  
   处理 emission timestep 和 meteorology timestep 的对齐。当前支持：
   - 长度相等
   - 单个 emission timestep 复制到多个气象时步
   - 单个气象时步复制到多个 emission 时步

9. `_ensure_models_loaded()`  
   位置: [calculators/dispersion.py:1091](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1091)  
   懒加载 12 个模型，并缓存到实例上。

10. `predict_time_series_xgb()`  
    位置: [calculators/dispersion.py:366](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L366)  
    执行每小时、每受体、每线源段的 surrogate 推理与浓度累积。

11. `inverse_transform_coords()`  
    位置: [calculators/dispersion.py:605](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L605)  
    把 local receptor 坐标转回 WGS-84。

12. `_assemble_result()`  
    位置: [calculators/dispersion.py:1103](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L1103)  
    组装最终 payload，包括：
    - `query_info`
    - `results`
    - `summary`
    - `concentration_grid`

## predict_time_series_xgb 实现要点

实现位置: [calculators/dispersion.py:366-566](/home/kirito/Agent1/emission_agent/calculators/dispersion.py#L366)

与原始 [mode_inference.py:490-668](/home/kirito/Agent1/emission_agent/ps-xgb-aermod-rline-surrogate/mode_inference.py#L490) 保持一致的核心点：

- 按时间步循环。
- 用 `theta = deg2rad(270 - wind_deg)` 做全局旋转。
- 计算 `x_hat`, `y_hat = receptor_rot - source_rot`。
- 分开做 downwind 和 upwind 掩码。
- 继续沿用 legacy feature layout：
  - `VS/S/N1` 使用 7 维特征
  - `N2/U/VU` 使用 8 维特征
- 保留 `preds * strength / 1e-6` 的浓度累积公式。
- 保留 `np.add.at(total_conc, r_idx, contrib)` 的 receptor 累加方式。
- 返回结构仍是 `Date, Receptor_ID, Receptor_X, Receptor_Y, Conc`。

相对原脚本的改进：

- 用 `logging` 替换 `print`。
- 增加了 shape 校验和时间维度校验。
- 支持两类模型对象：
  - `xgb.XGBRegressor`
  - `xgb.Booster`（自动包 `xgb.DMatrix`）
- 同时兼容两种模型字典 key：
  - legacy `pos/neg`
  - 当前 loader `x0/x-1`
- 当 `met_df` 缺少 `Stab_Class` 时，会回退使用 `classify_stability()` 自动补齐。

注意：

- 需求描述里提到 `VS/S/N1` 时 “HC=0”。原始 `mode_inference.py` 实际做法不是把 HC 显式置零，而是直接走 7 维特征分支，不传 HC。这里保留了原始数值路径，优先满足“与 490-668 数值等价”的约束。
- `sources` 的列顺序保留为 legacy 实际顺序 `[x, y, strength, road_angle]`，因为原脚本就是按这个顺序 zip 和 reshape 的。

## Adapter 设计说明

实现位置: [calculators/dispersion_adapter.py](/home/kirito/Agent1/emission_agent/calculators/dispersion_adapter.py)

`EmissionToDispersionAdapter.adapt()` 做了三件事：

1. 从 macro result 中抽取排放字段，构造 `emissions_df`
   - `link_id -> NAME_1`
   - `total_emissions_kg_per_hr.NOx -> nox`
   - `link_length_km -> length`
   - 生成单时刻 `data_time`

2. 从以下来源抽取道路几何，构造 `roads_gdf`
   - `macro_result.data.results[*].geometry`
   - 外部 `geometry_source: List[Dict]`
   - 外部 `geometry_source: GeoDataFrame`

3. 解析多种 geometry 表达
   - WKT
   - GeoJSON
   - Shapely geometry
   - 简单坐标数组

兼容性处理：

- 如果部分 link 缺少 geometry，会记录 warning，但不会让整个 adapter 失败。
- 如果全部 geometry 缺失，会返回空 `roads_gdf` 和正常的 `emissions_df`，由上层 calculator 决定是否报错。

## 测试结果

新增/更新测试文件：

- [tests/test_dispersion_calculator.py](/home/kirito/Agent1/emission_agent/tests/test_dispersion_calculator.py)

本轮新增覆盖：

- `predict_time_series_xgb` smoke / 输出列 / 零排放
- `DispersionCalculator` 初始化 / 输入校验 / 气象处理 / 错误返回 / 成功 smoke / 结果组装
- `EmissionToDispersionAdapter` 基础适配 / 字段映射 / 外部 geometry source / 缺几何 warning

执行结果：

```text
pytest tests/test_dispersion_calculator.py -q
41 passed in 0.56s
```

```text
pytest
233 passed, 19 warnings in 5.75s
```

```text
python main.py health
OK query_emission_factors
OK calculate_micro_emission
OK calculate_macro_emission
OK analyze_file
OK query_knowledge
OK render_spatial_map
Total tools: 6
```

## 已知限制和 TODO

- 当前 surrogate pipeline 只支持 `NOx`。
- preset / dict 气象输入没有真实的 AERMOD `H` 字段时，当前用 `surface_heat_flux` 或 `temperature_k` 兜底；这足以完成结构化接口和测试，但不是最终物理上最严谨的方案。
- `sources` 与 `met` 的对齐目前支持 “等长” 和 “单时刻复制”；更复杂的基于时间戳 join 还没做。
- adapter 目前只把宏观排放结果桥接成 calculator 输入，还没有接到 tool 层和 router 执行链。
- `concentration_grid` 已准备好，但 `tools/spatial_renderer.py` 的 concentration branch 仍是 Sprint 9 占位实现。

## 下一步（Sub-task C）

- 新建 `tools/dispersion.py`，把 `DispersionCalculator` 接入现有 tool 注册体系。
- 将 `EmissionToDispersionAdapter` 接入 `calculate_macro_emission -> calculate_dispersion` 链路。
- 在 executor / router 层补齐参数标准化、默认气象预设选择和错误提示。
- 给 `render_spatial_map` 增加 concentration/distribution 图层渲染。
- 增加端到端测试：
  - macro emission result -> adapter -> dispersion calculator
  - dispersion result -> spatial renderer
