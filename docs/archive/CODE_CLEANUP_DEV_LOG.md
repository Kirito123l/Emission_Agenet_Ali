# 开发日志：代码清理任务

**日期**: 2026-02-17
**任务类型**: 代码清理
**优先级**: P0
**预计工时**: 30 分钟

---

## 背景

架构升级已完成，所有设计目标已达成。现在需要清理遗留代码，保持代码库整洁。

根据 `CODEBASE_ANALYSIS_REPORT.md` 的分析：
- `agent/` 和 `agent_old/` 目录完全废弃，无任何引用
- `skills/` 目录大部分已迁移到 `tools/`，仅 `skills/knowledge/` 还在使用
- `legacy/` 目录是旧代码备份

---

## 任务清单

### Task 1: 删除废弃目录 (5 分钟)

**目标**: 删除完全废弃的目录

**执行步骤**:

```bash
# 1. 确认这些目录没有被引用
grep -r "from agent\." . --include="*.py" | grep -v __pycache__ | grep -v legacy
grep -r "from agent_old\." . --include="*.py" | grep -v __pycache__

# 2. 如果没有引用，删除目录
rm -rf agent/
rm -rf agent_old/

# 3. 如果存在 legacy/ 且不需要，也删除
rm -rf legacy/
```

**验证**:
- [ ] `agent/` 已删除
- [ ] `agent_old/` 已删除
- [ ] `legacy/` 已删除（如果存在）
- [ ] 服务器能正常启动

---

### Task 2: 清理 skills/ 目录 (10 分钟)

**目标**: 删除 `skills/` 中已迁移到 `tools/` 的子目录，仅保留 `skills/knowledge/`

**当前 skills/ 结构**:
```
skills/
├── base.py              # 保留（knowledge 依赖）
├── registry.py          # 保留（knowledge 依赖）
├── __init__.py          # 保留
├── common/              # 删除
├── emission_factors/    # 删除（已迁移到 tools/emission_factors.py）
├── micro_emission/      # 删除（已迁移到 tools/micro_emission.py）
├── macro_emission/      # 删除（已迁移到 tools/macro_emission.py）
└── knowledge/           # 保留（tools/knowledge.py 依赖它）
```

**执行步骤**:

```bash
# 1. 确认哪些 skills 还在被使用
grep -r "from skills\." . --include="*.py" | grep -v __pycache__ | grep -v "skills/"

# 2. 删除已迁移的 skills 子目录
rm -rf skills/common/
rm -rf skills/emission_factors/
rm -rf skills/micro_emission/
rm -rf skills/macro_emission/

# 3. 保留以下文件（knowledge 依赖）:
#    - skills/base.py
#    - skills/registry.py
#    - skills/__init__.py
#    - skills/knowledge/ (整个目录)
```

**验证**:
- [ ] `skills/common/` 已删除
- [ ] `skills/emission_factors/` 已删除
- [ ] `skills/micro_emission/` 已删除
- [ ] `skills/macro_emission/` 已删除
- [ ] `skills/knowledge/` 保留且完整
- [ ] `skills/base.py` 保留
- [ ] 服务器能正常启动
- [ ] 知识检索功能正常（测试："什么是国六排放标准？"）

---

### Task 3: 清理 llm/ 目录 (5 分钟)

**目标**: 检查 `llm/` 目录是否还在使用，如果没有则删除

**执行步骤**:

```bash
# 1. 检查 llm/ 是否被引用
grep -r "from llm\." . --include="*.py" | grep -v __pycache__ | grep -v "llm/"
grep -r "from llm import" . --include="*.py" | grep -v __pycache__ | grep -v "llm/"

# 2. 如果没有引用，删除
rm -rf llm/

# 3. 如果有引用，记录下来，暂不删除
```

**验证**:
- [ ] 确认 `llm/` 的引用情况
- [ ] 如果无引用，已删除
- [ ] 服务器能正常启动

