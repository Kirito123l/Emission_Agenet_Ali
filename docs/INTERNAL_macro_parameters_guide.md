# 宏观排放计算参数详解

**版本**: v1.0
**日期**: 2026-03-08
**内部文档**

---

## 1. 参数层级结构

```
用户输入参数（自然语言）
    ↓
LLM解析 → 标准化
    ↓
计算器参数（structured）
    ↓
MOVES查询参数
    ↓
最终计算使用的字段
```

---

## 2. 计算器层参数

### 2.1 calculate() 方法 - 入口参数

**文件**: `calculators/macro_emission.py:75`

```python
def calculate(
    links_data: List[Dict],      # 必需 ✅
    pollutants: List[str],       # 必需 ✅
    model_year: int,             # 必需 ✅
    season: str,                 # 必需 ✅
    default_fleet_mix: Dict = None  # 可选（有默认值）
) -> Dict
```

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `links_data` | ✅ | - | 路段数据列表 |
| `pollutants` | ✅ | - | 污染物列表，如 ["CO2", "NOx"] |
| `model_year` | ✅ | - | 车型年份 (1995-2025) |
| `season` | ✅ | - | 季节 ("春季"/"夏季"/"秋季"/"冬季") |
| `default_fleet_mix` | ❌ | 见下方 | 默认车队组成 |

### 2.2 default_fleet_mix 默认值

```python
DEFAULT_FLEET_MIX = {
    "Passenger Car": 70.0,                  # 70%
    "Passenger Truck": 20.0,                 # 20%
    "Light Commercial Truck": 5.0,          # 5%
    "Transit Bus": 3.0,                     # 3%
    "Combination Long-haul Truck": 2.0       # 2%
}
```

---

## 3. 路段数据字段详细说明

### 3.1 最终计算使用的字段

**必需字段**（无默认值，必须提供）:

| 字段名 | 类型 | 示例 | 计算用途 |
|--------|------|------|----------|
| `link_length_km` | float | `3.0` | 路段长度，用于计算行驶时间和单位排放率 |
| `traffic_flow_vph` | int | `1000` | 交通流量，用于计算各车型车流量 |
| `avg_speed_kph` | float | `50.0` | 平均速度，用于计算行驶时间和单位转换 |

**可选字段**（有默认值或自动生成）:

| 字段名 | 类型 | 默认值 | 生成逻辑 |
|--------|------|--------|----------|
| `fleet_mix` | Dict | `DEFAULT_FLEET_MIX` | ①优先使用路段自己的<br>②其次使用全局参数<br>③最后使用默认值 |
| `link_id` | str | `Link_1, Link_2...` | ①保留原始ID（如"Main_St"）<br>②空值自动生成顺序ID |

### 3.2 字段使用流程图

```
┌─────────────────────────────────────────────────────┐
│                    输入数据                             │
├─────────────────────────────────────────────────────┤
│  link_length_km  ← 必需，用于计算                           │
│  traffic_flow_vph ← 必需，用于计算各车型车流量                 │
│  avg_speed_kph   ← 必需，用于计算行驶时间和单位转换             │
│  fleet_mix       ← 可选，默认使用 DEFAULT_FLEET_MIX          │
│  link_id         ← 可选，空值自动生成 Link_1, Link_2...       │
└─────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────┐
│                    计算过程                             │
├─────────────────────────────────────────────────────┤
│  1. 单位转换                                              │
│     length_mi = link_length_km × 0.621371                   │
│     speed_mph = avg_speed_kph × 0.621371                     │
│                                                          │
│  2. 车队组成处理                                          │
│     获取 fleet_mix（路段 > 全局 > 默认）                   │
│     归一化百分比到 100%                                     │
│                                                          │
│  3. 分车型计算排放                                         │
│     for 每个车型:                                           │
│         vehicles_per_hour = traffic_flow_vph × percentage   │
│         for 每个污染物:                                       │
│             查询 MOVES 排放率 (g/hr)                       │
│             emission_g_per_sec = emission_rate / 3600      │
│             travel_time_sec = (length_mi / speed_mph) × 3600│
│             emission_g = emission_g_per_sec × travel_time_sec │
│             emission_kg = emission_g × vehicles_per_hour / 1000│
│                                                          │
│  4. 汇总统计                                              │
│     按污染物累加总排放                                       │
│     计算单位排放率 (g/veh-km)                             │
└─────────────────────────────────────────────────────┘
```

