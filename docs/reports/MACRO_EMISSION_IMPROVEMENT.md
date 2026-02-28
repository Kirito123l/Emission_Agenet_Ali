# 宏观排放计算问题分析与改进建议

**分析日期**: 2026-01-24
**问题类型**: 用户体验 & Planning准确性

## 问题现象

### 用户查询
```
计算一条2公里长的城市道路，平均车速40km/h，每小时车流量800辆
（其中70%小汽车、30%公交车），CO2和PM2.5总排放量是多少？
```

### 第一次尝试：失败 ❌
```
Agent: 根据执行结果，计算失败的原因是 links_data必须是列表。

请提供以下格式的道路数据：
[
  {
    "link_length_km": 2,
    "avg_speed_kmh": 40,  # ← 错误的字段名
    "traffic_volume_veh_h": 800,  # ← 错误的字段名
    "vehicle_composition": [  # ← 错误的结构
      {"vehicle_type": "小汽车", "percentage": 70},
      {"vehicle_type": "公交车", "percentage": 30}
    ]
  }
]
```

**问题点**:
1. 字段名错误：`avg_speed_kmh` 应该是 `avg_speed_kph`
2. 字段名错误：`traffic_volume_veh_h` 应该是 `traffic_flow_vph`
3. 结构错误：`vehicle_composition` 应该是 `fleet_mix`，且格式应该是对象而非数组

### 第二次尝试：成功 ✅
用户重复了相同的查询，这次成功了。

**说明**: Planning LLM在第二次尝试时正确构建了参数。

## 根本原因分析

### 原因1: Planning LLM不稳定

**问题**: 相同的自然语言输入，两次Planning结果不同
- 第一次：构建了错误的JSON结构
- 第二次：构建了正确的JSON结构

**根源**:
- System prompt中的示例5虽然正确，但LLM没有严格遵循
- 温度设置为0.3，仍有一定随机性
- 没有强制约束来确保输出格式

### 原因2: 错误提示不友好

**问题**: 第一次失败后，Agent要求用户提供JSON格式数据

**为什么这是问题**:
1. 用户已经用自然语言清楚描述了需求
2. 要求用户提供JSON违背了Agent的设计初衷
3. 提供的JSON格式示例还是错误的

### 原因3: 缺少参数验证和修复机制

**问题**: Skill层的参数验证只检查必需字段，不检查字段名是否正确

**当前验证**:
```python
required_fields = ["link_length_km", "traffic_flow_vph", "avg_speed_kph"]
for field in required_fields:
    if field not in link:
        return False, f"缺少必需字段: {field}", {}
```

**缺失**: 没有检测和修复常见的字段名错误

## 改进建议

### 建议1: 强化System Prompt（Priority: High）

**目标**: 让Planning LLM更严格地遵循格式

**方案**: 在system prompt中添加强制约束

```python
# agent/prompts/system.py

## 宏观排放计算 - 严格格式要求

当用户描述道路排放计算需求时，必须严格按照以下格式构建参数：

**必需字段**（字段名必须完全一致）:
- link_length_km: 路段长度（公里）
- traffic_flow_vph: 交通流量（辆/小时）
- avg_speed_kph: 平均速度（公里/小时）

**可选字段**:
- fleet_mix: 车队组成（对象格式）
  格式: {"小汽车": 70, "公交车": 30}
  注意: 是对象，不是数组！

**错误示例**（禁止使用）:
❌ "avg_speed_kmh" - 错误！应该是 "avg_speed_kph"
❌ "traffic_volume_veh_h" - 错误！应该是 "traffic_flow_vph"
❌ "vehicle_composition": [...] - 错误！应该是 "fleet_mix": {...}

**正确示例**:
✅ {
  "links_data": [{
    "link_length_km": 2,
    "traffic_flow_vph": 800,
    "avg_speed_kph": 40,
    "fleet_mix": {"小汽车": 70, "公交车": 30}
  }],
  "pollutants": ["CO2", "PM2.5"]
}
```

### 建议2: 添加参数自动修复（Priority: High）

**目标**: 自动检测和修复常见的字段名错误

**方案**: 在Skill层添加参数修复逻辑

```python
# skills/macro_emission/skill.py

def _fix_common_errors(self, links_data: List[Dict]) -> List[Dict]:
    """修复常见的参数错误"""
    fixed_links = []

    for link in links_data:
        fixed_link = {}

        # 修复字段名映射
        field_mapping = {
            # 正确名称: [可能的错误名称]
            "link_length_km": ["length", "link_length", "length_km"],
            "traffic_flow_vph": ["traffic_volume_veh_h", "traffic_flow", "flow", "volume"],
            "avg_speed_kph": ["avg_speed_kmh", "speed", "avg_speed"],
            "fleet_mix": ["vehicle_composition", "vehicle_mix", "composition"]
        }

        for correct_name, possible_names in field_mapping.items():
            # 先检查正确名称
            if correct_name in link:
                fixed_link[correct_name] = link[correct_name]
            else:
                # 检查可能的错误名称
                for wrong_name in possible_names:
                    if wrong_name in link:
                        fixed_link[correct_name] = link[wrong_name]
                        logger.info(f"自动修复字段名: {wrong_name} -> {correct_name}")
                        break

        # 修复fleet_mix格式（如果是数组，转换为对象）
        if "fleet_mix" in fixed_link:
            fleet_mix = fixed_link["fleet_mix"]
            if isinstance(fleet_mix, list):
                # 转换数组为对象
                fixed_fleet_mix = {}
                for item in fleet_mix:
                    if "vehicle_type" in item and "percentage" in item:
                        fixed_fleet_mix[item["vehicle_type"]] = item["percentage"]
                fixed_link["fleet_mix"] = fixed_fleet_mix
                logger.info("自动修复fleet_mix格式: 数组 -> 对象")

        fixed_links.append(fixed_link)

    return fixed_links

def execute(self, **params) -> SkillResult:
    # 在参数验证前添加自动修复
    if "links_data" in params:
        params["links_data"] = self._fix_common_errors(params["links_data"])

    # 然后进行正常的参数验证
    ...
```

