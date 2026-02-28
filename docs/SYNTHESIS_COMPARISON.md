# Synthesis 逻辑对比与修复方案

## 问题现状

当前新架构的 Synthesis 存在严重问题：
1. **LLM 严重幻觉**: 编造大量不存在的数据和分析
2. **数值错误**: CO2 从 5,821 kg 说成 1.72 kg
3. **编造细节**: 说"排放峰值在第42-48个点"等完全不存在的信息

## 原架构 Synthesis 逻辑

### 核心特点

1. **专门的 Synthesis LLM**
   ```python
   # legacy/agent/core.py
   def __init__(self):
       self._agent_llm = get_llm("agent")
       self._synthesis_llm = get_llm("synthesis")  # 专门的 LLM
   ```

2. **严格的 Synthesis Prompt**
   ```python
   SYNTHESIS_PROMPT = """
   ## 回答要求
   1. **基于结果回答**: 只使用执行结果中的数据，不要编造
   2. **引用历史**: 如果用户提到"刚才"、"之前"，从上下文中引用
   3. **参数说明**: 说明使用了哪些参数（包括从记忆中获取的）
   4. **格式清晰**: 使用表格展示汇总数据（总排放量等）
   5. **不要编造排放因子**: 不要显示"小汽车CO2排放因子约为xxx g/km"这种编造的数据
   6. **错误解释**: 如果用户询问错误，且有错误信息，解释错误原因和解决方案
   7. **不要重复展示详细数据**: results_sample仅供参考数据结构，不要在回答中列出详细的逐行数据表格
   """
   ```

3. **数据过滤机制**
   ```python
   def _filter_results_for_synthesis(self, results: Dict) -> Dict:
       """
       过滤结果数据，保留样本数据供LLM参考，避免发送过多详细数据
       """
       filtered = {}

       for skill_name, result in results.items():
           if skill_name in ["calculate_macro_emission", "calculate_micro_emission"]:
               data = result.get("data", {})

               # 只保留汇总信息
               filtered[skill_name] = {
                   "summary": data.get("summary", {}),
                   "download_file": data.get("download_file"),
                   "output_file": data.get("output_file"),
                   "query_params": result.get("metadata", {}).get("query_params", {})
               }

               # 保留最多3行样本数据
               results_list = data.get("results", [])
               if results_list:
                   filtered[skill_name]["results_sample"] = results_list[:3]

       return filtered
   ```

4. **检测输入方式，调整回答格式**
   ```python
   # 检查是否有input_file，决定回答格式
   has_input_file = False
   for skill_name, result in results.items():
       if skill_name in ["calculate_macro_emission", "calculate_micro_emission"]:
           query_params = result.get("metadata", {}).get("query_params", {})
           if query_params.get("input_file"):
               has_input_file = True
               break

   # 根据输入方式添加格式说明
   if has_input_file:
       format_instruction = """
   用户上传了文件进行计算。
   - 输入文件已处理
   - 结果文件已生成可供下载
   - 请在回答中强调文件处理流程
       """
   else:
       format_instruction = """
   用户提供了文本描述的参数。
   - 请直接展示计算结果
       """
   ```

## 新架构 Synthesis 逻辑

### 当前实现 (有问题)

```python
# core/router.py
SYNTHESIS_PROMPT = """你是一个排放计算助手。
你刚刚执行了一些工具来获取数据。现在请根据工具执行的结果，用自然、友好的语言向用户解释：
**重要**：
- 直接回复用户，不要调用任何工具
- 不要说"我将调用工具"或"让我执行..."
- 只需解释已经获得的结果
"""
```

### 问题分析

| 问题 | 原因 | 后果 |
|------|------|------|
| **"用自然、友好的语言向用户解释"** | 太宽松，LLM 理解为可以"美化"和"扩展" | LLM 编造分析 |
| **"解释已经获得的结果"** | 没有明确禁止编造 | LLM 添加不存在的细节 |
| **没有数据过滤** | 直接传递原始结果给 LLM | LLM 受到过多数据干扰 |
| **没有禁止编造条款** | 缺少明确限制 | LLM 创造性地生成内容 |
| **没有格式规范** | 没有指定如何展示数据 | LLM 随意组织回答 |

### 实际幻觉示例

**实际数据**:
```json
{
  "total_emissions_g": {"CO2": 5820971.98, "NOx": 1900.40}
}
```

**LLM 说的**:
- CO2: 1.72 kg ❌ (实际 5,821 kg)
- "排放峰值出现在第42–48个点" ❌ (完全编造)
- "空调启用导致 CO2 增加约 7%" ❌ (完全编造)

