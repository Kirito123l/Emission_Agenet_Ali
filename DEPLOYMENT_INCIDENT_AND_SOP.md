# 部署事故复盘与标准操作流程（SOP）

## 📋 文档目的

本文档记录了一次"本地与云服务器页面表现不一致"的真实生产事故，包括根因分析、排查过程、修复方法以及标准化的部署流程，旨在：
- 帮助后续开发者快速理解和解决类似问题
- 建立标准化的部署流程，避免同类问题再次发生
- 提供系统化的故障排查决策树

---

## 🔴 事件背景

### 现象描述

在某次代码更新后，发现以下异常现象：

1. **页面表现不一致**
   - 本地访问 `http://localhost:8000` 显示最新版本界面
   - 公网访问 `http://139.196.235.238:8000` 显示旧版本界面
   - 本地有登录/注册/退出相关UI，但公网页面完全没有这些功能

2. **初步排查方向（后证实为误导）**
   - ❌ 怀疑 Git 代码未同步
   - ❌ 怀疑浏览器缓存问题
   - ❌ 怀疑前端渲染逻辑问题
   - ❌ 怀疑虚拟环境配置不一致
   - ❌ 怀疑静态文件未正确更新

3. **困惑点**
   - 后端接口看起来正常响应
   - GitHub 代码已确认提交并推送
   - 浏览器已清除缓存并强制刷新
   - systemd 服务已重启

### 影响范围

- **用户影响**：所有公网访问用户看到的是旧版本界面，无法使用新功能
- **持续时间**：从发现问题到最终解决约 2 小时
- **业务影响**：用户体验受损，新功能无法使用

---

## 🎯 最终根因

### 真正的问题所在

**服务器上同时存在两套独立部署，导致端口争用和流量路由混乱**

#### 两套部署系统

1. **新部署方式（预期使用）**
   - 部署方式：systemd 服务 + Python 虚拟环境
   - 项目路径：`/opt/emission_agent`
   - 虚拟环境：`/opt/emission_agent/venv`
   - 服务名称：`emission-agent.service`
   - 监听地址：`0.0.0.0:8000`
   - 启动命令：`python run_api.py`

2. **旧部署方式（遗留）**
   - 部署方式：Docker 容器
   - 容器名称：`emission-agent-container`（示例）
   - 端口映射：`0.0.0.0:8000->8000`
   - 镜像版本：旧版本代码构建的镜像
   - 状态：运行中（未被清理）

#### 流量路由问题

```
┌─────────────────────────────────────────┐
│  请求来源                                │
├─────────────────────────────────────────┤
│  localhost:8000      公网IP:8000         │
│       ↓                    ↓             │
│    新服务              旧Docker容器       │
│  (systemd)            (遗留)             │
│       ↓                    ↓             │
│  app.js?v=21         app.js?v=12        │
│  2021行              1450行              │
└─────────────────────────────────────────┘
```

**核心问题**：
- 本地回环地址（`127.0.0.1:8000`）优先命中了新的 systemd 服务
- 公网地址（`139.196.235.238:8000`）因为 Docker 容器的端口映射，部分或全部流量被路由到了旧容器
- 两个服务都监听在 8000 端口，造成端口争用和流量分流

---

## 🔍 关键证据

### 1. 版本差异验证

#### 测试命令
```bash
# 本地回环地址测试
curl -s http://127.0.0.1:8000/ | grep "app.js"
curl -s http://127.0.0.1:8000/app.js | wc -l

# 公网地址测试
curl -s http://139.196.235.238:8000/ | grep "app.js"
curl -s http://139.196.235.238:8000/app.js | wc -l
```

#### 实际结果对比

| 测试项 | 本地回环 (127.0.0.1) | 公网地址 (139.196.235.238) |
|--------|---------------------|---------------------------|
| app.js 引用 | `<script src="app.js?v=21"></script>` | `<script src="app.js?v=12"></script>` |
| app.js 行数 | 2021 行 | 1450 行 |
| 登录功能 | ✅ 有 | ❌ 无 |
| 注册功能 | ✅ 有 | ❌ 无 |

**结论**：两个地址返回的内容完全不同，说明问题不是浏览器缓存，而是服务器端存在多个服务实例。

### 2. 端口监听检查

#### 使用 ss 命令
```bash
ss -tnlp | grep :8000
```

**预期结果**（正常情况）：
```
LISTEN  0  128  0.0.0.0:8000  0.0.0.0:*  users:(("python",pid=12345,fd=3))
```

