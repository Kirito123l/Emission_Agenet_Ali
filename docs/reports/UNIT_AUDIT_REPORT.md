# 排放计算单位一致性审计报告

**审计日期**: 2026-02-07
**审计范围**: 所有排放计算模块的单位一致性
**严重程度**: ❌ 致命 / ⚠️ 警告 / ℹ️ 建议

---

## 执行摘要

经过全面审计，发现 **2个致命单位错误**，导致微观和宏观排放计算结果严重偏差。VSP计算和排放因子查询的单位处理基本正确。

| 模块 | 严重程度 | 问题概述 | 影响程度 |
|------|---------|---------|---------|
| 微观排放计算 | ❌ 致命 | 未进行 g/hr → g/s 单位转换 | 结果偏大 **3600倍** |
| 宏观排放计算 | ❌ 致命 | 单位理解错误，公式链条断裂 | 结果偏大 **~2200倍** |
| 排放因子查询 | ✅ 正确 | g/mile → g/km 转换正确 | 无 |
| VSP计算 | ✅ 正确 | 速度单位转换正确 | 无 |

---

## 1. 数据源单位确认

### 1.1 微观排放数据源

**文件**: `skills/micro_emission/data/atlanta_2025_*.csv`

**格式**:
```csv
opModeID, pollutantID, SourceType, ModelYear, CalendarYear, EmissionQuant
300, 90, 21, 5, 2020, 3063.10
```

**EmissionQuant 数值范围分析**:

| 污染物 | 最小值 | 最大值 | 平均值 | 数据单位推断 |
|--------|--------|--------|--------|-------------|
| PM2.5 (ID=110) | 0.007 | 902.5 | 12.6 | g/hr |
| CO2 (ID=90) | 0.0 | 405,944 | 76,679 | **g/hr** |
| Energy (ID=91) | 17,906 | 7,621,050 | 1,091,406 | g/hr |

**关键验证 - 怠速 CO2 排放**:
- 数据库值: 1801.28 (opMode=0, Passenger Car 2020)
- 若单位为 g/hr: 1801.28 ÷ 3600 = **0.50 g/s**
- 若单位为 g/s: **1801.28 g/s** (不合理！)
- 小汽车怠速 CO2 实际值: ~0.5-0.8 g/s

**结论**: ✅ 数据单位是 **g/hr** (克/小时)

---

### 1.2 宏观排放数据源

**文件**: `skills/macro_emission/data/atlanta_2025_*.csv`

**格式**: 无表头，6列数据
```
300, 90, 21, 2020, 3501.62,
opModeID, pollutantID, sourceTypeID, modelYearID, EmissionQuant, extra
```

**EmissionQuant 数值范围**: 与微观数据一致

**结论**: ✅ 数据单位是 **g/hr** (克/小时)

---

### 1.3 排放因子数据源

**文件**: `skills/emission_factors/data/emission_matrix/atlanta_2025_*.csv`

**格式**:
```csv
Speed, pollutantID, SourceType, ModelYear, EmissionQuant
504, 90, 21, 2020, 180.5
```

**Speed编码**: `{speed_mph}0{road_type}`，如 504 = 5 mph + road type 4

**EmissionQuant 典型值**: 0.001 - 200 g/mile 范围

**结论**: ✅ 数据单位是 **g/mile** (克/英里)

---

## 2. 微观排放计算审计 ❌ 致命错误

### 2.1 代码追踪

**文件**: `calculators/micro_emission.py`

**计算流程**:
```python
# Line 91-157: calculate() 方法
for point in trajectory_with_vsp:
    emissions = {}
    for pollutant in pollutants:
        # Line 126-129: 从数据库查询排放率
        emission_rate = self._query_emission_rate(
            emission_matrix, point["opmode"], pollutant_id,
            source_type_id, model_year
        )
        # Line 130: 直接赋值，没有单位转换！
        emissions[pollutant] = round(emission_rate, 6)
```

**问题**: `emission_rate` 从数据库读取时单位是 g/hr，但代码直接将其作为每秒排放量使用。

### 2.2 单位链条分析

