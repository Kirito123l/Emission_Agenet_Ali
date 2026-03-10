#!/bin/bash

# 本地执行脚本：上传修复脚本到服务器并执行

SERVER_HOST="139.196.235.238"
SERVER_USER="root"
SERVER_PATH="/opt/emission_agent"

echo "=========================================="
echo "📤 上传修复脚本到服务器"
echo "=========================================="

# 上传修复脚本
scp deploy/fix-server-sync.sh ${SERVER_USER}@${SERVER_HOST}:${SERVER_PATH}/deploy/

echo ""
echo "✅ 上传完成"
echo ""
echo "=========================================="
echo "🚀 在服务器上执行修复脚本"
echo "=========================================="

# SSH 到服务器并执行脚本
ssh ${SERVER_USER}@${SERVER_HOST} << 'ENDSSH'
cd /opt/emission_agent
chmod +x deploy/fix-server-sync.sh
./deploy/fix-server-sync.sh
ENDSSH

echo ""
echo "=========================================="
echo "✅ 修复完成！"
echo "=========================================="
