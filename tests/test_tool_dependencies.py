"""Tests for canonical tool dependency handling and plan validation."""

from core.plan import ExecutionPlan, PlanStatus, PlanStep, PlanStepStatus
from core.context_store import SessionContextStore
from core.plan_repair import (
    PlanRepairDecision,
    PlanRepairPatch,
    RepairActionType,
    RepairTriggerType,
    validate_plan_repair,
)
from core.tool_dependencies import (
    get_missing_prerequisites,
    get_required_result_tokens,
    get_tool_provides,
    normalize_result_token,
    normalize_tokens,
    suggest_prerequisite_tool,
    validate_tool_prerequisites,
    validate_plan_steps,
)
from tests.test_context_store import make_dispersion_result, make_emission_result


def test_legacy_alias_normalization():
    assert normalize_result_token("emission_result") == "emission"
    assert normalize_result_token("dispersion_result") == "dispersion"
    assert normalize_result_token("hotspot_analysis") == "hotspot"
    assert normalize_tokens(["emission_result", "emission", "dispersion_result"]) == [
        "emission",
        "dispersion",
    ]


def test_no_prerequisites():
    missing = get_missing_prerequisites("calculate_macro_emission", set())
    assert missing == []


def test_dispersion_requires_emission():
    missing = get_missing_prerequisites("calculate_dispersion", set())
    assert missing == ["emission"]


def test_suggest_prerequisite():
    tool = suggest_prerequisite_tool("emission_result")
    assert tool in ("calculate_micro_emission", "calculate_macro_emission")


def test_suggest_prerequisite_unknown():
    tool = suggest_prerequisite_tool("nonexistent_result")
    assert tool is None


def test_all_met_with_legacy_available_token():
    missing = get_missing_prerequisites("calculate_dispersion", {"emission_result"})
    assert missing == []


def test_render_spatial_map_layer_type_dependency_mapping():
    assert get_required_result_tokens("render_spatial_map", {"layer_type": "emission"}) == ["emission"]
    assert get_required_result_tokens("render_spatial_map", {"layer_type": "dispersion"}) == ["dispersion"]
    assert get_required_result_tokens("render_spatial_map", {"layer_type": "contour"}) == ["dispersion"]
    assert get_required_result_tokens("render_spatial_map", {"layer_type": "raster"}) == ["dispersion"]
    assert get_required_result_tokens("render_spatial_map", {"layer_type": "concentration"}) == ["dispersion"]
    assert get_required_result_tokens("render_spatial_map", {"layer_type": "hotspot"}) == ["hotspot"]


def test_render_spatial_map_without_layer_type_has_no_static_prereqs():
    missing = get_missing_prerequisites("render_spatial_map", set())
    assert missing == []


def test_get_tool_provides_returns_canonical_tokens():
    provides = get_tool_provides("calculate_macro_emission")
    assert provides == ["emission"]


def test_get_tool_provides_unknown():
    provides = get_tool_provides("nonexistent_tool")
    assert provides == []


def test_query_emission_factors_provides():
    provides = get_tool_provides("query_emission_factors")
    assert "emission_factors" in provides


def test_validate_plan_steps_accepts_emission_to_dispersion_to_hotspot_chain():
    validation = validate_plan_steps(
        [
            PlanStep(step_id="s1", tool_name="calculate_macro_emission"),
            PlanStep(step_id="s2", tool_name="calculate_dispersion"),
            PlanStep(step_id="s3", tool_name="analyze_hotspots"),
        ]
    )

    assert validation["status"] == PlanStatus.VALID
    assert [item["status"] for item in validation["step_results"]] == [
        PlanStepStatus.READY,
        PlanStepStatus.READY,
        PlanStepStatus.READY,
    ]


def test_validate_plan_steps_marks_missing_prerequisite_as_blocked():
    validation = validate_plan_steps(
        [
            PlanStep(step_id="s1", tool_name="calculate_dispersion"),
            PlanStep(step_id="s2", tool_name="analyze_hotspots"),
        ]
    )

    assert validation["status"] == PlanStatus.PARTIAL
    assert validation["step_results"][0]["status"] == PlanStepStatus.BLOCKED
    assert validation["step_results"][1]["status"] == PlanStepStatus.BLOCKED
    assert any(
        "prerequisite validation failed" in note
        for note in validation["step_results"][0]["validation_notes"]
    )


def test_validate_plan_steps_uses_existing_available_tokens():
    validation = validate_plan_steps(
        [PlanStep(step_id="s1", tool_name="calculate_dispersion")],
        available_tokens={"emission_result"},
    )

    assert validation["status"] == PlanStatus.VALID
    assert validation["step_results"][0]["status"] == PlanStepStatus.READY


def test_validate_tool_prerequisites_passes_when_required_token_available():
    validation = validate_tool_prerequisites(
        "calculate_dispersion",
        available_tokens={"emission"},
    )

    assert validation.is_valid is True
    assert validation.missing_tokens == []
    assert validation.stale_tokens == []


def test_validate_tool_prerequisites_passes_with_injected_last_result():
    validation = validate_tool_prerequisites(
        "calculate_dispersion",
        arguments={"_last_result": make_emission_result("baseline")},
        available_tokens=set(),
    )

    assert validation.is_valid is True
    assert validation.missing_tokens == []
    assert "emission" in validation.available_tokens


