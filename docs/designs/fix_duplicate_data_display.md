# 修复：追问时显示重复/无关的历史数据

## 问题描述

### 现象
1. 用户上传微观排放文件，系统询问"请指定车型"
2. 但这条询问消息**错误地显示了之前的排放因子曲线图**（CO2/PM2.5/PM10的Transit Bus数据）
3. 这个图表与当前任务（微观排放计算）完全无关

### 截图分析
- 用户消息: "帮我计算下这个车辆的排放" + 上传文件
- 助手回复: "请指定车辆类型（如小汽车、公交车、货车等）"
- **问题**: 这条回复下面显示了 "Key Speed Points" 表格和排放因子曲线图
- 这些图表是**之前查询公交车排放因子的结果**，不应该出现在这里

### 问题根因

**可能原因1**: 后端 `_last_skill_result` 没有清理

```python
# api/routes.py
# 当Agent只返回文本回复（询问车型）时，_last_skill_result 仍然保留着上一次的值
last_result = getattr(agent, '_last_skill_result', None)
# 这个 last_result 是之前查询排放因子的结果，不是当前任务的
```

**可能原因2**: 前端错误地使用了 `has_data` 标志

```javascript
// web/app.js
// 可能在判断是否显示图表时，使用了错误的条件
if (data.has_data) {
    // 但 chart_data 实际上是空的或来自之前的缓存
}
```

**可能原因3**: Session 的 turn 数据混乱

```python
# 当前turn保存了之前的chart_data
# 因为在Agent回复之前就读取了_last_skill_result
```

---

## 修复方案

### 方案1: 后端 - 在每次请求开始时清理 `_last_skill_result`

**修改文件**: `api/routes.py`

```python
@router.post("/chat")
async def chat(...):
    # ... 获取session ...
    
    agent = session.agent
    
    # ✅ 关键修复：在调用Agent之前，清理上一次的Skill结果
    if hasattr(agent, '_last_skill_result'):
        agent._last_skill_result = None
    if hasattr(agent, '_context'):
        # 清理上下文中可能缓存的结果
        if hasattr(agent._context, '_last_skill_result'):
            agent._context._last_skill_result = None
    
    # 调用Agent
    response = agent.chat(message_with_file if file else message)
    
    # 获取Skill执行结果（现在只会是当前请求的结果）
    last_result = getattr(agent, '_last_skill_result', None)
    
    # ... 后续处理 ...
```

### 方案2: 后端 - 只在当前turn有Skill执行时才构建图表数据

**修改文件**: `api/routes.py`

```python
@router.post("/chat")
async def chat(...):
    # ... 前面的代码 ...
    
    # 调用Agent
    response = agent.chat(message_with_file if file else message)
    
    # ✅ 关键修复：检查当前turn是否有Skill执行
    chart_data = None
    table_data = None
    data_type = None
    
    if hasattr(agent, '_context') and agent._context.turns:
        current_turn = agent._context.turns[-1]
        
        # 只有当前turn有Skill执行时才处理
        if current_turn.skill_executions:
            last_execution = current_turn.skill_executions[-1]
            
            if last_execution.success:
                skill_name = last_execution.skill_name
                result_data = last_execution.result
                
                print(f"[DEBUG] 当前turn的Skill: {skill_name}")
                
                if skill_name == "query_emission_factors":
                    chart_data = build_emission_chart_data(result_data)
                    if chart_data:
                        data_type = "chart"
                
                elif skill_name in ["calculate_micro_emission", "calculate_macro_emission"]:
                    table_data = build_table_data(result_data)
                    if table_data:
                        data_type = "table"
        else:
            # 当前turn没有Skill执行（比如只是询问澄清问题）
            print(f"[DEBUG] 当前turn没有Skill执行，不附带图表/表格数据")
    
    # ... 构建响应 ...
```

### 方案3: 前端 - 检查数据是否与当前消息相关

