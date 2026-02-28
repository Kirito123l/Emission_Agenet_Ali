# Emission Agent 二次修复完成报告

## 修复时间
2026-01-27 (第二轮)

## 修复内容

### 修复1: 添加调试日志 - 历史图表保存

**修改文件**: `api/routes.py`

**位置**: 第275-285行

**修改内容**:
```python
# 保存图表数据到最后一个turn
if hasattr(session, 'agent') and hasattr(session.agent, '_context'):
    context = session.agent._context
    if context.turns:
        last_turn = context.turns[-1]
        last_turn.chart_data = response.chart_data
        last_turn.table_data = response.table_data
        last_turn.data_type = response.data_type
        # ✅ 添加调试日志
        sys.stdout.write(f"[DEBUG] 保存到turn: chart_data={response.chart_data is not None}, table_data={response.table_data is not None}, data_type={response.data_type}\n")
        sys.stdout.flush()
```

**预期效果**: 在终端看到保存图表数据的日志

---

### 修复2: 添加调试日志 - 历史记录加载

**修改文件**: `api/routes.py`

**位置**: 第458-470行

**修改内容**:
```python
logger.info(f"✅ 会话找到，获取历史消息...")
messages = session.agent.get_history()
logger.info(f"📝 历史消息数量: {len(messages)}")

# ✅ 添加调试日志
import sys
for i, msg in enumerate(messages):
    if msg.get('role') == 'assistant':
        has_chart = msg.get('chart_data') is not None
        has_table = msg.get('table_data') is not None
        sys.stdout.write(f"[DEBUG] 历史消息{i}: role=assistant, chart_data={has_chart}, table_data={has_table}, data_type={msg.get('data_type')}\n")
        sys.stdout.flush()

logger.info(f"{'='*60}\n")
```

**预期效果**: 在终端看到历史消息中是否包含图表数据

---

### 修复3: 添加调试日志 - 文件列名识别

**修改文件**: `skills/micro_emission/excel_handler.py`

**位置**: 第36-50行

**修改内容**:
```python
# 2. 读取文件
if path.suffix.lower() == '.csv':
    df = pd.read_csv(file_path)
elif path.suffix.lower() in ['.xlsx', '.xls']:
    df = pd.read_excel(file_path)
else:
    return False, None, f"不支持的文件格式: {path.suffix}，仅支持 .xlsx, .xls, .csv"

if df.empty:
    return False, None, "Excel文件为空"

# ✅ 添加调试日志
import sys
sys.stdout.write(f"[DEBUG] 文件列名: {list(df.columns)}\n")
sys.stdout.write(f"[DEBUG] 列名repr: {[repr(c) for c in df.columns]}\n")
sys.stdout.flush()

# ✅ 清理列名：去除前后空格
df.columns = df.columns.str.strip()
sys.stdout.write(f"[DEBUG] 清理后列名: {list(df.columns)}\n")
sys.stdout.flush()

# 3. 查找速度列（必需）
speed_col = ExcelHandler._find_column(df, ExcelHandler.SPEED_COLUMNS)
if speed_col is None:
    return False, None, f"未找到速度列，支持的列名: {', '.join(ExcelHandler.SPEED_COLUMNS)}"
```

**预期效果**:
1. 在终端看到CSV文件的实际列名
2. 清理列名中的空格
3. 能正确识别速度列

---

## 下一步测试

### 测试1: 验证调试日志

重启服务器后，执行以下操作：

```bash
# 1. 查询排放因子
发送: "2020年公交车的NOx排放因子"

# 预期终端日志:
[DEBUG] 保存到turn: chart_data=True, table_data=False, data_type=chart

# 2. 切换到历史记录
点击左侧历史记录

# 预期终端日志:
[DEBUG] 历史消息1: role=assistant, chart_data=True, table_data=False, data_type=chart

# 3. 上传文件
上传 micro_emission_example.csv

# 预期终端日志:
[DEBUG] 文件列名: ['t', 'speed_kph', 'acceleration_mps2']
[DEBUG] 列名repr: ['t', 'speed_kph', 'acceleration_mps2']
[DEBUG] 清理后列名: ['t', 'speed_kph', 'acceleration_mps2']
```

