from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from core.router import RouterResponse


@dataclass
class ContractContext:
    user_message: str
    file_path: Optional[str]
    trace: Optional[Dict[str, Any]]
    state_snapshot: Optional[Any] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    user_message_override: Optional[str] = None
    router_executed: bool = False

    @property
    def effective_user_message(self) -> str:
        return self.user_message_override or self.user_message


@dataclass
class ContractInterception:
    proceed: bool = True
    response: Optional[RouterResponse] = None
    user_message_override: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseContract:
    name = "base"

    async def before_turn(self, context: ContractContext) -> ContractInterception:
        return ContractInterception()

    async def after_turn(
        self,
        context: ContractContext,
        result: RouterResponse,
    ) -> None:
        return None
