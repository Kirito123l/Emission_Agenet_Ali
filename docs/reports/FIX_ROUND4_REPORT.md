# Emission Agent 第四轮修复完成报告

## 修复时间
2026-01-28 (第四轮 - 用户反馈修复)

## 用户反馈

### ✅ 已解决的问题
1. **历史记录图表显示** - 第三轮修复成功，图表能正常显示
2. **微观排放文件上传** - 第三轮修复成功，列名识别正常

### ❌ 新发现的问题
1. **多污染物图表失败** - 用户询问"PM2.5和CO2呢"，文本回答成功但画图失败
2. **宏观排放文件处理失败** - 用户上传的文件列名不被识别

---

## 问题诊断

### 问题1：多污染物图表失败

**根本原因**:
- Calculator 在 `return_curve=False` 时返回 `speed_curve` 字段
- Calculator 在 `return_curve=True` 时返回 `curve` 字段
- 前端 `initEmissionChart` 函数只识别 `curve` 字段
- 多污染物查询默认 `return_curve=False`，导致返回 `speed_curve`
- `build_emission_chart_data` 没有将 `speed_curve` 转换为 `curve`

**数据流**:
```
Skill (return_curve=False)
  → 返回 {"speed_curve": [...], "unit": "g/mile"}
  → build_emission_chart_data (格式2)
  → 直接传递 pollutants_data
  → 前端期望 {"curve": [...]}
  → ❌ 找不到 curve 字段，图表初始化失败
```

### 问题2：宏观排放文件列名不匹配

**用户文件列名**:
```
link_id, link_length_km, link_volume_veh_per_hour, link_avg_speed_kmh, temperature_F, humidity_percent
```

**代码支持的列名**:
```python
FLOW_COLUMNS = ["traffic_flow_vph", "flow_vph", "flow", "traffic", "交通流量", "流量"]
SPEED_COLUMNS = ["avg_speed_kph", "speed_kph", "speed", "平均速度", "速度"]
```

**不匹配的列**:
- `link_volume_veh_per_hour` ❌ 不在 FLOW_COLUMNS 中
- `link_avg_speed_kmh` ❌ 不在 SPEED_COLUMNS 中（kmh vs kph）

---

## 修复内容

### 修复1: 扩展宏观排放列名支持 ⭐

**修改文件**: `skills/macro_emission/excel_handler.py`

**位置**: 第13-23行

**修改内容**:
```python
# 列名映射（支持多种命名方式）
LENGTH_COLUMNS = ["link_length_km", "length_km", "length", "路段长度", "长度"]
FLOW_COLUMNS = [
    "traffic_flow_vph", "flow_vph", "flow", "traffic",
    "link_volume_veh_per_hour", "volume_veh_per_hour", "volume",  # 添加 volume 变体
    "交通流量", "流量"
]
SPEED_COLUMNS = [
    "avg_speed_kph", "speed_kph", "speed",
    "link_avg_speed_kmh", "avg_speed_kmh", "speed_kmh",  # 添加 kmh 变体
    "平均速度", "速度"
]
LINK_ID_COLUMNS = ["link_id", "id", "路段ID", "路段编号"]
```

**新增支持**:
- `link_volume_veh_per_hour` - 完整的流量列名
- `volume_veh_per_hour` - 简化版本
- `volume` - 最简版本
- `link_avg_speed_kmh` - 带 link 前缀的速度列名
- `avg_speed_kmh` - kmh 变体
- `speed_kmh` - 最简 kmh 变体

---

### 修复2: 添加宏观排放调试日志

**修改文件**: `skills/macro_emission/excel_handler.py`

**位置**: 第74-86行

**修改内容**:
```python
if df.empty:
    return False, None, "Excel文件为空"

# 添加调试日志
import sys
sys.stdout.write(f"[DEBUG] 宏观文件列名: {list(df.columns)}\n")
sys.stdout.write(f"[DEBUG] 列名repr: {[repr(c) for c in df.columns]}\n")
sys.stdout.flush()

# 清理列名：去除前后空格
df.columns = df.columns.str.strip()
sys.stdout.write(f"[DEBUG] 清理后列名: {list(df.columns)}\n")
sys.stdout.flush()

# 3. 查找必需列
```

