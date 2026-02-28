# 微观排放Excel输入/输出功能文档

## 概述

微观排放Skill已升级，支持从Excel文件读取轨迹数据，并将计算结果输出到Excel文件。

## 新增文件

### 1. `skills/micro_emission/excel_handler.py`
Excel文件处理器，提供读写功能。

## 新增参数

### 1. `input_file: str = None`
- **描述**: Excel输入文件路径
- **格式**: `.xlsx` 或 `.csv`
- **与 `trajectory_data` 二选一**

### 2. `output_file: str = None`
- **描述**: Excel输出文件路径
- **格式**: `.xlsx` 或 `.csv`
- **可选参数**

## Excel输入格式

### 必需列（任一即可）
- `speed_kph` / `speed` / `车速` / `速度`

### 可选列
- **加速度**: `acceleration` / `acc` / `acceleration_mps2` / `加速度`
  - 如果没有，将根据速度差自动计算
- **坡度**: `grade_pct` / `grade` / `坡度`
  - 如果没有，默认为 0
- **时间**: `t` / `time` / `时间`
  - 如果没有，自动生成 0, 1, 2, 3...

### 示例输入文件

**完整格式** (test_input.xlsx):
| 时间 | 速度 | 加速度 | 坡度 |
|------|------|--------|------|
| 0    | 0    | 0      | 0    |
| 1    | 10   | 2.78   | 0    |
| 2    | 20   | 2.78   | 0    |
| 3    | 30   | 2.78   | 0    |

**简化格式** (test_input_simple.xlsx):
| 车速 |
|------|
| 0    |
| 10   |
| 20   |
| 30   |

## Excel输出格式

输出文件包含以下列：

| 列名 | 描述 | 单位 |
|------|------|------|
| t | 时间 | 秒 |
| speed_kph | 速度 | km/h |
| acc_mps2 | 加速度 | m/s² |
| grade_pct | 坡度 | % |
| VSP | 车辆比功率 | kW/ton |
| CO2_g_per_s | CO2排放率 | g/s |
| NOx_mg_per_s | NOx排放率 | mg/s |
| PM2.5_mg_per_s | PM2.5排放率 | mg/s |

**注意**:
- CO2使用 `g/s` 单位
- 其他污染物使用 `mg/s` 单位（自动转换）

## 使用示例

### 示例1: Excel输入和输出

```python
from skills.micro_emission.skill import MicroEmissionSkill

skill = MicroEmissionSkill()
result = skill.execute(
    input_file="trajectory.xlsx",
    output_file="emissions.xlsx",
    vehicle_type="小汽车",
    model_year=2020,
    pollutants=["CO2", "NOx", "PM2.5"],
    season="夏季"
)

if result.success:
    print(f"输出文件: {result.data['output_file']}")
    print(f"总排放: {result.data['summary']}")
```

### 示例2: 只有速度列的简化输入

```python
# 输入文件只需要一列速度数据
# Excel: 车速
#        0
#        10
#        20
#        30

result = skill.execute(
    input_file="simple_trajectory.xlsx",
    output_file="emissions_output.xlsx",
    vehicle_type="公交车",
    model_year=2020,
    pollutants=["CO2"],
    season="夏季"
)
```

### 示例3: CSV格式

```python
# 支持CSV格式输入和输出
result = skill.execute(
    input_file="trajectory.csv",
    output_file="emissions.csv",
    vehicle_type="小汽车",
    model_year=2020,
    pollutants=["CO2", "NOx"],
    season="夏季"
)
```

### 示例4: 混合使用（数组输入，Excel输出）

```python
# 可以使用trajectory_data数组输入，但输出到Excel
result = skill.execute(
    trajectory_data=[
        {"t": 0, "speed_kph": 0},
        {"t": 1, "speed_kph": 10},
        {"t": 2, "speed_kph": 20}
    ],
    output_file="emissions.xlsx",
    vehicle_type="小汽车",
    model_year=2020,
    pollutants=["CO2"],
    season="夏季"
)
```

## 自动计算功能

### 1. 加速度自动计算

如果输入文件没有加速度列，系统会根据速度差自动计算：

```python
# 使用中心差分法
acc[i] = (speed[i+1] - speed[i-1]) / (2 * dt) / 3.6
```

- 第一个点：使用前向差分
- 最后一个点：使用后向差分
- 中间点：使用中心差分

### 2. 时间自动生成

如果没有时间列，自动生成：`0, 1, 2, 3, ...`

### 3. 坡度默认值

如果没有坡度列，默认为 `0`

## 列名识别

