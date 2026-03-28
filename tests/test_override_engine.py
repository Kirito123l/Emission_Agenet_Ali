"""Tests for the scenario override engine."""

from __future__ import annotations

from tools.override_engine import apply_overrides, describe_overrides, validate_overrides


def make_links():
    return [
        {
            "link_id": "L1",
            "avg_speed_kph": 80.0,
            "traffic_flow_vph": 1000.0,
            "link_length_km": 1.0,
        },
        {
            "link_id": "L2",
            "avg_speed_kph": 50.0,
            "traffic_flow_vph": 800.0,
            "link_length_km": 0.5,
        },
    ]


class TestValidateOverrides:
    def test_valid_set_override(self):
        assert validate_overrides([{"column": "avg_speed_kph", "value": 30}]) == []

    def test_valid_multiply_override(self):
        assert validate_overrides(
            [{"column": "traffic_flow_vph", "transform": "multiply", "factor": 0.5}]
        ) == []

    def test_valid_add_override(self):
        assert validate_overrides(
            [{"column": "traffic_flow_vph", "transform": "add", "offset": 120}]
        ) == []

    def test_valid_conditional_override(self):
        assert validate_overrides(
            [
                {
                    "column": "avg_speed_kph",
                    "value": 60,
                    "where": {"column": "avg_speed_kph", "op": ">", "value": 60},
                }
            ]
        ) == []

    def test_valid_fleet_mix_override(self):
        assert validate_overrides(
            [
                {
                    "column": "fleet_mix",
                    "value": {
                        "Passenger Car": 70,
                        "Transit Bus": 10,
                        "Passenger Truck": 10,
                        "Light Commercial Truck": 5,
                        "Combination Long-haul Truck": 5,
                    },
                }
            ]
        ) == []

    def test_invalid_column(self):
        errors = validate_overrides([{"column": "temperature", "value": 30}])
        assert "not overridable" in errors[0]

    def test_out_of_range_value(self):
        errors = validate_overrides([{"column": "avg_speed_kph", "value": 500}])
        assert "out of range" in errors[0]

    def test_negative_speed(self):
        errors = validate_overrides([{"column": "avg_speed_kph", "value": -1}])
        assert "out of range" in errors[0]

    def test_fleet_mix_sum_warning(self):
        errors = validate_overrides(
            [{"column": "fleet_mix", "value": {"Passenger Car": 50, "Transit Bus": 10}}]
        )
        assert "expected about 100%" in errors[0]

    def test_unknown_fleet_category(self):
        errors = validate_overrides(
            [{"column": "fleet_mix", "value": {"Electric Car": 100}}]
        )
        assert "unknown fleet categories" in errors[0]

    def test_invalid_transform(self):
        errors = validate_overrides(
            [{"column": "avg_speed_kph", "transform": "divide", "value": 30}]
        )
        assert "unknown transform" in errors[0]

    def test_missing_factor(self):
        errors = validate_overrides(
            [{"column": "avg_speed_kph", "transform": "multiply"}]
        )
        assert "requires factor" in errors[0]

    def test_negative_multiply_factor(self):
        errors = validate_overrides(
            [{"column": "avg_speed_kph", "transform": "multiply", "factor": -1}]
        )
        assert "factor must be positive" in errors[0]

    def test_invalid_condition_operator(self):
        errors = validate_overrides(
            [
                {
                    "column": "avg_speed_kph",
                    "value": 30,
                    "where": {"column": "avg_speed_kph", "op": "contains", "value": 1},
                }
            ]
        )
        assert "where.op" in errors[0]


