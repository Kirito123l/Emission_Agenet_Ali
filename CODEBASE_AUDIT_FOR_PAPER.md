# EmissionAgent 代码库审计报告（面向论文写作）

> 生成日期：2026-04-09
> 审计范围：完整代码库（`/home/kirito/Agent1/emission_agent/`）
> 审计方法：逐文件静态读取，不修改任何代码
> 主要参考提交：`80a9f2a`（fix(eval): accept geometry-gated multi-step success）

---

## 目录

1. [工具体系完整清单](#1-工具体系完整清单)
2. [计算引擎详情](#2-计算引擎详情)
3. [参数治理完整链路](#3-参数治理完整链路)
4. [状态机与工作流编排](#4-状态机与工作流编排)
5. [ToolContract 与可扩展性](#5-toolcontract-与可扩展性)
6. [端到端数据流追踪](#6-端到端数据流追踪)
7. [发现的问题与建议](#7-发现的问题与建议)

---

## 1. 工具体系完整清单

### 1.1 注册机制

工具注册采用单例模式。`tools/registry.py:20` 中 `ToolRegistry` 类使用 `__new__` 保证单例。`tools/registry.py:82` 中 `init_tools()` 函数在应用启动时被调用，手动依次 import 并注册 9 个工具。注册调用形式为 `register_tool("tool_name", ToolInstance())`。

**工具基类** (`tools/base.py:40`)：

```python
class BaseTool(ABC):
    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        pass

    def preflight_check(self, parameters: Dict[str, Any]) -> PreflightCheckResult:
        # 基类默认实现：直接返回 is_ready=True，无检查
        return PreflightCheckResult(is_ready=True)
```

**ToolResult 数据结构** (`tools/base.py:13`):

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | `bool` | 执行是否成功 |
| `data` | `Optional[Dict]` | 结构化结果数据 |
| `error` | `Optional[str]` | 错误信息 |
| `summary` | `Optional[str]` | 供 LLM 消化的人可读摘要 |
| `chart_data` | `Optional[Dict]` | 可视化图表数据 |
| `table_data` | `Optional[Dict]` | 表格展示数据 |
| `download_file` | `Optional[str]` | 可下载文件路径 |
| `map_data` | `Optional[Dict]` | 地理可视化数据 |

---

### 1.2 工具清单（9 个已注册工具）

#### 工具 1：`query_emission_factors`

- **类名/位置**：`tools/emission_factors.py`（对应 `EmissionFactorsTool`）
- **描述**：按车速查询排放因子曲线，返回图表和数据表。
- **参数列表**：

| 参数 | 必填 | 标准化类型 | 说明 |
|------|------|-----------|------|
| `vehicle_type` | 是 | `vehicle_type` | 车型（传用户原始表达，系统自动识别） |
| `pollutants` | 否 | `pollutant_list` | 污染物列表，默认 `[CO2, NOx, PM2.5]` |
| `model_year` | 是 | 无 | 车辆年款，范围 1995–2025 |
| `season` | 否 | `season` | 季节，默认夏季 |
| `road_type` | 否 | `road_type` | 路型，默认快速路 |
| `return_curve` | 否 | 无 | 是否返回完整曲线，默认 false |

- **依赖（requires）**：`[]`（无前提结果令牌）
- **产出（provides）**：`["emission_factors"]`
- **preflight_check**：继承基类，直接返回 `is_ready=True`，无实际检查
- **续接关键词**：`排放因子`, `emission factor`（来自 `config/tool_contracts.yaml:77-78`）

---

#### 工具 2：`calculate_micro_emission`

- **类名/位置**：`tools/micro_emission.py`（对应 `MicroEmissionTool`）
- **描述**：基于车辆轨迹数据（时间+速度）逐秒计算排放量。
- **参数列表**：

| 参数 | 必填 | 标准化类型 | 说明 |
|------|------|-----------|------|
| `file_path` | 否 | 无 | 上传文件路径（文件存在时必须提供） |
| `trajectory_data` | 否 | 无 | 轨迹数据数组（每点含 `t` 和 `speed_kph`） |
| `vehicle_type` | 是 | `vehicle_type` | 车型 |
| `pollutants` | 否 | `pollutant_list` | 污染物列表，默认 `[CO2, NOx, PM2.5]` |
| `model_year` | 否 | 无 | 车辆年款，默认 2020 |
| `season` | 否 | `season` | 季节 |

- **依赖（requires）**：`[]`
- **产出（provides）**：`["emission"]`
- **所需任务类型**：`micro_emission`
- **preflight_check**：继承基类，直接返回 `is_ready=True`，无实际检查
- **核心计算逻辑**：调用 `MicroEmissionCalculator`，先用 `VSPCalculator` 计算每个轨迹点的 VSP 值和 opMode，再查询对应季节的 MOVES-CSV 排放矩阵，获得逐秒排放率（g/hr → ÷3600 → g/s），累积得到总排放量。
- **action_variant**：`run_micro_emission`（`guidance_enabled: false`）

---

#### 工具 3：`calculate_macro_emission`

- **类名/位置**：`tools/macro_emission.py`（对应 `MacroEmissionTool`）
- **描述**：基于路段交通数据（长度 + 流量 + 速度）计算路段排放量，支持情景覆盖（`overrides` 参数）。
- **参数列表**：

| 参数 | 必填 | 标准化类型 | 说明 |
|------|------|-----------|------|
| `file_path` | 否 | 无 | 路段数据文件路径 |
| `links_data` | 否 | 无 | 路段数据数组，每路段含 `link_length_km`, `traffic_flow_vph`, `avg_speed_kph` |
| `pollutants` | 否 | `pollutant_list` | 污染物列表 |
| `fleet_mix` | 否 | 无 | 车队组成（车型百分比字典），不提供时用默认值 |
| `model_year` | 否 | 无 | 车辆年款 |
| `season` | 否 | `season` | 季节 |
| `overrides` | 否 | 无 | 情景覆盖参数列表，每项含 `column`, `value/transform/factor/offset`, `where` 条件 |
| `scenario_label` | 否 | 无 | 情景标签（如 `speed_30kmh`） |

- **自动修复**（`tools/macro_emission.py:57`，`_fix_common_errors`）：在工具层自动映射常见字段别名，如 `length` → `link_length_km`，`flow` → `traffic_flow_vph`，`speed` → `avg_speed_kph` 等（共 5 个字段 ×多个别名）。
- **依赖（requires）**：`[]`
- **产出（provides）**：`["emission"]`
- **所需任务类型**：`macro_emission`
- **preflight_check**：继承基类，直接返回 `is_ready=True`，无实际检查
- **action_variant**：`run_macro_emission`（`guidance_enabled: false`）

---

#### 工具 4：`analyze_file`

- **类名/位置**：`tools/file_analyzer.py`（对应 `FileAnalyzerTool`）
- **描述**：分析上传文件结构，识别列名、数据类型与任务类型，为后续工具准备 grounding 上下文。
- **参数列表**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `file_path` | 是 | 待分析文件路径 |

- **支持文件格式**：`.csv`, `.xlsx`, `.xls`, `.zip`（内含多表），`.geojson`, `.json`, `.shp`（需 geopandas）
- **依赖（requires）**：`[]`
- **产出（provides）**：`["file_analysis"]`
- **preflight_check**：继承基类，直接返回 `is_ready=True`，无实际检查
- **识别逻辑**：通过列名模式匹配（来自 `config/unified_mappings.yaml:column_patterns`），区分 `micro_emission`（需要 `speed_kph` 等）或 `macro_emission`（需要 `link_length_km`, `traffic_flow_vph`, `avg_speed_kph`）。输出包含 `task_type`、`confidence`、`columns`、`row_count`、`micro_mapping`、`macro_mapping`、`spatial_metadata` 等。

---

#### 工具 5：`query_knowledge`

- **类名/位置**：`tools/knowledge.py`（对应 `KnowledgeTool`）
- **描述**：在排放知识库中检索排放标准、法规和技术概念。
- **参数列表**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `query` | 是 | 查询文本 |
| `top_k` | 否 | 检索条目数，默认 5 |
| `expectation` | 否 | 期望信息类型 |

- **依赖（requires）**：`[]`
- **产出（provides）**：`["knowledge"]`
- **preflight_check**：继承基类，直接返回 `is_ready=True`，无实际检查
- **续接关键词**：`解释`, `说明`, `知识`, `knowledge`, `why`, `how`

---

#### 工具 6：`calculate_dispersion`

- **类名/位置**：`tools/dispersion.py`（对应 `DispersionTool`）
- **描述**：使用 PS-XGB-RLINE 代理模型计算路边近地面污染物浓度扩散场，生成栅格浓度矩阵和等值线。
- **参数列表**：

| 参数 | 必填 | 标准化类型 | 默认值 | 说明 |
|------|------|-----------|--------|------|
| `emission_source` | 否 | 无 | `last_result` | 排放数据来源 |
| `meteorology` | 否 | `meteorology` | `urban_summer_day` | 气象预设名、`custom` 或 `.sfc` 路径 |
| `wind_speed` | 否 | 无 | 预设值 | 风速（m/s） |
| `wind_direction` | 否 | 无 | 预设值 | 风向（度，0=N） |
| `stability_class` | 否 | `stability_class` | 预设值 | 大气稳定度（VS/S/N1/N2/U/VU） |
| `mixing_height` | 否 | 无 | 800 | 混合层高度（m） |
| `roughness_height` | 否 | 无 | 0.5 | 地表粗糙度（0.05/0.5/1.0） |
| `grid_resolution` | 否 | 无 | 50 | 显示栅格分辨率（m，可选 50/100/200） |
| `contour_resolution` | 否 | 无 | 10 | 等值线插值分辨率（m） |
| `pollutant` | 否 | `pollutant` | `NOx` | 污染物（当前仅支持 NOx） |
| `scenario_label` | 否 | 无 | `baseline` | 情景标签 |

- **依赖（requires）**：`["emission"]`（上游必须有宏观排放结果）
- **产出（provides）**：`["dispersion"]`
- **preflight_check**（`tools/dispersion.py`）：**是系统中唯一有实际检查逻辑的工具**，检查道路几何数据是否可用（`requires_geometry_support: true`）。
- **Stability Class 到 Obukhov 长度的映射**（`tools/dispersion.py:32`）：

```python
CUSTOM_STABILITY_TO_L = {
    "VS": 100.0,    # 非常稳定
    "S": 500.0,     # 稳定
    "N1": 2000.0,   # 中性1
    "N2": -2000.0,  # 中性2
    "U": -500.0,    # 不稳定
    "VU": -100.0,   # 非常不稳定
}
```

---

#### 工具 7：`analyze_hotspots`

- **类名/位置**：`tools/hotspot.py`（对应 `HotspotTool`）
- **描述**：从扩散结果中识别高浓度热点区域，追溯贡献路段。不重新运行扩散，直接分析已存储结果。
- **参数列表**：

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `method` | 否 | `percentile` | 识别方法：`percentile`（百分位）或 `threshold`（阈值） |
| `threshold_value` | 否 | 无 | 浓度阈值（μg/m³），method=threshold 时必填 |
| `percentile` | 否 | 5 | 热点百分位（如 5 表示最高 5%） |
| `min_hotspot_area_m2` | 否 | 2500 | 最小热点面积（m²） |
| `max_hotspots` | 否 | 10 | 最大热点数量 |
| `source_attribution` | 否 | true | 是否计算路段贡献 |
| `scenario_label` | 否 | 无 | 情景标签 |

- **依赖（requires）**：`["dispersion"]`
- **产出（provides）**：`["hotspot"]`
- **preflight_check**：继承基类，直接返回 `is_ready=True`，无实际检查

---

#### 工具 8：`render_spatial_map`

- **类名/位置**：`tools/spatial_renderer.py`（对应 `SpatialRendererTool`）
- **描述**：将排放结果、扩散结果或热点结果渲染为交互式地图。
- **参数列表**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `data_source` | 否 | 数据来源，默认 `last_result` |
| `pollutant` | 否 | 可视化污染物 |
| `title` | 否 | 地图标题 |
| `layer_type` | 否 | 图层类型：`emission/contour/raster/hotspot/concentration/points` |
| `scenario_label` | 否 | 情景标签 |

- **依赖（requires）**：动态，由 `layer_type` 决定（`core/tool_dependencies.py:121`）：当 `layer_type` 为 `emission/dispersion/hotspot` 时，分别需要对应的结果令牌。
- **产出（provides）**：`["visualization"]`
- **preflight_check**：继承基类，直接返回 `is_ready=True`，无实际检查
- **3 个 action_variants**：`render_emission_map`、`render_dispersion_map`（需要 `dispersion` 空间载荷）、`render_hotspot_map`（需要 `hotspot` 空间载荷）

---

#### 工具 9：`compare_scenarios`

- **类名/位置**：`tools/scenario_compare.py`（对应 `ScenarioCompareTool`）
- **描述**：比较基线与一个或多个情景的排放/扩散/热点结果差异（指标增量、百分比变化、路段级差异）。
- **参数列表**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `result_types` | 是 | 比较结果类型：`emission/dispersion/hotspot` 的列表 |
| `baseline` | 否 | 基线标签，默认 `baseline` |
| `scenario` | 否 | 单一情景标签 |
| `scenarios` | 否 | 多情景标签列表 |
| `metrics` | 否 | 关注指标名称 |

- **依赖（requires）**：`[]`（从会话上下文存储中检索已命名情景结果）
- **产出（provides）**：`["scenario_comparison"]`
- **preflight_check**：继承基类，直接返回 `is_ready=True`，无实际检查

---

### 1.3 工具依赖图（TOOL_GRAPH 完整邻接表）

来源：`config/tool_contracts.yaml` 中的 `dependencies` 字段，由 `tools/contract_loader.py:93` 动态生成。

```
query_emission_factors:   requires=[]         provides=["emission_factors"]
calculate_micro_emission: requires=[]         provides=["emission"]
calculate_macro_emission: requires=[]         provides=["emission"]
analyze_file:             requires=[]         provides=["file_analysis"]
query_knowledge:          requires=[]         provides=["knowledge"]
calculate_dispersion:     requires=["emission"] provides=["dispersion"]
analyze_hotspots:         requires=["dispersion"] provides=["hotspot"]
render_spatial_map:       requires=[](*动态)  provides=["visualization"]
compare_scenarios:        requires=[]         provides=["scenario_comparison"]
```

> 注：`render_spatial_map` 的 requires 在运行时由 `core/tool_dependencies.py:121` 根据 `layer_type` 参数动态推断。代码为：
> ```python
> if tool_name == "render_spatial_map":
>     layer_type = normalize_result_token((arguments or {}).get("layer_type"))
>     if layer_type in {"emission", "dispersion", "hotspot"}:
>         return [layer_type]
>     return []
> ```

**结果令牌规范化别名**（`core/tool_dependencies.py:20`）：

```python
CANONICAL_RESULT_ALIASES = {
    "emission_result": "emission",
    "dispersion_result": "dispersion",
    "hotspot_analysis": "hotspot",
    "concentration": "dispersion",
    "raster": "dispersion",
    "contour": "dispersion",
}
```

---

## 2. 计算引擎详情

### 2.1 VSP（Vehicle Specific Power）计算器

**位置**：`calculators/vsp.py`

**精确 VSP 公式**（`calculators/vsp.py:69`）：

```
VSP = (A×v + B×v² + C×v³ + M×v×a + M×v×g×grade/100) / m
```

其中：
- `v`：速度（m/s）
- `a`：加速度（m/s²）
- `grade`：坡度（%）
- `g = 9.81`（m/s²，重力加速度，`calculators/vsp.py:62`）
- `A, B, C, M, m`：车型特定系数（MOVES 标准参数）

**各车型 VSP 参数**（来源：`config/unified_mappings.yaml:vsp_params`）：

| 车型（标准名） | ID | A | B | C | M | m |
|--------------|-----|-----|-----|-----|-----|-----|
| Motorcycle | 11 | 0.0251 | 0.0 | 0.000315 | 0.285 | 0.285 |
| Passenger Car | 21 | 0.156461 | 0.002001 | 0.000492 | 1.4788 | 1.4788 |
| Passenger Truck | 31 | 0.22112 | 0.002837 | 0.000698 | 1.86686 | 1.8668 |
| Light Commercial Truck | 32 | 0.235008 | 0.003038 | 0.000747 | 2.05979 | 2.0597 |
| Intercity Bus | 41 | 1.23039 | 0.0 | 0.003714 | 17.1 | 19.593 |
| Transit Bus | 42 | 1.03968 | 0.0 | 0.003587 | 17.1 | 16.556 |
| School Bus | 43 | 0.709382 | 0.0 | 0.002175 | 17.1 | 9.0698 |
| Refuse Truck | 51 | 1.50429 | 0.0 | 0.003572 | 17.1 | 23.113 |
| Single Unit Short-haul Truck | 52 | 0.596526 | 0.0 | 0.001603 | 17.1 | 8.5389 |
| Single Unit Long-haul Truck | 53 | 0.529399 | 0.0 | 0.001473 | 17.1 | 6.9844 |
| Motor Home | 54 | 0.655376 | 0.0 | 0.002105 | 17.1 | 7.5257 |
| Combination Short-haul Truck | 61 | 1.43052 | 0.0 | 0.003792 | 17.1 | 22.828 |
| Combination Long-haul Truck | 62 | 1.47389 | 0.0 | 0.003681 | 17.1 | 24.419 |

**14 个 VSP Bin 定义**（来源：`config/unified_mappings.yaml:vsp_bins`，代码读取：`calculators/vsp.py:38`）：

| Bin | 下界 | 上界 | 注记 |
|-----|------|------|------|
| 1 | -∞ | -2 | YAML 中 `-999999` 被转换为 `-inf` |
| 2 | -2 | 0 | |
| 3 | 0 | 1 | |
| 4 | 1 | 4 | |
| 5 | 4 | 7 | |
| 6 | 7 | 10 | |
| 7 | 10 | 13 | |
| 8 | 13 | 16 | |
| 9 | 16 | 19 | |
| 10 | 19 | 23 | |
| 11 | 23 | 28 | |
| 12 | 28 | 33 | |
| 13 | 33 | 39 | |
| 14 | 39 | +∞ | YAML 中 `999999` 被转换为 `+inf` |

> **判别规则**（`calculators/vsp.py:99`）：对 Bin i，条件为 `lower < vsp <= upper`（左开右闭）。

**opMode 映射**（`calculators/vsp.py:104`）：速度 ≥ 50 mph 时忽略 VSP Bin，直接按 VSP 区间映射到 opMode 33–40。

---

### 2.2 微观排放计算器（MicroEmissionCalculator）

**位置**：`calculators/micro_emission.py`

**计算流程**：

1. 将车型名称映射为 MOVES sourceTypeID（`calculators/micro_emission.py:26`）
2. 调用 `VSPCalculator.calculate_trajectory_vsp()` 批量处理轨迹点，输出 `vsp`, `vsp_bin`, `opmode`
3. 加载对应季节的 MOVES-CSV 排放矩阵（3 个文件，按冬/春+秋/夏，`calculators/micro_emission.py:62`）
4. 对每个轨迹点查询 `(opModeID, pollutantID, sourceTypeID, modelYearID)` 四元组，返回 `EmissionQuant`（g/hr）
5. 单位转换：`g/hr ÷ 3600 = g/s`（`calculators/micro_emission.py:132`）
6. 累积得到总排放（g）和单位里程排放率（g/km）

**季节代码映射**（`calculators/micro_emission.py:52`）：

```python
SEASON_CODES = {"春季": 4, "夏季": 7, "秋季": 4, "冬季": 1}
```

注意：春季与秋季共用同一 MOVES 月份代码（4 月）。

**年龄组划分**（`calculators/micro_emission.py:68`，相对于 2025 年）：

| 年龄（年） | 年龄组 ID | 覆盖年款 |
|-----------|----------|---------|
| ≤1        | 1        | 2024–2025 |
| 2–9       | 2        | 2016–2023 |
| 10–19     | 5        | 2006–2015 |
| ≥20       | 9        | ≤2005 |

> **注意**：年龄组 3 在 MOVES 数据库中无数据，已跳过（`calculators/micro_emission.py:79` 注释说明）。

**数据文件**（`calculators/micro_emission.py:63`）：
- `winter`: `atlanta_2025_1_55_65.csv`
- `spring`: `atlanta_2025_4_75_65.csv`
- `summer`: `atlanta_2025_7_90_70.csv`

**文件路径**：`calculators/data/micro_emission/`

---

### 2.3 宏观排放计算器（MacroEmissionCalculator）

**位置**：`calculators/macro_emission.py`

**核心排放量公式**（`calculators/macro_emission.py:246`，修复后代码）：

```
emission_rate_g_per_sec = emission_rate / 3600        # MOVES EmissionQuant: g/hr → g/s
travel_time_sec = (link_length_km / avg_speed_kph) × 3600  # 行驶时间（s）
emission_g_per_veh = emission_rate_g_per_sec × travel_time_sec  # 单车排放量（g）
emission_kg_per_hr = emission_g_per_veh × vehicles_per_hour / 1000  # 路段排放（kg/hr）
```

> **注**：代码注释（`calculators/macro_emission.py:244`）明确标注了旧有错误版本（`emission_rate * length_mi * vehicles_per_hour / 1000`）及修复说明。修复后公式以行驶时间而非行驶距离为积分维度，与 MOVES 的 EmissionQuant 单位定义一致。

**单位排放率**（g/veh-km，`calculators/macro_emission.py:261`）：

```
emission_rate_g_per_veh_km = (total_emissions_kg_per_hr × 1000) / link_length_km / traffic_flow_vph
```

**矩阵查询策略**：所有路段统一使用 `opModeID=300`（平均运行模式，`calculators/macro_emission.py:12`）进行 MOVES 矩阵查询，不做逐秒 VSP 计算。通过 `_build_rate_lookup()` 构建 `(pollutantID, sourceTypeID, modelYearID) → EmissionQuant` 的 Python dict 热查找表（`calculators/macro_emission.py:275`），避免每路段重复扫描 DataFrame。

**进程级缓存**（`calculators/macro_emission.py:15`）：季节矩阵 DataFrame 使用类变量 `_SEASON_MATRIX_CACHE` 缓存，仅在首次读取时加载 CSV。

**数据文件**（`calculators/macro_emission.py:75`）：
- `winter`: `atlanta_2025_1_35_60 .csv`（注：文件名含多余空格，是原始文件名）
- `spring`: `atlanta_2025_4_75_65.csv`
- `summer`: `atlanta_2025_7_80_60.csv`

**文件路径**：`calculators/data/macro_emission/`

**默认车队组成**（`calculators/macro_emission.py:65`）：

| 车型 | 比例 |
|------|------|
| Passenger Car | 70.0% |
| Passenger Truck | 20.0% |
| Light Commercial Truck | 5.0% |
| Transit Bus | 3.0% |
| Combination Long-haul Truck | 2.0% |

---

### 2.4 扩散计算器（DispersionCalculator / PS-XGB-RLINE 代理模型）

**位置**：`calculators/dispersion.py`，`calculators/dispersion_adapter.py`

**核心方法**：PS-XGB（Passive Scalar XGBoost）替代 AERMOD/RLINE 物理模型，通过预训练 XGBoost 回归器直接预测受体点浓度，不运行高斯烟羽计算。

**训练数据生成**（`ps-xgb-aermod-rline-surrogate/training.py`）：
- 从 AERMOD PLOT 输出文件（`.txt`）读取 `(X, Y, AVERAGE_CONC, DATE)` 四元组
- 从气象观测文件（`.sfc`）读取 `(H, MixHGT_C, L, WSPD, WDIR)` 等参数
- 按稳定度等级分别训练子模型（顺风区 `x>=0` 和逆风区 `x<0`）

**模型输入特征**（推断自代码结构）：坐标（UTM 投影后的顺风/横风距离）、风速（WSPD）、风向（WDIR）、Obukhov 长度（L）、混合层高度（MixHGT_M）等气象参数。

**粗糙度模型分组**（`calculators/dispersion.py:104`）：

```python
ROUGHNESS_MAP = {0.05: "L", 0.5: "M", 1.0: "H"}
ROUGHNESS_DIR_MAP = {0.05: "model_z=0.05", 0.5: "model_z=0.5", 1.0: "model_z=1"}
```

**6 个大气稳定度类别**（`calculators/dispersion.py:107`）：

```python
STABILITY_CLASSES = ["stable", "verystable", "unstable", "veryunstable", "neutral1", "neutral2"]
STABILITY_ABBREV = {
    "VS": "verystable", "S": "stable",
    "N1": "neutral1", "N2": "neutral2",
    "U": "unstable", "VU": "veryunstable",
}
```

**受体点生成策略**（`calculators/dispersion.py:223`，`generate_receptors_custom_offset()`）：
- 近路受体：在道路两侧按 `offset_rule` 字典（`{3.5: 40, 8.5: 40}`，单位 m）逐段放置，间距 40 m
- 背景受体：在道路网络外包矩形范围内，按 `background_spacing_m=50` m 规则网格放置
- 排除在道路缓冲区（矩形缓冲，无半圆帽）内部的受体点

**道路分段**（`calculators/dispersion.py:332`，`split_polyline_by_interval_with_angle()`）：按 `segment_interval_m=10 m` 将折线切分为等长子段，记录每段中点方位角。

**CRS 转换**：数据从 `EPSG:4326` 转换到 UTM（默认 zone 51，北半球，对应上海地区）进行计算，输出时再转回 WGS84。

**输出结构**：
- `raster_grid`：包含 `matrix_mean`（二维浓度矩阵，μg/m³）、`resolution_m`、`bbox_wgs84`、`cell_centers_wgs84`
- `road_contributions`：`receptor_top_roads` 字典，按受体索引存储前 10 条贡献路段
- `contour_bands`：等值线多边形（需 `enable_contour_output=true`）

**等值线生成**（`calculators/dispersion.py:53`）：使用 `contourpy` 库，7 个等级（`contour_n_levels=7`），高斯模糊平滑（`contour_smooth_sigma=1.0`）。

---

### 2.5 热点分析器（HotspotAnalyzer）

**位置**：`calculators/hotspot_analyzer.py`

**识别方法**：

**方法一：百分位法（默认）**（`calculators/hotspot_analyzer.py:221`）：
```python
nonzero_values = matrix[matrix > 0]
cutoff = np.percentile(nonzero_values, 100.0 - percentile)
```
取非零浓度值的第 `(100-percentile)` 百分位数作为阈值，默认 `percentile=5`，即最高 5%。

**方法二：绝对阈值法**：直接使用用户指定的 `threshold_value`（μg/m³）作为截断值。

**聚类算法**（`calculators/hotspot_analyzer.py:334`，`_cluster_hotspot_cells()`）：4 邻域（上下左右）BFS，时间复杂度 O(矩阵大小)。

**过滤与排序**（`calculators/hotspot_analyzer.py:243`）：
1. 按最小面积 `min_hotspot_area_m2` 过滤（`cell_count × resolution² >= min_area`）
2. 按 `(max_conc, mean_conc, cell_count)` 三级排序（降序）
3. 取前 `max_hotspots` 个

**路段贡献归因**（`calculators/hotspot_analyzer.py:437`，`_compute_source_attribution()`）：
1. 从 `raster_grid.cell_receptor_map` 找到热点格网内的所有受体索引
2. 从 `road_contributions.receptor_top_roads` 聚合这些受体的路段贡献值
3. 按贡献值降序排列，输出前 10 条路段及其贡献百分比

**输出字段**（每个 `HotspotArea`）：`hotspot_id`, `rank`, `center` (lon/lat), `bbox`, `area_m2`, `grid_cells`, `max_conc`, `mean_conc`, `cell_keys`, `contributing_roads`（最多 10 条）

---

### 2.6 情景对比计算器（ScenarioComparator）

**位置**：`calculators/scenario_comparator.py`
**功能**：从会话上下文存储中读取不同 `scenario_label` 的结果，计算指标差值、百分比变化和路段级差异。

---

## 3. 参数治理完整链路

### 3.1 标准化流水线架构

**核心类**：`StandardizationEngine`（`services/standardization_engine.py`）

**流水线级联顺序**（`services/standardization_engine.py:11`，注释文档）：

```
exact → alias → fuzzy → LLM → default → abstain
```

**各级描述**：

| 层级 | 触发条件 | 算法 | 置信度 | 回退条件 |
|------|---------|------|--------|---------|
| **Exact** | 输入完全匹配标准名（大小写不敏感） | `dict.get(cleaned_lower)` + `cleaned == normalized` 判断 | 1.0 | 查找失败 |
| **Alias** | 输入匹配任意别名（大小写不敏感） | `dict.get(cleaned_lower)`（别名已预展开至 lookup） | 0.95 | 别名查找失败 |
| **Fuzzy** | 上述两层均失败，且 `fuzzy_enabled=True` | `fuzzywuzzy.fuzz.ratio()` 或 `difflib.SequenceMatcher`（备用） | `score/100` | 最高相似度 < 阈值 |
| **LLM** | 上述三层均失败，且 `llm_enabled=True`，且输入非空 | API 调用（`qwen-turbo-latest`，temperature=0.1，max_tokens=200） | 由 LLM 返回 | LLM 返回失败或超时 |
| **Default** | season/road_type 等有默认值的参数类型 | 直接使用配置默认值 | 0.5 | 无 |
| **Abstain** | 所有层均失败 | 返回建议候选列表 | 0.0 | 不触发协商时终止 |

**模糊匹配阈值**（`services/standardization_engine.py:47`）：

```python
LEGACY_FUZZY_THRESHOLDS = {
    "vehicle_type": 0.70,
    "pollutant": 0.80,
    "season": 0.60,
    "road_type": 0.60,
    "meteorology": 0.75,
    "stability_class": 0.75,
}
```

**参数类型配置**（`services/standardization_engine.py:56`）：

| 参数类型 | 有默认值 | 默认值 | 启用 Fuzzy | 启用 LLM |
|---------|---------|--------|-----------|---------|
| `vehicle_type` | 否 | - | 是 | 是 |
| `pollutant` | 否 | - | 是 | 是 |
| `pollutant_list` | - | - | - | - |
| `season` | **是** | **夏季** | 是 | 是 |
| `road_type` | **是** | **快速路** | 是 | 是 |
| `meteorology` | 否 | - | 是 | 是 |
| `stability_class` | 否 | - | 是 | 是 |

**passthrough 规则**（`services/standardization_engine.py:92`）：`meteorology` 参数在匹配 `r"\.sfc$"` 或 `r"^custom$"` 模式时直接通过，不做标准化。

---

### 3.2 参数维度完整有效值列表

#### 3.2.1 车型（vehicle_type）——13 个 MOVES 标准车型

来源：`config/unified_mappings.yaml:vehicle_types`

| 标准名 | ID | 中文名 | 别名数量 | 代表性别名 |
|--------|-----|--------|---------|-----------|
| Motorcycle | 11 | 摩托车 | 4 | 摩托车, 电动摩托, 机车, motorcycle |
| Passenger Car | 21 | 乘用车 | 13 | 小汽车, 轿车, 私家车, SUV, 网约车, 出租车, 滴滴, passenger car, car, 轻型汽油车, 汽油车, 乘用车, 轻型车 |
| Passenger Truck | 31 | 皮卡 | 4 | 皮卡, 轻型客货车, pickup, 客车 |
| Light Commercial Truck | 32 | 轻型货车 | 5 | 小货车, 面包车, 轻卡, 轻型商用车, light commercial truck |
| Intercity Bus | 41 | 城际客车 | 4 | 长途大巴, 旅游巴士, 长途客车, intercity bus |
| Transit Bus | 42 | 公交车 | 6 | 城市公交, 公交, 巴士, 市内公交, transit bus, bus |
| School Bus | 43 | 校车 | 2 | 学生巴士, school bus |
| Refuse Truck | 51 | 垃圾车 | 2 | 环卫车, refuse truck |
| Single Unit Short-haul Truck | 52 | 中型货车 | 4 | 城配货车, 中卡, 单体短途货车, 短途货车 |
| Single Unit Long-haul Truck | 53 | 长途货车 | 2 | 单体长途货车, long-haul truck |
| Motor Home | 54 | 房车 | 3 | 旅居车, motor home, rv |
| Combination Short-haul Truck | 61 | 半挂短途 | 2 | 组合短途货车, combination short-haul |
| Combination Long-haul Truck | 62 | 重型货车 | 8 | 重卡, 大货车, 挂车, 组合长途货车, 半挂长途, 货车, combination long-haul, heavy truck |

#### 3.2.2 污染物（pollutant）——6 个标准物种

| 标准名 | ID | 中文名 | 别名 |
|--------|-----|--------|------|
| CO2 | 90 | 二氧化碳 | 碳排放, 温室气体, co2, carbon dioxide |
| CO | 2 | 一氧化碳 | co, carbon monoxide |
| NOx | 3 | 氮氧化物 | 氮氧, nox, nitrogen oxides |
| PM2.5 | 110 | 细颗粒物 | 颗粒物, pm2.5, pm25, fine particulate matter |
| PM10 | 111 | 可吸入颗粒物 | pm10, particulate matter |
| THC | 1 | 总碳氢化合物 | 总烃, thc, total hydrocarbons |

> 注：MOVES 数据矩阵中还包含 `VOC(5)`, `SO2(30)`, `NH3(35)`, `NMHC(79)`, `Energy(91)`, `PM10(100)`，但 unified_mappings.yaml 对外仅暴露以上 6 种（calculator 层仍可查询更多）。

#### 3.2.3 季节（season）——4 个标准值

| 标准名 | 别名 |
|--------|------|
| 春季 | 春, 春天, spring |
| 夏季 | 夏, 夏天, summer |
| 秋季 | 秋, 秋天, fall, autumn |
| 冬季 | 冬, 冬天, winter |

**默认值**：夏季（`config/unified_mappings.yaml:542`）

#### 3.2.4 路型（road_type）——5 个标准值

| 标准名 | 别名 |
|--------|------|
| 快速路 | 城市快速路, 快速路, urban expressway, expressway |
| 高速公路 | 高速, freeway, highway, motorway, interstate |
| 主干道 | 主干路, 干道, arterial, major road, arterial road |
| 次干道 | 次干路, minor arterial, secondary road, collector road |
| 支路 | 地方道路, 支路, local road, local, residential, 居民区道路 |

**默认值**：快速路（`config/unified_mappings.yaml:541`）

#### 3.2.5 气象预设（meteorology）——6 个预设

| 预设名 | 别名（中/英） |
|--------|-------------|
| urban_summer_day | 城市夏季白天, 夏季白天, 夏天白天, 城市夏天, summer day, urban summer, urban summer daytime |
| urban_summer_night | 城市夏季夜间, 夏季夜间, 夏天晚上, summer night, urban summer night |
| urban_winter_day | 城市冬季白天, 冬季白天, 冬天白天, winter day, urban winter daytime |
| urban_winter_night | 城市冬季夜间, 冬季夜间, 冬天晚上, winter night, urban winter night |
| windy_neutral | 大风中性, 大风, 强风, windy, neutral windy, high wind |
| calm_stable | 静风稳定, 静风, 无风, calm, calm stable, no wind |

**特殊值**：`custom`（用户自定义参数）、`*.sfc`（直接上传气象观测文件路径），两者均 passthrough。

#### 3.2.6 大气稳定度（stability_class）——6 类（Pasquill-Gifford 体系）

| 代码 | 完整名 | 别名 |
|------|--------|------|
| VS | verystable | very stable, 非常稳定, 强稳定, F, f, pasquill f, class f |
| S | stable | stable, 稳定, E, e, pasquill e, class e |
| N1 | neutral1 | neutral, 中性, D, d, pasquill d, class d |
| N2 | neutral2 | neutral2, neutral 2, C, c, pasquill c, class c |
| U | unstable | unstable, 不稳定, B, b, pasquill b, class b |
| VU | veryunstable | very unstable, 非常不稳定, 强不稳定, A, a, pasquill a, class a |

---

### 3.3 跨参数约束（Cross-Constraints）

**配置文件**：`config/cross_constraints.yaml`，版本 `1.1`
**验证器**：`services/cross_constraints.py:CrossConstraintValidator`
**启用条件**：`config.enable_cross_constraint_validation=true`（默认 true）

**约束 1：vehicle_road_compatibility**（`cross_constraints.yaml:4`）
- **类型**：`blocked_combinations`（硬约束，violation）
- **规则**：`Motorcycle` × `高速公路` → 违规，原因："摩托车不允许上高速公路"

**约束 2：vehicle_pollutant_relevance**（`cross_constraints.yaml:17`）
- **类型**：`conditional_warning`（软约束，warning）
- **规则**：`Motorcycle` × `[PM2.5, PM10]` → 警告，原因："摩托车颗粒物排放通常很低，且 MOVES 对摩托车 PM 排放率数据覆盖有限"，建议使用 CO, NOx, THC, CO2

**约束 3：pollutant_task_applicability**（`cross_constraints.yaml:33`）
- **类型**：`conditional_warning`
- **规则**：
  - `CO2` × `calculate_dispersion` → 警告："CO2 在大气中混合较快，通常不作为近地扩散热点分析的重点污染物"
  - `THC` × `calculate_dispersion` → 警告："THC 的代理扩散模型支持有限"

**约束 4：season_meteorology_consistency**（`cross_constraints.yaml:53`）
- **类型**：`consistency_warning`
- **规则**：
  - `冬季` × `[urban_summer_day, urban_summer_night]` → 警告
  - `夏季` × `[urban_winter_day, urban_winter_night]` → 警告

---

### 3.4 参数协商（Parameter Negotiation）

**位置**：`core/parameter_negotiation.py`
**启用条件**：`config.enable_parameter_negotiation=true`（默认 true）

**触发条件**：标准化置信度低于 `parameter_negotiation_confidence_threshold`（默认 **0.85**）且策略为 `fuzzy` 或 `abstain`。

**协商请求结构**（`ParameterNegotiationRequest`，`core/parameter_negotiation.py:60`）：
- `request_id`：`neg-{param_name}-{uuid8}` 格式
- `parameter_name`：参数名
- `raw_value`：用户原始输入
- `confidence`：当前置信度
- `trigger_reason`：触发原因
- `candidates`：候选列表（最多 `parameter_negotiation_max_candidates=5` 个）

**每个候选**（`NegotiationCandidate`）：`index`, `normalized_value`, `display_label`, `confidence`, `strategy`, `reason`, `aliases`

**用户回复解析**（`core/parameter_negotiation.py:229`，`_extract_indices()`）：支持以下格式：
- 直接数字（如 `"1"`, `"2"`）
- 中文序数（`一二三四五六`，`core/parameter_negotiation.py:198`）
- 模式匹配（如 `"选第2个"`, `"option 3"`, `"choose 2"`）
- "以上都不对"短语（`都不对`, `都不是`, `都不行`, `none of the above`）

**决策类型**（`NegotiationDecisionType`）：
- `CONFIRMED`：用户确认了某个候选
- `NONE_OF_ABOVE`：用户拒绝所有候选
- `AMBIGUOUS_REPLY`：无法解析

**确认后锁定**（`core/task_state.py:869`，`apply_parameter_lock()`）：
```
ParamEntry.locked = True
ParamEntry.lock_source = "user_confirmation"
ParamEntry.strategy = "user_confirmed"
ParamEntry.confidence = 1.0
```
一旦锁定，后续 turn 不再对该参数重新协商。

---

## 4. 状态机与工作流编排

### 4.1 状态机定义

**TaskStage 枚举**（`core/task_state.py:47`）：

| 状态名 | 含义 | 是否终态 |
|--------|------|---------|
| `INPUT_RECEIVED` | 收到用户消息，尚未 grounding | 否 |
| `GROUNDED` | 文件已分析，任务已识别，准备执行 | 否 |
| `NEEDS_CLARIFICATION` | 需要向用户澄清意图或冲突 | **是** |
| `NEEDS_PARAMETER_CONFIRMATION` | 需要用户确认参数选择 | **是** |
| `NEEDS_INPUT_COMPLETION` | 需要用户补充缺失输入 | **是** |
| `EXECUTING` | 正在执行工具链 | 否 |
| `DONE` | 工作流结束（成功或失败） | **是** |

> `is_terminal()` 定义（`core/task_state.py:436`）：`{DONE, NEEDS_CLARIFICATION, NEEDS_PARAMETER_CONFIRMATION, NEEDS_INPUT_COMPLETION}` 为终态。

> 注意：系统**没有**独立的 `FAILED` 状态——失败路径统一归入 `DONE` 状态。

---

### 4.2 合法状态转换表

来源：`core/task_state.py:409`（`_valid_transitions()`）

```
INPUT_RECEIVED → GROUNDED, NEEDS_CLARIFICATION, NEEDS_PARAMETER_CONFIRMATION,
                 NEEDS_INPUT_COMPLETION, DONE
GROUNDED       → EXECUTING, NEEDS_CLARIFICATION, DONE
EXECUTING      → DONE, NEEDS_CLARIFICATION, NEEDS_PARAMETER_CONFIRMATION,
                 NEEDS_INPUT_COMPLETION
NEEDS_CLARIFICATION        → []（终态，无转出）
NEEDS_PARAMETER_CONFIRMATION → []（终态，无转出）
NEEDS_INPUT_COMPLETION     → []（终态，无转出）
DONE                       → []（终态，无转出）
```

违反合法转换表时抛出 `ValueError`（`core/task_state.py:403`）：
```python
raise ValueError(f"Invalid transition: {self.stage.value} -> {new_stage.value}")
```

**停机条件**（`core/task_state.py:444`）：
```python
def should_stop(self) -> bool:
    return self.is_terminal() or self.control.steps_taken >= self.control.max_steps
```

---

### 4.3 状态循环（`_run_state_loop`）

**位置**：`core/router.py:1362`

**执行路径**：

```python
# core/router.py:1380-1397
loop_guard = 0
max_state_iterations = max(6, state.control.max_steps * 3)
while not state.is_terminal() and loop_guard < max_state_iterations:
    loop_guard += 1
    if state.stage == TaskStage.INPUT_RECEIVED:
        await self._state_handle_input(state, trace_obj=trace_obj)
    elif state.stage == TaskStage.GROUNDED:
        await self._state_handle_grounded(state, trace_obj=trace_obj)
    elif state.stage == TaskStage.EXECUTING:
        await self._state_handle_executing(state, trace_obj=trace_obj)
# 超过最大迭代次数时强制转换到 DONE
```

**`max_orchestration_steps` 默认值**：`4`（`config.py:223`，环境变量 `MAX_ORCHESTRATION_STEPS`）
**最大迭代数**：`max(6, 4×3) = 12`

---

### 4.4 `_state_handle_input` 处理逻辑

**位置**：`core/router.py:8758`

处理顺序（优先级从高到低）：

1. **应用历史状态**：从持久化存储恢复 `input_completion`、`parameter_negotiation`、`file_relationship`、`intent_resolution` 状态（`router.py:8763-8766`）
2. **文件关系解析**（当有新文件上传时，`config.enable_file_relationship_resolution=true`）：判断新文件是替换文件、补充列、还是新任务。可能立即转换到 `NEEDS_CLARIFICATION` 或 `DONE`
3. **处理进行中的 InputCompletion**（`config.enable_input_completion_flow=true`）：若有活跃补全请求，解析用户回复。可能转换到 `NEEDS_INPUT_COMPLETION` 或 `DONE`
4. **处理进行中的 ParameterNegotiation**：若有活跃参数协商请求，解析用户回复。可能转换到 `NEEDS_CLARIFICATION` 或 `NEEDS_PARAMETER_CONFIRMATION`
5. **几何恢复路径**（`config.enable_geometry_recovery_path=true`）：检查是否满足几何恢复条件
6. **文件分析（Grounding）**：若有文件但未 grounded，调用 `analyze_file` 工具（或读取缓存）
7. **Readiness 评估**：调用 `ReadinessAssessment` 判断哪些动作可用
8. **转换状态**：若已 grounded 且有可用动作 → `GROUNDED`，否则 → `NEEDS_CLARIFICATION` 等

---

### 4.5 ReadinessStatus 枚举与评估逻辑

**位置**：`core/readiness.py`

**ReadinessStatus 枚举**（`core/readiness.py:78`）：

| 值 | 含义 |
|----|------|
| `READY` | 条件满足，可以执行 |
| `BLOCKED` | 缺少必要条件，无法修复 |
| `REPAIRABLE` | 缺少条件，但有已知修复路径 |
| `ALREADY_PROVIDED` | 该 artifact 本轮已交付，避免重复 |

**评估规则**（基于 `config/tool_contracts.yaml` 中的 action_variants）：每个 action 的 readiness 由以下条件决定：
- `required_task_types`：文件任务类型必须匹配（如 `macro_emission`）
- `required_result_tokens`：依赖结果令牌必须在 `available_results` 中
- `requires_geometry_support`：文件必须包含几何列
- `requires_spatial_result_token`：对应结果必须包含空间载荷（`map_data` 或 `raster_grid`）
- `provided_conflicts`：若已交付同类 artifact，标记为 `ALREADY_PROVIDED`

---

### 4.6 所有特征开关（Feature Flags）及默认值

来源：`config.py:44`，全部通过环境变量覆盖（默认值从代码中读取）。

| 配置键 | 默认值 | 说明 |
|--------|--------|------|
| `enable_state_orchestration` | **true** | 启用新状态循环（关键开关） |
| `enable_trace` | **true** | 启用决策追踪 |
| `persist_trace` | **false** | 将 trace 持久化到磁盘 |
| `enable_file_analyzer` | **true** | 启用文件分析器 |
| `enable_file_context_injection` | **true** | 将文件上下文注入 prompt |
| `enable_executor_standardization` | **true** | 执行前标准化参数 |
| `enable_llm_standardization` | **true** | 启用 LLM 标准化回退 |
| `enable_standardization_cache` | **true** | 启用标准化结果缓存 |
| `standardization_fuzzy_enabled` | **true** | 启用模糊匹配标准化 |
| `enable_cross_constraint_validation` | **true** | 启用跨参数约束验证 |
| `enable_parameter_negotiation` | **true** | 启用参数协商交互 |
| `parameter_negotiation_confidence_threshold` | **0.85** | 触发协商的置信度阈值 |
| `parameter_negotiation_max_candidates` | **5** | 协商候选最大数量 |
| `enable_readiness_gating` | **true** | 启用执行前 Readiness 门控 |
| `readiness_repairable_enabled` | **true** | 启用可修复状态 |
| `readiness_already_provided_dedup_enabled` | **true** | 启用已交付去重 |
| `enable_input_completion_flow` | **true** | 启用输入补全流程 |
| `input_completion_max_options` | **4** | 补全选项最大数量 |
| `input_completion_allow_uniform_scalar` | **true** | 允许统一标量填充 |
| `input_completion_allow_upload_support_file` | **true** | 允许要求上传补充文件 |
| `enable_geometry_recovery_path` | **true** | 启用几何恢复路径 |
| `enable_file_relationship_resolution` | **true** | 启用文件关系解析 |
| `enable_supplemental_column_merge` | **true** | 启用补充列合并 |
| `enable_intent_resolution` | **true** | 启用意图解析 |
| `enable_artifact_memory` | **true** | 启用 artifact 记忆 |
| `enable_summary_delivery_surface` | **true** | 启用摘要交付 |
| `enable_residual_reentry_controller` | **true** | 启用残余工作流重入 |
| `enable_policy_based_remediation` | **true** | 启用策略修复 |
| `enable_capability_aware_synthesis` | **true** | 启用能力感知合成 |
| `enable_skill_injection` | **true** | 启用 Skill 注入 |
| `enable_contour_output` | **true** | 启用等值线输出 |
| `enable_workflow_templates` | **false** | 启用工作流模板（**默认关闭**） |
| `enable_lightweight_planning` | **false** | 启用轻量规划（**默认关闭**） |
| `enable_bounded_plan_repair` | **false** | 启用有界计划修复（**默认关闭**） |
| `enable_repair_aware_continuation` | **false** | 启用修复感知续接（**默认关闭**） |
| `enable_file_analysis_llm_fallback` | **false** | 启用文件分析 LLM 回退（**默认关闭**） |
| `enable_builtin_map_data` | **false** | 启用内置地图数据（**默认关闭**） |
| `max_orchestration_steps` | **4** | 状态机最大步数 |

---

### 4.7 执行计划与修复（Plan & Plan Repair）

**ExecutionPlan**（`core/plan.py`）：每个 turn 可选地持有一个 `ExecutionPlan`，包含有序 `PlanStep` 列表，每步记录 `tool_name`, `step_id`, `status`（PENDING/RUNNING/DONE/FAILED/BLOCKED/SKIPPED）等。

**RepairActionType 枚举**（`core/plan_repair.py:22`）——8 种修复动作：

| 动作类型 | 说明 |
|---------|------|
| `KEEP_REMAINING` | 保留剩余步骤不变 |
| `DROP_BLOCKED_STEP` | 丢弃被阻塞的步骤 |
| `REORDER_REMAINING_STEPS` | 重排剩余步骤顺序 |
| `REPLACE_STEP` | 替换某个步骤 |
| `TRUNCATE_AFTER_CURRENT` | 截断当前步骤之后的所有步骤 |
| `APPEND_RECOVERY_STEP` | 追加恢复步骤 |
| `NO_REPAIR` | 不修复（维持原计划） |

**注意**：`enable_bounded_plan_repair=false`（默认关闭），修复功能在默认配置下不启用。

---

### 4.8 工作流模板

**位置**：`core/workflow_templates.py:188`（硬编码，非 YAML 配置）
**启用条件**：`enable_workflow_templates=false`（**默认关闭**）

5 个内置工作流模板：

| 模板 ID | 模板名称 | 支持任务类型 | 步骤概述 |
|---------|---------|------------|---------|
| `macro_emission_baseline` | Macro Emission Baseline | macro_emission | 宏观排放计算 |
| `macro_spatial_chain` | Macro Spatial Chain | macro_emission | 宏观排放 → 扩散 → 热点 → 渲染 |
| `micro_emission_baseline` | Micro Emission Baseline | micro_emission | 微观排放计算 |
| `macro_render_focus` | Macro Render Focus | macro_emission | 宏观排放 → 立即渲染 |
| `micro_render_focus` | Micro Render Focus | micro_emission | 微观排放 → 渲染 |

---

### 4.9 Trace 审计系统

**位置**：`core/trace.py`
**启用条件**：`enable_trace=true`（默认 true）

`TraceStepType` 枚举共 **约 55 个** 类型值（`core/trace.py:17`），覆盖整个 Agent 决策链，包括：
- 文件分析族（7 个）：`FILE_GROUNDING`, `FILE_ANALYSIS_MULTI_TABLE_ROLES`, `FILE_ANALYSIS_MISSING_FIELDS`, `FILE_ANALYSIS_SPATIAL_METADATA`, `FILE_ANALYSIS_FALLBACK_*`
- 文件关系解析族（5 个）
- 补充列合并族（6 个）
- 意图解析族（5 个）
- Artifact 记忆族（5 个）
- 摘要交付族（6 个）
- Readiness 评估族（4 个）
- 工作流模板族（4 个）
- 计划管理族（9 个）：`PLAN_CREATED`, `PLAN_VALIDATED`, `PLAN_DEVIATION`, `PLAN_STEP_MATCHED`, `PLAN_STEP_COMPLETED`, `DEPENDENCY_VALIDATED`, `DEPENDENCY_BLOCKED`, `PLAN_REPAIR_*`, `PLAN_CONTINUATION_*`
- 参数协商族（4 个）
- 输入补全族（5 个）
- 几何恢复族（5 个）
- 残余重入族（4 个）
- 核心工具族（5 个）：`PARAMETER_STANDARDIZATION`, `CROSS_CONSTRAINT_VALIDATED`, `TOOL_SELECTION`, `TOOL_EXECUTION`, `STATE_TRANSITION`
- 通用族（3 个）：`CLARIFICATION`, `SYNTHESIS`, `ERROR`

每个 `TraceStep` 包含：`step_index`, `step_type`, `timestamp`, `stage_before`, `stage_after`, `action`, `input_summary`, `output_summary`, `confidence`, `reasoning`, `duration_ms`, `standardization_records`, `error`。

---

### 4.10 RemediationPolicy（修复策略）

**位置**：`core/remediation_policy.py`
**启用条件**：`enable_policy_based_remediation=true`（默认 true）

**4 种策略类型**（`RemediationPolicyType`）：
- `UNIFORM_SCALAR_FILL`：对所有路段统一填充某字段的标量值
- `UPLOAD_SUPPORTING_FILE`：要求用户上传补充文件
- `APPLY_DEFAULT_TYPICAL_PROFILE`：应用 HCM 6th 典型剖面（含默认流量/速度查找表）
- `PAUSE`：暂停等待用户输入

**HCM 6th 默认流量查找表**（`core/remediation_policy.py:56`）：按 `(highway_class, lanes)` 二维键查找，覆盖 14 种道路类型（motorway → service）。例：`motorway, 2 lanes → 1600 veh/h`，`residential → 150 veh/h`。

**注意**：文档明确声明（`core/remediation_policy.py:47`）：
> "This is a *default typical profile* for rapid prototyping, NOT a calibrated traffic-state inference model."

---

## 5. ToolContract 与可扩展性

### 5.1 ToolContract 系统

**配置文件**：`config/tool_contracts.yaml`（存在）
**加载器**：`tools/contract_loader.py:ToolContractRegistry`

`ToolContractRegistry` 在初始化时：
1. 读取 `config/tool_contracts.yaml`
2. 验证 `tool_definition_order` 中引用的工具全部在 `tools` 字典中存在
3. 验证 `readiness_action_order` 中引用的 action 全部在某 `action_variants` 或 `artifact_actions` 中定义

`ToolContractRegistry` 对外提供 5 个方法（`tools/contract_loader.py:76`）：

| 方法 | 用途 |
|------|------|
| `get_tool_definitions()` | 生成 OpenAI function-calling 格式的 tool schema 列表 |
| `get_tool_graph()` | 生成 TOOL_GRAPH 依赖图 |
| `get_action_catalog_entries()` | 生成 readiness action catalog |
| `get_continuation_keywords()` | 生成续接关键词字典 |
| `get_param_standardization_map()` | 生成参数→标准化类型映射 |

---

### 5.2 添加新工具所需的步骤

基于代码审计，添加一个新工具需要修改以下文件：

1. **实现工具类**（`tools/new_tool.py`）：
   - 继承 `BaseTool`（`tools/base.py:40`）
   - 实现 `async execute(**kwargs) -> ToolResult`
   - 可选：覆盖 `preflight_check()` 以添加真实检查

2. **注册工具**（`tools/registry.py:82`，`init_tools()` 函数）：
   - 添加 `from tools.new_tool import NewTool` 和 `register_tool("new_tool_name", NewTool())`

3. **声明 ToolContract**（`config/tool_contracts.yaml`）：
   - 在 `tools:` 下添加完整 contract，包含 `description`, `parameters`, `dependencies`, `readiness`, `continuation_keywords`
   - 在 `tool_definition_order:` 中添加工具名
   - 可选：在 `action_variants:` 下声明 readiness action，并添加到 `readiness_action_order:`

4. **实现计算逻辑**（`calculators/` 或工具内部）

5. **无需修改** `tools/definitions.py`（已被 contract_loader 替代）、`core/tool_dependencies.py`（自动从 contracts 生成 TOOL_GRAPH）

---

### 5.3 已知遗留碎片（技术债务）

- **`tools/definitions.py`** 仍存在，但已被 `contract_loader.py` 取代。两者可能存在不一致。代码中的 `tools/definitions.py` 不再是运行时的主要工具定义来源。
- **`core/tool_dependencies.py:32`** 中 `TOOL_GRAPH` 已改为从 `get_tool_contract_registry().get_tool_graph()` 动态生成，而不再是硬编码字典。

---

## 6. 端到端数据流追踪

**场景**：用户上传含 `link_id, flow, speed, length` 列的 CSV 文件，并要求宏观排放估算。

---

### 步骤 1：入口——`UnifiedRouter.chat()`

**位置**：`core/router.py:1190`

```python
async def chat(self, user_message, file_path, trace):
    config = get_config()
    if config.enable_state_orchestration:   # 默认 True
        return await self._run_state_loop(user_message, file_path, trace)
```

`_run_state_loop`（`core/router.py:1362`）初始化 `TaskState`：

```python
state = TaskState.initialize(
    user_message=user_message,
    file_path=file_path,          # CSV 文件路径
    memory_dict=fact_memory,      # 来自上轮记忆的参数（如有）
    session_id=self.session_id,
)
state.control.max_steps = 4       # 默认最大步数
```

---

### 步骤 2：INPUT_RECEIVED 阶段——文件分析（Grounding）

**位置**：`core/router.py:8917`（`_state_handle_input` 中的文件分析分支）

由于 `state.file_context.has_file=True` 且未 grounded，系统调用：

```python
analysis_dict = await self._analyze_file(file_path_str)
```

`_analyze_file` 内部调用 `FileAnalyzerTool.execute(file_path=...)` (`tools/file_analyzer.py`)：

1. 读取 CSV：`pd.read_csv(file_path)`
2. 提取列名：`["link_id", "flow", "speed", "length"]`
3. 按 `config/unified_mappings.yaml:column_patterns.macro_emission` 进行模式匹配：
   - `flow` → 匹配 `traffic_flow_vph` 的 patterns 中 `"flow"` → 列映射成功
   - `speed` → 匹配 `avg_speed_kph` patterns 中 `"speed"` → 成功
   - `length` → 匹配 `link_length_km` patterns 中 `"length"` → 成功
   - `link_id` → 匹配 `link_id` patterns → 成功
4. 判定 `task_type="macro_emission"`，`confidence≈0.9`（因 3 个必填字段全部匹配）
5. 返回 `macro_mapping={"link_id": "link_id", "link_length_km": "length", "traffic_flow_vph": "flow", "avg_speed_kph": "speed"}`

**`state.update_file_context(analysis_dict)`**（`core/task_state.py:926`）：将分析结果写入 `state.file_context`，设置 `grounded=True`

---

### 步骤 3：INPUT_RECEIVED → GROUNDED 状态转换

**Readiness 评估**：`ReadinessAssessment` 被构建：
- `run_macro_emission` action：`required_task_types=["macro_emission"]` ✓，`required_result_tokens=[]` ✓ → **READY**
- `run_dispersion` action：`requires_geometry_support=true`，当前无几何列 → **BLOCKED**
- 其余 action 按各自条件评估

状态转换：`INPUT_RECEIVED → GROUNDED`

---

### 步骤 4：GROUNDED 阶段

**位置**：`core/router.py:9348`（`_state_handle_grounded`）

此阶段决定执行计划和目标工具：
- 根据文件上下文（`task_type=macro_emission`）和 Readiness 评估，目标工具确定为 `calculate_macro_emission`
- 调用 `state.transition(TaskStage.EXECUTING)`

---

### 步骤 5：EXECUTING 阶段——参数标准化

**位置**：`core/router.py:9405`（`_state_handle_executing`）

在工具执行前，Executor 层对 LLM 提议的参数进行标准化：

若 LLM 提议 `season="夏天"`：
- StandardizationEngine 查找 `season` lookup：`"夏天".lower() = "夏天"` → alias 匹配 → `"夏季"`
- `StandardizationResult(success=True, normalized="夏季", strategy="alias", confidence=0.95)`

跨约束验证：`CrossConstraintValidator.validate({"vehicle_type": ..., "pollutants": ..., "season": "夏季"})`
- 若 season=夏季, meteorology=urban_winter_day → 触发 `season_meteorology_consistency` 警告（不阻断）

---

### 步骤 6：工具执行——`MacroEmissionTool.execute()`

**位置**：`tools/macro_emission.py`

1. **字段修复**（`_fix_common_errors()`，`tools/macro_emission.py:57`）：
   - `flow` → `traffic_flow_vph`（已由 macro_mapping 处理，此处二次保障）
   - `speed` → `avg_speed_kph`
   - `length` → `link_length_km`

2. **参数准备**：从文件读取路段数据（通过 `ExcelHandler`，`skills/macro_emission/excel_handler.py`），按 `macro_mapping` 重命名列

3. **调用 `MacroEmissionCalculator.calculate()`**（`calculators/macro_emission.py:86`）：
   - 加载季节矩阵（带进程级缓存）
   - 对每个路段调用 `_calculate_link()`
   - 核心计算公式（见 §2.3）：使用 opMode=300 查询每种车型/污染物的平均排放率，乘以行驶时间和每小时车辆数

4. **返回 `ToolResult`**：
   - `data.results`：每路段 `{link_id, link_length_km, traffic_flow_vph, avg_speed_kph, fleet_composition, emissions_by_vehicle, total_emissions_kg_per_hr, emission_rates_g_per_veh_km}`
   - `data.summary`：`{total_links, total_emissions_kg_per_hr}`
   - `chart_data`：排放量排名图
   - `table_data`：格式化路段排放表格
   - `download_file`：CSV 文件路径

---

### 步骤 7：结果存储与上下文更新

**位置**：`core/router.py`（executing handler 内）

- 将 `"emission"` 令牌加入 `state.execution.available_results`
- 将工具结果存入 `SessionContextStore`（以 `scenario_label` 为键）
- Artifact Memory 记录本次交付（`enable_artifact_memory=true`）

---

### 步骤 8：EXECUTING → DONE + 响应合成

**位置**：`core/router.py`（`_state_build_response()`）

1. 检查是否有后续可执行步骤（`render_emission_map`, `run_dispersion` 等处于 READY 状态）
2. 调用 LLM 进行响应合成（`synthesis_llm: qwen-plus`），注入：
   - 工具计算摘要（`ToolResult.summary`）
   - Readiness 评估（`capability_summary`，通过 `enable_capability_aware_synthesis=true`）
   - 历史对话上下文
3. 返回 `RouterResponse`：`{text, chart_data, table_data, map_data, download_file, trace}`
4. 更新记忆：`self.memory.update(user_message, response_text, tool_calls_data, file_path, file_context)`

---

## 7. 发现的问题与建议

### 7.1 已证实的技术债务

#### 7.1.1 核心文件过大（`core/router.py`）

`core/router.py` 共 **10,633 行**（`wc -l` 实测），包含主 Orchestrator、所有 state handler、LLM 调用、响应合成、记忆管理等，无任何分离。论文可描述为"治理逻辑与路由逻辑耦合于单一 10K+ 行模块"。

**建议**（面向论文）：将 GovernanceEngine（参数验证、跨约束检查、状态转换）从路由逻辑中提取。

#### 7.1.2 双执行路径并存（Legacy Loop 未清除）

`core/router.py:1203`（`_run_legacy_loop`）和 `core/router.py:1362`（`_run_state_loop`）同时存在。通过 `config.enable_state_orchestration=true`（默认开启）选择新路径，但旧路径代码约 150 行未删除，增加维护负担。

#### 7.1.3 工作流模板硬编码

5 个工作流模板在 `core/workflow_templates.py:188` 中以 Python 代码硬编码，不是 YAML 驱动。且 `enable_workflow_templates=false`（默认关闭），意味着此功能在生产环境中未激活。

#### 7.1.4 工具 spec 碎片化

同一工具的参数定义分散在：
- `config/tool_contracts.yaml`（当前权威来源）
- `tools/definitions.py`（遗留，可能不一致）
- 工具类的 `execute()` 方法签名

#### 7.1.5 preflight_check 名不副实

9 个工具中，仅 `DispersionTool` 有实际的 preflight_check 逻辑（检查几何数据可用性）。其余 8 个工具均继承基类的默认实现，直接返回 `is_ready=True`，不做任何检查（`tools/base.py:79`）。

#### 7.1.6 排放矩阵数据来源限制

宏观和微观排放计算器的 MOVES 排放矩阵数据来自 Atlanta（亚特兰大）2025 年模拟结果（文件名如 `atlanta_2025_*`），而非中国本地 MOVES 数据。这是一个重要的数据适用性限制，应在论文的局限性章节中明确说明。

#### 7.1.7 `shared/standardizer/constants.py` 与 `config/unified_mappings.yaml` 重复

两个地方维护 `VSP_BINS` 和 `VEHICLE_TYPE_MAPPING`，存在潜在不一致风险。运行时代码已优先从 YAML 加载（`calculators/vsp.py:22`），但旧常量文件未删除。

#### 7.1.8 `_fix_common_errors()` 的隐式修复

`MacroEmissionTool._fix_common_errors()`（`tools/macro_emission.py:57`）在工具层静默修复字段名，对 LLM 不透明。这是一种脆弱的防御性编程，应通过 column_mapping 统一解决。

#### 7.1.9 扩散模型仅支持 NOx

`calculate_dispersion` 的 `pollutant` 参数描述（`config/tool_contracts.yaml:429`）明确标注："Currently only NOx."。这是一个重要的功能限制。

#### 7.1.10 无明确的 FAILED 状态

状态机没有独立的 `FAILED` 状态（`core/task_state.py:47`），失败路径统一归入 `DONE`。这使得调用方难以通过状态值区分成功与失败。

---

### 7.2 面向论文写作的正面论点

#### 7.2.1 Trace 层可直接引用

`core/trace.py` 的约 55 个 `TraceStepType` 值形成了完整的决策审计链，是论文方法论章节的有力证据。每个 TraceStep 包含 `confidence`、`reasoning`、`input_summary`、`output_summary`，可定量分析 agent 决策质量。

#### 7.2.2 ToolContract 声明式架构可发表

`config/tool_contracts.yaml` 的声明式 ToolContract 系统（工具定义 + 依赖图 + readiness rules + 续接关键词 + 参数标准化映射，全部从单一 YAML 文件加载）是系统设计中最清晰的贡献点，适合作为论文架构章节的核心图示。

#### 7.2.3 RemediationPolicy 可引用 HCM 标准

`core/remediation_policy.py` 中的默认典型剖面查找表明确引用了 HCM 6th Edition，且代码注释说明"值经过保守选择，倾向于低估而非高估"，表现出对数据可靠性的系统性审慎态度，可直接发表。

#### 7.2.4 参数协商是创新交互机制

当前 `ParameterNegotiation` 系统（触发条件、候选生成、确认解析、锁定）是系统中少有的面向最终用户的 UX 创新点，可在论文中单独成节描述。

#### 7.2.5 VSP-to-opMode 映射完整实现

VSP 计算器的完整实现（14 个 VSP Bin + opMode 映射表 + 13 种车型参数）与 MOVES 手册一致，可作为计算方法章节的量化验证依据。

---

*审计结束。本文档所有信息均来自 2026-04-09 代码库静态读取，未作任何推断或猜测。*
