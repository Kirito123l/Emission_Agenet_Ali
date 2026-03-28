"""Tests for SkillInjector intent detection and tool selection."""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.skill_injector import SkillInjector, INTENT_RULES, POST_TOOL_GUIDES
from tools.definitions import TOOL_DEFINITIONS


@pytest.fixture
def injector():
    return SkillInjector()


# ── Intent Detection ──────────────────────────────────────────────


class TestDetectIntents:

    def test_dispersion_chinese(self, injector):
        intents = injector.detect_intents("帮我做扩散分析")
        assert "dispersion" in intents

    def test_dispersion_english(self, injector):
        intents = injector.detect_intents("run dispersion analysis")
        assert "dispersion" in intents

    def test_dispersion_concentration(self, injector):
        intents = injector.detect_intents("我想看浓度分布")
        assert "dispersion" in intents

    def test_hotspot_chinese(self, injector):
        intents = injector.detect_intents("哪里浓度最高")
        assert "hotspot" in intents

    def test_hotspot_source(self, injector):
        intents = injector.detect_intents("哪条路贡献最大")
        assert "hotspot" in intents

    def test_emission_chinese(self, injector):
        intents = injector.detect_intents("计算排放")
        assert "emission" in intents

    def test_emission_macro(self, injector):
        intents = injector.detect_intents("帮我算宏观路段排放")
        assert "emission" in intents

    def test_visualization_chinese(self, injector):
        intents = injector.detect_intents("在地图上显示")
        assert "visualization" in intents

    def test_visualization_render(self, injector):
        intents = injector.detect_intents("渲染结果")
        assert "visualization" in intents

    def test_query_ef(self, injector):
        intents = injector.detect_intents("查一下排放因子曲线")
        assert "query_ef" in intents

    def test_knowledge(self, injector):
        intents = injector.detect_intents("什么是国六排放标准")
        assert "knowledge" in intents

    def test_multi_intent(self, injector):
        intents = injector.detect_intents("帮我算完排放后做扩散分析")
        assert "emission" in intents
        assert "dispersion" in intents

    def test_scenario_intent_detected(self, injector):
        intents = injector.detect_intents("如果把速度降到30看看效果")
        assert "scenario" in intents

    def test_file_context_drives_emission(self, injector):
        intents = injector.detect_intents(
            "分析这个文件",
            file_context={"task_type": "macro_emission"},
        )
        assert "emission" in intents
        assert "file_upload" in intents

    def test_file_context_micro(self, injector):
        intents = injector.detect_intents(
            "计算这个",
            file_context={"task_type": "micro_emission"},
        )
        assert "emission" in intents

    def test_file_context_unknown_no_emission(self, injector):
        intents = injector.detect_intents(
            "看看这个文件",
            file_context={"task_type": "unknown"},
        )
        assert "file_upload" in intents
        # "看看" triggers visualization
        assert "visualization" in intents

    def test_post_tool_guide_emission(self, injector):
        intents = injector.detect_intents(
            "接下来呢",
            last_tool_name="calculate_macro_emission",
        )
        assert "post_calculate_macro_emission" in intents
        assert "_fallback_all" not in intents

    def test_post_tool_guide_dispersion(self, injector):
        intents = injector.detect_intents(
            "然后呢",
            last_tool_name="calculate_dispersion",
        )
        assert "post_calculate_dispersion" in intents

    def test_fallback_all(self, injector):
        intents = injector.detect_intents("你好")
        assert "_fallback_all" in intents

    def test_empty_message(self, injector):
        intents = injector.detect_intents("")
        assert "_fallback_all" in intents

    def test_fallback_reuses_last_tool_intent_context(self, injector):
        intents = injector.detect_intents("OK", last_tool_name="calculate_dispersion")
        assert "dispersion" in intents
        assert "_fallback_all" not in intents

    def test_dependency_expansion_dispersion_needs_emission(self, injector):
        """Dispersion without emission result should auto-inject emission intent."""
        intents = injector.detect_intents(
            "帮我做扩散分析",
            available_results=set(),  # no emission_result
            last_tool_name=None,
        )
        assert "dispersion" in intents
        assert "emission" in intents  # auto-expanded

    def test_dependency_not_expanded_when_available(self, injector):
        """Dispersion with emission_result available should NOT inject emission."""
        intents = injector.detect_intents(
            "帮我做扩散分析",
            available_results={"emission_result"},
        )
        assert "dispersion" in intents
        assert "emission" not in intents

    def test_dependency_dispersion_via_last_tool(self, injector):
        """If last tool was macro emission, dispersion deps are met."""
        intents = injector.detect_intents(
            "帮我做扩散分析",
            last_tool_name="calculate_macro_emission",
        )
        assert "dispersion" in intents
        # emission should NOT be auto-injected because last_tool provides it
        assert "emission" not in intents

    def test_hotspot_dependency_chain(self, injector):
        """Hotspot without dispersion result should auto-inject dispersion + emission."""
        intents = injector.detect_intents(
            "找热点",
            available_results=set(),
            last_tool_name=None,
        )
        assert "hotspot" in intents
        assert "dispersion" in intents
        assert "emission" in intents


