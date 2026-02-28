# Emission Agent 架构升级开发指南

## 面向 Claude Code 的完整实施文档

**版本**: 2.0
**日期**: 2026-02-04
**目标**: 实现 ChatGPT 级别的智能交互体验

---

## 第一部分：升级目标与核心理念

### 1.1 升级目标

| 维度 | 当前状态 | 目标状态 |
|------|---------|---------|
| System Prompt | 617行（35%补丁规则） | <100行（纯原则） |
| 交互模式 | 规则驱动、防御性编程 | LLM驱动、自然对话 |
| 工具调用 | 复杂验证链（4层） | Tool Use 原生模式 |
| 硬编码规则 | 200+映射分散10个文件 | 单一配置文件 |
| 用户澄清 | 被动、规则触发 | 主动、智能、友好 |

### 1.2 核心设计理念

#### 理念1：信任 LLM，而非束缚 LLM

```
❌ 旧思维：LLM 不可靠，需要大量规则约束
   → 617行规则，"不要这样做"的补丁，多层验证

✅ 新思维：LLM 能理解，给它足够信息即可
   → 极简原则，自描述工具，自然对话流
```

#### 理念2：澄清是智能的体现，而非系统的缺陷

```
❌ 旧思维：尽量减少追问，追问=系统不够智能
   → 复杂的参数推断，大量默认值假设

✅ 新思维：恰当的追问=真正理解用户，体现智能
   → 友好、精准的澄清问题，给用户选择权
```

#### 理念3：工具自描述，路由自然化

```
❌ 旧思维：在 Prompt 中详细说明每个工具的使用规则
   → 188行文件处理规则，174行示例

✅ 新思维：工具自己描述能力，LLM 自然选择
   → 工具定义包含"什么时候用"，LLM 阅读即理解
```

---

## 第二部分：新架构设计

### 2.1 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户输入                                 │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Context Assembler（上下文组装器）                               │
│                                                                  │
│  职责：组装 LLM 需要的所有信息，不做决策                          │
│                                                                  │
│  组装内容：                                                       │
│  ├── Core Prompt（核心原则，~50行）                              │
│  ├── Tool Definitions（工具定义，Tool Use 格式）                 │
│  ├── Working Memory（最近3轮完整对话）                           │
│  ├── Fact Memory（结构化事实：最近用的车型、污染物等）            │
│  └── File Context（如有文件：类型+列名+样例）                    │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Unified LLM Layer（统一 LLM 层）                                │
│                                                                  │
│  单次 LLM 调用，使用 Tool Use 能力                               │
│                                                                  │
│  可能的输出：                                                     │
│  ├── 直接回复（闲聊、解释、回答知识问题）                        │
│  ├── 工具调用（tool_calls: [{name, arguments}]）                │
│  └── 澄清对话（友好地向用户询问缺失信息）                        │
│                                                                  │
│  关键：LLM 自己决定做什么，不需要"分诊"层                        │
└─────────────────────────────────────────────────────────────────┘
                               │
               ┌───────────────┼───────────────┐
               ▼               ▼               ▼
          [直接回复]      [工具调用]       [澄清对话]
               │               │               │
               │               ▼               │
               │  ┌───────────────────────┐   │
               │  │  Tool Executor        │   │
               │  │                       │   │
               │  │  内部处理（对LLM透明）：│   │
               │  │  ├── 参数标准化       │   │
               │  │  ├── 列名映射         │   │
               │  │  ├── 业务计算         │   │
               │  │  └── 结果格式化       │   │
               │  └───────────────────────┘   │
               │               │               │
               │               ▼               │
               │  ┌───────────────────────┐   │
               │  │  Result Synthesizer   │   │
               │  │                       │   │
               │  │  让 LLM 将结果转化为   │   │
               │  │  自然语言回复          │   │
               │  └───────────────────────┘   │
               │               │               │
               └───────────────┼───────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Memory Manager（记忆管理器）                                    │
│                                                                  │
│  更新：                                                          │
│  ├── Working Memory（添加本轮对话）                              │
│  ├── Fact Memory（提取本轮的关键事实）                           │
│  └── 判断是否需要压缩早期对话                                    │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
                          [返回用户]
```

### 2.2 与旧架构的关键区别

| 组件 | 旧架构 | 新架构 |
|------|--------|--------|
| Planning | 专门的规划步骤，输出 JSON 计划 | 取消，LLM 直接通过 Tool Use 决策 |
| Validator | 独立的4层验证 | 取消，验证内置于工具 |
| Reflector | 独立的反思修复层 | 取消，错误通过对话自然修复 |
| Standardizer | 对 LLM 可见的标准化 | 对 LLM 透明，工具内部处理 |
| 澄清逻辑 | 规则触发，Prompt 中大量规则 | LLM 自然判断，友好询问 |

### 2.3 本地微调模型的定位

**保留本地 Qwen3-4B + LoRA 模型**，但改变使用方式：

```
┌─────────────────────────────────────────────────────────────────┐
│  工具内部的标准化流程（对主 LLM 完全透明）                        │
│                                                                  │
│  主 LLM 传入: vehicle_type="小汽车"                             │
│                     │                                            │
│                     ▼                                            │
│  Step 1: 配置表精确匹配 ─────── 找到 → "Passenger Car" ✓        │
│                     │                                            │
│                     ▼ 找不到                                     │
│  Step 2: 本地模型推理 ─────── 置信度>0.9 → 返回结果 ✓           │
│          (Qwen3-4B+LoRA)     │                                   │
│                              ▼ 置信度<0.9                        │
│  Step 3: 返回 None ─────────── 工具返回友好错误                  │
│                               "无法识别车型'xxx'，请选择：..."   │
│                                                                  │
│  关键：主 LLM 只需传递用户原话，不需要知道标准化细节             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 第三部分：新文件结构

### 3.1 目标文件结构

```
emission_agent/
├── config/                           # 【新建】配置中心
│   ├── unified_mappings.yaml        # 统一映射配置（车型、污染物、列名）
│   ├── defaults.yaml                # 默认值配置
│   └── prompts/
│       └── core.yaml                # 核心 Prompt（~50行）
│
├── core/                             # 【新建】核心层（替代 agent/）
│   ├── __init__.py
│   ├── assembler.py                 # 上下文组装器
│   ├── router.py                    # 统一路由器（LLM + Tool Use）
│   ├── executor.py                  # 工具执行器
│   ├── synthesizer.py               # 结果综合器
│   └── memory.py                    # 记忆管理器
│
├── tools/                            # 【新建】工具层（替代 skills/）
│   ├── __init__.py
│   ├── base.py                      # 工具基类
│   ├── registry.py                  # 工具注册表
│   ├── definitions.py               # 工具定义（Tool Use 格式）
│   ├── emission_factors.py          # 排放因子查询工具
│   ├── micro_emission.py            # 微观排放计算工具
│   ├── macro_emission.py            # 宏观排放计算工具
│   └── file_analyzer.py             # 文件分析工具
│
├── services/                         # 【新建】服务层（从 shared/ 整理）
│   ├── __init__.py
│   ├── standardizer.py              # 统一标准化服务
│   ├── config_loader.py             # 配置加载服务
│   └── llm_client.py                # LLM 客户端
│
├── calculators/                      # 【保留】计算逻辑（从 skills/*/calculator.py 移出）
│   ├── __init__.py
│   ├── vsp.py                       # VSP 计算
│   ├── micro_emission.py            # 微观排放计算
│   ├── macro_emission.py            # 宏观排放计算
│   └── emission_factors.py          # 排放因子查询
│
├── data/                             # 【保留】数据目录
│   ├── moves/                       # MOVES 数据文件
│   ├── sessions/                    # 会话存储
│   └── learning/                    # 学习案例
│
├── api/                              # 【保留】API 层
│   ├── main.py
│   ├── routes.py
│   └── models.py
│
├── web/                              # 【保留】前端
│   ├── index.html
│   ├── app.js
│   └── styles.css
│
├── local_model/                      # 【保留】本地模型（从 LOCAL_STANDARDIZER_MODEL/ 重命名）
│   └── ...
│
└── legacy/                           # 【归档】旧代码（供参考，不使用）
    └── agent/                       # 旧的 agent 目录
```

