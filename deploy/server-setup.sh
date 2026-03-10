#!/bin/bash

# 服务器端配置脚本
# 在服务器上运行此脚本以完成部署前的配置

echo "=========================================="
echo "🔧 服务器部署前配置"
echo "=========================================="

# 检查当前用户
CURRENT_USER=$(whoami)
echo "当前用户: $CURRENT_USER"

# 1. 配置 sudo 免密
echo ""
echo "📝 配置 sudo 免密执行..."
sudo bash -c "cat > /etc/sudoers.d/emission-agent << 'SUDOEOF'
# Allow emission-agent service management without password
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart emission-agent
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl status emission-agent
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl is-active emission-agent
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl start emission-agent
$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl stop emission-agent
SUDOEOF"

sudo chmod 440 /etc/sudoers.d/emission-agent
echo "✅ Sudo 免密配置完成"

# 2. 测试 sudo 免密
echo ""
echo "🧪 测试 sudo 免密..."
if sudo -n systemctl status emission-agent &>/dev/null || sudo -n systemctl is-active emission-agent &>/dev/null; then
    echo "✅ Sudo 免密测试成功"
else
    echo "⚠️  Sudo 免密测试失败，请检查配置"
fi

# 3. 确保项目目录存在
echo ""
echo "📁 检查项目目录..."
if [ -d "/opt/emission_agent" ]; then
    echo "✅ 项目目录存在: /opt/emission_agent"
    cd /opt/emission_agent

    # 检查 Git 仓库
    if [ -d ".git" ]; then
        echo "✅ Git 仓库已初始化"
        git remote -v
    else
        echo "❌ Git 仓库未初始化"
    fi

    # 检查虚拟环境
    if [ -d "venv" ]; then
        echo "✅ 虚拟环境存在"
    else
        echo "❌ 虚拟环境不存在"
    fi

    # 检查 systemd 服务
    if systemctl list-unit-files | grep -q emission-agent; then
        echo "✅ Systemd 服务已配置"
        sudo systemctl status emission-agent --no-pager || true
    else
        echo "❌ Systemd 服务未配置"
    fi
else
    echo "❌ 项目目录不存在: /opt/emission_agent"
fi

# 4. 显示 SSH 公钥（用于 GitHub）
echo ""
echo "🔑 SSH 公钥（用于 GitHub Actions）:"
echo "=========================================="
if [ -f ~/.ssh/id_rsa.pub ]; then
    cat ~/.ssh/id_rsa.pub
else
    echo "⚠️  SSH 密钥不存在，请先生成:"
    echo "   ssh-keygen -t rsa -b 4096 -C 'your_email@example.com'"
fi

echo ""
echo "=========================================="
echo "✅ 服务器配置检查完成"
echo "=========================================="
echo ""
echo "📋 下一步操作:"
echo "1. 确保 GitHub Secrets 已配置:"
echo "   - SERVER_HOST: 139.196.235.238"
echo "   - SERVER_USER: $CURRENT_USER"
echo "   - SERVER_SSH_KEY: 私钥内容 (~/.ssh/id_rsa)"
echo ""
echo "2. 在本地推送代码到 GitHub:"
echo "   git add .github/workflows/deploy.yml deploy/"
echo "   git commit -m 'ci: add GitHub Actions deployment'"
echo "   git push origin main"
echo ""
echo "3. 访问 GitHub Actions 查看部署状态"
echo "=========================================="
