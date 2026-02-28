# 排放计算失败问题 - 修复报告

## 问题根因

通过分析日志和代码，确认了核心问题：

### 主要问题：合成阶段LLM尝试调用工具

**位置**: `core/router.py:288-291`

**原因**:
```python
# 之前的代码
synthesis_response = await self.llm.chat(
    messages=synthesis_messages,
    system=context.system_prompt  # ❌ 这个prompt包含"你可以通过调用工具"的描述
)
```

`context.system_prompt` 来自 `config/prompts/core.yaml`，其中包含：
```yaml
你是一个智能机动车排放计算助手。

## 你的能力

你可以通过调用工具来帮助用户：  # ← 这导致LLM认为还可以调用工具
- 查询排放因子曲线
- 计算车辆轨迹排放（微观）
...
```

**结果**:
- LLM在合成阶段仍然尝试调用工具
- `finish_reason: tool_calls` 而不是 `stop`
- 合成内容不完整或为空
- 用户看不到实际的计算结果

## 实施的修复

### 修复1: 创建专门的合成提示词 ✅

**文件**: `core/router.py:16-31`

添加了 `SYNTHESIS_PROMPT` 常量：

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

**关键点**:
- 明确告诉LLM"不要调用任何工具"
- 强调"只需解释已经获得的结果"
- 不包含任何工具调用的暗示

### 修复2: 使用专门的合成提示词 ✅

**文件**: `core/router.py:290-292`

```python
# 修改前
synthesis_response = await self.llm.chat(
    messages=synthesis_messages,
    system=context.system_prompt  # ❌ 包含工具调用描述
)

# 修改后
synthesis_response = await self.llm.chat(
    messages=synthesis_messages,
    system=SYNTHESIS_PROMPT  # ✅ 专门的合成提示词
)
```

### 修复3: 添加Fallback处理 ✅

**文件**: `core/router.py:298-310`

```python
if synthesis_response.finish_reason == "tool_calls":
    logger.warning(f"⚠️ Synthesis tried to call tools! This should not happen.")
    if synthesis_response.tool_calls:
        logger.warning(f"   Tools requested: {[tc.name for tc in synthesis_response.tool_calls]}")
    logger.warning(f"   Using fallback formatting...")
    # Fallback: format results directly
    return self._format_results_as_fallback(tool_results)

# Check if content is empty or too short
if not synthesis_response.content or len(synthesis_response.content.strip()) < 20:
    logger.warning("⚠️ Synthesis returned empty or very short content, using fallback")
    return self._format_results_as_fallback(tool_results)
```

**作用**:
- 如果合成仍然尝试调用工具，使用fallback
- 如果合成返回空内容，使用fallback
- 确保用户总能看到结果

### 修复4: 实现Fallback格式化方法 ✅

**文件**: `core/router.py:356-410`

添加了 `_format_results_as_fallback()` 方法：

```python
def _format_results_as_fallback(self, tool_results: list) -> str:
    """
    Fallback method to format tool results directly when synthesis fails

    This provides a structured, user-friendly response without relying on LLM synthesis
    """
    lines = []
    lines.append("## 工具执行结果\n")

    success_count = sum(1 for r in tool_results if r["result"].get("success"))
    error_count = len(tool_results) - success_count

    if error_count > 0:
        lines.append(f"⚠️ {error_count} 个工具执行失败，{success_count} 个成功\n")
    else:
        lines.append(f"✅ 所有工具执行成功\n")

    for i, r in enumerate(tool_results, 1):
        tool_name = r["name"]
        result = r["result"]

        lines.append(f"### {i}. {tool_name}\n")

        if result.get("success"):
            lines.append("**状态**: ✅ 成功\n")
            # Add summary and data...
        else:
            lines.append("**状态**: ❌ 失败\n")
            # Add error message and suggestions...

    return "".join(lines)
```

**作用**:
- 直接格式化工具结果，不依赖LLM
- 提供结构化、用户友好的输出
- 显示成功/失败状态、错误信息、建议

