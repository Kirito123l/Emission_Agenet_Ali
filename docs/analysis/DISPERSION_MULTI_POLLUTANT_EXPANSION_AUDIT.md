# Dispersion Multi-Pollutant Expansion Audit

## 1. Executive Summary

本报告对当前仓库中 `calculate_dispersion` 主链路与 `ps-xgb-aermod-rline-surrogate` 原始代理模型目录进行了只读审计。结论如下：

- 当前系统把扩散计算限制为 `NOx`，主要来自 agent 集成层和工程实现层的硬编码，不是 PS-XGB-RLINE 方法本身天然只能计算 `NOx`。
- 原始 `ps-xgb-aermod-rline-surrogate` 目录中的 README 明确区分了“示例聚焦 NOx”和“方法可用于主要由物理扩散控制的污染物”。训练特征和推理特征不包含污染物类别，模型预测的是单位源强下的浓度响应，实际浓度通过源强线性缩放得到。
- 当前主工程的限制点集中在 `calculators/dispersion_adapter.py`、`calculators/dispersion.py`、`tools/dispersion.py`、`config/tool_contracts.yaml` 和测试数据中。它们把宏观排放结果里的 `total_emissions_kg_per_hr["NOx"]` 固定映射到 `nox`，并在计算器 `_validate_inputs()` 中直接拒绝非 `NOx`。
- 最小可行扩展不需要重训代理模型，但需要把“污染物字段选择”和“源强列命名”从 `NOx/nox` 泛化为动态 `pollutant`，并补足缺失污染物、单位、渲染、热点、benchmark 相关测试。
- 科学表述必须收敛：可称为“对排放清单中指定一次污染物进行近路物理扩散代理模拟”，不能直接声称覆盖 NOx-NO2-O3 化学转化、二次 PM 生成、沉降/湿沉降、背景浓度叠加或健康风险评估。
- 推荐先做单污染物 MVP：保留 `pollutant` 参数和默认 `NOx`，允许 `CO`、`PM2.5`、`PM10`、`CO2`、`THC` 等在配置允许范围内被选择；多污染物批量扩散应作为第二阶段。

## 2. Current End-to-End Dispersion Pipeline

### 2.1 控制流总览

当前扩散链路可以概括为：

```text
用户请求/LLM tool call
  -> config/tool_contracts.yaml 生成工具 schema
  -> core/assembler.py 注入工具定义
  -> core/router.py 决定工具链与 _last_result 注入
  -> core/executor.py 标准化参数并调用工具
  -> tools/dispersion.py: DispersionTool.execute()
  -> calculators/dispersion_adapter.py: EmissionToDispersionAdapter.adapt()
  -> calculators/dispersion.py: DispersionCalculator.calculate()
  -> result_data: results + concentration_grid + raster_grid + contour_bands + road_contributions
  -> core/context_store.py / core/router.py 保存 dispersion 结果
  -> tools/hotspot.py / tools/spatial_renderer.py / tools/scenario_compare.py 下游使用
```

关键证据：

- 工具合同从 `config/tool_contracts.yaml` 加载并生成 OpenAI function-calling schema：`tools/contract_loader.py:76-91`。
- `calculate_dispersion` 在合同中声明依赖 `emission`、产出 `dispersion`：`config/tool_contracts.yaml:439-441`。
- Executor 在执行前标准化参数，然后调用 `tool.execute(**standardized_args)`：`core/executor.py:219-264`。
- Router 会把上游结果注入给 `calculate_dispersion`、`analyze_hotspots`、`render_spatial_map`：`core/router.py:825-907`。
- 扩散结果会被保存到 session context store 和 legacy `last_spatial_data`：`core/router.py:775-810`、`core/context_store.py:76-90`。

### 2.2 Tool Contract 与参数入口

`calculate_dispersion` 的工具合同位于 `config/tool_contracts.yaml:347-430`，当前暴露参数包括：

| 参数 | 当前含义 | 证据 |
| --- | --- | --- |
| `emission_source` | 默认 `last_result`，理论上也可写 file path | `config/tool_contracts.yaml:351-357` |
| `meteorology` | 预设名、`custom` 或 `.sfc` 路径，默认 `urban_summer_day` | `config/tool_contracts.yaml:358-364` |
| `wind_speed` / `wind_direction` / `stability_class` / `mixing_height` | custom 或覆盖预设气象参数 | `config/tool_contracts.yaml:365-395` |
| `roughness_height` | 地表粗糙度，只允许 `0.05/0.5/1.0` | `config/tool_contracts.yaml:396-405` |
| `grid_resolution` | 展示栅格分辨率，默认 50 m | `config/tool_contracts.yaml:406-416` |
| `contour_resolution` | 等值带插值分辨率，默认 10 m | `config/tool_contracts.yaml:417-423` |
| `pollutant` | 当前描述为 “Currently only NOx”，默认 `NOx` | `config/tool_contracts.yaml:424-430` |
| `scenario_label` | 情景标签 | `config/tool_contracts.yaml:431-436` |

`tools/definitions.py` 只是从合同自动生成 `TOOL_DEFINITIONS`，不手写 schema；因此未来扩展必须同步修改 `config/tool_contracts.yaml`，否则 LLM 仍会看到“只支持 NOx”的能力边界。

### 2.3 Router / Executor 如何传参

Executor 做两件关键事情：

1. 使用 `StandardizationEngine.standardize_batch()` 标准化参数：`core/executor.py:322-348`。
2. 调用注册表中的工具实例：`core/executor.py:209-264`。

污染物标准化本身已支持多种污染物：

- `PARAM_TYPE_REGISTRY` 中 `pollutant` 和 `pollutants` 都注册为标准化类型：`services/standardization_engine.py:37-45`。
- `config/unified_mappings.yaml` 中污染物包含 `CO2`、`CO`、`NOx`、`PM2.5`、`PM10`、`THC`：`config/unified_mappings.yaml:213-260`。
- `UnifiedStandardizer` 构建 `pollutant_lookup`，支持中文名和别名标准化：`services/standardizer.py:93-107`、`services/standardizer.py:313-380`。

这说明“参数标准化层”并没有把扩散限制为 NOx。相反，用户说“二氧化碳扩散”会被标准化为 `CO2`，然后在扩散计算器校验阶段失败。

Router 还有一个 deterministic fallback：当用户请求扩散且消息中出现污染物时，会取第一个污染物作为 `pollutant` 传给 `calculate_dispersion`：`core/router.py:1158-1166`。这为未来单污染物 MVP 已经预留了上层行为入口。

### 2.4 `calculate_macro_emission` 结果如何流向扩散模块

宏观排放计算器本身支持多污染物：

- `POLLUTANT_TO_ID` 包含 `THC`、`CO`、`NOx`、`CO2`、`PM10`、`PM2.5` 等：`calculators/macro_emission.py:41-54`。
- `calculate()` 接收 `pollutants: List[str]`，并把它们写入 `query_info.pollutants`：`calculators/macro_emission.py:86-121`。
- 单路段结果中 `total_emissions_kg_per_hr` 是按污染物名动态生成的 dict：`calculators/macro_emission.py:199-207`。
- 计算过程逐污染物循环：`calculators/macro_emission.py:225-253`。
- 汇总结果 `summary.total_emissions_kg_per_hr` 同样按污染物动态汇总：`calculators/macro_emission.py:323-338`。

工具层会把原始输入中的 geometry 合并回宏观排放结果，供扩散使用：

- `tools/macro_emission.py:130-135` 在 `_fix_common_errors()` 中保留 geometry/geom/wkt/shape 等字段。
- `tools/macro_emission.py:832-844` 在返回前把原始 `links_data` 中的几何合并回 `result["data"]["results"]`。

