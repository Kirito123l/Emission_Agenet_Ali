"""Token telemetry coverage for the async LLM client."""

from types import SimpleNamespace
import logging

import pytest

from services.llm_client import LLMClientService


def _fake_response(*, content: str = "ok", usage=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=None),
                finish_reason="stop",
            )
        ],
        usage=usage,
    )


def _make_uninitialized_client(response):
    client = object.__new__(LLMClientService)
    client.model = "telemetry-model"
    client.purpose = "agent"
    client.temperature = 0.0
    client.max_tokens = 64
    client._request_with_failover = lambda _request_fn, operation: response
    return client


@pytest.mark.anyio
async def test_chat_records_usage_metadata(caplog):
    caplog.set_level(logging.INFO, logger="services.llm_client")
    response = _fake_response(
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3, total_tokens=15)
    )
    client = _make_uninitialized_client(response)

    result = await client.chat(messages=[{"role": "user", "content": "hello"}])

    assert result.usage == {
        "prompt_tokens": 12,
        "completion_tokens": 3,
        "total_tokens": 15,
    }
    assert "[TOKEN_TELEMETRY]" in caplog.text
    assert "telemetry-model" in caplog.text


@pytest.mark.anyio
async def test_chat_json_logs_dict_usage_without_changing_return_value(caplog):
    caplog.set_level(logging.INFO, logger="services.llm_client")
    response = _fake_response(content='{"ok": true}', usage={"prompt_tokens": 5, "total_tokens": 7})
    client = _make_uninitialized_client(response)

    result = await client.chat_json(messages=[{"role": "user", "content": "{}"}])

    assert result == {"ok": True}
    assert "[TOKEN_TELEMETRY]" in caplog.text
    assert "total=7" in caplog.text


def _make_failover_client():
    client = object.__new__(LLMClientService)
    client.model = "retry-model"
    client.purpose = "agent"
    client._client_proxy = None
    client._client_direct = "direct-client"
    client.client = client._client_direct
    client._retry_sleep_calls = []
    client._retry_sleep = client._retry_sleep_calls.append
    return client


def test_request_with_failover_retries_transient_connection_errors(caplog):
    caplog.set_level(logging.WARNING, logger="services.llm_client")
    client = _make_failover_client()
    calls = {"count": 0}
    response = object()

    def request_fn(_client):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("connection error: temporary network issue")
        return response

    result = client._request_with_failover(request_fn, operation="retry-test")

    assert result is response
    assert calls["count"] == 2
    assert client._retry_sleep_calls == [1.0]
    assert "retrying in 1.0s" in caplog.text


def test_request_with_failover_does_not_retry_non_connection_errors():
    client = _make_failover_client()
    calls = {"count": 0}

    def request_fn(_client):
        calls["count"] += 1
        raise ValueError("invalid request")

    with pytest.raises(ValueError):
        client._request_with_failover(request_fn, operation="non-retry-test")

    assert calls["count"] == 1
    assert client._retry_sleep_calls == []
