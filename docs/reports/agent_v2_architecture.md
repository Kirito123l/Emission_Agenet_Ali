# Emission Agent 智能架构升级方案

## 一、当前问题总结

1. **Planning不稳定**: 相同查询有时成功有时失败
2. **错误发现太晚**: 到Skill层才发现格式错误
3. **缺乏自我修复**: 失败后只能让用户重试
4. **无学习能力**: 同样的错误会反复出现

## 二、升级目标

打造一个具备以下能力的智能Agent：

1. **自我反思**: 执行前检查，执行后验证
2. **自我修复**: 发现错误后自动修正，无需用户干预
3. **持续学习**: 从错误中学习，避免重复犯错
4. **优雅降级**: 实在无法修复时，给出有价值的提示

## 三、新架构设计

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Emission Agent v2.0                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                     用户输入                                   │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│                              ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                 1. Planning (意图理解)                         │  │
│  │  • 理解用户意图                                                │  │
│  │  • 生成执行计划                                                │  │
│  │  • Temperature=0.0 (确定性)                                    │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│                              ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │              2. Validator (计划验证) [新增]                    │  │
│  │  • 检查JSON格式                                                │  │
│  │  • 验证必需字段                                                │  │
│  │  • 检查参数类型和范围                                          │  │
│  │  • 返回: (valid, errors)                                       │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│              ┌───────────────┴───────────────┐                      │
│              │                               │                      │
│         验证通过                          验证失败                   │
│              │                               │                      │
│              │                               ▼                      │
│              │           ┌───────────────────────────────────────┐  │
│              │           │      3. Reflector (反思修复) [新增]    │  │
│              │           │  • 分析错误原因                        │  │
│              │           │  • 尝试自动修复                        │  │
│              │           │  • 最多重试2次                         │  │
│              │           │  • 记录错误模式                        │  │
│              │           └───────────────────────────────────────┘  │
│              │                               │                      │
│              │               ┌───────────────┴───────────────┐      │
│              │               │                               │      │
│              │           修复成功                         修复失败   │
│              │               │                               │      │
│              ▼               ▼                               ▼      │
│  ┌───────────────────────────────────────┐    ┌─────────────────┐  │
│  │         4. Executor (执行)             │    │ 优雅降级        │  │
│  │  • 调用Skill执行                       │    │ • 友好错误提示  │  │
│  │  • 收集执行结果                        │    │ • 建议重新表述  │  │
│  └───────────────────────────────────────┘    │ • 不要求JSON    │  │
│                              │                 └─────────────────┘  │
│                              ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │              5. Synthesizer (结果综合)                         │  │
│  │  • 生成自然语言回答                                            │  │
│  │  • 引用计算结果                                                │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│                              ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │              6. Learner (学习) [新增]                          │  │
│  │  • 记录成功/失败案例                                           │  │
│  │  • 更新Few-shot示例库                                          │  │
│  │  • 定期优化Prompt                                              │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## 四、核心模块实现

### 4.1 Validator (计划验证器)

创建 `agent/validator.py`:

