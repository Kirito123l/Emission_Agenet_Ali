"""
Cross-constraint validation for standardized parameters.

Ensures parameter combinations are compatible after individual parameter
standardization has completed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


logger = logging.getLogger(__name__)

CONSTRAINTS_FILE = Path(__file__).parent.parent / "config" / "cross_constraints.yaml"
PARAM_ALIASES: Dict[str, tuple[str, ...]] = {
    "pollutant": ("pollutants",),
    "pollutants": ("pollutant",),
}


@dataclass
class CrossConstraintViolation:
    """A single cross-constraint violation or warning."""

    constraint_name: str
    description: str
    param_a_name: str
    param_a_value: str
    param_b_name: str
    param_b_value: Any
    violation_type: str
    reason: str
    suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "constraint_name": self.constraint_name,
            "description": self.description,
            "param_a": f"{self.param_a_name}={self.param_a_value}",
            "param_b": f"{self.param_b_name}={self.param_b_value}",
            "violation_type": self.violation_type,
            "reason": self.reason,
            "suggestions": list(self.suggestions),
        }


@dataclass
class CrossConstraintResult:
    """Result of cross-constraint validation."""

    all_valid: bool
    violations: List[CrossConstraintViolation] = field(default_factory=list)
    warnings: List[CrossConstraintViolation] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "all_valid": self.all_valid,
            "violations": [violation.to_dict() for violation in self.violations],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


class CrossConstraintValidator:
    """Validate configured cross-parameter constraints."""

    def __init__(self, constraints_path: Optional[Path] = None):
        self._constraints_path = constraints_path or CONSTRAINTS_FILE
        self._constraints = self._load_constraints()

    def _load_constraints(self) -> List[Dict[str, Any]]:
        if not self._constraints_path.exists():
            logger.warning("Cross-constraints file not found: %s", self._constraints_path)
            return []

        with open(self._constraints_path, "r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        return list(payload.get("constraints", []) or [])

    def validate(
        self,
        standardized_params: Dict[str, Any],
        *,
        tool_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> CrossConstraintResult:
        violations: List[CrossConstraintViolation] = []
        warnings: List[CrossConstraintViolation] = []
        validation_context = dict(context or {})
        if tool_name:
            validation_context.setdefault("tool_name", tool_name)

        for constraint in self._constraints:
            param_a_name = constraint.get("param_a")
            param_b_name = constraint.get("param_b")
            constraint_type = constraint.get("type")

            if not param_a_name or not param_b_name or not constraint_type:
                continue

            val_a = self._resolve_param_value(
                str(param_a_name),
                standardized_params,
                validation_context,
            )
            val_b = self._resolve_param_value(
                str(param_b_name),
                standardized_params,
                validation_context,
            )
            if val_a is None or val_b is None:
                continue

            rules = constraint.get("rules", {}) or {}
            val_a_rules = rules.get(str(val_a))
            if not isinstance(val_a_rules, dict):
                continue

            if constraint_type == "blocked_combinations":
                violations.extend(
                    self._collect_matches(
                        constraint=constraint,
                        val_a=val_a,
                        val_b=val_b,
                        val_a_rules=val_a_rules,
                        field_name="blocked",
                        default_violation_type="blocked",
                        default_reason=f"{val_a} 与 {val_b} 不兼容",
                    )
                )
            elif constraint_type == "consistency_warning":
                warnings.extend(
                    self._collect_matches(
                        constraint=constraint,
                        val_a=val_a,
                        val_b=val_b,
                        val_a_rules=val_a_rules,
                        field_name="inconsistent",
                        default_violation_type="inconsistent",
                        default_reason=f"{val_a} 与 {val_b} 可能不一致",
                    )
                )
            elif constraint_type == "conditional_warning":
                warnings.extend(
                    self._collect_matches(
                        constraint=constraint,
                        val_a=val_a,
                        val_b=val_b,
                        val_a_rules=val_a_rules,
                        field_name="warned",
                        default_violation_type="warning",
                        default_reason=f"{val_a} 与 {val_b} 的组合需要谨慎解释",
                    )
                )

        return CrossConstraintResult(
            all_valid=len(violations) == 0,
            violations=violations,
            warnings=warnings,
        )

    def _resolve_param_value(
        self,
        param_name: str,
        standardized_params: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Any:
        candidate_names = (param_name, *PARAM_ALIASES.get(param_name, ()))
        for source in (standardized_params, context):
            for candidate_name in candidate_names:
                if candidate_name not in source:
                    continue
                value = source.get(candidate_name)
                if value is None:
                    continue
                if param_name == "pollutants" and not isinstance(value, list):
                    return [value]
                return value
        return None

    def _collect_matches(
        self,
        *,
        constraint: Dict[str, Any],
        val_a: Any,
        val_b: Any,
        val_a_rules: Dict[str, Any],
        field_name: str,
        default_violation_type: str,
        default_reason: str,
    ) -> List[CrossConstraintViolation]:
        targets = {str(item) for item in val_a_rules.get(field_name, []) if item is not None}
        if not targets:
            return []

        matched_values = (
            [item for item in val_b if str(item) in targets]
            if isinstance(val_b, (list, tuple, set))
            else [val_b] if str(val_b) in targets else []
        )
        if not matched_values:
            return []

        reason = str(val_a_rules.get("reason", default_reason))
        suggestions = [str(item) for item in val_a_rules.get("suggestions", []) if item]
        violation_type = str(
            val_a_rules.get("violation_type")
            or constraint.get("violation_type")
            or default_violation_type
        )

        return [
            CrossConstraintViolation(
                constraint_name=str(constraint.get("name", "unknown_constraint")),
                description=str(constraint.get("description", "")),
                param_a_name=str(constraint.get("param_a", "")),
                param_a_value=str(val_a),
                param_b_name=str(constraint.get("param_b", "")),
                param_b_value=item,
                violation_type=violation_type,
                reason=reason,
                suggestions=suggestions,
            )
            for item in matched_values
        ]


_validator: Optional[CrossConstraintValidator] = None


def get_cross_constraint_validator() -> CrossConstraintValidator:
    """Return a singleton cross-constraint validator."""
    global _validator
    if _validator is None:
        _validator = CrossConstraintValidator()
    return _validator
