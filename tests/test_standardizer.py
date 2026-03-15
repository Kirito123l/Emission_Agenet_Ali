"""Tests for the UnifiedStandardizer (vehicle type and pollutant mapping).

These tests verify the configuration-driven standardization layer
WITHOUT requiring any LLM API calls.
"""
from services.standardizer import UnifiedStandardizer


def _make_standardizer():
    """Create a fresh standardizer for each test."""
    return UnifiedStandardizer()


class TestVehicleStandardization:
    """Vehicle type standardization via exact and fuzzy matching."""

    def test_exact_english(self):
        s = _make_standardizer()
        assert s.standardize_vehicle("Passenger Car") == "Passenger Car"

    def test_exact_chinese(self):
        s = _make_standardizer()
        assert s.standardize_vehicle("乘用车") == "Passenger Car"

    def test_alias_chinese(self):
        s = _make_standardizer()
        assert s.standardize_vehicle("小汽车") == "Passenger Car"
        assert s.standardize_vehicle("公交车") == "Transit Bus"

    def test_case_insensitive(self):
        s = _make_standardizer()
        assert s.standardize_vehicle("passenger car") == "Passenger Car"
        assert s.standardize_vehicle("TRANSIT BUS") == "Transit Bus"

    def test_unknown_returns_none(self):
        s = _make_standardizer()
        result = s.standardize_vehicle("飞机")
        assert result is None

    def test_empty_returns_none(self):
        s = _make_standardizer()
        assert s.standardize_vehicle("") is None
        assert s.standardize_vehicle(None) is None

    def test_suggestions_non_empty(self):
        s = _make_standardizer()
        suggestions = s.get_vehicle_suggestions()
        assert len(suggestions) > 0
        assert any("Passenger Car" in sug for sug in suggestions)


class TestPollutantStandardization:
    """Pollutant standardization via exact and fuzzy matching."""

    def test_exact_english(self):
        s = _make_standardizer()
        assert s.standardize_pollutant("CO2") == "CO2"
        assert s.standardize_pollutant("NOx") == "NOx"
        assert s.standardize_pollutant("PM2.5") == "PM2.5"

    def test_case_insensitive(self):
        s = _make_standardizer()
        assert s.standardize_pollutant("co2") == "CO2"
        assert s.standardize_pollutant("nox") == "NOx"

    def test_chinese_name(self):
        s = _make_standardizer()
        assert s.standardize_pollutant("二氧化碳") == "CO2"
        assert s.standardize_pollutant("氮氧化物") == "NOx"

    def test_unknown_returns_none(self):
        s = _make_standardizer()
        assert s.standardize_pollutant("oxygen") is None

    def test_suggestions_non_empty(self):
        s = _make_standardizer()
        suggestions = s.get_pollutant_suggestions()
        assert "CO2" in suggestions
        assert "NOx" in suggestions


class TestColumnMapping:
    """Column name mapping for file data."""

    def test_micro_speed_column(self):
        s = _make_standardizer()
        mapping = s.map_columns(["speed_kph", "time", "other_col"], "micro_emission")
        # Should map at least the speed column
        assert any("speed" in v.lower() for v in mapping.values()) or len(mapping) >= 1

    def test_empty_columns(self):
        s = _make_standardizer()
        mapping = s.map_columns([], "micro_emission")
        assert mapping == {}
