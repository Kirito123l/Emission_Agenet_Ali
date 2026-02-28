# 前端问题诊断

## 当前问题

### 1. 404 错误
```
Failed to load resource: /api/sessions/ffdd6e53/history (404)
```

**原因**: 会话 `ffdd6e53` 不存在于 session_manager 中

### 2. 没有 HTTP 请求日志

**可能原因**:
- print() 语句没有刷新到终端
- 请求被缓存
- 路由没有正确注册

## 诊断步骤

### 步骤 1: 重启服务器并观察启动日志

```bash
# 停止服务器 (Ctrl+C)
# 重新启动
python run_api.py
```

**期望看到**:
```
============================================================
🌿 Emission Agent API Server
============================================================
服务器启动中...
访问地址: http://localhost:8000
API文档: http://localhost:8000/docs
============================================================
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Started server process [xxxxx]
INFO:     Waiting for application startup.
2026-01-26 xx:xx:xx - api.main - INFO - ============================================================
2026-01-26 xx:xx:xx - api.main - INFO - 🌿 Emission Agent API 已启动
2026-01-26 xx:xx:xx - api.main - INFO - ============================================================
INFO:     Application startup complete.
```

### 步骤 2: 打开浏览器并观察终端

1. 打开浏览器: http://localhost:8000
2. **立即查看终端**

**期望看到**:
```
============================================================
🔵 收到会话列表请求
📋 返回 X 个会话
🆔 会话ID列表: ['abc123', 'def456', ...]
============================================================
```

**如果没有看到**: 说明 print() 语句不工作，或者请求没有到达后端

### 步骤 3: 点击历史记录

1. 点击左侧任意历史记录
2. **立即查看终端**

**期望看到**:
```
============================================================
🔵 收到历史记录请求
🆔 会话ID: ffdd6e53
❌ 会话不存在: ffdd6e53
📋 当前会话列表: ['abc123', 'def456', ...]
============================================================
```

**如果看到 "会话不存在"**: 说明会话列表中的 ID 和实际存储的 ID 不匹配

### 步骤 4: 发送新消息

1. 在输入框输入: "测试"
2. 点击发送
3. **立即查看终端**

**期望看到**:
```
============================================================
🔵 收到聊天请求
📝 消息: 测试
🆔 会话ID: None
📎 文件: None
============================================================
```

## 可能的问题和解决方案

### 问题 1: print() 不显示

**原因**: Python 输出缓冲

**解决方案**: 在 run_api.py 中添加:
```python
import sys
sys.stdout.flush()
```

或者运行时使用:
```bash
python -u run_api.py
```

### 问题 2: 会话 ID 不匹配

**原因**:
- 会话列表返回的是旧的会话 ID
- 实际的会话已经被清空或重置
- pickle 加载失败

**解决方案**: 清空会话缓存
```bash
# Windows
del %USERPROFILE%\.release_agent_sessions.pkl

# 或者在 Python 中
import os
from pathlib import Path
session_file = Path.home() / ".release_agent_sessions.pkl"
if session_file.exists():
    os.remove(session_file)
```

### 问题 3: Agent.get_history() 不存在

**原因**: EmissionAgent 类没有 get_history() 方法

**解决方案**: 检查 agent/core.py 是否有此方法

## 快速修复

### 方案 1: 清空会话缓存并重启

```bash
# 1. 停止服务器 (Ctrl+C)

# 2. 删除会话缓存文件
# Windows PowerShell:
Remove-Item $env:USERPROFILE\.release_agent_sessions.pkl -ErrorAction SilentlyContinue

# 3. 重启服务器
python run_api.py

# 4. 刷新浏览器 (Ctrl+F5 强制刷新)
```

### 方案 2: 使用 -u 标志运行

```bash
python -u run_api.py
```

这会禁用 Python 的输出缓冲，确保 print() 立即显示。

### 方案 3: 直接测试 API

打开浏览器访问: http://localhost:8000/docs

这会打开 FastAPI 的自动文档界面，可以直接测试 API 端点。

1. 点击 `GET /api/sessions`
2. 点击 "Try it out"
3. 点击 "Execute"
4. 查看响应和终端日志

## 下一步

请执行以下操作并告诉我结果:

1. **停止服务器** (Ctrl+C)
2. **删除会话缓存**:
   ```powershell
   Remove-Item $env:USERPROFILE\.release_agent_sessions.pkl -ErrorAction SilentlyContinue
   ```
3. **使用 -u 标志重启**:
   ```bash
   python -u run_api.py
   ```
4. **打开浏览器**: http://localhost:8000
5. **查看终端输出**
6. **告诉我看到了什么**

如果还是没有日志，请:
1. 访问 http://localhost:8000/docs
2. 测试 `GET /api/sessions` 端点
3. 截图终端输出
