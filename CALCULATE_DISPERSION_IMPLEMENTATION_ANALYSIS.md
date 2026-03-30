# `calculate_dispersion` Implementation Analysis

## 1. Executive Summary

### 1.1 当前实现一句话总结
`calculate_dispersion` 当前不是一个“薄壳转调外部脚本”的工具，而是一个已经内化到主仓库中的两层实现：`tools/dispersion.py` 负责从 agent 会话上下文中取上游排放结果、做气象/场景/coverage 包装；`calculators/dispersion.py` 直接在本仓库内完成道路几何预处理、10 m 分段、受体生成、气象处理、XGBoost surrogate 推理、受体级结果组装、栅格化和道路贡献跟踪。

### 1.2 与外部 surrogate 仓库的一句话总结
当前运行时**不直接依赖** `ps-xgb-aermod-rline-surrogate` 里的 Python 脚本（没有 import `mode_inference.py`，也没有 subprocess 调用），但**默认直接依赖**该目录下的模型资产 `ps-xgb-aermod-rline-surrogate/models/...`。因此它不是“仅供参考”，也不是“完全脱钩”；更准确的结论是：**核心推理逻辑已内化，默认模型文件仍挂在该外部目录下作为运行时资产依赖**。

### 1.3 分析方法说明
本文结论主要来自以下真实代码与仓库元数据：

- `tools/dispersion.py`
- `calculators/dispersion.py`
- `calculators/dispersion_adapter.py`
- `core/router.py`
- `core/readiness.py`
- `core/tool_dependencies.py`
- `core/context_store.py`
- `tools/hotspot.py`
- `calculators/hotspot_analyzer.py`
- `tools/spatial_renderer.py`
- `tools/scenario_compare.py`
- `calculators/scenario_comparator.py`
- `config/meteorology_presets.yaml`
- `tools/registry.py`
- `tools/definitions.py`
- `config.py`
- 仓库 git 元数据：`git ls-files -s ps-xgb-aermod-rline-surrogate`、`git submodule status`、`ps-xgb-aermod-rline-surrogate/.git`

说明：

- **代码事实**：直接来自代码与本地 git 元数据。
- **基于代码的合理推断**：用于解释设计意图、工程风险或论文表述边界。
- 本次没有实际运行扩散计算；结论以静态代码核查为主。

## 2. High-Level Call Chain

下面按“用户请求 -> agent -> tool wrapper -> calculator -> 下游工具/前端”的顺序梳理。

```text
用户请求
  -> core prompt / skill injection / LLM tool selection
  -> readiness / dependency validation / geometry gating
  -> router 注入上游 emission 结果到 _last_result
  -> tools/dispersion.py
       - 解析 emission_source
       - 适配 emission -> roads_gdf + emissions_df
       - assess_coverage
       - meteorology preset/custom/.sfc 组装
       - 调用 DispersionCalculator
  -> calculators/dispersion.py
       - merge geometry + emissions
       - WGS84 -> UTM/local
       - 10m road segmentation
       - receptor generation
       - meteorology normalization/alignment
       - load XGBoost models
       - surrogate inference
       - receptor result + raster_grid + road_contributions
  -> tool wrapper 补充 meteorology_used / scenario_label / defaults_used / map_data
  -> router 保存到 SessionContextStore + legacy spatial memory
  -> 下游
       - analyze_hotspots 直接消费 raster_grid + road_contributions
       - render_spatial_map 消费 dispersion payload 或 tool 自带 map_data
       - compare_scenarios 比较 summary 指标与 meteorology_used
       - frontend payload extractor 直接提取 map_data
```

### 2.1 从用户请求到 tool selection

**代码事实**

- 核心 prompt 将 `calculate_dispersion` 作为正式工具暴露给模型，定义为“大气扩散浓度场计算”：`config/prompts/core_v3.yaml:16-24`
- `SkillInjector` 用“扩散 / 浓度 / dispersion / concentration / 大气 / 扩散分析”等关键词注入 `dispersion_skill` 和 `meteorology_guide`，并把 `calculate_dispersion`、`render_spatial_map` 作为相关工具：`core/skill_injector.py:28-33`
- `core/router.py` 也把 `calculate_dispersion` 绑定到 continuation 关键词 `["扩散", "dispersion", "浓度", "concentration", "raster"]`：`core/router.py:296-305`
- `dispersion_skill` 明确要求在调用工具前先确认气象条件，除非用户已明确指定或是在回应上一轮确认：`config/skills/dispersion_skill.yaml:7-28`

**基于代码的合理推断**

- 在默认配置下（`ENABLE_STATE_ORCHESTRATION=true`、`ENABLE_READINESS_GATING=true`、`ENABLE_INTENT_RESOLUTION=true`、`ENABLE_SKILL_INJECTION=true`），扩散请求通常不是“直接裸调工具”，而是先经过 intent/readiness/skill 三层约束：`config.py:50-61`, `config.py:101-124`, `config.py:199-200`

### 2.2 readiness / dependency / action catalog 如何约束它

**代码事实**

- canonical dependency graph 把 `calculate_dispersion` 定义为 `requires=["emission"]`, `provides=["dispersion"]`：`core/tool_dependencies.py:39-49`
- action catalog 中，`run_dispersion` 对应 `tool_name="calculate_dispersion"`，并额外要求 `requires_geometry_support=True`：`core/readiness.py:782-790`
- readiness 先做 canonical prerequisite 校验，再做 geometry 支持校验：
  - prerequisite 失败 -> `missing_prerequisite_result` / `stale_prerequisite_result`：`core/readiness.py:1201-1225`, `core/readiness.py:638-667`
  - geometry 缺失 -> `missing_geometry`：`core/readiness.py:1226-1241`, `core/readiness.py:670-677`
