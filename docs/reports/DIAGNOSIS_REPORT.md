# Emission Agent 问题诊断报告

## 执行摘要

通过分析代码和日志，发现了4个主要问题及其根本原因。所有问题都有明确的解决方案，预计修复时间约45分钟。

---

## 问题1: 历史聊天记录中折线图消失 ⭐⭐⭐

### 现象
用户切换会话后，再切换回来时，之前的图表无法显示，只显示文字提示。

### 根本原因
**后端**: `agent.get_history()` 只返回 `has_data` 标志，不返回实际的 `chart_data` 和 `table_data`

```python
# agent/core.py:443-449
history.append({
    "role": "assistant",
    "content": turn.assistant_response,
    "has_data": bool(turn.skill_executions)  # ❌ 只有标志
    # 缺少: chart_data, table_data, data_type
})
```

**前端**: `renderHistory()` 收到的数据不完整，无法重建图表

```javascript
// web/app.js:299-305
addAssistantMessage({
    reply: msg.content,
    success: true,
    has_data: msg.has_data  // ❌ 缺少图表数据
});
```

### 解决方案
修改3个文件，添加数据持久化：
1. `agent/context.py` - 在 ConversationTurn 中添加 chart_data/table_data 字段
2. `agent/core.py` - 在 get_history() 中返回完整数据
3. `api/routes.py` - 在 chat endpoint 中保存数据到 turn

详见 `QUICK_FIXES.md` 修复2。

---

## 问题2: 追问其他污染物时折线图显示失败 ⭐⭐

### 现象
第一次查询 NOx 正常显示图表，追问 "CO2和PM2.5的排放呢" 时图表消失。

### 日志证据
```
# 第一次查询 NOx - 成功
[chart] skill: query_emission_factors, keys: ['query_summary', 'speed_curve', 'typical_values', ...]

# 第二次查询 CO2, PM2.5 - 失败
[chart] skill: query_emission_factors, keys: ['vehicle_type', 'model_year', 'pollutants', 'metadata']
```

### 根本原因
`emission_factors/skill.py` 在不同情况下返回的数据格式不一致：
- 单个污染物: 返回 `speed_curve` + `query_summary`
- 多个污染物: 只返回 `pollutants` 字段

`api/routes.py` 的 `build_emission_chart_data()` 无法处理第二种格式。

### 解决方案
**方案A**: 统一 skill 返回格式（推荐）
```python
# skills/emission_factors/skill.py
return SkillResult(
    success=True,
    data={
        "speed_curve": {...},      # ✅ 始终包含
        "query_summary": {...},    # ✅ 始终包含
        "pollutants": {...}        # ✅ 兼容旧格式
    }
)
```

**方案B**: 增强 build_emission_chart_data() 容错能力
```python
# api/routes.py
def build_emission_chart_data(result: Dict) -> Optional[Dict]:
    # 尝试多种格式
    if "speed_curve" in result:
        pass
    elif "pollutants" in result:
        pass
    elif "data" in result:
        return build_emission_chart_data(result["data"])  # 递归
    else:
        logger.warning(f"未知格式: {list(result.keys())}")
        return None
```

### 翻页功能检查
前端的 tab 切换功能正常，代码在 `app.js:739-768`。问题不在翻页，而在数据格式。

---

## 问题3: 上传表格计算失败 ⭐⭐⭐⭐⭐ (最高优先级)

### 现象
用户上传 `micro_emission_example.csv`，发送 "帮我计算这个车辆的排放"，Agent 报错：
```
Planning验证失败 (尝试3): ['步骤0: 缺少必需参数 vehicle_type']
```

### 根本原因分析

**问题链条**:
1. 文件路径格式不明确
2. Agent Planning 无法识别文件路径
3. Validator 过于严格
4. Skill 无法从文件推断参数

**详细分析**:

#### 3.1 文件路径传递问题
```python
# api/routes.py:170-175
if file:
    file_path = temp_dir / file.filename
    with open(file_path, "wb") as f:
        f.write(await file.read())
    message_with_file = f"{message}\n\n[附件: {file.filename}]"  # ❌ 格式不明确
```

Agent 看到的消息:
```
帮我计算这个车辆的排放

[附件: micro_emission_example.csv]
```

Agent 无法从 `[附件: xxx]` 推断出应该使用 `input_file` 参数。

#### 3.2 Planning 生成错误
Agent 生成的计划:
```json
{
  "steps": [{
    "skill": "calculate_micro_emission",
    "params": {
      "trajectory_data": []  // ❌ 错误：应该用 input_file
    }
  }]
}
```

#### 3.3 Validator 拒绝执行
```python
# agent/validator.py
SKILL_SCHEMAS = {
    "calculate_micro_emission": {
        "required": ["vehicle_type"],  # ❌ 即使有 input_file 也要求
    }
}
```

### 解决方案（组合拳）

**修复1**: 明确文件路径格式
```python
message_with_file = f"{message}\n\n文件路径: {str(file_path)}"
```

