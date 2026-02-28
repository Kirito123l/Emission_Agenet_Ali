"""
知识检索器
从 rag_json_mcp 迁移并适配
支持本地BGE-M3和在线API两种embedding模式
"""
import json
import pickle
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import numpy as np

from config import get_config

logger = logging.getLogger(__name__)

# 可选依赖
try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    logger.warning("faiss 未安装，知识检索功能不可用")

try:
    from FlagEmbedding import BGEM3FlagModel
    BGE_AVAILABLE = True
except ImportError:
    BGE_AVAILABLE = False
    logger.warning("FlagEmbedding 未安装，本地embedding功能不可用")

try:
    import dashscope
    DASHSCOPE_AVAILABLE = True
except ImportError:
    DASHSCOPE_AVAILABLE = False
    logger.warning("dashscope 未安装，在线embedding功能不可用")


class KnowledgeRetriever:
    """知识检索器"""

    def __init__(self, index_dir: Path = None):
        self.config = get_config()
        self.index_dir = index_dir or Path(__file__).parent / "index"
        self.dense_index = None
        self.chunk_ids = []
        self.chunks = {}
        self.encoder = None
        self._loaded = False

        # 根据配置选择embedding模式
        self.embedding_mode = self.config.embedding_mode
        logger.info(f"知识检索器初始化 - Embedding模式: {self.embedding_mode}")

        # API模式下设置dashscope
        if self.embedding_mode == "api" and DASHSCOPE_AVAILABLE:
            api_key = self.config.providers["qwen"]["api_key"]
            if not api_key:
                logger.error("QWEN_API_KEY not set, API embedding will fail")
            dashscope.api_key = api_key

    def load(self) -> bool:
        """加载索引"""
        if self._loaded:
            return True

        if not FAISS_AVAILABLE:
            logger.error("faiss 不可用")
            return False

        try:
            # 加载FAISS索引
            index_path = self.index_dir / "dense_index.faiss"
            if index_path.exists():
                self.dense_index = faiss.read_index(str(index_path))
            else:
                logger.error(f"索引文件不存在: {index_path}")
                return False

            # 加载chunk IDs
            ids_path = self.index_dir / "chunk_ids.pkl"
            if ids_path.exists():
                with open(ids_path, "rb") as f:
                    self.chunk_ids = pickle.load(f)

            # 加载chunks内容
            chunks_path = self.index_dir / "chunks.jsonl"
            if chunks_path.exists():
                with open(chunks_path, "r", encoding="utf-8") as f:
                    for line in f:
                        chunk = json.loads(line)
                        chunk_id = chunk.get("chunk_id") or chunk.get("id")
                        if chunk_id:
                            self.chunks[chunk_id] = chunk

            # 根据模式加载编码器
            if self.embedding_mode == "local":
                if not BGE_AVAILABLE:
                    logger.error("本地embedding模式需要FlagEmbedding库，但未安装")
                    return False
                logger.info("加载本地BGE-M3模型...")
                self.encoder = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
                logger.info("本地BGE-M3模型加载完成")
            elif self.embedding_mode == "api":
                if not DASHSCOPE_AVAILABLE:
                    logger.error("在线embedding模式需要dashscope库，但未安装")
                    return False
                logger.info("使用在线API embedding模式")
                self.encoder = "api"  # 标记为API模式
            else:
                logger.error(f"未知的embedding模式: {self.embedding_mode}")
                return False

            self._loaded = True
            logger.info(f"知识库加载完成: {len(self.chunks)} 个文档块")
            return True

        except Exception as e:
            logger.exception(f"加载索引失败: {e}")
            return False

    def _encode_query(self, query: str) -> np.ndarray:
        """
        编码查询文本为向量

        Args:
            query: 查询文本

        Returns:
            查询向量 (1, dimension)
        """
        if self.embedding_mode == "local":
            # 本地BGE-M3编码
            query_output = self.encoder.encode([query], return_dense=True, return_sparse=False)
            return query_output['dense_vecs']
        elif self.embedding_mode == "api":
            # 在线API编码
            try:
                from dashscope import TextEmbedding
                from http import HTTPStatus

                response = TextEmbedding.call(
                    model=self.config.embedding_model,
                    input=query,
                    dimension=self.config.embedding_dimension
                )

                if response.status_code != HTTPStatus.OK:
                    logger.error(f"API embedding调用失败: {response.code} - {response.message}")
                    raise RuntimeError(f"API调用失败: {response.message}")

                # 提取embedding向量
                embedding = response.output['embeddings'][0]['embedding']
                return np.array([embedding], dtype=np.float32)

            except Exception as e:
                logger.error(f"API embedding调用失败: {e}")
                raise
        else:
            raise ValueError(f"未知的embedding模式: {self.embedding_mode}")

    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """
        检索相关文档

        Args:
            query: 查询文本
            top_k: 返回结果数量

        Returns:
            [{"id": str, "content": str, "score": float, "metadata": dict}, ...]
        """
        if not self._loaded:
            if not self.load():
                return []

        if not self.encoder or not self.dense_index:
            return []

        try:
            # 编码查询
            query_vector = self._encode_query(query)

            # FAISS检索
            distances, indices = self.dense_index.search(query_vector, top_k)

            results = []
            for i, (dist, idx) in enumerate(zip(distances[0], indices[0])):
                if idx < 0 or idx >= len(self.chunk_ids):
                    continue

                chunk_id = self.chunk_ids[idx]
                chunk = self.chunks.get(chunk_id, {})

                results.append({
                    "id": chunk_id,
                    "content": chunk.get("content", ""),
                    "score": float(1 / (1 + dist)),  # 转换为相似度分数
                    "metadata": chunk.get("metadata", {}),
                    "source": chunk.get("metadata", {}).get("provenance", {}).get("doc_title", ""),
                })

            return results

        except Exception as e:
            logger.exception(f"检索失败: {e}")
            return []

    def health_check(self) -> Tuple[bool, List[str]]:
        """健康检查"""
        errors = []

        if not FAISS_AVAILABLE:
            errors.append("faiss 未安装")

        if self.embedding_mode == "local" and not BGE_AVAILABLE:
            errors.append("本地embedding模式需要FlagEmbedding库，但未安装")

        if self.embedding_mode == "api" and not DASHSCOPE_AVAILABLE:
            errors.append("在线embedding模式需要dashscope库，但未安装")

        index_path = self.index_dir / "dense_index.faiss"
        if not index_path.exists():
            errors.append(f"索引文件不存在: {index_path}")

        chunks_path = self.index_dir / "chunks.jsonl"
        if not chunks_path.exists():
            errors.append(f"文档文件不存在: {chunks_path}")

        return len(errors) == 0, errors