- geometry support 的判定来源有：
  - `file_context.spatial_metadata`
  - `file_context.spatial_context`
  - geospatial dataset roles
  - 几何相关列名信号
  - 已有 emission result 是否含 geometry：`core/readiness.py:412-444`
- render action `render_dispersion_map` 还要求 `requires_spatial_result_token="dispersion"`，即当前 dispersion 结果里必须存在可渲染的空间 payload（`raster_grid` / `concentration_grid` / 等）：`core/readiness.py:814-823`, `core/readiness.py:336-360`

**基于代码的合理推断**

- 这意味着 `calculate_dispersion` 在 agent 里不是单纯“有 emission 就能跑”，还被更严格地限制为“有 emission 且有 geometry support 才 ready”。

### 2.3 router 在执行前如何准备参数

**代码事实**

- router 会在工具真正执行前调用 `_prepare_tool_arguments()`，专门对 `calculate_dispersion`、`analyze_hotspots`、`render_spatial_map` 注入 `_last_result`：`core/router.py:545-625`
- 对 `calculate_dispersion`：
  - 优先从 `SessionContextStore.get_result_for_tool("calculate_dispersion", label=scenario_label)` 取上游结果：`core/router.py:570-581`
  - 如果 context store 没有，再尝试 legacy `memory.fact_memory.last_spatial_data`，但要求其中 `results[*]` 看起来像宏观排放（存在 `total_emissions_kg_per_hr`）：`core/router.py:602-614`
- `SessionContextStore` 为 `calculate_dispersion` 声明的依赖类型是 `["emission"]`：`core/context_store.py:64-75`
- `SessionContextStore.get_result_for_tool()` 支持按 `scenario_label` 取指定情景，如果没找到且不是 `baseline`，会回退到 `baseline`：`core/context_store.py:117-177`, `core/context_store.py:303-346`

**基于代码的合理推断**

- `calculate_dispersion` 的“默认上游输入”不是文件，也不是用户直接给的原始几何，而是**会话上下文里最新/指定情景的 emission 结果**。

## 3. Tool-Layer Implementation

### 3.1 注册、schema 与工具定位

**代码事实**

- 工具注册发生在 `tools/registry.py`，`DispersionTool()` 被注册为 `calculate_dispersion`；注册失败只记 warning：`tools/registry.py:121-125`
- schema 里公开的参数包括：
  - `emission_source`
  - `meteorology`
  - `wind_speed`
  - `wind_direction`
  - `stability_class`
  - `mixing_height`
  - `roughness_height`
  - `grid_resolution`
  - `pollutant`
  - `scenario_label`
  见 `tools/definitions.py:215-275`
- schema 文案把它定义为“从 vehicle emissions 计算 pollutant dispersion/concentration distribution”，并明确依赖 emission results、产出 spatial concentration raster field：`tools/definitions.py:216-221`

### 3.2 `tools/dispersion.py` 实际做什么

**代码事实**

- `DispersionTool` 在构造函数中绑定：
  - `DispersionCalculator`
  - `DispersionConfig`
  - `EmissionToDispersionAdapter`
  并维护按 roughness 高度缓存 calculator 的 `_calculator_cache`：`tools/dispersion.py:57-76`
- `execute()` 的核心流程是：
  1. 读参数并记录哪些参数用了默认值：`tools/dispersion.py:89-105`
  2. `_resolve_emission_source()` 解析 `_last_result`：`tools/dispersion.py:107-113`, `tools/dispersion.py:174-210`
  3. 解析/继承 `scenario_label`：`tools/dispersion.py:115-117`, `tools/dispersion.py:212-219`
  4. `EmissionToDispersionAdapter.adapt()` 把 emission result 转成 `roads_gdf` 和 `emissions_df`：`tools/dispersion.py:118`
  5. `assess_coverage(roads_gdf)` 生成 coverage 语义：`tools/dispersion.py:126-131`
  6. `_build_met_input()` 把 preset/custom/.sfc 参数整理为 calculator 可接受格式：`tools/dispersion.py:133`, `tools/dispersion.py:221-358`
  7. `_get_calculator()` 取 roughness 对应的 calculator，并把 display grid resolution 写进 config：`tools/dispersion.py:134-143`, `tools/dispersion.py:368-379`
  8. 调用 `calculator.calculate(...)`：`tools/dispersion.py:137-143`
  9. 将 result data 补充 `coverage_assessment`、`meteorology_used`、`scenario_label`、`defaults_used`，再构造 `summary` 与 `map_data`：`tools/dispersion.py:152-165`

### 3.3 工具层输入整理的真实限制

**代码事实**

- `_resolve_emission_source()` 目前只真正支持 `emission_source="last_result"`；传文件路径只会 warning 后返回 `None`：`tools/dispersion.py:180-210`
- `_resolve_emission_source()` 要求 `_last_result.data.results` 是 list，且样本项中至少带 `total_emissions_kg_per_hr` 或 `link_length_km`，否则视为“不像 macro emission output”：`tools/dispersion.py:192-200`
- geometry 缺失时，工具层直接返回错误 `"No road geometry found in emission results"`：`tools/dispersion.py:118-124`
- roughness 只允许 `0.05 / 0.5 / 1.0`：`tools/dispersion.py:368-376`

**基于代码的合理推断**

- 虽然 canonical dependency graph 把 `calculate_micro_emission` 和 `calculate_macro_emission` 都视为 `emission` 提供者，但 `calculate_dispersion` 的 tool wrapper 实际只接受**宏观排放风格**的上游结构。
- 微观排放结果的 `results[*]` 是逐时刻轨迹点 `{t, speed_kph, vsp, emissions}`，不包含 `total_emissions_kg_per_hr`、`link_length_km`、road geometry，因此当前不能直接作为 `calculate_dispersion` 上游：`calculators/micro_emission.py:134-158`, `tools/micro_emission.py:196-244`

