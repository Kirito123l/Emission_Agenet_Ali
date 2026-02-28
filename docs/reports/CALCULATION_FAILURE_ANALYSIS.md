# 排放计算失败 - 完整问题分析

## 问题现象

用户上传CSV文件并要求计算"2021年大货车"的排放，但Agent无法成功完成计算：

### 用户看到的情况

1. **第一次尝试**（用户说"2021年的大货车"）：
   ```
   分析完成 ✅
   ...
   正在重新计算……👇

   [然后就没有结果了]
   ```

2. **第二次尝试**（用户说"重新计算吧"）：
   ```
   感谢分析！...
   正在执行……👇

   [又没有结果]
   ```

Agent一直说"正在计算"但从不显示实际结果。

### 服务器日志显示

```
Processing message: 2021年的大货车...
Assembled context: ~1244 tokens, 6 messages
HTTP Request: POST ... "HTTP/1.1 200 OK"
Executing tool: calculate_micro_emission
HTTP Request: POST ... "HTTP/1.1 200 OK"
Executing tool: analyze_file
Synthesizing results from 1 tool calls  ← ⚠️ 只合成1个工具，但执行了2个！
HTTP Request: POST ... "HTTP/1.1 200 OK"
Synthesis complete. Response length: 520 chars, finish_reason: tool_calls  ← ⚠️ 合成阶段又想调用工具！
```

## 发现的问题

### 问题1：工具结果丢失

**位置**：日志显示

```
Executing tool: calculate_micro_emission
Executing tool: analyze_file
Synthesizing results from 1 tool calls  ← 应该是2个！
```

**分析**：
- 执行了2个工具
- 但只合成了1个工具的结果
- 另一个工具的结果丢失了

**可能原因**：
- `tool_results` 列表构建有问题
- 某个工具执行失败但没有被正确记录
- 工具结果被覆盖或过滤掉了

### 问题2：合成阶段尝试调用工具

**位置**：日志显示

```
Synthesis complete. Response length: 520 chars, finish_reason: tool_calls
```

**分析**：
- `finish_reason: tool_calls` 意味着LLM想要调用更多工具
- 但合成阶段应该只是将结果转换为自然语言，不应该调用工具
- 这导致合成结果不完整，没有实际的排放计算数据

**可能原因**：
- 合成时的system prompt或context仍然包含工具定义
- 工具结果格式不正确，LLM认为需要更多信息
- LLM误解了任务，认为还需要调用工具

### 问题3：工具执行可能失败但未报告

**位置**：会话历史显示

Agent说：
```
但之前调用失败，大概率是因：
- 工具内部对"大货车"的车型名称匹配不严格
- 或 speed 列实际单位不是 km/h
```

**分析**：
- Agent意识到工具调用失败了
- 但没有显示具体的错误信息
- 用户无法知道真正的失败原因

## 需要检查的代码位置

### 1. 工具执行结果收集

**文件**：`core/router.py:144-157`

```python
# Case 3: Execute tool calls
tool_results = []
for tool_call in response.tool_calls:
    logger.info(f"Executing tool: {tool_call.name}")
    result = await self.executor.execute(
        tool_name=tool_call.name,
        arguments=tool_call.arguments,
        file_path=file_path
    )
    tool_results.append({
        "tool_call_id": tool_call.id,
        "name": tool_call.name,
        "result": result
    })
```

**需要检查**：
- 是否所有工具都被正确添加到 `tool_results`
- 是否有异常被吞掉
- `result` 的内容是什么

### 2. 错误处理逻辑

**文件**：`core/router.py:159-200`

```python
# Check for errors
has_error = any(r["result"].get("error") for r in tool_results)

if has_error and tool_call_count < self.MAX_TOOL_CALLS_PER_TURN - 1:
    # Let LLM handle the error (might ask for clarification)
    error_messages = self._format_tool_errors(tool_results)
    ...
    # Retry with error context
    retry_response = await self.llm.chat_with_tools(...)
    return await self._process_response(...)
```

**需要检查**：
- 错误检测是否正确
- 重试逻辑是否正常工作
- 是否进入了无限重试循环

### 3. 合成方法

**文件**：`core/router.py:230-286`

