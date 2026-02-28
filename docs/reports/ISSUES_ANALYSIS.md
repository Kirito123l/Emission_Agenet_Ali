# Emission Agent 问题分析与解决方案

## 问题总结

根据日志和代码分析，发现以下4个主要问题：

1. **历史聊天记录中折线图消失**
2. **追问其他污染物时折线图显示失败**
3. **上传表格计算失败**
4. **Agent规划能力较弱**

---

## 问题1: 历史聊天记录中折线图消失

### 根本原因

**后端问题**：`agent.get_history()` 方法只返回基础信息，不包含图表数据

```python
# agent/core.py:432-450
def get_history(self) -> List[Dict[str, Any]]:
    history = []
    for turn in self._context.turns:
        history.append({
            "role": "assistant",
            "content": turn.assistant_response,
            "timestamp": turn.timestamp,
            "has_data": bool(turn.skill_executions)  # ❌ 只有标志，没有实际数据
        })
    return history
```

**前端问题**：`renderHistory()` 无法还原图表

```javascript
// web/app.js:288-310
function renderHistory(messages) {
    messages.forEach(msg => {
        if (msg.role === 'assistant') {
            addAssistantMessage({
                reply: msg.content,
                success: true,
                has_data: msg.has_data  // ❌ 缺少 chart_data 和 table_data
            });
        }
    });
}
```

### 解决方案

**方案A：完整存储（推荐）**

修改 `ConversationTurn` 数据结构，存储完整的图表/表格数据：

```python
# agent/context.py
@dataclass
class ConversationTurn:
    user_input: str
    assistant_response: str
    understanding: str = ""
    skill_executions: List[SkillExecution] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # 新增：存储渲染数据
    chart_data: Optional[Dict] = None
    table_data: Optional[Dict] = None
    data_type: Optional[str] = None  # 'chart' or 'table'
```

修改 `agent.get_history()` 返回完整数据：

```python
# agent/core.py
def get_history(self) -> List[Dict[str, Any]]:
    history = []
    for turn in self._context.turns:
        history.append({"role": "user", "content": turn.user_input, "timestamp": turn.timestamp})
        history.append({
            "role": "assistant",
            "content": turn.assistant_response,
            "timestamp": turn.timestamp,
            "has_data": bool(turn.skill_executions),
            "chart_data": turn.chart_data,  # ✅ 新增
            "table_data": turn.table_data,  # ✅ 新增
            "data_type": turn.data_type     # ✅ 新增
        })
    return history
```

修改 `api/routes.py` 保存数据到 turn：

```python
# api/routes.py:138-265 chat endpoint
# 在构建响应后，保存到 turn
turn = agent._context.turns[-1]
turn.chart_data = chart_data
turn.table_data = table_data
turn.data_type = data_type
```

前端无需修改，`renderHistory()` 会自动渲染图表。

---

## 问题2: 追问其他污染物时折线图显示失败

### 根本原因

从日志看，第二次查询 CO2 和 PM2.5 时返回的数据格式不同：

```
[chart] skill: query_emission_factors, keys: ['vehicle_type', 'model_year', 'pollutants', 'metadata']
```

这个格式缺少 `speed_curve` 和 `query_summary`，导致前端无法渲染。

**问题定位**：`api/routes.py` 的 `build_emission_chart_data()` 函数

```python
# api/routes.py:57-99
def build_emission_chart_data(result: Dict) -> Optional[Dict]:
    # 新格式：有 speed_curve
    if "speed_curve" in result:
        # ... 处理成功

    # 旧格式：有 pollutants 字段
    elif "pollutants" in result:
        # ... 处理成功

    # ❌ 如果两者都没有，返回 None
    return None
```

**根本原因**：`emission_factors/skill.py` 在某些情况下返回的数据格式不一致。

### 解决方案

检查 `emission_factors/skill.py` 的返回格式，确保始终包含 `speed_curve`：

```python
# skills/emission_factors/skill.py
def execute(self, **params) -> SkillResult:
    # ...
    return SkillResult(
        success=True,
        data={
            "vehicle_type": vehicle_type_en,
            "model_year": model_year,
            "pollutants": {
                pollutant: {
                    "curve": curve_data,  # ✅ 必须包含
                    "unit": "g/km"
                }
                for pollutant in pollutants
            },
            "speed_curve": curve_data,  # ✅ 新格式兼容
            "query_summary": {...}      # ✅ 新格式兼容
        }
    )
```

或者增强 `build_emission_chart_data()` 的容错能力：

```python
def build_emission_chart_data(result: Dict) -> Optional[Dict]:
    # 尝试从多个位置提取数据
    if "speed_curve" in result:
        # 新格式
        pass
    elif "pollutants" in result:
        # 旧格式
        pass
    elif "data" in result and "pollutants" in result["data"]:
        # 嵌套格式
        return build_emission_chart_data(result["data"])
    else:
        logger.warning(f"无法识别的排放因子数据格式: {list(result.keys())}")
        return None
```

---

## 问题3: 上传表格计算失败

### 问题分析

从日志看：

```
Planning验证失败 (尝试3): ['步骤0: 缺少必需参数 vehicle_type']
```