### 3.2 需要删除的文件

```
【删除】- 逻辑已合并或不再需要
├── agent/validator.py               # 验证逻辑内置到工具
├── agent/reflector.py               # 移除反思层
├── agent/learner.py                 # 简化，可选保留用于数据收集
├── agent/cache.py                   # 简化
├── agent/prompts/system.py          # 替换为 config/prompts/core.yaml
├── skills/common/column_mapper.py   # 合并到 services/standardizer.py

【归档到 legacy/】- 供参考
├── agent/core.py                    # 旧的 Agent 核心
├── agent/context.py                 # 旧的上下文管理
└── skills/                          # 旧的 Skill 层
```

---

## 第四部分：核心组件实现规范

### 4.1 统一配置文件

**文件**: `config/unified_mappings.yaml`

**Claude Code 指令**：
```
请创建 config/unified_mappings.yaml，整合以下来源的所有映射：
1. shared/standardizer/constants.py 中的 VEHICLE_TYPE_MAPPING
2. shared/standardizer/constants.py 中的 POLLUTANT_MAPPING
3. shared/standardizer/constants.py 中的 SEASON_MAPPING
4. skills/micro_emission/excel_handler.py 中的列名模式
5. skills/macro_emission/excel_handler.py 中的列名模式
6. agent/validator.py 中的 FIELD_CORRECTIONS

格式规范：
```

```yaml
# config/unified_mappings.yaml
version: "2.0"

# ============ 车辆类型 ============
vehicle_types:
  - id: 21
    standard_name: "Passenger Car"
    display_name_zh: "乘用车"
    aliases:
      - "小汽车"
      - "轿车"
      - "私家车"
      - "SUV"
      - "网约车"
      - "出租车"
      - "passenger car"
      - "car"
    # 继续添加其他12种车型...

# ============ 污染物 ============
pollutants:
  - id: 90
    standard_name: "CO2"
    display_name_zh: "二氧化碳"
    aliases:
      - "碳排放"
      - "温室气体"
      - "co2"
    # 继续添加其他污染物...

# ============ 列名模式 ============
column_patterns:
  micro_emission:
    speed:
      standard: "speed_kph"
      required: true
      patterns:
        - "speed_kph"
        - "speed_kmh"
        - "speed"
        - "车速"
        - "速度"
        - "velocity"
    time:
      standard: "time"
      required: true
      patterns:
        - "t"
        - "time"
        - "time_sec"
        - "时间"
    acceleration:
      standard: "acceleration_mps2"
      required: false  # 可从速度计算
      patterns:
        - "acceleration"
        - "acc"
        - "加速度"
    grade:
      standard: "grade_pct"
      required: false  # 可默认为0
      patterns:
        - "grade_pct"
        - "grade"
        - "坡度"
        - "slope"

  macro_emission:
    # 类似结构...

# ============ 默认值 ============
defaults:
  season: "夏季"
  road_type: "快速路"
  model_year: 2020
  pollutants: ["CO2", "NOx", "PM2.5"]
  fleet_mix:
    "Passenger Car": 0.6
    "Passenger Truck": 0.15
    "Light Commercial Truck": 0.1
    "Transit Bus": 0.1
    "Single Unit Short-haul Truck": 0.05
```

### 4.2 核心 Prompt

**文件**: `config/prompts/core.yaml`

**Claude Code 指令**：
```
请创建 config/prompts/core.yaml，这是新架构的核心 Prompt。
目标：从617行压缩到~50行，只保留原则，移除所有规则和示例。

参考旧 Prompt 位置：agent/prompts/system.py
```

```yaml
# config/prompts/core.yaml

system_prompt: |
  你是一个智能机动车排放计算助手。

  ## 你的能力
  你可以通过调用工具来帮助用户：
  - 查询排放因子曲线
  - 计算车辆轨迹排放（微观）
  - 计算路段排放（宏观）
  - 分析用户上传的数据文件

  ## 交互原则
  1. 理解用户的真实意图，即使表达不完整
  2. 信息不足时，友好地询问，并给出选项或建议
  3. 使用工具获取数据，不要编造数据
  4. 回复简洁清晰，突出关键结果

  ## 关于澄清
  当需要更多信息时，请：
  - 直接、友好地询问
  - 提供选项让用户选择（如车型列表）
  - 可以给出推荐的默认选项
  例如："请问这是什么类型的车辆？常见的有：1.小汽车 2.公交车 3.货车，或者您可以直接告诉我具体车型。"

  ## 关于历史对话
  - 用户可能引用之前的内容（"用刚才那个"、"改成公交车"）
  - 结合对话历史理解用户意图
  - 只修改用户提到的参数，保留其他参数

# 注意：所有工具的具体使用方法由工具自身的描述说明，不在此处重复
```

### 4.3 工具定义

**文件**: `tools/definitions.py`

**Claude Code 指令**：
```
请创建 tools/definitions.py，定义所有工具的 Tool Use 格式描述。

关键原则：
1. 描述"做什么"，不描述"怎么做"（VSP公式等内部实现不要写）
2. 参数描述要让 LLM 知道传什么，但标准化由工具内部处理
3. 包含"什么时候用这个工具"的指引

参考旧实现：
- skills/emission_factors/skill.py
- skills/micro_emission/skill.py
- skills/macro_emission/skill.py
- skills/common/file_analyzer.py
```

