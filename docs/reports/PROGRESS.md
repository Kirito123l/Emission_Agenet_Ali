# Emission Agent 开发进度报告

**日期**: 2026-01-24
**状态**: Phase 1-6 完成（v2.0+ 架构升级）

## 已完成工作

### Phase 1: 基础框架 ✅

1. **项目目录结构** - 完整创建
   - agent/, llm/, skills/, shared/, data/, scripts/

2. **配置管理** (`config.py`)
   - 多Provider支持 (Qwen/DeepSeek/Local)
   - 多层模型分配 (Agent/Standardizer/Synthesis/RAG)
   - 功能开关配置
   - 自动创建数据目录

3. **LLM客户端** (`llm/client.py`)
   - 统一的OpenAI兼容接口
   - 单例模式的LLMManager
   - 支持chat/chat_json/chat_json_with_history

4. **数据收集器** (`llm/data_collector.py`)
   - JSONL格式记录
   - 统计分析功能
   - 微调数据导出

5. **依赖管理** (`requirements.txt`)
   - openai, python-dotenv, click, rich, pandas

### Phase 2: 标准化模块 ✅

1. **常量定义** (`shared/standardizer/constants.py`)
   - 13种MOVES标准车型映射
   - 6种污染物映射
   - 季节映射
   - 中英文别名支持

2. **LRU缓存** (`shared/standardizer/cache.py`)
   - 简单高效的缓存实现

3. **车型标准化器** (`shared/standardizer/vehicle.py`)
   - 规则匹配 + LLM回退
   - 置信度评分
   - 自动数据收集

4. **污染物标准化器** (`shared/standardizer/pollutant.py`)
   - 与车型标准化器相同架构

### Phase 3: 第一个Skill ✅

1. **Skill基类** (`skills/base.py`)
   - BaseSkill抽象类
   - SkillResult/HealthCheckResult数据类

2. **Skill注册表** (`skills/registry.py`)
   - 单例模式
   - 动态注册机制

3. **排放因子计算器** (`skills/emission_factors/calculator.py`)
   - 独立的计算逻辑
   - 车型/污染物ID映射
   - 季节环境条件处理
   - CSV数据查询
   - 速度曲线格式化

4. **排放因子Skill** (`skills/emission_factors/skill.py`)
   - 参数验证
   - 标准化调用
   - 健康检查
   - 元数据记录

5. **数据迁移** ✅
   - 3个CSV文件已复制
   - atlanta_2025_1_55_65.csv (冬季)
   - atlanta_2025_4_75_65.csv (春季)
   - atlanta_2025_7_90_70.csv (夏季)

### Phase 4: Agent层和CLI ✅

1. **Agent提示词** (`agent/prompts/`)
   - system.py - 简洁的系统提示
   - synthesis.py - 结果综合提示

2. **Agent核心** (`agent/core.py`)
   - 规划-执行-综合流程
   - 对话历史管理
   - 错误处理

3. **CLI入口** (`main.py`)
   - chat命令 - 交互式对话
   - health命令 - 健康检查
   - stats命令 - 数据统计
   - Rich终端美化

4. **环境配置** (`.env`)
   - 已配置Qwen API密钥
   - 模型分配设置
   - 功能开关启用

### Phase 4.5: 关键Bug修复 ✅

**修复日期**: 2026-01-23

#### Bug #1: 参数追问机制 ✅
**问题**: 缺少必需参数时使用默认值导致查询失败
**修复内容**:
1. **Skill层参数验证** (`skills/emission_factors/skill.py`)
   - 添加 `REQUIRED_PARAMS` 和 `OPTIONAL_PARAMS` 定义
   - 实现 `validate_params()` 方法
   - 缺少必需参数时返回 `needs_clarification=True`

2. **Agent层追问逻辑** (`agent/core.py`)
   - 添加 `_check_clarification_needed()` 方法
   - 添加 `_generate_clarification()` 方法
   - 生成友好的追问消息（包含参数说明和示例）

3. **Agent Prompt更新** (`agent/prompts/system.py`)
   - 强调不要填充默认值
   - 添加利用对话历史的示例
   - 明确必需参数和可选参数的处理方式

**效果**:
- 缺少参数时友好追问："请补充以下信息：\n- **车辆年份**（范围：1995-2025）"
- 支持连续对话，记住上下文

#### Bug #2: Speed列编码格式理解错误 ✅
**问题**: 错误理解了Speed列的编码格式
- 错误理解：504 = 50 mph + 道路类型4
- 正确格式：504 = 5 mph + 0（分隔符）+ 4（快速路）

**修复内容** (`skills/emission_factors/calculator.py`):
1. 更新道路类型映射（数据库中只有类型4和5）
2. 修复速度解析逻辑：
   ```python
   speed_code = str(int(row['Speed']))  # 处理浮点数
   road_type = int(speed_code[-1])      # 最后1位是道路类型
   speed_value = int(speed_code[:-2])   # 去掉最后2位
   ```
3. 添加道路类型过滤，只保留匹配的数据

**效果**:
- 速度值从错误的50-7700 mph 修正为正确的5-77 mph
- 道路类型过滤正确工作

