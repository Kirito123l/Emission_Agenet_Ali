# 训练操作指南

## 🎯 你现在的位置

✅ **数据准备完成** - 8,121条高质量训练数据已就绪
⏳ **接下来**: 环境设置 → 模型训练 → 评估 → 集成

## 📝 完整操作步骤

### 步骤1: 环境准备（必需）

#### 方案A: 使用自动化脚本（推荐）

**Windows用户**:
```bash
# 在 LOCAL_STANDARDIZER_MODEL 目录下运行
setup_environment.bat
```

**Linux/Mac用户**:
```bash
# 在 LOCAL_STANDARDIZER_MODEL 目录下运行
bash setup_environment.sh
```

#### 方案B: 手动设置

```bash
# 1. 创建虚拟环境
conda create -n local_standardizer python=3.10 -y

# 2. 激活环境
conda activate local_standardizer

# 3. 安装PyTorch（根据你的CUDA版本选择）
# CUDA 11.8
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# 或 CUDA 12.1
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# 或 CPU only（不推荐，训练会很慢）
pip install torch torchvision torchaudio

# 4. 安装其他依赖
pip install transformers==4.36.0 peft==0.7.1 datasets==2.14.0 accelerate==0.25.0 pyyaml tqdm bitsandbytes

# 5. 验证安装
python -c "import torch; print(f'PyTorch: {torch.__version__}'); print(f'CUDA: {torch.cuda.is_available()}')"
```

**期望输出**:
```
PyTorch: 2.x.x
CUDA: True  # 如果有GPU
```

### 步骤2: 训练统一模型（车型+污染物）

#### 方案A: 使用快捷脚本（推荐）

**Windows**:
```bash
train_unified.bat
```

**Linux/Mac**:
```bash
conda activate local_standardizer
python scripts/04_train_lora.py --config configs/unified_lora_config.yaml --model_type unified
```

#### 训练参数说明

```yaml
基础模型: Qwen/Qwen2.5-3B-Instruct (约6GB)
LoRA rank: 16
训练轮数: 5 epochs
学习率: 2e-4
批次大小: 4 × 4 (gradient accumulation)
数据量: 4,352条训练 + 512条验证
```

#### 预计时间

| GPU型号 | 训练时间 | 显存占用 |
|---------|----------|----------|
| RTX 3090 (24GB) | 2-3小时 | ~12GB |
| RTX 4090 (24GB) | 1-2小时 | ~12GB |
| RTX 3080 (10GB) | 3-4小时 | ~9GB |
| CPU only | 20-30小时 | N/A |

#### 训练过程监控

训练时会看到类似输出：
```
[1/6] 加载模型和 tokenizer...
  - 基础模型: Qwen/Qwen2.5-3B-Instruct
  - 模型参数量: 3.09B

[2/6] 配置 LoRA...
trainable params: 8,388,608 || all params: 3,098,388,608 || trainable%: 0.27%

[3/6] 加载数据集...
  - 训练集: 4352 条
  - 验证集: 512 条

[4/6] 预处理数据...
预处理训练集: 100%|████████████| 4352/4352

[5/6] 配置训练参数...

[6/6] 开始训练...
Epoch 1/5: 100%|████████████| 272/272 [12:34<00:00, 2.77s/it, loss=0.234]
Epoch 2/5: 100%|████████████| 272/272 [12:31<00:00, 2.76s/it, loss=0.156]
...
```

#### 输出位置

```
models/unified_lora/
├── checkpoint-100/
├── checkpoint-200/
├── checkpoint-300/
└── final/              # 最终模型（用于评估和部署）
    ├── adapter_config.json
    ├── adapter_model.bin
    └── ...
```

### 步骤3: 训练列名映射模型

#### 方案A: 使用快捷脚本

**Windows**:
```bash
train_column.bat
```

**Linux/Mac**:
```bash
conda activate local_standardizer
python scripts/04_train_lora.py --config configs/column_lora_config.yaml --model_type column
```

#### 训练参数说明

```yaml
基础模型: Qwen/Qwen2.5-3B-Instruct
LoRA rank: 32 (更大，因为任务更复杂)
训练轮数: 8 epochs
学习率: 1e-4
数据量: 2,550条训练 + 300条验证
```

#### 预计时间

| GPU型号 | 训练时间 |
|---------|----------|
| RTX 3090 | 1-2小时 |
| RTX 4090 | 30-60分钟 |
| RTX 3080 | 2-3小时 |

### 步骤4: 评估模型

```bash
# 评估统一模型
python scripts/06_evaluate.py \
    --model_type unified \
    --base_model Qwen/Qwen2.5-3B-Instruct \
    --lora_path models/unified_lora/final

# 评估列名映射模型
python scripts/06_evaluate.py \
    --model_type column \
    --base_model Qwen/Qwen2.5-3B-Instruct \
    --lora_path models/column_lora/final
```

#### 目标准确率

- ✅ 车型标准化: ≥95%
- ✅ 污染物标准化: ≥98%
- ✅ 列名映射: ≥90%

### 步骤5: 集成到emission_agent

参考 `INTEGRATION_ANALYSIS.md` 文档：

1. 创建 `shared/standardizer/local_client.py`
2. 修改配置文件
3. 更新标准化器初始化
4. 测试集成

## 🚨 常见问题

### Q1: CUDA out of memory

**解决方案**:
```yaml
# 修改配置文件，减小批次大小
per_device_train_batch_size: 2  # 从4改为2
gradient_accumulation_steps: 8  # 从4改为8
```

### Q2: 训练速度慢

**检查**:
```python
import torch
print(torch.cuda.is_available())  # 应该是 True
print(torch.cuda.get_device_name(0))  # 查看GPU型号
```

### Q3: 模型下载失败

**解决方案**:
```bash
# 设置镜像源
export HF_ENDPOINT=https://hf-mirror.com

# 或手动下载模型到本地，然后修改配置文件中的 base_model 路径
```

### Q4: 准确率不达标

**解决方案**:
1. 增加训练轮数
2. 调整学习率
3. 增加训练数据
4. 检查数据质量

## 📊 训练进度追踪

创建一个检查清单：

- [ ] 环境设置完成
- [ ] PyTorch + CUDA 验证通过
- [ ] 统一模型训练完成
- [ ] 统一模型评估通过（准确率≥95%）
- [ ] 列名映射模型训练完成
- [ ] 列名映射模型评估通过（准确率≥90%）
- [ ] 创建适配器类
- [ ] 集成测试通过
- [ ] 部署到生产环境

## 🎯 下一步行动

**立即执行**:
1. 运行 `setup_environment.bat` 设置环境
2. 验证CUDA可用
3. 运行 `train_unified.bat` 开始训练

**预计总时间**: 4-6小时（包括两个模型的训练）

## 📞 获取帮助

- 查看详细文档: `README.md`
- 查看集成分析: `INTEGRATION_ANALYSIS.md`
- 查看快速开始: `QUICKSTART.md`

祝训练顺利！🚀
