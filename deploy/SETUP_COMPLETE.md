# GitHub Actions CI/CD 部署配置完成

## ✅ 已创建的文件

```
emission_agent/
├── .github/
│   └── workflows/
│       └── deploy.yml          # GitHub Actions 工作流配置
└── deploy/
    ├── deploy.sh              # 部署脚本 (可执行)
    └── README.md              # 部署文档
```

## 📋 完整的 deploy.yml

```yaml
name: Deploy to Alibaba Cloud

on:
  push:
    branches:
      - main
  workflow_dispatch:  # 允许手动触发

jobs:
  deploy:
    name: Deploy to Production Server
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Setup SSH
        env:
          SSH_PRIVATE_KEY: ${{ secrets.SERVER_SSH_KEY }}
          SERVER_HOST: ${{ secrets.SERVER_HOST }}
          SERVER_USER: ${{ secrets.SERVER_USER }}
        run: |
          mkdir -p ~/.ssh
          echo "$SSH_PRIVATE_KEY" > ~/.ssh/id_rsa
          chmod 600 ~/.ssh/id_rsa
          ssh-keyscan -H $SERVER_HOST >> ~/.ssh/known_hosts
          echo "SSH setup completed"

      - name: Deploy to server
        env:
          SERVER_HOST: ${{ secrets.SERVER_HOST }}
          SERVER_USER: ${{ secrets.SERVER_USER }}
        run: |
          ssh -o StrictHostKeyChecking=no $SERVER_USER@$SERVER_HOST << 'ENDSSH'
            set -e

            echo "=========================================="
            echo "🚀 Starting Deployment"
            echo "=========================================="

            cd /opt/emission_agent

            echo "📥 Pulling latest code from GitHub..."
            git fetch origin
            git reset --hard origin/main

            echo "🐍 Activating virtual environment..."
            source venv/bin/activate

            echo "📦 Installing dependencies..."
            pip install -r requirements.txt --upgrade

            echo "🔄 Restarting service..."
            sudo systemctl restart emission-agent

            sleep 3

            echo "🔍 Checking service status..."
            sudo systemctl status emission-agent --no-pager || true

            echo "=========================================="
            echo "✅ Deployment completed successfully!"
            echo "=========================================="
          ENDSSH

      - name: Verify deployment
        env:
          SERVER_HOST: ${{ secrets.SERVER_HOST }}
          SERVER_USER: ${{ secrets.SERVER_USER }}
        run: |
          ssh -o StrictHostKeyChecking=no $SERVER_USER@$SERVER_HOST << 'ENDSSH'
            if sudo systemctl is-active --quiet emission-agent; then
              echo "✅ Service is running"
              exit 0
            else
              echo "❌ Service is not running"
              exit 1
            fi
          ENDSSH
```

## 📋 完整的 deploy.sh

```bash
#!/bin/bash

set -e

echo "=========================================="
echo "🚀 Emission Agent Deployment Script"
echo "=========================================="

cd /opt/emission_agent

echo "📥 Pulling latest code from GitHub..."
git fetch origin
git reset --hard origin/main

echo "🐍 Activating virtual environment..."
source venv/bin/activate

echo "📦 Installing dependencies..."
pip install -r requirements.txt --upgrade

echo "📁 Ensuring runtime directories exist..."
mkdir -p data/sessions data/collection data/logs logs outputs
chmod 755 data/sessions data/collection data/logs logs outputs

echo "🔄 Restarting service..."
sudo systemctl restart emission-agent

sleep 3

echo "🔍 Checking service status..."
if sudo systemctl is-active --quiet emission-agent; then
    echo "✅ Service is running"
    sudo systemctl status emission-agent --no-pager
else
    echo "❌ Service failed to start"
    sudo systemctl status emission-agent --no-pager
    exit 1
fi

echo "=========================================="
echo "✅ Deployment completed successfully!"
echo "=========================================="
```

## 🚀 使用流程

### 自动部署（推荐）

```bash
# 1. 本地开发
vim api/routes.py

# 2. 提交代码
git add .
git commit -m "feat: add new feature"

# 3. 推送到 GitHub（自动触发部署）
git push origin main

# 4. 查看部署状态
# 访问 GitHub → Actions 标签页
```

### 手动触发部署

