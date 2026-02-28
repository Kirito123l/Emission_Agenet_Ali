# 原架构处理逻辑详细分析

## 概述

原架构采用 **Agent-Skill 模式**，支持两种输入方式：
- **文本描述输入** → 文本输出
- **文件输入** → 文件输出 + 文本描述

## 架构分层

```
用户请求
    ↓
EmissionAgent (legacy/agent/core.py)
    ├── Planning 阶段：理解意图，规划技能调用
    ├── Execution 阶段：执行技能
    └── Synthesis 阶段：综合生成回答
    ↓
Skills (legacy/skills/)
    ├── calculate_micro_emission (微观排放)
    ├── calculate_macro_emission (宏观排放)
    ├── query_emission_factors (排放因子查询)
    └── file_analyzer (文件分析)
    ↓
Calculators (共享计算逻辑)
    ├── MicroEmissionCalculator
    ├── MacroEmissionCalculator
    └── EmissionFactorCalculator
```

## 四个工具的处理逻辑

### 1. File Analyzer (文件分析器)

**位置**: `legacy/skills/common/file_analyzer.py`

**功能**: 预分析上传的文件，识别文件类型和结构

**输入**:
- `file_path`: 上传的文件路径

**处理流程**:
```
1. 读取文件 (CSV/Excel)
2. 分析列名和结构
3. 识别任务类型:
   - micro_emission: 有 time + speed 列
   - macro_emission: 有 length + flow + speed 列
4. 检测缺失列
5. 生成警告和建议
6. 返回分析结果
```

**输出**:
```json
{
  "success": true,
  "task_type": "micro_emission",
  "confidence": 0.95,
  "columns": ["t", "speed"],
  "row_count": 100,
  "column_analysis": {
    "time_column": "t",
    "speed_column": "speed"
  },
  "warnings": [],
  "sample_data": [...]
}
```

**特点**: 不进行计算，只分析文件结构

---

### 2. Calculate Micro Emission (微观排放计算)

**位置**: `legacy/skills/micro_emission/skill.py`

**功能**: 计算车辆逐秒排放量

**支持两种输入方式**:

#### 方式1: 文本描述输入
```python
{
  "vehicle_type": "大货车",
  "model_year": 2020,
  "pollutants": ["CO2", "NOx", "PM2.5"],
  "season": "夏季",
  "trajectory_data": [
    {"t": 0, "speed_kph": 60, "acceleration_mps2": 0.5},
    {"t": 1, "speed_kph": 65, "acceleration_mps2": 0.3},
    ...
  ]
}
```

#### 方式2: 文件输入
```python
{
  "vehicle_type": "大货车",
  "model_year": 2020,
  "pollutants": ["CO2", "NOx"],
  "season": "夏季",
  "input_file": "/path/to/trajectory.csv",  # 文件输入
  "output_file": "/path/to/output.xlsx"    # 可选：文件输出
}
```

**处理流程**:
```
1. 验证参数
   - 检查 vehicle_type (必需)
   - 检查 trajectory_data 或 input_file (二选一)

2. 获取轨迹数据
   文本输入: 直接使用 trajectory_data
   文件输入: 从 input_file 读取

3. 标准化参数
   - vehicle_type: "大货车" → "Combination Long-haul Truck"
   - pollutants: ["CO2", "NOx"] → ["CO2", "NOx"]
   - season: "夏季" → "夏季"

4. 执行计算
   调用 MicroEmissionCalculator.calculate()
   - 计算 VSP (Vehicle Specific Power)
   - 查询排放因子 (基于 speed, VSP, vehicle_type)
   - 计算逐秒排放量

5. 生成输出
   文本输出: 返回 SkillResult 包含 summary 和 data
   文件输出: 如果指定 output_file，生成 Excel

6. 生成下载文件
   如果有 input_file，自动生成结果文件供下载
```

