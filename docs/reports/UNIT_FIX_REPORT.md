# 单位修复完成报告

**修复日期**: 2026-02-07
**修复内容**: 排放计算单位一致性修复

---

## 修复总结

| 修复项 | 状态 | 影响 |
|--------|------|------|
| 修复1: 微观排放单位转换 | ✅ 完成 | 结果精度提升 3600 倍 |
| 修复2: 宏观排放计算公式 | ✅ 完成 | 结果精度提升 ~31 倍 |
| 修复3: tools 层检查 | ✅ 无需修改 | - |

---

## 修复1: 微观排放计算

**文件**: `calculators/micro_emission.py`
**位置**: Line 130-132

**修改内容**:
```python
# 修改前:
emissions[pollutant] = round(emission_rate, 6)

# 修改后:
# Unit conversion: MOVES EmissionQuant is in g/hr, need g/s for per-second accumulation
# Original code: emissions[pollutant] = round(emission_rate, 6)
emissions[pollutant] = round(emission_rate / 3600, 6)
```

**验证结果**:

| 场景 | 参数 | 预期值 | 实际值 | 状态 |
|------|------|--------|--------|------|
| 怠速 | 100秒, Passenger Car 2020 | 65.94 g | 66.28 g | ✅ |
| 巡航 | 100秒@50km/h | 136.08 g | 136.79 g | ✅ |

---

## 修复2: 宏观排放计算

**文件**: `calculators/macro_emission.py`
**位置**: Line 180-200

**修改内容**:
```python
# 修改前:
# emission_rate: g/mile  ← 注释错误
emission_kg_per_hr = (
    emission_rate * length_mi * vehicles_per_hour / 1000
)

# 修改后:
# MOVES EmissionQuant 单位是 g/hr (不是 g/mile)
# Corrected code:
emission_rate_g_per_sec = emission_rate / 3600  # g/hr → g/s
travel_time_sec = (link["link_length_km"] / link["avg_speed_kph"]) * 3600  # 行驶时间(秒)
emission_g_per_veh = emission_rate_g_per_sec * travel_time_sec  # 单车排放量
emission_kg_per_hr = emission_g_per_veh * vehicles_per_hour / 1000  # kg/hr
```

**验证结果**:

| 参数 | 预期范围 | 实际值 | 状态 |
|------|----------|--------|------|
| 单位排放率 | 60-85 g/(veh·km) | 70.03 g/(veh·km) | ✅ |
| 路段总排放 | 60-85 kg/hr | 70.03 kg/hr | ✅ |
| 修正效果 | ~2175 → ~70 kg/hr | ~31 倍改进 | ✅ |

---

## 修复3: tools 层检查

**检查结果**: tools/micro_emission.py 和 tools/macro_emission.py
- ✅ 没有额外的单位转换操作
- ✅ 只调用 calculators 层并传递结果
- ✅ 无需修改

---

## 数据单位参考

根据 MOVES (Motor Vehicle Emission Simulator) 标准：

| 数据类型 | MOVES 输出单位 | 说明 |
|---------|---------------|------|
| Rate-based (opMode) | **g/hr** | 基于 opMode 的排放率 |
| Speed-based | **g/mile** | 基于速度的排放率 |
| 能耗 | **kJ/hr** 或 **BTU/hr** | Energy consumption |
| VSP | **kW/ton** | 车辆比功率 |

**关键发现**:
- 微观排放数据使用 opMode-based 格式，单位是 **g/hr**
- 宏观排放数据也使用 opMode-based 格式，单位是 **g/hr**
- 排放因子查询使用 Speed-based 格式，单位是 **g/mile**

---

## 修正前后对比

### 微观排放 (100秒怠速)

| 指标 | 修正前 | 修正后 | 误差倍数 |
|------|--------|--------|---------|
| CO2 总排放 | ~237,000 g ❌ | 66.28 g ✅ | **3600x** |

### 宏观排放 (1km路段, 1000 veh/hr)

| 指标 | 修正前 | 修正后 | 误差倍数 |
|------|--------|--------|---------|
| 路段总排放 | ~2175 kg/hr ❌ | 70.03 kg/hr ✅ | **~31x** |

---

## 验证测试

所有验证测试均通过 ✅

1. **验证1: 微观排放 - 怠速场景**
   - CO2: 66.28 g (预期 65.94 g) ✅

2. **验证2: 微观排放 - 巡航场景**
   - CO2 排放率: 99.49 g/km (预期 98 g/km) ✅

3. **验证3: 宏观排放**
   - 单位排放率: 70.03 g/(veh·km) (预期 60-85 g/(veh·km)) ✅

---

## 后续建议

1. ✅ 修复已完成并验证
2. ⚠️ 建议更新相关文档中的单位说明
3. ⚠️ 建议添加单元测试覆盖这些计算逻辑

---

**修复完成时间**: 2026-02-07
**验证脚本**: verify_unit_fix.py
