# 计算器数值异常分析

## 问题现象

计算结果显示 CO2 排放量异常高：
- **当前值**: 5,821 kg CO2 / 1.111 km = **5,239 kg/km**
- **正常值**: 货车 CO2 排放约 **0.5-1 kg/km**
- **异常倍数**: **5,000-10,000 倍**

## 计算链路追踪

### 1. 数据来源

```
用户上传: micro_05_minimal.csv
├─ 列: t, speed
├─ 行数: 100
└─ 单位: t (秒?), speed (km/h)
```

### 2. 文件读取

**位置**: `skills/micro_emission/excel_handler.py`

```python
def read_trajectory_from_excel(self, file_path: str):
    # 读取 CSV/Excel
    df = pd.read_csv(file_path)

    # 智能列名映射
    mapped = self._intelligent_map_columns(df, task_type="micro_emission")

    # 映射结果
    # t → time_sec
    # speed → speed_kph

    # 返回数据
    trajectory_data = df.to_dict("records")
    return True, trajectory_data, None
```

### 3. 数据传递

**位置**: `tools/micro_emission.py`

```python
async def execute(self, **kwargs):
    # 获取 input_file
    input_file = kwargs.get("input_file")

    # 读取轨迹数据
    success, trajectory_data, error = self._excel_handler.read_trajectory_from_excel(input_file)

    # trajectory_data 格式:
    # [
    #   {"t": 0, "speed": 50},
    #   {"t": 1, "speed": 55},
    #   ...
    # ]
```

### 4. VSP 计算

**位置**: `calculators/micro_emission.py` → `VSPCalculator`

```python
def calculate_vsp(self, speed: float, acceleration: float = 0, grade: float = 0):
    """
    VSP = v * (1.1 * a + 9.81 * grade + 0.132) + 0.000302 * v^3

    单位:
    - speed: km/h → 需要转换为 m/s
    - acceleration: m/s²
    - grade: 小数 (0.05 = 5%)
    """
    speed_ms = speed / 3.6  # km/h → m/s
    vsp = (speed_ms *
           (1.1 * acceleration + 9.81 * grade + 0.132) +
           0.000302 * speed_ms ** 3)
    return vsp
```

### 5. 排放因子查询

**位置**: `calculators/micro_emission.py` → `MicroEmissionCalculator.calculate()`

```python
def calculate(self, trajectory_data, vehicle_type, pollutants, model_year, season):
    # 1. 计算每个点的 VSP
    for point in trajectory_data:
        speed = point.get("speed_kph")
        vsp = self._vsp_calculator.calculate_vsp(speed)
        point["vsp"] = vsp

    # 2. 查询排放因子
    for point in trajectory_data:
        speed = point["speed_kph"]
        vsp = point["vsp"]

        # 从 Atlanta MOVES 数据库查询
        for pollutant in pollutants:
            factor = self._query_emission_factor(
                vehicle_type=vehicle_type,
                pollutant=pollutant,
                speed=speed,
                vsp=vsp,
                model_year=model_year,
                season=season
            )
            emission = factor * dt  # g/s × s
            point["emissions"][pollutant] = emission
```

### 6. 排放因子数据

**位置**: `calculators/data/atlanta_2025_7_90_70.csv`

CSV 格式:
```csv
vehicleID,pollutantID,speedBin,sourceType,factor
62,CO2,30,..."   # 组合长途卡车
62,CO2,60,...
62,CO2,90,...
```

**关键问题**:
- `factor` 的单位是什么？
- 是 **g/s**? **g/km**? 还是其他?

### 7. 排放计算

```python
# 假设:
# - speed = 50 km/h
# - factor = 150 (单位未知)
# - dt = 1 秒

emission = factor * dt  # 150 * 1 = 150 g

# 如果 factor 单位是 g/s:
# - 每秒排放 150g
# - 每小时排放 150 * 3600 = 540,000 g = 540 kg
# - 50 km/h → 540 / 50 = 10.8 kg/km (正常)

# 如果 factor 单位是 g/km:
# - 每公里排放 150g
# - 但按秒计算: 150 * dt (错误!)
# - dt = 1s, distance = 13.9m
# - 应该: 150 * 0.0139 = 2.08g
# - 实际: 150 * 1 = 150g (多算了 72 倍)
```

## 可能的错误源

### 错误1: 排放因子单位理解错误

**假设**: Atlanta MOVES 数据的 factor 单位是 **g/km**
**问题**: 计算时按 **g/s** 使用

```python
# 错误的计算
emission_g = factor * dt  # factor (g/km) * 1s → 错误!

# 正确的计算
distance_km = speed_kph * dt / 3600  # km
emission_g = factor * distance_km  # factor (g/km) * km → g
```

### 错误2: 数据文件单位不匹配

**检查**: `calculators/data/atlanta_*.csv` 的实际单位

```bash
# 查看文件头
head -5 calculators/data/atlanta_2025_7_90_70.csv
```

可能的情况:
- 单位是 **mg/s** 而非 **g/s**
- 单位是 **g/vehicle** 而非 **g/s**

### 错误3: VSP Bin 映射错误

