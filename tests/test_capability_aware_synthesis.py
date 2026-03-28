from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config import get_config
from core.capability_summary import build_capability_summary, get_capability_aware_follow_up
from core.context_store import SessionContextStore
from core.router import UnifiedRouter
from core.router_render_utils import render_single_tool_success
from tests.test_context_store import make_dispersion_result, make_emission_result


def _make_macro_file_context(*, has_geometry: bool) -> dict:
    payload = {
        "task_type": "macro_emission",
        "confidence": 0.91,
        "columns": ["link_id", "flow", "speed"],
        "column_mapping": {
            "link_id": "link_id",
            "flow": "traffic_flow_vph",
            "speed": "avg_speed_kph",
        },
        "missing_field_diagnostics": {
            "task_type": "macro_emission",
            "status": "complete",
            "required_fields": ["link_id", "traffic_flow_vph", "avg_speed_kph"],
            "missing_fields": [],
        },
    }
    if has_geometry:
        payload["spatial_metadata"] = {
            "crs": "EPSG:4326",
            "bounds": {
                "min_x": 121.4,
                "min_y": 31.2,
                "max_x": 121.6,
                "max_y": 31.4,
            },
        }
    return payload


def _make_macro_result(
    *,
    with_geometry: bool,
    with_download: bool = False,
    with_map: bool = False,
) -> dict:
    result = make_emission_result()
    if not with_geometry:
        for row in result["data"]["results"]:
            row["geometry"] = None
    if with_download:
        result["data"]["download_file"] = {
            "path": "/tmp/emission.xlsx",
            "filename": "emission.xlsx",
        }
    if with_map:
        result["map_data"] = {
            "type": "emission",
            "summary": {"total_links": 2},
            "links": [{"link_id": "L1"}, {"link_id": "L2"}],
        }
    return result


def _make_dispersion_result_no_spatial() -> dict:
    result = make_dispersion_result()
    result["data"].pop("raster_grid", None)
    result.pop("map_data", None)
    return result


def _make_router() -> UnifiedRouter:
    router = object.__new__(UnifiedRouter)
    router.runtime_config = get_config()
    router.context_store = SessionContextStore()
    router.memory = SimpleNamespace(get_fact_memory=lambda: {})
    router.llm = SimpleNamespace(
        chat=AsyncMock(return_value=SimpleNamespace(content="综合结论：已完成结果整理。"))
    )
    return router


def test_build_capability_summary_blocks_spatial_actions_without_geometry():
    store = SessionContextStore()
    result = _make_macro_result(with_geometry=False, with_download=True)
    store.store_result("calculate_macro_emission", result)

    summary = build_capability_summary(
        _make_macro_file_context(has_geometry=False),
        store,
        [{"name": "calculate_macro_emission", "result": result}],
        {"download_file": result["data"]["download_file"]},
    )

    available_labels = {item["label"] for item in summary["available_next_actions"]}
    unavailable = {
        item["label"]: item["reason"] for item in summary["unavailable_actions_with_reasons"]
    }

    assert "可视化排放空间分布" not in available_labels
    assert "模拟污染物扩散浓度" not in available_labels
    assert "可视化排放空间分布" in unavailable
    assert "模拟污染物扩散浓度" in unavailable
    assert "几何信息" in unavailable["可视化排放空间分布"]
    assert any(item["label"] == "结果下载文件" for item in summary["already_provided"])
    assert any("补充路段坐标" in hint for hint in summary["guidance_hints"])


def test_capability_summary_exposes_chart_and_summary_follow_up_surface_without_geometry():
    store = SessionContextStore()
    result = _make_macro_result(with_geometry=False)
    store.store_result("calculate_macro_emission", result)

    summary = build_capability_summary(
        _make_macro_file_context(has_geometry=False),
        store,
        [{"name": "calculate_macro_emission", "result": result}],
        {},
    )
    follow_up = get_capability_aware_follow_up("calculate_macro_emission", summary)

    available_labels = {item["label"] for item in summary["available_next_actions"]}

    assert "查看结果图表" in available_labels
    assert "下载摘要结果文件" in available_labels
    assert "查看结构化摘要" in available_labels
    assert "帮我可视化排放分布" not in "\n".join(follow_up["suggestions"])
    assert any("前5高排放路段" in item for item in follow_up["suggestions"])
    assert any("摘要" in item for item in follow_up["suggestions"])


def test_standard_csv_without_geometry_keeps_spatial_suggestions_out():
    result = _make_macro_result(with_geometry=False, with_download=True)
    file_context = {
        "task_type": "macro_emission",
        "confidence": 0.94,
        "columns": ["segment_id", "highway", "length_km", "daily_traffic", "avg_speed"],
        "column_mapping": {
            "segment_id": "link_id",
            "length_km": "link_length_km",
            "daily_traffic": "traffic_flow_vph",
            "avg_speed": "avg_speed_kph",
        },
        "missing_field_diagnostics": {
            "task_type": "macro_emission",
            "status": "complete",
            "required_fields": ["link_id", "link_length_km", "traffic_flow_vph", "avg_speed_kph"],
            "missing_fields": [],
        },
    }

    summary = build_capability_summary(
        file_context,
        None,
        [{"name": "calculate_macro_emission", "result": result}],
        {"download_file": result["data"]["download_file"]},
    )
    rendered = render_single_tool_success(
        "calculate_macro_emission",
        result,
        capability_summary=summary,
    )

    assert "帮我可视化排放分布" not in rendered
    assert "帮我做扩散分析" not in rendered
    assert "补充路段坐标" in rendered