**实际结果**（异常情况）：
```
LISTEN  0  128  0.0.0.0:8000  0.0.0.0:*  users:(("python",pid=12345,fd=3))
LISTEN  0  128  :::8000       :::*       users:(("docker-proxy",pid=67890,fd=4))
```

**发现**：8000 端口同时被 Python 进程和 docker-proxy 进程监听。

#### 使用 lsof 命令
```bash
lsof -i :8000
```

**结果示例**：
```
COMMAND     PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
python    12345 root    3u  IPv4  xxxxx      0t0  TCP *:8000 (LISTEN)
docker-pr 67890 root    4u  IPv6  xxxxx      0t0  TCP *:8000 (LISTEN)
```

**结论**：确认有两个进程在监听 8000 端口。

### 3. Docker 容器检查

#### 检查运行中的容器
```bash
docker ps
```

**发现**：
```
CONTAINER ID   IMAGE                    COMMAND            CREATED       STATUS       PORTS                    NAMES
abc123def456   emission-agent:v1.0      "python run_api.py" 2 weeks ago   Up 2 weeks   0.0.0.0:8000->8000/tcp   emission-agent-old
```

**关键信息**：
- 容器仍在运行（`Up 2 weeks`）
- 端口映射：`0.0.0.0:8000->8000/tcp`（对外暴露 8000 端口）
- 镜像是旧版本 `v1.0`

#### 检查所有容器（包括停止的）
```bash
docker ps -a
```

### 4. systemd 服务状态
```bash
sudo systemctl status emission-agent
```

**结果**：
```
● emission-agent.service - Emission Agent API Service
   Loaded: loaded (/etc/systemd/system/emission-agent.service; enabled)
   Active: active (running) since 2026-03-10 14:30:00 CST
   Main PID: 12345 (python)
```

**结论**：systemd 服务运行正常，但与 Docker 容器共存导致冲突。

### 5. 判断链总结

```
问题现象：localhost 和公网返回不同版本
    ↓
第一步：排除浏览器缓存
    → curl 直接请求仍有差异 ✅ 不是浏览器问题
    ↓
第二步：检查返回的文件内容
    → app.js 版本号不同（v=21 vs v=12）
    → app.js 行数不同（2021 vs 1450）
    ✅ 确认服务器端返回的就是不同内容
    ↓
第三步：检查端口监听
    → ss/lsof 显示两个进程监听 8000
    ✅ 存在端口争用
    ↓
第四步：检查 Docker 容器
    → docker ps 显示旧容器仍在运行
    → 容器映射了 0.0.0.0:8000->8000
    ✅ 找到根因：旧 Docker 容器仍在提供服务
    ↓
结论：公网流量被路由到旧 Docker 容器
```

---

## 🛠️ 解决步骤

### 标准修复流程

以下是完整的、可直接执行的修复步骤：

#### 1. 停止旧 Docker 容器

```bash
# 查看所有运行中的容器
docker ps

# 停止旧容器（替换为实际容器 ID 或名称）
docker stop <container_id_or_name>

# 示例
docker stop emission-agent-old
# 或使用容器 ID
docker stop abc123def456
```

**预期输出**：
```
abc123def456
```

#### 2. 删除旧容器

```bash
# 删除已停止的容器
docker rm <container_id_or_name>

# 示例
docker rm emission-agent-old
```

**可选：强制删除运行中的容器**
```bash
docker rm -f emission-agent-old
```

#### 3. 验证容器清理

```bash
# 确认没有 emission-agent 相关容器
docker ps -a | grep emission
```

**预期输出**：
```
（空，或没有相关容器）
```

#### 4. 验证端口占用

```bash
# 检查 8000 端口监听情况
ss -tnlp | grep :8000
```

**预期输出**（只有一个 Python 进程）：
```
LISTEN  0  128  0.0.0.0:8000  0.0.0.0:*  users:(("python",pid=12345,fd=3))
```

或使用 lsof：
```bash
lsof -i :8000
```

**预期输出**：
```
COMMAND   PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
python  12345 root    3u  IPv4  xxxxx      0t0  TCP *:8000 (LISTEN)
```

#### 5. 重启 systemd 服务（可选）

```bash
# 重启服务以确保配置生效
sudo systemctl restart emission-agent

# 等待 3 秒让服务完全启动
sleep 3

# 检查服务状态
sudo systemctl status emission-agent
```

#### 6. 验证修复结果

