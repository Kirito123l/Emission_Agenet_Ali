@echo off
REM ============================================================
REM 重新创建 emission_agent conda 环境
REM ============================================================

echo.
echo ============================================================
echo 重新创建 emission_agent 环境
echo ============================================================
echo.

REM 设置代理
set HTTP_PROXY=http://127.0.0.1:7890
set HTTPS_PROXY=http://127.0.0.1:7890

REM 1. 删除现有环境
echo [1/5] 删除现有环境...
conda env remove -n emission_agent -y
echo.

REM 2. 创建新环境
echo [2/5] 创建新环境 (Python 3.10)...
conda create -n emission_agent python=3.10 -y
echo.

REM 3. 激活环境并安装基础依赖
echo [3/5] 安装基础依赖...
call conda activate emission_agent

echo   - 安装 requirements.txt...
pip install -r requirements.txt --proxy http://127.0.0.1:7890
echo.

REM 4. 安装知识检索依赖 (特定版本避免冲突)
echo [4/5] 安装知识检索依赖...
echo   - 安装 faiss-cpu...
pip install faiss-cpu --proxy http://127.0.0.1:7890

echo   - 安装 transformers (4.46.0 - 与 FlagEmbedding 兼容)...
pip install transformers==4.46.0 --proxy http://127.0.0.1:7890

echo   - 安装 FlagEmbedding...
pip install FlagEmbedding --proxy http://127.0.0.1:7890

echo   - 安装 sentence-transformers...
pip install sentence-transformers --proxy http://127.0.0.1:7890

echo   - 安装 torch...
pip install torch --proxy http://127.0.0.1:7890

echo   - 安装 datasets...
pip install datasets --proxy http://127.0.0.1:7890

echo   - 安装 accelerate...
pip install accelerate --proxy http://127.0.0.1:7890
echo.

REM 5. 验证安装
echo [5/5] 验证安装...
python -c "import faiss; print('✓ faiss')" 2>nul || echo "✗ faiss 安装失败"
python -c "from FlagEmbedding import BGEM3FlagModel; print('✓ FlagEmbedding')" 2>nul || echo "✗ FlagEmbedding 安装失败"
python -c "import openai; print('✓ openai')" 2>nul || echo "✗ openai 安装失败"
python -c "import fastapi; print('✓ fastapi')" 2>nul || echo "✗ fastapi 安装失败"
python -c "import transformers; print('✓ transformers')" 2>nul || echo "✗ transformers 安装失败"
python -c "import pandas; print('✓ pandas')" 2>nul || echo "✗ pandas 安装失败"
echo.

echo ============================================================
echo 安装完成！
echo ============================================================
echo.
echo 激活环境: conda activate emission_agent
echo 启动服务: .\scripts\restart_server.ps1
echo.

pause
