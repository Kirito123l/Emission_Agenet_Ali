"""
Policy-Based Remediation for Repairable Missing Fields.

Upgrades the system from field-level scalar fill to bounded strategy-level
remediation.  A remediation policy is a formal, traceable decision object
that can fill *a group* of related missing fields in one shot, using
rule-based lookup tables rather than LLM inference.

Key abstractions:

* RemediationPolicyType  – enum of supported policy kinds
* RemediationPolicy      – a specific policy instance with applicability info
* RemediationPolicyDecision – the user/system decision to adopt a policy
* RemediationPolicyApplicationResult – field-level overrides produced by applying the policy

This module is intentionally bounded:
  - Only a small number of high-value policy types are supported.
  - The default typical profile is a conservative heuristic, NOT a traffic model.
  - All lookup values are fixed, auditable, and paper-citable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set


# ---------------------------------------------------------------------------
# Policy type enum
# ---------------------------------------------------------------------------

class RemediationPolicyType(str, Enum):
    UNIFORM_SCALAR_FILL = "uniform_scalar_fill"
    UPLOAD_SUPPORTING_FILE = "upload_supporting_file"
    APPLY_DEFAULT_TYPICAL_PROFILE = "apply_default_typical_profile"
    PAUSE = "pause"


# ---------------------------------------------------------------------------
# Default typical profile – bounded lookup tables
# ---------------------------------------------------------------------------
# Sources:
#   - Highway Capacity Manual (HCM 6th ed.) level-of-service defaults
#   - OSM highway tag wiki  (lanes defaults per road class)
#   - Conservative lower-bound values chosen deliberately so that the
#     profile under-estimates rather than over-estimates real traffic.
#
# IMPORTANT: This is a *default typical profile* for rapid prototyping,
# NOT a calibrated traffic-state inference model.
# ---------------------------------------------------------------------------

# traffic_flow_vph defaults keyed by (highway_class, lanes).
# "lanes" key None means "any / unknown lanes".
# Values are *per-direction* flow in veh/h.

_DEFAULT_FLOW_BY_HIGHWAY_LANES: Dict[str, Dict[Optional[int], float]] = {
    "motorway":       {None: 1800, 1: 1200, 2: 1600, 3: 2000, 4: 2200},
    "motorway_link":  {None: 800,  1: 600,  2: 900},
    "trunk":          {None: 1200, 1: 800,  2: 1200, 3: 1500},
    "trunk_link":     {None: 600,  1: 500,  2: 700},
    "primary":        {None: 800,  1: 600,  2: 900,  3: 1100},
    "primary_link":   {None: 500,  1: 400,  2: 600},
    "secondary":      {None: 500,  1: 400,  2: 600},
    "secondary_link": {None: 350,  1: 300,  2: 400},
    "tertiary":       {None: 300,  1: 250,  2: 350},
    "tertiary_link":  {None: 200,  1: 180,  2: 250},
    "residential":    {None: 150,  1: 120,  2: 180},
    "living_street":  {None: 50,   1: 40},
    "unclassified":   {None: 100,  1: 80,   2: 120},
    "service":        {None: 50,   1: 40},
}

# Fallback if highway class is completely unrecognised
_DEFAULT_FLOW_FALLBACK: float = 300.0

# avg_speed_kph defaults keyed by highway_class.
# Used only when maxspeed is absent.
_DEFAULT_SPEED_BY_HIGHWAY: Dict[str, float] = {
    "motorway":       100.0,
    "motorway_link":  60.0,
    "trunk":          80.0,
    "trunk_link":     50.0,
    "primary":        60.0,
    "primary_link":   40.0,
    "secondary":      50.0,
    "secondary_link": 35.0,
    "tertiary":       40.0,
    "tertiary_link":  30.0,
    "residential":    30.0,
    "living_street":  20.0,
    "unclassified":   30.0,
    "service":        20.0,
}

_DEFAULT_SPEED_FALLBACK: float = 40.0

# Which canonical fields can be remediated by this profile
_DEFAULT_PROFILE_TARGET_FIELDS: Set[str] = {"traffic_flow_vph", "avg_speed_kph"}

# Required context signals – at least one must be present in the file
_DEFAULT_PROFILE_CONTEXT_SIGNALS: Set[str] = {"highway", "lanes", "maxspeed"}

# Task types where the default typical profile is allowed
_DEFAULT_PROFILE_ALLOWED_TASK_TYPES: Set[str] = {"macro_emission"}


# ---------------------------------------------------------------------------
# Data objects
# ---------------------------------------------------------------------------

@dataclass
class RemediationPolicy:
    """A concrete, applicable remediation policy."""

    policy_type: RemediationPolicyType
    applicable_task_types: List[str] = field(default_factory=list)
    target_fields: List[str] = field(default_factory=list)
    context_signals: List[str] = field(default_factory=list)
    context_signals_present: List[str] = field(default_factory=list)
    estimation_basis: str = ""
    confidence_label: str = "conservative"  # conservative | approximate | default

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_type": self.policy_type.value,
            "applicable_task_types": list(self.applicable_task_types),
            "target_fields": list(self.target_fields),
            "context_signals": list(self.context_signals),
            "context_signals_present": list(self.context_signals_present),
            "estimation_basis": self.estimation_basis,
            "confidence_label": self.confidence_label,
        }


@dataclass
class RemediationPolicyDecision:
    """Records the user/system decision to adopt a specific policy."""

    policy: RemediationPolicy
    source: str = "input_completion"  # where the decision came from
    user_reply: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy": self.policy.to_dict(),
            "source": self.source,
            "user_reply": self.user_reply,
        }


@dataclass
class FieldOverride:
    """A single field-level override produced by applying a policy."""

    field_name: str
    mode: str  # e.g. "default_typical_profile"
    strategy_description: str = ""
    lookup_basis: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field_name": self.field_name,
            "mode": self.mode,
            "strategy_description": self.strategy_description,
            "lookup_basis": self.lookup_basis,
        }


@dataclass
class RemediationPolicyApplicationResult:
    """Result of applying a remediation policy – field overrides + metadata."""

    success: bool
    policy_type: RemediationPolicyType
    field_overrides: List[FieldOverride] = field(default_factory=list)
    error: Optional[str] = None
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "policy_type": self.policy_type.value,
            "field_overrides": [item.to_dict() for item in self.field_overrides],
            "error": self.error,
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Eligibility check
# ---------------------------------------------------------------------------

def check_default_typical_profile_eligibility(
    *,
    task_type: Optional[str],
    missing_fields: Sequence[str],
    available_columns: Sequence[str],
    allowed_task_types: Optional[Set[str]] = None,
) -> Optional[RemediationPolicy]:
    """Return a RemediationPolicy if the default typical profile is applicable.

    Returns None if the preconditions are not met.
    """
    effective_allowed = allowed_task_types or _DEFAULT_PROFILE_ALLOWED_TASK_TYPES
    normalized_task = str(task_type or "").strip().lower()
    if normalized_task not in effective_allowed:
        return None

    # At least one target field must actually be missing
    missing_set = {str(f).strip().lower() for f in missing_fields if str(f).strip()}
    relevant_missing = missing_set & _DEFAULT_PROFILE_TARGET_FIELDS
    if not relevant_missing:
        return None

    # Check context signals present in available columns
    normalized_columns = {str(c).strip().lower() for c in available_columns if str(c).strip()}
    signals_present = sorted(normalized_columns & _DEFAULT_PROFILE_CONTEXT_SIGNALS)
    if not signals_present:
        return None

    # Build estimation basis description
    basis_parts = []
    if "highway" in signals_present:
        basis_parts.append("road class (highway)")
    if "lanes" in signals_present:
        basis_parts.append("lane count (lanes)")
    if "maxspeed" in signals_present:
        basis_parts.append("speed limit (maxspeed)")
    estimation_basis = ", ".join(basis_parts) if basis_parts else "available road attributes"

    return RemediationPolicy(
        policy_type=RemediationPolicyType.APPLY_DEFAULT_TYPICAL_PROFILE,
        applicable_task_types=[normalized_task],
        target_fields=sorted(relevant_missing),
        context_signals=sorted(_DEFAULT_PROFILE_CONTEXT_SIGNALS),
        context_signals_present=signals_present,
        estimation_basis=estimation_basis,
        confidence_label="conservative",
    )


# ---------------------------------------------------------------------------
# Policy application – generate execution-side overrides
# ---------------------------------------------------------------------------

def apply_default_typical_profile(
    *,
    policy: RemediationPolicy,
    missing_fields: Sequence[str],
) -> RemediationPolicyApplicationResult:
    """Apply the default typical profile and return field-level overrides.

    This does NOT fill actual data – it produces override descriptors that
    the executor will use to generate per-row values during tool execution.
    """
    if policy.policy_type != RemediationPolicyType.APPLY_DEFAULT_TYPICAL_PROFILE:
        return RemediationPolicyApplicationResult(
            success=False,
            policy_type=policy.policy_type,
            error="Policy type mismatch: expected apply_default_typical_profile.",
        )

    missing_set = {str(f).strip().lower() for f in missing_fields if str(f).strip()}
    overrides: List[FieldOverride] = []

    if "traffic_flow_vph" in missing_set:
        basis_parts = []
        if "highway" in policy.context_signals_present:
            basis_parts.append("highway")
        if "lanes" in policy.context_signals_present:
            basis_parts.append("lanes")
        overrides.append(FieldOverride(
            field_name="traffic_flow_vph",
            mode="default_typical_profile",
            strategy_description=(
                "Per-row traffic flow estimated from road class"
                + (" and lane count" if "lanes" in policy.context_signals_present else "")
                + " using conservative HCM-based lookup table."
            ),
            lookup_basis=", ".join(basis_parts) if basis_parts else "fallback_default",
        ))

    if "avg_speed_kph" in missing_set:
        basis_parts = []
        if "maxspeed" in policy.context_signals_present:
            basis_parts.append("maxspeed")
        if "highway" in policy.context_signals_present:
            basis_parts.append("highway")
        overrides.append(FieldOverride(
            field_name="avg_speed_kph",
            mode="default_typical_profile",
            strategy_description=(
                "Per-row average speed estimated from "
                + ("speed limit (maxspeed)" if "maxspeed" in policy.context_signals_present else "road class (highway)")
                + " using conservative default lookup table."
            ),
            lookup_basis=", ".join(basis_parts) if basis_parts else "fallback_default",
        ))

    if not overrides:
        return RemediationPolicyApplicationResult(
            success=False,
            policy_type=policy.policy_type,
            error="No applicable fields to remediate with the default typical profile.",
        )

    field_names = [item.field_name for item in overrides]
    return RemediationPolicyApplicationResult(
        success=True,
        policy_type=policy.policy_type,
        field_overrides=overrides,
        summary=(
            f"Default typical profile applied to {len(overrides)} field(s): "
            f"{', '.join(field_names)}. "
            f"Estimation basis: {policy.estimation_basis}. "
            f"Confidence: {policy.confidence_label}."
        ),
    )


# ---------------------------------------------------------------------------
# Row-level value resolution (used by executor / macro_emission tool)
# ---------------------------------------------------------------------------

def resolve_traffic_flow_vph(
    *,
    highway: Optional[str] = None,
    lanes: Optional[int] = None,
) -> float:
    """Resolve a single traffic_flow_vph value from road attributes."""
    hw = str(highway or "").strip().lower()
    lane_map = _DEFAULT_FLOW_BY_HIGHWAY_LANES.get(hw)
    if lane_map is None:
        return _DEFAULT_FLOW_FALLBACK
    if lanes is not None and lanes in lane_map:
        return lane_map[lanes]
    return lane_map.get(None, _DEFAULT_FLOW_FALLBACK)


def resolve_avg_speed_kph(
    *,
    maxspeed: Optional[float] = None,
    highway: Optional[str] = None,
) -> float:
    """Resolve a single avg_speed_kph value from road attributes.

    If maxspeed is available, use 85% of posted limit as conservative average.
    Otherwise fall back to highway-class default.
    """
    if maxspeed is not None and maxspeed > 0:
        return round(maxspeed * 0.85, 1)
    hw = str(highway or "").strip().lower()
    return _DEFAULT_SPEED_BY_HIGHWAY.get(hw, _DEFAULT_SPEED_FALLBACK)


# ---------------------------------------------------------------------------
# Public lookup table accessors (for transparency / tracing)
# ---------------------------------------------------------------------------

def get_flow_lookup_table() -> Dict[str, Dict[Optional[int], float]]:
    """Return a copy of the flow lookup table for audit/trace."""
    return {k: dict(v) for k, v in _DEFAULT_FLOW_BY_HIGHWAY_LANES.items()}


def get_speed_lookup_table() -> Dict[str, float]:
    """Return a copy of the speed lookup table for audit/trace."""
    return dict(_DEFAULT_SPEED_BY_HIGHWAY)
