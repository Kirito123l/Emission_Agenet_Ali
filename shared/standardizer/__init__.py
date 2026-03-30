"""Deprecated legacy standardizer package.

DEPRECATED: This module is superseded by services/standardizer.py and
services/standardization_engine.py.
Only shared/standardizer/local_client.py is still actively used via lazy import
compatibility paths.
All other files in this directory are legacy code retained for reference only.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "shared.standardizer is deprecated. Use services.standardizer instead.",
    DeprecationWarning,
    stacklevel=2,
)
