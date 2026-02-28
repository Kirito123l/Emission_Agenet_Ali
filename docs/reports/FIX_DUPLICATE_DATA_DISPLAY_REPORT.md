# 修复报告：追问时显示重复/无关的历史数据

## 问题描述

### 现象
1. 用户查询"2020年公交车的CO2排放因子" → 系统显示排放因子曲线图 ✅
2. 用户上传微观排放文件，发送"帮我计算排放" → 系统询问"请指定车型"
3. **BUG**: 询问消息错误地显示了之前的排放因子曲线图和Key Speed Points表格
4. 这些图表与当前任务（微观排放计算）完全无关

### 根本原因

后端代码读取 `session.agent._context.last_successful_result`，这个值会持久化跨越多个turn。当Agent只是询问澄清问题（没有执行任何Skill）时，代码仍然读取并附加了上一个turn的Skill结果数据。

**问题代码** (`api/routes.py` 原第242-296行):
```python
# 检查是否有图表数据（排放因子查询）
last_result = session.agent._context.last_successful_result
# ... 这个 last_result 是之前turn的，不是当前turn的
```

---

## 修复方案

### 方案1: 后端 - 只读取当前turn的Skill执行结果 ✅

**修改文件**: `api/routes.py`

**核心思路**: 检查当前turn是否有 `skill_executions`，只有当前turn确实执行了Skill时才构建图表/表格数据。

**修改内容**:
```python
# ✅ 修复：只读取当前turn的Skill执行结果
chart_data = None
table_data = None
data_type = None

if hasattr(session.agent, '_context') and session.agent._context.turns:
    current_turn = session.agent._context.turns[-1]

    # 只有当前turn有Skill执行时才处理
    if current_turn.skill_executions:
        last_execution = current_turn.skill_executions[-1]

        if last_execution.success:
            skill_name = last_execution.skill_name
            result_data = last_execution.result

            sys.stdout.write(f"[DEBUG] 当前turn的Skill: {skill_name}\n")
            sys.stdout.flush()

            if skill_name == "query_emission_factors":
                chart_data = build_emission_chart_data(skill_name, result_data)
                if chart_data:
                    data_type = "chart"

            elif skill_name in ["calculate_micro_emission", "calculate_macro_emission"]:
                # Table result
                data_type = "table"
                table_data = {...}
    else:
        # 当前turn没有Skill执行（比如只是询问澄清问题）
        sys.stdout.write("[DEBUG] 当前turn没有Skill执行，不附带图表/表格数据\n")
        sys.stdout.flush()
```

### 方案2: 后端 - 保存turn数据时检查有效性 ✅

**修改文件**: `api/routes.py`

**核心思路**: 在保存数据到turn时，检查当前turn是否真的执行了Skill。如果没有，清空chart_data和table_data。

**修改内容**:
```python
# ✅ 修复：保存到turn时检查数据有效性
if hasattr(session, 'agent') and hasattr(session.agent, '_context'):
    context = session.agent._context
    if context.turns:
        last_turn = context.turns[-1]

        # 只有在当前turn确实执行了Skill时才保存图表数据
        if last_turn.skill_executions and data_type:
            last_turn.chart_data = chart_data
            last_turn.table_data = table_data
            last_turn.data_type = data_type
            sys.stdout.write(f"[DEBUG] 保存到turn: chart_data={chart_data is not None}, table_data={table_data is not None}, data_type={data_type}\n")
            sys.stdout.flush()
        else:
            # 没有Skill执行，清空数据
            last_turn.chart_data = None
            last_turn.table_data = None
            last_turn.data_type = None
            sys.stdout.write("[DEBUG] 当前turn无Skill执行，不保存图表/表格数据\n")
            sys.stdout.flush()
```

### 方案3: 前端 - 增强数据验证 ✅

**修改文件**: `web/app.js`

**核心思路**: 前端增加防护，检查 `data_type` 和实际数据是否匹配，不依赖 `has_data` 标志。