Router 则负责把这一结果注入给扩散：

- 对宏观排放结果，如果 `results[*]` 有 `geometry`，会存入 `memory.fact_memory.last_spatial_data`：`core/router.py:789-798`。
- 对 `calculate_dispersion`，如果 `last_spatial_data.results[*]` 看起来像宏观排放结果，则包装成 `{"success": True, "data": spatial}` 注入 `_last_result`：`core/router.py:884-896`。
- `SessionContextStore` 也把 `calculate_macro_emission` 标为 `emission`，`calculate_dispersion` 标为依赖 `emission`：`core/context_store.py:76-90`。

### 2.5 `DispersionTool.execute()` 的工具层逻辑

入口位于 `tools/dispersion.py:59-193`。主要步骤：

1. 读取参数：`emission_source` 默认 `last_result`，`meteorology` 默认 `urban_summer_day`，`roughness_height` 默认 `0.5`，`pollutant` 默认 `NOx`，`grid_resolution` 默认 `50`：`tools/dispersion.py:93-103`。
2. 记录默认值：`tools/dispersion.py:105-120`。
3. 通过 `_resolve_emission_source()` 解析 `_last_result`，目前只支持 `last_result`，文件路径只记录 warning：`tools/dispersion.py:202-235`。
4. 调用 `EmissionToDispersionAdapter.adapt(emission_data)`：`tools/dispersion.py:133`。
5. 如果 `roads_gdf` 为空，返回“没有 geometry 不能扩散”：`tools/dispersion.py:134-139`。
6. 调 `assess_coverage()` 做路网覆盖评估：`tools/dispersion.py:141-146`。
7. 构建气象输入 `_build_met_input()`：`tools/dispersion.py:148`。
8. 按粗糙度缓存/获取 `DispersionCalculator`：`tools/dispersion.py:149`、`tools/dispersion.py:396-424`。
9. 调用 `calculator.calculate(..., pollutant=pollutant)`：`tools/dispersion.py:162-168`。
10. 成功后注入 `meteorology_used`、`scenario_label`、`roads_wgs84`、`defaults_used`，并生成 `map_data`：`tools/dispersion.py:179-193`。

### 2.6 `dispersion_adapter` 的输入转换

`EmissionToDispersionAdapter` 位于 `calculators/dispersion_adapter.py`。当前它输出两个对象：

```python
roads_gdf: GeoDataFrame(columns=["NAME_1", "geometry"], crs="EPSG:4326")
emissions_df: DataFrame(columns=["NAME_1", "data_time", "nox", "length"])
```

证据：

- docstring 明确写 `total_emissions_kg_per_hr.NOx -> nox`：`calculators/dispersion_adapter.py:32-36`。
- `adapt()` 固定调用 `_build_emissions_df(results, "NOx")`：`calculators/dispersion_adapter.py:45-47`。
- `_build_emissions_df()` 用 `pollutant.lower()` 作为列名，并从 `total_emissions_kg_per_hr[pollutant]` 取值：`calculators/dispersion_adapter.py:127-147`。它已有泛化雏形，但上层调用写死了 `"NOx"`。
- geometry 支持 shapely、WKT、GeoJSON、嵌套 dict、坐标数组：`calculators/dispersion_adapter.py:95-124`。

### 2.7 源强单位、长度单位与路宽假设

当前主工程中的单位桥接是：

```text
macro emission: kg/h per road link
length: km
road_width: m, default 7.0
line-source strength: g/(m2*s)

source_strength = emission_kg_h * 1000 / 3600 / (length_km * 1000 * road_width_m)
```

证据：

- 宏观排放结果字段名为 `total_emissions_kg_per_hr`：`calculators/macro_emission.py:199-207`。
- 宏观排放计算注释说明输出为 kg/hr：`calculators/macro_emission.py:235-250`。
- 扩散换算函数写明公式：`calculators/dispersion.py:963-976`。
- 默认路宽 `default_road_width_m = 7.0`：`calculators/dispersion.py:45-48`。
- 若道路输入中没有 `width`，扩散计算器填充默认路宽：`calculators/dispersion.py:1292-1294`。

原始 `ps-xgb-aermod-rline-surrogate/mode_inference.py` 中则有历史写法：

- `merged_gdf["nox_g_m_s2"] = merged_gdf["nox"] / (merged_gdf["length"] * 7 * 1000 * 3600)`：`ps-xgb-aermod-rline-surrogate/mode_inference.py:119-120`。
- 因此早期文档曾指出需要把宏观排放的 `kg/h` 转成 `g/h` 再进入该公式：`docs/reports/PHASE2_EXPLORATION_REPORT.md:1113-1119`。

当前主工程已通过 `* 1000` 修复了 `kg/h -> g/h` 的桥接问题。

### 2.8 为什么没有 geometry 就不能做空间扩散

扩散代理模型不是只根据总排放量算一个浓度值，而是需要每条道路的空间线源：

- `roads_gdf` 必须包含 `NAME_1` 和 `geometry`：`calculators/dispersion.py:1245-1248`。
- 如果 merge 后所有道路没有 geometry，会报错：`calculators/dispersion.py:1288-1290`。
- geometry 会被转换到 UTM 并本地化：`calculators/dispersion.py:1320-1356`。
- 线源分段依赖 `new_coords`：`calculators/dispersion.py:1358-1388`。
- 受体点生成也依赖道路坐标和道路 buffer：`calculators/dispersion.py:1390-1405`。

因此无 geometry 时，模型无法知道源在哪里、受体在哪里、风向坐标中每个受体相对每段道路的顺风/横风距离是多少。

### 2.9 线源切分与受体点生成

默认配置：

- 输入 CRS：`EPSG:4326`
- UTM：zone 51 north
- 线源分段间隔：10 m
- 默认路宽：7 m
- 近路受体偏移规则：`{3.5: 40, 8.5: 40}`
- 背景受体间距：50 m
- buffer extra：3 m
- 下风向计算范围：0 到 1000 m
- 上风向计算范围：-100 到 0 m
- 横风向范围：-100 到 100 m

证据：`calculators/dispersion.py:37-72`。

控制流：

- `_transform_to_local()` 将 WGS84 转 UTM，再减去全局最小 x/y 形成局部坐标：`calculators/dispersion.py:1320-1356`。
- `_segment_roads()` 调 `split_polyline_by_interval_with_angle()`，每 10 m 生成 source segment 中点和道路角度：`calculators/dispersion.py:1358-1388`。
- `_generate_receptors()` 调 `generate_receptors_custom_offset()` 生成近路受体和背景受体：`calculators/dispersion.py:1390-1405`。
- `_build_source_arrays()` 把 source segment 按时间展开，并拼成形状 `(T, N_sources, 4)` 的数组 `[source_x, source_y, emission_strength, road_angle_deg]`：`calculators/dispersion.py:1407-1442`。

### 2.10 气象参数如何进入模型

气象输入有三种来源：

1. 预设名：`urban_summer_day` 等，读取 `config/meteorology_presets.yaml`。
2. `custom` dict 或预设覆盖：由 tool 层 `_build_met_input()` 构造。
3. `.sfc` 文件：由 `read_sfc()` 解析。

证据：

- tool 层支持 preset/custom/.sfc：`tools/dispersion.py:249-301`。
- preset 参数包含风速、风向、稳定度、混合层高度、温度和 Monin-Obukhov 长度：`config/meteorology_presets.yaml:1-38`。
- calculator 层 `_process_meteorology()` 归一化为 `Date, WSPD, WDIR, MixHGT_C, L, H, Stab_Class`：`calculators/dispersion.py:1444-1548`。
- 如果 `.sfc` 中没有显式稳定度，则根据 `L`、`WSPD`、`MixHGT_C` 分类：`calculators/dispersion.py:1474-1493`、`calculators/dispersion.py:668-694`。
- emission 与 meteorology 时间步数量不一致时，只支持单步复制到多步，或单气象复制到多 emission 步；否则报错：`calculators/dispersion.py:1550-1578`。

