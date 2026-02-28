# 新旧架构数据格式对比报告

## 1. 返回数据结构对比

### 旧架构 (SkillResult)
```python
@dataclass
class SkillResult:
    success: bool
    data: Any = None           # 计算结果数据
    error: Optional[str] = None
    metadata: Dict = field(default_factory=dict)  # 元数据（含download_file等）
```

**关键字段位置：**
- `download_file`: 位于 `metadata["download_file"]`
- `query_params`: 位于 `metadata["query_params"]`
- `standardization`: 位于 `metadata["standardization"]`

### 新架构 (ToolResult)
```python
@dataclass
class ToolResult:
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    summary: Optional[str] = None    # 人类可读摘要（供LLM使用）
    chart_data: Optional[Dict] = None    # 图表数据
    table_data: Optional[Dict] = None    # 表格数据
    download_file: Optional[str] = None  # 下载文件路径
```

**关键字段位置：**
- `download_file`: 直接位于顶层（但工具实现时放在 `data["download_file"]`）
- `summary`: 新增字段，人类可读摘要
- `chart_data`, `table_data`: 新增字段，直接返回给前端

### 差异分析
- ✅ 新架构增加了 `summary` 字段，让工具提供人类可读摘要
- ✅ 新架构增加了 `chart_data` 和 `table_data` 字段，直接返回可视化数据
- ⚠️ `download_file` 位置混乱：定义在顶层，但实际使用时放在 `data["download_file"]`

---

## 2. table_data 格式对比

### 旧架构 table_data
```python
{
    "type": "calculate_macro_emission",
    "columns": ["link_id", "link_length_km", ...],
    "preview_rows": [...],       # 前10行数据
    "total_rows": 2,
    "total_columns": 8,
    "summary": {
        "total_links": 2,
        "total_emissions_kg_per_hr": {"CO2": 9138.3815}
    },
    "total_emissions": {}
}
```

### 新架构 table_data
当前实现 (`core/router.py:468-486`):
```python
# _extract_table_data 方法返回：
{
    "type": "calculate_micro_emission",
    "summary": data.get("summary", {}),        # 来自 calculator 返回
    "total_emissions": data.get("total_emissions", {})
}
```

**问题：新架构缺少关键字段！**
- ❌ 缺少 `columns`（列名）
- ❌ 缺少 `preview_rows`（预览数据）
- ❌ 缺少 `total_rows`, `total_columns`（行列统计）

### 差异分析
旧架构通过 `metadata` 传递完整表格结构，新架构只传递汇总数据。前端 `renderResultTable` 函数期望：
```javascript
const columns = tableData.columns || [];
const rows = tableData.preview_rows || tableData.rows || [];
const totalRows = tableData.total_rows || rows.length;
const totalColumns = tableData.total_columns || columns.length;
```

**新架构无法正确渲染表格！**

---

## 3. download_file 格式对比

### 旧架构 download_file
位于 `metadata["download_file"]`:
```python
{
    "path": "/path/to/file.xlsx",
    "filename": "xxx_result.xlsx",
    "description": "包含原始轨迹数据和排放计算结果的完整文件"
}
```

### 新架构 download_file
工具实现中放在 `data["download_file"]`:
```python
{
    "path": output_path,
    "filename": filename
    # 注意：缺少 description
}
```

Router 提取逻辑 (`core/router.py:488-501`):
```python
def _extract_download_file(self, tool_results: list) -> Optional[str]:
    for r in tool_results:
        if r["result"].get("download_file"):
            return r["result"]["download_file"]  # 返回整个字典
        if r["name"] in ["calculate_micro_emission", "calculate_macro_emission"]:
            data = r["result"].get("data", {})
            if data and data.get("download_file"):
                return data["download_file"]  # 返回整个字典
```

### 差异分析
- ✅ 格式基本兼容
- ⚠️ 新架构缺少 `description` 字段
- ⚠️ API 返回给前端时使用 `file_id=session_id`，前端通过 `/file/download/{file_id}` 下载

---

## 4. Synthesis 逻辑对比