def test_validate_tool_prerequisites_fails_when_required_token_missing():
    validation = validate_tool_prerequisites(
        "analyze_hotspots",
        available_tokens={"emission"},
    )

    assert validation.is_valid is False
    assert validation.missing_tokens == ["dispersion"]
    assert validation.stale_tokens == []


def test_validate_tool_prerequisites_fails_when_only_stale_result_exists():
    store = SessionContextStore()
    store.store_result("calculate_dispersion", make_dispersion_result("baseline"))
    store.store_result("calculate_macro_emission", make_emission_result("baseline"))

    validation = validate_tool_prerequisites(
        "analyze_hotspots",
        available_tokens=set(),
        context_store=store,
        include_stale=False,
    )

    assert validation.is_valid is False
    assert validation.missing_tokens == []
    assert validation.stale_tokens == ["dispersion"]


def test_plan_validation_and_runtime_validation_share_same_dependency_mapping():
    plan_validation = validate_plan_steps(
        [
            PlanStep(
                step_id="s1",
                tool_name="render_spatial_map",
                argument_hints={"layer_type": "hotspot"},
            )
        ],
        available_tokens={"hotspot"},
    )
    runtime_validation = validate_tool_prerequisites(
        "render_spatial_map",
        arguments={"layer_type": "hotspot"},
        available_tokens={"hotspot"},
    )

    assert plan_validation["step_results"][0]["required_tokens"] == runtime_validation.required_tokens
    assert runtime_validation.is_valid is True


def test_validate_plan_repair_accepts_dependency_legal_residual_patch():
    current_plan = ExecutionPlan(
        goal="Continue after emission",
        steps=[
            PlanStep(step_id="s1", tool_name="calculate_macro_emission", status=PlanStepStatus.COMPLETED),
            PlanStep(step_id="s2", tool_name="analyze_hotspots", status=PlanStepStatus.BLOCKED),
        ],
    )
    decision = PlanRepairDecision(
        trigger_type=RepairTriggerType.DEPENDENCY_BLOCKED,
        trigger_reason="Missing dispersion result.",
        action_type=RepairActionType.REPLACE_STEP,
        target_step_id="s2",
        affected_step_ids=["s2"],
        planner_notes="Replace blocked hotspot analysis with a prerequisite dispersion step.",
        is_applicable=True,
        patch=PlanRepairPatch(
            target_step_id="s2",
            replacement_step=PlanStep(
                step_id="repair-dispersion",
                tool_name="calculate_dispersion",
                depends_on=["emission"],
                produces=["dispersion"],
            ),
        ),
    )

    validation = validate_plan_repair(current_plan, decision, available_tokens={"emission"})

    assert validation.is_valid is True
    assert validation.repaired_plan is not None
    assert validation.repaired_plan.steps[0].status == PlanStepStatus.COMPLETED
    assert validation.repaired_plan.steps[1].status == PlanStepStatus.SKIPPED
    assert validation.repaired_plan.steps[2].tool_name == "calculate_dispersion"
    assert validation.repaired_plan.steps[2].status == PlanStepStatus.READY


def test_validate_plan_repair_rejects_illegal_hotspot_residual_without_dependency_chain():
    current_plan = ExecutionPlan(
        goal="Render hotspot",
        steps=[
            PlanStep(
                step_id="s1",
                tool_name="render_spatial_map",
                argument_hints={"layer_type": "hotspot"},
                status=PlanStepStatus.BLOCKED,
            ),
        ],
    )
    decision = PlanRepairDecision(
        trigger_type=RepairTriggerType.DEPENDENCY_BLOCKED,
        trigger_reason="Missing hotspot result.",
        action_type=RepairActionType.KEEP_REMAINING,
        target_step_id="s1",
        affected_step_ids=["s1"],
        planner_notes="Keep the blocked render step unchanged.",
        is_applicable=True,
    )

    validation = validate_plan_repair(current_plan, decision, available_tokens=set())

    assert validation.is_valid is False
    assert any(issue.issue_type == "illegal_residual_plan" for issue in validation.issues)


def test_validate_plan_repair_rejects_completed_step_mutation():
    current_plan = ExecutionPlan(
        goal="Emission then map",
        steps=[
            PlanStep(step_id="s1", tool_name="calculate_macro_emission", status=PlanStepStatus.COMPLETED),
            PlanStep(step_id="s2", tool_name="render_spatial_map", status=PlanStepStatus.PENDING),
        ],
    )
    decision = PlanRepairDecision(
        trigger_type=RepairTriggerType.PLAN_DEVIATION,
        trigger_reason="Attempted to rewrite completed history.",
        action_type=RepairActionType.DROP_BLOCKED_STEP,
        target_step_id="s1",
        affected_step_ids=["s1"],
        planner_notes="Drop the completed step.",
        is_applicable=True,
        patch=PlanRepairPatch(skip_step_ids=["s1"]),
    )

    validation = validate_plan_repair(current_plan, decision, available_tokens={"emission"})

    assert validation.is_valid is False
    assert any(issue.issue_type == "completed_step_mutation" for issue in validation.issues)
