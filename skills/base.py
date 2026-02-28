from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

@dataclass
class SkillResult:
    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

@dataclass
class HealthCheckResult:
    healthy: bool
    checks: Dict[str, bool] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

class BaseSkill(ABC):
    @property
    @abstractmethod
    def name(self) -> str: pass

    @property
    @abstractmethod
    def description(self) -> str: pass

    @abstractmethod
    def execute(self, **params) -> SkillResult: pass

    @abstractmethod
    def get_brief_description(self) -> str: pass

    def health_check(self) -> HealthCheckResult:
        return HealthCheckResult(healthy=True)