### 旧架构 SYNTHESIS_PROMPT
```python
SYNTHESIS_PROMPT = """你是机动车排放计算助手。

## 对话上下文
{context}

## 当前问题
{query}

## 理解
{understanding}

## 执行结果
{results}     # 已经过滤，只包含样本数据

## 错误信息
{error_info}

## 回答要求
1. **基于结果回答**: 只使用执行结果中的数据，不要编造
2. **引用历史**: 如果用户提到"刚才"、"之前"，从上下文中引用
3. **参数说明**: 说明使用了哪些参数
4. **格式清晰**: 使用表格展示汇总数据
5. **不要编造排放因子**: 不要显示编造的数据
6. **错误解释**: 解释错误原因和解决方案
7. **不要重复展示详细数据**: results_sample仅供参考，不要列出详细数据
"""
```

**关键特性：**
- 使用 `_filter_results_for_synthesis()` 过滤详细数据
- 保留汇总信息和样本数据（前5条）
- 明确禁止编造数据
- 包含上下文和错误信息

### 新架构 SYNTHESIS_PROMPT
```python
SYNTHESIS_PROMPT = """你是一个排放计算助手。

你刚刚执行了一些工具来获取数据。现在请根据工具执行的结果，用自然、友好的语言向用户解释：

1. **计算完成了什么**：简要说明执行了哪些操作
2. **主要结果是什么**：清晰地展示关键数据和发现
3. **如果有错误**：解释错误原因，并给出具体的解决建议

**重要**：
- 直接回复用户，不要调用任何工具
- 不要说"我将调用工具"或"让我执行..."
- 只需解释已经获得的结果
- 如果结果显示错误，帮助用户理解问题并提供解决方案
"""
```

**关键特性：**
- ⚠️ **没有提供原始工具结果数据**！只传递 summary
- ⚠️ **没有数据过滤机制**
- ⚠️ **过于宽松**，缺少"不要编造"的明确约束

### Synthesis 数据传递对比

**旧架构：**
```python
# 过滤结果，只传递样本数据
filtered_results = self._filter_results_for_synthesis(results)
prompt = SYNTHESIS_PROMPT.format(
    results=json.dumps(filtered_results, ensure_ascii=False, indent=2),
    ...
)
```

**新架构：**
```python
# 只传递 summary，不传递完整结果
def _format_tool_results(self, tool_results: list) -> str:
    summaries = []
    for r in tool_results:
        if r["result"].get("success"):
            summary = r["result"].get("summary", "Execution successful")
            summaries.append(f"[{r['name']}] {summary}")
        else:
            error = r["result"].get("message", "Unknown error")
            summaries.append(f"[{r['name']}] Error: {error}")
    return "\n".join(summaries)  # 只传递文本摘要！
```

### 差异分析
- ❌ 新架构 Synthesis 只接收 summary，无法访问详细数据
- ❌ 新架构缺少数据过滤机制
- ❌ 新架构 Prompt 过于宽松，容易导致 LLM 幻觉
- ⚠️ 新架构有 fallback 机制（`_format_results_as_fallback`），但这不是解决方案

---

## 5. API 返回格式对比

### 旧架构 API 返回
```python
# api/routes.py ChatResponse
{
    "reply": "查询参数：\n- 车型：xxx → Passenger Car\n...",
    "session_id": "xxx",
    "success": True,
    "data_type": "table",
    "chart_data": {...},      # 完整的图表数据
    "table_data": {           # 完整的表格数据
        "type": "calculate_macro_emission",
        "columns": [...],
        "preview_rows": [...],
        "total_rows": 2,
        "total_columns": 8,
        "summary": {...}
    },
    "file_id": "session_id"
}
```

### 新架构 API 返回
```python
# api/routes.py (当前实现)
{
    "reply": "计算完成...",
    "session_id": "xxx",
    "success": True,
    "data_type": "table",
    "chart_data": {...},      # 可能存在
    "table_data": {           # 不完整！
        "type": "calculate_micro_emission",
        "summary": {...},
        "total_emissions": {}
        # 缺少 columns, preview_rows, total_rows, total_columns
    },
    "file_id": "session_id"
}
```

### 差异分析
- ❌ 新架构 `table_data` 缺少前端渲染必需的字段
- ⚠️ 需要从工具的 `data.results` 中提取表格数据

---

## 6. 前端期望的格式

