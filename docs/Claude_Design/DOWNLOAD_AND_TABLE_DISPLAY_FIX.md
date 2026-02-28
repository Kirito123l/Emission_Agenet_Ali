# 下载功能和表格显示修复

## 修复日期
2026-02-02

## 问题描述

### 问题 1: 下载按钮点击后无法下载
- **现象**: 下载按钮显示正常，但点击后浏览器提示"无法下载，没有文件"
- **根本原因**: 下载 URL 路径错误
  - 生成的 URL: `/download/{filename}`
  - 实际端点: `/api/download/{filename}`
  - 路由器挂载在 `/api` 前缀下，但 URL 没有包含这个前缀

### 问题 2: 表格列太多
- **现象**: 预览表格显示所有列（可能有十几列），导致页面拥挤
- **需求**: 只显示前5列作为预览，完整数据在下载的文件中

## 修复方案

### 修复 1: 下载 URL 路径

**文件**: `api/routes.py:476`

```python
# 修复前
"url": f"/download/{download_info['filename']}"

# 修复后
"url": f"/api/download/{download_info['filename']}"
```

**说明**: 添加 `/api` 前缀，使 URL 与实际的路由端点匹配。

### 修复 2: 限制预览列数

**文件**: `api/routes.py:487-493`

```python
# 修复前
df = pd.read_excel(result_file_path)
table_data["columns"] = list(df.columns)
table_data["preview_rows"] = df.head(5).to_dict(orient="records")
table_data["total_rows"] = len(df)

# 修复后
df = pd.read_excel(result_file_path)

# Limit to first 5 columns for better readability
preview_columns = list(df.columns)[:5]
table_data["columns"] = preview_columns
table_data["preview_rows"] = df[preview_columns].head(5).to_dict(orient="records")
table_data["total_rows"] = len(df)
table_data["total_columns"] = len(df.columns)  # 显示总列数
```

**说明**:
- 只选择前5列用于预览
- 添加 `total_columns` 字段，告知前端总列数

### 修复 3: 前端显示优化

**文件**: `web/app.js:721-782`

```javascript
// 添加总列数变量
const totalColumns = tableData.total_columns || columns.length;

// 构建列信息文本
const columnInfo = totalColumns > columns.length
    ? `显示前${columns.length}列（共${totalColumns}列）`
    : `共${columns.length}列`;

// 更新显示文本
<p class="text-xs text-slate-500 dark:text-slate-400">
    显示前${rows.length}行（共${totalRows}行），${columnInfo}
</p>
```

**说明**:
- 如果总列数大于显示列数，显示"显示前5列（共X列）"
- 否则显示"共X列"

## 预期效果

### 下载功能
✅ 点击下载按钮后，浏览器正常下载 Excel 文件
✅ 文件名保持原样（如 `9ffc9213_input_emission_results_20260202_200539.xlsx`）
✅ 下载的文件包含完整数据（所有行和所有列）

### 表格预览
✅ 只显示前5列，页面更简洁
✅ 显示信息："显示前5行（共25行），显示前5列（共18列）"
✅ 用户知道完整数据在下载文件中

## 示例

### 修复前
```
计算结果
显示前5行，共25行

[表格显示18列，页面很宽，需要横向滚动]
link_id | length_km | flow_vph | speed_kph | Motorcycle | Passenger Car | ... (13列车型数据)
```

### 修复后
```
计算结果
显示前5行（共25行），显示前5列（共18列）

[表格只显示5列，页面简洁]
link_id | length_km | flow_vph | speed_kph | Motorcycle
```

## 测试步骤

1. **重启服务器**:
   ```powershell
   .\scripts\restart_server.ps1
   ```

2. **上传文件并计算**

3. **验证表格预览**:
   - ✅ 只显示前5列
   - ✅ 显示"显示前5列（共X列）"

4. **验证下载功能**:
   - ✅ 点击"下载结果文件"按钮
   - ✅ 浏览器开始下载
   - ✅ 打开下载的 Excel 文件
   - ✅ 确认包含所有列和所有行

## 文件修改清单

| 文件 | 修改内容 | 行号 |
|------|---------|------|
| `api/routes.py` | 修复下载 URL 路径（添加 /api 前缀） | 476 |
| `api/routes.py` | 限制预览列数为前5列 | 487-493 |
| `web/app.js` | 显示总列数信息 | 721-782 |

## 技术细节

### 为什么需要 /api 前缀？

在 `api/main.py:66`：
```python
app.include_router(router, prefix="/api")
```

所有路由都挂载在 `/api` 前缀下，所以：
- `/download/{filename}` → 404 Not Found
- `/api/download/{filename}` → ✅ 正确

### 为什么限制为5列？

1. **可读性**: 太多列导致表格过宽，需要横向滚动
2. **性能**: 减少前端渲染的数据量
3. **用户体验**: 预览只需要看到关键信息，完整数据在下载文件中
4. **常见做法**: 大多数数据预览工具都限制列数

### 如何选择显示哪5列？

当前实现：显示前5列（按文件中的列顺序）

**优点**:
- 简单直接
- 通常前几列是最重要的（如 link_id, length, flow, speed）

**可能的改进**（未来）:
- 智能选择：优先显示关键列（ID、长度、流量、速度、排放结果）
- 用户自定义：允许用户选择要预览的列

## 总结

✅ **下载功能已修复**: URL 路径正确，可以正常下载文件
✅ **表格显示已优化**: 只显示前5列，页面更简洁
✅ **用户体验提升**: 清晰显示预览范围，用户知道完整数据在下载文件中

两个问题都已解决，重启服务器后即可生效！
