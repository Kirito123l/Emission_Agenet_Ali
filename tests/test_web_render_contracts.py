"""Lightweight source-level contracts for frontend rendering paths."""

from __future__ import annotations

import re
from pathlib import Path


APP_JS = Path(__file__).resolve().parents[1] / "web" / "app.js"
APP_SOURCE = APP_JS.read_text(encoding="utf-8")


def _extract_function_body(function_name: str) -> str:
    pattern = re.compile(rf"function {function_name}\([^)]*\) \{{(.*?)\n\}}", re.S)
    match = pattern.search(APP_SOURCE)
    assert match, f"Function {function_name} not found"
    return match.group(1)


def test_add_assistant_message_renders_table_when_table_payload_exists():
    assert re.search(
        r"const hasValidTableData =\s*data\.table_data\s*&&\s*typeof data\.table_data === 'object'\s*&&\s*Object\.keys\(data\.table_data\)\.length > 0",
        APP_SOURCE,
        re.S,
    )


def test_streaming_message_container_uses_stacking_classes():
    body = _extract_function_body("createAssistantMessageContainer")

    assert "assistant-message-row" in body
    assert "assistant-message-card" in body
    assert "ensureLeafletStackingStyles();" in body


def test_ranked_bar_chart_payload_has_render_and_init_dispatch():
    render_body = _extract_function_body("renderChartCard")
    init_body = _extract_function_body("initChartPayload")

    assert "chartData?.type === 'ranked_bar_chart'" in render_body
    assert "return renderRankedBarChart(chartData, chartId);" in render_body
    assert "chartData?.type === 'ranked_bar_chart'" in init_body
    assert "initRankedBarChart(chartData, chartId);" in init_body
