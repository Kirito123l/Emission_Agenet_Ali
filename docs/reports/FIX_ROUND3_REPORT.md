# Emission Agent 第三轮修复完成报告

## 修复时间
2026-01-27 (第三轮 - 根本原因修复)

## 诊断结果

通过第二轮添加的调试日志，成功定位了所有问题的根本原因：

### ✅ 问题1：历史记录图表消失 - 根本原因找到

**日志显示**:
```
[DEBUG] 历史消息1: role=assistant, chart_data=True, table_data=False, data_type=chart
```

**诊断结果**:
- ✅ 后端 `get_history()` 正确返回了 chart_data
- ✅ 后端保存到 turn 正确
- ❌ **根本原因**: `api/models.py` 中的 `Message` 模型缺少 `chart_data`, `table_data`, `data_type` 字段
- Pydantic 在序列化时过滤掉了这些字段，导致前端收不到数据

### ✅ 问题2：文件列名识别失败 - 根本原因找到

**日志显示**:
```
[DEBUG] 文件列名: ['time_sec', 'speed_kmh', 'acceleration_m_s2']
```

**诊断结果**:
- 文件使用 `speed_kmh`，但代码只支持 `speed_kph`
- 文件使用 `acceleration_m_s2`，但代码只支持 `acceleration_mps2`
- 文件使用 `time_sec`，但代码只支持 `t` 和 `time`
- **根本原因**: 列名变体支持不完整

### ✅ 问题3：持久化错误 - 暂时无法完全解决

**日志显示**:
```
Failed to save sessions: cannot pickle '_thread.RLock' object
```

**诊断结果**:
- 虽然添加了 `__getstate__` 和 `__setstate__`，但仍有其他不可序列化对象
- 可能来源：LLM 客户端、知识库加载器等
- **临时方案**: 此错误不影响功能，只是会话无法持久化到磁盘

---

## 修复内容

### 修复1: Message模型添加缺失字段 ⭐ 关键修复

**修改文件**: `api/models.py`

**位置**: 第41-46行

**修改内容**:
```python
class Message(BaseModel):
    """单条消息"""
    role: str  # "user" | "assistant"
    content: str
    timestamp: str
    has_data: bool = False
    # 新增字段 - 支持历史消息中的图表和表格数据
    chart_data: Optional[Dict[str, Any]] = None
    table_data: Optional[Dict[str, Any]] = None
    data_type: Optional[str] = None  # "chart" | "table" | None
```

**预期效果**:
- 历史记录 API 返回完整的图表数据
- 前端能正确渲染历史消息中的图表
- 不再显示黄色警告

---

### 修复2: 扩展Excel列名支持 ⭐ 关键修复

**修改文件**: `skills/micro_emission/excel_handler.py`

**位置**: 第13-17行

**修改内容**:
```python
# 列名映射（支持多种命名方式）
SPEED_COLUMNS = ["speed_kph", "speed_kmh", "speed", "车速", "速度"]  # 添加 speed_kmh
ACCELERATION_COLUMNS = ["acceleration", "acc", "acceleration_mps2", "acceleration_m_s2", "加速度"]  # 添加 acceleration_m_s2
GRADE_COLUMNS = ["grade_pct", "grade", "坡度"]
TIME_COLUMNS = ["t", "time", "time_sec", "时间"]  # 添加 time_sec
```

**预期效果**:
- 支持 `speed_kmh` (之前只支持 `speed_kph`)
- 支持 `acceleration_m_s2` (之前只支持 `acceleration_mps2`)
- 支持 `time_sec` (之前只支持 `t` 和 `time`)
- 文件上传后能正确识别列名

---

### 修复3: 前端添加调试日志

**修改文件**: `web/app.js`

**位置**: 第294-308行

**修改内容**:
```javascript
messages.forEach(msg => {
    if (msg.role === 'user') {
        addUserMessage(msg.content);
    } else {
        // 传递完整的图表数据
        console.log('[DEBUG] 渲染历史消息:', {
            has_chart_data: !!msg.chart_data,
            has_table_data: !!msg.table_data,
            data_type: msg.data_type
        });
        addAssistantMessage({
            reply: msg.content,
            success: true,
            data_type: msg.data_type,
            chart_data: msg.chart_data,
            table_data: msg.table_data,
            has_data: msg.has_data
        });
    }
});
```

**预期效果**:
- 浏览器控制台显示历史消息的数据状态
- 帮助快速诊断前端问题

---

### 修复4: 改进Agent文件处理提示

**修改文件**: `agent/prompts/system.py`

**位置**: 第32-65行

**修改内容**:
- 明确了缺少 vehicle_type 时的处理流程
- 添加了 needs_clarification 的正确用法示例
- 强调必须在 plan 中包含 input_file 参数

**预期效果**:
- Agent 在第一次就使用 input_file 参数
- 通过 clarification 询问缺失的 vehicle_type
- 用户回复车型后，Agent 能正确补充参数并执行

---

## 测试计划

### 测试1: 历史记录图表显示 ⭐ 关键测试

