# 结果文件下载按钮功能

## 需求

计算完成后，在结果表格下方显示一个**可点击的下载按钮**，让用户可以下载包含排放计算结果的Excel文件。

## 项目位置
`D:\Agent_MCP\emission_agent`

---

## 当前状态分析

从截图看，系统已经：
1. ✅ 生成了结果文件（如 `b85c6d28_input_emission_results_20260202_192225.xlsx`）
2. ✅ 在消息中显示了文件名
3. ❌ 但只是文本，不是可点击的下载链接

需要实现：
1. 后端：提供文件下载API端点
2. 前端：渲染可点击的下载按钮

---

## 实现步骤

### Step 1: 检查后端下载端点

**文件**: `api/routes.py`

确认是否已有下载端点，如果没有则添加：

```python
from fastapi import HTTPException
from fastapi.responses import FileResponse
import os

@router.get("/api/download/{filename}")
async def download_result_file(filename: str):
    """下载计算结果文件"""
    from config import OUTPUTS_DIR
    
    # 构建文件路径
    file_path = os.path.join(OUTPUTS_DIR, filename)
    
    # 安全检查：防止路径遍历攻击
    if not os.path.abspath(file_path).startswith(os.path.abspath(OUTPUTS_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # 检查文件是否存在
    if not os.path.exists(file_path):
        # 也检查 TEMP_DIR
        from config import TEMP_DIR
        file_path = os.path.join(TEMP_DIR, filename)
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="File not found")
    
    # 确定 MIME 类型
    if filename.endswith('.xlsx'):
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif filename.endswith('.xls'):
        media_type = "application/vnd.ms-excel"
    elif filename.endswith('.csv'):
        media_type = "text/csv"
    else:
        media_type = "application/octet-stream"
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=media_type
    )
```

### Step 2: 修改 Skill 返回下载信息

**文件**: `skills/micro_emission/skill.py` 和 `skills/macro_emission/skill.py`

确保在返回结果时包含下载文件信息：

```python
# 在 execute() 方法末尾，返回 SkillResult 时

# 如果生成了结果文件
if result_file_path:
    metadata["download_file"] = {
        "filename": os.path.basename(result_file_path),
        "path": result_file_path,
        "url": f"/api/download/{os.path.basename(result_file_path)}",
        "description": "包含原始数据和排放计算结果的完整文件"
    }

return SkillResult(
    success=True,
    data=result_data,
    metadata=metadata
)
```

### Step 3: 修改 API 响应传递下载信息

**文件**: `api/routes.py`

在 `chat_stream` 函数中，确保下载信息被传递到前端：

```python
# 在处理 skill 执行结果时，提取下载信息

# 查找下载文件信息
download_info = None
for step_result in execution_results:
    if step_result.get("metadata", {}).get("download_file"):
        download_info = step_result["metadata"]["download_file"]
        break

# 在发送表格数据时，附加下载信息
if table_data:
    table_response = {
        "type": "table",
        "data": table_data,
        "download": download_info  # 添加下载信息
    }
    yield f"data: {json.dumps(table_response)}\n\n"
```

### Step 4: 修改前端渲染下载按钮

**文件**: `web/app.js`

在渲染表格的函数中添加下载按钮：

