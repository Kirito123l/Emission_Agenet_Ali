"""Unit tests for _extract_implied_tools with declarative completion_keywords.

Phase 5.2 Round 3: validates that the 3-tier (primary/secondary/requires)
YAML-driven algorithm reproduces the original hardcoded behaviour.
"""

from __future__ import annotations

from core.ao_manager import AOManager


class _FakeMemory:
    current_ao_id = None


def _manager():
    return AOManager(_FakeMemory())


# ---------------------------------------------------------------------------
# Primary keyword (exclusive) tests
# ---------------------------------------------------------------------------

def test_primary_keyword_hit_exclusive():
    """'因子' in text → [{query_emission_factors}] exclusive, no other groups."""
    groups = _manager()._extract_implied_tools("查询排放因子")
    assert groups == [{"query_emission_factors"}]


def test_primary_keyword_english():
    """'factor' in text → [{query_emission_factors}]."""
    groups = _manager()._extract_implied_tools("get emission factor for CO2")
    assert groups == [{"query_emission_factors"}]


# ---------------------------------------------------------------------------
# Secondary + requires (AND logic) tests
# ---------------------------------------------------------------------------

def test_secondary_plus_requires_and_logic_triggers():
    """'排放' + '计算' → [{calculate_macro_emission, calculate_micro_emission}]."""
    groups = _manager()._extract_implied_tools("计算碳排放")
    assert {"calculate_macro_emission", "calculate_micro_emission"} in groups


def test_secondary_without_requires_does_not_trigger():
    """'排放' alone (no '计算') → macro/micro NOT triggered."""
    groups = _manager()._extract_implied_tools("查看排放数据")
    # No group should contain calculate_macro_emission or calculate_micro_emission
    all_tools = set()
    for group in groups:
        all_tools.update(group)
    assert "calculate_macro_emission" not in all_tools
    assert "calculate_micro_emission" not in all_tools


# ---------------------------------------------------------------------------
# Primary exclusivity — blocks secondary matches
# ---------------------------------------------------------------------------

def test_primary_excludes_secondary():
    """'排放因子' contains both '因子' (primary) and '排放' (secondary).
    Primary wins → only [{query_emission_factors}], macro/micro NOT triggered.
    """
    groups = _manager()._extract_implied_tools("查询排放因子曲线")
    assert groups == [{"query_emission_factors"}]


# ---------------------------------------------------------------------------
# Plain secondary (no requires) keyword tests
# ---------------------------------------------------------------------------

def test_secondary_only_keyword_triggers():
    """'扩散' → [{calculate_dispersion}]."""
    groups = _manager()._extract_implied_tools("模拟污染物扩散")
    assert {"calculate_dispersion"} in groups


def test_multiple_groups_independent():
    """'扩散' + '地图' → [{calculate_dispersion}, {render_spatial_map}]."""
    groups = _manager()._extract_implied_tools("先模拟扩散，然后在地图上渲染结果")
    tool_sets = [set(g) for g in groups]
    assert {"calculate_dispersion"} in tool_sets
    assert {"render_spatial_map"} in tool_sets


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_text_returns_empty():
    assert _manager()._extract_implied_tools("") == []
    assert _manager()._extract_implied_tools("   ") == []


def test_no_matching_keywords_returns_empty():
    assert _manager()._extract_implied_tools("今天天气怎么样") == []


def test_knowledge_keyword_triggers():
    """'知识' → [{query_knowledge}]."""
    groups = _manager()._extract_implied_tools("查询相关知识")
    assert {"query_knowledge"} in groups


def test_hotspot_keyword_triggers():
    """'热点' → [{analyze_hotspots}]."""
    groups = _manager()._extract_implied_tools("分析污染热点区域")
    assert {"analyze_hotspots"} in groups


def test_render_keyword_triggers():
    """'画图' → [{render_spatial_map}]."""
    groups = _manager()._extract_implied_tools("画图展示结果")
    assert {"render_spatial_map"} in groups
