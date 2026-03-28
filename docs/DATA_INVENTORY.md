# EmissionAgent 真实扩散集成测试数据清单

生成范围：`/home/kirito/Agent1/emission_agent` 及其上级 `~/Agent1/`。  
目标：盘点当前仓库中可用于 **真实模型 + 真实/半真实道路数据 + 扩散链路** 的数据文件，并判断它们是否能直接满足 `DispersionCalculator` / `DispersionTool` 的输入要求。

## 一、模型文件状态

### 1.1 surrogate 模型目录完整性

模型根目录：`ps-xgb-aermod-rline-surrogate/models/`

| roughness 目录 | JSON 文件数 | 目录大小 | 状态 |
|---|---:|---:|---|
| `model_z=0.05` | 12 | 50M | 完整 |
| `model_z=0.5` | 12 | 47M | 完整 |
| `model_z=1` | 12 | 47M | 完整 |
| **合计** | **36** | **142M** | 完整 |

结论：

- 3 个 roughness 目录都齐全，每个目录正好 12 个模型文件。
- 命名模式与 Sprint 8/9 中 `load_all_models()` 的规则一致。
- 当前仓库具备跑 **真实 XGBoost surrogate 模型** 的物理文件条件。

### 1.2 模型加载验证

实际验证：

- 成功加载 `model_z=0.5/model_RLINE_remet_multidir_neutral1_x-1_M.json`
- 成功对 3 个 roughness 目录分别加载首个模型
- 样例加载结果：
  - `model_z=0.05` -> `12` 个文件，样例模型 `num_features=7`
  - `model_z=0.5` -> `12` 个文件，样例模型 `num_features=7`
  - `model_z=1` -> `12` 个文件，样例模型 `num_features=7`

说明：

- 本次只验证了每个 roughness 目录中首个模型的可加载性，没有逐个加载全部 36 个文件。
- 首个样例都来自 `neutral1` 模型，因此 `num_features=7`；其他稳定度分支可能是 7 或 8 维，符合 Sprint 8 的实现说明。

### 1.3 surrogate 子目录是否自带测试输入

`ps-xgb-aermod-rline-surrogate/` 当前只有：

- `README.md`
- `data_gen.py`
- `mode_inference.py`
- `models/`
- `requirements.txt`
- `training.py`

**未发现**：

- `data/`
- `input/`
- `test/`
- 作者自带的 road/emission/met 示例文件

`mode_inference.py` 中也明确写的是占位路径：

```python
ROAD_SHP    = r"YOUR_PATH\roads.shp"
EMISSION_CSV= r"YOUR_PATH\hourly_emission.csv"
MET_SFC     = r"YOUR_PATH\met_file.SFC"
```

结论：原 surrogate 子目录 **只提供模型和脚本，不提供真实测试输入数据**。

## 二、可用的道路数据

### 2.1 最有价值的道路测试文件

#### A. `test_data/test_20links.xlsx`

- 格式：Excel
- 大小：`9403 bytes`
- 行数：`20`
- 列：`link_id, length, flow, speed, geometry`
- geometry：WKT `LINESTRING`
- 坐标系：`WGS84 / EPSG:4326`（来源：`test_data/README.md`；文件本身只存 WKT）

适配性判断：

- 对 **宏观排放工具**：✅ 直接可用
- 对 **DispersionCalculator.calculate()**：⚠️ 不能直接用
  - 缺 `NAME_1`
  - 缺 `data_time`
  - 不是 `roads_gdf + emissions_df` 双输入
- 对 **真实端到端集成测试**：✅ 很适合，推荐作为小规模真实链路样本

#### B. `test_data/test_6links.xlsx`

- 格式：Excel
- 大小：`6548 bytes`
- 行数：`6`
- 列：`link_id, length, flow, speed, geometry`
- geometry：WKT `LINESTRING`
- 坐标系：`WGS84 / EPSG:4326`（来源：`test_data/README.md`）

适配性判断：

- 对 **宏观排放工具**：✅ 直接可用
- 对 **扩散链路手动联调**：✅ 适合最小人工验证
- 对 **`DispersionCalculator` 直接文件输入**：⚠️ 仍需适配

#### C. `test_data/test_shanghai_full.xlsx`

