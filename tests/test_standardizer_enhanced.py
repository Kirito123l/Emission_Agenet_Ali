"""Tests for enhanced standardization: season, road_type, detailed results."""

import json

import pytest


class TestStandardizationResult:
    def test_vehicle_detailed_exact(self):
        """Exact vehicle match returns strategy='exact', confidence=1.0."""
        from services.standardizer import get_standardizer

        std = get_standardizer()
        result = std.standardize_vehicle_detailed("Passenger Car")
        assert result.success is True
        assert result.normalized == "Passenger Car"
        assert result.strategy == "exact"
        assert result.confidence == 1.0

    def test_vehicle_detailed_alias(self):
        """Chinese alias returns strategy='alias'."""
        from services.standardizer import get_standardizer

        std = get_standardizer()
        result = std.standardize_vehicle_detailed("小汽车")
        assert result.success is True
        assert result.normalized == "Passenger Car"
        assert result.strategy in ("exact", "alias")

    def test_vehicle_detailed_abstain(self):
        """Unknown input returns success=False with suggestions."""
        from services.standardizer import get_standardizer

        std = get_standardizer()
        result = std.standardize_vehicle_detailed("飞机")
        assert result.success is False
        assert result.strategy == "abstain"
        assert len(result.suggestions) > 0

    def test_vehicle_detailed_to_dict(self):
        """to_dict produces JSON-serializable output."""
        from services.standardizer import get_standardizer

        std = get_standardizer()
        result = std.standardize_vehicle_detailed("公交")
        data = result.to_dict()
        json.dumps(data)
        assert "strategy" in data


class TestSeasonStandardization:
    def test_chinese_summer(self):
        from services.standardizer import get_standardizer

        result = get_standardizer().standardize_season("夏天")
        assert result.success is True
        assert "夏" in result.normalized

    def test_english_winter(self):
        from services.standardizer import get_standardizer

        result = get_standardizer().standardize_season("winter")
        assert result.success is True
        assert "冬" in result.normalized

    def test_empty_returns_default(self):
        from services.standardizer import get_standardizer

        result = get_standardizer().standardize_season("")
        assert result.success is True
        assert result.strategy == "default"

    def test_unknown_returns_default(self):
        from services.standardizer import get_standardizer

        result = get_standardizer().standardize_season("monsoon")
        assert result.success is True


class TestRoadTypeStandardization:
    def test_chinese_freeway(self):
        from services.standardizer import get_standardizer

        result = get_standardizer().standardize_road_type("高速公路")
        assert result.success is True
        assert result.normalized is not None

    def test_english_freeway(self):
        from services.standardizer import get_standardizer

        result = get_standardizer().standardize_road_type("freeway")
        assert result.success is True

    def test_chinese_expressway(self):
        from services.standardizer import get_standardizer

        result = get_standardizer().standardize_road_type("城市快速路")
        assert result.success is True

    def test_empty_returns_default(self):
        from services.standardizer import get_standardizer

        result = get_standardizer().standardize_road_type("")
        assert result.success is True
        assert result.strategy == "default"

    def test_english_local(self):
        from services.standardizer import get_standardizer

        result = get_standardizer().standardize_road_type("local road")
        assert result.success is True


class TestPasquillStabilityMapping:
    """Pasquill A-F letters should map to internal stability codes."""

    @pytest.mark.parametrize(
        "letter,expected_code",
        [
            ("A", "VU"),
            ("B", "U"),
            ("C", "N2"),
            ("D", "N1"),
            ("E", "S"),
            ("F", "VS"),
            ("a", "VU"),
            ("b", "U"),
            ("c", "N2"),
            ("d", "N1"),
            ("e", "S"),
            ("f", "VS"),
        ],
    )
    def test_pasquill_letter(self, letter, expected_code):
        from services.standardizer import get_standardizer

        result = get_standardizer().standardize_stability_class(letter)
        assert result.success is True, f"'{letter}' should map to '{expected_code}', got abstain"
        assert result.normalized == expected_code

    def test_pasquill_class_prefix(self):
        from services.standardizer import get_standardizer

        result = get_standardizer().standardize_stability_class("Pasquill C")
        assert result.success is True
        assert result.normalized == "N2"

    def test_class_prefix(self):
        from services.standardizer import get_standardizer

        result = get_standardizer().standardize_stability_class("class D")
        assert result.success is True
        assert result.normalized == "N1"

    def test_existing_codes_still_work(self):
        from services.standardizer import get_standardizer

        std = get_standardizer()
        for code in ("VS", "S", "N1", "N2", "U", "VU"):
            result = std.standardize_stability_class(code)
            assert result.success is True
            assert result.normalized == code

    def test_existing_aliases_still_work(self):
        from services.standardizer import get_standardizer

        std = get_standardizer()
        result = std.standardize_stability_class("very stable")
        assert result.success is True
        assert result.normalized == "VS"

        result = std.standardize_stability_class("不稳定")
        assert result.success is True
        assert result.normalized == "U"


class TestExecutorStandardizationRecords:
    def test_standardize_returns_tuple(self):
        """_standardize_arguments must return (args, records) tuple."""
        from core.executor import ToolExecutor

        executor = ToolExecutor()
        args, records = executor._standardize_arguments(
            "query_emission_factors",
            {"vehicle_type": "小汽车", "pollutant": "CO2", "model_year": 2020},
        )
        assert isinstance(args, dict)
        assert isinstance(records, list)
        assert len(records) >= 2
        assert args["vehicle_type"] == "Passenger Car"

    def test_season_standardized(self):
        """Season parameter should be standardized."""
        from core.executor import ToolExecutor

        executor = ToolExecutor()
        args, records = executor._standardize_arguments(
            "query_emission_factors",
            {"vehicle_type": "Passenger Car", "season": "冬天", "model_year": 2020},
        )
        assert "冬" in args["season"]
        season_records = [record for record in records if record.get("param") == "season"]
        assert len(season_records) == 1

    def test_road_type_standardized(self):
        """Road type parameter should be standardized."""
        from core.executor import ToolExecutor

        executor = ToolExecutor()
        args, records = executor._standardize_arguments(
            "query_emission_factors",
            {"vehicle_type": "Passenger Car", "road_type": "高速", "model_year": 2020},
        )
        road_records = [record for record in records if record.get("param") == "road_type"]
        assert len(road_records) == 1
        assert road_records[0]["success"] is True
        assert args["road_type"] == "高速公路"

    def test_abstain_raises_with_suggestions(self):
        """Unknown vehicle should raise StandardizationError with suggestions."""
        from core.executor import ToolExecutor, StandardizationError

        executor = ToolExecutor()
        with pytest.raises(StandardizationError) as exc_info:
            executor._standardize_arguments(
                "query_emission_factors",
                {"vehicle_type": "飞机", "model_year": 2020},
            )
        assert len(exc_info.value.suggestions) > 0
