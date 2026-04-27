"""
Async LLM client with Tool Use (function calling) support.

This is the canonical LLM client for the **core router** (core/router.py):
  - Async chat and chat_with_tools for the tool-calling loop
  - Sync convenience methods (chat_sync, chat_json_sync) for backward compatibility

Key features vs llm/client.py:
  - Tool Use / function calling support (chat_with_tools)
  - ToolCall and LLMResponse dataclasses for structured responses
  - Proxy-to-direct failover (same pattern as llm/client.py)

For synchronous multi-purpose usage (standardizers, column mapping, RAG refinement),
see llm/client.py, which shares the same purpose-based assignment concept for
non-router call sites.

TODO (Phase 2+): Consolidate shared failover logic with llm/client.py and decide
whether router synthesis should move from the agent-scoped async client to a
separately instantiated `purpose="synthesis"` client.
"""
import json
import logging
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from openai import OpenAI
from openai import APIConnectionError
import httpx
from config import get_config

logger = logging.getLogger(__name__)


def _get_assignment_for_purpose(purpose: str):
    """Resolve the configured LLM assignment for a named async purpose."""
    config = get_config()
    assignment_map = {
        "agent": config.agent_llm,
        "standardizer": config.standardizer_llm,
        "synthesis": config.synthesis_llm,
        "rag_refiner": config.rag_refiner_llm,
    }
    if purpose not in assignment_map:
        raise ValueError(f"Unknown LLM purpose: {purpose}")
    return assignment_map[purpose]


@dataclass
class ToolCall:
    """Represents a tool call from the LLM"""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMResponse:
    """Represents an LLM response"""
    content: str
    tool_calls: Optional[List[ToolCall]] = None
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    reasoning_content: Optional[str] = None