系统支持多种列名格式（不区分大小写）：

| 数据类型 | 支持的列名 |
|----------|-----------|
| 速度 | speed_kph, speed, 车速, 速度 |
| 加速度 | acceleration, acc, acceleration_mps2, 加速度 |
| 坡度 | grade_pct, grade, 坡度 |
| 时间 | t, time, 时间 |

## 参数验证

### 必需参数
- `vehicle_type`: 车型
- `trajectory_data` 或 `input_file`: 至少提供一个

### 可选参数
- `model_year`: 车辆年份（默认：2020）
- `pollutants`: 污染物列表（默认：["CO2", "NOx"]）
- `season`: 季节（默认：夏季）
- `output_file`: 输出文件路径

### 验证示例

```python
# 缺少轨迹数据
result = skill.execute(
    vehicle_type="小汽车",
    model_year=2020
)

# 返回
{
    "success": False,
    "error": "缺少必需参数: trajectory_data/input_file",
    "metadata": {
        "missing_params": {
            "trajectory_data": {
                "description": "轨迹数据或输入文件",
                "format": "[{\"t\": 0, \"speed_kph\": 60}, ...]",
                "note": "可以提供trajectory_data数组，或使用input_file指定Excel文件路径"
            }
        }
    }
}
```

## 错误处理

### 1. 文件不存在

```python
result = skill.execute(
    input_file="nonexistent.xlsx",
    vehicle_type="小汽车"
)

# 返回
{
    "success": False,
    "error": "读取输入文件失败: 文件不存在: nonexistent.xlsx"
}
```

### 2. 不支持的文件格式

```python
result = skill.execute(
    input_file="data.txt",  # 不支持
    vehicle_type="小汽车"
)

# 返回
{
    "success": False,
    "error": "读取输入文件失败: 不支持的文件格式: .txt，仅支持 .xlsx, .xls, .csv"
}
```

### 3. 缺少速度列

```python
# Excel文件没有速度相关列
result = skill.execute(
    input_file="invalid.xlsx",
    vehicle_type="小汽车"
)

# 返回
{
    "success": False,
    "error": "读取输入文件失败: 未找到速度列，支持的列名: speed_kph, speed, 车速, 速度"
}
```

### 4. 输出文件写入失败

如果输出文件写入失败，计算结果仍然返回，但会包含警告：

```python
result = skill.execute(
    input_file="input.xlsx",
    output_file="/invalid/path/output.xlsx",
    vehicle_type="小汽车"
)

# 返回
{
    "success": True,
    "data": {
        "query_info": {...},
        "summary": {...},
        "results": [...],
        "output_file_warning": "写入输出文件失败: ..."
    }
}
```

## 测试

运行测试脚本：

```bash
cd D:\Agent_MCP\emission_agent
python test_micro_emission_excel.py
```

测试覆盖：
1. ✅ Excel输入和输出（完整数据）
2. ✅ 简化Excel输入（只有速度列）
3. ✅ CSV格式输入/输出
4. ✅ 参数验证
5. ✅ 文件不存在错误处理

## 修改的文件

### 1. `skills/micro_emission/excel_handler.py`（新增）
- `read_trajectory_from_excel()`: 读取Excel文件
- `write_results_to_excel()`: 写入Excel文件
- `_find_column()`: 查找列名
- `_calculate_acceleration()`: 自动计算加速度

### 2. `skills/micro_emission/skill.py`（修改）
- 添加 `input_file` 和 `output_file` 参数
- 更新参数验证逻辑
- 修改 `execute` 方法支持文件输入/输出
- 添加 `ExcelHandler` 实例

### 3. `test_micro_emission_excel.py`（新增）
- 完整的测试套件
- 自动创建示例文件

## 性能考虑

- Excel读取使用 `pandas`，支持大文件
- 自动计算加速度的时间复杂度为 O(n)
- 输出文件写入为批量操作，性能良好

## 注意事项

1. **单位转换**:
   - 输入速度单位：km/h
   - 输出CO2单位：g/s
   - 输出其他污染物单位：mg/s（自动转换）

2. **列名不区分大小写**:
   - "Speed", "speed", "SPEED" 都可以识别

3. **向后兼容**:
   - 原有的 `trajectory_data` 数组输入方式仍然支持
   - 可以混合使用（数组输入 + Excel输出）

4. **文件格式**:
   - 支持 `.xlsx`, `.xls`, `.csv`
   - CSV使用 UTF-8-BOM 编码（兼容Excel）

5. **错误恢复**:
   - 输出文件写入失败不影响计算结果
   - 会在结果中添加警告信息
