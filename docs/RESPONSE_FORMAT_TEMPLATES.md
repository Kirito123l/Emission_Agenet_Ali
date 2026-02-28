# 排放计算助手回答格式模板总结

> 本文档总结了系统中每种问题类型的标准回答格式模板

---

## 一、微观排放计算

### 成功格式模板

```markdown
## 微观排放计算结果

**计算参数**
- 车型: {vehicle_type}
- 年份: {model_year}
- 季节: {season}
- 污染物: {pollutants}
- 轨迹点数: {num_points}

**汇总结果**
- 总距离: {total_distance} km
- 总时间: {total_time} s
- 总排放量:
  - CO2: {value} g
  - NOx: {value} g
  - PM2.5: {value} g

**单位排放**
- CO2: {value} g/km
- NOx: {value} g/km
- PM2.5: {value} g/km

**计算结果详情**
显示前4行（共{total_rows}行），共{num_columns}列

t	speed_kph	VSP	CO2	NOx	PM2.5
0	0.0	0.00	0.6628	0.0000	0.0000
1	2.6	0.60	1.2485	0.0000	0.0000
2	5.2	1.20	1.2485	0.0000	0.0000
3	7.8	1.80	1.2485	0.0000	0.0000
还有 {remaining} 行数据，请下载完整文件查看
```

### 失败格式模板

```markdown
## 工具执行结果

⚠️ 1 个工具执行失败，0 个成功

1. calculate_micro_emission
状态: ❌ 失败
错误: {error_message}

建议：{suggestions}
```

---

## 二、宏观排放计算

### 成功格式模板

```markdown
## 宏观排放计算结果

**计算参数**
- 路段数: {num_links}
- 年份: {model_year}
- 季节: {season}
- 污染物: {pollutants}

**汇总结果**
- 总排放量 (kg/h):
  - CO2: {value}
  - NOx: {value}

**计算结果详情**
显示前4行（共{total_rows}行），共{num_columns}列

link_id	CO2_kg_h	CO2_g_veh_km	NOx_kg_h
G1-K010	4375.22	59.30	1.88
G1-K020	2735.11	53.48	0.87
G1-K030	1016.30	46.39	0.37
G1-K040	1309.07	67.29	0.51
还有 {remaining} 行数据，请下载完整文件查看
```

### 失败格式模板

```markdown
## 工具执行结果

⚠️ 1 个工具执行失败，0 个成功

1. calculate_macro_emission
状态: ❌ 失败
错误: {error_message}

建议：{suggestions}
```

---

## 三、排放因子查询

### 成功格式模板

```markdown
Found {pollutant} emission factors for {vehicle_type} ({model_year}) with {num_points} speed points. Season: {season}, Road type: {road_type}.

**排放因子曲线**
{vehicle_type} · {model_year}年

{pollutant}
鼠标移到曲线上查看具体数值
```

### 多污染物格式模板

```markdown
排放因子曲线
{vehicle_type} · {model_year}年

包含以下污染物：
- CO2
- NOx
- PM2.5

**关键点数据**
速度 (km/h)	CO2 (g/km)	NOx (g/km)	PM2.5 (g/km)
10.5		120.5		1.2		0.05
20.0		98.3		0.8		0.03
...
```

---

## 四、知识检索

### 成功格式模板

```markdown
{overview}（1-2句话概述核心答案）

### 第一个主题

**小标题1**
- 要点一 [来源1]
- 要点二 [来源2]

**小标题2**
- 要点三 [来源3]

### 第二个主题

内容描述... [来源1]

⚠️ 重要提示或注意事项

**参考文档**：
1. {source1}
2. {source2}
3. {source3}
```

### 未找到结果格式模板

```markdown
未找到相关知识，请尝试其他问法。
```

---

## 五、文件分析

### 成功格式模板

```markdown
已收到文件 {filename}，共{row_count}行，包含以下列：{columns}。

根据列名 {column_names}，该文件属于{file_type}。

✅ 已识别为{task_type}数据
⚠️ 缺失关键参数：
- {parameter1}: 描述
- {parameter2}: 描述

请告诉我：
👉 {clarification_question}
```

---

## 六、参数澄清

### 格式模板

```markdown
⚠️ 缺少必需参数: {parameter_names}

**{parameter_name}**
- 描述: {description}
- 示例: {example1}, {example2}, {example3}

请提供以上信息后继续计算。
```

---

## 七、工具执行失败（通用）

### 格式模板

```markdown
## 工具执行结果

⚠️ {error_count} 个工具执行失败，{success_count} 个成功

1. {tool_name}
状态: ❌ 失败
错误: {error_message}

建议：{suggestions}
```

---

## 回答格式规范

### 通用原则

1. **使用 Markdown 格式**
   - 章节标题用 `###`（不要用"一、二、三"）
   - 小标题用 `**加粗**`
   - 列表项用 `-`

2. **数值格式化**
   - 保留4位小数（排放量）
   - 保留1位小数（速度）
   - 保留2位小数（百分比）

3. **单位规范**
   - 距离: km
   - 时间: s 或 h
   - 排放量: g, kg, 或 t（根据大小自动选择）
   - 速度: km/h 或 mph

4. **图标使用**
   - ✅ 成功
   - ❌ 失败
   - ⚠️ 警告
   - 👉 提示用户输入

### 回答结构

1. **标题**: 用 `##` 标识主要内容
2. **参数区**: 用 `**加粗**` 标识参数名
3. **结果区**: 分层级展示汇总结果和详细数据
4. **提示区**: 用 `👉` 或 `⚠️` 引导用户下一步操作

---

## 代码实现位置

| 格式类型 | 实现位置 |
|---------|---------|
| 微观排放成功 | `core/router.py:_render_single_tool_success()` (第411-442行) |
| 宏观排放成功 | `core/router.py:_render_single_tool_success()` (第444-466行) |
| 知识检索格式 | `skills/knowledge/skill.py:_refine_answer()` (第133-185行) |
| 工具失败格式 | `core/router.py:_format_results_as_fallback()` (第709-763行) |
| 排放因子表格 | `core/router.py:_extract_table_data()` (第827-1030行) |
| 排放因子图表 | `core/router.py:_extract_chart_data()` (第765-825行) |

---

## 更新日期

2026-02-18