### 3.4 工具层里的气象处理

**代码事实**

- 支持三类 meteorology 输入：
  - 预设名，例如 `urban_summer_day`
  - `"custom"` + 覆盖参数
  - `.sfc` 文件路径
  逻辑在 `_build_met_input()`：`tools/dispersion.py:221-273`
- 预设从 `config/meteorology_presets.yaml` 读取：`tools/dispersion.py:49-55`
- 允许在 preset 基础上覆盖：
  - `wind_speed`
  - `wind_direction`
  - `stability_class`
  - `mixing_height`
  逻辑见 `MET_OVERRIDE_KEYS` 与 `_extract_meteorology_overrides()`：`tools/dispersion.py:46`, `tools/dispersion.py:275-289`
- 自定义稳定度会被映射到 `monin_obukhov_length` 与 `H`：`tools/dispersion.py:30-45`, `tools/dispersion.py:291-299`
- result data 中会保留 `meteorology_used`，并标记 `_source_mode` 为 `preset` / `preset_override` / `custom` / `sfc_file`：`tools/dispersion.py:154`, `tools/dispersion.py:327-358`

### 3.5 工具层输出包装

**代码事实**

- 工具层返回的是标准 `ToolResult`，包含：
  - `success`
  - `data`
  - `summary`
  - `map_data`
  定义在 `tools/base.py:13-28`
- `calculate_dispersion` 自己就构造了 `map_data`，不是必须额外再跑 `render_spatial_map` 才有前端 map payload：`tools/dispersion.py:159-165`, `tools/dispersion.py:470-483`
- 其 `map_data` 结构是：
  - `type: "concentration"`
  - `concentration_grid`
  - `pollutant`
  - `summary`
  - `query_info`
  - 可选 `raster_grid`
  - 可选 `coverage_assessment`
  见 `tools/dispersion.py:470-483`

## 4. Calculator-Layer Implementation

### 4.1 总体定位

**代码事实**

- `calculators/dispersion.py` 文件头就声明自己是从 legacy surrogate script 提取出来的 dispersion utilities：`calculators/dispersion.py:1`
- `DispersionCalculator` 的 docstring 直接写明：它封装了 `mode_inference.py` 的全流程 `road loading -> coordinate transform -> segmentation -> receptor generation -> meteorology processing -> model inference -> result assembly`：`calculators/dispersion.py:997-1004`

### 4.2 配置对象 `DispersionConfig`

**代码事实**

- 关键配置项包括：
  - `source_crs="EPSG:4326"`
  - `utm_zone=51`
  - `utm_hemisphere="north"`
  - `segment_interval_m=10.0`
  - `default_road_width_m=7.0`
  - `offset_rule={3.5: 40, 8.5: 40}`
  - `background_spacing_m=50.0`
  - `buffer_extra_m=3.0`
  - `display_grid_resolution_m=50.0`
  - 下/上风与横风裁剪范围
  - `batch_size=200000`
  - `roughness_height`
  - `model_base_dir`
  见 `calculators/dispersion.py:28-59`

**基于代码的合理推断**

- 论文里如果画系统图，这些默认值更像“当前工程实现参数”，不是从 agent 层动态学习出来的参数。

### 4.3 `DispersionCalculator.calculate()` 的真实计算链

**代码事实**

- `calculate()` 的顺序是固定的：`calculators/dispersion.py:1015-1087`
  1. `_validate_inputs()`
  2. `_merge_roads_and_emissions()`
  3. `_transform_to_local()`
  4. `_segment_roads()`
  5. `_generate_receptors()`
  6. `_build_source_arrays()`
  7. `_process_meteorology()`
  8. `_align_sources_and_met()`
  9. `_ensure_models_loaded()`
  10. `predict_time_series_xgb()`
  11. `inverse_transform_coords()`
  12. `_assemble_result()`

### 4.4 输入校验

**代码事实**

- 只支持 `pollutant == "NOx"`：`calculators/dispersion.py:1089-1096`
- `roads_gdf` 必须是 `GeoDataFrame`，且至少有 `NAME_1`, `geometry`：`calculators/dispersion.py:1098-1105`
- `emissions_df` 至少要有 `NAME_1`, `data_time`, `nox`, `length`：`calculators/dispersion.py:1106-1112`

### 4.5 道路-排放合并与排放强度换算

**代码事实**

- `_merge_roads_and_emissions()` 会按 `NAME_1` 把 geometry 与 emission row 合并：`calculators/dispersion.py:1114-1167`
- 如果 `width` 缺失，使用默认道路宽度 `7.0 m`：`calculators/dispersion.py:1148-1150`
- 会构造：
  - `road_index`
  - `day`
  - `hour`
  - `nox_g_m_s2`
- `nox_g_m_s2` 通过 `emission_to_line_source_strength()` 计算，公式是：

```text
nox_kg_h * 1000 / 3600 / (length_km * 1000 * road_width_m)
```

  见 `calculators/dispersion.py:1157-1163`, `calculators/dispersion.py:944-958`

### 4.6 坐标转换与局部坐标系

**代码事实**

- `_transform_to_local()` 先取 geometry 坐标，再用 `convert_coords()` 把输入 CRS 转为 `config` 指定的 UTM：`calculators/dispersion.py:1169-1212`
- 然后用所有 UTM 点的最小 `x/y` 作为 `local origin`，把 UTM 坐标转成局部坐标：`calculators/dispersion.py:1198-1202`, `calculators/dispersion.py:672-677`
- 最终结果里 `query_info.local_origin` 会保留这个 origin：`calculators/dispersion.py:1516-1525`
- 反投影使用 `inverse_transform_coords()`，将 local 坐标加回 origin，再从 UTM 反投影到 WGS84：`calculators/dispersion.py:680-701`

