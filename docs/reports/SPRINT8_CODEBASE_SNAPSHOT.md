# SPRINT8 Codebase Snapshot

生成时间: 2026-03-21  
项目根目录: `~/Agent1/emission_agent/`

---

## 第 1 部分：扩散模型源码分析

目标文件: `ps-xgb-aermod-rline-surrogate/mode_inference.py`

### 1.1 文件总行数

- 总行数: `708`
- 入口形式: ❌ 没有 `if __name__ == "__main__":`
- 运行方式: 文件在 import 时直接执行整个推理流水线

### 1.2 所有 import 语句（原样复制）

文件范围: `mode_inference.py:31-47`

```python
import numpy as np
import matplotlib.pyplot as plt
from itertools import product
import pandas as pd
import math
import geopandas as gpd
import os
import shutil
from scipy.interpolate import griddata
from pyproj import Proj, transform
from shapely.geometry import Polygon, LineString, Point
from shapely.ops import unary_union
from shapely.validation import make_valid
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score, mean_absolute_error
from sklearn.preprocessing import StandardScaler
```

### 1.3 顶层函数和类

文件中没有顶层类；只有 7 个顶层函数。

| 名称 | 签名 | 行号范围 | 一句话功能描述 |
|---|---|---:|---|
| `convert_to_utm` | `convert_to_utm(lon, lat)` | `79-82` | 将 WGS84 经纬度转换为 UTM 51N 米制坐标 |
| `make_rectangular_buffer` | `make_rectangular_buffer(line, half_width)` | `131-161` | 为线源道路构造无端帽的矩形缓冲区 |
| `generate_receptors_custom_offset` | `generate_receptors_custom_offset(e_road_df, offset_rule, background_spacing, buffer_extra, width_col, global_extent)` | `164-309` | 按道路侧向偏移和背景网格生成受体点 |
| `split_polyline_by_interval_with_angle` | `split_polyline_by_interval_with_angle(coords, interval)` | `330-374` | 将折线按固定间隔切分并输出中点与道路方位角 |
| `read_sfc` | `read_sfc(path)` | `431-434` | 读取 AERMOD `.SFC` 气象文件 |
| `load_model` | `load_model(path)` | `465-468` | 加载单个 XGBoost surrogate 模型 |
| `predict_time_series_xgb` | `predict_time_series_xgb(models, receptors_x, receptors_y, sources, met, x_range0, x_range1, y_range, batch_size)` | `490-668` | 在时间序列上对所有受体执行批量浓度推理 |

### 1.4 硬编码常量

#### 1.4.1 路径与模型文件

| 名称 | 值 | 行号 |
|---|---|---:|
| `ROAD_SHP` | `r"YOUR_PATH\roads.shp"` | `25` |
| `EMISSION_CSV` | `r"YOUR_PATH\hourly_emission.csv"` | `26` |
| `MET_SFC` | `r"YOUR_PATH\met_file.SFC"` | `27` |
| `MODEL_DIR` | `r"models"` | `28` |

硬编码加载的 12 个 `_M` 模型文件，文件范围 `mode_inference.py:471-482`:

```python
model_RLINE_remet_multidir_stable_2000_x0_M.json
model_RLINE_remet_multidir_stable_2000_x-1_M.json
model_RLINE_remet_multidir_verystable_2000_x0_M.json
model_RLINE_remet_multidir_verystable_2000_x-1_M.json
model_RLINE_remet_multidir_unstable_2000_x0_M.json
model_RLINE_remet_multidir_unstable_2000_x-1_M.json
model_RLINE_remet_multidir_veryunstable_2000_x0_M.json
model_RLINE_remet_multidir_veryunstable_2000_x-1_M.json
model_RLINE_remet_multidir_neutral1_x0_M.json
model_RLINE_remet_multidir_neutral1_x-1_M.json
model_RLINE_remet_multidir_neutral2_x0_M.json
model_RLINE_remet_multidir_neutral2_x-1_M.json
```

#### 1.4.2 坐标系 / CRS / 局部坐标

| 名称 | 值 | 行号 |
|---|---|---:|
| `wgs84` | `Proj(proj="latlong", datum="WGS84")` | `76` |
| `utm51n` | `Proj(proj="utm", zone=51, datum="WGS84", hemisphere="north")` | `77` |
| 局部原点平移 | `x - min_x`, `y - min_y` | `99-105` |

说明:
- EPSG 代码没有显式写出。
- 实际使用的是 `WGS84 -> UTM Zone 51N`。
- 输出坐标不是原始 UTM，而是再做了局部平移后的“本地 UTM-like 坐标”。

#### 1.4.3 网格 / 受体 / 几何参数

| 名称 | 值 | 行号 |
|---|---|---:|
| `offset_rule` 默认值 | `{6.5: 2, 15: 4, 30: 7, 50: 12}` | `166` |
| `background_spacing` 默认值 | `50` | `167` |
| `buffer_extra` 默认值 | `30` | `168` |
| `width_col` 默认值 | `'width'` | `169` |
| 缺省道路宽度 | `7.0` m | `193` |
| 实际调用 `offset_rule` | `{3.5: 40, 8.5: 40}` | `314` |
| 实际调用 `background_spacing` | `50` | `315` |
| 实际调用 `buffer_extra` | `3` | `316` |
| `interval` 默认值 | `10` m | `330` |
| 实际 `interval` | `10` | `378` |
| 绘图窗口 `xlim` | `(1000, 1400)` | `304` |
| 绘图窗口 `ylim` | `(600, 900)` | `305` |
| 绘图标题 | `"Receptor layout (rectangular buffer + local coordinates)"` | `306` |

#### 1.4.4 物理 / 单位 / 数值常量

| 名称 | 值 | 行号 |
|---|---|---:|
| NOx 面源换算宽度 | `7` m | `120` |
| kg -> g 换算 | `1000` | `120` |
| h -> s 换算 | `3600` | `120` |
| 稳定类阈值 | `L <= 200`, `L < 1000`, `L >= 1000`, `L <= -1000`, `L <= -200`, `L < 0` | `449-457` |
| 缺测哨兵值 | `999`, `-999`, `-99999` | `451-457` |
| 推理下风向范围 | `x_range0=(0, 1000.0)` | `496`, `705` |
| 推理上风向范围 | `x_range1=(-100, 0.0)` | `497`, `706` |
| 默认横风范围 | `y_range=(-50.0, 50.0)` | `498` |
| 实际调用横风范围 | `y_range=(-100.0, 100.0)` | `707` |
| 批推理大小 | `batch_size=200000` | `499` |
| 无 `HC` 特征稳定类 | `["VS", "S", "N1"]` | `531` |

#### 1.4.5 污染物、列名与输出字段

| 名称 | 值 | 行号 |
|---|---|---:|
| 输入污染物列 | `"nox"` | `120` |
| 派生排放字段 | `"nox_g_m_s2"` | `120`, `408-415` |
| 输出列 | `Date`, `Receptor_ID`, `Receptor_X`, `Receptor_Y`, `Conc` | `660-665` |
| `.SFC` 列名数组 `col_names` | `["Year","Month","Day","JulianDay","Hour","H","USTAR","WSTAR","ThetaGrad","MixHGT_C","MixHGT_M","L","Z0","B0","Albedo","WSPD","WDIR","AnemoHt","Temp","MeasHt","PrecipType","PrecipAmt","RH","Pressure","CloudCover","WindFlag","CloudTempFlag"]` | `422-429` |

### 1.5 执行流程

起点: 顶层执行代码，文件没有 `main()` 和 `if __name__ == "__main__":`。

1. `25-28` 读取用户配置中的 3 个输入路径和 1 个模型目录。
2. `53-61` 加载道路 Shapefile 与小时排放 CSV，并按 `NAME_1` 合并。
3. `63-66` 检查未匹配到几何的道路并打印 warning。
4. `72-111` 去重道路，使用 `convert_to_utm()` 将 WGS84 几何转 UTM 51N，并平移到局部原点。
5. `113-124` 解析 `data_time`，派生 `day/hour/index`，并把 `nox` 转成 `nox_g_m_s2`。
6. `131-309` 定义受体生成相关函数。
7. `312-323` 用硬编码参数调用 `generate_receptors_custom_offset()`，然后按 `(x, y)` 去重受体。
8. `330-416` 定义并调用折线分段函数，把每条路切成 10m 段，中点附带方位角，再把时序排放挂到每个线源段上。
9. `422-459` 读取 `.SFC` 气象文件，构造整数 `Date`，并按 `L/WSPD/MixHGT_C` 计算 `Stab_Class`。
10. `465-483` 依次加载 12 个 `_M` XGBoost 模型。
11. `490-668` 定义 `predict_time_series_xgb()` 推理函数。
12. `674-683` 构造 `sources` 和 `sources_re` 三维数组。
13. `686-687` 抽取受体坐标数组 `x_rp/y_rp`。
14. `689-696` 构建稳定类到正负向模型的映射字典 `models`。
15. `699-708` 调用 `predict_time_series_xgb()`，结果保存在内存变量 `time_series_conc`。

