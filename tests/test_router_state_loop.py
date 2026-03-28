"""Contract tests for the new router state loop and legacy dispatch path."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from config import get_config
from core.artifact_memory import ArtifactType, build_artifact_record
from core.geometry_recovery import GeometryRecoveryContext, SupportingSpatialInput
from core.memory import FactMemory
from core.plan import ExecutionPlan, PlanStep, PlanStepStatus
from core.readiness import ReadinessStatus
from core.residual_reentry import RecoveredWorkflowReentryContext, ResidualReentryTarget
from core.router import UnifiedRouter
from core.task_state import TaskStage, TaskState
from core.trace import Trace
from services.llm_client import LLMResponse, ToolCall
from tests.test_context_store import make_emission_result


class FakeMemory:
    def __init__(self, fact_memory=None, working_memory=None):
        self.fact_memory = FactMemory()
        for key, value in (fact_memory or {}).items():
            if hasattr(self.fact_memory, key):
                setattr(self.fact_memory, key, value)
        self._working_memory = working_memory or []
        self.update_calls = []

    def get_fact_memory(self):
        return {
            "recent_vehicle": self.fact_memory.recent_vehicle,
            "recent_pollutants": self.fact_memory.recent_pollutants,
            "recent_year": self.fact_memory.recent_year,
            "active_file": self.fact_memory.active_file,
            "file_analysis": self.fact_memory.file_analysis,
            "last_tool_name": self.fact_memory.last_tool_name,
            "last_tool_summary": self.fact_memory.last_tool_summary,
            "last_tool_snapshot": self.fact_memory.last_tool_snapshot,
            "last_spatial_data": self.fact_memory.last_spatial_data,
        }

    def get_working_memory(self):
        return list(self._working_memory)

    def update(self, user_message, assistant_response, tool_calls=None, file_path=None, file_analysis=None):
        self.update_calls.append(
            {
                "user_message": user_message,
                "assistant_response": assistant_response,
                "tool_calls": tool_calls,
                "file_path": file_path,
                "file_analysis": file_analysis,
            }
        )


def make_router(
    *,
    llm_response: LLMResponse,
    executor_result=None,
    fact_memory=None,
    working_memory=None,
) -> UnifiedRouter:
    router = object.__new__(UnifiedRouter)
    router.session_id = "test-session"
    router.runtime_config = get_config()
    router.memory = FakeMemory(fact_memory=fact_memory, working_memory=working_memory)
    router.assembler = SimpleNamespace(
        assemble=Mock(
            return_value=SimpleNamespace(
                system_prompt="system prompt",
                tools=[{"type": "function", "function": {"name": "query_emission_factors"}}],
                messages=[{"role": "user", "content": "test user message"}],
                estimated_tokens=12,
            )
        )
    )
    router.executor = SimpleNamespace(execute=AsyncMock(return_value=executor_result or {}))
    router.llm = SimpleNamespace(
        chat_with_tools=AsyncMock(return_value=llm_response),
        chat=AsyncMock(return_value=LLMResponse(content="unused synthesis")),
        chat_json=AsyncMock(return_value={}),
    )
    return router


def make_negotiation_standardization_error(
    *,
    raw_value: str = "飞机",
    selected_value: str = "Passenger Car",
    suggestions=None,
    confidence: float = 0.62,
    strategy: str = "llm",
):
    return {
        "success": False,
        "error": True,
        "error_type": "standardization",
        "message": (
            f"Parameter 'vehicle_type' for value '{raw_value}' requires confirmation before execution. "
            f"Candidates: {', '.join(suggestions or [selected_value, 'Transit Bus'])}"
        ),
        "suggestions": suggestions or ["乘用车 (Passenger Car)", "公交车 (Transit Bus)"],
        "param_name": "vehicle_type",
        "original_value": raw_value,
        "negotiation_eligible": True,
        "trigger_reason": f"low_confidence_{strategy}_match(confidence={confidence:.2f})",
        "_standardization_records": [
            {
                "param": "vehicle_type",
                "success": True,
                "original": raw_value,
                "normalized": selected_value,
                "strategy": strategy,
                "confidence": confidence,
                "suggestions": suggestions or ["乘用车 (Passenger Car)", "公交车 (Transit Bus)"],
            }
        ],
    }


def _macro_file_analysis(*, has_geometry: bool, missing_flow: bool = False) -> dict:
    diagnostics = {
        "task_type": "macro_emission",
        "status": "partial" if missing_flow else "complete",
        "required_fields": ["link_id", "traffic_flow_vph", "avg_speed_kph"],
        "required_field_statuses": [
            {
                "field": "link_id",
                "status": "present",
                "mapped_from": "segment_id",
                "candidate_columns": [],
                "reason": "present",
            },
            {
                "field": "traffic_flow_vph",
                "status": "missing" if missing_flow else "present",
                "mapped_from": None if missing_flow else "daily_traffic",
                "candidate_columns": [],
                "reason": "missing" if missing_flow else "present",
            },
            {
                "field": "avg_speed_kph",
                "status": "present",
                "mapped_from": "avg_speed",
                "candidate_columns": [],
                "reason": "present",
            },
        ],
        "missing_fields": [] if not missing_flow else [{"field": "traffic_flow_vph", "status": "missing"}],
        "derivable_opportunities": [],
    }
    payload = {
        "filename": "roads.csv",
        "file_path": "/tmp/roads.csv",
        "task_type": "macro_emission",
        "confidence": 0.93,
        "columns": ["segment_id", "daily_traffic", "avg_speed"],
        "column_mapping": {
            "segment_id": "link_id",
            "daily_traffic": "daily_traffic" if missing_flow else "traffic_flow_vph",
            "avg_speed": "avg_speed_kph",
        },
        "missing_field_diagnostics": diagnostics,
    }
    if has_geometry:
        payload["spatial_metadata"] = {
            "crs": "EPSG:4326",
            "bounds": {"min_x": 121.4, "min_y": 31.2, "max_x": 121.6, "max_y": 31.4},
        }
    return payload


def _emission_result_without_geometry(label: str = "baseline") -> dict:
    result = make_emission_result(label=label)
    result["data"]["results"] = [
        {
            "link_id": "L1",
            "total_emissions_kg_per_hr": {"CO2": 80.0, "NOx": 0.2},
        },
        {
            "link_id": "L2",
            "total_emissions_kg_per_hr": {"CO2": 40.5, "NOx": 0.14},
        },
    ]
    return result


def _micro_file_analysis() -> dict:
    return {
        "filename": "traj.csv",
        "file_path": "/tmp/traj.csv",
        "task_type": "micro_emission",
        "confidence": 0.91,
        "columns": ["timestamp", "speed_kph", "acceleration_mps2"],
        "column_mapping": {
            "timestamp": "timestamp_s",
            "speed_kph": "speed_kph",
            "acceleration_mps2": "acceleration_mps2",
        },
        "missing_field_diagnostics": {
            "task_type": "micro_emission",
            "status": "complete",
            "required_fields": ["timestamp_s", "speed_kph", "acceleration_mps2"],
            "required_field_statuses": [
                {"field": "timestamp_s", "status": "present"},
                {"field": "speed_kph", "status": "present"},
                {"field": "acceleration_mps2", "status": "present"},
            ],
            "missing_fields": [],
            "derivable_opportunities": [],
        },
    }


def _supporting_spatial_geojson_analysis() -> dict:
    return {
        "filename": "roads.geojson",
        "file_path": "/tmp/roads.geojson",
        "format": "geojson",
        "task_type": "macro_emission",
        "confidence": 0.82,
        "columns": ["segment_id", "name"],
        "dataset_roles": [
            {
                "dataset_name": "roads.geojson",
                "role": "primary_analysis",
                "format": "geojson",
                "selected": True,
            }
        ],
        "spatial_metadata": {
            "geometry_types": ["LineString"],
            "bounds": {"min_x": 121.4, "min_y": 31.2, "max_x": 121.6, "max_y": 31.4},
        },
    }


def _irrelevant_supporting_analysis() -> dict:
    return {
        "filename": "notes.csv",
        "file_path": "/tmp/notes.csv",
        "format": "csv",
        "task_type": "unknown",
        "confidence": 0.2,
        "columns": ["note", "description"],
        "dataset_roles": [
            {
                "dataset_name": "notes.csv",
                "role": "primary_analysis",
                "format": "tabular",
                "selected": True,
            }
        ],
        "spatial_metadata": {},
    }


def _supplemental_flow_analysis(file_path: str, *, key_column: str = "segment_id") -> dict:
    return {
        "filename": Path(file_path).name,
        "file_path": file_path,
        "format": "tabular",
        "task_type": "macro_emission",
        "confidence": 0.87,
        "columns": [key_column, "traffic_flow_vph"],
        "macro_mapping": {
            key_column: "link_id",
            "traffic_flow_vph": "traffic_flow_vph",
        },
        "column_mapping": {
            key_column: "link_id",
            "traffic_flow_vph": "traffic_flow_vph",
        },
        "missing_field_diagnostics": {
            "task_type": "macro_emission",
            "status": "partial",
            "required_fields": ["link_id", "traffic_flow_vph", "avg_speed_kph"],
            "required_field_statuses": [],
            "missing_fields": [],
            "derivable_opportunities": [],
        },
    }


def _merged_macro_analysis(file_path: str) -> dict:
    return {
        "filename": Path(file_path).name,
        "file_path": file_path,
        "task_type": "macro_emission",
        "confidence": 0.95,
        "columns": ["segment_id", "length_km", "avg_speed", "traffic_flow_vph"],
        "column_mapping": {
            "segment_id": "link_id",
            "length_km": "link_length_km",
            "avg_speed": "avg_speed_kph",
            "traffic_flow_vph": "traffic_flow_vph",
        },
        "macro_mapping": {
            "segment_id": "link_id",
            "length_km": "link_length_km",
            "avg_speed": "avg_speed_kph",
            "traffic_flow_vph": "traffic_flow_vph",
        },
        "missing_field_diagnostics": {
            "task_type": "macro_emission",
            "status": "complete",
            "required_fields": ["link_id", "traffic_flow_vph", "avg_speed_kph"],
            "required_field_statuses": [
                {"field": "link_id", "status": "present", "mapped_from": "segment_id"},
                {"field": "traffic_flow_vph", "status": "present", "mapped_from": "traffic_flow_vph"},
                {"field": "avg_speed_kph", "status": "present", "mapped_from": "avg_speed"},
            ],
            "missing_fields": [],
            "derivable_opportunities": [],
        },
    }


@pytest.mark.anyio
async def test_legacy_loop_unchanged():
    config = get_config()
    config.enable_state_orchestration = False

    router = make_router(llm_response=LLMResponse(content="legacy direct response"))
    router._run_state_loop = AsyncMock(side_effect=AssertionError("state loop should not run"))

    result = await router.chat("legacy request")

    assert result.text == "legacy direct response"
    assert result.executed_tool_calls is None
    assert router._run_state_loop.await_count == 0
    assert len(router.memory.update_calls) == 1
    assert router.memory.update_calls[0]["assistant_response"] == "legacy direct response"
    assert router.assembler.assemble.call_count == 1
    assert router.llm.chat_with_tools.await_count == 1


@pytest.mark.anyio
async def test_state_loop_no_tool_call():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True

    router = make_router(llm_response=LLMResponse(content="state direct response"))
    trace = {}

    result = await router.chat("state request", trace=trace)

    assert result.text == "state direct response"
    assert result.trace is not None
    assert result.trace["final_stage"] == "DONE"
    assert isinstance(result.trace["steps"], list)
    assert result.trace_friendly == []
    assert trace["final_stage"] == "DONE"
    assert len(router.memory.update_calls) == 1
    assert router.memory.update_calls[0]["tool_calls"] is None
    assert router.llm.chat_with_tools.await_count == 1


@pytest.mark.anyio
async def test_state_loop_with_tool_call():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True

    tool_call = ToolCall(
        id="call-1",
        name="query_emission_factors",
        arguments={"vehicle_type": "Passenger Car", "model_year": 2020},
    )
    llm_response = LLMResponse(content="calling query tool", tool_calls=[tool_call])
    executor_result = {
        "success": True,
        "summary": "查询成功",
        "data": {
            "vehicle_type": "Passenger Car",
            "model_year": 2020,
            "metadata": {"season": "夏季", "road_type": "快速路"},
            "pollutants": {
                "CO2": {
                    "speed_curve": [
                        {"speed_kph": 20.0, "emission_rate": 1.1},
                        {"speed_kph": 40.0, "emission_rate": 1.4},
                    ],
                    "unit": "g/km",
                    "typical_values": [
                        {"speed_kph": 20.0, "speed_mph": 12, "emission_rate": 1.1},
                    ],
                    "speed_range": {"min_kph": 20.0, "max_kph": 40.0},
                    "data_points": 2,
                    "data_source": "test-source",
                }
            },
        },
    }
    router = make_router(llm_response=llm_response, executor_result=executor_result)
    router.llm.chat_with_tools = AsyncMock(
        side_effect=[
            llm_response,
            LLMResponse(content="## 排放因子查询结果\n- Passenger Car (2020)"),
        ]
    )
    trace = {}

    result = await router.chat("query emission factors", trace=trace)

    assert result.text.startswith("## 排放因子查询结果")
    assert result.chart_data["type"] == "emission_factors"
    assert result.chart_data["vehicle_type"] == "Passenger Car"
    assert result.executed_tool_calls[0]["name"] == "query_emission_factors"
    assert result.trace["final_stage"] == "DONE"
    assert any(step["step_type"] == "tool_selection" for step in result.trace["steps"])
    assert any(step["step_type"] == "tool_execution" for step in result.trace["steps"])
    assert any(step["step_type"] == "synthesis" for step in result.trace["steps"])
    assert trace["final_stage"] == "DONE"
    assert any(item["step_type"] == "tool_execution" for item in result.trace_friendly)
    assert len(router.memory.update_calls) == 1
    assert router.memory.update_calls[0]["tool_calls"][0]["name"] == "query_emission_factors"
    router.llm.chat.assert_not_awaited()


@pytest.mark.anyio
async def test_state_loop_produces_trace():
    """State loop should produce structured trace with steps when enable_trace=True."""
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True

    router = make_router(llm_response=LLMResponse(content="trace only response"))

    result = await router.chat("trace request", trace={})

    assert result.trace is not None
    assert isinstance(result.trace["steps"], list)
    assert result.trace["final_stage"] == "DONE"
    assert isinstance(result.trace_friendly, list)


@pytest.mark.anyio
async def test_clarification_on_unknown_file_type():
    """When file analysis returns unknown task_type and LLM selects a tool,
    the system should enter NEEDS_CLARIFICATION."""
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True

    tool_call = ToolCall(
        id="call-unknown-file",
        name="calculate_macro_emission",
        arguments={"file_path": "/tmp/upload.csv"},
    )
    llm_response = LLMResponse(content="calling macro tool", tool_calls=[tool_call])
    router = make_router(llm_response=llm_response)
    router._analyze_file = AsyncMock(
        return_value={
            "filename": "upload.csv",
            "task_type": "unknown",
            "confidence": 0.3,
            "columns": ["x", "y"],
            "row_count": 8,
            "sample_rows": [{"x": 1, "y": 2}],
            "micro_mapping": {},
            "macro_mapping": {},
            "micro_has_required": False,
            "macro_has_required": False,
            "evidence": ["No clear task indicators found"],
        }
    )

    result = await router.chat("analyze this file", file_path="/tmp/upload.csv", trace={})

    assert "trajectory data" in result.text
    assert "road link data" in result.text
    assert result.trace["final_stage"] == "NEEDS_CLARIFICATION"
    assert any(step["step_type"] == "clarification" for step in result.trace_friendly)
    router.executor.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_file_grounding_fallback_integrates_into_state_loop():
    config = get_config()
    previous_flag = config.enable_file_analysis_llm_fallback
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_file_analysis_llm_fallback = True

    try:
        router = make_router(llm_response=LLMResponse(content="direct response after grounding"))
        router._analyze_file = AsyncMock(
            return_value={
                "filename": "custom_links.csv",
                "format": "tabular",
                "task_type": "unknown",
                "confidence": 0.28,
                "columns": ["lkid", "vol", "spd", "len_km"],
                "row_count": 15,
                "sample_rows": [{"lkid": "L1", "vol": 1200, "spd": 42, "len_km": 1.3}],
                "micro_mapping": {},
                "macro_mapping": {},
                "column_mapping": {},
                "micro_has_required": False,
                "macro_has_required": False,
                "evidence": ["No clear task type indicators found"],
            }
        )
        router.llm.chat_json = AsyncMock(
            return_value={
                "task_type": "macro_emission",
                "confidence": 0.81,
                "column_mapping": {
                    "link_id": "lkid",
                    "traffic_flow_vph": "vol",
                    "avg_speed_kph": "spd",
                    "link_length_km": "len_km",
                },
                "reasoning_summary": "The abbreviations vol, spd, and len_km align with macro road-link fields.",
                "evidence": ["vol", "spd", "len_km"],
            }
        )

        result = await router.chat("分析这个文件", file_path="/tmp/custom_links.csv", trace={})

        assembled_file_context = router.assembler.assemble.call_args.kwargs["file_context"]
        assert assembled_file_context["task_type"] == "macro_emission"
        assert assembled_file_context["column_mapping"]["vol"] == "traffic_flow_vph"
        assert assembled_file_context["fallback_used"] is True
        assert any(step["step_type"] == "file_analysis_fallback_triggered" for step in result.trace["steps"])
        assert any(step["step_type"] == "file_analysis_fallback_applied" for step in result.trace["steps"])
    finally:
        config.enable_file_analysis_llm_fallback = previous_flag


@pytest.mark.anyio
async def test_file_grounding_fallback_failure_remains_safe():
    config = get_config()
    previous_flag = config.enable_file_analysis_llm_fallback
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_file_analysis_llm_fallback = True

    try:
        tool_call = ToolCall(
            id="call-grounding-failure",
            name="calculate_macro_emission",
            arguments={"file_path": "/tmp/custom_links.csv"},
        )
        router = make_router(llm_response=LLMResponse(content="calling macro tool", tool_calls=[tool_call]))
        router._analyze_file = AsyncMock(
            return_value={
                "filename": "custom_links.csv",
                "format": "tabular",
                "task_type": "unknown",
                "confidence": 0.28,
                "columns": ["lkid", "vol", "spd", "len_km"],
                "row_count": 15,
                "sample_rows": [{"lkid": "L1", "vol": 1200, "spd": 42, "len_km": 1.3}],
                "micro_mapping": {},
                "macro_mapping": {},
                "column_mapping": {},
                "micro_has_required": False,
                "macro_has_required": False,
                "evidence": ["No clear task type indicators found"],
            }
        )
        router.llm.chat_json = AsyncMock(side_effect=RuntimeError("fallback backend unavailable"))

        result = await router.chat("分析这个文件", file_path="/tmp/custom_links.csv", trace={})

        assert result.trace["final_stage"] == "NEEDS_CLARIFICATION"
        assert any(step["step_type"] == "file_analysis_fallback_failed" for step in result.trace["steps"])
        assert "trajectory data" in result.text
        router.executor.execute.assert_not_awaited()
    finally:
        config.enable_file_analysis_llm_fallback = previous_flag


@pytest.mark.anyio
async def test_file_grounding_enhancement_trace_emission():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True

    router = make_router(llm_response=LLMResponse(content="grounded response"))
    router._analyze_file = AsyncMock(
        return_value={
            "filename": "bundle.zip",
            "format": "zip_multi_dataset",
            "task_type": "macro_emission",
            "confidence": 0.78,
            "columns": ["link_id", "flow", "speed", "length"],
            "row_count": 20,
            "sample_rows": [{"link_id": "L1", "flow": 1200, "speed": 42, "length": 1.3}],
            "micro_mapping": {},
            "macro_mapping": {
                "link_id": "link_id",
                "flow": "traffic_flow_vph",
                "speed": "avg_speed_kph",
                "length": "link_length_km",
            },
            "column_mapping": {
                "link_id": "link_id",
                "flow": "traffic_flow_vph",
                "speed": "avg_speed_kph",
                "length": "link_length_km",
            },
            "micro_has_required": False,
            "macro_has_required": True,
            "selected_primary_table": "roads.csv",
            "candidate_tables": ["roads.csv", "traffic_notes.csv"],
            "dataset_roles": [
                {
                    "dataset_name": "roads.csv",
                    "role": "primary_analysis",
                    "format": "csv",
                    "task_type": "macro_emission",
                    "confidence": 0.78,
                    "selection_score": 1.08,
                    "reason": "Required fields were complete.",
                    "selected": True,
                },
                {
                    "dataset_name": "traffic_notes.csv",
                    "role": "secondary_analysis",
                    "format": "csv",
                    "task_type": "unknown",
                    "confidence": 0.31,
                    "selection_score": 0.31,
                    "reason": "Auxiliary table only.",
                    "selected": False,
                },
            ],
            "dataset_role_summary": {
                "strategy": "rule",
                "ambiguous": False,
                "selected_primary_table": "roads.csv",
                "selection_score_gap": 0.77,
                "role_fallback_eligible": False,
            },
            "missing_field_diagnostics": {
                "task_type": "macro_emission",
                "status": "partial",
                "required_fields": ["link_length_km", "traffic_flow_vph", "avg_speed_kph"],
                "mapped_fields": ["traffic_flow_vph"],
                "missing_fields": [{"field": "avg_speed_kph", "status": "derivable"}],
                "derivable_opportunities": [{"field": "avg_speed_kph", "status": "derivable"}],
            },
            "spatial_metadata": {
                "geometry_column": "geometry",
                "feature_count": 20,
                "geometry_types": ["LineString"],
                "geometry_type_counts": {"LineString": 20},
                "crs": "EPSG:4326",
                "epsg": 4326,
                "bounds": {"min_x": 116.1, "min_y": 39.8, "max_x": 116.5, "max_y": 40.1},
            },
            "evidence": ["rule matched macro road-link fields"],
        }
    )

    result = await router.chat("分析压缩包", file_path="/tmp/bundle.zip", trace={})

    step_types = [step["step_type"] for step in result.trace["steps"]]
    assert "file_analysis_multi_table_roles" in step_types
    assert "file_analysis_missing_fields" in step_types
    assert "file_analysis_spatial_metadata" in step_types
    friendly_types = [step["step_type"] for step in result.trace_friendly]
    assert "file_analysis_multi_table_roles" in friendly_types
    assert "file_analysis_missing_fields" in friendly_types
    assert "file_analysis_spatial_metadata" in friendly_types


@pytest.mark.anyio
async def test_template_prior_injection_happens_before_planning():
    config = get_config()
    previous_templates = config.enable_workflow_templates
    previous_planning = config.enable_lightweight_planning
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_workflow_templates = True
    config.enable_lightweight_planning = True

    try:
        router = make_router(llm_response=LLMResponse(content="direct response after planning"))
        router._analyze_file = AsyncMock(
            return_value={
                "filename": "roads.shp",
                "format": "shapefile",
                "task_type": "macro_emission",
                "confidence": 0.88,
                "columns": ["link_id", "flow", "speed", "length"],
                "row_count": 20,
                "sample_rows": [{"link_id": "L1", "flow": 1200, "speed": 42, "length": 1.3}],
                "micro_mapping": {},
                "macro_mapping": {
                    "link_id": "link_id",
                    "flow": "traffic_flow_vph",
                    "speed": "avg_speed_kph",
                    "length": "link_length_km",
                },
                "column_mapping": {
                    "link_id": "link_id",
                    "flow": "traffic_flow_vph",
                    "speed": "avg_speed_kph",
                    "length": "link_length_km",
                },
                "micro_has_required": False,
                "macro_has_required": True,
                "selected_primary_table": "roads.shp",
                "dataset_roles": [
                    {
                        "dataset_name": "roads.shp",
                        "role": "primary_analysis",
                        "format": "shapefile",
                        "task_type": "macro_emission",
                        "confidence": 0.88,
                        "selection_score": 1.08,
                        "reason": "Primary spatial road-link table.",
                        "selected": True,
                    }
                ],
                "dataset_role_summary": {
                    "strategy": "rule",
                    "ambiguous": False,
                    "selected_primary_table": "roads.shp",
                    "selection_score_gap": None,
                },
                "missing_field_diagnostics": {
                    "task_type": "macro_emission",
                    "status": "complete",
                    "required_fields": ["link_length_km", "traffic_flow_vph", "avg_speed_kph"],
                    "missing_fields": [],
                    "derivable_opportunities": [],
                },
                "spatial_metadata": {
                    "geometry_types": ["LineString"],
                    "feature_count": 20,
                    "crs": "EPSG:4326",
                    "bounds": {"min_x": 116.1, "min_y": 39.8, "max_x": 116.5, "max_y": 40.1},
                },
                "evidence": ["rule matched macro road-link fields"],
            }
        )
        router.llm.chat_json = AsyncMock(
            return_value={
                "goal": "Compute macro emissions then derive hotspots",
                "steps": [
                    {"step_id": "s1", "tool_name": "calculate_macro_emission", "produces": ["emission"]},
                    {"step_id": "s2", "tool_name": "calculate_dispersion", "depends_on": ["emission"], "produces": ["dispersion"]},
                ],
            }
        )

        result = await router.chat("先做扩散热点，再渲染地图", file_path="/tmp/roads.shp", trace={})
    finally:
        config.enable_workflow_templates = previous_templates
        config.enable_lightweight_planning = previous_planning

    payload = json.loads(router.llm.chat_json.await_args.kwargs["messages"][0]["content"])
    assert payload["workflow_template_prior"]["selected_template"]["template_id"] == "macro_spatial_chain"
    step_types = [step["step_type"] for step in result.trace["steps"]]
    assert "workflow_template_recommended" in step_types
    assert "workflow_template_selected" in step_types
    assert "workflow_template_injected" in step_types
    assert step_types.index("workflow_template_injected") < step_types.index("plan_created")


@pytest.mark.anyio
async def test_continuation_path_skips_fresh_workflow_template_recommendation():
    config = get_config()
    previous_templates = config.enable_workflow_templates
    previous_continuation = config.enable_repair_aware_continuation
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_workflow_templates = True
    config.enable_repair_aware_continuation = True

    router = make_router(
        llm_response=LLMResponse(
            content="continue with dispersion",
            tool_calls=[ToolCall(id="c1", name="calculate_dispersion", arguments={"pollutant": "CO2"})],
        )
    )
    router._ensure_live_continuation_bundle().update(
        {
            "plan": ExecutionPlan(
                goal="Continue repaired residual workflow",
                steps=[
                    PlanStep(step_id="repair_s1", tool_name="calculate_dispersion"),
                    PlanStep(step_id="s3", tool_name="analyze_hotspots", depends_on=["dispersion"]),
                ],
            ).to_dict(),
            "repair_history": [],
            "blocked_info": None,
            "file_path": None,
            "latest_repair_summary": "REPLACE_STEP: Replace blocked render with dispersion.",
            "residual_plan_summary": "Goal: Continue repaired residual workflow",
        }
    )

    next_turn_state = TaskState.initialize(
        user_message="继续",
        file_path=None,
        memory_dict={},
        session_id="test-session",
    )
    trace_obj = Trace.start(session_id="test-session")

    try:
        await router._state_handle_input(next_turn_state, trace_obj=trace_obj)
    finally:
        config.enable_workflow_templates = previous_templates
        config.enable_repair_aware_continuation = previous_continuation

    step_types = [step.step_type.value for step in trace_obj.steps]
    assert "workflow_template_skipped" in step_types
    assert "workflow_template_recommended" not in step_types
    assert next_turn_state.selected_workflow_template is None
    assert next_turn_state.execution.selected_tool == "calculate_dispersion"


@pytest.mark.anyio
async def test_clarification_on_standardization_error():
    """When executor returns a standardization error, system should enter NEEDS_CLARIFICATION."""
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True

    tool_call = ToolCall(
        id="call-std-error",
        name="query_emission_factors",
        arguments={"vehicle_type": "飞机", "model_year": 2020},
    )
    llm_response = LLMResponse(content="calling factor tool", tool_calls=[tool_call])
    executor_result = {
        "success": False,
        "error": True,
        "error_type": "standardization",
        "message": "Cannot standardize vehicle type '飞机'. Suggestions: 乘用车 (Passenger Car), 公交车 (Transit Bus)",
        "suggestions": ["乘用车 (Passenger Car)", "公交车 (Transit Bus)"],
        "_standardization_records": [],
    }
    router = make_router(llm_response=llm_response, executor_result=executor_result)

    result = await router.chat("query factors for 飞机", trace={})

    assert "Cannot standardize vehicle type '飞机'" in result.text
    assert "Did you mean one of these?" in result.text
    assert result.trace["final_stage"] == "NEEDS_CLARIFICATION"
    assert any(step["step_type"] == "clarification" for step in result.trace_friendly)


@pytest.mark.anyio
async def test_low_confidence_standardization_enters_parameter_negotiation():
    config = get_config()
    previous_flag = config.enable_parameter_negotiation
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_parameter_negotiation = True

    try:
        tool_call = ToolCall(
            id="call-negotiation",
            name="query_emission_factors",
            arguments={"vehicle_type": "飞机", "model_year": 2020},
        )
        router = make_router(
            llm_response=LLMResponse(content="call query tool", tool_calls=[tool_call]),
            executor_result=make_negotiation_standardization_error(),
        )

        result = await router.chat("query factors for 飞机", trace={})

        assert "参数确认" in result.text
        assert "Passenger Car" in result.text
        assert result.trace["final_stage"] == "NEEDS_PARAMETER_CONFIRMATION"
        assert any(step["step_type"] == "parameter_negotiation_required" for step in result.trace_friendly)
        assert router._ensure_live_parameter_negotiation_bundle()["active_request"] is not None
    finally:
        config.enable_parameter_negotiation = previous_flag


@pytest.mark.anyio
async def test_next_turn_confirmation_by_index_applies_parameter_lock_and_continues():
    config = get_config()
    previous_flag = config.enable_parameter_negotiation
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_parameter_negotiation = True

    try:
        first_tool_call = ToolCall(
            id="call-negotiation-1",
            name="query_emission_factors",
            arguments={"vehicle_type": "飞机", "model_year": 2020},
        )
        second_tool_call = ToolCall(
            id="call-negotiation-2",
            name="query_emission_factors",
            arguments={"vehicle_type": "Transit Bus", "model_year": 2020},
        )
        router = make_router(
            llm_response=LLMResponse(content="call query tool", tool_calls=[first_tool_call]),
            executor_result=make_negotiation_standardization_error(),
        )
        router.llm.chat_with_tools = AsyncMock(
            side_effect=[
                LLMResponse(content="call query tool", tool_calls=[first_tool_call]),
                LLMResponse(content="call query tool", tool_calls=[second_tool_call]),
                LLMResponse(content="factor response after confirmation"),
            ]
        )
        router.executor.execute = AsyncMock(
            side_effect=[
                make_negotiation_standardization_error(),
                {
                    "success": True,
                    "summary": "查询成功",
                    "message": "查询成功",
                    "data": {
                        "vehicle_type": "Passenger Car",
                        "model_year": 2020,
                        "pollutants": {
                            "CO2": {
                                "speed_curve": [{"speed_kph": 20.0, "emission_rate": 1.1}],
                                "unit": "g/km",
                            }
                        },
                    },
                },
            ]
        )

        first_result = await router.chat("query factors for 飞机", trace={})
        second_result = await router.chat("1", trace={})

        assert first_result.trace["final_stage"] == "NEEDS_PARAMETER_CONFIRMATION"
        assert second_result.trace["final_stage"] == "DONE"
        assert second_result.text == "factor response after confirmation"
        assert any(step["step_type"] == "parameter_negotiation_confirmed" for step in second_result.trace_friendly)

        second_execute_call = router.executor.execute.await_args_list[1]
        assert second_execute_call.kwargs["arguments"]["vehicle_type"] == "Passenger Car"
        locks = router._ensure_live_parameter_negotiation_bundle()["locked_parameters"]
        assert locks["vehicle_type"]["locked"] is True
        assert locks["vehicle_type"]["normalized"] == "Passenger Car"
    finally:
        config.enable_parameter_negotiation = previous_flag


@pytest.mark.anyio
async def test_parameter_negotiation_none_of_above_moves_to_clarification():
    config = get_config()
    previous_flag = config.enable_parameter_negotiation
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_parameter_negotiation = True

    try:
        tool_call = ToolCall(
            id="call-negotiation-none",
            name="query_emission_factors",
            arguments={"vehicle_type": "飞机", "model_year": 2020},
        )
        router = make_router(
            llm_response=LLMResponse(content="call query tool", tool_calls=[tool_call]),
            executor_result=make_negotiation_standardization_error(),
        )

        await router.chat("query factors for 飞机", trace={})
        result = await router.chat("都不对", trace={})

        assert result.trace["final_stage"] == "NEEDS_CLARIFICATION"
        assert "请直接提供一个明确的" in result.text
        assert any(step["step_type"] == "parameter_negotiation_rejected" for step in result.trace_friendly)
        assert router._ensure_live_parameter_negotiation_bundle()["active_request"] is None
    finally:
        config.enable_parameter_negotiation = previous_flag


@pytest.mark.anyio
async def test_parameter_negotiation_ambiguous_reply_retries_without_locking():
    config = get_config()
    previous_flag = config.enable_parameter_negotiation
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_parameter_negotiation = True

    try:
        tool_call = ToolCall(
            id="call-negotiation-ambiguous",
            name="query_emission_factors",
            arguments={"vehicle_type": "飞机", "model_year": 2020},
        )
        router = make_router(
            llm_response=LLMResponse(content="call query tool", tool_calls=[tool_call]),
            executor_result=make_negotiation_standardization_error(),
        )

        await router.chat("query factors for 飞机", trace={})
        result = await router.chat("第一个还是第二个", trace={})

        assert result.trace["final_stage"] == "NEEDS_PARAMETER_CONFIRMATION"
        assert "上次回复未能唯一确认" in result.text
        assert any(step["step_type"] == "parameter_negotiation_failed" for step in result.trace_friendly)
        assert router._ensure_live_parameter_negotiation_bundle()["locked_parameters"] == {}
    finally:
        config.enable_parameter_negotiation = previous_flag


@pytest.mark.anyio
async def test_parameter_negotiation_confirmation_preserves_residual_continuation():
    config = get_config()
    previous_negotiation = config.enable_parameter_negotiation
    previous_continuation = config.enable_repair_aware_continuation
    previous_templates = config.enable_workflow_templates
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_parameter_negotiation = True
    config.enable_repair_aware_continuation = True
    config.enable_workflow_templates = True

    try:
        tool_call = ToolCall(
            id="call-negotiation-continuation",
            name="query_emission_factors",
            arguments={"vehicle_type": "飞机", "model_year": 2020},
        )
        router = make_router(
            llm_response=LLMResponse(content="call query tool", tool_calls=[tool_call]),
            executor_result=make_negotiation_standardization_error(),
        )
        router._ensure_live_continuation_bundle().update(
            {
                "plan": ExecutionPlan(
                    goal="Query factors then continue with dispersion",
                    steps=[
                        PlanStep(step_id="s1", tool_name="query_emission_factors"),
                        PlanStep(step_id="s2", tool_name="calculate_dispersion"),
                    ],
                ).to_dict(),
                "repair_history": [],
                "blocked_info": None,
                "file_path": None,
                "latest_repair_summary": None,
                "residual_plan_summary": "Goal: Query factors then continue with dispersion",
            }
        )
        router.llm.chat_with_tools = AsyncMock(
            side_effect=[
                LLMResponse(content="call query tool", tool_calls=[tool_call]),
                LLMResponse(content="call query tool", tool_calls=[tool_call]),
                LLMResponse(content="continued after confirmation"),
            ]
        )
        router.executor.execute = AsyncMock(
            side_effect=[
                make_negotiation_standardization_error(),
                {
                    "success": True,
                    "summary": "查询成功",
                    "message": "查询成功",
                    "data": {
                        "vehicle_type": "Passenger Car",
                        "model_year": 2020,
                        "pollutants": {
                            "CO2": {
                                "speed_curve": [{"speed_kph": 20.0, "emission_rate": 1.1}],
                                "unit": "g/km",
                            }
                        },
                    },
                },
            ]
        )

        await router.chat("query factors for 飞机", trace={})
        result = await router.chat("1", trace={})

        assert result.trace["final_stage"] == "DONE"
        assert any(step["step_type"] == "parameter_negotiation_confirmed" for step in result.trace_friendly)
        assert any(step["step_type"] == "plan_continuation_decided" for step in result.trace_friendly)
        assert any(step["step_type"] == "plan_continuation_injected" for step in result.trace_friendly)
        assert any(step["step_type"] == "workflow_template_skipped" for step in result.trace_friendly)
        assert all(
            step["step_type"] != "workflow_template_selected"
            for step in result.trace_friendly
        )
        injected_messages = router.assembler.assemble.return_value.messages
        assert any(
            msg.get("role") == "system" and "Confirmed parameter locks" in msg.get("content", "")
            for msg in injected_messages
        )
    finally:
        config.enable_parameter_negotiation = previous_negotiation
        config.enable_repair_aware_continuation = previous_continuation
        config.enable_workflow_templates = previous_templates


@pytest.mark.anyio
async def test_state_loop_saves_full_spatial_data_before_memory_compaction(caplog):
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True

    tool_call = ToolCall(
        id="call-macro",
        name="calculate_macro_emission",
        arguments={"pollutants": ["CO2", "NOx"]},
    )
    llm_response = LLMResponse(content="calling macro tool", tool_calls=[tool_call])
    spatial_data = {
        "query_info": {"pollutants": ["CO2", "NOx"]},
        "summary": {"total_links": 2},
        "results": [
            {"link_id": "L1", "geometry": "LINESTRING (0 0, 1 1)"},
            {"link_id": "L2", "geometry": "LINESTRING (1 1, 2 2)"},
        ],
    }
    executor_result = {
        "success": True,
        "summary": "宏观排放计算完成",
        "data": spatial_data,
    }
    router = make_router(llm_response=llm_response, executor_result=executor_result)

    with caplog.at_level("INFO"):
        result = await router.chat("计算排放", trace={})

    assert result.executed_tool_calls[0]["result"]["data"]["summary"] == {"total_links": 2}
    assert "results" not in result.executed_tool_calls[0]["result"]["data"]
    assert router.memory.fact_memory.last_spatial_data == spatial_data
    assert "Saved last_spatial_data: 2 links with geometry" in caplog.text
    assert router.memory.update_calls[0]["tool_calls"][0]["result"]["data"]["summary"] == {"total_links": 2}
    assert "results" not in router.memory.update_calls[0]["tool_calls"][0]["result"]["data"]


@pytest.mark.anyio
async def test_render_spatial_map_injects_last_spatial_data_from_memory(caplog):
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True

    spatial_data = {
        "query_info": {"pollutants": ["CO2"]},
        "summary": {"total_links": 2},
        "results": [
            {"link_id": "L1", "geometry": "LINESTRING (0 0, 1 1)"},
            {"link_id": "L2", "geometry": "LINESTRING (1 1, 2 2)"},
        ],
    }
    tool_call = ToolCall(
        id="call-render",
        name="render_spatial_map",
        arguments={"pollutant": "CO2"},
    )
    llm_response = LLMResponse(content="calling render tool", tool_calls=[tool_call])
    executor_result = {
        "success": True,
        "summary": "地图生成成功",
        "map_data": {"links": [{"link_id": "L1"}, {"link_id": "L2"}]},
    }
    router = make_router(
        llm_response=llm_response,
        executor_result=executor_result,
        fact_memory={"last_spatial_data": spatial_data},
    )
    router.llm.chat_with_tools = AsyncMock(
        side_effect=[
            llm_response,
            LLMResponse(content="地图已生成。"),
        ]
    )

    with caplog.at_level("INFO"):
        result = await router.chat("帮我可视化CO2排放", trace={})

    execute_kwargs = router.executor.execute.await_args.kwargs
    assert execute_kwargs["arguments"]["_last_result"] == {"success": True, "data": spatial_data}
    assert result.map_data == {"links": [{"link_id": "L1"}, {"link_id": "L2"}]}
    assert "render_spatial_map: injected from memory spatial_data, 2 links" in caplog.text


@pytest.mark.anyio
async def test_lightweight_planning_runs_before_first_tool_call_after_grounding():
    config = get_config()
    previous = config.enable_lightweight_planning
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_lightweight_planning = True

    plan_payload = {
        "goal": "Compute emissions and render them on a map",
        "planner_notes": "Grounded from uploaded road-link file.",
        "steps": [
            {
                "step_id": "s1",
                "tool_name": "calculate_macro_emission",
                "purpose": "Compute road-link emissions",
                "depends_on": [],
                "produces": ["emission"],
                "argument_hints": {"pollutants": ["CO2"]},
            },
            {
                "step_id": "s2",
                "tool_name": "render_spatial_map",
                "purpose": "Render the emission result",
                "depends_on": ["emission"],
                "produces": [],
                "argument_hints": {"layer_type": "emission"},
            },
        ],
    }
    router = make_router(llm_response=LLMResponse(content="state direct response"))
    router._analyze_file = AsyncMock(
        return_value={
            "filename": "roads.csv",
            "task_type": "macro_emission",
            "confidence": 0.97,
            "columns": ["link_id", "flow", "speed"],
            "row_count": 12,
            "sample_rows": [{"link_id": "L1", "flow": 1000, "speed": 40}],
            "macro_mapping": {"flow": "traffic_flow_vph", "speed": "avg_speed_kph"},
            "micro_mapping": {},
            "micro_has_required": False,
            "macro_has_required": True,
            "evidence": ["macro columns matched"],
        }
    )

    call_order = []

    async def chat_json_side_effect(*args, **kwargs):
        call_order.append("chat_json")
        return plan_payload

    async def chat_with_tools_side_effect(*args, **kwargs):
        call_order.append("chat_with_tools")
        assert any(
            message["role"] == "system" and "Execution plan guidance" in message["content"]
            for message in kwargs["messages"]
        )
        return LLMResponse(content="state direct response")

    router.llm.chat_json = AsyncMock(side_effect=chat_json_side_effect)
    router.llm.chat_with_tools = AsyncMock(side_effect=chat_with_tools_side_effect)

    try:
        result = await router.chat("请先计算排放再渲染地图", file_path="/tmp/roads.csv", trace={})
    finally:
        config.enable_lightweight_planning = previous

    assert call_order == ["chat_json", "chat_with_tools"]
    assert any(step["step_type"] == "plan_created" for step in result.trace["steps"])
    assert any(step["step_type"] == "plan_validated" for step in result.trace["steps"])


@pytest.mark.anyio
async def test_plan_deviation_is_traced_without_blocking_execution():
    config = get_config()
    previous = config.enable_lightweight_planning
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_lightweight_planning = True

    tool_call = ToolCall(id="call-1", name="query_emission_factors", arguments={})
    router = make_router(
        llm_response=LLMResponse(content="call query tool", tool_calls=[tool_call]),
        executor_result={
            "success": True,
            "summary": "查询成功",
            "data": {
                "vehicle_type": "Passenger Car",
                "model_year": 2020,
                "pollutants": {
                    "CO2": {
                        "speed_curve": [{"speed_kph": 40.0, "emission_rate": 1.4}],
                        "unit": "g/km",
                        "data_points": 1,
                    }
                },
            },
        },
    )
    router.llm.chat_json = AsyncMock(
        return_value={
            "goal": "Compute emissions and render a map",
            "steps": [
                {
                    "step_id": "s1",
                    "tool_name": "calculate_macro_emission",
                    "depends_on": [],
                    "produces": ["emission"],
                    "argument_hints": {"pollutants": ["CO2"]},
                },
                {
                    "step_id": "s2",
                    "tool_name": "render_spatial_map",
                    "depends_on": ["emission"],
                    "argument_hints": {"layer_type": "emission"},
                },
            ],
        }
    )
    router.llm.chat_with_tools = AsyncMock(
        side_effect=[
            LLMResponse(content="call query tool", tool_calls=[tool_call]),
            LLMResponse(content="查询完成。"),
        ]
    )

    try:
        result = await router.chat("先计算排放再渲染地图", trace={})
    finally:
        config.enable_lightweight_planning = previous

    assert result.text == "查询完成。"
    assert any(step["step_type"] == "plan_deviation" for step in result.trace["steps"])
    assert any(item["step_type"] == "plan_deviation" for item in result.trace_friendly)


@pytest.mark.anyio
async def test_planning_failure_falls_back_to_original_tool_calling():
    config = get_config()
    previous = config.enable_lightweight_planning
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_lightweight_planning = True

    tool_call = ToolCall(id="call-1", name="query_emission_factors", arguments={})
    router = make_router(
        llm_response=LLMResponse(content="call query tool", tool_calls=[tool_call]),
        executor_result={
            "success": True,
            "summary": "查询成功",
            "data": {
                "vehicle_type": "Passenger Car",
                "model_year": 2020,
                "pollutants": {
                    "CO2": {
                        "speed_curve": [{"speed_kph": 40.0, "emission_rate": 1.4}],
                        "unit": "g/km",
                        "data_points": 1,
                    }
                },
            },
        },
    )
    router.llm.chat_json = AsyncMock(side_effect=RuntimeError("planner unavailable"))
    router.llm.chat_with_tools = AsyncMock(
        side_effect=[
            LLMResponse(content="call query tool", tool_calls=[tool_call]),
            LLMResponse(content="查询完成。"),
        ]
    )

    try:
        result = await router.chat("先做排放分析然后告诉我结果", trace={})
    finally:
        config.enable_lightweight_planning = previous

    assert result.text == "查询完成。"
    assert router.llm.chat_with_tools.await_count == 2
    assert not any(step["step_type"] == "plan_created" for step in result.trace["steps"])


@pytest.mark.anyio
async def test_execution_stage_plan_reconciliation_tracks_multi_step_matches():
    config = get_config()
    previous = config.enable_lightweight_planning
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_lightweight_planning = True

    router = make_router(llm_response=LLMResponse(content="unused"))
    router.llm.chat_json = AsyncMock(
        return_value={
            "goal": "Compute emissions and render map",
            "steps": [
                {"step_id": "s1", "tool_name": "calculate_macro_emission", "produces": ["emission"]},
                {
                    "step_id": "s2",
                    "tool_name": "render_spatial_map",
                    "depends_on": ["emission"],
                    "argument_hints": {"layer_type": "emission"},
                },
            ],
        }
    )
    router.llm.chat_with_tools = AsyncMock(
        side_effect=[
            LLMResponse(
                content="call macro",
                tool_calls=[ToolCall(id="c1", name="calculate_macro_emission", arguments={"pollutants": ["CO2"]})],
            ),
            LLMResponse(
                content="call render",
                tool_calls=[ToolCall(id="c2", name="render_spatial_map", arguments={"layer_type": "emission"})],
            ),
            LLMResponse(content="已完成。"),
        ]
    )
    router.executor.execute = AsyncMock(
        side_effect=[
            make_emission_result(),
            {
                "success": True,
                "message": "Map rendered",
                "map_data": {"type": "vector_map", "summary": {"total_links": 2}},
                "data": {"map_config": {"summary": {"total_links": 2}}},
            },
        ]
    )

    state = TaskState.initialize(
        user_message="先计算排放再渲染地图",
        file_path=None,
        memory_dict={},
        session_id="test-session",
    )
    trace_obj = Trace.start(session_id="test-session")

    try:
        await router._state_handle_input(state, trace_obj=trace_obj)
        await router._state_handle_grounded(state, trace_obj=trace_obj)
        await router._state_handle_executing(state, trace_obj=trace_obj)
    finally:
        config.enable_lightweight_planning = previous

    assert state.stage == TaskStage.DONE
    assert state.plan is not None
    assert [step.status for step in state.plan.steps] == [
        PlanStepStatus.COMPLETED,
        PlanStepStatus.COMPLETED,
    ]
    assert sum(step.step_type.value == "plan_step_matched" for step in trace_obj.steps) == 2
    assert sum(step.step_type.value == "plan_step_completed" for step in trace_obj.steps) == 2


@pytest.mark.anyio
async def test_execution_stage_deviation_marks_out_of_order_step_without_blocking():
    config = get_config()
    previous = config.enable_lightweight_planning
    previous_repair = config.enable_bounded_plan_repair
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_lightweight_planning = True
    config.enable_bounded_plan_repair = True

    router = make_router(llm_response=LLMResponse(content="unused"))
    router.llm.chat_json = AsyncMock(
        return_value={
            "goal": "Emission then dispersion then render",
            "steps": [
                {"step_id": "s1", "tool_name": "calculate_macro_emission", "produces": ["emission"]},
                {"step_id": "s2", "tool_name": "calculate_dispersion", "depends_on": ["emission"]},
                {
                    "step_id": "s3",
                    "tool_name": "render_spatial_map",
                    "depends_on": ["emission"],
                    "argument_hints": {"layer_type": "emission"},
                },
            ],
        }
    )
    router.llm.chat_with_tools = AsyncMock(
        side_effect=[
            LLMResponse(
                content="call macro",
                tool_calls=[ToolCall(id="c1", name="calculate_macro_emission", arguments={"pollutants": ["CO2"]})],
            ),
            LLMResponse(
                content="call render",
                tool_calls=[ToolCall(id="c2", name="render_spatial_map", arguments={"layer_type": "emission"})],
            ),
            LLMResponse(content="完成。"),
        ]
    )
    router.executor.execute = AsyncMock(
        side_effect=[
            make_emission_result(),
            {
                "success": True,
                "message": "Map rendered",
                "map_data": {"type": "vector_map", "summary": {"total_links": 2}},
                "data": {"map_config": {"summary": {"total_links": 2}}},
            },
        ]
    )

    state = TaskState.initialize(
        user_message="先算排放，然后直接画图",
        file_path=None,
        memory_dict={},
        session_id="test-session",
    )
    trace_obj = Trace.start(session_id="test-session")

    try:
        await router._state_handle_input(state, trace_obj=trace_obj)
        await router._state_handle_grounded(state, trace_obj=trace_obj)
        await router._state_handle_executing(state, trace_obj=trace_obj)
    finally:
        config.enable_lightweight_planning = previous
        config.enable_bounded_plan_repair = previous_repair

    assert state.stage == TaskStage.DONE
    assert state.plan is not None
    assert state.plan.steps[0].status == PlanStepStatus.COMPLETED
    assert state.plan.steps[1].status == PlanStepStatus.READY
    assert state.plan.steps[2].status == PlanStepStatus.COMPLETED
    deviation_steps = [step for step in trace_obj.steps if step.step_type.value == "plan_deviation"]
    assert deviation_steps
    assert any(step.input_summary.get("deviation_type") == "ahead_of_plan" for step in deviation_steps if step.input_summary)
    assert any(step.step_type.value == "plan_repair_skipped" for step in trace_obj.steps)


@pytest.mark.anyio
async def test_dependency_blocked_before_execution_marks_plan_and_builds_response():
    config = get_config()
    previous = config.enable_lightweight_planning
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_lightweight_planning = True

    router = make_router(llm_response=LLMResponse(content="unused"))
    router.llm.chat_json = AsyncMock(
        return_value={
            "goal": "Run hotspot analysis",
            "steps": [
                {"step_id": "s1", "tool_name": "analyze_hotspots", "depends_on": ["dispersion"]},
            ],
        }
    )
    router.llm.chat_with_tools = AsyncMock(
        return_value=LLMResponse(
            content="call hotspot",
            tool_calls=[ToolCall(id="c1", name="analyze_hotspots", arguments={})],
        )
    )

    state = TaskState.initialize(
        user_message="做热点分析",
        file_path=None,
        memory_dict={},
        session_id="test-session",
    )
    trace_obj = Trace.start(session_id="test-session")

    try:
        await router._state_handle_input(state, trace_obj=trace_obj)
        await router._state_handle_grounded(state, trace_obj=trace_obj)
        await router._state_handle_executing(state, trace_obj=trace_obj)
        response = await router._state_build_response(state, "做热点分析", trace_obj=trace_obj)
    finally:
        config.enable_lightweight_planning = previous

    assert state.stage == TaskStage.DONE
    assert state.plan is not None
    assert state.plan.steps[0].status == PlanStepStatus.BLOCKED
    assert state.execution.blocked_info is not None
    assert "dispersion" in state.execution.blocked_info["missing_tokens"]
    assert "Cannot execute analyze_hotspots" in response.text
    assert any(step.step_type.value == "dependency_blocked" for step in trace_obj.steps)
    router.executor.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_readiness_repairable_pre_execution_stops_render_without_geometry():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_readiness_gating = True
    config.readiness_repairable_enabled = True

    router = make_router(
        llm_response=LLMResponse(
            content="call render",
            tool_calls=[ToolCall(id="c1", name="render_spatial_map", arguments={"layer_type": "emission"})],
        )
    )
    emission_result = make_emission_result()
    for row in emission_result["data"]["results"]:
        row["geometry"] = None
    router._ensure_context_store().store_result("calculate_macro_emission", emission_result)
    router.memory = FakeMemory(
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=False),
        }
    )

    state = TaskState.initialize(
        user_message="把排放画在地图上",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    trace_obj = Trace.start(session_id="test-session")

    await router._state_handle_input(state, trace_obj=trace_obj)
    await router._state_handle_grounded(state, trace_obj=trace_obj)
    await router._state_handle_executing(state, trace_obj=trace_obj)
    response = await router._state_build_response(state, "把排放画在地图上", trace_obj=trace_obj)

    assert state.stage == TaskStage.NEEDS_INPUT_COMPLETION
    assert state.active_input_completion is not None
    assert state.execution.blocked_info is not None
    assert state.execution.blocked_info["status"] == "repairable"
    assert state.execution.blocked_info["reason_code"] == "missing_geometry"
    assert "上传" in response.text
    assert any(step.step_type.value == "readiness_assessment_built" for step in trace_obj.steps)
    assert any(step.step_type.value == "action_readiness_repairable" for step in trace_obj.steps)
    assert any(step.step_type.value == "input_completion_required" for step in trace_obj.steps)
    router.executor.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_readiness_blocked_pre_execution_stops_incompatible_macro_tool():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_readiness_gating = True

    router = make_router(
        llm_response=LLMResponse(
            content="call macro",
            tool_calls=[ToolCall(id="c1", name="calculate_macro_emission", arguments={"pollutants": ["CO2"]})],
        )
    )
    router.memory = FakeMemory(
        fact_memory={
            "active_file": "/tmp/traj.csv",
            "file_analysis": _micro_file_analysis(),
            "recent_vehicle": "Passenger Car",
        }
    )

    state = TaskState.initialize(
        user_message="对这个轨迹文件直接做宏观排放",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    trace_obj = Trace.start(session_id="test-session")

    await router._state_handle_input(state, trace_obj=trace_obj)
    await router._state_handle_grounded(state, trace_obj=trace_obj)
    await router._state_handle_executing(state, trace_obj=trace_obj)
    response = await router._state_build_response(state, "对这个轨迹文件直接做宏观排放", trace_obj=trace_obj)

    assert state.execution.blocked_info is not None
    assert state.execution.blocked_info["status"] == "blocked"
    assert state.execution.blocked_info["reason_code"] == "incompatible_task_type"
    assert "不匹配" in response.text
    assert any(step.step_type.value == "action_readiness_blocked" for step in trace_obj.steps)
    router.executor.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_readiness_repairable_pre_execution_stops_macro_when_required_field_missing():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_readiness_gating = True
    config.readiness_repairable_enabled = True

    router = make_router(
        llm_response=LLMResponse(
            content="call macro",
            tool_calls=[ToolCall(id="c1", name="calculate_macro_emission", arguments={"pollutants": ["CO2"]})],
        )
    )
    router.memory = FakeMemory(
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=False, missing_flow=True),
        }
    )

    state = TaskState.initialize(
        user_message="先算排放",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    trace_obj = Trace.start(session_id="test-session")

    await router._state_handle_input(state, trace_obj=trace_obj)
    await router._state_handle_grounded(state, trace_obj=trace_obj)
    await router._state_handle_executing(state, trace_obj=trace_obj)
    response = await router._state_build_response(state, "先算排放", trace_obj=trace_obj)

    assert state.stage == TaskStage.NEEDS_INPUT_COMPLETION
    assert state.active_input_completion is not None
    assert state.execution.blocked_info is not None
    assert state.execution.blocked_info["status"] == "repairable"
    assert state.execution.blocked_info["reason_code"] == "missing_required_fields"
    assert "1500" in response.text
    assert any(step.step_type.value == "action_readiness_repairable" for step in trace_obj.steps)
    assert any(step.step_type.value == "input_completion_required" for step in trace_obj.steps)
    router.executor.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_input_completion_uniform_scalar_success_restores_current_task_context():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_readiness_gating = True
    config.enable_input_completion_flow = True

    router = make_router(
        llm_response=LLMResponse(
            content="call macro",
            tool_calls=[ToolCall(id="c1", name="calculate_macro_emission", arguments={"pollutants": ["CO2"]})],
        ),
        executor_result=make_emission_result(),
    )
    first_response = LLMResponse(
        content="call macro",
        tool_calls=[ToolCall(id="c1", name="calculate_macro_emission", arguments={"pollutants": ["CO2"]})],
    )
    second_response = LLMResponse(
        content="retry macro",
        tool_calls=[ToolCall(id="c2", name="calculate_macro_emission", arguments={"pollutants": ["CO2"]})],
    )
    final_response = LLMResponse(content="排放计算已完成")
    router.llm.chat_with_tools = AsyncMock(side_effect=[first_response, second_response, final_response])
    router.memory = FakeMemory(
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=False, missing_flow=True),
        }
    )

    first_state = TaskState.initialize(
        user_message="先算排放",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    first_state.set_plan(
        ExecutionPlan(
            goal="Compute macro emissions",
            steps=[PlanStep(step_id="s1", tool_name="calculate_macro_emission", produces=["emission"])],
        )
    )
    first_trace = Trace.start(session_id="test-session")

    await router._state_handle_input(first_state, trace_obj=first_trace)
    await router._state_handle_grounded(first_state, trace_obj=first_trace)
    await router._state_handle_executing(first_state, trace_obj=first_trace)

    assert first_state.stage == TaskStage.NEEDS_INPUT_COMPLETION

    second_state = TaskState.initialize(
        user_message="全部设为1500",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    second_trace = Trace.start(session_id="test-session")

    await router._state_handle_input(second_state, trace_obj=second_trace)
    assert second_state.input_completion_overrides["traffic_flow_vph"]["value"] == 1500.0
    assert second_state.continuation is not None
    assert second_state.continuation.signal == "input_completion_resume"
    assert second_state.stage == TaskStage.GROUNDED

    await router._state_handle_grounded(second_state, trace_obj=second_trace)
    await router._state_handle_executing(second_state, trace_obj=second_trace)

    assert second_state.stage == TaskStage.DONE
    router.executor.execute.assert_awaited_once()
    execute_kwargs = router.executor.execute.await_args.kwargs
    assert execute_kwargs["arguments"]["_input_completion_overrides"]["traffic_flow_vph"]["value"] == 1500.0
    assert any(step.step_type.value == "input_completion_confirmed" for step in second_trace.steps)
    assert any(step.step_type.value == "input_completion_applied" for step in second_trace.steps)


@pytest.mark.anyio
async def test_explicit_new_task_overrides_pending_input_completion():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_readiness_gating = True
    config.enable_input_completion_flow = True

    router = make_router(
        llm_response=LLMResponse(
            content="call macro",
            tool_calls=[ToolCall(id="c1", name="calculate_macro_emission", arguments={"pollutants": ["CO2"]})],
        ),
    )
    router.memory = FakeMemory(
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=False, missing_flow=True),
        }
    )

    first_state = TaskState.initialize(
        user_message="先算排放",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    first_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(first_state, trace_obj=first_trace)
    await router._state_handle_grounded(first_state, trace_obj=first_trace)
    await router._state_handle_executing(first_state, trace_obj=first_trace)

    assert first_state.stage == TaskStage.NEEDS_INPUT_COMPLETION

    router.llm.chat_with_tools = AsyncMock(return_value=LLMResponse(content="new task answer"))
    second_state = TaskState.initialize(
        user_message="现在帮我做另一个任务，不要管前面的",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    second_trace = Trace.start(session_id="test-session")

    await router._state_handle_input(second_state, trace_obj=second_trace)

    assert second_state.stage == TaskStage.DONE
    assert second_state.active_input_completion is None
    assert second_state.input_completion_overrides == {}
    assert router._ensure_live_input_completion_bundle()["active_request"] is None
    assert any(step.step_type.value == "input_completion_rejected" for step in second_trace.steps)


@pytest.mark.anyio
async def test_file_relationship_replace_primary_file_supersedes_pending_completion():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_readiness_gating = True
    config.enable_input_completion_flow = True
    config.enable_file_relationship_resolution = True

    router = make_router(
        llm_response=LLMResponse(
            content="call macro",
            tool_calls=[ToolCall(id="c1", name="calculate_macro_emission", arguments={"pollutants": ["CO2"]})],
        ),
    )
    router.memory = FakeMemory(
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=False, missing_flow=True),
        }
    )

    first_state = TaskState.initialize(
        user_message="先算排放",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    first_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(first_state, trace_obj=first_trace)
    await router._state_handle_grounded(first_state, trace_obj=first_trace)
    await router._state_handle_executing(first_state, trace_obj=first_trace)

    assert first_state.stage == TaskStage.NEEDS_INPUT_COMPLETION
    router._ensure_live_input_completion_bundle()["overrides"] = {
        "traffic_flow_vph": {
            "mode": "uniform_scalar",
            "value": 1500.0,
            "source": "input_completion",
        }
    }
    router._analyze_file = AsyncMock(return_value=_macro_file_analysis(has_geometry=True))
    router.llm.chat_json = AsyncMock(
        return_value={
            "relationship_type": "replace_primary_file",
            "confidence": 0.94,
            "reason": "The user explicitly says the previous file was incorrect and asks to use the newly uploaded file.",
            "should_supersede_pending_completion": True,
            "should_reset_recovery_context": True,
            "should_preserve_residual_workflow": False,
            "affected_contexts": [
                "primary_file",
                "pending_completion",
                "completion_overrides",
                "residual_workflow",
            ],
        }
    )

    second_state = TaskState.initialize(
        user_message="刚刚发错了，用这个新的算",
        file_path="/tmp/roads_new.csv",
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    second_trace = Trace.start(session_id="test-session")

    await router._state_handle_input(second_state, trace_obj=second_trace)

    assert second_state.latest_file_relationship_decision is not None
    assert second_state.latest_file_relationship_decision.relationship_type.value == "replace_primary_file"
    assert second_state.active_input_completion is None
    assert second_state.input_completion_overrides == {}
    assert router._ensure_live_input_completion_bundle()["active_request"] is None
    assert router._ensure_live_input_completion_bundle()["overrides"] == {}
    assert second_state.file_context.file_path == "/tmp/roads_new.csv"
    assert second_state.file_context.grounded is True
    assert second_state.stage == TaskStage.GROUNDED
    assert any(step.step_type.value == "file_relationship_resolution_decided" for step in second_trace.steps)
    assert any(step.step_type.value == "file_relationship_transition_applied" for step in second_trace.steps)


@pytest.mark.anyio
async def test_file_relationship_attach_supporting_file_preserves_primary_context():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_readiness_gating = True
    config.enable_input_completion_flow = True
    config.enable_geometry_recovery_path = True
    config.enable_file_relationship_resolution = True

    router = make_router(
        llm_response=LLMResponse(
            content="call render",
            tool_calls=[ToolCall(id="c1", name="render_spatial_map", arguments={"layer_type": "emission"})],
        )
    )
    router._analyze_file = AsyncMock(return_value=_supporting_spatial_geojson_analysis())

    emission_result = make_emission_result()
    for row in emission_result["data"]["results"]:
        row["geometry"] = None
    router._ensure_context_store().store_result("calculate_macro_emission", emission_result)
    router.memory = FakeMemory(
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=False),
        }
    )

    first_state = TaskState.initialize(
        user_message="帮我画地图",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    first_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(first_state, trace_obj=first_trace)
    await router._state_handle_grounded(first_state, trace_obj=first_trace)
    await router._state_handle_executing(first_state, trace_obj=first_trace)
    assert first_state.stage == TaskStage.NEEDS_INPUT_COMPLETION

    router.llm.chat_json = AsyncMock(
        return_value={
            "relationship_type": "attach_supporting_file",
            "confidence": 0.89,
            "reason": "The user described the upload as a supporting GIS file for the current map workflow.",
            "should_supersede_pending_completion": False,
            "should_reset_recovery_context": False,
            "should_preserve_residual_workflow": True,
            "affected_contexts": [
                "supporting_file_context",
                "geometry_recovery",
                "residual_workflow",
            ],
        }
    )

    second_state = TaskState.initialize(
        user_message="这是配套的 GIS 文件",
        file_path="/tmp/roads.geojson",
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    second_trace = Trace.start(session_id="test-session")

    await router._state_handle_input(second_state, trace_obj=second_trace)

    assert second_state.latest_file_relationship_decision is not None
    assert second_state.latest_file_relationship_decision.relationship_type.value == "attach_supporting_file"
    assert second_state.file_context.file_path == "/tmp/roads.csv"
    assert second_state.supporting_spatial_input is not None
    assert second_state.supporting_spatial_input.file_name == "roads.geojson"
    assert second_state.geometry_recovery_context is not None
    assert second_state.stage == TaskStage.DONE
    assert any(step.step_type.value == "file_relationship_transition_applied" for step in second_trace.steps)
    assert any(step.step_type.value == "geometry_recovery_resumed" for step in second_trace.steps)


@pytest.mark.anyio
async def test_file_relationship_resolution_skips_plain_continuation_without_upload():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_file_relationship_resolution = True

    router = make_router(llm_response=LLMResponse(content="unused"))
    router.memory = FakeMemory(
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=True),
        }
    )

    state = TaskState.initialize(
        user_message="还是按原来的算",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    trace_obj = Trace.start(session_id="test-session")

    await router._state_handle_input(state, trace_obj=trace_obj)

    assert router.llm.chat_json.await_count == 0
    assert any(step.step_type.value == "file_relationship_resolution_skipped" for step in trace_obj.steps)


@pytest.mark.anyio
async def test_file_relationship_resolution_asks_clarify_for_ambiguous_upload():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_file_relationship_resolution = True

    router = make_router(llm_response=LLMResponse(content="unused"))
    router.memory = FakeMemory(
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=True),
        }
    )
    router._analyze_file = AsyncMock(return_value=_macro_file_analysis(has_geometry=True))
    router.llm.chat_json = AsyncMock(
        return_value={
            "relationship_type": "ask_clarify",
            "confidence": 0.41,
            "reason": "The new upload was referenced, but the user did not specify whether it replaces or supplements the current file.",
        }
    )

    state = TaskState.initialize(
        user_message="用这个吧",
        file_path="/tmp/roads_new.csv",
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    trace_obj = Trace.start(session_id="test-session")

    await router._state_handle_input(state, trace_obj=trace_obj)

    assert state.stage == TaskStage.NEEDS_CLARIFICATION
    assert state.pending_file_relationship_upload is not None
    assert state.pending_file_relationship_upload.file_path == "/tmp/roads_new.csv"
    assert state.file_context.file_path == "/tmp/roads.csv"
    assert state.awaiting_file_relationship_clarification is True
    assert "替换主文件" in (state.control.clarification_question or "")
    assert router._ensure_live_file_relationship_bundle()["awaiting_clarification"] is True
    assert any(step.step_type.value == "file_relationship_resolution_decided" for step in trace_obj.steps)


@pytest.mark.anyio
async def test_run_state_loop_preserves_primary_memory_when_supporting_file_attaches():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_readiness_gating = True
    config.enable_input_completion_flow = True
    config.enable_geometry_recovery_path = True
    config.enable_file_relationship_resolution = True

    router = make_router(
        llm_response=LLMResponse(
            content="call render",
            tool_calls=[ToolCall(id="c1", name="render_spatial_map", arguments={"layer_type": "emission"})],
        )
    )
    router._analyze_file = AsyncMock(return_value=_supporting_spatial_geojson_analysis())

    emission_result = make_emission_result()
    for row in emission_result["data"]["results"]:
        row["geometry"] = None
    router._ensure_context_store().store_result("calculate_macro_emission", emission_result)
    router.memory = FakeMemory(
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=False),
        }
    )

    first_state = TaskState.initialize(
        user_message="帮我画地图",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    first_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(first_state, trace_obj=first_trace)
    await router._state_handle_grounded(first_state, trace_obj=first_trace)
    await router._state_handle_executing(first_state, trace_obj=first_trace)

    router.llm.chat_json = AsyncMock(
        return_value={
            "relationship_type": "attach_supporting_file",
            "confidence": 0.88,
            "reason": "The upload is a supporting GIS file for the current geometry-recovery path.",
            "should_preserve_residual_workflow": True,
            "affected_contexts": ["supporting_file_context", "geometry_recovery", "residual_workflow"],
        }
    )

    response = await router._run_state_loop(
        user_message="这是配套的 GIS 文件",
        file_path="/tmp/roads.geojson",
    )

    assert "补充空间文件" in response.text
    assert router.memory.update_calls[-1]["file_path"] == "/tmp/roads.csv"
    assert router.memory.update_calls[-1]["file_analysis"]["file_path"] == "/tmp/roads.csv"


@pytest.mark.anyio
async def test_supplemental_merge_executes_and_restores_resumable_workflow(tmp_path):
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_readiness_gating = True
    config.enable_input_completion_flow = True
    config.enable_file_relationship_resolution = True
    config.enable_supplemental_column_merge = True
    config.supplemental_merge_require_readiness_refresh = True

    primary_path = tmp_path / "roads.csv"
    supplemental_path = tmp_path / "flow.csv"
    pd = pytest.importorskip("pandas")
    pd.DataFrame(
        {
            "segment_id": ["S1", "S2", "S3"],
            "length_km": [1.0, 1.5, 2.0],
            "avg_speed": [35, 40, 45],
        }
    ).to_csv(primary_path, index=False)
    pd.DataFrame(
        {
            "segment_id": ["S1", "S2", "S3"],
            "traffic_flow_vph": [1000, 1200, 1500],
        }
    ).to_csv(supplemental_path, index=False)

    primary_analysis = {
        "filename": primary_path.name,
        "file_path": str(primary_path),
        "task_type": "macro_emission",
        "confidence": 0.93,
        "columns": ["segment_id", "length_km", "avg_speed"],
        "column_mapping": {
            "segment_id": "link_id",
            "length_km": "link_length_km",
            "avg_speed": "avg_speed_kph",
        },
        "macro_mapping": {
            "segment_id": "link_id",
            "length_km": "link_length_km",
            "avg_speed": "avg_speed_kph",
        },
        "missing_field_diagnostics": {
            "task_type": "macro_emission",
            "status": "partial",
            "required_fields": ["link_id", "traffic_flow_vph", "avg_speed_kph"],
            "required_field_statuses": [
                {"field": "link_id", "status": "present", "mapped_from": "segment_id"},
                {"field": "traffic_flow_vph", "status": "missing", "mapped_from": None},
                {"field": "avg_speed_kph", "status": "present", "mapped_from": "avg_speed"},
            ],
            "missing_fields": [{"field": "traffic_flow_vph", "status": "missing"}],
            "derivable_opportunities": [],
        },
    }

    router = make_router(
        llm_response=LLMResponse(
            content="call macro",
            tool_calls=[ToolCall(id="c1", name="calculate_macro_emission", arguments={"pollutants": ["CO2"]})],
        ),
    )
    router.memory = FakeMemory(
        fact_memory={
            "active_file": str(primary_path),
            "file_analysis": primary_analysis,
        }
    )

    first_state = TaskState.initialize(
        user_message="先算排放",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    first_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(first_state, trace_obj=first_trace)
    await router._state_handle_grounded(first_state, trace_obj=first_trace)
    await router._state_handle_executing(first_state, trace_obj=first_trace)

    assert first_state.stage == TaskStage.NEEDS_INPUT_COMPLETION

    def analyze_side_effect(file_path: str):
        if str(file_path) == str(supplemental_path):
            return _supplemental_flow_analysis(str(supplemental_path))
        return _merged_macro_analysis(str(file_path))

    router._analyze_file = AsyncMock(side_effect=analyze_side_effect)
    router.llm.chat_json = AsyncMock(
        return_value={
            "relationship_type": "merge_supplemental_columns",
            "confidence": 0.91,
            "reason": "The new upload is a supplemental flow table for the current primary file.",
            "should_supersede_pending_completion": True,
            "should_preserve_residual_workflow": True,
            "affected_contexts": ["primary_file", "pending_completion", "supplemental_merge"],
        }
    )

    second_state = TaskState.initialize(
        user_message="这是补充流量表",
        file_path=str(supplemental_path),
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    second_trace = Trace.start(session_id="test-session")

    await router._state_handle_input(second_state, trace_obj=second_trace)

    assert second_state.stage == TaskStage.DONE
    assert second_state.latest_file_relationship_decision is not None
    assert second_state.latest_file_relationship_decision.relationship_type.value == "merge_supplemental_columns"
    assert second_state.latest_supplemental_merge_result is not None
    assert second_state.latest_supplemental_merge_result.success is True
    assert second_state.file_context.file_path != str(primary_path)
    assert second_state.file_context.grounded is True
    assert second_state.continuation is not None
    assert second_state.continuation.signal == "supplemental_merge_resume"
    assert second_state.file_context.missing_field_diagnostics["status"] == "complete"
    assert any(step.step_type.value == "supplemental_merge_applied" for step in second_trace.steps)
    assert any(step.step_type.value == "supplemental_merge_readiness_refreshed" for step in second_trace.steps)
    assert any(step.step_type.value == "supplemental_merge_resumed" for step in second_trace.steps)
    assert "可继续" in getattr(second_state, "_final_response_text", "")


@pytest.mark.anyio
async def test_supplemental_merge_needs_clarification_when_key_alignment_is_not_safe(tmp_path):
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_readiness_gating = True
    config.enable_input_completion_flow = True
    config.enable_file_relationship_resolution = True
    config.enable_supplemental_column_merge = True

    primary_path = tmp_path / "roads.csv"
    supplemental_path = tmp_path / "flow_no_key.csv"
    pd = pytest.importorskip("pandas")
    pd.DataFrame(
        {
            "segment_id": ["S1", "S2"],
            "length_km": [1.0, 1.5],
            "avg_speed": [35, 40],
        }
    ).to_csv(primary_path, index=False)
    pd.DataFrame(
        {
            "district": ["A", "B"],
            "traffic_flow_vph": [1000, 1200],
        }
    ).to_csv(supplemental_path, index=False)

    primary_analysis = {
        "filename": primary_path.name,
        "file_path": str(primary_path),
        "task_type": "macro_emission",
        "confidence": 0.93,
        "columns": ["segment_id", "length_km", "avg_speed"],
        "column_mapping": {
            "segment_id": "link_id",
            "length_km": "link_length_km",
            "avg_speed": "avg_speed_kph",
        },
        "macro_mapping": {
            "segment_id": "link_id",
            "length_km": "link_length_km",
            "avg_speed": "avg_speed_kph",
        },
        "missing_field_diagnostics": {
            "task_type": "macro_emission",
            "status": "partial",
            "required_fields": ["link_id", "traffic_flow_vph", "avg_speed_kph"],
            "required_field_statuses": [
                {"field": "link_id", "status": "present", "mapped_from": "segment_id"},
                {"field": "traffic_flow_vph", "status": "missing", "mapped_from": None},
                {"field": "avg_speed_kph", "status": "present", "mapped_from": "avg_speed"},
            ],
            "missing_fields": [{"field": "traffic_flow_vph", "status": "missing"}],
            "derivable_opportunities": [],
        },
    }

    router = make_router(
        llm_response=LLMResponse(
            content="call macro",
            tool_calls=[ToolCall(id="c1", name="calculate_macro_emission", arguments={"pollutants": ["CO2"]})],
        ),
    )
    router.memory = FakeMemory(
        fact_memory={
            "active_file": str(primary_path),
            "file_analysis": primary_analysis,
        }
    )

    first_state = TaskState.initialize(
        user_message="先算排放",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    first_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(first_state, trace_obj=first_trace)
    await router._state_handle_grounded(first_state, trace_obj=first_trace)
    await router._state_handle_executing(first_state, trace_obj=first_trace)

    router._analyze_file = AsyncMock(
        return_value={
            "filename": supplemental_path.name,
            "file_path": str(supplemental_path),
            "task_type": "macro_emission",
            "confidence": 0.81,
            "columns": ["district", "traffic_flow_vph"],
            "column_mapping": {"traffic_flow_vph": "traffic_flow_vph"},
            "macro_mapping": {"traffic_flow_vph": "traffic_flow_vph"},
        }
    )
    router.llm.chat_json = AsyncMock(
        return_value={
            "relationship_type": "merge_supplemental_columns",
            "confidence": 0.89,
            "reason": "The upload is intended to supplement a missing flow column in the current table.",
            "should_supersede_pending_completion": True,
            "affected_contexts": ["primary_file", "pending_completion", "supplemental_merge"],
        }
    )

    second_state = TaskState.initialize(
        user_message="把这个表并到当前文件里",
        file_path=str(supplemental_path),
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    second_trace = Trace.start(session_id="test-session")

    await router._state_handle_input(second_state, trace_obj=second_trace)

    assert second_state.stage == TaskStage.NEEDS_CLARIFICATION
    assert second_state.latest_supplemental_merge_plan is not None
    assert second_state.latest_supplemental_merge_plan.plan_status != "ready"
    assert "reliable key" in (second_state.control.clarification_question or "")
    assert second_state.file_context.file_path == str(primary_path)
    assert any(step.step_type.value == "supplemental_merge_failed" for step in second_trace.steps)


@pytest.mark.anyio
async def test_run_state_loop_updates_memory_to_merged_primary_file(tmp_path):
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_readiness_gating = True
    config.enable_input_completion_flow = True
    config.enable_file_relationship_resolution = True
    config.enable_supplemental_column_merge = True

    primary_path = tmp_path / "roads.csv"
    supplemental_path = tmp_path / "flow.csv"
    pd = pytest.importorskip("pandas")
    pd.DataFrame(
        {
            "segment_id": ["S1", "S2", "S3"],
            "length_km": [1.0, 1.5, 2.0],
            "avg_speed": [35, 40, 45],
        }
    ).to_csv(primary_path, index=False)
    pd.DataFrame(
        {
            "segment_id": ["S1", "S2", "S3"],
            "traffic_flow_vph": [1000, 1200, 1500],
        }
    ).to_csv(supplemental_path, index=False)

    primary_analysis = {
        "filename": primary_path.name,
        "file_path": str(primary_path),
        "task_type": "macro_emission",
        "confidence": 0.93,
        "columns": ["segment_id", "length_km", "avg_speed"],
        "column_mapping": {
            "segment_id": "link_id",
            "length_km": "link_length_km",
            "avg_speed": "avg_speed_kph",
        },
        "macro_mapping": {
            "segment_id": "link_id",
            "length_km": "link_length_km",
            "avg_speed": "avg_speed_kph",
        },
        "missing_field_diagnostics": {
            "task_type": "macro_emission",
            "status": "partial",
            "required_fields": ["link_id", "traffic_flow_vph", "avg_speed_kph"],
            "required_field_statuses": [
                {"field": "link_id", "status": "present", "mapped_from": "segment_id"},
                {"field": "traffic_flow_vph", "status": "missing", "mapped_from": None},
                {"field": "avg_speed_kph", "status": "present", "mapped_from": "avg_speed"},
            ],
            "missing_fields": [{"field": "traffic_flow_vph", "status": "missing"}],
            "derivable_opportunities": [],
        },
    }

    router = make_router(
        llm_response=LLMResponse(
            content="call macro",
            tool_calls=[ToolCall(id="c1", name="calculate_macro_emission", arguments={"pollutants": ["CO2"]})],
        ),
    )
    router.memory = FakeMemory(
        fact_memory={
            "active_file": str(primary_path),
            "file_analysis": primary_analysis,
        }
    )

    first_state = TaskState.initialize(
        user_message="先算排放",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    first_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(first_state, trace_obj=first_trace)
    await router._state_handle_grounded(first_state, trace_obj=first_trace)
    await router._state_handle_executing(first_state, trace_obj=first_trace)

    def analyze_side_effect(file_path: str):
        if str(file_path) == str(supplemental_path):
            return _supplemental_flow_analysis(str(supplemental_path))
        return _merged_macro_analysis(str(file_path))

    router._analyze_file = AsyncMock(side_effect=analyze_side_effect)
    router.llm.chat_json = AsyncMock(
        return_value={
            "relationship_type": "merge_supplemental_columns",
            "confidence": 0.9,
            "reason": "The upload is a supplemental table that should be joined into the current file.",
            "should_supersede_pending_completion": True,
            "affected_contexts": ["primary_file", "pending_completion", "supplemental_merge"],
        }
    )

    response = await router._run_state_loop(
        user_message="把这一列加上",
        file_path=str(supplemental_path),
    )

    assert "合并到当前主数据中" in response.text
    assert router.memory.update_calls[-1]["file_path"] != str(primary_path)
    assert router.memory.update_calls[-1]["file_analysis"]["supplemental_merge_result"]["success"] is True
    assert router.memory.update_calls[-1]["file_analysis"]["file_path"] == router.memory.update_calls[-1]["file_path"]


@pytest.mark.anyio
async def test_missing_geometry_completion_enables_geometry_recovery_path():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_readiness_gating = True
    config.enable_input_completion_flow = True
    config.enable_geometry_recovery_path = True

    router = make_router(
        llm_response=LLMResponse(
            content="call render",
            tool_calls=[ToolCall(id="c1", name="render_spatial_map", arguments={"layer_type": "emission"})],
        )
    )
    router._analyze_file = AsyncMock(return_value=_supporting_spatial_geojson_analysis())

    emission_result = make_emission_result()
    for row in emission_result["data"]["results"]:
        row["geometry"] = None
    router._ensure_context_store().store_result("calculate_macro_emission", emission_result)
    router.memory = FakeMemory(
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=False),
        }
    )

    first_state = TaskState.initialize(
        user_message="帮我画地图",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    first_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(first_state, trace_obj=first_trace)
    await router._state_handle_grounded(first_state, trace_obj=first_trace)
    await router._state_handle_executing(first_state, trace_obj=first_trace)
    assert first_state.stage == TaskStage.NEEDS_INPUT_COMPLETION

    second_state = TaskState.initialize(
        user_message="上传文件",
        file_path="/tmp/roads.geojson",
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    second_trace = Trace.start(session_id="test-session")

    await router._state_handle_input(second_state, trace_obj=second_trace)

    assert second_state.stage == TaskStage.DONE
    assert second_state.supporting_spatial_input is not None
    assert second_state.supporting_spatial_input.file_name == "roads.geojson"
    assert second_state.geometry_recovery_context is not None
    assert second_state.geometry_recovery_context.recovery_status == "resumable"
    assert second_state.residual_reentry_context is not None
    assert second_state.residual_reentry_context.reentry_target.target_action_id == "render_emission_map"
    assert second_state.geometry_readiness_refresh_result["after_status"] == "ready"
    router.executor.execute.assert_not_awaited()
    assert any(step.step_type.value == "geometry_completion_attached" for step in second_trace.steps)
    assert any(step.step_type.value == "geometry_re_grounding_applied" for step in second_trace.steps)
    assert any(step.step_type.value == "geometry_readiness_refreshed" for step in second_trace.steps)
    assert any(step.step_type.value == "geometry_recovery_resumed" for step in second_trace.steps)
    assert any(step.step_type.value == "residual_reentry_target_set" for step in second_trace.steps)


@pytest.mark.anyio
async def test_geometry_recovery_preserves_residual_workflow_until_next_turn():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_readiness_gating = True
    config.enable_input_completion_flow = True
    config.enable_geometry_recovery_path = True
    config.enable_repair_aware_continuation = False
    config.enable_workflow_templates = True

    router = make_router(
        llm_response=LLMResponse(
            content="call render",
            tool_calls=[ToolCall(id="c1", name="render_spatial_map", arguments={"layer_type": "emission"})],
        )
    )
    router._analyze_file = AsyncMock(return_value=_supporting_spatial_geojson_analysis())
    router.llm.chat_with_tools = AsyncMock(
        side_effect=[
            LLMResponse(
                content="call render",
                tool_calls=[ToolCall(id="c1", name="render_spatial_map", arguments={"layer_type": "emission"})],
            ),
            LLMResponse(
                content="call render again",
                tool_calls=[ToolCall(id="c2", name="render_spatial_map", arguments={"layer_type": "emission"})],
            ),
        ]
    )

    emission_result = make_emission_result()
    for row in emission_result["data"]["results"]:
        row["geometry"] = None
    router._ensure_context_store().store_result("calculate_macro_emission", emission_result)
    router.memory = FakeMemory(
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=False),
        }
    )

    first_state = TaskState.initialize(
        user_message="帮我画地图",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    first_state.set_plan(
        ExecutionPlan(
            goal="Render the emission map",
            steps=[PlanStep(step_id="s1", tool_name="render_spatial_map", produces=["visualization"])],
        )
    )
    first_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(first_state, trace_obj=first_trace)
    await router._state_handle_grounded(first_state, trace_obj=first_trace)
    await router._state_handle_executing(first_state, trace_obj=first_trace)
    assert first_state.stage == TaskStage.NEEDS_INPUT_COMPLETION

    second_state = TaskState.initialize(
        user_message="上传文件",
        file_path="/tmp/roads.geojson",
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    second_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(second_state, trace_obj=second_trace)

    continuation_bundle = router._ensure_live_continuation_bundle()
    assert second_state.stage == TaskStage.DONE
    assert continuation_bundle["plan"] is not None
    assert continuation_bundle["plan"]["steps"][0]["tool_name"] == "render_spatial_map"
    assert second_state.geometry_recovery_context is not None
    assert second_state.geometry_recovery_context.residual_plan_summary is not None

    third_state = TaskState.initialize(
        user_message="继续",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    third_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(third_state, trace_obj=third_trace)
    await router._state_handle_grounded(third_state, trace_obj=third_trace)

    assert third_state.continuation is not None
    assert third_state.continuation.signal == "geometry_recovery_resume"
    assert third_state.plan is not None
    assert third_state.plan.steps[0].tool_name == "render_spatial_map"
    assert third_state.reentry_bias_applied is True
    assert third_state.residual_reentry_context is not None
    assert third_state.residual_reentry_context.reentry_status == "bias_applied"
    assert any(step.step_type.value == "plan_continuation_decided" for step in third_trace.steps)
    assert any(step.step_type.value == "residual_reentry_decided" for step in third_trace.steps)
    assert any(step.step_type.value == "residual_reentry_injected" for step in third_trace.steps)
    assert any(step.step_type.value == "workflow_template_skipped" for step in third_trace.steps)
    injected_messages = router.llm.chat_with_tools.await_args_list[-1].kwargs["messages"]
    assert any(
        msg.get("role") == "system"
        and "Recovered workflow re-entry target" in msg.get("content", "")
        and "render_emission_map" in msg.get("content", "")
        for msg in injected_messages
    )


@pytest.mark.anyio
async def test_explicit_new_task_overrides_active_geometry_recovery_context():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_readiness_gating = True
    config.enable_input_completion_flow = True
    config.enable_geometry_recovery_path = True

    router = make_router(
        llm_response=LLMResponse(
            content="call render",
            tool_calls=[ToolCall(id="c1", name="render_spatial_map", arguments={"layer_type": "emission"})],
        )
    )
    router._analyze_file = AsyncMock(return_value=_supporting_spatial_geojson_analysis())

    emission_result = make_emission_result()
    for row in emission_result["data"]["results"]:
        row["geometry"] = None
    router._ensure_context_store().store_result("calculate_macro_emission", emission_result)
    router.memory = FakeMemory(
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=False),
        }
    )

    first_state = TaskState.initialize(
        user_message="帮我画地图",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    first_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(first_state, trace_obj=first_trace)
    await router._state_handle_grounded(first_state, trace_obj=first_trace)
    await router._state_handle_executing(first_state, trace_obj=first_trace)

    second_state = TaskState.initialize(
        user_message="上传文件",
        file_path="/tmp/roads.geojson",
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    second_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(second_state, trace_obj=second_trace)
    assert second_state.geometry_recovery_context is not None
    assert second_state.residual_reentry_context is not None

    router.llm.chat_with_tools = AsyncMock(return_value=LLMResponse(content="new task answer"))
    third_state = TaskState.initialize(
        user_message="现在做另一个任务，不要管前面的",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    third_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(third_state, trace_obj=third_trace)

    assert third_state.stage == TaskStage.DONE
    assert third_state.geometry_recovery_context is None
    assert third_state.supporting_spatial_input is None
    assert third_state.residual_reentry_context is None
    assert router._ensure_live_input_completion_bundle()["geometry_recovery_context"] is None
    assert router._ensure_live_input_completion_bundle()["supporting_spatial_input"] is None
    assert router._ensure_live_input_completion_bundle()["residual_reentry_context"] is None
    assert any(step.step_type.value == "residual_reentry_skipped" for step in third_trace.steps)


@pytest.mark.anyio
async def test_geometry_reentry_skips_when_recovered_target_is_no_longer_ready():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_readiness_gating = True
    config.enable_input_completion_flow = True
    config.enable_geometry_recovery_path = True
    config.enable_residual_reentry_controller = True

    router = make_router(
        llm_response=LLMResponse(
            content="call render",
            tool_calls=[ToolCall(id="c1", name="render_spatial_map", arguments={"layer_type": "emission"})],
        )
    )
    router._analyze_file = AsyncMock(return_value=_supporting_spatial_geojson_analysis())

    emission_result = make_emission_result()
    for row in emission_result["data"]["results"]:
        row["geometry"] = None
    router._ensure_context_store().store_result("calculate_macro_emission", emission_result)
    router.memory = FakeMemory(
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=False),
        }
    )

    first_state = TaskState.initialize(
        user_message="帮我画地图",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    first_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(first_state, trace_obj=first_trace)
    await router._state_handle_grounded(first_state, trace_obj=first_trace)
    await router._state_handle_executing(first_state, trace_obj=first_trace)

    second_state = TaskState.initialize(
        user_message="上传文件",
        file_path="/tmp/roads.geojson",
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    second_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(second_state, trace_obj=second_trace)
    assert second_state.residual_reentry_context is not None

    bundle = router._ensure_live_input_completion_bundle()
    bundle["recovered_file_context"] = _macro_file_analysis(has_geometry=False)

    third_state = TaskState.initialize(
        user_message="继续",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    third_trace = Trace.start(session_id="test-session")
    await router._state_handle_input(third_state, trace_obj=third_trace)

    assert third_state.residual_reentry_context is not None
    assert third_state.reentry_bias_applied is False
    assert third_state.residual_reentry_context.reentry_status == "stale"
    assert any(step.step_type.value == "residual_reentry_skipped" for step in third_trace.steps)


@pytest.mark.anyio
async def test_synthesis_no_longer_suggests_unsupported_spatial_actions_or_duplicate_download():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_capability_aware_synthesis = True
    config.enable_readiness_gating = True

    tool_call = ToolCall(
        id="call-macro",
        name="calculate_macro_emission",
        arguments={"pollutants": ["CO2"]},
    )
    emission_result = make_emission_result()
    for row in emission_result["data"]["results"]:
        row["geometry"] = None
    emission_result["data"]["download_file"] = {
        "path": "/tmp/emission.xlsx",
        "filename": "emission.xlsx",
    }

    router = make_router(
        llm_response=LLMResponse(content="先算排放", tool_calls=[tool_call]),
        executor_result=emission_result,
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=False),
        },
    )
    router.llm.chat_with_tools = AsyncMock(
        side_effect=[
            LLMResponse(content="先算排放", tool_calls=[tool_call]),
            LLMResponse(content="已完成，不再继续调用工具。"),
        ]
    )

    result = await router.chat("请先计算排放", trace={})

    assert "帮我可视化排放分布" not in result.text
    assert "帮我做扩散分析" not in result.text
    assert "导出 CSV" not in result.text
    assert "下载详细结果文件" not in result.text


@pytest.mark.anyio
async def test_artifact_memory_is_recorded_and_persisted_after_download_delivery():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_artifact_memory = True

    tool_call = ToolCall(
        id="call-macro",
        name="calculate_macro_emission",
        arguments={"pollutants": ["CO2"]},
    )
    emission_result = make_emission_result()
    emission_result["data"]["download_file"] = {
        "path": "/tmp/emission.xlsx",
        "filename": "emission.xlsx",
    }

    router = make_router(
        llm_response=LLMResponse(content="先算排放", tool_calls=[tool_call]),
        executor_result=emission_result,
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=False),
        },
    )
    router.llm.chat_with_tools = AsyncMock(
        side_effect=[
            LLMResponse(content="先算排放", tool_calls=[tool_call]),
            LLMResponse(content="已完成，不再继续调用工具。"),
        ]
    )

    await router.chat("请先计算排放", trace={})

    saved_analysis = router.memory.update_calls[-1]["file_analysis"]
    artifact_types = {
        item["artifact_type"]
        for item in saved_analysis["artifact_memory"]["artifacts"]
    }
    assert "detailed_csv" in artifact_types
    assert "quick_summary_text" in artifact_types
    assert saved_analysis["artifact_memory_summary"]["artifact_count"] >= 2


def test_artifact_memory_makes_download_action_already_provided_across_turns():
    artifact_memory = {
        "artifacts": [
            build_artifact_record(
                artifact_type=ArtifactType.DETAILED_CSV,
                delivery_turn_index=1,
                source_tool_name="calculate_macro_emission",
                summary="已提供可下载的详细结果文件。",
                related_task_type="macro_emission",
            ).to_dict()
        ]
    }
    router = make_router(
        llm_response=LLMResponse(content="unused"),
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": {
                **_macro_file_analysis(has_geometry=False),
                "artifact_memory": artifact_memory,
            },
        },
    )

    state = TaskState.initialize(
        user_message="继续",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id=router.session_id,
    )
    assessment = router._build_readiness_assessment(
        [],
        state=state,
        frontend_payloads=None,
        purpose="synthesis_guidance",
    )

    assert assessment is not None
    affordance = assessment.get_action("download_detailed_csv")
    assert affordance is not None
    assert affordance.status == ReadinessStatus.ALREADY_PROVIDED
    assert affordance.provided_artifact is not None
    assert affordance.provided_artifact.kind == "artifact_memory"


@pytest.mark.anyio
async def test_dependency_blocked_triggers_bounded_repair_without_auto_execution():
    config = get_config()
    previous = config.enable_lightweight_planning
    previous_repair = config.enable_bounded_plan_repair
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_lightweight_planning = True
    config.enable_bounded_plan_repair = True

    router = make_router(llm_response=LLMResponse(content="unused"))
    router.llm.chat_json = AsyncMock(
        side_effect=[
            {
                "goal": "Render hotspot map",
                "steps": [
                    {
                        "step_id": "s1",
                        "tool_name": "render_spatial_map",
                        "depends_on": ["hotspot"],
                        "argument_hints": {"layer_type": "hotspot"},
                    },
                ],
            },
            {
                "trigger_type": "dependency_blocked",
                "trigger_reason": "Missing hotspot result.",
                "action_type": "DROP_BLOCKED_STEP",
                "target_step_id": "s1",
                "affected_step_ids": ["s1"],
                "planner_notes": "Drop the blocked hotspot render step and keep the finished history.",
                "is_applicable": True,
                "patch": {"skip_step_ids": ["s1"]},
            },
        ]
    )
    router.llm.chat_with_tools = AsyncMock(
        return_value=LLMResponse(
            content="call render",
            tool_calls=[ToolCall(id="c1", name="render_spatial_map", arguments={"layer_type": "hotspot"})],
        )
    )

    state = TaskState.initialize(
        user_message="渲染热点地图",
        file_path=None,
        memory_dict={},
        session_id="test-session",
    )
    trace_obj = Trace.start(session_id="test-session")

    try:
        await router._state_handle_input(state, trace_obj=trace_obj)
        await router._state_handle_grounded(state, trace_obj=trace_obj)
        await router._state_handle_executing(state, trace_obj=trace_obj)
        response = await router._state_build_response(state, "渲染热点地图", trace_obj=trace_obj)
    finally:
        config.enable_lightweight_planning = previous
        config.enable_bounded_plan_repair = previous_repair

    assert state.plan is not None
    assert state.plan.steps[0].status == PlanStepStatus.SKIPPED
    assert state.plan.steps[0].repair_action == "DROP_BLOCKED_STEP"
    assert state.repair_history
    assert state.execution.blocked_info is not None
    assert "No repair step was auto-executed" in response.text
    assert any(step.step_type.value == "dependency_blocked" for step in trace_obj.steps)
    assert any(step.step_type.value == "plan_repair_triggered" for step in trace_obj.steps)
    assert any(step.step_type.value == "plan_repair_applied" for step in trace_obj.steps)
    router.executor.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_plan_exhausted_deviation_triggers_repair_and_stops_before_unplanned_execution():
    config = get_config()
    previous = config.enable_lightweight_planning
    previous_repair = config.enable_bounded_plan_repair
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_lightweight_planning = True
    config.enable_bounded_plan_repair = True

    router = make_router(llm_response=LLMResponse(content="unused"))
    router.llm.chat_json = AsyncMock(
        side_effect=[
            {
                "goal": "Compute emissions",
                "steps": [
                    {"step_id": "s1", "tool_name": "calculate_macro_emission", "produces": ["emission"]},
                ],
            },
            {
                "trigger_type": "plan_deviation",
                "trigger_reason": "Plan exhausted after macro emission.",
                "action_type": "APPEND_RECOVERY_STEP",
                "target_step_id": "s1",
                "affected_step_ids": ["repair_s1"],
                "planner_notes": "Append a knowledge lookup as a bounded recovery step instead of executing it immediately.",
                "is_applicable": True,
                "patch": {
                    "append_steps": [
                        {
                            "step_id": "repair_s1",
                            "tool_name": "query_knowledge",
                            "purpose": "Provide follow-up explanation after the completed emission step.",
                            "depends_on": [],
                            "produces": ["knowledge"],
                            "argument_hints": {"question": "Explain next steps after emission analysis"},
                        }
                    ]
                },
            },
        ]
    )
    router.llm.chat_with_tools = AsyncMock(
        side_effect=[
            LLMResponse(
                content="call macro",
                tool_calls=[ToolCall(id="c1", name="calculate_macro_emission", arguments={"pollutants": ["CO2"]})],
            ),
            LLMResponse(
                content="call knowledge",
                tool_calls=[ToolCall(id="c2", name="query_knowledge", arguments={"question": "next steps"})],
            ),
        ]
    )
    router.executor.execute = AsyncMock(side_effect=[make_emission_result()])

    state = TaskState.initialize(
        user_message="先算排放，再继续说明下一步",
        file_path=None,
        memory_dict={},
        session_id="test-session",
    )
    trace_obj = Trace.start(session_id="test-session")

    try:
        await router._state_handle_input(state, trace_obj=trace_obj)
        await router._state_handle_grounded(state, trace_obj=trace_obj)
        await router._state_handle_executing(state, trace_obj=trace_obj)
        response = await router._state_build_response(state, "先算排放，再继续说明下一步", trace_obj=trace_obj)
    finally:
        config.enable_lightweight_planning = previous
        config.enable_bounded_plan_repair = previous_repair

    assert state.plan is not None
    assert state.plan.steps[0].status == PlanStepStatus.COMPLETED
    assert state.plan.steps[1].tool_name == "query_knowledge"
    assert state.plan.steps[1].repair_action == "APPEND_RECOVERY_STEP"
    assert state.plan.steps[1].status == PlanStepStatus.READY
    assert state.repair_history
    assert "No repair step was auto-executed" in response.text
    assert any(
        step.input_summary.get("deviation_type") == "plan_exhausted"
        for step in trace_obj.steps
        if step.step_type.value == "plan_deviation" and step.input_summary
    )
    assert any(step.step_type.value == "plan_repair_triggered" for step in trace_obj.steps)
    assert any(step.step_type.value == "plan_repair_applied" for step in trace_obj.steps)
    assert router.executor.execute.await_count == 1


@pytest.mark.anyio
async def test_invalid_repair_falls_back_without_mutating_original_plan():
    config = get_config()
    previous = config.enable_lightweight_planning
    previous_repair = config.enable_bounded_plan_repair
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_lightweight_planning = True
    config.enable_bounded_plan_repair = True

    router = make_router(llm_response=LLMResponse(content="unused"))
    router.llm.chat_json = AsyncMock(
        side_effect=[
            {
                "goal": "Render hotspot map",
                "steps": [
                    {
                        "step_id": "s1",
                        "tool_name": "render_spatial_map",
                        "depends_on": ["hotspot"],
                        "argument_hints": {"layer_type": "hotspot"},
                    },
                ],
            },
            {
                "trigger_type": "dependency_blocked",
                "trigger_reason": "Missing hotspot result.",
                "action_type": "KEEP_REMAINING",
                "target_step_id": "s1",
                "affected_step_ids": ["s1"],
                "planner_notes": "Keep the blocked residual plan unchanged.",
                "is_applicable": True,
            },
        ]
    )
    router.llm.chat_with_tools = AsyncMock(
        return_value=LLMResponse(
            content="call render",
            tool_calls=[ToolCall(id="c1", name="render_spatial_map", arguments={"layer_type": "hotspot"})],
        )
    )

    state = TaskState.initialize(
        user_message="渲染热点地图",
        file_path=None,
        memory_dict={},
        session_id="test-session",
    )
    trace_obj = Trace.start(session_id="test-session")

    try:
        await router._state_handle_input(state, trace_obj=trace_obj)
        await router._state_handle_grounded(state, trace_obj=trace_obj)
        await router._state_handle_executing(state, trace_obj=trace_obj)
        response = await router._state_build_response(state, "渲染热点地图", trace_obj=trace_obj)
    finally:
        config.enable_lightweight_planning = previous
        config.enable_bounded_plan_repair = previous_repair

    assert state.plan is not None
    assert state.plan.steps[0].status == PlanStepStatus.BLOCKED
    assert not state.repair_history
    assert any(step.step_type.value == "plan_repair_failed" for step in trace_obj.steps)
    assert "original residual plan was preserved" in response.text
    router.executor.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_repair_applied_next_turn_continues_on_residual_plan_without_replan():
    config = get_config()
    previous_planning = config.enable_lightweight_planning
    previous_repair = config.enable_bounded_plan_repair
    previous_continuation = config.enable_repair_aware_continuation
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_lightweight_planning = True
    config.enable_bounded_plan_repair = True
    config.enable_repair_aware_continuation = True

    router = make_router(llm_response=LLMResponse(content="unused"))
    router.llm.chat_json = AsyncMock(
        side_effect=[
            {
                "goal": "Calculate emission then render hotspot map",
                "steps": [
                    {"step_id": "s1", "tool_name": "calculate_macro_emission", "produces": ["emission"]},
                    {
                        "step_id": "s2",
                        "tool_name": "render_spatial_map",
                        "depends_on": ["hotspot"],
                        "argument_hints": {"layer_type": "hotspot"},
                    },
                ],
            },
            {
                "trigger_type": "dependency_blocked",
                "trigger_reason": "Need a hotspot result before rendering the hotspot layer.",
                "action_type": "REPLACE_STEP",
                "target_step_id": "s2",
                "affected_step_ids": ["s2", "repair_s1"],
                "planner_notes": "Replace the blocked hotspot render step with dispersion so the residual workflow can continue.",
                "is_applicable": True,
                "patch": {
                    "replacement_step": {
                        "step_id": "repair_s1",
                        "tool_name": "calculate_dispersion",
                        "purpose": "Compute dispersion before hotspot rendering resumes.",
                        "depends_on": ["emission"],
                        "produces": ["dispersion"],
                    }
                },
            },
        ]
    )
    router.llm.chat_with_tools = AsyncMock(
        side_effect=[
            LLMResponse(
                content="call macro",
                tool_calls=[ToolCall(id="c1", name="calculate_macro_emission", arguments={"pollutants": ["CO2"]})],
            ),
            LLMResponse(
                content="call blocked render",
                tool_calls=[ToolCall(id="c2", name="render_spatial_map", arguments={"layer_type": "hotspot"})],
            ),
            LLMResponse(
                content="continue with dispersion",
                tool_calls=[ToolCall(id="c3", name="calculate_dispersion", arguments={"pollutant": "CO2"})],
            ),
        ]
    )
    router.executor.execute = AsyncMock(side_effect=[make_emission_result()])

    try:
        await router.chat("先算排放，再渲染热点图", trace={})

        next_turn_state = TaskState.initialize(
            user_message="继续",
            file_path=None,
            memory_dict=router.memory.get_fact_memory(),
            session_id="test-session",
        )
        trace_obj = Trace.start(session_id="test-session")
        await router._state_handle_input(next_turn_state, trace_obj=trace_obj)
    finally:
        config.enable_lightweight_planning = previous_planning
        config.enable_bounded_plan_repair = previous_repair
        config.enable_repair_aware_continuation = previous_continuation

    assert next_turn_state.plan is not None
    assert next_turn_state.continuation is not None
    assert next_turn_state.continuation.should_continue is True
    assert next_turn_state.continuation.should_replan is False
    assert next_turn_state.get_next_planned_step().tool_name == "calculate_dispersion"
    assert next_turn_state.execution.selected_tool == "calculate_dispersion"
    assert any(step.step_type.value == "plan_continuation_decided" for step in trace_obj.steps)
    assert any(step.step_type.value == "plan_continuation_injected" for step in trace_obj.steps)
    assert router.llm.chat_json.await_count == 2

    injected_messages = router.llm.chat_with_tools.await_args_list[-1].kwargs["messages"]
    assert any(
        msg.get("role") == "system"
        and "Residual workflow continuation" in msg.get("content", "")
        and "repair_s1 -> calculate_dispersion" in msg.get("content", "")
        for msg in injected_messages
    )


@pytest.mark.anyio
async def test_dependency_blocked_residual_state_informs_next_turn_continuation():
    config = get_config()
    previous_planning = config.enable_lightweight_planning
    previous_repair = config.enable_bounded_plan_repair
    previous_continuation = config.enable_repair_aware_continuation
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_lightweight_planning = True
    config.enable_bounded_plan_repair = False
    config.enable_repair_aware_continuation = True

    router = make_router(llm_response=LLMResponse(content="unused"))
    router.llm.chat_json = AsyncMock(
        return_value={
            "goal": "Render hotspot map",
            "steps": [
                {
                    "step_id": "s1",
                    "tool_name": "render_spatial_map",
                    "depends_on": ["hotspot"],
                    "argument_hints": {"layer_type": "hotspot"},
                },
            ],
        }
    )
    router.llm.chat_with_tools = AsyncMock(
        side_effect=[
            LLMResponse(
                content="call blocked render",
                tool_calls=[ToolCall(id="c1", name="render_spatial_map", arguments={"layer_type": "hotspot"})],
            ),
            LLMResponse(
                content="continue with dispersion",
                tool_calls=[ToolCall(id="c2", name="calculate_dispersion", arguments={"pollutant": "CO2"})],
            ),
        ]
    )

    try:
        await router.chat("渲染热点地图", trace={})

        next_turn_state = TaskState.initialize(
            user_message="那先做扩散再渲染",
            file_path=None,
            memory_dict=router.memory.get_fact_memory(),
            session_id="test-session",
        )
        trace_obj = Trace.start(session_id="test-session")
        await router._state_handle_input(next_turn_state, trace_obj=trace_obj)
    finally:
        config.enable_lightweight_planning = previous_planning
        config.enable_bounded_plan_repair = previous_repair
        config.enable_repair_aware_continuation = previous_continuation

    assert next_turn_state.plan is not None
    assert next_turn_state.continuation is not None
    assert next_turn_state.continuation.should_continue is True
    assert "Cannot execute render_spatial_map" in (next_turn_state.continuation.latest_blocked_reason or "")
    assert next_turn_state.execution.selected_tool == "calculate_dispersion"
    assert any(step.step_type.value == "plan_continuation_decided" for step in trace_obj.steps)
    assert any(step.step_type.value == "plan_continuation_injected" for step in trace_obj.steps)

    injected_messages = router.llm.chat_with_tools.await_args_list[-1].kwargs["messages"]
    assert any(
        msg.get("role") == "system"
        and "Latest blocked reason" in msg.get("content", "")
        and "render_spatial_map" in msg.get("content", "")
        for msg in injected_messages
    )


@pytest.mark.anyio
async def test_new_task_override_skips_residual_plan_continuation():
    config = get_config()
    previous_planning = config.enable_lightweight_planning
    previous_repair = config.enable_bounded_plan_repair
    previous_continuation = config.enable_repair_aware_continuation
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_lightweight_planning = True
    config.enable_bounded_plan_repair = True
    config.enable_repair_aware_continuation = True

    router = make_router(llm_response=LLMResponse(content="unused"))
    router.llm.chat_json = AsyncMock(
        side_effect=[
            {
                "goal": "Calculate emission then render hotspot map",
                "steps": [
                    {"step_id": "s1", "tool_name": "calculate_macro_emission", "produces": ["emission"]},
                    {
                        "step_id": "s2",
                        "tool_name": "render_spatial_map",
                        "depends_on": ["hotspot"],
                        "argument_hints": {"layer_type": "hotspot"},
                    },
                ],
            },
            {
                "trigger_type": "dependency_blocked",
                "trigger_reason": "Need a hotspot result before rendering the hotspot layer.",
                "action_type": "REPLACE_STEP",
                "target_step_id": "s2",
                "affected_step_ids": ["s2", "repair_s1"],
                "planner_notes": "Replace the blocked hotspot render step with dispersion.",
                "is_applicable": True,
                "patch": {
                    "replacement_step": {
                        "step_id": "repair_s1",
                        "tool_name": "calculate_dispersion",
                        "depends_on": ["emission"],
                        "produces": ["dispersion"],
                    }
                },
            },
        ]
    )
    router.llm.chat_with_tools = AsyncMock(
        side_effect=[
            LLMResponse(
                content="call macro",
                tool_calls=[ToolCall(id="c1", name="calculate_macro_emission", arguments={"pollutants": ["CO2"]})],
            ),
            LLMResponse(
                content="call blocked render",
                tool_calls=[ToolCall(id="c2", name="render_spatial_map", arguments={"layer_type": "hotspot"})],
            ),
            LLMResponse(content="新的问题，直接回答。"),
        ]
    )
    router.executor.execute = AsyncMock(side_effect=[make_emission_result()])

    try:
        await router.chat("先算排放，再渲染热点图", trace={})

        next_turn_state = TaskState.initialize(
            user_message="换个任务，直接回答这个新问题",
            file_path=None,
            memory_dict=router.memory.get_fact_memory(),
            session_id="test-session",
        )
        trace_obj = Trace.start(session_id="test-session")
        await router._state_handle_input(next_turn_state, trace_obj=trace_obj)
    finally:
        config.enable_lightweight_planning = previous_planning
        config.enable_bounded_plan_repair = previous_repair
        config.enable_repair_aware_continuation = previous_continuation

    assert next_turn_state.plan is None
    assert next_turn_state.continuation is not None
    assert next_turn_state.continuation.residual_plan_exists is True
    assert next_turn_state.continuation.should_continue is False
    assert next_turn_state.continuation.new_task_override is True
    assert next_turn_state.stage == TaskStage.DONE
    assert next_turn_state.execution.tool_results[0]["no_tool"] is True
    assert any(step.step_type.value == "plan_continuation_skipped" for step in trace_obj.steps)


@pytest.mark.anyio
async def test_ambiguous_input_without_residual_alignment_skips_continuation():
    config = get_config()
    previous_planning = config.enable_lightweight_planning
    previous_repair = config.enable_bounded_plan_repair
    previous_continuation = config.enable_repair_aware_continuation
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_lightweight_planning = True
    config.enable_bounded_plan_repair = True
    config.enable_repair_aware_continuation = True

    router = make_router(llm_response=LLMResponse(content="unused"))
    router.llm.chat_json = AsyncMock(
        side_effect=[
            {
                "goal": "Calculate emission then render hotspot map",
                "steps": [
                    {"step_id": "s1", "tool_name": "calculate_macro_emission", "produces": ["emission"]},
                    {
                        "step_id": "s2",
                        "tool_name": "render_spatial_map",
                        "depends_on": ["hotspot"],
                        "argument_hints": {"layer_type": "hotspot"},
                    },
                ],
            },
            {
                "trigger_type": "dependency_blocked",
                "trigger_reason": "Need a hotspot result before rendering the hotspot layer.",
                "action_type": "REPLACE_STEP",
                "target_step_id": "s2",
                "affected_step_ids": ["s2", "repair_s1"],
                "planner_notes": "Replace the blocked hotspot render step with dispersion.",
                "is_applicable": True,
                "patch": {
                    "replacement_step": {
                        "step_id": "repair_s1",
                        "tool_name": "calculate_dispersion",
                        "depends_on": ["emission"],
                        "produces": ["dispersion"],
                    }
                },
            },
        ]
    )
    router.llm.chat_with_tools = AsyncMock(
        side_effect=[
            LLMResponse(
                content="call macro",
                tool_calls=[ToolCall(id="c1", name="calculate_macro_emission", arguments={"pollutants": ["CO2"]})],
            ),
            LLMResponse(
                content="call blocked render",
                tool_calls=[ToolCall(id="c2", name="render_spatial_map", arguments={"layer_type": "hotspot"})],
            ),
            LLMResponse(content="PM2.5 是细颗粒物。"),
        ]
    )
    router.executor.execute = AsyncMock(side_effect=[make_emission_result()])

    try:
        await router.chat("先算排放，再渲染热点图", trace={})

        next_turn_state = TaskState.initialize(
            user_message="顺便解释一下 PM2.5 是什么",
            file_path=None,
            memory_dict=router.memory.get_fact_memory(),
            session_id="test-session",
        )
        trace_obj = Trace.start(session_id="test-session")
        await router._state_handle_input(next_turn_state, trace_obj=trace_obj)
    finally:
        config.enable_lightweight_planning = previous_planning
        config.enable_bounded_plan_repair = previous_repair
        config.enable_repair_aware_continuation = previous_continuation

    assert next_turn_state.plan is None
    assert next_turn_state.continuation is not None
    assert next_turn_state.continuation.residual_plan_exists is True
    assert next_turn_state.continuation.should_continue is False
    assert next_turn_state.continuation.signal == "ambiguous_no_safe_continuation"
    assert next_turn_state.stage == TaskStage.DONE
    assert any(step.step_type.value == "plan_continuation_skipped" for step in trace_obj.steps)


@pytest.mark.anyio
async def test_intent_resolution_visualize_without_geometry_biases_away_from_map():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_intent_resolution = True
    config.enable_summary_delivery_surface = False

    router = make_router(
        llm_response=LLMResponse(content="unused"),
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=False),
        },
    )
    router._ensure_context_store().store_result(
        "calculate_macro_emission",
        _emission_result_without_geometry(),
    )

    captured_messages = {}

    async def chat_with_tools_side_effect(*args, **kwargs):
        captured_messages["messages"] = kwargs["messages"]
        return LLMResponse(content="当前更适合用排序图和摘要表展示结果。")

    router.llm.chat_json = AsyncMock(
        return_value={
            "deliverable_intent": "chart_or_ranked_summary",
            "progress_intent": "shift_output_mode",
            "confidence": 0.9,
            "reason": "Visualization was requested but there is no safe geometry support, so a ranked summary is the better bounded deliverable.",
            "current_task_relevance": 0.92,
            "should_bias_existing_action": True,
            "should_preserve_residual_workflow": True,
            "should_trigger_clarification": False,
            "user_utterance_summary": "帮我可视化一下",
        }
    )
    router.llm.chat_with_tools = AsyncMock(side_effect=chat_with_tools_side_effect)

    result = await router.chat("帮我可视化一下", trace={})

    assert "排序图和摘要表" in result.text
    assert any(
        step["step_type"] == "intent_resolution_decided"
        for step in result.trace["steps"]
    )
    assert any(
        msg.get("role") == "system"
        and "Deliverable intent=chart_or_ranked_summary" in msg.get("content", "")
        for msg in captured_messages["messages"]
    )
    router.executor.execute.assert_not_awaited()


@pytest.mark.anyio
async def test_summary_delivery_surface_visualize_without_geometry_returns_ranked_chart():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_intent_resolution = True
    config.enable_summary_delivery_surface = True

    router = make_router(
        llm_response=LLMResponse(content="unused"),
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=False),
        },
    )
    router._ensure_context_store().store_result(
        "calculate_macro_emission",
        _emission_result_without_geometry(),
    )
    router.llm.chat_json = AsyncMock(
        return_value={
            "deliverable_intent": "chart_or_ranked_summary",
            "progress_intent": "shift_output_mode",
            "confidence": 0.92,
            "reason": "The user wants a non-spatial visualization of the current result.",
            "current_task_relevance": 0.93,
            "should_bias_existing_action": True,
            "should_preserve_residual_workflow": True,
            "should_trigger_clarification": False,
            "user_utterance_summary": "帮我可视化一下",
        }
    )
    router.llm.chat_with_tools = AsyncMock(return_value=LLMResponse(content="unused"))

    result = await router.chat("帮我可视化一下", trace={})

    assert result.chart_data is not None
    assert result.chart_data["type"] == "ranked_bar_chart"
    assert result.table_data is not None
    assert result.table_data["type"] == "topk_summary_table"
    assert result.map_data is None
    assert any(step["step_type"] == "summary_delivery_applied" for step in result.trace["steps"])
    router.llm.chat_with_tools.assert_not_awaited()


@pytest.mark.anyio
async def test_summary_delivery_surface_switches_from_repeated_topk_table_to_chart():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_intent_resolution = True
    config.enable_summary_delivery_surface = True

    file_analysis = _macro_file_analysis(has_geometry=False)
    file_analysis["artifact_memory"] = {
        "artifacts": [
            build_artifact_record(
                artifact_type=ArtifactType.TOPK_SUMMARY_TABLE,
                delivery_turn_index=2,
                source_tool_name="summary_delivery_surface",
                source_action_id="download_topk_summary",
                summary="已提供 Top-K 摘要表。",
                related_task_type="macro_emission",
            ).to_dict()
        ]
    }

    router = make_router(
        llm_response=LLMResponse(content="unused"),
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": file_analysis,
        },
    )
    router._ensure_context_store().store_result(
        "calculate_macro_emission",
        _emission_result_without_geometry(),
    )
    router.llm.chat_json = AsyncMock(
        return_value={
            "deliverable_intent": "downloadable_table",
            "progress_intent": "shift_output_mode",
            "confidence": 0.89,
            "reason": "The user wants another ranked summary table for the current result.",
            "current_task_relevance": 0.9,
            "should_bias_existing_action": True,
            "should_preserve_residual_workflow": True,
            "should_trigger_clarification": False,
            "user_utterance_summary": "再给我一个前5高排放路段摘要表",
        }
    )
    router.llm.chat_with_tools = AsyncMock(return_value=LLMResponse(content="unused"))

    result = await router.chat("再给我一个前5高排放路段摘要表", trace={})

    assert result.chart_data is not None
    assert result.chart_data["type"] == "ranked_bar_chart"
    assert result.download_file is None
    decided_steps = [step for step in result.trace["steps"] if step["step_type"] == "summary_delivery_decided"]
    assert decided_steps
    assert decided_steps[0]["output_summary"]["decision"]["switched_from_delivery_type"] == "topk_summary_table"
    router.llm.chat_with_tools.assert_not_awaited()


@pytest.mark.anyio
async def test_summary_delivery_surface_quick_summary_returns_structured_text_and_records_artifacts():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_intent_resolution = True
    config.enable_summary_delivery_surface = True
    config.enable_artifact_memory = True

    router = make_router(
        llm_response=LLMResponse(content="unused"),
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=False),
        },
    )
    router._ensure_context_store().store_result(
        "calculate_macro_emission",
        _emission_result_without_geometry(),
    )
    router.llm.chat_json = AsyncMock(
        return_value={
            "deliverable_intent": "quick_summary",
            "progress_intent": "shift_output_mode",
            "confidence": 0.91,
            "reason": "The user wants a concise structured summary of the current result.",
            "current_task_relevance": 0.9,
            "should_bias_existing_action": True,
            "should_preserve_residual_workflow": True,
            "should_trigger_clarification": False,
            "user_utterance_summary": "先给我一个摘要",
        }
    )
    router.llm.chat_with_tools = AsyncMock(return_value=LLMResponse(content="unused"))

    result = await router.chat("先给我一个摘要", trace={})

    assert "已基于当前结果生成结构化摘要" in result.text
    assert result.chart_data is None
    assert result.table_data is None
    saved_analysis = router.memory.update_calls[-1]["file_analysis"]
    artifact_types = {
        item["artifact_type"]
        for item in saved_analysis["artifact_memory"]["artifacts"]
    }
    assert "quick_summary_text" in artifact_types
    assert any(step["step_type"] == "summary_delivery_recorded" for step in result.trace["steps"])
    router.llm.chat_with_tools.assert_not_awaited()


@pytest.mark.anyio
async def test_intent_resolution_visualize_with_geometry_can_bias_toward_spatial_map():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_intent_resolution = True

    router = make_router(
        llm_response=LLMResponse(content="unused"),
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=True),
        },
    )
    router._ensure_context_store().store_result("calculate_macro_emission", make_emission_result())
    router.llm.chat_json = AsyncMock(
        return_value={
            "deliverable_intent": "spatial_map",
            "progress_intent": "shift_output_mode",
            "confidence": 0.88,
            "reason": "The user asked to visualize the current result and safe spatial support is available.",
            "current_task_relevance": 0.9,
            "should_bias_existing_action": True,
            "should_preserve_residual_workflow": True,
            "should_trigger_clarification": False,
            "user_utterance_summary": "帮我可视化一下",
        }
    )
    router.llm.chat_with_tools = AsyncMock(
        return_value=LLMResponse(
            content="render map",
            tool_calls=[ToolCall(id="c1", name="render_spatial_map", arguments={"layer_type": "emission"})],
        )
    )

    state = TaskState.initialize(
        user_message="帮我可视化一下",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    trace_obj = Trace.start(session_id="test-session")

    await router._state_handle_input(state, trace_obj=trace_obj)

    assert state.execution.selected_tool == "render_spatial_map"
    assert state.latest_intent_resolution_decision is not None
    assert state.latest_intent_resolution_decision.deliverable_intent.value == "spatial_map"
    assert any(step.step_type.value == "intent_resolution_applied" for step in trace_obj.steps)


@pytest.mark.anyio
async def test_intent_resolution_continue_prefers_recovered_target_resume():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_intent_resolution = True
    config.enable_residual_reentry_controller = True

    router = make_router(
        llm_response=LLMResponse(content="unused"),
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=True),
        },
    )
    router._ensure_context_store().store_result("calculate_macro_emission", make_emission_result())
    router._ensure_live_continuation_bundle().update(
        {
            "plan": ExecutionPlan(
                goal="Render the recovered emission map",
                steps=[PlanStep(step_id="s1", tool_name="render_spatial_map", argument_hints={"layer_type": "emission"})],
            ).to_dict(),
            "repair_history": [],
            "blocked_info": None,
            "file_path": "/tmp/roads.csv",
            "latest_repair_summary": "Recovered map target remains ready.",
            "residual_plan_summary": "Goal: Render the recovered emission map",
        }
    )
    router.llm.chat_json = AsyncMock(
        return_value={
            "deliverable_intent": "spatial_map",
            "progress_intent": "resume_recovered_target",
            "confidence": 0.9,
            "reason": "The user is resuming the recovered map workflow.",
            "current_task_relevance": 0.95,
            "should_bias_existing_action": True,
            "should_preserve_residual_workflow": True,
            "should_trigger_clarification": False,
            "user_utterance_summary": "继续",
        }
    )
    router.llm.chat_with_tools = AsyncMock(return_value=LLMResponse(content="继续恢复后的地图分析。"))

    state = TaskState.initialize(
        user_message="继续",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    state.set_residual_reentry_context(
        RecoveredWorkflowReentryContext(
            reentry_target=ResidualReentryTarget(
                target_action_id="render_emission_map",
                target_tool_name="render_spatial_map",
                target_step_id="s1",
                source="geometry_recovery",
                reason="Recovered target remained ready.",
                priority=10,
                target_tool_arguments={"layer_type": "emission"},
                display_name="可视化排放空间分布",
                residual_plan_relationship="matches_next_pending_step",
                matches_next_pending_step=True,
            ),
            residual_plan_summary="Goal: Render the recovered emission map",
            geometry_recovery_context=GeometryRecoveryContext(
                primary_file_ref="/tmp/roads.csv",
                supporting_spatial_input=SupportingSpatialInput(
                    file_ref="/tmp/roads.geojson",
                    file_name="roads.geojson",
                    file_type="geojson",
                    source="input_completion_upload",
                    geometry_capability_summary={"has_geometry_support": True, "support_modes": ["line_geometry"]},
                ),
                target_action_id="render_emission_map",
                target_task_type="macro_emission",
                residual_plan_summary="Goal: Render the recovered emission map",
            ),
            readiness_refresh_result={"after_status": "ready"},
        )
    )
    trace_obj = Trace.start(session_id="test-session")

    await router._state_handle_input(state, trace_obj=trace_obj)

    assert state.continuation is not None
    assert state.continuation.signal == "intent_resume_recovered_target"
    assert state.reentry_bias_applied is True
    assert any(step.step_type.value == "residual_reentry_injected" for step in trace_obj.steps)


@pytest.mark.anyio
async def test_intent_resolution_shift_output_mode_suppresses_default_residual_continuation():
    config = get_config()
    config.enable_state_orchestration = True
    config.enable_trace = True
    config.enable_intent_resolution = True
    config.enable_repair_aware_continuation = True

    router = make_router(
        llm_response=LLMResponse(content="unused"),
        fact_memory={
            "active_file": "/tmp/roads.csv",
            "file_analysis": _macro_file_analysis(has_geometry=True),
        },
    )
    router._ensure_context_store().store_result("calculate_macro_emission", make_emission_result())
    router._ensure_live_continuation_bundle().update(
        {
            "plan": ExecutionPlan(
                goal="Continue with dispersion after emission",
                steps=[
                    PlanStep(step_id="s1", tool_name="calculate_dispersion", argument_hints={"pollutant": "CO2"}),
                    PlanStep(step_id="s2", tool_name="analyze_hotspots", depends_on=["dispersion"]),
                ],
            ).to_dict(),
            "repair_history": [],
            "blocked_info": None,
            "file_path": "/tmp/roads.csv",
            "latest_repair_summary": "Residual workflow ready.",
            "residual_plan_summary": "Goal: Continue with dispersion after emission",
        }
    )
    router.llm.chat_json = AsyncMock(
        return_value={
            "deliverable_intent": "quick_summary",
            "progress_intent": "shift_output_mode",
            "confidence": 0.87,
            "reason": "The user wants a different presentation instead of continuing the next analysis step.",
            "current_task_relevance": 0.88,
            "should_bias_existing_action": True,
            "should_preserve_residual_workflow": True,
            "should_trigger_clarification": False,
            "user_utterance_summary": "继续，但换个方式展示",
        }
    )
    router.llm.chat_with_tools = AsyncMock(return_value=LLMResponse(content="当前更适合先给出简洁摘要。"))

    state = TaskState.initialize(
        user_message="继续，但换个方式展示",
        file_path=None,
        memory_dict=router.memory.get_fact_memory(),
        session_id="test-session",
    )
    trace_obj = Trace.start(session_id="test-session")

    await router._state_handle_input(state, trace_obj=trace_obj)

    assert state.continuation is not None
    assert state.continuation.should_continue is False
    assert state.continuation.signal == "intent_shift_output_mode"
    assert state.latest_intent_resolution_decision is not None
    assert state.latest_intent_resolution_decision.progress_intent.value == "shift_output_mode"
