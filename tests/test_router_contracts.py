"""Thin contract coverage for router payload/result shaping helpers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.router import SYNTHESIS_PROMPT, UnifiedRouter
from core.router_memory_utils import build_memory_tool_calls, compact_tool_data
from core.router_payload_utils import (
    extract_chart_data,
    extract_download_file,
    extract_map_data,
    extract_table_data,
    format_emission_factors_chart,
)
from core.router_render_utils import (
    filter_results_for_synthesis,
    format_results_as_fallback,
    format_tool_errors,
    format_tool_results,
    render_single_tool_success,
)
from core.router_synthesis_utils import (
    build_synthesis_request,
    detect_hallucination_keywords,
    maybe_short_circuit_synthesis,
)


def make_router() -> UnifiedRouter:
    """Build a router instance without running the live LLM/executor setup."""
    return object.__new__(UnifiedRouter)


def test_build_memory_tool_calls_compacts_large_payloads_for_follow_up_turns():
    router = make_router()
    tool_results = [
        {
            "name": "calculate_micro_emission",
            "arguments": {"vehicle_type": "Passenger Car"},
            "result": {
                "success": True,
                "summary": "计算完成",
                "data": {
                    "query_info": {"vehicle_type": "Passenger Car"},
                    "summary": {"total_emissions_g": {"CO2": 12.3}},
                    "download_file": {"path": "/tmp/output.xlsx", "filename": "output.xlsx"},
                    "columns": [f"col_{i}" for i in range(25)],
                    "results": [{"t": 0, "speed_kph": 10.0}],
                    "speed_curve": [{"speed_kph": 10.0, "emission_rate": 1.0}],
                    "pollutants": {"CO2": {"curve": [1, 2, 3]}},
                    "row_count": 12,
                    "note": "keep me",
                    "extra_nested": {"skip": True},
                },
            },
        },
        {
            "name": "query_knowledge",
            "arguments": {"query": "NOx"},
            "result": {
                "success": False,
                "summary": None,
                "data": ["raw", "list"],
            },
        },
    ]

    compact_calls = router._build_memory_tool_calls(tool_results)

    assert compact_calls[0]["name"] == "calculate_micro_emission"
    assert compact_calls[0]["arguments"] == {"vehicle_type": "Passenger Car"}
    assert compact_calls[0]["result"]["success"] is True
    assert compact_calls[0]["result"]["summary"] == "计算完成"
    assert compact_calls[0]["result"]["data"]["query_info"] == {"vehicle_type": "Passenger Car"}
    assert compact_calls[0]["result"]["data"]["summary"] == {"total_emissions_g": {"CO2": 12.3}}
    assert compact_calls[0]["result"]["data"]["download_file"] == {
        "path": "/tmp/output.xlsx",
        "filename": "output.xlsx",
    }
    assert compact_calls[0]["result"]["data"]["row_count"] == 12
    assert compact_calls[0]["result"]["data"]["note"] == "keep me"
    assert len(compact_calls[0]["result"]["data"]["columns"]) == 20
    assert "results" not in compact_calls[0]["result"]["data"]
    assert "speed_curve" not in compact_calls[0]["result"]["data"]
    assert "pollutants" not in compact_calls[0]["result"]["data"]
    assert "extra_nested" not in compact_calls[0]["result"]["data"]

    assert compact_calls[1]["result"]["success"] is False
    assert compact_calls[1]["result"]["data"] is None


def test_router_memory_utils_match_core_router_compatibility_wrappers():
    router = make_router()
    data = {
        "summary": {"total_emissions_g": {"CO2": 1.2}},
        "columns": [f"col_{i}" for i in range(22)],
        "results": [{"speed_kph": 10.0}],
        "note": "kept",
    }
    tool_results = [
        {
            "name": "calculate_micro_emission",
            "arguments": {"vehicle_type": "Passenger Car"},
            "result": {
                "success": True,
                "summary": "计算完成",
                "data": data,
            },
        }
    ]

    assert compact_tool_data(data) == router._compact_tool_data(data)
    assert build_memory_tool_calls(tool_results) == router._build_memory_tool_calls(tool_results)


def test_router_payload_utils_match_core_router_compatibility_wrappers():
    router = make_router()
    emission_factor_data = {
        "vehicle_type": "Passenger Car",
        "model_year": 2022,
        "pollutants": {"CO2": {"speed_curve": [{"speed_kph": 30.0, "emission_rate": 1.2}]}},
        "metadata": {"season": "summer"},
    }
    tool_results = [
        {
            "name": "query_emission_factors",
            "result": {
                "success": True,
                "data": emission_factor_data,
            },
        },
        {
            "name": "calculate_macro_emission",
            "result": {
                "download_file": "/tmp/result.xlsx",
                "map_data": {"links": [{"id": "L1"}]},
            },
        },
    ]
    table_tool_results = [
        {
            "name": "calculate_micro_emission",
            "result": {
                "success": True,
                "data": {
                    "summary": {"total_emissions_g": {"CO2": 1.2}},
                    "results": [
                        {
                            "t": 0,
                            "speed_kph": 12.3,
                            "emissions": {"CO2": 0.1234},
                        }
                    ],
                },
            },
        }
    ]

    assert format_emission_factors_chart(emission_factor_data) == router._format_emission_factors_chart(emission_factor_data)
    assert extract_chart_data(tool_results) == router._extract_chart_data(tool_results)
    assert extract_table_data(table_tool_results) == router._extract_table_data(table_tool_results)
    assert extract_download_file(tool_results) == router._extract_download_file(tool_results)
    assert extract_map_data(tool_results) == router._extract_map_data(tool_results)


def test_router_render_utils_match_core_router_compatibility_wrappers():
    router = make_router()
    result = {
        "summary": "分析完成",
        "data": {
            "filename": "sample.csv",
            "row_count": 3,
            "columns": ["t", "speed_kph"],
            "task_type": "micro_emission",
            "confidence": 0.95,
        },
    }
    tool_results = [
        {
            "name": "calculate_micro_emission",
            "result": {
                "success": True,
                "summary": "微观计算完成",
                "data": {
                    "summary": {"total_emissions_g": {"CO2": 1.2}},
                    "results": [{"t": 0}],
                },
            },
        },
        {
            "name": "query_knowledge",
            "result": {
                "success": False,
                "error": "missing index",
                "message": "missing index",
                "suggestions": ["rebuild knowledge index"],
            },
        },
    ]

    assert render_single_tool_success("analyze_file", result) == router._render_single_tool_success("analyze_file", result)
    assert filter_results_for_synthesis(tool_results) == router._filter_results_for_synthesis(tool_results)
    assert format_tool_errors(tool_results) == router._format_tool_errors(tool_results)
    assert format_tool_results(tool_results) == router._format_tool_results(tool_results)
    assert format_results_as_fallback(tool_results) == router._format_results_as_fallback(tool_results)


def test_router_synthesis_utils_match_core_router_compatibility_wrappers():
    router = make_router()
    tool_results = [
        {
            "name": "query_knowledge",
            "result": {
                "success": True,
                "summary": "知识答案",
            },
        }
    ]
    keywords = ["峰值出现在", "空调导致"]

    assert maybe_short_circuit_synthesis(tool_results) == router._maybe_short_circuit_synthesis(tool_results)
    assert build_synthesis_request("请总结结果", tool_results, SYNTHESIS_PROMPT) == router._build_synthesis_request(
        "请总结结果",
        tool_results,
    )
    assert detect_hallucination_keywords("峰值出现在 这里", keywords) == router._detect_synthesis_hallucination_keywords(
        "峰值出现在 这里",
        keywords,
    )


def test_maybe_short_circuit_synthesis_covers_knowledge_failure_and_single_tool_paths():
    knowledge_tool_results = [
        {
            "name": "query_knowledge",
            "result": {
                "success": True,
                "summary": "知识答案",
            },
        }
    ]
    failure_tool_results = [
        {
            "name": "calculate_macro_emission",
            "result": {
                "success": False,
                "message": "bad file",
                "suggestions": ["检查输入文件"],
            },
        }
    ]
    summary_tool_results = [
        {
            "name": "query_knowledge",
            "result": {
                "success": True,
                "summary": "普通摘要",
            },
        }
    ]

    assert maybe_short_circuit_synthesis(knowledge_tool_results) == "知识答案"
    assert maybe_short_circuit_synthesis(failure_tool_results).startswith("## 工具执行结果")
    assert maybe_short_circuit_synthesis(summary_tool_results) == "普通摘要"


def test_build_synthesis_request_and_keyword_detection_preserve_llm_input_contract():
    tool_results = [
        {
            "name": "calculate_macro_emission",
            "result": {
                "success": True,
                "summary": "宏观计算完成",
                "data": {
                    "vehicle_type": "Passenger Car",
                    "pollutants": ["CO2"],
                    "model_year": 2022,
                    "season": "summer",
                    "download_file": "/tmp/out.xlsx",
                    "summary": {
                        "total_emissions": {"CO2": 12.3},
                        "total_distance_km": 8.8,
                        "total_time_s": 500,
                    },
                    "results": [{"link_id": "L1"}],
                },
            },
        }
    ]

    request = build_synthesis_request("请总结结果", tool_results, "工具执行结果:\n{results}")
    detected = detect_hallucination_keywords(
        "这里说峰值出现在城区，而且空调导致排放增加",
        ["峰值出现在", "空调导致", "不完全燃烧"],
    )

    assert request["messages"] == [{"role": "user", "content": "请总结结果"}]
    assert request["system_prompt"].startswith("工具执行结果:\n{")
    assert request["filtered_results"] == {
        "calculate_macro_emission": {
            "success": True,
            "summary": "宏观计算完成",
            "num_points": 1,
            "total_emissions": {"CO2": 12.3},
            "total_distance_km": 8.8,
            "total_time_s": 500,
            "query_params": {
                "vehicle_type": "Passenger Car",
                "pollutants": ["CO2"],
                "model_year": 2022,
                "season": "summer",
            },
            "has_download_file": True,
        }
    }
    assert '"calculate_macro_emission"' in request["results_json"]
    assert detected == ["峰值出现在", "空调导致"]


def test_render_single_tool_success_formats_micro_results_with_key_sections():
    router = make_router()
    result = {
        "data": {
            "query_info": {
                "vehicle_type": "Passenger Car",
                "model_year": 2022,
                "season": "summer",
                "pollutants": ["CO2", "NOx"],
                "trajectory_points": 120,
            },
            "summary": {
                "total_distance_km": 1.234,
                "total_time_s": 90,
                "total_emissions_g": {"CO2": 12.3456, "NOx": 0.7891},
                "emission_rates_g_per_km": {"CO2": 10.0044},
            },
        }
    }

    rendered = router._render_single_tool_success("calculate_micro_emission", result)

    assert rendered.startswith("## 微观排放计算结果")
    assert "- 车型: Passenger Car" in rendered
    assert "- 年份: 2022" in rendered
    assert "- 污染物: CO2, NOx" in rendered
    assert "- 轨迹点数: 120" in rendered
    assert "- 总距离: 1.234 km" in rendered
    assert "- 总时间: 90 s" in rendered
    assert "  - CO2: 12.3456 g" in rendered
    assert "  - NOx: 0.7891 g" in rendered
    assert "  - CO2: 10.0044 g/km" in rendered


def test_filter_results_and_error_formatting_keep_retry_and_synthesis_signal():
    router = make_router()
    tool_results = [
        {
            "name": "calculate_macro_emission",
            "result": {
                "success": True,
                "summary": "宏观计算完成",
                "data": {
                    "vehicle_type": "Passenger Car",
                    "pollutants": ["CO2"],
                    "model_year": 2021,
                    "season": "winter",
                    "download_file": "/tmp/macro.xlsx",
                    "summary": {
                        "total_emissions": {"CO2": 23.4},
                        "total_distance_km": 8.9,
                        "total_time_s": 600,
                    },
                    "results": [{"link_id": "L1"}, {"link_id": "L2"}],
                },
            },
        },
        {
            "name": "query_knowledge",
            "result": {
                "success": False,
                "error": "retriever unavailable",
                "message": "retriever unavailable",
                "suggestions": ["检查索引状态", "稍后重试"],
            },
        },
    ]

    filtered = router._filter_results_for_synthesis(tool_results)
    errors = router._format_tool_errors(tool_results)
    summaries = router._format_tool_results(tool_results)

    assert filtered == {
        "calculate_macro_emission": {
            "success": True,
            "summary": "宏观计算完成",
            "num_points": 2,
            "total_emissions": {"CO2": 23.4},
            "total_distance_km": 8.9,
            "total_time_s": 600,
            "query_params": {
                "vehicle_type": "Passenger Car",
                "pollutants": ["CO2"],
                "model_year": 2021,
                "season": "winter",
            },
            "has_download_file": True,
        },
        "query_knowledge": {
            "success": False,
            "error": "retriever unavailable",
        },
    }
    assert errors == "[query_knowledge] Error: retriever unavailable\nSuggestions: 检查索引状态, 稍后重试"
    assert summaries == "[calculate_macro_emission] 宏观计算完成\n[query_knowledge] Error: retriever unavailable"


def test_extract_chart_data_prefers_explicit_chart_payload():
    router = make_router()
    explicit_chart = {"type": "provided_by_tool", "series": [1, 2, 3]}

    chart = router._extract_chart_data(
        [
            {
                "name": "query_emission_factors",
                "result": {
                    "success": True,
                    "chart_data": explicit_chart,
                    "data": {"pollutants": {"CO2": {"speed_curve": []}}},
                },
            }
        ]
    )

    assert chart is explicit_chart


def test_extract_chart_data_formats_emission_factor_curves_for_frontend():
    router = make_router()
    tool_results = [
        {
            "name": "query_emission_factors",
            "result": {
                "success": True,
                "data": {
                    "vehicle_type": "Passenger Car",
                    "model_year": 2022,
                    "metadata": {"season": "summer", "road_type": "urban"},
                    "pollutants": {
                        "CO2": {
                            "speed_curve": [
                                {"speed_kph": 30.0, "emission_rate": 1.2},
                                {"speed_kph": 60.0, "emission_rate": 2.4},
                            ],
                            "unit": "g/km",
                        },
                        "NOx": {
                            "curve": [
                                {"speed_kph": 30.0, "emission_rate": 0.2},
                                {"speed_kph": 60.0, "emission_rate": 0.4},
                            ],
                            "unit": "g/km",
                        },
                    },
                },
            },
        }
    ]

    chart = router._extract_chart_data(tool_results)

    assert chart["type"] == "emission_factors"
    assert chart["vehicle_type"] == "Passenger Car"
    assert chart["model_year"] == 2022
    assert chart["metadata"] == {"season": "summer", "road_type": "urban"}
    assert chart["pollutants"]["CO2"] == {
        "curve": [
            {"speed_kph": 30.0, "emission_rate": 1.2},
            {"speed_kph": 60.0, "emission_rate": 2.4},
        ],
        "unit": "g/km",
    }
    assert chart["pollutants"]["NOx"] == {
        "curve": [
            {"speed_kph": 30.0, "emission_rate": 0.2},
            {"speed_kph": 60.0, "emission_rate": 0.4},
        ],
        "unit": "g/km",
    }


def test_extract_table_data_formats_macro_results_preview_for_frontend():
    router = make_router()
    tool_results = [
        {
            "name": "calculate_macro_emission",
            "result": {
                "success": True,
                "data": {
                    "query_info": {"pollutants": ["CO2", "NOx"]},
                    "summary": {"total_emissions": {"CO2": 12.34, "NOx": 0.7}},
                    "results": [
                        {
                            "link_id": "L1",
                            "total_emissions_kg_per_hr": {"CO2": 12.345, "NOx": 0.7},
                            "emission_rates_g_per_veh_km": {"CO2": 1.23, "NOx": 0.09},
                        },
                        {
                            "link_id": "L2",
                            "total_emissions_kg_per_hr": {"CO2": 23.456, "NOx": 0.8},
                            "emission_rates_g_per_veh_km": {"CO2": 2.34, "NOx": 0.1},
                        },
                    ],
                },
            },
        }
    ]

    table = router._extract_table_data(tool_results)

    assert table["type"] == "calculate_macro_emission"
    assert table["columns"] == ["link_id", "CO2_kg_h", "CO2_g_veh_km", "NOx_kg_h"]
    assert table["preview_rows"] == [
        {
            "link_id": "L1",
            "CO2_kg_h": "12.35",
            "CO2_g_veh_km": "1.23",
            "NOx_kg_h": "0.70",
        },
        {
            "link_id": "L2",
            "CO2_kg_h": "23.46",
            "CO2_g_veh_km": "2.34",
            "NOx_kg_h": "0.80",
        },
    ]
    assert table["total_rows"] == 2
    assert table["total_columns"] == 4
    assert table["total_emissions"] == {"CO2": 12.34, "NOx": 0.7}


def test_extract_table_data_formats_emission_factor_preview_for_frontend():
    router = make_router()
    tool_results = [
        {
            "name": "query_emission_factors",
            "result": {
                "success": True,
                "data": {
                    "vehicle_type": "Passenger Car",
                    "model_year": 2022,
                    "metadata": {"season": "summer", "road_type": "urban"},
                    "pollutants": {
                        "CO2": {
                            "speed_curve": [
                                {"speed_kph": 10.0, "emission_rate": 1.1111},
                                {"speed_kph": 20.0, "emission_rate": 2.2222},
                                {"speed_kph": 30.0, "emission_rate": 3.3333},
                                {"speed_kph": 40.0, "emission_rate": 4.4444},
                            ]
                        },
                        "NOx": {
                            "speed_curve": [
                                {"speed_kph": 10.0, "emission_rate": 0.1111},
                                {"speed_kph": 20.0, "emission_rate": 0.2222},
                                {"speed_kph": 30.0, "emission_rate": 0.3333},
                                {"speed_kph": 40.0, "emission_rate": 0.4444},
                            ]
                        },
                    },
                },
            },
        }
    ]

    table = router._extract_table_data(tool_results)

    assert table["type"] == "query_emission_factors"
    assert table["columns"] == ["速度 (km/h)", "CO2 (g/km)", "NOx (g/km)"]
    assert table["preview_rows"] == [
        {"速度 (km/h)": "10.0", "CO2 (g/km)": "1.1111", "NOx (g/km)": "0.1111"},
        {"速度 (km/h)": "20.0", "CO2 (g/km)": "2.2222", "NOx (g/km)": "0.2222"},
        {"速度 (km/h)": "30.0", "CO2 (g/km)": "3.3333", "NOx (g/km)": "0.3333"},
        {"速度 (km/h)": "40.0", "CO2 (g/km)": "4.4444", "NOx (g/km)": "0.4444"},
    ]
    assert table["total_rows"] == 4
    assert table["total_columns"] == 3
    assert table["summary"] == {
        "vehicle_type": "Passenger Car",
        "model_year": 2022,
        "season": "summer",
        "road_type": "urban",
    }


def test_extract_table_data_formats_micro_results_preview_for_frontend():
    router = make_router()
    tool_results = [
        {
            "name": "calculate_micro_emission",
            "result": {
                "success": True,
                "data": {
                    "summary": {"total_emissions_g": {"CO2": 12.34, "NOx": 0.56}},
                    "results": [
                        {
                            "t": 0,
                            "speed_kph": 12.345,
                            "acceleration_mps2": 0.456,
                            "vsp": 1.234,
                            "emissions": {"CO2": 0.12345, "NOx": 0.00678},
                        },
                        {
                            "t": 1,
                            "speed_kph": 23.456,
                            "acceleration_mps2": -0.5,
                            "vsp": -1.0,
                            "emissions": {"CO2": 0.98765, "NOx": 0.00432},
                        },
                    ],
                },
            },
        }
    ]

    table = router._extract_table_data(tool_results)

    assert table["type"] == "calculate_micro_emission"
    assert table["columns"] == ["t", "speed_kph", "acceleration_mps2", "VSP", "CO2", "NOx"]
    assert table["preview_rows"] == [
        {
            "t": 0,
            "speed_kph": "12.3",
            "acceleration_mps2": "0.46",
            "VSP": "1.23",
            "CO2": "0.1235",
            "NOx": "0.0068",
        },
        {
            "t": 1,
            "speed_kph": "23.5",
            "acceleration_mps2": "-0.50",
            "VSP": "-1.00",
            "CO2": "0.9877",
            "NOx": "0.0043",
        },
    ]
    assert table["total_rows"] == 2
    assert table["total_columns"] == 6
    assert table["summary"] == {"total_emissions_g": {"CO2": 12.34, "NOx": 0.56}}
    assert table["total_emissions"] == {"CO2": 12.34, "NOx": 0.56}


def test_extract_download_and_map_payloads_support_current_and_legacy_locations():
    router = make_router()

    current_download = router._extract_download_file(
        [{"name": "calculate_macro_emission", "result": {"download_file": "/tmp/result.xlsx"}}]
    )
    legacy_download = router._extract_download_file(
        [
            {
                "name": "calculate_macro_emission",
                "result": {
                    "metadata": {
                        "download_file": {"path": "/tmp/legacy.xlsx", "filename": "legacy.xlsx"}
                    }
                },
            }
        ]
    )
    current_map = router._extract_map_data(
        [{"name": "calculate_macro_emission", "result": {"map_data": {"links": [{"id": "L1"}]}}}]
    )
    nested_map = router._extract_map_data(
        [
            {
                "name": "calculate_macro_emission",
                "result": {"data": {"map_data": {"links": [{"id": "L2"}]}}},
            }
        ]
    )

    assert current_download == {"path": "/tmp/result.xlsx", "filename": "result.xlsx"}
    assert legacy_download == {"path": "/tmp/legacy.xlsx", "filename": "legacy.xlsx"}
    assert current_map == {"links": [{"id": "L1"}]}
    assert nested_map == {"links": [{"id": "L2"}]}


def test_format_results_as_fallback_preserves_success_and_error_sections():
    router = make_router()
    tool_results = [
        {
            "name": "calculate_macro_emission",
            "result": {
                "success": True,
                "summary": "宏观排放计算完成",
                "data": {"links_processed": 2},
            },
        },
        {
            "name": "query_emission_factors",
            "result": {
                "success": False,
                "message": "invalid pollutant",
                "suggestions": ["请检查污染物名称"],
            },
        },
    ]

    fallback_text = router._format_results_as_fallback(tool_results)

    assert fallback_text.startswith("## 工具执行结果")
    assert "⚠️ 1 个工具执行失败，1 个成功" in fallback_text
    assert "### 1. calculate_macro_emission" in fallback_text
    assert "**状态**: ✅ 成功" in fallback_text
    assert "**结果**: 宏观排放计算完成" in fallback_text
    assert "### 2. query_emission_factors" in fallback_text
    assert "**状态**: ❌ 失败" in fallback_text
    assert "**错误**: invalid pollutant" in fallback_text
    assert "- 请检查污染物名称" in fallback_text
    assert "links_processed" not in fallback_text
    assert len(fallback_text) < 3000


@pytest.mark.anyio
async def test_synthesize_results_calls_llm_with_built_request_and_returns_content():
    router = make_router()
    router.llm = SimpleNamespace(
        chat=AsyncMock(return_value=SimpleNamespace(content="综合结论：排放计算已完成。"))
    )
    context = SimpleNamespace(messages=[{"role": "user", "content": "请整合这些工具结果"}])
    tool_results = [
        {
            "name": "calculate_macro_emission",
            "result": {
                "success": True,
                "summary": "宏观排放计算完成",
                "data": {
                    "vehicle_type": "Passenger Car",
                    "pollutants": ["CO2"],
                    "model_year": 2022,
                    "season": "summer",
                    "download_file": "/tmp/macro.xlsx",
                    "summary": {
                        "total_emissions": {"CO2": 12.3},
                        "total_distance_km": 8.8,
                        "total_time_s": 500,
                    },
                    "results": [{"link_id": "L1"}],
                },
            },
        },
        {
            "name": "analyze_file",
            "result": {
                "success": True,
                "data": {
                    "task_type": "macro_emission",
                    "columns": ["link_id", "flow"],
                    "row_count": 3,
                    "file_path": "/tmp/input.csv",
                },
            },
        },
    ]

    synthesized = await router._synthesize_results(context, None, tool_results)

    assert synthesized == "综合结论：排放计算已完成。"
    router.llm.chat.assert_awaited_once()
    llm_kwargs = router.llm.chat.await_args.kwargs
    assert llm_kwargs["messages"] == [{"role": "user", "content": "请整合这些工具结果"}]
    assert llm_kwargs["system"].startswith("你是机动车排放计算助手。")
    assert '"calculate_macro_emission"' in llm_kwargs["system"]
    assert '"analyze_file"' in llm_kwargs["system"]


@pytest.mark.anyio
async def test_synthesize_results_short_circuits_failures_without_calling_llm():
    router = make_router()
    router.llm = SimpleNamespace(chat=AsyncMock())
    context = SimpleNamespace(messages=[{"role": "user", "content": "请总结失败情况"}])
    tool_results = [
        {
            "name": "calculate_macro_emission",
            "result": {
                "success": False,
                "message": "bad file",
                "suggestions": ["检查输入文件"],
            },
        }
    ]

    synthesized = await router._synthesize_results(context, None, tool_results)

    assert synthesized.startswith("## 工具执行结果")
    assert "**错误**: bad file" in synthesized
    router.llm.chat.assert_not_awaited()