**基于代码的合理推断**

- 当前真正用于计算的不是原始经纬度，而是 `WGS84 -> UTM -> local` 之后的局部米制坐标。

### 4.7 道路分段

**代码事实**

- `_segment_roads()` 对每条 road 的 `new_coords` 按 `segment_interval_m=10 m` 做固定距离分段：`calculators/dispersion.py:1214-1244`
- `split_polyline_by_interval_with_angle()` 返回每个子段的：
  - `x_mid`
  - `y_mid`
  - `angle_deg`
  见 `calculators/dispersion.py:314-349`
- 分段后的 source record 包含：
  - `road_id`
  - `road_idx`
  - `NAME_1`
  - `segment_id`
  - `xm`
  - `ym`
  - `angle_deg`
  - `interval`
  见 `calculators/dispersion.py:1227-1238`

### 4.8 受体生成

**代码事实**

- `_generate_receptors()` 调用 `generate_receptors_custom_offset()`：`calculators/dispersion.py:1246-1261`
- 运行时传入的 offset rule 来自 `DispersionConfig` 默认值 `{3.5: 40, 8.5: 40}`，而不是函数签名里展示的旧默认值：`calculators/dispersion.py:42-45`, `calculators/dispersion.py:1251-1256`
- `generate_receptors_custom_offset()` 做两类受体：
  - road-near receptors：沿道路左右侧按 offset/spacing 生成
  - background grid：按 `background_spacing` 生成背景网格
  见 `calculators/dispersion.py:205-311`
- 函数会先为每条道路构造矩形 road buffer，再把落在 buffer 内的受体剔除：`calculators/dispersion.py:220-237`, `calculators/dispersion.py:301-308`

### 4.9 气象处理与时间对齐

**代码事实**

- `_process_meteorology()` 支持三种 calculator 级输入：
  - `pd.DataFrame`
  - `dict`
  - `str`（预设名或 `.sfc` 路径）
  见 `calculators/dispersion.py:1300-1370`
- `.sfc` 输入走 `read_sfc()`，再基于 `L`, `WSPD`, `MixHGT_C` 推导 `Stab_Class`：`calculators/dispersion.py:1331-1349`, `calculators/dispersion.py:352-360`
- preset 输入从 `config/meteorology_presets.yaml` 读出，转成一条 met record：`calculators/dispersion.py:1351-1368`
- `_normalize_met_df()` 要求至少包含 `Date`, `WSPD`, `WDIR`, `MixHGT_C`, `L`；若无 `Stab_Class` 则自动分类：`calculators/dispersion.py:1372-1393`
- `_align_sources_and_met()` 只支持三种对齐方式：
  - emission timestep 数 == met rows
  - emission 只有 1 个 timestep，则复制到全部 meteorology timesteps
  - meteorology 只有 1 行，则复制到全部 emission timesteps
  否则报错：`calculators/dispersion.py:1395-1423`

**基于代码的合理推断**

- 对宏观排放这条链路，adapter 默认构造的是单时刻排放，因此 preset/custom 气象基本上对应“稳态单时刻”或“把单时刻排放复制到整段气象序列”的模式，而不是完整的时变交通-时变气象耦合模拟。

### 4.10 XGBoost surrogate 推理

**代码事实**

- `load_all_models()` 会为给定 roughness 高度加载 6 个稳定度 * 2 个方向（x0 / x-1）共 12 个模型：`calculators/dispersion.py:961-994`
- 默认模型目录通过 `_default_model_base_dir()` 指向：

```text
<repo>/ps-xgb-aermod-rline-surrogate/models
```

  见 `calculators/dispersion.py:118-120`
- `predict_time_series_xgb()` 的输入是：
  - `receptors_x`
  - `receptors_y`
  - `sources`，形状 `(T, N_sources, 4)`，每个 source 是 `(x, y, emission, road_angle)`
  - `met`
  - 范围裁剪参数
  - `track_road_contributions`
  见 `calculators/dispersion.py:370-382`
- 核心数值路径是：
  1. 按风向旋转 receptors 和 sources：`calculators/dispersion.py:472-479`
  2. 计算每个 receptor 相对每个 source 的 `x_hat`, `y_hat`：`calculators/dispersion.py:481-482`
  3. 分 downwind (`x>=0`) 与 upwind (`x<0`) 两个 mask：`calculators/dispersion.py:489-556`
  4. 按稳定度类决定 7 维或 8 维特征：
     - `VS/S/N1` 走 7 维特征
     - `N2/U/VU` 走 8 维特征
     见 `calculators/dispersion.py:390`, `calculators/dispersion.py:500-524`, `calculators/dispersion.py:562-586`
  5. 对每个方向调用对应 XGBoost 模型批量预测，再乘以 source strength 累加到 receptor：`calculators/dispersion.py:526-532`, `calculators/dispersion.py:588-595`

### 4.11 道路贡献跟踪

**代码事实**

- `calculate()` 固定把 `track_road_contributions=True` 传给 `predict_time_series_xgb()`：`calculators/dispersion.py:1041-1053`
- 如果 `n_receptors * n_roads <= 10,000,000`，使用 `dense_exact` 矩阵精确记录；否则退化成 `sparse_topk`：`calculators/dispersion.py:24-25`, `calculators/dispersion.py:421-439`
- 稀疏模式下会定期裁剪每个 receptor 的 road contribution map，只保留较大的若干项：`calculators/dispersion.py:538-549`, `calculators/dispersion.py:600-611`, `calculators/dispersion.py:850-865`
- 最终 `_serialize_road_contributions()` 产出：
  - `receptor_top_roads`
  - `road_id_map`
  - `top_k`
  - `effective_timesteps`
  - `tracking_mode`
  - `description`
  见 `calculators/dispersion.py:914-941`

