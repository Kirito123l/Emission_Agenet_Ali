# Emission Agent 系统修复任务

## 项目位置
```
D:\Agent_MCP\emission_agent
```

## 问题概述

系统存在5个需要修复的问题，按优先级排序：

| 优先级 | 问题 | 影响 |
|--------|------|------|
| P0 | 上传文件计算失败 | 核心功能不可用 |
| P1 | Session持久化错误 | 数据丢失风险 |
| P1 | 历史记录图表消失 | 用户体验差 |
| P2 | Agent智能不足 | 需要反复提供信息 |
| P3 | 多污染物图表失败 | 部分功能异常 |

---

## 修复任务（按顺序执行）

### 任务1: 修复文件上传失败 [P0 - 最高优先级]

**问题**: 用户上传文件后，Agent报错"缺少必需参数 vehicle_type"

**原因**: 
1. 文件路径格式不明确，Agent无法识别
2. Validator过于严格

**修复文件**: `api/routes.py`

找到文件上传处理代码（约第138-180行），修改消息格式：

```python
# 原代码（找到类似这样的代码）
if file:
    file_path = temp_dir / file.filename
    with open(file_path, "wb") as f:
        f.write(await file.read())
    message_with_file = f"{message}\n\n[附件: {file.filename}]"

# 修改为
if file:
    file_path = temp_dir / file.filename
    with open(file_path, "wb") as f:
        f.write(await file.read())
    # ✅ 明确传递文件路径，让Agent能识别
    message_with_file = f"{message}\n\n文件已上传，路径: {str(file_path)}\n请使用 input_file 参数处理此文件。"
```

**修复文件**: `agent/validator.py`

找到validate方法（约第150-200行），放宽对input_file的检查：

```python
def validate(self, plan: List[Dict]) -> Tuple[bool, List[str]]:
    errors = []
    
    for i, step in enumerate(plan):
        skill_name = step.get("skill")
        params = step.get("params", {})
        
        if skill_name not in self.SKILL_SCHEMAS:
            errors.append(f"步骤{i}: 未知的Skill '{skill_name}'")
            continue
        
        schema = self.SKILL_SCHEMAS[skill_name]
        
        # ✅ 新增：如果有 input_file，放宽必需参数检查
        has_input_file = "input_file" in params and params["input_file"]
        
        for required in schema.get("required", []):
            # ✅ 如果有 input_file，跳过 vehicle_type/trajectory_data/links_data 检查
            if has_input_file and required in ["vehicle_type", "trajectory_data", "links_data"]:
                continue
            
            if required not in params or params[required] is None or params[required] == "":
                errors.append(f"步骤{i}: 缺少必需参数 {required}")
        
        # ... 其余逻辑保持不变
    
    return len(errors) == 0, errors
```

---

### 任务2: 修复Session持久化错误 [P1]

**问题**: 日志显示 `Failed to save sessions: cannot pickle '_thread.RLock' object`

**修复文件**: `agent/core.py`

在EmissionAgent类末尾添加序列化方法：

```python
class EmissionAgent:
    # ... 现有代码 ...
    
    def __getstate__(self):
        """Pickle时排除不可序列化的对象"""
        state = self.__dict__.copy()
        # 排除 LLM 客户端
        if '_llm' in state:
            state['_llm'] = None
        # 排除锁对象
        if '_lock' in state:
            state['_lock'] = None
        return state
    
    def __setstate__(self, state):
        """Unpickle时重新初始化"""
        self.__dict__.update(state)
        # 重新初始化 LLM 客户端
        from llm.client import get_llm_client  # 根据实际导入路径调整
        self._llm = get_llm_client()
```

**修复文件**: `agent/context.py`

在ConversationContext类中添加：

```python
class ConversationContext:
    # ... 现有代码 ...
    
    def __getstate__(self):
        """Pickle时排除锁对象"""
        state = self.__dict__.copy()
        if '_lock' in state:
            state['_lock'] = None
        return state
    
    def __setstate__(self, state):
        """Unpickle时重新创建锁"""
        self.__dict__.update(state)
        import threading
        if hasattr(self, '_lock') or '_lock' in state:
            self._lock = threading.RLock()
```

