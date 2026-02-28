# 本地模型集成分析报告

## 执行摘要

✅ **数据准备完成**: 训练数据已就绪（统一模型5,121条，列名映射1,000条）

⚠️ **集成需要适配层**: 本地模型的输入输出格式与现有工作流存在差异，需要创建适配层

## 1. 当前工作流分析

### 1.1 车型/污染物标准化

**现有接口**:
```python
# shared/standardizer/vehicle.py
class VehicleStandardizer:
    def standardize(self, user_input: str, context: Dict = None) -> StandardizationResult:
        # 返回 StandardizationResult 对象
        pass

@dataclass
class StandardizationResult:
    input: str
    standard: Optional[str]  # 标准化后的值
    confidence: float        # 置信度
    method: str             # 方法 (rule/llm/rule_fallback)
    error: Optional[str]    # 错误信息
```

**调用方式**:
```python
# skills/micro_emission/skill.py
v_result = self._vehicle_std.standardize(vehicle_type, context)
if not v_result.standard:
    return SkillResult(success=False, error=f"无法识别车型: {vehicle_type}")

# 使用标准化结果
result = self._calculator.calculate(
    vehicle_type=v_result.standard,  # 使用 .standard 属性
    ...
)
```

**本地模型格式**:
- 输入: `[vehicle] 大货车`
- 输出: `Combination Long-haul Truck` (纯字符串)
- 格式: Qwen3 聊天格式

### 1.2 列名映射

**现有接口**:
```python
# skills/common/column_mapper.py
def map_columns_with_llm(
    file_info: Dict[str, Any],  # 包含 columns, sample_data
    task_type: str,              # "micro_emission" 或 "macro_emission"
    llm_client: Any
) -> Optional[Dict[str, Any]]:
    # 返回复杂的JSON结构
    pass
```

**期望输出**:
```json
{
    "mapping": {
        "用户列名1": "标准字段名1",
        "用户列名2": "标准字段名2"
    },
    "fleet_mix": {
        "用户车型列名1": "标准车型名1"
    },
    "confidence": 0.95,
    "warnings": ["可能的问题1"],
    "unmapped_columns": ["无法识别的列1"]
}
```

**本地模型格式**:
- 输入: `["车速km/h", "加速度", "时间"]`
- 输出: `{"车速km/h": "speed_kph", "加速度": "acceleration_mps2", "时间": "time_sec"}` (简单映射)
- 格式: Qwen3 聊天格式

## 2. 集成问题清单

### 问题1: 返回类型不匹配 ⚠️

**问题描述**:
- 现有接口返回 `StandardizationResult` 对象（包含 standard, confidence, method, error）
- 本地模型返回纯字符串

**影响范围**:
- `VehicleStandardizer.standardize()`
- `PollutantStandardizer.standardize()`

**解决方案**: 创建适配器包装模型输出

### 问题2: 列名映射输出格式不完整 ⚠️

**问题描述**:
- 现有接口期望返回包含 `mapping`, `fleet_mix`, `confidence`, `warnings`, `unmapped_columns` 的完整JSON
- 本地模型只返回简单的 `{"列名": "标准字段"}` 映射

**影响范围**:
- `map_columns_with_llm()`

**解决方案**: 适配器需要补充缺失字段

### 问题3: 输入格式差异 ⚠️

**问题描述**:
- 车型/污染物: 需要添加 `[vehicle]` 或 `[pollutant]` 前缀
- 列名映射: 现有系统传递完整文件信息（包括样本数据），本地模型只需要列名列表

**影响范围**:
- 所有标准化调用

**解决方案**: 适配器处理输入格式转换

### 问题4: 缺少置信度和错误处理 ⚠️

**问题描述**:
- 现有接口提供置信度评分和详细错误信息
- 本地模型只返回结果，没有置信度

**影响范围**:
- 日志记录
- 数据收集
- 错误处理

**解决方案**: 适配器提供默认置信度（如0.9），并处理解析错误

## 3. 推荐的集成方案

### 方案A: 创建本地标准化器适配类 ✅ 推荐

**优点**:
- 完全兼容现有接口
- 无需修改现有代码
- 易于切换（云端 vs 本地）