### 4.12 结果组装与栅格化

**代码事实**

- `_assemble_result()` 同时产出三种空间结果：`calculators/dispersion.py:1437-1562`
  - `results`：受体点级完整结果
  - `concentration_grid`：点位版简化输出
  - `raster_grid`：规则栅格版输出
- `results[*]` 包括：
  - `receptor_id`
  - `lon`
  - `lat`
  - `local_x`
  - `local_y`
  - `concentrations`（每个时间步的字典）
  - `mean_conc`
  - `max_conc`
  见 `calculators/dispersion.py:1478-1488`
- `concentration_grid` 包括：
  - `receptors`
  - `bounds`
  见 `calculators/dispersion.py:1535-1538`
- `raster_grid` 来自 `aggregate_to_raster()`，是显示型后处理，不影响 surrogate 推理精度：`calculators/dispersion.py:704-719`, `calculators/dispersion.py:1539-1548`
- `raster_grid` 包括：
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
  见 `calculators/dispersion.py:724-740`, `calculators/dispersion.py:825-847`

## 5. Input / Output Contract

### 5.1 输入契约

| 输入来源 | 真实字段/格式 | 使用位置 |
| --- | --- | --- |
| 上游 emission result | `_last_result`，要求 `data.results` 为 list，且结果项看起来像宏观排放 | `tools/dispersion.py:_resolve_emission_source` |
| emission result row | `link_id`, `total_emissions_kg_per_hr.NOx`, `link_length_km`, `geometry`, 可选 `data_time` | `calculators/dispersion_adapter.py:24-47`, `127-147` |
| geometry 格式 | shapely geometry / WKT / GeoJSON dict / `{geometry:...}` / `{wkt:...}` / 坐标列表 | `calculators/dispersion_adapter.py:95-124` |
| calculator roads_gdf | `NAME_1`, `geometry`, 可选 `width` | `calculators/dispersion.py:1098-1105`, `1129-1150` |
| calculator emissions_df | `NAME_1`, `data_time`, `nox`, `length` | `calculators/dispersion.py:1106-1112` |
| meteorology tool 参数 | `meteorology`, `wind_speed`, `wind_direction`, `stability_class`, `mixing_height` | `tools/dispersion.py:81-88`, `221-358` |
| meteorology calculator 参数 | `pd.DataFrame` / `dict` / preset string / `.sfc` path | `calculators/dispersion.py:1300-1370` |
| scenario 参数 | `scenario_label` | router 取上游 + context store 存储 |

### 5.2 上游 emission 到 dispersion 的真实字段映射

**代码事实**

- `EmissionToDispersionAdapter` 的字段映射写得很明确：`calculators/dispersion_adapter.py:29-37`
  - `macro_result.results[*].link_id -> NAME_1`
  - `macro_result.results[*].total_emissions_kg_per_hr.NOx -> nox`
  - `macro_result.results[*].link_length_km -> length`
  - `macro_result.results[*].geometry -> geometry`
- adapter 会把 `data_time` 缺失的情况补成合成时间戳 `2024-01-01 00:00:00`：`calculators/dispersion_adapter.py:131-147`

### 5.3 输出契约

**代码事实**

- `calculate_dispersion` 工具的成功返回是一个 `ToolResult`，其中：
  - `success=True`
  - `data=<dispersion payload>`
  - `summary=<文本摘要>`
  - `map_data=<空间 payload>`
  见 `tools/dispersion.py:159-165`, `tools/base.py:13-28`
- `data.query_info` 的关键字段包括：`calculators/dispersion.py:1516-1525`
  - `pollutant`
  - `n_roads`
  - `n_receptors`
  - `n_time_steps`
  - `roughness_height`
  - `met_source`
  - `local_origin`
  - `display_grid_resolution_m`
- `data.summary` 的关键字段包括：`calculators/dispersion.py:1527-1534`
  - `receptor_count`
  - `time_steps`
  - `mean_concentration`
  - `max_concentration`
  - `unit`
  - `coordinate_system`
- tool wrapper 额外补充：`tools/dispersion.py:152-158`
  - `coverage_assessment`
  - `meteorology_used`
  - `scenario_label`
  - `defaults_used`

### 5.4 输出如何被 hotspot / map / memory 使用

**代码事实**

- `analyze_hotspots` 直接读取：
  - `raster_grid`
  - `road_contributions`
  - `coverage_assessment`
  - `query_info`
  - `meteorology_used`
  - `scenario_label`
  见 `tools/hotspot.py:41-99`
- hotspot analyzer 用 `raster_grid.cell_receptor_map` + `road_contributions.receptor_top_roads` 把 receptor 级道路贡献聚合到 cluster 级热点贡献：`calculators/hotspot_analyzer.py:437-520`
- `render_spatial_map` 可以从 dispersion payload 中构造：
  - receptor point map（`concentration_grid` / `results`）
  - raster polygon map（`raster_grid`）
  见 `tools/spatial_renderer.py:362-664`
- router 的 frontend payload extractor 会直接从 tool results 中提取 `map_data`；如果只有一个 map payload，就直接把它作为 response map_data 返回：`core/router_payload_utils.py:13-36`, `core/router_payload_utils.py:300-334`
- `SessionContextStore` 会把该结果存为 `dispersion:<scenario_label>`，供下游工具复用：`core/context_store.py:52-66`, `core/context_store.py:82-115`
- legacy memory 里，如果结果里含 `concentration_grid` 或 `raster_grid`，router 还会把它写入 `memory.fact_memory.last_spatial_data`：`core/router.py:529-543`

## 6. Integration with the Agent

### 6.1 它在 agent 中的真实位置

**代码事实**