---

## 4. MOVES 查询参数

### 4.1 _load_emission_matrix() - 加载数据

**参数**:
- `season`: 季节字符串 ("春季"/"夏季"/"秋季"/"冬季")
- **作用**: 决定加载哪个CSV文件

**季节映射**:
```python
SEASON_CODES = {
    "春季": 4,   → atlanta_2025_4_75_65.csv
    "夏季": 7,   → atlanta_2025_7_80_60.csv
    "秋季": 4,   → atlanta_2025_4_75_65.csv
    "冬季": 1,   → atlanta_2025_1_35_60 .csv
}
```

### 4.2 _query_emission_rate() - 查询排放率

**参数**:
- `matrix`: MOVES排放矩阵DataFrame
- `source_type`: int (车型ID)
- `pollutant_id`: int (污染物ID)
- `model_year`: int (年龄组)

**查询条件**:
```python
matrix[
    (matrix['opModeID'] == 300) &      # 平均opMode
    (matrix['pollutantID'] == pollutant_id) &
    (matrix['sourceTypeID'] == source_type) &
    (matrix['modelYearID'] == model_year)
]
```

**MOVES内部参数**:

| 参数 | 说明 | 值/范围 |
|------|------|---------|
| opModeID | 运行模式ID | 300 (平均值) |
| sourceTypeID | 车型ID | 21=Passenger Car, 32=Light Commercial Truck等 |
| modelYearID | 车型年龄组 | 1=0-1年, 5=10-19年, 9=20+年 |
| pollutantID | 污染物ID | 90=CO2, 3=NOx, 110=PM2.5等 |

---

## 5. Excel 文件列要求

### 5.1 从 Excel 读取时需要的列

**文件**: `skills/macro_emission/excel_handler.py`

**必需列**（必须有，否则报错）:

| 列名 | 可选别名 | 示例 | 说明 |
|------|---------|------|------|
| 长度 | length, link_length, length_km | 3.0 | 路段长度 |
| 流量 | traffic_flow, flow, volume | 1000 | 交通流量 |
| 速度 | speed, avg_speed | 50.0 | 平均速度 |

**可选列**:

| 列名 | 可选别名 | 示例 | 说明 |
|------|---------|------|------|
| 车队组成 | fleet_mix, vehicle_composition | {"Passenger Car": 70} | 车队组成 |
| 路段ID | link_id, id, road_id, segment_id | "Main_St" | 路段标识 |

### 5.2 Excel 列名自动映射

```python
field_mapping = {
    "link_length_km": ["length", "link_length", "length_km", "road_length"],
    "traffic_flow_vph": ["traffic_volume_veh_h", "traffic_flow", "flow", "volume", "traffic_volume"],
    "avg_speed_kph": ["avg_speed_kmh", "speed", "avg_speed", "average_speed"],
    "fleet_mix": ["vehicle_composition", "vehicle_mix", "composition", "fleet_composition"],
    "link_id": ["id", "road_id", "segment_id"]
}
```

---

## 6. 完整的参数依赖关系

### 6.1 参数来源层级

```
Level 1: 用户/文件输入（最原始）
    ├─ link_length_km  ← 直接使用
    ├─ traffic_flow_vph ← 直接使用
    ├─ avg_speed_kph    ← 直接使用
    ├─ fleet_mix       ← 可选，有默认值
    └─ link_id         ← 可选，自动生成

Level 2: 全局参数
    ├─ pollutants      ← 必需，由用户提供
    ├─ model_year     ← 必需，由用户提供
    ├─ season         ← 必需，由用户提供
    └─ default_fleet_mix ← 可选，覆盖默认值

Level 3: 系统默认值
    └─ DEFAULT_FLEET_MIX ← 最终兜底

Level 4: MOVES内部参数（固定）
    ├─ opModeID = 300
    ├─ modelYearID (根据model_year映射)
    ├─ season (转换为季节代码)
    └─ 各类映射表（车型→sourceTypeID等）
```