```python
# tools/definitions.py
"""
工具定义 - Tool Use 格式
"""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "query_emission_factors",
            "description": """查询车辆在不同速度下的排放因子曲线。

使用场景：
- 用户想了解某车型某污染物的排放特性
- 用户问"XX车的排放因子是多少"
- 用户想比较不同速度下的排放

输出：速度-排放因子关系图 + 关键速度点数据表""",
            "parameters": {
                "type": "object",
                "properties": {
                    "vehicle_type": {
                        "type": "string",
                        "description": "车辆类型。直接传递用户的表述即可，如'小汽车'、'公交车'、'货车'等，系统会自动识别。"
                    },
                    "pollutant": {
                        "type": "string",
                        "description": "污染物。如'CO2'、'NOx'、'PM2.5'，支持中英文。"
                    },
                    "model_year": {
                        "type": "integer",
                        "description": "车辆年份，如2020。范围1995-2025。"
                    },
                    "season": {
                        "type": "string",
                        "description": "季节。可选：春季、夏季、秋季、冬季。不提供则使用默认值。"
                    }
                },
                "required": ["vehicle_type", "pollutant", "model_year"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_micro_emission",
            "description": """计算单个车辆的详细排放量（微观排放）。

使用场景：
- 用户有逐秒轨迹数据（速度、时间序列）
- 用户上传了轨迹文件
- 用户想计算某次行程的排放

输入：轨迹数据（时间+速度，加速度和坡度可选）
输出：逐秒排放明细 + 总排放量汇总 + 可下载的Excel文件""",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "轨迹数据文件路径。如果用户上传了文件，使用文件路径。"
                    },
                    "vehicle_type": {
                        "type": "string",
                        "description": "车辆类型。直接传递用户的表述。"
                    },
                    "pollutants": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要计算的污染物列表。不提供则使用默认值[CO2, NOx, PM2.5]。"
                    },
                    "model_year": {
                        "type": "integer",
                        "description": "车辆年份。不提供则使用默认值。"
                    }
                },
                "required": []  # 根据情况，可能需要澄清
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_macro_emission",
            "description": """计算道路路段的排放量（宏观排放）。

使用场景：
- 用户有路段数据（长度、流量、速度）
- 用户上传了路段/路网数据文件
- 用户想计算某区域的交通排放

输入：路段数据（长度+流量+速度，车队组成可选）
输出：各路段排放明细 + 总排放量汇总 + 可下载的Excel文件""",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "路段数据文件路径。"
                    },
                    "pollutants": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要计算的污染物列表。"
                    },
                    "fleet_mix": {
                        "type": "object",
                        "description": "车队组成（各车型比例）。不提供则使用默认车队组成。"
                    },
                    "model_year": {
                        "type": "integer",
                        "description": "车辆年份。"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_file",
            "description": """分析用户上传的文件，识别文件类型和结构。

使用场景：
- 用户上传了文件但没说明用途
- 需要先了解文件内容再决定如何处理
- 文件列名不标准，需要识别对应关系

输出：文件类型（轨迹/路段/其他）、列名列表、数据预览、建议的处理方式""",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "文件路径"
                    }
                },
                "required": ["file_path"]
            }
        }
    }
]
```

### 4.4 上下文组装器

**文件**: `core/assembler.py`

**Claude Code 指令**：
```
请创建 core/assembler.py，负责组装发送给 LLM 的完整上下文。

关键设计：
1. 不做任何决策，只组装信息
2. Token 预算管理（总上下文不超过6000 tokens）
3. 优先级：核心Prompt > 工具定义 > 事实记忆 > 工作记忆 > 文件摘要

参考：
- 旧的上下文构建逻辑在 agent/core.py 的 _build_messages() 方法
- 文件分析逻辑在 skills/common/file_analyzer.py
```

```python
# core/assembler.py
"""
上下文组装器 - 组装 LLM 需要的所有信息
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
from services.config_loader import ConfigLoader

@dataclass
class AssembledContext:
    """组装后的上下文"""
    system_prompt: str
    tools: List[Dict]
    messages: List[Dict]
    estimated_tokens: int

class ContextAssembler:
    """上下文组装器"""
    
    MAX_CONTEXT_TOKENS = 6000  # 保守估计，留空间给输出
    
    def __init__(self):
        self.config = ConfigLoader.load_prompts()
        self.tools = ConfigLoader.load_tool_definitions()
    
    def assemble(
        self,
        user_message: str,
        working_memory: List[Dict],  # 最近几轮对话
        fact_memory: Dict,           # 结构化事实
        file_context: Optional[Dict] = None  # 文件信息
    ) -> AssembledContext:
        """
        组装完整上下文
        
        优先级（token不足时从后往前裁剪）：
        1. 核心 Prompt（必须，~200 tokens）
        2. 工具定义（必须，~400 tokens）
        3. 事实记忆（重要，~100 tokens）
        4. 工作记忆（重要，最多3000 tokens）
        5. 文件上下文（可选，最多500 tokens）
        """
        used_tokens = 0
        
        # 1. 核心 Prompt（必须）
        system_prompt = self.config["system_prompt"]
        used_tokens += self._count_tokens(system_prompt)
        
        # 2. 工具定义（必须）
        tools = self.tools
        used_tokens += 400  # 估算
        
        # 3. 构建消息列表
        messages = []
        
        # 3.1 添加事实记忆（如果有）
        if fact_memory:
            fact_summary = self._format_fact_memory(fact_memory)
            messages.append({
                "role": "system",
                "content": f"[用户历史偏好和最近使用的参数]\n{fact_summary}"
            })
            used_tokens += self._count_tokens(fact_summary)
        
        # 3.2 添加工作记忆（最近对话）
        remaining_budget = self.MAX_CONTEXT_TOKENS - used_tokens - 500  # 留500给当前消息和文件
        working_memory_text = self._format_working_memory(working_memory, max_tokens=remaining_budget)
        for turn in working_memory_text:
            messages.append(turn)
        used_tokens += self._count_tokens(str(working_memory_text))
        
        # 3.3 添加文件上下文（如果有）
        if file_context:
            file_summary = self._format_file_context(file_context, max_tokens=500)
            user_message = f"[用户上传了文件]\n{file_summary}\n\n[用户消息]\n{user_message}"
        
        # 3.4 添加当前用户消息
        messages.append({"role": "user", "content": user_message})
        
        return AssembledContext(
            system_prompt=system_prompt,
            tools=tools,
            messages=messages,
            estimated_tokens=used_tokens + self._count_tokens(user_message)
        )
    
    def _format_fact_memory(self, fact_memory: Dict) -> str:
        """格式化事实记忆"""
        lines = []
        if fact_memory.get("recent_vehicle"):
            lines.append(f"最近使用的车型: {fact_memory['recent_vehicle']}")
        if fact_memory.get("recent_pollutants"):
            lines.append(f"最近查询的污染物: {', '.join(fact_memory['recent_pollutants'])}")
        if fact_memory.get("recent_year"):
            lines.append(f"最近使用的年份: {fact_memory['recent_year']}")
        if fact_memory.get("active_file"):
            lines.append(f"当前处理的文件: {fact_memory['active_file']}")
        return "\n".join(lines) if lines else ""
    
    def _format_working_memory(self, working_memory: List[Dict], max_tokens: int) -> List[Dict]:
        """格式化工作记忆，必要时压缩"""
        if not working_memory:
            return []
        
        # 简单策略：保留最近3轮完整对话
        # 如果超预算，只保留最近2轮
        recent = working_memory[-3:]
        
        result = []
        for turn in recent:
            result.append({"role": "user", "content": turn["user"]})
            result.append({"role": "assistant", "content": turn["assistant"]})
        
        return result
    
    def _format_file_context(self, file_context: Dict, max_tokens: int) -> str:
        """格式化文件上下文"""
        lines = [
            f"文件名: {file_context.get('filename', '未知')}",
            f"类型: {file_context.get('detected_type', '未知')}",
            f"行数: {file_context.get('row_count', '未知')}",
            f"列名: {', '.join(file_context.get('columns', []))}",
        ]
        
        # 如果有空间，添加样例数据
        if max_tokens > 300 and file_context.get("sample_rows"):
            lines.append(f"前2行数据: {file_context['sample_rows'][:2]}")
        
        return "\n".join(lines)
    
    def _count_tokens(self, text: str) -> int:
        """估算 token 数量（简单估算：1个中文字≈1token，1个英文单词≈1token）"""
        # 这是粗略估算，实际应使用 tiktoken
        return len(text) // 2
```

