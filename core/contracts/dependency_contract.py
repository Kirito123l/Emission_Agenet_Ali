"""Phase 3 dependency placeholder.

Phase 3 will own slots like meteorology for calculate_dispersion.
See PHASE2_SLOT_ANALYSIS.md §calculate_dispersion for benchmark evidence.
"""

from __future__ import annotations

from core.contracts.base import BaseContract


class DependencyContract(BaseContract):
    name = "dependency"