```python
async def _synthesize_results(...):
    # Format tool results for LLM
    results_summary = self._format_tool_results(tool_results)

    # Build synthesis messages
    synthesis_messages = context.messages.copy()
    ...

    # Call LLM to synthesize
    synthesis_response = await self.llm.chat(
        messages=synthesis_messages,
        system=context.system_prompt
    )
```

**需要检查**：
- `results_summary` 的内容是什么
- `synthesis_messages` 是否包含了所有工具结果
- 为什么 `finish_reason` 是 `tool_calls`
- `context.system_prompt` 是否包含工具定义（不应该有）

### 4. 工具结果格式化

**文件**：`core/router.py:293-303`

```python
def _format_tool_results(self, tool_results: list) -> str:
    """Format tool results for LLM"""
    summaries = []
    for r in tool_results:
        if r["result"].get("success"):
            summary = r["result"].get("summary", "Execution successful")
            summaries.append(f"[{r['name']}] {summary}")
        else:
            error = r["result"].get("message", "Unknown error")
            summaries.append(f"[{r['name']}] Error: {error}")
    return "\n".join(summaries)
```

**需要检查**：
- 是否所有工具结果都被格式化
- 错误信息是否完整
- summary 是否包含足够的信息

## 诊断步骤

### Step 1: 添加详细日志

在关键位置添加日志：

1. **工具执行后**：
   ```python
   logger.info(f"Tool {tool_call.name} executed. Success: {result.get('success')}, Error: {result.get('error')}")
   logger.debug(f"Tool result: {json.dumps(result, indent=2)[:500]}")
   ```

2. **工具结果收集后**：
   ```python
   logger.info(f"Collected {len(tool_results)} tool results")
   for i, tr in enumerate(tool_results):
       logger.info(f"  Tool {i+1}: {tr['name']}, Success: {tr['result'].get('success')}")
   ```

3. **合成前**：
   ```python
   logger.info(f"Results summary for synthesis:\n{results_summary}")
   logger.info(f"Synthesis messages count: {len(synthesis_messages)}")
   ```

4. **合成后**：
   ```python
   if synthesis_response.tool_calls:
       logger.warning(f"⚠️ Synthesis tried to call tools: {[tc.name for tc in synthesis_response.tool_calls]}")
   ```

### Step 2: 检查工具执行器

检查 `calculate_micro_emission` 工具是否正确执行：

```python
# In executor.py
logger.info(f"Executing tool: {tool_name}")
logger.info(f"Arguments: {json.dumps(arguments, indent=2)}")
result = await tool.execute(**standardized_args)
logger.info(f"Tool execution result: success={result.success}, error={result.error}")
if result.error:
    logger.error(f"Tool error message: {result.data}")
```

### Step 3: 检查车型标准化

检查"大货车"是否被正确标准化：

```python
# Check standardization
logger.info(f"Original vehicle_type: {arguments.get('vehicle_type')}")
logger.info(f"Standardized vehicle_type: {standardized_args.get('vehicle_type')}")
```

### Step 4: 检查文件数据

检查上传的CSV文件内容：

```python
# Read first few rows
import pandas as pd
df = pd.read_csv(file_path)
logger.info(f"File shape: {df.shape}")
logger.info(f"Columns: {df.columns.tolist()}")
logger.info(f"First 5 rows:\n{df.head()}")
logger.info(f"Speed range: {df['speed'].min()} - {df['speed'].max()}")
```

## 临时解决方案

在修复根本问题之前，可以：

1. **添加更详细的错误信息**：
   - 在合成阶段检测 `finish_reason == "tool_calls"`
   - 如果发生，返回友好的错误消息而不是空响应

2. **强制完成合成**：
   - 如果合成返回 `tool_calls`，忽略它们
   - 使用 `response.content` 即使它不完整

3. **添加fallback逻辑**：
   - 如果合成失败，直接返回工具结果的JSON
   - 至少让用户看到原始数据

## 下一步行动

1. ✅ 添加详细日志（Step 1）
2. ⏳ 重新测试并收集日志
3. ⏳ 根据日志定位具体问题
4. ⏳ 修复根本原因
5. ⏳ 验证修复

---

**创建时间**: 2026-02-04 17:30
**状态**: 🔍 诊断中
