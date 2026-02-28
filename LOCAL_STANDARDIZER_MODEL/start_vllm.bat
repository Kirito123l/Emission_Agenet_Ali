@echo off
REM VLLM启动脚本 - Windows版本（通过WSL2）

echo ==========================================
echo 启动本地标准化模型 VLLM 服务 (WSL2)
echo ==========================================
echo.

REM 转换Windows路径到WSL2路径
set "PROJECT_ROOT=%~dp0.."
set "WSL_PROJECT_ROOT=/mnt/d/Agent_MCP/emission_agent"

echo 配置信息:
echo   基础模型: Qwen/Qwen2.5-3B-Instruct
echo   端口: 8001
echo   项目路径: %PROJECT_ROOT%
echo   WSL2路径: %WSL_PROJECT_ROOT%
echo.

echo 检查WSL2...
wsl --list --quiet >nul 2>&1
if errorlevel 1 (
    echo ❌ WSL2未安装或未启动
    echo.
    echo 请先安装WSL2:
    echo   wsl --install
    echo.
    pause
    exit /b 1
)

echo ✅ WSL2已就绪
echo.

echo 启动VLLM服务...
echo 注意: 首次启动会下载模型，需要一些时间
echo.

REM 在WSL2中启动VLLM
wsl bash %WSL_PROJECT_ROOT%/LOCAL_STANDARDIZER_MODEL/start_vllm.sh

echo.
echo VLLM服务已停止
pause
