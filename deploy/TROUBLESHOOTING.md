# 服务器代码不同步问题 - 诊断与解决方案

## 问题描述

云服务器上的代码版本落后于本地，缺少以下功能：
- ❌ 游客登录功能
- ❌ 用户注册功能
- ❌ ZIP 文件处理功能
- ❌ 上传 ZIP 文件显示 0B

## 问题原因分析

虽然本地代码已经推送到 GitHub，但服务器上的代码可能由于以下原因未能正确同步：

1. **Git 缓存问题**: 服务器的 git 可能缓存了旧版本
2. **文件权限问题**: 某些文件可能没有正确更新
3. **服务未重启**: 代码更新后服务没有重新加载
4. **依赖未更新**: requirements.txt 更新后依赖未安装

## 解决方案

### 方案 1: 使用自动修复脚本（推荐）

在本地执行以下命令：

```bash
cd ~/Agent1/emission_agent
./deploy/run-fix-on-server.sh
```

这个脚本会：
1. 上传修复脚本到服务器
2. 在服务器上执行完整的同步和验证流程
3. 检查关键功能是否存在
4. 重启服务

### 方案 2: 手动在服务器上执行

SSH 登录服务器后执行：

```bash
ssh root@139.196.235.238

cd /opt/emission_agent

# 1. 强制同步到最新版本
git fetch origin
git reset --hard origin/main

# 2. 查看当前 commit（应该是 31de308）
git log -1 --oneline

# 3. 验证关键文件
ls -la api/auth.py api/database.py
grep -n "application/zip" api/routes.py
grep -n "get_user_id" api/routes.py

# 4. 更新依赖
source venv/bin/activate
pip install -r requirements.txt --upgrade

# 5. 重启服务
sudo systemctl restart emission-agent

# 6. 检查服务状态
sleep 3
sudo systemctl status emission-agent
journalctl -u emission-agent -n 20 --no-pager
```

### 方案 3: 触发 GitHub Actions 重新部署

在本地执行：

```bash
cd ~/Agent1/emission_agent

# 创建一个空提交触发部署
git commit --allow-empty -m "trigger: force redeploy"
git push origin main

# 访问 GitHub Actions 查看部署进度
# https://github.com/Kirito123l/Emission_Agenet_Ali/actions
```

## 验证步骤

部署完成后，执行以下验证：

### 1. 检查服务器代码版本

```bash
ssh root@139.196.235.238
cd /opt/emission_agent
git log -1 --oneline
# 应该显示: 31de308 retry deploy
```

### 2. 检查关键文件是否存在

```bash
# 检查认证相关文件
ls -la api/auth.py api/database.py

# 检查 routes.py 中的关键功能
grep -c "application/zip" api/routes.py  # 应该 > 0
grep -c "get_user_id" api/routes.py      # 应该 > 0
grep -c "RegisterRequest" api/routes.py  # 应该 > 0
```

### 3. 测试 API 功能

```bash
# 测试服务是否运行
curl http://139.196.235.238:8000

# 测试游客模式
curl -X POST http://139.196.235.238:8000/api/chat \
  -H "Content-Type: application/json" \
  -H "X-User-ID: guest-test-123" \
  -d '{"message": "你好"}'

# 测试注册接口
curl -X POST http://139.196.235.238:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "testuser", "email": "test@example.com", "password": "test123"}'
```

### 4. 测试文件上传

在浏览器中访问 http://139.196.235.238:8000，测试：
- 游客模式登录
- 上传 Excel 文件
- 上传 ZIP 文件（应该能正确显示文件大小）

## 常见问题排查

### 问题 1: 服务器代码版本正确但功能不工作

**原因**: 服务未重启，仍在运行旧代码

**解决**:
```bash
sudo systemctl restart emission-agent
sudo systemctl status emission-agent
```

### 问题 2: ZIP 文件上传显示 0B

**原因**:
1. 前端代码未更新
2. 服务器端 routes.py 缺少 ZIP 处理逻辑

**解决**:
```bash
# 检查 routes.py 是否包含 ZIP 处理
grep -A 10 "application/zip" /opt/emission_agent/api/routes.py

# 如果没有，强制重新拉取
cd /opt/emission_agent
git fetch origin
git reset --hard origin/main
sudo systemctl restart emission-agent
```

### 问题 3: 游客登录不工作

**原因**:
1. 缺少 auth.py 或 database.py
2. 数据库未初始化

**解决**:
```bash
# 检查文件是否存在
ls -la /opt/emission_agent/api/auth.py
ls -la /opt/emission_agent/api/database.py

# 检查数据库
ls -la /opt/emission_agent/data/users.db

# 重启服务让数据库自动初始化
sudo systemctl restart emission-agent
```

### 问题 4: GitHub Actions 部署成功但代码未更新

**原因**: 部署脚本可能有问题

**解决**:
```bash
# 查看 GitHub Actions 日志
# https://github.com/Kirito123l/Emission_Agenet_Ali/actions

# 手动执行部署脚本
ssh root@139.196.235.238
cd /opt/emission_agent
./deploy/deploy.sh
```

## 预防措施

为避免将来出现类似问题：

### 1. 在部署脚本中添加验证步骤

已在 `deploy/deploy.sh` 中添加：
```bash
# 验证关键文件
echo "Verifying critical files..."
test -f api/auth.py || echo "WARNING: auth.py missing"
test -f api/database.py || echo "WARNING: database.py missing"
grep -q "application/zip" api/routes.py || echo "WARNING: ZIP handling missing"
```

### 2. 使用版本标签

```bash
# 在本地打标签
git tag -a v1.0.0 -m "Release v1.0.0 with guest login and ZIP support"
git push origin v1.0.0

# 在服务器上检查版本
git describe --tags
```

### 3. 定期检查代码一致性

创建定时任务检查服务器代码版本：
```bash
# 添加到 crontab
0 */6 * * * cd /opt/emission_agent && git fetch origin && git diff --stat HEAD origin/main | mail -s "Code Sync Check" admin@example.com
```

## 快速命令参考

```bash
# 本地推送代码
git add .
git commit -m "your message"
git push origin main

# 服务器同步代码
ssh root@139.196.235.238 "cd /opt/emission_agent && git pull origin main && sudo systemctl restart emission-agent"

# 检查服务器状态
ssh root@139.196.235.238 "systemctl status emission-agent && journalctl -u emission-agent -n 20"

# 强制重新部署
git commit --allow-empty -m "trigger: force redeploy" && git push origin main
```

## 联系支持

如果问题仍未解决，请提供以下信息：

1. 服务器 git 日志: `git log -5 --oneline`
2. 服务状态: `systemctl status emission-agent`
3. 最近日志: `journalctl -u emission-agent -n 50`
4. 文件列表: `ls -la api/`