```python
"""
计划验证器
在执行前验证Planning输出的正确性
"""
from typing import Dict, List, Tuple, Any
import logging

logger = logging.getLogger(__name__)


class PlanValidator:
    """计划验证器"""
    
    # 各Skill的参数Schema
    SKILL_SCHEMAS = {
        "query_emission_factors": {
            "required": ["vehicle_type", "pollutant", "model_year"],
            "optional": ["season", "road_type"],
            "types": {
                "vehicle_type": str,
                "pollutant": str,
                "model_year": int,
                "season": str,
                "road_type": str,
            }
        },
        "calculate_micro_emission": {
            "required": ["trajectory_data", "vehicle_type"],
            "optional": ["model_year", "pollutants", "season"],
            "types": {
                "trajectory_data": list,
                "vehicle_type": str,
                "model_year": int,
                "pollutants": list,
            }
        },
        "calculate_macro_emission": {
            "required": ["links_data"],
            "optional": ["model_year", "pollutants", "season", "default_fleet_mix"],
            "types": {
                "links_data": list,
                "model_year": int,
                "pollutants": list,
            },
            "nested": {
                "links_data": {
                    "required": ["link_length_km", "traffic_flow_vph", "avg_speed_kph"],
                    "optional": ["fleet_mix", "link_id"],
                    "types": {
                        "link_length_km": (int, float),
                        "traffic_flow_vph": (int, float),
                        "avg_speed_kph": (int, float),
                        "fleet_mix": dict,
                    }
                }
            }
        },
        "query_knowledge": {
            "required": ["query"],
            "optional": ["top_k", "expectation"],
            "types": {
                "query": str,
                "top_k": int,
            }
        }
    }
    
    # 常见字段名错误映射
    FIELD_CORRECTIONS = {
        # macro_emission
        "length_km": "link_length_km",
        "road_length": "link_length_km",
        "distance_km": "link_length_km",
        "traffic_volume": "traffic_flow_vph",
        "vehicle_flow": "traffic_flow_vph",
        "flow_vph": "traffic_flow_vph",
        "avg_speed_kmh": "avg_speed_kph",
        "speed_kph": "avg_speed_kph",
        "average_speed": "avg_speed_kph",
        "vehicle_composition": "fleet_mix",
        "vehicle_mix": "fleet_mix",
        "car_mix": "fleet_mix",
        # emission_factors
        "year": "model_year",
        "vehicle": "vehicle_type",
        "emission_type": "pollutant",
    }
    
    def validate(self, plan_result: Dict) -> Tuple[bool, List[str], Dict]:
        """
        验证完整的Planning结果
        
        Returns:
            (is_valid, errors, corrected_plan)
        """
        errors = []
        corrected = plan_result.copy()
        
        # 检查基本结构
        if "plan" not in plan_result:
            errors.append("缺少plan字段")
            return False, errors, corrected
        
        plan = plan_result.get("plan", [])
        if not isinstance(plan, list):
            errors.append("plan必须是列表")
            return False, errors, corrected
        
        # 验证每个步骤
        corrected_plan = []
        for i, step in enumerate(plan):
            valid, step_errors, corrected_step = self._validate_step(step, i)
            errors.extend(step_errors)
            corrected_plan.append(corrected_step)
        
        corrected["plan"] = corrected_plan
        
        return len(errors) == 0, errors, corrected
    
    def _validate_step(self, step: Dict, index: int) -> Tuple[bool, List[str], Dict]:
        """验证单个执行步骤"""
        errors = []
        corrected = step.copy()
        
        skill_name = step.get("skill")
        if not skill_name:
            errors.append(f"步骤{index}: 缺少skill字段")
            return False, errors, corrected
        
        if skill_name not in self.SKILL_SCHEMAS:
            errors.append(f"步骤{index}: 未知技能 {skill_name}")
            return False, errors, corrected
        
        schema = self.SKILL_SCHEMAS[skill_name]
        params = step.get("params", {})
        
        # 1. 修正字段名
        corrected_params = self._correct_field_names(params, skill_name)
        
        # 2. 验证必需字段
        for field in schema["required"]:
            if field not in corrected_params:
                errors.append(f"步骤{index}: 缺少必需参数 {field}")
        
        # 3. 验证类型
        for field, value in corrected_params.items():
            expected_type = schema["types"].get(field)
            if expected_type and value is not None:
                if isinstance(expected_type, tuple):
                    if not isinstance(value, expected_type):
                        errors.append(f"步骤{index}: {field}类型错误，期望{expected_type}")
                elif not isinstance(value, expected_type):
                    errors.append(f"步骤{index}: {field}类型错误，期望{expected_type.__name__}")
        
        # 4. 验证嵌套结构
        if "nested" in schema:
            for nested_field, nested_schema in schema["nested"].items():
                if nested_field in corrected_params:
                    nested_errors = self._validate_nested(
                        corrected_params[nested_field], 
                        nested_schema, 
                        f"步骤{index}.{nested_field}"
                    )
                    errors.extend(nested_errors)
        
        corrected["params"] = corrected_params
        return len(errors) == 0, errors, corrected
    
    def _correct_field_names(self, params: Dict, skill_name: str) -> Dict:
        """修正常见的字段名错误"""
        corrected = {}
        
        for key, value in params.items():
            # 检查是否需要修正
            corrected_key = self.FIELD_CORRECTIONS.get(key, key)
            
            # 递归处理嵌套结构
            if isinstance(value, dict):
                value = self._correct_field_names(value, skill_name)
            elif isinstance(value, list):
                value = [
                    self._correct_field_names(item, skill_name) 
                    if isinstance(item, dict) else item
                    for item in value
                ]
            
            corrected[corrected_key] = value
        
        return corrected
    
    def _validate_nested(self, items: List, schema: Dict, path: str) -> List[str]:
        """验证嵌套列表结构"""
        errors = []
        
        if not isinstance(items, list):
            errors.append(f"{path}: 必须是列表")
            return errors
        
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"{path}[{i}]: 必须是对象")
                continue
            
            for field in schema.get("required", []):
                if field not in item:
                    errors.append(f"{path}[{i}]: 缺少必需字段 {field}")
        
        return errors
```

