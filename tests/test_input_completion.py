from __future__ import annotations

import pandas as pd

from core.input_completion import (
    InputCompletionDecisionType,
    InputCompletionOption,
    InputCompletionOptionType,
    InputCompletionReasonCode,
    InputCompletionRequest,
    format_input_completion_prompt,
    parse_input_completion_reply,
)
from skills.macro_emission.excel_handler import ExcelHandler


def _missing_flow_request() -> InputCompletionRequest:
    return InputCompletionRequest.create(
        action_id="run_macro_emission",
        reason_code=InputCompletionReasonCode.MISSING_REQUIRED_FIELD,
        reason_summary="当前缺少 traffic_flow_vph。",
        missing_requirements=["traffic_flow_vph"],
        target_field="traffic_flow_vph",
        current_task_type="macro_emission",
        options=[
            InputCompletionOption(
                option_id="traffic_flow_vph_uniform_value",
                option_type=InputCompletionOptionType.PROVIDE_UNIFORM_VALUE,
                label="统一流量值",
                description="为所有路段设置统一流量值。",
                requirements={"field": "traffic_flow_vph"},
            ),
            InputCompletionOption(
                option_id="traffic_flow_vph_upload_file",
                option_type=InputCompletionOptionType.UPLOAD_SUPPORTING_FILE,
                label="上传补充文件",
                description="上传包含流量字段的新文件。",
                requirements={"field": "traffic_flow_vph"},
            ),
            InputCompletionOption(
                option_id="traffic_flow_vph_pause",
                option_type=InputCompletionOptionType.PAUSE,
                label="暂停",
                description="先不补这个字段。",
            ),
        ],
    )


def _missing_geometry_request() -> InputCompletionRequest:
    return InputCompletionRequest.create(
        action_id="render_emission_map",
        reason_code=InputCompletionReasonCode.MISSING_GEOMETRY,
        reason_summary="当前没有 geometry。",
        missing_requirements=["geometry"],
        target_field="geometry",
        current_task_type="macro_emission",
        options=[
            InputCompletionOption(
                option_id="geometry_upload_file",
                option_type=InputCompletionOptionType.UPLOAD_SUPPORTING_FILE,
                label="上传空间文件",
                description="上传 GIS / GeoJSON / Shapefile。",
            ),
            InputCompletionOption(
                option_id="geometry_pause",
                option_type=InputCompletionOptionType.PAUSE,
                label="暂停",
                description="稍后再补空间数据。",
            ),
        ],
    )


def test_uniform_scalar_completion_success():
    request = _missing_flow_request()

    result = parse_input_completion_reply(request, "全部设为1500")

    assert result.is_resolved is True
    assert result.decision is not None
    assert result.decision.decision_type == InputCompletionDecisionType.SELECTED_OPTION
    assert result.decision.selected_option_id == "traffic_flow_vph_uniform_value"
    assert result.decision.structured_payload["value"] == 1500.0


def test_ambiguous_reply_retry():
    request = _missing_flow_request()

    result = parse_input_completion_reply(request, "默认就好")

    assert result.is_resolved is False
    assert result.needs_retry is True
    assert "numeric value" in (result.error_message or "")


def test_pause_reply():
    request = _missing_flow_request()

    result = parse_input_completion_reply(request, "暂停")

    assert result.is_resolved is True
    assert result.decision is not None
    assert result.decision.decision_type == InputCompletionDecisionType.PAUSE


def test_missing_geometry_upload_request_parses_with_supporting_file():
    request = _missing_geometry_request()

    result = parse_input_completion_reply(
        request,
        "上传文件",
        supporting_file_path="/tmp/roads.geojson",
    )

    assert result.is_resolved is True
    assert result.decision is not None
    assert result.decision.selected_option_id == "geometry_upload_file"
    assert result.decision.structured_payload["file_ref"] == "/tmp/roads.geojson"


def test_prompt_mentions_numeric_reply_format():
    prompt = format_input_completion_prompt(_missing_flow_request())

    assert "1500" in prompt
    assert "暂停" in prompt


def test_excel_handler_accepts_uniform_scalar_override_for_missing_required_field(tmp_path):
    csv_path = tmp_path / "roads.csv"
    df = pd.DataFrame(
        {
            "segment_id": ["L1", "L2"],
            "length_km": [1.2, 0.8],
            "avg_speed": [45.0, 50.0],
        }
    )
    df.to_csv(csv_path, index=False)

    handler = ExcelHandler(llm_client=None)
    success, links_data, error = handler.read_links_from_excel(
        str(csv_path),
        completion_overrides={
            "traffic_flow_vph": {
                "mode": "uniform_scalar",
                "value": 1500,
                "source": "input_completion",
            }
        },
    )

    assert success is True
    assert error is None
    assert links_data is not None
    assert links_data[0]["traffic_flow_vph"] == 1500.0
    assert links_data[1]["traffic_flow_vph"] == 1500.0