def test_build_capability_summary_enables_spatial_actions_with_geometry():
    store = SessionContextStore()
    result = _make_macro_result(with_geometry=True)
    store.store_result("calculate_macro_emission", result)

    summary = build_capability_summary(
        _make_macro_file_context(has_geometry=True),
        store,
        [{"name": "calculate_macro_emission", "result": result}],
        {},
    )

    available_labels = {item["label"] for item in summary["available_next_actions"]}
    assert "可视化排放空间分布" in available_labels
    assert "模拟污染物扩散浓度" in available_labels


def test_build_capability_summary_suppresses_redundant_map_action_when_map_already_provided():
    store = SessionContextStore()
    result = _make_macro_result(with_geometry=True, with_map=True)
    store.store_result("calculate_macro_emission", result)

    summary = build_capability_summary(
        _make_macro_file_context(has_geometry=True),
        store,
        [{"name": "calculate_macro_emission", "result": result}],
        {"map_data": result["map_data"]},
    )

    available_labels = {item["label"] for item in summary["available_next_actions"]}
    assert "可视化排放空间分布" not in available_labels
    assert "模拟污染物扩散浓度" in available_labels
    assert any(item["kind"] == "map:emission" for item in summary["already_provided"])


def test_build_capability_summary_after_dispersion_supports_hotspots_but_blocks_render_without_spatial():
    store = SessionContextStore()
    emission = _make_macro_result(with_geometry=True)
    dispersion = _make_dispersion_result_no_spatial()
    store.store_result("calculate_macro_emission", emission)
    store.store_result("calculate_dispersion", dispersion)

    summary = build_capability_summary(
        _make_macro_file_context(has_geometry=True),
        store,
        [{"name": "calculate_dispersion", "result": dispersion}],
        {},
    )

    available_labels = {item["label"] for item in summary["available_next_actions"]}
    unavailable = {
        item["label"]: item["reason"] for item in summary["unavailable_actions_with_reasons"]
    }

    assert "识别污染热点" in available_labels
    assert "可视化扩散浓度分布" not in available_labels
    assert "可视化扩散浓度分布" in unavailable
    assert "空间数据" in unavailable["可视化扩散浓度分布"]


def test_render_single_tool_success_filters_follow_up_with_capability_summary():
    result = _make_macro_result(with_geometry=False, with_download=True)
    summary = build_capability_summary(
        _make_macro_file_context(has_geometry=False),
        None,
        [{"name": "calculate_macro_emission", "result": result}],
        {"download_file": result["data"]["download_file"]},
    )

    rendered = render_single_tool_success(
        "calculate_macro_emission",
        result,
        capability_summary=summary,
    )

    assert "帮我可视化排放分布" not in rendered
    assert "帮我做扩散分析" not in rendered
    assert "补充路段坐标" in rendered


def test_router_build_capability_summary_logs_summary_payload(caplog):
    router = _make_router()
    file_context = _make_macro_file_context(has_geometry=False)
    router.memory = SimpleNamespace(get_fact_memory=lambda: {"file_analysis": file_context})
    result = _make_macro_result(with_geometry=False, with_download=True)
    router.context_store.store_result("calculate_macro_emission", result)

    with caplog.at_level("INFO"):
        summary = router._build_capability_summary_for_synthesis(
            [{"name": "calculate_macro_emission", "result": result}],
            frontend_payloads={"download_file": result["data"]["download_file"]},
        )

    assert summary is not None
    assert "可视化排放空间分布" in str(summary["unavailable_actions_with_reasons"])
    assert "[CapabilityAwareSynthesis]" in caplog.text
    assert "summary=" in caplog.text


@pytest.mark.anyio
async def test_synthesize_results_injects_capability_constraints_into_prompt():
    router = _make_router()
    store = router.context_store
    result = _make_macro_result(with_geometry=False, with_download=True)
    store.store_result("calculate_macro_emission", result)
    capability_summary = build_capability_summary(
        _make_macro_file_context(has_geometry=False),
        store,
        [{"name": "calculate_macro_emission", "result": result}],
        {"download_file": result["data"]["download_file"]},
    )
    context = SimpleNamespace(messages=[{"role": "user", "content": "请总结这些结果"}])
    tool_results = [
        {
            "name": "calculate_macro_emission",
            "result": result,
        },
        {
            "name": "analyze_file",
            "result": {
                "success": True,
                "data": {
                    "task_type": "macro_emission",
                    "columns": ["link_id", "flow", "speed"],
                    "row_count": 3,
                },
            },
        },
    ]

    synthesized = await router._synthesize_results(
        context,
        None,
        tool_results,
        capability_summary=capability_summary,
    )

    assert synthesized == "综合结论：已完成结果整理。"
    llm_kwargs = router.llm.chat.await_args.kwargs
    assert "后续建议硬约束" in llm_kwargs["system"]
    assert "严禁将这些列为推荐选项" in llm_kwargs["system"]
    assert "最终硬性要求" in llm_kwargs["system"]
    assert "可视化排放空间分布" in llm_kwargs["system"]
    assert "模拟污染物扩散浓度" in llm_kwargs["system"]
    assert "结果下载文件" in llm_kwargs["system"]
    assert llm_kwargs["system"].strip().endswith(
        "如果当前没有安全的后续操作，就明确说“当前没有额外的安全后续操作建议”。"
    )