**修复2**: 改进 Planning Prompt
```
当用户消息中包含"文件路径: /path/to/file"时，
使用 input_file 参数，不要使用 trajectory_data 或 links_data。
```

**修复3**: 放宽 Validator 检查
```python
if has_input_file and required in ["vehicle_type", "trajectory_data", "links_data"]:
    continue  # 跳过检查
```

详见 `QUICK_FIXES.md` 修复1、3、4。

---

## 问题4: Agent 感觉"笨笨的" ⭐⭐⭐

### 现象
- 无法从文件内容推断参数
- 重复询问已知信息
- Planning 验证失败率高

### 根本原因

#### 4.1 信息不对称
Agent 在 Planning 阶段看不到文件内容，只能看到文件名。

#### 4.2 上下文利用不足
Agent 没有充分利用之前的对话历史和文件元信息。

#### 4.3 Prompt 指导不足
Planning Prompt 缺少文件处理的明确指导。

### 解决方案

**短期方案**: 改进 Prompt + 放宽验证
- 在 Planning Prompt 中添加文件处理规则
- 放宽 Validator 对 input_file 的检查
- 允许 Skill 从文件中提取参数

**长期方案**: 文件预处理
```python
# api/routes.py
if file:
    # 1. 保存文件
    file_path = save_file(file)

    # 2. 提取元信息
    file_meta = extract_file_metadata(file_path)
    # {
    #   "type": "trajectory",
    #   "columns": ["t", "speed_kph", "acceleration_mps2"],
    #   "rows": 100,
    #   "detected_vehicle_type": "小汽车"  // 如果能推断
    # }

    # 3. 将元信息添加到消息
    message_with_file = f"{message}\n\n文件信息:\n{format_file_meta(file_meta)}\n文件路径: {file_path}"

    # 4. Agent 可以根据元信息生成更好的计划
    response = agent.chat(message_with_file)
```

---

## 其他发现

### 5. Session 持久化错误

**日志**:
```
Failed to save sessions: cannot pickle '_thread.RLock' object
```

**原因**: Agent 和 Context 中包含不可序列化的对象（LLM 客户端、锁）

**影响**: 会话无法持久化，重启服务器后会话丢失

**解决方案**: 实现 `__getstate__` 和 `__setstate__` 方法

详见 `QUICK_FIXES.md` 修复5。

---

## 修复优先级

| 优先级 | 问题 | 影响 | 修复时间 | 难度 |
|--------|------|------|----------|------|
| P0 | 问题3 - 文件上传失败 | 核心功能不可用 | 20分钟 | 简单 |
| P1 | 问题1 - 历史图表消失 | 用户体验差 | 20分钟 | 中等 |
| P1 | 问题5 - 持久化错误 | 数据丢失风险 | 5分钟 | 简单 |
| P2 | 问题4 - Agent 智能不足 | 用户体验差 | 15分钟 | 简单 |
| P3 | 问题2 - 多污染物图表 | 部分功能异常 | 15分钟 | 中等 |

**总计**: 约75分钟（包含测试）

---

## 实施建议

### 阶段1: 紧急修复（30分钟）
1. 修复文件上传（修复1、3、4）
2. 修复持久化错误（修复5）
3. 测试基本功能

### 阶段2: 体验优化（30分钟）
4. 修复历史图表（修复2）
5. 改进 Agent 智能（修复3）
6. 测试完整流程

### 阶段3: 完善优化（15分钟）
7. 修复多污染物图表（问题2）
8. 添加更多日志
9. 完整回归测试

---

## 测试清单

### 基础功能测试
- [ ] 查询排放因子（单个污染物）
- [ ] 查询排放因子（多个污染物）
- [ ] 宏观排放计算（手动输入）
- [ ] 微观排放计算（手动输入）

### 文件上传测试
- [ ] 上传轨迹文件（micro_emission_example.csv）
- [ ] 上传路段文件（macro_emission_with_distribution.csv）
- [ ] 上传后追问修改参数

### 会话管理测试
- [ ] 创建新会话
- [ ] 切换会话
- [ ] 删除会话
- [ ] 历史记录加载（包含图表）

### 多轮对话测试
- [ ] 追问其他污染物
- [ ] 修改参数（速度、年份等）
- [ ] 上下文记忆（记住车型、年份）

---

## 附录: 代码位置速查

| 功能 | 文件 | 行号 |
|------|------|------|
| 文件上传处理 | api/routes.py | 138-180 |
| 历史记录获取 | agent/core.py | 432-450 |
| 历史记录渲染 | web/app.js | 288-310 |
| Planning 验证 | agent/validator.py | 150-200 |
| Planning Prompt | agent/prompts.py | - |
| 图表数据构建 | api/routes.py | 57-99 |
| 图表初始化 | web/app.js | 625-769 |
| Session 管理 | api/session.py | - |

---

## 联系与支持

如有问题，请查看：
1. `ISSUES_ANALYSIS.md` - 详细问题分析
2. `QUICK_FIXES.md` - 快速修复指南
3. `logs/requests.log` - 运行日志

修复完成后，请运行完整测试并更新此文档。