---

### Task 4: 最终验证 (10 分钟)

**目标**: 确保清理后系统功能正常

**测试清单**:

```bash
# 1. 启动服务器
.\scripts\start_server.ps1

# 2. 访问 Web 界面
# http://localhost:8000/web/index.html
```

**功能测试**:

| 测试项 | 测试方法 | 预期结果 |
|--------|----------|----------|
| 知识检索 | 问 "什么是国六排放标准？" | 返回答案 + 参考文献 |
| 排放因子查询 | 问 "查询小汽车的 CO2 排放因子" | 返回图表 |
| 微观排放计算 | 上传 CSV + "帮我计算排放" | 返回表格 + 下载链接 |
| 宏观排放计算 | 上传路段数据 + "计算路段排放" | 返回表格 + 下载链接 |

**验证清单**:
- [ ] 服务器正常启动，无报错
- [ ] 知识检索功能正常
- [ ] 排放因子查询功能正常
- [ ] 微观排放计算功能正常
- [ ] 宏观排放计算功能正常
- [ ] 前端页面正常显示

---

## 清理后的目录结构

```
emission_agent/
├── core/                  # 核心架构 ✅
│   ├── router.py
│   ├── assembler.py
│   ├── executor.py
│   ├── memory.py
│   └── __init__.py
│
├── tools/                 # 工具层 ✅
│   ├── base.py
│   ├── definitions.py
│   ├── registry.py
│   ├── emission_factors.py
│   ├── micro_emission.py
│   ├── macro_emission.py
│   ├── file_analyzer.py
│   ├── knowledge.py
│   └── __init__.py
│
├── services/              # 服务层 ✅
│   ├── standardizer.py
│   ├── llm_client.py
│   ├── config_loader.py
│   └── __init__.py
│
├── calculators/           # 计算引擎 ✅
│   ├── emission_factors.py
│   ├── micro_emission.py
│   ├── macro_emission.py
│   ├── vsp.py
│   └── data/
│
├── skills/                # 精简后 ✅
│   ├── base.py            # 保留
│   ├── registry.py        # 保留
│   ├── __init__.py        # 保留
│   └── knowledge/         # 保留（RAG）
│
├── api/                   # API 层 ✅
├── web/                   # 前端 ✅
├── config/                # 配置 ✅
├── shared/                # 共享工具 ✅
├── data/                  # 数据目录 ✅
├── logs/                  # 日志目录 ✅
│
├── main.py
├── run_api.py
├── config.py
└── requirements.txt

已删除:
├── agent/                 ❌ 已删除
├── agent_old/             ❌ 已删除
├── legacy/                ❌ 已删除
├── llm/                   ❌ 已删除（如无引用）
├── skills/common/         ❌ 已删除
├── skills/emission_factors/ ❌ 已删除
├── skills/micro_emission/   ❌ 已删除
└── skills/macro_emission/   ❌ 已删除
```

---

## 回滚方案

如果清理后出现问题，可以通过 Git 恢复：

```bash
# 查看删除的文件
git status

# 恢复单个目录
git checkout HEAD -- agent/

# 恢复所有删除的文件
git checkout HEAD -- .
```

---

## 完成标准

- [ ] 所有废弃目录已删除
- [ ] skills/ 只保留 knowledge 相关文件
- [ ] 服务器正常启动
- [ ] 所有核心功能正常
- [ ] 代码行数从 ~14,000 行减少到 ~10,000 行

---

## 注意事项

1. **先检查再删除**: 每个目录删除前都要确认没有被引用
2. **保留 Git 历史**: 不要使用 `git rm`，直接 `rm -rf` 即可，Git 会自动追踪
3. **DEBUG 日志暂不处理**: 保留现有的 DEBUG 日志，后续再统一处理
4. **不要修改功能代码**: 本次只做清理，不修改任何功能逻辑

开始执行！