### 1.6 输入数据格式

#### 1.6.1 道路数据

- 文件格式: Shapefile
- 读取方式: `gpd.read_file(ROAD_SHP)` (`53`)
- 必需字段:
  - `NAME_1`
  - `geometry`
- 可选字段:
  - `width`，缺失则使用默认 `7.0 m` (`192-193`)
- 几何类型:
  - `LineString`
  - `MultiLineString`
- 期望坐标系:
  - 输入应为 WGS84 经纬度；代码随后转换到 UTM 51N (`76-82`)

#### 1.6.2 小时排放数据

- 文件格式: CSV
- 读取方式: `pd.read_csv(EMISSION_CSV)` (`54`)
- 必需字段:
  - `NAME` 或已存在 `NAME_1`；代码会把 `NAME -> NAME_1` (`56`)
  - `data_time`
  - `nox`
  - `length`
- 数据粒度:
  - 每条路每小时一行
- 单位假设:
  - `length` 以 km 计
  - `nox` 被换算为 `g/s/m2` 时使用了 `* 1000 / 3600 / (length * 7m)`，说明代码默认 `nox` 是“每路段每小时总量，单位 kg/h”

#### 1.6.3 气象数据

- 文件格式: AERMOD `.SFC`
- 读取方式: `pd.read_csv(..., delim_whitespace=True, names=col_names, skiprows=1, comment="#")` (`433-434`)
- 必需列:
  - `Year`, `Month`, `Day`, `Hour`
  - `H`, `MixHGT_C`, `L`, `WSPD`, `WDIR`
- 额外解析但当前推理未直接使用的列:
  - `USTAR`, `WSTAR`, `ThetaGrad`, `MixHGT_M`, `Z0`, `B0`, `Albedo`, `Temp`, `RH`, `Pressure`, `CloudCover` 等

### 1.7 输出数据格式

最终产物不是文件，而是内存变量 `time_series_conc`，类型为 `pd.DataFrame`，定义见 `660-665`:

```python
pd.DataFrame({
    "Date":       date,
    "Receptor_ID": indices,
    "Receptor_X":  np.round(rx, 1),
    "Receptor_Y":  np.round(ry, 1),
    "Conc":        total_conc
})
```

输出说明:

- 数据结构: `pandas.DataFrame`
- 列:
  - `Date`: 气象时间编码整数
  - `Receptor_ID`: 受体索引
  - `Receptor_X`, `Receptor_Y`: 局部平移后的 UTM-like 米制坐标
  - `Conc`: 每个时刻每个受体的累计浓度
- 坐标系:
  - 不是 WGS84
  - 也不是原始绝对 UTM
  - 是 `(utm_x - min_x, utm_y - min_y)` 的局部坐标
- 单位:
  - `Receptor_X/Y`: 米
  - `Conc`: 脚本中未显式标注单位；由 surrogate 模型输出与 `preds * strength / 1e-6` 累积而来
- 落盘情况:
  - ❌ 没有 `to_csv()` / `to_file()` / GeoJSON 输出

### 1.8 `models/` 目录结构

目标目录: `ps-xgb-aermod-rline-surrogate/models/`

目录汇总:

| 目录 | 文件数 | 总大小 |
|---|---:|---:|
| `model_z=0.05` | `12` | `51,902,763 bytes` |
| `model_z=0.5` | `12` | `48,307,193 bytes` |
| `model_z=1` | `12` | `48,300,376 bytes` |

完整结构:

```text
d		4096 bytes
d	model_z=0.05	4096 bytes
d	model_z=0.5	4096 bytes
d	model_z=1	4096 bytes
f	README_models.md	2480 bytes
f	model_z=0.05/model_RLINE_remet_multidir_neutral1_x-1_L.json	4025034 bytes
f	model_z=0.05/model_RLINE_remet_multidir_neutral1_x0_L.json	4029569 bytes
f	model_z=0.05/model_RLINE_remet_multidir_neutral2_x-1_L.json	4013088 bytes
f	model_z=0.05/model_RLINE_remet_multidir_neutral2_x0_L.json	4007701 bytes
f	model_z=0.05/model_RLINE_remet_multidir_stable_2000_x-1_L.json	4018376 bytes
f	model_z=0.05/model_RLINE_remet_multidir_stable_2000_x0_L.json	4029759 bytes
f	model_z=0.05/model_RLINE_remet_multidir_unstable_2000_x-1_L.json	4019001 bytes
f	model_z=0.05/model_RLINE_remet_multidir_unstable_2000_x0_L.json	4023484 bytes
f	model_z=0.05/model_RLINE_remet_multidir_verystable_2000_x-1_L.json	3993817 bytes
f	model_z=0.05/model_RLINE_remet_multidir_verystable_2000_x0_L.json	4005528 bytes
f	model_z=0.05/model_RLINE_remet_multidir_veryunstable_2000_x-1_L.json	4011757 bytes
f	model_z=0.05/model_RLINE_remet_multidir_veryunstable_2000_x0_L.json	7725649 bytes
f	model_z=0.5/model_RLINE_remet_multidir_neutral1_x-1_M.json	4022827 bytes
f	model_z=0.5/model_RLINE_remet_multidir_neutral1_x0_M.json	4023004 bytes
f	model_z=0.5/model_RLINE_remet_multidir_neutral2_x-1_M.json	4021650 bytes
f	model_z=0.5/model_RLINE_remet_multidir_neutral2_x0_M.json	4027256 bytes
f	model_z=0.5/model_RLINE_remet_multidir_stable_2000_x-1_M.json	4027036 bytes
f	model_z=0.5/model_RLINE_remet_multidir_stable_2000_x0_M.json	4029705 bytes
f	model_z=0.5/model_RLINE_remet_multidir_unstable_2000_x-1_M.json	4025102 bytes
f	model_z=0.5/model_RLINE_remet_multidir_unstable_2000_x0_M.json	4032801 bytes
f	model_z=0.5/model_RLINE_remet_multidir_verystable_2000_x-1_M.json	4027535 bytes
f	model_z=0.5/model_RLINE_remet_multidir_verystable_2000_x0_M.json	4026125 bytes
f	model_z=0.5/model_RLINE_remet_multidir_veryunstable_2000_x-1_M.json	4023740 bytes
f	model_z=0.5/model_RLINE_remet_multidir_veryunstable_2000_x0_M.json	4020412 bytes
f	model_z=1/model_RLINE_remet_multidir_neutral1_x-1_H.json	4016793 bytes
f	model_z=1/model_RLINE_remet_multidir_neutral1_x0_H.json	4024287 bytes
f	model_z=1/model_RLINE_remet_multidir_neutral2_x-1_H.json	4024768 bytes
f	model_z=1/model_RLINE_remet_multidir_neutral2_x0_H.json	4031409 bytes
f	model_z=1/model_RLINE_remet_multidir_stable_2000_x-1_H.json	4025240 bytes
f	model_z=1/model_RLINE_remet_multidir_stable_2000_x0_H.json	4031012 bytes
f	model_z=1/model_RLINE_remet_multidir_unstable_2000_x-1_H.json	4025635 bytes
f	model_z=1/model_RLINE_remet_multidir_unstable_2000_x0_H.json	4029645 bytes
f	model_z=1/model_RLINE_remet_multidir_verystable_2000_x-1_H.json	4022214 bytes
f	model_z=1/model_RLINE_remet_multidir_verystable_2000_x0_H.json	4020030 bytes
f	model_z=1/model_RLINE_remet_multidir_veryunstable_2000_x-1_H.json	4026999 bytes
f	model_z=1/model_RLINE_remet_multidir_veryunstable_2000_x0_H.json	4022344 bytes
```

推断出的命名规则:

```text
model_RLINE_remet_multidir_{stability}_{xside}_{roughness}.json
model_RLINE_remet_multidir_{stability}_2000_{xside}_{roughness}.json

stability ∈ {stable, verystable, unstable, veryunstable, neutral1, neutral2}
xside ∈ {x0, x-1}
roughness ∈ {L, M, H}
目录 roughness:
  model_z=0.05 -> L
  model_z=0.5  -> M
  model_z=1    -> H
```