```bash
# 验证本地回环地址
curl -s http://127.0.0.1:8000/ | grep "app.js"
curl -s http://127.0.0.1:8000/app.js | wc -l

# 验证公网地址
curl -s http://139.196.235.238:8000/ | grep "app.js"
curl -s http://139.196.235.238:8000/app.js | wc -l
```

**预期结果**：
- 两个地址返回的 `app.js` 版本号一致（都是 `v=21`）
- 两个地址返回的 `app.js` 行数一致（都是 `2021` 行）

#### 7. 浏览器验证

1. 打开浏览器
2. 访问公网地址：`http://139.196.235.238:8000`
3. 按 `Ctrl+Shift+R`（Windows）或 `Cmd+Shift+R`（Mac）强制刷新
4. 检查页面功能：
   - ✅ 登录按钮可见
   - ✅ 注册按钮可见
   - ✅ 退出按钮可见
   - ✅ 其他新功能正常

---

## ⚠️ 以后如何避免

### 最佳实践与防护措施

#### 1. 单一部署原则

**规则**：同一个项目在同一台服务器上只能保留**一种**对外提供 8000 端口的部署方式。

**执行**：
- ✅ 如果使用 systemd，则**不允许**同时运行 Docker 容器
- ✅ 如果使用 Docker，则**不允许**同时运行 systemd 服务
- ✅ 切换部署方式时，必须完全清理旧的部署方式

**检查命令**：
```bash
# 定期检查端口占用
ss -tnlp | grep :8000

# 定期检查 Docker 容器
docker ps -a | grep emission
```

#### 2. 部署后强制验证

**每次部署后必须执行的验证清单**：

```bash
#!/bin/bash
# 部署后验证脚本

echo "=========================================="
echo "部署后验证检查"
echo "=========================================="

# 1. 检查本地回环版本
echo "1. 检查本地回环地址..."
LOCAL_VERSION=$(curl -s http://127.0.0.1:8000/ | grep -o 'app.js?v=[0-9]*' | grep -o '[0-9]*')
LOCAL_LINES=$(curl -s http://127.0.0.1:8000/app.js | wc -l)
echo "   版本号: v=$LOCAL_VERSION, 行数: $LOCAL_LINES"

# 2. 检查公网版本
echo "2. 检查公网地址..."
PUBLIC_VERSION=$(curl -s http://139.196.235.238:8000/ | grep -o 'app.js?v=[0-9]*' | grep -o '[0-9]*')
PUBLIC_LINES=$(curl -s http://139.196.235.238:8000/app.js | wc -l)
echo "   版本号: v=$PUBLIC_VERSION, 行数: $PUBLIC_LINES"

# 3. 对比版本
echo "3. 对比版本一致性..."
if [ "$LOCAL_VERSION" = "$PUBLIC_VERSION" ] && [ "$LOCAL_LINES" = "$PUBLIC_LINES" ]; then
    echo "   ✅ 版本一致"
else
    echo "   ❌ 版本不一致！"
    echo "   本地: v=$LOCAL_VERSION, $LOCAL_LINES 行"
    echo "   公网: v=$PUBLIC_VERSION, $PUBLIC_LINES 行"
    exit 1
fi

# 4. 检查端口监听
echo "4. 检查端口监听..."
PORT_COUNT=$(ss -tnlp | grep :8000 | wc -l)
if [ "$PORT_COUNT" -eq 1 ]; then
    echo "   ✅ 只有一个进程监听 8000 端口"
    ss -tnlp | grep :8000
else
    echo "   ❌ 异常：有 $PORT_COUNT 个进程监听 8000 端口"
    ss -tnlp | grep :8000
    exit 1
fi

# 5. 检查 Docker 容器
echo "5. 检查 Docker 容器..."
CONTAINER_COUNT=$(docker ps -a | grep emission | wc -l)
if [ "$CONTAINER_COUNT" -eq 0 ]; then
    echo "   ✅ 没有遗留的 Docker 容器"
else
    echo "   ⚠️  警告：发现 $CONTAINER_COUNT 个相关 Docker 容器"
    docker ps -a | grep emission
fi

echo "=========================================="
echo "验证完成"
echo "=========================================="
```

**保存为 `scripts/verify_deployment.sh` 并执行**：
```bash
chmod +x scripts/verify_deployment.sh
./scripts/verify_deployment.sh
```

#### 3. 前端版本号管理

**规则**：每次前端代码更新时，必须递增版本号。

**操作位置**：`web/index.html`

```html
<!-- 修改前 -->
<script src="app.js?v=20"></script>

<!-- 修改后（版本号 +1） -->
<script src="app.js?v=21"></script>
```

