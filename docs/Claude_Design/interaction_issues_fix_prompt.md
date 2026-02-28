# 交互问题全面修复任务

## 项目位置
```
D:\Agent_MCP\emission_agent
```

## 问题概览

发现4个问题，按优先级排序：

| 优先级 | 问题 | 严重程度 | 修复时间 |
|--------|------|----------|----------|
| P0 | AttributeError: 'SkillExecution' object has no attribute 'success' | 🔴 高 | 5分钟 |
| P1 | Session持久化失败 (cannot pickle RLock) | 🟡 中 | 30分钟 |
| P1 | Planning验证多次失败导致延迟高 | 🟡 中 | 20分钟 |
| P2 | Agent无法感知后端错误 | 🟢 低 | 15分钟 |

---

## 任务1: 修复 AttributeError [P0 - 立即修复]

### 问题描述
```
AttributeError: 'SkillExecution' object has no attribute 'success'
位置: api/routes.py:254
```

### 根本原因

`SkillExecution` 类的定义（`agent/context.py`）：
```python
@dataclass
class SkillExecution:
    skill_name: str
    params: Dict[str, Any]
    result: Dict[str, Any]  # success 在这里面！
    timestamp: str
```

**问题**: `success` 不是直接属性，而是存储在 `result` 字典中。

### 修复方案

**搜索并替换所有 `last_execution.success` 的使用**：

```python
# 错误写法
if last_execution.success:

# 正确写法
if last_execution.result.get("success"):
```

### 修复文件清单

1. **api/routes.py** - 主要位置
   
   找到所有 `last_execution.success` 或类似的用法，改为：
   ```python
   # 检查技能执行是否成功
   if last_execution.result.get("success"):
       skill_name = last_execution.skill_name
       result_data = last_execution.result
       # ... 处理逻辑
   ```

2. **检查其他可能使用的文件**：
   - `agent/core.py`
   - `agent/synthesizer.py`（如果有）

### 验证方法

```bash
# 搜索所有可能的问题代码
grep -r "\.success" --include="*.py" .
grep -r "last_execution.success" --include="*.py" .
```

---

## 任务2: 修复 Session 持久化 [P1]

### 问题描述
```
Failed to save sessions: cannot pickle '_thread.RLock' object
```

### 根本原因

- `Session` 包含 `EmissionAgent` 实例
- `EmissionAgent` 包含 LLM客户端、Learner、Monitor 等组件
- 这些组件包含线程锁 (`threading.RLock`)，无法被 pickle 序列化

### 修复方案：分离持久化架构

#### 方案设计

```
持久化数据:
├── sessions_meta.json     # 会话元数据（ID、标题、创建时间）
├── history/
│   ├── session_xxx.json   # 各会话的对话历史
│   └── session_yyy.json
└── learning/
    └── cases.json         # Agent学习数据（可选）

运行时:
├── Session对象（内存中）
│   ├── session_id
│   ├── agent: EmissionAgent（不序列化）
│   └── metadata
```

#### 实现代码

**修改文件**: `api/session.py`

```python
import json
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

class SessionManager:
    def __init__(self, storage_dir: str = "data/sessions"):
        self._sessions: Dict[str, Session] = {}
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._meta_file = self._storage_dir / "sessions_meta.json"
        self._history_dir = self._storage_dir / "history"
        self._history_dir.mkdir(exist_ok=True)
        self._load_from_disk()
    
    def _load_from_disk(self):
        """从磁盘加载会话元数据"""
        if not self._meta_file.exists():
            return
        
        try:
            with open(self._meta_file, "r", encoding="utf-8") as f:
                meta_list = json.load(f)
            
            for meta in meta_list:
                session_id = meta["session_id"]
                # 重新创建Session对象（Agent会在需要时创建）
                session = Session(
                    session_id=session_id,
                    title=meta.get("title", "新对话"),
                    created_at=meta.get("created_at"),
                    agent=None  # 延迟创建
                )
                # 加载对话历史
                history_file = self._history_dir / f"{session_id}.json"
                if history_file.exists():
                    with open(history_file, "r", encoding="utf-8") as f:
                        session._history = json.load(f)
                
                self._sessions[session_id] = session
                
            print(f"✅ 成功加载 {len(self._sessions)} 个会话")
        except Exception as e:
            print(f"⚠️ 加载会话失败: {e}")
    
    def _save_to_disk(self):
        """保存会话元数据到磁盘"""
        try:
            # 保存元数据
            meta_list = []
            for session_id, session in self._sessions.items():
                meta_list.append({
                    "session_id": session_id,
                    "title": session.title,
                    "created_at": session.created_at,
                    "updated_at": datetime.now().isoformat()
                })
            
            with open(self._meta_file, "w", encoding="utf-8") as f:
                json.dump(meta_list, f, ensure_ascii=False, indent=2)
            
            # 保存各会话的对话历史
            for session_id, session in self._sessions.items():
                if hasattr(session, '_history') and session._history:
                    history_file = self._history_dir / f"{session_id}.json"
                    with open(history_file, "w", encoding="utf-8") as f:
                        json.dump(session._history, f, ensure_ascii=False, indent=2)
            
            print(f"✅ 成功保存 {len(self._sessions)} 个会话")
        except Exception as e:
            print(f"❌ 保存会话失败: {e}")
    
    # ... 其他方法保持不变，但移除pickle相关代码
```