**问题1：文件路径未传递给 Agent**

```python
# api/routes.py:138-180
if file:
    file_path = temp_dir / file.filename
    with open(file_path, "wb") as f:
        f.write(await file.read())

    # ❌ 文件路径没有传递给 agent
    message_with_file = f"{message}\n\n[附件: {file.filename}]"
```

**问题2：Agent 无法从消息中提取文件路径**

Agent 的 Planning 阶段无法识别 `[附件: xxx]` 这种格式，导致没有生成 `input_file` 参数。

### 解决方案

**方案A：在消息中明确文件路径**

```python
# api/routes.py
if file:
    file_path = temp_dir / file.filename
    with open(file_path, "wb") as f:
        f.write(await file.read())

    # ✅ 明确告知文件路径
    message_with_file = f"{message}\n\n文件路径: {file_path}"
    response = agent.chat(message_with_file)
```

**方案B：直接传递文件路径到 context（推荐）**

修改 Agent 接口，支持传递文件路径：

```python
# agent/core.py
def chat(self, user_input: str, file_path: Optional[str] = None) -> str:
    # 如果有文件，添加到 context
    if file_path:
        self._context.current_file_path = file_path

    # Planning 时自动注入 input_file 参数
    # ...
```

```python
# api/routes.py
response = agent.chat(message, file_path=str(file_path) if file else None)
```

**方案C：增强 Planning Prompt**

在 Planning 的 system prompt 中添加：

```
如果用户提到"上传文件"、"附件"、"表格"等，且消息中包含文件路径，
则自动添加 input_file 参数到计划中。

示例：
用户："帮我计算这个车辆的排放\n文件路径: /tmp/micro_emission_example.csv"
→ 计划应包含: {"skill": "calculate_micro_emission", "params": {"input_file": "/tmp/micro_emission_example.csv", ...}}
```

---

## 问题4: Agent 规划能力较弱

### 问题表现

1. **无法从文件中推断参数**：上传了轨迹文件，但仍然要求提供 `vehicle_type`
2. **Planning 验证失败率高**：多次尝试仍然缺少必需参数
3. **上下文记忆不足**：无法从文件内容推断车型

### 根本原因

**问题1：Planning 阶段没有文件内容**

Agent 在 Planning 时只看到用户消息，看不到文件内容，因此无法从文件中提取参数。

**问题2：Validator 过于严格**

```python
# agent/validator.py
SKILL_SCHEMAS = {
    "calculate_micro_emission": {
        "required": ["vehicle_type"],  # ❌ 即使有 input_file 也要求 vehicle_type
        ...
    }
}
```

**问题3：Skill 的 validate_params 逻辑问题**

```python
# skills/micro_emission/skill.py:99-146
def validate_params(self, params: Dict) -> Tuple[bool, Optional[str], Optional[Dict]]:
    # 检查必需参数
    for param in self.REQUIRED_PARAMS:  # ["vehicle_type"]
        if param not in params:
            missing.append(param)

    # ❌ 即使有 input_file，仍然要求 vehicle_type
```

### 解决方案

**方案A：文件预处理（推荐）**

在 Planning 之前，先读取文件并提取元信息：

```python
# api/routes.py
if file:
    file_path = temp_dir / file.filename
    with open(file_path, "wb") as f:
        f.write(await file.read())

    # ✅ 预处理文件，提取元信息
    file_meta = extract_file_metadata(file_path)
    # file_meta = {"detected_type": "trajectory", "columns": [...], "row_count": 100, ...}

    # 将元信息添加到消息中
    message_with_file = f"{message}\n\n文件信息：\n- 类型: {file_meta['detected_type']}\n- 列: {', '.join(file_meta['columns'])}\n- 行数: {file_meta['row_count']}\n- 路径: {file_path}"

    response = agent.chat(message_with_file)
```

**方案B：放宽 Validator 要求**

修改 Validator，允许 `input_file` 时不要求其他参数：

```python
# agent/validator.py
def validate(self, plan: List[Dict]) -> Tuple[bool, List[str]]:
    for step in plan:
        skill_name = step.get("skill")
        params = step.get("params", {})

        # ✅ 如果有 input_file，跳过部分必需参数检查
        if params.get("input_file"):
            continue

        # 否则检查必需参数
        for required in schema["required"]:
            if required not in params:
                errors.append(f"步骤{i}: 缺少必需参数 {required}")
```

**方案C：增强 Skill 的智能推断**

修改 Skill 的 `validate_params`，允许从文件中推断参数：

```python
# skills/micro_emission/skill.py
def validate_params(self, params: Dict) -> Tuple[bool, Optional[str], Optional[Dict]]:
    # 如果有 input_file，尝试从文件中推断参数
    if params.get("input_file"):
        try:
            file_meta = self._excel_handler.extract_metadata(params["input_file"])
            # 如果文件中有车型信息，自动填充
            if "vehicle_type" in file_meta:
                params["vehicle_type"] = file_meta["vehicle_type"]
        except Exception as e:
            logger.warning(f"无法从文件推断参数: {e}")

    # 然后再检查必需参数
    # ...
```

