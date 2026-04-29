"""Integration tests for tool extensibility (Phase 5.2 Round 4).

Validates that adding a new tool requires only:
  1. A BaseTool subclass
  2. A YAML entry in tool_contracts.yaml
  3. One register_tool() call in registry.init_tools

No agent-layer code changes needed (governed_router / ao_manager / naive_router).

These tests are the concrete evidence for the paper's §4.5 "tool extensibility"
claim — each test verifies that a specific agent-layer component recognizes
a dynamically-added tool with zero code changes to that component.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

from tools.base import BaseTool, ToolResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _DummyTool(BaseTool):
    """Minimal BaseTool subclass: only the required execute() method."""

    async def execute(self, **kwargs) -> ToolResult:
        return self._success(
            data={"echo": kwargs},
            summary=f"Dummy processed: {kwargs.get('input_text', '')}",
        )


def _make_dummy_tool_spec(*, available_in_naive: bool = True) -> Dict[str, Any]:
    """Return a complete tool_contracts.yaml entry for a dummy tool."""
    return {
        "display_name": "Dummy Tool",
        "description": "Fake tool for extensibility testing",
        "required_slots": ["input_text"],
        "optional_slots": ["count", "flag"],
        "defaults": {},
        "clarification_followup_slots": [],
        "confirm_first_slots": [],
        "parameters": {
            "input_text": {
                "required": True,
                "standardization": None,
                "type_coercion": "as_string",
                "schema": {"type": "string", "description": "Input text"},
            },
            "count": {
                "required": False,
                "standardization": None,
                "type_coercion": "safe_int",
                "schema": {"type": "integer", "description": "Number of iterations"},
            },
            "flag": {
                "required": False,
                "standardization": None,
                "type_coercion": "preserve",
                "schema": {"type": "string", "description": "A flag option"},
            },
        },
        "dependencies": {"requires": [], "provides": ["dummy_result"]},
        "readiness": {
            "required_result_tokens": [],
            "requires_geometry_support": False,
            "required_task_types": [],
        },
        "continuation_keywords": ["dummy", "假"],
        "completion_keywords": {
            "primary": ["dummy", "假"],
            "secondary": [],
            "requires": [],
        },
        "available_in_naive": available_in_naive,
    }


# ---------------------------------------------------------------------------
# Isolation fixture — yield → teardown always runs (even on test failure)
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Provide an isolated tool contract registry + tool registry.

    Teardown (via yield) always runs, even on test assertion failure,
    guaranteeing cleanup of both the contract registry singleton and
    the tool registry.
    """
    from tools.contract_loader import ToolContractRegistry
    from tools.registry import get_registry, init_tools

    tool_registry = get_registry()

    # --- setup ---
    original_yaml_path = (
        Path(__file__).resolve().parents[1] / "config" / "tool_contracts.yaml"
    )
    with open(original_yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    data.setdefault("tools", {})
    data.setdefault("tool_definition_order", [])

    dummy_spec = _make_dummy_tool_spec()
    data["tools"]["dummy_tool"] = dummy_spec
    data["tool_definition_order"].append("dummy_tool")

    temp_yaml = tmp_path / "tool_contracts_temp.yaml"
    with open(temp_yaml, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True)

    temp_registry = ToolContractRegistry(temp_yaml)

    import tools.contract_loader as cl

    monkeypatch.setattr(cl, "_registry", temp_registry)

    dummy_tool = _DummyTool()
    tool_registry.register("dummy_tool", dummy_tool)

    yield temp_registry, dummy_tool

    # --- teardown (always runs) ---
    tool_registry.clear()
    init_tools()


@pytest.fixture
def isolated_registry_excluded_in_naive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Same as isolated_registry but available_in_naive=False."""
    from tools.contract_loader import ToolContractRegistry
    from tools.registry import get_registry, init_tools

    tool_registry = get_registry()

    original_yaml_path = (
        Path(__file__).resolve().parents[1] / "config" / "tool_contracts.yaml"
    )
    with open(original_yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    data.setdefault("tools", {})
    data.setdefault("tool_definition_order", [])

    dummy_spec = _make_dummy_tool_spec(available_in_naive=False)
    data["tools"]["dummy_tool"] = dummy_spec
    data["tool_definition_order"].append("dummy_tool")

    temp_yaml = tmp_path / "tool_contracts_naive_false.yaml"
    with open(temp_yaml, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True)

    temp_registry = ToolContractRegistry(temp_yaml)

    import tools.contract_loader as cl

    monkeypatch.setattr(cl, "_registry", temp_registry)

    dummy_tool = _DummyTool()
    tool_registry.register("dummy_tool", dummy_tool)

    yield temp_registry, dummy_tool

    tool_registry.clear()
    init_tools()


# ---------------------------------------------------------------------------
# E-剩余.6 — 3 integration tests
# ---------------------------------------------------------------------------


def test_dummy_tool_via_yaml_only_recognized_by_all_agent_layers(
    isolated_registry,
):
    """Adding a tool via YAML + registry → recognised by all 5 agent layers.

    This is the paper's §4.5 evidence: no changes to governed_router /
    ao_manager / naive_router source code are needed for a new tool to
    be fully functional across every agent component.
    """
    temp_registry, _dummy_tool = isolated_registry

    # 1. Tool registry (layer: tools/)
    from tools.registry import get_registry

    tool_names = [str(n) for n in get_registry().list_tools()]
    assert "dummy_tool" in tool_names

    # 2. Type coercion declarations (layer: tools/contract_loader)
    coercions = temp_registry.get_type_coercion("dummy_tool")
    assert coercions.get("input_text") == "as_string"
    assert coercions.get("count") == "safe_int"
    assert coercions.get("flag") == "preserve"

    # 3. _snapshot_to_tool_args (layer: core/governed_router)
    from core.governed_router import GovernedRouter

    snapshot = {
        "input_text": {"value": "hello world", "source": "user"},
        "count": {"value": "5", "source": "user"},
        "flag": {"value": None, "source": "missing"},
    }
    args = GovernedRouter._snapshot_to_tool_args("dummy_tool", snapshot)
    assert args["input_text"] == "hello world", "as_string coercion"
    assert args["count"] == 5, "safe_int coercion"
    assert "flag" not in args, "source=missing should be skipped"

    # 4. _extract_implied_tools (layer: core/ao_manager)
    from core.ao_manager import AOManager

    class _FakeMemory:
        current_ao_id = None

    manager = AOManager(_FakeMemory())
    groups = manager._extract_implied_tools("使用 dummy 工具处理数据")
    flat_tools = set()
    for g in groups:
        flat_tools.update(g)
    assert "dummy_tool" in flat_tools, (
        f"expected dummy_tool in implied tools, got {flat_tools}"
    )

    # 5. NaiveRouter (layer: core/naive_router)
    from core.naive_router import NaiveRouter

    naive_defs = NaiveRouter._load_naive_tool_definitions()
    naive_names = [item["function"]["name"] for item in naive_defs]
    assert "dummy_tool" in naive_names, (
        f"dummy_tool should be in NaiveRouter whitelist, got {naive_names}"
    )


def test_dummy_tool_excluded_from_naive_when_available_in_naive_false(
    isolated_registry_excluded_in_naive,
):
    """available_in_naive: false → NaiveRouter excludes the tool."""
    from core.naive_router import NaiveRouter

    naive_defs = NaiveRouter._load_naive_tool_definitions()
    naive_names = [item["function"]["name"] for item in naive_defs]
    assert "dummy_tool" not in naive_names, (
        f"dummy_tool should NOT be in NaiveRouter whitelist, got {naive_names}"
    )


def test_dummy_tool_completion_keywords_secondary_plus_requires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """secondary + requires AND logic works for dynamically-added tools."""
    from tools.contract_loader import ToolContractRegistry
    from tools.registry import get_registry, init_tools

    tool_registry = get_registry()

    original_yaml_path = (
        Path(__file__).resolve().parents[1] / "config" / "tool_contracts.yaml"
    )
    with open(original_yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    data.setdefault("tools", {})
    data.setdefault("tool_definition_order", [])

    spec = {
        "display_name": "Dummy Secondary",
        "description": "Tool testing secondary+requires AND logic",
        "required_slots": [],
        "optional_slots": [],
        "defaults": {},
        "clarification_followup_slots": [],
        "confirm_first_slots": [],
        "parameters": {
            "input_text": {
                "required": True,
                "standardization": None,
                "type_coercion": "as_string",
                "schema": {"type": "string", "description": "Input text"},
            },
        },
        "dependencies": {"requires": [], "provides": ["dummy_result"]},
        "readiness": {
            "required_result_tokens": [],
            "requires_geometry_support": False,
            "required_task_types": [],
        },
        "continuation_keywords": [],
        "completion_keywords": {
            "primary": [],
            "secondary": ["辅助", "auxiliary"],
            "requires": ["测试", "test"],
        },
        "available_in_naive": True,
    }
    data["tools"]["dummy_secondary_tool"] = spec
    data["tool_definition_order"].append("dummy_secondary_tool")

    temp_yaml = tmp_path / "tool_contracts_secondary.yaml"
    with open(temp_yaml, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True)

    temp_registry = ToolContractRegistry(temp_yaml)

    import tools.contract_loader as cl

    monkeypatch.setattr(cl, "_registry", temp_registry)
    tool_registry.register("dummy_secondary_tool", _DummyTool())

    from core.ao_manager import AOManager

    class _FakeMemory:
        current_ao_id = None

    manager = AOManager(_FakeMemory())

    # Case A: secondary only (no requires) → NOT triggered
    groups = manager._extract_implied_tools("启动辅助模块处理")
    flat = set()
    for g in groups:
        flat.update(g)
    assert "dummy_secondary_tool" not in flat

    # Case B: secondary + requires both present → triggered
    groups = manager._extract_implied_tools("对辅助模块进行测试验证")
    flat = set()
    for g in groups:
        flat.update(g)
    assert "dummy_secondary_tool" in flat

    # Case C: requires only (no secondary) → NOT triggered
    assert manager._extract_implied_tools("运行测试") == []

    # Cleanup
    tool_registry.clear()
    init_tools()
