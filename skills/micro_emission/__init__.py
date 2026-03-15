"""Legacy direct micro-emission skill package retained for compatibility.

The active runtime uses `tools.micro_emission`. This package remains because its
Excel handler is still imported by the active tool path.
"""
from .skill import MicroEmissionSkill

__all__ = ["MicroEmissionSkill"]