## 修复方案

### 方案1: 强化 SYNTHESIS_PROMPT (推荐)

```python
SYNTHESIS_PROMPT = """你是机动车排放计算助手。你刚刚执行了工具并获得了计算结果。

## 严格要求

1. **只报告实际数据**: 只使用工具返回的数据，不要编造任何数字
2. **不要添加分析**: 不要添加任何未在工具结果中出现的分析、推断或细节
3. **不要单位转换**: 不要进行数学计算或单位转换，直接使用工具返回的数值
4. **禁止编造**: 严格禁止编造以下内容：
   - ❌ 编造"排放峰值出现在第X个点"
   - ❌ 编造"空调导致增加X%"
   - ❌ 编造"相当于X棵树"等类比
   - ❌ 修改或"美化"工具返回的数值

## 回答格式

如果工具返回了 summary 字段：
```
计算完成。
- 车型：{vehicle_type}
- 污染物：{pollutants}
- 总排放量：
  | 污染物 | 排放量 |
  |--------|--------|
  | CO2    | {value} g |
  | NOx    | {value} g |
```

如果工具返回了 download_file：
```
结果文件已生成：{filename}
```

## 禁止行为示例

❌ 不要说："排放峰值出现在第42-48个点"
❌ 不要说："空调启用导致CO2增加约7%"
❌ 不要说："PM2.5主要来自燃油不完全燃烧（占比68%）"
❌ 不要修改数值（如把5820971改成1720）

✅ 只说："计算已完成，CO2总排放量为5820971.98 g"

请基于工具返回的实际数据生成回答。
"""
```

### 方案2: 添加数据过滤

```python
def _filter_tool_results_for_synthesis(self, tool_results: List[Dict]) -> Dict:
    """
    过滤工具结果，只保留 synthesis 需要的信息
    """
    filtered = {}

    for tool_result in tool_results:
        tool_name = tool_result["name"]
        result_data = tool_result["result"]

        if tool_name in ["calculate_micro_emission", "calculate_macro_emission"]:
            # 只保留 summary，不保留详细 results
            filtered[tool_name] = {
                "summary": result_data.get("data", {}).get("summary"),
                "download_file": result_data.get("data", {}).get("download_file"),
                "output_file": result_data.get("data", {}).get("output_file")
            }

    return filtered
```

在 `_synthesize_results` 中使用：

```python
# 过滤工具结果
filtered_results = self._filter_tool_results_for_synthesis(tool_results)

# 构建 synthesis 消息
synthesis_messages = [{
    "role": "system",
    "content": SYNTHESIS_PROMPT
}, {
    "role": "user",
    "content": f"工具执行结果：\n{json.dumps(filtered_results, ensure_ascii=False, indent=2)}\n\n请生成用户回答。"
}]
```

### 方案3: 分离输入输出处理

检测输入方式，调整 prompt：

```python
def _synthesize_results(self, context, response, tool_results):
    # 检测是否有文件输入
    has_file_input = any(
        tr["result"].get("data", {}).get("download_file")
        for tr in tool_results
    )

    # 根据输入方式调整 prompt
    if has_file_input:
        instruction = "\n用户上传了文件，结果文件已生成。请强调：输入文件已处理，结果文件可供下载。"
    else:
        instruction = "\n用户提供了文本参数。请直接展示计算结果。"

    synthesis_messages = [...]
    synthesis_messages[0]["content"] += instruction

    # ...
```

## 立即行动项

1. ✅ **优先级1**: 修改 `SYNTHESIS_PROMPT`，添加严格的禁止条款
2. ✅ **优先级2**: 添加数据过滤逻辑
3. ✅ **优先级3**: 检查计算器单位问题 (CO2 为何异常高)
4. ✅ **优先级4**: 添加输入方式检测，调整回答格式

## 测试验证

修复后测试案例：

**输入**: 用户上传 micro_05_minimal.csv，说"帮我计算这个大货车的排放"

**期望输出**:
```
计算完成。

车型：大货车 → Combination Long-haul Truck
污染物：CO2, NOx, PM2.5
年份：2020
季节：夏季

总排放量：
| 污染物 | 排放量 (g) |
|--------|-----------|
| CO2    | 5820971.98 |
| NOx    | 1900.41 |
| PM2.5  | 27.36 |

结果文件已生成：9c953782_result.xlsx
```

**不应该出现**:
- ❌ "CO2: 1.72 kg" (数值错误)
- ❌ "排放峰值出现在第42-48个点" (编造)
- ❌ "空调导致增加7%" (编造)