### 2.11 模型文件加载与选择规则

当前模型资产位于 `calculators/data/dispersion_models/`，实际有 36 个 `.json` 模型文件：

```text
3 roughness tiers: z0 = 0.05, 0.5, 1.0
6 stability classes: VS, S, N1, N2, U, VU
2 directional branches: x0/downwind, x-1/upwind
total: 3 * 6 * 2 = 36
```

证据：

- `ROUGHNESS_MAP = {0.05: "L", 0.5: "M", 1.0: "H"}`，`ROUGHNESS_DIR_MAP` 指向 `model_z=...` 目录：`calculators/dispersion.py:113-114`。
- 稳定度映射 `STABILITY_ABBREV`：`calculators/dispersion.py:117-126`。
- `get_model_paths()` 组装模型文件名：`calculators/dispersion.py:1051-1072`。
- `load_all_models()` 对每个稳定度加载上下风模型：`calculators/dispersion.py:1086-1104`。
- 实际推理时不是一次加载全部，而是 `_get_or_load_model(stability_abbrev)` 按当前气象稳定度惰性加载：`calculators/dispersion.py:1580-1603`。
- 模型说明文档列出 12 个 z0=0.5 示例模型和特征：`calculators/data/dispersion_models/README_models.md:13-50`。

### 2.12 PS-XGB-RLINE 推理逻辑

核心推理函数是 `predict_time_series_xgb()`：`calculators/dispersion.py:388-665`。

每个时刻的主要步骤：

1. 根据 `Stab_Class` 选择模型组。
2. 读取风速 `WSPD`、Monin-Obukhov 长度 `L`、热通量/温度字段 `H`、混合层高度 `MixHGT_C`、风向 `WDIR`。
3. 按 `theta = 270 - wind_deg` 旋转源点和受体点坐标。
4. 计算受体相对源的 `x_hat, y_hat`。
5. 分别筛选下风向区域和上风向区域。
6. 构造模型特征：
   - `VS/S/N1`：`x_hat, y_hat, wind_sin, wind_cos, H, L, WSPD`
   - `N2/U/VU`：`x_hat, y_hat, wind_sin, wind_cos, H, MixHGT_C, L, WSPD`
7. 调用 XGBoost 模型预测单位源强下的浓度响应。
8. 用 `contrib = preds * strength / 1e-6` 按实际源强线性缩放。
9. 对同一受体累加所有 source segment 贡献。

关键证据：

- 坐标旋转与相对位置：`calculators/dispersion.py:490-500`。
- 特征构造：`calculators/dispersion.py:518-542`、`calculators/dispersion.py:580-604`。
- 单位源强线性缩放：`calculators/dispersion.py:548-550`、`calculators/dispersion.py:610-612`。
- 贡献路段追踪：`calculators/dispersion.py:551-567`、`calculators/dispersion.py:613-629`。

### 2.13 最终输出对象

`DispersionCalculator._assemble_result()` 生成的主要对象：

| 对象 | 内容 | 证据 |
| --- | --- | --- |
| `query_info` | pollutant、道路数、受体数、时间步、粗糙度、气象来源、局部坐标原点、栅格/等值带参数 | `calculators/dispersion.py:2115-2128` |
| `results` | 每个受体的经纬度、局部坐标、时序浓度、平均/最大浓度 | `calculators/dispersion.py:2062-2089` |
| `summary` | 受体数、时间步、平均浓度、最大浓度、单位、坐标系 | `calculators/dispersion.py:2130-2137` |
| `concentration_grid` | 受体点列表和 bounds | `calculators/dispersion.py:2138-2141` |
| `raster_grid` | 展示栅格：mean/max 矩阵、bbox、分辨率、cell centers、cell->receptor 映射 | `calculators/dispersion.py:722-840`、`calculators/dispersion.py:2142-2151` |
| `contour_bands` | 插值后的等值带 GeoJSON、levels、bbox、stats | `calculators/dispersion.py:1605-1836`、`calculators/dispersion.py:2153-2182` |
| `road_contributions` | 每个受体 top road 贡献，用于热点源归因 | `calculators/dispersion.py:2190-2193` |

下游：

- `HotspotTool` 只读取 `raster_grid` 和 `road_contributions`，不重新跑扩散：`tools/hotspot.py:38-81`。
- `SpatialRendererTool` 可渲染 concentration points、raster polygon、contour bands、hotspot overlay：`tools/spatial_renderer.py:139-153`。
- `ScenarioComparator` 的 dispersion 对比只比较 `mean_concentration` 和 `max_concentration`：`calculators/scenario_comparator.py:132-176`。

## 3. Where and Why NOx Is Hard-Coded

当前 NOx 限制来自多层“早期集成保守写法”。最核心的是 adapter 固定取 NOx、calculator 明确拒绝非 NOx、内部源强列名仍叫 `nox_g_m_s2`。

### 3.1 证据表

