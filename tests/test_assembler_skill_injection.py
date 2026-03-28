"""Tests for assembler's skill injection integration."""
import os
import sys
import json
import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.assembler import ContextAssembler, AssembledContext
from tools.definitions import TOOL_DEFINITIONS


def _make_assembler(enable_skill: bool):
    """Create assembler with a specific skill injection setting."""
    from services.config_loader import ConfigLoader
    ConfigLoader._prompts_cache = None  # Clear cache between tests

    with patch("config.get_config") as mock_cfg, \
         patch("core.assembler.get_config") as mock_cfg2:
        for m in (mock_cfg, mock_cfg2):
            m.return_value.enable_skill_injection = enable_skill
            m.return_value.enable_file_context_injection = True
        assembler = ContextAssembler()
    # Pin runtime_config so assemble() uses the same setting
    assembler.runtime_config.enable_skill_injection = enable_skill
    assembler.runtime_config.enable_file_context_injection = True
    return assembler


def _empty_fact_memory():
    return {
        "recent_vehicle": None,
        "recent_pollutants": [],
        "recent_year": None,
        "active_file": None,
        "file_analysis": None,
        "last_tool_name": None,
        "last_tool_summary": None,
        "last_tool_snapshot": None,
        "last_spatial_data": None,
    }


def _post_emission_fact_memory():
    fm = _empty_fact_memory()
    fm["last_tool_name"] = "calculate_macro_emission"
    fm["last_tool_summary"] = "Calculated emissions for 150 links"
    return fm


class TestAssemblerSkillMode:

    def test_skill_mode_uses_v3_prompt(self):
        assembler = _make_assembler(enable_skill=True)
        ctx = assembler.assemble(
            "帮我做扩散分析", [], _empty_fact_memory()
        )
        # v3 prompt has "核心规则" section
        assert "核心规则" in ctx.system_prompt
        # v3 prompt should NOT have the old verbose sections
        assert "特别重要：车辆类型确认" not in ctx.system_prompt

    def test_legacy_mode_uses_old_prompt(self):
        assembler = _make_assembler(enable_skill=False)
        ctx = assembler.assemble(
            "帮我做扩散分析", [], _empty_fact_memory()
        )
        # Legacy prompt loads from core.yaml which has these sections
        assert "你的能力" in ctx.system_prompt or "交互原则" in ctx.system_prompt
        # Legacy should NOT have v3-specific "核心规则" phrasing
        assert "核心规则" not in ctx.system_prompt

    def test_dispersion_scenario_tools(self):
        assembler = _make_assembler(enable_skill=True)
        ctx = assembler.assemble(
            "帮我做扩散分析", [],
            _post_emission_fact_memory(),  # emission already done
        )
        tool_names = {t["function"]["name"] for t in ctx.tools}
        assert "calculate_dispersion" in tool_names
        assert "render_spatial_map" in tool_names
        assert len(ctx.tools) == len(TOOL_DEFINITIONS)

    def test_post_emission_situational_prompt(self):
        assembler = _make_assembler(enable_skill=True)
        ctx = assembler.assemble(
            "接下来呢", [], _post_emission_fact_memory()
        )
        assert "排放计算已完成" in ctx.system_prompt

    def test_post_dispersion_situational_prompt(self):
        assembler = _make_assembler(enable_skill=True)
        fm = _empty_fact_memory()
        fm["last_tool_name"] = "calculate_dispersion"
        ctx = assembler.assemble("然后呢", [], fm)
        assert "扩散分析已完成" in ctx.system_prompt

    def test_fallback_all_tools(self):
        assembler = _make_assembler(enable_skill=True)
        ctx = assembler.assemble("你好", [], _empty_fact_memory())
        assert len(ctx.tools) == len(TOOL_DEFINITIONS)

    def test_skill_mode_still_injects_all_tools(self):
        """Skill mode keeps prompt injection but does not filter tool schemas."""
        assembler_skill = _make_assembler(enable_skill=True)
        assembler_legacy = _make_assembler(enable_skill=False)

        fm = _post_emission_fact_memory()
        msg = "帮我做扩散分析"

        ctx_skill = assembler_skill.assemble(msg, [], fm)
        ctx_legacy = assembler_legacy.assemble(msg, [], fm)

        assert len(ctx_skill.tools) == len(TOOL_DEFINITIONS)
        assert len(ctx_legacy.tools) == len(TOOL_DEFINITIONS)
        assert len(json.dumps(ctx_skill.tools)) == len(json.dumps(ctx_legacy.tools))

    def test_file_context_injection(self):
        assembler = _make_assembler(enable_skill=True)
        file_ctx = {
            "filename": "test.xlsx",
            "file_path": "/tmp/test.xlsx",
            "task_type": "macro_emission",
            "row_count": 100,
            "columns": ["link_id", "speed"],
        }
        ctx = assembler.assemble(
            "计算这个文件的排放", [], _empty_fact_memory(), file_context=file_ctx
        )
        tool_names = {t["function"]["name"] for t in ctx.tools}
        assert "calculate_macro_emission" in tool_names
        # File context should be in user message
        user_msg = ctx.messages[-1]["content"]
        assert "test.xlsx" in user_msg

    def test_messages_structure_matches_legacy(self):
        """Both modes should produce same message structure."""
        assembler_skill = _make_assembler(enable_skill=True)
        assembler_legacy = _make_assembler(enable_skill=False)

        fm = _empty_fact_memory()
        fm["recent_vehicle"] = "小汽车"
        wm = [{"user": "之前的问题", "assistant": "之前的回答"}]

        ctx_skill = assembler_skill.assemble("新问题", wm, fm)
        ctx_legacy = assembler_legacy.assemble("新问题", wm, fm)

        # Both should have: system (fact memory) + user/assistant (working) + user (current)
        assert len(ctx_skill.messages) == len(ctx_legacy.messages)
        for s, l in zip(ctx_skill.messages, ctx_legacy.messages):
            assert s["role"] == l["role"]

    def test_dispersion_with_meteo_skill_in_prompt(self):
        """Dispersion intent should inject meteorology guide into system prompt."""
        assembler = _make_assembler(enable_skill=True)
        ctx = assembler.assemble(
            "帮我做扩散分析", [],
            _post_emission_fact_memory(),
        )
        assert "urban_summer_day" in ctx.system_prompt
        assert "等用户确认后再调用工具" in ctx.system_prompt

    def test_emission_skill_in_prompt(self):
        """Emission intent should inject emission skill content."""
        assembler = _make_assembler(enable_skill=True)
        ctx = assembler.assemble(
            "计算排放", [], _empty_fact_memory()
        )
        assert "宏观" in ctx.system_prompt or "微观" in ctx.system_prompt

    def test_scenario_skill_in_prompt(self):
        assembler = _make_assembler(enable_skill=True)
        ctx = assembler.assemble("如果把速度降到30看看效果", [], _empty_fact_memory())
        assert "情景模拟指南" in ctx.system_prompt
