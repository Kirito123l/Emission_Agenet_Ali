@echo off
REM 快速修复脚本 - 禁用代理配置

echo ========================================
echo Emission Agent 快速修复
echo ========================================
echo.

echo 正在备份 .env 文件...
copy .env .env.backup.%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%%time:~6,2%
echo 备份完成！
echo.

echo 正在禁用代理配置...
powershell -Command "(Get-Content .env) -replace '^HTTP_PROXY=', '# HTTP_PROXY=' | Set-Content .env"
powershell -Command "(Get-Content .env) -replace '^HTTPS_PROXY=', '# HTTPS_PROXY=' | Set-Content .env"
echo 代理已禁用！
echo.

echo 建议的模型配置（更快）：
echo   AGENT_LLM_MODEL=qwen-plus
echo   SYNTHESIS_LLM_MODEL=qwen-plus
echo.

echo 是否切换到更快的模型？(Y/N)
set /p choice=
if /i "%choice%"=="Y" (
    echo 正在切换模型...
    powershell -Command "(Get-Content .env) -replace 'AGENT_LLM_MODEL=.*', 'AGENT_LLM_MODEL=qwen-plus' | Set-Content .env"
    powershell -Command "(Get-Content .env) -replace 'SYNTHESIS_LLM_MODEL=.*', 'SYNTHESIS_LLM_MODEL=qwen-plus' | Set-Content .env"
    echo 模型已切换！
)
echo.

echo ========================================
echo 修复完成！
echo ========================================
echo.
echo 请重启服务器以应用更改：
echo   .\scripts\restart_server.ps1
echo.
echo 如需恢复原配置，请使用备份文件：
echo   .env.backup.*
echo.

pause
