from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.context_store import SessionContextStore
from core.executor import ToolExecutor
from core.governed_router import GovernedRouter
from core.naive_router import NAIVE_TOOL_NAMES, NaiveRouter
from core.router import RouterResponse
from tools.contract_loader import get_tool_contract_registry


class _CleanDataFrameInnerRouter:
    def __init__(self) -> None:
        self.context_store = SessionContextStore()
        self.executor = ToolExecutor()
        self.memory = SimpleNamespace(turn_counter=1)

    async def chat(self, user_message, file_path=None, trace=None):
        result = await self.executor.execute(
            tool_name="clean_dataframe",
            arguments={},
            file_path=file_path,
        )
        self.context_store.add_current_turn_result("clean_dataframe", result)
        return RouterResponse(
            text=result.get("summary", ""),
            executed_tool_calls=[
                {
                    "name": "clean_dataframe",
                    "arguments": {},
                    "result": result,
                }
            ],
            trace={"steps": []},
        )


async def _no_snapshot_execution(context):
    return None


@pytest.mark.anyio
async def test_governed_router_can_call_clean_dataframe_and_store_report(tmp_path) -> None:
    csv_path = tmp_path / "traffic.csv"
    csv_path.write_text("link_id,flow\nA,100\nB,200\n", encoding="utf-8")

    router = object.__new__(GovernedRouter)
    router.inner_router = _CleanDataFrameInnerRouter()
    router.contracts = []
    router._maybe_execute_from_snapshot = _no_snapshot_execution

    result = await router.chat("请清洗这个文件", file_path=str(csv_path), trace={})

    assert result.executed_tool_calls[0]["name"] == "clean_dataframe"
    stored = router.inner_router.context_store.get_by_type("data_quality_report")
    assert stored is not None
    report = stored.data["data"]["report"]
    assert report["row_count"] == 2
    assert report["column_count"] == 2


def test_naive_router_does_not_expose_clean_dataframe() -> None:
    naive_tool_names = [
        item["function"]["name"]
        for item in NaiveRouter._load_naive_tool_definitions()
    ]

    assert "clean_dataframe" not in NAIVE_TOOL_NAMES
    assert "clean_dataframe" not in naive_tool_names


def test_clean_dataframe_contract_exposes_data_quality_report() -> None:
    registry = get_tool_contract_registry()
    graph = registry.get_tool_graph()
    definition_names = [
        item["function"]["name"]
        for item in registry.get_tool_definitions()
    ]

    assert "clean_dataframe" in definition_names
    assert graph["clean_dataframe"]["provides"] == ["data_quality_report"]
    assert registry.get_required_slots("clean_dataframe") == []
    assert registry.get_defaults("clean_dataframe") == {}
