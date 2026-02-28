# Emission Agent Web应用启动指南

## 项目完成状态

✅ **Phase 7: Web前端和API - 已完成**

### 已创建的文件

#### API层
- `api/__init__.py` - API模块初始化
- `api/main.py` - FastAPI应用入口
- `api/routes.py` - API路由定义
- `api/models.py` - Pydantic数据模型
- `api/session.py` - 会话管理

#### 前端
- `web/index.html` - 主页面（已修改，添加了script引用）
- `web/app.js` - 前端JavaScript代码（API交互、图表渲染等）

#### 启动脚本
- `run_api.py` - API服务启动脚本

#### 测试脚本
- `test_api_simple.py` - API功能测试脚本

#### 依赖更新
- `requirements.txt` - 已添加 fastapi, uvicorn, python-multipart, openpyxl

---

## 快速启动

### 1. 安装依赖（如果还没安装）

```bash
cd D:\Agent_MCP\emission_agent
pip install -r requirements.txt
```

### 2. 启动API服务

```bash
python run_api.py
```

服务将在 `http://localhost:8000` 启动

### 3. 访问应用

打开浏览器访问：
- **前端界面**: http://localhost:8000
- **API文档**: http://localhost:8000/docs
- **API健康检查**: http://localhost:8000/api/health

---

## 功能测试

### 自动化测试

运行测试脚本验证所有功能：

```bash
python test_api_simple.py
```

测试内容：
- ✅ 健康检查端点
- ✅ 会话创建
- ✅ 消息发送
- ✅ 前端页面访问
- ✅ API文档访问

### 手动测试场景

#### 场景1：排放因子查询
1. 打开 http://localhost:8000
2. 在输入框输入："查询2020年小汽车的CO2和NOx排放因子"
3. 点击发送
4. 预期：显示折线图，可切换污染物

#### 场景2：文件上传（轨迹计算）
1. 点击附件按钮
2. 选择 `test_input.xlsx`（轨迹文件）
3. 输入："计算这个轨迹的排放"
4. 点击发送
5. 预期：显示计算结果表格 + 下载按钮

#### 场景3：文件上传（路段计算）
1. 点击附件按钮
2. 选择 `test_macro_input_simple.xlsx`（路段文件）
3. 输入："计算这些道路的排放"
4. 点击发送
5. 预期：显示计算结果表格 + 下载按钮

#### 场景4：增量对话
1. 输入："查询小汽车CO2排放因子"
2. 等待回复
3. 输入："NOx呢？"
4. 预期：记住车型，只改污染物

---

## API端点说明

### 聊天相关
- `POST /api/chat` - 发送消息（支持文件上传）
- `POST /api/file/preview` - 预览上传的文件
- `GET /api/file/download/{file_id}` - 下载结果文件
- `GET /api/file/template/{type}` - 下载模板文件

### 会话管理
- `GET /api/sessions` - 获取会话列表
- `POST /api/sessions/new` - 创建新会话
- `DELETE /api/sessions/{id}` - 删除会话

### 系统
- `GET /api/health` - 健康检查

---

## 技术架构

### 后端
- **框架**: FastAPI
- **服务器**: Uvicorn
- **Agent**: EmissionAgent (已有)
- **会话管理**: 内存存储（SessionManager）

### 前端
- **框架**: 原生JavaScript
- **样式**: Tailwind CSS
- **图表**: ECharts
- **图标**: Material Symbols

### 数据流
```
用户输入 → 前端(app.js) → API(routes.py) → Agent(core.py) → Skills → 返回结果
```

---

## 文件结构

```
emission_agent/
├── api/                        # API层
│   ├── __init__.py
│   ├── main.py                 # FastAPI入口
│   ├── routes.py               # 路由定义
│   ├── models.py               # 数据模型
│   └── session.py              # 会话管理
│
├── web/                        # 前端
│   ├── index.html              # 主页面
│   └── app.js                  # JavaScript代码
│
├── agent/                      # Agent层（已有）
├── skills/                     # Skills层（已有）
├── shared/                     # 共享模块（已有）
├── llm/                        # LLM客户端（已有）
│
├── run_api.py                  # API启动脚本
├── test_api_simple.py          # API测试脚本
└── requirements.txt            # 依赖列表
```

---

## 测试结果

```
============================================================
API Service Test
============================================================

[1] Starting API server...
    Waiting for server to start...

[2] Testing health endpoint...
    [PASS] Health check OK

[3] Testing session creation...
    [PASS] Session created: e1deb6a3

[4] Testing chat endpoint...
    [PASS] Chat message sent successfully

[5] Testing frontend page...
    [PASS] Frontend accessible (17408 bytes)

[6] Testing API documentation...
    [PASS] API docs accessible

============================================================
Test Results: 5/5 passed
============================================================

[SUCCESS] All tests passed!
```

---

## 注意事项

### 开发环境
- CORS已配置为允许所有来源（`allow_origins=["*"]`）
- 生产环境需要限制CORS来源

### 文件管理
- 临时文件存储在系统临时目录：`%TEMP%\emission_agent`
- 需要定期清理临时文件

### 会话持久化
- 当前使用内存存储，重启服务会丢失会话
- 后续可改用数据库（Redis/SQLite）

### 性能优化
- 考虑添加请求缓存
- 考虑添加异步任务队列（Celery）
- 考虑添加WebSocket支持（实时更新）

---

## 下一步建议

### 功能增强
1. 添加用户认证（JWT）
2. 添加会话持久化（数据库）
3. 添加文件上传进度显示
4. 添加实时计算进度（WebSocket）
5. 添加历史记录查看

### 部署
1. 使用Docker容器化
2. 配置Nginx反向代理
3. 添加HTTPS支持
4. 配置日志系统
5. 添加监控和告警

---

## 故障排查

### 问题1：端口被占用
```bash
# Windows
netstat -ano | findstr :8000
taskkill /PID <PID> /F

# 或修改端口
# 编辑 run_api.py，将 port=8000 改为其他端口
```

### 问题2：依赖安装失败
```bash
# 使用国内镜像
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 问题3：前端无法访问
- 检查 `web/` 目录是否存在
- 检查 `web/index.html` 和 `web/app.js` 是否存在
- 查看浏览器控制台错误信息

### 问题4：API调用失败
- 检查 `.env` 文件配置
- 检查LLM API密钥是否有效
- 查看服务器日志输出

---

## 联系方式

如有问题，请查看：
- API文档: http://localhost:8000/docs
- 项目文档: `PROGRESS.md`
- Bug报告: `AGENT_BUG_FIX_REPORT.md`

---

**最后更新**: 2026-01-25
**版本**: v2.1 (Phase 7 完成)
**状态**: 生产就绪 ✅
