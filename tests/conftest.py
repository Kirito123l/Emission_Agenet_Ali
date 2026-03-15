"""Shared fixtures for the test suite."""
import os
import sys
from pathlib import Path

import pytest

# Ensure the project root is on sys.path so imports work without installation.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Provide safe default env vars so tests never hit real API keys."""
    monkeypatch.setenv("QWEN_API_KEY", "test-key-not-real")
    monkeypatch.setenv("QWEN_BASE_URL", "http://localhost:9999/v1")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-for-ci")
    # Reset the cached config singleton so each test gets a fresh instance.
    from config import reset_config
    reset_config()
    yield
    reset_config()