### 4.5 统一路由器

**文件**: `core/router.py`

**Claude Code 指令**：
```
请创建 core/router.py，这是新架构的核心入口。

关键设计：
1. 使用 Tool Use 模式调用 LLM
2. LLM 直接决定：回复/调用工具/澄清，不需要预分诊
3. 工具调用失败时，自然地通过对话修复
4. 重试保护：单轮最多3次工具调用

参考：
- 旧的 agent/core.py 中的 chat() 和 _plan() 方法
- 但要简化，移除所有规则判断
```

```python
# core/router.py
"""
统一路由器 - 新架构的核心入口
"""

from typing import Dict, Optional, List
from dataclasses import dataclass
from core.assembler import ContextAssembler
from core.executor import ToolExecutor
from core.memory import MemoryManager
from services.llm_client import LLMClient

@dataclass
class RouterResponse:
    """路由器响应"""
    text: str                        # 回复文本
    chart_data: Optional[Dict]       # 图表数据
    table_data: Optional[Dict]       # 表格数据
    download_file: Optional[str]     # 下载文件路径

class UnifiedRouter:
    """统一路由器"""
    
    MAX_TOOL_CALLS_PER_TURN = 3  # 单轮最多工具调用次数
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.assembler = ContextAssembler()
        self.executor = ToolExecutor()
        self.memory = MemoryManager(session_id)
        self.llm = LLMClient(model="qwen-plus")  # 主 LLM
    
    async def chat(
        self,
        user_message: str,
        file_path: Optional[str] = None
    ) -> RouterResponse:
        """
        处理用户消息
        
        流程：
        1. 组装上下文
        2. 调用 LLM（Tool Use 模式）
        3. 如果是工具调用 → 执行工具 → 让 LLM 综合结果
        4. 如果是直接回复 → 返回
        5. 更新记忆
        """
        
        # 1. 预处理文件（如果有）
        file_context = None
        if file_path:
            file_context = await self._analyze_file(file_path)
        
        # 2. 组装上下文
        context = self.assembler.assemble(
            user_message=user_message,
            working_memory=self.memory.get_working_memory(),
            fact_memory=self.memory.get_fact_memory(),
            file_context=file_context
        )
        
        # 3. 调用 LLM（Tool Use 模式）
        response = await self.llm.chat_with_tools(
            system=context.system_prompt,
            messages=context.messages,
            tools=context.tools
        )
        
        # 4. 处理响应
        result = await self._process_response(response, context, file_path)
        
        # 5. 更新记忆
        self.memory.update(
            user_message=user_message,
            assistant_response=result.text,
            tool_calls=response.tool_calls if hasattr(response, 'tool_calls') else None,
            file_path=file_path
        )
        
        return result
    
    async def _process_response(
        self,
        response,
        context,
        file_path: Optional[str],
        tool_call_count: int = 0
    ) -> RouterResponse:
        """处理 LLM 响应"""
        
        # 情况1：直接回复（无工具调用）
        if not response.tool_calls:
            return RouterResponse(
                text=response.content,
                chart_data=None,
                table_data=None,
                download_file=None
            )
        
        # 情况2：工具调用
        if tool_call_count >= self.MAX_TOOL_CALLS_PER_TURN:
            return RouterResponse(
                text="我尝试了几种方式但遇到了一些问题，能否请您更详细地描述一下需求？或者告诉我具体想要什么？",
                chart_data=None,
                table_data=None,
                download_file=None
            )
        
        # 执行工具
        tool_results = []
        for tool_call in response.tool_calls:
            result = await self.executor.execute(
                tool_name=tool_call.function.name,
                arguments=tool_call.function.arguments,
                file_path=file_path
            )
            tool_results.append({
                "tool_call_id": tool_call.id,
                "name": tool_call.function.name,
                "result": result
            })
        
        # 检查是否有错误需要重试
        has_error = any(r["result"].get("error") for r in tool_results)
        
        if has_error and tool_call_count < self.MAX_TOOL_CALLS_PER_TURN - 1:
            # 将错误信息传回 LLM，让它决定如何处理
            error_context = self._format_tool_errors(tool_results)
            context.messages.append({"role": "assistant", "content": response.content, "tool_calls": response.tool_calls})
            context.messages.append({"role": "tool", "content": error_context})
            
            # 重新调用 LLM
            retry_response = await self.llm.chat_with_tools(
                system=context.system_prompt,
                messages=context.messages,
                tools=context.tools
            )
            
            return await self._process_response(
                retry_response, context, file_path,
                tool_call_count=tool_call_count + 1
            )
        
        # 让 LLM 综合工具结果
        synthesis_response = await self._synthesize_results(
            context, response, tool_results
        )
        
        # 提取图表、表格、下载文件
        chart_data = self._extract_chart_data(tool_results)
        table_data = self._extract_table_data(tool_results)
        download_file = self._extract_download_file(tool_results)
        
        return RouterResponse(
            text=synthesis_response,
            chart_data=chart_data,
            table_data=table_data,
            download_file=download_file
        )
    
    async def _analyze_file(self, file_path: str) -> Dict:
        """分析文件（调用文件分析工具）"""
        result = await self.executor.execute(
            tool_name="analyze_file",
            arguments={"file_path": file_path},
            file_path=file_path
        )
        return result.get("data", {})
    
    async def _synthesize_results(
        self,
        context,
        original_response,
        tool_results: List[Dict]
    ) -> str:
        """让 LLM 综合工具结果生成自然语言回复"""
        
        # 构建综合提示
        results_summary = self._format_tool_results(tool_results)
        
        synthesis_messages = context.messages + [
            {"role": "assistant", "content": original_response.content, "tool_calls": original_response.tool_calls},
            {"role": "tool", "content": results_summary}
        ]
        
        response = await self.llm.chat(
            system=context.system_prompt,
            messages=synthesis_messages
        )
        
        return response.content
    
    def _format_tool_errors(self, tool_results: List[Dict]) -> str:
        """格式化工具错误信息"""
        errors = []
        for r in tool_results:
            if r["result"].get("error"):
                errors.append(f"[{r['name']}] 错误: {r['result']['message']}")
        return "\n".join(errors)
    
    def _format_tool_results(self, tool_results: List[Dict]) -> str:
        """格式化工具结果"""
        summaries = []
        for r in tool_results:
            if r["result"].get("success"):
                summaries.append(f"[{r['name']}] {r['result'].get('summary', '执行成功')}")
        return "\n".join(summaries)
    
    def _extract_chart_data(self, tool_results: List[Dict]) -> Optional[Dict]:
        """从工具结果提取图表数据"""
        for r in tool_results:
            if r["result"].get("chart_data"):
                return r["result"]["chart_data"]
        return None
    
    def _extract_table_data(self, tool_results: List[Dict]) -> Optional[Dict]:
        """从工具结果提取表格数据"""
        for r in tool_results:
            if r["result"].get("table_data"):
                return r["result"]["table_data"]
        return None
    
    def _extract_download_file(self, tool_results: List[Dict]) -> Optional[str]:
        """从工具结果提取下载文件"""
        for r in tool_results:
            if r["result"].get("download_file"):
                return r["result"]["download_file"]
        return None
```