- 格式：Excel
- 大小：`30097 bytes`
- 行数：`150`
- 列：`link_id, length, flow, speed, geometry`
- geometry：WKT `LINESTRING`
- 坐标系：`WGS84 / EPSG:4326`（来源：`test_data/SHANGHAI_FULL_TEST_GUIDE.md` 与 `test_data/README.md`）

适配性判断：

- 对 **宏观排放工具**：✅ 直接可用
- 对 **真实扩散中等规模测试**：✅ 非常合适
- 对 **前端可视化/性能联调**：✅ 很适合

#### D. `test_data/test_shanghai_allroads.xlsx`

- 格式：Excel
- 大小：`3641431 bytes`
- 行数：`25370`
- 列：`link_id, highway, length, flow, speed, geometry`
- geometry：WKT `LINESTRING`
- 坐标系：`WGS84 / EPSG:4326`（来源：`test_data/ALLROADS_README.md` 与文件实测）

适配性判断：

- 对 **宏观排放工具**：✅ 直接可用
- 对 **真实扩散压力测试**：✅ 可用，但规模很大
- 对 **首次真实模型集成测试**：⚠️ 不推荐，先用 20/150 条版本

### 2.2 Shapefile / GeoJSON 道路数据

| 文件路径 | 格式 | 行数 | 关键列 | CRS | 是否满足 `roads_gdf` 要求 |
|---|---|---:|---|---|---|
| `GIS文件/上海市路网/opt_link.shp` | Shapefile | 25370 | `link_id, length, geometry` 等 | `EPSG:4326` | ⚠️ 部分满足；有 geometry，但无 `NAME_1`，也无 flow/speed |
| `test_data/test_shanghai_allroads/test_shanghai_allroads/test_shanghai_allroads.shp` | Shapefile | 25370 | `link_id, highway, length, flow, speed, geometry` | `EPSG:4326` | ⚠️ 通过 `link_id -> NAME_1` 轻量适配后可用 |
| `static_gis/roadnetwork.geojson` | GeoJSON | 25370 | `highway, name, geometry` | `EPSG:4326` | ⚠️ 仅 geometry source；缺稳定唯一 ID、无 flow/speed |
| `GIS文件/上海市路网/opt_node.shp` | Shapefile | 16622 | `node_id, geometry` | `EPSG:4326` | ❌ 节点点数据，不是道路 |
| `GIS文件/上海市底图/上海市.shp` | Shapefile | 16 | 行政区 polygon | `EPSG:4326` | ❌ 底图边界，不是道路 |
| `static_gis/basemap.geojson` | GeoJSON | 16 | `name, geometry` | `EPSG:4326` | ❌ 底图边界，不是道路 |

补充观察：

- `GIS文件/上海市路网/opt_link.xlsx` 也存在，行数 `25370`，列为：
  - `highway, name, ref, oneway, bridge, tunnel, lanes, motorroad, maxspeed, id, osm_type, from_node, to_node, length, dir, link_id, geometry_wkt`
- 它比 `opt_link.shp` 更易于直接读表，但仍缺 flow/speed，也不是 `NAME_1` 命名。

### 2.3 Shapefile ZIP 上传包

这些文件对 **真实 API / Web 上传联调** 很有价值：

| 文件 | 大小 | 压缩包内容 | 备注 |
|---|---:|---|---|
| `test_data/test_6links.zip` | `1697 bytes` | `.shp/.shx/.dbf/.prj/.cpg` | 小样本上传测试 |
| `test_data/test_20links.zip` | `3206 bytes` | `.shp/.shx/.dbf/.prj/.cpg` | 推荐的小规模真实集成样本 |
| `test_data/test_shanghai_full.zip` | `15054 bytes` | `.shp/.shx/.dbf/.prj/.cpg` | 中等规模联调 |
| `test_data/test_shanghai_allroads.zip` | `2008058 bytes` | 目录 + `.shp/.shx/.dbf/.prj/.cpg` | 大规模压力测试 |

### 2.4 道路数据结论

当前仓库 **不缺道路几何数据**。  
最好的候选是：

1. `test_data/test_20links.xlsx`
2. `test_data/test_shanghai_full.xlsx`
3. `test_data/test_shanghai_allroads.xlsx` / 对应 shapefile

