import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()
PROJECT_ROOT = Path(__file__).parent

@dataclass
class LLMAssignment:
    provider: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 8000  # Increased to 8000 for complex multi-tool synthesis responses

@dataclass
class Config:
    def __post_init__(self):
        self.providers = {
            "qwen": {"api_key": os.getenv("QWEN_API_KEY"), "base_url": os.getenv("QWEN_BASE_URL")},
            "deepseek": {"api_key": os.getenv("DEEPSEEK_API_KEY"), "base_url": os.getenv("DEEPSEEK_BASE_URL")},
            "local": {"api_key": os.getenv("LOCAL_LLM_API_KEY"), "base_url": os.getenv("LOCAL_LLM_BASE_URL")},
        }

        self.agent_llm = LLMAssignment(
            provider=os.getenv("AGENT_LLM_PROVIDER", "qwen"),
            model=os.getenv("AGENT_LLM_MODEL", "qwen-plus"),
            temperature=0.0  # v2.0+: 降低temperature提高确定性
        )
        self.standardizer_llm = LLMAssignment(
            provider=os.getenv("STANDARDIZER_LLM_PROVIDER", "qwen"),
            model=os.getenv("STANDARDIZER_LLM_MODEL", "qwen-turbo-latest"),
            temperature=0.1, max_tokens=200
        )
        self.synthesis_llm = LLMAssignment(
            provider=os.getenv("SYNTHESIS_LLM_PROVIDER", "qwen"),
            model=os.getenv("SYNTHESIS_LLM_MODEL", "qwen-plus")
        )
        self.rag_refiner_llm = LLMAssignment(
            provider=os.getenv("RAG_REFINER_LLM_PROVIDER", "qwen"),
            model=os.getenv("RAG_REFINER_LLM_MODEL", "qwen-plus")
        )

        self.enable_llm_standardization = os.getenv("ENABLE_LLM_STANDARDIZATION", "true").lower() == "true"
        self.enable_standardization_cache = os.getenv("ENABLE_STANDARDIZATION_CACHE", "true").lower() == "true"
        self.enable_data_collection = os.getenv("ENABLE_DATA_COLLECTION", "true").lower() == "true"

        self.data_collection_dir = PROJECT_ROOT / os.getenv("DATA_COLLECTION_DIR", "data/collection")
        self.log_dir = PROJECT_ROOT / os.getenv("LOG_DIR", "data/logs")
        self.outputs_dir = PROJECT_ROOT / os.getenv("OUTPUTS_DIR", "outputs")

        self.data_collection_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)

        # 代理设置
        self.http_proxy = os.getenv("HTTP_PROXY", "")
        self.https_proxy = os.getenv("HTTPS_PROXY", "")

        # ============ 本地标准化模型配置 ============
        self.use_local_standardizer = os.getenv("USE_LOCAL_STANDARDIZER", "false").lower() == "true"

        self.local_standardizer_config = {
            "enabled": self.use_local_standardizer,
            "mode": os.getenv("LOCAL_STANDARDIZER_MODE", "direct"),  # "direct" or "vllm"
            "base_model": os.getenv("LOCAL_STANDARDIZER_BASE_MODEL", "Qwen/Qwen2.5-3B-Instruct"),
            "unified_lora": os.getenv("LOCAL_STANDARDIZER_UNIFIED_LORA", "./LOCAL_STANDARDIZER_MODEL/models/unified_lora/final"),
            "column_lora": os.getenv("LOCAL_STANDARDIZER_COLUMN_LORA", "./LOCAL_STANDARDIZER_MODEL/models/column_lora/checkpoint-200"),
            "device": os.getenv("LOCAL_STANDARDIZER_DEVICE", "cuda"),  # "cuda" or "cpu"
            "max_length": int(os.getenv("LOCAL_STANDARDIZER_MAX_LENGTH", "256")),
            "vllm_url": os.getenv("LOCAL_STANDARDIZER_VLLM_URL", "http://localhost:8001"),
        }

        # ============ RAG配置 ============
        # Embedding模式: "api" 或 "local"
        self.embedding_mode = os.getenv("EMBEDDING_MODE", "api").lower()

        # Rerank模式: "api", "local" 或 "none"
        self.rerank_mode = os.getenv("RERANK_MODE", "api").lower()

        # API模式下的模型配置
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
        self.embedding_dimension = int(os.getenv("EMBEDDING_DIMENSION", "1024"))
        self.rerank_model = os.getenv("RERANK_MODEL", "gte-rerank")
        self.rerank_top_n = int(os.getenv("RERANK_TOP_N", "5"))

_config = None
def get_config():
    global _config
    if _config is None:
        _config = Config()
    return _config
