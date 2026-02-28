#!/bin/bash
# VLLM启动脚本 - 用于启动本地标准化模型服务

echo "=========================================="
echo "启动本地标准化模型 VLLM 服务"
echo "=========================================="
echo ""

# 配置
BASE_MODEL="Qwen/Qwen2.5-3B-Instruct"
PORT=8001
GPU_MEMORY_UTIL=0.8

# 获取当前脚本所在目录（WSL2环境）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# LoRA适配器路径（相对于脚本目录）
UNIFIED_LORA="$SCRIPT_DIR/models/unified_lora/final"
COLUMN_LORA="$SCRIPT_DIR/models/column_lora/checkpoint-200"

# 检查LoRA路径是否存在
echo "检查模型文件..."
if [ ! -d "$UNIFIED_LORA" ]; then
    echo "⚠️  警告: Unified LoRA路径不存在: $UNIFIED_LORA"
    echo "   尝试查找其他checkpoint..."
    # 尝试查找最新的checkpoint
    LATEST_UNIFIED=$(find "$SCRIPT_DIR/models/unified_lora" -maxdepth 1 -type d -name "checkpoint-*" | sort -V | tail -1)
    if [ -n "$LATEST_UNIFIED" ]; then
        UNIFIED_LORA="$LATEST_UNIFIED"
        echo "   找到: $UNIFIED_LORA"
    else
        echo "   ❌ 未找到unified模型，请检查训练是否完成"
        exit 1
    fi
fi

if [ ! -d "$COLUMN_LORA" ]; then
    echo "⚠️  警告: Column LoRA路径不存在: $COLUMN_LORA"
    echo "   尝试查找其他checkpoint..."
    # 尝试查找checkpoint-200或最新的checkpoint
    if [ -d "$SCRIPT_DIR/models/column_lora/checkpoint-200" ]; then
        COLUMN_LORA="$SCRIPT_DIR/models/column_lora/checkpoint-200"
    else
        LATEST_COLUMN=$(find "$SCRIPT_DIR/models/column_lora" -maxdepth 1 -type d -name "checkpoint-*" | sort -V | tail -1)
        if [ -n "$LATEST_COLUMN" ]; then
            COLUMN_LORA="$LATEST_COLUMN"
            echo "   找到: $COLUMN_LORA"
        else
            echo "   ❌ 未找到column模型，请检查训练是否完成"
            exit 1
        fi
    fi
fi

echo ""
echo "配置信息:"
echo "  基础模型: $BASE_MODEL"
echo "  端口: $PORT"
echo "  Unified LoRA: $UNIFIED_LORA"
echo "  Column LoRA: $COLUMN_LORA"
echo "  GPU显存利用率: $GPU_MEMORY_UTIL"
echo ""

# 检查VLLM是否安装
if ! command -v vllm &> /dev/null; then
    echo "❌ VLLM未安装"
    echo ""
    echo "请安装VLLM:"
    echo "  pip install vllm"
    echo ""
    exit 1
fi

echo "✅ VLLM已安装"
echo ""
echo "启动VLLM服务..."
echo "提示: 按 Ctrl+C 停止服务"
echo ""

# 启动VLLM
vllm serve "$BASE_MODEL" \
    --enable-lora \
    --lora-modules unified="$UNIFIED_LORA" \
    --lora-modules column="$COLUMN_LORA" \
    --port $PORT \
    --gpu-memory-utilization $GPU_MEMORY_UTIL \
    --max-model-len 2048 \
    --trust-remote-code

# 如果VLLM退出
echo ""
echo "VLLM服务已停止"
