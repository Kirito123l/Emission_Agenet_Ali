"""Tests for config loading and secret handling."""
import os
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

    def test_feature_flag_override(self, monkeypatch):
        monkeypatch.setenv("ENABLE_LLM_STANDARDIZATION", "false")
        reset_config()
        config = get_config()
        assert config.enable_llm_standardization is False

    def test_directories_created(self):
        config = get_config()
        assert config.data_collection_dir.exists()
        assert config.outputs_dir.exists()


class TestJWTSecretLoading:
    """JWT secret key is loaded from environment, not hardcoded."""

    def test_jwt_secret_from_env(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "my-super-secret-key-123")
        # Re-import to pick up the new env value
        import importlib
        import api.auth as auth_mod
        importlib.reload(auth_mod)
        assert auth_mod.SECRET_KEY == "my-super-secret-key-123"

    def test_jwt_default_is_not_production_safe(self):
        """The default key should contain a warning-like string, not a strong secret."""
        from api.auth import _DEFAULT_SECRET
        assert "change" in _DEFAULT_SECRET.lower() or "dev" in _DEFAULT_SECRET.lower()
