#!/bin/bash
# 本地标准化模型训练环境设置脚本

echo "=========================================="
echo "设置本地标准化模型训练环境"
echo "=========================================="

# 1. 创建conda虚拟环境
echo ""
echo "[1/4] 创建conda虚拟环境..."
conda create -n local_standardizer python=3.10 -y

# 2. 激活环境
echo ""
echo "[2/4] 激活环境..."
conda activate local_standardizer

# 3. 安装PyTorch (根据你的CUDA版本选择)
echo ""
echo "[3/4] 安装PyTorch..."
echo "请根据你的CUDA版本选择："
echo "  - CUDA 11.8: pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118"
echo "  - CUDA 12.1: pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121"
echo "  - CPU only: pip install torch torchvision torchaudio"

# 如果你有CUDA 11.8，取消下面这行的注释
# pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# 如果你有CUDA 12.1，取消下面这行的注释
# pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# 4. 安装其他依赖
echo ""
echo "[4/4] 安装其他依赖..."
# 注意：Qwen3 需要 transformers >= 4.45.0
pip install "transformers[torch]>=4.45.0"
pip install "peft>=0.11.0"
pip install "datasets>=2.14.0"
pip install "accelerate>=0.30.0"
pip install pyyaml
pip install tqdm
pip install bitsandbytes  # 用于量化（可选）
pip install scipy

echo ""
echo "=========================================="
echo "环境设置完成！"
echo "=========================================="
echo ""
echo "验证安装："
python -c "import torch; print(f'PyTorch版本: {torch.__version__}'); print(f'CUDA可用: {torch.cuda.is_available()}'); print(f'CUDA版本: {torch.version.cuda if torch.cuda.is_available() else \"N/A\"}')"

echo ""
echo "下一步："
echo "1. 如果CUDA不可用，请重新安装对应版本的PyTorch"
echo "2. 运行训练脚本开始训练"