**方案D：改进 Planning Prompt**

在 Planning 的 system prompt 中添加更多指导：

```
当用户上传文件时：
1. 优先使用 input_file 参数，而不是要求用户手动输入数据
2. 如果文件类型明确（如"轨迹文件"、"路段文件"），可以推断 Skill 类型
3. 对于缺失的参数（如 vehicle_type），可以使用默认值或在执行时由 Skill 从文件中提取
4. 不要因为缺少次要参数而拒绝执行，让 Skill 自己处理

示例：
用户："帮我计算这个车辆的排放\n文件路径: /tmp/micro_emission_example.csv\n文件类型: 轨迹文件"
→ 计划: {"skill": "calculate_micro_emission", "params": {"input_file": "/tmp/micro_emission_example.csv"}}
   （不需要 vehicle_type，让 Skill 从文件中提取或使用默认值）
```

---

## 优先级建议

### 高优先级（立即修复）

1. **问题3 - 文件上传失败**：使用方案B（直接传递文件路径到 context）
2. **问题1 - 历史图表消失**：使用方案A（完整存储）

### 中优先级（本周修复）

3. **问题4 - Agent 规划能力**：组合使用方案A（文件预处理）+ 方案D（改进 Prompt）
4. **问题2 - 多污染物图表失败**：增强 `build_emission_chart_data()` 容错能力

### 低优先级（优化）

5. 添加更多日志，便于调试
6. 优化 Planning 缓存策略
7. 改进错误提示的用户友好性

---

## 实施步骤

### Step 1: 修复文件上传（30分钟）

1. 修改 `api/routes.py`，传递文件路径到 agent
2. 修改 `agent/core.py`，接收文件路径参数
3. 修改 Planning prompt，识别文件路径
4. 测试上传文件计算

### Step 2: 修复历史图表（45分钟）

1. 修改 `agent/context.py`，添加 chart_data/table_data 字段
2. 修改 `agent/core.py`，在 get_history() 中返回完整数据
3. 修改 `api/routes.py`，保存数据到 turn
4. 测试历史记录加载

### Step 3: 增强 Agent 规划（1小时）

1. 实现文件预处理函数 `extract_file_metadata()`
2. 修改 Planning prompt，添加文件处理指导
3. 放宽 Validator 对 input_file 的检查
4. 测试各种文件上传场景

### Step 4: 修复多污染物图表（30分钟）

1. 检查 `emission_factors/skill.py` 返回格式
2. 增强 `build_emission_chart_data()` 容错能力
3. 测试多污染物查询

---

## 测试用例

### 测试1：历史图表恢复

1. 查询 "2020年款公交车的 NOx 排放因子"
2. 切换到其他会话
3. 切换回来，检查图表是否正常显示

### 测试2：多污染物图表

1. 查询 "2020年款公交车的 NOx 排放因子"
2. 追问 "CO2 和 PM2.5 的排放呢"
3. 检查图表是否正常显示，翻页功能是否正常

### 测试3：文件上传计算

1. 上传 `micro_emission_example.csv`
2. 发送 "帮我计算这个车辆的排放"
3. 检查是否成功计算，不应要求额外参数

### 测试4：文件上传（路段数据）

1. 上传 `macro_emission_with_distribution.csv`
2. 发送 "计算这些路段的排放"
3. 检查是否成功计算并返回表格

---

## 附加建议

### 1. 改进错误提示

当前错误提示对用户不够友好：

```
"抱歉，我在理解您的查询时遇到了问题。"
```

建议改为：

```
"我注意到您上传了一个轨迹文件，但我需要知道车辆类型才能计算排放。
请告诉我：
1. 车型（如：小汽车、公交车、货车）
2. 或者，如果文件中包含车型信息，请告诉我在哪一列"
```

### 2. 添加文件内容预览

在 Planning 之前，显示文件前几行给用户确认：

```
"我看到您上传了文件 micro_emission_example.csv，包含以下列：
- t (时间)
- speed_kph (速度)
- acceleration_mps2 (加速度)

这看起来是一个轨迹文件。我将使用微观排放计算工具进行分析。
不过，我需要知道车辆类型。请问这是什么车型？"
```

### 3. 优化 Session 持久化

当前日志显示：

```
Failed to save sessions: cannot pickle '_thread.RLock' object
```

这是因为 Agent 中包含不可序列化的对象（LLM 客户端）。

解决方案：

```python
# agent/core.py
def __getstate__(self):
    state = self.__dict__.copy()
    # 排除不可序列化的对象
    state['_llm'] = None
    state['_context']._lock = None  # 如果有锁
    return state

def __setstate__(self, state):
    self.__dict__.update(state)
    # 重新初始化 LLM 客户端
    self._llm = self._init_llm()
```

---

## 总结

当前系统的主要问题是：

1. **数据持久化不完整**：历史记录缺少图表数据
2. **文件处理流程不完善**：文件路径没有正确传递给 Agent
3. **Agent 规划能力受限**：无法从文件内容推断参数
4. **数据格式不一致**：不同场景下返回的数据结构不同

建议按照上述优先级逐步修复，预计总工时约 3-4 小时。