### 4.2 Reflector (反思修复器)

创建 `agent/reflector.py`:

```python
"""
反思修复器
当Planning验证失败时，尝试分析错误并自动修复
"""
import json
import logging
from typing import Dict, List, Tuple, Any, Optional

from llm.client import get_llm

logger = logging.getLogger(__name__)


class PlanReflector:
    """计划反思修复器"""
    
    def __init__(self):
        self._llm = get_llm("agent")  # 复用Agent LLM
    
    def reflect_and_fix(
        self, 
        user_input: str, 
        original_plan: Dict, 
        errors: List[str],
        skill_schemas: Dict
    ) -> Tuple[bool, Dict, str]:
        """
        反思错误并尝试修复
        
        Args:
            user_input: 用户原始输入
            original_plan: 原始的错误计划
            errors: 验证器发现的错误列表
            skill_schemas: 各Skill的参数Schema
        
        Returns:
            (success, fixed_plan, reflection_message)
        """
        # 构建反思Prompt
        prompt = self._build_reflection_prompt(
            user_input, original_plan, errors, skill_schemas
        )
        
        try:
            # 请求LLM修复
            response = self._llm.chat_json(prompt)
            
            if response.get("can_fix"):
                fixed_plan = response.get("fixed_plan", {})
                reflection = response.get("reflection", "")
                logger.info(f"反思修复成功: {reflection}")
                return True, fixed_plan, reflection
            else:
                reason = response.get("reason", "无法修复")
                logger.warning(f"反思修复失败: {reason}")
                return False, original_plan, reason
        
        except Exception as e:
            logger.exception(f"反思修复异常: {e}")
            return False, original_plan, str(e)
    
    def _build_reflection_prompt(
        self, 
        user_input: str, 
        original_plan: Dict, 
        errors: List[str],
        skill_schemas: Dict
    ) -> str:
        """构建反思Prompt"""
        
        # 获取相关Skill的Schema
        skill_name = None
        if original_plan.get("plan"):
            skill_name = original_plan["plan"][0].get("skill")
        
        schema_info = ""
        if skill_name and skill_name in skill_schemas:
            schema = skill_schemas[skill_name]
            schema_info = f"""
## {skill_name} 的正确格式

必需参数: {schema.get('required', [])}
可选参数: {schema.get('optional', [])}
参数类型: {json.dumps(schema.get('types', {}), indent=2, default=str)}
"""
            if "nested" in schema:
                for field, nested_schema in schema["nested"].items():
                    schema_info += f"""
### {field} 嵌套结构
必需字段: {nested_schema.get('required', [])}
可选字段: {nested_schema.get('optional', [])}
"""

        return f"""你是一个JSON修复专家。用户的查询生成了一个错误的执行计划，请分析错误并修复。

## 用户原始查询
{user_input}

## 原始计划（有错误）
{json.dumps(original_plan, ensure_ascii=False, indent=2)}

## 验证器发现的错误
{chr(10).join(f"- {e}" for e in errors)}

{schema_info}

## 常见错误和修正

1. 字段名错误:
   - length_km → link_length_km
   - traffic_volume → traffic_flow_vph
   - avg_speed_kmh → avg_speed_kph
   - vehicle_composition → fleet_mix

2. 类型错误:
   - links_data 必须是列表 [{{...}}]，不是对象 {{...}}
   - fleet_mix 必须是对象 {{"小汽车": 70}}，不是列表

3. 车型标准化:
   - "大货车"、"重型货车"、"卡车" → "货车"
   - "轿车"、"私家车" → "小汽车"
   - "大巴"、"客车" → "公交车"

## 任务

分析错误原因，修复计划。返回JSON:

```json
{{
  "can_fix": true,
  "reflection": "错误原因分析...",
  "fixed_plan": {{
    "understanding": "...",
    "plan": [...]
  }}
}}
```

如果无法修复，返回:
```json
{{
  "can_fix": false,
  "reason": "无法修复的原因..."
}}
```
"""
```