### 6.2 参数传递链

```
用户输入
    ↓
LLM 解析/标准化
    ↓
Tool._execute()
    ├─ pollutants: kwargs["pollutants"] ✅
    ├─ model_year: kwargs["model_year"] ✅
    ├─ season: kwargs["season"] ✅
    ├─ links_data: kwargs["links_data"] ✅
    └─ default_fleet_mix: kwargs["default_fleet_mix"] ❌
    ↓
Tool._fix_common_errors()
    ├─ 字段名修复
    ├─ link_id 自动生成
    └─ 车队组成格式转换
    ↓
Tool._apply_global_fleet_mix()
    ├─ 应用全局 fleet_mix
    └─ 标准化车型名称
    ↓
Tool._fill_missing_link_fleet_mix()
    ├─ 填充缺失的 fleet_mix
    └─ 使用 effective_default_fleet_mix
    ↓
Calculator.calculate()
    ├─ 使用处理后的 links_data
    ├─ 使用 effective_default_fleet_mix
    ├─ 使用 pollutants, model_year, season
    └─ 查询 MOVES 数据
```

---

## 7. 实际计算示例

### 7.1 最小输入示例

**用户输入**:
```
计算3km路段，流量1000辆/小时，速度50km/h的CO2排放，2020年夏季
```

**LLM解析**:
```json
{
  "links_data": [
    {
      "link_length_km": 3.0,
      "traffic_flow_vph": 1000,
      "avg_speed_kph": 50.0
    }
  ],
  "pollutants": ["CO2"],
  "model_year": 2020,
  "season": "夏季"
}
```

**计算时自动添加**:
```json
{
  "link_id": "Link_1",                    // 自动生成
  "fleet_mix": {                         // 使用默认值
    "Passenger Car": 70.0,
    "Passenger Truck": 20.0,
    "Light Commercial Truck": 5.0,
    "Transit Bus": 3.0,
    "Combination Long-haul Truck": 2.0
  }
}
```

### 7.2 完整输入示例

**Excel文件内容**:

| 长度 | 流量 | 速度 | 车队组成 | 路段ID |
|------|------|------|----------|--------|
| 3.0 | 1000 | 50 | {"Passenger Car": 80, "Bus": 20} | Main_St |
| 5.0 | 800 | 60 | {"Passenger Car": 60, "Truck": 40} | Broad_Ave |

**用户指定全局参数**:
```
污染物: NOx, PM2.5
年份: 2025
季节: 冬季
```

**计算过程**:
1. Main_St: 使用自己的车队组成 (80% Car, 20% Bus)
2. Broad_Ave: 使用自己的车队组成 (60% Car, 40% Truck)
3. 两路段都查询冬季MOVES矩阵的NOx和PM2.5排放率

---

## 8. 关键计算公式详解

### 8.1 单车型单车排放量计算

```python
# 1. 获取排放率（从MOVES数据）
emission_rate_g_per_hr = query_emission_rate(
    source_type_id=21,      # Passenger Car
    pollutant_id=90,       # CO2
    model_year_id=5,        # 10-19年车龄
    season_code=7          # 夏季
)
# 返回: 123.456 g/hr

# 2. 单位转换: g/hr → g/s
emission_rate_g_per_sec = 123.456 / 3600
# 返回: 0.034293 g/s

# 3. 计算行驶时间
length_km = 3.0
avg_speed_kph = 50.0
travel_time_sec = (3.0 / 50.0) × 3600
# 返回: 216.0 秒

# 4. 单车通过路段的排放量
emission_g = 0.034293 × 216.0
# 返回: 7.407 g

# 5. 该车型的车流量
percentage = 70% (from fleet_mix)
traffic_flow_vph = 1000
vehicles_per_hour = 1000 × 0.70 = 700

# 6. 路段每小时总排放 (该车型)
emission_kg_per_hr = 7.407 × 700 / 1000
# 返回: 5.185 kg/h
```