1. 访问 GitHub 仓库
2. 点击 "Actions" 标签页
3. 选择 "Deploy to Alibaba Cloud" 工作流
4. 点击 "Run workflow" 按钮

### 服务器手动部署

```bash
ssh root@139.196.235.238
cd /opt/emission_agent
./deploy/deploy.sh
```

## 🔧 服务器配置要求

### 必需配置

1. **SSH 免密登录**
   ```bash
   # 本地生成 SSH 密钥（如果没有）
   ssh-keygen -t rsa -b 4096 -C "your_email@example.com"

   # 复制公钥到服务器
   ssh-copy-id root@139.196.235.238
   ```

2. **Sudo 免密执行**
   ```bash
   # 在服务器上配置
   sudo visudo

   # 添加以下行（替换 root 为实际用户名）
   root ALL=(ALL) NOPASSWD: /bin/systemctl restart emission-agent
   root ALL=(ALL) NOPASSWD: /bin/systemctl status emission-agent
   root ALL=(ALL) NOPASSWD: /bin/systemctl is-active emission-agent
   ```

3. **GitHub Secrets 配置**

   访问 GitHub 仓库 → Settings → Secrets and variables → Actions

   添加以下 secrets:

   - `SERVER_HOST`: `139.196.235.238`
   - `SERVER_USER`: `root`
   - `SERVER_SSH_KEY`: 私钥内容（~/.ssh/id_rsa 的完整内容）

## 📊 部署流程图

```
┌─────────────────┐
│  本地开发修改    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ git push main   │
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│ GitHub Actions 触发     │
│ - Checkout 代码         │
│ - 配置 SSH 连接         │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│ SSH 登录服务器          │
│ 139.196.235.238        │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│ 执行部署脚本            │
│ - git pull              │
│ - pip install           │
│ - systemctl restart     │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│ 验证服务状态            │
│ - 检查服务是否运行      │
└────────┬────────────────┘
         │
         ▼
┌─────────────────┐
│  部署完成 ✅    │
└─────────────────┘
```

## 🔍 故障排查

### 查看 GitHub Actions 日志

1. 访问 GitHub 仓库
2. 点击 "Actions" 标签页
3. 选择失败的工作流运行
4. 查看详细日志

### 查看服务器日志

```bash
# SSH 登录服务器
ssh root@139.196.235.238

# 查看服务状态
sudo systemctl status emission-agent

# 查看实时日志
sudo journalctl -u emission-agent -f

# 查看最近 50 条日志
sudo journalctl -u emission-agent -n 50
```

### 常见问题

**问题 1: SSH 连接失败**
```
解决方案:
1. 检查 SERVER_SSH_KEY 是否正确配置
2. 确认服务器 SSH 服务正常运行
3. 检查服务器防火墙是否允许 SSH 连接
```

**问题 2: 权限不足**
```
解决方案:
1. 确认 sudo 免密配置正确
2. 检查 deploy.sh 是否有执行权限
```

**问题 3: 服务重启失败**
```
解决方案:
1. 手动 SSH 登录服务器
2. 运行: sudo systemctl status emission-agent
3. 查看错误日志: sudo journalctl -u emission-agent -n 50
4. 检查 Python 依赖是否安装完整
```

## 📝 下一步操作

1. **提交配置文件到 GitHub**
   ```bash
   git add .github/workflows/deploy.yml deploy/
   git commit -m "ci: add GitHub Actions deployment workflow"
   git push origin main
   ```

2. **验证自动部署**
   - 推送后访问 GitHub Actions 标签页
   - 查看工作流是否成功运行
   - 访问 http://139.196.235.238:8000 验证服务

3. **配置通知（可选）**
   - 在 GitHub 仓库设置中配置邮件通知
   - 或集成 Slack/钉钉等通知服务

## ✅ 完成清单

- [x] 创建 `.github/workflows/deploy.yml`
- [x] 创建 `deploy/deploy.sh` 并赋予执行权限
- [x] 创建部署文档 `deploy/README.md`
- [x] 配置自动部署流程
- [x] 配置手动触发选项
- [x] 添加服务验证步骤
- [ ] 提交到 GitHub
- [ ] 验证自动部署功能
- [ ] 配置服务器 sudo 免密

---

**部署配置已完成！现在可以提交到 GitHub 并测试自动部署功能。**