**修改 Session 类**：

```python
@dataclass
class Session:
    session_id: str
    title: str = "新对话"
    created_at: str = None
    agent: Optional[EmissionAgent] = None
    _history: List[Dict] = None  # 对话历史缓存
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        if self._history is None:
            self._history = []
    
    def get_or_create_agent(self) -> EmissionAgent:
        """延迟创建Agent"""
        if self.agent is None:
            self.agent = EmissionAgent()
            # 如果有历史记录，恢复到Agent的上下文中
            if self._history:
                self._restore_history_to_agent()
        return self.agent
    
    def _restore_history_to_agent(self):
        """将历史记录恢复到Agent上下文"""
        for msg in self._history:
            if msg["role"] == "user":
                # 恢复用户消息到上下文
                pass  # 具体实现取决于Agent的API
    
    def save_turn(self, user_input: str, assistant_response: str, 
                  chart_data: dict = None, table_data: dict = None):
        """保存一轮对话"""
        self._history.append({
            "role": "user",
            "content": user_input,
            "timestamp": datetime.now().isoformat()
        })
        self._history.append({
            "role": "assistant", 
            "content": assistant_response,
            "chart_data": chart_data,
            "table_data": table_data,
            "timestamp": datetime.now().isoformat()
        })
```

---

## 任务3: 优化 Planning 验证 [P1]

### 问题描述

用户查询"大货车排放"时，因缺少 `model_year` 参数，Planning 尝试了3次才成功，导致延迟高达34秒。

### 修复方案：提前追问策略

**核心思路**：检测到缺失必需参数时，直接生成追问消息，而不是尝试多次自动推断。

#### 修改文件: `agent/validator.py`

```python
class PlanValidator:
    
    # 定义每个Skill的必需参数和可推断参数
    SKILL_PARAMS = {
        "query_emission_factors": {
            "required": ["vehicle_type", "pollutant"],
            "optional_with_default": {
                "model_year": 2020,
                "season": "夏季",
                "road_type": "快速路"
            },
            "ask_if_missing": ["vehicle_type", "pollutant"]  # 这些参数缺失时追问
        },
        "calculate_micro_emission": {
            "required": ["vehicle_type"],
            "optional_with_default": {
                "model_year": 2020,
                "pollutants": ["CO2", "NOx"]
            },
            "ask_if_missing": ["vehicle_type"]
        },
        "calculate_macro_emission": {
            "required": [],  # 从文件推断
            "optional_with_default": {
                "model_year": 2020,
                "pollutants": ["CO2", "NOx"]
            },
            "ask_if_missing": []
        }
    }
    
    def validate(self, plan: dict) -> tuple[bool, list, str]:
        """
        验证Planning结果
        
        Returns:
            (is_valid, errors, clarification_message)
            - is_valid: 是否有效
            - errors: 错误列表
            - clarification_message: 需要追问用户的消息（如果有）
        """
        errors = []
        clarification_needed = []
        
        for step in plan.get("steps", []):
            skill_name = step.get("skill")
            params = step.get("params", {})
            
            if skill_name not in self.SKILL_PARAMS:
                errors.append(f"未知的Skill: {skill_name}")
                continue
            
            skill_config = self.SKILL_PARAMS[skill_name]
            
            # 检查必需参数
            for param in skill_config.get("ask_if_missing", []):
                if param not in params or not params[param]:
                    clarification_needed.append(param)
            
            # 应用默认值
            for param, default in skill_config.get("optional_with_default", {}).items():
                if param not in params or not params[param]:
                    step["params"][param] = default
        
        # 如果有需要追问的参数，生成追问消息
        if clarification_needed:
            clarification_msg = self._generate_clarification(clarification_needed)
            return False, [], clarification_msg
        
        return len(errors) == 0, errors, ""
    
    def _generate_clarification(self, missing_params: list) -> str:
        """生成追问消息"""
        param_descriptions = {
            "vehicle_type": "车辆类型（如：小汽车、公交车、大货车等）",
            "pollutant": "污染物类型（如：CO2、NOx、PM2.5等）",
            "model_year": "车辆年份（如：2020）"
        }
        
        questions = [param_descriptions.get(p, p) for p in missing_params]
        
        if len(questions) == 1:
            return f"请提供{questions[0]}，以便进行准确的排放计算。"
        else:
            return f"请提供以下信息：\n" + "\n".join(f"- {q}" for q in questions)
```

