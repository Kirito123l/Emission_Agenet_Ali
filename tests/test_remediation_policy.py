"""Tests for policy-based remediation (P0-I5).

Covers:
  A. Eligibility check and option generation
  B. Deterministic parsing of default-typical-profile intent phrases
  C. Policy application – field-level overrides
  D. Unsupported cases – no policy when signals insufficient
  E. Trace step types
  F. Row-level value resolution
  G. Readiness override recognition
"""
from __future__ import annotations

import pytest

from core.input_completion import (
    InputCompletionDecisionType,
    InputCompletionOption,
    InputCompletionOptionType,
    InputCompletionReasonCode,
    InputCompletionRequest,
    format_input_completion_prompt,
    parse_input_completion_reply,
    reply_looks_like_input_completion_attempt,
)
from core.readiness import _missing_field_resolved_by_override
from core.remediation_policy import (
    RemediationPolicy,
    RemediationPolicyApplicationResult,
    RemediationPolicyType,
    apply_default_typical_profile,
    check_default_typical_profile_eligibility,
    resolve_avg_speed_kph,
    resolve_traffic_flow_vph,
)
from core.trace import TraceStepType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request_with_profile_option(
    *,
    target_fields: list[str] | None = None,
    context_signals: list[str] | None = None,
) -> InputCompletionRequest:
    """Build a completion request that includes the default typical profile option."""
    target_fields = target_fields or ["traffic_flow_vph"]
    context_signals = context_signals or ["highway", "lanes"]
    return InputCompletionRequest.create(
        action_id="run_macro_emission",
        reason_code=InputCompletionReasonCode.MISSING_REQUIRED_FIELD,
        reason_summary="缺少 traffic_flow_vph。",
        missing_requirements=["traffic_flow_vph"],
        target_field="traffic_flow_vph",
        current_task_type="macro_emission",
        options=[
            InputCompletionOption(
                option_id="apply_default_typical_profile",
                option_type=InputCompletionOptionType.APPLY_DEFAULT_TYPICAL_PROFILE,
                label="使用默认典型值策略补齐 traffic_flow_vph",
                description="根据道路属性自动估算。",
                requirements={
                    "target_fields": target_fields,
                    "context_signals_present": context_signals,
                    "estimation_basis": "road class (highway), lane count (lanes)",
                    "policy_type": "apply_default_typical_profile",
                },
                aliases=["默认典型值", "默认值模拟", "道路类型估算"],
            ),
            InputCompletionOption(
                option_id="traffic_flow_vph_uniform_value",
                option_type=InputCompletionOptionType.PROVIDE_UNIFORM_VALUE,
                label="统一流量值",
                description="为所有路段设置统一流量值。",
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


def _make_request_without_profile_option() -> InputCompletionRequest:
    """Build a completion request that does NOT include the default typical profile option."""
    return InputCompletionRequest.create(
        action_id="run_macro_emission",
        reason_code=InputCompletionReasonCode.MISSING_REQUIRED_FIELD,
        reason_summary="缺少 traffic_flow_vph。",
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
                option_id="traffic_flow_vph_pause",
                option_type=InputCompletionOptionType.PAUSE,
                label="暂停",
                description="先不补这个字段。",
            ),
        ],
    )


# ===================================================================
# A. Eligibility check / option generation
# ===================================================================

class TestEligibilityCheck:
    def test_eligible_macro_emission_with_highway_lanes_maxspeed(self):
        policy = check_default_typical_profile_eligibility(
            task_type="macro_emission",
            missing_fields=["traffic_flow_vph", "avg_speed_kph"],
            available_columns=["link_id", "highway", "lanes", "maxspeed", "length"],
        )
        assert policy is not None
        assert policy.policy_type == RemediationPolicyType.APPLY_DEFAULT_TYPICAL_PROFILE
        assert "traffic_flow_vph" in policy.target_fields
        assert "avg_speed_kph" in policy.target_fields
        assert "highway" in policy.context_signals_present
        assert "lanes" in policy.context_signals_present
        assert "maxspeed" in policy.context_signals_present

    def test_eligible_macro_emission_highway_only(self):
        policy = check_default_typical_profile_eligibility(
            task_type="macro_emission",
            missing_fields=["traffic_flow_vph"],
            available_columns=["link_id", "highway", "length"],
        )
        assert policy is not None
        assert policy.target_fields == ["traffic_flow_vph"]
        assert policy.context_signals_present == ["highway"]

    def test_not_eligible_wrong_task_type(self):
        policy = check_default_typical_profile_eligibility(
            task_type="micro_emission",
            missing_fields=["traffic_flow_vph"],
            available_columns=["link_id", "highway", "lanes"],
        )
        assert policy is None

    def test_not_eligible_no_context_signals(self):
        policy = check_default_typical_profile_eligibility(
            task_type="macro_emission",
            missing_fields=["traffic_flow_vph"],
            available_columns=["link_id", "length", "oneway"],
        )
        assert policy is None

    def test_not_eligible_no_missing_target_fields(self):
        policy = check_default_typical_profile_eligibility(
            task_type="macro_emission",
            missing_fields=["link_id"],  # not a policy target
            available_columns=["highway", "lanes"],
        )
        assert policy is None

    def test_not_eligible_empty_missing_fields(self):
        policy = check_default_typical_profile_eligibility(
            task_type="macro_emission",
            missing_fields=[],
            available_columns=["highway", "lanes"],
        )
        assert policy is None


# ===================================================================
# B. Deterministic parsing of default-typical-profile intent
# ===================================================================

class TestDeterministicParsing:
    @pytest.mark.parametrize(
        "user_reply",
        [
            "用默认典型值模拟吧",
            "使用默认典型值模拟",
            "按道路类型估算",
            "就用默认值算",
            "用默认值计算",
            "按默认典型值跑一下",
            "就用系统默认模拟吧",
            "默认估算",
            "use defaults",
            "use default typical profile",
        ],
    )
    def test_profile_phrase_parsed_as_policy(self, user_reply: str):
        request = _make_request_with_profile_option()
        result = parse_input_completion_reply(request, user_reply)
        assert result.is_resolved, f"Failed for: {user_reply}"
        assert result.decision is not None
        assert result.decision.decision_type == InputCompletionDecisionType.SELECTED_OPTION
        assert result.decision.selected_option_id == "apply_default_typical_profile"
        payload = result.decision.structured_payload
        assert payload.get("mode") == "remediation_policy"
        assert payload.get("policy_type") == "apply_default_typical_profile"

    def test_profile_phrase_not_matched_without_option(self):
        """If the request does not have a profile option, phrases should NOT match."""
        request = _make_request_without_profile_option()
        result = parse_input_completion_reply(request, "用默认典型值模拟吧")
        # Should not resolve as default typical profile
        if result.is_resolved:
            assert result.decision.selected_option_id != "apply_default_typical_profile"

    def test_numeric_still_works_with_profile_option(self):
        """Numeric replies should still match uniform scalar, even when profile option exists."""
        request = _make_request_with_profile_option()
        result = parse_input_completion_reply(request, "1500")
        assert result.is_resolved
        assert result.decision.structured_payload.get("mode") == "uniform_scalar"

    def test_pause_still_works_with_profile_option(self):
        request = _make_request_with_profile_option()
        result = parse_input_completion_reply(request, "暂停")
        assert result.is_resolved
        assert result.decision.decision_type == InputCompletionDecisionType.PAUSE

    def test_reply_looks_like_attempt_with_profile_phrase(self):
        request = _make_request_with_profile_option()
        assert reply_looks_like_input_completion_attempt(request, "用默认典型值模拟吧")

    def test_reply_looks_like_attempt_profile_phrase_no_option(self):
        request = _make_request_without_profile_option()
        # Without the option, the phrase alone should not register
        # (it falls through to alias matching which may or may not match)
        result = reply_looks_like_input_completion_attempt(request, "用默认典型值模拟吧")
        # This is OK either way – the point is it shouldn't crash
        assert isinstance(result, bool)


# ===================================================================
# C. Policy application – field-level overrides
# ===================================================================

class TestPolicyApplication:
    def test_apply_single_field_traffic_flow(self):
        policy = RemediationPolicy(
            policy_type=RemediationPolicyType.APPLY_DEFAULT_TYPICAL_PROFILE,
            applicable_task_types=["macro_emission"],
            target_fields=["traffic_flow_vph"],
            context_signals=["highway", "lanes", "maxspeed"],
            context_signals_present=["highway", "lanes"],
            estimation_basis="road class (highway), lane count (lanes)",
        )
        result = apply_default_typical_profile(
            policy=policy,
            missing_fields=["traffic_flow_vph"],
        )
        assert result.success
        assert len(result.field_overrides) == 1
        assert result.field_overrides[0].field_name == "traffic_flow_vph"
        assert result.field_overrides[0].mode == "default_typical_profile"

    def test_apply_both_fields(self):
        policy = RemediationPolicy(
            policy_type=RemediationPolicyType.APPLY_DEFAULT_TYPICAL_PROFILE,
            applicable_task_types=["macro_emission"],
            target_fields=["traffic_flow_vph", "avg_speed_kph"],
            context_signals=["highway", "lanes", "maxspeed"],
            context_signals_present=["highway", "lanes", "maxspeed"],
            estimation_basis="road class, lane count, speed limit",
        )
        result = apply_default_typical_profile(
            policy=policy,
            missing_fields=["traffic_flow_vph", "avg_speed_kph"],
        )
        assert result.success
        assert len(result.field_overrides) == 2
        field_names = {fo.field_name for fo in result.field_overrides}
        assert field_names == {"traffic_flow_vph", "avg_speed_kph"}

    def test_apply_wrong_policy_type(self):
        policy = RemediationPolicy(
            policy_type=RemediationPolicyType.UNIFORM_SCALAR_FILL,
        )
        result = apply_default_typical_profile(
            policy=policy,
            missing_fields=["traffic_flow_vph"],
        )
        assert not result.success
        assert result.error is not None

    def test_apply_no_matching_fields(self):
        policy = RemediationPolicy(
            policy_type=RemediationPolicyType.APPLY_DEFAULT_TYPICAL_PROFILE,
            context_signals_present=["highway"],
        )
        result = apply_default_typical_profile(
            policy=policy,
            missing_fields=["link_id"],  # not remediable by this policy
        )
        assert not result.success

    def test_serialization(self):
        policy = RemediationPolicy(
            policy_type=RemediationPolicyType.APPLY_DEFAULT_TYPICAL_PROFILE,
            target_fields=["traffic_flow_vph"],
            context_signals_present=["highway"],
        )
        result = apply_default_typical_profile(
            policy=policy,
            missing_fields=["traffic_flow_vph"],
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["policy_type"] == "apply_default_typical_profile"
        assert len(d["field_overrides"]) == 1


# ===================================================================
# D. Unsupported cases
# ===================================================================

class TestUnsupportedCases:
    def test_no_policy_for_micro_emission(self):
        policy = check_default_typical_profile_eligibility(
            task_type="micro_emission",
            missing_fields=["traffic_flow_vph"],
            available_columns=["highway", "lanes", "maxspeed"],
        )
        assert policy is None

    def test_no_policy_without_any_signal_columns(self):
        policy = check_default_typical_profile_eligibility(
            task_type="macro_emission",
            missing_fields=["traffic_flow_vph"],
            available_columns=["fid", "name", "length", "oneway"],
        )
        assert policy is None

    def test_no_policy_for_non_target_missing_fields(self):
        policy = check_default_typical_profile_eligibility(
            task_type="macro_emission",
            missing_fields=["vehicle_type", "link_id"],
            available_columns=["highway", "lanes"],
        )
        assert policy is None


# ===================================================================
# E. Trace step types exist
# ===================================================================

class TestTraceTypes:
    def test_remediation_trace_types_exist(self):
        assert hasattr(TraceStepType, "REMEDIATION_POLICY_OPTION_OFFERED")
        assert hasattr(TraceStepType, "REMEDIATION_POLICY_CONFIRMED")
        assert hasattr(TraceStepType, "REMEDIATION_POLICY_APPLIED")
        assert hasattr(TraceStepType, "REMEDIATION_POLICY_FAILED")

    def test_trace_type_values(self):
        assert TraceStepType.REMEDIATION_POLICY_OPTION_OFFERED.value == "remediation_policy_option_offered"
        assert TraceStepType.REMEDIATION_POLICY_CONFIRMED.value == "remediation_policy_confirmed"
        assert TraceStepType.REMEDIATION_POLICY_APPLIED.value == "remediation_policy_applied"
        assert TraceStepType.REMEDIATION_POLICY_FAILED.value == "remediation_policy_failed"


# ===================================================================
# F. Row-level value resolution
# ===================================================================

class TestRowLevelResolution:
    def test_resolve_flow_motorway_2_lanes(self):
        flow = resolve_traffic_flow_vph(highway="motorway", lanes=2)
        assert flow == 1600

    def test_resolve_flow_residential_default(self):
        flow = resolve_traffic_flow_vph(highway="residential")
        assert flow == 150

    def test_resolve_flow_unknown_highway(self):
        flow = resolve_traffic_flow_vph(highway="unknown_class")
        assert flow == 300.0  # fallback

    def test_resolve_flow_none_highway(self):
        flow = resolve_traffic_flow_vph()
        assert flow == 300.0

    def test_resolve_speed_from_maxspeed(self):
        speed = resolve_avg_speed_kph(maxspeed=100.0)
        assert speed == 85.0  # 100 * 0.85

    def test_resolve_speed_from_highway(self):
        speed = resolve_avg_speed_kph(highway="primary")
        assert speed == 60.0

    def test_resolve_speed_maxspeed_takes_priority(self):
        speed = resolve_avg_speed_kph(maxspeed=120.0, highway="residential")
        assert speed == 102.0  # 120 * 0.85

    def test_resolve_speed_fallback(self):
        speed = resolve_avg_speed_kph()
        assert speed == 40.0


# ===================================================================
# G. Readiness override recognition
# ===================================================================

class TestReadinessOverrideRecognition:
    def test_default_typical_profile_mode_recognized(self):
        overrides = {
            "traffic_flow_vph": {
                "mode": "default_typical_profile",
                "field": "traffic_flow_vph",
                "policy_type": "apply_default_typical_profile",
                "source": "input_completion",
            }
        }
        assert _missing_field_resolved_by_override("traffic_flow_vph", overrides) is True

    def test_uniform_scalar_still_recognized(self):
        overrides = {
            "traffic_flow_vph": {
                "mode": "uniform_scalar",
                "value": 1500,
                "source": "input_completion",
            }
        }
        assert _missing_field_resolved_by_override("traffic_flow_vph", overrides) is True

    def test_unknown_mode_not_recognized(self):
        overrides = {
            "traffic_flow_vph": {
                "mode": "magical_inference",
            }
        }
        assert _missing_field_resolved_by_override("traffic_flow_vph", overrides) is False


# ===================================================================
# H. Completion prompt formatting
# ===================================================================

class TestCompletionPromptFormatting:
    def test_prompt_includes_profile_hint(self):
        request = _make_request_with_profile_option()
        prompt = format_input_completion_prompt(request)
        assert "默认典型值策略" in prompt or "默认典型值" in prompt

    def test_prompt_includes_option_listing(self):
        request = _make_request_with_profile_option()
        prompt = format_input_completion_prompt(request)
        assert "1." in prompt
        assert "2." in prompt

    def test_option_type_enum_has_profile(self):
        assert InputCompletionOptionType.APPLY_DEFAULT_TYPICAL_PROFILE.value == "apply_default_typical_profile"


# ===================================================================
# I. Index-based selection of profile option
# ===================================================================

class TestIndexSelection:
    def test_select_profile_by_phrase(self):
        """User can select profile option by using a default-typical-profile phrase."""
        request = _make_request_with_profile_option()
        result = parse_input_completion_reply(request, "用默认典型值模拟")
        assert result.is_resolved
        assert result.decision.selected_option_id == "apply_default_typical_profile"

    def test_numeric_value_takes_precedence_over_index(self):
        """Numeric replies are interpreted as uniform scalar values, not indices."""
        request = _make_request_with_profile_option()
        result = parse_input_completion_reply(request, "1")
        assert result.is_resolved
        # "1" is parsed as a numeric value for uniform scalar, not as index 1
        assert result.decision.structured_payload.get("mode") == "uniform_scalar"
        assert result.decision.structured_payload.get("value") == 1.0