class TestApplyOverrides:
    def test_set_all_speeds(self):
        updated, summaries = apply_overrides(
            make_links(),
            [{"column": "avg_speed_kph", "value": 30}],
        )
        assert [row["avg_speed_kph"] for row in updated] == [30.0, 30.0]
        assert "设为 30" in summaries[0]

    def test_multiply_speeds(self):
        updated, _ = apply_overrides(
            make_links(),
            [{"column": "avg_speed_kph", "transform": "multiply", "factor": 0.8}],
        )
        assert updated[0]["avg_speed_kph"] == 64.0
        assert updated[1]["avg_speed_kph"] == 40.0

    def test_add_offset(self):
        updated, _ = apply_overrides(
            make_links(),
            [{"column": "traffic_flow_vph", "transform": "add", "offset": 200}],
        )
        assert updated[0]["traffic_flow_vph"] == 1200.0
        assert updated[1]["traffic_flow_vph"] == 1000.0

    def test_conditional_set(self):
        updated, _ = apply_overrides(
            make_links(),
            [
                {
                    "column": "avg_speed_kph",
                    "value": 60,
                    "where": {"column": "avg_speed_kph", "op": ">", "value": 60},
                }
            ],
        )
        assert updated[0]["avg_speed_kph"] == 60.0
        assert updated[1]["avg_speed_kph"] == 50.0

    def test_conditional_link_id(self):
        updated, _ = apply_overrides(
            make_links(),
            [
                {
                    "column": "avg_speed_kph",
                    "value": 30,
                    "where": {"column": "link_id", "op": "in", "value": ["L2"]},
                }
            ],
        )
        assert updated[0]["avg_speed_kph"] == 80.0
        assert updated[1]["avg_speed_kph"] == 30.0

    def test_fleet_mix_override(self):
        updated, _ = apply_overrides(
            make_links(),
            [
                {
                    "column": "fleet_mix",
                    "value": {
                        "Passenger Car": 70,
                        "Transit Bus": 10,
                        "Passenger Truck": 10,
                        "Light Commercial Truck": 5,
                        "Combination Long-haul Truck": 5,
                    },
                }
            ],
        )
        assert updated[0]["fleet_mix"]["Passenger Car"] == 70.0
        assert updated[1]["fleet_mix"]["Transit Bus"] == 10.0

    def test_fleet_mix_normalization(self):
        updated, _ = apply_overrides(
            make_links(),
            [
                {
                    "column": "fleet_mix",
                    "value": {
                        "Passenger Car": 35,
                        "Transit Bus": 35,
                        "Passenger Truck": 15,
                        "Light Commercial Truck": 10,
                        "Combination Long-haul Truck": 10,
                    },
                }
            ],
        )
        total = sum(updated[0]["fleet_mix"].values())
        assert round(total, 4) == 100.0

    def test_bounds_clamping(self):
        updated, summaries = apply_overrides(
            make_links(),
            [{"column": "avg_speed_kph", "transform": "multiply", "factor": 10}],
        )
        assert updated[0]["avg_speed_kph"] == 200.0
        assert updated[1]["avg_speed_kph"] == 200.0
        assert any("被裁剪" in item for item in summaries)

    def test_original_not_mutated(self):
        original = make_links()
        updated, _ = apply_overrides(
            original,
            [{"column": "avg_speed_kph", "value": 30}],
        )
        assert original[0]["avg_speed_kph"] == 80.0
        assert updated[0]["avg_speed_kph"] == 30.0

    def test_multiple_overrides_sequential(self):
        updated, _ = apply_overrides(
            make_links(),
            [
                {"column": "traffic_flow_vph", "transform": "multiply", "factor": 0.5},
                {"column": "avg_speed_kph", "value": 30},
            ],
        )
        assert updated[0]["traffic_flow_vph"] == 500.0
        assert updated[0]["avg_speed_kph"] == 30.0


class TestDescribeOverrides:
    def test_human_readable_description(self):
        description = describe_overrides(
            [
                {"column": "avg_speed_kph", "value": 30},
                {
                    "column": "traffic_flow_vph",
                    "transform": "multiply",
                    "factor": 0.5,
                    "where": {"column": "link_id", "op": "in", "value": ["L1"]},
                },
            ]
        )
        assert "avg_speed_kph" in description
        assert "link_id in ['L1']" in description

