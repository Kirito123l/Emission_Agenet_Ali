"""
LLM Client Service
Wrapper for LLM API calls with Tool Use support
"""
import json
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from openai import OpenAI
from openai import APIConnectionError
import httpx

logger = logging.getLogger(__name__)


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


class LLMClientService:
    """
    LLM Client with Tool Use support

    Supports both regular chat and Tool Use mode (function calling)
    """

    def __init__(self, model: str = "qwen-plus", temperature: float = 0.7):
        """
        Initialize LLM client

        Args:
            model: Model name (e.g., "qwen-plus", "gpt-4")
            temperature: Sampling temperature
        """
        # Load configuration
        from config import get_config
        config = get_config()

        # Find the assignment for this model
        self.model = model
        self.temperature = temperature

        # Get provider configuration from agent_llm
        assignment = config.agent_llm
        provider = config.providers[assignment.provider]
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

    def _create_openai_client(self, use_proxy: bool) -> OpenAI:
        if not self._api_key:
            raise ValueError(
                "LLM API key not configured. "
                "Please set QWEN_API_KEY environment variable."
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

    def _request_with_failover(self, request_fn, operation: str):
        """
        Execute request with proxy->direct failover on connection-layer failures.
        """
        last_error = None
        clients = []

        # keep stable order by current active client
        if self.client is self._client_proxy and self._client_proxy:
            clients = [("proxy", self._client_proxy), ("direct", self._client_direct)]
        else:
            clients = [("direct", self._client_direct)]
            if self._client_proxy:
                clients.append(("proxy", self._client_proxy))

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
                    logger.warning(f"{operation} via {mode} failed due to connection issue: {e}")
                    continue
                # Non-connection errors should fail fast
                raise

        # all attempts failed
        if last_error:
            raise last_error
        raise RuntimeError(f"{operation} failed with unknown error")

    async def chat(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        temperature: Optional[float] = None
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
                    max_tokens=self.max_tokens,
                ),
                operation="LLM chat"
            )

            content = response.choices[0].message.content
            finish_reason = response.choices[0].finish_reason

            return LLMResponse(
                content=content,
                finish_reason=finish_reason
            )

        except Exception as e:
            logger.error(f"LLM chat failed: {e}")
            raise

    async def chat_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict],
        system: Optional[str] = None,
        temperature: Optional[float] = None
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
                    max_tokens=self.max_tokens,
                ),
                operation="LLM chat with tools"
            )

            message = response.choices[0].message
            content = message.content or ""
            finish_reason = response.choices[0].finish_reason

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
                finish_reason=finish_reason
            )

        except Exception as e:
            logger.error(f"LLM chat with tools failed: {e}")
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


def get_llm_client(purpose: str = "agent", model: str = "qwen-plus") -> LLMClientService:
    """
    Get LLM client instance

    Args:
        purpose: Purpose identifier (e.g., "agent", "synthesis")
        model: Model name

    Returns:
        LLMClientService instance
    """
    key = f"{purpose}_{model}"
    if key not in _client_instances:
        _client_instances[key] = LLMClientService(model=model)
        logger.info(f"Created LLM client: {key}")

    return _client_instances[key]
