#!/bin/bash

# 服务器代码同步修复脚本
# 在服务器上运行此脚本以确保代码完全同步

set -e

echo "=========================================="
echo "🔧 服务器代码同步修复脚本"
echo "=========================================="

cd /opt/emission_agent

echo ""
echo "📊 当前状态检查..."
echo "当前 commit:"
git log -1 --oneline

echo ""
echo "远程最新 commit:"
git fetch origin
git log origin/main -1 --oneline

echo ""
echo "🔍 检查是否有未提交的修改..."
git status

echo ""
echo "📥 强制同步到远程最新版本..."
git fetch origin
git reset --hard origin/main

echo ""
echo "✅ 同步后的 commit:"
git log -1 --oneline

echo ""
echo "📋 检查关键文件是否存在..."
echo "检查 api/auth.py (认证功能):"
if [ -f "api/auth.py" ]; then
    echo "  ✅ 存在"
    head -5 api/auth.py
else
    echo "  ❌ 不存在"
fi

echo ""
echo "检查 api/database.py (数据库功能):"
if [ -f "api/database.py" ]; then
    echo "  ✅ 存在"
    head -5 api/database.py
else
    echo "  ❌ 不存在"
fi

echo ""
echo "检查 api/routes.py 中的 zip 处理功能:"
if grep -q "application/zip" api/routes.py; then
    echo "  ✅ 包含 zip 处理代码"
else
    echo "  ❌ 不包含 zip 处理代码"
fi

echo ""
echo "检查 api/routes.py 中的游客登录功能:"
if grep -q "get_user_id" api/routes.py; then
    echo "  ✅ 包含游客登录代码"
else
    echo "  ❌ 不包含游客登录代码"
fi

echo ""
echo "🐍 激活虚拟环境并更新依赖..."
source venv/bin/activate
pip install -r requirements.txt --upgrade --quiet

echo ""
echo "🔄 重启服务..."
sudo systemctl restart emission-agent

echo ""
echo "⏳ 等待服务启动..."
sleep 5

echo ""
echo "🔍 检查服务状态..."
if sudo systemctl is-active --quiet emission-agent; then
    echo "  ✅ 服务运行正常"
    sudo systemctl status emission-agent --no-pager | head -20
else
    echo "  ❌ 服务启动失败"
    sudo journalctl -u emission-agent -n 30 --no-pager
    exit 1
fi

echo ""
echo "=========================================="
echo "✅ 代码同步完成！"
echo "=========================================="
echo ""
echo "📝 验证步骤:"
echo "1. 访问 http://139.196.235.238:8000"
echo "2. 测试游客登录功能"
echo "3. 测试上传 zip 文件"
echo ""
