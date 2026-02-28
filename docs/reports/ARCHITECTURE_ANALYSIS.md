# Emission Agent 架构与数据流

## 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend (Web)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Chat UI     │  │  File Upload │  │  History     │      │
│  │  (app.js)    │  │  (app.js)    │  │  (app.js)    │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                  │                  │              │
└─────────┼──────────────────┼──────────────────┼──────────────┘
          │                  │                  │
          │ POST /api/chat   │ POST /api/file   │ GET /api/sessions/{id}/history
          │                  │                  │
┌─────────▼──────────────────▼──────────────────▼──────────────┐
│                      API Layer (FastAPI)                      │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  routes.py                                           │    │
│  │  - chat_endpoint()      ← 问题3: 文件路径传递       │    │
│  │  - file_preview()                                    │    │
│  │  - get_session_history() ← 问题1: 缺少图表数据      │    │
│  │  - build_emission_chart_data() ← 问题2: 格式不一致  │    │
│  └──────────────┬───────────────────────────────────────┘    │
│                 │                                             │
└─────────────────┼─────────────────────────────────────────────┘
                  │
                  │ agent.chat(message)
                  │
┌─────────────────▼─────────────────────────────────────────────┐
│                      Agent Core                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  core.py                                             │    │
│  │  1. Planning (with validation) ← 问题4: 规划能力弱   │    │
│  │  2. Execution                                        │    │
│  │  3. Synthesis                                        │    │
│  │  4. Learning                                         │    │
│  └──────────────┬───────────────────────────────────────┘    │
│                 │                                             │
│  ┌──────────────▼───────────────────────────────────────┐    │
│  │  context.py                                          │    │
│  │  - ConversationTurn ← 问题1: 缺少 chart_data 字段   │    │
│  │  - Parameter merging                                 │    │
│  │  - History management                                │    │
│  └──────────────┬───────────────────────────────────────┘    │
│                 │                                             │
│  ┌──────────────▼───────────────────────────────────────┐    │
│  │  validator.py                                        │    │
│  │  - Plan validation ← 问题3: 过于严格                 │    │
│  │  - Field name correction                             │    │
│  └──────────────────────────────────────────────────────┘    │
└───────────────────────────┬───────────────────────────────────┘
                            │
                            │ skill.execute(params)
                            │
┌───────────────────────────▼───────────────────────────────────┐
│                         Skills Layer                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ emission_    │  │ macro_       │  │ micro_       │       │
│  │ factors      │  │ emission     │  │ emission     │       │
│  │              │  │              │  │              │       │
│  │ ← 问题2:     │  │              │  │              │       │
│  │   返回格式   │  │              │  │              │       │
│  │   不一致     │  │              │  │              │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└───────────────────────────────────────────────────────────────┘
```

---

## 问题1: 历史图表消失 - 数据流分析

### 当前流程（有问题）

```
用户查询 "2020年款公交车的 NOx 排放因子"
    │
    ▼
┌─────────────────────────────────────────┐
│ Agent 执行 query_emission_factors       │
│ 返回: {speed_curve: [...], ...}        │
└─────────────┬───────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│ API routes.py                           │
│ - 提取 chart_data                       │
│ - 返回给前端                            │
│ - ❌ 但不保存到 turn                    │
└─────────────┬───────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│ 前端显示图表 ✅                         │
└─────────────────────────────────────────┘

用户切换会话，再切换回来
    │
    ▼
┌─────────────────────────────────────────┐
│ GET /api/sessions/{id}/history         │
│ agent.get_history()                     │
│ 返回: {                                 │
│   role: "assistant",                    │
│   content: "...",                       │
│   has_data: true  ← ❌ 只有标志         │
│ }                                       │
└─────────────┬───────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│ 前端 renderHistory()                    │
│ addAssistantMessage({                   │
│   reply: msg.content,                   │
│   has_data: true  ← ❌ 缺少 chart_data  │
│ })                                      │
│ → 无法渲染图表 ❌                       │
└─────────────────────────────────────────┘
```

### 修复后流程

```
用户查询 "2020年款公交车的 NOx 排放因子"
    │
    ▼
┌─────────────────────────────────────────┐
│ Agent 执行 query_emission_factors       │
│ 返回: {speed_curve: [...], ...}        │
└─────────────┬───────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│ API routes.py                           │
│ - 提取 chart_data                       │
│ - 返回给前端                            │
│ - ✅ 保存到 turn.chart_data             │
└─────────────┬───────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│ 前端显示图表 ✅                         │
└─────────────────────────────────────────┘

用户切换会话，再切换回来
    │
    ▼
