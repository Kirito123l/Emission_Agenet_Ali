"""
LLM module — synchronous client, data collection, and standardization support.

Primary entry point: llm.client.get_llm(purpose)
  - Returns a purpose-routed LLMClient (agent, standardizer, synthesis, rag_refiner)
  - Used by: shared/standardizer/, tools/ init blocks, skills/knowledge/

Also contains:
  - llm.data_collector — standardization logging for fine-tuning data collection

For async/tool-calling usage (core router), see services.llm_client instead.
"""
from .client import LLMClient, LLMManager, get_llm, reset_llm_manager

__all__ = ["LLMClient", "LLMManager", "get_llm", "reset_llm_manager"]