- 工具层入口是 `tools/dispersion.py:DispersionTool.execute`
- 注册入口是 `tools/registry.py:121-125`
- schema 入口是 `tools/definitions.py:215-275`
- canonical dependency 入口是 `core/tool_dependencies.py:43-46`
- action catalog 映射是 `run_dispersion -> calculate_dispersion`：`core/readiness.py:782-790`, `core/readiness.py:891-915`
- 计划模板中，`macro_spatial_chain` 把它放在 `calculate_macro_emission` 之后、`analyze_hotspots` 之前：`core/workflow_templates.py:217-251`

### 6.2 readiness / dependency enforcement / plan refresh

**代码事实**

- 执行前 router 会调用 `_validate_execution_dependencies()`，它内部再调用 `validate_tool_prerequisites()`：`core/router.py:7391-7425`
- residual plan 也会在执行过程中反复根据 available result tokens 刷新 step readiness：`core/router.py:6892-6927`
- `TaskState.execution.available_results` 是 runtime token 集合，完成工具后会更新：`core/task_state.py:186-203`, `core/router.py:9056-9059`

### 6.3 SessionContextStore / stale 传播 / scenario 管理

**代码事实**

- 成功结果会通过 `router._save_result_to_session_context()` 进入 `SessionContextStore`：`core/router.py:495-499`
- `SessionContextStore.TOOL_TO_RESULT_TYPE` 将 `calculate_dispersion` 映射为 `dispersion`：`core/context_store.py:52-62`
- 同 label 下，如果新的 emission 到来，会把已有 `dispersion`、`hotspot` 标记为 stale；如果新的 dispersion 到来，会把已有 `hotspot` 标记为 stale：`core/context_store.py:104-108`, `core/context_store.py:472-479`
- `get_result_for_tool()` 支持按 `scenario_label` 解析上游结果，并在缺失时回退到 baseline：`core/context_store.py:117-177`

### 6.4 下游动作链

**代码事实**

- `calculate_dispersion -> analyze_hotspots`：hotspot tool 明确要求先跑 dispersion：`tools/hotspot.py:7-15`, `tools/hotspot.py:41-55`
- `calculate_dispersion -> compare_scenarios(result_type="dispersion")`：scenario comparator 只比较 `summary.mean_concentration`、`summary.max_concentration` 和 `meteorology_used` 变更：`calculators/scenario_comparator.py:132-176`
- `calculate_dispersion -> render_spatial_map`：
  - auto-detect 时，若 payload 含 `raster_grid`，renderer 会优先走 `raster` 分支：`tools/spatial_renderer.py:183-197`
  - 若 payload 含 `concentration_grid` 或 `results`，也能构造 point map：`tools/spatial_renderer.py:362-545`

### 6.5 “是否必须再调 render_spatial_map”这个问题

**代码事实**

- `calculate_dispersion` 自己就返回 `map_data`：`tools/dispersion.py:159-165`, `470-483`
- frontend payload 抽取逻辑会直接收集 tool result 里的 `map_data`，不要求这一定来自 `render_spatial_map`：`core/router_payload_utils.py:13-36`, `300-334`

**基于代码的合理推断**

- 所以“扩散 -> 渲染”不是强制线性依赖。更准确地说：
  - `calculate_dispersion` 已经能把 dispersion 结果变成一个可交付的 map payload
  - `render_spatial_map` 是可选的专门渲染器，用于把已有空间结果转成更标准的 map config / layer 结构

## 7. Relationship to `ps-xgb-aermod-rline-surrogate`

### 7.1 是否直接 import / 调用外部仓库代码

**代码事实**

- 在主仓库运行路径里，没有发现：
  - `import mode_inference`
  - `sys.path.append(...)` 指向该目录
  - `subprocess` 调用该目录脚本
  - shell out 到 `python ps-xgb-aermod-rline-surrogate/...`
- repo 内与运行相关的直接引用，核心只有：
  - `calculators/dispersion.py` 中的默认模型目录 `_default_model_base_dir()`：`calculators/dispersion.py:118-120`
  - 文件头/注释里说明实现来自 legacy `mode_inference.py`：`calculators/dispersion.py:1`, `997-1004`

### 7.2 是否已经内化关键实现

**代码事实**

- 当前 `calculators/dispersion.py` 已直接包含以下原本可由外部脚本承担的核心能力：
  - 坐标转换：`convert_coords`, `inverse_transform_coords`
  - 路段矩形 buffer：`make_rectangular_buffer`
  - 受体生成：`generate_receptors_custom_offset`
  - 道路分段：`split_polyline_by_interval_with_angle`
  - `.sfc` 读取：`read_sfc`
  - 稳定度分类：`classify_stability`
  - XGBoost 模型加载：`load_model`, `load_all_models`
  - surrogate 推理：`predict_time_series_xgb`
  - 结果组装/栅格化：`aggregate_to_raster`, `_assemble_result`

**结论**

- **核心实现已经内化到当前仓库。**

### 7.3 当前运行时是否仍依赖该目录

**代码事实**

- 默认模型目录是：

```text
Path(__file__).resolve().parents[1] / "ps-xgb-aermod-rline-surrogate" / "models"
```

  `calculators/dispersion.py:118-120`
- `load_all_models()` 会在这个目录下继续寻找 `model_z=0.05` / `model_z=0.5` / `model_z=1` 子目录里的 12 个 JSON 文件：`calculators/dispersion.py:961-994`
- `requirements.txt` 也已把 `xgboost`、`scipy`、`scikit-learn` 提升为主仓库依赖：`requirements.txt:5-8`

**结论**

- **当前运行时默认直接依赖该目录中的模型文件资产。**
- 更精确地说：**依赖的是该目录的 `models/` 内容，而不是该目录里的 Python 脚本入口。**

### 7.4 这个目录现在扮演什么角色