---

## 第 2 部分：现有 calculators 模块结构

### 2.1 `calculators/` 目录所有文件及行数

```text
calculators/__init__.py	11
calculators/emission_factors.py	245
calculators/macro_emission.py	341
calculators/micro_emission.py	242
calculators/vsp.py	148
```

### 2.2 每个 calculator 的类、公开方法与输入输出

### 2.2.1 `calculators/vsp.py`

- 类: `VSPCalculator` (`7-148`)
- `__init__` 参数: `__init__(self)` (`10-12`)
- 公开方法:
  - `calculate_vsp(self, speed_mps, acc, grade_pct, vehicle_type_id)` (`14-45`)
  - `vsp_to_bin(self, vsp)` (`47-52`)
  - `vsp_to_opmode(self, speed_mph, vsp)` (`54-96`)
  - `calculate_trajectory_vsp(self, trajectory, vehicle_type_id)` (`98-148`)

输入输出:

- `calculate_vsp(...)`
  - 输入: `speed_mps: float`, `acc: float`, `grade_pct: float`, `vehicle_type_id: int`
  - 输出: `float`，四舍五入后的 VSP 值
- `vsp_to_bin(...)`
  - 输入: `vsp: float`
  - 输出: `int`，1-14 的 VSP bin
- `vsp_to_opmode(...)`
  - 输入: `speed_mph: float`, `vsp: float`
  - 输出: `int`，MOVES opMode
- `calculate_trajectory_vsp(...)`
  - 输入: `trajectory: list[dict]`，每个点至少有 `speed_kph`，可选 `t`、`acceleration_mps2`、`grade_pct`
  - 输出: `list[dict]`，在原点记录基础上补充 `speed_mps`、`speed_mph`、`acceleration_calculated`、`vsp`、`vsp_bin`、`opmode`

### 2.2.2 `calculators/micro_emission.py`

- 类: `MicroEmissionCalculator` (`9-242`)
- `__init__` 参数: `__init__(self)` (`59-66`)
- 公开方法:
  - `calculate(self, trajectory_data, vehicle_type, pollutants, model_year, season)` (`91-166`)

输入输出:

- `calculate(...)`
  - 输入:
    - `trajectory_data: List[Dict]`
    - `vehicle_type: str`
    - `pollutants: List[str]`
    - `model_year: int`
    - `season: str`
  - 轨迹数据格式:
    - 必需: `speed_kph`
    - 推荐: `t`
    - 可选: `acceleration_mps2`, `grade_pct`
  - 成功输出:

```python
{
  "status": "success",
  "data": {
    "query_info": {
      "vehicle_type": str,
      "pollutants": list[str],
      "model_year": int,
      "season": str,
      "trajectory_points": int
    },
    "summary": {
      "total_distance_km": float,
      "total_time_s": int,
      "total_emissions_g": {pollutant: float},
      "emission_rates_g_per_km": {pollutant: float}
    },
    "results": [
      {
        "t": int,
        "speed_kph": float,
        "speed_mph": float,
        "vsp": float,
        "opmode": int,
        "emissions": {pollutant: float}
      }
    ]
  }
}
```

  - 失败输出:

```python
{
  "status": "error",
  "error": "...",                 # 未知车型时
  "valid_vehicle_types": [...],   # 未知车型时
}
```

或:

```python
{
  "status": "error",
  "error_code": "CALCULATION_ERROR",
  "message": str(e)
}
```

### 2.2.3 `calculators/macro_emission.py`

- 类: `MacroEmissionCalculator` (`8-340`)
- `__init__` 参数: `__init__(self)` (`73-79`)
- 公开方法:
  - `clear_matrix_cache(cls)` (`82-84`)
  - `calculate(self, links_data, pollutants, model_year, season, default_fleet_mix)` (`86-129`)

输入输出:

- `calculate(...)`
  - 输入:
    - `links_data: List[Dict]`
    - `pollutants: List[str]`
    - `model_year: int`
    - `season: str`
    - `default_fleet_mix: Dict | None`
  - `links_data[*]` 期望字段:
    - 必需: `link_length_km`, `traffic_flow_vph`, `avg_speed_kph`
    - 推荐: `link_id`
    - 可选: `fleet_mix`
  - 成功输出:

```python
{
  "status": "success",
  "data": {
    "query_info": {
      "model_year": int,
      "pollutants": list[str],
      "season": str,
      "links_count": int
    },
    "results": [
      {
        "link_id": str,
        "link_length_km": float,
        "traffic_flow_vph": float,
        "avg_speed_kph": float,
        "fleet_composition": {
          vehicle_name: {
            "source_type_id": int,
            "percentage": float,
            "vehicles_per_hour": float
          }
        },
        "emissions_by_vehicle": {
          vehicle_name: {
            pollutant_name: float
          }
        },
        "total_emissions_kg_per_hr": {
          pollutant_name: float
        },
        "emission_rates_g_per_veh_km": {
          pollutant_name: float
        }
      }
    ],
    "summary": {
      "total_links": int,
      "total_emissions_kg_per_hr": {
        pollutant_name: float
      }
    }
  }
}
```

  - 失败输出:

```python
{
  "status": "error",
  "error_code": "CALCULATION_ERROR",
  "message": str(e)
}
```

### 2.2.4 `calculators/emission_factors.py`

- 类: `EmissionFactorCalculator` (`8-245`)
- `__init__` 参数: `__init__(self)` (`67-74`)
- 公开方法:
  - `query(self, vehicle_type, pollutant, model_year, season, road_type, return_curve)` (`76-233`)

输入输出:

- `query(...)`
  - 输入:
    - `vehicle_type: str`
    - `pollutant: str`
    - `model_year: int`
    - `season: str = "夏季"`
    - `road_type: str = "快速路"`
    - `return_curve: bool = False`
  - 成功输出 1: `return_curve=True`

```python
{
  "status": "success",
  "data": {
    "curve": [
      {"speed_kph": float, "emission_rate": float}
    ],
    "unit": "g/km",
    "speed_range": {"min_kph": float, "max_kph": float},
    "data_points": int
  }
}
```

  - 成功输出 2: `return_curve=False`

```python
{
  "status": "success",
  "data": {
    "query_summary": {
      "vehicle_type": str,
      "pollutant": str,
      "model_year": int,
      "season": str,
      "road_type": str
    },
    "speed_curve": [
      {
        "speed_mph": int,
        "speed_kph": float,
        "emission_rate": float,
        "unit": "g/mile"
      }
    ],
    "typical_values": [...],
    "speed_range": {...},
    "data_points": int,
    "unit": "g/mile",
    "data_source": "MOVES (Atlanta)"
  }
}
```

  - 失败输出:
    - 未知车型 / 污染物: 返回 `status=error` 和有效枚举列表
    - 未找到数据: 返回 `debug.query`、`available_years`、`available_source_types`、`available_pollutants`

### 2.3 `calculators/__init__.py` 导出内容

文件范围: `calculators/__init__.py:1-11`

```python
from calculators.vsp import VSPCalculator
from calculators.micro_emission import MicroEmissionCalculator
from calculators.macro_emission import MacroEmissionCalculator

__all__ = [
    'VSPCalculator',
    'MicroEmissionCalculator',
    'MacroEmissionCalculator'
]
```

### 2.4 现有 calculator 的共同模式

- ❌ 没有 calculator 基类，也没有统一抽象接口。
- 共同风格是“同步纯计算类”，通常在 `__init__()` 中准备 `data_path/csv_files` 或常量映射。
- `calculate()` / `query()` 的主要返回约定是字典:
  - 成功: `{"status": "success", "data": {...}}`
  - 失败: `{"status": "error", ...}`
- 例外:
  - `VSPCalculator` 不是状态字典接口，而是直接返回数值 / 列表；不支持车型时抛 `ValueError`
- 错误处理模式:
  - `MicroEmissionCalculator` / `MacroEmissionCalculator` / `EmissionFactorCalculator` 的主入口方法内部兜底 `try/except`
  - 更底层的私有方法通常直接抛异常，由主入口转成状态字典
- 共同依赖模式:
  - 通过类级映射常量维护 `vehicle -> sourceType`、`pollutant -> pollutantID`、`season -> season code`
  - 主要数据源是仓库内置 CSV

---

## 第 3 部分：工具注册与调用链

### 3.1 `tools/` 目录所有文件及行数

```text
tools/__init__.py	14
tools/base.py	104
tools/definitions.py	196
tools/emission_factors.py	229
tools/file_analyzer.py	601
tools/formatter.py	138
tools/knowledge.py	73
tools/macro_emission.py	805
tools/micro_emission.py	251
tools/registry.py	119
tools/spatial_renderer.py	302
```

