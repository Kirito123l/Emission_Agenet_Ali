# 信息收集任务：新旧架构数据格式对比

## 目标

在修复之前，我需要完整了解新旧架构的数据格式差异。请收集以下信息并生成一份详细报告。

---

## Part 1: 旧架构数据格式

### 1.1 查看旧架构的 SkillResult 定义

```bash
# 找到 SkillResult 类的定义
grep -r "class SkillResult" legacy/ --include="*.py" -A 20

# 或者
cat legacy/skills/base.py | head -100
```

### 1.2 查看旧架构微观排放的返回格式

```bash
# 查看 micro_emission skill 的 execute 方法返回
cat legacy/skills/micro_emission/skill.py | grep -A 50 "return SkillResult"
```

### 1.3 查看旧架构的 Synthesis 逻辑

```bash
# 查看旧的 synthesis 方法
cat legacy/agent/core.py | grep -A 100 "def _synthesize"

# 查看旧的 SYNTHESIS_PROMPT
cat legacy/agent/core.py | grep -A 50 "SYNTHESIS_PROMPT"
```

### 1.4 查看旧架构 API 返回格式

```bash
# 查看旧的 chat 路由返回什么
cat api/routes.py | grep -B 5 -A 30 "def chat"
```

---

## Part 2: 新架构数据格式

### 2.1 查看新架构的 ToolResult 定义

```bash
# 找到 ToolResult 类的定义
grep -r "class ToolResult" tools/ core/ --include="*.py" -A 20

# 或者
cat tools/base.py | head -50
```

### 2.2 查看新架构微观排放的返回格式

```bash
# 查看 micro_emission tool 的 execute 方法返回
cat tools/micro_emission.py | grep -A 50 "return ToolResult"

# 查看完整的 execute 方法
cat tools/micro_emission.py | grep -B 5 -A 100 "async def execute"
```

### 2.3 查看新架构的 Router 数据提取

```bash
# 查看 router 如何提取 table_data
cat core/router.py | grep -A 20 "_extract_table_data"

# 查看 router 如何提取 download_file
cat core/router.py | grep -A 20 "_extract_download_file"

# 查看 RouterResponse 定义
cat core/router.py | grep -A 10 "class RouterResponse"
```

### 2.4 查看新架构的 Synthesis 逻辑

```bash
# 查看 SYNTHESIS_PROMPT
cat core/router.py | grep -A 30 "SYNTHESIS_PROMPT"

# 查看 _synthesize_results 方法
cat core/router.py | grep -A 50 "_synthesize_results"
```

---

## Part 3: 实际数据对比

### 3.1 找一个成功的旧会话记录

```bash
# 列出历史会话
ls -lt data/sessions/history/ | head -20

# 找一个有 table_data 的会话（文件大小较大的可能有完整数据）
# 查看其中一个
cat data/sessions/history/[选择一个session_id].json | python -m json.tool | head -100
```

### 3.2 找一个新架构的会话记录

```bash
# 查看最近的会话
cat data/sessions/history/$(ls -t data/sessions/history/ | head -1) | python -m json.tool | head -100
```

### 3.3 对比前端收到的数据

```bash
# 如果有请求日志
cat logs/requests.log | tail -200 | grep -A 20 "response"
```

---

## Part 4: 前端期望的格式

### 4.1 查看前端如何处理数据

```bash
# 查看前端 JS 如何处理 table_data
cat web/app.js | grep -B 5 -A 20 "table_data"

# 查看前端如何处理 download_file
cat web/app.js | grep -B 5 -A 20 "download"

# 查看前端如何渲染消息
cat web/app.js | grep -B 5 -A 30 "renderMessage\|displayMessage"
```

### 4.2 查看前端的数据模型

```bash
# 查看前端期望的响应结构
cat web/app.js | grep -B 5 -A 20 "response\."
```

---

## Part 5: 生成对比报告

请将收集到的信息整理成以下格式的报告：

```markdown
# 新旧架构数据格式对比报告

## 1. 返回数据结构对比

### 旧架构 (SkillResult)
```python
{
    "success": bool,
    "data": {...},
    "summary": str,
    "metadata": {
        "download_file": {...}
    }
}
```

### 新架构 (ToolResult)
```python
{
    ...
}
```

### 差异分析
- 字段 A: 旧架构有，新架构无
- 字段 B: 位置不同（旧在 metadata，新在...）
- ...

## 2. table_data 格式对比

### 旧架构
```python
{
    "headers": [...],
    "rows": [...]
}
```

### 新架构
```python
...
```

### 差异分析
- ...

## 3. download_file 格式对比

### 旧架构
...

### 新架构
...

## 4. Synthesis 逻辑对比

### 旧架构 SYNTHESIS_PROMPT
...

### 新架构 SYNTHESIS_PROMPT
...

### 差异分析
- ...

## 5. API 返回格式对比

### 旧架构返回给前端
```json
{
    "reply": "...",
    "table_data": {...},
    "download_file": "..."
}
```

### 新架构返回给前端
```json
...
```

## 6. 前端期望的格式

前端代码显示它期望：
- table_data: {...格式}
- chart_data: {...格式}
- download_file: {...格式}

## 7. 问题总结

根据对比，发现以下问题：
1. ...
2. ...
3. ...

## 8. 修复建议

1. 需要修改的文件和位置
2. 具体修改内容
```

---

## 执行说明

1. **按顺序执行** Part 1-5 的命令
2. **记录所有输出**（即使是空的或报错的）
3. **生成对比报告** 按 Part 5 的格式
4. **保存报告** 到 `ARCHITECTURE_DATA_FORMAT_COMPARISON.md`

这份报告将帮助我们精确定位问题并制定修复方案。