| 模块/文件 | 代码位置 | 当前行为 | 是否 NOx 硬编码 | 对扩展的影响 | 推荐改法 |
| --- | --- | --- | --- | --- | --- |
| `config/tool_contracts.yaml` | `347-430` | `pollutant` 参数描述为 “Currently only NOx”，默认 `NOx` | 是 | LLM 会认为工具只支持 NOx；即使代码泛化，schema 仍会约束使用 | 改为“默认 NOx；可选支持由 dispersion applicability config 控制”；增加适用性说明 |
| `tools/dispersion.py` | `84-90` | docstring 写 `pollutant: currently only NOx` | 是 | 维护者和测试会继续按 NOx 理解 | 改成“single pollutant to disperse; default NOx” |
| `tools/dispersion.py` | `96,111-112` | 默认 `pollutant="NOx"`，记录默认污染物 NOx | 部分是 | 默认值本身可保留用于兼容，不应作为限制 | 保留默认 `NOx`，但不再写“only” |
| `tools/dispersion.py` | `133` | 调 `self._adapter.adapt(emission_data)`，未传 `pollutant` | 是 | 即使用户传 CO2，adapter 仍构造 NOx 输入 | 改为 `adapt(emission_data, pollutant=pollutant)` |
| `calculators/dispersion_adapter.py` | `32-36` | docstring 写 `total_emissions_kg_per_hr.NOx -> nox` | 是 | 数据契约写死 | 改为 `total_emissions_kg_per_hr[pollutant] -> emission_kg_h` 或动态列 |
| `calculators/dispersion_adapter.py` | `45-47` | `adapt()` 固定 `_build_emissions_df(results, "NOx")` | 是 | 多污染物直接被截断为 NOx | `adapt(..., pollutant: str = "NOx")` |
| `calculators/dispersion_adapter.py` | `127-147` | `_build_emissions_df()` 其实已有 `pollutant` 形参，但上游固定传 NOx | 间接是 | 可复用，但缺失污染物时当前默默置 0 | 动态取目标污染物；缺失时应 error 或显式 warnings |
| `calculators/dispersion.py` | `1148` | `calculate(..., pollutant="NOx")` | 默认值 | 默认可保留 | 保留默认，同时允许其他污染物 |
| `calculators/dispersion.py` | `1239-1240` | 非 NOx 直接 `ValueError` | 是，最强限制 | 所有非 NOx 调用失败 | 改为检查污染物是否在输入列中、是否在适用性配置中允许 |
| `calculators/dispersion.py` | `1250-1256` | 需要 `pollutant.lower()` 列 | 泛化雏形 | 对 `PM2.5` 会要求列名 `pm2.5`，可行但不稳定 | 统一规范列名，避免点号/大小写引发问题 |
| `calculators/dispersion.py` | `1301-1308` | 源强列固定命名 `nox_g_m_s2` | 是 | 语义错误，CO2/PM 使用时会混淆 | 改成 `source_strength_g_m2_s` |
| `calculators/dispersion.py` | `1418-1427` | source array 只读取 `nox_g_m_s2` | 是 | 必须重构，否则非 NOx 无法进入 source array | 改读取 `source_strength_g_m2_s` |
| `calculators/dispersion.py` | `963-976` | 函数参数名 `nox_kg_h` | 命名硬编码 | 数值公式可复用，但 API 语义限制 | 改名 `emission_kg_h_to_line_source_strength(emission_kg_h, ...)`，保留兼容 alias |
| `tests/test_dispersion_calculator.py` | `457-461` | 测试断言 CO2 应 raise | 是 | 测试会阻止泛化 | 改为 CO2 可通过；新增缺失列/不适用污染物测试 |
| `tests/test_dispersion_tool.py` | `18-50,267-270` | mock 宏观结果虽然含 CO2，但执行只传 NOx | 是 | 没覆盖 CO2 路径 | 参数化 NOx/CO2/PM2.5 |
| `tests/test_dispersion_integration.py` | `360-369` | pipeline helper 固定 `pollutant="NOx"` | 是 | 集成测试只证明 NOx | 参数化目标污染物 |
| `tests/test_dispersion_integration.py` | `660-671` | 标准化“氮氧化物”到 NOx | 不是问题 | 说明标准化层可工作 | 增加“二氧化碳”“细颗粒物”标准化后进入扩散参数的测试 |
| `docs/reports/SPRINT10_FINAL_REPORT.md` | `123-128` | 写“扩散模型仅支持 NOx（surrogate 模型限制）” | 文档层误归因 | 会误导论文/工程判断 | 新报告应修正为“当前集成层限制” |
| `docs/DATA_INVENTORY.md` | `225-244` | 直接输入要求 `NAME_1 + data_time + nox + length` | 是 | 数据准备指南只围绕 NOx | 扩展后改为 `pollutant_emission_kg_h/source_strength` 通用字段 |
| `ps-xgb-aermod-rline-surrogate/data_gen.py` | `398,403` | AERMOD 示例 `POLLUTID="NOx"`，单位源强 `1.0e-06` | 示例硬编码 | 对原始 demo 输入有 NOx 标签，但不进入模型特征 | 保留历史脚本，工程集成层另做通用包装 |
| `ps-xgb-aermod-rline-surrogate/mode_inference.py` | `119-120,408-415` | 原脚本字段叫 `nox_g_m_s2` | 示例硬编码 | agent 移植时沿用了该命名 | 主工程重构为通用字段，原目录作为参考实现 |

### 3.2 当前 tests / demo / case study 的倾向

- `tests/test_dispersion_calculator.py` 的 mock macro result 只包含 `NOx`：`tests/test_dispersion_calculator.py:92-112`。
- 同一文件明确测试 `CO2` 不支持：`tests/test_dispersion_calculator.py:457-461`。
- `tests/test_dispersion_tool.py` 的宏观结果包含 `NOx` 和 `CO2`，但执行测试只传 `pollutant="NOx"`：`tests/test_dispersion_tool.py:18-50`、`tests/test_dispersion_tool.py:267-270`。
- `tests/test_dispersion_integration.py` 的 realistic macro result 也包含 `NOx` 和 `CO2`，但 `_run_pipeline()` 固定 `pollutant="NOx"`：`tests/test_dispersion_integration.py:305-369`。
- `docs/DATA_INVENTORY.md` 的真实链路测试建议固定 `pollutant = "NOx"`：`docs/DATA_INVENTORY.md:428-435`。

### 3.3 限制归类

| 限制来源 | 是否为方法本身限制 | 判断 |
| --- | --- | --- |
| adapter 固定取 `NOx` | 否 | 纯工程映射硬编码 |
| calculator 拒绝非 `NOx` | 否 | 当前集成层校验策略 |
| 内部列名 `nox_g_m_s2` | 否 | 从原始 demo 迁移来的字段命名 |
| tool contract 写 only NOx | 否 | 对当前能力的保守 schema 描述 |
| 原始 AERMOD 输入 `POLLUTID=NOx` | 部分否 | 原始训练样本标签为 NOx，但模型输入特征不含 pollutant；如果只做非反应性物理扩散，单位源强响应可复用 |
| 不模拟化学反应、沉降、二次生成 | 是，方法边界 | 这不是 NOx 限制，而是“一次污染物物理扩散代理”的科学边界 |

## 4. Is PS-XGB-RLINE Intrinsically NOx-Only?

### 4.1 原始 README 的明确表述

`ps-xgb-aermod-rline-surrogate/README.md:12-13` 明确写到：示例聚焦 `NOx`，但 surrogate 学习的是纯物理扩散关系，不显式表示大气化学反应，因此预训练框架可直接用于主要由扩散过程控制的污染物，例如 PM、CO2、NOx，只需调整 emission inputs。

这与当前主工程文档中“surrogate 模型限制”的说法不一致。更准确的说法应是：

> 当前 agent 集成实现仅开放 NOx；PS-XGB-RLINE 方法在单位源强物理扩散意义下可复用到其他一次污染物，但科学解释需受污染物过程边界约束。

### 4.2 训练数据生成是否包含污染物类别

`data_gen.py` 中确实把 AERMOD `POLLUTID` 写成 `NOx`：

- AERMOD 模板包含 `POLLUTID {POLLUTID}`：`ps-xgb-aermod-rline-surrogate/data_gen.py:37-45`。
- 实际变量 `POLLUTID = "NOx"`：`ps-xgb-aermod-rline-surrogate/data_gen.py:395-403`。
- `SRCPARAM` 源强为 `1.0e-06`：`ps-xgb-aermod-rline-surrogate/data_gen.py:403`。

但这只是 AERMOD 模拟标签和训练数据生成配置。模型训练脚本读取的是 AERMOD 输出浓度与气象，不把 `POLLUTID` 或污染物类别作为特征输入。

### 4.3 训练特征是否包含污染物类别

`training.py` 读取 AERMOD 输出：

- `read_aermod_data_numpy()` 只读取 `X, Y, AVERAGE_CONC, DATE`：`ps-xgb-aermod-rline-surrogate/training.py:37-53`。
- `read_met_data_numpy()` 读取气象列并构造 DATE：`ps-xgb-aermod-rline-surrogate/training.py:56-84`。
- 旋转后的训练特征是 `x_rot, y_rot, sin, cos, H, L, WSPD`：`ps-xgb-aermod-rline-surrogate/training.py:180-196`。
- README 中模型特征也只列出 `x_rot/y_rot/wind_sin/wind_cos/H/MixHGT_C/L/WSPD`：`ps-xgb-aermod-rline-surrogate/README.md:106-119`。

没有污染物类别、分子量、反应速率、沉降速度、背景浓度等特征。

### 4.4 推理特征是否包含污染物类别

原始 `mode_inference.py` 和主工程 `predict_time_series_xgb()` 都只使用：

- source/receptor 相对坐标
- 风向相对道路角度的 sin/cos
- `H`
- `L`
- `MixHGT_C`
- `WSPD`
- source strength

原始推理 docstring 写 sources 数组列为 `[source_x, source_y, emission_strength, road_angle_deg]`：`ps-xgb-aermod-rline-surrogate/mode_inference.py:515-521`。