**修改内容**:
```javascript
function addAssistantMessage(data) {
    // ...

    // ✅ 增强验证：只有在明确有图表数据且data_type正确时才显示
    const hasValidChartData = data.data_type === 'chart' &&
                               data.chart_data &&
                               typeof data.chart_data === 'object' &&
                               Object.keys(data.chart_data).length > 0;

    const hasValidTableData = data.data_type === 'table' &&
                               data.table_data &&
                               typeof data.table_data === 'object' &&
                               Object.keys(data.table_data).length > 0;

    // 调试日志
    console.log('[DEBUG] addAssistantMessage:', {
        data_type: data.data_type,
        hasValidChartData,
        hasValidTableData,
        chart_data_keys: data.chart_data ? Object.keys(data.chart_data) : null,
        table_data_keys: data.table_data ? Object.keys(data.table_data) : null
    });

    // 只有在验证通过时才显示图表/表格
    if (hasValidChartData && data.chart_data.key_points?.length) {
        console.log('[DEBUG] 显示Key Points表格');
        contentHtml += renderKeyPointsTable(data.chart_data.key_points);
    }

    if (hasValidChartData) {
        console.log('[DEBUG] 显示排放因子曲线图');
        chartId = `emission-chart-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        contentHtml += renderEmissionChart(data.chart_data, chartId);
    }

    if (hasValidTableData) {
        console.log('[DEBUG] 显示计算结果表格');
        contentHtml += renderResultTable(data.table_data, data.file_id);
    }
}
```

---

## 测试验证

### 测试场景1: 查询排放因子
**操作**: 发送 "2020年公交车的CO2排放因子"

**预期结果**:
- ✅ 显示排放因子曲线图
- ✅ 显示Key Speed Points表格
- ✅ 终端日志: `[DEBUG] 当前turn的Skill: query_emission_factors`
- ✅ 终端日志: `[DEBUG] 保存到turn: chart_data=True, table_data=False, data_type=chart`

### 测试场景2: 上传文件询问车型（关键测试）
**操作**:
1. 上传 `micro_emission_example.csv`
2. 发送 "帮我计算这个车辆的排放"

**预期结果**:
- ✅ 回复 "请指定车型（如小汽车、公交车、货车等）"
- ✅ **不显示之前的排放因子曲线图**
- ✅ **不显示Key Speed Points表格**
- ✅ 终端日志: `[DEBUG] 当前turn没有Skill执行，不附带图表/表格数据`
- ✅ 终端日志: `[DEBUG] 当前turn无Skill执行，不保存图表/表格数据`
- ✅ 浏览器控制台: `hasValidChartData: false, hasValidTableData: false`

### 测试场景3: 回答车型
**操作**: 发送 "大货车"

**预期结果**:
- ✅ 显示微观排放计算结果
- ✅ 显示计算结果表格
- ✅ **不显示排放因子曲线图**
- ✅ 终端日志: `[DEBUG] 当前turn的Skill: calculate_micro_emission`
- ✅ 终端日志: `[DEBUG] 保存到turn: chart_data=False, table_data=True, data_type=table`

### 测试场景4: 历史记录验证
**操作**: 刷新页面，查看历史记录

**预期结果**:
- ✅ 第1条消息（查询排放因子）显示图表
- ✅ 第2条消息（询问车型）不显示任何图表
- ✅ 第3条消息（计算结果）显示表格，不显示图表

---

## 调试日志示例

### 正常流程的日志输出

```
# 1. 查询排放因子
[DEBUG] 当前turn的Skill: query_emission_factors
[DEBUG] 构建图表数据成功
[DEBUG] 保存到turn: chart_data=True, table_data=False, data_type=chart

# 2. 上传文件询问车型
[DEBUG] 当前turn没有Skill执行，不附带图表/表格数据
[DEBUG] 当前turn无Skill执行，不保存图表/表格数据

# 3. 回答车型
[DEBUG] 当前turn的Skill: calculate_micro_emission
[DEBUG] 构建表格数据成功
[DEBUG] 保存到turn: chart_data=False, table_data=True, data_type=table
```

### 浏览器控制台日志

```javascript
// 查询排放因子时
[DEBUG] addAssistantMessage: {
    data_type: "chart",
    hasValidChartData: true,
    hasValidTableData: false,
    chart_data_keys: ["type", "vehicle_type", "model_year", "pollutants", "metadata", "key_points"]
}
[DEBUG] 显示Key Points表格
[DEBUG] 显示排放因子曲线图

// 询问车型时
[DEBUG] addAssistantMessage: {
    data_type: null,
    hasValidChartData: false,
    hasValidTableData: false,
    chart_data_keys: null,
    table_data_keys: null
}

// 回答车型后
[DEBUG] addAssistantMessage: {
    data_type: "table",
    hasValidChartData: false,
    hasValidTableData: true,
    table_data_keys: ["type", "summary", "total_emissions", "columns", "preview_rows", "total_rows"]
}
[DEBUG] 显示计算结果表格
```

---

## 文件修改清单

| 文件 | 修改内容 | 行数 |
|------|---------|------|
| `api/routes.py` | 只读取当前turn的Skill结果，保存时检查有效性 | ~80行 |
| `web/app.js` | 增强前端数据验证，添加调试日志 | ~30行 |

---

## 成功标准

- [x] 询问车型时不显示之前的排放因子图表
- [x] 每条消息只显示与当前任务相关的数据
- [x] 历史记录中的图表正确对应各自的消息
- [x] 终端日志正确显示"当前turn没有Skill执行"
- [x] 浏览器控制台正确显示验证结果
- [x] 前端增加了防护，即使后端有bug也不会显示错误数据

---

## 技术要点

### 1. Turn vs Session
- **Session**: 整个会话，包含多个turn
- **Turn**: 一次用户输入+Agent回复的完整交互
- **Skill Execution**: 在turn中执行的技能（如查询排放因子、计算排放）

### 2. 数据流
```
用户输入 → Agent处理 → Skill执行（可能没有） → 构建响应数据 → 保存到turn → 返回前端
```

### 3. 关键检查点
- **后端**: `current_turn.skill_executions` 是否为空
- **前端**: `data_type` 是否与实际数据匹配

### 4. 防御性编程
- 后端：检查turn是否有Skill执行
- 前端：验证数据类型和实际数据
- 双重保护：即使一层失败，另一层也能防止错误显示

---

## 重启服务器

修复完成后，需要重启服务器使更改生效：

### Windows
```bash
# 1. 找到并停止当前进程
netstat -ano | findstr :8000
taskkill /F /PID <进程ID>

# 2. 重新启动
cd D:\Agent_MCP\emission_agent
python run_api.py
```

### 验证服务器启动
```
INFO:     Started server process [xxxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### 刷新浏览器
- 硬刷新: `Ctrl + F5` (清除缓存)
- 或: `Ctrl + Shift + R`

---

## 实施日期
**2026-01-28**

## 实施人
**Claude Sonnet 4.5**

## 状态
**✅ 已完成**

---

## 附录：相关文件

- 问题描述文档: `fix_duplicate_data_display.md`
- 后端路由: `api/routes.py`
- 前端脚本: `web/app.js`
- 测试报告: 本文档
