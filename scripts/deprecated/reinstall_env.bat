@echo off
REM ============================================================
REM 重新创建 emission_agent conda 环境
REM ============================================================

echo.
echo ============================================================
echo 重新创建 emission_agent 环境
echo ============================================================
echo.

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
pip install openai>=1.0.0 python-dotenv>=1.0.0 click>=8.0.0 rich>=13.0.0 pandas>=2.0.0 fastapi>=0.100.0 uvicorn>=0.22.0 python-multipart>=0.0.6 openpyxl>=3.0.0 --proxy http://127.0.0.1:7890
echo.

REM 4. 安装知识检索依赖
echo [4/5] 安装知识检索依赖 (faiss-cpu, FlagEmbedding)...
pip install faiss-cpu --proxy http://127.0.0.1:7890
pip install transformers==4.46.0 --proxy http://127.0.0.1:7890
pip install FlagEmbedding --proxy http://127.0.0.1:7890
echo.

REM 5. 验证安装
echo [5/5] 验证安装...
python -c "import faiss; print('✓ faiss-cpu')"
python -c "from FlagEmbedding import BGEM3FlagModel; print('✓ FlagEmbedding')"
python -c "import openai; print('✓ openai')"
python -c "import fastapi; print('✓ fastapi')"
echo.

echo ============================================================
echo 安装完成！
echo ============================================================
echo.
echo 激活环境: conda activate emission_agent
echo 启动服务: .\scripts\restart_server.ps1
echo.

pause
