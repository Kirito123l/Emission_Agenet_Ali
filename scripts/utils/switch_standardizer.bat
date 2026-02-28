@echo off
REM 本地标准化模型开关脚本

echo ==========================================
echo 本地标准化模型配置
echo ==========================================
echo.

echo 当前配置:
findstr "USE_LOCAL_STANDARDIZER" .env
echo.

echo 请选择模式:
echo   1. 使用API模式（云端）
echo   2. 使用本地模型（直接加载）
echo   3. 使用本地模型（VLLM服务）
echo   4. 查看当前配置
echo   0. 退出
echo.

set /p choice=请输入选项 (0-4):

if "%choice%"=="1" goto use_api
if "%choice%"=="2" goto use_local_direct
if "%choice%"=="3" goto use_local_vllm
if "%choice%"=="4" goto show_config
if "%choice%"=="0" goto end

echo 无效选项
goto end

:use_api
echo.
echo 切换到API模式...
powershell -Command "(Get-Content .env) -replace '^USE_LOCAL_STANDARDIZER=.*', 'USE_LOCAL_STANDARDIZER=false' | Set-Content .env"
echo ✅ 已切换到API模式
echo.
echo 请重启服务器以应用更改:
echo   .\scripts\restart_server.ps1
goto end

:use_local_direct
echo.
echo 切换到本地模型（直接加载）...
powershell -Command "(Get-Content .env) -replace '^USE_LOCAL_STANDARDIZER=.*', 'USE_LOCAL_STANDARDIZER=true' | Set-Content .env"
powershell -Command "(Get-Content .env) -replace '^LOCAL_STANDARDIZER_MODE=.*', 'LOCAL_STANDARDIZER_MODE=direct' | Set-Content .env"
echo ✅ 已切换到本地模型（直接加载模式）
echo.
echo ⚠️  注意:
echo   - 需要至少6GB显存
echo   - 首次加载会下载模型（约6GB）
echo   - 推理延迟约200ms
echo.
echo 请重启服务器以应用更改:
echo   .\scripts\restart_server.ps1
goto end

:use_local_vllm
echo.
echo 切换到本地模型（VLLM服务）...
powershell -Command "(Get-Content .env) -replace '^USE_LOCAL_STANDARDIZER=.*', 'USE_LOCAL_STANDARDIZER=true' | Set-Content .env"
powershell -Command "(Get-Content .env) -replace '^LOCAL_STANDARDIZER_MODE=.*', 'LOCAL_STANDARDIZER_MODE=vllm' | Set-Content .env"
echo ✅ 已切换到本地模型（VLLM模式）
echo.
echo ⚠️  注意:
echo   - 需要先启动VLLM服务
echo   - 运行: .\LOCAL_STANDARDIZER_MODEL\start_vllm.bat
echo   - 或在WSL2中: bash LOCAL_STANDARDIZER_MODEL/start_vllm.sh
echo.
echo 请重启服务器以应用更改:
echo   .\scripts\restart_server.ps1
goto end

:show_config
echo.
echo 当前完整配置:
echo ==========================================
findstr "LOCAL_STANDARDIZER" .env
echo ==========================================
goto end

:end
echo.
pause
