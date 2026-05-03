from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from core.naive_router import NAIVE_SYSTEM_PROMPT, NaiveRouter
from services.llm_client import LLMResponse, ToolCall
from tools.base import ToolResult
from tools.contract_loader import get_tool_contract_registry


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def chat_with_tools(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        return self.responses.pop(0)


class FakeRegistry:
    def __init__(self, tools):
        self.tools = dict(tools)

    def list_tools(self):
        return list(self.tools)

    def get(self, name):
        return self.tools.get(name)


class RecordingTool:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def execute(self, **kwargs):
        self.calls.append(dict(kwargs))
        next_response = self.responses.pop(0)
        if isinstance(next_response, Exception):
            raise next_response
        return next_response


def _tool_names(definitions):
    return [item["function"]["name"] for item in definitions]


def test_naive_router_uses_configured_agent_model(monkeypatch, tmp_path):
    captured = {}

    class FakeConfiguredLLM:
        model = "configured-agent-model"

        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

    monkeypatch.setattr("core.naive_router.LLMClientService", FakeConfiguredLLM)

    router = NaiveRouter(
        session_id="configured-model-test",
        registry=FakeRegistry({"calculate_macro_emission": object()}),
        tool_call_log_path=tmp_path / "calls.jsonl",
    )

    assert router.llm.model == "configured-agent-model"
    assert captured["args"] == ()
    assert captured["kwargs"] == {"temperature": 0.0, "purpose": "agent"}


def test_naive_router_uses_only_the_seven_baseline_tool_schemas(tmp_path):
    router = NaiveRouter(
        session_id="schema-test",
        llm=FakeLLM([LLMResponse(content="done")]),
        registry=FakeRegistry({"calculate_macro_emission": object()}),
        tool_call_log_path=tmp_path / "calls.jsonl",
    )

    naive_tool_names = get_tool_contract_registry().get_naive_available_tools()
    assert _tool_names(router.tool_definitions) == naive_tool_names
    assert "analyze_file" not in _tool_names(router.tool_definitions)
    assert "clean_dataframe" not in _tool_names(router.tool_definitions)
    assert "compare_scenarios" not in _tool_names(router.tool_definitions)


@pytest.mark.anyio
async def test_naive_router_passes_raw_arguments_and_logs_tool_call(tmp_path):
    raw_args = {
        "file_path": "/tmp/raw_links.csv",
        "pollutants": ["氮氧化物"],
        "season": "夏天",
    }
    tool = RecordingTool(
        [
            ToolResult(
                success=True,
                data={"echo": raw_args},
                summary="宏观排放计算完成",
                table_data={"rows": [{"link_id": "A"}]},
            )
        ]
    )
    llm = FakeLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="calculate_macro_emission",
                        arguments=raw_args,
                    )
                ],
            ),
            LLMResponse(content="完成"),
        ]
    )
    log_path = tmp_path / "naive_calls.jsonl"
    router = NaiveRouter(
        session_id="raw-test",
        llm=llm,
        registry=FakeRegistry({"calculate_macro_emission": tool}),
        tool_call_log_path=log_path,
    )

    result = await router.chat("计算这个文件", file_path="/tmp/raw_links.csv")

    assert llm.calls[0]["system"] == NAIVE_SYSTEM_PROMPT
    assert _tool_names(llm.calls[0]["tools"]) == get_tool_contract_registry().get_naive_available_tools()
    assert "文件已上传，路径: /tmp/raw_links.csv" in llm.calls[0]["messages"][-1]["content"]
    assert tool.calls == [raw_args]
    assert result.text == "完成"
    assert result.table_data == {"rows": [{"link_id": "A"}]}
    assert result.executed_tool_calls[0]["arguments"] == raw_args

    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert rows == [
        {
            "timestamp": rows[0]["timestamp"],
            "session_id": "raw-test",
            "iteration": 1,
            "tool_call_id": "call-1",
            "tool_name": "calculate_macro_emission",
            "raw_parameters": raw_args,
            "execution_success": True,
            "error_message": None,
        }
    ]


@pytest.mark.anyio
async def test_naive_router_returns_tool_errors_to_llm_and_allows_retry(tmp_path):
    first_args = {"pollutants": ["CO2"]}
    retry_args = {"file_path": "/tmp/links.csv", "pollutants": ["CO2"]}
    tool = RecordingTool(
        [
            ToolResult(success=False, error="Missing required parameter: file_path", data=None),
            ToolResult(success=True, data={"rows": [1]}, summary="retry ok"),
        ]
    )
    llm = FakeLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="bad-call",
                        name="calculate_macro_emission",
                        arguments=first_args,
                    )
                ],
            ),
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        id="retry-call",
                        name="calculate_macro_emission",
                        arguments=retry_args,
                    )
                ],
            ),
            LLMResponse(content="已重试并完成"),
        ]
    )
    log_path = tmp_path / "retry_calls.jsonl"
    router = NaiveRouter(
        session_id="retry-test",
        llm=llm,
        registry=FakeRegistry({"calculate_macro_emission": tool}),
        tool_call_log_path=log_path,
    )

    result = await router.chat("算排放")

    assert tool.calls == [first_args, retry_args]
    assert result.text == "已重试并完成"
    assert [call["arguments"] for call in result.executed_tool_calls] == [first_args, retry_args]
    assert "Missing required parameter: file_path" in llm.calls[1]["messages"][-1]["content"]

    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert [row["execution_success"] for row in rows] == [False, True]
    assert rows[0]["error_message"] == "Missing required parameter: file_path"


def test_naive_file_message_only_provides_path():
    from api.routes import build_router_user_message

    message = build_router_user_message("请计算", Path("/tmp/example.csv"), "naive")

    assert message == "请计算\n\n文件已上传，路径: /tmp/example.csv"
    assert "input_file" not in message