真正的问题不在道路，而在 **扩散输入所需的标准化排放时序文件和 `.sfc` 气象文件**。

## 三、可用的排放数据

### 3.1 仓库中存在两类“排放相关文件”

#### 类别 A：宏观排放输入文件

这些文件是给 `calculate_macro_emission` 用的，不是扩散排放时序：

| 文件 | 格式 | 行数 | 列 | 用途 |
|---|---|---:|---|---|
| `test_data/test_20links.xlsx` | Excel | 20 | `link_id, length, flow, speed, geometry` | 宏观排放小样本输入 |
| `test_data/test_6links.xlsx` | Excel | 6 | `link_id, length, flow, speed, geometry` | 宏观排放最小样本 |
| `test_data/test_shanghai_full.xlsx` | Excel | 150 | `link_id, length, flow, speed, geometry` | 宏观排放中等规模 |
| `test_data/test_shanghai_allroads.xlsx` | Excel | 25370 | `link_id, highway, length, flow, speed, geometry` | 宏观排放全路网压力测试 |
| `evaluation/file_tasks/data/macro_direct.csv` | CSV | 3 | `link_id, length, flow, speed` | 宏观排放 benchmark 样本 |
| `evaluation/file_tasks/data/macro_cn_fleet.csv` | CSV | 3 | 中文字段 + fleet 列 | 宏观排放/标准化评测 |
| `evaluation/file_tasks/data/macro_fuzzy.csv` | CSV | 3 | 模糊字段名 | 宏观排放/标准化评测 |

判断：

- 这些文件可以驱动 **真实宏观排放计算**。
- 但它们 **不是扩散器直接需要的 emission time series 文件**。

#### 类别 B：宏观排放输出结果文件

`outputs/` 目录下存在大量运行时产物：

- `find outputs -maxdepth 1 -name '*emission_results*.xlsx' | wc -l` -> **181 个文件**

其中最相关的两份代表性文件是：

##### `outputs/test_20links_emission_results_20260321_103041.xlsx`

- 行数：`20`
- 列：`link_id, length, flow, speed, geometry, CO2_kg_h, NOx_kg_h`
- 特点：
  - 有 geometry
  - 有 `NOx_kg_h`
  - **没有 `data_time`**
  - **没有 `NAME_1`**
  - `NOx_kg_h` 字段名也不是 `nox`

##### `outputs/test_shanghai_allroads_emission_results_20260314_102129.xlsx`

- 行数：`25370`
- 列：`link_id, highway, length, flow, speed, geometry, CO2_kg_h, NOx_kg_h`
- 特点同上，适合做大规模链路联调素材

### 3.2 直接满足 `DispersionCalculator` 排放输入要求的文件是否存在？

`DispersionCalculator.calculate()` 期望的 `emissions_df` 关键列是：

- `NAME_1` 或经兼容处理后的路段 ID
- `data_time`
- `nox`
- `length`

本次对 `outputs/`、`test_data/`、`evaluation/file_tasks/data/`、`GIS文件/上海市路网/` 下的所有 `xlsx/xls/csv` 做了表头扫描，结果是：

```text
FOUND 0
NAME_1 0 []
data_time 0 []
nox 0 []
```

结论：

- **没有任何现成文件** 同时包含 `NAME_1 + data_time + nox + length`
- 甚至在扫描范围内，单独的 `NAME_1`、`data_time`、`nox` 列都没有出现
- 所以当前仓库 **没有现成的标准扩散排放输入文件**

### 3.3 排放数据适配性结论

最接近真实扩散输入的不是某个现成 CSV，而是：

1. `test_data/*.xlsx` 这类 **宏观排放原始输入**
2. `outputs/*emission_results*.xlsx` 这类 **宏观排放结果**

其中：

- 如果走 **工具链真实集成测试**，应优先采用 `test_data/*.xlsx` -> `calculate_macro_emission` -> `calculate_dispersion`
- 如果走 **calculator 级直接测试**，可用 `outputs/test_20links_emission_results_20260321_103041.xlsx` 这类结果表，做以下轻量适配：
  - `link_id -> NAME_1`
  - `NOx_kg_h -> nox`
  - 添加单步 `data_time`
  - `length` 原样沿用

## 四、可用的气象数据

### 4.1 `.sfc` 文件搜索结果

在 `~/Agent1/` 下搜索：

