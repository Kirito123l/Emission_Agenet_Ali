"""
知识检索重排序器
支持在线API和本地简单重排序
"""
import logging
import re
from typing import List, Dict
from openai import OpenAI
import httpx

from config import get_config

logger = logging.getLogger(__name__)


class KnowledgeReranker:
    """知识检索重排序器"""

    def __init__(self):
        self.config = get_config()
        self.rerank_mode = self.config.rerank_mode
        logger.info(f"知识重排序器初始化 - Rerank模式: {self.rerank_mode}")

        if self.rerank_mode == "api":
            self.client = self._create_api_client()

    def _create_api_client(self) -> OpenAI:
        """创建API客户端（用于在线rerank）"""
        provider = self.config.providers["qwen"]
        api_key = provider["api_key"]
        if not api_key:
            raise ValueError(
                "Rerank API key not configured. "
                "Please set QWEN_API_KEY environment variable."
            )
        proxy = self.config.https_proxy or self.config.http_proxy

        http_client = None
        if proxy:
            http_client = httpx.Client(proxy=proxy, timeout=60.0)
            logger.info(f"Rerank API使用代理: {proxy}")

        return OpenAI(
            api_key=api_key,
            base_url=provider["base_url"],
            http_client=http_client
        )

    def rerank(self, query: str, documents: List[Dict], top_n: int = None) -> List[Dict]:
        """
        对检索结果进行重排序

        Args:
            query: 查询文本
            documents: 检索结果列表，每个元素包含 id, content, score, metadata, source
            top_n: 返回前N个结果，默认使用配置中的值

        Returns:
            重排序后的文档列表
        """
        if not documents:
            return []

        if self.rerank_mode == "none":
            logger.info("Rerank模式为none，跳过重排序")
            return documents

        if top_n is None:
            top_n = self.config.rerank_top_n

        try:
            if self.rerank_mode == "api":
                return self._rerank_api(query, documents, top_n)
            elif self.rerank_mode == "local":
                return self._rerank_local(query, documents, top_n)
            else:
                logger.warning(f"未知的rerank模式: {self.rerank_mode}，返回原始结果")
                return documents[:top_n]

        except Exception as e:
            logger.exception(f"重排序失败: {e}，返回原始结果")
            return documents[:top_n]

    def _rerank_api(self, query: str, documents: List[Dict], top_n: int) -> List[Dict]:
        """使用在线API进行重排序"""
        logger.info(f"使用API重排序 - 模型: {self.config.rerank_model}, 输入文档数: {len(documents)}, 返回数: {top_n}")

        # 准备文档文本列表
        doc_texts = [doc["content"] for doc in documents]

        try:
            # 使用DashScope原生API调用rerank
            # 注意：这里使用httpx直接调用，因为OpenAI SDK不支持rerank
            import dashscope
            from http import HTTPStatus

            # 设置API key
            dashscope.api_key = self.config.providers["qwen"]["api_key"]

            # 调用rerank API
            from dashscope import TextReRank

            response = TextReRank.call(
                model=self.config.rerank_model,
                query=query,
                documents=doc_texts,
                top_n=top_n,
                return_documents=False
            )

            if response.status_code != HTTPStatus.OK:
                logger.error(f"API返回错误: {response.code} - {response.message}")
                return self._rerank_local(query, documents, top_n)

            # 解析响应
            if not hasattr(response.output, 'results'):
                logger.error(f"API返回格式异常")
                return documents[:top_n]

            # 根据rerank结果重新排序
            reranked_docs = []
            for item in response.output.results:
                idx = item.index
                relevance_score = item.relevance_score
                if 0 <= idx < len(documents):
                    doc = documents[idx].copy()
                    doc["rerank_score"] = relevance_score
                    reranked_docs.append(doc)

            logger.info(f"API重排序完成，返回 {len(reranked_docs)} 个文档")
            return reranked_docs

        except ImportError:
            logger.warning("dashscope库未安装，降级到本地重排序")
            return self._rerank_local(query, documents, top_n)
        except Exception as e:
            logger.error(f"API重排序失败: {e}，使用备用方案")
            # 降级到本地重排序
            return self._rerank_local(query, documents, top_n)

    def _rerank_local(self, query: str, documents: List[Dict], top_n: int) -> List[Dict]:
        """使用本地简单算法进行重排序（基于关键词匹配）"""
        logger.info(f"使用本地重排序 - 输入文档数: {len(documents)}, 返回数: {top_n}")

        # 提取查询关键词（简单分词）
        query_keywords = self._extract_keywords(query)

        # 为每个文档计算关键词匹配分数
        for doc in documents:
            content = doc["content"]
            keyword_score = self._calculate_keyword_score(content, query_keywords)

            # 综合原始检索分数和关键词分数
            original_score = doc.get("score", 0.5)
            doc["rerank_score"] = 0.6 * original_score + 0.4 * keyword_score

        # 按rerank_score降序排序
        reranked_docs = sorted(documents, key=lambda x: x.get("rerank_score", 0), reverse=True)

        logger.info(f"本地重排序完成，返回 {min(top_n, len(reranked_docs))} 个文档")
        return reranked_docs[:top_n]

    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词（简单实现）"""
        # 移除标点符号，分词
        text = re.sub(r'[^\w\s]', ' ', text)
        words = text.split()

        # 过滤停用词（简化版）
        stopwords = {'的', '了', '是', '在', '有', '和', '与', '或', '等', '及', '以', '为', '对', '从', '到'}
        keywords = [w for w in words if w and w not in stopwords and len(w) > 1]

        return keywords

    def _calculate_keyword_score(self, content: str, keywords: List[str]) -> float:
        """计算关键词匹配分数"""
        if not keywords:
            return 0.0

        content_lower = content.lower()
        matches = sum(1 for kw in keywords if kw.lower() in content_lower)

        # 归一化到0-1
        score = min(matches / len(keywords), 1.0)
        return score