---

### 测试2: 根据日志诊断问题

**场景A: 如果历史记录日志显示 chart_data=False**

说明数据没有正确保存到 turn，需要检查：
1. response.chart_data 是否为 None
2. build_emission_chart_data 是否返回了数据
3. 保存时机是否正确

**场景B: 如果历史记录日志显示 chart_data=True，但前端仍不显示**

说明数据已保存，但前端没有正确渲染，需要检查：
1. 前端 renderHistory 函数是否正确传递数据
2. addAssistantMessage 函数是否正确处理 chart_data
3. 浏览器控制台是否有错误

**场景C: 如果文件列名日志显示列名正确，但仍报错**

说明 _find_column 方法有问题，需要检查：
1. 列名匹配逻辑
2. 大小写转换是否正确

---

## 已知问题

### 问题1: 持久化错误仍存在

```
Failed to save sessions: cannot pickle '_thread.RLock' object
```

**原因**: 虽然添加了 `__getstate__` 和 `__setstate__` 方法，但可能还有其他不可序列化的对象。

**临时解决方案**: 这个错误不影响功能，只是会话无法持久化到磁盘。重启服务器后会话会丢失。

**永久解决方案**: 需要找到所有包含锁对象的地方并排除。可能的位置：
- Agent 中的某个组件
- LLM 客户端
- 知识库加载器

---

### 问题2: 多污染物查询可能返回错误数据

从日志看，用户追问"CO2和PM2.5呢"，但系统返回的是NOx图表。

**可能原因**:
1. 数据库中没有CO2和PM2.5的数据
2. Skill 没有正确查询多个污染物
3. Agent Planning 没有正确理解要查询多个污染物

**需要进一步诊断**: 查看 Skill 的执行日志，确认是否查询了正确的污染物。

---

## 文件修改清单

| 文件 | 行号 | 修改内容 |
|------|------|----------|
| `api/routes.py` | 275-285 | 添加保存图表数据的调试日志 |
| `api/routes.py` | 458-470 | 添加历史记录加载的调试日志 |
| `skills/micro_emission/excel_handler.py` | 36-50 | 添加文件列名的调试日志，清理列名空格 |

---

## 重启服务器

```bash
# 停止当前服务器 (Ctrl+C)
cd D:\Agent_MCP\emission_agent
python run_api.py
```

---

## 预期日志输出

### 正常情况下的日志

```
# 查询排放因子
[chart] skill: query_emission_factors, keys: ['query_summary', 'speed_curve', ...]
[chart] chart_data ready
[DEBUG] 保存到turn: chart_data=True, table_data=False, data_type=chart

# 加载历史记录
[DEBUG] 历史消息1: role=assistant, chart_data=True, table_data=False, data_type=chart
[DEBUG] 历史消息3: role=assistant, chart_data=True, table_data=False, data_type=chart

# 上传文件
[DEBUG] 文件列名: ['t', 'speed_kph', 'acceleration_mps2']
[DEBUG] 清理后列名: ['t', 'speed_kph', 'acceleration_mps2']
```

### 异常情况下的日志

```
# 如果图表数据没有保存
[DEBUG] 保存到turn: chart_data=False, table_data=False, data_type=None

# 如果历史记录没有图表数据
[DEBUG] 历史消息1: role=assistant, chart_data=False, table_data=False, data_type=None

# 如果文件列名有问题
[DEBUG] 文件列名: [' t ', ' speed_kph ', ' acceleration_mps2 ']  # 注意空格
[DEBUG] 清理后列名: ['t', 'speed_kph', 'acceleration_mps2']
```

---

## 下一步行动

1. **重启服务器**
2. **执行测试1** - 查询排放因子并切换历史记录
3. **检查终端日志** - 确认 chart_data 是否正确保存和加载
4. **执行测试2** - 上传文件并检查列名识别
5. **根据日志结果** - 进行针对性修复

---

## 备注

- 所有修改都是添加调试日志，不影响现有功能
- 调试日志会帮助我们快速定位问题
- 如果日志显示数据正确，但前端不显示，需要检查前端代码
- 如果日志显示数据不正确，需要检查后端逻辑
