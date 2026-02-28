# Emission Agent 优化计划

**分析日期**: 2026-01-24
**基于**: 实际用户对话测试结果

## 当前问题分析

### 问题1: JSON解析失败（Critical）

**现象**:
```
You: 机动车尾气检测有哪些方法？
JSON解析失败，原始内容: [query_knowledge: query: 机动车尾气检测方法]
Agent: 抱歉，我没有完全理解您的问题，请再说一遍或提供更多细节。
```

**根本原因**:
- Planning LLM返回了简写格式: `[query_knowledge: query: 机动车尾气检测方法]`
- 当前JSON解析器只能处理 `{...}` 格式，无法处理 `[...]` 简写

**影响**: 用户体验差，需要重新提问

**优先级**: ⚠️ Critical

**解决方案**: ✅ 已实现
- 添加简写格式检测: `\[(\w+):\s*(\w+):\s*(.+)\]`
- 自动转换为标准JSON格式
- 代码已更新到 `llm/client.py`

---

## 优化计划

### Priority 1: 提升Planning LLM稳定性 ⚠️

**目标**: 减少JSON格式错误

**方案A: 强化System Prompt**
```python
# agent/prompts/system.py
# 在系统提示开头添加：
"""
## 重要：输出格式要求

你必须始终返回有效的JSON格式，结构如下：
{
  "understanding": "对用户意图的理解",
  "plan": [
    {
      "skill": "技能名称",
      "params": {"参数名": "参数值"},
      "purpose": "执行目的"
    }
  ],
  "needs_clarification": false,
  "clarification_message": null
}

禁止使用简写格式如 [skill_name: param: value]。
"""
```

**方案B: 添加Few-Shot示例**
- 在system prompt中添加3-5个完整的JSON示例
- 覆盖各种场景（完整参数、缺少参数、增量对话）

**方案C: 使用更稳定的模型**
- 当前: qwen-plus
- 备选: qwen-max (更强推理能力)
- 或: claude-3-5-sonnet (JSON格式更稳定)

**实施建议**: 先尝试方案A+B，如果仍有问题再考虑方案C

---

### Priority 2: 知识检索结果优化 📊

**当前表现**: ✅ 良好
- 答案详细、结构清晰
- 来源可追溯

**可优化点**:

#### 2.1 答案长度控制
**问题**: 第一个回答过长（~500字），可能超出用户期望

**方案**:
```python
# skills/knowledge/skill.py
def _refine_answer(self, query: str, results: List[Dict], expectation: str = None) -> str:
    prompt = f"""基于以下检索到的知识，回答用户问题。

## 要求
1. 回答简洁明了，控制在200字以内
2. 如果内容复杂，使用表格或列表
3. 核心信息优先
4. 引用来源编号
"""
```

#### 2.2 相关性过滤
**方案**: 添加相似度阈值
```python
# skills/knowledge/retriever.py
def search(self, query: str, top_k: int = 5, min_score: float = 0.5) -> List[Dict]:
    # 过滤低相关性结果
    results = [r for r in results if r['score'] >= min_score]
```

#### 2.3 多轮对话支持
**当前**: 知识检索不支持增量对话

**方案**: 添加对话历史到检索上下文
```python
# agent/core.py
def _plan(self, user_input: str) -> Dict[str, Any]:
    # 如果是知识检索，添加对话历史摘要
    if "知识" in user_input or "什么是" in user_input:
        context_summary = self._context.build_context_summary()
        user_input = f"{context_summary}\n\n当前问题: {user_input}"
```

---

### Priority 3: 性能优化 ⚡

#### 3.1 模型加载优化
**问题**: BGE-M3模型首次加载慢（~10秒）

**方案**:
```python
# skills/knowledge/retriever.py
class KnowledgeRetriever:
    _shared_encoder = None  # 类级别共享

    def load(self):
        if KnowledgeRetriever._shared_encoder is None:
            KnowledgeRetriever._shared_encoder = BGEM3FlagModel(...)
        self.encoder = KnowledgeRetriever._shared_encoder
```

#### 3.2 检索结果缓存
**方案**:
```python
from functools import lru_cache

@lru_cache(maxsize=100)
def search_cached(self, query: str, top_k: int) -> tuple:
    return tuple(self.search(query, top_k))
```

