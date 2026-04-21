from __future__ import annotations


REVERSAL_MARKERS = (
    "等等",
    "先确认",
    "换成",
    "改成",
    "先别",
    "不做了",
    "不用了",
    "还是",
    "要不",
)

PROBE_ABANDON_MARKERS = (
    "先算吧",
    "直接算吧",
    "别问了",
    "不用再问",
    "先跑吧",
    "直接继续",
)


def has_reversal_marker(message: str) -> bool:
    text = str(message or "").strip().lower()
    if not text:
        return False
    return any(marker in text for marker in REVERSAL_MARKERS)


def has_probe_abandon_marker(message: str) -> bool:
    text = str(message or "").strip().lower()
    if not text:
        return False
    return any(marker in text for marker in PROBE_ABANDON_MARKERS)

