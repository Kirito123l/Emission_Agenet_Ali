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
        self.enable_file_analyzer = os.getenv("ENABLE_FILE_ANALYZER", "true").lower() == "true"
        self.enable_file_context_injection = os.getenv("ENABLE_FILE_CONTEXT_INJECTION", "true").lower() == "true"
        self.enable_executor_standardization = os.getenv("ENABLE_EXECUTOR_STANDARDIZATION", "true").lower() == "true"
        self.enable_state_orchestration = os.getenv("ENABLE_STATE_ORCHESTRATION", "true").lower() == "true"
        self.enable_trace = os.getenv("ENABLE_TRACE", "true").lower() == "true"
        self.persist_trace = os.getenv("PERSIST_TRACE", "false").lower() == "true"
        self.enable_contour_output = os.getenv("ENABLE_CONTOUR_OUTPUT", "true").lower() == "true"
        self.contour_interp_resolution_m = float(
            os.getenv("CONTOUR_INTERP_RESOLUTION_M", "10.0")
        )
        self.contour_n_levels = int(os.getenv("CONTOUR_N_LEVELS", "7"))
        self.contour_smooth_sigma = float(os.getenv("CONTOUR_SMOOTH_SIGMA", "1.0"))
        self.map_export_dpi = int(os.getenv("MAP_EXPORT_DPI", "300"))
        self.map_export_default_format = (
            os.getenv("MAP_EXPORT_DEFAULT_FORMAT", "png").strip().lower() or "png"
        )
        self.map_export_ttl_hours = int(os.getenv("MAP_EXPORT_TTL_HOURS", "1"))
        self.map_export_basemap_enabled = (
            os.getenv("MAP_EXPORT_BASEMAP_ENABLED", "true").lower() == "true"
        )
        self.map_export_basemap_timeout = float(os.getenv("MAP_EXPORT_BASEMAP_TIMEOUT", "2"))
        self.standardization_fuzzy_enabled = (
            os.getenv("STANDARDIZATION_FUZZY_ENABLED", "true").lower() == "true"
        )
        self.enable_lightweight_planning = os.getenv("ENABLE_LIGHTWEIGHT_PLANNING", "false").lower() == "true"
        self.enable_bounded_plan_repair = os.getenv("ENABLE_BOUNDED_PLAN_REPAIR", "false").lower() == "true"
        self.enable_repair_aware_continuation = os.getenv("ENABLE_REPAIR_AWARE_CONTINUATION", "false").lower() == "true"
        self.enable_cross_constraint_validation = (
            os.getenv("ENABLE_CROSS_CONSTRAINT_VALIDATION", "true").lower() == "true"
        )
        self.enable_parameter_negotiation = os.getenv("ENABLE_PARAMETER_NEGOTIATION", "false").lower() == "true"
        self.enable_file_analysis_llm_fallback = os.getenv("ENABLE_FILE_ANALYSIS_LLM_FALLBACK", "false").lower() == "true"
        self.enable_workflow_templates = os.getenv("ENABLE_WORKFLOW_TEMPLATES", "false").lower() == "true"
        self.enable_capability_aware_synthesis = (
            os.getenv("ENABLE_CAPABILITY_AWARE_SYNTHESIS", "true").lower() == "true"
        )
        self.enable_readiness_gating = os.getenv("ENABLE_READINESS_GATING", "true").lower() == "true"
        self.readiness_repairable_enabled = (
            os.getenv("READINESS_REPAIRABLE_ENABLED", "true").lower() == "true"
        )
        self.readiness_already_provided_dedup_enabled = (
            os.getenv("READINESS_ALREADY_PROVIDED_DEDUP_ENABLED", "true").lower() == "true"
        )
        self.enable_input_completion_flow = (
            os.getenv("ENABLE_INPUT_COMPLETION_FLOW", "true").lower() == "true"
        )
        self.input_completion_max_options = int(
            os.getenv("INPUT_COMPLETION_MAX_OPTIONS", "4")
        )
        self.input_completion_allow_uniform_scalar = (
            os.getenv("INPUT_COMPLETION_ALLOW_UNIFORM_SCALAR", "true").lower() == "true"
        )
        self.input_completion_allow_upload_support_file = (
            os.getenv("INPUT_COMPLETION_ALLOW_UPLOAD_SUPPORT_FILE", "true").lower() == "true"
        )
        self.enable_geometry_recovery_path = (
            os.getenv("ENABLE_GEOMETRY_RECOVERY_PATH", "true").lower() == "true"
        )
        self.enable_file_relationship_resolution = (
            os.getenv("ENABLE_FILE_RELATIONSHIP_RESOLUTION", "true").lower() == "true"
        )
        self.file_relationship_resolution_require_new_upload = (
            os.getenv("FILE_RELATIONSHIP_RESOLUTION_REQUIRE_NEW_UPLOAD", "true").lower() == "true"
        )
        self.file_relationship_resolution_allow_llm_fallback = (
            os.getenv("FILE_RELATIONSHIP_RESOLUTION_ALLOW_LLM_FALLBACK", "true").lower() == "true"
        )
        self.enable_supplemental_column_merge = (
            os.getenv("ENABLE_SUPPLEMENTAL_COLUMN_MERGE", "true").lower() == "true"
        )
        self.supplemental_merge_allow_alias_keys = (
            os.getenv("SUPPLEMENTAL_MERGE_ALLOW_ALIAS_KEYS", "true").lower() == "true"
        )
        self.supplemental_merge_require_readiness_refresh = (
            os.getenv("SUPPLEMENTAL_MERGE_REQUIRE_READINESS_REFRESH", "true").lower() == "true"
        )
        self.enable_intent_resolution = (
            os.getenv("ENABLE_INTENT_RESOLUTION", "true").lower() == "true"
        )
        self.intent_resolution_allow_llm_fallback = (
            os.getenv("INTENT_RESOLUTION_ALLOW_LLM_FALLBACK", "true").lower() == "true"
        )
        self.intent_resolution_bias_followup_suggestions = (
            os.getenv("INTENT_RESOLUTION_BIAS_FOLLOWUP_SUGGESTIONS", "true").lower() == "true"
        )
        self.intent_resolution_bias_continuation = (
            os.getenv("INTENT_RESOLUTION_BIAS_CONTINUATION", "true").lower() == "true"
        )
        self.enable_artifact_memory = (
            os.getenv("ENABLE_ARTIFACT_MEMORY", "true").lower() == "true"
        )
        self.artifact_memory_track_textual_summary = (
            os.getenv("ARTIFACT_MEMORY_TRACK_TEXTUAL_SUMMARY", "true").lower() == "true"
        )
        self.artifact_memory_dedup_by_family = (
            os.getenv("ARTIFACT_MEMORY_DEDUP_BY_FAMILY", "true").lower() == "true"
        )
        self.artifact_memory_bias_followup = (
            os.getenv("ARTIFACT_MEMORY_BIAS_FOLLOWUP", "true").lower() == "true"
        )
        self.enable_summary_delivery_surface = (
            os.getenv("ENABLE_SUMMARY_DELIVERY_SURFACE", "true").lower() == "true"
        )
        self.summary_delivery_enable_bar_chart = (
            os.getenv("SUMMARY_DELIVERY_ENABLE_BAR_CHART", "true").lower() == "true"
        )
        self.summary_delivery_default_topk = int(
            os.getenv("SUMMARY_DELIVERY_DEFAULT_TOPK", "5")
        )
        self.summary_delivery_allow_text_fallback = (
            os.getenv("SUMMARY_DELIVERY_ALLOW_TEXT_FALLBACK", "true").lower() == "true"
        )
        self.geometry_recovery_supported_file_types = tuple(
            item.strip().lower()
            for item in os.getenv(
                "GEOMETRY_RECOVERY_SUPPORTED_FILE_TYPES",
                "geojson,json,shp,zip,csv,xlsx,xls",
            ).split(",")
            if item.strip()
        )
        self.geometry_recovery_require_readiness_refresh = (
            os.getenv("GEOMETRY_RECOVERY_REQUIRE_READINESS_REFRESH", "true").lower() == "true"
        )
        self.enable_residual_reentry_controller = (
            os.getenv("ENABLE_RESIDUAL_REENTRY_CONTROLLER", "true").lower() == "true"
        )
        self.residual_reentry_require_ready_target = (
            os.getenv("RESIDUAL_REENTRY_REQUIRE_READY_TARGET", "true").lower() == "true"
        )
        self.residual_reentry_prioritize_recovery_target = (
            os.getenv("RESIDUAL_REENTRY_PRIORITIZE_RECOVERY_TARGET", "true").lower() == "true"
        )
        self.enable_policy_based_remediation = (
            os.getenv("ENABLE_POLICY_BASED_REMEDIATION", "true").lower() == "true"
        )
        self.enable_default_typical_profile_policy = (
            os.getenv("ENABLE_DEFAULT_TYPICAL_PROFILE_POLICY", "true").lower() == "true"
        )
        self.default_typical_profile_allowed_task_types = tuple(
            item.strip().lower()
            for item in os.getenv(
                "DEFAULT_TYPICAL_PROFILE_ALLOWED_TASK_TYPES",
                "macro_emission",
            ).split(",")
            if item.strip()
        )
        self.workflow_template_max_recommendations = int(
            os.getenv("WORKFLOW_TEMPLATE_MAX_RECOMMENDATIONS", "3")
        )
        self.workflow_template_min_confidence = float(
            os.getenv("WORKFLOW_TEMPLATE_MIN_CONFIDENCE", "0.55")
        )
        self.file_analysis_fallback_confidence_threshold = float(
            os.getenv("FILE_ANALYSIS_FALLBACK_CONFIDENCE_THRESHOLD", "0.72")
        )
        self.file_analysis_fallback_max_sample_rows = int(
            os.getenv("FILE_ANALYSIS_FALLBACK_MAX_SAMPLE_ROWS", "3")
        )
        self.file_analysis_fallback_max_columns = int(
            os.getenv("FILE_ANALYSIS_FALLBACK_MAX_COLUMNS", "25")
        )
        self.file_analysis_fallback_allow_zip_table_selection = (
            os.getenv("FILE_ANALYSIS_FALLBACK_ALLOW_ZIP_TABLE_SELECTION", "true").lower() == "true"
        )
        self.parameter_negotiation_confidence_threshold = float(
            os.getenv("PARAMETER_NEGOTIATION_CONFIDENCE_THRESHOLD", "0.85")
        )
        self.parameter_negotiation_max_candidates = int(
            os.getenv("PARAMETER_NEGOTIATION_MAX_CANDIDATES", "5")
        )
        self.continuation_prompt_variant = (
            os.getenv("CONTINUATION_PROMPT_VARIANT", "balanced_repair_aware").strip().lower()
            or "balanced_repair_aware"
        )
        self.enable_builtin_map_data = os.getenv("ENABLE_BUILTIN_MAP_DATA", "false").lower() == "true"
        self.enable_skill_injection = os.getenv("ENABLE_SKILL_INJECTION", "true").lower() == "true"
        self.max_orchestration_steps = int(os.getenv("MAX_ORCHESTRATION_STEPS", "4"))
        self.macro_column_mapping_modes = tuple(
            mode.strip().lower()
            for mode in os.getenv("MACRO_COLUMN_MAPPING_MODES", "direct,ai,fuzzy").split(",")
            if mode.strip()
        )
        self.standardization_config = {
            "llm_enabled": os.getenv(
                "STANDARDIZATION_LLM_ENABLED",
                "true" if self.enable_llm_standardization else "false",
            ).lower() == "true",
            "fuzzy_enabled": self.standardization_fuzzy_enabled,
            "llm_backend": os.getenv("STANDARDIZATION_LLM_BACKEND", "api").lower(),
            "llm_model": os.getenv("STANDARDIZATION_LLM_MODEL") or None,
            "llm_timeout": float(os.getenv("STANDARDIZATION_LLM_TIMEOUT", "5.0")),
            "llm_max_retries": int(os.getenv("STANDARDIZATION_LLM_MAX_RETRIES", "1")),
            "fuzzy_threshold": float(os.getenv("STANDARDIZATION_FUZZY_THRESHOLD", "0.7")),
            "enable_cross_constraint_validation": self.enable_cross_constraint_validation,
            "parameter_negotiation_enabled": self.enable_parameter_negotiation,
            "parameter_negotiation_confidence_threshold": self.parameter_negotiation_confidence_threshold,
            "parameter_negotiation_max_candidates": self.parameter_negotiation_max_candidates,
            "local_model_path": os.getenv("STANDARDIZATION_LOCAL_MODEL_PATH") or None,
        }

        self.data_collection_dir = PROJECT_ROOT / os.getenv("DATA_COLLECTION_DIR", "data/collection")
        self.log_dir = PROJECT_ROOT / os.getenv("LOG_DIR", "data/logs")
        self.outputs_dir = PROJECT_ROOT / os.getenv("OUTPUTS_DIR", "outputs")
        self.map_export_dir = PROJECT_ROOT / os.getenv("MAP_EXPORT_DIR", "data/exports")

        self.data_collection_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.map_export_dir.mkdir(parents=True, exist_ok=True)

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
        self.standardization_config["use_local_standardizer"] = self.use_local_standardizer
        self.standardization_config["local_standardizer_config"] = dict(self.local_standardizer_config)

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

    def is_macro_mapping_mode_enabled(self, mode: str) -> bool:
        """Return whether a macro column-mapping stage is enabled."""
        return mode.strip().lower() in self.macro_column_mapping_modes

_config = None
def get_config():
    global _config
    if _config is None:
        _config = Config()
    return _config


def reset_config():
    """Reset cached config so new env/runtime overrides can take effect."""
    global _config
    _config = None