#### 明确判断

- `ps-xgb-aermod-rline-surrogate` **不是纯开发参考目录**
  - 因为默认模型路径直接指向它，不存在就会影响实际运行
- 它 **也不是当前运行时代码入口**
  - 因为主执行链不 import / 不 shell out `mode_inference.py`
- 它当前最准确的角色是：
  - **历史外部 surrogate 仓库的嵌入副本 / 嵌套仓库**
  - **其中的模型资产是当前 dispersion 计算的默认运行依赖**
  - **其中的脚本代码主要是历史来源和开发参考**

### 7.5 git 关系是否像 submodule

**代码事实**

- `git ls-files -s ps-xgb-aermod-rline-surrogate` 返回 mode `160000`，这是 gitlink 记录形式
- `git submodule status` 报错：

```text
fatal: no submodule mapping found in .gitmodules for path 'ps-xgb-aermod-rline-surrogate'
```

- 根仓库没有 `.gitmodules`
- 但目录本身存在自己的 `.git`
- 该目录内部 remote 指向 `https://github.com/abusswer/ps-xgb-aermod-rline-surrogate`

**基于代码与 git 元数据的合理推断**

- 这看起来像一个**已经被作为 gitlink 记录、但没有在根仓库规范声明 `.gitmodules` 的嵌套仓库/残缺 submodule 形态**。
- 从工程治理角度看，它更像“历史上被嵌进来的外部仓库”，而不是一个干净的 vendored 普通目录。

## 8. Current Limitations and Risks

### 8.1 上游结果兼容性边界

**代码事实**

- dependency graph 只要求 `emission` token：`core/tool_dependencies.py:43-46`
- 但 tool wrapper 实际只接受“宏观排放风格”的 `_last_result`：`tools/dispersion.py:192-200`

**风险**

- `calculate_micro_emission` 虽然也提供 `emission` token，但当前格式与 `calculate_dispersion` 不兼容。
- 这意味着“dependency token 合法”不等于“payload 结构可用”。

### 8.2 geometry 边界

**代码事实**

- 无 geometry 时 readiness 先阻断：`core/readiness.py:1226-1241`
- tool wrapper 即便被直接执行，也会在 adapter 之后报 `"No road geometry found..."`：`tools/dispersion.py:118-124`
- calculator 只接受 `LineString` / `MultiLineString` 类型几何；`_extract_line_coords()` 对其他 geometry type 报错：`calculators/dispersion.py:128-139`

**风险**

- 当前扩散链路本质上是**道路线源**模型，不适合直接吃 polygon / point geometry。

### 8.3 CRS 与空间坐标风险

**代码事实**

- calculator 默认 `utm_zone=51`, `utm_hemisphere="north"`：`calculators/dispersion.py:33-36`
- adapter 对解析出的几何默认设定 CRS 为 `EPSG:4326`：`calculators/dispersion_adapter.py:90-92`

**风险**

- 当前计算坐标系默认明显偏向 `WGS84 -> UTM 51N`。
- 如果输入 geometry 不是 WGS84 经纬度，或场景不在 UTM 51N 覆盖范围附近，而调用方又没有覆盖 `DispersionConfig`，结果会有明显空间误差。
- 注意：`coverage_assessment` 会自动估计 metric CRS，但**真正的 dispersion 计算不会自动估计 UTM zone**。

### 8.4 meteorology 边界

**代码事实**

- tool 层只暴露 preset / custom / `.sfc` 三种输入：`tools/dispersion.py:221-273`
- calculator 层额外支持 `DataFrame`，但这不是 tool schema 暴露给 agent 的常规入口：`calculators/dispersion.py:1300-1304`
- `_align_sources_and_met()` 只支持等长或单边复制，不支持更复杂的时间对齐：`calculators/dispersion.py:1395-1423`

**风险**

- 当前不是一个通用时序气象驱动框架，更像“单快照 emission + 单条或可复制 meteorology”的工程化包装。

### 8.5 `H` 字段语义不稳定

**代码事实**

- preset/custom 路径下，calculator 在 meteorology dict/record 中把 `H` 取自：
  - `surface_heat_flux`
  - 否则 `temperature_k`
  见 `calculators/dispersion.py:1322-1325`, `1358-1366`
- tool 层只有 custom stability metadata 才显式给 `H` 赋固定值：`tools/dispersion.py:291-299`

**风险**

- 当前 `H` 特征在不同输入路径下语义不完全一致，存在“用温度充当热通量特征”的情况。
- 这在论文方法部分不能表述成“严格使用真实 surface heat flux”；更稳妥的写法应是“当前系统使用 preset/custom meteorology surrogate features，其中部分 feature 由预设/映射值提供”。

### 8.6 pollutant / roughness / source model 边界

**代码事实**

- `pollutant != "NOx"` 会直接报错：`calculators/dispersion.py:1095-1096`
- roughness 只允许 `0.05 / 0.5 / 1.0`：`tools/dispersion.py:368-376`

**风险**

- 即使外部 surrogate README 声称物理上可泛化到 PM/CO2 等，**当前 agent 实现没有放开这个能力**。
- 论文里不能把当前系统描述成“已支持多污染物扩散”。

### 8.7 hotspot attribution 精度边界

**代码事实**

- road contributions 大问题规模下会退化到 `sparse_topk`：`calculators/dispersion.py:433-439`
- hotspot attribution 只基于每个 receptor 的 top roads 进行聚合：`calculators/hotspot_analyzer.py:466-520`

**风险**

- 大网络下 hotspot source attribution 不是完整贡献矩阵，而是**受 top-k 截断影响的近似归因**。

### 8.8 rendering 集成存在接口不一致

**代码事实**