**实现**:
```python
# shared/standardizer/local_client.py

from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel
from .vehicle import StandardizationResult
import json

class LocalStandardizer:
    """本地标准化模型客户端"""

    def __init__(self, config):
        self.base_model = config["base_model"]
        self.unified_lora_path = config["unified_lora"]
        self.column_lora_path = config["column_lora"]

        # 加载模型和tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.base_model,
            trust_remote_code=True
        )

        # 加载统一模型（车型+污染物）
        self.unified_model = self._load_model(self.unified_lora_path)

        # 加载列名映射模型
        self.column_model = self._load_model(self.column_lora_path)

    def _load_model(self, lora_path):
        """加载LoRA模型"""
        model = AutoModelForCausalLM.from_pretrained(
            self.base_model,
            trust_remote_code=True,
            torch_dtype=torch.float16,
            device_map="auto"
        )
        model = PeftModel.from_pretrained(model, lora_path)
        model.eval()
        return model

    def standardize_vehicle(self, user_input: str, context: Dict = None) -> StandardizationResult:
        """
        车型标准化（兼容现有接口）
        """
        try:
            # 构建输入
            messages = [
                {"role": "system", "content": UNIFIED_SYSTEM_PROMPT},
                {"role": "user", "content": f"[vehicle] {user_input}"}
            ]

            # 生成
            response = self._generate(self.unified_model, messages)

            # 验证输出是否为有效车型
            if response in STANDARD_VEHICLE_TYPES:
                return StandardizationResult(
                    input=user_input,
                    standard=response,
                    confidence=0.9,  # 本地模型默认置信度
                    method="local_model"
                )
            else:
                return StandardizationResult(
                    input=user_input,
                    standard=None,
                    confidence=0.0,
                    method="local_model",
                    error=f"模型输出无效: {response}"
                )
        except Exception as e:
            return StandardizationResult(
                input=user_input,
                standard=None,
                confidence=0.0,
                method="local_model",
                error=str(e)
            )

    def standardize_pollutant(self, user_input: str, context: Dict = None) -> StandardizationResult:
        """
        污染物标准化（兼容现有接口）
        """
        try:
            messages = [
                {"role": "system", "content": UNIFIED_SYSTEM_PROMPT},
                {"role": "user", "content": f"[pollutant] {user_input}"}
            ]

            response = self._generate(self.unified_model, messages)

            if response in STANDARD_POLLUTANTS:
                return StandardizationResult(
                    input=user_input,
                    standard=response,
                    confidence=0.9,
                    method="local_model"
                )
            else:
                return StandardizationResult(
                    input=user_input,
                    standard=None,
                    confidence=0.0,
                    method="local_model",
                    error=f"模型输出无效: {response}"
                )
        except Exception as e:
            return StandardizationResult(
                input=user_input,
                standard=None,
                confidence=0.0,
                method="local_model",
                error=str(e)
            )

    def map_columns(self, file_info: Dict, task_type: str) -> Optional[Dict]:
        """
        列名映射（兼容现有接口）
        """
        try:
            # 提取列名
            columns = file_info["columns"]

            # 选择system prompt
            if task_type == "micro_emission":
                system_prompt = COLUMN_MICRO_SYSTEM_PROMPT
            else:
                system_prompt = COLUMN_MACRO_SYSTEM_PROMPT

            # 构建输入
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(columns, ensure_ascii=False)}
            ]

            # 生成
            response = self._generate(self.column_model, messages, max_new_tokens=256)

            # 解析JSON
            mapping = json.loads(response)

            # 补充缺失字段以兼容现有接口
            result = {
                "mapping": mapping,
                "fleet_mix": {},  # 从mapping中提取车型列
                "confidence": 0.9,
                "warnings": [],
                "unmapped_columns": []
            }

            # 识别车型列（值为MOVES车型名的列）
            for col, std_field in mapping.items():
                if std_field in STANDARD_VEHICLE_TYPES:
                    result["fleet_mix"][col] = std_field
                    del result["mapping"][col]

            # 识别未映射的列
            result["unmapped_columns"] = [
                col for col in columns if col not in mapping
            ]

            return result

        except Exception as e:
            logger.error(f"[本地模型] 列名映射失败: {e}")
            return None

    def _generate(self, model, messages, max_new_tokens=128):
        """生成响应"""
        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )

        inputs = self.tokenizer(text, return_tensors="pt").to(model.device)

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=0.1,
                do_sample=False,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )

        response = self.tokenizer.decode(
            outputs[0][inputs["input_ids"].shape[1]:],
            skip_special_tokens=True
        )
        return response.strip()
```

### 方案B: 修改现有代码 ❌ 不推荐

**缺点**:
- 需要修改多个文件
- 破坏现有接口
- 难以回退到云端API

## 4. 配置集成

### 4.1 更新 config.py

```python
# config.py

# 本地标准化模型配置
LOCAL_STANDARDIZER_CONFIG = {
    "enabled": True,  # 是否启用本地模型
    "base_model": "Qwen/Qwen2.5-3B-Instruct",
    "unified_lora": "./LOCAL_STANDARDIZER_MODEL/models/unified_lora/final",
    "column_lora": "./LOCAL_STANDARDIZER_MODEL/models/column_lora/final",
    "device": "cuda",  # 或 "cpu"
}
```

### 4.2 修改标准化器初始化