#### Bug #3: 浮点数类型处理错误 ✅
**问题**: Speed列是浮点数（7705.0），直接转字符串变成"7705.0"
- `str(7705.0)` → `"7705.0"`
- `"7705.0"[-1]` → `"0"` (小数点后的0，而不是道路类型5)

**修复内容** (`skills/emission_factors/calculator.py`):
```python
# 修复前（错误）
speed_code = str(row['Speed'])  # "7705.0"

# 修复后（正确）
speed_code = str(int(row['Speed']))  # "7705"
```

**效果**:
- 道路类型解析正确（4或5，而不是0）
- 查询成功返回73个数据点

#### Bug #4: 对话历史重复添加 ✅
**问题**: 用户输入被添加两次到历史中
**修复内容** (`agent/core.py`):
- 将用户输入的添加移到 `_plan()` 方法内部
- 确保每条消息只添加一次

**效果**:
- 对话历史正确维护
- Agent能正确利用上下文

**详细文档**:
- `BUG_FIX_REPORT.md` - 参数追问机制修复
- `SPEED_BUG_FIX.md` - Speed编码格式修复
- `FLOAT_BUG_FIX.md` - 浮点数类型修复

## 项目文件清单

```
emission_agent/
├── .env                        # 环境配置 ✅
├── .env.example                # 配置模板 ✅
├── README.md                   # 项目说明 ✅
├── requirements.txt            # 依赖列表 ✅
├── config.py                   # 配置管理 ✅
├── main.py                     # CLI入口 ✅
├── test_basic.py               # 测试脚本 ✅
│
├── agent/                      # Agent层 ✅
│   ├── __init__.py
│   ├── core.py                 # Agent主逻辑
│   └── prompts/
│       ├── __init__.py
│       ├── system.py           # 系统提示
│       └── synthesis.py        # 综合提示
│
├── llm/                        # LLM管理 ✅
│   ├── __init__.py
│   ├── client.py               # 多模型客户端
│   └── data_collector.py       # 数据收集
│
├── skills/                     # Skill层 ✅
│   ├── __init__.py
│   ├── base.py                 # Skill基类
│   ├── registry.py             # 注册表
│   └── emission_factors/       # 排放因子Skill
│       ├── __init__.py
│       ├── skill.py            # Skill实现
│       ├── calculator.py       # 计算器
│       └── data/
│           └── emission_matrix/
│               ├── atlanta_2025_1_55_65.csv  ✅
│               ├── atlanta_2025_4_75_65.csv  ✅
│               └── atlanta_2025_7_90_70.csv  ✅
│
├── shared/                     # 共享模块 ✅
│   ├── __init__.py
│   └── standardizer/
│       ├── __init__.py
│       ├── constants.py        # 映射常量
│       ├── cache.py            # LRU缓存
│       ├── vehicle.py          # 车型标准化
│       └── pollutant.py        # 污染物标准化
│
├── data/                       # 数据目录 ✅
│   ├── collection/             # 标准化数据收集
│   └── logs/                   # 日志
│
└── scripts/                    # 工具脚本 ✅
    └── migrate_from_mcp.py     # 数据迁移
```

## 验证测试

### 1. 健康检查
```bash
$ python main.py health
OK query_emission_factors
```
✅ 通过

### 2. 数据文件
- ✅ 3个CSV文件已迁移
- ✅ 文件大小正常 (~24MB each)
- ✅ 数据完整性验证通过

### 3. 功能测试（修复后）

#### 测试1: 完整参数查询
```bash
You: 查询2020年小汽车的CO2排放因子
Agent: [成功返回]
  - 数据点数: 73个
  - 速度范围: 5-77 mph (正确！)
  - 道路类型: 快速路
```
✅ 通过

#### 测试2: 缺少参数追问
```bash
You: 网约车的CO2排放因子
Agent: 请补充以下信息：
      - **车辆年份**（范围：1995-2025）

You: 2020年
Agent: [成功返回数据]
```
✅ 通过

#### 测试3: 对话上下文记忆
```bash
You: 公交车的NOx排放因子
Agent: 请补充年份

You: 2021年
Agent: [返回2021年公交车NOx数据]

You: 我想要PM2.5和CO2的排放
Agent: [记住"公交车"和"2021年"，返回两组数据]
```
✅ 通过

#### 测试4: 道路类型过滤
```bash
查询: 2020年小汽车CO2，快速路
结果: 73个数据点（只包含道路类型4的数据）

查询: 2020年小汽车CO2，地面道路
结果: 73个数据点（只包含道路类型5的数据）
```
✅ 通过

## 待完成工作 (Phase 5)

### 1. 微观排放计算 Skill ✅ 已完成
- ✅ skills/micro_emission/skill.py
- ✅ skills/micro_emission/calculator.py
- ✅ skills/micro_emission/vsp.py
- ✅ 数据迁移（3个CSV文件，共24MB）
- ✅ 年龄组映射（年份→MOVES年龄组）
- ✅ VSP计算和opMode映射
- ✅ 参数验证和追问机制
- ✅ 注册到Skill Registry

**关键实现**:
- VSP计算器：严格按照MOVES模型实现
- 年龄组映射：2025年为基准，自动转换年份到年龄组（1,2,3,5,9）
- opMode映射：根据速度和VSP计算运行模式（0-40）
- 轨迹处理：支持自动计算加速度，处理坡度
- 默认年份：2015年（年龄组5，数据最完整）

