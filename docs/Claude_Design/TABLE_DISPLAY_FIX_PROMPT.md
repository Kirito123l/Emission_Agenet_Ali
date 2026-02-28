# 修复任务：优化表格显示样式

## 当前问题

表格显示了所有100行数据，应该像原架构那样：
- 只显示 **汇总信息表格**（总排放量、总距离等）
- 显示 **前5-10行预览**
- 提供 **下载按钮** 查看完整数据

## 参考：原架构的正确显示样式

```
查询参数：
• 污染物：CO2、NOx
• 车型年份：2020
• 季节：夏季
• 输入文件：xxx_input.csv（包含35个路段的宏观交通数据）

计算结果：
┌────────────┬─────────────────┐
│ 指标       │ 数值 (kg/h)     │
├────────────┼─────────────────┤
│ 总CO2排放  │ 120,044,757.73  │
│ 总NOx排放  │ 47,906.80       │
└────────────┴─────────────────┘

本次计算基于日流量转换为小时流量...

计算结果（预览前5行）
┌────┬────────┬────────┬────────┬──────────┬─────────┐
│ CT │ LIGHT  │ HEAVY  │ BUSES  │ CO2_KG_H │ NOX_KG_H│
├────┼────────┼────────┼────────┼──────────┼─────────┤
│5.2 │ 12.5   │ 2.4    │ 6895   │ 3457.76  │ ...     │
│... │ ...    │ ...    │ ...    │ ...      │ ...     │
└────┴────────┴────────┴────────┴──────────┴─────────┘

[下载结果文件]
```

## 修复方案

### 方案1：修改前端渲染逻辑（推荐）

**文件**: `web/app.js`

找到 `renderResultTable` 函数，修改为只显示预览行：

```javascript
function renderResultTable(tableData, fileId) {
    const columns = tableData.columns || [];
    const allRows = tableData.preview_rows || tableData.rows || [];
    const totalRows = tableData.total_rows || allRows.length;
    const totalColumns = tableData.total_columns || columns.length;
    const summary = tableData.summary || {};
    
    // 限制预览行数（最多显示10行）
    const MAX_PREVIEW_ROWS = 10;
    const previewRows = allRows.slice(0, MAX_PREVIEW_ROWS);
    const hasMoreRows = totalRows > MAX_PREVIEW_ROWS;
    
    // 1. 先渲染汇总表格（如果有）
    let summaryHtml = '';
    if (summary.total_emissions_g || summary.total_emissions || tableData.total_emissions) {
        const emissions = summary.total_emissions_g || summary.total_emissions || tableData.total_emissions;
        summaryHtml = `
            <div class="mb-4">
                <h4 class="text-sm font-medium text-gray-700 mb-2">计算结果汇总</h4>
                <table class="min-w-full divide-y divide-gray-200 border rounded-lg overflow-hidden">
                    <thead class="bg-gray-50">
                        <tr>
                            <th class="px-4 py-2 text-left text-xs font-medium text-gray-500">指标</th>
                            <th class="px-4 py-2 text-left text-xs font-medium text-gray-500">数值</th>
                        </tr>
                    </thead>
                    <tbody class="bg-white divide-y divide-gray-200">
                        ${summary.total_distance_km ? `<tr><td class="px-4 py-2">总行驶距离</td><td class="px-4 py-2">${summary.total_distance_km.toFixed(3)} km</td></tr>` : ''}
                        ${summary.total_time_s ? `<tr><td class="px-4 py-2">总运行时间</td><td class="px-4 py-2">${summary.total_time_s} s</td></tr>` : ''}
                        ${Object.entries(emissions).map(([key, value]) => `
                            <tr>
                                <td class="px-4 py-2">${key}总排放量</td>
                                <td class="px-4 py-2">${typeof value === 'number' ? value.toFixed(2) : value} g</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
    }
    
    // 2. 渲染详细数据预览（只显示前10行）
    const headerHtml = columns.map(col => 
        `<th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">${col}</th>`
    ).join('');
    
    const rowsHtml = previewRows.map(row => {
        const cells = columns.map(col => {
            const value = row[col] !== undefined ? row[col] : '';
            return `<td class="px-3 py-2 text-sm text-gray-700 whitespace-nowrap">${value}</td>`;
        }).join('');
        return `<tr class="hover:bg-gray-50">${cells}</tr>`;
    }).join('');
    
    // 3. 下载按钮
    const downloadHtml = fileId ? `
        <button onclick="downloadFile('${fileId}')" 
                class="inline-flex items-center px-4 py-2 bg-green-500 hover:bg-green-600 text-white text-sm font-medium rounded-lg transition-colors">
            <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path>
            </svg>
            下载结果文件
        </button>
    ` : '';
    
    // 4. 组合完整HTML
    return `
        <div class="mt-4 space-y-4">
            ${summaryHtml}
            
            <div>
                <div class="flex justify-between items-center mb-2">
                    <h4 class="text-sm font-medium text-gray-700">
                        计算结果
                        <span class="text-gray-400 font-normal">
                            显示前${previewRows.length}行（共${totalRows}行），共${totalColumns}列
                        </span>
                    </h4>
                    ${downloadHtml}
                </div>
                
                <div class="overflow-x-auto border rounded-lg">
                    <table class="min-w-full divide-y divide-gray-200">
                        <thead class="bg-gray-50">
                            <tr>${headerHtml}</tr>
                        </thead>
                        <tbody class="bg-white divide-y divide-gray-200">
                            ${rowsHtml}
                        </tbody>
                    </table>
                </div>
                
                ${hasMoreRows ? `
                    <p class="text-xs text-gray-500 mt-2 text-center">
                        还有 ${totalRows - MAX_PREVIEW_ROWS} 行数据，请下载完整文件查看
                    </p>
                ` : ''}
            </div>
        </div>
    `;
}
```

### 方案2：同时修改后端返回数据

**文件**: `core/router.py`

在 `_extract_table_data` 方法中，限制返回的预览行数：

```python
def _extract_table_data(self, tool_results: list) -> Optional[Dict]:
    """从工具结果提取表格数据，格式与前端 renderResultTable 兼容"""
    
    MAX_PREVIEW_ROWS = 10  # 只返回前10行作为预览
    
    for r in tool_results:
        # ... 前面的代码保持不变 ...
        
        if r["name"] in ["calculate_micro_emission", "calculate_macro_emission"]:
            data = r["result"].get("data", {})
            results = data.get("results", [])
            summary = data.get("summary", {})
            
            if not results:
                # 如果没有详细结果，返回汇总表格
                # ... 保持不变 ...
                continue
            
            # 从第一条结果提取列名
            first_result = results[0]
            
            # 微观排放
            if r["name"] == "calculate_micro_emission":
                columns = ["t", "speed_kph"]
                if "acceleration_mps2" in first_result:
                    columns.append("acceleration_mps2")
                if "vsp" in first_result or "VSP" in first_result:
                    columns.append("VSP")
                emissions = first_result.get("emissions", {})
                columns.extend(list(emissions.keys()))
                
                # 只取前10行作为预览
                preview_rows = []
                for row in results[:MAX_PREVIEW_ROWS]:  # 改为 MAX_PREVIEW_ROWS
                    row_data = {
                        "t": row.get("t", row.get("time", "")),
                        "speed_kph": f"{row.get('speed_kph', row.get('speed', 0)):.1f}"
                    }
                    if "acceleration_mps2" in row:
                        row_data["acceleration_mps2"] = f"{row['acceleration_mps2']:.2f}"
                    if "vsp" in row:
                        row_data["VSP"] = f"{row['vsp']:.2f}"
                    elif "VSP" in row:
                        row_data["VSP"] = f"{row['VSP']:.2f}"
                    for pol, val in row.get("emissions", {}).items():
                        row_data[pol] = f"{val:.4f}"
                    preview_rows.append(row_data)
            
            # 宏观排放
            else:
                # ... 类似修改 ...
                preview_rows = []
                for row in results[:MAX_PREVIEW_ROWS]:
                    # ...
            
            return {
                "type": r["name"],
                "columns": columns,
                "preview_rows": preview_rows,  # 只有前10行
                "total_rows": len(results),    # 总行数
                "total_columns": len(columns),
                "summary": summary,
                "total_emissions": summary.get("total_emissions_g", {}) or summary.get("total_emissions", {})
            }
    
    return None
