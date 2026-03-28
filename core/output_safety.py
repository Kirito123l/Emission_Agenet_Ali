"""User-facing response safety rails."""

from __future__ import annotations

MAX_RESPONSE_CHARS = 8000
DANGEROUS_PATTERNS = [
    "LINESTRING",
    "MULTILINESTRING",
    "POLYGON",
    "matrix_mean",
    "cell_receptor_map",
    "receptor_top_roads",
]


def sanitize_response(text: str) -> str:
    """Strip or truncate likely raw-data dumps from user-facing text."""
    if text is None:
        return ""

    normalized = str(text)
    has_dangerous = any(pattern in normalized for pattern in DANGEROUS_PATTERNS)

    if not has_dangerous and len(normalized) <= MAX_RESPONSE_CHARS:
        return normalized

    if has_dangerous:
        first_hit = min(
            normalized.find(pattern)
            for pattern in DANGEROUS_PATTERNS
            if pattern in normalized
        )
        safe_prefix = normalized[:first_hit].rstrip()
        placeholder = "[... 详细数据已省略，可通过下载文件查看 ...]"
        if not safe_prefix:
            return placeholder
        allowed_prefix = max(0, MAX_RESPONSE_CHARS - len(placeholder) - 1)
        if len(safe_prefix) > allowed_prefix:
            safe_prefix = safe_prefix[:allowed_prefix].rstrip()
        return f"{safe_prefix}\n{placeholder}".strip()

    placeholder = "[... 回复过长，已截断 ...]"
    allowed_prefix = max(0, MAX_RESPONSE_CHARS - len(placeholder) - 1)
    truncated = normalized[:allowed_prefix].rstrip()
    if not truncated:
        return placeholder
    return f"{truncated}\n{placeholder}"
