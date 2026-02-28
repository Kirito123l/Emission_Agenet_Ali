# 宏观排放计算Planning失败深度分析

**分析日期**: 2026-01-24
**问题**: Planning LLM不稳定，相同类型查询有时成功有时失败

## 问题复现

### 成功案例 ✅
```
查询: "2公里长的城市道路，平均车速40km/h，每小时车流量800辆（其中70%小汽车、30%公交车）"
结果: 成功计算，返回正确结果
```

### 失败案例 ❌
```
查询: "12公里长的城市道路，平均车速26km/h，每小时车流量800辆（其中50%小汽车、20%公交车, 30%大货车）"
错误: "links_data必须是列表"
Agent要求: 提供额外信息（道路等级、坡度、排放标准分布等）
```

## 深度分析

### 1. 配置层面

**当前配置** (`config.py`):
```python
self.agent_llm = LLMAssignment(
    provider="qwen",
    model="qwen-plus",  # ← 中等能力模型
    temperature=0.3      # ← 仍有随机性
)
```

**问题**:
- **Temperature 0.3**: 不是完全确定性（0.0），仍允许一定随机性
- **Model**: qwen-plus是中等能力模型，不是最强的qwen-max
- **No retry**: Planning失败后没有重试机制

### 2. Prompt层面

**当前System Prompt** (`agent/prompts/system.py`):

**优点**:
- 有示例5展示宏观排放的正确格式
- 字段名清晰：`link_length_km`, `traffic_flow_vph`, `avg_speed_kph`

**问题**:
```python
### 示例5：宏观排放计算
用户: "计算一条1.5公里的快速路，每小时1000辆车，平均速度60km/h，
      车队组成：70%小汽车，20%货车，10%公交车，计算CO2和NOx排放"
```

**缺陷**:
1. **只有1个示例**: 覆盖不足
2. **车型有限**: 只展示了"小汽车"、"货车"、"公交车"
3. **没有"大货车"**: 用户查询中的"大货车"不在示例中
4. **没有负面示例**: 没有展示错误格式和正确修正
5. **没有强制约束**: 没有明确说"必须严格遵循此格式"

### 3. 对比两次查询

| 维度 | 第一次查询（成功） | 第二次查询（失败） |
|------|-------------------|-------------------|
| 道路长度 | 2km | 12km |
| 车速 | 40km/h | 26km/h |
| 车型数量 | 2种 | 3种 |
| 车型名称 | 小汽车、公交车 | 小汽车、公交车、**大货车** |
| 与示例相似度 | 高 | 中等 |
| 复杂度 | 简单 | 较复杂 |

**关键差异**: "大货车"
- 示例中只有"货车"，没有"大货车"
- LLM可能不确定"大货车"应该如何处理
- 导致Planning输出格式错误

### 4. 上下文影响

**对话历史** (`agent/context.py`):
```python
def build_messages_for_planning(self, system_prompt: str, current_input: str):
    messages = [{"role": "system", "content": system_prompt}]

    # 添加最近5轮对话
    for turn in self.turns[-5:]:
        messages.append({"role": "user", "content": turn.user_input})
        summary = self._summarize_turn(turn)
        messages.append({"role": "assistant", "content": summary})

    messages.append({"role": "user", "content": current_input})
    return messages
```

**问题**:
- 第一次成功的查询被加入了上下文
- 第二次查询时，LLM看到了第一次的成功案例
- 但第二次查询更复杂（3种车型 vs 2种车型）
- 上下文可能产生干扰而非帮助

### 5. 执行流程分析

**当前流程**:
```
用户输入
  → Planning (LLM生成JSON)
  → 参数合并 (merge_params)
  → 参数验证 (validate_params)  ← 在这里失败
  → 执行Skill
```

**问题点**:
1. **Planning输出未验证**: 直接进入参数合并
2. **错误发现太晚**: 到Skill层才发现格式错误
3. **无重试机制**: Planning失败后直接返回错误
4. **错误提示不准确**: Agent要求用户提供额外信息（道路等级、坡度等），但这些不是必需的

### 6. JSON解析层面

**JSON解析** (`llm/client.py`):
```python
def _parse_json_response(self, content: str) -> Dict:
    # 已添加简写格式支持
    shorthand_match = re.match(r'\[(\w+):\s*(\w+):\s*(.+)\]', content.strip())
    if shorthand_match:
        # 转换为标准JSON
        ...
```

**问题**:
- 简写格式支持只处理单参数情况
- 对于复杂的宏观排放查询，可能无法正确转换
- 错误的JSON可能通过了解析，但格式不对