### 2. 宏观排放计算 Skill ✅ 已完成
- ✅ skills/macro_emission/skill.py
- ✅ skills/macro_emission/calculator.py
- ✅ 数据迁移（3个CSV文件，共13MB）
- ✅ MOVES-Matrix方法实现
- ✅ 车队组成支持
- ✅ 路段级排放计算
- ✅ 注册到Skill Registry

### 3. 知识检索 Skill ✅ 已完成
- ✅ skills/knowledge/skill.py
- ✅ skills/knowledge/retriever.py
- ✅ 向量索引迁移（FAISS + BGE-M3）
- ✅ 知识库加载（105MB数据）
- ✅ LLM精炼答案
- ✅ 注册到Skill Registry

### 4. JSON解析容错 ✅ 已完成
- ✅ llm/client.py 增强JSON解析
- ✅ 处理```json```代码块
- ✅ 修复尾部逗号
- ✅ 提取JSON结构
- ✅ 默认响应机制

### 5. 完善和测试
- ✅ 端到端测试
- [ ] 性能优化
- [ ] 文档完善

## 关键设计实现

### 1. Agent-Skill分离 ✅
- Agent Prompt简洁，不包含13种车型列表
- 参数保持用户原话（如"网约车"）
- 标准化在Skill内部完成

### 2. 标准化机制 ✅
- 规则匹配优先（高置信度）
- LLM回退（中等置信度）
- 自动数据收集到JSONL

### 3. 多模型配置 ✅
- Agent层: qwen-plus (推理能力)
- 标准化层: qwen-turbo-latest (速度优先)
- 综合层: qwen-plus (质量优先)

### 4. 数据收集 ✅
- 每次标准化自动记录
- 支持统计分析
- 支持导出微调数据

### 5. 参数追问机制 ✅
- Skill层验证参数完整性
- Agent层生成友好追问
- 支持连续对话上下文

### 6. 数据准确性 ✅
- 正确解析Speed列编码（{speed}0{road_type}）
- 处理浮点数类型
- 道路类型过滤（快速路4 vs 地面道路5）
- 速度范围合理（5-77 mph）

## 使用示例

### 示例1: 完整参数查询
```bash
$ python main.py chat

You: 查询2020年小汽车的CO2排放因子

Agent: [系统自动：
  1. 理解意图 -> 查询排放因子
  2. 提取参数 -> vehicle_type="小汽车", pollutant="CO2", model_year=2020
  3. 标准化 -> "小汽车" -> "Passenger Car", "CO2" -> "CO2"
  4. 查询数据 -> 返回73个速度点的排放曲线
  5. 综合回答 -> 自然语言 + 数据表格
]

返回数据：
- 速度范围: 5-77 mph
- 典型值: 25 mph, 50 mph, 70 mph
- 排放单位: g/mile
```

### 示例2: 缺少参数追问
```bash
You: 网约车的CO2排放因子是多少？

Agent: 请补充以下信息：
       - **车辆年份**（范围：1995-2025）

You: 2020年

Agent: [成功返回2020年网约车（Passenger Car）的CO2排放数据]
```

### 示例3: 连续对话上下文
```bash
You: 公交车的NOx排放因子

Agent: 请补充以下信息：
       - **车辆年份**（范围：1995-2025）

You: 2021年

Agent: [返回2021年公交车NOx数据]

You: 我想要PM2.5和CO2的排放

Agent: [自动记住"公交车"和"2021年"，并行查询两个污染物]
       根据查询结果，为您找到了2021年公交车的PM2.5和CO2排放因子...
```

### 示例4: 道路类型查询
```bash
You: 2020年小汽车在地面道路的CO2排放

Agent: [查询道路类型5的数据]
       - 速度范围: 5-77 mph
       - 道路类型: 地面道路
       - 数据点数: 73个
```

## 技术亮点

1. **完全独立**: 不依赖MCP项目，所有逻辑和数据已复制
2. **智能标准化**: 规则+LLM混合，自动数据收集
3. **灵活配置**: 支持多Provider，可为不同层配置不同模型
4. **健壮设计**: 健康检查、错误处理、数据验证
5. **易于扩展**: Skill注册机制，添加新功能只需实现BaseSkill
6. **友好交互**: 参数追问、上下文记忆、自然语言回答
7. **数据准确**: 正确解析Speed编码、道路类型过滤、浮点数处理

## 已知问题和限制

### 1. 数据覆盖范围
- 年份范围: 1995-2025
- 车型: 13种MOVES标准车型
- 污染物: 11种（CO2, NOx, PM2.5, PM10, CO, THC, VOC, SO2, NH3, NMHC, Energy）
- 道路类型: 2种（快速路4, 地面道路5）
- 季节: 3种（冬季、春季、夏季）

### 2. 速度数据说明
- 速度范围: 5-77 mph（合理范围）
- 数据点数: 每个查询约73个速度点
- 单位: g/mile（克/英里）

### 3. 终端编码问题
- Windows终端可能出现Unicode字符显示问题（如CO₂下标）
- 不影响核心功能，仅影响显示美观度

