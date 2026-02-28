@echo off
REM 本地标准化模型训练环境设置脚本 (Windows)

echo ==========================================
echo 设置本地标准化模型训练环境
echo ==========================================

REM 1. 创建conda虚拟环境
echo.
echo [1/4] 创建conda虚拟环境...
call conda create -n local_standardizer python=3.10 -y

REM 2. 激活环境
echo.
echo [2/4] 激活环境...
call conda activate local_standardizer

REM 3. 安装PyTorch
echo.
echo [3/4] 安装PyTorch...
echo 请根据你的CUDA版本选择：
echo   - CUDA 11.8: 运行 setup_cuda118.bat
echo   - CUDA 12.1: 运行 setup_cuda121.bat
echo   - CPU only: 运行 setup_cpu.bat
echo.
echo 当前脚本将安装CUDA 11.8版本（最常见）
echo 如果你的CUDA版本不同，请按Ctrl+C取消，然后手动安装
pause

pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

REM 4. 安装其他依赖
echo.
echo [4/4] 安装其他依赖...
REM 注意：Qwen3 需要 transformers >= 4.45.0
pip install "transformers[torch]>=4.45.0"
pip install "peft>=0.11.0"
pip install "datasets>=2.14.0"
pip install "accelerate>=0.30.0"
pip install pyyaml
pip install tqdm
pip install bitsandbytes
pip install scipy

echo.
echo ==========================================
echo 环境设置完成！
echo ==========================================
echo.
echo 验证安装：
python -c "import torch; print(f'PyTorch版本: {torch.__version__}'); print(f'CUDA可用: {torch.cuda.is_available()}'); print(f'CUDA版本: {torch.version.cuda if torch.cuda.is_available() else \"N/A\"}')"

echo.
echo 下一步：
echo 1. 如果CUDA不可用，请重新安装对应版本的PyTorch
echo 2. 运行 train_unified.bat 开始训练统一模型
echo 3. 运行 train_column.bat 开始训练列名映射模型
pause