### renderResultTable 期望的数据结构
```javascript
// web/app.js:718-730
function renderResultTable(tableData, fileId) {
    const columns = tableData.columns || [];
    const rows = tableData.preview_rows || tableData.rows || [];
    const totalRows = tableData.total_rows || rows.length;
    const totalColumns = tableData.total_columns || columns.length;

    // 渲染表头
    const headerHtml = columns.map(c =>
        `<th class="px-4 py-3 font-medium text-left">${c}</th>`
    ).join('');

    // 渲染数据行
    const rowsHtml = rows.map(row =>
        `<tr>...</tr>`
    ).join('');
}
```

**期望字段：**
- ✅ `columns`: 列名数组
- ✅ `preview_rows` 或 `rows`: 数据行数组
- ✅ `total_rows`: 总行数
- ✅ `total_columns`: 总列数

### download 按钮期望
```javascript
// web/app.js:737-754
let downloadBtn = '';
if (tableData.download) {
    downloadBtn = `
        <a href="${tableData.download.url}"
           download="${tableData.download.filename}"
           class="...">
           下载结果文件
        </a>`;
} else if (fileId) {
    downloadBtn = `
        <button onclick="downloadFile('${fileId}')"
                class="...">
            下载Excel
        </button>`;
}
```

**期望字段：**
- `tableData.download.url`: 下载链接
- `tableData.download.filename`: 文件名
- 或使用 `file_id` 通过 API 下载

---

## 7. 问题总结

### 7.1 新架构 table_data 不完整 ⚠️
**问题：** `_extract_table_data` 只提取 `summary` 和 `total_emissions`，缺少前端必需的字段。

**影响：** 前端无法渲染完整的计算结果表格。

### 7.2 Synthesis Prompt 过于宽松 ⚠️
**问题：** 新 Synthesis Prompt 只接收 summary，缺少详细数据，且没有明确禁止编造。

**影响：** LLM 可能编造数据，导致回答不准确。

### 7.3 缺少数据过滤机制 ⚠️
**问题：** 新架构没有像旧架构的 `_filter_results_for_synthesis()` 那样的过滤机制。

**影响：** 大量详细数据可能被发送给 LLM，浪费 token 且可能导致信息过载。

### 7.4 download_file 位置不一致 ⚠️
**问题：** `ToolResult.download_file` 定义在顶层，但工具实际放在 `data["download_file"]`。

**影响：** 提取逻辑复杂，可能导致提取失败。

---

## 8. 修复建议

### 8.1 修复 table_data 提取逻辑
**文件：** `core/router.py`

**当前代码 (468-486):**
```python
def _extract_table_data(self, tool_results: list) -> Optional[Dict]:
    for r in tool_results:
        if r["result"].get("table_data"):
            return r["result"]["table_data"]

        if r["name"] in ["calculate_micro_emission", "calculate_macro_emission"]:
            data = r["result"].get("data", {})
            if data and data.get("summary"):
                return {
                    "type": r["name"],
                    "summary": data.get("summary", {}),
                    "total_emissions": data.get("total_emissions", {})
                }
    return None
```

**修复后：**
```python
def _extract_table_data(self, tool_results: list) -> Optional[Dict]:
    for r in tool_results:
        if r["result"].get("table_data"):
            return r["result"]["table_data"]

        if r["name"] in ["calculate_micro_emission", "calculate_macro_emission"]:
            data = r["result"].get("data", {})
            results = data.get("results", [])
            summary = data.get("summary", {})

            if results:
                # 从第一条结果提取列名
                first_result = results[0]
                columns = ["t", "speed_kph", "acceleration_mps2", "VSP"] + \
                         list(first_result.get("emissions", {}).keys())

                # 返回完整表格数据（限制前100行）
                return {
                    "type": r["name"],
                    "columns": columns,
                    "preview_rows": results[:100],  # 前100行作为预览
                    "total_rows": len(results),
                    "total_columns": len(columns),
                    "summary": summary,
                    "total_emissions": summary.get("total_emissions", {})
                }
    return None
```

### 8.2 改进 Synthesis Prompt
**文件：** `core/router.py`

**当前代码 (17-30):**
```python
SYNTHESIS_PROMPT = """你是一个排放计算助手。

你刚刚执行了一些工具来获取数据。现在请根据工具执行的结果，用自然、友好的语言向用户解释：

1. **计算完成了什么**：简要说明执行了哪些操作
2. **主要结果是什么**：清晰地展示关键数据和发现
3. **如果有错误**：解释错误原因，并给出具体的解决建议

**重要**：
- 直接回复用户，不要调用任何工具
- 不要说"我将调用工具"或"让我执行..."
- 只需解释已经获得的结果
- 如果结果显示错误，帮助用户理解问题并提供解决方案
"""
```