主工程推理函数同样要求 `sources` shape `(T, N_sources, 4)`，没有 pollutant category：`calculators/dispersion.py:415-417`。

### 4.5 模型预测的是单位源强响应还是特定污染物响应

关键逻辑：

- 原始脚本：`contrib = preds * strength[s_idx] / 1e-6`：`ps-xgb-aermod-rline-surrogate/mode_inference.py:620`、`ps-xgb-aermod-rline-surrogate/mode_inference.py:657`。
- 主工程：同样为 `contrib = preds * strength[s_idx] / 1e-6`：`calculators/dispersion.py:548-550`、`calculators/dispersion.py:610-612`。

这说明模型的输出可理解为“单位源强 1e-6 g/(m2*s) 下的浓度响应”。实际源强只做线性缩放。因此，在不涉及污染物化学反应和去除过程的“保守示踪物/一次污染物物理扩散”意义下，替换源强输入是合理的工程复用。

### 4.6 工程判断

从代码证据看：

- PS-XGB-RLINE 的模型输入不含污染物类别。
- 模型文件命名不含污染物名，只含稳定度、上下风分支、粗糙度：`calculators/dispersion.py:1051-1072`。
- 预测阶段只关心源强和物理气象/几何特征。
- 原始 README 明确支持主要由物理扩散控制的污染物。

因此，当前“只能算 NOx”不是方法本身限制，而是 agent 集成层为了先打通 NOx 链路而留下的保守硬编码。

### 4.7 建模边界判断

可做工程实现不等于可做无限科学声称。多污染物复用成立的前提是：

- 目标是一次污染物的近路增量浓度。
- 排放源强单位正确。
- 不考虑污染物特有的化学反应、沉降、湿清除、二次生成或背景浓度。
- 输出解释为“物理扩散代理结果”，而非完整空气质量模型结果。

不应直接声称：

- `NOx` 结果就是 `NO2` 暴露浓度。
- `PM2.5/PM10` 结果包含二次颗粒物形成或沉降。
- `CO2` 结果代表城市背景 CO2 或碳循环影响。
- `THC` 结果包含 VOC 物种反应性、臭氧生成潜势或化学损耗。

## 5. Scientific and Engineering Boundaries of Multi-Pollutant Use

### 5.1 工程可实现 vs 科学可声称

| 维度 | 工程可实现 | 科学可声称 |
| --- | --- | --- |
| 替换源强字段 | 可以，动态读取 `total_emissions_kg_per_hr[pollutant]` | 只表示目标污染物按同一物理扩散核传播 |
| 复用 XGBoost 模型 | 可以，无需重训用于物理扩散响应 | 不能声称模型包含污染物化学/沉降机制 |
| 输出单位 `μg/m³` | 对质量浓度可保留；CO2 也可用质量浓度表达 | CO2 论文表达常需 ppm/背景浓度，应说明为增量质量浓度 |
| 热点识别 | 可以按 percentile 通用 | threshold 需污染物特定阈值；不能复用 NOx 阈值解释健康意义 |
| 地图渲染 | 可复用 | 图例、色阶、标题需要跟随污染物和单位 |
| 情景对比 | 可复用 mean/max concentration | 多污染物批量结构下需带 pollutant 维度 |

### 5.2 下游影响

#### Hotspot

`HotspotAnalyzer` 当前按 raster 数值做 percentile 或 threshold，不知道污染物类别：

- 默认方法是 `percentile`，默认 top 5%：`tools/hotspot.py:64-67`。
- threshold method 使用用户传入 `threshold_value`，单位描述为 `ug/m3`：`config/tool_contracts.yaml:480-490`。
- summary 和 interpretation 固定说 `μg/m³`：`calculators/hotspot_analyzer.py:532-563`。

影响：

- percentile 方法对多污染物工程上可复用。
- threshold 方法必须引入污染物特定阈值配置，否则 CO2/PM/CO/THC 不能共用同一阈值解释。
- source attribution 逻辑本身按贡献值聚合，可复用，但贡献值含义需跟随污染物。

#### Render

`SpatialRendererTool` 的 concentration/raster/contour 都默认回退到 `NOx`：

- concentration map fallback：`tools/spatial_renderer.py:404-411`。
- raster map fallback：`tools/spatial_renderer.py:596-602`。
- contour map fallback：`tools/spatial_renderer.py:718-723`。
- raster/contour legend unit 多处固定 `μg/m³`：`tools/spatial_renderer.py:684-697`、`tools/spatial_renderer.py:736-776`。

影响：

- 单污染物 MVP 只要 `query_info.pollutant` 正确，下游大多能显示正确污染物名。
- 需要把单位从结果 summary/query_info 传递，而不是硬编码 `μg/m³`。
- 前端 `web/app.js` 的 concentration/raster/hotspot 也有多个 `|| 'NOx'` fallback 和固定 `μg/m³` 文案，例如 `web/app.js:2741`、`web/app.js:2823`、`web/app.js:3000`、`web/app.js:3616`、`web/app.js:4020`。

#### Compare Scenarios

`ScenarioComparator._compare_dispersion()` 只比较 mean/max concentration，单位固定 `μg/m³`：`calculators/scenario_comparator.py:132-176`。

影响：

- 单污染物仍可用。
- 多污染物批量输出时，需要在比较结果中加入 `pollutant` 维度，否则不同污染物的结果无法同 schema 比较。

#### Map Export

`services/map_exporter.py` 对 dispersion/hotspot pollutant 默认回退 `NOx`，图例单位写 `μg/m³`：`services/map_exporter.py:273-318`、`services/map_exporter.py:335-344`。

影响：

- 单污染物 MVP 需要确保 result payload 中有 `query_info.pollutant` 和 `summary.unit`。
- 若未来支持 CO2 ppm 转换，导出图例也要支持单位切换。

### 5.3 现有跨参数约束已有适用性雏形

`config/cross_constraints.yaml` 已经存在 `pollutant_task_applicability`：

- 对 `CO2 + calculate_dispersion` 给 warning，原因是 CO2 混合较快，不常作为近地扩散热点重点：`config/cross_constraints.yaml:40-45`。
- 对 `THC + calculate_dispersion` 给 warning，原因是代理扩散模型支持有限，应谨慎解释：`config/cross_constraints.yaml:46-51`。

这说明系统设计上已经承认“不是所有污染物都同等适合扩散任务”。未来应把这类 warning 升级为正式的 `dispersion_pollutant_applicability` 配置。

## 6. Minimal Refactor Path

### 6.1 MVP 目标

在不破坏现有 NOx 链路的前提下，支持单次调用选择任意一个可物理扩散的污染物：

```python
calculate_dispersion(
    pollutant="PM2.5",
    meteorology="urban_summer_day",
    roughness_height=0.5,
)
```

MVP 不做多污染物批量输出，不重训模型，不改变核心 XGBoost 推理逻辑。

### 6.2 建议改动清单

| 文件 | 改动 | 风险 |
| --- | --- | --- |
| `calculators/dispersion_adapter.py` | `adapt(macro_result, pollutant="NOx", geometry_source=None)`；动态读取 `total_emissions_kg_per_hr[pollutant]` | 低 |
| `calculators/dispersion_adapter.py` | 缺失目标污染物时不要默默置 0；至少返回详细错误 | 中 |
| `calculators/dispersion.py` | 移除 `pollutant != "NOx"` 拒绝逻辑；改成输入列存在性和适用性校验 | 中 |
| `calculators/dispersion.py` | `nox_g_m_s2` 改为 `source_strength_g_m2_s` | 中，涉及测试 |
| `calculators/dispersion.py` | `emission_to_line_source_strength()` 改名或增加通用 alias | 低 |
| `tools/dispersion.py` | 调 adapter 时传入 `pollutant` | 低 |
| `config/tool_contracts.yaml` | 修改 `pollutant` 描述，不再写 currently only NOx；保留默认 NOx | 低 |
| `config/cross_constraints.yaml` 或新增配置 | 增加扩散污染物适用性表，至少 warning CO2/THC | 中 |
| `tools/spatial_renderer.py` | 单位从结果读取，减少 `NOx` fallback | 中 |
| `tools/hotspot.py` / `calculators/hotspot_analyzer.py` | hotspot 输出携带 pollutant/unit；threshold 提示污染物特异性 | 中 |
| `services/map_exporter.py` | 图例单位和 fallback 跟随结果 | 低 |
| `tests/test_dispersion_*.py` | 参数化 NOx/CO2/PM2.5，删除“CO2 必须失败”断言 | 中 |

