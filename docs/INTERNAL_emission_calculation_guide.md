# 路段排放计算技术文档

**版本**: v1.0
**日期**: 2026-03-08
**内部文档** - 仅供团队内部使用

---

## 目录

1. [系统架构](#1-系统架构)
2. [宏观排放计算（MOVES-Matrix方法）](#2-宏观排放计算moves-matrix方法)
3. [微观排放计算（轨迹数据方法）](#3-微观排放计算轨迹数据方法)
4. [MOVES数据结构](#4-moves数据结构)
5. [参数标准化](#5-参数标准化)
6. [API接口](#6-api接口)
7. [技术细节](#7-技术细节)

---

## 1. 系统架构

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                         前端 (Web)                          │
│  - 用户输入自然语言                                            │
│  - 显示计算结果（图表、表格、下载）                              │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP/WebSocket
                         ↓
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI (routes.py)                    │
│  - 请求路由                                                   │
│  - 会话管理                                                   │
│  - 文件上传/下载                                              │
│  - 流式响应                                                   │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│                      Skill层 (skills/)                       │
│  - 宏观排放: skills/macro_emission/                          │
│  - 微观排放: skills/micro_emission/                          │
│  - 业务逻辑封装                                               │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│                      Tool层 (tools/)                         │
│  - 宏观工具: tools/macro_emission.py                          │
│  - 微观工具: tools/micro_emission.py                          │
│  - 参数标准化                                                 │
│  - 错误处理                                                   │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│                   Calculator层 (calculators/)                 │
│  - 宏观计算器: calculators/macro_emission.py                 │
│  - 微观计算器: calculators/micro_emission.py                 │
│  - 排放因子: calculators/emission_factors.py                   │
│  - 纯计算逻辑                                                 │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│                    数据层 (data/)                            │
│  - MOVES排放矩阵数据                                          │
│  - 排放因子查询数据                                            │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 数据流向

```
用户输入 → LLM解析 → 标准化 → 计算 → 结果生成
    ↓         ↓         ↓        ↓         ↓
自然语言   参数验证  单位转换  MOVES查询  Excel导出
文件上传   字段映射  ID生成   VSP计算   图表渲染
```

---

## 2. 宏观排放计算（MOVES-Matrix方法）

### 2.1 计算原理

宏观排放计算使用 **MOVES-Matrix** 方法，基于以下物理模型：

#### 核心公式

```
路段每小时总排放 = Σ (各车型单车排放量 × 该车型车流量) / 1000

其中：
单车排放量(g) = 排放率(g/s) × 行驶时间(s)

排放率(g/s) = MOVES排放率(g/hr) / 3600

行驶时间(s) = (路段长度km / 平均速度km/h) × 3600
```

#### 单位转换

| 参数 | 输入单位 | 计算单位 | MOVES单位 |
|------|---------|---------|-----------|
| 路段长度 | km | mile | - |
| 平均速度 | km/h | mph | - |
| 排放率 | - | g/s | g/hr |
| 排放量 | - | kg/h | g |

### 2.2 计算器代码结构

**文件**: `calculators/macro_emission.py`

#### 核心方法

```python
class MacroEmissionCalculator:
    def calculate(self, links_data, pollutants, model_year, season):
        """
        Args:
            links_data: List[Dict] - 路段数据列表
                {
                    "link_id": str,              # 路段ID
                    "link_length_km": float,      # 路段长度(km)
                    "traffic_flow_vph": int,      # 交通流量(辆/小时)
                    "avg_speed_kph": float,       # 平均速度(km/h)
                    "fleet_mix": Dict            # 车队组成
                }
            pollutants: List[str] - 污染物列表，如 ["CO2", "NOx"]
            model_year: int - 车型年份 (1995-2025)
            season: str - 季节 ("春季"/"夏季"/"秋季"/"冬季")
        """
```

#### 计算流程

```python
# 1. 加载排放矩阵
emission_matrix = self._load_emission_matrix(season)

# 2. 对每个路段进行计算
for link in links_data:
    # 2.1 单位转换
    length_mi = link["link_length_km"] * 0.621371  # km → mile
    speed_mph = link["avg_speed_kph"] * 0.621371    # km/h → mph

    # 2.2 车队组成标准化（确保百分比总和为100%）
    total_percentage = sum(fleet_mix.values())
    if abs(total_percentage - 100.0) > 0.01:
        for vehicle in fleet_mix:
            fleet_mix[vehicle] = (fleet_mix[vehicle] / total_percentage) * 100.0

    # 2.3 对每个车型计算排放
    for vehicle_name, percentage in fleet_mix.items():
        source_type_id = VEHICLE_TO_SOURCE_TYPE[vehicle_name]
        vehicles_per_hour = traffic_flow_vph * percentage / 100

        for pollutant in pollutants:
            # 查询MOVES排放率
            emission_rate = self._query_emission_rate(
                matrix, source_type_id, pollutant_id, model_year
            )

            # 计算该车型在该路段的排放
            emission_rate_g_per_sec = emission_rate / 3600
            travel_time_sec = (link_length_km / avg_speed_kph) * 3600
            emission_g_per_veh = emission_rate_g_per_sec * travel_time_sec
            emission_kg_per_hr = emission_g_per_veh * vehicles_per_hour / 1000

            # 累加到总排放
            total_emissions_kg_per_hr[pollutant] += emission_kg_per_hr

    # 2.4 计算单位排放率
    emission_rate_g_per_veh_km = total_emissions_kg * 1000 / link_length_km / traffic_flow
```

### 2.3 MOVES数据查询

```python
def _query_emission_rate(self, matrix, source_type, pollutant_id, model_year):
    """
    查询条件：
    - opModeID = 300 (平均值)
    - pollutantID = 污染物ID (如90=CO2)
    - sourceTypeID = 车型ID (如21=Passenger Car)
    - modelYearID = 年龄组 (如5=10-19年)
    """
    result = matrix[
        (matrix['opModeID'] == 300) &
        (matrix['pollutantID'] == pollutant_id) &
        (matrix['sourceTypeID'] == source_type) &
        (matrix['modelYearID'] == model_year)
    ]
    return float(result.iloc[0]['em'])
```

### 2.4 车型映射

```python
VEHICLE_TO_SOURCE_TYPE = {
    "Motorcycle": 11,
    "Passenger Car": 21,
    "Passenger Truck": 31,
    "Light Commercial Truck": 32,
    "Intercity Bus": 41,
    "Transit Bus": 42,
    "School Bus": 43,
    "Refuse Truck": 51,
    "Single Unit Short-haul Truck": 52,
    "Single Unit Long-haul Truck": 53,
    "Motor Home": 54,
    "Combination Short-haul Truck": 61,
    "Combination Long-haul Truck": 62,
}
```

### 2.5 污染物映射

```python
POLLUTANT_TO_ID = {
    "THC": 1,
    "CO": 2,
    "NOx": 3,
    "VOC": 5,
    "SO2": 30,
    "NH3": 35,
    "NMHC": 79,
    "CO2": 90,
    "Energy": 91,
    "PM10": 100,
    "PM2.5": 110,
}
```

### 2.6 季节映射

```python
SEASON_CODES = {
    "春季": 4,
    "夏季": 7,
    "秋季": 4,
    "冬季": 1,
}
```

---

## 3. 微观排放计算（轨迹数据方法）

### 3.1 计算原理

微观排放计算基于车辆每秒的轨迹数据，使用 **VSP (Vehicle Specific Power)** 方法。

#### VSP计算公式

```
VSP = v × (1.1 × a + 9.81 × grade/100 + 0.132) + 0.000302 × v³

其中：
v = 车速 (m/s)
a = 加速度 (m/s²)
grade = 坡度 (%)
```

#### opMode映射

VSP值被映射到MOVES的opMode (0-40)：

| opMode | 描述 | VSP范围 | 速度范围 |
|--------|------|---------|----------|
| 0 | 怠速 | VSP ≤ -2 | - |
| 1-10 | 低速制动 | - | v < 25 mph |
| 11-16 | 低速 | - | 25 ≤ v < 40 |
| 21-30 | 中速 | - | 40 ≤ v < 65 |
| 31-40 | 高速 | - | v ≥ 65 |

### 3.2 计算器代码结构

**文件**: `calculators/micro_emission.py`

#### 核心方法

```python
class MicroEmissionCalculator:
    def calculate(self, trajectory_data, vehicle_type, pollutants, model_year, season):
        """
        Args:
            trajectory_data: List[Dict] - 秒级轨迹数据
                {
                    "t": int,          # 时间(s)
                    "speed_kph": float, # 速度(km/h)
                    "acceleration_mps2": float, # 加速度(m/s²)
                    "grade_pct": float, # 坡度(%)
                }
            vehicle_type: str - 车型
            pollutants: List[str] - 污染物列表
            model_year: int - 车型年份
            season: str - 季节
        """
```

#### 计算流程

```python
# 1. 计算VSP
for point in trajectory_data:
    point['vsp'] = calculate_vsp(
        point['speed_kph'],
        point['acceleration_mps2'],
        point.get('grade_pct', 0)
    )

# 2. 映射opMode
for point in trajectory_data:
    point['opMode'] = map_to_opmode(
        point['speed_kph'],
        point['vsp']
    )

# 3. 计算每秒排放
for point in trajectory_data:
    opMode = point['opMode']

    for pollutant in pollutants:
        # 查询MOVES排放率
        emission_rate = query_emission_rate(opMode, pollutant, vehicle_type, model_year)

        # 单位转换: g/hr → g/s
        emission_rate_g_per_sec = emission_rate / 3600

        # 计算该秒的排放量
        emission_g = emission_rate_g_per_sec

        # 累加
        total_emissions_g[pollutant] += emission_g

# 4. 计算统计
total_distance_km = sum(speeds) / 3600
total_time_s = len(trajectory_data)
avg_emission_rate_g_per_km = total_emissions_g / total_distance_km
```

### 3.3 VSP计算实现

```python
def calculate_vsp(speed_kph, acceleration_mps2, grade_pct):
    """
    Args:
        speed_kph: 速度
        acceleration_mps2: 加速度 (m/s²)
        grade_pct: 坡度 (%)

    Returns:
        VSP值 (kW/ton)
    """
    v = speed_kph / 3.6  # km/h → m/s
    a = acceleration_mps2
    grade = grade_pct / 100

    vsp = v * (1.1 * a + 9.81 * grade + 0.132) + 0.000302 * v**3
    return vsp
```

### 3.4 opMode映射规则

```python
def map_to_opmode(speed_kph, vsp):
    """
    规则：
    1. 如果 VSP ≤ -2 → opMode 0 (怠速)
    2. 根据 VSP 和速度范围映射到 opMode 1-40
    """
    if vsp <= -2:
        return 0

    speed_mph = speed_kph * 0.621371

    if speed_mph < 25:
        # 低速范围 (opMode 1-10)
        return calculate_low_speed_opmode(vsp)
    elif speed_mph < 40:
        # 中低速范围 (opMode 11-20)
        return calculate_mid_low_speed_opmode(vsp)
    elif speed_mph < 65:
        # 中高速范围 (opMode 21-30)
        return calculate_mid_high_speed_opmode(vsp)
    else:
        # 高速范围 (opMode 31-40)
        return calculate_high_speed_opmode(vsp)
```

---

## 4. MOVES数据结构

### 4.1 数据文件位置

```
calculators/data/
├── macro_emission/
│   ├── atlanta_2025_1_35_60 .csv   # 冬季（注意文件名有空格）
│   ├── atlanta_2025_4_75_65.csv     # 春季
│   └── atlanta_2025_7_80_60.csv     # 夏季
├── micro_emission/
│   ├── atlanta_2025_1_55_65.csv     # 冬季
│   ├── atlanta_2025_4_75_65.csv     # 春季
│   └── atlanta_2025_7_90_70.csv     # 夏季
└── emission_factors/
    ├── atlanta_2025_1_55_65.csv     # 冬季
    ├── atlanta_2025_4_75_65.csv     # 春季
    └── atlanta_2025_7_90_70.csv     # 夏季
```

### 4.2 CSV文件格式

```csv
opModeID,pollutantID,SourceType,modelYearID,em
300,90,21,5,123.456789
300,90,21,6,115.234567
300,90,32,5,98.7654321
...
```

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| opModeID | int | 运行模式ID (300=平均值) |
| pollutantID | int | 污染物ID (90=CO2, 110=PM2.5等) |
| SourceType | int | 车型ID (21=Passenger Car等) |
| modelYearID | int | 年龄组 (1=0-1年, 5=10-19年等) |
| em | float | 排放率 (g/hr) |

### 4.3 车型年龄组映射

```python
MODEL_YEAR_MAPPING = {
    2020: [1, 2, 5, 6, 9],  # 0-1, 2-9, 10-19, 20-29, 30+ years
    2021: [1, 2, 5, 6, 9],
    2022: [1, 2, 5, 6, 9],
    # ... 其他年份
}
```

### 4.4 数据特点

1. **季节性数据**: 不同季节使用不同的排放矩阵
2. **Atlanta数据**: 使用Atlanta地区的MOVES数据
3. **年龄组**: 按车辆使用年限分组
4. **opMode**: MOVES定义的50+种运行模式
5. **多种污染物**: 支持THC, CO, NOx, VOC, SO2, NH3, NMHC, CO2, Energy, PM10, PM2.5

---

## 5. 参数标准化

### 5.1 标准化服务

**文件**: `services/standardizer.py`

#### 车型标准化规则

```python
VEHICLE_STANDARDIZATION = {
    # 中文 → 标准英文名
    "小汽车": "Passenger Car",
    "乘用车": "Passenger Car",
    "轿车": "Passenger Car",
    "私家车": "Passenger Car",

    "货车": "Passenger Truck",
    "卡车": "Passenger Truck",

    "公交车": "Transit Bus",
    "客车": "Transit Bus",

    "重卡": "Combination Long-haul Truck",
    "重型卡车": "Combination Long-haul Truck",

    # 英文别名 → 标准名
    "car": "Passenger Car",
    "sedan": "Passenger Car",
    "bus": "Transit Bus",
    "truck": "Passenger Truck",
}
```

#### 污染物标准化规则

```python
POLLUTANT_STANDARDIZATION = {
    "氮氧化物": "NOx",
    "氮氧": "NOx",
    "二氧化碳": "CO2",
    "碳排放": "CO2",
    "PM2.5": "PM2.5",
    "PM10": "PM10",
    "颗粒物": "PM2.5",
    "VOC": "VOC",
    "碳氢": "THC",
}
```

### 5.2 工具层自动修复

**文件**: `tools/macro_emission.py`

#### 字段名映射

```python
def _fix_common_errors(self, links_data):
    field_mapping = {
        "link_length_km": ["length", "link_length", "length_km", "road_length"],
        "traffic_flow_vph": ["traffic_volume_veh_h", "traffic_flow", "flow", "volume"],
        "avg_speed_kph": ["avg_speed_kmh", "speed", "avg_speed", "average_speed"],
        "fleet_mix": ["vehicle_composition", "vehicle_mix", "composition"],
        "link_id": ["id", "road_id", "segment_id"]
    }
```

#### 车队组成格式转换

```python
# 从数组格式转换为对象格式
输入: [
    {"vehicle_type": "Passenger Car", "percentage": 70},
    {"vehicle_type": "Passenger Truck", "percentage": 30}
]

输出: {
    "Passenger Car": 70,
    "Passenger Truck": 30
}
```

---

## 6. API接口

### 6.1 核心路由

| 路由 | 方法 | 功能 |
|------|------|------|
| `/api/chat` | POST | 普通聊天 |
| `/api/chat/stream` | POST | 流式聊天 |
| `/api/file/preview` | POST | 文件预览 |
| `/api/file/download/{file_id}` | GET | 文件下载 |

### 6.2 请求处理流程

```python
# 1. 用户身份识别
user_id = get_user_id(request)

# 2. 文件处理（如果有）
if file upload:
    file_data = await save_temp_file(file)
    preview = analyze_file(file_data)

# 3. LLM参数解析
from llm.client import get_llm
llm_client = get_llm("agent")
parsed_params = llm_client.parse(user_input)

# 4. 标准化参数
standardizer = get_standardizer()
standard_params = standardizer.standardize(parsed_params)

# 5. 执行计算
tool = get_tool(standard_params['tool_name'])
result = await tool.execute(**standard_params)

# 6. 流式返回
if USE_STREAMING:
    yield {"type": "status", "content": "正在计算..."}
    yield {"type": "chart", "data": result.chart_data}
    yield {"type": "table", "data": result.table_data}
    yield {"type": "done", "session_id": session_id}
```

---

## 7. 技术细节

### 7.1 单位转换总结

| 物理量 | MOVES单位 | 输入单位 | 计算单位 |
|--------|-----------|----------|----------|
| 长度 | mile | km | mile (计算中) |
| 速度 | mph | km/h | mph (查询中) |
| 排放率 | g/hr | - | g/s (计算中) |
| 排放量 | - | kg/h | kg/h (输出) |

### 7.2 默认车队组成

```python
DEFAULT_FLEET_MIX = {
    "Passenger Car": 70.0,      # 70%
    "Passenger Truck": 20.0,     # 20%
    "Light Commercial Truck": 5.0,  # 5%
    "Transit Bus": 3.0,          # 3%
    "Combination Long-haul Truck": 2.0  # 2%
}
```

### 7.3 错误处理策略

1. **参数缺失**: 返回友好的错误提示和示例
2. **数据无效**: 自动修复常见错误（字段名、格式等）
3. **计算失败**: 记录详细日志，返回简化错误信息
4. **文件错误**: 支持CSV/Excel格式，自动检测编码

### 7.4 性能优化

1. **数据缓存**: MOVES矩阵只加载一次
2. **流式响应**: 实时输出计算进度
3. **异步处理**: 支持长时间计算任务
4. **会话管理**: 多用户并发支持

---

## 附录A：快速参考

### 宏观排放计算示例

**输入**:
```
两个路段：
- 路段1：3km，流量1000辆/小时，速度50km/h
- 路段2：5km，流量800辆/小时，速度60km/h
车型：Passenger Car (70%), Passenger Truck (30%)
污染物：CO2, NOx
年份：2020
季节：夏季
```

**输出**:
```json
{
  "results": [
    {
      "link_id": "Link_1",
      "link_length_km": 3.0,
      "total_emissions_kg_per_hr": {
        "CO2": 123.45,
        "NOx": 0.678
      }
    },
    {
      "link_id": "Link_2",
      "link_length_km": 5.0,
      "total_emissions_kg_per_hr": {
        "CO2": 156.78,
        "NOx": 0.890
      }
    }
  ]
}
```

### 微观排放计算示例

**输入**:
```
轨迹数据：
- 时间: 0-60秒
- 速度: 40-60 km/h（变化）
- 加速度: -2 到 +3 m/s²
车型：Passenger Car
污染物：CO2, NOx
年份：2020
季节：夏季
```

**输出**:
```json
{
  "total_emissions_g": {
    "CO2": 456.78,
    "NOx": 2.345
  },
  "total_distance_km": 0.833,
  "emission_rates_g_per_km": {
    "CO2": 548.12,
    "NOx": 2.81
  }
}
```

---

## 附录B：代码文件清单

### 核心计算文件

| 文件 | 功能 |
|------|------|
| `calculators/macro_emission.py` | 宏观排放计算器 |
| `calculators/micro_emission.py` | 微观排放计算器 |
| `calculators/emission_factors.py` | 排放因子查询 |
| `tools/macro_emission.py` | 宏观排放工具 |
| `tools/micro_emission.py` | 微观排放工具 |
| `skills/macro_emission/` | 宏观排放业务逻辑 |
| `skills/micro_emission/` | 微观排放业务逻辑 |

### 数据文件

| 文件 | 说明 |
|------|------|
| `calculators/data/macro_emission/atlanta_2025_*.csv` | 宏观排放矩阵 |
| `calculators/data/micro_emission/atlanta_2025_*.csv` | 微观排放矩阵 |
| `calculators/data/emission_factors/atlanta_2025_*.csv` | 排放因子数据 |

### 配置文件

| 文件 | 功能 |
|------|------|
| `services/standardizer.py` | 参数标准化服务 |
| `core/executor.py` | LLM执行器 |
| `api/routes.py` | FastAPI路由 |
| `api/models.py` | Pydantic数据模型 |

---

## 附录C：版本历史

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| v1.0 | 2026-03-08 | 初始版本，完整记录计算流程 |

---

**文档结束**

*如需更新或补充，请联系开发团队*
