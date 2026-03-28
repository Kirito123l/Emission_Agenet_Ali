"""
Skill-based prompt injector.
Determines which skills and tool schemas to inject based on conversation state.

Three-layer injection:
  Layer 1: Core system prompt (always present)
  Layer 2: Tool skills (loaded from config/skills/*.yaml, injected by intent)
  Layer 3: Situational prompts (post-tool guides, dynamic)
"""
import logging
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Set

from core.tool_dependencies import (
    TOOL_GRAPH,
    get_required_result_tokens,
    get_tool_provides,
    normalize_tokens,
    suggest_prerequisite_tool,
)

logger = logging.getLogger(__name__)

SKILL_DIR = Path(__file__).parent.parent / "config" / "skills"

# Keyword-based intent detection rules
INTENT_RULES: Dict[str, Dict] = {
    "dispersion": {
        "keywords": ["扩散", "浓度", "dispersion", "concentration", "大气", "污染物扩散", "扩散分析"],
        "tools": ["calculate_dispersion", "render_spatial_map"],
        "skills": ["dispersion_skill", "meteorology_guide"],
    },
    "hotspot": {
        "keywords": ["热点", "hotspot", "高浓度", "浓度最高", "溯源", "贡献", "来源", "哪条路"],
        "tools": ["analyze_hotspots", "render_spatial_map"],
        "skills": ["hotspot_skill"],
    },
    "emission": {
        "keywords": ["排放", "emission", "计算排放", "宏观", "微观", "路段排放"],
        "tools": ["calculate_macro_emission", "calculate_micro_emission", "analyze_file"],
        "skills": ["emission_skill"],
    },
    "visualization": {
        "keywords": ["地图", "可视化", "visualization", "map", "展示", "显示", "渲染", "看看"],
        "tools": ["render_spatial_map"],
        "skills": ["spatial_skill"],
    },
    "scenario": {
        "keywords": [
            "情景", "对比", "如果", "假设", "场景", "scenario", "what if",
            "降低", "提高", "减少", "增加", "调整", "改成", "设为", "限速",
            "对比下", "试试", "看看效果",
        ],
        "tools": [],
        "skills": ["scenario_skill"],
    },
    "query_ef": {
        "keywords": ["排放因子", "曲线", "emission factor", "因子"],
        "tools": ["query_emission_factors"],
        "skills": [],
    },
    "knowledge": {
        "keywords": ["知识", "标准", "法规", "什么是", "解释"],
        "tools": ["query_knowledge"],
        "skills": [],
    },
}

# Post-tool guides keyed by last_tool_name
POST_TOOL_GUIDES: Dict[str, str] = {
    "calculate_macro_emission": "post_emission_guide",
    "calculate_micro_emission": "post_emission_guide",
    "calculate_dispersion": "post_dispersion_guide",
    "analyze_hotspots": "post_hotspot_guide",
}