**预期效果**:
- 显示文件的实际列名
- 显示清理后的列名
- 帮助诊断列名匹配问题

---

### 修复3: 统一多污染物图表数据格式 ⭐ 关键修复

**修改文件**: `api/routes.py`

**位置**: 第88-122行

**修改内容**:
```python
# 格式2: 多污染物格式 (只有 pollutants)
if skill_name == "query_emission_factors" and "pollutants" in data:
    pollutants_data = data.get("pollutants", {})
    if isinstance(pollutants_data, dict):
        # 标准化每个污染物的数据格式：将 speed_curve 转换为 curve
        normalized_pollutants = {}
        for pollutant, poll_data in pollutants_data.items():
            if isinstance(poll_data, dict):
                # 如果有 speed_curve 但没有 curve，进行转换
                if "speed_curve" in poll_data and "curve" not in poll_data:
                    # 转换 speed_curve 为 curve 格式（g/mile -> g/km）
                    speed_curve = poll_data.get("speed_curve", [])
                    curve = []
                    for point in speed_curve:
                        curve.append({
                            "speed_kph": point.get("speed_kph", 0),
                            "emission_rate": round(point.get("emission_rate", 0) / 1.60934, 4)  # g/mile -> g/km
                        })
                    normalized_pollutants[pollutant] = {
                        "curve": curve,
                        "unit": "g/km"
                    }
                else:
                    # 已经是正确格式，直接使用
                    normalized_pollutants[pollutant] = poll_data

        return {
            "type": "emission_factors",
            "vehicle_type": data.get("vehicle_type", "Unknown"),
            "model_year": data.get("model_year", 2020),
            "pollutants": normalized_pollutants,
            "metadata": data.get("metadata", {}),
            "key_points": extract_key_points(normalized_pollutants)
        }
```

**关键改进**:
1. 检测 `speed_curve` 字段并转换为 `curve`
2. 同时进行单位转换：g/mile → g/km（除以 1.60934）
3. 统一数据格式，确保前端能正确渲染

---

## 测试计划

### 测试1: 多污染物图表 ⭐ 关键测试

```bash
1. 查询单个污染物
   发送: "2020年公交车的NOx排放因子"
   预期: ✅ 显示NOx图表

2. 追问其他污染物
   发送: "PM2.5和CO2呢"
   预期:
   - ✅ 文本回答正确
   - ✅ 显示PM2.5和CO2的图表
   - ✅ 可以切换污染物标签
   - ✅ 图表数据正确（单位为 g/km）

3. 验证浏览器控制台
   预期:
   - ✅ 无错误信息
   - ✅ 显示 "Chart init: {pollutants: {...}}"
   - ✅ 显示 "📈 PM2.5 曲线数据点数: X"
```

### 测试2: 宏观排放文件上传 ⭐ 关键测试

```bash
1. 准备测试文件
   文件名: macro_emission_example.csv
   列名: link_id, link_length_km, link_volume_veh_per_hour, link_avg_speed_kmh

2. 上传文件
   消息: "计算下这个路段"

3. 验证终端日志
   预期:
   - ✅ [DEBUG] 宏观文件列名: ['link_id', 'link_length_km', 'link_volume_veh_per_hour', 'link_avg_speed_kmh']
   - ✅ [DEBUG] 清理后列名: ['link_id', 'link_length_km', 'link_volume_veh_per_hour', 'link_avg_speed_kmh']
   - ✅ 不再报错 "未找到交通流量列"

4. 验证计算结果
   预期:
   - ✅ 成功计算排放
   - ✅ 显示结果表格
   - ✅ 可以下载结果文件
```

### 测试3: 微观排放（回归测试）

```bash
1. 上传文件
   文件: micro_emission_example.csv
   消息: "帮我计算这个车辆排放"

2. 回复车型
   发送: "小轿车"

3. 验证结果
   预期:
   - ✅ 成功计算（第三轮修复已解决）
   - ✅ 显示结果表格
```

---

## 文件修改清单