```javascript
// 找到渲染表格的函数（可能是 renderResultTable 或类似名称）

function renderResultTable(tableData, downloadInfo) {
    let html = '';
    
    // 渲染表格内容
    html += '<table class="result-table">';
    // ... 表格渲染逻辑 ...
    html += '</table>';
    
    // 如果有下载信息，渲染下载按钮
    if (downloadInfo && downloadInfo.url) {
        html += `
            <div class="download-section" style="margin-top: 16px; padding: 16px; background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%); border-radius: 12px; border: 1px solid #86efac;">
                <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;">
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <div style="width: 40px; height: 40px; background: #22c55e; border-radius: 10px; display: flex; align-items: center; justify-content: center;">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2">
                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                                <polyline points="7 10 12 15 17 10"/>
                                <line x1="12" y1="15" x2="12" y2="3"/>
                            </svg>
                        </div>
                        <div>
                            <div style="font-weight: 600; color: #166534; font-size: 14px;">计算结果文件</div>
                            <div style="color: #15803d; font-size: 12px; margin-top: 2px;">${downloadInfo.filename || '结果文件'}</div>
                        </div>
                    </div>
                    <a href="${downloadInfo.url}" 
                       download="${downloadInfo.filename}"
                       class="download-btn"
                       style="display: inline-flex; align-items: center; gap: 8px; padding: 10px 20px; 
                              background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%); 
                              color: white; border-radius: 8px; 
                              text-decoration: none; font-size: 14px; font-weight: 600;
                              box-shadow: 0 2px 8px rgba(34, 197, 94, 0.3);
                              transition: all 0.2s ease;">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                            <polyline points="7 10 12 15 17 10"/>
                            <line x1="12" y1="15" x2="12" y2="3"/>
                        </svg>
                        下载 Excel
                    </a>
                </div>
                <div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid #bbf7d0; color: #15803d; font-size: 12px;">
                    💡 文件包含原始数据及所有排放计算结果，可在Excel中进一步分析
                </div>
            </div>
        `;
    }
    
    return html;
}
```

### Step 5: 添加下载按钮悬停样式

**文件**: `web/styles.css` 或在 `app.js` 中内联

```css
/* 下载按钮样式 */
.download-btn:hover {
    background: linear-gradient(135deg, #16a34a 0%, #15803d 100%) !important;
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(34, 197, 94, 0.4) !important;
}

.download-btn:active {
    transform: translateY(0);
}

.download-section {
    animation: slideUp 0.3s ease;
}

@keyframes slideUp {
    from {
        opacity: 0;
        transform: translateY(10px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}
```

---

## 数据流说明

```
Skill计算完成
    ↓
生成结果Excel文件 (generate_result_excel)
    ↓
返回 SkillResult，metadata 中包含:
{
    "download_file": {
        "filename": "xxx_emission_results_20260202.xlsx",
        "url": "/api/download/xxx_emission_results_20260202.xlsx"
    }
}
    ↓
API routes 提取 download_file 信息
    ↓
通过 SSE 发送给前端:
{
    "type": "table",
    "data": {...},
    "download": {
        "filename": "...",
        "url": "/api/download/..."
    }
}
    ↓
前端 app.js 接收到 download 信息
    ↓
renderResultTable() 渲染表格 + 下载按钮
    ↓
用户点击下载按钮
    ↓
浏览器请求 /api/download/{filename}
    ↓
后端返回文件流
    ↓
浏览器下载文件
```

---

## 测试

1. 上传一个文件并完成计算
2. 查看结果表格下方是否出现绿色的下载按钮
3. 点击下载按钮，检查是否正确下载Excel文件
4. 打开下载的Excel，确认包含原始数据和排放计算结果列

---

## 文件修改清单

| 文件 | 修改内容 |
|------|----------|
| `api/routes.py` | 添加 `/api/download/{filename}` 端点（如果没有） |
| `api/routes.py` | 在响应中传递 download_file 信息 |
| `skills/micro_emission/skill.py` | 确保返回 download_file 信息 |
| `skills/macro_emission/skill.py` | 确保返回 download_file 信息 |
| `web/app.js` | 添加下载按钮渲染逻辑 |
| `web/styles.css` | 添加下载按钮样式（可选） |

---

## 预期效果

计算完成后，表格下方显示：

```
┌────────────────────────────────────────────────────────────┐
│  [📥]  计算结果文件                                          │
│        b85c6d28_input_emission_results_20260202.xlsx        │
│                                          [ 下载 Excel ]     │
│  ─────────────────────────────────────────────────────────  │
│  💡 文件包含原始数据及所有排放计算结果，可在Excel中进一步分析   │
└────────────────────────────────────────────────────────────┘
```

绿色配色，与系统主题一致，按钮有悬停效果。
