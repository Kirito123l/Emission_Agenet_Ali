# 优化任务：改进知识检索回答的排版样式

## 当前问题

知识检索的回答样式不够美观：
- 标题层级混乱（一、二、三 + 加粗 + bullet points）
- 格式不统一
- 视觉效果差

## 目标样式

参考 ChatGPT/Claude 的回答风格，简洁、清晰、易读：

```markdown
国六排放标准（即《重型柴油车污染物排放限值及测量方法》GB 17691-2018 及《轻型汽车污染物排放限值及测量方法》GB 18352.6-2016）的具体要求如下：

### 适用车型范围

**重型车辆（GB 17691-2018）**
适用于装用压燃式发动机或气体燃料点燃式发动机的以下车型：
- M₂、M₃ 类（客车，含城市公交、长途客运、校车等）
- N₁、N₂、N₃ 类（货车，含环卫车、轻/中/重型卡车等）
- 总质量 > 3500 kg 的 M₁ 类（大型乘用车）

**轻型车辆（GB 18352.6-2016）**
适用于最大设计总质量 ≤ 3500 kg 的 M₁、M₂、N₁ 类汽车（家用轿车、SUV、小型厢式货车等）[来源2][来源3]。

### 测试方法

- **型式认证循环**：采用 WLTC（全球统一轻型车辆测试循环），替代原 NEDC
- **实验室台架测试**：用于型式检验、生产一致性检查
- **实际道路 PEMS 测试**：用于在用车符合性检查
- **CO₂ 分段测量**：按 WLTC 划分低速、中速、高速、超高速四段

### 污染物排放限值

⚠️ 本次检索未获取到具体限值数值表格。如需详细数值，建议查阅：
- GB 17691-2018 附录 A/B（重型柴油车）
- GB 18352.6-2016 表 1-4（轻型汽油车）

---

**参考文档：**
1. 重型柴油车污染物排放限值及测量方法
2. 轻型汽车污染物排放限值及测量方法
3. 轻型汽车污染物排放限值及测量方法（中国第六阶段）
```

## 修复方案

### 修改 skills/knowledge/skill.py 的 _refine_answer 方法

找到 `_refine_answer` 方法中的 prompt，修改格式要求：

```python
REFINE_PROMPT = """请根据以下检索结果，回答用户问题。

**用户问题**: {query}

**检索结果**:
{context}

## 回答要求

1. **格式规范**：
   - 使用 Markdown 格式
   - 使用 ### 作为主要章节标题（不要用"一、二、三"）
   - 使用 **加粗** 作为小标题或强调
   - 使用 - 作为列表项（不要用 •）
   - 段落之间保留空行

2. **结构清晰**：
   - 开头用 1-2 句话概述
   - 按主题分成 2-4 个章节
   - 每个章节内容精炼

3. **引用格式**：
   - 在陈述事实时用 [来源1]、[来源2] 标注
   - 不要添加"参考文档"部分（系统会自动添加）

4. **风格要求**：
   - 专业但易懂
   - 简洁，避免冗余
   - 重要信息用 **加粗** 或 ⚠️ 提示

## 示例格式

```
这是对问题的简要概述，包含核心要点[来源1]。

### 第一个主题

**小标题1**
- 要点一
- 要点二[来源2]

**小标题2**
- 要点三
- 要点四

### 第二个主题

内容描述...[来源3]

⚠️ 重要提示或注意事项
```

请根据检索结果生成回答：
"""
```

### 修改位置

**文件**: `skills/knowledge/skill.py`

找到 `_refine_answer` 方法（大约在 120-180 行），替换其中的 prompt。

### 完整代码修改

```python
async def _refine_answer(self, query: str, search_results: List[Dict], sources: List[Dict]) -> str:
    """使用 LLM 优化答案"""
    
    # 构建检索上下文
    context_parts = []
    for i, result in enumerate(search_results[:5], 1):
        content = result.get("content", "")[:1500]  # 限制长度
        source_name = result.get("source", f"文档{i}")
        context_parts.append(f"[来源{i}] {source_name}:\n{content}")
    
    context = "\n\n---\n\n".join(context_parts)
    
    # 优化后的 prompt
    prompt = f"""请根据以下检索结果，回答用户问题。

**用户问题**: {query}

**检索结果**:
{context}

## 回答要求

1. **格式规范**：
   - 使用 Markdown 格式
   - 使用 ### 作为主要章节标题（不要用"一、二、三"这种中文序号）
   - 使用 **加粗** 作为小标题或关键词强调
   - 使用 - 作为列表项
   - 段落之间保留空行

2. **结构清晰**：
   - 开头用 1-2 句话概述核心答案
   - 按主题分成 2-4 个章节（用 ### 标题）
   - 每个章节内容精炼，避免重复

3. **引用格式**：
   - 在陈述事实时用 [来源1]、[来源2] 标注来源
   - 不要在末尾添加"参考文档"或"参考来源"部分（系统会自动添加）

4. **风格要求**：
   - 专业但通俗易懂
   - 简洁明了，避免冗余表述
   - 重要信息或警告用 ⚠️ 标记
   - 如果信息不完整，诚实说明

请生成回答："""

    try:
        response = await self._llm.chat(
            messages=[{"role": "user", "content": prompt}],
            system="你是一个专业的技术文档助手，擅长将复杂信息整理成清晰易读的格式。"
        )
        return response.content
    except Exception as e:
        logger.error(f"LLM refinement failed: {e}")
        # Fallback: 返回原始搜索结果的摘要
        return self._format_raw_results(search_results)
```

## 验证

修改后重启服务器，问同样的问题，回答应该：
- ✅ 使用 ### 章节标题（不是"一、二、三"）
- ✅ 使用 **加粗** 小标题
- ✅ 使用 - 列表项
- ✅ 结构清晰，层级分明
- ✅ 末尾有参考文档列表

## 可选：前端 Markdown 渲染优化

如果前端的 Markdown 渲染效果不好，也可以优化 `web/app.js` 中的渲染样式：

```javascript
// 添加自定义 Markdown 样式
const markdownStyles = `
.markdown-body h3 {
    font-size: 1.1rem;
    font-weight: 600;
    margin-top: 1.5rem;
    margin-bottom: 0.5rem;
    color: #1f2937;
    border-bottom: 1px solid #e5e7eb;
    padding-bottom: 0.25rem;
}

.markdown-body strong {
    color: #059669;
}

.markdown-body ul {
    margin-left: 1.5rem;
    margin-bottom: 1rem;
}

.markdown-body li {
    margin-bottom: 0.25rem;
}

.markdown-body p {
    margin-bottom: 0.75rem;
    line-height: 1.6;
}
`;
```

开始执行修复！