### 4.6 工具执行器

**文件**: `core/executor.py`

**Claude Code 指令**：
```
请创建 core/executor.py，负责执行工具调用。

关键设计：
1. 工具内部处理标准化（对 LLM 透明）
2. 统一的错误处理格式
3. 调用实际的计算逻辑（从旧的 skills/*/calculator.py）

参考：
- 旧的技能执行逻辑在 skills/*/skill.py
- 标准化逻辑在 shared/standardizer/
```

```python
# core/executor.py
"""
工具执行器 - 执行工具调用
"""

from typing import Dict, Any
from services.standardizer import UnifiedStandardizer
from tools.registry import ToolRegistry

class ToolExecutor:
    """工具执行器"""
    
    def __init__(self):
        self.standardizer = UnifiedStandardizer()
        self.registry = ToolRegistry()
    
    async def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        file_path: str = None
    ) -> Dict:
        """
        执行工具
        
        流程：
        1. 获取工具实例
        2. 标准化参数（对 LLM 透明）
        3. 验证参数完整性
        4. 执行工具逻辑
        5. 格式化返回结果
        """
        
        # 1. 获取工具
        tool = self.registry.get(tool_name)
        if not tool:
            return {
                "error": True,
                "message": f"未知的工具: {tool_name}"
            }
        
        # 2. 标准化参数
        try:
            standardized_args = self._standardize_arguments(tool_name, arguments)
        except StandardizationError as e:
            return {
                "error": True,
                "error_type": "standardization",
                "message": str(e),
                "suggestions": e.suggestions if hasattr(e, 'suggestions') else None
            }
        
        # 3. 添加文件路径（如果需要）
        if file_path and "file_path" not in standardized_args:
            standardized_args["file_path"] = file_path
        
        # 4. 执行工具
        try:
            result = await tool.execute(**standardized_args)
            return {
                "success": True,
                **result
            }
        except MissingParameterError as e:
            return {
                "error": True,
                "error_type": "missing_parameter",
                "message": str(e),
                "missing_params": e.params
            }
        except CalculationError as e:
            return {
                "error": True,
                "error_type": "calculation",
                "message": str(e)
            }
        except Exception as e:
            return {
                "error": True,
                "error_type": "unknown",
                "message": f"执行失败: {str(e)}"
            }
    
    def _standardize_arguments(self, tool_name: str, arguments: Dict) -> Dict:
        """
        标准化参数
        
        这个过程对 LLM 完全透明，LLM 只需传递用户原话
        """
        standardized = {}
        
        for key, value in arguments.items():
            if key == "vehicle_type" and value:
                # 标准化车型
                result = self.standardizer.standardize_vehicle(value)
                if result is None:
                    raise StandardizationError(
                        f"无法识别车型 '{value}'",
                        suggestions=self.standardizer.get_vehicle_suggestions(value)
                    )
                standardized[key] = result
                
            elif key == "pollutant" and value:
                # 标准化污染物
                result = self.standardizer.standardize_pollutant(value)
                if result is None:
                    raise StandardizationError(
                        f"无法识别污染物 '{value}'",
                        suggestions=self.standardizer.get_pollutant_suggestions()
                    )
                standardized[key] = result
                
            elif key == "pollutants" and value:
                # 标准化污染物列表
                standardized[key] = [
                    self.standardizer.standardize_pollutant(p) or p
                    for p in value
                ]
                
            else:
                standardized[key] = value
        
        return standardized


class StandardizationError(Exception):
    """标准化错误"""
    def __init__(self, message: str, suggestions: list = None):
        super().__init__(message)
        self.suggestions = suggestions

class MissingParameterError(Exception):
    """缺少参数错误"""
    def __init__(self, message: str, params: list):
        super().__init__(message)
        self.params = params

class CalculationError(Exception):
    """计算错误"""
    pass
```

### 4.7 记忆管理器

**文件**: `core/memory.py`

**Claude Code 指令**：
```
请创建 core/memory.py，负责管理对话记忆。

关键设计：
1. 三层记忆：工作记忆（完整对话）、事实记忆（结构化）、压缩记忆
2. 只在工具调用成功后更新事实记忆
3. 检测用户纠正（"不对，是公交车"）并更新

参考：
- 旧的上下文管理在 agent/context.py
```