┌─────────────────────────────────────────┐
│ GET /api/sessions/{id}/history         │
│ agent.get_history()                     │
│ 返回: {                                 │
│   role: "assistant",                    │
│   content: "...",                       │
│   has_data: true,                       │
│   chart_data: {...},  ← ✅ 完整数据     │
│   data_type: "chart"  ← ✅ 类型标识     │
│ }                                       │
└─────────────┬───────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│ 前端 renderHistory()                    │
│ addAssistantMessage({                   │
│   reply: msg.content,                   │
│   chart_data: msg.chart_data,  ← ✅     │
│   data_type: msg.data_type     ← ✅     │
│ })                                      │
│ → 成功渲染图表 ✅                       │
└─────────────────────────────────────────┘
```

---

## 问题3: 文件上传失败 - 数据流分析

### 当前流程（有问题）

```
用户上传 micro_emission_example.csv
    │
    ▼
┌─────────────────────────────────────────┐
│ POST /api/chat                          │
│ - 保存文件到 /tmp/xxx.csv               │
│ - message = "帮我计算这个车辆的排放\n   │
│              [附件: xxx.csv]"           │
│              ↑ ❌ 格式不明确             │
└─────────────┬───────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│ Agent Planning                          │
│ LLM 看到: "帮我计算这个车辆的排放\n     │
│            [附件: xxx.csv]"             │
│                                         │
│ LLM 生成计划:                           │
│ {                                       │
│   "skill": "calculate_micro_emission",  │
│   "params": {                           │
│     "trajectory_data": []  ← ❌ 错误    │
│   }                                     │
│ }                                       │
└─────────────┬───────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│ Validator 检查                          │
│ - 缺少 vehicle_type ❌                  │
│ - 缺少 trajectory_data ❌               │
│ → Planning 验证失败                     │
└─────────────┬───────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│ 返回错误: "缺少必需参数 vehicle_type"   │
└─────────────────────────────────────────┘
```

### 修复后流程

```
用户上传 micro_emission_example.csv
    │
    ▼
┌─────────────────────────────────────────┐
│ POST /api/chat                          │
│ - 保存文件到 /tmp/xxx.csv               │
│ - message = "帮我计算这个车辆的排放\n   │
│              文件路径: /tmp/xxx.csv"    │
│              ↑ ✅ 格式明确               │
└─────────────┬───────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│ Agent Planning                          │
│ LLM 看到: "帮我计算这个车辆的排放\n     │
│            文件路径: /tmp/xxx.csv"      │
│                                         │
│ Prompt 指导: "当看到文件路径时，使用    │
│              input_file 参数"           │
│                                         │
│ LLM 生成计划:                           │
│ {                                       │
│   "skill": "calculate_micro_emission",  │
│   "params": {                           │
│     "input_file": "/tmp/xxx.csv",  ✅   │
│     "model_year": 2020,            ✅   │
│     "pollutants": ["CO2", "NOx"]   ✅   │
│   },                                    │
│   "clarification": "需要确认车辆类型"   │
│ }                                       │
└─────────────┬───────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│ Validator 检查                          │
│ - 有 input_file ✅                      │
│ - 跳过 vehicle_type 检查 ✅             │
│ - 跳过 trajectory_data 检查 ✅          │
│ → Planning 验证通过                     │
└─────────────┬───────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│ Skill 执行                              │
│ - 从文件读取轨迹数据 ✅                 │
│ - 发现缺少 vehicle_type                 │
│ - 返回 needs_clarification ✅           │
└─────────────┬───────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│ Agent Synthesis                         │
│ "我看到您上传了轨迹文件，包含100个数据  │
│  点。要计算排放，我需要知道车辆类型。   │
│  请问这是什么车型？（小汽车/公交车/...）"│
└─────────────────────────────────────────┘
```

---

## 数据结构对比

### ConversationTurn - 修改前后

```python
# 修改前
@dataclass
class ConversationTurn:
    user_input: str
    assistant_response: str
    understanding: str = ""
    skill_executions: List[SkillExecution] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    # ❌ 缺少图表数据字段

# 修改后
@dataclass
class ConversationTurn:
    user_input: str
    assistant_response: str
    understanding: str = ""
    skill_executions: List[SkillExecution] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # ✅ 新增字段
    chart_data: Optional[Dict] = None
    table_data: Optional[Dict] = None
    data_type: Optional[str] = None  # 'chart' or 'table'
```

### History Response - 修改前后

```python
# 修改前
{
    "role": "assistant",
    "content": "根据查询结果，2020年款公交车...",
    "timestamp": "2026-01-27T20:42:35",
    "has_data": true  # ❌ 只有标志
}