```

## 修复步骤

1. **首先修改 `core/router.py`**：
   - 找到 `_extract_table_data` 方法
   - 添加 `MAX_PREVIEW_ROWS = 10` 常量
   - 修改循环，只取前10行

2. **然后修改 `web/app.js`**：
   - 找到 `renderResultTable` 函数
   - 按照上面的方案1修改
   - 添加汇总表格渲染
   - 添加"还有 X 行数据"提示

3. **重启服务器测试**

## 预期效果

修复后的显示效果：

```
查询参数：
• 车型：小轿车 → Passenger Car
• 污染物：CO2、NOx
• 车辆年份：2020
• 季节：夏季
• 轨迹点数：100

计算结果汇总：
┌─────────────┬──────────────┐
│ 指标        │ 数值         │
├─────────────┼──────────────┤
│ 总行驶距离  │ 1.111 km     │
│ 总运行时间  │ 100 s        │
│ CO2总排放量 │ 502,598.85 g │
│ NOx总排放量 │ 1.92 g       │
└─────────────┴──────────────┘

计算结果 显示前10行（共100行），共5列  [下载结果文件]
┌───┬───────────┬───────┬──────────┬─────────┐
│ t │ speed_kph │ VSP   │ CO2      │ NOx     │
├───┼───────────┼───────┼──────────┼─────────┤
│ 0 │ 0.0       │ 0.00  │ 2386.19  │ 0.0028  │
│ 1 │ 2.6       │ 0.41  │ 4494.56  │ 0.0086  │
│...│ ...       │ ...   │ ...      │ ...     │
└───┴───────────┴───────┴──────────┴─────────┘

还有 90 行数据，请下载完整文件查看
```

## 检查清单

- [ ] `core/router.py` 的 `_extract_table_data` 限制为前10行
- [ ] `web/app.js` 的 `renderResultTable` 添加汇总表格
- [ ] `web/app.js` 的 `renderResultTable` 限制预览行数
- [ ] `web/app.js` 添加"还有 X 行数据"提示
- [ ] 下载按钮正常工作
- [ ] 汇总信息正确显示

开始执行修复！