**自动化方案**（可选）：
```bash
# 在 package.json 中添加版本管理脚本
{
  "scripts": {
    "bump-version": "node scripts/bump-frontend-version.js"
  }
}
```

#### 4. 不要过早归因于缓存

**错误做法**：
```
问题：页面不一致
  ↓
第一反应：肯定是浏览器缓存问题
  ↓
清除缓存、强制刷新
  ↓
问题依旧，继续怀疑缓存
```

**正确做法**：
```
问题：页面不一致
  ↓
第一步：使用 curl 验证服务器实际返回内容
  ↓
如果 curl 返回就不一致 → 不是缓存问题，是服务器问题
如果 curl 返回一致 → 才考虑浏览器缓存问题
```

**验证命令模板**：
```bash
# 先验证服务器返回，再怀疑浏览器缓存
curl -s http://<your-server>:8000/ | grep "app.js"
curl -s http://<your-server>:8000/app.js | head -20
```

#### 5. 环境一致性检查

**定期检查清单**：
```bash
# 1. 检查 Git 仓库状态
cd /opt/emission_agent
git status
git log -1 --oneline

# 2. 检查虚拟环境
source venv/bin/activate
pip list | grep -E "fastapi|uvicorn"

# 3. 检查服务状态
sudo systemctl status emission-agent

# 4. 检查 Docker 容器（应该为空）
docker ps -a | grep emission

# 5. 检查端口占用（应该只有一个）
ss -tnlp | grep :8000
```

---

## 📚 标准部署 SOP

### 完整部署流程

本项目采用以下标准部署方式：

- **代码托管**：GitHub
- **服务器路径**：`/opt/emission_agent`
- **Python 虚拟环境**：`/opt/emission_agent/venv`
- **服务管理**：systemd (`emission-agent.service`)
- **自动部署**：GitHub Actions
- **手工兜底**：SSH 登录服务器执行命令

---

### 阶段 1：本地开发

#### 1.1 开发代码

```bash
# 在本地仓库开发
cd /path/to/emission_agent

# 创建功能分支（可选）
git checkout -b feature/your-feature

# 进行开发...
```

#### 1.2 本地测试

```bash
# 激活虚拟环境
source venv/bin/activate  # Linux/Mac
# 或
.\venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 启动服务
python run_api.py

# 在浏览器中测试
# http://localhost:8000
```

#### 1.3 更新前端版本号（如有前端改动）

编辑 `web/index.html`：
```html
<!-- 版本号 +1 -->
<script src="app.js?v=22"></script>
```

---

### 阶段 2：提交代码

#### 2.1 提交到 Git

```bash
# 查看改动
git status
git diff

# 添加文件
git add .

# 提交（写清楚改动内容）
git commit -m "feat: 添加用户认证功能

- 新增登录、注册、退出功能
- 更新前端 UI
- 版本号升级至 v=22
"

# 推送到 GitHub
git push origin main
# 或推送功能分支
git push origin feature/your-feature
```

#### 2.2 合并到主分支（如果使用功能分支）

```bash
# 切换到主分支
git checkout main

# 合并功能分支
git merge feature/your-feature

# 推送主分支
git push origin main
```

---

### 阶段 3：自动部署（GitHub Actions）

#### 3.1 触发条件

当代码推送到 `main` 分支时，GitHub Actions 会自动触发部署。

**GitHub Actions 配置文件**：`.github/workflows/deploy.yml`

#### 3.2 部署流程

GitHub Actions 会自动执行以下步骤：

```yaml
1. Checkout 代码
2. 设置 SSH 连接
3. SSH 到服务器执行部署脚本：
   - 进入 /opt/emission_agent
   - git pull 最新代码
   - 激活虚拟环境
   - 安装/更新依赖
   - 重启 systemd 服务
   - 检查服务状态
4. 验证部署结果
```

#### 3.3 查看部署状态

1. 打开 GitHub 仓库页面
2. 点击 **Actions** 标签
3. 查看最新的 workflow 运行状态
4. 如果失败，点击查看详细日志

---

### 阶段 4：手工兜底更新（如果自动部署失败）

#### 4.1 SSH 登录服务器

```bash
ssh root@139.196.235.238
# 或使用配置的用户名
ssh <your-user>@<your-server>
```

#### 4.2 手工更新代码