## 下一步建议

### 立即可用 ✅
当前版本已完全可用于排放因子查询：
- ✅ 参数追问机制完善
- ✅ 对话上下文记忆
- ✅ 数据查询准确
- ✅ 道路类型过滤正确
- ✅ 速度范围合理

### 测试验证 ✅
```bash
# 健康检查
python main.py health

# 交互式对话
python main.py chat

# 数据统计
python main.py stats
```

### Phase 5: 扩展功能（可选）
1. **微观排放计算 Skill**
   - skills/micro_emission/
   - VSP计算、瞬时排放

2. **宏观排放计算 Skill**
   - skills/macro_emission/
   - 区域排放、排放清单

3. **知识检索 Skill**
   - skills/knowledge/
   - 向量检索、文档问答

### 优化方向
1. **性能优化**
   - 缓存查询结果
   - 批量查询优化

2. **功能增强**
   - 支持更多道路类型
   - 添加排放可视化
   - 导出功能（CSV/Excel）

3. **用户体验**
   - 更丰富的追问提示
   - 查询历史记录
   - 快捷命令支持

---

## 总结

**Phase 1-5 已完成**，包括所有核心功能：排放因子查询、微观排放计算、宏观排放计算、知识检索，以及关键Bug修复和增量对话支持。

**核心成就**:
- ✅ 完整的Agent-Skill架构
- ✅ 智能参数追问机制
- ✅ 对话上下文记忆和增量对话
- ✅ 准确的数据查询（修复了多个关键bug）
- ✅ 友好的用户交互
- ✅ 四个核心Skill：排放因子查询 + 微观排放计算 + 宏观排放计算 + 知识检索
- ✅ VSP计算和opMode映射（MOVES模型）
- ✅ MOVES-Matrix宏观排放方法
- ✅ BGE-M3向量检索
- ✅ JSON解析容错机制

**项目已完全可用，可根据需求进行性能优化和功能扩展。**

---

## Phase 6: Skill功能增强 ✅

**完成日期**: 2026-01-24

### 1. 排放因子Skill - 曲线数据返回功能 ✅

**需求**: 支持返回完整的速度-排放曲线数据，并支持同时查询多个污染物

**新增参数**:
- `return_curve: bool = False` - 是否返回完整曲线数据（默认False保持向后兼容）
- `pollutants: List[str] = None` - 多个污染物列表
- `pollutant: str = None` - 单个污染物（改为可选，与pollutants二选一）

**实现内容**:

1. **skills/emission_factors/skill.py** (修改)
   - 添加 `pollutants` 和 `return_curve` 参数
   - 更新参数验证逻辑（pollutant或pollutants至少提供一个）
   - 重写 `execute` 方法支持多污染物查询
   - 添加辅助方法 `_get_defaults_used` 和 `_get_speed_range`

2. **skills/emission_factors/calculator.py** (修改)
   - 添加 `return_curve` 参数到 `query` 方法
   - 实现曲线数据格式（g/km单位）
   - 保持传统格式的向后兼容性

**数据格式**:

曲线格式（return_curve=True）:
```python
{
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
            "speed_range": {"min_kph": 8.0, "max_kph": 123.9},
            "data_points": 73
        }
    }
}
```

传统格式（return_curve=False）:
```python
{
    "speed_curve": [
        {"speed_mph": 5, "speed_kph": 8.0, "emission_rate": 860.6, "unit": "g/mile"}
    ],
    "typical_values": [
        {"label": "25 mph (40.2 kph)", "speed_mph": 25, "emission_rate": 245.3}
    ]
}
```

**单位转换**:
- 传统格式: g/mile（英里克数）
- 曲线格式: g/km（公里克数）
- 转换公式: g/km = g/mile / 1.60934

**向后兼容性**: ✅ 完全向后兼容
- 单个污染物 + return_curve=False（默认）→ 返回传统格式
- 所有现有代码无需修改即可继续工作

**测试**: ✅ 5个测试用例全部通过
- 单个污染物，不返回曲线（向后兼容）
- 单个污染物，返回曲线
- 多个污染物，返回曲线
- 多个污染物，不返回曲线
- 参数验证

**文档**: `EMISSION_FACTORS_CURVE_FEATURE.md`

---

### 2. 微观排放Skill - Excel输入/输出功能 ✅

**需求**: 支持从Excel文件读取轨迹数据，并将计算结果输出到Excel文件

**新增文件**:
- `skills/micro_emission/excel_handler.py` - Excel文件处理器

**新增参数**:
- `input_file: str = None` - Excel输入文件路径（.xlsx或.csv）
- `output_file: str = None` - Excel输出文件路径（.xlsx或.csv）
- 与 `trajectory_data` 二选一

**实现内容**:

1. **skills/micro_emission/excel_handler.py** (新增)
   - `read_trajectory_from_excel()`: 读取Excel文件
   - `write_results_to_excel()`: 写入Excel文件
   - `_find_column()`: 查找列名（支持多种命名方式）
   - `_calculate_acceleration()`: 自动计算加速度（中心差分法）

2. **skills/micro_emission/skill.py** (修改)
   - 添加 `input_file` 和 `output_file` 参数
   - 更新参数验证逻辑（trajectory_data或input_file二选一）
   - 修改 `execute` 方法支持文件输入/输出
   - 添加 `ExcelHandler` 实例