### 6.3 Adapter 设计

当前：

```python
roads_gdf = EmissionToDispersionAdapter._extract_geometry(results, geometry_source)
emissions_df = EmissionToDispersionAdapter._build_emissions_df(results, "NOx")
```

建议：

```python
@staticmethod
def adapt(macro_result: Dict[str, Any], pollutant: str = "NOx", geometry_source=None):
    results = ...
    roads_gdf = _extract_geometry(results, geometry_source)
    emissions_df = _build_emissions_df(results, pollutant)
    return roads_gdf, emissions_df
```

`_build_emissions_df()` 建议行为：

- 目标污染物存在：生成标准列，例如 `emission_kg_h` 或 `source_emission_kg_h`。
- 目标污染物缺失：返回错误，说明该宏观结果的可用污染物有哪些。
- 允许零排放值，但不要把“缺失字段”当作 0。

推荐内部 DataFrame schema：

```text
NAME_1
data_time
pollutant
emission_kg_h
length
```

或者为了最小 diff：

```text
NAME_1
data_time
<normalized_pollutant_col>
length
```

但计算器内部应尽快转成统一 `source_strength_g_m2_s`，避免 `pm2.5` 这种列名在后续 merge 中造成不便。

### 6.4 源强函数泛化

当前函数名和参数是：

```python
def emission_to_line_source_strength(nox_kg_h, length_km, road_width_m=7.0)
```

建议：

```python
def emission_kg_h_to_line_source_strength(
    emission_kg_h: float,
    length_km: float,
    road_width_m: float = 7.0,
) -> float:
    return emission_kg_h * 1000.0 / 3600.0 / (length_km * 1000.0 * road_width_m)
```

为降低破坏性，可保留旧函数作为 alias：

```python
def emission_to_line_source_strength(nox_kg_h, length_km, road_width_m=7.0):
    return emission_kg_h_to_line_source_strength(nox_kg_h, length_km, road_width_m)
```

### 6.5 `_validate_inputs()` 设计

当前：

```python
if pollutant != "NOx":
    raise ValueError("Only NOx is currently supported by the surrogate model")
```

MVP 建议：

1. 标准化 `pollutant` 名称，或假定 Executor 已标准化。
2. 检查 `roads_gdf` 必需列。
3. 检查 emission 输入是否有目标污染物或统一 `emission_kg_h` 列。
4. 检查目标污染物是否在 `dispersion_pollutant_applicability` 配置允许列表中。
5. 对 `CO2`、`THC` 等返回 warning，而不是硬失败，除非配置指定 block。

### 6.6 Tool Contract 改写建议

`config/tool_contracts.yaml` 中 `pollutant` 参数可改为：

```yaml
pollutant:
  required: false
  standardization: pollutant
  schema:
    type: string
    description: >
      Pollutant to disperse. Defaults to NOx. The current surrogate models simulate
      physical near-road dispersion of primary emissions; chemical transformation,
      deposition, secondary formation, and background concentration are not included.
    default: NOx
```

如果增加配置：

```yaml
dispersion_pollutant_applicability:
  NOx:
    status: supported
  CO:
    status: supported
  PM2.5:
    status: supported_with_caveats
    caveats: ["No deposition or secondary aerosol formation"]
  PM10:
    status: supported_with_caveats
    caveats: ["No size-dependent deposition"]
  CO2:
    status: supported_with_caveats
    caveats: ["Incremental mass concentration only; background/ppm conversion not included"]
  THC:
    status: limited
    caveats: ["No VOC speciation or chemistry"]
```

### 6.7 下游同步调整

MVP 不要求多污染物同图，但至少应保证单污染物结果贯通：

- `query_info.pollutant` 正确写目标污染物。
- `summary.unit` 可继续默认为 `μg/m³`，但应为下游传递单位，不要在 renderer/hotspot/exporter 重复硬编码。
- `HotspotTool` 的 `analysis_data` 应保留 `query_info.pollutant`，当前已经复制：`tools/hotspot.py:99-100`。
- `HotspotTool._build_map_data()` 当前没有显式写 `pollutant`，建议加入 `pollutant = dispersion_data.query_info.pollutant`。
- `SpatialRendererTool._build_hotspot_map()` 当前返回对象没有顶层 `pollutant`，建议加入，避免前端 fallback `NOx`。
- `ScenarioComparator._compare_dispersion()` 建议把 `pollutant` 放进返回结果。

### 6.8 兼容性策略

- 默认仍为 `NOx`。
- 原有 `calculate_dispersion()` 无 pollutant 参数的行为完全不变。
- 现有 NOx 测试必须全部继续通过。
- 对旧字段 `nox` 可保留兼容读取：如果 `pollutant == "NOx"` 且没有统一列，则读取 `nox`。
- 对非 NOx 不应静默降级到 NOx；应明确使用用户指定污染物或返回缺失污染物错误。

## 7. Alternative Expansion Designs

### 7.1 方案 1：保持工具单污染物，上层多次调用

每次 `calculate_dispersion` 只处理一个 `pollutant`。如果用户要求多个污染物，由 Router/LLM 或 workflow 层多次调用工具。

| 维度 | 评价 |
| --- | --- |
| 改造复杂度 | 低。最小改动集中在 adapter/calculator/tool contract/tests。 |
| 兼容现有系统 | 高。当前 result schema 是单污染物，`query_info.pollutant` 已存在。 |
| 输出结构清晰度 | 高。每个结果对象只对应一个污染物。 |
| 前端地图适配难度 | 低。现有 concentration/raster/contour 结构可复用。 |
| 热点分析适配难度 | 低。热点分析天然针对一个 raster。 |
| benchmark/case study 成本 | 中。多污染物 benchmark 需要多次调用和结果聚合。 |
| 论文叙述难度 | 低。可表述为“支持指定污染物的物理扩散模拟”。 |
| 性能 | 中。多污染物会重复 geometry/receptor/met/model 处理。 |

### 7.2 方案 2：工具内部支持 `pollutants: list[str]`

`calculate_dispersion` 一次接收多个污染物，内部复用 geometry、受体点、气象、模型加载，对每个污染物替换 source strength 后循环推理。

| 维度 | 评价 |
| --- | --- |
| 改造复杂度 | 高。需要重构 result schema、router、renderer、hotspot、compare。 |
| 兼容现有系统 | 中低。现有下游默认单污染物，需要兼容层。 |
| 输出结构清晰度 | 中。建议 `pollutants[p].results/raster_grid/...`，但 payload 变大。 |
| 前端地图适配难度 | 高。需要污染物切换、图例重算、热点层切换。 |
| 热点分析适配难度 | 高。每个污染物都有不同 raster/hotspot/threshold。 |
| benchmark/case study 成本 | 中。一次调用方便，但断言复杂。 |
| 论文叙述难度 | 中。能力更强，但更容易被误解为完整多污染物空气质量模型。 |
| 性能 | 高。可复用 geometry/receptor/met/model，减少重复计算。 |