**修复后：**
```python
SYNTHESIS_PROMPT = """你是机动车排放计算助手。

## 工具执行摘要
{summary}

## 回答要求
1. **基于结果回答**: 只使用工具摘要中的数据，不要编造数值
2. **参数说明**: 说明使用了哪些参数（车型、污染物、年份等）
3. **格式清晰**: 使用表格展示汇总数据
4. **不要编造**: 不要说"小汽车CO2排放因子约为xxx g/km"
5. **错误解释**: 如果有错误，解释原因和解决方案

**重要**：
- 直接回复用户，不要调用任何工具
- 不要编造任何数值数据
- 只解释已经获得的结果
"""
```

### 8.3 添加数据过滤机制
**文件：** `core/router.py`

**新增方法：**
```python
def _filter_results_for_synthesis(self, tool_results: list) -> Dict:
    """过滤工具结果，只保留关键信息供 Synthesis 使用"""
    filtered = {}

    for r in tool_results:
        tool_name = r["name"]
        result = r["result"]

        if not result.get("success"):
            filtered[tool_name] = {
                "success": False,
                "error": result.get("message")
            }
            continue

        data = result.get("data", {})

        # 对于排放计算工具，只保留汇总信息
        if tool_name in ["calculate_micro_emission", "calculate_macro_emission"]:
            summary = data.get("summary", {})
            filtered[tool_name] = {
                "success": True,
                "summary": result.get("summary"),
                "total_emissions": summary.get("total_emissions", {}),
                "num_points": len(data.get("results", [])),
                "query_params": data.get("query_params", {})
            }
        else:
            # 其他工具返回完整数据
            filtered[tool_name] = data

    return filtered
```

**修改 `_synthesize_results` 方法：**
```python
async def _synthesize_results(self, context, original_response, tool_results: list) -> str:
    # 1. 过滤数据，只保留关键信息
    filtered_results = self._filter_results_for_synthesis(tool_results)

    # 2. 格式化为 JSON 供 LLM 使用
    results_json = json.dumps(filtered_results, ensure_ascii=False, indent=2)

    # 3. 构建 synthesis messages
    synthesis_messages = context.messages.copy()
    synthesis_messages.append({
        "role": "assistant",
        "content": original_response.content or "Executing tools...",
        "tool_calls": [...]
    })

    # 4. 添加过滤后的结果
    for tr in tool_results:
        synthesis_messages.append({
            "role": "tool",
            "content": results_json,  # 使用过滤后的完整数据
            "tool_call_id": tr["tool_call_id"]
        })

    # 5. 调用 LLM synthesis
    synthesis_response = await self.llm.chat(
        messages=synthesis_messages,
        system=SYNTHESIS_PROMPT.format(summary=results_json)
    )

    return synthesis_response.content
```

### 8.4 修复 download_file 位置
**选项 1：** 统一放在顶层
```python
# tools/micro_emission.py
return ToolResult(
    success=True,
    data=result["data"],
    summary=summary,
    download_file=output_path  # 直接放在顶层
)
```

**选项 2：** 统一放在 data 中
```python
# core/router.py
def _extract_download_file(self, tool_results: list) -> Optional[str]:
    for r in tool_results:
        data = r["result"].get("data", {})
        if data and data.get("download_file"):
            # 返回 filename，不是整个字典
            return data["download_file"].get("filename")
    return None
```

---

## 9. 总结

| 问题 | 优先级 | 影响 | 修复文件 |
|-----|-------|------|---------|
| table_data 不完整 | 🔴 高 | 前端无法渲染表格 | `core/router.py` |
| Synthesis Prompt 过于宽松 | 🔴 高 | LLM 编造数据 | `core/router.py` |
| 缺少数据过滤机制 | 🟡 中 | Token 浪费、信息过载 | `core/router.py` |
| download_file 位置不一致 | 🟢 低 | 提取逻辑复杂 | `tools/*.py` 或 `core/router.py` |

建议修复顺序：
1. ✅ 修复 `table_data` 提取逻辑（立即修复）
2. ✅ 改进 Synthesis Prompt（立即修复）
3. ✅ 添加数据过滤机制（可选优化）
4. ⚠️ 统一 download_file 位置（可选优化）
