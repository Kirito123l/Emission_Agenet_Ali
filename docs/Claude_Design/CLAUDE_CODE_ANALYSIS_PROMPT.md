# Claude Code 代码库深度分析任务

## 任务目标

对 Emission Agent 项目进行全面深度分析，生成一份详尽的架构诊断报告，为后续架构优化提供依据。

## 背景说明

这是一个基于 Agent-Skill 架构的智能机动车排放计算系统。当前系统存在以下担忧：
1. 系统提示词中累积了大量硬编码规则来处理特定问题
2. 交互体验偏向规则驱动而非智能化
3. 需要向 ChatGPT 级别的智能交互体验演进

## 分析要求

### 第一阶段：全面代码扫描

请按以下顺序完整阅读代码库：

```bash
# 1. 项目根目录结构
ls -la
cat README.md
cat ARCHITECTURE.md

# 2. 配置和入口文件
cat config.py
cat main.py
cat run_api.py
cat requirements.txt
cat .env.example

# 3. Agent层 - 核心逻辑（重点关注）
cat agent/core.py
cat agent/context.py
cat agent/validator.py
cat agent/reflector.py
cat agent/learner.py
ls agent/prompts/
cat agent/prompts/system.py
cat agent/prompts/synthesis.py
# 如果存在其他prompt文件也全部读取

# 4. Skills层
cat skills/base.py
cat skills/registry.py

# 5. Skills - 通用工具
cat skills/common/file_analyzer.py
cat skills/common/column_mapper.py

# 6. Skills - 排放因子查询
cat skills/emission_factors/skill.py
cat skills/emission_factors/calculator.py
ls skills/emission_factors/data/

# 7. Skills - 微观排放计算
cat skills/micro_emission/skill.py
cat skills/micro_emission/calculator.py
cat skills/micro_emission/vsp.py
cat skills/micro_emission/excel_handler.py

# 8. Skills - 宏观排放计算
cat skills/macro_emission/skill.py
cat skills/macro_emission/calculator.py
cat skills/macro_emission/excel_handler.py

# 9. Skills - 知识检索
cat skills/knowledge/skill.py
cat skills/knowledge/retriever.py

# 10. 共享模块 - 标准化器
cat shared/standardizer/vehicle.py
cat shared/standardizer/pollutant.py
cat shared/standardizer/constants.py
cat shared/standardizer/cache.py

# 11. LLM管理
cat llm/client.py
cat llm/data_collector.py

# 12. API层
cat api/main.py
cat api/routes.py
cat api/models.py
cat api/session.py

# 13. Web前端
cat web/index.html
cat web/app.js
cat web/styles.css

# 14. 所有文档文件
find . -name "*.md" -type f | head -20
# 逐个读取重要文档

# 15. 测试文件
ls test*.py
cat test_basic.py
cat test_smart_mapping.py

# 16. 数据目录结构
ls -la data/
ls -la data/sessions/ 2>/dev/null || echo "no sessions dir"
ls -la data/collection/ 2>/dev/null || echo "no collection dir"
```

### 第二阶段：深度分析维度

请从以下维度进行深度分析：

#### 2.1 System Prompt 分析
- 找出所有 system prompt 的位置和内容
- 统计 prompt 中的硬编码规则数量
- 识别哪些规则是为了解决特定问题而打的"补丁"
- 分析 prompt 的结构化程度
- 评估 prompt 的可维护性

#### 2.2 Agent 决策逻辑分析
- Agent 如何理解用户意图？
- Agent 如何决定调用哪个 Skill？
- 参数提取的逻辑是硬编码还是LLM驱动？
- 多轮对话中上下文如何影响决策？
- 错误处理和重试逻辑如何实现？

#### 2.3 Skill 层设计分析
- Skill 的抽象程度是否合理？
- Skill 之间是否有重复代码？
- Skill 与 Agent 的耦合程度如何？
- Skill 是否有过度的 if-else 逻辑？

#### 2.4 数据流分析
- 用户输入到最终输出的完整数据流
- 哪些环节存在数据转换？
- 错误信息如何传递？
- 上下文信息如何在各层间流转？

#### 2.5 硬编码规则统计
请统计以下类型的硬编码：
- 字符串匹配规则
- 正则表达式
- if-elif-else 链条
- 魔法数字/字符串
- 枚举/常量映射
- 特殊情况处理

#### 2.6 文件冗余分析
- 是否存在重复或相似的文件？
- 是否有未使用的文件？
- 文档文件是否与代码同步？
- 测试文件覆盖情况

### 第三阶段：生成诊断报告

请生成名为 `ARCHITECTURE_DIAGNOSIS_REPORT.md` 的报告，包含以下章节：

```markdown
# Emission Agent 架构诊断报告

## 执行摘要
[一页纸的关键发现和建议]

## 1. 项目概况
### 1.1 文件结构总览
### 1.2 代码行数统计
### 1.3 依赖关系图

## 2. System Prompt 诊断
### 2.1 Prompt 文件清单
### 2.2 规则分类统计
### 2.3 "补丁式"规则识别
### 2.4 问题严重程度评估

## 3. Agent 层诊断
### 3.1 意图理解机制
### 3.2 决策逻辑流程图
### 3.3 参数提取方式
### 3.4 上下文管理
### 3.5 发现的问题

## 4. Skill 层诊断
### 4.1 Skill 清单与职责
### 4.2 代码重复分析
### 4.3 耦合度评估
### 4.4 发现的问题

## 5. 硬编码规则全览
### 5.1 按位置分类
### 5.2 按类型分类
### 5.3 按严重程度分类
### 5.4 完整规则清单表格

## 6. 数据流分析
### 6.1 主要数据流图
### 6.2 数据转换点
### 6.3 潜在问题点

## 7. 文件健康度分析
### 7.1 冗余文件清单
### 7.2 未使用文件清单
### 7.3 文档同步状态
### 7.4 建议清理的文件

## 8. 与 ChatGPT 体验的差距分析
### 8.1 当前交互模式
### 8.2 期望交互模式
### 8.3 差距识别
### 8.4 改进路径

## 9. 架构优化建议
### 9.1 短期优化（可立即执行）
### 9.2 中期重构（需要2-3周）
### 9.3 长期演进（架构级改动）

## 10. 优先级排序
[按影响程度和实施难度的四象限图]

## 附录
### A. 完整文件树
### B. 所有 Prompt 原文
### C. 硬编码规则详细清单
### D. 代码复杂度统计
```

## 注意事项

1. **必须完整阅读每个文件**，不要跳过任何代码
2. **对于长文件**，使用分段阅读，确保不遗漏
3. **发现问题时记录行号**，便于后续定位
4. **保持客观**，区分"设计选择"和"真正的问题"
5. **给出可操作的建议**，而非泛泛而谈

## 输出位置

将最终报告保存至项目根目录：`./ARCHITECTURE_DIAGNOSIS_REPORT.md`

## 开始执行

请现在开始执行第一阶段的全面代码扫描，然后依次完成后续阶段。在扫描过程中，请实时记录发现的问题和洞察。
