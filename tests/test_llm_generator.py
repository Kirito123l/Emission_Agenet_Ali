from config import reset_config
from evaluation.llm_generator import LLMGenerator


def test_llm_generator_resolves_configured_agent_model(monkeypatch):
    monkeypatch.delenv("EVALUATION_LLM_MODEL", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM_REASONING_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("LLM_FAST_MODEL", "deepseek-v4-flash")
    reset_config()

    assert LLMGenerator.resolve_model() == "deepseek-v4-pro"


def test_llm_generator_allows_evaluation_model_override(monkeypatch):
    monkeypatch.setenv("EVALUATION_LLM_MODEL", "evaluation-model")
    reset_config()

    assert LLMGenerator.resolve_model() == "evaluation-model"