```python
# core/memory.py
"""
记忆管理器 - 三层记忆结构
"""

from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, field
import json
from pathlib import Path

@dataclass
class FactMemory:
    """事实记忆 - 结构化的关键事实"""
    recent_vehicle: Optional[str] = None
    recent_pollutants: List[str] = field(default_factory=list)
    recent_year: Optional[int] = None
    active_file: Optional[str] = None
    user_preferences: Dict = field(default_factory=dict)

@dataclass
class Turn:
    """对话轮次"""
    user: str
    assistant: str
    tool_calls: Optional[List[Dict]] = None
    timestamp: datetime = field(default_factory=datetime.now)

class MemoryManager:
    """记忆管理器"""
    
    MAX_WORKING_MEMORY_TURNS = 5  # 工作记忆保留的轮次
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.working_memory: List[Turn] = []
        self.fact_memory = FactMemory()
        self.compressed_memory: str = ""  # 早期对话的摘要
        
        # 加载持久化的记忆（如果有）
        self._load()
    
    def get_working_memory(self) -> List[Dict]:
        """获取工作记忆（最近几轮对话）"""
        return [
            {"user": turn.user, "assistant": turn.assistant}
            for turn in self.working_memory[-self.MAX_WORKING_MEMORY_TURNS:]
        ]
    
    def get_fact_memory(self) -> Dict:
        """获取事实记忆"""
        return {
            "recent_vehicle": self.fact_memory.recent_vehicle,
            "recent_pollutants": self.fact_memory.recent_pollutants,
            "recent_year": self.fact_memory.recent_year,
            "active_file": self.fact_memory.active_file,
        }
    
    def update(
        self,
        user_message: str,
        assistant_response: str,
        tool_calls: Optional[List[Dict]] = None,
        file_path: Optional[str] = None
    ):
        """更新记忆"""
        
        # 1. 添加到工作记忆
        turn = Turn(
            user=user_message,
            assistant=assistant_response,
            tool_calls=tool_calls
        )
        self.working_memory.append(turn)
        
        # 2. 更新事实记忆（只从成功的工具调用中提取）
        if tool_calls:
            self._extract_facts_from_tool_calls(tool_calls)
        
        # 3. 更新活动文件
        if file_path:
            self.fact_memory.active_file = file_path
        
        # 4. 检测用户纠正
        self._detect_correction(user_message)
        
        # 5. 压缩早期记忆（如果需要）
        if len(self.working_memory) > self.MAX_WORKING_MEMORY_TURNS * 2:
            self._compress_old_memory()
        
        # 6. 持久化
        self._save()
    
    def _extract_facts_from_tool_calls(self, tool_calls: List[Dict]):
        """从工具调用中提取事实"""
        for call in tool_calls:
            args = call.get("arguments", {})
            result = call.get("result", {})
            
            # 只有成功时才更新
            if not result.get("success"):
                continue
            
            if "vehicle_type" in args:
                self.fact_memory.recent_vehicle = args["vehicle_type"]
            
            if "pollutant" in args:
                if args["pollutant"] not in self.fact_memory.recent_pollutants:
                    self.fact_memory.recent_pollutants.insert(0, args["pollutant"])
                    self.fact_memory.recent_pollutants = self.fact_memory.recent_pollutants[:5]
            
            if "pollutants" in args:
                for p in args["pollutants"]:
                    if p not in self.fact_memory.recent_pollutants:
                        self.fact_memory.recent_pollutants.insert(0, p)
                self.fact_memory.recent_pollutants = self.fact_memory.recent_pollutants[:5]
            
            if "model_year" in args:
                self.fact_memory.recent_year = args["model_year"]
    
    def _detect_correction(self, user_message: str):
        """检测用户纠正并更新事实记忆"""
        correction_patterns = ["不对", "不是", "应该是", "我说的是", "换成", "改成"]
        
        if not any(p in user_message for p in correction_patterns):
            return
        
        # 简单的纠正检测逻辑
        # 实际可以用 LLM 来更准确地理解纠正内容
        # 这里只做简单的关键词匹配
        
        # 例如: "不对，我要的是公交车" → 更新 recent_vehicle
        vehicle_keywords = ["小汽车", "公交车", "货车", "轿车"]
        for kw in vehicle_keywords:
            if kw in user_message:
                self.fact_memory.recent_vehicle = kw
                break
    
    def _compress_old_memory(self):
        """压缩早期记忆"""
        # 保留最近 N 轮，其他压缩为摘要
        old_turns = self.working_memory[:-self.MAX_WORKING_MEMORY_TURNS]
        
        # 简单摘要：提取工具调用信息
        summaries = []
        for turn in old_turns:
            if turn.tool_calls:
                for call in turn.tool_calls:
                    summaries.append(f"- 调用了 {call.get('name')}，参数: {call.get('arguments')}")
        
        self.compressed_memory = "\n".join(summaries)
        self.working_memory = self.working_memory[-self.MAX_WORKING_MEMORY_TURNS:]
    
    def clear_topic_memory(self):
        """清除主题相关记忆（主题切换时调用）"""
        self.fact_memory.active_file = None
        # 保留 user_preferences，清除其他
    
    def _save(self):
        """持久化记忆"""
        data = {
            "session_id": self.session_id,
            "fact_memory": {
                "recent_vehicle": self.fact_memory.recent_vehicle,
                "recent_pollutants": self.fact_memory.recent_pollutants,
                "recent_year": self.fact_memory.recent_year,
                "active_file": self.fact_memory.active_file,
            },
            "compressed_memory": self.compressed_memory,
            "working_memory": [
                {
                    "user": t.user,
                    "assistant": t.assistant,
                    "timestamp": t.timestamp.isoformat()
                }
                for t in self.working_memory[-10:]  # 最多保存10轮
            ]
        }
        
        path = Path(f"data/sessions/{self.session_id}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _load(self):
        """加载持久化的记忆"""
        path = Path(f"data/sessions/{self.session_id}.json")
        if not path.exists():
            return
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            if "fact_memory" in data:
                fm = data["fact_memory"]
                self.fact_memory.recent_vehicle = fm.get("recent_vehicle")
                self.fact_memory.recent_pollutants = fm.get("recent_pollutants", [])
                self.fact_memory.recent_year = fm.get("recent_year")
                self.fact_memory.active_file = fm.get("active_file")
            
            self.compressed_memory = data.get("compressed_memory", "")
            
            if "working_memory" in data:
                for item in data["working_memory"]:
                    self.working_memory.append(Turn(
                        user=item["user"],
                        assistant=item["assistant"]
                    ))
        except Exception:
            pass  # 加载失败则使用空记忆
```

### 4.8 统一标准化服务

**文件**: `services/standardizer.py`

**Claude Code 指令**：
```
请创建 services/standardizer.py，整合所有标准化逻辑。

关键设计：
1. 配置表优先，本地模型次之
2. 支持模糊匹配
3. 提供建议列表（当无法识别时）
4. 列名映射也在这里处理

参考：
- 旧的 shared/standardizer/vehicle.py
- 旧的 shared/standardizer/pollutant.py
- 旧的 shared/standardizer/constants.py
- 旧的 skills/common/column_mapper.py
- 本地模型调用在 shared/standardizer/local_client.py
```

```python
# services/standardizer.py
"""
统一标准化服务 - 配置优先，本地模型辅助
"""

from typing import Optional, Dict, List
from fuzzywuzzy import fuzz
from services.config_loader import ConfigLoader

class UnifiedStandardizer:
    """统一标准化服务"""
    
    def __init__(self):
        self.config = ConfigLoader.load_mappings()
        self._build_lookup_tables()
        self.local_model = None  # 延迟加载
    
    def _build_lookup_tables(self):
        """构建查找表"""
        # 车型查找表
        self.vehicle_lookup = {}
        for vtype in self.config["vehicle_types"]:
            # 标准名
            self.vehicle_lookup[vtype["standard_name"].lower()] = vtype
            # 中文名
            self.vehicle_lookup[vtype["display_name_zh"]] = vtype
            # 所有别名
            for alias in vtype.get("aliases", []):
                self.vehicle_lookup[alias.lower()] = vtype
        
        # 污染物查找表
        self.pollutant_lookup = {}
        for pol in self.config["pollutants"]:
            self.pollutant_lookup[pol["standard_name"].lower()] = pol
            self.pollutant_lookup[pol["display_name_zh"]] = pol
            for alias in pol.get("aliases", []):
                self.pollutant_lookup[alias.lower()] = pol
        
        # 列名模式
        self.column_patterns = self.config.get("column_patterns", {})
    
    def standardize_vehicle(self, raw_input: str) -> Optional[str]:
        """
        标准化车型
        
        返回标准名称，或 None（无法识别）
        """
        if not raw_input:
            return None
        
        raw_lower = raw_input.lower().strip()
        
        # 1. 精确匹配
        if raw_lower in self.vehicle_lookup:
            return self.vehicle_lookup[raw_lower]["standard_name"]
        
        # 2. 模糊匹配
        best_match = None
        best_score = 0
        for key, value in self.vehicle_lookup.items():
            score = fuzz.ratio(raw_lower, key)
            if score > best_score and score > 70:
                best_score = score
                best_match = value
        
        if best_match:
            return best_match["standard_name"]
        
        # 3. 本地模型推理（如果配置了）
        if self._get_local_model():
            result = self.local_model.standardize_vehicle(raw_input)
            if result and result.get("confidence", 0) > 0.9:
                return result["standard_name"]
        
        # 4. 无法识别
        return None
    
    def standardize_pollutant(self, raw_input: str) -> Optional[str]:
        """标准化污染物"""
        if not raw_input:
            return None
        
        raw_lower = raw_input.lower().strip()
        
        # 1. 精确匹配
        if raw_lower in self.pollutant_lookup:
            return self.pollutant_lookup[raw_lower]["standard_name"]
        
        # 2. 模糊匹配
        best_match = None
        best_score = 0
        for key, value in self.pollutant_lookup.items():
            score = fuzz.ratio(raw_lower, key)
            if score > best_score and score > 80:
                best_score = score
                best_match = value
        
        if best_match:
            return best_match["standard_name"]
        
        # 3. 本地模型
        if self._get_local_model():
            result = self.local_model.standardize_pollutant(raw_input)
            if result and result.get("confidence", 0) > 0.9:
                return result["standard_name"]
        
        return None
    
    def get_vehicle_suggestions(self, raw_input: str = None) -> List[str]:
        """获取车型建议列表"""
        suggestions = []
        for vtype in self.config["vehicle_types"][:6]:  # 返回前6种常见车型
            suggestions.append(f"{vtype['display_name_zh']} ({vtype['standard_name']})")
        return suggestions
    
    def get_pollutant_suggestions(self) -> List[str]:
        """获取污染物建议列表"""
        return [p["standard_name"] for p in self.config["pollutants"]]
    
    def map_columns(self, columns: List[str], task_type: str) -> Dict[str, str]:
        """
        映射列名
        
        task_type: "micro_emission" 或 "macro_emission"
        返回: {原始列名: 标准列名}
        """
        patterns = self.column_patterns.get(task_type, {})
        mapping = {}
        
        for col in columns:
            col_lower = col.lower().strip()
            for field_name, field_config in patterns.items():
                for pattern in field_config.get("patterns", []):
                    if col_lower == pattern.lower():
                        mapping[col] = field_config["standard"]
                        break
                if col in mapping:
                    break
        
        return mapping
    
    def _get_local_model(self):
        """延迟加载本地模型"""
        if self.local_model is None:
            try:
                from local_model.client import LocalStandardizerClient
                self.local_model = LocalStandardizerClient()
            except Exception:
                pass  # 本地模型不可用，忽略
        return self.local_model
```