**检查**: VSP 计算结果是否合理

```python
# 正常 VSP 范围: -20 到 50 kW/ton
# 如果 VSP 计算错误 → 查询到错误的排放因子

# 检查:
# - speed 单位是否正确 (km/h vs m/s)
# - acceleration 是否默认为 0
# - grade 是否默认为 0
```

### 错误4: 车型 ID 映射错误

**检查**: "Combination Long-haul Truck" 对应的 vehicleID

```python
# 映射: "大货车" → "Combination Long-haul Truck" → ID 62
# 如果 ID 62 的数据错误 → 排放因子错误

# 检查 Atlanta 数据库中 ID 62 是否:
# - 数据单位不同
# - 数据数值异常
```

## 诊断步骤

### 步骤1: 打印中间结果

在 `calculators/micro_emission.py` 中添加日志:

```python
def calculate(self, trajectory_data, vehicle_type, pollutants, model_year, season):
    logger.info("=" * 50)
    logger.info(f"[Calculation] Input:")
    logger.info(f"  vehicle_type: {vehicle_type}")
    logger.info(f"  pollutants: {pollutants}")
    logger.info(f"  model_year: {model_year}")
    logger.info(f"  season: {season}")
    logger.info(f"  trajectory_points: {len(trajectory_data)}")

    logger.info(f"[Calculation] First 3 points:")
    for i, point in enumerate(trajectory_data[:3]):
        logger.info(f"  Point {i}: {point}")

    # ... 执行计算 ...

    logger.info(f"[Calculation] Sample VSP calculation:")
    for i, point in enumerate(results[:3]):
        logger.info(f"  Point {i}:")
        logger.info(f"    speed_kph: {point['speed_kph']}")
        logger.info(f"    vsp: {point['vsp']}")
        logger.info(f"    emissions: {point['emissions']}")

    logger.info("=" * 50)
```

### 步骤2: 检查排放因子查询

```python
def _query_emission_factor(self, vehicle_type, pollutant, speed, vsp, model_year, season):
    result = self.emission_df.query(...)

    # 打印查询结果
    if not result.empty:
        factor = result['factor'].values[0]
        logger.info(f"[Factor Query] vehicle={vehicle_type}, pollutant={pollutant}, speed={speed}, vsp={vsp:.2f}")
        logger.info(f"[Factor Query] Found factor = {factor}")
        logger.info(f"[Factor Query] Factor row: {result.to_dict('records')[0]}")
    else:
        logger.warning(f"[Factor Query] NO FACTOR FOUND for {vehicle_type}/{pollutant}/{speed:.1f}/{vsp:.2f}")

    return factor
```

### 步骤3: 验证数据文件

```python
# 读取并检查排放因子数据
import pandas as pd

df = pd.read_csv("calculators/data/atlanta_2025_7_90_70.csv")

# 检查:
# 1. factor 列的范围
print(f"Factor range: {df['factor'].min()} - {df['factor'].max()}")
print(f"Factor mean: {df['factor'].mean()}")
print(f"Factor for vehicle 62, CO2, speed 60:")
print(df.query("vehicleID == 62 and pollutantID == 'CO2' and speedBin == 60"))
```

### 步骤4: 对比新旧架构

**原架构** (`skills/micro_emission/skill.py`):
```python
result = self._calculator.calculate(
    trajectory_data=trajectory_data,
    vehicle_type=v_result.standard,
    pollutants=standardized_pollutants,
    model_year=model_year,
    season=season_std,
)
```

**新架构** (`tools/micro_emission.py`):
```python
result = self._calculator.calculate(
    trajectory_data=trajectory_data,
    vehicle_type=vehicle_type,
    pollutants=pollutants,
    model_year=model_year,
    season=season,
)
```

**检查**: 调用参数是否一致？

## 可能的修复方案

### 方案1: 修正单位转换

如果排放因子单位是 **g/km**，需要修正计算:

```python
# 当前 (错误)
emission_g = factor * dt  # factor (g/km) * 1s

# 修正
distance_km = speed_kph * dt / 3600
emission_g = factor * distance_km
```

### 方案2: 修正排放因子数值

如果数据文件中的 factor 需要转换:

```python
# 检查 factor 是否需要除以 1000 或其他转换
factor_corrected = factor / 1000  # mg → g?
```

### 方案3: 修正 VSP 计算

如果 VSP 计算错误导致查询到错误的因子:

```python
# 检查 speed 单位
# 如果数据是 m/s 但代码当作 km/h
speed_kph = speed_ms * 3.6
```

## 立即行动

1. **添加诊断日志**: 打印所有中间结果
2. **检查数据文件**: 验证排放因子的单位和数值
3. **对比旧架构**: 使用相同的数据文件和参数，对比结果
4. **手动验证**: 用一个简单案例，手动计算验证

## 临时解决方案

如果无法立即修复，可以在 Synthesis 中添加警告:

```
⚠️ 注意：计算结果可能存在单位转换问题，数值仅供参考。
建议：
1. 查看详细结果文件
2. 对比同类研究的排放因子
3. 联系开发者确认计算逻辑
```