```bash
1. 查询排放因子
   发送: "2020年公交车的NOx排放因子"
   预期: 显示交互式折线图

2. 创建新会话
   点击 "New Calculation"

3. 切换回历史会话
   点击左侧历史记录

4. 验证结果
   预期:
   - ✅ 图表正常显示（不再是黄色警告）
   - ✅ 可以交互（鼠标悬停显示数值）
   - ✅ 浏览器控制台显示: has_chart_data=true, data_type='chart'
```

### 测试2: 文件上传计算 ⭐ 关键测试

```bash
1. 上传文件
   文件: micro_emission_example.csv
   消息: "帮我计算下这个车辆的排放"

2. 验证第一次响应
   预期:
   - ✅ 系统询问车型（而不是报错"未找到速度列"）
   - ✅ 终端日志显示: [DEBUG] 文件列名: ['time_sec', 'speed_kmh', 'acceleration_m_s2']
   - ✅ 终端日志显示: [DEBUG] 清理后列名: ['time_sec', 'speed_kmh', 'acceleration_m_s2']

3. 回复车型
   发送: "小轿车"

4. 验证计算结果
   预期:
   - ✅ 成功计算排放
   - ✅ 显示结果表格
   - ✅ 可以下载结果文件
```

### 测试3: 多污染物查询

```bash
1. 查询单个污染物
   发送: "2020年公交车的NOx排放因子"
   预期: 显示NOx图表

2. 追问其他污染物
   发送: "PM2.5和CO2的呢"
   预期:
   - ✅ 显示PM2.5和CO2的图表
   - ✅ 可以切换污染物标签
   - ✅ 不再显示NOx图表
```

---

## 文件修改清单

| 文件 | 行号 | 修改内容 | 优先级 |
|------|------|----------|--------|
| `api/models.py` | 41-50 | Message模型添加chart_data/table_data/data_type字段 | ⭐ P0 |
| `skills/micro_emission/excel_handler.py` | 13-17 | 扩展列名支持（speed_kmh, acceleration_m_s2, time_sec） | ⭐ P0 |
| `web/app.js` | 294-308 | 添加前端调试日志 | P2 |
| `agent/prompts/system.py` | 32-65 | 改进文件处理提示和示例 | P1 |

---

## 重启服务器

```bash
# 1. 停止当前服务器 (Ctrl+C)

# 2. 重启服务器
cd D:\Agent_MCP\emission_agent
python run_api.py

# 3. 清除浏览器缓存
# 使用 Ctrl+F5 强制刷新页面
```

---

## 预期日志输出

### 正常情况

```bash
# 1. 查询排放因子
[chart] skill: query_emission_factors, keys: [...]
[chart] chart_data ready
[DEBUG] 保存到turn: chart_data=True, table_data=False, data_type=chart

# 2. 切换历史记录
[DEBUG] 历史消息1: role=assistant, chart_data=True, table_data=False, data_type=chart

# 3. 浏览器控制台
[DEBUG] 渲染历史消息: {has_chart_data: true, has_table_data: false, data_type: 'chart'}

# 4. 上传文件
[DEBUG] 文件列名: ['time_sec', 'speed_kmh', 'acceleration_m_s2']
[DEBUG] 清理后列名: ['time_sec', 'speed_kmh', 'acceleration_m_s2']
# 不再报错 "未找到速度列"
```

---

## 成功标准

- [x] 修复1: Message模型添加缺失字段
- [x] 修复2: 扩展Excel列名支持
- [x] 修复3: 前端添加调试日志
- [x] 修复4: 改进Agent文件处理提示
- [ ] 测试1: 历史记录图表正常显示
- [ ] 测试2: 文件上传成功计算
- [ ] 测试3: 多污染物查询正确显示

---

## 与前两轮修复的对比

### 第一轮修复（盲目修复）
- 添加了数据结构字段
- 修改了数据传递逻辑
- **问题**: 没有发现 Pydantic 模型过滤数据的问题

### 第二轮修复（诊断方法）
- 添加了详细的调试日志
- **成功**: 通过日志定位了根本原因

### 第三轮修复（根本原因修复）⭐
- 修复了 Pydantic 模型缺失字段
- 扩展了列名支持
- **预期**: 彻底解决问题

---

## 备注

1. **持久化错误暂时无法完全解决**
   - 错误不影响功能
   - 会话在内存中正常工作
   - 重启服务器后会话会丢失
   - 需要深入排查所有不可序列化对象

2. **前端调试日志可以保留**
   - 帮助快速诊断问题
   - 生产环境可以移除

3. **列名支持可以继续扩展**
   - 如果用户使用其他列名变体，可以继续添加
   - 建议在文档中说明支持的列名格式

---

## 下一步

1. **重启服务器并测试**
2. **验证历史记录图表显示**
3. **验证文件上传计算**
4. **如果仍有问题，查看浏览器控制台和终端日志**

---

## 联系支持

如遇问题，请提供：
1. 终端完整日志
2. 浏览器控制台日志（F12）
3. 具体操作步骤