```bash
# 进入项目目录
cd /opt/emission_agent

# 拉取最新代码
git fetch origin
git reset --hard origin/main

# 激活虚拟环境
source venv/bin/activate

# 更新依赖
pip install -r requirements.txt --upgrade

# 重启服务
sudo systemctl restart emission-agent

# 等待服务启动
sleep 3

# 检查服务状态
sudo systemctl status emission-agent
```

#### 4.3 查看服务日志（如果需要排查问题）

```bash
# 查看 systemd 日志
sudo journalctl -u emission-agent -n 100 --no-pager

# 实时跟踪日志
sudo journalctl -u emission-agent -f

# 查看应用日志（如果有）
tail -f /opt/emission_agent/logs/*.log
```

---

### 阶段 5：部署后验证

#### 5.1 自动验证脚本

```bash
# 在服务器上执行
cd /opt/emission_agent
./scripts/verify_deployment.sh
```

#### 5.2 手工验证步骤

```bash
# 1. 检查本地版本
curl -s http://127.0.0.1:8000/ | grep "app.js"

# 2. 检查公网版本
curl -s http://139.196.235.238:8000/ | grep "app.js"

# 3. 检查行数一致性
curl -s http://127.0.0.1:8000/app.js | wc -l
curl -s http://139.196.235.238:8000/app.js | wc -l

# 4. 检查端口占用（应该只有一个 Python 进程）
ss -tnlp | grep :8000

# 5. 检查 Docker 容器（应该为空）
docker ps -a | grep emission

# 6. 检查 systemd 服务状态
sudo systemctl status emission-agent
```

#### 5.3 浏览器验证

1. 打开浏览器（使用隐私模式避免缓存）
2. 访问公网地址：`http://139.196.235.238:8000`
3. 按 `F12` 打开开发者工具
4. 切换到 **Network** 标签
5. 强制刷新页面（`Ctrl+Shift+R` 或 `Cmd+Shift+R`）
6. 检查 `app.js` 的版本号和文件大小
7. 测试新功能是否正常

---

### 阶段 6：回滚（如果部署出现问题）

#### 6.1 快速回滚到上一个版本

```bash
# SSH 登录服务器
ssh root@139.196.235.238

# 进入项目目录
cd /opt/emission_agent

# 查看最近的提交记录
git log --oneline -5

# 回滚到上一个提交
git reset --hard HEAD~1
# 或回滚到指定提交
git reset --hard <commit-hash>

# 重启服务
sudo systemctl restart emission-agent

# 验证
curl -s http://127.0.0.1:8000/ | grep "app.js"
```

#### 6.2 完整回滚流程

```bash
# 1. 停止服务
sudo systemctl stop emission-agent

# 2. 回滚代码
cd /opt/emission_agent
git reset --hard <previous-commit-hash>

# 3. 恢复依赖（如果需要）
source venv/bin/activate
pip install -r requirements.txt

# 4. 启动服务
sudo systemctl start emission-agent

# 5. 验证
sudo systemctl status emission-agent
```

---

## 🌲 排障决策树

### 问题：页面和本地表现不一致

```
┌─────────────────────────────────────────┐
│ 问题：页面和本地表现不一致                │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│ 第一步：验证服务器实际返回内容             │
│ curl -s http://<server>:8000/ | grep app │
└────────────────┬────────────────────────┘
                 ↓
        ┌────────┴────────┐
        ↓                 ↓
┌──────────────┐   ┌──────────────┐
│ 公网返回不同   │   │ 公网返回相同   │
└──────┬───────┘   └──────┬───────┘
       ↓                  ↓
       │           ┌──────────────┐
       │           │ 浏览器缓存问题 │
       │           │ Ctrl+Shift+R │
       │           └──────────────┘
       ↓
┌─────────────────────────────────────────┐
│ 第二步：检查 app.js 版本号和行数          │
│ curl http://<server>:8000/app.js | wc -l │
└────────────────┬────────────────────────┘
                 ↓
        ┌────────┴────────┐
        ↓                 ↓
┌──────────────┐   ┌──────────────┐
│ 版本不同      │   │ 版本相同      │
└──────┬───────┘   └──────┬───────┘
       ↓                  ↓
       │           ┌──────────────┐
       │           │ 前端渲染问题   │
       │           │ 检查 JS 逻辑  │
       │           └──────────────┘
       ↓
┌─────────────────────────────────────────┐
│ 第三步：检查端口监听情况                  │
│ ss -tnlp | grep :8000                   │
│ lsof -i :8000                           │
└────────────────┬────────────────────────┘
                 ↓
        ┌────────┴────────┐
        ↓                 ↓
┌──────────────┐   ┌──────────────┐
│ 多个进程监听   │   │ 单个进程监听   │
└──────┬───────┘   └──────┬───────┘
       ↓                  ↓
       │           ┌──────────────┐
       │           │ 检查代码差异   │
       │           │ git diff      │
       │           └──────────────┘
       ↓
┌─────────────────────────────────────────┐
│ 第四步：检查 Docker 容器                 │
│ docker ps -a                            │
└────────────────┬────────────────────────┘
                 ↓
        ┌────────┴────────┐
        ↓                 ↓
┌──────────────┐   ┌──────────────┐
│ 发现旧容器     │   │ 没有容器      │
└──────┬───────┘   └──────┬───────┘
       ↓                  ↓
       │           ┌──────────────┐
       │           │ 检查其他服务   │
       │           │ systemctl    │
       │           └──────────────┘
       ↓
┌─────────────────────────────────────────┐
│ 🎯 根因：旧 Docker 容器仍在运行           │
│                                         │
│ 解决方案：                               │
│ 1. docker stop <container>              │
│ 2. docker rm <container>                │
│ 3. 验证端口占用                          │
│ 4. 验证版本一致性                        │
└─────────────────────────────────────────┘
```

