# Claude Code 补充分析任务

基于已完成的架构诊断，需要补充以下关键信息以设计优化方案。

## 任务1：提取完整的 System Prompt

```bash
# 输出完整的 system.py 内容
cat agent/prompts/system.py
```

请将完整内容保存到 `FULL_SYSTEM_PROMPT.md`

## 任务2：分析 LLM 调用链路

统计一次完整请求中 LLM 被调用的次数和位置：

```bash
# 搜索所有 LLM 调用点
grep -rn "llm\." agent/ --include="*.py"
grep -rn "self._llm" agent/ --include="*.py"
grep -rn "client.chat" agent/ --include="*.py"
grep -rn "client.chat" shared/ --include="*.py"
grep -rn "client.chat" skills/ --include="*.py"
```

生成一个 LLM 调用链路图，说明：
1. 每次 LLM 调用的目的
2. 调用的模型（qwen-flash/qwen3-max/本地模型）
3. 是否可以合并或省略

## 任务3：分析"补丁式"规则的来源

查看 git 提交历史，找出 system.py 中规则增长的模式：

```bash
# 如果有 git 历史
git log --oneline --follow agent/prompts/system.py 2>/dev/null | head -20

# 或者分析文件中的注释
grep -n "注意\|重要\|不要\|错误" agent/prompts/system.py
```

## 任务4：提取所有硬编码映射到单一文件

创建 `ALL_HARDCODED_RULES.json`，包含所有硬编码规则：

```python
# 执行以下 Python 脚本
import json
import re

rules = {
    "vehicle_mappings": {},
    "pollutant_mappings": {},
    "column_patterns": {},
    "field_corrections": {},
    "keywords": {}
}

# 从 constants.py 提取
exec(open("shared/standardizer/constants.py").read())
# ... 收集所有映射

with open("ALL_HARDCODED_RULES.json", "w") as f:
    json.dump(rules, f, indent=2, ensure_ascii=False)
```

## 任务5：验证层实际效果统计

如果有学习案例数据，统计：

```bash
# 查看学习案例
cat data/learning/cases.jsonl | head -20

# 统计验证失败率
grep -c "validation_failed" data/learning/cases.jsonl 2>/dev/null || echo "无数据"
grep -c "reflection_needed" data/learning/cases.jsonl 2>/dev/null || echo "无数据"
```

## 任务6：生成交互体验对比示例

执行3个典型场景，记录完整的处理过程：

### 场景1：简单查询
```
输入: "查询2020年小汽车的CO2排放因子"
记录: Planning输出 → 验证结果 → Skill结果 → 综合回答
```

### 场景2：文件处理
```
输入: 上传轨迹文件 + "计算排放"
记录: 文件分析 → Planning → 追问 → 回答追问 → 计算结果
```

### 场景3：增量修改
```
输入: 在场景2基础上 "把车型改成公交车"
记录: 上下文合并 → 参数更新 → 重新计算
```

## 输出要求

生成 `SUPPLEMENT_ANALYSIS.md`，包含：

1. 完整 System Prompt（附带行号注释标记问题区域）
2. LLM 调用链路图
3. 硬编码规则 JSON
4. 验证层效果统计
5. 3个场景的完整处理日志
6. 你的优化建议（基于实际数据）