---

## 第五部分：实施步骤

### Phase 1：准备工作（0.5天）

**Claude Code 指令**：
```
在开始重构之前，请先完成以下准备工作：

1. 创建 legacy/ 目录，将以下文件复制过去（保留备份）：
   - agent/ 整个目录
   - skills/ 整个目录
   - shared/ 整个目录

2. 阅读并理解以下关键文件：
   - agent/core.py - 了解当前的处理流程
   - agent/prompts/system.py - 了解所有规则
   - agent/context.py - 了解上下文管理
   - skills/emission_factors/skill.py - 了解工具实现
   - skills/micro_emission/skill.py
   - skills/macro_emission/skill.py
   - shared/standardizer/vehicle.py - 了解标准化逻辑

3. 创建新的目录结构：
   mkdir -p config/prompts
   mkdir -p core
   mkdir -p tools
   mkdir -p services
   mkdir -p calculators

4. 确认 API 层（api/）和前端（web/）暂时不需要修改
```

### Phase 2：创建配置中心（0.5天）

**Claude Code 指令**：
```
请创建统一配置文件：

1. 创建 config/unified_mappings.yaml
   - 从 shared/standardizer/constants.py 提取所有映射
   - 从 skills/micro_emission/excel_handler.py 提取列名模式
   - 从 skills/macro_emission/excel_handler.py 提取列名模式
   - 从 agent/validator.py 提取字段校正规则
   - 格式按照第四部分 4.1 的规范

2. 创建 config/defaults.yaml
   - 提取所有默认值配置

3. 创建 config/prompts/core.yaml
   - 按照第四部分 4.2 的规范创建极简 Prompt
   - 目标：<60行

4. 创建 services/config_loader.py
   - 实现配置加载逻辑
   - 支持 YAML 文件加载
   - 启动时加载一次，缓存在内存

验证：
- 打印加载的配置，确认所有映射都正确
- 特别检查车型别名是否完整
```

### Phase 3：创建服务层（0.5天）

**Claude Code 指令**：
```
请创建服务层：

1. 创建 services/standardizer.py
   - 按照第四部分 4.8 的规范
   - 整合 shared/standardizer/vehicle.py 和 pollutant.py 的逻辑
   - 保留本地模型调用能力
   - 实现列名映射功能

2. 创建 services/llm_client.py
   - 封装 LLM 调用
   - 支持 Tool Use 模式
   - 参考旧的 llm/client.py

验证：
- 测试 standardizer.standardize_vehicle("小汽车") → "Passenger Car"
- 测试 standardizer.standardize_pollutant("氮氧") → "NOx"
- 测试 standardizer.map_columns(["speed", "时间"], "micro_emission")
```

### Phase 4：创建工具层（1天）

**Claude Code 指令**：
```
请创建工具层：

1. 创建 tools/base.py
   - 工具基类定义
   - 统一的执行接口

2. 创建 tools/definitions.py
   - 按照第四部分 4.3 的规范
   - 所有工具的 Tool Use 格式定义

3. 创建 tools/registry.py
   - 工具注册和获取

4. 移植并重构工具实现：
   
   4.1 tools/emission_factors.py
       - 从 skills/emission_factors/skill.py 移植
       - 简化：移除 Skill 基类依赖
       - 标准化在执行器层处理，这里直接使用标准参数
       - 保留计算逻辑（调用 calculators/emission_factors.py）
   
   4.2 tools/micro_emission.py
       - 从 skills/micro_emission/skill.py 移植
       - 文件处理和列映射逻辑保留
       - 但简化参数验证（交给执行器）
   
   4.3 tools/macro_emission.py
       - 从 skills/macro_emission/skill.py 移植
   
   4.4 tools/file_analyzer.py
       - 从 skills/common/file_analyzer.py 移植
       - 简化：只返回文件结构信息

5. 移植计算逻辑到 calculators/：
   - calculators/vsp.py（从 skills/micro_emission/vsp.py）
   - calculators/micro_emission.py（从 skills/micro_emission/calculator.py）
   - calculators/macro_emission.py（从 skills/macro_emission/calculator.py）
   - calculators/emission_factors.py（从 skills/emission_factors/calculator.py）

验证：
- 每个工具都能独立执行
- 计算结果与旧版本一致
```

### Phase 5：创建核心层（1天）

**Claude Code 指令**：
```
请创建核心层：

1. 创建 core/assembler.py
   - 按照第四部分 4.4 的规范
   - 实现上下文组装
   - Token 预算管理

2. 创建 core/executor.py
   - 按照第四部分 4.6 的规范
   - 工具执行
   - 参数标准化

3. 创建 core/memory.py
   - 按照第四部分 4.7 的规范
   - 三层记忆结构

4. 创建 core/router.py
   - 按照第四部分 4.5 的规范
   - 这是新架构的核心入口
   - 实现 Tool Use 模式的 LLM 调用

验证：
- 测试简单对话流程
- 测试工具调用流程
- 测试错误处理和重试
```

### Phase 6：集成测试（0.5天）

