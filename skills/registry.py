"""Legacy skills registry retained for deprecated scripts.

The active runtime registers tools through `tools.registry`. This module now
loads any remaining direct skill implementations on a best-effort basis so old
diagnostic scripts do not fail immediately when a legacy skill module is stale
or missing.
"""
import importlib
import logging
from typing import Dict, List, Optional, Tuple
from .base import BaseSkill

logger = logging.getLogger(__name__)

LEGACY_SKILL_SPECS: Tuple[Tuple[str, str], ...] = (
    ("skills.emission_factors.skill", "EmissionFactorsSkill"),
    ("skills.micro_emission.skill", "MicroEmissionSkill"),
    ("skills.macro_emission.skill", "MacroEmissionSkill"),
    ("skills.knowledge.skill", "KnowledgeSkill"),
)


class SkillRegistry:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._skills = {}
        return cls._instance

    def register(self, skill: BaseSkill):
        self._skills[skill.name] = skill

    def get(self, name: str) -> Optional[BaseSkill]:
        return self._skills.get(name)

    def all(self) -> List[BaseSkill]:
        return list(self._skills.values())

def init_skills():
    """Best-effort legacy skill registration for deprecated compatibility paths."""
    registry = SkillRegistry()

    for module_path, class_name in LEGACY_SKILL_SPECS:
        skill = _load_skill_instance(module_path, class_name)
        if skill is not None:
            registry.register(skill)

    return registry

def get_registry():
    return SkillRegistry()


def _load_skill_instance(module_path: str, class_name: str) -> Optional[BaseSkill]:
    """Import and instantiate a legacy skill without failing the whole registry."""
    try:
        module = importlib.import_module(module_path)
        skill_cls = getattr(module, class_name)
        return skill_cls()
    except Exception as exc:
        logger.warning(
            "Skipping legacy skill %s from %s: %s",
            class_name,
            module_path,
            exc,
        )
        return None
