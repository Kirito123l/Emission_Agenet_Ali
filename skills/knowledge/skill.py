"""
知识检索Skill
"""
import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from ..base import BaseSkill, SkillResult, HealthCheckResult
from .retriever import KnowledgeRetriever
from .reranker import KnowledgeReranker
from llm.client import get_llm

logger = logging.getLogger(__name__)


def deduplicate_sources(sources: List[str]) -> List[str]:
    """对参考来源去重"""
    seen = set()
    unique_sources = []

    for source in sources:
        # 标准化文档名称
        normalized = normalize_doc_name(source)

        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_sources.append(source)

    return unique_sources


def normalize_doc_name(name: str) -> str:
    """标准化文档名称"""
    if not name:
        return ""

    # 去除多余空格
    name = ' '.join(name.split())

    # 统一书名号
    name = name.replace('《', '《').replace('》', '》')

    return name


class KnowledgeSkill(BaseSkill):
    """知识检索Skill"""

    REQUIRED_PARAMS = ["query"]
    OPTIONAL_PARAMS = {
        "top_k": 5,
        "expectation": None,  # 期望找到什么类型的信息
    }

    def __init__(self):
        self._retriever = KnowledgeRetriever()
        self._reranker = KnowledgeReranker()
        self._refiner_llm = get_llm("rag_refiner")

    @property
    def name(self) -> str:
        return "query_knowledge"

    @property
    def description(self) -> str:
        return "检索排放相关知识和法规"

    def get_brief_description(self) -> str:
        return "知识检索（必需：query查询问题；可选：top_k返回数量）"

    def execute(self, **params) -> SkillResult:
        # 1. 参数验证
        query = params.get("query")
        if not query:
            return SkillResult(
                success=False,
                error="缺少查询问题",
                metadata={"needs_clarification": True}
            )

        top_k = params.get("top_k", 5)
        expectation = params.get("expectation")

        # 2. 检索
        try:
            results = self._retriever.search(query, top_k=top_k)

            if not results:
                return SkillResult(
                    success=True,
                    data={
                        "query": query,
                        "results": [],
                        "answer": "未找到相关知识，请尝试其他问法。"
                    }
                )

            # 2.5 重排序（如果启用）
            logger.info(f"检索到 {len(results)} 个初始结果")
            reranked_results = self._reranker.rerank(query, results, top_n=top_k)
            logger.info(f"重排序后保留 {len(reranked_results)} 个结果")

            # 3. 使用LLM精炼答案（只生成答案内容，不包含参考文献）
            answer = self._refine_answer(query, reranked_results, expectation)

            # 4. 提取并去重来源
            sources = [r.get("source", "") for r in reranked_results if r.get("source")]
            unique_sources = deduplicate_sources(sources)

            # 5. Python代码添加格式化的参考文献（不依赖LLM）
            logger.info(f"[DEBUG] 原始答案长度: {len(answer)} 字符")
            logger.info(f"[DEBUG] 来源数量: {len(unique_sources)}")

            if unique_sources:
                sources_list = "\n".join([f"{i+1}. {s}" for i, s in enumerate(unique_sources)])
                answer = f"{answer}\n\n**参考文档**：\n{sources_list}"
                logger.info(f"[DEBUG] 添加参考文献后答案长度: {len(answer)} 字符")
                logger.info(f"[DEBUG] 参考文献列表:\n{sources_list}")
            else:
                logger.warning("[DEBUG] 没有找到来源，跳过添加参考文献")

            return SkillResult(
                success=True,
                data={
                    "query": query,
                    "results": reranked_results,
                    "answer": answer,
                    "sources": unique_sources,
                },
                metadata={
                    "top_k": top_k,
                    "num_results": len(reranked_results),
                }
            )

        except Exception as e:
            logger.exception(f"知识检索失败: {e}")
            return SkillResult(success=False, error=str(e))

    def _refine_answer(self, query: str, results: List[Dict], expectation: str = None) -> str:
        """使用LLM精炼检索结果为答案"""
        # 构建检索结果上下文
        context = "\n\n".join([
            f"[来源{i+1}]\n{r.get('content', '')}"
            for i, r in enumerate(results[:3])
        ])

        prompt = f"""请根据以下检索结果，回答用户问题。

**用户问题**: {query}

**检索结果**:
{context}

{"**期望信息**: " + expectation if expectation else ""}

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
   - 提供详细、完整的回答，包括所有相关信息

请生成回答：
"""

        try:
            return self._refiner_llm.chat(prompt)
        except Exception as e:
            logger.error(f"LLM精炼失败: {e}")
            # 回退：直接返回检索结果摘要
            return f"检索到{len(results)}条相关信息：\n" + "\n".join([
                f"- {r.get('content', '')[:100]}..." for r in results[:3]
            ])

    def health_check(self) -> HealthCheckResult:
        healthy, errors = self._retriever.health_check()
        return HealthCheckResult(
            healthy=healthy,
            checks={
                "faiss_index": "dense_index.faiss" not in str(errors),
                "chunks_file": "chunks.jsonl" not in str(errors),
            },
            errors=errors
        )