# 修改后
{
    "role": "assistant",
    "content": "根据查询结果，2020年款公交车...",
    "timestamp": "2026-01-27T20:42:35",
    "has_data": true,
    # ✅ 完整数据
    "chart_data": {
        "vehicle_type": "Transit Bus",
        "model_year": 2020,
        "pollutants": {
            "NOx": {
                "curve": [
                    {"speed_kph": 0, "emission_rate": 2.5},
                    {"speed_kph": 10, "emission_rate": 1.8},
                    ...
                ],
                "unit": "g/km"
            }
        },
        "key_points": [...]
    },
    "data_type": "chart"
}
```

---

## Planning 流程图

```
用户输入
    │
    ▼
┌─────────────────────────────────────────┐
│ 1. Planning Phase                       │
│    - 理解用户意图                       │
│    - 生成执行计划                       │
│    - 识别需要的 Skill 和参数            │
└─────────────┬───────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│ 2. Plan Enrichment                      │
│    - 从上下文补充参数                   │
│    - 合并历史参数                       │
│    - 应用默认值                         │
└─────────────┬───────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────┐
│ 3. Plan Validation ← 问题3、4 的关键    │
│    - 检查必需参数                       │
│    - 检查参数类型                       │
│    - 自动修正字段名                     │
│    - ❌ 当前: 过于严格                  │
│    - ✅ 修复: 放宽 input_file 检查      │
└─────────────┬───────────────────────────┘
              │
              ▼
        验证通过？
         /    \
       否      是
       │       │
       ▼       ▼
┌──────────┐ ┌──────────────────────────┐
│ Reflector│ │ 4. Execution             │
│ 尝试修复 │ │    - 调用 Skill          │
│          │ │    - 获取结果            │
│ 最多3次  │ └─────────┬────────────────┘
└──────────┘           │
                       ▼
              ┌──────────────────────────┐
              │ 5. Synthesis             │
              │    - 生成用户友好的回复  │
              │    - 包含结果数据        │
              └─────────┬────────────────┘
                        │
                        ▼
              ┌──────────────────────────┐
              │ 6. Save Turn             │
              │    - 保存对话记录        │
              │    - ✅ 保存图表数据     │
              └──────────────────────────┘
```

---

## 关键代码位置

### 问题1: 历史图表消失

```
agent/context.py:24-31     ConversationTurn 定义
agent/core.py:432-450      get_history() 方法
api/routes.py:138-265      chat endpoint
web/app.js:288-310         renderHistory() 函数
web/app.js:342-394         addAssistantMessage() 函数
```

### 问题2: 多污染物图表失败

```
skills/emission_factors/skill.py:148-250  execute() 方法
api/routes.py:57-99                       build_emission_chart_data()
web/app.js:421-444                        renderEmissionChart()
web/app.js:625-769                        initEmissionChart()
```

### 问题3: 文件上传失败

```
api/routes.py:138-180      文件处理
agent/prompts.py           Planning Prompt
agent/validator.py:150-200 validate() 方法
agent/core.py:139-195      _plan_with_validation()
```

### 问题4: Agent 规划能力

```
agent/prompts.py           Planning Prompt
agent/core.py:139-195      _plan_with_validation()
agent/validator.py         PlanValidator
agent/reflector.py         PlanReflector
```

---

## 修复影响范围

### 低风险修复（推荐优先）
- ✅ 修改文件路径格式（api/routes.py）
- ✅ 放宽 Validator 检查（agent/validator.py）
- ✅ 改进 Planning Prompt（agent/prompts.py）
- ✅ 修复持久化错误（agent/core.py, agent/context.py）

### 中风险修复（需要测试）
- ⚠️ 修改 ConversationTurn 结构（agent/context.py）
  - 影响: 所有使用 turn 的代码
  - 测试: 确保序列化/反序列化正常
- ⚠️ 修改 get_history() 返回格式（agent/core.py）
  - 影响: 前端历史记录渲染
  - 测试: 确保前端兼容

### 高风险修复（谨慎操作）
- ⚠️⚠️ 修改 Skill 返回格式（skills/emission_factors/skill.py）
  - 影响: 所有依赖该 Skill 的代码
  - 建议: 保持向后兼容，同时支持新旧格式

---

## 总结

所有问题都有明确的根本原因和解决方案。建议按照 `QUICK_FIXES.md` 中的顺序逐步修复，每次修复后进行测试，确保不引入新问题。

修复完成后，系统将具备：
1. ✅ 完整的历史记录（包含图表）
2. ✅ 可靠的文件上传功能
3. ✅ 更智能的 Agent 规划
4. ✅ 稳定的会话持久化