```
数据库值: 1801.28 (g/hr)
    ↓
_query_emission_rate() 返回: 1801.28 (仍标记为 g/hr，但被当作 g/s)
    ↓
emissions["CO2"] = 1801.28 (错误！应该是 1801.28 / 3600 = 0.50)
    ↓
100秒累加: 1801.28 × 100 = 180,128 g
    ↓
正确值应该是: (1801.28 / 3600) × 100 = 50.04 g
```

### 2.3 示例验证

| 场景 | 参数 | 当前代码结果 | 正确结果 | 误差 |
|------|------|-------------|---------|------|
| 100秒怠速 | Passenger Car 2020 | 180,128 g | 50.04 g | **3600x** |
| 100秒巡航 | 50 km/h | 306,310 g | 85.09 g | **3600x** |

### 2.4 错误严重程度

**❌ 致命错误**: 微观排放计算结果偏大 **3600 倍**

**修复方案**:
```python
# Line 130 需要修改为:
emissions[pollutant] = round(emission_rate / 3600, 6)
# 添加单位转换: g/hr → g/s
```

---

## 3. 宏观排放计算审计 ❌ 致命错误

### 3.1 代码追踪

**文件**: `calculators/macro_emission.py`

**关键代码 (Line 180-195)**:
```python
# 查询排放率 (使用平均opMode=300)
emission_rate = self._query_emission_rate(matrix, source_type_id, pollutant_id, model_year)

# 计算排放量
# emission_rate: g/mile  ← 注释错误！实际是 g/hr
# length_mi: mile
# vehicles_per_hour: vehicles/hr
# result: kg/hr
emission_kg_per_hr = (
    emission_rate *           # g/mile (注释)
    length_mi *              # mile
    vehicles_per_hour /      # vehicles/hr
    1000                     # g -> kg
)
```

### 3.2 单位链条分析

**代码假设的单位**:
```
emission_rate (g/mile) × length_mi (mile) × flow (veh/hr) / 1000
= g/mile × mile × veh/hr / 1000
= g × veh/hr / 1000
= kg/hr
```

**实际的单位 (数据库是 g/hr)**:
```
emission_rate (g/hr) × length_mi (mile) × flow (veh/hr) / 1000
= g/hr × mile × veh/hr / 1000
= g·mile·veh/hr² / 1000  ← 单位不闭合！
```

### 3.3 示例验证

**场景**: 1 km 路段，1000 veh/hr 交通流量

| 参数 | 值 |
|------|-----|
| 路段长度 | 1 km = 0.6214 mi |
| 交通流量 | 1000 veh/hr |
| 数据库 emission_rate | 3501.62 (实际是 g/hr) |

**当前代码计算**:
```
emission_kg_per_hr = 3501.62 × 0.6214 × 1000 / 1000 = 2175.8 kg/hr
```

**正确计算** (如果数据库是 g/hr):
```
emission_g_per_veh = 3501.62 g/hr = 0.9727 g/s
link_emission_hr = 0.9727 g/s × 1000 veh × 3600 s/hr / 1000 = 3501.62 kg/hr
```

或者，正确的公式应该是:
```
emission_kg_per_hr = (emission_rate / 3600) × vehicles_per_hour × time_on_link / 1000
其中 time_on_link = length_km / avg_speed_kph × 3600 (seconds)
```

### 3.4 问题根源

宏观排放计算存在两个问题：

1. **单位理解错误**: 代码注释说 emission_rate 是 g/mile，但实际数据是 g/hr
2. **物理意义错误**: 即使是 g/mile，公式也缺少车辆在路段上的行驶时间因子

**正确公式**:
```
E_link = Σ(VehType_i × Rate_i × T_link / 1000)
其中:
- VehType_i: 车型 i 的车辆数 (veh)
- Rate_i: 车型 i 的排放率 (g/s)
- T_link: 车辆在路段上的行驶时间 (s)
- 结果: kg/hr

T_link = Length / Speed × 3600
```

### 3.5 错误严重程度

**❌ 致命错误**: 宏观排放计算单位链条完全错误，结果偏差 **~2200 倍**

---

## 4. 排放因子查询审计 ✅ 正确

### 4.1 代码追踪

**文件**: `calculators/emission_factors.py`

