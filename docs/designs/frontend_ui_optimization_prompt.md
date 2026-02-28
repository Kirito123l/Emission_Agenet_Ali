# 前端UI全面优化任务

## 项目位置
```
D:\Agent_MCP\emission_agent
```

## 问题汇总

### 问题1: 文件上传UI不美观
**现象**: 
- 文件预览区域太复杂，显示了很多技术信息
- 文件类型识别不准确（宏观文件显示为"轨迹文件"）
- 有时显示"未知类型"和"预览加载失败"

**参考**: ChatGPT的文件上传非常简洁
- 只显示: [文件图标] 文件名.csv [删除按钮]
- 不显示文件内容预览
- 不显示文件类型分类

### 问题2: 输入框有多余的透明滚动条
**现象**: 输入框区域有一个不必要的分隔线或透明滚动条

### 问题3: Markdown没有正确渲染
**现象**:
- `### 标题` 显示为纯文本而不是大标题
- `**粗体**` 显示为 `**粗体**` 而不是 **粗体**
- 表格显示为纯文本而不是格式化表格

### 问题4: 计算结果表格显示问题
**现象**:
- "计算结果"卡片显示"显示前5行，共0行"
- 实际数据没有显示在表格中
- "汇总"按钮没有内容

---

## 修复任务

### 任务1: 简化文件上传UI（参考ChatGPT）

**修改文件**: `web/app.js` 和 `web/index.html`

**目标效果**:
```
┌─────────────────────────────────────────────────────────┐
│ [📄] macro_emission_example.csv              [×]        │
└─────────────────────────────────────────────────────────┘
│ 请输入您的问题...                                    [↑] │
└─────────────────────────────────────────────────────────┘
```

**修改方案**:

```javascript
// web/app.js - 简化文件预览

function showFilePreview(file) {
    const previewArea = document.getElementById('file-preview-area');
    if (!previewArea) return;
    
    // 简洁的文件显示（参考ChatGPT）
    previewArea.innerHTML = `
        <div class="flex items-center gap-3 px-4 py-2 bg-slate-50 rounded-lg border border-slate-200">
            <div class="w-10 h-10 bg-emerald-100 rounded-lg flex items-center justify-center">
                <svg class="w-5 h-5 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" 
                          d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
                </svg>
            </div>
            <div class="flex-1 min-w-0">
                <p class="text-sm font-medium text-slate-700 truncate">${file.name}</p>
                <p class="text-xs text-slate-500">${formatFileSize(file.size)}</p>
            </div>
            <button onclick="removeFile()" class="p-1.5 hover:bg-slate-200 rounded-full transition-colors">
                <svg class="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                </svg>
            </button>
        </div>
    `;
    previewArea.classList.remove('hidden');
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function removeFile() {
    currentFile = null;
    const previewArea = document.getElementById('file-preview-area');
    if (previewArea) {
        previewArea.innerHTML = '';
        previewArea.classList.add('hidden');
    }
    // 清空file input
    const fileInput = document.getElementById('file-input');
    if (fileInput) fileInput.value = '';
}
```

**HTML结构调整**:
```html
<!-- 输入区域 -->
<div id="input-area" class="border-t border-slate-200 bg-white p-4">
    <!-- 文件预览区域（简洁版） -->
    <div id="file-preview-area" class="hidden mb-3"></div>
    
    <!-- 输入框 -->
    <div class="flex items-end gap-3 max-w-4xl mx-auto">
        <div class="flex-1 relative">
            <textarea 
                id="message-input"
                placeholder="Ask about emission factors or upload more data..."
                class="w-full px-4 py-3 pr-12 border border-slate-200 rounded-2xl resize-none 
                       focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500
                       text-slate-700 placeholder-slate-400"
                rows="1"
            ></textarea>
            <!-- 附件按钮 -->
            <button id="attach-btn" class="absolute left-3 bottom-3 p-1.5 hover:bg-slate-100 rounded-full">
                <svg class="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" 
                          d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"/>
                </svg>
            </button>
        </div>
        <!-- 发送按钮 -->
        <button id="send-btn" class="p-3 bg-emerald-500 hover:bg-emerald-600 text-white rounded-full transition-colors">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 10l7-7m0 0l7 7m-7-7v18"/>
            </svg>
        </button>
    </div>
</div>
```

---

### 任务2: 移除输入框的多余滚动条/分隔线

**修改文件**: `web/index.html` 或 `web/app.js`

检查并移除：
- `overflow-y-auto` 或 `overflow-y-scroll` 样式
- 多余的 `border` 或 `divider`
- 不必要的滚动容器

```css
/* 确保输入区域没有滚动条 */
#input-area {
    overflow: visible;
}

/* textarea 自动调整高度，不需要滚动 */
#message-input {
    overflow-y: hidden;
    min-height: 44px;
    max-height: 200px;
}
```