**修改文件**: `web/app.js`

```javascript
function addAssistantMessage(data) {
    let contentHtml = '';
    
    // 文本内容
    if (data.reply) {
        contentHtml += `<div class="prose max-w-none">${formatMarkdown(data.reply)}</div>`;
    }
    
    // ✅ 关键修复：只有在明确有图表数据且data_type正确时才显示
    const hasValidChartData = data.data_type === 'chart' && 
                               data.chart_data && 
                               typeof data.chart_data === 'object' &&
                               Object.keys(data.chart_data).length > 0;
    
    const hasValidTableData = data.data_type === 'table' && 
                               data.table_data && 
                               typeof data.table_data === 'object';
    
    // 不要依赖 has_data 标志，直接检查实际数据
    if (hasValidChartData) {
        console.log('[DEBUG] 显示图表数据:', data.chart_data);
        contentHtml += renderKeyPointsTable(data.chart_data.key_points);
        contentHtml += renderEmissionChart(data.chart_data);
    }
    
    if (hasValidTableData) {
        console.log('[DEBUG] 显示表格数据:', data.table_data);
        contentHtml += renderResultTable(data.table_data, data.file_id);
    }
    
    // ... 后续代码 ...
}
```

### 方案4: 后端 - 保存到turn时检查数据有效性

**修改文件**: `api/routes.py`

```python
# 保存到turn - 只有在有有效数据时才保存
if hasattr(session.agent, '_context') and session.agent._context.turns:
    last_turn = session.agent._context.turns[-1]
    
    # ✅ 只有在当前turn确实执行了Skill时才保存图表数据
    if last_turn.skill_executions and data_type:
        last_turn.chart_data = chart_data
        last_turn.table_data = table_data
        last_turn.data_type = data_type
        print(f"[DEBUG] 保存到turn: chart_data={chart_data is not None}, table_data={table_data is not None}")
    else:
        # 没有Skill执行，清空数据
        last_turn.chart_data = None
        last_turn.table_data = None
        last_turn.data_type = None
        print(f"[DEBUG] 当前turn无Skill执行，不保存图表/表格数据")
```

---

## 推荐实施顺序

1. **先实施方案2** - 从根本上解决问题（只读取当前turn的数据）
2. **再实施方案3** - 前端增加防护（即使后端有bug也不会显示错误数据）
3. **最后实施方案4** - 确保turn数据的正确性

---

## 测试验证

### 测试场景

1. **先查询排放因子**
   - 发送: "2020年公交车的CO2排放因子"
   - 预期: 显示排放因子曲线图 ✅

2. **然后上传微观排放文件**
   - 上传: micro_emission_example.csv
   - 发送: "帮我计算这个车辆的排放"
   - 预期: 
     - 回复"请指定车型"
     - **不显示之前的排放因子曲线图** ✅
     - **不显示Key Speed Points表格** ✅

3. **回答车型**
   - 发送: "大货车"
   - 预期:
     - 显示微观排放计算结果
     - 显示计算结果表格 ✅
     - **不显示排放因子曲线图** ✅

### 验证日志

修复后，终端日志应该显示：

```
# 查询排放因子时
[DEBUG] 当前turn的Skill: query_emission_factors
[DEBUG] 保存到turn: chart_data=True, table_data=False

# 上传文件询问车型时
[DEBUG] 当前turn没有Skill执行，不附带图表/表格数据
[DEBUG] 当前turn无Skill执行，不保存图表/表格数据

# 回答车型后
[DEBUG] 当前turn的Skill: calculate_micro_emission
[DEBUG] 保存到turn: chart_data=False, table_data=True
```

---

## 成功标准

- [ ] 询问车型时不显示之前的排放因子图表
- [ ] 每条消息只显示与当前任务相关的数据
- [ ] 历史记录中的图表正确对应各自的消息
- [ ] 日志正确显示"当前turn没有Skill执行"