**输出** (文本):
```python
SkillResult(
    success=True,
    data={
        "results": [...],  # 逐秒排放数据
        "summary": {
            "total_distance_km": 1.111,
            "total_time_s": 100,
            "total_emissions_g": {
                "CO2": 5820971.98,
                "NOx": 1900.40,
                "PM2.5": 27.36
            }
        }
    },
    summary="已计算微观排放...",
    metadata={
        "download_file": {
            "path": "/outputs/result.xlsx",
            "filename": "xxx_result.xlsx",
            "description": "包含原始数据和排放结果"
        }
    }
)
```

**输出** (文件):
- 如果指定 `output_file`: 生成指定路径的 Excel
- 如果有 `input_file`: 自动生成下载文件在 `outputs/` 目录

---

### 3. Calculate Macro Emission (宏观排放计算)

**位置**: `legacy/skills/macro_emission/skill.py`

**功能**: 计算路段排放量

**支持两种输入方式**:

#### 方式1: 文本描述输入
```python
{
  "links_data": [
    {
      "link_id": "L1",
      "link_length_km": 1.5,
      "traffic_flow_vph": 1000,
      "avg_speed_kph": 60,
      "fleet_mix": {"Car": 0.7, "Truck": 0.3}
    },
    ...
  ],
  "pollutants": ["CO2", "NOx"],
  "model_year": 2020,
  "season": "夏季"
}
```

#### 方式2: 文件输入
```python
{
  "input_file": "/path/to/links.xlsx",
  "output_file": "/path/to/output.xlsx",  # 可选
  "pollutants": ["CO2", "NOx"],
  "model_year": 2020,
  "season": "夏季"
}
```

**处理流程**:
```
1. 验证参数
   - 检查 links_data 或 input_file (二选一)

2. 获取路段数据
   文本输入: 直接使用 links_data
   文件输入: 从 input_file 读取

3. 自动修复常见错误
   - 字段名映射: length → link_length_km
   - 格式转换: fleet_mix 数组 → 对象

4. 标准化参数
   - pollutants 标准化
   - fleet_mix 车型标准化
   - season 标准化

5. 执行计算
   调用 MacroEmissionCalculator.calculate()
   - 查询排放因子 (基于 speed)
   - 计算路段总排放
   - 按车型分配排放

6. 生成输出
   文本输出: 返回 SkillResult
   文件输出: 生成 Excel
```

**输出** (文本):
```python
SkillResult(
    success=True,
    data={
        "results": [...],  # 各路段排放
        "summary": {
            "total_links": 10,
            "total_distance_km": 15.5,
            "total_emissions_g": {...}
        }
    },
    metadata={"download_file": {...}}
)
```

---

### 4. Query Emission Factors (排放因子查询)

**位置**: `legacy/skills/emission_factors/skill.py`

**功能**: 查询指定车型的排放因子

**只支持文本输入**:
```python
{
  "vehicle_type": "小汽车",
  "model_year": 2020,
  "pollutants": ["CO2", "NOx"],
  "season": "夏季",
  "return_curve": False  # 是否返回完整曲线
}
```

**处理流程**:
```
1. 验证参数
   - vehicle_type (必需)
   - model_year (必需)

2. 标准化参数

3. 查询排放因子
   调用 EmissionFactorCalculator.query()
   - 从 Atlanta MOVES 数据库查询
   - 基于 speed bins

4. 返回结果
   如果 return_curve=False: 返回关键速度点的排放因子
   如果 return_curve=True: 返回完整速度曲线
```

**输出**:
```python
SkillResult(
    success=True,
    data={
        "factors": {
            "CO2": {
                "30km/h": 150.5,
                "60km/h": 180.2,
                ...
            }
        }
    },
    summary="已查询排放因子..."
)
```

---

## Synthesis 阶段 (综合生成回答)

**位置**: `legacy/agent/core.py` → `_synthesize()` 方法

**功能**: 将多个技能的执行结果综合成自然的用户回答

**处理流程**:
```
1. 获取对话上下文
   context = self._context.build_context_for_synthesis()

2. 过滤结果数据
   filtered_results = self._filter_results_for_synthesis(results)
   - 移除详细行数据
   - 保留汇总信息
   - 保留样本数据

3. 检测是否有 input_file
   决定回答格式:
   - 有文件: 强调文件输入/输出
   - 无文件: 强调文本描述

4. 构建合成提示词
   包含:
   - 对话上下文
   - 当前问题
   - 理解结果
   - 执行结果 (过滤后)
   - 错误信息

5. 调用 synthesis LLM
   response = self._synthesis_llm.chat(prompt)

6. 返回自然语言回答
```

