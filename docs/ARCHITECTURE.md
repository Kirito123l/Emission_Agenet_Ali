# Emission Agent 架构文档

> **版本**: v2.0 (AI-First Architecture)
> **更新日期**: 2026-02-21
> **架构类型**: Tool Use (OpenAI Function Calling)

## 目录

1. [系统概述](#系统概述)
2. [AI-First 设计哲学](#ai-first-设计哲学)
3. [整体架构](#整体架构)
4. [核心组件详解](#核心组件详解)
5. [完整工作流程](#完整工作流程)
6. [三层记忆系统](#三层记忆系统)
7. [文件处理与缓存](#文件处理与缓存)
8. [工具系统](#工具系统)
9. [参数标准化](#参数标准化)
10. [关键技术细节](#关键技术细节)
11. [性能优化](#性能优化)
12. [部署架构](#部署架构)

---

## 系统概述

Emission Agent 是一个基于 **Tool Use 架构** 的智能机动车排放计算系统。系统采用 **AI-First** 设计理念，通过自然语言理解用户意图，自动调用相应的计算工具，并以对话形式返回结果。

### 核心特性

| 特性 | 描述 | 技术实现 |
|------|------|----------|
| AI-First | 信任 LLM 智能，最小化规则 | 移除复杂 guardrail，自然重试机制 |
| Tool Use | OpenAI 函数调用标准 | 5 个工具，透明参数标准化 |
| 智能缓存 | 文件 mtime 检测 | 防止使用过期缓存 |
| 三层记忆 | Working + Fact + Compressed | 高效上下文管理 |
| 多轮对话 | 上下文理解与延续 | 记忆系统 + 事实提取 |

### 系统能力

- **排放因子查询**: 查询 EPA MOVES 数据库的速度-排放曲线
- **微观排放计算**: 基于逐秒轨迹数据计算排放（VSP 方法）
- **宏观排放计算**: 基于路段数据和车队组成计算排放（MOVES-Matrix）
- **文件分析**: 智能识别文件类型和任务类型
- **知识检索**: 检索排放计算相关文档（预留）

---

## AI-First 设计哲学

### 核心理念

**"给 LLM 提供好的信息，而不是限制它的行为"**

传统 Agent 系统倾向于用大量规则和 guardrail 来"保护" LLM，但这往往导致：
- 代码复杂度高（~130 行 guardrail 代码）
- Token 消耗大（76 行 synthesis prompt）
- 响应速度慢（多次 LLM 调用）
- 维护困难（规则冲突）

AI-First 架构的做法：
1. **信任 LLM**: 让 LLM 自然地理解和决策
2. **提供好信息**: 清晰的工具定义、结构化的上下文
3. **自然重试**: 失败时让 LLM 自己调整，而不是强制规则
4. **最小规则**: 只在关键业务逻辑处使用 Python 规则检查

### 实际改进

| 改进项 | 优化前 | 优化后 | 效果 |
|--------|--------|--------|------|
| Vehicle Guardrail | 130 行 LLM 检查 | 删除 | 更自然的对话流程 |
| Synthesis Prompt | 76 行详细指导 | 15 行核心指导 | 省 ~200 tokens/请求 |
| Tool Definitions | 冗长的"Use this when" | 简洁的一句话描述 | 更清晰的工具理解 |
| Fleet Mix 标准化 | 重复代码 125 行 | 集中化 24 行 | 代码复用 |
| 文件缓存 | 仅路径比较 | 路径 + mtime | 可靠的缓存失效 |

**净结果**: -165 行代码，更快的响应，更可靠的文件处理

---

## 整体架构

### 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户界面层                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │  Web 界面    │  │   CLI 界面   │  │   API 接口   │           │
│  │  (index.html)│  │  (main.py)   │  │  (routes.py) │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      核心路由层 (Router)                          │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  UnifiedRouter (core/router.py)                            │ │
│  │  ├─ 处理用户消息                                            │ │
│  │  ├─ 文件分析与缓存 (mtime 检测)                            │ │
│  │  ├─ 调用 LLM 生成工具调用                                  │ │
│  │  ├─ 执行工具并综合结果                                      │ │
│  │  └─ 更新记忆系统                                            │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Assembler   │    │   Executor   │    │    Memory    │
│ (assembler.py│    │ (executor.py)│    │  (memory.py) │
│              │    │              │    │              │
│ 组装上下文    │    │ 执行工具      │    │ 三层记忆      │
│ - 工作记忆    │    │ - 标准化参数  │    │ - Working    │
│ - 事实记忆    │    │ - 调用工具    │    │ - Fact       │
│ - 文件上下文  │    │ - 返回结果    │    │ - Compressed │
└──────────────┘    └──────────────┘    └──────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         工具层 (Tools)                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ 排放因子查询  │  │ 微观排放计算  │  │ 宏观排放计算  │           │
│  │ emission_    │  │ micro_       │  │ macro_       │           │
│  │ factors.py   │  │ emission.py  │  │ emission.py  │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
│  ┌──────────────┐  ┌──────────────┐                             │
│  │  文件分析     │  │  知识检索     │                             │
│  │ file_        │  │ knowledge.py │                             │
│  │ analyzer.py  │  │  (预留)      │                             │
│  └──────────────┘  └──────────────┘                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      计算引擎层 (Calculators)                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ MOVES 查询   │  │ VSP 计算     │  │ 车队排放      │           │
│  │ emission_    │  │ micro.py     │  │ macro.py     │           │
│  │ factors.py   │  │              │  │              │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       服务层 (Services)                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │  LLM 客户端  │  │  标准化器     │  │  文件处理器  │           │
│  │ llm_client.py│  │ standardizer │  │ (内置工具)   │           │
│  │              │  │ .py          │  │              │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       数据层 (Data)                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ MOVES 数据   │  │ 会话存储      │  │  临时文件     │           │
│  │ (CSV)        │  │ (JSON)       │  │  (temp/)     │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
└─────────────────────────────────────────────────────────────────┘
```

### 数据流向

```
用户消息 + 文件
    │
    ▼
Router.process()
    │
    ├─> 1. 文件分析 (如有)
    │   └─> 检查缓存 (路径 + mtime)
    │       ├─ 命中: 使用缓存
    │       └─ 未命中: 调用 analyze_file
    │
    ├─> 2. 组装上下文
    │   └─> Assembler.assemble()
    │       ├─ 工作记忆 (最近 5 轮)
    │       ├─ 事实记忆 (车型、污染物等)
    │       └─ 文件上下文 (如有)
    │
    ├─> 3. LLM 决策
    │   └─> LLMClient.chat_with_tools()
    │       ├─ System Prompt
    │       ├─ 工具定义 (5 个工具)
    │       ├─ 上下文消息
    │       └─> 返回: 工具调用 或 直接回复
    │
    ├─> 4. 工具执行 (如有工具调用)
    │   └─> Executor.execute()
    │       ├─ 标准化参数 (车型、污染物)
    │       ├─ 调用工具
    │       └─> 返回: ToolResult
    │
    ├─> 5. 结果综合
    │   └─> Router._synthesize()
    │       ├─ 简化的 synthesis prompt (15 行)
    │       ├─ 工具结果
    │       └─> 返回: 自然语言回复
    │
    └─> 6. 更新记忆
        └─> Memory.update()
            ├─ 添加到工作记忆
            ├─ 提取事实 (车型、污染物等)
            └─ 缓存文件分析 (路径 + mtime)
```

---

## 核心组件详解

### 1. UnifiedRouter (core/router.py)

**职责**: 系统的核心协调器，处理所有用户请求

**核心方法**:

```python
class UnifiedRouter:
    async def process(
        self,
        user_message: str,
        file_path: Optional[str] = None
    ) -> RouterResponse:
        """
        处理用户消息的主入口
        
        流程:
        1. 分析文件 (如有) - 带 mtime 缓存
        2. 组装上下文 - 工作记忆 + 事实记忆 + 文件
        3. 调用 LLM - 生成工具调用或直接回复
        4. 执行工具 - 标准化参数并调用
        5. 综合结果 - 生成自然语言回复
        6. 更新记忆 - 保存对话和事实
        """
```

**关键特性**:

1. **文件缓存 (mtime 检测)**
   ```python
   # 获取文件修改时间
   current_mtime = os.path.getmtime(file_path_str)
   
   # 缓存有效条件: 路径和 mtime 都匹配
   cache_valid = (
       cached
       and str(cached.get("file_path")) == file_path_str
       and cached.get("file_mtime") == current_mtime
   )
   ```
   
   **为什么需要 mtime?**
   - API 将同一会话的文件保存为 `{session_id}_input.csv`
   - 新文件会覆盖旧文件，但路径相同
   - 仅比较路径会导致使用过期缓存
   - mtime 检测确保文件内容变化时重新分析

2. **车型确认检查 (Python 规则)**
   ```python
   if tool_call.name == "calculate_micro_emission":
       vehicle_type = tool_call.arguments.get("vehicle_type")
       if vehicle_type:
           # 检查用户消息中是否明确提到车型
           user_msg = context.messages[-1].get("content", "").lower()
           vehicle_keywords = ["小汽车", "轿车", "公交", "货车", ...]
           has_vehicle_mention = any(kw in user_msg for kw in vehicle_keywords)
           
           if not has_vehicle_mention:
               return RouterResponse(
                   text="请先告诉我车辆类型..."
               )
   ```
   
   **为什么用 Python 规则而不是 Prompt?**
   - 车型确认是关键业务逻辑，不能出错
   - Python 规则更可靠、更快速
   - 避免 prompt 膨胀

3. **简化的 Synthesis Prompt (15 行)**
   ```python
   SYNTHESIS_PROMPT = """
   你是排放计算助手。根据工具执行结果，生成自然、专业的回复。
   
   要求:
   - 直接陈述结果，不要重复用户问题
   - 使用中文，专业但易懂
   - 如有图表或表格，简要说明即可
   - 不要编造数据
   """
   ```
   
   **对比旧版 (76 行)**:
   - 旧版: 详细的格式指导、示例、注意事项
   - 新版: 核心要求，信任 LLM 理解
   - 效果: 省 ~200 tokens/请求，响应更自然

### 2. ContextAssembler (core/assembler.py)

**职责**: 组装 LLM 所需的上下文信息

**核心方法**:

```python
class ContextAssembler:
    def assemble(
        self,
        user_message: str,
        file_context: Optional[Dict] = None
    ) -> AssembledContext:
        """
        组装完整上下文
        
        包含:
        1. System Prompt (工具定义)
        2. 工作记忆 (最近 5 轮对话)
        3. 事实记忆 (车型、污染物、年份等)
        4. 文件上下文 (如有)
        5. 当前用户消息
        """
```

**上下文结构**:

```python
{
    "messages": [
        {
            "role": "system",
            "content": "你是排放计算助手...\n\n可用工具:\n- query_emission_factors\n- calculate_micro_emission\n- ..."
        },
        {
            "role": "user",
            "content": "[上下文] 最近使用的车型: 小汽车\n最近查询的污染物: CO2\n\n[当前消息] 查询 2020 年的排放因子"
        }
    ],
    "tools": [...],  # 工具定义
    "file_context": {...}  # 文件分析结果 (如有)
}
```

**上下文优化**:

1. **工作记忆**: 只保留最近 5 轮，避免 token 浪费
2. **事实记忆**: 结构化提取，快速访问
3. **文件上下文**: 只包含关键信息 (列名、行数、任务类型)

### 3. ToolExecutor (core/executor.py)

**职责**: 执行工具调用，透明地标准化参数

**核心方法**:

```python
class ToolExecutor:
    async def execute(
        self,
        tool_name: str,
        arguments: Dict
    ) -> ToolResult:
        """
        执行工具
        
        流程:
        1. 标准化参数 (车型、污染物)
        2. 获取工具实例
        3. 调用工具
        4. 返回结果
        """
```

**透明标准化**:

```python
# LLM 看到的参数
{
    "vehicle_type": "小汽车",
    "pollutant": "二氧化碳",
    "model_year": 2020
}

# 标准化后传给工具的参数
{
    "vehicle_type": "Passenger Car",
    "pollutant": "CO2",
    "model_year": 2020
}
```

**为什么透明?**
- LLM 不需要知道标准化的存在
- 用户可以用任何方式表达 (小汽车、轿车、passenger car)
- 工具只接收标准化的参数

### 4. MemoryManager (core/memory.py)

**职责**: 管理三层记忆系统

**数据结构**:

```python
@dataclass
class Turn:
    """单次对话轮次"""
    user: str
    assistant: str
    tool_calls: Optional[List[Dict]] = None

@dataclass
class FactMemory:
    """事实记忆 - 结构化信息"""
    recent_vehicle: Optional[str] = None
    recent_pollutants: List[str] = field(default_factory=list)
    recent_year: Optional[int] = None
    active_file: Optional[str] = None
    file_analysis: Optional[Dict] = None  # 包含 file_path 和 file_mtime

class MemoryManager:
    def __init__(self):
        self.working_memory: List[Turn] = []  # 最近 5 轮
        self.fact_memory: FactMemory = FactMemory()
        self.compressed_memory: str = ""  # 早期对话摘要
```

**记忆更新**:

```python
def update(
    self,
    user_message: str,
    assistant_response: str,
    tool_calls: Optional[List[Dict]] = None,
    file_path: Optional[str] = None,
    file_analysis: Optional[Dict] = None
):
    # 1. 添加到工作记忆
    turn = Turn(user=user_message, assistant=assistant_response, tool_calls=tool_calls)
    self.working_memory.append(turn)
    
    # 2. 提取事实
    if tool_calls:
        self._extract_facts_from_tool_calls(tool_calls)
    
    # 3. 缓存文件分析 (包含 mtime)
    if file_path and file_analysis:
        self.fact_memory.active_file = str(file_path)
        self.fact_memory.file_analysis = file_analysis  # 包含 file_mtime
    
    # 4. 保持工作记忆大小
    if len(self.working_memory) > 5:
        self.working_memory = self.working_memory[-5:]
```

**事实提取**:

```python
def _extract_facts_from_tool_calls(self, tool_calls: List[Dict]):
    """从工具调用中提取事实"""
    for tc in tool_calls:
        args = tc.get("arguments", {})
        
        # 提取车型
        if "vehicle_type" in args:
            self.fact_memory.recent_vehicle = args["vehicle_type"]
        
        # 提取污染物
        if "pollutants" in args:
            self.fact_memory.recent_pollutants = args["pollutants"]
        elif "pollutant" in args:
            self.fact_memory.recent_pollutants = [args["pollutant"]]
        
        # 提取年份
        if "model_year" in args:
            self.fact_memory.recent_year = args["model_year"]
```

---

## 完整工作流程

### 场景 1: 排放因子查询 (无文件)

```
用户: "查询 2020 年小汽车的 CO2 排放因子"
    │
    ▼
Router.process(user_message="查询 2020 年小汽车的 CO2 排放因子", file_path=None)
    │
    ├─> 1. 文件分析: 跳过 (无文件)
    │
    ├─> 2. 组装上下文
    │   Assembler.assemble()
    │   └─> messages = [
    │           {"role": "system", "content": "你是排放计算助手..."},
    │           {"role": "user", "content": "查询 2020 年小汽车的 CO2 排放因子"}
    │       ]
    │
    ├─> 3. LLM 决策
    │   LLMClient.chat_with_tools(messages, tools)
    │   └─> 返回: ToolCall(
    │           name="query_emission_factors",
    │           arguments={
    │               "vehicle_type": "小汽车",
    │               "pollutant": "CO2",
    │               "model_year": 2020
    │           }
    │       )
    │
    ├─> 4. 执行工具
    │   Executor.execute("query_emission_factors", {...})
    │   │
    │   ├─> 4.1 标准化参数
    │   │   Standardizer.standardize_vehicle("小汽车") → "Passenger Car"
    │   │   Standardizer.standardize_pollutant("CO2") → "CO2"
    │   │
    │   ├─> 4.2 调用工具
    │   │   QueryEmissionFactorsTool.execute(
    │   │       vehicle_type="Passenger Car",
    │   │       pollutant="CO2",
    │   │       model_year=2020
    │   │   )
    │   │   │
    │   │   └─> Calculator.query_emission_factors()
    │   │       ├─ 读取 MOVES 数据
    │   │       ├─ 插值计算速度曲线
    │   │       └─ 返回: {
    │   │             "speed_curve": [...],
    │   │             "key_points": {...}
    │   │           }
    │   │
    │   └─> 返回: ToolResult(
    │           success=True,
    │           data={...},
    │           summary="查询成功"
    │       )
    │
    ├─> 5. 综合结果
    │   Router._synthesize(tool_results)
    │   └─> LLM 生成自然语言回复:
    │       "2020 年小汽车的 CO2 排放因子曲线如下..."
    │
    └─> 6. 更新记忆
        Memory.update(
            user_message="查询 2020 年小汽车的 CO2 排放因子",
            assistant_response="2020 年小汽车的 CO2 排放因子曲线如下...",
            tool_calls=[{
                "name": "query_emission_factors",
                "arguments": {"vehicle_type": "小汽车", "pollutant": "CO2", ...}
            }]
        )
        ├─> 工作记忆: 添加本轮对话
        └─> 事实记忆: recent_vehicle="小汽车", recent_pollutants=["CO2"], recent_year=2020
```

### 场景 2: 微观排放计算 (有文件)

```
用户: 上传 trajectory.csv + "计算这个轨迹的排放"
    │
    ▼
Router.process(user_message="计算这个轨迹的排放", file_path="/tmp/xxx_input.csv")
    │
    ├─> 1. 文件分析 (带 mtime 缓存)
    │   │
    │   ├─> 检查缓存
    │   │   current_mtime = os.path.getmtime("/tmp/xxx_input.csv")  # 1771663362.52
    │   │   cached = memory.get_fact_memory().get("file_analysis")
    │   │   
    │   │   if cached and cached["file_path"] == "/tmp/xxx_input.csv" and cached["file_mtime"] == current_mtime:
    │   │       使用缓存
    │   │   else:
    │   │       重新分析
    │   │
    │   └─> FileAnalyzer.analyze_file("/tmp/xxx_input.csv")
    │       ├─ 读取文件结构 (列名、行数)
    │       ├─ 读取示例数据 (前 3 行)
    │       ├─ 智能识别任务类型: "micro_emission"
    │       └─ 返回: {
    │             "file_path": "/tmp/xxx_input.csv",
    │             "file_mtime": 1771663362.52,
    │             "columns": ["time", "speed_kph", "acceleration", "grade"],
    │             "row_count": 1000,
    │             "file_task_type": "micro_emission"
    │           }
    │
    ├─> 2. 组装上下文
    │   Assembler.assemble(user_message, file_context)
    │   └─> messages = [
    │           {"role": "system", "content": "你是排放计算助手..."},
    │           {"role": "user", "content": 
    │               "[文件上传] 文件路径: /tmp/xxx_input.csv\n" +
    │               "文件类型: 微观排放轨迹数据\n" +
    │               "列名: time, speed_kph, acceleration, grade\n" +
    │               "行数: 1000\n\n" +
    │               "[用户消息] 计算这个轨迹的排放"
    │           }
    │       ]
    │
    ├─> 3. LLM 决策
    │   LLMClient.chat_with_tools(messages, tools)
    │   └─> 返回: ToolCall(
    │           name="calculate_micro_emission",
    │           arguments={
    │               "file_path": "/tmp/xxx_input.csv",
    │               "vehicle_type": "小汽车",  # LLM 可能从上下文推断
    │               "model_year": 2020,
    │               "pollutants": ["CO2", "NOx"]
    │           }
    │       )
    │
    ├─> 4. 车型确认检查 (Python 规则)
    │   if tool_call.name == "calculate_micro_emission":
    │       vehicle_type = "小汽车"
    │       user_msg = "计算这个轨迹的排放"
    │       
    │       # 检查用户消息中是否提到车型
    │       has_vehicle_mention = any(kw in user_msg for kw in ["小汽车", "轿车", ...])
    │       
    │       if not has_vehicle_mention:
    │           return RouterResponse(text="请先告诉我车辆类型...")
    │
    ├─> 5. 执行工具 (如果通过车型检查)
    │   Executor.execute("calculate_micro_emission", {...})
    │   │
    │   ├─> 5.1 标准化参数
    │   │   vehicle_type: "小汽车" → "Passenger Car"
    │   │   pollutants: ["CO2", "NOx"] → ["CO2", "NOx"]
    │   │
    │   ├─> 5.2 调用工具
    │   │   MicroEmissionTool.execute(
    │   │       file_path="/tmp/xxx_input.csv",
    │   │       vehicle_type="Passenger Car",
    │   │       model_year=2020,
    │   │       pollutants=["CO2", "NOx"]
    │   │   )
    │   │   │
    │   │   ├─> 读取轨迹数据
    │   │   ├─> 计算 VSP
    │   │   ├─> 计算排放
    │   │   ├─> 生成结果 Excel
    │   │   └─> 返回: {
    │   │         "total_emissions": {...},
    │   │         "download_file": "/tmp/xxx_output.xlsx"
    │   │       }
    │   │
    │   └─> 返回: ToolResult(success=True, data={...})
    │
    ├─> 6. 综合结果
    │   Router._synthesize(tool_results)
    │   └─> "计算完成，总排放量: CO2 1234.5g, NOx 56.7g"
    │
    └─> 7. 更新记忆
        Memory.update(
            user_message="计算这个轨迹的排放",
            assistant_response="计算完成...",
            tool_calls=[...],
            file_path="/tmp/xxx_input.csv",
            file_analysis={
                "file_path": "/tmp/xxx_input.csv",
                "file_mtime": 1771663362.52,  # 关键: 保存 mtime
                ...
            }
        )
```

### 场景 3: 多轮对话 (上下文延续)

```
第 1 轮:
用户: "查询 2020 年小汽车的 CO2 排放因子"
助手: "2020 年小汽车的 CO2 排放因子曲线如下..."
    └─> 记忆更新: recent_vehicle="小汽车", recent_pollutants=["CO2"], recent_year=2020

第 2 轮:
用户: "那公交车呢？"
    │
    ▼
Router.process(user_message="那公交车呢？", file_path=None)
    │
    ├─> 1. 组装上下文 (包含事实记忆)
    │   Assembler.assemble()
    │   └─> messages = [
    │           {"role": "system", "content": "..."},
    │           {"role": "user", "content": 
    │               "[上下文] 最近使用的车型: 小汽车\n" +
    │               "最近查询的污染物: CO2\n" +
    │               "最近查询的年份: 2020\n\n" +
    │               "[当前消息] 那公交车呢？"
    │           }
    │       ]
    │
    ├─> 2. LLM 决策 (理解上下文)
    │   LLMClient.chat_with_tools(messages, tools)
    │   └─> LLM 理解: 用户想查询公交车的 CO2 排放因子 (2020 年)
    │       返回: ToolCall(
    │           name="query_emission_factors",
    │           arguments={
    │               "vehicle_type": "公交车",
    │               "pollutant": "CO2",  # 从上下文继承
    │               "model_year": 2020   # 从上下文继承
    │           }
    │       )
    │
    └─> 3. 执行工具并返回结果
        "2020 年公交车的 CO2 排放因子曲线如下..."
```

### 场景 4: 文件覆盖场景 (mtime 检测)

```
第 1 轮: 上传 micro_trajectory.csv
    │
    ├─> 文件分析
    │   file_path = "/tmp/session123_input.csv"
    │   file_mtime = 1771663362.52
    │   file_task_type = "micro_emission"
    │   
    │   缓存: {
    │       "file_path": "/tmp/session123_input.csv",
    │       "file_mtime": 1771663362.52,
    │       "file_task_type": "micro_emission"
    │   }
    │
    └─> 执行 calculate_micro_emission

第 2 轮: 上传 macro_network.csv (覆盖同一文件)
    │
    ├─> 文件分析
    │   file_path = "/tmp/session123_input.csv"  # 路径相同!
    │   file_mtime = 1771663400.15  # mtime 不同!
    │   
    │   检查缓存:
    │   cached["file_path"] == file_path  ✓
    │   cached["file_mtime"] == file_mtime  ✗  (1771663362.52 != 1771663400.15)
    │   
    │   缓存失效，重新分析:
    │   file_task_type = "macro_emission"  # 正确识别为宏观数据
    │   
    │   更新缓存: {
    │       "file_path": "/tmp/session123_input.csv",
    │       "file_mtime": 1771663400.15,  # 新的 mtime
    │       "file_task_type": "macro_emission"
    │   }
    │
    └─> 执行 calculate_macro_emission  # 正确的工具!
```

**如果没有 mtime 检测会怎样?**
```
第 2 轮: 上传 macro_network.csv
    │
    ├─> 文件分析
    │   file_path = "/tmp/session123_input.csv"
    │   
    │   检查缓存:
    │   cached["file_path"] == file_path  ✓
    │   
    │   使用缓存 (错误!):
    │   file_task_type = "micro_emission"  # 错误! 应该是 macro_emission
    │
    └─> LLM 调用 calculate_micro_emission  # 错误的工具!
        └─> 触发车型确认检查 (不应该出现)
```

---

## 三层记忆系统

### 设计目标

1. **高效**: 避免发送过多历史对话消耗 token
2. **准确**: 保留关键信息用于上下文理解
3. **灵活**: 支持长对话而不丢失重要信息

### 三层结构

```
┌─────────────────────────────────────────────────────────────┐
│                    Working Memory (工作记忆)                  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  最近 5 轮完整对话                                       │ │
│  │  ├─ Turn 1: user + assistant + tool_calls              │ │
│  │  ├─ Turn 2: user + assistant + tool_calls              │ │
│  │  ├─ Turn 3: user + assistant + tool_calls              │ │
│  │  ├─ Turn 4: user + assistant + tool_calls              │ │
│  │  └─ Turn 5: user + assistant + tool_calls              │ │
│  └────────────────────────────────────────────────────────┘ │
│  特点: 完整保留，用于理解最近的对话上下文                      │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     Fact Memory (事实记忆)                    │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  结构化的关键信息                                         │ │
│  │  ├─ recent_vehicle: "小汽车"                            │ │
│  │  ├─ recent_pollutants: ["CO2", "NOx"]                  │ │
│  │  ├─ recent_year: 2020                                  │ │
│  │  ├─ active_file: "/tmp/xxx_input.csv"                  │ │
│  │  └─ file_analysis: {                                   │ │
│  │        "file_path": "/tmp/xxx_input.csv",              │ │
│  │        "file_mtime": 1771663362.52,                    │ │
│  │        "file_task_type": "micro_emission"              │ │
│  │     }                                                   │ │
│  └────────────────────────────────────────────────────────┘ │
│  特点: 快速访问，用于参数继承和上下文补全                      │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                 Compressed Memory (压缩记忆)                  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  早期对话的摘要 (预留功能)                               │ │
│  │  "用户在前面的对话中查询了多种车型的排放因子..."          │ │
│  └────────────────────────────────────────────────────────┘ │
│  特点: 节省 token，保留长期上下文                             │
└─────────────────────────────────────────────────────────────┘
```

### 记忆流转

```
新对话轮次
    │
    ▼
添加到 Working Memory
    │
    ├─> 如果 Working Memory > 5 轮
    │   └─> 最旧的 1 轮移除 (或压缩到 Compressed Memory)
    │
    └─> 提取事实到 Fact Memory
        ├─ 从 tool_calls 提取车型、污染物、年份
        ├─ 更新 active_file
        └─ 缓存 file_analysis (包含 mtime)
```

### 上下文组装示例

```python
def assemble_context(self, user_message: str, file_context: Optional[Dict]) -> str:
    """组装发送给 LLM 的上下文"""
    
    parts = []
    
    # 1. 事实记忆 (如果有)
    fact_memory = self.memory.get_fact_memory()
    if fact_memory.get("recent_vehicle"):
        parts.append(f"[上下文] 最近使用的车型: {fact_memory['recent_vehicle']}")
    if fact_memory.get("recent_pollutants"):
        parts.append(f"最近查询的污染物: {', '.join(fact_memory['recent_pollutants'])}")
    if fact_memory.get("recent_year"):
        parts.append(f"最近查询的年份: {fact_memory['recent_year']}")
    
    # 2. 文件上下文 (如果有)
    if file_context:
        parts.append(f"\n[文件上传] 文件路径: {file_context['file_path']}")
        parts.append(f"文件类型: {file_context['file_task_type']}")
        parts.append(f"列名: {', '.join(file_context['columns'])}")
        parts.append(f"行数: {file_context['row_count']}")
    
    # 3. 当前消息
    parts.append(f"\n[当前消息] {user_message}")
    
    return "\n".join(parts)
```

---

## 文件处理与缓存

### 文件分析流程

```python
# tools/file_analyzer.py

class FileAnalyzer:
    async def analyze_file(self, file_path: str) -> Dict:
        """
        分析上传的文件
        
        返回:
        {
            "file_path": str,
            "file_mtime": float,  # 文件修改时间
            "columns": List[str],
            "row_count": int,
            "sample_data": List[Dict],
            "file_task_type": str  # "micro_emission" 或 "macro_emission"
        }
        """
        
        # 1. 读取文件基本信息
        df = pd.read_excel(file_path) if file_path.endswith('.xlsx') else pd.read_csv(file_path)
        
        # 2. 提取结构信息
        columns = list(df.columns)
        row_count = len(df)
        sample_data = df.head(3).to_dict(orient="records")
        
        # 3. 智能识别任务类型
        task_type = self._identify_task_type(columns, sample_data)
        
        return {
            "file_path": str(file_path),
            "file_mtime": os.path.getmtime(file_path),  # 关键: 记录 mtime
            "columns": columns,
            "row_count": row_count,
            "sample_data": sample_data,
            "file_task_type": task_type
        }
    
    def _identify_task_type(self, columns: List[str], sample_data: List[Dict]) -> str:
        """
        识别文件任务类型
        
        微观排放特征:
        - 有 time/speed/acceleration 等列
        - 数据是逐秒的轨迹点
        
        宏观排放特征:
        - 有 link_id/length/flow/avg_speed 等列
        - 有车队组成列 (Passenger Car, Bus, Truck 等)
        """
        columns_lower = [c.lower() for c in columns]
        
        # 检查微观排放特征
        micro_keywords = ["time", "speed", "acceleration", "grade", "trajectory"]
        has_micro = sum(1 for kw in micro_keywords if any(kw in col for col in columns_lower))
        
        # 检查宏观排放特征
        macro_keywords = ["link", "flow", "fleet", "passenger car", "bus", "truck"]
        has_macro = sum(1 for kw in macro_keywords if any(kw in col for col in columns_lower))
        
        if has_micro > has_macro:
            return "micro_emission"
        else:
            return "macro_emission"
```

### 缓存机制

**问题**: 同一会话上传多个文件时，API 将文件保存为 `{session_id}_input.csv`，新文件会覆盖旧文件

**解决方案**: 使用文件修改时间 (mtime) 检测文件是否变化

```python
# core/router.py

async def process(self, user_message: str, file_path: Optional[str] = None):
    file_context = None
    if file_path:
        from pathlib import Path
        import os

        cached = self.memory.get_fact_memory().get("file_analysis")
        file_path_str = str(file_path)

        # 获取当前文件的 mtime
        try:
            current_mtime = os.path.getmtime(file_path_str)
        except Exception:
            current_mtime = None

        # 缓存有效条件: 路径和 mtime 都匹配
        cache_valid = (
            cached
            and str(cached.get("file_path")) == file_path_str
            and cached.get("file_mtime") == current_mtime
        )

        if cache_valid:
            file_context = cached
            logger.info(f"Using cached file analysis for {file_path}")
        else:
            # 重新分析文件
            file_context = await self._analyze_file(file_path)
            file_context["file_path"] = file_path_str
            file_context["file_mtime"] = current_mtime
            logger.info(f"Analyzed new file: {file_path} (mtime: {current_mtime})")
```

**缓存失效场景**:

1. **文件路径不同**: 新会话或不同文件名
2. **文件 mtime 不同**: 同一路径但文件被覆盖
3. **缓存不存在**: 首次上传文件

**缓存命中场景**:

1. **追问场景**: 用户上传文件后，在同一会话中追问
2. **路径和 mtime 都匹配**: 文件未被修改

### 文件存储策略

```python
# api/routes.py

@router.post("/api/chat")
async def chat(
    message: str = Form(...),
    session_id: str = Form(None),
    file: UploadFile = File(None)
):
    if file:
        # 保存文件: {session_id}_input{suffix}
        suffix = Path(file.filename).suffix
        input_file_path = TEMP_DIR / f"{session.session_id}_input{suffix}"
        
        with open(input_file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        # 文件路径传给 Router
        result = await session.chat(message, input_file_path)
```

**优点**:
- 简单: 每个会话只有一个输入文件
- 自动清理: 新文件覆盖旧文件

**缺点**:
- 需要 mtime 检测来识别文件变化

---

## 工具系统

### 工具定义

系统提供 5 个工具，每个工具都遵循 OpenAI Function Calling 标准：

```python
# tools/definitions.py

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_emission_factors",
            "description": "Query vehicle emission factor curves by speed. Returns chart and data table.",
            "parameters": {
                "type": "object",
                "properties": {
                    "vehicle_type": {
                        "type": "string",
                        "description": "Vehicle type (e.g., Passenger Car, Bus, Truck)"
                    },
                    "pollutant": {
                        "type": "string",
                        "description": "Pollutant name (e.g., CO2, NOx, PM2.5)"
                    },
                    "model_year": {
                        "type": "integer",
                        "description": "Model year (1995-2025)"
                    },
                    "season": {
                        "type": "string",
                        "enum": ["summer", "winter", "spring"],
                        "description": "Season (default: summer)"
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
            "description": "Calculate emissions from second-by-second trajectory data using VSP method.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to trajectory data file"
                    },
                    "vehicle_type": {
                        "type": "string",
                        "description": "Vehicle type"
                    },
                    "model_year": {
                        "type": "integer",
                        "description": "Model year"
                    },
                    "pollutants": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of pollutants to calculate"
                    }
                },
                "required": ["file_path", "vehicle_type", "model_year", "pollutants"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_macro_emission",
            "description": "Calculate emissions for road network using fleet composition and traffic data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to road network data file"
                    },
                    "model_year": {
                        "type": "integer",
                        "description": "Model year"
                    },
                    "pollutants": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of pollutants to calculate"
                    }
                },
                "required": ["file_path", "model_year", "pollutants"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_file",
            "description": "Analyze uploaded file structure and identify task type.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to file"
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_knowledge",
            "description": "Search emission calculation knowledge base (reserved).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query"
                    }
                },
                "required": ["query"]
            }
        }
    }
]
```

### 工具简化原则

**优化前** (冗长的描述):
```python
{
    "name": "query_emission_factors",
    "description": """
    Query vehicle emission factor curves from EPA MOVES database.
    
    Use this when:
    - User wants to know emission factors for a specific vehicle type
    - User asks about speed-emission relationships
    - User needs emission factor data for calculations
    
    This tool will:
    - Query MOVES database
    - Interpolate emission factors by speed
    - Return chart data and key speed points
    """
}
```

**优化后** (简洁的描述):
```python
{
    "name": "query_emission_factors",
    "description": "Query vehicle emission factor curves by speed. Returns chart and data table."
}
```

**效果**:
- 省 ~50 tokens/工具
- 5 个工具共省 ~250 tokens/请求
- LLM 更容易理解工具用途

### 工具执行流程

```
LLM 返回工具调用
    │
    ▼
Executor.execute(tool_name, arguments)
    │
    ├─> 1. 标准化参数
    │   ├─ vehicle_type: "小汽车" → "Passenger Car"
    │   ├─ pollutant: "二氧化碳" → "CO2"
    │   └─ pollutants: ["二氧化碳", "氮氧化物"] → ["CO2", "NOx"]
    │
    ├─> 2. 获取工具实例
    │   tool = ToolRegistry.get(tool_name)
    │
    ├─> 3. 调用工具
    │   result = await tool.execute(**standardized_args)
    │
    └─> 4. 返回结果
        return ToolResult(
            success=True/False,
            data={...},
            summary="...",
            download_file="..."  # 如有
        )
```

---

## 参数标准化

### 标准化器架构

```python
# services/standardizer.py

class Standardizer:
    """参数标准化器 - 支持 API 和本地模式"""
    
    def __init__(self):
        self.mode = config.standardizer_mode  # "api" 或 "local"
        self.cache = {}  # 缓存标准化结果
        
        if self.mode == "local":
            self.client = LocalStandardizerClient()
        else:
            self.client = APIStandardizerClient()
    
    def standardize_vehicle(self, user_input: str) -> str:
        """
        标准化车型名称
        
        输入: "小汽车", "轿车", "passenger car", "sedan"
        输出: "Passenger Car"
        """
        # 检查缓存
        if user_input in self.cache:
            return self.cache[user_input]
        
        # 调用标准化服务
        result = self.client.standardize(
            task="vehicle_type",
            input_value=user_input
        )
        
        # 缓存结果
        self.cache[user_input] = result
        return result
    
    def standardize_pollutant(self, user_input: str) -> str:
        """
        标准化污染物名称
        
        输入: "二氧化碳", "CO2", "carbon dioxide"
        输出: "CO2"
        """
        if user_input in self.cache:
            return self.cache[user_input]
        
        result = self.client.standardize(
            task="pollutant",
            input_value=user_input
        )
        
        self.cache[user_input] = result
        return result
```

### 标准映射表

```python
# config/unified_mappings.yaml

vehicle_mappings:
  # 中文别名
  小汽车: Passenger Car
  轿车: Passenger Car
  私家车: Passenger Car
  公交车: Bus
  公交: Bus
  巴士: Bus
  货车: Truck
  卡车: Truck
  # 英文别名
  passenger car: Passenger Car
  sedan: Passenger Car
  car: Passenger Car
  bus: Bus
  truck: Truck
  # ... 更多映射

pollutant_mappings:
  # 中文别名
  二氧化碳: CO2
  碳排放: CO2
  氮氧化物: NOx
  颗粒物: PM2.5
  # 英文别名
  carbon dioxide: CO2
  nitrogen oxides: NOx
  particulate matter: PM2.5
  # ... 更多映射
```

### 标准化流程

```
用户输入: "小汽车"
    │
    ▼
Standardizer.standardize_vehicle("小汽车")
    │
    ├─> 检查缓存
    │   └─> 未命中
    │
    ├─> 调用标准化服务
    │   │
    │   ├─> API 模式: 调用 LLM API
    │   │   Prompt: "将'小汽车'映射到 MOVES 标准车型"
    │   │   Response: "Passenger Car"
    │   │
    │   └─> 本地模式: 调用本地 VLLM 服务
    │       Request: {"model": "unified", "prompt": "[vehicle] 小汽车"}
    │       Response: "Passenger Car"
    │
    ├─> 缓存结果
    │   cache["小汽车"] = "Passenger Car"
    │
    └─> 返回: "Passenger Car"
```

### 集中化标准化

**优化前**: 每个工具都有自己的标准化逻辑

```python
# tools/macro_emission.py (旧代码)

def _standardize_fleet_mix(self, fleet_mix: Dict) -> Dict:
    """125 行的硬编码映射"""
    result = {}
    for raw_name, pct in fleet_mix.items():
        if raw_name in ["小汽车", "轿车", "passenger car"]:
            result["Passenger Car"] = pct
        elif raw_name in ["公交车", "公交", "bus"]:
            result["Bus"] = pct
        # ... 重复 13 种车型的映射
    return result
```

**优化后**: 使用统一的标准化器

```python
# tools/macro_emission.py (新代码)

def _standardize_fleet_mix(self, fleet_mix: Dict) -> Dict:
    """24 行，使用统一标准化器"""
    from services.standardizer import get_standardizer
    standardizer = get_standardizer()
    
    result = {}
    for raw_name, pct in fleet_mix.items():
        std_name = standardizer.standardize_vehicle(str(raw_name))
        if std_name and std_name in self.SUPPORTED_VEHICLES:
            result[std_name] = result.get(std_name, 0) + pct
    
    return result if result else None
```

**效果**:
- 代码减少 ~100 行
- 逻辑集中，易于维护
- 自动享受标准化器的改进 (缓存、本地模型等)

---

## 关键技术细节

### 动态提示词注入

系统根据用户的任务类型动态调整提示词：

```python
# core/router.py

def _build_system_prompt(self, file_context: Optional[Dict]) -> str:
    """根据上下文动态构建提示词"""
    
    base_prompt = self.config.system_prompt
    
    if file_context:
        task_type = file_context.get("file_task_type")
        
        if task_type == "micro_emission":
            # 添加微观排放任务的特定指导
            base_prompt += """

For micro-scale emission calculation:
1. Always request vehicle_type, model_year, and pollutants
2. Vehicle type is required from file (do not assume)
3. Suggest default pollutants: [CO2, NOx, CO, PM2.5, HC]
4. Use calculate_micro_emission tool with file_path
"""
        
        elif task_type == "macro_emission":
            # 添加宏观排放任务的特定指导
            base_prompt += """

For macro-scale emission calculation:
1. Extract fleet composition from file columns
2. Default to 13 standard vehicle types if not specified
3. Suggest default pollutants: [CO2, NOx, PM2.5]
4. Use calculate_macro_emission tool with file_path
"""
    
    return base_prompt
```

### 文件路径处理

系统正确处理文件路径的多种场景：

```python
# core/router.py

async def process(self, user_message: str, file_path: Optional[str] = None):
    # 1. 接收 PathLike 对象
    if file_path:
        from pathlib import Path
        import os
        
        # 2. 转换为字符串
        file_path_str = str(file_path)
        
        # 3. 获取文件 mtime
        current_mtime = os.path.getmtime(file_path_str)
        
        # 4. 保存到上下文 (字符串 + mtime)
        file_context = {
            "file_path": file_path_str,
            "file_mtime": current_mtime,
            # ...
        }
        
        # 5. 传递给工具 (字符串)
        result = await self.execute_tool(
            tool_name="calculate_micro_emission",
            arguments={"file_path": file_path_str, ...}
        )
```

**关键点**:
- `PathLike` → `str`: 确保路径可序列化
- 记录 `mtime`: 用于缓存验证
- 传递 `str`: 工具函数期望字符串路径

### 工具结果摘要

系统将工具执行结果转换为简洁的摘要，减少 token 消耗：

```python
# core/tool_executor.py

def _summarize_result(self, result: ToolResult) -> str:
    """将工具结果转换为简洁摘要"""
    
    if not result.success:
        return f"Error: {result.summary}"
    
    if result.tool_name == "query_emission_factors":
        return f"""
Queried emission factors for {result.data['vehicle_type']} ({result.data['pollutant']}, {result.data['model_year']}):
- Chart available: /static/emission_chart.png
- Data available: /static/emission_data.csv
- Key speeds: {list(result.data['emission_data'].keys())[:5]}...
"""
    
    elif result.tool_name == "calculate_micro_emission":
        return f"""
Calculated micro-scale emissions:
- Total CO2: {result.data['summary']['CO2']} kg
- Trajectory points: {result.data['trajectory_points']}
- Results: /static/micro_emission_results.csv
"""
    
    # ... 其他工具的摘要
    
    return result.summary or "Tool executed successfully"
```

### 错误处理

```python
# core/tool_executor.py

async def execute(self, tool_name: str, arguments: Dict) -> ToolResult:
    try:
        # 1. 获取工具
        tool = ToolRegistry.get(tool_name)
        if not tool:
            return ToolResult(success=False, summary=f"Unknown tool: {tool_name}")
        
        # 2. 验证参数
        validation = tool.validate(arguments)
        if not validation.valid:
            return ToolResult(success=False, summary=f"Invalid arguments: {validation.errors}")
        
        # 3. 执行工具
        result = await tool.execute(**arguments)
        
        return result
    
    except FileNotFoundError as e:
        return ToolResult(success=False, summary=f"File not found: {e}")
    
    except ValueError as e:
        return ToolResult(success=False, summary=f"Invalid value: {e}")
    
    except Exception as e:
        logger.error(f"Tool execution error: {e}", exc_info=True)
        return ToolResult(success=False, summary=f"Execution error: {str(e)}")
```

---

## 性能优化

### Token 优化策略

1. **压缩系统提示词**: ~2000 → ~400 tokens (-80%)
   - 移除冗余说明
   - 使用格式化标记而非详细描述
   - 集中重复指令

2. **简化工具描述**: ~250 tokens/请求
   - 每个工具描述从 ~100 → ~30 tokens
   - 5 个工具共省 ~350 tokens/请求

3. **使用结果摘要**: 减少 ~70-90%
   - 微观排放: 280KB → ~200B (-99.9%)
   - 宏观排放: 27MB → ~500B (-99.998%)

4. **智能缓存**:
   - 文件分析结果缓存 (带 mtime 验证)
   - 参数标准化缓存 (车型、污染物)
   - LLM API 响应缓存 (可选)

### 并发处理

```python
# tools/macro_emission.py

async def execute(self, file_path: str, model_year: int, pollutants: List[str]):
    """并发计算多种污染物"""
    
    # 1. 读取文件 (一次)
    df = pd.read_csv(file_path)
    
    # 2. 并发计算多种污染物
    tasks = [
        self._calculate_emission(df, model_year, pollutant)
        for pollutant in pollutants
    ]
    
    results = await asyncio.gather(*tasks)
    
    # 3. 合并结果
    return self._merge_results(results)
```

### 内存优化

```python
# core/memory_manager.py

class MemoryManager:
    def __init__(self, max_tokens: int = 4000):
        self.max_tokens = max_tokens
        self.estimate_token = tiktoken.encoding_for_model("gpt-4")
    
    def _truncate_conversation(self, messages: List[Dict]) -> List[Dict]:
        """截断对话以保持在 token 限制内"""
        
        current_tokens = sum(
            len(self.estimate_token.encode(msg.get("content", "")))
            for msg in messages
        )
        
        if current_tokens <= self.max_tokens:
            return messages
        
        # 保留系统提示词和最近的消息
        system_messages = [m for m in messages if m.get("role") == "system"]
        user_assistant_messages = [m for m in messages if m.get("role") in ["user", "assistant"]]
        
        # 从最新的消息开始保留
        truncated = []
        tokens = 0
        
        for msg in reversed(user_assistant_messages):
            msg_tokens = len(self.estimate_token.encode(msg.get("content", "")))
            if tokens + msg_tokens > self.max_tokens:
                break
            truncated.insert(0, msg)
            tokens += msg_tokens
        
        return system_messages + truncated
```

---

## 部署架构

### Railway 部署配置

```yaml
# railway.toml
[build]
builder = "NIXPACKS"

[deploy]
startCommand = "uvicorn api.app:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/health"
healthcheckTimeout = 300
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 10

[deploy.env]
PORT = "8000"
```

### 环境变量

```bash
# 必需
QWEN_API_KEY=xxx              # 通义千问 API Key
STANDARDIZER_MODE=api         # api 或 local

# 可选
STANDARDIZER_API_BASE=xxx     # 标准化服务 API (api 模式)
STANDARDIZER_LOCAL_URL=xxx    # 本地标准化服务 URL (local 模式)
LOG_LEVEL=INFO                # 日志级别
MAX_TOKENS=4000               # 最大上下文 tokens
```

### Docker 部署

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  emission-agent:
    build: .
    ports:
      - "8000:8000"
    environment:
      - QWEN_API_KEY=${QWEN_API_KEY}
      - STANDARDIZER_MODE=api
    volumes:
      - ./data:/app/data
      - ./temp:/app/temp
```

---

## 监控与调试

### 日志系统

```python
# utils/logger.py

import logging
import sys

def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level))
    
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    
    logger.addHandler(handler)
    return logger
```

### 关键日志点

```python
# core/router.py

logger.info(f"Processing message: {user_message[:100]}...")
logger.debug(f"File context: {file_context}")
logger.info(f"LLM decision: {decision} (tools: {len(decision.tool_calls)})")
logger.debug(f"Tool results: {results}")
logger.info(f"Final response: {response[:100]}...")
```

### 调试模式

```python
# 启用调试日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 查看完整的 LLM 请求/响应
logger.debug(f"LLM request: {messages}")
logger.debug(f"LLM response: {completion}")
```

---

## 总结

### 核心设计原则

1. **AI-First**: AI 模型负责决策，代码负责执行
2. **最小化代码**: 只实现必要的逻辑，避免过度设计
3. **Token 优化**: 压缩提示词，简化工具描述，使用结果摘要
4. **智能缓存**: 文件分析缓存，参数标准化缓存
5. **可扩展性**: 插件式工具系统，易于添加新功能

### 技术栈

- **LLM**: 通义千问 (qwen-plus)
- **框架**: FastAPI + Uvicorn
- **数据处理**: Pandas + NumPy
- **科学计算**: SciPy (插值)
- **部署**: Railway / Docker

### 项目结构

```
emission_agent/
├── api/                    # API 层
│   ├── routes.py          # SSE 聊天端点
│   └── app.py             # FastAPI 应用
├── core/                   # 核心逻辑
│   ├── router.py          # AI 统一路由
│   ├── assembler.py       # 上下文组装器
│   ├── executor.py        # 工具执行器
│   └── memory.py          # 记忆管理
├── tools/                  # 工具实现
│   ├── definitions.py     # 工具定义
│   ├── registry.py        # 工具注册表
│   ├── base.py            # 工具基类
│   ├── micro_emission.py  # 微观排放
│   ├── macro_emission.py  # 宏观排放
│   ├── query_factors.py   # 因子查询
│   ├── file_analyzer.py   # 文件分析
│   └── knowledge.py       # 知识库
├── services/               # 服务层
│   └── standardizer.py    # 参数标准化
├── models/                 # 数据模型
│   └── schemas.py         # Pydantic 模型
├── config/                 # 配置
│   └── settings.py        # 配置管理
├── utils/                  # 工具函数
│   ├── logger.py          # 日志
│   └── helpers.py         # 辅助函数
└── docs/                   # 文档
    └── ARCHITECTURE.md    # 架构文档 (本文档)
```

### 快速开始

```bash
# 1. 克隆项目
git clone <repo>
cd emission_agent

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
export QWEN_API_KEY=your_api_key

# 4. 启动服务
uvicorn api.app:app --reload

# 5. 访问 API
curl http://localhost:8000/health
```

### 下一步

- [ ] 添加更多工具 (图表生成、数据分析)
- [ ] 实现 LLM 响应缓存
- [ ] 添加用户认证
- [ ] 实现多用户会话隔离
- [ ] 添加前端 UI (Streamlit/React)

---

**文档版本**: 1.0  
**最后更新**: 2025-02-23  
**作者**: Claude Code
