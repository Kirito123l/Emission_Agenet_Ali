# 完整诊断总结与修复路线图

## 问题汇总

当前系统存在 **三个严重问题**：

### 1. LLM 幻觉问题 🔴 严重

**现象**:
- CO2: 5,821 kg → LLM 说成 1.72 kg (相差 3,384 倍)
- 编造"排放峰值在第42-48个点"
- 编造"空调导致 CO2 增加 7%"
- 编造"PM2.5 主要来自燃油不完全燃烧（占比 68%）"

**原因**: Synthesis Prompt 太宽松，没有明确禁止编造

### 2. 计算数值异常 🔴 严重

**现象**:
- CO2 排放: 5,239 kg/km
- 正常值: 0.5-1 kg/km
- 异常倍数: **5,000-10,000 倍**

**原因**: 排放因子单位理解或转换错误

### 3. 参数名称不一致 🟡 中等

**现象**:
- 工具定义使用 `file_path`
- 工具实现期望 `input_file`

**原因**: 新旧架构过渡时的不一致

---

## 修复优先级

### 阶段 1: 立即修复 (高优先级)

#### 1.1 修复 Synthesis Prompt

**文件**: `core/router.py`

**修改**:
```python
SYNTHESIS_PROMPT = """你是机动车排放计算助手。

## 严格要求

1. **只报告实际数据**: 只使用工具返回的数值，不要编造
2. **禁止编造内容**:
   - ❌ 不要编造"排放峰值出现在第X个点"
   - ❌ 不要编造"空调导致增加X%"
   - ❌ 不要编造污染物来源分析
   - ❌ 不要进行生活化类比（如"相当于X棵树"）
3. **不要修改数值**: 直接使用工具返回的数值，不要转换
4. **简洁格式**: 使用表格展示汇总数据

## 回答模板

```
计算完成。

车型：{vehicle_type}
污染物：{pollutants}

总排放量：
| 污染物 | 排放量 (g) |
|--------|-----------|
| CO2    | {actual_value} |
| NOx    | {actual_value} |

结果文件：{filename} (如有)
```

请基于工具返回的实际数据生成回答。
"""
```

#### 1.2 添加数据过滤

**文件**: `core/router.py`

**添加方法**:
```python
def _filter_tool_results_for_synthesis(self, tool_results: List[Dict]) -> Dict:
    """过滤工具结果，只保留 synthesis 需要的信息"""
    filtered = {}

    for tool_result in tool_results:
        tool_name = tool_result["name"]
        result_data = tool_result["result"]

        if tool_name in ["calculate_micro_emission", "calculate_macro_emission"]:
            summary = result_data.get("data", {}).get("summary", {})
            download = result_data.get("data", {}).get("download_file")

            filtered[tool_name] = {
                "summary": summary,
                "has_download_file": download is not None
            }

    return filtered
```

**修改** `_synthesize_results`:
```python
# 过滤结果
filtered_results = self._filter_tool_results_for_synthesis(tool_results)

# 构建消息
synthesis_messages = [{
    "role": "system",
    "content": SYNTHESIS_PROMPT
}, {
    "role": "user",
    "content": f"工具执行结果：\n{json.dumps(filtered_results, ensure_ascii=False, indent=2)}\n\n请生成回答。"
}]
```

### 阶段 2: 诊断计算问题 (中优先级)

#### 2.1 添加诊断日志

**文件**: `calculators/micro_emission.py`

**添加**:
```python
logger.info(f"[Calc] Input: {len(trajectory_data)} points")
logger.info(f"[Calc] Sample point: {trajectory_data[0]}")
logger.info(f"[Calc] Query result: speed={speed}, vsp={vsp}, factor={factor}")
logger.info(f"[Calc] Emission: {emission} g")
```

#### 2.2 检查数据文件

```bash
# 检查排放因子单位
head -5 calculators/data/atlanta_2025_7_90_70.csv

# 检查 factor 范围
python -c "import pandas as pd; df=pd.read_csv('calculators/data/atlanta_2025_7_90_70.csv'); print(df['factor'].describe())"
```

#### 2.3 验证计算逻辑

创建测试脚本:
```python
# test_calculation.py
from calculators.micro_emission import MicroEmissionCalculator

calc = MicroEmissionCalculator()

# 简单测试
test_data = [
    {"t": 0, "speed_kph": 60},
    {"t": 1, "speed_kph": 60},
]

result = calc.calculate(
    trajectory_data=test_data,
    vehicle_type="Passenger Car",
    pollutants=["CO2"],
    model_year=2020,
    season="夏季"
)

print("Result:", result)
```

### 阶段 3: 巩固修复 (低优先级)

#### 3.1 统一参数名称

**选项A**: 修改工具定义，使用 `input_file`
**选项B**: 保持 `file_path`，添加映射逻辑 (已实现)

#### 3.2 完善文档

- 更新 API 文档
- 添加常见问题 FAQ
- 记录已知问题和解决方案

---

## 验证标准

### 修复后应该看到:

1. **Synthesis 输出正确**:
   ```
   计算完成。

   车型：Combination Long-haul Truck
   污染物：CO2, NOx, PM2.5

   总排放量：
   | 污染物 | 排放量 (g) |
   |--------|-----------|
   | CO2    | 5820971.98 |
   | NOx    | 1900.41 |
   | PM2.5  | 27.36 |

   结果文件：9c953782_result.xlsx
   ```

2. **不再出现**:
   - ❌ "CO2: 1.72 kg"
   - ❌ "排放峰值在第42-48个点"
   - ❌ 任何分析或推断

3. **计算结果合理**:
   - CO2 排放: 0.5-1 kg/km (货车)
   - 与文献值接近

---

## 快速修复脚本

创建一个快速修复脚本:

```bash
# fix_synthesis.sh
#!/bin/bash

echo "1. 备份当前文件..."
cp core/router.py core/router.py.backup

echo "2. 应用 Synthesis Prompt 修复..."
# 使用 sed 或手动修改

echo "3. 重启服务器..."
./scripts/restart_server.ps1

echo "4. 运行测试..."
python test_synthesis.py

echo "完成！"
```

---

## 相关文档

| 文档 | 内容 |
|------|------|
| `ORIGINAL_ARCHITECTURE_ANALYSIS.md` | 原架构详细分析 |
| `SYNTHESIS_COMPARISON.md` | Synthesis 对比与修复方案 |
| `CALCULATION_FAILURE_ANALYSIS.md` | 计算问题诊断 |
| `TOOL_PARAMETER_FIX_APPLIED.md` | 参数映射修复 |
| `MISSING_DATA_FILES_FIX.md` | 数据文件修复 |
| `LLM_HALLUCINATION_ANALYSIS.md` | LLM 幻觉分析 |
| `DIAGNOSTIC_REPORT.md` | 完整诊断报告 |

---

## 下一步行动

1. **立即**: 修改 `core/router.py` 中的 `SYNTHESIS_PROMPT`
2. **今天**: 添加数据过滤逻辑，测试 Synthesis
3. **明天**: 诊断计算器问题，添加日志
4. **本周**: 修复计算器单位问题，完善文档

---

## 联系与支持

如遇到问题：
1. 查看上述诊断文档
2. 检查日志: `logs/requests.log`
3. 查看会话历史: `data/sessions/history/{session_id}.json`