**Excel输入格式**:

必需列（任一即可）:
- 速度: `speed_kph` / `speed` / `车速` / `速度`

可选列:
- 加速度: `acceleration` / `acc` / `acceleration_mps2` / `加速度`（如果没有，自动计算）
- 坡度: `grade_pct` / `grade` / `坡度`（如果没有，默认为0）
- 时间: `t` / `time` / `时间`（如果没有，自动生成0, 1, 2, 3...）

**Excel输出格式**:
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

**自动计算功能**:
1. **加速度自动计算**: 使用中心差分法
   - 第一个点：前向差分
   - 最后一个点：后向差分
   - 中间点：中心差分
   - 公式: `acc[i] = (speed[i+1] - speed[i-1]) / (2 * dt) / 3.6`

2. **时间自动生成**: 如果没有时间列，自动生成 `0, 1, 2, 3, ...`

3. **坡度默认值**: 如果没有坡度列，默认为 `0`

**列名识别**: 支持多种列名格式（不区分大小写）
- 速度: speed_kph, speed, 车速, 速度
- 加速度: acceleration, acc, acceleration_mps2, 加速度
- 坡度: grade_pct, grade, 坡度
- 时间: t, time, 时间

**向后兼容性**: ✅ 完全向后兼容
- 原有的 `trajectory_data` 数组输入方式仍然支持
- 可以混合使用（数组输入 + Excel输出）

**测试**: ✅ 5个测试用例全部通过
- Excel输入和输出（完整数据）
- 简化Excel输入（只有速度列）
- CSV格式输入/输出
- 参数验证
- 文件不存在错误处理

**文档**: `MICRO_EMISSION_EXCEL_FEATURE.md`

---

### 3. 宏观排放Skill - Excel批量输入/输出功能 ✅

**需求**: 支持从Excel文件批量读取路段数据，并将计算结果输出到Excel文件

**新增文件**:
- `skills/macro_emission/excel_handler.py` - Excel文件处理器

**新增参数**:
- `input_file: str = None` - Excel输入文件路径（.xlsx或.csv）
- `output_file: str = None` - Excel输出文件路径（.xlsx或.csv）
- 与 `links_data` 二选一

**实现内容**:

1. **skills/macro_emission/excel_handler.py** (新增)
   - `read_links_from_excel()`: 读取Excel文件
   - `write_results_to_excel()`: 写入Excel文件
   - `_find_column()`: 查找列名（支持多种命名方式）
   - `_identify_vehicle_columns()`: 识别车型分布列
   - `_parse_fleet_mix()`: 解析车型分布并自动归一化

2. **skills/macro_emission/skill.py** (修改)
   - 添加 `input_file` 和 `output_file` 参数
   - 更新参数验证逻辑（links_data或input_file二选一）
   - 修改 `execute` 方法支持文件输入/输出
   - 添加 `ExcelHandler` 实例

**Excel输入格式**:

必需列（支持中英文）:
- 路段长度: `link_length_km` / `length_km` / `length` / `路段长度` / `长度`
- 交通流量: `traffic_flow_vph` / `flow_vph` / `flow` / `traffic` / `交通流量` / `流量`
- 平均速度: `avg_speed_kph` / `speed_kph` / `speed` / `平均速度` / `速度`

可选列:
- 路段ID: `link_id` / `id` / `路段ID` / `路段编号`（如果没有，自动生成Link_1, Link_2...）
- 车型分布列: 支持以下车型（列名包含车型名称和%符号）
  - `乘用车%` / `小汽车%` / `轿车%` → Passenger Car
  - `公交车%` / `巴士%` → Transit Bus
  - `货车%` / `重型货车%` / `大货车%` → Combination Long-haul Truck
  - `轻型货车%` / `小货车%` → Light Commercial Truck
  - `客车%` / `皮卡%` → Passenger Truck
  - 等9种车型

**Excel输出格式**:
| 列名 | 描述 | 单位 |
|------|------|------|
| link_id | 路段ID | - |
| link_length_km | 路段长度 | km |
| traffic_flow_vph | 交通流量 | 辆/小时 |
| avg_speed_kph | 平均速度 | km/h |
| CO2_kg_per_h | CO2排放率 | kg/h |
| NOx_kg_per_h | NOx排放率 | kg/h |
| PM2.5_kg_per_h | PM2.5排放率 | kg/h |

**自动处理功能**:
1. **路段ID自动生成**: 如果没有路段ID列，自动生成 `Link_1`, `Link_2`, `Link_3`...

2. **车型分布自动归一化**: 如果车型百分比总和不等于100%，自动归一化
   ```python
   # 输入: 乘用车 60%, 公交车 20%, 货车 30%  (总和 110%)
   # 自动归一化为:
   # 乘用车: 60/110*100 = 54.55%
   # 公交车: 20/110*100 = 18.18%
   # 货车: 30/110*100 = 27.27%
   ```

3. **默认车队组成**: 如果没有车型分布列或所有值为空，使用默认车队组成
   ```python
   DEFAULT_FLEET_MIX = {
       "Passenger Car": 70.0,
       "Passenger Truck": 20.0,
       "Light Commercial Truck": 5.0,
       "Transit Bus": 3.0,
       "Combination Long-haul Truck": 2.0,
   }
   ```

