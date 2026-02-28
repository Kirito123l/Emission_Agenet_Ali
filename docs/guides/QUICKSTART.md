# 🌿 Emission Agent - 快速启动

机动车排放计算助手 Web应用

---

## 🚀 快速启动（3步）

### 1. 安装依赖

```bash
cd D:\Agent_MCP\emission_agent
pip install -r requirements.txt
```

### 2. 启动服务

```bash
python run_api.py
```

### 3. 访问应用

打开浏览器访问：**http://localhost:8000**

---

## ✨ 功能特性

- 🔍 **排放因子查询** - 查询各类车型的排放因子曲线
- 📊 **微观排放计算** - 基于轨迹数据的逐秒排放计算
- 🗺️ **宏观排放计算** - 路段级排放清单计算
- 📚 **知识问答** - 排放相关知识检索
- 📁 **Excel批量处理** - 支持Excel文件输入输出
- 📈 **数据可视化** - 交互式图表展示
- 💬 **增量对话** - 智能上下文记忆

---

## 📖 使用示例

### 示例1：查询排放因子

```
输入: "查询2020年小汽车的CO2和NOx排放因子"
输出: 显示排放因子曲线图，可切换污染物
```

### 示例2：轨迹排放计算

```
1. 点击附件按钮
2. 选择轨迹Excel文件（test_input.xlsx）
3. 输入: "计算这个轨迹的排放"
4. 输出: 显示计算结果表格，可下载Excel
```

### 示例3：路段排放计算

```
1. 点击附件按钮
2. 选择路段Excel文件（test_macro_input_simple.xlsx）
3. 输入: "计算这些道路的排放"
4. 输出: 显示计算结果表格，可下载Excel
```

---

## 🔗 访问地址

- **前端界面**: http://localhost:8000
- **API文档**: http://localhost:8000/docs
- **健康检查**: http://localhost:8000/api/health

---

## 🧪 测试

运行自动化测试：

```bash
python test_api_simple.py
```

预期输出：
```
[PASS] Health check OK
[PASS] Session created
[PASS] Chat message sent successfully
[PASS] Frontend accessible
[PASS] API docs accessible

Test Results: 5/5 passed
```

---

## 📚 文档

- **启动指南**: `WEB_STARTUP_GUIDE.md`
- **完成报告**: `PHASE7_COMPLETION_REPORT.md`
- **开发进度**: `PROGRESS.md`
- **API文档**: http://localhost:8000/docs

---

## 🛠️ 技术栈

**后端**:
- FastAPI - Web框架
- Uvicorn - ASGI服务器
- Pydantic - 数据验证

**前端**:
- Tailwind CSS - 样式框架
- ECharts - 图表库
- Material Symbols - 图标

**Agent**:
- OpenAI API - LLM服务
- MOVES模型 - 排放计算

---

## 📦 项目结构

```
emission_agent/
├── api/           # API层
├── web/           # 前端
├── agent/         # Agent层
├── skills/        # Skills层
├── run_api.py     # 启动脚本
└── requirements.txt
```

---

## ❓ 常见问题

**Q: 端口被占用怎么办？**
A: 修改 `run_api.py` 中的 `port=8000` 为其他端口

**Q: 如何停止服务？**
A: 按 `Ctrl+C`

**Q: 如何查看日志？**
A: 服务启动后会在终端显示日志

---

## 📝 版本信息

- **版本**: v2.2
- **更新日期**: 2026-01-25
- **状态**: 生产就绪 ✅

---

## 📧 支持

如有问题，请查看：
- API文档: http://localhost:8000/docs
- 启动指南: `WEB_STARTUP_GUIDE.md`
- 完成报告: `PHASE7_COMPLETION_REPORT.md`

---

**Powered by Claude Sonnet 4.5** 🤖