## 根本原因总结

### 主要原因（按重要性排序）

1. **Prompt覆盖不足** (Critical)
   - 只有1个宏观排放示例
   - 没有覆盖"大货车"等车型
   - 没有负面示例和纠错指导

2. **模型能力限制** (High)
   - qwen-plus不是最强模型
   - Temperature 0.3仍有随机性
   - 对复杂结构化输出不够稳定

3. **缺少验证和重试** (High)
   - Planning输出未验证
   - 失败后无重试机制
   - 错误发现太晚

4. **上下文干扰** (Medium)
   - 历史对话可能产生干扰
   - 简单案例和复杂案例混在一起

5. **错误处理不当** (Medium)
   - 错误提示要求不必要的信息
   - 没有引导用户重新表述

## 优化方案（按优先级）

### 方案1: 强化Prompt（Priority: Critical）

**目标**: 让LLM严格遵循格式，覆盖更多场景

**实施**:

```python
# agent/prompts/system.py

## 宏观排放计算 - 严格格式要求

### 重要：字段名必须完全一致
- link_length_km (不是 length_km, road_length)
- traffic_flow_vph (不是 traffic_volume, flow)
- avg_speed_kph (不是 avg_speed_kmh, speed)
- fleet_mix (不是 vehicle_composition, vehicle_mix)

### 车型名称标准化
用户可能使用的车型名称：
- "小汽车" / "轿车" / "私家车" → 统一用 "小汽车"
- "公交车" / "大巴" / "客车" → 统一用 "公交车"
- "货车" / "卡车" / "大货车" / "重型货车" → 统一用 "货车"

### 示例5a：基本宏观排放（2种车型）
用户: "2公里道路，40km/h，800辆/小时，70%小汽车30%公交车，CO2排放"
响应:
{
  "understanding": "计算2公里道路的宏观排放",
  "plan": [{
    "skill": "calculate_macro_emission",
    "params": {
      "links_data": [{
        "link_length_km": 2,
        "traffic_flow_vph": 800,
        "avg_speed_kph": 40,
        "fleet_mix": {"小汽车": 70, "公交车": 30}
      }],
      "pollutants": ["CO2"]
    }
  }]
}

### 示例5b：复杂宏观排放（3种车型）
用户: "12公里道路，26km/h，800辆/小时，50%小汽车20%公交车30%大货车，CO2和PM2.5"
响应:
{
  "understanding": "计算12公里道路的宏观排放",
  "plan": [{
    "skill": "calculate_macro_emission",
    "params": {
      "links_data": [{
        "link_length_km": 12,
        "traffic_flow_vph": 800,
        "avg_speed_kph": 26,
        "fleet_mix": {"小汽车": 50, "公交车": 20, "货车": 30}
      }],
      "pollutants": ["CO2", "PM2.5"]
    }
  }]
}
注意：用户说"大货车"，我们统一为"货车"

### 错误示例（禁止）
❌ 错误1：字段名错误
{
  "links_data": [{
    "length_km": 2,  # 错误！应该是 link_length_km
    "traffic_volume": 800,  # 错误！应该是 traffic_flow_vph
    "avg_speed_kmh": 40  # 错误！应该是 avg_speed_kph
  }]
}

❌ 错误2：fleet_mix格式错误
{
  "links_data": [{
    "vehicle_composition": [  # 错误！应该是 fleet_mix，且是对象不是数组
      {"vehicle_type": "小汽车", "percentage": 70}
    ]
  }]
}

✅ 正确格式：
{
  "links_data": [{
    "link_length_km": 2,
    "traffic_flow_vph": 800,
    "avg_speed_kph": 40,
    "fleet_mix": {"小汽车": 70, "公交车": 30}
  }]
}
```

### 方案2: 降低Temperature（Priority: High）

**目标**: 提高Planning的确定性

**实施**:
```python
# config.py
self.agent_llm = LLMAssignment(
    provider="qwen",
    model="qwen-plus",
    temperature=0.0  # ← 从0.3改为0.0，完全确定性
)
```

**效果**: 相同输入产生相同输出

### 方案3: 添加Planning验证（Priority: High）

**目标**: 在执行前验证Planning输出