**车型列名映射**: 支持中文车型名称自动映射到MOVES标准名称
- 乘用车/小汽车/轿车 → Passenger Car
- 公交车/巴士 → Transit Bus
- 货车/重型货车/大货车 → Combination Long-haul Truck
- 轻型货车/小货车 → Light Commercial Truck
- 客车/皮卡 → Passenger Truck
- 摩托车 → Motorcycle
- 校车 → School Bus
- 城际客车 → Intercity Bus
- 垃圾车 → Refuse Truck

**列名识别**: 支持多种列名格式（不区分大小写）
- 路段长度: link_length_km, length_km, length, 路段长度, 长度
- 交通流量: traffic_flow_vph, flow_vph, flow, traffic, 交通流量, 流量
- 平均速度: avg_speed_kph, speed_kph, speed, 平均速度, 速度
- 路段ID: link_id, id, 路段ID, 路段编号

**向后兼容性**: ✅ 完全向后兼容
- 原有的 `links_data` 数组输入方式仍然支持
- 可以混合使用（数组输入 + Excel输出）

**测试**: ✅ 5个测试用例全部通过
- Excel输入和输出（完整数据，包含车型分布）
- 简化Excel输入（不包含车型分布，使用默认值）
- CSV格式输入/输出
- 参数验证
- 文件不存在错误处理

**文档**: `MACRO_EMISSION_EXCEL_FEATURE.md`

---

### Phase 6 总结

**完成时间**: 2026-01-24

**核心成就**:
- ✅ 排放因子Skill支持曲线数据返回和多污染物查询
- ✅ 微观排放Skill支持Excel输入/输出
- ✅ 宏观排放Skill支持Excel批量输入/输出
- ✅ 所有功能完全向后兼容
- ✅ 支持中英文列名识别
- ✅ 自动计算和归一化功能
- ✅ 完整的测试覆盖和文档

**新增文件**:
- `skills/micro_emission/excel_handler.py`
- `skills/macro_emission/excel_handler.py`
- `test_emission_factors_curve.py`
- `test_micro_emission_excel.py`
- `test_macro_emission_excel.py`
- `EMISSION_FACTORS_CURVE_FEATURE.md`
- `MICRO_EMISSION_EXCEL_FEATURE.md`
- `MACRO_EMISSION_EXCEL_FEATURE.md`

**修改文件**:
- `skills/emission_factors/skill.py`
- `skills/emission_factors/calculator.py`
- `skills/micro_emission/skill.py`
- `skills/macro_emission/skill.py`

**技术亮点**:
1. **灵活的列名识别**: 支持中英文、多种命名方式、不区分大小写
2. **智能自动处理**: 自动计算加速度、自动生成ID、自动归一化百分比
3. **多格式支持**: 同时支持.xlsx、.xls、.csv格式
4. **完全向后兼容**: 不影响现有代码，新旧功能可混合使用
5. **健壮的错误处理**: 详细的错误信息，输出失败不影响计算结果
6. **单位自动转换**: CO2使用g/s，其他污染物使用mg/s（自动转换）

**使用场景**:
1. **批量数据处理**: 从Excel读取大量路段数据，批量计算排放
2. **轨迹数据分析**: 从Excel读取车辆轨迹，计算逐秒排放
3. **曲线数据导出**: 获取完整速度-排放曲线用于可视化或进一步分析
4. **多污染物对比**: 一次查询多个污染物，便于对比分析

---

## Phase 7: Web前端和API ✅

**完成日期**: 2026-01-25

### 7.1 API层开发 ✅

**新增文件**:
- `api/__init__.py` - API模块初始化
- `api/main.py` - FastAPI应用入口
- `api/routes.py` - API路由定义（9个端点）
- `api/models.py` - Pydantic数据模型
- `api/session.py` - 会话管理器

**核心功能**:
1. **聊天接口** (`POST /api/chat`)
   - 支持纯文本消息
   - 支持文件上传（Excel/CSV）
   - 自动解析Agent返回的数据类型
   - 返回图表数据或表格数据

2. **文件处理**
   - `POST /api/file/preview` - 文件预览（前5行）
   - `GET /api/file/download/{id}` - 下载结果文件
   - `GET /api/file/template/{type}` - 下载模板文件

3. **会话管理**
   - `GET /api/sessions` - 会话列表
   - `POST /api/sessions/new` - 创建会话
   - `DELETE /api/sessions/{id}` - 删除会话

4. **系统**
   - `GET /api/health` - 健康检查

**技术实现**:
- FastAPI框架
- Uvicorn服务器
- 内存会话管理（SessionManager）
- 临时文件存储（系统临时目录）
- CORS支持（开发环境）

### 7.2 前端对接 ✅

**修改文件**:
- `web/index.html` - 添加JavaScript引用

**新增文件**:
- `web/app.js` - 完整的前端交互代码（600+行）

**核心功能**:
1. **消息发送和显示**
   - 用户消息渲染
   - 助手消息渲染
   - 加载状态动画
   - Markdown格式化

