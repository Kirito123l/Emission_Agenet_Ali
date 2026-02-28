# 排放因子Skill曲线返回功能文档

## 概述

排放因子Skill已升级，支持返回完整的速度-排放曲线数据，并支持同时查询多个污染物。

## 新增参数

### 1. `return_curve: bool = False`
- **描述**: 是否返回完整的速度-排放曲线数据
- **默认值**: `False`（保持向后兼容）
- **类型**: 布尔值

### 2. `pollutants: List[str] = None`
- **描述**: 多个污染物列表
- **类型**: 字符串列表
- **示例**: `["CO2", "NOx", "PM2.5"]`
- **注意**: 与 `pollutant` 参数二选一

### 3. `pollutant: str = None`（已改为可选）
- **描述**: 单个污染物（向后兼容）
- **类型**: 字符串
- **注意**: 与 `pollutants` 参数二选一

## 使用示例

### 示例1: 单个污染物，不返回曲线（向后兼容）

```python
from skills.emission_factors.skill import EmissionFactorsSkill

skill = EmissionFactorsSkill()
result = skill.execute(
    vehicle_type="小汽车",
    pollutant="CO2",
    model_year=2020,
    season="夏季"
)

# 返回格式（传统格式）
{
    "success": True,
    "data": {
        "query_summary": {...},
        "speed_curve": [...],  # 包含mph和kph
        "typical_values": [...],  # 25, 50, 70 mph的典型值
        "speed_range": {...},
        "data_points": 73,
        "unit": "g/mile",
        "data_source": "MOVES (Atlanta)"
    }
}
```

### 示例2: 单个污染物，返回曲线

```python
result = skill.execute(
    vehicle_type="小汽车",
    pollutant="CO2",
    model_year=2020,
    season="夏季",
    return_curve=True
)

# 返回格式（新格式）
{
    "success": True,
    "data": {
        "vehicle_type": "Passenger Car",
        "model_year": 2020,
        "pollutants": {
            "CO2": {
                "curve": [
                    {"speed_kph": 8.0, "emission_rate": 534.9938},
                    {"speed_kph": 9.7, "emission_rate": 460.4111},
                    ...
                ],
                "unit": "g/km",
                "speed_range": {
                    "min_kph": 8.0,
                    "max_kph": 123.9
                },
                "data_points": 73
            }
        },
        "metadata": {
            "season": "夏季",
            "road_type": "快速路",
            "speed_range_kph": [8.0, 123.9]
        }
    }
}
```

### 示例3: 多个污染物，返回曲线

```python
result = skill.execute(
    vehicle_type="公交车",
    pollutants=["CO2", "NOx", "PM2.5"],
    model_year=2020,
    season="夏季",
    return_curve=True
)

# 返回格式
{
    "success": True,
    "data": {
        "vehicle_type": "Transit Bus",
        "model_year": 2020,
        "pollutants": {
            "CO2": {
                "curve": [
                    {"speed_kph": 8.0, "emission_rate": 2876.6575},
                    ...
                ],
                "unit": "g/km",
                "speed_range": {"min_kph": 8.0, "max_kph": 123.9},
                "data_points": 73
            },
            "NOx": {
                "curve": [
                    {"speed_kph": 8.0, "emission_rate": 1.9702},
                    ...
                ],
                "unit": "g/km",
                "speed_range": {"min_kph": 8.0, "max_kph": 123.9},
                "data_points": 73
            },
            "PM2.5": {
                "curve": [
                    {"speed_kph": 8.0, "emission_rate": 0.0232},
                    ...
                ],
                "unit": "g/km",
                "speed_range": {"min_kph": 8.0, "max_kph": 123.9},
                "data_points": 73
            }
        },
        "metadata": {
            "season": "夏季",
            "road_type": "快速路",
            "speed_range_kph": [8.0, 123.9]
        }
    }
}
```

### 示例4: 多个污染物，不返回曲线

