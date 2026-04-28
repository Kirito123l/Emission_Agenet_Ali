"""Unit tests for Layer 1 fast path in input_completion (A.3)."""

from __future__ import annotations

import pytest

from core.input_completion import (
    InputCompletionDecisionType,
    InputCompletionOption,
    InputCompletionOptionType,
    InputCompletionReasonCode,
    InputCompletionRequest,
    _try_fast_path,
)


def _make_request(**kwargs):
    return InputCompletionRequest(
        request_id=kwargs.get("request_id", "ic-fastpath"),
        action_id=kwargs.get("action_id", "run_macro_emission"),
        reason_code=kwargs.get("reason_code", InputCompletionReasonCode.MISSING_REQUIRED_FIELD),
        reason_summary=kwargs.get("reason_summary", "need traffic_flow_vph"),
        missing_requirements=kwargs.get("missing_requirements", ["traffic_flow_vph"]),
        target_field=kwargs.get("target_field", "traffic_flow_vph"),
        options=kwargs.get("options", [
            InputCompletionOption(
                option_id="flow_uniform",
                option_type=InputCompletionOptionType.PROVIDE_UNIFORM_VALUE,
                label="统一流量值",
                description="为所有路段设置统一流量值",
            ),
            InputCompletionOption(
                option_id="flow_upload",
                option_type=InputCompletionOptionType.UPLOAD_SUPPORTING_FILE,
                label="上传补充文件",
                description="上传含流量字段的文件",
            ),
            InputCompletionOption(
                option_id="flow_pause",
                option_type=InputCompletionOptionType.PAUSE,
                label="暂停",
                description="先不补",
            ),
        ]),
    )


def _make_single_option_request():
    return InputCompletionRequest(
        request_id="ic-single",
        action_id="run_render",
        reason_code=InputCompletionReasonCode.MISSING_GEOMETRY,
        reason_summary="no geometry",
        target_field="geometry",
        options=[
            InputCompletionOption(
                option_id="geo_upload",
                option_type=InputCompletionOptionType.UPLOAD_SUPPORTING_FILE,
                label="上传空间文件",
                description="上传 GIS/GeoJSON",
            ),
        ],
    )


def test_fast_path_digit_selects_option():
    r = _make_request()
    result = _try_fast_path("1", r)
    assert result is not None
    # PROVIDE_UNIFORM_VALUE → retry (option selected but no value given)
    assert result.is_resolved is False
    assert result.needs_retry is True


def test_fast_path_digit_out_of_range_returns_none():
    r = _make_request()
    result = _try_fast_path("5", r)
    assert result is None


def test_fast_path_pause_word():
    r = _make_request()
    result = _try_fast_path("暂停", r)
    assert result is not None
    assert result.is_resolved is True
    assert result.decision.decision_type == InputCompletionDecisionType.PAUSE


def test_fast_path_pause_word_english_too_long():
    """'pause' is 5 chars — exceeds fast-path length guard.
    It's handled by legacy regex (_PAUSE_PHRASES) instead."""
    r = _make_request()
    result = _try_fast_path("pause", r)
    assert result is None  # >3 chars, delegates to legacy regex


def test_fast_path_long_reply_skips():
    r = _make_request()
    result = _try_fast_path("我选第一个", r)
    assert result is None


def test_fast_path_empty_reply():
    r = _make_request()
    result = _try_fast_path("", r)
    assert result is None


def test_fast_path_upload_option_selected_by_digit():
    """Digit '2' selects upload option → needs file."""
    r = _make_request()
    result = _try_fast_path("2", r)
    assert result is not None
    assert result.is_resolved is False  # UPLOAD without supporting_file → retry


def test_fast_path_non_digit_no_match():
    r = _make_request()
    result = _try_fast_path("abc", r)
    assert result is None