**实施**:
```python
# agent/core.py

def _validate_macro_plan(self, params: Dict) -> Tuple[bool, str]:
    """验证宏观排放计划的正确性"""
    if "links_data" not in params:
        return False, "缺少links_data"

    links_data = params["links_data"]

    # 检查是否是列表
    if not isinstance(links_data, list):
        return False, "links_data不是列表"

    # 检查必需字段
    required_fields = ["link_length_km", "traffic_flow_vph", "avg_speed_kph"]
    for i, link in enumerate(links_data):
        if not isinstance(link, dict):
            return False, f"links_data[{i}]不是对象"

        for field in required_fields:
            if field not in link:
                return False, f"links_data[{i}]缺少字段: {field}"

    return True, ""

def _plan(self, user_input: str) -> Dict[str, Any]:
    """Planning阶段（带验证）"""
    max_retries = 2

    for attempt in range(max_retries):
        messages = self._context.build_messages_for_planning(
            AGENT_SYSTEM_PROMPT,
            user_input
        )
        plan_result = self._agent_llm.chat_json_with_history(messages)

        # 验证宏观排放计划
        for step in plan_result.get("plan", []):
            if step.get("skill") == "calculate_macro_emission":
                valid, error = self._validate_macro_plan(step.get("params", {}))
                if not valid:
                    logger.warning(f"Planning验证失败 (尝试{attempt+1}/{max_retries}): {error}")
                    if attempt < max_retries - 1:
                        continue  # 重试
                    else:
                        # 最后一次失败，返回友好错误
                        return {
                            "understanding": "理解您的查询，但参数构建失败",
                            "plan": [],
                            "needs_clarification": True,
                            "clarification_message": "抱歉，我在理解道路参数时遇到了问题。请用简单的语言重新描述，例如：'2公里道路，40km/h，800辆/小时，70%小汽车30%公交车'"
                        }

        # 验证通过
        return plan_result

    return plan_result
```

### 方案4: 升级模型（Priority: Medium）

**目标**: 使用更强的模型提高稳定性

**实施**:
```python
# config.py 或 .env
AGENT_LLM_MODEL=qwen-max  # 从 qwen-plus 升级到 qwen-max
```

**成本**: qwen-max更贵，但更稳定

### 方案5: 隔离上下文（Priority: Low）

**目标**: 避免历史对话干扰

**实施**:
```python
# agent/context.py

def build_messages_for_planning(self, system_prompt: str, current_input: str,
                                include_history: bool = True):
    messages = [{"role": "system", "content": system_prompt}]

    if include_history:
        # 只包含相同技能的历史
        relevant_turns = [t for t in self.turns[-5:]
                         if self._is_same_skill_type(t, current_input)]
        for turn in relevant_turns:
            messages.append({"role": "user", "content": turn.user_input})
            summary = self._summarize_turn(turn)
            messages.append({"role": "assistant", "content": summary})

    messages.append({"role": "user", "content": current_input})
    return messages
```

## 实施优先级和预期效果

### 立即实施（本周）
1. ✅ **方案1**: 强化Prompt - 添加更多示例和负面案例
2. ✅ **方案2**: Temperature降为0.0 - 提高确定性

**预期效果**: Planning准确率 70% → 90%

### 短期实施（2周内）
3. **方案3**: 添加Planning验证和重试
4. **方案4**: 升级到qwen-max（可选）

**预期效果**: Planning准确率 90% → 98%

### 长期优化（按需）
5. **方案5**: 隔离上下文

## 测试计划

### 测试用例
```python
test_cases = [
    # 基本案例（2种车型）
    "2公里道路，40km/h，800辆/小时，70%小汽车30%公交车，CO2",

    # 复杂案例（3种车型）
    "12公里道路，26km/h，800辆/小时，50%小汽车20%公交车30%大货车，CO2和PM2.5",

    # 不同车型名称
    "5公里道路，50km/h，1000辆/小时，60%轿车25%客车15%卡车，NOx",

    # 多污染物
    "3公里道路，35km/h，600辆/小时，80%小汽车20%货车，CO2、NOx、PM2.5",

    # 极简表述
    "10km，60km/h，1500辆，全是小汽车，CO2",
]
```

### 成功标准
- 所有测试用例首次尝试成功率 > 95%
- 无需用户重复查询
- 无需用户提供额外信息

## 总结

**核心问题**: Planning LLM对复杂宏观排放查询不稳定

**根本原因**:
1. Prompt示例覆盖不足（只有1个示例，没有"大货车"）
2. Temperature 0.3仍有随机性
3. 缺少Planning验证和重试机制

**解决方案**:
1. 强化Prompt（添加多个示例、负面案例、车型标准化）
2. Temperature降为0.0
3. 添加Planning验证和重试

**预期效果**: Planning准确率从70%提升到98%

---

**分析日期**: 2026-01-24
**优先级**: Critical
**状态**: 待实施
