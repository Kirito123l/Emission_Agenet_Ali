@echo off
REM 训练列名映射模型

echo ==========================================
echo 训练列名映射模型
echo ==========================================
echo.
echo 训练参数：
echo   - 基础模型: Qwen/Qwen2.5-3B-Instruct
echo   - LoRA rank: 32
echo   - 训练轮数: 8 epochs
echo   - 学习率: 1e-4
echo   - 数据量: 2,550条训练 + 300条验证
echo.
echo 预计训练时间：
echo   - RTX 3090: 1-2小时
echo   - RTX 4090: 30-60分钟
echo.
pause

REM 激活环境
call conda activate local_standardizer

REM 开始训练
python scripts/04_train_lora.py --config configs/column_lora_config.yaml --model_type column

echo.
echo ==========================================
echo 训练完成！
echo ==========================================
echo.
echo 模型保存位置: models/column_lora/final/
echo.
echo 下一步：
echo 1. 运行 evaluate_column.bat 评估模型
pause
