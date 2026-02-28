# 快速修复指南

## 修复1: 文件上传失败（最高优先级）

### 问题
上传文件后，Agent 无法识别文件路径，导致计算失败。

### 修复代码

**文件: `api/routes.py` (第138-180行)**

```python
# 原代码
if file:
    file_path = temp_dir / file.filename
    with open(file_path, "wb") as f:
        f.write(await file.read())
    message_with_file = f"{message}\n\n[附件: {file.filename}]"
    response = agent.chat(message_with_file)

# 修改为
if file:
    file_path = temp_dir / file.filename
    with open(file_path, "wb") as f:
        f.write(await file.read())

    # ✅ 明确传递文件路径
    message_with_file = f"{message}\n\n文件路径: {str(file_path)}"
    response = agent.chat(message_with_file)
```

### 测试
```bash
# 上传 micro_emission_example.csv
# 发送消息: "帮我计算这个车辆的排放"
# 预期: 应该提示需要车型，而不是说"缺少文件"
```

---

## 修复2: 历史图表消失

### 问题
切换会话后，历史消息中的图表无法显示。

### 修复步骤

#### 2.1 修改 ConversationTurn 数据结构

**文件: `agent/context.py` (第24-31行)**

```python
@dataclass
class ConversationTurn:
    """单轮对话"""
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

#### 2.2 修改 get_history 方法

**文件: `agent/core.py` (第432-450行)**

```python
def get_history(self) -> List[Dict[str, Any]]:
    """获取对话历史"""
    history = []
    for turn in self._context.turns:
        # 用户消息
        history.append({
            "role": "user",
            "content": turn.user_input,
            "timestamp": turn.timestamp
        })
        # 助手回复
        history.append({
            "role": "assistant",
            "content": turn.assistant_response,
            "timestamp": turn.timestamp,
            "has_data": bool(turn.skill_executions),
            # ✅ 新增字段
            "chart_data": turn.chart_data,
            "table_data": turn.table_data,
            "data_type": turn.data_type
        })
    return history
```

#### 2.3 修改 chat endpoint 保存数据

**文件: `api/routes.py` (第138-265行，在 agent.chat() 之后)**

```python
# 在构建响应后，保存到最后一个 turn
if agent._context.turns:
    last_turn = agent._context.turns[-1]
    last_turn.chart_data = chart_data
    last_turn.table_data = table_data
    last_turn.data_type = data_type
```

完整修改位置（在第260行左右）：

```python
# 构建响应
response_data = ChatResponse(
    reply=response,
    success=True,
    data_type=data_type,
    chart_data=chart_data,
    table_data=table_data,
    file_id=file_id
)

# ✅ 新增：保存到 turn
if agent._context.turns:
    last_turn = agent._context.turns[-1]
    last_turn.chart_data = chart_data
    last_turn.table_data = table_data
    last_turn.data_type = data_type

