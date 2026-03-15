"""Transitional legacy skills package.

Current Phase 1B status:
- Active via tools/: `skills.knowledge.skill` and the micro/macro `excel_handler.py` helpers
- Likely deprecated direct entry points: `skills.*.skill` and `skills.registry`

The active runtime registers `tools/` in `tools.registry`. This package remains
on disk for compatibility while the direct skill interface is audited and slowly
retired.
"""
