"""Tests for config loading and secret handling."""
import os
import importlib
from config import Config, get_config, reset_config


class TestConfigLoading:
    """Config loads from environment and provides safe defaults."""

    def test_config_creates_successfully(self):
        config = get_config()
        assert config is not None
        assert config.agent_llm is not None
        assert config.agent_llm.provider == "qwen"

    def test_config_singleton(self):
        a = get_config()
        b = get_config()
        assert a is b

    def test_config_reset(self):
        a = get_config()
        reset_config()
        b = get_config()
        assert a is not b

    def test_feature_flags_default_true(self):
        config = get_config()
        assert config.enable_llm_standardization is True
        assert config.enable_standardization_cache is True
        assert config.persist_trace is False
        assert config.enable_contour_output is True
        assert config.contour_interp_resolution_m == 10.0
        assert config.contour_n_levels == 12
        assert config.contour_smooth_sigma == 1.0
        assert config.standardization_fuzzy_enabled is True
        assert config.continuation_prompt_variant == "balanced_repair_aware"
        assert config.enable_cross_constraint_validation is True
        assert config.enable_parameter_negotiation is False
        assert config.parameter_negotiation_confidence_threshold == 0.85
        assert config.parameter_negotiation_max_candidates == 5
        assert config.enable_capability_aware_synthesis is True
        assert config.enable_readiness_gating is True
        assert config.readiness_repairable_enabled is True
        assert config.readiness_already_provided_dedup_enabled is True
        assert config.enable_input_completion_flow is True
        assert config.input_completion_allow_uniform_scalar is True
        assert config.input_completion_allow_upload_support_file is True
        assert config.enable_geometry_recovery_path is True
        assert config.enable_file_relationship_resolution is True
        assert config.file_relationship_resolution_require_new_upload is True
        assert config.file_relationship_resolution_allow_llm_fallback is True
        assert config.enable_supplemental_column_merge is True
        assert config.supplemental_merge_allow_alias_keys is True
        assert config.supplemental_merge_require_readiness_refresh is True
        assert config.enable_intent_resolution is True
        assert config.intent_resolution_allow_llm_fallback is True
        assert config.intent_resolution_bias_followup_suggestions is True
        assert config.intent_resolution_bias_continuation is True
        assert config.enable_artifact_memory is True
        assert config.artifact_memory_track_textual_summary is True
        assert config.artifact_memory_dedup_by_family is True
        assert config.artifact_memory_bias_followup is True
        assert config.enable_summary_delivery_surface is True
        assert config.summary_delivery_enable_bar_chart is True
        assert config.summary_delivery_default_topk == 5
        assert config.summary_delivery_allow_text_fallback is True
        assert config.geometry_recovery_supported_file_types == (
            "geojson",
            "json",
            "shp",
            "zip",
            "csv",
            "xlsx",
            "xls",
        )
        assert config.geometry_recovery_require_readiness_refresh is True
        assert config.enable_residual_reentry_controller is True
        assert config.residual_reentry_require_ready_target is True
        assert config.residual_reentry_prioritize_recovery_target is True
        assert config.enable_file_analysis_llm_fallback is False
        assert config.enable_workflow_templates is False
        assert config.workflow_template_max_recommendations == 3
        assert config.workflow_template_min_confidence == 0.55
        assert config.file_analysis_fallback_confidence_threshold == 0.72
        assert config.file_analysis_fallback_max_sample_rows == 3
        assert config.file_analysis_fallback_max_columns == 25
        assert config.file_analysis_fallback_allow_zip_table_selection is True

    def test_feature_flag_override(self, monkeypatch):
        monkeypatch.setenv("ENABLE_LLM_STANDARDIZATION", "false")
        monkeypatch.setenv("PERSIST_TRACE", "true")
        monkeypatch.setenv("ENABLE_CONTOUR_OUTPUT", "false")
        monkeypatch.setenv("CONTOUR_INTERP_RESOLUTION_M", "20.0")
        monkeypatch.setenv("CONTOUR_N_LEVELS", "8")
        monkeypatch.setenv("CONTOUR_SMOOTH_SIGMA", "0.5")
        monkeypatch.setenv("STANDARDIZATION_FUZZY_ENABLED", "false")
        reset_config()
        config = get_config()
        assert config.enable_llm_standardization is False
        assert config.persist_trace is True
        assert config.enable_contour_output is False
        assert config.contour_interp_resolution_m == 20.0
        assert config.contour_n_levels == 8
        assert config.contour_smooth_sigma == 0.5
        assert config.standardization_fuzzy_enabled is False

    def test_directories_created(self):
        config = get_config()
        assert config.data_collection_dir.exists()
        assert config.outputs_dir.exists()


class TestJWTSecretLoading:
    """JWT secret key is loaded from environment, not hardcoded."""

    def test_jwt_secret_from_env(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "my-super-secret-key-123")
        # Re-import to pick up the new env value
        import api.auth as auth_mod
        importlib.reload(auth_mod)
        assert auth_mod.SECRET_KEY == "my-super-secret-key-123"

    def test_auth_module_loads_dotenv_before_reading_secret(self, monkeypatch):
        """api.auth should load .env itself instead of relying on config import order."""
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

        import dotenv
        import api.auth as auth_mod

        calls = []

        def fake_load_dotenv(path=None, override=False, *args, **kwargs):
            calls.append((path, override))
            monkeypatch.setenv("JWT_SECRET_KEY", "dotenv-loaded-secret")
            return True

        monkeypatch.setattr(dotenv, "load_dotenv", fake_load_dotenv)
        importlib.reload(auth_mod)

        assert auth_mod.SECRET_KEY == "dotenv-loaded-secret"
        assert calls
        assert str(calls[0][0]).endswith(".env")
        assert calls[0][1] is False

    def test_jwt_default_is_not_production_safe(self):
        """The default key should contain a warning-like string, not a strong secret."""
        from api.auth import _DEFAULT_SECRET
        assert "change" in _DEFAULT_SECRET.lower() or "dev" in _DEFAULT_SECRET.lower()
