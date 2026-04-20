from __future__ import annotations

from typing import Any

from core.contracts.base import BaseContract, ContractContext, ContractInterception


class IntentResolutionContract(BaseContract):
    """Wave 2 split contract for tool-intent resolution."""

    name = "intent_resolution"

    def __init__(self, inner_router: Any = None, ao_manager: Any = None, runtime_config: Any = None):
        self.inner_router = inner_router
        self.ao_manager = ao_manager
        self.runtime_config = runtime_config

    async def before_turn(self, context: ContractContext) -> ContractInterception:
        return ContractInterception()