### 3.2 工具注册机制与 Router 调用链

关键文件:

- `tools/definitions.py:6-196`
- `core/assembler.py:34-37, 42-119`
- `core/router.py:505, 682`
- `core/executor.py:25-33, 36-137`
- `tools/registry.py:12-119`

调用链:

1. `tools/definitions.py` 定义 OpenAI function-calling 格式的 `TOOL_DEFINITIONS`。
2. `ContextAssembler.__init__()` 通过 `ConfigLoader.load_tool_definitions()` 载入工具 schema，注入到 LLM 上下文。
3. `UnifiedRouter` 调 `self.llm.chat_with_tools(...)`，LLM 返回 `tool_calls`。
4. Router 在 `_state_handle_executing()` 中逐个把 `tool_call.name` 和 `tool_call.arguments` 传给 `self.executor.execute(...)`。
5. `ToolExecutor.__init__()` 首次运行时通过 `init_tools()` 完成工具实例注册。
6. `tools/registry.py` 的 `ToolRegistry` 以单例保存 `{tool_name -> tool_instance}`。
7. `ToolExecutor.execute()` 先标准化参数，再用 `registry.get(tool_name)` 找到工具实例，最后 `await tool.execute(**standardized_args)`。
8. 工具内部再调用 calculator、文件处理器或知识服务，返回统一的 `ToolResult`。
9. Executor 把 `ToolResult` 转成普通字典，Router 再做 synthesis / payload extract / memory update。

工具注册代码摘录，文件范围: `tools/registry.py:74-119`

```python
def init_tools():
    logger.info("Initializing tools...")

    try:
        from tools.emission_factors import EmissionFactorsTool
        register_tool("query_emission_factors", EmissionFactorsTool())
    except Exception as e:
        logger.error(f"Failed to register emission_factors tool: {e}")

    try:
        from tools.micro_emission import MicroEmissionTool
        register_tool("calculate_micro_emission", MicroEmissionTool())
    except Exception as e:
        logger.error(f"Failed to register micro_emission tool: {e}")

    try:
        from tools.macro_emission import MacroEmissionTool
        register_tool("calculate_macro_emission", MacroEmissionTool())
    except Exception as e:
        logger.error(f"Failed to register macro_emission tool: {e}")

    try:
        from tools.file_analyzer import FileAnalyzerTool
        register_tool("analyze_file", FileAnalyzerTool())
    except Exception as e:
        logger.error(f"Failed to register file_analyzer tool: {e}")

    try:
        from tools.knowledge import KnowledgeTool
        register_tool("query_knowledge", KnowledgeTool())
    except Exception as e:
        logger.error(f"Failed to register knowledge tool: {e}")

    try:
        from tools.spatial_renderer import SpatialRendererTool
        register_tool("render_spatial_map", SpatialRendererTool())
    except Exception as e:
        logger.warning(f"Failed to register render_spatial_map: {e}")
```

### 3.3 `tools/macro_emission.py` 深读

#### 3.3.1 它如何调用 calculator

关键范围: `tools/macro_emission.py:551-797`

```python
# 5. Execute calculation
result = self._calculator.calculate(
    links_data=links_data,
    pollutants=pollutants,
    model_year=model_year,
    season=season,
    default_fleet_mix=effective_default_fleet_mix
)
```

说明:

- `MacroEmissionTool.__init__()` 中初始化 `self._calculator = MacroEmissionCalculator()`
- tool 层负责:
  - 文件读取
  - 字段修正
  - 车队组成标准化
  - 几何保留
  - 结果摘要与 `map_data`
- calculator 层只做纯排放计算

#### 3.3.2 输入参数从哪来

输入来源链:

1. `tools/definitions.py:84-122` 定义 LLM 可调用 schema:
   - `file_path`
   - `links_data`
   - `pollutants`
   - `fleet_mix`
   - `model_year`
   - `season`
2. LLM 产出 `tool_call.arguments`
3. `core/executor.py:78-109` 做参数标准化与 `file_path` 自动注入
4. `MacroEmissionTool.execute(**kwargs)` 接收“已经标准化过”的参数
5. 如果有 `file_path`，tool 会把它兼容映射为 `input_file` (`565-568`)
6. 然后从 Excel/CSV/ZIP/Shapefile 解析 `links_data`

结论:

- 参数首先来自 LLM function call
- 然后经过 executor 的透明标准化
- 文件型输入会由 executor/router 注入 `file_path`

#### 3.3.3 返回值结构，尤其是 geometry

关键范围:

- 参数提取与 calculator 调用: `570-634`
- geometry 回灌到结果: `706-718`
- `map_data` 生成: `776-796`

geometry 处理逻辑:

```python
# Merge geometry from original input into calculator results
# so render_spatial_map can access it via _last_result
if links_results and links_data:
    original_geom_map = {}
    for link in links_data:
        lid = str(link.get("link_id", ""))
        geom = link.get("geometry") or link.get("geom") or link.get("wkt") or link.get("shape")
        if lid and geom:
            original_geom_map[lid] = geom
    for res_link in links_results:
        lid = str(res_link.get("link_id", ""))
        if lid in original_geom_map and "geometry" not in res_link:
            res_link["geometry"] = original_geom_map[lid]
```

成功返回结构:

```python
ToolResult(
    success=True,
    error=None,
    data=result["data"],
    summary=summary,
    map_data=map_data
)
```

其中:

- `ToolResult.data` 里保留 calculator 的:
  - `query_info`
  - `results`
  - `summary`
  - `fleet_mix_fill`
  - 可选 `download_file`
- `data["results"][*]` 会被 tool 层补上 `geometry`
- `map_data` 是额外构造的 legacy 前端地图结构

`results[*].geometry` 可能来源:

- Excel/CSV 中的 `geometry/geom/wkt/shape/几何/路段几何/坐标`
- ZIP 内 shapefile 转出来的坐标数组
- WKT / GeoJSON / JSON string / 坐标串解析后的坐标

#### 3.3.4 作为 Sprint 9 `calculate_dispersion` 的参考模板价值

它是合适模板，原因是:

- 工具层与 calculator 层职责分离清晰
- 输入既支持 LLM 直传结构体，也支持 `file_path`
- ToolResult 结构完整，兼容:
  - `data`
  - `summary`
  - `map_data`
  - `download_file`
- 已有跨 turn 地图可视化对接路径
- 已处理 geometry 回灌，适合作为 `calculate_dispersion` 输出空间结果的模式参考

需要注意的非模板化遗留:

- 依赖 `skills.macro_emission.excel_handler`
- `output_file` 分支仍错误使用 `result["data"].get("links", [])`

### 3.4 `core/tool_dependencies.py` 中的 `TOOL_GRAPH`（完整复制）

文件范围: `core/tool_dependencies.py:11-37`

```python
TOOL_GRAPH: Dict[str, Dict[str, List[str]]] = {
    "query_emission_factors": {
        "requires": [],
        "provides": ["emission_factors"],
    },
    "calculate_micro_emission": {
        "requires": [],
        "provides": ["emission_result"],
    },
    "calculate_macro_emission": {
        "requires": [],
        "provides": ["emission_result"],
    },
    "calculate_dispersion": {
        "requires": ["emission_result"],
        "provides": ["dispersion_result"],
    },
    "render_spatial_map": {
        "requires": [],  # Can render any result that has spatial data
        "provides": ["visualization"],
    },
    "analyze_file": {
        "requires": [],
        "provides": ["file_analysis"],
    },
    "query_knowledge": {
        "requires": [],
        "provides": ["knowledge"],
    },
}
```

---

## 第 4 部分：参数标准化与气象预设

### 4.1 `services/standardizer.py`

#### 4.1.1 当前支持的标准化参数类型

依据:

- `services/standardizer.py:32-53`
- `services/standardizer.py:70-138`
- `services/standardizer.py:208-495`
- `services/standardizer.py:497-572`
- `config/unified_mappings.yaml`

支持类型:

- `vehicle_type`
  - 来源 `vehicle_types`
  - 当前配置 13 个 MOVES 标准车型
- `pollutant`
  - 来源 `pollutants`
  - 当前配置 6 个标准污染物: `CO2`, `CO`, `NOx`, `PM2.5`, `PM10`, `THC`
- `pollutants`
  - 列表形式的批量污染物标准化
- `season`
  - 当前配置 4 个季节: `春季`, `夏季`, `秋季`, `冬季`
- `road_type`
  - 当前配置 5 个道路类型: `快速路`, `高速公路`, `主干道`, `次干道`, `支路`