### 快速排查命令清单

```bash
# ====================
# 快速排查脚本
# ====================

#!/bin/bash

echo "=== 1. 检查版本一致性 ==="
echo "本地版本："
curl -s http://127.0.0.1:8000/ | grep "app.js"
echo "公网版本："
curl -s http://139.196.235.238:8000/ | grep "app.js"

echo ""
echo "=== 2. 检查文件行数 ==="
echo "本地 app.js 行数："
curl -s http://127.0.0.1:8000/app.js | wc -l
echo "公网 app.js 行数："
curl -s http://139.196.235.238:8000/app.js | wc -l

echo ""
echo "=== 3. 检查端口监听 ==="
ss -tnlp | grep :8000

echo ""
echo "=== 4. 检查端口占用进程 ==="
lsof -i :8000

echo ""
echo "=== 5. 检查 Docker 容器 ==="
docker ps -a | grep emission

echo ""
echo "=== 6. 检查 systemd 服务 ==="
sudo systemctl status emission-agent --no-pager
```

**保存为 `scripts/quick_check.sh` 并执行**：
```bash
chmod +x scripts/quick_check.sh
./scripts/quick_check.sh
```

---

## 📝 本次事故一句话总结

> **服务器上同时运行了新的 systemd 服务和旧的 Docker 容器，两者都监听 8000 端口，导致公网流量被路由到旧容器，返回过时的代码版本。解决方法：停止并删除旧 Docker 容器，确保只有一个服务实例运行。**

---

## ✅ 检查清单（Checklist）

### 部署前检查

- [ ] 本地代码已测试通过
- [ ] 前端版本号已更新（如有前端改动）
- [ ] Git 提交信息清晰明确
- [ ] 代码已推送到 GitHub main 分支

### 部署中检查

- [ ] GitHub Actions workflow 运行成功
- [ ] 没有错误日志输出
- [ ] systemd 服务重启成功

### 部署后检查

- [ ] 本地版本与公网版本一致
- [ ] app.js 版本号一致
- [ ] app.js 文件行数一致
- [ ] 只有一个进程监听 8000 端口
- [ ] 没有遗留的 Docker 容器
- [ ] systemd 服务状态正常
- [ ] 浏览器访问新功能正常

### 定期检查（每周/每月）

- [ ] 清理无用的 Docker 镜像和容器
- [ ] 检查磁盘空间
- [ ] 检查日志文件大小
- [ ] 更新系统依赖
- [ ] 备份重要数据

---

## 🔗 相关文档

- [README.md](./README.md) - 项目简介和快速开始
- [docs/guides/TROUBLESHOOTING.md](./docs/guides/TROUBLESHOOTING.md) - 其他常见问题排查
- [.github/workflows/deploy.yml](./.github/workflows/deploy.yml) - GitHub Actions 部署配置

---

## 📅 文档维护

- **创建日期**：2026-03-11
- **最后更新**：2026-03-11
- **维护者**：DevOps Team
- **适用版本**：v1.0+

---

## 💡 改进建议

如果你在使用过程中发现本文档有任何不清晰或需要补充的地方，请：

1. 在 GitHub 上提交 Issue
2. 或直接提交 Pull Request 更新本文档
3. 或联系 DevOps 团队

**持续改进，让部署更简单、更可靠！**