### 8.2 完整计算流程（含多车型）

```python
# 输入
link = {
    "link_length_km": 3.0,
    "traffic_flow_vph": 1000,
    "avg_speed_kph": 50.0,
    "fleet_mix": {
        "Passenger Car": 70,
        "Passenger Truck": 30
    }
}

# 计算每种车型
emissions_by_vehicle = {}

# Passenger Car (70%)
vehicles_per_hour = 1000 × 0.70 = 700
emission_Car = 计算单车排放 × 700
emissions_by_vehicle["Passenger Car"] = {
    "CO2": 5.185,     # kg/h
    "NOx": 0.028      # kg/h
}

# Passenger Truck (30%)
vehicles_per_hour = 1000 × 0.30 = 300
emission_Truck = 计算单车排放 × 300
emissions_by_vehicle["Passenger Truck"] = {
    "CO2": 3.124,     # kg/h
    "NOx": 0.156      # kg/h
}

# 汇总总排放
total_emissions = {
    "CO2": 5.185 + 3.124 = 8.309 kg/h,
    "NOx": 0.028 + 0.156 = 0.184 kg/h
}
```

---

## 9. 单位转换总结

### 9.1 输入 → 计算

| 参数 | 输入单位 | MOVES查询单位 | 计算使用单位 |
|------|---------|--------------|-------------|
| 路段长度 | km | - | mile (内部转换) |
| 速度 | km/h | mph | mph (内部转换) |
| 车流量 | 辆/小时 | - | 辆/小时 |

### 9.2 MOVES → 输出

| 参数 | MOVES单位 | 输出单位 |
|------|-----------|---------|
| 排放率 | g/hr | - |
| 排放量 | - | kg/h |

---

## 10. 快速参考：用户输入示例

### 10.1 最小需求

```
"计算3km路段，流量1000辆/小时，速度50km/h的CO2排放"
```

**必需参数**:
- 路段长度: 3km
- 流量: 1000辆/小时
- 速度: 50km/h
- 污染物: CO2
- 年份: 默认2020
- 季节: 默认夏季

**自动提供**:
- 车队组成: 默认值
- 路段ID: Link_1

### 10.2 多路段输入

```
"两个路段：
第一段长3km，流量1000，速度50
第二段长5km，流量800，速度60"
```

**LLM解析结果**:
```json
{
  "links_data": [
    {
      "link_length_km": 3.0,
      "traffic_flow_vph": 1000,
      "avg_speed_kph": 50.0
    },
    {
      "link_length_km": 5.0,
      "traffic_flow_vph": 800,
      "avg_speed_kph": 60.0
    }
  ],
  "pollutants": ["CO2"],
  "model_year": 2020,
  "season": "夏季"
}
```

### 10.3 完整指定输入

```
"计算以下路段的CO2、NOx和PM2.5排放：
- 主街：长3km，流量1000辆/小时，速度50km/h
- 宽街：长5km，流量800辆/小时，速度60km/h
车型年份2025年，冬季，
车队组成：80%小汽车，20%公交车"
```

---

## 附录：参数检查清单

### A.1 必需参数检查

- [ ] `links_data` 非空列表
- [ ] 每个路段包含 `link_length_km`
- [ ] 每个路段包含 `traffic_flow_vph`
- [ ] 每个路段包含 `avg_speed_kph`
- [ ] `pollutants` 非空列表
- [ ] `model_year` 在有效范围 (1995-2025)
- [ ] `season` 是有效季节

### A.2 可选参数

- [ ] `fleet_mix` (每路段或全局)
- [ ] `link_id` (每路段)
- [ ] `default_fleet_mix` (全局覆盖)

### A3. MOVES数据要求

- [ ] 数据文件存在 (`data/macro_emission/`)
- [ ] 季节映射正确
- [ ] 车型映射有效 (sourceTypeID)
- [ ] 污染物映射有效 (pollutantID)
- [ ] 年份映射有效 (modelYearID)

---

**文档结束**

*最后更新: 2026-03-08*
