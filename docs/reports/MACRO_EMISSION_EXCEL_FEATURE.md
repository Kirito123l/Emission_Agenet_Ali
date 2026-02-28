# 宏观排放Excel批量输入/输出功能文档

## 概述

宏观排放Skill已升级，支持从Excel文件批量读取路段数据，并将计算结果输出到Excel文件。

## 新增文件

### 1. `skills/macro_emission/excel_handler.py`
Excel文件处理器，提供读写功能。

## 新增参数

### 1. `input_file: str = None`
- **描述**: Excel输入文件路径
- **格式**: `.xlsx` 或 `.csv`
- **与 `links_data` 二选一**

### 2. `output_file: str = None`
- **描述**: Excel输出文件路径
- **格式**: `.xlsx` 或 `.csv`
- **可选参数**

## Excel输入格式

### 必需列（支持中英文）
- **路段长度**: `link_length_km` / `length_km` / `length` / `路段长度` / `长度`
- **交通流量**: `traffic_flow_vph` / `flow_vph` / `flow` / `traffic` / `交通流量` / `流量`
- **平均速度**: `avg_speed_kph` / `speed_kph` / `speed` / `平均速度` / `速度`

### 可选列
- **路段ID**: `link_id` / `id` / `路段ID` / `路段编号`
  - 如果没有，自动生成 Link_1, Link_2, Link_3...
- **车型分布列**: 支持以下车型（列名包含车型名称和%符号）
  - `乘用车%` / `小汽车%` / `轿车%` → Passenger Car
  - `公交车%` / `巴士%` → Transit Bus
  - `货车%` / `重型货车%` / `大货车%` → Combination Long-haul Truck
  - `轻型货车%` / `小货车%` → Light Commercial Truck
  - `客车%` / `皮卡%` → Passenger Truck
  - `摩托车%` → Motorcycle
  - `校车%` → School Bus
  - `城际客车%` → Intercity Bus
  - `垃圾车%` → Refuse Truck

### 示例输入文件

**完整格式** (test_macro_input_full.xlsx):
| 路段ID | 路段长度 | 交通流量 | 平均速度 | 乘用车% | 公交车% | 货车% |
|--------|----------|----------|----------|---------|---------|-------|
| L1     | 1.5      | 1000     | 60       | 60      | 10      | 30    |
| L2     | 2.0      | 1500     | 50       | 50      | 20      | 30    |
| L3     | 1.2      | 800      | 70       | 70      | 5       | 25    |

**简化格式** (test_macro_input_simple.xlsx):
| 路段长度 | 交通流量 | 平均速度 |
|----------|----------|----------|
| 1.5      | 1000     | 60       |
| 2.0      | 1500     | 50       |
| 1.2      | 800      | 70       |

## Excel输出格式

输出文件包含以下列：

| 列名 | 描述 | 单位 |
|------|------|------|
| link_id | 路段ID | - |
| link_length_km | 路段长度 | km |
| traffic_flow_vph | 交通流量 | 辆/小时 |
| avg_speed_kph | 平均速度 | km/h |
| CO2_kg_per_h | CO2排放率 | kg/h |
| NOx_kg_per_h | NOx排放率 | kg/h |
| PM2.5_kg_per_h | PM2.5排放率 | kg/h |

**注意**: 所有污染物使用 `kg/h` 单位

## 使用示例

### 示例1: Excel输入和输出（包含车型分布）

```python
from skills.macro_emission.skill import MacroEmissionSkill

skill = MacroEmissionSkill()
result = skill.execute(
    input_file="links_data.xlsx",
    output_file="emissions_output.xlsx",
    model_year=2020,
    pollutants=["CO2", "NOx", "PM2.5"],
    season="夏季"
)

if result.success:
    print(f"输出文件: {result.data['output_file']}")
    print(f"总排放: {result.data['summary']}")
```

### 示例2: 简化输入（不包含车型分布，使用默认值）

```python
# 输入文件只需要三列必需数据
# Excel: 路段长度 | 交通流量 | 平均速度
#        1.5     | 1000    | 60
#        2.0     | 1500    | 50

result = skill.execute(
    input_file="simple_links.xlsx",
    output_file="emissions_output.xlsx",
    model_year=2020,
    pollutants=["CO2"],
    season="夏季"
)

# 将使用默认车队组成:
# - Passenger Car: 70%
# - Passenger Truck: 20%
# - Light Commercial Truck: 5%
# - Transit Bus: 3%
# - Combination Long-haul Truck: 2%
```

### 示例3: CSV格式

```python
# 支持CSV格式输入和输出
result = skill.execute(
    input_file="links_data.csv",
    output_file="emissions_output.csv",
    model_year=2020,
    pollutants=["CO2", "NOx"],
    season="夏季"
)
```

### 示例4: 混合使用（数组输入，Excel输出）

```python
# 可以使用links_data数组输入，但输出到Excel
result = skill.execute(
    links_data=[
        {
            "link_length_km": 1.5,
            "traffic_flow_vph": 1000,
            "avg_speed_kph": 60,
            "fleet_mix": {"Passenger Car": 70, "Transit Bus": 30}
        },
        {
            "link_length_km": 2.0,
            "traffic_flow_vph": 1500,
            "avg_speed_kph": 50
        }
    ],
    output_file="emissions_output.xlsx",
    model_year=2020,
    pollutants=["CO2"],
    season="夏季"
)
```

## 自动处理功能

### 1. 路段ID自动生成

如果输入文件没有路段ID列，系统会自动生成：`Link_1`, `Link_2`, `Link_3`...