- `column mapping`
  - `micro_emission` 文件列映射:
    - `speed_kph`, `time`, `acceleration_mps2`, `grade_pct`
  - `macro_emission` 文件列映射:
    - `link_length_km`, `traffic_flow_vph`, `avg_speed_kph`, `link_id`

标准化策略:

- `exact`
- `alias`
- `fuzzy`
- `local_model`
- `default`
- `abstain`

#### 4.1.2 `StandardizationResult` 结构

文件范围: `services/standardizer.py:32-53`

```python
@dataclass
class StandardizationResult:
    """Structured result of a parameter standardization operation."""

    success: bool
    original: str
    normalized: Optional[str] = None
    strategy: str = "none"  # exact / alias / fuzzy / abstain / default
    confidence: float = 0.0
    suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "success": self.success,
            "original": self.original,
            "normalized": self.normalized,
            "strategy": self.strategy,
            "confidence": self.confidence,
        }
        if self.suggestions:
            result["suggestions"] = self.suggestions
        return result
```

### 4.2 `config/meteorology_presets.yaml`

- ❌ 文件不存在
- `wc -l config/meteorology_presets.yaml` 返回 `No such file or directory`
- `rg -n "meteorology_presets|meteorology|presets.yaml" -S .` 未发现运行时代码引用该文件

替代现状:

- 当前项目里与标准化相关的配置集中在 `config/unified_mappings.yaml`
- surrogate 子项目的气象输入依赖 `.SFC` 文件和 `mode_inference.py` 内部硬编码列名，不依赖 preset YAML

### 4.3 `core/executor.py` 中标准化调用流程

关键范围: `core/executor.py:25-137`, `169-253`

流程:

1. `ToolExecutor.__init__()` 获取:
   - `registry = get_registry()`
   - `standardizer = get_standardizer()`
2. 若 registry 为空，调用 `init_tools()` 注册所有工具。
3. `execute(tool_name, arguments, file_path)`:
   - 先从 registry 找工具实例
   - 调 `_standardize_arguments(tool_name, arguments)`
4. `_standardize_arguments(...)` 当前按 key 分支处理:
   - `vehicle_type`
   - `pollutant`
   - `pollutants`
   - `season`
   - `road_type`
   - 其他参数原样透传
5. 标准化失败时抛 `StandardizationError`，executor 返回结构化失败结果，并带 `_standardization_records`
6. 若 router 传入了 `file_path` 且 arguments 没带 `file_path`，executor 自动注入
7. 最终调用 `await tool.execute(**standardized_args)`
8. 将 `ToolResult` 转换为统一 dict:
   - `success`
   - `data`
   - `error`
   - `summary`
   - `chart_data`
   - `table_data`
   - `map_data`
   - `download_file`

标准化关键代码摘录，文件范围: `core/executor.py:198-248`

```python
if key == "vehicle_type":
    result = self.standardizer.standardize_vehicle_detailed(value)
    ...
elif key == "pollutant":
    result = self.standardizer.standardize_pollutant_detailed(value)
    ...
elif key == "pollutants" and isinstance(value, list):
    ...
elif key == "season":
    result = self.standardizer.standardize_season(value)
    ...
elif key == "road_type":
    result = self.standardizer.standardize_road_type(value)
    ...
else:
    standardized[key] = value
```

---

## 第 5 部分：空间数据流与类型系统

### 5.1 `core/spatial_types.py`

完整定义，文件范围: `core/spatial_types.py:13-137`

```python
@dataclass
class SpatialLayer:
    """A single spatial layer with complete rendering instructions.

    Design principle: the backend specifies ALL rendering decisions.
    The frontend only executes -- it never guesses how to render.
    """
    # === Identity ===
    layer_id: str
    geometry_type: str  # "line" | "point" | "polygon" | "grid"

    # === Data ===
    geojson: Dict[str, Any]  # Standard GeoJSON FeatureCollection

    # === Color mapping ===
    color_field: str                    # Feature property to color by
    value_range: List[float]            # [min, max] -- backend computes this
    classification_mode: str = "continuous"  # "continuous" | "threshold" | "quantile" | "category"
    color_scale: str = "YlOrRd"        # Named color scale

    # === Legend ===
    legend_title: str = ""
    legend_unit: Optional[str] = None

    # === Style ===
    opacity: float = 0.8
    weight: float = 2.0                # Line width (line type)
    radius: float = 5.0                # Point radius (point type)
    style_hint: Optional[str] = None   # "heatmap" | "choropleth" | "bubble" | "border_only"

    # === Interaction ===
    popup_fields: Optional[List[Dict[str, str]]] = None

    # === Threshold rendering ===
    threshold: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize, excluding None optional fields."""
        result = {
            "layer_id": self.layer_id,
            "geometry_type": self.geometry_type,
            "geojson": self.geojson,
            "color_field": self.color_field,
            "value_range": self.value_range,
            "classification_mode": self.classification_mode,
            "color_scale": self.color_scale,
            "legend_title": self.legend_title,
            "opacity": self.opacity,
            "weight": self.weight,
            "radius": self.radius,
        }
        for key in ["legend_unit", "style_hint", "popup_fields", "threshold"]:
            val = getattr(self, key)
            if val is not None:
                result[key] = val
        return result


@dataclass
class SpatialDataPackage:
    """Complete spatial rendering package with one or more layers."""
    layers: List[SpatialLayer] = field(default_factory=list)
    title: str = ""
    bounds: Optional[Dict[str, Any]] = None  # {center: [lat, lon], zoom: int}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "bounds": self.bounds,
            "layers": [layer.to_dict() for layer in self.layers],
            "layer_count": len(self.layers),
        }

    @staticmethod
    def compute_bounds_from_geojson(geojson: Dict) -> Dict[str, Any]:
        """Compute map center and zoom from GeoJSON coordinates.

        Works with any geometry type (Point, LineString, Polygon, MultiLineString).
        Returns {center: [lat, lon], zoom: int, bbox: [min_lon, min_lat, max_lon, max_lat]}
        """
        all_coords: List[List[float]] = []
        features = geojson.get("features", [])
        for feature in features:
            geom = feature.get("geometry", {})
            coords = geom.get("coordinates", [])
            _extract_coords_recursive(coords, all_coords)

        if not all_coords:
            return {"center": [31.23, 121.47], "zoom": 12}  # fallback

        lons = [c[0] for c in all_coords]
        lats = [c[1] for c in all_coords]
        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)
        center_lat = (min_lat + max_lat) / 2
        center_lon = (min_lon + max_lon) / 2

        # Estimate zoom from span
        lat_span = max_lat - min_lat
        lon_span = max_lon - min_lon
        span = max(lat_span, lon_span)
        if span > 10:
            zoom = 6
        elif span > 5:
            zoom = 7
        elif span > 2:
            zoom = 8
        elif span > 1:
            zoom = 9
        elif span > 0.5:
            zoom = 10
        elif span > 0.2:
            zoom = 11
        elif span > 0.1:
            zoom = 12
        elif span > 0.05:
            zoom = 13
        else:
            zoom = 14

        return {
            "center": [center_lat, center_lon],
            "zoom": zoom,
            "bbox": [min_lon, min_lat, max_lon, max_lat],
        }
```

### 5.2 `tools/spatial_renderer.py`

#### 5.2.1 `render_spatial_map` 的函数签名和输入参数

实际工具类入口，文件范围: `tools/spatial_renderer.py:58-133`

```python
class SpatialRendererTool(BaseTool):
    name = "render_spatial_map"
    description = "Render spatial data as an interactive map"

    async def execute(self, **kwargs) -> ToolResult:
```

输入参数来自 `kwargs`:

- `data_source`
  - 默认 `"last_result"`
  - 可直接传 dict
- `pollutant`
- `title`
- `layer_type`
  - `"emission"`
  - `"concentration"`
  - `"points"`

#### 5.2.2 它如何处理 WKT geometry

WKT 解析函数，文件范围: `tools/spatial_renderer.py:19-55`

```python
def _parse_wkt_linestring(wkt_str: str) -> Optional[List[List[float]]]:
    """Parse WKT LINESTRING/MULTILINESTRING into [[lon, lat], ...] coordinates."""
```

支持:

- `LINESTRING (...)`
- `LINESTRING(...)`
- `MULTILINESTRING ((...), (...))`

处理流程:

1. 先判断是否为字符串。
2. 对 `LINESTRING`:
   - 定位最外层括号
   - 按 `,` 拆点
   - 每个点按空格拆成 `lon lat`
3. 对 `MULTILINESTRING`:
   - 用正则 `re.findall(r"\(([^()]+)\)", s)` 抽每组线
   - 再按 `,` 拆点