### 修复5: 增强工具执行日志 ✅

**文件**: `core/executor.py:66-76, 82-100`

添加了详细的日志：

```python
# 标准化前后
logger.debug(f"Original arguments for {tool_name}: {arguments}")
standardized_args = self._standardize_arguments(tool_name, arguments)
logger.debug(f"Standardized arguments: {standardized_args}")

# 执行结果
logger.info(f"Executing {tool_name} with standardized args")
result = await tool.execute(**standardized_args)

logger.info(f"{tool_name} execution completed. Success: {result.success}")
if not result.success:
    logger.error(f"{tool_name} failed: {result.data if result.error else 'Unknown error'}")
```

**作用**:
- 追踪参数标准化过程
- 记录工具执行状态
- 捕获错误信息

## 验证车型标准化

检查了 `config/unified_mappings.yaml`，确认"大货车"已正确映射：

```yaml
- id: 62
  standard_name: "Combination Long-haul Truck"
  display_name_zh: "重型货车"
  aliases:
    - "重卡"
    - "大货车"  # ✅ 已包含
    - "挂车"
    - "组合长途货车"
```

车型标准化应该正常工作。

## 预期效果

修复后的行为：

1. **工具执行阶段**:
   - LLM决定调用 `calculate_micro_emission` 和 `analyze_file`
   - 两个工具都被执行
   - 结果被收集

2. **合成阶段**:
   - 使用 `SYNTHESIS_PROMPT`（不包含工具调用描述）
   - LLM只解释结果，不尝试调用工具
   - `finish_reason: stop`（正常完成）

3. **如果合成失败**:
   - 检测到 `finish_reason: tool_calls` 或空内容
   - 自动使用fallback格式化
   - 用户仍然能看到结构化的结果

4. **用户体验**:
   - 看到完整的计算结果
   - 如果有错误，看到清晰的错误信息和建议
   - 不再出现"正在计算……"后无结果的情况

## 测试步骤

1. **重启服务器**:
   ```powershell
   .\scripts\restart_server.ps1
   ```

2. **重新测试相同场景**:
   - 上传 `micro_05_minimal.csv`
   - 输入"我上传了一个轨迹文件，帮我算排放"
   - 输入"2021年的大货车"

3. **检查日志**:
   - 查看工具执行状态
   - 查看参数标准化过程
   - 确认合成阶段 `finish_reason: stop`
   - 如果使用fallback，会看到警告日志

4. **验证结果**:
   - 用户应该看到完整的计算结果或清晰的错误信息
   - 不应该再出现"正在计算"后无结果的情况

## 其他改进

### 日志增强

在关键位置添加了详细日志：
- 工具执行前后
- 参数标准化过程
- 合成阶段状态
- Fallback触发条件

### 错误处理

改进了错误处理：
- 标准化错误
- 执行错误
- 合成失败
- 所有情况都有fallback

## 文件修改清单

1. ✅ `core/router.py`
   - 添加 `SYNTHESIS_PROMPT` 常量
   - 修改 `_synthesize_results()` 使用专门提示词
   - 添加fallback处理逻辑
   - 实现 `_format_results_as_fallback()` 方法

2. ✅ `core/executor.py`
   - 添加参数标准化日志
   - 添加工具执行状态日志
   - 增强错误信息记录

3. ✅ `config.py`
   - 提高 `max_tokens` 从 2000 → 8000

## 总结

- ✅ **根本问题**: 合成阶段使用了包含工具调用描述的system prompt
- ✅ **核心修复**: 创建并使用专门的合成提示词
- ✅ **安全网**: 添加fallback处理确保用户总能看到结果
- ✅ **可观测性**: 增强日志帮助诊断问题
- ⏳ **待验证**: 需要重启服务器并重新测试

---

**修复时间**: 2026-02-04 17:45
**状态**: ✅ 修复完成，等待测试验证
