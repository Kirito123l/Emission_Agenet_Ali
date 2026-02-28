# Emission Agent 文档导航

本目录包含项目的所有文档，按类型组织。

---

## 📖 核心文档

### [ARCHITECTURE.md](./ARCHITECTURE.md)
项目架构设计文档，包含：
- 系统架构概述
- 核心组件说明
- 数据流设计
- 技术栈说明

---

## 📊 分析报告 (reports/)

包含各类分析报告、诊断总结和问题分析文档。

**最新报告**:
- `AGENT_RESPONSE_ISSUE_ANALYSIS.md` - Agent回复问题分析
- `CSV_FILES_AUDIT_REPORT.md` - CSV文件审计报告
- `CALCULATORS_CHECK_REPORT.md` - 计算器检查报告
- `CODE_CLEANUP_SUMMARY.md` - 代码清理总结

**查看全部**: [reports/](./reports/)

---

## 📚 使用指南 (guides/)

面向用户和开发者的使用文档。

### 用户指南
- [QUICK_START_GUIDE.md](./guides/QUICK_START_GUIDE.md) - 快速开始指南
- [TROUBLESHOOTING.md](./guides/TROUBLESHOOTING.md) - 故障排除

### 开发指南
- [DEVELOPER_GUIDE.md](./guides/DEVELOPER_GUIDE.md) - 开发者指南
- [本地模型部署指南.md](./guides/本地模型部署指南.md) - 本地模型部署

---

## 🗄️ 归档文档 (archive/)

历史文档、修复记录和阶段性文档的归档。

### 架构升级记录
- `ARCHITECTURE_UPGRADE_COMPLETE.md` - 架构升级完成报告
- `ARCHITECTURE_UPGRADE_PROGRESS.md` - 架构升级进度
- `CODE_CLEANUP_DEV_LOG.md` - 代码清理开发日志

### 问题修复记录
- `DOWNLOAD_BUTTON_FIX.md`
- `LLM_NOT_CALLING_TOOL_FIX.md`
- `MISSING_DATA_FILES_FIX.md`
- `PARAMETER_NAME_MISMATCH_FIX.md`
- `RESPONSE_TRUNCATION_FIX.md`
- `RAG_AND_HISTORY_FIXES.md`

### 阶段完成报告
- `PHASE6_COMPLETE.md` - 阶段6完成
- `PHASE7_COMPLETE.md` - 阶段7完成
- `PHASE8_COMPLETE.md` - 阶段8完成

**查看全部**: [archive/](./archive/)

---

## 🎨 设计文档

### [Claude_Design/](./Claude_Design/)
Claude设计相关的提示词和分析文档

### [designs/](./designs/)
系统设计文档和原始设计资料

---

## 📝 文档规范

### 命名规范
- 分析报告: `{主题}_ANALYSIS.md` 或 `{主题}_REPORT.md`
- 修复记录: `{问题}_FIX.md`
- 使用指南: `{主题}_GUIDE.md`
- 总结文档: `{主题}_SUMMARY.md`

### 文档分类
- **reports/**: 分析报告、诊断总结、审计报告
- **guides/**: 使用指南、开发文档、部署说明
- **archive/**: 历史文档、修复记录、阶段报告

### 文档生命周期
1. 新文档创建在根目录
2. 完成后移动到对应分类目录
3. 过时文档移动到 archive/
4. 6个月后可考虑删除归档文档

---

## 🔗 相关链接

- [项目README](../README.md) - 项目主页
- [API文档](http://localhost:8000/docs) - FastAPI自动生成的API文档
- [GitHub Issues](https://github.com/your-repo/issues) - 问题追踪

---

**最后更新**: 2026-02-17