```javascript
// 自动调整textarea高度
const textarea = document.getElementById('message-input');
textarea.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 200) + 'px';
});
```

---

### 任务3: 修复Markdown渲染

**修改文件**: `web/app.js`

**方案**: 使用marked.js库进行Markdown渲染

```html
<!-- 在index.html的head中添加 -->
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
```

```javascript
// web/app.js - 改进Markdown渲染

function formatMarkdown(text) {
    if (!text) return '';
    
    // 使用marked.js渲染Markdown
    if (typeof marked !== 'undefined') {
        // 配置marked
        marked.setOptions({
            breaks: true,      // 支持换行
            gfm: true,         // 支持GitHub风格Markdown
            tables: true,      // 支持表格
            sanitize: false,   // 不过滤HTML（已经是安全的）
        });
        
        return marked.parse(text);
    }
    
    // 回退：简单的Markdown处理
    return text
        // 标题
        .replace(/^### (.*$)/gm, '<h3 class="text-lg font-semibold text-slate-800 mt-4 mb-2">$1</h3>')
        .replace(/^## (.*$)/gm, '<h2 class="text-xl font-semibold text-slate-800 mt-4 mb-2">$1</h2>')
        .replace(/^# (.*$)/gm, '<h1 class="text-2xl font-bold text-slate-800 mt-4 mb-2">$1</h1>')
        // 粗体
        .replace(/\*\*(.*?)\*\*/g, '<strong class="font-semibold text-slate-800">$1</strong>')
        // 斜体
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        // 代码
        .replace(/`(.*?)`/g, '<code class="px-1.5 py-0.5 bg-slate-100 rounded text-sm font-mono text-slate-700">$1</code>')
        // 列表
        .replace(/^- (.*$)/gm, '<li class="ml-4">$1</li>')
        // 换行
        .replace(/\n/g, '<br>');
}

// 表格渲染（如果marked不可用）
function renderMarkdownTable(text) {
    // 检测表格模式
    const tableRegex = /\|(.+)\|[\r\n]+\|[-:| ]+\|[\r\n]+((?:\|.+\|[\r\n]*)+)/g;
    
    return text.replace(tableRegex, (match, header, body) => {
        const headers = header.split('|').filter(h => h.trim());
        const rows = body.trim().split('\n').map(row => 
            row.split('|').filter(cell => cell.trim())
        );
        
        let html = '<div class="overflow-x-auto my-4"><table class="min-w-full border border-slate-200 rounded-lg overflow-hidden">';
        
        // 表头
        html += '<thead class="bg-slate-50"><tr>';
        headers.forEach(h => {
            html += `<th class="px-4 py-2 text-left text-sm font-semibold text-slate-700 border-b border-slate-200">${h.trim()}</th>`;
        });
        html += '</tr></thead>';
        
        // 表体
        html += '<tbody class="divide-y divide-slate-100">';
        rows.forEach(row => {
            html += '<tr class="hover:bg-slate-50">';
            row.forEach(cell => {
                html += `<td class="px-4 py-2 text-sm text-slate-600">${cell.trim()}</td>`;
            });
            html += '</tr>';
        });
        html += '</tbody></table></div>';
        
        return html;
    });
}

// 在addAssistantMessage中使用
function addAssistantMessage(data) {
    let content = data.reply || '';
    
    // 先处理表格，再处理其他Markdown
    content = renderMarkdownTable(content);
    content = formatMarkdown(content);
    
    // ... 其余代码
}
```

**CSS样式**:
```css
/* Markdown样式 */
.prose h1 { @apply text-2xl font-bold text-slate-800 mt-6 mb-3; }
.prose h2 { @apply text-xl font-semibold text-slate-800 mt-5 mb-2; }
.prose h3 { @apply text-lg font-semibold text-slate-800 mt-4 mb-2; }
.prose p { @apply text-slate-600 mb-3; }
.prose strong { @apply font-semibold text-slate-800; }
.prose ul { @apply list-disc list-inside mb-3; }
.prose ol { @apply list-decimal list-inside mb-3; }
.prose li { @apply text-slate-600 mb-1; }
.prose code { @apply px-1.5 py-0.5 bg-slate-100 rounded text-sm font-mono; }
.prose table { @apply min-w-full border-collapse; }
.prose th { @apply px-4 py-2 bg-slate-50 text-left font-semibold border-b; }
.prose td { @apply px-4 py-2 border-b border-slate-100; }
```

---

### 任务4: 修复计算结果表格显示

**问题根因**: 
- `table_data` 结构不正确
- 前端没有正确解析 `results` 数据

**修改文件**: `api/routes.py` 和 `web/app.js`

**后端修复** - 确保返回正确的table_data格式:

```python
# api/routes.py

def build_table_data(skill_result: Dict) -> Optional[Dict]:
    """构建表格数据"""
    
    # 检查是否有results字段
    results = skill_result.get("results", [])
    summary = skill_result.get("summary", {})
    
    if not results:
        # 尝试从其他字段提取
        if "data" in skill_result:
            results = skill_result["data"]
        elif "rows" in skill_result:
            results = skill_result["rows"]
    
    if not results:
        print(f"[DEBUG] 无法提取表格数据: {list(skill_result.keys())}")
        return None
    
    # 确保results是列表
    if isinstance(results, dict):
        results = [results]
    
    # 提取列名
    if results and isinstance(results[0], dict):
        columns = list(results[0].keys())
    else:
        columns = []
    
    return {
        "columns": columns,
        "rows": results,
        "total_rows": len(results),
        "summary": summary
    }
```

**前端修复** - 正确渲染表格:

```javascript
// web/app.js

function renderResultTable(tableData, fileId) {
    if (!tableData) return '';
    
    const { columns, rows, total_rows, summary } = tableData;
    
    if (!rows || rows.length === 0) {
        return '<div class="text-slate-500 text-sm">暂无数据</div>';
    }
    
    // 显示前5行
    const displayRows = rows.slice(0, 5);
    
    let html = `
        <div class="mt-4 bg-white rounded-xl border border-slate-200 overflow-hidden">
            <div class="px-4 py-3 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
                <div>
                    <h4 class="font-semibold text-slate-800">计算结果</h4>
                    <p class="text-xs text-slate-500">显示前${displayRows.length}行，共${total_rows}行</p>
                </div>
                ${fileId ? `
                    <a href="/api/file/download/${fileId}" 
                       class="px-3 py-1.5 bg-emerald-500 hover:bg-emerald-600 text-white text-sm rounded-lg transition-colors">
                        下载完整结果
                    </a>
                ` : ''}
            </div>
            <div class="overflow-x-auto">
                <table class="min-w-full">
                    <thead class="bg-slate-50">
                        <tr>
                            ${columns.map(col => `
                                <th class="px-4 py-2 text-left text-xs font-semibold text-slate-600 uppercase tracking-wider">
                                    ${col}
                                </th>
                            `).join('')}
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-100">
                        ${displayRows.map(row => `
                            <tr class="hover:bg-slate-50">
                                ${columns.map(col => `
                                    <td class="px-4 py-2 text-sm text-slate-600 whitespace-nowrap">
                                        ${formatCellValue(row[col])}
                                    </td>
                                `).join('')}
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
            ${summary && Object.keys(summary).length > 0 ? `
                <div class="px-4 py-3 bg-emerald-50 border-t border-slate-200">
                    <h5 class="font-medium text-emerald-800 mb-2">汇总</h5>
                    <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                        ${Object.entries(summary).map(([key, value]) => `
                            <div>
                                <p class="text-xs text-emerald-600">${key}</p>
                                <p class="text-sm font-semibold text-emerald-800">${formatCellValue(value)}</p>
                            </div>
                        `).join('')}
                    </div>
                </div>
            ` : ''}
        </div>
    `;
    
    return html;
}

function formatCellValue(value) {
    if (value === null || value === undefined) return '-';
    if (typeof value === 'number') {
        // 保留合理的小数位
        if (Number.isInteger(value)) return value.toString();
        return value.toFixed(4).replace(/\.?0+$/, '');
    }
    return String(value);
}
```

---

## 测试验证

### 测试1: 文件上传UI
1. 上传一个CSV文件
2. 预期: 显示简洁的文件卡片（图标+文件名+大小+删除按钮）
3. 点击删除按钮，文件应该被移除

### 测试2: 输入框
1. 查看输入区域
2. 预期: 没有多余的滚动条或分隔线
3. 输入多行文本，textarea应该自动扩展

### 测试3: Markdown渲染
1. 查询排放因子，等待回复
2. 预期: 
   - 标题正确显示（大字体、加粗）
   - 粗体文字正确显示
   - 表格正确渲染（有边框、对齐）

### 测试4: 计算结果表格
1. 上传文件并计算排放
2. 预期:
   - "计算结果"显示正确的行数
   - 表格数据正确显示
   - "汇总"区域显示统计信息
   - 可以下载完整结果

---

## 文件修改清单

| 文件 | 修改内容 |
|------|---------|
| `web/index.html` | 添加marked.js CDN，调整输入区域HTML结构 |
| `web/app.js` | 简化文件预览、修复Markdown渲染、修复表格显示 |
| `api/routes.py` | 修复build_table_data函数 |

---

## 成功标准

- [ ] 文件上传显示简洁的卡片（参考ChatGPT）
- [ ] 输入框没有多余的滚动条
- [ ] Markdown标题、粗体正确渲染
- [ ] Markdown表格正确渲染
- [ ] 计算结果表格显示正确的数据
- [ ] 汇总区域显示统计信息
