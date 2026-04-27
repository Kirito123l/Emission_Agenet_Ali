"""Focused regression tests for the conservative Phase 1B cleanup."""
from config import reset_config
from llm import LLMClient, get_llm, reset_llm_manager
from services.llm_client import (
    LLMClientService,
    get_llm_client,
    reset_llm_client_cache,
)


def test_sync_llm_package_export_uses_purpose_assignment(monkeypatch):
    monkeypatch.setenv("LLM_USE_GLOBAL_DEFAULTS", "false")
    monkeypatch.setenv("STANDARDIZER_LLM_MODEL", "standardizer-test-model")
    reset_config()
    reset_llm_manager()

    client = get_llm("standardizer")

    assert isinstance(client, LLMClient)
    assert client.purpose == "standardizer"
    assert client.assignment.model == "standardizer-test-model"


def test_async_llm_service_uses_purpose_assignment(monkeypatch):
    monkeypatch.setenv("LLM_USE_GLOBAL_DEFAULTS", "false")
    monkeypatch.setenv("SYNTHESIS_LLM_MODEL", "synthesis-test-model")
    reset_config()

    client = LLMClientService(purpose="synthesis")

    assert client.purpose == "synthesis"
    assert client.model == "synthesis-test-model"
    assert client.assignment.model == "synthesis-test-model"


def test_async_llm_factory_uses_purpose_default_model(monkeypatch):
    monkeypatch.setenv("LLM_USE_GLOBAL_DEFAULTS", "false")
    monkeypatch.setenv("AGENT_LLM_MODEL", "agent-test-model")
    monkeypatch.setenv("SYNTHESIS_LLM_MODEL", "synthesis-test-model")
    reset_config()
    reset_llm_client_cache()

    agent_client = get_llm_client("agent")
    synthesis_client = get_llm_client("synthesis")

    assert agent_client.model == "agent-test-model"
    assert synthesis_client.model == "synthesis-test-model"
    assert agent_client is not synthesis_client


def test_async_llm_factory_preserves_explicit_model_override(monkeypatch):
    monkeypatch.setenv("LLM_USE_GLOBAL_DEFAULTS", "false")
    monkeypatch.setenv("SYNTHESIS_LLM_MODEL", "configured-synthesis-model")
    reset_config()
    reset_llm_client_cache()

    client = get_llm_client("synthesis", model="manual-override-model")

    assert client.purpose == "synthesis"
    assert client.model == "manual-override-model"
    assert client.assignment.model == "configured-synthesis-model"


def test_legacy_micro_skill_import_path_remains_available():
    from skills.micro_emission import MicroEmissionSkill

    assert MicroEmissionSkill.__name__ == "MicroEmissionSkill"
