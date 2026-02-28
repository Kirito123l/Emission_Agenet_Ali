# 训练脚本使用指南

本目录包含本地标准化模型的数据准备和训练脚本。

## 脚本列表

### 数据准备脚本

1. **01_create_seed_data.py** - 生成种子数据
   - 从 README.md 和现有代码提取别名映射
   - 生成车型、污染物、列名映射的种子数据
   - 输出: `data/raw/*.json`

2. **02_augment_data.py** - 数据增强
   - 对种子数据进行多种增强（空格、大小写、上下文、修饰词等）
   - 生成大量多样化的训练数据
   - 输出: `data/augmented/*.json`

3. **03_prepare_training_data.py** - 准备训练数据
   - 转换为 Qwen3 聊天格式
   - 划分训练集/验证集/测试集 (85%/10%/5%)
   - 输出: `data/final/*.json`

4. **validate_data.py** - 数据验证
   - 验证数据质量和格式
   - 检查覆盖率和分布
   - 打印统计信息

### 训练脚本

5. **04_train_lora.py** - LoRA 微调训练
   - 支持统一模型和列名映射模型
   - 使用 PEFT 库进行 LoRA 微调
   - 自动保存最佳模型

### 评估脚本

6. **06_evaluate.py** - 模型评估
   - 在测试集上评估模型性能
   - 计算准确率指标
   - 分析错误案例

## 使用流程

### 1. 数据准备（已完成）

```bash
# 步骤1: 生成种子数据
python scripts/01_create_seed_data.py

# 步骤2: 数据增强
python scripts/02_augment_data.py

# 步骤3: 准备训练数据
python scripts/03_prepare_training_data.py

# 步骤4: 验证数据质量
python scripts/validate_data.py
```

**当前数据统计:**
- 统一模型: 5,121 条 (训练集: 4,352, 验证集: 512, 测试集: 257)
- 列名映射: 1,000 条 (训练集: 850, 验证集: 100, 测试集: 50)
- 覆盖: 13种车型 ✓, 7种污染物 ✓

### 2. 模型训练

#### 训练统一模型（车型 + 污染物）

```bash
python scripts/04_train_lora.py \
    --config configs/unified_lora_config.yaml \
    --model_type unified
```

**训练参数:**
- 基础模型: Qwen/Qwen2.5-3B-Instruct
- LoRA rank: 16
- 训练轮数: 5 epochs
- 学习率: 2e-4
- 批次大小: 4 × 4 (gradient accumulation)

**预计训练时间:**
- GPU (RTX 3090): ~2-3 小时
- GPU (RTX 4090): ~1-2 小时

#### 训练列名映射模型

```bash
python scripts/04_train_lora.py \
    --config configs/column_lora_config.yaml \
    --model_type column
```

**训练参数:**
- 基础模型: Qwen/Qwen2.5-3B-Instruct
- LoRA rank: 32 (更大，因为任务更复杂)
- 训练轮数: 8 epochs
- 学习率: 1e-4
- 批次大小: 4 × 4

**预计训练时间:**
- GPU (RTX 3090): ~1-2 小时
- GPU (RTX 4090): ~30-60 分钟

### 3. 模型评估

#### 评估统一模型

```bash
python scripts/06_evaluate.py \
    --model_type unified \
    --base_model Qwen/Qwen2.5-3B-Instruct \
    --lora_path models/unified_lora/final
```

**目标准确率:**
- 车型标准化: ≥95%
- 污染物标准化: ≥98%

#### 评估列名映射模型

```bash
python scripts/06_evaluate.py \
    --model_type column \
    --base_model Qwen/Qwen2.5-3B-Instruct \
    --lora_path models/column_lora/final
```

**目标准确率:**
- 完全匹配: ≥90%
- 部分匹配: ≥95%

## 依赖安装

```bash
pip install torch transformers peft datasets accelerate pyyaml tqdm
```

**推荐版本:**
- torch >= 2.0.0
- transformers >= 4.36.0
- peft >= 0.7.0
- datasets >= 2.14.0

## 常见问题

### Q1: 显存不足怎么办？

**方案1: 减小批次大小**
```yaml
per_device_train_batch_size: 2  # 从4改为2
gradient_accumulation_steps: 8  # 从4改为8
```

**方案2: 使用 QLoRA (4bit 量化)**
```python
# 在 04_train_lora.py 中添加
from transformers import BitsAndBytesConfig

bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16,
)

model = AutoModelForCausalLM.from_pretrained(
    model_name,
    quantization_config=bnb_config,
    ...
)
```

### Q2: 训练速度慢？

- 确保使用 GPU: `torch.cuda.is_available()` 应返回 True
- 启用 Flash Attention (需要 A100/H100)
- 使用更小的 max_length
- 减少 logging_steps 和 eval_steps

### Q3: 准确率不达标？

- 增加训练数据量（运行 02_augment_data.py 时增加变体数量）
- 调整学习率（尝试 1e-4 或 5e-5）
- 增加训练轮数
- 增大 LoRA rank

## 输出目录结构

```
LOCAL_STANDARDIZER_MODEL/
├── data/
│   ├── raw/                    # 种子数据
│   ├── augmented/              # 增强后数据
│   └── final/                  # 最终训练数据
├── models/
│   ├── unified_lora/           # 统一模型 LoRA 权重
│   │   ├── checkpoint-100/
│   │   ├── checkpoint-200/
│   │   └── final/              # 最终模型
│   └── column_lora/            # 列名映射模型 LoRA 权重
│       └── final/
└── scripts/                    # 本目录
```

## 下一步

完成训练后，参考主 README.md 的"部署集成"章节，将模型集成到 emission_agent 项目中。