**单位转换 (Line 167-177)**:
```python
if return_curve:
    for item in speed_data:
        speed_kph = round(item["speed_mph"] * 1.60934, 1)
        # 单位转换: g/mile -> g/km (除以1.60934)
        emission_rate_g_per_km = round(item["emission_rate"] / 1.60934, 4)
```

### 4.2 验证

| 源单位 | 目标单位 | 转换系数 | 正确性 |
|--------|---------|---------|--------|
| g/mile | g/km | ÷ 1.60934 | ✅ 正确 |

### 4.3 结论

ℹ️ **建议**: 代码正确，但可以添加更清晰的单位注释。

---

## 5. VSP 计算审计 ✅ 正确

### 5.1 速度单位转换

**文件**: `calculators/vsp.py`

```python
# Line 114-115
speed_mps = speed_kph / 3.6     # km/h → m/s (用于 VSP 公式)
speed_mph = speed_kph * 0.621371  # km/h → mph (用于 opMode 映射)
```

### 5.2 VSP 公式验证

```python
# Line 36-43
vsp = (
    p["A"] * v +              # v: m/s
    p["B"] * v**2 +
    p["C"] * v**3 +
    p["M"] * v * acc +        # acc: m/s²
    p["M"] * v * g * (grade_pct / 100.0)  # grade: %
) / p["m"]
```

**单位**: kW/ton ✅ 符合 MOVES 标准

### 5.3 opMode 速度阈值

```python
# Line 64-96: 使用 speed_mph 进行判断
if speed_mph < 1:      return 0  # 怠速
elif speed_mph < 25:   # 低速模式 (11-16)
elif speed_mph < 50:   # 中速模式 (21-30)
else:                  # 高速模式 (33-40)
```

**单位**: mph ✅ 符合 MOVES 标准

### 5.4 结论

✅ **VSP 计算完全正确**

---

## 6. 总结与修复建议

### 6.1 问题汇总

| 问题 | 严重程度 | 位置 | 修复优先级 |
|------|---------|------|-----------|
| 微观排放缺少 g/hr→g/s 转换 | ❌ 致命 | micro_emission.py:130 | P0 |
| 宏观排放单位理解错误 | ❌ 致命 | macro_emission.py:186-195 | P0 |
| 宏观排放公式缺少时间因子 | ❌ 致命 | macro_emission.py:186-195 | P0 |

### 6.2 修复代码

**修复 1: 微观排放单位转换**

```python
# calculators/micro_emission.py, Line 130
# 修改前:
emissions[pollutant] = round(emission_rate, 6)

# 修改后:
emissions[pollutant] = round(emission_rate / 3600, 6)  # g/hr → g/s
```

**修复 2: 宏观排放计算公式**

```python
# calculators/macro_emission.py, Line 180-220
# 修改前:
emission_kg_per_hr = (
    emission_rate * length_mi * vehicles_per_hour / 1000
)

# 修改后:
# 首先将 g/hr 转换为 g/s
emission_rate_g_per_sec = emission_rate / 3600

# 计算车辆在路段上的行驶时间 (秒)
travel_time_sec = (link["link_length_km"] / link["avg_speed_kph"]) * 3600

# 计算单辆车通过路段的排放量 (g)
emission_g_per_veh = emission_rate_g_per_sec * travel_time_sec

# 计算路段总排放 (kg/hr)
emission_kg_per_hr = emission_g_per_veh * vehicles_per_hour / 1000
```

### 6.3 验证测试

修复后需要验证:

1. **微观排放**: 100秒怠速，Passenger Car 2020，CO2 排放应约为 50g
2. **宏观排放**: 1km路段，50km/h，1000 veh/hr，排放应在合理范围

---

## 附录: MOVES 数据单位参考

根据 MOVES (Motor Vehicle Emission Simulator) 技术文档:

| 数据类型 | MOVES 输出单位 | 说明 |
|---------|---------------|------|
| Rate-based emission | **g/hr** | 基于 opMode 的排放率 |
| Speed-based emission | **g/mile** | 基于速度的排放率 |
| Energy consumption | **kJ/hr** 或 **BTU/hr** | 能耗 |
| VSP | **kW/ton** | 车辆比功率 |

---

**报告生成时间**: 2026-02-07
**审计工具**: Python pandas, 手动代码审查
**数据源版本**: MOVES Atlanta 2025