### 7.3 推荐优先路线

建议优先走方案 1：单污染物 MVP。

原因：

- 当前系统已经有 `pollutant` 单数参数和 `query_info.pollutant` 输出结构。
- 下游 hotspot/render/compare 都以单 raster 为核心，改动小。
- 可以快速解除 NOx 人为限制，同时保留科学边界。
- 更适合先写 benchmark 和论文案例：分别展示 NOx、CO、PM2.5 的单污染物扩散结果，避免一次性多图层输出造成解释复杂度。
- 多污染物内部批量可作为性能优化和交互升级的第二阶段，而不是第一阶段必须项。

## 8. Pollutant-by-Pollutant Recommendation Matrix

| 污染物 | 当前工程支持状态 | 物理扩散直接处理适合度 | 需要额外机制 | 科学风险 | 工程优先级 | 论文宣称建议 |
| --- | --- | --- | --- | --- | --- | --- |
| `NOx` | 已支持 | 高，当前验证链路围绕 NOx | 若要解释 NO2 暴露，需要 NOx-NO2 转化/背景 O3；否则只称 NOx 增量浓度 | 中：不能等同 NO2 | P0 | 可作为当前正式能力，但说明不含化学转化 |
| `CO` | 宏观排放支持；扩散未开放 | 高，近路 CO 可近似按一次污染物物理扩散处理 | 需要动态污染物输入；可选背景浓度叠加 | 低到中 | P1 高优先 | 可作为扩展能力，表述为 CO 近路增量浓度 |
| `PM2.5` | 宏观排放支持；扩散未开放 | 中，高度依赖一次颗粒物部分 | 需要说明不含二次气溶胶、干湿沉降、粒径过程；阈值需污染物特定 | 中高 | P1 | 可做工程能力和案例，但论文措辞应为 primary PM2.5 dispersion |
| `PM10` | 宏观排放支持；扩散未开放 | 中到低于 PM2.5，沉降更重要 | 需要粒径/沉降机制才适合强科学声称 | 高 | P1/P2 | 可作为探索性工程能力，不宜强宣称完整 PM10 扩散 |
| `CO2` | 宏观排放支持；扩散未开放 | 物理增量扩散可算，但热点意义弱 | 需要背景浓度、ppm 转换、碳排放解释边界；不宜健康热点阈值 | 中 | P1 但低于 CO/PM2.5 | 可称道路 CO2 增量浓度示意，不宜作为污染热点核心能力 |
| `THC` | 宏观排放支持；扩散未开放 | 有限。THC 是总烃混合指标，不同 VOC 反应性差异大 | 需要 VOC 物种分解、化学损耗/臭氧生成机制 | 高 | P2 | 不建议当前阶段作为正式扩散能力，只作 future work 或谨慎实验 |

优先级建议：

- P0：`NOx`。保持当前能力，修正文档误归因。
- P1：`CO`、`PM2.5`。最值得作为第一阶段扩展和 benchmark。`CO2` 可支持但应弱化热点解释。
- P1/P2：`PM10`。工程可做，科学 caveat 更强。
- P2：`THC`。不建议当前阶段正式 claim。

## 9. Required Tests and Validation Plan

### 9.1 NOx 数值回归测试

目标：重构后 NOx 结果与重构前完全一致或在浮点容差内一致。

建议位置：

- `tests/test_dispersion_numerical_equivalence.py`
- `tests/test_dispersion_calculator.py`

建议断言：

- 同一 mock model、同一 roads/emissions/met 下，`summary.mean_concentration`、`summary.max_concentration`、`raster_grid.matrix_mean`、`road_contributions` 与基线一致。
- `emission_kg_h_to_line_source_strength(1.0, 0.1, 7.0)` 与旧公式一致。

### 9.2 参数化污染物测试

建议在 `tests/test_dispersion_integration.py` 增加：

```python
@pytest.mark.parametrize("pollutant", ["NOx", "CO2", "PM2.5"])
def test_full_pipeline_for_selected_pollutant(...):
    ...
```

断言：

- `result["status"] == "success"`
- `result["data"]["query_info"]["pollutant"] == pollutant`
- adapter 取的是对应 `total_emissions_kg_per_hr[pollutant]`
- 若把 CO2 源强设为 NOx 的 40 倍，在 constant mock model 下平均浓度也按比例放大。

### 9.3 缺失污染物测试

当前 `_build_emissions_df()` 用 `emissions.get(pollutant_key, 0.0)`，会把缺失污染物静默当成 0：`calculators/dispersion_adapter.py:138-143`。

建议新增测试：

- 宏观结果只有 `NOx`，调用 `pollutant="PM2.5"`。
- 预期：工具失败，错误信息包含目标污染物和 available pollutants。
- 不接受静默生成全 0 浓度。

建议文件：

- `tests/test_dispersion_tool.py`
- `tests/test_dispersion_integration.py`

### 9.4 单位一致性测试

建议在 `tests/test_dispersion_calculator.py` 保留并改名：

- `test_emission_kg_h_to_g_s_m2()`
- 参数化 `emission_kg_h`，不使用 `nox_kg_h` 命名。

断言：

```text
1 kg/h, length=1 km, width=7 m
= 1000 / 3600 / (1000 * 7)
```

并增加一个比例测试：

- 输入 2 kg/h 的浓度应为 1 kg/h 的 2 倍（mock model 下）。

### 9.5 Geometry 缺失测试

已有 `test_execute_no_geometry()`：`tests/test_dispersion_tool.py:277-?`，应保留并扩展：

- 对 `pollutant="CO2"` 同样缺 geometry 也应优先报 geometry 缺失。
- 对部分道路缺 geometry：只使用有 geometry 的道路，还是报 warning，需要明确产品策略并测试。

### 9.6 Hotspot / Render 链路测试

建议在 `tests/test_dispersion_integration.py` 或新增 `tests/test_multi_pollutant_dispersion_rendering.py`：

- `SpatialRendererTool._build_raster_map()` 对 `query_info.pollutant="PM2.5"` 返回 `map_data["pollutant"] == "PM2.5"`。
- `legend_title` 为 `PM2.5 Concentration`。
- `legend_unit` 来自 `summary.unit`，而不是硬编码。
- `HotspotTool` 输出的 `map_data["pollutant"]` 应等于源 dispersion 的 pollutant。
- `HotspotAnalyzer` threshold method 对不同污染物应能接收不同 `threshold_value`，但默认推荐 percentile。

### 9.7 UI / 阈值配置测试

建议新增配置测试：

- `config/dispersion_pollutants.yaml` 或 `config/cross_constraints.yaml` 中每个支持污染物都有：
  - `status`
  - `default_unit`
  - `hotspot_threshold_default` 或明确 `null`
  - `caveats`

测试文件：

- `tests/test_tool_contracts.py`
- `tests/test_config.py`

断言：

- `NOx/CO/PM2.5/PM10/CO2/THC` 至少都有适用性条目。
- `CO2` 和 `THC` 对 `calculate_dispersion` 触发 warning 而非 hard block，除非产品决定 block。

### 9.8 Benchmark / case study

建议新增 benchmark 样本：

- `macro -> dispersion(NOx)` 当前链路回归。
- `macro -> dispersion(CO)` 工程扩展样本。
- `macro -> dispersion(PM2.5)` 带 caveat 的样本。
- 缺失污染物样本：要求系统清晰报错。
- `CO2` 样本：要求回答中说明“增量质量浓度/不代表背景 CO2”。

如果用于论文，应至少展示：

- 同一道路、同一气象下，不同污染物浓度场空间形态受同一扩散核控制，数值差异来自源强。
- 不同气象条件下同一污染物浓度场变化。
- 明确说明模型不包含化学和沉降过程。

