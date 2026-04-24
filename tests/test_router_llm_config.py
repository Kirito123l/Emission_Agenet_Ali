"""Router LLM assignment regression tests."""

from types import SimpleNamespace

from core.governed_router import build_router


def test_router_uses_configured_agent_llm_without_model_override(monkeypatch, tmp_path):
    calls = []

    def fake_get_llm_client(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(model="configured-agent-model")

    monkeypatch.setattr("core.router.get_llm_client", fake_get_llm_client)

    router = build_router("model-config-test", memory_storage_dir=tmp_path, router_mode="full")

    assert router.__class__.__name__ == "GovernedRouter"
    assert router.inner_router.llm.model == "configured-agent-model"
    assert calls == [(("agent",), {})]