```python
# shared/standardizer/vehicle.py

def get_vehicle_standardizer():
    """获取车型标准化器（支持本地模型）"""
    config = get_config()

    if config.LOCAL_STANDARDIZER_CONFIG.get("enabled"):
        # 使用本地模型
        from .local_client import LocalStandardizer
        local_std = LocalStandardizer(config.LOCAL_STANDARDIZER_CONFIG)

        # 返回兼容的接口
        class LocalVehicleStandardizer:
            def standardize(self, user_input, context=None):
                return local_std.standardize_vehicle(user_input, context)

        return LocalVehicleStandardizer()
    else:
        # 使用原有的云端API
        return VehicleStandardizer()
```

### 4.3 修改列名映射调用

```python
# skills/common/column_mapper.py

def map_columns_with_llm(file_info, task_type, llm_client):
    """智能列名映射（支持本地模型）"""
    config = get_config()

    if config.LOCAL_STANDARDIZER_CONFIG.get("enabled"):
        # 使用本地模型
        from shared.standardizer.local_client import LocalStandardizer
        local_std = LocalStandardizer(config.LOCAL_STANDARDIZER_CONFIG)
        return local_std.map_columns(file_info, task_type)
    else:
        # 使用原有的LLM
        # ... 现有代码 ...
```

## 5. 集成检查清单

### 5.1 代码修改

- [ ] 创建 `shared/standardizer/local_client.py`
- [ ] 更新 `config.py` 添加本地模型配置
- [ ] 修改 `shared/standardizer/vehicle.py` 的 `get_vehicle_standardizer()`
- [ ] 修改 `shared/standardizer/pollutant.py` 的 `get_pollutant_standardizer()`
- [ ] 修改 `skills/common/column_mapper.py` 的 `map_columns_with_llm()`

### 5.2 依赖安装

- [ ] 安装 PyTorch (GPU版本)
- [ ] 安装 transformers
- [ ] 安装 peft
- [ ] 安装 accelerate

### 5.3 模型文件

- [ ] 训练统一模型（车型+污染物）
- [ ] 训练列名映射模型
- [ ] 验证模型准确率达标
- [ ] 将模型文件放置到指定路径

### 5.4 测试

- [ ] 单元测试：车型标准化
- [ ] 单元测试：污染物标准化
- [ ] 单元测试：列名映射
- [ ] 集成测试：微观排放计算
- [ ] 集成测试：宏观排放计算
- [ ] 性能测试：推理速度
- [ ] 对比测试：本地 vs 云端准确率

## 6. 潜在风险和缓解措施

### 风险1: 推理速度慢 ⚠️

**风险**: 本地模型推理可能比云端API慢

**缓解**:
- 使用 GPU 加速
- 批量处理多个标准化请求
- 添加缓存层（相同输入直接返回缓存结果）
- 考虑模型量化（INT8/INT4）

### 风险2: 准确率不达标 ⚠️

**风险**: 微调后的模型准确率可能低于云端API

**缓解**:
- 设置准确率阈值，低于阈值时回退到云端API
- 持续收集错误案例，补充训练数据
- 实现混合策略：本地模型优先，失败时调用云端

### 风险3: 显存占用 ⚠️

**风险**: 加载两个模型可能占用大量显存

**缓解**:
- 使用模型量化
- 按需加载模型（用时加载，用完卸载）
- 使用 CPU 推理（速度较慢但无显存限制）

### 风险4: 输出格式不稳定 ⚠️

**风险**: 模型可能输出格式错误的JSON或无效的车型名

**缓解**:
- 添加输出验证逻辑
- 使用约束解码（constrained decoding）
- 失败时回退到规则匹配或云端API

## 7. 性能对比预期

| 指标 | 云端API | 本地模型 | 说明 |
|------|---------|----------|------|
| 车型准确率 | ~95% | 目标≥95% | 需要验证 |
| 污染物准确率 | ~98% | 目标≥98% | 需要验证 |
| 列名映射准确率 | ~90% | 目标≥90% | 需要验证 |
| 推理延迟 | 200-500ms | 50-200ms (GPU) | 本地更快 |
| 成本 | 按调用计费 | 一次性训练成本 | 长期本地更省 |
| 离线可用 | ❌ | ✅ | 本地优势 |

## 8. 结论

### ✅ 可以无缝集成

通过创建适配层（`LocalStandardizer`），本地模型可以完全兼容现有工作流，无需修改业务逻辑代码。

### 📋 需要完成的工作

1. **创建适配器类** (1-2小时)
2. **修改配置和初始化** (1小时)
3. **完成模型训练** (3-5小时，需要GPU)
4. **集成测试** (2-3小时)
5. **性能优化** (可选，1-2小时)

**总计**: 约8-13小时工作量

### 🎯 推荐行动计划

1. **立即**: 创建 `local_client.py` 适配器类
2. **训练完成后**: 集成测试
3. **验证通过后**: 逐步切换到本地模型
4. **保留回退**: 保持云端API作为备选方案

### 💡 关键建议

- 使用配置开关，方便在本地和云端之间切换
- 添加详细日志，便于调试和性能分析
- 实现缓存机制，提升重复查询性能
- 定期收集错误案例，持续改进模型