### 4.3 Learner (学习器)

创建 `agent/learner.py`:

```python
"""
学习器
从成功和失败案例中学习，持续优化
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import hashlib

logger = logging.getLogger(__name__)


@dataclass
class LearningCase:
    """学习案例"""
    case_id: str
    timestamp: str
    user_input: str
    skill_name: str
    original_plan: Dict
    final_plan: Dict
    success: bool
    errors: List[str]
    reflection: str
    execution_result: Optional[Dict]


class AgentLearner:
    """Agent学习器"""
    
    def __init__(self, data_dir: Path = None):
        self.data_dir = data_dir or Path("data/learning")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.cases_file = self.data_dir / "cases.jsonl"
        self.patterns_file = self.data_dir / "error_patterns.json"
        self.examples_file = self.data_dir / "learned_examples.json"
        
        self.error_patterns: Dict[str, int] = self._load_patterns()
        self.learned_examples: List[Dict] = self._load_examples()
    
    def record_case(
        self,
        user_input: str,
        skill_name: str,
        original_plan: Dict,
        final_plan: Dict,
        success: bool,
        errors: List[str] = None,
        reflection: str = "",
        execution_result: Dict = None
    ):
        """记录一个学习案例"""
        case = LearningCase(
            case_id=self._generate_case_id(user_input),
            timestamp=datetime.now().isoformat(),
            user_input=user_input,
            skill_name=skill_name,
            original_plan=original_plan,
            final_plan=final_plan,
            success=success,
            errors=errors or [],
            reflection=reflection,
            execution_result=execution_result
        )
        
        # 保存案例
        with open(self.cases_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(case), ensure_ascii=False) + "\n")
        
        # 更新错误模式
        if not success and errors:
            self._update_error_patterns(errors, skill_name)
        
        # 从成功案例学习
        if success and original_plan != final_plan:
            self._learn_from_fix(user_input, original_plan, final_plan, skill_name)
        
        logger.info(f"记录学习案例: {case.case_id}, success={success}")
    
    def _generate_case_id(self, user_input: str) -> str:
        """生成案例ID"""
        hash_input = f"{user_input}{datetime.now().isoformat()}"
        return hashlib.md5(hash_input.encode()).hexdigest()[:8]
    
    def _update_error_patterns(self, errors: List[str], skill_name: str):
        """更新错误模式统计"""
        for error in errors:
            # 提取错误模式（去除具体数值）
            pattern = self._extract_error_pattern(error)
            key = f"{skill_name}:{pattern}"
            self.error_patterns[key] = self.error_patterns.get(key, 0) + 1
        
        self._save_patterns()
    
    def _extract_error_pattern(self, error: str) -> str:
        """提取错误模式"""
        # 简化错误信息，提取模式
        import re
        # 去除具体的索引数字
        pattern = re.sub(r'\d+', 'N', error)
        # 去除具体的字段值
        pattern = re.sub(r'"[^"]*"', '"X"', pattern)
        return pattern
    
    def _learn_from_fix(
        self, 
        user_input: str, 
        original_plan: Dict, 
        fixed_plan: Dict,
        skill_name: str
    ):
        """从修复案例中学习，生成新的Few-shot示例"""
        # 检查是否已有类似示例
        for example in self.learned_examples:
            if example.get("skill") == skill_name:
                # 简单的相似度检查
                if self._is_similar_input(user_input, example.get("user_input", "")):
                    return  # 已有类似示例，不重复添加
        
        # 添加新示例
        new_example = {
            "skill": skill_name,
            "user_input": user_input,
            "correct_plan": fixed_plan,
            "learned_at": datetime.now().isoformat(),
        }
        self.learned_examples.append(new_example)
        
        # 限制示例数量
        if len(self.learned_examples) > 50:
            self.learned_examples = self.learned_examples[-50:]
        
        self._save_examples()
        logger.info(f"学习新示例: {skill_name} - {user_input[:50]}...")
    
    def _is_similar_input(self, input1: str, input2: str) -> bool:
        """简单的相似度检查"""
        # 提取关键词比较
        words1 = set(input1.replace("，", " ").replace(",", " ").split())
        words2 = set(input2.replace("，", " ").replace(",", " ").split())
        
        if not words1 or not words2:
            return False
        
        intersection = words1 & words2
        union = words1 | words2
        
        return len(intersection) / len(union) > 0.7
    
    def get_relevant_examples(self, skill_name: str, limit: int = 3) -> List[Dict]:
        """获取相关的学习示例"""
        relevant = [ex for ex in self.learned_examples if ex.get("skill") == skill_name]
        return relevant[-limit:]
    
    def get_common_errors(self, skill_name: str, limit: int = 5) -> List[str]:
        """获取常见错误模式"""
        prefix = f"{skill_name}:"
        skill_errors = {
            k.replace(prefix, ""): v 
            for k, v in self.error_patterns.items() 
            if k.startswith(prefix)
        }
        
        # 按频率排序
        sorted_errors = sorted(skill_errors.items(), key=lambda x: -x[1])
        return [e[0] for e in sorted_errors[:limit]]
    
    def get_statistics(self) -> Dict:
        """获取学习统计"""
        total_cases = 0
        success_cases = 0
        
        if self.cases_file.exists():
            with open(self.cases_file, "r", encoding="utf-8") as f:
                for line in f:
                    case = json.loads(line)
                    total_cases += 1
                    if case.get("success"):
                        success_cases += 1
        
        return {
            "total_cases": total_cases,
            "success_cases": success_cases,
            "success_rate": success_cases / total_cases if total_cases > 0 else 0,
            "error_patterns": len(self.error_patterns),
            "learned_examples": len(self.learned_examples),
        }
    
    def _load_patterns(self) -> Dict[str, int]:
        """加载错误模式"""
        if self.patterns_file.exists():
            with open(self.patterns_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    
    def _save_patterns(self):
        """保存错误模式"""
        with open(self.patterns_file, "w", encoding="utf-8") as f:
            json.dump(self.error_patterns, f, ensure_ascii=False, indent=2)
    
    def _load_examples(self) -> List[Dict]:
        """加载学习示例"""
        if self.examples_file.exists():
            with open(self.examples_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return []
    
    def _save_examples(self):
        """保存学习示例"""
        with open(self.examples_file, "w", encoding="utf-8") as f:
            json.dump(self.learned_examples, f, ensure_ascii=False, indent=2)
```