class SkillInjector:
    """Determines which skills and tool schemas to inject based on user intent."""

    def __init__(self):
        self._skill_cache: Dict[str, str] = {}

    def detect_intents(
        self,
        user_message: str,
        last_tool_name: Optional[str] = None,
        file_context: Optional[dict] = None,
        available_results: Optional[set] = None,
    ) -> Set[str]:
        """Detect user intent from message + conversation state.

        Returns a set of intent keys (e.g. {"dispersion", "emission"}).
        Special key "_fallback_all" means no specific intent detected.
        """
        intents: Set[str] = set()
        msg_lower = user_message.lower()

        # 1. Keyword matching on user message
        for intent_key, rule in INTENT_RULES.items():
            if any(kw in msg_lower for kw in rule["keywords"]):
                intents.add(intent_key)

        # 2. File context drives emission intent
        if file_context:
            task_type = file_context.get("task_type") or file_context.get("detected_type")
            if task_type in ("micro_emission", "macro_emission"):
                intents.add("emission")
            intents.add("file_upload")

        # 3. Dependency auto-补充: if a detected intent's tools have unmet
        #    prerequisites, inject the prerequisite tools' intents too.
        if available_results is None:
            available_results = set()
        intents = self._expand_dependencies(intents, available_results, last_tool_name)

        # 4. If no keyword intent detected, use post-tool guide as context
        if not intents and last_tool_name:
            for intent_key, rule in INTENT_RULES.items():
                if last_tool_name in rule.get("tools", []):
                    intents.add(intent_key)

        if last_tool_name and last_tool_name in POST_TOOL_GUIDES and (
            not intents or any(last_tool_name in INTENT_RULES.get(intent, {}).get("tools", []) for intent in intents)
        ):
            intents.add(f"post_{last_tool_name}")

        # 5. Safety fallback
        if not intents:
            intents.add("_fallback_all")

        return intents

    def _expand_dependencies(
        self,
        intents: Set[str],
        available_results: set,
        last_tool_name: Optional[str],
    ) -> Set[str]:
        """Auto-inject prerequisite tool intents when dependencies are unmet.

        Expands recursively so chains like hotspot→dispersion→emission are
        fully resolved.
        """
        expanded = set(intents)

        # Consider last_tool_name as a signal of available results
        effective_available = set(normalize_tokens(available_results))
        if last_tool_name and last_tool_name in TOOL_GRAPH:
            effective_available.update(get_tool_provides(last_tool_name))

        # Iterate until no new intents are added (handles transitive deps)
        changed = True
        while changed:
            changed = False
            # Collect all tools from current expanded intents
            needed_tools: Set[str] = set()
            for intent in expanded:
                rule = INTENT_RULES.get(intent, {})
                needed_tools.update(rule.get("tools", []))

            for tool_name in list(needed_tools):
                requires = get_required_result_tokens(tool_name)
                for req in requires:
                    if req not in effective_available:
                        prereq_tool = suggest_prerequisite_tool(req)
                        if prereq_tool:
                            for intent_key, rule in INTENT_RULES.items():
                                if prereq_tool in rule.get("tools", []):
                                    if intent_key not in expanded:
                                        expanded.add(intent_key)
                                        changed = True
                                        logger.info(
                                            f"Auto-injected '{intent_key}' intent: "
                                            f"{tool_name} requires '{req}', "
                                            f"adding {prereq_tool}"
                                        )
                                    break

        return expanded

    def get_tools_for_intents(
        self,
        intents: Set[str],
        all_tool_definitions: list,
    ) -> list:
        """Always return all tools and let the LLM decide which one to call."""
        return list(all_tool_definitions)

    def get_situational_prompt(
        self,
        intents: Set[str],
        last_tool_name: Optional[str] = None,
    ) -> str:
        """Build situational prompt (Layer 2 skills + Layer 3 guides).

        Returns combined text to inject into the system prompt's
        {situational_prompt} placeholder.
        """
        parts: List[str] = []

        # Layer 3: Post-tool guides (based on last_tool_name)
        if last_tool_name and last_tool_name in POST_TOOL_GUIDES:
            guide_name = POST_TOOL_GUIDES[last_tool_name]
            content = self._load_skill(guide_name)
            if content:
                parts.append(content)

        # Layer 2: Intent-specific skill content
        for intent in sorted(intents):  # sorted for deterministic output
            rule = INTENT_RULES.get(intent, {})
            for skill_name in rule.get("skills", []):
                content = self._load_skill(skill_name)
                if content:
                    parts.append(content)

        # file_upload intent has its own skill
        if "file_upload" in intents:
            content = self._load_skill("file_upload_guide")
            if content:
                parts.append(content)

        return "\n\n".join(parts)

    def _load_skill(self, skill_name: str) -> Optional[str]:
        """Load skill content from YAML file with caching."""
        if skill_name in self._skill_cache:
            return self._skill_cache[skill_name]

        path = SKILL_DIR / f"{skill_name}.yaml"
        if not path.exists():
            logger.warning(f"Skill file not found: {path}")
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            content = data.get("content", "")
            self._skill_cache[skill_name] = content
            return content
        except Exception as e:
            logger.error(f"Failed to load skill {skill_name}: {e}")
            return None