- schema / readiness / action catalog 把 dispersion map 的 layer type 统一写成 `"dispersion"`：`tools/definitions.py:349-376`, `core/readiness.py:814-823`
- 但 `SpatialRendererTool.execute()` 实际只识别：
  - `hotspot`
  - `raster`
  - `emission`
  - `concentration`
  - `points`
  不识别 `"dispersion"`，未知时会落回 emission map 分支：`tools/spatial_renderer.py:120-137`

**风险**

- 这是一个真实的工程不一致点。
- 如果没有其他标准化层把 `"dispersion"` 重写成 `"raster"` 或 `"concentration"`，直接传 `layer_type="dispersion"` 存在走错分支的风险。

### 8.9 scenario label 可能与真实上游 payload 不一致

**代码事实**

- context store 对缺失情景会回退到 baseline：`core/context_store.py:159-168`, `326-346`
- 但 `DispersionTool` 的最终 `scenario_label` 优先取用户传入的 `kwargs["scenario_label"]`：`tools/dispersion.py:115-117`

**风险**

- 如果用户指定了一个不存在的情景标签，router 可能实际注入的是 baseline emission，但 tool 仍把结果标成用户要求的 scenario label。
- 这会造成“结果标签”和“真实上游来源”不一致。

### 8.10 外部资产依赖风险

**代码事实**

- 工具注册在 import 失败时会 warning 而不是 hard fail：`tools/registry.py:121-125`
- `calculators/dispersion.py` import 时就依赖 `xgboost`：`calculators/dispersion.py:14`
- 执行时还要求模型 JSON 位于默认目录：`calculators/dispersion.py:118-120`, `961-994`

**风险**

- 环境若缺 `xgboost` / `scikit-learn` 或模型文件目录不完整，`calculate_dispersion` 不是“降级成空结果”，而是会注册失败或执行失败。

## 9. Suggested Diagram for Paper

### 9.1 建议画法

建议把 `calculate_dispersion` 画成下面这几个模块，而不是简单写成一个黑盒“dispersion model”：

```text
User Request
  -> Router / Intent Resolution / Readiness
  -> Upstream Emission Result Resolver (SessionContextStore / scenario label)
  -> calculate_dispersion Tool Wrapper
       - emission adapter
       - meteorology preset/custom builder
       - coverage assessment
  -> DispersionCalculator Engine
       - geometry + CRS transform
       - road segmentation
       - receptor generation
       - meteorology normalization
       - XGBoost surrogate inference
       - raster / contribution assembly
  -> Stored Dispersion Result
       - receptor results
       - concentration_grid
       - raster_grid
       - road_contributions
       - coverage_assessment
  -> Downstream Consumers
       - hotspot analysis
       - spatial rendering
       - scenario comparison
       - frontend map payload
```

### 9.2 图中建议特别标出的“外部仓库关系”

建议把 `ps-xgb-aermod-rline-surrogate` 单独画成**侧边资源框**，并明确区分：

- `mode_inference.py` 等 legacy scripts：**historical reference / not executed**
- `models/*.json`：**runtime model assets loaded by current calculator**

这样既能准确体现“实现逻辑已内化”，又不会误导读者以为 agent 仍在直接调用外部脚本仓库。

### 9.3 论文表述建议

如果论文方法部分要忠于当前代码，建议使用类似表述：

- “The agent-level `calculate_dispersion` capability is implemented as an internal wrapper-engine pipeline.”
- “The wrapper resolves upstream link-level emission results, assembles meteorological inputs, and annotates coverage semantics.”
- “The engine internalizes the legacy PS-XGB-RLINE inference path, including road segmentation, receptor generation, wind-aligned feature construction, and XGBoost-based directional surrogate inference.”
- “The current runtime loads pre-trained surrogate model files from a bundled/nested `ps-xgb-aermod-rline-surrogate/models` directory, but does not directly execute the legacy external scripts.”

## 10. Bottom-Line Answers to the Five Core Questions

### A. `calculate_dispersion` 在 agent 中怎么被调用？

- 通过 prompt/schema/skill injection 暴露给 LLM。
- readiness 把它映射为 `run_dispersion`，要求 `emission` token + geometry support。
- router 执行前从 `SessionContextStore` 或 legacy spatial memory 注入 `_last_result`。
- 成功后结果进入 context store、legacy spatial memory、frontend map payload，并可继续喂给 hotspot / compare / render。

### B. 它的底层实现逻辑到底是什么？

- `tools/dispersion.py`：工具包装层，负责输入解析、适配、coverage、气象、结果包装。
- `calculators/dispersion.py`：真实计算层，负责 CRS、分段、受体、气象、模型加载、surrogate 推理、栅格化、贡献跟踪。

### C. 它的真实输入输出是什么？

- 输入核心是宏观排放风格结果：road geometry + `NOx kg/h` + `link_length_km`。
- 输出核心是：
  - receptor-level concentration results
  - `concentration_grid`
  - `raster_grid`
  - `road_contributions`
  - `coverage_assessment`
  - `meteorology_used`
  - `scenario_label`

### D. 它和 `ps-xgb-aermod-rline-surrogate` 的关系是什么？

- **不直接依赖其 Python 脚本运行**
- **默认直接依赖其 `models/` 资产目录**
- **关键 surrogate 实现已吸收到当前仓库**
- **该目录当前更像嵌套外部仓库/残缺 submodule，而不是单纯参考资料**

### E. 当前实现边界和局限是什么？

- 只支持 NOx
- 实际上只接受宏观排放风格上游结果
- 必须有 line geometry
- CRS 与 UTM 默认值较强硬编码
- meteorology 主要是 preset/custom/.sfc，时间对齐能力有限
- hotspot 归因是 top-k 近似
- renderer 对 `"dispersion"` layer type 存在接口不一致
- scenario label 可能与 baseline fallback 发生错标