**Claude Code 指令**：
```
请进行全面的集成测试：

1. 创建测试脚本 test_new_architecture.py

2. 测试场景：

   场景1：简单查询
   输入："查询2020年小汽车的CO2排放因子"
   预期：返回图表数据和表格数据
   
   场景2：需要澄清的查询
   输入："查询排放因子"
   预期：LLM 友好地询问缺失的参数
   
   场景3：文件处理
   输入：上传轨迹文件 + "计算排放"
   预期：先分析文件，然后询问车型，最后计算
   
   场景4：增量修改
   输入：场景3后 + "改成公交车"
   预期：保留文件，只更新车型，重新计算
   
   场景5：错误恢复
   输入："查询2030年的数据"（超出范围）
   预期：返回友好的错误提示

3. 对比测试：
   - 同样的输入，对比新旧架构的响应
   - 确保计算结果一致
   - 对比响应时间

4. 记录所有问题并修复
```

### Phase 7：API 层适配（0.5天）

**Claude Code 指令**：
```
请适配 API 层：

1. 修改 api/routes.py
   - 将 Agent 调用替换为 UnifiedRouter 调用
   - 保持 API 接口不变
   - 返回格式保持兼容

2. 修改 api/session.py
   - 适配新的 MemoryManager

3. 确保前端（web/）无需修改

验证：
- 启动服务：python run_api.py
- 在浏览器中测试所有功能
- 确保图表、表格、下载都正常
```

### Phase 8：清理和文档（0.5天）

**Claude Code 指令**：
```
请完成最后的清理工作：

1. 删除不再使用的文件：
   - agent/validator.py
   - agent/reflector.py
   - agent/prompts/system.py（已替换为 config/prompts/core.yaml）

2. 更新 README.md
   - 更新项目结构
   - 更新使用说明

3. 更新 ARCHITECTURE.md
   - 描述新架构
   - 说明设计理念

4. 创建 MIGRATION_NOTES.md
   - 记录迁移过程中的决策
   - 记录与旧架构的差异

5. 确保 legacy/ 目录完整保留旧代码
```

---

## 第六部分：关键注意事项

### 6.1 保持计算逻辑不变

**重要**：重构只改变交互层和决策层，计算逻辑（VSP、排放计算）必须保持不变。

```
不要修改：
- VSP 计算公式
- 排放因子查询逻辑
- Excel 读写逻辑
- MOVES 数据处理

只重构：
- 如何决定调用哪个计算
- 如何获取和验证参数
- 如何与用户交互
```

### 6.2 LLM 调用的错误处理

```python
# 所有 LLM 调用都要有超时和重试
try:
    response = await llm.chat_with_tools(...)
except TimeoutError:
    # 超时处理
except RateLimitError:
    # 限流处理
except Exception as e:
    # 通用错误处理
```

### 6.3 保持 API 兼容

**重要**：API 接口和返回格式必须保持兼容，前端不应该需要修改。

```python
# api/routes.py 的返回格式必须保持：
{
    "response": str,          # 文本回复
    "chart_data": Optional[Dict],  # 图表数据
    "table_data": Optional[Dict],  # 表格数据
    "data_type": Optional[str],    # 数据类型
    "download_file": Optional[str] # 下载链接
}
```

### 6.4 本地模型的集成

确保本地 Qwen3-4B + LoRA 模型仍然可以使用：

```python
# services/standardizer.py 中的本地模型调用
# 必须与旧的 shared/standardizer/local_client.py 兼容

# 如果本地模型配置存在，使用本地模型
# 如果不存在，静默降级（不报错）
```

### 6.5 渐进式迁移

如果遇到问题，可以保留部分旧逻辑：

```python
# 例如：如果新的 Tool Use 模式在某些情况下效果不好
# 可以保留旧的 Planning 逻辑作为后备

USE_LEGACY_PLANNING = os.getenv("USE_LEGACY_PLANNING", "false") == "true"

if USE_LEGACY_PLANNING:
    # 使用旧的 agent/core.py 逻辑
else:
    # 使用新的 Tool Use 模式
```

---

## 第七部分：验收标准

### 7.1 功能验收

| 功能 | 验收标准 |
|------|---------|
| 排放因子查询 | 输入车型+污染物+年份，返回正确的图表和表格 |
| 微观排放计算 | 上传轨迹文件，返回正确的排放计算结果 |
| 宏观排放计算 | 上传路段文件，返回正确的排放计算结果 |
| 智能澄清 | 信息不足时，友好地询问并提供选项 |
| 增量修改 | "改成公交车"等指令能正确理解并执行 |
| 上下文记忆 | 能正确理解"刚才那个"、"用上次的"等指代 |

### 7.2 性能验收

| 指标 | 当前值 | 目标值 |
|------|--------|--------|
| System Prompt 大小 | 617行 | <100行 |
| 简单查询 LLM 调用次数 | 2-3次 | 1-2次 |
| 简单查询响应时间 | 2-3秒 | 1-2秒 |
| 文件处理响应时间 | 4-5秒 | 3-4秒 |

### 7.3 代码质量验收

| 指标 | 验收标准 |
|------|---------|
| 配置分离 | 所有映射来自单一配置文件 |
| 代码重复 | 无重复的映射定义 |
| 错误处理 | 所有错误都有友好的用户提示 |
| 日志记录 | 关键步骤有日志输出 |
| 测试覆盖 | 核心功能有测试用例 |

---

## 附录 A：文件清单

### 新建文件
```
config/unified_mappings.yaml     # 统一映射配置
config/defaults.yaml             # 默认值配置
config/prompts/core.yaml         # 核心 Prompt
core/__init__.py
core/assembler.py                # 上下文组装器
core/router.py                   # 统一路由器
core/executor.py                 # 工具执行器
core/memory.py                   # 记忆管理器
tools/__init__.py
tools/base.py                    # 工具基类
tools/definitions.py             # 工具定义
tools/registry.py                # 工具注册表
tools/emission_factors.py        # 排放因子工具
tools/micro_emission.py          # 微观排放工具
tools/macro_emission.py          # 宏观排放工具
tools/file_analyzer.py           # 文件分析工具
services/__init__.py
services/standardizer.py         # 统一标准化服务
services/config_loader.py        # 配置加载服务
services/llm_client.py           # LLM 客户端
calculators/__init__.py
calculators/vsp.py               # VSP 计算（移植）
calculators/micro_emission.py    # 微观排放计算（移植）
calculators/macro_emission.py    # 宏观排放计算（移植）
calculators/emission_factors.py  # 排放因子计算（移植）
```

### 归档文件
```
legacy/agent/                    # 旧的 Agent 目录
legacy/skills/                   # 旧的 Skills 目录
legacy/shared/                   # 旧的 Shared 目录
```

### 保留不变
```
api/                             # API 层（只修改调用方式）
web/                             # 前端（不修改）
data/                            # 数据目录
local_model/                     # 本地模型
```

---

**文档版本**: 1.0
**创建日期**: 2026-02-04
**目标版本**: Emission Agent v2.0

---

## 最后提示

Claude Code，请按照以下原则执行：

1. **先理解，后动手**：在修改任何代码前，先完整阅读相关的旧代码
2. **小步迭代**：每完成一个 Phase 就测试，不要一次性改完所有东西
3. **保持兼容**：确保 API 接口不变，前端不需要修改
4. **记录决策**：遇到设计决策时，在代码注释中说明原因
5. **有问题就问**：如果某个地方的实现不确定，可以先提出方案讨论

祝重构顺利！