### 2. 车型分布自动归一化

如果车型百分比总和不等于100%，系统会自动归一化：

```python
# 输入: 乘用车 60%, 公交车 20%, 货车 30%  (总和 110%)
# 自动归一化为:
# 乘用车: 60/110*100 = 54.55%
# 公交车: 20/110*100 = 18.18%
# 货车: 30/110*100 = 27.27%
```

### 3. 默认车队组成

如果没有车型分布列或所有值为空，使用默认车队组成：

```python
DEFAULT_FLEET_MIX = {
    "Passenger Car": 70.0,
    "Passenger Truck": 20.0,
    "Light Commercial Truck": 5.0,
    "Transit Bus": 3.0,
    "Combination Long-haul Truck": 2.0,
}
```

## 列名识别

系统支持多种列名格式（不区分大小写）：

| 数据类型 | 支持的列名 |
|----------|-----------|
| 路段长度 | link_length_km, length_km, length, 路段长度, 长度 |
| 交通流量 | traffic_flow_vph, flow_vph, flow, traffic, 交通流量, 流量 |
| 平均速度 | avg_speed_kph, speed_kph, speed, 平均速度, 速度 |
| 路段ID | link_id, id, 路段ID, 路段编号 |

## 参数验证

### 必需参数
- `links_data` 或 `input_file`: 至少提供一个

### 可选参数
- `model_year`: 车辆年份（默认：2020）
- `pollutants`: 污染物列表（默认：["CO2", "NOx"]）
- `season`: 季节（默认：夏季）
- `default_fleet_mix`: 默认车队组成
- `output_file`: 输出文件路径

### 验证示例

```python
# 缺少路段数据
result = skill.execute(
    model_year=2020,
    pollutants=["CO2"]
)

# 返回
{
    "success": False,
    "error": "缺少必需参数: links_data/input_file",
    "metadata": {
        "missing_params": {
            "links_data": {
                "description": "路段数据或输入文件",
                "format": "[{\"link_length_km\": 1.5, \"traffic_flow_vph\": 1000, \"avg_speed_kph\": 60}, ...]",
                "note": "可以提供links_data数组，或使用input_file指定Excel文件路径"
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
    model_year=2020
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
    model_year=2020
)

# 返回
{
    "success": False,
    "error": "读取输入文件失败: 不支持的文件格式: .txt，仅支持 .xlsx, .xls, .csv"
}
```

### 3. 缺少必需列

```python
# Excel文件缺少必需列
result = skill.execute(
    input_file="invalid.xlsx",
    model_year=2020
)

# 返回
{
    "success": False,
    "error": "读取输入文件失败: 未找到路段长度列，支持的列名: link_length_km, length_km, length, 路段长度, 长度"
}
```

### 4. 输出文件写入失败

如果输出文件写入失败，计算结果仍然返回，但会包含警告：

```python
result = skill.execute(
    input_file="input.xlsx",
    output_file="/invalid/path/output.xlsx",
    model_year=2020
)

# 返回
{
    "success": True,
    "data": {
        "query_info": {...},
        "results": [...],
        "summary": {...},
        "output_file_warning": "写入输出文件失败: ..."
    }
}
```

## 测试

运行测试脚本：

```bash
cd D:\Agent_MCP\emission_agent
python test_macro_emission_excel.py
```

测试覆盖：
1. ✅ Excel输入和输出（完整数据，包含车型分布）
2. ✅ 简化Excel输入（不包含车型分布，使用默认值）
3. ✅ CSV格式输入/输出
4. ✅ 参数验证
5. ✅ 文件不存在错误处理

## 修改的文件

### 1. `skills/macro_emission/excel_handler.py`（新增）
- `read_links_from_excel()`: 读取Excel文件
- `write_results_to_excel()`: 写入Excel文件
- `_find_column()`: 查找列名
- `_identify_vehicle_columns()`: 识别车型分布列
- `_parse_fleet_mix()`: 解析车型分布并归一化

### 2. `skills/macro_emission/skill.py`（修改）
- 添加 `input_file` 和 `output_file` 参数
- 更新参数验证逻辑（links_data或input_file二选一）
- 修改 `execute` 方法支持文件输入/输出
- 添加 `ExcelHandler` 实例

### 3. `test_macro_emission_excel.py`（新增）
- 完整的测试套件
- 自动创建示例文件

## 性能考虑

- Excel读取使用 `pandas`，支持大文件
- 车型分布归一化的时间复杂度为 O(n)
- 输出文件写入为批量操作，性能良好
- 建议单次处理路段数不超过1000条

## 注意事项

1. **单位**:
   - 输入路段长度单位：km
   - 输入交通流量单位：辆/小时
   - 输入速度单位：km/h
   - 输出排放单位：kg/h

2. **列名不区分大小写**:
   - "Length", "length", "LENGTH" 都可以识别

3. **车型分布**:
   - 支持中文车型名称
   - 自动归一化到100%
   - 如果没有提供，使用默认分布

4. **向后兼容**:
   - 原有的 `links_data` 数组输入方式仍然支持
   - 可以混合使用（数组输入 + Excel输出）

5. **文件格式**:
   - 支持 `.xlsx`, `.xls`, `.csv`
   - CSV使用 UTF-8-BOM 编码（兼容Excel）

6. **错误恢复**:
   - 输出文件写入失败不影响计算结果
   - 会在结果中添加警告信息

7. **路段ID**:
   - 如果输入文件没有路段ID，自动生成
   - 生成格式：Link_1, Link_2, Link_3...
