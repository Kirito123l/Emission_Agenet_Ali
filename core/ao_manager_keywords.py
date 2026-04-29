"""General-purpose multi-step signal patterns for analytical objective detection.

These are language-level patterns (not tool-specific) that indicate a user
may be expressing a multi-step or compound analytical objective.
"""

from __future__ import annotations

MULTI_STEP_SIGNAL_PATTERNS = (
    r"再",
    r"然后",
    r"接着",
    r"之后",
    r"并且",
    r"同时",
    r"做完.*再",
    r"算完.*做",
    r"出.*图",
    r"then",
    r"after that",
    r"and then",
    r"followed by",
)
