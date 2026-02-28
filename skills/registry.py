from typing import Dict, List, Optional
from .base import BaseSkill

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
    """初始化所有技能"""
    registry = SkillRegistry()
    from .emission_factors.skill import EmissionFactorsSkill
    from .micro_emission.skill import MicroEmissionSkill
    from .macro_emission.skill import MacroEmissionSkill
    from .knowledge.skill import KnowledgeSkill

    registry.register(EmissionFactorsSkill())
    registry.register(MicroEmissionSkill())
    registry.register(MacroEmissionSkill())
    registry.register(KnowledgeSkill())

    return registry

def get_registry():
    return SkillRegistry()