```bash
find ~/Agent1/ -name "*.sfc" -o -name "*.SFC"
```

结果：**未找到任何 `.sfc` / `.SFC` 文件**

### 4.2 当前可用的替代方案

虽然没有真实 `.sfc` 文件，但当前项目仍有两种可用气象来源：

1. `config/meteorology_presets.yaml`
   - 格式：YAML
   - 内容：6 个气象预设
   - 状态：✅ 当前 `DispersionCalculator` 可直接使用
   - 备注：这不是标准 AERMOD `.sfc`

2. `custom` 气象字典
   - 由工具或测试直接构造
   - 状态：✅ 当前 `DispersionCalculator` 可直接使用
   - 备注：也不是标准 `.sfc`

### 4.3 气象数据结论

- **标准 AERMOD `.sfc` 气象文件：缺失**
- **代码级可用替代：存在**（preset / custom）

如果目标是“真实集成测试”，当前仓库可以完成：

- **真实模型 + 真实道路 + 真实宏观排放 + 预设气象**

但还不能完成：

- **真实模型 + 真实道路 + 真实宏观排放 + 真实 `.sfc` 气象文件**

## 五、可用的内置测试数据

### 5.1 MOVES / 宏观 / 微观内置矩阵

内置 CSV 主要分布在：

- `calculators/data/emission_factors/*.csv`
- `calculators/data/macro_emission/*.csv`
- `calculators/data/micro_emission/*.csv`

代表文件：

- `calculators/data/emission_factors/atlanta_2025_1_55_65.csv`
- `calculators/data/macro_emission/atlanta_2025_4_75_65.csv`
- `calculators/data/micro_emission/atlanta_2025_7_90_70.csv`

判断：

- 这些是 **内置排放因子/计算矩阵**
- 它们对 **宏观排放、微观排放** 阶段是必需的
- 但它们 **不是扩散测试直接输入文件**

### 5.2 `test_data/` 目录中的高价值样本

`test_data/` 目前是最值得用于真实联调的数据目录，包含：

- `test_6links.xlsx/.zip`
- `test_20links.xlsx/.zip`
- `test_no_geometry.xlsx`
- `test_shanghai_full.xlsx/.zip`
- `test_shanghai_allroads.xlsx/.zip`
- 以及说明文档：
  - `README.md`
  - `ALLROADS_README.md`
  - `SHANGHAI_FULL_TEST_GUIDE.md`
  - `TESTING_GUIDE.md`

这些文档已经明确说明：

- 数据来自 `GIS文件/上海市路网/opt_link.shp`
- 几何为 `WGS84 / EPSG:4326`
- `flow/speed` 是模拟交通工况
- 设计初衷就是用于排放计算与地图可视化联调

### 5.3 运行时输出目录 `outputs/`

`outputs/` 中存在大量历史运行产物，尤其是：

- `*_emission_results_*.xlsx`

价值：

- 证明系统已经多次生成过宏观排放结果
- 可作为“半真实排放输入”素材
- 其中含 geometry 的文件可作为 direct calculator smoke 的原材料

局限：

- 不属于“策划好的标准测试集”
- 字段命名不统一
- 普遍缺 `data_time`

## 六、数据缺口分析

要跑“真实扩散集成测试”，当前仓库 **不是完全没数据**，但确实还缺关键环节。

### 6.1 当前已经具备的条件

- ✅ 真实 surrogate 模型文件（36 个 JSON）
- ✅ 真实道路 geometry（shapefile / geojson / WKT Excel）
- ✅ 宏观排放原始输入样本
- ✅ 宏观排放历史输出样本
- ✅ 气象预设 YAML

### 6.2 仍然缺失的关键数据

1. **标准扩散排放时序文件**
   - 缺 `NAME_1`
   - 缺 `data_time`
   - 缺标准化命名的 `nox`
   - 目前没有一份现成文件能直接喂给 `DispersionCalculator.calculate()`

2. **真实 `.sfc` 气象文件**
   - 仓库中完全不存在
   - 因此无法做“作者原始脚本同款输入路径”的真实复现

3. **与 surrogate 原脚本完全同结构的输入三件套**
   - `roads.shp`
   - `hourly_emission.csv`
   - `met_file.SFC`
   - `mode_inference.py` 明确写的是外部占位路径，说明这三件套没有被随仓库提供