#### 3.3 批量查询优化
**场景**: 用户问"PM2.5和CO2的排放因子"

**当前**: 串行执行2次查询
**优化**: 并行执行
```python
import asyncio

async def execute_plan_parallel(self, plan: List[Dict]):
    tasks = [self._execute_skill_async(step) for step in plan]
    return await asyncio.gather(*tasks)
```

---

### Priority 4: 用户体验增强 ✨

#### 4.1 进度提示优化
**当前**: "⠧ 思考中..."

**优化**: 显示具体步骤
```
⠧ 正在检索知识库...
⠧ 正在分析结果...
⠧ 正在生成回答...
```

#### 4.2 错误提示友好化
**当前**: "JSON解析失败，原始内容: [query_knowledge: ...]"

**优化**: 隐藏技术细节
```
⚠️ 系统处理出现问题，正在重试...
```

#### 4.3 快捷命令支持
```python
# main.py
SHORTCUTS = {
    "/help": "显示帮助",
    "/clear": "清空历史",
    "/stats": "显示统计",
    "/export": "导出对话",
}
```

#### 4.4 对话历史查看
```python
You: /history
Agent:
最近5轮对话：
1. 什么是国六排放标准？ → [知识检索]
2. 机动车尾气检测有哪些方法？ → [失败]
3. 轻型车和重型车的分类标准是什么？ → [知识检索]
```

---

### Priority 5: 数据质量提升 📈

#### 5.1 知识库更新机制
**当前**: 静态知识库

**方案**: 定期更新
```python
# scripts/update_knowledge.py
def update_knowledge_base():
    # 1. 爬取最新法规
    # 2. 重新分块
    # 3. 重建索引
    # 4. 验证质量
```

#### 5.2 答案质量评估
**方案**: 添加用户反馈
```python
You: 轻型车和重型车的分类标准是什么？
Agent: [回答...]

这个回答有帮助吗？ [👍 有帮助] [👎 没帮助]
```

#### 5.3 检索质量监控
```python
# 记录检索指标
{
    "query": "国六排放标准",
    "top_score": 0.85,
    "avg_score": 0.72,
    "num_results": 5,
    "user_satisfied": True
}
```

---

## 实施优先级

### 立即实施 (本周)
1. ✅ JSON解析简写格式支持 - 已完成
2. 🔄 强化System Prompt - 添加格式要求
3. 🔄 答案长度控制 - 修改refiner prompt

### 短期实施 (2周内)
4. 模型加载优化 - 共享encoder
5. 错误提示友好化 - 隐藏技术细节
6. 进度提示优化 - 显示具体步骤

### 中期实施 (1个月内)
7. 检索结果缓存 - LRU cache
8. 相关性过滤 - 添加阈值
9. 快捷命令支持 - /help, /clear等

### 长期实施 (按需)
10. 批量查询并行化 - asyncio
11. 知识库更新机制 - 定期爬取
12. 答案质量评估 - 用户反馈

---

## 测试计划

### 回归测试
```bash
# 测试所有核心功能
python test_comprehensive.py

# 测试JSON解析容错
python test_json_parsing.py

# 测试知识检索
python test_knowledge.py
```

### 压力测试
```python
# 测试100次连续查询
for i in range(100):
    response = agent.chat("国六排放标准")
    assert "国六" in response
```

### 用户场景测试
1. 新用户首次使用
2. 连续多轮对话
3. 混合使用多个Skill
4. 错误输入处理

---

## 成功指标

### 稳定性指标
- JSON解析成功率: 95% → 99%
- 查询成功率: 90% → 98%
- 系统可用性: 99%

### 性能指标
- 首次响应时间: <15秒
- 后续响应时间: <5秒
- 知识检索时间: <3秒

### 质量指标
- 答案相关性: >85%
- 用户满意度: >80%
- 来源准确性: 100%

---

## 总结

**当前状态**: 功能完整，但稳定性需提升

**核心问题**: JSON解析失败导致用户体验下降

**解决方案**:
1. ✅ 已添加简写格式支持
2. 🔄 需强化System Prompt
3. 🔄 需优化答案长度

**预期效果**:
- JSON解析成功率提升到99%
- 用户满意度提升到85%+
- 系统更稳定、更快速、更友好

---

**编写日期**: 2026-01-24
**状态**: 待实施
**优先级**: High