**Synthesis Prompt 要求**:
```python
SYNTHESIS_PROMPT = """
## 回答要求

1. **基于结果回答**: 只使用执行结果中的数据，不要编造
2. **引用历史**: 如果用户提到"刚才"、"之前"，从上下文中引用
3. **参数说明**: 说明使用了哪些参数
4. **格式清晰**: 使用表格展示汇总数据
5. **不要编造排放因子**: 不要显示编造的排放因子数据
6. **不要重复展示详细数据**: results_sample 仅供参考，不要列出详细数据
"""
```

---

## 输入输出对应关系总结

| 工具 | 文本输入 | 文件输入 | 文本输出 | 文件输出 |
|------|---------|---------|---------|---------|
| **file_analyzer** | - | ✅ | ✅ | - |
| **calculate_micro_emission** | ✅ | ✅ | ✅ | ✅ (可选) |
| **calculate_macro_emission** | ✅ | ✅ | ✅ | ✅ (可选) |
| **query_emission_factors** | ✅ | - | ✅ | - |

### 关键设计原则

1. **文件输入处理**:
   - 使用 `ExcelHandler` 读取 CSV/Excel
   - 智能列名映射 (支持各种列名格式)
   - 自动处理数据格式

2. **文件输出处理**:
   - `output_file` 参数: 用户指定输出路径
   - 自动生成下载文件: 如果有 `input_file`，在 `outputs/` 生成结果文件
   - 文件包含: 原始数据 + 排放结果

3. **文本输出处理**:
   - `summary` 字段: 简短描述
   - `data` 字段: 详细数据 (过滤后用于 synthesis)
   - `metadata` 字段: 元信息 (下载文件、标准化信息等)

4. **错误处理**:
   - 参数缺失 → 返回 needs_clarification
   - 数据格式错误 → 返回具体错误信息
   - 计算失败 → 返回错误原因

---

## 与新架构的差异

| 方面 | 原架构 (Agent-Skill) | 新架构 (Tool Use) |
|------|---------------------|-------------------|
| **调用方式** | Agent 规划 + 执行 | LLM 直接调用工具 |
| **Synthesis** | 专门的 synthesis LLM | router.py 的 _synthesize_results() |
| **参数标准化** | Skill 内部处理 | Executor 透明处理 |
| **文件路径参数** | `input_file` / `output_file` | `file_path` |
| **错误重试** | Agent 自动重试 | Router 处理 |
| **上下文记忆** | ConversationContext | Memory |

---

## 需要注意的关键点

### 1. 参数名称差异

**原架构 (skills/)**:
- 使用 `input_file` / `output_file`
- 在 Skill 内部处理文件 I/O

**新架构 (tools/)**:
- 工具定义使用 `file_path`
- 工具实现期望 `input_file`
- 需要参数映射

### 2. Synthesis 的重要性

原架构的 synthesis 非常严格：
- 只使用 results 中的数据
- 不编造任何信息
- 清晰的格式要求

新架构需要加强 SYNTHESIS_PROMPT，防止 LLM 幻觉。

### 3. 文件自动生成

原架构：
- 如果有 `input_file`，自动生成下载文件
- 生成位置: `outputs/` 目录

新架构需要保持这个行为。

---

## 下一步建议

1. **统一参数名称**:
   - 工具定义和实现使用相同名称
   - 或者保持映射逻辑

2. **强化 Synthesis Prompt**:
   - 明确禁止编造数据
   - 强制只使用工具返回的数据
   - 不允许添加"分析"和"推断"

3. **修复计算器单位问题**:
   - 检查 CO2 排放为何异常高 (5,000 倍)
   - 验证单位转换逻辑

4. **保持文件 I/O 行为**:
   - 确保 `input_file` → 自动生成下载文件
   - 确保 `output_file` → 生成指定路径文件