---

### 任务3: 修复历史记录图表消失 [P1]

**问题**: 切换会话后，历史消息中的图表无法显示

**修复文件**: `agent/context.py`

在ConversationTurn数据类中添加新字段：

```python
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

@dataclass
class ConversationTurn:
    """单轮对话"""
    user_input: str
    assistant_response: str
    understanding: str = ""
    skill_executions: List[SkillExecution] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # ✅ 新增字段 - 保存图表和表格数据
    chart_data: Optional[Dict[str, Any]] = None
    table_data: Optional[Dict[str, Any]] = None
    data_type: Optional[str] = None  # 'chart', 'table', 或 None
```

**修复文件**: `agent/core.py`

找到get_history方法（约第432-450行），修改返回数据：

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
        # 助手回复 - ✅ 包含完整的图表数据
        history.append({
            "role": "assistant",
            "content": turn.assistant_response,
            "timestamp": turn.timestamp,
            "has_data": bool(turn.skill_executions),
            "chart_data": turn.chart_data,      # ✅ 新增
            "table_data": turn.table_data,      # ✅ 新增
            "data_type": turn.data_type         # ✅ 新增
        })
    return history
```

**修复文件**: `api/routes.py`

在chat端点中，构建响应后保存数据到turn。找到构建ChatResponse的位置，在return之前添加：

```python
# 构建响应
response_data = ChatResponse(
    reply=response,
    success=True,
    session_id=session.session_id,
    data_type=data_type,
    chart_data=chart_data,
    table_data=table_data,
    file_id=file_id
)

# ✅ 新增：保存图表数据到最后一个turn
if hasattr(session, 'agent') and hasattr(session.agent, '_context'):
    context = session.agent._context
    if context.turns:
        last_turn = context.turns[-1]
        last_turn.chart_data = chart_data
        last_turn.table_data = table_data
        last_turn.data_type = data_type

return response_data
```

**修复文件**: `web/app.js`

找到renderHistory函数（约第288-310行），修改为正确传递图表数据：

```javascript
function renderHistory(messages) {
    clearMessages();
    
    messages.forEach(msg => {
        if (msg.role === 'user') {
            addUserMessage(msg.content);
        } else {
            // ✅ 传递完整的图表数据
            addAssistantMessage({
                reply: msg.content,
                success: true,
                data_type: msg.data_type,      // ✅ 新增
                chart_data: msg.chart_data,    // ✅ 新增
                table_data: msg.table_data,    // ✅ 新增
                has_data: msg.has_data
            });
        }
    });
    
    scrollToBottom();
}
```

---

### 任务4: 改进Agent智能 [P2]

**问题**: Agent无法从文件路径推断应该使用input_file参数

**修复文件**: `agent/prompts.py`

找到PLANNING_PROMPT定义，在其中添加文件处理规则：

```python
PLANNING_PROMPT = """
你是一个机动车排放计算助手的规划器。

# 现有内容保持不变...

## 文件处理规则（重要！）

当用户消息中包含"文件已上传，路径:"或"文件路径:"时：

1. **必须使用 input_file 参数**
   - 值为消息中的文件路径
   - 不要使用 trajectory_data 或 links_data

2. **参数处理**
   - 如果用户没有指定 vehicle_type，使用默认值或在 clarification 中询问
   - 如果用户没有指定 pollutants，默认使用 ["CO2", "NOx"]
   - model_year 默认使用 2020

3. **正确示例**
```json
用户: "帮我计算这个车辆的排放\n文件已上传，路径: /tmp/data.csv"

正确的计划:
{
  "steps": [{
    "skill": "calculate_micro_emission",
    "params": {
      "input_file": "/tmp/data.csv",
      "vehicle_type": "小汽车",
      "model_year": 2020,
      "pollutants": ["CO2", "NOx"]
    }
  }]
}
```

4. **错误示例（不要这样做）**
```json
{
  "steps": [{
    "skill": "calculate_micro_emission",
    "params": {
      "trajectory_data": []  // ❌ 错误！有文件时不要用这个
    }
  }]
}
```

# 继续现有的prompt内容...
"""
```

---

### 任务5: 修复多污染物图表 [P3]

**问题**: 追问其他污染物时图表不显示

**修复文件**: `api/routes.py`

找到build_emission_chart_data函数，增强容错能力：

```python
def build_emission_chart_data(result: Dict) -> Optional[Dict]:
    """从Skill结果构建图表数据，支持多种格式"""
    
    # 格式1: 标准格式 (有 speed_curve)
    if "speed_curve" in result:
        return {
            "type": "emission_factors",
            "vehicle_type": result.get("vehicle_type", ""),
            "model_year": result.get("model_year", 2020),
            "pollutants": result.get("pollutants", {}),
            "speed_curve": result.get("speed_curve", [])
        }
    
    # 格式2: 多污染物格式 (只有 pollutants)
    if "pollutants" in result and isinstance(result["pollutants"], dict):
        pollutants_data = result["pollutants"]
        # 转换为标准格式
        return {
            "type": "emission_factors",
            "vehicle_type": result.get("vehicle_type", ""),
            "model_year": result.get("model_year", 2020),
            "pollutants": pollutants_data
        }
    
    # 格式3: 嵌套在 data 字段中
    if "data" in result and isinstance(result["data"], dict):
        return build_emission_chart_data(result["data"])
    
    # 格式4: 直接是曲线数据
    if "curve" in result or "emission_curve" in result:
        curve = result.get("curve") or result.get("emission_curve", [])
        return {
            "type": "emission_factors",
            "pollutants": {
                "default": {"curve": curve}
            }
        }
    
    logger.warning(f"无法识别的图表数据格式: {list(result.keys())}")
    return None
