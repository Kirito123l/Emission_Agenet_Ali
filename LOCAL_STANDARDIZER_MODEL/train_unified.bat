@echo off
REM 训练统一模型（车型 + 污染物标准化）

echo ==========================================
echo 训练统一模型（车型 + 污染物标准化）
echo ==========================================
echo.
echo 训练参数：
echo   - 基础模型: Qwen/Qwen2.5-3B-Instruct
echo   - LoRA rank: 16
echo   - 训练轮数: 5 epochs
echo   - 学习率: 2e-4
echo   - 数据量: 4,352条训练 + 512条验证
echo.
echo 预计训练时间：
echo   - RTX 3090: 2-3小时
echo   - RTX 4090: 1-2小时
echo.
pause

REM 激活环境
call conda activate local_standardizer

REM 开始训练
python scripts/04_train_lora.py --config configs/unified_lora_config.yaml --model_type unified

echo.
echo ==========================================
echo 训练完成！
echo ==========================================
echo.
echo 模型保存位置: models/unified_lora/final/
echo.
echo 下一步：
echo 1. 运行 evaluate_unified.bat 评估模型
echo 2. 或继续训练列名映射模型: train_column.bat
pause