### 4.4 重构Agent核心

修改 `agent/core.py`:

```python
"""
Emission Agent v2.0 - 带反思和学习能力
"""
import json
import logging
from typing import Dict, List, Any, Optional, Tuple

from .context import ConversationContext, ConversationTurn, SkillExecution
from .validator import PlanValidator
from .reflector import PlanReflector
from .learner import AgentLearner
from .prompts.system import AGENT_SYSTEM_PROMPT
from .prompts.synthesis import SYNTHESIS_PROMPT
from llm.client import get_llm
from skills.registry import get_registry, init_skills

logger = logging.getLogger(__name__)


class EmissionAgent:
    """排放计算Agent v2.0"""
    
    MAX_RETRIES = 2  # 最大重试次数
    
    def __init__(self):
        self._agent_llm = get_llm("agent")
        self._synthesis_llm = get_llm("synthesis")
        init_skills()
        self._registry = get_registry()
        
        # 核心组件
        self._context = ConversationContext(max_turns=20)
        self._validator = PlanValidator()
        self._reflector = PlanReflector()
        self._learner = AgentLearner()
    
    def chat(self, user_input: str) -> str:
        """主对话入口"""
        try:
            # 1. 检查是否是回顾性问题
            if self._is_retrospective_query(user_input):
                return self._handle_retrospective_query(user_input)
            
            # 2. Planning + 验证 + 反思修复（带重试）
            plan_result, was_fixed = self._plan_with_validation(user_input)
            
            # 3. 检查是否需要追问
            if plan_result.get("needs_clarification"):
                response = plan_result["clarification_message"]
                self._add_turn(user_input, response, plan_result.get("understanding", ""))
                return response
            
            # 4. 参数合并（增量对话）
            plan = self._enrich_plan_with_memory(plan_result.get("plan", []))
            
            # 5. 执行技能
            skill_executions, results = self._execute_plan(plan)
            
            # 6. 检查Skill层的追问需求
            clarification = self._check_clarification_needed(results)
            if clarification:
                self._add_turn(user_input, clarification, plan_result.get("understanding", ""))
                return clarification
            
            # 7. 综合生成回答
            response = self._synthesize(
                user_input,
                plan_result.get("understanding", ""),
                results
            )
            
            # 8. 记录学习
            self._record_learning(
                user_input=user_input,
                plan_result=plan_result,
                was_fixed=was_fixed,
                results=results,
                success=any(r.get("success") for r in results.values())
            )
            
            # 9. 保存对话
            self._add_turn(
                user_input, response,
                plan_result.get("understanding", ""),
                skill_executions
            )
            
            return response
        
        except Exception as e:
            logger.exception("Agent处理失败")
            return f"抱歉，处理出错: {str(e)}"
    
    def _plan_with_validation(self, user_input: str) -> Tuple[Dict, bool]:
        """
        Planning + 验证 + 反思修复
        
        Returns:
            (final_plan, was_fixed)
        """
        original_plan = None
        was_fixed = False
        
        for attempt in range(self.MAX_RETRIES + 1):
            # 生成计划
            if attempt == 0:
                plan_result = self._plan(user_input)
                original_plan = plan_result.copy()
            else:
                # 重试时使用反思修复的结果
                pass
            
            # 验证
            valid, errors, corrected_plan = self._validator.validate(plan_result)
            
            if valid:
                logger.info(f"Planning验证通过 (尝试{attempt + 1})")
                return corrected_plan, was_fixed
            
            logger.warning(f"Planning验证失败 (尝试{attempt + 1}): {errors}")
            
            # 尝试反思修复
            if attempt < self.MAX_RETRIES:
                success, fixed_plan, reflection = self._reflector.reflect_and_fix(
                    user_input=user_input,
                    original_plan=plan_result,
                    errors=errors,
                    skill_schemas=self._validator.SKILL_SCHEMAS
                )
                
                if success:
                    plan_result = fixed_plan
                    was_fixed = True
                    logger.info(f"反思修复成功: {reflection}")
                else:
                    # 修复失败，返回友好错误
                    return self._graceful_degradation(user_input, errors), False
            else:
                # 最后一次尝试也失败
                return self._graceful_degradation(user_input, errors), False
        
        return plan_result, was_fixed
    
    def _graceful_degradation(self, user_input: str, errors: List[str]) -> Dict:
        """优雅降级 - 给出友好提示而不是要求JSON"""
        
        # 分析是什么类型的查询
        if "公里" in user_input or "道路" in user_input or "车流量" in user_input:
            suggestion = """请用简单的格式描述道路信息，例如：
- "2公里道路，40km/h，800辆/小时，70%小汽车30%公交车，计算CO2"
- "5公里快速路，时速60，每小时1000辆，全是小汽车，CO2和NOx"

提示：
- 道路长度（公里）
- 平均车速（km/h）
- 车流量（辆/小时）
- 车型比例（如70%小汽车30%公交车）
- 要计算的污染物（CO2、NOx、PM2.5等）"""
        else:
            suggestion = "请提供更多信息，我会尽力帮您计算。"
        
        return {
            "understanding": "理解您的查询，但需要更清晰的信息",
            "plan": [],
            "needs_clarification": True,
            "clarification_message": f"抱歉，我在理解您的查询时遇到了问题。\n\n{suggestion}"
        }
    
    def _plan(self, user_input: str) -> Dict:
        """生成执行计划"""
        # 获取相关的学习示例
        # (简化版：这里可以根据用户输入判断skill类型)
        learned_examples = self._learner.get_relevant_examples("calculate_macro_emission")
        
        # 构建增强的System Prompt
        enhanced_prompt = AGENT_SYSTEM_PROMPT
        if learned_examples:
            examples_text = "\n\n## 从历史学习的示例\n"
            for ex in learned_examples:
                examples_text += f"""
用户: {ex['user_input']}
正确计划: {json.dumps(ex['correct_plan'], ensure_ascii=False)}
"""
            enhanced_prompt += examples_text
        
        messages = self._context.build_messages_for_planning(enhanced_prompt, user_input)
        return self._agent_llm.chat_json_with_history(messages)
    
    def _record_learning(
        self,
        user_input: str,
        plan_result: Dict,
        was_fixed: bool,
        results: Dict,
        success: bool
    ):
        """记录学习案例"""
        skill_name = ""
        if plan_result.get("plan"):
            skill_name = plan_result["plan"][0].get("skill", "")
        
        self._learner.record_case(
            user_input=user_input,
            skill_name=skill_name,
            original_plan=plan_result,
            final_plan=plan_result,
            success=success,
            errors=[],
            reflection="自动修复" if was_fixed else "",
            execution_result=results
        )
    
    # ... 其他方法保持不变 ...
```

