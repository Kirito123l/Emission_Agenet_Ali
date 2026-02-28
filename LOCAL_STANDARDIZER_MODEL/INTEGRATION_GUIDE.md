# 本地标准化模型集成指南

## 📋 概述

本文档说明如何将本地微调的Qwen3-4B模型集成到emission_agent，替代云端API调用。

## 🎯 模型架构

- **基础模型**: Qwen/Qwen2.5-3B-Instruct
- **微调方法**: LoRA (Low-Rank Adaptation)
- **两个独立适配器**:
  - `unified_lora`: 车型标准化 + 污染物标准化
  - `column_lora`: 列名映射
- **策略**: 加载一个基础模型，动态切换不同的LoRA适配器

## 🔧 部署方案对比

### 方案1: 直接加载（推荐用于开发/测试）

**优点**:
- 简单，无需额外服务
- 适合单用户场景
- 调试方便

**缺点**:
- 每次请求都需要加载模型
- 显存占用高（~6GB）
- 延迟较高（首次加载慢）

**适用场景**: 开发测试、单用户使用

### 方案2: VLLM服务（推荐用于生产）

**优点**:
- 高性能推理（PagedAttention）
- 支持批处理
- 显存优化
- 支持多用户并发

**缺点**:
- 需要额外启动服务
- 配置稍复杂
- 需要WSL2（Windows用户）

**适用场景**: 生产环境、多用户、高并发

## 📝 集成步骤

### 步骤1: 确认模型训练完成

检查模型checkpoint是否存在：

```bash
# 检查unified_lora模型
ls LOCAL_STANDARDIZER_MODEL/models/unified_lora/

# 检查column_lora模型
ls LOCAL_STANDARDIZER_MODEL/models/column_lora/
```

**如果模型不存在**，需要先训练：

```bash
cd LOCAL_STANDARDIZER_MODEL

# 训练unified模型
python scripts/04_train_lora.py --config configs/unified_lora_config.yaml --model_type unified

# 训练column模型
python scripts/04_train_lora.py --config configs/column_lora_config.yaml --model_type column
```

**根据你的描述**，列标准化的最佳模型在第200步（epoch 1.25），应该在：
```
LOCAL_STANDARDIZER_MODEL/models/column_lora/checkpoint-200/
```

### 步骤2: 添加配置开关

编辑 `config.py`，添加本地模型配置：

```python
@dataclass
class Config:
    def __post_init__(self):
        # ... 现有配置 ...

        # ============ 本地标准化模型配置 ============
        self.use_local_standardizer = os.getenv("USE_LOCAL_STANDARDIZER", "false").lower() == "true"

        self.local_standardizer_config = {
            "enabled": self.use_local_standardizer,
            "mode": os.getenv("LOCAL_STANDARDIZER_MODE", "direct"),  # "direct" or "vllm"
            "base_model": os.getenv("LOCAL_STANDARDIZER_BASE_MODEL", "Qwen/Qwen2.5-3B-Instruct"),
            "unified_lora": os.getenv("LOCAL_STANDARDIZER_UNIFIED_LORA", "./LOCAL_STANDARDIZER_MODEL/models/unified_lora/final"),
            "column_lora": os.getenv("LOCAL_STANDARDIZER_COLUMN_LORA", "./LOCAL_STANDARDIZER_MODEL/models/column_lora/checkpoint-200"),
            "device": os.getenv("LOCAL_STANDARDIZER_DEVICE", "cuda"),  # "cuda" or "cpu"
            "max_length": int(os.getenv("LOCAL_STANDARDIZER_MAX_LENGTH", "256")),
            "vllm_url": os.getenv("LOCAL_STANDARDIZER_VLLM_URL", "http://localhost:8001"),
        }
```

### 步骤3: 更新 `.env` 文件

添加本地模型配置：

```bash
# ============ 本地标准化模型配置 ============
# 是否使用本地模型（true/false）
USE_LOCAL_STANDARDIZER=false

# 模式：direct（直接加载）或 vllm（VLLM服务）
LOCAL_STANDARDIZER_MODE=direct

# 基础模型路径
LOCAL_STANDARDIZER_BASE_MODEL=Qwen/Qwen2.5-3B-Instruct

# LoRA适配器路径
LOCAL_STANDARDIZER_UNIFIED_LORA=./LOCAL_STANDARDIZER_MODEL/models/unified_lora/final
LOCAL_STANDARDIZER_COLUMN_LORA=./LOCAL_STANDARDIZER_MODEL/models/column_lora/checkpoint-200

# 设备：cuda 或 cpu
LOCAL_STANDARDIZER_DEVICE=cuda

# VLLM服务地址（仅在mode=vllm时使用）
LOCAL_STANDARDIZER_VLLM_URL=http://localhost:8001
```

