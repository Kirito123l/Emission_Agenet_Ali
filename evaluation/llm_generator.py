"""LLM-powered data generation utilities."""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_MODEL = "qwen3-max"
MODEL_ENV_VARS = (
    "EVALUATION_LLM_MODEL",
    "QWEN_MODEL",
    "AGENT_LLM_MODEL",
)


class LLMGenerator:
    """Wrapper for Qwen-compatible chat completions with JSON parsing."""

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.8,
        max_retries: int = 3,
        retry_delay: float = 2.0,
        call_interval: float = 1.0,
    ) -> None:
        api_key = os.getenv("QWEN_API_KEY")
        base_url = os.getenv("QWEN_BASE_URL")
        if not api_key or not base_url:
            raise RuntimeError("QWEN_API_KEY and QWEN_BASE_URL must be configured in the project .env file.")

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = self.resolve_model(model)
        self.temperature = temperature
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.call_interval = call_interval
        self._last_call_time = 0.0

    @classmethod
    def resolve_model(cls, model: Optional[str] = None) -> str:
        """Resolve model with precedence: CLI argument > env var > default."""
        cleaned = str(model).strip() if model is not None else ""
        if cleaned:
            return cleaned

        for env_name in MODEL_ENV_VARS:
            env_value = str(os.getenv(env_name, "")).strip()
            if env_value:
                return env_value

        return DEFAULT_MODEL

    def _wait_for_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_call_time
        if elapsed < self.call_interval:
            time.sleep(self.call_interval - elapsed)

    @staticmethod
    def _extract_json_object(content: str) -> Optional[Dict[str, Any]]:
        start = content.find("{")
        end = content.rfind("}") + 1
        if start < 0 or end <= start:
            return None
        snippet = content[start:end]
        parsed = json.loads(snippet)
        return parsed if isinstance(parsed, dict) else None

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Call the LLM and parse the returned JSON object."""
        temp = self.temperature if temperature is None else temperature

        for attempt in range(self.max_retries):
            content = ""
            try:
                self._wait_for_rate_limit()
                self._last_call_time = time.monotonic()
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temp,
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content or ""
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict):
                        return parsed
                    raise json.JSONDecodeError("Top-level payload is not an object", content, 0)
                except json.JSONDecodeError:
                    extracted = self._extract_json_object(content)
                    if extracted is not None:
                        return extracted
                    raise
            except json.JSONDecodeError as exc:
                logger.warning("LLM JSON parse error (attempt %s/%s): %s", attempt + 1, self.max_retries, exc)
                if content:
                    logger.debug("Raw LLM content preview: %s", content[:500])
            except Exception as exc:
                logger.warning("LLM API call failed (attempt %s/%s): %s", attempt + 1, self.max_retries, exc)

            if attempt < self.max_retries - 1:
                time.sleep(self.retry_delay * (attempt + 1))

        logger.error("Failed to generate JSON after %s attempts.", self.max_retries)
        return None

    def generate_batch(
        self,
        system_prompt: str,
        user_prompts: List[str],
        temperature: Optional[float] = None,
    ) -> List[Optional[Dict[str, Any]]]:
        """Call the LLM once per prompt and collect parsed JSON results."""
        results: List[Optional[Dict[str, Any]]] = []
        for index, prompt in enumerate(user_prompts, start=1):
            logger.info("Generating batch item %s/%s", index, len(user_prompts))
            results.append(self.generate_json(system_prompt, prompt, temperature=temperature))
        return results