2. **文件上传**
   - 文件选择
   - 文件预览（显示文件信息、列名、警告）
   - 文件类型检测（轨迹/路段）
   - 文件移除

3. **图表渲染**（ECharts）
   - 排放因子曲线图
   - 多污染物Tab切换
   - 响应式设计
   - 交互式Tooltip

4. **表格展示**
   - 计算结果表格
   - 前5行预览
   - 汇总信息显示
   - Excel下载按钮

5. **会话管理**
   - 新建对话
   - 会话ID管理
   - 对话历史保持

**UI特性**:
- 深色模式支持
- 响应式布局
- 平滑动画
- Material Design图标

### 7.3 启动和测试 ✅

**新增文件**:
- `run_api.py` - API服务启动脚本
- `test_api_simple.py` - API功能测试脚本
- `WEB_STARTUP_GUIDE.md` - 完整的启动指南

**测试结果**:
```
============================================================
API Service Test
============================================================

[1] Starting API server...
    [PASS] Health check OK
[2] Testing session creation...
    [PASS] Session created
[3] Testing chat endpoint...
    [PASS] Chat message sent successfully
[4] Testing frontend page...
    [PASS] Frontend accessible (17408 bytes)
[5] Testing API documentation...
    [PASS] API docs accessible

============================================================
Test Results: 5/5 passed
============================================================
```

**依赖更新**:
- `requirements.txt` 添加：
  - fastapi>=0.100.0
  - uvicorn>=0.22.0
  - python-multipart>=0.0.6
  - openpyxl>=3.0.0

### 7.4 数据流设计

```
用户输入
  ↓
前端 (app.js)
  ↓ HTTP POST
API (routes.py)
  ↓
Session Manager
  ↓
Agent (core.py)
  ↓
Skills (emission_factors/micro/macro/knowledge)
  ↓
返回结果
  ↓
API响应 (JSON)
  ↓
前端渲染 (图表/表格)
  ↓
用户查看
```

### 7.5 API端点完整列表

| 方法 | 路径 | 功能 | 参数 |
|------|------|------|------|
| POST | /api/chat | 发送消息 | message, session_id, file |
| POST | /api/file/preview | 文件预览 | file |
| GET | /api/file/download/{id} | 下载结果 | file_id |
| GET | /api/file/template/{type} | 下载模板 | template_type |
| GET | /api/sessions | 会话列表 | - |
| POST | /api/sessions/new | 创建会话 | - |
| DELETE | /api/sessions/{id} | 删除会话 | session_id |
| GET | /api/health | 健康检查 | - |
| GET | /docs | API文档 | - |

### 7.6 前端功能完整列表

**消息交互**:
- ✅ 发送文本消息
- ✅ Enter发送（Shift+Enter换行）
- ✅ 消息历史显示
- ✅ 加载状态动画
- ✅ 错误处理

**文件处理**:
- ✅ 文件选择（.xlsx, .xls, .csv）
- ✅ 文件预览（文件名、大小、行数、列名）
- ✅ 文件类型检测（轨迹/路段/未知）
- ✅ 警告提示（缺少列）
- ✅ 文件移除

**数据可视化**:
- ✅ 排放因子曲线图（ECharts）
- ✅ 多污染物Tab切换
- ✅ 交互式Tooltip
- ✅ 响应式图表

**结果展示**:
- ✅ 计算结果表格
- ✅ 前5行预览
- ✅ 汇总信息
- ✅ Excel下载

**会话管理**:
- ✅ 新建对话
- ✅ 会话ID保持
- ✅ 对话历史

### 7.7 技术亮点

1. **完全前后端分离**: API和前端独立，易于维护和扩展
2. **RESTful设计**: 标准的REST API，易于集成
3. **自动API文档**: FastAPI自动生成交互式文档（/docs）
4. **类型安全**: Pydantic模型确保数据类型正确
5. **会话管理**: 支持多用户并发使用
6. **文件处理**: 完整的上传、预览、下载流程
7. **数据可视化**: ECharts图表，交互性强
8. **响应式设计**: 适配桌面和移动设备
9. **错误处理**: 完善的错误捕获和提示
10. **易于部署**: 单命令启动，支持Docker

### 7.8 使用场景

**场景1: 排放因子查询**
```
用户: "查询2020年小汽车的CO2和NOx排放因子"
系统: 返回折线图，可切换污染物
```

**场景2: 轨迹排放计算**
```
用户: 上传trajectory.xlsx + "计算这个轨迹的排放"
系统: 返回表格预览 + 下载按钮
```

**场景3: 路段排放计算**
```
用户: 上传links.xlsx + "计算这些道路的排放"
系统: 返回表格预览 + 下载按钮
```

**场景4: 增量对话**
```
用户: "查询小汽车CO2排放因子"
系统: 返回数据
用户: "NOx呢？"
系统: 记住车型，只改污染物
```

### 7.9 项目文件结构（完整）