4. 解析失败返回 `None`
5. 少于 2 个点也返回 `None`

在 `_build_emission_map()` 中，geometry 解析顺序是:

1. 先尝试 `json.loads(...)`
2. 再尝试 `_parse_wkt_linestring(...)`
3. 都失败则跳过该 link

#### 5.2.3 当前支持哪些图层类型

自动检测逻辑，文件范围: `tools/spatial_renderer.py:135-145`

```python
if "concentration_grid" in data or "concentration_geojson" in data:
    return "concentration"
if "results" in data or "links" in data:
    return "emission"
if "receptors" in data:
    return "points"
return "emission"
```

当前支持状态:

- `emission`: ✅ 已实现，返回 legacy `map_data`
- `concentration`: ⚠️ 占位，`_build_concentration_map()` 直接 `return None`
- `points`: ⚠️ 占位，`_build_points_map()` 直接 `return None`

### 5.3 `core/router.py` 中 `last_spatial_data` 的保存逻辑

保存逻辑代码段，文件范围: `core/router.py:315-350`

```python
# === Save full spatial data BEFORE compaction ===
# memory.update() receives compacted data (results array stripped),
# so we must extract spatial data here while it's still complete.
spatial_data_saved = False
for tool_result_entry in state.execution.tool_results:
    # Unwrap nesting: entries are {tool_call_id, name, arguments, result: {...}}
    if not isinstance(tool_result_entry, dict):
        continue
    tool_name = tool_result_entry.get("name", "")
    if tool_name not in ("calculate_macro_emission", "calculate_micro_emission"):
        continue
    actual = tool_result_entry.get("result", tool_result_entry)
    if not isinstance(actual, dict) or not actual.get("success"):
        continue
    data = actual.get("data", {})
    if not isinstance(data, dict):
        continue
    results_list = data.get("results", [])
    if not results_list:
        continue
    has_geom = any(
        isinstance(r, dict) and r.get("geometry")
        for r in results_list[:5]
    )
    if has_geom:
        self.memory.fact_memory.last_spatial_data = data
        spatial_data_saved = True
        logger.info(f"Saved last_spatial_data: {len(results_list)} links with geometry")
        break

if not spatial_data_saved:
    # Clear stale spatial data if no new spatial results this turn
    # (Don't clear if user just did a non-spatial query in a follow-up turn)
    pass

self.memory.update(user_message, response.text, tool_calls_data, file_path, file_context)
```

与之对应的跨 turn 注入逻辑，文件范围: `core/router.py:635-669`

```python
# Tier 2: last_spatial_data (full results with geometry)
spatial = fact_mem.get("last_spatial_data")
if isinstance(spatial, dict) and spatial.get("results"):
    effective_arguments["_last_result"] = {"success": True, "data": spatial}
    injected = True
    logger.info(
        f"render_spatial_map: injected from memory spatial_data, "
        f"{len(spatial['results'])} links"
    )
```

---

## 第 6 部分：测试结构

### 6.1 `tests/` 目录所有测试文件及行数

```text
tests/__init__.py	0
tests/conftest.py	24
tests/test_api_chart_utils.py	82
tests/test_api_response_utils.py	68
tests/test_api_route_contracts.py	128
tests/test_available_results_tracking.py	58
tests/test_calculators.py	319
tests/test_config.py	79
tests/test_file_grounding_enhanced.py	179
tests/test_micro_excel_handler.py	30
tests/test_phase1b_consolidation.py	63
tests/test_router_contracts.py	799
tests/test_router_state_loop.py	342
tests/test_smoke_suite.py	70
tests/test_spatial_renderer.py	200
tests/test_spatial_types.py	142
tests/test_standardizer.py	94
tests/test_standardizer_enhanced.py	166
tests/test_task_state.py	165
tests/test_tool_dependencies.py	55
tests/test_trace.py	191
```

### 6.2 `pytest --co -q` 用例名称（仅收集）

执行结果:

```text
============================= test session starts ==============================
platform linux -- Python 3.13.9, pytest-9.0.2, pluggy-1.5.0
rootdir: /home/kirito/Agent1/emission_agent
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.12.1
collected 192 items

<Dir emission_agent>
  <Package tests>
    <Module test_api_chart_utils.py>
      <Function test_build_emission_chart_data_single_pollutant_preserves_curve_shape>
      <Function test_build_emission_chart_data_multi_pollutant_converts_speed_curve_to_curve>
      <Function test_extract_key_points_supports_direct_and_legacy_formats>
      <Function test_routes_module_keeps_chart_helper_names>
    <Module test_api_response_utils.py>
      <Function test_clean_reply_text_removes_json_blocks_and_extra_blank_lines>
      <Function test_friendly_error_message_handles_connection_failures>
      <Function test_normalize_and_attach_download_metadata_preserve_existing_shape>
      <Function test_routes_module_keeps_helper_names_and_health_route_registration>
    <Module test_api_route_contracts.py>
      <Function test_api_status_routes_return_expected_top_level_shape[asyncio]>
      <Function test_file_preview_route_detects_trajectory_csv_with_expected_warnings[asyncio]>
      <Function test_session_routes_create_list_and_history_backfill_legacy_download_metadata[asyncio]>
    <Module test_available_results_tracking.py>
      <Class TestAvailableResultsTracking>
        <Function test_initial_available_results_empty>
        <Function test_available_results_serializable>
        <Function test_available_results_update>
        <Function test_available_results_sorted_in_dict>
      <Class TestDependencyIntegration>
        <Function test_macro_emission_no_missing>
        <Function test_dispersion_missing_emission>
        <Function test_dispersion_satisfied_after_emission>
        <Function test_suggest_macro_for_emission_result>
        <Function test_render_spatial_map_no_prerequisites>
    <Module test_calculators.py>
      <Class TestVSPCalculator>
        <Function test_idle_opmode>
        <Function test_low_speed_opmode>
        <Function test_medium_speed_opmode>
        <Function test_high_speed_opmode>
        <Function test_vsp_calculation_passenger_car>
        <Function test_vsp_with_acceleration>
        <Function test_vsp_bin_range>
        <Function test_trajectory_vsp_batch>
        <Function test_invalid_vehicle_type_raises>
      <Class TestMicroEmissionCalculator>
        <Function test_simple_trajectory_calculation>
        <Function test_summary_statistics>
        <Function test_unknown_vehicle_type_error>
        <Function test_empty_trajectory_error>
        <Function test_year_to_age_group>
      <Class TestMacroEmissionCalculator>
        <Function test_load_emission_matrix_reuses_cached_dataframe>
        <Function test_query_emission_rate_matches_legacy_scan>
        <Function test_query_emission_rate_rebuilds_lookup_for_external_matrix>
        <Function test_calculate_matches_legacy_lookup_path>
      <Class TestEmissionFactorCalculator>
        <Function test_vehicle_type_mapping_complete>
        <Function test_pollutant_mapping_complete>
    <Module test_config.py>
      <Class TestConfigLoading>
        <Function test_config_creates_successfully>
        <Function test_config_singleton>
        <Function test_config_reset>
        <Function test_feature_flags_default_true>
        <Function test_feature_flag_override>
        <Function test_directories_created>
      <Class TestJWTSecretLoading>
        <Function test_jwt_secret_from_env>
        <Function test_auth_module_loads_dotenv_before_reading_secret>
        <Function test_jwt_default_is_not_production_safe>
    <Module test_file_grounding_enhanced.py>
      <Class TestValueFeatureAnalysis>
        <Function test_vehicle_speed_detection>
        <Function test_link_speed_detection>
        <Function test_acceleration_detection>
        <Function test_traffic_flow_detection>
        <Function test_fraction_detection>
        <Function test_negative_column_excluded>
        <Function test_non_numeric_column_skipped>
        <Function test_empty_dataframe>
        <Function test_all_nan_column>
      <Class TestMultiSignalTaskIdentification>
        <Function test_standard_micro_file>
        <Function test_standard_macro_file>
        <Function test_ambiguous_column_names_resolved_by_values>
        <Function test_unknown_columns_with_value_hints>
        <Function test_evidence_contains_all_signal_types>
        <Function test_no_signals_returns_unknown>
        <Function test_evidence_output_is_list_of_strings>
      <Class TestAnalyzeStructureIntegration>
        <Function test_structure_output_includes_evidence>
        <Function test_structure_output_backward_compatible>
    <Module test_micro_excel_handler.py>
      <Function test_read_trajectory_from_excel_strips_columns_without_stdout_noise>
    <Module test_phase1b_consolidation.py>
      <Function test_sync_llm_package_export_uses_purpose_assignment>
      <Function test_async_llm_service_uses_purpose_assignment>
      <Function test_async_llm_factory_uses_purpose_default_model>
      <Function test_async_llm_factory_preserves_explicit_model_override>
      <Function test_legacy_micro_skill_import_path_remains_available>
    <Module test_router_contracts.py>
      <Function test_build_memory_tool_calls_compacts_large_payloads_for_follow_up_turns>
      <Function test_router_memory_utils_match_core_router_compatibility_wrappers>
      <Function test_router_payload_utils_match_core_router_compatibility_wrappers>
      <Function test_router_render_utils_match_core_router_compatibility_wrappers>
      <Function test_router_synthesis_utils_match_core_router_compatibility_wrappers>
      <Function test_maybe_short_circuit_synthesis_covers_knowledge_failure_and_single_tool_paths>
      <Function test_build_synthesis_request_and_keyword_detection_preserve_llm_input_contract>
      <Function test_render_single_tool_success_formats_micro_results_with_key_sections>
      <Function test_filter_results_and_error_formatting_keep_retry_and_synthesis_signal>
      <Function test_extract_chart_data_prefers_explicit_chart_payload>
      <Function test_extract_chart_data_formats_emission_factor_curves_for_frontend>
      <Function test_extract_table_data_formats_macro_results_preview_for_frontend>
      <Function test_extract_table_data_formats_emission_factor_preview_for_frontend>
      <Function test_extract_table_data_formats_micro_results_preview_for_frontend>
      <Function test_extract_download_and_map_payloads_support_current_and_legacy_locations>
      <Function test_format_results_as_fallback_preserves_success_and_error_sections>
      <Function test_synthesize_results_calls_llm_with_built_request_and_returns_content[asyncio]>
      <Function test_synthesize_results_short_circuits_failures_without_calling_llm[asyncio]>
    <Module test_router_state_loop.py>
      <Function test_legacy_loop_unchanged[asyncio]>
      <Function test_state_loop_no_tool_call[asyncio]>
      <Function test_state_loop_with_tool_call[asyncio]>
      <Function test_state_loop_produces_trace[asyncio]>
      <Function test_clarification_on_unknown_file_type[asyncio]>
      <Function test_clarification_on_standardization_error[asyncio]>
      <Function test_state_loop_saves_full_spatial_data_before_memory_compaction[asyncio]>
      <Function test_render_spatial_map_injects_last_spatial_data_from_memory[asyncio]>
    <Module test_smoke_suite.py>
      <Function test_run_smoke_suite_writes_summary_with_expected_defaults>
    <Module test_spatial_renderer.py>
      <Function test_detect_layer_type_emission>
      <Function test_detect_layer_type_concentration>
      <Function test_detect_layer_type_points>
      <Function test_detect_layer_type_fallback>
      <Function test_build_emission_map_basic>
      <Function test_build_emission_map_no_geometry>
      <Function test_build_emission_map_pollutant_selection>
      <Function test_build_emission_map_auto_pollutant>
      <Function test_build_emission_map_emission_intensity>
      <Function test_execute_last_result>
      <Function test_execute_no_last_result>
      <Function test_execute_direct_data>
      <Function test_build_emission_map_string_geometry>
      <Function test_parse_wkt_linestring_basic>
      <Function test_parse_wkt_linestring_no_space>
      <Function test_parse_wkt_linestring_many_points>
      <Function test_parse_wkt_multilinestring>
      <Function test_parse_wkt_returns_none_for_single_point>
      <Function test_parse_wkt_returns_none_for_non_wkt>
      <Function test_parse_wkt_returns_none_for_non_string>
      <Function test_build_emission_map_wkt_geometry>
      <Function test_build_emission_map_wkt_no_space>
    <Module test_spatial_types.py>
      <Function test_spatial_layer_to_dict>
      <Function test_spatial_layer_excludes_none>
      <Function test_spatial_data_package_to_dict>
      <Function test_compute_bounds_from_geojson>
      <Function test_compute_bounds_empty>
      <Function test_compute_bounds_multilinestring>
      <Function test_extract_coords_recursive_nested>
    <Module test_standardizer.py>
      <Class TestVehicleStandardization>
        <Function test_exact_english>
        <Function test_exact_chinese>
        <Function test_alias_chinese>
        <Function test_case_insensitive>
        <Function test_unknown_returns_none>
        <Function test_empty_returns_none>
        <Function test_suggestions_non_empty>
      <Class TestPollutantStandardization>
        <Function test_exact_english>
        <Function test_case_insensitive>
        <Function test_chinese_name>
        <Function test_unknown_returns_none>
        <Function test_suggestions_non_empty>
      <Class TestColumnMapping>
        <Function test_micro_speed_column>
        <Function test_empty_columns>
    <Module test_standardizer_enhanced.py>
      <Class TestStandardizationResult>
        <Function test_vehicle_detailed_exact>
        <Function test_vehicle_detailed_alias>
        <Function test_vehicle_detailed_abstain>
        <Function test_vehicle_detailed_to_dict>
      <Class TestSeasonStandardization>
        <Function test_chinese_summer>
        <Function test_english_winter>
        <Function test_empty_returns_default>
        <Function test_unknown_returns_default>
      <Class TestRoadTypeStandardization>
        <Function test_chinese_freeway>
        <Function test_english_freeway>
        <Function test_chinese_expressway>
        <Function test_empty_returns_default>
        <Function test_english_local>
      <Class TestExecutorStandardizationRecords>
        <Function test_standardize_returns_tuple>
        <Function test_season_standardized>
        <Function test_road_type_standardized>
        <Function test_abstain_raises_with_suggestions>
    <Module test_task_state.py>
      <Function test_initialize_without_file>
      <Function test_initialize_with_file>
      <Function test_initialize_with_memory>
      <Function test_valid_transitions>
      <Function test_invalid_transition_raises>
      <Function test_should_stop_at_terminal[DONE]>
      <Function test_should_stop_at_terminal[NEEDS_CLARIFICATION]>
      <Function test_should_stop_at_max_steps>
      <Function test_to_dict_serializable>
      <Function test_update_file_context>
    <Module test_tool_dependencies.py>
      <Function test_no_prerequisites>
      <Function test_dispersion_requires_emission>
      <Function test_suggest_prerequisite>
      <Function test_suggest_prerequisite_unknown>
      <Function test_all_met>
      <Function test_render_spatial_map_no_prereqs>
      <Function test_get_tool_provides>
      <Function test_get_tool_provides_unknown>
      <Function test_query_emission_factors_provides>
    <Module test_trace.py>
      <Class TestTraceStep>
        <Function test_to_dict_excludes_none>
        <Function test_to_dict_includes_set_fields>
      <Class TestTrace>
        <Function test_start_creates_with_timestamp>
        <Function test_record_appends_step>
        <Function test_record_auto_increments_index>
        <Function test_finish_sets_end_time_and_duration>
        <Function test_to_dict_serializable>
        <Function test_to_user_friendly_file_grounding>
        <Function test_to_user_friendly_tool_execution_success>
        <Function test_to_user_friendly_tool_execution_error>
        <Function test_to_user_friendly_skips_state_transition>
        <Function test_to_user_friendly_clarification>
        <Function test_full_workflow_trace>

=============================== warnings summary ===============================
api/main.py:73
  /home/kirito/Agent1/emission_agent/api/main.py:73: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
  
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
    @app.on_event("startup")

../../miniconda3/lib/python3.13/site-packages/fastapi/applications.py:4573
../../miniconda3/lib/python3.13/site-packages/fastapi/applications.py:4573
  /home/kirito/miniconda3/lib/python3.13/site-packages/fastapi/applications.py:4573: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
  
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
    return self.router.on_event(event_type)

api/main.py:88
  /home/kirito/Agent1/emission_agent/api/main.py:88: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
  
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
    @app.on_event("shutdown")

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
========================= 192 tests collected in 0.93s =========================
```

### 6.3 现有 calculator 测试的组织模式

依据:

- `tests/test_calculators.py`
- `tests/conftest.py`

组织模式:

- 所有 calculator 测试集中在单文件 `tests/test_calculators.py`
- 按类分组:
  - `TestVSPCalculator`
  - `TestMicroEmissionCalculator`
  - `TestMacroEmissionCalculator`
  - `TestEmissionFactorCalculator`
- 每个类使用 `setup_method()` 创建 calculator 实例
- 没有专门的 calculator fixture；共享 fixture 只有 `conftest.py` 里的 `autouse` 环境隔离
- `conftest.py` 的 `autouse` fixture 会:
  - 注入假的 `QWEN_API_KEY`
  - 注入假的 `QWEN_BASE_URL`
  - 注入测试用 `JWT_SECRET_KEY`
  - 每个测试前后 `reset_config()`