### 6.3 如果要构造最小可运行真实测试数据集，建议如下

最小方案：

1. **道路数据**
   - 用 `test_data/test_20links.xlsx`
   - 解析 `geometry` WKT -> GeoDataFrame
   - 重命名 `link_id -> NAME_1`

2. **排放数据**
   - 用 `outputs/test_20links_emission_results_20260321_103041.xlsx`
   - 重命名：
     - `link_id -> NAME_1`
     - `NOx_kg_h -> nox`
   - 添加一列：
     - `data_time = "2024070112"` 或任意单步时间戳

3. **气象数据**
   - 直接使用 `urban_summer_day` 等预设
   - 或构造自定义 dict：
     - `wind_speed`
     - `wind_direction`
     - `stability_class`
     - `mixing_height`

这样就能在 **不伪造模型文件** 的前提下，用真实模型 + 真实道路 geometry + 半真实排放结果 跑通 calculator。

## 七、推荐的集成测试方案

### 方案 A：当前最推荐的真实链路测试

**目标**：尽量走真实主链，而不是手工拼 `emissions_df`

步骤：

1. 上传 `test_data/test_20links.xlsx`
2. 调用 `calculate_macro_emission`
3. 调用 `calculate_dispersion`
   - `meteorology = "urban_summer_day"`
   - `roughness_height = 0.5`
   - `pollutant = "NOx"`
4. 调用 `render_spatial_map`

优点：

- 不需要手工造 `data_time`
- 直接验证 `macro -> adapter -> dispersion -> renderer` 真正工具链
- 样本规模小，排错成本低

结论：**这是当前最可行、最真实、最推荐的集成测试路径。**

### 方案 B：中等规模真实联调

使用：

- `test_data/test_shanghai_full.xlsx`

用途：

- 验证 150 条路段规模下的真实模型推理和 concentration 渲染
- 兼顾真实性与运行代价

适合作为：

- API 联调
- Web 手工联调
- Phase 3 之前的稳定性回归样本

### 方案 C：全量压力测试

使用：

- `test_data/test_shanghai_allroads.xlsx`
  或
- `test_data/test_shanghai_allroads.zip`

用途：

- 25,370 路段的性能压力测试

风险：

- 扩散阶段可能非常重
- 前端 concentration 点图层可能很密集
- 不适合作为第一条真实测试路径

### 方案 D：calculator 级直接真实模型测试

如果不走工具链，而是直接测 `DispersionCalculator.calculate()`：

1. `roads_gdf`
   - 来源：`test_data/test_20links.xlsx` 或 `test_data/test_shanghai_allroads/test_shanghai_allroads.shp`
   - 需要重命名到 `NAME_1`

2. `emissions_df`
   - 来源：`outputs/test_20links_emission_results_20260321_103041.xlsx`
   - 需要重命名 `NOx_kg_h -> nox`
   - 需要补 `data_time`

3. `met_input`
   - 用 preset，不依赖 `.sfc`

结论：

- 这是当前最现实的 **真实模型 calculator 集成测试** 方案
- 但它不如方案 A 那样贴近产品真实调用链

## 八、最终结论

一句话总结：

> 当前仓库已经具备 **真实 surrogate 模型 + 真实道路数据 + 宏观排放输入/输出样本**，足以做真实扩散链路测试；真正缺的是 **标准化扩散排放时序文件** 和 **真实 `.sfc` 气象文件**。

因此：

- 如果目标是 **现在就跑真实集成测试**：可以，推荐走  
  `test_data/test_20links.xlsx -> calculate_macro_emission -> calculate_dispersion(preset met) -> render_spatial_map`
- 如果目标是 **完全复现 surrogate 原作者脚本输入**：当前不行，因为缺  
  `hourly_emission.csv` 和 `met_file.SFC`

## 附：本次核验到的关键事实

- 模型目录：`36` 个 JSON，`142M`
- `.sfc` 文件：`0`
- `outputs/*emission_results*.xlsx`：`181` 个
- 扫描候选 `xlsx/xls/csv` 后，包含 `NAME_1 + data_time + nox + length` 的文件：`0`
- surrogate 子目录无 `data/`、`input/`、`test/` 示例输入目录