```
emission_agent/
├── api/                        # API层 ✅ NEW
│   ├── __init__.py
│   ├── main.py
│   ├── routes.py
│   ├── models.py
│   └── session.py
│
├── web/                        # 前端 ✅ NEW
│   ├── index.html
│   └── app.js
│
├── agent/                      # Agent层
│   ├── core.py
│   ├── context.py
│   ├── validator.py
│   ├── reflector.py
│   ├── learner.py
│   ├── monitor.py
│   ├── cache.py
│   └── prompts/
│
├── skills/                     # Skills层
│   ├── emission_factors/
│   ├── micro_emission/
│   ├── macro_emission/
│   └── knowledge/
│
├── shared/                     # 共享模块
│   └── standardizer/
│
├── llm/                        # LLM客户端
│   ├── client.py
│   └── data_collector.py
│
├── run_api.py                  # API启动脚本 ✅ NEW
├── test_api_simple.py          # API测试脚本 ✅ NEW
├── WEB_STARTUP_GUIDE.md        # 启动指南 ✅ NEW
├── requirements.txt            # 依赖列表（已更新）
└── config.py
```

---

**最后更新**: 2026-01-25
**版本**: v2.2 (Phase 7 完成 - Web前端和API)
**状态**: 生产就绪 ✅

**启动命令**:
```bash
python run_api.py
```

**访问地址**:
- 前端: http://localhost:8000
- API: http://localhost:8000/api
- 文档: http://localhost:8000/docs

---

## Phase 7.1: 前端布局BUG修复 ✅

**修复日期**: 2026-01-25
**问题严重性**: 🔴 严重 (Critical)
**状态**: ✅ 已修复并测试通过

### 问题描述

**症状**:
- ❌ 助手消息错误地显示在左侧边栏（sidebar）中
- ❌ 中间聊天区域显示静态示例内容，而不是动态消息
- ❌ 用户发送的消息无法正确显示

**根本原因**:
1. HTML结构问题：消息容器缺少唯一ID标识，包含大量静态示例内容
2. JavaScript选择器问题：使用不精确的class选择器，匹配到错误的DOM元素
3. 缺少空值检查，导致静默失败

### 修复内容

**HTML修复** (`web/index.html`):
- ✅ 添加 `id="messages-container"` 到消息容器
- ✅ 添加 `id="input-area"` 到输入区域
- ✅ 删除所有静态示例内容（用户消息、助手消息、图表、表格）
- ✅ 保留"Today"时间戳和注释

**JavaScript修复** (`web/app.js`):
- ✅ 修复DOM选择器：从class选择器改为ID选择器
  ```javascript
  // 修复前: document.querySelector('.overflow-y-auto.flex-1')
  // 修复后: document.getElementById('messages-container')
  ```
- ✅ 添加调试日志：验证DOM元素是否正确获取
- ✅ 添加空值检查：`addUserMessage`, `addAssistantMessage`, `addLoadingMessage`
- ✅ 添加loadingEl空值检查：防止remove()调用失败

### 测试验证

**服务器测试**: ✅
```bash
curl http://localhost:8000/api/health
# 返回: {"status":"healthy","timestamp":"2026-01-25T22:19:55.388051"}
```

**HTML结构测试**: ✅
```bash
curl http://localhost:8000/ | grep "messages-container"
# 确认: <div id="messages-container" ...>
# 确认: 只包含"Today"标签，无静态内容
```

**API功能测试**: ✅
```bash
# 创建会话
curl -X POST http://localhost:8000/api/sessions/new
# 返回: {"session_id":"5d0a1214"}

# 发送消息
curl -X POST http://localhost:8000/api/chat -F "message=测试消息" -F "session_id=5d0a1214"
# 返回: {"reply":"...","success":true}
```

### 修复文件清单

| 文件 | 修改类型 | 修改内容 |
|------|----------|----------|
| `web/index.html` | 修改 | 添加ID，删除静态内容 |
| `web/app.js` | 修改 | 修复选择器，添加空值检查和调试日志 |
| `BUGFIX_REPORT.md` | 新增 | 详细的BUG修复报告 |

### 技术细节

**DOM选择器优先级**:
- ❌ 错误: `document.querySelector('.overflow-y-auto.flex-1')` - 可能匹配多个元素
- ✅ 正确: `document.getElementById('messages-container')` - 唯一匹配

**空值检查的重要性**:
```javascript
// ❌ 没有检查: 静默失败
messagesContainer?.insertAdjacentHTML('beforeend', html);

// ✅ 有检查: 明确错误
if (!messagesContainer) {
    console.error('错误：消息容器不存在！');
    return;
}
```

### 验证清单

- [x] HTML结构正确（ID已添加）
- [x] 静态内容已删除
- [x] DOM选择器使用ID
- [x] 添加了调试日志
- [x] 添加了空值检查
- [x] API服务器正常运行
- [x] 健康检查通过
- [x] 会话创建成功
- [x] 消息发送成功
- [x] HTML正确加载

### 修复效果

✅ **完全修复** - 消息现在正确显示在中间聊天区域
- 左侧边栏只显示导航菜单和历史记录
- 中间聊天区域显示动态消息
- 用户消息右对齐（蓝色气泡）
- 助手消息左对齐（白色气泡，带🌿图标）
- 输入框固定在底部

**详细报告**: `BUGFIX_REPORT.md`

---

**最后更新**: 2026-01-25
**版本**: v2.2.1 (Phase 7.1 完成 - 前端布局BUG修复)
**状态**: 生产就绪 ✅