class LLMClientService:
    """
    LLM Client with Tool Use support

    Supports both regular chat and Tool Use mode (function calling)
    """

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        purpose: str = "agent",
    ):
        """
        Initialize LLM client

        Args:
            model: Optional model override. Defaults to the configured model for `purpose`.
            temperature: Optional temperature override. Defaults to the configured temperature for `purpose`.
            purpose: Assignment bucket to load from config (agent, standardizer, synthesis, rag_refiner)
        """
        config = get_config()
        assignment = _get_assignment_for_purpose(purpose)
        self.purpose = purpose
        self.assignment = assignment
        self.model = model or assignment.model
        self.temperature = assignment.temperature if temperature is None else temperature
        self.provider_name = assignment.provider
        provider = config.providers[self.provider_name]
        self._api_key = provider["api_key"]
        self._base_url = provider["base_url"]
        self._proxy = config.https_proxy or config.http_proxy
        self._request_timeout = 120.0

        # Build primary client (proxy first if configured) and optional direct fallback.
        self._use_proxy_primary = bool(self._proxy)
        self._client_proxy = self._create_openai_client(use_proxy=True) if self._proxy else None
        self._client_direct = self._create_openai_client(use_proxy=False)
        self.client = self._client_proxy if self._use_proxy_primary and self._client_proxy else self._client_direct

        self.max_tokens = assignment.max_tokens
        self._retry_sleep = time.sleep

    def _create_openai_client(self, use_proxy: bool) -> OpenAI:
        if not self._api_key:
            raise ValueError(
                "LLM API key not configured. "
                f"Please set {self.provider_name.upper()}_API_KEY environment variable."
            )
        http_client = None
        if use_proxy and self._proxy:
            http_client = httpx.Client(
                proxy=self._proxy,
                timeout=self._request_timeout
            )
            logger.info(f"Using proxy: {self._proxy}")
        return OpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            http_client=http_client
        )

    @staticmethod
    def _is_connection_error(exc: Exception) -> bool:
        if isinstance(exc, (APIConnectionError, httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout)):
            return True
        text = str(exc).lower()
        keywords = [
            "connection error",
            "connecterror",
            "timed out",
            "unexpected eof",
            "ssl",
            "tls",
        ]
        return any(k in text for k in keywords)

    def _provider_extra_kwargs(self) -> Dict[str, Any]:
        """Return provider-specific request parameters for OpenAI-compatible APIs."""
        if getattr(self, "provider_name", "") != "deepseek":
            return {}

        config = get_config()
        if not getattr(config, "deepseek_enable_thinking", False):
            return {}
        if self.model not in getattr(config, "deepseek_thinking_models", ()):
            return {}

        extra_body: Dict[str, Any] = {"thinking": {"type": "enabled"}}
        reasoning_effort = getattr(config, "deepseek_reasoning_effort", "")
        if reasoning_effort:
            extra_body["reasoning_effort"] = reasoning_effort
        return {"extra_body": extra_body}

    def _request_with_failover(self, request_fn, operation: str):
        """
        Execute request with proxy->direct failover and bounded transient retry.
        """
        config = get_config()
        max_attempts = 3 if getattr(config, "enable_llm_retry_backoff", False) else 1
        last_error = None

        for attempt in range(max_attempts):
            clients = []

            # keep stable order by current active client
            if self.client is self._client_proxy and self._client_proxy:
                clients = [("proxy", self._client_proxy), ("direct", self._client_direct)]
            else:
                clients = [("direct", self._client_direct)]
                if self._client_proxy:
                    clients.append(("proxy", self._client_proxy))

            saw_transient = False
            for mode, c in clients:
                if c is None:
                    continue
                try:
                    resp = request_fn(c)
                    # promote successful client as active
                    self.client = c
                    if mode == "direct" and self._client_proxy:
                        logger.warning(f"{operation}: switched to direct connection after proxy/connect failure")
                    return resp
                except Exception as e:
                    last_error = e
                    if self._is_connection_error(e):
                        saw_transient = True
                        logger.warning(
                            "%s via %s failed due to connection issue (attempt %s/%s): %s",
                            operation,
                            mode,
                            attempt + 1,
                            max_attempts,
                            e,
                        )
                        continue
                    # Non-connection errors should fail fast
                    raise

            if saw_transient and attempt < max_attempts - 1:
                wait_seconds = 1.0 * (2 ** attempt)
                logger.warning(
                    "%s retrying in %.1fs after transient connection failure",
                    operation,
                    wait_seconds,
                )
                retry_sleep = getattr(self, "_retry_sleep", time.sleep)
                retry_sleep(wait_seconds)

        # all attempts failed
        if last_error:
            raise last_error
        raise RuntimeError(f"{operation} failed with unknown error")

    def _extract_reasoning_content(self, message: Any) -> Optional[str]:
        """Return provider thinking metadata that must be replayed in tool histories."""
        if getattr(self, "provider_name", "") not in ("deepseek", "qwen"):
            return None

        reasoning_content = getattr(message, "reasoning_content", None)
        if reasoning_content is not None:
            return reasoning_content

        if hasattr(message, "model_dump"):
            payload = message.model_dump(exclude_none=True)
            value = payload.get("reasoning_content")
            if value is not None:
                return value

        return None

    @staticmethod
    def _extract_usage(response: Any) -> Optional[Dict[str, Any]]:
        """Extract token usage from an OpenAI-compatible response."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        if isinstance(usage, dict):
            return dict(usage)

        payload: Dict[str, Any] = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = getattr(usage, key, None)
            if value is not None:
                payload[key] = value
        return payload or None

    def _log_usage(self, response: Any, operation: str) -> Optional[Dict[str, Any]]:
        """Log token telemetry when the provider returns usage metadata."""
        usage = self._extract_usage(response)
        if usage:
            logger.info(
                "[TOKEN_TELEMETRY] operation=%s purpose=%s model=%s prompt=%s completion=%s total=%s",
                operation,
                self.purpose,
                self.model,
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                usage.get("total_tokens"),
            )
        return usage

    async def chat(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        seed: Optional[int] = None,
    ) -> LLMResponse:
        """
        Simple chat without tools

        Args:
            messages: List of message dicts with 'role' and 'content'
            system: Optional system message
            temperature: Optional temperature override

        Returns:
            LLMResponse with content
        """
        # Build messages
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        try:
            response = self._request_with_failover(
                lambda cli: cli.chat.completions.create(
                    model=self.model,
                    messages=full_messages,
                    temperature=temperature or self.temperature,
                    **({"seed": seed} if seed is not None else {}),
                    **self._provider_extra_kwargs(),
                    max_tokens=self.max_tokens,
                ),
                operation="LLM chat"
            )
            usage = self._log_usage(response, "chat")

            content = response.choices[0].message.content
            finish_reason = response.choices[0].finish_reason

            return LLMResponse(
                content=content,
                finish_reason=finish_reason,
                usage=usage,
            )

        except Exception as e:
            logger.error(f"LLM chat failed: {e}")
            raise

    async def chat_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict],
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        seed: Optional[int] = None,
    ) -> LLMResponse:
        """
        Chat with Tool Use support

        Args:
            messages: List of message dicts
            tools: List of tool definitions in OpenAI format
            system: Optional system message
            temperature: Optional temperature override

        Returns:
            LLMResponse with content and optional tool_calls
        """
        # Build messages
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        try:
            response = self._request_with_failover(
                lambda cli: cli.chat.completions.create(
                    model=self.model,
                    messages=full_messages,
                    tools=tools,
                    tool_choice="auto",  # Let LLM decide
                    temperature=temperature or self.temperature,
                    **({"seed": seed} if seed is not None else {}),
                    **self._provider_extra_kwargs(),
                    max_tokens=self.max_tokens,
                ),
                operation="LLM chat with tools"
            )
            usage = self._log_usage(response, "chat_with_tools")

            message = response.choices[0].message
            content = message.content or ""
            finish_reason = response.choices[0].finish_reason
            reasoning_content = self._extract_reasoning_content(message)

            # Parse tool calls if present
            tool_calls = None
            if message.tool_calls:
                tool_calls = []
                for tc in message.tool_calls:
                    try:
                        arguments = json.loads(tc.function.arguments)
                        tool_calls.append(ToolCall(
                            id=tc.id,
                            name=tc.function.name,
                            arguments=arguments
                        ))
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse tool call arguments: {e}")
                        # Skip this tool call
                        continue

            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage=usage,
                reasoning_content=reasoning_content,
            )

        except Exception as e:
            logger.error(f"LLM chat with tools failed: {e}")
            raise

    async def chat_json(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Async JSON-object chat for lightweight planning and other structured calls.

        Args:
            messages: List of message dicts
            system: Optional system message
            temperature: Optional temperature override

        Returns:
            Parsed JSON response
        """
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        try:
            response = self._request_with_failover(
                lambda cli: cli.chat.completions.create(
                    model=self.model,
                    messages=full_messages,
                    temperature=0.0 if temperature is None else temperature,
                    response_format={"type": "json_object"},
                    **({"seed": seed} if seed is not None else {}),
                    **self._provider_extra_kwargs(),
                    max_tokens=self.max_tokens,
                ),
                operation="LLM async JSON chat",
            )
            self._log_usage(response, "chat_json")

            content = response.choices[0].message.content or "{}"
            return json.loads(content)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse async JSON response: {e}")
            raise
        except Exception as e:
            logger.error(f"LLM async JSON chat failed: {e}")
            raise

    async def chat_json_with_metadata(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Async JSON chat with raw content and provider usage metadata."""
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        try:
            response = self._request_with_failover(
                lambda cli: cli.chat.completions.create(
                    model=self.model,
                    messages=full_messages,
                    temperature=0.0 if temperature is None else temperature,
                    response_format={"type": "json_object"},
                    **({"seed": seed} if seed is not None else {}),
                    **self._provider_extra_kwargs(),
                    max_tokens=self.max_tokens,
                ),
                operation="LLM async JSON chat",
            )
            usage = self._log_usage(response, "chat_json")
            content = response.choices[0].message.content or "{}"
            return {
                "payload": json.loads(content),
                "raw_response": content,
                "usage": usage or {},
            }
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse async JSON response: {e}")
            raise
        except Exception as e:
            logger.error(f"LLM async JSON chat failed: {e}")
            raise

    def chat_sync(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: Optional[float] = None
    ) -> str:
        """
        Synchronous simple chat (for backward compatibility)

        Args:
            prompt: User prompt
            system: Optional system message
            temperature: Optional temperature override

        Returns:
            Response content string
        """
        messages = [{"role": "user", "content": prompt}]
        if system:
            messages.insert(0, {"role": "system", "content": system})

        try:
            response = self._request_with_failover(
                lambda cli: cli.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature or self.temperature,
                    **self._provider_extra_kwargs(),
                    max_tokens=self.max_tokens,
                ),
                operation="LLM sync chat"
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"LLM sync chat failed: {e}")
            raise

    def chat_json_sync(
        self,
        prompt: str,
        system: Optional[str] = None
    ) -> Dict:
        """
        Synchronous JSON mode chat (for backward compatibility)

        Args:
            prompt: User prompt
            system: Optional system message

        Returns:
            Parsed JSON response
        """
        messages = [{"role": "user", "content": prompt}]
        if system:
            messages.insert(0, {"role": "system", "content": system})

        try:
            response = self._request_with_failover(
                lambda cli: cli.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.3,
                    response_format={"type": "json_object"},
                    **self._provider_extra_kwargs(),
                    max_tokens=self.max_tokens,
                ),
                operation="LLM JSON chat"
            )

            content = response.choices[0].message.content
            return json.loads(content)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            raise
        except Exception as e:
            logger.error(f"LLM JSON chat failed: {e}")
            raise


# Singleton instances for different purposes
_client_instances: Dict[str, LLMClientService] = {}


def get_llm_client(purpose: str = "agent", model: Optional[str] = None) -> LLMClientService:
    """
    Get a cached async LLM client instance.

    Args:
        purpose: Purpose identifier that selects the configured assignment.
        model: Optional model override. When omitted, the configured model for `purpose` is used.

    Returns:
        LLMClientService instance
    """
    assignment = _get_assignment_for_purpose(purpose)
    resolved_model = model or assignment.model
    key = f"{purpose}_{resolved_model}"
    if key not in _client_instances:
        _client_instances[key] = LLMClientService(model=model, purpose=purpose)
        logger.info(f"Created LLM client: {key}")

    return _client_instances[key]


def reset_llm_client_cache():
    """Clear cached async LLM clients. Useful for tests and runtime overrides."""
    _client_instances.clear()