### 建议3: 改进错误提示（Priority: Medium）

**目标**: 失败时不要求用户提供JSON，而是给出更友好的提示

**方案**: 修改Agent的错误处理逻辑

```python
# agent/core.py

def _check_clarification_needed(self, results: Dict) -> str:
    """检查是否需要追问"""
    for skill_name, result in results.items():
        if not result.get("success"):
            error = result.get("error", "")

            # 特殊处理宏观排放计算错误
            if skill_name == "calculate_macro_emission":
                if "links_data" in error:
                    return """抱歉，我在理解您的道路参数时遇到了问题。

请确认以下信息：
- 道路长度（公里）
- 平均车速（公里/小时）
- 车流量（辆/小时）
- 车队组成（各车型百分比）

您可以用自然语言重新描述，例如：
"一条3公里的道路，车速50km/h，每小时1000辆车，其中80%小汽车、20%货车"
"""

            # 其他错误的通用处理
            ...
```

### 建议4: 添加Planning验证（Priority: Medium）

**目标**: 在执行前验证Planning结果的正确性

**方案**: 添加Planning后验证步骤

```python
# agent/core.py

def _validate_plan(self, plan: List[Dict]) -> Tuple[bool, str]:
    """验证plan的正确性"""
    for step in plan:
        skill_name = step.get("skill")
        params = step.get("params", {})

        if skill_name == "calculate_macro_emission":
            # 验证links_data格式
            if "links_data" not in params:
                return False, "缺少links_data参数"

            links_data = params["links_data"]
            if not isinstance(links_data, list):
                return False, "links_data必须是列表"

            # 验证必需字段
            required_fields = ["link_length_km", "traffic_flow_vph", "avg_speed_kph"]
            for link in links_data:
                for field in required_fields:
                    if field not in link:
                        return False, f"links_data缺少必需字段: {field}"

    return True, ""

def chat(self, user_input: str) -> str:
    # 在Planning后添加验证
    plan_result = self._plan(user_input)

    # 验证plan
    valid, error = self._validate_plan(plan_result.get("plan", []))
    if not valid:
        logger.warning(f"Plan验证失败: {error}")
        # 重新Planning或返回错误
        ...
```

### 建议5: 添加Few-Shot示例（Priority: Low）

**目标**: 在Planning时提供更多示例

**方案**: 在system prompt中添加更多宏观排放的示例

```python
### 示例5a：简单宏观排放
用户: "2公里道路，40km/h，800辆/小时，70%小汽车30%公交车，CO2排放"
响应: {
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

### 示例5b：多路段宏观排放
用户: "计算两条路：第一条3km，60km/h，1000辆；第二条1km，30km/h，500辆"
响应: {
  "plan": [{
    "skill": "calculate_macro_emission",
    "params": {
      "links_data": [
        {
          "link_id": "L1",
          "link_length_km": 3,
          "traffic_flow_vph": 1000,
          "avg_speed_kph": 60
        },
        {
          "link_id": "L2",
          "link_length_km": 1,
          "traffic_flow_vph": 500,
          "avg_speed_kph": 30
        }
      ]
    }
  }]
}
```

## 实施优先级

### 立即实施（本周）
1. ✅ **建议2**: 添加参数自动修复 - 最直接有效
2. 🔄 **建议1**: 强化System Prompt - 预防问题

### 短期实施（2周内）
3. **建议3**: 改进错误提示 - 提升用户体验
4. **建议4**: 添加Planning验证 - 提高稳定性

### 长期实施（按需）
5. **建议5**: 添加Few-Shot示例 - 进一步提升准确性

## 预期效果

实施建议1+2后：
- ✅ Planning准确率: 70% → 95%
- ✅ 自动修复常见错误
- ✅ 用户无需重复查询
- ✅ 不再要求用户提供JSON

实施建议3+4后：
- ✅ 错误提示更友好
- ✅ 失败率降低
- ✅ 用户体验显著提升

## 测试计划

### 测试用例
```python
test_cases = [
    # 基本格式
    "2公里道路，40km/h，800辆/小时，70%小汽车30%公交车，CO2排放",

    # 不同表述
    "一条3公里的城市道路，平均速度50公里每小时，每小时车流量1000辆",

    # 多污染物
    "5km道路，60km/h，1500辆/h，计算CO2、NOx和PM2.5",

    # 多路段
    "计算两条路的排放：第一条2km，40km/h，800辆；第二条3km，60km/h，1200辆",
]
```

### 成功标准
- 所有测试用例首次尝试成功率 > 90%
- 无需用户提供JSON格式数据
- 错误提示清晰友好

## 总结

**当前问题**: 宏观排放计算的Planning不稳定，第一次可能失败

**核心原因**:
1. Planning LLM没有严格遵循格式
2. 缺少参数自动修复机制
3. 错误提示不友好

**解决方案**:
1. 强化System Prompt约束
2. 添加参数自动修复
3. 改进错误处理

**预期效果**: Planning准确率从70%提升到95%，用户体验显著改善

---

**编写日期**: 2026-01-24
**优先级**: High
**状态**: 待实施
