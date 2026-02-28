# LLM未调用计算工具问题 - 修复报告

## 问题现象

修复合成阶段问题后，出现新问题：
- 用户上传文件并要求计算排放
- LLM只调用了 `analyze_file` 工具
- LLM没有调用 `calculate_micro_emission` 工具
- 用户看到"正在执行计算…"但从未得到结果

## 根本原因

### 问题1：文件路径未传递给LLM

**位置**: `core/assembler.py:165-178`

文件上下文格式化时，没有包含 `file_path`：

```python
def _format_file_context(self, file_context: Dict, max_tokens: int) -> str:
    lines = [
        f"Filename: {file_context.get('filename', 'unknown')}",
        f"Type: {file_context.get('detected_type', 'unknown')}",
        # ❌ 缺少 file_path！
        f"Rows: {file_context.get('row_count', 'unknown')}",
        f"Columns: {', '.join(file_context.get('columns', []))}",
    ]
```

**结果**:
- LLM看到文件信息，但不知道文件路径
- 无法调用 `calculate_micro_emission(file_path=...)`
- 只能分析文件，无法计算

### 问题2：文件分析器未返回file_path

**位置**: `core/router.py:247-254`

`_analyze_file` 方法返回的数据不包含 file_path：

```python
async def _analyze_file(self, file_path: str) -> Dict:
    result = await self.executor.execute(
        tool_name="analyze_file",
        arguments={"file_path": file_path},
        file_path=file_path
    )
    return result.get("data", {})  # ❌ data中没有file_path
```

### 问题3：工具定义不够明确

**位置**: `tools/definitions.py:59-101`

`calculate_micro_emission` 工具定义：
- `file_path` 参数描述不够明确
- `required` 字段为空数组
- 没有强调"当用户上传文件时必须使用file_path"

## 实施的修复

### 修复1: 在文件上下文中包含file_path ✅

**文件**: `core/assembler.py:165-178`

```python
def _format_file_context(self, file_context: Dict, max_tokens: int) -> str:
    """Format file context for LLM"""
    lines = [
        f"Filename: {file_context.get('filename', 'unknown')}",
        f"File path: {file_context.get('file_path', 'unknown')}",  # ✅ 添加file_path
        f"Type: {file_context.get('detected_type', 'unknown')}",
        f"Rows: {file_context.get('row_count', 'unknown')}",
        f"Columns: {', '.join(file_context.get('columns', []))}",
    ]
    ...
```

### 修复2: 在_analyze_file中添加file_path ✅

**文件**: `core/router.py:247-256`

```python
async def _analyze_file(self, file_path: str) -> Dict:
    """Analyze file using file analyzer tool"""
    result = await self.executor.execute(
        tool_name="analyze_file",
        arguments={"file_path": file_path},
        file_path=file_path
    )
    data = result.get("data", {})
    # ✅ Add file_path to the data so LLM knows where the file is
    data["file_path"] = file_path
    return data
```

### 修复3: 改进工具定义 ✅

**文件**: `tools/definitions.py:56-102`

```python
{
    "name": "calculate_micro_emission",
    "description": """...

**IMPORTANT**: When user uploads a file, you will see the file path in the context. Use that file_path parameter to calculate emissions.

...""",
    "parameters": {
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to trajectory data file. REQUIRED when user uploaded a file. You will see this path in the file context."  # ✅ 更明确
            },
            "vehicle_type": {
                "type": "string",
                "description": "Vehicle type. Pass user's original expression. REQUIRED."  # ✅ 标记为必需
            },
            ...
        },
        "required": ["vehicle_type"]  # ✅ 添加必需参数
    }
}
```

## 预期效果

修复后的流程：

1. **用户上传文件并请求计算**:
   ```
   用户: "帮我计算这个大货车的排放"
   文件: micro_05_minimal.csv
   ```

2. **Router自动分析文件**:
   ```python
   file_context = await self._analyze_file(file_path)
   # file_context now includes:
   # {
   #     "filename": "micro_05_minimal.csv",
   #     "file_path": "C:\\Users\\PC\\AppData\\Local\\Temp\\ddaa2cf1_input.csv",  # ✅
   #     "detected_type": "micro_emission",
   #     "columns": ["t", "speed"],
   #     ...
   # }
   ```

3. **LLM看到完整上下文**:
   ```
   [File uploaded]
   Filename: micro_05_minimal.csv
   File path: C:\Users\PC\AppData\Local\Temp\ddaa2cf1_input.csv  # ✅ LLM能看到路径
   Type: micro_emission
   Rows: 100
   Columns: t, speed

   [User message]
   帮我计算这个大货车的排放
   ```

4. **LLM调用正确的工具**:
   ```python
   # LLM should now call:
   calculate_micro_emission(
       file_path="C:\\Users\\PC\\AppData\\Local\\Temp\\ddaa2cf1_input.csv",  # ✅ 使用文件路径
       vehicle_type="大货车",
       model_year=2021  # 如果用户指定
   )
   ```

5. **工具执行并返回结果**:
   - 读取文件数据
   - 计算排放
   - 生成Excel报告
   - 返回结果

6. **合成阶段**:
   - 使用 `SYNTHESIS_PROMPT`
   - 不尝试调用工具
   - 向用户解释结果

## 测试步骤

1. **重启服务器**:
   ```powershell
   .\scripts\restart_server.ps1
   ```

2. **重新测试**:
   - 上传 `micro_05_minimal.csv`
   - 输入"帮我计算这个大货车的排放"

3. **检查日志**:
   - 确认file_path出现在文件上下文中
   - 确认LLM调用了 `calculate_micro_emission`
   - 确认传递了正确的file_path参数

4. **验证结果**:
   - 用户应该看到完整的排放计算结果
   - 包括总排放量、详细数据、下载链接

## 文件修改清单

1. ✅ `core/assembler.py`
   - 在 `_format_file_context()` 中添加file_path

2. ✅ `core/router.py`
   - 在 `_analyze_file()` 中添加file_path到返回数据

3. ✅ `tools/definitions.py`
   - 改进 `calculate_micro_emission` 工具描述
   - 添加 `vehicle_type` 到required参数
   - 强调file_path的重要性

## 总结

- ✅ **问题1**: 合成阶段尝试调用工具 → 已修复（使用SYNTHESIS_PROMPT）
- ✅ **问题2**: LLM未调用计算工具 → 已修复（添加file_path到上下文）
- ⏳ **待验证**: 需要重启服务器并重新测试

---

**修复时间**: 2026-02-04 18:00
**状态**: ✅ 修复完成，等待测试验证