```

---

## 测试验证

完成所有修复后，按顺序测试：

### 测试1: 文件上传
```
1. 上传 micro_emission_example.csv
2. 发送: "帮我计算这个车辆的排放"
3. 预期: 应该成功计算或询问车型，而不是报错"缺少参数"
```

### 测试2: 基本查询
```
1. 发送: "2020年小汽车的CO2排放因子"
2. 预期: 显示交互式折线图
3. 鼠标悬停应该显示具体数值
```

### 测试3: 增量对话
```
1. 发送: "2020年公交车的NOx排放因子"
2. 等待图表显示
3. 发送: "CO2呢？"
4. 预期: 应该记住"公交车"和"2020年"，显示CO2图表
```

### 测试4: 历史记录
```
1. 进行上述查询
2. 点击"New Calculation"创建新会话
3. 点击左侧历史记录回到之前的会话
4. 预期: 图表应该正常显示
```

### 测试5: 持久化
```
1. 进行任意操作
2. 检查终端日志
3. 预期: 不应该看到 "Failed to save sessions" 错误
```

---

## 文件修改清单

| 文件 | 修改内容 |
|------|---------|
| `api/routes.py` | 文件路径格式、保存图表数据、build_emission_chart_data |
| `agent/validator.py` | 放宽input_file检查 |
| `agent/core.py` | 序列化方法、get_history返回完整数据 |
| `agent/context.py` | ConversationTurn添加字段、序列化方法 |
| `agent/prompts.py` | 添加文件处理规则 |
| `web/app.js` | renderHistory传递图表数据 |

---

## 注意事项

1. **修改前备份**: 每个文件修改前先备份
2. **逐步测试**: 每完成一个任务就测试一次
3. **检查导入**: 新增代码可能需要导入新的模块
4. **重启服务**: 每次修改后需要重启 `python run_api.py`
5. **清除缓存**: 前端修改后用 Ctrl+F5 强制刷新浏览器

---

## 成功标准

- [ ] 上传文件后能成功计算排放（不再报错"缺少参数"）
- [ ] 查询排放因子时显示交互式折线图
- [ ] 追问其他污染物时图表正常显示
- [ ] 切换历史会话时图表能恢复显示
- [ ] 终端不再显示持久化错误
- [ ] Agent能正确识别文件路径并使用input_file参数