# ── Tool Selection ────────────────────────────────────────────────


class TestGetToolsForIntents:

    def test_dispersion_returns_all_tools(self, injector):
        tools = injector.get_tools_for_intents({"dispersion"}, TOOL_DEFINITIONS)
        assert len(tools) == len(TOOL_DEFINITIONS)

    def test_fallback_returns_all(self, injector):
        tools = injector.get_tools_for_intents({"_fallback_all"}, TOOL_DEFINITIONS)
        assert len(tools) == len(TOOL_DEFINITIONS)

    def test_emission_returns_all_tools(self, injector):
        tools = injector.get_tools_for_intents({"emission"}, TOOL_DEFINITIONS)
        assert len(tools) == len(TOOL_DEFINITIONS)

    def test_multi_intent_still_returns_all_tools(self, injector):
        tools = injector.get_tools_for_intents(
            {"emission", "dispersion"}, TOOL_DEFINITIONS
        )
        assert len(tools) == len(TOOL_DEFINITIONS)

    def test_query_ef_returns_all_tools(self, injector):
        tools = injector.get_tools_for_intents({"query_ef"}, TOOL_DEFINITIONS)
        assert len(tools) == len(TOOL_DEFINITIONS)

    def test_post_tool_intent_returns_all_tools(self, injector):
        tools = injector.get_tools_for_intents(
            {"post_calculate_macro_emission"}, TOOL_DEFINITIONS
        )
        assert len(tools) == len(TOOL_DEFINITIONS)


# ── Situational Prompt ────────────────────────────────────────────


class TestGetSituationalPrompt:

    def test_post_emission_guide(self, injector):
        prompt = injector.get_situational_prompt(
            intents=set(),
            last_tool_name="calculate_macro_emission",
        )
        assert "排放" in prompt

    def test_post_dispersion_guide(self, injector):
        prompt = injector.get_situational_prompt(
            intents=set(),
            last_tool_name="calculate_dispersion",
        )
        assert "扩散" in prompt

    def test_post_hotspot_guide(self, injector):
        prompt = injector.get_situational_prompt(
            intents=set(),
            last_tool_name="analyze_hotspots",
        )
        assert "热点" in prompt

    def test_scenario_skill_prompt(self, injector):
        prompt = injector.get_situational_prompt({"scenario"})
        assert "情景模拟指南" in prompt

    def test_dispersion_skill_loaded(self, injector):
        prompt = injector.get_situational_prompt(
            intents={"dispersion"},
            last_tool_name=None,
        )
        assert "气象" in prompt

    def test_dispersion_includes_meteorology(self, injector):
        prompt = injector.get_situational_prompt(
            intents={"dispersion"},
            last_tool_name=None,
        )
        assert "urban_summer_day" in prompt
        assert "等用户确认后再调用工具" in prompt

    def test_file_upload_guide(self, injector):
        prompt = injector.get_situational_prompt(
            intents={"file_upload"},
            last_tool_name=None,
        )
        assert "task_type" in prompt

    def test_no_skill_for_fallback(self, injector):
        prompt = injector.get_situational_prompt(
            intents={"_fallback_all"},
            last_tool_name=None,
        )
        assert prompt == ""

    def test_combined_post_tool_and_intent(self, injector):
        """Post-tool guide and intent skill can coexist."""
        prompt = injector.get_situational_prompt(
            intents={"dispersion"},
            last_tool_name="calculate_macro_emission",
        )
        assert "排放计算已完成" in prompt
        assert "气象" in prompt


# ── Skill File Loading ────────────────────────────────────────────


class TestSkillFileLoading:

    EXPECTED_FILES = [
        "dispersion_skill.yaml",
        "hotspot_skill.yaml",
        "emission_skill.yaml",
        "spatial_skill.yaml",
        "post_emission_guide.yaml",
        "post_dispersion_guide.yaml",
        "post_hotspot_guide.yaml",
        "meteorology_guide.yaml",
        "file_upload_guide.yaml",
    ]

    def test_all_skill_files_exist(self):
        skill_dir = os.path.join(
            os.path.dirname(__file__), "..", "config", "skills"
        )
        for fname in self.EXPECTED_FILES:
            path = os.path.join(skill_dir, fname)
            assert os.path.isfile(path), f"Missing skill file: {fname}"

    def test_all_skills_have_content(self):
        import yaml as _yaml

        skill_dir = os.path.join(
            os.path.dirname(__file__), "..", "config", "skills"
        )
        for fname in self.EXPECTED_FILES:
            path = os.path.join(skill_dir, fname)
            with open(path, "r", encoding="utf-8") as f:
                data = _yaml.safe_load(f)
            assert data.get("content"), f"{fname} has empty content"
            assert len(data["content"]) > 20, f"{fname} content too short"

    def test_skill_caching(self, injector):
        content1 = injector._load_skill("dispersion_skill")
        content2 = injector._load_skill("dispersion_skill")
        assert content1 is content2  # Same object from cache

    def test_missing_skill_returns_none(self, injector):
        assert injector._load_skill("nonexistent_skill") is None