- mock / patch 策略:
  - `monkeypatch.setattr(pd, "read_csv", fake_read_csv)` 用于矩阵加载缓存测试
  - `monkeypatch.setattr(legacy_calc, "_query_emission_rate", legacy_calc._query_emission_rate_scan)` 用于优化路径与 legacy 路径对比
- 数据策略:
  - 大多数测试直接使用仓库内置 CSV 数据或最小内嵌样本
  - 只有缓存/lookup 层面测试会 mock I/O

---

## 第 7 部分：依赖与环境

### 7.1 当前依赖

#### 7.1.1 根项目 `requirements.txt`

```text
openai>=1.0.0
python-dotenv>=1.0.0
click>=8.0.0
rich>=13.0.0
pandas>=2.0.0
fastapi>=0.100.0
uvicorn>=0.22.0
python-multipart>=0.0.6
openpyxl>=3.0.0
httpx>=0.24.0
pyyaml>=6.0
faiss-cpu>=1.7.0
numpy>=1.24.0
dashscope>=1.14.0
passlib[bcrypt]>=1.7.4
PyJWT>=2.8.0
aiosqlite>=0.16.0
email-validator>=1.3.0
bcrypt<4.1
shapely>=2.0.0
geopandas>=0.13.0
fiona>=1.9.0
```

#### 7.1.2 `pyproject.toml`

- `pyproject.toml` 没有维护依赖列表
- 仅包含:
  - 项目元数据
  - `requires-python = ">=3.10"`
  - pytest 配置
  - ruff 配置

#### 7.1.3 surrogate 子目录 `ps-xgb-aermod-rline-surrogate/requirements.txt`

```text
numpy
pandas
geopandas
shapely
pyproj
xgboost
scikit-learn
matplotlib
seaborn
scipy
```

### 7.2 指定包安装状态

当前环境检测结果:

```text
pyproj True
xgboost False
scipy False
```

结论:

- `pyproj`: ✅ 已安装
- `xgboost`: ❌ 未安装
- `scipy`: ❌ 未安装

### 7.3 Python 版本

```text
3.13.9 | packaged by Anaconda, Inc. | (main, Oct 21 2025, 19:16:10) [GCC 11.2.0]
```

---

## 第 8 部分：`PHASE2_EXPLORATION_REPORT.md` 摘要

文件状态: ✅ 存在  
目标章节: `## 3. Dispersion Model Analysis`

### 8.1 3.1 执行流程伪代码

报告结论与当前 `mode_inference.py` 基本一致:

```text
1. 读道路 Shapefile + 排放 CSV，按路名合并
2. WGS84 -> UTM 51N，并整体平移到局部原点
3. 从 data_time 派生时序字段，把 nox 转成 nox_g_m_s2
4. 生成道路缓冲区、近路受体和背景网格受体
5. 对受体去重
6. 把道路切分为 10m 线源段并计算方位角
7. 按所有时刻复制线源段并挂接每小时排放强度
8. 读取 .SFC 气象，构造 Date，分类 Stab_Class
9. 加载 12 个 XGBoost surrogate 模型
10. 构造 sources_re 与 models 字典
11. 调用 predict_time_series_xgb() 输出 time_series_conc
```

### 8.2 3.2 输入格式

报告摘要:

- 道路输入: Shapefile，至少要有 `NAME_1` 与 `geometry`
- 排放输入: CSV，至少要有 `NAME/NAME_1`、`data_time`、`nox`、`length`
- 气象输入: AERMOD `.SFC`
- 坐标输入假设: WGS84，经代码转换到 UTM 51N

与当前代码对照:

- ✅ 一致

### 8.3 3.3 可复用函数列表

报告列出的可复用函数:

- `convert_to_utm(lon, lat)`，需参数化 CRS/zone
- `make_rectangular_buffer(...)`
- `generate_receptors_custom_offset(...)`，需去掉内嵌 plotting side effect
- `split_polyline_by_interval_with_angle(...)`
- `read_sfc(path)`
- `load_model(path)`
- `predict_time_series_xgb(...)`，需从顶层全局假设中解耦

与当前代码对照:

- ✅ 一致

### 8.4 3.4 硬编码依赖清单

报告提到的主要硬编码点:

- 文件路径常量 `ROAD_SHP/EMISSION_CSV/MET_SFC/MODEL_DIR`
- `WGS84 -> UTM Zone 51N`
- 用 `min_x/min_y` 平移到局部原点
- `7m` 道路宽度假设
- 仅 `NOx`
- 受体生成参数与 10m segmentation
- `plt.show()` 与固定显示窗口
- 只加载 `_M` 模型
- `MODEL_DIR="models"` 与当前仓库子目录布局不一致
- `sources.reshape(len(met), len(base_midpoints_df), 4)` 依赖严格对齐

与当前代码对照:

- ✅ 一致

### 8.5 3.5 输出格式

报告摘要:

- 输出是 `predict_time_series_xgb()` 返回的 `pd.DataFrame`
- 列:
  - `Date`
  - `Receptor_ID`
  - `Receptor_X`
  - `Receptor_Y`
  - `Conc`
- 坐标是局部平移后的米制坐标，不是 WGS84
- 结果只保存在变量 `time_series_conc` 中，没有写文件

与当前代码对照:

- ✅ 一致

### 8.6 3.6 模型文件命名规则

报告摘要:

- 模型目录有 3 套粗糙度高度:
  - `model_z=0.05`
  - `model_z=0.5`
  - `model_z=1`
- 每套 12 个文件
- 名称由:
  - 稳定类
  - 风向正负侧 (`x0`, `x-1`)
  - roughness 后缀 (`L`, `M`, `H`)
 组成

当前仓库验证:

- ✅ 一致
- 当前实际大小:
  - `model_z=0.05`: `51,902,763 bytes`
  - `model_z=0.5`: `48,307,193 bytes`
  - `model_z=1`: `48,300,376 bytes`

### 8.7 差异标注

结论:

- 对 `PHASE2_EXPLORATION_REPORT.md` 第 3 节与当前 `mode_inference.py` 的比对结果是: **没有发现实质性不一致**

补充说明:

- 当前代码中确实存在多处未使用 import，报告未专门列出:
  - `product`
  - `math`
  - `shutil`
  - `griddata`
  - `Point`
  - `train_test_split`
  - `mean_squared_error`
  - `r2_score`
  - `mean_absolute_error`
  - `StandardScaler`
- 这不影响第 3 节主结论，但说明该脚本仍混有训练/实验残留依赖

---

## 发现与风险

1. `mode_inference.py` import 即执行，无法安全作为库复用；Sprint 8/9 若要接入，需要先拆出纯函数入口。
2. 根项目当前环境里 `xgboost` 和 `scipy` 未安装，surrogate 推理脚本在此环境下不可直接运行；而 surrogate 子项目 requirements 明确需要它们。
3. `MODEL_DIR = "models"` 与实际模型文件布局不匹配。脚本硬编码加载根目录下的 `_M` 文件，但仓库实际文件在 `models/model_z=.../` 子目录。
4. `config/meteorology_presets.yaml` 不存在，说明“气象预设”目前没有进入统一配置体系；surrogate 仍完全依赖 `.SFC` 原始文件和硬编码列名/阈值。
5. `mode_inference.py` 坐标链路硬编码为 `WGS84 -> UTM 51N -> local origin`，且输出坐标没有 CRS 元数据，后续若要接入前端地图，必须补充反投影与 CRS 显式标记。
6. `tools/spatial_renderer.py` 虽然导入了 `SpatialLayer` / `SpatialDataPackage`，但当前实际返回的还是 legacy `map_data`，并未真正使用新的空间类型系统。
7. `tools/spatial_renderer.py` 的 `concentration` / `points` 分支仍是占位；Sprint 9 若做 `calculate_dispersion`，地图渲染侧还需要补齐浓度图层实现。
8. `tools/macro_emission.py` 仍依赖 `skills.macro_emission.excel_handler`，说明工具层尚未完全摆脱 legacy `skills/` 边界。
9. `tools/macro_emission.py` 的 `output_file` 分支使用 `result["data"].get("links", [])`，但 calculator 返回的是 `results`，这是一个现存输出路径风险点。
10. `calculators/` 没有统一基类；如果 Sprint 9 要新增 `DispersionCalculator`，建议在重构前先明确统一接口契约，否则 tool 层会继续承担过多适配逻辑。