## 10. Recommended Next Steps

### 10.1 是否建议立刻泛化到其他污染物

建议立刻做第一阶段单污染物泛化，但不要一次做批量多污染物输出。

原因：

- 当前宏观排放、标准化、router 参数入口都已经支持多污染物。
- PS-XGB-RLINE 方法可复用到物理扩散主导的一次污染物。
- 当前 NOx 限制是工程硬编码，解除成本可控。
- 保留默认 NOx 可以最大限度降低回归风险。

### 10.2 第一阶段最值得支持的污染物

推荐顺序：

1. `NOx`：保持现有正式能力。
2. `CO`：最适合作为非 NOx 的第一扩展目标，近路物理扩散解释相对清晰。
3. `PM2.5`：工程价值高，但必须注明 primary PM2.5，不含二次生成/沉降。
4. `CO2`：可作为增量浓度示意和碳排放空间影响展示，但不要主打热点。
5. `PM10`：可工程支持，但沉降 caveat 更强。
6. `THC`：暂不建议正式宣称，只保留实验/未来工作。

### 10.3 是否需要重训代理模型

MVP 不需要重训。

理由：

- 模型输入不含污染物类别。
- 模型学习的是单位源强下的物理扩散响应。
- 实际污染物差异通过源强输入线性缩放。

但如果未来要纳入污染物特异过程，则需要新增机制或重训/耦合其他模型：

- NOx-NO2-O3 chemistry
- VOC/THC speciation and chemistry
- PM size-dependent deposition
- wet deposition
- secondary aerosol formation
- background concentration fields

### 10.4 这个改造适合如何定位

| 定位 | 建议 |
| --- | --- |
| 工程能力扩展 | 是。应作为近期实现目标。 |
| benchmark 扩展 | 是。应新增 CO/PM2.5/CO2 样本和 caveat 检查。 |
| 论文方法贡献 | 谨慎。可作为“代理模型可泛化到一次污染物物理扩散”的系统能力，不宜包装成完整多污染物化学空气质量模型。 |
| 未来工作 | 批量多污染物输出、污染物特异阈值、背景浓度、化学/沉降机制应作为后续工作。 |

### 10.5 推荐执行顺序

1. 先补测试，锁定当前 NOx 数值与链路行为。
2. 做单污染物 MVP 重构：adapter + calculator 内部源强字段 + tool contract。
3. 增加 `CO`、`PM2.5`、`CO2` 的 mock model 参数化测试。
4. 同步修 renderer/hotspot/exporter 的 pollutant/unit 传递。
5. 再做小型 benchmark：NOx、CO、PM2.5 各一个 macro->dispersion->render 案例。
6. 最后写论文表述边界，避免过度 claim。

## Appendix A. Code Evidence Table

| 主题 | 文件/位置 | 证据摘要 |
| --- | --- | --- |
| 工具 schema 来自 YAML | `tools/contract_loader.py:76-91` | 从 `config/tool_contracts.yaml` 生成 function-calling tool definitions |
| 扩散合同默认 NOx | `config/tool_contracts.yaml:424-430` | `pollutant` 描述为 “Currently only NOx” |
| 扩散依赖 emission | `config/tool_contracts.yaml:439-441` | requires `emission`, provides `dispersion` |
| Executor 标准化参数 | `core/executor.py:219-264` | 标准化后调用工具 |
| 污染物标准化支持多污染物 | `config/unified_mappings.yaml:213-260` | `CO2/CO/NOx/PM2.5/PM10/THC` 均在映射表中 |
| Router 注入 `_last_result` | `core/router.py:825-907` | 对扩散/热点/渲染注入上游结果 |
| 宏观排放输出多污染物 | `calculators/macro_emission.py:199-207` | `total_emissions_kg_per_hr` 按污染物动态生成 |
| 宏观工具合并 geometry | `tools/macro_emission.py:832-844` | 原始输入 geometry 回灌到结果 |
| 扩散工具入口 | `tools/dispersion.py:59-193` | `DispersionTool.execute()` 完整工具层 |
| 文件输入未实现 | `tools/dispersion.py:232-235` | file-based `emission_source` 仅 warning |
| Adapter 固定 NOx | `calculators/dispersion_adapter.py:45-47` | `_build_emissions_df(results, "NOx")` |
| Adapter geometry 解析 | `calculators/dispersion_adapter.py:95-124` | WKT/GeoJSON/list/shapely |
| 计算器拒绝非 NOx | `calculators/dispersion.py:1239-1240` | `Only NOx is currently supported` |
| 源强换算公式 | `calculators/dispersion.py:963-976` | `kg/h -> g/(m2*s)` |
| 内部源强列写死 | `calculators/dispersion.py:1301-1308` | `nox_g_m_s2` |
| source array 读取写死列 | `calculators/dispersion.py:1418-1427` | 读取 `nox_g_m_s2` 后 rename 为 `emission` |
| 模型路径规则 | `calculators/dispersion.py:1051-1072` | 按 roughness/stability/x branch 选模型 |
| 懒加载模型 | `calculators/dispersion.py:1580-1603` | 按稳定度加载模型 |
| 推理特征不含污染物 | `calculators/dispersion.py:518-542`、`580-604` | 特征仅几何/风向/气象 |
| 源强线性缩放 | `calculators/dispersion.py:548-550`、`610-612` | `preds * strength / 1e-6` |
| 输出 result schema | `calculators/dispersion.py:2115-2155` | `query_info/results/summary/concentration_grid/raster_grid/contour_bands` |
| 原始 README 说明可泛化 | `ps-xgb-aermod-rline-surrogate/README.md:12-13` | 示例 NOx，但物理扩散可用于 PM/CO2/NOx |
| 原始训练特征 | `ps-xgb-aermod-rline-surrogate/training.py:180-196` | `x_rot/y_rot/sin/cos/H/L/WSPD` |
| 原始推理缩放 | `ps-xgb-aermod-rline-surrogate/mode_inference.py:620,657` | 单位源强线性缩放 |
| Hotspot 默认 percentile | `tools/hotspot.py:64-68` | top 5%、最小面积、max_hotspots |
| Hotspot 固定单位文案 | `calculators/hotspot_analyzer.py:532-563` | `μg/m³` |
| Renderer NOx fallback | `tools/spatial_renderer.py:404-411`、`596-602`、`718-723` | 无 pollutant 时回退 `NOx` |
| Scenario dispersion 单位固定 | `calculators/scenario_comparator.py:132-176` | mean/max concentration，unit `μg/m³` |
| 测试断言 CO2 不支持 | `tests/test_dispersion_calculator.py:457-461` | 当前测试保护 NOx-only 行为 |

## Appendix B. Candidate Files to Modify

第一阶段 MVP 预计修改：

- `calculators/dispersion_adapter.py`
- `calculators/dispersion.py`
- `tools/dispersion.py`
- `config/tool_contracts.yaml`
- `config/cross_constraints.yaml` 或新增 `config/dispersion_pollutants.yaml`
- `tools/hotspot.py`
- `calculators/hotspot_analyzer.py`
- `tools/spatial_renderer.py`
- `services/map_exporter.py`
- `tests/test_dispersion_calculator.py`
- `tests/test_dispersion_tool.py`
- `tests/test_dispersion_integration.py`
- `tests/test_dispersion_numerical_equivalence.py`
- `tests/test_tool_contracts.py`

第二阶段批量多污染物可能还需修改：

- `core/router.py`
- `core/context_store.py`
- `core/router_render_utils.py`
- `calculators/scenario_comparator.py`
- `tools/scenario_compare.py`
- `web/app.js`
- evaluation benchmark JSONL / case study 数据

