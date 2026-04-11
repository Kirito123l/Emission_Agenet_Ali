"""Router LLM assignment regression tests."""

from types import SimpleNamespace

from core.router import UnifiedRouter


def test_router_uses_configured_agent_llm_without_model_override(monkeypatch, tmp_path):
    calls = []

    def fake_get_llm_client(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(model="configured-agent-model")

    monkeypatch.setattr("core.router.get_llm_client", fake_get_llm_client)

    router = UnifiedRouter("model-config-test", memory_storage_dir=tmp_path)

    assert router.llm.model == "configured-agent-model"
    assert calls == [(("agent",), {})]