#### 修改文件: `agent/core.py`

在 Planning 阶段处理追问：

```python
def chat(self, user_input: str) -> str:
    # ... 前面的代码 ...
    
    # Planning
    plan = self._planner.plan(user_input, context)
    
    # 验证
    is_valid, errors, clarification = self._validator.validate(plan)
    
    # 如果需要追问，直接返回追问消息
    if clarification:
        # 记录这是一个追问轮次
        self._context.add_clarification_turn(user_input, clarification)
        return clarification
    
    if not is_valid:
        # 尝试反思修复（最多1次）
        plan = self._reflector.fix(plan, errors)
        is_valid, errors, clarification = self._validator.validate(plan)
        
        if clarification:
            return clarification
        
        if not is_valid:
            return f"抱歉，无法处理您的请求。错误：{errors}"
    
    # 执行
    # ... 后续代码 ...
```

---

## 任务4: 改进错误感知 [P2 - 可选]

### 问题描述

用户问"什么原因导致你报错了"，Agent无法访问后端错误日志，给出了不准确的回答。

### 修复方案

#### 在上下文中记录错误

**修改文件**: `agent/context.py`

```python
@dataclass
class ConversationContext:
    # ... 现有字段 ...
    
    # 新增：错误记录
    last_error: Optional[str] = None
    error_timestamp: Optional[str] = None
    
    def record_error(self, error: str):
        """记录后端错误"""
        self.last_error = error
        self.error_timestamp = datetime.now().isoformat()
    
    def clear_error(self):
        """清除错误记录"""
        self.last_error = None
        self.error_timestamp = None
```

#### 在路由中捕获错误

**修改文件**: `api/routes.py`

```python
@router.post("/chat")
async def chat(...):
    try:
        # ... 处理逻辑 ...
        
        # 处理成功，清除错误记录
        if hasattr(agent, '_context'):
            agent._context.clear_error()
            
    except Exception as e:
        # 记录错误到上下文
        if hasattr(agent, '_context'):
            agent._context.record_error(str(e))
        
        # 记录日志
        logger.error(f"处理请求时出错: {e}")
        
        # 返回错误响应
        raise HTTPException(status_code=500, detail=str(e))
```

#### 在 System Prompt 中添加错误感知

**修改文件**: `agent/prompts/system.py`

```python
# 在System Prompt中添加
"""
## 错误处理

如果用户询问"为什么报错"、"什么错误"等问题，你应该：
1. 检查上下文中是否有记录的错误 (last_error)
2. 如果有，解释这个错误的含义和可能的解决方案
3. 如果没有，告知用户没有检测到错误，或请用户描述具体情况
"""
```

---

## 测试验证

### 测试1: AttributeError修复
```
1. 查询 "2020年公交车的CO2排放因子"
2. 检查终端日志
3. 预期: 不应该出现 AttributeError
```

### 测试2: Session持久化
```
1. 进行几轮对话
2. 重启服务器 (Ctrl+C, python run_api.py)
3. 刷新页面
4. 预期: 历史会话应该保留
```

### 测试3: Planning优化
```
1. 查询 "大货车的排放"（不提供年份和污染物）
2. 预期: Agent应该立即追问，而不是尝试多次
3. 响应时间应该 < 15秒
```

### 测试4: 错误感知
```
1. 故意触发一个错误
2. 询问 "刚才为什么报错了"
3. 预期: Agent应该能解释错误原因
```

---

## 成功标准

- [ ] 终端不再出现 `AttributeError: 'SkillExecution' object has no attribute 'success'`
- [ ] 终端不再出现 `Failed to save sessions: cannot pickle`
- [ ] 重启服务器后会话历史保留
- [ ] 缺失参数时直接追问，不尝试多次推断
- [ ] 平均响应延迟 < 15秒
- [ ] Agent能正确解释后端错误（可选）