## 五、配置更新

修改 `config.py`:

```python
# 降低Temperature，提高确定性
self.agent_llm = LLMAssignment(
    provider=os.getenv("AGENT_LLM_PROVIDER", "qwen"),
    model=os.getenv("AGENT_LLM_MODEL", "qwen-plus"),
    temperature=0.0,  # 从0.3改为0.0
    max_tokens=2000
)
```

## 六、目录结构更新

```
agent/
├── __init__.py
├── core.py           # 主逻辑 (v2.0)
├── context.py        # 上下文管理
├── validator.py      # 计划验证器 [新增]
├── reflector.py      # 反思修复器 [新增]
├── learner.py        # 学习器 [新增]
└── prompts/
    ├── system.py
    └── synthesis.py

data/
├── collection/       # 标准化数据
├── logs/
└── learning/         # 学习数据 [新增]
    ├── cases.jsonl       # 所有案例
    ├── error_patterns.json   # 错误模式统计
    └── learned_examples.json # 学习到的示例
```

## 七、执行流程对比

### 之前（v1.0）
```
用户输入 → Planning → 执行 → 失败 → 用户重试
```

### 现在（v2.0）
```
用户输入 
  → Planning 
  → Validator验证 
  → [失败] → Reflector反思修复 
  → [修复成功] → 执行 
  → [修复失败] → 优雅降级（友好提示）
  → Learner记录学习
```