### 步骤4: 创建本地模型客户端

创建 `shared/standardizer/local_client.py`：

```python
import json
import logging
import torch
from typing import Optional, Dict, List
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel
import requests

logger = logging.getLogger(__name__)

class LocalStandardizerClient:
    """本地标准化模型客户端"""

    def __init__(self, config: Dict):
        self.config = config
        self.mode = config.get("mode", "direct")

        if self.mode == "direct":
            self._init_direct_mode()
        elif self.mode == "vllm":
            self._init_vllm_mode()
        else:
            raise ValueError(f"Unknown mode: {self.mode}")

    def _init_direct_mode(self):
        """初始化直接加载模式"""
        logger.info("初始化本地标准化模型（直接加载模式）...")

        device = self.config.get("device", "cuda")
        base_model_path = self.config.get("base_model")

        # 加载tokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(base_model_path)

        # 加载基础模型
        self.base_model = AutoModelForCausalLM.from_pretrained(
            base_model_path,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            device_map=device
        )

        # 加载LoRA适配器
        self.unified_lora_path = self.config.get("unified_lora")
        self.column_lora_path = self.config.get("column_lora")

        # 当前加载的适配器
        self.current_adapter = None
        self.model = None

        logger.info("本地标准化模型初始化完成")

    def _init_vllm_mode(self):
        """初始化VLLM模式"""
        logger.info("初始化本地标准化模型（VLLM模式）...")
        self.vllm_url = self.config.get("vllm_url")
        logger.info(f"VLLM服务地址: {self.vllm_url}")

    def _switch_adapter(self, adapter_type: str):
        """切换LoRA适配器"""
        if self.mode == "vllm":
            # VLLM模式不需要切换适配器
            return

        if self.current_adapter == adapter_type:
            return

        logger.info(f"切换LoRA适配器: {adapter_type}")

        if adapter_type == "unified":
            lora_path = self.unified_lora_path
        elif adapter_type == "column":
            lora_path = self.column_lora_path
        else:
            raise ValueError(f"Unknown adapter type: {adapter_type}")

        # 加载LoRA适配器
        self.model = PeftModel.from_pretrained(self.base_model, lora_path)
        self.current_adapter = adapter_type

    def _generate_direct(self, prompt: str) -> str:
        """直接生成（非VLLM）"""
        messages = [
            {"role": "system", "content": "你是标准化助手。"},
            {"role": "user", "content": prompt}
        ]

        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )

        inputs = self.tokenizer([text], return_tensors="pt").to(self.model.device)

        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=self.config.get("max_length", 256),
                temperature=0.1,
                do_sample=False
            )

        response = self.tokenizer.decode(outputs[0][len(inputs.input_ids[0]):], skip_special_tokens=True)
        return response.strip()

    def _generate_vllm(self, prompt: str, adapter: str) -> str:
        """通过VLLM生成"""
        response = requests.post(
            f"{self.vllm_url}/v1/completions",
            json={
                "model": adapter,  # "unified" or "column"
                "prompt": prompt,
                "max_tokens": self.config.get("max_length", 256),
                "temperature": 0.1
            }
        )
        response.raise_for_status()
        return response.json()["choices"][0]["text"].strip()

    def standardize_vehicle(self, input_text: str) -> str:
        """标准化车型"""
        self._switch_adapter("unified")
        prompt = f"[vehicle] {input_text}"

        if self.mode == "direct":
            return self._generate_direct(prompt)
        else:
            return self._generate_vllm(prompt, "unified")

    def standardize_pollutant(self, input_text: str) -> str:
        """标准化污染物"""
        self._switch_adapter("unified")
        prompt = f"[pollutant] {input_text}"

        if self.mode == "direct":
            return self._generate_direct(prompt)
        else:
            return self._generate_vllm(prompt, "unified")

    def map_columns(self, columns: List[str], task_type: str) -> Dict[str, str]:
        """映射列名"""
        self._switch_adapter("column")

        # 构建prompt
        system_prompt = f"""你是列名映射助手。分析Excel表格列名，将其映射到标准字段。

任务类型: {task_type}

返回JSON格式的映射，只返回能识别的列。"""

        prompt = json.dumps(columns, ensure_ascii=False)

        if self.mode == "direct":
            result = self._generate_direct(prompt)
        else:
            result = self._generate_vllm(prompt, "column")

        try:
            return json.loads(result)
        except json.JSONDecodeError:
            logger.error(f"JSON解析失败: {result}")
            return {}
```

### 步骤5: 修改现有Standardizer

修改 `shared/standardizer/vehicle.py` 和 `pollutant.py`，添加本地模型支持：