| 文件 | 行号 | 修改内容 | 优先级 |
|------|------|----------|--------|
| `skills/macro_emission/excel_handler.py` | 13-23 | 扩展列名支持（volume, kmh变体） | ⭐ P0 |
| `skills/macro_emission/excel_handler.py` | 74-86 | 添加调试日志和列名清理 | P1 |
| `api/routes.py` | 88-122 | 统一多污染物图表数据格式（speed_curve→curve） | ⭐ P0 |

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
# 1. 多污染物查询
[chart] skill: query_emission_factors, keys: ['vehicle_type', 'model_year', 'pollutants', 'metadata']
[chart] chart_data ready
[DEBUG] 保存到turn: chart_data=True, table_data=False, data_type=chart

# 2. 浏览器控制台
Chart init: {type: 'emission_factors', pollutants: {PM2.5: {curve: [...], unit: 'g/km'}, CO2: {...}}}
📈 PM2.5 曲线数据点数: 26
✅ 图表初始化完成

# 3. 宏观排放文件上传
[DEBUG] 宏观文件列名: ['link_id', 'link_length_km', 'link_volume_veh_per_hour', 'link_avg_speed_kmh']
[DEBUG] 清理后列名: ['link_id', 'link_length_km', 'link_volume_veh_per_hour', 'link_avg_speed_kmh']
# 不再报错 "未找到交通流量列"
```

---

## 成功标准

- [x] 修复1: 扩展宏观排放列名支持
- [x] 修复2: 添加宏观排放调试日志
- [x] 修复3: 统一多污染物图表数据格式
- [ ] 测试1: 多污染物图表正常显示
- [ ] 测试2: 宏观排放文件成功处理
- [ ] 测试3: 微观排放回归测试通过

---

## 技术细节

### 数据格式统一

**问题**:
- Skill 返回两种格式：`speed_curve`（默认）和 `curve`（return_curve=True）
- 前端只识别 `curve` 格式

**解决方案**:
- 在 `build_emission_chart_data` 中统一转换
- 将 `speed_curve` 转换为 `curve`
- 同时进行单位转换：g/mile → g/km

**转换公式**:
```python
emission_rate_g_per_km = emission_rate_g_per_mile / 1.60934
```

### 列名匹配策略

**原则**:
1. 支持多种命名变体（kph/kmh, flow/volume）
2. 支持带前缀的列名（link_xxx）
3. 大小写不敏感匹配
4. 清理列名中的空格

**实现**:
```python
# 1. 清理列名
df.columns = df.columns.str.strip()

# 2. 大小写不敏感匹配
df_columns_lower = {col.lower(): col for col in df.columns}
for name in possible_names:
    name_lower = name.lower()
    if name_lower in df_columns_lower:
        return df_columns_lower[name_lower]
```

---

## 与前三轮修复的对比

### 第一轮修复（盲目修复）
- 添加了数据结构字段
- 修改了数据传递逻辑
- **问题**: 没有发现 Pydantic 模型过滤数据

### 第二轮修复（诊断方法）
- 添加了详细的调试日志
- **成功**: 通过日志定位了根本原因

### 第三轮修复（根本原因修复）
- 修复了 Pydantic 模型缺失字段
- 扩展了微观排放列名支持
- **成功**: 解决了历史记录图表和微观排放问题

### 第四轮修复（用户反馈修复）⭐
- 统一了多污染物图表数据格式
- 扩展了宏观排放列名支持
- **预期**: 彻底解决所有已知问题

---

## 备注

1. **数据格式统一很重要**
   - 前后端需要约定统一的数据格式
   - 建议在文档中明确定义数据格式规范

2. **列名支持应该更灵活**
   - 当前方案：硬编码列名列表
   - 用户建议：使用 LLM 智能识别列名
   - 折中方案：扩展列名列表 + 添加调试日志

3. **单位转换需要注意**
   - g/mile → g/km: 除以 1.60934
   - mph → kph: 乘以 1.60934

---

## 下一步

1. **重启服务器并测试**
2. **验证多污染物图表显示**
3. **验证宏观排放文件处理**
4. **如果仍有问题，查看浏览器控制台和终端日志**

---

## 联系支持

如遇问题，请提供：
1. 终端完整日志
2. 浏览器控制台日志（F12）
3. 具体操作步骤
4. 上传的文件内容（前几行）