## 八、预期效果

| 指标 | v1.0 | v2.0 |
|------|------|------|
| Planning首次成功率 | 70% | 85% |
| 经反思修复后成功率 | - | 95% |
| 用户需要重试次数 | 1-2次 | 0次 |
| 错误提示质量 | 要求JSON | 友好引导 |
| 持续学习能力 | 无 | 有 |

## 九、实施优先级

1. **立即实施**:
   - Validator（计划验证器）
   - Reflector（反思修复器）
   - Temperature=0.0

2. **短期实施**:
   - Learner（学习器）
   - 优雅降级

3. **长期优化**:
   - 基于学习数据自动优化Prompt
   - 错误模式自动规避

## 十、测试计划

```python
test_cases = [
    # 基本查询
    "2公里道路，40km/h，800辆/小时，70%小汽车30%公交车，CO2",
    
    # 复杂查询（之前失败的）
    "12公里道路，26km/h，800辆/小时，50%小汽车20%公交车30%大货车，CO2和PM2.5",
    
    # 各种表述方式
    "5公里快速路，时速60，每小时1000辆，全是小汽车，NOx排放",
    "10km，30码，500辆，80%轿车20%卡车",
]

# 成功标准
# 1. 所有测试首次尝试成功率 > 95%
# 2. 无需用户提供JSON格式
# 3. 错误时给出友好提示
```

把这个方案给Claude Code实施即可。
