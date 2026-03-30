"""Tests for cross-constraint validation."""

from __future__ import annotations

import pytest

from services.cross_constraints import CrossConstraintValidator
from services.standardization_engine import BatchStandardizationError, StandardizationEngine


class TestCrossConstraintValidator:
    def test_valid_combination(self):
        validator = CrossConstraintValidator()
        result = validator.validate(
            {
                "vehicle_type": "Passenger Car",
                "road_type": "快速路",
            }
        )
        assert result.all_valid
        assert len(result.violations) == 0

    def test_blocked_combination(self):
        validator = CrossConstraintValidator()
        result = validator.validate(
            {
                "vehicle_type": "Motorcycle",
                "road_type": "高速公路",
            }
        )
        assert result.all_valid is False
        assert len(result.violations) == 1
        assert result.violations[0].violation_type == "blocked"

    def test_consistency_warning(self):
        validator = CrossConstraintValidator()
        result = validator.validate(
            {
                "season": "冬季",
                "meteorology": "urban_summer_day",
            }
        )
        assert result.all_valid is True
        assert len(result.warnings) == 1

    def test_missing_params_skip_validation(self):
        validator = CrossConstraintValidator()
        result = validator.validate(
            {
                "vehicle_type": "Motorcycle",
            }
        )
        assert result.all_valid is True

    def test_empty_params(self):
        validator = CrossConstraintValidator()
        result = validator.validate({})
        assert result.all_valid is True


class TestCrossConstraintEngineIntegration:
    def test_standardize_batch_raises_on_cross_constraint_violation(self):
        engine = StandardizationEngine({"llm_enabled": False, "enable_cross_constraint_validation": True})

        with pytest.raises(BatchStandardizationError) as exc_info:
            engine.standardize_batch(
                {
                    "vehicle_type": "Motorcycle",
                    "road_type": "高速公路",
                },
                tool_name="query_emission_factors",
            )

        assert exc_info.value.negotiation_eligible is True
        assert exc_info.value.trigger_reason == "cross_constraint_violation:vehicle_road_compatibility"
        assert any(record.get("record_type") == "cross_constraint_violation" for record in exc_info.value.records)

    def test_standardize_batch_records_warning_without_blocking(self):
        engine = StandardizationEngine({"llm_enabled": False, "enable_cross_constraint_validation": True})

        standardized, records = engine.standardize_batch(
            {
                "season": "冬季",
                "meteorology": "urban_summer_day",
            },
            tool_name="calculate_dispersion",
        )

        assert standardized["season"] == "冬季"
        assert standardized["meteorology"] == "urban_summer_day"
        warning_records = [record for record in records if record.get("record_type") == "cross_constraint_warning"]
        assert len(warning_records) == 1
        assert engine.get_last_constraint_trace()["warnings"]

    def test_standardize_batch_can_disable_cross_constraint_validation(self):
        engine = StandardizationEngine({"llm_enabled": False, "enable_cross_constraint_validation": False})

        standardized, records = engine.standardize_batch(
            {
                "vehicle_type": "Motorcycle",
                "road_type": "高速公路",
            },
            tool_name="query_emission_factors",
        )

        assert standardized["vehicle_type"] == "Motorcycle"
        assert standardized["road_type"] == "高速公路"
        assert not any(record.get("record_type", "").startswith("cross_constraint_") for record in records)