```python
# 在 VehicleStandardizer.__new__ 中添加
def __new__(cls):
    if cls._instance is None:
        cls._instance = super().__new__(cls)
        config = get_config()

        # 选择使用本地模型还是API
        if config.use_local_standardizer:
            from .local_client import LocalStandardizerClient
            cls._instance._local_client = LocalStandardizerClient(config.local_standardizer_config)
            cls._instance._use_local = True
        else:
            cls._instance._llm = get_llm("standardizer") if config.enable_llm_standardization else None
            cls._instance._use_local = False

        # ... 其他初始化 ...
    return cls._instance

# 修改 _llm_standardize 方法
def _llm_standardize(self, user_input: str) -> Optional[StandardizationResult]:
    if self._use_local:
        # 使用本地模型
        try:
            standard = self._local_client.standardize_vehicle(user_input)
            if standard in STANDARD_VEHICLE_TYPES:
                return StandardizationResult(user_input, standard, 0.95, "local_llm")
        except Exception as e:
            logger.error(f"本地模型标准化失败: {e}")
            return None
    else:
        # 使用API（原有逻辑）
        # ...
```

## 🚀 启动方式

### 方式1: 直接加载模式

```bash
# 1. 修改 .env
USE_LOCAL_STANDARDIZER=true
LOCAL_STANDARDIZER_MODE=direct

# 2. 重启服务器
.\scripts\restart_server.ps1
```

### 方式2: VLLM模式（推荐）

#### Windows用户（使用WSL2）

```bash
# 1. 在WSL2中安装VLLM
wsl
conda create -n vllm python=3.10 -y
conda activate vllm
pip install vllm

# 2. 启动VLLM服务（unified模型）
vllm serve Qwen/Qwen2.5-3B-Instruct \
    --enable-lora \
    --lora-modules unified=/mnt/d/Agent_MCP/emission_agent/LOCAL_STANDARDIZER_MODEL/models/unified_lora/final \
    --lora-modules column=/mnt/d/Agent_MCP/emission_agent/LOCAL_STANDARDIZER_MODEL/models/column_lora/checkpoint-200 \
    --port 8001 \
    --gpu-memory-utilization 0.8

# 3. 在Windows中修改 .env
USE_LOCAL_STANDARDIZER=true
LOCAL_STANDARDIZER_MODE=vllm
LOCAL_STANDARDIZER_VLLM_URL=http://localhost:8001

# 4. 重启服务器
.\scripts\restart_server.ps1
```

#### Linux用户

```bash
# 1. 安装VLLM
pip install vllm

# 2. 启动VLLM服务
vllm serve Qwen/Qwen2.5-3B-Instruct \
    --enable-lora \
    --lora-modules unified=./LOCAL_STANDARDIZER_MODEL/models/unified_lora/final \
    --lora-modules column=./LOCAL_STANDARDIZER_MODEL/models/column_lora/checkpoint-200 \
    --port 8001 \
    --gpu-memory-utilization 0.8

# 3. 修改 .env
USE_LOCAL_STANDARDIZER=true
LOCAL_STANDARDIZER_MODE=vllm

# 4. 重启服务器
./scripts/restart_server.sh
```

## 📊 性能对比

| 指标 | API模式 | 直接加载 | VLLM模式 |
|------|---------|----------|----------|
| 首次延迟 | ~500ms | ~3000ms | ~100ms |
| 后续延迟 | ~500ms | ~200ms | ~50ms |
| 显存占用 | 0 | ~6GB | ~4GB |
| 并发支持 | 高 | 低 | 高 |
| 成本 | 按调用计费 | 免费 | 免费 |

## 🔍 测试验证

```bash
# 测试本地模型
python -c "
from shared.standardizer.vehicle import get_vehicle_standardizer
std = get_vehicle_standardizer()
result = std.standardize('小汽车')
print(f'输入: 小汽车')
print(f'标准: {result.standard}')
print(f'方法: {result.method}')
"
```

## ⚠️ 注意事项

1. **模型路径**: 确保checkpoint-200存在，如果不存在，使用最新的checkpoint或final目录
2. **显存要求**: 至少需要6GB显存（直接加载）或4GB（VLLM）
3. **首次加载**: 第一次加载模型会下载基础模型（~6GB），需要时间
4. **WSL2路径**: Windows用户使用VLLM时，路径需要转换为WSL2格式（/mnt/d/...）

## 🎯 推荐配置

- **开发/测试**: 使用API模式（简单快速）
- **生产环境（单用户）**: 使用直接加载模式
- **生产环境（多用户）**: 使用VLLM模式

## 📝 切换回API模式

如果需要切换回API模式：

```bash
# 修改 .env
USE_LOCAL_STANDARDIZER=false

# 重启服务器
.\scripts\restart_server.ps1
```