return response_data
```

### 测试
```bash
# 1. 查询 "2020年款公交车的 NOx 排放因子"
# 2. 创建新会话
# 3. 切换回第一个会话
# 4. 检查图表是否正常显示
```

---

## 修复3: 改进 Planning Prompt（提升 Agent 智能）

### 问题
Agent 无法从文件路径推断应该使用 input_file 参数。

### 修复代码

**文件: `agent/prompts.py` (找到 PLANNING_PROMPT 定义)**

在 PLANNING_PROMPT 中添加文件处理指导：

```python
PLANNING_PROMPT = """
你是一个排放计算助手的规划器...

## 文件处理规则

当用户消息中包含"文件路径: /path/to/file"时：
1. 优先使用 input_file 参数，值为该文件路径
2. 不要要求用户手动输入数据（如 trajectory_data、links_data）
3. 对于缺失的参数（如 vehicle_type），可以：
   - 使用默认值（如 model_year=2020）
   - 让 Skill 从文件中提取
   - 或者在 clarification 中询问用户

示例：
用户："帮我计算这个车辆的排放\n文件路径: /tmp/micro_emission_example.csv"
正确的计划：
{
  "steps": [
    {
      "skill": "calculate_micro_emission",
      "params": {
        "input_file": "/tmp/micro_emission_example.csv",
        "model_year": 2020,
        "pollutants": ["CO2", "NOx"]
      },
      "clarification": "需要确认车辆类型（如：小汽车、公交车）"
    }
  ]
}

错误的计划（不要这样做）：
{
  "steps": [
    {
      "skill": "calculate_micro_emission",
      "params": {
        "vehicle_type": "小汽车",  # ❌ 不要猜测
        "trajectory_data": []      # ❌ 不要要求手动输入
      }
    }
  ]
}

...
"""
```

### 测试
```bash
# 上传文件后发送: "帮我计算这个车辆的排放"
# 预期: Agent 应该使用 input_file 参数，而不是要求 trajectory_data
```

---

## 修复4: 放宽 Validator 检查

### 问题
即使提供了 input_file，Validator 仍然要求 vehicle_type。

### 修复代码

**文件: `agent/validator.py` (第150-200行左右，validate 方法中)**

```python
def validate(self, plan: List[Dict]) -> Tuple[bool, List[str]]:
    """验证计划的正确性"""
    errors = []

    for i, step in enumerate(plan):
        skill_name = step.get("skill")
        params = step.get("params", {})

        if skill_name not in self.SKILL_SCHEMAS:
            errors.append(f"步骤{i}: 未知的Skill '{skill_name}'")
            continue

        schema = self.SKILL_SCHEMAS[skill_name]

        # ✅ 新增：如果有 input_file，放宽检查
        has_input_file = params.get("input_file") is not None

        # 检查必需参数
        for required in schema["required"]:
            # ✅ 如果有 input_file，跳过某些必需参数检查
            if has_input_file and required in ["vehicle_type", "trajectory_data", "links_data"]:
                continue

            if required not in params or params[required] is None or params[required] == "":
                errors.append(f"步骤{i}: 缺少必需参数 {required}")

        # ... 其余验证逻辑

    return len(errors) == 0, errors
```

### 测试
```bash
# 上传文件后发送: "帮我计算这个车辆的排放"
# 预期: Planning 验证应该通过，不应该报错"缺少必需参数 vehicle_type"
```

---

## 修复5: 修复 Session 持久化错误

### 问题
日志显示: `Failed to save sessions: cannot pickle '_thread.RLock' object`

### 修复代码

**文件: `agent/core.py` (在类的末尾添加)**

```python
def __getstate__(self):
    """Pickle时排除LLM客户端"""
    state = self.__dict__.copy()
    # 排除不可序列化的对象
    state['_llm'] = None
    if hasattr(self, '_lock'):
        state['_lock'] = None
    return state

def __setstate__(self, state):
    """Unpickle时重新初始化LLM客户端"""
    self.__dict__.update(state)
    # 重新初始化 LLM 客户端
    from shared.llm.client import get_llm_client
    self._llm = get_llm_client()
```

**文件: `agent/context.py` (在 ConversationContext 类中添加)**

```python
def __getstate__(self):
    """Pickle时排除锁对象"""
    state = self.__dict__.copy()
    if hasattr(self, '_lock'):
        state['_lock'] = None
    return state

def __setstate__(self, state):
    """Unpickle时重新创建锁"""
    self.__dict__.update(state)
    # 如果需要锁，重新创建
    # self._lock = threading.RLock()
```

### 测试
```bash
# 进行任何操作后，检查日志
# 预期: 不应该再看到 "Failed to save sessions" 错误
```

---

## 实施顺序

1. **修复1** (5分钟) - 立即修复文件上传
2. **修复4** (5分钟) - 放宽 Validator 检查
3. **修复3** (10分钟) - 改进 Planning Prompt
4. **修复5** (5分钟) - 修复持久化错误
5. **修复2** (20分钟) - 修复历史图表

总计: 约45分钟

---

## 验证清单

- [ ] 上传 micro_emission_example.csv 可以成功计算
- [ ] 上传 macro_emission_with_distribution.csv 可以成功计算
- [ ] 历史记录中的图表可以正常显示
- [ ] 追问其他污染物时图表正常显示
- [ ] 不再出现 "Failed to save sessions" 错误
- [ ] Agent 不再频繁要求提供已有的信息

---

## 注意事项

1. 修改前请备份原文件
2. 每次修改后重启服务器: `Ctrl+C` 然后重新运行 `python run_api.py`
3. 清除浏览器缓存或使用无痕模式测试
4. 如果遇到问题，检查日志文件: `logs/requests.log`
