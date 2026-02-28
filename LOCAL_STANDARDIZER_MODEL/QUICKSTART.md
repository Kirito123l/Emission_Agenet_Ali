# 快速开始指南

本指南帮助你快速开始本地标准化模型的训练和使用。

## 前置条件

### 硬件要求
- **GPU**: NVIDIA GPU with ≥16GB VRAM (推荐 RTX 3090/4090 或 A100)
- **内存**: ≥32GB RAM
- **存储**: ≥20GB 可用空间

### 软件要求
- Python 3.8+
- CUDA 11.8+ (for GPU support)
- Git

## 安装步骤

### 1. 安装依赖

```bash
# 进入项目目录
cd D:/Agent_MCP/emission_agent/LOCAL_STANDARDIZER_MODEL

# 安装 PyTorch (根据你的 CUDA 版本选择)
# CUDA 11.8
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# CUDA 12.1
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# 安装其他依赖
pip install transformers peft datasets accelerate pyyaml tqdm bitsandbytes
```

### 2. 验证安装

```bash
python -c "import torch; print(f'PyTorch: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}')"
```

应该输出:
```
PyTorch: 2.x.x
CUDA available: True
```

## 数据准备（已完成）

数据已经准备好，位于 `data/final/` 目录：
- ✅ 统一模型: 5,121 条数据
- ✅ 列名映射: 1,000 条数据

如需重新生成数据:
```bash
python scripts/01_create_seed_data.py
python scripts/02_augment_data.py
python scripts/03_prepare_training_data.py
python scripts/validate_data.py
```

## 模型训练

### 训练统一模型（车型 + 污染物标准化）

```bash
python scripts/04_train_lora.py \
    --config configs/unified_lora_config.yaml \
    --model_type unified
```

**训练时间**: 约 2-3 小时 (RTX 3090)

**输出**: `models/unified_lora/final/`

### 训练列名映射模型

```bash
python scripts/04_train_lora.py \
    --config configs/column_lora_config.yaml \
    --model_type column
```

**训练时间**: 约 1-2 小时 (RTX 3090)

**输出**: `models/column_lora/final/`

## 模型评估

### 评估统一模型

```bash
python scripts/06_evaluate.py \
    --model_type unified \
    --base_model Qwen/Qwen2.5-3B-Instruct \
    --lora_path models/unified_lora/final
```

**目标准确率**:
- 车型标准化: ≥95%
- 污染物标准化: ≥98%

### 评估列名映射模型

```bash
python scripts/06_evaluate.py \
    --model_type column \
    --base_model Qwen/Qwen2.5-3B-Instruct \
    --lora_path models/column_lora/final
```

**目标准确率**:
- 完全匹配: ≥90%

## 快速测试

训练完成后，可以快速测试模型:

```python
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

# 加载模型
base_model = "Qwen/Qwen2.5-3B-Instruct"
tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
model = AutoModelForCausalLM.from_pretrained(base_model, trust_remote_code=True, device_map="auto")
model = PeftModel.from_pretrained(model, "models/unified_lora/final")

# 测试车型标准化
messages = [
    {"role": "system", "content": "你是标准化助手..."},
    {"role": "user", "content": "[vehicle] 大货车"}
]

text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
inputs = tokenizer(text, return_tensors="pt").to(model.device)
outputs = model.generate(**inputs, max_new_tokens=32)
response = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)

print(f"输入: 大货车")
print(f"输出: {response}")  # 应该输出: Combination Long-haul Truck
```

## 常见问题

### Q: 显存不足 (OOM)

**解决方案**:
1. 减小批次大小: 在配置文件中设置 `per_device_train_batch_size: 2`
2. 使用 4bit 量化 (QLoRA)
3. 使用更小的模型 (如 Qwen2.5-1.5B)

### Q: 训练速度慢

**解决方案**:
1. 确保使用 GPU: `torch.cuda.is_available()` 应返回 True
2. 减少 `logging_steps` 和 `eval_steps`
3. 使用 Flash Attention (需要 A100/H100)

### Q: 准确率不达标

**解决方案**:
1. 增加训练轮数
2. 调整学习率
3. 增大 LoRA rank
4. 增加训练数据

## 下一步

训练完成后:
1. 评估模型性能
2. 集成到 emission_agent 项目
3. 进行端到端测试
4. 性能对比（本地 vs 云端 API）

## 获取帮助

- 查看详细文档: `README.md`
- 查看脚本说明: `scripts/README.md`
- 查看完成总结: `SUMMARY.md`

## 项目结构

```
LOCAL_STANDARDIZER_MODEL/
├── README.md              # 详细开发文档
├── PROMPT.md              # 任务说明
├── SUMMARY.md             # 完成总结
├── QUICKSTART.md          # 本文档
├── data/                  # 数据目录
│   ├── raw/              # 种子数据
│   ├── augmented/        # 增强数据
│   └── final/            # 训练数据 ✓
├── scripts/              # 脚本目录 ✓
├── configs/              # 配置文件 ✓
├── models/               # 模型输出
│   ├── unified_lora/
│   └── column_lora/
└── tests/                # 测试目录
```

## 时间估算

| 任务 | 时间 (RTX 3090) |
|------|-----------------|
| 数据准备 | ✅ 已完成 |
| 训练统一模型 | 2-3 小时 |
| 训练列名映射模型 | 1-2 小时 |
| 模型评估 | 10-20 分钟 |
| **总计** | **3-5 小时** |

开始训练吧！🚀