```python
result = skill.execute(
    vehicle_type="小汽车",
    pollutants=["CO2", "NOx"],
    model_year=2020,
    season="夏季",
    return_curve=False
)

# 返回格式（每个污染物使用传统格式）
{
    "success": True,
    "data": {
        "vehicle_type": "Passenger Car",
        "model_year": 2020,
        "pollutants": {
            "CO2": {
                "query_summary": {...},
                "speed_curve": [...],
                "typical_values": [...],
                "speed_range": {...},
                "data_points": 73,
                "unit": "g/mile",
                "data_source": "MOVES (Atlanta)"
            },
            "NOx": {
                "query_summary": {...},
                "speed_curve": [...],
                "typical_values": [...],
                "speed_range": {...},
                "data_points": 73,
                "unit": "g/mile",
                "data_source": "MOVES (Atlanta)"
            }
        },
        "metadata": {
            "season": "夏季",
            "road_type": "快速路",
            "speed_range_kph": [8.0, 123.9]
        }
    }
}
```

## 数据格式说明

### 曲线数据格式（return_curve=True）

```json
{
    "curve": [
        {
            "speed_kph": 8.0,
            "emission_rate": 534.9938
        },
        {
            "speed_kph": 9.7,
            "emission_rate": 460.4111
        }
    ],
    "unit": "g/km",
    "speed_range": {
        "min_kph": 8.0,
        "max_kph": 123.9
    },
    "data_points": 73
}
```

### 传统数据格式（return_curve=False）

```json
{
    "speed_curve": [
        {
            "speed_mph": 5,
            "speed_kph": 8.0,
            "emission_rate": 860.6,
            "unit": "g/mile"
        }
    ],
    "typical_values": [
        {
            "label": "25 mph (40.2 kph)",
            "speed_mph": 25,
            "speed_kph": 40.2,
            "emission_rate": 245.3,
            "unit": "g/mile"
        }
    ]
}
```

## 单位转换

- **传统格式**: `g/mile`（英里克数）
- **曲线格式**: `g/km`（公里克数）
- **转换公式**: `g/km = g/mile / 1.60934`

## 向后兼容性

✅ **完全向后兼容**

- 单个污染物 + `return_curve=False`（默认）→ 返回传统格式
- 所有现有代码无需修改即可继续工作

## 参数验证

### 必需参数
- `vehicle_type`: 车型
- `model_year`: 车辆年份
- `pollutant` 或 `pollutants`: 至少提供一个

### 可选参数
- `season`: 季节（默认：夏季）
- `road_type`: 道路类型（默认：快速路）
- `return_curve`: 是否返回曲线（默认：False）

### 验证示例

```python
# 缺少污染物参数
result = skill.execute(
    vehicle_type="小汽车",
    model_year=2020
)

# 返回
{
    "success": False,
    "error": "缺少必需参数: pollutant/pollutants",
    "metadata": {
        "missing_params": {
            "pollutant": {
                "description": "污染物（单个或多个）",
                "examples": ["CO2", "NOx", "PM2.5", "CO"],
                "note": "可以使用pollutant指定单个污染物，或使用pollutants指定多个污染物列表"
            }
        },
        "needs_clarification": True
    }
}
```

## 性能考虑

- 多个污染物查询会依次执行，每个污染物一次数据库查询
- 建议一次查询不超过5个污染物
- 曲线数据通常包含70-80个数据点

## 测试

运行测试脚本：

```bash
cd D:\Agent_MCP\emission_agent
python test_emission_factors_curve.py
```

测试覆盖：
1. ✅ 单个污染物，不返回曲线（向后兼容）
2. ✅ 单个污染物，返回曲线
3. ✅ 多个污染物，返回曲线
4. ✅ 多个污染物，不返回曲线
5. ✅ 参数验证

## 修改的文件

1. `skills/emission_factors/skill.py`
   - 添加 `pollutants` 和 `return_curve` 参数
   - 更新参数验证逻辑
   - 重写 `execute` 方法支持多污染物查询
   - 添加辅助方法 `_get_defaults_used` 和 `_get_speed_range`

2. `skills/emission_factors/calculator.py`
   - 添加 `return_curve` 参数到 `query` 方法
   - 实现曲线数据格式（g/km单位）
   - 保持传统格式的向后兼容性

3. `test_emission_factors_curve.py`（新增）
   - 完整的测试套件

## 注意事项

1. **单位差异**: 曲线格式使用 `g/km`，传统格式使用 `g/mile`
2. **数据结构**: 多污染物或曲线模式下，数据结构会改变
3. **向后兼容**: 单个污染物 + 不返回曲线 = 传统格式
4. **标准化**: 使用现有的车型和污染物标准化机制
